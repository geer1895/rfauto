"""oe_phase3 三期发射编排驱动测试（wf:oe-phase3-prep，全离线零仿真零发射）。

覆盖面：①判据窗/席位表完整性（预声明单源）；②脉冲长度标定锚（引擎两日志
口径）+NrTS 计划；③HJ 逆根同源回收（#118 换算正确性钉，模型正确性锚在
test_ring_resonator_template）；④合成 S21/S11 判读判定表（含 #281 夹持/
退化谱/无源性违规）；⑤sparams 列解析；⑥criteria 快照 JSON 可序列化；
⑦名义单源核对（真实 docs meta.yaml）；⑧ring 预飞 exec 审计（#212 口径
真实渲染一次，秒级）；⑨--help dry-call + judge-only 空目录稳态；
⑩席位策略门合成 run 判读（review_slice6 P2-2：must_converge 降级/
record_only 留痕/ok=None 不动状态）+ P2-1 S21 缺测降 PARTIAL +
P1-1 引擎日志落盘端到端。
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
DRIVER = SCRIPTS / "oe_phase3_campaign.py"


def _load_driver():
    spec = importlib.util.spec_from_file_location(
        "oe_phase3_campaign", DRIVER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("oe_phase3_campaign", mod)
    spec.loader.exec_module(mod)
    return mod


drv = _load_driver()


# ── ① 席位表/判据窗（预声明完整性）────────────────────────────────────────
class TestSeatTable:
    def test_three_targets_exact(self):
        assert list(drv.SEATS) == [
            "ring_resonator", "pyramid_horn", "coax_waveguide_transition"]
        assert list(drv.SEATS) == drv.TARGETS

    def test_seat_fields_present(self):
        for name, seat in drv.SEATS.items():
            lo, hi = seat["band_ghz"]
            assert 0 < lo < hi, name
            assert seat["mesh_mm"] > 0, name
            assert seat["window_ns"] > 0, name
            assert seat["nrts_policy"] in ("record_only", "must_converge"), name
            assert seat["excite_port"] >= 1, name

    def test_criteria_windows_declared(self):
        # ring：四窗一地板一一致性（模块头预声明的常量化）
        assert drv.RING["f1_win_ghz"] == (2.40, 2.60)
        assert drv.RING["f2_win_ghz"] == (4.75, 5.25)
        assert drv.RING["eps_r_win"][0] < 3.66 < drv.RING["eps_r_win"][1]
        assert drv.RING["s21_peak_min"] > 0
        assert drv.RING["eps_r_diff_max"] > 0
        # horn/transition：S11 门全负 dB、S21 插损下限
        assert drv.HORN["s11_f0_max_db"] < 0 and drv.HORN["core_max_db"] < 0
        assert drv.COAX["s11_f0_max_db"] < drv.COAX["core_max_db"] < 0
        assert drv.COAX["s21_f0_min_db"] < 0

    def test_criteria_snapshot_json_serializable(self, tmp_path):
        for t in drv.TARGETS:
            crit = drv.build_criteria(t)
            payload = json.dumps(crit, ensure_ascii=False, default=str)
            assert "首跑定标" in payload or "record_only" in payload \
                or "must_converge" in payload, t
            assert crit["nrts_policy"] == drv.SEATS[t]["nrts_policy"]
            assert crit["windows"], t


# ── ② 脉冲标定锚 + NrTS 计划 ─────────────────────────────────────────────
class TestPulseAndNrts:
    def test_pulse_calibration_anchors(self):
        # 引擎日志标定：fc=1.0GHz → 2.865ns；fc=3.5GHz → 0.8187ns
        assert drv.pulse_est_s(1.0) == pytest.approx(2.865e-9, rel=1e-3)
        assert drv.pulse_est_s(3.5) == pytest.approx(0.81858e-9, rel=1e-3)

    def test_pulse_rejects_nonpositive(self):
        for fc in (0.0, -1.0):
            with pytest.raises(ValueError, match="须 >0"):
                drv.pulse_est_s(fc)

    def test_plan_nrts_formula_and_monotonic(self):
        dt = 2.14e-13
        expected = math.ceil(1.1 * (12e-9) / dt)
        assert drv.plan_nrts(12.0, dt) == expected
        assert drv.plan_nrts(12.0, dt) <= drv.plan_nrts(13.0, dt)
        # 宁长勿截：≥ 无余量值
        assert drv.plan_nrts(12.0, dt) >= math.ceil(12e-9 / dt)

    def test_plan_nrts_rejects_nonpositive(self):
        for t, dt in ((0.0, 1e-13), (12.0, 0.0), (-1.0, 1e-13)):
            with pytest.raises(ValueError, match="须 >0"):
                drv.plan_nrts(t, dt)


# ── ③ HJ 逆根同源回收（#118 换算正确性钉）────────────────────────────────
class TestHjInverse:
    def test_roundtrip_recovers_er(self):
        from rfauto.core.synthesis import Stackup, forward_z0

        er_true = 3.66
        sub = Stackup(name="rt", epsilon_r=er_true, thickness_mm=0.508,
                      loss_tangent=0.0037)
        _z0, eeff = forward_z0(1.1134, 2.5, sub)
        er, note = drv.hj_inverse_er(float(eeff), 1.1134, 2.5, 0.508,
                                     tan_d=0.0037)
        assert note == "ok"
        assert er == pytest.approx(er_true, rel=1e-6)

    def test_tan_d_must_match_design_chain(self):
        # tan_d 进 HJ εeff（0→0.0037 差 ~0.19% εeff）：提取侧漏传 tan_d
        # 即 −0.22% εr 系统偏差（单测回收钉实测抓出后加的回归钉）
        from rfauto.core.synthesis import Stackup, forward_z0

        sub = Stackup(name="rt", epsilon_r=3.66, thickness_mm=0.508,
                      loss_tangent=0.0037)
        _z0, eeff = forward_z0(1.1134, 2.5, sub)
        er_matched, _ = drv.hj_inverse_er(float(eeff), 1.1134, 2.5, 0.508,
                                          tan_d=0.0037)
        er_no_tand, _ = drv.hj_inverse_er(float(eeff), 1.1134, 2.5, 0.508,
                                          tan_d=0.0)
        assert er_matched == pytest.approx(3.66, rel=1e-5)
        assert er_no_tand < 3.66 * (1 - 1e-3), "tan_d 缺失须表现为可见系统偏差"

    def test_out_of_bracket_honest_none(self):
        er, note = drv.hj_inverse_er(0.9, 1.1134, 2.5, 0.508)   # εeff<1 不可达
        assert er is None
        assert "超出" in note


# ── ④ 合成谱判读判定表 ───────────────────────────────────────────────────
def _ring_f_from_er(er: float, f_ref_ghz: float = 2.5) -> float:
    """给定 er 反解名义几何上的 f1（r_mean 用名义单源；提取侧模型一致才有恒等回收）。

    er 偏低 → εeff 偏低 → f1 偏高（f ∝ 1/√εeff）。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import Stackup, forward_z0

    sub = Stackup(name="syn", epsilon_r=er, thickness_mm=0.508,
                  loss_tangent=0.0037)
    _z0, eeff = forward_z0(1.1134, f_ref_ghz, sub)
    r_mean = float(TEMPLATE_NOMINAL["ring_resonator"]["r_mean_mm"])
    return drv.C0 / (2.0 * math.pi * r_mean * 1e-3 * math.sqrt(eeff)) / 1e9


