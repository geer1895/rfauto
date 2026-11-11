"""动图渲染器基类+注册表（T-Q3 批 1）——规则 3 基类+注册表模式。

照 EMSolverAdapter/EMSolverRegistry 先例：:class:`AnimRenderer` 抽象基类
定义统一接口（``chart_type`` 类键 + :meth:`build_plan`），每个图型是独立
模块、import 期经 :func:`register_anim_renderer` 装饰器自注册；消费面走
:func:`get_anim_renderer`（未知键显式报错，带可用键清单）。

注册表底座=rfauto.core.registry_kit.RegistryKit（R1 T6 统一脚手架；
allow_overwrite=False——重名注册视为编程错误）。

本模块同时收敛 SVG 手写件公共件（后续 12 图型直接消费，不再各写一遍）：

- 几何底盘：:class:`PlotBox`（直角坐标绘图区像素框）+ 固定页边距；
- 数值件：:func:`fmt_num`（%.6g 定型）、:func:`nice_ticks`（确定性
  nice-tick 算法）、:func:`frame_edges`（逐帧揭示边界→SMIL discrete
  values/keyTimes）；
- SVG 件：:func:`esc`/:func:`svg_text`/:func:`polyline`/:func:`legend_row`/
  :func:`cartesian_axes`/:func:`discrete_clip_reveal`（逐帧 clip 揭示）/
  :func:`steps_reveal`（多步组 opacity 逐帧点亮）；
- 顶层面：:func:`render_animation`（spec dict|AnimationSpec →
  :class:`AnimationResult`，sha256 逐字节确定性钉）。

确定性铁律：禁 matplotlib/字体/平台依赖；禁 datetime.now/locale/dict 迭
代序（全部 sorted）；文本元素一律显式 x/y（自检席文字挤压检测钩子）。
"""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from rfauto.core.registry_kit import RegistryKit
from rfauto.service.animation.spec import (
    AnimationSpec,
    AnimationSpecError,
    parse_animation_spec,
)

__all__ = [
    "ANIM_RENDERER_REGISTRY",
    "AnimRenderer",
    "AnimationResult",
    "AnimationSelfCheckReport",
    "AnimationSelfCheckedResult",
    "RenderPlan",
    "SelfCheckIssue",
    "available_chart_types",
    "cartesian_axes",
    "clip_edges_midpoints",
    "detect_frame_order",
    "detect_text_overlap",
    "discrete_clip_reveal",
    "esc",
    "fmt_num",
    "frame_edges",
    "get_anim_renderer",
    "legend_row",
    "magnitude_to_y",
    "nice_ticks",
    "polyline",
    "register_anim_renderer",
    "render_animation",
    "require_common_grid",
    "run_animation_self_check",
    "steps_reveal",
    "svg_text",
    "verify_svg_structure",
]

#: 内建系列调色板（固定序；style.colors 优先，超出回退本表循环）
PALETTE: tuple[str, ...] = (
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd",
    "#ff7f0e", "#8c564b", "#e377c2", "#7f7f7f",
)

#: 直角坐标页边距（px；标题/图例/轴标签空间固定——布局确定性）
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 64, 28, 48, 52

#: SVG 字体栈（文件内容固定；像素渲染不在确定性口径内）
FONT_FAMILY = "Helvetica, Arial, sans-serif"

#: 渲染器注册表（label 进缺名错误文案；键=chart_type 字符串）
ANIM_RENDERER_REGISTRY: RegistryKit[type] = RegistryKit(
    label="动图渲染器", allow_overwrite=False)


def register_anim_renderer(chart_type: str):
    """``@register_anim_renderer("chart_type")`` —— 图型渲染器自注册装饰器。"""
    return ANIM_RENDERER_REGISTRY.register(chart_type)


def get_anim_renderer(chart_type: str) -> type[AnimRenderer]:
    """按 chart_type 取渲染器类（未知键→AnimationSpecError 带可用键清单）。"""
    if not isinstance(chart_type, str) or not chart_type:
        raise AnimationSpecError(
            f"chart_type 必须是非空字符串，收到 {chart_type!r}")
    try:
        return ANIM_RENDERER_REGISTRY.get(chart_type)
    except KeyError as exc:
        raise AnimationSpecError(
            f"未知图型 {chart_type!r}；已注册图型={available_chart_types()}"
            "（新增图型用 register_anim_renderer 注册）") from exc


def available_chart_types() -> list[str]:
    """已注册图型键（字典序——RegistryKit 缺省 sorted 口径）。"""
    return sorted(ANIM_RENDERER_REGISTRY.keys())


# ─── 数值件（确定性定型） ─────────────────────────────────────────────────────

def fmt_num(v: float) -> str:
    """float → 稳定短文本（%.6g；``-0`` 归一 ``0``；inf/nan 调用方先挡）。"""
    if v == 0:
        return "0"
    s = f"{float(v):.6g}"
    return "0" if s == "-0" else s


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """确定性 nice-tick（1/2/5×10^k 步长，覆盖 [lo,hi]；退化区间=单 tick）。"""
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ValueError(f"nice_ticks 需要有限区间，收到 [{lo}, {hi}]")
    if hi < lo:
        lo, hi = hi, lo
    span = hi - lo
    if span <= 0 or not math.isfinite(span):
        return [lo]
    raw = span / max(1, target)
    mag = 10.0 ** math.floor(math.log10(raw))
    step = mag
    for m in (1.0, 2.0, 5.0, 10.0):
        if m * mag >= raw:
            step = m * mag
            break
    start = math.ceil(lo / step - 1e-12) * step
    ticks: list[float] = []
    k = 0
    while True:
        t = start + k * step
        if t > hi + step * 1e-9:
            break
        ticks.append(t)
        k += 1
        if k > 10000:  # 防御上限（坏步长不挂死）
            break
    return ticks


