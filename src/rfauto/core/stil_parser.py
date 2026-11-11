"""STIL（Standard Test Interface Language，IEEE 1450）确定性解析内核
（aurora_q 席位 Q-X72，2026-11-08）。

数字测试向量交换**公开标准** STIL（ATPG 输出、ATE 消费）的只读结构化
解析——与 IPC-356（裸板测试）、VCD（波形）同构成测试三面。词法与语义
全部在 core 确定性内核（铁律 7：结构化数据只出自数据源文本本身；时序
事件字母表**结构化保存不解释物理含义**，LLM/agent 永不产生物理数字）。
服务包装见 :mod:`rfauto.service.stil_service`（规则 4 JSON 进出），CLI
薄壳见 cli/domains/stil.py（citi/gdsii/vcd 同款域形态）。解析器集群四件
套参照：core/vcd_parser.py（Q-X63 同代词法/状态机）、core/citi_parser.py
（仪器数据流解析同代）。

覆盖面（结构子集；fail-soft 口径——病态词/病态行降级为警告+跳过，不炸
全文；仅文件身份级致命面走 :class:`StilParseError`）：

- 词法：块结构状态机（块头关键字+``{...}`` 嵌套 brace 平衡计数；``/* */``
  与 ``//`` 注释双形态收编；``'...'``/``"..."`` 字符串单 token 收编；
  **深度守卫** :data:`MAX_BLOCK_DEPTH` 超限致命（ runaway 嵌套防栈炸）；
  brace 失衡（``{`` 未闭合到 EOF）**致命**带开括号行号，顶层多余 ``}``
  fail-soft 警告；语句未以 ``;`` 终结（文件截断）fail-soft 警告；
- Signals 块：``name = in|out|inout ;``（大小写归一小写；无 ``=`` 两词
  形态容忍）+ WFC 定义 ``WFC_0 = '0' ;``（引号/裸字双形态）→ 波形字符
  集（文件全局，定义序去重）；信号名→``{"dir", "wfcs"}``；
- SignalGroups 块：``grp = 'sig1 sig2' ;`` 成员列表（引号串空白切分；
  无引号逐词形态容忍；``'a' + 'b'`` 级联逐段并收、``+``/``&`` 级联符剔除；
  ``'_sel': '...'`` 选择器形态只取**末个 ``:`` 之后**的成员段——fail-soft
  口径如实登记）；
- Timing 块：``WaveformTable <名> { Period '50ns'; Waveforms { <组> {
  <wfc集> { <事件语句>; } } } }``——每信号组逐 WFC 事件映射表（多字符
  wfc 集 ``01`` 逐字符展开共享同一事件表；同字符重复定义后列覆盖+警告；
  事件语句 token 序列化保存（``'D'``/``10 D`` 同收）**不解释事件字母
  物理含义**）；
- PatternExec 块：``PatternBurst``/``Protocol`` 引用如实登记不展开；
- PatternBurst 块：Pattern 清单（``Pattern p;`` 声明语句=零向量空壳；
  ``Pattern p { ... }`` 内联体全解析）；顶层散置 Pattern 归 ``""`` 桶；
- Pattern 块：``W <wft>``（后列覆盖）+ ``V { 组=值串; }`` 向量行（值串
  逐字符对应该组 Signal 列表；**长度≠组员数→fail-soft 跳行警告**；未知
  组→跳行警告；值串内部空白剔除后计数）+ ``Loop n { ... }``（倍数计数
  入 stats **不物化展开**——大 Loop 不炸内存；n_loop=Loop 语句倍数累计
  和，嵌套不乘积）+ ``Shift``/``SubStroke`` 控制语句（计数/识别不展开）
  + ``Ann "..."`` 注释语句收编（pattern 域内入 anns，全域计数）；
- Import/Procedures 块（BSDL/过程引用）：如实登记名目**不展开**；未知
  关键字整块 skip 到配对块尾+warning（#208 家法 fail-soft 零进展守卫
  ——结构树整块丢弃，无死循环面）。

语义走**两遍**（先声明面 Signals/SignalGroups/Timing 后 Pattern 面——
向量行长度校验依赖 Groups 已知，声明后置的文件同样可解析）。

结构化输出（schema=stil/1.0，全 JSON 原生类型）::

    {
      "schema": "stil/1.0",
      "header_version": "1.0"|None,
      "signals":   {信号名: {"dir": "in|out|inout", "wfcs": ["0","1"]}},
      "groups":    {组名: [成员信号, ...]},
      "timing":    {wft名: {"period": str|None,
                            "waveforms": {组: {wfc字符: [事件token, ...]}}}},
      "patterns":  {burst名(顶层散置=""): {"patterns": {pattern名: {
                       "wft": str|None,
                       "vectors": [{"group", "values"}, ...],
                       "n_loop": int,   # Loop 倍数累计和（不物化）
                       "n_shift": int,  # Shift 语句个数
                       "anns": [str, ...]}}}},
      "imports": [名, ...],        # 如实登记不展开
      "procedures": [名, ...],     # 如实登记不展开
      "pattern_execs": {名: {"pattern_burst": str|None, "protocol": str|None}},
      "stats": {"n_signals", "n_groups", "n_patterns", "n_vectors_total",
                "n_ann", "n_bursts", "n_wfts", "n_loop_multiplier_total",
                "n_shift_total", "n_vector_rows_skipped",
                "n_unknown_blocks", "n_warnings"},
      "warnings": [str],
    }

查询三函数（服务/CLI 上层消费）：

- :func:`stil_pattern_vectors`：跨 burst 查 pattern 向量平坦清单（burst
  插入序首个命中——确定性；未命中 None 调用方分型）；
- :func:`stil_vector_at`：第 idx 向量行+其 WFC 时序事件联查——组值串逐
  字符→对应 wft 波形表映射（缺映射/缺 wft 如实 None **不猜**）；idx 越
  界/负值/未命中→None；
- :func:`stil_coverage_stats`：每 pattern 向量数/Loop 倍数/信号组覆盖
  计数（覆盖组名录+全组覆盖率分数；无 patterns 时 fraction None）。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。本模块不设
``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json——
vcd_parser/spef_parser 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 块嵌套深度守卫（runaway 嵌套防栈炸——超限致命 StilParseError）。
MAX_BLOCK_DEPTH = 100

#: 信号方向闭集（IEEE 1450；大小写归一小写后比对）。
SIGNAL_DIRECTIONS = frozenset({"in", "out", "inout"})

#: 已知控制语句/块关键字（Pattern 域内识别不警告；SubStroke 只识别不计数）。
PATTERN_CONTROL_BLOCKS = frozenset({"Loop", "Shift", "SubStroke"})

#: SignalGroups 成员级联符（``'a' + 'b'`` 形态的结构性记号，剔除不入成员）。
_GROUP_CONCAT_TOKENS = frozenset({"+", "&"})

#: PatternExec 块内引用语句关键字 → 输出字段（如实登记不展开）。
_EXEC_REF_FIELDS: dict[str, str] = {
    "PatternBurst": "pattern_burst",
    "Protocol": "protocol",
}


class StilParseError(ValueError):
    """STIL 文件身份级致命错误（空文件/缺 STIL 头/brace 失衡/嵌套超深）
    ——fail-soft 之外的唯一致命面。词法/结构病态不走本异常（warning+跳过
    口径）。继承 ValueError（vcd_parser 同款口径）。"""


# --------------------------------------------------------------------------- #
# 词法：token 流（kind ∈ {"word","string","{","}",";"}，携带行号）
# --------------------------------------------------------------------------- #


def _tokenize(text: str) -> tuple[list[tuple[str, str, int]], list[str]]:
    """STIL 文本 → (token 流, 词法警告)。

    token 三元组 ``(kind, value, line)``：word=裸词（空白/括点/引号/分号
    终结）、string=引号串内容（``'...'``/``"..."`` 双形态；STIL 无转义
    惯例——引号字面闭合）、``{``/``}``/``;`` 单字符。注释双形态（块
    ``/* */``/行 ``//``）剔除并保持行号推进；块注释/引号串未闭合
    fail-soft 警告（行号=起点）。
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
        if c == "/" and text[i + 1:i + 2] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                warns.append(f"块注释未闭合（第 {line} 行起）——至文件尾如实收编")
                line += text.count("\n", i)
                i = n
            else:
                line += text.count("\n", i, end)
                i = end + 2
            continue
        if c == "/" and text[i + 1:i + 2] == "/":
            end = text.find("\n", i)
            i = n if end == -1 else end  # 行注释：换行留给下轮推进行号
            continue
        if c in "{};":
            tokens.append((c, c, line))
            i += 1
            continue
        if c in "'\"":
            end = text.find(c, i + 1)
            if end == -1:
                end = text.find("\n", i)
                if end == -1:
                    end = n
                tokens.append(("string", text[i + 1:end], line))
                warns.append(f"字符串引号未闭合（第 {line} 行）——至行/文件尾如实收编")
                line += text.count("\n", i)
                i = n
            else:
                tokens.append(("string", text[i + 1:end], line))
                line += text.count("\n", i, end)
                i = end + 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n\f\v{};'\"":
            j += 1
        tokens.append(("word", text[i:j], line))
        i = j
    return tokens, warns


