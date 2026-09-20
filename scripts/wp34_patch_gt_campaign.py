r"""W1⑪a WP3.4 神经算子数据门槛解锁——patch_antenna 族 HFSS ground-truth 点补齐战役。

背景（对账发现）：``neural_operator_readiness("wp24_registry_20260913")``
逐族 ground-truth 点数 patch_antenna n_gt=69（threshold=100，deficit 31）。
GT 判定走 ``dataset_service.is_ground_truth_adapter``（adapter 含 hfss/openems/
comsol/meas 词根且不含 fake）。本战役只补 **HFSS** 真机点。

参数空间对齐（不发明数字，数值纪律）：
- 参数名 = 旧注册表 patch 族 **hfss 行** params_json 键并集（实测
  {feed_offset_mm, patch_len_mm, patch_w_mm}：run 20260831_125228_db3856cb 的
  15 行三参数 + run 20260831_003706_338afc6c 的 8 行两参数子集）；
- 边界 = 模板配方 ``recipes/patch_tune_light.yaml`` 的 optimization.params
  （patch_len_mm [35,45] / feed_offset_mm [3,20] / patch_w_mm [40,60]）——与
  上述 HFSS GT 行的 recipe.snapshot.yaml 逐字段一致；
- 二者键集合不相等即显式报错，绝不静默取交集。

执行口径：
- LHS（``optimization.sample_design.lhs_points``）固定 seed，N=36（>31 留失败余量）；
- 逐点写配方副本（runs/wp34_patch_gt/recipes/，原件不改）→ ``service.api.run_once``
  （adapter_name="hfss"，study 只进 provenance #158）→ 每点一个 runs/<run_id>
  （meta.json adapter=hfss，与既有 GT 行同物化路径）；
- 串行 1（机器独占，#246），HFSS 失败整点重试 ≤2 次（#191）带退避，仍失败记
  failed 继续；
- 可恢复：progress.json 逐点落盘，重启跳过 done 与已用尽重试的 failed；
- 每点日志追加 campaign.log（含单点用时）。

运行（长任务分离+日志轮询，#157；单条命令勿超 8 分钟）：
  .venv\Scripts\python.exe scripts/wp34_patch_gt_campaign.py --mode plan   # 只出计划
  .venv\Scripts\python.exe scripts/wp34_patch_gt_campaign.py --mode run --max-points 1   # 前台验链路
  powershell Start-Process -FilePath .venv\Scripts\python.exe `
    -ArgumentList "scripts/wp34_patch_gt_campaign.py --mode run" `
    -RedirectStandardOutput runs/wp34_patch_gt/stdout.log `
    -RedirectStandardError runs/wp34_patch_gt/stderr.log
收尾（全部点完成后）：
  .venv\Scripts\python.exe scripts/wp34_patch_gt_campaign.py --mode ingest
  → 以新名 wp34_registry_20260916 物化（旧注册表 source_runs + 本战役 done runs，
    双集口径不碰 wp24_registry_20260913），跑 neural_operator_readiness 写
    runs/wp34_patch_gt/readiness.json。

几何纪律：参数值 float 预计算写入配方 value（单位由配方字段语义 mm 固定，#218）；
Hfss()/run_dir 由 run_once 以绝对路径创建（#243），本脚本 --mode run/ingest
一律 chdir 到仓库根（run_once/materialize 的 runs/ 相对路径锚点）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

RUNS_DIR = REPO / "runs"
SOURCE_REGISTRY_NAME = "wp24_registry_20260913"
SOURCE_REGISTRY_DIR = RUNS_DIR / "datasets" / SOURCE_REGISTRY_NAME
SOURCE_REGISTRY_PARQUET = SOURCE_REGISTRY_DIR / "points.parquet"
SOURCE_REGISTRY_MANIFEST = SOURCE_REGISTRY_DIR / "dataset_manifest.yaml"
WORK_DIR = RUNS_DIR / "wp34_patch_gt"
PROGRESS_PATH = WORK_DIR / "progress.json"
LOG_PATH = WORK_DIR / "campaign.log"
READINESS_PATH = WORK_DIR / "readiness.json"
TEMPLATE_RECIPE = REPO / "recipes" / "patch_tune_light.yaml"

MODEL_NAME = "patch_antenna"
NEW_REGISTRY_NAME = "wp34_registry_20260916"
CAMPAIGN_STUDY = "wp34_patch_gt"
LHS_SEED = 20260916
N_POINTS_DEFAULT = 36
MAX_ATTEMPTS_DEFAULT = 3       # 1 次初始 + ≤2 次整点重试（#191）
RETRY_BACKOFF_S_DEFAULT = 30.0  # 重试前退避基值（gRPC 抖动自愈窗口），指数递增

RunOnceFn = Callable[..., dict[str, Any]]


# ---------------------------------------------------------------------------
# 纯函数面（单测覆盖，零真机）
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry_rows(parquet_path: Path, model: str = MODEL_NAME) -> list[dict[str, Any]]:
    """读旧注册表 points.parquet，返回指定器件族的行（只读复核，不改写）。"""
    import pyarrow.parquet as pq  # 延迟 import：dataset extra

    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"注册表点级数据不存在: {path}")
    table = pq.read_table(path, columns=["run_id", "model", "adapter", "params_json"])
    return [row for row in table.to_pylist() if str(row.get("model") or "") == model]


def hfss_param_union(rows: list[dict[str, Any]]) -> set[str]:
    """patch 族 ground-truth **hfss** 行的参数名并集（fake/openEMS 行不参与定空间）。"""
    from rfauto.service.dataset_service import is_ground_truth_adapter

    names: set[str] = set()
    for row in rows:
        adapter = str(row.get("adapter") or "")
        if "hfss" not in adapter.lower() or not is_ground_truth_adapter(adapter):
            continue
        raw = row.get("params_json") or "{}"
        params = json.loads(raw) if isinstance(raw, str) else dict(raw)
        names.update(str(k) for k in params)
    return names


def recipe_bounds(recipe_data: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """从配方 optimization.params 取 {name: (low, high)}；缺 low/high 显式报错。"""
    opt = (recipe_data.get("optimization") or {}).get("params") or {}
    if not isinstance(opt, dict) or not opt:
        raise ValueError("模板配方缺 optimization.params，无法定采样边界")
    out: dict[str, tuple[float, float]] = {}
    for name, spec in opt.items():
        if not isinstance(spec, dict) or "low" not in spec or "high" not in spec:
            raise ValueError(f"配方参数 {name!r} 缺 low/high 边界")
        low, high = float(spec["low"]), float(spec["high"])
        if not high > low:
            raise ValueError(f"配方参数 {name!r} 边界非法: low={low} high={high}")
        out[str(name)] = (low, high)
    return out


def derive_param_space(
    rows: list[dict[str, Any]],
    bounds: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """参数名对齐：注册表 hfss 行键并集 必须 == 模板配方 bounds 键集合。

    不相等即 ValueError（多/少键各自列出）——新点必须与既有 GT 行同参数空间
    才计入同一族，静默取交集会让新旧点落在不同空间。
    """
    gt_names = hfss_param_union(rows)
    if not gt_names:
        raise ValueError("注册表中无 patch 族 hfss ground-truth 行，无法对齐参数名")
    recipe_names = set(bounds)
    if gt_names != recipe_names:
        raise ValueError(
            "参数名不对齐：注册表 hfss 行键集合 "
            f"{sorted(gt_names)} vs 配方 bounds 键集合 {sorted(recipe_names)}"
            f"（仅注册表有: {sorted(gt_names - recipe_names)}；"
            f"仅配方有: {sorted(recipe_names - gt_names)}）"
        )
    return {name: bounds[name] for name in sorted(recipe_names)}


def build_plan(
    bounds: dict[str, tuple[float, float]],
    n_points: int,
    seed: int,
) -> list[dict[str, Any]]:
    """LHS 采样计划（确定性：同 seed 同点集；min_dist=0 保证恰 n_points 点）。"""
    from rfauto.optimization.sample_design import lhs_points

    if n_points < 1:
        raise ValueError(f"n_points 必须 >= 1，收到 {n_points}")
    design = lhs_points(bounds, n_points, seed=int(seed))
    points = design["points"]
    if len(points) != n_points:
        raise RuntimeError(f"LHS 计划点数 {len(points)} != {n_points}")
    plan: list[dict[str, Any]] = []
    for idx, pt in enumerate(points):
        params = {name: float(pt[name]) for name in sorted(bounds)}
        for name, (low, high) in bounds.items():
            if not low <= params[name] <= high:
                raise RuntimeError(f"LHS 点 {idx} 参数 {name}={params[name]} 越界 [{low},{high}]")
        plan.append({
            "index": idx,
            "params": params,
            "status": "pending",
            "attempts": 0,
            "run_id": "",
            "elapsed_s": None,
            "error": "",
        })
    return plan


def render_recipe_copy(template_text: str, params: dict[str, float]) -> str:
    """配方副本：模板 YAML 的 params.<name>.value 改成采样值（float 预计算，
    单位由字段语义固定 mm，#218），其余字段原样；原件不改。"""
    import yaml

    data = yaml.safe_load(template_text)
    if not isinstance(data, dict) or not isinstance(data.get("params"), dict):
        raise ValueError("模板配方缺 params 段")
    for name, value in params.items():
        spec = data["params"].get(name)
        if isinstance(spec, dict):
            spec["value"] = float(value)
        else:
            data["params"][name] = {"value": float(value)}
    data["notes"] = (
        f"{data.get('notes', '')} | wp34 patch GT campaign copy "
        f"(seed={LHS_SEED}, study={CAMPAIGN_STUDY})"
    ).strip(" |")
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def load_progress(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path, progress: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    progress["updated_at"] = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def new_progress(
    param_space: dict[str, tuple[float, float]],
    plan: list[dict[str, Any]],
    *,
    seed: int,
    template_recipe: str,
) -> dict[str, Any]:
    return {
        "campaign": CAMPAIGN_STUDY,
        "model": MODEL_NAME,
        "source_registry": SOURCE_REGISTRY_NAME,
        "template_recipe": template_recipe,
        "param_space": {k: [float(v[0]), float(v[1])] for k, v in param_space.items()},
        "seed": int(seed),
        "n_points": len(plan),
        "started_at": _now_iso(),
        "updated_at": "",
        "points": plan,
    }


def progress_matches_plan(
    progress: dict[str, Any],
    param_space: dict[str, tuple[float, float]],
    *,
    seed: int,
    n_points: int,
) -> bool:
    """既有 progress 与本次计划口径（参数空间/seed/点数）一致才允许恢复。"""
    want_space = {k: [float(v[0]), float(v[1])] for k, v in param_space.items()}
    return (
        progress.get("campaign") == CAMPAIGN_STUDY
        and progress.get("param_space") == want_space
        and int(progress.get("seed", -1)) == int(seed)
        and int(progress.get("n_points", -1)) == int(n_points)
        and len(progress.get("points") or []) == int(n_points)
    )


def pending_indices(progress: dict[str, Any], max_attempts: int = MAX_ATTEMPTS_DEFAULT) -> list[int]:
    """待跑点：跳过 done；failed 且 attempts>=max_attempts 视为用尽不再重试。"""
    out: list[int] = []
    for pt in progress.get("points") or []:
        status = str(pt.get("status") or "pending")
        if status == "done":
            continue
        if status == "failed" and int(pt.get("attempts") or 0) >= max_attempts:
            continue
        out.append(int(pt["index"]))
    return out


def summarize(progress: dict[str, Any]) -> dict[str, Any]:
    pts = progress.get("points") or []
    done = [p for p in pts if p.get("status") == "done"]
    failed = [p for p in pts if p.get("status") == "failed"]
    elapsed = [float(p["elapsed_s"]) for p in done if p.get("elapsed_s") is not None]
    return {
        "n_points": len(pts),
        "n_done": len(done),
        "n_failed": len(failed),
        "n_pending": len(pts) - len(done) - len(failed),
        "mean_elapsed_s": (sum(elapsed) / len(elapsed)) if elapsed else None,
        "done_run_ids": [p["run_id"] for p in done],
    }


# ---------------------------------------------------------------------------
# 真机面（单测 monkeypatch 入口）
# ---------------------------------------------------------------------------

def _resolve_aedt_install() -> dict[str, Any] | None:
    from rfauto.infra.version_probe import resolve_aedt_install

    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "") or None
    return resolve_aedt_install(aedt_path)