def _ring_synthetic(f1: float | None = None, f2: float | None = None,
                    peak: float = 0.85, base: float = 0.05,
                    n: int = 401):
    """合成 S21 双谐振谱：f1 缺省=er 3.66 设计链同源值（≈2.5）；f2 缺省=2×f1。"""
    if f1 is None:
        f1 = round(_ring_f_from_er(3.66), 3)
    if f2 is None:
        f2 = round(2.0 * f1, 3)
    freqs = np.linspace(1.5, 5.5, n)
    s21 = base + (peak - base) / (1.0 + ((freqs - f1) / 0.02) ** 2) \
        + (peak - base) / (1.0 + ((freqs - f2) / 0.04) ** 2)
    s11 = 0.1 * np.ones_like(freqs)
    return freqs, s11.astype(complex), s21.astype(complex), f1, f2


class TestRingJudge:
    def test_nominal_synthetic_pass(self):
        freqs, s11, s21, f1, f2 = _ring_synthetic()
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, s21, TEMPLATE_NOMINAL["ring_resonator"])
        assert ext["f1"] == pytest.approx(f1, abs=1e-6)
        assert ext["f2"] == pytest.approx(f2, abs=1e-6)
        # 峰位恰在"er=3.66 设计链同源 f1"上 → εr 回收 == 3.66（同源恒等路径；
        # tan_d 与设计链一致是恒等前提，漏传即 −0.22% 系统偏差）
        assert ext["eps_r_f1"] == pytest.approx(3.66, rel=1e-5)
        # f2=2×f1 → 闭式 εeff_2==εeff_1；色散致 εr(f2) 略低（一致门覆盖）
        assert ext["eps_r_f2"] == pytest.approx(3.66, rel=0.05)
        assert ext["f1_clamped"] is False and ext["f2_clamped"] is False
        assert ext["ql_info"] is not None and ext["ql_info"]["ql"] > 0
        s = np.stack([s11, s21])
        jd = drv.judge_ring(ext, s)
        assert jd["status"] == "PASS", jd["checks"]
        assert jd["nrts_policy"] == "record_only"

    def test_degenerate_no_fingerprint_fail(self):
        freqs, s11, _s21, _f1, _f2 = _ring_synthetic()
        flat = (0.01 * np.ones_like(freqs)).astype(complex)
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, flat,
                               TEMPLATE_NOMINAL["ring_resonator"])
        s = np.stack([s11, flat])
        jd = drv.judge_ring(ext, s)
        names = {c["name"]: c["ok"] for c in jd["checks"]}
        assert names["s21_peak_floor"] is False
        assert jd["status"] == "FAIL"

    def test_passivity_violation_fail(self):
        freqs, s11, s21, _f1, _f2 = _ring_synthetic()
        bad = 1.2 * np.ones_like(freqs).astype(complex)
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, s21,
                               TEMPLATE_NOMINAL["ring_resonator"])
        jd = drv.judge_ring(ext, np.stack([s11, bad]))
        assert jd["status"] == "FAIL"

    def test_clamped_peak_fails_guard(self):
        # 峰位推到搜索窗缘（#281 夹持形态：argmax 被窗缘夹持即红）
        freqs, s11, s21, _f1, _f2 = _ring_synthetic(f1=2.40)
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, s21,
                               TEMPLATE_NOMINAL["ring_resonator"])
        assert ext["f1_clamped"] is True
        s = np.stack([s11, s21])
        jd = drv.judge_ring(ext, s)
        names = {c["name"] for c in jd["checks"] if c["ok"] is False}
        assert "f1_clamp_guard" in names
        assert jd["status"] == "FAIL"

    def test_shifted_peak_clamped_or_out(self):
        # f1 漂出窗（er 漂 −13% → f1 ∝1/√εeff 抬 ~4.4%）：极值被窗缘夹持——
        # FAIL 如实不凑绿（#122/#281 形态）
        f1_bad = _ring_f_from_er(3.66 * 0.87)
        assert f1_bad > drv.RING["f1_win_ghz"][1], "扰动须真出窗（测试前提）"
        freqs, s11, s21, _f1, _f2 = _ring_synthetic(f1=round(f1_bad, 3))
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, s21,
                               TEMPLATE_NOMINAL["ring_resonator"])
        jd = drv.judge_ring(ext, np.stack([s11, s21]))
        assert jd["status"] in ("FAIL", "PARTIAL")
        names = {c["name"] for c in jd["checks"]
                 if c["ok"] is False or c["ok"] is None}
        assert names & {"f1_window", "f1_clamp_guard", "eps_r_f1_window"}, names


