"""lake_compact_service.reversible —— ①b h5 保留的可逆执行面（blob 化+回填+清退）。

自 service/lake_compact_service.py 单文件巨石按职责域拆分（架构批 W3-S1，
T2 范式/AU-1 工艺）：代码体自原节「①b h5 保留策略的可逆执行面」逐字节
搬迁（W6-G 用户豁免放量：内容寻址 blob store+manifest 审计+观察窗，
禁裸删），零逻辑改动；保护面扫描自 retention 域单向导入。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import (
    _git_head_short,
    _norm,
    _repo_root_guess,
)
from .retention import (
    _chain_protected,
    _nearest_meta_dir,
    extract_pointer_dirs,
)

# ---------------------------------------------------------------------------
# ①b h5 保留策略的可逆执行面（W6-G 用户豁免放量：blob 化+manifest 审计，
#    禁裸删——同卷 move 进内容寻址 blob store，观察窗内可逐条回填恢复）
# ---------------------------------------------------------------------------

#: 可逆 compact manifest 格式标识（schema 演进锚）
REVERSIBLE_MANIFEST_FORMAT = "rfauto-lake-h5-compact-reversible-v1"

#: h5 在 blob store 内的 kind 目录（与 et/ht 同布局惯例：{kind}/<sha256 前 16>）
H5_BLOB_KIND = "h5"

#: 缺省观察窗天数（W6-G 用户裁决：30 天观察窗后 purge 才落物理释放）
DEFAULT_OBSERVATION_DAYS = 30


def _blob_path_for(store: Path, digest: str) -> Path:
    return store / H5_BLOB_KIND / digest[:16]


def _move_into_blob(target: Path, blob: Path, digest: str) -> tuple[str, str | None]:
    """把 target 原子移入 blob 位（同卷 rename 零拷贝；数据零丢失时序）。

    返回 (mode, error)：mode ∈ moved / dedup_existing / copied；error 非 None
    表示 target 原样保留未动。blob 已存在（同内容寻址命中）时只核 size 后
    删原路径——内容寻址 blob 视为不可变，绝不覆盖。
    """
    from rfauto.infra.lake_blob_store import sha256_of_file

    t_size = target.stat().st_size
    if blob.exists():
        try:
            b_size = blob.stat().st_size
        except OSError as exc:
            return "kept", f"blob 不可读（保留原样）: {exc}"
        if b_size != t_size:
            return "kept", (f"blob 与目标 size 不符（疑似哈希碰撞/损坏，"
                            f"保留原样不覆盖）: {blob}")
        try:
            target.unlink()
            return "dedup_existing", None
        except OSError as exc:
            return "kept", f"原路径移除失败: {exc}"
    blob.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(target, blob)
        return "moved", None
    except OSError:
        # 跨卷兜底：拷贝到临时名 → sha 复核 → 原子就位 → 删原路径
        tmp = blob.with_name(blob.name + ".tmp")
        try:
            shutil.copyfile(target, tmp)
            if sha256_of_file(tmp) != digest:
                tmp.unlink(missing_ok=True)
                return "kept", "跨卷拷贝 sha 复核不符（保留原样）"
            os.replace(tmp, blob)
        except OSError as exc:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            return "kept", f"跨卷拷贝失败（保留原样）: {exc}"
        try:
            target.unlink()
            return "copied", None
        except OSError as exc:
            return "kept", f"拷贝就位后原路径移除失败: {exc}"


def apply_h5_retention_reversible(
    plan: dict[str, Any],
    *,
    manifest_path: str | Path,
    runs_root: str | Path | None = None,
    blob_store: str | Path | None = None,
    operation_commit: str | None = None,
    min_age_h: float = 24.0,
    observation_days: int = DEFAULT_OBSERVATION_DAYS,
) -> dict[str, Any]:
    """h5 保留策略的**可逆**执行（W6-G 用户豁免放量面；禁裸删）。

    与 ``apply_h5_retention``（unlink 直删）不同：逐文件 sha256 → 同卷
    move 进内容寻址 blob store（``<store>/h5/<sha256 前 16>``）→ manifest
    逐条审计（相对路径+sha+blob 映射）。run 目录树即时缩容（bytes_freed
    与 plan 对账），物理空间在观察窗结束 purge 后落全量释放（30 天观察窗
    注记写进 manifest：回填路径+恢复/清退命令一行）。恢复=``restore_h5_
    from_manifest``（dry-run 可逐条 sha 回放核验）；清退=``purge_blobs_
    from_manifest``。

    安全面（与直删版同源加强）：删除清单∩保护面=∅ 断言（违反零动）；
    豁免行二次核验（豁免子树标记+子树包含关系+指针/名字保护链+min_age
    新近）；meta 行保留 meta 在档复核。blob 视为不可变，同内容二次命中
    只删原路径不覆盖（dedup_existing 如实记 mode）。
    """
    from rfauto.infra.lake_blob_store import blob_store_root, sha256_of_file

    root = Path(runs_root) if runs_root is not None \
        else Path(str(plan.get("runs_root") or "."))
    root = root.resolve()
    base: dict[str, Any] = {"runs_root": str(root),
                            "manifest_path": str(manifest_path)}
    rows = plan.get("delete")
    if not isinstance(rows, list):
        return error_envelope(["plan 无 delete 清单（先 plan_h5_retention）"],
                              **base)
    audit = plan.get("golden_rewrite_audit") or {}
    if audit.get("violations"):
        return error_envelope(
            ["golden 零改写断言失败（删除清单命中保护面，零动拒绝）: "
             + "; ".join(str(v) for v in audit["violations"][:10])],
            **base)
    plan_exempt = plan.get("exempt_subtrees") or []
    store = Path(blob_store) if blob_store is not None \
        else blob_store_root(root)
    store_norm = _norm(store)
    commit = operation_commit if operation_commit is not None \
        else _git_head_short(_repo_root_guess())
    pointers = extract_pointer_dirs(root)
    now = time.time()
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    n_moved = 0
    n_dedup = 0
    bytes_freed = 0
    bytes_retained = 0
    applied_at = datetime.now(timezone.utc)
    try:
        obs_days = max(0, int(observation_days))
    except (TypeError, ValueError):
        obs_days = DEFAULT_OBSERVATION_DAYS
    purge_after = applied_at + timedelta(days=obs_days)
    mtext = str(manifest_path)
    purge_date = purge_after.date().isoformat()

    def _flush_manifest() -> None:
        """崩溃安全：每条 move 落地即重写 manifest（path→blob 映射不断链）。"""
        manifest = {
            "format": REVERSIBLE_MANIFEST_FORMAT,
            "created_at": applied_at.isoformat(),
            "runs_root": str(root),
            "tier": str(plan.get("tier") or ""),
            "n_entries": len(entries),
            "bytes_freed": bytes_freed,
            "bytes_retained": bytes_retained,
            "operation_commit": commit,
            "blob_store_rel": ".blob_store",
            "exempt_subtrees": list(plan_exempt),
            "observation_window": {
                "days": obs_days,
                "applied_at": applied_at.isoformat(),
                "purge_after": purge_date,
                "backfill_path": "runs/.blob_store/h5",
                "restore_command": (
                    ".venv\\Scripts\\python.exe -c \"from rfauto.service."
                    "lake_compact_service import restore_h5_from_manifest; "
                    f"print(restore_h5_from_manifest(r'{mtext}'))\""),
                "purge_command": (
                    ".venv\\Scripts\\python.exe -c \"from rfauto.service."
                    "lake_compact_service import purge_blobs_from_manifest; "
                    f"print(purge_blobs_from_manifest(r'{mtext}'))\""),
                "note": (f"可逆豁免放量（禁裸删）：内容已 blob 化于 "
                         f"runs/.blob_store/h5，观察窗 {obs_days} 天内可按 "
                         "restore_command 逐条回填；窗满（" + purge_date
                         + "）无回归再执行 purge_command 落物理释放。"),
            },
            "entries": entries,
        }
        mpath = Path(manifest_path)
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    for row in rows:
        rel = str(row.get("path") or "")
        target = root / rel
        if not target.is_file():
            errors.append(f"目标不存在（跳过）: {rel}")
            continue
        # 写面前收口：目标必须真在 runs 根下（防清单被篡改/路径穿越）
        if not _norm(target).startswith(_norm(root) + os.sep):
            errors.append(f"目标越出 runs 根（拒绝）: {rel}")
            continue
        exempt_hit = str(row.get("exempt_subtree") or "")
        if exempt_hit:
            # 豁免行二次核验：标记必须与 plan 回显一致 + 路径确在子树内
            if exempt_hit not in plan_exempt:
                errors.append(f"豁免子树标记与 plan 回显不符（拒绝）: {rel}")
                continue
            if not (rel == exempt_hit
                    or rel.startswith(exempt_hit + "/")):
                errors.append(f"目标越出豁免子树（拒绝）: {rel}")
                continue
            if _chain_protected(target.parent, root, pointers) is not None:
                errors.append(f"目标命中保护链（拒绝）: {rel}")
                continue
            try:
                if now - target.stat().st_mtime < max(0.0, min_age_h) * 3600:
                    errors.append(f"目标资格漂移（min_age 内新近，拒绝）: {rel}")
                    continue
            except OSError as exc:
                errors.append(f"{rel}: 不可读 {exc}")
                continue
        else:
            # meta 行：meta 在档复核（plan→apply 窗口内消失=在跑嫌疑 #144）
            if _nearest_meta_dir(target, root) is None:
                errors.append(
                    f"删除目标 meta 在 plan 后消失（#144 在跑嫌疑，拒绝）: {rel}")
                continue
            if _chain_protected(root / str(row.get("run_dir") or rel),
                                root, pointers) is not None:
                errors.append(f"删除目标命中保护面（拒绝）: {rel}")
                continue
        digest = sha256_of_file(target)
        if digest is None:
            errors.append(f"sha256 不可读（跳过）: {rel}")
            continue
        blob = _blob_path_for(store, digest)
        if not _norm(blob).startswith(store_norm + os.sep):
            errors.append(f"blob 位越出 store（拒绝）: {rel}")
            continue
        size = target.stat().st_size
        mode, err = _move_into_blob(target, blob, digest)
        if err is not None:
            errors.append(f"{rel}: {err}")
            continue
        try:
            if blob.stat().st_size != size:
                raise OSError("move 后 size 复核不符")
        except OSError as exc:
            errors.append(f"{rel}: move 后复核失败 {exc}")
            continue
        if mode == "dedup_existing":
            n_dedup += 1
        else:
            n_moved += 1
        bytes_freed += size
        bytes_retained += size
        entries.append({
            "path": rel, "run_dir": str(row.get("run_dir") or ""),
            "size": size, "sha256": digest,
            "blob": f"{H5_BLOB_KIND}/{digest[:16]}",
            "mode": mode, "reason": str(row.get("reason") or "none"),
            "exempt_subtree": exempt_hit or None,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "operation_commit": commit,
        })
        _flush_manifest()
    _flush_manifest()  # 收尾兜底（空清单/尾条目后状态一致）
    result: dict[str, Any] = {
        "n_deleted": n_moved + n_dedup,
        "n_moved": n_moved,
        "n_dedup_existing": n_dedup,
        "bytes_freed": bytes_freed,
        "bytes_retained": bytes_retained,
        "blob_store": str(store),
        "purge_after": purge_after.date().isoformat(),
        **base}
    if errors:
        return error_envelope(errors, **result)
    return ok_envelope(errors=[], **result)


def _resolve_manifest_targets(
    manifest: dict[str, Any],
    manifest_path: Path,
    runs_root: str | Path | None,
    out: dict[str, Any],
) -> tuple[Path, Path] | None:
    """manifest → (runs 根, blob store 根) 解析；失败时 errors 已记账。"""
    rel_store = str(manifest.get("blob_store_rel") or ".blob_store")
    base_str = str(runs_root) if runs_root is not None \
        else str(manifest.get("runs_root") or ".")
    base = Path(base_str)
    if not base.is_dir():
        out["errors"].append(
            f"runs 根不可达（传 runs_root 或自仓根运行）: {base}")
        return None
    return base, base / rel_store


def restore_h5_from_manifest(
    manifest_path: str | Path,
    *,
    runs_root: str | Path | None = None,
    target_root: str | Path | None = None,
    verify: bool = True,
    dry_run: bool = False,
    max_errors: int = 50,
) -> dict[str, Any]:
    """按可逆 compact manifest 回填/核验（恢复面；缺省 dry_run=False 真回填）。

    ``dry_run=True``：零写面——逐条核 blob 在档 +（verify=True 时）blob sha
    与 manifest 逐位一致（判据"manifest 逐条 sha 可回放"的本体）。
    ``target_root`` 给出时回填到新目录（模拟重建，不触碰原湖——测试面口径）；
    原位回填时 dest 已在且 sha 一致记 already_restored，不符记 error 拒绝
    覆盖。逐条失败记 error 继续（如实报告，不静默丢条目）。
    """
    from rfauto.infra.lake_blob_store import sha256_of_file

    out: dict[str, Any] = {"ok": False, "n_entries": 0, "n_verified": 0,
                           "n_restored": 0, "n_already": 0,
                           "n_missing_blob": 0, "n_sha_mismatch": 0,
                           "n_skipped": 0, "dry_run": bool(dry_run),
                           "errors": []}
    mpath = Path(manifest_path)
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["errors"].append(f"manifest 读取/解析失败: {exc}")
        return out
    if not isinstance(manifest, dict) \
            or manifest.get("format") != REVERSIBLE_MANIFEST_FORMAT:
        out["errors"].append(
            f"manifest 格式不符（期望 {REVERSIBLE_MANIFEST_FORMAT}）")
        return out
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        out["errors"].append("manifest 缺 entries 段")
        return out
    resolved = _resolve_manifest_targets(manifest, mpath, runs_root, out)
    if resolved is None:
        return out
    base, store = resolved
    if target_root is not None:
        base = Path(target_root)
    out["n_entries"] = len(entries)
    for entry in entries:
        rel = str(entry.get("path") or "")
        digest = str(entry.get("sha256") or "")
        blob_rel = str(entry.get("blob") or "")
        if not rel or not digest:
            out["n_skipped"] += 1
            out["errors"].append(f"条目缺 path/sha256: {entry!r}"[:200])
            continue
        blob = store / blob_rel if blob_rel             else _blob_path_for(store, digest)
        if not blob.is_file():
            out["n_missing_blob"] += 1
            out["errors"].append(f"blob 缺失: {rel}（{blob.name}）")
            continue
        if verify:
            actual = sha256_of_file(blob)
            if actual is None:
                out["n_skipped"] += 1
                out["errors"].append(f"blob 不可读: {rel}")
                continue
            if actual != digest:
                out["n_sha_mismatch"] += 1
                out["errors"].append(f"blob sha 与 manifest 不符: {rel}")
                continue
        out["n_verified"] += 1
        if dry_run:
            continue
        dest = base / rel
        try:
            if dest.is_file():
                cur = sha256_of_file(dest)
                if cur == digest:
                    out["n_already"] += 1
                    continue
                out["n_skipped"] += 1
                out["errors"].append(
                    f"现文件存在且 sha 不符（拒绝覆盖）: {rel}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(blob, dest)
            except OSError:
                shutil.copyfile(blob, dest)
        except OSError as exc:
            out["n_skipped"] += 1
            if len(out["errors"]) < max_errors:
                out["errors"].append(f"{rel}: 回填失败 {exc}")
            continue
        back = sha256_of_file(dest)
        if back != digest:
            out["n_skipped"] += 1
            out["errors"].append(f"{rel}: 回填后 sha 复核不符")
            continue
        out["n_restored"] += 1
    shape_ok = (out["n_missing_blob"] == 0 and out["n_sha_mismatch"] == 0
                and not any("失败" in e or "不符" in e or "缺" in e
                            for e in out["errors"]))
    out["ok"] = bool(shape_ok and out["n_verified"] == out["n_entries"]
                     and (dry_run or
                          out["n_restored"] + out["n_already"]
                          == out["n_entries"]))
    return out


def purge_blobs_from_manifest(
    manifest_path: str | Path,
    *,
    runs_root: str | Path | None = None,
    max_errors: int = 50,
) -> dict[str, Any]:
    """观察窗满后的 blob 清退（**破坏性**——物理释放落点；用户窗显式执行）。

    仅删 manifest 点名 blob（内容寻址位，逐条核在 store 目录内），run
    目录树零触碰。 Returns: {"ok", "n_entries", "n_purged",
    "bytes_released", "n_missing", "errors"}。
    """
    out: dict[str, Any] = {"ok": False, "n_entries": 0, "n_purged": 0,
                           "bytes_released": 0, "n_missing": 0, "errors": []}
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["errors"].append(f"manifest 读取/解析失败: {exc}")
        return out
    if not isinstance(manifest, dict) \
            or manifest.get("format") != REVERSIBLE_MANIFEST_FORMAT:
        out["errors"].append(
            f"manifest 格式不符（期望 {REVERSIBLE_MANIFEST_FORMAT}）")
        return out
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        out["errors"].append("manifest 缺 entries 段")
        return out
    resolved = _resolve_manifest_targets(manifest, Path(manifest_path),
                                         runs_root, out)
    if resolved is None:
        return out
    _base, store = resolved
    store_norm = _norm(store)
    out["n_entries"] = len(entries)
    for entry in entries:
        digest = str(entry.get("sha256") or "")
        blob_rel = str(entry.get("blob") or "")
        blob = (store / blob_rel) if blob_rel else _blob_path_for(store, digest)
        if not _norm(blob).startswith(store_norm + os.sep):
            out["errors"].append(f"blob 位越出 store（拒绝）: {blob_rel}")
            continue
        try:
            size = blob.stat().st_size
        except OSError:
            out["n_missing"] += 1
            continue
        try:
            blob.unlink()
        except OSError as exc:
            if len(out["errors"]) < max_errors:
                out["errors"].append(f"{blob_rel}: 清退失败 {exc}")
            continue
        out["n_purged"] += 1
        out["bytes_released"] += size
    out["ok"] = not out["errors"]
    return out
