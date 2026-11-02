"""引脚级原理图内核（aurora_p A1 席，2026-11-01）：ADS 网表 → 引脚级 .drawio。

与既有五叶电路图（link/testsetup/annotate/stackup + ads-circuit 三叶）互补：
那些是**框图级**（元件框+框间连线）；本模块是**引脚级原理图**——元件符号
带引脚点（子 cell）、连线引脚到引脚（source/target=引脚点 id）、网名
（net name）标注在连线上。输入=ADS 网表文本（.net 形态，与
linkage/templates/ads/*.net 经渲染器/模板族渲染后的实文同语法——本解析器
对渲染实文逐行实测校验，#215 纪律：不凭想象写语法）。

网表语法（出处=adapters/ads_netlist.generate_netlist 与
linkage/ads_template_family 渲染实文，2026-11-01 实测；ADR-0009 铁律：
每条语句独占一行）::

    Options ResourceUsage=yes ...                      # 控制语句
    S_Param:SP1 CalcS=yes ...                          # 控制语句
    SweepPlan: SP1_stim Start=1.6 GHz Stop=3.2 GHz Lin=401
    OutputPlan:SP1_Output Type="Output" ...
    Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes             # 元件行（2 节点，第 2=地）
    TLIN:TLIN1  N_A N_B  Z=50 Ohm E=90 F=2.4 GHz       # 元件行（2 节点）
    SnP:SNP1  N_B N_C N_T1 N_T2 NumPorts=4 File="..."  # 元件行（NumPorts 个节点）
    HB:HB1 Freq[1]=2.4 GHz Order[1]=3 StatusLevel=2    # 控制语句
    aele Pout_W=...; Pout_dBm=...;                     # 控制语句

严格校验（负例显式 ValueError，不静默）：注释（``*`` 头）与空行跳过；
ADS 续行符（行尾 ``\\``）v1 不支持=显式报错（ADR-0009 单行铁律下模板渲染
不产生续行）；``Kind:Name`` 的 Kind 只认元件三族 Port/TLIN/SnP 与控制
Options/S_Param/SweepPlan/OutputPlan/HB/aele——其他行（含未知元件头）显式
报错；逐族节点数/必备参数校验（Port 第 2 节点恒=地 "0" 且 Num 必填、
TLIN 节点=2 且 Z/E/F 必填、SnP NumPorts=节点数且 File 必填）；实例名重复/
同元件节点重复/端口 Num 重复均显式报错。参数值一律**原样字符串**保留
（零换算零数值解析——铁律 7：图上标注=网表原值原样）。

引脚级装配（走 T-O2 通用内核 :mod:`rfauto.core.drawio_xml`，本模块禁止
另写文档级装配器）：

- 元件符号 = mxCell 框（value=``Kind:Name`` + 参数原值串）+ 引脚点**子
  cell**（``parent=<元件 id>``、几何相对父、id 形态 ``<元件>.<引脚号>``，
  引脚号=节点序 1 基；extra_attrs 带 node=<网名>——draw.io 组内引脚原生
  惯例，拖元件引脚跟随）。
- 连线 = 正交 edge，source/target=引脚点 id（引脚到引脚，不指元件主体）；
  两引脚网=直连一条边、edge value=网名（网名标注单点）；三引脚以上网=
  汇接点 vertex（小黑点，value=网名）+ 各引脚→汇接点辐条（每引脚恰一条
  边——引脚连接完整性判据的统一形态）；单引脚网=悬空：不建边、引脚点
  红色虚线样式 + ``dangling="1"`` 属性 + warnings 显式提示（无静默悬空）。
- 地网（节点名 "0"，ADS 全局地）= 每个地引脚一枚 "GND" 符号（子 cell）
  + 引脚→符号短边（不跨元件互连——图形惯例：地以符号表达，不画地干线）。
- 布局 = 信号流向左→右：以 Num 最小端口为根做 BFS 分层（非 Port 元件
  列深=BFS 跳数，环状互连不影响收敛——每元件只访问一次；无 Port 网表
  以首个元件为根，与根不连通孤岛按声明序接续编列）；Port 落其锚元件
  （同网最浅非 Port 元件）邻列，侧别=锚元件该网的引脚侧反侧；同列按
  网表声明序自上而下。v1 诚实边界：正交路由交给 draw.io
  ``orthogonalEdgeStyle;jettySize=auto`` 自动布线，残余交叉靠人工微调
  （产出=原生可编辑文件）。

确定性：同输入两次构建 XML 逐字节相同——cell id 全部确定性命名（元件
id=实例名、引脚 ``<元件>.<引脚号>``、地符号 ``<元件>.<引脚号>.gnd``、
线 ``w<i>``/地桩 ``g<i>``/汇接点 ``j<i>``、标题 "title"；实例名禁保留
命名空间——title 与 ``^[wgj]\\d+$`` 显式拒绝），禁 uuid、零时间戳、
ElementTree 属性序=插入序。

零 IO（纯函数返回 XML 文本与 plan dict；落盘在 service 层）、零第三方
依赖（仅标准库 + 同层 core.drawio_xml）、零物理数值（铁律 7：无公式，
图上数字=网表参数原值原样）。
"""

