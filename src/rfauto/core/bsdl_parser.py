"""BSDL（Boundary Scan Description Language，IEEE 1149.1 附录 A）确定性
解析内核（aurora_q 席位 Q-X77，2026-11-08）。

JTAG 边界扫描描述**公开标准**（VHDL 子集）的只读结构化解析——芯片
TAP/边界单元的交换格式，与 STIL（Q-X72，其 Procedures/Import 块引用
BSDL 过程）和 IPC-356 构成测试三面。词法与语义全在 core 确定性内核
（铁律 7：结构化数据只出自数据源文本本身，LLM/agent 永不产生物理数字）。
服务包装见 :mod:`rfauto.service.bsdl_service`（规则 4 JSON 进出），CLI
薄壳见 cli/domains/bsdl.py（stil/citi/gdsii 同款域形态）。解析器集群
四件套参照：core/stil_parser.py（Q-X72 同代词法/状态机）、
core/verilog_netlist_parser.py（VHDL 表亲硬件描述语言解析同代）。

覆盖面（结构子集；fail-soft 口径——病态条目/病态语句降级为警告+跳过，
不炸全文；仅文件身份级致命面走 :class:`BsdlParseError`）：

- 词法：VHDL 子集 token 流（标识符/数字 word、``"..."`` 字符串（``""``
  转义=成对双引号——VHDL 惯例）、``'c'`` 字符字面量、括点/分号/逗号/
  ``:=``/``:``/``&``/``=`` 符号、``--`` 行注释收编；**大小写归一双录**
  ——关键字比较走 lower，标识符原样保存（VHDL 不敏感语义））；字符串
  ``&`` 级联（跨行长串惯用形态）在取值段合并；引号未闭合 fail-soft；
- entity 身份面：``entity <名> is ... end <名>;`` 提取（关键字大小写
  不敏感）；无 entity/空文件/**entity 未以 ``end <名>;`` 收口**→致命
  :class:`BsdlParseError` 带行号；同文件多 entity：首个解析、其余如实
  计数+警告；
- port 表：``port ( 名[, 名2] : 模式 类型 ; ... ) ;``——多名声、模式
  （in/out/inout/buffer/linkage 小写归一，未知如实登记）、类型原样；
  **5 标准 TAP 信号识别**（TCK/TMS/TDI/TDO/TRST）：``TAP_SCAN_CLOCK/
  MODE/IN/OUT/RESET of <端口>`` 标准属性目标**优先**（端口名可非标准
  如 JTDO），名字匹配（大小写不敏感）回落，``source`` 如实标注
  attribute/name；TCK/TMS/TDI/TDO 缺任一→warning（如实不全）；TRST
  标准可选，缺省**不**警告；
- PIN_MAP 面（IEEE 1149.1 解析链）：``attribute PIN_MAP of ... is
  <标识符|字符串>;``——字符串直用；标识符先查同名 ``constant``，再查
  同名 ``generic`` 取其缺省值作常量名二跳（标准 ``PIN_MAP is
  PHYSICAL_PIN_MAP`` + ``generic (PHYSICAL_PIN_MAP : string := "PKG")``
  + ``constant PKG : PIN_MAP_STRING := "..."`` 形态，实际命中常量名记
  ``pin_map_constant``）；PIN_MAP 缺失时 PIN_MAP_STRING 属性直写形态
  兜底 → 引脚映射 ``pin:位置`` / ``pin:(位1,位2)``（总线组括号多位置）；
  病态条目 fail-soft 跳条+警告；PIN_MAP 与兜底俱缺→warning；
- INSTRUCTION_OPCODE：``"EXTEST=0000, SAMPLE=0001, ..."`` 逗号切分逐
  条 ``名=位串``（位串字符集 {0,1} 校验，违例如实 warning 保原值）；
  INSTRUCTION_CAPTURE 位串校验；IDCODE_REGISTER **32 位串长度校验**
  （长度+字符集双检，不硬门只 warning——如实三态 idcode_valid）；
- BOUNDARY_REGISTER 主面：``"<序号> (CELL, PORT, FUNC, SAFE[, CC, DV[,
  RST]]) , ..."`` 逐单元解析（序号/cell 类型 BC_N/port（``*``=内部→
  port None+is_internal）/function/safe/控制单元序号+禁用值+禁用结果
  ——7 字段全收，>7 字段 warning，<4 字段警告保部分解析）；病态条目
  fail-soft 跳条+警告；**控制链校验**（output3 的 control 序号存在性
  +指向单元 function∈{control,controlr} 一致性——违例如实 warning
  列表不猜；bidir 等其余受控函数本席不校验，见模块尾已知限制）；
- BOUNDARY_LENGTH vs 实际最大序号+1 **一致性三数字**（length_declared
  /max_cell+1/rel_diff=(算得-申报)/|申报|——SPEF cap sum 同款口径，
  报告不做硬门）；REGISTER_ACCESS 等 1149.1-2001 增补 attribute 如实
  登记 ``attributes_other`` **不展开**；use 声明收编名录（多行语句
  天然容忍——语句收集按 token 不按行）。

结构化输出（schema=bsdl/1.0，全 JSON 原生类型）::

    {
      "schema": "bsdl/1.0",
      "entity_name": str|None,
      "n_entities": int,
      "generics":  {名: {"type": str, "default": str|None}},
      "ports":     {名: {"dir": str, "type": str, "line": int}},
      "tap_ports": {"tck"/"tms"/"tdi"/"tdo"/"trst":
                    {"name", "source": "attribute|name", "dir", "type",
                     "line"} | None},
      "n_tap_present": int,
      "pin_map_ref": str|None,       # PIN_MAP 属性取值（标识符/字符串）
      "pin_map_constant": str|None,  # 实际命中的 PIN_MAP_STRING 常量名
      "pins":      {引脚名: [位置, ...]},
      "use_clauses": [str, ...],
      "instructions": {指令名: 位串},
      "instruction_capture": str|None,
      "idcode_register": str|None,
      "idcode_length": int|None,
      "idcode_valid": bool|None,
      "boundary_cells": [单元 dict, ...],   # 见 :func:`parse_bsdl` 内注释
      "boundary_length_declared": int|None,
      "boundary_length_max_cell_plus_1": int,
      "boundary_length_rel_diff": float|None,
      "attributes_other": {attr 名: 值串},
      "constants": {常量名: 值串},
      "stats": {"n_ports", "n_pins", "n_instructions", "n_boundary_cells",
                "n_control_cells", "n_output3_cells", "n_entities",
                "n_unknown_statements", "n_control_chain_warnings",
                "n_pin_map_entries_skipped", "n_boundary_entries_skipped",
                "n_warnings"},
      "warnings": [str],
    }

查询三函数（服务/CLI 上层消费）：

- :func:`bsdl_boundary_cells`：边界单元平坦清单（声明序文件序拷贝）；
- :func:`bsdl_cell_lookup`：按 port 查关联单元（大小写不敏感；总线端口
  名无索引查询命中全部 ``名(i)`` 位）——input 直接命中；output3 等带
  控制序号单元命中时**控制链关联**（其 control 序号指向单元一并回列，
  如实不去猜）；未命中→None 调用方分型；
- :func:`bsdl_instruction_table`：指令→opcode 表+capture/idcode 摘要
  （指令名大小写不敏感查询由调用方对 key lower——表本身保原样键）。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。本模块不设
``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json——
stil_parser 同款先例，新模块零金快照漂移）。

已知限制（如实登记不展开）：1149.1-2001/2013 增补 attribute
（REGISTER_ACCESS/BOUNDARY_LIMIT 等）只收 ``attributes_other`` 原样
值串；bidir/output 差分驱动等其余受控函数不参与控制链校验（任务书面
=output3）；port 类型/bit_vector 位宽只作字符串登记不做语义解释；
VHDL record/configuration 声明不在子集（出现即 unknown 语句警告）。
"""

