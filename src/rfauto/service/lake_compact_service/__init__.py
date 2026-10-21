"""lake_compact_service —— RB-WN-1 湖语义压缩三件套（W3-A，sa_specs2 §五）。

三件（spec §5.2 逐件）：

① **h5 白名单保留策略**：``plan_h5_retention`` 纯读构建保留/删除/理由
分类三清单（推导式白名单——meta 无 run_type 字段（全湖实测零命中），
保留面只能从指针源与目录名启发推导）：锚注册表（knowledge/anchors.yaml）
路径指针→anchor_evidence；sim_ci golden 基线（knowledge/simci_baseline.yaml，
XD-5 pin 面）run_id→baseline_ref；tests/golden 等 golden 指针→golden_judged；
目录名启发（anchor/arb/arbitration/hfsswin/golden/review/gate）→
name_heuristic。理由=none 才可删（§5.4 宁保守——漏删只损失空间不损失证据）。
在跑/半途 run（无 meta，#144 形态）任何档都不可删；``--apply`` 真删由 CLI
层执行且缺省 dry-run。

② **et/ht 内容寻址去重**：原语在 infra/lake_blob_store（adapters 增量钩子
共用，分层契约），本模块给全湖 plan（纯读扫描+hash 分组统计）与 apply 包装
（受保护面零触碰）。

③ **sparams VF 有界摘要**：``sparams_summary`` 复用 core/macromodel 的
request_from_touchstone/fit_macromodel，产出 ``sparams.vf.json``
（{schema_version, n_poles, poles, residues, d_coeff, freq_band,
linf_error_linear, linf_error_db, rms_error, fidelity_class,
passivity_state, provenance}）。误差界是摘要组成部分（铁律 7 变体）：
L∞_linear ≤ 5e-3（≈dB 域 ≤0.05dB，#339 对拍门口径）→ lossless_equivalent；
超界如实标 bounded_lossy 带 linf 值——**不带误差界的摘要不落盘**。摘要
单激励部分矩阵只对已测元素（#314 掩码口径）计误差，零填充元素不进拟合
误差裁判；原 csv 不删（F3 冷压层处置），摘要=检索加速面非替代面。
消费面：lake index ``vf_summary`` 列（lake_service 单源）+ ``read_sparams_
summary``/``s_model_from_summary`` 零解压读面。

**golden 零改写红线（#325）**：本模块对受保护面（指针源命中目录+启发命中
目录+在跑 run）零写零替——dry-run 纯读；apply 只处理删除清单点名文件（白
名单式点名删除，规则 3），且 golden_rewrite_audit 钉"删除清单∩保护面=∅"。

**真湖放量口径（W3-A criteria 预声明）**：真实压缩/删除/迁移等破坏性动作
绝不自动执行——CLI 缺省 dry-run，--apply 需 XD-5 golden 基线已 pin 互锁
（sim_ci_service.default_baseline_path 在档且 schema 合法）。

无 __all__：公开 API 快照（DP-17）按 __all__ 登记，本件保持无 __all__ 即
不入快照（共享计数面零碰）。
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .common import (
    _META_NAMES as _META_NAMES,
)
from .common import (
    Any as Any,
)
from .common import (
    Path as Path,
)
from .common import (
    _dir_size_bytes as _dir_size_bytes,
)
from .common import (
    _git_head_short as _git_head_short,
)
from .common import (
    _meta_file as _meta_file,
)
from .common import (
    _norm as _norm,
)
from .common import (
    _norm_under as _norm_under,
)
from .common import (
    _read_json_object as _read_json_object,
)
from .common import (
    _repo_root_guess as _repo_root_guess,
)
from .common import (
    json as json,
)
from .common import (
    os as os,
)
from .common import (
    subprocess as subprocess,
)
from .et_ht_dedup import (
    _inflight_dir_norms as _inflight_dir_norms,
)
from .et_ht_dedup import (
    apply_et_ht_dedup as apply_et_ht_dedup,
)
from .et_ht_dedup import (
    plan_et_ht_dedup as plan_et_ht_dedup,
)
from .retention import (
    _H5_SUFFIX as _H5_SUFFIX,
)
from .retention import (
    _RUNS_POINTER_RE as _RUNS_POINTER_RE,
)
from .retention import (
    DEFAULT_POINTER_SOURCES as DEFAULT_POINTER_SOURCES,
)
from .retention import (
    HEURISTIC_TOKENS as HEURISTIC_TOKENS,
)
from .retention import (
    JUDGED_ARTIFACTS as JUDGED_ARTIFACTS,
)
from .retention import (
    JUDGED_STATUSES as JUDGED_STATUSES,
)
from .retention import (
    PurePosixPath as PurePosixPath,
)
from .retention import (
    _all_run_dirs as _all_run_dirs,
)
from .retention import (
    _chain_protected as _chain_protected,
)
from .retention import (
    _dir_is_name_protected as _dir_is_name_protected,
)
from .retention import (
    _dir_judged as _dir_judged,
)
from .retention import (
    _dir_recent as _dir_recent,
)
from .retention import (
    _exempt_hit as _exempt_hit,
)
from .retention import (
    _meta_mtime as _meta_mtime,
)
from .retention import (
    _nearest_meta_dir as _nearest_meta_dir,
)
from .retention import (
    _run_sort_key as _run_sort_key,
)
from .retention import (
    _validate_exempt_subtrees as _validate_exempt_subtrees,
)
from .retention import (
    apply_h5_retention as apply_h5_retention,
)
from .retention import (
    datetime as datetime,
)
from .retention import (
    error_envelope as error_envelope,
)
from .retention import (
    extract_pointer_dirs as extract_pointer_dirs,
)
from .retention import (
    ok_envelope as ok_envelope,
)
from .retention import (
    plan_h5_retention as plan_h5_retention,
)
from .retention import (
    re as re,
)
from .retention import (
    time as time,
)
from .retention import (
    timezone as timezone,
)
from .reversible import (
    DEFAULT_OBSERVATION_DAYS as DEFAULT_OBSERVATION_DAYS,
)
from .reversible import (
    H5_BLOB_KIND as H5_BLOB_KIND,
)
from .reversible import (
    REVERSIBLE_MANIFEST_FORMAT as REVERSIBLE_MANIFEST_FORMAT,
)
from .reversible import (
    _blob_path_for as _blob_path_for,
)
from .reversible import (
    _move_into_blob as _move_into_blob,
)
from .reversible import (
    _resolve_manifest_targets as _resolve_manifest_targets,
)
from .reversible import (
    apply_h5_retention_reversible as apply_h5_retention_reversible,
)
from .reversible import (
    contextlib as contextlib,
)
from .reversible import (
    purge_blobs_from_manifest as purge_blobs_from_manifest,
)
from .reversible import (
    restore_h5_from_manifest as restore_h5_from_manifest,
)
from .reversible import (
    shutil as shutil,
)
from .reversible import (
    timedelta as timedelta,
)
from .vf_summary import (
    LINF_LOSSLESS_THRESHOLD as LINF_LOSSLESS_THRESHOLD,
)
from .vf_summary import (
    VF_SUMMARY_NAME as VF_SUMMARY_NAME,
)
from .vf_summary import (
    VF_SUMMARY_SCHEMA as VF_SUMMARY_SCHEMA,
)
from .vf_summary import (
    _fit_request_from_sparams_csv as _fit_request_from_sparams_csv,
)
from .vf_summary import (
    _rational_response as _rational_response,
)
from .vf_summary import (
    hashlib as hashlib,
)
from .vf_summary import (
    plan_sparams_summaries as plan_sparams_summaries,
)
from .vf_summary import (
    read_sparams_summary as read_sparams_summary,
)
from .vf_summary import (
    s_model_from_summary as s_model_from_summary,
)
from .vf_summary import (
    sparams_summary as sparams_summary,
)

# ══ T2 巨石拆分 facade（架构批 W3-S1，2026-10-19）══════════════════
# 本文件原为单文件巨石 service/lake_compact_service.py，实现按职责域迁入
# 上方 re-export 的子模块（common/et_ht_dedup/retention/reversible/
# vf_summary）；此处逐名显式 re-export 全部模块级名（公开面快照钉：拆分
# 前后 dir() 逐名相等，内部证据目录 一次性证明；
# redundant-alias=PEP 484 显式 re-export 惯例）。原件无 __all__（DP-17
# 公开 API 快照不入册，共享计数面零碰），门面同样保持无 __all__。
#
# setattr 双写扇出（AU-1 工艺，commit 121bce3 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局——与单文件时代"补丁即全局生效"逐位一致（含模块级状态
# 与按名内调的实现函数）。扇出清单由各子模块 globals 按名自动构建。
_SUBMODULES = (['common', 'et_ht_dedup', 'retention', 'reversible', 'vf_summary'])


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
