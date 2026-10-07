"""XN-7 工具情报监控测试（ge8c 席C6，零真网 mock 全覆盖）。

锚定：
- #139 通道钉：全部扫描经注入 canned http_get；不注入时本模块只有显式
  调用才触网——本测试文件全程零真网（monkeypatch _http_get 哨兵双保险）；
- URL 构造/JSON 解析（缺 tag 如实 None）；diff 三态（up_to_date/behind/
  unknown）；无 repo 目标 local_only；fetch_failed 如实留痕不炸批次；
- 账本幂等去重（同 tool+tag 重复登记跳过并计数）；
- 本机探测：caller_provided 优先；pip 元数据探测（optuna 真实已装）；
  未登记工具 KeyError/负例。
"""

from __future__ import annotations

import json

import pytest

import rfauto.service.tool_intel_service as ti
from rfauto.service.tool_intel_service import (
    TOOL_INTEL_SCHEMA,
    TOOL_TARGETS,
    build_releases_url,
    detect_installed_version,
    parse_release_payload,
    render_intel_markdown,
    scan_tools,
)


def _canned_release(tag: str, name: str = "release") -> bytes:
    return json.dumps({
        "tag_name": tag, "name": name, "published_at": "2026-09-01T00:00:00Z",
        "prerelease": False, "body": "## Highlights\n- faster meshing",
    }).encode()


def _fake_http(tags: dict[str, str]) -> ti.HttpGet:
    def get(url: str, timeout_s: float) -> bytes:
        for tool, target in TOOL_TARGETS.items():
            if target.get("repo") and \
                    target["repo"] in url and tool in tags:
                return _canned_release(tags[tool])
        raise RuntimeError(f"no canned response for {url}")
    return get


@pytest.fixture(autouse=True)
def _guard_real_network(monkeypatch):
    """双保险：任何漏注入的默认通道调用一律炸（零真网铁律）。"""
    def _forbidden(url: str, timeout_s: float) -> bytes:
        raise AssertionError(f"real network attempted: {url}")
    monkeypatch.setattr(ti, "_http_get", _forbidden)


class TestUrlAndParse:
    def test_url_shape(self) -> None:
        assert build_releases_url("optuna/optuna") == \
            "https://api.github.com/repos/optuna/optuna/releases/latest"
        with pytest.raises(ValueError):
            build_releases_url("optuna")
        with pytest.raises(ValueError):
            build_releases_url("a/b/c")

    def test_parse_missing_tag_honest(self) -> None:
        p = parse_release_payload({"name": "n"})
        assert p["latest_tag"] is None
        p2 = parse_release_payload(
            {"tag_name": "v1", "body": "x" * 1000, "prerelease": True})
        assert len(p2["body_excerpt"]) <= 600
        assert p2["prerelease"] is True


class TestDetectInstalled:
    def test_caller_provided_first(self) -> None:
        d = detect_installed_version("ads", known_versions={"ads": "2027"})
        assert d == {"installed": "2027", "method": "caller_provided"}

    def test_pip_metadata_probe(self) -> None:
        # optuna 是仓内必装依赖（pyproject deps）
        d = detect_installed_version("optuna")
        assert d["installed"] is not None
        assert d["method"].startswith("importlib:")

    def test_non_pip_honest_none(self) -> None:
        d = detect_installed_version("openems")
        assert d["installed"] is None
        assert d["method"] == "local_install_probe"

    def test_unknown_tool(self) -> None:
        with pytest.raises(KeyError):
            detect_installed_version("ham_radio")


class TestScan:
    def test_mock_scan_full(self, tmp_path) -> None:
        get = _fake_http({"optuna": "v9.9.9", "skrf": "v2.0.0",
                          "aedt": "v2.0"})
        r = scan_tools(
            ledger_path=tmp_path / "ledger.jsonl", http_get=get,
            known_versions={"optuna": "9.9.9", "skrf": "1.9.0",
                            "aedt": None, "openems": "25.1"},
        )
        assert r["ok"] is True
        assert r["n_scanned"] == 5
        by = {e["tool"]: e for e in r["entries"]}
        # up_to_date：tag 归一（v 前缀剥离）后相等
        assert by["optuna"]["diff"] == "up_to_date"
        # behind：1.9.0 vs 2.0.0
        assert by["skrf"]["diff"] == "behind"
        # unknown：本机版本不可探
        assert by["aedt"]["diff"] == "unknown"
        # local_only：无 repo 目标
        assert by["ads"]["status"] == "local_only"
        assert by["openems"]["status"] == "local_only"
        assert r["n_new"] == 5
        # 状态恒 candidate（升级决策人工）
        assert all(e["status"] in ("candidate", "local_only")
                   for e in r["entries"])
        # 账本落盘
        lines = (tmp_path / "ledger.jsonl").read_text(
            encoding="utf-8").splitlines()
        assert len(lines) == 5

    def test_ledger_dedupe_idempotent(self, tmp_path) -> None:
        get = _fake_http({"optuna": "v9.9.9"})
        kw = dict(tools=["optuna"], ledger_path=tmp_path / "l.jsonl",
                  http_get=get, known_versions={"optuna": "1.0"})
        r1 = scan_tools(**kw)
        r2 = scan_tools(**kw)
        assert r1["n_new"] == 1
        assert r2["n_new"] == 0
        assert r2["n_duplicates"] == 1

    def test_fetch_failed_honest(self, tmp_path) -> None:
        def failing(url: str, timeout_s: float) -> bytes:
            raise OSError("network down")
        r = scan_tools(tools=["optuna"], ledger_path=tmp_path / "l.jsonl",
                       http_get=failing)
        assert r["ok"] is True  # 批次不炸
        e = r["entries"][0]
        assert e["status"] == "fetch_failed"
        assert "network down" in e["note"]
        assert e["diff"] == "unknown"

    def test_unknown_tool_negative(self, tmp_path) -> None:
        r = scan_tools(tools=["nope"], ledger_path=tmp_path / "l.jsonl",
                       http_get=_fake_http({}))
        assert r["ok"] is False

    def test_schema_id(self) -> None:
        assert TOOL_INTEL_SCHEMA == "rfauto-tool-intel-v1"


class TestMarkdown:
    def test_render_table(self, tmp_path) -> None:
        r = scan_tools(tools=["optuna"], ledger_path=tmp_path / "l.jsonl",
                       http_get=_fake_http({"optuna": "v9.9.9"}),
                       known_versions={"optuna": "1.0.0"})
        md = render_intel_markdown(r)
        assert "| 工具 |" in md
        assert "behind" in md
        assert "candidate" in md

    def test_render_failure(self) -> None:
        md = render_intel_markdown({"ok": False, "errors": ["x"]})
        assert "失败" in md