from __future__ import annotations

from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 边界单元 function 闭集（IEEE 1149.1 BSDL 常见集；未知如实登记+warning）。
BOUNDARY_FUNCTIONS = frozenset({
    "input", "output2", "output3", "control", "controlr", "internal",
    "clock", "test", "bidir", "observe_only",
})

#: port 模式闭集（VHDL；大小写归一小写后比对，未知如实登记原值）。
PORT_MODES = frozenset({"in", "out", "inout", "buffer", "linkage"})

#: 5 标准 TAP 端口名（小写键；TRST 标准可选——缺省不警告）。
TAP_PORT_KEYS = ("tck", "tms", "tdi", "tdo", "trst")

#: TAP 必备端口（缺任一→warning；TRST 不在其中——可选）。
TAP_REQUIRED_KEYS = ("tck", "tms", "tdi", "tdo")

#: TAP_SCAN_* 标准属性 → TAP 键（IEEE 1149.1 按属性目标端口识别 TAP——
#: 端口名可非标准如 JTDO；属性优先于名字匹配，``source`` 字段如实标注）。
TAP_SCAN_ATTRIBUTES: dict[str, str] = {
    "TAP_SCAN_CLOCK": "tck",
    "TAP_SCAN_MODE": "tms",
    "TAP_SCAN_IN": "tdi",
    "TAP_SCAN_OUT": "tdo",
    "TAP_SCAN_RESET": "trst",
}

#: 控制链校验适用的受控 function（任务书面=output3；其余受控函数不校验）。
CONTROLLED_FUNCTIONS = frozenset({"output3"})

#: 控制链目标 function 合法集（control* 一致性判据）。
CONTROL_TARGET_FUNCTIONS = frozenset({"control", "controlr"})

#: IDCODE_REGISTER 标准位宽（IEEE 1149.1：version 4+part 16+maker 11+1）。
IDCODE_BITS = 32


class BsdlParseError(ValueError):
    """BSDL 文件身份级致命错误（空文件/无 entity/entity 未收口）
    ——fail-soft 之外的唯一致命面。词法/条目病态不走本异常（warning+跳过
    口径）。继承 ValueError（stil_parser 同款口径）。"""


# --------------------------------------------------------------------------- #
# 词法：token 流（kind ∈ {"word","string","char","sym"}，携带行号）
# --------------------------------------------------------------------------- #

#: 符号集（多字符 ``:=`` 先判；单字符括点/分号/逗号/级联/等号）。
_SYMBOLS_2 = (":=",)
_SYMBOLS_1 = "();:,&="

#: word 终结字符集（空白/符号/引号）。``.`` 与单 ``-`` **不**终结——
#: ``STD_1149_1_1994.all`` 选择名与 ``20.0e6`` 数字保持单 word；``--``
#: 注释起头在扫描循环内单独判断截断。
_WORD_STOP = " \t\r\n\f\v();:,&=\"'"


def _tokenize(text: str) -> tuple[list[tuple[str, str, int]], list[str]]:
    """BSDL 文本 → (token 流, 词法警告)。

    token 三元组 ``(kind, value, line)``：word=标识符/数字（字母/下划线
    起头或数字连续段，遇符号/空白/引号终结）、string=``"..."`` 内容
    （``""`` 成对双引号=VHDL 转义单引号语义，收编为内容中的单 ``"``）、
    char=``'c'`` 字符字面量内容、sym=符号。``--`` 注释至行尾剔除并保持
    行号推进；引号未闭合 fail-soft 警告（行号=起点）。
    """
    tokens: list[tuple[str, str, int]] = []
    warns: list[str] = []
    line = 1
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if c == "-" and text[i + 1:i + 2] == "-":
            end = text.find("\n", i)
            i = n if end == -1 else end  # 行注释：换行留给下轮推进行号
            continue
        if c == '"':
            j = i + 1
            chunks: list[str] = []
            closed = False
            while j < n:
                if text[j] == '"':
                    if text[j + 1:j + 2] == '"':  # "" 转义：收编单引号
                        chunks.append('"')
                        j += 2
                        continue
                    closed = True
                    break
                chunks.append(text[j])
                j += 1
            if not closed:
                warns.append(f"字符串引号未闭合（第 {line} 行）——至文件尾如实收编")
                line += text.count("\n", i)
                tokens.append(("string", "".join(chunks), line))
                i = n
            else:
                content = "".join(chunks)
                tokens.append(("string", content, line))
                line += text.count("\n", i, j + 1)
                i = j + 1
            continue
        if c == "'":
            if text[i + 2:i + 3] == "'":
                tokens.append(("char", text[i + 1:i + 2], line))
                i += 3
                continue
            warns.append(f"字符字面量形态不识（第 {line} 行）——单引号剔除")
            i += 1
            continue
        two = text[i:i + 2]
        if two in _SYMBOLS_2:
            tokens.append(("sym", two, line))
            i += 2
            continue
        if c in _SYMBOLS_1:
            tokens.append(("sym", c, line))
            i += 1
            continue
        j = i
        while j < n and text[j] not in _WORD_STOP:
            if text[j] == "-" and text[j + 1:j + 2] == "-":
                break  # 词紧贴注释起头（病态排版容忍）：词到此为止
            j += 1
        if j == i:
            # 进展守卫：任何未归类单字符收编为 sym 单 token（零进展死循环
            # 面封死——词法对任意输入恒终止）。
            tokens.append(("sym", c, line))
            i += 1
            continue
        tokens.append(("word", text[i:j], line))
        i = j
    return tokens, warns


