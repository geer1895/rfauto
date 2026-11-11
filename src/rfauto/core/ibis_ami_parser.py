"""IBIS-AMI（.ami 算法建模接口参数文件，IBIS 7.0 §9 AMI）确定性解析内核
（aurora_q 席位 Q-X86，2026-11-08）。

SerDes 链路仿真标配的 AMI 参数文件（IBIS 的算法建模扩展——.ibs 缓冲
模型由 core/ibis_parser.py Q-X46 承担，.ami 承担可执行模型参数声明）
的只读结构化解析。词法与语义全在 core 确定性内核（铁律 7：结构化数据
只出自数据源文本本身，LLM/agent 永不产生物理数字）。服务包装见
:mod:`rfauto.service.ibis_ami_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/ibis_ami.py。解析器集群四件套参照：core/ibis_parser.py
（Q-X46 同代 IBIS 词法——``|`` 注释同源）、core/bsdl_parser.py（括号
节嵌套+fail-soft 口径同款）、cli/domains/stil.py（域形态）、
service/verilog_netlist_service.py（信封）。

格式面（IBIS 7.0 AMI 公开口径，任务书契约）：

- 词法：``|`` 行注释（行中任何位置起至行尾——IBIS v4.2 §3.1 同款）；
  ``(SectionName ...)`` 括号节嵌套（S-表达式形态）；``"..."`` 引号串
  （内容原样，无转义语义）；节名=首个裸 atom 子项。词法扫描用
  :data:`_TOKEN_RE` 的 ``match(text, i)`` **定点形态**（Q-X80 词法教训：
  禁止 ``i = m.end()`` 配切片推进——坐标回跳死循环；定点 match 对任意
  输入恒前进恒终止）；
- 双主节：``(RESERVED ...)`` 保留参数字典（扁平 ``(键 值)`` 条目——
  AMI_Version/Ignore_IL/Init_Returns_Impulse/GetWave_Exists/
  Use_Init_Output 等标准键；**必需键缺失检测**=必备集常量
  :data:`REQUIRED_RESERVED_KEYS` − 实际键集（大小写不敏感）→
  ``missing_reserved`` 如实清单**不硬拒**——#122 族诚实语义）；未识别
  保留键照常登记（保留集开放，零静默丢弃）；重复键后列覆盖+警告；
- ``(Model_Specific ...)`` 参数逐个 ``(参数名 (describe "...") (type
  float|boolean|integer) (default v) (parse_inbounds ...) (usage ...))``
  五键逐参：type 归一小写闭集 :data:`PARAM_TYPES`（非法→warning+raw
  保留）；default 记 raw+按 type 分派 typed（float/int 转换失败、
  boolean 非 true/false 字面→warning+typed None）；parse_inbounds 的
  ``(a:b)`` 开闭区间结构化（``[``/``(`` 括号定端点开闭，无括号=闭——
  AMI in-bounds 含端点惯例；非数值端点/形态不识→warning+structured
  None+raw 保留）；describe/usage 如实字符串；Description/
  In_Bounds 别名同收（真实供应商文件大小写惯用形态）；
- 辅助：顶层 ``(DLL_file "...")``/``(SoC_file "...")`` 引用键值对如实
  登记 :data:`DLL_SOC_KEYS`（大小写不敏感，键保留原拼写）；顶层
  ``(ami_version v)`` 在 RESERVED 缺版本时兜底（RESERVED 优先，重复
  警告）；其余未识别顶层节→warning+忽略（零静默丢弃）；
- AMI_Version 档位表 :data:`AMI_VERSIONS`（未知档位 warning+保留）。

结构化输出（:func:`parse_ami`，全 JSON 原生类型）::

    {"ami_version": str|None,
     "reserved": {键(原拼写): str|list[str]|None},
     "missing_reserved": [必备集缺失键(canonical 名), ...],
     "model_specific": {参数名: {describe, type, default_raw,
                                default_typed, bounds_raw, bounds,
                                usage, line}},
     "dll_refs": {键(原拼写): str|None},
     "stats": {"n_reserved", "n_model_specific", "n_dll_refs",
               "n_missing_reserved", "n_warnings"},
     "warnings": [str, ...]}

其中 ``bounds`` = ``{"lo", "hi", "lo_closed", "hi_closed"}``（开闭区间
结构化）或 None（raw 缺失/不识——raw 恒在 ``bounds_raw``）。

查询三函数（服务/CLI 上层消费）：

- :func:`ami_param_lookup`：参数名查参数（Model_Specific 优先、
  RESERVED 回落，大小写不敏感——AMI 参数名不敏感语义）；带 ``source``
  如实标注；未命中→None 调用方分型；
- :func:`ami_required_check`：必备保留键三清单（complete 布尔+missing
  canonical+present）——缺失如实清单不硬拒（任务书口径）；
- :func:`ami_defaults_table`：Model_Specific 参数→default_typed 平表
  （缺 default/type 非法的参数记 None 键——不隐键）。

错误面：空文件/仅注释空白→ :class:`AmiParseError`（ValueError 子类，
文件身份级致命——bsdl 同款口径）；其余病态（括号失衡/多余右括号/
空节/裸 token/缺值/重复键/type 非法/bounds 不识）一律 warning+如实
收编（fail-soft——截断文件不炸全文）。确定性（同输入同输出）、零 IO
（纯文本进出）、零第三方依赖。本模块不设 ``__all__``（无 __all__ 的
非门面文件不进 tests/gold/public_api.json——bsdl_parser/stil_parser
同款先例，新模块零金快照漂移）。

已知限制（如实登记不展开）：Reserved 参数值不做类型化（raw 原样——
标准保留键值形态由消费方解释）；``(a:b)`` 逗号分隔变体不识别（仅
冒号——任务书口径）；嵌套节内嵌套节（三重以上括号体）只消费两级，
更深层级随子键"含嵌套节"警告忽略。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: AMI_Version 已知档位表（IBIS-AMI 历代版本；未知档位→warning+保留）。
AMI_VERSIONS: tuple[str, ...] = (
    "1.0", "1.1", "2.0", "2.1", "3.0", "3.1", "3.2",
    "4.0", "4.1", "5.0", "5.1", "6.0", "6.1", "6.2",
)

#: RESERVED 必备保留键（缺失→missing_reserved 如实清单，不硬拒——任务书口径）。
REQUIRED_RESERVED_KEYS: tuple[str, ...] = (
    "AMI_Version", "Ignore_IL", "Init_Returns_Impulse",
    "GetWave_Exists", "Use_Init_Output",
)

#: Model_Specific 参数 type 闭集（归一小写后比对；非法→warning+raw 保留）。
PARAM_TYPES: tuple[str, ...] = ("float", "boolean", "integer")

#: 顶层 DLL/SoC 引用键闭集（大小写不敏感匹配；登记保留原拼写）。
DLL_SOC_KEYS: tuple[str, ...] = ("dll_file", "soc_file")

#: Model_Specific 参数子键别名 → 规范键（真实文件 Description/In_Bounds
#: 大小写惯用形态同收；未识别子键→warning+跳过）。
_PARAM_KEY_ALIASES: dict[str, str] = {
    "describe": "describe",
    "description": "describe",
    "type": "type",
    "default": "default",
    "parse_inbounds": "bounds",
    "in_bounds": "bounds",
    "usage": "usage",
}

#: 词法主扫描：空白/| 注释/闭合引号串/未闭合引号串(EOF)/左右括号/裸 atom。
#: 交替支全字符覆盖（任意输入恒匹配恒前进）；用 ``match(text, i)`` 定点
#: 形态扫描（Q-X80 教训：禁 ``i = m.end()`` 配切片——坐标回跳死循环）。
_TOKEN_RE = re.compile(
    r"(?P<ws>[ \t\r\n\f\v]+)"
    r"|(?P<comment>\|[^\n]*)"
    r'|"(?P<str>[^"]*)"'
    r'|"(?P<unclosed>[^"]*\Z)'
    r"|(?P<open>\()"
    r"|(?P<close>\))"
    r'|(?P<atom>[^\s()|"]+)'
)

#: in-bounds ``(a:b)`` 形态：可选端点括号定开闭（无括号=闭——AMI 惯例），
#: 冒号分隔（允许端点两侧空白）。端点 token 禁 ``: , ) ]`` 与空白。
_BOUNDS_RE = re.compile(
    r"^\s*(?P<lo_b>[\[(])?\s*(?P<lo>[^\s:,)\]]+)\s*:\s*"
    r"(?P<hi>[^\s:,)\]]+)\s*(?P<hi_b>[\])])?\s*$"
)


class AmiParseError(ValueError):
    """AMI 文件身份级致命错误（空文件/仅注释空白）——fail-soft 之外的
    唯一致命面。词法/结构病态不走本异常（warning+如实收编口径）。
    继承 ValueError（ibis_parser/bsdl_parser 同款口径）。"""


# --------------------------------------------------------------------------- #
# 词法：token 流（kind ∈ {"open","close","atom","str"}，携带行号）
# --------------------------------------------------------------------------- #


def _tokenize(text: str) -> tuple[list[tuple[str, str, int]], list[str]]:
    """AMI 文本 → (token 流, 词法警告)。

    token 三元组 ``(kind, value, line)``：open/close=括号、atom=裸词
    （空白/括号/竖线/引号终结）、str=引号串内容（``"`` 无转义语义——
    未闭合 fail-soft 至 EOF 如实收编+警告）。``|`` 注释至行尾（行中
    任何位置起——atom 内竖线亦截断，IBIS v4.2 §3.1 同源）。
    """
    tokens: list[tuple[str, str, int]] = []
    warns: list[str] = []
    line = 1
    i = 0
    n = len(text)
    while i < n:
        m = _TOKEN_RE.match(text, i)  # 定点形态：锚定 i 扫描（Q-X80 教训）
        if m is None:  # 交替支全字符覆盖——防御守卫（恒不触发）
            tokens.append(("atom", text[i], line))
            i += 1
            continue
        kind = m.lastgroup or ""
        if kind == "str":
            tokens.append(("str", m.group("str"), line))
        elif kind == "unclosed":
            warns.append(
                f"字符串引号未闭合（第 {line} 行）——至文件尾如实收编")
            tokens.append(("str", m.group("unclosed"), line))
        elif kind in ("open", "close", "atom"):
            tokens.append((kind, m.group(0), line))
        # ws/comment：跳过（注释零落 token）
        line += text.count("\n", i, m.end())
        i = m.end()
    return tokens, warns


# --------------------------------------------------------------------------- #
# 括号节森林（S-表达式两级内嵌——_Sect.items = 子节 | 字符串叶）
# --------------------------------------------------------------------------- #


@dataclass
class _Sect:
    """括号节：name=首个裸 atom 子项（None=空节）；items=子节或叶串。"""

    name: str | None
    line: int
    items: list[Any] = field(default_factory=list)


def _attach(sect: _Sect, stack: list[_Sect], forest: list[_Sect]) -> None:
    """闭合节挂载：栈非空挂父 items，栈空挂顶层森林（源序保持）。"""
    if stack:
        stack[-1].items.append(sect)
    else:
        forest.append(sect)


def _parse_forest(
    toks: list[tuple[str, str, int]], warnings: list[str]
) -> list[_Sect]:
    """token 流 → 顶层节森林（括号嵌套栈；fail-soft 口径）。

    多余 ``)``/空节 ``()``/顶层裸 token→警告跳过；EOF 括号失衡→警告+
    未闭合节按源序如实收编（截断文件不炸全文）。
    """
    forest: list[_Sect] = []
    stack: list[_Sect] = []
    for kind, value, ln in toks:
        if kind == "open":
            stack.append(_Sect(name=None, line=ln))
        elif kind == "close":
            if not stack:
                warnings.append(f"第 {ln} 行：多余的 ')'——跳过")
                continue
            sect = stack.pop()
            if sect.name is None:
                warnings.append(f"第 {ln} 行：空节 ()——跳过")
                continue
            _attach(sect, stack, forest)
        elif kind == "atom":
            if stack and stack[-1].name is None:
                stack[-1].name = value  # 节名=首个裸 atom 子项
            elif stack:
                stack[-1].items.append(value)
            else:
                warnings.append(f"第 {ln} 行：顶层裸 token {value!r}——跳过")
        elif kind == "str":
            if stack:
                stack[-1].items.append(value)
            else:
                warnings.append(f"第 {ln} 行：顶层裸字符串 {value!r}——跳过")
    if stack:
        warnings.append("括号失衡：EOF 仍有未闭合 '('——如实收编（fail-soft）")
        # 自内向外弹栈重建嵌套（截断处子节归回最近未闭合父节——保真）
        while stack:
            sect = stack.pop()
            if sect.name is None:
                warnings.append(
                    f"第 {sect.line} 行：无名空节（截断处）——丢弃")
                continue
            _attach(sect, stack, forest)
    return forest


def _sub_sects(items: list[Any]) -> list[_Sect]:
    """items 中的子节（叶串剔除——消费方按节分派）。"""
    return [x for x in items if isinstance(x, _Sect)]


def _leaves(items: list[Any]) -> list[str]:
    """items 中的叶串（嵌套子节剔除——调用方按计数警告）。"""
    return [x for x in items if isinstance(x, str)]


def _ci_key(table: dict[str, Any], ci: str) -> str | None:
    """大小写不敏感查表 → 原样键（未命中 None——bsdl _lookup_ci 同款）。"""
    return next((k for k in table if str(k).lower() == ci), None)


# --------------------------------------------------------------------------- #
# RESERVED / Model_Specific / DLL·SoC 消费
# --------------------------------------------------------------------------- #


def _merge_reserved(
    sect: _Sect, reserved: dict[str, Any], warnings: list[str]
) -> None:
    """RESERVED 节体 → 保留参数字典（扁平 (键 值) 条目）。

    值形态：单 token→str、多 token→list[str]（如实）、缺值→None+警告；
    含嵌套子节→警告忽略嵌套；重复键（大小写不敏感）后列覆盖+警告。
    """
    for child in _sub_sects(sect.items):
        key = child.name or ""
        if not key:
            continue  # 空节已在森林阶段剔除——防御
        leaves = _leaves(child.items)
        if len(leaves) != len(child.items):
            warnings.append(
                f"第 {child.line} 行：RESERVED 参数 {key!r} 含嵌套子节——忽略")
        if not child.items:
            warnings.append(
                f"第 {child.line} 行：RESERVED 参数 {key!r} 缺值——记 None")
            value: Any = None
        elif len(leaves) == 1:
            value = leaves[0]
        elif leaves:
            value = list(leaves)
        else:
            value = None  # 仅嵌套节无叶——已在上面警告，记 None
        dup = _ci_key(reserved, key.lower())
        if dup is not None:
            warnings.append(
                f"第 {child.line} 行：RESERVED 参数 {key!r} 重复——后列覆盖")
            reserved.pop(dup)
        reserved[key] = value


def _leaf_value(
    child: _Sect, what: str, name: str, warnings: list[str], *,
    join: bool = False,
) -> str | None:
    """子节叶值提取：单叶直取/多叶 join 或取首+警告/无叶 None+警告。"""
    leaves = _leaves(child.items)
    if len(leaves) != len(child.items):
        warnings.append(
            f"第 {child.line} 行：参数 {name} 子键 {what} 含嵌套节——忽略")
    if not leaves:
        warnings.append(
            f"第 {child.line} 行：参数 {name} 子键 {what} 无内容——记 None")
        return None
    if join:
        return " ".join(leaves)
    if len(leaves) > 1:
        warnings.append(
            f"第 {child.line} 行：参数 {name} 子键 {what} 多值——取首个")
    return leaves[0]


def _typed_default(
    raw: str | None, typ: str | None, name: str, ln: int,
    warnings: list[str],
) -> Any:
    """default raw 按 type 分派 typed：float/integer 转换失败、boolean
    非 true/false 字面→warning+None；type 非法/缺失→None（raw 恒在）。"""
    if raw is None or typ is None:
        return None
    if typ == "float":
        try:
            return float(raw)
        except ValueError:
            warnings.append(
                f"第 {ln} 行：参数 {name} default {raw!r} 不可转 float"
                "——typed 记 None")
            return None
    if typ == "integer":
        try:
            return int(raw)
        except ValueError:
            warnings.append(
                f"第 {ln} 行：参数 {name} default {raw!r} 不可转 integer"
                "——typed 记 None")
            return None
    low = raw.lower()  # boolean
    if low == "true":
        return True
    if low == "false":
        return False
    warnings.append(
        f"第 {ln} 行：参数 {name} default {raw!r} 非 boolean 字面"
        "（true/false）——typed 记 None")
    return None


def _parse_bounds(
    raw: str | None, name: str, ln: int, warnings: list[str],
) -> dict[str, Any] | None:
    """in-bounds raw → 开闭区间结构化 {"lo","hi","lo_closed","hi_closed"}。

    ``[``/``(`` 定端点闭/开，无括号=闭（AMI in-bounds 含端点惯例）；
    形态不识/端点非数值→None（raw 恒在 bounds_raw）；下界>上界如实
    保留+警告。
    """
    if raw is None:
        return None
    m = _BOUNDS_RE.match(raw)
    if m is None:
        warnings.append(
            f"第 {ln} 行：参数 {name} in-bounds {raw!r} 形态不识"
            "（应 a:b / [a:b] / (a:b) / [a:b) 形态）——structured 记 None")
        return None
    lo_b = m.group("lo_b")
    hi_b = m.group("hi_b")
    try:
        lo = float(m.group("lo"))
        hi = float(m.group("hi"))
    except ValueError:
        warnings.append(
            f"第 {ln} 行：参数 {name} in-bounds 端点非数值——structured 记 None")
        return None
    if lo > hi:
        warnings.append(
            f"第 {ln} 行：参数 {name} in-bounds 下界 {lo:g} > 上界 {hi:g}"
            "——如实保留")
    return {
        "lo": lo, "hi": hi,
        "lo_closed": lo_b is None or lo_b == "[",
        "hi_closed": hi_b is None or hi_b == "]",
    }


def _parse_param(param: _Sect, warnings: list[str]) -> dict[str, Any]:
    """Model_Specific 单参数节 → 记录 dict（五键逐参；缺 default 警告）。"""
    name = param.name or ""
    out: dict[str, Any] = {
        "describe": None, "type": None, "default_raw": None,
        "default_typed": None, "bounds_raw": None, "bounds": None,
        "usage": None, "line": param.line,
    }
    seen: dict[str, _Sect] = {}
    for bare in _leaves(param.items):
        warnings.append(
            f"第 {param.line} 行：参数 {name} 含裸值 {bare!r}——忽略")
    for child in _sub_sects(param.items):
        canon = (_PARAM_KEY_ALIASES.get(child.name.lower())
                 if child.name else None)
        if canon is None:
            warnings.append(
                f"第 {child.line} 行：参数 {name} 未识别子键 "
                f"{child.name!r}——跳过")
            continue
        if canon in seen:
            warnings.append(
                f"第 {child.line} 行：参数 {name} 子键 {canon} 重复"
                "——后列覆盖")
        seen[canon] = child
    if not seen:
        warnings.append(
            f"第 {param.line} 行：参数 {name} 无五键子节——如实空登记")
    if "describe" in seen:
        out["describe"] = _leaf_value(
            seen["describe"], "describe", name, warnings)
    if "type" in seen:
        raw = _leaf_value(seen["type"], "type", name, warnings)
        if raw is not None:
            low = raw.lower()
            if low in PARAM_TYPES:
                out["type"] = low
            else:
                warnings.append(
                    f"第 {seen['type'].line} 行：参数 {name} type {raw!r} "
                    f"不在闭集 {list(PARAM_TYPES)}——raw 保留")
                out["type"] = raw
    if "default" in seen:
        raw = _leaf_value(
            seen["default"], "default", name, warnings, join=True)
        out["default_raw"] = raw
        out["default_typed"] = _typed_default(
            raw, out["type"], name, seen["default"].line, warnings)
    else:
        warnings.append(
            f"第 {param.line} 行：参数 {name} 缺 default 子节——如实登记")
    if "bounds" in seen:
        raw = _leaf_value(
            seen["bounds"], "parse_inbounds", name, warnings, join=True)
        out["bounds_raw"] = raw
        out["bounds"] = _parse_bounds(
            raw, name, seen["bounds"].line, warnings)
    if "usage" in seen:
        out["usage"] = _leaf_value(seen["usage"], "usage", name, warnings)
    return out


def _merge_model_specific(
    sect: _Sect, model_specific: dict[str, Any], warnings: list[str]
) -> None:
    """Model_Specific 节体 → 参数字典（重复参数名后列覆盖+警告）。"""
    for child in _sub_sects(sect.items):
        name = child.name or ""
        if not name:
            continue  # 空节已在森林阶段剔除——防御
        dup = _ci_key(model_specific, name.lower())
        if dup is not None:
            warnings.append(
                f"第 {child.line} 行：参数 {name!r} 重复——后列覆盖")
            model_specific.pop(dup)
        model_specific[name] = _parse_param(child, warnings)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def parse_ami(text: str) -> dict[str, Any]:
    """AMI 参数文件文本 → 结构化 dict（纯函数；只做结构提取不做仿真结论）。

    空文件/仅注释空白 → :class:`AmiParseError`（文件身份致命，service
    层转 error 信封）；其余病态一律 warning+如实收编（fail-soft）。
    返回键集见模块 docstring。
    """
    if not text or not text.strip():
        raise AmiParseError("空文件（无任何内容）——拒绝解析")
    core = "\n".join(
        ln.split("|", 1)[0] for ln in text.splitlines()).strip()
    if not core:
        raise AmiParseError("空文件（仅注释/空白）——拒绝解析")

    toks, lex_warns = _tokenize(text)
    warnings: list[str] = list(lex_warns)
    forest = _parse_forest(toks, warnings)

    reserved: dict[str, Any] = {}
    model_specific: dict[str, Any] = {}
    dll_refs: dict[str, Any] = {}
    top_ami_version: str | None = None
    n_reserved_sections = 0
    n_model_sections = 0

    for sect in forest:
        name = sect.name or ""
        lname = name.lower()
        if lname == "reserved":
            n_reserved_sections += 1
            if n_reserved_sections > 1:
                warnings.append(
                    f"第 {sect.line} 行：重复 RESERVED 节——合并"
                    "（后列覆盖）")
            _merge_reserved(sect, reserved, warnings)
        elif lname == "model_specific":
            n_model_sections += 1
            if n_model_sections > 1:
                warnings.append(
                    f"第 {sect.line} 行：重复 Model_Specific 节——合并"
                    "（后列覆盖）")
            _merge_model_specific(sect, model_specific, warnings)
        elif lname in DLL_SOC_KEYS:
            leaves = _leaves(sect.items)
            if not leaves:
                warnings.append(
                    f"第 {sect.line} 行：{name} 引用缺值——记 None")
                value: Any = None
            else:
                value = leaves[0]
            dup = _ci_key(dll_refs, lname)
            if dup is not None:
                warnings.append(
                    f"第 {sect.line} 行：{name} 重复——后列覆盖")
                dll_refs.pop(dup)
            dll_refs[name] = value
        elif lname == "ami_version":
            leaves = _leaves(sect.items)
            if top_ami_version is not None:
                warnings.append(
                    f"第 {sect.line} 行：顶层 ami_version 重复——后者忽略")
            elif leaves:
                top_ami_version = leaves[0]
            else:
                warnings.append(
                    f"第 {sect.line} 行：顶层 ami_version 缺值——忽略")
        else:
            warnings.append(
                f"第 {sect.line} 行：未识别顶层节 {name!r}——内容忽略")

    # ---- ami_version：RESERVED 优先，顶层兜底（重复警告）。 ----
    ami_version: str | None = None
    vkey = _ci_key(reserved, "ami_version")
    if vkey is not None:
        vval = reserved[vkey]
        if isinstance(vval, str):
            ami_version = vval
        elif isinstance(vval, list) and vval:
            ami_version = str(vval[0])
        if top_ami_version is not None:
            warnings.append("顶层 ami_version 与 RESERVED 重复——RESERVED 优先")
    elif top_ami_version is not None:
        ami_version = top_ami_version
    if ami_version is not None and ami_version not in AMI_VERSIONS:
        warnings.append(
            f"未知 AMI_Version 档位 {ami_version!r}（已知档位: "
            f"{', '.join(AMI_VERSIONS)}）——如实保留")

    missing_reserved = [
        k for k in REQUIRED_RESERVED_KEYS
        if _ci_key(reserved, k.lower()) is None
    ]

    return {
        "ami_version": ami_version,
        "reserved": reserved,
        "missing_reserved": missing_reserved,
        "model_specific": model_specific,
        "dll_refs": dll_refs,
        "stats": {
            "n_reserved": len(reserved),
            "n_model_specific": len(model_specific),
            "n_dll_refs": len(dll_refs),
            "n_missing_reserved": len(missing_reserved),
            "n_warnings": len(warnings),
        },
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 查询三函数（纯派生视图；不改 doc）
# --------------------------------------------------------------------------- #


def ami_param_lookup(doc: dict[str, Any], name: str) -> dict[str, Any] | None:
    """参数名查参数（Model_Specific 优先、RESERVED 回落；大小写不敏感
    ——AMI 参数名不敏感语义）。命中返回新 dict（``name``=doc 原样键、
    ``source``=model_specific|reserved 如实标注，其余字段随记录）；
    未命中→None（调用方分型，bsdl_cell_lookup 同款口径）。
    """
    needle = str(name).lower()
    for pname, rec in (doc.get("model_specific") or {}).items():
        if str(pname).lower() == needle:
            out = dict(rec)
            out["name"] = pname
            out["source"] = "model_specific"
            return out
    for rkey, val in (doc.get("reserved") or {}).items():
        if str(rkey).lower() == needle:
            return {"name": rkey, "source": "reserved", "value": val}
    return None


def ami_required_check(doc: dict[str, Any]) -> dict[str, Any]:
    """必备保留键三清单（缺失如实清单不硬拒——任务书口径）。

    ``{"complete", "missing"(canonical 名), "present", "n_missing",
    "n_present"}``；比对基于 doc["reserved"] 实际键集（大小写不敏感），
    missing 记 :data:`REQUIRED_RESERVED_KEYS` canonical 名。
    """
    res_ci = {str(k).lower() for k in (doc.get("reserved") or {})}
    missing = [k for k in REQUIRED_RESERVED_KEYS if k.lower() not in res_ci]
    present = [k for k in REQUIRED_RESERVED_KEYS if k.lower() in res_ci]
    return {
        "complete": not missing,
        "missing": missing,
        "present": present,
        "n_missing": len(missing),
        "n_present": len(present),
    }


def ami_defaults_table(doc: dict[str, Any]) -> dict[str, Any]:
    """Model_Specific 参数→default_typed 平表（插入序拷贝）。

    缺 default/type 非法/转换失败的参数记 None 键（不隐键——消费方
    区分"无 default"与"typed 失败"走 doc 的 default_raw/warnings）。
    """
    return {
        name: rec.get("default_typed")
        for name, rec in (doc.get("model_specific") or {}).items()
    }
