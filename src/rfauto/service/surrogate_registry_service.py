"""代理模型注册表服务面（RB-ML-1，sa_specs2 §六；JSON 进出，规则 4）。

三消费面（spec §6.2-2）：
- ①战役启动：``surrogate_registry_champion_points``（champion→blob 反序
  列化→确定性近优点搜索）+ ``run_optimization_with_registry_warm_start``
  （把近优点并入 run_optimization 的 warm_start 通道——相似度门/排队全在
  既有 stage-1 内，零内核侵入；#273 教训：注入点过同款判据=warm_start
  门，不绕行）；``tune --warm-start-registry/--no-warm-start-registry``
  三态开关经 ``resolve_warm_start_registry_flag``（#277 bool|None 形态，
  缺省 None=env/配置裁决）。
- ②锚漂移联动：``mark_stale_from_anchor_drift``——消费
  ``core.anchor_drift_spc.anchor_drift_spc_report`` 既有判定（verdict=
  drifted 才标），同 template_family 全版本 stale+stale_reason=锚指针；
  stale 模型被 champion 读取面拒用（kernel 守卫）。
- ③跨战役检索：``surrogate_registry_query``——family/channel/status/
  stale 过滤→版本清单+heldout 误差；可选 lake 同库只读 join
  （runs_lake_index.run_id↔trained_run_ids，meta.git_sha 读通=血缘第三跳）。

配对裁判（spec §6.3-2，#273 channel 口径）：``judge_registry_warm_start_
benefit``——注入 vs 不注入首 trial cost 中位改善 ≥30% 或达标 trial 数
减少；无改善如实 FAIL，verdict 带 channel 字段。

数值纪律（铁律 7）：近优点 cost/champion 预测/heldout 全部出自确定性
代理模型与 SpecEvaluator 内核；本模块只编排、过滤、归并，不产生物理数字。
MCP/CLI：v1 零接线（spec §6.2-4；tune 三态开关除外，不新增叶计数零）。
"""

from __future__ import annotations

import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

from rfauto.optimization.model_registry import (
    ModelRegistry,
    canonical_key,
    feature_set_fingerprint,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "judge_registry_warm_start_benefit",
    "mark_stale_from_anchor_drift",
    "resolve_warm_start_registry_flag",
    "run_optimization_with_registry_warm_start",
    "surrogate_registry_champion_points",
    "surrogate_registry_mark_stale",
    "surrogate_registry_query",
    "surrogate_registry_set_status",
    "surrogate_registry_upsert",
]

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})

#: 判据阈值（spec §6.3-2：首 trial cost 中位改善 ≥30% 或达标 trial 数减少）
BENEFIT_THRESHOLD_PCT_DEFAULT = 30.0


# ─── 三态开关解析（#277：显式 > env > 配置 > False）──────────────────────────


def resolve_warm_start_registry_flag(
    explicit: bool | None, *,
    environ: dict[str, str] | None = None,
) -> bool:
    """tune 三态开关裁决：显式参数 > ``RFAUTO_WARM_START_REGISTRY`` env >
    configs/settings.yaml ``tune.warm_start_registry`` > False（缺省关）。

    缺省关=旧环境行为逐字节不变（spec §6.3-6 零退化钉）；配置读取失败
    （文件缺失/键缺失/解析错）一律按 False，不阻塞 tune 主路径。
    """
    if explicit is not None:
        return bool(explicit)
    env = os.environ if environ is None else environ
    raw = str(env.get("RFAUTO_WARM_START_REGISTRY", "")).strip().lower()
    if raw:
        return raw in _TRUE_STRINGS
    try:
        import yaml

        cfg_path = Path("configs") / "settings.yaml"
        if not cfg_path.exists():
            return False
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        val = ((cfg.get("tune") or {}).get("warm_start_registry"))
        if isinstance(val, bool):
            return val
    except Exception:  # 配置读取失败不阻塞（#105）
        return False
    return False


def _registry(paths: dict[str, Any] | None) -> ModelRegistry:
    paths = paths or {}
    return ModelRegistry(
        registry_path=paths.get("registry_path"),
        store_dir=paths.get("store_dir"))


# ─── 消费面③：注册/检索 ──────────────────────────────────────────────────────


