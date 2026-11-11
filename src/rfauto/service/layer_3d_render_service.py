"""KiCad .kicad_pcb 逐层 3D 渲染导出 service（aurora_q Q-X39，2026-11-07）。

消费形态（任务书原文）：KiCad .kicad_pcb → 逐层 3D 渲染导出——铜层
（F.Cu/B.Cu）+ 阻焊层（F.Mask/B.Mask）+ 丝印层（F.Silkscreen/B.Silkscreen）
+ 钻孔（Edge.Cuts 板框，过孔/焊盘钻孔独立渲染）逐层独立 PNG + 叠层合成
预览 PNG/SVG；零 pcbnew 子进程依赖（纯文本 s-expr 直读，AGENTS 规则 2 的
反向形态——本服务连 KiCad 安装都不需要）、零真机零 license，Agg OO 后端。

== 几何忠实纪律（铁律 7 的版图面落实）==================================

**渲染坐标 = s-expr 直出**：全部几何（走线折线端点/焊盘中心与尺寸/图形
项坐标/层厚度）从 .kicad_pcb 文本原文逐点读取，零算术派生——本服务里
唯一合法的"新坐标"只有两类：
1. **pad 面向装配坐标系的旋转变换**：pad 的 ``(at X Y [ANGLE])`` 是
   footprint 局部坐标，装配坐标 = 旋转(角度) + 平移——这是**几何恒等
   变换**（刚体运动），不是数值派生；公式以 pcbnew 真机 oracle 逐点
   互证（见下"oracle 互证"节）；
2. 视图/版面（轴范围、盒子比例、相机角）——渲染呈现参数，非几何数据，
   全部以显式常量落档（``VIEW_*`` 族）并随信封回显。

角向口径（KiCad 9/10 实证，oracle 互证）：板文件 s-expr 的角度单位=度，
y 轴向下（显示面镜像），正角=CW（屏面直觉）。pad 文件角=**绝对角**
（KiCad 写文件时已折算 footprint 旋转——ecc83-pp 真板 R1 fp −90°、pad
文件角 270° 的 oracle 实测绝对 270° 同值），只决定 pad **形状朝向**。
pad **位置**变换用 **footprint 角**：
``(x', y') = R(θ_fp)·(x, y) + (X_fp, Y_fp)``，R 为 y-down 系旋转矩阵
``[[cosθ, sinθ], [−sinθ, cosθ]]``（y-down 使标准 CCW 矩阵的 sin 项符号
翻转；θ 用度）。背面翻转 footprint 的局部坐标在文件内已镜像落盘，
同式直用零额外镜像（StickHub 57 背面 fp oracle 实证）。

footprint 图形项（fp_line/fp_rect/fp_circle/fp_arc/fp_poly）同帧变换：
局部坐标逐点 R(θ_fp)·p + at（θ_fp=footprint 角，y-down 口径同上）。
板级图形项（gr_*）与走线/过孔/板框本身就是板坐标，直读零变换。

== z 轴叠层（stackup 直读，KiCad 文件序=自顶向下）======================

``(stackup (layer "F.Cu" ... (thickness 0.035)) ...)`` 文件序即物理
顶→底（KiCad 官方口径，#375 的 pyedb 反例 mirror——本服务消费侧按文件
序**原序**直接当"自顶向下"使用，不做二次翻转）。每层 z 位置=其上方
全部层的厚度累加（含介质），介质层厚度同样取 stackup 原文；层厚缺失
时用 ``_DEFAULT_THICKNESS_MM`` 声明式缺省（silk/mask=0.01、copper=0.035、
介质=1.51/总厚分摊不可得时层间距取 copper 缺省）+ warning 如实入信封
——与 kicad_edb_bridge 同纪律：**缺失不编造**，声明式缺省+显式 warning。

== oracle 互证（#118 家法：裁判面独立于被测实现）=======================

pad 位置/角度变换公式经 KiCad 10 pcbnew 真机 oracle 逐点互证
（``pcbnew.LoadBoard`` → ``pad.GetPosition/GetOrientationDegrees``）：
ecc83-pp（15 fp/33 pad，含 ±90°/180° 旋转）+ StickHub（94 fp/278 pad，
含 57 背面翻转 fp）两真板 311 pad 全量对拍——位置 worst ≤5e-7 mm
（pcbnew 内部整数 nm 舍入量级）、角度 worst 0°，落档
runs/aurora_q/qx39_render/oracle_crosscheck.json。单测钉用**手工
独立推导**的合成板（R 旋转矩阵手算锚）+ oracle 实测值字面锚，不依赖
真机（规则：单测零真机）；oracle 互证是席位级证据不是常驻门（KiCad
安装不可移植）。

== 渲染面 ==============================================================

matplotlib mplot3d（Poly3DCollection/Line3DCollection），OO API
（Figure+FigureCanvasAgg，零 pyplot，零 GUI）+ plot_style 单源消费
（dpi/字号/canvas 底色全走 :mod:`rfauto.core.plot_style`，本模块零新造
样式数值）+ ``paper_figure_context`` 作用域施加。确定性：Agg OO +
显式 metadata + 零时间戳零随机——同输入两跑逐字节（hfss_run_report
同款先例）。

逐层渲染（``render_pcb_layers``）：
- 每个请求层一张 PNG：该层几何（走线+焊盘+过孔 pad 环+该层图形项+
  板框 z=层 z 平面）绘成 3D 场景，其余层隐去；层名进 figure title 与
  PNG metadata；
- Edge.Cuts（钻孔/板框层）独立一张：板框多边形 + 过孔钻孔柱面 + pad
  钻孔柱面（thru-hole pad 有 drill 时）。
叠层合成（``composite`` 参数）：所有层同场景按 z 叠放（介质层以半透明
板材体渲染），PNG + SVG 双出——SVG 带每 collection 的 gid
（``layer3d-<层名>``）供下游按层挑组（G1 出图同源思路）。

GLB/STEP 接口预留（任务书第 5 项）：``EXPORT_FORMATS`` 注册面挂
"glb"/"step" 两占位，请求即 skipped 信封（reason 声明"接口预留，
几何面已备好
scene_layers/shapes_traces 中间表示"，零 silently-wrong 产物）——
与 kicad_edb_bridge STACKUP_POLICIES 同款注册面纪律。

== 信封/分层/快照面 ====================================================

信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict）；
解析/渲染失败 → ``error_envelope``（errors 恒 list[str]）。分层：
service（本模块）→ adapters（kicad_sch_gen.parse_sexpr 只读复用）/
core（plot_style 只读消费）——**不 import kicad_edb_bridge**（冻结只读，
零耦合；其 docstring 的单位纪律 nm→mm 已由 extract 侧完成，本服务直接
吃 .kicad_pcb 原文毫米坐标）。

不设 ``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json
——plot_style/hfss_run_report 同款先例，新模块零金快照漂移）。

已知限制（如实）：
1. zone（铺铜）按轮廓多边形渲染填充（KiCad 7+ 文本无填充纹理，画
   outline 多边形是保真上限——filled_polys 属 pcbnew 运行时产物）；
2. pad shape 只实现 circle/rect/oval/roundrect/trapezoid（custom 的
   primitives 多边形直读渲染，chamfer 比例简化为 roundrect 近似+
   warning 如实）；
3. 弧段（gr_arc/fp_arc/arc 走线）按 start/mid/end 三点圆弧离散（缺
   mid 的旧格式 arc 如实 warning 跳过）；
4. 文本项（gr_text/fp_text）不渲染（3D 文字非版图几何，丝印层图形
   项已含丝印线框）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rfauto.adapters.kicad_sch_gen import parse_sexpr
from rfauto.core.plot_style import PAPER_FIGSIZE_DOUBLE, STYLE
from rfauto.service.envelope import error_envelope, ok_envelope

# ── 单源消费钉（plot_style Q-W8-4 冻结面——只读消费，禁改 plot_style）──────
#: 保存 dpi 单源（STYLE["savefig.dpi"]）
_FIG_DPI: int = int(STYLE["savefig.dpi"])
#: 合成预览 figsize 单源（IEEE 全宽 PAPER_FIGSIZE_DOUBLE）
_FIGSIZE_COMPOSITE: tuple[float, float] = PAPER_FIGSIZE_DOUBLE

#: 服务标识（信封 ``renderer`` 键，消费方版本兼容判据）
RENDERER_NAME = "layer_3d_render_service"
RENDERER_VERSION = "layer_3d_render_service/v0"

#: 任务书口径的缺省渲染层清单（--layers 缺省值）
DEFAULT_LAYERS: tuple[str, ...] = ("F.Cu", "B.Cu")

#: 导出格式注册面（glb/step=接口预留占位，请求即 skipped 如实）
EXPORT_FORMATS: tuple[str, ...] = ("png", "svg", "glb", "step")

#: 层语义分组（渲染样式分派键；layer_kind() 单源）
COPPER_KINDS = ("copper",)
#: KiCad 常见用户层名 → 渲染分组（名称制直查；含别名）

_LAYER_KIND_ALIASES: dict[str, str] = {
    "F.Cu": "copper", "B.Cu": "copper",
    "F.Mask": "mask", "B.Mask": "mask",
    "F.SilkS": "silk", "B.SilkS": "silk",
    "F.Silkscreen": "silk", "B.Silkscreen": "silk",
    "F.Paste": "paste", "B.Paste": "paste",
    "Edge.Cuts": "edge",
}

#: KiCad 标准层用户名 → 文件 canonical 名（板层表第 4 token 缺省时回退；
#: 口径=KiCad 9/10 层表实测，如 ``(5 "F.SilkS" user "F.Silkscreen")``——
#: 图形项 (layer ...) 恒写 canonical 名，用户/任务书常写用户名）
_STD_LAYER_ALIASES: dict[str, str] = {
    "F.Silkscreen": "F.SilkS", "B.Silkscreen": "B.SilkS",
    "F.Courtyard": "F.CrtYd", "B.Courtyard": "B.CrtYd",
    "F.Adhesive": "F.Adhes", "B.Adhesive": "B.Adhes",
    "User.Drawings": "Dwgs.User", "User.Comments": "Cmts.User",
    "User.Eco1": "Eco1.User", "User.Eco2": "Eco2.User",
}

#: 声明式缺省层厚（stackup 无厚度时用；缺失不编造→缺省+warning 双落档）
_DEFAULT_THICKNESS_MM: dict[str, float] = {
    "copper": 0.035, "mask": 0.01, "silk": 0.01, "paste": 0.05,
    "dielectric": 1.51, "edge": 0.0,
}

#: 层配色（单源常量；取 plot_style.PAPER_COLORS 同族色相、语义命名落档）
_LAYER_COLORS: dict[str, str] = {
    "copper": "#b87333",   # copper 色（语义命名；非 plot_style 数据系列色）
    "mask": "#2ca02c",     # 阻焊绿（PAPER_COLORS[2]）
    # 丝印灰（KiCad 3D 惯例丝印=白，但白底画布上白线不可见——
    # 呈现面可见性守卫用中灰，语义=丝印层；非数据系列色）
    "silk": "#7f7f7f",
    "paste": "#9467bd",    # 焊膏灰紫（PAPER_COLORS[4]）
    "edge": "#1f77b4",     # 板框蓝（PAPER_COLORS[0]）
    "dielectric": "#ff7f0e",  # 介质橙（PAPER_COLORS[1]）
}

#: 视图常量（呈现参数显式落档，非几何数据；随信封 view 键回显）
_VIEW_ELEV_DEG = 35.0
_VIEW_AZIM_DEG = -60.0
#: z 视觉放大倍数（板 z 向 1.6mm 对 100mm 级板面太小，3D 呈现放大；
#: **只影响呈现，不影响任何几何坐标**——docstring 声明+信封 view 键落档）
_VIEW_Z_SCALE = 4.0

#: SVG gid 前缀（逐 collection 按层命名，供下游按层挑组）
_SVG_GID_PREFIX = "layer3d"

#: SVG clip-path id 盐（matplotlib svg.hashsalt——缺省随机盐使同输入两跑
#: SVG 的 clip-path id 逐字节漂移；固定盐=确定性面。只影响 SVG 内部
#: id 命名，不影响任何渲染几何）
_SVG_HASH_SALT = "rfauto-layer3d"

#: 弧段离散步数（呈现平滑度；几何端点/圆心直读，离散只影响渲染光滑）
_ARC_SEGMENTS = 32


# ══════════════════════════ s-expr 帮手 ══════════════════════════════════

def _num(value: Any) -> float | None:
    """数值收敛：int/float（非 bool、有限）→ float，字符串数字可转→float。

    s-expr 数字 token 是 str（parse_sexpr 不转型），此处显式 float() 收敛；
    失败/非有限 → None（调用方按"跳过+warning"处置，绝不编造）。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if math.isfinite(out) else None
    if isinstance(value, str):
        try:
            out = float(value)
        except ValueError:
            return None
        return out if math.isfinite(out) else None
    return None


