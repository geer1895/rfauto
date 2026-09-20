"""C3 滤波器族 II 三项收紧的离线单测（零真机、零网络）。

① 耦合缝网格守卫（#266）：render_script 对 interdigital/combline/sir_bpf 断言
   NEAR=base/4 ≤ 最小耦合缝/3，违反即 ValueError（不许静默粗网格）；
② NrTS/EndCriteria 收敛判读门：scripts/smoke_c3_filter_family.judge 在引擎触
   NrTS 上限且能量未达判据时判 FAIL（真机 −46/−29dB 触顶实证）；
③ 过孔电感进裁判：Goldfarb-Pucel 1991 闭式 L=(μ0/2π)·h·[ln(4h/d)+1] 端接
   短路端，c3_circuit_sparams(l_via_h=None) 自动取几何值；缺省 0.0 逐位复现
   理想短路旧口径。数值锚：|Y| 数值极小化 vs 闭式谐振条件 tanθ=Z_r/(ωL)
   （#118 独立裁判，非自证）。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.adapters import openems_templates as ot

BAND = (2.25, 2.75)
H_MM = 0.508
# 缺省 mesh=0 → base=λ_sub/50@2.75GHz=1.1405mm、NEAR=0.2851mm（真机实测）
NEAR_DEFAULT_MM = 3e8 / (2.75e9 * math.sqrt(3.66)) / 50 / 4 * 1e3


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def freqs() -> np.ndarray:
    return np.linspace(2.0, 3.0, 4001)


@pytest.fixture(scope="module")
def smoke():
    return _load_script("smoke_c3_filter_family")


def _band_center_ghz(f: np.ndarray, s: np.ndarray) -> float:
    s21 = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-300)
    above = f[s21 > -3.0]
    return 0.5 * (float(above.min()) + float(above.max()))


# ─── ③ 过孔电感内核 ────────────────────────────────────────────────────────────

class TestViaInductanceKernel:
    def test_goldfarb_pucel_si_matches_mil_form(self):
        # 工程式 L[nH]=5.08e-3·h[mil]·[ln(4h/d)+1]（Goldfarb-Pucel 1991）
        h_mm, d_mm = H_MM, 2.0 * ot._C3_R_VIA_MM
        h_mil, d_mil = h_mm / 0.0254, d_mm / 0.0254
        l_mil = 5.08e-3 * h_mil * (math.log(4.0 * h_mil / d_mil) + 1.0) * 1e-9
        l_si = ot.via_inductance_h(h_mm * 1e-3, d_mm * 1e-3)
        assert l_si == pytest.approx(l_mil, rel=1e-9)
        assert l_si == pytest.approx(2.9596e-10, rel=1e-4)        # 0.296 nH
        assert ot.c3_via_inductance_h(H_MM) == l_si

    def test_kernel_validation(self):
        with pytest.raises(ValueError):
            ot.via_inductance_h(0.0, 3e-4)
        with pytest.raises(ValueError):
            ot.via_inductance_h(5e-4, -1.0)
        with pytest.raises(ValueError):
            ot.c3_y_shorted_stub(2.5, 2.8, 17.7, 50.0, l_via_h=-1e-10)
        with pytest.raises(ValueError):
            ot.c3_y_sir(2.5, 2.9, 6.8, 35.0, 2.6, 7.1, 70.0, l_via_h=-1e-10)

    def test_zero_inductance_is_bitwise_legacy(self):
        z_r, ere = ot._c3_single_line(1.1117, 2.5, 3.66, H_MM)
        for f in (2.3, 2.5, 2.7):
            legacy = -1j / math.tan(ot._c3_theta(f, ere, 17.7)) / z_r
            assert ot.c3_y_shorted_stub(f, ere, 17.7, z_r) == legacy
            assert ot.c3_y_shorted_stub(f, ere, 17.7, z_r, 0.0) == legacy
            assert ot.c3_y_combline(f, ere, 8.87, z_r, 1.27e-12, 0.0) == \
                ot.c3_y_combline(f, ere, 8.87, z_r, 1.27e-12)
            assert ot.c3_y_sir(f, 2.9, 6.8, 35.0, 2.6, 7.1, 70.0, 0.0) == \
                ot.c3_y_sir(f, 2.9, 6.8, 35.0, 2.6, 7.1, 70.0)

    def test_via_loaded_stub_resonance_matches_closed_form_root(self):
        """#118：|Y(f)| 数值极小化定位谐振 vs 闭式条件 Z_r−ωL·tanθ=0 的二分根。"""
        lv = ot.c3_via_inductance_h(H_MM)
        z_r, ere = ot._c3_single_line(1.1117, 2.5, 3.66, H_MM)
        l_eff = 17.5252 + ot._open_end_delta_mm(1.1117, 2.5, 3.66, H_MM)
        fg = np.linspace(2.2, 2.6, 200001)
        y = np.array([abs(ot.c3_y_shorted_stub(f, ere, l_eff, z_r, lv)) for f in fg])
        f_num = float(fg[int(np.argmin(y))])

        def g(f: float) -> float:
            return z_r - 2 * math.pi * f * 1e9 * lv * math.tan(ot._c3_theta(f, ere, l_eff))

        lo, hi = 2.2, 2.499
        for _ in range(100):
            mid = 0.5 * (lo + hi)
            if g(lo) * g(mid) <= 0:
                hi = mid
            else:
                lo = mid
        f_root = 0.5 * (lo + hi)
        assert f_num == pytest.approx(f_root, abs=3e-6)
        # 名义 λ/4 棒（理想短路谐振 2.5GHz）经 0.296nH 过孔下移 ≈5.6%
        assert f_root / 2.5 - 1.0 == pytest.approx(-0.0558, abs=0.001)
        # 谐振点导纳恰为 0（分母为零分支返回 0j，不抛错）
        assert abs(ot.c3_y_shorted_stub(f_root, ere, l_eff, z_r, lv)) < 1e-6

    def test_sir_via_reduces_to_ideal_as_inductance_vanishes(self):
        args = (2.45, 2.9, 6.8, 35.0, 2.6, 7.1, 70.0)
        y0 = ot.c3_y_sir(*args)
        # 谐振区 Y≈0 对 L 灵敏（1e-15H 即 rel 5e-6）：取 1e-18H 验连续性
        y_small = ot.c3_y_sir(*args, l_via_h=1e-18)
        assert y_small == pytest.approx(y0, rel=1e-6)
        y_via = ot.c3_y_sir(*args, l_via_h=ot.c3_via_inductance_h(H_MM))
        assert y_via != y0


