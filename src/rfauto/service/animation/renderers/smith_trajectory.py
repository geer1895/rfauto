"""smith_trajectory 渲染器——Smith 圆图匹配轨迹逐点演进（T-Q3 批 1 图型②）。

动画语义：帧 k=轨迹第 k 点点亮（``<set opacity>`` 逐点计时）+整条轨迹折线
stroke-dash 匀速揭示（pathLength 归一，弧长口径——docstring 声明的显示变
换）；参考网格=Γ 单位圆+常数电阻圆+常数电抗弧（解析几何，clip 到单位圆）。

Smith 投影数学（纯解析，零随机零依赖）：

- Γ 平面即 Smith 图面：数据 S 参数/锚点 (re, im) 直接落 Γ 平面（Z0 归一基）；
- 阻抗读数：z = (1+Γ)/(1−Γ)（Γ→归一化阻抗，仅供 docstring 说明，不画）；
- 网格正映射：归一化阻抗 z = r + jx → Γ = (z−1)/(z+1)：
  - 常数 r 圆：圆心 (r/(1+r), 0)、半径 1/(1+r)（r>0；r=0 即单位圆本体）；
  - 常数 x 圆：圆心 (1, 1/x)、半径 1/|x|（x≠0），与单位圆交点
    Γ = ((x²−1)/(x²+1), 2x/(x²+1))（x 标签锚点，上感性下容性）。

数据源：sparams_csv/snip（单列轨迹，多列→AnimationSpecError 带指引）或
anchor_json（``{"points":[{"re","im"},...]}``）。|Γ|>1 数据点照原样绘制
（超出单位圆部分被视图裁剪，warnings 如实提示——零数据改写）。
"""

from __future__ import annotations

import math

from rfauto.service.animation.loaders import (
    AnimationDataError,
    load_anchor_json,
    load_snip,
    load_sparams_csv,
)
from rfauto.service.animation.renderers.base import (
    AnimRenderer,
    RenderPlan,
    esc,
    fmt_num,
    legend_row,
    register_anim_renderer,
    svg_text,
)
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    SourceSpec,
)

__all__ = ["SmithTrajectoryRenderer"]

_CHART_TYPE = "smith_trajectory"

#: 缺省参考网格（style.grid_r/grid_x 覆盖；Smith 图惯例档）
DEFAULT_GRID_R = (0.2, 0.5, 1.0, 2.0, 5.0)
DEFAULT_GRID_X = (-5.0, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 5.0)


def gamma_of_impedance(r: float, x: float) -> tuple[float, float]:
    """z = r + jx → Γ = (z−1)/(z+1) 的 (re, im)（解析式；x≠−1 前提）。"""
    den = (r + 1.0) ** 2 + x * x
    re = (r * r + x * x - 1.0) / den
    im = 2.0 * x / den
    return re, im