def _node(node: list, tag: str) -> list | None:
    """node 直系子节点里第一个 tag 匹配（format_overview 同款走法）。"""
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _nodes(node: list, tag: str) -> list[list]:
    """node 直系子节点里全部 tag 匹配。"""
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def _token(node: list | None, idx: int) -> str | None:
    if node is None or len(node) <= idx:
        return None
    return str(node[idx])


def _xy(node: list | None) -> tuple[float, float] | None:
    """(x Y) 节点 → (float, float)；非法 → None。"""
    if node is None or len(node) < 3:
        return None
    x, y = _num(node[1]), _num(node[2])
    if x is None or y is None:
        return None
    return (x, y)


def _stroke_width_mm(item: list) -> float | None:
    """图形项 (stroke (width W)) → W（缺失/非法 → None）。"""
    stroke = _node(item, "stroke")
    if stroke is None:
        return None
    return _num(_token(_node(stroke, "width"), 1))


# ═══════════════════════ 几何变换（oracle 互证口径） ═════════════════════

def rotate_y_down(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """y-down 板坐标系旋转（KiCad 屏面 CW 正角口径；oracle 互证见模块
    docstring）。

    标准右手系 CCW 矩阵 ``[[c, −s], [s, c]]`` 在 y-down 系里 sin 项
    符号翻转 → ``[[c, s], [−s, c]]``。θ=90 时 (1,0)→(0,−1)（屏面上方）
    ——与 ecc83 R1 oracle（fp at 90°，pad (5,0) 绝对位移 (0,−5)）一致。
    """
    rad = math.radians(angle_deg)
    c, s = math.cos(rad), math.sin(rad)
    return (x * c + y * s, -x * s + y * c)


def _kfp(item: list) -> tuple[float, float, float]:
    """footprint (at X Y [ANGLE]) → (x, y, 角度缺省 0)。"""
    at = _node(item, "at")
    if at is None:
        return (0.0, 0.0, 0.0)
    x, y = _xy(at) or (0.0, 0.0)
    ang = _num(at[3]) if len(at) > 3 else 0.0
    return (x, y, ang if ang is not None else 0.0)


def _pad_absolute(x_fp: float, y_fp: float, ang_fp: float,
                  pad: list) -> dict[str, Any] | None:
    """pad s-expr 节点 → 装配坐标几何（返回 None=几何非法，调用方 warning）。

    变换（pcbnew oracle 两板 311 pad 互证定谳）：pad 局部位置 (x,y) 旋
    **footprint 角** θ_fp 再平移 footprint at——``R(θ_fp)·(x,y)+at``；
    pad 文件角（=绝对角，含 fp 旋转）只决定**形状朝向**（矩形四角/
    椭圆轴/trapezoid delta/custom primitives），不参与位置变换。
    （早期实现误用 pad 角旋位置：正面 pad 文件角恒=fp 角时巧合正确，
    StickHub 背面翻转 fp 实测偏差达 1.025 mm——oracle 互证当场抓出。）
    尺寸/钻孔/层集直读零变换。
    """
    at = _node(pad, "at")
    if at is None:
        return None
    lx, ly = _xy(at) or (None, None)
    if lx is None:
        return None
    ang_pad = _num(at[3]) if len(at) > 3 else 0.0
    if ang_pad is None:
        ang_pad = 0.0
    ax, ay = rotate_y_down(lx, ly, ang_fp)
    ax += x_fp
    ay += y_fp
    size = _node(pad, "size")
    w = _num(_token(size, 1)) if size is not None else None
    h = _num(_token(size, 2)) if size is not None and len(size) > 2 else None
    if w is None or w <= 0 or h is None or h <= 0:
        return None
    shape = str(pad[3]) if len(pad) > 3 else "circle"
    # 层集直读
    layers_node = _node(pad, "layers")
    layers = ([str(t) for t in layers_node[1:]
               if not isinstance(t, list)] if layers_node is not None else [])
    # 钻孔直读
    drill = _node(pad, "drill")
    drill_mm = _num(_token(drill, 1)) if drill is not None else None
    oval_drill = drill is not None and "oval" in [t for t in drill[1:]
                                                  if not isinstance(t, list)]
    # roundrect 圆角比 / trapezoid delta（局部原值；形状四角在局部系按
    # KiCad 角式成形后**只旋转一次** pad 角——pcbnew 形状 oracle 实证）
    rratio = _num(_token(_node(pad, "roundrect_rratio"), 1))
    delta_node = _node(pad, "rect_delta")
    delta: tuple[float, float] | None = None
    delta_local: tuple[float, float] | None = None
    if delta_node is not None:
        dx, dy = _xy(delta_node) or (None, None)
        if dx is not None:
            delta_local = (dx, dy)
            delta = rotate_y_down(dx, dy, ang_pad)
    # custom primitives 轮廓点（pad 局部系 → 按 pad 形状朝向旋转；平移在
    # _pad_polygons 侧随 pad 中心——primitives 只出形状轮廓）
    prim_pts: list[list[tuple[float, float]]] = []
    prims = _node(pad, "primitives")
    if prims is not None:
        for p in prims[1:]:
            if not isinstance(p, list) or not p or not str(p[0]).startswith(
                    "gr_"):
                continue
            prim_shape = _graphic_shape(str(p[0])[3:], p)
            if prim_shape is not None and prim_shape[0]:
                prim_pts.append([rotate_y_down(px, py, ang_pad)
                                 for (px, py) in prim_shape[0]])
    # custom pad 锚形（(options (anchor rect|circle))，缺省 circle——
    # KiCad 自定义焊盘锚形口径）
    anchor = "circle"
    opts = _node(pad, "options")
    if opts is not None:
        anchor_tok = _token(_node(opts, "anchor"), 1)
        if anchor_tok in ("rect", "circle"):
            anchor = anchor_tok
    return {
        "x_mm": ax, "y_mm": ay, "angle_deg": ang_pad,
        "w_mm": w, "h_mm": h, "shape": shape,
        "layers": layers, "drill_mm": drill_mm,
        "oval_drill": oval_drill, "roundrect_rratio": rratio,
        "rect_delta_rot": delta, "rect_delta_local": delta_local,
        "primitive_polys": prim_pts,
        "custom_anchor": anchor,
        "number": str(pad[1]) if len(pad) > 1 else "",
    }


# ════════════════════════ 图形项几何直读 ═════════════════════════════════

def _bezier_polyline(p0: tuple[float, float], p1: tuple[float, float],
                     p2: tuple[float, float], p3: tuple[float, float],
                     n: int = _ARC_SEGMENTS) -> list[tuple[float, float]]:
    """三次 Bézier 离散（gr_curve/fp_curve 四控制点直读；端点=p0/p3 精确）。"""
    pts: list[tuple[float, float]] = [p0]
    for i in range(1, n):
        t = i / n
        u = 1.0 - t
        b0, b1, b2, b3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        pts.append((b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0],
                    b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]))
    pts.append(p3)
    return pts


