"""G1 REST API：service 层能力的 OpenAPI 化薄壳。

设计红线（薄壳纪律）：路由是薄壳——参数校验 / HTTP 状态映射 /
OpenAPI 文档在本模块，业务语义全部仍在 service 层（health / run 查询 /
calculator 调用 / dataset 查询 / db·rag 只读查询 / slotline·transitions
确定性计算）；本模块不含任何物理数值计算（铁律 7）。

- 进出信封：成功 {"ok": true, "data": <service 结果>}；失败
 {"ok": false, "error": {"code": ..., "message": ...}}。
- OpenAPI 3.0.3 spec 由声明式 _ROUTE_TABLE 单源生成（路由与文档天然
 同步，杜绝"文档一套、路由另一套"）；validate_openapi_spec 提供无
 第三方依赖的结构自校验。
- 不接常驻服务器：create_rest_app() 返回 ASGI app，测试/嵌入式客户端
 直接驱动（starlette TestClient）；serve() 才起 uvicorn。
"""

from __future__ import annotations

import re
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

API_PREFIX = "/api/v1"
OPENAPI_VERSION = "3.0.3"
API_TITLE = "rfauto REST API"
API_DESCRIPTION = "rfauto service 层能力的薄壳 REST 封装（G1，）"

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_NOT_FOUND_MARKERS = ("不存在", "未注册", "未找到", "not found")


class BadRequestError(Exception):
  """请求体/参数校验失败（app 级 exception handler 统一转 400 信封）。"""

  def __init__(self, code: str, message: str) -> None:
    super().__init__(message)
    self.code = code
    self.message = message


# ---------------------------------------------------------------------------
# 信封与错误映射
# ---------------------------------------------------------------------------

def _ok(data: Any) -> JSONResponse:
  return JSONResponse({"ok": True, "data": data})


def _error(status_code: int, code: str, message: str) -> JSONResponse:
  return JSONResponse(
    {"ok": False, "error": {"code": code, "message": message}},
    status_code=status_code,
  )


def _messages(result: dict[str, Any]) -> list[str]:
  """从 service 结果抽错误文本（errors 列表优先，其次单 error 串）。"""
  errors = result.get("errors")
  if isinstance(errors, list) and errors:
    return [str(e) for e in errors]
  if result.get("error"):
    return [str(result["error"])]
  return ["service 返回 ok=False 但未提供错误信息"]


def _is_not_found(result: dict[str, Any]) -> bool:
  """service 层"资源不存在"标记 → HTTP 404（否则 400 非法输入）。"""
  return any(
    marker in message
    for message in _messages(result)
    for marker in _NOT_FOUND_MARKERS
  )


def _failure(result: dict[str, Any]) -> JSONResponse:
  messages = _messages(result)
  message = messages[0] if len(messages) == 1 else "; ".join(messages)
  if _is_not_found(result):
    return _error(404, "not_found", message)
  return _error(400, "invalid_request", message)


async def _bad_request_handler(request: Request, exc: Exception) -> JSONResponse:
  error = exc if isinstance(exc, BadRequestError) else BadRequestError(
    "bad_request", str(exc))
  return _error(400, error.code, error.message)


async def _json_body(request: Request) -> dict[str, Any]:
  """解析 JSON 请求体；非法 JSON / 非对象 → BadRequestError（400 信封）。"""
  try:
    body = await request.json()
  except Exception as exc: # JSONDecodeError 等
    raise BadRequestError("bad_json", f"请求体必须是合法 JSON: {exc}") from exc
  if not isinstance(body, dict):
    raise BadRequestError("invalid_request", "请求体必须是 JSON 对象")
  return body


# ---------------------------------------------------------------------------
# 端点（薄壳：调 service → 映射状态码）
# ---------------------------------------------------------------------------

async def api_health(request: Request) -> JSONResponse:
  """系统健康：包版本 + 已注册模型（确定性，无外部探测/网络）。"""
  from rfauto import __version__
  from rfauto.service.api import list_models

  models = list_models().get("models") or []
  return _ok({
    "status": "ok",
    "version": __version__,
    "n_models": len(models),
    "models": list(models),
  })


async def api_openapi(request: Request) -> JSONResponse:
  """OpenAPI 3.0.3 规范（未包信封，直接返回 spec 对象）。"""
  return JSONResponse(openapi_spec())


async def api_list_runs(request: Request) -> JSONResponse:
  """run 列表（ui_service.list_runs 薄壳）。"""
  from rfauto.service import ui_service

  raw = request.query_params.get("limit", "50")
  try:
    limit = int(raw)
  except (TypeError, ValueError):
    return _error(400, "invalid_request", f"limit 必须是整数，收到 {raw!r}")
  if limit < 1 or limit > 1000:
    return _error(400, "invalid_request", f"limit 必须在 [1, 1000]，收到 {limit}")
  return _ok(ui_service.list_runs(limit=limit))


async def api_run_detail(request: Request) -> JSONResponse:
  """单次 run 全量中间产物（ui_service.run_detail 薄壳）。"""
  from rfauto.service import ui_service

  result = ui_service.run_detail(request.path_params["run_id"])
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


_FALSE_STRINGS = frozenset({"0", "false", "no", "off"})


async def api_list_calculators(request: Request) -> JSONResponse:
  """计算器清单（calculator_service.list_calculators 薄壳）。

  ``?include_experimental=false`` 剔除实验键（默认列出并打 experimental 标签）。
  """
  from rfauto.service.calculator_service import list_calculators

  raw = request.query_params.get("include_experimental", "true")
  include_experimental = str(raw).strip().lower() not in _FALSE_STRINGS
  return _ok(list_calculators(include_experimental=include_experimental))


