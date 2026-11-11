"""CITI（Common Instrument Transfer Intermediate / CITIfile）结构化解析器
（aurora_q 席位 Q-X35；纯 stdlib 叶子，零业务依赖）。

职责（铁律 7：数值只在确定性内核——本模块 = 确定性文本解析内核，解码
失败的值一律保留原文（raw）并如实标注，绝不编造数值）：

把 HP/Agilent/Keysight 测试仪器的 CITIfile（.cti）文本包解析为结构化
对象树：包头（header 关键字）+ 变量/常量声明 + 数据段（segments）。

格式口径（三层出处，逐层落地）：
1. Keysight PLTS / Ansys Circuit 官方文档：CITIFILE 版本行（首行必判，
   缺=非 CITI 文件报错）、NAME、VAR、CONST/CONSTANT、
   VAR_LIST_BEGIN/END、SEG_LIST_BEGIN/SEG start stop count/SEG_LIST_END、
   DATA name fmt（RI/MAGANGLE/DBANGLE ASCII 对）+ BEGIN/END 数据块、
   COMMENT/``!`` 注释、``#DEV KW val`` 设备关键字。SEG_LIST 线性段频率
   合成公式 F(n) = start + (n-1)*(stop-start)/(count-1)（Ansys Circuit
   文档口径）。
2. 本席任务书契约的 IC-CAP/ADS 扩展包头关键字：CVG VERSION（替代版本
   行形态）、RAWDATE、OUTPERHA、AUTOLOAD、INSPFILE——统一进 header
   字典（首 token 关键字 → 余串值），未知关键字同法收编不丢真。
3. 数据段二进制扩展（任务书契约）：``SEG <格式串> <记录数>`` +
   BEGIN/END，格式串为下划线分隔的格式字母（A/B/C/D/E）：
   A=%16E（16 hex 位 double，IEEE-754 binary64 位型，大端字节序——HP
   68000 系谱惯例，本版固定大端）、B=%8E（8 hex 位 float，binary32）、
   C=%10F（10 hex 位 complex）、D=%6E（6 hex 位 float）、E=ASCII float。
   以及 BEGIN_MODE/END_MODE 块内 ``MODE <字母> [c格式]`` 逐记录数据
   （IC-CAP 模式块形态）。

诚实语义（#122 族）：
- C=%10F（40 bit）与 D=%6E（24 bit）**没有 IEEE-754 标准位型映射**，
  公开规范不可查——本解析器接受并保留其结构（格式字母/原始 hex 串/
  记录数），decode_status="unsupported_width" 如实登记，**不解码出
  任何数值**（宁 raw 不编数）；A/B/E 精确解码（struct 位型往返逐位
  相等，测试钉住）。
- 布局歧义（SEG 每记录字段数与声明的 dependent 数对不上）→
  decode_status="layout_ambiguous"，values=None + raw 保留，不猜。
- BEGIN 无 END（文件截断）→ warning + 已收记录如实保留（截断态），
  不假装完整。
- 非记录杂行 → 逐行 warning（截断原文），零静默丢弃。

结构化输出（任务书口径）::

    package_to_dict(pkg) -> {
      "header": {关键字: 值, ...},          # RAWDATE/OUTPERHA/AUTOLOAD/...
      "version": "A.01.01", "version_keyword": "CITIFILE"|"CVG VERSION",
      "name": 包名, "constants": {名: 原值串},
      "variables": [{name, fmt, occurrences, values, n_values}],
      "segments": [{
        "type": "DATA"|"SEG"|"MODE",
        "var_name": "S[1,1]", "var_unit": str|None,
        "format": 声明的格式 token（RI/A_B/...）,
        "independent_var": {"name","unit","values"},
        "dependent_vars": [{"name","unit","values","value_kind"}],
        "decode_status": "ok"|"unsupported_width"|"layout_ambiguous"|...,
        "n_records":..., "n_records_expected":...,
        "raw_records": 仅 decode_status != "ok" 时带,
        "warnings": [...],
      }],
      "metadata": {n_packages, package_index, n_lines, warnings, ...},
    }

skrf 桥接不在本模块（core 零依赖纪律）：service/citi_service.py 消费
本模块结构化输出组装 skrf.Network（数据段格式匹配时才可桥，条件不满足
走 skipped 信封如实声明）。
"""

from __future__ import annotations

import cmath
import struct
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "CITI_FORMAT_WIDTHS",
    "KNOWN_HEADER_KEYS",
    "SUPPORTED_FORMAT_LETTERS",
    "CitiDecodeError",
    "CitiPackage",
    "CitiParseError",
    "CitiSegment",
    "CitiVar",
    "DependentVar",
    "IndependentVar",
    "decode_citi_field",
    "decode_hex_double",
    "decode_hex_float",
    "package_to_dict",
    "parse_citi_file",
    "parse_citi_text",
    "segment_to_dict",
]

