"""vswr_history 渲染器——VSWR 驻波比历程逐频点揭示（批 2 图型⑨/决策②9）。

动画语义（spec docstring 决策②清单第 9 项）：帧 k=曲线揭示到第 k 个频点
（共享 discrete clip，x=freq_hz 单调——"历程"语义=沿数据序逐点推进）。

**声明式派生（任务书钉死的变换式，非任意改写）**：

- 数据=单 source sparams_csv|snip 的恰一列（缺省 ``S11``——反射量）；
- 每点 ``VSWR = (1+|Γ|)/(1−|Γ|)``，其中 ``Γ=S11``（50Ω 基复反射系数，
  数据直通；|·| 为模）。公式与传输线理论标准定义一致（独立复算锚在测试）；
- **|Γ|≥1 保护性截断为 inf→显式标记不画点**：|Γ|≥1（含恰 =1 的全反射）
  数学上 VSWR→inf 或负值（非物理），该点不计入折线（分段断开）且 warnings
  记首个坏点（照 smith |Γ|>1 先例：如实提示不静默不刷屏）；全部点无效→
  AnimationDataError（不画空图）。

y 轴=VSWR 线性刻度（无量纲比，无 dB 口径）；x=freq_hz 原值。渲染零算术
改写——上式为唯一声明变换，坐标像素=nice_ticks/PlotBox 常规映射。
"""

from __future__ import annotations

import itertools
import math

from rfauto.service.animation.loaders import (
    AnimationDataError,
    SparamsTable,
    load_snip,
    load_sparams_csv,
)
from rfauto.service.animation.renderers.base import (
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    clip_edges_midpoints,
    discrete_clip_reveal,
    fmt_num,
    nice_ticks,
    polyline,
    register_anim_renderer,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    SourceSpec,
)

__all__ = ["VswrHistoryRenderer", "vswr_of_gamma"]

_CHART_TYPE = "vswr_history"


def vswr_of_gamma(gamma_abs: float) -> float:
    """|Γ| → VSWR=(1+|Γ|)/(1−|Γ|)（|Γ|≥1 → math.inf；独立复算锚用）。"""
    if gamma_abs >= 1.0:
        return math.inf
    return (1.0 + gamma_abs) / (1.0 - gamma_abs)


@register_anim_renderer(_CHART_TYPE)
class VswrHistoryRenderer(AnimRenderer):
    """VSWR 历程渲染器（单 sparams 源单列，逐频点揭示，inf 点断开不画）。"""

    chart_type = _CHART_TYPE

    # ── 数据面 ────────────────────────────────────────────────────────────
    def _load(self, src: SourceSpec) -> SparamsTable:
        if src.kind not in ("sparams_csv", "snip"):
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 sparams_csv|snip（收到 "
                f"{src.kind!r}）——VSWR 派生自 S 参数反射量")
        columns = src.columns or ["S11"]
        if len(set(columns)) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 恰一列反射量（如 S11；收到 "
                f"{sorted(set(columns))}）——多列请拆多 spec")
        if src.kind == "sparams_csv":
            return load_sparams_csv(src.path, columns=columns)
        return load_snip(src.path, columns=columns, ports=src.ports)

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）")
        table = self._load(sources[0])
        grid = table.freq_hz
        if any(b < a for a, b in itertools.pairwise(grid)):
            raise AnimationDataError(
                f"{table.source_path} freq_hz 非单调不减——逐帧揭示前提"
                "破坏；请预排序数据源（渲染器不隐式重排引擎产物）")
        col = table.columns[0]
        where = f"{table.source_path}:{col}"
        warnings: list[str] = []
        vswr: list[float | None] = []
        for k, z in enumerate(table.series[col]):
            g = abs(z)
            if g >= 1.0:
                vswr.append(None)
                if not warnings:
                    warnings.append(
                        f"数据点 {k} |Γ|={g:.6g}≥1——VSWR 保护性截断为 inf，"
                        "该点不画（分段断开）；请核对数据源或端接条件")
            else:
                vswr.append(vswr_of_gamma(g))
        valid = [v for v in vswr if v is not None]
        if not valid:
            raise AnimationDataError(
                f"{where} 全部点 |Γ|≥1（无有效 VSWR 点）——不画空图")
        n = len(grid)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        y_dom = (min(valid), max(valid))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        dur = self.duration_for(spec, n)
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        edges = clip_edges_midpoints(px, box)
        clip_def = discrete_clip_reveal("anim_clip", box, edges, dur=dur)
        color = spec.style.colors[0] if spec.style.colors else "#1f77b4"
        chrome = [
            cartesian_axes(box, x_ticks, y_ticks, xlabel="freq_hz",
                           ylabel="VSWR", font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(min(y_ticks),
                                                     max(y_ticks))),
        ]
        # 折线按有效点分段（None=断开；单点段为退化折线，与批 1 单点口径同）
        segments: list[list[tuple[float, float]]] = []
        cur: list[tuple[float, float]] = []
        for k, v in enumerate(vswr):
            if v is None:
                if cur:
                    segments.append(cur)
                    cur = []
            else:
                py = box.xy(v, y_dom[0], y_dom[1], horizontal=False)
                cur.append((px[k], py))
        if cur:
            segments.append(cur)
        body = ("".join(chrome) + clip_def
                + '<g clip-path="url(#anim_clip)">'
                + "".join(polyline(seg, color, spec.style.stroke_width)
                          for seg in segments)
                + "</g>")
        summary = {"kind": "sparams_table", "path": table.source_path,
                   "n_points": n, "columns": [col],
                   "n_invalid_gamma": n - len(valid),
                   "x_min": fmt_num(min(grid)), "x_max": fmt_num(max(grid)),
                   "vswr_min": fmt_num(y_dom[0]), "vswr_max": fmt_num(y_dom[1])}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur, warnings=tuple(warnings))