def require_common_grid(grids: list[tuple[float, ...]] | tuple[tuple[float, ...], ...],
                        where: str) -> tuple[float, ...]:
    """多源 x 网格对齐守卫（等长+逐点 isclose rel 1e-9 / abs 1e-6 Hz）。

    不满足→ AnimationDataError 带同栅重采样指引（#287 家族：对拍前同栅，
    渲染器不做隐式插值）。
    """
    from rfauto.service.animation.loaders import AnimationDataError

    if not grids:
        raise AnimationDataError(f"{where} 无任何网格——不画空图")
    first = grids[0]
    n = len(first)
    for gi, g in enumerate(grids[1:], start=1):
        if len(g) != n:
            raise AnimationDataError(
                f"{where} 第 {gi} 源 x 点数 {len(g)} != 第 0 源 {n}——"
                "请先同栅重采样（渲染器不做隐式插值）")
        for k, (a, b) in enumerate(zip(first, g, strict=True)):
            if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6):
                raise AnimationDataError(
                    f"{where} 第 {gi} 源 x[{k}]={b!r} 与第 0 源 {a!r} 不同栅——"
                    "请先同栅重采样（渲染器不做隐式插值）")
    return first


def frame_edges(count: int) -> list[float]:
    """N 帧的 keyTimes（0..(N-1)/N 等分；discrete 末值自然保持到结尾）。"""
    if count < 1:
        raise ValueError("frame count 必须 ≥1")
    return [k / count for k in range(count)]


def clip_edges_midpoints(px: list[float], box: PlotBox) -> list[float]:
    """逐频点揭示边界=相邻点像素中点；末帧=全宽（discrete 揭示契约）。

    批 2 起公共化（before_after/vswr_history 及后续图型消费）；公式与批 1
    sparam_evolution/fit_compare 内联式逐位同（批 1 文件冻结不回改）。
    单点序列=全宽单帧。
    """
    n = len(px)
    if n == 0:
        raise ValueError("px 至少 1 点")
    if n == 1:
        return [box.x0 + box.w]
    edges = [(px[k] + px[k + 1]) / 2.0 for k in range(n - 1)]
    edges.append(box.x0 + box.w)
    return edges


def magnitude_to_y(values: list[complex] | tuple[complex, ...], y_mode: str, *,
                   where: str) -> list[float]:
    """复数序列 → 纵轴值（db=20*log10|S| / linear=|S|；确定性显示变换）。

    db 模式遇 |S|=0 显式报错（log 无定义，不做地板截断——零算术语义改写）；
    非有限值一律显式报错。
    """
    from rfauto.service.animation.loaders import AnimationDataError

    out: list[float] = []
    for k, z in enumerate(values):
        mag = abs(z)
        if not math.isfinite(mag):
            raise AnimationDataError(f"{where} 第 {k} 点幅值非有限——残缺数据显式拒绝")
        if y_mode == "db":
            if mag <= 0.0:
                raise AnimationDataError(
                    f"{where} 第 {k} 点 |S|=0 无法取 dB（log 无定义）——"
                    "请改 style.y_mode='linear' 或修数据源；不做地板截断")
            out.append(20.0 * math.log10(mag))
        else:
            out.append(mag)
    return out


# ─── SVG 公共件 ───────────────────────────────────────────────────────────────

def esc(s: str) -> str:
    """XML 文本转义（&<>"'；title/label 消费面强制过本函数）。"""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def svg_text(x: float, y: float, s: str, *, size: int, anchor: str = "start",
             fill: str = "#333333", weight: str = "normal",
             transform: str | None = None) -> str:
    """文本元素（**显式 x/y**——自检席文字挤压检测钩子的最低契约）。

    ``transform``（可选，Q-R3R 排版修复）：SVG transform 属性原样透传；
    缺省 None=不带属性（既有调用方输出逐字节零变化）。自检检测器消费
    ``rotate(...)`` 形态做盒旋转识别（见 :func:`_text_boxes`）；内核产出
    形态=``rotate(-90 <x> <y>)``（绕自身锚点逆时针 90°，直角坐标 ylabel
    竖排惯例）。
    """
    tattr = f' transform="{esc(transform)}"' if transform else ""
    return (f'<text x="{fmt_num(x)}" y="{fmt_num(y)}" font-size="{size}" '
            f'fill="{esc(fill)}" text-anchor="{esc(anchor)}" '
            f'font-weight="{esc(weight)}"{tattr}>{esc(s)}</text>')


def polyline(points: list[tuple[float, float]], color: str, width: float) -> str:
    """折线（空点=编程错误由调用方挡；点串 fmt_num 定型）。"""
    pts = " ".join(f"{fmt_num(x)},{fmt_num(y)}" for x, y in points)
    return (f'<polyline points="{pts}" fill="none" stroke="{esc(color)}" '
            f'stroke-width="{fmt_num(width)}" stroke-linejoin="round" '
            f'stroke-linecap="round"/>')


def legend_row(items: list[tuple[str, str]], x: float, y: float, *,
               font_size: int, gap: float = 24.0) -> str:
    """单行图例：色样线段+标签（x/y 显式；列宽=标签长度确定性估算）。"""
    out: list[str] = []
    cx = x
    char_w = font_size * 0.62
    for label, color in items:
        out.append(f'<line x1="{fmt_num(cx)}" y1="{fmt_num(y)}" '
                   f'x2="{fmt_num(cx + 18)}" y2="{fmt_num(y)}" '
                   f'stroke="{esc(color)}" stroke-width="3"/>')
        out.append(svg_text(cx + 24, y + font_size * 0.35, label,
                            size=font_size, fill="#333333"))
        cx += 24 + len(label) * char_w + gap
    return "".join(out)


@dataclass(frozen=True)
class PlotBox:
    """直角坐标绘图区（像素；canvas − 固定页边距）。"""

    x0: float
    y0: float
    w: float
    h: float

    @classmethod
    def from_canvas(cls, width: int, height: int) -> PlotBox:
        return cls(float(MARGIN_L), float(MARGIN_T),
                   float(width - MARGIN_L - MARGIN_R),
                   float(height - MARGIN_T - MARGIN_B))

    def xy(self, v: float, lo: float, hi: float, horizontal: bool = True) -> float:
        """数据值 → 像素（线性映射；退化区间=中心；零算术语义改写）。"""
        if hi <= lo:
            return (self.x0 + self.w / 2.0) if horizontal else (self.y0 + self.h / 2.0)
        frac = (v - lo) / (hi - lo)
        return (self.x0 + frac * self.w) if horizontal else (self.y0 + self.h - frac * self.h)


