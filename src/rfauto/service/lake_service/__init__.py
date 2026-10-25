"""
能力面（规格：docs/plan_expansion_pool_20260924.md F3；study 元组面
DA-1，docs/research_expansion_20260926_round4.md 中件包三）：

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
- study 元组（DA-1）：extract_study_tuple 从单 run meta+trials 抽
  study→(template, target, budget) 元组（缺失字段 None 如实）；
  study_tuples_from_index 从已建索引按 study 名聚合元组；
  build_index_cli_entry 索引首建薄包装（计时统计，CLI 接线归出口批）。

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

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .audit import (
    _AUDIT_BUDGET_META_KEYS as _AUDIT_BUDGET_META_KEYS,
)
from .audit import (
    _SWEEP_PRODUCT_MARKERS as _SWEEP_PRODUCT_MARKERS,
)
from .audit import (
    _audit_dag_components as _audit_dag_components,
)
from .audit import (
    _audit_engine_record as _audit_engine_record,
)
from .audit import (
    _audit_git_head as _audit_git_head,
)
from .audit import (
    _audit_norm as _audit_norm,
)
from .audit import (
    _canonical_dump as _canonical_dump,
)
from .audit import (
    audit_stale_runs as audit_stale_runs,
)
from .audit import (
    normalize_config_diff as normalize_config_diff,
)
from .audit import (
    sweep_runs as sweep_runs,
)
from .index import (
    _META_NAMES as _META_NAMES,
)
from .index import (
    _VERDICT_NAME as _VERDICT_NAME,
)
from .index import (
    DEFAULT_DUCKDB_MEMORY_LIMIT as DEFAULT_DUCKDB_MEMORY_LIMIT,
)
from .index import (
    DEFAULT_DUCKDB_THREADS as DEFAULT_DUCKDB_THREADS,
)
from .index import (
    DEFAULT_LAKE_INDEX_NAME as DEFAULT_LAKE_INDEX_NAME,
)
from .index import (
    LAKE_INDEX_COLUMNS as LAKE_INDEX_COLUMNS,
)
from .index import (
    LAKE_INDEX_SOURCE_DIRSCAN as LAKE_INDEX_SOURCE_DIRSCAN,
)
from .index import (
    LAKE_INDEX_SOURCE_INDEX as LAKE_INDEX_SOURCE_INDEX,
)
from .index import (
    LAKE_INDEX_STALENESS_THRESHOLD as LAKE_INDEX_STALENESS_THRESHOLD,
)
from .index import (
    LAKE_INDEX_TABLE as LAKE_INDEX_TABLE,
)
from .index import (
    RUN_LINEAGE_DDL as RUN_LINEAGE_DDL,
)
from .index import (
    RUN_LINEAGE_TABLE as RUN_LINEAGE_TABLE,
)
from .index import (
    Any as Any,
)
from .index import (
    Path as Path,
)
from .index import (
    _dir_stats as _dir_stats,
)
from .index import (
    _import_duckdb as _import_duckdb,
)
from .index import (
    _index_row as _index_row,
)
from .index import (
    _iter_run_dirs as _iter_run_dirs,
)
from .index import (
    _lineage_edges_from_meta as _lineage_edges_from_meta,
)
from .index import (
    _meta_file as _meta_file,
)
from .index import (
    _parse_date as _parse_date,
)
from .index import (
    _read_json_object as _read_json_object,
)
from .index import (
    _split_cycle_edges as _split_cycle_edges,
)
from .index import (
    build_runs_index as build_runs_index,
)
from .index import (
    configure_duckdb_connection as configure_duckdb_connection,
)
from .index import (
    contextlib as contextlib,
)
from .index import (
    count_runs_index as count_runs_index,
)
from .index import (
    datetime as datetime,
)
from .index import (
    default_lake_index_db_path as default_lake_index_db_path,
)
from .index import (
    error_envelope as error_envelope,
)
from .index import (
    index_candidate_paths as index_candidate_paths,
)
from .index import (
    index_scope_dir_count as index_scope_dir_count,
)
from .index import (
    json as json,
)
from .index import (
    lake_index_db_path_for as lake_index_db_path_for,
)
from .index import (
    logging as logging,
)
from .index import (
    ok_envelope as ok_envelope,
)
from .index import (
    os as os,
)
from .index import (
    query_runs_index as query_runs_index,
)
from .lineage import (
    _LINEAGE_NODE_COLUMNS as _LINEAGE_NODE_COLUMNS,
)
from .lineage import (
    LINEAGE_HOPS_MAX as LINEAGE_HOPS_MAX,
)
from .lineage import (
    LINEAGE_HOPS_MIN as LINEAGE_HOPS_MIN,
)
from .lineage import (
    query_lineage as query_lineage,
)
from .lineage import (
    render_lineage_md as render_lineage_md,
)
from .lineage import (
    verify_lineage as verify_lineage,
)
from .pack import (
    PACK_FORMAT as PACK_FORMAT,
)
from .pack import (
    PurePosixPath as PurePosixPath,
)
from .pack import (
    _collect_files as _collect_files,
)
from .pack import (
    _decompress_pack as _decompress_pack,
)
from .pack import (
    _import_zstandard as _import_zstandard,
)
from .pack import (
    _load_manifest as _load_manifest,
)
from .pack import (
    _manifest_path_for as _manifest_path_for,
)
from .pack import (
    _safe_rel_path as _safe_rel_path,
)
from .pack import (
    _sha256_file as _sha256_file,
)
from .pack import (
    export_index_parquet as export_index_parquet,
)
from .pack import (
    hashlib as hashlib,
)
from .pack import (
    pack_campaign as pack_campaign,
)
from .pack import (
    restore_campaign as restore_campaign,
)
from .pack import (
    tarfile as tarfile,
)
from .pack import (
    tempfile as tempfile,
)
from .pack import (
    timezone as timezone,
)
from .pack import (
    verify_campaign as verify_campaign,
)
from .study import (
    _STUDY_TUPLE_SECTIONS as _STUDY_TUPLE_SECTIONS,
)
from .study import (
    _as_budget_int as _as_budget_int,
)
from .study import (
    _study_tuple_nested as _study_tuple_nested,
)
from .study import (
    build_index_cli_entry as build_index_cli_entry,
)
from .study import (
    extract_study_tuple as extract_study_tuple,
)
from .study import (
    study_tuples_from_index as study_tuples_from_index,
)
from .study import (
    time as time,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_LAKE_INDEX_NAME",
    "LAKE_INDEX_COLUMNS",
    "LAKE_INDEX_SOURCE_DIRSCAN",
    "LAKE_INDEX_SOURCE_INDEX",
    "LAKE_INDEX_STALENESS_THRESHOLD",
    "LAKE_INDEX_TABLE",
    "PACK_FORMAT",
    "RUN_LINEAGE_TABLE",
    "build_index_cli_entry",
    "build_runs_index",
    "configure_duckdb_connection",
    "count_runs_index",
    "default_lake_index_db_path",
    "export_index_parquet",
    "extract_study_tuple",
    "index_candidate_paths",
    "index_scope_dir_count",
    "lake_index_db_path_for",
    "pack_campaign",
    "query_lineage",
    "query_runs_index",
    "render_lineage_md",
    "restore_campaign",
    "study_tuples_from_index",
    "sweep_runs",
    "verify_campaign",
    "verify_lineage",
]

# ══ T2 巨石拆分 facade（aurora_g W7-S1，2026-10-19）══════════════════
# 本文件原为单文件巨石，实现按职责域迁入上方 re-export 的子模块；此处
# 逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir() 逐名
# 相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数）。扇出清单由各子模块 globals 按名自动构建。
_SUBMODULES = (['index', 'lineage', 'audit', 'pack', 'study'])


class _FacadeModule(_ModuleType):
    """facade setattr 双写：补丁扇出到持有该名的全部子模块（AU-1）。"""

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _sub in _FANOUT.get(name, ()):
            setattr(_importlib.import_module(__name__ + "." + _sub),
                    name, value)


_FANOUT: dict[str, list[str]] = {}


def _build_fanout() -> None:
    for _sub in _SUBMODULES:
        _mod = _importlib.import_module(__name__ + "." + _sub)
        for _name in list(vars(_mod)):
            _FANOUT.setdefault(_name, []).append(_sub)


_build_fanout()
del _build_fanout
_sys.modules[__name__].__class__ = _FacadeModule
