"""drawio_svg_service —— .drawio → SVG 渲染入口（aurora_p C3，2026-11-01）。

报告/服务器场景无 draw.io 桌面 GUI 的看图件：既有 rfauto 六叶（link/
testsetup/annotate/stackup/schematic/ads-circuit）产出的 .drawio（以及
任何未压缩 mxfile）→ 静态 SVG 落盘。

- 渲染内核 = core/drawio_svg.py（框+连线+文字直映射；样式支持子集
  常量表单源；不支持形态降级占位+warnings 显式回显；压缩页显式报错
  ——read 面 DrawioReadError 原样透传）；
- 本模块只做：路径纪律（source 只读、out 不自动建目录、source==out
  同路径覆盖显式报错——annotation service `_same_path` 同款 normcase
  口径）→ 内核调用 → 落盘 → JSON 信封（规则 4：JSON 进出，CLI/MCP
  是薄壳）。

零数值逻辑：SVG 内几何=drawio 坐标直映射、文字=value 原值原样（铁律
7——本服务零换算零重算）。确定性：同输入两次调用 SVG 逐字节相同
（内核零时间戳零 uuid）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rfauto.core.drawio_svg import render_xml_text
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["render_drawio_svg"]


def _same_path(a: Any, b: Any) -> bool:
    """同路径判定（Windows 大小写/分隔符不敏感——normcase+#105 .lower()，
    与 diagram_annotation_service._same_path 同款口径）。"""
    na = os.path.normcase(os.path.abspath(str(a))).lower()
    nb = os.path.normcase(os.path.abspath(str(b))).lower()
    return na == nb


def render_drawio_svg(
    source_path: Any,
    out_path: Any,
    *,
    page_index: int = 0,
) -> dict[str, Any]:
    """渲染 .drawio 为静态 SVG 文件（只读 source；--out 落盘）。

    Args:
        source_path: 输入 .drawio 路径（未压缩 mxfile；压缩页显式报错）。
        out_path: 输出 .svg 路径（父目录须已存在，不自动建目录；
            **禁与 source 同路径**——覆盖原稿显式报错）。
        page_index: 页序号（0 起缺省首页；越界显式报错）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str, "source_path": str,
             "page_index": int, "n_pages": int, "diagram_name": str,
             "n_vertices": int, "n_edges": int, "n_layers": int,
             "n_degraded": int, "warnings": [str, ...]}

        失败信封（缺文件/压缩页/非 mxfile/页序越界/空页/同路径覆盖/
        父目录缺失）：``{"ok": False, "errors": [str...]}``。
    """
    src = Path(source_path)  # PathLike 入参第一行收敛（#140）
    out = Path(out_path)
    try:
        if _same_path(src, out):
            raise ValueError(
                f"source 与 out 同路径（{src}）：输入原稿不可覆盖，"
                "请另给 .svg 输出路径")
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        xml_text = src.read_text(encoding="utf-8")
        svg_text, stats = render_xml_text(xml_text, page_index)
        out.write_text(svg_text, encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        # DrawioReadError/DrawioSvgError 均为 ValueError 子类——错误信封
        # 同路捕获（压缩页/坏 XML/越界/空页显式回显，不静默不炸）
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        source_path=str(src),
        page_index=page_index,
        n_pages=stats["n_pages"],
        diagram_name=stats["diagram_name"],
        n_vertices=stats["n_vertices"],
        n_edges=stats["n_edges"],
        n_layers=stats["n_layers"],
        n_degraded=stats["n_degraded"],
        warnings=stats["warnings"],
    )