def preflight_hfss() -> dict[str, Any]:
    """HFSS 可用性预检：AEDT 安装探测失败即显式 RuntimeError（不静默降级 fake）。"""
    install = _resolve_aedt_install()
    if install is None:
        raise RuntimeError(
            "HFSS 不可用：未找到 AEDT 安装（RFAUTO_AEDT_PATH 未设且自动探测失败）——"
            "本战役只产 hfss ground-truth 点，拒绝降级到 fake"
        )
    return {"aedt_version": str(install.get("aedt_version") or ""),
            "path": str(install.get("path") or "")}


def _default_run_once(recipe_path: Path, *, adapter_name: str, study: str, seed: str) -> dict[str, Any]:
    from rfauto.service.api import run_once

    return run_once(str(recipe_path), adapter_name=adapter_name, study=study, seed=seed)


def _append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{_now_iso()}] {line}\n")


def run_point(
    point: dict[str, Any],
    *,
    template_text: str,
    recipes_dir: Path,
    run_once_fn: RunOnceFn,
    log_path: Path,
    max_attempts: int,
    backoff_s: float,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """单点执行：写配方副本 → run_once（hfss）→ 失败整点重试 ≤max_attempts-1 次。

    就地更新 point 的 status/attempts/run_id/elapsed_s/error 并返回。
    """
    idx = int(point["index"])
    recipes_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = recipes_dir / f"recipe_pt{idx:02d}.yaml"
    recipe_path.write_text(render_recipe_copy(template_text, point["params"]), encoding="utf-8")

    while int(point.get("attempts") or 0) < max_attempts:
        attempt = int(point.get("attempts") or 0) + 1
        point["attempts"] = attempt
        t0 = time.perf_counter()
        try:
            result = run_once_fn(recipe_path, adapter_name="hfss", study=CAMPAIGN_STUDY, seed=str(LHS_SEED))
        except Exception as exc:  # run_once 抛异常（gRPC/COM 层）也按失败重试
            result = {"ok": False, "errors": [f"{type(exc).__name__}: {exc}"],
                      "traceback": traceback.format_exc(limit=6)}
        elapsed = time.perf_counter() - t0
        point["elapsed_s"] = round(elapsed, 1)
        point["run_id"] = str(result.get("run_id") or "")
        if result.get("ok"):
            point["status"] = "done"
            point["error"] = ""
            point["from_cache"] = bool(result.get("from_cache"))
            metrics = result.get("metrics") or {}
            point["metrics"] = {k: metrics[k] for k in sorted(metrics)} if isinstance(metrics, dict) else {}
            _append_log(log_path, (
                f"pt={idx:02d} status=done attempt={attempt} elapsed_s={elapsed:.1f} "
                f"run_id={point['run_id']} from_cache={point['from_cache']} "
                f"params={json.dumps(point['params'], sort_keys=True)} "
                f"metrics={json.dumps(point['metrics'], sort_keys=True)}"))
            return point
        err = "; ".join(str(e) for e in (result.get("errors") or ["unknown"]))
        point["status"] = "failed"
        point["error"] = err[:800]
        _append_log(log_path, (
            f"pt={idx:02d} status=failed attempt={attempt}/{max_attempts} elapsed_s={elapsed:.1f} "
            f"run_id={point['run_id']} error={point['error']}"))
        if attempt < max_attempts:
            delay = backoff_s * (2 ** (attempt - 1))
            _append_log(log_path, f"pt={idx:02d} retry in {delay:.0f}s (#191 整点重试)")
            sleep_fn(delay)
    return point


def run_campaign(
    *,
    template_recipe: Path = TEMPLATE_RECIPE,
    registry_parquet: Path = SOURCE_REGISTRY_PARQUET,
    work_dir: Path = WORK_DIR,
    n_points: int = N_POINTS_DEFAULT,
    seed: int = LHS_SEED,
    max_points: int | None = None,
    max_attempts: int = MAX_ATTEMPTS_DEFAULT,
    backoff_s: float = RETRY_BACKOFF_S_DEFAULT,
    run_once_fn: RunOnceFn = _default_run_once,
    preflight_fn: Callable[[], dict[str, Any]] = preflight_hfss,
    plan_only: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """战役主循环（可恢复）：plan → 逐点串行 → progress/log 落盘 → 汇总。

    max_points：本次进程最多跑几个待跑点（前台验链路用 1），None=跑完全部待跑。
    plan_only：只写计划到 progress.json（不预检 HFSS、不跑点）。
    """
    import yaml

    work_dir = Path(work_dir)
    progress_path = work_dir / "progress.json"
    log_path = work_dir / "campaign.log"
    recipes_dir = work_dir / "recipes"

    template_text = Path(template_recipe).read_text(encoding="utf-8")
    bounds = recipe_bounds(yaml.safe_load(template_text))
    rows = load_registry_rows(Path(registry_parquet))
    param_space = derive_param_space(rows, bounds)

    progress = load_progress(progress_path)
    resumed = False
    if progress is not None:
        if not progress_matches_plan(progress, param_space, seed=seed, n_points=n_points):
            raise RuntimeError(
                f"既有 progress {progress_path} 与本次计划口径不一致（参数空间/seed/点数），"
                "拒绝混跑——换 work_dir 或删除旧 progress 后重来")
        resumed = True
    else:
        plan = build_plan(param_space, n_points, seed)
        progress = new_progress(param_space, plan, seed=seed,
                                template_recipe=str(Path(template_recipe).as_posix()))
        save_progress(progress_path, progress)

    if plan_only:
        return {"ok": True, "mode": "plan", "resumed": resumed, "progress": str(progress_path),
                "param_space": progress["param_space"], **summarize(progress)}

    hfss = preflight_fn()
    progress.setdefault("hfss", hfss)
    todo = pending_indices(progress, max_attempts)
    if max_points is not None:
        todo = todo[: max(0, int(max_points))]
    _append_log(log_path, (
        f"campaign start resumed={resumed} aedt={hfss.get('aedt_version')} "
        f"todo={len(todo)} pending_total={len(pending_indices(progress, max_attempts))} "
        f"{json.dumps(summarize(progress) | {'done_run_ids': '...'}, ensure_ascii=False)}"))

    points_by_index = {int(p["index"]): p for p in progress["points"]}
    for idx in todo:
        point = points_by_index[idx]
        run_point(point, template_text=template_text, recipes_dir=recipes_dir,
                  run_once_fn=run_once_fn, log_path=log_path, max_attempts=max_attempts,
                  backoff_s=backoff_s, sleep_fn=sleep_fn)
        save_progress(progress_path, progress)

    summary = summarize(progress)
    _append_log(log_path, f"campaign stop {json.dumps(summary | {'done_run_ids': '...'}, ensure_ascii=False)}")
    return {"ok": True, "mode": "run", "resumed": resumed, "progress": str(progress_path),
            "log": str(log_path), "ran_indices": todo, **summary}


# ---------------------------------------------------------------------------
# 收尾：新注册表物化 + 解锁进度
# ---------------------------------------------------------------------------

def source_registry_run_ids(manifest_path: Path) -> list[str]:
    import yaml

    data = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8")) or {}
    ids = [str(r.get("run_id")) for r in (data.get("source_runs") or []) if r.get("run_id")]
    if not ids:
        raise ValueError(f"旧注册表 manifest 无 source_runs: {manifest_path}")
    return ids


def ingest(
    *,
    progress_path: Path = PROGRESS_PATH,
    source_manifest: Path = SOURCE_REGISTRY_MANIFEST,
    new_name: str = NEW_REGISTRY_NAME,
    readiness_path: Path = READINESS_PATH,
    materialize_fn: Callable[..., dict[str, Any]] | None = None,
    readiness_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """新名物化（旧 source_runs ∪ 本战役 done runs）→ neural_operator_readiness → readiness.json。"""
    if materialize_fn is None or readiness_fn is None:
        from rfauto.service.dataset_insights import neural_operator_readiness
        from rfauto.service.dataset_service import materialize_dataset
        materialize_fn = materialize_fn or materialize_dataset
        readiness_fn = readiness_fn or neural_operator_readiness

    progress = load_progress(Path(progress_path))
    if progress is None:
        raise FileNotFoundError(f"progress 不存在，先跑战役: {progress_path}")
    summary = summarize(progress)
    new_ids = [rid for rid in summary["done_run_ids"] if rid]
    old_ids = source_registry_run_ids(Path(source_manifest))
    run_ids = sorted(set(old_ids) | set(new_ids))

    mat = materialize_fn(run_ids, name=new_name, fmt="parquet")
    readiness = readiness_fn(new_name) if mat.get("ok") else {"ok": False, "errors": mat.get("errors")}
    out = {
        "generated_at": _now_iso(),
        "new_registry": new_name,
        "source_registry": SOURCE_REGISTRY_NAME,
        "n_source_runs": len(old_ids),
        "n_campaign_runs": len(new_ids),
        "campaign": summary,
        "materialize": {k: mat.get(k) for k in (
            "ok", "name", "n_points", "n_rows", "n_dup", "skipped_runs", "missing_runs",
            "unhealthy_runs", "errors", "parquet", "manifest")},
        "readiness": readiness,
    }
    Path(readiness_path).parent.mkdir(parents=True, exist_ok=True)
    Path(readiness_path).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", choices=("plan", "run", "ingest"), default="plan")
    ap.add_argument("--n-points", type=int, default=N_POINTS_DEFAULT)
    ap.add_argument("--seed", type=int, default=LHS_SEED)
    ap.add_argument("--max-points", type=int, default=None,
                    help="本进程最多跑几个待跑点（前台验链路用 1）")
    ap.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS_DEFAULT)
    ap.add_argument("--backoff-s", type=float, default=RETRY_BACKOFF_S_DEFAULT)
    ap.add_argument("--work-dir", default=str(WORK_DIR))
    args = ap.parse_args(argv)

    os.chdir(REPO)  # run_once/materialize 以 runs/ 相对路径为锚（run_dir 本身绝对，#243）
    work_dir = Path(args.work_dir).resolve()
    try:
        if args.mode == "ingest":
            out = ingest(progress_path=work_dir / "progress.json",
                         readiness_path=work_dir / "readiness.json")
        else:
            out = run_campaign(
                work_dir=work_dir, n_points=args.n_points, seed=args.seed,
                max_points=args.max_points, max_attempts=args.max_attempts,
                backoff_s=args.backoff_s, plan_only=(args.mode == "plan"))
    except Exception as exc:
        print(json.dumps({"ok": False, "mode": args.mode, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        traceback.print_exc()
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
