"""M4·代理寻优（查库存）vs HFSS 基线墙钟账。

判据/口径全部预声明 runs/datafactory_m4/criteria.md（写死再跑）。
链路：M1 库存（120 点 parquet，只读）→ smt_kriging GP 训练（墙钟实测）→
run_surrogate_loop 代理寻优（evaluate_fn=GP 查询，环内零现算零真跑，
max_real=25 对齐 wp39 预算）→ 验证点选择（环最优 + GP 预测最深优先，
≤5 点）→ openEMS 真验证（双缓存关 RFAUTO_CACHE=off + cache=False，
OE 串行 1 守卫 #261）→ G2 墙钟/cost 双门判读 → m4_verdict.json。

判据内核复用 service/wp39_benchmark.py：wallclock_ratio（:69）与
cost_degradation_pct（:55）——judge_problem_pair 同一原语族，本脚本不内联
任何判据公式。数值只在确定性内核。

用法（cwd=仓库根）：
  python scripts/factory_m4_bench.py --selftest  # 纯函数面+合成 GP 冒烟（零真机）
  python scripts/factory_m4_bench.py --offline   # 库存加载+GP 训练+代理寻优（零真机）
  python scripts/factory_m4_bench.py --verify    # 真机验证腿（≤5 点，断点 resume 幂等）
  python scripts/factory_m4_bench.py --judge     # 判读（幂等离线重跑）
  python scripts/factory_m4_bench.py --verify-refine  # M4 run2 谷芯加密验证（criteria_v2）
  python scripts/factory_m4_bench.py --judge-refine   # run2 幂等离线重判

退出码：--verify/--judge/--verify-refine 0=PASS；1=门未达/执行失败；2=参数错误。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

__all__ = [
    "m4_account",
    "m4_cost",
    "refine_best_of",
    "refine_gate_pass",
    "refine_points",
    "refine_threshold_db",
    "select_verify_points",
    "stock_best",
    "violation_db",
    "window_max_step_um",
]

# ─── 预声明常量（criteria.md 同源，改门先改 criteria 再改这里） ────────────────
DATASET_DIR = REPO / "runs" / "datasets" / "datafactory_m1_mline_20260919"
ROOT = REPO / "runs" / "datafactory_m4"
OFFLINE_PATH = ROOT / "m4_offline.json"
VERIFY_INDEX_PATH = ROOT / "verify_index.json"
VERDICT_PATH = ROOT / "m4_verdict.json"
CRITERIA_PATH = ROOT / "criteria.md"

TEMPLATE = "mline"
SUBSTRATE = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}  # rogers4350b 锚口径
FREQ_RANGE_GHZ = (2.0, 3.0)
BAND_GHZ = (2.4, 2.6)
LINE_LEN_MM = 40.0
W_LOW, W_HIGH = 0.5, 2.0
S11_KEY = "s11_db_max_in_band"

SEED = 42
N_INIT = 10
MAX_REAL = 25            # wp39 BUDGET_DEFAULT 对齐（criteria 预声明）
SOLVE_TIMEOUT_S = 900.0  # 单点墙钟帽（防挂死，非预算门）
MAX_VERIFY = 5
MIN_DIST_VERIFY = 0.02   # 归一化域 [0.5,2.0] 距离（criteria 预声明）
GRID_STEP_MM = 0.001

BASELINE_S = 1457.74     # wp39 mline pattern_search 15 评估
RATIO_GATE = 0.2         # T_factory ≤ 基线 1/5（wp39 内核取 0.2，严于主线 0.5）
DEG_GATE_PCT = 5.0       # cost 劣化 ≤5%（wp39 同门）
BUDGET_WALL_S = 90 * 60.0
BUDGET_PARTIAL_S = 90 * 60.0 * 1.5

C_COLLECT_MEASURED_S = 4197.5   # M1 120 点 Σwall 实测（points_index）
C_COLLECT_NOMINAL_S = 120 * 35.8  # 名义单点墙钟（旁注）

#: #261 OE 互斥标记（本仓 openEMS=python 进程内 FDTD.Run，tasklist 守卫无效）
OE_GUARD_MARKERS = r"_rfauto_runner|simulation\.py|factory_m1_collect"
OE_GUARD_WAIT_S = 60.0
OE_GUARD_MAX_TRIES = 3

# ─── M4 run2 谷芯加密验证常量（criteria_v2_refine.md 同源，改门先改它再改这里） ──
REFINE_CRITERIA_PATH = ROOT / "criteria_v2_refine.md"
REFINE_OFFLINE_PATH = ROOT / "refine_offline_v2.json"
REFINE_INDEX_PATH = ROOT / "refine_index_v2.json"
REFINE_EVALS_ROOT = ROOT / "refine_evals_v2"
VERDICT_V2_PATH = ROOT / "verdict_v2_refine.json"

REFINE_ANCHOR_A_MM = 0.910346   # 库存最优（写死舍入值；门分母用 parquet 全精度）
REFINE_ANCHOR_B_MM = 0.905512   # 环最优（run1 v1 已实测 −48.3801，不重跑）
REFINE_OFFSETS_A_UM = (0.5, 1.0, 1.5, 2.0, 3.0)
REFINE_OFFSETS_B_UM = (1.0, 2.0)
REFINE_DEDUP_UM = 1.0           # 贪心去重阈（恰 1.0µm 距保留）
REFINE_MAX_POINTS = 10          # 帽：9 谷芯点 + 1 锚复现 ra
REFINE_ANCHOR_REPRO_W_MM = 0.910346  # ra：库存最优复跑（诊断，不进门不替代分母）
REFINE_GATE_FACTOR = 0.95       # 门阈 = 库存最优 × 0.95（预声明直比形式）

BUDGET_WALL_S_V2 = 40 * 60.0
BUDGET_PARTIAL_S_V2 = 40 * 60.0 * 1.5
QUOTA_TRIALS_V2 = 10            # QuotaGuard(10, 0.5h)（criteria_v2 预声明）
QUOTA_WALL_H_V2 = 0.5

LOCK_PATH = REPO / "runs" / ".oe_collect.lock"  # 与并行 M3 采集任务互斥
LOCK_POLL_S = 60.0
LOCK_PER_POINT_WAIT_S = 20 * 60.0

GP_PROFILE_LO_MM = 0.9030       # 窗内 GP 预测剖面（次级量）
GP_PROFILE_HI_MM = 0.9140
GP_PROFILE_STEP_MM = 0.0001


# ─── 纯逻辑（selftest 钉死面，零引擎零 IO） ──────────────────────────────────

def violation_db(s11_db: float, threshold_db: float = -40.0) -> float:
    """max_below 违约量：带内 max|S11| 超 threshold 的部分（环 objective 语义）。"""
    v = float(s11_db)
    t = float(threshold_db)
    return max(0.0, v - t)


def stock_best(
    samples: list[dict[str, Any]], key: str = S11_KEY
) -> tuple[float, float]:
    """库存最优真值点：(w_mm, min metric)。空/全非有限 → ValueError（不猜）。"""
    best: tuple[float, float] | None = None
    for s in samples:
        v = s.get("metrics", {}).get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not math.isfinite(float(v)):
            continue
        w = float(s["params"]["w_mm"])
        if best is None or float(v) < best[1]:
            best = (w, float(v))
    if best is None:
        raise ValueError(f"库存无可用 {key} 行")
    return best


def select_verify_points(
    loop_best_w: float,
    predict_fn: Callable[[float], float],
    lo: float = W_LOW,
    hi: float = W_HIGH,
    step_mm: float = GRID_STEP_MM,
    k: int = MAX_VERIFY,
    min_dist: float = MIN_DIST_VERIFY,
) -> list[float]:
    """验证点选择（criteria 预声明策略，纯函数）。

    v1 = 环最优（loop_best_w，原值不吸附）；v2..vK = 稠密网格预测值升序
    （最深优先），逐个过滤与已选点归一化距离 < min_dist 者。非有限预测
    剔除；候选不足 k 如实按实际量返回。
    """
    span = max(hi - lo, 1e-12)
    selected = [float(loop_best_w)]

    def ndist(a: float, b: float) -> float:
        return abs(a - b) / span

    grid: list[tuple[float, float]] = []
    n_steps = round((hi - lo) / step_mm)
    for i in range(n_steps + 1):
        w = lo + i * step_mm
        p = float(predict_fn(w))
        if math.isfinite(p):
            grid.append((w, p))
    grid.sort(key=lambda t: t[1])
    for w, _p in grid:
        if len(selected) >= k:
            break
        if all(ndist(w, s) >= min_dist for s in selected):
            selected.append(w)
    return selected


def refine_points(
    anchor_a_mm: float = REFINE_ANCHOR_A_MM,
    anchor_b_mm: float = REFINE_ANCHOR_B_MM,
    offsets_a_um: tuple[float, ...] = REFINE_OFFSETS_A_UM,
    offsets_b_um: tuple[float, ...] = REFINE_OFFSETS_B_UM,
    dedup_um: float = REFINE_DEDUP_UM,
    cap: int = REFINE_MAX_POINTS - 1,
) -> tuple[list[float], list[dict[str, Any]]]:
    """谷芯加密验证点构造（criteria_v2 预声明，纯函数，整数 nm 运算）。

    两锚 ± 偏移全组合（锚自身不重跑：A=库存最优=门分母、B=环最优 run1
    已测）→ 升序贪心去重（与已保留点距 < dedup_um 者剔除，恰等保留）
    → cap 帽（超帽按升序截断）。返回 (保留 w_mm 列表, 剔除轨迹)。
    """
    a_nm = round(anchor_a_mm * 1e6)
    b_nm = round(anchor_b_mm * 1e6)
    cand: set[int] = set()
    for off in offsets_a_um:
        o = round(off * 1000.0)
        cand.update((a_nm - o, a_nm + o))
    for off in offsets_b_um:
        o = round(off * 1000.0)
        cand.update((b_nm - o, b_nm + o))
    dedup_nm = round(dedup_um * 1000.0)
    kept: list[int] = []
    dropped: list[dict[str, Any]] = []
    for w in sorted(cand):
        near = next((k for k in kept if abs(w - k) < dedup_nm), None)
        if near is not None:
            dropped.append({"w_mm": w / 1e6,
                            "reason": f"dup<{dedup_um}um@{near / 1e6}"})
        elif len(kept) >= cap:
            dropped.append({"w_mm": w / 1e6, "reason": "cap"})
        else:
            kept.append(w)
    return [w / 1e6 for w in kept], dropped


def window_max_step_um(
    pts_mm: list[float], lo_mm: float, hi_mm: float
) -> float | None:
    """两锚窗 (lo,hi) 内相邻验证点最大步距（µm，含锚边界）；窗内无点 → None。"""
    inside = sorted(w for w in pts_mm if lo_mm < w < hi_mm)
    if not inside:
        return None
    seq = [float(lo_mm), *inside, float(hi_mm)]
    return max(seq[i + 1] - seq[i] for i in range(len(seq) - 1)) * 1000.0


def refine_best_of(
    index: dict[str, Any],
) -> tuple[float, float, str] | None:
    """refine 谷芯最优（排除 ra 锚复现/skipped/failed/_batch 元键）。

    返回 (w_mm, s11_db_max_in_band, vid)；无成功 refine 点 → None
    （fail-closed，#367 语义：判缺 `is not None`）。
    """
    best: tuple[float, float, str] | None = None
    for vid, row in index.items():
        if vid.startswith("_") or not isinstance(row, dict) or vid == "ra":
            continue
        if row.get("status") != "done" or row.get("source") != "refine":
            continue
        v = row.get("s11_db_max_in_band")
        if not isinstance(v, (int, float)) or isinstance(v, bool) \
                or not math.isfinite(float(v)):
            continue
        if best is None or float(v) < best[1]:
            best = (float(row["w_mm"]), float(v), str(vid))
    return best


def refine_threshold_db(
    stock_best_db: float, factor: float = REFINE_GATE_FACTOR
) -> float:
    """cost 门 v2 阈值：库存最优 × 0.95（单次舍入，预声明主形式）。"""
    return float(stock_best_db) * float(factor)


def refine_gate_pass(refine_best_db: float | None, threshold_db: float) -> bool:
    """cost 门 v2 主判：refine_best ≤ 阈值（直比，单次舍入）。

    与 wp39 劣化 ≤5.0% 数学等价；阈值恰点两者浮点差 ~1e-14（两次舍入
    vs 一次舍入），低于实测分辨率，判据以直比为准（criteria_v2 预声明）。
    None → False（fail-closed）。
    """
    return refine_best_db is not None and float(refine_best_db) <= float(threshold_db)


def m4_account(
    t_gp_fit_s: float,
    t_loop_s: float,
    t_select_s: float,
    verify_walls_s: list[float],
    baseline_s: float = BASELINE_S,
    ratio_gate: float = RATIO_GATE,
) -> dict[str, Any]:
    """G2 墙钟账（纯函数；ratio 用 wp39 wallclock_ratio 内核）。"""
    from rfauto.service.wp39_benchmark import wallclock_ratio

    walls = [float(w) for w in verify_walls_s if w is not None]
    t_verify = float(sum(walls))
    t_factory = float(t_gp_fit_s) + float(t_loop_s) + float(t_select_s) + t_verify
    ratio = wallclock_ratio(t_factory, float(baseline_s))
    ratio_ok = ratio is not None and ratio <= float(ratio_gate)
    reasons: list[str] = []
    if ratio is None:
        reasons.append(f"ratio 不可判定（基线墙钟 {baseline_s}s 非正）")
    elif not ratio_ok:
        reasons.append(
            f"墙钟超门：ratio={ratio:.4f} > {ratio_gate}"
            f"（T_factory={t_factory:.2f}s vs 基线 {baseline_s}s）")
    return {
        "t_gp_fit_s": round(float(t_gp_fit_s), 3),
        "t_loop_s": round(float(t_loop_s), 3),
        "t_select_s": round(float(t_select_s), 3),
        "t_verify_total_s": round(t_verify, 3),
        "n_verify": len(walls),
        "verify_walls_s": [round(w, 3) for w in walls],
        "t_factory_s": round(t_factory, 3),
        "baseline_s": float(baseline_s),
        "ratio": None if ratio is None else round(ratio, 4),
        "ratio_gate": float(ratio_gate),
        "ratio_ok": bool(ratio_ok),
        "reasons": reasons,
    }


def m4_cost(
    cost_best_verif: float | None,
    cost_stock_best: float,
    deg_gate_pct: float = DEG_GATE_PCT,
) -> dict[str, Any]:
    """G2 cost 账（纯函数；劣化用 wp39 cost_degradation_pct 内核）。

    #367：0.0 是合法测值非缺失——判缺一律 `is not None`，`or` 缺省禁用。
    """
    from rfauto.service.wp39_benchmark import cost_degradation_pct

    if cost_best_verif is None:
        return {
            "cost_best_verif_db": None,
            "cost_stock_best_db": float(cost_stock_best),
            "degradation_pct": None,
            "deg_gate_pct": float(deg_gate_pct),
            "deg_ok": False,
            "reasons": ["无成功验证点（真验证全失败或未跑），cost 门不可判 → FAIL"],
        }
    deg = cost_degradation_pct(float(cost_best_verif), float(cost_stock_best))
    deg_ok = deg is not None and deg <= float(deg_gate_pct)
    reasons: list[str] = []
    if deg is None:
        reasons.append("劣化不可判定（库存最优真值恒 0）")
    elif not deg_ok:
        reasons.append(
            f"cost 劣化超门：{deg:+.2f}% > {deg_gate_pct}%"
            f"（Δ={float(cost_best_verif) - float(cost_stock_best):+.4f} dB）")
    return {
        "cost_best_verif_db": float(cost_best_verif),
        "cost_stock_best_db": float(cost_stock_best),
        "degradation_pct": None if deg is None else round(deg, 4),
        "deg_gate_pct": float(deg_gate_pct),
        "deg_ok": bool(deg_ok),
        "reasons": reasons,
    }


# ─── IO/编排面 ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_sha() -> str:
    """provenance best-effort（#105：失败记 unknown 不阻断）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def load_stock() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """M1 库存加载（只读；t_load 单列不进门，criteria 口径）。"""
    t0 = time.perf_counter()
    path = DATASET_DIR / "points.parquet"
    df = pd.read_parquet(path)
    samples: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        params = json.loads(row["params_json"])
        metrics = json.loads(row["metrics_json"])
        samples.append({"params": {k: float(v) for k, v in params.items()},
                        "metrics": {k: float(v) for k, v in metrics.items()
                                    if isinstance(v, (int, float))
                                    and not isinstance(v, bool)
                                    and math.isfinite(float(v))}})
    meta = {
        "path": str(path.relative_to(REPO)),
        "n_rows": len(df),
        "t_load_s": round(time.perf_counter() - t0, 3),
    }
    return samples, meta