#: 格式字母 → （任务书契约格式描述, 每 hex 位宽）；E=ASCII 不占本表。
CITI_FORMAT_WIDTHS: dict[str, tuple[str, int]] = {
    "A": ("%16E", 16),
    "B": ("%8E", 8),
    "C": ("%10F", 10),
    "D": ("%6E", 6),
}

#: 支持的格式字母全集（E=ASCII float）。
SUPPORTED_FORMAT_LETTERS = "ABCDE"

#: 官方包头关键字（PLTS/Ansys 文档 + 任务书扩展；未知关键字同法收编）。
KNOWN_HEADER_KEYS = (
    "RAWDATE",
    "INSPDATE",
    "INSPFILE",
    "OUTPERHA",
    "AUTOLOAD",
)


class CitiParseError(ValueError):
    """CITI 包结构级错误（缺版本行/不可读文件）。"""


#: 解析输出 schema 版本（键集/字段形状变更时升位）。解析产物为包列表
# （非 dict），自描述键由 service 信封携带（skill_service 同款先例）。
PARSER_SCHEMA_VERSION = "1.0"


class CitiDecodeError(ValueError):
    """单值解码错误（位宽/字符集不符/不支持宽度）。"""


# ────────────────────────── 单值解码（精确/诚实两态） ──────────────────────────


def decode_hex_double(text: str) -> float:
    """格式 A：%16E——16 hex 位 = IEEE-754 binary64 位型（大端）→ float。

    位宽/字符集不符抛 :class:`CitiDecodeError`（不猜不改）。
    """
    token = text.strip()
    if len(token) != 16:
        raise CitiDecodeError(
            f"格式 A 需 16 hex 位，实得 {len(token)}: {token!r}")
    try:
        raw = bytes.fromhex(token)
    except ValueError as exc:
        raise CitiDecodeError(f"格式 A 非 hex 字符: {token!r}") from exc
    return struct.unpack(">d", raw)[0]


def decode_hex_float(text: str) -> float:
    """格式 B：%8E——8 hex 位 = IEEE-754 binary32 位型（大端）→ float。

    返回 Python float（双精度承载；位型本身是 f32，往返测试按
    ``struct.pack('>f')`` 量化后比对，逐位精确）。
    """
    token = text.strip()
    if len(token) != 8:
        raise CitiDecodeError(
            f"格式 B 需 8 hex 位，实得 {len(token)}: {token!r}")
    try:
        raw = bytes.fromhex(token)
    except ValueError as exc:
        raise CitiDecodeError(f"格式 B 非 hex 字符: {token!r}") from exc
    return struct.unpack(">f", raw)[0]


def decode_citi_field(letter: str, text: str) -> float:
    """按格式字母解码单字段值。

    A/B/E 精确解码；C/D 位宽无 IEEE-754 标准映射 → :class:`CitiDecodeError`
    （message 含 ``unsupported_width`` 标记与格式描述——上层据此走
    raw 保留路径，绝不编造数值）。
    """
    letter = letter.strip().upper()
    if letter == "E":
        try:
            return float(text)
        except ValueError as exc:
            raise CitiDecodeError(
                f"格式 E ASCII float 解析失败: {text!r}") from exc
    if letter == "A":
        return decode_hex_double(text)
    if letter == "B":
        return decode_hex_float(text)
    if letter in ("C", "D"):
        desc, width = CITI_FORMAT_WIDTHS[letter]
        raise CitiDecodeError(
            f"unsupported_width: 格式 {letter}（{desc}，{width} hex 位）"
            "无 IEEE-754 标准位型映射，不解码数值（raw 保留）")
    raise CitiDecodeError(f"未知 CITI 格式字母: {letter!r}")


# ────────────────────────── 结构化对象树 ──────────────────────────


@dataclass
class CitiVar:
    """VAR 声明（独立变量/参数）：名称 + 值表格式 + 出现次数 + 值列表。"""

    name: str
    fmt: str
    occurrences: int
    values: list[float] | None = None


@dataclass
class IndependentVar:
    """数据段的独立变量（INDEPENDENT 声明 + 已解析值）。"""

    name: str
    unit: str | None
    values: list[float] | None


@dataclass
class DependentVar:
    """数据段的因变量（DEPENDENT/DATA 声明 + 解码值）。

    values 元素为 float 或 complex（RI/MAGANGLE/DBANGLE 对/打包 RI 对）；
    解码失败时 None（raw 走段的 raw_records 保留）。
    """

    name: str
    unit: str | None
    values: list[float] | list[complex] | None
    value_kind: str = "none"  # "float" | "complex" | "none"