# --------------------------------------------------------------------------- #
# 块结构状态机：token 流 → 语句/块树（brace 平衡+深度守卫）
# --------------------------------------------------------------------------- #


def _parse_block_tree(
    toks: list[tuple[str, str, int]], warnings: list[str]
) -> list[Any]:
    """token 流 → 顶层条目树。

    条目形态：``("stmt", [(kind, val, ln), ...])``（到 ``;`` 终结）或
    ``("block", 关键字, 名|None, [子条目], 行号)``。块头=``关键字 [名] {``
    两形态；brace 失衡（EOF 未闭合）致命 :class:`StilParseError` 带开括
    号行号；顶层多余 ``}`` fail-soft 警告；深度守卫超限致命。
    """
    items, _end = _parse_items(toks, 0, 0, warnings, top_level=True)
    return items


def _parse_items(
    toks: list[tuple[str, str, int]],
    i: int,
    depth: int,
    warnings: list[str],
    *,
    top_level: bool,
) -> tuple[list[Any], int]:
    n = len(toks)
    items: list[Any] = []
    while i < n:
        kind, val, ln = toks[i]
        if kind == ";":
            i += 1  # 孤立分号：静默跳过（零信息量，不造警告噪声）
            continue
        if kind == "}":
            if top_level:
                warnings.append(f"第 {ln} 行多余的 '}}'（顶层无开放块）——忽略")
                i += 1
                continue
            return items, i  # 正常块收口（调用方消费 }
        # 块头前瞻（仅 word 起头）：关键字 [名] {
        is_block_header = kind == "word" and (
            (i + 1 < n and toks[i + 1][0] == "{")
            or (i + 2 < n and toks[i + 1][0] == "word"
                and toks[i + 2][0] == "{"))
        if is_block_header:
            if toks[i + 1][0] == "{":
                kw: str = val
                name: str | None = None
                brace_i = i + 1
            else:
                kw = val
                name = toks[i + 1][1]
                brace_i = i + 2
        else:
            # 语句收集到 ;（word 起头主形态 + string 起头事件语句如 'D';）
            stmt = [toks[i]]
            j = i + 1
            while j < n and toks[j][0] != ";":
                stmt.append(toks[j])
                j += 1
            if j >= n:
                warnings.append(
                    f"第 {ln} 行语句未以 ';' 终结（文件截断）——如实收编")
            items.append(("stmt", stmt))
            i = j + 1  # 越过 ;（j==n 时置 n，循环退出）
            continue
        if depth + 1 > MAX_BLOCK_DEPTH:
            raise StilParseError(
                f"第 {ln} 行块嵌套超过深度守卫 {MAX_BLOCK_DEPTH}——拒绝解析")
        body, j2 = _parse_items(toks, brace_i + 1, depth + 1, warnings,
                                top_level=False)
        if j2 >= n:
            raise StilParseError(
                f"第 {ln} 行 '{{' 未闭合（brace 失衡）——文件截断")
        items.append(("block", kw, name, body, ln))
        i = j2 + 1  # 越过收口 }
    return items, i


