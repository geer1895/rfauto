"""SPICE 网表深度解析器（ngspice/HSPICE/Spectre 三格式统一结构化输出）。

Q-X33（aurora_q T-Q22）席面：rfauto 既有 SPICE 基础面
（core.macromodel.validate_spice_subcircuit=skrf 导出子电路的**结构校验**，
replay MNA=回放求解）之外，补**三格式统一深度解析**——把一份网表解析为
五维度统一 JSON 结构化输出 keys ``{elements, subckts, controls, models,
topology}``：

- ``elements``：元件实例（R/L/C/D/M/Q/J/E/F/G/H/K/X/V/I/T/O/S/W/B + 端口
  节点 + 参数值 + 单位提取；SPICE 数值后缀缩放 T/G/K/M/U/N/P/F 与
  MEG/MIL 同 core.macromodel 口径）；
- ``subckts``：``.subckt``/``.ends`` 定义 + 嵌套层次树（X 实例引用 →
  父子调用边，``hierarchy`` 字段；子电路体内元素归属 ``scope``）；非
  ``.ends`` 形态的方言终止符（``.endl``=Eldo、``.endfl``/``.endt``/
  ``ends``=任务书与 Spectre 口径）一律收编并记 warning 如实；
- ``controls``：``.op``/``.tran``/``.ac``/``.dc``/``.sp``/``.noise``/
  ``.four`` + 参数扫描步进（``.dc`` 内建扫描语义、``sweep`` 内联与
  ``.step`` 卡，Spectre ``sweep`` 分析块同口径归一 ``sweep`` 字段）；
- ``models``：``.model`` 行（与 Spectre ``model`` 语句）→ name/type/
  level/params dict；
- ``topology``：MNA 稀疏矩阵维度（非地节点数 + V/E/H 分支电流增广数——
  与 core.macromodel._REPLAY_BRANCH_KINDS 同口径）+ 节点连接双向图
  （node→[elements] 与 element→[nodes]）+ 孤立节点检测（顶层单连接节点，
  浮空嫌疑如实警示）+ 接地节点归一（``0``/``gnd``/``gnd!`` 大小写不敏感
  → ``0``）。拓扑在**顶层网表**上计算（子电路体=模板不展平——展平需
  参数代入超出解析器职责，``scope_note`` 如实声明；X 实例引脚按顶层
  网络计数）。

flavor 差异归一（统一 JSON 输出的前提）：
- 注释：ngspice=``*`` 整行 + ``$`` 行内；HSPICE=``*`` 整行 + ``$``/``;``
  行内；Spectre=``//`` 整行 + ``*`` 整行（old-style）+ ``/* */`` 块；
- 元件形态：SPICE 两方言=首字母前缀（``R1 n1 n2 1k``）；Spectre=命名块
  （``Rmain (n1 n2) resistor r=1k``），master 名映射回统一 kind；
- 控制语句：SPICE=点卡（``.tran 1n 100n``）；Spectre=命名分析块
  （``tran1 tran stop=1u``），归一 ``name``=分析类型、``params`` dict；
- 子电路：``.subckt n1 n2`` 与 ``.subckt name (n1 n2)`` 括号 pin 形态
  （HSPICE）与 Spectre ``subckt name (pins)`` 同口径收编。

分层：core 纯函数（零外部依赖——本模块禁 import numpy/skrf/仓内其他
core 面；SPICE 数值后缀表为格式常数非物理数值，铁律 7 不涉）；服务包装
在 service/spice_netlist_service.py（文件 IO + 信封），CLI 叶
``rfauto spice parse`` 为薄壳（规则 4）。

解析尽力而为（fail-soft）：结构错误（令牌不足/终止符不配对/未知首字母）
进 ``structural_errors`` 不中断——诊断面与 validate_spice_subcircuit
同族风格；解析**不仿真**（零求解零器件方程）；表达式 ``{...}``/``'...'``
参数引用保留原文不代入（``value_raw`` 记录）。

AX-6 结构化 tier 诊断（aurora_r R-02 席位；:mod:`rfauto.core.
parser_diagnostics` 四层判据单源）：每个跳行/降级事件同笔落 ``diagnostics``
新增键——``{tier, parser, reason, line, snippet}``（snippet=消费语句原文，
#331 不美化）。定档口径：缺名/缺引用/无法归类=unparsed；未知元件首字母/
方言混排段/嵌套 subckt 与方言终止符收编=unsupported-tier1；X 引用外部
未定义子电路（结构已登记、展开语义未实现）=unsupported-tier2；令牌不足
但条目已降级登记/master 表未命中兜底归档/EOF 强制收口=unsupported-tier3。
既有 ``warnings``/``structural_errors`` 文案逐字节零变化（纯附加键）。
"""

from __future__ import annotations

import re

from rfauto.core.parser_diagnostics import (
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
    TIER_UNSUPPORTED_3,
    make_parse_diagnostic,
)

__all__ = [
    "FLAVOR_AUTO",
    "FLAVOR_HSPICE",
    "FLAVOR_NGSPICE",
    "FLAVOR_SPECTRE",
    "GROUND_ALIASES",
    "PARSER_SCHEMA_VERSION",
    "SPICE_LETTER_KINDS",
    "detect_flavor",
    "normalize_flavor",
    "parse_spice_netlist_text",
    "parse_spice_number",
]

#: 解析输出 schema 版本（五维度键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

FLAVOR_AUTO = "auto"
FLAVOR_NGSPICE = "ngspice"
FLAVOR_HSPICE = "hspice"
FLAVOR_SPECTRE = "spectre"
#: flavor 词表（normalize_flavor 单源）。
_KNOWN_FLAVORS = (FLAVOR_AUTO, FLAVOR_NGSPICE, FLAVOR_HSPICE, FLAVOR_SPECTRE)

#: 接地节点归一词表（大小写不敏感，含 HSPICE ``gnd!`` 全局地形态）。
GROUND_ALIASES = frozenset({"0", "gnd", "gnd!"})

#: SPICE 数值后缀缩放（先双字母 meg/mil 再单字母；同 core.macromodel
#: _REPLAY_SCALE_FACTORS 口径——格式常数，非物理数值）。
_SPICE_SCALE: tuple[tuple[str, float], ...] = (
    ("meg", 1e6),
    ("mil", 25.4e-6),
    ("t", 1e12),
    ("g", 1e9),
    ("k", 1e3),
    ("m", 1e-3),
    ("u", 1e-6),
    ("n", 1e-9),
    ("p", 1e-12),
    ("f", 1e-15),
)
_NUMBER_RE = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z]*)$")
_PARAM_RE = re.compile(r"^([A-Za-z_][\w.$']*?)\s*=\s*(.+)$")

