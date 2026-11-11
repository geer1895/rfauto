"""LVS 网表对照器服务（Q-X49 aurora_q——netgen 思想借鉴化用，自研实现）。

LVS（Layout vs Schematic）是 IC 设计核心验证步骤：比较版图提取网表与
原理图网表的**拓扑一致性**。本席在 Q-X33 SPICE 深度解析
（core.spice_netlist_parser，只读消费）之上补**网表级结构对照**单源
（与既有 ``rfauto layout lvs`` 几何 flag 级对照互补——那是几何网表对
参考连接表的旗检，本席是两份网表文本的全图同构比对）：

1. **网表归一化**：两种网表源（SPICE netlist + Verilog 门级 netlist）
   归一到统一图表示（元件顶点+网络顶点+带引脚序的关联边）；SPICE 走
   core.spice_netlist_parser 三格式统一解析（顶层 scope，子电路体不
   展开——与解析器口径一致）；Verilog 优先消费 ``rfauto.core.
   verilog_netlist_parser.parse_verilog``（Q-X47 席面，同窗落树——
   ``_core_verilog_parser`` 单点探测只读消费，schema 不识/模块缺失时
   兜底本模块内置最小门级归一器，切换在信封 ``layout.
   verilog_parser_source``=core|builtin 如实披露非静默）；
2. **拓扑比对**：图同构检测（1-WL 颜色精化剪枝 + 元件序回溯，网络映射
   由元件映射一致性派生——双向检查+基数相等=双射）+ 元件清单比对
   （missing/extra 两类差异）+ 同构映射下逐对参数比对（容差 =
   ``--tolerance`` 相对容差 ``|a-b| <= tol*max(|a|,|b|)``）；
3. **RF 特化**（``--rf``）：S 参数端口数量/序号/阻抗比对 + 传输线拓扑
   分类比对（串联/并联按非地网络数，耦合线按 K 互感引用归组）；
4. **对照报告**：``{verdict: MATCH|MISMATCH|PARTIAL, score: [0-1],
   differences: [...], summary}`` 信封（AU-2 三构造器契约）。

verdict 语义（如实三分，不凑绿不误判）：
- ``MATCH``：图同构成立 + 零差异（含参数在容差内 + RF 检查全过）；
- ``MISMATCH``：**结构性**不一致——missing/extra 元件、同构失败、
  端口数量/序号不齐、传输线分类不齐（RF）；
- ``PARTIAL``：结构一致但**值级**出窗——参数超容差/端口阻抗超容差
  （RF），或同构搜索预算耗尽不可判定（``undecidable`` 差异 + warning
  如实，不猜 MATCH 不猜 MISMATCH）。

score 口径（确定性公式，docstring 单源）::

    total   = max(n_elements_layout, n_elements_schematic)
              （RF 开启再加 max(端口数) + 传输线分类键数）
    penalty = missing×1 + extra×1 + 端口不齐×1 + 分类不齐×1
              + 同构失败×max(元件数)（结构全扣）
              + 参数出窗×0.5 + 阻抗出窗×0.5
    score   = clamp(1 - penalty/total, 0, 1)（total=0 → 1.0 空对空）

结构语义判定细节（同构引脚序）：对称族（resistor/capacitor/inductor）
两引脚可翻转（R/L/C 无极性）；其余族引脚序固定（二极管/源/晶体管/
传输线的极性与端口序不可换——D 翻转=MISMATCH 是结构判定不是参数判定）。
SPICE 名称大小写不敏感（归一小写）；Verilog 大小写敏感（语言语义）。
接地别名归一：``0``/``gnd``/``gnd!``/``1'b0`` → ``0``。

铁律 7：本模块零物理数值产出——tolerance 是对照参数非仿真结果，
全部数字来自两份网表原文解析，无任何求解/综合（解析不仿真）。

分层：service 单源（JSON 进出规则 4；文件 IO 收敛本层）；CLI 叶
``rfauto lvs compare`` 薄壳（cli/domains/lvs.py，带 --json 信封）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rfauto.core.spice_netlist_parser import (
    parse_spice_netlist_text,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_TOLERANCE",
    "LVS_COMPARE_SCHEMA",
    "LVS_FORMATS",
    "LVS_VERDICTS",
    "compare_netlist_files",
    "compare_netlist_texts",
    "detect_netlist_format",
]

#: 对照报告 schema 版本（键集/字段形状变更时升位）。
LVS_COMPARE_SCHEMA = "lvs_compare/1.0"

#: verdict 词表（对照报告单源）。
LVS_VERDICTS = ("MATCH", "MISMATCH", "PARTIAL")

#: 网表格式词表（--format 单源；auto=内容判定）。
LVS_FORMATS = ("auto", "spice", "verilog")

#: 缺省相对容差（|a-b| <= tol*max(|a|,|b|)）。
DEFAULT_TOLERANCE = 0.01

#: 同构回溯步数预算（防病态图组合爆炸——超预算=PARTIAL undecidable
#: 如实不可判定，不猜方向）。可经 compare_* 的 iso_step_budget 覆盖。
_ISO_STEP_BUDGET = 200_000

#: 引脚可翻转的对称族（R/L/C 无极性；其余族引脚序=结构语义）。
_SYMMETRIC_FAMILIES = frozenset({"resistor", "capacitor", "inductor"})

#: SPICE 元件首字母 → 统一族名（与 core.spice_netlist_parser _KIND_META
#: desc 同口径；verilog master 别名映射同表复用）。
_FAMILY_BY_KIND: dict[str, str] = {
    "R": "resistor", "C": "capacitor", "L": "inductor", "D": "diode",
    "M": "mosfet", "Q": "bjt", "J": "jfet", "Z": "mesfet",
    "V": "vsource", "I": "isource", "E": "vcvs", "F": "cccs",
    "G": "vccs", "H": "ccvs", "K": "coupling", "X": "subckt",
    "T": "tline", "O": "tline_lossy", "P": "tline_coax",
    "S": "switch", "W": "cswitch", "U": "rc_line",
    "Y": "tline_lossy_single", "N": "special", "B": "behavioral",
    "A": "xspice",
}

#: verilog master 名 → 统一族名（门级 + 无源件别名；未命中 → instance）。
_VERILOG_MASTER_FAMILY: dict[str, str] = {
    "resistor": "resistor", "res": "resistor",
    "capacitor": "capacitor", "cap": "capacitor",
    "inductor": "inductor", "ind": "inductor",
    "diode": "diode", "nmos": "mosfet", "pmos": "mosfet",
    "npn": "bjt", "pnp": "bjt",
}
#: verilog 门级原语（family=gate，kind=门名小写）。
_VERILOG_GATES = frozenset({
    "and", "nand", "or", "nor", "xor", "xnor", "not", "buf",
    "bufif0", "bufif1", "notif0", "notif1",
})
#: verilog 例化面忽略/跳过的关键字语句（行为级/声明级——MVP 门级子集）。
_VERILOG_SKIP_KEYWORDS = frozenset({
    "input", "output", "inout", "wire", "tri", "wand", "wor",
    "supply0", "supply1", "reg", "parameter", "localparam", "specify",
    "function", "task", "primitive", "assign", "always", "initial",
    "endmodule", "module",
})

#: 接地别名归一词表（大小写不敏感；SPICE 0/gnd/gnd! + verilog 1'b0）。
_GROUND_ALIASES = frozenset({"0", "gnd", "gnd!", "1'b0"})

#: 值别名参数键（主值已由 value 承载，参数键比对排除——防 R=1k vs
#: 位置值 1000 的假差异；键小写）。
_VALUE_ALIAS_KEYS = frozenset({
    "r", "res", "resistance", "c", "cap", "capacitance",
    "l", "ind", "inductance", "dc", "value",
} | {k.lower() for k in _FAMILY_BY_KIND})

#: RF 端口序号参数键（SPICE P 元件显式端口声明；键小写）。
_PORT_INDEX_KEYS = ("port", "portnum", "num")
#: RF 端口阻抗参数键别名（键小写）。
_PORT_Z0_KEYS = ("z0", "zo", "impedance")
#: 传输线分类适用族（RF 特化；coupling=K 是归组依据非分类对象）。
_TLINE_FAMILIES = frozenset({"tline", "tline_lossy", "tline_coax"})

_MODULE_RE = re.compile(r"\bmodule\b")


# --------------------------------------------------------------------------- #
# 归一化：统一图表示
# --------------------------------------------------------------------------- #


def _normalize_net(name: Any) -> str:
    """网络名归一（接地别名大小写不敏感 → ``0``；其余去空白原文保留）。"""
    s = str(name).strip()
    if s.lower() in _GROUND_ALIASES:
        return "0"
    return s


def _norm_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """参数键小写归一（SPICE 大小写不敏感口径；值原样保留）。"""
    return {str(k).lower(): v for k, v in (params or {}).items()}


def _value_of_params(params: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    """值别名参数回填查找（首个命中；键已小写）。"""
    for alias in aliases:
        if alias in params:
            return params[alias]
    return None


def _detect_format(text: str) -> str:
    """内容格式判定（``auto`` 单源）：module/endmodule 形态 → verilog，
    其余 → spice（SPICE 是 RF 网表事实主流缺省，flavor 由 Q-X33 解析器
    内部判定）。"""
    if _MODULE_RE.search(text) and re.search(r"\bendmodule\b", text):
        return "verilog"
    return "spice"


def normalize_format(fmt: str) -> str:
    """格式词表校验/归一（小写去空白）；词表外显式 ValueError。"""
    f = str(fmt).strip().lower()
    if f not in LVS_FORMATS:
        raise ValueError(
            f"fmt={fmt!r} 不在词表 {list(LVS_FORMATS)}（auto/spice/verilog）"
        )
    return f


def _core_verilog_parser():
    """Q-X47 verilog_netlist_parser 落树探测（惰性，缺失恒 None）。

    落树后本单点切换为只读消费（禁改清单"只读消费"的兑现位）；Q-X47
    入口名 ``parse_verilog``（2026-11-07 落树实测；任务书预估名
    ``parse_verilog_netlist_text`` 亦保留探测——双名兼容，先新后旧）。
    探测不中或 schema 不识 → 内置最小归一器兜底（切换在信封
    verilog_parser_source=core|builtin 如实披露非静默）。
    """
    try:
        from rfauto.core import verilog_netlist_parser as _vnp
    except ImportError:
        return None
    for name in ("parse_verilog", "parse_verilog_netlist_text"):
        fn = getattr(_vnp, name, None)
        if callable(fn):
            return fn
    return None


def _parse_verilog_netlist_text(text: str) -> dict:
    """内置最小门级 Verilog 归一器（Q-X49 自研，fail-soft）。

    子集：module 头（端口序）、input/output/inout/wire 声明、
    ``master [#(.p(v))] inst (conns);`` 例化子（位置/命名连接形态，
    命名连接按出现序摊平 + warning 如实）、门级原语与无源件 master
    别名。行为级（assign/always）与向量位选跳过 + warning——解析是
    结构 MVP 不是完整语言前端（模块 docstring 如实声明）。
    """
    warnings: list[str] = []
    body = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", " ", body)
    statements = [s.strip() for s in body.replace("\n", " ").split(";")]
    modules: list[dict] = []
    cur: dict | None = None
    for stmt in statements:
        toks = _verilog_tokens(stmt)
        if not toks:
            continue
        head = toks[0]
        if head == "module":
            name, ports = _parse_module_header(toks)
            cur = {"name": name, "ports": ports, "nets": set(),
                   "elements": []}
            modules.append(cur)
            continue
        if head == "endmodule":
            cur = None
            continue
        if cur is None:
            continue
        if head in ("input", "output", "inout", "wire", "tri", "reg",
                    "wand", "wor", "supply0", "supply1"):
            for nm in _decl_names(toks[1:], warnings):
                if head in ("input", "output", "inout") and nm not in cur["ports"]:
                    cur["ports"].append(nm)
                cur["nets"].add(nm)
            continue
        if head in ("parameter", "localparam", "specify", "function",
                    "task", "primitive", "assign", "always", "initial"):
            if head in ("assign", "always", "initial"):
                warnings.append(
                    f"verilog 行为级语句（{head}）不在门级结构子集内，跳过"
                    "（LVS 结构对照 MVP 口径）")
            continue
        _parse_verilog_instance(toks, cur, warnings)

    if not modules:
        warnings.append("未找到 module 定义（门级子集口径）")
        return {"modules": [], "elements": [], "ports": [], "nets": [],
                "warnings": warnings}
    if len(modules) > 1:
        warnings.append(
            f"多 module 文件取首个 module {modules[0]['name']!r} 对照"
            f"（其余 {len(modules) - 1} 个未展开——顶层口径与 SPICE 一致）")
    top = modules[0]
    return {
        "modules": [m["name"] for m in modules],
        "elements": top["elements"],
        "ports": top["ports"],
        "nets": sorted(top["nets"]),
        "warnings": warnings,
    }


def _verilog_tokens(stmt: str) -> list[str]:
    """语句 → 令牌（#(.x(y)) 参数段与 .name(conn) 连接段保持原子性）。"""
    toks: list[str] = []
    i = 0
    n = len(stmt)
    while i < n:
        ch = stmt[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "#":
            # #(.p(v)) 参数段：括号深度感知扫描（嵌套 (1000) 不误断）
            j = i + 1
            depth = 0
            started = False
            while j < n:
                if stmt[j] == "(":
                    depth += 1
                    started = True
                elif stmt[j] == ")":
                    depth -= 1
                    if started and depth == 0:
                        break
                j += 1
            toks.append(stmt[i:j + 1])
            i = j + 1
            continue
        if ch == "(":
            depth = 0
            j = i
            while j < n:
                if stmt[j] == "(":
                    depth += 1
                elif stmt[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            toks.append(stmt[i:j + 1])
            i = j + 1
            continue
        j = i
        while j < n and not stmt[j].isspace() and stmt[j] not in "(),":
            j += 1
        if j == i:
            j = i + 1
        toks.append(stmt[i:j])
        i = j
    return toks


def _parse_module_header(toks: list[str]) -> tuple[str, list[str]]:
    """module 头 → (name, 有序端口名表)。

    ANSI 形态（``module m(input a, output b)``）与非 ANSI（``module
    m(a, b)``）统一：取头括号内标识符，剔除方向/网络关键字（ANSI 声明
    内联时方向关键字后随的名字才是端口名）。
    """
    joined = " ".join(toks[1:])
    m = re.match(r"(\w+)\s*\((.*)\)?", joined, flags=re.DOTALL)
    if m is None:
        name_m = re.match(r"(\w+)", joined)
        return (name_m.group(1) if name_m else "anonymous"), []
    name = m.group(1)
    inner = m.group(2).rstrip(") ")  # 贪婪 (.*) 吞进的尾括号剥离
    ports: list[str] = []
    skip_next = False
    for raw in re.split(r"[,()]", inner):
        for tok in raw.split():
            low = tok.lower()
            if low in ("input", "output", "inout", "wire", "tri", "reg"):
                skip_next = True  # ANSI：方向关键字后的下一标识符是端口名
                continue
            if re.match(r"^\[", tok):
                continue  # 向量范围
            if skip_next or re.match(r"^\w+", tok):
                if tok not in ports:
                    ports.append(tok)
                skip_next = False
    return name, ports


def _decl_names(toks: list[str], warnings: list[str]) -> list[str]:
    """input/output/wire 声明 → 名字表（向量范围剥离 + warning）。"""
    names: list[str] = []
    for tok in toks:
        if tok.startswith("["):
            warnings.append(
                f"verilog 向量声明 {tok} 按标量单网处理（位级展开超 MVP 口径）")
            continue
        for piece in re.split(r"[,\s]+", tok):
            if re.match(r"^\w+$", piece):
                names.append(piece)
    return names


def _parse_verilog_params(text: str | None) -> dict[str, Any]:
    """``#(.p(v), .q(2))`` → params dict（数值字面量解析，余者原文）。"""
    if not text or not text.startswith("#"):
        return {}
    inner = text[1:].strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    params: dict[str, Any] = {}
    for part in re.split(r",(?![^()]*\))", inner):
        m = re.match(r"\s*\.(\w+)\s*\(\s*(.*?)\s*\)\s*$", part, flags=re.DOTALL)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        try:
            params[key.lower()] = float(raw)
        except ValueError:
            params[key.lower()] = raw.strip()
    return params


def _parse_verilog_connections(text: str | None, warnings: list[str],
                               inst_name: str) -> list[str]:
    """连接段 → 有序网络名表（命名连接按出现序摊平 + warning 如实）。"""
    if not text or not (text.startswith("(") and text.endswith(")")):
        return []
    inner = text[1:-1]
    nodes: list[str] = []
    named = False
    for part in _split_conn_list(inner):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^\.(\w+)\s*\(\s*(.*?)\s*\)$", part, flags=re.DOTALL)
        if m:
            named = True
            nodes.append(_normalize_net(m.group(2)))
            continue
        nodes.append(_normalize_net(part))
    if named:
        warnings.append(
            f"verilog 例化 {inst_name} 命名端口连接按出现序摊平（名端口"
            "语义序不在 MVP 口径——跨名序实例可能假差异，warning 如实）")
    return nodes


def _split_conn_list(inner: str) -> list[str]:
    """连接表逗号拆分（括号深度感知——.a(expr(x)) 复合表达式不误拆）。"""
    parts: list[str] = []
    depth = 0
    buf = ""
    for ch in inner:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    if buf.strip():
        parts.append(buf)
    return parts


def _parse_verilog_instance(toks: list[str], module: dict,
                            warnings: list[str]) -> None:
    """例化子 → 元素条目（门级原语/无源别名/通用 instance 三归档）。"""
    idx = 0
    master = toks[idx]
    idx += 1
    params: dict[str, Any] = {}
    if toks[idx:idx + 1] and toks[idx].startswith("#"):
        params = _parse_verilog_params(toks[idx])
        idx += 1
    if toks[idx:idx + 1]:
        inst_name = toks[idx]
        idx += 1
    else:
        warnings.append(f"verilog 例化缺实例名，跳过: {' '.join(toks)!r}")
        return
    conn_text = toks[idx] if toks[idx:idx + 1] else None
    nodes = _parse_verilog_connections(conn_text, warnings, inst_name)
    master_low = master.lower()
    if master_low in _VERILOG_GATES:
        family = "gate"
        kind = master_low
    else:
        family = _VERILOG_MASTER_FAMILY.get(master_low, "instance")
        kind = master_low
    value = None
    if family in _SYMMETRIC_FAMILIES:
        value = _value_of_params(
            params, (master_low, master_low[:3],
                     {"resistor": "r", "capacitor": "c",
                      "inductor": "l"}.get(family, "")))
    module["elements"].append({
        "name": inst_name,
        "kind": kind,
        "family": family,
        "nodes": [_normalize_net(x) for x in nodes],
        "value": value,
        "value_raw": None if value is None else str(value),
        "params": params,
        "model": None if family == "gate" else master,
    })
    for x in nodes:
        module["nets"].add(x)


def _normalize_verilog_graph(parsed: dict) -> dict:
    """verilog 解析 → 统一图表示（首 module 顶层；模块端口=RF 端口序）。"""
    ports = [
        {"index": i + 1, "element": None, "net": nm, "z0": None}
        for i, nm in enumerate(parsed["ports"])
    ]
    elements = parsed["elements"]
    net_set = set(parsed["nets"]) | {n for el in elements
                                     for n in el["nodes"]}
    return {
        "format": "verilog",
        "detail": None,
        "elements": elements,
        "nets": sorted(net_set),
        "ports": ports,
        "coupled_names": set(),
        "warnings": list(parsed["warnings"]),
        "n_elements": len(elements),
        "n_nets": len(net_set),
    }


def _normalize_spice_graph(parsed: dict) -> dict:
    """SPICE 五维度解析（Q-X33 core，只读）→ 统一图表示（顶层 scope）。

    顶层口径与解析器 topology 一致（子电路体为模板不展开）；名称/网络
    小写归一（SPICE 大小写不敏感）；K 互感引用 → coupled_names 归组
    （RF 耦合线分类依据）；P 元件带显式端口序号参数 → RF 端口。
    """
    warnings: list[str] = list(parsed.get("warnings") or [])
    if parsed.get("structural_errors"):
        warnings.append(
            "SPICE 解析结构错误 "
            f"{len(parsed['structural_errors'])} 条（--json 看"
            " layout.structural_errors 明细；对照按可解析部分尽力而为）")
    elements: list[dict] = []
    coupled: set[str] = set()
    ports: dict[int, dict] = {}
    for el in parsed["elements"]:
        if el.get("scope"):
            continue  # 子电路体不展开（顶层口径）
        kind = el["kind"]
        name = str(el["name"]).lower()
        nodes = [_normalize_net(n).lower() for n in el.get("nodes") or []]
        params = _norm_params(el.get("params"))
        family = _FAMILY_BY_KIND.get(kind, "special")
        entry = {
            "name": name,
            "kind": kind,
            "family": family,
            "nodes": nodes,
            "value": el.get("value"),
            "value_raw": el.get("value_raw"),
            "params": params,
            "model": el.get("model"),
        }
        if kind == "K":
            for ref in params.get("inductors") or []:
                coupled.add(str(ref).lower())
        port_idx = _spice_port_index(el, params, name)
        if port_idx is not None:
            z0 = _spice_port_z0(params)
            if port_idx in ports:
                warnings.append(
                    f"RF 端口序号重复 port={port_idx}（{name} 与 "
                    f"{ports[port_idx]['element']}），保留首见")
            else:
                ports[port_idx] = {
                    "index": port_idx, "element": name,
                    "net": nodes[0] if nodes else None, "z0": z0,
                }
                continue  # 端口不进元件清单（端口=边界非元件）
        elements.append(entry)
    port_list = [ports[k] for k in sorted(ports)]
    nets = sorted({n for el in elements for n in el["nodes"]})
    return {
        "format": "spice",
        "detail": parsed.get("flavor"),
        "elements": elements,
        "nets": nets,
        "ports": port_list,
        "coupled_names": coupled,
        "warnings": warnings,
        "n_elements": len(elements),
        "n_nets": len(nets),
        "structural_errors": list(parsed.get("structural_errors") or []),
    }


def _spice_port_index(el: dict, params: dict, name: str) -> int | None:
    """RF 端口序号提取（显式数值参数单源——port/portnum/num 任一命中）。

    无显式端口参数的 P 元件=同轴线元件非端口（名尾数字不做回填——
    隐式推断会误吞真实 coax 元件，端口化必须显式声明，确定性契约）。
    """
    for key in _PORT_INDEX_KEYS:
        v = params.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def _spice_port_z0(params: dict) -> float | None:
    """端口阻抗参数提取（z0/zo/impedance 首个数值命中）。"""
    for key in _PORT_Z0_KEYS:
        v = params.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def load_netlist_graph(path: str | Path, fmt: str = "auto") -> dict:
    """网表文件 → 统一图表示信封（文件 IO 收敛本层；utf-8 replace 口径）。

    ok 字段：``graph``（统一图）/``format``/``path``/``warnings``/
    ``structural_errors``（spice）/``verilog_parser_source``（verilog
    时 core|builtin 如实披露）。
    """
    try:
        fmt_norm = normalize_format(fmt)
    except ValueError as exc:
        return error_envelope([str(exc)], path=str(path))
    p = Path(path)
    if not p.is_file():
        return error_envelope([f"网表文件不存在: {p}"], path=str(p))
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return error_envelope([f"网表文件不可读: {exc}"], path=str(p))
    env = _graph_from_text(text, fmt_norm)
    env["path"] = str(p)
    return env


def _graph_from_text(text: str, fmt: str) -> dict:
    """文本 → 统一图信封（auto 判定 + 双源归一分派；ok/errors 同构）。"""
    fmt_eff = detect_netlist_format(text) if fmt == "auto" else fmt
    if fmt_eff == "verilog":
        core_fn = _core_verilog_parser()
        if core_fn is not None:  # pragma: no cover - Q-X47 落树后启用
            graph = _normalize_verilog_graph_generic(core_fn(text))
            if graph is not None:
                return ok_envelope(graph=graph, format="verilog",
                                   verilog_parser_source="core",
                                   warnings=graph["warnings"])
        parsed = _parse_verilog_netlist_text(text)
        graph = _normalize_verilog_graph(parsed)
        return ok_envelope(graph=graph, format="verilog",
                           verilog_parser_source="builtin",
                           warnings=graph["warnings"])
    parsed = parse_spice_netlist_text(text)
    graph = _normalize_spice_graph(parsed)
    return ok_envelope(graph=graph, format="spice",
                       verilog_parser_source=None,
                       structural_errors=graph["structural_errors"],
                       warnings=graph["warnings"])


def _coerce_verilog_number(raw: str) -> Any:
    """verilog 参数值数值化（Q-X47 词法把指数拆令牌回拼 "2 e - 12"
    ——先原样 float、再去空白重试；两败保留原文）。"""
    s = str(raw).strip()
    try:
        return float(s)
    except ValueError:
        try:
            return float(re.sub(r"\s+", "", s))
        except ValueError:
            return s


def _normalize_verilog_graph_generic(parsed: dict) -> dict | None:
    """Q-X47 core 解析输出 → 统一图（防御式键名探测；不认识返回 None）。

    schema（Q-X47 落树实测 verilog_netlist/1.0）：``modules``{名→
    {ports[{name,direction,width}], wires, instances[{type,name,
    connections{序号|端口名→网}, params{序→".k (v)"}|None, primitive}]}}、
    ``top_modules``/``module_order``/``warnings[{line,name,note}]``。
    顶层=首个 top_modules 真顶层候选（比我内置"首 module"更准）。
    """
    if not isinstance(parsed, dict):
        return None
    modules = parsed.get("modules")
    if not isinstance(modules, dict) or not modules:
        return None
    top_name = None
    for cand in parsed.get("top_modules") or []:
        if isinstance(cand, str) and cand in modules:
            top_name = cand
            break
    if top_name is None:
        order = parsed.get("module_order") or list(modules)
        for cand in order:
            if isinstance(cand, str) and cand in modules:
                top_name = cand
                break
    if top_name is None:
        return None
    module = modules[top_name]
    if not isinstance(module, dict):
        return None
    warnings: list[str] = []
    for w in parsed.get("warnings") or []:
        if isinstance(w, dict):
            warnings.append(
                f"verilog 第 {w.get('line')} 行 {w.get('name')}: "
                f"{w.get('note')}")
        else:
            warnings.append(str(w))

    elements: list[dict] = []
    net_set: set[str] = set()
    for inst in module.get("instances") or []:
        master = str(inst.get("type") or "")
        name = str(inst.get("name") or "")
        conns = inst.get("connections") or {}
        named = inst.get("connection_style") == "named"
        keys = sorted(conns, key=lambda k: (0, int(k)) if str(k).isdigit()
                      else (1, str(k)))
        if named:
            warnings.append(
                f"verilog 例化 {name} 命名端口连接按键名序摊平（名端口"
                "语义序不在 MVP 口径——跨名序实例可能假差异，warning 如实）")
        nodes = [_normalize_net(conns[k]) for k in keys]
        params: dict[str, Any] = {}
        raw_params = inst.get("params") or {}
        if isinstance(raw_params, dict):
            for pk, raw in sorted(raw_params.items(),
                                  key=lambda kv: str(kv[0])):
                sraw = str(raw).strip()
                # Q-X47 params 双形态（同窗演进，兼容收编）：
                # a) 索引键+ ".r (1000)" 包装原文；b) 名键+裸值原文
                m = re.match(r"^\.(\w+)\s*\(\s*(.*?)\s*\)$", sraw)
                if m is not None:
                    pkey, pval = m.group(1).lower(), m.group(2)
                elif str(pk).isalpha() or "_" in str(pk):
                    pkey, pval = str(pk).lower(), sraw
                else:
                    continue  # 索引键+无法定名裸值——如实跳过不猜
                params[pkey] = _coerce_verilog_number(pval)
        is_primitive = bool(inst.get("primitive"))
        family = "gate" if is_primitive else \
            _VERILOG_MASTER_FAMILY.get(master.lower(), "instance")
        value = None
        if family in _SYMMETRIC_FAMILIES:
            value = _value_of_params(
                params, (master.lower(),
                         {"resistor": "r", "capacitor": "c",
                          "inductor": "l"}.get(family, "")))
        elements.append({
            "name": name,
            "kind": master.lower(),
            "family": family,
            "nodes": nodes,
            "value": value,
            "value_raw": None if value is None else str(value),
            "params": params,
            "model": None if is_primitive else master,
        })
        net_set.update(nodes)

    ports: list[dict] = []
    for i, p in enumerate(module.get("ports") or []):
        if not isinstance(p, dict):
            return None  # 端口形态不识 → 兜底内置器（防御）
        pname = str(p.get("name") or "")
        width = p.get("width") or {}
        if isinstance(width, dict) and (width.get("span") or 1) > 1:
            warnings.append(
                f"verilog 向量端口 {pname} 按标量单网处理"
                "（位级展开超 MVP 口径）")
        net_set.add(pname)
        ports.append({"index": i + 1, "element": None, "net": pname,
                      "z0": None})
    for w in module.get("wires") or []:
        if isinstance(w, dict):
            net_set.add(str(w.get("name") or ""))
    return {
        "format": "verilog",
        "detail": f"core/{parsed.get('schema_version')}",
        "elements": elements,
        "nets": sorted(net_set),
        "ports": ports,
        "coupled_names": set(),
        "warnings": warnings,
        "n_elements": len(elements),
        "n_nets": len(net_set),
    }


def detect_netlist_format(text: str) -> str:
    """公开格式判定（``auto`` 单源薄壳）。"""
    return _detect_format(text)


# --------------------------------------------------------------------------- #
# 图同构（1-WL 精化 + 元件回溯，网络映射派生）
# --------------------------------------------------------------------------- #


def _net_incidence(graph: dict) -> dict[str, list[tuple[str, int]]]:
    """网络 → [(元件名, 引脚序), ...]（多重度；引脚序=nodes 下标）。"""
    inc: dict[str, list[tuple[str, int]]] = {}
    for el in graph["elements"]:
        for p, net in enumerate(el["nodes"]):
            inc.setdefault(net, []).append((el["name"], p))
    return inc


def _pin_canonical(family: str, pin: int, degree: int) -> int:
    """引脚规范形（对称族翻转等价 → 反转规范形 min(p, deg-1-p)）。

    对称族二引脚元件（R/L/C）：pin0/pin1 同映 0——网络签名不区分翻转；
    其余族恒等（极性序=结构语义）。
    """
    if family in _SYMMETRIC_FAMILIES and degree == 2:
        return min(pin, degree - 1 - pin)
    return pin


def _refine_colors(gl: dict, gr: dict) -> tuple[dict, dict, int]:
    """1-WL 颜色精化（两图共享颜色词表——元组直接可比）。

    初色：元件=(family, degree)、网络=度；迭代：元件色=(旧色, 有序
    (邻网络色, 引脚规范形) 元组)、网络色=(旧色, (邻元件色, 引脚规范形)
    多重集)。类数不再增长即停（上限 8 轮）。返回 (元件色表 l, 元件色表
    r, 精化轮数)。
    """
    inc_l = _net_incidence(gl)
    inc_r = _net_incidence(gr)
    el_color_l = {el["name"]: (el["family"], len(el["nodes"]))
                  for el in gl["elements"]}
    el_color_r = {el["name"]: (el["family"], len(el["nodes"]))
                  for el in gr["elements"]}
    net_color_l = {n: ("net", len(v)) for n, v in inc_l.items()}
    net_color_r = {n: ("net", len(v)) for n, v in inc_r.items()}
    el_by_name_l = {el["name"]: el for el in gl["elements"]}
    el_by_name_r = {el["name"]: el for el in gr["elements"]}
    rounds = 0

    def _el_sig(el: dict, net_colors: dict[str, tuple]) -> tuple:
        """元件邻接签名（同构不变量——对称族多重度序、极性族位置序）。"""
        base = ((net_colors.get(n, ("isolated", 0)),
                 _pin_canonical(el["family"], p, len(el["nodes"])))
                for p, n in enumerate(el["nodes"]))
        if el["family"] in _SYMMETRIC_FAMILIES:
            return tuple(sorted(base))  # 引脚翻转等价 → 多重集
        return tuple(base)  # 极性序=结构语义

    for _ in range(8):
        rounds += 1
        new_l: dict[str, tuple] = {}
        new_r: dict[str, tuple] = {}
        for name, el in el_by_name_l.items():
            new_l[name] = (el_color_l[name],
                           _el_sig(el, net_color_l))
        for name, el in el_by_name_r.items():
            new_r[name] = (el_color_r[name],
                           _el_sig(el, net_color_r))
        new_net_l = {
            n: (net_color_l[n],
                tuple(sorted(
                    (el_color_l[en],
                     _pin_canonical(el_by_name_l[en]["family"], p,
                                    len(el_by_name_l[en]["nodes"])))
                    for en, p in v)))
            for n, v in inc_l.items()}
        new_net_r = {
            n: (net_color_r[n],
                tuple(sorted(
                    (el_color_r[en],
                     _pin_canonical(el_by_name_r[en]["family"], p,
                                    len(el_by_name_r[en]["nodes"])))
                    for en, p in v)))
            for n, v in inc_r.items()}
        # 类数（跨两图并集）不再增长即停
        before = len(set(el_color_l.values()) | set(el_color_r.values()))
        el_color_l, el_color_r = new_l, new_r
        net_color_l, net_color_r = new_net_l, new_net_r
        after = len(set(el_color_l.values()) | set(el_color_r.values()))
        if after == before:
            break
    return el_color_l, el_color_r, rounds


def _pin_permutations(family: str, degree: int) -> tuple[tuple[int, ...], ...]:
    """该族允许的引脚置换组（对称族二引脚=恒等+翻转；余者恒等）。"""
    if family in _SYMMETRIC_FAMILIES and degree == 2:
        return ((0, 1), (1, 0))
    return (tuple(range(degree)),)


def _find_isomorphism(gl: dict, gr: dict, budget: int) -> dict:
    """图同构回溯（元件主搜，网络映射由关联一致性派生）。

    前提：两图元件数相等（调用方保证）。搜序=（-度, 色, 名）确定性排序
    （最受限优先）；候选=同色未用元件 × 允许引脚置换；每步派生网络
    映射双向一致性检查（l→r 与 r→l 冲突即剪枝）。步数超预算 →
    ``budget_exceeded=True`` 如实返回（调用方判 PARTIAL undecidable）。
    """
    el_color_l, el_color_r, rounds = _refine_colors(gl, gr)
    el_by_l = {el["name"]: el for el in gl["elements"]}
    el_by_r = {el["name"]: el for el in gr["elements"]}
    cand_by_color: dict[tuple, list[str]] = {}
    for name, color in el_color_r.items():
        cand_by_color.setdefault(color, []).append(name)
    order = sorted(el_by_l, key=lambda n: (-len(el_by_l[n]["nodes"]),
                                           str(el_color_l[n]), n))
    used_r: set[str] = set()
    net_map: dict[str, str] = {}
    net_map_rev: dict[str, str] = {}
    elem_map: dict[str, str] = {}
    steps = 0
    exceeded = False

    def assign(el_name: str, cand_name: str, perm: tuple[int, ...]) -> bool:
        el = el_by_l[el_name]
        cand = el_by_r[cand_name]
        added: list[str] = []
        ok = True
        for p, net_l in enumerate(el["nodes"]):
            net_r = cand["nodes"][perm[p]]
            if net_l in net_map:
                if net_map[net_l] != net_r:
                    ok = False
                    break
            elif net_r in net_map_rev:
                ok = False
                break
            else:
                net_map[net_l] = net_r
                net_map_rev[net_r] = net_l
                added.append(net_l)
        if not ok:
            for nl in added:
                nr = net_map.pop(nl, None)
                if nr is not None:
                    net_map_rev.pop(nr, None)
        return ok

    def backtrack(i: int) -> bool:
        nonlocal steps, exceeded
        if i == len(order):
            return True
        el_name = order[i]
        el = el_by_l[el_name]
        color = el_color_l[el_name]
        for cand_name in cand_by_color.get(color, []):
            if cand_name in used_r:
                continue
            for perm in _pin_permutations(el["family"], len(el["nodes"])):
                steps += 1
                if steps > budget:
                    exceeded = True
                    return False
                if not assign(el_name, cand_name, perm):
                    continue
                used_r.add(cand_name)
                elem_map[el_name] = cand_name
                if backtrack(i + 1):
                    return True
                used_r.discard(cand_name)
                del elem_map[el_name]
                # 回滚本元素派生的网络映射（elem_map 已撤本项后全量重建）
                rollback_net_map()
        return False

    def rollback_net_map() -> None:
        """撤销已回溯元素的网络映射（按 elem_map 幸存项全量重建）。"""
        # 撤销需知道该元件最后分配时用的 perm——改为全量重建：回溯深度
        # 内重放。MVP 口径：小图（单元测试量级）全量重建成本可忽略；
        # 大图靠颜色精化剪枝不进深回溯（预算护栏）。
        keep_pairs = set()
        for done_l, done_r in elem_map.items():
            done_el = el_by_l[done_l]
            done_cand = el_by_r[done_r]
            for p, net_l in enumerate(done_el["nodes"]):
                keep_pairs.add((net_l, done_cand["nodes"][p]))
        for nl in list(net_map):
            if (nl, net_map[nl]) not in keep_pairs:
                nr = net_map.pop(nl)
                net_map_rev.pop(nr, None)

    matched = backtrack(0)
    if not matched:
        elem_map, net_map = {}, {}
    return {
        "matched": bool(matched),
        "element_mapping": dict(sorted(elem_map.items())),
        "net_mapping": dict(sorted(net_map.items())),
        "steps": steps,
        "budget_exceeded": exceeded,
        "refine_rounds": rounds,
        "color_l": {k: str(v) for k, v in sorted(el_color_l.items())},
        "color_r": {k: str(v) for k, v in sorted(el_color_r.items())},
    }


# --------------------------------------------------------------------------- #
# 比对核心
# --------------------------------------------------------------------------- #


def _values_close(a: float, b: float, tol: float) -> bool:
    """相对容差判等（|a-b| <= tol*max(|a|,|b|)；零对零恒等）。"""
    m = max(abs(float(a)), abs(float(b)))
    return abs(float(a) - float(b)) <= tol * m


def _compare_value(el: dict, es: dict, tol: float) -> dict | None:
    """主值比对（数值走容差；双表达式走 raw 小写比对；缺边如实出窗）。"""
    vl, vs = el.get("value"), es.get("value")
    if isinstance(vl, (int, float)) and isinstance(vs, (int, float)):
        if _values_close(vl, vs, tol):
            return None
        return {"param": "value", "layout": vl, "schematic": vs}
    if vl is None and vs is None:
        rl = str(el.get("value_raw") or "").lower()
        rs = str(es.get("value_raw") or "").lower()
        if rl == rs:
            return None
        return {"param": "value_raw", "layout": rl or None,
                "schematic": rs or None}
    return {"param": "value", "layout": vl, "schematic": vs,
            "note": "一侧无数值（表达式/缺失哨兵 None 恒非 0——#117 同族）"}


def _compare_params(el: dict, es: dict, tol: float) -> list[dict]:
    """同构对参数键比对（值别名键排除；数值容差/字符串精确）。"""
    diffs: list[dict] = []
    pl: dict = {k: v for k, v in (el.get("params") or {}).items()
                if k not in _VALUE_ALIAS_KEYS}
    ps: dict = {k: v for k, v in (es.get("params") or {}).items()
                if k not in _VALUE_ALIAS_KEYS}
    for k in sorted(set(pl) | set(ps)):
        vl = pl.get(k)
        vs = ps.get(k)
        if vl is None or vs is None:
            diffs.append({"param": k, "layout": vl, "schematic": vs,
                          "note": "单侧参数键"})
            continue
        if isinstance(vl, (int, float)) and not isinstance(vl, bool) \
                and isinstance(vs, (int, float)) and not isinstance(vs, bool):
            if not _values_close(vl, vs, tol):
                diffs.append({"param": k, "layout": vl, "schematic": vs})
            continue
        if str(vl) != str(vs):
            diffs.append({"param": k, "layout": vl, "schematic": vs})
    return diffs


def _classify_tline(el: dict, coupled: frozenset[str]) -> str:
    """传输线分类（RF 特化单源）：

    - inductor：K 互感引用 → ``coupled``，否则 ``isolated``；
    - tline 族：非地网络数（去重）==1 → ``shunt``（单网络短路/开路枝
      ——如 ``T a 0 0 0``），>=2 → ``series``（在线二端口）；端口化
      P 元件不进分类（边界非元件）。
    """
    if el["family"] == "inductor":
        return "coupled" if el["name"] in coupled else "isolated"
    non_ground = {n for n in el["nodes"] if n != "0"}
    return "series" if len(non_ground) >= 2 else "shunt"


def _compare_rf(gl: dict, gr: dict, tol: float) -> tuple[list[dict], dict]:
    """RF 特化比对（端口数量/序号/阻抗 + 传输线分类清单）。"""
    diffs: list[dict] = []
    ports_l = {p["index"]: p for p in gl["ports"]}
    ports_r = {p["index"]: p for p in gr["ports"]}
    z0_compared = 0
    for idx in sorted(set(ports_l) | set(ports_r)):
        pl = ports_l.get(idx)
        pr = ports_r.get(idx)
        if pl is None or pr is None:
            side = "layout" if pl is not None else "schematic"
            diffs.append({
                "category": "mismatched", "type": "port_mismatch",
                "side": side, "port_index": idx,
                "detail": f"端口序号 {idx} 仅 {'layout' if pl is not None else 'schematic'} 侧存在",
            })
            continue
        zl, zr = pl.get("z0"), pr.get("z0")
        if isinstance(zl, (int, float)) and isinstance(zr, (int, float)):
            z0_compared += 1
            if not _values_close(zl, zr, tol):
                diffs.append({
                    "category": "mismatched", "type": "impedance_mismatch",
                    "side": None, "port_index": idx,
                    "detail": f"端口 {idx} 阻抗超容差",
                    "layout": zl, "schematic": zr, "tolerance": tol,
                })
    cls_l: dict[tuple, int] = {}
    cls_r: dict[tuple, int] = {}
    for el in gl["elements"]:
        if el["family"] in _TLINE_FAMILIES or el["family"] == "inductor":
            key = (el["family"], _classify_tline(el, gl["coupled_names"]))
            cls_l[key] = cls_l.get(key, 0) + 1
    for el in gr["elements"]:
        if el["family"] in _TLINE_FAMILIES or el["family"] == "inductor":
            key = (el["family"], _classify_tline(el, gr["coupled_names"]))
            cls_r[key] = cls_r.get(key, 0) + 1
    for key in sorted(set(cls_l) | set(cls_r)):
        cl, cr = cls_l.get(key, 0), cls_r.get(key, 0)
        if cl != cr:
            diffs.append({
                "category": "mismatched", "type": "tline_class_mismatch",
                "side": None, "family": key[0], "tline_class": key[1],
                "detail": f"{key[0]}/{key[1]} 计数 layout={cl} schematic={cr}",
                "layout_count": cl, "schematic_count": cr,
            })
    rf_summary = {
        "n_ports_layout": len(ports_l),
        "n_ports_schematic": len(ports_r),
        "z0_compared": z0_compared,
        "tline_class_layout": {f"{k[0]}/{k[1]}": v
                               for k, v in sorted(cls_l.items())},
        "tline_class_schematic": {f"{k[0]}/{k[1]}": v
                                  for k, v in sorted(cls_r.items())},
    }
    return diffs, rf_summary


def _structural_missing_extra(gl: dict, gr: dict) -> tuple[list[dict], int]:
    """元件清单比对（按族计数；missing=schematic 独有，extra=layout 独有）。

    计数差逐族展开为点名差异（族内名称按字典序，配对消耗）。返回
    (差异列表, 可比对元件对数上界=min(同族计数))。
    """
    diffs: list[dict] = []
    by_l: dict[str, list[str]] = {}
    by_r: dict[str, list[str]] = {}
    for el in gl["elements"]:
        by_l.setdefault(el["family"], []).append(el["name"])
    for el in gr["elements"]:
        by_r.setdefault(el["family"], []).append(el["name"])
    pairable = 0
    for family in sorted(set(by_l) | set(by_r)):
        names_l = sorted(by_l.get(family, []))
        names_r = sorted(by_r.get(family, []))
        pairable += min(len(names_l), len(names_r))
        for nm in names_r[len(names_l):] if len(names_r) > len(names_l) \
                else []:
            diffs.append({
                "category": "missing", "type": "missing_element",
                "side": "schematic", "family": family, "element": nm,
                "detail": f"schematic 独有 {family} {nm}（layout 缺失）",
            })
        for nm in names_l[len(names_r):] if len(names_l) > len(names_r) \
                else []:
            diffs.append({
                "category": "extra", "type": "extra_element",
                "side": "layout", "family": family, "element": nm,
                "detail": f"layout 独有 {family} {nm}（schematic 无对应）",
            })
    return diffs, pairable


def _compare_graphs(gl: dict, gr: dict, tol: float, rf: bool,
                    iso_budget: int) -> dict:
    """统一图比对核心（纯函数；信封包装由调用方做）。"""
    warnings: list[str] = []
    diffs: list[dict] = []
    n_l, n_r = gl["n_elements"], gr["n_elements"]
    iso: dict = {
        "matched": False, "element_mapping": {}, "net_mapping": {},
        "steps": 0, "budget_exceeded": False, "refine_rounds": 0,
        "attempted": False,
    }
    if not gl["elements"] and not gr["elements"]:
        warnings.append("双方均零元件（空对空平凡一致——如非预期请查解析面）")

    inv_diffs, pairable = _structural_missing_extra(gl, gr)
    diffs.extend(inv_diffs)

    matched_pairs = 0
    if n_l == n_r and not inv_diffs and n_l > 0:
        iso["attempted"] = True
        iso = _find_isomorphism(gl, gr, iso_budget)
        if iso["matched"]:
            matched_pairs = n_l
            el_by_l = {el["name"]: el for el in gl["elements"]}
            el_by_r = {el["name"]: el for el in gr["elements"]}
            for name_l, name_r in iso["element_mapping"].items():
                vdiff = _compare_value(el_by_l[name_l], el_by_r[name_r], tol)
                if vdiff is not None:
                    diffs.append({
                        "category": "mismatched", "type": "param_mismatch",
                        "side": None, "layout_element": name_l,
                        "schematic_element": name_r, **vdiff,
                        "detail": f"{name_l}↔{name_r} 参数 "
                                  f"{vdiff['param']} 超容差",
                    })
                for pd in _compare_params(el_by_l[name_l],
                                          el_by_r[name_r], tol):
                    diffs.append({
                        "category": "mismatched", "type": "param_mismatch",
                        "side": None, "layout_element": name_l,
                        "schematic_element": name_r, **pd,
                        "detail": f"{name_l}↔{name_r} 参数 {pd['param']} 不一致",
                    })
        else:
            detail = "两网表结构不同构（元件清单一致但连接关系不同）"
            if iso["budget_exceeded"]:
                detail = ("同构搜索预算耗尽不可判定"
                          f"（budget={iso_budget}，steps={iso['steps']}）")
            diffs.append({
                "category": "mismatched", "type": "topology_mismatch",
                "side": None, "detail": detail,
            })
            if iso["budget_exceeded"]:
                diffs.append({
                    "category": "mismatched", "type": "undecidable",
                    "side": None,
                    "detail": "同构不可判定（预算耗尽——不猜方向，"
                              "PARTIAL 如实）",
                })
                warnings.append(
                    "同构搜索预算耗尽（verdict=PARTIAL undecidable 如实，"
                    "不凑 MATCH 不误判 MISMATCH）")
    elif n_l != n_r:
        warnings.append(
            f"元件数不等（layout={n_l} schematic={n_r}）——清单级差异"
            "已出 missing/extra，同构跳过（MVP 口径：清单不等不搜公共"
            "子图映射）")

    rf_summary: dict | None = None
    if rf:
        rf_diffs, rf_summary = _compare_rf(gl, gr, tol)
        diffs.extend(rf_diffs)

    # 结构性判定：topology_mismatch 在预算耗尽（undecidable）时不计结构红
    # ——不可判定≠判定不一致（如实三分，不凑绿不误判）
    structural = any(d["type"] in ("missing_element", "extra_element",
                                   "port_mismatch", "tline_class_mismatch")
                     for d in diffs)
    if not structural and not iso.get("budget_exceeded"):
        structural = any(d["type"] == "topology_mismatch" for d in diffs)
    undecidable = any(d["type"] == "undecidable" for d in diffs)
    if structural:
        verdict = "MISMATCH"
    elif undecidable or any(d["type"] in ("param_mismatch", "impedance_mismatch")
             for d in diffs):
        verdict = "PARTIAL"
    else:
        verdict = "MATCH"

    # score（docstring 单源公式；确定性）。同构失败（含预算耗尽）结构全扣
    # ——未验证同构=零已证一致（PARTIAL undecidable 得 score=0 如实）。
    total = max(n_l, n_r)
    penalty = 0.0
    for d in diffs:
        t = d["type"]
        if t in ("missing_element", "extra_element", "port_mismatch",
                 "tline_class_mismatch"):
            penalty += 1.0
        elif t in ("param_mismatch", "impedance_mismatch"):
            penalty += 0.5
        elif t == "topology_mismatch":
            penalty += float(max(n_l, n_r))  # 结构全扣
    if rf and rf_summary is not None:
        total += max(len(gl["ports"]), len(gr["ports"]))
        total += len(rf_summary["tline_class_layout"]) \
            + len(rf_summary["tline_class_schematic"])
    score = 1.0 if total <= 0 else max(0.0, min(1.0, 1.0 - penalty / total))

    cat_counts = {"missing": 0, "extra": 0, "mismatched": 0}
    for d in diffs:
        cat_counts[d["category"]] += 1
    diffs.sort(key=lambda d: (d["category"], d["type"],
                              str(d.get("detail", ""))))
    summary = {
        "verdict": verdict,
        "verdict_reason": (
            "零差异全同构" if verdict == "MATCH" else
            ("结构性不一致（missing/extra/同构失败/RF 结构不齐）"
             if verdict == "MISMATCH" else
             ("同构不可判定（预算耗尽）" if undecidable else
              "结构一致但值级出窗（参数/阻抗超容差）"))),
        "n_missing": cat_counts["missing"],
        "n_extra": cat_counts["extra"],
        "n_mismatched": cat_counts["mismatched"],
        "n_differences": len(diffs),
        "n_elements_layout": n_l,
        "n_elements_schematic": n_r,
        "n_nets_layout": gl["n_nets"],
        "n_nets_schematic": gr["n_nets"],
        "matched_element_pairs": matched_pairs,
        "pairable_elements": pairable,
        "budget_exceeded": bool(iso.get("budget_exceeded", False)),
    }
    return {
        "verdict": verdict,
        "score": score,
        "differences": diffs,
        "summary": summary,
        "iso": iso,
        "rf": rf_summary,
        "warnings": warnings,
    }


def compare_netlist_files(layout_path: str | Path,
                          schematic_path: str | Path,
                          tolerance: float = DEFAULT_TOLERANCE,
                          rf: bool = False, fmt: str = "auto",
                          iso_step_budget: int | None = None) -> dict:
    """两份网表文件 → LVS 对照信封（文件 IO 收敛本层；主入口）。

    ok 字段：``schema``/``verdict``/``score``/``differences``/``summary``
    /``layout``/``schematic``（两侧图描述+路径）/``iso``（同构详情）
    /``rf``（RF 特化摘要或 None）/``params``（对照参数回显）/
    ``warnings``（两侧解析警示合并）。任一侧装载失败 → error 信封
    （errors 合并两侧、side 归属如实）。
    """
    try:
        tol = float(tolerance)
    except (TypeError, ValueError):
        return error_envelope([f"tolerance 须为数值，实际 {tolerance!r}"])
    if tol < 0:
        return error_envelope([f"tolerance 须 >= 0，实际 {tol}"])
    try:
        fmt_norm = normalize_format(fmt)
    except ValueError as exc:
        return error_envelope([str(exc)])
    budget = _ISO_STEP_BUDGET if iso_step_budget is None else int(iso_step_budget)
    env_l = load_netlist_graph(layout_path, fmt_norm)
    env_r = load_netlist_graph(schematic_path, fmt_norm)
    errs: list[str] = []
    if not env_l.get("ok"):
        errs.extend(f"layout 侧: {e}" for e in env_l.get("errors") or [])
    if not env_r.get("ok"):
        errs.extend(f"schematic 侧: {e}" for e in env_r.get("errors") or [])
    if errs:
        return error_envelope(errs, layout_path=str(layout_path),
                              schematic_path=str(schematic_path))
    gl = env_l["graph"]
    gr = env_r["graph"]
    report = _compare_graphs(gl, gr, tol, rf, budget)
    return ok_envelope(
        schema=LVS_COMPARE_SCHEMA,
        verdict=report["verdict"],
        score=report["score"],
        differences=report["differences"],
        summary=report["summary"],
        layout=_side_descriptor(env_l, layout_path),
        schematic=_side_descriptor(env_r, schematic_path),
        iso=report["iso"],
        rf=report["rf"],
        params={"tolerance": tol, "rf": bool(rf),
                "format": fmt_norm,
                "iso_step_budget": budget},
        warnings=(env_l.get("warnings") or [])
        + (env_r.get("warnings") or [])
        + report["warnings"],
    )


def compare_netlist_texts(layout_text: str, schematic_text: str,
                          tolerance: float = DEFAULT_TOLERANCE,
                          rf: bool = False, fmt: str = "auto",
                          iso_step_budget: int | None = None) -> dict:
    """两份网表文本 → LVS 对照信封（程序化调用面/测试钉同源）。"""
    try:
        tol = float(tolerance)
    except (TypeError, ValueError):
        return error_envelope([f"tolerance 须为数值，实际 {tolerance!r}"])
    if tol < 0:
        return error_envelope([f"tolerance 须 >= 0，实际 {tol}"])
    try:
        fmt_norm = normalize_format(fmt)
    except ValueError as exc:
        return error_envelope([str(exc)])
    budget = _ISO_STEP_BUDGET if iso_step_budget is None else int(iso_step_budget)
    env_l = _graph_from_text(layout_text, fmt_norm)
    env_r = _graph_from_text(schematic_text, fmt_norm)
    gl = env_l["graph"]
    gr = env_r["graph"]
    report = _compare_graphs(gl, gr, tol, rf, budget)
    return ok_envelope(
        schema=LVS_COMPARE_SCHEMA,
        verdict=report["verdict"],
        score=report["score"],
        differences=report["differences"],
        summary=report["summary"],
        layout=_side_descriptor(env_l, None),
        schematic=_side_descriptor(env_r, None),
        iso=report["iso"],
        rf=report["rf"],
        params={"tolerance": tol, "rf": bool(rf),
                "format": fmt_norm,
                "iso_step_budget": budget},
        warnings=(env_l.get("warnings") or [])
        + (env_r.get("warnings") or [])
        + report["warnings"],
    )


def _side_descriptor(env: dict, path: str | Path | None) -> dict:
    """单侧装载信封 → 报告侧描述（图统计+格式+路径+解析源披露）。"""
    g = env["graph"]
    return {
        "path": str(path) if path is not None else env.get("path"),
        "format": env.get("format"),
        "detail": g.get("detail"),
        "verilog_parser_source": env.get("verilog_parser_source"),
        "n_elements": g["n_elements"],
        "n_nets": g["n_nets"],
        "n_ports": len(g["ports"]),
        "elements": [el["name"] for el in g["elements"]],
        "nets": g["nets"],
        "ports": g["ports"],
    }
