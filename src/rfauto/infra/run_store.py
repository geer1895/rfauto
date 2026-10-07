"""rfauto run-store — run directory management & metadata.

方向 7 可复现基建：provenance 采集（python_version/os/pip_freeze_sha/
solver_versions/optuna_seed），recipe_version 字段支持。

XD-1（W3-B）跨 run lineage：write_meta 增可选 derived_from 边（落
meta.json 新键）；run_lineage 表 DDL 单源在本模块（service/lake_service
同库消费；record_lineage_edges 提供湖侧 best-effort 直写桥，重建以
meta.json 为事实源）。
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from rfauto.infra.db import RegistryDB, default_registry_db_path

logger = logging.getLogger(__name__)

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
    （infra.recipe_guard，配方污染根修 TODO 增量②）。
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
    solver_versions, optuna_seed, numeric_env.  All fields are best-effort
    (never raise).

    numeric_env（round3 附带件之二消费钩子，E 类台账 §三.2 销账）：数值栈指纹
    （numpy 版本/BLAS backend/线程环境变量/CPU 核数，infra/numeric_env.py）——
    探测自身永不 raise，此处 try/except 仅兜 import 异常态（#105 观测面不进
    业务主路径故障链）。
    """
    try:
        from rfauto.infra.numeric_env import numeric_env_fingerprint

        numeric_env = numeric_env_fingerprint()
    except Exception as exc:  # pragma: no cover - 防御性（#105 best-effort）
        numeric_env = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "python_version": _python_version(),
        "os": _os_info(),
        "pip_freeze_sha": _pip_freeze_sha(),
        "solver_versions": solver_versions or {},
        "optuna_seed": optuna_seed,
        "numeric_env": numeric_env,
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

#: XD-1（W3-B）跨 run lineage 边表（DuckDB 湖库；lake_service 同库建表/重建）。
#: DDL 单源在本模块（service 可 import infra，反向不行——分层铁律 3）。
RUN_LINEAGE_TABLE = "run_lineage"

#: XD-1 规格 DDL 原文（sa_specs2 §10.2.2，逐列一致）。
RUN_LINEAGE_DDL = (
    f"CREATE TABLE IF NOT EXISTS {RUN_LINEAGE_TABLE} ("
    "child_run_id VARCHAR NOT NULL, "
    "parent_run_id VARCHAR NOT NULL, "
    "edge_kind VARCHAR DEFAULT 'derived', "
    "created_at TIMESTAMP, "
    f"PRIMARY KEY (child_run_id, parent_run_id, edge_kind))"
)

#: 预声明边种词汇（spec §10.2.1：dataset|calib|report|warmstart + DDL 缺省
#: derived）。开放词汇表：未知 kind 如实保留不拒（多报不放过方向 #316），
#: 本常量只作文档锚与测试对照，不做枚举强校验。
LINEAGE_EDGE_KINDS = ("dataset", "calib", "report", "warmstart", "derived")


def normalize_derived_from(
    derived_from: Any,
    edge_kind: str = "derived",
) -> tuple[list[dict[str, str]], list[str]]:
    """归一 derived_from 输入为 canonical 边列表（纯函数，永不 raise）。

    接受形态（逐项判别，混合合法）：
    - ``"run_id"``：str，边种=调用级 *edge_kind*；
    - ``{"run_id": "r", "edge_kind": "dataset", "note": "..."}``：dict，
      键缺省回退调用级 edge_kind，note 可选；其余 dict 无 run_id 丢弃。

    Returns:
        (entries, warnings)：entries 为 ``[{"run_id", "edge_kind", "note"?}]``
        （run_id 空/非串的项丢弃）；warnings 为丢弃/修正说明（best-effort
        留痕，#105——写边失败不阻塞主路径）。
    """
    warnings: list[str] = []
    entries: list[dict[str, str]] = []
    if derived_from is None:
        return entries, warnings
    if isinstance(derived_from, str):
        derived_from = [derived_from]
    if not isinstance(derived_from, (list, tuple)):
        warnings.append(
            f"derived_from 需为列表，收到 {type(derived_from).__name__}（整边丢弃）")
        return entries, warnings
    kind = str(edge_kind) if str(edge_kind).strip() else "derived"
    seen: set[tuple[str, str]] = set()
    for item in derived_from:
        if isinstance(item, str):
            run_id, item_kind, note = item.strip(), kind, ""
            if not run_id:
                warnings.append("derived_from 含空 run_id 项（丢弃）")
                continue
        elif isinstance(item, dict):
            rid = item.get("run_id")
            run_id = str(rid).strip() if rid is not None else ""
            if not run_id:
                warnings.append(f"derived_from dict 项缺 run_id（丢弃）: {item!r}")
                continue
            item_kind = str(item.get("edge_kind") or kind).strip() or kind
            note = str(item.get("note") or "")
        else:
            warnings.append(
                f"derived_from 含非法项 {type(item).__name__}（丢弃）")
            continue
        key = (run_id, item_kind)
        if key in seen:
            continue
        seen.add(key)
        entry = {"run_id": run_id, "edge_kind": item_kind}
        if note:
            entry["note"] = note
        entries.append(entry)
    return entries, warnings