#: 元件首字母 → 统一 kind 元数据：
#: desc=人读描述 / unit=主参数单位（None=无量纲或非单一主参数）/
#: n_nodes=确定性节点/控制令牌数（None=变体，逐类判）/
#: model=节点后是否跟模型名 / branch=True 该类元件在 MNA 中增广分支电流。
_KIND_META: dict[str, dict] = {
    "R": {"desc": "resistor", "unit": "ohm", "n_nodes": 2, "model": False, "branch": False},
    "C": {"desc": "capacitor", "unit": "farad", "n_nodes": 2, "model": False, "branch": False},
    "L": {"desc": "inductor", "unit": "henry", "n_nodes": 2, "model": False, "branch": False},
    "V": {"desc": "vsource", "unit": "volt", "n_nodes": 2, "model": False, "branch": True},
    "I": {"desc": "isource", "unit": "ampere", "n_nodes": 2, "model": False, "branch": False},
    "D": {"desc": "diode", "unit": None, "n_nodes": 2, "model": True, "branch": False},
    "M": {"desc": "mosfet", "unit": None, "n_nodes": 4, "model": True, "branch": False},
    "Q": {"desc": "bjt", "unit": None, "n_nodes": None, "model": True, "branch": False},
    "J": {"desc": "jfet", "unit": None, "n_nodes": 3, "model": True, "branch": False},
    "Z": {"desc": "mesfet", "unit": None, "n_nodes": 3, "model": True, "branch": False},
    "E": {"desc": "vcvs", "unit": None, "n_nodes": 4, "model": False, "branch": True},
    "F": {"desc": "cccs", "unit": None, "n_nodes": None, "model": False, "branch": False},
    "G": {"desc": "vccs", "unit": None, "n_nodes": 4, "model": False, "branch": False},
    "H": {"desc": "ccvs", "unit": None, "n_nodes": None, "model": False, "branch": True},
    "K": {"desc": "mutual_inductance", "unit": None, "n_nodes": 0, "model": False, "branch": False},
    "X": {"desc": "subckt_instance", "unit": None, "n_nodes": None, "model": False, "branch": False},
    "T": {"desc": "transmission_line", "unit": None, "n_nodes": 4, "model": False, "branch": False},
    "O": {"desc": "lossy_line", "unit": None, "n_nodes": 4, "model": False, "branch": False},
    "S": {"desc": "vswitch", "unit": None, "n_nodes": 4, "model": False, "branch": False},
    "W": {"desc": "cswitch", "unit": None, "n_nodes": None, "model": False, "branch": False},
    "U": {"desc": "rc_line", "unit": None, "n_nodes": 3, "model": True, "branch": False},
    "Y": {"desc": "single_lossy_line", "unit": None, "n_nodes": 4, "model": True, "branch": False},
    "N": {"desc": "special_device", "unit": None, "n_nodes": 2, "model": False, "branch": False},
    "B": {"desc": "behavioral_source", "unit": None, "n_nodes": 2, "model": False, "branch": False},
    "A": {"desc": "xspice_block", "unit": None, "n_nodes": 2, "model": False, "branch": False},
    "P": {"desc": "coaxial_tline", "unit": None, "n_nodes": 2, "model": False, "branch": False},
}
#: 统一 kind 首字母词表（未知首字母判定与 Spectre master 兜底映射单源）。
SPICE_LETTER_KINDS = frozenset(_KIND_META)

#: Spectre master 名 → 统一 kind（大小写不敏感；未命中→model 保留原名+warning）。
_SPECTRE_MASTER_KIND: dict[str, str] = {
    "resistor": "R", "res": "R", "capacitor": "C", "cap": "C",
    "inductor": "L", "ind": "L",
    "vsource": "V", "isource": "I", "diode": "D",
    "nmos": "M", "pmos": "M", "npn": "Q", "pnp": "Q",
    "njf": "J", "pjf": "J", "vcvs": "E", "cccs": "F", "vccs": "G",
    "ccvs": "H", "switch": "S",
}
#: Spectre 分析类型词表（控制语句归一口径）。
_SPECTRE_ANALYSES = frozenset({
    "tran", "ac", "dc", "sp", "noise", "pss", "hb", "pac", "pnoise",
    "pxf", "qpss", "sweep", "stb", "xf",
})
#: SPICE 分析点卡词表（``sweep`` 内联/``.step`` 步进见 _parse_sweep）。
#: SPICE 源规格关键字（位置形态 ``V1 n1 n2 DC 5`` 的 spec 段捕获单源）。
_SOURCE_SPECS = frozenset({
    "dc", "ac", "tran", "pulse", "sin", "exp", "pwl", "sffm", "am",
    "noise", "distofreq",
})

# --------------------------------------------------------------------------- #
# 基础词法
# --------------------------------------------------------------------------- #


def normalize_flavor(flavor: str) -> str:
    """flavor 词表校验/归一（小写去空白）；非法显式 ValueError。"""
    f = str(flavor).strip().lower()
    if f not in _KNOWN_FLAVORS:
        raise ValueError(
            f"flavor={flavor!r} 不在词表 {list(_KNOWN_FLAVORS)}"
            "（ngspice/hspice/spectre/auto）"
        )
    return f


def parse_spice_number(token: str) -> float | None:
    """SPICE 数值令牌 → 缩放后 float（``1k``=1000、``2meg``=2e6、``1u``=1e-6）。

    非数值（参数引用/表达式/普通单词）返回 None——调用方区分"数值缺失"
    与 0.0（0.0 是合法值，缺失哨兵恒用 None；#117/#364-④ 同族纪律）。
    纯字母尾巴（单位词 ohm/Hz 等）按 SPICE 惯例忽略取纯数前缀。
    """
    m = _NUMBER_RE.match(token.strip())
    if not m:
        return None
    body, suffix = m.group(1), m.group(2)
    try:
        value = float(body)
    except ValueError:
        return None
    if not suffix:
        return value
    low = suffix.lower()
    for name, factor in _SPICE_SCALE:
        if low == name:
            return value * factor
    if low.isalpha():
        return value
    return None


def _normalize_ground(node: str) -> str:
    """接地节点归一（GROUND_ALIASES 大小写不敏感 → ``0``）。"""
    if node.strip().lower() in GROUND_ALIASES:
        return "0"
    return node


def _strip_inline_comment(line: str, flavor: str) -> str:
    """行内注释剥离（flavor 感知；引号内不剥——Spectre/表达式字符串）。"""
    in_quote = False
    quote_ch = ""
    for i, ch in enumerate(line):
        if ch in ("'", '"'):
            if in_quote and ch == quote_ch:
                in_quote = False
            elif not in_quote:
                in_quote = True
                quote_ch = ch
        if in_quote:
            continue
        if ch == "$":
            return line[:i]
        if flavor == FLAVOR_HSPICE and ch == ";":
            return line[:i]
        if flavor == FLAVOR_SPECTRE and line[i:i + 2] == "//":
            return line[:i]
    return line