@register_anim_renderer(_CHART_TYPE)
class SmithTrajectoryRenderer(AnimRenderer):
    """Smith 圆图匹配轨迹渲染器（单轨迹逐点演进）。"""

    chart_type = _CHART_TYPE

    # ── 数据面 ────────────────────────────────────────────────────────────
    def _trajectory(self, src: SourceSpec) -> tuple[list[tuple[float, float]],
                                                    str, list[str]]:
        """源声明 → (Γ 点列, 图例名, 数据摘要 dict 序列化预留键值)。"""
        if src.kind in ("sparams_csv", "snip"):
            columns = src.columns or ["S11"]
            if len(columns) != 1:
                raise AnimationSpecError(
                    f"{_CHART_TYPE} 一次只画一条轨迹：columns 须恰一列"
                    f"（收到 {sorted(set(columns))}）——多轨迹需求请拆多 spec")
            if src.kind == "sparams_csv":
                table = load_sparams_csv(src.path, columns=columns)
            else:
                table = load_snip(src.path, columns=columns, ports=src.ports)
            col = table.columns[0]
            pts = [(z.real, z.imag) for z in table.series[col]]
            return pts, col, [{"kind": "sparams_table", "path": table.source_path,
                               "n_points": table.n_points, "columns": [col]}]
        if src.kind == "anchor_json":
            obj = load_anchor_json(src.path)
            raw = obj.get("points")
            if not isinstance(raw, list) or not raw:
                raise AnimationDataError(
                    f"{src.path} 缺非空 points 数组——anchor_json 的 smith 契约="
                    "``{'points':[{'re','im'},...]}``（匹配轨迹锚点导出）")
            pts: list[tuple[float, float]] = []
            for k, item in enumerate(raw):
                if not isinstance(item, dict) or "re" not in item or "im" not in item:
                    raise AnimationDataError(
                        f"{src.path} points[{k}] 须为 {{'re','im'}} dict"
                        f"（收到 {type(item).__name__}）")
                re_v, im_v = float(item["re"]), float(item["im"])
                if not (math.isfinite(re_v) and math.isfinite(im_v)):
                    raise AnimationDataError(
                        f"{src.path} points[{k}] 非有限数值——残缺数据显式拒绝")
                pts.append((re_v, im_v))
            return pts, "trajectory", [{"kind": "anchor_json", "path": src.path,
                                        "n_points": len(pts)}]
        raise AnimationSpecError(
            f"{_CHART_TYPE} 数据源 kind 须为 sparams_csv|snip|anchor_json"
            f"（收到 {src.kind!r}）——trials 归 param_race")

    # ── 几何面 ────────────────────────────────────────────────────────────
    @staticmethod
    def _geometry(spec: AnimationSpec) -> tuple[float, float, float]:
        """→ (圆心 px, 圆心 py, 单位圆半径 px)（画幅内接正方形居中）。

        映射契约（docstring 钉死）：Γ=1（单位圆边界）↔ 距圆心 R 像素，
        即 px = cx + Re(Γ)·R、py = cy − Im(Γ)·R——单位圆绘制半径与数据
        映射距离同源（测试按本式独立复算锚定）。
        """
        box_w = spec.canvas.width - 64 - 28
        box_h = spec.canvas.height - 48 - 52
        radius = max(10.0, min(box_w, box_h) / 2.0 - 18.0)  # 外圈 x 标签余量
        cx = 64 + box_w / 2.0
        cy = 48 + box_h / 2.0
        return cx, cy, radius

    def _grid(self, spec: AnimationSpec, cx: float, cy: float,
              radius: float) -> str:
        """Γ 单位圆+常数 r 圆+常数 x 弧+刻度标签（解析几何；radius=Γ=1 像素距）。"""
        grid_r = tuple(spec.style.grid_r) if spec.style.grid_r else DEFAULT_GRID_R
        grid_x = tuple(spec.style.grid_x) if spec.style.grid_x else DEFAULT_GRID_X
        if any(r <= 0 for r in grid_r):
            raise AnimationSpecError(
                f"style.grid_r 须全为正数（r=0 即单位圆本体；收到 {grid_r}）")
        if any(x == 0 for x in grid_x):
            raise AnimationSpecError(
                "style.grid_x 不得含 0（x=0 即实轴本体）")
        parts: list[str] = []
        # 单位圆边界+实轴
        parts.append(f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(cy)}" '
                     f'r="{fmt_num(radius)}" fill="none" stroke="#444444" '
                     f'stroke-width="1.2"/>')
        parts.append(f'<line x1="{fmt_num(cx - radius)}" y1="{fmt_num(cy)}" '
                     f'x2="{fmt_num(cx + radius)}" y2="{fmt_num(cy)}" '
                     f'stroke="#888888" stroke-width="0.8"/>')
        # 常数 r 圆（单位圆内整圆，无需裁剪；圆心 r/(1+r)、半径 1/(1+r)）
        for r in sorted(grid_r):
            parts.append(f'<circle cx="{fmt_num(cx + (r / (1.0 + r)) * radius)}" '
                         f'cy="{fmt_num(cy)}" '
                         f'r="{fmt_num(radius / (1.0 + r))}" fill="none" '
                         f'stroke="#bbbbbb" stroke-width="0.7"/>')
            parts.append(svg_text(cx + (r / (1.0 + r)) * radius, cy + 12.0,
                                  fmt_num(r), size=max(8, spec.style.font_size - 4),
                                  anchor="middle", fill="#888888"))
        # 常数 x 圆（圆心 (1, 1/x)，超出单位圆部分裁剪）
        parts.append('<clipPath id="smith_unit">'
                     f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(cy)}" '
                     f'r="{fmt_num(radius)}"/></clipPath>')
        for x in sorted(grid_x):
            ccy = cy - radius / x
            cr = abs(radius / x)
            parts.append(f'<g clip-path="url(#smith_unit)">'
                         f'<circle cx="{fmt_num(cx + radius)}" cy="{fmt_num(ccy)}" '
                         f'r="{fmt_num(cr)}" fill="none" stroke="#bbbbbb" '
                         f'stroke-width="0.7"/></g>')
            # x 标签=该圆与单位圆交点（解析），沿径向外推 6%
            gx = (x * x - 1.0) / (x * x + 1.0)
            gy = 2.0 * x / (x * x + 1.0)
            lx, ly = cx + gx * radius * 1.06, cy - gy * radius * 1.06
            label = ("j" + fmt_num(abs(x))) if x > 0 else ("-j" + fmt_num(abs(x)))
            parts.append(svg_text(lx, ly, label,
                                  size=max(8, spec.style.font_size - 4),
                                  anchor="middle", fill="#888888"))
        return "".join(parts)

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）——"
                "多源对比图型用 fit_compare/param_race")
        pts, legend_name, summaries = self._trajectory(sources[0])
        n = len(pts)
        cx, cy, radius = self._geometry(spec)
        dur = self.duration_for(spec, n)

        warnings: list[str] = []
        out = [self._grid(spec, cx, cy, radius)]
        out.append(legend_row([(legend_name, spec.style.colors[0]
                                if spec.style.colors else "#1f77b4")],
                              64.0, 38.0, font_size=spec.style.font_size))
        # 折线（整轨迹）+dash 匀速揭示（pathLength=1 归一；animate 为
        # polyline 子元素——SMIL 动画默认靶向父元素）
        line_pts = [(cx + u * radius, cy - v * radius) for u, v in pts]
        color_line = spec.style.colors[0] if spec.style.colors else "#1f77b4"
        pts_txt = " ".join(f"{fmt_num(x)},{fmt_num(y)}" for x, y in line_pts)
        out.append('<g clip-path="url(#smith_unit)">'
                   f'<polyline points="{pts_txt}" fill="none" '
                   f'stroke="{esc(color_line)}" '
                   f'stroke-width="{fmt_num(spec.style.stroke_width)}" '
                   f'stroke-linejoin="round" pathLength="1" '
                   f'stroke-dasharray="1" stroke-dashoffset="1">'
                   '<animate attributeName="stroke-dashoffset" from="1" to="0" '
                   f'dur="{dur:.6f}s" repeatCount="1" fill="freeze"/>'
                   "</polyline></g>")
        # 逐点标记（<set opacity> 逐帧点亮；k=0 帧起点即亮）
        marker_r = max(2.0, spec.style.font_size / 5.0)
        color = spec.style.colors[0] if spec.style.colors else "#d62728"
        for k, (px, py) in enumerate(line_pts):
            out.append(f'<circle cx="{fmt_num(px)}" cy="{fmt_num(py)}" '
                       f'r="{fmt_num(marker_r)}" fill="{esc(color)}" '
                       f'opacity="0">'
                       f'<set attributeName="opacity" to="1" '
                       f'begin="{k * dur / n:.6f}s"/></circle>')
        for k, (u, v) in enumerate(pts):
            if math.hypot(u, v) > 1.0 + 1e-9:
                warnings.append(
                    f"数据点 {k} |Γ|={math.hypot(u, v):.6g}>1（有源性判据外）"
                    "——照数据原样绘制，超出单位圆部分被视图裁剪")
                break  # 首个即代表存在性，不刷屏
        body = "".join(out)
        return RenderPlan(frame_count=n, body=body,
                          data_sources=tuple(dict(s) for s in summaries),
                          duration_s=dur, warnings=tuple(warnings))
