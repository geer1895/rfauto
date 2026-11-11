"""封装/测试封装域 MCP 工具组（aurora_q Q-X85 四批小席，2026-11-08）。

Q-X85 四批：odbpp/bsdl 两域（Q-X68 odbpp_service+Q-X77 bsdl_service 已
service+CLI 双面交付、MCP 面零覆盖）本文件照抄 parser_queries.py/
cad_formats.py 单组先例补齐——零逻辑转发 service 单源（规则 4；信封
进出在 service，本文件只做参数透传+异常兜底），完成 aurora_q MCP 只读
面四批收官。与 CLI 同源叶：``rfauto odbpp report --dir``（odbpp_report）
/``rfauto bsdl report --file``（bsdl_report）；bsdl_boundary_detail 系
service 二线查询面（无 CLI 叶），本组为首次 agent 面暴露。

全部三工具只读零副作用（不写盘不仿真不网络）；查询未命中不是调用失败
而是查询答案（ok=False errors 信封随附可用 port 名录——消费方不猜，与
service 口径一致）。裁面旋钮：bsdl_boundary_detail port 过滤（None=全量
平坦清单；未命中名录显示上限 30 条在 service 内置）。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope

__all__ = [
    "bsdl_boundary_detail",
    "bsdl_report",
    "odbpp_report",
]


@mcp.tool
def odbpp_report(dir_path: str) -> dict[str, Any]:
    """ODB++ 目录报告：目录树 → stack 对齐+net 库存统计聚合面。

    什么时候用：拿到 ODB++ 制造数据包要"一屏看懂版图库存健康"——
    逐 step 报告（层目录数/特征记录数/pad 引用/stack 对齐布尔+缺失/
    多余层清单+cadnet net 数与点数+eda net 数+悬空 pad+空 net）+全树
    统计（matrix 声明层数 vs 盘上层数/model_units）。与 CLI
    ``rfauto odbpp report`` 同源。只读零副作用（纯读目录树文本离线
    解析），可安全调用。目录不存在/缺 matrix → ok=False errors 信封
    零静默；文件面不可读已在 core fail-soft 消化（warnings 如实登记
    不判错）。只读无时序约束；要五文件全结构化视图走 CLI
    ``rfauto odbpp report``（service parse_odbpp_dir 形态）。

    Args:
        dir_path: ODB++ 目录根路径（matrix/ 所在目录）。

    Returns:
        dict: ok=True 时 {ok, kind: "odbpp_report", root, matrix_kind,
        n_layers_declared, n_layers_on_disk, steps, n_steps, empty_nets,
        n_empty_nets, dangling_pads, n_dangling_pads, model_units, stats,
        warnings}；失败 → ok=False errors（errors 恒 list[str]）。
    """
    from rfauto.service.odbpp_service import odbpp_report as _fn

    try:
        return _fn(dir_path)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def bsdl_report(path: str) -> dict[str, Any]:
    """BSDL 统计报告：.bsd 文件 → 指令表+边界分桶+长度一致性三数字。

    什么时候用：拿到边界扫描描述（IEEE 1149.1 BSDL）要紧凑一致性面——
    entity/统计计数+TAP 端口面+引脚映射摘要+指令表摘要（INSTRUCTION_
    OPCODE 表+capture+idcode 三态）+边界摘要（单元 function 分桶计数+
    BOUNDARY_LENGTH 一致性三数字：申报值/max 单元号+1/相对差——报告面
    不做硬门）。与 CLI ``rfauto bsdl report`` 同源。只读零副作用，可
    安全调用。文件不可读/空文件/无 entity/未收口 → ok=False errors。
    只读无时序约束；要全结构化视图（ports/pins/boundary_cells 全量）
    走 bsdl_boundary_detail（本组另一工具）。

    Args:
        path: BSDL 文件路径（.bsd/.bsdl 文本）。

    Returns:
        dict: ok=True 时 {ok, path, entity_name, n_entities, stats,
        tap_ports, n_tap_present, pins_summary, ports_summary,
        instruction_summary, boundary_summary, warnings}；失败 →
        ok=False errors。
    """
    from rfauto.service.bsdl_service import bsdl_report as _fn

    try:
        return _fn(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def bsdl_boundary_detail(path: str,
                         port: str | None = None) -> dict[str, Any]:
    """BSDL 边界单元查询：.bsd → 全量平坦清单或按 port 关联视图。

    什么时候用：不读实体全量、只要"边界寄存器长什么样/这个引脚的
    边界单元怎么配"——port=None 给全量平坦清单（声明序文件序，逐单元
    num/cell_type/port/function/safe/control 链字段）；port 给定给关联
    视图（input 直接/output3 经控制链关联出 control_cells）。service
    二线查询面（无 CLI 叶）。查询未命中是查询答案不是调用故障（
    ok=False errors 信封随附可用 port 名录，显示上限 30 条+总数注记
    ——消费方不猜）。只读零副作用，可安全调用。文件不可读/解析失败
    → ok=False errors。只读无时序约束；要指令表/一致性聚合面走
    bsdl_report（本组另一工具）。

    Args:
        path: BSDL 文件路径（.bsd/.bsdl 文本）。
        port: 目标 port 名（大小写不敏感；None=全量平坦清单；总线名
            无索引命中全部位）。

    Returns:
        dict: ok=True 时 {ok, path, entity_name, port, cells, n_cells,
        warnings}（port 命中另带 control_cells/n_control_cells）；
        未命中 → ok=False errors（带可用名录）；文件失败 → ok=False
        errors。
    """
    from rfauto.service.bsdl_service import bsdl_boundary_detail as _fn

    try:
        return _fn(path, port)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
