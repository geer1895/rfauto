"""A3 场-路协同锚单测（linkage/field_circuit_nonlinear，全离线，不跑 ngspice）。

钉死四类事实：
- 闭式 L 截面替身的教科书性质（DC 极限/互易/无源/高频反射）；
- Touchstone 往返与 S→Y 谐波插值（对拍直接 s_to_y 闭式）；
- **Y(S) vs 物理 RLC 两条独立导出路径的 HB 等价性**（A3 链路核心前提）；
- 对拍判定与端到端管线（注入 ngspice_runner 替身；判据数字来自
  2026-09-14 真机 ngspice-47 实测，HB 确定性故回归钉死有效）。

真机对照（真 ngspice 二进制）由 tests/real_edt/test_field_circuit_nonlinear_real.py
承载——与 WP4.3 场路锚同纪律。
"""

import json

import numpy as np
import pytest

from rfauto.core.circuit_hb import solve_harmonic_balance
from rfauto.linkage import field_circuit_nonlinear as fcn

#: 2026-09-14 真机 ngspice-47（runs/a3_field_circuit_nonlinear/smoke 实测）：
#: 检波器锚 DEFAULT_COMPARE_QUANTITIES 的参考值 + p2 基波相位（正弦参考）。
REAL_NGSPICE_20260914 = {
    "fourier": {
        "out": {
            "dc": 0.715479,
            "harmonics": {1: {"frequency_hz": 1e9, "magnitude": 4.51012e-4, "phase_deg": 227.6}},
        },
        "p2": {
            "dc": -3.6e-3,
            "harmonics": {
                1: {"frequency_hz": 1e9, "magnitude": 1.38795, "phase_deg": -45.408},
                2: {"frequency_hz": 2e9, "magnitude": 0.010771, "phase_deg": 0.0},
                3: {"frequency_hz": 3e9, "magnitude": 0.00540486, "phase_deg": 0.0},
            },
        },
    },
    "meas": {"vdc_out": 0.715479},
}


class TestLSectionStandin:
    def test_reciprocity_and_passivity(self):
        spec = fcn.DetectorSpec()
        freq = np.linspace(0.2e9, 8e9, 201)
        s = fcn.lsection_smatrix(freq, spec)
        assert np.allclose(s[:, 0, 1], s[:, 1, 0])  # 互易
        assert np.all(np.linalg.svd(s, compute_uv=False) <= 1.0 + 1e-12)  # 无源

    def test_dc_limit_textbook(self):
        """DC 极限：L 短路余 ESR、C 开路 → S11=(r/z0)/(2+r/z0)、S21=2/(2+r/z0)。"""
        spec = fcn.DetectorSpec(esr_ohm=0.5, z0_ohm=50.0)
        s = fcn.lsection_smatrix(np.array([1.0]), spec)[0]
        x = spec.esr_ohm / spec.z0_ohm
        assert s[0, 0] == pytest.approx(x / (2 + x))
        assert s[1, 0] == pytest.approx(2 / (2 + x))

    def test_high_frequency_reflection(self):
        """高频极限：串 L 开路/并 C 短路 → |S11|→1、|S21|→0。"""
        spec = fcn.DetectorSpec()
        s = fcn.lsection_smatrix(np.array([40 * spec.f0_hz]), spec)[0]
        assert abs(s[0, 0]) > 0.99
        assert abs(s[1, 0]) < 0.05

    def test_dc_y_admittance_matrix(self):
        """DC 导纳 = 纯 ESR 导纳矩阵（闭式，供 HB 的 k=0 显式行）。"""
        spec = fcn.DetectorSpec(esr_ohm=0.5)
        g = 1.0 / 0.5
        assert np.allclose(fcn.standin_dc_y(spec), [[g, -g], [-g, g]])


class TestTouchstoneBridge:
    def test_roundtrip_y_at_harmonics(self, tmp_path):
        """Touchstone 往返 + 谐波插值 ≈ 直接闭式 s_to_y（密网格插值误差内）。"""
        spec = fcn.DetectorSpec()
        snp = fcn.build_em_standin_touchstone(
            tmp_path / "em.s2p", spec, max_harmonic=9, n_points=6001,
        )
        harmonics = np.array([k * spec.f0_hz for k in range(1, 10)])
        y_net = fcn.y_harmonics_from_touchstone(snp, harmonics, z0_ohm=spec.z0_ohm)
        from rfauto.core.circuit_hb import s_to_y

        y_ref = s_to_y(fcn.lsection_smatrix(harmonics, spec), spec.z0_ohm)
        assert np.allclose(y_net, y_ref, atol=1e-7)

    def test_out_of_band_harmonic_raises(self, tmp_path):
        """谐波出带显式报错（不外推——诚实失败）。"""
        spec = fcn.DetectorSpec()
        snp = fcn.build_em_standin_touchstone(tmp_path / "em.s2p", spec, max_harmonic=9)
        with pytest.raises(ValueError, match="出带"):
            fcn.y_harmonics_from_touchstone(
                snp, np.array([20 * spec.f0_hz]), z0_ohm=spec.z0_ohm,
            )


