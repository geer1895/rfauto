"""EDA 格式解析八域 MCP 工具组（aurora_q Q-X69 席位，2026-11-08）。

Q-X33..X36+Q-X46..X49 八域解析器（SPICE/Liberty/CITI/SDC/IBIS/Verilog/
DRC/LVS）此前 service+CLI 双面交付、MCP 面零覆盖——本文件按 aging.py/
env_reliability.py 单组先例（多域一文件承载）补齐 agent 只读解析面：
零逻辑转发 service 单源（规则 4；信封进出在 service，本文件只做参数
透传+异常兜底），与 CLI 各域叶（``rfauto spice parse``/``liberty parse``/
``citi info``/``sdc parse``/``ibis parse``/``verilog parse``/``drc parse``/
``lvs compare``）同源同名 service 函数。

全部八工具只读零副作用（不写盘不仿真不网络）；大输出裁面走 service
自带的过滤/截断旋钮（cell/pin 过滤、include_tables/include_topology
裁面、citi max_values 截断），与 CLI 同参。在飞解析器域（spef/lefdef/
sdf/gdsii/fab/ipc356/touchstone/skill/vcd）不在本组——归后续接线席。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope

__all__ = [
    "citi_info",
    "drc_rules_parse",
    "ibis_parse",
    "liberty_parse",
    "lvs_compare_files",
    "sdc_parse",
    "spice_netlist_parse",
    "verilog_netlist_parse",
]


@mcp.tool
def spice_netlist_parse(path: str, flavor: str = "auto",
                        include_topology: bool = True) -> dict[str, Any]:
    """SPICE 网表解析：网表文件 → 结构化视图（元件/子电路/控制卡/模型/拓扑）。

    什么时候用：拿到 .cir/.sp/.spi 网表要读结构——elements（元件表）/
    subckts（子电路定义）/controls（控制卡）/models（模型卡）+ 可选
    topology（节点邻接/别名归一/MNA 尺寸等派生面）。与 CLI
    ``rfauto spice parse`` 同源。只读零副作用（不落盘不仿真），可安全
    调用。flavor 词表 auto/ngspice/hspice/spectre（auto=自动探测，
    flavor_detected 如实回显）；词表外/文件不存在/目录入参 → ok=False
    errors 信封零静默。include_topology=False 剪拓扑面（topology=None
    且 summary 拓扑派生字段如实 None 非 0）。只读无时序约束。

    Args:
        path: 网表文件路径（.cir/.sp/.spi/.ckt/.net 等文本网表）。
        flavor: SPICE 方言语系，auto（缺省）/ngspice/hspice/spectre。
        include_topology: True（缺省）=附拓扑派生面；False=剪面省信封。

    Returns:
        dict: ok=True 时 {ok, schema, parser_schema_version, path, flavor,
        flavor_requested, flavor_detected, title, elements, subckts,
        controls, models, topology, summary, structural_errors, warnings,
        include_topology}；失败 → ok=False errors（errors 恒 list[str]）。
    """
    from rfauto.service.spice_netlist_service import parse_netlist_file

    try:
        return parse_netlist_file(path, flavor,
                                  include_topology=include_topology)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def liberty_parse(path: str, cell: str | None = None,
                  pin: str | None = None, include_timing: bool = True,
                  include_power: bool = True) -> dict[str, Any]:
    """Liberty 时序库解析：.lib 文件 → 单元/pin/NLDM 时序表结构化视图。

    什么时候用：拿到标准单元库要读面——library/units/cells（含 pin 的
    direction/function/capacitance 与 timing/power 表组）/
    operating_conditions/lu_templates+stats 计数。与 CLI
    ``rfauto liberty parse`` 同源。只读零副作用，可安全调用。大库裁面
    三旋钮：cell=只留同名 cell（未知名 error 附可用清单）；pin=在 cell
    过滤基础上只留同名 pin（必须配合 cell）；include_timing/
    include_power=False 剪对应表体面（stats 对返回视图计数同步缩）。
    文件不可读/语法违规 → ok=False errors。只读无时序约束。

    Args:
        path: Liberty 文件路径（.lib）。
        cell: 只保留同名 cell（None=全库）。
        pin: 只保留同名 pin，必须配合 cell（None=cell 全 pin）。
        include_timing: True（缺省）=含 NLDM 时序表组；False=剪面。
        include_power: True（缺省）=含功率表组；False=剪面。

    Returns:
        dict: ok=True 时 {ok, path, library, file_version, units, cells,
        operating_conditions, lu_templates, stats, filters}；失败 →
        ok=False errors。
    """
    from rfauto.service.liberty_service import parse_liberty_file

    try:
        return parse_liberty_file(path, cell=cell, pin=pin,
                                  include_timing=include_timing,
                                  include_power=include_power)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def citi_info(path: str, max_values: int | None = None) -> dict[str, Any]:
    """CITI 仪器数据文件解析：.cti 包级结构化信息（段/变量/元数据）。

    什么时候用：拿到网络分析仪/LMS 仪器导出的 CITI 文件要读包结构——
    packages（逐包 version/name/segments/variables 及值列）+ summary
    包级概览（n_segments/segment_names/n_warnings）。与 CLI
    ``rfauto citi info`` 同源。只读零副作用，可安全调用。大值列截断走
    max_values（单值列截断上限；截断列带 values_truncated=true 与
    n_values 全量计数——显式声明不冒充完整；None=不截断）。文件不存在/
    解析失败 → ok=False errors。只读无时序约束；要解码段值走 CLI
    ``rfauto citi segments``（本组未收）。

    Args:
        path: CITI 文件路径（.cti）。
        max_values: 单值列截断上限（None=不截断）。

    Returns:
        dict: ok=True 时 {ok, path, packages, n_packages, summary}；
        失败 → ok=False errors。
    """
    from rfauto.service.citi_service import citi_info as _fn

    try:
        return _fn(path, max_values=max_values)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def sdc_parse(path: str) -> dict[str, Any]:
    """SDC 时序约束解析：.sdc 文件 → 约束全结构化视图。

    什么时候用：拿到 Synopsys 设计约束要读面——clocks（时钟定义）/
    delays（延时命令）/paths（时序路径命令）/constraints（约束集合）/
    objects/variables/commands（原始命令序）+stats 计数与 warnings
    （未知命令等非致命项）。与 CLI ``rfauto sdc parse`` 同源。只读零
    副作用（不落盘零网络零真机），可安全调用。文件不可读/语法违规 →
    ok=False errors。只读无时序约束；要命令名录清单走 CLI
    ``rfauto sdc list``（本组未收）。

    Args:
        path: SDC 文件路径（.sdc）。

    Returns:
        dict: ok=True 时 {ok, path, clocks, delays, paths, constraints,
        objects, variables, commands, warnings, stats}；失败 →
        ok=False errors。
    """
    from rfauto.service.sdc_service import parse_sdc_file

    try:
        return parse_sdc_file(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def ibis_parse(path: str, component: str | None = None,
               model: str | None = None,
               include_tables: bool = True) -> dict[str, Any]:
    """IBIS IO buffer 模型解析：.ibs 文件 → 器件/模型/引脚结构化视图。

    什么时候用：拿到 IBIS 模型要读面——header（版本/勾选项）/
    components（逐器件 pins/submodules）/models（buffer 模型，含
    tables/waveforms/ramp 表体）/model_selectors/pins（扁平引脚视图）
    +stats 计数。与 CLI ``rfauto ibis parse`` 同源。只读零副作用，可
    安全调用。大模型裁面三旋钮：component=只留同名器件（pins 同步收
    窄，未知名 error 附可用清单）；model=只留同名模型；include_tables=
    False 剪表体面（tables/waveforms/ramp 整键缺席，stats 同步归零，
    模型/引脚元数据不受影响）。文件不可读/语法违规 → ok=False errors。
    只读无时序约束。

    Args:
        path: IBIS 文件路径（.ibs）。
        component: 只保留同名 component（None=全器件）。
        model: 只保留同名 model（None=全模型）。
        include_tables: True（缺省）=含表体；False=剪面省信封。

    Returns:
        dict: ok=True 时 {ok, path, header, components, models,
        model_selectors, pins, warnings, stats, filters}；失败 →
        ok=False errors。
    """
    from rfauto.service.ibis_service import parse_ibis_file

    try:
        return parse_ibis_file(path, component=component, model=model,
                               include_tables=include_tables)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def verilog_netlist_parse(path: str,
                          with_topology: bool = True) -> dict[str, Any]:
    """Verilog 网表解析：.v 网表 → 模块五桶+例化+拓扑结构化视图。

    什么时候用：拿到门级/结构级 Verilog 网表要读面——modules（逐模块
    ports/wires/instances 等）、module_order/top_modules（层次判定）/
    instantiations/external_instance_types（黑盒类型）/directives+
    stats+topology（逐模块拓扑派生面）。与 CLI ``rfauto verilog parse``
    同源。只读零副作用，可安全调用。with_topology=False 剪拓扑面
    （topology 如实 None 非 0——派生字段缺席哨兵）。文件不可读/语法
    违规 → ok=False errors。只读无时序约束。

    Args:
        path: Verilog 网表文件路径（.v/.vg）。
        with_topology: True（缺省）=附逐模块拓扑派生面；False=剪面。

    Returns:
        dict: ok=True 时 {ok, path, modules, module_order, top_modules,
        instantiations, external_instance_types, directives, warnings,
        stats, topology}；失败 → ok=False errors。
    """
    from rfauto.service.verilog_netlist_service import parse_verilog_file

    try:
        return parse_verilog_file(path, with_topology=with_topology)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def drc_rules_parse(path: str, fmt: str = "auto") -> dict[str, Any]:
    """DRC 规则集解析：规则文件 → 统一结构化规则表（format/rules/groups）。

    什么时候用：拿到 DRC 规则清单（JSON/CSV/文本三格式）要读规则面——
    rules（归一规则表，文件序）、groups（组声明序+隐式组）、metadata
    （声明元数据+计算计数键：n_rules/n_enabled/n_rf_rules 等）、
    warnings（未知类型/单位/坏 priority 非致命项）。与 CLI
    ``rfauto drc parse`` 同源。只读零副作用，可安全调用。fmt 词表
    auto/json/csv/text（auto=探测；词表外/文件不可读/解析失败 →
    ok=False errors）。只读无时序约束；要对 design JSON 跑违规校验走
    CLI ``rfauto drc validate``（校验面不在本组——保持纯解析零歧义）。

    Args:
        path: DRC 规则文件路径（.json/.csv/.txt）。
        fmt: 格式词表，auto（缺省）/json/csv/text。

    Returns:
        dict: ok=True 时 {ok, path, format, rules, groups, metadata,
        warnings}；失败 → ok=False errors。
    """
    from rfauto.service.drc_service import parse_drc_file

    try:
        return parse_drc_file(path, fmt=fmt)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def lvs_compare_files(layout_path: str, schematic_path: str,
                      tolerance: float = 0.01, rf: bool = False,
                      fmt: str = "auto",
                      iso_step_budget: int | None = None) -> dict[str, Any]:
    """LVS 网表对照：两份网表文件（layout 侧 vs schematic 侧）→ 对照报告。

    什么时候用：回答"画出来的网表和原理图网表一致吗"——图同构判定
    （relay 重命名不绑名）+参数容差对照+RF 特化（rf=True）。verdict
    词表 MATCH/PARTIAL/MISMATCH/UNDECIDABLE（iso 预算耗尽时）；违规
    不算调用失败（消费面看 verdict/score/differences）。与 CLI
    ``rfauto lvs compare`` 同源。只读零副作用；fmt=auto/spice/verilog；
    任一侧装载失败 → ok=False errors（side 归属如实）。

    Args:
        layout_path: layout 侧网表文件路径（SPICE 或 Verilog）。
        schematic_path: schematic 侧网表文件路径（SPICE 或 Verilog）。
        tolerance: 参数对照相对容差（>=0，缺省 0.01）。
        rf: True=附 RF 特化对照（端口/传输线面）；False（缺省）=纯结构。
        fmt: 格式词表，auto（缺省）/spice/verilog。
        iso_step_budget: 同构搜索步数预算（None=内建缺省）。

    Returns:
        dict: ok=True 时 {ok, schema, verdict, score, differences,
        summary, layout, schematic, iso, rf, params, warnings}；失败 →
        ok=False errors。
    """
    from rfauto.service.lvs_compare_service import compare_netlist_files

    try:
        return compare_netlist_files(layout_path, schematic_path,
                                     tolerance=tolerance, rf=rf, fmt=fmt,
                                     iso_step_budget=iso_step_budget)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
