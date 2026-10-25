"""
原则（内核立规注记 硬限制）：服务层 JSON 进出；cli/mcp 是薄壳；写操作只经
本模块落盘（配方保存走 validate_recipe 校验 + 单写锁由 run 链路负责）。

页面数据：
- list_runs / run_detail：runs 产物索引与单次 run 全量中间产物
- recipe_view / recipe_save：配方的表单化读改（人不需要写 YAML）
- model3d_for_recipe：3D 预览几何 spec（毫米）
- read_run_events：P-1 SSE 战役进度桥的读面（events.jsonl→偏移增量）
"""

from __future__ import annotations

import copy as copy
import importlib as _importlib
import json as json
import logging as logging
import os as os
import re as re
import sys as _sys
import threading as threading
import time as time
from datetime import datetime as datetime
from datetime import timezone as timezone
from pathlib import Path as Path
from types import ModuleType as _ModuleType
from typing import Any as Any

from rfauto.service._helpers import (
    load_run_trials as load_run_trials,
)
from rfauto.service._helpers import (
    safe_run_id as safe_run_id,
)
from rfauto.service.envelope import (
    error_envelope as error_envelope,
)
from rfauto.service.envelope import (
    ok_envelope as ok_envelope,
)
from rfauto.service.template_hints import (
    _template_hint as _template_hint,
)
from rfauto.service.ui_scan_cache import (
    _UI_CACHE_OFF_VALUES as _UI_CACHE_OFF_VALUES,
)
from rfauto.service.ui_scan_cache import (
    _UI_SCAN_TTL_S as _UI_SCAN_TTL_S,
)
from rfauto.service.ui_scan_cache import (
    _ui_cache_enabled as _ui_cache_enabled,
)
from rfauto.service.ui_scan_cache import (
    _UiScanCache as _UiScanCache,
)