def cartesian_axes(box: PlotBox, x_ticks: list[float], y_ticks: list[float],
                   *, xlabel: str, ylabel: str, font_size: int,
                   x_domain: tuple[float, float],
                   y_domain: tuple[float, float]) -> str:
    """直角坐标轴+刻度（tick 文本=fmt_num(tick)；轴标签显式 x/y）。

    ylabel 竖排（Q-R3R 排版修复，声明式）：绕自身锚点 ``rotate(-90 x y)``
    逆时针 90°——横排形态的左缘越界（长标签盒 x0=16−w/2<0）与左缘 y-tick
    文本重叠（同 #122 家法 warn 证据：qw41 ex1/ex2）为内核既有排版缺陷，
    修复后盒宽=字号量级、恒在画幅内且与 tick 列（右缘 box.x0−8）脱接；
    自检检测器对 rotate 形态做盒旋转识别（:func:`_text_boxes`），不再对这些
    正确形态 warn。空串 ylabel 照旧透传渲染（空文本元素无内容，检测器
    自然跳过——既有行为零变化）。
    """
    out: list[str] = []
    out.append(f'<rect x="{fmt_num(box.x0)}" y="{fmt_num(box.y0)}" '
               f'width="{fmt_num(box.w)}" height="{fmt_num(box.h)}" '
               f'fill="none" stroke="#999999" stroke-width="1"/>')
    for t in x_ticks:
        px = box.xy(t, x_domain[0], x_domain[1], horizontal=True)
        if not box.x0 - 1e-9 <= px <= box.x0 + box.w + 1e-9:
            continue
        out.append(f'<line x1="{fmt_num(px)}" y1="{fmt_num(box.y0 + box.h)}" '
                   f'x2="{fmt_num(px)}" y2="{fmt_num(box.y0 + box.h + 4)}" '
                   f'stroke="#666666" stroke-width="1"/>')
        out.append(svg_text(px, box.y0 + box.h + 4 + font_size, fmt_num(t),
                            size=font_size - 2, anchor="middle", fill="#555555"))
    for t in y_ticks:
        py = box.xy(t, y_domain[0], y_domain[1], horizontal=False)
        if not box.y0 - 1e-9 <= py <= box.y0 + box.h + 1e-9:
            continue
        out.append(f'<line x1="{fmt_num(box.x0 - 4)}" y1="{fmt_num(py)}" '
                   f'x2="{fmt_num(box.x0)}" y2="{fmt_num(py)}" '
                   f'stroke="#666666" stroke-width="1"/>')
        out.append(svg_text(box.x0 - 8, py + font_size * 0.35, fmt_num(t),
                            size=font_size - 2, anchor="end", fill="#555555"))
    out.append(svg_text(box.x0 + box.w / 2.0, box.y0 + box.h + font_size * 2.6,
                        xlabel, size=font_size, anchor="middle", fill="#333333"))
    ylabel_y = box.y0 + box.h / 2.0
    out.append(svg_text(16, ylabel_y, ylabel, size=font_size,
                        anchor="middle", fill="#333333",
                        transform=f"rotate(-90 16 {fmt_num(ylabel_y)})"))
    return "".join(out)


def discrete_clip_reveal(clip_id: str, box: PlotBox, edges_px: list[float],
                         *, dur: float) -> str:
    """逐帧离散 clip 揭示（x 单调图型的 O(N) 逐点生长语义）。

    返回 ``(clipPath 定义, clip-path 引用属性串)`` 二元组拼好的 XML：
    ``edges_px[k]`` = 第 k 帧揭示到的 x 像素边界（frame k 起 width=edges_px[k]，
    calcMode=discrete 等分 keyTimes——帧语义=逐点，不依赖渲染器插值）。
    """
    n = len(edges_px)
    if n < 1:
        raise ValueError("edges_px 至少 1 帧")
    values = ";".join(fmt_num(e) for e in edges_px)
    key_times = ";".join(f"{t:.6f}" for t in frame_edges(n))
    rect = (f'<rect x="{fmt_num(box.x0)}" y="{fmt_num(box.y0)}" width="0" '
            f'height="{fmt_num(box.h)}">'
            f'<animate attributeName="width" calcMode="discrete" '
            f'dur="{dur:.6f}s" repeatCount="1" fill="freeze" '
            f'values="{values}" keyTimes="{key_times}"/></rect>')
    return f'<clipPath id="{esc(clip_id)}">{rect}</clipPath>'


def steps_reveal(clip_id: str, box: PlotBox, n_steps: int, *,
                 dur: float) -> tuple[str, str]:
    """多步组逐帧点亮：返回 (clip 定义, 各步 begin 时刻列表)。

    每步 `<g opacity="0">` + `<set attributeName="opacity" to="1"
    begin="t_k"/>`；t_k=k×dur/n_steps（等分；frame k=第 k 步点亮）。
    """
    if n_steps < 1:
        raise ValueError("n_steps 必须 ≥1")
    begins = [f"{k * dur / n_steps:.6f}s" for k in range(n_steps)]
    clip = (f'<clipPath id="{esc(clip_id)}">'
            f'<rect x="{fmt_num(box.x0)}" y="{fmt_num(box.y0)}" '
            f'width="{fmt_num(box.w)}" height="{fmt_num(box.h)}"/></clipPath>')
    return clip, begins


# ─── 渲染器基类与顶层面 ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class RenderPlan:
    """渲染器产出（基类负责 SVG 封装+sha256+信封）。"""

    frame_count: int
    body: str
    data_sources: tuple[dict[str, Any], ...] = ()
    duration_s: float = 0.0
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class AnimationResult:
    """render_animation 结果（svg_str 逐字节确定；sha256=同 spec 指纹）。"""

    svg_str: str
    sha256: str
    chart_type: str
    frame_count: int
    duration_s: float
    data_sources: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class AnimationSelfCheckedResult(AnimationResult):
    """self_check=True 时的结果（在 :class:`AnimationResult` 上增
    ``self_check`` 报告字段；isinstance AnimationResult 恒成立）。

    仅 ``render_animation(..., self_check=True)`` 返回本类型——缺省路径
    返回基类实例、**无** ``self_check`` 属性（既有行为零变化钉）。
    """

    self_check: AnimationSelfCheckReport = field(default_factory=lambda: _EMPTY_REPORT)


