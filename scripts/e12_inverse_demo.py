"""E12 像素域生成式逆设计最小闭环演示（6x6 域，零真机、纯闭式内核）。

链条（stage-1 档）：
    随机伯努利 + 1-bit 局部贪心提议器（只产出拓扑）
    → core/mapes.py MAPES 闭式内核（占用→Z_L(P)→Schur 补→S）
    → 指定通带/双阻带 hinge 评判（error_db + PASS/NEAR/MISS 等级）
    → top-k 记录。

诚实边界：Z_ALL 为合成 RLC 网格（stage-1 档，非真机提取）；扩散/流匹配
提议器未实现。数值纪律：全部数字由确定性评判器产出。

用法：
    .venv\\Scripts\\python.exe scripts\\e12_inverse_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from rfauto.core.inverse_design import (  # noqa: E402
    PassbandTarget,
    build_demo_model,
    run_inverse_search,
)
from rfauto.core.mapes import PixelLayout  # noqa: E402

N_ROWS, N_COLS = 6, 6
FREQ_HZ = np.linspace(0.5e9, 12.0e9, 24)
# 合成 RLC 网格常数（低损耗档：图案相关的谐振结构显著，校准见
# tests/unit/test_inverse_design.py 冻结常量）
MESH_KWARGS = dict(r_edge=0.01, l_edge=1.5e-10, g_node=0.001, c_node=5e-12)
TARGET = PassbandTarget(
    band_ghz=(5.5, 6.5),
    stop_low_ghz=(0.5, 3.0),
    stop_high_ghz=(9.5, 12.0),
    s21_pass_min_db=-8.0,
    s21_stop_low_max_db=-25.0,
    s21_stop_high_max_db=-12.0,
)


def main() -> int:
    layout = PixelLayout(n_rows=N_ROWS, n_cols=N_COLS, n_io_ports=2)
    model = build_demo_model(layout, FREQ_HZ, mesh_kwargs=MESH_KWARGS)
    result = run_inverse_search(
        model, TARGET, n_random=64, max_local_steps=8, k_top=5,
        seed=20260912)
    print(f"layout   : {result['layout']}")
    print(f"target   : {result['target']}")
    print(f"proposers: {result['proposers']}（{result['generative_note']}）")
    print(f"evaluate : {result['judge']}")
    print(f"随机阶段最优 error_db = "
          f"{result['random_phase']['best_error_db']:.4f}")
    lp = result["local_phase"]
    print(f"局部精修 : {lp['steps']} 步，{lp['start_error_db']:.4f} → "
          f"{lp['final_error_db']:.4f} dB（改善 {lp['improvement_db']:.4f}，"
          f"{lp['stop_reason']}）")
    best = result["best"]
    print(f"最优版图 : error_db={best['error_db']:.4f} grade={best['grade']} "
          f"占用 {best['n_occupied']}/{N_ROWS * N_COLS}")
    print(f"  通带 |S21|min = {best['s21_passband_min_db']:.2f} dB "
          f"(要求 ≥ {TARGET.s21_pass_min_db:g})")
    print(f"  阻带 |S21|max = {best['s21_stopband_max_db']:.2f} dB "
          f"(要求 ≤ 高阻带 {TARGET.s21_stop_high_max_db:g})")
    print(f"评估统计 : 唯一图案 {result['n_evaluated']}，"
          f"缓存命中 {result['n_cache_hits']}，elapsed {result['elapsed_s']}s")
    print("最优像素图案（1=占用）：")
    for row in best["occupancy"]:
        print("  ", "".join(str(x) for x in row))
    print("top-k：")
    for i, rec in enumerate(result["top_k"], 1):
        print(f"  #{i} error_db={rec['error_db']:.4f} grade={rec['grade']} "
              f"占用={rec['n_occupied']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
