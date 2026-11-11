"""constellation_eye 渲染器——星座/眼图张开演进（批 4 图型⑮，决策②第 16 项）。

动画语义：帧 k=第 k 个符号落面——星座散点逐符号点亮（``<set opacity>``
smith 同款计时）+ **眼图轨迹 polyline 随帧滑窗生长**：第 k 帧画出以当前
符号收尾的滑窗轨迹（当前数据帧内向前取 W=窗宽个符号连折线，窗滑动=帧
推进；轨迹累积=眼图逐步张开，帧语义=符号窗滑动）。

数据源（单 ``symbols_json``，loaders.load_symbols_json 契约）：单云
``{"symbols":[[i,q],...]}`` 或帧序列 ``{"frames":[{"symbols":[[i,q],...]},
...]}``（恰一形态；si_channel 面无既有符号产物——任务书最小 JSON 约定）。

**几何规则（声明式，独立复算锚在测试）**：

- 象限域：I 横轴/Q 纵轴，域=(−m, m) 对称，``m = max(|i|,|q|)`` 全符号
  最大模（m=0 退化 → m=1.0 布局回退常量，非数据补造——域常量仅定刻度）；
- 符号→像素：``px = box.xy(i, −m, m)``、``py = box.xy(q, −m, m,
  horizontal=False)``（线性映射零改写）；
- **眼图轨迹窗**：W=style.eye_window（None=8 缺省，spec 约束 ≥2）；第 k
  帧（全局符号序 k）轨迹=当前数据帧内 ``[max(帧首, k−W+1), k]`` 区间符号
  依序连线——**轨迹不跨数据帧连接**（帧=符号窗捕获分组，跨窗过渡非真实
  符号转移）；窗内符号 <2 的帧只落散点无轨迹；
- 散点标记半径=max(2.0, font_size/5)（smith 同款）。

文本：图例（style.labels 覆盖须恰 2 项：[星座散点, 眼图轨迹]；缺省
``constellation``/``eye trace``）+轴标签（``I``/``Q``）。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import SymbolsDoc, load_symbols_json
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    fmt_num,
    legend_row,
    nice_ticks,
    polyline,
    register_anim_renderer,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["DEFAULT_EYE_WINDOW", "ConstellationEyeRenderer", "eye_windows"]

_CHART_TYPE = "constellation_eye"

#: 眼图轨迹缺省窗宽（style.eye_window 覆盖；spec 约束 ≥2）
DEFAULT_EYE_WINDOW = 8

#: 缺省图例（style.labels 覆盖须恰 2 项：[星座散点, 眼图轨迹]）
DEFAULT_LABELS = ("constellation", "eye trace")


def eye_windows(frame_sizes: list[int], window: int) -> list[int]:
    """逐符号轨迹长度表（声明式）：第 k 符号（全局序）的轨迹点数。

    帧内滑窗：``min(k−帧首+1, W)``；窗内 <2 → 0（该帧只落散点）。
    纯布局函数（测试独立复算锚）；window ≥2 前提由 spec 约束保证。
    """
    if window < 2:
        raise ValueError("eye window 必须 ≥2")
    out: list[int] = []
    for size in frame_sizes:
        for j in range(size):
            length = min(j + 1, window)
            out.append(length if length >= 2 else 0)
    return out


@register_anim_renderer(_CHART_TYPE)
class ConstellationEyeRenderer(AnimRenderer):
    """星座/眼图张开渲染器（单 symbols_json 源，逐符号落面+滑窗轨迹）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）")
        if sources[0].kind != "symbols_json":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 symbols_json（收到 "
                f"{sources[0].kind!r}）——S 参数源归 sparam_evolution，"
                "trials 归 param_race/tuning_replay")
        doc: SymbolsDoc = load_symbols_json(sources[0].path)
        return self._plan(spec, doc)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, doc: SymbolsDoc) -> RenderPlan:
        window = (spec.style.eye_window
                  if spec.style.eye_window is not None else DEFAULT_EYE_WINDOW)
        if window < 2:
            raise AnimationSpecError(
                f"style.eye_window 必须 ≥2（收到 {window}）")
        flat: list[tuple[float, float]] = []
        frame_sizes: list[int] = []
        for frame in doc.frames:
            flat.extend(frame.symbols)
            frame_sizes.append(frame.n_symbols)
        n_total = len(flat)
        m = max(max(abs(i), abs(q)) for i, q in flat)
        if m == 0:
            m = 1.0
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        dom = (-m, m)
        ticks = nice_ticks(dom[0], dom[1])
        dur = self.duration_for(spec, n_total)
        colors = spec.style.colors or PALETTE
        dot_color, trace_color = colors[0 % len(colors)], colors[1 % len(colors)]
        labels = self._labels(spec)
        marker_r = max(2.0, spec.style.font_size / 5.0)

        def px(i: float) -> float:
            return box.xy(i, dom[0], dom[1])

        def py(q: float) -> float:
            return box.xy(q, dom[0], dom[1], horizontal=False)

        chrome = [
            cartesian_axes(box, ticks, ticks, xlabel="I", ylabel="Q",
                           font_size=spec.style.font_size, x_domain=dom,
                           y_domain=dom),
            legend_row([(labels[0], dot_color), (labels[1], trace_color)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        out: list[str] = []
        k = 0
        trace_lens = eye_windows(frame_sizes, window)
        for frame in doc.frames:
            frame_start = k
            for _j, (i_val, q_val) in enumerate(frame.symbols):
                begin = f"{k * dur / n_total:.6f}s"
                out.append(f'<circle cx="{fmt_num(px(i_val))}" '
                           f'cy="{fmt_num(py(q_val))}" '
                           f'r="{fmt_num(marker_r)}" fill="{dot_color}" '
                           f'opacity="0">'
                           f'<set attributeName="opacity" to="1" '
                           f'begin="{begin}"/></circle>')
                if trace_lens[k] >= 2:
                    lo = max(frame_start, k - window + 1)
                    pts = [(px(flat[t][0]), py(flat[t][1]))
                           for t in range(lo, k + 1)]
                    trace = polyline(pts, trace_color,
                                     spec.style.stroke_width)
                    out.append(f'<g opacity="0">'
                               f'<set attributeName="opacity" to="1" '
                               f'begin="{begin}"/>{trace}</g>')
                k += 1
        body = "".join(chrome) + "".join(out)
        summary = {"kind": "symbols_json", "path": doc.source_path,
                   "n_symbols": n_total, "n_frames": doc.n_frames,
                   "eye_window": window}
        return RenderPlan(frame_count=n_total, body=body,
                          data_sources=(summary,), duration_s=dur)

    @staticmethod
    def _labels(spec: AnimationSpec) -> tuple[str, str]:
        labels = spec.style.labels
        if labels is not None:
            if len(labels) != 2:
                raise AnimationSpecError(
                    f"{_CHART_TYPE} style.labels 须恰 2 项"
                    f"（星座散点/眼图轨迹，收到 {len(labels)} 项）")
            return (labels[0], labels[1])
        return DEFAULT_LABELS
