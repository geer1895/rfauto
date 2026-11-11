"""before_after 渲染器——改参前后响应同轴双色对比逐帧揭示（批 2 图型⑥）。

动画语义（spec docstring 决策②清单第 6 项）：帧 k=两条曲线同帧揭示到第
k 个频点（共享 discrete clip——"前后对比"语义：同帧看改参前后贴合/偏移）。

形态取舍（任务书"分屏/同轴两形态选一"）：**同轴**实现——双线同坐标系
（双色=style.colors[0:2] 或内建调色板前两色；图例=style.labels 或缺省
``before``/``after``），分屏形态不在此实现。

数据源（恰 2 个，kind 限 sparams_csv|snip）：

- 每源一条线：``columns`` 须恰一列（缺省 ``["S11"]``），且两源列名必须
  相同（"改参前后"对比语义=同一 S 参数量——不同列名显式报错不猜）；
- x 网格必须同栅（require_common_grid，rel 1e-9/abs 1e-6 Hz——不满足→
  AnimationDataError 带同栅重采样指引，渲染器不做隐式插值）；
- y=magnitude_to_y（style.y_mode，缺省 db=20*log10|S|；|S|=0 in db 显式
  报错）——确定性显示变换，零语义改写。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import (
    SparamsTable,
    load_snip,
    load_sparams_csv,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    clip_edges_midpoints,
    discrete_clip_reveal,
    legend_row,
    magnitude_to_y,
    nice_ticks,
    polyline,
    register_anim_renderer,
    require_common_grid,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    SourceSpec,
)

__all__ = ["BeforeAfterRenderer"]

_CHART_TYPE = "before_after"

#: 缺省系列语义（style.labels 覆盖）
DEFAULT_LABELS = ("before", "after")

_YLABEL = {"db": "|S| (dB)", "linear": "|S|"}


@register_anim_renderer(_CHART_TYPE)
class BeforeAfterRenderer(AnimRenderer):
    """改参前后同轴双色对比渲染器（恰 2 个 sparams 源，同列同栅）。"""

    chart_type = _CHART_TYPE

    # ── 数据面 ────────────────────────────────────────────────────────────
    def _load_source(self, src: SourceSpec, y_mode: str) -> tuple[
            SparamsTable, list[float], dict]:
        """源声明 → (表, y 值序列, 数据摘要)（每源恰一列在本面守卫）。"""
        if src.kind not in ("sparams_csv", "snip"):
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 sparams_csv|snip（收到 "
                f"{src.kind!r}）——trials 归 param_race，anchor_json 归 "
                "fit_compare，field_dump/layout_json 归各自图型")
        columns = src.columns or ["S11"]
        if len(set(columns)) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 每源一条线：columns 须恰一列（收到 "
                f"{sorted(set(columns))}）——多线需求请拆多 spec")
        if src.kind == "sparams_csv":
            table = load_sparams_csv(src.path, columns=columns)
        else:
            table = load_snip(src.path, columns=columns, ports=src.ports)
        col = table.columns[0]
        y = magnitude_to_y(table.series[col], y_mode,
                           where=f"{table.source_path}:{col}")
        return table, y, {"kind": "sparams_table", "path": table.source_path,
                          "n_points": table.n_points, "columns": [col]}

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 2:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 须恰 2 个源（before/after，收到 "
                f"{len(sources)} 个）")
        labels = list(DEFAULT_LABELS)
        if spec.style.labels is not None:
            if len(spec.style.labels) != 2:
                raise AnimationSpecError(
                    f"style.labels 数量 {len(spec.style.labels)} != 源数量 2")
            labels = list(spec.style.labels)
        y_mode = spec.style.y_mode or "db"
        loaded = [self._load_source(s, y_mode) for s in sources]
        col_names = [t.columns[0] for t, _, _ in loaded]
        if col_names[0] != col_names[1]:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 两源 S 参数列须同名（前后对比=同一量；收到 "
                f"{col_names}）——请统一 spec.source.columns")
        grid = require_common_grid([t.freq_hz for t, _, _ in loaded],
                                   f"{_CHART_TYPE} 同栅守卫")
        n = len(grid)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        y_all = [v for _, ys, _ in loaded for v in ys]
        y_dom = (min(y_all), max(y_all))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        dur = self.duration_for(spec, n)
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        edges = clip_edges_midpoints(px, box)
        clip_def = discrete_clip_reveal("anim_clip", box, edges, dur=dur)
        chrome = [
            cartesian_axes(box, x_ticks, y_ticks, xlabel="freq_hz",
                           ylabel=_YLABEL[y_mode],
                           font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(min(y_ticks),
                                                     max(y_ticks))),
            legend_row([(labels[k], self._color(spec, k)) for k in range(2)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        drawn: list[str] = []
        for k, (_, ys, _) in enumerate(loaded):
            pts = [(px[i], box.xy(ys[i], y_dom[0], y_dom[1], horizontal=False))
                   for i in range(n)]
            drawn.append(polyline(pts, self._color(spec, k),
                                  spec.style.stroke_width))
        body = ("".join(chrome) + clip_def
                + f'<g clip-path="url(#anim_clip)">{"".join(drawn)}</g>')
        return RenderPlan(frame_count=n, body=body,
                          data_sources=tuple(dict(s[2]) for s in loaded),
                          duration_s=dur)

    @staticmethod
    def _color(spec: AnimationSpec, idx: int) -> str:
        colors = spec.style.colors or PALETTE
        return colors[idx % len(colors)]
