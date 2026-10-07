"""search_knowledge（QW-2 知识库统一检索）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 37. QW-2 知识库统一检索（knowledge_service 薄壳） ────────────────────────

@mcp.tool
def search_knowledge(query: str, scope: str = "all") -> dict[str, Any]:
    """知识库统一检索（QW-2）：rules/anchors/playbook/fab 剖面一键子串检索。

    只读零副作用，大小写不敏感子串匹配（纯确定性，零 LLM）；检索面含
    rules.yaml 规则 id/描述/hint/公式、anchors.yaml 锚 id/状态/量名/语义、
    diagnostics/playbook.yaml 失败指纹规则、fab_profiles/*.yaml 剖面名/来源。
    不用于运行时数值取证（snippet 仅供上下文）；无命中=正常非错误；
    空 query → ok=False。只读无时序约束。

    Args:
        query: 检索词（剥空白后须非空；大小写不敏感子串匹配）。
        scope: 检索域 "all"（缺省）| "rules" | "anchors" | "playbook" | "fab"。

    Returns:
        dict: {ok, query, scope, hits: [{source, name, snippet, path}],
        counts: {scope → 命中数, total}, scanned: {scope → 扫描条数}}；
        无命中 ok=True 零 hits（正常结果非错误）；空 query/非法 scope
        → ok=False。
    """
    from rfauto.service.knowledge_service import search_knowledge as _search
    try:
        return _search(query, scope)
    except Exception as e:
        return {"ok": False, "error": str(e)}
