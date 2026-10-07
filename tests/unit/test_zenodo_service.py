"""PR-11 zenodo_service 单测：元数据导出器+校验器（零网络铁律钉）。"""

from __future__ import annotations

import json
from pathlib import Path

_CFF_COMPLETE = """\
cff-version: 1.2.0
message: "If you use rfauto in your research, please cite it as below."
title: "rfauto: test framework"
type: software
repository-code: "https://github.com/geer1895/rfauto"
authors:
  - name: rfauto developers
version: 9.9.9
license: GPL-3.0-only
abstract: >-
  Test abstract for the exporter.
keywords:
  - RF
  - test
"""

_CFF_NO_REPO = """\
cff-version: 1.2.0
message: "cite me"
title: "rfauto: test framework"
type: software
authors:
  - name: rfauto developers
version: 9.9.9
license: GPL-3.0-only
abstract: >-
  Test abstract.
"""

_PYPROJECT = '[project]\nname = "rfauto"\nversion = "9.9.9"\n'


def _write_cff(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "CITATION.cff"
    p.write_text(text, encoding="utf-8")
    return p


class TestExport:
    def test_shape_and_related_identifiers(self, tmp_path):
        from rfauto.service.zenodo_service import export_zenodo_metadata

        r = export_zenodo_metadata(_write_cff(tmp_path, _CFF_COMPLETE))
        assert r["ok"]
        m = r["metadata"]
        assert m["title"] == "rfauto: test framework"
        assert m["upload_type"] == "software"
        assert m["creators"] == [{"name": "rfauto developers"}]
        assert m["version"] == "9.9.9" and m["license"] == "GPL-3.0-only"
        assert m["access_right"] == "open"
        assert m["keywords"] == ["RF", "test"]
        assert m["related_identifiers"] == [{
            "identifier": "https://github.com/geer1895/rfauto",
            "relation": "isSupplementTo", "scheme": "url"}]
        assert r["written"] is False and r["out_path"] is None

    def test_writes_json_roundtrip(self, tmp_path):
        from rfauto.service.zenodo_service import export_zenodo_metadata

        out = tmp_path / "sub" / ".zenodo.json"
        r = export_zenodo_metadata(
            _write_cff(tmp_path, _CFF_COMPLETE), out_path=out)
        assert r["ok"] and r["written"] and Path(r["out_path"]) == out
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded == r["metadata"]

    def test_no_repository_code_related_empty(self, tmp_path):
        from rfauto.service.zenodo_service import export_zenodo_metadata

        r = export_zenodo_metadata(_write_cff(tmp_path, _CFF_NO_REPO))
        assert r["ok"] and r["metadata"]["related_identifiers"] == []

    def test_family_given_authors(self, tmp_path):
        from rfauto.service.zenodo_service import export_zenodo_metadata

        cff = _CFF_COMPLETE.replace(
            "  - name: rfauto developers", "  - family: Doe\n    given: Jane")
        r = export_zenodo_metadata(_write_cff(tmp_path, cff))
        assert r["metadata"]["creators"] == [{"name": "Doe, Jane"}]

    def test_missing_cff_is_error(self, tmp_path):
        from rfauto.service.zenodo_service import export_zenodo_metadata

        r = export_zenodo_metadata(tmp_path / "nope.cff")
        assert r["ok"] is False and "不存在" in r["errors"][0]

    def test_broken_yaml_is_error(self, tmp_path):
        from rfauto.service.zenodo_service import export_zenodo_metadata

        p = tmp_path / "CITATION.cff"
        p.write_text("a: [unclosed\n  b: {bad", encoding="utf-8")
        r = export_zenodo_metadata(p)
        assert r["ok"] is False and r["errors"]


class TestValidate:
    def test_complete_passes_no_warnings(self, tmp_path):
        from rfauto.service.zenodo_service import validate_citation_metadata

        pp = tmp_path / "pyproject.toml"
        pp.write_text(_PYPROJECT, encoding="utf-8")
        r = validate_citation_metadata(
            _write_cff(tmp_path, _CFF_COMPLETE), pyproject_path=pp)
        assert r["ok"] and r["warnings"] == []
        assert r["checked"]["pyproject_version"] == "9.9.9"
        assert r["checked"]["repository_code"].startswith("https://github.com/")

    def test_missing_repository_code_is_warning_not_error(self, tmp_path):
        from rfauto.service.zenodo_service import validate_citation_metadata

        pp = tmp_path / "pyproject.toml"
        pp.write_text(_PYPROJECT, encoding="utf-8")
        r = validate_citation_metadata(
            _write_cff(tmp_path, _CFF_NO_REPO), pyproject_path=pp)
        assert r["ok"] is True
        assert any("repository-code" in w for w in r["warnings"])
        assert r["checked"]["repository_code"] is None

    def test_missing_required_field_is_error(self, tmp_path):
        from rfauto.service.zenodo_service import validate_citation_metadata

        cff = _CFF_COMPLETE.replace("version: 9.9.9\n", "")
        r = validate_citation_metadata(_write_cff(tmp_path, cff))
        assert r["ok"] is False
        assert any("version" in e for e in r["errors"])

    def test_bad_cff_version_is_error(self, tmp_path):
        from rfauto.service.zenodo_service import validate_citation_metadata

        cff = _CFF_COMPLETE.replace("cff-version: 1.2.0", "cff-version: 9.9")
        r = validate_citation_metadata(_write_cff(tmp_path, cff))
        assert r["ok"] is False and any("cff-version" in e for e in r["errors"])

    def test_version_mismatch_vs_pyproject_is_error(self, tmp_path):
        from rfauto.service.zenodo_service import validate_citation_metadata

        pp = tmp_path / "pyproject.toml"
        pp.write_text(
            _PYPROJECT.replace('version = "9.9.9"', 'version = "0.0.1"'),
            encoding="utf-8")
        r = validate_citation_metadata(
            _write_cff(tmp_path, _CFF_COMPLETE), pyproject_path=pp)
        assert r["ok"] is False
        assert any("版本错位" in e for e in r["errors"])

    def test_missing_pyproject_downgrades_to_warning(self, tmp_path):
        from rfauto.service.zenodo_service import validate_citation_metadata

        r = validate_citation_metadata(
            _write_cff(tmp_path, _CFF_COMPLETE),
            pyproject_path=tmp_path / "absent.toml")
        assert r["ok"] is True
        assert any("pyproject" in w for w in r["warnings"])


class TestRepoArtifactsAndNoNetwork:
    def test_committed_zenodo_metadata_public_facts(self):
        """仓内 docs/publication/zenodo.metadata.json 钉公开仓事实（GPL-3.0/
        公开 URL），且零敏感（无盘符路径——发布面产物预审钉进测试）。"""
        root = Path(__file__).resolve().parents[2]
        p = root / "docs" / "publication" / "zenodo.metadata.json"
        assert p.exists(), f"canonical 产物缺失: {p}"
        m = json.loads(p.read_text(encoding="utf-8"))
        assert m["upload_type"] == "software" and m["access_right"] == "open"
        assert m["license"] == "GPL-3.0-only"  # 公开仓事实（release 面）
        assert m["title"].startswith("rfauto:")
        assert any(
            ri["identifier"] == "https://github.com/geer1895/rfauto"
            for ri in m["related_identifiers"])
        blob = json.dumps(m, ensure_ascii=False)
        for needle in ("E:\\", "E:/", "DEV" + "LOG", "AGENT_" + "HANDOFF", "任务书"):
            assert needle not in blob, f"敏感串 {needle!r} 泄入发布元数据"

    def test_module_has_zero_network_surface(self):
        """零网络铁律：本模块源码无任何网络客户端导入/调用（永不真实上传）。"""
        root = Path(__file__).resolve().parents[2]
        src = (root / "src" / "rfauto" / "service" / "zenodo_service.py"
               ).read_text(encoding="utf-8")
        for needle in ("requests", "urllib", "socket", "http.client",
                       "httpx", "aiohttp", "zenodo_client"):
            assert needle not in src, f"网络面 {needle!r} 混入 zenodo_service"