def _preprocess(text: str, flavor: str) -> list[tuple[int, str]]:
    """原始文本 → 结构化逻辑语句行 ``[(line_no, text), ...]``（注释剥离 +
    续行拼接）。行号=语句首行（续行并入首行语句）。

    SPICE 两方言：首列 ``*`` 整行注释、``+`` 续行（并入上一条逻辑行）；
    Spectre：``//``/``*`` 整行注释、``/* */`` 块注释（非嵌套折叠）、
    行尾 ``\\`` 续行。
    """
    logical: list[tuple[int, str]] = []
    if flavor == FLAVOR_SPECTRE:
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    buf = ""
    buf_lineno = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\r\n").strip()
        if flavor == FLAVOR_SPECTRE:
            if line.startswith("//") or line.startswith("*"):
                continue
            if buf:
                line = (buf + " " + line).strip()
            else:
                buf_lineno = lineno
            if line.endswith("\\"):
                buf = line[:-1].rstrip()
                continue
            buf = ""
            if line:
                logical.append((buf_lineno or lineno, line))
            continue
        # SPICE 两方言
        if line.startswith("*"):
            continue
        body = _strip_inline_comment(line, flavor).strip()
        if not body:
            continue
        if body.startswith("+") and logical:
            cont = body[1:].strip()
            if cont:
                prev_no, prev = logical[-1]
                logical[-1] = (prev_no, (prev + " " + cont).strip())
            continue
        logical.append((lineno, body))
    return logical


def detect_flavor(text: str) -> str:
    """按内容启发式判定 flavor（``auto`` 的单源；返回三格式之一）。

    判定序（确定性，先显式后统计，平票回落 ngspice）：
    1. ``simulator lang=spectre`` 显式标记 → spectre；
    2. Spectre 信号占优（``//`` 注释行、命名块语句形态 ``name (nodes)
       master``）→ spectre；
    3. ngspice 信号（``.control``/``.endc``/``.four``）≥ HSPICE → ngspice；
    4. HSPICE 信号（行内 ``;`` 注释、``.alter``/``.data``/``.probe``）→
       hspice；
    5. 零信号 → ngspice（事实标准缺省；调用方可显式覆盖）。
    """
    if re.search(r"(?im)^\s*simulator\s+lang\s*=\s*spectre\b", text):
        return FLAVOR_SPECTRE
    spectre_score = 0
    ngspice_score = 0
    hspice_score = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("//"):
            spectre_score += 2
            continue
        if re.match(r"^\w+\s*\([^)]*\)\s+\w", line):
            first = line.split(None, 1)[0].lower()
            if first not in ("subckt", "model", "ends", "parameters",
                             "simulator", "inline", "connect"):
                spectre_score += 2
        low = line.lower()
        if low.startswith(".control") or low.startswith(".endc"):
            ngspice_score += 3
        elif low.startswith(".four") or low.startswith(".fourier"):
            ngspice_score += 2
        elif (low.startswith(".alter") or low.startswith(".data")
              or low.startswith(".probe") or low.startswith(".print")):
            hspice_score += 2
        elif low.startswith(".option") and "post" in low:
            hspice_score += 2  # .option post=HSPICE 仿真输出标志（ngspice 无）
        elif low.startswith(".step"):
            hspice_score += 2  # .step 步进卡=HSPICE 方言（ngspice 无此卡）
        elif (low.startswith(".tran") or low.startswith(".dc")
              or low.startswith(".ac")) and " sweep" in low:
            hspice_score += 1  # 内联 sweep=HSPICE 惯例
        if ";" in line:
            hspice_score += 1
    best = max(spectre_score, ngspice_score, hspice_score)
    if best == 0:
        return FLAVOR_NGSPICE
    if spectre_score == best and spectre_score > max(ngspice_score, hspice_score):
        return FLAVOR_SPECTRE
    if ngspice_score >= hspice_score:
        return FLAVOR_NGSPICE
    return FLAVOR_HSPICE


# --------------------------------------------------------------------------- #
# 令牌工具
# --------------------------------------------------------------------------- #


def _split_paren_pin_list(tokens: list[str]) -> tuple[list[str], list[str]]:
    """括号 pin 形态拆分：``(n1 n2) rest...`` → (pins, rest)。

    容忍 pin 挤在单令牌（``(n1`` ``n2)``）与逗号分隔；无括号形态返回
    ([], tokens) 原样。
    """
    if not tokens or not tokens[0].startswith("("):
        return [], list(tokens)
    text = " ".join(tokens)
    open_idx = text.find("(")
    close_idx = text.find(")", open_idx)
    if close_idx == -1:
        return [], list(tokens)
    inner = text[open_idx + 1:close_idx]
    pins = [p for p in re.split(r"[\s,]+", inner.strip()) if p]
    rest_text = text[close_idx + 1:].strip()
    return pins, rest_text.split()


def _param_dict(tokens: list[str]) -> dict[str, object]:
    """令牌段的 ``key=value`` 参数 → dict（数值解析失败保留原串）。

    ``k={expr}``/``k='expr'`` 表达式保留原文（解析器不代入——模块
    docstring 如实声明）。
    """
    out: dict[str, object] = {}
    for tok in tokens:
        m = _PARAM_RE.match(tok)
        if not m:
            continue
        key = m.group(1)
        raw_val = m.group(2).strip()
        if raw_val.startswith("{") and raw_val.endswith("}"):
            out[key] = raw_val
            continue
        num = parse_spice_number(raw_val)
        out[key] = num if num is not None else raw_val
    return out


def _maybe_value(token: str) -> dict[str, object] | None:
    """位置值令牌 → ``{"value": float|None, "value_raw": 原文}``；非值 None。

    接受：纯数值/缩放数值、``{expr}``/``'expr'`` 表达式（value=None 仅
    raw 留档）。
    """
    t = token.strip()
    if not t:
        return None
    if (t.startswith("{") and t.endswith("}")) or (
            t.startswith("'") and t.endswith("'") and len(t) >= 2):
        return {"value": None, "value_raw": t}
    num = parse_spice_number(t)
    if num is not None:
        return {"value": num, "value_raw": t}
    return None


# --------------------------------------------------------------------------- #
# 主解析
# --------------------------------------------------------------------------- #


def _diag(diags: list[dict], tier: str, reason: str, line_no: int | None,
          snippet: str | None) -> None:
    """AX-6 结构化 tier 诊断入列（snippet=消费语句原文，#331 不美化）。"""
    diags.append(make_parse_diagnostic(
        tier, reason, line_no, snippet, parser="spice_netlist"))


