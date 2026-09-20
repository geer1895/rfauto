"""c3 谐振 Q 时域提取 + S 参数稳态外推内核与判读门单测（零真机）。

① 合成衰减正弦（已知 f0/Q 多模）回收 Q 与稳态幅值；② 截断敏感性（不同截断点外推
稳定；模型外模式在短截断下被置信门如实拦下）；③ c3 归档 107.6ns 部分数据复现
（与 sparams_partial.csv 直接判读互证）。内核=scripts/c3_resonance_q_extract.py，
判读门=scripts/smoke_c3_filter_family.q_extrapolation_gate（阈值 Q_EXTRAP_*）。
"""
from __future__ import annotations

import importlib.util
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

import c3_resonance_q_extract as c3q
from c3_resonance_q_extract import (
    dft_cumsum,
    extract_ring_modes,
    min_duration_s,
    q_extrap_report,
    sparams_windows,
)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 合成两端口序列（模型类与内核尾基完全同构，真值=长序列 DFT）─────────────────
DT_ROW = 45.35e-12                    # 探针行距（c3 归档同量级）
T_EXC = 10e-9
Z0 = 50.0
FC = 2.46e9
SYNTH_MODES = [                       # (f_hz, alpha_per_s, r1, t2, phase_rad)
    (2.40e9, 3.7699e7, 0.30, 0.25, 0.7),
    (2.52e9, 5.2779e7, 0.22, 0.18, 2.1),
]
SYNTH_MODES3 = [*SYNTH_MODES, (2.62e9, 4.2e7, 0.08, 0.06, 4.0)]
ALPHA_SLOW = SYNTH_MODES[0][1]        # τ_slow = 1/α ≈ 26.5ns


def synth_ports(t_end_s: float, modes=SYNTH_MODES):
    """激励脉冲 + 环振多模的两端口 u/i 序列（引擎波分解口径 u=a+b, i=(a−b)/Z0）。

    环振带 1ns 平滑建立窗（谐振器自脉冲连续建立，无人工阶跃点击污染频谱）。
    """
    t = np.arange(0.0, t_end_s, DT_ROW)
    a = np.exp(-((t - T_EXC / 2) / (T_EXC / 5)) ** 2) * np.cos(2 * np.pi * FC * t)

    def ring(amps: list[float]) -> np.ndarray:
        out = np.zeros_like(t)
        for (_f, al, _r1, _t2, ph), amp in zip(modes, amps, strict=True):
            tp = t - T_EXC
            m = tp >= 0
            fade = 1.0 - np.exp(-tp[m] / 1e-9)
            out[m] += (amp * fade * np.exp(-al * tp[m])
                       * np.cos(2 * np.pi * _f * tp[m] + ph))
        return out

    b1 = ring([m[2] for m in modes])
    b2 = ring([m[3] for m in modes])
    probes = {1: (a + b1, (a - b1) / Z0), 2: (b2, -b2 / Z0)}
    return t, probes


def truth_s21(freq_hz: np.ndarray, modes=SYNTH_MODES) -> np.ndarray:
    """真值参考：环振跑到 12τ_slow 的长合成全窗 DFT（尾项 <1e-4 可忽略）。"""
    t, probes = synth_ports(T_EXC + 12.0 / ALPHA_SLOW, modes)
    sw = sparams_windows(t, probes, freq_hz, [None], z0=Z0)
    return sw["s21"][0]


FREQ = np.linspace(2.3e9, 2.6e9, 301)


# ── 内核微面 ───────────────────────────────────────────────────────────────────

class TestKernelPrimitives:
    def test_dft_cumsum_matches_direct_and_engine_convention(self):
        t = np.arange(64) * 1e-12
        v = np.cos(2 * np.pi * 1e9 * t)
        freq = np.array([1e9, 2e9])
        c = dft_cumsum(t, v, freq)
        for n_end in (20, 64):
            direct = np.array([
                2.0 * (t[1] - t[0]) * np.sum(v[:n_end]
                                             * np.exp(-1j * 2 * np.pi * f * t[:n_end]))
                for f in freq])
            assert np.allclose(c[n_end - 1], direct, rtol=1e-12, atol=1e-15)

    def test_min_duration_s_analytic_single_mode(self):
        alpha = 4e7
        modes = [{"f0_hz": 2.45e9, "alpha_per_s": alpha}]
        c_row = np.array([5e-2 + 0j])
        s_inf = 0.5 + 0j
        tol = 0.05
        t_req = min_duration_s(s_inf, c_row, modes, 2.45e9, tol, 1e-8, 1e-7)
        assert t_req == pytest.approx(np.log(5e-2 / (tol * 0.5)) / alpha, rel=2e-3)

    def test_extract_rejects_bad_inputs(self):
        t = np.arange(100) * DT_ROW
        with pytest.raises(ValueError):
            extract_ring_modes(t, np.zeros(100), 2.3e9, 2.6e9, 2e-9)
        with pytest.raises(ValueError):
            c3q.sparams_windows(t, {}, FREQ, [None])


