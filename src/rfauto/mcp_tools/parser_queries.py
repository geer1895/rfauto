"""EDA 格式解析二线查询/校验 MCP 工具组（aurora_q Q-X76 席位，2026-11-08）。

Q-X76 三批：解析器集群二线只读 service 函数（Q-X69 parser_formats.py
八域+Q-X73 cad_formats.py 十域均未收的查询/校验面）——本文件照抄
parser_formats.py/cad_formats.py 单组先例补齐 agent 只读查询面，完成
全集群 MCP 只读面收官：零逻辑转发 service 单源（规则 4；信封进出在
service，本文件只做参数透传+异常兜底）。与 CLI 同源叶：
``rfauto gdsii layers``（gdsii_layers）/``rfauto vcd report``
（vcd_report）/``rfauto ipc356 report --check-gerber/--check-drill``
（ipc356_fab_pair_check 同叶旗标分支）/``rfauto lefdef check``
（lef_def_check）；gdsii_hierarchy/sdf_cell_detail/spef_net_detail/
stil_pattern_detail 四函数系 service 二线查询面（无 CLI 叶，service 直
消费），本组为首次 agent 面暴露。

全部八工具只读零副作用（不写盘不仿真不网络）；查询未命中不是调用失败
而是查询答案（ok=False errors 信封随附可用清单——消费方不猜，与 service
口径一致）。裁面旋钮：vcd_report top_n 活跃度截断。LEF/DEF 交叉校验
lef_def_check 收单 LEF 基元入参（多份 LEF 走 CLI ``rfauto lefdef check
--lef`` 可重复旗标，MCP 入参全基元不收 Iterable）。

零 stdout 红线（#278）：本文件禁止 print——stdio 传输把 stdout 当
JSON-RPC 协议信道。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope

__all__ = [
    "gdsii_hierarchy",
    "gdsii_layers",
    "ipc356_fab_pair_check",
    "lef_def_check",
    "sdf_cell_detail",
    "spef_net_detail",
    "stil_pattern_detail",
    "vcd_report",
]


@mcp.tool
def gdsii_layers(path: str) -> dict[str, Any]:
    """GDSII 层汇总：.gds 二进制 → 逐 (layer,datatype) 元素计数+包围盒。

    什么时候用：不读结构六桶全量、只要"这版版图用了哪些层、每层多少
    元素、占多大范围"——layers（逐 (layer,datatype) 键：n_elements 计数
    +by_kind 桶拆分+DBU 原值包围盒 bbox_dbu；text 按 texttype、box 按
    boxtype 归并；排序确定性）+n_layer_keys 层键总数。与 CLI
    ``rfauto gdsii layers`` 同源。只读零副作用（纯读字节流离线解码），
    可安全调用。文件不存在/不可读/垃圾流/流中截断 → ok=False errors
    信封零静默。要六桶全量结构视图走 gdsii_parse；要引用/层级面走
    gdsii_hierarchy（本组另两工具）。只读无时序约束。

    Args:
        path: GDSII 文件路径（.gds 二进制流）。

    Returns:
        dict: ok=True 时 {ok, path, layers, n_layer_keys, warnings}；
        失败 → ok=False errors。
    """
    from rfauto.service.gdsii_service import gdsii_layer_report

    try:
        return gdsii_layer_report(path)
    except Exception as e:  # 观测面兜底（#105）：异常进信封不炸会话
        return error_envelope(str(e))


@mcp.tool
def gdsii_hierarchy(path: str) -> dict[str, Any]:
    """GDSII 层级报告：.gds 二进制 → 引用计数/未定义引用/孤儿双桶。

    什么时候用：回答"这版版图的结构层次健康吗"——reference_counts
    （逐结构被 SREF/AREF 引用计数）+undefined_references（SNAME 指向
    不存在结构的引用，逐名带次数）+orphan_structures（零引用**且**零
    元素）+unreferenced_structures（零引用含非空叶/顶层——宁多报不误
    报双桶都如实给出，消费方按需取用）。service 二线查询面（无 CLI
    叶）。只读零副作用，可安全调用。文件不存在/不可读/垃圾流 →
    ok=False errors。只读无时序约束；要逐层元素面走 gdsii_layers
    （本组另一工具）。

    Args:
        path: GDSII 文件路径（.gds 二进制流）。

    Returns:
        dict: ok=True 时 {ok, path, reference_counts,
        undefined_references, orphan_structures, unreferenced_structures,
        warnings}；失败 → ok=False errors。
    """
    from rfauto.service.gdsii_service import gdsii_hierarchy_report

    try:
        return gdsii_hierarchy_report(path)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def vcd_report(path: str, top_n: int = 10) -> dict[str, Any]:
    """VCD 活跃度报告：.vcd → 头部+计数+时间跨窗+信号 top 活跃度聚合。

    什么时候用：不回传事件流全量、只要"这段波形里哪些信号最活跃"——
    header（date/version/timescale）+stats 计数+time_windows（时间跨
    窗）+activity_top（逐信号事件数降序 top-N：id/名/scope 路径/位宽/
    事件数/x 事件数与占比；并列按 id 升序稳定——确定性）。与 CLI
    ``rfauto vcd report`` 同源。只读零副作用，可安全调用。top_n=活跃
    度 top 条数截断旋钮（缺省 10；0=空表）。文件不可读/语法违规 →
    ok=False errors。只读无时序约束；要事件流全量走 vcd_parse。

    Args:
        path: VCD 文件路径（.vcd 文本）。
        top_n: 活跃度 top 条数截断上限（缺省 10，0=空表）。

    Returns:
        dict: ok=True 时 {ok, path, header, stats, time_windows,
        activity_top, warnings}；失败 → ok=False errors。
    """
    from rfauto.service.vcd_service import vcd_report as _fn

    try:
        return _fn(path, top_n=top_n)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def sdf_cell_detail(path: str, celltype: str,
                    instance: str | None = None) -> dict[str, Any]:
    """SDF 单元查询：.sdf → 单 CELLTYPE(+实例) 命中 CELL+延迟路径清单。

    什么时候用：只要"这个 celltype（可限定实例）的延时"——matches
    （IEEE 1497 通配语义 match 键如实）+delay_paths 平坦清单（三值延
    时）。查询未命中是查询答案不是调用故障（ok=False 信封带可用清单
    ——消费方不猜；instance=None 只命中 top-level，
    ``*`` 只命中通配条目）。文件不存在/语法违规 → ok=False errors。
    只读无时序约束；要逐 celltype 计数聚合走 sdf_report。

    Args:
        path: SDF 文件路径（.sdf 文本）。
        celltype: 目标 CELLTYPE 名（大小写敏感精确比较）。
        instance: 目标实例名（None=只命中 top-level 条目；``*``=只命中
            通配条目；具体名=精确相等+该 celltype 通配条目）。

    Returns:
        dict: ok=True 时 {ok, path, celltype, instance, n_matches,
        matches, delay_paths, warnings}；未命中 → ok=False errors（带
        可用清单）；文件失败 → ok=False errors。
    """
    from rfauto.service.sdf_service import sdf_cell_detail as _fn

    try:
        return _fn(path, celltype, instance)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def spef_net_detail(path: str, name: str) -> dict[str, Any]:
    """SPEF 单 net 查询：.spef → 单 net 全量视图+拓扑摘要单条。

    什么时候用：不读全部 D_NET、只要"这条网络的连接/电容/电阻明细"——
    net（该 D_NET 全量：CONN/CAP/RES/IND）+topology（该 net 的拓扑
    摘要单条）。service 二线查询面（无 CLI 叶）。只读零副作用，可
    安全调用。查询未命中是查询答案不是调用故障（ok=False errors 信封
    随附可用 net 名录——消费方不猜；name=展开名）。文件不可读/语法
    违规 → ok=False errors。只读无时序约束；要拓扑+耦合聚合面走
    spef_report。

    Args:
        path: SPEF 文件路径（.spef 文本）。
        name: 目标 net 展开名（如层次名 u1/CK）。

    Returns:
        dict: ok=True 时 {ok, path, net, topology, warnings}；未命中 →
        ok=False errors（带可用名录）；文件失败 → ok=False errors。
    """
    from rfauto.service.spef_service import spef_net_detail as _fn

    try:
        return _fn(path, name)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def ipc356_fab_pair_check(ipc_path: str, gerber_path: str | None = None,
                          drill_path: str | None = None,
                          tol_mm: float = 0.5) -> dict[str, Any]:
    """IPC-D-356 × Gerber/Excellon 配对校验：越界焊盘+钻孔覆盖判定。

    什么时候用：回答"裸板测试网表与制造数据对得上吗"——越界判定
    （356 焊盘落 gerber 包络盒，出盒逐条 out_of_bounds 条目；缺轴/
    bbox 缺失 → n_skipped 如实）+覆盖判定（drill 孔位最近邻 ≤tol_mm
    计覆盖）。与 CLI ``rfauto ipc356 report --check-*`` 同源。只读零
    副作用；gerber_path/drill_path 至少给一（双缺 → ok=False usage 级）。

    Args:
        ipc_path: IPC-D-356/356A 文件路径（.ipc/.d356 文本）。
        gerber_path: Gerber RS-274X 层文件路径（None=跳过越界判定）。
        drill_path: Excellon 钻孔文件路径（None=跳过覆盖判定）。
        tol_mm: 钻孔覆盖最近邻容差 mm（缺省 0.5）。

    Returns:
        dict: ok=True 时 {ok, kind: "ipc356_pair_check", ...双侧判定
        面}；失败 → ok=False errors。
    """
    from rfauto.service.ipc356_service import (
        ipc356_fab_pair_check as _fn,
    )

    try:
        return _fn(ipc_path, gerber_path, drill_path, tol_mm=tol_mm)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def lef_def_check(lef_path: str, def_path: str,
                  macro: str | None = None) -> dict[str, Any]:
    """LEF×DEF 交叉校验：单 LEF+DEF → 闭包/连通/对齐三件套+verdict。

    什么时候用：回答"这版 DEF 的元件/pin 在科技 LEF 里对得上吗"——
    closure（macro 闭包 missing_models）+connectivity（悬空 net/未知
    引用）+alignment（pin 对齐三态）+summary 与 verdict。与 CLI
    ``rfauto lefdef check`` 同源（单 LEF 形态，多份走 CLI --lef）。只
    读零副作用；缺输入/不可读 → ok=False errors（同键置空供定位）。

    Args:
        lef_path: LEF 文件路径（单份科技/单元 LEF）。
        def_path: DEF 文件路径。
        macro: top-level 对齐目标 macro 名（None=DEF DESIGN 名）。

    Returns:
        dict: ok=True 时 {ok, lef_paths, def_path, design_name, units,
        closure, connectivity, alignment, summary, verdict, warnings}；
        失败 → ok=False errors。
    """
    from rfauto.service.lef_def_service import lef_def_check as _fn

    try:
        return _fn(lef_path, def_path, macro=macro)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))


@mcp.tool
def stil_pattern_detail(path: str, pattern: str) -> dict[str, Any]:
    """STIL 单 pattern 查询：.stil → 向量平坦清单+账目（loop/shift/ann）。

    什么时候用：只要"这条测试 pattern 的向量序与账目"——vectors
    （平坦清单文件序）+burst/wft 归属+账目计数与注记。service 二线
    查询面。查询未命中是查询答案不是调用故障（ok=False 随附可用
    pattern 名录；pattern=裸名跨 burst 首个命中）。文件不可读/语法
    违规 → ok=False errors；聚合面走 stil_report（CLI 同源）。

    Args:
        path: STIL 文件路径（.stil 文本）。
        pattern: 目标 pattern 裸名（跨 burst 首个命中）。

    Returns:
        dict: ok=True 时 {ok, path, pattern, burst, wft, vectors,
        n_vectors, n_loop, n_shift, anns, warnings}；未命中 → ok=False
        errors（带可用名录）；文件失败 → ok=False errors。
    """
    from rfauto.service.stil_service import stil_pattern_detail as _fn

    try:
        return _fn(path, pattern)
    except Exception as e:  # 观测面兜底（#105）
        return error_envelope(str(e))