class TestCircuitJudgeViaInductance:
    @pytest.mark.parametrize("template", ot.C3_TEMPLATES)
    def test_default_is_ideal_short_and_auto_equals_geometry(self, template, freqs):
        nom = dict(ot.TEMPLATE_NOMINAL[template])
        s_def = ot.c3_circuit_sparams(template, freqs, nom)
        s_zero = ot.c3_circuit_sparams(template, freqs, nom, l_via_h=0.0)
        assert np.array_equal(s_def, s_zero)
        s_auto = ot.c3_circuit_sparams(template, freqs, nom, l_via_h=None)
        s_expl = ot.c3_circuit_sparams(template, freqs, nom,
                                       l_via_h=ot.c3_via_inductance_h(H_MM))
        assert np.array_equal(s_auto, s_expl)
        assert not np.array_equal(s_auto, s_def)
        with pytest.raises(ValueError):
            ot.c3_circuit_sparams(template, freqs, nom, l_via_h=-1e-10)

    @pytest.mark.parametrize("template,ideal_up_pct,auto_off_pct", [
        ("interdigital", 6.275, 0.000), ("combline", 7.970, 0.070),
        ("sir_bpf", 5.800, 0.035),
    ])
    def test_compensated_nominal_resonates_at_f0(self, template, ideal_up_pct,
                                                 auto_off_pct, freqs):
        """过孔补偿口径：NOMINAL 已按设计链 l_via_h=None 再生（棒长按谐
        振条件精确解缩短）——过孔裁判（l_via_h=None）带心回 f0（|偏移|≤0.1%）；
        理想短路裁判同几何则上移 5.8~8.0%（与补偿前 −5.58/−6.64/−5.06% 下移
        同源反号，真机峰位 −4.6~−5.15% 即该量的 EM 实证）；
        无耗/互易/回文对称由构造保持。"""
        nom = dict(ot.TEMPLATE_NOMINAL[template])
        s0 = ot.c3_circuit_sparams(template, freqs, nom)
        s1 = ot.c3_circuit_sparams(template, freqs, nom, l_via_h=None)
        bc_ideal = _band_center_ghz(freqs, s0)
        bc_auto = _band_center_ghz(freqs, s1)
        assert (bc_auto / 2.5 - 1.0) * 100.0 == pytest.approx(auto_off_pct, abs=0.05)
        assert (bc_ideal / 2.5 - 1.0) * 100.0 == pytest.approx(ideal_up_pct, abs=0.05)
        shift = (bc_auto / bc_ideal - 1.0) * 100.0
        assert -8.0 < shift < -3.0
        p = np.abs(s1[:, 0, 0]) ** 2 + np.abs(s1[:, 1, 0]) ** 2
        assert float(np.max(np.abs(p - 1.0))) < 1e-9
        assert float(np.max(np.abs(s1[:, 0, 1] - s1[:, 1, 0]))) < 1e-9
        assert float(np.max(np.abs(s1[:, 0, 0] - s1[:, 1, 1]))) < 1e-9

    def test_synchronous_tem_path_accepts_via(self, freqs):
        design = ot.interdigital_design_from_order(3, 2.5, 0.05, 20.0)
        s0 = ot.c3_circuit_sparams("interdigital", freqs, {}, synchronous_tem=True,
                                   design=design)
        s1 = ot.c3_circuit_sparams("interdigital", freqs, {}, synchronous_tem=True,
                                   design=design, l_via_h=None)
        assert _band_center_ghz(freqs, s1) < _band_center_ghz(freqs, s0)

    def test_fake_channel_default_ideal_and_via_opt_in(self, freqs):
        """fake 同源通道缺省=理想短路（保守判定：显式旧几何黄金钉保持，
        逐位复现旧名义）；过孔裁判经 l_via_h（"auto"/数值 H）显式开启，与
        c3_circuit_sparams 同口径逐位一致。"""
        from rfauto.adapters.fake_adapter import _c3_sparams

        nom = dict(ot.TEMPLATE_NOMINAL["combline"])
        assert np.array_equal(_c3_sparams(freqs, "combline", nom, f0_ghz=2.5),
                              ot.c3_circuit_sparams("combline", freqs, nom, f0_ghz=2.5))
        s_auto = _c3_sparams(freqs, "combline", nom, f0_ghz=2.5, l_via_h=None)
        assert np.array_equal(
            s_auto, ot.c3_circuit_sparams("combline", freqs, nom, f0_ghz=2.5,
                                          l_via_h=None))
        assert not np.array_equal(s_auto, _c3_sparams(freqs, "combline", nom,
                                                      f0_ghz=2.5))
        # 过孔裁判下再生名义带心回 f0（fake=EM 同期望，补偿闭环）
        s21 = 20.0 * np.log10(np.abs(s_auto[:, 1, 0]) + 1e-300)
        above = freqs[s21 > -3.0]
        assert 0.5 * (float(above.min()) + float(above.max())) == pytest.approx(
            2.5, abs=0.0025)


