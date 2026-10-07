"""QW-6 术语卡测试：YAML schema 校验 + service 三函数正负例 + MCP resource
注册面冒烟（照 test_mcp_server.TestMCPResources 形态）。

数据单一事实源：knowledge/terminology.yaml；MCP resource 与 service 同源
（mcp_server.terminology_resource 读同一文件原文结构）。
"""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERMINOLOGY_PATH = _REPO_ROOT / "knowledge" / "terminology.yaml"

_ALLOWED_KEYS = {"term", "definition", "unit", "scope", "see_also"}
_REQUIRED_KEYS = {"term", "definition"}
_ALLOWED_SCOPES = {
    "general",
    "antenna",
    "port",
    "engine",
    "resonator",
    "measurement",
    "mimo",
}


@pytest.fixture()
def terminology_service():
    from rfauto.service import terminology_service as svc

    return svc


class TestTerminologyYaml:
    """knowledge/terminology.yaml 全条目 schema 校验。"""

    @pytest.fixture()
    def data(self) -> dict:
        with open(_TERMINOLOGY_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_file_exists(self):
        assert _TERMINOLOGY_PATH.exists()

    def test_top_level_structure(self, data):
        assert isinstance(data, dict)
        assert isinstance(data.get("terms"), list)

    def test_first_version_size(self, data):
        # 任务书首版口径：30-50 条
        assert 30 <= len(data["terms"]) <= 50

    def test_required_fields_nonempty(self, data):
        for t in data["terms"]:
            assert set(t) >= _REQUIRED_KEYS, f"缺必填键: {t.get('term')!r}"
            assert isinstance(t["term"], str) and t["term"].strip()
            assert isinstance(t["definition"], str) and t["definition"].strip()

    def test_optional_fields_allowlist(self, data):
        for t in data["terms"]:
            extra = set(t) - _ALLOWED_KEYS
            assert not extra, f"未知键 {extra!r}（schema: term/definition/unit/scope/see_also）"

    def test_term_unique_case_insensitive(self, data):
        names = [str(t["term"]).strip().lower() for t in data["terms"]]
        assert len(names) == len(set(names)), "term 重复（大小写不敏感口径）"

    def test_scope_in_vocabulary(self, data):
        for t in data["terms"]:
            if "scope" in t:
                assert t["scope"] in _ALLOWED_SCOPES, f"未知 scope: {t['scope']!r}"

    def test_unit_and_see_also_are_strings(self, data):
        for t in data["terms"]:
            for key in ("unit", "see_also"):
                if key in t:
                    assert isinstance(t[key], str) and t[key].strip()


class TestTerminologyService:
    """service 三函数正负例（ok 信封口径）。"""

    def test_list_terms_all(self, terminology_service):
        result = terminology_service.list_terms()
        assert result["ok"] is True
        assert result["count"] == len(result["terms"])
        assert result["count"] >= 30
        assert set(result["scopes"]) <= _ALLOWED_SCOPES

    def test_list_terms_scope_filter(self, terminology_service):
        result = terminology_service.list_terms(scope="antenna")
        assert result["ok"] is True
        assert result["count"] >= 1
        assert all(t.get("scope", "general") == "antenna" for t in result["terms"])

    def test_list_terms_scope_unknown_returns_empty(self, terminology_service):
        result = terminology_service.list_terms(scope="no_such_scope")
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["terms"] == []

    def test_get_term_known_case_insensitive(self, terminology_service):
        for probe in ("VSWR", "vswr", "Vswr"):
            result = terminology_service.get_term(probe)
            assert result["ok"] is True
            assert result["term"]["term"] == "VSWR"
            assert result["term"]["definition"].strip()

    def test_get_term_unknown_negative(self, terminology_service):
        result = terminology_service.get_term("no_such_term_xyz")
        assert result["ok"] is False
        assert "error" in result

    def test_get_term_blank_negative(self, terminology_service):
        assert terminology_service.get_term("   ")["ok"] is False

    def test_report_footnotes_citation_order_and_dedup(self, terminology_service):
        result = terminology_service.report_footnotes(["VSWR", "dB", "VSWR", "dBm"])
        assert result["ok"] is True
        assert result["count"] == 3
        assert [f["term"] for f in result["footnotes"]] == ["VSWR", "dB", "dBm"]
        assert [f["no"] for f in result["footnotes"]] == [1, 2, 3]

    def test_report_footnotes_unknown_soft(self, terminology_service):
        result = terminology_service.report_footnotes(["dB", "no_such_term"])
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["unknown"] == ["no_such_term"]

    def test_report_footnotes_footnote_shape(self, terminology_service):
        result = terminology_service.report_footnotes(["s11_db_min"])
        note = result["footnotes"][0]
        assert note["no"] == 1
        assert note["definition"].strip()
        # 可选键只随源条目出现
        assert set(note) <= {"no", "term", "definition", "unit", "see_also"}

    def test_report_footnotes_empty_input(self, terminology_service):
        result = terminology_service.report_footnotes([])
        assert result["ok"] is True
        assert result["footnotes"] == [] and result["unknown"] == []

    def test_missing_yaml_degrades_empty(self, monkeypatch):
        from rfauto.service import terminology_service as svc

        monkeypatch.setattr(svc, "_TERMINOLOGY_PATH", Path("no/such/file.yaml"))
        assert svc.load_terminology() == {}
        assert svc.list_terms()["count"] == 0
        assert svc.get_term("VSWR")["ok"] is False


class TestTerminologyMCPResource:
    """MCP resource 注册面冒烟（照 test_mcp_server.TestMCPResources 形态）。"""

    @pytest.fixture()
    def mcp_server(self):
        from rfauto.mcp_server import mcp

        return mcp

    def test_terminology_resource_registered(self, mcp_server):
        resources = anyio.run(mcp_server.list_resources)
        uris = {str(r.uri) for r in resources}
        assert "rfauto://knowledge/terminology" in uris

    def test_read_terminology_resource(self, mcp_server, monkeypatch):
        monkeypatch.chdir(_REPO_ROOT)  # 资源按相对路径读 knowledge/
        content = anyio.run(
            lambda: mcp_server.read_resource("rfauto://knowledge/terminology")
        )
        text = content[0].text if isinstance(content, list) else str(content)
        assert "terms" in text
        assert "VSWR" in text
