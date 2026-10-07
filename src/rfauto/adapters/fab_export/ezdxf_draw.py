"""ezdxf 出图引擎：GB 图框 + 参数标注 + 技术要求（ezdxf 惰性 import）.

标注值只从 dims.json 取，禁止测量几何回填。
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rfauto.core.fab_export.process_notes import dfm_notes, process_tag_for
from rfauto.core.fab_export.rules import RuleSet, default_ruleset
from rfauto.core.fab_export.schema import DimsDocument, VariableDim
from rfauto.core.fab_export.views import build_wr90_views, flange_hole_table


@dataclass
class DrawingConfig:
    part_name: str = "零件名称"
    part_id: str = "P-001"
    rev: str = "A"
    material: str = "AL6061-T6"
    scale: str = "1:1"
    org: str = "单位名称"
    weight: str = ""
    sheet_mm: tuple[float, float] = (297.0, 210.0)  # A4 landscape
    title_block_w: float = 180.0
    title_block_h: float = 56.0
    notes: list[str] = field(default_factory=list)
    designer: str = ""
    checker: str = ""
    approver: str = ""
    # GB/T 10609.1 标题栏字段全集补齐（细则 §2.1/§13.1；此前缺失项）
    date: str = ""  # 年月日
    stage: str = ""  # 阶段标记（缺省回退 rev）
    standardize: str = ""  # 标准化
    technologist: str = ""  # 工艺
    projection: str = "第一角"  # 投影符号
    sheet_no: int = 1  # 第几张
    sheet_total: int = 1  # 共几张


def default_notes(
    rules: RuleSet | None = None,
    dims: DimsDocument | None = None,
) -> list[str]:
    """默认技术要求图注（主方案 §6.3 七条全集 + 细则 §1.4 金样图注）.

    dims 提供时追加 §6.2 CAM 友好标注的 DFM 行（深窄槽穿丝/型腔基准/
    薄壁警示；wall 取 dims 中 wall/t_wall 变量）。
    """
    rs = rules or default_ruleset()
    notes = [
        "1. 未注线性公差 GB/T 1804-m；未注形位公差 GB/T 1184-K。",
        "2. 内腔与耦合窗为关键尺寸，见 critical_chars.csv；内壁 Ra≤0.8，无刀痕毛刺翻边。",
        "3. 耦合窗/窄槽标注「线切割 WEDM」或最小内圆角 R≤0.5；薄筋按图。",
        f"4. 棱边倒钝 {rs.chamfer_inside}；去毛刺、清洗、无油。",
        "5. 表面处理：铝导电氧化或外漆+内酸洗（表处单边厚度 0.005–0.008mm，镀前留量）；"
        "铜镀银 5μm（高Q 5–8μm），镀后不得堵塞耦合结构。",
        "6. 螺纹注有效牙深+底孔(牙深+3~5P)、公差 6H。",
        "7. 尺寸与公差以 dims.json 为准，禁止按导入模型测量改图。",
        "8. 检验：关键特性 100% 镀前全尺寸检验（三坐标/影像）；重要件镀后复测内腔。",
        "9. 法兰贴合面平面度 ≤0.03；销孔 Ø2.5 H7；基准 A=法兰贴合面。",
    ]
    if dims is not None:
        wall = next(
            (v.value for v in dims.variables if v.name.lower() in ("wall", "t_wall")),
            None,
        )
        notes.extend(dfm_notes(wall=wall))
    return notes


def render_drawing(
    out_path: str | Path,
    dims: DimsDocument,
    *,
    config: DrawingConfig | None = None,
    rules: RuleSet | None = None,
    views: Sequence[dict] | None = None,
    closed_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
) -> Path:
    """生成 DXF 图纸.

    views: 可选 [{"name":"主视","points":[(x,y),...]}] 轮廓；
    closed_polylines: 直接闭合轮廓（2.5D 俯视等）。
    """
    try:
        import ezdxf  # type: ignore
        from ezdxf.enums import TextEntityAlignment  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("draw_engine 需要 ezdxf：pip install rfauto[fab]") from e

    rs = rules or default_ruleset()
    cfg = config or DrawingConfig(part_id=dims.part_id, rev=dims.rev, part_name=dims.part_id)
    if not cfg.notes:
        cfg.notes = default_notes(rs, dims)

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    _ensure_styles(doc)
    _layers(doc)

    W, H = cfg.sheet_mm
    # 图框
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "FRAME"})
    _title_block(msp, cfg, W, H)

    # 轮廓：多视图优先（core.views）；origin 抬高使 A-A 剖视/局部放大
    # （y=origin.y-60）落在图框内（原 origin.y=30 时剖视在 y=-30 出框）
    try:
        vmap = {v.name: v.value for v in dims.variables}
        views_geom = build_wr90_views(vmap, origin=(30.0, 70.0))
        for vg in views_geom:
            for layer, pts in vg.loops:
                if len(pts) >= 2:
                    msp.add_lwpolyline(
                        list(pts), close=True,
                        dxfattribs={"layer": layer if layer in ("OUT", "POCKET") else "VISIBLE"},
                    )
            for _layer, center, r in vg.circles:
                msp.add_circle(center, r, dxfattribs={"layer": "HOLE"})
            for text, tx, ty in vg.texts:
                msp.add_text(text, dxfattribs={"layer": "TEXT", "height": 3.5}).set_placement(
                    (tx, ty), align=TextEntityAlignment.TOP_LEFT
                )
        # 孔表文字
        try:
            holes = flange_hole_table()
            msp.add_text(
                f"法兰孔表 {len(holes)} 孔（详见 critical/标准）",
                dxfattribs={"layer": "TEXT", "height": 3.0},
            ).set_placement((20, 18.0), align=TextEntityAlignment.TOP_LEFT)
        except Exception:
            pass
    except Exception:
        if closed_polylines:
            y0 = H * 0.35
            x0 = 40.0
            for pts in closed_polylines:
                shifted = [(x0 + p[0], y0 + p[1]) for p in pts]
                msp.add_lwpolyline(shifted, close=True, dxfattribs={"layer": "VISIBLE"})
        if views:
            for view in views:
                pts = view.get("points") or []
                if len(pts) >= 2:
                    msp.add_lwpolyline(
                        list(pts), close=bool(view.get("closed", True)),
                        dxfattribs={"layer": "VISIBLE"},
                    )

    # 自动标注 rf_critical + assembly
    _auto_dimensions(msp, dims, rs, cfg)

    # 工艺表：特征旁注 WEDM/3轴铣（主方案 §6.2 CAM 友好标注）
    render_process_table(msp, dims)

    # 技术要求（y 起点抬高到 H-24：图注可达 ~14 行不与视图区相碰）
    y = H - 24.0
    for line in cfg.notes:
        msp.add_text(line, dxfattribs={"layer": "TEXT", "height": 3.5}).set_placement(
            (20, y), align=TextEntityAlignment.TOP_LEFT
        )
        y -= 6.0

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(out))
    return out


def _ensure_styles(doc) -> None:
    try:
        doc.styles.add("GB", font="simhei.ttf", bigfont="gbcbig.shx")
    except Exception:
        with contextlib.suppress(Exception):
            doc.styles.add("GB", font="txt")


def _layers(doc) -> None:
    specs = [
        ("VISIBLE", 7, 0.50),
        ("DIM", 2, 0.25),
        ("HIDDEN", 3, 0.25),
        ("CENTER", 1, 0.25),
        ("TEXT", 4, 0.25),
        ("FRAME", 7, 0.50),
        ("TITLE", 7, 0.50),
    ]
    for name, color, lw in specs:
        if name not in doc.layers:
            doc.layers.add(name, color=color)
        with contextlib.suppress(Exception):
            doc.layers.get(name).dxf.lineweight = int(lw * 100)


def _title_block(msp, cfg: DrawingConfig, W: float, H: float) -> None:
    """GB/T 10609.1 标题栏（细则 §2.1/§13.1 字段全集）.

    覆盖：图样代号/图样名称/单位名称/材料标记/比例/重量/共_张 第_张/
    阶段标记/年月日/设计/工艺/标准化/校对/审核/批准/更改区/投影符号。
    """
    from ezdxf.enums import TextEntityAlignment  # type: ignore

    w, h = cfg.title_block_w, cfg.title_block_h
    x0, y0 = W - 5 - w, 5
    msp.add_lwpolyline(
        [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)],
        close=True,
        dxfattribs={"layer": "TITLE"},
    )
    rows = [
        f"图样代号  {cfg.part_id}   图样名称  {cfg.part_name}",
        f"单位 {cfg.org}",
        f"材料标记 {cfg.material}   比例 {cfg.scale}   重量 {cfg.weight or '—'}"
        f"   阶段标记 {cfg.stage or cfg.rev}",
        f"共 {cfg.sheet_total} 张  第 {cfg.sheet_no} 张   日期 {cfg.date or '—'}   投影 {cfg.projection}",
        f"设计 {cfg.designer or '—'}   工艺 {cfg.technologist or '—'}   "
        f"标准化 {cfg.standardize or '—'}   校对 {cfg.checker or '—'}   审核/批准 {cfg.approver or '—'}",
        "更改标记/处数/分区/更改文件号/签名/年月日 —（未更改）",
    ]
    for i, text in enumerate(rows):
        msp.add_text(text, dxfattribs={"layer": "TITLE", "height": 2.8}).set_placement(
            (x0 + 2.5, y0 + h - 5 - i * 8.5),
            align=TextEntityAlignment.TOP_LEFT,
        )


def _auto_dimensions(msp, dims: DimsDocument, rs: RuleSet, cfg: DrawingConfig) -> None:
    """把变量写入图纸尺寸（参数驱动，非测量）.

    公差形态按细则 §3.1：偏差走 ezdxf ``set_tolerance``（叠排进 DIMSTYLE
    override，非纯文本拼接）；配合代号（H7/6H）与零公差走文本。
    """
    from ezdxf.enums import TextEntityAlignment  # type: ignore

    selected: list[VariableDim] = [v for v in dims.variables if v.role in ("rf_critical", "assembly")]
    if not selected:
        selected = dims.variables[:8]
    base_y = 28.0
    for i, v in enumerate(selected[:12]):
        tol = rs.tol_for(v.tol_class)
        text = _dim_text(v, tol)
        x = 25.0 + (i % 6) * 40.0
        y = base_y if i < 6 else base_y - 12.0
        try:
            dim = msp.add_linear_dim(
                base=(x, y),
                p1=(x, y - 8),
                p2=(x + 25, y - 8),
                dimstyle="EZDXF",
                override={"dimtxsty": "GB", "dimtxt": 3.0, "dimdec": 2},
            )
            if not _apply_tolerance(dim, tol):
                dim.set_text(text)
            dim.render()
        except Exception:
            # 尺寸失败不影响出图骨架
            msp.add_text(text, dxfattribs={"layer": "DIM", "height": 3.0}).set_placement(
                (x, y), align=TextEntityAlignment.TOP_LEFT
            )


def _apply_tolerance(dim, tol) -> bool:
    """细则 §3.1 set_tolerance 模式：上/下偏差写入 DIMSTYLE override.

    fit（H7/6H）与零偏差返回 False（由调用方走 set_text 文本形态）。
    返回 True 表示已写 dimtol/dimtp/dimtm（GB 叠排形态）。
    """
    if tol.fit:
        return False
    if tol.plus == 0 and tol.minus == 0:
        return False
    # ezdxf set_tolerance：upper=上偏差，lower=下偏差幅度（内部按负偏差渲染）
    dim.set_tolerance(upper=abs(tol.plus), lower=abs(tol.minus), hfactor=0.6, dec=2)
    return True


def _dim_text(v: VariableDim, tol) -> str:
    """关键尺寸后缀 (变量名)（主方案 §12：关键尺寸后缀 `(变量名)`，可回溯）."""
    label = v.drawing_label or v.name
    suffix = f"({v.name})" if v.drawing_label and v.drawing_label != v.name else ""
    if tol.fit:
        return f"{label} {v.value:g} {tol.fit}{suffix}"
    if tol.plus == 0 and tol.minus == 0:
        return f"{label} {v.value:g}{suffix}"
    if abs(tol.plus - tol.minus) < 1e-12:
        return f"{label} {v.value:g}±{tol.plus:g}{suffix}"
    return f"{label} {v.value:g} +{tol.plus:g}/-{tol.minus:g}{suffix}"


def render_process_table(msp, dims: DimsDocument, *, max_rows: int = 10) -> None:
    """工艺表：rf_critical 特征旁注工序（WEDM/3轴铣/钻铰/攻丝）.

    主方案 §6.2「特征旁注线切割 WEDM 或 3轴铣」的图形化落地；工序推断
    与 core.process_notes.process_tag_for / qif_cam 同口径。
    """
    from ezdxf.enums import TextEntityAlignment  # type: ignore

    rows = [v for v in dims.variables if v.role == "rf_critical"][:max_rows]
    if not rows:
        return
    x, y = 195.0, 165.0
    msp.add_text("工艺表（特征→工序）", dxfattribs={"layer": "TEXT", "height": 3.0}).set_placement(
        (x, y), align=TextEntityAlignment.TOP_LEFT
    )
    y -= 6.0
    msp.add_text("特征 | 值 | 公差类 | 工序", dxfattribs={"layer": "TEXT", "height": 2.2}).set_placement(
        (x, y), align=TextEntityAlignment.TOP_LEFT
    )
    y -= 4.5
    for v in rows:
        line = f"{v.drawing_label or v.name} | {v.value:g} | {v.tol_class} | {process_tag_for(v.name)}"
        msp.add_text(line, dxfattribs={"layer": "TEXT", "height": 2.2}).set_placement(
            (x, y), align=TextEntityAlignment.TOP_LEFT
        )
        y -= 4.5
        if y < 70.0:  # 标题栏上方留空
            break


def export_dxf_pdf(dxf_path: str | Path, pdf_path: str | Path | None = None) -> Path | None:
    """DXF→PDF（ezdxf drawing + matplotlib；缺 matplotlib 返回 None 不抛）."""
    dxf_path = Path(dxf_path)
    if pdf_path is None:
        pdf_path = dxf_path.with_suffix(".pdf")
    try:
        import matplotlib  # type: ignore

        matplotlib.use("Agg")
        import ezdxf  # type: ignore
        import matplotlib.pyplot as plt  # type: ignore
        from ezdxf.addons.drawing import Frontend, RenderContext  # type: ignore
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # type: ignore

        doc = ezdxf.readfile(str(dxf_path))
        msp = doc.modelspace()
        fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape inches
        ax = fig.add_axes([0, 0, 1, 1])
        backend = MatplotlibBackend(ax)
        Frontend(RenderContext(doc), backend).draw_layout(msp)
        fig.savefig(str(pdf_path), dpi=200, bbox_inches="tight")
        plt.close(fig)
        return Path(pdf_path) if Path(pdf_path).exists() else None
    except Exception:
        return None


class EzdxfDrawPort:
    name = "ezdxf"

    def render(self, dims, out_path, **kwargs):
        return render_drawing(out_path, dims, **kwargs)

    def render_pdf(self, dxf_path, pdf_path=None):
        return export_dxf_pdf(dxf_path, pdf_path)
