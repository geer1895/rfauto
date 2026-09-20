"""M1 数据面采集管线（M1 里程碑）。

判据/口径全部预声明 runs/data_factory_m1/criteria.md（写死再跑）。
链路：lhs_points 批量（+锚点预置）→ OpenEMSOptAdapter 逐点求解（e11 harness
产物化通道，OE 串行 1）→ 标准 run 产物落盘（api.run_once 兼容布局）→
materialize_dataset 成行（dataset_service ⑤ 分支，#251④ 先例）→ 三门判读。

用法（cwd=仓库根）：
  python scripts/factory_m1_collect.py --plan          # 采样计划+查重统计（离线）
  python scripts/factory_m1_collect.py --collect       # 真机批量采集（断点 resume 幂等）
  python scripts/factory_m1_collect.py --materialize   # 由已落盘点物化数据集（幂等）
  python scripts/factory_m1_collect.py --judge         # 三门判读（幂等重跑）

纪律：
- 放量前先跑 1 点 ingest 核对成行（#251④）：首点产物 _collect_run_points
  不出 1 行即中止批量（门 G1 前置保险）。
- 采集期缓存=开（引擎磁盘缓存缺省 runs/openems_cache；RFAUTO_CACHE 未设
  即 readwrite）——同参数 resume 重跑秒回（#158），criteria.md 预声明。
- QuotaGuard(max_trials/max_wall_hours) 逐点准入，超限停批判 PARTIAL，
  已完成点照常 materialize 双记不删（#317 先例）。
- 断点 resume：plan.json 首次生成后不可变（resume 同计划）；points_index
  json 逐点落盘（崩溃安全），status=done 的点自动跳过。

退出码：--collect/--judge 0=PASS；1=门未达/执行失败；2=参数错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

C0 = 299792458.0
#: M3 扩 2D 时的显式变量键集（params_json 按 optimization.params
#: 键集成行——第二维 line_len_mm 不声明则静默不入行）；M1/M2 保持 1D 缺省。
VARIABLE_PARAM_KEYS = ("w_mm",)

__all__ = [
    "build_sampling_plan",
    "compute_point_metrics",
    "existing_mline_w",
    "judge_m1",
    "w_fingerprint",
    "write_run_products",
]

# ─── 预声明常量（criteria.md 同源，改门先改 criteria 再改这里） ────────────────
TEMPLATE = "mline"
SUBSTRATE = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # rogers4350b 锚口径
FREQ_RANGE_GHZ = (2.0, 3.0)
BAND_GHZ = (2.4, 2.6)
LINE_LEN_MM = 40.0
W_LOW, W_HIGH = 0.5, 2.0
ANCHOR_W = (0.5, 2.0, 1.113, 0.745, 1.182)  # 域端点+名义+零违约区边界
N_LHS = 115
LHS_POOL = 130
LHS_MAX_POOLS = 3
LHS_SEED = 42
LHS_MIN_DIST = 0.01
STUDY = "datafactory_m1"
SOLVE_TIMEOUT_S = 900.0
QUOTA_TRIALS = 120
QUOTA_WALL_H = 3.0
MEDIAN_WALL_GATE_S = 50.0
MIN_ROWS_GATE = 100
DATASET_NAME = "datafactory_m1_mline_20260919"
REGISTRY_FOR_DEDUP = "factory_registry_20260917"
ROOT = REPO / "runs" / "data_factory_m1"
PLAN_PATH = ROOT / "plan.json"
INDEX_PATH = ROOT / "points_index.json"
JUDGMENT_PATH = ROOT / "judgment.json"


# ─── 纯逻辑（单测钉死面，零引擎零 IO） ────────────────────────────────────────

def w_fingerprint(w: float) -> int:
    """w_mm 查重指纹（round 1e-6；criteria 存量查重口径）。"""
    return round(float(w) * 1e6)


def _point_id(w: float, used: dict[str, float]) -> str:
    """点 id（m1_w<µm 四位>）；四舍五入撞名时追加序号守卫。"""
    base = f"m1_w{round(float(w) * 1000):04d}"
    if base not in used:
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    return f"{base}_{i}"


def build_sampling_plan(
    dedup_w: list[float],
    n_lhs: int = N_LHS,
    seed: int = LHS_SEED,
) -> dict[str, Any]:
    """采样计划（纯函数）：锚点预置 + LHS（避让锚点、剔除存量查重点）。

    LHS 池不足（查重吃掉过多）时按 seed+pool 序号续抽，至多 LHS_MAX_POOLS
    轮；仍不足则如实按实际量出计划（G3 门会如实红）。
    """
    from rfauto.optimization.sample_design import lhs_points

    anchors = [float(w) for w in ANCHOR_W]
    dedup_keys = {w_fingerprint(w) for w in dedup_w}
    kept: list[float] = []
    n_dropped = 0
    pool_seed = seed
    for _pool_i in range(LHS_MAX_POOLS):
        res = lhs_points(
            {"w_mm": (W_LOW, W_HIGH)}, LHS_POOL, seed=pool_seed,
            include=[{"w_mm": w} for w in anchors], min_dist=LHS_MIN_DIST)
        pool_seed += 1
        for pt in res["points"]:
            w = float(pt["w_mm"])
            if w_fingerprint(w) in dedup_keys:
                n_dropped += 1
                continue
            kept.append(w)
            if len(kept) >= n_lhs:
                break
        if len(kept) >= n_lhs:
            break
    kept = kept[:n_lhs]
    used: dict[str, float] = {}
    points: list[dict[str, Any]] = []
    for w in anchors + kept:
        pid = _point_id(w, used)
        used[pid] = w
        points.append({"point_id": pid, "w_mm": w, "line_len_mm": LINE_LEN_MM,
                       "is_anchor": w in anchors})
    return {
        "points": points,
        "stats": {
            "n_anchors": len(anchors),
            "n_lhs_requested": n_lhs,
            "n_lhs_kept": len(kept),
            "n_dedup_dropped": n_dropped,
            "n_plan_total": len(points),
            "lhs_seed": seed,
            "lhs_pool": LHS_POOL,
            "lhs_min_dist": LHS_MIN_DIST,
            "dedup_registry": REGISTRY_FOR_DEDUP,
            "dedup_n_existing_w": len({w_fingerprint(w) for w in dedup_w}),
        },
    }


def judge_m1(
    attempted: int,
    n_rows: int,
    walls_s: list[float],
    n_unhealthy: int = 0,
    n_skipped: int = 0,
    median_gate_s: float = MEDIAN_WALL_GATE_S,
    min_rows: int = MIN_ROWS_GATE,
) -> dict[str, Any]:
    """M1 三门判定（纯函数；criteria 三门，FAIL 如实不凑绿）。

    Args:
        attempted: 本批 solve 完成点数（成功+失败都计）。
        n_rows: 物化数据集行数。
        walls_s: 成功点逐点 solve 墙钟（秒）。
        n_unhealthy: health gate 拦截点数；n_skipped: 零点跳过 run 数。
    """
    row_rate = (float(n_rows) / attempted) if attempted > 0 else 0.0
    med = float(statistics.median(walls_s)) if walls_s else None
    g1 = attempted > 0 and n_rows == attempted
    g2 = med is not None and med <= float(median_gate_s)
    g3 = n_rows >= int(min_rows)
    gates = {
        "G1_row_rate_100pct": {
            "pass": bool(g1), "n_attempted": attempted, "n_rows": n_rows,
            "row_rate": round(row_rate, 6),
            "n_unhealthy": n_unhealthy, "n_skipped": n_skipped},
        "G2_median_wall_le_50s": {
            "pass": bool(g2), "median_wall_s": None if med is None else round(med, 2),
            "n_points": len(walls_s), "gate_s": float(median_gate_s)},
        "G3_rows_ge_100": {
            "pass": bool(g3), "n_rows": n_rows, "gate": int(min_rows)},
    }
    passed = bool(g1 and g2 and g3)
    fails = [k for k, g in gates.items() if not g["pass"]]
    verdict = "PASS" if passed else f"FAIL: {'; '.join(fails)}"
    return {"pass": passed, "verdict": verdict, "gates": gates}


def beta_metrics_from_port_beta(
    port_beta_csv: str | Path,
    band: tuple[float, float] = BAND_GHZ,
) -> dict[str, float] | None:
    """从 eval 目录 port_beta.csv 导 β 口径指标（参考面无关，#301）。

    εeff=(β·c/ω)²（带内中位 β、带心中位频率）；并列 ZL Re 带内中位。
    文件缺失/带内无点/无 β 列 → 返回 None（调用方降级 S21 斜率路径并记
    note——斜率口径 L=参数线长，但参考面含馈段（#329 port_ut 头证据），
    仅留档不消费）。
    """
    try:
        rows = list(csv.DictReader(
            Path(port_beta_csv).read_text(encoding="utf-8").splitlines()))
    except OSError:
        return None
    if not rows or "freq_hz" not in rows[0]:
        return None
    band_rows = [r for r in rows
                 if band[0] * 1e9 <= float(r["freq_hz"]) <= band[1] * 1e9]
    betas: list[float] = []
    zl1: list[float] = []
    zl2: list[float] = []
    for r in band_rows:
        for key in ("beta_rad_per_m", "beta2_rad_per_m"):
            v = r.get(key)
            if v not in (None, ""):
                betas.append(float(v))
        for key, out in (("re_zl1_ohm", zl1), ("re_zl2_ohm", zl2)):
            v = r.get(key)
            if v not in (None, ""):
                out.append(float(v))
    if not betas:
        return None
    beta_med = float(statistics.median(betas))
    f_med = float(statistics.median(float(r["freq_hz"]) for r in band_rows))
    return {
        "eps_eff_beta_mean_in_band": (beta_med * C0 / (2 * 3.141592653589793 * f_med)) ** 2,
        "beta_med_rad_per_m": beta_med,
        "zl1_re_ohm_med_in_band": float(statistics.median(zl1)) if zl1 else None,
        "zl2_re_ohm_med_in_band": float(statistics.median(zl2)) if zl2 else None,
    }


def compute_point_metrics(
    network: Any,
    band: tuple[float, float] = BAND_GHZ,
    line_len_mm: float = LINE_LEN_MM,
    port_beta_csv: str | Path | None = None,
) -> tuple[dict[str, float], list[str]]:
    """单点指标（确定性内核复用 SpecEvaluator；数值只出内核）。

    eps_eff 走 eps_eff_band_average 相位斜率内核——#255 守卫如实：
    返回 None 时键缺省 + note 记跳过原因，禁填占位数值。
    port_beta_csv 提供时并列 β 口径 eps_eff_beta_mean_in_band（参考面
    无关，首选消费列）+ ZL 中位列；S21 斜率口径键保留留档（其 L 语义
    含端口参考面外长度，仅留档）。
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
    eps = SpecEvaluator.eps_eff_band_average(network, lo, hi, line_len_mm)
    if eps is None:
        notes.append(
            "eps_eff_skipped: #255 守卫（带内 max|S11|>-10dB 或长度/频点/"
            "斜率前提不满足），不产出键")
    else:
        metrics["eps_eff_mean_in_band"] = float(eps)
    if port_beta_csv is not None:
        beta = beta_metrics_from_port_beta(port_beta_csv, band)
        if beta is None:
            notes.append("beta_metrics_skipped: port_beta.csv 缺失或带内无点")
        else:
            metrics["eps_eff_beta_mean_in_band"] = float(
                beta["eps_eff_beta_mean_in_band"])
            if beta.get("zl1_re_ohm_med_in_band") is not None:
                metrics["zl1_re_ohm_med_in_band"] = float(
                    beta["zl1_re_ohm_med_in_band"])
                metrics["zl2_re_ohm_med_in_band"] = float(
                    beta["zl2_re_ohm_med_in_band"])
            notes.append(
                "eps_eff 口径=β（CalcPort，参考面无关）；eps_eff_mean_in_band"
                "（S21 斜率×L）含端口参考面外长度仅留档")
    return metrics, notes