def surrogate_registry_upsert(payload: dict[str, Any]) -> dict[str, Any]:
    """注册训练产物新版本（JSON 进出；heldout 强制，spec §6.2-3）。

    payload 必填：template_family / channel / heldout{metric,value,n_points} /
    model_path（pickle 文件路径——blob 字节源）。可选：feature_names（有序）
    或 feature_set_fingerprint（二选一，缺一不可）、preprocessing、
    hyperparams、trained_run_ids、render_commit、promote、version、
    registry_path、store_dir。
    """
    payload = payload or {}
    try:
        family = str(payload.get("template_family") or "")
        channel = str(payload.get("channel") or "")
        if not family or not channel:
            return error_envelope(["template_family / channel 必填"])
        fingerprint = str(payload.get("feature_set_fingerprint") or "")
        if not fingerprint:
            names = payload.get("feature_names")
            if not isinstance(names, list) or not names:
                return error_envelope(
                    ["feature_names（有序列表）或 feature_set_fingerprint 必填"])
            fingerprint = feature_set_fingerprint(names,
                                                  payload.get("preprocessing"))
        model_path = payload.get("model_path")
        if not model_path or not Path(model_path).is_file():
            return error_envelope([f"model_path 不存在: {model_path}"])
        data = Path(model_path).read_bytes()
        key = canonical_key(family, channel, fingerprint)
        reg = _registry(payload)
        res = reg.upsert(
            key=key,
            model_bytes=data,
            heldout=payload.get("heldout"),
            hyperparams=payload.get("hyperparams"),
            trained_run_ids=payload.get("trained_run_ids"),
            render_commit=payload.get("render_commit"),
            promote=bool(payload.get("promote", False)),
            version=payload.get("version"),
        )
        res.setdefault("key", key)
        return ok_envelope(**res)
    except ValueError as exc:
        return error_envelope([f"{exc}"])
    except Exception as exc:  # 注册失败不阻塞调用方（#105，如实报错）
        return error_envelope([f"注册失败: {exc}"])


