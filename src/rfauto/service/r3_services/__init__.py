"""
Separated from api.py to avoid write-tool truncation (#108/#112).
Imported by api.py via: from rfauto.service.r3_services import *

6g: Solver visualization protocol
6h: Solver management (registry list + add/remove)
6i: Approval inbox (Gate pending items)
6j: LLM conversation (direct service layer)
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .chat import (
    _SYSTEM_PROMPT as _SYSTEM_PROMPT,
)
from .chat import (
    CHAT_SETTINGS_PATH as CHAT_SETTINGS_PATH,
)
from .chat import (
    SYSTEM_PROMPT_PATH as SYSTEM_PROMPT_PATH,
)
from .chat import (
    SYSTEM_PROMPT_SCHEMA as SYSTEM_PROMPT_SCHEMA,
)
from .chat import (
    AgentChat as AgentChat,
)
from .chat import (
    _execute_tool as _execute_tool,
)
from .chat import (
    _llm_chat_completion as _llm_chat_completion,
)
from .chat import (
    _load_prompt_doc as _load_prompt_doc,
)
from .chat import (
    _prompt_warn_emitted as _prompt_warn_emitted,
)
from .chat import (
    _resolve_recipe as _resolve_recipe,
)
from .chat import (
    contextlib as contextlib,
)
from .chat import (
    get_chat_settings as get_chat_settings,
)
from .chat import (
    get_chat_settings_raw as get_chat_settings_raw,
)
from .chat import (
    get_system_prompt as get_system_prompt,
)
from .chat import (
    get_system_prompt_meta as get_system_prompt_meta,
)
from .chat import (
    save_chat_settings as save_chat_settings,
)
from .fence import (
    FS_SENSITIVE_DIR_NAMES as FS_SENSITIVE_DIR_NAMES,
)
from .fence import (
    FS_SENSITIVE_FILE_NAMES as FS_SENSITIVE_FILE_NAMES,
)
from .fence import (
    RECIPE_HELP as RECIPE_HELP,
)
from .fence import (
    WORKCOPY_REVIEW_HINT as WORKCOPY_REVIEW_HINT,
)
from .fence import (
    _fs_sensitive_dir_hit as _fs_sensitive_dir_hit,
)
from .fence import (
    _fs_within_roots as _fs_within_roots,
)
from .fence import (
    _scan_recipe_dir as _scan_recipe_dir,
)
from .fence import (
    _workcopy_root as _workcopy_root,
)
from .fence import (
    fs_allowed_roots as fs_allowed_roots,
)
from .fence import (
    fs_list as fs_list,
)
from .fence import (
    fs_read_fence as fs_read_fence,
)
from .fence import (
    list_recipes as list_recipes,
)
from .fence import (
    os as os,
)
from .governance import (
    _CHANGE_KINDS as _CHANGE_KINDS,
)
from .governance import (
    _RESOURCE_CAPACITY_PATH as _RESOURCE_CAPACITY_PATH,
)
from .governance import (
    _RESOURCE_SCOPES as _RESOURCE_SCOPES,
)
from .governance import (
    _STATUS_BY_EVENT as _STATUS_BY_EVENT,
)
from .governance import (
    RegistryDB as RegistryDB,
)
from .governance import (
    _append_change_event as _append_change_event,
)
from .governance import (
    _apply_change as _apply_change,
)
from .governance import (
    _apply_resource_capacity as _apply_resource_capacity,
)
from .governance import (
    _approval_id as _approval_id,
)
from .governance import (
    _approval_kind as _approval_kind,
)
from .governance import (
    _approval_payload as _approval_payload,
)
from .governance import (
    _approve_change as _approve_change,
)
from .governance import (
    _audit_path as _audit_path,
)
from .governance import (
    _change_decided as _change_decided,
)
from .governance import (
    _change_entries as _change_entries,
)
from .governance import (
    _change_id as _change_id,
)
from .governance import (
    _current_solver_names as _current_solver_names,
)
from .governance import (
    _find_change as _find_change,
)
from .governance import (
    _find_proposal_in_audit as _find_proposal_in_audit,
)
from .governance import (
    _find_proposal_in_db as _find_proposal_in_db,
)
from .governance import (
    _list_pending_changes as _list_pending_changes,
)
from .governance import (
    _load_resource_capacity_config as _load_resource_capacity_config,
)
from .governance import (
    _open_approval_db as _open_approval_db,
)
from .governance import (
    _pending_from_audit as _pending_from_audit,
)
from .governance import (
    _pending_from_db as _pending_from_db,
)
from .governance import (
    _propose_resource_change as _propose_resource_change,
)
from .governance import (
    _propose_solver_registration as _propose_solver_registration,
)
from .governance import (
    _read_audit_entries as _read_audit_entries,
)
from .governance import (
    _record_approval_event_in_db as _record_approval_event_in_db,
)
from .governance import (
    _reject_change as _reject_change,
)
from .governance import (
    _sync_approvals_to_db as _sync_approvals_to_db,
)
from .governance import (
    approve_proposal as approve_proposal,
)
from .governance import (
    json as json,
)
from .governance import (
    list_pending_approvals as list_pending_approvals,
)
from .solvers import (
    Any as Any,
)
from .solvers import (
    Path as Path,
)
from .solvers import (
    add_solver_to_config as add_solver_to_config,
)
from .solvers import (
    error_envelope as error_envelope,
)
from .solvers import (
    list_registered_solvers as list_registered_solvers,
)
from .solvers import (
    list_solver_visualizations as list_solver_visualizations,
)
from .solvers import (
    ok_envelope as ok_envelope,
)
from .solvers import (
    remove_solver_from_config as remove_solver_from_config,
)
from .solvers import (
    spice_tool_status as spice_tool_status,
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
_SUBMODULES = (['solvers', 'governance', 'chat', 'fence'])


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
