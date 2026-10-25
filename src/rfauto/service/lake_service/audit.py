"""lake_service.audit —— 湖只读清点与陈旧审计（QW-13 sweep + XD-9 audit-stale）。

自 lake_service.py 巨石按职责域拆分（aurora_g W7-S1 T2，AU-1 工艺）：代码体自原「lake sweep」「湖陈旧审计」两节逐字节搬迁（sweep 半产物标记面被 audit-stale unknown 口径复用，同域承载）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .index import _dir_stats, _iter_run_dirs, _meta_file, _read_json_object

# ---------------------------------------------------------------------------
# QW-13 lake sweep：incomplete/半产物只读清点（DP-9 gc 视角，零改写）
# ---------------------------------------------------------------------------

#: sweep 判"半产物"的证据文件（存在即记原因；判定只读文件存在性，
#: 不解析不臆造状态——#144：在跑 run 的形态恰是"有 trials/无 meta"）。
_SWEEP_PRODUCT_MARKERS: tuple[tuple[str, str], ...] = (
    ("trials", "有 trials/ 无 meta（在跑或中断，meta 结束才落盘）"),
    ("samples.json", "有 samples.json 无 meta"),
    ("sparams.csv", "有 sparams.csv 无 meta"),
    ("calib.json", "有 calib.json 无 meta"),
)


def sweep_runs(runs_dir: str | Path = "runs",
               *, max_list: int = 200) -> dict[str, Any]:
    """runs/ 只读清点报告（QW-13：incomplete 标记/半产物 gc 视角）。

    分类口径（只读文件存在性，零改写零移动——与 pack/restore 同款红线）：
    - ``container``：一级战役目录且含子目录（容器位，不进四分类——战役
      层无 meta 属正常形态；run 点内的 trials/ 子目录不算容器，恰是
      #144 在跑形态的证据面）；n_dirs 含容器，四桶之和=n_dirs-n_containers；
    - ``complete``：meta 文件在（meta.json/run_meta.json 任一）；
    - ``empty``：目录零文件（空壳战役位/废弃位）；
    - ``incomplete``：无 meta 但有产物证据（trials//samples.json/
      sparams.csv/calib.json 任一）——在跑（#144 形态）或中断半产物；
    - ``unannotated``：无 meta 且无任何已知产物证据（仅杂项文件）。
    判定信息只有文件存在性与实测体积，缺失字段如实省略不臆造。

    Returns:
        dict: {"ok", "runs_dir", "n_dirs", "n_containers", "n_complete",
               "n_incomplete", "n_empty", "n_unannotated",
               "incomplete": [{path, campaign, depth, n_files, size_bytes,
               markers, reasons}], "errors"}
    """
    root = Path(runs_dir)
    base: dict[str, Any] = {"runs_dir": str(root)}
    if not root.is_dir():
        return ok_envelope(
                   **{
                   "n_dirs": 0,
                   "n_containers": 0,
                   "n_complete": 0,
                   "n_incomplete": 0,
                   "n_empty": 0,
                   "n_unannotated": 0,
                   "incomplete": [],
                   "errors": [],
                   **base,
                   "note": f"runs 目录不存在: {root}",
                   },
               )
    counts = {"complete": 0, "incomplete": 0, "empty": 0, "unannotated": 0}
    n_containers = 0
    incomplete_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for run_dir, campaign, depth in _iter_run_dirs(root):
        try:
            rel = run_dir.relative_to(root).as_posix()
            size, n_files = _dir_stats(run_dir)
            has_children = any(p.is_dir() for p in run_dir.iterdir())
        except Exception as exc:  # 单目录失败不阻塞（#105）
            if len(errors) < 20:
                errors.append(f"{run_dir}: {exc}")
            continue
        if depth == 1 and has_children:
            n_containers += 1
            continue
        if _meta_file(run_dir) is not None:
            counts["complete"] += 1
            continue
        if n_files == 0:
            counts["empty"] += 1
            continue
        markers: list[str] = []
        reasons: list[str] = []
        for name, reason in _SWEEP_PRODUCT_MARKERS:
            if (run_dir / name).exists():
                markers.append(name)
                reasons.append(reason)
        row: dict[str, Any] = {
            "path": rel, "campaign": campaign, "depth": depth,
            "n_files": n_files, "size_bytes": size, "markers": markers,
            "reasons": reasons,
        }
        if markers:
            counts["incomplete"] += 1
            if len(incomplete_rows) < max_list:
                incomplete_rows.append(row)
        else:
            counts["unannotated"] += 1
    return ok_envelope(
               **{
               "n_dirs": sum(counts.values()) + n_containers,
               "n_containers": n_containers,
               "n_complete": counts["complete"],
               "n_incomplete": counts["incomplete"],
               "n_empty": counts["empty"],
               "n_unannotated": counts["unannotated"],
               "incomplete": incomplete_rows,
               "errors": errors,
               **base,
               },
           )


# ---------------------------------------------------------------------------
# XD-9：湖陈旧审计（audit-stale——Snakemake --list-code-changes 的湖级版）
# ---------------------------------------------------------------------------
# 只读承诺：零写系统（对 runs/ 与 .rfauto_cache/ 只读；输出由调用方落盘）。
# 失效判定复用 infra/dag_cache 的键成分语义（TRIGGER_OF_COMPONENT 四类：
# code/params/budget/env），meta 缺失目录（在跑/半途 #144）如实单列 unknown。

#: config-diff 键 → budget 类（网格/预算档变化按 #343/#262 族语义单列）。
_AUDIT_BUDGET_META_KEYS: frozenset[str] = frozenset(
    {"mesh_config", "budget_tier", "mesh_resolution_mm"})


def _audit_git_head(cwd: str | Path | None = None) -> str:
    """当前 HEAD 短 SHA（best-effort #105：非 git 环境/失败 → 空串不抛穿）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30,
            cwd=str(cwd) if cwd else None)
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 and sha else ""
    except Exception:
        return ""