def parse_spice_netlist_text(text: str, flavor: str = FLAVOR_AUTO) -> dict:
    """网表文本 → 五维度统一结构化 dict（纯函数；不仿真不代入表达式）。

    返回键集（PARSER_SCHEMA_VERSION=1.0 契约；全 JSON 原生类型）::

        {
          "schema": "spice_netlist/1.0",
          "flavor": "ngspice|hspice|spectre",
          "flavor_requested": "auto|ngspice|hspice|spectre",
          "flavor_detected": bool,
          "title": 标题行原文或 None（SPICE 首行惯例；Spectre 恒 None）,
          "elements": [...],   # 五维度之一
          "subckts": [...],
          "controls": [...],
          "models": [...],
          "topology": {...},   # 顶层网表（scope_note 声明口径）
          "summary": {..., "n_warnings"},   # 计数面含 n_warnings（R-22 升位批补键）
          "structural_errors": [...],
          "warnings": [...],
        }

    各维度条目字段见 _handle_element_line/_handle_subckt_start/
    _handle_control_card/_handle_model_card/_build_topology。
    """
    flavor_requested = normalize_flavor(flavor)
    detected = flavor_requested == FLAVOR_AUTO
    flavor_eff = detect_flavor(text) if detected else flavor_requested
    lines = _preprocess(text, flavor_eff)
    warnings: list[str] = []
    diags: list[dict] = []

    if flavor_eff == FLAVOR_SPECTRE:
        parsed = _parse_spectre(lines, warnings, diags)
    else:
        parsed = _parse_spice(lines, flavor_eff, warnings, diags)

    topology = _build_topology(parsed["elements"], parsed["subckts"], warnings)
    result: dict = {
        "schema": f"spice_netlist/{PARSER_SCHEMA_VERSION}",
        "flavor": flavor_eff,
        "flavor_requested": flavor_requested,
        "flavor_detected": detected,
        "title": parsed["title"],
        "elements": parsed["elements"],
        "subckts": parsed["subckts"],
        "controls": parsed["controls"],
        "models": parsed["models"],
        "topology": topology,
        "summary": {
            "n_elements": len(parsed["elements"]),
            "n_subckts": len(parsed["subckts"]),
            "n_models": len(parsed["models"]),
            "n_controls": len(parsed["controls"]),
            "n_nodes": topology["n_nodes"],
            "n_non_ground_nodes": topology["n_non_ground_nodes"],
            "mna_size": topology["mna_size"],
            "n_x_instances": topology["n_x_instances"],
            "n_structural_errors": len(parsed["structural_errors"]),
            "n_warnings": len(warnings),
        },
        "structural_errors": parsed["structural_errors"],
        "warnings": warnings,
        "diagnostics": diags,
    }
    return result


# --------------------------------------------------------------------------- #
# SPICE 两方言（ngspice/HSPICE）解析
# --------------------------------------------------------------------------- #

#: 子电路终止符方言收编词表（.ends 标准；其余收编+warning）。
_SUBCKT_END_ALIASES = frozenset({".ends", ".endl", ".endfl", ".endt", "ends"})


def _parse_spice(lines: list[tuple[int, str]], flavor: str,
                 warnings: list[str], diags: list[dict]) -> dict:
    elements: list[dict] = []
    subckts: list[dict] = []
    controls: list[dict] = []
    models: list[dict] = []
    errors: list[str] = []
    title: str | None = None
    scope_stack: list[str] = []
    name_to_subckt: dict[str, dict] = {}
    in_control_block = False
    control_block_lines: list[str] = []
    control_block_start = 0

    for stmt_idx, (line_no, stmt) in enumerate(lines):
        toks = stmt.split()
        if not toks:
            continue
        head = toks[0]
        head_low = head.lower()
        if title is None and stmt_idx == 0 and not head.startswith(".") \
                and not _looks_like_element(toks):
            title = stmt
            continue
        if head_low == ".control":
            # ngspice 交互命令块（ac/wrdata/meas 等脚本行非网表元件）——
            # 整块捕获为单条 control（name="control_block"），块内行跳过
            # 元件解析（"ac dec 10 1k 100meg" 首字母 a=A 类误吸需防）。
            if in_control_block:
                errors.append(
                    f"第 {line_no} 行嵌套 .control（前块未 .endc 关闭）"
                )
                _diag(diags, TIER_UNPARSED, "nested_control_block",
                      line_no, stmt)
            in_control_block = True
            control_block_lines: list[str] = []
            control_block_start = line_no
            continue
        if head_low == ".endc":
            if not in_control_block:
                errors.append(f"第 {line_no} 行 .endc 无匹配的 .control")
                _diag(diags, TIER_UNPARSED, "endc_without_control",
                      line_no, stmt)
            else:
                controls.append({
                    "name": "control_block",
                    "args": list(control_block_lines),
                    "params": {},
                    "sweep": None,
                    "scope": list(scope_stack),
                    "raw": "\n".join(control_block_lines),
                    "line_no": control_block_start,
                })
                in_control_block = False
            continue
        if in_control_block:
            control_block_lines.append(stmt)
            continue
        if head_low.startswith(".subckt"):
            _handle_subckt_start(toks, stmt, line_no, scope_stack, subckts,
                                 name_to_subckt, errors, warnings, diags)
            continue
        if head_low in _SUBCKT_END_ALIASES:
            if head_low != ".ends":
                warnings.append(
                    f"第 {line_no} 行子电路终止符 {head!r} 非 .ends 标准形态"
                    "（方言收编：.endl/.endfl/.endt/ends 同口径关闭）"
                )
                _diag(diags, TIER_UNSUPPORTED_1,
                      "dialect_subckt_terminator_absorbed", line_no, stmt)
            _handle_subckt_end(line_no, head, scope_stack, subckts, errors,
                               diags)
            continue
        if head_low == ".end":
            continue
        if head_low.startswith(".model"):
            _handle_model_card(toks, stmt, line_no, scope_stack, models, diags)
            continue
        if head.startswith("."):
            _handle_control_card(head, toks, stmt, line_no, scope_stack, controls)
            continue
        _handle_element_line(toks, stmt, line_no, scope_stack, elements,
                             name_to_subckt, errors, warnings, diags)
    if scope_stack:
        errors.append(
            f"文件结束仍有未关闭的 .subckt 定义: {scope_stack}（缺少 .ends）"
        )
        _diag(diags, TIER_UNSUPPORTED_3, "subckt_unclosed_at_eof", None, None)
    _resolve_x_references(elements, name_to_subckt, warnings, diags)
    return {
        "title": title,
        "elements": elements,
        "subckts": subckts,
        "controls": controls,
        "models": models,
        "structural_errors": errors,
    }


def _resolve_x_references(elements: list[dict],
                          name_to_subckt: dict[str, dict],
                          warnings: list[str],
                          diags: list[dict]) -> None:
    """X 引用解析后置（instances_in 回填 + 未定义引用警告单源）。

    SPICE 惯例子电路定义在实例之后——解析期前向引用放行，全部元素收齐
    后统一解析：命中 → ``instances_in`` 回填（去重保序）；未命中 →
    warning 如实（.include/.lib 外部定义不展开）。
    """
    seen: dict[str, set[str]] = {}
    for el in elements:
        if el["kind"] != "X":
            continue
        ref = el.get("subckt_ref")
        if not ref:
            continue
        target = name_to_subckt.get(ref)
        if target is not None:
            bucket = seen.setdefault(ref, set())
            if el["name"] not in bucket:
                bucket.add(el["name"])
                target["instances_in"].append(el["name"])
        else:
            warnings.append(
                f"第 {el['line_no']} 行 X 实例 {el['name']} 引用未在本文件"
                f"定义的子电路 {ref!r}（.include/.lib 外部定义不展开）"
            )
            _diag(diags, TIER_UNSUPPORTED_2, "x_reference_unresolved_external",
                  el.get("line_no"), el.get("raw"))


