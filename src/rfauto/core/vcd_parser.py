"""VCD（Value Change Dump，IEEE 1364-2005 附录）确定性解析内核
（aurora_q 席位 Q-X63，2026-11-08）。

数字仿真**波形交换事实标准** VCD（iverilog/Verilator/开源仿真器全走此链，
IEEE 1364 Verilog 标准附件公开规范）的只读结构化解析——数字验证面入口
格式。词法与语义全部在 core 确定性内核（铁律 7：结构化数值只出自数据源
文本本身；timescale 换算=显式档位表，LLM/agent 永不产生物理数字）。服务
包装见 :mod:`rfauto.service.vcd_service`（规则 4 JSON 进出），CLI 薄壳见
cli/domains/vcd.py（spef/sdc/verilog 同款域内自注册）。解析器集群四件套
参照：core/citi_parser.py（仪器数据流解析同代）、core/spef_parser.py
（名字映射同款）。

覆盖面（结构子集；fail-soft 口径——病态词/病态行降级为警告+跳过，不炸
全文；仅文件身份级致命面走 :class:`VcdParseError`）：

- 声明段状态机（逐关键字分派）：``$date``/``$version``（跨行块收集到
  ``$end``，空白 join）；``$timescale``（表驱动解析：
  :func:`parse_timescale`——数值 1/10/100 × 单位 fs..s 档位闭集，**非法
  fail-closed** 抛 :class:`VcdParseError`（ValueError 子类）；换算因子
  →秒）；``$scope <type> <name> $end`` 嵌套栈→层次树（scope 路径
  ``top.alu.clk`` 点分单源）；``$upscope $end`` 弹栈（空栈弹越如实警告）；
  ``$var <type> <width> <id> <name> $end``（width≥1 否则该 var 不入表+
  警告；id=ASCII 可打印 33-126 多字符编码，越界字符如实警告保留；**id
  冲突**（同 id 两 var）如实 warning+后列覆盖——vars 表以 id 为键）；
  ``$enddefinitions $end`` 切换数值段（**缺失=致命**——文件身份判定面）；
  ``$comment ... $end`` 整块收编进 comments；未知 ``$关键字`` 整块跳到
  ``$end``+warning（#208 家法 fail-soft 零进展守卫——token 流索引推进，
  无死循环面）；
- 数值段流解析：时间戳 ``#123``（非整数跳过+warning；**单调不减检查**
  违例 warning 不中断、事件按原文保留）；标量 ``0!``/``1!``/``x!``/``z!``
  （值+id 无空格；``X``/``Z`` 大写变体同收）；向量 ``b1010 #``（二进制
  串+空格+id，含 x/z 位字符如实保留字符串语义）；实数 ``r123.456 id``
  （float 解析失败原文保留+warning）；``$dumpvars``/``$dumpall``/
  ``$dumpoff``/``$dumpon`` 块内值行按正常值事件处理（初始快照是真数据，
  不丢）；``$dumpoff..$dumpon`` 窗口登记进 dump_regions（x 窗口语义；
  显式 x 值如实保留、**不合成**未显式写出的 x）；``$dumpports``（VCD
  扩展）如实计数登记+整块跳过不解析；值事件引用未声明 id→warning+事件
  如实保留（events 与 vars 键集可异，消费方自查）；先于首个时间戳的值
  事件按时间 0 归置+warning。

结构化输出（schema=vcd/1.0，全 JSON 原生类型）::

    {
      "schema": "vcd/1.0",
      "header": {"date", "version", "timescale_raw", "timescale_factor_s"},
      "scopes": {顶层名: {"type", "children": {...嵌套}, "var_ids": [...]}},
      "vars":   {id: {"name", "scope_path", "type", "width", "line"}},
      "events": {id: [[time, value], ...]（文件序，同 id 跨 var 冲突合并如实）},
      "dump_regions": {"windows": [{"start", "end"|None}], "counts": {...}},
      "stats": {"n_vars", "n_vars_declared", "n_events", "t_min", "t_max",
                "n_scopes", "per_type_counts", "per_kind_counts", "n_warnings"},
      "comments": [str],
      "warnings": [str],
    }

x/z 语义（#122 族如实分型）：标量/向量值恒为 str（``"x"`` 与数值不可比
——不做数值化）；仅实数值为 float（不可解析时原文 str+warning）；
:func:`_is_xlike` 单源判定 x-like（值含 x/X/z/Z 字符）。

查询三函数（服务/CLI 上层消费）：

- :func:`vcd_var_lookup`：按名（+可选 scope 前缀过滤）查 var 事件流——
  同名多 scope 全列如实；返回列表（未命中空列表，调用方分型）；
- :func:`vcd_signal_profile`：单 id 事件画像——事件数/首末值/变化率
  （时间归一：每 timescale 单位与每秒双口径）/x 占比；已声明零事件 id
  如实给 n_events=0 画像；未声明且零事件→None；
- :func:`vcd_time_windows`：时间戳去重清单+每窗口事件数直方摘要
  （busiest 并列取最小时间——确定性）。

:func:`vcd_activity_top`：信号活跃度聚合（事件数降序、id 升序并列稳定
——report 叶消费）。

确定性（同输入同输出）、零 IO（纯文本进出）、零第三方依赖。本模块不设
``__all__``（无 __all__ 的非门面文件不进 tests/gold/public_api.json——
spef_parser/sdc_parser/verilog_netlist_parser 同款先例，新模块零金快照
漂移）。
"""

