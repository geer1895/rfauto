"""tuning_replay 渲染器——调谐历史回放（批 4 图型⑭，决策②第 15 项）。

动画语义：帧 k=第 k 个 trial 散点落点（``<set opacity>`` 逐帧点亮，smith
同款计时）；响应曲线为**静态背景**（全程可见，不参与帧揭示）——回放语义
=调谐迭代在响应画布上逐点落位。

数据源（双源，sources 恰 2，按 kind 定角色——fit_compare 多源先例，
spec 零扩展）：

- ``trials``（恰 1 个）：trial 散点=(x=迭代序号 i（trial_number 升序位置，
  同 param_race 口径）, y=cost 原值直通)；
- ``sparams_csv``/``snip``（恰 1 个，columns 须恰一列）：响应曲线背景，
  y=|S|（style.y_mode，缺省 db=magnitude_to_y 口径）。

**背景曲线 x 映射（声明式展示变换，独立复算锚在测试）**：背景与散点共用
回放轴 x∈[0, N−1]（N=trial 数）；背景第 j 频点 x=j·(N−1)/(M−1)（M=频点
数，索引等距拉伸到回放域——展示映射非物理频率标定；M<2 AnimationDataError
显式拒绝，单点无响应形态）。y 域=两源 y 值并集（曲线 dB 与 cost 同面同
轴——数值直通零改写；轴标签声明双语义）。

文本：图例（style.labels 覆盖须恰 2 项：[响应曲线, trial 落点]；缺省
``response``/``trial``）+轴标签。散点标记半径=max(2.0, font_size/5)
（smith 同款）。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import (
    AnimationDataError,
    TrialRecord,
    load_snip,
    load_sparams_csv,
    load_trials,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    fmt_num,
    legend_row,
    magnitude_to_y,
    nice_ticks,
    polyline,
    register_anim_renderer,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    SourceSpec,
)

__all__ = ["TuningReplayRenderer", "background_x_values"]

_CHART_TYPE = "tuning_replay"

#: 缺省图例（style.labels 覆盖须恰 2 项：[响应曲线, trial 落点]）
DEFAULT_LABELS = ("response", "trial")


def background_x_values(n_curve: int, x_lo: float, x_hi: float) -> list[float]:
    """背景曲线索引等距映射（声明式）：第 j 频点 → x=j·(hi−lo)/(M−1)+lo。

    M<2 ValueError（调用方渲染器先以 AnimationDataError 拦截）；M=2 恰
    两端点。纯布局映射，零数值改写。
    """
    if n_curve < 2:
        raise ValueError("背景曲线至少 2 频点")
    step = (x_hi - x_lo) / (n_curve - 1)
    return [x_lo + j * step for j in range(n_curve)]


@register_anim_renderer(_CHART_TYPE)
class TuningReplayRenderer(AnimRenderer):
    """调谐历史回放渲染器（trials+sparams 双源，散点逐帧落点）。"""

    chart_type = _CHART_TYPE

    # ── 数据面 ────────────────────────────────────────────────────────────
    @staticmethod
    def _curve(src: SourceSpec, y_mode: str) -> tuple[list[float], dict]:
        """响应曲线源 → (y 序列[y_mode 口径], 数据摘要)；x 由索引映射派生。"""
        columns = src.columns or ["S11"]
        if len(columns) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 背景曲线一次一条：columns 须恰一列（收到 "
                f"{sorted(set(columns))}）")
        if src.kind == "sparams_csv":
            table = load_sparams_csv(src.path, columns=columns)
        else:
            table = load_snip(src.path, columns=columns, ports=src.ports)
        if table.n_points < 2:
            raise AnimationDataError(
                f"{table.source_path} 背景曲线仅 {table.n_points} 频点——"
                "须 ≥2（单点无响应形态；请换完整响应产物）")
        col = table.columns[0]
        y = magnitude_to_y(table.series[col], y_mode,
                           where=f"{table.source_path}:{col}")
        return y, {"kind": "sparams_table", "path": table.source_path,
                   "n_points": table.n_points, "columns": [col]}

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 2:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 恰 2 个源（trials+sparams，收到 "
                f"{len(sources)} 个）")
        trial_srcs = [s for s in sources if s.kind == "trials"]
        curve_srcs = [s for s in sources
                      if s.kind in ("sparams_csv", "snip")]
        if len(trial_srcs) != 1 or len(curve_srcs) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 双源角色须恰一 trials + 恰一 "
                f"sparams_csv|snip（收到 kinds="
                f"{[s.kind for s in sources]}）——纯 trials 赛跑归 "
                "param_race，纯 S 参数归 sparam_evolution")
        records: list[TrialRecord] = load_trials(trial_srcs[0].path)
        curve_y, curve_summary = self._curve(
            curve_srcs[0], spec.style.y_mode or "db")
        return self._plan(spec, records, trial_srcs[0].path, curve_y,
                          curve_summary)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, records: list[TrialRecord],
              trial_path: str, curve_y: list[float],
              curve_summary: dict) -> RenderPlan:
        n = len(records)
        m = len(curve_y)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (0.0, float(n - 1))
        bg_x = background_x_values(m, x_dom[0], x_dom[1])
        y_dom = (min(min(curve_y), min(r.cost for r in records)),
                 max(max(curve_y), max(r.cost for r in records)))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        dur = self.duration_for(spec, n)
        colors = spec.style.colors or PALETTE
        curve_color = colors[0 % len(colors)]
        dot_color = colors[1 % len(colors)]
        labels = self._labels(spec)
        y_mode = spec.style.y_mode or "db"

        bg_px = [(box.xy(xv, x_dom[0], x_dom[1]),
                  box.xy(yv, y_dom[0], y_dom[1], horizontal=False))
                 for xv, yv in zip(bg_x, curve_y, strict=True)]
        chrome = [
            polyline(bg_px, curve_color, spec.style.stroke_width),
            cartesian_axes(box, x_ticks, y_ticks, xlabel="iteration",
                           ylabel="cost / |S| (dB)" if y_mode == "db"
                           else "cost / |S|",
                           font_size=spec.style.font_size,
                           x_domain=x_dom,
                           y_domain=(min(y_ticks), max(y_ticks))),
            legend_row([(labels[0], curve_color), (labels[1], dot_color)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        marker_r = max(2.0, spec.style.font_size / 5.0)
        out: list[str] = []
        for k, rec in enumerate(records):
            px = box.xy(float(k), x_dom[0], x_dom[1])
            py = box.xy(rec.cost, y_dom[0], y_dom[1], horizontal=False)
            out.append(f'<circle cx="{fmt_num(px)}" cy="{fmt_num(py)}" '
                       f'r="{fmt_num(marker_r)}" fill="{dot_color}" '
                       f'opacity="0">'
                       f'<set attributeName="opacity" to="1" '
                       f'begin="{k * dur / n:.6f}s"/></circle>')
        body = "".join(chrome) + "".join(out)
        summaries = (curve_summary,
                     {"kind": "trials", "path": trial_path,
                      "n_trials": n,
                      "trial_numbers": [r.number for r in records]})
        return RenderPlan(frame_count=n, body=body,
                          data_sources=tuple(summaries), duration_s=dur)

    @staticmethod
    def _labels(spec: AnimationSpec) -> tuple[str, str]:
        labels = spec.style.labels
        if labels is not None:
            if len(labels) != 2:
                raise AnimationSpecError(
                    f"{_CHART_TYPE} style.labels 须恰 2 项"
                    f"（响应曲线/trial 落点，收到 {len(labels)} 项）")
            return (labels[0], labels[1])
        return DEFAULT_LABELS
