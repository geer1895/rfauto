"""tri_view——原理图↔版图↔3D 三视图联动服务（aurora_q 席位 Q-X38）。

定位：三视图**同源数据**交叉高亮——同一设计的原理图符号、版图 footprint、
3D 分层体以**位号（ref）为键 1:1 映射**，产出映射 JSON（每 ref 三视图位置
+高亮 id+一致性检查）与联动 SVG 三联（三面板并排、同 ref 同色、悬停任一
面板元素三面同亮）；geometry_lint 报告的问题对象经同一映射落到三视图位置
高亮。零新依赖（stdlib+pydantic 既有），纯离线（零 KiCad 子进程/零真机）。

三视图数据源（全部消费既有冻结面，只读不改）：

- **原理图面**＝``kicad_sch_service.spec_from_payload/spec_to_gen`` →
  ``adapters.kicad_sch_gen.render_schematic`` 产出 .kicad_sch s-expr 文本 →
  ``parse_sexpr`` 读符号实例（lib_id/at/Reference/Value/Footprint）+ 内嵌库
  符号几何（矩形体/引脚连接端）→ 世界坐标（Y 翻转约定同 ``readback_nets``：
  ``world=(inst_x+lx, inst_y-ly)``，实例 angle 恒 0）；网络连通＝
  ``readback_nets``（round-trip 证书读侧：按坐标 union-find 从产物文本回读，
  不信任输入 spec 自述）+ ``round_trip_certificate`` 二值证书随行；
- **版图面**＝``adapters.kicad_edb_bridge.kicad_to_edb_spec``（extract_pcb
  契约 → EDB spec：焊盘按铜层名单映射、坏几何跳过、warnings 如实）；
  footprint 清单（位号/值/位置）取 extract 契约 ``footprints[]`` 原表（桥接
  输出只含展平焊盘，footprint 级位置/值只在原表），焊盘几何/网络取桥接输出；
- **3D 面**＝分层体（layered bodies），两条来源：
  (a) 缺省：版图焊盘 × 叠层 z 账派生——EDB spec ``stackup.layers``
      （bottom_to_top）自底 z=0 向上累计：介质厚取 KiCad (stackup) 节实值；
      铜厚 **extract 契约未含**（桥接 ``copper_thickness_source`` 如实
      unresolved）→ 缺省零厚 sheet，调用方可显式声明 ``copper_thickness_mm``
      （铁律 7：零编造）；任一介质厚未解析（``placeholder_unresolved``）→
      ``z_mode="topological"``：z 退化为层序单位（``z_units="layer_index"``，
      介质 1 单位/铜 0），不按板总厚均摊编造（桥接同口径）；
  (b) 外部体：①:class:`TriBody` 列表（通用接口）；②Q-X37 exploded_view_service
      场景（3D 渲染在制席——**数据级接口约定**：其 ``render_exploded_view``
      信封 ``view`` 键 / ``build_scene`` 产物 ``schema="exploded-view/v0"`` 的
      ``solids[].box_mm`` 与 TriBody.coords 同布局，经
      :func:`bodies_from_exploded_view` 直接作 3D 面输入；本模块零 import 该
      在制面，schema 串钉漂移）；③``adapters.layered_stack_spec`` 分层体——
      :func:`bodies_from_layered_stack` 把 ``layered_stack_layout`` 经
      ``layered_stack_lint_projection`` 逐体转 TriBody（体名与 lint 投影
      **逐字同名**，lint 报告对象名直接落 3D 体）。外部体的位号一律经
      ``ref_bindings`` 显式绑定体名→位号（如 ``{"strip": "TL1"}``）。

1:1 映射口径（ref 标签为键）：refs = 原理图符号 ∪ 版图 footprint ∪ 3D 体
ref 并集；每 ref 三视图各恰一（原理图位号 SchSpec 已校验唯一；版图同位号
footprint ≥2 = ``duplicate_ref``；3D 体按 ref 成组——一个 ref 多体是常态，
组即一）。``one_to_one=True`` ⇔ 全部 ref 三视图俱在且零 duplicate（ERROR
级 issue 只这两族）。一致性诊断（WARN 级 issue，不进 1:1 判定）：值对拍
（sch Value vs footprint value）、引脚无同号焊盘、网络对拍（每 net 的
(ref,pin) 集 vs 版图 (ref,pad) 集）。

KiCad 网络命名口径（真机实证，非约定臆测）：根图局部 label "MID" 在 KiCad
网表/PCB 侧名为 "/MID"（runs/aurora_q/qcad1_smoke/rc_lowpass_net.net：
kicad-cli 10.0.6 ``sch export netlist`` 实读 "/GND" "/MID" "/VIN"）——版图
网名恰一个前导 "/" 且余部不含 "/"（根图）时归一去 "/" 再与原理图 label 名
比对（:func:`normalize_kicad_net`）；层次图 "/sheet/X" 不归一（本生成器单根图）。

交叉高亮数据：每 ref 一个稳定色（tab10 调色板按 refs 排序序号轮转）与三面板
元素 id（``sch-<sid>``/``pcb-<sid>``/``3d-<sid>``，每面板每 ref 恰一）；sid=
ref 的单射转义（:func:`ref_sid`）。SVG 内 ``data-ref=<sid>`` 承载联动（内联
脚本悬停三面同亮 ``hov``；静态预高亮 ``hl``；lint 标注 ``lint-error``/
``lint-warn``）；网络同理 ``data-net=<sid>``。

geometry_lint 标注（:func:`annotate_lint`）：报告 ``issues[].objects`` 逐名
解析——①3D 体名（含 port 体）→ 体+体 ref；②位号；③版图焊盘名（桥接口径
``<ref>-<number>``）；均不中 = unresolved 如实列出（不丢弃、不猜测）。每对象
给三视图位置（sch bbox / pcb bbox / 3D box；无 ref 的体只有 3D 位置，sch/pcb
=None 如实）。:func:`tri_view_lint_projection` 把 3D 面投影为 LintGeometry
兼容 dict（TriBody 即 LintBox 子类：体名/坐标布局逐字同 lint 口径）——自查
（``self_lint``）即对 3D 面跑 lint_geometry 再标注回三视图。注意 lint ④
不判零厚 sheet 相交（lint 口径）：缺省零厚铜下焊盘碰撞需显式声明铜厚。

坐标与单位：原理图 mm（KiCad schematic 坐标，Y 向下）；版图 mm（KiCad 板
坐标，Y 向下）；3D x/y 同版图、z 自底向上（mm 或层序单位）。三视图各自
坐标系，联动按 ref 键而非几何对应。SVG 显示参数（面板尺寸/等轴测 30°/z 显示
映射系数）=纯显示常量（非物理数值，铁律 7 不涉；JSON 恒为原坐标）。

诚实边界（如实登记）：
1. extract 契约无焊盘/footprint 旋转角——焊盘矩形按未旋转 w/h 轴对齐
   （90° 旋转件 w/h 互换）；无 footprint 库名（fpid）——sch Footprint 属性
   只回显不对拍；
2. 3D 缺省面只含介质板+焊盘体（过孔/走线/zone 只在版图面）；
3. 原理图仅支持实例 angle=0（自产恒 0；外部非 0 同 readback_nets 拒绝）；
4. 版图同位号多 footprint 时焊盘按位号合并（桥接展平后不可区分），
   duplicate_ref 如实 ERROR。

本模块不带 ``__all__``：按 public_api 快照口径记私有（tests/gold/
public_api.json 零漂移；geometry_lint_service/layered_stack_spec 同款）。
"""

from __future__ import annotations

import hashlib
import html
import itertools
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import model_validator

from rfauto.adapters.kicad_edb_bridge import kicad_to_edb_spec
from rfauto.adapters.kicad_sch_gen import (
    SchGridLayout,
    parse_sexpr,
    readback_nets,
    render_schematic,
)
from rfauto.adapters.layered_stack_spec import (
    LayeredStackSpec,
    layered_stack_layout,
    layered_stack_lint_projection,
)
from rfauto.service.envelope import error_envelope, normalize_errors, ok_envelope
from rfauto.service.geometry_lint_service import (
    LintBox,
    is_air_material,
    is_metal_material,
    lint_geometry,
)
from rfauto.service.kicad_sch_service import (
    round_trip_certificate,
    spec_from_payload,
    spec_to_gen,
)

# ── 口径常量 ───────────────────────────────────────────────────────────

#: 三视图结果 schema 串（映射 JSON / 信封 ``schema`` 键）
TRI_VIEW_SCHEMA = "rfauto-tri-view-v1"
#: 3D 体载荷 schema 串（文件形态必须带，防形态漂移静默张冠李戴——SchSpec 同惯例）
BODIES_SCHEMA = "rfauto-tri-view-bodies-v1"
#: Q-X37 exploded_view_service 场景 schema（数据级接口约定：render_exploded_view
#: 信封 ``view`` 键 / build_scene 产物；本模块零 import 该在制面，schema 串钉漂移）
EXPLODED_VIEW_SCHEMA = "exploded-view/v0"
#: 三视图键（顺序=SVG 面板序=views_present 序）
VIEWS: tuple[str, ...] = ("sch", "pcb", "3d")
#: ref 稳定色调色板（matplotlib tab10 十色；refs 排序序号轮转）
PALETTE: tuple[str, ...] = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)
#: lint 级别秩（高亮取最高级；未知级别秩 0=只入标注不着色）
_LEVEL_RANK = {"WARN": 1, "ERROR": 2}
#: 判 1:1 映射断裂的 issue 族（ERROR 级）
_ONE_TO_ONE_KINDS = frozenset({"missing_in_view", "duplicate_ref"})
#: 3D 体载荷允许键
_BODIES_PAYLOAD_KEYS = frozenset({"schema", "bodies", "layered_stack", "exploded_view",
                                  "ref_bindings", "units"})