from __future__ import annotations

import re
from typing import Any

#: 解析输出 schema 版本（键集/字段形状变更时升位）。
PARSER_SCHEMA_VERSION = "1.0"

#: 标量值字符闭集（IEEE 1364：0/1/x/z 四值 + X/Z 大写变体如实收）。
SCALAR_VALUE_CHARS = frozenset("01xzXZ")

#: 向量/实数值关键字首字符（``b``/``B`` 向量、``r``/``R`` 实数——大小写
#: 两形态规范均允许）。
VALUE_KIND_PREFIX_CHARS = frozenset("bBrR")

#: timescale 单位→秒换算基准表（档位闭集；大小写不敏感，键统一大写）。
TIMESCALE_UNIT_FACTORS: dict[str, float] = {
    "FS": 1e-15,
    "PS": 1e-12,
    "NS": 1e-9,
    "US": 1e-6,
    "MS": 1e-3,
    "S": 1.0,
}

#: timescale 数值档位闭集（IEEE 1364 惯例：1/10/100）。
TIMESCALE_MAGNITUDES = (1, 10, 100)

#: 声明段跨行块收集关键字（体收集到 ``$end``，空白 join）。
DECL_BLOCK_KEYWORDS = frozenset({"$date", "$version", "$timescale", "$comment"})

#: 数值段 dump 关键字（块内值行按正常值事件处理；``$end`` 收口）。
DUMP_KEYWORDS = ("$dumpvars", "$dumpall", "$dumpoff", "$dumpon")

_TIMESCALE_RE = re.compile(r"^(\d+)([A-Za-z]+)$")


class VcdParseError(ValueError):
    """VCD 文件身份级致命错误（空文件/缺 $enddefinitions/timescale 非法）
    ——fail-soft 之外的唯一致命面。词法/结构病态不走本异常（warning+跳过
    口径）。继承 ValueError（任务书 fail-closed 口径）。"""


def parse_timescale(raw: str) -> float:
    """timescale 原文（如 ``1ps``/``10 ns``/``100FS``）→ 换算因子（秒）。

    数值限 1/10/100、单位限 fs..s 档位闭集（表驱动：单位大小写不敏感、
    内部空白剔除）；**非法 fail-closed** 抛 :class:`VcdParseError`
    （ValueError 子类）——绝不静默猜量纲（铁律 7）。
    """
    token = "".join(raw.split())
    if not token:
        raise VcdParseError("timescale 为空——无法解析时间单位")
    m = _TIMESCALE_RE.match(token)
    if m is None:
        raise VcdParseError(
            f"timescale 形态非法: {raw!r}（应为 <数值><单位>，如 1ps/10 ns）")
    magnitude = int(m.group(1))
    if magnitude not in TIMESCALE_MAGNITUDES:
        raise VcdParseError(
            f"timescale 数值 {magnitude} 不在档位闭集 "
            f"{list(TIMESCALE_MAGNITUDES)}（{raw!r}）")
    unit = m.group(2).upper()
    factor = TIMESCALE_UNIT_FACTORS.get(unit)
    if factor is None:
        raise VcdParseError(
            f"timescale 单位 {unit!r} 不在单位闭集 "
            f"{sorted(TIMESCALE_UNIT_FACTORS)}（{raw!r}）")
    return magnitude * factor


