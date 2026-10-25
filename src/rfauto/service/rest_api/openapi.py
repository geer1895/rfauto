"""rest_api.openapi —— 路由表单源、OpenAPI spec 与 ASGI 装配。

自 rest_api.py 巨石按职责域拆分（aurora_h W3-S2，AU-1 工艺）：
``_ROUTE_TABLE``（声明式单源）→ ``openapi_spec()``/``validate_openapi_spec
()``/``endpoint_inventory()`` → ``create_rest_app()``/``serve()`` 整链与
openapi.json 端点逐字节搬迁。**整链单模块承载是零漂移约束**：表项在
import 时引用 handler 与 spec 端点名、spec 端点又读 ``openapi_spec``
（单文件时代同一命名空间全局读），拆二必循环；本模块头部对全部
handler 子模块的模块级 import 保证注册先于构表——注册顺序语义与
单文件时代逐位一致（W3-S2 副作用链显式化）。
"""

from __future__ import annotations

import re
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from rfauto.service.envelope import error_envelope, ok_envelope

from .calculators import api_list_calculators, api_run_calculator
from .common import (
    _HTTP_METHODS,
    API_DESCRIPTION,
    API_PREFIX,
    API_TITLE,
    OPENAPI_VERSION,
    BadRequestError,
    _bad_request_handler,
)
from .datasets import (
    api_dataset_annotate_ground_truth,
    api_dataset_coverage,
    api_dataset_discover_workdir,
    api_dataset_export_hf,
    api_dataset_neural_operator_readiness,
    api_dataset_register_public,
    api_dataset_set_visibility,
    api_dataset_sets,
    api_list_datasets,
    api_query_dataset,
)
from .db import api_db_query, api_db_status
from .rag import api_rag_explain, api_rag_query
from .runs import api_list_runs, api_run_detail
from .slotline import (
    api_slotline_analyze,
    api_slotline_synth,
    api_transition_marchand_balun,
    api_transition_marchand_two_section,
    api_transition_msl_slot,
)
from .system import api_health


async def api_openapi(request: Request) -> JSONResponse:
    """OpenAPI 3.0.3 规范（未包信封，直接返回 spec 对象）。"""
    return JSONResponse(openapi_spec())


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
    from rfauto import __version__  # lazy: run-path（执行面按需取用）

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
        return error_envelope(["spec 必须是对象"])

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

    # ge8e W2 快偿（R5-06）：裸 ok 信封 → 构造器（键集/键序/语义零变化）
    if errors:
        return error_envelope(errors)
    return ok_envelope(errors=errors)


def _entry_uses_envelope(entry: dict[str, Any]) -> bool:
    """端点全部响应是否都走 Envelope $ref（False=raw 直出，如 openapi.json）。"""
    envelope_ref = _schema_ref("Envelope")["$ref"]
    for response in entry["responses"].values():
        schema = (response.get("content", {}).get("application/json", {})
                  or {}).get("schema", {})
        if schema.get("$ref") != envelope_ref:
            return False
    return True


def endpoint_inventory() -> dict[str, Any]:
    """全端点机器可读清单（程序化枚举 _ROUTE_TABLE 单源，防手抄漂移）。

    REST-B schema 导出面（openapi_spec() 同源派生）：逐端点给方法/路径/
    查询参数/请求 schema/响应码/信封形态摘要；完整 OpenAPI 3.0.3 spec 另见
    ``openapi_spec()``（线上 GET /api/v1/openapi.json）。返回 ok 信封
    （service 层 errors 契约形；REST 传输线形见 envelope_shape 摘要）。
    """
    endpoints: list[dict[str, Any]] = []
    n_operations = 0
    for entry in _ROUTE_TABLE:
        params = entry.get("parameters", [])
        n_operations += len(entry["methods"])
        endpoints.append({
            "path": entry["path"],
            "methods": list(entry["methods"]),
            "operation_id": entry["operation_id"],
            "summary": entry["summary"],
            "tags": list(entry["tags"]),
            "query_params": [p for p in params if p.get("in") == "query"],
            "path_params": [p for p in params if p.get("in") == "path"],
            "request_schema": entry.get("request_schema"),
            "response_codes": sorted(entry["responses"]),
            "envelope": _entry_uses_envelope(entry),
        })
    return ok_envelope(
        face="rest",
        api_prefix=API_PREFIX,
        openapi_version=OPENAPI_VERSION,
        openapi_endpoint=f"{API_PREFIX}/openapi.json",
        n_endpoints=len(endpoints),
        n_operations=n_operations,
        endpoints=endpoints,
        # 信封形态摘要=OpenAPI components 单源派生（schema 形态；具体示例见
        # 本模块 docstring 头注——棘轮面禁再造裸信封字面，REST-B 2026-10-14）
        envelope_shape={
            "success_schema": _schemas()["SuccessEnvelope"],
            "error_schema": _schemas()["ErrorEnvelope"],
            "note": "REST 传输面信封（对象形 error），与 service 层 "
                    "errors 列表契约不同形；见 docs/envelope_contract.md",
        },
    )


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
