"""解析器集群结构化 tier 诊断小工具（aurora_r R-02 席位 AX-6，2026-11-10）。

EVAS（MIT，思想级吸收——四层 support-tier 语义）启发的**解析面"不支持/
跳过/降级"事件分层诊断**：把解析器 fail-soft 路径上"warning+跳行/降级"
的静默面升级为稳定命名的结构化事件流，每事件携带
``{tier, parser, reason, line, snippet}``——报告面可按层聚合解读，不把
解析盲区与语义盲区混报（EVAS 基准解读分层同源思想）。

四层判据（本模块单源；各解析器 docstring 引用同口径）：

- :data:`TIER_UNPARSED`（``unparsed``）——病态/残缺输入：无法映射到任
  何已支持语法形态，冒犯片段**零产出**跳过（序号非整数/列数非法/缺名/
  无法归类）。保留原文物证（snippet），
- :data:`TIER_UNSUPPORTED_1`（``unsupported-tier1``）——语法超集：已知
  方言/超集语法形态存在，本解析器**未实现该语法语义**（未知 ``*指令``/
  未收录元件首字母/方言混排段/量纲不可判定的方言数值形态）。
- :data:`TIER_UNSUPPORTED_2`（``unsupported-tier2``）——结构已识别、
  语义未实现：结构形态可定位且已如实登记（外部子电路引用/预处理条件/
  ``*SCALE`` 声明），但展开/代入/求值语义未实现（引用原文保真，绝不
  猜）。
- :data:`TIER_UNSUPPORTED_3`（``unsupported-tier3``）——部分支持已降
  级：已按支持子集解析产出，但字段/量纲/分类存在**如实降级**（方向
  None/未知单位系数取 1.0/兜底桶/EOF 强制收口）。

纪律（#331 家法）：``snippet`` 恒为**原文行**（仅剥行尾换行，不人工美
化不重排）——观察工具自身失真是 #331 定谳教训；无行锚的事件（文件级）
``line``/``snippet`` 如实 None。诊断是**附加层**：既返回 dict 的
``warnings``（str 文案，零变化）照旧，``diagnostics`` 为新增键（默认
行为零变化纪律，#315 全仓解包点已查——三解析器消费面全按键取用）。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——spef_parser/spectre_parser 同款先例，新模
块零金快照漂移）。

其他解析器域接入挂账处方（本席只接 SPEF/SPICE/SPECTRE 三面，其余域
零改动）：①解析主函数建 ``diags: list[dict] = []``；②每个跳行/降级
warning 点同笔 :func:`make_parse_diagnostic` 入列（tier 按上方判据定
档）；③返回 dict 增 ``"diagnostics"`` 键（附加键，既有键零变化）；
④报告面用 :func:`diagnostics_summary` 聚合。禁止改变既有 warning 文案
（文案是既定契约，substring 断言在档）。
"""

from __future__ import annotations

from typing import Any

#: 诊断 schema 版本（事件键集/分档词表变更时升位）。
DIAGNOSTIC_SCHEMA_VERSION = "1.0"

#: 病态/残缺输入（零产出跳过）。
TIER_UNPARSED = "unparsed"
#: 语法超集不支持（已知方言语法存在、语义未实现）。
TIER_UNSUPPORTED_1 = "unsupported-tier1"
#: 结构已识别、语义未实现（引用/声明已登记，展开/求值不做）。
TIER_UNSUPPORTED_2 = "unsupported-tier2"
#: 部分支持已降级（已产出但字段/量纲/分类如实降级）。
TIER_UNSUPPORTED_3 = "unsupported-tier3"

#: tier 词表闭集（定档非法即 ValueError——分档拼写错误当场抓）。
TIER_VALUES = frozenset({
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
    TIER_UNSUPPORTED_3,
})

#: 聚合面固定 tier 序（确定性输出：全四档恒出现，零计数也列）。
_TIER_ORDER = (
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
    TIER_UNSUPPORTED_3,
)


def line_snippet(raw: str) -> str:
    """原文行证据（#331 不美化）：仅剥行尾 ``\\r``/``\\n``，前导空白与
    行内内容逐字保留。"""
    return raw.rstrip("\r\n")


def make_parse_diagnostic(
    tier: str,
    reason: str,
    line: int | None,
    snippet: str | None,
    *,
    parser: str,
) -> dict[str, Any]:
    """单条结构化诊断（四层 tier 事件的标准形状）。

    Args:
        tier: 四层词表之一（:data:`TIER_VALUES`）。
        reason: 机读原因码或短句（稳定命名——报告面按此聚合）。
        line: 1 起行号；文件级事件如实 ``None``。
        snippet: 原文行（:func:`line_snippet` 口径）；无行锚如实 ``None``。
        parser: 解析器域标识（``"spef"``/``"spice_netlist"``/``"spectre"``）。

    Returns:
        ``{"schema", "tier", "parser", "reason", "line", "snippet"}``。
    """
    if tier not in TIER_VALUES:
        raise ValueError(
            f"tier={tier!r} 不在词表 {sorted(TIER_VALUES)}"
        )
    return {
        "schema": f"parse_diagnostic/{DIAGNOSTIC_SCHEMA_VERSION}",
        "tier": tier,
        "parser": parser,
        "reason": reason,
        "line": line,
        "snippet": None if snippet is None else line_snippet(snippet),
    }


def diagnostics_summary(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """诊断流聚合（报告面单源）：总数+全四档计数（零计数恒列出，确定性）。

    非法 tier 条目如实进 ``n_invalid_tier`` 不炸（观测面不阻塞主路径，
    #105 同族）。
    """
    by_tier: dict[str, int] = {tier: 0 for tier in _TIER_ORDER}
    n_invalid = 0
    for diag in diagnostics:
        tier = diag.get("tier")
        if tier in by_tier:
            by_tier[tier] += 1
        else:
            n_invalid += 1
    return {
        "schema": f"parse_diagnostic_summary/{DIAGNOSTIC_SCHEMA_VERSION}",
        "n_total": len(diagnostics),
        "by_tier": by_tier,
        "n_invalid_tier": n_invalid,
    }
