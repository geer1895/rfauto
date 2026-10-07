"""TF-3 短路 stub / K-inverter 内核单测（round5 §4.2 判据）。

裁判口径（#118 双路径/独立来源）：
- Richards 恒等式：f→Ω→f 往返 + Ω(f0)=1 逐位 + θ 线性度。
- 并联电纳↔K 等效：ABCD 矩阵逐元素相等（自推导 vs 独立构造的级联，
  模块零共享代码路径）≤1e-12；反演 b̄=1/k−k 闭式 1e-12。
- g→倒置器：测试内独立重写 Hong-Lancaster eq.(5.32) 闭式（rel 1e-12）
  + 手算锚（butter N=3, FBW=0.1）+ g 值经 core/lc_filter 独立供给
  （模块不 import lc_filter，双路径不被同源污染）。
- 频响面：ABCD 级联 vs 理想带通原型（常规窄带映射，声明近似源）。
  预声明门（模块 docstring 已登记实测余量）：butter N=5 FBW=0.05
  −3dB 带宽 rel ≤5%（实测 −3.7%）、带边 ≤1%（实测 ≤0.12%）、内带
  ≤0.3dB（实测 0.095dB）；FBW 单调收敛性作为窄带近似自洽性证据。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import lc_filter
from rfauto.core import stub_k_inverter as ski

F0 = 1e9
Z0 = 50.0


def g_butter(n: int) -> list[float]:
    """butterworth g_k 闭式（测试独立路径；2sin((2k−1)π/2N)）。"""
    return [1.0] + [2.0 * math.sin((2 * k - 1) * math.pi / (2 * n)) for k in range(1, n + 1)] + [1.0]


def g_cheby3_01db() -> list[float]:
    """chebyshev 0.1dB N=3 的 g_k：经 lc_filter 既有递式独立供给（#118 双路径）。"""
    ladder = lc_filter.cauer_ladder_gk(lc_filter.make_prototype("chebyshev1", 3, ripple_db=0.1))
    return [1.0] + [el.value for el in ladder.elements] + [ladder.g_load]


def ideal_bandpass_gain_lin(
    freqs: np.ndarray, f0: float, fbw: float, n: int, response: str = "butter",
    ripple_db: float = 0.1,
) -> np.ndarray:
    """理想带通原型 |S21|（常规窄带映射，声明近似源）。"""
    omega = (freqs / f0 - f0 / freqs) / fbw
    if response == "butter":
        return 1.0 / np.sqrt(1.0 + omega ** (2 * n))
    eps2 = 10 ** (ripple_db / 10) - 1
    tn = np.cos(n * np.arccos(np.clip(omega, -1.0, 1.0)))
    return 1.0 / np.sqrt(1.0 + eps2 * tn**2)


# ─── 1. Richards 变换 ────────────────────────────────────────────────────────


def test_richards_roundtrip_identity():
    # 主支单调域 f < 2·f0（θ0·f/f0 < π/2，Richards 折叠支不在此列）
    for f in (0.0, 0.137e9, 0.5e9, F0, 1.731e9):
        omega = ski.richards_omega(f, F0)
        assert ski.richards_omega_inverse(omega, F0) == pytest.approx(f, rel=1e-12, abs=0.0)


def test_richards_anchor_points_exact():
    # Ω(f0)=1 与 Ω(0)=0 逐位（θ0=π/4 口径钉死）
    assert ski.richards_omega(F0, F0) == 1.0
    assert ski.richards_omega(0.0, F0) == 0.0
    # θ0 换档：θ0=π/6 时 Ω(f0)=tan(π/6)/tan(π/6)=1 仍逐位
    assert ski.richards_omega(F0, F0, theta0=math.pi / 6) == 1.0