def _graphic_shape(kind: str, item: list
                   ) -> tuple[list[tuple[float, float]], bool] | None:
    """图形项（gr_*/fp_* 去前缀 kind）→ (局部坐标折线点, 是否闭合)。

    **按节点名显式取点**（不依赖 tag 遍历序——早期按 start/end/center/mid
    序取点致 arc 被当 (start,end,mid) 画成长弧 ¾ 圆、rect 两点画成对角线、
    circle 画成圆心连线：NFC 天线板框圆角实证）：
    - line：start→end；rect：start/end 两角张成四角闭合；
    - circle：center+半径=|end−center|，圆周离散闭合；
    - arc：start/mid/end 三点定弧（缺 mid 旧格式→None，调用方 warning）；
    - poly：pts 内 (xy)/(arc start mid end) 逐段展开闭合；
    - curve：pts 四控制点三次 Bézier。
    几何定义点全部 s-expr 原文直读（铁律 7），离散只影响呈现光滑度。
    """
    if kind == "line":
        s, e = _xy(_node(item, "start")), _xy(_node(item, "end"))
        return ([s, e], False) if s is not None and e is not None else None
    if kind == "rect":
        s, e = _xy(_node(item, "start")), _xy(_node(item, "end"))
        if s is None or e is None:
            return None
        return ([s, (e[0], s[1]), e, (s[0], e[1])], True)
    if kind == "circle":
        c, e = _xy(_node(item, "center")), _xy(_node(item, "end"))
        if c is None or e is None:
            return None
        r = math.hypot(e[0] - c[0], e[1] - c[1])
        if r <= 0:
            return None
        n = _ARC_SEGMENTS * 2
        return ([(c[0] + r * math.cos(2 * math.pi * i / n),
                  c[1] + r * math.sin(2 * math.pi * i / n))
                 for i in range(n)], True)
    if kind == "arc":
        s = _xy(_node(item, "start"))
        m = _xy(_node(item, "mid"))
        e = _xy(_node(item, "end"))
        if s is None or m is None or e is None:
            return None
        return (_arc_polyline(s, m, e), False)
    if kind in ("poly", "curve"):
        pts_node = _node(item, "pts")
        if pts_node is None:
            return None
        pts: list[tuple[float, float]] = []
        for el in pts_node[1:]:
            if not isinstance(el, list) or not el:
                continue
            if el[0] == "xy":
                p = _xy(el)
                if p is not None:
                    pts.append(p)
            elif el[0] == "arc":
                s = _xy(_node(el, "start"))
                m = _xy(_node(el, "mid"))
                e = _xy(_node(el, "end"))
                if s is not None and m is not None and e is not None:
                    seg = _arc_polyline(s, m, e)
                    pts.extend(seg[1:] if pts and pts[-1] == seg[0] else seg)
        if kind == "curve":
            if len(pts) != 4:
                return None
            return (_bezier_polyline(pts[0], pts[1], pts[2], pts[3]), False)
        return (pts, True) if len(pts) >= 2 else None
    return None


def _arc_polyline(start: tuple[float, float], mid: tuple[float, float],
                  end: tuple[float, float], n: int = _ARC_SEGMENTS
                  ) -> list[tuple[float, float]]:
    """三点圆弧离散（start/mid/end 直读三点定圆，均匀参数采样）。

    三点共线（圆退化）→ 折线直连（如实退化，零编造）。
    """
    (x1, y1), (x2, y2), (x3, y3) = start, mid, end
    d = 2.0 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return [start, mid, end]
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1)
          + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3)
          + (x3**2 + y3**2) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1 = math.atan2(y1 - uy, x1 - ux)
    am = math.atan2(y2 - uy, x2 - ux)
    a3 = math.atan2(y3 - uy, x3 - ux)
    two_pi = 2.0 * math.pi
    # 终角相对 start 的带符号最短差（(−π, π]）
    d3 = (a3 - a1) % two_pi
    if d3 > math.pi:
        d3 -= two_pi
    dm_u = am - a1  # mid 相对 start 的原始角差（可超 π——长弧面）
    # 候选总扫掠 = d3 + 2πk；取「end 精确可达 + mid 落参数域 [0,1] 内」
    # 的最短者（三点定弧：mid 在弧上是 KiCad 文件格式语义，候选集
    # k∈[−2,2] 覆盖多圈歧义；最短原则消解 wrap 歧义）
    sweep = d3
    best = None
    for k in range(-2, 3):
        s = d3 + two_pi * k
        if abs(s) < 1e-12:
            continue
        hit = False
        for m in range(-2, 3):
            t = (dm_u + two_pi * m) / s
            if -1e-9 <= t <= 1.0 + 1e-9:
                hit = True
                break
        if hit and (best is None or abs(s) < abs(best)):
            best = s
    if best is not None:
        sweep = best
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):
        a = a1 + sweep * i / n
        pts.append((ux + r * math.cos(a), uy + r * math.sin(a)))
    return pts


# ═══════════════════════════ 板解析 ══════════════════════════════════════

def layer_kind(layer_name: str) -> str:
    """层名 → 渲染分组（copper/mask/silk/paste/edge/other）。单源。

    内层铜 ``In<k>.Cu`` 一律 copper（后缀判定；别名表只列外层双面）。
    """
    kind = _LAYER_KIND_ALIASES.get(layer_name)
    if kind is not None:
        return kind
    if layer_name.endswith(".Cu"):
        return "copper"
    return "other"


def _expand_layer_tokens(tokens: list[str], copper_layers: list[str]
                         ) -> tuple[list[str], bool]:
    """KiCad 通配层名展开（pcbnew oracle 实证：thru pad 层集写 `*.Cu`/
    `*.Mask`，其 LSET 展开=全部铜层/双面 mask——ecc83 R1 pad1 实测 22 层）。

    - ``*.Cu``  → 全部铜层名（板层表 id 序）
    - ``*.Mask``→ F.Mask + B.Mask（存在哪个展开哪个，按板层表序）
    - ``*.SilkS``/``*.Silkscreen`` → F+B 丝印
    - ``*.Paste`` → F+B 焊膏
    - ``F&B.Cu`` → 板层表里 F.Cu 与 B.Cu（旧格式 via 层对通配）
    其余 token 原样保留。返回 (展开层名列表, 是否发生展开)。
    """
    out: list[str] = []
    expanded = False
    lower_map = {n.lower(): n for n in copper_layers}

    def _both(kind: str) -> list[str]:
        faces = ("F", "B")
        names = []
        for f in faces:
            for alias in (f"{f}.{kind}",):
                if alias in copper_layers or alias in _LAYER_KIND_ALIASES:
                    names.append(alias)
        return names

    for tok in tokens:
        t = str(tok)
        if t == "*.Cu":
            expanded = True
            out.extend(copper_layers)
        elif t == "F&B.Cu":
            expanded = True
            for cand in ("F.Cu", "B.Cu"):
                real = lower_map.get(cand.lower())
                out.append(real if real is not None else cand)
        elif t.lower() in ("*.mask", "*.silks", "*.silkscreen", "*.paste"):
            expanded = True
            kind = ("Mask" if "mask" in t.lower()
                    else "SilkS" if "silk" in t.lower() else "Paste")
            out.extend(_both(kind))
        else:
            out.append(t)
    # 去重保序
    seen: set[str] = set()
    dedup = [x for x in out if not (x in seen or seen.add(x))]
    return dedup, expanded


