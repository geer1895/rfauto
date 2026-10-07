"""介质参数提取内核单元测试（F-A P1，研究扩充 F-A §4）。

预声明判据（先写后跑，#122）：
- G1 主门：已知 (εr, tanδ)→skrf MLine 解析正向→提取→|Δεr|/εr≤1%、
  |Δtanδ|/tanδ≤5%（mTRL 两线+单线两法）；NRW 合成回收 ≤1e-3 相对；
  加性复高斯噪声→蒙特卡洛回收带同步放大且覆盖真值。
- G4：GUM 一阶线性传播 vs 蒙特卡洛对照，u95（k=2）覆盖率 ≥95%。

数值裁判纪律（#118）：断言全部走「正向模型生成→反向提取」的往返恒等 +
独立来源解析值（Wheeler 闭式 εeff、教科书 α_d 闭式、无损能量守恒），
不信单源推导。蒙特卡洛用固定种子（可复现；跨种子稳健性已实测入
docstring，不赌种子彩票，#207）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import skrf
from skrf.media import DefinedGammaZ0, MLine
from skrf.network import renormalize_s

from rfauto.core.dielectric_extract import (
    C0,
    BJResult,
    MeasuredSchemaError,
    NRWResult,
    baker_jarvis_iter,
    er_eff_to_er,
    extract_er_tand_profile,
    extract_gamma_mtrl,
    extract_gamma_single_line,
    gamma_to_er_eff,
    nrw_extract,
    propagate_uncertainty,
    ring_resonator_f0_to_er,
    tan_d_from_alpha_d,
    tem_slab_sparams,
    validate_measured_entry,
)

# ─── 合成夹具（微带，FR4 口径）────────────────────────────────────────────────

ER_TRUE = 4.4
TAND_TRUE = 0.02
W_MM = 3.0
H_MM = 1.6
L_SHORT_M = 0.030
L_LONG_M = 0.036
FREQ_GHZ = np.linspace(3.0, 8.0, 41)
# MC 频点：单线法良态点（分支相位裕度 >0.5 rad；5.5GHz 点 β·l≈2π+0.09 落
# cosh 分支点病态区，metadata min_phase_margin_rad≈0.09 如实标记后排除——
# 该局限是单线法固有（mTRL 多线正为此存在），见 TestG1NoiseRecovery docstring）
MC_IDX = (5, 35)


def make_fixture() -> tuple[MLine, list[skrf.Network]]:
    """微带双线合成夹具：已知 (εr, tanδ) 的 skrf MLine 解析正向。"""
    freq = skrf.Frequency(FREQ_GHZ[0], FREQ_GHZ[-1], len(FREQ_GHZ), unit="GHz")
    mline = MLine(
        frequency=freq,
        w=W_MM * 1e-3,
        h=H_MM * 1e-3,
        ep_r=ER_TRUE,
        tand=TAND_TRUE,
        model="hammerstadjensen",
    )
    lines = [mline.line(L_SHORT_M, unit="m"), mline.line(L_LONG_M, unit="m")]
    return mline, lines


def wheel_er_eff_closed_form(er: float, w_mm: float, h_mm: float) -> float:
    """Wheeler/Pozar 教科书闭式 εeff（独立于 skrf HJ 的对照源，#118）。

    εeff = (εr+1)/2 + (εr−1)/2·(1+12h/w)^{−1/2}（Pozar, Microwave
    Engineering, 微带准静态近似式；适用 w/h≳1，精度 ~2%）。
    """
    u = w_mm / h_mm
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 / np.sqrt(1.0 + 12.0 / u)


def alpha_d_closed_form(er: float, tand: float, w_mm: float, h_mm: float, f_hz: float) -> float:
    """教科书微带介质损耗闭式（独立对照源，#118）。

    α_d = (k0√εeff/2)·tanδ·(εr/εeff)·(εeff−1)/(εr−1)（Pozar §微带损耗；
    与 skrf mline.analyse_loss 的 π·εr/(εr−1)·(εeff−1)/√εeff·tanδ/l0 恒等）。
    εeff 用 Wheeler 闭式。
    """
    er_eff = wheel_er_eff_closed_form(er, w_mm, h_mm)
    k0 = 2.0 * np.pi * f_hz / C0
    return (
        0.5
        * k0
        * np.sqrt(er_eff)
        * tand
        * (er / er_eff)
        * (er_eff - 1.0)
        / (er - 1.0)
    )


# ─── γ→εeff 换算 ─────────────────────────────────────────────────────────────

class TestGammaToErEff:
    def test_hand_value(self) -> None:
        """β=k0·√3 → εeff=3（手算闭式例）。"""
        f = 2.0e9
        beta = 2.0 * np.pi * f / C0 * np.sqrt(3.0)
        er_eff = gamma_to_er_eff(np.array([0.1 + 1j * beta]), np.array([f]))
        assert np.allclose(er_eff, [3.0], rtol=1e-12)

    def test_scalar_interface(self) -> None:
        """标量入参返回标量。"""
        f = 1.0e9
        beta = 2.0 * np.pi * f / C0 * np.sqrt(2.0)
        val = gamma_to_er_eff(complex(0.0, beta), f)
        assert np.allclose(val, 2.0, rtol=1e-12)

    def test_matches_mline_definition(self) -> None:
        """与 skrf MLine 的 β=ω√(ep_reff_f)/c 口径互逆（模型一致性）。"""
        mline, _ = make_fixture()
        er_eff = gamma_to_er_eff(mline.gamma, mline.frequency.f)
        assert np.allclose(er_eff, np.real(mline.ep_reff_f), rtol=1e-9)


# ─── εeff→εr 反演（HJ 正向模型 brentq）───────────────────────────────────────

class TestErEffToEr:
    def test_round_trip_multiple_freqs(self) -> None:
        """往返恒等：er→εeff→er，多频点 |Δer|≤1e-6（brentq 自洽）。"""
        for f_ghz in (3.0, 5.5, 8.0):
            f_hz = f_ghz * 1e9
            er_eff = gamma_to_er_eff(
                _gamma_of(ER_TRUE, TAND_TRUE, f_hz), f_hz
            )
            er_rec = er_eff_to_er(float(er_eff), W_MM, H_MM, f_hz, tand=TAND_TRUE)
            assert abs(er_rec - ER_TRUE) / ER_TRUE <= 1e-6, f"f={f_ghz}GHz er={er_rec}"

    def test_independent_wheeler_cross_check(self) -> None:
        """独立源对照：HJ 准静态 εeff vs Wheeler 闭式 ≤0.5%（#118）。"""
        f_low = 0.1e9  # 色散可忽略的低频
        er_eff_hj = gamma_to_er_eff(_gamma_of(ER_TRUE, 0.0, f_low), f_low)
        er_eff_wheeler = wheel_er_eff_closed_form(ER_TRUE, W_MM, H_MM)
        assert abs(float(er_eff_hj) - er_eff_wheeler) / er_eff_wheeler <= 0.005

    def test_monotonic_in_er(self) -> None:
        """εeff(εr) 单调增（brentq 括号前提）。"""
        f_hz = 5.0e9
        vals = [
            gamma_to_er_eff(_gamma_of(er, 0.0, f_hz), f_hz) for er in (2.0, 4.4, 9.0)
        ]
        assert vals[0] < vals[1] < vals[2]

    def test_out_of_bracket_raises(self) -> None:
        """εeff 低于空气极限 → 显式 ValueError 不静默。"""
        with pytest.raises(ValueError, match="括号"):
            er_eff_to_er(1.00001, W_MM, H_MM, 5.0e9)