# ─── IO 面（真跑/落盘编排） ───────────────────────────────────────────────────

def existing_mline_w(
    dataset_name: str = REGISTRY_FOR_DEDUP,
) -> tuple[list[float], list[str]]:
    """存量数据集里 mline 行的 w_mm 清单（查重先于新算）。

    查询失败不阻塞采集（如实透出 error，查重退化为空集=全量新算）。
    """
    from rfauto.service.dataset_service import query_dataset

    res = query_dataset(dataset_name, model="mline",
                        columns=["params_json"], limit=100000)
    if not res.get("ok"):
        return [], [f"查重查询失败（按空集处理）: {res.get('errors')}"]
    ws: list[float] = []
    errs: list[str] = []
    for row in res.get("rows") or []:
        try:
            pj = json.loads(str(row.get("params_json") or "{}"))
        except (ValueError, TypeError):
            continue
        w = pj.get("w_mm")
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            errs.append(f"params_json.w_mm 非数值: {row.get('params_json')!r}")
            continue
        ws.append(float(w))
    return ws, errs


def write_run_products(
    run_dir: Path,
    w_mm: float,
    network: Any,
    wall_s: float,
    eval_dir: str,
    metrics: dict[str, float],
    notes: list[str],
    line_len_mm: float = LINE_LEN_MM,
    opt_params: dict[str, Any] | None = None,
) -> None:
    """把单点写成 api.run_once 兼容标准 run 产物（成行 ⑤ 分支契约）。

    布局：meta.json(status=done) + recipe.snapshot.yaml
    (optimization.params=变量键集) + results/metrics.json +
    results/params.s2p（2 端口，#248 扩展名契约）。
    opt_params：变量键集显式声明——缺省 {"w_mm"}（M1/M2
    1D 口径）；M3 扩 2D 时须传 {"w_mm":…, "line_len_mm":…}，否则第二维
    静默不入数据集行。
    """
    from rfauto.infra.run_store import snapshot_recipe, write_meta

    recipe: dict[str, Any] = {
        "model": TEMPLATE,
        "study": STUDY,
        "params": {
            "w_mm": {"value": float(w_mm), "unit": "mm"},
            "line_len_mm": {"value": line_len_mm, "unit": "mm"},
        },
        "optimization": {"params": opt_params or {"w_mm": {"low": W_LOW, "high": W_HIGH}}},
        "setup": {"freq_range_ghz": list(FREQ_RANGE_GHZ), "points": 41},
        "notes": "datafactory_m1 采集点（runs/data_factory_m1/criteria.md 预声明）",
    }
    snapshot_recipe(run_dir, recipe)
    payload = {
        "metrics": metrics,
        "notes": notes,
        "band_ghz": list(BAND_GHZ),
        "w_mm": float(w_mm),
        "line_len_mm": LINE_LEN_MM,
        "freq_range_ghz": list(FREQ_RANGE_GHZ),
    }
    (run_dir / "results" / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    network.write_touchstone(str(run_dir / "results" / "params.s2p"))
    write_meta(run_dir, {
        "status": "done",
        "model": TEMPLATE,
        "adapter": "openems",
        "study_name": STUDY,
        "algorithm": "lhs_collect",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "wall_s": round(float(wall_s), 2),
        "w_mm": float(w_mm),
        "line_len_mm": LINE_LEN_MM,
        "mesh_resolution_mm": 0.0,
        "freq_range_ghz": list(FREQ_RANGE_GHZ),
        "cache_env": os_cache_state(),
        "eval_dir": str(eval_dir),
        "source": "datafactory_m1",
    }, run_id=run_dir.name)


def os_cache_state() -> str:
    """缓存环境态（采集期=开，criteria 预声明；记录进 meta 供审计）。"""
    import os

    raw = os.environ.get("RFAUTO_CACHE", "")
    return raw if raw else "unset(readwrite default)"


def _load_or_build_plan(dedup_w: list[float]) -> dict[str, Any]:
    """首次生成后不可变的采样计划（resume 同计划；#322 指纹折叠教训）。"""
    if PLAN_PATH.exists():
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan = build_sampling_plan(dedup_w)
    ROOT.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan


def _load_index() -> dict[str, Any]:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def _save_index(index: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def done_run_ids(index: dict[str, Any]) -> list[str]:
    """index 里 status=done 的 rid（物化输入；落盘序稳定）。"""
    return [row["rid"] for pid, row in sorted(index.items())
            if isinstance(row, dict) and row.get("status") == "done"]


def run_collect(repo_root: Path, n_lhs: int = N_LHS, seed: int = LHS_SEED) -> int:
    """真机批量采集（OE 串行 1 独占时段；断点 resume 幂等）。"""
    if str(Path.cwd().resolve()) != str(repo_root.resolve()):
        print(f"[m1] 拒跑：cwd 必须是仓库根 {repo_root}（当前 {Path.cwd()}）")
        return 2
    from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir
    from rfauto.pipeline.quota_guard import QuotaExceededError, QuotaGuard, QuotaLimits
    from rfauto.service.dataset_service import materialize_dataset

    dedup_w, dedup_errs = existing_mline_w()
    plan = _load_or_build_plan(dedup_w)
    index = _load_index()
    print(f"[m1] plan={plan['stats']['n_plan_total']} 点 "
          f"(锚 {plan['stats']['n_anchors']} + LHS {plan['stats']['n_lhs_kept']}，"
          f"查重剔除 {plan['stats']['n_dedup_dropped']}；缓存态 {os_cache_state()})")
    for e in dedup_errs[:5]:
        print(f"[m1][warn] {e}")

    evals_root = ROOT / "evals"
    adapter = OpenEMSOptAdapter(
        FREQ_RANGE_GHZ, template=TEMPLATE, substrate=SUBSTRATE,
        solve_timeout_s=SOLVE_TIMEOUT_S, work_root=evals_root)
    guard = QuotaGuard(QuotaLimits(max_trials=QUOTA_TRIALS, max_wall_hours=QUOTA_WALL_H))
    t0 = time.time()
    walls: list[float] = []
    ingest_checked = False
    partial = False
    try:
        for pt in plan["points"]:
            pid = str(pt["point_id"])
            row = index.get(pid)
            if isinstance(row, dict) and row.get("status") == "done":
                walls.append(float(row["wall_s"]))
                continue
            guard.check_trial(len(walls))
            guard.check_wall_time(t0)
            w = float(pt["w_mm"])
            rid = generate_run_id()
            run_dir = create_run_dir(repo_root, rid)
            eval_n = len(list(evals_root.glob("eval_*"))) + 1
            adapter.set_variables({"w_mm": w, "line_len_mm": LINE_LEN_MM})
            t_solve = time.monotonic()
            rep = adapter.solve(timeout_s=SOLVE_TIMEOUT_S)
            solve_wall = time.monotonic() - t_solve
            if not rep.success:
                index[pid] = {"status": "failed", "rid": rid,
                              "msg": str(rep.message)[:300]}
                _save_index(index)
                print(f"[m1] {pid} FAIL solve: {rep.message}")
                continue
            net = adapter.get_sparams()
            port_beta = evals_root / f"eval_{eval_n:04d}" / "port_beta.csv"
            metrics, notes = compute_point_metrics(net, port_beta_csv=port_beta)
            write_run_products(run_dir, w, net, solve_wall,
                               str(adapter.eval_root), metrics, notes)
            index[pid] = {"status": "done", "rid": rid, "w_mm": w,
                          "wall_s": round(solve_wall, 2)}
            _save_index(index)
            walls.append(solve_wall)
            eps = metrics.get("eps_eff_mean_in_band")
            print(f"[m1] {pid} rid={rid} wall={solve_wall:.1f}s "
                  f"s11_max={metrics['s11_db_max_in_band']:.2f}dB "
                  f"eps_eff={eps if eps is not None else 'skipped'}")
            # 放量纪律（#251④）：首点 ingest 核对成行（materialize 1 点探针）
            # 通过才继续批量；探针数据集固定名幂等覆盖（非归档）
            if not ingest_checked:
                probe = materialize_dataset(
                    run_ids=[rid], name="datafactory_m1_ingest_probe",
                    health_gate=True)
                n_probe = int(probe.get("n_rows") or 0)
                if not probe.get("ok") or n_probe != 1:
                    print(f"[m1] 首点 ingest 核对失败（ok={probe.get('ok')} "
                          f"n_rows={n_probe} errors={probe.get('errors')} "
                          f"unhealthy={probe.get('unhealthy_runs')}）——停批排查")
                    return 1
                print("[m1] 首点 ingest 核对 OK（1 行成行，health gate 不拦）")
                ingest_checked = True
    except QuotaExceededError as exc:
        partial = True
        print(f"[m1] quota 停批（PARTIAL 判定，已完成点照常入库）: {exc}")

    rids = done_run_ids(index)
    n_done = len(rids)
    n_failed = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "failed")
    attempted = n_done + n_failed
    print(f"[m1] 批量墙钟 {time.time() - t0:.0f}s；done={n_done} failed={n_failed}")
    ok_mat, n_unhealthy, n_skipped = materialize_from_index(index)
    judgment = judge_m1(attempted, ok_mat, walls,
                        n_unhealthy=n_unhealthy, n_skipped=n_skipped)
    judgment["partial_budget"] = partial
    if partial:
        judgment["verdict"] = f"PARTIAL(超预算): {judgment['verdict']}"
    judgment["meta"] = {
        "plan": plan["stats"], "n_failed": n_failed,
        "dataset": DATASET_NAME, "n_rows": ok_mat,
        "quota": {"trials": QUOTA_TRIALS, "wall_hours": QUOTA_WALL_H},
        "batch_wall_s": round(time.time() - t0, 1),
        "cache_env": os_cache_state(),
    }
    JUDGMENT_PATH.write_text(
        json.dumps(judgment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[m1] 判读: {judgment['verdict']}")
    for k, g in judgment["gates"].items():
        print(f"  {k}: pass={g['pass']} {g}")
    return 0 if judgment["pass"] else 1


def materialize_from_index(index: dict[str, Any]) -> tuple[int, int, int]:
    """由 index 的 done 点物化数据集，返回 (n_rows, n_unhealthy, n_skipped)。

    失败返回 (-1, 0, 0)。
    """
    from rfauto.service.dataset_service import materialize_dataset

    rids = done_run_ids(index)
    if not rids:
        print("[m1] 无 done 点可物化")
        return -1, 0, 0
    mat = materialize_dataset(run_ids=rids, name=DATASET_NAME, health_gate=True)
    if not mat.get("ok"):
        print(f"[m1] 物化失败: {mat.get('errors')}")
        return -1, 0, 0
    n_unh = len(mat.get("unhealthy_runs") or [])
    n_skip = len(mat.get("skipped_runs") or [])
    print(f"[m1] 物化 ok rows={mat.get('n_rows')} "
          f"unhealthy={n_unh} skipped={n_skip} dup={mat.get('n_dup')}")
    return int(mat.get("n_rows") or 0), n_unh, n_skip


def run_judge() -> int:
    """三门判读（幂等离线重跑；输入=index + 已物化数据集）。"""
    index = _load_index()
    if not index:
        print("[m1] 无 points_index（先 --collect）")
        return 2
    from rfauto.service.dataset_service import query_dataset

    q = query_dataset(DATASET_NAME, model="mline", limit=100000)
    n_rows = int(q.get("n_rows") or 0) if q.get("ok") else 0
    walls = [float(r["wall_s"]) for r in index.values()
             if isinstance(r, dict) and r.get("status") == "done"]
    n_failed = sum(1 for r in index.values()
                   if isinstance(r, dict) and r.get("status") == "failed")
    judgment = judge_m1(len(walls) + n_failed, n_rows, walls)
    judgment["meta"] = {"dataset": DATASET_NAME, "dataset_ok": bool(q.get("ok")),
                        "n_failed": n_failed}
    JUDGMENT_PATH.write_text(
        json.dumps(judgment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[m1] 判读: {judgment['verdict']}")
    for k, g in judgment["gates"].items():
        print(f"  {k}: pass={g['pass']} {g}")
    return 0 if judgment["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="M1 数据面采集管线（criteria 预声明判据）")
    ap.add_argument("--plan", action="store_true", help="打印采样计划与查重统计")
    ap.add_argument("--collect", action="store_true", help="真机批量采集")
    ap.add_argument("--materialize", action="store_true", help="物化数据集")
    ap.add_argument("--judge", action="store_true", help="三门判读")
    ap.add_argument("--n-lhs", type=int, default=N_LHS)
    ap.add_argument("--seed", type=int, default=LHS_SEED)
    args = ap.parse_args(argv)
    chosen = sum(1 for f in (args.plan, args.collect, args.materialize, args.judge) if f)
    if chosen != 1:
        ap.print_help()
        return 2
    if args.plan:
        dedup_w, errs = existing_mline_w()
        plan = build_sampling_plan(dedup_w, n_lhs=args.n_lhs, seed=args.seed)
        print(json.dumps(plan["stats"], ensure_ascii=False, indent=1))
        for pt in plan["points"][:10]:
            print(f"  {pt['point_id']}: w={pt['w_mm']:.4f}"
                  f"{' [anchor]' if pt['is_anchor'] else ''}")
        print(f"  ...（共 {len(plan['points'])} 点，全量见 --collect 生成 plan.json）")
        for e in errs[:3]:
            print(f"  [warn] {e}")
        return 0
    if args.collect:
        return run_collect(REPO, n_lhs=args.n_lhs, seed=args.seed)
    if args.materialize:
        n, _unh, _skip = materialize_from_index(_load_index())
        return 0 if n >= 0 else 1
    return run_judge()


if __name__ == "__main__":
    sys.exit(main())
