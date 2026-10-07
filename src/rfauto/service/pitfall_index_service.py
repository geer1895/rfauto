"""pitfall_index_service —— 坑账结构化索引只读 loader（ge8e X6 批，KD-坑账 v1）。

定位（宏图弱点#3「坑账 300+ 纯文本」的最小闭环）：坑号体系（#89…#372+）
此前只以纯文本散落在 项目规则 踩坑速查与 正文，机器不可检索。本模块
对 knowledge/pitfalls_index.json（结构化子集：id/title/category/lesson_one_line/
source 行段）做**只读**加载+校验+确定性检索——零写入、零改写既有账本（新增
索引文件允许，既有文件零改写）。

消费挂点（FU-16 清偿，2026-10-05：premortem 已接线——
service/premortem_service.py:37 惰性导入本模块 pitfall_notes_for 做
报告尾注记，best-effort 零阻塞；逐坑消费指针面=
knowledge/pitfall_consumption.yaml，由 W5-E B12 SLA 门驻守）：
- service/premortem_service.premortem_report / campaign_premortem_block：
  报告尾部附带 pitfall_notes_for(task 关键词) 的 top 命中（best-effort #105，
  索引缺失时返回空列表不阻塞）——本模块已备好 pitfall_notes_for 单调用面；
- KD-4 失败库注入（core/premortem FAILURE_MODE_LIBRARY 同窗）可复用同函数。

设计约束（确定性内核，铁律 7；#122 如实）：
- 纯函数、零网络、零 LLM；同输入两次输出逐字节一致（canonical JSON）；
- 索引文件缺失/畸形 → ok=False+errors 显式报，不静默回退空账（#316 同方向：
  坏账如实报，不假装无坑）；
- 校验器（validate_pitfall_index）钉 schema：必填键/类型/行段整数/id 唯一
  /category 词表（词表为信息性——未知 category 报 warnings 不拒收，避免
  新增条目被词表锁死）。

用法::

    from rfauto.service.pitfall_index_service import (
        load_pitfall_index, pitfall_by_id, pitfall_by_category,
        pitfall_search, pitfall_notes_for)

    idx = load_pitfall_index()                # {ok, schema_version, entries, ...}
    hit = pitfall_by_id(idx, "#122")          # 如实 FAIL/PARTIAL 不凑绿
    notes = pitfall_notes_for(idx, ["PowerShell", "编码"])   # 供 premortem 注入
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 坑账索引契约版本（与 knowledge/pitfalls_index.json 的 schema_version 对应）。
PITFALL_INDEX_SCHEMA = "rfauto-pitfalls-index-v1"

#: 缺省索引路径（与 knowledge_service._KNOWLEDGE_DIR 同源口径：parents[3]）。
DEFAULT_PITFALL_INDEX_PATH = (
    Path(__file__).resolve().parents[3] / "knowledge" / "pitfalls_index.json"
)

#: 条目必填键（schema 钉）。
REQUIRED_ENTRY_KEYS = ("id", "title", "category", "lesson_one_line", "source")

#: 条目 source 子对象必填键。
REQUIRED_SOURCE_KEYS = ("file", "line_start", "line_end")

_LINE_ANCHOR_RE = re.compile(r"^A\d+$")


# ---------------------------------------------------------------------------
# 校验（结构往返钉的裁判面）
# ---------------------------------------------------------------------------

def validate_pitfall_index(data: Any) -> tuple[list[str], list[str]]:
    """校验索引结构，返回 (errors, warnings)。

    errors 非空 = 结构性损坏（loader 拒载）；warnings = 信息性偏差
    （未知 category 等，如实透出不拒收）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["索引顶层必须是 dict"], warnings
    if data.get("schema_version") != PITFALL_INDEX_SCHEMA:
        errors.append(
            f"schema_version 必须是 {PITFALL_INDEX_SCHEMA}，"
            f"实际 {data.get('schema_version')!r}")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries 必须是非空 list")
        return errors, warnings
    vocab = data.get("category_vocab")
    vocab_set = set(vocab) if isinstance(vocab, list) else None
    seen: set[str] = set()
    for pos, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{pos}] 必须是 dict")
            continue
        for key in REQUIRED_ENTRY_KEYS:
            if key not in entry:
                errors.append(f"entries[{pos}] 缺必填键 {key!r}")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not (
                entry_id.startswith("#") or _LINE_ANCHOR_RE.match(entry_id)):
            errors.append(
                f"entries[{pos}] id 必须是 '#N' 坑号或 'A<行号>' 行锚，"
                f"实际 {entry_id!r}")
        elif entry_id in seen:
            errors.append(f"entries[{pos}] id 重复: {entry_id}")
        else:
            seen.add(entry_id)
        for key in ("title", "category", "lesson_one_line"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"entries[{pos}] {key} 必须是非空 str")
        if (vocab_set is not None and isinstance(entry.get("category"), str)
                and entry["category"] not in vocab_set):
            warnings.append(
                f"entries[{pos}] category {entry['category']!r} 不在词表")
        source = entry.get("source")
        if not isinstance(source, dict):
            errors.append(f"entries[{pos}] source 必须是 dict")
        else:
            for key in REQUIRED_SOURCE_KEYS:
                if key not in source:
                    errors.append(f"entries[{pos}] source 缺必填键 {key!r}")
            for key in ("line_start", "line_end"):
                value = source.get(key)
                if (isinstance(value, bool) or not isinstance(value, int)
                        or value < 1):
                    errors.append(
                        f"entries[{pos}] source.{key} 必须是 >=1 的 int")
            if (isinstance(source.get("line_start"), int)
                    and isinstance(source.get("line_end"), int)
                    and source["line_start"] > source["line_end"]):
                errors.append(
                    f"entries[{pos}] source 行段起 {source['line_start']}"
                    f">止 {source['line_end']}")
    return errors, warnings


