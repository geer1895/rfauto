"""CAD 制造/数字后端/波形 MCP 工具组（8 域 10 工具；aurora_q Q-X73 席位，2026-11-08；
勘误 2026-11-10 合流笔：原文"十域"实为 8 域 10 工具——LEF/DEF 并记口径不一，FINAL_AUDIT P2-4）。

Q-X73 二批：在飞九域解析器（SPEF/LEF/DEF/SDF/GDSII/Gerber+Excellon/
IPC-D-356/Touchstone/VCD）此前 service+CLI 双面交付、MCP 面零覆盖——
本文件照抄 parser_formats.py（Q-X69）单组先例补齐 agent 只读解析面：
零逻辑转发 service 单源（规则 4；信封进出在 service，本文件只做参数
透传+异常兜底），与 CLI 各域叶（``rfauto spef parse``/``spef report``/
``lefdef parse``/``sdf parse``/``sdf report``/``gdsii parse``/
``fab parse``（配 --drill 即 pair check）/``ipc356 report``/
``touchstone info``/``vcd parse``）同源同名 service 函数。

全部十工具只读零副作用（不写盘不仿真不网络）；大输出裁面走 service
自带的截断/过滤旋钮（spef_report top_k 最强耦合对条数）。LEF/DEF 合并
入口 lef_def_parse 收单 LEF+可选 DEF（MCP 入参全基元；多份 LEF 走 CLI
``rfauto lefdef parse --lef`` 可重复旗标，本组不收 Iterable）。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope

__all__ = [
    "gdsii_parse",
    "gerber_excellon_pair_check",
    "ipc356_report",
    "lef_def_parse",
    "sdf_parse",
    "sdf_report",
    "spef_parse",
    "spef_report",
    "touchstone_info",
    "vcd_parse",
]


@mcp.tool
def spef_parse(path: str) -> dict[str, Any]:
    """SPEF 寄生交换格式解析：.spef 文件 → 全结构化视图（头部/NAME_MAP/PORTS/D_NET）。

    什么时候用：拿到标准寄生交换格式（IEEE 1481）要读面——header
    （design/单位系/分隔符）+name_map/name_map_reverse（索引名双向表）+
    ports（端口方向）+nets（逐 D_NET：CONN/CAP/RES/IND 全量）+stats
    计数。与 CLI ``rfauto spef parse`` 同源。只读零副作用（不落盘
    不仿真），可安全调用。只要拓扑摘要+耦合统计走 spef_report（本组
    另一工具）。文件不可读/语法违规 → ok=False errors 信封零静默。
    只读无时序约束。

    Args:
        path: SPEF 文件路径（.spef 文本）。

    Returns:
        dict: ok=True 时 {ok, path, header, name_map, name_map_reverse,
        ports, nets, stats, warnings}；失败 → ok=False errors（errors
        恒 list[str]）。
    """
    from rfauto.service.spef_service import parse_spef_file

    try:
        return parse_spef_file(path)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def spef_report(path: str, top_k: int = 5) -> dict[str, Any]:
    """SPEF 拓扑摘要+耦合统计聚合：.spef 文件 → 拓扑/耦合紧凑报告面。

    什么时候用：不读 D_NET 全量、只要"这版寄生长什么样"——topology
    （逐 net 摘要：节点/电容/电阻计数）+coupling（耦合电容统计：
    n_coupling/n_ground/总和/耦合对地比+最强耦合对 top_k 条）+stats
    计数。与 CLI ``rfauto spef report`` 同源。只读零副作用，可安全
    调用。top_k=最强耦合对条数截断旋钮（缺省 5；按值降序+文档序稳定
    排序——确定性）。文件不可读/语法违规 → ok=False errors。只读无
    时序约束；SPEF 单 net 全量视图走 CLI ``rfauto spef report``
    （勘误 2026-11-10 合流笔：原文指引 ``spef net-detail`` 叶不存在——spef 域只有 parse/report 两叶，FINAL_AUDIT 挂账勘误）
    （本组未收）。

    Args:
        path: SPEF 文件路径（.spef 文本）。
        top_k: 最强耦合对条数截断上限（缺省 5，0=空表）。

    Returns:
        dict: ok=True 时 {ok, path, design, units, topology, coupling,
        stats, warnings}；失败 → ok=False errors。
    """
    from rfauto.service.spef_service import spef_report as _fn

    try:
        return _fn(path, top_k=top_k)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def lef_def_parse(lef_path: str | None = None,
                  def_path: str | None = None) -> dict[str, Any]:
    """LEF/DEF 组合解析：科技/单元 LEF（单份）+可选 DEF → 双侧结构化信封。

    什么时候用：拿到物理设计交换格式要读面——lef 侧信封（units/
    layers/vias/macros 等）+def 侧信封（design_name/components/pins/
    nets 等）。与 CLI ``rfauto lefdef parse`` 同源。只读零副作用；
    两类输入都缺/任一文件不可读 → ok=False errors 且 lef/def 键保留
    逐文件信封供定位；多份 LEF 或交叉校验走 CLI ``rfauto lefdef
    check``。

    Args:
        lef_path: LEF 文件路径（None=只解析 DEF；需与 def_path 至少给一）。
        def_path: DEF 文件路径（None=只解析 LEF）。

    Returns:
        dict: ok=True 时 {ok, lef: [LEF 信封...], def: DEF 信封|None}；
        失败 → ok=False errors（lef/def 键同在）。
    """
    from rfauto.service.lef_def_service import parse_lef_def

    try:
        return parse_lef_def(lef_path, def_path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def sdf_parse(path: str) -> dict[str, Any]:
    """SDF 标准延时格式解析：.sdf 文件 → 全结构化视图（头部/CELL/celltypes）。

    什么时候用：拿到标准延时格式（IEEE 1497）要读面——header
    （SDFVERSION/DESIGN/TIMESCALE/VOLTAGE/TEMPERATURE 等）+cells
    （逐 CELL：CELLTYPE/INSTANCE/DELAY 的 IOPATH/INTERCONNECT/COND 与
    TIMINGCHECK 全量三值延时）+celltypes（celltype 分组视图）+stats
    计数。与 CLI ``rfauto sdf parse`` 同源。只读零副作用，可安全调用。
    只要逐 celltype 计数+TIMINGCHECK 摘要走 sdf_report（本组另一工具）。
    文件不存在/不可读/空文件/括号失配等语法违规 → ok=False errors。
    只读无时序约束。

    Args:
        path: SDF 文件路径（.sdf 文本）。

    Returns:
        dict: ok=True 时 {ok, path, schema, header, cells, celltypes,
        stats, warnings}；失败 → ok=False errors（errors 恒 list[str]）。
    """
    from rfauto.service.sdf_service import parse_sdf_file

    try:
        return parse_sdf_file(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def sdf_report(path: str) -> dict[str, Any]:
    """SDF 紧凑报告：.sdf 文件 → 头部+逐 celltype 计数+TIMINGCHECK 摘要。

    什么时候用：不回传 cells 全量、只要"这版延时文件里什么 celltype
    各多少、最坏时序检查值多少"——celltype_counts（逐 celltype 计数
    聚合）+timing_check_summary（逐 celltype 最坏值口径，全在 core
    聚合函数）。与 CLI ``rfauto sdf report`` 同源。只读零副作用，可
    安全调用。文件不存在/不可读/空文件/语法违规 → ok=False errors。
    只读无时序约束；要 IOPATH/INTERCONNECT 全量明细走 sdf_parse
    （本组另一工具）。

    Args:
        path: SDF 文件路径（.sdf 文本）。

    Returns:
        dict: ok=True 时 {ok, path, schema, header, stats, celltypes,
        celltype_counts, timing_check_summary, warnings}；失败 →
        ok=False errors。
    """
    from rfauto.service.sdf_service import sdf_report as _fn

    try:
        return _fn(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def gdsii_parse(path: str) -> dict[str, Any]:
    """GDSII 版图流解析：.gds 二进制 → lib/单位/结构六桶全结构化视图。

    什么时候用：拿到 GDSII 流要读面——lib_name/version/units（用户
    单位与 dbu 换算，units_raw 原始双实数）+structures（逐结构六桶：
    boundary/path/sref/aref/text/box 元素全量）+stats 计数。与 CLI
    ``rfauto gdsii parse`` 同源。只读零副作用（纯读字节流离线解码），
    可安全调用。文件不存在/不可读/垃圾流/流中截断 → ok=False errors
    （截断态不冒充完整文档）。只读无时序约束；要分层摘要/层次展开走
    CLI ``rfauto gdsii layers``（本组未收）。

    Args:
        path: GDSII 文件路径（.gds 二进制流）。

    Returns:
        dict: ok=True 时 {ok, path, lib_name, version, units, units_raw,
        structures, stats, warnings}；失败 → ok=False errors。
    """
    from rfauto.service.gdsii_service import parse_gdsii_file

    try:
        return parse_gdsii_file(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def gerber_excellon_pair_check(gerber_path: str,
                               drill_path: str) -> dict[str, Any]:
    """Gerber+Excellon 交叉校验：光绘包络盒 × 钻孔孔位 → 越界判定报告。

    什么时候用：回答"钻孔有没有打到板框外"——gerber 层 bbox 求包络
    盒（bbox_mm），逐钻孔命中点两轴判定，任一轴出界即 out_of_bounds
    条目 {index, tool, x_mm, y_mm, axis, value_mm}+n_hits/n_tools/
    per_tool_counts 孔数汇总。与 CLI ``rfauto fab parse``（配 --drill
    时同源分支）同源。只读零副作用，可安全调用。判定口径如实三分
    （#122 不凑绿）：孔位任一轴未知或 bbox 不可用（无几何参照）→
    n_skipped 如实计数不判越界（notes 说明归因）。任一文件解析失败 →
    ok=False errors（首错优先）。只读无时序约束。

    Args:
        gerber_path: Gerber RS-274X 光绘文件路径（bbox 参照面）。
        drill_path: Excellon 钻孔文件路径（孔位判定面）。

    Returns:
        dict: ok=True 时 {ok, kind: "pair_check", gerber_path,
        drill_path, bbox_mm, n_hits, n_slots, n_tools, per_tool_counts,
        n_out_of_bounds, out_of_bounds, n_skipped, notes}；失败 →
        ok=False errors。
    """
    from rfauto.service.fab_gerber_service import (
        gerber_excellon_pair_check as _fn,
    )

    try:
        return _fn(gerber_path, drill_path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def ipc356_report(path: str) -> dict[str, Any]:
    """IPC-D-356 网表提取报告：.ipc 文件 → 统计+单点 net+测试点 bbox 聚合。

    什么时候用：拿到裸板电气测试网表（IPC-D-356/356A）要紧凑面——
    version/scale_factor+nets（net 名录排序）+single_point_nets（单点
    net 开路嫌疑清单）+bbox_mm（焊盘+过孔已知坐标包络盒；全未知如实
    None 不猜）+stats/truncated 计数。与 CLI ``rfauto ipc356 report``
    同源。只读零副作用，可安全调用。文件不可读/语法违规 → ok=False
    errors。只读无时序约束；要逐记录全量视图走 CLI ``rfauto ipc356
    parse``（本组未收）。

    Args:
        path: IPC-D-356 文件路径（.ipc/.356 文本）。

    Returns:
        dict: ok=True 时 {ok, kind: "ipc356_report", path, version,
        scale_factor, nets, single_point_nets, bbox_mm, stats,
        truncated, warnings}；失败 → ok=False errors。
    """
    from rfauto.service.ipc356_service import ipc356_report as _fn

    try:
        return _fn(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def touchstone_info(path: str) -> dict[str, Any]:
    """Touchstone 文件嗅探：.sNp → 格式证据+rank 三规则推断+冲突报告。

    什么时候用：拿到 S 参数文件先问"这是几端口的、什么格式"——format
    （option line/单位系/关键字块证据）+rank（三规则证据：文件名/首行
    /数据块）+n_ports/n_freqs/band（f_min_hz/f_max_hz）+disagreements
    （规则间冲突清单）。与 CLI ``rfauto touchstone info`` 同源。只读
    零副作用，可安全调用。info 是查询面：rank 冲突不是失败而是查询
    答案（ok=True 且 disagreements 如实；n_ports=None 表不可定）；
    结构违规（option line 缺失/空文件）才是失败态 → ok=False errors。
    只读无时序约束。

    Args:
        path: Touchstone 文件路径（.s1p/.s2p/.s4p 等）。

    Returns:
        dict: ok=True 时 {ok, path, format, rank, n_ports, n_freqs,
        freqs_hz, band, disagreements, parse_error}；失败 → ok=False
        errors（仍带格式+rank 证据键）。
    """
    from rfauto.service.touchstone_service import touchstone_info as _fn

    try:
        return _fn(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def vcd_parse(path: str) -> dict[str, Any]:
    """VCD 值变化转储解析：.vcd → 头部/scope 树/vars/事件流全结构化视图。

    什么时候用：拿到仿真波形转储（Value Change Dump）要读面——header
    （date/version/timescale）+scopes（scope 树）+vars（逐变量 id 码/
    位宽/类型）+events（值变化事件流）+dump_regions（$dumpvars 窗口）
    +stats/comments。与 CLI ``rfauto vcd parse`` 同源。只读零副作用，
    可安全调用。文件不可读/语法违规 → ok=False errors 信封零静默。
    只读无时序约束；要逐变量翻转统计走 CLI ``rfauto vcd report``
    （本组未收）。

    Args:
        path: VCD 文件路径（.vcd 文本）。

    Returns:
        dict: ok=True 时 {ok, path, header, scopes, vars, events,
        dump_regions, stats, comments, warnings}；失败 → ok=False
        errors（errors 恒 list[str]）。
    """
    from rfauto.service.vcd_service import parse_vcd_file

    try:
        return parse_vcd_file(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
