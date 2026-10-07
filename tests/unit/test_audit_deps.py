"""依赖漏洞门单测（QM-4，scripts/audit_deps.py）。

离线可测面：豁免键解析（PEP503 归一）/复审日期过期语义/门判定
（evaluate 纯函数，合成 pip-audit JSON 注入，零网络零环境依赖）/
报告 schema 完整性/主入口退出码与降级路径（monkeypatch run_pip_audit）。

真跑入口：``.venv/Scripts/python.exe scripts/audit_deps.py``（需联网查
PyPI 漏洞库；首跑留档 runs/qm4/，2026-10-02）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_deps.py"

_spec = importlib.util.spec_from_file_location("audit_deps", SCRIPT)
audit_deps = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("audit_deps", audit_deps)
_spec.loader.exec_module(audit_deps)

TODAY = date(2026, 10, 2)


def _doc(*deps: dict) -> dict:
    return {"dependencies": list(deps)}


def _dep(name: str, version: str, *vulns: dict, skip_reason: str | None = None) -> dict:
    return {"name": name, "version": version, "vulns": list(vulns),
            "skip_reason": skip_reason}


def _vuln(vid: str, fix: tuple[str, ...] = ()) -> dict:
    return {"id": vid, "fix_versions": list(fix), "aliases": [f"CVE-X-{vid}"],
            "description": f"desc {vid}"}


class TestExemptTable:
    def test_normalize_name_pep503(self):
        assert audit_deps.normalize_name("Some_Pkg.Name") == "some-pkg-name"
        assert audit_deps.normalize_name("pip-audit") == "pip-audit"

    def test_lookup_by_normalized_key(self):
        table = {"some-pkg:PYSEC-1": {"reason": "r", "review_date": "2026-12-31"}}
        assert audit_deps.lookup_exempt("Some_Pkg", "PYSEC-1", table) == table["some-pkg:PYSEC-1"]
        assert audit_deps.lookup_exempt("other", "PYSEC-1", table) is None

    def test_expired_semantics(self):
        entry = {"reason": "r", "review_date": "2026-10-02"}
        assert audit_deps.exemption_expired(entry, TODAY) is False  # 当日仍有效
        assert audit_deps.exemption_expired(entry, date(2026, 10, 3)) is True
        assert audit_deps.exemption_expired({"reason": "r"}, TODAY) is True  # 缺复审日期=过期
        assert audit_deps.exemption_expired(
            {"reason": "r", "review_date": "not-a-date"}, TODAY) is True  # 坏日期=过期不静默放行


class TestEvaluate:
    def test_green_no_vulns(self):
        report = audit_deps.evaluate(_doc(_dep("numpy", "2.1.0")), today=TODAY)
        assert report["status"] == "green"
        assert report["summary"]["vulnerabilities_total"] == 0
        assert report["degradation"] == {"skipped": False, "reason": None}

    def test_unexempted_vuln_is_red(self):
        report = audit_deps.evaluate(
            _doc(_dep("flask", "2.0.1", _vuln("PYSEC-9", ("2.0.2",)))), today=TODAY)
        assert report["status"] == "red"
        assert report["summary"]["unexempted"] == 1
        v = report["vulnerabilities"][0]
        assert v["fix_versions"] == ["2.0.2"]
        assert v["exempt"] is False

    def test_valid_exemption_passes(self):
        table = {"flask:PYSEC-9": {"reason": "无修复版本，接受风险", "review_date": "2026-12-31"}}
        report = audit_deps.evaluate(
            _doc(_dep("flask", "2.0.1", _vuln("PYSEC-9"))), today=TODAY, table=table)
        assert report["status"] == "green"
        assert report["summary"]["exempted"] == 1
        v = report["vulnerabilities"][0]
        assert v["exempt"] is True
        assert v["exempt_reason"] == "无修复版本，接受风险"
        assert v["exempt_review_date"] == "2026-12-31"

    def test_expired_exemption_is_red(self):
        table = {"flask:PYSEC-9": {"reason": "旧裁决", "review_date": "2026-09-30"}}
        report = audit_deps.evaluate(
            _doc(_dep("flask", "2.0.1", _vuln("PYSEC-9"))), today=TODAY, table=table)
        assert report["status"] == "red"
        assert report["summary"]["exemptions_expired"] == 1
        assert report["vulnerabilities"][0]["exempt_expired"] is True

    def test_skip_reason_deps_counted(self):
        report = audit_deps.evaluate(
            _doc(_dep("local-pkg", "0.1", skip_reason="not on PyPI")), today=TODAY)
        assert report["summary"]["dependencies_skipped"] == 1
        assert report["skipped_dependencies"][0]["skip_reason"] == "not on PyPI"
        assert report["status"] == "green"  # 跳过≠漏洞，如实入报告不判红

    def test_report_schema_keys(self):
        report = audit_deps.evaluate(_doc(), today=TODAY)
        assert report["schema"] == audit_deps.REPORT_SCHEMA
        assert {"generated_at", "status", "mode", "pip_audit_version", "summary",
                "vulnerabilities", "skipped_dependencies", "exempt_table",
                "degradation"} <= set(report)
        assert {"dependencies_scanned", "dependencies_skipped", "vulnerabilities_total",
                "vulnerabilities_unique", "exempted", "unexempted",
                "exemptions_expired"} <= set(report["summary"])

    def test_duplicate_source_entries_counted_once(self):
        # pip-audit 双源（PyPI JSON API + OSV）同一 PYSEC 记两条——原始条目
        # 保留，unique 口径按 (归一包名, 漏洞 ID) 计 1
        doc = _doc(_dep("flask", "2.0.1", _vuln("PYSEC-9"), _vuln("PYSEC-9")))
        report = audit_deps.evaluate(doc, today=TODAY)
        assert report["summary"]["vulnerabilities_total"] == 2
        assert report["summary"]["vulnerabilities_unique"] == 1


class TestBuildCommand:
    def test_env_mode_default(self):
        cmd = audit_deps.build_command()
        assert cmd[cmd.index("--format") + 1] == "json"
        assert "--no-deps" not in cmd
        assert "-r" not in cmd

    def test_requirements_mode_no_deps(self):
        # uv export 锁面已展平全树：必须 --no-deps 直查（缺省 pip 解析撞
        # 全平台标记变体 ResolutionImpossible，2026-10-02 首跑实证）
        cmd = audit_deps.build_command("req.txt")
        assert cmd[cmd.index("-r") + 1] == "req.txt"
        assert "--no-deps" in cmd


def _run_main(monkeypatch, tmp_path, doc, table=None):
    monkeypatch.setattr(audit_deps, "run_pip_audit",
                        lambda requirements=None, timeout_s=1800: (doc, None))
    if table is not None:
        monkeypatch.setattr(audit_deps, "EXEMPT", table)
    out = tmp_path / "report.json"
    rc = audit_deps.main(["--json", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8"))


class TestMain:
    def test_green_writes_report(self, monkeypatch, tmp_path):
        rc, report = _run_main(monkeypatch, tmp_path, _doc(_dep("numpy", "2.1.0")))
        assert rc == 0
        assert report["status"] == "green"

    def test_red_exit_1_and_names_package(self, monkeypatch, tmp_path, capsys):
        rc, report = _run_main(
            monkeypatch, tmp_path, _doc(_dep("flask", "2.0.1", _vuln("PYSEC-9"))))
        assert rc == 1
        assert report["status"] == "red"
        assert "flask" in capsys.readouterr().out

    def test_raw_json_archived(self, monkeypatch, tmp_path):
        monkeypatch.setattr(audit_deps, "run_pip_audit",
                            lambda requirements=None, timeout_s=1800:
                            (_doc(_dep("numpy", "2.1.0")), None))
        raw = tmp_path / "raw.json"
        audit_deps.main(["--raw-json", str(raw)])
        assert json.loads(raw.read_text(encoding="utf-8"))["dependencies"][0]["name"] == "numpy"

    def test_degradation_skip_exit_2(self, monkeypatch, tmp_path):
        monkeypatch.setattr(audit_deps, "run_pip_audit",
                            lambda requirements=None, timeout_s=1800:
                            (None, "pip-audit 无 JSON 输出（rc=1）：connection refused"))
        out = tmp_path / "report.json"
        rc = audit_deps.main(["--json", str(out)])
        assert rc == 2  # 降级非绿非红：审计没跑成不判绿
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["status"] == "skipped"
        assert report["degradation"]["skipped"] is True
        assert "connection refused" in report["degradation"]["reason"]