from __future__ import annotations

import re
from typing import Any

from rfauto.core.drawio_xml import DEFAULT_PAGE_ATTRS, new_document, page_attrs

__all__ = [
    "COL_STEP",
    "COMP_H",
    "COMP_W",
    "CONTROL_KINDS",
    "ELEMENT_KINDS",
    "ROW_STEP",
    "build_schematic_diagram_xml",
    "build_schematic_plan",
    "parse_netlist",
]

# ─── 网表语法常量（渲染实文实测，#215） ─────────────────────────────────────

#: 元件族枚举（templates/ads 渲染实文出现的全部元件头；未知头显式报错）
ELEMENT_KINDS: tuple[str, ...] = ("Port", "TLIN", "SnP")

#: 控制语句头枚举（识别后记录、不入电路拓扑；未知行显式报错）
CONTROL_KINDS: tuple[str, ...] = (
    "Options", "S_Param", "SweepPlan", "OutputPlan", "HB", "aele")

#: 裸 token 单位词表（参数区的裸 token 只允许这些；词表外裸 token 显式报错。
#: 渲染实文出现：Ohm（TLIN/Port Z 单位）、GHz/MHz/kHz/Hz（频率单位）、
#: dBm/W（功率）、deg（电长度）、mil/mm/um/nm（几何）——按渲染实文 +
#: ADS 惯用单位收口，词表外显式报错不静默吞）
_UNIT_TOKENS: frozenset[str] = frozenset({
    "Ohm", "GHz", "MHz", "kHz", "Hz", "dBm", "W", "mW", "deg", "mil",
    "mm", "um", "nm", "V", "A", "sec", "nsec", "usec", "msec"})

#: 实例名形态（元件 id/引脚点 id ``<元件>.<引脚号>`` 依赖实例名不含 ``.``）
_INST_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
#: 生成器保留 id 命名空间（title 标题、w<i>/g<i>/j<i> 边与汇接点 id——
#: 元件 id 占用即 id 冲突，显式拒绝）
_RESERVED_NAME_RE = re.compile(r"(?:[wgj]\d+)")
_RESERVED_NAMES = frozenset({"title"})

_GROUND_NODE = "0"  # ADS 全局地节点名


def _tokenize(line: str, lineno: int) -> list[str]:
    """按空白切 token（双引号段视为一体——File="带 空格 路径" 实测需求）。"""
    tokens: list[str] = []
    cur: list[str] = []
    in_quote = False
    for ch in line:
        if ch == '"':
            in_quote = not in_quote
            cur.append(ch)
        elif ch.isspace() and not in_quote:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if in_quote:
        raise ValueError(
            f"第 {lineno} 行引号不闭合（ADS 网表参数值引号必须成对）: {line!r}")
    if cur:
        tokens.append("".join(cur))
    return tokens


def _split_kv(token: str) -> tuple[str, str]:
    """``Key=Value`` → (Key, Value)（首个 ``=`` 切分；Value 可为空串）。"""
    key, _, val = token.partition("=")
    return key, val


def _parse_int_param(kind: str, name: str, params: dict[str, str],
                     key: str, lineno: int) -> int:
    """参数取整数值（严格：缺失/非整文本显式报错）。"""
    raw = params.get(key)
    if raw is None:
        raise ValueError(f"第 {lineno} 行 {kind}:{name} 缺必备参数 {key}")
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"第 {lineno} 行 {kind}:{name} 参数 {key} 必须是整数值，"
            f"收到 {raw!r}") from exc


# ─── 解析器（纯文本 → 结构；零 IO 零数值换算） ─────────────────────────────


