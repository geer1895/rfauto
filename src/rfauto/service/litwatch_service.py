"""KD-5 文献监控管线（round16 P2，J 流）——arXiv RSS/API→候选账本。

定位（任务书口径）：arXiv 订阅面（RSS/API 同一 Atom 端点）+ 关键词
排序 → **账本候选登记**（JSONL，纯离线可 mock）。双源核实沿 #300：
候选状态恒为 ``candidate``——升格 VERIFIED 必须人工双源核对，本管线
只负责"发现与登记"，不负责"采信"。

#139 铁律合规：**单测钉住网络通道，禁真网**——``fetch_arxiv`` 的
HTTP 面收敛在模块级 ``_http_get`` 单点，测试 monkeypatch 该点注入
canned Atom XML；真实抓取=CLI/script 入口手动触发（
scripts/litwatch_fetch.py 薄壳，本模块零 CLI 依赖）。

设计约束（确定性内核，铁律 7）：
- 排序=确定性关键词命中计（query 关键词 × 标题+摘要子串交集），
  同分按 (published 降序, id 字典序) 全序——无 BM25 库依赖、无随机；
- 账本去重：同 arXiv id 幂等（重复登记跳过并计数）；
- Atom 解析用 stdlib xml.etree（无第三方依赖）；解析失败条目跳过
  并留痕（宁缺毋滥），成功条目数如实透出。

用法::

    from rfauto.service.litwatch_service import (
        watch, render_candidates_markdown)

    r = watch(["pyramidal antenna hologram", "additive manufacturing antenna"],
              ledger_path="runs/litwatch/candidates.jsonl",
              http_get=fake_http_get)   # 测试/离线注入
    r["entries"]      # 去重后的新增候选（关键词命中排序）
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from rfauto.service.envelope import ok_envelope

#: 候选账本契约版本。
LITWATCH_SCHEMA = "rfauto-litwatch-v1"

#: 候选状态（升格 VERIFIED 必须人工双源核实，#300 沿革；本管线不升格）。
STATUS_CANDIDATE = "candidate"

#: arXiv Atom API 端点（RSS 面同一端点；http→https 升级由 urllib 处理）。
ARXIV_API_URL = "https://export.arxiv.org/api/query"

#: 命名空间（Atom）。
_ATOM_NS = "{http://www.w3.org/2005/Atom}"

#: 分词口径（与 rationale_memory._TOKEN 同源：字母数字+CJK 连续段）。
_TOKEN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")

#: 单次查询最大条数（API 惯例上限 100；防误配全库拖取）。
MAX_RESULTS_CAP = 100


def _http_get(url: str, timeout_s: float) -> bytes:
    """网络面单点（#139）：全部 HTTP 收敛在此函数，测试 monkeypatch 它。"""
    req = urllib.request.Request(url, headers={"User-Agent": "rfauto-litwatch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def build_query_url(query: str, *, max_results: int = 20) -> str:
    """关键词 → arXiv API 查询 URL（search_query=all:"..."，确定性）。"""
    n = max(1, min(int(max_results), MAX_RESULTS_CAP))
    q = urllib.parse.quote(f'all:"{query}"')
    return f"{ARXIV_API_URL}?search_query={q}&start=0&max_results={n}"


def parse_atom_feed(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Atom feed → 条目列表（确定性；解析失败条目跳过留痕由调用方计数）。

    每条：{arxiv_id, title, summary, published, updated, authors, url}。
    """
    root = ElementTree.fromstring(xml_bytes)
    entries: list[dict[str, Any]] = []
    for node in root.findall(f"{_ATOM_NS}entry"):
        entry_id = (node.findtext(f"{_ATOM_NS}id") or "").strip()
        if not entry_id:
            continue
        # arxiv id 规范化：http://arxiv.org/abs/2401.12345v2 → 2401.12345v2
        arxiv_id = entry_id.rsplit("/abs/", 1)[-1]
        title = re.sub(r"\s+", " ", (node.findtext(f"{_ATOM_NS}title") or "")).strip()
        summary = re.sub(r"\s+", " ",
                         (node.findtext(f"{_ATOM_NS}summary") or "")).strip()
        authors = [a.findtext(f"{_ATOM_NS}name", default="").strip()
                   for a in node.findall(f"{_ATOM_NS}author")]
        entries.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "published": (node.findtext(f"{_ATOM_NS}published") or "").strip(),
            "updated": (node.findtext(f"{_ATOM_NS}updated") or "").strip(),
            "authors": [a for a in authors if a],
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })
    return entries


def score_entry(entry: Mapping[str, Any], keywords: Sequence[str]) -> int:
    """关键词命中计（确定性）：关键词（规范化子串，小写）在标题+摘要中
    出现的条数。规范化=strip→小写；空关键词不计分。"""
    text = (str(entry.get("title", "")) + " "
            + str(entry.get("summary", ""))).lower()
    hits = 0
    for kw in keywords:
        k = str(kw).strip().lower()
        if k and k in text:
            hits += 1
    return hits


def _load_ledger_ids(ledger_path: Path) -> set[str]:
    """账本既有 arxiv id 集（文件缺失/坏行跳过——账本是低风险登记面）。"""
    seen: set[str] = set()
    if not ledger_path.is_file():
        return seen
    for ln in ledger_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
            if isinstance(rec, dict) and rec.get("arxiv_id"):
                seen.add(str(rec["arxiv_id"]))
        except Exception:
            continue  # 坏行留原样，不中断（#105 best-effort）
    return seen


def watch(queries: Sequence[str], *,
          ledger_path: str | Path,
          max_results_per_query: int = 20,
          min_score: int = 0,
          timeout_s: float = 30.0,
          fetch_fn: Callable[[str], bytes] | None = None,
          http_get: Callable[[str, float], bytes] | None = None,
          now: datetime | None = None) -> dict[str, Any]:
    """订阅→抓取→排序→登记主入口（KD-5）。

    Args:
        queries: 关键词查询表（每条一次 API 调用）。
        ledger_path: 候选账本 JSONL 路径（同 id 幂等去重）。
        max_results_per_query: 每查询条数帽（≤100）。
        min_score: 关键词命中计下限（0=不过滤）。
        timeout_s: HTTP 超时（秒）。
        fetch_fn: 注入的抓取函数（入参 url 出参 bytes）——测试/离线主
            注入口；注入即**零网络**（#139 通道钉死）。
        http_get: 低层注入面（与 fetch_fn 二选一，fetch_fn 优先）。
        now: 时间注入（测试确定性；缺省取当前 UTC）。

    Returns:
        {ok, schema, n_queries, n_fetched, n_new, n_dup, n_parse_error,
         entries: [候选条目（新增，命中排序）], ledger_path}
    """
    if not queries:
        return {"ok": False, "schema": LITWATCH_SCHEMA, "n_queries": 0,
                "n_fetched": 0, "n_new": 0, "n_dup": 0, "n_parse_error": 0,
                "entries": [], "issues": ["queries 为空"]}

    def _get(url: str) -> bytes:
        if fetch_fn is not None:
            return fetch_fn(url)
        if http_get is not None:
            return http_get(url, timeout_s)
        return _http_get(url, timeout_s)

    # 抓取+解析（跨查询按 arxiv id 去重）
    fetched: dict[str, dict[str, Any]] = {}
    dup_in_feed = 0
    parse_errors = 0
    for q in queries:
        try:
            xml_bytes = _get(build_query_url(q, max_results=max_results_per_query))
        except Exception:
            parse_errors += 1
            continue
        try:
            entries = parse_atom_feed(xml_bytes)
        except Exception:
            parse_errors += 1
            continue
        for e in entries:
            if e["arxiv_id"] in fetched:
                dup_in_feed += 1
                continue
            e["matched_query"] = str(q)
            fetched[e["arxiv_id"]] = e
    n_fetched = len(fetched)

    # 关键词排序（确定性全序：(-score, -published, arxiv_id)；published
    # 逆序=新文优先，空 published 排后）
    def _key(e: dict[str, Any]) -> tuple[int, str, str]:
        return (-score_entry(e, queries),
                _neg_iso(str(e.get("published", ""))),
                str(e["arxiv_id"]))

    ranked = sorted(fetched.values(), key=_key)
    if min_score > 0:
        ranked = [e for e in ranked if score_entry(e, queries) >= min_score]

    # 账本登记（幂等去重）
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = _load_ledger_ids(path)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    new_entries: list[dict[str, Any]] = []
    n_dup = 0
    with path.open("a", encoding="utf-8") as fh:
        for e in ranked:
            if e["arxiv_id"] in seen:
                n_dup += 1
                continue
            rec = {
                "schema": LITWATCH_SCHEMA,
                "status": STATUS_CANDIDATE,
                "registered_at": stamp,
                "arxiv_id": e["arxiv_id"],
                "title": e["title"],
                "summary": e["summary"],
                "published": e["published"],
                "authors": e["authors"],
                "url": e["url"],
                "matched_query": e["matched_query"],
                "score": score_entry(e, queries),
                "verify_note": "candidate——升格须人工双源核实（#300）",
            }
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            seen.add(e["arxiv_id"])
            new_entries.append(rec)

    return ok_envelope(schema=LITWATCH_SCHEMA, n_queries=len(queries),
                       n_fetched=n_fetched, n_new=len(new_entries),
                       n_dup=n_dup, n_parse_error=parse_errors,
                       n_dup_in_feed=dup_in_feed,
                       entries=new_entries, ledger_path=str(path))


def _neg_iso(iso: str) -> str:
    """published ISO 串 → 逆序键（新文优先）；空串排最后。"""
    return "".join(chr(0x10FFFF - ord(c)) for c in iso) if iso else ""


def render_candidates_markdown(result: Mapping[str, Any]) -> str:
    """watch 结果 → 确定性 markdown 登记块（候选=待人工双源核实）。"""
    if not result.get("ok"):
        return ""
    entries = list(result.get("entries") or [])
    if not entries:
        return ""
    lines = [f"## 文献监控候选（新增 {len(entries)} 条，状态=candidate）", ""]
    for e in entries:
        lines.append(f"- [ ] **{e['title']}**（arXiv:{e['arxiv_id']}，"
                     f"score={e['score']}，query={e['matched_query']}）")
        lines.append(f"  - {e['url']}｜published={e.get('published', '')}")
        lines.append("  - 升格 VERIFIED 前须双源核实（#300）；本体不入账本。")
    lines.append("")
    return "\n".join(lines)