# ─── ① 耦合缝网格守卫 ──────────────────────────────────────────────────────────

class TestGapMeshGuard:
    @pytest.mark.parametrize("template,expected_max", [
        ("interdigital", 4.0 * 0.2263 / 3.0), ("combline", 4.0 * 0.1393 / 3.0),
        ("sir_bpf", 4.0 * 0.2417 / 3.0),
    ])
    def test_mesh_max_from_min_gap(self, template, expected_max):
        nom = dict(ot.TEMPLATE_NOMINAL[template])
        assert ot.c3_mesh_max_mm(template, nom) == pytest.approx(expected_max, rel=1e-12)
        info = ot.c3_gap_mesh_guard(template, nom, expected_max * 1e-3 / 4.0)
        assert info["min_gap_mm"] == pytest.approx(min(nom["gaps_mm"]))
        assert info["near_max_mm"] == pytest.approx(min(nom["gaps_mm"]) / 3.0)
        assert info["mesh_max_mm"] == pytest.approx(expected_max)

    @pytest.mark.parametrize("template", ot.C3_TEMPLATES)
    def test_default_mesh_raises_and_boundary_passes(self, template):
        nom = dict(ot.TEMPLATE_NOMINAL[template])
        # 缺省 mesh=0（λ_sub/50 → NEAR 0.285mm）：三模板外缝 0.139~0.242mm 全部违反
        assert min(nom["gaps_mm"]) / 3.0 < NEAR_DEFAULT_MM
        with pytest.raises(ValueError) as ei:
            ot.render_script(template, nom, BAND)
        msg = str(ei.value)
        assert "#266" in msg and "mesh_resolution_mm ≤" in msg
        assert f"{min(nom['gaps_mm']):.4f}" in msg
        mesh_max = ot.c3_mesh_max_mm(template, nom)
        text = ot.render_script(template, nom, BAND, mesh_resolution_mm=mesh_max)
        compile(text, "c3_guard_ok", "exec")
        assert "FDTD.Run(" in text
        with pytest.raises(ValueError):
            ot.render_script(template, nom, BAND, mesh_resolution_mm=mesh_max * 1.01)

    def test_guard_scales_with_gaps(self):
        nom = dict(ot.TEMPLATE_NOMINAL["combline"])
        wide = dict(nom, gaps_mm=[v * 8.0 for v in nom["gaps_mm"]])
        # 缝 ×8 → 最小缝 1.114mm → mesh_max 1.486 > 缺省 base 1.14 → 缺省网格合规
        assert ot.c3_mesh_max_mm("combline", wide) > 4.0 * NEAR_DEFAULT_MM
        compile(ot.render_script("combline", wide, BAND), "c3_wide", "exec")
        with pytest.raises(ValueError):
            ot.c3_gap_mesh_guard("patch", {}, 1e-4)
        with pytest.raises(ValueError):
            ot.c3_gap_mesh_guard("combline", dict(nom, gaps_mm=[0.1, 0.9, 0.9]), 1e-5)


