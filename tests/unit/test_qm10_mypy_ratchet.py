"""QM-10 mypy 棘轮门测试（round16 P2，J 流）。

锚树：
- 基线常量实测锚：BASELINE_ERRORS>0 且 BASELINE_META 元数据齐（数字
  与出处绑定——#97 实测不臆造；2026-10-03 实测 1709，runs/qm10_mypy/
  留证据快照）；
- 解析面：标准 summary/Success/崩溃三形态的解析（mock 子进程输出，
  单测零真跑 mypy——全仓真跑由脚本入口承担）；
- 棘轮逻辑（注入假 run_mypy）：劣化 FAIL/不劣化 PASS/改进给收紧建议/
  mypy 崩溃 ERROR/模块钉超钉 FAIL；
- 新模块出生清零钉（closed_form_oracle/publication_standards=0）；
- 模块钉 standalone 口径声明（与全仓跑不同噪声面）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "qm10_mypy_baseline", _REPO / "scripts" / "qm10_mypy_baseline.py")
assert _spec is not None and _spec.loader is not None
qm10: ModuleType = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("qm10_mypy_baseline", qm10)
_spec.loader.exec_module(qm10)


class TestBaselineConstants:
    def test_baseline_is_measured_positive_int(self):
        assert isinstance(qm10.BASELINE_ERRORS, int)
        assert qm10.BASELINE_ERRORS > 0
        assert qm10.BASELINE_ERRORS == 1709  # 2026-10-03 实测钉

    def test_baseline_meta_complete(self):
        meta = qm10.BASELINE_META
        for key in ("measured_at", "mypy_version", "python_version",
                    "files_with_errors", "checked_files"):
            assert meta.get(key), key
        assert meta["measured_at"] == "2026-10-03"

    def test_new_modules_pinned_to_zero(self):
        pins = qm10.MODULE_PINS
        assert pins["src/rfauto/core/closed_form_oracle.py"] == 0
        assert pins["src/rfauto/core/publication_standards.py"] == 0

    def test_pins_are_nonneg_ints(self):
        for mod, n in qm10.MODULE_PINS.items():
            assert isinstance(n, int) and n >= 0, mod
            assert mod.startswith("src/rfauto/"), mod


def _fake_run(n: int):
    """构造 run_mypy 替身（standalone 模式下被注入）。"""
    def fake(target, *, timeout_s=900.0):
        if n < 0:
            return {"ok": False, "errors": ["boom"], "n_errors": -1,
                    "n_files": -1, "checked_files": -1, "raw_tail": "boom"}
        return {"ok": True, "errors": [], "n_errors": n,
                "n_files": 1 if n else 0, "checked_files": 694,
                "raw_tail": f"Found {n} errors"}
    return fake


class TestRatchetLogic:
    def test_regression_fails(self, monkeypatch):
        monkeypatch.setattr(qm10, "run_mypy", _fake_run(qm10.BASELINE_ERRORS + 5))
        r = qm10.ratchet_check()
        assert r["verdict"] == "FAIL"
        assert r["full"]["delta_vs_baseline"] == 5

    def test_no_regression_passes(self, monkeypatch):
        monkeypatch.setattr(qm10, "run_mypy",
                            _fake_run(qm10.BASELINE_ERRORS - 1))
        r = qm10.ratchet_check(run_pins=False)
        assert r["verdict"] == "PASS"
        assert r["full_verdict"] == "PASS"

    def test_improvement_suggests_manual_repin(self, monkeypatch):
        monkeypatch.setattr(qm10, "run_mypy", _fake_run(10))
        r = qm10.ratchet_check(run_pins=False)
        assert r["verdict"] == "PASS"
        assert "收紧" in r["suggest"]

    def test_mypy_crash_is_error_not_fail(self, monkeypatch):
        monkeypatch.setattr(qm10, "run_mypy", _fake_run(-1))
        r = qm10.ratchet_check()
        assert r["verdict"] == "ERROR"

    def test_over_pin_fails_even_when_full_passes(self, monkeypatch):
        # 全仓不劣化但某钉超限 → 总门 FAIL（高价值模块优先钉）
        calls = {"n": 0}
        real_fake = _fake_run(qm10.BASELINE_ERRORS)

        def fake(target, *, timeout_s=900.0):
            calls["n"] += 1
            if target.endswith("quantity.py"):
                return {**real_fake(target), "n_errors": 1}
            return real_fake(target)

        monkeypatch.setattr(qm10, "run_mypy", fake)
        r = qm10.ratchet_check()
        assert r["full_verdict"] == "PASS"
        assert r["pins_verdict"] == "OVER_PIN"
        assert r["verdict"] == "FAIL"

    def test_report_is_json_serializable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(qm10, "run_mypy", _fake_run(5))
        r = qm10.ratchet_check()
        out = tmp_path / "r.json"
        out.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "FAIL"


class TestParsing:
    def test_summary_regex(self):
        m = qm10._SUMMARY_RE.search("Found 1709 errors in 331 files (checked 694 source files)")
        assert m and m.group(1) == "1709" and m.group(2) == "331"
        m2 = qm10._SUMMARY_RE.search("Found 1 error in 1 file (errors prevented further checking)")
        assert m2 and m2.group(1) == "1"

    def test_success_regex(self):
        m = qm10._OK_RE.search("Success: no issues found in 1 source file")
        assert m and m.group(1) == "1"

    def test_checked_files_regex(self):
        m = qm10._CHECKED_RE.search("Found 5 errors in 2 files (checked 694 source files)")
        assert m and m.group(1) == "694"
