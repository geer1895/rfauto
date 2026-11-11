"""structure_explode 渲染器——器件分层拆解逐层平移动画（批 2 图型⑦）。

动画语义（spec docstring 决策②清单第 7 项）：逐层拆开——层 k（0 基）的
``<g>`` 组在 ``begin=k×dur/N`` 起经 **SMIL animateTransform translate 线性
插值**（from="0 0" → to="0 {−k·G}"，dur/N 时长，fill=freeze）平移到拆解位
；层 0 不动（偏移零，免发 no-op animate）。帧语义：帧 k=第 k 层开始拆出
（frame_count=层数 N）。

拆解偏移（任务书"声明式 offset 或按层序自动等距"二选一）：

- **自动等距**（本实现）：第 k 层竖直向上偏移 ``k×G`` px——**G=几何布局量
  非数据改写**（声明式公式）：G=style.explode_gap（显式）或缺省
  ``box.h/(3×N)``；纵向总余量=(N−1)×G 在绘图区顶部预留，数据域映射按扣除
  余量后的可用区等比缩放（uniform scale 保持纵横比，居中）；
- 声明式 offset 留待后续按需增键（spec 只增不改纪律）。

数据源（单 source kind=``layout_json``，loaders.load_layout_json 契约）：
``{"layers":[{"name":...,"primitives":[{"shape","x","y","w","h"},...]}]}``。

绘制面（几何布局声明）：

- 全部图元（跨层）的 (x,y,w,h) 并集 → 数据包围盒 → uniform scale 映射到
  绘图区（层序=数据声明序，不重排）；
- 图元 shape 暂仅支持 ``"rect"``（其他值 AnimationDataError 显式拒绝，
  不猜不兜底）；w/h≤0 显式拒绝；层色=内建调色板按层序取色（style.colors
  覆盖），fill-opacity 固定 0.85；
- 层名标签随组平移（组内文本，显式 x/y；空层标签落绘图区中心）；无数据
  轴（坐标值零参与刻度）。同 spec 双跑逐字节同。
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

__all__ = ["StructureExplodeRenderer"]

_CHART_TYPE = "structure_explode"

#: 图元填充不透明度/描边（固定字面量——布局确定性）
FILL_OPACITY = "0.85"
STROKE = "#333333"


@register_anim_renderer(_CHART_TYPE)
class StructureExplodeRenderer(AnimRenderer):
    """器件分层拆解渲染器（单 layout_json 源，逐层 animateTransform 平移）。"""

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
                f"{sources[0].kind!r}）——场帧归 field_heatmap，S 参数源归 "
                "sparam_evolution/before_after/vswr_history")
        doc: LayoutDoc = load_layout_json(sources[0].path)
        return self._plan(spec, doc)

    # ── 几何面 ────────────────────────────────────────────────────────────
    @staticmethod
    def _gap(spec: AnimationSpec, box: PlotBox, n_layers: int) -> float:
        """逐层间距 G px（声明式公式：style.explode_gap 优先，缺省 box.h/(3N)）。"""
        if spec.style.explode_gap is not None:
            return float(spec.style.explode_gap)
        return box.h / (3.0 * n_layers)

    def _layout_px(self, doc: LayoutDoc, box: PlotBox,
                   headroom: float) -> tuple[float, float, float]:
        """数据坐标 → 像素映射参数 (scale, ox, oy)（uniform scale 居中）。

        可用区=绘图区扣除顶部拆解余量 headroom；包围盒=全部图元 (x,y,w,h)
        并集（w/h>0 在此守卫，全空层/余量超绘图区显式报错）。
        """
        xs: list[float] = []
        ys: list[float] = []
        for layer in doc.layers:
            for prim in layer.primitives:
                if prim.shape != "rect":
                    raise AnimationDataError(
                        f"{prim.source_path} 图元 shape={prim.shape!r} 暂仅"
                        "支持 'rect'——未知形状显式拒绝（不猜不兜底；扩展 "
                        "shape 请走 loaders/renderers 增量）")
                if prim.w <= 0 or prim.h <= 0:
                    raise AnimationDataError(
                        f"{prim.source_path} 图元 w/h 须为正（收到 "
                        f"w={prim.w!r}, h={prim.h!r}）——零尺寸图元无法绘制")
                xs.extend((prim.x, prim.x + prim.w))
                ys.extend((prim.y, prim.y + prim.h))
        if not xs:
            raise AnimationDataError(
                f"{doc.source_path} 全部层 primitives 为空——无图元可画，"
                "不画空图")
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        avail_w = box.w
        avail_h = box.h - headroom
        if avail_h <= 0:
            raise AnimationDataError(
                f"{_CHART_TYPE} 拆解余量 {(doc.n_layers - 1)}×G 超出绘图区"
                f"（headroom={headroom:.6g}px > box.h={box.h:.6g}px）——"
                "请调小 style.explode_gap 或减少层数")
        s = min(avail_w / (x_max - x_min), avail_h / (y_max - y_min))
        ox = box.x0 + (avail_w - (x_max - x_min) * s) / 2.0
        oy = box.y0 + headroom + (avail_h - (y_max - y_min) * s) / 2.0
        return s, ox, oy

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, doc: LayoutDoc) -> RenderPlan:
        n = doc.n_layers
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        gap = self._gap(spec, box, n)
        headroom = gap * (n - 1)
        s, ox, oy = self._layout_px(doc, box, headroom)
        dur = self.duration_for(spec, n)

        out: list[str] = []
        for k, layer in enumerate(doc.layers):
            dy = -gap * k
            color = (spec.style.colors or PALETTE)[k % len(spec.style.colors
                                                           or PALETTE)]
            parts: list[str] = []
            lx = box.x0 + box.w / 2.0
            ly = box.y0 + box.h / 2.0
            for prim in layer.primitives:
                px = ox + prim.x * s
                py = oy + prim.y * s
                pw = prim.w * s
                parts.append(f'<rect x="{fmt_num(px)}" y="{fmt_num(py)}" '
                             f'width="{fmt_num(pw)}" '
                             f'height="{fmt_num(prim.h * s)}" '
                             f'fill="{esc(color)}" '
                             f'fill-opacity="{FILL_OPACITY}" '
                             f'stroke="{STROKE}" stroke-width="1"/>')
                lx = px + pw / 2.0
                ly = py - 4.0
            parts.append(svg_text(lx, ly, layer.name,
                                  size=spec.style.font_size,
                                  anchor="middle", fill="#222222",
                                  weight="bold"))
            group = "".join(parts)
            if k == 0:
                out.append(f"<g>{group}</g>")
                continue
            out.append(
                "<g>"
                '<animateTransform attributeName="transform" '
                'attributeType="XML" type="translate" from="0 0" '
                f'to="0 {fmt_num(dy)}" begin="{k * dur / n:.6f}s" '
                f'dur="{dur / n:.6f}s" fill="freeze" calcMode="linear"/>'
                f"{group}</g>")
        body = "".join(out)
        summary = {"kind": "layout_json", "path": doc.source_path,
                   "n_layers": n,
                   "layer_names": [layer.name for layer in doc.layers],
                   "explode_gap_px": fmt_num(gap),
                   "explode_mode": ("style" if spec.style.explode_gap
                                    is not None else "auto")}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)