class TestWaveguideJudge:
    def test_horn_good_match_pass(self):
        freqs = np.linspace(8.0, 12.0, 201)
        s11 = 0.1 * np.exp(-1j * 2 * np.pi * freqs / 4.0)   # −20dB
        ext = drv.extract_waveguide(freqs, s11, template="pyramid_horn")
        jd = drv.judge_waveguide_refl(ext, s11.reshape(-1, 1),
                                      drv.HORN, "pyramid_horn")
        assert jd["status"] == "PASS"
        names = {c["name"]: c["ok"] for c in jd["checks"]}
        # 方向性如实注记：ok=None（本席不可测），不是 PASS 也不是 FAIL
        assert names["directivity"] is None

    def test_horn_bad_match_fail(self):
        freqs = np.linspace(8.0, 12.0, 201)
        s11 = 0.7 * np.ones_like(freqs).astype(complex)   # −3dB 全反射
        ext = drv.extract_waveguide(freqs, s11, template="pyramid_horn")
        jd = drv.judge_waveguide_refl(ext, s11.reshape(-1, 1),
                                      drv.HORN, "pyramid_horn")
        assert jd["status"] == "FAIL"

    def test_coax_pass_with_insertion(self):
        freqs = np.linspace(8.0, 12.0, 201)
        s11 = 0.2 * np.ones_like(freqs).astype(complex)   # −14dB
        s21 = 10 ** (-0.5 / 20) * np.ones_like(freqs).astype(complex)  # −0.5dB
        ext = drv.extract_waveguide(freqs, s11, s21, zl_wg_f0=350.0,
                                    template="coax_waveguide_transition")
        jd = drv.judge_coax(ext, np.stack([s11, s21]))
        assert jd["status"] == "PASS", jd["checks"]
        assert jd["scalars"]["zl_wg_f0_ohm"] == 350.0

    def test_coax_insertion_loss_fail(self):
        freqs = np.linspace(8.0, 12.0, 201)
        s11 = 0.2 * np.ones_like(freqs).astype(complex)
        s21 = 10 ** (-3.0 / 20) * np.ones_like(freqs).astype(complex)  # −3dB
        ext = drv.extract_waveguide(freqs, s11, s21, template="coax_waveguide_transition")
        jd = drv.judge_coax(ext, np.stack([s11, s21]))
        names = {c["name"]: c["ok"] for c in jd["checks"]}
        assert names["s21_f0"] is False
        assert jd["status"] == "FAIL"

    def test_coax_s21_missing_degrades_partial(self):
        # P2-1（review_slice6）：S21 整列缺测（渲染器端口面异常/解析列名漂移
        # 时先消失）→ 插损主轴不可判，缺测如实降 PARTIAL（#314/#316 口径），
        # S11 三窗全绿也不得冒充 PASS
        freqs = np.linspace(8.0, 12.0, 201)
        s11 = 0.2 * np.ones_like(freqs).astype(complex)   # S11 三窗全绿
        ext = drv.extract_waveguide(freqs, s11, None,
                                    template="coax_waveguide_transition")
        jd = drv.judge_coax(ext, s11.reshape(-1, 1))
        names = {c["name"]: c["ok"] for c in jd["checks"]}
        assert names["s21_f0"] is None
        assert jd["status"] == "PARTIAL", jd["checks"]
        assert "缺测" in jd["reason"]

    def test_coax_s21_missing_with_s11_fail_stays_fail(self):
        # FAIL 优先于缺测降级：降级只作用于"本会 PASS"的 run，不救已 FAIL
        freqs = np.linspace(8.0, 12.0, 201)
        s11 = 0.7 * np.ones_like(freqs).astype(complex)   # −3dB 全反射
        ext = drv.extract_waveguide(freqs, s11, None,
                                    template="coax_waveguide_transition")
        jd = drv.judge_coax(ext, s11.reshape(-1, 1))
        assert jd["status"] == "FAIL"