def _is_xlike(value: Any) -> bool:
    """x-like 单源判定：str 值含 x/X/z/Z 字符（float 恒否——实数无 x/z）。"""
    return isinstance(value, str) and any(c in "xzXZ" for c in value)


def _count_scope_nodes(tree: dict[str, Any]) -> int:
    """scope 树节点总数（含嵌套）。"""
    n = 0
    for node in tree.values():
        n += 1 + _count_scope_nodes(node["children"])
    return n


def parse_vcd(text: str) -> dict[str, Any]:
    """VCD 文本 → 结构化 dict（纯函数；只做结构提取不做电气结论）。

    空文件/缺 ``$enddefinitions``/timescale 非法 →
    :class:`VcdParseError`（文件身份致命，service 层转 error 信封）；
    其余病态一律 warning+跳过（fail-soft，#208 家法）。返回键集见模块
    docstring。
    """
    if not text or not text.strip():
        raise VcdParseError("空文件（无任何内容）——拒绝解析")

    warnings: list[str] = []
    comments: list[str] = []
    header: dict[str, Any] = {
        "date": None,
        "version": None,
        "timescale_raw": None,
        "timescale_factor_s": None,
    }
    scope_tree: dict[str, dict[str, Any]] = {}
    scope_stack: list[dict[str, Any]] = []
    scope_names: list[str] = []
    vars_tab: dict[str, dict[str, Any]] = {}
    events: dict[str, list[list[Any]]] = {}
    dump_windows: list[dict[str, Any]] = []
    dump_counts: dict[str, int] = {
        "dumpvars": 0, "dumpall": 0, "dumpoff": 0, "dumpon": 0, "dumpports": 0,
    }
    kind_counts: dict[str, int] = {"scalar": 0, "vector": 0, "real": 0}
    n_declared = 0
    saw_enddefinitions = False
    phase = "decl"
    cur_time: int | None = None
    last_time: int | None = None
    pending_end: str | None = None   # 值段开放 dump 块待 $end 收口
    skip_block: str | None = None    # 值段整块跳过（$dumpports/未知关键字）

    # 词流扁平化（保留行号——VCD 逐词语法，空白等价）
    tok_stream: list[tuple[str, int]] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        for tok in raw_line.split():
            tok_stream.append((tok, line_no))
    n_tok = len(tok_stream)

    def _warn(msg: str, ln: int) -> None:
        warnings.append(f"{msg}（第 {ln} 行）")

    def _scope_path() -> str:
        return ".".join(scope_names)

    def _eff_time() -> int:
        return 0 if cur_time is None else cur_time

    def _consume_until_end(i: int) -> tuple[list[str], int]:
        """从 i 起收集词直到 ``$end``；返回 (词表, 越过 $end 后的索引)。"""
        parts: list[str] = []
        j = i
        while j < n_tok:
            tok2 = tok_stream[j][0]
            if tok2 == "$end":
                return parts, j + 1
            parts.append(tok2)
            j += 1
        return parts, j  # EOF 未遇 $end（截断态）

    def _push_scope(scope_type: str, name: str, ln: int) -> None:
        node: dict[str, Any] = {"type": scope_type, "children": {}, "var_ids": []}
        if scope_stack:
            scope_stack[-1]["children"][name] = node
        else:
            if name in scope_tree:
                _warn(f"顶层 scope 重复名 {name!r}——后者覆盖", ln)
            scope_tree[name] = node
        scope_stack.append(node)
        scope_names.append(name)

    def _register_var(vtype: str, width_tok: str, vid: str, name: str,
                      ln: int) -> None:
        nonlocal n_declared
        n_declared += 1
        if not vid:
            _warn("$var id 为空——该 var 不入表", ln)
            return
        try:
            width = int(width_tok)
        except ValueError:
            _warn(f"$var 位宽非整数 {width_tok!r}——该 var 不入表", ln)
            return
        if width < 1:
            _warn(f"$var 位宽 {width} < 1——该 var 不入表", ln)
            return
        if any(ord(c) < 33 or ord(c) > 126 for c in vid):
            _warn(f"id {vid!r} 含非可打印 ASCII 字符——如实保留登记", ln)
        if vid in vars_tab:
            prior = vars_tab[vid]
            _warn(
                f"id 冲突：{vid!r} 已登记为 {prior['name']!r}"
                f"@{prior['scope_path']}——后列 {name!r} 覆盖", ln)
        vars_tab[vid] = {
            "name": name, "scope_path": _scope_path(), "type": vtype,
            "width": width, "line": ln,
        }
        if scope_stack:
            scope_stack[-1]["var_ids"].append(vid)

    def _add_event(vid: str, value: Any, ln: int, kind: str) -> None:
        if vid not in vars_tab:
            _warn(f"值事件引用未声明 id {vid!r}——事件如实保留", ln)
        if cur_time is None:
            _warn("值事件先于首个时间戳——按时间 0 如实归置", ln)
        events.setdefault(vid, []).append([_eff_time(), value])
        kind_counts[kind] += 1

    i = 0
    while i < n_tok:
        tok, ln = tok_stream[i]

        # ────────────────── 声明段 ──────────────────
        if phase == "decl":
            if tok == "$enddefinitions":
                parts, i = _consume_until_end(i + 1)
                if parts:
                    _warn(f"$enddefinitions 行多余词 {parts}——忽略", ln)
                saw_enddefinitions = True
                phase = "values"
                continue
            if tok in DECL_BLOCK_KEYWORDS:
                parts, i = _consume_until_end(i + 1)
                body = " ".join(parts).strip()
                if tok == "$date":
                    header["date"] = body or None
                elif tok == "$version":
                    header["version"] = body or None
                elif tok == "$timescale":
                    header["timescale_raw"] = body or None
                    header["timescale_factor_s"] = parse_timescale(body)
                else:  # $comment
                    comments.append(body)
                continue
            if tok == "$scope":
                nxt = [tok_stream[j][0] for j in range(i + 1, min(i + 4, n_tok))]
                if len(nxt) >= 3 and nxt[2] == "$end":
                    _push_scope(nxt[0], nxt[1], ln)
                    i += 4
                    continue
                if len(nxt) >= 2 and nxt[1] == "$end":
                    # 类型缺省变体：$scope <name> $end
                    _push_scope("module", nxt[0], ln)
                    i += 3
                    continue
                parts, i = _consume_until_end(i + 1)
                _warn(f"$scope 形态不完整: {' '.join(parts)!r}——跳过", ln)
                continue
            if tok == "$upscope":
                if i + 1 < n_tok and tok_stream[i + 1][0] == "$end":
                    i += 2
                    if scope_stack:
                        scope_stack.pop()
                        scope_names.pop()
                    else:
                        _warn("$upscope 无匹配 $scope——忽略", ln)
                    continue
                parts, i = _consume_until_end(i + 1)
                _warn("$upscope 形态不完整——未弹栈", ln)
                continue
            if tok == "$var":
                parts, i = _consume_until_end(i + 1)
                if len(parts) < 4:
                    _warn(
                        f"$var 形态不完整（{len(parts)} 词，需 type/width/"
                        "id/name）——该 var 不入表", ln)
                    continue
                if len(parts) > 4:
                    _warn(f"$var 多余词 {parts[4:]}——取前四词", ln)
                _register_var(parts[0], parts[1], parts[2], parts[3], ln)
                continue
            if tok == "$dumpports":
                dump_counts["dumpports"] += 1
                parts, i = _consume_until_end(i + 1)
                _warn("$dumpports（VCD 扩展）如实登记不解析", ln)
                continue
            if tok == "$end":
                _warn("声明段孤立 $end——忽略", ln)
                i += 1
                continue
            if tok.startswith("$"):
                # 未知声明关键字：整块跳到 $end（fail-soft #208 家法）
                parts, i = _consume_until_end(i + 1)
                _warn(f"未知声明关键字 {tok}——整块跳过（{len(parts)} 词）", ln)
                continue
            _warn(f"声明段杂散词 {tok!r}——跳过", ln)
            i += 1
            continue

        # ────────────────── 数值段 ──────────────────
        if tok == "$end":
            if skip_block is not None:
                skip_block = None
            elif pending_end is not None:
                pending_end = None
            else:
                _warn("值段孤立 $end——忽略", ln)
            i += 1
            continue
        if skip_block is not None:
            i += 1   # 整块跳过中（$dumpports/未知关键字）——丢弃到 $end
            continue
        if tok == "$comment":
            parts, i = _consume_until_end(i + 1)
            comments.append(" ".join(parts).strip())
            continue
        if tok in DUMP_KEYWORDS:
            dump_counts[tok[1:]] += 1
            pending_end = tok
            if tok == "$dumpoff":
                dump_windows.append({"start": _eff_time(), "end": None})
            elif tok == "$dumpon":
                open_w = next(
                    (w for w in reversed(dump_windows) if w["end"] is None),
                    None)
                if open_w is None:
                    _warn("$dumpon 无匹配 $dumpoff——忽略窗口", ln)
                else:
                    open_w["end"] = _eff_time()
            i += 1
            continue
        if tok == "$dumpports":
            dump_counts["dumpports"] += 1
            skip_block = tok
            _warn("$dumpports（VCD 扩展）如实登记不解析——整块跳过", ln)
            i += 1
            continue
        if tok == "$enddefinitions":
            _warn("值段重复 $enddefinitions——忽略", ln)
            i += 1
            continue
        if tok.startswith("$"):
            skip_block = tok
            _warn(f"未知值段关键字 {tok}——整块跳过", ln)
            i += 1
            continue
        if tok.startswith("#"):
            t_raw = tok[1:]
            try:
                t = int(t_raw)
            except ValueError:
                _warn(f"时间戳非整数 {tok!r}——跳过", ln)
                i += 1
                continue
            if last_time is not None and t < last_time:
                _warn(
                    f"时间回退 {last_time} → {t}（单调不减违例）"
                    "——事件按原文保留", ln)
            cur_time = t
            last_time = t
            i += 1
            continue
        if tok[0] in VALUE_KIND_PREFIX_CHARS:
            value_txt = tok[1:]
            if i + 1 >= n_tok:
                _warn(f"{tok[0]} 值缺 id 词——跳过", ln)
                i += 1
                continue
            vid = tok_stream[i + 1][0]
            if tok[0] in "bB":
                if value_txt and all(c in "01xzXZ" for c in value_txt):
                    _add_event(vid, value_txt, ln, "vector")
                else:
                    _warn(f"向量值非法 {tok!r}——跳过（id 词已消费）", ln)
            else:
                try:
                    _add_event(vid, float(value_txt), ln, "real")
                except ValueError:
                    _warn(f"实数值不可解析 {tok!r}——原文保留", ln)
                    _add_event(vid, value_txt, ln, "real")
            i += 2
            continue
        if tok[0] in SCALAR_VALUE_CHARS:
            vid = tok[1:]
            if not vid:
                _warn(f"标量值 {tok!r} 缺 id——跳过", ln)
                i += 1
                continue
            _add_event(vid, tok[0], ln, "scalar")
            i += 1
            continue
        _warn(f"无法归类的值词 {tok!r}——跳过", ln)
        i += 1

    if not saw_enddefinitions:
        raise VcdParseError("缺少 $enddefinitions（声明段未终结）——拒绝解析")
    if pending_end is not None:
        warnings.append(f"文件截断：{pending_end} 块未以 $end 收口")
    if skip_block is not None:
        warnings.append(f"文件截断：{skip_block} 块未以 $end 收口")
    if any(w["end"] is None for w in dump_windows):
        warnings.append("文件截断：$dumpoff 窗口未以 $dumpon 闭合——end=None 如实")

    all_times = [ev[0] for evs in events.values() for ev in evs]
    per_type: dict[str, int] = {}
    for v in vars_tab.values():
        per_type[v["type"]] = per_type.get(v["type"], 0) + 1
    return {
        "schema": f"vcd/{PARSER_SCHEMA_VERSION}",
        "header": header,
        "scopes": scope_tree,
        "vars": vars_tab,
        "events": events,
        "dump_regions": {"windows": dump_windows, "counts": dump_counts},
        "stats": {
            "n_vars": len(vars_tab),
            "n_vars_declared": n_declared,
            "n_events": len(all_times),
            "t_min": min(all_times) if all_times else None,
            "t_max": max(all_times) if all_times else None,
            "n_scopes": _count_scope_nodes(scope_tree),
            "per_type_counts": per_type,
            "per_kind_counts": dict(kind_counts),
            "n_warnings": len(warnings),
        },
        "comments": comments,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# 查询三函数+活跃度聚合（纯派生视图；不改 doc）
# --------------------------------------------------------------------------- #


def vcd_var_lookup(
    doc: dict[str, Any], name: str, scope: str | None = None
) -> list[dict[str, Any]]:
    """按名（+可选 scope 前缀过滤）查 var 事件流。

    匹配口径：``vars`` 表 ``name`` 精确相等；``scope`` 给定时
    ``scope_path`` 等于该 scope 或以其 ``"."`` 前缀开头（子树过滤）。
    同名多 scope **全列如实**（返回多条）。返回元素含 id/元数据/事件流
    （事件列表为拷贝——调用方原地改不回流 doc）；未命中返回空列表。
    """
    matches: list[dict[str, Any]] = []
    for vid, v in doc["vars"].items():
        if v["name"] != name:
            continue
        if scope is not None:
            sp = v["scope_path"]
            if sp != scope and not sp.startswith(scope + "."):
                continue
        matches.append({
            "id": vid,
            "name": v["name"],
            "scope_path": v["scope_path"],
            "type": v["type"],
            "width": v["width"],
            "events": [list(ev) for ev in doc["events"].get(vid, [])],
        })
    return matches


def vcd_signal_profile(doc: dict[str, Any], var_id: str) -> dict[str, Any] | None:
    """单 id 信号画像：事件数/首末值/变化率（时间归一）/x 占比。

    变化率双口径：``change_rate_per_ts``=（事件数−1）/首末时间跨度
    （timescale 单位）；``change_rate_per_s``=每秒口径（头部
    timescale_factor_s 已知时）。跨度零（单事件/同刻）如实 None。
    x 占比=x-like 事件占比（:func:`_is_xlike` 单源）。已声明零事件 id
    如实给 n_events=0 画像（首末值/变化率 None）；未声明且零事件→None
    （调用方分型）。
    """
    evs = doc["events"].get(var_id, [])
    if var_id not in doc["vars"] and not evs:
        return None
    n = len(evs)
    first = evs[0] if evs else None
    last = evs[-1] if evs else None
    span = (last[0] - first[0]) if (first is not None and last is not None) else 0
    rate: float | None = None
    if n >= 2 and span > 0:
        rate = (n - 1) / span
    factor = doc["header"].get("timescale_factor_s")
    rate_s: float | None = None
    if rate is not None and factor is not None:
        rate_s = rate / factor
    n_x = sum(1 for ev in evs if _is_xlike(ev[1]))
    info = doc["vars"].get(var_id, {})
    return {
        "id": var_id,
        "name": info.get("name"),
        "scope_path": info.get("scope_path"),
        "type": info.get("type"),
        "width": info.get("width"),
        "n_events": n,
        "first_time": first[0] if first else None,
        "first_value": first[1] if first else None,
        "last_time": last[0] if last else None,
        "last_value": last[1] if last else None,
        "span_ts": span,
        "change_rate_per_ts": rate,
        "change_rate_per_s": rate_s,
        "n_x_events": n_x,
        "x_fraction": (n_x / n) if n else None,
    }


def vcd_time_windows(doc: dict[str, Any]) -> dict[str, Any]:
    """时间戳去重清单+每窗口事件数直方摘要。

    ``times`` 升序去重；``events_per_window`` 对齐计数（跨 id 求和）；
    ``busiest`` 最繁忙窗口（并列取最小时间——确定性），无事件时 None。
    """
    counts: dict[int, int] = {}
    for evs in doc["events"].values():
        for ev in evs:
            t = ev[0]
            counts[t] = counts.get(t, 0) + 1
    times = sorted(counts)
    busiest: dict[str, int] | None = None
    if times:
        best_t = min(times, key=lambda t: (-counts[t], t))
        busiest = {"time": best_t, "n_events": counts[best_t]}
    return {
        "n_windows": len(times),
        "times": times,
        "events_per_window": [counts[t] for t in times],
        "busiest": busiest,
    }


def vcd_activity_top(doc: dict[str, Any], top_n: int = 10) -> list[dict[str, Any]]:
    """信号活跃度聚合：按事件数降序 top-N（并列按 id 升序——确定性稳定）。

    每行=id+元数据+事件数+x 事件数/x 占比（零事件 id 如实 0/None）。
    """
    rows: list[dict[str, Any]] = []
    for vid, v in doc["vars"].items():
        evs = doc["events"].get(vid, [])
        n_x = sum(1 for ev in evs if _is_xlike(ev[1]))
        rows.append({
            "id": vid,
            "name": v["name"],
            "scope_path": v["scope_path"],
            "type": v["type"],
            "width": v["width"],
            "n_events": len(evs),
            "n_x_events": n_x,
            "x_fraction": (n_x / len(evs)) if evs else None,
        })
    rows.sort(key=lambda r: (-r["n_events"], r["id"]))
    k = max(0, int(top_n))
    return rows[:k]
