"""W4-C P6：精确球模 Q 界（式(42)/(47)/(51)）+ 三门带 verdict 锚测试。

原文核对证据（#1c，2026-10-05）：
- 主源：A.D. Yaghjian, "Fundamentals of Antenna Bandwidth and Quality
  Factors," arXiv:2501.03146（开放 PDF 本地存证
  runs/w4_phase4/w4c/evidence/arxiv_2501_03146.pdf）——式(42)/(47)/(51)
  印刷页 10-11 视觉读式；式(40a-c)/(41)/(44)/(49)/(50) 球模阻抗与调谐 Q
  定义同源。
- 谱系勘误（实测原文引用）：Thal "Gain and Q bounds for coupled TM-TE
  modes" = IEEE TAP 57(7):1879-1885, **2009**（SM 报告误记 54(10) 2006）；
  Thal "New radiation Q limits for spherical wire antennas" = TAP
  54:2757-2763, 2006（空气芯球面电流类 ≈1.5×Chu 的类特定界，本模块注记
  不设门）。
- McLean 1996（既有 chu_q_bound）= 1/x³+1/x 对照行。

裁判制度（#118 三路径）：
A. 球 Hankel 阻抗数值路径（scipy，式(40b/c)+(41)+(50a)）独立回收三闭式；
B. n=1 有理式手推路径：Z^TM_1 = x²/(1+x²) − j/(x(1+x²))（测试 docstring
   留推导），FD 导数进式(41)——与实现同式不同排布；
C. 结构/展开锚：小 ka 渐近、半 Q 带、序关系、与既有 McLean 门衔接。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from scipy.special import spherical_jn, spherical_yn

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.antenna_q import q_reachability_band, q_reachability_verdict
from rfauto.core.bounds import chu_q_bound, exact_spherical_q_bounds

GRID = (0.05, 0.1, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0)

# ─── 路径 A：球 Hankel 阻抗数值裁判（独立编码）────────────────────────────────


def _h2(n: int, x: float) -> complex:
    return spherical_jn(n, x) - 1j * spherical_yn(n, x)


def _z_tm(x: float) -> complex:
    """式(40a)：Z^TM_1 = j·[x·h_1^(2)]′/(x·h_1^(2))，(xh)′=x·h_0−n·h_n。"""
    xh = x * _h2(1, x)
    return 1j * (x * _h2(0, x) - _h2(1, x)) / xh


def _q_tuned(z_fun, x: float) -> float:
    """式(41)/(45)：Q = x/(2R)·√(R′²+(X′+|X|/x)²)，FD 导数。"""
    z = z_fun(x)
    h = 1e-6
    rp = (z_fun(x + h).real - z_fun(x - h).real) / (2 * h)
    xp = (z_fun(x + h).imag - z_fun(x - h).imag) / (2 * h)
    return x / (2 * z.real) * math.sqrt(
        rp * rp + (xp + abs(z.imag) / x) ** 2)


def _q_tmte_num(x: float) -> float:
    """式(50a/c)：|（1+γ)·Q̃^TM/2|，γ=−(Z*/Z)，Q̃^TM=−j x Z′/(2R)。"""
    z = _z_tm(x)
    h = 1e-6
    zp = (_z_tm(x + h) - _z_tm(x - h)) / (2 * h)
    q_ut = -1j * x * zp / (2 * z.real)
    gamma = -np.conj(z) / z
    return abs((1 + gamma) * q_ut / 2)


# ─── 闭式 vs 数值裁判（#118 双路径互证）───────────────────────────────────────

@pytest.mark.parametrize("x", GRID)
def test_closed_forms_match_hankel_impedance_route(x):
    b = exact_spherical_q_bounds(x)
    assert b.q_tm1 == pytest.approx(_q_tuned(_z_tm, x), rel=1e-6)
    assert b.q_te1 == pytest.approx(_q_tuned(lambda t: 1.0 / _z_tm(t), x), rel=1e-6)
    assert b.q_tmte1 == pytest.approx(_q_tmte_num(x), rel=1e-6)


def test_rational_z_tm_hand_derivation_judge():
    """路径 B：手推 Z^TM_1 有理式 → 式(41) 数值 → 闭式（rel 1e-9）。

    推导（h_1^(2) = −e^{−jx}(x−j)/x² 起点，代数化简）：
    x·h_1^(2) = e^{−jx}(j/x − 1)；(xh)′ = e^{−jx}(1/x + j − j/x²)；
    Z = j(xh)′/(xh) = j(1/x + j − j/x²)/(j/x − 1) = (1 − j/x³)/(1 + 1/x²)
      = x²/(1+x²) − j/(x(1+x²))。
    故 R = x²/(1+x²)，X = −1/(x(1+x²))。
    """
    def z(x):
        return complex(x * x / (1 + x * x), -1.0 / (x * (1 + x * x)))

    for x in GRID:
        # 有理式与 hankel 阻抗一致（推导自检）
        assert z(x) == pytest.approx(_z_tm(x), rel=1e-9, abs=1e-12)
        h = 1e-6
        rp = (z(x + h).real - z(x - h).real) / (2 * h)
        xp = (z(x + h).imag - z(x - h).imag) / (2 * h)
        zz = z(x)
        q = x / (2 * zz.real) * math.sqrt(rp * rp + (xp + abs(zz.imag) / x) ** 2)
        b = exact_spherical_q_bounds(x)
        assert b.q_tm1 == pytest.approx(q, rel=1e-9)


# ─── 结构/展开锚 ─────────────────────────────────────────────────────────────

def test_small_ka_expansion_anchors():
    """小 ka 渐近锚：式(42)→1/x³+1/x−x；式(51)→1/(2x³)+1/x−x（+O(x³)）。

    注记：arXiv 文本层把式(51) 渐近行渲染成 "1/2·1/(ka)³ + 2/ka − ka" 的
    token 串（分数版式扁平化歧义）；按闭式（其本身已被 hankel 阻抗路径
    1e-10 钉死）数值定渐近系数为 1/(2x³)+1/x−x（x=0.05 残差 2e-4=下一项
    ~1.75x³ 量级），不以歧义 token 为锚。
    """
    x = 0.05
    b = exact_spherical_q_bounds(x)
    assert b.q_tm1 == pytest.approx(1 / x**3 + 1 / x - x, rel=1e-6)
    assert b.q_tmte1 == pytest.approx(1 / (2 * x**3) + 1 / x - x, rel=1e-6)
    # O(x³) 尾量真实存在（下一项 ~1.75x³ 级，残差非零但同量级）
    assert abs(b.q_tmte1 - (1 / (2 * x**3) + 1 / x - x)) < 3.0 * x**3


def test_exact_bounds_below_mclean_chu():
    """式(42)/(47) 严格低于 McLean/CR（原文 "smaller in value than ... Chu/CR"）。"""
    grid = np.array(GRID)
    b = exact_spherical_q_bounds(grid)
    assert np.all(b.q_tm1 < b.q_chu_mclean)
    assert np.all(b.q_te1 < b.q_chu_mclean)


def test_tmte_about_half_for_small_ka():
    """式(51) ≈ 单模之半（原文 "nearly equal to half ... for ka ≲ 1"）：
    比值窗 [0.45, 0.65]（x≤1），x>1 后走 1/x⁵ 尾快速下降。"""
    for x in (0.05, 0.1, 0.3, 0.5, 0.8, 1.0):
        b = exact_spherical_q_bounds(x)
        ratio = b.q_tmte1 / b.q_tm1
        assert 0.45 <= ratio <= 0.65, (x, ratio)
    # 大 ka 尾序：TMTE 明显低于单模
    for x in (2.0, 3.0):
        b = exact_spherical_q_bounds(x)
        assert b.q_tmte1 < 0.5 * b.q_tm1


def test_monotone_decreasing_in_ka():
    """三界随 ka 单调下降（电小→电大 Q 界递减）。"""
    grid = np.array(GRID)
    b = exact_spherical_q_bounds(grid)
    for arr in (b.q_tm1, b.q_te1, b.q_tmte1, b.q_chu_mclean):
        assert all(u > v for u, v in pairwise(arr.tolist()))


def test_consistency_with_mclean_chu_q_bound():
    """q_chu_mclean 行与既有 chu_q_bound 逐位一致（rel 1e-15）。"""
    for x in (0.1, 1.0, 3.0):
        b = exact_spherical_q_bounds(x)
        chu = float(chu_q_bound(x).limit_value)
        assert b.q_chu_mclean == pytest.approx(chu, rel=1e-15)


def test_array_vectorization_and_scalar_shape():
    """数组向量化逐元素 = 标量逐点；标量入标量出。"""
    grid = np.array(GRID)
    b_arr = exact_spherical_q_bounds(grid)
    for i, x in enumerate(GRID):
        b_s = exact_spherical_q_bounds(x)
        assert b_arr.q_tm1[i] == pytest.approx(b_s.q_tm1, rel=1e-15)
        assert b_arr.q_tmte1[i] == pytest.approx(b_s.q_tmte1, rel=1e-15)
    assert isinstance(exact_spherical_q_bounds(0.5).q_tm1, float)


def test_guards_reject_bad_ka():
    with pytest.raises(ValueError, match="ka"):
        exact_spherical_q_bounds(0.0)
    with pytest.raises(ValueError, match="ka"):
        exact_spherical_q_bounds(-1.0)
    with pytest.raises(ValueError, match="ka"):
        exact_spherical_q_bounds(float("nan"))
    with pytest.raises(ValueError, match="ka"):
        exact_spherical_q_bounds([])


def test_to_dict_json_roundtrip():
    b = exact_spherical_q_bounds(0.5)
    d = b.to_dict()
    assert set(d) == {"ka", "q_tm1", "q_te1", "q_tmte1", "q_chu_mclean"}
    import json
    json.dumps(d)  # JSON 可序列化


# ─── 三门带 verdict ──────────────────────────────────────────────────────────

def test_band_verdict_three_tiers():
    """三档语义：≥单模门 → reachable；两门之间 → with_coupled；<耦合门 → unreachable。"""
    ka = 0.3
    b = exact_spherical_q_bounds(ka)
    above = q_reachability_band(ka, b.q_tm1 * 1.5)
    assert above["verdict"] == "reachable"
    between = q_reachability_band(ka, (b.q_tm1 + b.q_tmte1) / 2.0)
    assert between["verdict"] == "reachable_with_coupled_modes"
    below = q_reachability_band(ka, b.q_tmte1 * 0.5)
    assert below["verdict"] == "unreachable"


def test_band_tol_semantics_and_gates_in_output():
    """tol 贴界余量：恰在门上不判违约（#347）；输出带全部门值。"""
    ka = 0.5
    b = exact_spherical_q_bounds(ka)
    at_gate = q_reachability_band(ka, b.q_tmte1)  # 恰等耦合门 → with_coupled 非 unreachable
    assert at_gate["verdict"] == "reachable_with_coupled_modes"
    out = q_reachability_band(ka, b.q_tm1 * 2.0)
    for key in ("verdict", "q_measured", "q_gate_single", "q_gate_coupled",
                "q_min_chu_mclean", "ka", "margin_ratio_single",
                "margin_ratio_coupled", "tol", "source"):
        assert key in out
    import json
    json.dumps(out)


def test_band_circular_halving_and_legacy_single_gate_consistency():
    """circular 减半约定与既有口径一致；linear 档小 ka 与 legacy 单门 verdict
    语义衔接（小 ka 精确界≈McLean，reachable 判定应一致）。"""
    ka = 0.2
    lin = q_reachability_band(ka, 500.0, polarization="linear")
    cir = q_reachability_band(ka, 500.0, polarization="circular")
    assert cir["q_gate_single"] == pytest.approx(lin["q_gate_single"] / 2.0, rel=1e-15)
    assert cir["q_gate_coupled"] == pytest.approx(lin["q_gate_coupled"] / 2.0, rel=1e-15)
    # legacy（McLean 单门）与 band 在"明显高于界"处同为 reachable
    legacy = q_reachability_verdict(ka, 500.0)
    assert legacy["verdict"] == "reachable" and lin["verdict"] == "reachable"


def test_band_guards():
    with pytest.raises(ValueError, match="q_measured"):
        q_reachability_band(0.5, -1.0)
    with pytest.raises(ValueError, match="tol"):
        q_reachability_band(0.5, 10.0, tol=1.0)
    with pytest.raises(ValueError, match="polarization"):
        q_reachability_band(0.5, 10.0, polarization="elliptic")