async def api_run_calculator(request: Request) -> JSONResponse:
  """执行一个计算器（calculator_service.run_calculator 薄壳）。

  body.allow_experimental（bool|null 三态）透传：实验性公式默认拒跑，
  True 显式放行、False 显式拒绝、缺省读配置 calculators.allow_experimental。
  """
  from rfauto.service.calculator_service import run_calculator

  body = await _json_body(request)
  params = body.get("params")
  if params is not None and not isinstance(params, dict):
    return _error(400, "invalid_request", "params 必须是对象或省略")
  allow_experimental = body.get("allow_experimental")
  if allow_experimental is not None and not isinstance(allow_experimental, bool):
    return _error(400, "invalid_request",
           "allow_experimental 必须是布尔值或省略")
  result = run_calculator(request.path_params["name"], params or {},
              allow_experimental=allow_experimental)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def api_query_dataset(request: Request) -> JSONResponse:
  """数据集直查（dataset_service.query_dataset 薄壳）。"""
  from rfauto.service.dataset_service import query_dataset

  body = await _json_body(request)
  name = body.get("name")
  if not isinstance(name, str) or not name:
    return _error(400, "invalid_request", "name 必须是非空字符串")
  kwargs: dict[str, Any] = {}
  for key in ("where", "columns", "limit", "model", "study_name"):
    if body.get(key) is not None:
      kwargs[key] = body[key]
  result = query_dataset(name, **kwargs)
  if not result.get("ok"):
    # 错误文案收敛（审查 P1-2 同批）：仅"数据集不存在"保留原文（404
    # 语义需要）；其余拒绝一律统一文案，不透传 where 原文/引擎细节
    # ——注入 payload 的回执不得成为探测 oracle。
    if _is_not_found(result):
      messages = _messages(result)
      message = messages[0] if len(messages) == 1 else "; ".join(messages)
      return _error(404, "not_found", message)
    return _error(400, "invalid_request",
           "查询被拒绝: where 表达式或查询参数非法"
           "（原始引擎错误不透出）")
  return _ok(result)


# ---- datasets 余量（dataset_insights 八接口薄壳，E1 收口 re-export）-----

def _require_name(body: dict[str, Any]) -> str:
  name = body.get("name")
  if not isinstance(name, str) or not name:
    raise BadRequestError("invalid_request", "name 必须是非空字符串")
  return name


def _opt_int(body: dict[str, Any], key: str) -> int | None:
  """可选整数参数：缺省/None → None；非整数（含 bool）→ 400。"""
  value = body.get(key)
  if value is None:
    return None
  if isinstance(value, bool) or not isinstance(value, int):
    raise BadRequestError("invalid_request", f"{key} 必须是整数")
  return value


def _opt_bool(body: dict[str, Any], key: str) -> bool | None:
  """可选布尔参数：缺省/None → None；非 bool → 400（不做 "yes" 强转）。"""
  value = body.get(key)
  if value is None:
    return None
  if not isinstance(value, bool):
    raise BadRequestError("invalid_request", f"{key} 必须是布尔值")
  return value


def _opt_str(body: dict[str, Any], key: str) -> str | None:
  value = body.get(key)
  if value is None:
    return None
  if not isinstance(value, str):
    raise BadRequestError("invalid_request", f"{key} 必须是字符串")
  return value


def _opt_number(body: dict[str, Any], key: str) -> float | None:
  """可选数值参数：缺省/None → None；非数值（含 bool）→ 400。"""
  value = body.get(key)
  if value is None:
    return None
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    raise BadRequestError("invalid_request", f"{key} 必须是数值")
  return value


def _require_numbers(body: dict[str, Any],
           keys: tuple[str, ...]) -> dict[str, Any] | None:
  """必填数值参数收集：任一缺失/非数值 → None（调用方统一回 400）。

  只挡"非 JSON 数值"；有效域/单位语义仍在 service 层（越域拒绝进信封）。
  """
  kwargs: dict[str, Any] = {}
  for key in keys:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
      return None
    kwargs[key] = value
  return kwargs


def _dataset_result(result: dict[str, Any]) -> JSONResponse:
  """dataset_insights 结果 → 信封：双集污染（overlap_ids 非空）映射 409
  conflict（状态冲突而非输入非法），其余沿用 _failure（404/400）。"""
  if result.get("ok"):
    return _ok(result)
  if result.get("overlap_ids"):
    messages = _messages(result)
    return _error(409, "conflict",
           messages[0] if len(messages) == 1 else "; ".join(messages))
  return _failure(result)


async def api_list_datasets(request: Request) -> JSONResponse:
  """数据集注册表总览（dataset_insights.list_datasets 薄壳）。"""
  from rfauto.service.dataset_insights import list_datasets

  visibility = request.query_params.get("visibility") or None
  return _dataset_result(list_datasets(visibility=visibility))


async def api_dataset_coverage(request: Request) -> JSONResponse:
  """点数/参数空间覆盖度（dataset_insights.dataset_coverage 薄壳）。"""
  from rfauto.service.dataset_insights import dataset_coverage

  body = await _json_body(request)
  name = _require_name(body)
  kwargs: dict[str, Any] = {}
  bins = _opt_int(body, "bins")
  if bins is not None:
    kwargs["bins"] = bins
  return _dataset_result(dataset_coverage(name, **kwargs))


async def api_dataset_annotate_ground_truth(request: Request) -> JSONResponse:
  """ground truth 标注回写（dataset_insights.annotate_ground_truth 薄壳）。"""
  from rfauto.service.dataset_insights import annotate_ground_truth

  body = await _json_body(request)
  name = _require_name(body)
  kwargs: dict[str, Any] = {}
  threshold = _opt_int(body, "threshold")
  if threshold is not None:
    kwargs["threshold"] = threshold
  return _dataset_result(annotate_ground_truth(name, **kwargs))