def fit_stock_gp(samples: list[dict[str, Any]]) -> tuple[Any, float]:
    """库存 GP 拟合（smt_kriging，registry 缺省 theta0 不调参）；返回 (model, wall)。"""
    from rfauto.optimization.surrogate import surrogate_registry

    model = surrogate_registry.create("smt_kriging", config={
        "bounds": {"w_mm": (W_LOW, W_HIGH)},
        "metrics": [S11_KEY],
    })
    t0 = time.perf_counter()
    model.fit(samples)
    wall = time.perf_counter() - t0
    if not getattr(model, "fitted", False):
        raise RuntimeError("库存 GP 拟合失败（fitted=False）")
    return model, wall


def run_loop(model: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """代理寻优环（evaluate_fn=GP 查询，环内零真跑）；返回 (环结果, 计时)。"""
    from rfauto.core.objectives import Objective
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    objectives = [Objective(metric="s11_db", band=list(BAND_GHZ),
                            op="max_below", value=-40.0, weight=1.0)]
    query = {"n": 0, "total_s": 0.0}

    def evaluate_fn(params: dict[str, float]) -> dict[str, float]:
        t0 = time.perf_counter()
        pred = model.predict(dict(params))
        query["n"] += 1
        query["total_s"] += time.perf_counter() - t0
        return {S11_KEY: float(pred[S11_KEY])}

    bounds = {"w_mm": (W_LOW, W_HIGH)}
    t0 = time.perf_counter()
    res = run_surrogate_loop(
        bounds, objectives, evaluate_fn,
        n_init=N_INIT, max_real=MAX_REAL,
        surrogate_kind="smt_kriging",
        surrogate_config={"bounds": bounds},
        seed=SEED)
    wall = time.perf_counter() - t0
    timing = {"t_loop_s": wall, "n_queries": query["n"],
              "t_query_total_s": query["total_s"],
              "loop_elapsed_s": float(res.get("elapsed_s") or 0.0)}
    return res, timing


def select_candidates(model: Any, loop_best_w: float) -> tuple[list[float], float]:
    """验证点选择（criteria 策略）；返回 (点列表, 选择腿墙钟)。"""
    t0 = time.perf_counter()
    pts = select_verify_points(
        loop_best_w, lambda w: float(model.predict({"w_mm": w})[S11_KEY]))
    return pts, time.perf_counter() - t0


def run_offline() -> int:
    """离线腿：库存加载→GP 训练→代理寻优→验证点计划；落 m4_offline.json。"""
    if str(Path.cwd().resolve()) != str(REPO.resolve()):
        print(f"[m4] 拒跑：cwd 必须是仓库根 {REPO}（当前 {Path.cwd()}）")
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    samples, load_meta = load_stock()
    if load_meta["n_rows"] != 120:
        print(f"[m4] 库存行数异常：{load_meta['n_rows']} != 120（criteria 口径）")
        return 1
    sb_w, sb_v = stock_best(samples)
    print(f"[m4] 库存 {load_meta['n_rows']} 行加载 {load_meta['t_load_s']}s；"
          f"最优真值 {sb_v:.4f} dB @ w={sb_w:.6f} mm")

    model, t_gp = fit_stock_gp(samples)
    print(f"[m4] 库存 GP 拟合 {t_gp:.3f}s")

    loop, timing = run_loop(model)
    if not loop.get("ok"):
        print(f"[m4] 代理寻优环失败：{loop.get('errors') or loop.get('stop_reason')}")
        return 1
    best = loop.get("best") or {}
    best_w = float(best["params"]["w_mm"])
    print(f"[m4] 环完成 wall={timing['t_loop_s']:.2f}s "
          f"(elapsed_s 旁证 {timing['loop_elapsed_s']}s) stop={loop.get('stop_reason')} "
          f"n_real={loop.get('n_real_used')} n_attempts={loop.get('n_attempts')} "
          f"查询 {timing['n_queries']} 次累计 {timing['t_query_total_s']:.3f}s；"
          f"best w={best_w:.6f} cost={best.get('cost')}")

    cand_w, t_select = select_candidates(model, best_w)
    verify_plan = []
    for i, w in enumerate(cand_w, start=1):
        pred = float(model.predict({"w_mm": w})[S11_KEY])
        verify_plan.append({"vid": f"v{i}", "w_mm": round(w, 9),
                            "pred_s11_db": round(pred, 4),
                            "source": "loop_best" if i == 1 else "gp_ranked"})
        print(f"[m4] 验证点 v{i}: w={w:.6f} pred={pred:.3f} dB "
              f"({'环最优' if i == 1 else 'GP 排序'})")
    print(f"[m4] 验证点选择 {t_select:.3f}s（{len(cand_w)} 点）")

    loop_slim = {k: v for k, v in loop.items() if k != "failures"}
    payload = {
        "schema_version": 1,
        "created_at": _now_iso(),
        "git_sha": git_sha(),
        "criteria": {
            "baseline_s": BASELINE_S, "ratio_gate": RATIO_GATE,
            "deg_gate_pct": DEG_GATE_PCT, "max_verify": MAX_VERIFY,
            "min_dist_verify": MIN_DIST_VERIFY, "grid_step_mm": GRID_STEP_MM,
            "seed": SEED, "n_init": N_INIT, "max_real": MAX_REAL,
            "objective": "s11_db band [2.4,2.6] max_below -40",
            "surrogate": "smt_kriging(registry default theta0)",
            "criteria_md": str(CRITERIA_PATH.relative_to(REPO)),
        },
        "stock": {
            **load_meta,
            "best_w_mm": sb_w, "best_s11_db": sb_v,
            "c_collect_measured_s": C_COLLECT_MEASURED_S,
            "c_collect_nominal_s": C_COLLECT_NOMINAL_S,
        },
        "t_gp_fit_s": t_gp,
        "timing": timing,
        "loop": loop_slim,
        "verify_plan": verify_plan,
        "t_select_s": t_select,
    }
    OFFLINE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[m4] 离线产物 → {OFFLINE_PATH.relative_to(REPO)}")
    return 0


def oe_guard_check() -> dict[str, Any]:
    """OE 串行 1 守卫（#261）：查 python 命令行他轨 OE 进程，存在则等待重探。

    返回 {busy, attempts, pids}；超过重试次数仍 busy → busy=True（调用方
    如实弃跑该点，不杀不抢）。
    """
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" "
        "-ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match '"
        + OE_GUARD_MARKERS + "' } | Select-Object ProcessId,CommandLine | "
        "ConvertTo-Json -Compress")
    pids: list[dict[str, Any]] = []
    for attempt in range(1, OE_GUARD_MAX_TRIES + 1):
        pids = []
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=60)
            txt = (out.stdout or "").strip()
            if txt:
                data = json.loads(txt)
                rows = data if isinstance(data, list) else [data]
                for r in rows:
                    try:
                        pid = int(r.get("ProcessId"))
                    except (TypeError, ValueError):
                        continue
                    pids.append({"pid": pid,
                                 "cmd": str(r.get("CommandLine"))[:200]})
        except Exception as exc:  # 守卫是 best-effort（#105），失败不静默放行：
            # 记 unknown 并按 busy 处理一次重探；连守卫都起不来时如实弃跑。
            pids = [{"pid": -1, "cmd": f"guard_error: {exc!r}"}]
        if not pids:
            return {"busy": False, "attempts": attempt, "pids": []}
        print(f"[m4][guard] 第 {attempt}/{OE_GUARD_MAX_TRIES} 次探测到他轨 OE 进程，"
              f"等 {OE_GUARD_WAIT_S:.0f}s：{pids}")
        if attempt < OE_GUARD_MAX_TRIES:
            time.sleep(OE_GUARD_WAIT_S)
    return {"busy": True, "attempts": OE_GUARD_MAX_TRIES, "pids": pids}


