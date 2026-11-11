"""KiCad 10 原理图（.kicad_sch）s-expr 程序化生成器 + round-trip 网表回读。

T-Q22（aurora_q Q-CAD-1，CAD-Agent 吸收提案 §13.3 行动 A 的 rfauto 化）。
本模块是 **纯 adapters 面**：零第三方依赖（纯文本 s-expr 拼装/解析，stdlib
only），service 层（kicad_sch_service）做 SchSpec schema、信封编排与
kicad-cli 子进程封装。表示法思想吸收（SchGen 语义接地=按引脚名连线+相对
位置、Weave round-trip 二值证书），**零外部代码拷贝**（许可未逐一验）。

连通性表示法（声明式，非智能布局——铁律 7：坐标/间距=规则参数）：
    每个元件按网格槽位摆放（angle=0），每个 **属于某 net 的引脚** 从引脚
    连接点向外引一段 stub 导线，stub 外端放 **同名局部 label**——同 net 的
    所有引脚靠 label 名相等连通（KiCad 局部 label 语义），**不画跨元件
    导线**（SchGen "按引脚名布线" 的确定性内核版）。无 T 结 → 无需
    junction。不属于任何 net 的显式 pin 只画引脚不画 stub（如实留未连接，
    交给 ERC 报告）。

格式纪律（KiCad 10 / version 20250114，参照 E:\\KiCad\\share\\kicad\\demos
真实文件与本机 kicad-cli 10.0.6 实读）：
- 文件版本钉 ``20250114``（eeschema 9.0 schema；KiCad 10 向后兼容实读，
  本机 10.0.6 `kicad-cli sch erc` 冒烟实证）；
- 库符号内嵌 ``lib_symbols``：每个 lib_id 一个通用矩形体符号，子块命名
  ``<name>_0_1``（公共图形）/``<name>_1_1``（unit 1 引脚）；
- **net 名称制**：本生成器的连通性全靠 label 名（schematic 面无数字
  net code）——CAD 文档坑 #15（KiCad 10 文件格式 net 是名称制）在
  schematic 侧的自然推论：同名 label=同 net，改名=改连接；
- **Y 轴翻转**：symbol 库坐标 Y 向上、schematic 坐标 Y 向下，实例 angle=0
  时引脚世界坐标 = ``(inst_x + local_x, inst_y - local_y)``——本仓约定
  经 kicad-cli ``sch export netlist`` 真机对拍实证（runs/aurora_q/
  qcad1_smoke/ 冒烟证据件，stub 精确落引脚=连通正确）；
- 所有 uuid 用 ``uuid5``（内容键确定性）——同 spec 逐字节同输出（可
  diff、可重放），不同 spec 键不同 uuid。

round-trip 证书（Weave 思想）：:func:`readback_nets` 把自产 s-expr 独立
解析回 net→pins 映射（union-find 按坐标连通），与输入 SchSpec 逐 net 比
对给二值判定——生成器几何 bug（stub 落错脚/label 写错名/槽位碰撞）在
证书面必然现形。
"""

from __future__ import annotations

import itertools
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

__all__ = [
    "FONT_SIZE_MM",
    "GENERATOR_NAME",
    "GENERATOR_VERSION",
    "PIN_LENGTH_MM",
    "PROJECT_NAME",
    "SCH_VERSION",
    "GenComponent",
    "GenNet",
    "NetReadback",
    "SchGridLayout",
    "derive_pin_map",
    "parse_erc_report",
    "parse_sexpr",
    "pin_local_offset",
    "pin_world_pos",
    "readback_nets",
    "render_schematic",
    "symbol_slot_xy",
]