def surrogate_registry_query(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """版本检索（family/channel/status/stale 过滤 + 可选 lake join 血缘）。"""
    payload = payload or {}
    reg = _registry(payload)
    try:
        rows = reg.query(
            template_family=payload.get("template_family"),
            channel=payload.get("channel"),
            status=payload.get("status"),
            stale=payload.get("stale"),
        )
    except ValueError as exc:
        return error_envelope([f"{exc}"])

    if payload.get("verify_blob"):
        for row in rows:
            check = reg.load_entry_model(row)
            row["blob_ok"] = bool(check.get("ok"))
            if not check.get("ok"):
                row["blob_reason"] = check.get("reason")

    join_info: dict[str, Any] | None = None
    if payload.get("lake_join"):
        join_info = _lake_join(
            rows,
            db_path=payload.get("db_path"),
            runs_dir=payload.get("runs_dir", "runs"))
        for row in rows:
            row["lake_runs"] = (join_info.get("by_run") or {}).get(
                row.get("model_blob_sha256") or "", {}).get(
                _row_run_key(row), [])

    return ok_envelope(rows=rows, n_rows=len(rows), lake_join=join_info,
                       registry_path=str(reg.registry_path))


def _row_run_key(row: dict[str, Any]) -> str:
    return "\x00".join([
        str(row.get("template_family")), str(row.get("channel")),
        str(row.get("feature_set_fingerprint")), str(row.get("version"))])


def _lake_join(
    rows: list[dict[str, Any]],
    *,
    db_path: str | Path | None,
    runs_dir: str | Path,
) -> dict[str, Any]:
    """runs_lake_index 只读 join：trained_run_ids→行（path/study）→
    meta.git_sha 读通（血缘第三跳，spec §6.3-1）。

    库缺失/duckdb 缺装不阻塞查询主路径（ok 保持 True，join_skipped 如实）。
    """
    wanted: set[str] = set()
    for row in rows:
        wanted |= {str(r) for r in (row.get("trained_run_ids") or [])}
    if not wanted:
        return {"joined": False, "note": "无 trained_run_ids，join 跳过",
                "by_run": {}}
    try:
        import duckdb
    except ImportError as exc:
        return {"joined": False, "note": f"duckdb 未安装: {exc}",
                "by_run": {}}
    db = Path(db_path) if db_path else Path("runs") / ".lake_index.duckdb"
    if not db.exists():
        return {"joined": False,
                "note": f"湖索引库不存在（先 lake index）: {db}",
                "by_run": {}}
    try:
        con = duckdb.connect(str(db), read_only=True)
    except Exception as exc:
        return {"joined": False, "note": f"索引库连接失败: {exc}",
                "by_run": {}}
    hit: dict[str, dict[str, Any]] = {}
    try:
        for rid in sorted(wanted):
            # 值走参数绑定，永不拼进 SQL 文本（防注入面不倒退）
            cur = con.execute(
                "SELECT run_id, path, template, adapter, study "
                "FROM runs_lake_index WHERE run_id = ? LIMIT 1", [rid])
            rec = cur.fetchone()
            if rec:
                hit[rid] = {"run_id": rec[0], "path": rec[1],
                            "template": rec[2], "adapter": rec[3],
                            "study": rec[4]}
    finally:
        con.close()

    # 第三跳：run 目录 meta.git_sha 读通（lake 表无 git_sha 列，读原 meta）
    root = Path(runs_dir)
    for info in hit.values():
        meta = _read_run_meta(root / str(info.get("path") or ""))
        info["git_sha"] = meta.get("git_sha") if meta else None

    by_run: dict[str, Any] = {}
    for row in rows:
        runs = [hit[str(r)] for r in (row.get("trained_run_ids") or [])
                if str(r) in hit]
        by_run.setdefault(row.get("model_blob_sha256"), {})[
            _row_run_key(row)] = runs
    return {"joined": True, "db_path": str(db), "n_matched": len(hit),
            "n_wanted": len(wanted), "by_run": by_run}


def _read_run_meta(run_dir: Path) -> dict[str, Any] | None:
    for name in ("meta.json", "run_meta.json"):
        p = run_dir / name
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else None
            except Exception:
                return None
    return None


# ─── 消费面②：锚漂移联动 ─────────────────────────────────────────────────────


def surrogate_registry_mark_stale(payload: dict[str, Any]) -> dict[str, Any]:
    """直接标记族级 stale（payload：template_family / stale_reason）。"""
    payload = payload or {}
    family = str(payload.get("template_family") or "")
    if not family:
        return error_envelope(["template_family 必填"])
    reason = str(payload.get("stale_reason") or "manual_mark_stale")
    try:
        res = _registry(payload).mark_family_stale(family, reason)
    except Exception as exc:
        return error_envelope([f"标记失败: {exc}"])
    return ok_envelope(**res, action="marked_stale",
                       revalidation={"required": True,
                                     "how": "surrogate_registry_set_status "
                                            "promote（复验通过后显式晋升，清 stale）"})


def mark_stale_from_anchor_drift(
    template_family: str,
    drift_report: dict[str, Any] | None,
    *,
    anchor_id: str | None = None,
    registry_path: str | Path | None = None,
    store_dir: str | Path | None = None,
) -> dict[str, Any]:
    """锚漂移→模型 stale 联动钩子（spec §6.2-2②）。

    消费 ``core.anchor_drift_spc`` 既有判定：verdict == "drifted"（≥2 证据
    线成立）才把同 template_family 全版本标 stale；warning/stable/
    insufficient 如实不动（单线命中上限 warning，保守不升级是 SPC 内核
    既有语义）。stale_reason=锚指针（verdict/anchor_id/fired_lines）。
    """
    report = drift_report or {}
    verdict = str(report.get("verdict") or "unknown")
    if verdict != "drifted":
        return ok_envelope(
            action="noop", n_marked=0, verdict=verdict,
            note="非 drifted 判定不标 stale（保守不升级，SPC 既有语义）")
    fired = ",".join(str(x) for x in (report.get("fired_lines") or []))
    reason = f"anchor_drift:{verdict}:{anchor_id or 'na'}:{fired}"
    reg = ModelRegistry(registry_path=registry_path, store_dir=store_dir)
    try:
        res = reg.mark_family_stale(str(template_family), reason)
    except Exception as exc:
        return error_envelope([f"stale 联动失败: {exc}"])
    return ok_envelope(
        action="marked_stale", verdict=verdict, **res,
        revalidation={"required": True,
                      "how": "复验 run 通过后显式 promote（clear_stale）"})


def surrogate_registry_set_status(payload: dict[str, Any]) -> dict[str, Any]:
    """版本状态机（promote/retire；promote 清 stale=复验通过语义）。"""
    payload = payload or {}
    try:
        family = str(payload.get("template_family") or "")
        channel = str(payload.get("channel") or "")
        fingerprint = str(payload.get("feature_set_fingerprint") or "")
        if not fingerprint:
            names = payload.get("feature_names")
            if not isinstance(names, list) or not names:
                return error_envelope(
                    ["feature_names 或 feature_set_fingerprint 必填"])
            fingerprint = feature_set_fingerprint(names,
                                                  payload.get("preprocessing"))
        key = canonical_key(family, channel, fingerprint)
        status = str(payload.get("status") or "")
        version = payload.get("version")
        if version is None:
            return error_envelope(["version 必填"])
        res = _registry(payload).set_version_status(
            key, int(version), status,
            clear_stale=bool(payload.get("clear_stale", status == "champion")))
    except (ValueError, TypeError) as exc:
        return error_envelope([f"{exc}"])
    except Exception as exc:
        return error_envelope([f"状态更新失败: {exc}"])
    if not res.get("ok"):
        return error_envelope([f"{res.get('reason')}: "
                               f"{res.get('detail', '')}"], entry=res)
    return ok_envelope(**res)


# ─── 消费面①：champion 近优点 → warm-start 注入 ──────────────────────────────


def surrogate_registry_champion_points(
    recipe_path: str | Path,
    adapter_name: str,
    *,
    top_k: int = 3,
    n_probe: int = 128,
    n_refine_starts: int = 4,
    refine_iters: int = 24,
    seed: int = 0,
    registry_path: str | Path | None = None,
    store_dir: str | Path | None = None,
) -> dict[str, Any]:
    """champion（同键非 stale）→ blob 反序列化 → 确定性近优参数点。

    键指纹=当前配方参数名+顺序（读取面按指纹精确匹配，schema 演进自然
    失配不模糊复用）。搜索=LHS 探针（固定 seed）→ 模型预测 →
    SpecEvaluator 转 cost → 顶部起点确定性模式搜索细化——全程确定性
    （同输入同输出，可复现红线 C4）；数字全部出自 champion 模型内核。

    Returns:
        ``{"ok": True, "points": [{"params", "cost"}], "champion": {...},
        "key": {...}, "n_probe_evaluated"}``；
        拒用形态：reason=no_champion / stale（含 stale_reason）/
        blob_sha256_mismatch / blob_missing / unpickle_failed / 空参数空间。
    """
    import yaml

    from rfauto.core.objectives import Objective, SpecEvaluator

    path = Path(recipe_path)
    if not path.exists():
        return error_envelope(f"配方不存在: {path}",
                              reason="recipe_missing",
                              detail=f"配方不存在: {path}")
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f) or {}

    from rfauto.optimization.optimizer import extract_param_ranges

    ranges = extract_param_ranges(recipe_data)
    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    if not ranges:
        return error_envelope("参数空间为空：配方无 optimization.params 可采样参数",
                              reason="empty_param_space")
    if not objectives:
        return error_envelope("目标为空：配方无 objectives，无从评估 cost",
                              reason="empty_objectives")
    family = str(recipe_data.get("model") or "")
    if not family:
        return error_envelope("缺模板族：配方无 model 字段",
                              reason="missing_template_family")

    fingerprint = feature_set_fingerprint(list(ranges.keys()))
    key = canonical_key(family, str(adapter_name), fingerprint)
    reg = ModelRegistry(registry_path=registry_path, store_dir=store_dir)
    ch = reg.champion(key)
    if not ch.get("ok"):
        return error_envelope(
            str(ch.get("detail") or ch.get("reason") or "champion 不可用"),
            reason=ch.get("reason"), stale_reason=ch.get("stale_reason"),
            detail=ch.get("detail"), key=key)
    entry = ch["entry"]
    loaded = reg.load_entry_model(entry)
    if not loaded.get("ok"):
        return error_envelope(
            str(loaded.get("detail") or loaded.get("reason")
                or "champion 模型加载失败"),
            reason=loaded.get("reason"), detail=loaded.get("detail"), key=key)
    model = loaded["model"]

    bounds = {k: (float(v["low"]), float(v["high"]))
              for k, v in ranges.items()}
    names = list(bounds.keys())

    def _pred_cost(params: dict[str, float]) -> float | None:
        try:
            metrics = model.predict(dict(params))
            return float(SpecEvaluator.evaluate_objectives(metrics, objectives))
        except Exception:
            return None  # 单点预测失败跳过（best-effort #105）

    from rfauto.optimization.sample_design import lhs_points

    probe = lhs_points(bounds, max(int(n_probe), 8), seed=int(seed))
    scored: list[tuple[float, dict[str, float]]] = []
    for pt in probe["points"]:
        c = _pred_cost(pt)
        if c is not None and math.isfinite(c):
            scored.append((c, pt))
    if not scored:
        return error_envelope(
            "champion 模型探针点全部预测失败（无有效 cost）",
            reason="probe_all_failed", key=key)
    scored.sort(key=lambda t: t[0])

    refined: list[tuple[float, dict[str, float]]] = []
    for _, start in scored[:max(1, int(n_refine_starts))]:
        refined.append(_pattern_search(_pred_cost, start, bounds,
                                       iters=int(refine_iters)))
    refined.sort(key=lambda t: t[0])
    points = [{"params": {n: float(p[n]) for n in names}, "cost": float(c)}
              for c, p in refined[:max(1, int(top_k))]]
    champion_info = {k: entry.get(k) for k in (
        "version", "model_blob_sha256", "trained_run_ids", "render_commit",
        "heldout", "created_at", "hyperparams")}
    return ok_envelope(points=points, champion=champion_info,
                       key=key, n_probe_evaluated=len(scored))


