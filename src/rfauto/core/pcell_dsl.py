"""B1/LC-2 PCell 几何 DSL（声明式参数化单元语言，YAML/Python 双面）。

方案依据（§10.2 B1，验收列）："3 个既有模板迁移到 DSL，冒烟结果等价"；
LC-2 扩面（round15 §四）："原语扩 path/polygon/via/旋转；求值产物直产
Layout；与 layout_generator 合流、N14 三原语迁可组合 PCell。验收：8+
PCell 且渲染桥消费"。
语言形态 = 声明式参数化单元（Parameterized Cell）：参数（带边界）→
派生量（表达式）→ 原语列表（盒/描边路径/多边形/过孔，每面坐标是参数
表达式，可选刚体旋转）+ 可选内核（registry 命名的确定性 Python 几何
内核，N14 走线基元/via_rail 这类顶点由闭式内核生成的原语）。

生态复用口径（§10.19 七轮强化）的落法：gdsfactory/KLayout 未进本仓
venv（GDS 读写/DRC 属 B2 的文件互操作），本模块是几何参数化内核——
只做"参数 → 原语坐标"的确定性求值，不碰 GDS/版图文件格式（Layout
出口在 cli 渲染桥，core 不反向依赖 adapters，分层 #3）；等价性裁判 =
既有渲染器几何段（#212 审计模式）。

铁律 7（数值只在确定性内核）：表达式经 AST 白名单求值（四则/幂/
min/max/abs），无 eval、无外部调用面；LLM 只产出 DSL 文本，数值
全部由本内核从参数确定性导出。

单位约定（如实声明，DSL 本身不带单位）：迁移的 3 个 openEMS 模板
（mline/cpw/wstep）坐标域=米（render 脚手架口径，H_SUB/BOARD/NEAR
上下文常量）；LC-2 新单元（ms_bend/gnd_void/rf_*/via_rail）坐标域=
毫米（layout_interchange.Layout 内部口径），渲染桥零换算直产。

用法（Python 面）：
    from rfauto.core.pcell_dsl import get_pcell, evaluate_pcell
    geo = evaluate_pcell(get_pcell("mline"), {"w_mm": 1.113},
                         context={"H_SUB": 5.08e-4, "BOARD": 0.06})
    geo.boxes[0].lo  # 归一化包围盒下角（与参数同单位域）

用法（YAML 面）：
    name: mline
    params: {w_mm: {default: 1.113}, line_len_mm: {default: 40.0}}
    variables:
      W: w_mm*1e-3
      Y0: -L/2
    boxes:
      - layer: microstrip
        name: line
        start: [-W/2, Y0, H_SUB]
        stop: [W/2, Y1, H_SUB]
        priority: 10

LC-2 新原语（YAML 面）：
    name: ms_bend
    params: {w_mm: {default: 1.113}, l1_mm: {default: 10.0},
             l2_mm: {default: 8.0}, rot_deg: {default: 0.0}}
    paths:
      - layer: F.Cu
        name: bend
        points: [[0, 0], [l1_mm, 0], [l1_mm, l2_mm]]
        width: w_mm
        rotate: {angle_deg: rot_deg, center: [0, 0]}   # 可选，度/绕点

    name: via_rail          # 内核面（顶点由确定性内核生成）
    params: {n: {default: 5}, pitch_mm: {default: 1.0}, ...}
    kernel: via_rail
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "KERNEL_REGISTRY",
    "PCELL_LIBRARY",
    "PCellBox",
    "PCellBoxGeom",
    "PCellDef",
    "PCellError",
    "PCellExpressionError",
    "PCellGeometry",
    "PCellParam",
    "PCellParamError",
    "PCellPath",
    "PCellPathGeom",
    "PCellPolygon",
    "PCellPolygonGeom",
    "PCellVia",
    "PCellViaGeom",
    "def_from_dict",
    "def_from_yaml",
    "def_to_dict",
    "def_to_yaml",
    "eval_expr",
    "evaluate_library",
    "evaluate_pcell",
    "get_pcell",
    "register_pcell_kernel",
]


class PCellError(ValueError):
    """PCell DSL 基类错误。"""


class PCellExpressionError(PCellError):
    """表达式非法或引用未知名字。"""


class PCellParamError(PCellError):
    """参数缺失/未知/越界。"""


# ─── 安全表达式求值（AST 白名单，确定性内核）───────────────────────────────

_ALLOWED_FUNCS: dict[str, Any] = {"min": min, "max": max, "abs": abs}
_ALLOWED_BINOPS: tuple[type[ast.AST], ...] = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
)
_ALLOWED_UNARY: tuple[type[ast.AST], ...] = (ast.USub, ast.UAdd)


def eval_expr(expr: Any, names: dict[str, float]) -> float:
    """白名单 AST 求值：四则/幂/一元正负/min/max/abs + 名字查找。

    expr 为 int/float 时直通（YAML 常量面）；str 才走解析。其它类型
    与一切越界节点（属性访问/下标/比较/调用白名单外函数/lambda/…）
    抛 PCellExpressionError——DSL 面不可执行任意代码。
    """
    if isinstance(expr, bool):
        raise PCellExpressionError(f"表达式不接受布尔值: {expr!r}")
    if isinstance(expr, (int, float)):
        value = float(expr)
        if value != value or value in (float("inf"), float("-inf")):
            raise PCellExpressionError(f"常量非有限: {expr!r}")
        return value
    if not isinstance(expr, str):
        raise PCellExpressionError(f"表达式必须是常量或字符串: {expr!r}")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise PCellExpressionError(f"表达式语法错误: {expr!r}（{exc}）") from exc
    try:
        value = float(_eval_node(tree.body, expr, names))
    except ZeroDivisionError as exc:
        raise PCellExpressionError(f"表达式 {expr!r} 除零") from exc
    except OverflowError as exc:
        raise PCellExpressionError(f"表达式 {expr!r} 数值溢出") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise PCellExpressionError(f"表达式结果非有限: {expr!r} → {value}")
    return value


def _eval_node(node: ast.AST, source: str, names: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        return eval_expr(node.value, names)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise PCellExpressionError(
                f"表达式 {source!r} 引用未定义名字: {node.id}")
        return float(names[node.id])
    if isinstance(node, ast.BinOp):
        _require(node.op, _ALLOWED_BINOPS, source, "二元运算")
        left = _eval_node(node.left, source, names)
        right = _eval_node(node.right, source, names)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        return left ** right  # ast.Pow
    if isinstance(node, ast.UnaryOp):
        _require(node.op, _ALLOWED_UNARY, source, "一元运算")
        operand = _eval_node(node.operand, source, names)
        return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in (
                _ALLOWED_FUNCS):
            raise PCellExpressionError(
                f"表达式 {source!r} 调用了白名单外的函数")
        if node.keywords:
            raise PCellExpressionError(f"表达式 {source!r} 不接受关键字参数")
        args = [_eval_node(a, source, names) for a in node.args]
        return float(_ALLOWED_FUNCS[node.func.id](*args))
    raise PCellExpressionError(
        f"表达式 {source!r} 含不允许的节点: {type(node).__name__}")


def _require(op: ast.AST, allowed: tuple[type[ast.AST], ...],
             source: str, what: str) -> None:
    if not any(isinstance(op, kind) for kind in allowed):
        raise PCellExpressionError(
            f"表达式 {source!r} 的{what}不在白名单: {type(op).__name__}")


# ─── 旋转（LC-2：刚体旋转原语面）──────────────────────────────────────────

_ROT_QUARTER_TOL = 1e-9  # 盒旋转仅 90° 倍数（保持轴对齐），判据容差


def rot2d(
    points: Iterable[tuple[float, float]],
    angle_deg: float,
    center: tuple[float, float],
) -> tuple[tuple[float, float], ...]:
    """绕 center 刚体旋转 2D 点列（度制；θ=0 恒等——cos/sin 精确 1/0）。"""
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    cx, cy = center
    return tuple(
        (cx + (x - cx) * cos_t - (y - cy) * sin_t,
         cy + (x - cx) * sin_t + (y - cy) * cos_t)
        for x, y in points
    )


# ─── 数据模型 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PCellParam:
    """PCell 用户参数：默认值 + 可选闭区间边界。"""
    name: str
    default: float
    lo: float | None = None
    hi: float | None = None
    note: str = ""


@dataclass(frozen=True)
class PCellBox:
    """一个盒原语声明：每面坐标是表达式（常量或参数算式字符串）。

    LC-2：可选刚体旋转（rotate_angle/rotate_center 必须成对给；盒只
    支持 90° 倍数——任意角会破坏轴对齐语义，请用 polygon 原语）。
    """
    layer: str
    start: tuple[Any, Any, Any]
    stop: tuple[Any, Any, Any]
    priority: Any = 10
    name: str = ""
    rotate_angle: Any = None
    rotate_center: tuple[Any, Any] | None = None


@dataclass(frozen=True)
class PCellPath:
    """描边路径原语（LC-2）：中心线折线（每点 (x,y) 表达式对）+ 恒定线宽。"""
    points: tuple[tuple[Any, Any], ...]
    width: Any
    layer: str
    name: str = ""
    rotate_angle: Any = None
    rotate_center: tuple[Any, Any] | None = None


@dataclass(frozen=True)
class PCellPolygon:
    """填充多边形原语（LC-2）：顶点 (x,y) 表达式对，闭合不重复首点。"""
    points: tuple[tuple[Any, Any], ...]
    layer: str
    name: str = ""
    rotate_angle: Any = None
    rotate_center: tuple[Any, Any] | None = None


@dataclass(frozen=True)
class PCellVia:
    """过孔原语（LC-2）：焊盘圆 + 钻孔（pad > drill > 0 在求值时判）。"""
    x: Any
    y: Any
    pad_diameter: Any
    drill_diameter: Any
    pad_layer: str
    name: str = ""
    rotate_angle: Any = None
    rotate_center: tuple[Any, Any] | None = None


@dataclass(frozen=True)
class PCellDef:
    """一个 PCell 的声明式全集（不可变；YAML/Python 双面共用）。

    LC-2：boxes 之外新增 paths/polygons/vias 三类声明原语与 kernel
    （KERNEL_REGISTRY 命名的确定性内核；求值时先出内核原语、再出声明
    原语，均按声明序）。
    """
    name: str
    description: str = ""
    params: tuple[PCellParam, ...] = ()
    variables: tuple[tuple[str, Any], ...] = ()  # 派生量，按声明序求值
    boxes: tuple[PCellBox, ...] = ()
    context_names: tuple[str, ...] = ()  # 求值时须由调用方注入的外部常量
    paths: tuple[PCellPath, ...] = ()
    polygons: tuple[PCellPolygon, ...] = ()
    vias: tuple[PCellVia, ...] = ()
    kernel: str | None = None


@dataclass(frozen=True)
class PCellBoxGeom:
    """求值后的盒原语（lo/hi 为逐轴归一化包围盒，坐标域与参数一致）。"""
    name: str
    layer: str
    start: tuple[float, float, float]
    stop: tuple[float, float, float]
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    priority: float


@dataclass(frozen=True)
class PCellPathGeom:
    """求值后的描边路径（LC-2）：毫米/米随单元约定，中心线 + 恒定线宽。"""
    name: str
    layer: str
    points: tuple[tuple[float, float], ...]
    width: float


@dataclass(frozen=True)
class PCellPolygonGeom:
    """求值后的填充多边形（LC-2）：顶点序列，闭合不重复首点。"""
    name: str
    layer: str
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class PCellViaGeom:
    """求值后的过孔（LC-2）：位置 + 焊盘/钻孔直径。"""
    name: str
    pad_layer: str
    position: tuple[float, float]
    pad_diameter: float
    drill_diameter: float


@dataclass(frozen=True)
class PCellGeometry:
    """PCell 求值产物：参数点 + 原语列表（确定性、可序列化）。"""
    pcell: str
    params: dict[str, float]
    boxes: tuple[PCellBoxGeom, ...]
    paths: tuple[PCellPathGeom, ...] = ()
    polygons: tuple[PCellPolygonGeom, ...] = ()
    vias: tuple[PCellViaGeom, ...] = ()

    def signature(self, digits: int = 12) -> tuple:
        """几何签名（round 归一，含全部原语类），供等价/参数敏感性比对。

        同类原语载荷同形可比；异类以 kind 串先分决，排序确定。
        """
        rows: list[tuple] = []
        for b in self.boxes:
            rows.append(("box", b.layer,
                         tuple(round(v, digits) for v in (*b.lo, *b.hi))))
        for p in self.paths:
            rows.append(("path", p.layer, round(p.width, digits),
                         tuple((round(x, digits), round(y, digits))
                               for x, y in p.points)))
        for p in self.polygons:
            rows.append(("polygon", p.layer,
                         tuple((round(x, digits), round(y, digits))
                               for x, y in p.points)))
        for v in self.vias:
            rows.append(("via", v.pad_layer,
                         (round(v.position[0], digits),
                          round(v.position[1], digits)),
                         round(v.pad_diameter, digits),
                         round(v.drill_diameter, digits)))
        return tuple(sorted(rows))

    def to_dicts(self) -> list[dict[str, Any]]:
        """JSON 友好序列化（service 层进出约定）：每原语一行，kind 标类。"""
        rows: list[dict[str, Any]] = []
        for b in self.boxes:
            rows.append({"kind": "box", "name": b.name, "layer": b.layer,
                         "start": list(b.start), "stop": list(b.stop),
                         "lo": list(b.lo), "hi": list(b.hi),
                         "priority": b.priority})
        for p in self.paths:
            rows.append({"kind": "path", "name": p.name, "layer": p.layer,
                         "points": [list(pt) for pt in p.points],
                         "width": p.width})
        for p in self.polygons:
            rows.append({"kind": "polygon", "name": p.name, "layer": p.layer,
                         "points": [list(pt) for pt in p.points]})
        for v in self.vias:
            rows.append({"kind": "via", "name": v.name, "layer": v.pad_layer,
                         "position": list(v.position),
                         "pad_diameter": v.pad_diameter,
                         "drill_diameter": v.drill_diameter})
        return rows


# ─── 内核注册表（LC-2：可组合 PCell——顶点由确定性内核生成的原语）────────────

#: 内核签名：evaluated values（参数+上下文+派生量）→ 原语 dict 列表
#: （键限 boxes/paths/polygons/vias，形状同 def_from_dict 各原语段，
#: 数值已定，求值侧按常量直通）。
PCellKernel = Callable[[dict[str, float]], dict[str, list[dict[str, Any]]]]

KERNEL_REGISTRY: dict[str, PCellKernel] = {}


def register_pcell_kernel(name: str, fn: PCellKernel) -> None:
    """注册确定性几何内核（重复注册显式报错，注册表纪律）。"""
    if name in KERNEL_REGISTRY:
        raise ValueError(f"PCell 内核已注册: {name}")
    KERNEL_REGISTRY[name] = fn


def _kernel_n14_taper(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """N14 线性渐变段（rf_trace_geometry.taper_polygon，A=L·(w1+w2)/2）。"""
    from rfauto.core.rf_trace_geometry import taper_polygon

    pts = taper_polygon((0.0, 0.0), (values["len_mm"], 0.0),
                        values["w1_mm"], values["w2_mm"])
    return {"polygons": [{"layer": "F.Cu", "name": "taper",
                          "points": [list(p) for p in pts]}]}


def _kernel_n14_miter_bend(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """N14 45° 倒角 90° 弯（mitered_bend_polygon，A=w(L1+L2)−c²/2）。"""
    from rfauto.core.rf_trace_geometry import mitered_bend_polygon

    pts = mitered_bend_polygon(
        (0.0, 0.0), (values["l1_mm"], 0.0),
        (values["l1_mm"], values["l2_mm"]),
        values["w_mm"], chamfer_mm=values["chamfer_mm"])
    return {"polygons": [{"layer": "F.Cu", "name": "miter_bend",
                          "points": [list(p) for p in pts]}]}


def _kernel_n14_round_bend(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """N14 圆角 90° 弯（rounded_bend_polygon，A→w(L1+L2)−r·w·(2−π/2)）。"""
    from rfauto.core.rf_trace_geometry import rounded_bend_polygon

    pts = rounded_bend_polygon(
        (0.0, 0.0), (values["l1_mm"], 0.0),
        (values["l1_mm"], values["l2_mm"]),
        values["w_mm"], values["r_mm"], n_arc=int(values["n_arc"]))
    return {"polygons": [{"layer": "F.Cu", "name": "round_bend",
                          "points": [list(p) for p in pts]}]}


def _kernel_via_rail(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """接地过孔排（与 layout_generator.via_fence 同口径的直线特例：沿 +x）。"""
    n = int(values["n"])
    if n < 1:
        raise ValueError(f"过孔数 n 必须 ≥1，得到 {n}")
    pad, drill = values["pad_mm"], values["drill_mm"]
    if not pad > drill > 0.0:
        raise ValueError(f"焊盘直径 {pad} 必须大于钻孔直径 {drill} 且为正")
    x0, y0, pitch = values["x0_mm"], values["y0_mm"], values["pitch_mm"]
    return {"vias": [
        {"pad_layer": "F.Cu", "name": f"via_{k}",
         "position": [x0 + k * pitch, y0],
         "pad_diameter": pad, "drill_diameter": drill}
        for k in range(n)
    ]}


def _kernel_guard_ring_fence(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """LC-3 矩形闭合护环（rf_guard_structures.via_fence_ring）。"""
    from rfauto.core.rf_guard_structures import via_fence_ring

    vias = via_fence_ring(
        values["w_mm"], values["h_mm"], values["pitch_mm"],
        values["pad_mm"], values["drill_mm"],
        x0_mm=values["x0_mm"], y0_mm=values["y0_mm"])
    return {"vias": [v.to_flat() for v in vias]}


def _kernel_cpw_ground_stitch(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """LC-3 CPW 共面地+缝合带（rf_guard_structures.cpw_ground_stitch）。"""
    from rfauto.core.rf_guard_structures import cpw_ground_stitch

    st = cpw_ground_stitch(
        values["length_mm"], values["w_mm"], values["gap_mm"],
        values["ground_width_mm"], values["strap_pitch_mm"],
        values["pad_mm"], values["drill_mm"],
        inset_mm=values["inset_mm"],
        x0_mm=values["x0_mm"], y0_mm=values["y0_mm"])
    return {
        "polygons": [
            {"layer": "F.Cu", "name": "center_trace",
             "points": [list(p) for p in st.center_trace]},
            {"layer": "F.Cu", "name": "ground_left",
             "points": [list(p) for p in st.ground_left]},
            {"layer": "F.Cu", "name": "ground_right",
             "points": [list(p) for p in st.ground_right]},
        ],
        "vias": [v.to_flat() for v in st.vias],
    }


def _kernel_stitch_mesh(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """LC-3 缝合网格（rf_guard_structures.stitch_mesh）。"""
    from rfauto.core.rf_guard_structures import stitch_mesh

    mesh = stitch_mesh(
        values["width_mm"], values["height_mm"],
        values["pitch_x_mm"], values["pitch_y_mm"],
        values["pad_mm"], values["drill_mm"],
        x0_mm=values["x0_mm"], y0_mm=values["y0_mm"])
    return {"vias": [v.to_flat() for v in mesh.vias]}


def _kernel_ground_void(values: dict[str, float]) -> dict[str, list[dict[str, Any]]]:
    """LC-3 地板开窗+可选护窗栅栏（rf_guard_structures.ground_void）。

    fence_offset_mm=0 语义为无栅栏（DSL 参数面全数值，0 即关）；>0 为
    护窗栅栏孔心距开窗边界的间距。
    """
    from rfauto.core.rf_guard_structures import ground_void

    off = values["fence_offset_mm"]
    void = ground_void(
        values["plane_w_mm"], values["plane_h_mm"],
        values["void_cx_mm"], values["void_cy_mm"],
        values["void_w_mm"], values["void_h_mm"],
        x0_mm=values["x0_mm"], y0_mm=values["y0_mm"],
        fence_offset_mm=None if off <= 0.0 else off,
        fence_pitch_mm=values["fence_pitch_mm"],
        fence_pad_mm=values["fence_pad_mm"],
        fence_drill_mm=values["fence_drill_mm"])
    out: dict[str, list[dict[str, Any]]] = {
        "polygons": [{"layer": "F.Cu", "name": "void",
                      "points": [list(p) for p in void.void_polygon]}]
    }
    if void.fence_vias:
        out["vias"] = [v.to_flat() for v in void.fence_vias]
    return out


register_pcell_kernel("n14_taper", _kernel_n14_taper)
register_pcell_kernel("n14_miter_bend", _kernel_n14_miter_bend)
register_pcell_kernel("n14_round_bend", _kernel_n14_round_bend)
register_pcell_kernel("via_rail", _kernel_via_rail)
register_pcell_kernel("guard_ring_fence", _kernel_guard_ring_fence)
register_pcell_kernel("cpw_ground_stitch", _kernel_cpw_ground_stitch)
register_pcell_kernel("stitch_mesh", _kernel_stitch_mesh)
register_pcell_kernel("ground_void", _kernel_ground_void)


# ─── 求值 ────────────────────────────────────────────────────────────────────

def _eval_rotate(decl, values: dict[str, float]):
    """声明原语的旋转字段 → (angle_deg, center) 或 None（成对性在 def 级判）。"""
    if decl.rotate_angle is None:
        return None
    return (eval_expr(decl.rotate_angle, values),
            (eval_expr(decl.rotate_center[0], values),
             eval_expr(decl.rotate_center[1], values)))


def evaluate_pcell(
    defn: PCellDef,
    params: dict[str, Any] | None = None,
    context: dict[str, float] | None = None,
) -> PCellGeometry:
    """参数点 → 几何。缺省/越界/未知参数与缺失/未知 context 均显式报错。"""
    values: dict[str, float] = {}
    overrides = dict(params or {})
    declared = {p.name: p for p in defn.params}
    for key in overrides:
        if key not in declared:
            raise PCellParamError(
                f"PCell {defn.name} 未知参数: {key}（可用: {sorted(declared)}）")
    for pname, param in declared.items():
        raw = overrides.get(pname, param.default)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise PCellParamError(
                f"PCell {defn.name} 参数 {pname} 必须是数值，得到 {raw!r}")
        value = float(raw)
        if value != value or value in (float("inf"), float("-inf")):
            raise PCellParamError(f"PCell {defn.name} 参数 {pname} 非有限")
        if param.lo is not None and value < param.lo:
            raise PCellParamError(
                f"PCell {defn.name} 参数 {pname}={value} 低于下界 {param.lo}")
        if param.hi is not None and value > param.hi:
            raise PCellParamError(
                f"PCell {defn.name} 参数 {pname}={value} 高于上界 {param.hi}")
        values[pname] = value

    ctx = dict(context or {})
    missing = [n for n in defn.context_names if n not in ctx]
    if missing:
        raise PCellParamError(
            f"PCell {defn.name} 缺少上下文常量: {missing}（"
            f"如 render 脚手架的 H_SUB/BOARD/NEAR）")
    extra = [n for n in ctx if n not in defn.context_names]
    if extra:
        raise PCellParamError(f"PCell {defn.name} 传入了未声明的上下文: {extra}")
    values.update({k: float(v) for k, v in ctx.items()})

    for var_name, expr in defn.variables:
        if var_name in values:
            raise PCellError(
                f"PCell {defn.name} 派生量 {var_name} 与参数/上下文/更早"
                f"派生量重名")
        values[var_name] = eval_expr(expr, values)

    boxes: list[PCellBoxGeom] = []
    paths: list[PCellPathGeom] = []
    polygons: list[PCellPolygonGeom] = []
    vias: list[PCellViaGeom] = []

    # 内核原语先出（cell 本体），声明原语随后按类/声明序（确定性次序）。
    if defn.kernel is not None:
        fn = KERNEL_REGISTRY.get(defn.kernel)
        if fn is None:
            raise PCellError(
                f"PCell {defn.name} 未知内核: {defn.kernel}"
                f"（可用: {sorted(KERNEL_REGISTRY)}）")
        try:
            emitted = fn(dict(values))
        except PCellError:
            raise
        except (ValueError, TypeError, KeyError, ZeroDivisionError,
                OverflowError) as exc:
            raise PCellError(
                f"PCell {defn.name} 内核 {defn.kernel} 求值失败: {exc}") from exc
        for raw in emitted.get("boxes") or []:
            boxes.append(_box_geom_from_flat(raw, defn.name, values))
        for raw in emitted.get("paths") or []:
            paths.append(_path_geom_from_flat(raw, defn.name, values))
        for raw in emitted.get("polygons") or []:
            polygons.append(_polygon_geom_from_flat(raw, defn.name, values))
        for raw in emitted.get("vias") or []:
            vias.append(_via_geom_from_flat(raw, defn.name, values))

    for box in defn.boxes:
        start = tuple(eval_expr(c, values) for c in box.start)
        stop = tuple(eval_expr(c, values) for c in box.stop)
        lo = tuple(min(s, t) for s, t in zip(start, stop, strict=True))
        hi = tuple(max(s, t) for s, t in zip(start, stop, strict=True))
        rot = _eval_rotate(box, values)
        if rot is not None:
            angle_deg, center = rot
            quarters = angle_deg / 90.0
            if abs(quarters - round(quarters)) > _ROT_QUARTER_TOL:
                raise PCellError(
                    f"PCell {defn.name} 盒原语旋转仅支持 90° 倍数（得到 "
                    f"{angle_deg}°）；任意角请用 polygon 原语")
            start = tuple((*rot2d([start[:2]], angle_deg, center)[0], start[2]))
            stop = tuple((*rot2d([stop[:2]], angle_deg, center)[0], stop[2]))
            lo = tuple(min(s, t) for s, t in zip(start, stop, strict=True))
            hi = tuple(max(s, t) for s, t in zip(start, stop, strict=True))
        boxes.append(PCellBoxGeom(
            name=box.name, layer=box.layer,
            start=start, stop=stop, lo=lo, hi=hi,
            priority=eval_expr(box.priority, values),
        ))

    for path in defn.paths:
        pts = [(eval_expr(x, values), eval_expr(y, values))
               for x, y in path.points]
        rot = _eval_rotate(path, values)
        if rot is not None:
            pts = rot2d(pts, rot[0], rot[1])
        width = eval_expr(path.width, values)
        if width <= 0.0:
            raise PCellParamError(
                f"PCell {defn.name} 路径 {path.name or path.layer} 线宽必须 "
                f">0，得到 {width}")
        paths.append(PCellPathGeom(
            name=path.name, layer=path.layer,
            points=tuple(pts), width=width))

    for poly in defn.polygons:
        pts = [(eval_expr(x, values), eval_expr(y, values))
               for x, y in poly.points]
        rot = _eval_rotate(poly, values)
        if rot is not None:
            pts = rot2d(pts, rot[0], rot[1])
        polygons.append(PCellPolygonGeom(
            name=poly.name, layer=poly.layer, points=tuple(pts)))

    for via in defn.vias:
        pos = (eval_expr(via.x, values), eval_expr(via.y, values))
        rot = _eval_rotate(via, values)
        if rot is not None:
            pos = rot2d([pos], rot[0], rot[1])[0]
        pad = eval_expr(via.pad_diameter, values)
        drill = eval_expr(via.drill_diameter, values)
        if not pad > drill > 0.0:
            raise PCellParamError(
                f"PCell {defn.name} 过孔 {via.name or pos} 焊盘直径 {pad} 必须"
                f"大于钻孔直径 {drill} 且为正")
        vias.append(PCellViaGeom(
            name=via.name, pad_layer=via.pad_layer, position=pos,
            pad_diameter=pad, drill_diameter=drill))

    return PCellGeometry(
        pcell=defn.name,
        params={k: values[k] for k in declared},
        boxes=tuple(boxes), paths=tuple(paths),
        polygons=tuple(polygons), vias=tuple(vias))


def _box_geom_from_flat(raw: dict[str, Any], cell: str,
                        values: dict[str, float]) -> PCellBoxGeom:
    """内核产出的盒 dict（数值直通求值面）→ PCellBoxGeom。"""
    box = PCellBox(layer=str(raw.get("layer", "metal")),
                   start=tuple(raw["start"]), stop=tuple(raw["stop"]),
                   priority=raw.get("priority", 10),
                   name=str(raw.get("name", "")))
    start = tuple(eval_expr(c, values) for c in box.start)
    stop = tuple(eval_expr(c, values) for c in box.stop)
    lo = tuple(min(s, t) for s, t in zip(start, stop, strict=True))
    hi = tuple(max(s, t) for s, t in zip(start, stop, strict=True))
    return PCellBoxGeom(name=box.name, layer=box.layer, start=start, stop=stop,
                        lo=lo, hi=hi, priority=eval_expr(box.priority, values))


def _path_geom_from_flat(raw: dict[str, Any], cell: str,
                         values: dict[str, float]) -> PCellPathGeom:
    path = PCellPath(points=tuple(tuple(p) for p in raw["points"]),
                     width=raw["width"], layer=str(raw.get("layer", "F.Cu")),
                     name=str(raw.get("name", "")))
    pts = [(eval_expr(x, values), eval_expr(y, values)) for x, y in path.points]
    return PCellPathGeom(name=path.name, layer=path.layer, points=tuple(pts),
                         width=eval_expr(path.width, values))


def _polygon_geom_from_flat(raw: dict[str, Any], cell: str,
                            values: dict[str, float]) -> PCellPolygonGeom:
    poly = PCellPolygon(points=tuple(tuple(p) for p in raw["points"]),
                        layer=str(raw.get("layer", "F.Cu")),
                        name=str(raw.get("name", "")))
    pts = [(eval_expr(x, values), eval_expr(y, values)) for x, y in poly.points]
    return PCellPolygonGeom(name=poly.name, layer=poly.layer, points=tuple(pts))


def _via_geom_from_flat(raw: dict[str, Any], cell: str,
                        values: dict[str, float]) -> PCellViaGeom:
    via = PCellVia(x=raw["position"][0], y=raw["position"][1],
                   pad_diameter=raw["pad_diameter"],
                   drill_diameter=raw["drill_diameter"],
                   pad_layer=str(raw.get("pad_layer", "F.Cu")),
                   name=str(raw.get("name", "")))
    return PCellViaGeom(
        name=via.name, pad_layer=via.pad_layer,
        position=(eval_expr(via.x, values), eval_expr(via.y, values)),
        pad_diameter=eval_expr(via.pad_diameter, values),
        drill_diameter=eval_expr(via.drill_diameter, values))


# ─── 序列化（YAML/Python 双面共用同一 dict 形状）──────────────────────────

_EXPR_OBJ_KEYS = ("start", "stop")


def _rot_to_dict(rotate_angle: Any, rotate_center: tuple[Any, Any] | None
                 ) -> dict[str, Any] | None:
    if rotate_angle is None:
        return None
    return {"angle_deg": rotate_angle, "center": list(rotate_center)}


def _rot_from_dict(raw: dict[str, Any], what: str) -> tuple[Any, tuple[Any, Any]]:
    rot = raw.get("rotate")
    if rot is None:
        return (None, None)
    if not isinstance(rot, dict) or "angle_deg" not in rot:
        raise PCellError(f"{what} 的 rotate 段须含 angle_deg: {rot!r}")
    center = rot.get("center")
    if center is None or len(center) != 2:
        raise PCellError(f"{what} 的 rotate.center 必须是 2 元素: {rot!r}")
    return (rot["angle_deg"], (center[0], center[1]))


def _pts_from_dict(raw_pts: Any, what: str, min_pts: int
                   ) -> tuple[tuple[Any, Any], ...]:
    pts = tuple(tuple(p) for p in (raw_pts or ()))
    if len(pts) < min_pts or any(len(p) != 2 for p in pts):
        raise PCellError(
            f"{what} 的 points 必须是 ≥{min_pts} 个 (x,y) 对: {raw_pts!r}")
    return pts


def def_to_dict(defn: PCellDef) -> dict[str, Any]:
    """PCellDef → 纯数据 dict（YAML/JSON 双兼容）。"""
    out: dict[str, Any] = {"name": defn.name}
    if defn.description:
        out["description"] = defn.description
    if defn.params:
        out["params"] = {
            p.name: _param_dict(p) for p in defn.params}
    if defn.variables:
        out["variables"] = {k: v for k, v in defn.variables}
    out["boxes"] = [
        {"layer": b.layer, "start": list(b.start), "stop": list(b.stop),
         "priority": b.priority, **({"name": b.name} if b.name else {}),
         **({"rotate": _rot_to_dict(b.rotate_angle, b.rotate_center)}
            if b.rotate_angle is not None else {})}
        for b in defn.boxes
    ]
    if defn.paths:
        out["paths"] = [_path_dict(p) for p in defn.paths]
    if defn.polygons:
        out["polygons"] = [_polygon_dict(p) for p in defn.polygons]
    if defn.vias:
        out["vias"] = [_via_dict(v) for v in defn.vias]
    if defn.kernel is not None:
        out["kernel"] = defn.kernel
    if defn.context_names:
        out["context"] = list(defn.context_names)
    return out


def _name_suffix(name: str) -> dict[str, Any]:
    return {"name": name} if name else {}


def _path_dict(p: PCellPath) -> dict[str, Any]:
    out: dict[str, Any] = {"layer": p.layer,
                           "points": [list(pt) for pt in p.points],
                           "width": p.width, **_name_suffix(p.name)}
    if p.rotate_angle is not None:
        out["rotate"] = _rot_to_dict(p.rotate_angle, p.rotate_center)
    return out


def _polygon_dict(p: PCellPolygon) -> dict[str, Any]:
    out: dict[str, Any] = {"layer": p.layer,
                           "points": [list(pt) for pt in p.points],
                           **_name_suffix(p.name)}
    if p.rotate_angle is not None:
        out["rotate"] = _rot_to_dict(p.rotate_angle, p.rotate_center)
    return out


def _via_dict(v: PCellVia) -> dict[str, Any]:
    out: dict[str, Any] = {"pad_layer": v.pad_layer, "x": v.x, "y": v.y,
                           "pad_diameter": v.pad_diameter,
                           "drill_diameter": v.drill_diameter,
                           **_name_suffix(v.name)}
    if v.rotate_angle is not None:
        out["rotate"] = _rot_to_dict(v.rotate_angle, v.rotate_center)
    return out


def _param_dict(p: PCellParam) -> dict[str, Any]:
    d: dict[str, Any] = {"default": p.default}
    if p.lo is not None:
        d["lo"] = p.lo
    if p.hi is not None:
        d["hi"] = p.hi
    if p.note:
        d["note"] = p.note
    return d


def def_from_dict(data: dict[str, Any]) -> PCellDef:
    """纯数据 dict → PCellDef。形状不对/名字缺失显式报错。"""
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise PCellError(f"PCell 定义缺 name: {data!r}")
    params: list[PCellParam] = []
    for pname, raw in (data.get("params") or {}).items():
        if isinstance(raw, (int, float)):
            params.append(PCellParam(name=pname, default=float(raw)))
            continue
        if not isinstance(raw, dict):
            raise PCellError(f"PCell {name} 参数 {pname} 形状非法: {raw!r}")
        params.append(PCellParam(
            name=pname,
            default=float(raw.get("default", 0.0)),
            lo=raw.get("lo"),
            hi=raw.get("hi"),
            note=str(raw.get("note", "")),
        ))
    variables = tuple((k, v) for k, v in (data.get("variables") or {}).items())
    boxes: list[PCellBox] = []
    for raw in data.get("boxes") or []:
        for key in _EXPR_OBJ_KEYS:
            if len(raw.get(key) or ()) != 3:
                raise PCellError(
                    f"PCell {name} 盒的 {key} 必须是 3 元素: {raw!r}")
        angle, center = _rot_from_dict(raw, f"PCell {name} 盒")
        boxes.append(PCellBox(
            layer=str(raw.get("layer", "metal")),
            start=tuple(raw["start"]),
            stop=tuple(raw["stop"]),
            priority=raw.get("priority", 10),
            name=str(raw.get("name", "")),
            rotate_angle=angle, rotate_center=center,
        ))
    paths: list[PCellPath] = []
    for raw in data.get("paths") or []:
        angle, center = _rot_from_dict(raw, f"PCell {name} 路径")
        paths.append(PCellPath(
            points=_pts_from_dict(raw.get("points"), f"PCell {name} 路径", 2),
            width=raw.get("width", 0),
            layer=str(raw.get("layer", "F.Cu")),
            name=str(raw.get("name", "")),
            rotate_angle=angle, rotate_center=center,
        ))
    polygons: list[PCellPolygon] = []
    for raw in data.get("polygons") or []:
        angle, center = _rot_from_dict(raw, f"PCell {name} 多边形")
        polygons.append(PCellPolygon(
            points=_pts_from_dict(raw.get("points"), f"PCell {name} 多边形", 3),
            layer=str(raw.get("layer", "F.Cu")),
            name=str(raw.get("name", "")),
            rotate_angle=angle, rotate_center=center,
        ))
    vias: list[PCellVia] = []
    for raw in data.get("vias") or []:
        for key in ("x", "y", "pad_diameter", "drill_diameter"):
            if raw.get(key) is None:
                raise PCellError(f"PCell {name} 过孔缺 {key}: {raw!r}")
        angle, center = _rot_from_dict(raw, f"PCell {name} 过孔")
        vias.append(PCellVia(
            x=raw["x"], y=raw["y"],
            pad_diameter=raw["pad_diameter"],
            drill_diameter=raw["drill_diameter"],
            pad_layer=str(raw.get("pad_layer", "F.Cu")),
            name=str(raw.get("name", "")),
            rotate_angle=angle, rotate_center=center,
        ))
    kernel = data.get("kernel")
    if kernel is not None and kernel not in KERNEL_REGISTRY:
        raise PCellError(
            f"PCell {name} 未知内核: {kernel!r}（可用: {sorted(KERNEL_REGISTRY)}）")
    if not (boxes or paths or polygons or vias or kernel is not None):
        raise PCellError(f"PCell {name} 至少需要一个原语（或声明 kernel）")
    return PCellDef(
        name=name,
        description=str(data.get("description", "")),
        params=tuple(params),
        variables=variables,
        boxes=tuple(boxes),
        context_names=tuple(data.get("context") or ()),
        paths=tuple(paths),
        polygons=tuple(polygons),
        vias=tuple(vias),
        kernel=kernel,
    )


def def_to_yaml(defn: PCellDef) -> str:
    return yaml.safe_dump(def_to_dict(defn), allow_unicode=True, sort_keys=False)


def def_from_yaml(path: str | Path) -> PCellDef:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise PCellError(f"PCell YAML 顶层必须是映射: {path}")
    return def_from_dict(data)


# ─── 既有模板迁移库（§10.2 B1 验收：3 个既有模板迁移到 DSL）──────────────
# 坐标表达式与 adapters/openems_templates 的几何段逐字同构（_mline_lines /
# _cpw_lines / _wstep_lines），默认值 = TEMPLATE_NOMINAL 同名条目；
# 冒烟等价由 tests/unit/test_pcell_dsl.py 对渲染器几何段实测钉死。
# LC-2 新单元（ms_bend/gnd_void/rf_*/via_rail）坐标域=毫米（Layout 口径）。

_CONTEXT_SCAFFOLD = ("H_SUB", "BOARD", "NEAR")  # render 脚手架注入的常量


def _mline_def() -> PCellDef:
    """均匀微带线（WP2.1 锚模板）：一条直带，两端 MSLPort 自画馈线。"""
    return def_from_dict({
        "name": "mline",
        "description": "均匀微带线：单直带金属，端口馈线由 MSLPort 补画",
        "params": {
            "w_mm": {"default": 1.113, "note": "线宽（skrf HJ 综合 50Ω 口径）"},
            "line_len_mm": {"default": 40.0, "note": "两端口间线长"},
        },
        "context": list(_CONTEXT_SCAFFOLD),
        "variables": {
            "W": "w_mm*1e-3", "L": "line_len_mm*1e-3",
            "Y0": "-L/2", "Y1": "L/2",
        },
        "boxes": [
            {"layer": "microstrip", "name": "line",
             "start": ["-W/2", "Y0", "H_SUB"],
             "stop": ["W/2", "Y1", "H_SUB"], "priority": 10},
        ],
    })


def _cpw_def() -> PCellDef:
    """均匀共面波导：中心带 + 两侧地（地延伸到域边，端口段地须自画）。"""
    return def_from_dict({
        "name": "cpw",
        "description": "均匀共面波导：中心带 + 两侧全域地（CPWG 口径）",
        "params": {
            "w_mm": {"default": 0.849, "note": "中心带宽（CPWG 共形映射闭式）"},
            "gap_mm": {"default": 0.2, "note": "缝宽"},
            "line_len_mm": {"default": 40.0, "note": "两端口间线长"},
        },
        "context": list(_CONTEXT_SCAFFOLD),
        "variables": {
            "W": "w_mm*1e-3", "GAP": "gap_mm*1e-3", "L": "line_len_mm*1e-3",
            "Y0": "-L/2", "Y1": "L/2",
        },
        "boxes": [
            {"layer": "cpw", "name": "center",
             "start": ["-W/2", "Y0", "H_SUB"],
             "stop": ["W/2", "Y1", "H_SUB"], "priority": 10},
            {"layer": "cpw", "name": "gnd_left",
             "start": ["-BOARD", "-BOARD", "H_SUB"],
             "stop": ["-W/2-GAP", "BOARD", "H_SUB"], "priority": 10},
            {"layer": "cpw", "name": "gnd_right",
             "start": ["W/2+GAP", "-BOARD", "H_SUB"],
             "stop": ["BOARD", "BOARD", "H_SUB"], "priority": 10},
        ],
    })


def _wstep_def() -> PCellDef:
    """微带宽度阶跃（WP2.2 不连续性基元）：窄段/宽段各半长，单阶在中点。"""
    return def_from_dict({
        "name": "wstep",
        "description": "微带宽度阶跃：窄段/宽段各半长，单阶梯跃在中点",
        "params": {
            "w1_mm": {"default": 1.1134, "note": "窄段线宽（50Ω 口径）"},
            "w2_mm": {"default": 1.897, "note": "宽段线宽（35Ω 口径）"},
            "line_len_mm": {"default": 40.0, "note": "总长"},
        },
        "context": list(_CONTEXT_SCAFFOLD),
        "variables": {
            "W1": "w1_mm*1e-3", "W2": "w2_mm*1e-3", "L": "line_len_mm*1e-3",
            "Y0": "-L/2", "YM": 0.0, "Y1": "L/2",
        },
        "boxes": [
            {"layer": "wstep", "name": "narrow",
             "start": ["-W1/2", "Y0", "H_SUB"],
             "stop": ["W1/2", "YM", "H_SUB"], "priority": 10},
            {"layer": "wstep", "name": "wide",
             "start": ["-W2/2", "YM", "H_SUB"],
             "stop": ["W2/2", "Y1", "H_SUB"], "priority": 10},
        ],
    })


def _ms_bend_def() -> PCellDef:
    """微带 L 弯（声明式 path 原语 + 旋转演示）。坐标域=毫米（Layout 口径）。"""
    return def_from_dict({
        "name": "ms_bend",
        "description": "微带 L 弯（path 原语）：两段正交走线，参数化刚体旋转"
                       "（坐标域=毫米，Layout 口径）",
        "params": {
            "w_mm": {"default": 1.113, "note": "线宽"},
            "l1_mm": {"default": 10.0, "note": "第一臂长（沿 +x）"},
            "l2_mm": {"default": 8.0, "note": "第二臂长（沿 +y）"},
            "rot_deg": {"default": 0.0, "note": "整体旋转角（度，绕原点）"},
        },
        "paths": [
            {"layer": "F.Cu", "name": "bend",
             "points": [[0, 0], ["l1_mm", 0], ["l1_mm", "l2_mm"]],
             "width": "w_mm",
             "rotate": {"angle_deg": "rot_deg", "center": [0, 0]}},
        ],
    })


def _gnd_void_def() -> PCellDef:
    """地窗（声明式 polygon 原语 + 绕心旋转演示）。坐标域=毫米。"""
    return def_from_dict({
        "name": "gnd_void",
        "description": "地窗（polygon 原语）：矩形挖铜窗，可绕自身中心旋转"
                       "（坐标域=毫米，Layout 口径）",
        "params": {
            "cx_mm": {"default": 0.0, "note": "窗中心 x"},
            "cy_mm": {"default": 0.0, "note": "窗中心 y"},
            "w_mm": {"default": 3.0, "note": "窗宽（x）"},
            "h_mm": {"default": 2.0, "note": "窗高（y）"},
            "rot_deg": {"default": 0.0, "note": "旋转角（度，绕窗中心）"},
        },
        "polygons": [
            {"layer": "F.Cu", "name": "void",
             "points": [["cx_mm-w_mm/2", "cy_mm-h_mm/2"],
                        ["cx_mm+w_mm/2", "cy_mm-h_mm/2"],
                        ["cx_mm+w_mm/2", "cy_mm+h_mm/2"],
                        ["cx_mm-w_mm/2", "cy_mm+h_mm/2"]],
             "rotate": {"angle_deg": "rot_deg", "center": ["cx_mm", "cy_mm"]}},
        ],
    })


def _gnd_via_quad_def() -> PCellDef:
    """接地过孔四（声明式 via 原语 + 旋转演示）。坐标域=毫米。"""
    return def_from_dict({
        "name": "gnd_via_quad",
        "description": "接地过孔四（via 原语声明面）：环绕中心的 ±d/2 四孔，"
                       "可整体旋转（坐标域=毫米，Layout 口径）",
        "params": {
            "cx_mm": {"default": 0.0, "note": "阵列中心 x"},
            "cy_mm": {"default": 0.0, "note": "阵列中心 y"},
            "d_mm": {"default": 1.0, "note": "对角跨距"},
            "pad_mm": {"default": 0.6, "note": "焊盘直径"},
            "drill_mm": {"default": 0.3, "note": "钻孔直径（须 <焊盘）"},
            "rot_deg": {"default": 0.0, "note": "整体旋转角（度）"},
        },
        "vias": [
            {"pad_layer": "F.Cu", "name": name,
             "x": f"cx_mm{sx}d_mm/2", "y": f"cy_mm{sy}d_mm/2",
             "pad_diameter": "pad_mm", "drill_diameter": "drill_mm",
             "rotate": {"angle_deg": "rot_deg", "center": ["cx_mm", "cy_mm"]}}
            for name, sx, sy in (("via_pp", "+", "+"), ("via_pm", "+", "-"),
                                 ("via_mp", "-", "+"), ("via_mm", "-", "-"))
        ],
    })


def _rf_taper_def() -> PCellDef:
    """N14 线性渐变段（内核 n14_taper）。坐标域=毫米。"""
    return def_from_dict({
        "name": "rf_taper",
        "description": "N14 线性渐变段（内核 n14_taper）：面积恒等式 "
                       "A=L·(w1+w2)/2（坐标域=毫米，Layout 口径）",
        "params": {
            "len_mm": {"default": 8.0, "note": "渐变段长"},
            "w1_mm": {"default": 1.113, "note": "起端线宽（50Ω 口径）"},
            "w2_mm": {"default": 1.897, "note": "末端线宽（35Ω 口径）"},
        },
        "kernel": "n14_taper",
    })


def _rf_miter_bend_def() -> PCellDef:
    """N14 45° 倒角 90° 弯（内核 n14_miter_bend）。坐标域=毫米。"""
    return def_from_dict({
        "name": "rf_miter_bend",
        "description": "N14 45° 倒角 90° 弯（内核 n14_miter_bend）：面积恒等"
                       "式 A=w(L1+L2)−c²/2（坐标域=毫米，Layout 口径）",
        "params": {
            "l1_mm": {"default": 6.0, "note": "角点前臂长"},
            "l2_mm": {"default": 6.0, "note": "角点后臂长"},
            "w_mm": {"default": 1.113, "note": "线宽"},
            "chamfer_mm": {"default": 0.5565, "note": "倒角量（微带惯用 w/2）"},
        },
        "kernel": "n14_miter_bend",
    })


def _rf_round_bend_def() -> PCellDef:
    """N14 圆角 90° 弯（内核 n14_round_bend）。坐标域=毫米。"""
    return def_from_dict({
        "name": "rf_round_bend",
        "description": "N14 圆角 90° 弯（内核 n14_round_bend）：面积收敛到 "
                       "A=w(L1+L2)−r·w·(2−π/2)（坐标域=毫米，Layout 口径）",
        "params": {
            "l1_mm": {"default": 6.0, "note": "角点前臂长"},
            "l2_mm": {"default": 6.0, "note": "角点后臂长"},
            "w_mm": {"default": 1.113, "note": "线宽"},
            "r_mm": {"default": 2.0, "note": "中心线圆角半径（须 >w/2）"},
            "n_arc": {"default": 32.0, "lo": 2.0, "note": "弧离散段数"},
        },
        "kernel": "n14_round_bend",
    })


def _via_rail_def() -> PCellDef:
    """接地过孔排（内核 via_rail，layout_generator via_fence 直线特例合流）。"""
    return def_from_dict({
        "name": "via_rail",
        "description": "接地过孔排（内核 via_rail，与 layout_generator "
                       "via_fence 同口径合流）：沿 +x 每 pitch 一孔"
                       "（坐标域=毫米，Layout 口径）",
        "params": {
            "n": {"default": 5.0, "lo": 1.0, "note": "过孔数"},
            "pitch_mm": {"default": 1.0, "note": "孔距"},
            "pad_mm": {"default": 0.6, "note": "焊盘直径"},
            "drill_mm": {"default": 0.3, "note": "钻孔直径（须 <焊盘）"},
            "x0_mm": {"default": 0.0, "note": "首孔 x"},
            "y0_mm": {"default": 0.0, "note": "轨 y"},
        },
        "kernel": "via_rail",
    })


def _guard_ring_fence_def() -> PCellDef:
    """LC-3 矩形闭合护环（内核 guard_ring_fence）。坐标域=毫米。"""
    return def_from_dict({
        "name": "guard_ring_fence",
        "description": "LC-3 矩形闭合护环（内核 guard_ring_fence）：沿 "
                       "w×h 周长每 pitch 一孔的接地护墙（坐标域=毫米，"
                       "Layout 口径）",
        "params": {
            "w_mm": {"default": 10.0, "note": "护环矩形宽（x）"},
            "h_mm": {"default": 6.0, "note": "护环矩形高（y）"},
            "pitch_mm": {"default": 1.0, "note": "孔距"},
            "pad_mm": {"default": 0.6, "note": "焊盘直径"},
            "drill_mm": {"default": 0.3, "note": "钻孔直径（须 <焊盘）"},
            "x0_mm": {"default": 0.0, "note": "矩形角点 x"},
            "y0_mm": {"default": 0.0, "note": "矩形角点 y"},
        },
        "kernel": "guard_ring_fence",
    })


def _cpw_ground_stitch_def() -> PCellDef:
    """LC-3 CPW 共面地+缝合带（内核 cpw_ground_stitch）。坐标域=毫米。"""
    return def_from_dict({
        "name": "cpw_ground_stitch",
        "description": "LC-3 CPW 共面地+缝合带（内核 cpw_ground_stitch）："
                       "中心带+两侧地多边形，地内缝合孔排沿 +x（坐标域="
                       "毫米，Layout 口径）",
        "params": {
            "length_mm": {"default": 20.0, "note": "线长（沿 +x）"},
            "w_mm": {"default": 0.849, "note": "中心带宽（CPWG 口径）"},
            "gap_mm": {"default": 0.2, "note": "缝宽"},
            "ground_width_mm": {"default": 2.0, "note": "每侧地延伸宽"},
            "strap_pitch_mm": {"default": 2.0, "note": "缝合孔距"},
            "pad_mm": {"default": 0.6, "note": "焊盘直径"},
            "drill_mm": {"default": 0.3, "note": "钻孔直径（须 <焊盘）"},
            "inset_mm": {"default": 0.5, "note": "孔心距缝缘内缩"
                        "（≥pad/2 且 ≤ground_width−pad/2）"},
            "x0_mm": {"default": 0.0, "note": "线起点 x"},
            "y0_mm": {"default": 0.0, "note": "中心线 y"},
        },
        "kernel": "cpw_ground_stitch",
    })


def _stitch_mesh_def() -> PCellDef:
    """LC-3 缝合网格（内核 stitch_mesh）。坐标域=毫米。"""
    return def_from_dict({
        "name": "stitch_mesh",
        "description": "LC-3 缝合网格（内核 stitch_mesh）：w×h 内每 pitch"
                       " 一孔的矩形孔阵（坐标域=毫米，Layout 口径）",
        "params": {
            "width_mm": {"default": 5.0, "note": "网格宽（x）"},
            "height_mm": {"default": 4.0, "note": "网格高（y）"},
            "pitch_x_mm": {"default": 1.0, "note": "x 向孔距"},
            "pitch_y_mm": {"default": 1.0, "note": "y 向孔距"},
            "pad_mm": {"default": 0.6, "note": "焊盘直径"},
            "drill_mm": {"default": 0.3, "note": "钻孔直径（须 <焊盘）"},
            "x0_mm": {"default": 0.0, "note": "网格角点 x"},
            "y0_mm": {"default": 0.0, "note": "网格角点 y"},
        },
        "kernel": "stitch_mesh",
    })


def _ground_void_def() -> PCellDef:
    """LC-3 地板开窗+可选护窗栅栏（内核 ground_void）。坐标域=毫米。"""
    return def_from_dict({
        "name": "ground_void",
        "description": "LC-3 地板开窗（内核 ground_void）：平面内矩形挖铜"
                       "窗 + 可选护窗栅栏（fence_offset_mm=0 即关，>0 为"
                       "孔心距窗边间距；坐标域=毫米，Layout 口径）",
        "params": {
            "plane_w_mm": {"default": 40.0, "note": "平面宽（x）"},
            "plane_h_mm": {"default": 30.0, "note": "平面高（y）"},
            "void_cx_mm": {"default": 20.0, "note": "窗中心 x"},
            "void_cy_mm": {"default": 15.0, "note": "窗中心 y"},
            "void_w_mm": {"default": 6.0, "note": "窗宽（x，须严格在平面内）"},
            "void_h_mm": {"default": 4.0, "note": "窗高（y，须严格在平面内）"},
            "fence_offset_mm": {"default": 0.8,
                                "note": "护窗栅栏间距（0=无栅栏）"},
            "fence_pitch_mm": {"default": 1.0, "note": "栅栏孔距"},
            "fence_pad_mm": {"default": 0.6, "note": "栅栏焊盘直径"},
            "fence_drill_mm": {"default": 0.3, "note": "栅栏钻孔直径"},
            "x0_mm": {"default": 0.0, "note": "平面角点 x"},
            "y0_mm": {"default": 0.0, "note": "平面角点 y"},
        },
        "kernel": "ground_void",
    })


PCELL_LIBRARY: dict[str, PCellDef] = {
    d.name: d for d in (_mline_def(), _cpw_def(), _wstep_def(),
                        _ms_bend_def(), _gnd_void_def(), _gnd_via_quad_def(),
                        _rf_taper_def(), _rf_miter_bend_def(),
                        _rf_round_bend_def(), _via_rail_def(),
                        _guard_ring_fence_def(), _cpw_ground_stitch_def(),
                        _stitch_mesh_def(), _ground_void_def())
}


def get_pcell(name: str) -> PCellDef:
    """按名取库中的 PCell 定义；未知名字列出可用项。"""
    if name not in PCELL_LIBRARY:
        raise KeyError(f"未知 PCell: {name}（可用: {sorted(PCELL_LIBRARY)}）")
    return PCELL_LIBRARY[name]


def evaluate_library(context: dict[str, float],
                     param_sets: Iterable[dict[str, Any]] | None = None
                     ) -> dict[str, PCellGeometry]:
    """整库求值便捷入口（param_sets 按序对应各 PCell，None=全默认）。

    注意：迁移的 3 模板需要 render 脚手架上下文（H_SUB/BOARD/NEAR），
    LC-2 新单元 context_names 为空、不受 context 影响。
    """
    sets = list(param_sets) if param_sets is not None else [None] * len(PCELL_LIBRARY)
    return {
        name: evaluate_pcell(defn, params, context)
        for (name, defn), params in zip(PCELL_LIBRARY.items(), sets,
                                        strict=True)
    }
