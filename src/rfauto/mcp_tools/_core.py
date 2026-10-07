"""MCP 单点共享态：FastMCP 实例 + lifespan 预导入 + 静音 pyaedt + _run_model_name helper（先于全部工具组模块导入）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# ─── Lifespan：解决 uv venv python shim + fastmcp stdio 首工具卡死 ──────────
# 根因（2026-08-30 排障）：uv venv python shim 重定向子进程时，
# 首个 call_tool 触发的延迟 import 在 stdio 管道上产生初始化阻塞。
# 对策：在 lifespan startup 预导入核心模块 + 静音 pyaedt，将初始化
# 成本从首次工具调用提前到服务器启动阶段。

@asynccontextmanager
async def _server_lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """服务器启动生命周期：预导入核心模块，解决首工具卡死。"""
    # 1. 静音 pyaedt 屏幕日志（stdio 通道保护）
    _silence_pyaedt_screen_logs()
    # 2. 预导入核心模块——flush 出延迟 import 的初始化副作用
    try:
        import rfauto.core.objectives
        import rfauto.core.parameters
        import rfauto.models.registry
        import rfauto.service.api  # noqa: F401
    except Exception:
        pass  # fake 通道/无 license 环境不受影响
    yield {}


# 创建 MCP 服务器实例
mcp = FastMCP(
    name="rfauto",
    instructions=(
        "rfauto HFSS ↔ ADS 自动化仿真调优框架的 MCP 服务器。"
        "提供环境探测、模型管理、配方校验、仿真执行、任务轮询、指标读取等工具。"
    ),
    lifespan=_server_lifespan,
)


def _silence_pyaedt_screen_logs() -> None:
    """静音 pyaedt 的屏幕日志（真机排障发现，2026-08-30）。

    stdio 传输下 server 的 stdout 是 MCP 协议通道；pyaedt 默认把
    "PyAEDT INFO: ..." 写到 stdout，客户端会收到非法 JSONRPC 消息。
    SDK 只在适配器内使用（军规 8），此处 import 失败则静默跳过
    （fake 通道/无 license 环境不受影响）。
    """
    try:
        from ansys.aedt.core.generic.settings import settings

        settings.enable_screen_logs = False
    except Exception:
        pass


# ─── 11. diagnose ─────────────────────────────────────────────────────────────

def _run_model_name(run_id: str) -> str:
    """best-effort 读 run 元数据里的模型名（决定规则适用域），失败回退 "all"。

    #105：元数据读取不阻塞主路径——meta.json 缺失/损坏时回退 "all"，
    仅保留通用规则（R002/R003/R004），模型限定规则（R001/R006/R007/R009）
    自动跳过，不臆测模型名。
    """
    meta_path = Path("runs") / run_id / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return "all"
    name = meta.get("model") if isinstance(meta, dict) else None
    return str(name) if name else "all"
