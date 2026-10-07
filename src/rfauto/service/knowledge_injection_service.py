"""knowledge_injection_service —— AD-2 会话知识注入组装器（SK 规格包 V §二）。

定位（唯一跨源融合点，Q1b 裁决）：检索读侧五源保持单职责源直连（不建
facade，Q1），本模块是**唯一允许同时 import 坑账/rationale/rag/knowledge
四源**的模块（防双注入面钉 2；tests/unit/test_w5_a_knowledge_bus.py 驻守）。
消费面=chat 链 ``r3_services._llm_turn``（唯一调用方）经
``agent_runtime.RuntimeRequest.extra_system`` 通道注入——**永不拼
get_system_prompt 本体**（AD-1 prompt 指纹门，Q2 裁决红线）。

组装链（全确定性、零 LLM、零网络；四源逐源 best-effort #105）：
  ① rationale  recall_for(task, top_k=3)          优先级 1（防错经验前置）
  ② pitfall    pitfall_search(关键词, limit=3)    优先级 2（坑条短且防错价值高）
  ③ rag        query_corpus(task, top_k=3, 只索引 docs/) 优先级 3（v1 不索引
     runs 语料：runs 随战役演化，注入稳定性差）
  ④ knowledge  search_knowledge(task, limit=2)    优先级 4（rules/anchors/
     playbook/fab 静态知识库）

预算（Q4 单账本，常量进模块；configs/settings.yaml agent.knowledge_injection
.budgets 可覆盖）：单条 snippet ≤200 / 单源节 ≤600 / 知识节 ≤1500 /
few-shot 段 ≤900 / extra_system 总 ≤2400。超预算按（归一命中分, 源优先级）
截断，**截断单位=整条**（不产半行残句）。

红线（铁律 7）：注入的是文本上下文非数值——渲染模板零数字拼接、snippet
只截断不加工；坑条 lesson 里的约束性数值教训（如"NEAR≤缝/3"）属约束知识
允许；本模块永不合成新数值建议。

会话注入开关：configs/settings.yaml ``agent.knowledge_injection.enabled``
（tracked 可测；不进 gitignored 的 chat_settings.yaml）。缺省 false 落码
（#329 缺省路径字节不变纪律）；判分门（agentbench 回归，mock transport #139）
过后由主代理同批翻 true（两步预声明）。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 注入契约版本（会话档 meta.injections.schema 同源）。
KNOWLEDGE_INJECTION_SCHEMA = "rfauto-knowledge-injection-v1"

# ─── 预算账本（Q4 单账本；单位 chars）───────────────────────────────────────
SNIPPET_MAX = 200        #: 单条 snippet 上限（沿 rag/knowledge snippet 先例）
SOURCE_SECTION_MAX = 600  #: 单源节上限
SECTION_MAX = 1500        #: 知识注入 section 总上限
FEW_SHOT_MAX = 900        #: few-shot 段上限（AD-3 同账本）
EXTRA_SYSTEM_MAX = 2400   #: extra_system 总上限（few-shot+knowledge）

#: 源优先级（SK §2.1-1：rationale>pitfall>rag>knowledge，deepdive 原文
#: "rationale>anchors>rag" 已勘误——anchors 现属 knowledge_service scope）。
SOURCE_PRIORITY: tuple[str, ...] = ("rationale", "pitfall", "rag", "knowledge")

#: 逐源命中条数上限（task→源并行 top-k 口径）。
SOURCE_HIT_LIMIT: dict[str, int] = {
    "rationale": 3, "pitfall": 3, "rag": 3, "knowledge": 2}

#: 配置缺省路径（锚仓库根，cwd 无关——#295 同族）。
SETTINGS_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "settings.yaml")

#: rag docs 语料缺省目录（v1 只索引 docs/；runs 语料留 v2）。
DOCS_DIR = Path(__file__).resolve().parents[3] / "docs"

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)

# 后验扫描器（护栏③）：数值/路径断言提取（宽松口径，v1 只标注不拦截）。
_CLAIM_NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:GHz|MHz|kHz|Hz|mm|cm|um|µm|nm|dB|dBc|dBm|ns|us|µs"
    r"|ms|°C|ohm|Ω|nH|uH|µH|pH|pF|nF|uF|µF|ppm|pp|W|mW|GiB|MiB)")
_CLAIM_PATH_RE = re.compile(
    r"[\w./\\\-]+\.(?:yaml|yml|json|md|py|csv|txt|s1p|s2p|s3p|s4p"
    r"|kicad_pcb|ffs)")
_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """断言对拍归一（压空白；数值/路径字面子串判定用）。"""
    return _WS_RE.sub("", str(text or ""))


def injection_key(task_text: str) -> str:
    """当轮任务词集 → 会话级 memo 键（词集 hash；同词集复用缓存注入节）。"""
    words = sorted(set(_TOKEN_RE.findall(str(task_text or "").lower())))
    return hashlib.sha1(" ".join(words).encode("utf-8")).hexdigest()


def knowledge_injection_settings(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """读 configs/settings.yaml ``agent.knowledge_injection``（永不抛）。

    返回 {"enabled": bool, "budgets": dict}；文件/节缺失 → enabled=False
    （缺省关=零行为变化，#329 纪律）；budgets 只收数值键（非法键忽略）。
    """
    import yaml

    target = Path(path) if path is not None else SETTINGS_PATH
    out: dict[str, Any] = {"enabled": False, "budgets": {}}
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:  # 配置缺失/畸形 → 缺省关（#105：开关面不阻塞主链路）
        return out
    try:
        section = ((data.get("agent") or {}).get("knowledge_injection") or {})
    except AttributeError:
        return out
    if not isinstance(section, dict):
        return out
    out["enabled"] = bool(section.get("enabled", False))
    budgets = section.get("budgets")
    if isinstance(budgets, dict):
        out["budgets"] = {
            str(k): v for k, v in budgets.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return out


def clamp_few_shot_section(section: str,
                           max_chars: int = FEW_SHOT_MAX) -> tuple[str, int]:
    """few-shot 段整块截断到预算内（Q4 单账本；返回 (section, 丢弃块数)）。

    截断单位=整条案例块（"### 案例" 起）；标题行与收尾固定句保留——不产
    半块残句。超预算且首块即溢出时返回仅标题+收尾句（块全弃，如实截断）。
    """
    text = str(section or "")
    if len(text) <= max_chars:
        return text, 0
    lines = text.splitlines()
    head_idx = next((i for i, ln in enumerate(lines)
                     if ln.startswith("## ")), 0)
    tail_idx = next((i for i in range(len(lines) - 1, -1, -1)
                     if lines[i].startswith("（案例只演示")), len(lines) - 1)
    head, tail = lines[head_idx], lines[tail_idx]
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for i, ln in enumerate(lines):
        if i <= head_idx or i >= tail_idx:
            continue
        if ln.startswith("### 案例"):
            if cur is not None:
                blocks.append(cur)
            cur = [ln]
        elif cur is not None:
            cur.append(ln)
    if cur is not None:
        blocks.append(cur)
    kept: list[list[str]] = []
    used = len(head) + len(tail) + 4  # 标题/收尾行+换行余量
    for block in blocks:
        cost = sum(len(ln) + 1 for ln in block)
        if used + cost > max_chars:
            break
        kept.append(block)
        used += cost
    dropped = len(blocks) - len(kept)
    parts = [head, ""]
    for block in kept:
        parts.extend(block)
    parts += ["", tail]
    return "\n".join(parts) + "\n", dropped


# ─── 逐源检索（模块级函数=测试 mock 点，#139 钉不真打外部）────────────────

def _fetch_rationale(task_text: str, limit: int) -> list[dict[str, Any]]:
    """源 B rationale：recall_for 命中 → 注入条目（require_offline_audit 透传）。"""
    from rfauto.service.rationale_memory import recall_for

    result = recall_for(task_text, top_k=limit)
    if not result.get("ok"):
        raise RuntimeError("; ".join(result.get("errors") or ["recall 失败"]))
    entries: list[dict[str, Any]] = []
    for rank, hit in enumerate(result.get("hits") or []):
        snippet = "；".join(
            part for part in (str(hit.get("conclusion") or ""),
                              str(hit.get("action") or "")) if part)
        entries.append({
            "id": str(hit.get("lesson_id") or ""),
            "source": "rationale",
            "title": "历史经验",
            "score": 1.0 / (rank + 1),
            "snippet": snippet,
            "offline_audit": bool(hit.get("requires_offline_audit")),
        })
    return entries


def _fetch_pitfall(task_text: str, limit: int) -> list[dict[str, Any]]:
    """源 A 坑账：任务关键词 → pitfall_search 命中（title+lesson 单行）。"""
    from rfauto.service.pitfall_index_service import load_pitfall_index, pitfall_search

    keywords = list(dict.fromkeys(
        w for w in _TOKEN_RE.findall(str(task_text or "").lower()) if w))[:6]
    index = load_pitfall_index()
    if not index.get("ok"):
        raise RuntimeError("; ".join(index.get("errors") or ["索引不可用"]))
    result = pitfall_search(index, keywords or [task_text], limit=limit)
    if not result.get("ok"):
        raise RuntimeError("; ".join(result.get("errors") or ["检索失败"]))
    entries: list[dict[str, Any]] = []
    for rank, entry in enumerate(result.get("entries") or []):
        entries.append({
            "id": str(entry.get("id") or ""),
            "source": "pitfall",
            "title": str(entry.get("title") or ""),
            "score": 1.0 / (rank + 1),
            "snippet": str(entry.get("lesson_one_line") or ""),
        })
    return entries


def _fetch_rag(task_text: str, limit: int,
               docs_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """源 C RAG：docs/ 语料 BM25 命中（citation 可溯；索引进程级 memo）。"""
    from rfauto.service.rag_service import query

    index = _memo_rag_index(docs_dir)
    if index is None:
        index, _errors = _build_rag_index(docs_dir)
        if index is None:
            raise RuntimeError("; ".join(_errors or ["语料索引构建失败"]))
    result = query(index, task_text, limit)
    if not result.get("ok"):
        raise RuntimeError("; ".join(result.get("errors") or ["检索失败"]))
    entries: list[dict[str, Any]] = []
    for rank, hit in enumerate(result.get("hits") or []):
        citation = hit.get("citation") or {}
        entries.append({
            "id": str(hit.get("chunk_id") or ""),
            "source": "rag",
            "title": str(citation.get("title")
                         or Path(str(citation.get("path") or "")).name),
            "score": 1.0 / (rank + 1),
            "snippet": str(hit.get("snippet") or ""),
            "path": str(citation.get("path") or "") or None,
        })
    return entries


def _fetch_knowledge(task_text: str, limit: int) -> list[dict[str, Any]]:
    """源 D 知识库：rules/anchors/playbook/fab 子串命中。"""
    from rfauto.service.knowledge_service import search_knowledge

    result = search_knowledge(task_text, limit=limit)
    if not result.get("ok"):
        raise RuntimeError("; ".join(result.get("errors") or ["检索失败"]))
    entries: list[dict[str, Any]] = []
    for rank, hit in enumerate(result.get("hits") or []):
        entries.append({
            "id": str(hit.get("name") or ""),
            "source": "knowledge",
            "title": str(hit.get("source") or ""),
            "score": 1.0 / (rank + 1),
            "snippet": str(hit.get("snippet") or ""),
            "path": str(hit.get("path") or "") or None,
        })
    return entries


# rag 索引进程级 memo（docs/ 全量建索引秒级~十秒级；同语料状态结果一致，
# memo 只消重复构建成本不改判定——确定性口径见模块头"组装链"）。
_RAG_INDEX_CACHE: dict[str, tuple[Any, list[str]]] = {}


def _rag_docs_dir(docs_dir: str | Path | None) -> Path:
    return Path(docs_dir) if docs_dir is not None else DOCS_DIR


def _build_rag_index(
    docs_dir: str | Path | None,
) -> tuple[Any | None, list[str]]:
    from rfauto.service.rag_service import _safe_build_corpus_index

    index, errors = _safe_build_corpus_index(
        docs_dir=_rag_docs_dir(docs_dir), runs_dir=None,  # v1 只索引 docs/
        base_dir=None, runs_limit=None)
    if index is not None:
        _RAG_INDEX_CACHE[str(_rag_docs_dir(docs_dir))] = (index, [])
    return index, list(errors or [])


def _memo_rag_index(docs_dir: str | Path | None) -> Any | None:
    cached = _RAG_INDEX_CACHE.get(str(_rag_docs_dir(docs_dir)))
    return cached[0] if cached else None


def clear_rag_index_cache() -> None:
    """清空 rag 索引 memo（测试隔离口；生产链路无需调用）。"""
    _RAG_INDEX_CACHE.clear()


# ─── 组装器（Q1b：唯一跨源融合点）─────────────────────────────────────────

def compose_knowledge_injection(
    task_text: str,
    *,
    budgets: dict[str, Any] | None = None,
    docs_dir: str | Path | None = None,
) -> dict[str, Any]:
    """任务文本 → 四源融合注入节（纯函数语义；永不抛，逐源 best-effort）。

    返回 {ok, schema_version, section, entries, usage, errors}：
      - section：渲染好的注入文本（空命中=""，调用方零注入）；
      - entries：[{{k, id, source, title, path?, score, snippet}}]——k 为
        节内稳定序号，id 可反查四源（#坑号 / lesson_id / chunk_id / name）；
      - usage：{{per_source: {{source: {{n, chars}}}}, chars, truncated,
        truncated_blocks}}；
      - errors：逐源 best-effort 留痕（部分源失败不阻塞其余，#105）。
    预算超限按（归一命中分 desc, 源优先级, 源内秩）整条截断。
    """
    b = {"snippet": SNIPPET_MAX, "source_section": SOURCE_SECTION_MAX,
         "section": SECTION_MAX, "few_shot": FEW_SHOT_MAX,
         "extra_system": EXTRA_SYSTEM_MAX}
    for key, val in (budgets or {}).items():
        if key in b and isinstance(val, (int, float)) and not isinstance(val, bool):
            b[key] = val

    task_text = str(task_text or "").strip()
    if not task_text:
        return error_envelope(
            ["task_text 为空（剥空白后须非空）"],
            schema_version=KNOWLEDGE_INJECTION_SCHEMA, section="",
            entries=[], usage=_usage({}, 0, 0, 0))

    fetchers = (("rationale", lambda: _fetch_rationale(task_text,
                                                       SOURCE_HIT_LIMIT["rationale"])),
                ("pitfall", lambda: _fetch_pitfall(task_text,
                                                   SOURCE_HIT_LIMIT["pitfall"])),
                ("rag", lambda: _fetch_rag(task_text,
                                           SOURCE_HIT_LIMIT["rag"], docs_dir)),
                ("knowledge", lambda: _fetch_knowledge(
                    task_text, SOURCE_HIT_LIMIT["knowledge"])))
    errors: list[str] = []
    per_source: dict[str, list[dict[str, Any]]] = {}
    clamped_dropped = 0
    for source, fetch in fetchers:
        try:
            entries = fetch()
        except Exception as exc:  # 逐源 best-effort（#105）：该源 0 条+留痕
            errors.append(f"{source}: {type(exc).__name__}: {exc}")
            per_source[source] = []
            continue
        kept, dropped = _clamp_source_entries(
            entries, snippet_max=int(b["snippet"]),
            source_max=int(b["source_section"]))
        per_source[source] = kept
        clamped_dropped += dropped

    # 全局候选排序：归一命中分 desc → 源优先级 → 源内秩（确定性全序）。
    candidates: list[tuple[tuple[float, int, int], dict[str, Any]]] = []
    for source in SOURCE_PRIORITY:
        for rank, entry in enumerate(per_source.get(source) or []):
            key = (-float(entry.get("score") or 0.0),
                   SOURCE_PRIORITY.index(source), rank)
            candidates.append((key, entry))
    candidates.sort(key=lambda item: item[0])

    header = "【参考资料·仅供上下文（引用结论须标 [kN]）】"
    footer = ("以上仅供上下文；结论引用须标注 [kN]；"
              "数值以工具实测返回为准（铁律 7）")
    selected: list[dict[str, Any]] = []
    used = len(header) + len(footer) + 2
    truncated = clamped_dropped  # 单源预算裁掉的整条也计入截断账
    for _key, entry in candidates:
        line = _render_entry(entry)
        cost = len(line) + 1
        if used + cost > int(b["section"]):
            truncated += 1
            continue
        selected.append(entry)
        used += cost

    # k=节内稳定序号：按源优先级组内原秩渲染（阅读稳定，与选择序解耦）。
    ordered: list[dict[str, Any]] = []
    for source in SOURCE_PRIORITY:
        ordered.extend(e for e in selected if e["source"] == source)
    lines = [header]
    usage_per_source: dict[str, dict[str, int]] = {}
    for k, entry in enumerate(ordered, 1):
        entry["k"] = k
        lines.append(_render_entry(entry, k=k))
        stat = usage_per_source.setdefault(entry["source"], {"n": 0, "chars": 0})
        stat["n"] += 1
        stat["chars"] += len(lines[-1]) + 1
    section = "\n".join([*lines, footer]) if ordered else ""

    return ok_envelope(
        schema_version=KNOWLEDGE_INJECTION_SCHEMA,
        section=section,
        entries=[_public_entry(e) for e in ordered],
        # truncated_blocks=few-shot 块截断计数，由调用方（_llm_turn 组装点）
        # 经会话档 usage 合并——本函数只管知识节自身的整条截断。
        usage=_usage(usage_per_source, len(section), truncated, 0),
        errors=errors,
    )


def _render_entry(entry: dict[str, Any], k: int | None = None) -> str:
    """条目 → 单行渲染（确定性拼接；snippet 只截断不加工，铁律 7）。"""
    prefix = f"[k{k}] " if k is not None else ""
    title = str(entry.get("title") or "")
    head = " ".join(part for part in (str(entry.get("id") or ""), title) if part)
    body = f"{head}：{entry.get('snippet')}" if head else str(entry.get("snippet"))
    suffix = f"（源 {entry.get('source')}）"
    return f"{prefix}{body}{suffix}"


def _clamp_source_entries(entries: list[dict[str, Any]], *,
                          snippet_max: int,
                          source_max: int) -> tuple[list[dict[str, Any]], int]:
    """单源预算收紧：snippet 截断（…收尾）+ 单源整条截断（保秩序前缀）。

    返回 (存活条目, 整条截断数)——截断数由调用方并入 usage.truncated。
    """
    clamped: list[dict[str, Any]] = []
    used = 0
    for entry in entries:
        snippet = str(entry.get("snippet") or "")
        if len(snippet) > snippet_max:
            snippet = snippet[: max(0, snippet_max - 1)] + "…"
        entry = dict(entry)
        entry["snippet"] = snippet
        cost = len(_render_entry(entry)) + 1
        if used + cost > source_max:
            break  # 整条截断：保秩序前缀，不产半行残句
        clamped.append(entry)
        used += cost
    return clamped, len(entries) - len(clamped)


def _public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "k": entry.get("k"), "id": entry.get("id"),
        "source": entry.get("source"), "title": entry.get("title"),
        "score": entry.get("score"), "snippet": entry.get("snippet")}
    if entry.get("path"):
        out["path"] = entry["path"]
    if entry.get("offline_audit"):
        out["offline_audit"] = True
    return out


def _usage(per_source: dict[str, dict[str, int]], chars: int,
           truncated: int, truncated_blocks: int) -> dict[str, Any]:
    return {"per_source": per_source, "chars": int(chars),
            "truncated": int(truncated),
            "truncated_blocks": int(truncated_blocks)}


# ─── 防幻觉后验扫描器（护栏③；v1 只标注不拦截不重写）──────────────────────

def scan_ungrounded_claims(
    reply_text: str,
    grounded_texts: list[str] | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """回复中的数值/路径断言后验标注（确定性；deepdive 三件套护栏③）。

    断言既不在工具结果文本（grounded_texts）也不在注入条目 snippet 中
    → 标 ungrounded。v1 只标注：调用方写 session doc
    meta.ungrounded_claims / stats 计数，不拦截不重写回复。
    """
    reply = str(reply_text or "")
    corpus = [_norm(t) for t in (grounded_texts or [])]
    corpus += [_norm(e.get("snippet")) for e in (entries or [])]
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, pattern in (("number", _CLAIM_NUMBER_RE),
                          ("path", _CLAIM_PATH_RE)):
        for match in pattern.findall(reply):
            claim = _norm(match)
            if not claim or claim in seen:
                continue
            seen.add(claim)
            if not any(claim in text for text in corpus if text):
                claims.append({"claim": claim, "kind": kind})
    return ok_envelope(n=len(claims), claims=claims)