def load_offline() -> dict[str, Any]:
    if not OFFLINE_PATH.exists():
        raise SystemExit(f"[m4] 缺离线产物 {OFFLINE_PATH}（先跑 --offline）")
    return json.loads(OFFLINE_PATH.read_text(encoding="utf-8"))


def run_verify() -> int:
    """真机验证腿（≤5 点，双缓存关，OE 守卫；断点 resume 幂等）→ verdict。"""
    if str(Path.cwd().resolve()) != str(REPO.resolve()):
        print(f"[m4] 拒跑：cwd 必须是仓库根 {REPO}（当前 {Path.cwd()}）")
        return 2
    offline = load_offline()
    plan = offline.get("verify_plan") or []
    if not plan:
        print("[m4] 离线产物无 verify_plan——先跑 --offline")
        return 2
    ROOT.mkdir(parents=True, exist_ok=True)
    verify_dir = ROOT / "verify"
    verify_dir.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    if VERIFY_INDEX_PATH.exists():
        index = json.loads(VERIFY_INDEX_PATH.read_text(encoding="utf-8"))

    # 验收双缓存关（criteria 预声明）：环境级 + adapter 级，两套缓存同关
    import os

    os.environ["RFAUTO_CACHE"] = "off"
    from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter

    evals_root = ROOT / "verify_evals"
    adapter = OpenEMSOptAdapter(
        FREQ_RANGE_GHZ, template=TEMPLATE, substrate=SUBSTRATE,
        cache=False, solve_timeout_s=SOLVE_TIMEOUT_S, work_root=evals_root)
    from factory_m1_collect import compute_point_metrics  # M1 同指标内核

    for pt in plan:
        vid = str(pt["vid"])
        row = index.get(vid)
        if isinstance(row, dict) and row.get("status") in ("done", "failed"):
            print(f"[m4] {vid} 已有记录（{row.get('status')}），resume 跳过")
            continue
        guard = oe_guard_check()
        if guard["busy"]:
            index[vid] = {"status": "failed", "w_mm": pt["w_mm"],
                          "msg": f"OE 串行 1 守卫：他轨 OE 进程占岗 {guard['pids']}"}
            _save_json(VERIFY_INDEX_PATH, index)
            print(f"[m4] {vid} 弃跑：{index[vid]['msg']}")
            continue
        w = float(pt["w_mm"])
        adapter.set_variables({"w_mm": w, "line_len_mm": LINE_LEN_MM})
        eval_n = len(list(evals_root.glob("eval_*"))) + 1
        port_beta = evals_root / f"eval_{eval_n:04d}" / "port_beta.csv"
        t0 = time.perf_counter()
        rep = adapter.solve(timeout_s=SOLVE_TIMEOUT_S)
        wall = time.perf_counter() - t0
        if not rep.success:
            index[vid] = {
                "status": "failed", "w_mm": w, "wall_s": round(wall, 3),
                "msg": str(rep.message)[:300], "cache_env": "off(set)",
                "oe_guard": guard,
            }
            _save_json(VERIFY_INDEX_PATH, index)
            print(f"[m4] {vid} w={w:.6f} SOLVE FAIL: {rep.message}")
            continue
        net = adapter.get_sparams()
        metrics, notes = compute_point_metrics(net, port_beta_csv=port_beta)
        index[vid] = {
            "status": "done", "w_mm": w, "wall_s": round(wall, 3),
            "s11_db_max_in_band": float(metrics[S11_KEY]),
            "pred_s11_db": (None if pt.get("pred_s11_db") is None
                            else float(pt["pred_s11_db"])),
            "source": pt.get("source"), "eval_dir": str(adapter.eval_root),
            "port_beta_csv": str(port_beta), "notes": notes,
            "cache_env": "off(set)+adapter cache=False",
            "oe_guard": guard,
            "metrics": metrics,
        }
        _save_json(VERIFY_INDEX_PATH, index)
        print(f"[m4] {vid} w={w:.6f} wall={wall:.1f}s "
              f"s11_max={metrics[S11_KEY]:.3f} dB (pred {pt.get('pred_s11_db')}) "
              f"eval=eval_{eval_n:04d}")
    return build_and_write_verdict(offline, index)


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def build_and_write_verdict(
    offline: dict[str, Any], index: dict[str, Any],
) -> int:
    """G2 双门判读（判据内核 wp39 复用；幂等）→ m4_verdict.json。"""
    from rfauto.service.wp39_benchmark import cost_degradation_pct

    stock = offline.get("stock") or {}
    sb_v = float(stock["best_s11_db"])
    sb_w = float(stock["best_w_mm"])
    timing = offline.get("timing") or {}

    pts: list[dict[str, Any]] = []
    walls: list[float] = []
    best_verif: float | None = None
    best_vid: str | None = None
    gp_vs_real: list[dict[str, Any]] = []
    for vid, row in sorted(index.items()):
        if not isinstance(row, dict):
            continue
        pts.append({"vid": vid, **{k: row.get(k) for k in
                                   ("status", "w_mm", "wall_s", "msg",
                                    "s11_db_max_in_band", "source")}})
        if row.get("status") != "done":
            continue
        walls.append(float(row.get("wall_s") or 0.0))
        v = row.get("s11_db_max_in_band")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = float(v)
            if best_verif is None or v < best_verif:
                best_verif, best_vid = v, vid
            pred = row.get("pred_s11_db")
            pred_f = (float(pred) if isinstance(pred, (int, float))
                      and not isinstance(pred, bool) else None)
            gp_vs_real.append({
                "vid": vid, "w_mm": float(row.get("w_mm") or 0.0),
                "pred_s11_db": pred_f, "real_s11_db": v,
                "delta_db": None if pred_f is None else round(v - pred_f, 4),
            })

    account = m4_account(
        float(offline.get("t_gp_fit_s") or 0.0),
        float(timing.get("t_loop_s") or 0.0),
        float(offline.get("t_select_s") or 0.0),
        walls)
    cost = m4_cost(best_verif, sb_v)

    # 违约量口径（环 objective 语义）并列诊断（criteria：不作本门判读）
    viol_verif = None if best_verif is None else violation_db(best_verif)
    viol_stock = violation_db(sb_v)
    deg_viol = cost_degradation_pct(viol_verif, viol_stock)

    locate_err = None
    if best_vid is not None:
        bw = index.get(best_vid, {}).get("w_mm")
        if isinstance(bw, (int, float)) and not isinstance(bw, bool):
            locate_err = abs(float(bw) - sb_w)

    total_wall = (float(stock.get("t_load_s") or 0.0)
                  + account["t_gp_fit_s"] + account["t_loop_s"]
                  + account["t_select_s"] + account["t_verify_total_s"])
    partial = total_wall > BUDGET_PARTIAL_S
    ratio_ok = bool(account["ratio_ok"])
    deg_ok = bool(cost["deg_ok"])
    overall = "PASS" if (ratio_ok and deg_ok) else "FAIL"
    if partial:
        overall = f"PARTIAL(超预算): {overall}"
    reasons = list(account["reasons"]) + list(cost["reasons"])

    t_factory = account["t_factory_s"]
    denom = BASELINE_S - t_factory
    k_breakeven = (C_COLLECT_MEASURED_S / denom) if denom > 0 else None
    k_nominal_denom = BASELINE_S - t_factory
    k_breakeven_nominal = (C_COLLECT_NOMINAL_S / k_nominal_denom
                           if k_nominal_denom > 0 else None)
    amortized_5x_k = (None if k_breakeven is None
                      else 5.0 * C_COLLECT_MEASURED_S / denom)

    verdict = {
        "schema_version": 1,
        "created_at": _now_iso(),
        "git_sha": offline.get("git_sha"),
        "criteria_md": str(CRITERIA_PATH.relative_to(REPO)),
        "gates": {
            "G2_wallclock": {**account, "pass": ratio_ok},
            "G2_cost": {**cost, "pass": deg_ok},
        },
        "verdict": overall,
        "reasons": reasons,
        "cost_account_violation_diagnostic": {
            "note": "环 objective（max_below −40 违约量）口径并列，不作本门判读"
                    "（criteria 预声明：库存最优以 dB 真值定义）",
            "cost_best_verif_violation": viol_verif,
            "cost_stock_violation": viol_stock,
            "degradation_pct": None if deg_viol is None else round(deg_viol, 4),
        },
        "validity": {
            "cache_env": "off(set)+adapter cache=False",
            "verify_points": pts,
            "n_verify_done": len(walls),
            "n_verify_total": len(pts),
            "best_vid": best_vid,
            "gp_vs_real": gp_vs_real,
            "locate_err_mm": None if locate_err is None else round(locate_err, 6),
            "oe_guard_note": "每点起跑前 Get-CimInstance 查 #261 标记进程（逐点存档）",
        },
        "amortization": {
            "note": "如实报告不设门（plan §1.2/G3）",
            "c_collect_measured_s": C_COLLECT_MEASURED_S,
            "c_collect_nominal_s": C_COLLECT_NOMINAL_S,
            "t_factory_s": t_factory,
            "k_breakeven_measured": (None if k_breakeven is None
                                     else round(k_breakeven, 3)),
            "k_breakeven_nominal": (None if k_breakeven_nominal is None
                                    else round(k_breakeven_nominal, 3)),
            "k_for_5x_amortized": (None if amortized_5x_k is None
                                   else round(amortized_5x_k, 2)),
        },
        "budget": {
            "batch_wall_s": round(total_wall, 2),
            "budget_wall_s": BUDGET_WALL_S,
            "partial_over_1_5x_s": BUDGET_PARTIAL_S,
            "partial": partial,
        },
        "attribution": {
            "t_query_total_s": round(float(timing.get("t_query_total_s") or 0.0), 4),
            "n_loop_queries": timing.get("n_queries"),
            "t_share_opt_s": round(account["t_gp_fit_s"] + account["t_loop_s"]
                                   + account["t_select_s"], 3),
            "t_share_verify_s": account["t_verify_total_s"],
            "gp_depth_note": "GP 定深误差见 validity.gp_vs_real（pred vs real ΔdB）；"
                             "定位误差见 validity.locate_err_mm",
        },
    }
    _save_json(VERDICT_PATH, verdict)
    print(f"[m4] 判读: {verdict['verdict']}")
    print(f"  G2 墙钟: T_factory={t_factory:.2f}s ratio={account['ratio']} "
          f"门 {RATIO_GATE} → {'PASS' if ratio_ok else 'FAIL'}")
    print(f"  G2 cost: verif={cost['cost_best_verif_db']} vs 库存最优 {sb_v:.4f} "
          f"@w={sb_w:.6f} 劣化 {cost['degradation_pct']}% 门 {DEG_GATE_PCT}% → "
          f"{'PASS' if deg_ok else 'FAIL'}")
    print(f"  摊销: K={verdict['amortization']['k_breakeven_measured']} 场"
          f"（实测 C_collect {C_COLLECT_MEASURED_S}s）")
    for r in reasons:
        print(f"  [reason] {r}")
    return 0 if ratio_ok and deg_ok and not partial else 1


