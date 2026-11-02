r"""C10 GT 补族战役——branchline（34 点）/ wilkinson（18 点）openEMS ground-truth 采集。

背景（TODO 0da followUp④，2026-09-16 登记）：wp34 patch HFSS GT 战役同法
补 branchline_coupler / wilkinson_power_divider 两族的 openEMS GT 点
（wp34_registry_20260916 实测 branchline n_gt=34、wilkinson n_gt=18，
threshold=100；本战役点数即 0da④ 预声明的 34/18，``--n-points`` 可调）。
真机排程由主代理负责（铁律：本脚本交付+离线验证，禁自行真跑 OE）。

参数空间对齐（不发明数字，铁律 7）：
- 参数名 = 源注册表该族 **GT 行**（is_ground_truth_adapter）params_json 键并集
  （实测两族均 {arm_len_mm, series_w_mm, shunt_w_mm}）；
- 边界 = 族配方 optimization.params（branchline_tune_light.yaml /
  wilkinson_pd_v1.yaml）——缺边界显式报错（wp34 纪律）；
- 频段/判读带 = 族配方 setup.freq_range_ghz / objectives[].band（原样继承）。

执行口径（factory_m1/m3 + wp34 三先例合成，只 import 不改源）：
- LHS（optimization.sample_design.lhs_points）固定 seed，对源注册表该族
  GT 行参数元组查重（round 1e-6）+ 计划内查重；
- 逐点 OpenEMSOptAdapter 整脚本重渲染真跑（OE 串行 1：共享锁
  runs/.oe_collect.lock + #261 命令行互斥查，复用 factory_m3_valley）；
- 失败整点跳过记 failed 继续（points_index 幂等，resume 跳过 done）；
- QuotaGuard(逐点/墙钟) 超限停批判 PARTIAL，已完成点照常入库；
- 放量前首点 ingest 探针 1 行成行（#251④）；
- 单激励口径注意：OpenEMSOptAdapter 单次 solve 产 (n,3,3) 部分矩阵
  （S11/S21/S31 @ port1 激励，openems_solver._parse_output），指标内核
  只读激励列（s11/s21/s31），隔离类 S23 不产出（不凑数，#314 同族纪律）。

用法（cwd=仓库根；长任务分离+日志轮询，#157）：
  python scripts/c10_gt_campaign.py --family branchline --mode plan
  python scripts/c10_gt_campaign.py --family branchline --mode collect --max-points 1
  python scripts/c10_gt_campaign.py --family branchline --mode ingest
  # wilkinson 同法换 --family wilkinson

收尾产物：runs/c10_<family>_gt/{plan.json,points_index.json,campaign.log,
readiness.json} + 新注册表 registry_20260922_<family>（源注册表 source_runs
∪ 本战役 done runs，双集口径不碰源注册表）。

退出码：plan=0；collect/ingest 0=门过；1=门未达/执行失败；2=参数错误。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 采集链复用（只 import 不改源，m3→m1 同款）：m1 模块导入时自注入 src 路径，
# 脚本目录经 python 运行/测试 sys.path 注入解析（本文件 cwd 守卫=仓库根）。
from factory_m3_valley import acquire_lock, oe_foreign_running, release_lock

REPO = Path(__file__).resolve().parents[1]

# ─── 族配置（参数空间/频段全部来自族配方，这里只登记名与点数） ────────────────
LHS_SEED = 20260922
SOURCE_REGISTRY_NAME = "wp34_registry_20260916"
SOURCE_REGISTRY_MANIFEST = REPO / "runs" / "datasets" / SOURCE_REGISTRY_NAME / "dataset_manifest.yaml"
SOURCE_REGISTRY_PARQUET = REPO / "runs" / "datasets" / SOURCE_REGISTRY_NAME / "points.parquet"
SUBSTRATE = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # rogers4350b 锚口径（_DEFAULT_SUB 显式化）
SOLVE_TIMEOUT_S_DEFAULT = 1800.0
QUOTA_WALL_H_DEFAULT = 12.0
LHS_POOL_FACTOR = 2
LHS_MAX_POOLS = 5

FAMILIES: dict[str, dict[str, Any]] = {
    "branchline": {
        "model": "branchline_coupler",
        "template": "branchline",
        "recipe": REPO / "recipes" / "branchline_tune_light.yaml",
        "n_points": 34,
        "study": "c10_branchline_gt",
        "dataset": "registry_20260922_branchline",
        "probe_dataset": "c10_branchline_ingest_probe",
        "work_root": REPO / "runs" / "c10_branchline_gt",
    },
    "wilkinson": {
        "model": "wilkinson_power_divider",
        "template": "wilkinson",
        "recipe": REPO / "recipes" / "wilkinson_pd_v1.yaml",
        "n_points": 18,
        "study": "c10_wilkinson_gt",
        "dataset": "registry_20260922_wilkinson",
        "probe_dataset": "c10_wilkinson_ingest_probe",
        "work_root": REPO / "runs" / "c10_wilkinson_gt",
    },
}

__all__ = [
    "FAMILIES",
    "build_plan",
    "compute_point_metrics",
    "existing_eval_index_max",
    "family_gt_param_tuples",
    "mesh_meta_value",
    "param_fingerprint",
    "recipe_bounds",
    "recipe_spec",
]


# ---------------------------------------------------------------------------
# 纯函数面（单测覆盖，零真机零 IO）
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def recipe_bounds(recipe_data: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """从配方 optimization.params 取 {name: (low, high)}；缺 low/high 显式报错。"""
    opt = (recipe_data.get("optimization") or {}).get("params") or {}
    if not isinstance(opt, dict) or not opt:
        raise ValueError("族配方缺 optimization.params，无法定采样边界")
    out: dict[str, tuple[float, float]] = {}
    for name, spec in opt.items():
        if not isinstance(spec, dict) or "low" not in spec or "high" not in spec:
            raise ValueError(f"配方参数 {name!r} 缺 low/high 边界")
        low, high = float(spec["low"]), float(spec["high"])
        if not high > low:
            raise ValueError(f"配方参数 {name!r} 边界非法: low={low} high={high}")
        out[str(name)] = (low, high)
    return out


def recipe_spec(family: str) -> dict[str, Any]:
    """族配方规格（bounds / freq_range / band，全部原样继承自配方 YAML）。"""
    import yaml

    cfg = FAMILIES[family]
    data = yaml.safe_load(Path(cfg["recipe"]).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"族配方不是对象: {cfg['recipe']}")
    setup = data.get("setup") or {}
    freq = setup.get("freq_range_ghz") or []
    if len(freq) != 2:
        raise ValueError(f"族配方 setup.freq_range_ghz 缺失或非两元素: {freq}")
    objectives = data.get("objectives") or []
    bands = [tuple(o.get("band") or []) for o in objectives
             if isinstance(o, dict) and len(o.get("band") or []) == 2]
    return {
        "bounds": recipe_bounds(data),
        "freq_range_ghz": (float(freq[0]), float(freq[1])),
        "band_ghz": bands[0] if bands else (float(freq[0]), float(freq[1])),
    }


def param_fingerprint(params: dict[str, float]) -> tuple[tuple[str, float], ...]:
    """参数元组指纹（round 1e-6；存量查重口径，多维同构 m1 w_fingerprint）。"""
    return tuple(sorted((str(k), round(float(v), 6)) for k, v in params.items()))


def family_gt_param_tuples(
    parquet_path: Path,
    model: str,
    *,
    bounds_names: set[str] | None = None,
) -> set[tuple[tuple[str, float], ...]]:
    """源注册表该族 GT 行的参数元组集合（fake/非 GT 行不参与查重）。"""
    import pyarrow.parquet as pq  # 延迟 import：dataset extra

    from rfauto.service.dataset_service import is_ground_truth_adapter

    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"源注册表点级数据不存在: {path}")
    table = pq.read_table(path, columns=["run_id", "model", "adapter", "params_json"])
    out: set[tuple[tuple[str, float], ...]] = set()
    for row in table.to_pylist():
        if str(row.get("model") or "") != model:
            continue
        if not is_ground_truth_adapter(row.get("adapter")):
            continue
        raw = row.get("params_json") or "{}"
        params = json.loads(raw) if isinstance(raw, str) else dict(raw)
        if bounds_names is not None:
            params = {k: v for k, v in params.items() if str(k) in bounds_names}
        if params:
            out.add(param_fingerprint(params))
    return out


def build_plan(
    bounds: dict[str, tuple[float, float]],
    n_points: int,
    seed: int,
    taken: set[tuple[tuple[str, float], ...]] | None = None,
) -> list[dict[str, Any]]:
    """LHS 采样计划（确定性：同 seed 同点集；存量/计划内撞点剔除+续抽）。"""
    from rfauto.optimization.sample_design import lhs_points

    if n_points < 1:
        raise ValueError(f"n_points 必须 >= 1，收到 {n_points}")
    taken = taken or set()
    names = sorted(bounds)
    points: list[dict[str, Any]] = []
    n_dropped = 0
    pool_seed = int(seed)
    pool = max(n_points * LHS_POOL_FACTOR, 8)
    used: set[tuple[tuple[str, float], ...]] = set()
    for _pool_i in range(LHS_MAX_POOLS):
        design = lhs_points(bounds, pool, seed=pool_seed)
        pool_seed += 1
        for pt in design["points"]:
            params = {name: float(pt[name]) for name in names}
            for name, (low, high) in bounds.items():
                if not low <= params[name] <= high:
                    raise RuntimeError(
                        f"LHS 点参数 {name}={params[name]} 越界 [{low},{high}]")
            fp = param_fingerprint(params)
            if fp in taken or fp in used:
                n_dropped += 1
                continue
            used.add(fp)
            points.append({
                "index": len(points),
                "params": params,
                "status": "pending",
                "attempts": 0,
                "run_id": "",
                "elapsed_s": None,
                "error": "",
            })
            if len(points) >= n_points:
                break
        if len(points) >= n_points:
            break
    if len(points) != n_points:
        raise RuntimeError(
            f"LHS 计划点数 {len(points)} != {n_points}（查重剔除 {n_dropped}，"
            f"{LHS_MAX_POOLS} 轮池耗尽）——如投放量请换 seed 或清查重集")
    return points


def compute_point_metrics(
    network: Any,
    band: tuple[float, float],
) -> tuple[dict[str, float], list[str]]:
    """单点指标（确定性内核；单激励部分矩阵只读激励列，#314 同族纪律）。

    产键：s11_db_max_in_band / s11_db_min_in_band / s21_db_mean_in_band，
    网络 ≥3 端口时并列 s31_db_mean_in_band。隔离类 S23 在单激励通道为
    未测/掩码语义，不产出（不凑数）。
    """
    import numpy as np

    from rfauto.core.objectives import SpecEvaluator

    lo, hi = float(band[0]), float(band[1])
    sub = SpecEvaluator.extract_band(network, lo, hi) if lo > 0 else network
    curve = 20 * np.log10(np.abs(sub.s[:, 0, 0]) + 1e-30)
    metrics: dict[str, float] = {
        "s11_db_max_in_band": float(np.max(curve)),
        "s11_db_min_in_band": float(np.min(curve)),
        "s21_db_mean_in_band": SpecEvaluator.s21_db(network, lo, hi),
    }
    notes: list[str] = []
    if sub.s.shape[1] >= 3:
        s31 = sub.s[:, 2, 0]
        metrics["s31_db_mean_in_band"] = float(
            np.mean(20 * np.log10(np.abs(s31) + 1e-30)))
    else:
        notes.append("s31_skipped: 网络 <3 端口（单激励部分矩阵口径）")
    return metrics, notes


# ---------------------------------------------------------------------------
# 产物面（标准 run 布局 = dataset_service ⑤ 分支成行契约，#251④）
# ---------------------------------------------------------------------------

def _cache_state() -> str:
    raw = os.environ.get("RFAUTO_CACHE", "")
    return raw if raw else "unset(readwrite default)"


def mesh_meta_value(mesh_resolution_mm: float | str | None) -> float | str:
    """meta.mesh_resolution_mm 落痕口径（#117 邻形：0.0 是"自动档"语义哨兵
    非实测值，禁当数值落 meta 被下游误消费）。

    正数=实测网格 base（mm）原值落痕；0.0=官方自动 λ_sub/50 档 → "auto"
    字符串注记；未知（注入替身无 mesh_resolution_mm 观测面）→ "unknown"
    （#105 观测缺失如实，不臆造）。消费面 grep 实证：src/ 无 meta 数值
    消费者（contracts.py 的 mesh 字段属 gate/calibration payload 非本键）。
    """
    if mesh_resolution_mm is None:
        return "unknown"
    if isinstance(mesh_resolution_mm, str):
        return mesh_resolution_mm
    mesh = float(mesh_resolution_mm)
    return mesh if mesh > 0.0 else "auto"


def existing_eval_index_max(evals_root: Path) -> int:
    """evals 根下既有 eval_NNNN 子目录的最大序号（A-02 resume 防覆盖）。

    resume 会话新 adapter 的 _n 计数从 0 回卷，会把 work_root/eval_0001
    起的既有评估归档整目录覆盖——factory 以本值作 eval_index_offset 接续
    编号；根不存在/无 eval_NNNN 目录 = 0（全新根）。
    """
    root = Path(evals_root)
    if not root.is_dir():
        return 0
    mx = 0
    for child in root.iterdir():
        m = re.fullmatch(r"eval_(\d{4,})", child.name)
        if child.is_dir() and m:
            mx = max(mx, int(m.group(1)))
    return mx


def write_run_products(
    run_dir: Path,
    family: str,
    params: dict[str, float],
    network: Any,
    wall_s: float,
    eval_dir: str,
    metrics: dict[str, float],
    notes: list[str],
    *,
    freq_range_ghz: tuple[float, float],
    band_ghz: tuple[float, float],
    bounds: dict[str, tuple[float, float]],
    study: str,
    mesh_resolution_mm: float | None = None,
) -> None:
    """单点写成 api.run_once 兼容标准 run 产物（⑤ 分支契约）。

    布局：meta.json(status=done, model=族插件名, adapter=openems) +
    recipe.snapshot.yaml(params 值 + optimization.params 键集) +
    results/metrics.json + results/params.s{n}p（n=network.nports 实测，
    #248 扩展名契约；单激励通道 branchline/wilkinson 均 .s3p）+
    results/sparams.csv（engine 原生随 run 归档：G11 健康门的已测掩码
    载体——单激励 Touchstone 是零填充部分矩阵，仅凭它体检互易必假阳性）。

    eval_dir 语义=最近一次 solve 的评估产物目录（adapter.last_eval_dir），
    其下 sparams.csv 缺失即抛错（健康门掩码载体是产品契约非可选项）。
    mesh_resolution_mm=adapter.mesh_resolution_mm 观测面透传（缺省 None=
    未知），meta 落痕经 mesh_meta_value 归一（0.0 哨兵→"auto"，#117 邻形）。
    """
    from rfauto.infra.run_store import snapshot_recipe, write_meta

    cfg = FAMILIES[family]
    recipe: dict[str, Any] = {
        "model": cfg["model"],
        "study": study,
        "params": {k: {"value": float(v), "unit": "mm"} for k, v in params.items()},
        "optimization": {"params": {
            k: {"low": float(v[0]), "high": float(v[1])}
            for k, v in sorted(bounds.items())}},
        "setup": {"solver": "openEMS",
                  "freq_range_ghz": list(freq_range_ghz)},
        "notes": f"c10 {family} GT 采集点（study={study}）",
    }
    snapshot_recipe(run_dir, recipe)
    payload = {
        "metrics": metrics,
        "notes": notes,
        "band_ghz": list(band_ghz),
        "params": {k: float(v) for k, v in params.items()},
        "freq_range_ghz": list(freq_range_ghz),
    }
    (run_dir / "results" / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ports = int(network.s.shape[1])
    network.write_touchstone(str(run_dir / "results" / f"params.s{n_ports}p"))
    csv_src = Path(eval_dir) / "sparams.csv"
    if not csv_src.is_file():
        found = sorted(Path(eval_dir).rglob("sparams.csv"))
        csv_src = found[0] if found else None
    if csv_src is None:
        raise FileNotFoundError(
            f"engine sparams.csv 缺失（eval_dir={eval_dir}）——"
            "健康门已测掩码载体是 run 产品契约，禁止无掩码 Touchstone 单飞")
    shutil.copyfile(csv_src, run_dir / "results" / "sparams.csv")
    write_meta(run_dir, {
        "status": "done",
        "model": cfg["model"],
        "adapter": "openems",
        "study_name": study,
        "algorithm": "lhs_collect",
        "timestamp": _now_iso(),
        "wall_s": round(float(wall_s), 2),
        "params": {k: float(v) for k, v in params.items()},
        "mesh_resolution_mm": mesh_meta_value(mesh_resolution_mm),
        "freq_range_ghz": list(freq_range_ghz),
        "cache_env": _cache_state(),
        "eval_dir": str(eval_dir),
        "source": f"c10_{family}_gt",
    }, run_id=run_dir.name)


def _append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{_now_iso()}] {line}\n")


# ---------------------------------------------------------------------------
# 采集面（锁内真机；adapter/materialize 注入供 fake 冒烟与单测）
# ---------------------------------------------------------------------------

def _default_adapter_factory(family: str, freq_range_ghz: tuple[float, float],
                             solve_timeout_s: float, evals_root: Path) -> Any:
    from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter

    # cache=False 显式压住 RFAUTO_CACHE 缺省（round5 C-F2）：GT 采集必须
    # 新鲜 solve——缓存命中即早退（openems_solver._load_cached）不执行渲染
    # 脚本 → 新 eval_dir 无 sparams.csv → write_run_products 抛
    # FileNotFoundError，成功的（缓存）点被判假失败。
    # eval_index_offset=既有最大序号（A-02）：resume 会话 _n 回卷会整目录
    # 覆盖既有 eval_NNNN 归档，从既有最大序号接续编号防覆盖。
    return OpenEMSOptAdapter(
        freq_range_ghz, template=FAMILIES[family]["template"],
        substrate=dict(SUBSTRATE), solve_timeout_s=solve_timeout_s,
        work_root=evals_root, cache=False,
        eval_index_offset=existing_eval_index_max(evals_root))


def _load_index(work_root: Path) -> dict[str, Any]:
    p = work_root / "points_index.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save_index(work_root: Path, index: dict[str, Any]) -> None:
    work_root.mkdir(parents=True, exist_ok=True)
    p = work_root / "points_index.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def done_run_ids(index: dict[str, Any]) -> list[str]:
    return [row["rid"] for _pid, row in sorted(index.items())
            if isinstance(row, dict) and row.get("status") == "done"]


def run_collect(
    repo_root: Path,
    family: str,
    *,
    n_points: int | None = None,
    seed: int = LHS_SEED,
    max_points: int | None = None,
    solve_timeout_s: float = SOLVE_TIMEOUT_S_DEFAULT,
    quota_wall_h: float = QUOTA_WALL_H_DEFAULT,
    adapter_factory: Callable[[], Any] | None = None,
    materialize_fn: Callable[..., dict[str, Any]] | None = None,
    work_root: Path | None = None,
    use_shared_lock: bool = True,
) -> int:
    """真机批量采集（共享锁内整段；points_index 幂等可恢复）。

    adapter_factory/materialize_fn/work_root/use_shared_lock 注入面：
    fake 冒烟与单测零真机、零 runs/ 污染、零真锁（repo_root 指 tmp，
    use_shared_lock=False 跳过共享锁与 #261 进程查）；缺省为
    OpenEMSOptAdapter 真跑 + 真物化 + runs/.oe_collect.lock。
    """
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir
    from rfauto.pipeline.quota_guard import QuotaExceededError, QuotaGuard, QuotaLimits
    from rfauto.service.dataset_service import materialize_dataset

    if materialize_fn is None:
        materialize_fn = materialize_dataset
    cfg = FAMILIES[family]
    if n_points is None:
        n_points = int(cfg["n_points"])
    spec = recipe_spec(family)
    root = Path(work_root) if work_root is not None else Path(cfg["work_root"])
    plan_path = root / "plan.json"
    log_path = root / "campaign.log"

    if str(Path.cwd().resolve()) != str(Path(repo_root).resolve()):
        print(f"[c10:{family}] 拒跑：cwd 必须是仓库根 {repo_root}（当前 {Path.cwd()}）")
        return 2

    # 计划不可变（首次生成后 resume 同计划；口径变更须换 work_root）
    existing = json.loads(plan_path.read_text(encoding="utf-8")) \
        if plan_path.exists() else None
    want_space = {k: [float(v[0]), float(v[1])] for k, v in spec["bounds"].items()}
    if existing is not None:
        if (existing.get("family") != family
                or existing.get("param_space") != want_space
                or int(existing.get("seed", -1)) != int(seed)
                or int(existing.get("n_points", -1)) != int(n_points)
                or len(existing.get("points") or []) != int(n_points)):
            print(f"[c10:{family}] 既有 plan {plan_path} 与本次口径不一致，拒绝混跑")
            return 2
        plan = existing
    else:
        taken = family_gt_param_tuples(
            SOURCE_REGISTRY_PARQUET, cfg["model"],
            bounds_names=set(spec["bounds"]))
        points = build_plan(spec["bounds"], n_points, seed, taken)
        plan = {
            "family": family,
            "model": cfg["model"],
            "source_registry": SOURCE_REGISTRY_NAME,
            "param_space": want_space,
            "freq_range_ghz": list(spec["freq_range_ghz"]),
            "band_ghz": list(spec["band_ghz"]),
            "seed": int(seed),
            "n_points": len(points),
            "started_at": _now_iso(),
            "points": points,
        }
        root.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        _append_log(log_path, f"plan 产出 {len(points)} 点（查重集 "
                              f"source={SOURCE_REGISTRY_NAME}，seed={seed}）")

    evals_root = root / "evals"
    if adapter_factory is None:
        adapter = _default_adapter_factory(
            family, spec["freq_range_ghz"], solve_timeout_s, evals_root)
    else:
        adapter = adapter_factory()
    guard = QuotaGuard(QuotaLimits(max_trials=n_points, max_wall_hours=quota_wall_h))
    index = _load_index(root)
    owner_pid = os.getpid()

    if use_shared_lock:
        acquire_lock(f"c10_{family}_gt")

    t0 = time.time()
    ingest_checked = False
    partial = False
    ran = 0
    try:
        if use_shared_lock:
            foreign = oe_foreign_running()
            if foreign:
                print("[c10] #261 互斥命中（他轨 OE 在跑，拒绝起跑，不代杀）：\n"
                      + "\n".join(f"  {ln}" for ln in foreign[:10]))
                return 1
            print("[c10] #261 命令行查：无他轨 OE 进程，锁内起跑")
        for pt in plan["points"]:
            pid = f"pt{int(pt['index']):02d}"
            row = index.get(pid)
            if isinstance(row, dict) and row.get("status") == "done":
                continue
            guard.check_trial(ran)
            guard.check_wall_time(t0)
            params = {k: float(v) for k, v in pt["params"].items()}
            rid = generate_run_id()
            run_dir = create_run_dir(repo_root, rid)
            adapter.set_variables(params)
            t_solve = time.monotonic()
            rep = adapter.solve(timeout_s=solve_timeout_s)
            solve_wall = time.monotonic() - t_solve
            if not rep.success:
                index[pid] = {"status": "failed", "rid": rid,
                              "msg": str(rep.message)[:300]}
                _save_index(root, index)
                _append_log(log_path, f"{pid} FAIL solve: {rep.message}")
                ran += 1
                continue
            net = adapter.get_sparams()
            metrics, notes = compute_point_metrics(net, spec["band_ghz"])
            eval_hint = (getattr(adapter, "last_eval_dir", None)
                         or getattr(adapter, "eval_root", evals_root))
            write_run_products(
                run_dir, family, params, net, solve_wall,
                str(eval_hint), metrics, notes,
                freq_range_ghz=spec["freq_range_ghz"], band_ghz=spec["band_ghz"],
                bounds=spec["bounds"], study=cfg["study"],
                mesh_resolution_mm=getattr(adapter, "mesh_resolution_mm", None))
            index[pid] = {"status": "done", "rid": rid,
                          "wall_s": round(solve_wall, 2),
                          "params": params}
            _save_index(root, index)
            ran += 1
            _append_log(log_path,
                        f"{pid} rid={rid} wall={solve_wall:.1f}s "
                        f"metrics={json.dumps(metrics, sort_keys=True)}")
            print(f"[c10:{family}] {pid} rid={rid} wall={solve_wall:.1f}s "
                  f"s11_min={metrics.get('s11_db_min_in_band')}", flush=True)
            # 放量纪律（#251④）：首点 ingest 核对成行才继续批量
            if not ingest_checked:
                probe = materialize_fn(run_ids=[rid], name=cfg["probe_dataset"],
                                       health_gate=True)
                n_probe = int(probe.get("n_rows") or 0)
                if not probe.get("ok") or n_probe != 1:
                    msg = (f"首点 ingest 核对失败（ok={probe.get('ok')} "
                           f"n_rows={n_probe} errors={probe.get('errors')} "
                           f"unhealthy={probe.get('unhealthy_runs')}）——停批排查")
                    print(f"[c10:{family}] {msg}")
                    _append_log(log_path, f"{pid} {msg}")
                    return 1
                _append_log(log_path, "首点 ingest 核对 OK（1 行成行）")
                ingest_checked = True
            if max_points is not None and ran >= int(max_points):
                break
    except QuotaExceededError as exc:
        partial = True
        _append_log(log_path, f"quota 停批（PARTIAL，已完成点照常入库）: {exc}")
    finally:
        if use_shared_lock:
            release_lock(owner_pid)

    summary = {
        "n_points": len(plan["points"]),
        "n_done": len(done_run_ids(index)),
        "n_failed": sum(1 for r in index.values()
                        if isinstance(r, dict) and r.get("status") == "failed"),
        "ran_this_session": ran,
        "partial": partial,
        "batch_wall_s": round(time.time() - t0, 1),
    }
    _append_log(log_path, f"collect stop {json.dumps(summary, ensure_ascii=False)}")
    print(json.dumps({"ok": True, "mode": "collect", "family": family,
                      "work_root": str(root), **summary},
                     ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------------------
# 收尾：新注册表物化（源 source_runs ∪ 本战役 done）+ readiness
# ---------------------------------------------------------------------------

def source_registry_run_ids(manifest_path: Path) -> list[str]:
    import yaml

    data = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8")) or {}
    ids = [str(r.get("run_id")) for r in (data.get("source_runs") or [])
           if isinstance(r, dict) and r.get("run_id")]
    if not ids:
        raise ValueError(f"源注册表 manifest 无 source_runs: {manifest_path}")
    return ids


def run_ingest(
    family: str,
    *,
    manifest_path: Path = SOURCE_REGISTRY_MANIFEST,
    readiness_fn: Callable[..., dict[str, Any]] | None = None,
    materialize_fn: Callable[..., dict[str, Any]] | None = None,
    work_root: Path | None = None,
) -> int:
    """新名物化（源 source_runs ∪ 本战役 done runs）→ readiness → readiness.json。"""
    if materialize_fn is None:
        from rfauto.service.dataset_service import materialize_dataset
        materialize_fn = materialize_dataset
    if readiness_fn is None:
        from rfauto.service.dataset_insights import neural_operator_readiness
        readiness_fn = neural_operator_readiness
    cfg = FAMILIES[family]
    root = Path(work_root) if work_root is not None else Path(cfg["work_root"])
    index = _load_index(root)
    rids = done_run_ids(index)
    if not rids:
        print(f"[c10:{family}] 无 done 点（先 --mode collect）")
        return 2
    old_ids = source_registry_run_ids(Path(manifest_path))
    all_ids = sorted(set(old_ids) | set(rids))
    mat = materialize_fn(run_ids=all_ids, name=cfg["dataset"], fmt="parquet",
                         health_gate=True)
    readiness = (readiness_fn(cfg["dataset"]) if mat.get("ok")
                 else {"ok": False, "errors": mat.get("errors")})
    out = {
        "generated_at": _now_iso(),
        "family": family,
        "new_registry": cfg["dataset"],
        "source_registry": SOURCE_REGISTRY_NAME,
        "n_source_runs": len(old_ids),
        "n_campaign_runs": len(rids),
        "materialize": {k: mat.get(k) for k in (
            "ok", "name", "n_points", "n_rows", "n_dup", "skipped_runs",
            "missing_runs", "unhealthy_runs", "errors", "parquet", "manifest")},
        "readiness": readiness,
    }
    path = root / "readiness.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": bool(mat.get("ok")), "mode": "ingest",
                      "family": family, "readiness": str(path),
                      "n_rows": out["materialize"].get("n_rows")},
                     ensure_ascii=False, indent=1))
    return 0 if mat.get("ok") else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="C10 GT 补族战役（branchline/wilkinson）")
    ap.add_argument("--family", choices=sorted(FAMILIES), required=True)
    ap.add_argument("--mode", choices=("plan", "collect", "ingest"), default="plan")
    ap.add_argument("--n-points", type=int, default=None,
                    help="覆盖族预声明点数（branchline 34 / wilkinson 18）")
    ap.add_argument("--seed", type=int, default=LHS_SEED)
    ap.add_argument("--max-points", type=int, default=None,
                    help="本进程最多真跑几个待跑点（前台验链路用 1）")
    ap.add_argument("--solve-timeout-s", type=float, default=SOLVE_TIMEOUT_S_DEFAULT)
    ap.add_argument("--quota-wall-h", type=float, default=QUOTA_WALL_H_DEFAULT)
    args = ap.parse_args(argv)

    os.chdir(REPO)  # create_run_dir/materialize 以 runs/ 相对路径为锚（#243 同款）
    family = args.family
    cfg = FAMILIES[family]
    try:
        if args.mode == "plan":
            spec = recipe_spec(family)
            n_points = args.n_points if args.n_points is not None else int(cfg["n_points"])
            taken = family_gt_param_tuples(
                SOURCE_REGISTRY_PARQUET, cfg["model"],
                bounds_names=set(spec["bounds"]))
            points = build_plan(spec["bounds"], n_points, args.seed, taken)
            print(json.dumps({
                "ok": True, "mode": "plan", "family": family,
                "model": cfg["model"],
                "param_space": {k: list(v) for k, v in spec["bounds"].items()},
                "freq_range_ghz": list(spec["freq_range_ghz"]),
                "band_ghz": list(spec["band_ghz"]),
                "seed": args.seed, "n_points": len(points),
                "n_dedup_source": len(taken),
                "first_points": [p["params"] for p in points[:3]],
            }, ensure_ascii=False, indent=1))
            return 0
        if args.mode == "collect":
            return run_collect(REPO, family, n_points=args.n_points,
                               seed=args.seed, max_points=args.max_points,
                               solve_timeout_s=args.solve_timeout_s,
                               quota_wall_h=args.quota_wall_h)
        return run_ingest(family)
    except Exception as exc:
        print(json.dumps({"ok": False, "mode": args.mode, "family": family,
                          "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False))
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
