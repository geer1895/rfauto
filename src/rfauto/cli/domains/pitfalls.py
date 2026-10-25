"""pitfalls 子应用（坑账结构化检索面；aurora_d KB-B 席，2026-10-14）.

只读两叶：search（关键词/域/坑号检索）+ get（按 id 精确查坑）。
索引加载/校验/id 精确查转发 service/pitfall_index_service（只读 loader，
零写入，规则 4）；关键词计分是纯映射（确定性词面检索，铁律 7 对偶：
映射表也是确定性数据）——service/** 在本席禁碰清单内，故该纯函数落
本域模块并由 tests/unit/test_kb_b_pitfall_index.py 直钉。

数据面：knowledge/pitfalls_index_full.json（scripts/pitfall_index.py 从
内核立规注记.md 踩坑速查+runs/ SESSION_PITFALLS 散档机器全量解析，条目数以
构建报告实测为准；漂移重建：
``python scripts/pitfall_index.py``）；--index 可切人工精选 v1
（knowledge/pitfalls_index.json，66 条）——两索引同 schema 契约
（rfauto-pitfalls-index-v1），同一 loader 零改动可加载。

用法::

    rfauto pitfalls search taskkill              # 关键词（空格分词，多词计分）
    rfauto pitfalls search "波端口" --domain hfss
    rfauto pitfalls search --number 245          # 按坑号（连号组已展开）
    rfauto pitfalls get "#89"                    # 按 id 精确查坑
    两叶均带 --json（信封契约与 service 信封同构；Agent 消费面）。
"""

from __future__ import annotations

from typing import Any

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app

pitfalls_app = typer.Typer(help="坑账检索面（结构化索引，只读；数据缺席如实报缺）")
app.add_typer(pitfalls_app, name="pitfalls")

#: 缺省索引（与 knowledge/pitfalls_index.json 同目录的全量机器解析产物；
#: 经 service 缺省常量推导同源目录，不硬编码绝对路径）。
_DEFAULT_INDEX_NAME = "pitfalls_index_full.json"


def _resolve_index_path(index_path: str) -> Any:
    from pathlib import Path

    from rfauto.service.pitfall_index_service import DEFAULT_PITFALL_INDEX_PATH

    if index_path.strip():
        return Path(index_path.strip())
    return DEFAULT_PITFALL_INDEX_PATH.parent / _DEFAULT_INDEX_NAME


def _load_index(index_path: str) -> dict[str, Any]:
    from rfauto.service.pitfall_index_service import load_pitfall_index

    return load_pitfall_index(_resolve_index_path(index_path))


def _parse_number_filter(number: str) -> int | None:
    """--number 形态归一：'#245'/'245' → 245；非法 → None（调用方报用法错）。"""
    raw = number.strip().lstrip("#")
    if not raw.isdigit():
        return None
    return int(raw)


