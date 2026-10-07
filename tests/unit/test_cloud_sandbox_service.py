"""XN-8 云沙箱接口面测试（ge8c 席C6，零真云 mock 全覆盖）。

锚定：
- URL 形态：mybinder/colab 公开形态精确构造；repo/ref 白名单守卫
  （坏 ref 拒绝产出坏链接）；colab notebook 路径守卫（仓内 .ipynb、拒 ..）；
- environment.yml：yaml.safe_load 往返 + 依赖子集钉；
- notebook：nbformat 4 结构 + 代码单元只引用闭式注册表（零真机依赖）；
- probe：注入 canned 通道（可达/失败/异常三态），非 https 显式拒；
  #139 双保险 monkeypatch 默认通道哨兵；
- bundle 落盘往返。
"""

from __future__ import annotations

import json

import pytest
import yaml

import rfauto.service.cloud_sandbox_service as cs
from rfauto.service.cloud_sandbox_service import (
    BINDER_BASE,
    COLAB_BASE,
    ENV_DEPENDENCIES,
    SANDBOX_SCHEMA,
    build_binder_url,
    build_colab_url,
    build_environment_yml,
    build_notebook,
    make_sandbox_bundle,
    probe_bundle_urls,
    save_bundle,
)


@pytest.fixture(autouse=True)
def _guard_real_cloud(monkeypatch):
    def _forbidden(url: str, timeout_s: float) -> bytes:
        raise AssertionError(f"real cloud attempted: {url}")
    monkeypatch.setattr(cs, "_default_http_get", _forbidden)


class TestUrls:
    def test_binder_shape(self) -> None:
        u = build_binder_url("org/repo", "main")
        assert u == f"{BINDER_BASE}/org/repo/main"
        u2 = build_binder_url("org/repo", "v1.2.3", "notebooks/a.ipynb")
        assert u2.endswith("?filepath=notebooks/a.ipynb")

    def test_colab_shape(self) -> None:
        u = build_colab_url("org/repo", "main", "nb/intro.ipynb")
        assert u == f"{COLAB_BASE}/org/repo/main/nb/intro.ipynb"

    def test_bad_repo_rejected(self) -> None:
        for bad in ("repo", "a/b/c", "a b/c", ""):
            with pytest.raises(ValueError):
                build_binder_url(bad)

    def test_bad_ref_rejected(self) -> None:
        for bad in ("feature branch", "ref..odd", "a?b", ""):
            with pytest.raises(ValueError):
                build_binder_url("org/repo", bad)

    def test_bad_notebook_path_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_colab_url("org/repo", "main", "nb.txt")
        with pytest.raises(ValueError):
            build_colab_url("org/repo", "main", "../escape.ipynb")


class TestEnvAndNotebook:
    def test_env_yaml_roundtrip(self) -> None:
        y = build_environment_yml("sbx")
        data = yaml.safe_load(y)
        assert data["name"] == "sbx"
        assert data["channels"] == ["conda-forge"]
        assert len(data["dependencies"]) == len(ENV_DEPENDENCIES)
        assert any(d.startswith("python>=3.12") for d in data["dependencies"])

    def test_notebook_nbformat(self) -> None:
        nb = build_notebook("org/repo", "dev")
        assert nb["nbformat"] == 4
        assert nb["metadata"]["kernelspec"]["name"] == "python3"
        code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
        joined = "".join("".join(c["source"]) for c in code_cells)
        assert "CALCULATOR_REGISTRY" in joined  # 只消费闭式注册表
        assert "pip install -q rfauto" in joined


class TestBundle:
    def test_bundle_complete(self) -> None:
        b = make_sandbox_bundle("org/repo", "main")
        assert b["ok"] is True
        assert b["schema"] == SANDBOX_SCHEMA
        assert b["urls"]["binder"].startswith("https://mybinder.org/")
        assert b["urls"]["colab"].startswith("https://colab.research.google.com/")
        assert "badge_logo" in b["badges"]["binder_md"]
        assert "colab-badge" in b["badges"]["colab_md"]
        assert "零真云" in b["note"]

    def test_bundle_negative(self) -> None:
        b = make_sandbox_bundle("bad repo", "main")
        assert b["ok"] is False

    def test_save_roundtrip(self, tmp_path) -> None:
        b = make_sandbox_bundle("org/repo", "main")
        r = save_bundle(b, tmp_path / "sbx")
        assert r["ok"] is True
        env = yaml.safe_load((tmp_path / "sbx" / "environment.yml")
                             .read_text(encoding="utf-8"))
        assert env["name"] == "rfauto-sandbox"
        nb = json.loads((tmp_path / "sbx" / "rfauto_intro.ipynb")
                        .read_text(encoding="utf-8"))
        assert nb["nbformat"] == 4
        urls = json.loads((tmp_path / "sbx" / "urls.json")
                          .read_text(encoding="utf-8"))
        assert urls == b["urls"]

    def test_save_requires_ok(self, tmp_path) -> None:
        r = save_bundle({"ok": False, "errors": ["x"]}, tmp_path)
        assert r["ok"] is False


class TestProbe:
    def _http(self, ok_urls: set[str], fail_urls: set[str] = frozenset()):
        def get(url: str, timeout_s: float) -> bytes:
            if url in fail_urls:
                raise OSError("conn refused")
            if url in ok_urls:
                return b""
            raise OSError(f"unexpected: {url}")
        return get

    def test_probe_mock(self) -> None:
        ok = {"https://mybinder.org/v2/gh/org/repo/main"}
        bad = {"https://colab.research.google.com/github/org/repo/main/x.ipynb"}
        r = probe_bundle_urls(sorted(ok | bad), http_get=self._http(ok, bad))
        assert r["ok"] is True
        assert r["n_ok"] == 1 and r["n_total"] == 2
        by = {x["url"]: x for x in r["results"]}
        assert by[sorted(ok)[0]]["status"] == "reachable"
        assert by[sorted(bad)[0]]["status"] == "failed"
        assert "conn refused" in by[sorted(bad)[0]]["reason"]

    def test_probe_rejects_non_https(self) -> None:
        r = probe_bundle_urls(["http://mybinder.org/x"],
                              http_get=self._http(set()))
        assert r["ok"] is False
