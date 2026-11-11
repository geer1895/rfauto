"""nf_cascade 渲染器——NF 级联瀑布逐级点亮（批 3 图型⑨，决策②第 10 项）。

动画语义：帧 k=第 k 级点亮（:func:`steps_reveal` 逐级组 opacity set）——
阶梯 polyline 双线（累计 NF + 累计增益），逐级看出噪声/增益在链上的累计。

**声明式派生（本图型唯一算术，非数据改写；公式与 core/cascade.py Friis
口径一致，独立复算锚在测试）**：

- 线性功率域换算：``F_i = 10^(nf_db_i/10)``、``G_i = 10^(gain_db_i/10)``；
- **Friis 级联噪声系数**：``F_total = F1 + (F2−1)/G1 + (F3−1)/(G1·G2) + …``
  ——累计到第 k 级：``F_cum(k) = F1 + Σ_{i=2..k} (F_i−1)/Π_{j=1..k-1} G_j``；
  ``NF_cum(k) dB = 10·log10(F_cum(k))``；
- **累计增益**：``G_cum(k) dB = Σ_{i=1..k} gain_db_i``（dB 域算术和）；
- 每级标注文本：级名（数据直通或位置回退 ``stage{k}``）、该级 gain_db
  （数据直通）、累计 NF 值（上式派生）——fmt_num 定型。

几何（布局量，非数据）：级 i（0 基）占 x 带 ``[i, i+1]``（域 (0,N) 等分）；
第 i 级组=竖直连接线（x=i 处从上一级电平到本级电平；i=0 免发）+带内水平
线（本级电平）；y 域=两序列全部累计值的 min/max（nice_ticks）。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from rfauto.service.animation.loaders import CascadeDoc, load_cascade_json
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
    steps_reveal,
    svg_text,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["CascadeNfRenderer", "cumulative_gain_db", "friis_cumulative_nf_db"]

_CHART_TYPE = "nf_cascade"

#: 缺省图例（style.labels 覆盖须恰 2 项：[累计 NF, 累计增益]）
DEFAULT_LABELS = ("cumulative NF", "cumulative gain")


def _lin10(db: float) -> float:
    """dB → 线性功率比（10^(db/10)；Friis 功率域口径）。"""
    return 10.0 ** (db / 10.0)


def friis_cumulative_nf_db(stages: Sequence[tuple[float, float]]) -> list[float]:
    """级表 [(gain_db, nf_db), ...]（信号流向序）→ 累计 NF dB 序列。

    Friis：F_cum(k) = F1 + Σ_{i=2..k} (F_i−1)/Π_{j=1..k-1} G_j（功率域
    线性叠加）；返回 [NF_cum(1), ..., NF_cum(k)] dB（声明式派生，测试
    独立复算锚）。gain_lin>0 对任意有限 gain_db 恒成立（10^x>0），无
    除零路径。
    """
    if not stages:
        raise ValueError("stages 至少 1 级")
    f_cum = 0.0
    prod_gain = 1.0
    out: list[float] = []
    for k, (gain_db, nf_db) in enumerate(stages):
        f = _lin10(nf_db)
        g = _lin10(gain_db)
        f_cum += f if k == 0 else (f - 1.0) / prod_gain
        prod_gain *= g
        out.append(10.0 * math.log10(f_cum))
    return out


def cumulative_gain_db(stages: Sequence[tuple[float, float]]) -> list[float]:
    """级表 → 累计增益 dB 序列（dB 域算术和；声明式派生，测试锚）。"""
    out: list[float] = []
    acc = 0.0
    for gain_db, _nf in stages:
        acc += gain_db
        out.append(acc)
    return out


@register_anim_renderer(_CHART_TYPE)
class CascadeNfRenderer(AnimRenderer):
    """NF 级联瀑布渲染器（单 cascade_json 源，阶梯双线逐级点亮）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）——"
                "多源对比图型用 fit_compare/before_after")
        if sources[0].kind != "cascade_json":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 cascade_json（收到 "
                f"{sources[0].kind!r}）——S 参数源归 sparam_evolution，"
                "链路框图归 signal_flow")
        doc: CascadeDoc = load_cascade_json(sources[0].path)
        return self._plan(spec, doc)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, doc: CascadeDoc) -> RenderPlan:
        n = doc.n_stages
        pairs = [(s.gain_db, s.nf_db) for s in doc.stages]
        nf_cum = friis_cumulative_nf_db(pairs)
        gain_cum = cumulative_gain_db(pairs)
        labels = self._labels(spec)
        nf_color, gain_color = self._colors(spec)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        y_dom = (min(min(nf_cum), min(gain_cum)),
                 max(max(nf_cum), max(gain_cum)))
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        x_dom = (0.0, float(n))
        x_ticks = [float(k) for k in range(n + 1)]
        dur = self.duration_for(spec, n)
        px = [box.xy(float(i), x_dom[0], x_dom[1]) for i in range(n + 1)]
        y_dB = {v: box.xy(v, y_dom[0], y_dom[1], horizontal=False)
                for v in set(nf_cum) | set(gain_cum)}

        def stair_i(i: int, level: list[float], color: str) -> str:
            """级 i 的阶梯段（竖直连接+带内水平）；i=0 免竖直（免 no-op）。

            只画本级段——逐级点亮语义：级 i 的段仅在 begin_i 后可见。
            """
            pts: list[tuple[float, float]] = []
            if i > 0:
                pts.append((px[i], y_dB[level[i - 1]]))
            pts.append((px[i], y_dB[level[i]]))
            pts.append((px[i + 1], y_dB[level[i]]))
            return polyline(pts, color, spec.style.stroke_width)

        clip_def, begins = steps_reveal("anim_clip", box, n, dur=dur)
        groups: list[str] = []
        for i, stage in enumerate(doc.stages):
            name = stage.name if stage.name is not None else f"stage{i}"
            cx_band = (px[i] + px[i + 1]) / 2.0
            parts = [stair_i(i, nf_cum, nf_color),
                     stair_i(i, gain_cum, gain_color)]
            parts.append(svg_text(cx_band, box.y0 + spec.style.font_size,
                                  name, size=spec.style.font_size,
                                  anchor="middle", fill="#222222",
                                  weight="bold"))
            parts.append(svg_text(cx_band, box.y0 + box.h
                                  - spec.style.font_size * 0.4,
                                  f"G={fmt_num(stage.gain_db)}dB",
                                  size=spec.style.font_size - 1,
                                  anchor="middle", fill="#555555"))
            parts.append(svg_text(cx_band, y_dB[nf_cum[i]]
                                  - spec.style.font_size * 0.3,
                                  f"NF={fmt_num(nf_cum[i])}dB",
                                  size=spec.style.font_size - 1,
                                  anchor="middle", fill=nf_color))
            groups.append(f'<g opacity="0">'
                          f'<set attributeName="opacity" to="1" '
                          f'begin="{begins[i]}"/>'
                          f'{"".join(parts)}</g>')
        chrome = [
            cartesian_axes(box, x_ticks, y_ticks, xlabel="stage",
                           ylabel="dB", font_size=spec.style.font_size,
                           x_domain=x_dom,
                           y_domain=(min(y_ticks), max(y_ticks))),
            legend_row([(labels[0], nf_color), (labels[1], gain_color)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        body = ("".join(chrome) + clip_def
                + f'<g clip-path="url(#anim_clip)">{"".join(groups)}</g>')
        summary = {"kind": "cascade_json", "path": doc.source_path,
                   "n_stages": n,
                   "stage_names": [s.name if s.name is not None
                                   else f"stage{i}"
                                   for i, s in enumerate(doc.stages)],
                   "nf_total_db": fmt_num(nf_cum[-1]),
                   "gain_total_db": fmt_num(gain_cum[-1])}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)

    @staticmethod
    def _colors(spec: AnimationSpec) -> tuple[str, str]:
        colors = spec.style.colors or PALETTE
        return (colors[0 % len(colors)], colors[1 % len(colors)])

    @staticmethod
    def _labels(spec: AnimationSpec) -> tuple[str, str]:
        labels = spec.style.labels
        if labels is not None:
            if len(labels) != 2:
                raise AnimationSpecError(
                    f"{_CHART_TYPE} style.labels 须恰 2 项"
                    f"（累计 NF/累计增益，收到 {len(labels)} 项）")
            return (labels[0], labels[1])
        return DEFAULT_LABELS
