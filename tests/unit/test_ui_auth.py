"""架构批 W6-S2 定向门——UI auth 安全面（R2 审计 §面5.4 / Top10 #5）。

写端点 Bearer 鉴权（服务端）：
- env ``RFAUTO_UI_TOKEN`` 未设=零行为变化（本机回环部署缺省安全——POST 面
  照旧直通路由，本套件用不存在的路径拿路由 404 作"中间件放行"探针，不触
  任何真 handler 副作用）；
- 设定时写方法（POST/PUT/DELETE/PATCH）要求 ``Authorization: Bearer <token>``：
  正确放行（探针仍 404=到达路由）、缺失 401、错误 401；401 归一 error 信封
  （ok=False+errors 列表，errorText 回退链兼容）且出站仍带 CSP/安全头批
  （拒绝路径响应面一致性）；
- 读端点豁免：token 启用下 GET /api/solvers 与 GET / 照常 200。

前端 Bearer 接线（node 行为钉）：api.js 装配期读
``<meta name="rfauto-ui-token">``（服务端同 env 源中继）→ setApiToken →
apiRequestInit 全部请求附 Authorization 头；meta 缺席/空 content/无 document
（node 裸环境）三态均零行为；meta 注入对含引号/尖括号 token 做属性转义
（服务端 HTMLResponse 注入面）。

不依赖 runs/、不读网络、不启动真服务器（TestClient+node 桩）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")
_ENV = "RFAUTO_UI_TOKEN"


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    with TestClient(create_ui_app(include_runs_mount=False)) as c:
        yield c


# ────────────────────────── 服务端：env 未设=零行为变化 ──────────────────────────


class TestNoEnvZeroBehavior:
    def test_post_passthrough_without_env(self, client, monkeypatch):
        """env 未设：POST 无凭据照旧到达路由（探针 404=中间件放行零改动）。"""
        monkeypatch.delenv(_ENV, raising=False)
        r = client.post("/api/__no_such_route__")
        assert r.status_code == 404

    def test_empty_env_value_means_unset(self, client, monkeypatch):
        """空串视同未设（ui_auth_token 空值守卫——部署脚本残留空值不打红）。"""
        monkeypatch.setenv(_ENV, "")
        r = client.post("/api/__no_such_route__")
        assert r.status_code == 404

    def test_get_untouched_without_env(self, client, monkeypatch):
        monkeypatch.delenv(_ENV, raising=False)
        assert client.get("/api/solvers").status_code == 200


# ────────────────────────── 服务端：写端点校验三态 ──────────────────────────


class TestWriteEndpointAuth:
    def test_post_with_correct_token_reaches_route(self, client, monkeypatch):
        monkeypatch.setenv(_ENV, "tok-123")
        r = client.post(
            "/api/__no_such_route__",
            headers={"Authorization": "Bearer tok-123"},
        )
        assert r.status_code == 404, "正确令牌必须放行到路由（404=探针路径不存在）"

    def test_post_missing_token_401_envelope(self, client, monkeypatch):
        monkeypatch.setenv(_ENV, "tok-123")
        r = client.post("/api/__no_such_route__")
        assert r.status_code == 401
        body = r.json()
        assert body.get("ok") is False
        assert isinstance(body.get("errors"), list) and body["errors"]

    def test_post_wrong_token_401(self, client, monkeypatch):
        monkeypatch.setenv(_ENV, "tok-123")
        for presented in ("Bearer wrong", "tok-123", "bearer tok-123",
                          "Bearer tok-123 ", ""):
            r = client.post(
                "/api/__no_such_route__",
                headers={"Authorization": presented} if presented else {},
            )
            assert r.status_code == 401, presented

    def test_401_still_carries_security_headers(self, client, monkeypatch):
        """拒绝路径响应面一致性：CSP/安全头批对 401 同样附加（外层中间件）。"""
        monkeypatch.setenv(_ENV, "tok-123")
        r = client.post("/api/__no_such_route__")
        from rfauto.ui.csp import CSP_HEADER, CSP_VALUE, NOSNIFF_HEADER

        assert r.headers.get(CSP_HEADER) == CSP_VALUE
        assert r.headers.get(NOSNIFF_HEADER) == "nosniff"

    def test_put_delete_patch_also_gated(self, client, monkeypatch):
        monkeypatch.setenv(_ENV, "tok-123")
        for meth in ("put", "delete", "patch"):
            r = getattr(client, meth)("/api/__no_such_route__")
            assert r.status_code == 401, meth

    def test_read_endpoints_exempt_when_enabled(self, client, monkeypatch):
        """读端点豁免：页面壳与只读 API 在 token 启用下照常 200（浏览语义
        不受扰；写闸只收写方法）。"""
        monkeypatch.setenv(_ENV, "tok-123")
        assert client.get("/api/solvers").status_code == 200
        assert client.get("/").status_code == 200


# ────────────────────────── 服务端：index meta 注入 ──────────────────────────


class TestIndexMetaInjection:
    def test_no_env_serves_file_bytes_unchanged(self, client, monkeypatch):
        """env 未设：/ 走 FileResponse 原路径（响应体==index.html 文件字节）。"""
        monkeypatch.delenv(_ENV, raising=False)
        want = (_STATIC / "index.html").read_bytes()
        r = client.get("/")
        assert r.status_code == 200
        assert r.content == want

    def test_env_set_injects_token_meta(self, client, monkeypatch):
        monkeypatch.setenv(_ENV, "tok-123")
        r = client.get("/")
        assert r.status_code == 200
        assert '<meta name="rfauto-ui-token" content="tok-123">' in r.text
        assert r.text.index("<head>") < r.text.index("rfauto-ui-token")

    def test_meta_escapes_attribute_specials(self, client, monkeypatch):
        """含引号/尖括号 token 属性转义（注入面守卫；浏览器 HTML 解析后
        content 还原原文——api.js 侧拿回原值）。"""
        monkeypatch.setenv(_ENV, 'a"b<c>&d')
        r = client.get("/")
        assert '<meta name="rfauto-ui-token"' in r.text
        assert 'content="a&quot;b&lt;c&gt;&amp;d"' in r.text
        assert 'a"b<c>' not in r.text


# ────────────────────────── 前端：api.js meta 扫描（node 行为钉） ──────────────────────────


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


def _payload(out: str) -> dict:
    import json

    return json.loads(out.strip().splitlines()[-1])


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestApiMetaTokenScan:
    def test_meta_present_wires_token_into_request_init(self):
        """meta 在场：装配期 setApiToken → apiRequestInit 全请求附 Bearer 头
        （app.js api 的 init 缺席调用同样获得头——apiRequestInit 单源）。"""
        out = _run_node_js(
            "globalThis.document = { querySelector: (sel) =>\n"
            "  sel === 'meta[name=\"rfauto-ui-token\"]' ? { content: 'tok-123' } : null };\n"
            "const api = await import('./pages/api.js');\n"
            "const bare = api.apiRequestInit(undefined);\n"
            "const withOpts = api.apiRequestInit({ method: 'POST',\n"
            "  headers: { 'Content-Type': 'application/json' } });\n"
            "console.log(JSON.stringify({ set: api.apiTokenSet(),\n"
            "  bareAuth: bare && bare.headers && bare.headers.Authorization,\n"
            "  optsAuth: withOpts.headers.Authorization,\n"
            "  optsKeepsCt: withOpts.headers['Content-Type'] }));\n"
        )
        p = _payload(out)
        assert p == {
            "set": True,
            "bareAuth": "Bearer tok-123",
            "optsAuth": "Bearer tok-123",
            "optsKeepsCt": "application/json",
        }, "meta 注入必须经 setApiToken 落 apiRequestInit 单源（既有头不覆盖）"

    def test_explicit_authorization_header_wins(self):
        """调用方显式 Authorization 不被覆盖（apiRequestInit 既有契约）。"""
        out = _run_node_js(
            "globalThis.document = { querySelector: () => ({ content: 'tok-123' }) };\n"
            "const api = await import('./pages/api.js');\n"
            "const r = api.apiRequestInit({ headers: { Authorization: 'Bearer mine' } });\n"
            "console.log(JSON.stringify(r.headers.Authorization));\n"
        )
        assert _payload(out) == "Bearer mine"

    def test_meta_absent_or_empty_zero_behavior(self):
        """meta 缺席（服务端未启用）与空 content：token 不置位、init 原样。"""
        out = _run_node_js(
            "globalThis.document = { querySelector: () => null };\n"
            "const api = await import('./pages/api.js');\n"
            "const absent = { set: api.apiTokenSet(),\n"
            "  bare: api.apiRequestInit(undefined) ?? null };\n"
            "globalThis.document = { querySelector: () => ({ content: '' }) };\n"
            "const mod2 = await import('./pages/api.js?empty=1');\n"
            "console.log(JSON.stringify({ absent,\n"
            "  emptySet: mod2.apiTokenSet() }));\n"
        )
        p = _payload(out)
        assert p["absent"] == {"set": False, "bare": None}
        assert p["emptySet"] is False

    def test_no_document_node_import_silent(self):
        """无 document（node 裸 import/行为钉环境）：装配守卫静默零副作用。"""
        out = _run_node_js(
            "const api = await import('./pages/api.js');\n"
            "console.log(JSON.stringify({ set: api.apiTokenSet(),\n"
            "  bare: api.apiRequestInit(undefined) ?? null }));\n"
        )
        assert _payload(out) == {"set": False, "bare": None}

    def test_node_check_api_js(self):
        r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / "api.js")],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