from .cache import (
    _DIR_LISTING_CACHE as _DIR_LISTING_CACHE,
)
from .cache import (
    _H5_PROBE_CACHE as _H5_PROBE_CACHE,
)
from .cache import (
    _JSON_FILE_CACHE as _JSON_FILE_CACHE,
)
from .cache import (
    _REG_GEN as _REG_GEN,
)
from .cache import (
    _REG_GEN_LAST_SHAPE as _REG_GEN_LAST_SHAPE,
)
from .cache import (
    _REG_HEAL_BATCH as _REG_HEAL_BATCH,
)
from .cache import (
    _REG_HEAL_ENGINE_DIRS as _REG_HEAL_ENGINE_DIRS,
)
from .cache import (
    _REG_HEAL_EVIDENCE_CONTENT_DIRS as _REG_HEAL_EVIDENCE_CONTENT_DIRS,
)
from .cache import (
    _REG_HEAL_EVIDENCE_FILES as _REG_HEAL_EVIDENCE_FILES,
)
from .cache import (
    _REG_HEAL_MIN_INTERVAL_S as _REG_HEAL_MIN_INTERVAL_S,
)
from .cache import (
    _REG_HEAL_STATE as _REG_HEAL_STATE,
)
from .cache import (
    _REG_INDEX_CACHE as _REG_INDEX_CACHE,
)
from .cache import (
    _REG_RUN_POINT_NAME_RE as _REG_RUN_POINT_NAME_RE,
)
from .cache import (
    _REG_SQLITE_SIDECAR_PREFIX as _REG_SQLITE_SIDECAR_PREFIX,
)
from .cache import (
    _RUN_SCAN_CACHE as _RUN_SCAN_CACHE,
)
from .cache import (
    _SNAPSHOT_CACHE as _SNAPSHOT_CACHE,
)
from .cache import (
    _UI_REGISTRY_OFF_VALUES as _UI_REGISTRY_OFF_VALUES,
)
from .cache import (
    _UI_SCAN_CACHES as _UI_SCAN_CACHES,
)
from .cache import (
    RUNS_DIR as RUNS_DIR,
)
from .cache import (
    _bump_reg_gen as _bump_reg_gen,
)
from .cache import (
    _cached_json as _cached_json,
)
from .cache import (
    _cached_meta as _cached_meta,
)
from .cache import (
    _cached_run_entries as _cached_run_entries,
)
from .cache import (
    _cached_trials_count as _cached_trials_count,
)
from .cache import (
    _endpoint_snapshot as _endpoint_snapshot,
)
from .cache import (
    _file_signature as _file_signature,
)
from .cache import (
    _heal_row_from_meta as _heal_row_from_meta,
)
from .cache import (
    _heal_row_no_meta as _heal_row_no_meta,
)
from .cache import (
    _maybe_spawn_heal as _maybe_spawn_heal,
)
from .cache import (
    _missing_registry_rows as _missing_registry_rows,
)
from .cache import (
    _produce_registry_index as _produce_registry_index,
)
from .cache import (
    _reg_iso as _reg_iso,
)
from .cache import (
    _reg_model_from_recipe_snapshot as _reg_model_from_recipe_snapshot,
)
from .cache import (
    _reg_no_meta_evidence as _reg_no_meta_evidence,
)
from .cache import (
    _registry_file_signature as _registry_file_signature,
)
from .cache import (
    _registry_meta_lookup as _registry_meta_lookup,
)
from .cache import (
    _registry_run_index as _registry_run_index,
)
from .cache import (
    _run_meta_pair as _run_meta_pair,
)
from .cache import (
    _runs_dir_key as _runs_dir_key,
)
from .cache import (
    _runs_fingerprint as _runs_fingerprint,
)
from .cache import (
    _self_heal_backfill as _self_heal_backfill,
)
from .cache import (
    _top_dir_names as _top_dir_names,
)
from .cache import (
    _ui_cache_stats as _ui_cache_stats,
)
from .cache import (
    _ui_registry_enabled as _ui_registry_enabled,
)
from .cache import (
    _ui_scan_cache_clear as _ui_scan_cache_clear,
)
from .insights import (
    _UQ_SAMPLE_MAX_DEPTH as _UQ_SAMPLE_MAX_DEPTH,
)
from .insights import (
    _UQ_SAMPLE_PARSE_CAP_BYTES as _UQ_SAMPLE_PARSE_CAP_BYTES,
)
from .insights import (
    FARFIELD_H5_NAMES as FARFIELD_H5_NAMES,
)
from .insights import (
    FIELD_DUMP_SUBDIRS as FIELD_DUMP_SUBDIRS,
)
from .insights import (
    PATCH_ETA_GATE as PATCH_ETA_GATE,
)
from .insights import (
    PATCH_ETA_GATE_BASIS as PATCH_ETA_GATE_BASIS,
)
from .insights import (
    _farfield_h5 as _farfield_h5,
)
from .insights import (
    _field_dump_candidates as _field_dump_candidates,
)
from .insights import (
    _is_field_dump as _is_field_dump,
)
from .insights import (
    _load_run_trials as _load_run_trials,
)
from .insights import (
    _run_dir_or_error as _run_dir_or_error,
)
from .insights import (
    _smith_traces_from_touchstone as _smith_traces_from_touchstone,
)
from .insights import (
    _viz3d_available as _viz3d_available,
)
from .insights import (
    anchor_detail as anchor_detail,
)
from .insights import (
    anchors_overview as anchors_overview,
)
from .insights import (
    dataset_preview as dataset_preview,
)
from .insights import (
    datasets_overview as datasets_overview,
)
from .insights import (
    feasibility_heatmap as feasibility_heatmap,
)
from .insights import (
    field_runs as field_runs,
)
from .insights import (
    field_view as field_view,
)
from .insights import (
    pareto_view as pareto_view,
)
from .insights import (
    patch_eta_gate as patch_eta_gate,
)
from .insights import (
    smith_external as smith_external,
)
from .insights import (
    smith_view as smith_view,
)
from .insights import (
    uq_samples_list as uq_samples_list,
)
from .insights import (
    uq_yield_run as uq_yield_run,
)
from .runs_recipes import (
    RUN_TERMINAL_EVENT_TYPES as RUN_TERMINAL_EVENT_TYPES,
)
from .runs_recipes import (
    _model3d_from_snapshot as _model3d_from_snapshot,
)
from .runs_recipes import (
    _run_detail_signature as _run_detail_signature,
)
from .runs_recipes import (
    _workcopy_rel as _workcopy_rel,
)
from .runs_recipes import (
    append_run_event as append_run_event,
)
from .runs_recipes import (
    list_runs as list_runs,
)
from .runs_recipes import (
    model3d_for_params as model3d_for_params,
)
from .runs_recipes import (
    model3d_for_recipe as model3d_for_recipe,
)
from .runs_recipes import (
    read_run_events as read_run_events,
)
from .runs_recipes import (
    recipe_create as recipe_create,
)
from .runs_recipes import (
    recipe_save as recipe_save,
)
from .runs_recipes import (
    recipe_view as recipe_view,
)
from .runs_recipes import (
    run_detail as run_detail,
)
from .runs_recipes import (
    sandbox_diff as sandbox_diff,
)
from .runs_recipes import (
    sandbox_drafts as sandbox_drafts,
)
from .runs_recipes import (
    sandbox_promote as sandbox_promote,
)
from .runs_recipes import (
    tune_trials as tune_trials,
)
from .views import (
    _FIG_SUFFIXES as _FIG_SUFFIXES,
)
from .views import (
    _PARETO_RUNS_SCAN_CAP as _PARETO_RUNS_SCAN_CAP,
)
from .views import (
    _REPORT_FILES as _REPORT_FILES,
)
from .views import (
    REPORT_FIG_SUBDIR as REPORT_FIG_SUBDIR,
)
from .views import (
    calibration_runs as calibration_runs,
)
from .views import (
    calibration_view as calibration_view,
)
from .views import (
    cost_timeline as cost_timeline,
)
from .views import (
    cross_fidelity_view as cross_fidelity_view,
)
from .views import (
    external_sparams as external_sparams,
)
from .views import (
    list_reports as list_reports,
)
from .views import (
    loop_board_control as loop_board_control,
)
from .views import (
    loop_board_view as loop_board_view,
)
from .views import (
    loop_boards as loop_boards,
)
from .views import (
    pareto_runs as pareto_runs,
)
from .views import (
    report_content as report_content,
)
from .views import (
    run_fig_file as run_fig_file,
)
from .views import (
    sparams_compare_png as sparams_compare_png,
)
from .views import (
    sparams_series as sparams_series,
)

_LOG = logging.getLogger(__name__)

# ══ T2 巨石拆分 facade（aurora_g W7-S1，2026-10-19）══════════════════
# 本文件原为单文件巨石，实现按职责域迁入上方 re-export 的子模块；此处
# 逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir() 逐名
# 相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数）。扇出清单由各子模块 globals 按名自动构建。
_SUBMODULES = (['cache', 'runs_recipes', 'views', 'insights'])


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
