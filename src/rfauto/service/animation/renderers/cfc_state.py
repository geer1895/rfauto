"""cfc_state 渲染器——CfC 隐态轨迹逐 step 生长（Q-R3R 遗留清偿席）。

Q-W4-1 登记的 LNN 遗留清偿动画出口（"CfC 门控隐态轨迹从没画过"）：
隐态矩阵 (T,H) 逐维一条线（h00..hNN，调色板循环）、x=time（doc.time 缺席
时=step 序号）、帧 k=全部隐维同帧揭示到第 k 个 time step（discrete clip
揭示，O(T) 几何——sparam_evolution points 模式同构语义）。

数值口径（确定性显示变换，零语义改写）：x=doc.time 原值（或 step 序号）；
y=hidden 原值直用（**标准化网络空间**，Eq.(10) 门控态 tanh 有界 |x|≤1，
非物理原单位——口径声明于 SOURCE 溯源链：lnn_cfc 隐态导出 → cfc_state
渲染）。图例=隐维名（``h00``.. 缺省序号名；style.labels 覆盖，数量须=
hidden_dim）；tick=nice_ticks(数据域)。

数据源（单 source，kind=cfc_state）：loaders.load_cfc_state 契约——
``{"hidden":[[H 值]/step,...],"time"?:[...],"hidden_dim"?}``（产出面=
lnn_cfc.hidden_state_doc / LnnCfcSurrogate.hidden_states → service/
lnn_cfc_export_service.export_cfc_hidden_states）。time 须单调不减（逐帧
揭示前提；违反→ AnimationDataError 带预排序指引，渲染器不隐式重排）。

本模块无 ``__all__``：公开面快照 tests/gold/public_api.json 本席冻结
（新增公开名收编=显式评审动作，留后续席位 ``--generate`` 重钉）；注册面
走 ``@register_anim_renderer`` 装饰器自注册（renderers/__init__.py import
期挂载，消费面只走 base.get_anim_renderer）。
"""

from __future__ import annotations

import itertools

from rfauto.service.animation.loaders import (
    AnimationDataError,
    CfcStateDoc,
    load_cfc_state,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    PlotBox,
    RenderPlan,
    cartesian_axes,
    clip_edges_midpoints,
    discrete_clip_reveal,
    fmt_num,
    legend_row,
    nice_ticks,
    polyline,
    register_anim_renderer,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
)

_CHART_TYPE = "cfc_state"
_YLABEL = "hidden state (net space)"


@register_anim_renderer(_CHART_TYPE)
class CfcStateRenderer(AnimRenderer):
    """CfC 隐态轨迹逐 step 生长渲染器（单源 cfc_state，逐维多线）。"""

    chart_type = _CHART_TYPE

    # ── 数据面 ────────────────────────────────────────────────────────────
    @staticmethod
    def _x_grid(doc: CfcStateDoc) -> tuple[float, ...]:
        """横轴网格：doc.time 原值（单调不减校验）或 step 序号（0 基）。"""
        if doc.time is not None:
            grid = doc.time
            if any(b < a for a, b in itertools.pairwise(grid)):
                raise AnimationDataError(
                    f"{doc.source_path} time 非单调不减——逐帧揭示前提破坏；"
                    "请预排序数据源（渲染器不隐式重排引擎产物）")
            return grid
        return tuple(float(k) for k in range(doc.n_steps))

    @staticmethod
    def _labels(spec: AnimationSpec, n_dims: int) -> list[str]:
        """图例名：style.labels 覆盖（数量须=hidden_dim）或 h00.. 序号名。"""
        labels = spec.style.labels
        if labels is not None:
            if len(labels) != n_dims:
                raise AnimationSpecError(
                    f"{_CHART_TYPE} style.labels 数量 {len(labels)} != "
                    f"hidden_dim {n_dims}")
            return list(labels)
        return [f"h{k:02d}" for k in range(n_dims)]

    @staticmethod
    def _color(spec: AnimationSpec, idx: int) -> str:
        colors = spec.style.colors or PALETTE
        return colors[idx % len(colors)]

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 单源图型：恰 1 个 source（收到 "
                f"{len(sources)} 个）——多源对比请各渲染一张后并排")
        src = sources[0]
        if src.kind != "cfc_state":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 cfc_state（收到 "
                f"{src.kind!r}）——S 参数源归 sparam_evolution/fit_compare")
        doc = load_cfc_state(src.path)
        n = doc.n_steps
        h = doc.hidden_dim
        grid = self._x_grid(doc)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        y_all = [v for row in doc.hidden for v in row]
        y_dom = (min(y_all), max(y_all))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        dur = self.duration_for(spec, n)
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        edges = clip_edges_midpoints(px, box)
        clip_def = discrete_clip_reveal("anim_clip", box, edges, dur=dur)
        labels = self._labels(spec, h)
        chrome = [
            cartesian_axes(box, x_ticks, y_ticks,
                           xlabel="time_s" if doc.time is not None else "step",
                           ylabel=_YLABEL, font_size=spec.style.font_size,
                           x_domain=x_dom,
                           y_domain=(min(y_ticks), max(y_ticks))),
            legend_row([(labels[k], self._color(spec, k)) for k in range(h)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        lines: list[str] = []
        for k in range(h):
            pts = [(px[i], box.xy(doc.hidden[i][k], y_dom[0], y_dom[1],
                                  horizontal=False)) for i in range(n)]
            lines.append(polyline(pts, self._color(spec, k),
                                  spec.style.stroke_width))
        body = ("".join(chrome) + clip_def
                + f'<g clip-path="url(#anim_clip)">{"".join(lines)}</g>')
        summary = {"kind": "cfc_state", "path": doc.source_path,
                   "n_steps": n, "hidden_dim": h,
                   "x_min": fmt_num(x_dom[0]), "x_max": fmt_num(x_dom[1]),
                   "x_axis": "time_s" if doc.time is not None else "step",
                   "provenance_keys": sorted(doc.provenance)}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)
