"""lake_compact_service.et_ht_dedup —— ② et/ht 内容寻址去重的 service 包装。

自 service/lake_compact_service.py 单文件巨石按职责域拆分（aurora_h W3-S1，
T2 范式/AU-1 工艺）：代码体自原节「② et/ht 去重的 service 包装」逐字节
搬迁（plan 纯读扫描 / apply 走 infra 原语，原语在 infra/lake_blob_store），
零逻辑改动；保护面扫描自 retention 域单向导入。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import (
    _meta_file,
    _norm,
    _norm_under,
)
from .retention import (
    extract_pointer_dirs,
)

# ---------------------------------------------------------------------------
# ② et/ht 去重的 service 包装（plan 纯读 / apply 走 infra 原语）
# ---------------------------------------------------------------------------

def _inflight_dir_norms(root: Path) -> set[str]:
    """完全无 meta 的子树目录集（在跑/半途 #144 形态，归一键）。

    口径：目录自身无 meta **且**子树内无任何 meta（全 inflight 子树）才
    入集——meta 容器战役（无 meta 但其下 run 点有 meta）不算 inflight，
    其已落盘 run 点的产物正常参与去重；run 点无 meta（#144 在跑形态）
    整子树跳过。根自身不计。
    """
    out: set[str] = set()
    root_norm = _norm(root)

    def visit(d: Path) -> bool:
        """返回子树是否完全无 meta；完全无 meta 的子树目录入 out。"""
        has_meta = _meta_file(d) is not None
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir()
                              and not p.name.startswith(".")
                              and p.name != "__pycache__")
        except OSError:
            children = []
        child_all_inflight = all(visit(c) for c in children)
        inflight = (not has_meta) and child_all_inflight
        if inflight and _norm(d) != root_norm:
            out.add(_norm(d))
        return inflight

    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for child in children:
        visit(child)
    return out


def plan_et_ht_dedup(
    runs_root: str | Path = "runs",
    *,
    min_age_h: float = 24.0,
    pointer_sources: list[tuple[str | Path, str]] | None = None,
) -> dict[str, Any]:
    """全湖 et/ht 去重规划（纯读：逐文件 sha256 分组统计，零写）。

    保护口径与 apply 同源（宁保守）：指针源命中面 + 在跑/半途（无 meta
    祖先 #144）+ mtime 距今不足 min_age_h 的文件，全部跳过并如实计数。

    Returns:
        dict: {"ok", "n_files", "total_bytes", "n_unique", "n_dup_files",
        "bytes_dup_total"（重复面字节，去重上限收益）, "n_protected",
        "n_inflight", "errors"}
    """
    from rfauto.infra.lake_blob_store import DEDUP_KINDS, sha256_of_file

    root = Path(runs_root).resolve()
    base: dict[str, Any] = {"runs_root": str(root)}
    if not root.is_dir():
        return error_envelope([f"runs 根不存在: {root}"], **base)
    protected = set(extract_pointer_dirs(root, pointer_sources).keys())
    inflight = _inflight_dir_norms(root)
    now = time.time()
    fresh_cut = max(0.0, min_age_h) * 3600.0
    store_norm = _norm(root / ".blob_store")
    groups: dict[str, int] = {}
    group_bytes: dict[str, int] = {}
    n_files = 0
    total_bytes = 0
    n_protected = 0
    n_fresh = 0
    errors: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames
                       if _norm(here / d) != store_norm]
        here_norm = _norm(here)
        skip_dir = here_norm in inflight or _norm_under(here_norm, inflight) \
            or here_norm in protected or _norm_under(here_norm, protected)
        for name in filenames:
            suffix = os.path.splitext(name)[1].lower().lstrip(".")
            if suffix not in DEDUP_KINDS:
                continue
            path = here / name
            if skip_dir:
                n_protected += 1
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if now - st.st_mtime < fresh_cut:
                n_fresh += 1
                continue
            digest = sha256_of_file(path)
            if digest is None:
                errors.append(f"sha256 不可读: {path}")
                continue
            n_files += 1
            total_bytes += st.st_size
            groups[digest] = groups.get(digest, 0) + 1
            group_bytes[digest] = st.st_size
    n_dup_files = sum(c - 1 for c in groups.values() if c > 1)
    bytes_dup = sum((c - 1) * group_bytes[d]
                    for d, c in groups.items() if c > 1)
    return ok_envelope(
        n_files=n_files, total_bytes=total_bytes, n_unique=len(groups),
        n_dup_files=n_dup_files, bytes_dup_total=bytes_dup,
        n_protected=n_protected, n_inflight_dirs=len(inflight),
        n_too_fresh=n_fresh,
        errors=errors[:50], **base)


def apply_et_ht_dedup(
    runs_root: str | Path = "runs",
    *,
    min_age_h: float = 24.0,
    manifest_path: str | Path | None = None,
    pointer_sources: list[tuple[str | Path, str]] | None = None,
) -> dict[str, Any]:
    """全湖 et/ht 去重执行（**破坏性**——CLI --apply 且 XD-5 互锁后可达）。

    受保护面零触碰：指针源命中目录 + 在跑/半途（无 meta 祖先，#144）+
    mtime 新近文件一律跳过（infra 层逐文件跳过+如实计数）。
    """
    from rfauto.infra.lake_blob_store import blob_store_root, dedup_tree_et_ht

    root = Path(runs_root).resolve()
    protected = set(extract_pointer_dirs(root, pointer_sources).keys())
    protected |= _inflight_dir_norms(root)
    result = dedup_tree_et_ht(
        root, blob_store_root(root), protected_norm=frozenset(protected),
        min_age_h=min_age_h, manifest_path=manifest_path)
    return result
