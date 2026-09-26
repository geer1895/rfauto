"""lake_service —— runs/ 数据湖索引与分层压实 MVP（F3/df7）。

三个能力面（规格：docs/plan_expansion_pool_20260924.md F3）：

- 索引：``build_runs_index`` 扫 runs/（一级战役目录+二级 run 点，两层
  目录**全部入索引**，目录级元数据如实留 NULL）入 DuckDB 表
  ``runs_lake_index``——查询面复用现有 DuckDB 惯例（连接管理/建表/只读
  参数化查询，参照 db_service.fidelity_shadow 同款）；``query_runs_index``
  按 template/adapter/study/campaign/日期段过滤，``?`` 占位符绑定，
  值永不拼进 SQL。
- 冷层压实：``pack_campaign`` 把战役目录打成 tar.zst + 偏移清单
  manifest JSON（每文件相对路径+offset+size+sha256，确定性文件排序+
  归一化 tar 头，同内容重打包 pack_sha256 逐位一致），原目录零改动
  （只读）。
- 内容寻址恢复：``verify_campaign`` 整包 sha256 快速校验 + 逐文件
  sha256 重算比对（偏移定位）；``restore_campaign`` 解包到**新目录**
  （目标已存在即拒——绝不覆盖），恢复后逐文件哈希复核。

绝不重写历史（#325/#326 golden 零改写同构）：本模块对 runs/ 既有内容
只读——build_runs_index 只读扫描，pack 只读打包，verify/restore 只读
归档；唯一写点是显式传入/缺省约定的 db_path、out_path 与 restore 的
target_dir（必须是不存在的新目录）。DVC/git-annex 判超配（单机无跨机
同步需求，不引入，规格原文）。

可选依赖：duckdb（dataset extra，索引/查询面缺装显式报缺）、zstandard
（冷层 tar.zst 压缩面缺装显式报缺）；其余路径不依赖二者。

分层：service 层（可 import infra）；CLI/MCP 接线本件不做（df7 另批，
报告登记缺口）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

__all__ = [
    "LAKE_INDEX_COLUMNS",
    "LAKE_INDEX_TABLE",
    "PACK_FORMAT",
    "build_runs_index",
    "default_lake_index_db_path",
    "pack_campaign",
    "query_runs_index",
    "restore_campaign",
    "verify_campaign",
]

# ---------------------------------------------------------------------------
# runs/ 湖索引（DuckDB）
# ---------------------------------------------------------------------------

#: 索引表名（查询面复用现有 DuckDB）
LAKE_INDEX_TABLE = "runs_lake_index"

#: 表结构：(列名, DuckDB 类型)。spec 必列 path/template/adapter/study/
#: created_ts/has_meta/has_verdict/size_bytes；run_id/campaign/depth/
#: status/created_date/meta_source/verdict/n_files 为实测可得补充字段
#: （created_ts 存 meta.timestamp 原文，created_date 是解析出的日期列，
#: 供日期段过滤；缺字段一律 NULL，不臆造）。
LAKE_INDEX_COLUMNS: tuple[tuple[str, str], ...] = (
    ("path", "VARCHAR"),        # 相对 runs_dir 的 posix 路径
    ("run_id", "VARCHAR"),      # 目录名（末段）
    ("campaign", "VARCHAR"),    # 二级点所属一级战役目录名；一级目录为 NULL
    ("depth", "INTEGER"),       # 1=runs/<dir>，2=runs/<campaign>/<dir>
    ("template", "VARCHAR"),    # meta.model
    ("adapter", "VARCHAR"),     # meta.adapter
    ("study", "VARCHAR"),       # meta.study_name
    ("status", "VARCHAR"),      # meta.status
    ("created_ts", "VARCHAR"),  # meta.timestamp 原文
    ("created_date", "DATE"),   # created_ts 解析出的日期（失败 NULL）
    ("has_meta", "BOOLEAN"),    # meta.json / run_meta.json 存在
    ("meta_source", "VARCHAR"), # "meta.json" | "run_meta.json" | NULL
    ("has_verdict", "BOOLEAN"), # verdict.json 存在
    ("verdict", "VARCHAR"),     # verdict.json 的 verdict 键（缺/解析失败 NULL）
    ("size_bytes", "BIGINT"),   # 目录实测总大小（递归求和）
    ("n_files", "BIGINT"),      # 目录实测文件数
)

#: 索引库缺省落点（runs/ 已整体 gitignore，运行时 DB 不进 git）
DEFAULT_LAKE_INDEX_NAME = ".lake_index.duckdb"

_META_NAMES = ("meta.json", "run_meta.json")
_VERDICT_NAME = "verdict.json"


def default_lake_index_db_path() -> Path:
    """缺省索引库路径：``runs/.lake_index.duckdb``。"""
    return Path("runs") / DEFAULT_LAKE_INDEX_NAME


def _import_duckdb() -> Any:
    """duckdb 缺装显式报缺（extras dataset 已含，缺失提示装法）。"""
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "duckdb 未安装：湖索引需要 pip install rfauto[dataset]"
            f"（{exc}）") from exc
    return duckdb


def _meta_file(run_dir: Path) -> Path | None:
    """run 目录的 meta 文件：meta.json 优先，run_meta.json 兜底。"""
    for name in _META_NAMES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """读 JSON 对象；缺失/解析失败/非对象一律 None（best-effort #105）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _parse_date(raw: Any) -> Any:
    """ISO 时间戳字符串 → date（供日期段过滤）；解析失败 None。"""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _dir_stats(run_dir: Path) -> tuple[int, int]:
    """目录实测 (总字节数, 文件数)——os.scandir 递归，零写面。"""
    total = 0
    n_files = 0
    stack = [run_dir]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            n_files += 1
                    except OSError:
                        continue  # 单条目失败不阻塞（#105 best-effort）
        except OSError:
            continue
    return total, n_files


