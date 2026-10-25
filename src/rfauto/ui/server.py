"""rfauto 人工核验 UI（本地 web 服务，starlette + uvicorn）——装配薄壳。

设计红线（内核立规注记）：路由是薄壳，全部业务在 service/ui_service.py（JSON 进出）；
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

import hmac
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from rfauto.ui import csp as csp_routes
from rfauto.ui.campaign_app import api_campaign_dashboard as api_campaign_dashboard
from rfauto.ui.campaign_app import api_campaign_queue as api_campaign_queue
from rfauto.ui.campaign_app import api_remote_resources as api_remote_resources

# W2-S4 远程机器面板（只读）——import 与注释分行（合流预检参数降级清偿）
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


async def index(request: Request) -> Any:
    return _index_html_response()


# ── 写端点 Bearer 鉴权（aurora_g W6-S2，R2 审计 §面5.4 / Top10 #5）────────
#
# R2 审计定谳：前端 api.js setApiToken Bearer 通道建成零消费、服务端零鉴权
# ——非回环绑定（内核立规注记 规则 0b 远程部署方向）下写端点（POST /api/run、
# /api/sandbox/promote、/api/chat 等）无凭据可调，是安全纵深唯一缺层。
# 最小可行面（零新依赖，env+Bearer）：
#   - env ``RFAUTO_UI_TOKEN`` **未设=零行为变化**（本机回环部署缺省安全，
#     逐请求读 env——测试经 monkeypatch.setenv 即插即用，无装配期快照）；
#   - 设定时**写端点**（POST/PUT/DELETE/PATCH）要求
#     ``Authorization: Bearer <token>``（hmac.compare_digest 常量时间比对），
#     失败归一 401 error 信封（与既有 _param_error_handler 同形）；
#   - **读端点豁免**（GET/HEAD/OPTIONS/SSE 流直通）——页面壳与只读数据面
#     不设闸（人工核验工作台的浏览语义不受扰）。
# 前端接线（同 env 源）：token 设定时 index 响应注入
# ``<meta name="rfauto-ui-token">``（pages/api.js 模块装配期读取一次 →
# setApiToken → apiFetch 全部请求自动附头）。浏览器进程读不到服务端 env，
# meta 注入是"同 env 源"的最小中继；安全语义=单操作者部署语境（页面可达
# 者即持令者）——门面价值在**非浏览器通道**（脚本/curl/跨机自动化）写端点
# 被拒；逐用户登录态不在本批（R1 #5 明示"登录态/token 注入入口最小面"）。
_AUTH_ENV = "RFAUTO_UI_TOKEN"
#: 写端点方法集（路由表全部写面=POST；PUT/DELETE/PATCH 前瞻收编，零成本）
_WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
_AUTH_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "


def ui_auth_token() -> str | None:
    """UI 写端点鉴权令牌（env 单源；空串视同未设=零行为变化）。"""
    value = os.environ.get(_AUTH_ENV)
    return value if value else None


class BearerAuthMiddleware:
    """纯 ASGI 中间件：RFAUTO_UI_TOKEN 设定时写端点校验 Bearer（P9-8→W6-S2）。

    与 CacheControlMiddleware 同构形态（#105 零故障面纪律）：非 http scope
    原样直通；token 未设直通；读方法直通；校验只做头部前缀+常量时间比对，
    无任何可抛路径落业务侧。401 走 service error 信封（消费方 errorText()
    回退链兼容），响应出站仍经外层 CSP/Cache-Control/GZip 中间件（安全头
    批对 401 同样附加——响应面一致性不因拒绝路径豁免）。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = ui_auth_token()
        if token is None:
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "GET").upper()
        if method not in _WRITE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        presented = headers.get(_AUTH_HEADER, "")
        expected = _BEARER_PREFIX + token
        if hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
            await self.app(scope, receive, send)
            return
        from rfauto.service.envelope import error_envelope

        msg = ("unauthorized: 写端点需要 Bearer 令牌"
               "（服务端 RFAUTO_UI_TOKEN 已启用鉴权）")
        resp = JSONResponse(error_envelope([msg]), status_code=401)
        await resp(scope, receive, send)


