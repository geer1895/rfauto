"""
所有服务函数 JSON 进出，保证"人能用的 Agent 就能用，Agent 能用的人也能用"（军规 10）。
长任务只返回 JobHandle，永不阻塞调用方（军规 4）。
"""

from __future__ import annotations

import contextlib as contextlib
import getpass as getpass
import importlib as _importlib
import json as json
import platform as platform
import sys as _sys
from pathlib import (
    Path as Path,
)
from types import (
    ModuleType as _ModuleType,
)
from typing import (
    Any as Any,
)

from rfauto.core.contracts import (
    AdsExchangeContract as AdsExchangeContract,
)
from rfauto.core.objectives import (
    Objective as Objective,
)
from rfauto.core.objectives import (
    SpecEvaluator as SpecEvaluator,
)
from rfauto.core.parameters import (
    ParameterSystem as ParameterSystem,
)
from rfauto.core.parameters import (
    ParamValue as ParamValue,
)
from rfauto.core.state import (
    generate_job_id as generate_job_id,
)
from rfauto.core.state import (
    generate_run_id as generate_run_id,
)

# ─── v3 service re-exports ───────────────────────────────────────────────────
# 唯一事实源在 v3_services.py / r3_services.py / dataset_service.py /
# dataset_insights.py / warm_start_data.py（#108/#112 治理；B-34 补齐四模块
# 公开服务函数；E1 收口补 dataset_insights 八接口）。
# 审查批次修复：本文件尾部曾残留 5 个同名旧实现（compare_runs_provenance /
# run_p0_experiment / study_inject / structured_sweep / run_multifidelity_tune），
# 遮蔽 v3_services 版本——修 v3_services 不生效的幽灵 bug 由此而来（#116）。
# 以后新增服务函数：写进对应源模块，在此 re-export，禁止在本文件写实现；
# 完整性由 tests/unit/test_api_reexport.py 钉住（缺 re-export / 尾部同名
# def 遮蔽都会身份断言失败）。
# 契约性排除：r3_services.get_chat_settings_raw（返回含 api_key 明文，
# 自述"不对外"）不入 api 公开面。
# ─── T1 解环轴（aurora_g W6-S1）：门面动作注册（service/agent_actions）───────
# 实现模块（r3_services/agent_sandbox/ui_service）经 agent_actions 服务定位器
# 取本门面动作，静态依赖图上不再出现 实现→门面 边（R1 审计 19 模块 SCC 的
# 轴心 api↔r3_services 解环）。注册必须在本文件全部动作定义之后。
from rfauto.service.agent_actions import register_actions as _register_actions
from rfauto.service.dataset_insights import annotate_ground_truth as annotate_ground_truth
from rfauto.service.dataset_insights import dataset_coverage as dataset_coverage
from rfauto.service.dataset_insights import export_hf_dataset as export_hf_dataset
from rfauto.service.dataset_insights import list_datasets as list_datasets
from rfauto.service.dataset_insights import load_dataset_sets as load_dataset_sets
from rfauto.service.dataset_insights import neural_operator_readiness as neural_operator_readiness
from rfauto.service.dataset_insights import register_public_dataset as register_public_dataset
from rfauto.service.dataset_insights import set_dataset_visibility as set_dataset_visibility
from rfauto.service.dataset_service import discover_workdir_candidates as discover_workdir_candidates
from rfauto.service.dataset_service import import_workdir_runs as import_workdir_runs
from rfauto.service.dataset_service import is_ground_truth_adapter as is_ground_truth_adapter
from rfauto.service.dataset_service import materialize_dataset as materialize_dataset
from rfauto.service.dataset_service import query_dataset as query_dataset
from rfauto.service.dataset_service import write_workdir_params_json as write_workdir_params_json
from rfauto.service.dataset_service.profile import dataset_profile as dataset_profile
from rfauto.service.envelope import (
    error_envelope as error_envelope,
)
from rfauto.service.envelope import (
    ok_envelope as ok_envelope,
)
from rfauto.service.envelope import (
    skipped_envelope as skipped_envelope,
)
from rfauto.service.r3_services import AgentChat as AgentChat
from rfauto.service.r3_services import add_solver_to_config as add_solver_to_config
from rfauto.service.r3_services import approve_proposal as approve_proposal
from rfauto.service.r3_services import fs_allowed_roots as fs_allowed_roots
from rfauto.service.r3_services import fs_list as fs_list
from rfauto.service.r3_services import fs_read_fence as fs_read_fence
from rfauto.service.r3_services import get_chat_settings as get_chat_settings
from rfauto.service.r3_services import get_system_prompt as get_system_prompt
from rfauto.service.r3_services import (
    get_system_prompt_meta as get_system_prompt_meta,  # AD-1
)
from rfauto.service.r3_services import list_pending_approvals as list_pending_approvals
from rfauto.service.r3_services import list_recipes as list_recipes
from rfauto.service.r3_services import list_registered_solvers as list_registered_solvers
from rfauto.service.r3_services import list_solver_visualizations as list_solver_visualizations
from rfauto.service.r3_services import remove_solver_from_config as remove_solver_from_config
from rfauto.service.r3_services import save_chat_settings as save_chat_settings
from rfauto.service.r3_services import spice_tool_status as spice_tool_status
from rfauto.service.v3_services import agent_quality_summary as agent_quality_summary
from rfauto.service.v3_services import compare_runs_provenance as compare_runs_provenance
from rfauto.service.v3_services import generate_enhanced_report as generate_enhanced_report
from rfauto.service.v3_services import hfss_import_recipe as hfss_import_recipe
from rfauto.service.v3_services import run_multifidelity_sbo_tune as run_multifidelity_sbo_tune
from rfauto.service.v3_services import run_multifidelity_tune as run_multifidelity_tune
from rfauto.service.v3_services import run_p0_experiment as run_p0_experiment
from rfauto.service.v3_services import run_sensitivity as run_sensitivity
from rfauto.service.v3_services import structured_sweep as structured_sweep
from rfauto.service.v3_services import study_inject as study_inject
from rfauto.service.warm_start_data import collect_warm_start_samples as collect_warm_start_samples
from rfauto.service.warm_start_data import (
    run_optimization_warm_start_from_dataset as run_optimization_warm_start_from_dataset,
)