class AnimRenderer(ABC):
    """图型渲染器基类（子类实现 build_plan；chart_type=注册键类属性）。"""

    #: 注册键（子类必填；与 spec.chart_type 匹配）
    chart_type: ClassVar[str] = ""

    @abstractmethod
    def build_plan(self, spec: AnimationSpec) -> RenderPlan:
        """spec → 渲染计划（帧几何+SVG 内联 body+数据源摘要）。

        缺数据/残缺数据→ AnimationDataError（loaders）；spec 图型级违约
        （源数量/列名不合）→ AnimationSpecError——全部显式，不静默。
        """

    def duration_for(self, spec: AnimationSpec, frame_count: int) -> float:
        """帧时长归一：duration_s 显式优先，否则 frames/fps（fps 缺省 8）。"""
        if spec.animation.duration_s is not None:
            return float(spec.animation.duration_s)
        return frame_count / float(spec.animation.fps)


def _assemble_svg(spec: AnimationSpec, plan: RenderPlan, body: str) -> str:
    """SVG 封装（根+viewBox+背景+desc 溯源+body；逐字节确定）。"""
    w, h = spec.canvas.width, spec.canvas.height
    sources_txt = "; ".join(
        f"{s.get('kind', '?')}:{s.get('path', '?')}"
        f"({s.get('n_points', s.get('n_trials', '?'))} pts)"
        for s in plan.data_sources)
    desc = (f"rfauto animation chart_type={spec.chart_type} "
            f"frame_count={plan.frame_count} duration_s={plan.duration_s:.6f} "
            f"sources=[{sources_txt}]")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="{FONT_FAMILY}">\n'
        f'<desc>{esc(desc)}</desc>\n'
        f'<rect x="0" y="0" width="{w}" height="{h}" '
        f'fill="{esc(spec.style.background)}"/>\n'
        + body + "\n</svg>\n")


def render_animation(spec: AnimationSpec | dict[str, Any], *,
                     self_check: bool = False) -> AnimationResult:
    """顶层 API：spec（dict|AnimationSpec）→ :class:`AnimationResult`。

    流程：parse_animation_spec 校验 → 注册表按 chart_type 分派 →
    build_plan（加载+几何+SVG body）→ 封装+sha256。

    Args:
        spec: spec dict 或 :class:`AnimationSpec` 实例。
        self_check: 缺省 False=既有行为零变化（返回基类
            :class:`AnimationResult`，SVG 逐字节同）；True=附加自动化体检
            （:func:`run_animation_self_check`），返回
            :class:`AnimationSelfCheckedResult`（多 ``self_check`` 报告
            字段）——**SVG 输出不受开关影响**（逐字节同）。

    Raises:
        AnimationSpecError: spec 违约/未知图型/图型级源数量不合；
        AnimationDataError: 数据源缺失/残缺（带指引文案）。
    """
    parsed = parse_animation_spec(spec)
    cls = get_anim_renderer(parsed.chart_type)
    renderer = cls()
    plan = renderer.build_plan(parsed)
    body = plan.body
    if parsed.title:
        body = svg_text(parsed.canvas.width / 2.0, 26, parsed.title,
                        size=spec_title_size(parsed), anchor="middle",
                        fill="#222222", weight="bold") + body
    svg = _assemble_svg(parsed, plan, body)
    result = AnimationResult(
        svg_str=svg,
        sha256=hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        chart_type=parsed.chart_type,
        frame_count=plan.frame_count,
        duration_s=plan.duration_s,
        data_sources=plan.data_sources,
        warnings=plan.warnings,
    )
    if not self_check:
        return result
    report = run_animation_self_check(
        svg, frame_count=plan.frame_count,
        canvas_wh=(parsed.canvas.width, parsed.canvas.height))
    return AnimationSelfCheckedResult(
        svg_str=result.svg_str, sha256=result.sha256,
        chart_type=result.chart_type, frame_count=result.frame_count,
        duration_s=result.duration_s, data_sources=result.data_sources,
        warnings=result.warnings, self_check=report)


def spec_title_size(spec: AnimationSpec) -> int:
    """标题字号（比正文大 3 号，封顶 style.font_size+3≤72）。"""
    return min(72, spec.style.font_size + 3)


# ─── 自检闭环（T-Q4 Q-W4-1 席；z-skills 自检同构思想，确定性实现） ─────────────
#
# 动图产物 SVG 的自动化体检三检测器（纯函数、stdlib xml.etree、零新依赖）：
#
# - :func:`verify_svg_structure` —— 结构完整（XML 可解析/根 svg+命名空间/
#   viewBox 存在且与 width/height·期望画幅一致）——**error 级**（精确判据）；
# - :func:`detect_frame_order` —— 帧序完整性（SMIL 离散 keyTimes 单调/
#   计数一致；同父同 attributeName 的 begin 链单调；desc 声明帧数=预期
#   帧数）——**error 级**（精确判据）；
# - :func:`detect_text_overlap` —— 文字挤压检测（文本框=字符数×字号×0.62
#   **声明式估算**——同 legend_row 列宽估算口径；rotate(θ) 文本盒按 SVG
#   旋转矩阵映射取包围盒——90° 竖排 ylabel=正确排版形态不误报（Q-R3R
#   排版修复配套）；两两重叠含**帧互斥语义**
#   （逐帧替换标签任一时刻仅一帧可见，不同帧同位标签不算同屏挤压）/
#   越出画幅）——**warn 级**（估算判据有假阳性可能，不作硬门）。
#
# 汇总 :func:`run_animation_self_check` → :class:`AnimationSelfCheckReport`
# （per-issue level/kind/locator/message）；接线 :func:`render_animation` 的
# ``self_check=True`` 可选参数（缺省 False=既有行为零变化）。
#
# 帧数核对契约说明（探针实测 16 内建图型，校准记录在
# runs/aurora_q/qw41_examples/RECON_NOTES.md）：帧的 SMIL 载体随图型语义而
# 异——clip 揭示=单 animate
# values 链（sparam_evolution/param_race 等）、逐帧 opacity 切换=每帧一个
# animate（field_heatmap/pattern_scan/filter_morphing）、逐级点亮=set 组
# （nf_cascade/smith_trajectory 等，signal_flow 边/constellation_eye 眼窗
# 帧内多元素=begin 数 > 帧数）、animateTransform 平移（structure_explode，
# 层 0 偏移零免发 no-op=首帧无 begin）——故**不从 SMIL 反推帧数**，帧数
# 契约=``<desc>`` 声明 ``frame_count=N``（_assemble_svg 内建档，与
# RenderPlan.frame_count 同源）对预期值核对；SMIL 面只查精确不变式。