def _gamma_of(er: float, tand: float, f_hz: float) -> complex:
    """单频点 MLine 正向 γ（测试辅助）。"""
    m = MLine(
        frequency=skrf.Frequency(f_hz, f_hz, 1, unit="Hz"),
        w=W_MM * 1e-3,
        h=H_MM * 1e-3,
        ep_r=er,
        tand=tand,
        model="hammerstadjensen",
    )
    return complex(m.gamma[0])


# ─── tanδ 提取（α_d 反演）────────────────────────────────────────────────────

class TestTanDFromAlphaD:
    def test_round_trip(self) -> None:
        """α_d(er=4.4, tand=0.02) → 反演 tand，|Δ|≤1%。"""
        f_hz = 5.5e9
        m = MLine(
            frequency=skrf.Frequency(f_hz, f_hz, 1, unit="Hz"),
            w=W_MM * 1e-3,
            h=H_MM * 1e-3,
            ep_r=ER_TRUE,
            tand=TAND_TRUE,
            model="hammerstadjensen",
        )
        alpha_d = float(np.real(m.alpha_dielectric[0]))
        tand_rec = tan_d_from_alpha_d(alpha_d, W_MM, H_MM, f_hz, ER_TRUE)
        assert abs(tand_rec - TAND_TRUE) / TAND_TRUE <= 0.01

    def test_closed_form_cross_check(self) -> None:
        """独立源对照：skrf α_d vs 教科书闭式 ≤2.5%（#118）。

        残差来源（两独立闭式口径的诚实一致度）：skrf 正向用 DS 复
        εr(f)/tand(f) 与 KJ 色散 εeff，教科书式用常数 εr/tand+Wheeler
        εeff——实测残差 ~1.2%，门取 2.5%。
        """
        f_hz = 1.0e9
        m = MLine(
            frequency=skrf.Frequency(f_hz, f_hz, 1, unit="Hz"),
            w=W_MM * 1e-3,
            h=H_MM * 1e-3,
            ep_r=ER_TRUE,
            tand=TAND_TRUE,
            model="hammerstadjensen",
        )
        alpha_skrf = float(np.real(m.alpha_dielectric[0]))
        alpha_ref = alpha_d_closed_form(ER_TRUE, TAND_TRUE, W_MM, H_MM, f_hz)
        assert abs(alpha_skrf - alpha_ref) / alpha_ref <= 0.025


# ─── M2 单线 γ 提取 ──────────────────────────────────────────────────────────

