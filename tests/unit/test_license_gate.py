"""许可合规门脚本单测（r4 P-3，scripts/license_gate.py）。

最小 dry-call 钉（df4②：备妥未跑=零价值）：门判定逻辑用合成许可行
注入（monkeypatch collect_rows，零环境依赖零网络），覆盖 ALLOWED 家族
匹配/词边界/全文签名/EXEMPT 豁免/UNKNOWN 处置与退出码。

真跑入口：``.venv/Scripts/python.exe scripts/license_gate.py``（CI
licenses job 同款命令，2026-09-28 批 B1 P-3 接线）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "license_gate.py"

_spec = importlib.util.spec_from_file_location("license_gate", SCRIPT)
license_gate = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("license_gate", license_gate)
_spec.loader.exec_module(license_gate)


class TestFamilyMatch:
    def test_word_boundary(self):
        assert license_gate._family_match("MIT", "MIT License")
        assert license_gate._family_match("Apache", "Apache Software License")
        # 词边界："ML" 不得撞 "html"/"MLP" 类子串（审查轨 C P2-9）
        assert not license_gate._family_match("ML", "html5lib")
        assert not license_gate._family_match("ML", "Eclipse Public License")

    def test_text_signature_mit_without_token(self):
        # MIT 正文许可文本不含 "MIT" 字样——全文签名兜底匹配
        text = ("Permission is hereby granted, free of charge, to any person "
                "obtaining a copy of this software...")
        assert license_gate._family_match("MIT", text)
        assert not license_gate._family_match("MIT", "all rights reserved")

    def test_case_insensitive_substring_family(self):
        assert license_gate._family_match("MPL", "MPL-2.0")
        assert license_gate._family_match("mozilla", "Mozilla Public License 2.0")


class TestNormalizeName:
    def test_pep503(self):
        assert license_gate.normalize_name("openEMS") == "openems"
        assert license_gate.normalize_name("netgen-occt") == "netgen-occt"
        assert license_gate.normalize_name("NetGen_OCCT") == "netgen-occt"


def _run_gate(monkeypatch, rows: list[dict[str, str]]) -> int:
    monkeypatch.setattr(license_gate, "collect_rows", lambda: rows)
    monkeypatch.setattr(sys, "argv", ["license_gate.py"])
    return license_gate.main()


class TestGateDecision:
    def test_all_allowed_passes(self, monkeypatch, capsys):
        rc = _run_gate(monkeypatch, [
            {"Name": "numpy", "Version": "1", "License": "BSD-3-Clause"},
            {"Name": "fastmcp", "Version": "1", "License": "Apache-2.0"},
        ])
        assert rc == 0

    def test_violation_fails_and_names_package(self, monkeypatch, capsys):
        rc = _run_gate(monkeypatch, [
            {"Name": "somegpl", "Version": "1", "License": "GPL-3.0-or-later"},
        ])
        assert rc == 1
        assert "somegpl" in capsys.readouterr().out

    def test_unknown_fails_unless_exempt(self, monkeypatch, capsys):
        rc = _run_gate(monkeypatch, [
            {"Name": "mystery-pkg", "Version": "1", "License": "UNKNOWN"},
        ])
        assert rc == 1
        rc2 = _run_gate(monkeypatch, [
            {"Name": "openEMS", "Version": "1", "License": ""},
        ])
        assert rc2 == 0  # EXEMPT 豁免（裁决注记在表内）

    def test_weak_copyleft_tagged(self, monkeypatch, capsys):
        rc = _run_gate(monkeypatch, [
            {"Name": "leftpkg", "Version": "1", "License": "LGPL-2.1+"},
        ])
        assert rc == 1
        assert "弱copyleft待裁决" in capsys.readouterr().out
