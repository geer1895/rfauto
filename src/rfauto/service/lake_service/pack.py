"""lake_service.pack —— 冷层归档（P-5 parquet 导出 + 打包/校验/恢复）。

自 lake_service.py 巨石按职责域拆分（架构批 W7-S1 T2，AU-1 工艺）：代码体自原「冷层导出」「冷层压实」两节逐字节搬迁。
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

from rfauto.service.envelope import error_envelope, ok_envelope

from .index import (
    LAKE_INDEX_COLUMNS,
    LAKE_INDEX_TABLE,
    _import_duckdb,
    configure_duckdb_connection,
    default_lake_index_db_path,
)

# ---------------------------------------------------------------------------
# P-5 冷层导出：索引表 COPY parquet（hive 分区接口）
# ---------------------------------------------------------------------------

def export_index_parquet(
    db_path: str | Path | None = None,
    out_dir: str | Path | None = None,
    *,
    partition_by: str | None = "created_date",
    overwrite: bool = False,
) -> dict[str, Any]:
    """湖索引表 → parquet 冷层（``COPY … TO … (FORMAT PARQUET,
    PARTITION_BY …)`` hive 分区接口，P-5）。

    冷层语义：索引库（.lake_index.duckdb）是易失查询面，parquet 目录是
    可被外部引擎（pandas/pyarrow/其他 DuckDB）直读的归档面；本接口只从
    **已建索引**导出，不重扫 runs/（建索引走 build_runs_index）。分区列
    缺省 created_date（NULL 分区行 DuckDB 落 ``__HIVE_DEFAULT_PARTITION__``
    ——属正常产物，如实注记不清洗）；零防御配置例外：导出连接同样走
    configure_duckdb_connection（best-effort）。只读索引库+新写 out_dir，
    原目录零改动红线不变。

    Returns:
        dict: {"ok", "db_path", "out_dir", "n_rows", "partition_by",
               "files", "errors"}（行数=导出后 SELECT count(*) 复核）
    """
    path = Path(db_path) if db_path is not None else default_lake_index_db_path()
    base: dict[str, Any] = {"db_path": str(path),
                            "out_dir": str(Path(out_dir) if out_dir is not None
                                            else path.with_suffix(".parquet")),
                            "partition_by": partition_by}
    if not path.is_file():
        return error_envelope(
            [f"湖索引库不存在（先 build_runs_index）: {path}"],
            n_rows=0, files=[], **base)
    duckdb = _import_duckdb()
    con = None
    try:
        out = Path(base["out_dir"])
        out.mkdir(parents=True, exist_ok=overwrite)
        con = duckdb.connect(str(path), read_only=True)
        configure_duckdb_connection(con)
        names = [name for name, _typ in LAKE_INDEX_COLUMNS]
        partition_sql = (f", PARTITION_BY ({partition_by})"
                         if partition_by else "")
        overwrite_sql = ", OVERWRITE_OR_IGNORE true" if overwrite else ""
        con.execute(
            f"COPY (SELECT {', '.join(names)} FROM {LAKE_INDEX_TABLE}) "
            f"TO '{out.as_posix()}' (FORMAT PARQUET{partition_sql}"
            f"{overwrite_sql})")
        n_rows = int(con.execute(
            f"SELECT count(*) FROM {LAKE_INDEX_TABLE}").fetchone()[0])
        files = sorted(str(p.relative_to(out).as_posix())
                       for p in out.rglob("*.parquet"))
        return ok_envelope(
                   **{
                   "n_rows": n_rows,
                   "files": files,
                   **base,
                   "note": "hive 分区目录可被 pandas/pyarrow/duckdb 直读；"
                         "NULL 分区列落 __HIVE_DEFAULT_PARTITION__ 属正常产物",
                   },
               )
    except Exception as exc:
        return error_envelope(
            [f"冷层导出失败: {exc}"], n_rows=0, files=[], **base)
    finally:
        if con is not None:
            with contextlib.suppress(Exception):
                con.close()
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
    include_crate_metadata: bool = False,
) -> dict[str, Any]:
    """战役目录 → tar.zst + 偏移清单（只读原目录，零改动）。

    - 文件清单确定性排序（相对 posix 路径全序），tar 头归一化
      （mtime=0/uid=gid=0/uname=gname 空）→ 同内容重打包 pack_sha256
      逐位一致；
    - 偏移清单 JSON：每文件 {path, offset(tar 流内数据起始字节),
      size, sha256} + 整包 pack_sha256（内容寻址锚，verify 快速路径）；
    - XD-16 crate 化（opt-in）：``include_crate_metadata=True`` 时另写
      ``<out>.crate-metadata.json`` 侧车（RO-Crate 1.1 JSON-LD 自描述
      层，复用 reproducibility_service.build_crate_metadata，引用
      #pack 实体=本包投影；缺省 False=零行为变化，信封无新键）；
    - 原目录只读；写面仅 out_path 与 manifest（缺省
      ``<out>.manifest.json``）与 opt-in 侧车。

    返回 {"ok", "pack_path", "manifest_path", "n_files", "total_bytes",
    "pack_sha256", "pack_size_bytes"}（opt-in 时附加
    "crate_metadata_path"）；目录不存在/无文件/缺 zstandard →
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
        return error_envelope([f"战役目录不存在: {src}"], **base)
    try:
        zstandard = _import_zstandard()
    except RuntimeError as exc:
        return error_envelope([str(exc)], **base)
    files = _collect_files(src)
    if not files:
        return error_envelope([f"战役目录无文件（拒绝打空 tar）: {src}"], **base)

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
            return error_envelope([f"tar 成员偏移缺失: {missing_offsets[:5]}"], **base)
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
        crate_path: str | None = None
        if include_crate_metadata:
            # XD-16：crate 自描述侧车（懒导入，共享服务面零环依赖）；
            # 失败=opt-in 交付物缺席，如实报错（pack tar 本身已落盘，
            # 重跑幂等——确定性打包 pack_sha256 逐位一致）。
            from rfauto.service.reproducibility_service import build_crate_metadata
            crate = build_crate_metadata(src, pack_manifest=manifest)
            if not crate.get("ok"):
                return error_envelope(
                    [f"crate 元数据构建失败: {crate.get('errors')}"], **base)
            crate_path_obj = Path(str(out) + ".crate-metadata.json")
            crate_path_obj.write_text(
                json.dumps(crate, ensure_ascii=False, indent=2),
                encoding="utf-8")
            crate_path = str(crate_path_obj)
        fields = {
            "n_files": len(files),
            "total_bytes": total,
            "pack_sha256": pack_sha,
            "pack_size_bytes": out.stat().st_size,
            **base,
        }
        if crate_path is not None:
            fields["crate_metadata_path"] = crate_path
        return ok_envelope(**fields)
    except Exception as exc:
        return error_envelope([f"打包失败: {exc}"], **base)
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)


