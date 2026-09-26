"""df7 T2 SI 通道报告 service 测试（判据预声明，合成通道全确定性）。

判据与出处（方案池 T2 / 规格预声明，逐条对号）：
1. 理想无耗匹配线 → passivity PASS、TDR 平坦 Z0（±1%）；
2. 注入无源性违规（S×1.2）→ FAIL 且违规频点命中；
3. 已知阻抗阶梯（两段无损线 ABCD 合成，50Ω→75Ω）→ TDR 两平台各 ±3%；
4. 因果性：合成因果系统前导能量 ≈0 PASS；注入时域超前（负群延迟）
   → FAIL；
5. COM：合成 4 端口直通链跑通 pychopmarg 全流程（数值带内即可，精确值
   不自证——COM 内核是权威）；2 端口 not_applicable；pychopmarg 缺装
   degraded 钉。

合成通道 = 纯 numpy/skrf 确定性解析式（无 RNG）；时域原语复用
core/si_channel（单源）。COM 段较慢（~10s），单独类便于定向挑选。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.si_channel import rc_lowpass_s21
from rfauto.service.si_channel_service import render_si_channel_markdown, si_channel_report

F_HZ = np.arange(1e7, 40.001e9, 1e7)  # 10 MHz 步进，0.01–40 GHz（含 DC 邻域）
Z_REF = 50.0


# ---------------------------------------------------------------------------
# 合成通道（确定性解析式；ABCD↔S 换算为标准 2 端口口径）
# ---------------------------------------------------------------------------

def _line_s(zc: float, delay_s: float, f: np.ndarray) -> np.ndarray:
    """无损线（特征阻抗 zc、延时 delay_s）→ 50Ω 参考基 2 端口 S 矩阵。"""
    bl = 2.0 * np.pi * f * delay_s
    a = np.cos(bl) + 0j
    b = 1j * zc * np.sin(bl)
    c = 1j * np.sin(bl) / zc
    d = a
    den = a * Z_REF + b + c * Z_REF * Z_REF + d * Z_REF
    s11 = (a * Z_REF + b - c * Z_REF * Z_REF - d * Z_REF) / den
    s21 = 2.0 * Z_REF / den
    n = f.size
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 1] = s11
    s[:, 0, 1] = s21
    s[:, 1, 0] = s21
    return s


def _abcd(s: np.ndarray) -> np.ndarray:
    den = 2.0 * s[:, 1, 0]
    abcd = np.empty_like(s)
    abcd[:, 0, 0] = ((1 + s[:, 0, 0]) * (1 - s[:, 1, 1])
                     + s[:, 0, 1] * s[:, 1, 0]) / den
    abcd[:, 0, 1] = Z_REF * ((1 + s[:, 0, 0]) * (1 + s[:, 1, 1])
                             - s[:, 0, 1] * s[:, 1, 0]) / den
    abcd[:, 1, 0] = ((1 - s[:, 0, 0]) * (1 - s[:, 1, 1])
                     - s[:, 0, 1] * s[:, 1, 0]) / (den * Z_REF)
    abcd[:, 1, 1] = ((1 - s[:, 0, 0]) * (1 + s[:, 1, 1])
                     + s[:, 0, 1] * s[:, 1, 0]) / den
    return abcd


def _s_from_abcd(a: np.ndarray) -> np.ndarray:
    den = a[:, 0, 0] + a[:, 0, 1] / Z_REF + a[:, 1, 0] * Z_REF + a[:, 1, 1]
    s = np.empty_like(a)
    s[:, 0, 0] = (a[:, 0, 0] + a[:, 0, 1] / Z_REF - a[:, 1, 0] * Z_REF
                  - a[:, 1, 1]) / den
    s[:, 0, 1] = 2.0 * (a[:, 0, 0] * a[:, 1, 1] - a[:, 0, 1] * a[:, 1, 0]) / den
    s[:, 1, 0] = 2.0 / den
    s[:, 1, 1] = (-a[:, 0, 0] + a[:, 0, 1] / Z_REF - a[:, 1, 0] * Z_REF
                  + a[:, 1, 1]) / den
    return s


def _cascade(s1: np.ndarray, s2: np.ndarray) -> np.ndarray:
    return _s_from_abcd(_abcd(s1) @ _abcd(s2))


def _matched_line_s(f: np.ndarray, delay_s: float = 1e-9) -> np.ndarray:
    """理想无耗匹配线（Z0=50=参考）：|S21|=1、S11=0。"""
    return _line_s(50.0, delay_s, f)


def _impedance_step_s(f: np.ndarray) -> np.ndarray:
    """两段无损线 50Ω(0.5ns)→75Ω(0.5ns) 级联（端口参考 50Ω）。"""
    return _cascade(_line_s(50.0, 0.5e-9, f), _line_s(75.0, 0.5e-9, f))


def _write_s2p(path: Path, s: np.ndarray, f: np.ndarray = F_HZ) -> Path:
    """2 端口 S 矩阵 → Touchstone v1（RI HZ 50Ω）。"""
    lines = ["# HZ S RI R 50.0"]
    for k in range(f.size):
        vals = [s[k, 0, 0], s[k, 1, 0], s[k, 0, 1], s[k, 1, 1]]
        flat: list[str] = []
        for v in vals:
            flat.append(f"{v.real:.10e}")
            flat.append(f"{v.imag:.10e}")
        lines.append(f"{f[k]:.10e} " + " ".join(flat))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_s4p_decoupled_pair(path: Path,
                              f: np.ndarray = F_HZ,
                              advance_s: float = 0.0) -> Path:
    """解耦差分对 4 端口（sdd_21 "1→2/3→4" 端口序：直通=1→2 与 3→4）。

    单端两路独立 50Ω 有耗线（因果 RLC 传输线模型）；advance_s>0 时给
    直通路径乘 exp(+jω·advance)（时域超前 = 非因果注入）。
    """
    w = 2.0 * np.pi * f
    r_ohm, l_h, c_f, g_s, length = 8.0, 260e-9, 130e-12, 1e-6, 0.25
    gamma = np.sqrt((r_ohm + 1j * w * l_h) * (g_s + 1j * w * c_f))
    zc = np.sqrt((r_ohm + 1j * w * l_h) / (g_s + 1j * w * c_f))
    thru = np.exp(-gamma * length) * (2.0 * zc / (zc + Z_REF))
    ref = (zc - Z_REF) / (zc + Z_REF)
    thru = thru * np.exp(1j * 2.0 * np.pi * f * advance_s)
    n = f.size
    s = np.zeros((n, 4, 4), dtype=complex)
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2)):
        s[:, i, j] = thru
    for i in range(4):
        s[:, i, i] = ref
    lines = ["# HZ S RI R 50.0"]
    for k in range(n):
        parts: list[str] = [f"{f[k]:.10e}"]
        for i in range(4):
            for j in range(4):
                parts.append(f"{s[k, i, j].real:.10e}")
                parts.append(f"{s[k, i, j].imag:.10e}")
        lines.append(" ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 判据 1：理想无耗匹配线 → passivity PASS + TDR 平坦
# ---------------------------------------------------------------------------

class TestIdealMatchedLine:
    def test_passivity_pass_and_tdr_flat(self, tmp_path: Path) -> None:
        s2p = _write_s2p(tmp_path / "ideal.s2p", _matched_line_s(F_HZ))
        rep = si_channel_report(s2p)
        assert rep["ok"] is True
        pas = rep["passivity"]
        assert pas["status"] == "pass"
        # 无耗匹配线 σmax=1（酉矩阵）+ 浮点尾数
        assert pas["max_sigma_max"] == pytest.approx(1.0, abs=1e-9)
        assert pas["n_violations"] == 0
        tdr = rep["tdr"]
        assert tdr["status"] == "ok"
        # TDR 全程平坦 50Ω（±1%）
        assert tdr["z_mean_first_window_from_zero_ohm"] == pytest.approx(
            50.0, rel=0.01)
        assert tdr["z_min_ohm"] == pytest.approx(50.0, rel=0.01)
        assert tdr["z_max_ohm"] == pytest.approx(50.0, rel=0.01)
        assert tdr["flatness_rel"] < 0.01
        # 因果性：合成因果系统前导能量 ≈0
        cau = rep["causality"]
        assert cau["status"] == "pass"
        assert cau["pre_cursor_energy_frac"] < 1e-6
        assert cau["apparent_group_delay_s"] == pytest.approx(1e-9, rel=0.05)

    def test_json_safe_and_markdown_renders(self, tmp_path: Path) -> None:
        s2p = _write_s2p(tmp_path / "ideal.s2p", _matched_line_s(F_HZ))
        rep = si_channel_report(s2p, markdown=True)
        text = json.dumps(rep, ensure_ascii=False, allow_nan=False)  # NaN 即炸
        assert "passivity" in text
        md = render_si_channel_markdown(rep)
        assert "# SI 通道报告" in md
        assert "COM (IEEE 93A" in md


# ---------------------------------------------------------------------------
# 判据 2：无源性违规（S×1.2）→ FAIL 且违规频点命中
# ---------------------------------------------------------------------------

class TestPassivityViolation:
    def test_scaled_s_fails_with_freq_hits(self, tmp_path: Path) -> None:
        s_bad = _matched_line_s(F_HZ) * 1.2
        s2p = _write_s2p(tmp_path / "viol.s2p", s_bad)
        rep = si_channel_report(s2p)
        pas = rep["passivity"]
        assert pas["status"] == "fail"
        assert pas["max_sigma_max"] == pytest.approx(1.2, abs=1e-9)
        # 全频段违规（|S21|=1.2 每频点都 > 1+tol），TOP N 截断
        assert pas["n_violations"] == F_HZ.size
        assert len(pas["violations_top"]) == 10
        assert pas["violations_top"][0]["sigma_max"] == pytest.approx(
            1.2, abs=1e-9)
        assert pas["violations_top"][0]["freq_hz"] in F_HZ

    def test_tol_relaxes_to_pass(self, tmp_path: Path) -> None:
        s_slight = _matched_line_s(F_HZ) * 1.005
        s2p = _write_s2p(tmp_path / "slight.s2p", s_slight)
        rep = si_channel_report(s2p, passivity_tol=0.01)
        assert rep["passivity"]["status"] == "pass"
        rep2 = si_channel_report(s2p, passivity_tol=1e-4)
        assert rep2["passivity"]["status"] == "fail"


# ---------------------------------------------------------------------------
# 判据 3：阻抗阶梯 50→75 → TDR 两平台各 ±3%
# ---------------------------------------------------------------------------

class TestTdrImpedanceStep:
    def test_two_platforms_hit(self, tmp_path: Path) -> None:
        s2p = _write_s2p(tmp_path / "step.s2p", _impedance_step_s(F_HZ))
        rep = si_channel_report(s2p)
        tdr = rep["tdr"]
        assert tdr["status"] == "ok"
        prof_t = np.array(tdr["profile"]["t_ns"])
        prof_z = np.array([z if z is not None else np.nan
                           for z in tdr["profile"]["z_ohm"]])
        # 平台窗：接口反射 0.5ns 往返 = 1ns 到达；段 2 末端反射 2ns
        m1 = (prof_t > 0.05) & (prof_t < 0.8)
        m2 = (prof_t > 1.3) & (prof_t < 1.8)
        assert np.nanmean(prof_z[m1]) == pytest.approx(50.0, rel=0.03)
        assert np.nanmean(prof_z[m2]) == pytest.approx(75.0, rel=0.03)
        assert tdr["z_max_ohm"] == pytest.approx(75.0, rel=0.03)
        assert tdr["z_min_ohm"] == pytest.approx(50.0, abs=1.5)


# ---------------------------------------------------------------------------
# 判据 4：因果性（因果 PASS / 时域超前 FAIL）
# ---------------------------------------------------------------------------

class TestCausality:
    def test_causal_lossy_line_passes(self, tmp_path: Path) -> None:
        s2p = _write_s2p(tmp_path / "causal.s2p", _matched_line_s(F_HZ))
        rep = si_channel_report(s2p)
        cau = rep["causality"]
        assert cau["status"] == "pass"
        assert cau["pre_cursor_energy_frac"] == pytest.approx(0.0, abs=1e-6)

    def test_time_advance_injection_fails(self, tmp_path: Path) -> None:
        # 非因果注入：S21 × exp(+jω·2ns)（时域超前 2ns > 线延时 1ns
        # → 低频视在群延迟为负；尾窗能量占比同步抬升）
        s_nc = _matched_line_s(F_HZ).copy()
        s_nc[:, 1, 0] *= np.exp(1j * 2.0 * np.pi * F_HZ * 2e-9)
        s_nc[:, 0, 1] *= np.exp(1j * 2.0 * np.pi * F_HZ * 2e-9)
        s2p = _write_s2p(tmp_path / "noncausal.s2p", s_nc)
        rep = si_channel_report(s2p)
        cau = rep["causality"]
        assert cau["status"] == "fail"
        assert cau["apparent_group_delay_s"] < 0.0
        assert cau.get("reasons")

    def test_few_freq_points_degrades(self, tmp_path: Path) -> None:
        f_coarse = np.arange(1e7, 40.001e9, 1e9)  # 40 点 < 64 点门
        s2p = _write_s2p(tmp_path / "coarse.s2p",
                         _matched_line_s(f_coarse), f_coarse)
        rep = si_channel_report(s2p)
        assert rep["causality"]["status"] == "degraded"
        assert rep["tdr"]["status"] == "degraded"


# ---------------------------------------------------------------------------
# 判据 5：COM（4 端口全流程 / 2 端口 not_applicable / 缺装 degraded）
# ---------------------------------------------------------------------------

class TestCom:
    def test_4port_full_flow_in_band(self, tmp_path: Path) -> None:
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        rep = si_channel_report(s4p)
        com = rep["com"]
        assert com["status"] == "ok"
        # 数值合理性带（精确值不自证——COM 内核是权威）
        assert 0.0 <= com["com_db"] <= 30.0
        assert com["fb_gbaud"] == pytest.approx(25.78125)
        assert "pychopmarg" in com["params_note"]

    def test_2port_not_applicable(self, tmp_path: Path) -> None:
        s2p = _write_s2p(tmp_path / "ideal.s2p", _matched_line_s(F_HZ))
        rep = si_channel_report(s2p)
        com = rep["com"]
        assert com["status"] == "not_applicable"
        assert "4 端口" in com["note"]

    def test_pychopmarg_missing_degrades_not_raises(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        s4p = _write_s4p_decoupled_pair(tmp_path / "thru.s4p")
        monkeypatch.setitem(sys.modules, "pychopmarg", None)
        monkeypatch.setitem(sys.modules, "pychopmarg.com", None)
        monkeypatch.setitem(sys.modules, "pychopmarg.config", None)
        monkeypatch.setitem(sys.modules, "pychopmarg.config.template", None)
        rep = si_channel_report(s4p)
        assert rep["ok"] is True  # 报告本体不受 COM 段阻塞（#105）
        com = rep["com"]
        assert com["status"] == "degraded"
        assert "pychopmarg" in com["note"]
        # 其余段照常产出
        assert rep["passivity"]["status"] == "pass"
        assert rep["tdr"]["status"] == "ok"
        assert rep["provenance"]["pychopmarg_version"] is None


# ---------------------------------------------------------------------------
# 源面：run 目录 sparams.csv（掩码口径）+ CLI 冒烟
# ---------------------------------------------------------------------------

class TestSources:
    @staticmethod
    def _write_csv(path: Path, f: np.ndarray, s21: np.ndarray) -> Path:
        lines = ["freq_hz,s11_re,s11_im,s21_re,s21_im"]
        for k in range(f.size):
            lines.append(f"{f[k]:.9e},0.0,0.0,"
                         f"{s21[k].real:.9e},{s21[k].imag:.9e}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_run_dir_csv_partial_matrix_inconclusive(self, tmp_path: Path) -> None:
        # 掩码 csv（S11=0、S21=单位幅值有耗线）：已测元 ≤1+tol 但未测元
        # 不背书 → inconclusive（不冒充 PASS，#314 口径）
        run = tmp_path / "run_csv"
        run.mkdir()
        self._write_csv(run / "sparams.csv", F_HZ,
                        rc_lowpass_s21(F_HZ, 5.0, 20e-12))
        rep = si_channel_report(run)
        assert rep["ok"] is True
        assert rep["source"]["kind"] == "sparams_csv"
        assert rep["source"]["partial_matrix"] is True
        assert rep["passivity"]["basis"] == "measured_entries_upper_bound"
        assert rep["passivity"]["status"] == "inconclusive"

    def test_run_dir_csv_violation_still_fails(self, tmp_path: Path) -> None:
        run = tmp_path / "run_csv_bad"
        run.mkdir()
        self._write_csv(run / "sparams.csv", F_HZ,
                        np.abs(rc_lowpass_s21(F_HZ, 5.0, 20e-12)) * 1.5)
        rep = si_channel_report(run)
        assert rep["passivity"]["status"] == "fail"
        # 违规带 = 1.5·|H(f)| > 1+tol → f ≲ 1.747 GHz（RC=1e-10 一阶低通）
        assert rep["passivity"]["n_violations"] == 174
        assert rep["passivity"]["max_sigma_max"] == pytest.approx(1.5, abs=1e-3)

    def test_missing_source_ok_false(self, tmp_path: Path) -> None:
        rep = si_channel_report(tmp_path / "nope.s2p")
        assert rep["ok"] is False
        assert rep["errors"]

    def test_corrupt_csv_no_touchstone_fallback(self, tmp_path: Path) -> None:
        # #316：掩码载体损坏 = 证据损坏，不回退 Touchstone
        run = tmp_path / "run_bad_csv"
        run.mkdir()
        (run / "sparams.csv").write_text("freq_hz,a,b\n", encoding="utf-8")
        rep = si_channel_report(run)
        assert rep["ok"] is False
        assert "sparams.csv" in rep["errors"][0]


class TestCliSmoke:
    """CLI 薄壳冒烟（`rfauto si report`）：json/markdown/坏格式/坏源。"""

    @staticmethod
    def _make_s2p(tmp_path: Path) -> Path:
        return _write_s2p(tmp_path / "cli.s2p", _matched_line_s(F_HZ))

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        s2p = self._make_s2p(tmp_path)
        rc = CliRunner().invoke(
            app, ["si", "report", str(s2p), "--format", "json", "--passivity-tol", "0.01"])
        assert rc.exit_code == 0, rc.output
        payload = json.loads(rc.output)
        assert payload["ok"] is True
        assert payload["passivity"]["status"] == "pass"

    def test_markdown_output(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        s2p = self._make_s2p(tmp_path)
        rc = CliRunner().invoke(app, ["si", "report", str(s2p), "--format", "markdown"])
        assert rc.exit_code == 0, rc.output
        assert "# SI 通道报告" in rc.output

    def test_bad_format_exits_two(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        s2p = self._make_s2p(tmp_path)
        rc = CliRunner().invoke(app, ["si", "report", str(s2p), "--format", "xml"])
        assert rc.exit_code == 2

    def test_missing_source_exits_one(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        rc = CliRunner().invoke(
            app, ["si", "report", str(tmp_path / "nope.s2p")])
        assert rc.exit_code == 1