# ── ⑤ sparams 列解析 ─────────────────────────────────────────────────────
class TestReadSparams:
    def test_five_column_roundtrip(self, tmp_path):
        p = tmp_path / "sparams.csv"
        f = np.linspace(1.5, 5.5, 11)
        s11 = 0.1 - 0.05j
        s21 = 0.8 + 0.1j
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write("freq_hz,re_S11,im_S11,re_S21,im_S21\n")
            for fi in f:
                fh.write(f"{fi},{s11.real},{s11.imag},{s21.real},{s21.imag}\n")
        cols = drv._read_sparams_columns(p)
        assert cols is not None
        assert np.allclose(cols["freq_hz"], f)
        assert np.allclose(cols["s11"], s11)
        assert np.allclose(cols["s21"], s21)

    def test_malformed_returns_none(self, tmp_path):
        p = tmp_path / "broken.csv"
        p.write_text("freq_hz,garbage\n1,2\n", encoding="utf-8")
        assert drv._read_sparams_columns(p) is None
        assert drv._read_sparams_columns(tmp_path / "missing.csv") is None


# ── ⑦ 名义单源核对（真实 docs）──────────────────────────────────────────
class TestNominalSingleSource:
    @pytest.mark.parametrize("template", drv.TARGETS)
    def test_docs_meta_matches_src(self, template):
        out = drv.nominal_vs_docs(template)
        assert out["ok"] is True, out["mismatches"]


# ── ⑧ ring 预飞 exec 审计（#212 口径真实渲染一次，秒级零仿真）────────────
class TestPreflightRing:
    def test_preflight_ring_ok(self):
        out = drv.preflight("ring_resonator")
        assert out["ok"] is True, out["checks"]
        assert out["nrts_plan"] > 0
        assert out["pulse_coverage"] >= 2.0
        assert out["nrts_literal"]["ok"] is True
        assert out["est_wall_min"][0] <= out["est_wall_min"][1]
        # 审计档差异预声明：冒烟档 0.5（≠ tests 帮助表审计档 0.4）
        assert out["mesh_mm"] == 0.5