_SVG_NS = "http://www.w3.org/2000/svg"

#: 文本宽度估算比率（字符数×字号×本值；同 legend_row 列宽估算口径——
#: 声明式估算：Helvetica 半角经验值，CJK 全角字符实际更宽→估算偏窄=
#: 可能漏报不误报，docstring 声明的已知局限）
_CHAR_WIDTH_RATIO = 0.62

#: 文本盒纵向占比（基线 y → 上探 0.72×字号、下探 0.28×字号；视觉经验值，
#: 声明式估算口径）
_TEXT_ASCENT_RATIO = 0.72

#: 重叠判定最小交叠量（px；两轴同时超过才算重叠——边缘相接不算）
_OVERLAP_TOL_PX = 0.5

_LEVEL_WARN = "warn"
_LEVEL_ERROR = "error"


@dataclass(frozen=True)
class SelfCheckIssue:
    """单条自检问题（level=warn|error；locator=元素定位串；零语义改写）。"""

    level: str
    kind: str
    locator: str
    message: str


@dataclass(frozen=True)
class AnimationSelfCheckReport:
    """自检报告（issues 按检测器固定序：structure→frame→text）。"""

    issues: tuple[SelfCheckIssue, ...] = ()

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.level == _LEVEL_ERROR)

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.level == _LEVEL_WARN)

    @property
    def ok(self) -> bool:
        """无 error 级问题（warn 级=提示不拦路——估算判据不设硬门）。"""
        return self.n_errors == 0

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化形态（证据区 selfcheck.json 消费口径）。"""
        return {"ok": self.ok,
                "n_errors": self.n_errors,
                "n_warnings": self.n_warnings,
                "issues": [{"level": i.level, "kind": i.kind,
                            "locator": i.locator, "message": i.message}
                           for i in self.issues]}


_EMPTY_REPORT = AnimationSelfCheckReport()


def _local(tag: str) -> str:
    """ET tag → localname（命名空间无关；渲染器 SVG 带缺省命名空间）。"""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _timed_elements(root: Any) -> list[tuple[str, Any]]:
    """文档序收集定时元素 [(localname, element)]（animate/animateTransform/
    set——SMIL 三定时件；顺序=文档序=帧点亮契约序）。"""
    out: list[tuple[str, Any]] = []
    for el in root.iter():
        name = _local(el.tag)
        if name in ("animate", "animateTransform", "set"):
            out.append((name, el))
    return out


def _parse_begin_seconds(begin: str) -> float | None:
    """SMIL begin 属性 → 秒（内核口径恒 ``<f>s``；不可解析=None）。"""
    s = begin.strip()
    if s.endswith("s"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    return None


def verify_svg_structure(svg: str, *,
                         expected_canvas_wh: tuple[int, int] | None = None
                         ) -> tuple[SelfCheckIssue, ...]:
    """结构完整检测（精确判据，error 级）。

    检查项：①XML 可解析（闭标签/良构——解析失败=单 error，不抛异常）；
    ②根元素=SVG 命名空间 svg；③viewBox 存在、4 数、宽高>0；④width/height
    属性（存在时）与 viewBox 一致；⑤expected_canvas_wh 给出时与 viewBox
    一致（render_animation 接线传 spec.canvas）。
    """
    import xml.etree.ElementTree as ET

    issues: list[SelfCheckIssue] = []
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        return (SelfCheckIssue(
            level=_LEVEL_ERROR, kind="structure", locator="root",
            message=f"SVG 不可解析（XML 良构性破坏）：{exc}"),)
    if _local(root.tag) != "svg" or root.tag != f"{{{_SVG_NS}}}svg":
        issues.append(SelfCheckIssue(
            level=_LEVEL_ERROR, kind="structure", locator="root",
            message=f"根元素须为 SVG 命名空间 svg（实测 {root.tag!r}）"))
    vb = root.get("viewBox")
    if vb is None:
        issues.append(SelfCheckIssue(
            level=_LEVEL_ERROR, kind="structure", locator="root@viewBox",
            message="缺 viewBox 属性（内核契约=viewBox 与像素画幅同值，"
                    "无缩放歧义）"))
        dims: tuple[float, float] | None = None
    else:
        parts = vb.replace(",", " ").split()
        if len(parts) != 4:
            issues.append(SelfCheckIssue(
                level=_LEVEL_ERROR, kind="structure", locator="root@viewBox",
                message=f"viewBox 须 4 个数（实测 {vb!r}）"))
            dims = None
        else:
            try:
                _x0, _y0, w, h = (float(p) for p in parts)
            except ValueError:
                issues.append(SelfCheckIssue(
                    level=_LEVEL_ERROR, kind="structure",
                    locator="root@viewBox",
                    message=f"viewBox 含非数值（实测 {vb!r}）"))
                dims = None
            else:
                if w <= 0 or h <= 0:
                    issues.append(SelfCheckIssue(
                        level=_LEVEL_ERROR, kind="structure",
                        locator="root@viewBox",
                        message=f"viewBox 宽高须>0（实测 {w}x{h}）"))
                dims = (w, h)
    w_attr, h_attr = root.get("width"), root.get("height")
    if dims is not None and w_attr is not None and h_attr is not None:
        try:
            wv, hv = float(w_attr), float(h_attr)
        except ValueError:
            issues.append(SelfCheckIssue(
                level=_LEVEL_ERROR, kind="structure",
                locator="root@width,height",
                message=f"width/height 须数值（实测 {w_attr!r}x{h_attr!r}）"))
        else:
            if (wv, hv) != dims:
                issues.append(SelfCheckIssue(
                    level=_LEVEL_ERROR, kind="structure",
                    locator="root@width,height",
                    message=f"width/height {wv}x{hv} 与 viewBox {dims[0]}x"
                            f"{dims[1]} 不一致（内核契约=同值无缩放歧义）"))
    if expected_canvas_wh is not None and dims is not None and \
            (dims[0], dims[1]) != (float(expected_canvas_wh[0]),
                                   float(expected_canvas_wh[1])):
        issues.append(SelfCheckIssue(
            level=_LEVEL_ERROR, kind="structure", locator="root@viewBox",
            message=f"viewBox {dims[0]}x{dims[1]} 与 spec 画幅 "
                    f"{expected_canvas_wh[0]}x{expected_canvas_wh[1]}"
                    " 不一致"))
    return tuple(issues)


def detect_frame_order(svg: str, *,
                       expected_frames: int | None = None
                       ) -> tuple[SelfCheckIssue, ...]:
    """帧序完整性检测（精确判据，error 级）。

    检查项（SMIL 精确不变式，对 16 内建图型零假阳性——探针实测见模块头
    注释）：

    ①定时元素（animate/animateTransform/set）begin 属性可解析（内核口径
    ``<f>s``）；②离散 animate 的 keyTimes：计数与 values 一致、单调不减、
    首=0、全部∈[0,1]；③**同父同 attributeName 的 begin 链**单调不减
    （插值链/点亮链时间只前进——探针实测：filter_morphing 每列 path 各有
    一条 d 插值链，跨链文档序不单调是设计内形态，故单调性按链核对不按
    全文档序）；④帧数契约=``<desc>`` 声明 ``frame_count=N``（与 SMIL 载体
    无关的内核建档——clip 揭示/逐帧切换/点亮组/animateTransform 四载体
    探针实测差异见模块头注释），expected_frames 给出时与之核对（缺
    desc=warn：声明契约缺席，无法核对帧数）。
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return ()  # 结构归 verify_svg_structure 专责，此处免重复报
    issues: list[SelfCheckIssue] = []
    timed = _timed_elements(root)
    parent_map: dict[int, Any] = {id(c): p for p in root.iter()
                                  for c in p}
    chain_begins: dict[tuple[int, str], list[float]] = {}
    for idx, (name, el) in enumerate(timed):
        loc = f"{name}[{idx}]"
        begin = el.get("begin")
        if begin is not None:
            secs = _parse_begin_seconds(begin)
            if secs is None:
                issues.append(SelfCheckIssue(
                    level=_LEVEL_ERROR, kind="frame_begin_parse", locator=loc,
                    message=f"begin 属性不可解析（内核口径=<f>s）：{begin!r}"))
            else:
                key = (id(parent_map.get(id(el))), el.get("attributeName") or "")
                chain_begins.setdefault(key, []).append(secs)
        if name == "animate" and el.get("calcMode") == "discrete":
            values = [v for v in (el.get("values") or "").split(";")
                      if v.strip() != ""]
            kt_raw = el.get("keyTimes")
            if kt_raw is None:
                continue
            kts_raw = [k for k in kt_raw.split(";") if k.strip() != ""]
            if len(kts_raw) != len(values):
                issues.append(SelfCheckIssue(
                    level=_LEVEL_ERROR, kind="frame_keytimes_mismatch",
                    locator=loc,
                    message=f"keyTimes 计数 {len(kts_raw)} != values 计数 "
                            f"{len(values)}（SMIL discrete 契约）"))
                continue
            kts: list[float] = []
            bad = False
            for k, raw in enumerate(kts_raw):
                try:
                    kts.append(float(raw))
                except ValueError:
                    issues.append(SelfCheckIssue(
                        level=_LEVEL_ERROR, kind="frame_order", locator=loc,
                        message=f"keyTimes[{k}] 非数值：{raw!r}"))
                    bad = True
            if bad:
                continue
            if kts and kts[0] != 0.0:
                issues.append(SelfCheckIssue(
                    level=_LEVEL_ERROR, kind="frame_order", locator=loc,
                    message=f"keyTimes 首值 {kts[0]!r} != 0（离散帧契约）"))
            for k in range(1, len(kts)):
                if kts[k] < kts[k - 1]:
                    issues.append(SelfCheckIssue(
                        level=_LEVEL_ERROR, kind="frame_order", locator=loc,
                        message=f"keyTimes 非单调（[{k - 1}]={kts[k - 1]!r} >"
                                f" [{k}]={kts[k]!r}）——帧序倒退"))
            for k, t in enumerate(kts):
                if not 0.0 <= t <= 1.0:
                    issues.append(SelfCheckIssue(
                        level=_LEVEL_ERROR, kind="frame_order", locator=loc,
                        message=f"keyTimes[{k}]={t!r} 越界 [0,1]"))
    chain_keys = sorted(chain_begins, key=lambda key: (str(key[0]), key[1]))
    for chain_idx, key in enumerate(chain_keys):
        seq = chain_begins[key]
        for k in range(1, len(seq)):
            if seq[k] < seq[k - 1]:
                issues.append(SelfCheckIssue(
                    level=_LEVEL_ERROR, kind="frame_order",
                    locator=f"begin-chain[{chain_idx}]",
                    message=f"begin 链非单调（[{k - 1}]={seq[k - 1]!r}s > "
                            f"[{k}]={seq[k]!r}s；同父同 attributeName 的"
                            "点亮/插值链时间只前进）"))
    if expected_frames is not None:
        m = None
        for el in root.iter():
            if _local(el.tag) == "desc":
                m = re.search(r"frame_count=(\d+)", el.text or "")
                if m is not None:
                    break
        if m is None:
            issues.append(SelfCheckIssue(
                level=_LEVEL_WARN, kind="frame_count", locator="desc",
                message="缺 <desc> frame_count 声明（内核建档契约）——"
                        "帧数无法核对"))
        elif int(m.group(1)) != int(expected_frames):
            issues.append(SelfCheckIssue(
                level=_LEVEL_ERROR, kind="frame_count", locator="desc",
                message=f"desc 声明帧数 {m.group(1)} != 预期 {expected_frames}"))
    return tuple(issues)