def parse_netlist(text: str) -> dict[str, Any]:
    """ADS 网表文本 → 结构化 dict（严格校验；负例显式 ValueError）。

    Returns::

        {"components": [{name, kind, nodes: [str...], params: {k: v},
                         param_tokens: [原样 token...], line: int}, ...],
         "controls": [{kind, line}, ...],
         "sweep": {"start","stop","npoints","unit"} 原样字符串 | None,
         "n_lines": int}

    校验面（全部显式报错）：未知行 / 未知元件头 / 续行符 / 引号不闭合 /
    缺节点或缺必备参数 / 节点数与族不符（Port 2 节点且第 2=地、TLIN 2 节点、
    SnP NumPorts=节点数）/ 实例名形态与保留命名空间 / 实例名重复 /
    同元件节点重复 / Port Num 重复 / 参数区词表外裸 token / 空网表。
    """
    if not isinstance(text, str):
        raise ValueError(f"netlist 文本必须是 str，收到 {type(text)!r}")
    components: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    sweep: dict[str, str] | None = None
    seen_names: dict[str, int] = {}
    seen_port_nums: set[int] = set()
    lines = text.splitlines()
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("*"):  # 空行/注释（ADS 注释= * 头）
            continue
        if line.endswith("\\"):
            raise ValueError(
                f"第 {lineno} 行以续行符结尾：v1 不支持 ADS 续行"
                "（ADR-0009 铁律=每条语句独占一行）")
        tokens = _tokenize(line, lineno)
        head = tokens[0]
        if head in ("Options", "aele"):
            controls.append({"kind": head, "line": lineno})
            continue
        if ":" in head:
            kind = head.partition(":")[0]
            if kind in CONTROL_KINDS:
                controls.append({"kind": kind, "line": lineno})
                if kind == "SweepPlan" and sweep is None:
                    sweep = _extract_sweep(tokens)
                continue
            if kind in ELEMENT_KINDS:
                comp = _parse_component(kind, head, tokens, lineno)
                name = comp["name"]
                if name in seen_names:
                    raise ValueError(
                        f"第 {lineno} 行元件实例名重复：{name!r}"
                        f"（首次出现于第 {seen_names[name]} 行）")
                seen_names[name] = lineno
                if comp["kind"] == "Port":
                    num = int(comp["params"]["Num"])
                    if num in seen_port_nums:
                        raise ValueError(
                            f"第 {lineno} 行 Port Num={num} 与既有端口重复"
                            "（端口编号必须唯一）")
                    seen_port_nums.add(num)
                components.append(comp)
                continue
        raise ValueError(
            f"第 {lineno} 行无法识别（既非元件行也非控制语句）: {line!r}；"
            f"已知元件头 {list(ELEMENT_KINDS)}、已知控制语句 "
            f"{list(CONTROL_KINDS)}")
    if not components:
        raise ValueError("网表无元件行（Port/TLIN/SnP 至少一条）——空网表不建图")
    return {
        "components": components,
        "controls": controls,
        "sweep": sweep,
        "n_lines": len(lines),
    }


def _extract_sweep(tokens: list[str]) -> dict[str, str]:
    """SweepPlan 行 token → 频扫原值（Start/Stop/Lin raw + 首个单位 token）。"""
    out: dict[str, str] = {}
    for tok in tokens[1:]:
        if "=" in tok:
            key, val = _split_kv(tok)
            if key == "Start":
                out["start"] = val
            elif key == "Stop":
                out["stop"] = val
            elif key == "Lin":
                out["npoints"] = val
        elif tok in _UNIT_TOKENS and "unit" not in out:
            out["unit"] = tok
    return out


def _parse_component(kind: str, head: str, tokens: list[str],
                     lineno: int) -> dict[str, Any]:
    """元件行 → 结构（节点表 + 参数原值；逐族严格校验）。"""
    name = head.partition(":")[2]
    if not _INST_NAME_RE.fullmatch(name):
        raise ValueError(
            f"第 {lineno} 行元件实例名 {name!r} 必须匹配 "
            "[A-Za-z][A-Za-z0-9_]*（引脚点 id 形态 <元件>.<引脚号> 依赖"
            "实例名不含 '.'）")
    if name in _RESERVED_NAMES or _RESERVED_NAME_RE.fullmatch(name):
        raise ValueError(
            f"第 {lineno} 行元件实例名 {name!r} 占用生成器保留 id 命名空间"
            "（title / w<i> / g<i> / j<i>），请改名")
    body = tokens[1:]
    nodes: list[str] = []
    idx = 0
    for tok in body:
        if "=" in tok or tok in _UNIT_TOKENS:
            break
        nodes.append(tok)
        idx += 1
    if not nodes:
        raise ValueError(f"第 {lineno} 行 {head} 缺节点表（节点列表不能为空）")
    params: dict[str, str] = {}
    param_tokens: list[str] = []
    for tok in body[idx:]:
        param_tokens.append(tok)
        if "=" in tok:
            key, val = _split_kv(tok)
            if key in params:
                raise ValueError(
                    f"第 {lineno} 行 {head} 参数 {key} 重复（{params[key]!r}"
                    f" 与 {val!r}）")
            # 值的引号剥离=语法归一（字符串定界符，非数值换算）；
            # param_tokens 保留 token 原文（含引号——标签原值原样）
            if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            params[key] = val
        elif tok not in _UNIT_TOKENS:
            raise ValueError(
                f"第 {lineno} 行 {head} 参数区出现词表外裸 token {tok!r}"
                f"（允许：键值对 Key=Value 或单位词 {sorted(_UNIT_TOKENS)}）")
    if len(set(nodes)) != len(nodes):
        raise ValueError(
            f"第 {lineno} 行 {head} 节点重复（{nodes}）——同一元件两引脚"
            "接同一网为退化短路，显式拒绝")
    if kind == "Port":
        if len(nodes) != 2 or nodes[1] != _GROUND_NODE:
            raise ValueError(
                f"第 {lineno} 行 Port:{name} 必须恰 2 节点且第 2 节点=地 "
                f"'{_GROUND_NODE}'（渲染实文口径），收到 {nodes}")
        _parse_int_param(kind, name, params, "Num", lineno)
        if "Z" not in params:
            raise ValueError(f"第 {lineno} 行 Port:{name} 缺必备参数 Z")
    elif kind == "TLIN":
        if len(nodes) != 2:
            raise ValueError(
                f"第 {lineno} 行 TLIN:{name} 必须恰 2 节点，收到 {nodes}")
        for key in ("Z", "E", "F"):
            if key not in params:
                raise ValueError(
                    f"第 {lineno} 行 TLIN:{name} 缺必备参数 {key}（渲染实文"
                    "口径 Z/E/F 三参）")
    else:  # SnP
        n_ports = _parse_int_param(kind, name, params, "NumPorts", lineno)
        if n_ports != len(nodes):
            raise ValueError(
                f"第 {lineno} 行 SnP:{name} NumPorts={n_ports} 与节点数 "
                f"{len(nodes)} 不符（节点恰 NumPorts 个、不含地——ADR-0009）")
        if "File" not in params:
            raise ValueError(f"第 {lineno} 行 SnP:{name} 缺必备参数 File")
    return {
        "name": name, "kind": kind, "nodes": nodes, "params": params,
        "param_tokens": param_tokens, "line": lineno,
    }