async def api_dataset_neural_operator_readiness(request: Request) -> JSONResponse:
  """6.3 神经算子解锁进度（dataset_insights.neural_operator_readiness 薄壳）。"""
  from rfauto.service.dataset_insights import neural_operator_readiness

  body = await _json_body(request)
  name = _require_name(body)
  kwargs: dict[str, Any] = {}
  threshold = _opt_int(body, "threshold")
  if threshold is not None:
    kwargs["threshold"] = threshold
  return _dataset_result(neural_operator_readiness(name, **kwargs))


async def api_dataset_set_visibility(request: Request) -> JSONResponse:
  """公开/私有切换（dataset_insights.set_dataset_visibility 薄壳）。"""
  from rfauto.service.dataset_insights import set_dataset_visibility

  body = await _json_body(request)
  name = _require_name(body)
  visibility = body.get("visibility")
  if not isinstance(visibility, str) or not visibility:
    return _error(400, "invalid_request",
           "visibility 必须是非空字符串（public/private）")
  return _dataset_result(set_dataset_visibility(name, visibility))


async def api_dataset_export_hf(request: Request) -> JSONResponse:
  """HuggingFace 布局导出（dataset_insights.export_hf_dataset 薄壳）。"""
  from rfauto.service.dataset_insights import export_hf_dataset

  body = await _json_body(request)
  name = _require_name(body)
  kwargs: dict[str, Any] = {}
  lic = _opt_str(body, "license")
  if lic is not None:
    kwargs["license"] = lic
  allow_private = _opt_bool(body, "allow_private")
  if allow_private is not None:
    kwargs["allow_private"] = allow_private
  return _dataset_result(export_hf_dataset(name, **kwargs))


async def api_dataset_register_public(request: Request) -> JSONResponse:
  """公开集注册路径（dataset_insights.register_public_dataset 薄壳）。"""
  from rfauto.service.dataset_insights import register_public_dataset

  body = await _json_body(request)
  name = _require_name(body)
  kwargs: dict[str, Any] = {}
  for key in ("source", "license"):
    value = _opt_str(body, key)
    if value is not None:
      kwargs[key] = value
  promote = _opt_bool(body, "promote")
  if promote is not None:
    kwargs["promote"] = promote
  return _dataset_result(register_public_dataset(name, **kwargs))


async def api_dataset_sets(request: Request) -> JSONResponse:
  """公开/私有双集装载 + 防污染检查（dataset_insights.load_dataset_sets
  薄壳；id 交集非空 → 409 conflict）。"""
  from rfauto.service.dataset_insights import load_dataset_sets

  return _dataset_result(load_dataset_sets())


# ---- db / rag / 工作目录发现 / slotline·transitions（只读透传，F-R2-3）-----
# 四批新增壳的 REST/SDK 只读查询面补齐：零逻辑转发 service 层（规则 4）；
# db 只暴露 status/query_safe 只读口（init/migrate/reindex 写操作不暴露），
# importer 只暴露 discover（import 写数据集不暴露）；slotline/transitions
# 五入口全是确定性计算（数值只出内核，铁律 7）。

async def api_db_status(request: Request) -> JSONResponse:
  """注册表状态盘点（db_service.db_status 薄壳，只读不建库）。"""
  from rfauto.service.db_service import db_status

  return _ok(db_status(request.query_params.get("db_path") or None))


async def api_db_query(request: Request) -> JSONResponse:
  """只读查询注册表（db_service.db_query_safe 薄壳：SELECT 白名单 +
  ? 占位符参数绑定；拒绝/执行错误进信封）。"""
  from rfauto.service.db_service import db_query_safe

  body = await _json_body(request)
  sql = body.get("sql")
  if not isinstance(sql, str) or not sql:
    return _error(400, "invalid_request", "sql 必须是非空字符串")
  kwargs: dict[str, Any] = {}
  params = body.get("params")
  if params is not None:
    if not isinstance(params, list):
      return _error(400, "invalid_request", "params 必须是标量数组或省略")
    kwargs["params"] = params
  limit = _opt_int(body, "limit")
  if limit is not None:
    kwargs["limit"] = limit
  db_path = _opt_str(body, "db_path")
  if db_path is not None:
    kwargs["db_path"] = db_path
  result = db_query_safe(sql, **kwargs)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def _rag_corpus_call(request: Request, corpus_fn: Any) -> JSONResponse:
  """rag query/explain 共用薄壳：docs_dir/runs_dir 缺省 docs/runs、
  显式 null 跳过该来源（与 CLI/MCP 同口径）；top_k/runs_limit 薄层
  校验挡掉 service 的 ValueError（那里抛出，这里进 400 信封）。"""
  body = await _json_body(request)
  text = body.get("text")
  if not isinstance(text, str) or not text.strip():
    return _error(400, "invalid_request", "text 必须是非空字符串")
  kwargs: dict[str, Any] = {"base_dir": "."}
  top_k = _opt_int(body, "top_k")
  if top_k is not None:
    if top_k < 1:
      return _error(400, "invalid_request", "top_k 必须 >= 1")
    kwargs["top_k"] = top_k
  runs_limit = _opt_int(body, "runs_limit")
  if runs_limit is not None:
    if runs_limit < 0:
      return _error(400, "invalid_request", "runs_limit 必须是非负整数")
    kwargs["runs_limit"] = runs_limit
  for key, default in (("docs_dir", "docs"), ("runs_dir", "runs")):
    if key in body:
      value = _opt_str(body, key)
      if value is not None:
        kwargs[key] = value
    else:
      kwargs[key] = default
  result = corpus_fn(text, **kwargs)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def api_rag_query(request: Request) -> JSONResponse:
  """RAG 词法检索（rag_service.query_corpus 薄壳，只读、citation 可溯）。"""
  from rfauto.service.rag_service import query_corpus

  return await _rag_corpus_call(request, query_corpus)


async def api_rag_explain(request: Request) -> JSONResponse:
  """RAG 检索 + 逐词 BM25 分数明细（rag_service.explain_corpus 薄壳）。"""
  from rfauto.service.rag_service import explain_corpus

  return await _rag_corpus_call(request, explain_corpus)