def parse_pcb_scene(pcb_path: str | Path) -> dict[str, Any]:
    """.kicad_pcb → 渲染场景 dict（全部几何 s-expr 直出，毫米）。

    返回（成功场景，``ok`` 恒 True）::

        {
          "ok": True, "renderer": ..., "units": "mm",
          "copper_layers": ["F.Cu", "B.Cu", ...]（KiCad 层 id 升序）,
          "stackup": [{"name", "kind", "thickness_mm", "z_top_mm",
                       "er": ..., "tan_d": ...}, ...]（文件序顶→底）,
          "board_thickness_mm": float（(general (thickness)) 或 stackup 累加）,
          "traces_by_layer": {层名: [{"points_mm", "width_mm", "net"}, ...]},
          "arcs_by_layer":   {层名: [{"points_mm"(离散折线), "width_mm"}]},
          "pads_by_layer":   {层名: [pad dict（_pad_absolute 产物）]},
          "vias":            [{"x_mm", "y_mm", "pad_diameter_mm",
                                "drill_mm", "layers"}],
          "zones_by_layer":  {层名: [{"points_mm"}]},
          "graphics_by_layer": {层名: [{"points_mm", "width_mm", "closed",
                                         "item"}]},
          "edge_outline":    {"polylines": [[(x, y), ...]], "bbox_mm": ...},
          "warnings": [...],
        }

    解析失败（非 kicad_pcb 根/读文件失败）→ ``error_envelope``。
    几何非法的元素跳过+warning（桥接同纪律：warnings 空=逐元素零跳过）。
    """
    path = Path(pcb_path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return error_envelope(f".kicad_pcb 不可读: {exc}")
    try:
        top = parse_sexpr(text)
    except ValueError as exc:
        return error_envelope(f".kicad_pcb s-expr 解析失败: {exc}")
    if (len(top) != 1 or not isinstance(top[0], list) or not top[0]
            or top[0][0] != "kicad_pcb"):
        return error_envelope(
            "根表达式不是 (kicad_pcb ...)——文件损坏或非 .kicad_pcb")
    root = top[0]
    warnings: list[str] = []

    # ---- 层表（KiCad 层 id 升序=物理顶→底）----
    copper_layers: list[str] = []
    user_layers: list[str] = []
    layer_aliases: dict[str, str] = dict(_STD_LAYER_ALIASES)
    layers_node = _node(root, "layers")
    if layers_node is not None:
        for child in layers_node[1:]:
            if not isinstance(child, list) or len(child) < 2:
                continue
            name = str(child[1])
            # 第 4 token=用户名（如 "F.Silkscreen"）→ canonical 名映射；
            # 板层表实测优先于标准回退表
            if len(child) > 3 and not isinstance(child[3], list):
                layer_aliases[str(child[3])] = name
            if layer_kind(name) == "copper":
                copper_layers.append(name)
            else:
                user_layers.append(name)

        def _cu_rank(n: str) -> int:
            # 物理顶→底按**名称**排（KiCad 9/10 层 id 重排 B.Cu=2 而非
            # 旧 31——kicad_extract 同坑实证；id 序会把 B.Cu 排到内层前）
            if n == "F.Cu":
                return 0
            if n == "B.Cu":
                return 1 << 20
            if n.startswith("In") and n.endswith(".Cu"):
                k = _num(n[2:-3])
                if k is not None:
                    return int(k)
            return 1 << 19

        copper_layers.sort(key=_cu_rank)
    if not copper_layers:
        warnings.append("(layers) 无铜层条目——按 F.Cu/B.Cu 缺省口径渲染")

    # ---- stackup（文件序顶→底；z 自顶向下累加）----
    stackup: list[dict[str, Any]] = []
    setup = _node(root, "setup")
    stack_node = _node(setup, "stackup") if setup is not None else None
    if stack_node is None:
        # 根级 (stackup ...) 变体（仓内 minimal_board fixture 口径——
        # KiCad 官方真机板在 (setup) 内，手写/简化板常落根级；两形态
        # 都收，根级无则如实缺省告警）
        stack_node = _node(root, "stackup")
    if stack_node is None:
        warnings.append(
            "缺 (setup (stackup ...))——层厚按声明式缺省（copper 0.035/"
            "mask/silk 0.01/dielectric 1.51 mm）+ 板总厚 (general "
            "(thickness)) 兜底，缺失不编造")
    z_cursor = 0.0
    board_thickness = None
    general = _node(root, "general")
    if general is not None:
        board_thickness = _num(_token(_node(general, "thickness"), 1))
    if stack_node is not None:
        for sl in _nodes(stack_node, "layer"):
            name = _token(sl, 1)
            if name is None:
                continue
            kind = layer_kind(name)
            tnode = _node(sl, "type")
            type_token = _token(tnode, 1) if tnode is not None else ""
            if type_token in ("core", "prepreg", "substrate"):
                kind = "dielectric"
            thick = _num(_token(_node(sl, "thickness"), 1))
            if thick is None:
                thick = _DEFAULT_THICKNESS_MM.get(kind)
                if thick is not None:
                    warnings.append(
                        f"stackup 层 {name!r} 缺 thickness——用声明式缺省 "
                        f"{thick} mm（{kind} 档），如实非实测")
            z_top = z_cursor
            if thick is not None:
                z_cursor += thick
            stackup.append({
                "name": name, "kind": kind, "thickness_mm": thick,
                "z_top_mm": z_top,
                "er": _num(_token(_node(sl, "epsilon_r"), 1)),
                "tan_d": _num(_token(_node(sl, "loss_tangent"), 1)),
            })
    if stackup and board_thickness is None:
        board_thickness = z_cursor
    if not stackup:
        # 无 stackup：铜层 2 张面 + 介质一张体，声明式缺省
        cu_t = _DEFAULT_THICKNESS_MM["copper"]
        di_t = board_thickness if board_thickness is not None \
            else _DEFAULT_THICKNESS_MM["dielectric"]
        stackup = [
            {"name": copper_layers[0] if copper_layers else "F.Cu",
             "kind": "copper", "thickness_mm": cu_t, "z_top_mm": 0.0,
             "er": None, "tan_d": None},
            {"name": "dielectric 1", "kind": "dielectric",
             "thickness_mm": di_t, "z_top_mm": cu_t,
             "er": None, "tan_d": None},
            {"name": copper_layers[-1] if len(copper_layers) > 1 else "B.Cu",
             "kind": "copper", "thickness_mm": cu_t,
             "z_top_mm": cu_t + di_t, "er": None, "tan_d": None},
        ]
        board_thickness = cu_t * 2 + di_t
        warnings.append(
            "无 stackup 节——叠层按铜/介质/铜三段声明式缺省合成"
            f"（板厚 {board_thickness} mm）")

    # ---- 走线（segment 直读）----
    traces_by_layer: dict[str, list[dict[str, Any]]] = {}
    for seg in _nodes(root, "segment"):
        layer = _token(_node(seg, "layer"), 1)
        start = _xy(_node(seg, "start"))
        end = _xy(_node(seg, "end"))
        width = _num(_token(_node(seg, "width"), 1))
        if layer is None or start is None or end is None:
            warnings.append("segment 缺 layer/start/end，跳过")
            continue
        if width is None or width <= 0:
            warnings.append(f"segment width 非正（layer={layer}），跳过")
            continue
        traces_by_layer.setdefault(layer, []).append({
            "points_mm": [list(start), list(end)],
            "width_mm": width,
            "net": _token(_node(seg, "net"), 2) or "",
        })

    # ---- 板级弧段走线（arc：start/mid/end）----
    arcs_by_layer: dict[str, list[dict[str, Any]]] = {}
    for arc in _nodes(root, "arc"):
        layer = _token(_node(arc, "layer"), 1)
        s = _xy(_node(arc, "start"))
        m = _xy(_node(arc, "mid"))
        e = _xy(_node(arc, "end"))
        width = _num(_token(_node(arc, "width"), 1))
        if layer is None:
            warnings.append("arc 缺 layer，跳过")
            continue
        if s is None or m is None or e is None:
            warnings.append(
                f"arc（layer={layer}）缺 start/mid/end 三点，跳过"
                "（旧格式弧如实跳过）")
            continue
        if width is None or width <= 0:
            warnings.append(f"arc width 非正（layer={layer}），跳过")
            continue
        arcs_by_layer.setdefault(layer, []).append({
            "points_mm": [list(p) for p in _arc_polyline(s, m, e)],
            "width_mm": width,
        })

    # ---- 过孔 ----
    vias: list[dict[str, Any]] = []
    for via in _nodes(root, "via"):
        at = _xy(_node(via, "at"))
        size = _num(_token(_node(via, "size"), 1))
        drill = _num(_token(_node(via, "drill"), 1))
        layers_node_v = _node(via, "layers")
        vlayers = ([str(t) for t in layers_node_v[1:]
                    if not isinstance(t, list)]
                   if layers_node_v is not None else [])
        if at is None or size is None or size <= 0:
            warnings.append("via 缺 at/size 非法，跳过")
            continue
        vlayers_exp, _exp = _expand_layer_tokens(vlayers, copper_layers)
        vias.append({
            "x_mm": at[0], "y_mm": at[1], "pad_diameter_mm": size,
            "drill_mm": drill, "layers": vlayers_exp,
        })

    # ---- footprint（pad + 图形项，帧变换）----
    pads_by_layer: dict[str, list[dict[str, Any]]] = {}
    graphics_by_layer: dict[str, list[dict[str, Any]]] = {}
    n_fp = 0
    for fp in _nodes(root, "footprint"):
        n_fp += 1
        x_fp, y_fp, ang_fp = _kfp(fp)
        for pad in _nodes(fp, "pad"):
            info = _pad_absolute(x_fp, y_fp, ang_fp, pad)
            if info is None:
                warnings.append(
                    f"footprint[{n_fp}] pad 几何非法（缺 at/size 非正），跳过")
                continue
            layers_exp, _exp = _expand_layer_tokens(info["layers"],
                                                    copper_layers)
            info["layers"] = layers_exp
            for ln in layers_exp:
                pads_by_layer.setdefault(ln, []).append(info)
        for tag in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly",
                    "fp_curve"):
            for item in _nodes(fp, tag):
                layer = _token(_node(item, "layer"), 1)
                if layer is None:
                    continue
                shape = _graphic_shape(tag[3:], item)
                if shape is None:
                    warnings.append(
                        f"footprint[{n_fp}] {tag} 几何定义缺失/非法（arc 缺 "
                        "mid=旧格式弧），跳过")
                    continue
                local_pts, closed = shape
                # 局部→装配：R(θ_fp)·p + at（刚体变换保圆/弧，先离散后
                # 变换与先变换后离散等价）
                pts = [rotate_y_down(px, py, ang_fp) for (px, py) in local_pts]
                pts = [(px + x_fp, py + y_fp) for (px, py) in pts]
                width = _stroke_width_mm(item) or 0.0
                graphics_by_layer.setdefault(layer, []).append({
                    "points_mm": [list(p) for p in pts],
                    "width_mm": width, "closed": closed, "item": tag,
                })

    # ---- 板级图形项（gr_*，板坐标零变换）----
    for tag in ("gr_line", "gr_rect", "gr_circle", "gr_arc", "gr_poly",
                "gr_curve"):
        for item in _nodes(root, tag):
            layer = _token(_node(item, "layer"), 1)
            if layer is None:
                continue
            shape = _graphic_shape(tag[3:], item)
            if shape is None:
                warnings.append(
                    f"{tag} 几何定义缺失/非法（arc 缺 mid=旧格式弧），跳过")
                continue
            pts, closed = shape
            width = _stroke_width_mm(item) or 0.0
            graphics_by_layer.setdefault(layer, []).append({
                "points_mm": [list(p) for p in pts],
                "width_mm": width, "closed": closed, "item": tag,
            })

    # ---- zone（板级轮廓多边形直读；footprint 内 zone 同法）----
    zones_by_layer: dict[str, list[dict[str, Any]]] = {}
    zone_owners = [root] + [fp for fp in _nodes(root, "footprint")]
    for owner in zone_owners:
        for zone in _nodes(owner, "zone"):
            layers_node_z = _node(zone, "layers")
            if layers_node_z is None:
                layers_node_z = _node(zone, "layer")
            zlayers = ([str(t) for t in layers_node_z[1:]
                        if not isinstance(t, list)]
                       if layers_node_z is not None else [])
            poly_pts: list[list[list[float]]] = []
            for poly in _nodes(zone, "polygon"):
                pts_node = _node(poly, "pts")
                if pts_node is None:
                    continue
                pts = [_xy(xy) for xy in _nodes(pts_node, "xy")]
                pts = [p for p in pts if p is not None]
                if len(pts) >= 3:
                    poly_pts.append([list(p) for p in pts])
            for ln in zlayers:
                for poly in poly_pts:
                    zones_by_layer.setdefault(ln, []).append(
                        {"points_mm": poly})

    # ---- 板框（Edge.Cuts 全图形项，闭合多边形优先）----
    edge_polys: list[list[tuple[float, float]]] = []
    edge_lines: list[list[tuple[float, float]]] = []
    for g in graphics_by_layer.get("Edge.Cuts", []):
        pts = [tuple(p) for p in g["points_mm"]]
        if g["closed"] and len(pts) >= 3:
            edge_polys.append(pts)
        else:
            edge_lines.append(pts)
    edge_outline: dict[str, Any] = {"polylines": [list(p) for p in
                                                  edge_polys + edge_lines]}
    all_edge = edge_polys + edge_lines
    if all_edge:
        xs = [p[0] for poly in all_edge for p in poly]
        ys = [p[1] for poly in all_edge for p in poly]
        edge_outline["bbox_mm"] = {
            "min_mm": [min(xs), min(ys)], "max_mm": [max(xs), max(ys)]}
    else:
        edge_outline["bbox_mm"] = None
        warnings.append("Edge.Cuts 无几何——板框缺，bbox 按内容自适应")

    # 信封走 envelope 构造器（AU-2 契约 §4：新代码禁裸 dict 信封）
    return ok_envelope(
        renderer=RENDERER_NAME,
        renderer_version=RENDERER_VERSION,
        units="mm",
        source=str(path),
        copper_layers=copper_layers,
        layer_aliases=layer_aliases,
        stackup=stackup,
        board_thickness_mm=board_thickness,
        traces_by_layer=traces_by_layer,
        arcs_by_layer=arcs_by_layer,
        pads_by_layer=pads_by_layer,
        vias=vias,
        zones_by_layer=zones_by_layer,
        graphics_by_layer=graphics_by_layer,
        edge_outline=edge_outline,
        warnings=warnings,
        counts={
            "footprints": n_fp,
            "traces": sum(len(v) for v in traces_by_layer.values()),
            "arcs": sum(len(v) for v in arcs_by_layer.values()),
            "vias": len(vias),
            "pads": sum(len(v) for v in pads_by_layer.values()),
            "zones": sum(len(v) for v in zones_by_layer.values()),
            "graphics": sum(len(v) for v in graphics_by_layer.values()),
            "warnings": len(warnings),
        },
    )


