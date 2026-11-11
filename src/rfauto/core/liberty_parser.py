"""Liberty (.lib) 时序库结构化解析内核（aurora_q Q-X34，2026-11-07）。

数字 IC 标准**时序库格式**（Synopsys Liberty，IEEE 1601 系自由格式）的
只读结构化解析——数模混合设计中 RF 用户需要读取时序库做 timing/power
引用时的单源入口。解析纯函数+NLDM 查找表提取+双线性插值全部在 core
确定性内核（铁律 7：数字只出自数据源与本内核的声明式公式；LLM/agent
永不产生物理数字）。服务包装见 :mod:`rfauto.service.liberty_service`
（规则 4 JSON 进出），CLI 薄壳见 cli/domains/liberty.py。

格式要点（解析面覆盖范围）：

- 组（group）：``cell (NAME) { … }``——类型名+圆括号名表+花括号体；
  名表可空（``timing () { … }`` 惯例）；
- 简单属性：``area : 4.5 ;``——单值后跟分号；
- 复合属性：``index_1 ("0.01, 0.2") ;``——圆括号参数表后跟分号；
- 值类型：带引号字符串（保留原文去引号）/ 数字（整型字面量→int、
  其余→float）/ 词（true/false→bool，其余保留字符串）；
- 注释：``/* … */``（C 风格块注释，字符串字面量内不剥离）；
- 行连续：行尾反斜杠 ``\\``（Liberty values 表多行惯例）按空白跳过。

本内核不做 Liberty 全语义（CCS/ECSM 深表、check_timing 约束建模等
按需扩展）；未识别组/属性一律原样保留（attrs 透传+groups 子组表），
消费端可继续下钻——结构化输出只钉 NLDM 主面：

- library(name/file_version/单位属性)、cell(area)、pin(direction/
  function/capacitance)、timing(related_pin/timing_sense + 四张 NLDM
  查找表)、lu_table_template、operating_conditions；
- 功率面：pin 级 internal_power（rise_power/fall_power/power 查找表）+
  cell 级 leakage_power（values/value+when）与 cell_leakage_power。

查找表形态（NLDM 标准两维）：index_1（input transition）× index_2
（output load）→ values 矩阵；一维表（仅 index_1）与零维表（单值）
按 dims 键归一。表组可引用 lu_table_template（组名即模板名）——
index_1/index_2 缺省时从模板继承（values 恒为本地）。

错误：语法/形状违规抛 :class:`LibertyParseError`（ValueError 子类，
带行号定位）——服务层转 error 信封，CLI 层 exit 1。零 IO（纯文本进
出）、零依赖、确定性（同输入同输出）。

不设 ``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json
——hfss_run_report_service/plot_style 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any

#: timing 组内的四张 NLDM 查找表标准键（结构化输出 schema 钉）
LIBERTY_TIMING_TABLES = (
    "cell_rise",
    "cell_fall",
    "rise_transition",
    "fall_transition",
)

#: internal_power 组内的功率查找表键
LIBERTY_POWER_TABLES = ("rise_power", "fall_power", "power")

_PUNCT = frozenset("(){}:;,")

_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_INT_RE = re.compile(r"[+-]?\d+")
_INF_RE = re.compile(r"[+-]?inf")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_ROW_SPLIT_RE = re.compile(r"[, \t\r\n]+")


class LibertyParseError(ValueError):
    """Liberty 语法/结构/查找表形状违规（ValueError 子类，带行号文本）。"""


#: 解析输出 schema 版本（键集/字段形状变更时升位）。解析产物为组树
# （非 dict），自描述键由 service 信封携带（skill_service 同款先例）。
PARSER_SCHEMA_VERSION = "1.0"


# ─── 词法（tokenizer）───────────────────────────────────────────────────────
# Token = (kind, value, line)；kind ∈ {"word", "number", "string", "punct"}。


def _make_number(text: str) -> int | float:
    if _INT_RE.fullmatch(text):
        return int(text)
    if _INF_RE.fullmatch(text):
        return float(text)  # ±inf → float 字面量
    return float(text)


def _tokenize(text: str) -> list[tuple[str, Any, int]]:
    tokens: list[tuple[str, Any, int]] = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif c == "\\" and text[i + 1 : i + 2] in ("\n", ""):
            # 行尾反斜杠=行连续（Liberty values 表惯例）；文件尾孤立反斜杠同按空白
            if text[i + 1 : i + 2] == "\n":
                line += 1
                i += 2
            else:
                i += 1
        elif c == "/" and text[i + 1 : i + 2] == "*":
            end = text.find("*/", i + 2)
            if end < 0:
                raise LibertyParseError(f"第 {line} 行：块注释未闭合（缺 */）")
            line += text.count("\n", i, end)
            i = end + 2
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                ch = text[j]
                if ch == "\\" and j + 1 < n:  # 引号内转义按原文保留（不解释）
                    buf.append(text[j : j + 2])
                    j += 2
                elif ch == '"':
                    break
                else:
                    if ch == "\n":
                        line += 1
                    buf.append(ch)
                    j += 1
            if j >= n:
                raise LibertyParseError(f"第 {line} 行：字符串字面量未闭合")
            tokens.append(("string", "".join(buf), line))
            i = j + 1
        elif c in _PUNCT:
            tokens.append(("punct", c, line))
            i += 1
        else:
            m_num = _NUM_RE.match(text, i)
            m_inf = _INF_RE.match(text, i)
            m_word = _WORD_RE.match(text, i)
            # 数字判定必须"带边界"（词首为数字/带符号数字），否则 `1e-3x` 类粘连误判
            if m_num and (c.isdigit() or c == "." or (c in "+-" and i + 1 < n
                                                       and (text[i + 1].isdigit() or text[i + 1] == "."))):
                tok = m_num.group(0)
                tokens.append(("number", _make_number(tok), line))
                i += len(tok)
            elif m_inf and (text[i] in "+-" or text[i : i + 3] == "inf"):
                tok = m_inf.group(0)
                tokens.append(("number", _make_number(tok), line))
                i += len(tok)
            elif m_word:
                tok = m_word.group(0)
                tokens.append(("word", tok, line))
                i += len(tok)
            else:
                raise LibertyParseError(f"第 {line} 行：非法字符 {c!r}")
    return tokens


# ─── 语法（recursive descent）──────────────────────────────────────────────


@dataclass
class LibertyGroup:
    """Liberty 组节点：类型名+名表+属性表+子组表（未识别面原样保留）。

    attrs 值二态：简单属性=标量（str/int/float/bool）；复合属性=token
    列表（str/int/float 混合，字符串已去引号）。消费端用 :meth:`find`
    /:meth:`get` 下钻，无需感知解析细节。
    """

    group_type: str
    names: list[str] = field(default_factory=list)
    line: int = 0
    attrs: dict[str, Any] = field(default_factory=dict)
    groups: list[LibertyGroup] = field(default_factory=list)

    @property
    def name(self) -> str:
        """首个组名（名表为空时空串——``timing () {`` 惯例）。"""
        return self.names[0] if self.names else ""

    def find(self, group_type: str, name: str | None = None) -> list[LibertyGroup]:
        """按组类型（可再加组名）过滤直接子组（保持文档序）。"""
        hits = [g for g in self.groups if g.group_type == group_type]
        if name is not None:
            hits = [g for g in hits if g.name == name]
        return hits

    def first(self, group_type: str, name: str | None = None) -> LibertyGroup | None:
        hits = self.find(group_type, name)
        return hits[0] if hits else None

    def get(self, attr: str, default: Any = None) -> Any:
        """简单属性取值（复合属性返回 token 列表原样）。"""
        return self.attrs.get(attr, default)


class _TokenStream:
    def __init__(self, tokens: list[tuple[str, Any, int]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def peek(self) -> tuple[str, Any, int] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def next(self) -> tuple[str, Any, int]:
        tok = self.peek()
        if tok is None:
            raise LibertyParseError("Liberty 文本提前结束（意外 EOF）")
        self._pos += 1
        return tok

    def exhausted(self) -> bool:
        return self._pos >= len(self._tokens)


def _expect_punct(stream: _TokenStream, which: str, where: str) -> tuple[str, Any, int]:
    tok = stream.next()
    if tok[0] != "punct" or tok[1] != which:
        raise LibertyParseError(f"第 {tok[2]} 行：{where}期望 {which!r}，实际 {tok[1]!r}")
    return tok


def _convert_scalar(kind: str, value: Any) -> Any:
    """简单属性/组名的值归一：词 true/false→bool，其余保型。"""
    if kind == "word" and value in ("true", "false"):
        return value == "true"
    return value


def _parse_paren_args(stream: _TokenStream, where: str) -> list[Any]:
    """``( … )`` 内 token 列表（逗号分隔；字符串去引号，数字保型）。"""
    _expect_punct(stream, "(", where)
    args: list[Any] = []
    while True:
        tok = stream.peek()
        if tok is None:
            raise LibertyParseError(f"{where}：圆括号参数表未闭合（意外 EOF）")
        if tok[0] == "punct" and tok[1] == ")":
            stream.next()
            return args
        if tok[0] == "punct" and tok[1] == ",":
            stream.next()
            continue
        tok = stream.next()
        args.append(tok[1] if tok[0] in ("number", "string") else str(tok[1]))


def _parse_body(stream: _TokenStream, group: LibertyGroup, *, top: bool = False) -> None:
    while True:
        tok = stream.peek()
        if tok is None:
            if top:
                return
            raise LibertyParseError(
                f"第 {group.line} 行：组 {group.group_type!r} 未闭合（缺 }}，意外 EOF）")
        if tok[0] == "punct" and tok[1] == "}":
            stream.next()
            return
        if tok[0] == "punct":
            raise LibertyParseError(f"第 {tok[2]} 行：组体起点期望属性名，实际 {tok[1]!r}")
        stream.next()
        name, wline = str(tok[1]), tok[2]
        nxt = stream.peek()
        if nxt is None:
            raise LibertyParseError(f"第 {wline} 行：属性 {name!r} 后意外 EOF")
        if nxt[0] == "punct" and nxt[1] == ":":
            stream.next()
            val = stream.next()
            if val[0] == "punct":
                raise LibertyParseError(f"第 {val[2]} 行：属性 {name!r} 缺值（直接遇 {val[1]!r}）")
            group.attrs[name] = _convert_scalar(val[0], val[1])
            _expect_punct(stream, ";", f"属性 {name!r}")
        elif nxt[0] == "punct" and nxt[1] == "(":
            args = _parse_paren_args(stream, f"第 {wline} 行 {name!r}")
            closer = stream.peek()
            if closer is not None and closer[0] == "punct" and closer[1] == "{":
                stream.next()
                sub = LibertyGroup(group_type=name, names=[str(a) for a in args], line=wline)
                _parse_body(stream, sub)
                group.groups.append(sub)
            elif closer is not None and closer[0] == "punct" and closer[1] == ";":
                stream.next()
                group.attrs[name] = args  # 复合属性：token 列表原样
            else:
                where = f"第 {closer[2]} 行" if closer is not None else "EOF"
                raise LibertyParseError(
                    f"{where}：{name!r} 参数表后期望 {{ 或 ;，实际 "
                    f"{closer[1] if closer is not None else 'EOF'!r}")
        elif nxt[0] == "punct" and nxt[1] == "{":
            stream.next()
            sub = LibertyGroup(group_type=name, names=[], line=wline)
            _parse_body(stream, sub)
            group.groups.append(sub)
        else:
            raise LibertyParseError(
                f"第 {nxt[2]} 行：{name!r} 后期望 : ( 或 {{，实际 {nxt[1]!r}")


def parse_liberty(text: str) -> LibertyGroup:
    """Liberty 文本 → 根 library 组（非 library 顶层组/多 library 拒收）。"""
    stream = _TokenStream(_tokenize(text))
    root = LibertyGroup(group_type="<root>", line=1)
    _parse_body(stream, root, top=True)  # 顶层 EOF 正常收束；'}' 后余 token 即多余
    libs = root.find("library")
    if not libs:
        raise LibertyParseError("未找到顶层 library 组（Liberty 文件必须含唯一 library）")
    if len(libs) > 1:
        raise LibertyParseError(f"顶层 library 组多于一个（{len(libs)} 个）——单文件单库口径")
    stray = [g for g in root.groups if g.group_type != "library"]
    if stray:
        raise LibertyParseError(
            f"顶层存在 library 之外的组：{', '.join(g.group_type for g in stray)}")
    if not stream.exhausted():
        tok = stream.next()
        raise LibertyParseError(f"第 {tok[2]} 行：顶层多余 token {tok[1]!r}（疑似多余 '}}'）")
    return libs[0]


# ─── 查找表提取与插值（NLDM）───────────────────────────────────────────────


def _numbers_from_tokens(tokens: Any, where: str) -> list[float]:
    """复合属性 token 列表 → 数字列表（引号内逗号分隔串逐项 float）。"""
    if tokens is None:
        return []
    if isinstance(tokens, (int, float, str)):
        tokens = [tokens]
    out: list[float] = []
    for tok in tokens:
        if isinstance(tok, (int, float)):
            out.append(float(tok))
            continue
        for part in _ROW_SPLIT_RE.split(str(tok)):
            if not part:
                continue
            try:
                out.append(float(part))
            except ValueError as exc:
                raise LibertyParseError(f"{where}：非数字索引值 {part!r}") from exc
    return out


def _table_rows(tokens: Any, where: str) -> list[list[float]]:
    """values 复合属性 → 矩阵（每个引号串=一行；裸数字=单值行）。"""
    if tokens is None:
        raise LibertyParseError(f"{where}：缺 values 属性")
    rows: list[list[float]] = []
    for tok in tokens:
        if isinstance(tok, (int, float)):
            rows.append([float(tok)])
            continue
        row: list[float] = []
        for part in _ROW_SPLIT_RE.split(str(tok)):
            if not part:
                continue
            try:
                row.append(float(part))
            except ValueError as exc:
                raise LibertyParseError(f"{where}：values 行含非数字 {part!r}") from exc
        if row:
            rows.append(row)
    if not rows:
        raise LibertyParseError(f"{where}：values 为空")
    return rows


def extract_table(
    group: LibertyGroup, templates: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """查找表组（cell_rise 等）→ 结构化表（模板继承 index_*）。

    返回 ``{"index_1", "index_2"(2 维才有), "values"(矩阵), "template",
    "dims"(0/1/2)}``。形状校验严格：行数=len(index_1)、列数=len(index_2)
    （2 维）；1 维接受"单行 N 值"或"N 行单值"两种写法并归一为单行。
    """
    where = f"查找表 {group.group_type!r}（第 {group.line} 行）"
    tpl_name = group.name or None
    tpl = (templates or {}).get(tpl_name) if tpl_name else None
    idx1 = _numbers_from_tokens(group.attrs.get("index_1"), where)
    idx2 = _numbers_from_tokens(group.attrs.get("index_2"), where)
    if not idx1 and tpl is not None:
        idx1 = list(tpl.get("index_1") or [])
    if not idx2 and tpl is not None:
        idx2 = list(tpl.get("index_2") or [])
    rows = _table_rows(group.attrs.get("values"), where)
    dims = 2 if (idx1 and idx2) else (1 if (idx1 or idx2) else 0)
    if dims == 2:
        if len(rows) != len(idx1) or any(len(r) != len(idx2) for r in rows):
            raise LibertyParseError(
                f"{where}：values 形状 {len(rows)}×{len(rows[0])} "
                f"与 index_1×index_2 {len(idx1)}×{len(idx2)} 不符")
        matrix = rows
        out: dict[str, Any] = {
            "index_1": idx1, "index_2": idx2, "values": matrix,
            "template": tpl_name, "dims": dims,
        }
        return out
    if dims == 1:
        axis_idx = idx1 or idx2
        axis = len(axis_idx)
        if len(rows) == 1 and len(rows[0]) == axis:
            matrix = [list(rows[0])]
        elif len(rows) == axis and all(len(r) == 1 for r in rows):
            matrix = [[r[0] for r in rows]]
        else:
            raise LibertyParseError(
                f"{where}：一维表 values 行列 {len(rows)}×{len(rows[0])} "
                f"与索引长度 {axis} 不符")
        return {"index_1": axis_idx, "values": matrix,
                "template": tpl_name, "dims": dims}
    if len(rows) != 1 or len(rows[0]) != 1:
        raise LibertyParseError(
            f"{where}：零维表（无索引）values 须为单值，实际 "
            f"{len(rows)}×{len(rows[0])}")
    return {"values": rows, "template": tpl_name, "dims": 0}


def _bracket(index: list[float], x: float) -> tuple[int, int, float]:
    """夹取后的下标区间与分数位置（len==1 退化零区间）。"""
    if len(index) == 1:
        return 0, 0, 0.0
    pos = bisect_right(index, x) - 1
    pos = max(0, min(pos, len(index) - 2))
    lo, hi = index[pos], index[pos + 1]
    frac = 0.0 if hi == lo else (x - lo) / (hi - lo)
    return pos, pos + 1, frac


def lookup_table(table: dict[str, Any], x1: float, x2: float | None = None) -> float:
    """NLDM 查找表双线性插值（越界按边界夹取——NLDM 惯例）。

    dims=2：index_1×index_2 双线性；dims=1：index_1 线性；dims=0：单值
    （x1/x2 忽略）。声明式确定性公式（铁律 7：数字只出自数据+公式）。
    """
    idx1 = table.get("index_1") or []
    vals = table["values"]
    dims = int(table.get("dims", 2 if (idx1 and table.get("index_2")) else 1))
    if dims == 0:
        return float(vals[0][0])
    if not idx1:
        raise ValueError("lookup_table：缺 index_1 索引")
    if x1 < idx1[0]:
        x1 = idx1[0]
    elif x1 > idx1[-1]:
        x1 = idx1[-1]
    if dims == 1:
        i0, i1, f = _bracket(idx1, x1)
        row = vals[0]
        return float(row[i0] * (1.0 - f) + row[i1] * f)
    idx2 = table.get("index_2") or []
    if x2 is None or not idx2:
        raise ValueError("lookup_table：二维表需要 x2 与 index_2")
    if x2 < idx2[0]:
        x2 = idx2[0]
    elif x2 > idx2[-1]:
        x2 = idx2[-1]
    i0, i1, fi = _bracket(idx1, x1)
    j0, j1, fj = _bracket(idx2, x2)
    v00, v01 = vals[i0][j0], vals[i0][j1]
    v10, v11 = vals[i1][j0], vals[i1][j1]
    top = v00 * (1.0 - fj) + v01 * fj
    bot = v10 * (1.0 - fj) + v11 * fj
    return float(top * (1.0 - fi) + bot * fi)


# ─── 结构化输出（NLDM 主面 schema）─────────────────────────────────────────


def _simple_attrs(group: LibertyGroup) -> dict[str, Any]:
    """纯标量属性透传（复合属性列表原样保留——消费端自辨）。"""
    return dict(group.attrs)


def _timing_key(timing: dict[str, dict[str, Any]], related_pin: str,
                timing_type: str | None) -> str:
    """timing 键：related_pin；同 related_pin 多组以 @timing_type 消歧。"""
    if related_pin not in timing:
        return related_pin
    base = f"{related_pin}@{timing_type or 'unnamed'}"
    if base not in timing:
        return base
    k = 2
    while f"{base}#{k}" in timing:
        k += 1
    return f"{base}#{k}"


def _extract_timing_groups(pin: LibertyGroup,
                           templates: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    timing: dict[str, dict[str, Any]] = {}
    for tg in pin.find("timing"):
        related_pin = str(tg.get("related_pin", "") or "")
        sense = tg.get("timing_sense")
        ttype = tg.get("timing_type")
        entry: dict[str, Any] = {
            "related_pin": related_pin,
            "timing_sense": sense if isinstance(sense, str) else None,
            "timing_type": ttype if isinstance(ttype, str) else None,
            "when": tg.get("when") if isinstance(tg.get("when"), str) else None,
        }
        for tname in LIBERTY_TIMING_TABLES:
            tgrp = tg.first(tname)
            entry[tname] = extract_table(tgrp, templates) if tgrp is not None else None
        key = _timing_key(timing, related_pin, entry["timing_type"])
        timing[key] = entry
    return timing


def _extract_internal_power(pin: LibertyGroup,
                            templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ip in pin.find("internal_power"):
        entry: dict[str, Any] = {
            "related_pin": ip.get("related_pin") if isinstance(ip.get("related_pin"), str) else None,
            "when": ip.get("when") if isinstance(ip.get("when"), str) else None,
        }
        for tname in LIBERTY_POWER_TABLES:
            tgrp = ip.first(tname)
            entry[tname] = extract_table(tgrp, templates) if tgrp is not None else None
        out.append(entry)
    return out


def _leakage_value(cell: LibertyGroup) -> float | None:
    raw = cell.get("cell_leakage_power")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _extract_leakage_groups(cell: LibertyGroup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lg in cell.find("leakage_power"):
        when = lg.get("when") if isinstance(lg.get("when"), str) else None
        value: float | None = None
        raw = lg.attrs.get("value")
        if isinstance(raw, (int, float)):
            value = float(raw)
        else:
            nums = _numbers_from_tokens(lg.attrs.get("values"), "leakage_power.values")
            if nums:
                value = nums[0]
        out.append({"value": value, "when": when, "attrs": _simple_attrs(lg)})
    return out


def _extract_cell(cell: LibertyGroup,
                  templates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    area = cell.get("area")
    pins: dict[str, dict[str, Any]] = {}
    for pin in cell.find("pin"):
        cap = pin.get("capacitance")
        max_cap = pin.get("max_capacitance")
        entry: dict[str, Any] = {
            "direction": pin.get("direction") if isinstance(pin.get("direction"), str) else None,
            "function": pin.get("function") if isinstance(pin.get("function"), str) else None,
            "capacitance": float(cap) if isinstance(cap, (int, float)) else None,
            "max_capacitance": float(max_cap) if isinstance(max_cap, (int, float)) else None,
            "clock": bool(pin.get("clock")) if isinstance(pin.get("clock"), bool) else None,
            "attrs": _simple_attrs(pin),
            "timing": _extract_timing_groups(pin, templates),
            "internal_power": _extract_internal_power(pin, templates),
        }
        pins[pin.name] = entry
    return {
        "area": float(area) if isinstance(area, (int, float)) else None,
        "attrs": _simple_attrs(cell),
        "pins": pins,
        "cell_leakage_power": _leakage_value(cell),
        "leakage_power": _extract_leakage_groups(cell),
    }


def _extract_templates(library: LibertyGroup) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for tpl in library.find("lu_table_template"):
        templates[tpl.name] = {
            "variable_1": tpl.get("variable_1") if isinstance(tpl.get("variable_1"), str) else None,
            "variable_2": tpl.get("variable_2") if isinstance(tpl.get("variable_2"), str) else None,
            "index_1": _numbers_from_tokens(tpl.attrs.get("index_1"), f"模板 {tpl.name!r}.index_1"),
            "index_2": _numbers_from_tokens(tpl.attrs.get("index_2"), f"模板 {tpl.name!r}.index_2"),
        }
    return templates


def _extract_operating_conditions(library: LibertyGroup) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for oc in library.find("operating_conditions"):
        out[oc.name] = _simple_attrs(oc)
    return out


_UNIT_KEYS = (
    "time_unit", "voltage_unit", "current_unit", "leakage_power_unit",
    "pulling_resistance_unit", "capacitive_load_unit",
    "nom_process", "nom_temperature", "nom_voltage",
    "default_max_transition", "delay_model",
)


def extract_library(
    library: LibertyGroup, *, include_timing: bool = True, include_power: bool = True
) -> dict[str, Any]:
    """library 组 → 结构化输出（NLDM 主面 schema；compact 开关可裁面）。

    ``include_timing=False`` 剪去 pin 的 timing 表；``include_power=False``
    剪去 internal_power/leakage_power 面（pin 元数据与计数不受影响）。
    """
    attrs = _simple_attrs(library)
    templates = _extract_templates(library)
    file_version = attrs.get("file_version")
    if file_version is None:
        file_version = attrs.get("revision")
    cells: dict[str, dict[str, Any]] = {}
    for cell in library.find("cell"):
        entry = _extract_cell(cell, templates)
        if not include_timing:
            for pin in entry["pins"].values():
                pin.pop("timing", None)
        if not include_power:
            for pin in entry["pins"].values():
                pin.pop("internal_power", None)
            entry.pop("leakage_power", None)
            entry.pop("cell_leakage_power", None)
        cells[cell.name] = entry
    return {
        "library": library.name,
        "file_version": file_version,
        "units": {k: attrs[k] for k in _UNIT_KEYS if k in attrs},
        "attrs": attrs,
        "cells": cells,
        "operating_conditions": _extract_operating_conditions(library),
        "lu_templates": templates,
    }
