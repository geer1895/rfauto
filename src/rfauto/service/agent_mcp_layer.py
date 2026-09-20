"""MCP 工具层（WP3.8 三层栈·第 2 层）——生态标准工具协议的进程内桥。

方案口径：rfauto mcp_server 已把服务能力以
MCP 工具形式对外暴露（生态标准工具协议），多 Agent 编排的各角色**经同一
协议面**取用工具——工具调用 typed（JSON schema 约束入参，铁律 7）、结果
JSON 进出、协议边界内吞异常（isError 折入结果，不向调用方抛）。

本模块是 MCP wire 契约的进程内子集（transport/stdio/HTTP 由 fastmcp 的
mcp_server.py 承担，本轮不改该文件——后续轮次把这里的工具表接出即可）：

- **MCPTool**：name/description/inputSchema（MCP 规范的 tool 载荷三件套）
  + 确定性 handler（args dict → dict）；
- **MCPToolLayer.list_tools()**：tools/list 载荷（inputSchema 全量回传）；
- **MCPToolLayer.call_tool(name, arguments)**：tools/call 契约——返回
  ``{"content": [{"type": "text", "text": <json>}], "isError": bool}``；
  handler 异常/未知工具折入 isError 结果；
- **tool_spec_to_mcp**：既有 agent_runtime.ToolSpec（function-calling 形）
  ↔ MCP inputSchema 互转，两套协议面共享同一张工具表。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

#: 缺省 inputSchema（空对象约束：任意 object，无必填键）。
EMPTY_INPUT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


@dataclass
class MCPTool:
    """一个 MCP 工具：wire 三件套 + 确定性 handler。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: dict(EMPTY_INPUT_SCHEMA))
    handler: ToolHandler | None = None

    def to_wire(self) -> dict[str, Any]:
        """tools/list 单条载荷（MCP 规范：name/description/inputSchema）。"""
        return {"name": self.name, "description": self.description,
                "inputSchema": self.input_schema}


def tool_spec_to_mcp(spec: Any) -> dict[str, Any]:
    """agent_runtime.ToolSpec（function-calling 形）→ MCP tool wire 载荷。

    ToolSpec.to_schema 产 ``{"type":"function","function":{name,description,
    parameters}}``；MCP 形即把 parameters 平铺为 inputSchema。
    """
    fn = spec.to_schema().get("function") or {}
    return {
        "name": str(fn.get("name", getattr(spec, "name", ""))),
        "description": str(fn.get("description", "")),
        "inputSchema": dict(fn.get("parameters") or EMPTY_INPUT_SCHEMA),
    }


class MCPToolLayer:
    """进程内 MCP 工具层：注册表 + tools/list + tools/call。

    call_tool 契约（协议边界）：
    - 未知工具 / handler 异常 → ``{"content": [{"type": "text", "text":
      json}], "isError": True}``，**不向调用方抛协议外异常**；
    - handler 返回值必须是 dict（JSON 进出，服务层同规）。
    """

    def __init__(self, *, server_name: str = "rfauto-multi-agent") -> None:
        self.server_name = server_name
        self._tools: dict[str, MCPTool] = {}

    # ── 注册面 ───────────────────────────────────────────────────────────
    def register(self, tool: MCPTool) -> None:
        name = str(tool.name)
        if not name:
            raise ValueError("MCPTool.name 不能为空")
        if name in self._tools:
            raise ValueError(f"MCP 工具重复注册: {name}")
        self._tools[name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """装饰器注册：@layer.register_function("name", "...", schema)。"""
        def deco(fn: ToolHandler) -> ToolHandler:
            self.register(MCPTool(
                name=name, description=description,
                input_schema=dict(input_schema or EMPTY_INPUT_SCHEMA),
                handler=fn))
            return fn
        return deco

    # ── 查询/调用面（MCP wire 契约）─────────────────────────────────────
    def list_tools(self) -> list[dict[str, Any]]:
        """tools/list 载荷（名字序，确定性）。"""
        return [self._tools[n].to_wire() for n in sorted(self._tools)]

    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None
                  ) -> dict[str, Any]:
        """tools/call：返回 MCP CallToolResult 形（isError 折入，不抛）。"""
        tool = self._tools.get(str(name))
        if tool is None:
            return _error_result(f"未知 MCP 工具: {name}")
        if tool.handler is None:
            return _error_result(f"MCP 工具无 handler: {name}")
        try:
            result = tool.handler(dict(arguments or {}))
        except Exception as exc:  # 协议边界：异常折入 isError 结果
            return _error_result(f"MCP 工具 {name} 执行失败: {exc}")
        if not isinstance(result, dict):
            return _error_result(
                f"MCP 工具 {name} handler 必须返回 dict，得到 "
                f"{type(result).__name__}")
        return {
            "content": [{"type": "text",
                         "text": json.dumps(result, ensure_ascii=False,
                                            sort_keys=True)}],
            "isError": False,
            "structuredContent": result,
        }


def unwrap_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """CallToolResult → 业务 dict（结构化通道优先，失败抛协议错误）。

    供图节点等进程内消费者取回 handler 的原始 dict，省去二次 JSON 解析。
    """
    if result.get("isError"):
        raise RuntimeError(str(result.get("error", "MCP 工具调用失败")))
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content") or []:
        text = item.get("text") if isinstance(item, dict) else None
        if text:
            return {"text": str(text)}
    return {}


def _error_result(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": str(message)}],
        "isError": True,
        "error": str(message),
    }