def _looks_like_element(toks: list[str]) -> bool:
    """首逻辑行是否"更像元件行"（首行标题惯例的反例守卫）。

    SPICE 标准：文件首行恒为标题——元件形态的首行会被真引擎当标题吞掉。
    本守卫只对**结构上确凿**的元件行让位（末令牌可解析为数值或含
    ``k=v`` 参数段的 ≥3 令牌行）；纯文字行（"RC divider circuit"——末
    令牌非数值无参数段）按标题处理。首行直接以 X 实例开场且无标题的
    deck 按标准让位（title=该行，X 不解析——与真引擎行为一致，如实
    声明于模块 docstring）。
    """
    first = toks[0]
    if first.startswith(".") or not first:
        return False
    letter = first[0].upper()
    if letter not in SPICE_LETTER_KINDS or len(toks) < 3:
        return False
    if parse_spice_number(toks[-1]) is not None:
        return True
    if toks[-1].startswith("{") or toks[-1].startswith("'"):
        return True  # 表达式/引号值（'2p*3'/{1k*2}）也是确凿元件结构
    return any("=" in t for t in toks[1:])


def _handle_subckt_start(toks: list[str], raw: str, line_no: int,
                         scope_stack: list[str], subckts: list[dict],
                         name_to_subckt: dict[str, dict], errors: list[str],
                         warnings: list[str], diags: list[dict]) -> None:
    body = toks[1:]
    if not body:
        errors.append(f"第 {line_no} 行 .subckt 缺名: {raw!r}")
        _diag(diags, TIER_UNPARSED, "subckt_missing_name", line_no, raw)
        return
    name = body[0]
    rest = body[1:]
    if scope_stack:
        warnings.append(
            f"第 {line_no} 行嵌套 .subckt（SPICE 标准不嵌套——按方言收编为"
            "顺序定义，层次仍由 X 引用边表达）"
        )
        _diag(diags, TIER_UNSUPPORTED_1, "nested_subckt_dialect_absorbed",
              line_no, raw)
    pins, rest2 = _split_paren_pin_list(rest)
    if not pins:
        pins = rest2
        rest2 = []
    params: dict[str, object] = {}
    for i, t in enumerate(rest2):
        if t.lower() == "params:":
            params = _param_dict(rest2[i + 1:])
            rest2 = rest2[:i]
            break
    for k, v in _param_dict(rest2).items():
        params.setdefault(k, v)
    entry = {
        "name": name,
        "pins": [_normalize_ground(p) for p in pins],
        "params": params,
        "scope": list(scope_stack),
        "element_names": [],
        "instances_in": [],
        "line_no": line_no,
        "end_line_no": None,
        "raw": raw,
    }
    subckts.append(entry)
    name_to_subckt[name] = entry
    scope_stack.append(name)


def _handle_subckt_end(line_no: int, head: str, scope_stack: list[str],
                       subckts: list[dict], errors: list[str],
                       diags: list[dict]) -> None:
    if not scope_stack:
        errors.append(
            f"第 {line_no} 行 {head} 无匹配的 .subckt（当前无打开的子电路）"
        )
        _diag(diags, TIER_UNPARSED, "ends_without_subckt", line_no, head)
        return
    name = scope_stack.pop()
    for entry in reversed(subckts):
        if entry["name"] == name and entry["end_line_no"] is None:
            entry["end_line_no"] = line_no
            break


def _handle_model_card(toks: list[str], raw: str, line_no: int,
                       scope_stack: list[str], models: list[dict],
                       diags: list[dict]) -> None:
    if len(toks) < 3:
        _diag(diags, TIER_UNPARSED, "model_insufficient_tokens", line_no, raw)
        models.append({
            "name": None, "type": None, "level": None, "params": {},
            "positional_params": [], "scope": list(scope_stack),
            "raw": raw, "line_no": line_no,
            "structural_error": (
                f"第 {line_no} 行 .model 令牌不足"
                f"（需 .model name type [params]）: {raw!r}"
            ),
        })
        return
    name, mtype = toks[1], toks[2].strip("()")
    rest = toks[3:]
    params = _param_dict(rest)
    positional = [t for t in rest if "=" not in t]
    level = params.get("level")
    models.append({
        "name": name,
        "type": mtype,
        "level": level if isinstance(level, (int, float)) else (
            parse_spice_number(str(level)) if level is not None else None),
        "params": params,
        "positional_params": positional,
        "scope": list(scope_stack),
        "raw": raw,
        "line_no": line_no,
    })


def _parse_sweep(head_low: str, args: list[str], params: dict,
                 low_args: list[str]) -> dict | None:
    """控制卡扫描/步进段归一（``sweep`` 字段单源）。

    - ``.dc V1 0 1 0.1``：dc 本身即扫描语义（declared=True 逐字段解析）；
    - 内联 sweep：``.tran 1n 100n sweep temp -40 125 5`` / ``.ac ... sweep
      vdd 1.8 3.3 0.1`` → ``{"kind": 卡名, "source": 扫描变量, ...}``；
    - ``.step param=vdd list 1.8 3.3``（HSPICE 步进卡）→ kind="step"，
      source 取 ``param=``/``var=``。
    """
    if head_low == ".dc":
        return {
            "kind": "dc",
            "declared": True,
            "source": args[0] if args else None,
            "start": parse_spice_number(args[1]) if len(args) > 1 else None,
            "stop": parse_spice_number(args[2]) if len(args) > 2 else None,
            "step": parse_spice_number(args[3]) if len(args) > 3 else None,
        }
    if "sweep" in low_args:
        idx = low_args.index("sweep")
        rest_tokens = args[idx + 1:]
        source = next(
            (t for t in rest_tokens if "=" not in t
             and parse_spice_number(t) is None),
            None,
        )
        return {
            "kind": head_low.lstrip("."),
            "declared": True,
            "source": source,
            "raw_args": rest_tokens,
            "params": _param_dict(rest_tokens),
        }
    if head_low == ".step":
        return {
            "kind": "step",
            "declared": True,
            "source": params.get("param") or params.get("var"),
            "params": params,
        }
    return None


def _handle_control_card(head: str, toks: list[str], raw: str, line_no: int,
                         scope_stack: list[str], controls: list[dict]) -> None:
    args = toks[1:]
    low_args = [a.lower() for a in args]
    params = _param_dict(args)
    controls.append({
        "name": head.lower().lstrip("."),
        "args": args,
        "params": params,
        "sweep": _parse_sweep(head.lower(), args, params, low_args),
        "scope": list(scope_stack),
        "raw": raw,
        "line_no": line_no,
    })


