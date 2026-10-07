"""W1-E D-04 定向门——UI 响应头 Content-Security-Policy（script-src 'self'）。

判据（runs/w1_phase1/criteria.md §W1-E）：
- 头部断言：create_ui_app 全响应（HTML/静态 JS/API JSON）带 CSP 头，
  值含 ``script-src 'self'``；不出现 'unsafe-inline'/'unsafe-eval' 豁免；
- 内联脚本兼容性自证：index.html 全部内联 <script>（现况唯一=importmap，
  外链化不可行——外部 importmap 浏览器不支持）逐个 sha256 哈希钉进 CSP
  值——任何人改 importmap 内容，本测试立刻红并提示同步更新
  server.py:_IMPORTMAP_SHA256（防哈希静默失配把页面打残）；
- UI 冒烟：/ 与 /static/*.js 真返回 200（CSP 头不破坏静态资源服务）。
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.ui.server import _STATIC_DIR, CSP_HEADER, CSP_VALUE

_INDEX_HTML = _STATIC_DIR / "index.html"
_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                               re.S)


def _inline_scripts() -> list[str]:
    """index.html 全部内联脚本原文（浏览器哈希口径：标签间逐字节文本）。"""
    return _INLINE_SCRIPT_RE.findall(_INDEX_HTML.read_text(encoding="utf-8"))


def _csp_hashes() -> set[str]:
    """CSP 值里的全部 sha256 哈希钉（含引号）。"""
    return set(re.findall(r"'sha256-[A-Za-z0-9+/=]+'", CSP_VALUE))


@pytest.fixture(scope="module")
def client():
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app
    with TestClient(create_ui_app(include_runs_mount=False)) as c:
        yield c


class TestCspHeaderPresent:
    def test_index_html_has_csp(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers.get(CSP_HEADER) == CSP_VALUE

    def test_csp_is_script_src_self_no_unsafe(self, client):
        assert "script-src 'self'" in CSP_VALUE
        assert "'unsafe-inline'" not in CSP_VALUE
        assert "'unsafe-eval'" not in CSP_VALUE

    def test_static_js_and_api_also_carry_header(self, client):
        # 静态资源与 API JSON 面同名头无害且统一（中间件全响应附加）
        for path in ("/static/app.js", "/api/solvers"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert r.headers.get(CSP_HEADER) == CSP_VALUE, path


class TestInlineScriptHashPins:
    def test_importmap_hash_pinned_exactly(self):
        """接地现状：唯一内联 script=importmap，其 sha256 必须钉在 CSP 值。"""
        inlines = _inline_scripts()
        assert len(inlines) == 1, (
            f"index.html 内联 script 数量变化（{len(inlines)} 个）——"
            "新增内联脚本必须同步哈希钉进 server.py:_IMPORTMAP_SHA256/"
            "CSP_VALUE，或改外链")
        digest = base64.b64encode(
            hashlib.sha256(inlines[0].encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in _csp_hashes(), (
            "importmap 内容与 CSP 哈希钉失配——同步更新 "
            "server.py:_IMPORTMAP_SHA256（内容变了浏览器会拒载）")

    def test_external_scripts_unaffected_by_hash_only_policy(self):
        """外链 5 件（3 vendor + 2 module）在 'self' 下照常放行（同源）。"""
        html = _INDEX_HTML.read_text(encoding="utf-8")
        external = re.findall(r'<script\s+[^>]*\bsrc="([^"]+)"', html)
        assert len(external) == 5
        assert all(src.startswith("/static/") for src in external)

    def test_inline_importmap_not_convertible_to_external(self):
        """防"改外链"回归：importmap 是唯一内联件，若有人改成 src= 外链
        而浏览器不支持外部 importmap，three.module.js 解析会断——钉住其
        内联形态在位（含 type="importmap" 且无 src）。"""
        html = _INDEX_HTML.read_text(encoding="utf-8")
        m = re.search(r'<script\s+type="importmap"[^>]*>', html)
        assert m is not None, "importmap 内联标签消失（D-04 兼容性前提）"
        assert "src=" not in m.group(0)
