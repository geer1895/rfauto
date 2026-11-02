"""diagram_service —— RF 链路框图 .drawio 生成入口（T-O1 席，2026-10-31）。

"算画同源"第一件：RF 链路框图生成器——AI/用户给链路级表，产出的
.drawio 是**原生可编辑工程图**（非截图），每级框内标注本级增益/NF 与
级联累计（Friis），数字全部来自确定性内核（铁律 7）：

- 数字单源 = core/budget.py::LinkBudget（教科书 Friis 级联）；
- XML 装配 = core/link_diagram.py（自研 ElementTree 装配器，零第三方
  依赖、零 AGPL 复制——mxGraph XML 格式开放规范）；
- 本模块只做：入参校验 → 内核调用 → 落盘 → JSON 信封（规则 4：
  JSON 进出，CLI/MCP 是薄壳）。

确定性：同输入两次调用逐字节同文件（内核 XML 确定性 + 零时间戳）。
负例（空链/非有限 gain 等）显式报错——以 ok=False 错误信封出（CLI
--json 消费同构信封；不静默、不凑绿）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.link_diagram import build_link_diagram_xml, compute_link_chain
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["generate_link_diagram"]


def generate_link_diagram(
    chain: Any,
    out_path: Any,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """生成 RF 链路框图 .drawio 文件（每级标数字，Friis 级联=内核单源）。

    Args:
        chain: 级表（顺序=信号流向），级 schema 严格三键
            ``{"name": str, "gain_db": float, "nf_db": float}``；
            空链/缺键/非有限数值/负 NF 显式报错（错误信封，见下）。
        out_path: 输出 .drawio 路径（父目录须已存在；不自动建目录——
            路径错误显式报错而非静默补救）。
        title: 图标题（None 用内核缺省标题）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str, "n_stages": int,
             "gain_total_db": float, "nf_total_db": float,
             "stages": [{name, gain_db, nf_db,
                         cumulative_gain_db, cumulative_nf_db}, ...]}

        失败信封（校验负例/IO 错误）：``{"ok": False, "errors": [str...]}``。
        数值字段全部来自 LinkBudget 内核（与图内数字同源同值）。
    """
    try:
        computed = compute_link_chain(chain)
        xml_text = build_link_diagram_xml(chain, title=title)
        out = Path(out_path)  # PathLike 入参第一行收敛（#140）
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_text(xml_text, encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        n_stages=len(computed["stages"]),
        gain_total_db=computed["cascade_gain_db"],
        nf_total_db=computed["cascade_nf_db"],
        stages=computed["stages"],
    )