#: 文件 schema 版本（eeschema 9.0；KiCad 10.0.6 实读兼容——冒烟证据件）。
SCH_VERSION = 20250114
#: generator 字段（诚实标注：本仓生成器，非 eeschema）。
GENERATOR_NAME = "rfauto"
GENERATOR_VERSION = "1.0"
#: instances/project 工程名（固定串；KiCad 以此归档实例路径）。
PROJECT_NAME = "rfauto"
#: 通用符号引脚长度 [mm]（KiCad 惯例 100mil）。
PIN_LENGTH_MM = 2.54
#: 属性字号 [mm]（KiCad 缺省）。
FONT_SIZE_MM = 1.27

_PIN_NUM_RE = re.compile(r"^\d+$")
_REF_PREFIX_RE = re.compile(r"^[A-Za-z]+")


# ---------------------------------------------------------------------------
# 声明式布局规则参数（铁律 7：间距/坐标全部是显式参数，docstring 声明+测试钉）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchGridLayout:
    """声明式网格布局规则参数（非智能布局；全部缺省值=单源钉）。

    规则（声明）：元件按 ``per_row`` 列网格排布，槽位 i →
    ``col=i%per_row, row=i//per_row``；列距 ``col_pitch_mm``、行距
    ``row_pitch_mm``；引脚在符号体两侧自上而下交替（偶序左/奇序右，世界
    坐标 y 向下、slot 0 在最上）；stub 从引脚连接点沿左右向外水平引
    ``stub_len_mm``，label 落 stub 外端。

    边界（如实登记）：不做分页/避让——超出 A4 版面（约 297×210mm，缺省
    参数约容纳 15 行）时元件仍完整生成、连通性不受影响（KiCad 连通判定
    不裁剪纸外几何），仅视觉溢出版面。全部缺省值取 1.27mm（KiCad 连接
    栅格 50mil）的整数倍——离栅坐标触发 ERC ``endpoint_off_grid`` 警告
    （真机实测），origin 也必须落在栅格上。
    """

    origin_x_mm: float = 50.8
    origin_y_mm: float = 50.8
    per_row: int = 4
    col_pitch_mm: float = 50.8
    row_pitch_mm: float = 38.1
    stub_len_mm: float = 5.08
    pin_pitch_mm: float = 2.54
    body_w_mm: float = 10.16
    min_body_h_mm: float = 7.62
    pin_len_mm: float = PIN_LENGTH_MM
    paper: str = "A4"


@dataclass(frozen=True)
class GenComponent:
    """生成器输入元件（service 层 SchSpec 校验后投影）。"""

    ref: str
    value: str
    lib_id: str
    footprint: str = ""
    #: 显式额外引脚号（∪ nets 引用集）；空=完全从 nets 推导。
    pins: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenNet:
    """生成器输入网络（引脚引用对 ``(ref, pin)`` 元组序列）。"""

    name: str
    pins: tuple[tuple[str, str], ...] = ()


@dataclass
class NetReadback:
    """s-expr 回读结果（round-trip 证书的"读"侧）。"""

    #: net 名 → [(ref, pin), ...]（排序去重；同簇多 label 名如实多键）。
    nets: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: 连通但无 label 的引脚（自产文件恒空；外部文件诊断用）。
    unnamed_pins: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 声明式几何规则
# ---------------------------------------------------------------------------


def symbol_slot_xy(index: int, layout: SchGridLayout) -> tuple[float, float]:
    """槽位 ``index`` → 实例原点 (x, y) [mm]（col=i%per_row/row=i//per_row）。"""
    per_row = max(1, int(layout.per_row))
    col, row = index % per_row, index // per_row
    return (layout.origin_x_mm + col * layout.col_pitch_mm,
            layout.origin_y_mm + row * layout.row_pitch_mm)


def _side_of(pin_index: int) -> str:
    """引脚交替取边规则：偶序左/奇序右（声明式，测试钉）。"""
    return "left" if pin_index % 2 == 0 else "right"