# --------------------------------------------------------------------------- #
# 语句收集：token 流 → 语句列表（``;`` 深度 0 终结；括号深度跟踪）
# --------------------------------------------------------------------------- #


def _collect_statements(
    toks: list[tuple[str, str, int]], warnings: list[str]
) -> list[tuple[list[tuple[str, str, int]], int]]:
    """token 流 → 语句列表 ``([tokens], 起始行)``（到 ``;`` 深度 0 终结）。

    ``port (...)``/``generic (...)`` 内部 ``;``（深度>0）不终结语句——
    整个括号体随语句收编；EOF 截断（无终结 ``;``）fail-soft 警告+如实
    收编；括号失衡（深度不归零到 EOF）fail-soft 警告。
    """
    stmts: list[tuple[list[tuple[str, str, int]], int]] = []
    cur: list[tuple[str, str, int]] = []
    start_ln = 0
    depth = 0
    for tok in toks:
        kind, val, ln = tok
        if not cur:
            start_ln = ln
        cur.append(tok)
        if kind == "sym" and val == "(":
            depth += 1
        elif kind == "sym" and val == ")":
            depth = max(0, depth - 1)
        elif kind == "sym" and val == ";" and depth == 0:
            stmts.append((cur, start_ln))
            cur = []
    if cur:
        warnings.append(
            f"第 {start_ln} 行语句未以 ';' 终结（文件截断）——如实收编")
        stmts.append((cur, start_ln))
    if depth != 0:
        warnings.append("括号失衡：EOF 时仍有未闭合 '('——如实收编")
    return stmts


# --------------------------------------------------------------------------- #
# 取值段：语句尾段 → 文本/标识符/数字（``&`` 级联合并）
# --------------------------------------------------------------------------- #


def _value_part(stmt: list[tuple[str, str, int]]) -> dict[str, Any]:
    """语句取值段提取：``is``/``:=`` 之后到语句尾。

    返回 ``{"text": str|None, "word": str|None, "raw": str|None}``：字符串
    token 经 ``&`` 级联合并（``"a" & "b"`` → ``"ab"``——BSDL 跨行长串惯用
    形态）；首个 word 记入 ``word``（PIN_MAP 标识符引用/BOUNDARY_LENGTH
    数字）；char token 内容并入 text；``raw``=取值段非终结符 token 原样
    空格拼接（``(20.0e6, BOTH)`` 类非字符串值的如实展示面）。``is`` 缺省
    容忍=取 ``:=`` 之后、再缺省=第二个 token 之后（attribute 形态兜底）。
    """
    tail: list[tuple[str, str, int]] = []
    for idx, (kind, val, _ln) in enumerate(stmt):
        if kind == "word" and val.lower() == "is":
            tail = stmt[idx + 1:]
            break
    if not tail:
        for idx, (kind, val, _ln) in enumerate(stmt):
            if kind == "sym" and val == ":=":
                tail = stmt[idx + 1:]
                break
    if not tail and len(stmt) >= 2:
        tail = stmt[2:]
    text_parts: list[str] = []
    raw_parts: list[str] = []
    word: str | None = None
    for kind, val, _ln in tail:
        if kind == "sym":
            if val != ";":
                raw_parts.append(val)
            continue  # & 级联符/杂散符号剔除——字符串直接拼接即 VHDL 语义
        raw_parts.append(val)
        if kind in ("string", "char"):
            text_parts.append(val)
        elif kind == "word" and word is None:
            word = val
    text = "".join(text_parts) if text_parts else None
    raw = " ".join(raw_parts) if raw_parts else None
    return {"text": text, "word": word, "raw": raw}


def _attr_target(stmt: list[tuple[str, str, int]]) -> str | None:
    """attribute 语句 ``of <目标>`` 的目标名（缺 ``of`` → None）。

    ``attribute TAP_SCAN_IN of TDI : signal is true;`` → ``"TDI"``——
    TAP_SCAN_* 族按目标端口识别 TAP（IEEE 1149.1 标准机制）。
    """
    for idx, (kind, val, _ln) in enumerate(stmt):
        if kind == "word" and val.lower() == "of" and idx + 1 < len(stmt):
            nxt = stmt[idx + 1]
            if nxt[0] == "word":
                return nxt[1]
            return None
    return None


def _stmt_words(stmt: list[tuple[str, str, int]]) -> list[str]:
    """语句 token 值列表（word/string/char 原样——引号已剥离）。"""
    return [v for k, v, _ln in stmt if k in ("word", "string", "char")]


def _warn(warnings: list[str], msg: str, ln: int) -> None:
    warnings.append(f"{msg}（第 {ln} 行）")


def _lookup_ci(table: dict[str, Any], name: str) -> str | None:
    """大小写不敏感查表 → 原样键（未命中 None；VHDL 标识符不敏感语义）。"""
    needle = name.lower()
    return next((k for k in table if k.lower() == needle), None)


# --------------------------------------------------------------------------- #
# entity 身份面
# --------------------------------------------------------------------------- #


def _find_entity_open(
    toks: list[tuple[str, str, int]], warnings: list[str]
) -> tuple[str | None, int, int, int]:
    """token 流 → (entity 名|None, `is` 之后下标, 起始行, entity 声明数)。

    ``entity <名> is`` 三 token 形态（大小写不敏感）；无 entity→(None,
    -1, -1, 0)（调用方致命）；多 entity 首个之外如实计数+警告。
    """
    n = len(toks)
    first: tuple[str, int, int] | None = None
    count = 0
    i = 0
    while i < n - 2:
        kind, val, ln = toks[i]
        if kind == "word" and val.lower() == "entity" \
                and toks[i + 1][0] == "word" \
                and toks[i + 2][0] == "word" \
                and toks[i + 2][1].lower() == "is":
            count += 1
            if first is None:
                first = (toks[i + 1][1], i + 3, ln)
            else:
                warnings.append(
                    f"第 {ln} 行第二个 entity {toks[i + 1][1]!r}——"
                    "首个之外如实计数不展开")
            i += 3
            continue
        i += 1
    if first is None:
        return None, -1, -1, 0
    name, start, ln = first
    return name, start, ln, count


