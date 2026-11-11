"""vendor_docs MCP 工具组——厂商帮助文档检索 agent 面（T-Q19 批 2 接线席
Q-W9-3，aurora_q 方向 E）。

零逻辑转发 service/vendor_doc_service（Q-W6-4 批 1 单源；规则 4；CLI
``rfauto vendor-docs build|search|audit`` 同源同名三函数，JSON 信封出）：

- ``vendor_docs_build``：本机厂商语料（PDF/CHM/HTML 三通道）→ 本地
  SQLite FTS5 索引。**mutating**：写 ``db_path`` 指定索引库（增量
  sha256 去重/rebuild 全量重建）；红线=厂商内容零入库（库内仅 ≤
  chunk_chars 摘要块与元数据）；
- ``vendor_docs_search``：带引用检索（FTS5 trigram MATCH→短词 LIKE
  回退），引用含 source/title/path/page；
- ``vendor_docs_audit``：零入库审计（记录数/chunk 字符总量/来源清单，
  复核"摘要块非全文"红线）。

db_path 三个工具全部必填（缺省 None 拒写拒读——#144 同族纪律，服务层
不做 cwd 相对缺省落盘）；语料根路径全部参数注入，configs 不动。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

__all__ = ["vendor_docs_audit", "vendor_docs_build", "vendor_docs_search"]


@mcp.tool
def vendor_docs_build(
    roots: dict[str, str],
    db_path: str,
    chunk_chars: int = 1200,
    max_docs: int | None = None,
    rebuild: bool = False,
    pdf_max_pages: int | None = None,
) -> dict[str, Any]:
    """构建厂商文档 FTS5 索引（mutating：写 db_path 指定索引库）。

    本机厂商语料（PDF=pypdf 逐页/CHM=hh.exe 反编译/HTML=直读去标签）→
    分块 → 本地 SQLite FTS5（trigram）索引；增量 sha256 去重，rebuild
    全量重建。**红线：厂商内容零入库**——库内仅存 ≤chunk_chars 摘要块
    与元数据，全文禁入仓。roots 键=source 名（约定 ansys_help/ads_doc，
    自由名允许）。单文件失败不中断整批（best-effort，错误入 errors）。

    Args:
        roots: {source 名: 语料根目录} 映射（至少一项；根不存在显式报错）。
        db_path: 索引库 SQLite 路径（必填；缺省 None 拒写，不落缺省库位）。
        chunk_chars: 单摘要块字符上限（缺省 1200）。
        max_docs: 最多处理文件数（冒烟限幅；None=全部）。
        rebuild: True=先 DROP 旧表全量重建（否则增量+去重）。
        pdf_max_pages: 单 PDF 最多抽取页数（None=不限）。

    Returns:
        dict: ok=True 时 {indexed_files, dedup_skipped, chunks_new,
        total_chunks, skipped_files, errors, elapsed_s, roots, sources,
        db_path}；ok=False 时 {errors}。
    """
    from rfauto.service.vendor_doc_service import build_vendor_index

    return build_vendor_index(
        dict(roots), db_path=db_path, chunk_chars=chunk_chars,
        max_docs=max_docs, rebuild=rebuild, pdf_max_pages=pdf_max_pages)


@mcp.tool
def vendor_docs_search(
    query: str,
    db_path: str,
    limit: int = 10,
) -> dict[str, Any]:
    """厂商文档带引用检索（只读）：FTS5 trigram MATCH→LIKE 子串回退。

    引用含 source/title/path/page（PDF page=原文页码主通道）；MATCH 语法
    错误自动降级短语重试；<3 字短词/零命中走 LIKE 子串回退，envelope
    mode 字段声明命中通道（fts5/fts5_phrase/like）。

    Args:
        query: 检索词（非空；多词空白分隔=AND 短语）。
        db_path: 索引库 SQLite 路径（必填；库不存在/未构建显式报错）。
        limit: 返回命中数上限（缺省 10）。

    Returns:
        dict: ok=True 时 {query, mode, total, hits, limit}（hits 每项
        {source, title, path, page, snippet, chunk_index, rank}）；
        ok=False 时 {errors}。
    """
    from rfauto.service.vendor_doc_service import search_vendor_docs

    return search_vendor_docs(query, db_path=db_path, limit=limit)


@mcp.tool
def vendor_docs_audit(db_path: str) -> dict[str, Any]:
    """索引库零入库审计（只读）：复核"摘要块非全文"红线。

    报告记录数/chunk 字符总量/最大块字符/逐来源清单；max_chunk_chars ≤
    meta 声明 chunk_chars 即红线成立（库内仅摘要块，全文只在本机厂商
    语料不进库不入仓）。

    Args:
        db_path: 索引库 SQLite 路径（必填；库不存在显式报错）。

    Returns:
        dict: ok=True 时 {n_files, n_chunks, total_chunk_chars,
        max_chunk_chars, by_source, sources, declared_chunk_chars,
        within_chunk_limit, built_at, roots, note}；ok=False 时 {errors}。
    """
    from rfauto.service.vendor_doc_service import zero_ingest_audit

    return zero_ingest_audit(db_path=db_path)