def pin_local_offset(pin_index: int, npins: int,
                     layout: SchGridLayout) -> tuple[str, float]:
    """引脚 ``pin_index``（共 ``npins``）→ (side, 世界 dy) [mm]。

    交替左右（偶左奇右）；同侧第 k 个自上而下：世界坐标 y 向下，
    ``dy = (k - (n_side-1)/2) * pin_pitch``（slot 0 在最上）。
    """
    n_left = (npins + 1) // 2
    n_side = n_left if _side_of(pin_index) == "left" else npins // 2
    k = pin_index // 2
    if n_side <= 0:
        return (_side_of(pin_index), 0.0)
    dy = (k - (n_side - 1) / 2.0) * layout.pin_pitch_mm
    return (_side_of(pin_index), dy)


def body_height_mm(npins: int, layout: SchGridLayout) -> float:
    """符号体高 [mm]：同侧最多引脚数 × 引脚距 + 上下各一引脚距余量，
    下限 ``min_body_h_mm``（声明式，测试钉）。"""
    n_side = (npins + 1) // 2
    return max(layout.min_body_h_mm, (n_side + 2) * layout.pin_pitch_mm)


def pin_world_pos(pin_index: int, npins: int,
                  inst_xy: tuple[float, float],
                  layout: SchGridLayout) -> tuple[float, float]:
    """引脚世界连接点 [mm]（schematic 坐标，Y 向下）。

    Y 翻转约定：lib 局部坐标 Y 向上，``world = (inst_x + local_x,
    inst_y - local_y)``（angle=0）；本仓约定经 kicad-cli netlist 真机
    对拍实证（冒烟证据件 runs/aurora_q/qcad1_smoke/）。
    """
    side, dy_world = pin_local_offset(pin_index, npins, layout)
    half_w = layout.body_w_mm / 2.0 + layout.pin_len_mm
    x = inst_xy[0] - half_w if side == "left" else inst_xy[0] + half_w
    return (x, inst_xy[1] + dy_world)


def _pin_sort_key(p: str) -> tuple[int, int, str]:
    """pin 号排序键：纯数字按数值排且排前，非数字字典序排后（声明式）。"""
    if _PIN_NUM_RE.match(p):
        return (0, int(p), "")
    return (1, 0, p)


def derive_pin_map(components: Sequence[GenComponent],
                   nets: Sequence[GenNet]) -> dict[str, list[str]]:
    """ref → 有效 pin 号列表（显式 pins ∪ nets 引用；:data:`_pin_sort_key`）。"""
    out: dict[str, set[str]] = {c.ref: {str(p) for p in c.pins} for c in components}
    for net in nets:
        for ref, pin in net.pins:
            if ref in out:
                out[ref].add(str(pin))
    return {r: sorted(vals, key=_pin_sort_key) for r, vals in out.items()}


# ---------------------------------------------------------------------------
# s-expr 拼装
# ---------------------------------------------------------------------------


def _f(v: float) -> str:
    """坐标/尺寸格式化：6 位小数去尾零（-0 归一为 0；确定性）。"""
    s = f"{float(v):.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _esc(s: str) -> str:
    """s-expr 字符串转义（反斜杠与双引号）。"""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _q(s: str) -> str:
    return f'"{_esc(str(s))}"'


