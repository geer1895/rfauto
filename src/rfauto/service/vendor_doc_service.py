"""vendor_doc_service：厂商帮助文档 FTS5 检索层（T-Q19 批 1：索引构建）。

本机厂商语料（只读侦察，位置参数注入不写死）→ 文本抽取分块 → 本地
SQLite FTS5 索引 → 带引用（source/path/page）检索。三条抽取通道：

- PDF  ：pypdf（pyproject 已声明依赖，零新增）逐页 extract_text，
  ``page`` 落 PDF 页码（1 起）——引用指向原文页码的主通道；
- CHM  ：``hh.exe -decompile`` 子进程抽 HTML（实测 hh.exe 对含空格
  CHM 路径静默失败且异步写产物——先拷贝到无空白 staging 路径再
  发射，随后轮询产物目录），内页 ``path`` 形如 ``<chm相对路径>!<内页>``；
- HTML ：直读去标签分块（ADS doc 语料主通道）。

**红线：厂商内容零入库**——库内只存 ≤chunk_chars 的摘要块（chunk_text）
与元数据（source/path/title/page/sha256），全文禁入仓；``zero_ingest_audit``
给出记录数/chunk 字符总量/来源清单供复核"摘要块非全文"。索引库落
``db_path`` 调用方给：**缺省 None 一律拒写**（#144 同族纪律——服务层
不做 cwd 相对缺省落盘）。语料根路径全部参数注入，configs 不动。

FTS5 口径（venv sqlite 3.53.1 实测，runs/aurora_q/r7）：external content
虚表（chunk_text 单份存储）+ ``tokenize='trigram'``——unicode61 把连写
CJK 当单 token 实测 0 命中，trigram 支持中文 ≥3 字 MATCH；<3 字短词走
LIKE 子串回退（search 内置，envelope ``mode`` 字段声明所用通道）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import typing
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "SUPPORTED_SUFFIXES",
    "build_vendor_index",
    "search_vendor_docs",
    "zero_ingest_audit",
]

#: 索引 schema 版本（表结构变更时升位）
VENDOR_INDEX_SCHEMA_VERSION = 1

#: 支持抽取的后缀（其余文件跳过并计数）
SUPPORTED_SUFFIXES = {".pdf", ".chm", ".htm", ".html"}

#: trigram MATCH 的最小词元长度（<3 字走 LIKE 回退）
_TRIGRAM_MIN_CHARS = 3

_DB_TABLES_SQL = (
    # 文件台账（sha256 去重决策面；path 在 source 内相对根）
    """CREATE TABLE IF NOT EXISTS vendor_files (
        source TEXT NOT NULL,
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        n_chunks INTEGER NOT NULL,
        title TEXT,
        PRIMARY KEY (source, path)
    )""",
    # 摘要块主表（红线：只存 ≤chunk_chars 块，不存全文）
    """CREATE TABLE IF NOT EXISTS vendor_docs (
        rowid INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        path TEXT NOT NULL,
        title TEXT NOT NULL,
        page INTEGER,
        chunk_index INTEGER NOT NULL,
        chunk_text TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        UNIQUE (source, path, chunk_index)
    )""",
    # FTS5 external content 虚表（索引只此一份，文本在 vendor_docs）
    """CREATE VIRTUAL TABLE IF NOT EXISTS vendor_docs_fts USING fts5(
        chunk_text, content='vendor_docs', content_rowid='rowid',
        tokenize='trigram'
    )""",
    """CREATE TABLE IF NOT EXISTS vendor_index_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
)

class VendorDocError(Exception):
    """单文件抽取失败（best-effort：记入 errors 不中断整批）。"""


# ---------------------------------------------------------------------------
# HTML 清洗与分块
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    """去标签取文本（script/style 剔除，实体解码）。"""

    _SKIP: typing.ClassVar[set[str]] = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title" and not self.title:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if getattr(self, "_in_title", False):
            self.title += data.strip()
            return
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self._parts)


