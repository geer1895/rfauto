"""field_heatmap 渲染器——场分布热力逐帧演进（T-Q3 批 2 图型⑤，Q-W2-2 席）。

动画语义（spec docstring 决策②清单第 5 项）：帧 k=显示第 k 帧场分布——
逐帧组 ``opacity`` SMIL **discrete 切换**（values="0;1;0" keyTimes 三点式，
帧 k 仅在 ``[k/N,(k+1)/N)`` 可见，末帧 freeze 保持——同屏恰一帧，非累计叠
加；与批 1 steps_reveal 的"逐步点亮并保留"语义不同，此处是"逐帧替换"）。

绘制面（几何布局，非数据改写）：

- 数据网格 ``values[ny][nx]`` → ny×nx 个 cell rect 填色（行 0=顶部；
  cell 均分热区——cell 尺寸是几何布局量，不由数据数值派生）；
- 颜色=内建色标映射 :func:`ramp_color`（style.colormap，None=``iron``），
  t=(v−vmin)/(vmax−vmin) 归一（vmin/vmax=**全部帧**全局数据域——跨帧可比
  色阶；vmax==vmin 退化域 t=0.5）；t 只做线性归一，数值本身零改写；
- 色标条（style.colorbar，None=画）：竖向 linearGradient（16 等分采样内建
  ramp）+ 刻度=nice_ticks(全局数据域)（色标数值=数据域，任务书钉死）；
- 文本：帧计数 ``frame k/N``（位置量，非数据）；axes 透传中的
  ``xlabel``/``ylabel``（若为字符串）按直角坐标惯例位绘制。

数据源：单 source kind=``field_dump``（loaders.load_field_frames 契约；
缺帧/非矩形/非有限显式报错）。meta/axes 仅透传（进数据摘要），渲染零算术
改写。同 spec 双跑逐字节同（禁 datetime/dict 迭代序依赖）。
"""

from __future__ import annotations