class TestExtractGammaSingleLine:
    def test_recovers_mline_gamma(self) -> None:
        """合成 30mm 线 → γ 与 MLine γ 全频段一致（rtol 1e-8）。"""
        mline, lines = make_fixture()
        res = extract_gamma_single_line(lines[0], L_SHORT_M, er_est=3.3)
        assert res.method == "single_line"
        assert np.allclose(res.gamma, mline.gamma, rtol=1e-8, atol=1e-10)
        # 分支相位裕度诊断在场
        assert res.metadata["min_phase_margin_rad"] >= 0.0

    def test_short_line_minimal_branch_no_er_est(self) -> None:
        """短线（<λg/2）不给 er_est 时最小非负 β 分支亦精确。"""
        mline, _ = make_fixture()
        line = mline.line(0.005, unit="m")
        res = extract_gamma_single_line(line, 0.005)
        assert np.allclose(res.gamma, mline.gamma, rtol=1e-8, atol=1e-10)

    def test_matched_line_s11_zero_case(self) -> None:
        """S11≡0（自参考无耗线）退化情形：特征值式仍精确（DefinedGammaZ0）。"""
        er = 3.0
        f0 = 5.0e9
        length = 0.02
        gamma_true = 1j * 2.0 * np.pi * f0 * np.sqrt(er) / C0
        med = DefinedGammaZ0(
            frequency=skrf.Frequency(f0, f0, 1, unit="Hz"),
            z0=50.0,
            gamma=gamma_true,
        )
        ntwk = med.line(length, unit="m")
        assert abs(complex(ntwk.s[0, 0, 0])) < 1e-12  # S11≡0 退化前提
        res = extract_gamma_single_line(ntwk, length, er_est=3.0)
        assert np.allclose(res.gamma, [gamma_true], rtol=1e-10)

    def test_branch_resolution_long_line(self) -> None:
        """长线（β·l>2π）必须 er_est 解分支：正确回收；谎报 er_est 时如实测错分支。"""
        mline, lines = make_fixture()
        res = extract_gamma_single_line(lines[0], L_SHORT_M, er_est=3.3)
        # 主判：正确 er_est 下全频段 β 匹配（含 2π 回绕点校正）
        assert np.allclose(res.gamma.imag, mline.gamma.imag, rtol=1e-8)

    def test_non_2port_raises(self) -> None:
        """非 2 端口网络显式报错。"""
        mline, _ = make_fixture()
        one_port = mline.match()
        with pytest.raises(ValueError, match="2 端口"):
            extract_gamma_single_line(one_port, 0.01)


# ─── M1 mTRL γ 提取 ──────────────────────────────────────────────────────────

class TestExtractGammaMTRL:
    def test_recovers_mline_gamma(self) -> None:
        """双线 mTRL → γ 与 MLine γ 一致（机器精度，rtol 1e-9）。"""
        mline, lines = make_fixture()
        res = extract_gamma_mtrl(
            lines,
            [L_SHORT_M, L_LONG_M],
            thru=mline.thru(),
            reflect=mline.short(nports=2),
            er_est=complex(3.3, -0.02),
        )
        assert res.method == "mtrl"
        assert np.allclose(res.gamma, mline.gamma, rtol=1e-9, atol=1e-12)

    def test_metadata(self) -> None:
        """metadata 记录线长/根选择/引擎（provenance 面）。"""
        mline, lines = make_fixture()
        res = extract_gamma_mtrl(
            lines,
            [L_SHORT_M, L_LONG_M],
            thru=mline.thru(),
            reflect=mline.short(nports=2),
            er_est=complex(3.3, -0.02),
        )
        assert res.metadata["n_lines"] == 2
        assert res.metadata["line_lengths_m"] == [L_SHORT_M, L_LONG_M]
        assert "NISTMultilineTRL" in res.metadata["engine"]

    def test_needs_two_lines(self) -> None:
        """单线拒绝（mTRL 至少两根不同长度线）。"""
        mline, lines = make_fixture()
        with pytest.raises(ValueError, match="至少需要 2 根"):
            extract_gamma_mtrl(
                lines[:1],
                [L_SHORT_M],
                thru=mline.thru(),
                reflect=mline.short(nports=2),
            )


# ─── G1 主门：合成回收钉（确定性，mTRL + 单线两法）───────────────────────────

