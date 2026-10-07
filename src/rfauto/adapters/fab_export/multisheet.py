"""多页图纸：Sheet1 三视图+标注，Sheet2 特性表+技术要求（ezdxf 惰性 import）."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rfauto.core.fab_export.rules import RuleSet, default_ruleset
from rfauto.core.fab_export.schema import CriticalChar, DimsDocument

from .ezdxf_draw import (
    DrawingConfig,
    _auto_dimensions,
    _ensure_styles,
    _layers,
    _title_block,
    default_notes,
)


def render_two_sheet(
    out_path: str | Path,
    dims: DimsDocument,
    chars: Sequence[CriticalChar],
    *,
    config: DrawingConfig | None = None,
    rules: RuleSet | None = None,
) -> Path:
    """生成单 DXF 多布局近似：用大图纸分区（sheet1 主图 / sheet2 表）.

    工业多 sheet 完整实现可换图纸空间；此处保证「共2张 第1/2张」信息进标题栏。
    """
    try:
        import ezdxf  # type: ignore
        from ezdxf.enums import TextEntityAlignment  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("需要 ezdxf：pip install rfauto[fab]") from e

    rs = rules or default_ruleset()
    cfg = config or DrawingConfig(part_id=dims.part_id, rev=dims.rev, part_name=dims.part_id)
    # dims 传入：默认图注含 §6.2 DFM 行（穿丝/型腔基准/薄壁）
    cfg.notes = cfg.notes or default_notes(rs, dims)
    W, H = 420.0, 297.0  # A3
    cfg.sheet_mm = (W, H)
    cfg.sheet_no, cfg.sheet_total = 1, 2  # 标题栏「共2张 第1张」（docstring 口径落地）

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    _ensure_styles(doc)
    _layers(doc)

    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "FRAME"})
    # 中缝
    msp.add_line((W / 2, 10), (W / 2, H - 10), dxfattribs={"layer": "FRAME"})

    # Sheet1 左：标题栏 + 参数标注（完整多视图走 render_drawing）
    _title_block(msp, cfg, W / 2, H)
    _auto_dimensions(msp, dims, rs, cfg)

    # Sheet2 右：特性表（含检验方法栏/基准/抽检比——13A.4「检验方法栏」）
    x = W / 2 + 10
    y = H - 20
    msp.add_text(
        f"Sheet 2 / 2  特性表  {dims.part_id}",
        dxfattribs={"layer": "TEXT", "height": 4.0},
    ).set_placement((x, y), align=TextEntityAlignment.TOP_LEFT)
    y -= 10
    msp.add_text(
        "char_id | feature | nominal | +tol | -tol | datum | source | meas_method | inspect%",
        dxfattribs={"layer": "TEXT", "height": 3.0},
    ).set_placement((x, y), align=TextEntityAlignment.TOP_LEFT)
    y -= 7
    for c in chars[:30]:
        nom = "" if c.nominal is None else f"{c.nominal:g}"
        line = (
            f"{c.char_id} | {c.feature} | {nom} | {c.tol_plus:g} | {c.tol_minus:g} | "
            f"{c.datum or '-'} | {c.source_var} | {c.meas_method or '-'} | {c.inspect_pct:g}"
        )
        msp.add_text(line, dxfattribs={"layer": "TEXT", "height": 2.2}).set_placement(
            (x, y), align=TextEntityAlignment.TOP_LEFT
        )
        y -= 5.5
        if y < 80:
            break

    # 技术要求在左下
    y = 70
    for note in cfg.notes[:12]:
        msp.add_text(note, dxfattribs={"layer": "TEXT", "height": 2.8}).set_placement(
            (15, y), align=TextEntityAlignment.TOP_LEFT
        )
        y -= 5.5

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out))
    return out