# ══════════════════════════ 3D 渲染（Agg OO） ════════════════════════════

def _layer_z(stackup: list[dict[str, Any]], layer_name: str,
             board_thickness: float | None) -> float | None:
    """层名 → 层顶面 z（mm；无 stackup 条目按铜面缺省口径返回 None）。"""
    for entry in stackup:
        if entry["name"] == layer_name:
            return entry["z_top_mm"]
    # stackup 无该层名（如缺 stackup 节的板）——顶铜/底铜按板厚口径
    return None


def _fallback_z(layer_name: str, copper_layers: list[str],
                board_thickness: float | None) -> float:
    """stackup 缺该层时的声明式 z：顶层铜=0、底层铜=板厚、其余=板厚/2。"""
    if board_thickness is None:
        board_thickness = (_DEFAULT_THICKNESS_MM["copper"] * 2
                           + _DEFAULT_THICKNESS_MM["dielectric"])
    if copper_layers and layer_name == copper_layers[0]:
        return 0.0
    if len(copper_layers) > 1 and layer_name == copper_layers[-1]:
        return board_thickness
    return board_thickness / 2.0


def _collect_layer_geometry(scene: dict[str, Any], layer: str
                            ) -> dict[str, Any]:
    """某层渲染所需的全部几何（走线+弧+焊盘+zone+图形项+板框）。"""
    traces = scene["traces_by_layer"].get(layer, [])
    arcs = scene["arcs_by_layer"].get(layer, [])
    pads = scene["pads_by_layer"].get(layer, [])
    zones = scene["zones_by_layer"].get(layer, [])
    graphics = scene["graphics_by_layer"].get(layer, [])
    if layer == "Edge.Cuts":
        graphics = list(graphics)
    return {
        "traces": traces, "arcs": arcs, "pads": pads,
        "zones": zones, "graphics": graphics,
    }