from rfauto.service.animation.loaders import FieldFrame, FieldFrames, load_field_frames
from rfauto.service.animation.renderers.base import (
    AnimRenderer,
    PlotBox,
    RenderPlan,
    fmt_num,
    nice_ticks,
    register_anim_renderer,
    svg_text,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["Colormaps", "FieldHeatmapRenderer", "ramp_color"]

_CHART_TYPE = "field_heatmap"

#: 色标条几何常量（px；bar 宽/与热区间距/刻度线长/标签余量——布局确定性）
CB_WIDTH = 14.0
CB_GAP = 12.0
CB_TICK_LEN = 4.0
CB_LABEL_PAD = 24.0

#: linearGradient 采样数（0..1 等分；确定性）
CB_STOPS = 16


#: 内建色标（名称 → (pos,(r,g,b)) 升序 stop 表；固定字面量零依赖）
Colormaps: dict[str, tuple[tuple[float, tuple[int, int, int]], ...]] = {
    "iron": (
        (0.00, (0, 0, 0)),
        (0.25, (80, 0, 80)),
        (0.50, (200, 40, 40)),
        (0.75, (255, 160, 0)),
        (1.00, (255, 255, 220)),
    ),
    "grayscale": (
        (0.00, (0, 0, 0)),
        (1.00, (255, 255, 255)),
    ),
    "coolwarm": (
        (0.00, (59, 76, 192)),
        (0.50, (221, 221, 221)),
        (1.00, (180, 4, 38)),
    ),
}


def ramp_color(name: str, t: float) -> str:
    """t∈[0,1] → 内建色标 hex（分段线性插值；越界截断到端点 stop）。

    确定性：查 :data:`Colormaps` 固定 stop 表线性插值（未知名称 KeyError=
    编程错误，调用方先经 spec Literal 校验）。
    """
    stops = Colormaps[name]
    tc = min(1.0, max(0.0, t))
    for k in range(len(stops) - 1):
        p0, c0 = stops[k]
        p1, c1 = stops[k + 1]
        if tc <= p1:
            frac = 0.0 if p1 <= p0 else (tc - p0) / (p1 - p0)
            rgb = tuple(round(c0[j] + (c1[j] - c0[j]) * frac)
                        for j in range(3))
            return "#{:02x}{:02x}{:02x}".format(*rgb)
    return "#{:02x}{:02x}{:02x}".format(*stops[-1][1])


@register_anim_renderer(_CHART_TYPE)
class FieldHeatmapRenderer(AnimRenderer):
    """场分布热力逐帧演进渲染器（单 field_dump 源，逐帧替换语义）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）——"
                "多源对比图型用 before_after/fit_compare")
        if sources[0].kind != "field_dump":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 field_dump（收到 "
                f"{sources[0].kind!r}）——sparams 源归 sparam_evolution/"
                "before_after/vswr_history")
        data: FieldFrames = load_field_frames(sources[0].path)
        return self._plan(spec, data)

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, data: FieldFrames) -> RenderPlan:
        n = data.n_frames
        vmin, vmax = self._domain(data)
        colormap = spec.style.colormap or "iron"
        box = PlotBox.from_canvas(spec.canvas.width, spec.canvas.height)
        draw_bar = spec.style.colorbar is not False
        hm_w = box.w - (CB_GAP + CB_WIDTH + CB_LABEL_PAD) if draw_bar else box.w
        dur = self.duration_for(spec, n)

        out: list[str] = []
        if draw_bar:
            out.append(self._colorbar(spec, box, hm_w, vmin, vmax, colormap))
        out.append(self._axes_labels(spec, box, hm_w, data))
        for k, frame in enumerate(data.frames):
            out.append(self._frame_group(spec, frame, k, n, box, hm_w,
                                         vmin, vmax, colormap, dur))
        body = "".join(out)
        summary = {"kind": "field_dump", "path": data.source_path,
                   "n_frames": n, "n_rows": data.frames[0].n_rows,
                   "n_cols": data.frames[0].n_cols,
                   "value_min": fmt_num(vmin), "value_max": fmt_num(vmax),
                   "colormap": colormap,
                   "axes": dict(sorted(data.axes.items())) if data.axes else {}}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)

    @staticmethod
    def _domain(data: FieldFrames) -> tuple[float, float]:
        """全局数据域（全部帧 min/max；加载面已挡非有限）。"""
        vals = [v for frame in data.frames for row in frame.values for v in row]
        return min(vals), max(vals)

    @staticmethod
    def _cell_fill(value: float, vmin: float, vmax: float, colormap: str) -> str:
        """数值 → hex 填色（线性归一；退化域 t=0.5——零数值改写）。"""
        t = 0.5 if vmax <= vmin else (value - vmin) / (vmax - vmin)
        return ramp_color(colormap, t)

    def _frame_group(self, spec: AnimationSpec, frame: FieldFrame, k: int,
                     n: int, box: PlotBox, hm_w: float, vmin: float,
                     vmax: float, colormap: str, dur: float) -> str:
        """帧 k 的 ny×nx cell rect 组+帧计数（discrete opacity 切换件）。"""
        ny, nx = frame.n_rows, frame.n_cols
        cw = hm_w / nx
        ch = box.h / ny
        parts: list[str] = []
        for ri, row in enumerate(frame.values):
            y = box.y0 + box.h - (ri + 1) * ch
            for ci, v in enumerate(row):
                x = box.x0 + ci * cw
                parts.append(
                    f'<rect x="{fmt_num(x)}" y="{fmt_num(y)}" '
                    f'width="{fmt_num(cw)}" height="{fmt_num(ch)}" '
                    f'fill="{self._cell_fill(v, vmin, vmax, colormap)}"/>')
        parts.append(svg_text(box.x0 + 6.0, box.y0 + 18.0,
                              f"frame {k + 1}/{n}",
                              size=spec.style.font_size, fill="#222222",
                              weight="bold"))
        group = "".join(parts)
        if n == 1:
            return f"<g>{group}</g>"
        if k < n - 1:
            values = "0;1;0"
            key_times = f"0;{k / n:.6f};{(k + 1) / n:.6f}"
            freeze = ""
        else:
            values = "0;1"
            key_times = f"0;{(n - 1) / n:.6f}"
            freeze = ' fill="freeze"'
        return (f'<g opacity="0">'
                f'<animate attributeName="opacity" calcMode="discrete" '
                f'values="{values}" keyTimes="{key_times}" '
                f'dur="{dur:.6f}s" repeatCount="1"{freeze}/>'
                f'{group}</g>')

    def _colorbar(self, spec: AnimationSpec, box: PlotBox, hm_w: float,
                  vmin: float, vmax: float, colormap: str) -> str:
        """竖向色标条（gradient stops=内建 ramp 等分采样；刻度=数据域 nice_ticks）。"""
        bar_x = box.x0 + hm_w + CB_GAP
        parts: list[str] = [
            '<defs><linearGradient id="cb_grad" x1="0" y1="1" x2="0" y2="0">']
        for k in range(CB_STOPS):
            t = k / (CB_STOPS - 1)
            parts.append(f'<stop offset="{t:.6f}" stop-color='
                         f'"{ramp_color(colormap, t)}"/>')
        parts.append("</linearGradient></defs>")
        parts.append(f'<rect x="{fmt_num(bar_x)}" y="{fmt_num(box.y0)}" '
                     f'width="{fmt_num(CB_WIDTH)}" height="{fmt_num(box.h)}" '
                     f'fill="url(#cb_grad)" stroke="#999999" '
                     f'stroke-width="0.8"/>')
        span = vmax - vmin
        ticks = nice_ticks(vmin, vmax) if span > 0 else [vmin]
        label_x = bar_x + CB_WIDTH + CB_TICK_LEN + 2.0
        for t in ticks:
            frac = 0.5 if span <= 0 else (t - vmin) / span
            ty = box.y0 + box.h - frac * box.h
            parts.append(f'<line x1="{fmt_num(bar_x + CB_WIDTH)}" '
                         f'y1="{fmt_num(ty)}" '
                         f'x2="{fmt_num(bar_x + CB_WIDTH + CB_TICK_LEN)}" '
                         f'y2="{fmt_num(ty)}" stroke="#666666" '
                         f'stroke-width="1"/>')
            parts.append(svg_text(label_x, ty + spec.style.font_size * 0.35,
                                  fmt_num(t), size=spec.style.font_size - 2,
                                  fill="#555555"))
        if spec.style.colorbar_label:
            parts.append(svg_text(bar_x + CB_WIDTH / 2.0, box.y0 - 6.0,
                                  spec.style.colorbar_label,
                                  size=spec.style.font_size - 1,
                                  anchor="middle", fill="#333333"))
        return "".join(parts)

    @staticmethod
    def _axes_labels(spec: AnimationSpec, box: PlotBox, hm_w: float,
                     data: FieldFrames) -> str:
        """axes 透传 xlabel/ylabel（字符串才画；位置=直角坐标惯例位）。"""
        parts: list[str] = []
        xlabel = data.axes.get("xlabel")
        ylabel = data.axes.get("ylabel")
        if isinstance(xlabel, str) and xlabel:
            parts.append(svg_text(box.x0 + hm_w / 2.0,
                                  box.y0 + box.h + spec.style.font_size * 1.6,
                                  xlabel, size=spec.style.font_size,
                                  anchor="middle", fill="#333333"))
        if isinstance(ylabel, str) and ylabel:
            parts.append(svg_text(16, box.y0 + box.h / 2.0, ylabel,
                                  size=spec.style.font_size, anchor="middle",
                                  fill="#333333"))
        return "".join(parts)
