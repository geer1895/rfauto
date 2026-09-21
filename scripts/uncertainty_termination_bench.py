"""B5 不确定度终止判据 tol 标定协议（合成碗裁判，#207 禁 fake 原生模型）。

裁判面：synthetic_noisy_bowl（active_learning.py 同一合成裁判，只 import
复用定义域/闭式/密网格极值，零真机、零 fake 原生模型）。配对协议：

  1. 全预算臂：15 固定种子（0..14）各跑一次 run_surrogate_loop，
     uncertainty_tol=0.0（观测模式：σ_cost_max 逐轮恒记录，而 GP 后验
     σ>0 严格成立 → 终止判据永不触发，采样与缺省臂逐字节同）；
  2. target = f_min + fraction·(f_max−f_min)（active_learning :657 口径，
     阈值高于极值下限——#207 防种子彩票）；cost 通道用 MAX_BELOW
     地板目标（value=f_min−1）映射，cost=target_bowl−f_min+1，全域无零平台；
  3. 每种子记 target 首达轮 t_hit 与该轮 sigma_cost_max → 输出
     "target 首达轮 sigma_max 分布" 各分位数，**q90 为 tol 标定值**；
  4. uncertainty_rounds 由离线扫描确定（σ 轨迹从全预算臂逐轮复用：
     判据不影响采样 → 早停臂真跑轨迹必为全预算臂前缀，模拟精确）：
     取 q90 下预测命中 15/15 的最小 R；
  5. 早停臂真跑：15 种子 × (tol=q90, R, pool=128)，配对同种子。

预声明门（脚本写定后才跑，不事后改门——#122）：
  - 硬门：早停臂 target 命中率 100%（未达如实 FAIL 落 verdict）；
  - 软门：evals 节省中位 ≥20%（未达如实登记）。

用法：
  .venv\\Scripts\\python.exe scripts/uncertainty_termination_bench.py
结果落 runs/uncertainty_bench/bench.json。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
_src = REPO / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from rfauto.core.objectives import MetricOp, Objective  # noqa: E402
from rfauto.optimization.surrogate_loop import run_surrogate_loop  # noqa: E402
from rfauto.service.active_learning import (  # noqa: E402
    BOWL_BOUNDS,
    synthetic_bowl_range,
    synthetic_noisy_bowl,
)

# ── 协议常量（预声明，跑前写定） ──────────────────────────────────────────────
N_SEEDS = 15
SEED0 = 0
N_INIT = 8
TOP_K = 3
MAX_REAL = 30
VIRTUAL_TRIALS = 800
UNCERTAINTY_POOL = 128
TARGET_FRACTION = 0.02
#: 观测模式 tol：GP 后验 σ 严格 >0（nugget>0 且池点与样本点不精确重合），
#: 判据 sigma<=0 永不触发——σ 只被记录，不影响采样/停止。
OBSERVE_TOL = 0.0
#: 候选 R 网格（离线扫描；q90 下预测命中 100% 的最小者为早停臂配置）
R_GRID = (1, 2, 3, 4)
TOL_QUANTILES = ("min", "q10", "q25", "q50", "q90", "max")
OUT_PATH = REPO / "runs" / "uncertainty_bench" / "bench.json"

#: MAX_BELOW 地板目标（value=f_min−1）下 cost = bowl − (f_min−1)：
#: 全域严格正、无零平台（#207），target 换算只差常数平移
_FLOOR = float(synthetic_bowl_range()[0]) - 1.0


def _objectives(floor: float) -> list[Objective]:
    return [Objective(metric="bowl_cost", band=[], op=MetricOp.MAX_BELOW,
                      value=floor, weight=1.0)]


def _run_arm(seed: int, tol: float | None, rounds: int) -> dict[str, Any]:
    return run_surrogate_loop(
        BOWL_BOUNDS, _objectives(_FLOOR),
        lambda params: {"bowl_cost": synthetic_noisy_bowl(params)},
        n_init=N_INIT, top_k=TOP_K, max_real=MAX_REAL,
        virtual_trials=VIRTUAL_TRIALS, seed=seed,
        uncertainty_tol=tol, uncertainty_rounds=rounds,
        uncertainty_pool=UNCERTAINTY_POOL)


def _sigma_trace(res: dict[str, Any]) -> list[float | None]:
    return [r.get("sigma_cost_max") for r in res["rounds"]
            if "sigma_cost_max" in r]


def _hit_round(res: dict[str, Any], target_cost: float) -> int | None:
    for r in res["rounds"]:
        if "sigma_cost_max" not in r:
            continue  # round-0 lhs_init 相位记录
        b = r.get("best_cost_after")
        if b is not None and b <= target_cost:
            return int(r["round"])
    return None


def _simulate_streak(
    sigmas: list[float | None], tol: float, rounds_n: int,
) -> int | None:
    """按环内同式连击逻辑离线预测停止轮（返回停止前保留的轮数）。

    与 surrogate_loop 一致：sigma≤tol 计连击（None 复位），连击达
    rounds_n 即在当轮批前停——保留轮数 = 触发轮序号 −1（无触发返 None）。
    """
    streak = 0
    for i, sig in enumerate(sigmas, start=1):
        if sig is not None and sig <= tol:
            streak += 1
            if streak >= max(1, rounds_n):
                return i - 1  # 保留 1..i-1 轮
        else:
            streak = 0
    return None


def main() -> int:
    t0 = time.time()
    f_min, f_max = synthetic_bowl_range()
    target_bowl = f_min + TARGET_FRACTION * (f_max - f_min)
    # MAX_BELOW 地板目标下 cost = bowl − (f_min−1)（全域严格正，无零平台 #207）
    target_cost = target_bowl - _FLOOR

    # ── ① 全预算臂（观测模式：tol=0.0 只记录 σ 不触发判据） ─────────────────
    print(f"[1/4] 全预算臂：{N_SEEDS} 种子（tol={OBSERVE_TOL} 观测模式）…")
    full: list[dict[str, Any]] = []
    for s in range(SEED0, SEED0 + N_SEEDS):
        res = _run_arm(s, OBSERVE_TOL, 1)
        if res["stop_reason"] == "uncertainty_saturated":
            print(f"  seed {s}: 观测模式意外触发判据（σ 出现 0）——协议失效")
            return 1
        full.append(res)
    # 采样等价性抽查：tol=None（缺省路径）与观测模式轨迹逐位一致（seed0）
    ref = run_surrogate_loop(
        BOWL_BOUNDS, _objectives(_FLOOR),
        lambda params: {"bowl_cost": synthetic_noisy_bowl(params)},
        n_init=N_INIT, top_k=TOP_K, max_real=MAX_REAL,
        virtual_trials=VIRTUAL_TRIALS, seed=SEED0)
    if ref["real_cost_trace"] != full[0]["real_cost_trace"]:
        print("  观测臂与缺省臂轨迹不一致——σ 通道污染了采样，协议失效")
        return 1

    # ── ② target 首达轮 σ 分布 → q90 标定值 ─────────────────────────────────
    print("[2/4] target 首达轮 sigma_max 分布…")
    sigma_hits: list[float] = []
    hit_rounds: list[int | None] = []
    for res in full:
        t_hit = _hit_round(res, target_cost)
        hit_rounds.append(t_hit)
        if t_hit is not None:
            sig = _sigma_trace(res)[t_hit - 1]
            if sig is None:
                print(f"  seed {res.get('seed')}: 首达轮 σ 缺失（None）")
                return 1
            sigma_hits.append(float(sig))
    n_full_hit = sum(1 for t in hit_rounds if t is not None)
    qs = {name: float(np.quantile(sigma_hits, q)) for name, q in
          (("min", 0.0), ("q10", 0.10), ("q25", 0.25), ("q50", 0.50),
           ("q90", 0.90))} if sigma_hits else {}
    if sigma_hits:
        qs["max"] = float(np.max(sigma_hits))
    tol_calib = qs.get("q90")
    print(f"  全预算臂命中 {n_full_hit}/{N_SEEDS}；σ_hit 分布："
          + ", ".join(f"{k}={v:.4f}" for k, v in qs.items()))

    # ── ③ 离线扫描 (tol 分位 × R) → 早停臂配置 ──────────────────────────────
    print("[3/4] 离线扫描 (tol×R)，q90 下取预测命中 100% 的最小 R…")
    sweep: list[dict[str, Any]] = []
    for qname in TOL_QUANTILES:
        tol_q = qs.get(qname)
        if tol_q is None:
            continue
        for r_n in R_GRID:
            saved: list[int] = []
            hit_n = 0
            for res, t_hit in zip(full, hit_rounds, strict=True):
                keep = _simulate_streak(_sigma_trace(res), tol_q, r_n)
                n_full_used = int(res["n_real_used"])
                if keep is None:
                    n_early = n_full_used
                else:
                    n_early = N_INIT + int(sum(
                        rr["n_evaluated"] for rr in res["rounds"][1:keep + 1]))
                if t_hit is not None and keep is not None \
                        and keep >= t_hit:
                    hit_n += 1
                elif t_hit is not None and keep is None:
                    hit_n += 1  # 不停=全预算，命中随全预算臂
                saved.append(n_full_used - n_early)
            sweep.append({
                "tol_quantile": qname, "tol": tol_q, "rounds": r_n,
                "predicted_hit": hit_n,
                "predicted_saved_total": int(sum(saved)),
            })
            print(f"  {qname:>4} tol={tol_q:.4f} R={r_n}: "
                  f"预测命中 {hit_n}/{N_SEEDS}，节省 {sum(saved)} evals")
    r_star = next((int(s["rounds"]) for s in sweep
                   if s["tol_quantile"] == "q90"
                   and s["predicted_hit"] == N_SEEDS), None)
    if r_star is None:
        print("  q90 下无 R 达预测命中 100%——如实按 FAIL 出报告")
        r_star = max(
            (s for s in sweep if s["tol_quantile"] == "q90"),
            key=lambda s: (s["predicted_hit"], s["predicted_saved_total"]),
        )["rounds"]

    # ── ④ 早停臂真跑（配对同种子）+ 预声明门 ────────────────────────────────
    print(f"[4/4] 早停臂真跑：tol={tol_calib:.4f}(q90) R={r_star} …")
    early: list[dict[str, Any]] = []
    for s in range(SEED0, SEED0 + N_SEEDS):
        early.append(_run_arm(s, tol_calib, r_star))

    per_seed: list[dict[str, Any]] = []
    saved_pct: list[float] = []
    n_hit = 0
    prefix_ok = True
    for s, res_f, res_e in zip(range(N_SEEDS), full, early, strict=True):
        t_hit = hit_rounds[s]
        n_f, n_e = int(res_f["n_real_used"]), int(res_e["n_real_used"])
        hit = (t_hit is not None
               and min(res_e["real_cost_trace"]) <= target_cost)
        n_hit += int(hit)
        is_prefix = res_f["real_cost_trace"][:n_e] == res_e["real_cost_trace"]
        prefix_ok = prefix_ok and is_prefix
        pct = (100.0 * (n_f - n_e) / n_f) if n_f else 0.0
        saved_pct.append(pct)
        per_seed.append({
            "seed": s, "hit_round_full": t_hit, "hit": bool(hit),
            "n_full": n_f, "n_early": n_e, "evals_saved": n_f - n_e,
            "saved_pct": round(pct, 2),
            "early_stop_reason": res_e["stop_reason"],
            "early_trace_is_prefix": bool(is_prefix),
        })
    median_saved = float(np.median(saved_pct))
    hard_pass = n_hit == N_SEEDS
    soft_pass = median_saved >= 20.0
    verdict = "PASS" if hard_pass else "FAIL"
    report = {
        "ok": True,
        "protocol": {
            "function": "synthetic_noisy_bowl",
            "bounds": {k: list(v) for k, v in BOWL_BOUNDS.items()},
            "n_seeds": N_SEEDS, "seed0": SEED0, "n_init": N_INIT,
            "top_k": TOP_K, "max_real": MAX_REAL,
            "virtual_trials": VIRTUAL_TRIALS,
            "uncertainty_pool": UNCERTAINTY_POOL,
            "target_fraction": TARGET_FRACTION,
            "observe_tol": OBSERVE_TOL,
        },
        "target_bowl": target_bowl,
        "target_cost": target_cost,
        "function_min": f_min,
        "function_max": f_max,
        "full_arm_hit": n_full_hit,
        "sigma_hit_quantiles": {k: round(v, 6) for k, v in qs.items()},
        "tol_calibrated_q90": tol_calib,
        "uncertainty_rounds_selected": r_star,
        "sweep_predicted": sweep,
        "gates": {
            "hard_target_hit_100pct": {
                "pass": bool(hard_pass), "hit": n_hit, "of": N_SEEDS},
            "soft_median_saved_ge_20pct": {
                "pass": bool(soft_pass), "median_saved_pct": median_saved},
            "early_trace_is_prefix_of_full": bool(prefix_ok),
        },
        "verdict": verdict,
        "per_seed": per_seed,
        "note": ("硬门=早停臂 target 命中率 100%；软门=evals 节省中位 ≥20%；"
                 "未达如实记 FAIL 不凑绿（#122）。R 由离线扫描取 q90 下"
                 "预测命中 100% 的最小值（判据不影响采样，模拟精确）；"
                 "tol 标定为同种子内样本值（in-sample），跨分布外推需重标定"),
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1,
                                   default=str), encoding="utf-8")
    print(f"\n命中 {n_hit}/{N_SEEDS}（硬门{'PASS' if hard_pass else 'FAIL'}），"
          f"节省中位 {median_saved:.1f}%（软门{'PASS' if soft_pass else 'FAIL'}），"
          f"前缀性质 {'OK' if prefix_ok else 'BROKEN'}")
    print(f"tol(q90)={tol_calib:.4f}  R={r_star}  verdict={verdict}")
    print(f"落档: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
