"""
把 runs/ 下的点级数据（trials/*.json、calibration/samples.json、
surrogate_loop.json / autotune.json 的 best 点）物化为统一行式 schema
的数据集（Parquet 默认；HDF5 经 h5py 并列可选，E1 待做列①），并提供
DuckDB 直查接口（谓词下推/列裁剪；hdf5 经 Arrow 表注册走同一 SQL 管线）。

设计要点：
- 目录布局：``<out_dir>/<name>/points.parquet``（或 ``points.h5``）+
  ``dataset_manifest.yaml``（``format``/``points_file`` 记录物化格式，
  旧 manifest 无键回退 parquet）；
- 去重指纹 ``(study_name, seed, params canonical json)``：同一优化点跨
  run 复用/缓存复跑只留一份（#158 缓存语义延续），manifest 记录
  n_points/n_rows/n_dup；
- 非有限值（NaN/±Inf，params/metrics/cost 三处同口径）在收集侧整点拦截
  并计数（manifest n_nonfinite_skipped），canonical JSON 以
  allow_nan=False 兜底——规范外 "NaN"/"Infinity" 字面量与非有限 cost
  永不落盘（E11 未尽②根治；DuckDB read_parquet 统计路径下 ``cost < 阈值``
  对 NaN 行求值 TRUE，非有限 cost 落盘会挤占 warm-start collect 的
  LIMIT 窗口，故必须在写入侧拦死）；
- where 是单条 SQL WHERE 片段，service 层做白名单字符集 + 注入子串
  （分号/注释符）校验后才拼入查询；model/study_name 等值过滤走 ``?``
  参数绑定下推，值永不拼进 SQL（E11 未尽③：limit 在过滤后生效）；
- 依赖为可选 extra（dataset）：未安装时显式报错提示
  ``pip install rfauto[dataset]``（参照 smt_kriging 模式，不阻塞本模块 import）。

数值只由确定性内核产出（军规 7）：本模块只做确定性收集/去重/SQL 查询，
不引入任何估计量。
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .common import (
    _COLUMN_RE as _COLUMN_RE,
)
from .common import (
    _DATASET_NAME_RE as _DATASET_NAME_RE,
)
from .common import (
    _WHERE_ALLOWED_RE as _WHERE_ALLOWED_RE,
)
from .common import (
    _WHERE_FORBIDDEN as _WHERE_FORBIDDEN,
)
from .common import (
    _WHERE_FORBIDDEN_KEYWORDS as _WHERE_FORBIDDEN_KEYWORDS,
)
from .common import (
    DATASET_FORMATS as DATASET_FORMATS,
)
from .common import (
    DATASET_SCHEMA as DATASET_SCHEMA,
)
from .common import (
    DEFAULT_FORMAT as DEFAULT_FORMAT,
)
from .common import (
    DEFAULT_OUT_DIR as DEFAULT_OUT_DIR,
)
from .common import (
    GROUND_TRUTH_ADAPTER_TOKENS as GROUND_TRUTH_ADAPTER_TOKENS,
)
from .common import (
    GROUND_TRUTH_POLICY as GROUND_TRUTH_POLICY,
)
from .common import (
    HDF5_NAME as HDF5_NAME,
)
from .common import (
    MANIFEST_NAME as MANIFEST_NAME,
)
from .common import (
    PARQUET_NAME as PARQUET_NAME,
)
from .common import (
    SCHEMA_VERSION as SCHEMA_VERSION,
)
from .common import (
    Any as Any,
)
from .common import (
    Path as Path,
)
from .common import (
    _canonical_json as _canonical_json,
)
from .common import (
    _coerce_seed as _coerce_seed,
)
from .common import (
    _has_nonfinite as _has_nonfinite,
)
from .common import (
    _import_duckdb as _import_duckdb,
)
from .common import (
    _import_h5py as _import_h5py,
)
from .common import (
    _import_pyarrow as _import_pyarrow,
)
from .common import (
    _save_manifest_atomic as _save_manifest_atomic,
)
from .common import (
    _validate_columns as _validate_columns,
)
from .common import (
    _validate_dataset_name as _validate_dataset_name,
)
from .common import (
    _validate_where as _validate_where,
)
from .common import (
    is_ground_truth_adapter as is_ground_truth_adapter,
)
from .common import (
    json as json,
)
from .common import (
    map_ordered as map_ordered,
)
from .common import (
    math as math,
)
from .common import (
    os as os,
)
from .common import (
    re as re,
)
from .io import (
    _dataset_format as _dataset_format,
)
from .io import (
    _load_manifest_yaml as _load_manifest_yaml,
)
from .io import (
    _points_path as _points_path,
)
from .io import (
    _read_points_hdf5 as _read_points_hdf5,
)
from .io import (
    _read_points_table as _read_points_table,
)
from .io import (
    _register_dataset_row as _register_dataset_row,
)
from .io import (
    _resolve_registry_sync as _resolve_registry_sync,
)
from .io import (
    _write_points_hdf5 as _write_points_hdf5,
)
from .materialize import (
    _TOUCHSTONE_RE as _TOUCHSTONE_RE,
)
from .materialize import (
    _aggregate_bounds as _aggregate_bounds,
)
from .materialize import (
    _coerce_cost as _coerce_cost,
)
from .materialize import (
    _collect_run_points as _collect_run_points,
)
from .materialize import (
    _run_payload as _run_payload,
)
from .materialize import (
    _run_touchstone as _run_touchstone,
)
from .materialize import (
    _single_run_params as _single_run_params,
)
from .materialize import (
    datetime as datetime,
)
from .materialize import (
    error_envelope as error_envelope,
)
from .materialize import (
    materialize_dataset as materialize_dataset,
)
from .materialize import (
    ok_envelope as ok_envelope,
)
from .materialize import (
    timezone as timezone,
)
from .profile import (
    dataset_profile as dataset_profile,
)
from .query import (
    _rows_to_csv as _rows_to_csv,
)
from .query import (
    query_dataset as query_dataset,
)
from .workdir import (
    _WORKDIR_CSV_COL_RE as _WORKDIR_CSV_COL_RE,
)
from .workdir import (
    _WORKDIR_CSV_NAME as _WORKDIR_CSV_NAME,
)
from .workdir import (
    _WORKDIR_MAX_DEPTH as _WORKDIR_MAX_DEPTH,
)
from .workdir import (
    _WORKDIR_SKIP_DIR_NAMES as _WORKDIR_SKIP_DIR_NAMES,
)
from .workdir import (
    _WORKDIR_SKIP_DIR_SUFFIXES as _WORKDIR_SKIP_DIR_SUFFIXES,
)
from .workdir import (
    _WORKDIR_TOUCHSTONE_RE as _WORKDIR_TOUCHSTONE_RE,
)
from .workdir import (
    WORKDIR_FAMILIES as WORKDIR_FAMILIES,
)
from .workdir import (
    WORKDIR_SOURCE as WORKDIR_SOURCE,
)
from .workdir import (
    _discover_workdir_scans as _discover_workdir_scans,
)
from .workdir import (
    _mtime_iso as _mtime_iso,
)
from .workdir import (
    _normalize_families as _normalize_families,
)
from .workdir import (
    _scan_workdir as _scan_workdir,
)
from .workdir import (
    _scan_workdir_curves as _scan_workdir_curves,
)
from .workdir import (
    _serialize_scan as _serialize_scan,
)
from .workdir import (
    _sparams_csv_ports as _sparams_csv_ports,
)
from .workdir import (
    _workdir_adapter as _workdir_adapter,
)
from .workdir import (
    _workdir_family as _workdir_family,
)
from .workdir import (
    _workdir_health_verdict as _workdir_health_verdict,
)
from .workdir import (
    _workdir_skip_dir as _workdir_skip_dir,
)
from .workdir import (
    discover_workdir_candidates as discover_workdir_candidates,
)
from .workdir import (
    import_workdir_runs as import_workdir_runs,
)
from .workdir_params import (
    _WORKDIR_JSON_MAX_BYTES as _WORKDIR_JSON_MAX_BYTES,
)
from .workdir_params import (
    _WORKDIR_PARAM_PATHS as _WORKDIR_PARAM_PATHS,
)
from .workdir_params import (
    _dig_path as _dig_path,
)
from .workdir_params import (
    _json_mentions_path as _json_mentions_path,
)
from .workdir_params import (
    _load_json_dict as _load_json_dict,
)
from .workdir_params import (
    _params_from_json as _params_from_json,
)
from .workdir_params import (
    _resolve_workdir_params as _resolve_workdir_params,
)
from .workdir_params import (
    _scalar_items as _scalar_items,
)
from .workdir_params import (
    write_workdir_params_json as write_workdir_params_json,
)

# ══ T2 巨石拆分 facade（架构批 W7-S1，2026-10-19）══════════════════
# 本文件原为单文件巨石，实现按职责域迁入上方 re-export 的子模块；此处
# 逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir() 逐名
# 相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数）。扇出清单由各子模块 globals 按名自动构建。
_SUBMODULES = (['common', 'io', 'materialize', 'profile', 'query', 'workdir'])


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