def test_richards_monotone_and_stub_length():
    # 单调性与 stub 电长度律：θ(f0)=π/2 逐位，θ 线性于 f
    w1 = ski.richards_omega(0.25 * F0, F0)
    w2 = ski.richards_omega(1.5 * F0, F0)
    assert 0.0 < w1 < 1.0 < w2
    assert ski.stub_elec_length(F0, F0) == math.pi / 2
    assert ski.stub_elec_length(0.5 * F0, F0) == math.pi / 4
    assert ski.stub_elec_length(0.25 * F0, F0) * 2 == ski.stub_elec_length(0.5 * F0, F0)


def test_richards_input_guards():
    with pytest.raises(ValueError):
        ski.richards_omega(-1.0, F0)
    with pytest.raises(ValueError):
        ski.richards_omega(1.0, 0.0)
    with pytest.raises(ValueError):
        ski.richards_omega(1.0, F0, theta0=math.pi / 2)  # 端点属外
    with pytest.raises(ValueError):
        ski.richards_omega_inverse(-0.1, F0)  # 主支 Ω>=0
    with pytest.raises(ValueError):
        ski.richards_omega(True, F0)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        ski.stub_elec_length(float("nan"), F0)


# ─── 2. 并联电纳 ↔ K-inverter 精确等效 ───────────────────────────────────────


def _tline_abcd(theta: float, z: float = 1.0) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, 1j * z * s], [1j * s / z, c]])


def test_shunt_b_k_abcd_equivalence_exact():
    # [并联 jB] == [−θ/2 线][K 倒置器][−θ/2 线]：ABCD 逐元素 ≤1e-12（自推导裁判）
    for b in (-2.0, -0.5, 0.5, 2.0):
        theta = ski.shunt_b_to_neg_length(b)
        k = ski.shunt_b_to_k(b)
        net = (
            _tline_abcd(-theta / 2.0)
            @ np.array([[0.0, 1j * k], [1j / k, 0.0]])
            @ _tline_abcd(-theta / 2.0)
        )
        shunt = np.array([[1.0, 0.0], [1j * b, 1.0]])
        assert np.max(np.abs(net - shunt)) <= 1e-12


def test_shunt_b_k_roundtrip_identity():
    for b in (-2.0, -0.5, 0.5, 2.0):
        k = ski.shunt_b_to_k(b)
        assert k * b > 0.0  # 带符号口径：k 与 b 同号（恒等式所需）
        assert ski.k_to_shunt_b(k) == pytest.approx(b, rel=1e-12)
    # b̄→0⁺ 极限 → |k|→1（|K|=Z0 全四分之一波长）
    assert abs(ski.shunt_b_to_k(1e-9)) == pytest.approx(1.0, rel=1e-6)


def test_shunt_b_guards():
    with pytest.raises(ValueError):
        ski.shunt_b_to_neg_length(0.0)  # 无元件退化，显式拒绝
    with pytest.raises(ValueError):
        ski.shunt_b_to_neg_length(float("inf"))
    with pytest.raises(ValueError):
        ski.shunt_b_to_neg_length(True)
    with pytest.raises(ValueError):
        ski.k_to_shunt_b(0.0)  # k 必须 >0


# ─── 3. g→倒置器表 ───────────────────────────────────────────────────────────


def test_inverter_table_butter_anchor_and_recycle():
    g = g_butter(3)
    fbw = 0.1
    jbar = ski.inverter_table(g, fbw)
    # 测试内独立重写 Hong-Lancaster eq.(5.32) 闭式（双路径）：n+1 项
    # （j01, j12, j23, j34——负载端倒置器 j_n,n+1 也在表内）
    expect = [
        math.sqrt(math.pi * fbw / (2 * g[0] * g[1])),
        math.pi * fbw / 2 / math.sqrt(g[1] * g[2]),
        math.pi * fbw / 2 / math.sqrt(g[2] * g[3]),
        math.sqrt(math.pi * fbw / (2 * g[3] * g[4])),
    ]
    assert jbar == pytest.approx(expect, rel=1e-12)
    # 手算锚（butter N=3, FBW=0.1：g=[1,1,2,1]）
    assert jbar[0] == pytest.approx(math.sqrt(math.pi * 0.1 / 2), rel=1e-12)
    assert jbar[1] == pytest.approx(math.pi * 0.1 / (2 * math.sqrt(2)), rel=1e-12)


