"""SPEF 寄生交换格式结构化解析内核（aurora_q Q-X60 席位，2026-11-07）。

数字后端**寄生提取交换格式** SPEF（Standard Parasitic Exchange Format，
IEEE 1481-1998）的只读结构化解析——OpenRCX/K-layout/商用提取器输出、
STA 输入三件套之二（SDC Q-X36 / Verilog 网表 Q-X47 已在仓）的标准交接
面。词法与语义全部在 core 确定性内核（铁律 7：结构化数字只出自数据源
文本本身；单位换算=显式系数表，LLM/agent 永不产生物理数字）。服务
包装见 :mod:`rfauto.service.spef_service`（规则 4 JSON 进出），CLI 薄壳
见 cli/domains/spef.py。

覆盖面（结构子集；fail-soft 口径——病态行降级为警告+跳行，不炸全文）：

- 头部：``*SPEF "IEEE 1481-1998"`` 版本串（缺 *SPEF 头=致命，抛
  :class:`SpefParseError`——文件身份判定面）；``*DESIGN``/``*DATE``/
  ``*VENDOR``/``*PROGRAM``/``*VERSION``/``*DESIGN_FLOW``（引号串剥壳）
  ；``*DIVIDER``（缺省 ``/``）与 ``*DELIMITER_CHAR``（缺省 ``:``）
  收进 ``header["dividers"]``、``*BUS_DELIMITER_CHAR``（缺省 ``[ ]``）
  收进 ``header["bus_delimiters"]``；
- 单位声明：``*T_UNIT/*C_UNIT/*R_UNIT/*L_UNIT <乘数> <单位>``——
  换算系数=乘数×单位基准（:func:`spef_unit_factor` 单源；PF→1e-12
  等）；**未知单位 fail-closed**：warning+系数取 1.0（原值保留，
  绝不静默猜量纲）；
- ``*NAME_MAP``：``*id name`` 长名折叠机制——id→name 主映射
  （``name_map``，JSON 安全 str 键）+ name→id 反查（
  ``name_map_reverse``，重名时首 id 胜出）；重复 id 后者覆盖前者+
  warning；重复名如实告警；
- ``*PORTS``：``name direction``（direction ∈ I/O/B；id 引用形态
  ``*10001 I`` 同样解析展开）；direction 非词表值如实记录原文+
  warning；
- ``*D_NET`` 段状态机：``*D_NET *id 总电容``（总电容=头部 C_UNIT
  口径原值 ``total_cap_header`` + 换算法拉 ``total_cap_far``）→
  ``*CONN``（``*P pin direction`` / ``*I node type direction *C x y
  *L layers``——**direction-first**（业界主流：tokens[2]∈I/O/B 判
  direction，type=None）与 **type-first**（任务书口径 tokens[2]=类型
  tokens[3]=方向）双形态判定；坐标/层注记如实入 ``coords``/
  ``layers``）→ ``*CAP``（序号+两列=对地、序号+三列=耦合双端；
  coupling 标志变体——非数字 id 形态的星词如 ``*C``——如实识别入
  ``flag``）→ ``*RES``（四列形态）→ ``*IND``（同 RES 形态电感）→
  ``*END``；非法列数/非数值/非整数序号→fail-soft 跳行+warning；
- 节点引用解析：``*id``（整名）与 ``*id:pin``（id+分隔符+尾段）双
  形态按 ``*DELIMITER_CHAR`` 切分回名；**未映射 id 保真展开为
  ``<*id>`` 字面**（``*99999:3``→``<*99999>:3``——不猜不丢）；
- 注释容忍：``//`` 行注释（整行或行尾）与 ``#`` 注释变体（行首或前接
  空白的行尾形态——SPEF 名不含空白故无误伤）；引号串内两者都不算注
  释；词法=双引号串整体成词（``*SPEF "IEEE 1481-1998"`` 含空格版本串
  不被切碎）；``*SCALE`` 段如实登记进 ``header["scale"]``；其余未知
  ``*指令`` 行 warning+跳过。

数值形态扩展（aurora_r R-02 席位，Q-X60"三值数值（min:typ:max）未支
持 warning 整行跳过"已知限制转正——:func:`parse_spef_value` 单源）：

- **plain**：``float(token)`` 原生成功（含科学计数/显式正负号——与历
  史 ``float()`` 路径逐位同判，零行为变化）；
- **d_exponent**：Fortran D 阶码变体（``1.2D3``/``1.5d-3``）——d→e
  后 float（纯记法变体，量纲口径与 plain 同）；
- **triple**：``min:typ:max`` 三段冒号三值（Q-X60 已知限制转正）——每
  段限 plain/d_exponent（段内禁乘积/后缀）；判定值=**typ**（中段，
  STA 惯例），min/typ/max 全量随行；条目附 ``value_form="triple"``/
  ``value_raw``/``value_min_far``/``value_max_far``（D_NET 总电容附
  ``total_cap_form``/``total_cap_raw``/``total_cap_min``/
  ``total_cap_max``——头部原值口径同 ``total_cap_header``）；typ 取中
  段是**声明性选择**，随行发 tier3 诊断 ``triple_typ_selected`` 披露；
- **product**：``A*B[*C…]`` 缩放乘积链——每因子=带符号十进制数（可含
  e 阶码）+可选单个 SPICE 家族后缀（:data:`SPEF_VALUE_SUFFIXES`，
  meg/mil 双字母先于单字母、大小写不敏感）；值=全因子**十进制精确乘
  积**的单次 float 舍入（Decimal 链，spectre_parser 同款逐位口径）；
  任一因子带后缀 → 量纲=**absolute**（后缀已携带 SI 量纲，**不再乘头
  部单位系数**——量纲读法是声明性约定，随行 tier3 诊断
  ``suffixed_product_absolute_si`` 披露+原文随行可复算）；全因子无后
  缀 → 量纲=header（与 plain 同口径乘头部系数）；
- **不可判定形态保留跳行**：裸后缀值（``1.2p``——量纲"头部单位 vs 绝
  对 SI"两读不可判，绝不猜）→ tier1 诊断；其余病态形态（乘积因子空
  缺/三值段数非 3/未知后缀）→ tier 诊断见下节，warning 文案不变；
- **续行**：``*CAP``/``*RES``/``*IND`` 段内 ``+``/``-`` 起头两词行
  （``+ <数>``）=对**该段最近一条已解析元件值**的算术续行（值±增量，
  增量限 header 量纲形态）；续行事件全量落
  ``doc["value_continuations"]``（net/段/op/增量/行号/原文）；无前置
  元件/增量形态不可续 → warning+跳行+tier 诊断（不再静默）。

解析输出 schema=spef/1.0，本批为**纯附加键扩展不升位**（既有键与语
义零变化；新键全部可选出现——``diagnostics``/``value_continuations``
顶层键与非 plain 值条目的 ``value_form`` 族键）。

AX-6 结构化 tier 诊断（:mod:`rfauto.core.parser_diagnostics` 四层判
据）：每个跳行/降级/声明性选择事件同笔落
``doc["diagnostics"]``——``{tier, parser, reason, line, snippet}``，
snippet=剥注释后消费行原文（#331 不美化）；既有 ``warnings`` 文案
（既定契约）逐字节零变化，两列同笔发射（:class:`_DiagSink` 单源）。
定档口径：病态跳行=unparsed；未知指令/头部未分派指令/裸后缀值=
unsupported-tier1；typ 选择/量纲约定/EOF 收口/方向词表外降级/未知单
位系数 1.0=unsupported-tier3（本域无 tier2 事件——``*SCALE`` 登记未
应用等结构已识别语义未实现面如实挂账空缺）。

总电容一致性（不设硬门）：每 net 报告三数字——``total_cap_far``（头
部申报，法拉）/``cap_sum_far``（段内求和，法拉）/``cap_rel_diff``
（相对偏差）；``total_cap_far==0`` 时 ``cap_rel_diff`` 如实 None
（除零未定义）。偏差成因（提取器口径不一：耦合电容是否计入总电容、
只计一端等）由消费方复核，解析层只出数字不下结论。

拓扑三函数（服务/CLI 上层消费）：

- :func:`spef_topology_summary`：逐 net 节点数/元件数/连通分量数
  （并查集）+孤立节点清单（口径=仅 CONN 声明零元件节点如实列出——
  宁多报不误报，孤立=解析层判据非电气结论）；
- :func:`spef_coupling_stats`：耦合电容总数/总和对地总和比/最强耦
  合对 top-k（k 缺省 5；排序键 ``(-值, 全局序)`` 确定性稳定）；
- :func:`spef_net_lookup`：按展开名查 net 全量视图（未命中返回
  None，调用方分型）。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖（诊断工
具=仓内 core 兄弟模块）。本模块
不设 ``__all__``（无 __all__ 的非门面文件不进 tests/gold/
public_api.json——verilog_netlist_parser/sdc_parser 同款先例，新模
块零金快照漂移）。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from rfauto.core.parser_diagnostics import (
    TIER_UNPARSED,
    TIER_UNSUPPORTED_1,
    TIER_UNSUPPORTED_2,
    TIER_UNSUPPORTED_3,
    line_snippet,
    make_parse_diagnostic,
)

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 单位换算基准表（kind→单位→SI 基准系数；大小写不敏感，键统一大写）。
#: 换算=头部乘数×本表基准。未知单位 fail-closed（调用方 warning+系数 1.0）。
UNIT_SCALES: dict[str, dict[str, float]] = {
    "c": {
        "F": 1.0,
        "PF": 1e-12,
        "NF": 1e-9,
        "UF": 1e-6,
        "FF": 1e-15,
    },
    "r": {
        "OHM": 1.0,
        "KOHM": 1e3,
        "MOHM": 1e6,
    },
    "l": {
        "HENRY": 1.0,
        "MH": 1e-3,
        "UH": 1e-6,
        "NH": 1e-9,
        "PH": 1e-12,
    },
    "t": {
        "S": 1.0,
        "MS": 1e-3,
        "US": 1e-6,
        "NS": 1e-9,
        "PS": 1e-12,
    },
}

#: 端口/连接方向词表（I=input，O=output，B=bidir；词表外如实记原文+warning）。
DIRECTIONS = frozenset({"I", "O", "B"})

#: D_NET 内子段关键词→记录桶。
D_NET_SECTIONS = frozenset({"*CONN", "*CAP", "*RES", "*IND"})

#: SPEF 方言数值后缀缩放表（格式常数非物理数值；SPICE 家族口径——同
#: core.spice_netlist_parser._SPICE_SCALE / core.spectre_parser.
#: SPECTRE_UNIT_SCALE 家族；大小写不敏感、meg/mil 双字母先于单字母，
#: 经典 SPICE 口径 M=毫 meg=兆）。**只用于缩放乘积链的因子换算**——裸
#: 后缀值量纲两读不可判，绝不入正式解析（fail-closed 不猜量纲）。
SPEF_VALUE_SUFFIXES: dict[str, float] = {
    "meg": 1e6,
    "mil": 25.4e-6,
    "t": 1e12,
    "g": 1e9,
    "k": 1e3,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}

#: 缩放乘积因子词法：带符号十进制数（可含 e 阶码）+可选字母尾。
_FACTOR_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z]*)$")
#: Fortran D 阶码变体（``1.2D3``/``1.5d-3``——d/D 与 e/E 等价记法）。
_DEXPONENT_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)[dD][+-]?\d+$")
#: plain/纯十进制段词法（triple 段内用；禁后缀禁乘积）。
_SIMPLE_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")

#: parse_spef_value 失败 reason → tier 定档单源（未列出的 reason 一律
#: unparsed——病态形态；列出的=已知方言语法但量纲两读不可判→tier1）。
_VALUE_FAIL_TIER: dict[str, str] = {
    "bare_suffix_dimension_ambiguous": TIER_UNSUPPORTED_1,
    "triple_part_suffixed_dimension_ambiguous": TIER_UNSUPPORTED_1,
}


class SpefParseError(ValueError):  # P2-3 勘误 2026-11-10 合流笔：Exception→ValueError（19 parser 唯一离群，消费方 except ValueError 漏接风险；FINAL_AUDIT P2-3）
    """SPEF 文件身份级致命错误（缺 *SPEF 头/空文件）——fail-soft 之外的
    唯一致命面。词法/结构病态不走本异常（warning+跳行口径）。"""


def spef_unit_factor(kind: str, unit: str) -> float | None:
    """单位换算系数（kind ∈ c/r/l/t；未知单位返回 None——调用方 fail-closed）。

    系数=单位基准（头部乘数由调用方另乘）。大小写不敏感。
    """
    table = UNIT_SCALES.get(kind)
    if table is None:
        return None
    return table.get(unit.strip().upper())


def _value_ok(
    value: float, form: str, raw: str, units: str,
    *,
    triple: tuple[float, float, float] | None = None,
    factors: list[float] | None = None,
    suffixed: bool | None = None,
) -> dict[str, Any]:
    """parse_spef_value 成功形状（全键恒在——消费方按键取用免 KeyError）。"""
    out: dict[str, Any] = {
        "ok": True,
        "value": value,
        "form": form,
        "raw": raw,
        "units": units,
        "reason": None,
        "min": None,
        "typ": None,
        "max": None,
        "factors": factors,
        "suffixed": suffixed,
    }
    if triple is not None:
        out["min"], out["typ"], out["max"] = triple
    return out


def _value_fail(reason: str, raw: str) -> dict[str, Any]:
    """parse_spef_value 失败形状（reason 机读码——tier 定档走
    :data:`_VALUE_FAIL_TIER`，未列出一律 unparsed）。"""
    return {
        "ok": False,
        "value": None,
        "form": None,
        "raw": raw,
        "units": None,
        "reason": reason,
        "min": None,
        "typ": None,
        "max": None,
        "factors": None,
        "suffixed": None,
    }


def _parse_simple_number(token: str) -> float | None:
    """plain/d_exponent 两形态strict解析（triple 段内专用；禁后缀禁乘积）。

    plain 走 float 原生；D 阶码 d/D→e/E 替换后 float。均失败返回 None。
    """
    if _SIMPLE_RE.match(token):
        try:
            return float(token)
        except ValueError:  # pragma: no cover - 词法已过，float 必成
            return None
    if _DEXPONENT_RE.match(token):
        try:
            return float(token.replace("d", "e").replace("D", "E"))
        except (ValueError, OverflowError):
            return None
    return None


def parse_spef_value(token: str) -> dict[str, Any]:
    """SPEF 数值令牌解析（含三值/缩放乘积/D 阶码扩展形态；纯函数单源）。

    判定序（确定性，先标准后方言）：

    1. **plain**——``float(token)`` 原生成功（与历史 ``float()`` 路径
       逐位同判：含科学计数、显式正负号、下划线、inf/nan 全部 Python
       float 字面；零行为变化）；量纲=header（调用方乘头部单位系数）；
    2. **d_exponent**——Fortran D 阶码变体（``1.2D3``=1200.0）；量纲=
       header（纯记法变体）；
    3. **triple**——``min:typ:max`` 三段冒号三值；每段限
       plain/d_exponent；判定值=typ（中段），``min``/``typ``/``max``
       随行；段含后缀 → 量纲两读不可判 fail（tier1）；
    4. **product**——``A*B[*C…]`` 缩放乘积链；每因子=十进制数+可选单
       个 SPICE 家族后缀；值=Decimal 精确全乘积单次 float 舍入（逐位
       回收锚）；任一因子带后缀 → 量纲=**absolute**（不再乘头部系数）；
    5. **失败**——``ok=False``+机读 ``reason``（裸后缀值
       ``1.2p``=量纲两读不可判 → tier1；其余病态 → unparsed）；
       调用方按既定文案 warning+跳行+tier 诊断。

    返回全键恒在的 dict：``{"ok", "value", "form", "raw", "units",
    "reason", "min", "typ", "max", "factors", "suffixed"}``（form ∈
    plain/d_exponent/triple/product/None；units ∈ header/absolute/
    None）。输入应为无空白单词（``_tokenize`` 产物）。
    """
    # 1) plain——历史 float() 路径逐位同判（不 strip：词法词无空白）
    try:
        return _value_ok(float(token), "plain", token, "header")
    except ValueError:
        pass
    # 2) Fortran D 阶码变体
    if _DEXPONENT_RE.match(token):
        try:
            value = float(token.replace("d", "e").replace("D", "E"))
        except (ValueError, OverflowError):
            return _value_fail("unrecognized", token)
        return _value_ok(value, "d_exponent", token, "header")
    # 3) min:typ:max 三值
    if ":" in token:
        parts = token.split(":")
        if len(parts) != 3:
            return _value_fail("triple_arity", token)
        vals: list[float] = []
        for part in parts:
            simple = _parse_simple_number(part)
            if simple is not None:
                vals.append(simple)
                continue
            if part and _FACTOR_RE.match(part) and part.lstrip("+-0123456789.eE") \
                    and part.lstrip("+-0123456789.eE").lower() in SPEF_VALUE_SUFFIXES:
                return _value_fail(
                    "triple_part_suffixed_dimension_ambiguous", token)
            if not part:
                return _value_fail("triple_empty_part", token)
            return _value_fail("triple_part_unrecognized", token)
        return _value_ok(
            vals[1], "triple", token, "header",
            triple=(vals[0], vals[1], vals[2]))
    # 4) 缩放乘积链 A*B[*C…]
    if "*" in token:
        parts = token.split("*")
        if len(parts) < 2 or any(p == "" for p in parts):
            return _value_fail("product_empty_factor", token)
        factor_decimals: list[Decimal] = []
        factor_views: list[float] = []
        suffixed = False
        for part in parts:
            m = _FACTOR_RE.match(part)
            if not m:
                return _value_fail("factor_unrecognized", token)
            body, suffix = m.group(1), m.group(2)
            try:
                body_dec = Decimal(body)
            except InvalidOperation:
                return _value_fail("factor_unrecognized", token)
            if suffix:
                scale = SPEF_VALUE_SUFFIXES.get(suffix.lower())
                if scale is None:
                    return _value_fail("factor_suffix_unrecognized", token)
                body_dec = body_dec * Decimal(str(scale))
                suffixed = True
            factor_decimals.append(body_dec)
            factor_views.append(float(body_dec))
        product = Decimal(1)
        for dec in factor_decimals:
            product = product * dec
        return _value_ok(
            float(product), "product", token,
            "absolute" if suffixed else "header",
            factors=factor_views, suffixed=suffixed)
    # 5) 裸后缀值（量纲两读不可判——绝不猜）与其余病态
    m = _FACTOR_RE.match(token)
    if m and m.group(2):
        if m.group(2).lower() in SPEF_VALUE_SUFFIXES:
            return _value_fail("bare_suffix_dimension_ambiguous", token)
        return _value_fail("suffix_unrecognized", token)
    return _value_fail("unrecognized", token)


def value_fail_tier(reason: str) -> str:
    """parse_spef_value 失败 reason → tier 定档（单源；未列出一律 unparsed）。"""
    return _VALUE_FAIL_TIER.get(reason, TIER_UNPARSED)


class _DiagSink:
    """warnings（既有文案契约逐字节零变化）+ diagnostics（AX-6 结构化
    附加层）双列同笔发射器——warning/diagnostic 永不成孤列。"""

    def __init__(self, parser: str) -> None:
        self.warnings: list[str] = []
        self.diags: list[dict[str, Any]] = []
        self._parser = parser

    def warn(
        self, msg: str, *, tier: str, reason: str,
        line: int | None = None, snippet: str | None = None,
    ) -> None:
        """既定文案 warning + 同笔 tier 诊断。"""
        self.warnings.append(msg)
        self.diag(tier=tier, reason=reason, line=line, snippet=snippet)

    def diag(
        self, *, tier: str, reason: str,
        line: int | None = None, snippet: str | None = None,
    ) -> None:
        """仅诊断（无 warning 的披露类事件——typ 选择/量纲约定）。"""
        self.diags.append(make_parse_diagnostic(
            tier, reason, line,
            None if snippet is None else line_snippet(snippet),
            parser=self._parser))


def _strip_comment(line: str) -> str:
    """剥行注释：``//``（整行或行尾）与 ``#``（行首或前接空白——SPEF
    名不含空白，空白后的 ``#`` 不可能属名字词）。引号串内两者都不算
    注释（``*VENDOR "http://x"`` 保真）。"""
    in_quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif in_quote:
            continue
        elif (ch == "/" and line[i:i + 2] == "//") or (
                ch == "#" and (i == 0 or line[i - 1].isspace())):
            return line[:i].strip()
    return line.strip()


#: 词法：双引号串整体成词（头部 ``*SPEF "IEEE 1481-1998"`` 含空格），其余按空白切分。
_TOKEN_RE = re.compile(r'"[^"]*"|\S+')


def _tokenize(line: str) -> list[str]:
    """行 → 词表（引号串整体保留含引号；剥壳由头部分派层做）。"""
    return _TOKEN_RE.findall(line)


def _resolve_token(
    token: str, name_map: dict[str, str], delimiter: str
) -> str:
    """节点/名引用展开：``*id`` 整名与 ``*id<分隔符>尾段`` 双形态。

    未映射 id 保真展开为 ``<*id>``（含尾段形态 ``<*id>:3``）——不猜
    不丢（字面保真口径）。非星词原样通过。
    """
    if not token.startswith("*"):
        return token
    body = token[1:]
    if delimiter and delimiter in body:
        head, _, tail = body.partition(delimiter)
    else:
        head, tail = body, ""
    name = name_map.get(head)
    if name is None:
        # 未映射 id 保真：只对 id 引用段加尖括号（尾段保持原位）
        base = f"<*{head}>"
        return f"{base}{delimiter}{tail}" if tail else base
    if not tail:
        return name
    return f"{name}{delimiter}{tail}"


def _split_star_flags(tokens: list[str]) -> tuple[list[str], list[str]]:
    """数据词分派：非数字 id 形态的星词（``*C`` 类 coupling 标志）与
    数据词分离。数字 id 引用（``*10001:2``）不算标志。"""
    flags: list[str] = []
    data: list[str] = []
    for tok in tokens:
        if tok.startswith("*") and not tok[1:2].isdigit():
            flags.append(tok)
        else:
            data.append(tok)
    return data, flags


def _scaled_value(pv: dict[str, Any], factor: float) -> float:
    """parse_spef_value 成功结果 → SI 值（量纲口径单源）。

    header=判定值×头部系数（plain/d_exponent/triple/无后缀乘积）；
    absolute=判定值原样（后缀乘积已携带 SI 量纲，不再乘头部系数）。
    """
    if pv["units"] == "absolute":
        return pv["value"]
    return pv["value"] * factor


def _disclose_form(
    sink: _DiagSink, pv: dict[str, Any], line_no: int, snippet: str
) -> None:
    """非 plain 形态的声明性选择披露（tier3 诊断；零 warning 文案变化）。"""
    if pv["form"] == "triple":
        sink.diag(tier=TIER_UNSUPPORTED_3, reason="triple_typ_selected",
                  line=line_no, snippet=snippet)
    elif pv["form"] == "product" and pv["suffixed"]:
        sink.diag(tier=TIER_UNSUPPORTED_3,
                  reason="suffixed_product_absolute_si",
                  line=line_no, snippet=snippet)


def _parse_conn_line(
    tokens: list[str],
    net: dict[str, Any],
    name_map: dict[str, str],
    delimiter: str,
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> None:
    """``*CONN`` 行：``*P pin direction`` / ``*I node type direction
    *C x y *L layers``（direction-first 与 type-first 双形态判定）。"""
    kind = tokens[0].lstrip("*").upper()
    if len(tokens) < 3:
        sink.warn(
            f"CONN 行字段不足（第 {line_no} 行）: {' '.join(tokens)}——跳过",
            tier=TIER_UNPARSED, reason="conn_insufficient_fields",
            line=line_no, snippet=snippet)
        return
    node = _resolve_token(tokens[1], name_map, delimiter)
    entry: dict[str, Any] = {"kind": kind, "node": node}
    rest = tokens[2:]
    # direction-first（tokens[2]∈I/O/B——业界主流）/type-first（任务书
    # 口径 tokens[2]=类型 tokens[3]=方向）双形态确定性判定
    if rest[0] in DIRECTIONS:
        entry["direction"] = rest[0]
        extra = rest[1:]
    else:
        entry["type"] = rest[0]
        if len(rest) > 1 and rest[1] in DIRECTIONS:
            entry["direction"] = rest[1]
            extra = rest[2:]
        else:
            entry["direction"] = None
            sink.warn(
                f"CONN 方向词表外（第 {line_no} 行）: {rest[-1]}——direction 如实 None",
                tier=TIER_UNSUPPORTED_3,
                reason="conn_direction_out_of_vocabulary",
                line=line_no, snippet=snippet)
            extra = rest[1:] if len(rest) > 1 else []
    # 坐标/层注记（*C x y / *L layer...）如实提取
    i = 0
    while i < len(extra):
        tag = extra[i]
        if tag == "*C" and i + 3 <= len(extra):
            try:
                entry["coords"] = [
                    float(extra[i + 1]), float(extra[i + 2])]
                i += 3
                continue
            except ValueError:
                sink.warn(
                    f"CONN 坐标非数值（第 {line_no} 行）: {' '.join(extra)}——坐标略",
                    tier=TIER_UNPARSED, reason="conn_coords_non_numeric",
                    line=line_no, snippet=snippet)
                break
        if tag == "*L":
            j = i + 1
            layers: list[str] = []
            while j < len(extra) and not extra[j].startswith("*"):
                layers.append(extra[j])
                j += 1
            entry["layers"] = layers
            i = j
            continue
        i += 1
    net["conn"].append(entry)


def _parse_cap_line(
    tokens: list[str],
    net: dict[str, Any],
    name_map: dict[str, str],
    delimiter: str,
    c_factor: float,
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> None:
    """``*CAP`` 行：序号+两列=对地 / 序号+三列=耦合双端；星词 coupling
    标志如实识别入 ``flag``；非法列数→fail-soft 跳行+warning。

    值槽走 :func:`parse_spef_value`（三值/缩放乘积/D 阶码扩展形态）；
    非 plain 形态条目附 ``value_form``/``value_raw`` 族键（纯附加键，
    plain 条目形状零变化）。
    """
    try:
        int(tokens[0])
    except ValueError:
        sink.warn(
            f"CAP 序号非整数（第 {line_no} 行）: {tokens[0]}——跳过",
            tier=TIER_UNPARSED, reason="cap_index_not_integer",
            line=line_no, snippet=snippet)
        return
    data, flags = _split_star_flags(tokens[1:])
    if len(data) == 2:
        pv = parse_spef_value(data[1])
        if not pv["ok"]:
            sink.warn(
                f"CAP 电容值非数值（第 {line_no} 行）: {data[1]}——跳过",
                tier=value_fail_tier(pv["reason"]), reason=pv["reason"],
                line=line_no, snippet=snippet)
            return
        entry: dict[str, Any] = {
            "node": _resolve_token(data[0], name_map, delimiter),
            "value_far": _scaled_value(pv, c_factor),
        }
        if pv["form"] != "plain":
            entry["value_form"] = pv["form"]
            entry["value_raw"] = pv["raw"]
            if pv["form"] == "triple":
                entry["value_min_far"] = pv["min"] * c_factor
                entry["value_max_far"] = pv["max"] * c_factor
            elif pv["form"] == "product":
                entry["value_factors"] = pv["factors"]
                if pv["suffixed"]:
                    entry["value_suffixed"] = True
        if flags:
            entry["flag"] = flags[0]
        _disclose_form(sink, pv, line_no, snippet)
        net["caps_gnd"].append(entry)
        return
    if len(data) == 3:
        pv = parse_spef_value(data[2])
        if not pv["ok"]:
            sink.warn(
                f"CAP 电容值非数值（第 {line_no} 行）: {data[2]}——跳过",
                tier=value_fail_tier(pv["reason"]), reason=pv["reason"],
                line=line_no, snippet=snippet)
            return
        entry = {
            "node1": _resolve_token(data[0], name_map, delimiter),
            "node2": _resolve_token(data[1], name_map, delimiter),
            "value_far": _scaled_value(pv, c_factor),
        }
        if pv["form"] != "plain":
            entry["value_form"] = pv["form"]
            entry["value_raw"] = pv["raw"]
            if pv["form"] == "triple":
                entry["value_min_far"] = pv["min"] * c_factor
                entry["value_max_far"] = pv["max"] * c_factor
            elif pv["form"] == "product":
                entry["value_factors"] = pv["factors"]
                if pv["suffixed"]:
                    entry["value_suffixed"] = True
        if flags:
            entry["flag"] = flags[0]
        _disclose_form(sink, pv, line_no, snippet)
        net["caps_cpl"].append(entry)
        return
    sink.warn(
        f"CAP 行列数非法（第 {line_no} 行，{len(data)} 数据列）: "
        f"{' '.join(tokens)}——跳过",
        tier=TIER_UNPARSED, reason="cap_column_count_invalid",
        line=line_no, snippet=snippet)


def _parse_branch_line(
    tokens: list[str],
    bucket: list[dict[str, Any]],
    kind_label: str,
    factor: float,
    value_key: str,
    name_map: dict[str, str],
    delimiter: str,
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> None:
    """``*RES``/``*IND`` 行（同四列形态）：序号 node1 node2 值。

    值槽走 :func:`parse_spef_value`（扩展形态同 CAP；triple 附
    ``value_min_<unit>``/``value_max_<unit>``，乘积附
    ``value_factors``/``value_suffixed``——纯附加键）。
    """
    try:
        int(tokens[0])
    except ValueError:
        sink.warn(
            f"{kind_label} 序号非整数（第 {line_no} 行）: {tokens[0]}——跳过",
            tier=TIER_UNPARSED,
            reason=f"{kind_label.lower()}_index_not_integer",
            line=line_no, snippet=snippet)
        return
    data, _flags = _split_star_flags(tokens[1:])
    if len(data) != 3:
        sink.warn(
            f"{kind_label} 行列数非法（第 {line_no} 行，{len(data)} 数据列）: "
            f"{' '.join(tokens)}——跳过",
            tier=TIER_UNPARSED,
            reason=f"{kind_label.lower()}_column_count_invalid",
            line=line_no, snippet=snippet)
        return
    pv = parse_spef_value(data[2])
    if not pv["ok"]:
        sink.warn(
            f"{kind_label} 数值非数值（第 {line_no} 行）: {data[2]}——跳过",
            tier=value_fail_tier(pv["reason"]), reason=pv["reason"],
            line=line_no, snippet=snippet)
        return
    entry: dict[str, Any] = {
        "node1": _resolve_token(data[0], name_map, delimiter),
        "node2": _resolve_token(data[1], name_map, delimiter),
        value_key: _scaled_value(pv, factor),
    }
    if pv["form"] != "plain":
        entry["value_form"] = pv["form"]
        entry["value_raw"] = pv["raw"]
        if pv["form"] == "triple":
            entry[f"value_min_{value_key.split('_', 1)[1]}"] = (
                pv["min"] * factor)
            entry[f"value_max_{value_key.split('_', 1)[1]}"] = (
                pv["max"] * factor)
        elif pv["form"] == "product":
            entry["value_factors"] = pv["factors"]
            if pv["suffixed"]:
                entry["value_suffixed"] = True
    _disclose_form(sink, pv, line_no, snippet)
    bucket.append(entry)


def _parse_header_kw(
    tokens: list[str],
    header: dict[str, Any],
    unit_factors: dict[str, float],
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> None:
    """头部指令行（*SPEF/*DESIGN/*单位族/*DIVIDER 族/*SCALE）。"""
    kw = tokens[0].upper()
    quoted = [t.strip('"') for t in tokens[1:]]
    if kw == "*SPEF":
        header["spef_version"] = quoted[0] if quoted else ""
    elif kw == "*DESIGN":
        header["design"] = quoted[0] if quoted else None
    elif kw in ("*DATE", "*VENDOR", "*PROGRAM", "*VERSION"):
        header[kw[1:].lower()] = quoted[0] if quoted else None
    elif kw == "*DESIGN_FLOW":
        header["design_flow"] = quoted
    elif kw == "*DIVIDER":
        header["dividers"]["divider"] = quoted[0] if quoted else "/"
    elif kw == "*DELIMITER_CHAR":
        header["dividers"]["delimiter"] = quoted[0] if quoted else ":"
    elif kw == "*BUS_DELIMITER_CHAR":
        header["bus_delimiters"] = [
            quoted[0] if len(quoted) > 0 else "[",
            quoted[1] if len(quoted) > 1 else "]",
        ]
    elif kw in ("*T_UNIT", "*C_UNIT", "*R_UNIT", "*L_UNIT"):
        kind = kw[1].lower()  # t/c/r/l
        if len(tokens) < 3:
            sink.warn(
                f"单位声明字段不足（第 {line_no} 行）: {' '.join(tokens)}——跳过",
                tier=TIER_UNPARSED,
                reason="unit_declaration_insufficient_fields",
                line=line_no, snippet=snippet)
            return
        try:
            multiplier = float(tokens[1])
        except ValueError:
            sink.warn(
                f"单位乘数非数值（第 {line_no} 行）: {tokens[1]}——跳过",
                tier=TIER_UNPARSED, reason="unit_multiplier_non_numeric",
                line=line_no, snippet=snippet)
            return
        unit = tokens[2]
        base = spef_unit_factor(kind, unit)
        if base is None:
            # fail-closed：未知单位 warning+系数 1.0（原值保留，不猜量纲）
            sink.warn(
                f"未知{kind.upper()}单位 {unit!r}（第 {line_no} 行）——"
                "系数取 1.0 原值保留",
                tier=TIER_UNSUPPORTED_3,
                reason="unknown_unit_factor_defaults_1",
                line=line_no, snippet=snippet)
            base = 1.0
        unit_factors[kind] = multiplier * base
        header["units"][kind] = {
            "declared": f"{tokens[1]} {unit}",
            "factor_si": unit_factors[kind],
        }
    elif kw == "*SCALE":
        header["scale"] = list(tokens[1:])
    else:
        # 调用方只送已知集；兜底 fail-soft 不炸（防未来分派表漂移）
        sink.warn(
            f"头部指令未分派 {tokens[0]}（第 {line_no} 行）——跳过",
            tier=TIER_UNSUPPORTED_1, reason="header_instruction_undispatched",
            line=line_no, snippet=snippet)


def _add_name_map_entry(
    tokens: list[str],
    name_map: dict[str, str],
    name_map_reverse: dict[str, str],
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> None:
    """``*NAME_MAP`` 行：``*id name``——重复 id 后者覆盖+warning；重复名
    如实告警（反查表首 id 胜出）。"""
    id_tok = tokens[0]
    map_id = id_tok[1:] if id_tok.startswith("*") else id_tok
    if len(tokens) < 2:
        sink.warn(
            f"NAME_MAP 行缺名（第 {line_no} 行）: {' '.join(tokens)}——跳过",
            tier=TIER_UNPARSED, reason="name_map_entry_missing_name",
            line=line_no, snippet=snippet)
        return
    map_name = tokens[1]
    if len(tokens) > 2:
        sink.warn(
            f"NAME_MAP 行多余词（第 {line_no} 行）——取前两词",
            tier=TIER_UNSUPPORTED_3, reason="name_map_extra_tokens_dropped",
            line=line_no, snippet=snippet)
    if map_id in name_map:
        sink.warnings.append(
            f"NAME_MAP 重复 id {id_tok}（第 {line_no} 行）——"
            f"后者 {map_name!r} 覆盖前者 {name_map[map_id]!r}")
        old_name = name_map[map_id]
        if name_map_reverse.get(old_name) == map_id:
            del name_map_reverse[old_name]
    prior = name_map_reverse.get(map_name)
    if prior is not None and prior != map_id:
        sink.warnings.append(
            f"NAME_MAP 重复名 {map_name!r}（id {prior} 与 "
            f"{id_tok}）——反查表首 id 胜出")
    else:
        name_map_reverse[map_name] = map_id
    name_map[map_id] = map_name


def _add_port_entry(
    tokens: list[str],
    ports: list[dict[str, Any]],
    name_map: dict[str, str],
    delimiter: str,
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> None:
    """``*PORTS`` 行：``name direction``（id 引用形态展开；方向词表外/缺
    方向 → direction 如实 None+warning）。"""
    port_name = _resolve_token(tokens[0], name_map, delimiter)
    direction: str | None = None
    if len(tokens) >= 2:
        direction = tokens[1]
        if direction not in DIRECTIONS:
            sink.warn(
                f"PORTS 方向词表外（第 {line_no} 行）: {direction}"
                "——direction 如实 None",
                tier=TIER_UNSUPPORTED_3,
                reason="port_direction_out_of_vocabulary",
                line=line_no, snippet=snippet)
            direction = None
    else:
        sink.warn(
            f"PORTS 行缺方向（第 {line_no} 行）: {' '.join(tokens)}"
            "——direction 如实 None",
            tier=TIER_UNSUPPORTED_3, reason="port_direction_missing",
            line=line_no, snippet=snippet)
    ports.append({"name": port_name, "direction": direction})


def _apply_value_continuation(
    tokens: list[str],
    net: dict[str, Any],
    sub: str,
    last_value: tuple[str, int] | None,
    sink: _DiagSink,
    line_no: int,
    snippet: str,
) -> bool:
    """``+``/``-`` 续行：对该段最近一条已解析元件值做算术续行（值±增量）。

    增量限 header 量纲形态（plain/d_exponent/无后缀乘积——带后缀增量
    与头部量纲混算两读不可判，绝不猜）。可续 → 原位更新该元件值并落
    ``value_continuations`` 事件（返回 True）；不可续 → warning+跳行+
    tier 诊断（返回 False，不再静默）。
    """
    op = tokens[0]
    label = sub
    value_key = {"CAP": "value_far", "RES": "value_ohm", "IND": "value_henry"}[sub]
    family = {"CAP": ("caps_gnd", "caps_cpl"), "RES": ("res",),
              "IND": ("inds",)}[sub]
    if last_value is None:
        sink.warn(
            f"{label} 续行无前置元件可续（第 {line_no} 行）: "
            f"{' '.join(tokens)}——跳过",
            tier=TIER_UNPARSED, reason="continuation_without_previous_element",
            line=line_no, snippet=snippet)
        return False
    bucket_name, idx = last_value
    if bucket_name not in family:
        sink.warn(
            f"{label} 续行无前置元件可续（第 {line_no} 行）: "
            f"{' '.join(tokens)}——跳过",
            tier=TIER_UNPARSED, reason="continuation_without_previous_element",
            line=line_no, snippet=snippet)
        return False
    pv = parse_spef_value(tokens[1])
    if not pv["ok"]:
        sink.warn(
            f"{label} 续行增量不可解析（第 {line_no} 行）: {tokens[1]}——跳过",
            tier=value_fail_tier(pv["reason"]),
            reason=f"continuation_{pv['reason']}",
            line=line_no, snippet=snippet)
        return False
    if pv["form"] == "triple":
        sink.warn(
            f"{label} 续行增量形态不支持（第 {line_no} 行）: {tokens[1]}——跳过",
            tier=TIER_UNSUPPORTED_2,
            reason="continuation_delta_triple_unimplemented",
            line=line_no, snippet=snippet)
        return False
    if pv["form"] == "product" and pv["suffixed"]:
        sink.warn(
            f"{label} 续行增量量纲两读不可判（第 {line_no} 行）: "
            f"{tokens[1]}——跳过",
            tier=TIER_UNSUPPORTED_1,
            reason="continuation_delta_dimension_ambiguous",
            line=line_no, snippet=snippet)
        return False
    bucket = net[bucket_name]
    factor = _current_factor(net, sub)
    delta = _scaled_value(pv, factor)
    entry = bucket[idx]
    sign = 1.0 if op == "+" else -1.0
    entry[value_key] = entry[value_key] + sign * delta
    net.setdefault("_continuations", []).append({
        "section": sub,
        "bucket": bucket_name,
        "element_index": idx,
        "op": op,
        "delta_si": sign * delta,
        "value_key": value_key,
        "line": line_no,
        "raw": snippet,
    })
    return True


def _current_factor(net: dict[str, Any], sub: str) -> float:
    """续行增量换算系数（解析主循环注入的当时系数快照）。"""
    key = {"CAP": "c", "RES": "r", "IND": "l"}[sub]
    return net["_factors"][key]


def parse_spef(text: str) -> dict[str, Any]:
    """SPEF 文本 → 结构化 dict（纯函数；不做电气结论只做结构提取）。

    返回键集（PARSER_SCHEMA_VERSION=1.0 契约；全 JSON 原生类型）::

        {
          "schema": "spef/1.0",
          "header": {"spef_version", "design", "units": {"r","c","l","t"},
                     "dividers": {"divider","delimiter"},
                     "bus_delimiters": [左, 右], ...其余头部声明如实},
          "name_map": {id: name},          # id→name 主映射
          "name_map_reverse": {name: id},  # 反查（重名首 id 胜出）
          "ports": [{name, direction}],
          "nets": [{id, name, total_cap_header, total_cap_far, conn,
                    caps_gnd, caps_cpl, res, inds, cap_sum_far,
                    cap_rel_diff, res_count, ind_count, line, ...}],
          "stats": {...计数面},
          "warnings": [str, ...],
          "diagnostics": [{tier, parser, reason, line, snippet}, ...],
          "value_continuations": [{section, bucket, element_index, op,
                                   delta_si, value_key, line, raw}, ...],
        }

    ``diagnostics``/``value_continuations`` 为 AX-6/数值扩展附加键（纯
    增量，既有键与语义零变化）。D_NET 内续行事件同时镜像在该 net 的
    ``continuations`` 键下（net 级消费面）。

    缺 ``*SPEF`` 头/空文本 → :class:`SpefParseError`（文件身份致命，
    service 层转 error 信封）。
    """
    sink = _DiagSink("spef")
    header: dict[str, Any] = {
        "spef_version": None,
        "design": None,
        "units": {"r": None, "c": None, "l": None, "t": None},
        "dividers": {"divider": "/", "delimiter": ":"},
        "bus_delimiters": ["[", "]"],
    }
    # 当前生效换算系数（单位声明随见随更新；CAP/RES/IND 行按当时系数换算）
    unit_factors: dict[str, float] = {"r": 1.0, "c": 1.0, "l": 1.0, "t": 1.0}
    name_map: dict[str, str] = {}
    name_map_reverse: dict[str, str] = {}
    ports: list[dict[str, Any]] = []
    nets: list[dict[str, Any]] = []
    saw_spef_kw = False

    # 段状态机：header（缺省）/name_map/ports/dnet（+dnet 内子段 sub）
    section = "header"
    sub: str | None = None
    net: dict[str, Any] | None = None
    # 续行锚：该 D_NET 内最近一条已解析元件值 → (bucket, 下标)；
    # CAP 的 bucket ∈ caps_gnd/caps_cpl，RES/IND 固定。新 D_NET 复位。
    last_value: tuple[str, int] | None = None

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(raw)
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        tokens = _tokenize(stripped)
        kw = tokens[0].upper()

        # ── 星词指令行 ─────────────────────────────────────────────
        if kw == "*SPEF":
            saw_spef_kw = True
            _parse_header_kw(tokens, header, unit_factors, sink, line_no,
                             stripped)
            continue
        if kw in ("*DESIGN", "*DATE", "*VENDOR", "*PROGRAM", "*VERSION",
                  "*DESIGN_FLOW", "*DIVIDER", "*DELIMITER_CHAR",
                  "*BUS_DELIMITER_CHAR", "*T_UNIT", "*C_UNIT", "*R_UNIT",
                  "*L_UNIT", "*SCALE"):
            _parse_header_kw(tokens, header, unit_factors, sink, line_no,
                             stripped)
            continue
        if kw == "*NAME_MAP":
            section = "name_map"
            sub = None
            continue
        if kw == "*PORTS":
            section = "ports"
            sub = None
            continue
        if kw == "*D_NET":
            section = "dnet"
            sub = None
            last_value = None
            if len(tokens) < 3:
                sink.warn(
                    f"D_NET 行字段不足（第 {line_no} 行）: {' '.join(tokens)}——跳过",
                    tier=TIER_UNPARSED, reason="dnet_insufficient_fields",
                    line=line_no, snippet=stripped)
                net = None
                continue
            id_raw = tokens[1]
            net_id = id_raw[1:] if id_raw.startswith("*") else id_raw
            # 展开名与节点引用同口径（*id 查表/未映射保真 <*id>/字面名原样）
            name = _resolve_token(id_raw, name_map,
                                  header["dividers"]["delimiter"])
            pv = parse_spef_value(tokens[2])
            if pv["ok"]:
                total_header: float | None = pv["value"]
            else:
                sink.warn(
                    f"D_NET 总电容非数值（第 {line_no} 行）: {tokens[2]}——如实 None",
                    tier=value_fail_tier(pv["reason"]), reason=pv["reason"],
                    line=line_no, snippet=stripped)
                total_header = None
            net = {
                "id": net_id,
                "name": name,
                "total_cap_header": total_header,
                "total_cap_far": (
                    None if total_header is None
                    else _scaled_value(pv, unit_factors["c"])),
                "conn": [],
                "caps_gnd": [],
                "caps_cpl": [],
                "res": [],
                "inds": [],
                "cap_sum_far": 0.0,
                "cap_rel_diff": None,
                "res_count": 0,
                "ind_count": 0,
                "line": line_no,
                "_factors": {"c": unit_factors["c"], "r": unit_factors["r"],
                             "l": unit_factors["l"]},
            }
            if pv["ok"] and pv["form"] != "plain":
                net["total_cap_form"] = pv["form"]
                net["total_cap_raw"] = pv["raw"]
                if pv["form"] == "triple":
                    net["total_cap_min"] = pv["min"]
                    net["total_cap_max"] = pv["max"]
                elif pv["form"] == "product" and pv["suffixed"]:
                    net["total_cap_suffixed"] = True
            if pv["ok"]:
                _disclose_form(sink, pv, line_no, stripped)
            nets.append(net)
            continue
        if kw in D_NET_SECTIONS:
            if section != "dnet" or net is None:
                sink.warn(
                    f"{kw} 段外出现（第 {line_no} 行）——跳过",
                    tier=TIER_UNPARSED, reason="section_keyword_outside_dnet",
                    line=line_no, snippet=stripped)
                continue
            sub = kw[1:]  # CONN/CAP/RES/IND
            continue
        if kw == "*END":
            if net is not None and section == "dnet":
                _finalize_net(net, sink)
                net = None
            section = "header"
            sub = None
            continue
        # ── 段内数据行（先于未知指令兜底分派——NAME_MAP/PORTS 的 *id 形态
        #    与 CONN 的 *P/*I 行都以星词起头，不得被未知指令分支吞掉）──
        star_ref = kw.startswith("*") and kw[1:2].isdigit()
        if section == "name_map" and (star_ref or not kw.startswith("*")):
            _add_name_map_entry(tokens, name_map, name_map_reverse,
                                sink, line_no, stripped)
            continue
        if section == "ports" and (star_ref or not kw.startswith("*")):
            _add_port_entry(tokens, ports, name_map,
                            header["dividers"]["delimiter"],
                            sink, line_no, stripped)
            continue
        if (section == "dnet" and net is not None and sub == "CONN"
                and kw in ("*P", "*I")):
            _parse_conn_line(tokens, net, name_map,
                             header["dividers"]["delimiter"],
                             sink, line_no, stripped)
            continue
        if kw.startswith("*"):
            # 未知指令：warning+跳过（fail-soft 不中断）
            sink.warn(
                f"未知指令 {tokens[0]}（第 {line_no} 行）——跳过",
                tier=TIER_UNSUPPORTED_1, reason="unknown_instruction",
                line=line_no, snippet=stripped)
            continue

        # ── 非星词数据行（D_NET 子段分派）──────────────────────────
        if section == "dnet" and net is not None:
            if (sub in ("CAP", "RES", "IND") and tokens[0] in ("+", "-")
                    and len(tokens) == 2):
                if _apply_value_continuation(tokens, net, sub, last_value,
                                             sink, line_no, stripped):
                    continue
                # 不可续 → 落入常规病态行路径（warning+diag 已发），
                # 不再重复解析
                continue
            if sub == "CAP":
                before = (len(net["caps_gnd"]), len(net["caps_cpl"]))
                _parse_cap_line(tokens, net, name_map,
                                header["dividers"]["delimiter"],
                                unit_factors["c"], sink, line_no, stripped)
                if len(net["caps_gnd"]) > before[0]:
                    last_value = ("caps_gnd", len(net["caps_gnd"]) - 1)
                elif len(net["caps_cpl"]) > before[1]:
                    last_value = ("caps_cpl", len(net["caps_cpl"]) - 1)
            elif sub == "RES":
                before = len(net["res"])
                _parse_branch_line(
                    tokens, net["res"], "RES", unit_factors["r"],
                    "value_ohm", name_map,
                    header["dividers"]["delimiter"], sink, line_no, stripped)
                if len(net["res"]) > before:
                    last_value = ("res", len(net["res"]) - 1)
            elif sub == "IND":
                before = len(net["inds"])
                _parse_branch_line(
                    tokens, net["inds"], "IND", unit_factors["l"],
                    "value_henry", name_map,
                    header["dividers"]["delimiter"], sink, line_no, stripped)
                if len(net["inds"]) > before:
                    last_value = ("inds", len(net["inds"]) - 1)
            else:
                sink.warn(
                    f"D_NET 内游离行（第 {line_no} 行）: "
                    f"{' '.join(tokens[:3])}——跳过",
                    tier=TIER_UNPARSED, reason="dnet_stray_line",
                    line=line_no, snippet=stripped)
            continue
        # header 段（或段外）游离数据行
        sink.warn(
            f"游离数据行（第 {line_no} 行）: {' '.join(tokens[:3])}——跳过",
            tier=TIER_UNPARSED, reason="stray_data_line",
            line=line_no, snippet=stripped)

    if net is not None:
        sink.warn("*END 缺失（文件尾 D_NET 未闭合）——按文件尾收口",
                  tier=TIER_UNSUPPORTED_3, reason="dnet_unclosed_at_eof")
        _finalize_net(net, sink)
    if not saw_spef_kw:
        raise SpefParseError(
            "缺少 *SPEF 头（非 SPEF 文件或空文件）——拒绝解析")

    n_gnd = sum(len(n["caps_gnd"]) for n in nets)
    n_cpl = sum(len(n["caps_cpl"]) for n in nets)
    n_res = sum(len(n["res"]) for n in nets)
    n_ind = sum(len(n["inds"]) for n in nets)
    # net 级续行事件镜像 + 运行态键出清（_factors 为解析期系数快照，
    # 不进 JSON 输出面——续行 delta_si 已按当时系数折算落档）
    value_continuations: list[dict[str, Any]] = []
    for n in nets:
        conts = n.pop("_continuations", [])
        n.pop("_factors", None)
        if conts:
            n["continuations"] = conts
            value_continuations.extend(conts)
    return {
        "schema": f"spef/{PARSER_SCHEMA_VERSION}",
        "header": header,
        "name_map": name_map,
        "name_map_reverse": name_map_reverse,
        "ports": ports,
        "nets": nets,
        "stats": {
            "n_name_map": len(name_map),
            "n_ports": len(ports),
            "n_nets": len(nets),
            "n_conn": sum(len(n["conn"]) for n in nets),
            "n_caps_gnd": n_gnd,
            "n_caps_cpl": n_cpl,
            "n_res": n_res,
            "n_ind": n_ind,
            "n_warnings": len(sink.warnings),
        },
        "warnings": sink.warnings,
        "diagnostics": sink.diags,
        "value_continuations": value_continuations,
    }


def _finalize_net(net: dict[str, Any], sink: _DiagSink) -> None:
    """D_NET 收口：cap 求和与头部申报一致性三数字（不设硬门只报告）。

    ``cap_sum_far``=段内全部电容（对地+耦合）之和；偏差成因（提取器
    口径不一、coupling 只计一端等）由消费方复核——解析层只出数字。
    """
    total = net["total_cap_far"]
    cap_sum = sum(c["value_far"] for c in net["caps_gnd"]) + sum(
        c["value_far"] for c in net["caps_cpl"])
    net["cap_sum_far"] = cap_sum
    net["res_count"] = len(net["res"])
    net["ind_count"] = len(net["inds"])
    if total is None:
        net["cap_rel_diff"] = None
    elif total == 0.0:
        # 申报为零：除零未定义——如实 None（全零段同此口径）
        net["cap_rel_diff"] = None
    else:
        net["cap_rel_diff"] = (cap_sum - total) / abs(total)


# --------------------------------------------------------------------------- #
# 拓扑三函数（纯派生视图；不改 doc）
# --------------------------------------------------------------------------- #


def _net_union_find(net: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    """单 net 并查集：返回 (node→root 映射, 全节点集)。

    节点源=CONN 声明+四段元件端点；元件对（耦合电容/电阻/电感）逐对
    union，对地电容为单节点自环（不改变分量）。
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        # 路径压缩
        while parent.get(x, x) != x:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def touch(*nodes: str) -> None:
        for n in nodes:
            parent.setdefault(n, n)

    for c in net["conn"]:
        touch(c["node"])
    for c in net["caps_gnd"]:
        touch(c["node"])
    for c in net["caps_cpl"]:
        touch(c["node1"], c["node2"])
        union(c["node1"], c["node2"])
    for r in net["res"]:
        touch(r["node1"], r["node2"])
        union(r["node1"], r["node2"])
    for ind in net["inds"]:
        touch(ind["node1"], ind["node2"])
        union(ind["node1"], ind["node2"])
    return {n: find(n) for n in parent}, set(parent)


def spef_topology_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """逐 net 拓扑摘要：节点数/元件数/连通分量数（并查集）+孤立节点清单。

    孤立节点口径=**仅 CONN 声明且零元件触碰**的节点如实列出（宁多报
    不误报；孤立=解析层判据非电气结论）。返回::

        {"nets": [{id, name, node_count, element_count,
                   component_count, isolated_nodes}, ...按 doc 序],
         "totals": {n_nets, n_nodes, n_elements, n_components,
                    n_isolated}}
    """
    per_net: list[dict[str, Any]] = []
    tot_nodes = 0
    tot_elems = 0
    tot_comps = 0
    tot_isolated = 0
    for net in doc["nets"]:
        root_of, nodes = _net_union_find(net)
        element_nodes: set[str] = set()
        for c in net["caps_gnd"]:
            element_nodes.add(c["node"])
        for c in net["caps_cpl"]:
            element_nodes.update((c["node1"], c["node2"]))
        for r in net["res"]:
            element_nodes.update((r["node1"], r["node2"]))
        for ind in net["inds"]:
            element_nodes.update((ind["node1"], ind["node2"]))
        # 孤立=CONN 声明零元件触碰（宁多报不误报——如实列全）
        isolated = sorted(
            {c["node"] for c in net["conn"]} - element_nodes)
        n_elements = (len(net["caps_gnd"]) + len(net["caps_cpl"])
                      + len(net["res"]) + len(net["inds"]))
        n_components = len({root_of[n] for n in nodes})
        per_net.append({
            "id": net["id"],
            "name": net["name"],
            "node_count": len(nodes),
            "element_count": n_elements,
            "component_count": n_components,
            "isolated_nodes": isolated,
        })
        tot_nodes += len(nodes)
        tot_elems += n_elements
        tot_comps += n_components
        tot_isolated += len(isolated)
    return {
        "nets": per_net,
        "totals": {
            "n_nets": len(per_net),
            "n_nodes": tot_nodes,
            "n_elements": tot_elems,
            "n_components": tot_comps,
            "n_isolated": tot_isolated,
        },
    }


def spef_coupling_stats(
    doc: dict[str, Any], top_k: int = 5
) -> dict[str, Any]:
    """耦合电容统计：总数/总和对地总和比/最强耦合对 top-k。

    排序键=``(-值, 全局序号)``——值并列时按文档序稳定（确定性排序）；
    对地总和为零时比值如实 None（除零未定义）。
    """
    n_cpl = 0
    n_gnd = 0
    cpl_sum = 0.0
    gnd_sum = 0.0
    pairs: list[dict[str, Any]] = []
    seq = 0
    for net in doc["nets"]:
        n_gnd += len(net["caps_gnd"])
        gnd_sum += sum(c["value_far"] for c in net["caps_gnd"])
        for c in net["caps_cpl"]:
            n_cpl += 1
            cpl_sum += c["value_far"]
            pairs.append({
                "net": net["name"],
                "node1": c["node1"],
                "node2": c["node2"],
                "value_far": c["value_far"],
                "_seq": seq,
            })
            seq += 1
    pairs.sort(key=lambda p: (-p["value_far"], p["_seq"]))
    k = max(0, int(top_k))
    top = [
        {"net": p["net"], "node1": p["node1"], "node2": p["node2"],
         "value_far": p["value_far"]}
        for p in pairs[:k]
    ]
    return {
        "n_coupling": n_cpl,
        "n_ground": n_gnd,
        "coupling_sum_far": cpl_sum,
        "ground_sum_far": gnd_sum,
        "coupling_to_ground_ratio": (
            None if gnd_sum == 0.0 else cpl_sum / gnd_sum),
        "top_pairs": top,
    }


def spef_net_lookup(doc: dict[str, Any], name: str) -> dict[str, Any] | None:
    """按展开名查 net 全量视图（未命中返回 None——调用方分型）。"""
    for net in doc["nets"]:
        if net["name"] == name:
            return net
    return None