def _iter_run_dirs(root: Path):
    """扫 runs/ 两层：一级战役目录+二级 run 点，全部目录产出（元数据
    缺失如实 NULL）；产出 (run_dir, campaign_name_or_None, depth)。"""
    try:
        level1 = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return
    for top in level1:
        yield top, None, 1
        try:
            level2 = sorted(p for p in top.iterdir() if p.is_dir())
        except OSError:
            continue
        for sub in level2:
            yield sub, top.name, 2


def _index_row(run_dir: Path, campaign: str | None,
               depth: int, rel: str) -> dict[str, Any]:
    """单目录索引行：实测可得字段全量收集，缺失字段 NULL。"""
    meta_path = _meta_file(run_dir)
    meta = _read_json_object(meta_path) if meta_path is not None else None
    verdict_path = run_dir / _VERDICT_NAME
    has_verdict = verdict_path.is_file()
    verdict = (_read_json_object(verdict_path) or {}).get("verdict") \
        if has_verdict else None
    size, n_files = _dir_stats(run_dir)
    created_ts = meta.get("timestamp") if meta else None
    return {
        "path": rel,
        "run_id": run_dir.name,
        "campaign": campaign,
        "depth": depth,
        "template": str(meta.get("model")) if meta and meta.get("model") is not None else None,
        "adapter": str(meta.get("adapter")) if meta and meta.get("adapter") is not None else None,
        "study": str(meta.get("study_name")) if meta and meta.get("study_name") is not None else None,
        "status": str(meta.get("status")) if meta and meta.get("status") is not None else None,
        "created_ts": str(created_ts) if created_ts is not None else None,
        "created_date": _parse_date(created_ts),
        "has_meta": meta_path is not None,
        "meta_source": meta_path.name if meta_path is not None else None,
        "has_verdict": has_verdict,
        "verdict": str(verdict) if verdict is not None else None,
        "size_bytes": size,
        "n_files": n_files,
    }


