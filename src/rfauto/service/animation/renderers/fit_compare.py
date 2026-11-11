"""fit_compare 渲染器——实测 vs 仿真 vs 代理预测三线同轴逐帧对齐（图型④）。

动画语义：帧 k=三线同帧揭示到第 k 个频点（共享 discrete clip，x=频率单调
——"对齐"语义：同帧看三线贴合度）。

数据源（2..3 个源，按序=实测/仿真/代理缺省语义）：

- sparams_csv/snip：x=freq_hz、y=|S|（style.y_mode，缺省 db）；
- anchor_json：``{"series":{"x":[...],"y":[...]}}``（代理预测导出惯例；
  y 原值直用，零变换）。

对齐守卫：各源 x 网格必须同栅（require_common_grid，rel 1e-9/abs 1e-6 Hz
——不满足→ AnimationDataError 带同栅重采样指引，渲染器不做隐式插值；
#287 家族口径）。sparams/snip 的 x 须单调不减（逐帧揭示前提）；anchor
series 渲染前按 x 升序排序（确定性显示排序，零数值改写）。

图例=style.labels 或缺省 ["measured","simulated","surrogate"] 按源序。
"""

from __future__ import annotations

import itertools
import math

from rfauto.service.animation.loaders import (
    AnimationDataError,
    load_anchor_json,
    load_snip,
    load_sparams_csv,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
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

__all__ = ["FitCompareRenderer"]

_CHART_TYPE = "fit_compare"

#: 缺省系列语义（按源序；style.labels 覆盖）
DEFAULT_LABELS = ("measured", "simulated", "surrogate")


@register_anim_renderer(_CHART_TYPE)
class FitCompareRenderer(AnimRenderer):
    """实测/仿真/代理三线同轴对齐渲染器（2..3 源）。"""

    chart_type = _CHART_TYPE

    # ── 数据面 ────────────────────────────────────────────────────────────
    def _series(self, src: SourceSpec, y_mode: str) -> tuple[
            list[float], list[float], dict]:
        """源声明 → (x 列表[升序], y 列表, 数据摘要 dict)。"""
        if src.kind in ("sparams_csv", "snip"):
            columns = src.columns or ["S11"]
            if len(columns) != 1:
                raise AnimationSpecError(
                    f"{_CHART_TYPE} 每源一条线：columns 须恰一列（收到 "
                    f"{sorted(set(columns))}）——多线需求请用多源")
            if src.kind == "sparams_csv":
                table = load_sparams_csv(src.path, columns=columns)
            else:
                table = load_snip(src.path, columns=columns, ports=src.ports)
            x = list(table.freq_hz)
            if any(b < a for a, b in itertools.pairwise(x)):
                raise AnimationDataError(
                    f"{table.source_path} freq_hz 非单调不减——逐帧揭示前提"
                    "破坏；请预排序数据源（渲染器不隐式重排引擎产物）")
            col = table.columns[0]
            y = magnitude_to_y(table.series[col], y_mode,
                               where=f"{table.source_path}:{col}")
            return x, y, {"kind": "sparams_table", "path": table.source_path,
                          "n_points": table.n_points, "columns": [col]}
        if src.kind == "anchor_json":
            obj = load_anchor_json(src.path)
            raw = obj.get("series")
            if (not isinstance(raw, dict) or "x" not in raw or "y" not in raw
                    or not isinstance(raw["x"], list)
                    or not isinstance(raw["y"], list)
                    or len(raw["x"]) != len(raw["y"]) or not raw["x"]):
                raise AnimationDataError(
                    f"{src.path} 缺合法 series——anchor_json 的 fit_compare 契约"
                    "=``{'series':{'x':[...],'y':[...]}}``（等长非空数值数组）")
            pairs = sorted(zip(raw["x"], raw["y"], strict=True),
                           key=lambda p: float(p[0]))
            x: list[float] = []
            y: list[float] = []
            for k, (xv, yv) in enumerate(pairs):
                fx, fy = float(xv), float(yv)
                if not (math.isfinite(fx) and math.isfinite(fy)):
                    raise AnimationDataError(
                        f"{src.path} series[{k}] 非有限数值——残缺数据显式拒绝")
                x.append(fx)
                y.append(fy)
            return x, y, {"kind": "anchor_json", "path": src.path,
                          "n_points": len(x)}
        raise AnimationSpecError(
            f"{_CHART_TYPE} 数据源 kind 须为 sparams_csv|snip|anchor_json"
            f"（收到 {src.kind!r}）——trials 归 param_race")

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if not 2 <= len(sources) <= 3:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 须 2..3 个源（实测/仿真[/代理]，收到 "
                f"{len(sources)} 个）")
        labels = spec.style.labels or list(DEFAULT_LABELS[:len(sources)])
        if spec.style.labels is not None and len(spec.style.labels) != len(sources):
            raise AnimationSpecError(
                f"style.labels 数量 {len(spec.style.labels)} != 源数量 "
                f"{len(sources)}")
        y_mode = spec.style.y_mode or "db"
        series = [self._series(s, y_mode) for s in sources]
        grid = require_common_grid([tuple(x) for x, _, _ in series],
                                   f"{_CHART_TYPE} 对齐守卫")
        n = len(grid)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        y_all = [v for _, ys, _ in series for v in ys]
        y_dom = (min(y_all), max(y_all))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        dur = self.duration_for(spec, n)
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        edges = ([box.x0 + box.w] if n == 1
                 else [(px[k] + px[k + 1]) / 2.0 for k in range(n - 1)]
                 + [box.x0 + box.w])
        clip_def = discrete_clip_reveal("anim_clip", box, edges, dur=dur)
        chrome = [
            cartesian_axes(box, x_ticks, y_ticks, xlabel="freq_hz",
                           ylabel="|S| (dB)" if y_mode == "db" else "|S|",
                           font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(min(y_ticks), max(y_ticks))),
            legend_row([(labels[k], (spec.style.colors or PALETTE)
                         [k % len(spec.style.colors or PALETTE)])
                        for k in range(len(sources))],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        drawn: list[str] = []
        for k, (_, y, _) in enumerate(series):
            color = (spec.style.colors or PALETTE)[k % len(spec.style.colors
                                                           or PALETTE)]
            pixel_pts = [(px[i], box.xy(y[i], y_dom[0], y_dom[1],
                                        horizontal=False)) for i in range(n)]
            drawn.append(polyline(pixel_pts, color, spec.style.stroke_width))
        body = ("".join(chrome) + clip_def
                + f'<g clip-path="url(#anim_clip)">{"".join(drawn)}</g>')
        summaries = tuple(dict(s[2]) for s in series)
        return RenderPlan(frame_count=n, body=body, data_sources=summaries,
                          duration_s=dur)