def _text_visibility_windows(root: Any) -> list[list[tuple[float, float]]]:
    """文本元素（文档序，与 :func:`_text_boxes` 同序）→ 可见时间窗列表
    （归一化 [0,1]；多窗=并集语义）。

    帧互斥语义（声明式规则）：文本的最近祖先组若带离散 opacity animate
    （values 含 "1" 段）→ 文本仅在该段 keyTimes 窗口可见（field_heatmap/
    filter_morphing 的"逐帧替换"标签——不同帧同位标签**不构成同屏挤压**）；
    带 ``<set to="1" begin>`` 祖先组 → 窗口 [begin/dur_total, 1]（点亮后
    常驻——nf_cascade/signal_flow 等级联标签仍互检）。无动画祖先=常驻
    [0,1]。多约束取交集；无法解析（缺 keyTimes/dur）→ 保守回退 [0,1]
    （不放过挤压误报方向，宁多报不放过——#316 同向）。
    """
    parent_map: dict[int, Any] = {id(c): p for p in root.iter() for c in p}
    dur_total: float | None = None
    for el in root.iter():
        if _local(el.tag) == "desc" and el.text:
            m = re.search(r"duration_s=([0-9.eE+-]+)", el.text)
            if m is not None:
                try:
                    dur_total = float(m.group(1))
                except ValueError:
                    dur_total = None
            break
    windows: list[list[tuple[float, float]]] = []
    for el in root.iter():
        if _local(el.tag) != "text":
            continue
        # 祖先链（文本→根）逐级收集可见性约束，取交集
        seg: list[tuple[float, float]] | None = None
        node: Any = el
        while node is not None:
            for child in node:
                if _local(child.tag) != "animate" or \
                        child.get("attributeName") != "opacity":
                    continue
                wins = _opacity_windows_from_animate(child)
                if wins:
                    seg = wins if seg is None else _intersect(seg, wins)
            for child in node:
                if _local(child.tag) == "set" and \
                        child.get("attributeName") == "opacity" and \
                        child.get("to") == "1" and child.get("begin"):
                    secs = _parse_begin_seconds(child.get("begin"))
                    if secs is not None and dur_total and dur_total > 0:
                        t0 = min(1.0, max(0.0, secs / dur_total))
                        seg = ([(t0, 1.0)] if seg is None
                               else _intersect(seg, [(t0, 1.0)]))
            node = parent_map.get(id(node))
        windows.append(seg if seg else [(0.0, 1.0)])
    return windows