@dataclass
class CitiSegment:
    """一个数据段（DATA 块 / SEG 块 / MODE 块归一后的结构）。"""

    type: str                       # "DATA" | "SEG" | "MODE"
    var_name: str                   # 主数据名（单 DATA 时=DATA 名；SEG 时=首 dependent 名）
    var_unit: str | None
    format: str                     # 声明格式 token 原文（RI / MAGANGLE / A_B / A ...）
    independent_var: IndependentVar | None
    dependent_vars: list[DependentVar] = field(default_factory=list)
    decode_status: str = "ok"
    n_records: int = 0
    n_records_expected: int | None = None
    raw_records: list[str] | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CitiPackage:
    """一个 CITIfile 包（版本行起，到下一版本行或文件尾）。"""

    version: str | None = None
    version_keyword: str | None = None   # "CITIFILE" | "CVG VERSION"
    name: str | None = None
    header: dict[str, str] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)
    variables: list[CitiVar] = field(default_factory=list)
    segments: list[CitiSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_lines: int = 0
    comments: list[str] = field(default_factory=list)

    def find_variable_values(self, *names: str) -> list[float] | None:
        """按名（大小写不敏感）找 VAR 值列表；多候选取首个命中。"""
        lowered = {n.lower() for n in names if n}
        for var in self.variables:
            if var.name.lower() in lowered and var.values is not None:
                return var.values
        return None


# ────────────────────────── 行解析状态机 ──────────────────────────

_ASCII_DATA_FORMATS = ("RI", "MAGANGLE", "DBANGLE")


def _split_fields(line: str) -> list[str]:
    """数据记录行 → 字段（逗号或空白分隔）。"""
    if "," in line:
        return [tok for tok in (t.strip() for t in line.split(",")) if tok]
    return line.split()


def _try_float(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


def _try_int(token: str) -> int | None:
    try:
        return int(token)
    except ValueError:
        return None


def _indep_for(pkg: CitiPackage, indep_name: str | None,
               indep_unit: str | None, indep_count: int | None,
               seg_list: tuple[float, float, int] | None,
               warnings: list[str]) -> IndependentVar | None:
    """段独立变量归一：INDEPENDENT 声明 + 值解析（VAR 表 > SEG_LIST 合成）。

    值不可得时 values=None + warning（不虚构频率轴）。
    """
    if indep_name is None:
        return None
    values: list[float] | None = pkg.find_variable_values(indep_name, "freq")
    if values is None and seg_list is not None:
        start, stop, count = seg_list
        if indep_count is None or indep_count == count:
            step = (stop - start) / (count - 1) if count > 1 else 0.0
            values = [start + n * step for n in range(count)]
        else:
            warnings.append(
                f"SEG_LIST 点数 {count} 与 INDEPENDENT {indep_name} 点数 "
                f"{indep_count} 不一致，独立变量值不合成")
    if values is None:
        warnings.append(
            f"独立变量 {indep_name} 无值表（VAR_LIST/SEG_LIST 均缺），"
            "values=None 如实保留")
    return IndependentVar(name=indep_name, unit=indep_unit, values=values)


def _decode_ascii_records(
    decl_name: str, decl_unit: str | None, fmt: str,
    records: list[str], warnings: list[str],
) -> tuple[DependentVar, str]:
    """DATA/DEPENDENT ASCII 记录块解码（RI/MAGANGLE/DBANGLE）。

    返回 (dependent, decode_status)。未知格式 → 状态
    ``ascii_unknown_format``，值不产（raw 由调用方保留）。
    MAGANGLE/DBANGLE 幅角换算同 skrf 口径（mag*exp(j*deg)；
    dB=20log10 幅值口径）。
    """
    fmt_u = fmt.strip().upper()
    values: list[float] | list[complex] | None
    if fmt_u in _ASCII_DATA_FORMATS:
        values = []
        for line_no, rec in enumerate(records, 1):
            fields = _split_fields(rec)
            if len(fields) != 2:
                warnings.append(
                    f"{decl_name} 记录 {line_no} 需 2 字段（{fmt_u}），"
                    f"实得 {len(fields)}，该行丢弃")
                continue
            a, b = _try_float(fields[0]), _try_float(fields[1])
            if a is None or b is None:
                warnings.append(
                    f"{decl_name} 记录 {line_no} 字段非数值: {rec!r}")
                continue
            if fmt_u == "RI":
                values.append(complex(a, b))
            else:  # MAGANGLE / DBANGLE
                mag = a if fmt_u == "MAGANGLE" else 10.0 ** (a / 20.0)
                values.append(cmath.rect(mag, cmath.pi * b / 180.0))
        kind = "complex"
    else:
        values = None
        kind = "none"
        warnings.append(
            f"{decl_name} 声明格式 {fmt!r} 不在 RI/MAGANGLE/DBANGLE 内，"
            "ASCII 块不解码（raw 保留）")
    status = "ok" if values is not None else "ascii_unknown_format"
    dep = DependentVar(name=decl_name, unit=decl_unit, values=values,
                       value_kind=kind)
    return dep, status


def _decode_packed_records(
    letters: list[str], records: list[str], dependents: list[DependentVar],
    fmt_token: str, warnings: list[str],
) -> tuple[list[DependentVar], str, list[str] | None]:
    """SEG/MODE 打包记录解码（格式字母逐字段）。

    返回 (dependents, decode_status, raw_records_or_None)。任何字段解码
    失败（含 C/D unsupported_width）→ 全段走 raw 保留（不产数值——部分
    解码的部分段会让下游误当完整数值段消费）。
    布局分配：F 字段 × K 因变量——F==K 列分配（float），F==2K 为 RI 对
    （complex），其余 layout_ambiguous（不猜）。
    """
    n_fields = len(letters)
    decoded_rows: list[list[float]] = []
    bad: str | None = None
    for line_no, rec in enumerate(records, 1):
        fields = _split_fields(rec)
        if len(fields) != n_fields:
            warnings.append(
                f"记录 {line_no} 需 {n_fields} 字段（格式 {fmt_token}），"
                f"实得 {len(fields)}")
            bad = bad or "field_count"
            continue
        row: list[float] = []
        for letter, tok in zip(letters, fields, strict=True):
            try:
                row.append(decode_citi_field(letter, tok))
            except CitiDecodeError as exc:
                warnings.append(f"记录 {line_no} 字段解码失败: {exc}")
                bad = ("unsupported_width" if "unsupported_width"
                       in str(exc) else "decode_error")
                break
        else:
            decoded_rows.append(row)
    if bad is not None:
        status = bad if bad == "unsupported_width" else "decode_error"
        return dependents, status, list(records)
    n_dep = len(dependents)
    if n_dep == 0:
        warnings.append("段无 DEPENDENT/DATA 声明，记录仅 raw 保留")
        return dependents, "no_dependent_declared", list(records)
    if n_fields == n_dep:
        for idx, dep in enumerate(dependents):
            dep.values = [row[idx] for row in decoded_rows]
            dep.value_kind = "float"
        return dependents, "ok", None
    if n_fields == 2 * n_dep and n_fields >= 2:
        for idx, dep in enumerate(dependents):
            dep.values = [
                complex(row[2 * idx], row[2 * idx + 1]) for row in decoded_rows]
            dep.value_kind = "complex"
        return dependents, "ok", None
    warnings.append(
        f"布局歧义：每记录 {n_fields} 字段对 {n_dep} 个因变量无法唯一分配"
        "（既非 F==K 亦非 F==2K），values=None + raw 保留")
    return dependents, "layout_ambiguous", list(records)


class _Pending:
    """包内解析游标：待消费声明与收集态。"""

    def __init__(self) -> None:
        self.seg_list_open = False
        self.seg_list: tuple[float, float, int] | None = None
        self.mode_open = False
        self.mode_letter: str | None = None
        self.mode_cformat: str | None = None
        self.pending_data: tuple[str, str | None, str] | None = None
        self.pending_dependents: list[tuple[str, str | None, str]] = []
        self.pending_seg: str | None = None
        self.pending_seg_count: int | None = None
        self.collecting: str | None = None      # None | "values" | "records"
        self.collect_is_data = False
        self.collected: list[str] = []


def _flush_mode_records(pkg: CitiPackage, cur: _Pending,
                        indep: IndependentVar | None) -> None:
    """把 MODE 在收记录物化成 MODE 段（END/换 MODE/END_MODE/截断共用）。"""
    letters = [cur.mode_letter] if cur.mode_letter else []
    deps = [DependentVar(name=n, unit=u, values=None, value_kind="none")
            for (n, u, _f) in cur.pending_dependents]
    deps, status, rawrec = _decode_packed_records(
        letters, cur.collected, deps,
        cur.mode_cformat or cur.mode_letter or "?", pkg.warnings)
    pkg.segments.append(CitiSegment(
        type="MODE",
        var_name=deps[0].name if deps else "(unknown)",
        var_unit=deps[0].unit if deps else None,
        format=cur.mode_cformat or cur.mode_letter or "?",
        independent_var=indep, dependent_vars=deps,
        decode_status=status, n_records=len(cur.collected),
        raw_records=rawrec))
    cur.mode_letter = None
    cur.mode_cformat = None
    cur.pending_dependents = []
    cur.collected = []


def _flush_data_block(pkg: CitiPackage, cur: _Pending,
                      indep: IndependentVar | None) -> None:
    """把已收记录/值表按当前待消费声明物化（BEGIN...END 收口共用）。"""
    records = cur.collected
    if cur.collecting == "values":
        if pkg.variables:
            vals = [_try_float(t.strip()) for t in records]
            if any(v is None for v in vals):
                pkg.warnings.append(
                    f"VAR {pkg.variables[-1].name} 值表含非数值行，整表弃解")
            else:
                pkg.variables[-1].values = [float(v) for v in vals]
        cur.collected = []
        cur.collecting = None
        cur.collect_is_data = False
        return
    if cur.collect_is_data and cur.pending_seg is not None:
        letters = [c for c in cur.pending_seg if c != "_"]
        bad = [c for c in letters if c not in SUPPORTED_FORMAT_LETTERS]
        if bad:
            pkg.warnings.append(
                f"SEG 格式串含未知字母 {bad}，段不解码（raw 保留）")
            pkg.segments.append(CitiSegment(
                type="SEG", var_name="(unknown)", var_unit=None,
                format=cur.pending_seg, independent_var=indep,
                dependent_vars=[], decode_status="unknown_format_letter",
                n_records=len(records),
                n_records_expected=cur.pending_seg_count,
                raw_records=list(records)))
        else:
            deps = [DependentVar(name=n, unit=u, values=None,
                                 value_kind="none")
                    for (n, u, _f) in cur.pending_dependents]
            deps, status, raw = _decode_packed_records(
                letters, records, deps, cur.pending_seg, pkg.warnings)
            seg = CitiSegment(
                type="SEG",
                var_name=deps[0].name if deps else "(unknown)",
                var_unit=deps[0].unit if deps else None,
                format=cur.pending_seg, independent_var=indep,
                dependent_vars=deps, decode_status=status,
                n_records=len(records),
                n_records_expected=cur.pending_seg_count,
                raw_records=raw)
            if (cur.pending_seg_count is not None
                    and len(records) != cur.pending_seg_count):
                seg.warnings.append(
                    f"记录数 {len(records)} 与 SEG 声明 "
                    f"{cur.pending_seg_count} 不一致，如实按实收数处理")
            pkg.segments.append(seg)
    elif cur.pending_data is not None:
        name, unit, fmt = cur.pending_data
        dep, status = _decode_ascii_records(name, unit, fmt, records,
                                            pkg.warnings)
        pkg.segments.append(CitiSegment(
            type="DATA", var_name=name, var_unit=unit, format=fmt,
            independent_var=indep, dependent_vars=[dep],
            decode_status=status, n_records=len(records),
            raw_records=(list(records) if status != "ok" else None)))
    elif cur.pending_dependents:
        # DEPENDENT 声明后直接 BEGIN（无 SEG 打包头）——ASCII 块形态
        name, unit, fmt = cur.pending_dependents[0]
        dep, status = _decode_ascii_records(name, unit, fmt, records,
                                            pkg.warnings)
        pkg.segments.append(CitiSegment(
            type="DATA", var_name=name, var_unit=unit, format=fmt,
            independent_var=indep, dependent_vars=[dep],
            decode_status=status, n_records=len(records),
            raw_records=(list(records) if status != "ok" else None)))
    cur.collected = []
    cur.collecting = None
    cur.collect_is_data = False
    cur.pending_data = None
    cur.pending_dependents = []
    cur.pending_seg = None
    cur.pending_seg_count = None


def _close_collecting(pkg: CitiPackage, cur: _Pending,
                      indep: IndependentVar | None, *,
                      warn: str | None) -> None:
    """收口当前收集块（records/values → 段或值表；warn=截断类告警语义）。"""
    if warn:
        pkg.warnings.append(warn)
    if cur.collecting == "records":
        if cur.mode_open and cur.mode_letter is not None:
            _flush_mode_records(pkg, cur, indep)
        else:
            _flush_data_block(pkg, cur, indep)
    elif cur.collecting == "values":
        _flush_data_block(pkg, cur, indep)


#: 收集态内的结构关键字（数据记录=数值行，永不与关键字同名相撞；
#: END/VAR_LIST_END/END_MODE/MODE 有专用收口语义、BEGIN 有块起点语义，
#: 三者均不在此表）。
_STRUCTURAL_KEYWORDS = frozenset({
    "VAR", "CONST", "CONSTANT", "NAME", "INDEPENDENT", "DEPENDENT", "DATA",
    "SEG", "BEGIN_MODE", "SEG_LIST_BEGIN", "SEG_LIST_END", "COMMENT",
})


def _parse_package_lines(pkg: CitiPackage, lines: list[str]) -> None:
    """单包逐行状态机（版本行已剥离）。"""
    cur = _Pending()
    indep_name: str | None = None
    indep_unit: str | None = None
    indep_count: int | None = None

    def indep_now() -> IndependentVar | None:
        return _indep_for(pkg, indep_name, indep_unit, indep_count,
                          cur.seg_list, pkg.warnings)

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        keyword = tokens[0].upper()

        # 注释（! 与 COMMENT）与设备关键字（# 形态）——收集态同样先过滤
        if stripped.startswith("!"):
            pkg.comments.append(stripped[1:].strip())
            continue
        if keyword == "COMMENT":
            pkg.comments.append(stripped[len(tokens[0]):].strip())
            continue
        if stripped.startswith("#"):
            parts = stripped[1:].split()
            if len(parts) >= 2:
                pkg.header[f"#{parts[0]}"] = " ".join(parts[1:])
            else:
                pkg.warnings.append(f"设备关键字形态不完整: {stripped!r}")
            continue

        # ── 收集态：数据记录=数值行逐条吸收；结构行触发收口语义 ──
        if cur.collecting is not None:
            if keyword == "BEGIN":
                # SEG/DATA 声明即挂起收集态，块开头的 BEGIN（collected 空）
                # 是本块标准起点——保持收集态；非空=真嵌套，忽略并告警
                if cur.collected:
                    pkg.warnings.append(
                        "嵌套 BEGIN（前块未收口），忽略新 BEGIN")
                continue
            if keyword in ("END", "VAR_LIST_END", "END_MODE", "MODE"):
                if keyword == "END":
                    _close_collecting(pkg, cur, indep_now(), warn=None)
                    continue
                if keyword == "VAR_LIST_END":
                    _close_collecting(pkg, cur, indep_now(), warn=None)
                    continue
                if keyword == "END_MODE":
                    _close_collecting(pkg, cur, indep_now(), warn=None)
                    if not cur.mode_open:
                        pkg.warnings.append("END_MODE 无匹配 BEGIN_MODE")
                    cur.mode_open = False
                    continue
                # keyword == "MODE"：换 MODE 是前一记录组合法终止 → 收口后
                # 落入下方 MODE 常规处理
                _close_collecting(pkg, cur, indep_now(), warn=None)
            elif keyword in _STRUCTURAL_KEYWORDS:
                # 其余结构行落在数据块内：按截断态收口（如实证记录），
                # 再落入常规关键字处理
                _close_collecting(
                    pkg, cur, indep_now(),
                    warn="数据块在 END 前被结构行打断，按截断态收口"
                         "（已收记录保留）")
            else:
                cur.collected.append(stripped)
                continue

        # ── 非收集态关键字 ──
        if keyword == "NAME":
            pkg.name = stripped[len(tokens[0]):].strip() or None
            continue
        if keyword in ("CONST", "CONSTANT"):
            if len(tokens) >= 3:
                pkg.constants[tokens[1]] = " ".join(tokens[2:])
            else:
                pkg.warnings.append(f"{keyword} 形态不完整: {stripped!r}")
            continue
        if keyword == "VAR":
            if len(tokens) >= 4:
                occ = _try_int(tokens[3])
                if occ is None:
                    pkg.warnings.append(f"VAR 出现次数非整数: {stripped!r}")
                    continue
                pkg.variables.append(
                    CitiVar(name=tokens[1], fmt=tokens[2], occurrences=occ))
            else:
                pkg.warnings.append(f"VAR 形态不完整: {stripped!r}")
            continue
        if keyword == "VAR_LIST_BEGIN":
            if pkg.variables:
                cur.collecting = "values"
                cur.collect_is_data = False
                cur.collected = []
            else:
                pkg.warnings.append("VAR_LIST_BEGIN 无前置 VAR 声明")
            continue
        if keyword == "VAR_LIST_END":
            if cur.collecting == "values":
                _flush_data_block(pkg, cur, indep_now())
            continue
        if keyword == "SEG_LIST_BEGIN":
            cur.seg_list_open = True
            continue
        if keyword == "SEG_LIST_END":
            cur.seg_list_open = False
            continue
        if keyword == "SEG":
            if cur.seg_list_open or (
                    len(tokens) >= 4 and _try_float(tokens[1]) is not None
                    and _try_float(tokens[2]) is not None):
                # 线性段声明形态：SEG start stop count（Ansys 文档口径）
                if len(tokens) >= 4:
                    start, stop = float(tokens[1]), float(tokens[2])
                    count = _try_int(tokens[3])
                    if count is None:
                        pkg.warnings.append(
                            f"SEG 线性段点数非整数: {stripped!r}")
                        continue
                    cur.seg_list = (start, stop, count)
                continue
            # 打包数据段头：SEG <格式串> <记录数>
            if len(tokens) >= 3:
                cur.pending_seg = tokens[1]
                cur.pending_seg_count = _try_int(tokens[2])
                if cur.pending_seg_count is None:
                    pkg.warnings.append(f"SEG 记录数非整数: {stripped!r}")
                cur.collecting = "records"
                cur.collect_is_data = True
                cur.collected = []
            else:
                pkg.warnings.append(f"SEG 打包头形态不完整: {stripped!r}")
            continue
        if keyword == "INDEPENDENT":
            if len(tokens) >= 2:
                indep_name = tokens[1]
                indep_count = None
                indep_unit = None
                rest = tokens[2:]
                if rest and _try_float(rest[-1]) is not None:
                    indep_count = _try_int(rest[-1])
                    if len(rest) >= 2:
                        indep_unit = rest[0]
                elif rest:
                    indep_unit = rest[0]
            else:
                pkg.warnings.append(f"INDEPENDENT 形态不完整: {stripped!r}")
            continue
        if keyword == "DEPENDENT":
            if len(tokens) >= 4:
                # 4 token：name unit fmt
                cur.pending_dependents.append(
                    (tokens[1], tokens[2], tokens[3]))
            elif len(tokens) == 3:
                # 3 token：name fmt（unit 缺省 None）
                cur.pending_dependents.append((tokens[1], None, tokens[2]))
            else:
                pkg.warnings.append(f"DEPENDENT 形态不完整: {stripped!r}")
            continue
        if keyword == "DATA":
            if len(tokens) >= 3:
                cur.pending_data = (tokens[1], None, tokens[2])
            elif len(tokens) == 2:
                # PLTS 最小形态：DATA S RI 省略索引 → 按声明名裸收
                cur.pending_data = (tokens[1], None, "RI")
            else:
                pkg.warnings.append(f"DATA 形态不完整: {stripped!r}")
            continue
        if keyword == "BEGIN":
            if cur.collecting is not None:
                pkg.warnings.append("嵌套 BEGIN（前块未收口），忽略新 BEGIN")
                continue
            cur.collecting = "records" if (
                cur.pending_seg is not None or cur.pending_data is not None
                or cur.pending_dependents) else "values"
            cur.collect_is_data = cur.collecting == "records"
            cur.collected = []
            continue
        if keyword == "BEGIN_MODE":
            if cur.mode_open:
                pkg.warnings.append("嵌套 BEGIN_MODE，忽略")
            else:
                cur.mode_open = True
            continue
        if keyword == "END_MODE":
            if not cur.mode_open:
                pkg.warnings.append("END_MODE 无匹配 BEGIN_MODE")
            else:
                if cur.mode_letter is not None:
                    pkg.warnings.append(
                        "END_MODE 时 MODE 数据未以 END 收口——已收记录如实"
                        "按截断处理")
                    _flush_mode_records(pkg, cur, indep_now())
                cur.mode_open = False
            continue
        if keyword == "MODE":
            if not cur.mode_open:
                pkg.warnings.append(
                    f"MODE 行出现在 BEGIN_MODE 外，按原文登记: {stripped!r}")
                pkg.header["MODE"] = " ".join(tokens[1:])
                continue
            if cur.mode_letter is not None and cur.collected:
                # 前一 MODE 段未 END 收口即换新 MODE：截断态如实物化
                _flush_mode_records(pkg, cur, indep_now())
            letter = tokens[1].strip().upper() if len(tokens) >= 2 else ""
            if letter not in SUPPORTED_FORMAT_LETTERS:
                pkg.warnings.append(f"MODE 字母非法: {stripped!r}")
                cur.mode_letter = None
                continue
            cur.mode_letter = letter
            cur.mode_cformat = tokens[2] if len(tokens) >= 3 else None
            cur.collecting = "records"
            cur.collect_is_data = True
            cur.collected = []
            continue

        # 未知行：包头关键字形态收编（原文大写首 token——keyword 已被
        # upper()，isupper 判定必须回原文），其余逐行 warning
        if keyword in KNOWN_HEADER_KEYS or tokens[0].isupper():
            pkg.header[keyword] = " ".join(tokens[1:])
        else:
            pkg.warnings.append(f"无法归类的行: {stripped[:60]!r}")

    # 文件尾收尾：未收口块如实登记（截断态保留已收记录）
    if cur.collecting == "records":
        pkg.warnings.append("文件截断：BEGIN 后无 END，已收记录按截断态保留")
        if cur.mode_open and cur.mode_letter is not None:
            _flush_mode_records(pkg, cur, indep_now())
        else:
            _flush_data_block(pkg, cur, indep_now())
    elif cur.collecting == "values":
        pkg.warnings.append("文件截断：值表未 END 收口，已收值保留")
        _flush_data_block(pkg, cur, indep_now())
    if cur.mode_open:
        pkg.warnings.append("文件截断：BEGIN_MODE 未 END_MODE")
    if cur.pending_dependents:
        pkg.warnings.append(
            "文件尾仍有未消费的 DEPENDENT 声明（无数据块），如实登记不产段")


def _is_version_line(stripped: str) -> bool:
    upper = stripped.upper()
    if upper.startswith("CITIFILE"):
        return True
    tokens = upper.split()
    return len(tokens) >= 2 and tokens[0] == "CVG" and tokens[1] == "VERSION"


def parse_citi_text(text: str, *,
                    source: str | None = None) -> list[CitiPackage]:
    """解析 CITIfile 文本 → 包列表（一文件可含多包，按版本行拆分）。

    首个非空行不是版本行（CITIFILE / CVG VERSION）→
    :class:`CitiParseError`（非 CITI 文件，不猜）。
    """
    lines = text.splitlines()
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty or not _is_version_line(nonempty[0].strip()):
        raise CitiParseError(
            "非 CITI 文件：首行应为 CITIFILE <版本> 或 CVG VERSION <版本>")
    # 按版本行切包（版本行进包首）
    chunks: list[list[str]] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and _is_version_line(stripped):
            if buf:
                chunks.append(buf)
            buf = [line]
        else:
            buf.append(line)
    if buf:
        chunks.append(buf)
    packages: list[CitiPackage] = []
    for chunk in chunks:
        header_line = chunk[0].strip()
        tokens = header_line.split()
        pkg = CitiPackage(n_lines=len(chunk))
        if tokens[0].upper() == "CITIFILE":
            pkg.version_keyword = "CITIFILE"
            pkg.version = tokens[1] if len(tokens) >= 2 else None
            pkg.header["CITIFILE"] = pkg.version or ""
        else:
            pkg.version_keyword = "CVG VERSION"
            pkg.version = tokens[2] if len(tokens) >= 3 else None
            pkg.header["CVG VERSION"] = pkg.version or ""
        if source:
            pkg.header["SOURCE"] = source
        _parse_package_lines(pkg, chunk[1:])
        packages.append(pkg)
    return packages


def parse_citi_file(path: str | Path) -> list[CitiPackage]:
    """读文件并解析（utf-8 失败回落 latin-1 并在包头登记 SOURCE 编码注记）。"""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        encoding_note = "utf-8"
    except UnicodeDecodeError:
        text = p.read_text(encoding="latin-1")
        encoding_note = "latin-1(fallback)"
    except OSError as exc:
        raise CitiParseError(f"CITI 文件不可读: {p} ({exc})") from exc
    packages = parse_citi_text(text, source=str(p))
    for pkg in packages:
        pkg.header["SOURCE_ENCODING"] = encoding_note
    return packages


# ────────────────────────── JSON 安全输出 ──────────────────────────


def _json_value(values: list[float] | list[complex] | None) -> tuple[
        list[float] | list[list[float]] | None, str]:
    """值列 → JSON 安全形态；返回 (json_values, value_kind)。"""
    if values is None:
        return None, "none"
    if values and isinstance(values[0], complex):
        return [[v.real, v.imag] for v in values], "complex"
    return list(values), "float"


def segment_to_dict(seg: CitiSegment) -> dict:
    """段 → JSON 安全字典（任务书结构化输出口径）。"""
    indep = None
    if seg.independent_var is not None:
        indep_vals, _kind = _json_value(seg.independent_var.values)
        indep = {
            "name": seg.independent_var.name,
            "unit": seg.independent_var.unit,
            "values": indep_vals,
        }
    deps = []
    for dep in seg.dependent_vars:
        vals, kind = _json_value(dep.values)
        deps.append({"name": dep.name, "unit": dep.unit,
                     "values": vals, "value_kind": kind})
    out: dict = {
        "type": seg.type,
        "var_name": seg.var_name,
        "var_unit": seg.var_unit,
        "format": seg.format,
        "independent_var": indep,
        "dependent_vars": deps,
        "decode_status": seg.decode_status,
        "n_records": seg.n_records,
        "n_records_expected": seg.n_records_expected,
        "warnings": list(seg.warnings),
    }
    if seg.raw_records is not None:
        out["raw_records"] = list(seg.raw_records)
    return out


def package_to_dict(pkg: CitiPackage, *, package_index: int = 0,
                    n_packages: int = 1) -> dict:
    """包 → JSON 安全字典（任务书 {header, segments, metadata} 口径）。

    metadata 计数面含 ``n_warnings``（=len(warnings)，R-22 schema 升位
    批补键——附加键不改既有键语义）。
    """
    return {
        "header": dict(pkg.header),
        "version": pkg.version,
        "version_keyword": pkg.version_keyword,
        "name": pkg.name,
        "constants": dict(pkg.constants),
        "variables": [
            {"name": v.name, "fmt": v.fmt, "occurrences": v.occurrences,
             "n_values": (len(v.values) if v.values is not None else None),
             "values": (list(v.values) if v.values is not None else None)}
            for v in pkg.variables
        ],
        "segments": [segment_to_dict(s) for s in pkg.segments],
        "metadata": {
            "n_packages": n_packages,
            "package_index": package_index,
            "n_lines": pkg.n_lines,
            "n_comments": len(pkg.comments),
            "n_warnings": len(pkg.warnings),
            "warnings": list(pkg.warnings),
        },
    }
