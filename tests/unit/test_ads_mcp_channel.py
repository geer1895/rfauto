"""M档官方 MCP 后端测试（桩 transport，不依赖真机 ADS）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.linkage.ads_mcp_channel import AdsMcpBackend


class FakeText:
    def __init__(self, text: str):
        self.text = text
        self.type = "text"


class FakeResult:
    def __init__(self, payload, is_error=False):
        self.content = [FakeText(json.dumps(payload))]
        self.is_error = is_error


class FakeClient:
    """按工具名回放脚本化响应的桩客户端。"""

    def __init__(self, script: dict[str, list]):
        self.script = script
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, tool: str, arguments: dict | None = None):
        self.calls.append((tool, arguments or {}))
        queue = self.script[tool]
        return queue.pop(0)


@pytest.fixture()
def stubbed_backend(tmp_path: Path, monkeypatch):
    """用桩 Client 替换 fastmcp（transport_factory 注入 + 类打桩）。"""
    from fastmcp import Client as RealClient

    client = FakeClient({
        "start_local_session": [FakeResult({"success": True, "mode": "local"})],
        "execute_python": [FakeResult({"ok": True, "success": True, "stdout": "2"})],
        "disconnect_session": [FakeResult({"ok": True})],
    })
    def fake_ctx(client_obj=client):
        client_obj._real_ctx = RealClient  # 确认真实类仍可访问（结构自检）
        return _null_cm()

    # 直接把 session() 内部用到的 Client 换成桩：monkeypatch fastmcp.Client
    import fastmcp

    monkeypatch.setattr(fastmcp, "Client", lambda transport: client)
    backend = AdsMcpBackend(tmp_path, transport_factory=lambda: object())
    return backend, client


def _null_cm():
    import contextlib

    @contextlib.asynccontextmanager
    async def cm():
        yield None

    return cm


class TestSessionLifecycle:
    def test_session_happy_path(self, stubbed_backend):
        import asyncio

        backend, client = stubbed_backend

        async def run():
            async with backend.session() as execute:
                result = await execute("1 + 1")
            return result

        result = asyncio.run(run())
        assert result["ok"] is True
        tools = [c[0] for c in client.calls]
        assert tools == ["start_local_session", "execute_python", "disconnect_session"], (
            "生命周期必须是 起 → 执行 → 断开"
        )

    def test_start_failure_raises_and_skips_execute(self, tmp_path, monkeypatch):
        import asyncio

        import fastmcp

        client = FakeClient({
            "start_local_session": [FakeResult({"success": False, "error": "no license"})],
            "disconnect_session": [FakeResult({"ok": True})],
        })
        monkeypatch.setattr(fastmcp, "Client", lambda transport: client)
        backend = AdsMcpBackend(tmp_path, transport_factory=lambda: object())

        async def run():
            async with backend.session():
                pass

        with pytest.raises(RuntimeError, match="start_local_session"):
            asyncio.run(run())
        # 启动失败不得尝试执行
        assert all(c[0] != "execute_python" for c in client.calls)

    def test_disconnect_failure_is_nonfatal(self, tmp_path, monkeypatch):
        import asyncio

        import fastmcp

        client = FakeClient({
            "start_local_session": [FakeResult({"success": True})],
            "execute_python": [FakeResult({"ok": True})],
            "disconnect_session": [RuntimeError("stub boom")],  # 抛异常也应被吞
        })

        async def broken_call(tool, arguments=None):
            raise RuntimeError("stub boom")

        async def call_tool(tool, arguments=None):
            client.calls.append((tool, arguments or {}))
            if tool == "disconnect_session":
                raise RuntimeError("stub boom")
            return client.script[tool].pop(0)

        client.call_tool = call_tool
        monkeypatch.setattr(fastmcp, "Client", lambda transport: client)
        backend = AdsMcpBackend(tmp_path, transport_factory=lambda: object())

        async def run():
            async with backend.session() as execute:
                await execute("x")

        asyncio.run(run())  # 不抛即通过
        assert client.calls[-1][0] == "disconnect_session"


class Res:
    """可变结果桩（parse_result 只读其属性）。"""

    def __init__(self, content=None, is_error=False):
        self.content = content if content is not None else []
        self.is_error = is_error


class TestParseResult:
    def test_json_payload(self, stubbed_backend):
        r = AdsMcpBackend.parse_result(FakeResult({"ok": True, "value": 3}))
        assert r == {"ok": True, "value": 3}

    def test_non_json_text(self):
        class Item:
            text = "plain text"

        res = Res(content=[Item()])
        assert AdsMcpBackend.parse_result(res) == {"ok": True, "text": "plain text"}

    def test_error_raises(self):
        res = Res(is_error=True)

        with pytest.raises(RuntimeError, match="MCP 工具调用失败"):
            AdsMcpBackend.parse_result(res)
