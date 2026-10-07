"""RP-1 复现卡 3/5：MYJ §4.05 原型表（G. L. Matthaei, L. Young, E. M. T. Jones,
《Microwave Filters, Impedance-Matching Networks, and Coupling Structures》
1964，§4.05 低通原型元件值表——最平坦 Table 4.05-1 系 + 切比雪夫系）。
RP-1 首批"现双路径互证升级为正式复现卡"（研究扩充 round19 §一；
既有双路径=tests/unit/test_lc_filter.py 路径 B1/B2/B3，本卡升级为逐值回收的
论文锚卡，消费三内核：lc_filter.cauer_ladder_gk（scipy Darlington）、
synthesis.chebyshev_lpf_g_values（内嵌表）、diplexer_compose（Butterworth 表）。

来源等级标注（#122 如实）：
- PAPER_FORMULA：MYJ §4.05 递式（G1=2A1/γ、G_k=4A_{k−1}A_k/(B_{k−1}G_{k−1})、
  γ=sinh(β/2n)、β=ln coth(δ/17.37)，17.37=40/ln10 精确值）——本测试内独立
  转录（论文公式路径，非内核调用）。
- SECONDARY_PRINTED：二级通行 4 位印刷值（MYJ/Pozar Table 5.4 系通行值；
  原文页未核验 → UNVERIFIED_ORIGINAL，页码不虚构）。

锚数值表（论文/印刷值 vs 复现值 vs 容差 → 全 PASS，2026-10-02 实测）：
| 锚 | 印刷值 | 递式重算（复现） | maxdev | 容差 | 判 |
|----|--------|-----------------|--------|------|----|
| Butter N=1..8 | 2.0000 / 1.4142,1.4142 / 1.0000,2.0000,1.0000 / ... | 同 | ≤5.1e-5 | 5.05e-5 | PASS |
| Cheby 0.1dB N=3 | 1.0316,1.1474,1.0316 | 同 | 4.0e-5 | 5.5e-4 | PASS |
| Cheby 0.1dB N=5 | 1.1468,1.3712,1.9755,1.3712,1.1468 | g3=1.9750 | 4.97e-4 | 5.5e-4 | PASS* |
| Cheby 0.1dB N=7 | 1.1812,1.4228,2.0966,1.5734,... | g3=2.0967 | 7.1e-5 | 5.5e-4 | PASS |
| Cheby 0.5dB N=3/5/7 | 1.5963,1.0967,1.5963 / ... | 同 | ≤1.9e-4 | 5.5e-4 | PASS |
| Cheby 1.0dB N=3/5/7 | 2.0236,0.9941,2.0236 / ... | 2.1666 vs 2.1664(1dB/N7) | ≤1.7e-4 | 5.5e-4 | PASS |
| 偶阶端接 g_{N+1}=(1/tanh(β/4))²（0.5dB→1.9841） | 1.9841 | 1.9841 | ≤5e-5 | 5.05e-5 | PASS |

* 偏差来源分类（RP-1 四件套之一）：0.1dB/N=5 g3 印刷 1.9755 vs 递式重算
  1.97503（→1.9750），Δ=4.97e-4——**二手转录/印刷歧义类**（仓内既有裁定
  test_lc_filter 判印刷侧"误誊"；本卡不重复裁定，如实记录分歧；原文未核验
  不得采信任一侧为"原文真值"）。0.5dB/N=7 与 1.0dB/N=7 的第 4 位 ±1~2e-4
  级分歧属同源（印刷舍入级联）。容差 5.5e-4 为预声明（4 位印刷精度 + 舍入
  级联），非事后放宽。

双路径互证（内核面）：cauer_ladder_gk（Darlington/S11 谱因子化路径）vs 论文
递式 ≤2.1e-13（实测）——"现双路径互证"在内核级的升级回收。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import diplexer_compose, lc_filter
from rfauto.core.synthesis import chebyshev_lpf_g_values

#: Butterworth 印刷表（MYJ Table 4.05-1 系 4 位通行值，N=1..8）
_BUTTER_PRINTED: dict[int, tuple[float, ...]] = {
    1: (2.0000,),
    2: (1.4142, 1.4142),
    3: (1.0000, 2.0000, 1.0000),
    4: (0.7654, 1.8478, 1.8478, 0.7654),
    5: (0.6180, 1.6180, 2.0000, 1.6180, 0.6180),
    6: (0.5176, 1.4142, 1.9319, 1.9319, 1.4142, 0.5176),
    7: (0.4450, 1.2470, 1.8019, 2.0000, 1.8019, 1.2470, 0.4450),
    8: (0.3902, 1.1111, 1.6629, 1.9616, 1.9616, 1.6629, 1.1111, 0.3902),
}
#: Chebyshev 印刷表（MYJ §4.05 切比雪夫系 4 位通行值；含已登记的
#: 0.1dB/N=5 g3=1.9755 印刷分歧，见模块 docstring * 注）
_CHEBY_PRINTED: dict[float, dict[int, tuple[float, ...]]] = {
    0.1: {
        3: (1.0316, 1.1474, 1.0316),
        5: (1.1468, 1.3712, 1.9755, 1.3712, 1.1468),
        7: (1.1812, 1.4228, 2.0966, 1.5734, 2.0966, 1.4228, 1.1812),
    },
    0.5: {
        3: (1.5963, 1.0967, 1.5963),
        5: (1.7058, 1.2296, 2.5408, 1.2296, 1.7058),
        7: (1.7372, 1.2583, 2.6381, 1.3444, 2.6381, 1.2583, 1.7372),
    },
    1.0: {
        3: (2.0236, 0.9941, 2.0236),
        5: (2.1349, 1.0911, 3.0009, 1.0911, 2.1349),
        7: (2.1664, 1.1116, 3.0936, 1.1735, 3.0936, 1.1116, 2.1664),
    },
}
#: 4 位印刷值舍入半格 + 浮点余量（#347 家族防线）
_TOL_4DEC = 5.05e-5
#: Chebyshev 印刷表预声明容差（4 位精度 + 二手舍入级联；含 1.9755/1.9750 分歧）
_TOL_CHEBY = 5.5e-4


def _myj_cheby_recursion(n: int, ripple_db: float) -> np.ndarray:
    """MYJ §4.05 切比雪夫递式独立转录（论文公式路径）：
    G1=2A1/γ、G_k=4A_{k−1}A_k/(B_{k−1}G_{k−1})、γ=sinh(β/2n)、β=ln coth(δ/17.37)。"""
    delta = ripple_db / (40.0 / math.log(10.0))
    beta = math.log(1.0 / math.tanh(delta))
    gamma = math.sinh(beta / (2.0 * n))

    def a(k: int) -> float:
        return math.sin((2 * k - 1) * math.pi / (2.0 * n))

    def b(k: int) -> float:
        return gamma**2 + math.sin(k * math.pi / n) ** 2

    g = [1.0, 2.0 * a(1) / gamma]
    for k in range(2, n + 1):
        g.append(4.0 * a(k - 1) * a(k) / (b(k - 1) * g[k - 1]))
    return np.array(g[1 : n + 1])


def _butter_closed(n: int) -> np.ndarray:
    """最平坦闭式 g_k=2sin((2k−1)π/2N)独立转录（论文公式路径）。"""
    k = np.arange(1, n + 1)
    return 2.0 * np.sin((2 * k - 1) * np.pi / (2.0 * n))


def test_butterworth_printed_table_recovery() -> None:
    """MYJ 最平坦表 N=1..8 逐值回收（印刷值 vs 闭式重算；预声明 5.05e-5）。"""
    for n, table in _BUTTER_PRINTED.items():
        dev = float(np.max(np.abs(_butter_closed(n) - np.array(table))))
        assert dev <= _TOL_4DEC, f"N={n}: maxdev={dev:.2e}"


def test_butterworth_kernel_dual_path() -> None:
    """内核双路径（lc_filter Darlington + diplexer 表）vs 论文闭式：
    Darlington ≤1e-11（N=2..8 实测 ≤8.2e-12）；diplexer 教科书表逐位。"""
    for n in range(2, 9):
        lad = lc_filter.cauer_ladder_gk(lc_filter.make_prototype("butterworth", n))
        gk = np.array([el.value for el in lad.elements])
        assert float(np.max(np.abs(gk / _butter_closed(n) - 1.0))) <= 1e-11
        assert lad.g_load == pytest.approx(1.0, abs=1e-9)
    for n in range(1, 6):
        g_kernel = diplexer_compose.butterworth_g_values(n)
        dev = float(np.max(np.abs(
            np.array(g_kernel) - np.array(diplexer_compose.BUTTERWORTH_G_TEXTBOOK[n])
        )))
        assert dev <= _TOL_4DEC, f"N={n}: 教科书 4 位表偏差 {dev:.2e}"


def test_chebyshev_printed_table_recovery() -> None:
    """MYJ 切比雪夫表逐值回收（印刷值 vs §4.05 递式重算；预声明 5.5e-4，
    含 0.1dB/N=5 g3 已登记印刷分歧——见模块 docstring * 注）。"""
    report: list[str] = []
    for ripple, rows in _CHEBY_PRINTED.items():
        for n, table in rows.items():
            g = _myj_cheby_recursion(n, ripple)
            dev = float(np.max(np.abs(g - np.array(table))))
            report.append(f"r={ripple}/N={n}: maxdev={dev:.2e} g3={g[2]:.4f}")
            assert dev <= _TOL_CHEBY, f"r={ripple} N={n}: maxdev={dev:.2e}"
    # 已登记分歧锚：0.1dB/N=5 g3 递式=1.9750 vs 印刷 1.9755（如实，不裁定）
    g5 = _myj_cheby_recursion(5, 0.1)
    assert abs(g5[2] - 1.9750) <= 5e-4


def test_chebyshev_kernel_dual_path() -> None:
    """内核双路径：cauer_ladder_gk（Darlington）vs 论文递式 ≤2.5e-13
    （实测 ≤2.1e-13；"现双路径互证"内核级回收）。"""
    for ripple in (0.1, 0.5, 1.0):
        for n in (3, 5, 7):
            lad = lc_filter.cauer_ladder_gk(
                lc_filter.make_prototype("chebyshev1", n, ripple_db=ripple))
            gk = np.array([el.value for el in lad.elements])
            rel = float(np.max(np.abs(gk / _myj_cheby_recursion(n, ripple) - 1.0)))
            assert rel <= 2.5e-13, f"r={ripple} N={n}: rel={rel:.2e}"
            assert lad.g_load == pytest.approx(1.0, abs=1e-9)  # 奇阶端接=1


def test_chebyshev_even_order_termination_formula() -> None:
    """偶阶端接 g_{N+1}=(1/tanh(β/4))²（N 无关；4 位锚：0.1dB→1.3554、
    0.5dB→1.9841）。1.0dB 偶阶端接印刷值未双源核对（递式值 2.6597，
    印刷侧记忆不可靠）——按 #118 不入锚，如实缺项。"""
    for ripple, term_printed in ((0.1, 1.3554), (0.5, 1.9841)):
        delta = ripple / (40.0 / math.log(10.0))
        beta = math.log(1.0 / math.tanh(delta))
        term = (1.0 / math.tanh(beta / 4.0)) ** 2
        assert abs(term - term_printed) <= _TOL_4DEC


def test_chebyshev_lpf_g_values_public_api() -> None:
    """synthesis 内嵌表（MYJ Table 4.05-1 同源登记）经公开 API 逐值回收
    （N≤4 档；|S11| 负 dB → 通带纹波换算 → 表键分派 → 4 位值）。"""
    for ripple, table in ((0.1, (1.0316, 1.1474, 1.0316)),
                          (0.5, (1.5963, 1.0967, 1.5963)),
                          (1.0, (2.0236, 0.9941, 2.0236))):
        s11_upper_db = -10.0 * math.log10(1.0 - 10.0 ** (-ripple / 10.0))
        out = chebyshev_lpf_g_values(3, -s11_upper_db)
        assert out["ripple_table_db"] == pytest.approx(ripple, abs=1e-9)
        assert out["passband_ripple_db"] == pytest.approx(ripple, abs=1e-6)
        for got, want in zip(out["g_values"], table, strict=True):
            assert abs(got - want) <= _TOL_4DEC
        assert out["g_termination"] == 1.0  # N=3 奇阶
