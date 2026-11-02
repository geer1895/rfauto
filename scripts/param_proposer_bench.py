"""E12 参数域提议器三臂合成裁判（sphere / rosenbrock / 带纹波碗）。

配对臂（同 seed 序号、同评估预算）：
  annealed = ParamAnnealedProposer + 注入 score_fn（= 合成函数本身——
             "代理评判"语义：提议器消费的分数全部来自注入的评判器，
             逐候选评估计入预算，贪心不接受也花预算）；
  random   = 均匀随机搜索（非 LHS，house 口径，seed+7919 派生）；
  gplcb    = service.active_learning_search(source="gp")（LCB μ−βσ）。

裁判函数（定义域已知、闭式、与 fake 原生模型无关——#207）：
  sphere / rosenbrock 自写；带纹波碗只读复用
  service/active_learning.synthetic_noisy_bowl（含其密网格 range 口径）。

门（预声明，不改门凑绿）：
  G1 vs random：median(evals_random/evals_annealed) ≥ 1.30
  G2 vs gp-LCB：median(evals_gplcb /evals_annealed) ≥ 1.0
evals_to_target = 首次到达 f_min + 2%·(f_max−f_min) 的评估数（#207：阈值
高于极值下限防种子彩票）；未达标按预算截尾。逐函数出账 + 汇总；结果
如实——设计预期可能不敌 LCB，FAIL 也是交付。

用法（cwd 任意，产物绝对路径）：
  python scripts/param_proposer_bench.py [--seeds 15] [--budget 40]
      [--seed0 20260921] [--out runs/param_proposer_bench/bench.json]
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.optimization.param_proposer import ParamAnnealedProposer
from rfauto.service.active_learning import (
    BOWL_BOUNDS,
    active_learning_search,
    synthetic_bowl_range,
    synthetic_noisy_bowl,
)

REPO = Path(__file__).resolve().parents[1]

#: 预声明门（改门先改这里并同步 bench.json 的 thresholds 字段）。
GATE_VS_RANDOM = 1.30
GATE_VS_GPLCB = 1.00
TARGET_FRACTION = 0.02
N_INIT = 5
EVAL_FN = dict[str, float]  # 参数点 → cost（越小越好）


# ---------------------------------------------------------------- 裁判函数


def sphere_fn(params: dict[str, float]) -> float:
    """球面函数：f = x² + y²（凸、各向同性、全局最小 0 @ 原点）。"""
    x, y = float(params["x"]), float(params["y"])
    return x * x + y * y


def rosenbrock_fn(params: dict[str, float]) -> float:
    """Rosenbrock山谷：f = (1−x)² + 100(y−x²)²（全局最小 0 @ (1,1)）。"""
    x, y = float(params["x"]), float(params["y"])
    return (1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2


SQUARE_BOUNDS: dict[str, tuple[float, float]] = {"x": (-2.0, 2.0),
                                                 "y": (-2.0, 2.0)}


def _sphere_range(n: int = 401) -> tuple[float, float]:
    """sphere 密网格 (min, max)（向量化，与 synthetic_bowl_range 同口径）。"""
    x, y = np.meshgrid(np.linspace(-2.0, 2.0, n), np.linspace(-2.0, 2.0, n),
                       indexing="ij")
    vals = x * x + y * y
    return float(np.min(vals)), float(np.max(vals))


def _rosenbrock_range(n: int = 401) -> tuple[float, float]:
    """rosenbrock 密网格 (min, max)（向量化）。"""
    x, y = np.meshgrid(np.linspace(-2.0, 2.0, n), np.linspace(-2.0, 2.0, n),
                       indexing="ij")
    vals = (1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2
    return float(np.min(vals)), float(np.max(vals))


def bench_functions() -> list[dict[str, Any]]:
    """三裁判函数登记（名字/闭式/定义域/密网格极值——确定性）。"""
    fns: list[dict[str, Any]] = []
    for name, fn, bounds, range_fn in (
        ("sphere", sphere_fn, SQUARE_BOUNDS, _sphere_range),
        ("rosenbrock", rosenbrock_fn, SQUARE_BOUNDS, _rosenbrock_range),
        ("synthetic_noisy_bowl", synthetic_noisy_bowl, BOWL_BOUNDS,
         synthetic_bowl_range),
    ):
        f_min, f_max = range_fn()
        fns.append({"name": name, "fn": fn,
                    "bounds": {k: tuple(v) for k, v in bounds.items()},
                    "f_min": f_min, "f_max": f_max})
    return fns


# ---------------------------------------------------------------- 三臂


def arm_annealed(fn: EVAL_FN, bounds: dict[str, tuple[float, float]],
                 budget: int, seed: int,
                 proposer: ParamAnnealedProposer) -> list[float]:
    """退火提议器臂：评估序 = [起点] + [逐步候选]（贪心不接受也计预算）。"""
    rng = random.Random(seed)
    _best, trace = proposer.propose_with_trace(bounds, rng, score_fn=fn)
    costs = [trace[0]["score_best"]]
    costs += [rec["score_cand"] for rec in trace]
    return [float(c) for c in costs[:budget]]


def arm_random(fn: EVAL_FN, bounds: dict[str, tuple[float, float]],
               budget: int, seed: int) -> list[float]:
    """均匀随机搜索臂（i.i.d.，非 LHS——house 口径）。"""
    rng = np.random.default_rng(seed)
    names = sorted(bounds)
    out = []
    for _ in range(int(budget)):
        pt = {n: float(rng.uniform(bounds[n][0], bounds[n][1]))
              for n in names}
        out.append(float(fn(pt)))
    return out


def arm_gp_lcb(fn: EVAL_FN, bounds: dict[str, tuple[float, float]],
               budget: int, seed: int) -> list[float]:
    """gp-LCB 臂（house active_learning_search，LCB μ−βσ，确定性）。"""
    res = active_learning_search(fn, bounds, budget=budget, n_init=N_INIT,
                                 seed=seed, source="gp")
    return [float(s["metrics"]["cost"]) for s in res["samples"]]


def evals_to_target(costs: list[float], target: float, budget: int) -> int:
    """首次达标评估数；未达标按预算截尾（#207 同款语义）。"""
    for i, c in enumerate(costs):
        if c <= target:
            return i + 1
    return int(budget)