def search_entries(
    entries: list[dict[str, Any]],
    keywords: list[str],
    *,
    domains: list[str] | None = None,
    number: int | None = None,
    limit: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    """确定性词面检索（纯函数；tests 直钉）。

    计分：每词对每条目——命中 title/lesson/category/坑号（头部字段）计 2，
    仅命中全文计 1，零命中不计；总分>0 即候选；同分按索引原序。
    域过滤（category ∈ domains）与坑号过滤（number ∈ numbers）为前置硬滤。
    返回 (top-limit 命中, 候选总数)。
    """
    lowered = [k.lower() for k in keywords if k.strip()]
    domain_set = {d.strip() for d in (domains or []) if d.strip()}
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for pos, entry in enumerate(entries):
        if domain_set and entry.get("category") not in domain_set:
            continue
        if number is not None and number not in (entry.get("numbers") or []):
            continue
        if not lowered:
            # 纯过滤模式（仅 --domain/--number，零关键词）：过滤即命中
            scored.append((1, pos, entry))
            continue
        head = " ".join((
            entry.get("title", ""), entry.get("lesson_one_line", ""),
            entry.get("category", ""),
            " ".join(str(n) for n in (entry.get("numbers") or [])),
        )).lower()
        text = (entry.get("text") or "").lower()
        score = 0
        for kw in lowered:
            if kw in head:
                score += 2
            elif kw in text:
                score += 1
        if score > 0:
            scored.append((score, pos, entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    hits = [entry for _, _, entry in scored[:limit]]
    return hits, len(scored)


@pitfalls_app.command("search")
def pitfalls_search_cmd(
    keywords: list[str] = typer.Argument(  # noqa: B008
        None, help="关键词（空格分词，多词计分排序；可与 --number 组合）"),
    domain: str = typer.Option(
        "", "--domain", help="域标签过滤（逗号分隔，如 hfss,openems；"
        "词表见索引 category_vocab）"),
    number: str = typer.Option(
        "", "--number", help="坑号过滤（#245 或 245 形态；连号组已展开）"),
    limit: int = typer.Option(
        10, "--limit", min=1, help="返回条数上限"),
    index_path: str = typer.Option(
        "", "--index", help="索引 JSON 路径（缺省全量机器解析产物；"
        "可指向人工精选 v1）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """坑账关键词检索（确定性词面计分：头部命中 2 分/全文 1 分）。"""
    if number.strip():
        num = _parse_number_filter(number)
        if num is None:
            _emit_usage_error(
                f"--number 需 #245 或 245 形态，实际 {number!r}",
                json_output=json_output)
            return
    else:
        num = None
    kw_list = [k for k in (keywords or []) if k.strip()]
    if not kw_list and num is None:
        _emit_usage_error(
            "至少给关键词或 --number 之一（如 rfauto pitfalls search taskkill）",
            json_output=json_output)
        return
    idx = _load_index(index_path)
    if not idx.get("ok"):
        _emit(idx, "坑账索引读取失败", json_output=json_output)
        return
    domains = [d for d in domain.split(",") if d.strip()]
    hits, n_candidates = search_entries(
        idx["entries"], kw_list, domains=domains, number=num, limit=limit)
    result = {
        "ok": True,
        "keywords": kw_list,
        "domain": domain,
        "number": number.strip(),
        "limit": limit,
        "n_entries": idx["n_entries"],
        "n_hits": n_candidates,
        "entries": hits,
    }
    _emit(result, "坑账检索失败", json_output=json_output)
    if json_output:
        return
    from rich.table import Table

    from rfauto.cli.domains._core import console

    console.print(
        f"[green]坑账检索：{n_candidates} 条候选"
        f"（显示 top {len(hits)}/{idx['n_entries']}）[/green]")
    table = Table(title="pitfalls search")
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("域", no_wrap=True)
    table.add_column("标题")
    table.add_column("教训一句话")
    table.add_column("出处", no_wrap=True)
    for entry in hits:
        src = entry.get("source") or {}
        table.add_row(
            entry["id"], entry["category"], entry["title"],
            entry["lesson_one_line"][:60],
            f"{src.get('file', '')}:{src.get('line_start', '')}")
    console.print(table)


@pitfalls_app.command("get")
def pitfalls_get_cmd(
    pitfall_id: str = typer.Argument(
        ...,
        help="坑 id（#89 坑号形态或 A<行号> 行锚合成 id，见索引 id_scheme）"),
    index_path: str = typer.Option(
        "", "--index", help="索引 JSON 路径（缺省全量机器解析产物）"),
    json_output: bool = typer.Option(
        False, "--json", "-j", help="JSON 信封输出（供脚本/Agent 消费）"),
) -> None:
    """按 id 精确查坑（未命中 → error 信封退出码 1，不抛穿）。"""
    from rfauto.service.pitfall_index_service import pitfall_by_id

    idx = _load_index(index_path)
    if not idx.get("ok"):
        _emit(idx, "坑账索引读取失败", json_output=json_output)
        return
    result = pitfall_by_id(idx, pitfall_id)
    _emit(result, f"坑号未命中: {pitfall_id}", json_output=json_output)
    if json_output:
        return
    from rfauto.cli.domains._core import console

    entry = result["entry"]
    src = entry.get("source") or {}
    console.print(
        f"[cyan]{entry['id']}[/cyan]（{entry['category']}）"
        f"[bold]{entry['title']}[/bold]  "
        f"{src.get('file', '')}:{src.get('line_start', '')}-"
        f"{src.get('line_end', '')}")
    console.print(f"  {entry['lesson_one_line']}")
    numbers = entry.get("numbers") or []
    if numbers:
        console.print(f"  坑号族：{' '.join('#' + str(n) for n in numbers)}",
                      style="dim")
    cons = entry.get("consumption") or []
    for c in cons:
        console.print(
            f"  消费面：{c.get('surface')} → {c.get('pointer')}", style="dim")