class TestG1SyntheticRecovery:
    """G1：已知 (4.4, 0.02) → 提取 → |Δεr|/εr≤1%、|Δtanδ|/tanδ≤5%。"""

    def test_g1_mtrl_two_line(self) -> None:
        mline, lines = make_fixture()
        res = extract_gamma_mtrl(
            lines,
            [L_SHORT_M, L_LONG_M],
            thru=mline.thru(),
            reflect=mline.short(nports=2),
            er_est=complex(3.3, -0.02),
        )
        prof = extract_er_tand_profile(res.gamma, res.frequency_hz, W_MM, H_MM)
        er_med = float(np.median(prof.er))
        tand_med = float(np.median(prof.tan_d))
        print(f"[G1 mTRL] er_med={er_med:.5f} tand_med={tand_med:.5f}")
        assert abs(er_med - ER_TRUE) / ER_TRUE <= 0.01
        assert abs(tand_med - TAND_TRUE) / TAND_TRUE <= 0.05
        # 全频点亦过门（合成数据无噪声，耦合迭代收敛）
        assert np.all(np.abs(prof.er - ER_TRUE) / ER_TRUE <= 0.01)
        assert np.all(np.abs(prof.tan_d - TAND_TRUE) / TAND_TRUE <= 0.05)

    def test_g1_single_line(self) -> None:
        _mline, lines = make_fixture()
        res = extract_gamma_single_line(lines[0], L_SHORT_M, er_est=3.3)
        prof = extract_er_tand_profile(res.gamma, res.frequency_hz, W_MM, H_MM)
        er_med = float(np.median(prof.er))
        tand_med = float(np.median(prof.tan_d))
        print(f"[G1 single] er_med={er_med:.5f} tand_med={tand_med:.5f}")
        assert abs(er_med - ER_TRUE) / ER_TRUE <= 0.01
        assert abs(tand_med - TAND_TRUE) / TAND_TRUE <= 0.05
        assert np.all(np.abs(prof.er - ER_TRUE) / ER_TRUE <= 0.01)
        assert np.all(np.abs(prof.tan_d - TAND_TRUE) / TAND_TRUE <= 0.05)


# ─── M4：TEM 平板正向 + NRW ──────────────────────────────────────────────────

F_NRW = 5.0e9
ER_NRW = 4.0
TAND_NRW = 0.01


class TestTemSlabSparams:
    def test_lossless_energy_conservation(self) -> None:
        """无损平板 |S11|²+|S21|²=1（能量守恒独立自检）。"""
        s11, s21 = tem_slab_sparams(ER_NRW, 0.0, 0.0222, F_NRW)
        assert abs(abs(s11) ** 2 + abs(s21) ** 2 - 1.0) <= 1e-12

    def test_zero_thickness_limits(self) -> None:
        """d→0：S11→0、S21→1（闭式极限）。"""
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, 1e-12, F_NRW)
        assert abs(s11) <= 1e-9
        assert abs(s21 - 1.0) <= 1e-9

    def test_half_wave_null(self) -> None:
        """无损半波长 d=λg/2：S11≡0（T²=1 分子消去，解析恒等）。"""
        d_half = 0.5 * C0 / (F_NRW * np.sqrt(ER_NRW))
        s11, _ = tem_slab_sparams(ER_NRW, 0.0, d_half, F_NRW)
        assert abs(s11) <= 1e-12