def _index_html_response() -> Any:
    """index 响应（token 未设=FileResponse 原路径逐字节不变；设定时注入
    token meta——供前端 api.js 装配期读取，CSP 哈希钉不受扰：meta 非内联
    脚本，test_w1e_ui_csp 双哈希门不触）。"""
    token = ui_auth_token()
    if token is None:
        return FileResponse(_STATIC_DIR / "index.html")
    text = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    meta = (f'<meta name="rfauto-ui-token" content="{html.escape(token, quote=True)}">'
            "\n")
    marker = "<head>"
    # head 缺席=结构守卫（#105 best-effort）：前置注入不阻断页面
    text = text.replace(marker, marker + "\n" + meta, 1) if marker in text \
        else meta + text
    return HTMLResponse(text)


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1"}


# ── Cache-Control 分域（aurora_g W1-S1，R1 审计 P9-1 v9 Top3）────────────
#
# R1 实证：真机 curl /static/vendor/echarts.min.js 有 etag/last-modified
# 但 cache-control 缺席——W7 走查首屏 26 请求每次导航全量条件重验证
# （RTT 串行排队），远程部署面放大。分域（按 scope.path 前缀，挂载拓扑
# 单源在本装配壳）：
#   /static/*（vendor/js/css 等 UI 自有资产）→ public, max-age=86400
#     （一日窗：无内容哈希不取 immutable/长窗，模块有版本演进，ETag 兜
#     过期后重验证）；
#   /runs/*（run 产物静态服务）→ public, max-age=300（审计口径短窗：
#     run 结束后产物不变，但实验中同名 fig 会改写——防陈旧误缓存）；
#   其余（/ 与 /api/*）→ no-cache 显式化（HTML 是 import 图入口必须每
#     导航重验证；API 动态面禁缓存；既有 ETag 链不受扰）；
#   **SSE 端点（路径含 /events/stream）零缓存头**（审计钉面：流式响应
#     不得挂任何缓存语义）。
_CACHE_STATIC_PREFIX_VALUE = "public, max-age=86400"
_CACHE_RUNS_PREFIX_VALUE = "public, max-age=300"
_CACHE_DEFAULT_VALUE = "no-cache"
_SSE_PATH_MARK = "/events/stream"
_CACHE_CONTROL_HEADER = "Cache-Control"


