"""stackup_growth 渲染器——PCB 叠层/布线生长（批 4 图型⑬，决策②第 14 项）。

动画语义（生长序列=逐层自下而上 + 布线逐段 reveal）：帧槽序列=按层序
（数据声明序=自下而上语义，层 0=最底层/基板先出现——与 structure_explode
"层序=数据声明序不重排"先例一致）逐层推进，每层先整组 appear（层带+层
名标签），随后该层布线中心线 polyline **逐段 reveal**（每段 1 帧槽），
再进入下一层。frame_count=Σ_layers (1 + max(0, n_prims−1))。

**布局规则（声明式几何，非数据改写；独立复算锚在测试）**：

- 数据源=单 ``layout_json``（loaders.load_layout_json 契约复用；侦察
  diagram_stackup_service 层卡字段 {index,name,kind,thickness_mm,material,er}
  与 layout_json 不一致——按任务书裁定 layout_json 为准）；
- uniform scale 映射：全部图元 (x,y,w,h) 并集 → 数据包围盒 →
  ``s = min(box.w/Δx, box.h/Δy)``（uniform scale 保纵横比，居中：
  ``ox = box.x0 + (box.w−Δx·s)/2``、``oy = box.y0 + (box.h−Δy·s)/2``）；
- **y 轴翻转（叠层物理语义）**：数据 y=距底板高度（向上为正）——像素
  ``py_top = oy + (y_max − y − h)·s``（数据上=屏上；structure_explode 无
  翻转因拆解语义无上下约定，本图型按叠层惯例翻转，声明式）；
- **层带 rect 高度∝厚度**：uniform scale 下像素高=``h·s``——h（数据厚度
  语义）与像素高严格成正比，比例常数=同一 s（本条即"高度∝厚度"布局
  规则，无逐层独立缩放）；
- **布线层 polyline 逐段 reveal**：图元数 ≥2 的层取图元中心连线（数据
  声明序=走线段序）为中心线，按相邻中心拆分为单段 ``<line>`` 元素逐帧
  点亮（``<set opacity>``，与 signal_flow 同款计时）；单图元层只有层带
  appear（无段）。拆段而非 x 单调 clip——不对非单调走线做方向假设；
- 图元 shape 暂仅支持 ``"rect"``、w/h>0（同 structure_explode 守卫口径，
  未知形状/零尺寸 AnimationDataError 显式拒绝）；全空层（无任何图元）
  AnimationDataError 显式报错（不画空图）。

文本：层名标签（数据直通）随层带同帧 appear，显式 x/y（标签 x=该层首
图元中心、y=首图元上缘−4px）。层色=内建调色板按层序取色（style.colors
覆盖）；走线段颜色固定 TRACE_COLOR（与层带色区分中心线）。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import (
    AnimationDataError,
    LayoutDoc,
    load_layout_json,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    esc,
    fmt_num,
    register_anim_renderer,
    svg_text,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["StackupGrowthRenderer", "growth_schedule", "stackup_layout_px"]

_CHART_TYPE = "stackup_growth"

#: 图元填充不透明度/描边（固定字面量——布局确定性；同 structure_explode）
FILL_OPACITY = "0.85"
STROKE = "#333333"

#: 中心线段颜色（固定字面量；布线层走线生长视觉）
TRACE_COLOR = "#222222"


def stackup_layout_px(
        doc: LayoutDoc,
        box: PlotBox) -> tuple[float, float, float, float]:
    """数据坐标 → 像素映射参数 (scale, ox, oy, y_max)（uniform scale 居中）。

    包围盒=全部图元 (x,y,w,h) 并集（shape=rect 且 w/h>0 在此守卫）；
    全空层/零尺寸显式报错（同 structure_explode 口径）。像素坐标：
    ``px = ox + x·s``、``py_top = oy + (y_max − y − h)·s``（y 翻转——
    数据 y=距底板高度向上）。返回的 s 即"层带 rect 高度∝厚度"的唯
    比例常数（像素高=h·s）。
    """
    xs: list[float] = []
    ys: list[float] = []
    for layer in doc.layers:
        for prim in layer.primitives:
            if prim.shape != "rect":
                raise AnimationDataError(
                    f"{prim.source_path} 图元 shape={prim.shape!r} 暂仅"
                    "支持 'rect'——未知形状显式拒绝（不猜不兜底）")
            if prim.w <= 0 or prim.h <= 0:
                raise AnimationDataError(
                    f"{prim.source_path} 图元 w/h 须为正（收到 "
                    f"w={prim.w!r}, h={prim.h!r}）——零尺寸图元无法绘制")
            xs.extend((prim.x, prim.x + prim.w))
            ys.extend((prim.y, prim.y + prim.h))
    if not xs:
        raise AnimationDataError(
            f"{doc.source_path} 全部层 primitives 为空——无叠层可画，"
            "不画空图")
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    s = min(box.w / (x_max - x_min), box.h / (y_max - y_min))
    ox = box.x0 + (box.w - (x_max - x_min) * s) / 2.0
    oy = box.y0 + (box.h - (y_max - y_min) * s) / 2.0
    return s, ox, oy, y_max


def growth_schedule(n_prims_per_layer: list[int]) -> list[tuple[int, int]]:
    """帧槽调度表（声明式）：每层 → (层带槽号, 段起始槽号)。

    帧槽序=层序推进；层 k 层带占 1 槽，其布线段占后续 max(0, n−1) 槽。
    返回逐层 (band_slot, first_seg_slot)；总槽数=Σ(1+max(0,n−1))，
    frame_count 与 begin 计时（slot×dur/total）均由本表派生（测试锚）。
    """
    if not n_prims_per_layer:
        raise ValueError("n_prims_per_layer 至少 1 层")
    schedule: list[tuple[int, int]] = []
    slot = 0
    for n in n_prims_per_layer:
        schedule.append((slot, slot + 1))
        slot += 1 + max(0, n - 1)
    return schedule


@register_anim_renderer(_CHART_TYPE)
class StackupGrowthRenderer(AnimRenderer):
    """叠层/布线生长渲染器（单 layout_json 源，自下而上逐层逐段生长）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）")
        if sources[0].kind != "layout_json":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 layout_json（收到 "
                f"{sources[0].kind!r}）——拆解动画归 structure_explode，"
                "场帧归 field_heatmap")
        doc: LayoutDoc = load_layout_json(sources[0].path)
        return self._plan(spec, doc)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, doc: LayoutDoc) -> RenderPlan:
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        s, ox, oy, y_max = stackup_layout_px(doc, box)
        n_prims = [len(layer.primitives) for layer in doc.layers]
        schedule = growth_schedule(n_prims)
        total = sum(1 + max(0, n - 1) for n in n_prims)
        dur = self.duration_for(spec, total)
        colors = spec.style.colors or PALETTE

        def py_top(y: float, h: float) -> float:
            """y 翻转映射：数据 y（距底板高度）→ 像素顶缘。"""
            return oy + (y_max - y - h) * s

        out: list[str] = []
        for k, layer in enumerate(doc.layers):
            band_slot, seg_slot = schedule[k]
            band_begin_s = f"{band_slot * dur / total:.6f}s"
            color = colors[k % len(colors)]
            parts: list[str] = []
            lx = box.x0 + box.w / 2.0
            ly = box.y0 + box.h / 2.0
            centers: list[tuple[float, float]] = []
            for prim in layer.primitives:
                px = ox + prim.x * s
                pt = py_top(prim.y, prim.h)
                pw = prim.w * s
                ph = prim.h * s
                parts.append(f'<rect x="{fmt_num(px)}" y="{fmt_num(pt)}" '
                             f'width="{fmt_num(pw)}" height="{fmt_num(ph)}" '
                             f'fill="{esc(color)}" '
                             f'fill-opacity="{FILL_OPACITY}" '
                             f'stroke="{STROKE}" stroke-width="1"/>')
                centers.append((px + pw / 2.0, pt + ph / 2.0))
            if layer.primitives:
                first = layer.primitives[0]
                lx = ox + first.x * s + first.w * s / 2.0
                ly = py_top(first.y, first.h) - 4.0
            parts.append(svg_text(lx, ly, layer.name,
                                  size=spec.style.font_size,
                                  anchor="middle", fill="#222222",
                                  weight="bold"))
            group = (f'<g opacity="0"><set attributeName="opacity" to="1" '
                     f'begin="{band_begin_s}"/>{"".join(parts)}</g>')
            # 布线段（层带组外兄弟节点——段有自己的 opacity 计时；
            # 段颜色固定 TRACE_COLOR 与层带色区分走线中心线）
            for j in range(len(centers) - 1):
                seg_begin_s = f"{(seg_slot + j) * dur / total:.6f}s"
                (x1, y1), (x2, y2) = centers[j], centers[j + 1]
                group += (f'<line x1="{fmt_num(x1)}" y1="{fmt_num(y1)}" '
                          f'x2="{fmt_num(x2)}" y2="{fmt_num(y2)}" '
                          f'stroke="{TRACE_COLOR}" '
                          f'stroke-width="{fmt_num(spec.style.stroke_width)}" '
                          f'stroke-linecap="round" opacity="0">'
                          f'<set attributeName="opacity" to="1" '
                          f'begin="{seg_begin_s}"/></line>')
            out.append(group)
        body = "".join(out)
        summary = {"kind": "layout_json", "path": doc.source_path,
                   "n_layers": doc.n_layers,
                   "layer_names": [layer.name for layer in doc.layers],
                   "n_trace_segments": sum(max(0, n - 1) for n in n_prims),
                   "frame_count": total,
                   "height_proportional": "h*s (uniform scale)"}
        return RenderPlan(frame_count=total, body=body,
                          data_sources=(summary,), duration_s=dur)
