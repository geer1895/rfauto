"""rfauto run-store — run directory management & metadata.

方向 7 可复现基建：provenance 采集（python_version/os/pip_freeze_sha/
solver_versions/optuna_seed），recipe_version 字段支持。
"""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from rfauto.infra.db import RegistryDB, default_registry_db_path

# ---------------------------------------------------------------------------
# Run directory helpers
# ---------------------------------------------------------------------------

def create_run_dir(base_dir: str | Path, run_id: str) -> Path:
    """Create ``<base_dir>/runs/<run_id>/`` with standard sub-directories.

    Returns the run directory path.
    """
    run_dir = Path(base_dir) / "runs" / run_id
    for sub in ("results", "hfss", "ads", "checkpoints"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def snapshot_recipe(run_dir: str | Path, recipe_dict: dict[str, Any]) -> Path:
    """Write *recipe.snapshot.yaml* into *run_dir* and return its path.

    快照只落 run 目录；目标若落在受保护 recipes/ 下由守卫拒绝
    （infra.recipe_guard，配方污染根修）。
    """
    from rfauto.infra.recipe_guard import check_recipe_write_target

    run_dir = Path(run_dir)
    dest = check_recipe_write_target(run_dir / "recipe.snapshot.yaml")
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg = OmegaConf.create(recipe_dict)
    OmegaConf.save(cfg, str(dest))
    return dest


def _git_sha() -> str:
    """Best-effort current git SHA (returns ``'unknown'`` on failure)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Provenance collection（方向 7 可复现基建）
# ---------------------------------------------------------------------------

def _pip_freeze_sha() -> str:
    """Best-effort pip freeze SHA (returns ``'unknown'`` on failure).

    对 venv 中的 pip freeze 输出取 sha256 前 16 位，用于环境指纹锁定。
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze", "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return hashlib.sha256(result.stdout.strip().encode()).hexdigest()[:16]
    except Exception:
        pass
    return "unknown"


def _python_version() -> str:
    """Current Python version string."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _os_info() -> str:
    """OS fingerprint: system + release + machine."""
    return f"{platform.system()} {platform.release()} {platform.machine()}"


def collect_provenance(
    *,
    optuna_seed: int | None = None,
    solver_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Collect full provenance metadata for a run (方向 7).

    Returns a dict with keys: python_version, os, pip_freeze_sha,
    solver_versions, optuna_seed.  All fields are best-effort (never raise).
    """
    return {
        "python_version": _python_version(),
        "os": _os_info(),
        "pip_freeze_sha": _pip_freeze_sha(),
        "solver_versions": solver_versions or {},
        "optuna_seed": optuna_seed,
    }


def load_solver_versions() -> dict[str, str]:
    """Load solver versions from configs/solvers.yaml (best-effort).

    Returns {solver_name: version_or_path} for provenance recording.
    """
    import yaml as _yaml

    versions: dict[str, str] = {}
    # Try configs/solvers.yaml
    for candidate in (
        Path("configs") / "solvers.yaml",
        Path(__file__).parent.parent.parent.parent / "configs" / "solvers.yaml",
    ):
        if candidate.exists():
            try:
                with open(candidate, encoding="utf-8") as f:
                    data = _yaml.safe_load(f) or {}
                for name, cfg in data.items():
                    if isinstance(cfg, dict):
                        exe = cfg.get("exe_path", "")
                        versions[name] = str(exe) if exe else name
                    else:
                        versions[name] = str(cfg)
            except Exception:
                pass
            break
    # Always record openEMS binding version if importable
    try:
        import openems  # type: ignore[import-untyped]
        versions["openems_binding"] = getattr(openems, "__version__", "unknown")
    except ImportError:
        pass
    return versions


# ---------------------------------------------------------------------------
# meta.json
# ---------------------------------------------------------------------------

def write_meta(
    run_dir: str | Path,
    meta_dict: dict[str, Any] | None = None,
    *,
    run_id: str = "",
    package_version: str = "",
    plugin_version: str = "",
    schema_version: str = "1.0",
    aedt_version: str = "",
    ads_version: str = "",
    seed: int | None = None,
) -> Path:
    """Write ``meta.json`` with standard provenance fields.

    方向 7：自动追加 python_version / os / pip_freeze_sha / solver_versions
    (via collect_provenance)。Any key present in *meta_dict* overrides.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # 基础字段
    record: dict[str, Any] = {
        "run_id": run_id,
        "git_sha": _git_sha(),
        "package_version": package_version,
        "plugin_version": plugin_version,
        "schema_version": schema_version,
        "aedt_version": aedt_version,
        "ads_version": ads_version,
        "user": getpass.getuser(),
        "hostname": platform.node(),
        "seed": seed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # 方向 7 provenance（meta_dict 覆盖优先）
    optuna_seed = (meta_dict or {}).get("optuna_seed", seed)
    solver_vers = (meta_dict or {}).get("solver_versions")
    provenance = collect_provenance(optuna_seed=optuna_seed, solver_versions=solver_vers)
    record.update(provenance)

    if meta_dict:
        record.update(meta_dict)

    dest = run_dir / "meta.json"
    dest.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# SQLite runs 索引（P1：单一运行索引，runs/ 目录本身不入 git）
#
# 索引实现经 infra/db.py 的 RegistryDB（runs 表同表名同字段，
# 行为向后兼容——原 _SCHEMA_RUNS 的 runs 表被迁移 v1 吸收）。record_run /
# list_runs 的对外签名、返回形状与容错语义（失败静默 False/[]）不变。
# ---------------------------------------------------------------------------

def record_run(db_path: str | Path | None = None,
               record: dict[str, Any] | None = None) -> bool:
    """Upsert a run record into the SQLite runs index.

    db_path 缺省（None）走 ``default_registry_db_path()``（env
    RFAUTO_REGISTRY_DB > settings db.path > runs/registry.sqlite，B④ 默认
    路径合流）；显式传路径语义不变。record 至少包含 run_id；
    model/adapter/status/git_sha/timestamp 可选。键名以 ``_`` 开头的字段
    （如内部路径）不入库。返回 True 表示成功。
    """
    if record is None:
        raise TypeError("record_run() 缺少必填参数 record（run 记录 dict）")
    # #140：PathLike 入参第一行先 Path() 收敛；None → 缺省路径解析链
    target = Path(db_path) if db_path is not None else default_registry_db_path()
    db = RegistryDB(path=target)
    try:
        return db.upsert_run(record)
    except Exception:
        # #105：索引是 best-effort 观测面，绝不阻塞业务主路径
        return False
    finally:
        db.close()


def list_runs(db_path: str | Path | None = None,
              limit: int = 20) -> list[dict[str, Any]]:
    """List recent runs from the SQLite index, newest first.

    db_path 缺省（None）走 ``default_registry_db_path()``（与 record_run
    同一解析链，写读两侧天然同库）；显式传路径语义不变。
    """
    # #140：PathLike 入参第一行先 Path() 收敛；None → 缺省路径解析链
    target = Path(db_path) if db_path is not None else default_registry_db_path()
    if not target.exists():
        return []
    db = RegistryDB(path=target)
    try:
        return db.list_runs(limit=limit)
    except Exception:
        return []
    finally:
        db.close()