def _decompress_pack(pack_path: Path, tmp_tar: str) -> str | None:
    """zstd 流式解压到临时 tar；失败返回错误描述（None=成功）。

    收窄（AU-3①）：预期异常面 = (OSError, zstandard.ZstdError)——文件读
    写/缺失 OSError，包体损坏 ZstdError 家族；其余异常如实上抛给外层
    信封（verify/restore 的 ok=False 兜底）留痕，不再折叠成"包体损坏"。
    """
    zstandard = _import_zstandard()
    dctx = zstandard.ZstdDecompressor()
    try:
        with open(pack_path, "rb") as src, open(tmp_tar, "wb") as dst:
            dctx.copy_stream(src, dst)
    except (OSError, zstandard.ZstdError) as exc:
        return f"解压失败（包体损坏?）: {exc}"
    return None


def _load_manifest(manifest_path: Path) -> tuple[dict[str, Any] | None,
                                                 str | None]:
    """读偏移清单；格式不符/字段缺失返回错误描述。

    收窄（AU-3①）：预期异常面 = (OSError, ValueError)——清单缺失/不可读
    OSError，坏 JSON/坏编码 ValueError 子类；错误描述随返回值外显（信封
    errors），不再吞其余异常类型（上抛由调用面信封兜底）。
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
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
        return error_envelope([f"归档不存在: {pack}"],
                              pack_sha256_ok=False, files=[],
                              n_ok=0, n_fail=0, **base)
    _import_zstandard()  # 缺装显式报缺（解压面）
    manifest, err = _load_manifest(manifest_file)
    if err is not None:
        return error_envelope([err], pack_sha256_ok=False, files=[],
                              n_ok=0, n_fail=0, **base)
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
            return error_envelope([*errors, decompress_err],
                                  pack_sha256_ok=pack_sha_ok, files=[],
                                  n_ok=0, n_fail=0, **base)
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
        if ok:
            return ok_envelope(pack_sha256_ok=pack_sha_ok, files=results,
                               n_ok=len(results) - n_fail, n_fail=n_fail,
                               errors=errors, **base)
        return error_envelope(errors, pack_sha256_ok=pack_sha_ok,
                              files=results,
                              n_ok=len(results) - n_fail, n_fail=n_fail,
                              **base)
    except Exception as exc:
        return error_envelope([*errors, f"校验执行失败: {exc}"],
                              pack_sha256_ok=pack_sha_ok,
                              files=results, n_ok=0,
                              n_fail=sum(1 for r in results if not r["ok"]),
                              **base)
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
        return error_envelope([f"目标目录已存在，拒绝恢复（绝不覆盖）: {target}"], **base)
    if not pack.is_file():
        return error_envelope([f"归档不存在: {pack}"], **base)
    _import_zstandard()  # 缺装显式报缺（解压面）
    manifest, err = _load_manifest(manifest_file)
    if err is not None:
        return error_envelope([err], **base)
    assert manifest is not None
    entries: list[dict[str, Any]] = manifest["files"]
    if not entries:
        return error_envelope(["清单无文件（空归档）"], **base)
    # 相对路径守卫：穿越/绝对路径条目预检拒绝（写面前最后一道防线）
    for entry in entries:
        if _safe_rel_path(str(entry.get("path") or "")) is None:
            return error_envelope([f"清单含非法相对路径条目: {entry.get('path')!r}"], **base)

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
            return error_envelope([*errors, decompress_err], **base)
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
            return error_envelope(errors, **{**base})

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
            return error_envelope(errors, n_files=len(entries),
                                  n_verified=n_verified, total_bytes=total,
                                  **base)
        return ok_envelope(**{"n_files": len(entries), "n_verified": n_verified, "total_bytes": total, **base})
    except Exception as exc:
        return error_envelope([f"恢复失败: {exc}"], **base)
    finally:
        if tmp_tar is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_tar)