def _round_rect_local(w: float, h: float, r: float,
                      n_arc: int = 6) -> list[tuple[float, float]]:
    """圆角矩形局部轮廓（中心原点、轴对齐；r=0 退化直角四角）。"""
    hw, hh = w / 2.0, h / 2.0
    r = max(0.0, min(r, hw, hh))
    if r <= 0.0:
        return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    pts: list[tuple[float, float]] = []
    # 角心与起始角（y-down 局部系，沿 +角向逐角走一圈）
    for cx, cy, a0 in ((hw - r, -hh + r, -90.0), (hw - r, hh - r, 0.0),
                       (-hw + r, hh - r, 90.0), (-hw + r, -hh + r, 180.0)):
        for i in range(n_arc + 1):
            a = math.radians(a0 + 90.0 * i / n_arc)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _stadium_local(w: float, h: float, n_cap: int = 12
                   ) -> list[tuple[float, float]]:
    """椭圆端条形（KiCad oval=stadium/obround）局部轮廓：长轴两端半圆，
    半径=短边/2（pcbnew 形状 oracle：3×1@45° bbox 半宽 1.2071=√½+0.5，
    椭圆假设得 1.118 被证伪）。"""
    if abs(w - h) < 1e-12:
        r = w / 2.0
        return [(r * math.cos(2 * math.pi * i / (2 * n_cap)),
                 r * math.sin(2 * math.pi * i / (2 * n_cap)))
                for i in range(2 * n_cap)]
    pts: list[tuple[float, float]] = []
    if w > h:
        r, c = h / 2.0, w / 2.0 - h / 2.0
        for i in range(n_cap + 1):  # 右半圆 −90°→90°
            a = math.radians(-90.0 + 180.0 * i / n_cap)
            pts.append((c + r * math.cos(a), r * math.sin(a)))
        for i in range(n_cap + 1):  # 左半圆 90°→270°
            a = math.radians(90.0 + 180.0 * i / n_cap)
            pts.append((-c + r * math.cos(a), r * math.sin(a)))
    else:
        r, c = w / 2.0, h / 2.0 - w / 2.0
        for i in range(n_cap + 1):  # 下半圆 0°→180°
            a = math.radians(180.0 * i / n_cap)
            pts.append((r * math.cos(a), c + r * math.sin(a)))
        for i in range(n_cap + 1):  # 上半圆 180°→360°
            a = math.radians(180.0 + 180.0 * i / n_cap)
            pts.append((r * math.cos(a), -c + r * math.sin(a)))
    return pts


def _pad_polygon(pad: dict[str, Any]) -> list[list[float]]:
    """pad → 主形状平面多边形（装配坐标，毫米）。

    形状口径全部经 pcbnew ``GetEffectivePolygon`` 形状 oracle 实证
    （runs/aurora_q/qx39_render/oracle/oracle_shapes.json）：
    - circle：直径=size.x（KiCad 圆焊盘只用 x）；
    - oval：stadium/obround（非椭圆）；
    - rect：四角；roundrect：圆角半径=rratio·min(w,h)（rratio 缺省
      0.25——KiCad 新建圆角焊盘缺省比）；
    - trapezoid：KiCad 角式（d=rect_delta/2，局部原值）
      ``(−hw−d.y, hh+d.x) (hw+d.y, hh−d.x) (hw−d.y, −hh+d.x)
      (−hw+d.y, −hh−d.x)``——左/右竖边长 h±dx、上/下横边长 w∓dy；
    - custom：锚形（options anchor rect=w×h 矩形 / circle=直径 w）。
    局部轮廓**只旋转一次** pad 文件角（=绝对形状朝向）后平移到 pad
    中心（=装配位置，_pad_absolute：R(θ_fp)·局部+at）。
    """
    ang = pad.get("angle_deg", 0.0)
    w, h = pad["w_mm"], pad["h_mm"]
    x0, y0 = pad["x_mm"], pad["y_mm"]
    shape = pad.get("shape", "circle")
    if shape == "circle" or (shape == "custom"
                             and pad.get("custom_anchor") == "circle"):
        r = w / 2.0
        n = 24
        local = [(r * math.cos(2 * math.pi * i / n),
                  r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    elif shape == "oval":
        local = _stadium_local(w, h)
    elif shape == "roundrect":
        rr = pad.get("roundrect_rratio")
        rr = 0.25 if rr is None else rr
        local = _round_rect_local(w, h, rr * min(w, h))
    elif shape == "trapezoid" and pad.get("rect_delta_local") is not None:
        ddx, ddy = (v / 2.0 for v in pad["rect_delta_local"])
        hw, hh = w / 2.0, h / 2.0
        local = [(-hw - ddy, hh + ddx), (hw + ddy, hh - ddx),
                 (hw - ddy, -hh + ddx), (-hw + ddy, -hh - ddx)]
    else:
        # rect / custom(rect 锚) / 未知 shape 矩形兜底（声明式退化不编造）
        hw, hh = w / 2.0, h / 2.0
        local = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    out: list[list[float]] = []
    for (lx, ly) in local:
        rx, ry = rotate_y_down(lx, ly, ang)
        out.append([x0 + rx, y0 + ry])
    return out


def _pad_polygons(pad: dict[str, Any]) -> list[list[list[float]]]:
    """pad → 全部平面多边形：主形状 + custom primitives（已按 pad 角旋转，
    此处平移到 pad 中心——pcbnew 形状 oracle：custom@90° 三角 primitive
    顶点 (60,8)/(61,8) 逐位吻合）。"""
    polys = [_pad_polygon(pad)]
    if pad.get("shape") == "custom":
        x0, y0 = pad["x_mm"], pad["y_mm"]
        for prim in pad.get("primitive_polys") or []:
            if len(prim) >= 3:
                polys.append([[x0 + px, y0 + py] for (px, py) in prim])
    return polys


def _draw_traces(ax: Any, traces: list[dict[str, Any]], z: float,
                 color: str, alpha: float, gid: str) -> list[Any]:
    """走线（含弧离散）→ 3D 面片集合（矩形长条沿折线逐段铺放）。"""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    if not traces:
        return []

    zt = z * _VIEW_Z_SCALE
    quads: list[list[list[float]]] = []
    for tr in traces:
        pts = tr["points_mm"]
        half = tr["width_mm"] / 2.0
        for i in range(len(pts) - 1):
            x1, y1 = pts[i][0], pts[i][1]
            x2, y2 = pts[i + 1][0], pts[i + 1][1]
            dx, dy = x2 - x1, y2 - y1
            ln = math.hypot(dx, dy)
            if ln <= 0:
                continue
            nx, ny = -dy / ln * half, dx / ln * half
            quads.append([
                [x1 + nx, y1 + ny, zt], [x2 + nx, y2 + ny, zt],
                [x2 - nx, y2 - ny, zt], [x1 - nx, y1 - ny, zt]])
        # 折点圆角方帽（简化为折点处 w×w 方块，避免裂缝；呈现面）
        if len(pts) >= 3:
            for p in pts[1:-1]:
                quads.append([
                    [p[0] - half, p[1] - half, zt], [p[0] + half, p[1] - half, zt],
                    [p[0] + half, p[1] + half, zt], [p[0] - half, p[1] + half, zt]])
    coll = Poly3DCollection(quads, facecolors=color, edgecolors="none",
                            alpha=alpha)
    coll.set_gid(gid)
    coll.set_zorder(3)
    ax.add_collection3d(coll, autolim=False)
    return [coll]


def _draw_zones(ax: Any, zones: list[dict[str, Any]], z: float,
                color: str, alpha: float, gid: str) -> list[Any]:
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    if not zones:
        return []
    zt = z * _VIEW_Z_SCALE
    polys = [[ [p[0], p[1], zt] for p in z["points_mm"] ] for z in zones]
    coll = Poly3DCollection(polys, facecolors=color, edgecolors="none",
                            alpha=alpha)
    coll.set_gid(gid)
    coll.set_zorder(2)
    ax.add_collection3d(coll, autolim=False)
    return [coll]


def _draw_pads(ax: Any, pads: list[dict[str, Any]], z: float,
               color: str, alpha: float, gid: str) -> list[Any]:
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    if not pads:
        return []
    zt = z * _VIEW_Z_SCALE
    # 主形状+custom primitives 全量（pcbnew 形状 oracle 口径）
    polys = [poly for p in pads for poly in _pad_polygons(p)]
    polys3 = [[[p[0], p[1], zt] for p in poly] for poly in polys]
    coll = Poly3DCollection(polys3, facecolors=color, edgecolors="none",
                            alpha=alpha)
    coll.set_gid(gid)
    coll.set_zorder(4)
    ax.add_collection3d(coll, autolim=False)
    return [coll]


def _draw_graphics(ax: Any, graphics: list[dict[str, Any]], z: float,
                   color: str, alpha: float, gid: str) -> list[Any]:
    """丝印/阻焊/板框图形项 → 3D 线集合（closed 项闭合画）。"""
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    if not graphics:
        return []
    zt = z * _VIEW_Z_SCALE
    segs: list[list[list[float]]] = []
    for g in graphics:
        pts = g["points_mm"]
        if g.get("closed") and len(pts) >= 3:
            pts = [*pts, pts[0]]
        for i in range(len(pts) - 1):
            segs.append([[pts[i][0], pts[i][1], zt],
                         [pts[i + 1][0], pts[i + 1][1], zt]])
    coll = Line3DCollection(segs, colors=color, linewidths=1.0)
    coll.set_gid(gid)
    coll.set_alpha(alpha)
    coll.set_zorder(5)
    ax.add_collection3d(coll, autolim=False)
    return [coll]


def _draw_drills(ax: Any, vias: list[dict[str, Any]],
                 pads: list[dict[str, Any]], z_lo: float, z_hi: float,
                 gid: str) -> list[Any]:
    """钻孔柱面（过孔+thru pad drill）→ 3D 线集合（每孔 8 条素线）。"""
    from mpl_toolkits.mplot3d.art3d import Line3DCollection

    zl, zh = z_lo * _VIEW_Z_SCALE, z_hi * _VIEW_Z_SCALE
    segs: list[list[list[float]]] = []
    holes: list[tuple[float, float, float]] = []
    for v in vias:
        d = v.get("drill_mm")
        if d is not None and d > 0:
            holes.append((v["x_mm"], v["y_mm"], d / 2.0))
    for p in pads:
        d = p.get("drill_mm")
        if d is not None and d > 0:
            holes.append((p["x_mm"], p["y_mm"], d / 2.0))
    for (cx, cy, r) in holes:
        for i in range(8):
            t = 2 * math.pi * i / 8
            nx, ny = r * math.cos(t), r * math.sin(t)
            segs.append([[cx + nx, cy + ny, zl], [cx + nx, cy + ny, zh]])
    if not segs:
        return []
    coll = Line3DCollection(segs, colors="#555555", linewidths=0.7)
    coll.set_gid(gid)
    coll.set_zorder(6)
    ax.add_collection3d(coll, autolim=False)
    return [coll]


def _setup_axes(ax: Any, bbox: dict[str, Any] | None,
                board_thickness: float | None) -> None:
    """轴范围/盒子比例/相机/方向（呈现常量单源 _VIEW_*）。

    轴范围恒由本函数显式给定——各 collection 一律 ``autolim=False`` 入轴
    （mplot3d 缺省 autolim 对空轴区间做 margin 运算会冒 numpy overflow
    RuntimeWarning：StickHub B.Mask 实证，-W error 抓出；显式范围下
    autoscale 纯属冗余计算，关掉后零告警且语义零变化）。
    """
    if bbox:
        x0, y0 = bbox["min_mm"]
        x1, y1 = bbox["max_mm"]
    else:
        x0, y0, x1, y1 = 0.0, 0.0, 100.0, 100.0
    if x1 - x0 < 1e-9:
        x1 = x0 + 1.0
    if y1 - y0 < 1e-9:
        y1 = y0 + 1.0
    th = (board_thickness if board_thickness is not None
          else _DEFAULT_THICKNESS_MM["copper"] * 2
          + _DEFAULT_THICKNESS_MM["dielectric"])
    zspan = max(th * _VIEW_Z_SCALE, 1.0)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)  # y-down（KiCad 屏面口径）
    ax.set_zlim(0.0, zspan)
    ax.set_box_aspect((x1 - x0, y1 - y0, zspan))
    ax.view_init(elev=_VIEW_ELEV_DEG, azim=_VIEW_AZIM_DEG)
    ax.set_axis_off()


def _figure_frame(figsize: tuple[float, float], title: str):
    """OO Figure 装配（Agg 后端，零 pyplot 零 GUI）。

    plot_style 作用域（paper_figure_context）由调用方 render_pcb_layers
    在外层统一施加——Figure 必须在作用域内创建并保存才吃到 STYLE。
    ``title`` 仅作调用面语义标注（标题由各渲染段 ax.set_title 落）。
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    del title  # 签名语义位（见 docstring），渲染段自设标题
    fig = Figure(figsize=figsize, dpi=100)
    FigureCanvasAgg(fig)
    return fig


def _save_png(fig: Any, path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), format="png", dpi=_FIG_DPI, metadata={
        "Software": f"rfauto {RENDERER_NAME}",
        "Title": title,
    })


def _save_svg(fig: Any, path: Path, title: str) -> None:
    """SVG 落盘（Date=None=零时间戳确定性；逐 collection gid 已设）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), format="svg", metadata={"Title": title,
                                                   "Date": None})