def run_judge() -> int:
    """幂等离线判读（输入=offline 产物 + verify_index；不碰真机）。"""
    offline = load_offline()
    if not VERIFY_INDEX_PATH.exists():
        print(f"[m4] 缺 {VERIFY_INDEX_PATH}（先跑 --verify）")
        return 2
    index = json.loads(VERIFY_INDEX_PATH.read_text(encoding="utf-8"))
    return build_and_write_verdict(offline, index)


# ─── M4 run2 谷芯加密验证（criteria_v2_refine.md 预声明编排） ─────────────────

def _lock_owner() -> dict[str, Any] | None:
    """读锁文件所有者（best-effort）；空锁/不可读 → None（按无主只等待不误抢）。"""
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    """进程存活探测（Get-Process）；探测失败按存活（不误抢，criteria 预声明）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"if (Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue) "
             f"{{ Write-Output ALIVE }}"],
            capture_output=True, text=True, timeout=30)
        return "ALIVE" in (out.stdout or "")
    except Exception:
        return True


def lock_acquire(timeout_s: float) -> dict[str, Any]:
    """runs/.oe_collect.lock O_CREAT|O_EXCL 原子占锁；被占 60s 轮询；
    持有进程已死（stale）→ 记录后接管。返回 {acquired, attempts, waited_s, owner}。"""
    t0 = time.monotonic()
    attempts = 0
    while True:
        attempts += 1
        try:
            fd = os.open(str(LOCK_PATH), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"pid": os.getpid(), "task": "m4_v2_refine",
                                     "ts": _now_iso()}, ensure_ascii=False))
            return {"acquired": True, "attempts": attempts,
                    "waited_s": round(time.monotonic() - t0, 1), "owner": None}
        except FileExistsError:
            owner = _lock_owner()
            if isinstance(owner, dict) and isinstance(owner.get("pid"), int) \
                    and not _pid_alive(int(owner["pid"])):
                try:
                    LOCK_PATH.unlink()
                    print(f"[m4v2][lock] stale 锁接管：owner={owner}")
                except OSError:
                    pass  # 他进程同时接管：下一轮重试
                continue
            if time.monotonic() - t0 > timeout_s:
                return {"acquired": False, "attempts": attempts,
                        "waited_s": round(time.monotonic() - t0, 1), "owner": owner}
            time.sleep(LOCK_POLL_S)


def lock_release() -> None:
    """释放锁（幂等：不存在则吞）。"""
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[m4v2][lock] 释放异常（不阻断）：{exc!r}")


def _oe_guard_once() -> dict[str, Any]:
    """#261 单次查（锁内执行；等待语义由锁轮询承担），排除自身 pid。

    守卫 best-effort（#105）但失败不静默放行：按 busy 处理（保守弃跑可 resume）。
    """
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" "
        "-ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match '"
        + OE_GUARD_MARKERS + "' } | Select-Object ProcessId,CommandLine | "
        "ConvertTo-Json -Compress")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=60)
        txt = (out.stdout or "").strip()
        pids: list[dict[str, Any]] = []
        if txt:
            data = json.loads(txt)
            rows = data if isinstance(data, list) else [data]
            for r in rows:
                try:
                    pid = int(r.get("ProcessId"))
                except (TypeError, ValueError):
                    continue
                if pid == os.getpid():
                    continue
                pids.append({"pid": pid, "cmd": str(r.get("CommandLine"))[:200]})
        return {"busy": bool(pids), "pids": pids}
    except Exception as exc:
        return {"busy": True,
                "pids": [{"pid": -1, "cmd": f"guard_error: {exc!r}"}]}


def _load_or_build_refine_offline() -> dict[str, Any] | int:
    """v2 离线腿：库存加载→GP 重训→谷芯点构造→预测剖面；落 refine_offline_v2.json。

    已存在则复用（resume 安全；GP 同数据同配置确定性同构）。"""
    if REFINE_OFFLINE_PATH.exists():
        print(f"[m4v2] 复用离线产物 {REFINE_OFFLINE_PATH.name}（resume）")
        return json.loads(REFINE_OFFLINE_PATH.read_text(encoding="utf-8"))
    samples, load_meta = load_stock()
    if load_meta["n_rows"] != 120:
        print(f"[m4v2] 库存行数异常：{load_meta['n_rows']} != 120（criteria 口径）")
        return 1
    sb_w, sb_v = stock_best(samples)
    model, t_gp = fit_stock_gp(samples)
    pts, dropped = refine_points()
    mx = window_max_step_um(pts, REFINE_ANCHOR_B_MM, REFINE_ANCHOR_A_MM)
    if mx is None or mx > 1.5 + 1e-9:
        print(f"[m4v2] 谷芯点窗内步距核验失败：max={mx}（criteria ≤1.5µm）")
        return 1

    def pred(w: float) -> float:
        return round(float(model.predict({"w_mm": w})[S11_KEY]), 4)

    exec_plan = [{"vid": f"r{i:02d}", "w_mm": w, "pred_s11_db": pred(w),
                  "source": "refine"} for i, w in enumerate(pts, start=1)]
    exec_plan.append({"vid": "ra", "w_mm": REFINE_ANCHOR_REPRO_W_MM,
                      "pred_s11_db": pred(REFINE_ANCHOR_REPRO_W_MM),
                      "source": "anchor_repro"})
    exec_plan.sort(key=lambda p: float(p["w_mm"]))
    n_steps = round((GP_PROFILE_HI_MM - GP_PROFILE_LO_MM) / GP_PROFILE_STEP_MM)
    curve_ws = [GP_PROFILE_LO_MM + i * GP_PROFILE_STEP_MM
                for i in range(n_steps + 1)]
    payload = {
        "schema_version": 1,
        "created_at": _now_iso(),
        "git_sha": git_sha(),
        "criteria_md": str(REFINE_CRITERIA_PATH.relative_to(REPO)),
        "gp": {"kind": "smt_kriging 重训并列（同 120 行库存同配置 registry 缺省 "
                        "theta0 不调参，与 run1 --offline 确定性同构；非消费 run1 "
                        "进程内对象）",
               "t_fit_s": round(t_gp, 3)},
        "stock": {**load_meta, "best_w_mm": sb_w, "best_s11_db": sb_v},
        "anchors": {"A_stock_mm": REFINE_ANCHOR_A_MM, "B_loop_mm": REFINE_ANCHOR_B_MM,
                    "pred_A_db": pred(REFINE_ANCHOR_A_MM),
                    "pred_B_db": pred(REFINE_ANCHOR_B_MM)},
        "refine_points": pts,
        "dropped": dropped,
        "window_check": {"lo_mm": REFINE_ANCHOR_B_MM, "hi_mm": REFINE_ANCHOR_A_MM,
                         "max_step_um_plan": round(mx, 4),
                         "le_1p5um": bool(mx <= 1.5 + 1e-9)},
        "exec_plan": exec_plan,
        "gp_profile_curve": {"lo_mm": GP_PROFILE_LO_MM, "hi_mm": GP_PROFILE_HI_MM,
                             "step_mm": GP_PROFILE_STEP_MM,
                             "w_mm": [round(w, 6) for w in curve_ws],
                             "pred_s11_db": [pred(w) for w in curve_ws]},
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    _save_json(REFINE_OFFLINE_PATH, payload)
    print(f"[m4v2] GP 重训 {t_gp:.3f}s；谷芯 {len(pts)} 点+ra 共 {len(exec_plan)} 点；"
          f"窗内最大步距 {mx:.3f}µm；离线产物 → {REFINE_OFFLINE_PATH.relative_to(REPO)}")
    return payload


def run_verify_refine() -> int:
    """真机谷芯微批（10 点，双缓存关，共享锁+#261 锁内查+QuotaGuard；
    断点 resume 幂等：done/failed 跳过，skipped 重试）→ verdict_v2_refine.json。"""
    if str(Path.cwd().resolve()) != str(REPO.resolve()):
        print(f"[m4v2] 拒跑：cwd 必须是仓库根 {REPO}（当前 {Path.cwd()}）")
        return 2
    built = _load_or_build_refine_offline()
    if isinstance(built, int):
        return built
    offline = built
    plan = offline.get("exec_plan") or []
    ROOT.mkdir(parents=True, exist_ok=True)
    REFINE_EVALS_ROOT.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {}
    if REFINE_INDEX_PATH.exists():
        index = json.loads(REFINE_INDEX_PATH.read_text(encoding="utf-8"))

    # 验证双缓存关（criteria_v2 预声明）：环境级 + adapter 级，两套缓存同关
    os.environ["RFAUTO_CACHE"] = "off"
    from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter
    from rfauto.pipeline.quota_guard import (
        QuotaExceededError,
        QuotaGuard,
        QuotaLimits,
    )

    adapter = OpenEMSOptAdapter(
        FREQ_RANGE_GHZ, template=TEMPLATE, substrate=SUBSTRATE,
        cache=False, solve_timeout_s=SOLVE_TIMEOUT_S, work_root=REFINE_EVALS_ROOT)
    from factory_m1_collect import compute_point_metrics  # M1 同指标内核

    guard = QuotaGuard(QuotaLimits(max_trials=QUOTA_TRIALS_V2,
                                   max_wall_hours=QUOTA_WALL_H_V2))
    t_batch_wall = time.time()   # QuotaGuard check_wall_time 用 time.time 口径
    t_batch = time.monotonic()   # 预算帽用单调钟
    n_solved = 0
    try:
        for pt in plan:
            vid = str(pt["vid"])
            row = index.get(vid)
            if isinstance(row, dict) and row.get("status") in ("done", "failed"):
                print(f"[m4v2] {vid} 已有记录（{row.get('status')}），resume 跳过")
                continue
            elapsed = time.monotonic() - t_batch
            if elapsed > BUDGET_WALL_S_V2:
                index[vid] = {"status": "skipped", "reason": "budget",
                              "w_mm": pt["w_mm"], "elapsed_s": round(elapsed, 1)}
                _save_json(REFINE_INDEX_PATH, index)
                print(f"[m4v2] {vid} skipped(budget) elapsed={elapsed:.0f}s")
                continue
            try:
                guard.check_trial(n_solved)
                guard.check_wall_time(t_batch_wall)
            except QuotaExceededError as exc:
                index[vid] = {"status": "skipped", "reason": f"quota: {exc}",
                              "w_mm": pt["w_mm"]}
                _save_json(REFINE_INDEX_PATH, index)
                print(f"[m4v2] {vid} skipped(quota): {exc}")
                continue
            lk = lock_acquire(LOCK_PER_POINT_WAIT_S)
            if not lk["acquired"]:
                index[vid] = {"status": "skipped", "reason": "lock_timeout",
                              "w_mm": pt["w_mm"], "lock": lk}
                _save_json(REFINE_INDEX_PATH, index)
                print(f"[m4v2] {vid} skipped(lock_timeout)：owner={lk.get('owner')}")
                continue
            try:
                g = _oe_guard_once()
                if g["busy"]:
                    index[vid] = {"status": "skipped", "reason": "oe_guard_busy",
                                  "w_mm": pt["w_mm"], "oe_guard": g}
                    _save_json(REFINE_INDEX_PATH, index)
                    print(f"[m4v2] {vid} skipped(oe_guard_busy)：{g['pids']}")
                    continue
                w = float(pt["w_mm"])
                adapter.set_variables({"w_mm": w, "line_len_mm": LINE_LEN_MM})
                eval_n = len(list(REFINE_EVALS_ROOT.glob("eval_*"))) + 1
                port_beta = (REFINE_EVALS_ROOT / f"eval_{eval_n:04d}"
                             / "port_beta.csv")
                t0 = time.perf_counter()
                rep = adapter.solve(timeout_s=SOLVE_TIMEOUT_S)
                wall = time.perf_counter() - t0
                if not rep.success:
                    index[vid] = {
                        "status": "failed", "w_mm": w, "wall_s": round(wall, 3),
                        "msg": str(rep.message)[:300], "source": pt.get("source"),
                        "cache_env": "off(set)+adapter cache=False",
                        "oe_guard": g,
                        "lock": {"attempts": lk["attempts"],
                                 "waited_s": lk["waited_s"]},
                    }
                    print(f"[m4v2] {vid} w={w:.6f} SOLVE FAIL: {rep.message}")
                else:
                    net = adapter.get_sparams()
                    metrics, notes = compute_point_metrics(net,
                                                           port_beta_csv=port_beta)
                    index[vid] = {
                        "status": "done", "w_mm": w, "wall_s": round(wall, 3),
                        "s11_db_max_in_band": float(metrics[S11_KEY]),
                        "pred_s11_db": pt.get("pred_s11_db"),
                        "source": pt.get("source"),
                        "eval_dir": str(REFINE_EVALS_ROOT / f"eval_{eval_n:04d}"),
                        "port_beta_csv": str(port_beta), "notes": notes,
                        "cache_env": "off(set)+adapter cache=False",
                        "oe_guard": g,
                        "lock": {"attempts": lk["attempts"],
                                 "waited_s": lk["waited_s"]},
                        "metrics": metrics,
                    }
                    n_solved += 1
                    print(f"[m4v2] {vid} w={w:.6f} wall={wall:.1f}s "
                          f"s11_max={metrics[S11_KEY]:.4f} dB "
                          f"(pred {pt.get('pred_s11_db')}) eval=eval_{eval_n:04d}")
            finally:
                lock_release()
            index["_batch"] = {"wall_s_sofar": round(time.monotonic() - t_batch, 2),
                               "updated_at": _now_iso()}
            _save_json(REFINE_INDEX_PATH, index)
    finally:
        lock_release()  # 兜底：任何异常路径不留死锁（幂等）
    index["_batch"] = {"batch_wall_s": round(time.monotonic() - t_batch, 2),
                       "completed_at": _now_iso()}
    _save_json(REFINE_INDEX_PATH, index)
    return build_verdict_v2(offline, index)


def build_verdict_v2(offline: dict[str, Any], index: dict[str, Any]) -> int:
    """cost 门 v2 判读（劣化内核 wp39 cost_degradation_pct 复用；幂等）
    → verdict_v2_refine.json。"""
    stock = offline.get("stock") or {}
    sb_v = float(stock["best_s11_db"])
    sb_w = float(stock["best_w_mm"])
    threshold = refine_threshold_db(sb_v)
    best = refine_best_of(index)
    gate = m4_cost(None if best is None else best[1], sb_v, DEG_GATE_PCT)
    # 门主判=预声明直比（refine_best ≤ 库存×0.95，单次舍入）；
    # 劣化百分比仍由 wp39 内核产出并列报告（阈值恰点浮点差 ~1e-14 见
    # refine_gate_pass docstring；criteria_v2 预声明）。
    gate_pass = refine_gate_pass(None if best is None else best[1], threshold)
    gate = {**gate, "deg_ok": gate_pass}
    if best is not None and not gate_pass:
        gate["reasons"] = [
            f"cost 劣化超门：refine_best {best[1]:.4f} dB > 门阈 "
            f"{threshold:.4f} dB（库存最优×{REFINE_GATE_FACTOR}）"]

    pts: list[dict[str, Any]] = []
    gp_vs_real: list[dict[str, Any]] = []
    for vid, row in sorted(index.items()):
        if vid.startswith("_") or not isinstance(row, dict):
            continue
        pts.append({"vid": vid, **{k: row.get(k) for k in
                                   ("status", "w_mm", "wall_s", "reason", "msg",
                                    "s11_db_max_in_band", "pred_s11_db",
                                    "source")}})
        if row.get("status") != "done":
            continue
        v = row.get("s11_db_max_in_band")
        v_f = (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
               else None)
        p = row.get("pred_s11_db")
        p_f = (float(p) if isinstance(p, (int, float)) and not isinstance(p, bool)
               else None)
        gp_vs_real.append({
            "vid": vid, "w_mm": float(row.get("w_mm") or 0.0),
            "pred_s11_db": p_f, "real_s11_db": v_f,
            "delta_db": None if v_f is None or p_f is None
            else round(v_f - p_f, 4),
        })
    n_done = sum(1 for p in pts if p.get("status") == "done")

    ra_row = index.get("ra")
    ra_diag: dict[str, Any] | None = None
    if isinstance(ra_row, dict) and ra_row.get("status") == "done":
        rv = ra_row.get("s11_db_max_in_band")
        if isinstance(rv, (int, float)) and not isinstance(rv, bool):
            ra_diag = {"w_mm": float(ra_row.get("w_mm") or 0.0),
                       "stock_db": sb_v, "remeasured_db": float(rv),
                       "delta_db": round(float(rv) - sb_v, 4),
                       "note": "复现性诊断（不进门不替代分母，criteria_v2 预声明）"}

    # run1 上下文（只读 best-effort）
    v1_cost_ref: dict[str, Any] = {"verdict_path": str(VERDICT_PATH.relative_to(REPO))}
    v1_loop_best_db: float | None = None
    try:
        v1v = json.loads(VERDICT_PATH.read_text(encoding="utf-8"))
        c1 = (v1v.get("gates") or {}).get("G2_cost") or {}
        v1_cost_ref.update({"v1_verdict": v1v.get("verdict"),
                            "v1_cost_best_verif_db": c1.get("cost_best_verif_db"),
                            "v1_degradation_pct": c1.get("degradation_pct"),
                            "v1_pass": c1.get("pass")})
        v1_loop_best_db = c1.get("cost_best_verif_db")
    except Exception:
        v1_cost_ref["note"] = "run1 verdict 读取失败（best-effort #105）"
    try:
        v1_idx = json.loads(VERIFY_INDEX_PATH.read_text(encoding="utf-8"))
        row1 = v1_idx.get("v1")
        if isinstance(row1, dict) and isinstance(row1.get("s11_db_max_in_band"),
                                                 (int, float)):
            v1_loop_best_db = float(row1["s11_db_max_in_band"])
    except Exception:
        pass

    measured = sorted(
        ({"vid": vid, "w_mm": float(row["w_mm"]),
          "s11_db_max_in_band": float(row["s11_db_max_in_band"]),
          "source": row.get("source")}
         for vid, row in index.items()
         if isinstance(row, dict) and row.get("status") == "done"
         and isinstance(row.get("w_mm"), (int, float))
         and not isinstance(row.get("w_mm"), bool)
         and isinstance(row.get("s11_db_max_in_band"), (int, float))
         and not isinstance(row.get("s11_db_max_in_band"), bool)),
        key=lambda r: r["w_mm"])
    profile = {
        "note": "谷形剖面 w→s11_db_max_in_band（本批实测；上下文锚行=库存/run1 "
                "已测值不重跑）；GP 预测剖面曲线见 refine_offline_v2.json "
                "gp_profile_curve",
        "measured_v2": measured,
        "context": [
            {"w_mm": sb_w, "s11_db_max_in_band": sb_v,
             "source": "stock(M1, 门分母)"},
            {"w_mm": REFINE_ANCHOR_B_MM, "s11_db_max_in_band": v1_loop_best_db,
             "source": "run1_v1(环最优实测)"},
        ],
        "max_step_um_in_window_measured": window_max_step_um(
            [r["w_mm"] for r in measured], REFINE_ANCHOR_B_MM,
            REFINE_ANCHOR_A_MM),
        "window_mm": [REFINE_ANCHOR_B_MM, REFINE_ANCHOR_A_MM],
    }

    plan_vids = [str(p.get("vid")) for p in (offline.get("exec_plan") or [])]
    missing = [vid for vid in plan_vids
               if not (isinstance(index.get(vid), dict)
                       and index[vid].get("status") == "done")]
    refine_missing = [vid for vid in missing if vid != "ra"]

    batch_meta = index.get("_batch")
    batch_wall = 0.0
    if isinstance(batch_meta, dict):
        for k in ("batch_wall_s", "wall_s_sofar"):
            val = batch_meta.get(k)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                batch_wall = float(val)
                break
    partial_budget = batch_wall > BUDGET_PARTIAL_S_V2
    gate_pass = bool(gate["deg_ok"])
    if gate_pass:
        overall = "PASS"
    elif refine_missing:
        overall = (f"FAIL(未完:{len(refine_missing)} refine 点未跑，"
                   f"resume 补跑后 --judge-refine 重判)")
    else:
        overall = "FAIL"
    if partial_budget:
        overall = f"PARTIAL(超预算): {overall}"

    reasons = list(gate["reasons"])
    if refine_missing:
        reasons.append(f"refine 点未完成 {len(refine_missing)} 个：{refine_missing}")
    improve_vs_v1 = (None if best is None or v1_loop_best_db is None
                     else round(best[1] - float(v1_loop_best_db), 4))

    verdict = {
        "schema_version": 1,
        "task": "M4 run2 谷芯加密验证（refine-around-best）·cost 门实质闭合出路验证",
        "created_at": _now_iso(),
        "git_sha": git_sha(),
        "criteria_md": str(REFINE_CRITERIA_PATH.relative_to(REPO)),
        "run1_ref": {**v1_cost_ref,
                     "note": "run1 产物零改写；v1 FAIL 判读不撤销（历史预声明门）"},
        "gate": {
            "name": "G2_cost_v2_refine",
            "refine_best_db": gate["cost_best_verif_db"],
            "refine_best_w_mm": None if best is None else best[0],
            "refine_best_vid": None if best is None else best[2],
            "stock_best_db": gate["cost_stock_best_db"],
            "stock_best_w_mm_full_precision": sb_w,
            "threshold_db": threshold,
            "degradation_pct": gate["degradation_pct"],
            "deg_gate_pct": gate["deg_gate_pct"],
            "pass": gate["deg_ok"],
            "reasons": gate["reasons"],
        },
        "verdict": overall,
        "reasons": reasons,
        "total_account_note": "v1 cost 门 FAIL 系验证策略粒度（min_dist=0.02 伴测点"
                              "落谷肩，非代理失效）；v2 谷芯加密后 cost 实质状态见 "
                              "gate 节；子集 PASS 为保守有效 PASS（criteria_v2）",
        "validity": {
            "cache_env": "off(set)+adapter cache=False（逐点存档 "
                         "refine_index_v2.json）",
            "lock": "runs/.oe_collect.lock O_CREAT|O_EXCL 原子占锁 60s 轮询"
                    "（与 M3 采集互斥）；#261 命令行查在锁内（单次查，排除自身）",
            "points": pts,
            "n_done": n_done,
            "n_plan_total": len(plan_vids),
            "missing": missing,
            "gp_vs_real": gp_vs_real,
            "gp_note": (offline.get("gp") or {}).get("kind"),
            "anchor_repro_diag": ra_diag,
            "improve_vs_run1_loop_best_db": improve_vs_v1,
        },
        "profile": profile,
        "budget": {
            "batch_wall_s": round(batch_wall, 2),
            "budget_wall_s": BUDGET_WALL_S_V2,
            "partial_over_1_5x_s": BUDGET_PARTIAL_S_V2,
            "partial": partial_budget,
        },
        "quota": {"max_trials": QUOTA_TRIALS_V2, "max_wall_hours": QUOTA_WALL_H_V2,
                  "used_trials_done": n_done},
    }
    _save_json(VERDICT_V2_PATH, verdict)
    print(f"[m4v2] 判读: {overall}")
    print(f"  cost v2: refine_best={gate['cost_best_verif_db']} dB"
          f"@w={None if best is None else best[0]} vs 库存最优 {sb_v:.4f}"
          f"（门阈 {threshold:.4f}）劣化 {gate['degradation_pct']}% → "
          f"{'PASS' if gate_pass else 'FAIL'}")
    if ra_diag is not None:
        print(f"  ra 复现性: {ra_diag['remeasured_db']:.4f} vs 库存 "
              f"{ra_diag['stock_db']:.4f}（Δ{ra_diag['delta_db']:+.4f} dB）")
    for r in reasons:
        print(f"  [reason] {r}")
    return 0 if gate_pass and not partial_budget else 1


def run_judge_refine() -> int:
    """run2 幂等离线重判（输入=refine_offline_v2 + refine_index_v2；不碰真机）。"""
    if not REFINE_OFFLINE_PATH.exists():
        print(f"[m4v2] 缺 {REFINE_OFFLINE_PATH}（先跑 --verify-refine）")
        return 2
    if not REFINE_INDEX_PATH.exists():
        print(f"[m4v2] 缺 {REFINE_INDEX_PATH}（先跑 --verify-refine）")
        return 2
    offline = json.loads(REFINE_OFFLINE_PATH.read_text(encoding="utf-8"))
    index = json.loads(REFINE_INDEX_PATH.read_text(encoding="utf-8"))
    return build_verdict_v2(offline, index)


# ─── 定向自检（纯函数面 + 合成 GP 冒烟，零真机零网络） ────────────────────────

def _selftest() -> int:
    import rfauto.optimization.surrogate.smt_kriging  # noqa: F401 注册副作用
    from rfauto.service.wp39_benchmark import cost_degradation_pct, wallclock_ratio

    cases: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        cases.append((name, bool(cond), detail))

    # 1) violation_db（环 objective 语义；#367：0.0 合法非缺失）
    check("violation_db(-41)==0", violation_db(-41.0) == 0.0)
    check("violation_db(-40)==0(边界)", violation_db(-40.0) == 0.0)
    check("violation_db(-35)==5", abs(violation_db(-35.0) - 5.0) < 1e-12)

    # 2) m4_cost（wp39 内核复用 + #367 语义钉）
    c = m4_cost(-51.0, -52.8267, 5.0)
    check("m4_cost(-51 vs -52.83) PASS",
          c["deg_ok"] and abs((c["degradation_pct"] or 0) - 3.4577) < 0.01,
          f"deg={c['degradation_pct']}")
    c = m4_cost(-40.0, -52.8267, 5.0)
    check("m4_cost(-40 vs -52.83) FAIL", (not c["deg_ok"])
          and (c["degradation_pct"] or 0) > 20.0, f"deg={c['degradation_pct']}")
    c = m4_cost(None, -52.8267, 5.0)
    check("m4_cost(None) fail-closed", not c["deg_ok"]
          and c["cost_best_verif_db"] is None)
    check("内核钉 cost_degradation_pct(0,0)==0.0（违约量口径两零=劣化 0 非缺失）",
          cost_degradation_pct(0.0, 0.0) == 0.0)
    check("内核钉 cost_degradation_pct(-51,-52.8267) 笔算一致",
          abs(cost_degradation_pct(-51.0, -52.8267)
              - (-51.0 + 52.8267) / 52.8267 * 100.0) < 1e-9)

    # 3) m4_account（合成账：197.9s → ratio 0.1357 PASS；300s → FAIL；基线 0 → 不可判）
    a = m4_account(1.5, 20.0, 0.2, [35.1, 34.9, 35.0, 35.2, 36.0],
                   baseline_s=1457.74, ratio_gate=0.2)
    check("m4_account 197.9s PASS", a["ratio_ok"]
          and abs((a["ratio"] or 0) - 197.9 / 1457.74) < 1e-3,
          f"ratio={a['ratio']}")
    a = m4_account(1.5, 20.0, 0.2, [90.0] * 3 + [35.1, 34.9],
                   baseline_s=1457.74, ratio_gate=0.2)
    check("m4_account 311.7s FAIL", (not a["ratio_ok"])
          and (a["ratio"] or 1) > 0.2, f"ratio={a['ratio']}")
    a = m4_account(1.0, 1.0, 0.0, [1.0], baseline_s=0.0, ratio_gate=0.2)
    check("m4_account 基线 0 → fail-closed", (not a["ratio_ok"])
          and a["ratio"] is None)
    check("内核钉 wallclock_ratio(10,100)==0.1", wallclock_ratio(10.0, 100.0) == 0.1)

    # 4) select_verify_points（尖谷合成面：v1 环最优 + 最深优先 + min_dist 过滤）
    def synth_pred(w: float) -> float:
        return -20.0 - 33.0 * math.exp(-((w - 0.91) / 0.02) ** 2)

    pts = select_verify_points(0.905, synth_pred, k=4, min_dist=0.02)
    span = 1.5
    check("select v1=环最优原值", abs(pts[0] - 0.905) < 1e-12, f"{pts}")
    check("select 点数=k", len(pts) == 4, f"{pts}")
    check("select min_dist 保持",
          all(abs(a - b) / span >= 0.02 - 1e-12
              for i, a in enumerate(pts) for b in pts[i + 1:]))

    # v2..vK 期望值独立复算：网格预测升序中首个与已选集距离达标者（逐位同法）
    def expected_after(seed_pts: list[float], count: int) -> list[float]:
        grid = [0.5 + i * 0.001 for i in range(1501)]
        ranked = sorted(grid, key=synth_pred)
        out = list(seed_pts)
        for w in ranked:
            if len(out) >= count:
                break
            if all(abs(w - s) / span >= 0.02 for s in out):
                out.append(w)
        return out

    exp_pts = expected_after([0.905], 4)
    check("select 与独立复算逐位一致",
          all(abs(a - b) < 1e-9 for a, b in zip(pts, exp_pts, strict=True)),
          f"got={pts} exp={exp_pts}")

    # 5) stock_best（合成库存）
    sb = stock_best([
        {"params": {"w_mm": 0.5}, "metrics": {S11_KEY: -17.8}},
        {"params": {"w_mm": 0.91}, "metrics": {S11_KEY: -52.83}},
        {"params": {"w_mm": 1.2}, "metrics": {S11_KEY: -25.0}},
    ])
    check("stock_best 合成", abs(sb[0] - 0.91) < 1e-12 and abs(sb[1] + 52.83) < 1e-12)
    try:
        stock_best([])
        check("stock_best 空库存报错", False)
    except ValueError:
        check("stock_best 空库存报错", True)

    # 6) GP 合成冒烟（SMT 真拟合，~1.5s，零真机）
    try:
        xs = [0.5 + i * 1.5 / 59 for i in range(60)]
        gp_samples = [{"params": {"w_mm": x},
                       "metrics": {S11_KEY: synth_pred(x)}} for x in xs]
        model, wall = fit_stock_gp(gp_samples)
        pv = float(model.predict({"w_mm": 0.91})[S11_KEY])
        check("GP 合成冒烟 fit+predict 有限值",
              model.fitted and math.isfinite(pv) and pv < -20.0,
              f"fit {wall:.2f}s pred(0.91)={pv:.2f}")
    except Exception as exc:
        check("GP 合成冒烟 fit+predict 有限值", False, repr(exc))

    # 7) refine_points（谷芯点构造：criteria_v2 写死 9 点集，独立期望=字面表）
    pts, dropped = refine_points()
    expected = [0.903512, 0.904512, 0.906512, 0.907512, 0.908846,
                0.909846, 0.910846, 0.911846, 0.913346]
    check("refine_points 写死 9 点集（criteria 表逐位）", pts == expected, f"{pts}")
    check("refine_points 剔除 5 点且全为 dup",
          len(dropped) == 5
          and all(str(d["reason"]).startswith("dup") for d in dropped),
          f"{dropped}")
    check("refine 去重边界：恰 1.0µm 距两点都保留",
          0.903512 in pts and 0.904512 in pts
          and 0.909846 in pts and 0.910846 in pts)
    pts5, _d5 = refine_points(cap=5)
    check("refine cap 截断升序前 5", pts5 == expected[:5], f"{pts5}")
    mx = window_max_step_um(pts, REFINE_ANCHOR_B_MM, REFINE_ANCHOR_A_MM)
    check("窗内最大步距 ≤1.5µm（criteria 核验）",
          mx is not None and mx <= 1.5 + 1e-9, f"max={mx}")
    check("window_max_step_um 空窗 fail-closed",
          window_max_step_um([], REFINE_ANCHOR_B_MM, REFINE_ANCHOR_A_MM) is None)

    # 8) refine_best_of（ra/skipped/failed/_batch 排除 + fail-closed）
    idx = {
        "r01": {"status": "done", "w_mm": 0.903512, "s11_db_max_in_band": -45.0,
                "source": "refine"},
        "ra": {"status": "done", "w_mm": 0.910346, "s11_db_max_in_band": -60.0,
               "source": "anchor_repro"},
        "r02": {"status": "skipped", "reason": "lock_timeout", "w_mm": 0.904512,
                "source": "refine"},
        "r03": {"status": "failed", "w_mm": 0.906512, "source": "refine"},
        "_batch": {"batch_wall_s": 1.0},
    }
    b = refine_best_of(idx)
    check("refine_best_of 排除 ra/skipped/failed/_batch",
          b is not None and abs(b[0] - 0.903512) < 1e-12
          and abs(b[1] + 45.0) < 1e-12 and b[2] == "r01", f"{b}")
    check("refine_best_of 空成功集 fail-closed",
          refine_best_of({"_batch": {}}) is None)

    # 9) cost 门 v2 边界（主判=直比 refine_best ≤ 库存×0.95，单次舍入；
    #    wp39 劣化内核产出并列报告——阈值恰点内核两次舍入差 ~1e-14）
    sb_ref = -52.826710699164074
    thr = refine_threshold_db(sb_ref)
    check("门阈 = 库存×0.95 全精度", thr == -50.18537516420587
          or abs(thr + 50.185375164205870) < 1e-12, f"{thr!r}")
    check("门边界恰等 → PASS(直比 ≤)", refine_gate_pass(thr, thr))
    c = m4_cost(thr, sb_ref, 5.0)
    check("阈值恰点内核劣化 ≈5.0（并列报告口径）",
          c["degradation_pct"] is not None
          and abs((c["degradation_pct"] or 0) - 5.0) < 1e-9,
          f"deg={c['degradation_pct']}")
    check("门上方 0.001dB → FAIL", not refine_gate_pass(thr + 0.001, thr))
    check("门下方 0.001dB → PASS", refine_gate_pass(thr - 0.001, thr))
    check("refine_best None → fail-closed", not refine_gate_pass(None, thr))

    n_fail = sum(1 for _n, ok, _d in cases if not ok)
    for name, ok, detail in cases:
        print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"[selftest] {len(cases) - n_fail}/{len(cases)} 过")
    return 0 if n_fail == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="M4 代理寻优 vs HFSS 基线墙钟账（criteria 预声明判据）")
    ap.add_argument("--selftest", action="store_true",
                    help="纯函数面+合成 GP 冒烟（零真机）")
    ap.add_argument("--offline", action="store_true",
                    help="库存加载+GP 训练+代理寻优+验证点计划（零真机）")
    ap.add_argument("--verify", action="store_true",
                    help="真机验证腿（≤5 点双缓存关，断点 resume）")
    ap.add_argument("--judge", action="store_true", help="G2 双门判读（幂等）")
    ap.add_argument("--verify-refine", action="store_true",
                    help="M4 run2 谷芯加密验证（criteria_v2，真机 10 点微批）")
    ap.add_argument("--judge-refine", action="store_true",
                    help="run2 幂等离线重判")
    args = ap.parse_args(argv)
    chosen = sum(1 for f in (args.selftest, args.offline, args.verify, args.judge,
                             args.verify_refine, args.judge_refine)
                 if f)
    if chosen != 1:
        ap.print_help()
        return 2
    if args.selftest:
        return _selftest()
    if args.offline:
        return run_offline()
    if args.verify:
        return run_verify()
    if args.judge:
        return run_judge()
    if args.verify_refine:
        return run_verify_refine()
    return run_judge_refine()


if __name__ == "__main__":
    sys.exit(main())