def test_inverter_table_reciprocal_symmetry():
    # 互易对称原型（butter：g0=g6=1、g1=g5、g2=g4）→ 倒置器表回文
    # （sin(π/10) vs sin(9π/10) 末位 ulp 差 → rel 1e-15 而非逐位）
    g = g_butter(5)
    jbar = ski.inverter_table(g, 0.05)
    assert len(jbar) == 6
    assert jbar[0] == pytest.approx(jbar[-1], rel=1e-15)
    assert jbar[1] == pytest.approx(jbar[-2], rel=1e-15)
    assert jbar[2] == pytest.approx(jbar[-3], rel=1e-12)


def test_inverter_table_cheby_via_lc_filter_g():
    # g 由 lc_filter 独立供给（模块不 import，#118 双路径不被同源污染）
    g = g_cheby3_01db()
    fbw = 0.05
    jbar = ski.inverter_table(g, fbw)
    expect = [
        math.sqrt(math.pi * fbw / (2 * g[0] * g[1])),
        math.pi * fbw / 2 / math.sqrt(g[1] * g[2]),
        math.pi * fbw / 2 / math.sqrt(g[2] * g[3]),
        math.sqrt(math.pi * fbw / (2 * g[3] * g[4])),
    ]
    assert jbar == pytest.approx(expect, rel=1e-12)


def test_inverter_table_input_guards():
    with pytest.raises(ValueError):
        ski.inverter_table([1.0, 1.0], 0.1)  # len<3
    with pytest.raises(ValueError):
        ski.inverter_table(g_butter(3), 0.0)  # fbw 域
    with pytest.raises(ValueError):
        ski.inverter_table(g_butter(3), 1.5)
    with pytest.raises(ValueError):
        ski.inverter_table([1.0, -1.0, 1.0, 1.0], 0.1)  # g 非正
    with pytest.raises(ValueError):
        ski.inverter_table(g_butter(3), True)  # bool 拒收


# ─── 4. stub 网表构造 ────────────────────────────────────────────────────────


def test_stub_filter_design_impedances_and_lengths():
    g = g_butter(5)
    net = ski.stub_filter_design(g, 0.05, F0, Z0)
    # 全部 stub 阻抗 = Z0/2 逐位（b̄=(π/2)Y0 自洽口径）
    assert net.stub_impedances == [Z0 / 2.0] * 5
    # 连接线 = Z0/j̄ 逐位级
    for z_line, jbar in zip(net.line_impedances, net.inverter_values, strict=True):
        assert z_line == pytest.approx(Z0 / jbar, rel=1e-15)
    # 元件数：n stub + n+1 line；电长度恒 π/2
    assert len(net.stub_impedances) == 5 and len(net.line_impedances) == 6
    assert net.euler_pi2 == math.pi / 2
    d = net.to_dict()
    assert d["order"] == 5 and d["stub_impedances"][0] == Z0 / 2.0
    assert d["inverter_values"] == net.inverter_values


def test_stub_filter_design_guards():
    with pytest.raises(ValueError):
        ski.stub_filter_design(g_butter(1), 0.05, F0)  # n=1 口径不自洽，显式拒绝
    with pytest.raises(ValueError):
        ski.stub_filter_design(g_butter(3), 1.0, F0)
    with pytest.raises(ValueError):
        ski.stub_filter_design(g_butter(3), 0.1, 0.0)  # f0 非正
    with pytest.raises(ValueError):
        ski.stub_filter_design(g_butter(3), 0.1, F0, z0_ohm=-1.0)


# ─── 5. 频响验证面（预声明门：见文件头，近似源已声明）────────────────────────