class TestYVsPhysicalEquivalence:
    def test_em_port_circuit_matches_physical_circuit(self):
        """Y(S) 链 vs 物理 RLC：两条独立导出路径的 HB 解必须一致（≤1e-5）。"""
        spec = fcn.DetectorSpec()
        harmonics = np.array([k * spec.f0_hz for k in range(1, 5)])
        from rfauto.core.circuit_hb import s_to_y

        y_k = s_to_y(fcn.lsection_smatrix(harmonics, spec), spec.z0_ohm)
        hb_circ = fcn.build_hb_circuit(y_k, fcn.standin_dc_y(spec), spec, n_harmonics=4)
        phys_circ, _ = fcn.build_physical_circuit(spec)
        # 两侧同 K 同采样（K 不同 → 投影截断不同，比较无意义）
        phys_circ.n_harmonics = 4
        phys_circ.n_samples = 256
        sol_em = solve_harmonic_balance(hb_circ)
        sol_ph = solve_harmonic_balance(phys_circ)
        # EM 电路 p2=节点3/out=4；物理电路 p2=节点4/out=5
        for k in range(1, 4):
            assert sol_em.node_amplitude(3, k) == pytest.approx(
                sol_ph.node_amplitude(4, k), rel=1e-5,
            )
            assert sol_em.node_amplitude(4, k) == pytest.approx(
                sol_ph.node_amplitude(5, k), rel=1e-5,
            )
        assert sol_em.node_dc(4) == pytest.approx(sol_ph.node_dc(5), rel=1e-5)


class TestComparison:
    def _hb_summary(self):
        spec = fcn.DetectorSpec()
        harmonics = np.array([k * spec.f0_hz for k in range(1, 8)])
        from rfauto.core.circuit_hb import s_to_y

        y_k = s_to_y(fcn.lsection_smatrix(harmonics, spec), spec.z0_ohm)
        sol = solve_harmonic_balance(
            fcn.build_hb_circuit(y_k, fcn.standin_dc_y(spec), spec, n_harmonics=7),
        )
        return fcn.harmonic_summary(sol, dict(enumerate(fcn.HB_NODE_NAMES)))

    def test_compare_pass_with_real_reference(self):
        """HB（确定性）vs 真机 ngspice 实测值：逐量在门限内（回归钉死）。"""
        cmp = fcn.compare_hb_vs_ngspice(self._hb_summary(), REAL_NGSPICE_20260914)
        assert cmp["all_ok"] is True
        rows = {(r["node"], r["harmonic"]): r for r in cmp["quantities"]}
        assert rows[("out", 0)]["rel_err"] < 0.005
        assert rows[("p2", 1)]["rel_err"] < 0.001

    def test_compare_detects_mismatch(self):
        hb = self._hb_summary()
        ref = {
            "fourier": {
                "out": {"dc": 0.5, "harmonics": {}},
                "p2": {"dc": 0.0, "harmonics": {}},
            },
            "meas": {},
        }
        cmp = fcn.compare_hb_vs_ngspice(hb, ref)
        assert cmp["all_ok"] is False
        rows = {(r["node"], r["harmonic"]): r for r in cmp["quantities"]}
        assert rows[("out", 0)]["ok"] is False
        assert rows[("p2", 1)]["status"] == "missing"  # 缺谐波行=诚实缺失不凑绿

    def test_phase_guard_conversion(self):
        """ngspice 相位（正弦参考）换算后与 HB 余弦参考相位互差 <0.1°。"""
        hb = self._hb_summary()
        ref_p2_h1 = REAL_NGSPICE_20260914["fourier"]["p2"]["harmonics"][1]
        cos_ref = -45.408 - 90.0  # 手工换算的余弦参考期望
        from rfauto.adapters.spice_netlist import ngspice_phase_to_cosine

        got = ngspice_phase_to_cosine(ref_p2_h1["phase_deg"])
        assert got == pytest.approx(cos_ref, abs=0.01)
        hb_phase = hb["p2"]["phase_deg_cos"]["1"]
        assert abs((hb_phase - got + 180) % 360 - 180) < 0.1


class TestAnchorPipeline:
    def _runner(self, parsed):
        def run(spec, out_dir, exe=None):
            return {"netlist": "injected", "run": {"errors": []}, "parsed": parsed}

        return run

    def test_pipeline_ok_with_injected_reference(self, tmp_path):
        """端到端管线（注入真机实测参考值）：ok=True + 报告落盘。"""
        summary = fcn.run_field_circuit_nonlinear_anchor(
            tmp_path / "anchor", ngspice_runner=self._runner(REAL_NGSPICE_20260914),
        )
        assert summary["harmonic_balance"]["status"] == "ok"
        assert summary["harmonic_balance"]["k_refine"]["ok"] is True
        assert summary["ngspice"]["status"] == "ok"
        assert summary["comparison"]["all_ok"] is True
        assert summary["ok"] is True
        report = json.loads(
            (tmp_path / "anchor" / "anchor_report.json").read_text(encoding="utf-8"),
        )
        assert report["ok"] is True

    def test_pipeline_flags_missing_reference_signal(self, tmp_path):
        """参考解缺信号（.four 失败类）：管线如实判红，不静默。"""
        broken = {
            "fourier": {"out": REAL_NGSPICE_20260914["fourier"]["out"]},
            "meas": REAL_NGSPICE_20260914["meas"],
        }
        summary = fcn.run_field_circuit_nonlinear_anchor(
            tmp_path / "anchor", ngspice_runner=self._runner(broken),
        )
        assert summary["ok"] is False
        assert any(
            r["status"] == "missing" for r in summary["comparison"]["quantities"]
        )

    def test_em_dc_mode_flagged(self, tmp_path):
        """替身链 DC 模式与 HB 解标注一致（closed_form_standin）。"""
        summary = fcn.run_field_circuit_nonlinear_anchor(
            tmp_path / "anchor", ngspice_runner=self._runner(REAL_NGSPICE_20260914),
        )
        assert summary["em"]["dc_mode"] == "closed_form_standin"