def _uuid(key: str) -> str:
    """内容键 → 确定性 uuid 字符串（uuid5；同键同值可 diff）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rfauto-kicad-sch:{key}"))


def _sym_split(lib_id: str) -> tuple[str, str]:
    """"lib:name" → (lib, name)；无 ':' → ("", lib_id)。"""
    if ":" in lib_id:
        lib, name = lib_id.split(":", 1)
        return (lib, name)
    return ("", lib_id)


def _ind(depth: int, text: str) -> str:
    return "\t" * depth + text


def _prop_lines(depth: int, name: str, value: str, x: float, y: float,
                *, hide: bool = False) -> list[str]:
    out = [_ind(depth, f"(property {_q(name)} {_q(value)} "
                       f"(at {_f(x)} {_f(y)} 0)"),
           _ind(depth + 1, "(effects"),
           _ind(depth + 2,
                f"(font (size {_f(FONT_SIZE_MM)} {_f(FONT_SIZE_MM)}))")]
    if hide:
        out.append(_ind(depth + 2, "(hide yes)"))
    out += [_ind(depth + 1, ")"), _ind(depth, ")")]
    return out


def _pin_lines(pin: str, side: str, local_x: float, local_y: float,
               layout: SchGridLayout) -> list[str]:
    """lib 引脚块：``at``=连接端，angle 指向符号体（左 0/右 180）。"""
    angle = 0 if side == "left" else 180
    return [_ind(4, "(pin passive line"),
            _ind(5, f"(at {_f(local_x)} {_f(local_y)} {angle})"),
            _ind(5, f"(length {_f(layout.pin_len_mm)})"),
            _ind(5, f"(name {_q(pin)}"),
            _ind(6, "(effects"),
            _ind(7, f"(font (size {_f(FONT_SIZE_MM)} {_f(FONT_SIZE_MM)}))"),
            _ind(6, ")"),
            _ind(5, ")"),
            _ind(5, f"(number {_q(pin)}"),
            _ind(6, "(effects"),
            _ind(7, f"(font (size {_f(FONT_SIZE_MM)} {_f(FONT_SIZE_MM)}))"),
            _ind(6, ")"),
            _ind(5, ")"),
            _ind(4, ")")]


def _lib_symbol_block(lib_id: str, ref_prefix: str, pins: Sequence[str],
                      layout: SchGridLayout) -> list[str]:
    """内嵌库符号块（通用矩形体+引脚；参照 demos 真实格式，完整闭合）。

    引脚 lib 局部坐标：Y 向上（local_y = -世界 dy）；左侧连接端在
    ``-(体半宽+引脚长)``、右侧镜像；``at`` 角度指向符号体。
    """
    _, name = _sym_split(lib_id)
    h = body_height_mm(len(pins), layout)
    half_w = layout.body_w_mm / 2.0
    half_h = h / 2.0
    out = [_ind(2, f"(symbol {_q(lib_id)}"),
           _ind(3, "(pin_names (offset 0.254))"),
           _ind(3, "(exclude_from_sim no)"),
           _ind(3, "(in_bom yes)"),
           _ind(3, "(on_board yes)")]
    out += _prop_lines(3, "Reference", ref_prefix, 0.0, half_h + FONT_SIZE_MM * 2)
    out += _prop_lines(3, "Value", name, 0.0, -(half_h + FONT_SIZE_MM * 2))
    out += _prop_lines(3, "Footprint", "", 0.0, 0.0, hide=True)
    out += _prop_lines(3, "Datasheet", "~", 0.0, 0.0, hide=True)
    out += _prop_lines(3, "Description", "", 0.0, 0.0, hide=True)
    # 公共图形（_0_1）：矩形体
    out += [_ind(3, f"(symbol {_q(name + '_0_1')}"),
            _ind(4, "(rectangle"),
            _ind(5, f"(start {_f(-half_w)} {_f(-half_h)})"),
            _ind(5, f"(end {_f(half_w)} {_f(half_h)})"),
            _ind(5, "(stroke (width 0.254) (type default))"),
            _ind(5, "(fill (type none))"),
            _ind(4, ")"),
            _ind(3, ")")]
    # 引脚（_1_1）
    out.append(_ind(3, f"(symbol {_q(name + '_1_1')}"))
    for idx, p in enumerate(pins):
        side, dy_world = pin_local_offset(idx, len(pins), layout)
        local_y = -dy_world
        x_off = half_w + layout.pin_len_mm
        local_x = -x_off if side == "left" else x_off
        out += _pin_lines(p, side, local_x, local_y, layout)
    out += [_ind(3, ")"), _ind(2, ")")]
    return out


def _wire_block(x1: float, y1: float, x2: float, y2: float, key: str) -> list[str]:
    return [_ind(1, "(wire"),
            _ind(2, "(pts"),
            _ind(3, f"(xy {_f(x1)} {_f(y1)}) (xy {_f(x2)} {_f(y2)})"),
            _ind(2, ")"),
            _ind(2, "(stroke (width 0) (type solid))"),
            _ind(2, f"(uuid {_q(_uuid(key))})"),
            _ind(1, ")")]


def _label_block(name: str, x: float, y: float, justify: str, key: str) -> list[str]:
    return [_ind(1, f"(label {_q(name)}"),
            _ind(2, f"(at {_f(x)} {_f(y)} 0)"),
            _ind(2, "(effects"),
            _ind(3, f"(font (size {_f(FONT_SIZE_MM)} {_f(FONT_SIZE_MM)}))"),
            _ind(3, f"(justify {justify})"),
            _ind(2, ")"),
            _ind(2, f"(uuid {_q(_uuid(key))})"),
            _ind(1, ")")]


def _stub_end_x(side: str, px: float, layout: SchGridLayout) -> float:
    """stub 外端 x [mm]：向外引（左减右加）。"""
    return px - layout.stub_len_mm if side == "left" else px + layout.stub_len_mm


def render_schematic(components: Sequence[GenComponent],
                     nets: Sequence[GenNet],
                     layout: SchGridLayout | None = None) -> str:
    """GenComponent/GenNet 序列 → 完整 .kicad_sch 文本（逐字节确定性）。

    结构：头（version 20250114/generator rfauto/uuid/paper）→ lib_symbols
    （每 lib_id 一通用符号，首次出现序）→ 元件实例（网格槽位+属性+pin uuid
    +instances 归档）→ 每 net 引脚一 stub 导线+同名 label → sheet_instances
    /embedded_fonts 尾。同输入逐字节同输出（uuid5+固定次序）。
    """
    lay = layout or SchGridLayout()
    if not components:
        raise ValueError("components 必须非空（空原理图不生成）")
    pin_map = derive_pin_map(components, nets)
    order = {c.ref: i for i, c in enumerate(components)}
    root_uuid = _uuid("root:" + lay.paper)

    # lib 符号：lib_id 首现序；引脚集=该 lib 全部元件 pin 并集；
    # Reference 前缀=首现元件位号字母前缀
    lib_pins: dict[str, list[str]] = {}
    lib_prefix: dict[str, str] = {}
    for c in components:
        if c.lib_id not in lib_pins:
            lib_pins[c.lib_id] = []
            m = _REF_PREFIX_RE.match(c.ref)
            lib_prefix[c.lib_id] = m.group(0) if m else "U"
        for p in pin_map[c.ref]:
            if p not in lib_pins[c.lib_id]:
                lib_pins[c.lib_id].append(p)

    out: list[str] = ["(kicad_sch",
                      _ind(1, f"(version {SCH_VERSION})"),
                      _ind(1, f"(generator {_q(GENERATOR_NAME)})"),
                      _ind(1, f"(generator_version {_q(GENERATOR_VERSION)})"),
                      _ind(1, f"(uuid {_q(root_uuid)})"),
                      _ind(1, f"(paper {_q(lay.paper)})"),
                      _ind(1, "(lib_symbols")]
    for lib_id in lib_pins:
        out += _lib_symbol_block(lib_id, lib_prefix[lib_id],
                                 lib_pins[lib_id], lay)
    out.append(_ind(1, ")"))

    # 元件实例
    for c in components:
        i = order[c.ref]
        x, y = symbol_slot_xy(i, lay)
        h = body_height_mm(len(pin_map[c.ref]), lay)
        ukey = f"sym:{c.ref}"
        out += [_ind(1, "(symbol"),
                _ind(2, f"(lib_id {_q(c.lib_id)})"),
                _ind(2, f"(at {_f(x)} {_f(y)} 0)"),
                _ind(2, "(unit 1)"),
                _ind(2, "(exclude_from_sim no)"),
                _ind(2, "(in_bom yes)"),
                _ind(2, "(on_board yes)"),
                _ind(2, "(dnp no)"),
                _ind(2, f"(uuid {_q(_uuid(ukey))})")]
        out += _prop_lines(2, "Reference", c.ref, x, y - h / 2.0 - FONT_SIZE_MM * 2)
        out += _prop_lines(2, "Value", c.value, x, y + h / 2.0 + FONT_SIZE_MM * 2)
        out += _prop_lines(2, "Footprint", c.footprint, x, y, hide=True)
        out += _prop_lines(2, "Datasheet", "~", x, y, hide=True)
        out += _prop_lines(2, "Description", "", x, y, hide=True)
        for p in pin_map[c.ref]:
            out += [_ind(2, f"(pin {_q(p)}"),
                    _ind(3, f"(uuid {_q(_uuid(ukey + ':pin:' + p))})"),
                    _ind(2, ")")]
        out += [_ind(2, "(instances"),
                _ind(3, f"(project {_q(PROJECT_NAME)}"),
                _ind(4, f'(path {_q("/" + root_uuid)}'),
                _ind(5, f"(reference {_q(c.ref)})"),
                _ind(5, "(unit 1)"),
                _ind(4, ")"),
                _ind(3, ")"),
                _ind(2, ")"),
                _ind(1, ")")]

    # stub 导线 + 同名 label（连通性本体；SchGen 按引脚名连线语义）
    for net in nets:
        for ref, pin in net.pins:
            if ref not in order or pin not in pin_map.get(ref, []):
                continue
            comp = components[order[ref]]
            plist = pin_map[ref]
            j = plist.index(pin)
            npins = len(plist)
            inst = symbol_slot_xy(order[ref], lay)
            side, _ = pin_local_offset(j, npins, lay)
            px, py = pin_world_pos(j, npins, inst, lay)
            ex = _stub_end_x(side, px, lay)
            wkey = f"wire:{comp.ref}:{pin}:{net.name}"
            out += _wire_block(px, py, ex, py, wkey)
            justify = "right bottom" if side == "left" else "left bottom"
            out += _label_block(net.name, ex, py, justify,
                                f"label:{comp.ref}:{pin}:{net.name}")

    out += [_ind(1, "(sheet_instances"),
            _ind(2, '(path "/"'),
            _ind(3, '(page "1")'),
            _ind(2, ")"),
            _ind(1, ")"),
            _ind(1, "(embedded_fonts no)"),
            ")"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# s-expr 解析 + round-trip 回读
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+')


def parse_sexpr(text: str) -> list:
    """KiCad s-expr → 顶层表达式列表（每项=嵌套 list）。

    .kicad_sch 恒单根：``parse_sexpr(text)[0] == ["kicad_sch", ...]``。
    数字不转型（消费方自行 float/int，避免格式漂移的精度语义）。
    """
    stack: list[list] = [[]]
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok == "(":
            new: list = []
            stack[-1].append(new)
            stack.append(new)
        elif tok == ")":
            if len(stack) == 1:
                raise ValueError("s-expr 括号不配对：多余 ')'")
            stack.pop()
        else:
            if tok.startswith('"') and tok.endswith('"') and len(tok) >= 2:
                tok = tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            stack[-1].append(tok)
    if len(stack) != 1:
        raise ValueError("s-expr 括号不配对：缺 ')'")
    return stack[0]


def _sub(node: list, tag: str) -> list | None:
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == tag:
            return child
    return None


def _subs(node: list, tag: str) -> list[list]:
    return [c for c in node[1:]
            if isinstance(c, list) and c and c[0] == tag]


def _prop_value(node: list, name: str) -> str:
    for p in _subs(node, "property"):
        if len(p) > 2 and p[1] == name:
            return str(p[2])
    return ""


def _xy(node: list | None) -> tuple[float, float] | None:
    if node is None or len(node) < 3:
        return None
    try:
        return (float(node[1]), float(node[2]))
    except (TypeError, ValueError):
        return None


def _lib_pin_geometry(root: list) -> dict[str, dict[str, tuple[float, float]]]:
    """lib_symbols → {lib 符号全名: {pin 号: (局部 x, 局部 y)}}（at=连接端）。"""
    out: dict[str, dict[str, tuple[float, float]]] = {}
    libs = _sub(root, "lib_symbols")
    if libs is None:
        return out
    for sym in _subs(libs, "symbol"):
        name = str(sym[1])
        pins: dict[str, tuple[float, float]] = {}
        for child in sym[2:]:
            if not isinstance(child, list) or not child:
                continue
            if child[0] == "symbol":
                for p in _subs(child, "pin"):
                    at = _xy(_sub(p, "at"))
                    num_node = _sub(p, "number")
                    if at is None or num_node is None or len(num_node) < 2:
                        continue
                    pins[str(num_node[1])] = at
        out[name] = pins
    return out


def readback_nets(sch_text: str) -> NetReadback:
    """自产/外部 .kicad_sch 文本 → net 连通集（round-trip 证书读侧）。

    算法：lib 引脚几何 × 实例（angle=0，Y 翻转）→ 引脚世界点；wire 端点
    与 label 锚点按坐标 union-find（1e-4 mm 量化）；每连通簇的 label 名=
    net 名（同簇多 label 名如实多键入 nets——短路在证书 diff 必现形）。
    仅支持实例 angle=0（自产恒 0；外部文件非 0 抛 ValueError 如实拒绝）。
    """
    top = parse_sexpr(sch_text)
    if len(top) != 1 or not isinstance(top[0], list) or not top[0] \
            or top[0][0] != "kicad_sch":
        raise ValueError("不是 kicad_sch 文件（根节点缺失或多根）")
    root = top[0]
    libs = _lib_pin_geometry(root)

    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def find(k: tuple[float, float]) -> tuple[float, float]:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: tuple[float, float], b: tuple[float, float]) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def node(k: tuple[float, float]) -> tuple[float, float]:
        q = (round(k[0], 4), round(k[1], 4))
        if q not in parent:
            parent[q] = q
        return q

    pin_pts: list[tuple[tuple[str, str], tuple[float, float]]] = []
    for sym in _subs(root, "symbol"):
        lib_node = _sub(sym, "lib_id")
        lib_id = str(lib_node[1]) if lib_node and len(lib_node) > 1 else ""
        at = _xy(_sub(sym, "at"))
        if at is None or not lib_id:
            continue
        at_node = _sub(sym, "at")
        angle = 0.0
        if at_node is not None and len(at_node) > 3:
            try:
                angle = float(at_node[3])
            except (TypeError, ValueError):
                angle = 0.0
        if angle != 0:
            raise ValueError(f"实例 angle={angle} 不受支持（自产恒 0）")
        geom = libs.get(lib_id)
        if geom is None:
            continue
        ref = _prop_value(sym, "Reference")
        for num, (lx, ly) in geom.items():
            q = node((at[0] + lx, at[1] - ly))
            pin_pts.append(((ref, num), q))
    for w in _subs(root, "wire"):
        pts = _sub(w, "pts")
        if pts is None:
            continue
        xys = [x for x in (_xy(p) for p in _subs(pts, "xy")) if x is not None]
        qs = [node(x) for x in xys]
        for a, b in itertools.pairwise(qs):
            union(a, b)
    labels: list[tuple[str, tuple[float, float]]] = []
    for lab in _subs(root, "label"):
        at = _xy(_sub(lab, "at"))
        if at is not None and len(lab) > 1:
            labels.append((str(lab[1]), node(at)))

    cluster_pins: dict[tuple[float, float], list[tuple[str, str]]] = {}
    for ref_pin, q in pin_pts:
        cluster_pins.setdefault(find(q), []).append(ref_pin)
    nets: dict[str, list[tuple[str, str]]] = {}
    named: set[tuple[float, float]] = set()
    for name, q in labels:
        named.add(find(q))
        nets.setdefault(name, [])
    for name, q in labels:
        for rp in cluster_pins.get(find(q), []):
            if rp not in nets[name]:
                nets[name].append(rp)
    for v in nets.values():
        v.sort()
    unnamed_pins = sorted(
        rp for r, plist in cluster_pins.items() if r not in named
        for rp in plist)
    return NetReadback(nets=nets, unnamed_pins=unnamed_pins)


# ---------------------------------------------------------------------------
# kicad-cli ERC 报告解析（report 文本格式；KiCad 10.0.6 真机样本定稿）
# ---------------------------------------------------------------------------

#: 汇总行（KiCad 10 实测格式）::
#:     ** ERC messages: 10  Errors 0  Warnings 10
_ERC_SUMMARY_RE = re.compile(
    r"\*\*\s*ERC\s+messages:\s*(\d+)\s+Errors\s+(\d+)\s+Warnings\s+(\d+)",
    re.IGNORECASE)
#: 条目头 ``[isolated_pin_label]: Label connected to only one pin``
#: （KiCad 10 条目 tag 无 ``erc_`` 前缀——KiCad 9 老格式不同，勿混）。
_ERC_ITEM_RE = re.compile(r"^\[([a-z0-9_]+)\]\s*:\s*(.*)$", re.IGNORECASE)
#: 条目内 severity 行 ``    ; error`` / ``    ; warning``。
_ERC_SEVERITY_RE = re.compile(r"^;\s*(error|warning|exclusions?)\s*$",
                              re.IGNORECASE)


def parse_erc_report(rpt_text: str) -> dict:
    """kicad-cli ``sch erc`` report 文本 → 计数与条目（纯解析，零子进程）。

    口径（KiCad 10.0.6 真机样本定稿，样本=
    ``tests/unit/fixtures/kicad_sch/erc_report_sample.rpt``，来源
    runs/aurora_q/qcad1_smoke/）：
    - 汇总行 ``** ERC messages: T  Errors E  Warnings W`` 给三计数（T=E+W）；
    - 条目块以 ``[tag]: 标题`` 起头，块内 ``; error``/``; warning`` 行定
      severity，其余缩进行=逐例明细（原样收集）；
    - 计数与条目数**独立**（条目受 --severity 过滤影响，汇总行恒全量），
      两口径都落信封不合并（#331 族：观察工具不美化）。
    缺汇总行（malformed/空报告）→ ``{"ok": False, "errors": [...]}``，
    error_count/warning_count 置 None（不伪造 0——0 是合法实测值）。
    """
    summary: tuple[int, int, int] | None = None
    items: list[dict] = []
    current: dict | None = None
    for ln in rpt_text.splitlines():
        m = _ERC_SUMMARY_RE.search(ln)
        if m:
            summary = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            continue
        mi = _ERC_ITEM_RE.match(ln.strip())
        if mi:
            current = {"type": mi.group(1).lower(), "title": mi.group(2).strip(),
                       "severity": None, "details": []}
            items.append(current)
            continue
        if current is None:
            continue
        ms = _ERC_SEVERITY_RE.match(ln.strip())
        if ms:
            current["severity"] = ms.group(1).lower()
            continue
        if ln.strip():
            current["details"].append(ln.rstrip())
    if summary is None:
        return {"ok": False,
                "errors": ["ERC 报告缺汇总行（** ERC messages: N Errors E "
                           "Warnings W）——格式不识别或空报告"],
                "error_count": None, "warning_count": None, "items": items}
    return {"ok": True, "total_count": summary[0],
            "error_count": summary[1], "warning_count": summary[2],
            "items": items, "errors": []}