from .analysis import (
    analyze_surrogate as analyze_surrogate,
)
from .analysis import (
    compare_runs as compare_runs,
)
from .analysis import (
    correlate_files as correlate_files,
)
from .analysis import (
    vna_offline_replay as vna_offline_replay,
)
from .reporting import (
    _CURRENT_RECIPE_VERSION as _CURRENT_RECIPE_VERSION,
)
from .reporting import (
    _generate_reproduce_py as _generate_reproduce_py,
)
from .reporting import (
    doctor as doctor,
)
from .reporting import (
    generate_report_for_run as generate_report_for_run,
)
from .reporting import (
    get_metrics as get_metrics,
)
from .reporting import (
    list_models as list_models,
)
from .reporting import (
    recipe_migrate as recipe_migrate,
)
from .reporting import (
    replay_run as replay_run,
)
from .reporting import (
    repro_export as repro_export,
)
from .reporting import (
    run_link as run_link,
)
from .reporting import (
    run_tolerance as run_tolerance,
)
from .run_core import (
    _make_progress_reporter as _make_progress_reporter,
)
from .run_core import (
    agent_apply as agent_apply,
)
from .run_core import (
    agent_propose as agent_propose,
)
from .run_core import (
    dry_run as dry_run,
)
from .run_core import (
    run_once as run_once,
)
from .run_core import (
    validate_recipe as validate_recipe,
)
from .tuning import (
    poll_job as poll_job,
)
from .tuning import (
    run_once_async as run_once_async,
)
from .tuning import (
    start_tune as start_tune,
)
from .tuning import (
    start_tune_async as start_tune_async,
)
from .tuning import (
    start_tune_multi as start_tune_multi,
)

_register_actions(
    agent_propose=agent_propose,
    agent_apply=agent_apply,
    validate_recipe=validate_recipe,
    get_metrics=get_metrics,
)

# ══ T2 巨石拆分 facade（aurora_g W7-S1，2026-10-19）══════════════════
# 本文件原为单文件巨石，实现按职责域迁入上方 re-export 的子模块；此处
# 逐名显式 re-export 全部模块级名（公开面快照钉：拆分前后 dir() 逐名
# 相等；redundant-alias=PEP 484 显式 re-export 惯例）。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数）。扇出清单由各子模块 globals 按名自动构建。
_SUBMODULES = (['run_core', 'analysis', 'tuning', 'reporting'])


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
