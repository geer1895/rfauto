"""G1 REST API（§10.7）：service 层能力的 OpenAPI 化薄壳。

设计红线（内核立规注记 硬限制 4）：路由是薄壳——参数校验 / HTTP 状态映射 /
OpenAPI 文档在本模块，业务语义全部仍在 service 层（health / run 查询 /
calculator 调用 / dataset 查询 / db·rag 只读查询 / slotline·transitions
确定性计算）；本模块不含任何物理数值计算（铁律 7）。

双 HTTP 面职责边界（A-2，code_audit_slice6）：本模块是**程序化 REST 面**
（/api/v1/*，OpenAPI 化，传输壳禁业务逻辑，serve() 默认 8644）；人工
工作台面在 ui/server.py（/api/*，浏览器交互，loopback 8642）——两边各自
独立路由表，新增能力按消费方选面，不在两边互相转发。

- 进出信封：成功 {"ok": true, "data": <service 结果>}；失败
  {"ok": false, "error": {"code": ..., "message": ...}}。
- OpenAPI 3.0.3 spec 由声明式 _ROUTE_TABLE 单源生成（路由与文档天然
  同步，杜绝"文档一套、路由另一套"）；validate_openapi_spec 提供无
  第三方依赖的结构自校验。
- 不接常驻服务器：create_rest_app() 返回 ASGI app，测试/嵌入式客户端
  直接驱动（starlette TestClient）；serve() 才起 uvicorn。
"""

# ══ T2 巨石拆分 facade（aurora_h W3-S2，2026-10-19）══════════════════
# 本文件原为单文件巨石（service/rest_api.py，1417 行），实现按资源族
# 迁入上方 re-export 的子模块；公开面快照钉：拆分前后模块级名逐名相等
# （含私有助手——测试面按名取用）。**无 __all__**（公开 API 快照口径=
# 无 __all__ 记私有，新增即触金快照评审门）。
#
# 副作用链（import 期）显式声明——按下方 from-import 序：
#   1. common（常量/信封助手，仅依赖 envelope，零副作用）；
#   2. 八个 handler 族模块 system/runs/calculators/datasets/db/rag/
#      slotline（仅依赖 common，handler 定义零副作用）；
#   3. openapi（**模块级构造 _ROUTE_TABLE**：表项字面量引用全部
#      handler 名与 _envelope_response/_raw_response——单文件时代的
#      "模块尾注册序"等价物，由 openapi 自身头部的模块级 import 保证
#      handler 先就位；注册顺序语义与拆分前逐位一致。门面 import 序
#      为文档性冗余保险）。
#
# setattr 双写扇出（AU-1 工艺，lake_service W7-S1 先例）：monkeypatch/
# 测试面 ``setattr(本模块, name, value)`` 时同步写入全部持有该名的
# 子模块全局（按 vars() 建映射，from-import 持名也算持有）——与单文件
# 时代"补丁即全局生效"逐位一致（test_integ_b 的 create_rest_app/
# endpoint_inventory 注入缝即此语义）。

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from types import ModuleType as _ModuleType