# ── ① 合成回收：Q 与稳态幅值 ───────────────────────────────────────────────────

class TestSyntheticRecovery:
    @pytest.fixture(scope="class")
    def short_report(self):
        t, probes = synth_ports(T_EXC + 4.0 / ALPHA_SLOW)
        modes = extract_ring_modes(t, probes[1][0], FREQ[0], FREQ[-1], T_EXC)
        return q_extrap_report(t, probes, FREQ, modes, T_EXC,
                               f_design_hz=FC, z0=Z0), modes

    def test_mode_recovery(self, short_report):
        _rep, modes = short_report
        assert len(modes) == len(SYNTH_MODES)
        for f_true, a_true, *_ in SYNTH_MODES:
            near = min(modes, key=lambda m: abs(float(m["f0_hz"]) - f_true))
            assert abs(float(near["f0_hz"]) - f_true) / f_true < 5e-3
            assert abs(float(near["alpha_per_s"]) - a_true) / a_true < 4e-2
            q_rec = float(near["q_loaded"])
            assert q_rec == pytest.approx(np.pi * f_true / a_true, rel=4e-2)
        assert all(m["span_db"] > 20.0 for m in modes)

    def test_steady_state_matches_long_truth(self, short_report):
        rep, _modes = short_report
        truth = 20 * np.log10(np.abs(truth_s21(FREQ)) + 1e-300)
        keys = rep["keys"]
        for key in ("s21_peak", "s21_f0"):
            f_hz = float(keys[key]["freq_hz"])
            i = int(np.argmin(np.abs(FREQ - f_hz)))
            assert float(keys[key]["s_inf_db"]) == pytest.approx(float(truth[i]),
                                                                 abs=0.15)
        assert abs(float(keys["s21_peak"]["dev_db"])) < 1.0

    def test_confidence_gate_passes_with_smoke_thresholds(self, short_report):
        smoke = _load_script("smoke_c3_filter_family")
        rep, _modes = short_report
        gate = smoke.q_extrapolation_gate(rep)
        assert gate["ok"] is True
        assert gate["value"] <= smoke.Q_EXTRAP_DEV_DB_MAX


# ── ② 截断敏感性：外推稳定性 + 模型外模式短截断被拦 ────────────────────────────

class TestTruncationSensitivity:
    @pytest.fixture(scope="class")
    def truth(self):
        return 20 * np.log10(np.abs(truth_s21(FREQ)) + 1e-300)

    def _matched_report_at(self, tau_multiple: float):
        """模型匹配（2 模合成 + n_modes=2）的截断敏感性面。"""
        t, probes = synth_ports(T_EXC + tau_multiple / ALPHA_SLOW)
        modes = extract_ring_modes(t, probes[1][0], FREQ[0], FREQ[-1], T_EXC)
        return q_extrap_report(t, probes, FREQ, modes, T_EXC, f_design_hz=FC, z0=Z0)

    def _mismatched_report_at(self, tau_multiple: float, n_modes: int = 2):
        """3 模合成、只给 n_modes 个模式（模型失配面）。"""
        t, probes = synth_ports(T_EXC + tau_multiple / ALPHA_SLOW, SYNTH_MODES3)
        modes = extract_ring_modes(t, probes[1][0], FREQ[0], FREQ[-1], T_EXC,
                                   n_modes=n_modes)
        return q_extrap_report(t, probes, FREQ, modes, T_EXC, f_design_hz=FC, z0=Z0)

    def test_extrapolation_stable_across_truncations(self, truth):
        s_inf_dbs = []
        for k in (3.0, 5.0):
            rep = self._matched_report_at(k)
            pk = rep["keys"]["s21_peak"]
            i = int(np.argmin(np.abs(FREQ - float(pk["freq_hz"]))))
            assert float(pk["s_inf_db"]) == pytest.approx(float(truth[i]), abs=0.15)
            s_inf_dbs.append(float(pk["s_inf_db"]))
        assert abs(s_inf_dbs[0] - s_inf_dbs[1]) <= 0.15

    def test_gate_rejects_early_stop_with_unmodelled_mode(self):
        smoke = _load_script("smoke_c3_filter_family")
        # 短截断（1.5τ）+ 第 3 模在模型外：dev/holdout/span 至少一面如实判红
        rep_short = self._mismatched_report_at(1.5)
        gate_short = smoke.q_extrapolation_gate(rep_short)
        assert gate_short["ok"] is False
        assert gate_short["reason"]
        # 长截断（5τ）后模型外模式尾项已死：同门如实放行
        rep_long = self._mismatched_report_at(5.0)
        gate_long = smoke.q_extrapolation_gate(rep_long)
        assert gate_long["ok"] is True

    def test_n_windows_guard(self):
        t, probes = synth_ports(T_EXC + 4.0 / ALPHA_SLOW)
        modes = extract_ring_modes(t, probes[1][0], FREQ[0], FREQ[-1], T_EXC)
        with pytest.raises(ValueError):
            q_extrap_report(t, probes, FREQ, modes, T_EXC, f_design_hz=FC,
                            n_windows=5)