# --------------------------------------------------------------------------- #
# 语义小件
# --------------------------------------------------------------------------- #


def _stmt_words(stmt: list[tuple[str, str, int]]) -> list[str]:
    """语句 token 值列表（word 原样、string 内容原样——引号已剥离）。"""
    return [v for _, v, _ln in stmt]


def _stmt_name(stmt: list[tuple[str, str, int]]) -> str:
    """语句首个 word 的值（语句分类键）。"""
    return stmt[0][1]


def _split_group_members(stmt: list[tuple[str, str, int]]) -> list[str]:
    """SignalGroups 赋值语句 → 成员列表（fail-soft 多形态）。

    取值段=``=`` 之后的 token（缺 ``=`` 时=组名之后）；值段含 ``:``
    （``'_sel': 'a b'`` 选择器形态）时只取**末个 ``:`` 之后**的 token；
    逐 token 收成员：string 内容空白切分、word 原样（``+``/``&`` 级联符
    与 ``:`` 剔除）——``'a' + 'b'``/``'a b'``/``a b`` 三形态同得 [a, b]。
    """
    tail = stmt[1:]
    for idx, (kind, val, _ln) in enumerate(tail):
        if kind == "word" and val == "=":
            tail = tail[idx + 1:]
            break
    colon_idx = [i for i, (k, v, _l) in enumerate(tail) if k == "word" and v == ":"]
    if colon_idx:
        tail = tail[colon_idx[-1] + 1:]
    members: list[str] = []
    for kind, val, _ln in tail:
        if kind == "string":
            members.extend(val.split())
        elif val not in _GROUP_CONCAT_TOKENS and val != ":":
            members.append(val)
    return members


def _scalar_value(stmt: list[tuple[str, str, int]]) -> str | None:
    """语句末个 token 值（Period/W/WFC 值/Loop 倍数等单值提取）。"""
    return stmt[-1][1] if len(stmt) >= 2 else None


def _warn(warnings: list[str], msg: str, ln: int) -> None:
    warnings.append(f"{msg}（第 {ln} 行）")


# --------------------------------------------------------------------------- #
# 声明面提取（Signals / SignalGroups / Timing / 登记面）
# --------------------------------------------------------------------------- #