def _band_metrics(net, n_order: int, fbw: float, response: str = "butter"):
    grid = np.linspace(F0 * (1 - 2 * fbw), F0 * (1 + 2 * fbw), 200001)
    _, s21 = ski.stub_filter_sparams(net, grid)
    lo, hi = ski.band_edges_3db(grid, s21)
    assert lo is not None and hi is not None
    sb = math.sqrt(fbw**2 / 4 + 1)
    i_lo, i_hi = F0 * (sb - fbw / 2), F0 * (sb + fbw / 2)
    inner = np.abs((grid / F0 - F0 / grid) / fbw) <= 0.8
    ideal_db = 10 * np.log10(
        ideal_bandpass_gain_lin(grid[inner], F0, fbw, n_order, response) ** 2
    )
    sim_db = 10 * np.log10(np.abs(s21[inner]) ** 2)
    return {
        "bw_rel": (hi - lo) / (i_hi - i_lo) - 1.0,
        "edge_rel": (lo / i_lo - 1.0, hi / i_hi - 1.0),
        "inner_dev_db": float(np.max(np.abs(sim_db - ideal_db))),
        "center_db": float(10 * np.log10(np.abs(s21[len(grid) // 2]) ** 2)),
    }


def test_response_butter_bandwidth_gate():
    # 预声明门：−3dB 带宽 rel ≤5%（实测 −3.7%）、带边 ≤1%、中心匹配
    net = ski.stub_filter_design(g_butter(5), 0.05, F0, Z0)
    m = _band_metrics(net, 5, 0.05)
    assert m["bw_rel"] <= 0.05
    assert all(abs(e) <= 0.01 for e in m["edge_rel"])
    assert m["center_db"] >= -0.05


def test_response_butter_inner_band_deviation():
    # 预声明门：内带（|ω_lp|≤0.8）最大偏差 ≤0.3dB（实测 0.095dB）
    net = ski.stub_filter_design(g_butter(5), 0.05, F0, Z0)
    m = _band_metrics(net, 5, 0.05)
    assert m["inner_dev_db"] <= 0.3


def test_response_chebyshev_inner_band_deviation():
    # cheby 0.1dB N=3（g 经 lc_filter 独立供给）：对 cheby 理想原型内带 ≤0.3dB
    # （对照 butter 原型的 scratch 实测 0.046dB）
    net = ski.stub_filter_design(g_cheby3_01db(), 0.05, F0, Z0)
    m = _band_metrics(net, 3, 0.05, response="cheby1")
    assert m["inner_dev_db"] <= 0.3
    assert m["center_db"] >= -0.05


def test_response_narrowband_convergence_monotone():
    # 窄带近似自洽：FBW 缩小 → 带宽误差单调改善（近似源声明的物理证据）
    errs = []
    for fbw in (0.05, 0.02):
        net = ski.stub_filter_design(g_butter(5), fbw, F0, Z0)
        errs.append(abs(_band_metrics(net, 5, fbw)["bw_rel"]))
    assert errs[1] < errs[0]
    assert errs[1] <= 0.05  # 更小 FBW 必落门内


def test_band_edges_3db_helpers():
    # 无交越侧返回 None（不凑值），交越按功率线性插值精确复算
    freqs = np.linspace(0.0, 10.0, 1001)
    s21 = np.full_like(freqs, 0.3, dtype=complex)  # 全阻带（|S21|²=0.09）
    lo, hi = ski.band_edges_3db(freqs, s21)
    assert lo is None and hi is None
    s21 = np.where((freqs > 3.0) & (freqs < 7.0), 1.0 + 0j, 0.2 + 0j)
    # 幅值 1.0/0.2 → 功率 1.0/0.04；严格不等号 ⇒ f=3.00/7.00 点属阻带：
    # 上交越在 [3.00,3.01]、下交越在 [6.99,7.00]
    frac = (0.5 - 0.04) / (1.0 - 0.04)
    lo_expect = 3.00 + 0.01 * frac
    hi_expect = 6.99 + 0.01 * ((1.0 - 0.5) / (1.0 - 0.04))
    lo, hi = ski.band_edges_3db(freqs, s21)
    assert lo == pytest.approx(lo_expect, rel=1e-12)
    assert hi == pytest.approx(hi_expect, rel=1e-12)