# ─── 网/引脚结构推导 ────────────────────────────────────────────────────────


def _derive_nets(
    components: list[dict[str, Any]],
) -> dict[str, list[tuple[str, int]]]:
    """网名 → 引脚表 [(元件名, 引脚号 1 基)...]（声明序；地网 "0" 同表）。"""
    nets: dict[str, list[tuple[str, int]]] = {}
    for comp in components:
        for i, node in enumerate(comp["nodes"], 1):
            nets.setdefault(node, []).append((comp["name"], i))
    return nets


# ─── 布局（信号流向左→右；确定性） ──────────────────────────────────────────

COMP_W = 150
COMP_H = 64
COL_STEP = 230
ROW_STEP = 150
ROW_Y0 = 100
MARGIN_X = 40
TITLE_Y = 20
TITLE_W = 520
TITLE_H = 26
PORT_SIZE = 10
_PIN_Y_FIRST = 10
_PIN_X_LEFT = -PORT_SIZE // 2
_PIN_X_RIGHT = COMP_W - PORT_SIZE // 2
_GND_Y = COMP_H + 14
_GND_W = 44
_GND_H = 18

_DEFAULT_TITLE = "引脚级原理图（ADS 网表；引脚到引脚连线，网名=原值标注）"

#: kind → (fillColor, strokeColor)（drawio 经典色板；Port 绿/TLIN 黄/SnP 蓝）
_KIND_COLOR: dict[str, tuple[str, str]] = {
    "Port": ("#d5e8d4", "#82b366"),
    "TLIN": ("#fff2cc", "#d6b656"),
    "SnP": ("#dae8fc", "#6c8ebf"),
}

_TITLE_STYLE = ("text;html=1;strokeColor=none;fillColor=none;align=left;"
                "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1")
_PIN_STYLE = "ellipse;fillColor=#ffffff;strokeColor=#333333;html=1;fontSize=8;"
_PIN_DANGLING_STYLE = ("ellipse;fillColor=#f8cecc;strokeColor=#b85450;"
                       "dashed=1;html=1;fontSize=8;")
_WIRE_STYLE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
               "jettySize=auto;html=1;fontSize=10;")
_GND_EDGE_STYLE = ("edgeStyle=orthogonalEdgeStyle;rounded=0;endArrow=none;"
                   "strokeColor=#666666;html=1;")
_GND_LABEL_STYLE = ("text;html=1;fontColor=#666666;align=center;"
                    "verticalAlign=middle;whiteSpace=wrap;rounded=0;"
                    "fontSize=9;")
_JUNCTION_STYLE = ("ellipse;fillColor=#333333;strokeColor=#333333;html=1;"
                   "fontColor=#ffffff;fontSize=9;")


def _comp_style(kind: str) -> str:
    fill, stroke = _KIND_COLOR[kind]
    return (f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};"
            f"strokeColor={stroke};fontSize=11;")


