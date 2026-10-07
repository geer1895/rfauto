"""get_guidelines_for（EC-6 上下文工具，W5-D）：坑账/playbook/rules 确定性检索薄壳。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── EC-6 guidelines 上下文工具（service/guidelines_service 薄壳，零逻辑） ─────


@mcp.tool
def get_guidelines_for(topic: str) -> dict[str, Any]:
    """坑规指南检索（guidelines 域）：主题词 → 坑账/playbook/规则三源命中。

    EC-6。只读零副作用零 LLM 零网络（类别映射+大小写不敏感关键词，纯
    确定性，同输入逐位一致）；数据源=knowledge/pitfalls_index.json +
    knowledge/diagnostics/playbook.yaml + knowledge/rules.yaml；每条带
    source/ref/anchor 可溯源（坑号 #NNN 为 出处标记）。与
    search_knowledge 的差异：本工具按主题做跨源归类检索并附取证命令，
    search_knowledge 按域做子串全文检索。未知名 topic 或数据源缺失 →
    ok=False errors 非空（附已知类别词表，不凑结果）。只读无时序约束。

    Args:
        topic: 主题词（如 openems、hfss、kicad、fdtd、校准；剥空白后须非空）。

    Returns:
        dict: {ok, topic, hits: [{source, ref, category, text, anchor, ...}],
        counts: {pitfalls, playbook, rules, total}}；未知名 topic 或数据源
        缺失 → ok=False errors 非空（附已知类别词表，不凑结果）。
    """
    from rfauto.service.guidelines_service import get_guidelines_for as _get

    return _get(topic)
