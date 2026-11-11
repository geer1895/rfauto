"""param_race 渲染器——调参迭代赛跑（T-Q3 批 1 图型③）。

动画语义：帧 k=所有 runner 同帧揭示到第 k 次迭代（共享 discrete clip，
x=迭代序号 0..n−1 等距——"赛跑"语义：同帧看各家进度）。

数值口径（确定性显示变换，零语义改写）：

- y=**best-so-far**（逐点累计 min(cost)，收敛曲线标准口径——docstring 声
  明的确定性变换；原始 cost 逐点序列不变换不外泄）；
- x=迭代序号（trial_number 升序位置，非 trial 数值本身——轴标签
  ``iteration``，trial_number 进数据摘要）；
- 数据源=trials（rfauto run 目录 ``trials/trial_*.json`` / 单 trial /
  JSON 数组，cost 必备——loaders 契约）。

图例=runner 名（style.labels 覆盖，缺省=源路径末段名）。
"""

from __future__ import annotations

from pathlib import Path

from rfauto.service.animation.loaders import TrialRecord, load_trials
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    discrete_clip_reveal,
    legend_row,
    nice_ticks,
    polyline,
    register_anim_renderer,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["ParamRaceRenderer"]

_CHART_TYPE = "param_race"


@register_anim_renderer(_CHART_TYPE)
class ParamRaceRenderer(AnimRenderer):
    """多参数组优化收敛赛跑渲染器（≥1 个 trials 源）。"""

    chart_type = _CHART_TYPE

    @staticmethod
    def _best_so_far(records: list[TrialRecord]) -> list[float]:
        """逐点累计 min(cost)（收敛曲线标准口径；确定性单调不增序列）。"""
        out: list[float] = []
        best = float("inf")
        for r in records:
            best = min(best, r.cost)
            out.append(best)
        return out

    @staticmethod
    def _color(spec: AnimationSpec, idx: int) -> str:
        colors = spec.style.colors or PALETTE
        return colors[idx % len(colors)]

    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        bad = [s.kind for s in sources if s.kind != "trials"]
        if bad:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须全为 trials（收到 {bad}）——"
                "sparams_csv/snip 归 sparam_evolution/smith/fit_compare")
        if spec.style.labels is not None and len(spec.style.labels) != len(sources):
            raise AnimationSpecError(
                f"style.labels 数量 {len(spec.style.labels)} != 源数量 "
                f"{len(sources)}")
        runners: list[tuple[str, list[TrialRecord]]] = []
        for k, s in enumerate(sources):
            records = load_trials(s.path)
            name = (spec.style.labels[k] if spec.style.labels is not None
                    else self._default_name(s.path))
            runners.append((name, records))
        n_frames = max(len(recs) for _, recs in runners)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (0.0, float(n_frames - 1))
        curves: list[list[tuple[float, float]]] = []
        for _, recs in runners:
            best = self._best_so_far(recs)
            curves.append([(float(i), best[i]) for i in range(len(best))])
        y_vals = [y for c in curves for _, y in c]
        y_dom = (min(y_vals), max(y_vals))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        dur = self.duration_for(spec, n_frames)
        # 帧边界：第 k 帧揭示到 x=(k+1)/N×宽（点 i=i/(N−1)×宽 < 边界，
        # 点 k+1 > 边界——离散揭示逐迭代推进，末帧全宽）
        edges = ([box.x0 + box.w] if n_frames == 1
                 else [box.x0 + box.w * (k + 1) / n_frames
                       for k in range(n_frames)])
        clip_def = discrete_clip_reveal("anim_clip", box, edges, dur=dur)
        chrome = [
            cartesian_axes(box, x_ticks, y_ticks, xlabel="iteration",
                           ylabel="cost (best-so-far)",
                           font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(min(y_ticks), max(y_ticks))),
            legend_row([(name, self._color(spec, k))
                        for k, (name, _) in enumerate(runners)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        drawn: list[str] = []
        for k, pts in enumerate(curves):
            pixel_pts = [(box.xy(x, x_dom[0], x_dom[1], horizontal=True),
                          box.xy(y, y_dom[0], y_dom[1], horizontal=False))
                         for x, y in pts]
            drawn.append(polyline(pixel_pts, self._color(spec, k),
                                  spec.style.stroke_width))
        body = ("".join(chrome) + clip_def
                + f'<g clip-path="url(#anim_clip)">{"".join(drawn)}</g>')
        summaries = tuple(
            {"kind": "trials", "path": s.path, "n_trials": len(recs),
             "trial_numbers": [r.number for r in recs],
             "runner": runners[k][0]}
            for k, (s, (_, recs)) in enumerate(zip(sources, runners,
                                                   strict=True)))
        return RenderPlan(frame_count=n_frames, body=body,
                          data_sources=summaries, duration_s=dur)

    @staticmethod
    def _default_name(path: str) -> str:
        p = Path(path)
        return p.name if p.is_dir() else (p.parent.name or p.name)
