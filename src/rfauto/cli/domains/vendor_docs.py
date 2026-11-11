"""vendor-docs 子应用——厂商帮助文档检索 CLI 薄壳（T-Q19 批 2 接线席
Q-W9-3，aurora_q 方向 E）。

零逻辑转发 service/vendor_doc_service（Q-W6-4 批 1 单源；规则 4 薄壳；
铁律 7 不涉——检索/审计全在 service 层）：
  rfauto vendor-docs build --root ansys_help=<语料根> --db <库路径> [--rebuild]
  rfauto vendor-docs search <query> --db <库路径> [--limit N]
  rfauto vendor-docs audit --db <库路径>

--db 三叶全部必填（缺省 None 拒写拒读——#144 同族纪律：服务层不做 cwd
相对缺省落盘，CLI 不造缺省库位）；语料根全部 --root source=路径 注入，
configs 不动。红线=厂商内容零入库（库内仅 ≤chunk_chars 摘要块与元数据，
audit 叶复核）。

注册=域内自注册（dag/loop/anim 同款：模块级 add_typer，main.py 只
re-export，二次 add_typer 会双注册打红 zero-shadow 钉）；顶层无同名
`vendor-docs` 域（#df6① 冲突检查 2026-11-06：全 CLI 树零撞名，唯一近名
db 域语义=注册表数据库非厂商语料）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

vendor_docs_app = typer.Typer(
    help="厂商帮助文档检索（FTS5 索引+带引用检索+零入库审计）")
app.add_typer(vendor_docs_app, name="vendor-docs")

_DB_HELP = "索引库 SQLite 路径（必填——不落缺省库位，#144 同族纪律）"


def _parse_roots(
    pairs: list[str] | None, *, json_output: bool
) -> dict[str, str]:
    """--root source=路径（可多次）→ {source: 路径}；格式错走 usage 信封。"""
    roots: dict[str, str] = {}
    for item in pairs or []:
        source, sep, root = item.partition("=")
        if not sep or not source.strip() or not root.strip():
            _emit_usage_error(
                f"--root 格式应为 source=语料根目录：{item}",
                json_output=json_output)
        roots[source.strip()] = root.strip()
    return roots


@vendor_docs_app.command("build")
def vendor_docs_build_cmd(
    # list[str] 注解触发 B008（str 不触）——仓内 bands_uq/agent_kicad 同款 noqa 先例
    root: list[str] = typer.Option(  # noqa: B008
        None, "--root",
        help="source=语料根目录（可多次；source 约定 ansys_help/ads_doc）"),
    db: str | None = typer.Option(None, "--db", help=_DB_HELP),
    chunk_chars: int = typer.Option(
        1200, "--chunk-chars", help="单摘要块字符上限（红线：库内无超限全文块）"),
    max_docs: int | None = typer.Option(
        None, "--max-docs", help="最多处理文件数（冒烟限幅；缺省=全部）"),
    rebuild: bool = typer.Option(
        False, "--rebuild", help="先 DROP 旧表全量重建（否则增量+sha256 去重）"),
    pdf_max_pages: int | None = typer.Option(
        None, "--pdf-max-pages", help="单 PDF 最多抽取页数（缺省=不限）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """构建厂商文档 FTS5 索引（增量 sha256 去重；rebuild 全量重建）。"""
    from rfauto.service.vendor_doc_service import build_vendor_index  # lazy: 叶内延迟导入（Q-W9-3 vendor-docs 批）

    if db is None:
        _emit_usage_error("db_path 必填（--db 显式给定索引库位置，"
                          "不落缺省库位）", json_output=json_output)
    roots = _parse_roots(root, json_output=json_output)
    if not roots:
        _emit_usage_error("roots 必填（至少一个 --root source=语料根目录）",
                          json_output=json_output)
    result = build_vendor_index(
        roots, db_path=db, chunk_chars=chunk_chars, max_docs=max_docs,
        rebuild=rebuild, pdf_max_pages=pdf_max_pages)
    _emit(result, "厂商索引构建失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ 索引就绪[/green] files={result.get('indexed_files')}"
        f"  chunks_new={result.get('chunks_new')}"
        f"  total={result.get('total_chunks')}"
        f"  dedup_skip={result.get('dedup_skipped')}"
        f"  skipped={result.get('skipped_files')}")
    console.print(f"  db: {result.get('db_path')}")
    errors = result.get("errors") or []
    if errors:
        console.print(f"  [yellow]errors({len(errors)}):[/yellow]")
        for err in errors[:5]:
            console.print(f"    - {err}")


@vendor_docs_app.command("search")
def vendor_docs_search_cmd(
    query: str = typer.Argument(..., help="检索词（多词空白分隔=AND 短语）"),
    db: str | None = typer.Option(None, "--db", help=_DB_HELP),
    limit: int = typer.Option(10, "--limit", help="返回命中数上限"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """带引用检索（FTS5 trigram MATCH→短词 LIKE 回退；引用含 source/
    title/path/page）。"""
    from rfauto.service.vendor_doc_service import search_vendor_docs  # lazy: 叶内延迟导入（Q-W9-3 vendor-docs 批）

    if db is None:
        _emit_usage_error("db_path 必填（--db 显式给定索引库位置）",
                          json_output=json_output)
    result = search_vendor_docs(query, db_path=db, limit=limit)
    _emit(result, "厂商文档检索失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ {result.get('total')} 命中[/green]"
        f"（mode={result.get('mode')}  limit={result.get('limit')}）")
    for hit in (result.get("hits") or [])[:limit]:
        page = f"  p.{hit['page']}" if hit.get("page") is not None else ""
        console.print(f"  [{hit.get('source')}] {hit.get('title')}{page}")
        console.print(f"    {hit.get('path')}")
        console.print(f"    {hit.get('snippet')}")


@vendor_docs_app.command("audit")
def vendor_docs_audit_cmd(
    db: str | None = typer.Option(None, "--db", help=_DB_HELP),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """索引库零入库审计（记录数/chunk 字符总量/来源清单——红线复核面）。"""
    from rfauto.service.vendor_doc_service import zero_ingest_audit  # lazy: 叶内延迟导入（Q-W9-3 vendor-docs 批）

    if db is None:
        _emit_usage_error("db_path 必填（--db 显式给定索引库位置）",
                          json_output=json_output)
    result = zero_ingest_audit(db_path=db)
    _emit(result, "厂商索引审计失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ 审计完成[/green] files={result.get('n_files')}"
        f"  chunks={result.get('n_chunks')}"
        f"  total_chars={result.get('total_chunk_chars')}"
        f"  max_chunk={result.get('max_chunk_chars')}")
    console.print(f"  within_chunk_limit={result.get('within_chunk_limit')}")
    console.print(f"  {result.get('note')}")
