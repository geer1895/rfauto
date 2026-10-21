"""lake_compact_service.common —— 跨域共用 helpers（runs 树遍历与保护面）。

自 service/lake_compact_service.py 单文件巨石按职责域拆分（架构批 W3-S1，
T2 范式/AU-1 工艺）：本域持有归一/JSON 读取/git 探针/保护前缀判定等共用
helpers 与 meta 文件名常量，et_ht_dedup/retention/reversible/vf_summary
各域从此单向导入（包内零环）。代码体自原节「共用：runs 树遍历与保护面」
及 _norm_under 逐字节搬迁，零逻辑改动。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 共用：runs 树遍历与保护面
# ---------------------------------------------------------------------------

#: meta 文件名（lake_service._META_NAMES 同口径，就地重复以免跨模块私引）
_META_NAMES = ("meta.json", "run_meta.json")


def _meta_file(run_dir: Path) -> Path | None:
    for name in _META_NAMES:
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _norm(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _git_head_short(repo: str | Path | None = None) -> str:
    """当前 HEAD 短 SHA（best-effort #105；失败空串不抛穿）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30,
            cwd=str(repo) if repo else None)
        sha = (out.stdout or "").strip()
        return sha if out.returncode == 0 and sha else ""
    except Exception:
        return ""


def _repo_root_guess() -> Path:
    return Path(__file__).resolve().parents[3]


def _dir_size_bytes(run_dir: Path) -> int:
    total = 0
    for current, _dirs, filenames in os.walk(run_dir):
        for name in filenames:
            try:
                total += (Path(current) / name).stat().st_size
            except OSError:
                continue
    return total


def _norm_under(norm: str, protected_norms: set[str]) -> bool:
    """norm 是否命中保护集（精确相等或位于某保护目录之下）。"""
    return any(norm == p or norm.startswith(p.rstrip(os.sep) + os.sep)
               for p in protected_norms)
