"""sparam_evolution 渲染器——S 参数曲线逐帧生长（T-Q3 批 1 图型①）。

动画语义（spec docstring 决策②清单第 1 项）：

- **points 模式**（单 source）：逐频点生长——帧 k 揭示曲线前 k+1 个频点
  （discrete clip 揭示，O(N) 几何）；多列（S11/S21...）同帧同速生长。
- **steps 模式**（多 sources≥2，扫参）：逐参数步点亮——帧 k 点亮第 k 步
  的整组曲线（组 opacity set 揭示）；各源 S 参数列集必须一致（同列同色，
  跨步对比），x 网格必须同栅（不满足→ AnimationDataError 带重采样指引）。

数值口径（确定性显示变换，零语义改写）：x=freq_hz 原值；y=|S| 线性或
dB（style.y_mode，缺省 db=20*log10|S|；|S|=0 in db 模式显式报错）。
图例=列名（数据源直通）；tick=nice_ticks(数据域)。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import (
    AnimationDataError,
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
    discrete_clip_reveal,
    fmt_num,
    legend_row,
    magnitude_to_y,
    nice_ticks,
    polyline,
    register_anim_renderer,
    require_common_grid,
    steps_reveal,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    SourceSpec,
)

__all__ = ["SparamEvolutionRenderer"]

_CHART_TYPE = "sparam_evolution"
_YLABEL = {"db": "|S| (dB)", "linear": "|S|"}


@register_anim_renderer(_CHART_TYPE)
class SparamEvolutionRenderer(AnimRenderer):
    """S 参数逐帧演变渲染器（points/steps 双模式，单列多列皆可）。"""

    chart_type = _CHART_TYPE

    # ── 加载面 ────────────────────────────────────────────────────────────
    def _load_source(self, src: SourceSpec) -> SparamsTable:
        if src.kind == "sparams_csv":
            return load_sparams_csv(src.path, columns=src.columns)
        if src.kind == "snip":
            return load_snip(src.path, columns=src.columns, ports=src.ports)
        raise AnimationSpecError(
            f"{_CHART_TYPE} 数据源 kind 须为 sparams_csv|snip（收到 "
            f"{src.kind!r}）——trials/anchor_json 归其他图型")

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        tables = [self._load_source(s) for s in sources]
        mode = "points" if len(tables) == 1 else "steps"
        if mode == "steps":
            grid = require_common_grid(
                [t.freq_hz for t in tables], f"{_CHART_TYPE} steps 模式")
            col_sets = [set(t.columns) for t in tables]
            if any(cs != col_sets[0] for cs in col_sets):
                raise AnimationDataError(
                    f"{_CHART_TYPE} steps 模式各源 S 参数列集不一致"
                    f"（{[sorted(cs) for cs in col_sets]}）——扫参对比要求"
                    "同一列集；请统一 spec.source.columns")
            columns = tables[0].columns
        else:
            grid = tables[0].freq_hz
            columns = tables[0].columns
        if not columns:
            raise AnimationDataError(f"{_CHART_TYPE} 无可绘制 S 参数列——不画空图")
        y_mode = spec.style.y_mode or "db"
        return (self._plan_points(spec, tables[0], grid, columns, y_mode)
                if mode == "points"
                else self._plan_steps(spec, tables, grid, columns, y_mode))

    # ── 公共：纵轴值+域+轴面 ──────────────────────────────────────────────
    def _ys_all(self, tables: list[SparamsTable], columns: tuple[str, ...],
                y_mode: str) -> dict[tuple[int, str], list[float]]:
        """(源序, 列名) → y 值（db/linear 确定性变换；加载面已挡非有限）。"""
        out: dict[tuple[int, str], list[float]] = {}
        for si, table in enumerate(tables):
            for col in columns:
                where = f"{table.source_path}:{col}"
                out[(si, col)] = magnitude_to_y(table.series[col], y_mode,
                                                where=where)
        return out

    @staticmethod
    def _domain(ys: dict[tuple[int, str], list[float]]) -> tuple[float, float]:
        vals = [v for seq in ys.values() for v in seq]
        return min(vals), max(vals)

    def _chrome(self, spec: AnimationSpec, grid: tuple[float, ...],
                y_dom: tuple[float, float], columns: tuple[str, ...],
                y_mode: str) -> str:
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        parts = [
            cartesian_axes(box, x_ticks, y_ticks,
                           xlabel="freq_hz", ylabel=_YLABEL[y_mode],
                           font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(min(y_ticks), max(y_ticks))),
            legend_row([(c, self._color(spec, k)) for k, c in enumerate(columns)],
                       box.x0, 38.0, font_size=spec.style.font_size),
        ]
        return "".join(parts)

    @staticmethod
    def _color(spec: AnimationSpec, idx: int) -> str:
        colors = spec.style.colors or PALETTE
        return colors[idx % len(colors)]

    @staticmethod
    def _clip_edges(px: list[float], box: PlotBox) -> list[float]:
        """逐帧揭示边界：相邻点像素中点；末帧=全宽（discrete 揭示契约）。"""
        n = len(px)
        if n == 1:
            return [box.x0 + box.w]
        edges = [ (px[k] + px[k + 1]) / 2.0 for k in range(n - 1) ]
        edges.append(box.x0 + box.w)
        return edges

    # ── points 模式 ───────────────────────────────────────────────────────
    def _plan_points(self, spec: AnimationSpec, table: SparamsTable,
                     grid: tuple[float, ...], columns: tuple[str, ...],
                     y_mode: str) -> RenderPlan:
        n = table.n_points
        ys = self._ys_all([table], columns, y_mode)
        y_dom = self._domain(ys)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        dur = self.duration_for(spec, n)
        edges = self._clip_edges(px, box)
        clip_def = discrete_clip_reveal("anim_clip", box, edges, dur=dur)
        curves: list[str] = []
        for k, col in enumerate(columns):
            pts = [(px[i], box.xy(ys[(0, col)][i], y_dom[0], y_dom[1],
                                  horizontal=False)) for i in range(n)]
            curves.append(polyline(pts, self._color(spec, k),
                                   spec.style.stroke_width))
        body = (
            self._chrome(spec, grid, y_dom, columns, y_mode)
            + clip_def
            + f'<g clip-path="url(#anim_clip)">{"".join(curves)}</g>'
        )
        summary = {"kind": "sparams_table", "path": table.source_path,
                   "n_points": n, "columns": list(columns), "mode": "points",
                   "x_min": fmt_num(min(grid)), "x_max": fmt_num(max(grid))}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)

    # ── steps 模式（扫参逐帧点亮） ────────────────────────────────────────
    def _plan_steps(self, spec: AnimationSpec, tables: list[SparamsTable],
                    grid: tuple[float, ...], columns: tuple[str, ...],
                    y_mode: str) -> RenderPlan:
        n_steps = len(tables)
        ys = self._ys_all(tables, columns, y_mode)
        y_dom = self._domain(ys)
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        dur = self.duration_for(spec, n_steps)
        clip_def, begins = steps_reveal("anim_clip", box, n_steps, dur=dur)
        groups: list[str] = []
        for si in range(n_steps):
            curves = []
            for k, col in enumerate(columns):
                pts = [(px[i], box.xy(ys[(si, col)][i], y_dom[0], y_dom[1],
                                      horizontal=False)) for i in range(len(grid))]
                curves.append(polyline(pts, self._color(spec, k),
                                       spec.style.stroke_width))
            groups.append(f'<g opacity="0">'
                          f'<set attributeName="opacity" to="1" '
                          f'begin="{begins[si]}"/>'
                          f'{"".join(curves)}</g>')
        labels = self._labels(spec, n_steps)
        body = (
            self._chrome(spec, grid, y_dom, columns, y_mode)
            + clip_def
            + f'<g clip-path="url(#anim_clip)">{"".join(groups)}</g>'
        )
        summaries = tuple(
            {"kind": "sparams_table", "path": t.source_path, "n_points": t.n_points,
             "columns": list(t.columns), "mode": "steps", "step_label": labels[si]}
            for si, t in enumerate(tables))
        return RenderPlan(frame_count=n_steps, body=body,
                          data_sources=summaries, duration_s=dur)

    @staticmethod
    def _labels(spec: AnimationSpec, n: int) -> list[str]:
        labels = spec.style.labels
        if labels is not None:
            if len(labels) != n:
                raise AnimationSpecError(
                    f"style.labels 数量 {len(labels)} != 源数量 {n}")
            return list(labels)
        return [f"step{k}" for k in range(n)]