async def api_dataset_discover_workdir(request: Request) -> JSONResponse:
  """工作目录形态真机产物发现（dataset_service.discover_workdir_candidates
  薄壳，只读；import 是写操作不经 REST）。"""
  from rfauto.service.dataset_service import discover_workdir_candidates

  models_raw = request.query_params.get("models")
  models = ([m.strip() for m in models_raw.split(",") if m.strip()]
       if models_raw else None)
  result = discover_workdir_candidates(
    request.query_params.get("runs_root") or "runs", models=models)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def api_slotline_analyze(request: Request) -> JSONResponse:
  """槽线闭式分析（slotline_service.slotline_analysis 薄壳，确定性内核）。"""
  from rfauto.service.slotline_service import slotline_analysis

  body = await _json_body(request)
  kwargs = _require_numbers(body, ("w_mm", "h_mm", "epsilon_r", "freq_ghz"))
  if kwargs is None:
    return _error(400, "invalid_request",
           "w_mm/h_mm/epsilon_r/freq_ghz 必须都是数值")
  result = slotline_analysis(**kwargs)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def api_slotline_synth(request: Request) -> JSONResponse:
  """槽线综合：目标 Z0 → 槽宽（slotline_service.slotline_synthesis 薄壳）。"""
  from rfauto.service.slotline_service import slotline_synthesis

  body = await _json_body(request)
  kwargs = _require_numbers(body, ("z0_ohm", "h_mm", "epsilon_r", "freq_ghz"))
  if kwargs is None:
    return _error(400, "invalid_request",
           "z0_ohm/h_mm/epsilon_r/freq_ghz 必须都是数值")
  result = slotline_synthesis(**kwargs)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def _transition_design_call(request: Request, design_fn: Any) -> JSONResponse:
  """transitions msl-slot / marchand-balun 共用薄壳（四必填 + 两可选数值）。"""
  body = await _json_body(request)
  kwargs = _require_numbers(body, ("f0_ghz", "h_mm", "er", "w_slot_mm"))
  if kwargs is None:
    return _error(400, "invalid_request",
           "f0_ghz/h_mm/er/w_slot_mm 必须都是数值")
  for key in ("tan_d", "z_msl_target"):
    value = _opt_number(body, key)
    if value is not None:
      kwargs[key] = value
  result = design_fn(**kwargs)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


async def api_transition_msl_slot(request: Request) -> JSONResponse:
  """Roberts/Knorr MSL↔槽线过渡设计（slotline_service.msl_slot_transition_design
  薄壳）。"""
  from rfauto.service.slotline_service import msl_slot_transition_design

  return await _transition_design_call(request, msl_slot_transition_design)


async def api_transition_marchand_balun(request: Request) -> JSONResponse:
  """双槽臂 Marchand 巴伦（最小族）设计（slotline_service.marchand_balun_design
  薄壳）。"""
  from rfauto.service.slotline_service import marchand_balun_design

  return await _transition_design_call(request, marchand_balun_design)


async def api_transition_marchand_two_section(request: Request) -> JSONResponse:
  """两节对称 Marchand 电路级综合（slotline_service.marchand_two_section_synthesis
  薄壳；realizable=False 是合法结果非错误，#122）。"""
  from rfauto.service.slotline_service import marchand_two_section_synthesis

  body = await _json_body(request)
  kwargs: dict[str, Any] = {}
  for key in ("f0_ghz", "z_unbal_ohm", "z_bal_diff_ohm", "er", "h_mm",
        "tan_d", "s_min_mm", "w_max_mm", "z_c_ohm"):
    value = _opt_number(body, key)
    if value is not None:
      kwargs[key] = value
  band = body.get("band_ghz")
  if band is not None:
    if not isinstance(band, list):
      return _error(400, "invalid_request",
             "band_ghz 必须是 [f_lo, f_hi] 数组或省略")
    kwargs["band_ghz"] = band
  result = marchand_two_section_synthesis(**kwargs)
  if not result.get("ok"):
    return _failure(result)
  return _ok(result)


# ---------------------------------------------------------------------------
# OpenAPI 文档（路由单源 → spec）
# ---------------------------------------------------------------------------

def _schema_ref(name: str) -> dict[str, Any]:
  return {"$ref": f"#/components/schemas/{name}"}


def _envelope_response(description: str) -> dict[str, Any]:
  return {
    "description": description,
    "content": {"application/json": {"schema": _schema_ref("Envelope")}},
  }


def _raw_response(description: str, schema: dict[str, Any]) -> dict[str, Any]:
  return {
    "description": description,
    "content": {"application/json": {"schema": schema}},
  }


