"""EDA 格式解析五批扩展 MCP 工具组（aurora_r R-26 席位，2026-11-10）。

Q-X69 报告 §8 建议清单（在飞九域 MCP 五批候选）+ 交接书 §二-8 扩展池
方向的接地差集落地：DRC validate 校验面锚（交接书 §二-8 点名）、
Verilog-A 单模块查询（veriloga 域 MCP 面此前零覆盖）、SKILL 静态调用
图（Q-X69 九域清单 skill 域只读面的二线查询锚）、网表语义 overlay
三件套（R-02 AX-2 三 service 函数零 agent 面）。四域六工具全部
**复用既有 service 函数零逻辑转发**（规则 4；信封进出在 service，本
文件只做参数透传+异常兜底），无 CLI 叶的查询面照 parser_queries.py
先例首次 agent 面暴露，有 CLI 叶的与 CLI 同源同名 service 函数
（``rfauto drc validate``）。

全部六工具只读零副作用（不写盘不仿真不网络）；查询未命中不是调用
失败而是查询答案（ok=False errors 信封随附可用清单——消费方不猜，
与 service 口径一致）。不收在飞九域其余首线 parse/report 面（此前
批次已有取舍先例——stil parse/report 不收同款）。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope

__all__ = [
    "drc_design_validate",
    "netlist_overlay_file",
    "netlist_overlay_text",
    "skill_call_graph",
    "spectre_overlay_file",
    "veriloga_module_detail",
]


@mcp.tool
def drc_design_validate(design_path: str, rules_path: str | None = None,
                        rf: bool = False) -> dict[str, Any]:
    """DRC 校验：design JSON × 规则集 → 违规清单+verdict 判定信封。

    什么时候用：回答"这份布局过不过规则"——violations 逐条+summary
    计数+verdict 三态（违规不算调用失败，ok=True 照常，消费面看
    verdict）。与 CLI ``rfauto drc validate`` 同源。只读零副作用。
    规则缺省链：rules_path 给定→解析（format 自动检测）；未给且
    rf=True→内置 RF 规则集；双缺 → ok=False（usage 级）。要规则文件
    解析面走 drc_rules_parse。

    Args:
        design_path: design JSON 路径（objects 列表+可选 coordinate_unit）。
        rules_path: DRC 规则文件路径（None=须 rf=True 走内置缺省 RF
            规则集，双缺 → ok=False errors）。
        rf: True=启用 RF 特化检查器（规则文件中 RF 类型规则求值；
            无 rules_path 时用内置缺省 RF 规则集）；False（缺省）=纯
            结构规则（RF 规则不判，RF 检查未启用 warning 如实计数）。

    Returns:
        dict: ok=True 时 {ok, design_path, rules_path, rules_source,
        format, coordinate_unit, rules, groups, metadata, violations,
        summary, verdict, warnings}；失败 → ok=False errors。
    """
    from rfauto.service.drc_service import validate_design_file as _fn

    try:
        return _fn(design_path, rules_path, rf=rf)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def veriloga_module_detail(path: str, module: str) -> dict[str, Any]:
    """Verilog-A 单模块查询：.va 文件 → 指定 module 汇总视图。

    什么时候用：不读 modules 全量、只要"这个 Verilog-A 模块的端口/
    net/参数/analog 语句/贡献对账"——summary（模块名/ports/nets/
    params/analog stmt_counts/contributions/events 汇总）。veriloga
    域 MCP 面此前零覆盖，本工具系 service 二线查询面首次 agent 面
    暴露（无 CLI 叶）。只读零副作用，可安全调用。查询未命中是查询
    答案不是调用故障（ok=False errors 信封随附可用模块名录——消费方
    不猜；module=裸名精确匹配）。文件不存在/解析失败/无 module 声明
    （空文档或纯注释）→ ok=False errors。只读无时序约束。

    Args:
        path: Verilog-A 源文件路径（.va 文本）。
        module: 目标 module 裸名（文件内精确匹配）。

    Returns:
        dict: ok=True 时 {ok, path, module, summary, warnings}；未命中
        → ok=False errors（带可用名录）；文件失败 → ok=False errors。
    """
    from rfauto.service.veriloga_service import veriloga_module_detail as _fn

    try:
        return _fn(path, module)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def skill_call_graph(path: str) -> dict[str, Any]:
    """SKILL/OCEAN 静态调用图：源文件 → define→calls 边+外部调用面。

    什么时候用：回答"这份 SKILL/OCEAN 源里哪些定义互调、哪些调用落
    在外部"——defined_names（同名 define 符号集）+edges（逐边
    caller/callee，静态符号名匹配；递归=caller==callee 边如实）+
    external（被调名无同名定义清单）+n_edges/n_external 计数。Q-X69
    九域清单 skill 域只读面二线查询锚（无 CLI 叶，service 直消费，
    parser_queries.py 先例）。只读零副作用，可安全调用。文件不存在/
    为空（或纯注释）/词法括号失衡 → ok=False errors（失衡附 line/
    column 1 基结构化键）。无词法作用域分析（调用归属最近包围定义，
    core skill_call_edges 单源语义如实）。只读无时序约束。

    Args:
        path: SKILL/OCEAN 源文件路径（.il/.ils 文本）。

    Returns:
        dict: ok=True 时 {ok, path, defined_names, edges, external,
        n_edges, n_external, warnings}；失败 → ok=False errors。
    """
    from rfauto.service.skill_service import skill_call_graph as _fn

    try:
        return _fn(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def netlist_overlay_file(path: str, flavor: str = "auto",
                         min_coverage: float = 0.8) -> dict[str, Any]:
    """SPICE 网表语义 overlay：网表文件 → 逐元件语义标注+覆盖率门。

    什么时候用：拿到 SPICE 网表要"每个元件是什么语义角色、依据何在"
    ——overlay（逐元件标注+coverage{ratio/threshold/low_coverage/
    结论计数}+出处，只复述解析器既有推断并附出处，零物理数字产出）+
    diagnostics（解析诊断结构化层）。R-02 AX-2 三件套之文件面。只读
    零副作用，可安全调用。flavor 词表 auto/ngspice/hspice/spectre
    （auto=自动探测，flavor_detected 如实回显）；min_coverage=覆盖率
    门阈值（缺省 0.8；low_coverage=True 只标注不改 ok 语义）。文件
    不存在/不可读/词表外/解析失败 → ok=False errors。只读无时序约束；
    Spectre 原生语法走 spectre_overlay_file（本组另一工具）。

    Args:
        path: SPICE 网表文件路径（.cir/.sp/.spi/.ckt/.net 等文本网表）。
        flavor: SPICE 方言语系，auto（缺省）/ngspice/hspice/spectre。
        min_coverage: 覆盖率门阈值（0-1，缺省 0.8；只标注不拒调用）。

    Returns:
        dict: ok=True 时 {ok, path, flavor, flavor_requested,
        flavor_detected, overlay, diagnostics}；失败 → ok=False errors。
    """
    from rfauto.service.netlist_overlay_service import (
        netlist_semantic_overlay_file as _fn,
    )

    try:
        return _fn(path, flavor, min_coverage=min_coverage)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def spectre_overlay_file(path: str,
                         min_coverage: float = 0.8) -> dict[str, Any]:
    """Spectre 原生网表语义 overlay：Spectre 文件 → 逐元件语义标注。

    什么时候用：拿到 Spectre 原生语法网表（非 SPICE 方言）要"每个
    元件的语义角色与出处"——overlay（逐元件标注+coverage 覆盖率门
    同 netlist_overlay_file）+diagnostics（解析诊断）。R-02 AX-2
    三件套之 Spectre 原生面（解码链 utf-8 优先 Latin-1 兜底）。只读
    零副作用，可安全调用。min_coverage=覆盖率门阈值（缺省 0.8；
    low_coverage=True 只标注不改 ok 语义）。文件不存在/不可读/解析
    失败 → ok=False errors。只读无时序约束；SPICE 方言走
    netlist_overlay_file（本组另一工具）。

    Args:
        path: Spectre 原生网表文件路径（.scs/.spi 等文本）。
        min_coverage: 覆盖率门阈值（0-1，缺省 0.8；只标注不拒调用）。

    Returns:
        dict: ok=True 时 {ok, path, lang, overlay, diagnostics}；失败
        → ok=False errors。
    """
    from rfauto.service.netlist_overlay_service import (
        spectre_semantic_overlay_file as _fn,
    )

    try:
        return _fn(path, min_coverage=min_coverage)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def netlist_overlay_text(text: str, flavor: str = "auto",
                         min_coverage: float = 0.8) -> dict[str, Any]:
    """SPICE 网表文本语义 overlay：网表文本 → 逐元件语义标注（零落盘）。

    什么时候用：网表内容已在手（剪贴板/上游工具输出）不想先落临时
    文件——直接对文本做语义 overlay（overlay+diagnostics 键面同
    netlist_overlay_file；path 恒 None 如实标注无来源文件）。R-02
    AX-2 三件套之文本面。只读零副作用，可安全调用。flavor 词表
    auto/ngspice/hspice/spectre（auto=自动探测）；min_coverage=覆盖
    率门阈值（缺省 0.8）。空文本/词表外/解析失败 → ok=False errors。
    只读无时序约束。

    Args:
        text: SPICE 网表文本全文（原样解析，不落盘）。
        flavor: SPICE 方言语系，auto（缺省）/ngspice/hspice/spectre。
        min_coverage: 覆盖率门阈值（0-1，缺省 0.8；只标注不拒调用）。

    Returns:
        dict: ok=True 时 {ok, path=None, flavor, flavor_requested,
        flavor_detected, overlay, diagnostics}；失败 → ok=False errors。
    """
    from rfauto.service.netlist_overlay_service import (
        netlist_semantic_overlay_text as _fn,
    )

    try:
        return _fn(text, flavor, min_coverage=min_coverage)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