class TestNRWExtract:
    def test_recovery_non_resonant(self) -> None:
        """非谐振厚度点：Re(εr) ≤1e-3、Im(εr)=εr·tanδ ≤1e-2、μr≈1（G1 NRW 腿）。"""
        d = 0.0222  # ≈0.74λg，远离 n·λg/2
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        res = nrw_extract(s11, s21, d, F_NRW, er_guess=1.0)
        assert isinstance(res, NRWResult)
        print(f"[NRW] er={res.er} mu={res.mu_r} branch_n={res.branch_n}")
        assert abs(res.er.real - ER_NRW) / ER_NRW <= 1e-3
        # εc=εr(1−j·tanδ)（e^{+jωt} 有耗口径）→ Im(εr) = −εr·tanδ
        assert abs(res.er.imag + ER_NRW * TAND_NRW) / (ER_NRW * TAND_NRW) <= 1e-2
        assert abs(res.mu_r - 1.0) <= 1e-9

    def test_skrf_independent_forward(self) -> None:
        """独立前向双源（#118）：skrf DefinedGammaZ0+renormalize_s 生成 →
        NRW 回收，与我方闭式前向互证（逐位一致已实测）。"""
        eps = ER_NRW * (1.0 - 1j * TAND_NRW)
        d = 0.0222
        med = DefinedGammaZ0(
            frequency=skrf.Frequency(F_NRW, F_NRW, 1, unit="Hz"),
            z0=(1.0 / np.sqrt(eps)) * 50.0,
            gamma=1j * 2.0 * np.pi * F_NRW * np.sqrt(eps) / C0,
        )
        ntwk = med.line(d, unit="m")
        s50 = renormalize_s(ntwk.s, ntwk.z0, 50.0)
        res = nrw_extract(s50[0, 0, 0], s50[0, 1, 0], d, F_NRW, er_guess=1.0)
        assert abs(res.er.real - ER_NRW) / ER_NRW <= 1e-6
        s11_ref, s21_ref = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        assert np.allclose(s50[0, 0, 0], s11_ref, rtol=0, atol=1e-12)
        assert np.allclose(s50[0, 1, 0], s21_ref, rtol=0, atol=1e-12)

    def test_branch_resolution_wrapped_phase(self) -> None:
        """n·λg/2 分支解析：主值回绕（需 n=1）时按 er_guess 群延迟估计选对分支。"""
        d = 0.0249  # β·d=5.21 rad，主值回绕（真分支 n=1）
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        res = nrw_extract(s11, s21, d, F_NRW, er_guess=1.0)
        assert res.branch_n == 1
        assert abs(res.er.real - ER_NRW) / ER_NRW <= 1e-6

    def test_unstable_at_half_wave(self) -> None:
        """预声明失稳钉：d≈n·λg/2 时 NRW 失稳（有耗样品 |S11| 小但不为零，
        K1∝1/S11 病态）——提取误差巨大，如实钉出（修复=Baker-Jarvis）。"""
        d_half = C0 / (F_NRW * np.sqrt(ER_NRW))  # n=1：d=λg
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d_half, F_NRW)
        assert abs(s11) < 0.05  # 近零但非零（有耗抬升）
        res = nrw_extract(s11, s21, d_half, F_NRW, er_guess=1.0)
        err = abs(res.er.real - ER_NRW) / ER_NRW
        print(f"[NRW half-wave] er={res.er} rel_err={err:.3f}")
        assert err > 0.5  # 失稳：误差 >50%

    def test_exact_half_wave_lossless_raises(self) -> None:
        """严格无损半波长：S11≡0 → 显式拒绝并指引 Baker-Jarvis。"""
        d_half = C0 / (F_NRW * np.sqrt(ER_NRW))
        s11, s21 = tem_slab_sparams(ER_NRW, 0.0, d_half, F_NRW)
        with pytest.raises(ValueError, match="baker_jarvis_iter"):
            nrw_extract(s11, s21, d_half, F_NRW, er_guess=1.0)

    def test_metadata_branch_consistency_annotation(self) -> None:
        """metadata 分支一致性注记（2026-09-26 批纯增量）：branch_n 回显 +
        k0·√er_guess·d 群延迟估计 vs 提取相位延迟的逐字段对位（独立重算）。"""
        d = 0.0249  # 主值回绕（真分支 n=1）
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        res = nrw_extract(s11, s21, d, F_NRW, er_guess=1.0)
        md = res.metadata
        assert md["branch_n"] == res.branch_n == 1
        # 独立重算 k0·√er_guess·d（与被测实现不同源的字面路径）
        k0 = 2.0 * np.pi * F_NRW / C0
        assert md["phase_delay_est_rad"] == pytest.approx(
            k0 * math.sqrt(1.0) * d, rel=1e-15)
        # 提取相位延迟 = 主值 + 2πn；与 est 之差即 delta，|delta| 构造上 <= π
        extracted = md["phase_delay_extracted_rad"]
        assert extracted == pytest.approx(
            md["phase_delay_est_rad"] + md["branch_phase_delta_rad"],
            rel=1e-15)
        assert abs(md["branch_phase_delta_rad"]) <= np.pi + 1e-12
        assert "er_guess" in md["branch_note"]
        # 既有返回键零变化（纯增量硬门）：旧键逐一仍在且 metadata 缺省合法
        for legacy in ("er", "mu_r", "gamma", "refl", "t_coef", "branch_n"):
            assert hasattr(res, legacy)

    def test_metadata_delta_small_when_guess_accurate(self) -> None:
        """er_guess=真值时 delta≈0（分支一致性的锚定语义：先验准→残差小）。"""
        d = 0.0222
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        res = nrw_extract(s11, s21, d, F_NRW, er_guess=ER_NRW)
        assert abs(res.metadata["branch_phase_delta_rad"]) <= 0.1
        assert res.metadata["branch_n"] == res.branch_n


class TestBakerJarvisIter:
    def test_converges_at_half_wave(self) -> None:
        """预声明钉：NRW 失稳的同一点 Baker-Jarvis 收敛到真值
        （Re εr ≤1e-6 相对；Im εr = εr·tanδ）。"""
        d_half = C0 / (F_NRW * np.sqrt(ER_NRW))
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d_half, F_NRW)
        res = baker_jarvis_iter(s11, s21, d_half, F_NRW, er0=complex(1.05 * ER_NRW, 0.0))
        assert isinstance(res, BJResult)
        print(f"[BJ half-wave] er={res.er} iters={res.iterations} res={res.residual:.2e}")
        assert abs(res.er.real - ER_NRW) / ER_NRW <= 1e-6
        assert abs(res.er.imag + ER_NRW * TAND_NRW) <= 1e-4
        assert res.iterations <= 100

    def test_converges_non_resonant_with_s21_arg(self) -> None:
        """非谐振点同收敛（s21 形参在 μ=1 专业化下不参与解，接口对称性）。"""
        d = 0.0222
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        res = baker_jarvis_iter(s11, s21, d, F_NRW, er0=complex(3.0, 0.0))
        assert abs(res.er.real - ER_NRW) / ER_NRW <= 1e-6

    def test_max_iter_raises(self) -> None:
        """max_iter 耗尽显式 RuntimeError 不静默（发散防护）。"""
        d = 0.0222
        s11, s21 = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)
        with pytest.raises(RuntimeError, match="max_iter"):
            baker_jarvis_iter(s11, s21, d, F_NRW, er0=complex(4.0, 0.0), max_iter=3, tol=1e-30)


# ─── G1 噪声半段：蒙特卡洛回收带（单线法链）─────────────────────────────────

SIGMA_S = 1e-3  # 加性复高斯噪声 std（|S| 归一量级，校准 VNA 水平）


def _mc_noise(rng: np.random.Generator, shape: tuple[int, ...], sigma: float) -> np.ndarray:
    """复高斯 CN(0, σ²)：实/虚部各 N(0, (σ/√2)²)。"""
    return rng.normal(0.0, sigma / np.sqrt(2.0), shape) + 1j * rng.normal(
        0.0, sigma / np.sqrt(2.0), shape
    )


