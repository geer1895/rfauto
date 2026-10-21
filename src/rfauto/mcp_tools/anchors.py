"""anchors_list/anchors_inspect（DP-3 物理标定锚注册表）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。

异常壳信封走 error_envelope 单源（架构批 AU-2C 域升版 2026-10-14：
服务面失败形统一 ``errors`` list[str]，anchors 域 schema 1.1）。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope

# ─── 锚注册表 (DP-3) ──────────────────────────────────────────────────────────

@mcp.tool
def anchors_list() -> dict[str, Any]:
    """列出物理标定锚注册表全部锚（DP-3，knowledge/anchors.yaml）。

    无副作用，可安全调用。

    Returns:
        dict: {ok, registry, count, expected_count, load_errors,
               anchors: [{anchor_id, kind, status, version, engine_pair,
               quantity, value, uncertainty, domain, fallback}]}
    """
    from rfauto.service.anchors_service import list_anchors
    try:
        return list_anchors()
    except Exception as e:
        return error_envelope(str(e))


@mcp.tool
def anchors_inspect(anchor_id: str) -> dict[str, Any]:
    """单锚全量记录查询（anchors 域）：锚 id → provenance/不确定度/消费面。

    无副作用，可安全调用；不用于清单浏览（走 anchors_list）。未知锚 id
    → ok=False errors 如实。只读无时序约束。

    Args:
        anchor_id: 锚 id（如 c3.l_via_h.openems-hfss-v1）

    Returns:
        dict: {ok, anchor: {全量字段 + version}}；未知 id → ok=False errors
    """
    from rfauto.service.anchors_service import inspect_anchor
    try:
        return inspect_anchor(anchor_id)
    except Exception as e:
        return error_envelope(str(e))