# ── ⑨ CLI dry-call / judge-only 稳态 ────────────────────────────────────
class TestCli:
    def test_help_dry_call(self):
        r = subprocess.run(
            [sys.executable, str(DRIVER), "--help"],
            capture_output=True, text=True, timeout=120)
        assert r.returncode == 0
        assert "--preflight-only" in r.stdout
        assert "--judge-only" in r.stdout

    def test_judge_only_skips_empty_root(self, tmp_path, monkeypatch):
        monkeypatch.setattr(drv, "OUT_ROOT", tmp_path)
        rc = drv.run_judge_only(list(drv.TARGETS))
        assert rc == 0
        assert not (tmp_path / "campaign_summary.json").exists() or (
            json.loads((tmp_path / "campaign_summary.json").read_text(
                encoding="utf-8")) == {})


# ── ⑩ 席位策略门（_apply_gates/run_judge_only 合成 run 判读，P2-2+P1-1）──
#: 触 NrTS 帽引擎日志（review_slice6 P2-2：仿引擎文案合成，逐行可被
#: fd_oe_campaign.parse_engine_log 正则消费——warn 行即 ok=False 主证）
_CAP_ENGINE_LOG = (
    "FDTD simulation size: 100x100x100 --> 1.0e6 FDTD cells\n"
    "FDTD timestep is: 2.14e-13 s; Nyquist rate: 8 timesteps @1.2e11 Hz\n"
    "Excitation signal length is: 6694 timesteps (1.4323e-09s)\n"
    "Max. number of timesteps: 28060 ( --> 4.19 * Excitation signal length)\n"
    "Time for 28060 iterations with 1.0e6 cells : 45.2 sec\n"
    "Timestep:  28060 || Bnd: ABC || Energy: ~1.0e-01 (-20.37dB)\n"
    "Max. number of timesteps was reached before the end-criteria of -60dB\n")


def _write_sparams_csv(path: Path, freqs, pairs) -> None:
    """合成 sparams.csv：pairs=[(端口对名, 复数组), ...] → freq_hz,re_X,im_X…"""
    header = ["freq_hz"]
    for name, _arr in pairs:
        header += [f"re_{name}", f"im_{name}"]
    lines = [",".join(header)]
    for i, f in enumerate(freqs):
        row = [f"{float(f):.6e}"]
        for _name, arr in pairs:
            row += [f"{arr[i].real:.6e}", f"{arr[i].imag:.6e}"]
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _coax_healthy_pairs(n: int = 201):
    """coax 判据全绿合成谱：S11=−14dB（三窗过）+ S21=−0.92dB（≥−1.5 过）。"""
    freqs = np.linspace(8.0, 12.0, n)
    s11 = (0.2 * np.ones_like(freqs)).astype(complex)
    s21 = (10 ** (-0.5 / 20) * np.ones_like(freqs)).astype(complex)
    return freqs, s11, s21


def _read_verdict(root: Path, template: str) -> dict:
    return json.loads(
        (root / template / "verdict.json").read_text(encoding="utf-8"))