from .calculators import (
    api_list_calculators as api_list_calculators,
)
from .calculators import (
    api_run_calculator as api_run_calculator,
)
from .common import (
    _FALSE_STRINGS as _FALSE_STRINGS,
)
from .common import (
    _HTTP_METHODS as _HTTP_METHODS,
)
from .common import (
    _NOT_FOUND_MARKERS as _NOT_FOUND_MARKERS,
)
from .common import (
    API_DESCRIPTION as API_DESCRIPTION,
)
from .common import (
    API_PREFIX as API_PREFIX,
)
from .common import (
    API_TITLE as API_TITLE,
)
from .common import (
    OPENAPI_VERSION as OPENAPI_VERSION,
)
from .common import (
    Any as Any,
)
from .common import (
    BadRequestError as BadRequestError,
)
from .common import (
    JSONResponse as JSONResponse,
)
from .common import (
    Request as Request,
)
from .common import (
    _bad_request_handler as _bad_request_handler,
)
from .common import (
    _error as _error,
)
from .common import (
    _failure as _failure,
)
from .common import (
    _is_not_found as _is_not_found,
)
from .common import (
    _json_body as _json_body,
)
from .common import (
    _messages as _messages,
)
from .common import (
    _ok as _ok,
)
from .common import (
    _opt_bool as _opt_bool,
)
from .common import (
    _opt_int as _opt_int,
)
from .common import (
    _opt_number as _opt_number,
)
from .common import (
    _opt_str as _opt_str,
)
from .common import (
    _require_name as _require_name,
)
from .common import (
    _require_numbers as _require_numbers,
)
from .common import (
    ok_envelope as ok_envelope,
)
from .datasets import (
    _dataset_result as _dataset_result,
)
from .datasets import (
    api_dataset_annotate_ground_truth as api_dataset_annotate_ground_truth,
)
from .datasets import (
    api_dataset_coverage as api_dataset_coverage,
)
from .datasets import (
    api_dataset_discover_workdir as api_dataset_discover_workdir,
)
from .datasets import (
    api_dataset_export_hf as api_dataset_export_hf,
)
from .datasets import (
    api_dataset_neural_operator_readiness as api_dataset_neural_operator_readiness,
)
from .datasets import (
    api_dataset_register_public as api_dataset_register_public,
)
from .datasets import (
    api_dataset_set_visibility as api_dataset_set_visibility,
)
from .datasets import (
    api_dataset_sets as api_dataset_sets,
)
from .datasets import (
    api_list_datasets as api_list_datasets,
)
from .datasets import (
    api_query_dataset as api_query_dataset,
)
from .db import (
    api_db_query as api_db_query,
)
from .db import (
    api_db_status as api_db_status,
)
from .openapi import (
    _ROUTE_TABLE as _ROUTE_TABLE,
)
from .openapi import (
    Route as Route,
)
from .openapi import (
    Starlette as Starlette,
)
from .openapi import (
    _entry_uses_envelope as _entry_uses_envelope,
)
from .openapi import (
    _envelope_response as _envelope_response,
)
from .openapi import (
    _iter_refs as _iter_refs,
)
from .openapi import (
    _operation as _operation,
)
from .openapi import (
    _raw_response as _raw_response,
)
from .openapi import (
    _resolve_ref as _resolve_ref,
)
from .openapi import (
    _schema_ref as _schema_ref,
)
from .openapi import (
    _schemas as _schemas,
)
from .openapi import (
    _tag_names as _tag_names,
)
from .openapi import (
    api_openapi as api_openapi,
)
from .openapi import (
    create_rest_app as create_rest_app,
)
from .openapi import (
    endpoint_inventory as endpoint_inventory,
)
from .openapi import (
    error_envelope as error_envelope,
)
from .openapi import (
    openapi_spec as openapi_spec,
)
from .openapi import (
    re as re,
)
from .openapi import (
    serve as serve,
)
from .openapi import (
    validate_openapi_spec as validate_openapi_spec,
)
from .rag import (
    _rag_corpus_call as _rag_corpus_call,
)
from .rag import (
    api_rag_explain as api_rag_explain,
)
from .rag import (
    api_rag_query as api_rag_query,
)
from .runs import (
    api_list_runs as api_list_runs,
)
from .runs import (
    api_run_detail as api_run_detail,
)
from .slotline import (
    _transition_design_call as _transition_design_call,
)
from .slotline import (
    api_slotline_analyze as api_slotline_analyze,
)
from .slotline import (
    api_slotline_synth as api_slotline_synth,
)
from .slotline import (
    api_transition_marchand_balun as api_transition_marchand_balun,
)
from .slotline import (
    api_transition_marchand_two_section as api_transition_marchand_two_section,
)
from .slotline import (
    api_transition_msl_slot as api_transition_msl_slot,
)
from .system import (
    api_health as api_health,
)

# ══ AU-1 facade setattr 双写扇出（lake_service W7-S1 同式）══════════
_SUBMODULES = ("common", "system", "runs", "calculators", "datasets",
               "db", "rag", "slotline", "openapi")


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