def _lineage_meta_form(entries: list[dict[str, str]]) -> list[Any]:
    """canonical 边 → meta.json 序列形态。

    规格口径（sa_specs2 §10.2.1"数组，run_id 列表+可选每边注释"）：缺省
    边种（derived）且无 note 时落裸 run_id 串（与"run_id 列表"字面一致）；
    有边种/注释时落 ``{"run_id", "edge_kind", "note"?}`` dict。
    """
    out: list[Any] = []
    for entry in entries:
        if entry["edge_kind"] == "derived" and not entry.get("note"):
            out.append(entry["run_id"])
        else:
            body: dict[str, str] = {"run_id": entry["run_id"],
                                    "edge_kind": entry["edge_kind"]}
            if entry.get("note"):
                body["note"] = entry["note"]
            out.append(body)
    return out


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
    derived_from: list[str] | list[dict[str, Any]] | None = None,
    edge_kind: str = "derived",
) -> Path:
    """Write ``meta.json`` with standard provenance fields.

    方向 7：自动追加 python_version / os / pip_freeze_sha / solver_versions
    (via collect_provenance)。Any key present in *meta_dict* overrides.

    XD-1（W3-B）：*derived_from* 非空时落 meta.json 新键 ``derived_from``
    （跨 run 血缘边；None=零改动现状，既有调用逐字节不变——判据 1）。
    归一化 best-effort（#105）：非法项丢弃留 warning，永不阻塞 meta 写主
    路径；边种用 *edge_kind*（dataset|calib|report|warmstart，词汇表见
    LINEAGE_EDGE_KINDS）。边信息来源=调用方上下文（不做目录名猜测）。
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

    # XD-1 lineage 边（meta_dict 不得覆盖本键——显式参数单源）
    if derived_from is not None:
        entries, edge_warnings = normalize_derived_from(derived_from, edge_kind)
        if entries:
            record["derived_from"] = _lineage_meta_form(entries)
        for warning in edge_warnings:
            logger.warning("XD-1 lineage 边归一化丢弃（非阻断）: %s", warning)

    dest = run_dir / "meta.json"
    dest.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# SQLite runs 索引（P1：单一运行索引，runs/ 目录本身不入 git）
#
# W1⑫：索引实现改经 infra/db.py 的 RegistryDB（runs 表同表名同字段，
# 行为向后兼容——原 _SCHEMA_RUNS 的 runs 表被迁移 v1 吸收）。record_run /
# list_runs 的对外签名、返回形状与容错语义（失败静默 False/[]）不变。
# ---------------------------------------------------------------------------

def record_lineage_edges(
    child_run_id: str,
    parents: list[str] | list[dict[str, Any]] | None,
    *,
    db_path: str | Path | None = None,
    edge_kind: str = "derived",
    created_at: datetime | None = None,
) -> bool:
    """把血缘边直写湖 DuckDB ``run_lineage`` 表（XD-1，best-effort #105）。

    record_run 的可选同步边桥：meta.json 是事实源（湖 rebuild 按 meta 扫
    描重建边表），本桥让边在下次 rebuild 前即可查（rebuild 会按 meta 重放
    ——未落 meta 的直写边是临时的，属设计语义）。表不存在时按
    ``RUN_LINEAGE_DDL`` 建（幂等）；同 (child, parent, kind) 重写覆盖。

    db_path 缺省 ``runs/.lake_index.duckdb``（与湖索引同库，import 局部
    避免硬依赖——duckdb 缺装/库不可写一律 False 不 raise）。parents 走
    normalize_derived_from 归一（非法项丢弃）。child 为空或无有效父边
    → 无事可做返回 True。返回 True=全部边已写/无事可做。
    """
    if not child_run_id or not str(child_run_id).strip():
        return True
    entries, _warnings = normalize_derived_from(parents, edge_kind)
    if not entries:
        return True
    target = Path(db_path) if db_path is not None \
        else Path("runs") / ".lake_index.duckdb"
    try:
        import duckdb

        target.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(target))
        try:
            con.execute(RUN_LINEAGE_DDL)
            stamp = created_at or datetime.now(timezone.utc)
            for entry in entries:
                con.execute(
                    f"INSERT OR REPLACE INTO {RUN_LINEAGE_TABLE} "
                    f"(child_run_id, parent_run_id, edge_kind, created_at) "
                    f"VALUES (?, ?, ?, ?)",
                    [str(child_run_id), entry["run_id"],
                     entry["edge_kind"], stamp],
                )
        finally:
            con.close()
        return True
    except Exception as exc:  # 观测面绝不阻塞业务主路径（#105）
        logger.warning("XD-1 血缘边直写失败（非阻断）: %s", exc)
        return False


def record_run(db_path: str | Path | None = None,
               record: dict[str, Any] | None = None,
               *,
               derived_from: list[str] | list[dict[str, Any]] | None = None,
               edge_kind: str = "derived") -> bool:
    """Upsert a run record into the SQLite runs index.

    db_path 缺省（None）走 ``default_registry_db_path()``（env
    RFAUTO_REGISTRY_DB > settings db.path > runs/registry.sqlite，B④ 默认
    路径合流）；显式传路径语义不变。record 至少包含 run_id；
    model/adapter/status/git_sha/timestamp 可选。键名以 ``_`` 开头的字段
    （如内部路径）不入库。返回 True 表示成功。

    XD-1（W3-B）：*derived_from* 非空时顺带 best-effort 同步血缘边进湖
    ``run_lineage`` 表（record_lineage_edges；失败只留 warning 不影响
    本函数返回值——判据 6 写边失败 run 主流程不受阻）。
    """
    if record is None:
        raise TypeError("record_run() 缺少必填参数 record（run 记录 dict）")
    if derived_from is not None:
        # 可选同步边（#105 best-effort，先于 upsert 亦不阻塞：失败仅 False）
        record_lineage_edges(str(record.get("run_id") or ""), derived_from,
                             edge_kind=edge_kind)
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