def _audit_norm(path: str | Path) -> str:
    """run_dir 归一键（#318：Windows 大小写/分隔符 normcase 比较）。"""
    import os

    return os.path.normcase(str(Path(path).resolve()))


def _audit_dag_components(
    cache_dir: str | Path | None,
) -> dict[str, dict[str, str]]:
    """扫 dag 索引（DagCasIndex 落盘面），run_dir 归一 → 键成分表。

    索引目录缺失/条目损坏逐条跳过（best-effort，#105）——audit 退化为
    纯 meta 面判定，不阻塞。
    """
    import json as _json

    base = Path(cache_dir) if cache_dir else Path(".rfauto_cache") / "dag"
    out: dict[str, dict[str, str]] = {}
    if not base.is_dir():
        return out
    for child in sorted(base.glob("*.json")):
        try:
            data = _json.loads(child.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        run_dir = str(data.get("run_dir") or "")
        comps = data.get("components")
        if run_dir and isinstance(comps, dict):
            out.setdefault(_audit_norm(run_dir),
                           {str(k): str(v) for k, v in comps.items()})
    return out


def _audit_engine_record(meta: dict[str, Any]) -> str:
    """meta 面引擎版本记录（dag 成分缺档时的回退源；无记录 → 空串）。"""
    sv = meta.get("solver_versions")
    if isinstance(sv, dict) and sv:
        return _canonical_dump(sv)
    adapter = str(meta.get("adapter") or "")
    if adapter.startswith("hfss"):
        return str(meta.get("aedt_version") or "")
    if "ads" in adapter:
        return str(meta.get("ads_version") or "")
    return ""


def _canonical_dump(obj: Any) -> str:
    """稳定 JSON 串（dag_cache.canonical_json 只读复用，惰性导入）。"""
    from rfauto.infra.dag_cache import canonical_json

    return canonical_json(obj)


def normalize_config_diff(raw: Any) -> tuple[dict[str, Any], str]:
    """config-diff 载荷归一为 键→新值 映射（新值 None=只声明键变化）。

    接受三形：{"keys": [k, …]}；{"keys": {k: 新值或 {"old","new"}}}；
    扁平 {k: 新值或 {"old","new"}}。空输入（None/空对象/空键表）=合法
    零变化 → 空映射（判据 1 双态钉：空 diff 输入→清单为空）；非法
    （非 dict 非空）→ error 串。
    """
    if raw is None:
        return {}, ""
    if not isinstance(raw, dict):
        return {}, f"config-diff 必须是 JSON 对象，得到 {type(raw).__name__}"
    body: Any = raw
    if "keys" in raw and isinstance(raw["keys"], (list, dict)):
        body = raw["keys"]
    if isinstance(body, list):
        pairs: dict[str, Any] = {str(k): None for k in body}
    elif isinstance(body, dict):
        pairs = {}
        for k, v in body.items():
            if isinstance(v, dict) and "new" in v:
                pairs[str(k)] = v["new"]
            else:
                pairs[str(k)] = v
    else:
        return {}, "config-diff keys 必须是列表或对象"
    return pairs, ""


def audit_stale_runs(
    runs_dir: str | Path = "runs",
    *,
    render_commit: str | None = None,
    engine_version: str | None = None,
    config_diff: Any = None,
    cache_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    max_detail: int = 200,
    max_depth: int | None = 6,
) -> dict[str, Any]:
    """湖陈旧审计（XD-9：给定当前成分，扫全湖列将失效 run 清单+原因分类）。

    三选择器（可组合）：
    - ``render_commit``：代码面（meta.git_sha 对照；缺省=当前 HEAD）——
      不一致=code 类（Snakemake --list-code-changes 湖级语义）；
    - ``engine_version``：引擎面——与 run 的 dag 键成分 engine_version
      对照（缺档回退 meta solver_versions/aedt/ads 记录；两处皆无=不可比，
      如实计 no_engine_record 不 inflate）——不一致=engine 类；
    - ``config_diff``：配置面（normalize_config_diff 三形）——变化的键
      命中 meta 顶键且值可对且不等 → params 类（网格/预算键 → budget 类）；
      键不在 meta → unmatched 计数不 inflate；有 dag 成分的 run 顺带比
      env_fingerprint_sha（commit 推进即 env 失效是设计语义）→ env 类。

    缺 meta 目录（在跑/半途 #144）→ unknown 清单单列。纯读零写（判据 3）；
    退出语义由 CLI 映射（0 无失效 / 1 有失效 / 2 程序性错误）。
    """
    root = Path(runs_dir)
    base: dict[str, Any] = {"runs_dir": str(root)}
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root}"], **base)
    pairs, diff_err = normalize_config_diff(config_diff)
    if diff_err:
        return error_envelope([diff_err], **base)

    head = _audit_git_head(repo_root or root)
    code_ref = str(render_commit) if render_commit else head
    comps_by_dir = _audit_dag_components(cache_dir)

    current_env_sha: str | None = None

    def _env_sha() -> str:
        nonlocal current_env_sha
        if current_env_sha is None:
            from rfauto.infra.dag_cache import canonical_json, env_fingerprint, sha256_text

            # 包化后深一层：lake_service/audit.py → parents[4]=仓根
            # （原单文件 lake_service.py 为 parents[3]，W7-S1 T2 拆分随域调整）。
            root_guess = Path(repo_root) if repo_root else (
                Path(__file__).resolve().parents[4])
            current_env_sha = sha256_text(
                canonical_json(env_fingerprint(root_guess)))
        return current_env_sha

    class_counts = {"code": 0, "params": 0, "engine": 0, "env": 0,
                    "budget": 0}
    n_checked = 0
    n_stale = 0
    n_unknown = 0
    n_no_engine_record = 0
    n_config_key_unmatched = 0
    stale_rows: list[dict[str, Any]] = []
    unknown_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # 递归走湖（run 点 meta 可嵌在战役/批次多层下，两层 _iter_run_dirs
    # 覆盖不了——实测湖内 meta 大多在 3-4 层）；run 点内部子目录
    # （trials//fdtd/ 等产物位）不再按 unknown 计（其 meta 语义归属父
    # run 点）。unknown 口径对齐 sweep_runs 半途形态（_SWEEP_PRODUCT_MARKERS）。
    import os

    suppress_unknown: set[str] = set()
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__pycache__"]
        here = Path(dirpath)
        try:
            depth = len(here.relative_to(root).parts)
        except ValueError:
            depth = 0
        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []
        has_meta = _meta_file(here) is not None
        if not has_meta:
            if (_audit_norm(here) != _audit_norm(root)
                    and _audit_norm(here) not in suppress_unknown
                    and any((here / name).exists()
                            for name, _ in _SWEEP_PRODUCT_MARKERS)):
                n_unknown += 1
                if len(unknown_rows) < max_detail:
                    unknown_rows.append({
                        "path": here.relative_to(root).as_posix(),
                        "reason": "无 meta 但有产物证据（在跑或半途，#144 形态）"})
            continue
        # run 点：子目录视为内部产物位，不再报 unknown
        for d in dirnames:
            suppress_unknown.add(_audit_norm(here / d))
        meta = _read_json_object(_meta_file(here))
        if meta is None:  # meta 文件在但不可解析（损坏）——如实进 unknown
            n_unknown += 1
            if len(unknown_rows) < max_detail:
                unknown_rows.append({
                    "path": here.relative_to(root).as_posix(),
                    "reason": "meta 文件不可解析（损坏）"})
            continue
        n_checked += 1
        rel = here.relative_to(root).as_posix()
        campaign = rel.split("/", 1)[0] if "/" in rel else None
        classes: list[str] = []
        reasons: list[str] = []

        if code_ref:
            run_sha = str(meta.get("git_sha") or "")
            if run_sha and run_sha != code_ref:
                classes.append("code")
                reasons.append(
                    f"git_sha {run_sha} != 当前 {code_ref}（渲染/代码面已变）")

        comps = comps_by_dir.get(_audit_norm(here)) or {}
        if engine_version:
            stored_engine = str(comps.get("engine_version") or "") \
                or _audit_engine_record(meta)
            if stored_engine:
                if stored_engine != engine_version:
                    classes.append("engine")
                    reasons.append(
                        "engine_version "
                        f"{stored_engine[:24]} != 当前 {engine_version[:24]}")
            else:
                n_no_engine_record += 1

        stored_env = str(comps.get("env_fingerprint_sha") or "")
        if stored_env and stored_env != _env_sha():
            classes.append("env")
            reasons.append("env_fingerprint_sha 与当前环境不一致（git/依赖面）")

        for key, new_val in pairs.items():
            if key not in meta:
                n_config_key_unmatched += 1
                continue
            if new_val is None:
                continue  # 只声明键变化、未给新值：不可比，不计失效
            if str(meta[key]) != str(new_val):
                cls = "budget" if key in _AUDIT_BUDGET_META_KEYS else "params"
                classes.append(cls)
                reasons.append(
                    f"{key}: {str(meta[key])[:24]} -> {str(new_val)[:24]}")

        if classes:
            n_stale += 1
            for c in classes:
                class_counts[c] += 1
            if len(stale_rows) < max_detail:
                stale_rows.append({"path": rel, "campaign": campaign,
                                   "classes": classes,
                                   "reasons": reasons})
    return ok_envelope(
        n_dirs=n_checked + n_unknown,
        n_checked=n_checked,
        n_stale=n_stale,
        n_fresh=n_checked - n_stale,
        n_unknown_meta=n_unknown,
        class_counts=class_counts,
        n_no_engine_record=n_no_engine_record,
        n_config_key_unmatched=n_config_key_unmatched,
        stale=stale_rows,
        unknown=unknown_rows[:max_detail],
        selectors={"render_commit": code_ref or None,
                   "render_commit_source":
                       "explicit" if render_commit else ("git-head" if head else "unavailable"),
                   "engine_version": engine_version,
                   "config_keys": sorted(pairs)},
        errors=errors,
        **base)