def build_runs_index(
    runs_dir: str | Path = "runs",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """扫 runs/（一级+二级目录）重建 DuckDB 湖索引表（幂等可重放）。

    幂等口径：**重建=drop create**（``DROP TABLE IF EXISTS`` + ``CREATE
    TABLE`` + 全量 INSERT）——同 runs 重跑行数/内容不变，schema 一次建准
    不做增量迁移。行集=两层全部目录（一级战役目录+二级 run 点），字段只
    从实际存在的 meta.json/run_meta.json/verdict.json 读取，缺失如实
    NULL（不臆造，规格"存在才读，缺失跳过如实"）；单目录元数据解析失败
    不阻塞整体（#105），errors 留痕截断前 20 条。

    runs 目录不存在时如实返回零值不建库（reindex_runs 同款惯例）。
    返回 {"ok", "db_path", "table", "n_rows", "n_meta_rows",
    "n_verdict_rows", "errors"}。
    """
    root = Path(runs_dir)
    base: dict[str, Any] = {
        "db_path": str(Path(db_path) if db_path is not None
                       else default_lake_index_db_path()),
        "table": LAKE_INDEX_TABLE,
    }
    if not root.is_dir():
        return {"ok": True, "n_rows": 0, "n_meta_rows": 0,
                "n_verdict_rows": 0, "errors": [], **base,
                "note": f"runs 目录不存在: {root}"}
    try:
        duckdb = _import_duckdb()
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)], **base}

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for run_dir, campaign, depth in _iter_run_dirs(root):
        try:
            rel = run_dir.relative_to(root).as_posix()
            rows.append(_index_row(run_dir, campaign, depth, rel))
        except Exception as exc:  # 单目录失败不阻塞（#105）
            if len(errors) < 20:
                errors.append(f"{run_dir}: {exc}")

    con = None
    try:
        path = Path(base["db_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(path))
        cols = ", ".join(f"{name} {typ}" for name, typ in LAKE_INDEX_COLUMNS)
        con.execute(f"DROP TABLE IF EXISTS {LAKE_INDEX_TABLE}")
        con.execute(f"CREATE TABLE {LAKE_INDEX_TABLE} ({cols})")
        names = [name for name, _typ in LAKE_INDEX_COLUMNS]
        placeholders = ", ".join("?" for _ in names)
        insert_sql = (f"INSERT INTO {LAKE_INDEX_TABLE} "
                      f"({', '.join(names)}) VALUES ({placeholders})")
        for row in rows:
            con.execute(insert_sql,
                        [row[name] for name in names])
        n_meta = sum(1 for row in rows if row["has_meta"])
        n_verdict = sum(1 for row in rows if row["has_verdict"])
        return {"ok": True, "n_rows": len(rows), "n_meta_rows": n_meta,
                "n_verdict_rows": n_verdict, "errors": errors, **base}
    except Exception as exc:
        return {"ok": False, "errors": [f"索引写入失败: {exc}"], **base}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


def query_runs_index(
    db_path: str | Path | None = None,
    *,
    template: str | None = None,
    adapter: str | None = None,
    study: str | None = None,
    campaign: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """湖索引只读参数化查询（等值过滤 + 日期段，``?`` 占位符绑定）。

    template/adapter/study/campaign 为等值过滤（空串/None 视为不过滤）；
    date_from/date_to 为 ``YYYY-MM-DD`` 闭区间（落在 created_date 列，
    非法日期 ValueError 信封）；行按 path 排序，limit 截断。
    返回 {"ok", "rows"(dict 列表), "n_rows", "db_path", "table"}；
    库不存在/duckdb 缺装 → ok=False 如实。
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    base: dict[str, Any] = {"db_path": str(path), "table": LAKE_INDEX_TABLE}
    if not path.exists():
        return {"ok": False,
                "errors": [f"湖索引库不存在（先 build_runs_index）: {path}"],
                "rows": [], "n_rows": 0, **base}
    try:
        duckdb = _import_duckdb()
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)], "rows": [], "n_rows": 0,
                **base}
    try:
        n_limit = max(1, int(limit))
    except (TypeError, ValueError):
        return {"ok": False, "errors": [f"limit 非法: {limit!r}"],
                "rows": [], "n_rows": 0, **base}

    clauses: list[tuple[str, Any]] = []
    for key, val in (("template", template), ("adapter", adapter),
                     ("study", study), ("campaign", campaign)):
        if val is None or val == "":
            continue
        if not isinstance(val, str):
            return {"ok": False,
                    "errors": [f"{key} 必须是 str 或 None，"
                               f"收到 {type(val).__name__}"],
                    "rows": [], "n_rows": 0, **base}
        clauses.append((f"{key} = ?", val))
    try:
        if date_from is not None:
            clauses.append(("created_date >= ?", datetime.strptime(
                date_from, "%Y-%m-%d").date()))
        if date_to is not None:
            clauses.append(("created_date <= ?", datetime.strptime(
                date_to, "%Y-%m-%d").date()))
    except ValueError as exc:
        return {"ok": False,
                "errors": [f"日期段非法（YYYY-MM-DD）: {exc}"],
                "rows": [], "n_rows": 0, **base}

    # 参数化 WHERE：值只进 ? 绑定，永不拼进 SQL 文本（db_service 同款防线）
    where_parts = [clause for clause, _val in clauses]
    params = [val for _clause, val in clauses]
    names = [name for name, _typ in LAKE_INDEX_COLUMNS]
    sql = (f"SELECT {', '.join(names)} FROM {LAKE_INDEX_TABLE}"
           + (" WHERE " + " AND ".join(where_parts) if where_parts else "")
           + " ORDER BY path LIMIT ?")
    params.append(n_limit)
    con = None
    try:
        con = duckdb.connect(str(path), read_only=True)
        rows_raw = con.execute(sql, params).fetchall()
        rows = [dict(zip(names, r, strict=True)) for r in rows_raw]
        return {"ok": True, "rows": rows, "n_rows": len(rows), **base}
    except Exception as exc:
        return {"ok": False, "errors": [f"湖索引查询失败: {exc}"],
                "rows": [], "n_rows": 0, **base}
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()


# ---------------------------------------------------------------------------
# 冷层压实：tar.zst + 偏移清单（内容寻址）
# ---------------------------------------------------------------------------

#: 偏移清单格式标识（schema 演进锚）
PACK_FORMAT = "rfauto-lake-pack-v1"


def _import_zstandard() -> Any:
    """zstandard 缺装显式报缺（tar.zst 压缩面；pip install zstandard）。"""
    try:
        import zstandard
    except ImportError as exc:
        raise RuntimeError(
            "zstandard 未安装：冷层 tar.zst 压实需要 "
            f"pip install zstandard（{exc}）") from exc
    return zstandard


def _sha256_file(path: Path, _buf_size: int = 1 << 20) -> str:
    """文件流式 sha256（hex）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_buf_size):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_files(campaign_dir: Path) -> list[tuple[str, Path]]:
    """战役目录全部文件的确定性清单：相对 posix 路径排序（规格"确定性
    排序文件列表"），返回 [(rel_posix, absolute_path)]。"""
    entries: list[tuple[str, Path]] = []
    for current, _dirnames, filenames in os.walk(campaign_dir):
        for filename in filenames:
            abs_path = Path(current) / filename
            entries.append(
                (abs_path.relative_to(campaign_dir).as_posix(), abs_path))
    entries.sort(key=lambda pair: pair[0])
    return entries


def _manifest_path_for(out_path: Path) -> Path:
    """偏移清单缺省落点：<pack>.manifest.json。"""
    return Path(str(out_path) + ".manifest.json")


def _safe_rel_path(rel: str) -> PurePosixPath | None:
    """清单相对路径守卫：拒绝绝对路径/穿越/盘符/反斜杠（restore 写面前
    最后一道防线；pack 侧清单由本模块生成天然安全）。"""
    if not rel or "\\" in rel:
        return None
    pure = PurePosixPath(rel)
    if pure.is_absolute() or ".." in pure.parts or pure.drive:
        return None
    return pure


def pack_campaign(
    campaign_dir: str | Path,
    out_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """战役目录 → tar.zst + 偏移清单（只读原目录，零改动）。

    - 文件清单确定性排序（相对 posix 路径全序），tar 头归一化
      （mtime=0/uid=gid=0/uname=gname 空）→ 同内容重打包 pack_sha256
      逐位一致；
    - 偏移清单 JSON：每文件 {path, offset(tar 流内数据起始字节),
      size, sha256} + 整包 pack_sha256（内容寻址锚，verify 快速路径）；
    - 原目录只读；写面仅 out_path 与 manifest（缺省
      ``<out>.manifest.json``）。

    返回 {"ok", "pack_path", "manifest_path", "n_files", "total_bytes",
    "pack_sha256", "pack_size_bytes"}；目录不存在/无文件/缺 zstandard →
    ok=False 如实。
    """
    src = Path(campaign_dir)
    base: dict[str, Any] = {
        "pack_path": str(out_path),
        "manifest_path": str(manifest_path
                             if manifest_path is not None
                             else _manifest_path_for(Path(out_path))),
    }
    if not src.is_dir():
        return {"ok": False,
                "errors": [f"战役目录不存在: {src}"], **base}
    try:
        zstandard = _import_zstandard()
    except RuntimeError as exc:
        return {"ok": False, "errors": [str(exc)], **base}
    files = _collect_files(src)
    if not files:
        return {"ok": False,
                "errors": [f"战役目录无文件（拒绝打空 tar）: {src}"],
                **base}

    out = Path(out_path)
    manifest_path_obj = Path(base["manifest_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest_path_obj.parent.mkdir(parents=True, exist_ok=True)
    tmp_tar: str | None = None
    try:
        # ① 未压缩 tar 落临时文件（确定性头），② 回读取逐成员 offset_data
        # （tarfile 自身记账，含 PAX 头），③ zstd 流式压缩到 out_path
        with tempfile.NamedTemporaryFile(
                suffix=".tar", delete=False) as tmp:
            tmp_tar = tmp.name
        with tarfile.open(tmp_tar, "w", format=tarfile.PAX_FORMAT) as tar:
            for rel, abs_path in files:
                info = tarfile.TarInfo(name=rel)
                info.size = abs_path.stat().st_size
                info.mtime = 0
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                with open(abs_path, "rb") as f:
                    tar.addfile(info, f)
        offsets: dict[str, int] = {}
        with tarfile.open(tmp_tar, "r") as tar:
            for member in tar.getmembers():
                offsets[member.name] = member.offset_data
        missing_offsets = [rel for rel, _p in files if rel not in offsets]
        if missing_offsets:
            return {"ok": False,
                    "errors": [f"tar 成员偏移缺失: {missing_offsets[:5]}"],
                    **base}
        cctx = zstandard.ZstdCompressor(level=3, write_checksum=True,
                                        write_content_size=True)
        with open(tmp_tar, "rb") as src_io, open(out, "wb") as dst:
            cctx.copy_stream(src_io, dst)

        file_entries = []
        total = 0
        for rel, abs_path in files:
            size = abs_path.stat().st_size
            total += size
            file_entries.append({
                "path": rel,
                "offset": offsets[rel],
                "size": size,
                "sha256": _sha256_file(abs_path),
            })
        pack_sha = _sha256_file(out)
        manifest = {
            "format": PACK_FORMAT,
            "campaign": src.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "n_files": len(files),
            "total_bytes": total,
            "pack_file": out.name,
            "pack_sha256": pack_sha,
            "pack_size_bytes": out.stat().st_size,
            "files": file_entries,
        }
        manifest_path_obj.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return {"ok": True, "n_files": len(files), "total_bytes": total,
                "pack_sha256": pack_sha,
                "pack_size_bytes": out.stat().st_size, **base}
    except Exception as exc:
        return {"ok": False, "errors": [f"打包失败: {exc}"], **base}
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)


def _decompress_pack(pack_path: Path, tmp_tar: str) -> str | None:
    """zstd 流式解压到临时 tar；失败返回错误描述（None=成功）。"""
    zstandard = _import_zstandard()
    dctx = zstandard.ZstdDecompressor()
    try:
        with open(pack_path, "rb") as src, open(tmp_tar, "wb") as dst:
            dctx.copy_stream(src, dst)
    except Exception as exc:
        return f"解压失败（包体损坏?）: {exc}"
    return None


def _load_manifest(manifest_path: Path) -> tuple[dict[str, Any] | None,
                                                 str | None]:
    """读偏移清单；格式不符/字段缺失返回错误描述。"""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"清单读取/解析失败: {exc}"
    if not isinstance(manifest, dict) or manifest.get("format") != PACK_FORMAT:
        return None, f"清单格式不符（期望 {PACK_FORMAT}）"
    if not isinstance(manifest.get("files"), list):
        return None, "清单缺 files 段"
    return manifest, None


def verify_campaign(
    pack_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    """归档校验：整包 sha256 快速校验 + 逐文件 sha256 重算（偏移定位）。

    逐文件口径：解压后在 tar 流内按清单 offset 定位、按 size 读取、
    sha256 与清单比对；offset/size 不符或哈希不匹配该文件 FAIL——
    **如实逐文件报告，不凑绿不放大**（#122/#314 同族：校验面只对独立
    证据下结论）。整包哈希不符只记 error 不中止（继续定位损坏面）；
    解压失败则无法逐文件定位，ok=False + error 如实返回。

    返回 {"ok", "pack_sha256_ok", "files": [{path, ok, reason?}],
    "n_ok", "n_fail", "errors"}。
    """
    pack = Path(pack_path)
    manifest_file = Path(manifest_path)
    base: dict[str, Any] = {"pack_path": str(pack),
                            "manifest_path": str(manifest_file)}
    if not pack.is_file():
        return {"ok": False, "pack_sha256_ok": False, "files": [],
                "n_ok": 0, "n_fail": 0,
                "errors": [f"归档不存在: {pack}"], **base}
    _import_zstandard()  # 缺装显式报缺（解压面）
    manifest, err = _load_manifest(manifest_file)
    if err is not None:
        return {"ok": False, "pack_sha256_ok": False, "files": [],
                "n_ok": 0, "n_fail": 0, "errors": [err], **base}
    assert manifest is not None  # err is None ⇒ manifest 就绪
    entries: list[dict[str, Any]] = manifest["files"]

    errors: list[str] = []
    pack_sha = _sha256_file(pack)
    pack_sha_ok = pack_sha == manifest.get("pack_sha256")
    if not pack_sha_ok:
        errors.append(
            f"整包 sha256 不符（内容寻址锚失配）: 清单 "
            f"{manifest.get('pack_sha256')} vs 实测 {pack_sha}")

    results: list[dict[str, Any]] = []
    tmp_tar: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                suffix=".tar", delete=False) as tmp:
            tmp_tar = tmp.name
        decompress_err = _decompress_pack(pack, tmp_tar)
        if decompress_err is not None:
            # 包体损坏到解不开：逐文件定位不可得，如实整体 FAIL
            return {"ok": False, "pack_sha256_ok": pack_sha_ok,
                    "files": [], "n_ok": 0, "n_fail": 0,
                    "errors": [*errors, decompress_err], **base}
        member_offsets: dict[str, tuple[int, int]] = {}
        with tarfile.open(tmp_tar, "r") as tar:
            for member in tar.getmembers():
                member_offsets[member.name] = (member.offset_data,
                                               member.size)
        manifest_paths = {entry.get("path") for entry in entries}
        extra = sorted(set(member_offsets) - manifest_paths)
        if extra:
            errors.append(f"tar 含清单外成员（包/清单失配）: {extra[:5]}")
        with open(tmp_tar, "rb") as tar_io:
            for entry in entries:
                rel = str(entry.get("path") or "")
                record: dict[str, Any] = {"path": rel}
                expected_off = entry.get("offset")
                expected_size = entry.get("size")
                expected_sha = entry.get("sha256")
                if rel not in member_offsets:
                    record.update(ok=False, reason="tar 内缺该成员")
                    results.append(record)
                    continue
                actual_off, actual_size = member_offsets[rel]
                if expected_off != actual_off or expected_size != actual_size:
                    record.update(
                        ok=False,
                        reason=f"offset/size 不符（清单 "
                               f"{expected_off}/{expected_size} vs tar "
                               f"{actual_off}/{actual_size}）")
                    results.append(record)
                    continue
                tar_io.seek(actual_off)
                data = tar_io.read(actual_size)
                actual_sha = hashlib.sha256(data).hexdigest()
                if actual_sha != expected_sha:
                    record.update(
                        ok=False,
                        reason=f"sha256 不符（清单 {expected_sha} vs "
                               f"实测 {actual_sha}）")
                    results.append(record)
                    continue
                record.update(ok=True)
                results.append(record)
        n_fail = sum(1 for r in results if not r["ok"])
        ok = pack_sha_ok and n_fail == 0 and not extra
        return {"ok": ok, "pack_sha256_ok": pack_sha_ok, "files": results,
                "n_ok": len(results) - n_fail, "n_fail": n_fail,
                "errors": errors, **base}
    except Exception as exc:
        return {"ok": False, "pack_sha256_ok": pack_sha_ok,
                "files": results, "n_ok": 0,
                "n_fail": sum(1 for r in results if not r["ok"]),
                "errors": [*errors, f"校验执行失败: {exc}"], **base}
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)


def restore_campaign(
    pack_path: str | Path,
    manifest_path: str | Path,
    target_dir: str | Path,
) -> dict[str, Any]:
    """恢复归档到**新目录**（目标已存在即拒——绝不覆盖，规格原文）。

    流程：整包 sha + 清单/tar 成员集一致性预检（任一不符则在触碰目标
    目录**之前**中止）→ 解包逐文件写入（按清单偏移定位）→ 恢复后逐文件
    哈希复核（重读落盘文件比对清单 sha256）。原归档零触碰；预检失败
    不创建目标目录，逐文件复核失败保留现场如实报 FAIL（不静默清理）。

    返回 {"ok", "target_dir", "n_files", "n_verified", "total_bytes"}；
    拒绝/失败 → ok=False + errors。
    """
    pack = Path(pack_path)
    manifest_file = Path(manifest_path)
    target = Path(target_dir)
    base: dict[str, Any] = {"pack_path": str(pack),
                            "manifest_path": str(manifest_file),
                            "target_dir": str(target)}
    if target.exists():
        return {"ok": False,
                "errors": [f"目标目录已存在，拒绝恢复（绝不覆盖）: {target}"],
                **base}
    if not pack.is_file():
        return {"ok": False, "errors": [f"归档不存在: {pack}"], **base}
    _import_zstandard()  # 缺装显式报缺（解压面）
    manifest, err = _load_manifest(manifest_file)
    if err is not None:
        return {"ok": False, "errors": [err], **base}
    assert manifest is not None
    entries: list[dict[str, Any]] = manifest["files"]
    if not entries:
        return {"ok": False, "errors": ["清单无文件（空归档）"], **base}
    # 相对路径守卫：穿越/绝对路径条目预检拒绝（写面前最后一道防线）
    for entry in entries:
        if _safe_rel_path(str(entry.get("path") or "")) is None:
            return {"ok": False,
                    "errors": [f"清单含非法相对路径条目: {entry.get('path')!r}"],
                    **base}

    errors: list[str] = []
    pack_sha = _sha256_file(pack)
    pack_sha_ok = pack_sha == manifest.get("pack_sha256")
    if not pack_sha_ok:
        errors.append(
            f"整包 sha256 不符: 清单 {manifest.get('pack_sha256')} vs "
            f"实测 {pack_sha}")

    tmp_tar: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
                suffix=".tar", delete=False) as tmp:
            tmp_tar = tmp.name
        decompress_err = _decompress_pack(pack, tmp_tar)
        if decompress_err is not None:
            return {"ok": False,
                    "errors": [*errors, decompress_err], **base}
        member_offsets: dict[str, tuple[int, int]] = {}
        with tarfile.open(tmp_tar, "r") as tar:
            for member in tar.getmembers():
                member_offsets[member.name] = (member.offset_data,
                                               member.size)
        manifest_paths = {str(entry.get("path")) for entry in entries}
        extra = sorted(set(member_offsets) - manifest_paths)
        missing = sorted(manifest_paths - set(member_offsets))
        if extra:
            errors.append(f"tar 含清单外成员: {extra[:5]}")
        if missing:
            errors.append(f"tar 缺清单成员: {missing[:5]}")
        if errors:
            # 预检不符：不触碰目标目录（绝不半恢复覆盖历史面）
            return {"ok": False, "errors": errors, **base}

        target.mkdir(parents=True)
        n_verified = 0
        total = 0
        with open(tmp_tar, "rb") as tar_io:
            for entry in entries:
                rel = str(entry["path"])
                dest = target / _safe_rel_path(rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                offset, size = member_offsets[rel]
                tar_io.seek(offset)
                data = tar_io.read(size)
                digest = hashlib.sha256(data).hexdigest()
                dest.write_bytes(data)
                total += len(data)
                # 恢复后逐文件哈希复核（重读落盘文件，非写前内存值）
                written_sha = _sha256_file(dest)
                if (digest != str(entry.get("sha256"))
                        or written_sha != str(entry.get("sha256"))):
                    errors.append(
                        f"{rel}: 恢复后哈希复核不符（落盘 "
                        f"{written_sha} vs 清单 {entry.get('sha256')}）")
                    continue
                n_verified += 1
        if errors:
            return {"ok": False, "n_files": len(entries),
                    "n_verified": n_verified, "total_bytes": total,
                    "errors": errors, **base}
        return {"ok": True, "n_files": len(entries),
                "n_verified": n_verified, "total_bytes": total,
                **base}
    except Exception as exc:
        return {"ok": False, "errors": [f"恢复失败: {exc}"], **base}
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)