def _handle_element_line(toks: list[str], raw: str, line_no: int,
                         scope_stack: list[str], elements: list[dict],
                         name_to_subckt: dict[str, dict], errors: list[str],
                         warnings: list[str], diags: list[dict]) -> None:
    name = toks[0]
    letter = name[0].upper()
    meta = _KIND_META.get(letter)
    if meta is None:
        errors.append(
            f"第 {line_no} 行未知元件类型 {letter!r}"
            f"（不在 SPICE 元件首字母词表）: {raw!r}"
        )
        _diag(diags, TIER_UNSUPPORTED_1, "element_letter_unsupported",
              line_no, raw)
        return
    entry: dict = {
        "name": name,
        "kind": letter,
        "kind_desc": meta["desc"],
        "nodes": [],
        "value": None,
        "value_raw": None,
        "unit": meta["unit"],
        "model": None,
        "control_source": None,
        "subckt_ref": None,
        "source_spec": None,
        "params": {},
        "scope": list(scope_stack),
        "line_no": line_no,
        "raw": raw,
    }
    owner = name_to_subckt.get(scope_stack[-1]) if scope_stack else None
    rest = toks[1:]

    if letter == "X":
        _handle_x_instance(entry, rest, line_no, errors, diags)
        elements.append(entry)
        if owner is not None:
            owner["element_names"].append(name)
        return

    if letter in ("F", "H", "W"):
        # 电流控制类：name n+ n- 控制源 [值/模型...]——第 3 令牌是控制源名
        # 非 node（task 口径"端口对"）。
        if len(rest) < 3:
            errors.append(
                f"第 {line_no} 行元件 {name}（{meta['desc']}）令牌不足"
                f"（需 ≥3 个：n+ n- 控制源）: {raw!r}"
            )
            _diag(diags, TIER_UNSUPPORTED_3,
                  "element_insufficient_tokens_degraded", line_no, raw)
            elements.append(entry)
            if owner is not None:
                owner["element_names"].append(name)
            return
        entry["nodes"] = [_normalize_ground(p) for p in rest[:2]]
        entry["control_source"] = rest[2]
        cursor = rest[3:]
        entry["params"] = _param_dict(cursor)
        if cursor and "=" not in cursor[0]:
            v = _maybe_value(cursor[0])
            if v is not None:
                entry["value"] = v["value"]
                entry["value_raw"] = v["value_raw"]
        elements.append(entry)
        if owner is not None:
            owner["element_names"].append(name)
        return

    n_nodes = meta["n_nodes"]
    if n_nodes is None:  # Q 变体：3 节点（+model）或 4 节点（c b e s +model）
        n_nodes = 4 if len(rest) >= 5 else 3
    if len(rest) < n_nodes + (1 if meta["model"] else 0):
        errors.append(
            f"第 {line_no} 行元件 {name}（{meta['desc']}）令牌不足"
            f"（需 ≥{n_nodes + 1} 个）: {raw!r}"
        )
        _diag(diags, TIER_UNSUPPORTED_3,
              "element_insufficient_tokens_degraded", line_no, raw)
        elements.append(entry)
        if owner is not None:
            owner["element_names"].append(name)
        return

    if letter == "K":
        # Kname L1 L2 coupling
        if len(rest) < 3:
            errors.append(
                f"第 {line_no} 行 K 元件 {name} 缺互感要素"
                f"（需 L1 L2 coupling）: {raw!r}"
            )
            _diag(diags, TIER_UNSUPPORTED_3,
                  "mutual_inductance_missing_operands", line_no, raw)
        else:
            entry["params"] = {"inductors": rest[:2]}
            v = _maybe_value(rest[2])
            if v is not None:
                entry["value"] = v["value"]
                entry["value_raw"] = v["value_raw"]
            else:
                errors.append(
                    f"第 {line_no} 行 K 元件 {name} 耦合系数不可解析:"
                    f" {rest[2]!r}"
                )
                _diag(diags, TIER_UNSUPPORTED_3,
                      "mutual_inductance_value_unparsable", line_no, raw)
        elements.append(entry)
        if owner is not None:
            owner["element_names"].append(name)
        return

    entry["nodes"] = [_normalize_ground(p) for p in rest[:n_nodes]]
    cursor = rest[n_nodes:]
    if meta["model"] and cursor:
        entry["model"] = cursor[0]
        cursor = cursor[1:]
    entry["params"] = _param_dict(cursor)
    if cursor and "=" not in cursor[0]:
        v = _maybe_value(cursor[0])
        if v is not None:
            entry["value"] = v["value"]
            entry["value_raw"] = v["value_raw"]
            cursor = cursor[1:]
        else:
            spec = cursor[0].upper().rstrip("()").lower()
            if letter == "V" and spec in _SOURCE_SPECS:
                # 位置形态源规格：V1 n1 n2 DC 5 / SIN(...) —— spec 段整体留档
                entry["source_spec"] = {"type": spec.upper(),
                                        "raw": " ".join(cursor)}
    # hspice 参数化主值形态（R1 n1 n2 R=1k / C1 n1 n2 c=1p）→ params 回填
    if entry["value"] is None:
        low_params = {k.lower(): (k, v) for k, v in entry["params"].items()}
        for alias in (letter.lower(), {"R": "resistance", "C": "capacitance",
                                       "L": "inductance"}.get(letter.lower(), "")):
            if alias and alias in low_params:
                _, val = low_params[alias]
                entry["value"] = val
                entry["value_raw"] = str(val)
                break
    elements.append(entry)
    if owner is not None:
        owner["element_names"].append(name)


def _handle_x_instance(entry: dict, rest: list[str], line_no: int,
                       errors: list[str], diags: list[dict]) -> None:
    """X 实例：``Xname n1..nN subckt [params: k=v..]`` / 括号 pin/参数形态。"""
    if rest and rest[0].startswith("("):
        pins, rest = _split_paren_pin_list(rest)
        entry["nodes"] = [_normalize_ground(p) for p in pins]
        if rest:
            entry["subckt_ref"] = rest[0]
            for k, v in _param_dict(rest[1:]).items():
                entry["params"].setdefault(k, v)
    else:
        params_split = None
        for i, t in enumerate(rest):
            if t.lower() == "params:":
                params_split = i
                break
        if params_split is not None:
            node_toks = rest[:params_split]
            if node_toks:
                entry["subckt_ref"] = node_toks[-1]
                entry["nodes"] = [_normalize_ground(p) for p in node_toks[:-1]]
            entry["params"] = _param_dict(rest[params_split + 1:])
        else:
            param_toks = [t for t in rest if "=" in t]
            plain = [t for t in rest if "=" not in t]
            if plain:
                entry["subckt_ref"] = plain[-1]
                entry["nodes"] = [_normalize_ground(p) for p in plain[:-1]]
            for k, v in _param_dict(param_toks).items():
                entry["params"].setdefault(k, v)
    if entry["subckt_ref"] is None:
        errors.append(f"第 {line_no} 行 X 实例缺子电路名: {entry['raw']!r}")
        _diag(diags, TIER_UNPARSED, "x_missing_subckt_ref", line_no,
              entry.get("raw"))
        return
    # 引用解析（instances_in 回填/未定义警告）统一延后到 _resolve_x_references
    # ——SPICE 惯例子电路定义在实例之后，解析期前向引用必须放行。