class TestSeatPolicyGates:
    """_apply_gates 席位策略语义（review_slice6 P2-2）+ P1-1 端到端。

    变异 M5 实证：_apply_gates 整段删空 28 测无一变红——本组补"降级行为"
    层回归钉（删 must_converge 降级/record_only 不降级/ok=None 留痕任一语义
    须红）。P1-1：openems_solver.solve() 成功路径落 _last_stdout.log 后，
    nrts_converged 门在 judge-only 真实消费路径端到端可判（此前恒 ok=None）。
    """

    def test_must_converge_cap_hit_degrades_pass_to_fail(
            self, tmp_path, monkeypatch):
        run_dir = tmp_path / "coax_waveguide_transition"
        run_dir.mkdir(parents=True)
        freqs, s11, s21 = _coax_healthy_pairs()
        _write_sparams_csv(run_dir / "sparams.csv", freqs,
                           [("S11", s11), ("S21", s21)])
        (run_dir / "_last_stdout.log").write_text(
            _CAP_ENGINE_LOG, encoding="utf-8")
        monkeypatch.setattr(drv, "OUT_ROOT", tmp_path)

        assert drv.run_judge_only(["coax_waveguide_transition"]) == 0
        verdict = _read_verdict(tmp_path, "coax_waveguide_transition")
        # 判读层本会 PASS → 降级只能来自席位策略门
        assert verdict["judge"]["status"] == "PASS"
        assert verdict["status"] == "FAIL"
        assert "nrts_converged" in verdict["reason"]
        assert verdict["nrts_converged"]["ok"] is False

    def test_record_only_cap_hit_stays_pass_with_trace(
            self, tmp_path, monkeypatch):
        run_dir = tmp_path / "ring_resonator"
        run_dir.mkdir(parents=True)
        freqs, s11, s21, _f1, _f2 = _ring_synthetic()
        _write_sparams_csv(run_dir / "sparams.csv", freqs,
                           [("S11", s11), ("S21", s21)])
        (run_dir / "_last_stdout.log").write_text(
            _CAP_ENGINE_LOG, encoding="utf-8")
        monkeypatch.setattr(drv, "OUT_ROOT", tmp_path)

        assert drv.run_judge_only(["ring_resonator"]) == 0
        verdict = _read_verdict(tmp_path, "ring_resonator")
        # ring 触帽属预期（record_only）：如实留痕，不动状态
        assert verdict["status"] == "PASS", verdict["judge"]["checks"]
        assert verdict["nrts_converged"]["ok"] is False

    def test_missing_engine_log_ok_none_keeps_status(
            self, tmp_path, monkeypatch):
        run_dir = tmp_path / "coax_waveguide_transition"
        run_dir.mkdir(parents=True)
        freqs, s11, s21 = _coax_healthy_pairs()
        _write_sparams_csv(run_dir / "sparams.csv", freqs,
                           [("S11", s11), ("S21", s21)])
        monkeypatch.setattr(drv, "OUT_ROOT", tmp_path)

        assert drv.run_judge_only(["coax_waveguide_transition"]) == 0
        verdict = _read_verdict(tmp_path, "coax_waveguide_transition")
        # 证据缺=ok=None 只留痕（#122：不凑 PASS 也不冒充 FAIL）
        assert verdict["status"] == "PASS"
        assert verdict["nrts_converged"]["ok"] is None

    def test_solver_success_log_feeds_gate_end_to_end(
            self, tmp_path, monkeypatch):
        """P1-1 端到端：solve() 成功路径落盘 → 门真读 → must_converge 降 FAIL。

        删 solver 落盘 hunk（本日志缺→ok=None→不降级）或删 _apply_gates 降级
        分支，本测均须红——落盘与消费两侧各有一钉。
        """
        from rfauto.adapters.em_solver_base import EMSolverConfig
        from rfauto.adapters.openems_solver import OpenEMSSolver

        run_dir = tmp_path / "coax_waveguide_transition"
        run_dir.mkdir(parents=True)
        freqs, s11, s21 = _coax_healthy_pairs()
        _write_sparams_csv(run_dir / "sparams.csv", freqs,
                           [("S11", s11), ("S21", s21)])
        (run_dir / "simulation.py").write_text("# stub\n", encoding="utf-8")
        (tmp_path / "oe.exe").write_text("", encoding="utf-8")
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems", exe_path=str(tmp_path / "oe.exe"),
            working_dir=str(run_dir), freq_range_ghz=(8.0, 12.0),
            extra_params={"cache": False}))
        assert solver.connect()
        assert solver.build_geometry(
            {"template": "coax_waveguide_transition", "params": {}})

        import subprocess as sp

        def fake_run(cmd, **kw):
            return sp.CompletedProcess(cmd, 0, stdout=_CAP_ENGINE_LOG, stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        res = solver.solve()
        assert res.success
        # P1-1 落盘面：rc=0 触帽正常终止的引擎日志在档
        assert (run_dir / "_last_stdout.log").read_text(
            encoding="utf-8") == _CAP_ENGINE_LOG

        monkeypatch.setattr(drv, "OUT_ROOT", tmp_path)
        assert drv.run_judge_only(["coax_waveguide_transition"]) == 0
        verdict = _read_verdict(tmp_path, "coax_waveguide_transition")
        assert verdict["judge"]["status"] == "PASS"
        assert verdict["status"] == "FAIL"
        assert verdict["nrts_converged"]["ok"] is False

    def test_coax_s21_missing_run_partial_not_pass(
            self, tmp_path, monkeypatch):
        """P2-1 端到端：3 列 csv（S21 整列缺）全链路判 PARTIAL 非 PASS。"""
        run_dir = tmp_path / "coax_waveguide_transition"
        run_dir.mkdir(parents=True)
        freqs, s11, _s21 = _coax_healthy_pairs()
        _write_sparams_csv(run_dir / "sparams.csv", freqs, [("S11", s11)])
        monkeypatch.setattr(drv, "OUT_ROOT", tmp_path)

        assert drv.run_judge_only(["coax_waveguide_transition"]) == 0
        verdict = _read_verdict(tmp_path, "coax_waveguide_transition")
        assert verdict["status"] == "PARTIAL"
        # 判读层 reason/checks 均如实注记缺测（verdict 顶层 reason 只在
        # _apply_gates/产物缺路径设置）
        assert "缺测" in verdict["judge"]["reason"]
        names = {c["name"]: c["ok"] for c in verdict["judge"]["checks"]}
        assert names["s21_f0"] is None


# ── ⑪ S4 审计回归钉：extract_ring 复数 argmax 幅值语义（H3，2026-09-29 修）──
class TestExtractRingMagnitudeSemantics:
    """复现审计实测形态：f2 真峰 4.78 相量 (0.0086,−0.0502) 实部极小，
    实部 argmax（bug）必误取 4.75/误报 clamped——幅值语义必取 4.78。
    删 extract_ring 调用点 np.abs 本组两测均红。
    """

    def _freqs(self) -> np.ndarray:
        return np.linspace(1.5, 5.5, 401)   # 0.01GHz 步（与真跑同网格密度）

    def test_small_real_part_peak_selected_by_magnitude(self):
        freqs = self._freqs()
        s21 = (0.002 * np.ones_like(freqs)).astype(complex)
        s21[np.argmin(np.abs(freqs - 4.75))] = 0.0373 + 0.0j        # 实部峰 decoy
        s21[np.argmin(np.abs(freqs - 4.78))] = 0.0086 - 0.0502j     # 真峰
        s11 = (0.95 * np.ones_like(freqs)).astype(complex)
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, s21,
                               TEMPLATE_NOMINAL["ring_resonator"])
        assert ext["f2"] == pytest.approx(4.78)
        assert ext["f2_clamped"] is False
        assert ext["f2_s21"] == pytest.approx(abs(0.0086 - 0.0502j))
        # decoy 若被实部语义选中恰是窗缘点（bug 形态=f2=4.75+clamped）
        assert ext["f2"] != pytest.approx(4.75)

    def test_negative_real_part_peak_not_skipped(self):
        # 真峰实部为负（−0.010 < 背景 0.004）：实部 argmax 必跳过（numpy
        # 复数按实部比较），幅值语义必取——共轭/负实部谱的提取正确性钉
        freqs = self._freqs()
        s21 = (0.004 * np.ones_like(freqs)).astype(complex)
        s21[np.argmin(np.abs(freqs - 4.78))] = -0.010 + 0.050j
        s11 = (0.95 * np.ones_like(freqs)).astype(complex)
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        ext = drv.extract_ring(freqs, s11, s21,
                               TEMPLATE_NOMINAL["ring_resonator"])
        assert ext["f2"] == pytest.approx(4.78)
        assert ext["f2_s21"] == pytest.approx(abs(-0.010 + 0.050j))

    def test_argext_db_argmin_unaffected(self):
        # _argext_clamped 入口禁 abs 的守卫钉：dB 域负值谱 argmin（horn/coax
        # 共享路径）若被翻转（abs 把 −30dB 谷变 +30）即丢谷
        freqs = np.linspace(8.0, 12.0, 201)
        s11_db = np.full(201, -5.0)
        s11_db[100] = -30.0
        idx, clamped = drv._argext_clamped(freqs, s11_db, (8.0, 12.0), "min")
        assert freqs[idx] == pytest.approx(10.0)
        assert clamped is False


