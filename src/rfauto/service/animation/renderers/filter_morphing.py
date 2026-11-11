"""filter_morphing 渲染器——滤波器响应族 morphing 连续变形（批 3 图型⑪）。

动画语义：曲线从第 0 步响应出发，帧边界处 **SMIL ``<animate
attributeName="d">`` 线性插值**（from=上一步 path d、to=本步 path d、
``begin=k×dur/N``、``dur= dur/N``、``fill=freeze``——后激活者按 SMIL 优先
级覆盖前者冻结值，级联成步进 morph 链）；帧 k=第 k 步开始变形
（frame_count=步数 N）。当前步名标签组按 discrete opacity 逐帧切换
（同 field_heatmap 逐帧替换件）。

数据源（多源形态沿 sparam_evolution steps 模式同款）：sources≥2，每源
kind=``sparams_csv|snip``；**各源 x 网格必须同点数同栅**
（:func:`require_common_grid`——同点数是 path d 可插值前提：逐点等长
才存在逐点线性对应）；各源 S 参数列集必须一致（同列同色）。

数值口径：y=|S|（style.y_mode，缺省 db=20·log10|S|；零算术语义改写走
:func:`magnitude_to_y` 公共件）；path d=``M x0,y0 L x1,y1 ...``（像素
坐标 fmt_num 定型——坐标映射为声明式确定性变换）。
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
    esc,
    fmt_num,
    legend_row,
    magnitude_to_y,
    nice_ticks,
    register_anim_renderer,
    require_common_grid,
    svg_text,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    SourceSpec,
)

__all__ = ["FilterMorphingRenderer"]

_CHART_TYPE = "filter_morphing"
_YLABEL = {"db": "|S| (dB)", "linear": "|S|"}


def path_d(points: list[tuple[float, float]]) -> str:
    """像素点列 → SVG path d（``M x0,y0 L x1,y1 ...``；fmt_num 定型）。

    同点数前提由 require_common_grid 保证——逐点等长才有逐点线性插值
    （morph 语义的数学前提，缺数据/异栅显式报错不做隐式重采样）。
    """
    if not points:
        raise ValueError("points 至少 1 点")
    head = f"M {fmt_num(points[0][0])},{fmt_num(points[0][1])}"
    rest = " ".join(f"L {fmt_num(x)},{fmt_num(y)}" for x, y in points[1:])
    return f"{head} {rest}".strip()


@register_anim_renderer(_CHART_TYPE)
class FilterMorphingRenderer(AnimRenderer):
    """响应族 morphing 渲染器（多 sparams 源同栅，SMIL d 属性插值）。"""

    chart_type = _CHART_TYPE

    # ── 加载面 ────────────────────────────────────────────────────────────
    def _load_source(self, src: SourceSpec) -> SparamsTable:
        if src.kind == "sparams_csv":
            return load_sparams_csv(src.path, columns=src.columns)
        if src.kind == "snip":
            return load_snip(src.path, columns=src.columns, ports=src.ports)
        raise AnimationSpecError(
            f"{_CHART_TYPE} 数据源 kind 须为 sparams_csv|snip（收到 "
            f"{src.kind!r}）——cascade/nf2ff/chain 源归各自图型")

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) < 2:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是多源 morph 图型（收到 {len(sources)} 个源"
                "）——morphing 语义需 ≥2 步响应（sources 列表）")
        tables = [self._load_source(s) for s in sources]
        grid = require_common_grid([t.freq_hz for t in tables],
                                   f"{_CHART_TYPE} morph 守卫")
        col_sets = [set(t.columns) for t in tables]
        if any(cs != col_sets[0] for cs in col_sets):
            raise AnimationDataError(
                f"{_CHART_TYPE} 各源 S 参数列集不一致"
                f"（{[sorted(cs) for cs in col_sets]}）——morph 要求同一列集；"
                "请统一 spec.source.columns")
        columns = tables[0].columns
        if not columns:
            raise AnimationDataError(f"{_CHART_TYPE} 无可绘制 S 参数列——不画空图")
        n_steps = len(tables)
        y_mode = spec.style.y_mode or "db"
        ys: dict[tuple[int, str], list[float]] = {}
        for si, table in enumerate(tables):
            for col in columns:
                ys[(si, col)] = magnitude_to_y(
                    table.series[col], y_mode,
                    where=f"{table.source_path}:{col}")
        y_all = [v for seq in ys.values() for v in seq]
        y_dom = (min(y_all), max(y_all))
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        x_dom = (min(grid), max(grid))
        x_ticks = nice_ticks(x_dom[0], x_dom[1])
        y_ticks = nice_ticks(y_dom[0], y_dom[1])
        px = [box.xy(f, x_dom[0], x_dom[1], horizontal=True) for f in grid]
        dur = self.duration_for(spec, n_steps)

        # 每列一条 path：d_k 序列 + SMIL d 插值链（begin=k×dur/N）
        paths: list[str] = []
        for k, col in enumerate(columns):
            color = (spec.style.colors or PALETTE)[k % len(spec.style.colors
                                                           or PALETTE)]
            ds = [path_d([(px[i], box.xy(ys[(si, col)][i], y_dom[0], y_dom[1],
                                         horizontal=False))
                          for i in range(len(grid))])
                  for si in range(n_steps)]
            anims = "".join(
                f'<animate attributeName="d" from="{esc(ds[m - 1])}" '
                f'to="{esc(ds[m])}" begin="{m * dur / n_steps:.6f}s" '
                f'dur="{dur / n_steps:.6f}s" calcMode="linear" '
                f'fill="freeze"/>'
                for m in range(1, n_steps))
            paths.append(f'<path d="{esc(ds[0])}" fill="none" '
                         f'stroke="{esc(color)}" '
                         f'stroke-width="{fmt_num(spec.style.stroke_width)}" '
                         f'stroke-linejoin="round" stroke-linecap="round">'
                         f'{anims}</path>')

        # 当前步名标签组（discrete opacity 逐帧切换；style.labels 或 step{k}）
        labels = self._step_labels(spec, n_steps)
        label_groups: list[str] = []
        for k, name in enumerate(labels):
            txt = svg_text(box.x0 + 6.0, box.y0 + 18.0, name,
                           size=spec.style.font_size, fill="#222222",
                           weight="bold")
            if n_steps == 1:
                label_groups.append(f"<g>{txt}</g>")
                continue
            if k < n_steps - 1:
                values, key_times, freeze = "0;1;0", \
                    f"0;{k / n_steps:.6f};{(k + 1) / n_steps:.6f}", ""
            else:
                values, key_times, freeze = "0;1", \
                    f"0;{(n_steps - 1) / n_steps:.6f}", ' fill="freeze"'
            label_groups.append(
                f'<g opacity="0">'
                f'<animate attributeName="opacity" calcMode="discrete" '
                f'values="{values}" keyTimes="{key_times}" '
                f'dur="{dur:.6f}s" repeatCount="1"{freeze}/>'
                f'{txt}</g>')

        chrome = [
            cartesian_axes(box, x_ticks, y_ticks, xlabel="freq_hz",
                           ylabel=_YLABEL[y_mode],
                           font_size=spec.style.font_size,
                           x_domain=x_dom, y_domain=(min(y_ticks),
                                                     max(y_ticks))),
            legend_row([(c, (spec.style.colors or PALETTE)[j % len(
                spec.style.colors or PALETTE)])
                for j, c in enumerate(columns)],
                box.x0, 38.0, font_size=spec.style.font_size),
        ]
        body = "".join(chrome) + "".join(paths) + "".join(label_groups)
        summaries = tuple(
            {"kind": "sparams_table", "path": t.source_path,
             "n_points": t.n_points, "columns": list(t.columns),
             "mode": "morph", "step_label": labels[si]}
            for si, t in enumerate(tables))
        return RenderPlan(frame_count=n_steps, body=body,
                          data_sources=summaries, duration_s=dur)

    @staticmethod
    def _step_labels(spec: AnimationSpec, n: int) -> list[str]:
        labels = spec.style.labels
        if labels is not None:
            if len(labels) != n:
                raise AnimationSpecError(
                    f"style.labels 数量 {len(labels)} != 源数量 {n}")
            return list(labels)
        return [f"step{k}" for k in range(n)]