# --------------------------------------------------------------------------- #
# Spectre 解析
# --------------------------------------------------------------------------- #


def _parse_spectre(lines: list[tuple[int, str]], warnings: list[str],
                   diags: list[dict]) -> dict:
    elements: list[dict] = []
    subckts: list[dict] = []
    controls: list[dict] = []
    models: list[dict] = []
    errors: list[str] = []
    scope_stack: list[str] = []
    name_to_subckt: dict[str, dict] = {}
    models_by_name: dict[str, dict] = {}

    for line_no, stmt in lines:
        toks = stmt.split()
        if not toks:
            continue
        head = toks[0]
        head_low = head.lower()
        if head_low == "simulator":
            if "spice" in stmt.lower():
                warnings.append(
                    f"第 {line_no} 行 simulator lang=spice 混排段不切换语法"
                    "（按检测主 flavor 统一解析——多方言混排如实警示）"
                )
                _diag(diags, TIER_UNSUPPORTED_1, "spice_segment_mixed_language",
                      line_no, stmt)
            continue
        if head_low in ("parameters", "parameter", "global", "options",
                        "option", "save", "include", "inline", "connect"):
            controls.append({
                "name": head_low,
                "args": toks[1:],
                "params": _param_dict(toks[1:]),
                "sweep": None,
                "scope": list(scope_stack),
                "raw": stmt,
                "line_no": line_no,
            })
            continue
        if head_low == "subckt":
            body = toks[1:]
            if not body:
                errors.append(f"第 {line_no} 行 subckt 缺名: {stmt!r}")
                _diag(diags, TIER_UNPARSED, "subckt_missing_name", line_no,
                      stmt)
                continue
            sname = body[0]
            pins, rest2 = _split_paren_pin_list(body[1:])
            entry = {
                "name": sname,
                "pins": [_normalize_ground(p) for p in pins],
                "params": _param_dict(rest2),
                "scope": list(scope_stack),
                "element_names": [],
                "instances_in": [],
                "line_no": line_no,
                "end_line_no": None,
                "raw": stmt,
            }
            subckts.append(entry)
            name_to_subckt[sname] = entry
            scope_stack.append(sname)
            continue
        if head_low in ("ends", "endends"):
            if not scope_stack:
                errors.append(
                    f"第 {line_no} 行 {head} 无匹配 subckt（当前无打开的子电路）"
                )
                _diag(diags, TIER_UNPARSED, "ends_without_subckt", line_no,
                      stmt)
                continue
            sname = scope_stack.pop()
            for entry in reversed(subckts):
                if entry["name"] == sname and entry["end_line_no"] is None:
                    entry["end_line_no"] = line_no
                    break
            continue
        if head_low == "model":
            body = toks[1:]
            if len(body) < 2:
                errors.append(
                    f"第 {line_no} 行 model 令牌不足"
                    f"（需 model name master [params]）: {stmt!r}"
                )
                _diag(diags, TIER_UNPARSED, "model_insufficient_tokens",
                      line_no, stmt)
                continue
            mname, master = body[0], body[1]
            params = _param_dict(body[2:])
            params.setdefault("master", master)
            level = params.get("level")
            model_entry = {
                "name": mname,
                "type": master,
                "level": level if isinstance(level, (int, float)) else (
                    parse_spice_number(str(level)) if level is not None else None),
                "params": params,
                "positional_params": [],
                "scope": list(scope_stack),
                "raw": stmt,
                "line_no": line_no,
            }
            models.append(model_entry)
            models_by_name[mname] = model_entry
            continue
        if len(toks) >= 2 and toks[1].lower() in _SPECTRE_ANALYSES \
                and not toks[1].startswith("("):
            # 命名分析块：tran1 tran stop=1u —— head=实例名，toks[1]=类型
            atype = toks[1].lower()
            params = _param_dict(toks[2:])
            sweep = None
            if atype in ("sweep", "dc"):
                sweep = {"kind": atype, "declared": True, "params": params}
            controls.append({
                "name": atype,
                "args": toks[2:],
                "params": params,
                "sweep": sweep,
                "instance": head,
                "scope": list(scope_stack),
                "raw": stmt,
                "line_no": line_no,
            })
            continue
        if toks[1:2] and toks[1].startswith("("):
            _handle_spectre_element(toks, stmt, line_no, scope_stack,
                                    elements, name_to_subckt, models_by_name,
                                    errors, warnings, diags)
            continue
        errors.append(f"第 {line_no} 行 Spectre 语句无法归类: {stmt!r}")
        _diag(diags, TIER_UNPARSED, "statement_unclassifiable", line_no, stmt)
    if scope_stack:
        errors.append(
            f"文件结束仍有未关闭的 subckt: {scope_stack}（缺少 ends）"
        )
        _diag(diags, TIER_UNSUPPORTED_3, "subckt_unclosed_at_eof", None, None)
    return {
        "title": None,  # Spectre 无标题行惯例（首行恒为语句）
        "elements": elements,
        "subckts": subckts,
        "controls": controls,
        "models": models,
        "structural_errors": errors,
    }


#: Spectre 设备模型（bsim4/hicum 等）kind 关键词启发式（model name+type
#: 联合小写扫描，序即优先级；未命中回退 type 首字母）。
_SPECTRE_MODEL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("bsim", "M"), ("mos", "M"), ("hicum", "Q"), ("bjt", "Q"),
    ("npn", "Q"), ("pnp", "Q"), ("jfet", "J"), ("mesfet", "Z"),
    ("diode", "D"), ("vcvs", "E"), ("cccs", "F"), ("vccs", "G"),
    ("ccvs", "H"), ("vsource", "V"), ("isource", "I"), ("switch", "S"),
    ("res", "R"), ("cap", "C"), ("ind", "L"),
)


def _spectre_model_kind(model_entry: dict) -> str:
    """已定义 Spectre 模型 → 统一 kind（model 名+type 关键词启发式）。

    已定义模型是显式声明非猜测——零 warning（与内建 master 未命中路径
    区分）；关键词全未命中时回退 type 首字母，再未命中归 N 兜底。
    """
    haystack = " ".join([
        str(model_entry.get("name") or ""),
        str(model_entry.get("type") or ""),
    ]).lower()
    for keyword, kind in _SPECTRE_MODEL_KEYWORDS:
        if keyword in haystack:
            return kind
    mtype = str(model_entry.get("type") or "")
    if mtype and mtype[0].upper() in SPICE_LETTER_KINDS:
        return mtype[0].upper()
    return "N"


