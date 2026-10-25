"""sleep-AST 常驻守卫 + 门口径 v2 durations 分层（2026-10-11 W2-D 清偿批）。

覆盖面（开发注记 八百八十三 v2 采纳批 ④ followUp 两半）：
- TestSleepAudit：scripts/audit_test_sleeps.py——AST 结构判定（数值字面量
  sleep(N>阈值) 违例；字符串模板/变量实参零误报；阈值严格大于；属性与
  from-import 双形态；--allow 豁免；main rc 语义 0/1/2）；
- TestGateDurations：scripts/wf_gate_full_v2.py——_parse_durations 实测
  表形态解析（s/ms 双单位、同测多相取 max）、durations_tier_lines 分层
  （60/10/1s 三层计数+top 明细）、_parse_summary 与 durations 表共存
  不受扰（#355 数字源兼容钉）、_run_segment 真子进程冒烟（--durations
  接线确实落日志且汇总解析不受扰）。

脚本经 importlib spec 装载（scripts 非包，test_check_numbers 同款口径）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{name}_w2d", _REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sleeps = _load_script("audit_test_sleeps")
gate_v2 = _load_script("wf_gate_full_v2")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# sleep-AST 守卫
# ---------------------------------------------------------------------------

class TestSleepAudit:
    def test_literal_sleep_over_threshold_detected(self, tmp_path):
        _write(tmp_path / "test_a.py",
               "import time\n"
               "def test_x():\n"
               "    time.sleep(20)\n"
               "    assert True\n")
        v = sleeps.scan_tree(tmp_path, 10.0)
        assert len(v) == 1
        assert v[0]["seconds"] == 20.0
        assert v[0]["line"] == 3

    def test_threshold_is_strictly_greater(self, tmp_path):
        """登记口径 N>10：恰好 10 不违例，10.5 违例。"""
        _write(tmp_path / "test_a.py",
               "import time\n"
               "def test_a():\n"
               "    time.sleep(10)\n\n"
               "def test_b():\n"
               "    time.sleep(10.5)\n")
        v = sleeps.scan_tree(tmp_path, 10.0)
        assert [x["seconds"] for x in v] == [10.5]

    def test_dynamic_and_template_args_zero_false_positive(self, tmp_path):
        """变量实参（静态不可判）与字符串模板内 sleep（AST Call 面之外）
        均不报——零误报红线；后者即 test_w2_a_dag.py 现树形态。"""
        _write(tmp_path / "test_dyn.py",
               "import time\n"
               "TEMPLATE = 'import time; time.sleep(600)\\n'\n"
               "def test_x(interval):\n"
               "    time.sleep(interval)\n")
        assert sleeps.scan_tree(tmp_path, 10.0) == []

    def test_from_import_and_attribute_forms(self, tmp_path):
        _write(tmp_path / "test_fi.py",
               "from time import sleep\n"
               "import asyncio\n"
               "def test_x():\n"
               "    sleep(99)\n\n"
               "async def test_y():\n"
               "    await asyncio.sleep(88)\n")
        v = sleeps.scan_tree(tmp_path, 10.0)
        assert sorted(x["seconds"] for x in v) == [88.0, 99.0]

    def test_allow_suppresses_by_name_or_suffix(self, tmp_path):
        _write(tmp_path / "sub" / "test_real.py",
               "import time\ndef test_x():\n    time.sleep(30)\n")
        v_all = sleeps.scan_tree(tmp_path, 10.0)
        assert len(v_all) == 1
        rel = v_all[0]["file"]
        # 路径尾段豁免
        assert sleeps.scan_tree(tmp_path, 10.0, (rel,)) == []
        # 文件名豁免
        assert sleeps.scan_tree(tmp_path, 10.0, ("test_real.py",)) == []

    def test_parse_error_is_fail_closed_violation(self, tmp_path):
        _write(tmp_path / "test_bad.py", "def broken(:\n")
        v = sleeps.scan_tree(tmp_path, 10.0)
        assert len(v) == 1 and "AST 解析失败" in str(v[0]["source"])

    def test_main_rc_semantics(self, tmp_path):
        clean = tmp_path / "clean"
        _write(clean / "test_c.py",
               "import time\ndef test_x():\n    time.sleep(0.5)\n")
        assert sleeps.main(["--tests-dir", str(clean)]) == 0
        dirty = tmp_path / "dirty"
        _write(dirty / "test_d.py",
               "import time\ndef test_x():\n    time.sleep(42)\n")
        assert sleeps.main(["--tests-dir", str(dirty)]) == 1
        assert sleeps.main(["--tests-dir", str(tmp_path / "nope")]) == 2

    def test_main_json_envelope(self, tmp_path, capsys):
        dirty = tmp_path / "dirty"
        _write(dirty / "test_d.py",
               "import time\ndef test_x():\n    time.sleep(42)\n")
        assert sleeps.main(["--tests-dir", str(dirty), "--json"]) == 1
        doc = json.loads(capsys.readouterr().out)
        assert doc["ok"] is False
        assert doc["n_violations"] == 1
        assert doc["violations"][0]["seconds"] == 42.0

    def test_real_tests_tree_clean(self):
        """现树出生绿钉（零误报）：全 tests 树零 sleep(N>10) 违例——
        test_w2_a_dag 的 sleep(600) 在字符串模板内不得命中。"""
        assert sleeps.main(["--tests-dir", str(_REPO / "tests")]) == 0


# ---------------------------------------------------------------------------
# 门口径 v2 durations 分层
# ---------------------------------------------------------------------------

_DUR_SAMPLE = (
    "============================ slowest 20 durations "
    "============================\n"
    "0.30s call     tests/unit/test_probe.py::test_slow\n"
    "120.50s call     tests/unit/test_big.py::test_huge\n"
    "15.00s setup     tests/unit/test_big.py::test_huge\n"
    "3.25s call     tests/unit/test_mid.py::test_mid\n"
    "5ms call     tests/unit/test_probe.py::test_fast\n"
    "\n"
    "(1 durations < 0.005s hidden.  Use -vv to show these durations.)\n"
    "2 passed in 0.44s\n")


class TestGateDurations:
    def test_parse_durations_units_and_max_phase(self):
        d = gate_v2._parse_durations(_DUR_SAMPLE)
        # 同测多相取 max：test_huge = max(120.50 call, 15.00 setup)
        assert d["tests/unit/test_big.py::test_huge"] == 120.5
        assert d["tests/unit/test_probe.py::test_slow"] == pytest.approx(0.3)
        # ms 单位换算
        assert d["tests/unit/test_probe.py::test_fast"] == pytest.approx(0.005)
        # hidden 注记与汇总行不进表
        assert len(d) == 4

    def test_parse_summary_unaffected_by_durations_table(self):
        """#355 数字源兼容钉：durations 表行不得被当汇总行（末次匹配语义
        仍落在真汇总行 '2 passed in 0.44s'）。"""
        p, f, s = gate_v2._parse_summary(_DUR_SAMPLE)
        assert (p, f, s) == (2, 0, 0)

    def test_tier_lines_counts_and_top_detail(self):
        d = gate_v2._parse_durations(_DUR_SAMPLE)
        lines = gate_v2.durations_tier_lines(d, top=2)
        assert lines[0].startswith("# DURATIONS 分层")
        # 层级计数（max 相聚合后：120.5 / 3.25 / 0.3 / 0.005——15s setup
        # 归并进同测 120.5s call，不计独立层）
        assert ">=60s=1" in lines[0]
        assert "10-60s=0" in lines[0]
        assert "1-10s=1" in lines[0]
        assert "<1s=2" in lines[0]
        # top 明细截断生效且降序
        detail = [ln for ln in lines if ln.startswith("# DUR ")]
        assert len(detail) == 2
        assert "test_huge" in detail[0]
        assert "test_mid" in detail[1]
        # 数字源兼容：报告行不带 passed/failed 字样
        assert all("passed" not in ln and "failed" not in ln
                   for ln in lines)

    def test_tier_lines_empty(self):
        assert gate_v2.durations_tier_lines({}) == []

    def test_run_segment_wires_durations(self, tmp_path, monkeypatch):
        """真子进程冒烟：--durations=20 确实进段日志（接线不在场即红），
        且 _parse_summary 在含 durations 表的真实日志上不受扰。"""
        tfile = _write(tmp_path / "test_mini.py",
                       "import time\n"
                       "def test_ok():\n"
                       "    time.sleep(0.05)\n"
                       "    assert 1 == 1\n")
        monkeypatch.setattr(gate_v2, "REPO_ROOT", tmp_path)
        res = gate_v2._run_segment([str(tfile)],
                                   tmp_path / "seg.log", tmp_path / "seg.xml")
        assert res["rc"] == 0
        assert res["passed"] == 1 and res["failed"] == 0
        log_text = (tmp_path / "seg.log").read_text(encoding="utf-8")
        assert "durations" in log_text  # --durations 接线证据
        assert res["durations"], "段日志应解析出 durations 表"
        tiers = gate_v2.durations_tier_lines(res["durations"])
        assert tiers and tiers[0].startswith("# DURATIONS 分层")