_ROUTE_TABLE: list[dict[str, Any]] = [
  {
    "path": f"{API_PREFIX}/health",
    "methods": ["GET"],
    "endpoint": api_health,
    "summary": "系统健康：包版本 + 已注册模型",
    "operation_id": "getHealth",
    "tags": ["system"],
    "parameters": [],
    "responses": {"200": _envelope_response("系统健康信息")},
  },
  {
    "path": f"{API_PREFIX}/openapi.json",
    "methods": ["GET"],
    "endpoint": api_openapi,
    "summary": "OpenAPI 3.0.3 规范",
    "operation_id": "getOpenApi",
    "tags": ["system"],
    "parameters": [],
    "responses": {"200": _raw_response("OpenAPI 文档对象", {"type": "object"})},
  },
  {
    "path": f"{API_PREFIX}/runs",
    "methods": ["GET"],
    "endpoint": api_list_runs,
    "summary": "run 列表",
    "operation_id": "listRuns",
    "tags": ["runs"],
    "parameters": [{
      "name": "limit", "in": "query", "required": False,
      "schema": {"type": "integer", "minimum": 1, "maximum": 1000,
            "default": 50},
      "description": "返回条数上限",
    }],
    "responses": {
      "200": _envelope_response("run 列表"),
      "400": _envelope_response("limit 非法"),
    },
  },
  {
    "path": f"{API_PREFIX}/runs/{{run_id}}",
    "methods": ["GET"],
    "endpoint": api_run_detail,
    "summary": "单次 run 全量中间产物",
    "operation_id": "getRun",
    "tags": ["runs"],
    "parameters": [{
      "name": "run_id", "in": "path", "required": True,
      "schema": {"type": "string"},
    }],
    "responses": {
      "200": _envelope_response("run 明细"),
      "404": _envelope_response("run 不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/calculators",
    "methods": ["GET"],
    "endpoint": api_list_calculators,
    "summary": "计算器清单（含参数自描述；实验键带 experimental 标签）",
    "operation_id": "listCalculators",
    "tags": ["calculators"],
    "parameters": [{
      "name": "include_experimental", "in": "query", "required": False,
      "schema": {"type": "boolean", "default": True},
      "description": "false 时剔除实验性公式（n_experimental/experimental 名单仍报告）",
    }],
    "responses": {"200": _envelope_response("计算器清单")},
  },
  {
    "path": f"{API_PREFIX}/calculators/{{name}}/run",
    "methods": ["POST"],
    "endpoint": api_run_calculator,
    "summary": "执行一个确定性计算器",
    "operation_id": "runCalculator",
    "tags": ["calculators"],
    "parameters": [{
      "name": "name", "in": "path", "required": True,
      "schema": {"type": "string"},
    }],
    "request_schema": "CalculatorRunRequest",
    "responses": {
      "200": _envelope_response("计算结果"),
      "400": _envelope_response("参数缺失/不匹配"),
      "404": _envelope_response("计算器未注册"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/query",
    "methods": ["POST"],
    "endpoint": api_query_dataset,
    "summary": "数据集直查（谓词下推；parquet/hdf5 同管线）",
    "operation_id": "queryDataset",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetQueryRequest",
    "responses": {
      "200": _envelope_response("查询结果"),
      "400": _envelope_response("查询参数非法"),
      "404": _envelope_response("数据集不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets",
    "methods": ["GET"],
    "endpoint": api_list_datasets,
    "summary": "数据集注册表总览（点数/GT 标注/可见性/格式/HF 导出态）",
    "operation_id": "listDatasets",
    "tags": ["datasets"],
    "parameters": [{
      "name": "visibility", "in": "query", "required": False,
      "schema": {"type": "string", "enum": ["public", "private"]},
      "description": "按可见性过滤（缺省不过滤）",
    }],
    "responses": {
      "200": _envelope_response("数据集列表"),
      "400": _envelope_response("visibility 非法"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/coverage",
    "methods": ["POST"],
    "endpoint": api_dataset_coverage,
    "summary": "点数分布 + 参数空间覆盖度统计",
    "operation_id": "datasetCoverage",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetCoverageRequest",
    "responses": {
      "200": _envelope_response("覆盖度统计"),
      "400": _envelope_response("参数非法"),
      "404": _envelope_response("数据集不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/ground-truth/annotate",
    "methods": ["POST"],
    "endpoint": api_dataset_annotate_ground_truth,
    "summary": "ground truth 标注回写 manifest（幂等重标）",
    "operation_id": "annotateGroundTruth",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetThresholdRequest",
    "responses": {
      "200": _envelope_response("标注 + 6.3 解锁进度"),
      "400": _envelope_response("参数非法"),
      "404": _envelope_response("数据集不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/neural-operator-readiness",
    "methods": ["POST"],
    "endpoint": api_dataset_neural_operator_readiness,
    "summary": "6.3 神经算子解锁进度（器件族级门槛）",
    "operation_id": "neuralOperatorReadiness",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetThresholdRequest",
    "responses": {
      "200": _envelope_response("解锁进度"),
      "400": _envelope_response("参数非法"),
      "404": _envelope_response("数据集不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/visibility",
    "methods": ["POST"],
    "endpoint": api_dataset_set_visibility,
    "summary": "公开/私有可见性切换",
    "operation_id": "setDatasetVisibility",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetVisibilityRequest",
    "responses": {
      "200": _envelope_response("切换结果"),
      "400": _envelope_response("visibility 非法"),
      "404": _envelope_response("数据集不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/export-hf",
    "methods": ["POST"],
    "endpoint": api_dataset_export_hf,
    "summary": "HuggingFace datasets 布局导出（private 默认拒绝）",
    "operation_id": "exportHfDataset",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetExportHfRequest",
    "responses": {
      "200": _envelope_response("导出产物路径"),
      "400": _envelope_response("private 拒绝导出/参数非法"),
      "404": _envelope_response("数据集不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/public/register",
    "methods": ["POST"],
    "endpoint": api_dataset_register_public,
    "summary": "公开集注册路径（私有 id 默认拒绝，promote 显式转公开）",
    "operation_id": "registerPublicDataset",
    "tags": ["datasets"],
    "parameters": [],
    "request_schema": "DatasetPublicRegisterRequest",
    "responses": {
      "200": _envelope_response("注册结果 + 双集检查"),
      "400": _envelope_response("私有 id 拒绝注册/参数非法"),
      "409": _envelope_response("双集污染：id 交集非空"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/sets",
    "methods": ["GET"],
    "endpoint": api_dataset_sets,
    "summary": "公开/私有双集装载 + 防污染检查",
    "operation_id": "loadDatasetSets",
    "tags": ["datasets"],
    "parameters": [],
    "responses": {
      "200": _envelope_response("双集状态（无交集）"),
      "400": _envelope_response("公开集注册表结构非法"),
      "409": _envelope_response("双集污染：id 交集非空"),
    },
  },
  {
    "path": f"{API_PREFIX}/db/status",
    "methods": ["GET"],
    "endpoint": api_db_status,
    "summary": "注册表状态盘点（路径/存在性/schema 版本/各表行数，只读不建库）",
    "operation_id": "dbStatus",
    "tags": ["db"],
    "parameters": [{
      "name": "db_path", "in": "query", "required": False,
      "schema": {"type": "string"},
      "description": "注册表 SQLite 路径（缺省 env RFAUTO_REGISTRY_DB "
              "或 runs/registry.sqlite）",
    }],
    "responses": {"200": _envelope_response("注册表状态")},
  },
  {
    "path": f"{API_PREFIX}/db/query",
    "methods": ["POST"],
    "endpoint": api_db_query,
    "summary": "只读查询注册表（SELECT 白名单 + ? 占位符参数绑定）",
    "operation_id": "dbQuery",
    "tags": ["db"],
    "parameters": [],
    "request_schema": "DbQueryRequest",
    "responses": {
      "200": _envelope_response("查询结果（columns/rows/truncated）"),
      "400": _envelope_response("SQL 被白名单拒绝/参数非法"),
    },
  },
  {
    "path": f"{API_PREFIX}/rag/query",
    "methods": ["POST"],
    "endpoint": api_rag_query,
    "summary": "RAG 词法检索（BM25，只读、citation 可溯）",
    "operation_id": "ragQuery",
    "tags": ["rag"],
    "parameters": [],
    "request_schema": "RagQueryRequest",
    "responses": {
      "200": _envelope_response("检索命中（score + citation + snippet）"),
      "400": _envelope_response("参数非法"),
      "404": _envelope_response("来源目录不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/rag/explain",
    "methods": ["POST"],
    "endpoint": api_rag_explain,
    "summary": "RAG 检索 + 逐词 BM25 分数明细（打分可溯）",
    "operation_id": "ragExplain",
    "tags": ["rag"],
    "parameters": [],
    "request_schema": "RagQueryRequest",
    "responses": {
      "200": _envelope_response("命中附 score_breakdown"),
      "400": _envelope_response("参数非法"),
      "404": _envelope_response("来源目录不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/datasets/discover-workdir",
    "methods": ["GET"],
    "endpoint": api_dataset_discover_workdir,
    "summary": "工作目录形态真机产物发现（无 meta.json 的 runs 子目录，只读）",
    "operation_id": "discoverWorkdir",
    "tags": ["datasets"],
    "parameters": [
      {
        "name": "runs_root", "in": "query", "required": False,
        "schema": {"type": "string", "default": "runs"},
        "description": "runs 根目录",
      },
      {
        "name": "models", "in": "query", "required": False,
        "schema": {"type": "string"},
        "description": "逗号分隔器件族过滤（slotline/hairpin/marchand/"
                "mline/helix）",
      },
    ],
    "responses": {
      "200": _envelope_response("候选清单（逐目录曲线数/引擎/端口数）"),
      "400": _envelope_response("未知器件族"),
      "404": _envelope_response("runs 目录不存在"),
    },
  },
  {
    "path": f"{API_PREFIX}/slotline/analyze",
    "methods": ["POST"],
    "endpoint": api_slotline_analyze,
    "summary": "槽线闭式分析（Janaswamy–Schaubert：λ'/λ0、εeff、β、Z0）",
    "operation_id": "slotlineAnalysis",
    "tags": ["slotline"],
    "parameters": [],
    "request_schema": "SlotlineAnalysisRequest",
    "responses": {
      "200": _envelope_response("闭式分析结果"),
      "400": _envelope_response("参数缺失/越有效域拒绝（不外推）"),
    },
  },
  {
    "path": f"{API_PREFIX}/slotline/synth",
    "methods": ["POST"],
    "endpoint": api_slotline_synth,
    "summary": "槽线综合：目标 Z0 → 槽宽（brentq 反解 + 回代自洽）",
    "operation_id": "slotlineSynthesis",
    "tags": ["slotline"],
    "parameters": [],
    "request_schema": "SlotlineSynthesisRequest",
    "responses": {
      "200": _envelope_response("综合结果（w_mm 等）"),
      "400": _envelope_response(
        "参数非法/越域（目标不可达=200+realizable=False 合法结果，D5）"),
    },
  },
  {
    "path": f"{API_PREFIX}/transitions/msl-slot",
    "methods": ["POST"],
    "endpoint": api_transition_msl_slot,
    "summary": "Roberts/Knorr MSL↔槽线过渡设计参数（微带 HJ 综合 + 槽线闭式）",
    "operation_id": "mslSlotTransitionDesign",
    "tags": ["transitions"],
    "parameters": [],
    "request_schema": "TransitionDesignRequest",
    "responses": {
      "200": _envelope_response("设计参数 + 预声明过渡门"),
      "400": _envelope_response("参数缺失/越域"),
    },
  },
  {
    "path": f"{API_PREFIX}/transitions/marchand-balun",
    "methods": ["POST"],
    "endpoint": api_transition_marchand_balun,
    "summary": "双槽臂 Marchand 巴伦（最小族）设计参数（对照几何）",
    "operation_id": "marchandBalunDesign",
    "tags": ["transitions"],
    "parameters": [],
    "request_schema": "TransitionDesignRequest",
    "responses": {
      "200": _envelope_response("设计参数 + 预声明巴伦门"),
      "400": _envelope_response("参数缺失/越域"),
    },
  },
  {
    "path": f"{API_PREFIX}/transitions/marchand-two-section",
    "methods": ["POST"],
    "endpoint": api_transition_marchand_two_section,
    "summary": "两节对称 Marchand 电路级综合（realizable=False 是合法结果）",
    "operation_id": "marchandTwoSectionSynthesis",
    "tags": ["transitions"],
    "parameters": [],
    "request_schema": "MarchandTwoSectionRequest",
    "responses": {
      "200": _envelope_response("综合设计 + 电路级自检门"),
      "400": _envelope_response("参数非法/越域"),
    },
  },
]


def _schemas() -> dict[str, Any]:
  return {
    "ErrorInfo": {
      "type": "object",
      "required": ["code", "message"],
      "properties": {
        "code": {"type": "string"},
        "message": {"type": "string"},
      },
    },
    "ErrorEnvelope": {
      "type": "object",
      "required": ["ok", "error"],
      "properties": {
        "ok": {"type": "boolean", "enum": [False]},
        "error": _schema_ref("ErrorInfo"),
      },
    },
    "SuccessEnvelope": {
      "type": "object",
      "required": ["ok", "data"],
      "properties": {
        "ok": {"type": "boolean", "enum": [True]},
        "data": {"type": "object"},
      },
    },
    "Envelope": {
      "oneOf": [
        _schema_ref("SuccessEnvelope"),
        _schema_ref("ErrorEnvelope"),
      ],
    },
    "CalculatorRunRequest": {
      "type": "object",
      "properties": {
        "params": {"type": "object", "additionalProperties": True},
        "allow_experimental": {
          "type": "boolean", "nullable": True,
          "description": "实验性公式放行开关：true 显式放行、false 显式拒绝、"
                  "缺省读配置 calculators.allow_experimental",
        },
      },
    },
    "DatasetQueryRequest": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "where": {"type": "string", "nullable": True},
        "columns": {
          "type": "array", "items": {"type": "string"},
          "nullable": True,
        },
        "limit": {"type": "integer", "minimum": 1, "default": 100},
        "model": {"type": "string", "nullable": True},
        "study_name": {"type": "string", "nullable": True},
      },
    },
    "DatasetCoverageRequest": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "bins": {"type": "integer", "minimum": 2, "default": 10},
      },
    },
    "DatasetThresholdRequest": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "threshold": {"type": "integer", "minimum": 1, "default": 100},
      },
    },
    "DatasetVisibilityRequest": {
      "type": "object",
      "required": ["name", "visibility"],
      "properties": {
        "name": {"type": "string"},
        "visibility": {"type": "string", "enum": ["public", "private"]},
      },
    },
    "DatasetExportHfRequest": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "license": {"type": "string", "nullable": True},
        "allow_private": {"type": "boolean", "default": False},
      },
    },
    "DatasetPublicRegisterRequest": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "source": {"type": "string", "nullable": True},
        "license": {"type": "string", "nullable": True},
        "promote": {"type": "boolean", "default": False},
      },
    },
    "DbQueryRequest": {
      "type": "object",
      "required": ["sql"],
      "properties": {
        "sql": {"type": "string",
            "description": "单条只读 SELECT（? 占位符）"},
        "params": {
          "type": "array", "items": {}, "nullable": True,
          "description": "占位符标量参数（str/int/float/bool/null）",
        },
        "limit": {"type": "integer", "minimum": 1, "default": 200,
             "description": "返回行数上限（最大 5000，超出截断）"},
        "db_path": {"type": "string", "nullable": True},
      },
    },
    "RagQueryRequest": {
      "type": "object",
      "required": ["text"],
      "properties": {
        "text": {"type": "string"},
        "top_k": {"type": "integer", "minimum": 1, "default": 5},
        "docs_dir": {"type": "string", "nullable": True,
               "description": "文档目录（null 跳过该来源；"
                      "缺省 docs）"},
        "runs_dir": {"type": "string", "nullable": True,
               "description": "runs 历史目录（null 跳过该来源；"
                      "缺省 runs）"},
        "runs_limit": {"type": "integer", "minimum": 0,
                "nullable": True},
      },
    },
    "SlotlineAnalysisRequest": {
      "type": "object",
      "required": ["w_mm", "h_mm", "epsilon_r", "freq_ghz"],
      "properties": {
        "w_mm": {"type": "number", "description": "槽宽 mm"},
        "h_mm": {"type": "number", "description": "基板厚 mm"},
        "epsilon_r": {"type": "number", "description": "相对介电常数"},
        "freq_ghz": {"type": "number", "description": "频率 GHz"},
      },
    },
    "SlotlineSynthesisRequest": {
      "type": "object",
      "required": ["z0_ohm", "h_mm", "epsilon_r", "freq_ghz"],
      "properties": {
        "z0_ohm": {"type": "number", "description": "目标特性阻抗 Ω"},
        "h_mm": {"type": "number", "description": "基板厚 mm"},
        "epsilon_r": {"type": "number", "description": "相对介电常数"},
        "freq_ghz": {"type": "number", "description": "频率 GHz"},
      },
    },
    "TransitionDesignRequest": {
      "type": "object",
      "required": ["f0_ghz", "h_mm", "er", "w_slot_mm"],
      "properties": {
        "f0_ghz": {"type": "number", "description": "设计中心频率 GHz"},
        "h_mm": {"type": "number", "description": "基板厚 mm"},
        "er": {"type": "number", "description": "相对介电常数"},
        "w_slot_mm": {"type": "number", "description": "槽宽 mm"},
        "tan_d": {"type": "number", "default": 0.0037,
             "description": "损耗角正切"},
        "z_msl_target": {"type": "number", "default": 50.0,
                 "description": "微带馈线目标阻抗 Ω"},
      },
    },
    "MarchandTwoSectionRequest": {
      "type": "object",
      "properties": {
        "f0_ghz": {"type": "number", "default": 2.5},
        "z_unbal_ohm": {"type": "number", "default": 50.0},
        "z_bal_diff_ohm": {"type": "number", "default": 280.0},
        "er": {"type": "number", "default": 3.66},
        "h_mm": {"type": "number", "default": 1.524},
        "tan_d": {"type": "number", "default": 0.0037},
        "s_min_mm": {"type": "number", "default": 0.1},
        "w_max_mm": {"type": "number", "default": 6.0},
        "z_c_ohm": {"type": "number", "nullable": True,
              "description": "耦合段 Z_c（缺省自动扫描）"},
        "band_ghz": {
          "type": "array", "items": {"type": "number"},
          "minItems": 2, "maxItems": 2, "nullable": True,
          "description": "自检带 [f_lo, f_hi] GHz（缺省 f0±10%）",
        },
      },
    },
  }


def _operation(entry: dict[str, Any]) -> dict[str, Any]:
  operation: dict[str, Any] = {
    "operationId": entry["operation_id"],
    "summary": entry["summary"],
    "tags": list(entry["tags"]),
    "parameters": entry.get("parameters", []),
    "responses": entry["responses"],
  }
  request_schema = entry.get("request_schema")
  if request_schema:
    operation["requestBody"] = {
      "required": True,
      "content": {
        "application/json": {"schema": _schema_ref(request_schema)},
      },
    }
  return operation


def _tag_names() -> list[str]:
  names: list[str] = []
  for entry in _ROUTE_TABLE:
    for tag in entry["tags"]:
      if tag not in names:
        names.append(tag)
  return names


def openapi_spec() -> dict[str, Any]:
  """由路由表单源生成 OpenAPI 3.0.3 spec。"""
  from rfauto import __version__

  paths: dict[str, Any] = {}
  for entry in _ROUTE_TABLE:
    item = paths.setdefault(entry["path"], {})
    for method in entry["methods"]:
      item[method.lower()] = _operation(entry)
  return {
    "openapi": OPENAPI_VERSION,
    "info": {
      "title": API_TITLE,
      "version": __version__,
      "description": API_DESCRIPTION,
    },
    "servers": [{"url": "/"}],
    "tags": [{"name": name} for name in _tag_names()],
    "paths": paths,
    "components": {"schemas": _schemas()},
  }


def _iter_refs(node: Any):
  if isinstance(node, dict):
    ref = node.get("$ref")
    if isinstance(ref, str):
      yield ref
    for value in node.values():
      yield from _iter_refs(value)
  elif isinstance(node, list):
    for item in node:
      yield from _iter_refs(item)


def _resolve_ref(spec: dict[str, Any], ref: str) -> Any:
  if not ref.startswith("#/"):
    return None
  node: Any = spec
  for part in ref[2:].split("/"):
    if not isinstance(node, dict) or part not in node:
      return None
    node = node[part]
  return node


def validate_openapi_spec(spec: Any) -> dict[str, Any]:
  """无第三方依赖的 OpenAPI 3.x 结构自校验。

  校验项：openapi 版本串 / info.title+version / paths 非空且每个 path
  item 有 HTTP 方法、operationId 唯一、responses 非空且响应带
  description / components.schemas 非空 / 所有 $ref 可在文档内解析。
  返回 {"ok": bool, "errors": [...]}（不抛异常）。
  """
  errors: list[str] = []
  if not isinstance(spec, dict):
    return {"ok": False, "errors": ["spec 必须是对象"]}

  version = spec.get("openapi")
  if not (isinstance(version, str) and re.fullmatch(r"3\.\d+\.\d+", version)):
    errors.append("openapi 必须是 3.x.y 版本串")

  info = spec.get("info")
  if not isinstance(info, dict):
    errors.append("info 必须是对象")
  else:
    if not info.get("title"):
      errors.append("info.title 不能为空")
    if not info.get("version"):
      errors.append("info.version 不能为空")

  paths = spec.get("paths")
  if not (isinstance(paths, dict) and paths):
    errors.append("paths 必须是非空对象")
  else:
    operation_ids: list[str] = []
    for path, item in paths.items():
      if not (isinstance(path, str) and path.startswith("/")):
        errors.append(f"path 必须以 / 开头: {path!r}")
        continue
      if not (isinstance(item, dict) and item):
        errors.append(f"path item 必须是非空对象: {path}")
        continue
      if not any(method in item for method in _HTTP_METHODS):
        errors.append(f"path item 无 HTTP 操作方法: {path}")
      for method in _HTTP_METHODS:
        operation = item.get(method)
        if operation is None:
          continue
        if not isinstance(operation, dict):
          errors.append(f"{method.upper()} {path} 操作必须是对象")
          continue
        operation_id = operation.get("operationId")
        if not operation_id:
          errors.append(f"{method.upper()} {path} 缺 operationId")
        elif operation_id in operation_ids:
          errors.append(f"operationId 重复: {operation_id}")
        else:
          operation_ids.append(operation_id)
        responses = operation.get("responses")
        if not (isinstance(responses, dict) and responses):
          errors.append(f"{method.upper()} {path} 缺 responses")
          continue
        for code, response in responses.items():
          if not (isinstance(response, dict) and response.get("description")):
            errors.append(
              f"{method.upper()} {path} 响应 {code} 缺 description")

  components = spec.get("components")
  if not isinstance(components, dict):
    errors.append("components 必须是对象")
  else:
    schemas = components.get("schemas")
    if not (isinstance(schemas, dict) and schemas):
      errors.append("components.schemas 必须是非空对象")

  for ref in _iter_refs(spec):
    if _resolve_ref(spec, ref) is None:
      errors.append(f"$ref 无法解析: {ref}")

  return {"ok": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# ASGI app / 服务器入口
# ---------------------------------------------------------------------------

def create_rest_app() -> Starlette:
  """构建 REST ASGI app（测试与 rfauto rest-api 共用）。"""
  routes = [
    Route(entry["path"], entry["endpoint"], methods=list(entry["methods"]))
    for entry in _ROUTE_TABLE
  ]
  return Starlette(
    routes=routes,
    exception_handlers={BadRequestError: _bad_request_handler},
  )


def serve(host: str = "127.0.0.1", port: int = 8644) -> None:
  """阻塞启动 REST 服务（本地回环，不对外网监听）。"""
  import uvicorn

  uvicorn.run(create_rest_app(), host=host, port=port, log_level="warning")
