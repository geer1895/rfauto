"""schematic_diagram_service —— 引脚级原理图 .drawio 生成入口（aurora_p A1 席）。

"算画同源"第六件：ADS 网表 → **引脚级原理图**（元件符号带引脚点子 cell、
连线引脚到引脚、网名标注在连线上——与既有五叶框图级电路图互补，内核见
core/schematic_diagram.py）。两种输入形态（二选一，均完整实现）：

- **族形态**：``family``（wilkinson_snp | branchline_cascade）+ ``snp_path``
  + 可选 ``params``——经 linkage/ads_template_family.render_family 渲染出
  网表文本再建图（snp 文件仅在 sweep/n_ports 缺项时被读取；图面只消费其
  路径文本入 SnP File= 属性——本面不仿真，缺文件+缺参数显式报错信封）；
- **网表形态**：``netlist_text``（.net 文本，或经 ``netlist_path`` 传文件
  路径由本服务读入）——直入内核建图。

- 装配内核 = core/schematic_diagram.py（严格解析/布局/引脚装配）→
  core/drawio_xml.py（T-O2 通用 mxGraph XML 内核，零第三方依赖零 AGPL
  复制）；
- 本模块只做：形态分派 → 内核调用 → 落盘 → JSON 信封（规则 4：JSON
  进出，CLI/MCP 是薄壳）。

确定性：同输入两次调用逐字节同文件（内核 XML 确定性 + 零时间戳）。
负例（未知族/网表校验违约/IO 错误）显式报错——以 ok=False 错误信封出
（CLI --json 消费同构信封；不静默、不凑绿）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.schematic_diagram import build_schematic_plan
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["generate_schematic_diagram"]


def generate_schematic_diagram(
    out_path: Any,
    *,
    netlist_text: str | None = None,
    netlist_path: str | Path | None = None,
    family: str | None = None,
    snp_path: str | Path | None = None,
    params: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """生成引脚级原理图 .drawio 文件（网表 → 原生可编辑工程图）。

    Args:
        out_path: 输出 .drawio 路径（父目录须已存在；不自动建目录——
            路径错误显式报错而非静默补救）。
        netlist_text: ADS 网表文本（与 netlist_path 二选一）。
        netlist_path: ADS 网表文件路径（UTF-8/ASCII 文本读入）。
        family: 模板族名（wilkinson_snp | branchline_cascade；与
            netlist_text/netlist_path 互斥）。
        snp_path: Touchstone 路径（family 形态必给；仅渲染器需读元信息时
            才访问文件——图面只消费路径文本）。
        params: 族渲染器关键字参数（JSON 原生 dict，透传
            linkage.ads_template_family.render_family）。
        title: 图标题（None 用内核缺省标题）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str, "source": "family"|"netlist",
             "family": str|None,
             "n_components"/"n_ports"/"n_elements"/"n_nets_signal"/
             "n_ground_pins"/"n_wires"/"n_ground_stubs"/"n_dangling": int,
             "dangling": [str, ...],
             "components": [{name, kind, nodes, column, row}, ...],
             "nets": [{name, n_pins, pins, kind}, ...],
             "n_controls": int, "sweep": dict|None,
             "warnings": [str, ...]}

        失败信封（校验负例/IO 错误）：``{"ok": False, "errors": [str...]}``。
    """
    try:
        out = Path(out_path)  # PathLike 入参第一行收敛（#140）
        source: str
        if netlist_text is not None:
            if netlist_path is not None or family is not None:
                raise ValueError(
                    "netlist_text/netlist_path 与 family 互斥（恰给一）")
            text = netlist_text
            source = "netlist"
        elif netlist_path is not None:
            if family is not None:
                raise ValueError(
                    "netlist_text/netlist_path 与 family 互斥（恰给一）")
            p = Path(netlist_path)
            if not p.exists():
                raise FileNotFoundError(f"网表文件不存在: {p}")
            text = p.read_text(encoding="utf-8")
            source = "netlist"
        elif family is not None:
            from rfauto.linkage import ads_template_family as atf

            if family not in atf.FAMILIES:
                raise ValueError(
                    f"未知模板族 {family!r}（可选 {list(atf.FAMILIES)}）")
            if snp_path is None:
                raise ValueError("family 形态需给 snp_path（Touchstone 路径；"
                                 "图面只消费其路径文本）")
            text = atf.render_family(family, snp_path, dict(params or {}))
            source = "family"
        else:
            raise ValueError(
                "输入形态缺一：netlist_text/netlist_path（网表形态）或 "
                "family+snp_path（模板族形态）——恰给一")

        plan = build_schematic_plan(text, title=title)
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_text(plan["xml"], encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        source=source,
        family=family,
        n_components=plan["n_components"],
        n_ports=plan["n_ports"],
        n_elements=plan["n_elements"],
        n_nets_signal=plan["n_nets_signal"],
        n_ground_pins=plan["n_ground_pins"],
        n_wires=plan["n_wires"],
        n_ground_stubs=plan["n_ground_stubs"],
        n_dangling=plan["n_dangling"],
        dangling=plan["dangling"],
        components=plan["components"],
        nets=plan["nets"],
        n_controls=plan["n_controls"],
        sweep=plan["sweep"],
        warnings=plan["warnings"],
    )