#: 3D 体载荷来源键（恰含其一）
_BODIES_SOURCE_KEYS = ("bodies", "layered_stack", "exploded_view")

# ── SVG 显示常量（纯显示参数，非物理数值——铁律 7 不涉）───────────────────

PANEL_W = 420.0
PANEL_H = 340.0
PANEL_GAP = 16.0
PANEL_PAD = 24.0
TITLE_H = 22.0
FOOTER_H = 26.0
#: 3D 面等轴测投影角（度）
ISO_ANGLE_DEG = 30.0
#: 3D 面 z 显示映射：相邻 z 断点区间显示厚 = max(x 跨度, y 跨度) ×
#: (Z_MIN_FRACTION + Z_PROP_FRACTION × 区间厚/总厚)——薄铜可见不夸张、厚介质成板
#: （等距逐断点展开会把 35µm 铜画成与 1.5mm 介质同高的柱，首版目检实证弃用）
Z_MIN_FRACTION = 0.01
Z_PROP_FRACTION = 0.2

_PANEL_TITLES = {
    "sch": "原理图 · kicad_sch_gen",
    "pcb": "版图 · kicad_edb_bridge",
    "3d": "3D 分层体",
}

_SVG_STYLE = """\
.bg{fill:#fafafa}
.frame{fill:#ffffff;stroke:#555555;stroke-width:1}
.title{font-size:12px;font-weight:bold;fill:#222222}
.foot{font-size:11px;fill:#333333}
.empty{font-size:11px;fill:#999999}
.reflabel{font-size:9px;fill:#111111;pointer-events:none}
.netlabel{font-size:8px;fill:#2b7a2b}
.wire{fill:none;stroke:#2b7a2b;stroke-width:1}
.pin{stroke:#333333;stroke-width:1}
.board{fill:#f4f1e6;stroke:#8a7f5a;stroke-width:1}
.trace{fill:none;stroke:#b87333;stroke-linecap:round;stroke-opacity:0.6}
.via{fill:#999999;stroke:#555555;stroke-width:0.5}
.pad-orphan{fill:#cccccc;stroke:#888888;stroke-width:0.5}
.topface{fill:none;stroke:#333333;stroke-opacity:0.35;stroke-width:0.4;pointer-events:none}
.hl rect,.hl line,.hl circle,.hl polygon,polygon.hl{stroke:#000000;stroke-width:2.5px}
.lint-warn rect,.lint-warn line,.lint-warn polygon,polygon.lint-warn{stroke:#ff7f0e;stroke-width:2.5px;stroke-dasharray:4 2}
.lint-error rect,.lint-error line,.lint-error polygon,polygon.lint-error{stroke:#d62728;stroke-width:3px;stroke-dasharray:6 2}
.hov rect,.hov line,.hov circle,.hov polygon,polygon.hov{stroke:#000000;stroke-width:3px;stroke-dasharray:none}
.nhov{stroke:#e377c2;stroke-width:2.5px}
"""

#: 联动脚本（静态文本；悬停任一 data-ref/data-net 元素 → 三面板同键元素同亮）
_SVG_SCRIPT = (
    "(function(){var d=document;"
    "function tog(a,v,c,on){var n=d.querySelectorAll('['+a+'=\"'+v+'\"]');"
    "for(var i=0;i<n.length;i++){n[i].classList.toggle(c,on);}}"
    "function bind(a,c){var n=d.querySelectorAll('['+a+']');"
    "for(var i=0;i<n.length;i++){(function(e){var v=e.getAttribute(a);"
    "e.addEventListener('mouseenter',function(){tog(a,v,c,true);});"
    "e.addEventListener('mouseleave',function(){tog(a,v,c,false);});})(n[i]);}}"
    "bind('data-ref','hov');bind('data-net','nhov');})();"
)


class TriViewError(ValueError):
    """三视图构建输入错误（errors 列表随行，服务入口转 error 信封）。"""

    def __init__(self, errors: Any) -> None:
        self.errors = normalize_errors(errors)
        super().__init__("; ".join(self.errors))


# ── 3D 体 schema（Q-X37 接口约定面）───────────────────────────────────────


class TriBody(LintBox):
    """3D 面一个分层体（LintBox 子类：lint 投影=字段子集，名/坐标布局逐字同）。

    通用外部 3D 接口：按本 schema 交付即可直接作 3D 面输入（Q-X37 场景另有
    数据级适配 :func:`bodies_from_exploded_view`）——``coords`` 布局
    ``(x_lo, y_lo, z_lo, x_hi, y_hi, z_hi)``
    =LintBox 口径（注意 ``layered_stack_layout`` 的 box 是
    ``(x0, x1, y0, y1, z0, z1)``，转置见 :func:`bodies_from_layered_stack`）；
    ``ref``=联动键（None=上下文体，只入 3D 面不入 1:1 映射）；
    ``role="port"``=零厚端口片（恰一轴零厚，lint 投影还原为 LintPort）。
    """

    ref: str | None = None
    layer: str | None = None
    net: str | None = None
    role: Literal["body", "port"] = "body"
    port_kind: Literal["wave", "lumped"] = "wave"
    multimode: bool = False

    @model_validator(mode="after")
    def _tri_checks(self) -> TriBody:
        if not all(math.isfinite(float(c)) for c in self.coords):
            raise ValueError(f"体 {self.name!r} coords 含非有限数值: {self.coords}")
        if self.ref is not None and not self.ref.strip():
            raise ValueError(f"体 {self.name!r} ref 为空串（无 ref 请用 null）")
        if self.role == "port":
            zero_axes = [k for k, e in enumerate(self.extent()) if e == 0.0]
            if len(zero_axes) != 1:
                raise ValueError(
                    f"port 体 {self.name!r} 必须恰一轴零厚（端口 sheet），"
                    f"得 extent={self.extent()}")
        return self


# ── 小工具 ─────────────────────────────────────────────────────────────


