"""架构批 W1-S1 UI 远程部署安全硬化包定向门（R1 审计 v9 Top1-3 + Top4 钉索引）。

审计依据：内部证据目录 §面6（P9-13/P9-14）+ §面1（P9-1）
+ §面5（P9-11，行为钉在 test_ui_r12_deepening 同笔）。

四件：
1. P9-13 run_id 路径守卫单源化：service._helpers.safe_run_id 单源
   （判据=read_run_events/append_run_event/run_fig_file 三先例并集，
   NUL 模式=W6-S26 P2-2），8 处零清洗拼接点全部接入——真机实证
   ``curl --path-as-is /api/runs/..`` 直通仓根触发全仓 rglob 枚举
   （worker 阻塞 >12s + 目录结构泄漏）；
2. P9-14 安全头批：CSP 追加 frame-ancestors/base-uri/form-action/
   object-src 四指令（零破坏实证：index.html 无 iframe/form）+
   X-Content-Type-Options: nosniff + Referrer-Policy:
   strict-origin-when-cross-origin；
3. P9-1 Cache-Control 分域：/static → public, max-age=86400；
   /runs → public, max-age=300（run 产物短窗防实验中误缓存，审计口径）；
   其余（/ 与 /api/*）→ no-cache；SSE（/events/stream）零缓存头直通。
4. P9-11 apiFetch 缺省 30s 超时：node 行为钉在 test_ui_r12_deepening
   （TestUnifiedApiBehavioral 三新钉），本文件不重复。
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from rfauto.service import ui_service
from rfauto.service._helpers import safe_run_id
from rfauto.service.nf2ff_service import farfield_view
from rfauto.ui.server import CacheControlMiddleware, create_ui_app

# ────────────────────────── 1. P9-13 守卫单源 ──────────────────────────


class TestSafeRunIdSingleSource:
    @pytest.mark.parametrize("bad", [
        "", "   ",              # 空串/纯空白
        ".", "..",              # 相对段
        "../x", "..\\x",        # 显式穿越
        "a/b", "a\\b",          # 分隔符（路由转换器 [^/]+ 之外的服务面直呼）
        "bad\x00id",            # NUL（W6-S26 P2-2 模式）
        "..x", "a..b",          # ``..`` 子串变体（run_fig_file 既有口径）
        "/abs", "C:\\win",      # 绝对路径形态
    ])
    def test_illegal_forms_rejected(self, bad):
        assert safe_run_id(bad) is None

    @pytest.mark.parametrize("legit", [
        "abc",
        "20260101_000000_abcd1234",
        "hairpin_calib_g0500",
        "  spaced_run  ",        # strip 收敛（与三先例同款）
    ])
    def test_legit_single_segment_passthrough(self, legit):
        assert safe_run_id(legit) == legit.strip()


class TestJoinPointsGuarded:
    """8 处零清洗拼接点全部接入单源（R1 §面6 未设防清单逐点）。"""

    BAD_IDS: ClassVar[list[str]] = ["../x", "..", "a/b", "bad\x00id"]

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path, isolated_cache_off):
        (tmp_path / "runs").mkdir()
        yield

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_run_detail(self, bad):
        r = ui_service.run_detail(bad)
        assert r["ok"] is False and r["errors"]
        assert "非法 run_id" in r["errors"][0]
        assert "files" not in r  # 零枚举（DoS 面收口）

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_tune_trials(self, bad):
        r = ui_service.tune_trials(bad)
        assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_calibration_view(self, bad):
        r = ui_service.calibration_view(bad)
        assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_sparams_series(self, bad):
        r = ui_service.sparams_series(bad)
        assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_field_view(self, bad):
        r = ui_service.field_view(bad)
        assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_smith_view(self, bad):
        r = ui_service.smith_view(bad)
        assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_pareto_and_feasibility_chain(self, bad):
        for r in (ui_service.pareto_view(bad),
                  ui_service.feasibility_heatmap(bad, "a", "b")):
            assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    @pytest.mark.parametrize("bad", BAD_IDS)
    def test_farfield_view_nf2ff(self, bad):
        r = farfield_view(bad)
        assert r["ok"] is False and "非法 run_id" in r["errors"][0]

    def test_dotdot_does_not_enumerate_repo_root(self):
        # DoS 回归钉（审计真机探针语义）：``RUNS_DIR / ".."`` 是仓根，
        # 修复前 is_dir 通过 → rglob 全仓枚举；修复后守卫前置拦截，
        # 响应里不得出现 files 枚举键。
        r = ui_service.run_detail("..")
        assert r["ok"] is False and "files" not in r


class TestTraversalRoutes:
    """路由面穿越形态（``..%5C`` 反斜杠 / ``%2E%2E`` 点编码）→ error 信封。"""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from starlette.testclient import TestClient

        (tmp_path / "runs").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        return TestClient(create_ui_app(include_runs_mount=False))

    def test_backslash_traversal_envelope(self, client):
        r = client.get("/api/runs/..%5C")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False and body["errors"]

    def test_encoded_dotdot_envelope(self, client):
        r = client.get("/api/runs/%2E%2E")
        body = r.json()
        assert body["ok"] is False and "非法 run_id" in body["errors"][0]

    def test_legal_run_still_passes(self, client, tmp_path):
        run_dir = tmp_path / "runs" / "20260101_000000_okrun"
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "results" / "metrics.json").write_text(
            '{"cost": 0.1}', encoding="utf-8")
        r = client.get("/api/runs/20260101_000000_okrun")
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_fig_route_traversal_still_404(self, client):
        # run_fig_file 白名单钉（test_ui_report_figs 同口径）路由面复核
        r = client.get("/api/runs/..%5C/figs/results/figs/a.png")
        assert r.status_code == 404 and r.json()["ok"] is False


# ────────────────────────── 2. P9-14 安全头批 ──────────────────────────


class TestSecurityHeaders:
    @pytest.fixture(scope="class")
    def client(self):
        from starlette.testclient import TestClient

        with TestClient(create_ui_app(include_runs_mount=False)) as c:
            yield c

    def test_csp_value_carries_four_hardening_directives(self):
        from rfauto.ui.csp import CSP_VALUE

        for directive in ("frame-ancestors 'none'", "base-uri 'self'",
                          "form-action 'self'", "object-src 'none'"):
            assert directive in CSP_VALUE, directive
        # 哈希双门不受扰（test_w1e_ui_csp 同笔核对）
        assert "script-src 'self'" in CSP_VALUE
        assert "'unsafe-inline'" not in CSP_VALUE
        assert "'unsafe-eval'" not in CSP_VALUE

    @pytest.mark.parametrize("path", ["/", "/static/app.js", "/api/solvers"])
    def test_nosniff_and_referrer_policy_on_all_faces(self, client, path):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers.get("X-Content-Type-Options") == "nosniff", path
        assert (r.headers.get("Referrer-Policy")
                == "strict-origin-when-cross-origin"), path
        # CSP 头值仍==常量单源（test_w1e_ui_csp 口径不变）
        from rfauto.ui.csp import CSP_HEADER, CSP_VALUE

        assert r.headers.get(CSP_HEADER) == CSP_VALUE, path


# ────────────────────────── 3. P9-1 Cache-Control 分域 ──────────────────


class TestCacheControlDomains:
    @pytest.fixture(scope="class")
    def client(self):
        from starlette.testclient import TestClient

        with TestClient(create_ui_app(include_runs_mount=False)) as c:
            yield c

    def test_static_assets_one_day(self, client):
        r = client.get("/static/app.js")
        assert r.status_code == 200
        assert r.headers["Cache-Control"] == "public, max-age=86400"

    @pytest.mark.parametrize("path", ["/", "/api/solvers"])
    def test_html_and_api_no_cache(self, client, path):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.headers["Cache-Control"] == "no-cache", path

    def test_runs_mount_short_window(self, tmp_path, monkeypatch):
        # /runs 产物静态服务：300s 短窗（审计口径：run 结束后产物不变，
        # 实验中同名 fig 会改写——防陈旧误缓存）
        from starlette.testclient import TestClient

        run_dir = tmp_path / "runs" / "20260101_000000_cacherun"
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "results" / "curve.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + b"x" * 8)
        monkeypatch.chdir(tmp_path)
        with TestClient(create_ui_app(include_runs_mount=True)) as c:
            r = c.get("/runs/20260101_000000_cacherun/results/curve.png")
        assert r.status_code == 200
        assert r.headers["Cache-Control"] == "public, max-age=300"


class TestCacheControlSseExemption:
    """SSE 端点零缓存头（审计钉面：流式响应不得挂任何缓存语义）。

    直连 ASGI 中间件单元钉：EventSourceResponse 会挂长连接，TestClient
    走全 app 需要真流面；中间件级 stub 等价覆盖 scope 分派逻辑。
    """

    @staticmethod
    def _run_middleware(path: str) -> dict[str, str]:
        captured: dict[str, str] = {}

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})

        async def send(message):
            if message["type"] == "http.response.start":
                raw = message.get("headers") or []
                for k, v in raw:
                    name = k.decode("latin-1").lower()
                    captured[name] = v.decode("latin-1")

        import asyncio

        mw = CacheControlMiddleware(app)
        asyncio.run(mw({"type": "http", "path": path},
                       lambda: None, send))
        return captured

    @pytest.mark.parametrize("path", [
        "/api/runs/x/events/stream",
        "/api/tune/events/stream",
        "/api/campaign_queue/events/stream",
        "/api/events/stream",
    ])
    def test_sse_paths_get_no_cache_header(self, path):
        headers = self._run_middleware(path)
        assert "cache-control" not in headers, path

    def test_non_sse_paths_still_stamped(self):
        assert self._run_middleware("/api/solvers")[
            "cache-control"] == "no-cache"
        assert self._run_middleware("/static/app.js")[
            "cache-control"] == "public, max-age=86400"