def _decode_bytes(raw: bytes) -> str:
    """HTML 字节解码启发式：utf-8 → meta 声明 charset → cp1252 → latin-1。"""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    head = raw[:2048].decode("ascii", errors="ignore").lower()
    m = re.search(r'charset=["\']?([\w-]+)', head)
    if m:
        try:
            return raw.decode(m.group(1))
        except (UnicodeDecodeError, LookupError):
            pass
    for enc in ("cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:  # pragma: no cover - latin-1 不抛
            continue
    return raw.decode("utf-8", errors="replace")  # pragma: no cover


def _strip_html(raw: bytes) -> tuple[str, str]:
    """HTML → (title, 正文文本)。title 缺省空串由调用方兜底。"""
    parser = _TextExtractor()
    try:
        parser.feed(_decode_bytes(raw))
        parser.close()
    except Exception as exc:  # 畸形 HTML best-effort
        raise VendorDocError(f"HTML 解析失败: {exc}") from exc
    return parser.title, parser.text()


def _split_cjk_run(run: str, limit: int) -> list[str]:
    """长 CJK 连写段按标点优先切分（段内保词不跨块），超限硬切。"""
    pieces: list[str] = []
    sentences = re.split(r"(?<=[。！？；，、])", run)
    buf = ""
    for sent in sentences:
        if len(sent) > limit:  # 单句超限：硬切
            if buf:
                pieces.append(buf)
                buf = ""
            for i in range(0, len(sent), limit):
                pieces.append(sent[i : i + limit])
            continue
        if len(buf) + len(sent) > limit:
            pieces.append(buf)
            buf = sent
        else:
            buf += sent
    if buf:
        pieces.append(buf)
    return pieces


def _chunk_text(text: str, chunk_chars: int) -> list[str]:
    """贪心分块：每块 ≤chunk_chars，词边界优先（CJK 连写段单独处理）。"""
    chunks: list[str] = []
    buf = ""
    for word in text.split():
        if len(word) > chunk_chars:  # CJK 连写长段：标点优先切
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_split_cjk_run(word, chunk_chars))
            continue
        if not buf:
            buf = word
        elif len(buf) + 1 + len(word) <= chunk_chars:
            buf = f"{buf} {word}"
        else:
            chunks.append(buf)
            buf = word
    if buf:
        chunks.append(buf)
    return chunks


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 三条抽取通道
# ---------------------------------------------------------------------------