# ── ⑫ criteria v2（S4 审计换基）+ 离线重判（scripts/oe_phase3_ring_rejudge）──
REJUDGE = SCRIPTS / "oe_phase3_ring_rejudge.py"


def _load_rejudge():
    spec = importlib.util.spec_from_file_location(
        "oe_phase3_ring_rejudge", REJUDGE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("oe_phase3_ring_rejudge", mod)
    spec.loader.exec_module(mod)
    return mod


rj = _load_rejudge()


class TestCriteriaV2Declaration:
    def test_windows_pinned_to_audit(self):
        # 审计 §5 Tier-1 预声明值（#122：先声明后判）
        assert rj.RING_V2["r_eff_basis"] == "outer_radius"
        assert rj.RING_V2["f1_win_ghz"] == (2.30, 2.50)
        assert rj.RING_V2["f2_win_ghz"] == (4.65, 4.90)
        assert rj.RING_V2["f1_peak_min"] == 0.010
        assert rj.RING_V2["f2_peak_min"] == 0.025
        # 维持 v1 不动的两项
        assert rj.RING_V2["eps_r_win"] == (3.11, 4.21)
        assert rj.RING_V2["eps_r_diff_max"] == 0.60

    def test_r_eff_and_predictions_match_audit_step3(self):
        crit = rj.build_criteria_v2()
        # R_OUT = r_mean + w/2（单源推导）≈ 11.8565mm；预测复算非手抄审计
        assert crit["r_eff_mm"] == pytest.approx(11.8565, abs=5e-4)
        assert crit["predictions_ghz"]["f1_pred_ghz"] == pytest.approx(
            2.3826, abs=5e-4)
        assert crit["predictions_ghz"]["f2_pred_ghz"] == pytest.approx(
            4.7652, abs=5e-4)
        assert "换基声明" in crit["rebasis_declaration"]


class TestRejudgeV2:
    """criteria v2 提取/判读纯函数（合成复现审计实测形态，全离线）。"""

    def _measured_form(self):
        # S4 审计实测形态：f1=2.38（|S21|=0.0167 实部为正）/f2=4.78
        # （幅值 0.0509、实部极小 0.0086）+ 背景 0.003
        freqs = np.linspace(1.5, 5.5, 401)
        s21 = (0.003 * np.ones_like(freqs)).astype(complex)
        s21[np.argmin(np.abs(freqs - 2.38))] = 0.0167 + 0.0j
        s21[np.argmin(np.abs(freqs - 4.78))] = 0.0086 - 0.0502j
        s11 = (0.95 * np.ones_like(freqs)).astype(complex)
        return freqs, s11, s21

    def test_measured_form_passes_v2_full_gates(self):
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        freqs, s11, s21 = self._measured_form()
        ext = rj.extract_ring_v2(freqs, s11, s21,
                                 TEMPLATE_NOMINAL["ring_resonator"])
        assert ext["f1"] == pytest.approx(2.38)
        assert ext["f1_clamped"] is False
        assert ext["f2"] == pytest.approx(4.78)
        assert ext["f2_clamped"] is False
        # εr 回收（R_eff 基准）≈审计 step3：3.6687/3.6401
        assert ext["eps_r_f1"] == pytest.approx(3.6687, abs=5e-3)
        assert ext["eps_r_f2"] == pytest.approx(3.6401, abs=5e-3)
        jd = rj.judge_ring_v2(ext, np.stack([s11, s21]))
        names = {c["name"]: c["ok"] for c in jd["checks"]}
        assert names["f1_window"] and names["f2_window"]
        assert names["f1_peak_floor"] and names["f2_peak_floor"]
        assert names["eps_r_f1_window"] and names["eps_r_harmonic_consistency"]
        assert jd["status"] == "PASS", jd["checks"]

    def test_weak_coupling_peak_fails_floor(self):
        # 峰 0.008（< f1 地板 0.010）→ 谐振指纹门红（v2 地板仍守语义；
        # v1 地板 0.2 对该峰同为 FAIL——v2 只修"判据误定"，不放水）
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        freqs, s11, s21 = self._measured_form()
        s21[np.argmin(np.abs(freqs - 2.38))] = 0.008 + 0.0j
        ext = rj.extract_ring_v2(freqs, s11, s21,
                                 TEMPLATE_NOMINAL["ring_resonator"])
        jd = rj.judge_ring_v2(ext, np.stack([s11, s21]))
        names = {c["name"]: c["ok"] for c in jd["checks"]}
        assert names["f1_peak_floor"] is False
        assert jd["status"] == "FAIL"

    def test_ql_honest_unknown_resolution_limited(self):
        # H6：冒烟档分辨率受限 → Q_L 如实 UNKNOWN（原始量可留痕但不采信）
        from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

        freqs, s11, s21 = self._measured_form()
        ext = rj.extract_ring_v2(freqs, s11, s21,
                                 TEMPLATE_NOMINAL["ring_resonator"])
        assert ext["ql_info"]["status"] == "UNKNOWN"
        assert "H6" in ext["ql_info"]["reason"]

    def test_run_rejudge_on_synthetic_run_dir(self, tmp_path):
        """端到端（隔离目录）：合成 sparams.csv → *_fix.json/md 落盘；
        v1 双留痕文件不被触碰。"""
        run_dir = tmp_path / "ring_resonator"
        run_dir.mkdir()
        freqs, s11, s21 = self._measured_form()
        _write_sparams_csv(run_dir / "sparams.csv", freqs * 1e9,
                           [("S11", s11), ("S21", s21)])
        out_dir = tmp_path / "out"
        verdict = rj.run_rejudge(run_dir, out_dir, env_gates=False)
        assert verdict["status"] == "PASS", verdict["judge"]["checks"]
        assert (out_dir / "verdict_offline_fix.json").exists()
        md = (out_dir / "verdict_offline_fix.md").read_text(encoding="utf-8")
        assert "换基声明" in md and "新旧对照" in md
        # run 目录零写入（双留痕纪律）
        assert not (run_dir / "verdict_offline_fix.json").exists()