# ---------------------------------------------------------------- 主流程


def run_bench(n_seeds: int, budget: int, seed0: int,
              log=print) -> dict[str, Any]:
    """三函数 × 三臂 × n_seeds 配对基准；门判定如实（不凑绿）。"""
    n_steps = max(budget - 1, 1)  # 起点 1 次 + n_steps 候选 = budget 次评估
    proposer = ParamAnnealedProposer(n_steps=n_steps)
    functions = bench_functions()
    per_function: list[dict[str, Any]] = []
    for spec in functions:
        fn, bounds = spec["fn"], spec["bounds"]
        target = spec["f_min"] + TARGET_FRACTION * (spec["f_max"] - spec["f_min"])
        an_evals: list[int] = []
        rd_evals: list[int] = []
        lc_evals: list[int] = []
        best_costs: dict[str, list[float]] = {"annealed": [], "random": [],
                                              "gp_lcb": []}
        for s in range(n_seeds):
            seed = seed0 + s
            c_an = arm_annealed(fn, bounds, budget, seed, proposer)
            c_rd = arm_random(fn, bounds, budget, seed + 7919)
            c_lc = arm_gp_lcb(fn, bounds, budget, seed)
            an_evals.append(evals_to_target(c_an, target, budget))
            rd_evals.append(evals_to_target(c_rd, target, budget))
            lc_evals.append(evals_to_target(c_lc, target, budget))
            best_costs["annealed"].append(min(c_an))
            best_costs["random"].append(min(c_rd))
            best_costs["gp_lcb"].append(min(c_lc))
        sp_rd = [r / a for r, a in zip(rd_evals, an_evals, strict=True)]
        sp_lc = [c / a for c, a in zip(lc_evals, an_evals, strict=True)]
        med_rd = float(statistics.median(sp_rd))
        med_lc = float(statistics.median(sp_lc))
        g1 = bool(med_rd >= GATE_VS_RANDOM)
        g2 = bool(med_lc >= GATE_VS_GPLCB)
        per_function.append({
            "function": spec["name"],
            "bounds": {k: list(v) for k, v in bounds.items()},
            "f_min": spec["f_min"], "f_max": spec["f_max"],
            "target": target, "target_fraction": TARGET_FRACTION,
            "budget": budget, "n_steps_annealed": n_steps,
            "n_seeds": n_seeds, "seed0": seed0,
            "evals_to_target": {"annealed": an_evals, "random": rd_evals,
                                "gp_lcb": lc_evals},
            "best_cost_median": {k: float(statistics.median(v))
                                 for k, v in best_costs.items()},
            "speedup_vs_random": {"median": med_rd,
                                  "min": float(min(sp_rd)),
                                  "max": float(max(sp_rd))},
            "speedup_vs_gp_lcb": {"median": med_lc,
                                  "min": float(min(sp_lc)),
                                  "max": float(max(sp_lc))},
            "gates": {
                "G1_vs_random_ge_1.30": {"pass": g1,
                                         "median": med_rd,
                                         "gate": GATE_VS_RANDOM},
                "G2_vs_gp_lcb_ge_1.00": {"pass": g2,
                                         "median": med_lc,
                                         "gate": GATE_VS_GPLCB},
            },
            "pass": bool(g1 and g2),
        })
        log(f"[bench] {spec['name']}: median speedup vs random="
            f"{med_rd:.3f} (gate {GATE_VS_RANDOM} {'PASS' if g1 else 'FAIL'}), "
            f"vs gp-LCB={med_lc:.3f} (gate {GATE_VS_GPLCB} "
            f"{'PASS' if g2 else 'FAIL'})")

    overall = bool(all(f["pass"] for f in per_function))
    return {
        "schema": "param_proposer_bench/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "arms": {
            "annealed": "ParamAnnealedProposer（σ 退火高斯扰动+贪心接受，"
                        "score_fn=合成函数）",
            "random": "均匀随机搜索（seed+7919）",
            "gp_lcb": "active_learning_search(source=gp, LCB μ−βσ)",
        },
        "proposer_config": proposer.describe(),
        "thresholds": {"G1_vs_random": GATE_VS_RANDOM,
                       "G2_vs_gp_lcb": GATE_VS_GPLCB,
                       "target_fraction": TARGET_FRACTION},
        "note": ("evals_to_target 未达标按预算截尾；annealed 臂每候选评估"
                 "计入预算（贪心不接受也花预算）。结果如实，不调门凑绿。"),
        "functions": per_function,
        "overall": "PASS" if overall else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="E12 参数域提议器三臂合成裁判（预声明门，如实判定）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--seeds", type=int, default=15)
    ap.add_argument("--budget", type=int, default=40)
    ap.add_argument("--seed0", type=int, default=20260921)
    ap.add_argument("--out", type=str,
                    default="runs/param_proposer_bench/bench.json")
    args = ap.parse_args(argv)
    verdict = run_bench(args.seeds, args.budget, args.seed0)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"\n===== param_proposer_bench 摘要（overall={verdict['overall']}）"
          f" =====")
    for f in verdict["functions"]:
        g = f["gates"]
        print(f"{f['function']:>22}: vs random {g['G1_vs_random_ge_1.30']['median']:.3f} "
              f"({'PASS' if g['G1_vs_random_ge_1.30']['pass'] else 'FAIL'}) | "
              f"vs gp-LCB {g['G2_vs_gp_lcb_ge_1.00']['median']:.3f} "
              f"({'PASS' if g['G2_vs_gp_lcb_ge_1.00']['pass'] else 'FAIL'})")
    print(f"bench.json → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