def render_pcb_layers(
    pcb_path: str | Path,
    out_dir: str | Path | None = None,
    *,
    layers: list[str] | tuple[str, ...] | None = None,
    composite: bool = True,
    svg_composite: bool = True,
    export_format: str = "png",
    explode: float = 0.0,
) -> dict[str, Any]:
    """KiCad .kicad_pcb → 逐层 3D PNG（+合成预览 PNG/SVG）+ JSON 信封。

    Args:
        pcb_path: .kicad_pcb 路径（纯文本直读，零 pcbnew 依赖）。
        out_dir: 产物目录；None=只出信封零落盘（确定性面：文件名固定
            ``<板名>_layer_<层名>.png`` / ``<板名>_composite.png/.svg``，
            无时间戳）。
        layers: 渲染层清单（缺省 DEFAULT_LAYERS=F.Cu,B.Cu；层名制——
            "F.Silkscreen"/"F.SilkS" 双名都收）；请求层名不在板文件层表
            时按"该层零几何"如实渲染空场景+warning（不拒绝）——板文件
            常省略空层条目。
        composite: 叠层合成预览 PNG（全部请求层同场景按 z 叠放）。
        svg_composite: 合成预览 SVG（逐 collection gid=layer3d-<层名>）。
        export_format: png|svg|glb|step；glb/step=接口预留，skipped
            信封如实（reason 声明预留语义，零 silently-wrong 产物）。
        explode: 爆炸间距系数（0=实叠层；>0 时各层 z 额外抬升
            layer_index×explode×板厚——呈现参数随信封 view 落档）。

    Returns:
        成功：``{"ok": True, "renderer": ..., "units": "mm", "layers":
        [...实际渲染层], "png_paths": [...], "svg_paths": [...],
        "composite": {...}, "view": {...}, "warnings": [...],
        "counts": {...}}``；解析失败 → error_envelope。
    """
    scene = parse_pcb_scene(pcb_path)
    if not scene.get("ok"):
        return scene
    warnings = list(scene.get("warnings") or [])

    # ---- export_format 预留面 ----
    fmt = str(export_format).strip().lower()
    if fmt not in EXPORT_FORMATS:
        return error_envelope(
            f"未知 export_format {export_format!r}（可用: "
            f"{list(EXPORT_FORMATS)}）")
    if fmt in ("glb", "step"):
        return ok_envelope(
            renderer=RENDERER_NAME,
            skipped=True,
            reason=(f"export_format={fmt!r} 为接口预留（Q-X39 任务书第 5 项）"
                    "——几何中间表示（scene/pads/traces 按层分桶）已在 "
                    "parse_pcb_scene 产物备好，GLB/STEP 写出器为后续席位 "
                    "落地面；本调用零产物零 silently-wrong"),
            layers=list(layers or DEFAULT_LAYERS),
            export_format=fmt,
            source=str(Path(pcb_path)),
        )

    requested = list(layers) if layers else list(DEFAULT_LAYERS)
    if not requested:
        return error_envelope("layers 清单为空——至少请求一个层名")
    # 用户名 → canonical 名（"F.Silkscreen"→"F.SilkS"：图形项恒写
    # canonical 名，几何桶/stackup 按 canonical 查；信封 layers 保留
    # 请求原名，layer_canonical 显式回显映射）
    aliases = scene.get("layer_aliases") or {}
    canon = {ln: aliases.get(ln, ln) for ln in requested}
    known = (set(scene["copper_layers"])
             | {e["name"] for e in scene["stackup"]}
             | set(scene["traces_by_layer"])
             | set(scene["pads_by_layer"])
             | set(scene["graphics_by_layer"])
             | set(scene["zones_by_layer"]))
    for ln in requested:
        if canon[ln] not in known:
            warnings.append(
                f"层 {ln!r} 不在板文件层表/stackup/几何桶——按空场景渲染"
                "（板文件常省略空层条目，如实 warning 非错误）")

    # ---- 每层 z（stackup 直读，缺条目走声明式缺省）----
    def _z_of(layer: str) -> float:
        zz = _layer_z(scene["stackup"], layer, scene["board_thickness_mm"])
        if zz is not None:
            return zz
        return _fallback_z(layer, scene["copper_layers"],
                           scene["board_thickness_mm"])

    th = scene["board_thickness_mm"] or 1.6
    layer_z = {ln: _z_of(canon[ln]) for ln in requested}
    explode_off = {ln: i * explode * th for i, ln in enumerate(requested)}
    # 每层几何计数（信封回显：Agent/用户可直接看出某层是否空场景）
    geometry_counts = {
        ln: {k: len(v) for k, v in
             _collect_layer_geometry(scene, canon[ln]).items()}
        for ln in requested}

    png_paths: list[str] = []
    svg_paths: list[str] = []
    from rfauto.core.plot_style import paper_figure_context

    base = Path(out_dir) if out_dir is not None else None
    stem = Path(str(pcb_path)).stem

    def _fname(kind: str, layer: str | None, ext: str) -> str:
        safe = (layer or "").replace(".", "_").replace("/", "_")
        return f"{stem}_{kind}_{safe}.{ext}" if layer else \
            f"{stem}_{kind}.{ext}"

    with paper_figure_context(**{"svg.hashsalt": _SVG_HASH_SALT}):
        for ln in requested:
            geo = _collect_layer_geometry(scene, canon[ln])
            color = _LAYER_COLORS.get(layer_kind(canon[ln]), "#1f77b4")
            fig = _figure_frame(_FIGSIZE_COMPOSITE, f"{stem} {ln}")
            ax = fig.add_subplot(1, 1, 1, projection="3d",
                                 computed_zorder=False)
            zt = layer_z[ln] + explode_off[ln]
            _draw_traces(ax, geo["traces"] + geo["arcs"], zt, color, 0.95,
                         f"{_SVG_GID_PREFIX}-{ln}-traces")
            _draw_zones(ax, geo["zones"], zt, color, 0.6,
                        f"{_SVG_GID_PREFIX}-{ln}-zones")
            _draw_pads(ax, geo["pads"], zt, color, 0.95,
                       f"{_SVG_GID_PREFIX}-{ln}-pads")
            _draw_graphics(ax, geo["graphics"], zt, color, 0.9,
                           f"{_SVG_GID_PREFIX}-{ln}-graphics")
            outline = scene["edge_outline"]
            _draw_graphics(ax, [{"points_mm": p, "width_mm": 0.1,
                                 "closed": False, "item": "edge"}
                                for p in outline["polylines"]],
                           zt, "#1f77b4", 0.8,
                           f"{_SVG_GID_PREFIX}-{ln}-edge")
            if layer_kind(canon[ln]) == "edge":
                # 钻孔面 = 过孔 + 全部含 drill 的 pad（通孔钻孔贯通叠层，
                # 请求层语义为 Edge.Cuts/钻孔面时全量画出）
                _draw_drills(ax, scene["vias"],
                             [p for pads in scene["pads_by_layer"].values()
                              for p in pads],
                             0.0, th, f"{_SVG_GID_PREFIX}-{ln}-drills")
            _setup_axes(ax, outline.get("bbox_mm"), scene["board_thickness_mm"])
            ax.set_title(f"{stem} — {ln}")
            if base is not None:
                p = base / _fname("layer", ln, "png")
                _save_png(fig, p, f"{stem} {ln}")
                png_paths.append(str(p))
                if fmt == "svg":
                    ps = base / _fname("layer", ln, "svg")
                    _save_svg(fig, ps, f"{stem} {ln}")
                    svg_paths.append(str(ps))

        # ---- 叠层合成（全部请求层同场景按 z 叠放；介质体半透明）----
        composite_png = None
        composite_svg = None
        if composite or svg_composite:
            fig = _figure_frame(_FIGSIZE_COMPOSITE, f"{stem} composite")
            ax = fig.add_subplot(1, 1, 1, projection="3d",
                                 computed_zorder=False)
            outline = scene["edge_outline"]
            bbox = outline.get("bbox_mm")
            # 介质层体（stackup 中 kind=dielectric，半透明板材色）
            for entry in scene["stackup"]:
                if entry["kind"] != "dielectric":
                    continue
                off = explode_off.get("__diel__", 0.0)
                _draw_slab(ax, bbox, entry["z_top_mm"] + off,
                           entry["thickness_mm"], scene)
            for ln in requested:
                geo = _collect_layer_geometry(scene, canon[ln])
                color = _LAYER_COLORS.get(layer_kind(canon[ln]), "#1f77b4")
                zt = layer_z[ln] + explode_off[ln]
                kind = layer_kind(canon[ln])
                alpha = 0.95 if kind == "copper" else 0.85
                _draw_traces(ax, geo["traces"] + geo["arcs"], zt, color,
                             alpha, f"{_SVG_GID_PREFIX}-composite-{ln}-traces")
                _draw_zones(ax, geo["zones"], zt, color, alpha * 0.6,
                            f"{_SVG_GID_PREFIX}-composite-{ln}-zones")
                _draw_pads(ax, geo["pads"], zt, color, alpha,
                           f"{_SVG_GID_PREFIX}-composite-{ln}-pads")
            # 钻孔（合成图全量）
            _draw_drills(ax, scene["vias"],
                         [p for ln in requested
                          for p in scene["pads_by_layer"].get(ln, [])],
                         0.0, th, f"{_SVG_GID_PREFIX}-composite-drills")
            _draw_graphics(ax, [{"points_mm": p, "width_mm": 0.1,
                                 "closed": False, "item": "edge"}
                                for p in outline["polylines"]],
                           0.0, "#1f77b4", 0.9,
                           f"{_SVG_GID_PREFIX}-composite-edge")
            _setup_axes(ax, bbox, scene["board_thickness_mm"])
            ax.set_title(f"{stem} — composite ({len(requested)} layers)")
            if base is not None and composite:
                p = base / _fname("composite", None, "png")
                _save_png(fig, p, f"{stem} composite")
                composite_png = str(p)
            if base is not None and svg_composite:
                p = base / _fname("composite", None, "svg")
                _save_svg(fig, p, f"{stem} composite")
                composite_svg = str(p)

    return ok_envelope(
        renderer=RENDERER_NAME,
        renderer_version=RENDERER_VERSION,
        units="mm",
        source=str(Path(pcb_path)),
        layers=requested,
        export_format=fmt,
        png_paths=png_paths,
        svg_paths=svg_paths,
        composite={"png": composite_png, "svg": composite_svg},
        layer_z_mm={ln: layer_z[ln] for ln in requested},
        layer_canonical=canon,
        layer_geometry_counts=geometry_counts,
        view={"elev_deg": _VIEW_ELEV_DEG, "azim_deg": _VIEW_AZIM_DEG,
              "z_scale": _VIEW_Z_SCALE, "explode": explode,
              "figsize_in": list(_FIGSIZE_COMPOSITE), "dpi": _FIG_DPI},
        stackup=[{k: e[k] for k in ("name", "kind", "thickness_mm",
                                    "z_top_mm", "er", "tan_d")}
                 for e in scene["stackup"]],
        board_thickness_mm=scene["board_thickness_mm"],
        warnings=warnings,
        counts=scene["counts"],
    )


