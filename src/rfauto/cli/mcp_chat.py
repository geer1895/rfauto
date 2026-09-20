"""6j LLM 对话窗的 MCP 客户端通道（Plan §3 方向 6j 双通道可选）。

分层依据（.importlinter）：cli > mcp_server > service——MCP 客户端通道必须在
cli 层实现（service 反向 import mcp_server 会破坏分层契约）。内嵌通道是
service.r3_services.AgentChat（默认）；本模块与其同关键词路由、同源工具
（MCP 工具内部调同一批 service 函数）、同审计（audit.jsonl）。

fastmcp Client 以 in-memory 方式连接 get_mcp_server()，无需子进程。
"""

from __future__ import annotations

import json
from typing import Any


class MCPAgentChat:
    """MCP 客户端通道对话循环：每条消息 = 一次 MCP tool call。"""

    def __init__(self) -> None:
        self.history: list[dict[str, str]] = []

    def chat(self, message: str) -> dict[str, Any]:
        self.history.append({"role": "user", "content": message})
        response = self._route_message(message)
        self.history.append({"role": "assistant", "content": response.get("text", "")})
        return response

    def get_history(self) -> list[dict[str, str]]:
        return self.history

    # ── 路由 ────────────────────────────────────────────────────────────────

    def _route_message(self, message: str) -> dict[str, Any]:
        msg = message.lower().strip()

        if msg in ("models", "list models", "solvers"):
            return self._call("list_models")
        if msg in ("doctor", "health"):
            return self._call("doctor")
        if msg.startswith("validate "):
            return self._call("validate_recipe", {"recipe_path": message[9:].strip()})
        if msg.startswith("diagnose "):
            return self._call("diagnose", {"run_id": message[9:].strip()})
        if msg.startswith("metrics "):
            return self._call("get_metrics", {"run_id": message[8:].strip()})
        if msg.startswith("run "):
            return self._call("create_run", {"recipe_path": message[4:].strip()})
        return {
            "text": "MCP 通道可用命令:\n"
                    "  models - 列出已注册模型 (list_models)\n"
                    "  doctor - 环境探测 (doctor)\n"
                    "  validate <recipe> - 配方校验 (validate_recipe)\n"
                    "  diagnose <run_id> - 诊断 (diagnose)\n"
                    "  metrics <run_id> - 指标查询 (get_metrics)\n"
                    "  run <recipe> - 单次仿真 (create_run)",
            "action": "help",
        }

    # ── MCP 调用 ────────────────────────────────────────────────────────────

    def _call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        import asyncio

        from fastmcp import Client

        from rfauto.mcp_server import get_mcp_server

        async def _invoke() -> Any:
            async with Client(get_mcp_server()) as client:
                return await client.call_tool(tool, arguments or {})

        try:
            raw = asyncio.run(_invoke())
        except Exception as e:
            return {"text": f"MCP 调用失败: {e}", "action": "error",
                    "tool": tool, "ok": False}
        # fastmcp 版本差异兼容：优先结构化数据，逐级降级
        data = getattr(raw, "data", None)
        if data is None:
            sc = getattr(raw, "structured_content", None) or getattr(raw, "content", None)
            data = sc
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        return {"text": text, "action": f"mcp:{tool}", "tool": tool,
                "result": data, "ok": True}