def _pattern_search(
    pred_cost, start: dict[str, float],
    bounds: dict[str, tuple[float, float]], *, iters: int,
) -> tuple[float, dict[str, float]]:
    """确定性坐标模式搜索（步长折半细化；无随机性）。"""
    cur = {k: min(max(float(v), bounds[k][0]), bounds[k][1])
           for k, v in start.items()}
    best = pred_cost(cur)
    if best is None:
        return (math.inf, cur)
    steps = {k: 0.05 * (bounds[k][1] - bounds[k][0]) for k in bounds}
    for _ in range(max(1, iters)):
        improved = False
        for n in bounds:
            for sign in (1.0, -1.0):
                cand = dict(cur)
                cand[n] = min(max(cur[n] + sign * steps[n], bounds[n][0]),
                              bounds[n][1])
                c = pred_cost(cand)
                if c is not None and c < best - 1e-15:
                    cur, best = cand, c
                    improved = True
        if not improved:
            for n in bounds:
                steps[n] *= 0.5
            if max(steps.values()) < 1e-9 * max(
                    bounds[k][1] - bounds[k][0] for k in bounds):
                break
    return (best, cur)


def run_optimization_with_registry_warm_start(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    max_trials: int = 60,
    study_name: str | None = None,
    max_wall_s: float | None = None,
    adapter_kwargs: dict[str, Any] | None = None,
    sampler: str = "tpe",
    seed: int | None = None,
    warm_start: list[dict[str, Any]] | None = None,
    warm_start_registry: bool | None = None,
    pruner: str = "none",
    callbacks: Any = None,
) -> dict[str, Any]:
    """战役启动包装：registry champion 近优点并入 warm_start 通道（①）。

    三态开关裁决见 ``resolve_warm_start_registry_flag``（缺省 False=行为
    与 run_optimization 原样一致，零退化）。解析失败/stale/blob 损坏一律
    best-effort 降级冷启动并在 ``result["registry_warm_start"]`` 如实透出
    （#105 不阻塞战役；#122 不静默——reason 随结果可见）。
    pruner/callbacks 原样透传 run_optimization（start_tune 接线用，
    None=不加键条件透传 #df6③）。
    """
    enabled = resolve_warm_start_registry_flag(warm_start_registry)
    info: dict[str, Any] = {"enabled": enabled, "channel": str(adapter_name)}
    merged = [dict(p) for p in (warm_start or [])]
    if enabled:
        try:
            pts = surrogate_registry_champion_points(
                recipe_path, adapter_name)
        except Exception as exc:  # 解析失败降级（#105）
            pts = error_envelope(f"{exc}", reason="resolution_error",
                                 detail=f"{exc}")
        info["resolution"] = {k: v for k, v in pts.items() if k != "points"}
        if pts.get("ok"):
            merged.extend(pts.get("points") or [])
            info["n_points"] = len(pts.get("points") or [])
            info["champion"] = pts.get("champion")
        else:
            info["n_points"] = 0

    from rfauto.optimization.optimizer import run_optimization

    kw: dict[str, Any] = {}
    if seed is not None:
        kw["seed"] = int(seed)
    if merged:
        kw["warm_start"] = merged
    if callbacks:
        kw["callbacks"] = [callbacks]
    result = run_optimization(
        recipe_path,
        adapter_name=adapter_name,
        max_trials=max_trials,
        study_name=study_name,
        max_wall_s=max_wall_s,
        adapter_kwargs=adapter_kwargs,
        sampler=sampler,
        pruner=pruner,
        **kw,
    )
    if isinstance(result, dict) and enabled:
        result["registry_warm_start"] = info
    return result