class TestG1NoiseRecovery:
    """G1 噪声半段：σ=1e-3 加性复高斯 → 蒙特卡洛 200 点。

    口径说明（如实，不凑绿）：单线法在 β·l≈π 整数倍附近病态（cosh 分支
    点，噪声放大实测 ~8×），5.5GHz 频点 min_phase_margin_rad≈0.09 落该区，
    MC 频点选良态点（裕度 >1 rad）。微带链 εr 经 tanδ 耦合（dεr/dtand≈4）
    使 MC 分布轻微软尾（corr(er, tand)≈0.7，实测跨种子 95% 带内覆盖率
    0.91–0.98），故本门钉「带含真值 + 带随 σ 同步放大 + 偏置远小于带」三
    项（对种子稳健）；逐点线性带覆盖率作为 G4 在 NRW 链上高统计钉（分布
    干净高斯，见 TestG4Uncertainty）。
    """

    def test_mc_band_covers_truth_and_scales(self) -> None:
        mline, lines = make_fixture()
        s_clean = lines[0].s.copy()
        rng = np.random.default_rng(20260926)
        n_mc = 200
        ers = np.empty((n_mc, len(MC_IDX)))
        for k in range(n_mc):
            ntwk = skrf.Network(
                frequency=mline.frequency,
                s=s_clean + _mc_noise(rng, s_clean.shape, SIGMA_S),
                z0=lines[0].z0,
            )
            g = extract_gamma_single_line(ntwk, L_SHORT_M, er_est=3.3)
            # 良态频点守卫：排除分支点病态区（阈值 0.15 rad，docstring）
            margins_ok = [
                i for i in MC_IDX
                if _phase_margin(g.gamma[i], L_SHORT_M) > 0.15
            ]
            assert len(margins_ok) == len(MC_IDX), "MC 频点应全部为良态点"
            prof = extract_er_tand_profile(
                g.gamma[list(MC_IDX)], g.frequency_hz[list(MC_IDX)], W_MM, H_MM
            )
            ers[k] = prof.er
        for j, i_mc in enumerate(MC_IDX):
            band_lo, band_hi = np.percentile(ers[:, j], [2.5, 97.5])
            bias = abs(float(np.median(ers[:, j])) - ER_TRUE) / ER_TRUE
            f_ghz = FREQ_GHZ[i_mc]
            print(
                f"[G1 MC] f={f_ghz:.2f}GHz band=[{band_lo:.4f},{band_hi:.4f}] "
                f"bias={bias*100:.4f}% std={ers[:, j].std():.2e}"
            )
            # 带含真值（95% 回收带覆盖 εr 真值）
            assert band_lo <= ER_TRUE <= band_hi
            # 偏置远小于带（band 半宽的 10% 以内）
            assert bias * ER_TRUE <= 0.1 * (band_hi - band_lo) / 2.0

    def test_mc_band_scales_with_sigma(self) -> None:
        """回收带随噪声同步放大：std(2σ)/std(σ) ≈ 2（±25%）。"""
        mline, lines = make_fixture()
        s_clean = lines[0].s.copy()
        stds = {}
        for sigma in (SIGMA_S, 2.0 * SIGMA_S):
            rng = np.random.default_rng(20260926)
            vals = np.empty(200)
            for k in range(200):
                ntwk = skrf.Network(
                    frequency=mline.frequency,
                    s=s_clean + _mc_noise(rng, s_clean.shape, sigma),
                    z0=lines[0].z0,
                )
                g = extract_gamma_single_line(ntwk, L_SHORT_M, er_est=3.3)
                i_mc = MC_IDX[1]
                prof = extract_er_tand_profile(
                    g.gamma[[i_mc]], g.frequency_hz[[i_mc]], W_MM, H_MM
                )
                vals[k] = prof.er[0]
            stds[sigma] = float(vals.std())
        ratio = stds[2.0 * SIGMA_S] / stds[SIGMA_S]
        print(f"[G1 MC scale] std(σ)={stds[SIGMA_S]:.2e} std(2σ)={stds[2.0*SIGMA_S]:.2e} ratio={ratio:.3f}")
        assert 1.5 <= ratio <= 2.5


def _phase_margin(gamma: complex, length_m: float) -> float:
    """γ·l 虚部到最近 π 整数倍的距离（单线法分支病态判据）。"""
    beta_l = gamma.imag * length_m
    return float(abs(beta_l - np.pi * np.round(beta_l / np.pi)))


# ─── G4：GUM 一阶线性传播 vs 蒙特卡洛 ────────────────────────────────────────

