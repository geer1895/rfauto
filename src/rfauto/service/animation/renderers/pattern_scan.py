"""pattern_scan 渲染器——2D 切面方向图随频率/俯仰步扫描（批 3 图型⑩）。

动画语义：帧 k=显示第 k 幅切面——逐帧组 ``opacity`` SMIL **discrete 切换**
（同 field_heatmap"逐帧替换"语义：同屏恰一幅切面，扫描感=切面序列轮替）。

**极坐标几何与 dB 径向映射（声明式，独立复算锚在测试；画幅内接方映射同
smith_trajectory 先例）**：

- 圆心/半径：``R = max(10, min(box_w, box_h)/2 − 18)``（外圈标签余量），
  ``cx = MARGIN_L + box_w/2``、``cy = MARGIN_T + box_h/2``；
- **dB→径向归一**：``r_norm(db) = clamp((db − (db_max − DR))/DR, 0, 1)``，
  ``DR = style.dynamic_range or 40.0``；外环（R 像素）↔ 数据全局最大 dB
  （**全部切面**取 max——跨帧可比色阶/半径），内环 0 像素 ↔ 最大值−DR；
  超出动态范围的点截断到端点（不外推不静默）；
- 点映射：``px = cx + r_norm·R·cos(θ)``、``py = cy − r_norm·R·sin(θ)``
  （θ=弧度自度数；0°=+x 轴，逆时针为正，SVG y 翻转由负号承载）；
- 网格环：j=0..4 共 5 环，电平 ``db_max − j·(DR/4)``，半径
  ``radial_norm(电平)·R``（环标签=fmt_num(电平)）；角向辐条每 30° 一根
  （固定几何）；0/90/180/270 方向标签在 ``1.06R`` 外推位（smith 先例）；
- 闭合规则（声明式）：切面角跨度 ≥350° 且首末角差 >1e-9 时补首点闭合
  （显示完整性补全，零数值改写）。

切面标签（确定性派生）：``freq_hz`` 有 → ``f={fmt_num} Hz``；否则
``phi_deg`` 有 → ``phi={fmt_num} deg``；否则位置回退 ``cut {k+1}``。
数据源：单 source kind=``nf2ff_cut``（loaders.load_nf2ff_cut 契约）。
"""

from __future__ import annotations

import math

from rfauto.service.animation.loaders import (
    PatternCut,
    PatternCutSeries,
    load_nf2ff_cut,
)
from rfauto.service.animation.renderers.base import (
    PALETTE,
    AnimRenderer,
    RenderPlan,
    esc,
    fmt_num,
    register_anim_renderer,
    svg_text,
)
from rfauto.service.animation.spec import AnimationSpec, AnimationSpecError

__all__ = ["PatternScanRenderer", "cut_label", "is_closed_loop", "radial_norm"]

_CHART_TYPE = "pattern_scan"

#: 缺省径向 dB 跨度（style.dynamic_range 覆盖）
DEFAULT_DYNAMIC_RANGE_DB = 40.0

#: 网格环数（含外环；电平=最大值−j·DR/4）
N_RINGS = 5

#: 辐条步进（度；固定几何）
SPOKE_STEP_DEG = 30.0

#: 方向标签外推系数（smith 1.06 先例同值）
DIR_LABEL_R = 1.06

#: 闭合判定：角跨度阈值（度）
CLOSED_SPAN_DEG = 350.0


def radial_norm(db: float, db_max: float, dynamic_range_db: float) -> float:
    """dB 值 → [0,1] 径向归一（声明式：外环=db_max、内环=db_max−DR）。

    越界截断到端点（不外推）；``dynamic_range_db`` 须 >0（spec gt 守卫）。
    """
    floor = db_max - dynamic_range_db
    return min(1.0, max(0.0, (db - floor) / dynamic_range_db))


def is_closed_loop(theta_deg: list[float] | tuple[float, ...]) -> bool:
    """闭合判定（声明式）：角跨度 ≥350° 且首末角差 >1e-9。"""
    span = max(theta_deg) - min(theta_deg)
    return span >= CLOSED_SPAN_DEG and abs(theta_deg[0] - theta_deg[-1]) > 1e-9


def cut_label(cut: PatternCut, index: int) -> str:
    """切面标签确定性派生：freq_hz > phi_deg > 位置回退（docstring 声明）。"""
    if cut.freq_hz is not None:
        return f"f={fmt_num(cut.freq_hz)} Hz"
    if cut.phi_deg is not None:
        return f"phi={fmt_num(cut.phi_deg)} deg"
    return f"cut {index + 1}"