def _finite(value: Any) -> float | None:
    """int/float（非 bool、有限）→ float，其余 None（桥接 _num 同口径，不隐式转换）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _pin_key(pin: str) -> tuple[int, int, str]:
    """引脚/焊盘号排序键：纯数字按数值排前，其余字典序排后（生成器同口径）。"""
    return (0, int(pin), "") if pin.isdigit() else (1, 0, pin)


def _rp_key(rp: tuple[str, str] | list[str]) -> tuple[str, tuple[int, int, str]]:
    return (rp[0], _pin_key(rp[1]))


def ref_sid(text: str) -> str:
    """位号/网名 → SVG id 安全串（单射）：ASCII 字母数字与 '-' 保留、'_'→'__'、
    其余字符→``_<十六进制码点>_``；空串→``_``（非空输入永不产出单个 '_'）。"""
    out: list[str] = []
    for ch in str(text):
        if ch == "_":
            out.append("__")
        elif ch.isascii() and (ch.isalnum() or ch == "-"):
            out.append(ch)
        else:
            out.append(f"_{ord(ch):x}_")
    return "".join(out) or "_"


def normalize_kicad_net(name: str) -> str:
    """KiCad 根图局部 label 网名归一："/X"→"X"（余部不含 "/" 时；见模块 docstring 实证）。"""
    s = str(name)
    if len(s) > 1 and s.startswith("/") and "/" not in s[1:]:
        return s[1:]
    return s


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _union2(boxes: list[list[float] | None]) -> list[float] | None:
    real = [b for b in boxes if b is not None]
    if not real:
        return None
    return [min(b[0] for b in real), min(b[1] for b in real),
            max(b[2] for b in real), max(b[3] for b in real)]


def _union3(boxes: list[Any]) -> list[float] | None:
    real = [list(b) for b in boxes if b is not None]
    if not real:
        return None
    return [min(b[0] for b in real), min(b[1] for b in real), min(b[2] for b in real),
            max(b[3] for b in real), max(b[4] for b in real), max(b[5] for b in real)]


def _q4(p: list[float] | tuple[float, float]) -> tuple[float, float]:
    """坐标量化（1e-4 mm，readback_nets 同口径）——wire 端点↔label 锚点配对用。"""
    return (round(float(p[0]), 4), round(float(p[1]), 4))


def _jsonable(obj: Any) -> Any:
    """tuple→list 等 JSON 原生化（信封与落盘映射 JSON 逐键同形）。"""
    return json.loads(json.dumps(obj, ensure_ascii=False))


def _issue(kind: str, level: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"kind": kind, "level": level, **fields, "message": message}


# ── s-expr 读取（kicad_sch_gen.parse_sexpr 产物；节点=list，[0]=tag）────────


def _sx_sub(node: Any, tag: str) -> list | None:
    if not isinstance(node, list):
        return None
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _sx_subs(node: Any, tag: str) -> list[list]:
    if not isinstance(node, list):
        return []
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == tag]


def _sx_xy(node: Any) -> tuple[float, float] | None:
    if not isinstance(node, list) or len(node) < 3:
        return None
    try:
        return (float(node[1]), float(node[2]))
    except (TypeError, ValueError):
        return None


def _sx_prop(node: list, name: str) -> str:
    for p in _sx_subs(node, "property"):
        if len(p) > 2 and p[1] == name:
            return str(p[2])
    return ""


def _lib_geometry(root: list) -> dict[str, dict[str, Any]]:
    """lib_symbols → {lib_id: {"rects": [(x0,y0,x1,y1)], "pins": {号: (lx, ly)}}}（局部坐标 Y 向上）。"""
    out: dict[str, dict[str, Any]] = {}
    for sym in _sx_subs(_sx_sub(root, "lib_symbols"), "symbol"):
        if len(sym) < 2:
            continue
        rects: list[tuple[float, float, float, float]] = []
        pins: dict[str, tuple[float, float]] = {}
        for child in sym[2:]:
            if not (isinstance(child, list) and child and child[0] == "symbol"):
                continue
            for rect in _sx_subs(child, "rectangle"):
                s = _sx_xy(_sx_sub(rect, "start"))
                e = _sx_xy(_sx_sub(rect, "end"))
                if s is not None and e is not None:
                    rects.append((s[0], s[1], e[0], e[1]))
            for pin in _sx_subs(child, "pin"):
                at = _sx_xy(_sx_sub(pin, "at"))
                num = _sx_sub(pin, "number")
                if at is not None and num is not None and len(num) > 1:
                    pins[str(num[1])] = at
        out[str(sym[1])] = {"rects": rects, "pins": pins}
    return out


# ── 原理图面 ───────────────────────────────────────────────────────────


def schematic_view(spec: Any, layout: SchGridLayout | None = None) -> dict[str, Any]:
    """SchSpec 载荷 → 原理图面（符号清单+引脚世界坐标+导线/label+回读网络+证书）。

    位置一律取 **render_schematic 产物文本**（parse_sexpr 读回，KiCad 打开所见
    即此），网络取 ``readback_nets``（产物回读，不信 spec 自述）。输入非法/
    实例 angle≠0 → ValueError（服务入口转 error 信封）。
    """
    sp = spec_from_payload(spec)
    comps, nets = spec_to_gen(sp)
    text = render_schematic(comps, nets, layout)
    root = parse_sexpr(text)[0]
    libs = _lib_geometry(root)
    symbols: dict[str, dict[str, Any]] = {}
    for sym in _sx_subs(root, "symbol"):
        lib_node = _sx_sub(sym, "lib_id")
        at_node = _sx_sub(sym, "at")
        at = _sx_xy(at_node)
        if lib_node is None or len(lib_node) < 2 or at is None:
            continue
        if at_node is not None and len(at_node) > 3 and float(at_node[3]) != 0.0:
            raise ValueError(f"实例 angle={at_node[3]} 不受支持（自产恒 0，readback_nets 同口径）")
        lib_id = str(lib_node[1])
        ref = _sx_prop(sym, "Reference")
        geom = libs.get(lib_id, {"rects": [], "pins": {}})
        x, y = at
        pins = {num: [x + lx, y - ly] for num, (lx, ly)
                in sorted(geom["pins"].items(), key=lambda kv: _pin_key(kv[0]))}
        rects = [_rect(x + r[0], y - r[1], x + r[2], y - r[3]) for r in geom["rects"]]
        bbox = _union2([*rects, *([p[0], p[1], p[0], p[1]] for p in pins.values())])
        symbols[ref] = {
            "lib_id": lib_id,
            "value": _sx_prop(sym, "Value"),
            "footprint": _sx_prop(sym, "Footprint"),
            "at": [x, y],
            "body": rects[0] if rects else None,
            "bbox": bbox or [x, y, x, y],
            "pins": pins,
        }
    labels: list[dict[str, Any]] = []
    for lab in _sx_subs(root, "label"):
        a = _sx_xy(_sx_sub(lab, "at"))
        if a is not None and len(lab) > 1:
            labels.append({"name": str(lab[1]), "at": [a[0], a[1]]})
    anchor_net = {_q4(lb["at"]): lb["name"] for lb in labels}
    wires: list[dict[str, Any]] = []
    for w in _sx_subs(root, "wire"):
        pts = [p for p in (_sx_xy(n) for n in _sx_subs(_sx_sub(w, "pts"), "xy")) if p is not None]
        if len(pts) < 2:
            continue
        net = next((anchor_net[_q4(p)] for p in pts if _q4(p) in anchor_net), None)
        wires.append({"pts": [[p[0], p[1]] for p in pts], "net": net})
    rb = readback_nets(text)
    cert = round_trip_certificate(sp, text)
    bbox = _union2([
        *(s["bbox"] for s in symbols.values()),
        *([p[0], p[1], p[0], p[1]] for w in wires for p in w["pts"]),
        *([lb["at"][0], lb["at"][1], lb["at"][0], lb["at"][1]] for lb in labels),
    ])
    return {
        "units": "mm",
        "symbols": dict(sorted(symbols.items())),
        "labels": labels,
        "wires": wires,
        "nets": {k: [[r, p] for r, p in v] for k, v in sorted(rb.nets.items())},
        "unnamed_pins": [[r, p] for r, p in rb.unnamed_pins],
        "certificate_pass": bool(cert["pass"]),
        "certificate_diff": cert["diff"],
        "bbox": bbox,
        "sch_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "sch_bytes": len(text.encode("utf-8")),
    }


# ── 版图面 ─────────────────────────────────────────────────────────────


def _side(layer_set: set[str], top: str, bottom: str) -> str | None:
    if not layer_set:
        return None
    on_top, on_bottom = top in layer_set, bottom in layer_set
    if top == bottom:
        return "top" if on_top else "inner"
    if on_top and on_bottom:
        return "both"
    if on_top:
        return "top"
    return "bottom" if on_bottom else "inner"


def _outline_bbox(outline: Any) -> list[float] | None:
    if not isinstance(outline, dict):
        return None
    lo, hi = outline.get("min_mm"), outline.get("max_mm")
    if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) == 2 and len(hi) == 2):
        return None
    vals = [_finite(v) for v in (*lo, *hi)]
    if any(v is None for v in vals):
        return None
    x0, y0, x1, y1 = (float(v) for v in vals)  # type: ignore[arg-type]
    return _rect(x0, y0, x1, y1)


def layout_view(pcb: Any) -> dict[str, Any]:
    """extract_pcb 契约 → 版图面（footprint 清单+焊盘几何/网络+走线/过孔/板框）。

    桥接失败契约（ok=False）→ :class:`TriViewError`（errors 原样透传）。
    """
    spec = kicad_to_edb_spec(pcb)
    if not spec.get("ok"):
        raise TriViewError(["版图桥接失败（kicad_edb_bridge.kicad_to_edb_spec）",
                            *normalize_errors(spec.get("errors"))])
    copper = [str(x) for x in pcb["board"].get("copper_layers") or []]  # 桥接已校验非空
    raw = pcb.get("footprints")
    fps: dict[str, dict[str, Any]] = {}
    fp_count: Counter[str] = Counter()
    unreferenced = 0
    for fp in raw if isinstance(raw, list) else []:
        if not isinstance(fp, dict):
            continue
        ref = str(fp.get("reference", ""))
        if not ref:
            unreferenced += 1
            continue
        fp_count[ref] += 1
        entry = fps.setdefault(ref, {"value": str(fp.get("value", "")), "positions": [], "pads": []})
        x, y = _finite(fp.get("x_mm")), _finite(fp.get("y_mm"))
        if x is not None and y is not None:
            entry["positions"].append([x, y])
    orphan_pads: list[dict[str, Any]] = []
    for p in spec["pads"]:
        x, y, w, h = p["x_mm"], p["y_mm"], p["w_mm"], p["h_mm"]
        pad = {
            "name": p["name"], "number": p["number"], "net": p["net"],
            "net_norm": normalize_kicad_net(p["net"]), "layers": list(p["layers"]),
            "center": [x, y], "rect": _rect(x - w / 2.0, y - h / 2.0, x + w / 2.0, y + h / 2.0),
            "shape": p["shape"],
        }
        ref = p["reference"]
        if ref and ref in fps:
            fps[ref]["pads"].append(pad)
        else:
            orphan_pads.append(pad)
    top, bottom = copper[0], copper[-1]
    for ref, e in fps.items():
        e["count"] = fp_count[ref]
        pos0 = e["positions"][0] if e["positions"] else None
        e["bbox"] = _union2([pd["rect"] for pd in e["pads"]]) or (
            [pos0[0], pos0[1], pos0[0], pos0[1]] if pos0 else None)
        bb = e["bbox"]
        e["position"] = pos0 or ([(bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0] if bb else None)
        layer_set = {ly for pd in e["pads"] for ly in pd["layers"]}
        e["layers"] = [c for c in copper if c in layer_set]
        e["side"] = _side(layer_set, top, bottom)
    nets: dict[str, list[list[str]]] = {}
    for ref in sorted(fps):
        for pd in fps[ref]["pads"]:
            if not pd["net_norm"]:
                continue
            members = nets.setdefault(pd["net_norm"], [])
            if [ref, pd["number"]] not in members:
                members.append([ref, pd["number"]])
    for members in nets.values():
        members.sort(key=_rp_key)
    traces = [{"net": t["net"], "net_norm": normalize_kicad_net(t["net"]), "layer": t["layer"],
               "width_mm": t["width_mm"], "points_mm": t["points_mm"]} for t in spec["traces"]]
    vias = [{"net": v["net"], "net_norm": normalize_kicad_net(v["net"]), "x_mm": v["x_mm"],
             "y_mm": v["y_mm"], "pad_diameter_mm": v["pad_diameter_mm"], "drill_mm": v["drill_mm"]}
            for v in spec["vias"]]
    outline_bbox = _outline_bbox(spec.get("outline"))
    content = _union2([
        *(pd["rect"] for e in fps.values() for pd in e["pads"]),
        *(pd["rect"] for pd in orphan_pads),
        *(_rect(min(p[0] for p in t["points_mm"]) - t["width_mm"] / 2.0,
                min(p[1] for p in t["points_mm"]) - t["width_mm"] / 2.0,
                max(p[0] for p in t["points_mm"]) + t["width_mm"] / 2.0,
                max(p[1] for p in t["points_mm"]) + t["width_mm"] / 2.0) for t in traces),
        *(_rect(v["x_mm"] - v["pad_diameter_mm"] / 2.0, v["y_mm"] - v["pad_diameter_mm"] / 2.0,
                v["x_mm"] + v["pad_diameter_mm"] / 2.0, v["y_mm"] + v["pad_diameter_mm"] / 2.0)
          for v in vias),
    ])
    return {
        "units": "mm",
        "copper_layers": copper,
        "footprints": dict(sorted(fps.items())),
        "orphan_pads": orphan_pads,
        "duplicate_refs": sorted(r for r, c in fp_count.items() if c > 1),
        "unreferenced_footprints": unreferenced,
        "nets": dict(sorted(nets.items())),
        "traces": traces,
        "vias": vias,
        "outline_bbox": outline_bbox,
        "bbox": outline_bbox or content,
        "stackup": spec["stackup"],
        "bridge_counts": spec["counts"],
        "warnings": list(spec["warnings"]),
    }


# ── 3D 面 ──────────────────────────────────────────────────────────────


def _d3(bodies: list[TriBody], *, source: str, z_mode: str, z_units: str,
        layers: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None) -> dict[str, Any]:
    dup = sorted(n for n, c in Counter(b.name for b in bodies).items() if c > 1)
    if dup:
        raise TriViewError(f"3D 体名重复: {dup}（体名即 lint 对象名，必须唯一）")
    return {
        "source": source, "z_mode": z_mode, "z_units": z_units,
        "layers": list(layers or []),
        "bodies": [b.model_dump(mode="json") for b in bodies],
        "bbox": _union3([b.coords for b in bodies]),
        "warnings": list(warnings or []),
    }


def stack_bodies(lv: dict[str, Any], *, copper_thickness_mm: float | None = None) -> dict[str, Any]:
    """版图面 × EDB 叠层 z 账 → 3D 分层体（介质板+焊盘体；口径见模块 docstring (a)）。"""
    warnings: list[str] = []
    cu_decl: float | None = None
    if copper_thickness_mm is not None:
        cu_decl = _finite(copper_thickness_mm)
        if cu_decl is None or cu_decl <= 0.0:
            raise TriViewError(f"copper_thickness_mm 必须为正有限数（得 {copper_thickness_mm!r}）")
    layers = lv["stackup"]["layers"]  # bottom_to_top（EDB 惯例）
    unresolved = [str(ly["name"]) for ly in layers
                  if ly.get("type") == "dielectric" and _finite(ly.get("thickness_mm")) is None]
    physical = not unresolved
    if not physical:
        warnings.append(
            f"介质厚未解析 {unresolved}（KiCad 无 (stackup) 节/桥接 placeholder）——3D z 退化为"
            "层序单位 topological（介质 1/铜 0），不按板总厚均摊编造")
        if cu_decl is not None:
            warnings.append("topological 模式下 copper_thickness_mm 不适用（z 为层序单位非 mm），已忽略")
    z = 0.0
    table: list[dict[str, Any]] = []
    z_of: dict[str, tuple[float, float]] = {}
    for ly in layers:
        name = str(ly["name"])
        if ly.get("type") == "copper":
            use_decl = physical and cu_decl is not None
            t = float(cu_decl) if use_decl and cu_decl is not None else 0.0
            src = "declared" if use_decl else "sheet_unresolved"
        else:
            t = float(ly["thickness_mm"]) if physical else 1.0
            src = "kicad_stackup" if physical else "topological_unit"
        table.append({"name": name, "type": str(ly.get("type")), "z_lo": z, "z_hi": z + t,
                      "thickness_source": src})
        z_of[name] = (z, z + t)
        z += t
    used: Counter[str] = Counter()

    def _uniq(base: str) -> str:
        used[base] += 1
        return base if used[base] == 1 else f"{base}#{used[base]}"

    bodies: list[TriBody] = []
    ext = lv["outline_bbox"] or lv["bbox"]
    if ext is None:
        warnings.append("版图无板框且无焊盘/走线/过孔内容——3D 介质板不生成")
    else:
        for row in table:
            if row["type"] == "dielectric" and row["z_hi"] > row["z_lo"]:
                bodies.append(TriBody(
                    name=_uniq(f"diel:{row['name']}"), material="dielectric", solve_inside=True,
                    is_metal=False, layer=row["name"],
                    coords=(ext[0], ext[1], row["z_lo"], ext[2], ext[3], row["z_hi"])))
    pad_sets = [(ref, fp["pads"]) for ref, fp in lv["footprints"].items()]
    pad_sets.append((None, lv["orphan_pads"]))
    for ref, pads in pad_sets:
        for pad in pads:
            r = pad["rect"]
            for layer in pad["layers"]:
                z0, z1 = z_of[layer]
                bodies.append(TriBody(
                    name=_uniq(f"pad:{pad['name']}@{layer}"), material="copper", is_metal=True,
                    solve_inside=False, ref=ref, layer=layer, net=pad["net"] or None,
                    coords=(r[0], r[1], z0, r[2], r[3], z1)))
    return _d3(bodies, source="pcb_stack", z_mode="physical" if physical else "topological",
               z_units="mm" if physical else "layer_index", layers=table, warnings=warnings)


def bodies_from_layered_stack(spec: Any = None, *,
                              ref_bindings: dict[str, str] | None = None) -> list[TriBody]:
    """layered_stack spec → TriBody 列表（体名=``layered_stack_lint_projection`` 逐字同名）。

    ``spec``：None/dict（LayeredStackSpec 字段覆盖，{}=名义）/LayeredStackSpec。
    ``ref_bindings``：{体名或端口名: 位号}；未知体名 → ValueError（列可用名）。
    盒坐标直取 lint 投影（LintBox 布局），端口按 sheet 轴还原零厚 port 体。
    """
    sp = spec if isinstance(spec, LayeredStackSpec) else LayeredStackSpec.model_validate(spec or {})
    layout = layered_stack_layout(sp)
    proj = layered_stack_lint_projection(layout)
    binds = {str(k): str(v) for k, v in (ref_bindings or {}).items()}
    names = {b["name"] for b in proj["boxes"]} | {p["name"] for p in proj["ports"]}
    unknown = sorted(set(binds) - names)
    if unknown:
        raise ValueError(f"ref_bindings 含未知体名 {unknown}（可用: {sorted(names)}）")
    layer_of = {str(seg["name"]): f"layer{seg['layer']}" for seg in layout["stack_solids"]}
    out: list[TriBody] = []
    for b in proj["boxes"]:
        out.append(TriBody(name=b["name"], material=b["material"], solve_inside=b["solve_inside"],
                           coords=b["coords"], is_metal=b.get("is_metal"),
                           ref=binds.get(b["name"]), layer=layer_of.get(b["name"])))
    for p in proj["ports"]:
        sheet = p["sheet"]
        ax = "xyz".index(sheet["axis"])
        tang = [k for k in range(3) if k != ax]
        lo, hi = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        lo[ax] = hi[ax] = float(sheet["pos"])
        lo[tang[0]], hi[tang[0]] = (float(v) for v in sheet["u"])
        lo[tang[1]], hi[tang[1]] = (float(v) for v in sheet["v"])
        out.append(TriBody(name=p["name"], material="port", role="port", port_kind=p["kind"],
                           multimode=bool(p.get("multimode", False)),
                           coords=(lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]),
                           ref=binds.get(p["name"])))
    return out


def bodies_from_exploded_view(scene: Any, *,
                              ref_bindings: dict[str, str] | None = None) -> list[TriBody]:
    """Q-X37 exploded_view 场景 → TriBody 列表（数据级接口约定，零 import 在制面）。

    约定形态（Q-X37 ``render_exploded_view`` 信封 ``view`` 键 / ``build_scene``
    产物，2026-11-07 在制面只读对读）：``schema="exploded-view/v0"``，
    ``solids[{name, layer_index, kind=solid|sheet|trace|via, material,
    box_mm=(x0,y0,z0,x1,y1,z1), net?}]``——box_mm 与 TriBody.coords 同布局且为
    **未爆炸一手坐标**（``offset_mm`` 仅显示偏移，不入 3D 面）；``cavity`` 挖除区
    不成体。金属判定=材质名启发式或 kind∈{sheet,trace,via}；solve_inside=非金属
    solid（layered_stack lint 投影同口径）。场景无位号——ref 只经
    ``ref_bindings`` 显式绑定；schema 串不符 → ValueError（形态漂移 fail-loud）。
    """
    if not isinstance(scene, dict) or scene.get("schema") != EXPLODED_VIEW_SCHEMA:
        got = scene.get("schema") if isinstance(scene, dict) else type(scene).__name__
        raise ValueError(f"exploded_view 场景 schema 必须为 {EXPLODED_VIEW_SCHEMA!r}，得到 {got!r}")
    solids = scene.get("solids")
    if not isinstance(solids, list) or not all(isinstance(s, dict) for s in solids):
        raise ValueError("exploded_view 场景 solids 必须为对象列表")
    out: list[TriBody] = []
    for s in solids:
        mat = str(s.get("material") or "unknown")
        metal = is_metal_material(mat) or str(s.get("kind")) in ("sheet", "trace", "via")
        li = s.get("layer_index")
        out.append(TriBody(name=str(s.get("name")), material=mat, coords=s.get("box_mm"),
                           is_metal=metal, solve_inside=(str(s.get("kind")) == "solid" and not metal),
                           layer=None if li is None else f"layer{li}", net=s.get("net") or None))
    return _bind(out, ref_bindings)


def _bind(bodies: list[TriBody], ref_bindings: Any) -> list[TriBody]:
    """{体名: 位号} 绑定（重校验——空串位号同样拒绝）；未知体名 → ValueError。"""
    if ref_bindings is None:
        return bodies
    if not isinstance(ref_bindings, dict):
        raise ValueError("ref_bindings 必须为 {体名: 位号} 对象")
    binds = {str(k): str(v) for k, v in ref_bindings.items()}
    unknown = sorted(set(binds) - {b.name for b in bodies})
    if unknown:
        raise ValueError(f"ref_bindings 含未知体名 {unknown}")
    return [TriBody.model_validate({**b.model_dump(), "ref": binds[b.name]}) if b.name in binds else b
            for b in bodies]


def bodies_from_payload(payload: Any) -> dict[str, Any]:
    """3D 体输入 → 3D 面 dict。

    - dict（文件形态，必带 ``schema=rfauto-tri-view-bodies-v1``）：恰含
      ``bodies``（外部 TriBody 表）/ ``layered_stack``（spec 覆盖 dict）/
      ``exploded_view``（Q-X37 场景 dict，见 :func:`bodies_from_exploded_view`）
      之一，可选 ``ref_bindings``（体名→位号）/``units``（外部体缺省 "mm"）；
    - list：TriBody 实例或 dict 序列（Python API 直传）。
    """
    if isinstance(payload, list):
        bodies = [b if isinstance(b, TriBody) else TriBody.model_validate(b) for b in payload]
        return _d3(bodies, source="external", z_mode="external", z_units="mm")
    if not isinstance(payload, dict):
        raise TriViewError(f"3D 体输入必须为 dict 载荷或体列表（得 {type(payload).__name__}）")
    if payload.get("schema") != BODIES_SCHEMA:
        raise TriViewError(f"3D 体载荷 schema 必须为 {BODIES_SCHEMA!r}，得到 {payload.get('schema')!r}")
    extra = sorted(set(payload) - _BODIES_PAYLOAD_KEYS)
    if extra:
        raise TriViewError(f"3D 体载荷含未知键 {extra}（允许: {sorted(_BODIES_PAYLOAD_KEYS)}）")
    present = [k for k in _BODIES_SOURCE_KEYS if k in payload]
    if len(present) != 1:
        raise TriViewError(f"3D 体载荷须恰含 {list(_BODIES_SOURCE_KEYS)} 之一（得 {present}）")
    binds = payload.get("ref_bindings")
    units = str(payload.get("units", "mm"))
    if "layered_stack" in payload:
        bodies = bodies_from_layered_stack(payload["layered_stack"], ref_bindings=binds)
        return _d3(bodies, source="layered_stack", z_mode="external", z_units="mm")
    if "exploded_view" in payload:
        scene = payload["exploded_view"]
        bodies = bodies_from_exploded_view(scene, ref_bindings=binds)
        return _d3(bodies, source="exploded_view", z_mode="external",
                   z_units=str(scene.get("units", units)))
    raw = payload["bodies"]
    if not isinstance(raw, list):
        raise TriViewError("bodies 必须为 TriBody 对象列表")
    bodies = _bind([TriBody.model_validate(b) for b in raw], binds)
    return _d3(bodies, source="external", z_mode="external", z_units=units)


# ── 三视图联动（ref 键 1:1 映射+网络交叉）────────────────────────────────


def _link(sv: dict[str, Any], lv: dict[str, Any],
          d3: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    syms, fps = sv["symbols"], lv["footprints"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for b in d3["bodies"]:
        if b.get("ref"):
            groups.setdefault(str(b["ref"]), []).append(b)
    refs = sorted(set(syms) | set(fps) | set(groups))
    mapping: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    for i, ref in enumerate(refs):
        sym, fp, grp = syms.get(ref), fps.get(ref), groups.get(ref)
        present = [v for v, obj in zip(VIEWS, (sym, fp, grp), strict=True) if obj]
        missing = [v for v in VIEWS if v not in present]
        sid = ref_sid(ref)
        checks: dict[str, Any] = {"value_match": None, "pins_without_pad": [], "pads_not_in_sch": []}
        if sym and fp:
            sv_val, fp_val = sym["value"], fp["value"]
            checks["value_match"] = (sv_val == fp_val) if (sv_val and fp_val) else None
            pins, pad_nums = set(sym["pins"]), {p["number"] for p in fp["pads"]}
            checks["pins_without_pad"] = sorted(pins - pad_nums, key=_pin_key)
            checks["pads_not_in_sch"] = sorted(pad_nums - pins, key=_pin_key)
        mapping[ref] = {
            "ref": ref, "sid": sid, "color": PALETTE[i % len(PALETTE)],
            "status": "linked" if not missing else "partial",
            "views_present": present, "missing": missing,
            "svg_ids": {v: f"{v}-{sid}" for v in present},
            "sch": None if not sym else {
                "lib_id": sym["lib_id"], "value": sym["value"], "footprint": sym["footprint"],
                "at": sym["at"], "bbox": sym["bbox"], "pins": sym["pins"]},
            "pcb": None if not fp else {
                "value": fp["value"], "position": fp["position"], "bbox": fp["bbox"],
                "side": fp["side"], "layers": fp["layers"], "count": fp["count"],
                "pads": [{"name": p["name"], "number": p["number"], "net": p["net"],
                          "rect": p["rect"]} for p in fp["pads"]]},
            "3d": None if not grp else {
                "bodies": [b["name"] for b in grp], "bbox": _union3([b["coords"] for b in grp])},
            "checks": checks,
        }
        if missing:
            issues.append(_issue("missing_in_view", "ERROR", f"位号 {ref} 缺 {missing} 视图（1:1 映射断裂）",
                                 ref=ref, views=missing))
        if fp and fp["count"] > 1:
            issues.append(_issue("duplicate_ref", "ERROR",
                                 f"版图位号 {ref} 出现 {fp['count']} 个 footprint（1:1 映射断裂；焊盘已按位号合并）",
                                 ref=ref, views=["pcb"], count=fp["count"]))
        if checks["value_match"] is False:
            issues.append(_issue("value_mismatch", "WARN",
                                 f"位号 {ref} 值不一致：原理图 {sym['value']!r} vs 版图 {fp['value']!r}",
                                 ref=ref, views=["sch", "pcb"]))
        if checks["pins_without_pad"]:
            issues.append(_issue("pin_without_pad", "WARN",
                                 f"位号 {ref} 原理图引脚 {checks['pins_without_pad']} 在版图无同号焊盘",
                                 ref=ref, views=["sch", "pcb"]))
    label_pts: dict[str, list[list[float]]] = {}
    for lb in sv["labels"]:
        label_pts.setdefault(lb["name"], []).append(lb["at"])
    pad_rect: dict[tuple[str, str], list[float]] = {}
    for ref, fp in fps.items():
        for p in fp["pads"]:
            pad_rect.setdefault((ref, p["number"]), p["rect"])
    body_by_net: dict[str, list[str]] = {}
    for b in d3["bodies"]:
        if b.get("net"):
            body_by_net.setdefault(normalize_kicad_net(b["net"]), []).append(b["name"])
    nets: dict[str, Any] = {}
    sch_nets = {k: {(r, p) for r, p in v} for k, v in sv["nets"].items()}
    pcb_nets = {k: {(r, p) for r, p in v} for k, v in lv["nets"].items()}
    for name in sorted(set(sch_nets) | set(pcb_nets)):
        s, p = sch_nets.get(name, set()), pcb_nets.get(name, set())
        only_sch, only_pcb = sorted(s - p, key=_rp_key), sorted(p - s, key=_rp_key)
        match = not only_sch and not only_pcb
        nets[name] = {
            "nid": ref_sid(name), "match": match,
            "sch_pins": [list(k) for k in sorted(s, key=_rp_key)],
            "pcb_pads": [list(k) for k in sorted(p, key=_rp_key)],
            "only_sch": [list(k) for k in only_sch], "only_pcb": [list(k) for k in only_pcb],
            "sch_points": [syms[r]["pins"][pin] for r, pin in sorted(s, key=_rp_key)
                           if r in syms and pin in syms[r]["pins"]] + label_pts.get(name, []),
            "pcb_rects": [pad_rect[k] for k in sorted(p, key=_rp_key) if k in pad_rect],
            "bodies": sorted(body_by_net.get(name, [])),
        }
        if not match:
            issues.append(_issue("net_mismatch", "WARN",
                                 f"网络 {name} 原理图/版图成员不一致：仅原理图 {only_sch}、仅版图 {only_pcb}",
                                 net=name, views=["sch", "pcb"]))
    return mapping, nets, issues


def build_tri_view(sch: Any, pcb: Any, *, bodies: Any = None,
                   copper_thickness_mm: float | None = None,
                   layout: SchGridLayout | None = None) -> dict[str, Any]:
    """三视图联动主入口（JSON 进出）：SchSpec 载荷 + extract_pcb 契约 [+ 3D 体] → 信封。

    Returns
    -------
    dict
        ok 信封：``schema/one_to_one/refs/counts/mapping/nets/issues/views/
        warnings``（views={"sch","pcb","3d"} 三面同源数据；JSON 原生形态）；
        任一面输入非法 → error 信封（errors 如实，不半成品出货）。
    """
    try:
        sv = schematic_view(sch, layout)
    except ValueError as exc:  # SchSpec 校验/spec_to_gen/渲染/回读（ValidationError ⊂ ValueError）
        return error_envelope(f"原理图面构建失败: {exc}")
    try:
        lv = layout_view(pcb)
        if bodies is None:
            d3 = stack_bodies(lv, copper_thickness_mm=copper_thickness_mm)
        else:
            d3 = bodies_from_payload(bodies)
            if copper_thickness_mm is not None:
                d3["warnings"].append("外部 3D 体输入下 copper_thickness_mm 不适用，已忽略")
    except TriViewError as exc:
        return error_envelope(exc.errors)
    except ValueError as exc:  # TriBody/LayeredStackSpec 校验
        return error_envelope(f"3D 面构建失败: {exc}")
    mapping, nets, issues = _link(sv, lv, d3)
    warnings = [f"pcb: {w}" for w in lv["warnings"]] + [f"3d: {w}" for w in d3["warnings"]]
    if not sv["certificate_pass"]:
        warnings.insert(0, "sch: round-trip 证书 FAIL（产物回读网络≠SchSpec，见 views.sch.certificate_diff）")
    counts = {
        "refs": len(mapping),
        "linked": sum(1 for m in mapping.values() if m["status"] == "linked"),
        "sch_symbols": len(sv["symbols"]),
        "pcb_footprints": len(lv["footprints"]),
        "ref_groups_3d": sum(1 for m in mapping.values() if m["3d"]),
        "bodies_3d": len(d3["bodies"]),
        "nets": len(nets),
        "net_mismatch": sum(1 for n in nets.values() if not n["match"]),
        "issues_error": sum(1 for it in issues if it["level"] == "ERROR"),
        "issues_warn": sum(1 for it in issues if it["level"] == "WARN"),
    }
    one_to_one = bool(mapping) and not any(it["kind"] in _ONE_TO_ONE_KINDS for it in issues)
    return ok_envelope(**_jsonable({
        "schema": TRI_VIEW_SCHEMA,
        "one_to_one": one_to_one,
        "refs": list(mapping),
        "counts": counts,
        "mapping": mapping,
        "nets": nets,
        "issues": issues,
        "views": {"sch": sv, "pcb": lv, "3d": d3},
        "warnings": warnings,
    }))


# ── geometry_lint 投影与标注 ────────────────────────────────────────────


def tri_view_lint_projection(tri: dict[str, Any]) -> dict[str, Any]:
    """三视图 3D 面 → LintGeometry 兼容 dict（role=body→boxes，role=port→ports）。

    layered_stack 来源的 3D 面投影与 ``layered_stack_lint_projection`` 逐体
    等价（同名同坐标同端口 sheet），lint 结果因此逐字节可对拍。
    """
    d3 = tri["views"]["3d"]
    boxes: list[dict[str, Any]] = []
    ports: list[dict[str, Any]] = []
    for raw in d3["bodies"]:
        b = TriBody.model_validate(raw)
        if b.role == "port":
            ext = b.extent()
            ax = next(k for k in range(3) if ext[k] == 0.0)
            tang = [k for k in range(3) if k != ax]
            lo, hi = b.lo(), b.hi()
            ports.append({"name": b.name, "kind": b.port_kind,
                          "sheet": {"axis": "xyz"[ax], "pos": lo[ax],
                                    "u": [lo[tang[0]], hi[tang[0]]], "v": [lo[tang[1]], hi[tang[1]]]},
                          "multimode": b.multimode})
        else:
            boxes.append({"name": b.name, "material": b.material, "solve_inside": b.solve_inside,
                          "coords": list(b.coords), "is_metal": b.is_metal})
    units = "mm" if d3["z_units"] == "mm" else f"mm_xy+{d3['z_units']}_z"
    return {"model_units": units, "boxes": boxes, "ports": ports, "variables": []}


def _resolve_object(name: str, bodies: dict[str, dict[str, Any]], mapping: dict[str, Any],
                    pads: dict[str, tuple[str | None, dict[str, Any]]]) -> dict[str, Any]:
    """lint 对象名 → {resolved_as, ref, positions{sch,pcb,3d}}（解析序见模块 docstring）。"""
    def _m(ref: str | None) -> dict[str, Any] | None:
        return mapping.get(ref) if ref else None

    def _bb(m: dict[str, Any] | None, view: str) -> Any:
        return m[view]["bbox"] if m and m[view] else None

    if name in bodies:
        b = bodies[name]
        m = _m(b.get("ref"))
        return {"name": name, "resolved_as": "port" if b.get("role") == "port" else "body",
                "ref": b.get("ref"),
                "positions": {"sch": _bb(m, "sch"), "pcb": _bb(m, "pcb"), "3d": list(b["coords"])}}
    if name in mapping:
        m = mapping[name]
        return {"name": name, "resolved_as": "ref", "ref": name,
                "positions": {"sch": _bb(m, "sch"), "pcb": _bb(m, "pcb"), "3d": _bb(m, "3d")}}
    if name in pads:
        ref, pad = pads[name]
        m = _m(ref)
        pin = m["sch"]["pins"].get(pad["number"]) if m and m["sch"] else None
        sch_pos = [pin[0], pin[1], pin[0], pin[1]] if pin else _bb(m, "sch")
        pad_bodies = [b["coords"] for n, b in bodies.items() if n.startswith(f"pad:{name}@")]
        return {"name": name, "resolved_as": "pad", "ref": ref, "pad": pad["number"],
                "positions": {"sch": sch_pos, "pcb": pad["rect"],
                              "3d": _union3(pad_bodies) or _bb(m, "3d")}}
    return {"name": name, "resolved_as": None, "ref": None,
            "positions": {"sch": None, "pcb": None, "3d": None}}


def annotate_lint(tri: dict[str, Any], lint_report: Any) -> dict[str, Any]:
    """geometry_lint 报告 → 问题对象三视图位置标注（ok 信封；未解析对象如实列出）。

    Returns
    -------
    dict
        ``lint_pass/annotations[{index,check,level,message,objects[...],refs}]/
        flagged_refs{ref: 最高级}/flagged_bodies{体名: 最高级}/
        unresolved_objects/counts``；报告形态非法或报告本身是失败信封 → error。
    """
    if not isinstance(lint_report, dict) or not isinstance(lint_report.get("issues"), list):
        return error_envelope("lint 报告形态非法：须为 geometry_lint 信封（含 issues 列表）")
    if lint_report.get("ok") is False:
        return error_envelope(["lint 报告为失败信封（ok=False），无可标注对象",
                               *normalize_errors(lint_report.get("errors"))])
    bodies = {str(b["name"]): b for b in tri["views"]["3d"]["bodies"]}
    mapping = tri["mapping"]
    pads: dict[str, tuple[str | None, dict[str, Any]]] = {}
    for ref, fp in tri["views"]["pcb"]["footprints"].items():
        for p in fp["pads"]:
            pads.setdefault(str(p["name"]), (ref, p))
    for p in tri["views"]["pcb"]["orphan_pads"]:
        pads.setdefault(str(p["name"]), (None, p))
    annotations: list[dict[str, Any]] = []
    flagged_refs: dict[str, str] = {}
    flagged_bodies: dict[str, str] = {}
    unresolved: list[str] = []
    n_obj = 0

    def _flag(table: dict[str, str], key: str, level: str) -> None:
        if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(table.get(key, ""), 0):
            table[key] = level

    for idx, issue in enumerate(lint_report["issues"]):
        if not isinstance(issue, dict):
            continue
        level = str(issue.get("level") or "").upper()
        objs = [_resolve_object(str(n), bodies, mapping, pads) for n in issue.get("objects") or []]
        for o in objs:
            n_obj += 1
            if o["resolved_as"] is None:
                unresolved.append(o["name"])
                continue
            if o["ref"]:
                _flag(flagged_refs, o["ref"], level)
            if o["resolved_as"] in ("body", "port"):
                _flag(flagged_bodies, o["name"], level)
        annotations.append({"index": idx, "check": issue.get("check"), "level": level,
                            "message": issue.get("message"), "objects": objs,
                            "refs": sorted({o["ref"] for o in objs if o["ref"]})})
    return ok_envelope(**_jsonable({
        "lint_pass": lint_report.get("lint_pass"),
        "annotations": annotations,
        "flagged_refs": dict(sorted(flagged_refs.items())),
        "flagged_bodies": dict(sorted(flagged_bodies.items())),
        "unresolved_objects": sorted(set(unresolved)),
        "counts": {"issues": len(annotations), "objects": n_obj,
                   "resolved": n_obj - len(unresolved), "unresolved": len(unresolved),
                   "flagged_refs": len(flagged_refs)},
    }))


# ── 联动 SVG 三联 ───────────────────────────────────────────────────────


def _n(v: float) -> str:
    """SVG 数字：3 位小数去尾零（-0 归一为 0；确定性）。"""
    s = f"{float(v):.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "", "-") else s


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _net_attr(net: str | None) -> str:
    return f' data-net="{ref_sid(net)}"' if net else ""


class _Fit:
    """数据 bbox → 面板像素矩形的等比映射（数据 Y 向下 = SVG Y 向下）。"""

    def __init__(self, bbox: list[float], rect: tuple[float, float, float, float]) -> None:
        x0, y0, w, h = rect
        bw, bh = max(bbox[2] - bbox[0], 0.0), max(bbox[3] - bbox[1], 0.0)
        if bw > 0.0 and bh > 0.0:
            s = min(w / bw, h / bh)
        elif bw > 0.0:
            s = w / bw
        elif bh > 0.0:
            s = h / bh
        else:
            s = 1.0
        self.s = s
        self.ox = x0 + (w - bw * s) / 2.0 - bbox[0] * s
        self.oy = y0 + (h - bh * s) / 2.0 - bbox[1] * s

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (self.ox + x * self.s, self.oy + y * self.s)

    def pts(self, points: Any) -> str:
        return " ".join(f"{_n(px)},{_n(py)}" for px, py in (self.p(x, y) for x, y in points))

    def rect_attrs(self, r: list[float]) -> str:
        (x0, y0), (x1, y1) = self.p(r[0], r[1]), self.p(r[2], r[3])
        return f'x="{_n(x0)}" y="{_n(y0)}" width="{_n(x1 - x0)}" height="{_n(y1 - y0)}"'


def _hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """2D 凸包（Andrew 单调链；投影点 6 位量化去近重）——确定性。"""
    pts = sorted({(round(x, 6), round(y, 6)) for x, y in points})
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _empty(rect: tuple[float, float, float, float], text: str) -> list[str]:
    x0, y0, w, h = rect
    return [f'<text class="empty" x="{_n(x0 + w / 2.0)}" y="{_n(y0 + h / 2.0)}" '
            f'text-anchor="middle">{_esc(text)}</text>']


def _svg_sch(sv: dict[str, Any], mapping: dict[str, Any], ref_cls: Any,
             rect: tuple[float, float, float, float]) -> list[str]:
    if not sv.get("bbox"):
        return _empty(rect, "原理图面无内容")
    fit = _Fit(sv["bbox"], rect)
    out: list[str] = []
    for w in sv["wires"]:
        out.append(f'<polyline class="wire"{_net_attr(w.get("net"))} points="{fit.pts(w["pts"])}"/>')
    for lb in sv["labels"]:
        x, y = fit.p(*lb["at"])
        out.append(f'<text class="netlabel" x="{_n(x)}" y="{_n(y - 2.0)}" text-anchor="middle"'
                   f'{_net_attr(lb["name"])}>{_esc(lb["name"])}</text>')
    for ref, sym in sv["symbols"].items():
        m = mapping[ref]
        sid, color = m["sid"], m["color"]
        body = sym["body"] or sym["bbox"]
        out.append(f'<g id="sch-{sid}" class="{ref_cls(ref)}" data-ref="{sid}">')
        out.append(f"<title>{_esc(ref)} · {_esc(sym['value'])} · {_esc(sym['lib_id'])}</title>")
        out.append(f'<rect {fit.rect_attrs(body)} fill="{color}" fill-opacity="0.15" '
                   f'stroke="{color}" stroke-width="1.2"/>')
        cx = (body[0] + body[2]) / 2.0
        for num, (px, py) in sym["pins"].items():
            (x1, y1), (x2, y2) = fit.p(px, py), fit.p(body[0] if px < cx else body[2], py)
            out.append(f'<line class="pin" x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" '
                       f'data-pin="{_esc(num)}"/>')
        tx, ty = fit.p(cx, body[1])
        out.append(f'<text class="reflabel" x="{_n(tx)}" y="{_n(ty - 3.0)}" '
                   f'text-anchor="middle">{_esc(ref)}</text>')
        out.append("</g>")
    return out


def _svg_pcb(lv: dict[str, Any], mapping: dict[str, Any], ref_cls: Any,
             rect: tuple[float, float, float, float]) -> list[str]:
    if not lv.get("bbox"):
        return _empty(rect, "版图面无内容")
    fit = _Fit(lv["bbox"], rect)
    out: list[str] = []
    if lv.get("outline_bbox"):
        out.append(f'<rect class="board" {fit.rect_attrs(lv["outline_bbox"])}/>')
    for t in lv["traces"]:
        sw = max(0.6, float(t["width_mm"]) * fit.s)
        out.append(f'<polyline class="trace"{_net_attr(t["net_norm"])} stroke-width="{_n(sw)}" '
                   f'points="{fit.pts(t["points_mm"])}"/>')
    for v in lv["vias"]:
        cx, cy = fit.p(v["x_mm"], v["y_mm"])
        r = max(1.0, float(v["pad_diameter_mm"]) / 2.0 * fit.s)
        out.append(f'<circle class="via"{_net_attr(v["net_norm"])} cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}"/>')
    for pd in lv["orphan_pads"]:
        out.append(f'<rect class="pad-orphan" {fit.rect_attrs(pd["rect"])}{_net_attr(pd["net_norm"])}/>')
    for ref, fp in lv["footprints"].items():
        m = mapping[ref]
        sid, color = m["sid"], m["color"]
        out.append(f'<g id="pcb-{sid}" class="{ref_cls(ref)}" data-ref="{sid}">')
        out.append(f"<title>{_esc(ref)} · {_esc(fp['value'])} · side={_esc(fp['side'])}</title>")
        for pd in fp["pads"]:
            out.append(f'<rect class="pad" {fit.rect_attrs(pd["rect"])} fill="{color}" fill-opacity="0.6" '
                       f'stroke="{color}" stroke-width="0.8"{_net_attr(pd["net_norm"])} '
                       f'data-pad="{_esc(pd["number"])}"/>')
        if not fp["pads"] and fp["position"]:
            px, py = fit.p(*fp["position"])
            out.append(f'<circle cx="{_n(px)}" cy="{_n(py)}" r="3" fill="none" stroke="{color}" stroke-width="1"/>')
        if fp["bbox"]:
            bb = fp["bbox"]
            tx, ty = fit.p((bb[0] + bb[2]) / 2.0, bb[1])
            out.append(f'<text class="reflabel" x="{_n(tx)}" y="{_n(ty - 2.0)}" '
                       f'text-anchor="middle">{_esc(ref)}</text>')
        out.append("</g>")
    return out


def _ctx_style(b: dict[str, Any]) -> tuple[str, str, str, str]:
    """上下文体（无 ref）配色：(fill, fill-opacity, stroke, 额外属性)。"""
    mat = str(b.get("material", ""))
    if b.get("role") == "port":
        return ("#ff9896", "0.35", "#d62728", ' stroke-dasharray="3 2"')
    if is_air_material(mat):
        return ("none", "0", "#9a9a9a", ' stroke-dasharray="2 2"')
    if is_metal_material(mat, b.get("is_metal")):
        return ("#d4af37", "0.45", "#8c6d1f", "")
    return ("#9edae5", "0.25", "#4a9aa5", "")


def _svg_3d(d3: dict[str, Any], mapping: dict[str, Any], ref_cls: Any,
            flagged_bodies: dict[str, str], rect: tuple[float, float, float, float]) -> list[str]:
    bodies = d3["bodies"]
    if not bodies:
        return _empty(rect, "3D 面无体")
    zs = sorted({float(b["coords"][2]) for b in bodies} | {float(b["coords"][5]) for b in bodies})
    level = {z: k for k, z in enumerate(zs)}
    span = max(max(float(b["coords"][3]) for b in bodies) - min(float(b["coords"][0]) for b in bodies),
               max(float(b["coords"][4]) for b in bodies) - min(float(b["coords"][1]) for b in bodies))
    span = span if span > 0.0 else 1.0
    total = zs[-1] - zs[0]
    z_disp = {zs[0]: 0.0}
    acc = 0.0
    for lo, hi in itertools.pairwise(zs):
        acc += span * (Z_MIN_FRACTION + Z_PROP_FRACTION * ((hi - lo) / total if total > 0.0 else 0.0))
        z_disp[hi] = acc
    ca, sa = math.cos(math.radians(ISO_ANGLE_DEG)), math.sin(math.radians(ISO_ANGLE_DEG))

    def proj(x: float, y: float, z: float) -> tuple[float, float]:
        return ((x - y) * ca, (x + y) * sa - z_disp[z])

    shapes: list[tuple[tuple[Any, ...], dict[str, Any], list[tuple[float, float]], list[tuple[float, float]]]] = []
    for idx, b in enumerate(bodies):
        x0, y0, z0, x1, y1, z1 = (float(v) for v in b["coords"])
        hull = _hull([proj(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
        top = [proj(x0, y0, z1), proj(x1, y0, z1), proj(x1, y1, z1), proj(x0, y1, z1)]
        shapes.append(((level[z0], level[z0] - level[z1], x0 + y0, idx), b, hull, top))
    shapes.sort(key=lambda s: s[0])
    all_pts = [p for _, _, hull, _ in shapes for p in hull]
    fit = _Fit([min(p[0] for p in all_pts), min(p[1] for p in all_pts),
                max(p[0] for p in all_pts), max(p[1] for p in all_pts)], rect)
    out: list[str] = []
    seq: Counter[str] = Counter()
    for _, b, hull, top in shapes:
        ref = b.get("ref")
        title = f"<title>{_esc(b['name'])}</title>"
        dash = ' stroke-dasharray="3 2"' if b.get("role") == "port" else ""
        if ref and ref in mapping:
            m = mapping[ref]
            seq[ref] += 1
            out.append(f'<polygon id="3d-{m["sid"]}-{seq[ref]}" class="body {ref_cls(ref)}" '
                       f'data-ref="{m["sid"]}" data-body="{_esc(b["name"])}"{_net_attr(normalize_kicad_net(b["net"]) if b.get("net") else None)} '
                       f'points="{fit.pts(hull)}" fill="{m["color"]}" fill-opacity="0.5" '
                       f'stroke="{m["color"]}" stroke-width="0.8"{dash}>{title}</polygon>')
        else:
            fill, op, stroke, extra = _ctx_style(b)
            lint = flagged_bodies.get(b["name"])
            cls = "body ctx" + {"ERROR": " lint-error", "WARN": " lint-warn"}.get(lint or "", "")
            out.append(f'<polygon class="{cls}" data-body="{_esc(b["name"])}" points="{fit.pts(hull)}" '
                       f'fill="{fill}" fill-opacity="{op}" stroke="{stroke}" stroke-width="0.6"{extra}>'
                       f"{title}</polygon>")
        if b.get("role") != "port" and len(_hull(top)) >= 3:
            out.append(f'<polygon class="topface" points="{fit.pts(top)}"/>')
    for ref, m in mapping.items():
        if not m["3d"]:
            continue
        bx = m["3d"]["bbox"]
        tx, ty = fit.p(*proj((bx[0] + bx[3]) / 2.0, (bx[1] + bx[4]) / 2.0, float(bx[5])))
        out.append(f'<g id="3d-{m["sid"]}" class="{ref_cls(ref)} label3d" data-ref="{m["sid"]}">'
                   f'<text class="reflabel" x="{_n(tx)}" y="{_n(ty - 3.0)}" '
                   f'text-anchor="middle">{_esc(ref)}</text></g>')
    return out


def render_tri_view_svg(tri: dict[str, Any], *, lint_annotation: dict[str, Any] | None = None,
                        highlight_refs: Any = ()) -> str:
    """三视图信封 → 联动 SVG 三联文本（同输入逐字节同；元素 id/类见模块 docstring）。

    ``highlight_refs``：静态预高亮位号（``hl`` 类）；``lint_annotation``：
    :func:`annotate_lint` 信封（flagged_refs 三面着 lint 类，flagged_bodies 着
    3D 上下文体）。
    """
    mapping = tri["mapping"]
    views = tri["views"]
    ann = lint_annotation or {}
    flagged_refs = ann.get("flagged_refs") or {}
    flagged_bodies = ann.get("flagged_bodies") or {}
    hl = {str(r) for r in highlight_refs}

    def ref_cls(ref: str) -> str:
        cls = ["ref"]
        if ref in hl:
            cls.append("hl")
        lint = flagged_refs.get(ref)
        if lint == "ERROR":
            cls.append("lint-error")
        elif lint == "WARN":
            cls.append("lint-warn")
        return " ".join(cls)

    total_w = 3 * PANEL_W + 4 * PANEL_GAP
    total_h = PANEL_H + 2 * PANEL_GAP + FOOTER_H
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_n(total_w)}" height="{_n(total_h)}" '
        f'viewBox="0 0 {_n(total_w)} {_n(total_h)}" font-family="sans-serif" data-schema="{TRI_VIEW_SCHEMA}">',
        f"<style>\n{_SVG_STYLE}</style>",
        f'<rect class="bg" x="0" y="0" width="{_n(total_w)}" height="{_n(total_h)}"/>',
    ]
    d3 = views["3d"]
    titles = dict(_PANEL_TITLES)
    titles["3d"] = f"{_PANEL_TITLES['3d']} · {d3['source']}/{d3['z_mode']}"
    for k, view in enumerate(VIEWS):
        x0 = PANEL_GAP + k * (PANEL_W + PANEL_GAP)
        y0 = PANEL_GAP
        rect = (x0 + PANEL_PAD, y0 + TITLE_H + PANEL_PAD / 2.0,
                PANEL_W - 2.0 * PANEL_PAD, PANEL_H - TITLE_H - 1.5 * PANEL_PAD)
        out.append(f'<g id="panel-{view}" class="panel">')
        out.append(f'<rect class="frame" x="{_n(x0)}" y="{_n(y0)}" width="{_n(PANEL_W)}" height="{_n(PANEL_H)}"/>')
        out.append(f'<text class="title" x="{_n(x0 + 8.0)}" y="{_n(y0 + 15.0)}">{_esc(titles[view])}</text>')
        if view == "sch":
            out += _svg_sch(views["sch"], mapping, ref_cls, rect)
        elif view == "pcb":
            out += _svg_pcb(views["pcb"], mapping, ref_cls, rect)
        else:
            out += _svg_3d(d3, mapping, ref_cls, flagged_bodies, rect)
        out.append("</g>")
    c = tri["counts"]
    foot = (f"refs {c['refs']} · linked {c['linked']} · one_to_one={tri['one_to_one']} · "
            f"nets {c['nets']}（mismatch {c['net_mismatch']}）· issues E{c['issues_error']}/W{c['issues_warn']}")
    if ann:
        ac = ann.get("counts") or {}
        foot += (f" · lint issues {ac.get('issues', 0)} · flagged refs {ac.get('flagged_refs', 0)}"
                 f" · unresolved {ac.get('unresolved', 0)}")
    out.append(f'<text class="foot" x="{_n(PANEL_GAP)}" y="{_n(total_h - 9.0)}">{_esc(foot)}</text>')
    out.append(f"<script><![CDATA[{_SVG_SCRIPT}]]></script>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ── 文件入口（CLI 叶 rfauto tri-view link 的 service 面）────────────────────


def _read_json(path: Path, what: str) -> tuple[Any, str | None]:
    if not path.is_file():
        return None, f"{what}不存在: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"{what}不可读: {exc}"


def tri_view_link(sch_path: str | Path, pcb_path: str | Path, *,
                  out_dir: str | Path | None = None, lint_path: str | Path | None = None,
                  self_lint: bool = False, bodies_path: str | Path | None = None,
                  copper_thickness_mm: float | None = None) -> dict[str, Any]:
    """文件进出：sch.json + pcb.json [+ 3D 体 JSON][+ lint 报告] → 联动 SVG 三联 + 映射 JSON。

    落点：``out_dir`` 缺省=sch 同目录，文件名 ``<sch stem>.tri_view.svg`` /
    ``<sch stem>.tri_view.json``（映射 JSON=信封同形，sort_keys 确定性）；
    ``out_dir="-"`` 不落盘（SVG 原文进信封 ``svg_str``）。``lint_path`` 与
    ``self_lint`` 互斥（外部报告标注 vs 对 3D 面投影自跑 lint_geometry）。
    """
    if lint_path and self_lint:
        return error_envelope("--lint 与 --self-lint 互斥（外部报告标注 vs 自跑 lint 二选一）")
    sch_p, pcb_p = Path(sch_path), Path(pcb_path)
    sch, err = _read_json(sch_p, "原理图 SchSpec JSON")
    if err:
        return error_envelope(err)
    pcb, err = _read_json(pcb_p, "版图 JSON")
    if err:
        return error_envelope(err)
    bodies = None
    if bodies_path:
        bodies, err = _read_json(Path(bodies_path), "3D 体 JSON")
        if err:
            return error_envelope(err)
    tri = build_tri_view(sch, pcb, bodies=bodies, copper_thickness_mm=copper_thickness_mm)
    if not tri.get("ok"):
        return tri
    report: Any = None
    lint_src: str | None = None
    if lint_path:
        report, err = _read_json(Path(lint_path), "geometry_lint 报告 JSON")
        if err:
            return error_envelope(err)
        lint_src = Path(lint_path).name
    elif self_lint:
        report = lint_geometry(tri_view_lint_projection(tri))
        lint_src = "self"
    ann: dict[str, Any] | None = None
    if report is not None:
        ann = annotate_lint(tri, report)
        if not ann.get("ok"):
            return ann
        if self_lint:
            ann["report"] = _jsonable(report)
    svg = render_tri_view_svg(tri, lint_annotation=ann)
    doc = _jsonable({
        **{k: v for k, v in tri.items() if k != "ok"},
        "lint": ann,
        "svg_sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
        "inputs": {"sch": sch_p.name, "pcb": pcb_p.name,
                   "bodies": Path(bodies_path).name if bodies_path else None, "lint": lint_src},
    })
    if str(out_dir) == "-":
        return ok_envelope(**doc, svg_path=None, map_path=None, map_sha256=None, svg_str=svg)
    od = Path(out_dir) if out_dir else sch_p.parent
    svg_file = od / f"{sch_p.stem}.tri_view.svg"
    map_file = od / f"{sch_p.stem}.tri_view.json"
    map_text = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        od.mkdir(parents=True, exist_ok=True)
        svg_file.write_text(svg, encoding="utf-8", newline="\n")
        map_file.write_text(map_text, encoding="utf-8", newline="\n")
    except OSError as exc:
        return error_envelope(f"写出失败 {od}: {exc}")
    return ok_envelope(**doc, svg_path=str(svg_file), map_path=str(map_file),
                       map_sha256=hashlib.sha256(map_text.encode("utf-8")).hexdigest())