# ─── 配对裁判（spec §6.3-2，#273 channel 口径）───────────────────────────────


def judge_registry_warm_start_benefit(
    pairs: dict[str, dict[str, Any]],
    *,
    threshold_pct: float = BENEFIT_THRESHOLD_PCT_DEFAULT,
    channel: str | None = None,
) -> dict[str, Any]:
    """registry warm-start 收益配对裁判（注入 vs 不注入，≥3 对）。

    pairs 形如 ``{seed: {"injected_first": c|None, "baseline_first": c|None,
    "injected_ttt": n|None, "baseline_ttt": n|None}}``——首 trial cost 与
    达标 trial 数（可选）。判据（spec §6.3-2）：
    - 首 trial cost 中位改善 ≥ threshold_pct（逐对 (base−inj)/base，取
      中位；base ≤ 0/缺值对剔除计 censored）；
    - **或**双臂 ttt 齐备且注入组中位 ttt < 基线组中位 ttt；
    - 无改善如实 FAIL 不凑绿；verdict 顶层带 channel 字段（#273 口径：
      fake 通道数字不得冒充真跑判据）。
    """
    per_pair: dict[str, Any] = {}
    improvements: list[float] = []
    n_censored = 0
    inj_ttt: list[float] = []
    base_ttt: list[float] = []
    for seed_label in sorted(pairs, key=str):
        row = pairs[seed_label] or {}
        inj = row.get("injected_first")
        base = row.get("baseline_first")
        entry: dict[str, Any] = {
            "injected_first": inj, "baseline_first": base}
        if isinstance(inj, (int, float)) and not isinstance(inj, bool) \
                and isinstance(base, (int, float)) and not isinstance(base, bool) \
                and float(base) > 0.0:
            imp = (float(base) - float(inj)) / float(base) * 100.0
            entry["improvement_pct"] = round(imp, 4)
            improvements.append(imp)
        else:
            entry["improvement_pct"] = None
            n_censored += 1
        for key_arm, sink in (("injected_ttt", inj_ttt),
                              ("baseline_ttt", base_ttt)):
            val = row.get(key_arm)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                sink.append(float(val))
                entry[key_arm] = val
            else:
                entry[key_arm] = None
        per_pair[str(seed_label)] = entry

    median_imp = float(statistics.median(improvements)) \
        if improvements else None
    ttt_ok = len(inj_ttt) == len(base_ttt) == len(per_pair) and per_pair
    ttt_reduced = bool(
        ttt_ok and statistics.median(inj_ttt) < statistics.median(base_ttt))
    passed = bool(
        (median_imp is not None and median_imp >= float(threshold_pct))
        or ttt_reduced)

    if passed and median_imp is not None and median_imp >= float(threshold_pct):
        why = (f"首 trial cost 中位改善 {median_imp:.2f}% "
               f"≥ 阈值 {threshold_pct}%")
    elif passed:
        why = (f"达标 trial 数中位减少 "
               f"（注入 {statistics.median(inj_ttt):.1f} < "
               f"基线 {statistics.median(base_ttt):.1f}）")
    else:
        why = (f"无达标改善（中位改善 {median_imp if median_imp is not None else 'NA'}"
               f"%，阈值 {threshold_pct}%；ttt 缺数据或未减少）——如实 FAIL")

    return ok_envelope(
        verdict="PASS" if passed else "FAIL",
        **{"pass": passed},
        why=why,
        n_pairs=len(per_pair),
        n_censored=n_censored,
        median_improvement_pct=(round(median_imp, 4)
                                if median_imp is not None else None),
        median_injected_ttt=(statistics.median(inj_ttt) if inj_ttt else None),
        median_baseline_ttt=(statistics.median(base_ttt) if base_ttt else None),
        threshold_pct=float(threshold_pct),
        channel=channel,
        per_pair=per_pair,
    )