@register_anim_renderer(_CHART_TYPE)
class PatternScanRenderer(AnimRenderer):
    """方向图扫描渲染器（单 nf2ff_cut 源，逐帧切换切面）。"""

    chart_type = _CHART_TYPE

    # ── 主入口 ────────────────────────────────────────────────────────────
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        sources = spec.resolve_sources()
        if len(sources) != 1:
            raise AnimationSpecError(
                f"{_CHART_TYPE} 是单源图型（收到 {len(sources)} 个源）")
        if sources[0].kind != "nf2ff_cut":
            raise AnimationSpecError(
                f"{_CHART_TYPE} 数据源 kind 须为 nf2ff_cut（收到 "
                f"{sources[0].kind!r}）——远场切面归本图型，S 参数源归 "
                "sparam_evolution/smith_trajectory")
        data: PatternCutSeries = load_nf2ff_cut(sources[0].path)
        return self._plan(spec, data)

    # ── 几何面 ────────────────────────────────────────────────────────────
    @staticmethod
    def _geometry(spec: AnimationSpec) -> tuple[float, float, float]:
        """→ (cx, cy, R px)（画幅内接方映射；smith _geometry 同式）。"""
        box_w = spec.canvas.width - 64 - 28
        box_h = spec.canvas.height - 48 - 52
        radius = max(10.0, min(box_w, box_h) / 2.0 - 18.0)
        cx = 64 + box_w / 2.0
        cy = 48 + box_h / 2.0
        return cx, cy, radius

    # ── 渲染面 ────────────────────────────────────────────────────────────
    def _plan(self, spec: AnimationSpec, data: PatternCutSeries) -> RenderPlan:
        n = data.n_cuts
        cx, cy, radius = self._geometry(spec)
        dr = (spec.style.dynamic_range
              if spec.style.dynamic_range is not None
              else DEFAULT_DYNAMIC_RANGE_DB)
        db_max = max(v for cut in data.cuts for v in cut.db)
        color = spec.style.colors[0] if spec.style.colors else PALETTE[0]
        dur = self.duration_for(spec, n)
        labels = [cut_label(cut, k) for k, cut in enumerate(data.cuts)]

        out: list[str] = [self._grid(spec, cx, cy, radius, db_max, dr)]
        for k, cut in enumerate(data.cuts):
            group = self._cut_group(spec, cut, k, n, labels[k], cx, cy,
                                    radius, db_max, dr, color)
            if n == 1:
                out.append(f"<g>{group}</g>")
                continue
            if k < n - 1:
                values, key_times, freeze = "0;1;0", \
                    f"0;{k / n:.6f};{(k + 1) / n:.6f}", ""
            else:
                values, key_times, freeze = "0;1", \
                    f"0;{(n - 1) / n:.6f}", ' fill="freeze"'
            out.append(f'<g opacity="0">'
                       f'<animate attributeName="opacity" calcMode="discrete" '
                       f'values="{values}" keyTimes="{key_times}" '
                       f'dur="{dur:.6f}s" repeatCount="1"{freeze}/>'
                       f'{group}</g>')
        body = "".join(out)
        summary = {"kind": "nf2ff_cut", "path": data.source_path,
                   "n_cuts": n, "db_max": fmt_num(db_max),
                   "dynamic_range_db": fmt_num(dr),
                   "labels": labels}
        return RenderPlan(frame_count=n, body=body, data_sources=(summary,),
                          duration_s=dur)

    def _grid(self, spec: AnimationSpec, cx: float, cy: float, radius: float,
              db_max: float, dr: float) -> str:
        """网格环（电平=最大值−j·DR/4）+30° 辐条+方向标签（固定几何）。"""
        fs = max(8, spec.style.font_size - 4)
        parts: list[str] = []
        for j in range(N_RINGS):
            level = db_max - j * dr / (N_RINGS - 1)
            r_px = radial_norm(level, db_max, dr) * radius
            parts.append(f'<circle cx="{fmt_num(cx)}" cy="{fmt_num(cy)}" '
                         f'r="{fmt_num(r_px)}" fill="none" stroke="#bbbbbb" '
                         f'stroke-width="0.7"/>')
            parts.append(svg_text(cx, cy - r_px - 3.0, fmt_num(level),
                                  size=fs, anchor="middle", fill="#888888"))
        for deg in range(0, 360, int(SPOKE_STEP_DEG)):
            a = math.radians(deg)
            parts.append(f'<line x1="{fmt_num(cx)}" y1="{fmt_num(cy)}" '
                         f'x2="{fmt_num(cx + radius * math.cos(a))}" '
                         f'y2="{fmt_num(cy - radius * math.sin(a))}" '
                         f'stroke="#dddddd" stroke-width="0.6"/>')
        for deg, name in ((0, "0"), (90, "90"), (180, "180"), (270, "270")):
            a = math.radians(deg)
            parts.append(svg_text(cx + radius * DIR_LABEL_R * math.cos(a),
                                  cy - radius * DIR_LABEL_R * math.sin(a)
                                  + fs * 0.35, name, size=fs,
                                  anchor="middle", fill="#888888"))
        return "".join(parts)

    def _cut_group(self, spec: AnimationSpec, cut: PatternCut, k: int, n: int,
                   label: str, cx: float, cy: float, radius: float,
                   db_max: float, dr: float, color: str) -> str:
        """切面 k 的折线组（含声明式闭合）+帧计数标签（显式 x/y）。"""
        pts: list[tuple[float, float]] = []
        for t, db in zip(cut.theta_deg, cut.db, strict=True):
            r = radial_norm(db, db_max, dr) * radius
            a = math.radians(t)
            pts.append((cx + r * math.cos(a), cy - r * math.sin(a)))
        if is_closed_loop(cut.theta_deg):
            pts.append(pts[0])
        pts_txt = " ".join(f"{fmt_num(x)},{fmt_num(y)}" for x, y in pts)
        parts = [f'<polyline points="{pts_txt}" fill="none" '
                 f'stroke="{esc(color)}" '
                 f'stroke-width="{fmt_num(spec.style.stroke_width)}" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>']
        parts.append(svg_text(cx - radius, cy - radius - 10.0,
                              f"cut {k + 1}/{n} [{label}]",
                              size=spec.style.font_size, fill="#222222",
                              weight="bold"))
        return "".join(parts)
