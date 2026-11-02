"""DR-7 core/pdn_tran.py 单测（规格 §C-5 验收锚，先写后跑 #122）。

锚面（规格原文逐条）：
① 梯形谱双路：解析包络（导数法闭式）vs FFT（rfft/N）一致 ≤1e-9（归一化
   ΔI；规格门，实测 N=2^18 时 ~2.3e-10）；
② 单谐振锚：单谐波 × 纯 R → V_pk-pk = 4|c₁|R 逐位（机器精度，采样峰恰在
   网格点）；梯形 × 并联 RLC：IFFT 波形 vs 谐波和闭式逐点 ≤1e-12、V_pk-pk
   网格真值互证 + SSO 上界（三角不等式严格上界）包住；
③ 正弦纹波 → Sφ 闭式：β = K_push·v/f_m、L = 10log10(β²/4)、σ_φ² = Σβ²/2
   逐位（clock_noise INTERP_CONST 段积分为解析闭式，收口等式）；
   K_push 缺失 → awaiting_data 不产数（规格风险条款）；
④ Xyce 对照面：render_tran_netlist PWL 断点同 schema（往返解析 ≤1e-15）+
   .tran/.print 结构钉；真机对照为 opt-in（RFAUTO_PDN_TRAN_XYCE_REAL=1，
   df4⑥ 真跑集成不进缺省 unit 门），不可达如实 skip 降级登记。
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.pdn import VrmModel
from rfauto.core.pdn_tran import (
    SMALL_ANGLE_BETA_MAX,
    SPUR_BIN_HALF_WIDTH_HZ,
    PushPhaseNoiseResult,
    TrapezoidCurrent,
    push_jitter,
    push_phase_noise,
    render_tran_netlist,
    ripple_response,
    trapezoid_harmonics,
    trapezoid_harmonics_fft,
    z_parallel_rlc,
)

TRAP = TrapezoidCurrent(i_min_a=1.0, i_pk_a=3.0, t_period_s=100e-9,
                        t_rise_s=1e-9, t_fall_s=2e-9)


# ─── schema ──────────────────────────────────────────────────────────────────


class TestSchema:
    def test_guards(self) -> None:
        with pytest.raises(ValueError, match="i_pk_a"):
            TrapezoidCurrent(3.0, 1.0, 100e-9, 1e-9, 2e-9)
        with pytest.raises(ValueError, match="t_rise_s"):
            TrapezoidCurrent(1.0, 3.0, 100e-9, 0.0, 2e-9)
        with pytest.raises(ValueError, match="t_rise\\+t_fall"):
            TrapezoidCurrent(1.0, 3.0, 100e-9, 60e-9, 40e-9)
        with pytest.raises(ValueError, match="有限"):
            TrapezoidCurrent(float("nan"), 3.0, 100e-9, 1e-9, 2e-9)

    def test_tau_top_and_amplitude(self) -> None:
        assert TRAP.amplitude_a == 2.0
        assert TRAP.tau_top_s == 97e-9

    def test_waveform_breakpoints_exact(self) -> None:
        t = [0.0, TRAP.t_rise_s, TRAP.t_rise_s + TRAP.tau_top_s,
             TRAP.t_period_s, TRAP.t_period_s + TRAP.t_rise_s]
        v = TRAP.waveform(t)
        assert v[0] == 1.0
        assert v[1] == 3.0
        assert v[2] == 3.0
        assert v[3] == 1.0  # t=T 周期回卷 → i_min
        assert v[4] == pytest.approx(3.0, rel=1e-12)  # t=T+t_r（mod 浮点回卷）

    def test_waveform_mid_rise_mid_fall(self) -> None:
        assert TRAP.waveform(0.5e-9) == pytest.approx(2.0)
        assert TRAP.waveform(99e-9) == pytest.approx(2.0)

    def test_dict_round_trip(self) -> None:
        d = TRAP.to_dict()
        assert set(d) == {"i_min_a", "i_pk_a", "t_period_s", "t_rise_s", "t_fall_s"}
        assert TrapezoidCurrent.from_dict(d) == TRAP


# ─── 锚 ①：解析包络 vs FFT 双路 ≤1e-9 ────────────────────────────────────────


class TestDualPathSpectrum:
    def test_analytic_vs_fft_below_1e_9(self) -> None:
        n_fft = 1 << 18
        an = trapezoid_harmonics(TRAP, 800)
        ff = trapezoid_harmonics_fft(TRAP, n_fft)
        assert an.method == "analytic" and ff.method == "fft"
        diff = np.abs(an.c[1:] - ff.c[1:801]).max()
        assert diff / TRAP.amplitude_a < 1e-9  # 规格门

    def test_dc_coefficient_closed_form(self) -> None:
        """c_0 = 周期平均 = i_min + ΔI·(t_r/2+τ+t_f/2)/T（闭式逐位）。"""
        an = trapezoid_harmonics(TRAP, 4)
        mean_closed = 1.0 + 2.0 * (0.5e-9 + 97e-9 + 1e-9) / 100e-9
        assert an.dc_a == mean_closed

    def test_asymptotic_1_over_n2_envelope(self) -> None:
        """梯形谱高频包络 ~1/n²（角点一阶导跳变口径，量级自洽钉）。

        参数刻意取非对齐（t_r/T=0.013、t_f/T=0.027 非整百）：对齐参数下
        f·t_r 与 f·t_f 成整数使 sinc 项逐零（|c_n| 陷为浮点噪声，比值无义）。
        """
        trap = TrapezoidCurrent(i_min_a=1.0, i_pk_a=3.0, t_period_s=100e-9,
                                t_rise_s=1.3e-9, t_fall_s=2.7e-9)
        an = trapezoid_harmonics(trap, 977)
        assert abs(an.c[933]) > 1e-9 and abs(an.c[466]) > 1e-9  # 非零陷（对齐病态守卫）
        # 窗均包络比（点值受三段干涉纹波调制，窗均才是平滑 1/n² 包络）
        hi = float(np.abs(an.c[900:978]).mean())
        lo = float(np.abs(an.c[400:479]).mean())
        assert 0.12 < hi / lo < 0.45  # ≈ (450/950)² = 0.224（实测 0.202）


# ─── 锚 ②：单谐振 RLC 解析纹波 ───────────────────────────────────────────────


class TestRippleResponse:
    def test_single_tone_pure_r_sampling_bracket(self) -> None:
        """单谐波 × 纯 R：v_pp = 4|c₁|R·[cos(π/N), 1] 采样括区（相位任意时
        采样峰 ≤ 真峰、且不低于 cos(π/N) 因子——离散采样语义逐位钉）。"""
        r_ohm = 2.0
        n_fft = 1 << 14
        res = ripple_response(
            TRAP, n_max=1, n_fft=n_fft,
            z_of_freq=lambda f: np.full(np.shape(f), r_ohm + 0.0j))
        closed = 4.0 * abs(trapezoid_harmonics(TRAP, 1).c[1]) * r_ohm
        assert res.v_pkpk_v <= closed * (1.0 + 1e-12)
        assert res.v_pkpk_v >= closed * math.cos(math.pi / n_fft) * (1.0 - 1e-12)
        assert res.sso_bound_pp_v >= res.v_pkpk_v

    def test_iff_waveform_matches_harmonic_sum_closed_form(self) -> None:
        """IFFT 波形 vs 谐波和闭式（同网格逐点 ≤1e-12·scale，规格"解析纹波"）。"""
        r_ohm, l_h, c_f = 0.5, 10e-9, 100e-9
        n_max = 200
        res = ripple_response(TRAP, n_max=n_max,
                              z_of_freq=lambda f: z_parallel_rlc(f, r_ohm, l_h, c_f),
                              n_fft=1 << 16)
        an = trapezoid_harmonics(TRAP, n_max)
        vn = an.c[1:] * z_parallel_rlc(an.f_hz[1:], r_ohm, l_h, c_f)
        phase = 2.0 * np.pi * np.outer(np.arange(1, n_max + 1), res.t_s) / TRAP.t_period_s
        v_sum = 2.0 * np.real(vn @ np.exp(1j * phase)).reshape(-1)
        scale = max(abs(v_sum).max(), 1e-30)
        assert np.abs(res.v_t - v_sum).max() < 1e-12 * scale
        # V_pk-pk 网格互证 + SSO 上界（三角不等式）包住
        assert res.v_pkpk_v == res.v_t.max() - res.v_t.min()
        assert res.v_pkpk_v <= res.sso_bound_pp_v
        # v_rms Parseval：Σ 2|v_n|²
        assert abs(res.v_rms_v - math.sqrt(float(np.sum(2.0 * np.abs(vn) ** 2)))) < 1e-15 * scale

    def test_fine_grid_pkpk_converges_upward(self) -> None:
        """采样峰 ≤ 真峰：n_fft 加密 V_pk-pk 单调不降（网格分辨率诚实口径）。"""
        kw = dict(n_max=100, z_of_freq=lambda f: z_parallel_rlc(f, 0.5, 10e-9, 100e-9))
        coarse = ripple_response(TRAP, n_fft=1 << 14, **kw)
        fine = ripple_response(TRAP, n_fft=1 << 17, **kw)
        assert fine.v_pkpk_v >= coarse.v_pkpk_v
        assert abs(fine.v_pkpk_v / coarse.v_pkpk_v - 1.0) < 0.01

    def test_z_from_pdn_profile_reuse(self) -> None:
        """复用 pdn.py:668 面（VRM+decap profile 路径）与手算导纳和一致。"""
        from rfauto.core.pdn import decap_impedance, vrm_model

        vrm = VrmModel(r0=1e-3, l0=1e-6, r1=1e-3, l1=1e-9)
        decaps = [(100e-6, 5e-3, 1e-9)]
        res = ripple_response(TRAP, n_max=8, vrm=vrm, decaps=decaps, n_fft=2048)
        f_h = np.arange(1, 9) / TRAP.t_period_s
        z_hand = 1.0 / (1.0 / vrm_model(f_h, vrm.r0, vrm.l0, vrm.r1, vrm.l1)
                        + 1.0 / decap_impedance(100e-6, 5e-3, 1e-9, 0.0, f_h))
        an = trapezoid_harmonics(TRAP, 8)
        v_closed = 2.0 * np.abs(an.c[1:] * z_hand)
        assert np.abs(res.v_amp_v - v_closed).max() < 1e-15

    def test_requires_load_network(self) -> None:
        with pytest.raises(ValueError, match="负载网络"):
            ripple_response(TRAP, n_max=4)

    def test_n_fft_too_small_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_fft"):
            ripple_response(TRAP, n_max=100, z_of_freq=lambda f: f * 0 + 1, n_fft=64)

    def test_dc_offset_shifts_level_not_pkpk(self) -> None:
        kw = dict(n_max=8, z_of_freq=lambda f: np.full(np.shape(f), 0.1 + 0j), n_fft=2048)
        plain = ripple_response(TRAP, **kw)
        biased = ripple_response(TRAP, v_dc_offset_v=1.2, **kw)
        assert abs(plain.v_pkpk_v - biased.v_pkpk_v) < 1e-15
        assert biased.v_t.max() > plain.v_t.max()  # 电位整体抬升


# ─── 锚 ③：正弦纹波 → Sφ 闭式 ────────────────────────────────────────────────


class TestPushPhaseNoise:
    K_PUSH = 1e5  # Hz/V
    V_RIP = 0.01  # V
    F_M = 1e6  # Hz

    def test_line_spectrum_closed_form(self) -> None:
        res = push_phase_noise([self.V_RIP], [self.F_M], self.K_PUSH)
        assert res.status == "ok"
        assert res.small_angle_ok
        beta = self.K_PUSH * self.V_RIP / self.F_M  # 1e-3 rad
        ln = res.lines[0]
        assert ln.beta_rad == beta  # 逐位
        assert ln.l_dbc_per_hz == 10.0 * math.log10(beta**2 / 4.0)  # 逐位闭式
        assert ln.s_phi_equiv_rad2_per_hz == beta**2 / 4.0

    def test_small_angle_flag_on_large_beta(self) -> None:
        res = push_phase_noise([1.0], [1e3], 1e4)  # β = 10 rad ≫ 0.5
        assert not res.small_angle_ok
        assert res.status == "ok"  # 照算，采信权在调用方（诚实边界③）

    def test_awaiting_data_no_numbers(self) -> None:
        res = push_phase_noise([self.V_RIP], [self.F_M], None)
        assert isinstance(res, PushPhaseNoiseResult)
        assert res.status == "awaiting_data"
        assert res.lines == ()  # 不产数（规格风险条款）
        assert res.as_dict()["lines"] == []

    def test_jitter_kernel_closed_form_and_clock_noise_consistency(self) -> None:
        """σ_φ² = Σβ²/2（rms 闭式）与 clock_noise INTERP_CONST 收口逐位一致。"""
        pj = push_jitter([self.V_RIP], [self.F_M], self.K_PUSH, f_carrier_hz=25e6)
        beta = self.K_PUSH * self.V_RIP / self.F_M
        assert pj.sigma_phi2_closed_rad2 == beta**2 / 2.0
        assert pj.phase_jitter is not None
        assert pj.phase_jitter.interp == "const"
        assert abs(pj.phase_jitter.sigma_phi2_rad2 / pj.sigma_phi2_closed_rad2 - 1.0) < 1e-15
        # 两正弦谐波叠加：闭式和 = 内核逐位
        f2 = 3.0 * self.F_M
        pj2 = push_jitter([self.V_RIP, self.V_RIP], [self.F_M, f2], self.K_PUSH,
                          f_carrier_hz=25e6)
        b1 = self.K_PUSH * self.V_RIP / self.F_M
        b2 = self.K_PUSH * self.V_RIP / f2
        assert pj2.sigma_phi2_closed_rad2 == (b1**2 + b2**2) / 2.0
        assert abs(pj2.phase_jitter.sigma_phi2_rad2 / pj2.sigma_phi2_closed_rad2 - 1.0) < 1e-15
        assert pj2.phase_jitter.jitter_s is not None
        assert pj2.phase_jitter.f_carrier_hz == 25e6

    def test_jitter_awaiting_data(self) -> None:
        pj = push_jitter([self.V_RIP], [self.F_M], None)
        assert pj.phase_jitter is None
        assert pj.sigma_phi2_closed_rad2 is None

    def test_jitter_bin_guards(self) -> None:
        with pytest.raises(ValueError, match="不得触及 f=0"):
            push_jitter([self.V_RIP], [0.4], self.K_PUSH)
        with pytest.raises(ValueError, match="禁重叠"):
            push_jitter([self.V_RIP, self.V_RIP], [1e6, 1e6 + 0.5], self.K_PUSH)
        assert SPUR_BIN_HALF_WIDTH_HZ == 0.5
        assert SMALL_ANGLE_BETA_MAX == 0.5

    def test_input_guards(self) -> None:
        with pytest.raises(ValueError, match="严格递增"):
            push_phase_noise([1.0, 1.0], [1e6, 1e6], self.K_PUSH)
        with pytest.raises(ValueError, match="正有限数"):
            push_phase_noise([0.0], [1e6], self.K_PUSH)
        with pytest.raises(ValueError, match="k_push_hz_per_v"):
            push_phase_noise([1.0], [1e6], 0.0)


# ─── 锚 ④：Xyce .TRAN 网表 schema 钉（纯文本面，不产数）──────────────────────


class TestXyceNetlistSchema:
    R, LH, CF, N_PER = 0.5, 10e-9, 100e-9, 5

    def _render(self) -> str:
        return render_tran_netlist(TRAP, r_ohm=self.R, l_henry=self.LH,
                                   c_farad=self.CF, n_periods=self.N_PER)

    def test_pwl_breakpoints_same_schema(self) -> None:
        text = self._render()
        m = re.search(r"I1 1 0 PWL\(([^)]*)\)", text)
        assert m is not None, "缺 I1 PWL 电流源"
        tokens = m.group(1).split()
        pts = [(float(tokens[i]), float(tokens[i + 1])) for i in range(0, len(tokens), 2)]
        # 断点数：每周期 4 点 + 末点
        assert len(pts) == 4 * self.N_PER + 1
        tau = TRAP.tau_top_s
        first = [(0.0, 1.0), (TRAP.t_rise_s, 3.0),
                 (TRAP.t_rise_s + tau, 3.0), (TRAP.t_rise_s + tau + TRAP.t_fall_s, 1.0)]
        for (tx, vx), (ty, vy) in zip(pts[:4], first, strict=True):
            assert tx == ty  # 逐位同 schema
            assert vx == vy
        assert pts[-1] == (self.N_PER * TRAP.t_period_s, 1.0)
        # 第二周期相位平移
        assert pts[5][0] == TRAP.t_period_s + TRAP.t_rise_s
        assert pts[5][1] == 3.0

    def test_structure_lines(self) -> None:
        text = self._render()
        assert text.startswith("* rfauto DR-7")
        assert f"R1 1 0 {self.R:.17g}" in text
        assert f"L1 1 0 {self.LH:.17g}" in text
        assert f"C1 1 0 {self.CF:.17g}" in text
        assert f".tran {TRAP.t_period_s / 1000.0:.17g} {5 * TRAP.t_period_s:.17g}" in text
        assert ".print tran v(1)" in text
        assert text.rstrip().endswith(".end")
        text.encode("ascii")  # #89：工具文件零非 ASCII（写盘即炸面）

    def test_render_guards(self) -> None:
        with pytest.raises(ValueError, match="n_periods"):
            render_tran_netlist(TRAP, r_ohm=1, l_henry=1, c_farad=1, n_periods=0)
        with pytest.raises(ValueError, match="r_ohm"):
            render_tran_netlist(TRAP, r_ohm=0, l_henry=1, c_farad=1, n_periods=1)
        with pytest.raises(ValueError, match="t_step_s"):
            render_tran_netlist(TRAP, r_ohm=1, l_henry=1, c_farad=1, n_periods=1,
                                t_step_s=2 * TRAP.t_period_s)


# ─── 真机 Xyce 对照（opt-in：RFAUTO_PDN_TRAN_XYCE_REAL=1；不可达如实降级）────


def _xyce_real_cross_check() -> str:
    """真机对照：Xyce .TRAN 纹波峰峰 vs IFFT 纹波峰峰（规格 ≤10% 起步）。

    走 adapters/xyce_adapter 的 WSL 通道（core 层禁 import adapters——分层
    契约，故驱动面落在本测试）；产物归档 runs/dr67/。
    """
    from rfauto.adapters.xyce_adapter import (
        prn_path_for,
        read_prn,
        resolve_xyce_exe,
        run_xyce,
        verify_xyce_reachable,
    )

    r_ohm, l_h, c_f = 0.5, 10e-9, 100e-9
    out_dir = Path(__file__).resolve().parents[2] / "runs" / "dr67"
    out_dir.mkdir(parents=True, exist_ok=True)
    netlist = out_dir / "dr7_pdn_tran.cir"
    netlist.write_bytes(render_tran_netlist(
        TRAP, r_ohm=r_ohm, l_henry=l_h, c_farad=c_f, n_periods=8,
        title="rfauto DR-7 pdn tran ripple xyce cross-check",
    ).encode("ascii"))
    verify_xyce_reachable(resolve_xyce_exe())
    run = run_xyce(netlist, timeout_s=300.0)
    if run.timed_out or run.rc != 0:
        return f"DEGRADED: Xyce 运行失败 rc={run.rc} err={run.stderr[-200:]}"
    parsed = read_prn(prn_path_for(netlist, ac=False))
    t_xy = np.asarray(parsed["data"]["TIME"], dtype=float).real
    v_xy = np.asarray(parsed["data"]["V(1)"], dtype=float).real
    tail = t_xy >= 7.0 * TRAP.t_period_s  # 末周期判稳态
    v_pp_xy = float(v_xy[tail].max() - v_xy[tail].min())
    res = ripple_response(TRAP, n_max=400,
                          z_of_freq=lambda f: z_parallel_rlc(f, r_ohm, l_h, c_f),
                          n_fft=1 << 16)
    rel = abs(v_pp_xy / res.v_pkpk_v - 1.0)
    verdict = "PASS" if rel < 0.10 else "FAIL"
    (out_dir / "dr7_xyce_crosscheck_summary.txt").write_text(
        f"v_pp_xyce={v_pp_xy!r} V\nv_pp_iff={res.v_pkpk_v!r} V\nrel={rel!r}\n"
        f"verdict={verdict}（规格起步门 ≤10%）\n",
        encoding="utf-8",
    )
    return f"{verdict}: v_pp_xyce={v_pp_xy:.6e} v_pp_iff={res.v_pkpk_v:.6e} rel={rel:.4%}"


@pytest.mark.skipif(
    not __import__("os").environ.get("RFAUTO_PDN_TRAN_XYCE_REAL"),
    reason="真跑集成测试不进缺省 unit 门（df4⑥）：设 RFAUTO_PDN_TRAN_XYCE_REAL=1 启用",
)
def test_xyce_real_tran_cross_check() -> None:
    report = _xyce_real_cross_check()
    assert report.startswith("PASS"), report