def _extract_signals(
    body: list[Any],
    signals: dict[str, dict[str, Any]],
    wfc_chars: list[str],
    warnings: list[str],
) -> None:
    """Signals 块体 → 信号表+全局 WFC 字符集（定义序去重）。

    ``name = dir ;`` 主形态；``name dir ;`` 两词形态容忍；``WFC_x = c ;``
    为 WFC 定义（引号/裸字双形态）；重复信号后列覆盖+警告；未知形态/
    未知方向 fail-soft 警告（未知方向如实登记原值小写）。
    """
    for item in body:
        if item[0] == "block":
            _warn(warnings, f"Signals 块内未知子块 {item[1]!r}——整块跳过", item[4])
            continue
        stmt = item[1]
        if not stmt or stmt[0][0] != "word":
            _warn(warnings, "Signals 块内杂散语句——跳过", stmt[0][2] if stmt else 0)
            continue
        ln = stmt[0][2]
        words = _stmt_words(stmt)
        if len(words) >= 3 and words[1] == "=" and words[0].startswith("WFC"):
            ch = words[2].strip() or None
            if ch:
                if ch not in wfc_chars:
                    wfc_chars.append(ch)
            else:
                _warn(warnings, f"WFC 定义值空 {words[0]!r}——不入字符集", ln)
            continue
        if len(words) >= 3 and words[1] == "=":
            name, direction = words[0], words[2].lower()
        elif len(words) == 2:
            name, direction = words[0], words[1].lower()
        else:
            _warn(warnings,
                  f"Signals 语句形态不识 {' '.join(words)!r}——跳过", ln)
            continue
        if direction not in SIGNAL_DIRECTIONS:
            _warn(warnings,
                  f"信号 {name!r} 方向 {direction!r} 不在闭集"
                  f" {sorted(SIGNAL_DIRECTIONS)}——如实登记", ln)
        if name in signals:
            _warn(warnings, f"信号重复名 {name!r}——后列覆盖", ln)
        signals[name] = {"dir": direction, "wfcs": []}
    # WFC 字符集文件全局（定义序）——块体走完后统一回填（WFC 定义后置的
    # 文件同样拿全集；快照序不依赖声明/定义相对顺序）。
    for sig in signals.values():
        sig["wfcs"] = list(wfc_chars)


def _extract_groups(
    body: list[Any],
    groups: dict[str, list[str]],
    warnings: list[str],
) -> None:
    """SignalGroups 块体 → 组名→成员列表（重复名后列覆盖+警告）。"""
    for item in body:
        if item[0] == "block":
            _warn(warnings, f"SignalGroups 块内未知子块 {item[1]!r}——整块跳过",
                  item[4])
            continue
        stmt = item[1]
        if not stmt or stmt[0][0] != "word":
            _warn(warnings, "SignalGroups 块内杂散语句——跳过",
                  stmt[0][2] if stmt else 0)
            continue
        ln = stmt[0][2]
        words = _stmt_words(stmt)
        if len(words) >= 2 and words[1] == "=":
            members = _split_group_members(stmt)
        elif len(words) >= 2:
            # 无 = 形态：组名后 token 按同一成员口径容忍（引号串仍切分）
            members = _split_group_members(stmt)
            _warn(warnings,
                  f"组 {words[0]!r} 赋值缺 '='——按组名后成员容忍", ln)
        else:
            _warn(warnings, "SignalGroups 语句形态不识——跳过", ln)
            continue
        if not members:
            _warn(warnings, f"组 {words[0]!r} 成员列表为空——如实登记空组", ln)
        if words[0] in groups:
            _warn(warnings, f"组重复名 {words[0]!r}——后列覆盖", ln)
        groups[words[0]] = members


def _extract_waveforms(
    body: list[Any],
    waveforms: dict[str, dict[str, list[str]]],
    warnings: list[str],
) -> None:
    """Waveforms 块体 → 组→{wfc 字符: 事件 token 表}。

    ``<组> { <wfc集> { <事件语句>; ... } }``；多字符 wfc 集（如 ``01``）
    逐字符展开共享同一事件表；同字符重复定义后列覆盖+警告；事件语句
    token 序列化保存（**不解释事件字母物理含义**——铁律 7 结构化口径）。
    """
    for item in body:
        if item[0] != "block":
            _warn(warnings, "Waveforms 块内杂散语句——跳过", item[1][0][2])
            continue
        _mark, group_name, _gname, g_body, g_ln = item
        for sub in g_body:
            if sub[0] != "block":
                _warn(warnings,
                      f"Waveforms 组 {group_name!r} 内杂散语句——跳过",
                      sub[1][0][2] if sub[1] else g_ln)
                continue
            _kw2, wfc_set, _n2, ev_body, ev_ln = sub
            events: list[str] = []
            for ev_item in ev_body:
                if ev_item[0] != "stmt":
                    _warn(warnings,
                          f"Waveforms {group_name!r}/{wfc_set!r} 事件域内"
                          "意外子块——跳过", ev_ln)
                    continue
                events.extend(_stmt_words(ev_item[1]))
            for ch in wfc_set:
                if ch in waveforms.setdefault(group_name, {}):
                    _warn(warnings,
                          f"WFC 字符 {ch!r} 在组 {group_name!r} 重复定义"
                          "——后列覆盖", ev_ln)
                waveforms[group_name][ch] = list(events)