# ---------------------------------------------------------------------------
# 只读 loader 与确定性检索
# ---------------------------------------------------------------------------

def load_pitfall_index(path: str | Path | None = None) -> dict[str, Any]:
    """加载坑账索引（只读；缺文件/畸形 → ok=False+errors，不静默回退）。"""
    target = Path(path) if path is not None else DEFAULT_PITFALL_INDEX_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        return error_envelope([f"坑账索引读取失败: {exc}"], path=str(target))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return error_envelope(
            [f"坑账索引 JSON 解析失败: {exc}"], path=str(target))
    errors, warnings = validate_pitfall_index(data)
    if errors:
        return error_envelope(errors, path=str(target))
    entries = data["entries"]
    categories: dict[str, int] = {}
    for entry in entries:
        categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    return ok_envelope(
        schema_version=data["schema_version"],
        path=str(target),
        n_entries=len(entries),
        categories=dict(sorted(categories.items())),
        warnings=warnings,
        entries=entries,
    )


def _require_loaded(index: dict[str, Any]) -> list[str] | None:
    if not index.get("ok"):
        return index.get("errors") or ["索引未加载（ok=False）"]
    return None


def pitfall_by_id(index: dict[str, Any], pitfall_id: str) -> dict[str, Any]:
    """按 id 精确查坑（'#122' / 'A104'）；未命中 → ok=False+errors 不抛穿。"""
    if err := _require_loaded(index):
        return error_envelope(err)
    if not isinstance(pitfall_id, str) or not pitfall_id:
        return error_envelope(["pitfall_id 必须是非空 str"])
    for entry in index["entries"]:
        if entry["id"] == pitfall_id:
            return ok_envelope(entry=entry)
    return error_envelope([f"坑号未命中: {pitfall_id}"])


def pitfall_by_category(index: dict[str, Any], category: str) -> dict[str, Any]:
    """按 category 过滤（确定性：按索引文件原序）。"""
    if err := _require_loaded(index):
        return error_envelope(err)
    if not isinstance(category, str) or not category:
        return error_envelope(["category 必须是非空 str"])
    hits = [entry for entry in index["entries"]
            if entry["category"] == category]
    return ok_envelope(category=category, n_hits=len(hits), entries=hits)


def pitfall_search(index: dict[str, Any], keywords: Any, *,
                   limit: int = 5) -> dict[str, Any]:
    """关键词子串检索（title/lesson_one_line/category；确定性计分）。

    计分 = 命中关键词数（每词对每条目至多计 1），同分按索引原序——纯词面
    确定性检索，无 BM25/无网络（消费面要语义检索可走 KD-2 rag 语义档）。
    """
    if err := _require_loaded(index):
        return error_envelope(err)
    if isinstance(keywords, str):
        keywords = [keywords]
    if (not isinstance(keywords, (list, tuple))
            or not all(isinstance(k, str) and k.strip() for k in keywords)
            or not keywords):
        return error_envelope(["keywords 必须是非空 str 或非空 str 列表"])
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return error_envelope(["limit 必须是 >=1 的 int"])
    lowered = [k.lower() for k in keywords]
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for pos, entry in enumerate(index["entries"]):
        haystack = " ".join((entry["title"], entry["lesson_one_line"],
                             entry["category"])).lower()
        score = sum(1 for k in lowered if k in haystack)
        if score > 0:
            scored.append((score, pos, entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    hits = [entry for _, _, entry in scored[:limit]]
    return ok_envelope(keywords=list(keywords), n_hits=len(scored),
                       entries=hits)


def pitfall_notes_for(index: dict[str, Any], keywords: Any, *,
                      limit: int = 3) -> list[str]:
    """premortem 注入面备好的单调用面（best-effort #105）。

    任何失败（索引未加载/关键词畸形）返回空列表，绝不抛穿——观测性/增强
    面不得成为主路径故障点。命中渲染为「#id title：lesson」单行串。
    """
    try:
        result = pitfall_search(index, keywords, limit=limit)
        if not result.get("ok"):
            return []
        return [f"{entry['id']} {entry['title']}：{entry['lesson_one_line']}"
                for entry in result["entries"]]
    except Exception:  # best-effort 增强面，宁空不阻塞（#105）
        return []


def dumps_canonical(index: dict[str, Any]) -> str:
    """加载信封的 canonical JSON（往返/逐字节确定性比对用）。"""
    return json.dumps(index, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