def _edge_ys(n: int) -> list[int]:
    """单缘 n 个引脚点的 y 序列（px，相对父顶；首/末各留缘距均布）。"""
    if n <= 1:
        return [(COMP_H - PORT_SIZE) // 2]
    first = _PIN_Y_FIRST
    last = COMP_H - _PIN_Y_FIRST - PORT_SIZE
    return [first + round(i * (last - first) / (n - 1)) for i in range(n)]


def _coord(v: float) -> int:
    out = float(v)
    if not out.is_integer():
        raise AssertionError(f"布局坐标出现非整值 {v!r}（内部错误）")
    return int(out)


def _assign_layers(
    components: list[dict[str, Any]],
    nets: dict[str, list[tuple[str, int]]],
) -> tuple[dict[str, int], list[str]]:
    """非 Port 元件 BFS 分层（信号流向左→右的列深度；Port=信号端点不入层）。

    根 = Num 最小的 Port（唯一——解析器钉 Port Num 唯一；并列按声明序兜底）；
    无 Port 网表以首个元件为根。非 Port 元件深度 = 与根相邻元件集的 BFS
    跳数（经共享网逐跳；多父取先发现者——邻接遍历按声明序，确定性）。
    与根不连通的孤岛（无 Port 岛）：按声明序取岛首元件，深度=当前最大
    深度+1 接续编列。BFS 恒收敛（环状互连不影响——每元件只访问一次）。

    返回 (元件名 → 列深度, warnings)。
    """
    warnings: list[str] = []
    kind_of = {c["name"]: c["kind"] for c in components}
    decl = {c["name"]: i for i, c in enumerate(components)}
    # 网 → 同网非 Port 元件（声明序）；地网不入层
    net_peers: dict[str, dict[str, list[str]]] = {}
    for net, pins in nets.items():
        if net == _GROUND_NODE:
            continue
        members = [c for c, _pin in pins if kind_of[c] != "Port"]
        for c in members:
            net_peers.setdefault(net, {})[c] = [m for m in members if m != c]

    ports = [c for c in components if c["kind"] == "Port"]
    root_comp: str | None = None
    if ports:
        root_port = min(
            ports,
            key=lambda p: (int(p["params"]["Num"]), decl[p["name"]]))
        root_comp = root_port["name"]
    elif components:
        root_comp = components[0]["name"]

    depth: dict[str, int] = {}
    frontier: list[str] = []
    if root_comp is not None:
        if kind_of[root_comp] == "Port":
            # 根 Port 的非地网上的非 Port 元件 = 深度 0 起点（声明序）
            frontier = sorted({
                c for net, pins in nets.items()
                if net != _GROUND_NODE
                for c, _pin in pins
                if any(cn == root_comp for cn, _p2 in pins)
                and kind_of[c] != "Port"
            }, key=lambda n: decl[n])
        else:
            frontier = [root_comp]
        for c in frontier:
            depth[c] = 0
    # BFS 逐层扩展
    layer = 0
    while frontier:
        nxt: list[str] = []
        for c in frontier:
            for _net, peers in net_peers.items():
                if c not in peers:
                    continue
                for m in peers[c]:
                    if m not in depth:
                        depth[m] = layer + 1
                        nxt.append(m)
        frontier = nxt
        layer += 1
    # 孤岛接续编列（声明序取岛首，深度=当前最大+1）
    unvisited = [c["name"] for c in components
                 if c["kind"] != "Port" and c["name"] not in depth]
    while unvisited:
        base = (max(depth.values()) + 1) if depth else 0
        seed = unvisited[0]
        depth[seed] = base
        unvisited = [u for u in unvisited if u != seed]
        frontier = [seed]
        layer = base
        while frontier:
            nxt = []
            for c in frontier:
                for _net, peers in net_peers.items():
                    if c not in peers:
                        continue
                    for m in peers[c]:
                        if m not in depth:
                            depth[m] = layer + 1
                            nxt.append(m)
                            if m in unvisited:
                                unvisited.remove(m)
            frontier = nxt
            layer += 1
    return depth, warnings


def _pin_sides(
    components: list[dict[str, Any]],
    nets: dict[str, list[tuple[str, int]]],
    depth: dict[str, int],
) -> dict[tuple[str, str], str]:
    """每个 (元件, 网) 的引脚缘侧（"left"/"right"；地网不在表——恒落盒底缘）。

    两遍规则（确定性）：
    - 非 Port 元件：同网有其他非 Port 元件 → 对方最浅深度 < 本元件深度 =
      left、否则（含同深并列）= right；port-only 网（同网无非 Port 元件）=
      本元件其余网多数侧的反侧（并列多数取 right；元件全部为 port-only 网 →
      全部落 left——端口列于符号左侧馈入）。
    - Port 元件（第二遍，依赖锚元件已定侧）：有非 Port 同网锚 → 侧=锚侧
      反侧（Port 落锚邻列、引脚面朝锚）；无锚（port-port 直连网）→ 网上
      首个声明 Port 取 right、其余 left（直连线水平对拉）。
    """
    kind_of = {c["name"]: c["kind"] for c in components}
    decl = {c["name"]: i for i, c in enumerate(components)}
    side: dict[tuple[str, str], str] = {}
    portonly: dict[str, list[str]] = {}
    for comp in components:  # 第一遍：非 Port 元件
        if comp["kind"] == "Port":
            continue
        name = comp["name"]
        for net in comp["nodes"]:
            if net == _GROUND_NODE:
                continue
            peers = [c for c, _pin in nets[net]
                     if c != name and kind_of[c] != "Port"]
            if peers:
                side[(name, net)] = (
                    "left" if min(depth[p] for p in peers) < depth[name]
                    else "right")
            else:
                portonly.setdefault(name, []).append(net)
    for name, pnets in portonly.items():
        resolved = [s for (n, _net), s in side.items() if n == name]
        n_left = resolved.count("left")
        n_right = resolved.count("right")
        if n_left or n_right:
            ref = "right" if n_right >= n_left else "left"
            pside = "left" if ref == "right" else "right"
        else:
            pside = "left"  # 全 port-only（如直通 SnP）：端口列符号左侧
        for net in pnets:
            side[(name, net)] = pside
    for comp in components:  # 第二遍：Port 元件
        if comp["kind"] != "Port":
            continue
        name = comp["name"]
        for net in comp["nodes"]:
            if net == _GROUND_NODE:
                continue
            peers = [c for c, _pin in nets[net]
                     if c != name and kind_of[c] != "Port"]
            if peers:
                a = min(peers, key=lambda p: (depth[p], decl[p]))
                side[(name, net)] = (
                    "left" if side[(a, net)] == "right" else "right")
            else:
                ports_on_net = [c for c, _pin in nets[net]]
                side[(name, net)] = (
                    "right" if ports_on_net and ports_on_net[0] == name
                    else "left")
    return side


def _layout(
    components: list[dict[str, Any]],
    nets: dict[str, list[tuple[str, int]]],
) -> tuple[dict[str, tuple[int, int]], list[str]]:
    """元件 → (列, 行)（整数；列=信号流向序、行=同列自上而下序）。

    非 Port 元件列=分层深度；Port 列=锚元件（同网最浅非 Port 元件，并列
    取声明序首位）邻列——侧别 left → 锚列-1、right → 锚列+1；无锚 Port
    （port-port 直连或全悬空）列 0。列整体平移使最小列=0；同列按声明序
    定行。
    """
    warnings: list[str] = []
    depth, w1 = _assign_layers(components, nets)
    warnings.extend(w1)
    side = _pin_sides(components, nets, depth)
    kind_of = {c["name"]: c["kind"] for c in components}
    decl = {c["name"]: i for i, c in enumerate(components)}
    col: dict[str, int] = {}
    for comp in components:
        name = comp["name"]
        if kind_of[name] != "Port":
            col[name] = depth[name]
            continue
        anchor: tuple[int, int, int] | None = None  # (锚列, 锚声明序, 侧)
        for net in comp["nodes"]:
            if net == _GROUND_NODE:
                continue
            peers = [c for c, _pin in nets[net]
                     if c != name and kind_of[c] != "Port"]
            if not peers:
                continue
            a = min(peers, key=lambda p: (depth[p], decl[p]))
            anchor = (depth[a], decl[a], 1 if side[(a, net)] == "right" else -1)
            break
        if anchor is None:
            col[name] = 0
        else:
            col[name] = anchor[0] + anchor[2]
    min_col = min(col.values())
    col = {n: c - min_col for n, c in col.items()}
    by_col: dict[int, list[str]] = {}
    for name in sorted(col, key=lambda n: decl[n]):
        by_col.setdefault(col[name], []).append(name)
    pos: dict[str, tuple[int, int]] = {}
    for c, names in by_col.items():
        for j, name in enumerate(names):
            pos[name] = (c, j)
    return pos, warnings


# ─── 装配计划（XML 走 T-O2 内核 + 信封回显面） ─────────────────────────────


def _param_label(comp: dict[str, Any]) -> str:
    """元件参数标签串（原样 token 拼接；SnP 的 File= 只入属性不进标签）。"""
    toks = [t for t in comp["param_tokens"]
            if not (comp["kind"] == "SnP" and t.startswith("File="))]
    return " ".join(toks)


def build_schematic_plan(text: str, *, title: str | None = None) -> dict[str, Any]:
    """网表文本 → 装配计划（XML 文本 + 信封回显面；service 与内核测试同源）。

    Returns::

        {"xml": str（未压缩原生 mxfile，逐字节确定性）,
         "title": str,
         "n_components": int, "n_ports": int, "n_elements": int,
         "n_nets_signal": int, "n_ground_pins": int,
         "n_wires": int, "n_ground_stubs": int, "n_dangling": int,
         "dangling": ["<元件>.<引脚号>", ...],
         "components": [{name, kind, nodes, column, row}, ...],
         "nets": [{name, n_pins, pins: ["<元件>.<引脚号>", ...], kind},
                  ...],   # kind ∈ wire/junction/ground/dangling
         "n_controls": int, "sweep": dict | None,
         "warnings": [str, ...]}

    Raises:
        ValueError: 网表校验负例（见 :func:`parse_netlist`）。
    """
    parsed = parse_netlist(text)
    components = parsed["components"]
    nets = _derive_nets(components)
    kind_of = {c["name"]: c["kind"] for c in components}
    pos, warnings = _layout(components, nets)

    # 引脚缘侧 → 引脚点几何（子 cell 相对父坐标）
    side = _pin_sides(components, nets, {
        n: c for n, (c, _r) in pos.items() if kind_of[n] != "Port"})
    # 注：side 只依赖相对深度序——用列号做深度等价量（平移后仍保序）
    pin_xy: dict[tuple[str, int], tuple[int, int]] = {}
    left_seq: dict[str, list[int]] = {}
    right_seq: dict[str, list[int]] = {}
    for comp in components:
        name = comp["name"]
        for i, net in enumerate(comp["nodes"], 1):
            if net == _GROUND_NODE:
                continue
            s = side.get((name, net), "right")
            (left_seq if s == "left" else right_seq).setdefault(
                name, []).append(i)
    for name, seq in left_seq.items():
        for k, i in enumerate(seq):
            pin_xy[(name, i)] = (_PIN_X_LEFT, _edge_ys(len(seq))[k])
    for name, seq in right_seq.items():
        for k, i in enumerate(seq):
            pin_xy[(name, i)] = (_PIN_X_RIGHT, _edge_ys(len(seq))[k])

    # 悬空网（单引脚非地网）显式标记
    dangling: list[str] = []
    for net, pins in nets.items():
        if net == _GROUND_NODE or len(pins) != 1:
            continue
        cname, pidx = pins[0]
        dangling.append(f"{cname}.{pidx}")
        warnings.append(
            f"引脚 {cname}.{pidx}（网络 {net!r}）无对端连接——悬空显式标记")

    # 页面尺寸按内容自适应
    max_col = max(c for c, _r in pos.values())
    max_row = max(r for _c, r in pos.values())
    page_w = max(int(DEFAULT_PAGE_ATTRS["pageWidth"]),
                 MARGIN_X + (max_col + 1) * COL_STEP + COMP_W + MARGIN_X)
    page_h = max(int(DEFAULT_PAGE_ATTRS["pageHeight"]),
                 ROW_Y0 + (max_row + 1) * ROW_STEP + _GND_Y + _GND_H + 40)

    doc = new_document(diagram_id="schematic-diagram", diagram_name="Schematic",
                       page=page_attrs(pageWidth=str(page_w),
                                       pageHeight=str(page_h)))
    title_text = title or _DEFAULT_TITLE
    doc.add_vertex("title", title_text, style=_TITLE_STYLE,
                   x=MARGIN_X, y=TITLE_Y, width=TITLE_W, height=TITLE_H)

    # 元件符号 + 引脚点 + 地符号
    for comp in components:
        name = comp["name"]
        cx, cy = pos[name]
        x = MARGIN_X + cx * COL_STEP
        y = ROW_Y0 + cy * ROW_STEP
        label = f"{comp['kind']}:{name}"
        plabel = _param_label(comp)
        if plabel:
            label += f"\n{plabel}"
        extra: dict[str, Any] = {"kind": comp["kind"],
                                 "nodes": "|".join(comp["nodes"])}
        if comp["kind"] == "SnP":
            extra["file"] = comp["params"].get("File", "")
        if comp["kind"] == "Port":
            extra["num"] = comp["params"].get("Num", "")
        doc.add_vertex(name, label, style=_comp_style(comp["kind"]),
                       x=_coord(x), y=_coord(y), width=COMP_W, height=COMP_H,
                       extra_attrs=extra)
        for i, net in enumerate(comp["nodes"], 1):
            pin_id = f"{name}.{i}"
            if net == _GROUND_NODE:
                # 地引脚点=盒底缘中点（半出盒）；GND 符号随其正下方
                px, py = (COMP_W - PORT_SIZE) // 2, COMP_H - PORT_SIZE // 2
                doc.add_vertex(pin_id, str(i), style=_PIN_STYLE,
                               x=px, y=py, width=PORT_SIZE, height=PORT_SIZE,
                               parent=name, extra_attrs={"node": net})
                continue
            is_dangling = f"{name}.{i}" in dangling
            px, py = pin_xy.get((name, i), (_PIN_X_RIGHT,
                                            (COMP_H - PORT_SIZE) // 2))
            pin_attrs: dict[str, Any] = {"node": net}
            if is_dangling:
                pin_attrs["dangling"] = "1"  # 悬空显式标记（无静默悬空）
            doc.add_vertex(pin_id, str(i),
                           style=_PIN_DANGLING_STYLE if is_dangling
                           else _PIN_STYLE,
                           x=px, y=py, width=PORT_SIZE, height=PORT_SIZE,
                           parent=name, extra_attrs=pin_attrs)

    # 连线：两引脚网直连 / 多引脚网汇接点辐条 / 地桩边
    n_wires = 0
    wire_index = 0
    gnd_index = 0
    junc_index = 0
    net_rows: list[dict[str, Any]] = []
    for net, pins in nets.items():
        pin_ids = [f"{c}.{i}" for c, i in pins]
        if net == _GROUND_NODE:
            for cname, pidx in pins:
                pin_id = f"{cname}.{pidx}"
                gnd_id = f"{pin_id}.gnd"
                doc.add_vertex(
                    gnd_id, "GND", style=_GND_LABEL_STYLE,
                    x=(COMP_W - _GND_W) // 2, y=_GND_Y,
                    width=_GND_W, height=_GND_H, parent=cname)
                doc.add_edge(f"g{gnd_index}", "", style=_GND_EDGE_STYLE,
                             source=pin_id, target=gnd_id)
                gnd_index += 1
            net_rows.append({"name": net, "n_pins": len(pins),
                             "pins": pin_ids, "kind": "ground"})
            continue
        if len(pins) == 1:
            net_rows.append({"name": net, "n_pins": 1, "pins": pin_ids,
                             "kind": "dangling"})
            continue
        if len(pins) == 2:
            doc.add_edge(f"w{wire_index}", net, style=_WIRE_STYLE,
                         source=pin_ids[0], target=pin_ids[1])
            wire_index += 1
            n_wires += 1
            net_rows.append({"name": net, "n_pins": 2, "pins": pin_ids,
                             "kind": "wire"})
            continue
        # ≥3 引脚网：汇接点（小黑点，value=网名）+ 每引脚恰一条辐条
        anchor_cols = [pos[c][0] for c, _i in pins]
        jx = MARGIN_X + (max(anchor_cols) + 1) * COL_STEP + COL_STEP // 2
        anchor_rows = [pos[c][1] for c, _i in pins]
        jy = ROW_Y0 + max(anchor_rows) * ROW_STEP + COMP_H + 40
        junc_id = f"j{junc_index}"
        junc_index += 1
        doc.add_vertex(junc_id, net, style=_JUNCTION_STYLE,
                       x=_coord(jx), y=_coord(jy), width=PORT_SIZE,
                       height=PORT_SIZE)
        for pin_id in pin_ids:
            doc.add_edge(f"w{wire_index}", "", style=_WIRE_STYLE,
                         source=pin_id, target=junc_id)
            wire_index += 1
            n_wires += 1
        net_rows.append({"name": net, "n_pins": len(pins), "pins": pin_ids,
                         "kind": "junction"})

    comp_rows = [{
        "name": c["name"], "kind": c["kind"], "nodes": list(c["nodes"]),
        "column": pos[c["name"]][0], "row": pos[c["name"]][1],
    } for c in components]

    return {
        "xml": doc.to_xml(),
        "title": title_text,
        "n_components": len(components),
        "n_ports": sum(1 for c in components if c["kind"] == "Port"),
        "n_elements": sum(1 for c in components if c["kind"] != "Port"),
        "n_nets_signal": sum(1 for n in nets if n != _GROUND_NODE),
        "n_ground_pins": len(nets.get(_GROUND_NODE, [])),
        "n_wires": n_wires,
        "n_ground_stubs": gnd_index,
        "n_dangling": len(dangling),
        "dangling": dangling,
        "components": comp_rows,
        "nets": net_rows,
        "n_controls": len(parsed["controls"]),
        "sweep": parsed["sweep"],
        "warnings": warnings,
    }


def build_schematic_diagram_xml(text: str, *, title: str | None = None) -> str:
    """网表文本 → 完整 .drawio XML 文本（未压缩原生 mxfile，逐字节确定性）。

    Args:
        text: ADS 网表文本（渲染实文语法，见 :func:`parse_netlist`）。
        title: 图标题文本（None 用缺省标题）。

    Raises:
        ValueError: 网表校验负例（显式报错，不静默）。
    """
    return build_schematic_plan(text, title=title)["xml"]
