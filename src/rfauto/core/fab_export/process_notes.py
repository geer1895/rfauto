"""工艺标注辅助：WEDM/铣 标签、镀层厚度提示、螺纹注法（L0 纯函数）.

主方案 §6.2（iris/深腔 CAM 友好标注）六项中代码可表达的：
穿丝/预钻孔、最小 R 或尖角、型腔基准相对标注、薄壁警示、筋/壁厚平行度——
由 :func:`dfm_notes` 产出图注行；「特征旁注 WEDM/3轴铣」由
adapters.fab_export.ezdxf_draw.render_process_table 上图。
"""

from __future__ import annotations

from .standards import DEFAULT_PROCESS_TAGS, FINISH_ONE_SIDE_MM, FIT_BANDS_MM


def process_tag_for(feature_name: str) -> str:
    low = feature_name.lower()
    if any(k in low for k in ("iris", "window", "coupl", "窄", "槽")):
        return DEFAULT_PROCESS_TAGS["iris"]
    if any(k in low for k in ("thread", "m2", "m3", "螺纹")):
        return DEFAULT_PROCESS_TAGS["thread"]
    return DEFAULT_PROCESS_TAGS["pocket"]


def thread_note(spec: str = "M3x0.5", effective_depth: float = 3.0) -> str:
    pitch = 0.5 if "M3" in spec else 0.4
    drill_depth = effective_depth + 3 * pitch
    return f"{spec}-6H 有效牙深{effective_depth:g} 底孔深≥{drill_depth:g}"


def finish_note(aluminum: bool = True, plating_um: float = 5.0) -> str:
    if aluminum:
        return "铝：导电氧化（或外灰色漆+内酸洗）；单边厚度参阳极 0.005–0.008mm"
    return f"铜/银：镀银 {plating_um:g}μm，镀后不得堵塞 iris；单边增长约镀层厚度"


def fit_note(kind: str = "location") -> str:
    lo, hi = FIT_BANDS_MM.get(kind, (0.0, 0.0))
    return f"配合({kind}) {lo:+g}/{hi:+g}"


def finish_allowance(kind: str = "anodize") -> str:
    lo, hi = FINISH_ONE_SIDE_MM.get(kind, (0.0, 0.0))
    return f"表处单边 {kind}: {lo:g}–{hi:g} mm（镀前留量）"


def dfm_notes(
    *,
    wall: float | None = None,
    thin_wall_mm: float = 1.0,
    wire_thread_hole_dia: float = 0.4,
) -> list[str]:
    """深腔/窄槽 DFM 图注行（主方案 §6.2 CAM 友好标注的可文本项）.

    - 深窄槽：可穿丝/预钻孔（孔径建议值随行给出）
    - 最小内圆角：EDM 允许 R 或「尖角」
    - 型腔基准：位置尺寸相对型腔基准 A/B/C，禁止只标外轮廓
    - 薄壁警示：wall 低于阈值时提示装夹/切削力专项评估与筋位平行度
    """
    notes = [
        "深窄槽/耦合窗优先慢走丝 WEDM：可穿丝（预钻孔约 Φ0.3–0.5，"
        f"建议 Φ{wire_thread_hole_dia:g}，位置由工艺定）；最小内圆角按 EDM 允许 R 或注明「尖角」。",
        "型腔位置尺寸相对型腔基准 A/B/C 标注，禁止只标外轮廓。",
    ]
    if wall is not None and 0.0 < wall < thin_wall_mm:
        notes.append(
            f"薄壁警示：壁厚 {wall:g}mm < {thin_wall_mm:g}mm——装夹/切削力需专项评估；筋位平行度 ≤0.02。"
        )
    else:
        notes.append("壁厚与筋位按图；平行度未注按 GB/T 1184-K。")
    return notes