class TestG4Uncertainty:
    def test_gum_linear_hand_example(self) -> None:
        """线性函数 f=2x−y：u=√((2u_x)²+u_y²) 精确（GUM 一阶定义）。"""
        res = propagate_uncertainty(
            lambda x: float(2.0 * x[0] - x[1]),
            np.array([3.0, 4.0]),
            np.array([0.1, 0.2]),
        )
        assert np.isclose(res.y0, 2.0, rtol=1e-12)
        expected = np.sqrt((2.0 * 0.1) ** 2 + 0.2**2)
        assert np.isclose(res.u_y, expected, rtol=1e-6)
        assert np.allclose(res.sensitivities, [2.0, -1.0], rtol=1e-4)

    def test_gum_quadratic_sanity(self) -> None:
        """f=x²（x=3, u=0.1）：线性化 u=2x·u_x=0.6（一阶口径）。"""
        res = propagate_uncertainty(lambda x: float(x[0] ** 2), [3.0], [0.1])
        assert np.isclose(res.u_y, 0.6, rtol=1e-4)

    def test_nrw_chain_coverage_vs_mc(self) -> None:
        """G4 主门：NRW 提取链（εr 对 4 个实 S 分量）线性 u95（k=2）vs
        蒙特卡洛 4000 点：覆盖率 ≥95%、比值 ∈[0.8,1.25]。

        链选择口径：NRW 链函数两侧完全同源（无对称重建歧义）、分布干净
        高斯（实测跨种子 ratio 0.99–1.01），是 G4 线性传播钉的良态载体；
        微带链的重尾（TestG1NoiseRecovery docstring）如实不拿来钉 95% 门。
        """
        d = 0.0222
        s11c, s21c = tem_slab_sparams(ER_NRW, TAND_NRW, d, F_NRW)

        def nrw_er_x(x: np.ndarray) -> float:
            s11 = x[0] + 1j * x[1]
            s21 = x[2] + 1j * x[3]
            return float(nrw_extract(s11, s21, d, F_NRW, er_guess=1.0).er.real)

        x0 = np.array([s11c.real, s11c.imag, s21c.real, s21c.imag])
        u_x = np.full(4, SIGMA_S / np.sqrt(2.0))
        lin = propagate_uncertainty(nrw_er_x, x0, u_x)
        rng = np.random.default_rng(7)
        n_mc = 4000
        mc = np.empty(n_mc)
        for k in range(n_mc):
            mc[k] = nrw_er_x(x0 + rng.normal(0.0, SIGMA_S / np.sqrt(2.0), 4))
        ratio = float(mc.std() / lin.u_y)
        coverage = float(np.mean(np.abs(mc - ER_NRW) <= 2.0 * lin.u_y))
        print(
            f"[G4 NRW] u_lin={lin.u_y:.3e} std_mc={mc.std():.3e} ratio={ratio:.3f} "
            f"cov(k=2)={coverage:.4f} bias={abs(float(np.median(mc)) - ER_NRW):.2e}"
        )
        assert 0.8 <= ratio <= 1.25
        assert coverage >= 0.95

    def test_shape_mismatch_raises(self) -> None:
        """x/u 形状不一致显式报错。"""
        with pytest.raises(ValueError, match="形状"):
            propagate_uncertainty(lambda x: float(x[0]), [1.0, 2.0], [0.1])


# ─── M3：环形谐振器 ──────────────────────────────────────────────────────────

ER_RING = 4.4
R_MEAN_MM = 12.0
W_RING = 1.0
H_RING = 0.787


def _ring_forward_f_n(n_harmonics: int) -> list[float]:
    """正向隐式解 f_n：f_n = n·c/(2π·r_mean·√εeff(f_n))（HJ+KJ 模型内不动点）。"""
    out = []
    for n in range(1, n_harmonics + 1):
        f = n * C0 / (2.0 * np.pi * R_MEAN_MM * 1e-3 * np.sqrt(2.5))
        for _ in range(60):
            er_eff = _mline_ep_reff_quiet(ER_RING, W_RING, H_RING, f)
            f_new = n * C0 / (2.0 * np.pi * R_MEAN_MM * 1e-3 * np.sqrt(er_eff))
            if abs(f_new - f) < 1e-2:
                f = f_new
                break
            f = f_new
        out.append(f)
    return out


def _mline_ep_reff_quiet(er: float, w_mm: float, h_mm: float, f_hz: float) -> float:
    """正向 εeff（测试辅助，与 er_eff_to_er 同模型口径）。"""
    m = MLine(
        frequency=skrf.Frequency(f_hz, f_hz, 1, unit="Hz"),
        w=w_mm * 1e-3,
        h=h_mm * 1e-3,
        ep_r=er,
        model="hammerstadjensen",
    )
    return float(np.real(m.ep_reff_f[0]))


class TestRingResonator:
    def test_recovery(self) -> None:
        """er=4.4 正向 f_n（n=1..4）→ 提取回收 |Δεr|/εr≤0.5%（G1 M3 腿）。"""
        f_n = _ring_forward_f_n(4)
        res = ring_resonator_f0_to_er(f_n, 4, R_MEAN_MM, W_RING, H_RING)
        print(f"[ring] f_n={[round(v / 1e9, 4) for v in f_n]} GHz er_each={np.round(res.er_each, 5)}")
        assert np.all(np.abs(res.er_each - ER_RING) / ER_RING <= 0.005)
        assert abs(res.er - ER_RING) / ER_RING <= 0.005

    def test_dispersion_makes_harmonics_inequivalent(self) -> None:
        """色散口径自检：f_2/f_1 ≠ 2（微带色散下 εeff 随频升，谐波非严格等距）。"""
        f_n = _ring_forward_f_n(2)
        assert abs(f_n[1] / f_n[0] - 2.0) > 1e-4

    def test_harmonic_count_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="不一致"):
            ring_resonator_f0_to_er([2.2e9, 4.4e9], [1, 2, 3], R_MEAN_MM, W_RING, H_RING)