def _draw_slab(ax: Any, bbox: dict[str, Any] | None, z_top: float,
               thickness: float, scene: dict[str, Any]) -> list[Any]:
    """介质板材体（半透明长方体 6 面）——合成预览的叠层语境件。"""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    if bbox:
        x0, y0 = bbox["min_mm"]
        x1, y1 = bbox["max_mm"]
    else:
        x0, y0, x1, y1 = 0.0, 0.0, 100.0, 100.0
    zt, zb = z_top * _VIEW_Z_SCALE, (z_top + thickness) * _VIEW_Z_SCALE
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    faces = [
        [[px, py, zt] for (px, py) in c],
        [[px, py, zb] for (px, py) in c],
    ]
    for i in range(4):
        j = (i + 1) % 4
        faces.append([[c[i][0], c[i][1], zt], [c[j][0], c[j][1], zt],
                      [c[j][0], c[j][1], zb], [c[i][0], c[i][1], zb]])
    coll = Poly3DCollection(faces, facecolors=_LAYER_COLORS["dielectric"],
                            edgecolors="none", alpha=0.15)
    coll.set_gid(f"{_SVG_GID_PREFIX}-dielectric-{z_top:.3f}")
    coll.set_zorder(1)
    ax.add_collection3d(coll, autolim=False)
    return [coll]
