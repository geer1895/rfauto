"""lake_blob_store —— et/ht 内容寻址去重的 infra 原语（RB-WN-1 ②）。

blob store 布局（spec sa_specs2 §五②）：``<store_root>/{et,ht}/<sha256 前
16>``；原位文件替换为**硬链接**（同卷零数据块增量；不支持硬链接的回退=留
一份+其余删+manifest 记映射，仅批量面支持回退，增量钩子遇不可链接一律原
样跳过——求解收尾路径绝不破坏产物）。

放 infra 层的理由：增量写点在 adapters/openems_solver·rotation 的产物收尾
段（spec 原文），而分层契约 adapters→infra 方向合法、adapters→service 非
法——去重原语必须下沉 infra，service 批量面（lake_compact_service）与
adapter 增量钩子共用同一实现。

数据安全时序（零丢失设计）：任何原位替换都是**先建 blob 侧硬链接（数据
获得第二引用）→ 校验 st_nlink≥2 → 再删原路径 → 再从 blob 链接回原路径**；
末步失败兜底 shutil.copyfile（同 inode 源，字节必一致）。manifest 记
dedup 映射（重建原始目录形态可逆：restore 按映射从 blob 链接回填）。

无 __all__：公开 API 快照（DP-17 check_public_api）按 __all__ 登记，本件
保持无 __all__ 即不入快照（共享计数面零碰，W3-A 席位纪律）。

增量钩子 ``maybe_dedup_workdir_et_ht`` 默认**关闭**（env
``RFAUTO_LAKE_DEDUP_ET_HT`` 真值才启用）——对 runs/ 既有产物的任何写面
都属破坏性语义，放量等用户窗（W3-A criteria 预声明）；关闭时调用零副作用，
缺省求解路径行为逐字节不变。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

#: manifest 格式标识（schema 演进锚；pack_campaign.PACK_FORMAT 同惯例）
BLOB_DEDUP_FORMAT = "rfauto-lake-etht-dedup-v1"

#: 缺省 blob store 落点（runs/ 已整体 gitignore）
DEFAULT_BLOB_STORE_NAME = ".blob_store"

#: 参与去重的引擎时间序列产物后缀（spec：et/ht；#279——et/ht 是激励信号
#: 时间序列，同激励参数模板组内跨模板逐字节相同，去重即内容寻址合并）
DEDUP_KINDS: tuple[str, ...] = ("et", "ht")

#: blob 键取 sha256 前 16 hex（spec 原文；16 hex=64bit 抗碰足够湖量级）
_BLOB_KEY_LEN = 16

_TRUTHY = {"1", "true", "yes", "on"}


def sha256_of_file(path: str | Path, _buf_size: int = 1 << 20) -> str | None:
    """文件流式 sha256（hex）；不可读返回 None（与 dag_cache.file_sha256 的
    空串口径区分——None 让上层把"读不了"与"空文件"分开处理，不吞错误）。"""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(_buf_size):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def blob_store_root(runs_root: str | Path) -> Path:
    """缺省 blob store 根：``<runs_root>/.blob_store``。"""
    return Path(runs_root) / DEFAULT_BLOB_STORE_NAME


def blob_rel_path(kind: str, digest: str) -> str:
    """blob 相对 store 根的 posix 路径：``<kind>/<sha256[:16]>``。"""
    return f"{kind}/{digest[:_BLOB_KEY_LEN]}"


def _iter_kind_files(root: Path, kinds: tuple[str, ...],
                     skip_below: frozenset[str]) -> list[Path]:
    """递归收集目标后缀文件（确定性排序）；``skip_below``（归一小写绝对
    路径）之下的子树整枝剪掉（blob store 自身/受保护面）。"""
    found: list[Path] = []
    suffixes = {f".{k}" for k in kinds}
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        keep: list[str] = []
        for d in dirnames:
            child = here / d
            if os.path.normcase(str(child.resolve())) not in skip_below:
                keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            if os.path.splitext(name)[1].lower() in suffixes:
                found.append(here / name)
    found.sort()
    return found


def _replace_with_hardlink(target: Path, blob: Path) -> tuple[str, str | None]:
    """把 target 原位替换为指向 blob 的硬链接（数据零丢失时序）。

    返回 (mode, error)：mode="hardlink" 成功；mode="copy_fallback" 末步
    链接失败已用字节拷贝兜底；error 非 None 表示文件原样保留未动（含
    blob 建链失败的场合——数据仍在 target，绝不先删后建）。
    """
    if not blob.exists():
        # 第一引用：直接把 target 链接成 blob（同 inode，零拷贝）
        try:
            blob.parent.mkdir(parents=True, exist_ok=True)
            os.link(target, blob)
        except OSError as exc:
            return "skipped", f"blob 建链失败（跨卷/不支持?）: {exc}"
        if os.stat(blob).st_nlink < 2:
            return "skipped", "blob 建链后 nlink<2（语义不符，放弃替换）"
    # 数据已获第二引用，原路径可安全移除
    try:
        target.unlink()
    except OSError as exc:
        return "skipped", f"原路径移除失败: {exc}"
    try:
        os.link(blob, target)
        return "hardlink", None
    except OSError:
        try:
            shutil.copyfile(blob, target)
            return "copy_fallback", None
        except OSError as exc:
            # 最后兜底也失败：数据仍在 blob，从 blob 复原一份（尽力而为）
            try:
                shutil.copyfile(blob, target)
                return "copy_fallback", f"链接失败已拷贝复原: {exc}"
            except OSError:
                # 原路径已 unlink 且复原失败：数据仅在 blob——返回专用 mode
                # 让调用方仍写 manifest 条目（lost_at_path；可逆性 manifest
                # 不断链，审查 P2-3 2026-10-05）
                return ("lost_at_path",
                        f"替换失败且复原失败（数据在 blob，路径待复原）: {exc}")


def link_workdir_et_ht(
    work_dir: str | Path,
    store_root: str | Path,
    *,
    kinds: tuple[str, ...] = DEDUP_KINDS,
) -> dict[str, Any]:
    """单工作目录（或其子树）的 et/ht 落 blob store 增量去重（spec ②增量面）。

    求解收尾段调用；**best-effort**：逐文件失败只记 error 不抛穿——观测/
    优化面不得成为求解主路径故障点（#105）。仅做硬链接（同卷）；不支持
    硬链接的文件原样保留（增量钩子不做"留一份+删其余"回退，回退是批量面
    语义——钩子所在路径旁绝无删产物许可）。

    Returns:
        dict: {"n_scanned", "n_linked", "n_already", "n_skipped",
        "bytes_saved", "errors"}（bytes_saved=被替换文件的原 size 和，
        硬链接下即省下的目录项级冗余计账口径）
    """
    work = Path(work_dir)
    store = Path(store_root)
    out: dict[str, Any] = {"n_scanned": 0, "n_linked": 0, "n_already": 0,
                           "n_skipped": 0, "bytes_saved": 0, "errors": []}
    if not work.is_dir():
        out["errors"].append(f"工作目录不存在: {work}")
        return out
    files = _iter_kind_files(work, kinds,
                             frozenset({os.path.normcase(str(store.resolve()))}))
    for path in files:
        out["n_scanned"] += 1
        digest = sha256_of_file(path)
        if digest is None:
            out["n_skipped"] += 1
            out["errors"].append(f"sha256 不可读，跳过: {path}")
            continue
        blob = store / Path(blob_rel_path(path.suffix.lstrip(".").lower(),
                                          digest))
        already = False
        try:
            already = blob.exists() and _same_inode(path, blob)
        except OSError:
            already = False
        if already:
            out["n_already"] += 1
            continue
        size = path.stat().st_size
        _mode, err = _replace_with_hardlink(path, blob)
        if err is not None:
            out["n_skipped"] += 1
            out["errors"].append(f"{path.name}: {err}")
            continue
        out["n_linked"] += 1
        out["bytes_saved"] += size
    return out


def _same_inode(a: Path, b: Path) -> bool:
    try:
        return os.path.samestat(os.stat(a), os.stat(b))
    except OSError:
        return False


def maybe_dedup_workdir_et_ht(
    work_dir: str | Path,
    *,
    store_root: str | Path | None = None,
    env_var: str = "RFAUTO_LAKE_DEDUP_ET_HT",
) -> dict[str, Any] | None:
    """env 门控的增量去重钩子（openems_solver/rotation 产物收尾段调用）。

    env ``RFAUTO_LAKE_DEDUP_ET_HT`` 非真值 → 立即返回 None（**零副作用**，
    缺省路径逐字节不变）。store 缺省 ``<cwd>/runs/.blob_store``（生产驱动
    自仓根运行，与湖索引 runs 相对缺省同惯例；可用
    ``RFAUTO_LAKE_BLOB_STORE`` 覆盖）。异常全吞进 errors（#105）。
    """
    if str(os.environ.get(env_var, "")).strip().lower() not in _TRUTHY:
        return None
    root = store_root
    if root is None:
        env_store = os.environ.get("RFAUTO_LAKE_BLOB_STORE", "")
        root = Path(env_store) if env_store else blob_store_root("runs")
    try:
        return link_workdir_et_ht(work_dir, root)
    except Exception as exc:  # 钩子绝不抛穿求解收尾（#105）
        return {"n_scanned": 0, "n_linked": 0, "n_already": 0,
                "n_skipped": 0, "bytes_saved": 0,
                "errors": [f"增量去重钩子异常（已吞）: {exc}"]}


def dedup_tree_et_ht(
    runs_root: str | Path,
    store_root: str | Path,
    *,
    kinds: tuple[str, ...] = DEDUP_KINDS,
    protected_norm: frozenset[str] = frozenset(),
    min_age_h: float = 24.0,
    manifest_path: str | Path | None = None,
    max_errors: int = 50,
) -> dict[str, Any]:
    """全湖扫描去重（spec ②存量批）：重复 et/ht → blob store 单份+全体硬链接。

    - 逐文件 sha256 分组；同 hash 组内第一路径（排序序）作为 blob 内容源，
      组内全部路径替换为指向 blob 的硬链接；
    - ``protected_norm``（归一绝对路径集，basename 或目录前缀命中即保护）
      之下的文件整枝跳过（golden 零改写红线 #325——硬链接替换虽字节不变，
      但目录项被动了，归档证据面零触碰）；
    - ``min_age_h``：文件 mtime 距今不足该小时数的跳过（并发生产在写面
      防误碰；dry-run 与 apply 同口径预声明）；
    - manifest 缺省 ``<store_root>/dedup_manifest.json``：逐路径映射
      （重建原始目录形态可逆，restore_et_ht_from_manifest 重放）。

    Returns:
        dict: {"ok", "n_scanned", "n_unique", "n_duplicate", "n_linked",
        "n_already", "n_protected", "n_too_fresh", "n_skipped",
        "bytes_dup_total", "bytes_saved", "manifest_path", "errors"}
    """
    root = Path(runs_root)
    store = Path(store_root)
    out: dict[str, Any] = {"ok": False, "n_scanned": 0, "n_unique": 0,
                           "n_duplicate": 0, "n_linked": 0, "n_already": 0,
                           "n_protected": 0, "n_too_fresh": 0,
                           "n_skipped": 0, "bytes_dup_total": 0,
                           "bytes_saved": 0,
                           "manifest_path": str(manifest_path
                                                if manifest_path is not None
                                                else store / "dedup_manifest.json"),
                           "errors": []}
    if not root.is_dir():
        out["errors"].append(f"runs 根不存在: {root}")
        return out
    # 受保护面不剪枝（如实计数 n_protected），逐文件命中即跳过；仅 blob
    # store 自身在 walk 层剪掉（绝不去重 store 内部）。
    files = _iter_kind_files(root, kinds,
                             frozenset({os.path.normcase(str(store.resolve()))}))
    now = time.time()
    fresh_cutoff_s = max(0.0, float(min_age_h)) * 3600.0
    groups: dict[str, list[Path]] = {}
    protected_hit = 0
    for path in files:
        norm = os.path.normcase(str(path.resolve()))
        if _norm_hit(protected_norm, norm):
            protected_hit += 1
            continue
        try:
            if now - path.stat().st_mtime < fresh_cutoff_s:
                out["n_too_fresh"] += 1
                continue
        except OSError:
            out["n_skipped"] += 1
            continue
        digest = sha256_of_file(path)
        if digest is None:
            out["n_skipped"] += 1
            if len(out["errors"]) < max_errors:
                out["errors"].append(f"sha256 不可读，跳过: {path}")
            continue
        out["n_scanned"] += 1
        groups.setdefault(digest, []).append(path)
    out["n_protected"] = protected_hit
    out["n_unique"] = len(groups)
    out["n_duplicate"] = sum(max(0, len(g) - 1) for g in groups.values())

    entries: list[dict[str, Any]] = []
    for digest in sorted(groups):
        paths = groups[digest]
        kind = paths[0].suffix.lstrip(".").lower()
        blob = store / Path(blob_rel_path(kind, digest))
        size = paths[0].stat().st_size
        # 单例且 store 无同内容 blob：零去重收益，原样不动（不做无谓的
        # 目录项翻动）；单例但 blob 已在（跨批共享内容）→ 链接省一份数据块。
        if len(paths) == 1 and not blob.exists():
            continue
        for path in paths:
            try:
                if blob.exists() and _same_inode(path, blob):
                    out["n_already"] += 1
                    entries.append(_entry(root, path, kind, digest, blob,
                                          size, "hardlink"))
                    continue
                mode, err = _replace_with_hardlink(path, blob)
            except OSError as exc:
                mode, err = "skipped", str(exc)
            if err is not None:
                out["n_skipped"] += 1
                if len(out["errors"]) < max_errors:
                    out["errors"].append(f"{path}: {err}")
                if mode == "lost_at_path":
                    # 数据在 blob 但路径缺失：manifest 照写（size 取 blob 实测），
                    # 恢复器可按条目 link 回填（可逆性闭环，审查 P2-3）
                    try:
                        bsize = Path(blob).stat().st_size
                    except OSError:
                        bsize = 0
                    entries.append(_entry(root, path, kind, digest, blob,
                                          bsize, mode))
                continue
            out["n_linked"] += 1
            if len(paths) > 1:
                out["bytes_dup_total"] += size
            if mode == "hardlink":
                out["bytes_saved"] += size
            entries.append(_entry(root, path, kind, digest, blob, size, mode))
    _write_manifest(Path(out["manifest_path"]), root, store, entries, out)
    out["ok"] = True
    return out


def _entry(root: Path, path: Path, kind: str, digest: str, blob: Path,
           size: int, mode: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "kind": kind,
        "sha256": digest,
        "blob": blob.relative_to(_store_of(blob)).as_posix()
        if _store_of(blob) else blob.as_posix(),
        "size": size,
        "mode": mode,
    }


def _store_of(blob: Path) -> Path | None:
    """blob 绝对路径的 store 根（=父的父，{kind}/{key} 两层布局）。"""
    try:
        return blob.resolve().parent.parent
    except OSError:
        return None


def _write_manifest(path: Path, root: Path, store: Path,
                    entries: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    manifest = {
        "format": BLOB_DEDUP_FORMAT,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs_root": str(root),
        "store_root": str(store),
        "kinds": list(DEDUP_KINDS),
        "n_entries": len(entries),
        "stats": {k: v for k, v in stats.items() if k.startswith("n_")
                  or k.startswith("bytes_")},
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _norm_hit(protected_norm: frozenset[str], norm: str) -> bool:
    """归一路径是否命中保护集：精确相等或位于某保护目录之下。"""
    return norm in protected_norm or any(
        norm.startswith(p.rstrip(os.sep) + os.sep) for p in protected_norm)


def restore_et_ht_from_manifest(
    manifest_path: str | Path,
    *,
    runs_root: str | Path | None = None,
    target_root: str | Path | None = None,
    verify_sha: bool = True,
    max_errors: int = 50,
) -> dict[str, Any]:
    """按 dedup manifest 重放，从 blob store 链接回填原始目录布局（可逆性门）。

    ``runs_root`` 缺省读 manifest 记录；``target_root`` 给出时回填到新目录
    （模拟重建，不触碰原湖——测试面口径）；原位回填（target_root=None）时
    逐条校验现文件 sha 与 manifest 一致后才 unlink+relink。逐条失败记
    error 继续（如实报告，不静默丢条目）。

    Returns:
        dict: {"ok", "n_entries", "n_restored", "n_verified",
        "n_missing_blob", "n_skipped", "errors"}
    """
    out: dict[str, Any] = {"ok": False, "n_entries": 0, "n_restored": 0,
                           "n_verified": 0, "n_missing_blob": 0,
                           "n_skipped": 0, "errors": []}
    mpath = Path(manifest_path)
    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out["errors"].append(f"manifest 读取/解析失败: {exc}")
        return out
    if not isinstance(manifest, dict) \
            or manifest.get("format") != BLOB_DEDUP_FORMAT:
        out["errors"].append(
            f"manifest 格式不符（期望 {BLOB_DEDUP_FORMAT}）")
        return out
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        out["errors"].append("manifest 缺 entries 段")
        return out
    base = Path(target_root) if target_root is not None \
        else Path(runs_root) if runs_root is not None \
        else Path(str(manifest.get("runs_root") or "."))
    store = Path(str(manifest.get("store_root") or "."))
    out["n_entries"] = len(entries)
    for entry in entries:
        rel = str(entry.get("path") or "")
        digest = str(entry.get("sha256") or "")
        kind = str(entry.get("kind") or "et")
        if not rel or not digest:
            out["n_skipped"] += 1
            out["errors"].append(f"条目缺 path/sha256: {entry!r}"[:200])
            continue
        blob = store / Path(blob_rel_path(kind, digest))
        dest = base / rel
        if not blob.is_file():
            out["n_missing_blob"] += 1
            out["errors"].append(f"blob 缺失: {blob}")
            continue
        if target_root is None and dest.is_file():
            actual = sha256_of_file(dest)
            if actual is None:
                out["n_skipped"] += 1
                out["errors"].append(f"现文件不可读: {dest}")
                continue
            if verify_sha and actual != digest:
                out["n_skipped"] += 1
                out["errors"].append(
                    f"现文件 sha 与 manifest 不符（拒绝替换）: {dest}")
                continue
            out["n_verified"] += 1
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            os.link(blob, dest)
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
    out["ok"] = not out["errors"]
    return out
