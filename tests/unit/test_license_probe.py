"""infra/license_probe 单元测试（方向 1 license-aware 队列）。"""

from __future__ import annotations

import socket
import threading


class TestParseServer:
    def test_host_port(self):
        from rfauto.infra.license_probe import _parse_server
        assert _parse_server("localhost:1055") == ("localhost", 1055)

    def test_port_at_host(self):
        from rfauto.infra.license_probe import _parse_server
        assert _parse_server("1055@licserv") == ("licserv", 1055)

    def test_garbage_returns_none(self):
        from rfauto.infra.license_probe import _parse_server
        assert _parse_server("not-a-server") is None


class TestProbeLicense:
    def test_no_server_configured_passes_through(self, monkeypatch):
        # 本机节点锁场景：没有 server 可探测 → 放行不算失败
        monkeypatch.delenv("ANSYSLMD_LICENSE_FILE", raising=False)
        monkeypatch.delenv("RFAUTO_LICENSE_SERVER", raising=False)
        from rfauto.infra.license_probe import probe_license
        result = probe_license()
        assert result["available"] is True
        assert result["server"] is None

    def test_reachable_server(self):
        # 起 localhost TCP listener 模拟 license server
        from rfauto.infra.license_probe import probe_license
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        threading.Thread(target=srv.accept, daemon=True).start()
        result = probe_license(f"127.0.0.1:{port}", timeout_s=2.0)
        srv.close()
        assert result["available"] is True

    def test_unreachable_server_fails_gracefully(self):
        # 保留端口 1 基本不可连；探测失败返回 available=False 而非抛异常
        from rfauto.infra.license_probe import probe_license
        result = probe_license("127.0.0.1:1", timeout_s=1.0)
        assert result["available"] is False
        assert result["detail"]

    def test_unparseable_spec_passes_with_note(self, monkeypatch):
        from rfauto.infra.license_probe import probe_license
        result = probe_license("some-weird-spec", timeout_s=1.0)
        assert result["available"] is True
        assert "无法探测" in result["detail"]


class TestWaitForLicense:
    def test_wait_returns_immediately_when_available(self, monkeypatch):
        import rfauto.infra.license_probe as lp
        monkeypatch.setattr(lp, "probe_license",
                            lambda *a, **k: {"available": True, "server": "x", "detail": "ok"})
        result = lp.wait_for_license(server="x", max_wait_s=5, poll_s=0.1)
        assert result["available"] is True
        assert result["probes"] == 1

    def test_wait_suspends_then_succeeds(self, monkeypatch):
        # license 恢复前挂起重试（非失败语义），恢复后返回
        import rfauto.infra.license_probe as lp
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            return {"available": calls["n"] >= 3, "server": "x", "detail": "probe"}

        monkeypatch.setattr(lp, "probe_license", flaky)
        result = lp.wait_for_license(server="x", max_wait_s=10, poll_s=0.05)
        assert result["available"] is True
        assert result["probes"] == 3
