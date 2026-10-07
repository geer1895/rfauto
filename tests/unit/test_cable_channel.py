"""M-8 电缆-连接器通道组装：合成裁判（spec 判据全离线零仿真零硬件）。

判据出处（研究扩充 §M-8 判据原文）：
- 同轴闭式 RLGC→S 参数→通道报告与解析插损对照；
- 两段电缆+连接器组装 vs 整体 skrf 级联逐位（级联恒等式）。

独立裁判口径（#118：期望独立来源/合成回收，禁同源自证）：
- S21/S11 解析式 (1−Γ²)e^{−γl}/(1−Γ²e^{−2γl}) 与 Γ(1−e^{−2γl})/(1−Γ²e^{−2γl})
  是与模块 ABCD→a2s 转换**不同代数路径**的裁判；
- 组装裁判的期望值用测试侧手排 ABCD 矩阵乘 + 波级联式
  S21=2/(A+B/Z0+C·Z0+D) 独立转换；
- UT-085 半刚电缆 datasheet 尺寸锚（内导体 0.51mm/介质 1.68mm/PTFE εr≈2.07，
  50Ω 名义档）→ 闭式 Z_c 落 50Ω ±2%。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import skrf

from rfauto.core.cable_channel import (
    CableRLGC,
    assemble_channel,
    channel_report,
    coax_rlgc,
    extract_rlgc_from_network,
    line_gamma_z0,
    load_connector,
    rlgc_to_network,
)

#: UT-085 半刚电缆（datasheet 尺寸档：50Ω 名义）
_UT085 = dict(d_inner_m=0.51e-3, d_outer_m=1.68e-3, er=2.07,
              sigma_s_per_m=5.8e7, tan_d=2.1e-4)
_FREQ = np.linspace(1e9, 8e9, 8)
_ZREF = 50.0


def _analytic_line_sparams(
    gamma: np.ndarray, z0_char: np.ndarray, length_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """嵌入 Z_ref 系统的均匀线段解析 S 参数（独立代数路径，非 ABCD 转换）。

    S21 = (1−Γ²)e^{−θ}/(1−Γ²e^{−2θ})、S11 = Γ(1−e^{−2θ})/(1−Γ²e^{−2θ})，
    θ=γl、Γ=(Z_c−Z_ref)/(Z_c+Z_ref)（电报员方程波分解闭式）。
    """
    gamma = np.asarray(gamma)
    z0_char = np.asarray(z0_char)
    refl = (z0_char - _ZREF) / (z0_char + _ZREF)
    theta = gamma * length_m
    e = np.exp(-theta)
    e2 = np.exp(-2.0 * theta)
    denom = 1.0 - refl**2 * e2
    s21 = (1.0 - refl**2) * e / denom
    s11 = refl * (1.0 - e2) / denom
    return s11, s21


# ─── 同轴闭式 RLGC 与特性阻抗锚 ────────────────────────────────────────────


class TestCoaxClosedForm:
    def test_ut085_impedance_datasheet_anchor(self):
        """datasheet 尺寸锚：闭式无损 Z_c=60/√εr·ln(b/a) 落 50Ω 名义 ±2%。

        无损 Z_c=sqrt(L'/C') 才是纯实数——用闭式 L'/C' 重组零损耗剖面
        （有耗剖面 Z_c 带小虚部，不作阻抗锚）。
        """
        rl = coax_rlgc(_FREQ, **_UT085)
        lossless = CableRLGC(_FREQ, np.zeros(8), rl.l_h_per_m,
                             np.zeros(8), rl.c_f_per_m)
        _, z0_char = line_gamma_z0(lossless)
        assert np.all(np.abs(np.imag(z0_char)) < 1e-12)
        assert abs(float(np.real(z0_char[0])) - 50.0) / 50.0 < 0.02

    def test_rlgc_static_values_exact(self):
        """L'/C' 静态闭式逐位；R'、G' 闭式逐频对照（独立重算）。"""
        rl = coax_rlgc(_FREQ, **_UT085)
        b_over_a = math.log((1.68e-3 / 2.0) / (0.51e-3 / 2.0))
        l_expect = (4e-7 * math.pi) / (2.0 * math.pi) * b_over_a
        c_expect = 2.0 * math.pi * 8.8541878128e-12 * 2.07 / b_over_a
        assert np.allclose(rl.l_h_per_m, l_expect, rtol=1e-14)
        assert np.allclose(rl.c_f_per_m, c_expect, rtol=1e-14)
        omega = 2.0 * math.pi * _FREQ
        rs = np.sqrt(math.pi * _FREQ * (4e-7 * math.pi) / 5.8e7)
        r_expect = rs / (2.0 * math.pi) * (1.0 / 0.255e-3 + 1.0 / 0.84e-3)
        assert np.allclose(rl.r_ohm_per_m, r_expect, rtol=1e-14)
        assert np.allclose(rl.g_s_per_m, omega * c_expect * 2.1e-4, rtol=1e-14)

    def test_rlgc_skin_frequency_dependence(self):
        """趋肤电阻 √f 律：R(4f)/R(f)≈2（趋肤一阶项的物理指纹）。"""
        f2 = np.array([1e9, 4e9])
        rl = coax_rlgc(f2, **_UT085)
        assert rl.r_ohm_per_m[1] / rl.r_ohm_per_m[0] == pytest.approx(2.0, rel=1e-9)

    def test_input_validation(self):
        with pytest.raises(ValueError, match="严格递增"):
            coax_rlgc(np.array([2e9, 1e9]), **_UT085)
        with pytest.raises(ValueError, match="d_outer_m"):
            coax_rlgc(_FREQ, d_inner_m=2e-3, d_outer_m=1e-3, er=2.0,
                      sigma_s_per_m=5.8e7, tan_d=0.0)
        with pytest.raises(ValueError, match="sigma_s_per_m"):
            coax_rlgc(_FREQ, d_inner_m=0.5e-3, d_outer_m=1.7e-3, er=2.0,
                      sigma_s_per_m=-1.0, tan_d=0.0)
        with pytest.raises(ValueError, match="d_inner_m"):
            coax_rlgc(_FREQ, d_inner_m=True, d_outer_m=1.7e-3, er=2.0,
                      sigma_s_per_m=5.8e7, tan_d=0.0)
        with pytest.raises(ValueError, match="全为正"):
            CableRLGC(_FREQ, np.zeros(8), np.zeros(8), np.zeros(8), np.zeros(8))


# ─── 判据①：闭式 RLGC→S 参数 vs 独立解析式 ────────────────────────────────


class TestClosedFormVsAnalytic:
    def test_sparams_match_independent_analytic(self):
        rl = coax_rlgc(_FREQ, **_UT085)
        gamma, z0_char = line_gamma_z0(rl)
        net = rlgc_to_network(rl, 0.01)
        s11, s21 = _analytic_line_sparams(gamma, z0_char, 0.01)
        assert np.allclose(net.s[:, 1, 0], s21, rtol=1e-10, atol=1e-14)
        assert np.allclose(net.s[:, 0, 0], s11, rtol=1e-10, atol=1e-14)

    def test_lossless_matched_limit(self):
        """无损+匹配极限：|S21|=1 逐位、S11=0 逐位（50Ω 系统 Z_c=50）。"""
        rl = CableRLGC(
            freq_hz=_FREQ,
            r_ohm_per_m=np.zeros(8), l_h_per_m=np.full(8, 250e-9),
            g_s_per_m=np.zeros(8), c_f_per_m=np.full(8, 100e-12))
        # Z_c = sqrt(L/C) = 50Ω 精确
        net = rlgc_to_network(rl, 0.05)
        assert np.allclose(np.abs(net.s[:, 1, 0]), 1.0, atol=1e-12)
        assert np.allclose(np.abs(net.s[:, 0, 0]), 0.0, atol=1e-12)
        # 相位 = −βl：β = ω√(LC)（复数指数比较，免 angle 卷绕歧义）
        beta = 2.0 * math.pi * _FREQ * math.sqrt(250e-9 * 100e-12)
        assert np.allclose(net.s[:, 1, 0], np.exp(-1j * beta * 0.05), atol=1e-10)


# ─── 判据②：级联恒等式（组装 vs 手排 ABCD）────────────────────────────────


def _abcd_of(net: skrf.Network) -> np.ndarray:
    return skrf.network.s2a(np.asarray(net.s), z0=net.z0[:, 0])


class TestCascadeIdentity:
    def test_assemble_equals_manual_abcd_composition(self):
        """电缆+连接器+电缆组装 vs 测试侧手排 ABCD 矩阵乘 + 波级联式转换。"""
        rl = coax_rlgc(_FREQ, **_UT085)
        cable = rlgc_to_network(rl, 0.005)
        # 合成连接器：串联 0.3+j0.5Ω（ABCD 串联阻抗段）
        z_conn = 0.3 + 0.5j
        abcd_conn = np.zeros((8, 2, 2), dtype=complex)
        abcd_conn[:, 0, 0] = 1.0
        abcd_conn[:, 0, 1] = z_conn
        abcd_conn[:, 1, 1] = 1.0
        conn = skrf.Network(frequency=skrf.Frequency.from_f(_FREQ, unit="Hz"),
                            s=skrf.network.a2s(abcd_conn, z0=_ZREF), z0=_ZREF)
        assembled = assemble_channel([cable, conn, cable])
        # 手排：ABCD_total = A_c·A_conn·A_c → S 独立转换
        a_c = _abcd_of(cable)
        total = a_c @ abcd_conn @ a_c
        den = total[:, 0, 0] + total[:, 0, 1] / _ZREF \
            + total[:, 1, 0] * _ZREF + total[:, 1, 1]
        s21_manual = 2.0 / den
        s11_manual = (total[:, 0, 0] + total[:, 0, 1] / _ZREF
                      - total[:, 1, 0] * _ZREF - total[:, 1, 1]) / den
        assert np.allclose(assembled.s[:, 1, 0], s21_manual, rtol=1e-10, atol=1e-14)
        assert np.allclose(assembled.s[:, 0, 0], s11_manual, rtol=1e-10, atol=1e-14)

    def test_uniform_line_halves_equal_full(self):
        """均匀线二分恒等式：两半长段级联 == 整段（γ/cosh/sinh 合成恒等）。"""
        rl = coax_rlgc(_FREQ, **_UT085)
        full = rlgc_to_network(rl, 0.01)
        halves = assemble_channel([rlgc_to_network(rl, 0.005),
                                   rlgc_to_network(rl, 0.005)])
        assert np.allclose(halves.s, full.s, rtol=1e-9)

    def test_assemble_equals_rshift_fold(self):
        rl = coax_rlgc(_FREQ, **_UT085)
        a = rlgc_to_network(rl, 0.004)
        b = rlgc_to_network(rl, 0.006)
        assert np.array_equal(assemble_channel([a, b]).s, (a >> b).s)

    def test_assemble_input_validation(self):
        rl = coax_rlgc(_FREQ, **_UT085)
        net = rlgc_to_network(rl, 0.005)
        with pytest.raises(ValueError, match="非空"):
            assemble_channel([])
        with pytest.raises(ValueError, match="2 端口"):
            one_port = skrf.Network(frequency=skrf.Frequency.from_f(_FREQ, unit="Hz"),
                                    s=np.zeros((8, 1, 1)), z0=_ZREF)
            assemble_channel([net, one_port])
        other_z = rlgc_to_network(rl, 0.005, z_ref_ohm=75.0)
        with pytest.raises(ValueError, match="z0 基"):
            assemble_channel([net, other_z])
        net_shift = rlgc_to_network(coax_rlgc(np.linspace(1e9, 8e9, 9), **_UT085), 0.005)
        with pytest.raises(ValueError, match="频率轴"):
            assemble_channel([net, net_shift])


# ─── 判据③：RLGC 反提取回收集 ─────────────────────────────────────────────


class TestRlgcExtraction:
    def test_roundtrip_recovers_rlgc(self):
        """network→extract→逐频 R/L/G/C 回收（arccosh 主值分支内，βl<π）。"""
        rl = coax_rlgc(_FREQ, **_UT085)
        length = 0.01
        net = rlgc_to_network(rl, length)
        back = extract_rlgc_from_network(net, length)
        assert np.allclose(back.r_ohm_per_m, rl.r_ohm_per_m, rtol=1e-9)
        assert np.allclose(back.l_h_per_m, rl.l_h_per_m, rtol=1e-9)
        assert np.allclose(back.g_s_per_m, rl.g_s_per_m, rtol=1e-6)
        assert np.allclose(back.c_f_per_m, rl.c_f_per_m, rtol=1e-9)
        # 重建网络与原网络逐位一致（回收→再正演闭环）
        net2 = rlgc_to_network(back, length)
        assert np.allclose(net2.s, net.s, rtol=1e-10, atol=1e-14)

    def test_extraction_branch_boundary_honest(self):
        """βl 越过 π 后相位混叠——显式相位窗守卫拒绝（P3-5 守卫路径）。

        混叠机制：arccosh 主值把 Im(γl) 卷绕回 (−π,π]，本档（UT-085、
        10mm、35-40GHz，βl≈10.5-12.1 rad）卷绕落负半窗 → 守卫
        ValueError（原实现靠 L<0 副作用触发，守卫升级后显式先行）。
        """
        f_hi = np.linspace(35e9, 40e9, 4)
        rl = coax_rlgc(f_hi, **_UT085)
        net = rlgc_to_network(rl, 0.01)
        with pytest.raises(ValueError, match="相位卷绕区"):
            extract_rlgc_from_network(net, 0.01)

    def test_extraction_aliasing_three_tiers_guard_path(self):
        """审查三档混叠（βl≈15.7/62.9/314.4 rad）全部走显式守卫（P3-5）。

        实测锚（单频 10GHz 探针）：三档卷绕相位 3.13/0.068/0.24 rad 全部
        折叠为**正但错**的 L（4.8e-8/2.6e-10/1.8e-10 vs 真值 2.38e-7）——
        原实现的 L<0 副作用在此形态下不触发（静默错值），显式因果性地板
        （提取 β < 0.9·ω/c0=超光速相速，TEM 无源介质不可能）全数拦截。
        """
        f = np.array([10e9])
        rl = coax_rlgc(f, **_UT085)
        gamma, _ = line_gamma_z0(rl)
        beta = float(np.imag(gamma)[0])  # 301.5 rad/m @10GHz
        for target_bl in (15.7, 62.9, 314.4):
            net = rlgc_to_network(rl, target_bl / beta)
            with pytest.raises(ValueError, match="相位卷绕区"):
                extract_rlgc_from_network(net, target_bl / beta)

    def test_extraction_phase_window_parameter(self):
        """声明窗参数：收紧窗提高灵敏度；>π 与非正值显式拒收。"""
        rl = coax_rlgc(_FREQ, **_UT085)
        net = rlgc_to_network(rl, 0.01)  # 合法档 βl<0.77π
        # 缺省窗 π：合法档照常回收
        back = extract_rlgc_from_network(net, 0.01)
        assert np.allclose(back.l_h_per_m, rl.l_h_per_m, rtol=1e-9)
        # 收紧到 0.5π：8GHz 端 βl≈0.77π 越窗 → 守卫拒绝（声明窗生效）
        with pytest.raises(ValueError, match="相位卷绕区"):
            extract_rlgc_from_network(net, 0.01, max_phase_rad=0.5 * math.pi)
        # >π 无意义（主值分支硬界）、非正、非有限 → 显式拒收
        with pytest.raises(ValueError, match="max_phase_rad"):
            extract_rlgc_from_network(net, 0.01, max_phase_rad=2.0 * math.pi)
        with pytest.raises(ValueError, match="max_phase_rad"):
            extract_rlgc_from_network(net, 0.01, max_phase_rad=0.0)
        with pytest.raises(ValueError, match="max_phase_rad"):
            extract_rlgc_from_network(net, 0.01, max_phase_rad=float("nan"))

    def test_extraction_input_validation(self):
        rl = coax_rlgc(_FREQ, **_UT085)
        net = rlgc_to_network(rl, 0.01)
        with pytest.raises(ValueError, match="2 端口"):
            one_port = skrf.Network(frequency=skrf.Frequency.from_f(_FREQ, unit="Hz"),
                                    s=np.zeros((8, 1, 1)), z0=_ZREF)
            extract_rlgc_from_network(one_port, 0.01)
        with pytest.raises(ValueError, match="length_m"):
            extract_rlgc_from_network(net, -1.0)

    def test_extraction_mixed_z0_raises(self):
        """两端口 z0 基不一致 → 显式 ValueError（P3-6：禁静默取首端口基）。

        报文须列出两个冲突 z0 值与来源端口（port0/port1）；一致基（含
        容差内微噪声）照常提取不误伤。
        """
        rl = coax_rlgc(_FREQ, **_UT085)
        net = rlgc_to_network(rl, 0.01)  # 一致基 50Ω
        mixed = net.copy()
        z0_mix = np.full((len(_FREQ), 2), 50.0)
        z0_mix[:, 1] = 75.0
        mixed.z0 = z0_mix
        with pytest.raises(ValueError, match="z0 基不一致") as exc_info:
            extract_rlgc_from_network(mixed, 0.01)
        msg = exc_info.value.args[0]
        assert "port0=50" in msg and "port1=75" in msg, msg
        # 容差内一致基（port1 加 1e-9 相对微噪声）不误伤：照常回收
        noisy = net.copy()
        z0_noisy = np.full((len(_FREQ), 2), 50.0)
        z0_noisy[:, 1] *= 1.0 + 1e-9
        noisy.z0 = z0_noisy
        back = extract_rlgc_from_network(noisy, 0.01)
        assert np.allclose(back.l_h_per_m, rl.l_h_per_m, rtol=1e-9)


# ─── 连接器段与通道报告 ────────────────────────────────────────────────────


class TestConnectorAndReport:
    def test_load_connector_roundtrip_and_z0(self, tmp_path):
        rl = coax_rlgc(_FREQ, **_UT085)
        seg = rlgc_to_network(rl, 0.002)
        p = tmp_path / "conn.s2p"
        seg.write_touchstone(str(p))
        loaded = load_connector(p)
        assert loaded.nports == 2
        assert np.allclose(loaded.s, seg.s, rtol=1e-12)
        assert np.allclose(np.asarray(loaded.z0), 50.0)

    def test_load_connector_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_connector(tmp_path / "nope.s2p")

    def test_channel_report_analytic_il(self):
        """通道报告插损与独立解析式对照（spec 判据「通道报告与解析插损」）。"""
        rl = coax_rlgc(_FREQ, **_UT085)
        net = rlgc_to_network(rl, 0.01)
        gamma, z0_char = line_gamma_z0(rl)
        _, s21 = _analytic_line_sparams(gamma, z0_char, 0.01)
        rep = channel_report(net)
        assert np.allclose(rep["il_db"], -20.0 * np.log10(np.abs(s21)), rtol=1e-10)
        assert rep["passive"] is True
        assert rep["n_points"] == 8
        assert rep["min_il_db"] == pytest.approx(float(np.min(rep["il_db"])))
        assert rep["f_min_hz"] == pytest.approx(1e9)
        assert rep["f_max_hz"] == pytest.approx(8e9)

    def test_channel_report_hl_over_one_meter_cable(self):
        """1m UT-085 @6GHz：解析插损量级合理性（趋肤+介质损耗 dB/m 档）。"""
        f = np.array([6e9])
        rl = coax_rlgc(f, **_UT085)
        net = rlgc_to_network(rl, 1.0)
        rep = channel_report(net)
        # 6GHz UT-085 手册插损 ~1.5-2.5 dB/m 档（datasheet 量级锚，宽门）
        assert 1.0 < rep["min_il_db"] < 4.0

    def test_report_input_validation(self):
        with pytest.raises(ValueError, match="2 端口"):
            one_port = skrf.Network(frequency=skrf.Frequency.from_f(_FREQ, unit="Hz"),
                                    s=np.zeros((8, 1, 1)), z0=_ZREF)
            channel_report(one_port)