# ─── ② 收敛判读门（判读器 = scripts/smoke_c3_filter_family.judge）──────────────

class TestConvergenceGate:
    def test_defaults(self, smoke):
        assert smoke.NRTS_DEFAULT == 1000000
        assert smoke.DEFAULT_END_CRITERIA_DB == -60.0      # openEMS EndCriteria=1e-6

    def test_devlog_205_ceiling_is_not_converged(self, smoke):
        # 旧轮：NrTS 400k 触顶，能量仅 −46/−29dB（interdigital/combline）
        for e_db in (-46.0, -29.0):
            eng = {"nrts": 400000, "iterations_done": 400000, "hit_nrts_limit": True,
                   "excitation_covered": True, "min_energy_db": e_db,
                   "last_energy_db": e_db, "nrts_limit_warning": False}
            conv = smoke.nrts_convergence(eng)
            assert conv["converged"] is False
            assert conv["end_criteria_db"] == -60.0 and conv["min_energy_db"] == e_db
        # 引擎显式告警行 → 未收敛（能量再低也不采信引擎自述之外的推断）
        warn = {"nrts": 400000, "iterations_done": 400000, "hit_nrts_limit": True,
                "nrts_limit_warning": True, "end_criteria_db": -60.0,
                "min_energy_db": -59.0}
        assert smoke.nrts_convergence(warn)["converged"] is False

    def test_converged_forms(self, smoke):
        early = {"nrts": 1000000, "iterations_done": 612000, "hit_nrts_limit": False,
                 "min_energy_db": -60.3}
        assert smoke.nrts_convergence(early)["converged"] is True
        # 触顶但能量已达判据（探针日志拼接形态）
        hit_ok = {"nrts": 400000, "iterations_done": 400000, "hit_nrts_limit": True,
                  "nrts_limit_warning": False, "min_energy_db": -78.52}
        assert smoke.nrts_convergence(hit_ok)["converged"] is True
        # 显式 EndCriteria 改写：判据 −50dB 下 −55dB 触顶亦收敛
        custom = {"nrts": 400000, "iterations_done": 400000, "hit_nrts_limit": True,
                  "nrts_limit_warning": False, "min_energy_db": -55.0,
                  "end_criteria_db": -50.0}
        assert smoke.nrts_convergence(custom)["converged"] is True
        # 终止信息缺失 → 不可证明收敛
        assert smoke.nrts_convergence({})["converged"] is False

    def test_judge_fails_when_unconverged_even_if_gates_pass(self, smoke, freqs):
        """用裁判自身响应（带心 F0、叠 −0.5dB 均匀损耗落进 IL 门）冒充 EM：五门+
        无源全过，仅收敛门翻转 verdict PASS→FAIL。NOMINAL 为过孔补偿
        口径，合成响应取过孔裁判（l_via_h=None）带心回 F0。"""
        nom = dict(ot.TEMPLATE_NOMINAL["interdigital"])
        s = ot.c3_circuit_sparams("interdigital", freqs, nom, l_via_h=None)
        s11, s21 = s[:, 0, 0], s[:, 1, 0] * 10 ** (-0.5 / 20)
        circ_db = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
        eng_ok = {"nrts": 1000000, "iterations_done": 700000, "hit_nrts_limit": False,
                  "excitation_covered": True, "min_energy_db": -60.1}
        gates, verdict, _metrics = smoke.judge(freqs, s11, s21, circ_db,
                                               float("nan"), eng_ok)
        assert gates["nrts_converged"]["ok"] is True
        assert gates["peak_vs_circuit_pct"]["value"] == 0.0
        assert all(g["ok"] for g in gates.values()), gates
        assert verdict == "PASS"
        eng_bad = dict(eng_ok, iterations_done=1000000, hit_nrts_limit=True,
                       min_energy_db=-46.0)
        gates2, verdict2, _ = smoke.judge(freqs, s11, s21, circ_db,
                                          float("nan"), eng_bad)
        assert gates2["nrts_converged"]["ok"] is False
        assert "未达" in str(gates2["nrts_converged"]["reason"])
        assert all(v["ok"] for k, v in gates2.items() if k != "nrts_converged")
        assert verdict2 == "FAIL"

    def test_auto_mesh_respects_guard(self, smoke):
        for t in ot.C3_TEMPLATES:
            nom = dict(ot.TEMPLATE_NOMINAL[t])
            m = smoke.auto_mesh_mm(t, nom)
            assert m <= ot.c3_mesh_max_mm(t, nom)
            assert m == pytest.approx(math.floor(ot.c3_mesh_max_mm(t, nom) * 1000) / 1000)
            compile(ot.render_script(t, nom, BAND, mesh_resolution_mm=m), "auto", "exec")
        assert smoke.auto_mesh_mm("combline", dict(ot.TEMPLATE_NOMINAL["combline"])) == 0.185
