"""budget_funnel 渲染器——链路预算漏斗（批 4 图型④/决策②第 4 项，批 4 落地）。

动画语义：帧 k=第 k 级横条点亮（:func:`steps_reveal` 逐级组 opacity set，
nf_cascade 同款计时）——发射→接收逐级扣减，横条 rect 宽度随累计余量
递减（漏斗形态）。

数据源（单 ``budget_json``，loaders.load_budget_json 契约）：级表
``{"stages":[{"name"?,"value_db"},...]}``——与 cascade_json 同构，语义=
预算扣减（value_db 为逐级增量 dB，负值=损耗）。

**声明式派生（本图型唯一算术，非数据改写；独立复算锚在测试）**：

- **累计余量**：``cum(k) = Σ_{i=0..k} value_db_i``（dB 域算术和，与
  nf_cascade cumulative_gain_db 同口径）；
- **漏斗基准**：``ref = max(cum)``（发射端满预算基准）；``ref ≤ 0`` →
  AnimationDataError 显式报错（漏斗语义要求正预算基准，无预算可扣不画）；
- **横条宽度**：第 k 条 rect 宽=``max(0, box.xy(cum_k, 0, ref) − box.x0)``
  （x 域=(0, ref) 线性映射；cum_k<0 → 宽 0=漏斗见底，如实显示不造假；
  cum_k>ref 不可能因 ref=累计最大值）——宽度递减即余量递减。

文本（全部显式 x/y）：级名（数据直通或位置回退 ``stage{k}``，条内左端）
+本级增量 ``v={fmt_num(value_db)}dB``（数据直通，条内右对齐）+剩余余量
``M={fmt_num(cum)}dB``（声明式派生，条右端外 6px）。级色=内建调色板按
级序取色（style.colors 覆盖）；行高=box.h/N、条高=0.62×行高
（固定布局常量 BAR_H_FRAC）。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import (
    AnimationDataError,
    BudgetDoc,
    load_budget_json,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    fmt_num,
    nice_ticks,
    register_anim_renderer,
    steps_reveal,
    svg_text,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["BudgetFunnelRenderer", "cumulative_margin_db"]

_CHART_TYPE = "budget_funnel"

#: 条高占行高比例（固定布局常量；signal_flow BOX_H_FRAC 同款口径）
BAR_H_FRAC = 0.62


def cumulative_margin_db(values: list[float] | tuple[float, ...]) -> list[float]:
    """逐级增量 dB → 累计余量序列（dB 域算术和；声明式派生，测试锚）。"""
    out: list[float] = []
    acc = 0.0
    for v in values:
        acc += v
        out.append(acc)
    return out


@register_anim_renderer(_CHART_TYPE)
class BudgetFunnelRenderer(AnimRenderer):
    """链路预算漏斗渲染器（单 budget_json 源，横条递减逐级点亮）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）")
        if sources[0].kind != "budget_json":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 budget_json（收到 "
                f"{sources[0].kind!r}）——NF/增益级联归 nf_cascade，链路框图"
                "归 signal_flow")
        doc: BudgetDoc = load_budget_json(sources[0].path)
        return self._plan(spec, doc)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, doc: BudgetDoc) -> RenderPlan:
        n = doc.n_stages
        cum = cumulative_margin_db([s.value_db for s in doc.stages])
        ref = max(cum)
        if ref <= 0:
            raise AnimationDataError(
                f"{doc.source_path} 预算累计最大值 {ref!r} ≤ 0——budget_funnel"
                " 语义要求正预算基准（首级=发射功率/预算上限，正 dB）；无预算"
                "可扣不画空漏斗")
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (0.0, ref)
        x_ticks = nice_ticks(0.0, ref)
        dur = self.duration_for(spec, n)
        row_h = box.h / n
        bar_h = BAR_H_FRAC * row_h
        colors = spec.style.colors or PALETTE

        clip_def, begins = steps_reveal("anim_clip", box, n, dur=dur)
        groups: list[str] = []
        for k, stage in enumerate(doc.stages):
            name = stage.name if stage.name is not None else f"stage{k}"
            width = max(0.0, box.xy(cum[k], 0.0, ref) - box.x0)
            y_top = box.y0 + k * row_h + (row_h - bar_h) / 2.0
            color = colors[k % len(colors)]
            cy = y_top + bar_h / 2.0
            parts = [
                f'<rect x="{fmt_num(box.x0)}" y="{fmt_num(y_top)}" '
                f'width="{fmt_num(width)}" height="{fmt_num(bar_h)}" '
                f'fill="{color}" fill-opacity="0.85" '
                f'stroke="#333333" stroke-width="1"/>',
                svg_text(box.x0 + 6.0, cy + spec.style.font_size * 0.35,
                         name, size=spec.style.font_size, fill="#222222",
                         weight="bold"),
                svg_text(box.x0 + width - 6.0,
                         cy + spec.style.font_size * 0.35,
                         f"v={fmt_num(stage.value_db)}dB",
                         size=spec.style.font_size - 1, anchor="end",
                         fill="#ffffff"),
                # 剩余余量标注：条下方右对齐（条右端随宽度递减左移——
                # 标注恒在绘图区内，不被 clip 裁剪不出画布）
                svg_text(box.x0 + width - 6.0,
                         y_top + bar_h + spec.style.font_size,
                         f"M={fmt_num(cum[k])}dB",
                         size=spec.style.font_size - 1, anchor="end",
                         fill="#555555"),
            ]
            groups.append(f'<g opacity="0">'
                          f'<set attributeName="opacity" to="1" '
                          f'begin="{begins[k]}"/>'
                          f'{"".join(parts)}</g>')
        chrome = [
            cartesian_axes(box, x_ticks, [], xlabel="cumulative margin (dB)",
                           ylabel="", font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(0.0, 1.0)),
        ]
        body = ("".join(chrome) + clip_def
                + f'<g clip-path="url(#anim_clip)">{"".join(groups)}</g>')
        summary = {"kind": "budget_json", "path": doc.source_path,
                   "n_stages": n,
                   "stage_names": [s.name if s.name is not None
                                   else f"stage{i}"
                                   for i, s in enumerate(doc.stages)],
                   "margin_total_db": fmt_num(cum[-1]),
                   "budget_ref_db": fmt_num(ref)}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)
