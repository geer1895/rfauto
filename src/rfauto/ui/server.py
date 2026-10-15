"""rfauto 人工核验 UI（本地 web 服务，starlette + uvicorn）——装配薄壳。

设计红线（AGENTS）：路由是薄壳，全部业务在 service/ui_service.py（JSON 进出）；
只读 endpoints 无副作用，POST /api/run 复用 service.run_once（单写锁在那层）。
启动：rfauto ui（默认 127.0.0.1:8642，不对外网监听）。

双 HTTP 面职责边界（A-2，code_audit_slice6）：本模块是**人工工作台**
（/api/*，loopback 8642，浏览器交互消费）；程序化 REST 面在
service/rest_api.py（/api/v1/*，传输壳禁业务逻辑，8644）——两边各自独立
路由表，新增能力按消费方选面，不在两边互相转发。

aurora_d UI-R1（2026-10-14）：API handler 按域机械迁 rfauto/ui/routes/
（函数体逐字节不变，域清单见各模块 docstring）；CSP 策略（哈希钉常量+
中间件）迁 rfauto/ui/csp.py。本模块只保留 app 装配（create_ui_app/
exception_handlers/CSP 中间件接线/Mount/serve 启动逻辑）与既有引用路径
薄 re-export（campaign_app/edb_app/params/_TUNE_STATE/CSP/api_fs_list，
is 同一性契约见 test_uxb6_campaign_app_split/test_f1_ui_review_fixes/
test_w1e_ui_csp；其余 handler 消费方直走 rfauto.ui.routes.<域>）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from rfauto.ui import csp as csp_routes
from rfauto.ui.campaign_app import api_campaign_dashboard as api_campaign_dashboard
from rfauto.ui.campaign_app import api_campaign_queue as api_campaign_queue

# D-04 哈希钉既有消费面保持（test_w1e_ui_csp/test_ui_theme_boot 直 import）。
from rfauto.ui.csp import CSP_HEADER as CSP_HEADER
from rfauto.ui.csp import CSP_VALUE as CSP_VALUE
from rfauto.ui.edb_app import api_edb_status as api_edb_status

# A6 P0-2/A4 P0-3（review_aurora_next 审查，2026-10-13）：参数守卫单源迁
# rfauto/ui/params.py；本模块薄 re-export 保持既有引用路径
# rfauto.ui.server.ParamError/_int_param 不变（#116 教训：只经 import 名字
# 透传，禁止尾部重定义同名）。
from rfauto.ui.params import ParamError as ParamError
from rfauto.ui.params import _int_param as _int_param
from rfauto.ui.params import _json_body as _json_body

# aurora_d UI-R1：分域模块按命名空间收编（route 表引用 <域>_routes.<handler>
# ——同一对象透传，注册序零漂移）；既有消费面保持薄 re-export（test_fs_fence
# 直 import api_fs_list、test_a8d/test_f1 经 server_mod._TUNE_STATE setitem
# 就地置位——同一 dict 对象透传；#116 教训：只经 import 名字透传）。
from rfauto.ui.routes import agent as agent_routes
from rfauto.ui.routes import data as data_routes
from rfauto.ui.routes import events as events_routes
from rfauto.ui.routes import fieldviz as fieldviz_routes
from rfauto.ui.routes import importer as importer_routes
from rfauto.ui.routes import insight as insight_routes
from rfauto.ui.routes import measurement as measurement_routes
from rfauto.ui.routes import recipes as recipes_routes
from rfauto.ui.routes import runs as runs_routes
from rfauto.ui.routes import tools as tools_routes
from rfauto.ui.routes import tune as tune_routes
from rfauto.ui.routes.recipes import api_fs_list as api_fs_list
from rfauto.ui.routes.tune import _TUNE_STATE as _TUNE_STATE

_STATIC_DIR = Path(__file__).parent / "static"


async def index(request: Request) -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1"}


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def resolve_runs_mount(host: str, expose_runs: bool | None) -> bool:
    """三态裁决 runs/ 静态挂载：显式 True/False 优先；缺省=回环绑定开、非回环关。

    开源默认安全（R2-B-05）：runs/ 可能含未发布仿真数据，把 UI 绑到非回环地址
    （如 0.0.0.0）时不得未经确认整目录暴露，须显式 --expose-runs。
    """
    if expose_runs is not None:
        return expose_runs
    return _is_loopback(host)


def create_ui_app(include_runs_mount: bool = True) -> Starlette:
    """构建 UI 应用（测试与 rfauto ui 共用）。"""
    routes = [
        Route("/", index),
        Route("/api/runs", runs_routes.api_runs),
        # PR-4 双 run 对比：具体路径必须先于 /{run_id} 参数路由（顺序坑）
        Route("/api/runs/diff", runs_routes.api_runs_diff),
        Route("/api/runs/{run_id}", runs_routes.api_run_detail),
        # P-1 战役进度 SSE 桥（run_id 过滤；旧 3s 轮询端点保留为降级）
        Route("/api/runs/{run_id}/events/stream", runs_routes.api_run_events_stream),
        Route("/api/recipe", recipes_routes.api_recipe),
        Route("/api/recipe", recipes_routes.api_recipe_save, methods=["POST"]),
        Route("/api/model3d", recipes_routes.api_model3d, methods=["GET", "POST"]),
        Route("/api/run", runs_routes.api_run, methods=["POST"]),
        Route("/api/tune/start", tune_routes.api_tune_start, methods=["POST"]),
        Route("/api/tune/status", tune_routes.api_tune_status),
        Route("/api/tune/trials", tune_routes.api_tune_trials),
        # UI-R3 统一实时事件流（aurora_d）：tune/campaign 接入 SSE——统一信封
        # {seq,ts,kind,domain,payload}（单源 helper 在 routes/event_bus.py）；
        # 既有轮询端点（/api/tune/status、/api/campaign_queue）与 runs SSE 桥
        # 保留不动=兼容层，前端消费适配留后续席。
        Route("/api/tune/events/stream", events_routes.api_tune_events_stream),
        Route("/api/campaign_queue/events/stream",
              events_routes.api_campaign_queue_events_stream),
        Route("/api/events/stream", events_routes.api_events_stream),
        Route("/api/sandbox/drafts", agent_routes.api_sandbox_drafts),
        Route("/api/sandbox/diff", agent_routes.api_sandbox_diff),
        Route("/api/sandbox/promote", agent_routes.api_sandbox_promote, methods=["POST"]),
        Route("/api/solvers", agent_routes.api_solvers),
        Route("/api/solvers/viz", agent_routes.api_solvers_viz),
        Route("/api/inbox", agent_routes.api_inbox),
        Route("/api/inbox/approve", agent_routes.api_inbox_approve, methods=["POST"]),
        Route("/api/chat", agent_routes.api_chat, methods=["POST"]),
        Route("/api/chat/settings", agent_routes.api_chat_settings, methods=["GET", "POST"]),
        Route("/api/chat/reset", agent_routes.api_chat_reset, methods=["POST"]),
        Route("/api/chat/prompt", agent_routes.api_chat_prompt),
        Route("/api/chat/stats", agent_routes.api_chat_stats),
        Route("/api/fs/list", recipes_routes.api_fs_list),
        Route("/api/recipes", recipes_routes.api_recipes),
        Route("/api/hfss/import", importer_routes.api_hfss_import, methods=["POST"]),
        Route("/api/calibration", measurement_routes.api_calibration_runs),
        Route("/api/calibration/{run_id}", measurement_routes.api_calibration_view),
        Route("/api/cross_fidelity", measurement_routes.api_cross_fidelity),
        Route("/api/sparams/external", measurement_routes.api_sparams_external, methods=["POST"]),
        Route("/api/sparams/{run_id}", measurement_routes.api_sparams),
        Route("/api/cost_timeline", insight_routes.api_cost_timeline),
        Route("/api/reports", measurement_routes.api_reports),
        Route("/api/reports/content", measurement_routes.api_report_content),
        Route("/api/runs/{run_id}/figs/{name:path}", runs_routes.api_run_fig),
        Route("/api/pareto_runs", insight_routes.api_pareto_runs),
        Route("/api/calculators", tools_routes.api_calculators),
        Route("/api/calculators/run", tools_routes.api_calculators_run, methods=["POST"]),
        Route("/api/playground/runs", tools_routes.api_playground_runs),
        Route("/api/playground/predict", tools_routes.api_playground_predict, methods=["POST"]),
        Route("/api/playground/explore", tools_routes.api_playground_explore, methods=["POST"]),
        Route("/api/loop/boards", insight_routes.api_loop_boards),
        Route("/api/loop/board/{board_id}", insight_routes.api_loop_board),
        Route("/api/loop/control", insight_routes.api_loop_control, methods=["POST"]),
        Route("/api/farfield", fieldviz_routes.api_farfield_runs),
        Route("/api/farfield/{run_id}", fieldviz_routes.api_farfield_view),
        Route("/api/field", fieldviz_routes.api_field_runs),
        Route("/api/field/{run_id}", fieldviz_routes.api_field_view),
        Route("/api/smith/external", measurement_routes.api_smith_external, methods=["POST"]),
        Route("/api/smith/{run_id}", measurement_routes.api_smith),
        Route("/api/runs/{run_id}/pareto", insight_routes.api_pareto_view),
        Route("/api/runs/{run_id}/feasibility", insight_routes.api_feasibility),
        Route("/api/datasets", data_routes.api_datasets),
        Route("/api/datasets/{name}/preview", data_routes.api_dataset_preview),
        Route("/api/anchors", data_routes.api_anchors),
        Route("/api/anchors/{anchor_id}", data_routes.api_anchor_detail),
        Route("/api/uq/samples", data_routes.api_uq_samples),
        Route("/api/uq/yield", data_routes.api_uq_yield, methods=["POST"]),
        Route("/api/gallery", tools_routes.api_gallery),
        Route("/api/runs/{run_id}/dashboard", api_campaign_dashboard),
        # PR-9 调度队列页（ge8b Wave B 席B3）：战役队列+G13 决策日志（只读）
        Route("/api/campaign_queue", api_campaign_queue),
        # EDB 快车道状态页：产物清单+模板能力面（只读，照 campaign_app 先例）
        Route("/api/edb_status", api_edb_status),
        Route("/api/profile", tools_routes.api_profile, methods=["GET", "POST"]),
        Mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"),
    ]
    if include_runs_mount:
        # run 产物只读静态服务（人工核验直接看 PNG 曲线等中间产物）；
        # 非回环绑定默认关闭（R2-B-05 开源默认安全），显式 --expose-runs 才开。
        # A6 P1-5（review_aurora_next 审查）：目录改与 service 层 RUNS_DIR
        # 同源的绝对解析（此前字面 "runs" 相对 cwd——非仓库根目录 `rfauto ui`
        # 启动即 RuntimeError: Directory 'runs' does not exist，而 service 面
        # 同目录缺席只是返回空清单，两口径不一致）；目录缺席降级关闭挂载+
        # stderr 提示（对齐 R2-B-05 缺省关语义），API 面不受影响。
        from rfauto.service.ui_service import RUNS_DIR

        runs_root = Path(RUNS_DIR).absolute()
        if runs_root.is_dir():
            routes.append(Mount("/runs", StaticFiles(directory=str(runs_root)),
                                name="runs"))
        else:
            print(
                f"[rfauto ui] 提示：runs 目录不存在（{runs_root}），"
                "/runs 静态服务未挂载（API 面不受影响）。",
                file=sys.stderr,
            )
    # D-04：CSP 头全响应附加（HTML 面为主；JSON/静态资源带同名头无害）
    # A8-D：ParamError → 400 error 信封（非法查询/请求参数的失败面补齐）
    # A4 P0-3 保险环：未来新增调用点若漏过 _json_body 守卫直接裸
    # request.json()，JSON 解码错误仍归一 400 信封（非 500 纯文本）。
    return Starlette(
        routes=routes,
        middleware=[Middleware(csp_routes.ContentSecurityPolicyMiddleware)],
        exception_handlers={
            ParamError: _param_error_handler,
            json.JSONDecodeError: _param_error_handler,
        },
    )


async def _param_error_handler(request: Request, exc: Exception) -> JSONResponse:
    from rfauto.service.envelope import error_envelope

    return JSONResponse(error_envelope([str(exc)]), status_code=400)


def serve(
    host: str = "127.0.0.1", port: int = 8642, expose_runs: bool | None = None
) -> None:
    """阻塞启动 UI 服务器（rfauto ui 入口）。"""
    import uvicorn

    include_runs_mount = resolve_runs_mount(host, expose_runs)
    if not _is_loopback(host):
        if include_runs_mount:
            print(
                "[rfauto ui] 警告：--expose-runs 已显式开启，runs/ 目录静态服务"
                "随非回环绑定对外暴露（内含未发布仿真数据）。",
                file=sys.stderr,
            )
        else:
            print(
                "[rfauto ui] /runs 静态服务已随非回环绑定默认关闭"
                "（--expose-runs 可显式开启）。",
                file=sys.stderr,
            )
    uvicorn.run(
        create_ui_app(include_runs_mount=include_runs_mount), host=host, port=port,
        log_level="warning",
    )