def _opacity_windows_from_animate(el: Any) -> list[tuple[float, float]]:
    """离散 opacity animate → value=="1" 的 keyTimes 段列表（末段延到 1）。"""
    if el.get("calcMode") != "discrete":
        return []
    values = [v.strip() for v in (el.get("values") or "").split(";")
              if v.strip() != ""]
    kts_raw = [k.strip() for k in (el.get("keyTimes") or "").split(";")
               if k.strip() != ""]
    if len(values) != len(kts_raw) or not values:
        return []
    try:
        kts = [float(k) for k in kts_raw]
    except ValueError:
        return []
    wins: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        if v == "1":
            t0 = kts[i]
            t1 = kts[i + 1] if i + 1 < len(kts) else 1.0
            wins.append((min(t0, t1), max(t0, t1)))
    return wins


def _intersect(a: list[tuple[float, float]],
               b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """窗口并集列表交（两两相交非空段；空=文本永不可见→空表）。"""
    out: list[tuple[float, float]] = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                out.append((lo, hi))
    return out


def _windows_overlap(a: list[tuple[float, float]],
                     b: list[tuple[float, float]]) -> bool:
    return any(min(a1, b1) - max(a0, b0) > 0.0
               for a0, a1 in a for b0, b1 in b)


#: SVG rotate 变换解析（``rotate(θ)`` 或 ``rotate(θ cx cy)``；空格/逗号分隔；
#: 无中心点=绕原点旋转——SVG 规范语义）。只认单 rotate；其余 transform
#: 形态不解析（保守回退未旋转盒——旋转文本按未旋转盒估算只会更宽更易报，
#: 宁多报不放过，#316 同向）。
_ROTATE_RE = re.compile(
    r"rotate\(\s*([+-]?[0-9.eE+-]+)"
    r"(?:[\s,]+([+-]?[0-9.eE+-]+)[\s,]+([+-]?[0-9.eE+-]+))?\s*\)")


def _rotated_bbox(corners: list[tuple[float, float]], theta_deg: float,
                  cx: float, cy: float) -> tuple[float, float, float, float]:
    """四角绕 (cx,cy) 旋转 θ（SVG 口径：正角=屏幕顺时针，y 轴向下）→ 包围盒。"""
    t = math.radians(theta_deg)
    cos_t, sin_t = math.cos(t), math.sin(t)
    xs: list[float] = []
    ys: list[float] = []
    for px, py in corners:
        dx, dy = px - cx, py - cy
        xs.append(cx + dx * cos_t - dy * sin_t)
        ys.append(cy + dx * sin_t + dy * cos_t)
    return min(xs), min(ys), max(xs), max(ys)


def _text_boxes(root: Any) -> list[tuple[float, float, float, float, str, int]]:
    """文本元素 → (x0, y0, x1, y1, 文本内容, 字号) 盒列表（声明式估算：
    宽=字符数×字号×_CHAR_WIDTH_RATIO；高=字号（基线上 0.72/下 0.28）；
    锚点平移：middle=中心、end=右对齐。显式 x/y 缺失=跳过（不参与）。

    rotate 识别（Q-R3R 排版修复配套）：元素带可解析 ``rotate(θ[,cx,cy])``
    transform 时，未旋转盒四角按 SVG 旋转矩阵映射后取包围盒——90° 竖排
    文本（直角坐标 ylabel 惯例位）盒宽=字号量级，不再误报越界/tick 重叠；
    任意 θ 通用（包围盒=保守外包络）。transform 存在但不可解析 → 未旋转
    盒保守回退（宁多报不放过，#316 同向）。
    """
    boxes: list[tuple[float, float, float, float, str, int]] = []
    for el in root.iter():
        if _local(el.tag) != "text":
            continue
        xs, ys = el.get("x"), el.get("y")
        if xs is None or ys is None:
            continue  # 显式 x/y 是内核最低契约（缺=结构问题，归结构检测面）
        try:
            x, y = float(xs), float(ys)
        except ValueError:
            continue
        try:
            fs = float(el.get("font-size") or 13)
        except ValueError:
            fs = 13.0
        content = "".join(el.itertext())
        if not content:
            continue
        w = len(content) * fs * _CHAR_WIDTH_RATIO
        anchor = el.get("text-anchor") or "start"
        if anchor == "middle":
            x0 = x - w / 2.0
        elif anchor == "end":
            x0 = x - w
        else:
            x0 = x
        y0 = y - _TEXT_ASCENT_RATIO * fs
        corners = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + fs), (x0, y0 + fs)]
        raw_tf = el.get("transform")
        rot = None
        if raw_tf:
            m = _ROTATE_RE.fullmatch(raw_tf.strip())
            if m is not None:
                try:
                    theta = float(m.group(1))
                    cx = float(m.group(2)) if m.group(2) is not None else 0.0
                    cy = float(m.group(3)) if m.group(3) is not None else 0.0
                except ValueError:
                    rot = None  # 不可解析 → 保守回退（不放过方向）
                else:
                    rot = (theta, cx, cy)
        if rot is not None:
            bx0, by0, bx1, by1 = _rotated_bbox(corners, *rot)
        else:
            bx0, by0, bx1, by1 = x0, y0, x0 + w, y0 + fs
        boxes.append((bx0, by0, bx1, by1, content, int(fs)))
    return boxes