def _extract_pdf_pages(
    path: Path, *, max_pages: int | None = None
) -> tuple[str, list[tuple[int, str]]]:
    """PDF 通道：pypdf 逐页抽文，返回 (title, [(页码, 文本)])。页码 1 起。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 已声明依赖，防御性
        raise VendorDocError(f"pypdf 不可用: {exc}") from exc
    try:
        reader = PdfReader(str(path))
        n = len(reader.pages)
        if max_pages is not None:
            n = min(n, max_pages)
        pages = [
            (i + 1, (reader.pages[i].extract_text() or "").strip())
            for i in range(n)
        ]
        title = ""
        if reader.metadata is not None:
            title = str(reader.metadata.title or "").strip()
    except VendorDocError:
        raise
    except Exception as exc:  # 损坏 PDF best-effort
        raise VendorDocError(f"PDF 抽取失败: {exc}") from exc
    return title, [(p, t) for p, t in pages if t]


def _find_hh_exe() -> str | None:
    """定位 hh.exe（Windows 帮助查看器，CHM 反编译子进程）。"""
    if sys.platform != "win32":
        return None
    cand = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "hh.exe"
    return str(cand) if cand.exists() else None


def _poll_files(out_dir: Path, *, timeout_s: float, poll_s: float = 0.5) -> list[Path]:
    """轮询反编译产物（hh.exe 异步写：rc=0 即回，产物陆续到）。

    停止条件：文件总数连续两轮（~1s）零增长判写完（Q-W6-4 冒烟实证：
    首个 .htm 落地 ≠ 写完——首版"见文件即收"只拿到 1/72 内页）；超时
    则返回已有产物（best-effort），零产物返回空表由调用方报错。
    """
    deadline = time.monotonic() + timeout_s
    last = -1
    stable = 0
    while time.monotonic() < deadline:
        if out_dir.exists():
            files = [p for p in out_dir.rglob("*") if p.is_file()]
            n = len(files)
            if n and n == last:
                stable += 1
                if stable >= 2:
                    return sorted(
                        p
                        for p in files
                        if p.suffix.lower() in (".htm", ".html")
                    )
            else:
                stable = 0
            last = n
        time.sleep(poll_s)
    if out_dir.exists():  # 超时但已有产物：best-effort 返回
        return sorted(
            p
            for p in out_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in (".htm", ".html")
        )
    return []


def _chm_staging_root() -> Path:
    """选无空白 staging 根（hh.exe 对含空白路径静默失败）。"""
    root = Path(tempfile.mkdtemp(prefix="rfauto_chm_"))
    if any(" " in part for part in root.parts):
        alt = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "Temp"
        alt.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="rfauto_chm_", dir=str(alt)))
        if any(" " in part for part in root.parts):  # pragma: no cover
            raise VendorDocError(
                f"CHM staging 路径含空白（hh.exe 静默失败面）: {root}"
            )
    return root


def _decompile_chm(
    chm_path: Path, out_dir: Path, *, timeout_s: float = 60.0
) -> list[Path]:
    """CHM 通道：hh.exe -decompile 子进程，返回内页 HTML 路径列表。

    实测坑（Q-W6-4 探针）：hh.exe 对含空白字符的路径**静默失败**
    （rc=0 零产物）且发射后异步写产物——CHM 与产物目录都先落到无空白
    staging，轮询到产物后由 Python 拷回调用方 ``out_dir``（可含空白）。
    失败（超时零产物）抛 VendorDocError。
    """
    hh = _find_hh_exe()
    if hh is None:
        raise VendorDocError("hh.exe 不可用（非 Windows 或未安装）")
    staging_root = _chm_staging_root()
    staged = staging_root / f"doc{chm_path.suffix.lower()}"
    decomp_out = staging_root / "out"
    try:
        shutil.copyfile(chm_path, staged)
        proc = subprocess.run(  # 固定 hh.exe + 本机 CHM 语料路径
            [hh, "-decompile", str(decomp_out), str(staged)],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            raise VendorDocError(
                f"hh.exe 反编译失败 rc={proc.returncode}: "
                f"{proc.stderr[:200]!r}"
            )
        files = _poll_files(decomp_out, timeout_s=timeout_s)
        if not files:
            raise VendorDocError("hh.exe 反编译零产物（超时）")
        out_dir.mkdir(parents=True, exist_ok=True)
        result: list[Path] = []
        for f in files:
            dest = out_dir / f.relative_to(decomp_out)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
            result.append(dest)
        return sorted(result)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _index_html_file(path: Path) -> tuple[str, str]:
    """HTML 通道：直读去标签，返回 (title, 正文)。"""
    title, text = _strip_html(path.read_bytes())
    return (title or path.stem), text


def _index_chm_file(
    chm_path: Path, source_root: Path, out_dir: Path, *, timeout_s: float = 60.0
) -> tuple[list[tuple[str, str | None, str]], str]:
    """CHM 反编译产物逐内页抽文。

    返回 ([(引用路径, title, 正文)], chm 文件级 title)；引用路径 =
    ``<chm相对路径>!<内页相对路径>``（引用可指向 CHM 内具体页）。
    """
    inner_files = _decompile_chm(chm_path, out_dir, timeout_s=timeout_s)
    rel = chm_path.relative_to(source_root).as_posix()
    entries: list[tuple[str, str | None, str]] = []
    for inner in inner_files:
        try:
            title, text = _strip_html(inner.read_bytes())
        except VendorDocError:
            continue
        if not text:
            continue
        cite = f"{rel}!{inner.relative_to(out_dir).as_posix()}"
        entries.append((cite, title or inner.stem, text))
    return entries, (chm_path.stem or rel)


# ---------------------------------------------------------------------------
# 索引构建
# ---------------------------------------------------------------------------


def _open_db(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """打开索引库；read_only 走 URI 只读模式（检索面拒写纪律）。"""
    if read_only:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for sql in _DB_TABLES_SQL:
        conn.execute(sql)


def _iter_candidates(root: Path) -> tuple[list[tuple[Path, str]], int]:
    """遍历语料根：返回 [(绝对路径, 相对路径)] 与不识别后缀计数。"""
    cands: list[tuple[Path, str]] = []
    others = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in SUPPORTED_SUFFIXES:
            cands.append((p, p.relative_to(root).as_posix()))
        else:
            others += 1
    return cands, others


def _index_one_file(
    abs_path: Path,
    rel: str,
    source: str,
    source_root: Path,
    *,
    chunk_chars: int,
    pdf_max_pages: int | None,
    chm_out_dir: Path,
) -> list[dict[str, Any]]:
    """单文件抽取+分块，返回待插入 chunk 行（无 DB 副作用）。

    chunk_index 为**文件级**流水号（跨页/跨内页连续）——(source, path,
    chunk_index) 即唯一键；PDF 的页码单列 ``page``（引用指向原文页码）。
    """
    rows: list[dict[str, Any]] = []
    ci = 0  # 文件级 chunk 流水号
    suffix = abs_path.suffix.lower()
    if suffix == ".pdf":
        title, pages = _extract_pdf_pages(abs_path, max_pages=pdf_max_pages)
        file_title = title or abs_path.stem
        for page_no, text in pages:
            for ck in _chunk_text(text, chunk_chars):
                rows.append(
                    {
                        "source": source,
                        "path": rel,
                        "title": file_title,
                        "page": page_no,
                        "chunk_index": ci,
                        "chunk_text": ck,
                    }
                )
                ci += 1
    elif suffix == ".chm":
        entries, file_title = _index_chm_file(
            abs_path, source_root, chm_out_dir
        )
        for cite, inner_title, text in entries:
            for ck in _chunk_text(text, chunk_chars):
                rows.append(
                    {
                        "source": source,
                        "path": cite,
                        "title": inner_title or file_title,
                        "page": None,
                        "chunk_index": ci,
                        "chunk_text": ck,
                    }
                )
                ci += 1
        if not entries:
            raise VendorDocError("CHM 反编译无可用内页")
    else:  # .htm / .html
        title, text = _index_html_file(abs_path)
        if not text:
            raise VendorDocError("HTML 正文为空")
        for ck in _chunk_text(text, chunk_chars):
            rows.append(
                {
                    "source": source,
                    "path": rel,
                    "title": title,
                    "page": None,
                    "chunk_index": ci,
                    "chunk_text": ck,
                }
            )
            ci += 1
    return rows


def build_vendor_index(
    roots: dict[str, Any],
    *,
    db_path: str | Path | None,
    chunk_chars: int = 1200,
    max_docs: int | None = None,
    rebuild: bool = False,
    pdf_max_pages: int | None = None,
    chm_timeout_s: float = 60.0,
) -> dict[str, Any]:
    """构建厂商文档 FTS5 索引（增量 sha256 去重；rebuild 全量重建）。

    Args:
        roots: ``{source 名: 语料根目录}``——source 约定取
            ``ansys_help``/``ads_doc``（自由名允许），根路径参数注入。
        db_path: 索引库路径；**None 拒写**（不落任何缺省位置）。
        chunk_chars: 单摘要块字符上限（红线：库内无超限全文块）。
        max_docs: 最多处理的文件数（冒烟限幅；None=全部）。
        rebuild: True 时先 DROP 旧表全量重建（否则增量+去重）。
        pdf_max_pages: 单 PDF 最多抽取页数（None=不限；冒烟限幅）。
        chm_timeout_s: 单 CHM 反编译超时秒。

    Returns:
        信封：``{ok, indexed_files, dedup_skipped, chunks_new, total_chunks,
        skipped_files, errors, elapsed_s, roots, sources, db_path}``。
        单文件失败不中断整批（best-effort，错误入 ``errors``）。
    """
    t0 = time.monotonic()
    if db_path is None:
        return error_envelope(
            ["db_path 必填（索引库落盘位置由调用方显式给定，"
             "缺省 None 拒写——#144 同族纪律）"]
        )
    if not roots:
        return error_envelope(["roots 必填（至少一个 source→根目录 映射）"])
    roots_norm: dict[str, Path] = {}
    missing: list[str] = []
    for source, root in roots.items():
        rp = Path(root)  # #140：PathLike 入参第一行先 Path() 收敛
        if rp.is_dir():
            roots_norm[str(source)] = rp
        else:
            missing.append(f"{source} -> {rp}")
    if missing:
        return error_envelope(
            [f"语料根不存在: {m}" for m in missing]
        )

    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = _open_db(db)
    try:
        if rebuild:
            for tbl in (
                "vendor_docs_fts",
                "vendor_docs",
                "vendor_files",
                "vendor_index_meta",
            ):
                conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        _ensure_schema(conn)

        indexed_files = 0
        dedup_skipped = 0
        skipped_files = 0
        chunks_new = 0
        errors: list[str] = []
        sources_stat: dict[str, dict[str, int]] = {}
        changed = False

        for source, root in roots_norm.items():
            cands, others = _iter_candidates(root)
            skipped_files += others
            if max_docs is not None:
                cands = cands[:max_docs]
            stat = sources_stat.setdefault(
                source, {"files": 0, "chunks": 0}
            )
            work_root = db.parent / f"_chm_work_{db.stem}"
            work_root.mkdir(parents=True, exist_ok=True)
            for abs_path, rel in cands:
                chm_out: Path | None = None
                try:
                    digest = _sha256_file(abs_path)
                    prev = conn.execute(
                        "SELECT sha256 FROM vendor_files "
                        "WHERE source=? AND path=?",
                        (source, rel),
                    ).fetchone()
                    if prev is not None and prev["sha256"] == digest:
                        dedup_skipped += 1
                        continue
                    chm_out = work_root / re.sub(
                        r"[^\w.-]", "_", rel
                    )[:120]
                    rows = _index_one_file(
                        abs_path,
                        rel,
                        source,
                        root,
                        chunk_chars=chunk_chars,
                        pdf_max_pages=pdf_max_pages,
                        chm_out_dir=chm_out,
                    )
                    if prev is not None:  # 同路径内容已变：清旧块再重建
                        conn.execute(
                            "DELETE FROM vendor_docs WHERE source=? AND path=?",
                            (source, rel),
                        )
                        changed = True
                    for r in rows:
                        conn.execute(
                            "INSERT INTO vendor_docs (source, path, title,"
                            " page, chunk_index, chunk_text, sha256)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                r["source"],
                                r["path"],
                                r["title"],
                                r["page"],
                                r["chunk_index"],
                                r["chunk_text"],
                                digest,
                            ),
                        )
                    conn.execute(
                        "INSERT INTO vendor_files (source, path, sha256,"
                        " n_chunks, title) VALUES (?, ?, ?, ?, ?)"
                        " ON CONFLICT (source, path) DO UPDATE SET"
                        " sha256=excluded.sha256,"
                        " n_chunks=excluded.n_chunks,"
                        " title=excluded.title",
                        (source, rel, digest, len(rows), rows[0]["title"] if rows else None),
                    )
                    indexed_files += 1
                    chunks_new += len(rows)
                    stat["files"] += 1
                    stat["chunks"] += len(rows)
                    changed = True
                except (VendorDocError, OSError) as exc:
                    errors.append(f"{source}/{rel}: {exc}")
                finally:
                    if chm_out is not None and chm_out.exists():
                        shutil.rmtree(chm_out, ignore_errors=True)
            shutil.rmtree(work_root, ignore_errors=True)

        total_chunks = conn.execute(
            "SELECT COUNT(*) FROM vendor_docs"
        ).fetchone()[0]
        if changed:  # external content 增删后以 rebuild 命令同步 FTS 索引
            conn.execute(
                "INSERT INTO vendor_docs_fts(vendor_docs_fts) VALUES('rebuild')"
            )
        built_at = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_vals = {
            "schema_version": str(VENDOR_INDEX_SCHEMA_VERSION),
            "chunk_chars": str(chunk_chars),
            "built_at": built_at,
            "roots_json": json.dumps(
                {s: str(r) for s, r in roots_norm.items()}, ensure_ascii=False
            ),
        }
        for k, v in meta_vals.items():
            conn.execute(
                "INSERT INTO vendor_index_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                (k, v),
            )
        prev_runs = conn.execute(
            "SELECT value FROM vendor_index_meta WHERE key='n_build_runs'"
        ).fetchone()
        n_runs = (int(prev_runs["value"]) + 1) if prev_runs else 1
        conn.execute(
            "INSERT INTO vendor_index_meta (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value=excluded.value",
            ("n_build_runs", str(n_runs)),
        )
        conn.commit()
        return ok_envelope(
            indexed_files=indexed_files,
            dedup_skipped=dedup_skipped,
            chunks_new=chunks_new,
            total_chunks=total_chunks,
            skipped_files=skipped_files,
            errors=errors,
            elapsed_s=round(time.monotonic() - t0, 3),
            roots={s: str(r) for s, r in roots_norm.items()},
            sources=sources_stat,
            db_path=str(db),
        )
    except sqlite3.Error as exc:
        return error_envelope([f"索引库操作失败: {exc}"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


def _fts_phrase_query(query: str) -> str:
    """FTS5 语法兜底：按空白分词、去内嵌引号、逐词双引号短语（AND）。"""
    tokens = [t.replace('"', "") for t in query.split()]
    return " ".join(f'"{t}"' for t in tokens if t)


def _like_snippet(text: str, token: str) -> str:
    """LIKE 回退通道的手工摘要（FTS snippet 不可用于 LIKE 结果）。"""
    idx = text.lower().find(token.lower())
    if idx < 0:
        return text[:120]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(token) + 80)
    core = (
        text[start:idx]
        + "["
        + text[idx : idx + len(token)]
        + "]"
        + text[idx + len(token) : end]
    )
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{core}{suffix}"


def search_vendor_docs(
    query: str,
    *,
    db_path: str | Path | None,
    limit: int = 10,
) -> dict[str, Any]:
    """带引用检索：FTS5 MATCH（trigram）→ 短词/零命中 LIKE 子串回退。

    Returns:
        信封：``{ok, query, mode, total, hits, limit}``，``hits`` 每项
        ``{source, title, path, page, snippet, chunk_index, rank}``；
        ``mode`` ∈ {fts5, fts5_phrase, like}（声明命中通道）。MATCH 语法
        错误自动降级短语重试；两者皆败才返 error 信封（不抛异常）。
    """
    if db_path is None:
        return error_envelope(
            ["db_path 必填（检索面不落缺省库位置）"]
        )
    query = (query or "").strip()
    if not query:
        return error_envelope(["query 必填（非空检索词）"])
    db = Path(db_path)
    if not db.is_file():
        return error_envelope([f"索引库不存在: {db}（先 build_vendor_index）"])
    limit = max(1, int(limit))
    try:
        conn = _open_db(db, read_only=True)
    except sqlite3.Error as exc:
        return error_envelope([f"索引库打开失败: {exc}"])
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if "vendor_docs" not in tables or "vendor_docs_fts" not in tables:
            return error_envelope(
                [f"索引库未构建（缺 vendor_docs/fts 表）: {db}"]
            )

        mode = "fts5"
        rows: list[sqlite3.Row] = []
        match_expr: str | None = query
        err_raw = None
        try:
            rows = conn.execute(
                "SELECT v.source, v.title, v.path, v.page, v.chunk_index,"
                " snippet(vendor_docs_fts, 0, '[', ']', '…', 12) AS snip,"
                " bm25(vendor_docs_fts) AS rank"
                " FROM vendor_docs_fts f JOIN vendor_docs v"
                " ON v.rowid = f.rowid WHERE vendor_docs_fts MATCH ?"
                " ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            err_raw = str(exc)
            phrase = _fts_phrase_query(query)
            if phrase:
                try:
                    rows = conn.execute(
                        "SELECT v.source, v.title, v.path, v.page,"
                        " v.chunk_index,"
                        " snippet(vendor_docs_fts, 0, '[', ']', '…', 12)"
                        " AS snip, bm25(vendor_docs_fts) AS rank"
                        " FROM vendor_docs_fts f JOIN vendor_docs v"
                        " ON v.rowid = f.rowid WHERE vendor_docs_fts MATCH ?"
                        " ORDER BY rank LIMIT ?",
                        (phrase, limit),
                    ).fetchall()
                    mode = "fts5_phrase"
                    match_expr = phrase
                except sqlite3.OperationalError as exc2:
                    return error_envelope(
                        [f"FTS5 MATCH 语法错误: {exc2}", f"原始错误: {err_raw}"]
                    )
            else:
                return error_envelope([f"FTS5 MATCH 语法错误: {exc}"])

        total = 0
        if rows:
            total = conn.execute(
                "SELECT COUNT(*) FROM vendor_docs_fts WHERE vendor_docs_fts"
                " MATCH ?",
                (match_expr,),
            ).fetchone()[0]
        elif match_expr is not None:
            total = 0  # MATCH 成功但零命中——LIKE 回退再判

        if not rows:  # trigram <3 字短词/复合词失配 → LIKE 子串回退
            mode = "like"
            tokens = [t for t in re.split(r"\s+", query) if t]
            if tokens:
                conds = " OR ".join(["chunk_text LIKE ?"] * len(tokens))
                params = [f"%{t}%" for t in tokens]
                total = conn.execute(
                    f"SELECT COUNT(*) FROM vendor_docs WHERE {conds}", params
                ).fetchone()[0]
                cand = conn.execute(
                    "SELECT source, title, path, page, chunk_index, chunk_text"
                    f" FROM vendor_docs WHERE {conds}"
                    " ORDER BY (CASE WHEN title LIKE ? THEN 0 ELSE 1 END),"
                    " INSTR(chunk_text, ?) LIMIT ?",
                    (*params, f"%{tokens[0]}%", tokens[0], limit),
                ).fetchall()
                rows = [
                    {
                        "source": r["source"],
                        "title": r["title"],
                        "path": r["path"],
                        "page": r["page"],
                        "chunk_index": r["chunk_index"],
                        "snip": _like_snippet(r["chunk_text"], tokens[0]),
                        "rank": None,
                    }
                    for r in cand
                ]

        hits = [
            {
                "source": r["source"],
                "title": r["title"],
                "path": r["path"],
                "page": r["page"],
                "snippet": r["snip"],
                "chunk_index": r["chunk_index"],
                "rank": r["rank"],
            }
            for r in rows
        ]
        return ok_envelope(
            query=query, mode=mode, total=total, hits=hits, limit=limit
        )
    except sqlite3.Error as exc:
        return error_envelope([f"检索失败: {exc}"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 零入库审计
# ---------------------------------------------------------------------------


def zero_ingest_audit(*, db_path: str | Path | None) -> dict[str, Any]:
    """索引库零入库审计：记录数/chunk 字符总量/来源清单（可复核红线）。

    复核口径：库内仅存 ≤chunk_chars 摘要块——``max_chunk_chars`` ≤
    meta 声明 ``chunk_chars`` 即"摘要块非全文"成立；全文体量只存在于
    厂商本机语料（不进本库、不入仓）。
    """
    if db_path is None:
        return error_envelope(["db_path 必填（审计面不落缺省库位置）"])
    db = Path(db_path)
    if not db.is_file():
        return error_envelope([f"索引库不存在: {db}"])
    try:
        conn = _open_db(db, read_only=True)
    except sqlite3.Error as exc:
        return error_envelope([f"索引库打开失败: {exc}"])
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        if "vendor_docs" not in tables:
            return error_envelope([f"索引库未构建: {db}"])
        n_files = conn.execute("SELECT COUNT(*) FROM vendor_files").fetchone()[0]
        n_chunks = conn.execute("SELECT COUNT(*) FROM vendor_docs").fetchone()[0]
        total_chars = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(chunk_text)), 0) FROM vendor_docs"
        ).fetchone()[0]
        max_chunk = conn.execute(
            "SELECT COALESCE(MAX(LENGTH(chunk_text)), 0) FROM vendor_docs"
        ).fetchone()[0]
        by_source_rows = conn.execute(
            "SELECT d.source AS source,"
            " COUNT(DISTINCT d.path) AS files,"
            " COUNT(*) AS chunks,"
            " COALESCE(SUM(LENGTH(d.chunk_text)), 0) AS chunk_chars"
            " FROM vendor_docs d GROUP BY d.source ORDER BY d.source"
        ).fetchall()
        by_source = {
            r["source"]: {
                "files": r["files"],
                "chunks": r["chunks"],
                "chunk_chars": r["chunk_chars"],
            }
            for r in by_source_rows
        }
        meta = {
            r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM vendor_index_meta")
        }
        declared = int(meta.get("chunk_chars", "0") or 0)
        within = bool(declared) and max_chunk <= declared
        return ok_envelope(
            n_files=n_files,
            n_chunks=n_chunks,
            total_chunk_chars=total_chars,
            max_chunk_chars=max_chunk,
            by_source=by_source,
            sources=sorted(by_source),
            declared_chunk_chars=declared,
            within_chunk_limit=within,
            built_at=meta.get("built_at"),
            roots=json.loads(meta.get("roots_json", "{}")),
            note=(
                "红线复核：库内仅存 ≤chunk_chars 摘要块与元数据，"
                "厂商全文零入仓（索引库=runs/ 证据区本地件）"
                if within
                else "无法确认块上限（meta 缺 chunk_chars 或有超限块）——"
                "请复核索引构建参数"
            ),
        )
    except sqlite3.Error as exc:
        return error_envelope([f"审计失败: {exc}"])
    finally:
        conn.close()