# --------------------------------------------------------------------------- #
# port / generic 括号体解析
# --------------------------------------------------------------------------- #


def _paren_body(stmt: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
    """语句 → 首个括号体内部 token（无括号体→空表）。"""
    start = -1
    depth = 0
    for idx, (kind, val, _ln) in enumerate(stmt):
        if kind != "sym":
            continue
        if val == "(":
            if start == -1:
                start = idx + 1
            depth += 1
        elif val == ")":
            depth -= 1
            if depth == 0 and start != -1:
                return stmt[start:idx]
    return [] if start == -1 else stmt[start:]


def _split_top(
    toks: list[tuple[str, str, int]], sep: str
) -> list[list[tuple[str, str, int]]]:
    """token 列表按深度 0 的 sep 符号切段（括号深度跟踪）。"""
    parts: list[list[tuple[str, str, int]]] = []
    cur: list[tuple[str, str, int]] = []
    depth = 0
    for tok in toks:
        kind, val, _ln = tok
        if kind == "sym":
            if val == "(":
                depth += 1
            elif val == ")":
                depth -= 1
            elif val == sep and depth == 0:
                parts.append(cur)
                cur = []
                continue
        cur.append(tok)
    parts.append(cur)
    return parts


def _extract_ports(
    body: list[tuple[str, str, int]],
    ports: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    """port 括号体 → 信号表（多名声展开；重复名后列覆盖+警告）。"""
    for decl in _split_top(body, ";"):
        if not decl or all(k == "sym" for k, _v, _l in decl):
            continue
        ln = decl[0][2]
        colon_idx = -1
        depth = 0
        for idx, (kind, val, _l) in enumerate(decl):
            if kind == "sym":
                if val == "(":
                    depth += 1
                elif val == ")":
                    depth -= 1
                elif val == ":" and depth == 0:
                    colon_idx = idx
                    break
        if colon_idx == -1:
            _warn(warnings,
                  f"port 声明形态不识（缺 ':'）"
                  f"{' '.join(_stmt_words(decl))!r}——跳过", ln)
            continue
        names: list[str] = []
        name_buf: list[str] = []
        for kind, val, _l in decl[:colon_idx]:
            if kind == "sym" and val == ",":
                if name_buf:
                    names.append(" ".join(name_buf))
                    name_buf = []
            elif kind in ("word", "string"):
                name_buf.append(val)
        if name_buf:
            names.append(" ".join(name_buf))
        names = [nm for nm in (n.strip() for n in names) if nm]
        if not names:
            _warn(warnings, "port 声明缺名——跳过", ln)
            continue
        tail = decl[colon_idx + 1:]
        words = _stmt_words(tail)
        mode = words[0].lower() if words else ""
        if mode not in PORT_MODES:
            _warn(warnings,
                  f"port {names[0]!r} 模式 {mode!r} 不在闭集"
                  f" {sorted(PORT_MODES)}——如实登记", ln)
        # 类型串=mode 之后的 token 原样（word/sym 并收——bit_vector 位宽
        # 括号保形；仅登记展示面，不做语义解释）。
        mode_seen = False
        type_parts: list[str] = []
        for kind, val, _l in tail:
            if not mode_seen and kind == "word":
                mode_seen = True
                continue
            if kind in ("word", "sym"):
                type_parts.append(val)
        type_str = " ".join(type_parts)
        for name in names:
            if name in ports:
                _warn(warnings, f"信号重复名 {name!r}——后列覆盖", ln)
            ports[name] = {"dir": mode, "type": type_str, "line": ln}


def _extract_generics(
    body: list[tuple[str, str, int]],
    generics: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    """generic 括号体 → 形参表（``名 : 类型 := 缺省``；缺省缺失如实 None）。"""
    for decl in _split_top(body, ";"):
        if not decl or all(k == "sym" for k, _v, _l in decl):
            continue
        ln = decl[0][2]
        colon_idx = -1
        for idx, (kind, val, _l) in enumerate(decl):
            if kind == "sym" and val == ":":
                colon_idx = idx
                break
        if colon_idx == -1:
            _warn(warnings, "generic 声明形态不识（缺 ':'）——跳过", ln)
            continue
        name_words = [v for k, v, _l in decl[:colon_idx] if k in ("word", "string")]
        name = name_words[0] if name_words else ""
        if not name:
            _warn(warnings, "generic 声明缺名——跳过", ln)
            continue
        tail = decl[colon_idx + 1:]
        # 类型段=``:`` 与 ``:=`` 之间的 token（缺 ``:=``=尾段全量、缺省
        # 值 None）；缺省值段=``:=`` 之后（字符串级联/标识符）。
        assign_idx = next(
            (idx for idx, (k, v, _l) in enumerate(tail)
             if k == "sym" and v == ":="), -1)
        type_toks = tail if assign_idx == -1 else tail[:assign_idx]
        type_str = " ".join(v for k, v, _l in type_toks if k in ("word", "sym"))
        default_val: str | None = None
        if assign_idx != -1:
            dpart = _value_part(tail[assign_idx:])
            default_val = dpart.get("text") or dpart.get("word")
        if name in generics:
            _warn(warnings, f"generic 重复名 {name!r}——后列覆盖", ln)
        generics[name] = {"type": type_str, "default": default_val}


# --------------------------------------------------------------------------- #
# PIN_MAP_STRING / INSTRUCTION / IDCODE 值解析
# --------------------------------------------------------------------------- #


def _split_str_commas(text: str) -> list[str]:
    """字符串按深度 0 逗号切段（括号深度跟踪）。

    PIN_MAP 总线组 ``data:(P2,P3)``、边界记录体索引端口 ``D(1)`` 内部
    逗号不误切——引脚映射/指令表/单元记录三处共用单源切分。
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def _parse_pin_map_string(
    content: str, ln: int, warnings: list[str]
) -> tuple[dict[str, list[str]], int]:
    """PIN_MAP_STRING 内容 → (引脚映射, 跳条数)。

    ``名:位置`` / ``名:(位1,位2)``（总线组括号多位置）逗号切分逐条；
    病态条目（缺 ':'/缺名/缺位置）fail-soft 跳条+警告；重复引脚后列
    覆盖+警告。
    """
    pins: dict[str, list[str]] = {}
    skipped = 0
    for raw_entry in _split_str_commas(content):
        entry = raw_entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            skipped += 1
            _warn(warnings, f"引脚映射条目 {entry!r} 缺 ':'——跳条", ln)
            continue
        pin, _, locs_raw = entry.partition(":")
        pin = pin.strip()
        locs_raw = locs_raw.strip()
        if not pin:
            skipped += 1
            _warn(warnings, f"引脚映射条目 {entry!r} 缺引脚名——跳条", ln)
            continue
        if locs_raw.startswith("("):
            if not locs_raw.endswith(")"):
                skipped += 1
                _warn(warnings,
                      f"引脚 {pin!r} 总线组括号未闭合 {locs_raw[:40]!r}——跳条",
                      ln)
                continue
            locs = [p.strip() for p in locs_raw[1:-1].split(",") if p.strip()]
        else:
            locs = [locs_raw] if locs_raw else []
        if not locs:
            skipped += 1
            _warn(warnings, f"引脚 {pin!r} 位置列表为空——跳条", ln)
            continue
        if pin in pins:
            _warn(warnings, f"引脚重复名 {pin!r}——后列覆盖", ln)
        pins[pin] = locs
    return pins, skipped


def _bits_valid(bits: str | None) -> bool:
    """位串字符集校验（{0,1}；None/空→False）。"""
    return bool(bits) and all(ch in "01" for ch in bits)


def _parse_instruction_opcodes(
    content: str, ln: int, warnings: list[str]
) -> dict[str, str]:
    """INSTRUCTION_OPCODE 内容 → 指令→位串表（病态条目跳条+警告）。"""
    table: dict[str, str] = {}
    for raw_entry in _split_str_commas(content):
        entry = raw_entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            _warn(warnings, f"指令条目 {entry!r} 缺 '='——跳条", ln)
            continue
        name, _, bits = entry.partition("=")
        name = name.strip()
        bits = bits.strip()
        if not name:
            _warn(warnings, f"指令条目 {entry!r} 缺指令名——跳条", ln)
            continue
        if not _bits_valid(bits):
            _warn(warnings,
                  f"指令 {name!r} 位串 {bits!r} 含非 0/1 字符——如实保原值",
                  ln)
        if name in table:
            _warn(warnings, f"指令重复名 {name!r}——后列覆盖", ln)
        table[name] = bits
    return table


# --------------------------------------------------------------------------- #
# BOUNDARY_REGISTER 主面
# --------------------------------------------------------------------------- #


def _skip_entry(content: str, i: int) -> int:
    """从 i 起括号感知跳到下个深度 0 逗号下标（无则 len）——病态条目整条
    跳过（``x (BC_1, a, input, X)`` 内部逗号不切碎成多条）。"""
    n = len(content)
    depth = 0
    while i < n:
        ch = content[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return i
        i += 1
    return n


def _parse_boundary_register(
    content: str, ln: int, warnings: list[str]
) -> tuple[list[dict[str, Any]], int]:
    """BOUNDARY_REGISTER 内容 → (单元清单, 跳条数)。

    ``<序号> (CELL, PORT, FUNC, SAFE[, CC, DV[, RST]])`` 逗号间隔逐条；
    序号非整数/括号不闭合→fail-soft 跳条+警告；记录字段 <4 警告保部分
    解析、>7 警告多余字段；``*`` 端口→port None+is_internal；safe 为
    ``'c'`` 字面形态剥引号；function 未知如实登记+warning（不硬门）。
    """
    cells: list[dict[str, Any]] = []
    skipped = 0
    i = 0
    n = len(content)
    while i < n:
        while i < n and content[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        num_start = i
        while i < n and content[i].isdigit():
            i += 1
        num_raw = content[num_start:i]
        if not num_raw:
            # 缺序号病态条目——括号感知跳到下个深度 0 逗号（记录体内部
            # 逗号不误计为多条；一条病态条目恰计一次跳条）
            skipped += 1
            seg_end = _skip_entry(content, i)
            seg = content[i:seg_end].strip()
            _warn(warnings, f"边界单元条目缺序号 {seg[:40]!r}——跳条", ln)
            i = seg_end
            continue
        num = int(num_raw)
        while i < n and content[i] in " \t\r\n":
            i += 1
        if i >= n or content[i] != "(":
            skipped += 1
            _warn(warnings, f"边界单元 {num} 缺 '(' 记录体——跳条", ln)
            i = _skip_entry(content, i)
            continue
        depth = 0
        j = i
        while j < n:
            if content[j] == "(":
                depth += 1
            elif content[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            skipped += 1
            _warn(warnings,
                  f"边界单元 {num} 记录体括号未闭合——跳条并止于余文", ln)
            break
        record = content[i + 1:j]
        fields = [f.strip() for f in _split_str_commas(record)]
        cell: dict[str, Any] = {
            "num": num,
            "cell_type": None,
            "port": None,
            "is_internal": False,
            "function": None,
            "safe": None,
            "control_cell": None,
            "disable_value": None,
            "disable_result": None,
            "n_fields": len(fields),
        }
        if len(fields) >= 1 and fields[0]:
            cell["cell_type"] = fields[0]
        if len(fields) >= 2:
            port = fields[1]
            if port == "*":
                cell["is_internal"] = True
            elif port:
                cell["port"] = port
        if len(fields) >= 3 and fields[2]:
            func = fields[2]
            cell["function"] = func
            if func.lower() not in BOUNDARY_FUNCTIONS:
                _warn(warnings,
                      f"边界单元 {num} function {func!r} 不在已知闭集"
                      "——如实登记", ln)
        if len(fields) >= 4 and fields[3]:
            safe = fields[3]
            if len(safe) >= 2 and safe[0] == "'" and safe[-1] == "'":
                safe = safe[1:-1]  # 'c' 字面形态剥引号（bare 字符同收）
            cell["safe"] = safe
        if len(fields) >= 5 and fields[4]:
            try:
                cell["control_cell"] = int(fields[4])
            except ValueError:
                _warn(warnings,
                      f"边界单元 {num} 控制序号 {fields[4]!r} 非整数——如实"
                      "保 None", ln)
        if len(fields) >= 6 and fields[5]:
            cell["disable_value"] = fields[5]
        if len(fields) >= 7 and fields[6]:
            cell["disable_result"] = fields[6]
        if len(fields) < 4:
            _warn(warnings,
                  f"边界单元 {num} 记录字段数 {len(fields)} < 4——保部分解析",
                  ln)
        elif len(fields) > 7:
            _warn(warnings,
                  f"边界单元 {num} 记录字段数 {len(fields)} > 7——多余字段"
                  "不收", ln)
        cells.append(cell)
        i = j + 1
    return cells, skipped


def _check_control_chain(
    cells: list[dict[str, Any]], ln: int, warnings: list[str]
) -> int:
    """output3 控制链校验 → 警告数（存在性+目标 function=control*）。

    缺控制序号/指向单元不存在/目标 function 不在
    :data:`CONTROL_TARGET_FUNCTIONS`——逐一如实 warning 不猜；重复坏链
    逐单元各记一条。
    """
    by_num = {c["num"]: c for c in cells}
    n_bad = 0
    for cell in cells:
        if (cell["function"] or "").lower() not in CONTROLLED_FUNCTIONS:
            continue
        cc = cell["control_cell"]
        if cc is None:
            n_bad += 1
            _warn(warnings,
                  f"边界单元 {cell['num']} function "
                  f"{cell['function']!r} 缺控制序号——控制链不完整", ln)
            continue
        target = by_num.get(cc)
        if target is None:
            n_bad += 1
            _warn(warnings,
                  f"边界单元 {cell['num']} 控制序号 {cc} 指向单元不存在"
                  "——控制链断裂", ln)
            continue
        tfunc = (target["function"] or "").lower()
        if tfunc not in CONTROL_TARGET_FUNCTIONS:
            n_bad += 1
            _warn(warnings,
                  f"边界单元 {cell['num']} 控制序号 {cc} 指向单元 "
                  f"{target['num']} function "
                  f"{target['function']!r} 非 control*——控制链不一致", ln)
    return n_bad


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def parse_bsdl(text: str) -> dict[str, Any]:
    """BSDL 文本 → 结构化 dict（纯函数；只做结构提取不做测试结论）。

    空文件/无 ``entity <名> is``/entity 未以 ``end <名>;`` 收口 →
    :class:`BsdlParseError`（文件身份致命，service 层转 error 信封）；
    其余病态一律 warning+跳过（fail-soft，#208 家法）。返回键集见模块
    docstring。
    """
    if not text or not text.strip():
        raise BsdlParseError("空文件（无任何内容）——拒绝解析")

    warnings: list[str] = []
    toks, lex_warns = _tokenize(text)
    warnings.extend(lex_warns)

    entity_name, body_start, ent_ln, n_entities = _find_entity_open(
        toks, warnings)
    if entity_name is None:
        raise BsdlParseError(
            "缺少 'entity <名> is' 头（文件身份面）——拒绝解析")
    stmts = _collect_statements(toks[body_start:], warnings)

    # entity 收口定位：首个 `end [名] ;` 语句；其后语句如实计数（多
    # entity 面已在 _find_entity_open 警告，此处防尾随杂散静默）。
    end_idx = -1
    for idx, (stmt, _ln) in enumerate(stmts):
        words = _stmt_words(stmt)
        if words and words[0].lower() == "end":
            end_idx = idx
            break
    if end_idx == -1:
        raise BsdlParseError(
            f"entity {entity_name!r}（第 {ent_ln} 行）未以 "
            f"'end {entity_name};' 收口——文件截断")
    n_trailing = len(stmts) - end_idx - 1
    if n_trailing > 0:
        warnings.append(
            f"entity 收口后尾随语句 {n_trailing} 条——如实计数不展开")

    generics: dict[str, dict[str, Any]] = {}
    ports: dict[str, dict[str, Any]] = {}
    constants: dict[str, str | None] = {}
    constant_lines: dict[str, int] = {}
    use_clauses: list[str] = []
    attributes: dict[str, dict[str, Any]] = {}
    attributes_other: dict[str, str | None] = {}
    tap_scan: list[tuple[str, dict[str, Any], int]] = []
    n_unknown = 0

    for stmt, ln in stmts[:end_idx]:
        words = _stmt_words(stmt)
        if not words:
            continue
        key = words[0].lower()
        if key == "generic":
            _extract_generics(_paren_body(stmt), generics, warnings)
        elif key == "port":
            _extract_ports(_paren_body(stmt), ports, warnings)
        elif key == "use":
            use_clauses.append(" ".join(words[1:]))
        elif key == "constant":
            cname = words[1] if len(words) >= 2 else ""
            if not cname:
                _warn(warnings, "constant 声明缺名——跳过", ln)
                continue
            constants[cname] = _value_part(stmt).get("text")
            constant_lines[cname] = ln
        elif key == "attribute":
            aname = words[1] if len(words) >= 2 else ""
            if not aname:
                _warn(warnings, "attribute 声明缺名——跳过", ln)
                continue
            value = _value_part(stmt)
            value["name"] = aname
            value["target"] = _attr_target(stmt)
            value["line"] = ln  # 取值面警告定位到属性语句行（非 entity 行）
            akey = aname.upper()  # VHDL 标识符大小写不敏感：消费键归一大写
            if akey in TAP_SCAN_ATTRIBUTES:
                # TAP_SCAN_* 按目标端口逐条收（不同目标同名属性不互相覆盖）
                tap_scan.append((TAP_SCAN_ATTRIBUTES[akey], value, ln))
                continue
            if akey in attributes:
                _warn(warnings, f"attribute 重复名 {aname!r}——后列覆盖", ln)
            attributes[akey] = value
        else:
            n_unknown += 1
            _warn(warnings, f"entity 域内未知语句 {words[0]!r}——跳过", ln)

    # ---- PIN_MAP 面（IEEE 1149.1 解析链）：attr 值=字符串直用；=标识符
    #      时先查同名常量，再查同名 generic→其缺省值作常量名二跳（标准
    #      ``PIN_MAP is PHYSICAL_PIN_MAP`` + ``generic (PHYSICAL_PIN_MAP :
    #      string := "PKG")`` + ``constant PKG : PIN_MAP_STRING := "..."``
    #      形态）；PIN_MAP 属性缺失时 PIN_MAP_STRING 属性兜底（部分工具
    #      直写形态）。 ----
    pin_map_ref: str | None = None
    pin_map_constant: str | None = None
    pins: dict[str, list[str]] = {}
    n_pin_skipped = 0
    pin_map_attr = attributes.get("PIN_MAP")
    pin_content: str | None = None

    pin_ln = ent_ln  # 引脚映射取值面警告行：随实际来源语句（属性/常量）
    if pin_map_attr is None:
        fallback = attributes.get("PIN_MAP_STRING")
        if fallback is not None and fallback.get("text"):
            pin_content = fallback["text"]
            pin_ln = fallback["line"]
            _warn(warnings, "缺 PIN_MAP 属性——PIN_MAP_STRING 直写形态兜底",
                  pin_ln)
        else:
            _warn(warnings, "缺 PIN_MAP 属性（IEEE 1149.1 必备面）——如实登记",
                  ent_ln)
    elif pin_map_attr.get("text"):
        pin_map_ref = pin_map_attr["text"]
        pin_content = pin_map_attr["text"]
        pin_ln = pin_map_attr["line"]
    elif pin_map_attr.get("word"):
        pin_map_ref = pin_map_attr["word"]
        pin_ln = pin_map_attr["line"]
        const_key = _lookup_ci(constants, pin_map_ref)
        if const_key is None:
            gen_key = _lookup_ci(generics, pin_map_ref)
            if gen_key is not None:
                default = generics[gen_key].get("default")
                if default:
                    const_key = _lookup_ci(constants, str(default))
                    if const_key is None:
                        _warn(warnings,
                              f"PIN_MAP 经 generic {gen_key!r} 缺省值 "
                              f"{default!r} 指向常量未找到——引脚映射为空",
                              pin_ln)
                else:
                    _warn(warnings,
                          f"PIN_MAP 引用 generic {gen_key!r} 无缺省值——"
                          "引脚映射为空", pin_ln)
            else:
                _warn(warnings,
                      f"PIN_MAP 引用 {pin_map_ref!r} 既非常量也非 generic"
                      "——引脚映射为空", pin_ln)
        if const_key is not None:
            pin_map_constant = const_key
            pin_content = constants[const_key]
            pin_ln = constant_lines.get(const_key, pin_ln)
            if pin_content is None:
                _warn(warnings,
                      f"常量 {const_key!r} 值非字符串——引脚映射为空", pin_ln)
    else:
        _warn(warnings, "PIN_MAP 属性取值为空——引脚映射为空",
              pin_map_attr["line"])
    if pin_content is not None:
        pins, n_pin_skipped = _parse_pin_map_string(
            pin_content, pin_ln, warnings)

    # ---- INSTRUCTION / IDCODE 面。 ----
    instructions: dict[str, str] = {}
    opcode_attr = attributes.get("INSTRUCTION_OPCODE")
    if opcode_attr is not None and opcode_attr.get("text") is not None:
        instructions = _parse_instruction_opcodes(
            opcode_attr["text"], opcode_attr["line"], warnings)
    capture: str | None = None
    capture_attr = attributes.get("INSTRUCTION_CAPTURE")
    if capture_attr is not None:
        capture = capture_attr.get("text") or capture_attr.get("word")
        if capture is not None and not _bits_valid(capture):
            _warn(warnings,
                  f"INSTRUCTION_CAPTURE {capture!r} 含非 0/1 字符——如实"
                  "保原值", capture_attr["line"])
    idcode: str | None = None
    idcode_length: int | None = None
    idcode_valid: bool | None = None
    idcode_attr = attributes.get("IDCODE_REGISTER")
    if idcode_attr is not None:
        idcode = idcode_attr.get("text") or idcode_attr.get("word")
        if idcode is not None:
            idcode_length = len(idcode)
            idcode_valid = _bits_valid(idcode) and idcode_length == IDCODE_BITS
            if not _bits_valid(idcode):
                _warn(warnings,
                      f"IDCODE_REGISTER 含非 0/1 字符（长度 "
                      f"{idcode_length}）——如实保原值", idcode_attr["line"])
            elif idcode_length != IDCODE_BITS:
                _warn(warnings,
                      f"IDCODE_REGISTER 长度 {idcode_length} ≠ 标准位宽 "
                      f"{IDCODE_BITS}——如实保原值", idcode_attr["line"])

    # ---- BOUNDARY_REGISTER 主面 + 一致性三数字。 ----
    boundary_cells: list[dict[str, Any]] = []
    n_bnd_skipped = 0
    n_chain_bad = 0
    bnd_attr = attributes.get("BOUNDARY_REGISTER")
    if bnd_attr is not None and bnd_attr.get("text") is not None:
        boundary_cells, n_bnd_skipped = _parse_boundary_register(
            bnd_attr["text"], bnd_attr["line"], warnings)
        n_chain_bad = _check_control_chain(
            boundary_cells, bnd_attr["line"], warnings)
    length_declared: int | None = None
    length_attr = attributes.get("BOUNDARY_LENGTH")
    if length_attr is None:
        _warn(warnings,
              "缺 BOUNDARY_LENGTH 属性（一致性三数字缺申报边）——如实登记",
              ent_ln)
    else:
        raw = length_attr.get("word") or length_attr.get("text")
        try:
            length_declared = int(str(raw))
        except (TypeError, ValueError):
            _warn(warnings,
                  f"BOUNDARY_LENGTH {raw!r} 非整数——三数字缺申报边",
                  length_attr["line"])
    max_cell_plus_1 = max((c["num"] for c in boundary_cells), default=-1) + 1
    rel_diff: float | None = None
    if length_declared is not None and length_declared != 0:
        rel_diff = (max_cell_plus_1 - length_declared) / abs(length_declared)

    # ---- 未消费 attribute 如实登记（REGISTER_ACCESS 等 2001 增补：原名
    #      原样值串，不展开；字符串值取级联文本，非字符串值取 raw 展示面）。 ----
    consumed = {
        "PIN_MAP", "PIN_MAP_STRING", "INSTRUCTION_OPCODE",
        "INSTRUCTION_CAPTURE", "IDCODE_REGISTER", "BOUNDARY_REGISTER",
        "BOUNDARY_LENGTH",
    }
    for akey, value in attributes.items():
        if akey not in consumed:
            attributes_other[value["name"]] = (
                value.get("text") if value.get("text") is not None
                else value.get("raw"))

    # ---- TAP 五信号识别：TAP_SCAN_* 属性目标优先（标准机制，端口名可
    #      非标准），名字匹配回落（大小写不敏感）；source 如实标注来源。 ----
    tap_ports: dict[str, dict[str, Any] | None] = dict.fromkeys(TAP_PORT_KEYS)
    for tap, value, ln in tap_scan:
        target = value.get("target")
        if not target:
            _warn(warnings,
                  f"TAP_SCAN 属性 {value['name']!r} 缺 'of <端口>' 目标——跳过",
                  ln)
            continue
        if tap_ports[tap] is not None:
            _warn(warnings,
                  f"TAP 键 {tap.upper()} 被 {value['name']!r} 重复指认——"
                  "后列覆盖", ln)
        port_key = _lookup_ci(ports, target)
        entry: dict[str, Any] = {"name": target, "source": "attribute"}
        if port_key is not None:
            entry.update(ports[port_key])
            entry["name"] = port_key
        else:
            entry.update({"dir": None, "type": None, "line": ln})
            _warn(warnings,
                  f"TAP_SCAN 属性 {value['name']!r} 目标 {target!r} 不在 port"
                  " 表——如实登记", ln)
        tap_ports[tap] = entry
    for tap in TAP_PORT_KEYS:
        if tap_ports[tap] is None:
            port_key = _lookup_ci(ports, tap)
            if port_key is not None:
                tap_ports[tap] = {"name": port_key, "source": "name",
                                  **ports[port_key]}
        if tap in TAP_REQUIRED_KEYS and tap_ports[tap] is None:
            _warn(warnings,
                  f"缺标准 TAP 端口 {tap.upper()}——TAP 面如实不全", ent_ln)

    n_output3 = sum(
        1 for c in boundary_cells
        if (c["function"] or "").lower() in CONTROLLED_FUNCTIONS)
    n_control = sum(
        1 for c in boundary_cells
        if (c["function"] or "").lower() in CONTROL_TARGET_FUNCTIONS)

    return {
        "schema": f"bsdl/{PARSER_SCHEMA_VERSION}",
        "entity_name": entity_name,
        "n_entities": n_entities,
        "generics": generics,
        "ports": ports,
        "tap_ports": tap_ports,
        "n_tap_present": sum(1 for v in tap_ports.values() if v is not None),
        "pin_map_ref": pin_map_ref,
        "pin_map_constant": pin_map_constant,
        "pins": pins,
        "use_clauses": use_clauses,
        "instructions": instructions,
        "instruction_capture": capture,
        "idcode_register": idcode,
        "idcode_length": idcode_length,
        "idcode_valid": idcode_valid,
        "boundary_cells": boundary_cells,
        "boundary_length_declared": length_declared,
        "boundary_length_max_cell_plus_1": max_cell_plus_1,
        "boundary_length_rel_diff": rel_diff,
        "attributes_other": attributes_other,
        "constants": constants,
        "stats": {
            "n_ports": len(ports),
            "n_pins": len(pins),
            "n_instructions": len(instructions),
            "n_boundary_cells": len(boundary_cells),
            "n_control_cells": n_control,
            "n_output3_cells": n_output3,
            "n_entities": n_entities,
            "n_unknown_statements": n_unknown,
            "n_control_chain_warnings": n_chain_bad,
            "n_pin_map_entries_skipped": n_pin_skipped,
            "n_boundary_entries_skipped": n_bnd_skipped,
            "n_warnings": len(warnings),
        },
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 查询三函数+一致性聚合（纯派生视图；不改 doc）
# --------------------------------------------------------------------------- #


def bsdl_boundary_cells(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """边界单元平坦清单（声明序文件序；深拷贝列表——调用方原地改不回流
    doc）。无边界寄存器→空列表如实。
    """
    return [dict(cell) for cell in doc.get("boundary_cells") or []]


def bsdl_cell_lookup(doc: dict[str, Any], port: str) -> dict[str, Any] | None:
    """按 port 查关联单元（大小写不敏感；BSDL 标识符不敏感语义）。

    input/clock 等直接命中=该 port 的单元清单；**总线端口名**（无索引，
    如 ``data``）同时命中其全部索引单元 ``data(i)``；带索引查询
    （``data(0)``）只命中该位。output3 等带控制序号的单元命中时**控制链
    关联**——其 control 序号指向单元一并回列（目标缺失/坏链如实不去
    补猜）；``*`` 内部单元不可寻址（跳过）。未命中→None（调用方分型，
    stil_pattern_vectors 同款口径）。
    """
    needle = str(port).lower()
    bus_prefix = needle + "("
    direct = []
    for cell in doc.get("boundary_cells") or []:
        cport = cell.get("port")
        if cport is None:
            continue
        low = str(cport).lower()
        if low == needle or low.startswith(bus_prefix):
            direct.append(cell)
    if not direct:
        return None
    by_num = {c["num"]: c for c in doc.get("boundary_cells") or []}
    control: list[dict[str, Any]] = []
    seen: set[int] = set()
    for cell in direct:
        cc = cell.get("control_cell")
        if cc is None or cc in seen:
            continue
        target = by_num.get(cc)
        if target is not None:
            seen.add(cc)
            control.append(dict(target))
    return {
        "port": port,
        "cells": [dict(cell) for cell in direct],
        "n_cells": len(direct),
        "control_cells": control,
        "n_control_cells": len(control),
    }


def bsdl_instruction_table(doc: dict[str, Any]) -> dict[str, Any]:
    """指令→opcode 表+capture/idcode 摘要（确定性插入序；纯派生拷贝）。

    ``{"instructions", "n_instructions", "capture", "capture_length",
    "idcode", "idcode_length", "idcode_valid"}``；无指令面→空表如实。
    """
    instructions = dict(doc.get("instructions") or {})
    capture = doc.get("instruction_capture")
    return {
        "instructions": instructions,
        "n_instructions": len(instructions),
        "capture": capture,
        "capture_length": len(capture) if capture is not None else None,
        "idcode": doc.get("idcode_register"),
        "idcode_length": doc.get("idcode_length"),
        "idcode_valid": doc.get("idcode_valid"),
    }
