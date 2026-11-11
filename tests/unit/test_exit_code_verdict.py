"""退出码判读统一前置条款内核 + 三 adapter 接入测试（aurora_r R-21/P4-1-1）。

"退出码 0 不足信 + 日志 fatal-marker 白名单复核"（PANDA/virtuoso-agent/
OpenROAD/terminal-bench 四仓横向观察② 思想级吸收，零代码搬运；
runs/aurora_r/p4_survey/RAW_P4_A.md）——覆盖：

- 判读内核正负例（rc 门 / rc=0+marker 假绿拦截 / rc=None 无 rc 通道）；
- 词边界误报回归（FATALITY_RATE 不命中 fatal；openEMS 健康日志良性
  Error 行真机实录不命中族集；健康 hpeesofsim 行不命中 ADS 族）；
- 截断策略（HEAD+TAIL 双行窗：头部/尾部 fatal 双向可达 + 中段整行丢弃
  显式语义；MAX_FATAL_HITS 截停）；
- 三 adapter 合成日志注入（spice run_ngspice / ads_python_api
  run_simulation / openems_solver solve——各含零变化面与加严面）；
- pattern 单源化钉（现行字面量逐字符钉 + 消费点源码钉 + not_applicable
  面 pin + provenance 非空钉 + DEFAULT 全族并集等式钉）。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters import spice_netlist as sn
from rfauto.adapters.ads_python_api import AdsPythonApiAdapter
from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
from rfauto.adapters.openems_solver import OpenEMSSolver
from rfauto.core.exit_code_verdict import (
    DEFAULT_FATAL_MARKERS,
    FAMILY_ADS,
    FAMILY_HFSS,
    FAMILY_OPENEMS,
    FAMILY_SPECTRE,
    FAMILY_SPICE,
    HFSS_BATCH_EXTRACT_FATAL,
    MAX_FATAL_HITS,
    PYTHON_TRACEBACK,
    SPICE_FATAL_PATTERN,
    SPICE_FLAG_LINE_PATTERN,
    FatalMarker,
    evaluate_exit_code,
)

_REPO = Path(__file__).resolve().parents[2]

# 真机实录形态（接地，R-21 席位逐文件核证）
_OPENEMS_BENIGN_HEALTH_LINE = (
    "ProcessModeMatch::InitProcess(): Error loading mode file "
    "'slot_mode_E.h5', disabling probe."
)
_HPEESOFSIM_CLEAN_LINE = "***** Simulation finished at Sat Aug 29 21:52:58 2026"
_HPEESOFSIM_PARSE_ERROR = "Error detected by hpeesofsim during netlist parsing."
_HPEESOFSIM_LICENSE = "Linear features are not licensed"
_HPEESOFSIM_TERMINATED = "hpeesofsim terminated due to an error."
_OPENEMS_MUR_SKIP = (
    "Mur ABC Extension is not compatible with cylinder-coords!! skipping"
)


# ── 内核正负例 ──────────────────────────────────────────────────────────────

class TestKernelBasics:
    def test_rc_zero_clean_ok(self):
        v = evaluate_exit_code(0, "all good\n", "",
                               fatal_marker_patterns=FAMILY_ADS)
        assert v.ok is True
        assert v.exit_code == 0
        assert v.fatal_hits == ()
        assert "零命中" in v.note

    def test_rc_nonzero_fails_even_clean(self):
        v = evaluate_exit_code(3, "", "", fatal_marker_patterns=FAMILY_ADS)
        assert v.ok is False
        assert v.exit_code == 3
        assert "rc=3" in v.note

    def test_rc_zero_with_marker_fails_fail_closed(self):
        v = evaluate_exit_code(0, f"progress\n{_HPEESOFSIM_PARSE_ERROR}\n",
                               "", fatal_marker_patterns=FAMILY_ADS)
        assert v.ok is False
        assert len(v.fatal_hits) == 1
        h = v.fatal_hits[0]
        assert h.source == "stdout"
        assert h.pattern == "hpeesofsim_error_detected"
        assert h.line == 2
        assert "Error detected" in h.snippet
        assert "退出码 0 不足信" in v.note

    def test_marker_in_stderr_reported_with_source(self):
        v = evaluate_exit_code(0, "", f"note\n{_HPEESOFSIM_TERMINATED}\n",
                               fatal_marker_patterns=FAMILY_ADS)
        assert v.ok is False
        assert v.fatal_hits[0].source == "stderr"
        assert v.fatal_hits[0].line == 2

    def test_rc_nonzero_reports_hits_as_diagnostics(self):
        v = evaluate_exit_code(120, f"{_HPEESOFSIM_LICENSE}\n", "",
                               fatal_marker_patterns=FAMILY_ADS)
        assert v.ok is False
        assert len(v.fatal_hits) == 1
        assert "rc=120" in v.note and "命中 1 处" in v.note

    def test_rc_none_clean_ok_no_rc_channel(self):
        v = evaluate_exit_code(None, "ok\n", "",
                               fatal_marker_patterns=FAMILY_OPENEMS)
        assert v.ok is True
        assert v.exit_code is None
        assert "无 rc 通道" in v.note

    def test_rc_none_with_hit_fails(self):
        v = evaluate_exit_code(None, f"{_OPENEMS_MUR_SKIP}\n", "",
                               fatal_marker_patterns=FAMILY_OPENEMS)
        assert v.ok is False

    def test_bare_string_patterns_rejected(self):
        with pytest.raises(TypeError, match="FatalMarker"):
            evaluate_exit_code(0, "x", "", fatal_marker_patterns=["fatal"])

    def test_envelope_stable_key_order(self):
        v = evaluate_exit_code(0, "x", "", fatal_marker_patterns=FAMILY_ADS)
        assert list(v.as_dict().keys()) == ["ok", "exit_code",
                                            "fatal_hits", "note"]
        d = v.as_dict()
        assert isinstance(d["fatal_hits"], list)

    def test_default_union_equals_all_families_plus_generic(self):
        members = (set(FAMILY_SPICE) | set(FAMILY_ADS) | set(FAMILY_OPENEMS)
                   | set(FAMILY_SPECTRE) | set(FAMILY_HFSS)
                   | {PYTHON_TRACEBACK})
        assert set(DEFAULT_FATAL_MARKERS) == members


# ── 词边界误报回归（真机实录形态）─────────────────────────────────────────

class TestWordBoundary:
    def test_fatility_rate_no_hit_spectre_family(self):
        v = evaluate_exit_code(0, "FATALITY_RATE = 0.42\n", "",
                               fatal_marker_patterns=FAMILY_SPECTRE)
        assert v.ok is True
        assert v.fatal_hits == ()

    def test_openems_benign_health_log_no_hit_family(self):
        # 真机实录 runs/aurora_c_oe/slotline/_last_stderr.log——良性 Error
        # 形态不在 openEMS 族白名单（族集不含通用 Error 词的接地理由）。
        v = evaluate_exit_code(0, f"{_OPENEMS_BENIGN_HEALTH_LINE}\n", "",
                               fatal_marker_patterns=FAMILY_OPENEMS)
        assert v.ok is True
        assert v.fatal_hits == ()

    def test_benign_line_hits_under_default_union_family_discipline(self):
        # 同一行在缺省并集（含 spice 族 \bError\b）下命中——钉"通道判读点
        # 必须传本通道族集"的纪律依据（跨族混扫=真机实录级误报）。
        v = evaluate_exit_code(0, f"{_OPENEMS_BENIGN_HEALTH_LINE}\n", "")
        assert v.ok is False

    def test_ads_clean_finished_line_no_hit(self):
        v = evaluate_exit_code(0, f"{_HPEESOFSIM_CLEAN_LINE}\n", "",
                               fatal_marker_patterns=FAMILY_ADS)
        assert v.ok is True

    def test_spectre_fatal_word_hit_positive(self):
        # 官方 PDF p895 逐字 '$fatal ... Fatal message. Abort simulation.'
        v = evaluate_exit_code(0, "Fatal message. Abort simulation.\n", "",
                               fatal_marker_patterns=FAMILY_SPECTRE)
        assert v.ok is False
        assert v.fatal_hits[0].pattern == "spectre_fatal_severity"

    def test_python_traceback_belt_hit(self):
        v = evaluate_exit_code(0, "Traceback (most recent call last):\n", "")
        assert v.ok is False
        assert v.fatal_hits[0].pattern == "python_traceback"


# ── 截断策略（HEAD+TAIL 双行窗，显式口径）─────────────────────────────────

def _filler_lines(n: int, width: int = 30) -> str:
    return "".join(f"filler line {i:04d} {'x' * (width - 15)}\n"
                   for i in range(n))


class TestTruncationPolicy:
    _LIMIT = 200

    def test_head_marker_found_after_truncation(self):
        # 重派修正回归：首派稿 TAIL 单窗头部 fatal 落丢弃段=漏报假绿；
        # 双行窗下头部命中必须可达（fail-closed）。
        text = ("head line 0\nhead line 1\n"
                + _HPEESOFSIM_PARSE_ERROR + "\n" + _filler_lines(80))
        v = evaluate_exit_code(0, text, "",
                               fatal_marker_patterns=FAMILY_ADS,
                               stdout_limit=self._LIMIT)
        assert v.ok is False
        assert v.fatal_hits[0].line == 3
        assert "截断" in v.note

    def test_tail_marker_found_with_absolute_line_number(self):
        text = _filler_lines(80) + _HPEESOFSIM_TERMINATED + "\n"
        total_lines = len(text.splitlines())
        v = evaluate_exit_code(0, text, "",
                               fatal_marker_patterns=FAMILY_ADS,
                               stdout_limit=self._LIMIT)
        assert v.ok is False
        assert v.fatal_hits[0].line == total_lines
        assert v.fatal_hits[0].line == 81

    def test_middle_only_marker_dropped_with_explicit_note(self):
        # 显式语义：双窗之间中段整行丢弃（单行口径 marker；note 注明截断）。
        text = (_filler_lines(8) + _HPEESOFSIM_PARSE_ERROR + "\n"
                + _filler_lines(60))
        v = evaluate_exit_code(0, text, "",
                               fatal_marker_patterns=FAMILY_ADS,
                               stdout_limit=self._LIMIT)
        assert v.ok is True
        assert v.fatal_hits == ()
        assert "截断" in v.note

    def test_within_budget_no_truncation_note(self):
        text = _filler_lines(3)
        v = evaluate_exit_code(0, text, "",
                               fatal_marker_patterns=FAMILY_ADS,
                               stdout_limit=self._LIMIT)
        assert "截断" not in v.note

    def test_hits_cap_stops_scan(self):
        text = "".join(f"fatal line {i}\n" for i in range(MAX_FATAL_HITS + 6))
        v = evaluate_exit_code(0, text, "",
                               fatal_marker_patterns=FAMILY_SPECTRE)
        assert v.ok is False
        assert len(v.fatal_hits) == MAX_FATAL_HITS
        assert "截停" in v.note


# ── spice 家族接入（run_ngspice 合成日志注入 + 单源化钉）──────────────────

class TestSpiceWiring:
    @staticmethod
    def _fake_proc(stdout: str, stderr: str = "", rc: int = 0):
        def _run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, rc, stdout=stdout,
                                               stderr=stderr)
        return _run

    def test_run_ngspice_collects_error_line_rc_zero(self, tmp_path,
                                                     monkeypatch):
        # rc=0 + "Error: ..."（.four 失败真机形态）——旗标行收集必须走
        # 单源 pattern（现行判读，零变化面）。
        deck = tmp_path / "x.cir"
        deck.write_text("* dummy\n", encoding="ascii")
        monkeypatch.setattr("subprocess.run",
                            self._fake_proc("Error: unknown device\n"))
        res = sn.run_ngspice(deck)
        assert res["returncode"] == 0
        assert res["errors"] == ["Error: unknown device"]

    def test_warning_collected_but_not_fatal(self, tmp_path, monkeypatch):
        # warning 进 errors 仅收集不判死（现行口径，零变化面）；
        # fatal 复扫 pattern 对 warning 行零命中。
        deck = tmp_path / "x.cir"
        deck.write_text("* dummy\n", encoding="ascii")
        monkeypatch.setattr(
            "subprocess.run",
            self._fake_proc("warning: node v1 floating\nall done\n"))
        res = sn.run_ngspice(deck)
        assert res["errors"] == ["warning: node v1 floating"]
        assert re.search(SPICE_FATAL_PATTERN, res["errors"][0],
                         re.IGNORECASE) is None

    def test_ac_dual_gate_blocks_rc_zero_fatal_injection(self, tmp_path,
                                                         monkeypatch):
        # 合成注入：rc=0 + errors 带 Error 行 → 双门拦截（现行判读，经
        # 单源 SPICE_FATAL_PATTERN 复扫；与既有
        # test_spice_netlist.py::test_run_fails_loudly_on_ngspice_error
        # 同型，此处钉单源化后同语义）。
        sp = tmp_path / "dut.sp"
        sp.write_text(".SUBCKT dut p1 p2\nR1 p1 p2 1.0\n.ENDS dut\n",
                      encoding="ascii")

        def _bad(deck_path, *, exe=None, timeout_s=300.0):
            return {"stdout": "Error: unknown device", "stderr": "",
                    "returncode": 0, "errors": ["Error: unknown device"]}

        monkeypatch.setattr(sn, "run_ngspice", _bad)
        freq = np.linspace(1e9, 2e9, 3)
        with pytest.raises(sn.NgspiceAcError, match="运行失败"):
            sn.run_ngspice_ac_sparam(sp, freq, [50.0, 50.0],
                                     work_dir=tmp_path / "wd")

    def test_patterns_single_sourced_literals(self):
        # 现行字面量逐字符钉（单源化收编零漂移）。
        assert SPICE_FATAL_PATTERN == r"\b(Error|failed)\b"
        assert SPICE_FLAG_LINE_PATTERN == r"\b(Error|failed|warning)\b"

    def test_spice_netlist_consumes_kernel_patterns(self):
        # 消费点源码钉：本地字面量已收编，判读点引用内核单源。
        src = (_REPO / "src" / "rfauto" / "adapters"
               / "spice_netlist.py").read_text(encoding="utf-8")
        assert "SPICE_FLAG_LINE_PATTERN" in src
        assert "SPICE_FATAL_PATTERN" in src
        assert r"\b(Error|failed|warning)\b" not in src
        assert r"\b(Error|failed)\b" not in src


# ── ADS/hpeesofsim A 档接入（run_simulation 合成日志注入）─────────────────

class TestAdsPythonApiWiring:
    @staticmethod
    def _adapter(tmp_path: Path) -> AdsPythonApiAdapter:
        (tmp_path / "bin").mkdir(exist_ok=True)
        (tmp_path / "bin" / "hpeesofsim.exe").write_text("", encoding="utf-8")
        adapter = AdsPythonApiAdapter(ads_dir=tmp_path)
        adapter._connected = True  # 跳过 connect()（真机探活不进单测）
        return adapter

    @staticmethod
    def _fake_run(rc: int, stdout: str, stderr: str = ""):
        def _run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, rc, stdout=stdout,
                                               stderr=stderr)
        return _run

    def test_rc_zero_with_fatal_marker_fails(self, tmp_path, monkeypatch):
        # 加严面：rc=0 + 真机实录 fatal 形态（parse error + terminated）
        # → ok 门 fail-closed（现行纯 rc 门此处假绿）。
        netlist = tmp_path / "netlist.txt"
        netlist.write_text("synthesis\n", encoding="ascii")
        monkeypatch.setattr(
            "subprocess.run",
            self._fake_run(0, f"{_HPEESOFSIM_PARSE_ERROR}\n",
                           f"{_HPEESOFSIM_TERMINATED}\n"))
        res = self._adapter(tmp_path).run_simulation(str(netlist))
        assert res["ok"] is False
        assert res["returncode"] == 0
        verdict = res["verdict"]
        assert verdict["ok"] is False
        labels = {h["pattern"] for h in verdict["fatal_hits"]}
        assert labels == {"hpeesofsim_error_detected",
                          "hpeesofsim_terminated"}
        assert all(h["source"] in ("stdout", "stderr")
                   for h in verdict["fatal_hits"])
        assert "退出码 0 不足信" in verdict["note"]

    def test_rc_zero_clean_ok_unchanged(self, tmp_path, monkeypatch):
        # 零变化面：干净输出 + rc=0 → ok≡(rc==0)，verdict 信封随行落档。
        netlist = tmp_path / "netlist.txt"
        netlist.write_text("synthesis\n", encoding="ascii")
        monkeypatch.setattr(
            "subprocess.run",
            self._fake_run(0, f"{_HPEESOFSIM_CLEAN_LINE}\n"))
        res = self._adapter(tmp_path).run_simulation(str(netlist))
        assert res["ok"] is True
        assert res["verdict"]["ok"] is True
        assert res["verdict"]["fatal_hits"] == []
        assert res["returncode"] == 0

    def test_rc_nonzero_with_license_marker(self, tmp_path, monkeypatch):
        # 真机实录 exit 120 + not licensed → rc 门与 marker 门同报。
        netlist = tmp_path / "netlist.txt"
        netlist.write_text("synthesis\n", encoding="ascii")
        monkeypatch.setattr(
            "subprocess.run",
            self._fake_run(120, f"Error detected by hpeesofsim during "
                             f"circuit set up.\n{_HPEESOFSIM_LICENSE}\n"))
        res = self._adapter(tmp_path).run_simulation(str(netlist))
        assert res["ok"] is False
        assert res["returncode"] == 120
        assert res["verdict"]["exit_code"] == 120


# ── openEMS exe 子进程形态接入（solve 合成日志注入）───────────────────────

class TestOpenemsSolverWiring:
    @staticmethod
    def _solver(tmp_path: Path) -> OpenEMSSolver:
        config = EMSolverConfig(
            solver_type=EMSolverType.OPENEMS,
            working_dir=str(tmp_path / "openems_run"),
        )
        s = OpenEMSSolver(config)
        s._exe_path = str(tmp_path / "openEMS.exe")
        (tmp_path / "openEMS.exe").write_text("", encoding="utf-8")
        assert s.connect()
        # 缓存目录放进 tmp_path，避免污染工作区 runs/（#144 家族纪律）
        s._config.extra_params["cache"] = False
        s._config.extra_params["cache_dir"] = str(tmp_path / "cache")
        s.build_geometry({"template": "wilkinson", "params": {"f0_ghz": 2.4}})
        return s

    @staticmethod
    def _write_csv(run_dir: Path) -> None:
        lines = [
            "freq_hz,re_S11,im_S11,re_S21,im_S21",
            "2e9,0.05,0.0,0.7,0.0",
            "3e9,0.1,0.0,0.6,0.0",
        ]
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "sparams.csv").write_text("\n".join(lines), encoding="utf-8")

    def test_rc_zero_with_mur_skip_marker_fails_despite_products(
            self, tmp_path, monkeypatch):
        # 加严面（P4-1-1 核心）：rc=0 + #232 柱坐标 MUR skipping 静默退化
        # + CSV 已完整落盘 → 产物在也判失败（现行判读此处假绿）。
        def fake_run(cmd, **kw):
            self._write_csv(Path(kw["cwd"]))
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"banner\n{_OPENEMS_MUR_SKIP}\ndone\n",
                stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        r = self._solver(tmp_path).solve()
        assert r.success is False
        assert "退出码 0 不足信" in r.message
        assert "openems_mur_cylinder_skip" in r.message
        assert (tmp_path / "openems_run" / "_last_stderr.log").is_file()

    def test_rc_zero_clean_with_csv_unchanged(self, tmp_path, monkeypatch):
        # 零变化面：干净日志 + rc=0 + CSV → 现行成功路径逐字节不变。
        def fake_run(cmd, **kw):
            self._write_csv(Path(kw["cwd"]))
            return subprocess.CompletedProcess(cmd, 0, stdout="all done\n",
                                               stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        r = self._solver(tmp_path).solve()
        assert r.success is True
        assert r.s_params.shape == (2, 2, 2)

    def test_rc_nonzero_products_first_face_unchanged(self, tmp_path,
                                                      monkeypatch):
        # 零变化面：rc≠0 + 干净日志 + CSV 完整 → 产物优先分支照旧接受
        # （2026-09-04 绑定库退出段非零实测判读不动）。
        def fake_run(cmd, **kw):
            self._write_csv(Path(kw["cwd"]))
            return subprocess.CompletedProcess(cmd, 1, stdout="ok-out\n",
                                               stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        r = self._solver(tmp_path).solve()
        assert r.success is True

    def test_excitation_inside_mur_marker_also_gated(self, tmp_path,
                                                     monkeypatch):
        # #253 坑 A 形态同门（族集第二条 marker）。
        def fake_run(cmd, **kw):
            self._write_csv(Path(kw["cwd"]))
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Excitation inside Mur-ABC region\n", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        r = self._solver(tmp_path).solve()
        assert r.success is False
        assert "openems_excitation_inside_mur" in r.message


# ── not_applicable 面 + marker 表接地钉 ──────────────────────────────────

class TestNotApplicableAndGrounding:
    def test_inprocess_fdtd_not_wired(self):
        # 进程内 FDTD.Run（openems_adapter 渲染脚本内联形态）无 rc 通道
        # ——如实 not_applicable 不强接（源码钉：该文件零内核引用）。
        src = (_REPO / "src" / "rfauto" / "adapters"
               / "openems_adapter.py").read_text(encoding="utf-8")
        assert "exit_code_verdict" not in src

    def test_hfss_batch_fatal_banner_read_only_reference(self):
        # hfss_batch 本体禁改未动——横幅原文在档（源码钉接地）+ marker
        # 与现行横幅逐字符相配（只读引用收编）。
        src = (_REPO / "src" / "rfauto" / "adapters"
               / "hfss_batch.py").read_text(encoding="utf-8")
        assert '"[rfauto-batch-extract] FATAL: "' in src
        hit = HFSS_BATCH_EXTRACT_FATAL and re.search(
            HFSS_BATCH_EXTRACT_FATAL.pattern,
            "[rfauto-batch-extract] FATAL: project missing")
        assert hit is not None

    def test_every_default_marker_has_provenance(self):
        # 不许凭记忆编：缺省表每条必须带接地实据（provenance 非空）。
        for m in DEFAULT_FATAL_MARKERS:
            assert isinstance(m, FatalMarker)
            assert m.label and m.pattern and m.provenance.strip(), m.label

    def test_kernel_module_no_all_private_face(self):
        # 无 __all__ 的非门面文件不进 public_api 快照（零漂移纪律）。
        import rfauto.core.exit_code_verdict as verdict_mod

        assert not hasattr(verdict_mod, "__all__")

    def test_verdict_type_is_frozen_dataclass(self):
        v = evaluate_exit_code(0, "", "")
        with pytest.raises(FrozenInstanceError):
            v.ok = True  # frozen: 无法就地改判（fail-closed 判读不可变）