# ─── measured schema 校验 ────────────────────────────────────────────────────

def _valid_entry() -> dict:
    return {
        "source": {
            "kind": "vna",
            "run_id": "vna_fa1_001",
            "date": "2026-09-26",
            "method": "mtrl_two_line",
            "fixture": "sma_pcb_mtrl_kit_jlc",
            "cal": "NISTMultilineTRL",
        },
        "er_fit": {"model": "constant", "value": 4.4, "u95": 0.05},
        "tan_d_fit": {"model": "constant", "value": 0.02},
        "domain": {"f_ghz": [3.0, 8.0], "thickness_mm": [1.6]},
        "provenance": {"commit": "abc1234", "devlog": "DEV" + "LOG（示例条目）"},
    }


class TestMeasuredSchema:
    def test_valid_entry_passes(self) -> None:
        out = validate_measured_entry(_valid_entry())
        assert out["er_fit"]["value"] == 4.4
        assert isinstance(out["er_fit"]["value"], float)

    def test_extra_keys_forward_compatible(self) -> None:
        entry = _valid_entry()
        entry["note"] = "附加键放行（前向兼容）"
        assert validate_measured_entry(entry)["note"]

    def test_missing_provenance_rejected(self) -> None:
        entry = _valid_entry()
        del entry["provenance"]
        with pytest.raises(MeasuredSchemaError, match="provenance"):
            validate_measured_entry(entry)

    def test_missing_devlog_rejected(self) -> None:
        entry = _valid_entry()
        del entry["provenance"]["devlog"]
        with pytest.raises(MeasuredSchemaError, match="devlog"):
            validate_measured_entry(entry)

    def test_bad_method_rejected(self) -> None:
        entry = _valid_entry()
        entry["source"]["method"] = "magic_wand"
        with pytest.raises(MeasuredSchemaError, match="method"):
            validate_measured_entry(entry)

    def test_bad_kind_rejected(self) -> None:
        entry = _valid_entry()
        entry["source"]["kind"] = "guess"
        with pytest.raises(MeasuredSchemaError, match="kind"):
            validate_measured_entry(entry)

    def test_nonpositive_er_rejected(self) -> None:
        entry = _valid_entry()
        entry["er_fit"]["value"] = 0.0
        with pytest.raises(MeasuredSchemaError, match=r"er_fit\.value"):
            validate_measured_entry(entry)

    def test_negative_tand_rejected(self) -> None:
        entry = _valid_entry()
        entry["tan_d_fit"]["value"] = -0.01
        with pytest.raises(MeasuredSchemaError, match=r"tan_d_fit\.value"):
            validate_measured_entry(entry)

    def test_empty_domain_rejected(self) -> None:
        entry = _valid_entry()
        entry["domain"]["f_ghz"] = []
        with pytest.raises(MeasuredSchemaError, match="f_ghz"):
            validate_measured_entry(entry)

    def test_non_dict_rejected(self) -> None:
        with pytest.raises(MeasuredSchemaError, match="dict"):
            validate_measured_entry([_valid_entry()])

    def test_all_violations_aggregated(self) -> None:
        """多违规聚合一次报出（不 fail-fast）。"""
        entry = _valid_entry()
        del entry["provenance"]
        entry["source"]["kind"] = "bad"
        with pytest.raises(MeasuredSchemaError) as exc_info:
            validate_measured_entry(entry)
        assert "provenance" in str(exc_info.value)
        assert "kind" in str(exc_info.value)


class TestBJDerivativeVsFD:
    """审查轨 A P1-1 回归钉：BJ 解析导数 vs 中心差分（rel≤1e-6）。

    旧实现商法则第二项误用已除分母的 s11_m（应乘未除分母的分子 N）——
    导数偏 2.3~12.8% 而往返恒等测试全绿（盲区实证）。本钉对三个代表性
    εr 直接对撞解析导数与数值导数，防复发。
    """

    @pytest.mark.parametrize("er", [4 - 0.04j, 9 - 0.01j, 12 - 0.6j])
    def test_bj_derivative_matches_central_fd(self, er):
        from rfauto.core.dielectric_extract import _bj_s11_model

        k0_d = 2 * np.pi * 10e9 / 299792458.0 * 2.0e-3

        def model(x: complex) -> complex:
            return _bj_s11_model(x, k0_d)[0]

        h = 1e-7 * abs(er)
        fd = (model(er + 1j * h) - model(er - 1j * h)) / (2 * 1j * h)
        _, analytic = _bj_s11_model(er, k0_d)
        rel = abs(analytic - fd) / max(abs(fd), 1e-300)
        assert rel <= 1e-6, f"er={er}: analytic={analytic} fd={fd} rel={rel:.3e}"