class CacheControlMiddleware:
    """纯 ASGI 中间件：按路径分域附加 Cache-Control（P9-1，SSE 豁免直通）。

    setitem 覆写语义单头不叠；非 http scope 原样直通（#105 同纪律：
    加固面零故障面——头写入不抛，scope.path 缺席按缺省域处理）。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if _SSE_PATH_MARK in path:
            await self.app(scope, receive, send)
            return
        if path.startswith("/runs"):
            value = _CACHE_RUNS_PREFIX_VALUE
        elif path.startswith("/static"):
            value = _CACHE_STATIC_PREFIX_VALUE
        else:
            value = _CACHE_DEFAULT_VALUE

        async def send_with_cache_control(message: Any) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[_CACHE_CONTROL_HEADER] = value
            await send(message)

        await self.app(scope, receive, send_with_cache_control)


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
        # W2-S3 失败诊断包读面（aurora_i 采纳 #3；具体路径先于参数路由无冲突，
        # 独立段名不与 /{run_id} 竞争——保守仍注册在其后）
        Route("/api/runs/{run_id}/failure_context",
              runs_routes.api_run_failure_context),
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
        # R3 设计 M2（aurora_i W2-S2）：指标词典悬浮说明数据面（只读；
        # 单键查询在 service 层 get_metric——REST 面不设未消费路由）
        Route("/api/metric-glossary", data_routes.api_metric_glossary),
        # R3 设计 M3（aurora_i W3-S1）：双引擎对照曲线数据面（只读；
        # 前端画廊抽屉"对照"标签页叠加图消费——runs 挂载默认关故必须
        # 服务层组装，解析走既有链，证据零改写）
        Route("/api/credibility/curves", data_routes.api_credibility_curves),
        Route("/api/gallery", tools_routes.api_gallery),
        Route("/api/runs/{run_id}/dashboard", api_campaign_dashboard),
        # PR-9 调度队列页（ge8b Wave B 席B3）：战役队列+G13 决策日志（只读）
        Route("/api/campaign_queue", api_campaign_queue),
        # W2-S4 远程机器面板：resources_view（recommend 推荐+probed_at）
        #   + 在途战役占用面（只读，照 campaign_queue 先例）
        Route("/api/remote/resources", api_remote_resources),
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
    # P8-1（aurora_f R1 审计 Top1）：全站 GZip 压缩——静态首载 2.61MB 线传
    # 压至 ~715KB（three.module.js 1.27MB→~350KB 级），远程/服务器部署
    # 线传 ×3.6（内核立规注记 规则 0b 远程优先方向的前置件）。装配序=GZip 在前
    # （Starlette 列表首项为最外层）：响应出站先经内层 CSP 附加头、再经
    # GZip 压缩体——CSP 头与 Content-Encoding 并存（test_w1e_ui_csp 头值
    # 断言不破）。minimum_size=1024 小响应不压；starlette 1.6 缺省
    # exclude_content_types 已含 text/event-stream（SSE 帧不被 gzip 缓冲）
    # 与 image/png 等已压格式，真机 SSE 冒烟同笔复核。
    # A8-D：ParamError → 400 error 信封（非法查询/请求参数的失败面补齐）
    # A4 P0-3 保险环：未来新增调用点若漏过 _json_body 守卫直接裸
    # request.json()，JSON 解码错误仍归一 400 信封（非 500 纯文本）。
    # D-04：CSP 头全响应附加（HTML 面为主；JSON/静态资源带同名头无害）
    # P9-14（aurora_g W1-S1）：同一中间件单点附加安全头批
    # （X-Content-Type-Options/Referrer-Policy，csp.py 单源）。
    # P9-1（aurora_g W1-S1）：Cache-Control 分域中间件挂最内层（响应出站
    # 先经本层加分域头，再经 CSP/安全头批、最后 GZip 压缩体）——SSE 路径
    # 在该层直通零缓存头，gzip 对 text/event-stream 的既有豁免不交互。
    # Bearer 鉴权（W6-S2）与 CacheControl 同层（最内）：401 拒绝响应出站
    # 仍经外层 CSP/安全头/GZip——响应面一致性不因拒绝路径豁免；env 未设
    # 时逐请求直通零开销。
    return Starlette(
        routes=routes,
        middleware=[
            Middleware(GZipMiddleware, minimum_size=1024),
            Middleware(csp_routes.ContentSecurityPolicyMiddleware),
            Middleware(CacheControlMiddleware),
            Middleware(BearerAuthMiddleware),
        ],
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
        # W6-S2（R2 审计 §面5.4）：非回环绑定提示写端点鉴权闸（env 未设=
        # 写端点无凭据可调——远程部署唯一缺层的启动期可见化）。
        if ui_auth_token() is None:
            print(
                "[rfauto ui] 提示：非回环绑定且 RFAUTO_UI_TOKEN 未设——写端点"
                "（POST/PUT/DELETE）无鉴权可调；设 env RFAUTO_UI_TOKEN=<令牌> "
                "启用 Bearer 写闸（读端点豁免，前端随页面自动接线）。",
                file=sys.stderr,
            )
    uvicorn.run(
        create_ui_app(include_runs_mount=include_runs_mount), host=host, port=port,
        log_level="warning",
    )
