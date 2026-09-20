"""M档 ADS 官方 MCP 后端（项目 A）—— 通过 bin/ads-mcp.exe 驱动 ADS。

真机评估结论（ADS 2027；安装根一律 RFAUTO_HPEESOF_DIR 优先、settings.local.yaml 回退）：
- stdio 传输，fastmcp Client 直连，零新增依赖
- 8 个工具：connect_session / start_local_session / execute_python /
  list_sessions / workspace_summary / search_docs / get_docs / disconnect_session
- start_local_session 支持 headless 会话（自动 checkout license，约 5-10s）
- execute_python 在持久 REPL 中执行，结果 JSON 含 ok/success/stdout/stderr

边界：官方 2027 文档声明 MCP 首发主要面向 Design Environment API；
电路仿真（hpeesofsim 等价）语义未获官方保证。因此本后端目前提供
异步会话上下文 + execute_python 原语 + smoke 探针；与 B 档 ads_sim_fn
完全等价的仿真后端待后续轮次实装。生产默认仍走 B 档
（见 knowledge/compat_matrix.yaml ads.versions."2027".channel）。
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MCP_EXE_RELPATH = Path("bin/ads-mcp.exe")


class AdsMcpBackend:
    """官方 ADS MCP server 的异步客户端封装（stdio）。

    用法::

        backend = AdsMcpBackend(ads_dir)
        async with backend.session() as execute:
            result = await execute("1 + 1")   # 持久 REPL，result 变量回传

    设计说明：transport 工厂可注入（tests 用桩替换，不依赖真机）。
    """

    def __init__(self, ads_dir: str | Path, transport_factory: Any = None) -> None:
        self.ads_dir = Path(ads_dir)
        self.mcp_exe = self.ads_dir / _MCP_EXE_RELPATH
        self._transport_factory = transport_factory or self._default_transport

    def _default_transport(self) -> Any:
        import os

        from fastmcp.client.transports import StdioTransport

        env = dict(os.environ)
        env["HPEESOF_DIR"] = str(self.ads_dir)
        return StdioTransport(
            command=str(self.mcp_exe),
            args=[],
            cwd=str(self.ads_dir / "bin"),
            env=env,
        )

    # ─── 结果解析 ────────────────────────────────────────────────────────────

    @staticmethod
    def parse_result(result: Any) -> dict[str, Any]:
        """MCP CallToolResult → dict（首个 TextContent 的 JSON）。"""
        content = getattr(result, "content", None) or []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"ok": True, "text": text}
        if getattr(result, "is_error", False):
            raise RuntimeError(f"MCP 工具调用失败: {result!r}"[:300])
        return {"ok": True, "text": ""}

    # ─── 会话生命周期 ────────────────────────────────────────────────────────

    def session(self):
        """异步上下文管理器：启动 headless 会话，yield execute(code) 协程函数，
        退出时 disconnect（失败不阻塞）。

        注意：start_local_session 会 checkout ADS license。
        """
        backend = self

        @asynccontextmanager
        async def ctx():
            from fastmcp import Client

            async with Client(backend._transport_factory()) as client:
                started = backend.parse_result(
                    await client.call_tool("start_local_session", {})
                )
                if not started.get("success", False):
                    raise RuntimeError(f"start_local_session 失败: {started}")

                async def execute(code: str) -> dict[str, Any]:
                    result = await client.call_tool("execute_python", {"code": code})
                    return backend.parse_result(result)

                try:
                    yield execute
                finally:
                    try:
                        await client.call_tool("disconnect_session", {})
                    except Exception as exc:
                        logger.warning("disconnect_session 失败（忽略）: %s", exc)

        return ctx()


async def smoke_test_async(ads_dir: str | Path) -> dict[str, Any]:
    """M档真机探针：起会话 → execute_python 探针 → 断开。返回审计信息。"""
    backend = AdsMcpBackend(ads_dir)
    async with backend.session() as execute:
        probe = await execute("result = {'probe': True}\n")
    ok = bool(probe.get("ok", False)) and probe.get("success", True) is not False
    return {"ok": ok, "step": "done", "probe": probe}


def smoke_test(ads_dir: str | Path) -> dict[str, Any]:
    """smoke_test_async 的同步入口。"""
    import asyncio

    return asyncio.run(smoke_test_async(ads_dir))
