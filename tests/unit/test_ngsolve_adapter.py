"""NGSolve 适配器单测（离线确定性 + 真机 skipif 两层）。

离线面（不 import ngsolve，任何环境必跑）：注册表/枚举接线、capabilities
如实声明（A5）、参数规范化、闭式 S 矩阵（匹配线/四分之一波独立锚）、
Robin γ、行波分解、波变量→S 全链符号/相位约定（与闭式逐频互检 1e-10，
**约定锁定测试**——真机跑之前先钉死数学链）、build/solve 生命周期守卫。
P2⑫ 增量：TE10 闭式（WR-90 独立锚 + 截止拒绝）、色散段闭式 S、
rect_waveguide 参数/闭式（独立 Z_in 锚）、模剖面内积模电压、多端口
真 S 列装配（锁定列逐位一致 + 激励 2 镜像 roundtrip）。
真机面（skipif ngsolve 未装，语义清晰跳过）：parallel_plate 全链真跑
（|ΔS|≤0.02、无源性、对称/互易）；rect_waveguide 真 2×2 全矩阵门
（闭式复数逐元 + 无源性 + 互易小量）。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from rfauto.adapters import ngsolve_adapter as na
from rfauto.adapters.em_solver_base import (
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
)
from rfauto.adapters.ngsolve_adapter import (
    C0,
    ETA0,
    GATE_S_MAX_ABS_ERR,
    RECT_WAVEGUIDE_DEFAULTS,
    NGSolveAdapter,
    dispersive_section_sparams,
    excitation_coef,
    extract_eps_eff,
    modal_voltage_te10,
    normalize_parallel_plate_params,
    normalize_rect_waveguide_params,
    parallel_plate_closed_form,
    parallel_plate_z0,
    port_waves_to_b,
    rect_waveguide_closed_form,
    resolve_freq_points,
    robin_gamma,
    sparams_column_from_waves,
    sparams_from_waves,
    te10_beta,
    te10_fc_ghz,
    te10_wave_impedance,
    tl_section_sparams,
    wave_decompose,
)

# 真机语义：ngsolve 未安装时整类跳过（skip 理由显式给出安装口径）
_HAS_NGSOLVE = na.ngsolve_installed()


def _make_adapter(tmp_path, **extra) -> NGSolveAdapter:
    cfg = EMSolverConfig(solver_type=EMSolverType.NGSOLVE,
                         working_dir=str(tmp_path),
                         freq_range_ghz=(2.0, 5.0),
                         extra_params={"n_freq": 4, **extra})
    return NGSolveAdapter(cfg)


class TestRegistration:
    """注册表/枚举接线（基类+注册表模式）。"""

    def test_enum_member_value(self):
        assert EMSolverType.NGSOLVE.value == "ngsolve"

    def test_registered_on_package_import(self):
        import rfauto.adapters  # noqa: F401  导入即注册

        assert get_global_registry().is_registered(EMSolverType.NGSOLVE)
        assert get_global_registry().lookup(EMSolverType.NGSOLVE) is NGSolveAdapter

    def test_is_em_solver_adapter_with_contract(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert isinstance(adapter, EMSolverAdapter)
        for method in ("connect", "is_available", "build_geometry", "solve",
                       "get_sparams", "close"):
            assert callable(getattr(adapter, method)), method

    def test_capabilities_declared_honestly(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        caps = adapter.capabilities()
        # A5 纪律：未实现能力一律 False，不得虚报。P2⑫：rect_waveguide 的
        # TE10 解析模态波导端口过门后 supports_wave_port 翻真（COMSOL 数值
        # 模端口过锚翻真同口径）；lumped/场导出/Touchstone/optimetrics/
        # nf2ff/SAR 仍无实现 → False。
        assert caps.solver_type == "ngsolve"
        assert caps.supports_wave_port is True  # TE10 模态 Robin（rect_waveguide）
        assert caps.supports_lumped_port is False
        assert caps.supports_field_export is False
        assert caps.supports_convergence_report is False
        assert caps.supports_touchstone_export is False
        assert caps.supports_optimetrics is False
        assert caps.supports_nf2ff is False
        assert caps.supports_sar is False
        assert caps.requires_license is False
        assert caps.supported_templates == ("parallel_plate", "rect_waveguide")
        assert caps.availability_gate == "pip:ngsolve"
        assert caps.material_models == ("pec", "lossless_dielectric")
        # 声明 vs 实现：无 Touchstone 导出方法、输出格式不含 touchstone
        assert not hasattr(adapter, "_export_touchstone")
        assert "touchstone" not in adapter.supported_output_formats()

    def test_param_semantics_declared_for_every_param(self):
        semantics = NGSolveAdapter.param_semantics
        for key in na.PARALLEL_PLATE_DEFAULTS:
            assert key in semantics["parallel_plate"], key
        for key in na.RECT_WAVEGUIDE_DEFAULTS:
            assert key in semantics["rect_waveguide"], key


class TestAvailability:
    """可用性门：不依赖 ngsolve 的环境显式不可用、报错清晰。"""

    def test_ngsolve_installed_follows_find_spec(self, monkeypatch):
        import importlib.util

        monkeypatch.setattr(importlib.util, "find_spec",
                            lambda name: None, raising=True)
        assert na.ngsolve_installed() is False

    def test_connect_gated_without_ngsolve(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: False)
        assert adapter.is_available() is False
        assert adapter.connect() is False

    def test_solve_without_connection_fails_cleanly(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: False)
        result = adapter.solve()
        assert result.success is False
        assert "未连接" in result.message


class TestPureMath:
    """确定性内核：闭式/提取数学（无 ngsolve 依赖）。"""

    def test_normalize_defaults_override_and_validation(self):
        spec = normalize_parallel_plate_params(None)
        assert spec == na.PARALLEL_PLATE_DEFAULTS
        spec = normalize_parallel_plate_params({"height_mm": 1.0})
        assert spec["height_mm"] == 1.0
        assert spec["eps_r"] == na.PARALLEL_PLATE_DEFAULTS["eps_r"]
        with pytest.raises(ValueError, match="height_mm"):
            normalize_parallel_plate_params({"height_mm": -1.0})
        with pytest.raises(ValueError, match="eps_r"):
            normalize_parallel_plate_params({"eps_r": float("nan")})
        unknown = normalize_parallel_plate_params({"unknown_key": 3.0})
        assert "unknown_key" not in unknown

    def test_z0_closed_form(self):
        # 手算锚：η0/√2.1·(0.6924/6) ≈ 30.000Ω（刻意与 Zref=50 失配）
        z0 = parallel_plate_z0(6.0, 0.6924, 2.1)
        assert abs(z0 - 30.0) < 0.01
        assert abs(parallel_plate_z0(1.0, 1.0, 1.0) - ETA0) < 1e-9

    def test_robin_gamma_value_and_validation(self):
        assert abs(robin_gamma(30.0, 50.0) - 0.6) < 1e-12
        assert robin_gamma(50.0, 50.0) == 1.0
        with pytest.raises(ValueError):
            robin_gamma(0.0, 50.0)
        with pytest.raises(ValueError):
            robin_gamma(30.0, -1.0)

    def test_resolve_freq_points(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        pts = resolve_freq_points(adapter._config, None)
        assert pts == [2.0, 3.0, 4.0, 5.0]
        pts = resolve_freq_points(adapter._config, {"freq_ghz": [1.0, 2.5]})
        assert pts == [1.0, 2.5]
        with pytest.raises(ValueError):
            resolve_freq_points(adapter._config, {"freq_ghz": [-1.0]})

    def test_tl_section_matched_line(self):
        # 匹配线（Z0=Zref）：S11=0、|S21|=1、S21 相位=−βL（手推独立锚）
        freqs = np.array([2.0, 3.0, 5.0])
        s = tl_section_sparams(freqs, 2.1, 50.0, 20.0, z_ref=50.0)
        assert np.max(np.abs(s[:, 0, 0])) < 1e-12
        assert np.max(np.abs(np.abs(s[:, 1, 0]) - 1.0)) < 1e-12
        for i, f in enumerate(freqs):
            beta_l = 2.0 * np.pi * f * 1e9 * math.sqrt(2.1) / C0 * 0.02
            assert abs(np.angle(s[i, 1, 0]) + beta_l) < 1e-12

    def test_tl_section_quarter_wave_independent_anchor(self):
        # 四分之一波长线（βL=π/2）：S11=(Z0²−Zref²)/(Z0²+Zref²) 为实数
        # （手推独立锚：A=D=0, B=jZ0, C=j/Z0 代入 ABCD→S）。取 f0 使
        # βL=π/2：f = c/(4L√εr)。
        eps_r, length_mm = 2.1, 20.0
        f0 = C0 / (4.0 * (length_mm * 1e-3) * math.sqrt(eps_r)) / 1e9
        s = tl_section_sparams(np.array([f0]), eps_r, 30.0, length_mm, z_ref=50.0)
        expect = (30.0**2 - 50.0**2) / (30.0**2 + 50.0**2)
        assert abs(s[0, 0, 0].imag) < 1e-10
        assert abs(s[0, 0, 0].real - expect) < 1e-10

    def test_parallel_plate_closed_form_defaults_mismatch(self):
        # 独立锚：Z_in 解析式（线+负载输入阻抗）→ Γ=(Z_in−Zref)/(Z_in+Zref)
        # （与被测 ABCD 公式不同推导路径，防同源互证）
        spec = normalize_parallel_plate_params(None)
        freqs = np.array([2.0, 3.0, 4.0, 5.0])
        s = parallel_plate_closed_form(spec, freqs)
        z0 = parallel_plate_z0(spec["width_mm"], spec["height_mm"],
                               spec["eps_r"])
        zref, length_m, eps_r = spec["z_ref_ohm"], spec["length_mm"] * 1e-3, \
            spec["eps_r"]
        for i, f_ghz in enumerate(freqs):
            beta = 2.0 * np.pi * f_ghz * 1e9 * math.sqrt(eps_r) / C0
            t = math.tan(beta * length_m)
            z_in = z0 * (zref + 1j * z0 * t) / (z0 + 1j * zref * t)
            s11_indep = (z_in - zref) / (z_in + zref)
            assert abs(s[i, 0, 0] - s11_indep) < 1e-10

    def test_wave_decompose_roundtrip(self):
        xs = np.linspace(0.006, 0.014, 5)
        k = 60.7
        c_plus, c_minus = 1.5 - 0.3j, -0.4 + 0.2j
        v = c_plus * np.exp(1j * k * xs) + c_minus * np.exp(-1j * k * xs)
        r_plus, r_minus = wave_decompose(v, xs, k)
        assert abs(r_plus - c_plus) < 1e-12
        assert abs(r_minus - c_minus) < 1e-12

    def test_wave_decompose_rejects_bad_input(self):
        xs = np.array([0.0, 0.01])
        with pytest.raises(ValueError):
            wave_decompose(np.array([1.0 + 0j]), xs, 60.0)  # 点数不足
        with pytest.raises(ValueError):
            wave_decompose(np.array([1j, 1j]), xs, -1.0)  # k 非正
        with pytest.raises(ValueError):
            wave_decompose(np.array([1j, 1j, 1j]), xs, 60.0)  # 形状不一致

    def test_excitation_coef_hand_value(self):
        # G1 = 2jkγE_INC/H：手算锚（2GHz、γ=0.6、H=0.6924mm）
        k = 2.0 * np.pi * 2e9 * math.sqrt(2.1) / C0
        expect = 2j * k * 0.6 * 1.0 / 0.6924e-3
        got = excitation_coef(k, 0.6, 1.0, 0.6924e-3)
        assert abs(got - expect) < 1e-6 * abs(expect)
        with pytest.raises(ValueError):
            excitation_coef(k, 0.6, 1.0, 0.0)

    def test_sparams_from_waves_matches_closed_form(self):
        # **约定锁定测试**：物理夹具=Zref 源 + Z0 线 + Zref 负载。
        # 独立解析链：Thevenin 分压 → 线上工程约定波幅 (a,b)（Γ_L 闭合式）
        # → 取共轭模拟求解器 e^{−iωt} 相位 → sparams_from_waves 输出必须
        # 逐频全复数复现 ABCD 闭式 S（真机跑之前钉死全部符号/相位约定）。
        z0, zref, length_m, eps_r = 30.0, 50.0, 0.02, 2.1
        gamma_l = (zref - z0) / (zref + z0)
        freqs = np.array([2.0, 3.0, 4.0, 5.0])
        s_ref = tl_section_sparams(freqs, eps_r, z0, length_m * 1e3, z_ref=zref)
        for i, f_ghz in enumerate(freqs):
            omega = 2.0 * np.pi * f_ghz * 1e9
            k = omega * math.sqrt(eps_r) / C0
            vs = -2.0  # 适配器激励参考：Vs = 2√Zref·a1 = −2·E_INC（a1=−E_INC/√Zref）
            # 线输入阻抗（工程解析式）→ 源面 V/I → 波幅分解
            t = math.tan(k * length_m)
            z_in = z0 * (zref + 1j * z0 * t) / (z0 + 1j * zref * t)
            vv = vs * z_in / (zref + z_in)
            ii = vs / (zref + z_in)
            a_eng = (vv + z0 * ii) / 2.0            # 前向（e^{−jkx}）
            b_eng = (vv - z0 * ii) / 2.0            # 反向（e^{+jkx}）
            # 解析自检：反向/前向 = Γ_L e^{−2jkL}
            assert abs(b_eng / a_eng - gamma_l * np.exp(-2j * k * length_m)) < 1e-9
            s = sparams_from_waves(np.conj(a_eng), np.conj(b_eng), k,
                                   length_m, z0, zref)
            assert np.max(np.abs(s - s_ref[i])) < 1e-10

    def test_sparams_from_waves_validates_inputs(self):
        with pytest.raises(ValueError):
            sparams_from_waves(1j, 0j, 60.0, 0.02, 30.0, -50.0)
        with pytest.raises(ValueError):
            sparams_from_waves(1j, 0j, 60.0, 0.0, 30.0, 50.0)

    def test_extract_eps_eff_synthetic(self):
        eps_true, length_mm = 2.5, 20.0
        freqs = np.array([2.0, 3.0, 4.0, 5.0, 6.0])
        beta = 2.0 * np.pi * freqs * 1e9 * math.sqrt(eps_true) / C0
        s21 = np.exp(-1j * beta * length_mm * 1e-3)  # 工程约定 e^{−jβL}
        assert abs(extract_eps_eff(freqs, s21, length_mm) - eps_true) < 1e-9

    def test_extract_eps_eff_rejects_nonphysical_slope(self):
        freqs = np.array([2.0, 3.0, 4.0])
        s21 = np.array([1 + 0j, 1 + 0j, 1 + 0j])  # 零斜率，无法解释为 −βL
        with pytest.raises(ValueError, match="斜率"):
            extract_eps_eff(freqs, s21, 20.0)
        with pytest.raises(ValueError, match="2 个频点"):
            extract_eps_eff(np.array([2.0]), np.array([1.0 + 0j]), 20.0)


class TestTe10ClosedForm:
    """TE10 闭式（P2⑫）：WR-90 独立锚 + 截止拒绝（确定性，无 ngsolve）。"""

    def test_fc_wr90_independent_anchor(self):
        # 锚：WR-90（a=22.86mm 空气）fc=6.5571GHz（文献值）
        fc = te10_fc_ghz(22.86, 1.0)
        assert abs(fc - 6.5571) < 5e-4
        # 独立路径：fc = c·kc/(2π)，kc=π/a
        kc = math.pi / 0.02286
        assert abs(fc * 1e9 - C0 * kc / (2.0 * math.pi)) < 1e-6
        # 填充介质 1/√εr 标度
        assert abs(te10_fc_ghz(22.86, 2.1) * math.sqrt(2.1) - fc) < 1e-9
        with pytest.raises(ValueError):
            te10_fc_ghz(-1.0, 1.0)
        with pytest.raises(ValueError):
            te10_fc_ghz(22.86, 0.0)

    def test_beta_identity_and_cutoff_reject(self):
        fc = te10_fc_ghz(22.86, 1.0)
        kc = math.pi / 0.02286
        for f in (8.2, 10.0, 12.4):
            beta = te10_beta(f, fc)
            k = 2.0 * math.pi * f * 1e9 / C0
            # 独立锚：色散关系 β=√(k²−kc²)
            assert abs(beta - math.sqrt(k * k - kc * kc)) < 1e-9
        with pytest.raises(ValueError, match="截止"):
            te10_beta(6.0, fc)
        with pytest.raises(ValueError, match="截止"):
            te10_beta(fc, fc)  # 恰在截止：β=0 无传播解
        with pytest.raises(ValueError):
            te10_beta(10.0, -1.0)

    def test_wave_impedance_anchor_and_crosscheck(self):
        fc = te10_fc_ghz(22.86, 1.0)
        # 锚：Z_TE10@10GHz=498.97Ω（文献值）
        assert abs(te10_wave_impedance(10.0, fc) - 498.97) < 0.05
        for f in (8.2, 10.0, 12.4):
            z_te = te10_wave_impedance(f, fc)
            k = 2.0 * math.pi * f * 1e9 / C0
            # 独立路径：Z_TE = η·k/β
            assert abs(z_te - ETA0 * k / te10_beta(f, fc)) < 1e-8 * z_te
        with pytest.raises(ValueError, match="截止"):
            te10_wave_impedance(5.0, fc)
        with pytest.raises(ValueError):
            te10_wave_impedance(10.0, fc, eta_medium=-1.0)


class TestDispersiveSection:
    """色散段闭式 S：退化一致性 + 匹配线 + 输入校验（tl_section 签名不动）。"""

    def test_reduces_to_tl_section_when_nondispersive(self):
        freqs = np.array([8.2, 9.5, 10.5, 12.4])
        eps_r, z0, length_mm = 2.1, 30.0, 20.0
        beta = np.array([2.0 * math.pi * f * 1e9 * math.sqrt(eps_r) / C0
                         for f in freqs])
        s_disp = dispersive_section_sparams(freqs, beta,
                                            np.full(freqs.size, z0),
                                            length_mm, z_ref=50.0)
        s_ref = tl_section_sparams(freqs, eps_r, z0, length_mm, z_ref=50.0)
        assert np.max(np.abs(s_disp - s_ref)) < 1e-12

    def test_matched_line_unitary_phase(self):
        freqs = np.array([9.0, 10.0, 11.0])
        fc = te10_fc_ghz(22.86)
        beta = np.array([te10_beta(f, fc) for f in freqs])
        s = dispersive_section_sparams(freqs, beta, np.full(3, 50.0), 40.0,
                                       z_ref=50.0)
        assert np.max(np.abs(s[:, 0, 0])) < 1e-12
        assert np.max(np.abs(np.abs(s[:, 1, 0]) - 1.0)) < 1e-12
        for i in range(len(freqs)):
            # 相位差按 2π 卷绕比较（angle ∈ (−π,π]，βL 可超过 π）
            dphi = np.angle(s[i, 1, 0]) + beta[i] * 0.04
            dphi = (dphi + math.pi) % (2.0 * math.pi) - math.pi
            assert abs(dphi) < 1e-12

    def test_validates_inputs(self):
        freqs = np.array([10.0, 11.0])
        with pytest.raises(ValueError):
            dispersive_section_sparams(freqs, np.array([1.0, 2.0, 3.0]),
                                       np.array([50.0, 50.0]), 40.0)
        with pytest.raises(ValueError):
            dispersive_section_sparams(freqs, np.array([1.0, 2.0]),
                                       np.array([50.0, -50.0]), 40.0)
        with pytest.raises(ValueError):
            dispersive_section_sparams(freqs, np.array([1.0, 2.0]),
                                       np.array([50.0, 50.0]), 0.0)


class TestRectWaveguidePure:
    """rect_waveguide 参数/闭式/模电压投影（离线确定性内核）。"""

    def test_normalize_defaults_override_validation(self):
        spec = normalize_rect_waveguide_params(None)
        assert spec == RECT_WAVEGUIDE_DEFAULTS
        spec = normalize_rect_waveguide_params({"length_mm": 30.0})
        assert spec["length_mm"] == 30.0
        assert spec["a_mm"] == RECT_WAVEGUIDE_DEFAULTS["a_mm"]
        with pytest.raises(ValueError, match="length_mm"):
            normalize_rect_waveguide_params({"length_mm": 0.0})
        with pytest.raises(ValueError, match="a_mm"):
            normalize_rect_waveguide_params({"a_mm": float("nan")})
        with pytest.raises(ValueError, match="TE10"):
            normalize_rect_waveguide_params({"a_mm": 10.16, "b_mm": 22.86})

    def test_closed_form_independent_zin_anchor(self):
        # 独立解析链：色散线输入阻抗式 → Γ（与 ABCD 公式不同推导路径，
        # 防同源互证；同 test_parallel_plate_closed_form_defaults_mismatch 范式）
        spec = normalize_rect_waveguide_params(None)
        freqs = np.array([8.5, 10.0, 11.5, 12.4])
        s = rect_waveguide_closed_form(spec, freqs)
        assert s.shape == (4, 2, 2)
        zref = spec["z_ref_ohm"]
        length_m = spec["length_mm"] * 1e-3
        fc = te10_fc_ghz(spec["a_mm"], spec["eps_r"])
        for i, f_ghz in enumerate(freqs):
            beta = te10_beta(float(f_ghz), fc, spec["eps_r"])
            z_te = te10_wave_impedance(float(f_ghz), fc)
            t = math.tan(beta * length_m)
            z_in = z_te * (zref + 1j * z_te * t) / (z_te + 1j * zref * t)
            s11_indep = (z_in - zref) / (z_in + zref)
            assert abs(s[i, 0, 0] - s11_indep) < 1e-10
            # 无耗能量守恒：|S11|²+|S21|²=1
            assert abs(abs(s[i, 0, 0]) ** 2 + abs(s[i, 1, 0]) ** 2 - 1.0) < 1e-10

    def test_closed_form_rejects_below_cutoff(self):
        spec = normalize_rect_waveguide_params(None)
        with pytest.raises(ValueError, match="截止"):
            rect_waveguide_closed_form(spec, np.array([5.0, 9.0]))
        with pytest.raises(ValueError, match="截止"):
            rect_waveguide_closed_form(spec, np.array([6.55707]))  # ≈fc 截止点

    def test_modal_voltage_projection(self):
        a_mm, b_mm = 22.86, 10.16
        ys = np.linspace(0.0, a_mm * 1e-3, 41)
        # 纯 TE10 剖面：精确恢复 V=b·Ê（与采样无关）
        ez = 3.3 * np.sin(math.pi * ys / (a_mm * 1e-3))
        got = modal_voltage_te10(ez, ys, a_mm, b_mm)
        assert abs(got - b_mm * 1e-3 * 3.3) < 1e-9
        # 线性场的最小二乘投影：解析 ∫₀ᵃ2y·sin(πy/a)dy·(2/a) = 4a/π；
        # 非纯剖面场的离散投影与连续积分有 O(h²) 差（41 点实测 ~5e-4 相对）
        ez_lin = 2.0 * ys
        expect = b_mm * 1e-3 * (4.0 * a_mm * 1e-3 / math.pi)
        assert abs(modal_voltage_te10(ez_lin, ys, a_mm, b_mm) - expect) < 1e-6
        # 复数剖面（行波相位）幅值正确
        ez_c = 3.3 * np.exp(1j * 0.7) * np.sin(math.pi * ys / (a_mm * 1e-3))
        got = modal_voltage_te10(ez_c, ys, a_mm, b_mm)
        assert abs(abs(got) - b_mm * 1e-3 * 3.3) < 1e-9
        with pytest.raises(ValueError):
            modal_voltage_te10(np.array([1.0]), np.array([0.0, 0.01]),
                               a_mm, b_mm)  # 采样不匹配
        with pytest.raises(ValueError):
            modal_voltage_te10(np.array([1.0, 2.0]), np.array([0.0, 0.011]),
                               0.0, b_mm)  # a 非正
        with pytest.raises(ValueError, match="节点"):
            modal_voltage_te10(np.array([1.0, 2.0]),
                               np.array([0.0, a_mm * 1e-3]), a_mm, b_mm)


class TestMultiPortWaveAssembly:
    """多端口真 S 列装配（P2⑫ E 项，离线）：锁定列逐位一致 + 激励 2 镜像
    roundtrip（S22/S12 不再假设填充的数学验证）。"""

    @staticmethod
    def _analytic_waves(f_ghz, z0, zref, length_m, eps_r):
        """激励 1 的线内行波幅值（Thevenin 独立解析链，同锁定测试口径）。"""
        omega = 2.0 * np.pi * f_ghz * 1e9
        k = omega * math.sqrt(eps_r) / C0
        vs = -2.0
        t = math.tan(k * length_m)
        z_in = z0 * (zref + 1j * z0 * t) / (z0 + 1j * zref * t)
        vv = vs * z_in / (zref + z_in)
        ii = vs / (zref + z_in)
        a_eng = (vv + z0 * ii) / 2.0
        b_eng = (vv - z0 * ii) / 2.0
        return complex(np.conj(a_eng)), complex(np.conj(b_eng)), k

    def test_column_matches_closed_form(self):
        z0, zref, length_m, eps_r = 30.0, 50.0, 0.02, 2.1
        freqs = np.array([2.0, 3.0, 4.0, 5.0])
        s_ref = tl_section_sparams(freqs, eps_r, z0, length_m * 1e3,
                                   z_ref=zref)
        for i, f in enumerate(freqs):
            cp, cm, k = self._analytic_waves(float(f), z0, zref, length_m,
                                             eps_r)
            col = sparams_column_from_waves(cp, cm, k, length_m, z0, zref)
            assert col.shape == (2,)
            assert abs(col[0] - s_ref[i, 0, 0]) < 1e-10  # S11
            assert abs(col[1] - s_ref[i, 1, 0]) < 1e-10  # S21

    def test_roundtrip_excitation2_symmetric_line(self):
        # 对称无耗线：激励 2 的场 = 激励 1 的镜像（V₂(x)=V₁(L−x)）⟹
        # c₊'=c₋·e^{−jkL}、c₋'=c₊·e^{+jkL}；装配的第 2 列必须给出
        # [S12, S22]=[S21, S11]——参考面相位处理的端到端验证。
        z0, zref, length_m, eps_r = 30.0, 50.0, 0.02, 2.1
        freqs = np.array([2.0, 3.0, 4.0, 5.0])
        s_ref = tl_section_sparams(freqs, eps_r, z0, length_m * 1e3,
                                   z_ref=zref)
        for i, f in enumerate(freqs):
            cp, cm, k = self._analytic_waves(float(f), z0, zref, length_m,
                                             eps_r)
            cp2 = cm * np.exp(-1j * k * length_m)
            cm2 = cp * np.exp(1j * k * length_m)
            col2 = sparams_column_from_waves(cp2, cm2, k, length_m, z0, zref)
            assert abs(col2[0] - s_ref[i, 0, 1]) < 1e-10  # S12
            assert abs(col2[1] - s_ref[i, 1, 1]) < 1e-10  # S22

    def test_column_validates_inputs(self):
        with pytest.raises(ValueError):
            sparams_column_from_waves(1j, 0j, 60.0, 0.02, 30.0, -50.0)
        with pytest.raises(ValueError):
            sparams_column_from_waves(1j, 0j, 60.0, 0.0, 30.0, 50.0)

    def test_port_waves_to_b_shared_with_locked_path(self):
        # port_waves_to_b 与 sparams_from_waves 前两元素同源（重构不变形）
        cp, cm, k = self._analytic_waves(3.0, 30.0, 50.0, 0.02, 2.1)
        b1, b2 = port_waves_to_b(cp, cm, k, 0.02, 30.0, 50.0)
        s = sparams_from_waves(cp, cm, k, 0.02, 30.0, 50.0)
        a1 = -1.0 / math.sqrt(50.0)
        assert abs(s[0, 0] - np.conj(b1 / a1)) < 1e-14
        assert abs(s[1, 0] - np.conj(b2 / a1)) < 1e-14


class TestLifecycle:
    """build/solve 生命周期（离线，无 ngsolve 依赖的守卫语义）。"""

    def test_build_geometry_guards(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: True)
        assert adapter.build_geometry({"template": "parallel_plate"}) is False  # 未连接
        assert adapter.connect() is True
        assert adapter.build_geometry({"template": "patch"}) is False  # 不支持
        assert adapter.build_geometry(
            {"template": "parallel_plate", "params": {"width_mm": -1}}) is False

    def test_build_geometry_writes_spec_evidence(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: True)
        assert adapter.connect() and adapter.build_geometry(
            {"template": "parallel_plate"})
        doc = json.loads((tmp_path / "ngsolve_spec.json").read_text(
            encoding="utf-8"))
        assert doc["template"] == "parallel_plate"
        assert abs(doc["closed_form_z0_ohm"] - 30.0) < 0.01
        assert abs(doc["robin_gamma"] - 0.6) < 1e-3
        assert doc["freq_ghz"] == [2.0, 3.0, 4.0, 5.0]
        assert "Robin" in doc["port_convention"]

    def test_build_geometry_rect_waveguide_evidence(self, tmp_path,
                                                    monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: True)
        assert adapter.connect()
        assert adapter.build_geometry(
            {"template": "rect_waveguide",
             "params": {"freq_ghz": [8.2, 10.0, 12.4]}})
        doc = json.loads((tmp_path / "ngsolve_spec.json").read_text(
            encoding="utf-8"))
        assert doc["template"] == "rect_waveguide"
        assert abs(doc["te10_fc_ghz"] - 6.5571) < 1e-3
        assert abs(doc["te10_z_mid_ohm"] - te10_wave_impedance(
            10.0, te10_fc_ghz(22.86))) < 0.01
        assert "TE10" in doc["port_convention"]
        # 波导模板默认网格档自动切换（显式 mesh_maxh_mm extra_params 优先）
        assert adapter._mesh_maxh_mm == na.WAVEGUIDE_MESH_MAXH_MM

    def test_build_geometry_rect_rejects_swapped_walls(self, tmp_path,
                                                       monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: True)
        adapter.connect()
        assert adapter.build_geometry(
            {"template": "rect_waveguide",
             "params": {"a_mm": 10.16, "b_mm": 22.86}}) is False  # TE10 需 a>b

    def test_solve_rect_below_cutoff_fails_cleanly(self, tmp_path,
                                                   monkeypatch):
        # 低于截止：闭式层显式 ValueError → success=False（先于网格构建）
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: True)
        adapter.connect()
        assert adapter.build_geometry(
            {"template": "rect_waveguide", "params": {"freq_ghz": [3.0]}})
        result = adapter.solve()
        assert result.success is False
        assert "截止" in result.message

    def test_get_sparams_before_solve_raises(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        with pytest.raises(RuntimeError, match="尚未成功求解"):
            adapter.get_sparams()

    def test_close_and_status(self, tmp_path, monkeypatch):
        adapter = _make_adapter(tmp_path)
        monkeypatch.setattr(na, "ngsolve_installed", lambda: True)
        assert adapter.connect()
        status = adapter.get_status()
        assert status["solver_type"] == "ngsolve"
        assert status["ngsolve_installed"] is True
        assert status["license_policy"]
        adapter.close()
        assert adapter._connected is False

    def test_visualizations_declare_sparams(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        viz = adapter.visualizations()
        assert any(v["kind"] == "sparams" for v in viz)


@pytest.mark.skipif(not _HAS_NGSOLVE,
                    reason="ngsolve 未安装——真机语义测试跳过"
                           "（.venv/Scripts/python.exe -m pip install ngsolve 后生效）")
class TestRealRun:
    """真机全链（ngsolve 已装时执行）：闭式对照门 + 无源性/互易性。"""

    def test_parallel_plate_closed_form_gate(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.connect()
        assert adapter.build_geometry({"template": "parallel_plate"})
        result = adapter.solve()
        assert result.success, result.message
        _freq_ghz, s = adapter.get_sparams()
        assert s.shape == (4, 2, 2)
        # 闭式对照门（|ΔS| 复数逐元）
        assert result.field_data["s11_max_abs_err"] <= GATE_S_MAX_ABS_ERR
        assert result.field_data["s21_max_abs_err"] <= GATE_S_MAX_ABS_ERR
        # εeff 门控界（闭式相位残差传播）
        assert result.field_data["eps_eff_rel_err_bound"] <= 1e-3
        # 无源性 + 结构对称 + 互易
        assert float(np.abs(s).max()) <= 1.0 + 1e-6
        assert np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])) < 1e-12
        assert np.max(np.abs(s[:, 1, 1] - s[:, 0, 0])) < 1e-12
        # 证据产物 + 门语义
        assert (tmp_path / "sparams.csv").exists()
        assert (tmp_path / "ngsolve_spec.json").exists()
        assert "门全过" in result.message

    def test_rect_waveguide_true_2x2_gate(self, tmp_path):
        """P2⑫ 真跑门：TE10 模态 Robin + 逐端口激励轮转 → 真 2×2 对照
        色散闭式（复数逐元）+ 无源性 + 互易小量（S22/S12 为真测量）。"""
        adapter = _make_adapter(tmp_path)
        assert adapter.connect()
        assert adapter.build_geometry(
            {"template": "rect_waveguide",
             "params": {"freq_ghz": [8.2, 9.6, 11.0, 12.4]}})
        result = adapter.solve()
        assert result.success, result.message
        _freq, s = adapter.get_sparams()
        assert s.shape == (4, 2, 2)
        fd = result.field_data
        # 全 2×2 复数逐元闭式对照（含 S22/S12，无对称/互易假设）
        assert fd["s_max_abs_err"] <= GATE_S_MAX_ABS_ERR
        # 无源性（无耗结构）：逐端口功率守恒 Σ_j|S_ij|² ≤ 1 + 离散容差
        assert fd["passivity_max_sum"] <= 1.0 + 1e-3
        # 互易小量：两次独立激励的量级一致性检查，非恒等假设
        assert fd["reciprocity_max_abs"] <= GATE_S_MAX_ABS_ERR
        assert (tmp_path / "sparams.csv").exists()
        assert (tmp_path / "ngsolve_spec.json").exists()
        assert "门全过" in result.message
