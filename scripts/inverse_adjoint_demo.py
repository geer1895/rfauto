"""E5 逆向设计研究线演示：JAX 可微 1D FDTD 伴随拓扑优化（CPU 小规模，研究分支）。

跑三件事并把证据落成可读报告：
1. 均匀介质板透射 vs Airy 闭式解（独立裁判，物理 + 离散色散修正两版）；
2. jax.grad（伴随/反向模式）vs 中心有限差分；
3. 1D 反射器逆设计（密度参数化 + 移动平均滤波 + tanh 投影 + beta 退火）：
   打印优化前后目标值曲线，并用 TMM 解析解独立交叉验证。

用法::

    .venv/Scripts/python.exe scripts/inverse_adjoint_demo.py
    .venv/Scripts/python.exe scripts/inverse_adjoint_demo.py --iterations 40 --out runs/inverse_adjoint/demo.json
    .venv/Scripts/python.exe scripts/inverse_adjoint_demo.py --notes

退出码：0 = 全部判据通过；2 = 任一判据未过（如实标 partial，不凑绿）。
不读写用户资产、不联网、不跑大规模真机；固定种子确定性。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from rfauto.core import inverse_adjoint as ia  # noqa: E402

SLAB_CASES = ((2.0, 14), (1.5, 35), (2.0, 30), (4.0, 40), (6.0, 20))
AIRY_REL_TOL = 0.05
SPARK = " .:-=+*#%@"


def _sparkline(values: list[float]) -> str:
    """把 T 曲线映射成 ASCII：纵轴 = -log10(T)（越高=反射越强，对数刻度）。"""
    if not values:
        return ""
    scores = [-math.log10(max(float(value), 1e-12)) for value in values]
    lo, hi = min(scores), max(scores)
    span = (hi - lo) or 1.0
    chars = []
    for score in scores:
        idx = round((score - lo) / span * (len(SPARK) - 1))
        chars.append(SPARK[min(max(idx, 0), len(SPARK) - 1)])
    return "".join(chars)


def run_demo(iterations: int, beta_end: float, eps_max: float) -> dict:
    cfg = ia.FDTD1DConfig(eps_max=float(eps_max))
    slab = [ia.homogeneous_slab_report(eps_r, thickness, cfg) for eps_r, thickness in SLAB_CASES]
    gradient = ia.gradient_check(cfg, beta=1.0, seed=0, components=4)
    design = ia.optimize_density(
        cfg, ia.OptimizeConfig(iterations=int(iterations), beta_end=float(beta_end), sense="min", seed=0)
    )
    final_beta = design["beta_history"][-1]
    cross = ia.tmm_fdtd_cross_check(np.asarray(design["density"]), final_beta, cfg)

    valid = [r["rel_error_physical"] for r in slab if r["rel_error_physical"] is not None]
    max_slab_rel = max(valid) if valid else None
    criteria = {
        "airy_validation": bool(max_slab_rel is not None and max_slab_rel <= AIRY_REL_TOL),
        "gradient_fd_match": bool(
            gradient["max_relative_error"] is not None
            and gradient["max_relative_error"] <= ia.GRAD_REL_TOL
        ),
        "objective_improved": bool(
            design["final_objective"] < 0.05 * design["initial_objective_final_beta"]
            and design["strict_improvements"] >= 5
        ),
        "tmm_strong_reflection": bool(cross["tmm_numerical"] < 0.05 and cross["tmm_physical"] < 0.05),
    }
    return {
        "config": design["config"],
        "slab_validation": slab,
        "max_slab_rel_error_physical": max_slab_rel,
        "gradient_check": gradient,
        "design": design,
        "cross_check_final": cross,
        "criteria": criteria,
        "passed": all(criteria.values()),
    }


def render(report: dict) -> str:
    lines = ["E5 逆向设计研究线 · JAX 可微 1D FDTD 伴随拓扑优化（CPU 小规模）", "=" * 72]
    lines.append("[1] 均匀板 FDTD vs Airy 闭式解（独立裁判）")
    for row in report["slab_validation"]:
        lines.append(
            "    eps={eps_r:<4} d={thickness_cells:<3} T_fdtd={transmission_fdtd:.6f} "
            "T_airy={airy_physical:.6f} rel_phys={rel_error_physical:.2e} "
            "rel_num={rel_error_numerical:.2e}".format(**row)
        )
    lines.append(
        "    max rel(physical) = {:.3e}  (tol {})".format(report["max_slab_rel_error_physical"], AIRY_REL_TOL)
    )
    grad = report["gradient_check"]
    lines.append("[2] jax.grad vs 中心有限差分")
    lines.append(
        "    step={step:.1e} x64={x64} max_rel={max_relative_error:.3e} (tol {tol})".format(
            tol=ia.GRAD_REL_TOL, **grad
        )
    )
    design = report["design"]
    lines.append("[3] 1D 反射器逆设计（透射极小，目标频率功率透射率）")
    lines.append(
        "    T(rho0,beta0)={:.6f}  T(rho0,beta_end)={:.6f}  T(rho*,beta_end)={:.3e}".format(
            design["initial_objective"],
            design["initial_objective_final_beta"],
            design["final_objective"],
        )
    )
    lines.append(
        "    strict_improvements={strict_improvements} accepted_steps={accepted_steps} "
        "binary_score={binary_score:.4f}".format(**design)
    )
    lines.append("    best-so-far -log10(T) 曲线: " + _sparkline(design["objective_history_best"]))
    cross = report["cross_check_final"]
    lines.append(
        "    TMM 交叉验证（末代结构）: T_fdtd={transmission_fdtd:.3e} "
        "TMM_num={tmm_numerical:.3e} TMM_phys={tmm_physical:.3e}".format(**cross)
    )
    lines.append("[判据] " + " ".join("{k}={v}".format(k=k, v="PASS" if v else "FAIL") for k, v in report["criteria"].items()))
    verdict = "PASS（研究分支，1D CPU 小规模）" if report["passed"] else "PARTIAL（见上 FAIL 项，不凑绿）"
    lines.append("结论: " + verdict)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--beta-end", type=float, default=32.0)
    parser.add_argument("--eps-max", type=float, default=6.0)
    parser.add_argument("--out", default=None, help="可选 JSON 报告路径（不指定则不写盘）")
    parser.add_argument("--notes", action="store_true", help="只打印文献/范围说明，不跑仿真")
    args = parser.parse_args(argv)

    if args.notes:
        for note in ia.LITERATURE_NOTES:
            print("- " + note)
        return 0

    report = run_demo(args.iterations, args.beta_end, args.eps_max)
    print(render(report))
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告 -> {out}")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