def _extract_timing(
    body: list[Any],
    timing: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    """Timing 块体 → WaveformTable 清单（period+waveforms；重名后列覆盖）。"""
    for item in body:
        if item[0] != "block":
            _warn(warnings, "Timing 块内杂散语句——跳过", item[1][0][2])
            continue
        _mark, kw, name, w_body, ln = item
        if kw != "WaveformTable":
            _warn(warnings, f"Timing 块内未知子块 {kw!r}——整块跳过", ln)
            continue
        wft_name = name or ""
        period: str | None = None
        waveforms: dict[str, dict[str, list[str]]] = {}
        for sub in w_body:
            if sub[0] == "stmt":
                words = _stmt_words(sub[1])
                if words and words[0] == "Period":
                    period = _scalar_value(sub[1])
                else:
                    _warn(warnings,
                          f"WaveformTable {wft_name!r} 内未知语句"
                          f" {(words[0] if words else '')!r}——跳过",
                          sub[1][0][2] if sub[1] else ln)
            elif sub[0] == "block":
                if sub[1] == "Waveforms":
                    _extract_waveforms(sub[3], waveforms, warnings)
                else:
                    _warn(warnings,
                          f"WaveformTable {wft_name!r} 内未知子块"
                          f" {sub[1]!r}——整块跳过", sub[4])
        if wft_name in timing:
            _warn(warnings, f"WaveformTable 重复名 {wft_name!r}——后列覆盖", ln)
        timing[wft_name] = {"period": period, "waveforms": waveforms}


# --------------------------------------------------------------------------- #
# Pattern 面提取（burst/pattern/向量行/Loop/Shift/Ann）
# --------------------------------------------------------------------------- #


def _parse_vector_rows(
    body: list[Any],
    groups: dict[str, list[str]],
    vectors: list[dict[str, str]],
    skipped: list[int],
    warnings: list[str],
) -> None:
    """V 块体 → 向量行清单（fail-soft：长度不符/未知组跳行+警告）。

    ``组 = 值串 ;``（``=`` 缺省两词形态容忍）；值串内部空白剔除后逐字符
    对应该组 Signal 列表——长度≠组员数→跳行警告；未知组→跳行警告。
    """
    for item in body:
        if item[0] == "block":
            _warn(warnings, f"V 块内未知子块 {item[1]!r}——整块跳过", item[4])
            continue
        stmt = item[1]
        if not stmt or stmt[0][0] != "word":
            _warn(warnings, "V 块内杂散语句——跳过", stmt[0][2] if stmt else 0)
            continue
        ln = stmt[0][2]
        words = _stmt_words(stmt)
        if len(words) >= 3 and words[1] == "=":
            group, raw = words[0], words[2]
        elif len(words) == 2:
            group, raw = words
            _warn(warnings, f"向量行 {group!r} 缺 '='——按两词形态容忍", ln)
        else:
            _warn(warnings, f"向量行形态不识 {' '.join(words)!r}——跳过", ln)
            continue
        values = "".join(raw.split())
        members = groups.get(group)
        if members is None:
            skipped.append(ln)
            _warn(warnings,
                  f"向量行引用未知组 {group!r}（可用组: "
                  f"{', '.join(groups) or '无'}）——跳行", ln)
            continue
        if len(values) != len(members):
            skipped.append(ln)
            _warn(warnings,
                  f"向量行 {group!r} 值串长度 {len(values)} ≠ 组员数 "
                  f"{len(members)}——跳行", ln)
            continue
        vectors.append({"group": group, "values": values})


def _walk_pattern_body(
    body: list[Any],
    pentry: dict[str, Any],
    groups: dict[str, list[str]],
    warnings: list[str],
) -> None:
    """Pattern 体递归走查（V/Loop/Shift/SubStroke/W/Ann）。

    Loop 倍数计数入 ``n_loop``（倍数累计和——**不物化展开**，嵌套不乘积；
    倍数非正整数→警告按 1 计）；Shift 计数入 ``n_shift``；SubStroke 识别
    不计数；V 块行解析进 vectors；``W`` 后列覆盖 wft；``Ann`` 文本收编。
    """
    for item in body:
        if item[0] == "stmt":
            stmt = item[1]
            if not stmt or stmt[0][0] != "word":
                _warn(warnings, "Pattern 域内杂散语句——跳过",
                      stmt[0][2] if stmt else 0)
                continue
            ln = stmt[0][2]
            key = _stmt_name(stmt)
            if key == "W":
                pentry["wft"] = _scalar_value(stmt)
            elif key == "Ann":
                strs = [v for k, v, _l in stmt if k == "string"]
                pentry["anns"].append(strs[0] if strs else
                                      " ".join(_stmt_words(stmt)[1:]))
            elif key == "PatternExec":
                pass  # 域内引用语句：结构已收（burst 面），零进展守卫不造噪声
            else:
                _warn(warnings, f"Pattern 域内未知语句 {key!r}——跳过", ln)
            continue
        _mark, kw, name, sub_body, ln = item
        if kw == "V":
            _parse_vector_rows(sub_body, groups, pentry["vectors"],
                               pentry["skipped_lines"], warnings)
        elif kw in PATTERN_CONTROL_BLOCKS:
            # 控制语句闭集（Loop/Shift/SubStroke）：体内递归走查，账目分派——
            # Loop 倍数累计（不物化展开）/Shift 计数/SubStroke 识别不计数。
            if kw == "Loop":
                pentry["n_loop"] += _loop_multiplier(name, ln, warnings)
            elif kw == "Shift":
                pentry["n_shift"] += 1
            _walk_pattern_body(sub_body, pentry, groups, warnings)
        elif kw == "Pattern":
            _warn(warnings, "Pattern 域内嵌套 Pattern——整块跳过", ln)
        else:
            _warn(warnings, f"Pattern 域内未知子块 {kw!r}——整块跳过", ln)


def _loop_multiplier(name: str | None, ln: int, warnings: list[str]) -> int:
    """Loop 块名 → 倍数（缺省/非整数/非正→警告按 1 计；fail-soft）。"""
    if name is None:
        _warn(warnings, "Loop 缺倍数——按 1 计", ln)
        return 1
    try:
        mult = int(name)
    except ValueError:
        _warn(warnings, f"Loop 倍数 {name!r} 非整数——按 1 计", ln)
        return 1
    if mult < 1:
        _warn(warnings, f"Loop 倍数 {mult} < 1——按 1 计", ln)
        return 1
    return mult


def _count_anns(items: list[Any]) -> int:
    """全域 Ann 语句计数（块树单次递归扫——任意域内的 Ann 都计一次）。"""
    n = 0
    for it in items:
        if it[0] == "stmt":
            stmt = it[1]
            if stmt and stmt[0][0] == "word" and _stmt_name(stmt) == "Ann":
                n += 1
        else:  # block
            n += _count_anns(it[3])
    return n


def _new_pattern_entry() -> dict[str, Any]:
    return {
        "wft": None,
        "vectors": [],
        "n_loop": 0,
        "n_shift": 0,
        "anns": [],
        "skipped_lines": [],
    }


def _extract_pattern_block(
    item: tuple[Any, ...],
    bucket: dict[str, dict[str, Any]],
    groups: dict[str, list[str]],
    warnings: list[str],
) -> None:
    """单个 Pattern 块 → 归入 burst 桶（重名后列覆盖+警告）。"""
    _mark, _kw2, name, p_body, ln = item
    pname = name or ""
    pentry = _new_pattern_entry()
    _walk_pattern_body(p_body, pentry, groups, warnings)
    if pname in bucket:
        _warn(warnings, f"Pattern 重复名 {pname!r}（同 burst）——后列覆盖", ln)
    bucket[pname] = pentry


def _extract_burst(
    item: tuple[Any, ...],
    patterns: dict[str, dict[str, Any]],
    pattern_execs: dict[str, dict[str, Any]],
    groups: dict[str, list[str]],
    warnings: list[str],
) -> None:
    """PatternBurst 块 → burst 桶（Pattern 声明语句/内联体/PatternExec）。"""
    _mark, _kw2, bname, b_body, ln = item
    bucket_name = bname or ""
    bucket: dict[str, dict[str, Any]] = {}
    for sub in b_body:
        if sub[0] == "stmt":
            stmt = sub[1]
            if not stmt or stmt[0][0] != "word":
                _warn(warnings, "PatternBurst 域内杂散语句——跳过",
                      stmt[0][2] if stmt else ln)
                continue
            key = _stmt_name(stmt)
            if key == "Pattern":
                if len(stmt) < 2:
                    _warn(warnings, "Pattern 声明缺名——跳过", stmt[0][2])
                    continue
                pname = stmt[1][1]
                if pname in bucket:
                    _warn(warnings,
                          f"Pattern 重复名 {pname!r}（同 burst）——后列覆盖",
                          stmt[0][2])
                bucket[pname] = _new_pattern_entry()
            elif key == "PatternExec":
                pass  # 引用语句：PatternExec 块面（pattern_execs）单源登记
            elif key == "Ann":
                pass  # burst 域 Ann：计数在 Pattern 面——burst 域零进展容忍
            else:
                _warn(warnings,
                      f"PatternBurst 域内未知语句 {key!r}——跳过", stmt[0][2])
        elif sub[0] == "block":
            if sub[1] == "Pattern":
                _extract_pattern_block(sub, bucket, groups, warnings)
            elif sub[1] == "PatternExec":
                _extract_pattern_exec(sub, pattern_execs, warnings)
            else:
                _warn(warnings,
                      f"PatternBurst 域内未知子块 {sub[1]!r}——整块跳过", sub[4])
    if bucket_name in patterns:
        _warn(warnings, f"PatternBurst 重复名 {bucket_name!r}——后列覆盖", ln)
    patterns[bucket_name] = {"patterns": bucket}


def _extract_pattern_exec(
    item: tuple[Any, ...],
    pattern_execs: dict[str, dict[str, Any]],
    warnings: list[str],
) -> None:
    """PatternExec 块 → 引用登记（PatternBurst/Protocol；如实不展开）。"""
    _mark, _kw2, name, body, ln = item
    ename = name or ""
    refs: dict[str, str | None] = {"pattern_burst": None, "protocol": None}
    for sub in body:
        if sub[0] == "block":
            _warn(warnings,
                  f"PatternExec {ename!r} 域内意外子块 {sub[1]!r}——跳过",
                  sub[4])
            continue
        stmt = sub[1]
        if not stmt or stmt[0][0] != "word":
            continue
        key = _stmt_name(stmt)
        field = _EXEC_REF_FIELDS.get(key)
        if field is not None:
            refs[field] = _scalar_value(stmt)
        else:
            _warn(warnings,
                  f"PatternExec {ename!r} 域内未知语句 {key!r}——跳过",
                  stmt[0][2])
    if ename in pattern_execs:
        _warn(warnings, f"PatternExec 重复名 {ename!r}——后列覆盖", ln)
    pattern_execs[ename] = refs


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def parse_stil(text: str) -> dict[str, Any]:
    """STIL 文本 → 结构化 dict（纯函数；只做结构提取不做测试结论）。

    空文件/缺 ``STIL <版本>;`` 头/brace 失衡/嵌套超深 →
    :class:`StilParseError`（文件身份致命，service 层转 error 信封）；
    其余病态一律 warning+跳过（fail-soft，#208 家法）。返回键集见模块
    docstring。
    """
    if not text or not text.strip():
        raise StilParseError("空文件（无任何内容）——拒绝解析")

    warnings: list[str] = []
    toks, lex_warns = _tokenize(text)
    warnings.extend(lex_warns)

    items = _parse_block_tree(toks, warnings)

    header_version: str | None = None
    signals: dict[str, dict[str, Any]] = {}
    wfc_chars: list[str] = []
    groups: dict[str, list[str]] = {}
    timing: dict[str, dict[str, Any]] = {}
    patterns: dict[str, dict[str, Any]] = {}
    imports: list[str] = []
    procedures: list[str] = []
    pattern_execs: dict[str, dict[str, Any]] = {}
    n_unknown_blocks = 0
    pattern_work: list[tuple[str, Any]] = []  # 第二遍 Pattern 面作业清单

    # 第一遍：头部/声明面/登记面（Pattern 项只收作业不展开）
    for item in items:
        if item[0] == "stmt":
            stmt = item[1]
            if not stmt or stmt[0][0] != "word":
                continue  # 域内杂散已在词法/块层面警告
            ln = stmt[0][2]
            key = _stmt_name(stmt)
            if key == "STIL":
                header_version = _scalar_value(stmt)
            elif key == "Import":
                strs = [v for k, v, _l in stmt if k == "string"]
                imports.append(strs[-1] if strs else
                               (_stmt_words(stmt)[1] if len(stmt) >= 2 else ""))
            elif key == "Ann":
                pass  # 全域计数见 _count_anns（块树单扫）
            elif key == "Pattern":
                # 顶层散置 Pattern 声明语句（无体）——"" 桶空壳（第二遍）
                if len(stmt) >= 2:
                    pattern_work.append(("decl", (stmt[1][1], ln)))
                else:
                    _warn(warnings, "Pattern 声明缺名——跳过", ln)
            else:
                _warn(warnings, f"顶层未知语句 {key!r}——跳过", ln)
            continue
        _mark, kw, _name, body, ln = item
        if kw == "Signals":
            _extract_signals(body, signals, wfc_chars, warnings)
        elif kw == "SignalGroups":
            _extract_groups(body, groups, warnings)
        elif kw == "Timing":
            _extract_timing(body, timing, warnings)
        elif kw == "PatternBurst":
            pattern_work.append(("burst", item))
        elif kw == "Pattern":
            pattern_work.append(("block", item))
        elif kw == "PatternExec":
            _extract_pattern_exec(item, pattern_execs, warnings)
        elif kw == "Procedures":
            for sub in body:
                if sub[0] == "block":
                    procedures.append(sub[2] or sub[1] or "")
                # 域内语句（如 WFT 引用）如实不展开——零进展守卫
        else:
            n_unknown_blocks += 1
            _warn(warnings, f"未知顶层块 {kw!r}——整块跳过", ln)

    if header_version is None:
        raise StilParseError(
            "缺少 'STIL <版本>;' 头（文件身份面）——拒绝解析")

    # 第二遍：Pattern 面（向量行长度校验依赖 Groups 已知——Pattern 块先于
    # SignalGroups 后置的文件同样可解析；作业按文件序处理，警告序确定）。
    for kind, payload in pattern_work:
        if kind == "burst":
            _extract_burst(payload, patterns, pattern_execs, groups, warnings)
        elif kind == "block":
            patterns.setdefault("", {"patterns": {}})
            _extract_pattern_block(payload, patterns[""]["patterns"], groups,
                                   warnings)
        else:  # decl：顶层散置声明语句（无体空壳）
            pname, ln = payload
            patterns.setdefault("", {"patterns": {}})
            bucket = patterns[""]["patterns"]
            if pname in bucket:
                _warn(warnings,
                      f"Pattern 重复名 {pname!r}（同 burst）——后列覆盖", ln)
            bucket[pname] = _new_pattern_entry()

    # 聚合（Ann 全域计数=块树单扫；跳行账目收尾剥离）
    all_vectors = 0
    loop_total = 0
    shift_total = 0
    n_skipped = 0
    for bdata in patterns.values():
        for pentry in bdata["patterns"].values():
            all_vectors += len(pentry["vectors"])
            loop_total += pentry["n_loop"]
            shift_total += pentry["n_shift"]
            n_skipped += len(pentry["skipped_lines"])
            pentry.pop("skipped_lines", None)
    n_ann = _count_anns(items)

    n_patterns = sum(len(b["patterns"]) for b in patterns.values())
    return {
        "schema": f"stil/{PARSER_SCHEMA_VERSION}",
        "header_version": header_version,
        "signals": signals,
        "groups": groups,
        "timing": timing,
        "patterns": patterns,
        "imports": imports,
        "procedures": procedures,
        "pattern_execs": pattern_execs,
        "stats": {
            "n_signals": len(signals),
            "n_groups": len(groups),
            "n_patterns": n_patterns,
            "n_vectors_total": all_vectors,
            "n_ann": n_ann,
            "n_bursts": len(patterns),
            "n_wfts": len(timing),
            "n_loop_multiplier_total": loop_total,
            "n_shift_total": shift_total,
            "n_vector_rows_skipped": n_skipped,
            "n_unknown_blocks": n_unknown_blocks,
            "n_warnings": len(warnings),
        },
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 查询三函数+覆盖统计（纯派生视图；不改 doc）
# --------------------------------------------------------------------------- #


def _find_pattern(
    doc: dict[str, Any], pattern: str
) -> tuple[str, dict[str, Any]] | None:
    """跨 burst 查 pattern（burst 插入序首个命中——确定性）。"""
    for burst, bdata in doc["patterns"].items():
        pats = bdata["patterns"]
        if pattern in pats:
            return burst, pats[pattern]
    return None


def stil_pattern_vectors(
    doc: dict[str, Any], pattern: str
) -> list[dict[str, str]] | None:
    """pattern 向量平坦清单（``[{"group", "values"}, ...]`` 文件序拷贝）。

    burst 插入序首个命中；未命中→None（调用方分型）。返回深拷贝列表
    （调用方原地改不回流 doc）。声明语句型 pattern（无内联体）→空列表
    如实。
    """
    hit = _find_pattern(doc, pattern)
    if hit is None:
        return None
    _burst, pentry = hit
    return [{"group": v["group"], "values": v["values"]}
            for v in pentry["vectors"]]


def stil_vector_at(
    doc: dict[str, Any], pattern: str, idx: int
) -> dict[str, Any] | None:
    """第 idx 向量行+其 WFC 时序事件联查。

    ``events`` 与值串逐字符对齐：每字符→该 pattern wft 波形表中对应组
    的事件表（缺 wft/缺组/缺该字符映射→**如实 None 不猜**——铁律 7）。
    pattern 未命中/idx 越界/负值→None（无 Python 负索引语义——确定性）。
    """
    hit = _find_pattern(doc, pattern)
    if hit is None:
        return None
    _burst, pentry = hit
    vectors = pentry["vectors"]
    if idx < 0 or idx >= len(vectors):
        return None
    row = vectors[idx]
    wft = pentry["wft"]
    waveforms: dict[str, dict[str, list[str]]] = {}
    if wft is not None:
        waveforms = doc["timing"].get(wft, {}).get("waveforms", {})
    group_map = waveforms.get(row["group"], {})
    events = [group_map.get(ch) for ch in row["values"]]
    return {
        "pattern": pattern,
        "index": idx,
        "group": row["group"],
        "values": row["values"],
        "wft": wft,
        "events": events,
    }


def stil_coverage_stats(doc: dict[str, Any]) -> dict[str, Any]:
    """每 pattern 向量数/Loop 倍数/信号组覆盖计数（确定性插入序）。

    每行=``{"burst", "pattern", "n_vectors", "n_loop", "n_shift",
    "groups_covered", "n_groups_covered"}``；顶层聚合=覆盖组名录（去重
    排序）/全组覆盖分数（无 patterns 时 0.0 如实——未覆盖任何组；仅在
    无组的退化态分数无定义给 None）。
    """
    rows: list[dict[str, Any]] = []
    covered: set[str] = set()
    for burst, bdata in doc["patterns"].items():
        for pname, pentry in bdata["patterns"].items():
            used = {v["group"] for v in pentry["vectors"]}
            covered |= used
            rows.append({
                "burst": burst,
                "pattern": pname,
                "n_vectors": len(pentry["vectors"]),
                "n_loop": pentry["n_loop"],
                "n_shift": pentry["n_shift"],
                "groups_covered": sorted(used),
                "n_groups_covered": len(used),
            })
    n_total = len(doc["groups"])
    fraction: float | None = None
    if n_total > 0:
        fraction = len(covered & set(doc["groups"])) / n_total
    return {
        "patterns": rows,
        "n_patterns": len(rows),
        "n_groups_total": n_total,
        "n_groups_covered_distinct": len(covered & set(doc["groups"])),
        "covered_groups": sorted(covered & set(doc["groups"])),
        "coverage_fraction": fraction,
    }
