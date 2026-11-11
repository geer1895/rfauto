"""T-Q20 本地自托管 MCP 端点最小可行性探针（aurora_q 席位 Q-W9-2，决策③降级档）。

验证目标（R7 底座判定的实证落地）：官方 python-sdk（mcp 包，MIT）的
Streamable HTTP 传输在本仓依赖树端到端可用——服务端走官方
``StreamableHTTPSessionManager``（stateless + json_response 形态），客户端走
官方 ``streamable_http_client``，二者经 ``httpx.ASGITransport`` 内存直驱：
零真端口、零网络、零外部服务、零新增依赖（mcp/httpx 均已在依赖树）。

本文件自足，不 import rfauto（src/ 禁改面零触碰；探针结论见
runs/aurora_q/qw95_explore/SELF_HOST_SPEC.md——设计档非承诺）。
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import LATEST_PROTOCOL_VERSION

PROBE_URL = "http://testserver/mcp"


def _build_probe_app() -> tuple[FastMCP, StreamableHTTPSessionManager]:
    """构造最小探针 ASGI 应用（官方 SDK 服务端形态，无真监听）。

    形态=官方 SDK 文档 "Streamable HTTP" 服务端配方：FastMCP（官方 SDK 内
    建版）定义 echo 工具 → StreamableHTTPSessionManager(json_response=True,
    stateless=True)。stateless 探针形态对应 SPEC §3 的"本地单用户自托管
    （Phase A）"；多租户/OAuth 形态见 SPEC，本探针不承诺（决策③降级档）。
    """
    mcp_server = FastMCP("rfauto-http-probe")

    @mcp_server.tool()
    def echo(text: str) -> str:
        """Echo the input text (minimal probe tool, Q-W9-2)."""
        return f"echo: {text}"

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server._mcp_server,
        json_response=True,
        stateless=True,
    )
    return mcp_server, session_manager


def _in_memory_http_client(session_manager: StreamableHTTPSessionManager) -> httpx.AsyncClient:
    """把真实网络 transport 换成 ASGITransport（进程内直调 ASGI 应用）——
    零端口零网络的关键开关；base_url 只决定 Host 头（=testserver）。"""

    async def handle_streamable_http(scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] == "lifespan":  # httpx.ASGITransport 不发 lifespan
            return
        scope["path"] = "/mcp"
        await session_manager.handle_request(scope, receive, send)

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=handle_streamable_http, raise_app_exceptions=True
        ),
        base_url="http://testserver",
    )


async def _probe_roundtrip(action):  # type: ignore[no-untyped-def]
    """探针 app → session_manager.run() → 官方 SDK 客户端内存直驱完整
    initialize 握手 → 交给 action 回调（回调用已初始化的 ClientSession）。"""
    mcp_server, session_manager = _build_probe_app()
    client = _in_memory_http_client(session_manager)
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(client)
        await stack.enter_async_context(session_manager.run())
        async with streamable_http_client(
            PROBE_URL, http_client=client
        ) as (read_stream, write_stream, get_session_id), ClientSession(read_stream, write_stream) as session:
            init_result = await session.initialize()
            action_result = await action(session, get_session_id, mcp_server)
            return init_result, action_result


def _run(coro):  # type: ignore[no-untyped-def]
    """同步测试入口跑协程（仓库无 pytest-asyncio/anyio 插件，#142 族稳态）。"""
    return asyncio.run(coro)


def test_probe_initialize_handshake() -> None:
    """探针 1：官方 SDK Streamable HTTP 完整 initialize 握手（内存直驱）。

    协议版本断言=SDK 当前最新（1.30.0 实测协商 2025-11-25，比 R7 审计口径
    2025-06-18 规范版更新——SPEC §6 依赖实证记录该漂移事实）。
    """
    init, _ = _run(_probe_roundtrip(lambda s, gid, m: asyncio.sleep(0)))
    assert init.protocolVersion == LATEST_PROTOCOL_VERSION
    assert init.serverInfo.name == "rfauto-http-probe"
    assert init.capabilities.tools is not None


def test_probe_tools_list_has_echo() -> None:
    """探针 2：tools/list 经 Streamable HTTP 返回 echo 工具与入参 schema。"""

    async def _list_tools(session) -> object:  # type: ignore[no-untyped-def]
        return await session.list_tools()

    _, tools = _run(_probe_roundtrip(lambda s, gid, m: _list_tools(s)))
    names = {t.name for t in tools.tools}
    assert "echo" in names
    echo = next(t for t in tools.tools if t.name == "echo")
    assert echo.inputSchema["type"] == "object"
    assert "text" in echo.inputSchema["properties"]


def test_probe_echo_call_roundtrip() -> None:
    """探针 3：tools/call 端到端回环——官方 SDK 客户端↔服务端 JSON-RPC
    全链（请求构造/传输解析/信封）在进程内打通。"""

    async def _call_echo(session, text: str) -> object:  # type: ignore[no-untyped-def]
        return await session.call_tool("echo", {"text": text})

    _, result = _run(_probe_roundtrip(lambda s, gid, m: _call_echo(s, "S11 10GHz probe")))
    assert not result.isError
    assert result.content[0].text == "echo: S11 10GHz probe"


def test_probe_error_path_unknown_tool() -> None:
    """探针 4：错误路径——未知工具名返回 isError 信封（不静默成功）。
    1.30.0 实测契约：缺工具不抛 JSON-RPC 协议错误，回 isError=True 的
    tool result（content="Unknown tool: ..."）——远程只读面的 ok/error
    信封形态可原样落到传输层（SPEC §3 错误形态节依据）。"""

    async def _call_unknown(session) -> object:  # type: ignore[no-untyped-def]
        return await session.call_tool("no_such_tool_qw95_probe", {})

    _, result = _run(_probe_roundtrip(lambda s, gid, m: _call_unknown(s)))
    assert result.isError is True
    assert "no_such_tool_qw95_probe" in result.content[0].text


def test_probe_stateless_session_contract() -> None:
    """探针 5：stateless 形态的会话合同——服务器不下发 Mcp-Session-Id
    （get_session_id() 为 None）。SPEC §3 结论依据：无会话句柄时远程认证
    必须走 Authorization 头而非会话绑定；有状态形态（多租户）是二期形态。"""

    def _inspect(session, get_session_id, _m):  # type: ignore[no-untyped-def]
        async def _go():  # type: ignore[no-untyped-def]
            return get_session_id()

        return _go()

    _, session_id = _run(_probe_roundtrip(_inspect))
    assert session_id is None
