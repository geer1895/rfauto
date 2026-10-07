"""PK-6 wirebond 寄生内核测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/wirebond.py 模块 docstring 文献核实账）：

- Rosa 直丝（已核，Wikipedia/Rosa 1908 逐位）：① 10 m/1.024 mm 数值例锚
  19.6458 μH（页面例值 19.67 μH 差 0.12%——页面线径舍入口径未注明，差异
  如实入档不吸收）；② DC−AC 恒等式 L_DC−L_AC=μ0l/(8π)（构造恒等逐位）；
  ③ 与 package_interconnect.rosa_wire_self_inductance_h 逐位互证。
- 地平面镜像：① 细线极限 2×spec/TEM_exact→1（h/r=1e6，恒等）；② 镜像
  守卫 h≤r 拒绝。
- 弧形内核（独立数值）：① θ→0 直丝退化恒等（0 误差）；② n_chords 倍增
  收敛钉（16/32/64，≤1e-4）；③ 弯折正超额（弧 ≥ 等长直丝，物理向）；
  ④ 共线端接互感精确式合成回收（a=b→(μ0a/2π)ln2）+ 与 Rosa 融合口径
  比值=2.000（Rosa 端效应常数，登记性钉死防静默漂移）。
- 趋肤 AC 电阻：① 双区间 regime 判类；② skin_perimeter 区 R′=Rs/(2πr)
  与 conductor_loss 禁改消费互证；③ DC 区几何精确 ρ/(πr²)。
- 多线并联：① n=2 Z 矩阵对称约化构造恒等（L+M)/2；② M=0 → L/n；
  ③ M>L 守卫。
- π 模型：① 双独立数值路径（ABCD 级联 vs 节点导纳矩阵）≤1e-10；
  ② SPICE 文本结构校验（subckt/ends/RLC 元素/唯一名）；③ 文本数值与
  模型 dict 互证；④ 子电路名守卫。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.package_interconnect import rosa_wire_self_inductance_h
from rfauto.core.wirebond import (
    arc_wire_l_h,
    bondwire_ac_resistance_per_length,
    bondwire_pi_model,
    collinear_end_to_end_mutual_h,
    lamp_cord_example_10m_awg18,
    parallel_bondwires_l_eff_h,
    pi_network_z_matrix,
    pi_network_z_matrix_nodal,
    straight_wire_l_ac_h,
    straight_wire_l_dc_h,
    validate_pi_subckt,
    wire_over_ground_l_partial_h,
    wire_over_ground_loop_l_exact_h,
    write_pi_subckt_spice,
)

_MU0 = 4.0e-7 * math.pi


# ─── Rosa 直丝（已核面）──────────────────────────────────────────────────────


def test_rosa_lamp_cord_numeric_anchor() -> None:
    # Wikipedia 逐位例：10 m、线径 1.024 mm → 约 19.67 μH；本式给 19.6458
    # （0.12% 差=页面线径舍入口径未注明，如实登记不吸收）
    val = lamp_cord_example_10m_awg18()
    assert val == pytest.approx(19.6458e-6, rel=1e-4)
    assert val == pytest.approx(19.67e-6, rel=0.002)  # 0.12% 带内


def test_rosa_dc_ac_identity_and_crosscheck() -> None:
    length, radius = 3.0e-3, 12.5e-6
    l_dc = straight_wire_l_dc_h(length, radius)
    l_ac = straight_wire_l_ac_h(length, radius)
    # DC−AC = μ0·l/(8π)（均匀内感构造恒等，逐位）
    assert l_dc - l_ac == pytest.approx(_MU0 * length / (8.0 * math.pi), rel=1e-15)
    # 与 PK-7 rosa 实现逐位互证（两处独立录入不漂移）
    assert l_dc == pytest.approx(rosa_wire_self_inductance_h(length, radius), rel=1e-15)
    with pytest.raises(ValueError):
        straight_wire_l_dc_h(1.0e-6, 1.0e-6)  # l/r<2 守卫


# ─── 地平面镜像 ──────────────────────────────────────────────────────────────


def test_wire_over_ground_thin_wire_limit_identity() -> None:
    length, radius = 2.0e-3, 12.5e-6
    partial = wire_over_ground_l_partial_h(length, 1.0, radius)  # h/r=8e4
    exact = wire_over_ground_loop_l_exact_h(length, 1.0, radius)
    assert 2.0 * partial / exact == pytest.approx(1.0, abs=1e-9)
    with pytest.raises(ValueError):
        wire_over_ground_l_partial_h(length, radius, radius)  # h≤r 守卫


# ─── 弧形内核（独立数值）─────────────────────────────────────────────────────


def test_arc_small_angle_straight_limit_identity() -> None:
    arc = arc_wire_l_h(1.0e-3, 0.05, 5.0e-6, n_chords=2)
    straight = straight_wire_l_ac_h(1.0e-3 * 0.05, 5.0e-6)
    assert arc["l_h"] == pytest.approx(straight, rel=1e-12)
    assert arc["curvature_excess_rel"] == pytest.approx(0.0, abs=1e-12)


def test_arc_convergence_and_curvature_excess() -> None:
    vals = [arc_wire_l_h(1.0e-3, math.pi / 2, 5.0e-6, n_chords=n)["l_h"]
            for n in (16, 32, 64)]
    assert abs(vals[1] / vals[0] - 1.0) < 1e-4
    assert abs(vals[2] / vals[1] - 1.0) < 5e-5
    # 弯折正超额：弧 ≥ 等长直丝（quarter arc ~0.3%）
    straight = straight_wire_l_ac_h(1.0e-3 * math.pi / 2, 5.0e-6)
    assert vals[1] > straight
    assert vals[1] / straight - 1.0 == pytest.approx(0.0032, abs=1e-3)
    with pytest.raises(ValueError):
        arc_wire_l_h(1.0e-3, 3.0 * math.pi, 5.0e-6)  # θ>2π 守卫


def test_collinear_mutual_exact_and_rosa_divergence_registered() -> None:
    b = 100.0e-6
    m_exact = collinear_end_to_end_mutual_h(b, b)
    # 合成回收：a=b → (μ0/4π)·2b·ln2（本会话从 Neumann 积分直接推导）
    assert m_exact == pytest.approx(_MU0 / (4.0 * math.pi) * 2 * b * math.log(2.0),
                                    rel=1e-15)
    # Rosa 融合口径 / 纯 Neumann 精确式 = 2.000（端效应常数差，登记性钉死）
    m_fused = straight_wire_l_ac_h(2 * b, 5.0e-6) - 2 * straight_wire_l_ac_h(b, 5.0e-6)
    assert m_fused / m_exact == pytest.approx(2.0, rel=1e-9)


# ─── 趋肤 AC 电阻 ────────────────────────────────────────────────────────────


def test_bondwire_ac_resistance_regimes() -> None:
    rho = 1.68e-8
    # DC 型：低频厚丝（δ ≫ r）
    low = bondwire_ac_resistance_per_length(1.0e3, 12.5e-6, rho)
    assert low["regime"] == "uniform_dc_like"
    assert low["r_ohm_per_m"] == pytest.approx(rho / (math.pi * 12.5e-6**2), rel=1e-12)
    # 趋肤型：1 GHz 铜 δ≈2.1 µm ≪ r=62.5 µm（5 mil 直径键合线）
    high = bondwire_ac_resistance_per_length(1.0e9, 62.5e-6, rho)
    assert high["regime"] == "skin_perimeter"
    assert high["r_ohm_per_m"] == pytest.approx(
        high["rs_ohm_per_sq"] / (2.0 * math.pi * 62.5e-6), rel=1e-12)
    # 同几何跨 regime：趋肤后 AC R 高于 DC R（同 r=62.5 µm）
    dc_same = bondwire_ac_resistance_per_length(1.0e3, 62.5e-6, rho)
    assert dc_same["regime"] == "uniform_dc_like"
    assert high["r_ohm_per_m"] > dc_same["r_ohm_per_m"]


# ─── 多线并联 ────────────────────────────────────────────────────────────────


def test_parallel_bondwires_identity_and_guards() -> None:
    l_single, mutual = 1.0e-9, 0.4e-9
    # n=2：Z 矩阵对称约化（I1=I2=I/2）→ (L+M)/2 构造恒等
    assert parallel_bondwires_l_eff_h(l_single, mutual, 2) == pytest.approx(
        0.5 * (l_single + mutual), rel=1e-15)
    assert parallel_bondwires_l_eff_h(l_single, mutual, 3) == pytest.approx(
        (l_single + 2 * mutual) / 3, rel=1e-15)
    # M=0 → L/n
    assert parallel_bondwires_l_eff_h(l_single, 0.0, 4) == pytest.approx(
        l_single / 4, rel=1e-15)
    with pytest.raises(ValueError):
        parallel_bondwires_l_eff_h(l_single, 2.0 * l_single, 2)  # M>L 守卫
    with pytest.raises(ValueError):
        parallel_bondwires_l_eff_h(l_single, mutual, 0)


# ─── π 模型 ──────────────────────────────────────────────────────────────────

_PI_MODEL = bondwire_pi_model(2.0e-3, 12.5e-6, 1.0e9, 0.05e-12)
_PI_FREQS = np.array([1.0e8, 5.0e8, 1.0e9, 2.0e9])


def test_pi_model_two_independent_paths_agree() -> None:
    za = pi_network_z_matrix(_PI_MODEL, _PI_FREQS)["z"]
    zn = pi_network_z_matrix_nodal(_PI_MODEL, _PI_FREQS)["z"]
    rel = np.max(np.abs(za - zn) / np.abs(zn))
    assert float(rel) < 1e-10


def test_pi_model_port_limit_and_sources() -> None:
    # 端口极限（物理：低频下串联 L≈短路，两只并臂电容并联跨在端口上）：
    # |Z11| = |Z21| = 1/(2ωC)
    f0 = 1.0e8
    z = pi_network_z_matrix(_PI_MODEL, np.array([f0]))["z"][:, :, 0]
    omega = 2.0 * math.pi * f0
    z_cap = 1.0 / (2.0 * omega * _PI_MODEL["c_shunt_f"])
    assert abs(z[0, 0]) == pytest.approx(z_cap, rel=5e-3)
    assert abs(z[0, 1]) == pytest.approx(z_cap, rel=5e-3)
    assert z[0, 0].real > 0.0  # 无源性
    # 地平面源切换
    m_g = bondwire_pi_model(2.0e-3, 12.5e-6, 1.0e9, 0.05e-12,
                            ground_height_m=0.2e-3)
    assert m_g["l_source"] == "wire_over_ground_partial"
    assert m_g["l_h"] == pytest.approx(
        wire_over_ground_l_partial_h(2.0e-3, 0.2e-3, 12.5e-6), rel=1e-15)
    assert _PI_MODEL["l_source"] == "rosa_ac_free_space"


def test_pi_spice_text_structure_and_values() -> None:
    text = write_pi_subckt_spice(_PI_MODEL)
    info = validate_pi_subckt(text)
    assert info["valid"] is True, info["errors"]
    assert info["element_counts"] == {"C": 2, "L": 1, "R": 1}
    # 文本数值与模型 dict 互证（防写出口径漂移）
    for line in text.splitlines():
        tok = line.split()
        if tok and tok[0] == "LSR":
            assert float(tok[3]) == pytest.approx(_PI_MODEL["l_h"], rel=1e-9)
        if tok and tok[0] == "RSR":
            assert float(tok[3]) == pytest.approx(_PI_MODEL["r_ohm"], rel=1e-9)
    with pytest.raises(ValueError):
        write_pi_subckt_spice(_PI_MODEL, subckt_name="bad name")
    bad = text.replace(".ENDS", "")
    assert validate_pi_subckt(bad)["valid"] is False