def _handle_spectre_element(toks: list[str], raw: str, line_no: int,
                            scope_stack: list[str], elements: list[dict],
                            name_to_subckt: dict[str, dict],
                            models_by_name: dict[str, dict],
                            errors: list[str], warnings: list[str],
                            diags: list[dict]) -> None:
    """Spectre 元件/实例：``name (nodes) master params...``。

    master 解析序：本文件 subckt 名 → X 实例；本文件 model 名 → 按其
    type（bsim4 等）映射 kind（映射未命中按 type 首字母，零 warning——
    已定义模型是显式声明非猜测）；内建 master 表 → kind；其余按 master
    首字母归档并 warning 如实。
    """
    head = toks[0]
    pins, rest = _split_paren_pin_list(toks[1:])
    if not rest:
        errors.append(
            f"第 {line_no} 行 Spectre 语句缺 master/类型: {raw!r}"
        )
        _diag(diags, TIER_UNPARSED, "spectre_missing_master", line_no, raw)
        return
    master = rest[0]
    params = _param_dict(rest[1:])
    subckt_names = set(name_to_subckt)
    if master.lower() in {m.lower() for m in subckt_names}:
        kind = "X"
    elif master.lower() in {m.lower() for m in models_by_name}:
        model_entry = models_by_name[
            next(m for m in models_by_name if m.lower() == master.lower())
        ]
        kind = _spectre_model_kind(model_entry)
    elif master.lower() in _SPECTRE_MASTER_KIND:
        kind = _SPECTRE_MASTER_KIND[master.lower()]
    elif master[0].upper() in SPICE_LETTER_KINDS:
        kind = master[0].upper()
        warnings.append(
            f"第 {line_no} 行 master {master!r} 不在内建映射表——按首字母"
            f" {kind} 归档（model 字段保留原名）"
        )
        _diag(diags, TIER_UNSUPPORTED_3, "master_first_letter_fallback",
              line_no, raw)
    else:
        kind = "N"
        warnings.append(
            f"第 {line_no} 行 master {master!r} 不在内建映射表——按 N 类"
            "兜底归档（model 字段保留原名）"
        )
        _diag(diags, TIER_UNSUPPORTED_3, "master_unknown_fallback",
              line_no, raw)
    meta = _KIND_META[kind]
    entry: dict = {
        "name": head,
        "kind": kind,
        "kind_desc": meta["desc"],
        "nodes": [_normalize_ground(p) for p in pins],
        "value": None,
        "value_raw": None,
        "unit": meta["unit"],
        "model": None if kind == "X" else master,
        "control_source": None,
        "subckt_ref": master if kind == "X" else None,
        "source_spec": None,
        "params": params,
        "scope": list(scope_stack),
        "line_no": line_no,
        "raw": raw,
    }
    # 主参数归一（resistor r= → value；capacitor c=；inductor l=；
    # vsource/isource dc= → value——Spectre 命名参数形态）
    unit_alias = {"R": ("r", "res"), "C": ("c", "cap"), "L": ("l", "ind"),
                  "V": ("dc",), "I": ("dc",)}.get(kind)
    if unit_alias:
        low_params = {k.lower(): (k, v) for k, v in params.items()}
        for alias in unit_alias:
            if alias in low_params:
                _, val = low_params[alias]
                entry["value"] = val
                entry["value_raw"] = str(val)
                break
    if kind == "X" and master in name_to_subckt:
        name_to_subckt[master]["instances_in"].append(head)
    elements.append(entry)
    if scope_stack and scope_stack[-1] in name_to_subckt:
        name_to_subckt[scope_stack[-1]]["element_names"].append(head)


# --------------------------------------------------------------------------- #
# 拓扑
# --------------------------------------------------------------------------- #


def _build_topology(elements: list[dict], subckts: list[dict],
                    warnings: list[str]) -> dict:
    """顶层网表拓扑（子电路体不展开——模块 docstring 如实声明）。

    - 双向图：node→[element names] 与 element→[nodes]；
    - 孤立节点：顶层恰好只被 1 个元件引用的非地节点（浮空嫌疑；孤立=
      解析层判据非电气结论——单端接地器件亦触发，须人工复核电气语义）；
    - MNA 维度 = 非地节点数 + 分支电流增广数（V/E/H——与
      core.macromodel._REPLAY_BRANCH_KINDS 同口径）。
    """
    node_elements: dict[str, list[str]] = {}
    element_nodes: dict[str, list[str]] = {}
    n_branches = 0
    n_x = 0
    for el in elements:
        if el.get("scope"):
            continue  # 子电路体不展开
        nodes = [str(n) for n in el.get("nodes") or []]
        element_nodes[el["name"]] = nodes
        for nd in nodes:
            node_elements.setdefault(nd, []).append(el["name"])
        meta = _KIND_META.get(el["kind"]) or {}
        if meta.get("branch"):
            n_branches += 1
        if el["kind"] == "X":
            n_x += 1
    non_ground = sorted(n for n in node_elements if n != "0")
    isolated = sorted(
        n for n, els in node_elements.items() if n != "0" and len(els) == 1
    )
    if isolated:
        warnings.append(
            "检测到疑似孤立节点（顶层单连接，浮空嫌疑——单端接地器件亦会"
            "触发，须人工复核电气语义）: " + ", ".join(isolated)
        )
    return {
        "ground_nodes": sorted(n for n in node_elements if n == "0"),
        "non_ground_nodes": non_ground,
        "n_nodes": len(node_elements),
        "n_non_ground_nodes": len(non_ground),
        "n_branches": n_branches,
        "mna_size": len(non_ground) + n_branches,
        "isolated_nodes": isolated,
        "node_elements": node_elements,
        "element_nodes": element_nodes,
        "n_x_instances": n_x,
        "subckt_count": len(subckts),
        "scope_note": (
            "top-level only（子电路体为模板不展平；X 实例引脚按顶层网络计数）"
        ),
        "hierarchy": _subckt_hierarchy(elements, subckts),
    }


def _subckt_hierarchy(elements: list[dict],
                      subckts: list[dict]) -> list[dict]:
    """子电路调用层次树：roots=顶层 X 直接引用的子电路；children=递归。

    环引用（自引用/互引）以 ``recursive=True`` 叶截断（不穷举——层次树
    非展平）。
    """
    by_name = {s["name"]: s for s in subckts}
    children_of: dict[str | None, list[str]] = {}
    for el in elements:
        if el["kind"] != "X" or not el.get("subckt_ref"):
            continue
        scope = tuple(el.get("scope") or [])
        parent: str | None = scope[-1] if scope else None
        if parent is not None and parent not in by_name:
            parent = None  # 引用未定义子电路的实例归顶层（引用警告解析期已记）
        bucket = children_of.setdefault(parent, [])
        if el["subckt_ref"] not in bucket:
            bucket.append(el["subckt_ref"])

    def node_for(name: str, seen: frozenset[str]) -> dict:
        if name in seen:
            return {"name": name, "recursive": True, "children": []}
        sub = by_name.get(name)
        kids = children_of.get(name) or []
        return {
            "name": name,
            "recursive": False,
            "pins": sub["pins"] if sub else None,
            "children": [node_for(k, seen | {name}) for k in kids],
        }

    return [node_for(r, frozenset()) for r in (children_of.get(None) or [])]