def detect_text_overlap(svg: str, *,
                        canvas_wh: tuple[int, int] | None = None
                        ) -> tuple[SelfCheckIssue, ...]:
    """文字挤压检测（声明式估算判据，**warn 级**——估算有假阳性可能，
    不设硬门；估算口径见 _CHAR_WIDTH_RATIO/_TEXT_ASCENT_RATIO 注释）。

    检查项：①两两文本盒矩形相交（x/y 双向交叠量均 > _OVERLAP_TOL_PX；
    边缘相接不算）且**可见时间窗相交**（帧互斥语义：逐帧替换标签任一
    时刻仅一帧可见，不同帧同位标签不算同屏挤压——见
    :func:`_text_visibility_windows` 声明式规则）→ kind=``text_overlap``；
    ②文本盒越出画幅（canvas_wh 缺省从 viewBox 推导；越界 →
    kind=``text_out_of_bounds``——盒几何静态量，不按时窗豁免）。

    rotate 识别（Q-R3R 排版修复配套）：``rotate(θ[,cx,cy])`` 文本盒按
    SVG 旋转矩阵映射取包围盒（90° 竖排 ylabel=正确排版形态，不再误报
    越界/tick 重叠；见 :func:`_text_boxes`）；不可解析 transform → 未旋转
    盒保守回退（宁多报不放过）。

    已知局限（docstring 声明）：CJK 全角字符宽于 0.62×字号估算 → 可能
    漏报（不误报）；字号缺省回退 13（内核 svg_text 恒显式 font-size）。
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return ()  # 结构归 verify_svg_structure 专责
    boxes = _text_boxes(root)
    vis = _text_visibility_windows(root)
    issues: list[SelfCheckIssue] = []
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ax0, ay0, ax1, ay1, atext, _afs = boxes[a]
            bx0, by0, bx1, by1, btext, _bfs = boxes[b]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox <= _OVERLAP_TOL_PX or oy <= _OVERLAP_TOL_PX:
                continue
            if not _windows_overlap(vis[a], vis[b]):
                continue  # 帧互斥：任一时刻至多其一可见，非同屏挤压
            issues.append(SelfCheckIssue(
                level=_LEVEL_WARN, kind="text_overlap",
                locator=f"text[{a}]×text[{b}]",
                message=f"文本盒估算重叠（x 交叠 {ox:.1f}px / y 交叠 "
                        f"{oy:.1f}px）：{atext!r} × {btext!r}"))
    if canvas_wh is None:
        vb = root.get("viewBox")
        if vb is not None:
            parts = vb.replace(",", " ").split()
            if len(parts) == 4:
                try:
                    canvas_wh = (float(parts[2]), float(parts[3]))
                except ValueError:
                    canvas_wh = None
    if canvas_wh is not None:
        w_lim, h_lim = float(canvas_wh[0]), float(canvas_wh[1])
        for k, (x0, y0, x1, y1, text, _fs) in enumerate(boxes):
            if x0 < -_OVERLAP_TOL_PX or y0 < -_OVERLAP_TOL_PX \
                    or x1 > w_lim + _OVERLAP_TOL_PX \
                    or y1 > h_lim + _OVERLAP_TOL_PX:
                issues.append(SelfCheckIssue(
                    level=_LEVEL_WARN, kind="text_out_of_bounds",
                    locator=f"text[{k}]",
                    message=f"文本盒 [{x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f}] "
                            f"越出画幅 0,0,{w_lim:.0f},{h_lim:.0f}：{text!r}"))
    return tuple(issues)


def run_animation_self_check(svg: str, *, frame_count: int | None = None,
                             canvas_wh: tuple[int, int] | None = None
                             ) -> AnimationSelfCheckReport:
    """三检测器汇总 → :class:`AnimationSelfCheckReport`（issue 序固定：
    structure→frame→text——确定性报告序）。"""
    issues: list[SelfCheckIssue] = []
    issues.extend(verify_svg_structure(svg, expected_canvas_wh=canvas_wh))
    issues.extend(detect_frame_order(svg, expected_frames=frame_count))
    issues.extend(detect_text_overlap(svg, canvas_wh=canvas_wh))
    return AnimationSelfCheckReport(issues=tuple(issues))