# ── ③ c3 归档复现（107.6ns 部分数据 vs sparams_partial.csv 直接判读互证）───────

ARCHIVE = REPO / "runs" / "smoke_c3_refix" / "interdigital"
ARCHIVE_FDTD = ARCHIVE / "fdtd_partial"


@pytest.mark.skipif(not ARCHIVE_FDTD.exists(), reason="c3 归档不在本工作区")
class TestArchiveReproduction:
    @pytest.fixture(scope="class")
    def rep(self):
        probes_all = c3q.load_msl_probes(str(ARCHIVE_FDTD))
        t = probes_all[1][0]
        probes = {k: (u, i) for k, (_tt, u, i) in probes_all.items()}
        modes = extract_ring_modes(t, probes[1][0], 2.25e9, 2.75e9, 1.14593e-8)
        return q_extrap_report(t, probes, np.linspace(2.25e9, 2.75e9, 401), modes,
                               1.14593e-8, f_design_hz=2.5e9)

    def test_truncated_sparams_match_engine_csv(self):
        """内核截断态 S 与 extract_partial.py（引擎 CalcPort 链）互证。"""
        import csv

        with open(ARCHIVE / "sparams_partial.csv", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        arr = np.array([[float(x) for x in r[:5]] for r in rows[1:]])
        s21_csv = arr[:, 3] + 1j * arr[:, 4]
        probes_all = c3q.load_msl_probes(str(ARCHIVE_FDTD))
        t = probes_all[1][0]
        probes = {k: (u, i) for k, (_tt, u, i) in probes_all.items()}
        sw = sparams_windows(t, probes, arr[:, 0], [None], z0=50.0)
        d = np.abs(20 * np.log10(np.abs(sw["s21"][0]) + 1e-300)
                   - 20 * np.log10(np.abs(s21_csv) + 1e-300))
        assert float(np.max(d)) <= 0.05

    def test_ring_modes_quantify_devlog_235_slow_tail(self, rep):
        """#323 的 12× 慢衰减谜题定量闭合：环振模 Q≈96-263（弱负载，远高于设计
        有载 Q），带心模频率与截断 S21 峰位一致到 0.01%。"""
        modes = rep["modes"]
        assert len(modes) == 3
        center = [m for m in modes if 2.40e9 < m["f0_ghz"] * 1e9 < 2.50e9]
        assert len(center) == 1
        m = center[0]
        assert m["f0_ghz"] * 1e9 == pytest.approx(rep["f_peak_hz"], rel=1e-4)
        assert 80.0 <= m["q_loaded"] <= 300.0
        assert all(mm["span_db"] > 20.0 for mm in modes)

    def test_steady_vs_truncated_and_crosscheck_numbers(self, rep):
        """带心 2.4525GHz：截断 S21 峰 −5.81dB（partial_meta 同源）；外推稳态
        −5.77dB（dev 0.036dB）；holdout 2.5e-4；T_req(带心±5%)≈52ns 已满足。"""
        pk = rep["keys"]["s21_peak"]
        assert pk["freq_hz"] == pytest.approx(2.4525e9, abs=1e4)
        assert pk["s_trunc_db"] == pytest.approx(-5.806, abs=0.02)
        assert pk["s_inf_db"] == pytest.approx(-5.77, abs=0.05)
        assert abs(float(pk["dev_db"])) == pytest.approx(0.036, abs=0.02)
        assert float(pk["holdout_rel"]) < 0.05
        assert float(pk["resid_rel"]) < 0.01
        assert pk["min_duration_satisfied"] is True
        assert pk["min_duration_s"] == pytest.approx(52.1e-9, rel=0.1)
        assert rep["excitation_covered_by_data"] is True

    def test_archive_gate_passes_and_judge_flips_verdict(self, rep):
        smoke = _load_script("smoke_c3_filter_family")
        gate = smoke.q_extrapolation_gate(rep)
        assert gate["ok"] is True
        assert gate["thresholds"] == {
            "dev_db_max": smoke.Q_EXTRAP_DEV_DB_MAX,
            "holdout_rel_max": smoke.Q_EXTRAP_HOLDOUT_REL_MAX,
            "span_db_min": smoke.Q_EXTRAP_SPAN_DB_MIN}
        # judge 接线：能量未收敛（触顶 −46dB）+ Q 外推置信 → FAIL 翻 PASS
        from rfauto.adapters import openems_templates as ot

        freqs = np.linspace(2.0, 3.0, 4001)
        nom = dict(ot.TEMPLATE_NOMINAL["interdigital"])
        # NOMINAL 为过孔补偿口径 → 合成响应取过孔裁判带心回 F0
        s = ot.c3_circuit_sparams("interdigital", freqs, nom, l_via_h=None)
        s11 = s[:, 0, 0]
        s21 = s[:, 1, 0] * 10 ** (-0.5 / 20)
        circ_db = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
        eng_bad = {"nrts": 1000000, "iterations_done": 1000000,
                   "hit_nrts_limit": True, "excitation_covered": True,
                   "min_energy_db": -46.0}
        _g0, v0, _m0 = smoke.judge(freqs, s11, s21, circ_db, float("nan"), eng_bad)
        assert v0 == "FAIL"
        gates, verdict, _m = smoke.judge(freqs, s11, s21, circ_db, float("nan"),
                                         eng_bad, q_extrap=rep)
        assert gates["nrts_converged"]["ok"] is False          # 能量门如实仍红
        assert gates["q_extrap_confident"]["ok"] is True
        assert verdict == "PASS"

    def test_judge_error_report_and_backcompat(self, rep):
        """坏报告如实不过；能量门自身已过时坏报告不改变结局（回归钉）。"""
        smoke = _load_script("smoke_c3_filter_family")
        from rfauto.adapters import openems_templates as ot

        freqs = np.linspace(2.0, 3.0, 4001)
        nom = dict(ot.TEMPLATE_NOMINAL["interdigital"])
        # NOMINAL 为过孔补偿口径 → 合成响应取过孔裁判带心回 F0
        s = ot.c3_circuit_sparams("interdigital", freqs, nom, l_via_h=None)
        s21 = s[:, 1, 0] * 10 ** (-0.5 / 20)
        circ_db = 20.0 * np.log10(np.abs(s[:, 1, 0]) + 1e-12)
        eng_ok = {"nrts": 1000000, "iterations_done": 700000,
                  "hit_nrts_limit": False, "excitation_covered": True,
                  "min_energy_db": -60.1}
        _g, v_ok, _m = smoke.judge(freqs, s[:, 0, 0], s21, circ_db,
                                   float("nan"), eng_ok)
        assert v_ok == "PASS"
        gates_err, v_err, _m1 = smoke.judge(freqs, s[:, 0, 0], s21, circ_db,
                                            float("nan"), eng_ok,
                                            q_extrap={"error": "boom"})
        assert v_err == "PASS"          # 能量门自身已过，坏报告不改变结局
        assert gates_err["q_extrap_confident"]["ok"] is False
        eng_bad = dict(eng_ok, iterations_done=1000000, hit_nrts_limit=True,
                       min_energy_db=-46.0)
        _g2, v_bad, _m2 = smoke.judge(freqs, s[:, 0, 0], s21, circ_db,
                                      float("nan"), eng_bad,
                                      q_extrap={"error": "boom"})
        assert v_bad == "FAIL"

    def test_main_wiring_helpers(self, tmp_path):
        """main() 接线薄壳：开关关=不介入；探针/日志缺失=error 形态（判读如实不过）。"""
        smoke = _load_script("smoke_c3_filter_family")
        import argparse

        args = argparse.Namespace(q_extrap=False, flo=2.25, fhi=2.75)
        eng = {"excitation_s": 1.14593e-8}
        assert smoke._q_extrap_for(tmp_path, eng, args) is None      # 开关关
        args_on = argparse.Namespace(q_extrap=True, flo=2.25, fhi=2.75)
        assert "error" in smoke._q_extrap_for(tmp_path, eng, args_on)  # 无探针目录
        pdir = tmp_path / "fdtd"
        pdir.mkdir()
        for suffix in ("1A", "1B", "1C", "2A", "2B", "2C"):
            (pdir / f"port_ut_{suffix}").write_text("% t/s\tvoltage\n0 0\n",
                                                    encoding="utf-8")
        rep = smoke._q_extrap_for(tmp_path, {}, args_on)             # 无 excitation_s
        assert "error" in rep and "excitation_s" in rep["error"]
        rep2 = smoke._q_extrap_for(tmp_path, eng, args_on)           # 探针过短
        assert "error" in rep2
        assert smoke._probe_dir(tmp_path) == pdir                    # fdtd/ 优先解析
