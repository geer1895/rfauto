"""四域信道塑形策略表（描述性单源——aurora_p F3 席落表，F3L1 席清偿后同步）。

rfauto 有四条机器可辨的输出信道（域）：

- ``cli-human``：CLI rich 人读分支（红字/表格/建议提示；``--no-json``）；
- ``cli-json``：CLI JSON 机器读分支（信封契约三态；``--json``）；
- ``ui-sse``：UI 实时事件流（SSE 帧；统一事件总线）；
- ``mcp``：MCP 工具返回（stdio JSON-RPC 信封）。

本模块把"每个域的输出形态规则"收成**一张表**：成功形态/错误形态/失败
不变量/泄漏禁令。性质是**描述性单源**——现状即策略，表是对既有四条
发射面行为的单点描述，不引入任何新行为、不被任何发射面 import（零
行为变更的结构保证；后续席若把表接入发射面做运行时强制，须同笔更新
tests/unit/test_channel_policy.py 的结构钉）。

表里每条 ``failure_invariants`` 都能在真实发射面源码结构上逐条对上，
结构钉在 ``tests/unit/test_channel_policy.py``（AST/探针双路，钉描述
现状——现状若与表冲突则钉红如实暴露，不掩盖；F3 审计登记的四域相互
不一致（runs/aurora_p/f3/AUDIT.md §2 I-1/I-2、§3 I-3）已由 F3L1 席
2026-11-02 清偿，表与钉同笔更新为修后行为）。

与 Super-agent Channel 的对照（思想吸收声明，出处与许可核实见
runs/aurora_o/superagent_absorb/ABSORB.md）：Channel 的 allowed（出口
可用面声明）↔ 本表 ``surface`` 锚；send（往哪个信道发什么形态）↔
``success_shape``/``error_shape``；link（外部会话怎么接进来）↔ CLI 域
exit 码约定（调用方分支语义）/ui-sse 域 ``id`` 行 Last-Event-ID 续传锚/
mcp 域 stdio JSON-RPC 会话。

分层纪律：本模块**零 rfauto 内部 import**（纯 stdlib 描述表）——service
层不得反向 import cli/ui/mcp_tools（import-linter 契约），发射面只经
字符串锚引用。禁 ``__all__``：public_api 金快照零扰动
（ui/routes/event_bus.py 同款纪律，无 ``__all__`` 文件不入快照）。

引用符号（#222 家法，全部 grep/实测复核，复测时点 2026-11-02）：
- ``rfauto.cli.domains._core``::``_emit`` / ``_emit_usage_error`` /
  ``_attach_error_hints`` / ``_print_next_steps_stderr``
- ``rfauto.service.envelope``::``ok_envelope`` / ``error_envelope`` /
  ``skipped_envelope``
- ``rfauto.ui.routes.event_bus``::``sse_frame`` / ``control_frame`` /
  ``EVENT_ENVELOPE_KEYS``
- ``rfauto.ui.routes.events``::``_events_stream_response``（SSE 端点错误面）
- ``rfauto.ui.server``::``_param_error_handler``（ParamError→400 信封单源）
- ``rfauto.mcp_tools``（@mcp.tool 薄壳，全包零 raise）
- ``tests/unit/test_w2_c_json_coverage.py``（--json 棘轮）/
  ``tests/unit/test_mcp_tool_consistency.py``（MCP 逐工具双检）/
  ``tests/unit/test_mcp_server.py``（工具计数钉）/
  ``tests/unit/test_envelope_contract.py``（信封契约门）
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# ── 域清单 ────────────────────────────────────────────────────────────────

DOMAIN_CLI_HUMAN = "cli-human"
DOMAIN_CLI_JSON = "cli-json"
DOMAIN_UI_SSE = "ui-sse"
DOMAIN_MCP = "mcp"

#: 四域（策略表覆盖面；键集即覆盖面，缺域=漏钉）
DOMAINS: tuple[str, ...] = (
    DOMAIN_CLI_HUMAN,
    DOMAIN_CLI_JSON,
    DOMAIN_UI_SSE,
    DOMAIN_MCP,
)

#: 每域策略的顶层键集（ uniform 形状；accessor 与自检按此机械比较）
POLICY_FIELDS: tuple[str, ...] = (
    "surface",  # 发射面锚（file::symbol 元组；Channel allowed 对照）
    "success_shape",  # 成功形态描述（Channel send 对照）
    "error_shape",  # 错误形态描述
    "failure_invariants",  # 失败路径结构不变量（机器可查；钉面对照）
    "leak_bans",  # 泄漏禁令（该域禁止出现的输出形态）
    "notes",  # 描述性注记（含现状偏移登记指针）
)

# ── 逐域策略（描述现状；结构钉=tests/unit/test_channel_policy.py）─────────
#: 失败信封构造器三元组（cli-json / mcp 共用同一契约单源）
_ENVELOPE_CONSTRUCTORS = ("ok_envelope", "error_envelope", "skipped_envelope")

#: 事件信封键集（与 ui/routes/event_bus.py::EVENT_ENVELOPE_KEYS 逐字节同序）
_EVENT_ENVELOPE_KEYS = ("seq", "ts", "kind", "domain", "payload")

DOMAIN_POLICIES: dict[str, dict[str, Any]] = {
    DOMAIN_CLI_HUMAN: {
        "surface": (
            "rfauto.cli.domains._core::_emit(human 分支)",
            "rfauto.cli.domains._core::_emit_usage_error(human 分支)",
            "rfauto.cli.domains._core::_print_next_steps_stderr",
        ),
        "success_shape": "rich 渲染归各叶自定（表格/进度/摘要），_emit "
                         "human 成功分支零输出——不进契约（注意力只花在需要人的事）",
        "error_shape": "红字 ✗ fail_msg 一行 + 逐条 - err 红字 + 经 "
                       "_print_error_hints_text 附着 → 建议行（hits 未命中零输出）",
        "failure_invariants": {
            "exit_code_service_failure": 1,
            "exit_code_usage_error": 2,
            "error_output_channel": "red_text_stdout",
            "next_steps_channel": "stderr",
            "hints_rule_source": "rfauto.service.error_hints_service",
        },
        "leak_bans": (
            "下一步指针走 stderr——stdout 是人读主通道，补充指针不得挤占",
            "人读分支不输出 JSON 信封（分域不混原则的对偶面）",
        ),
        "notes": (
            "hints 与 --json 分支同一规则表（error_hints_service 单源），"
            "best-effort：hint 生成失败绝不遮蔽原错误（#105）",
            "usage 类错误与 service 失败 exit 码二分（2/1）沿 typer 惯例",
        ),
    },
    DOMAIN_CLI_JSON: {
        "surface": (
            "rfauto.cli.domains._core::_emit(--json 分支)",
            "rfauto.cli.domains._core::_emit_usage_error(--json 分支)",
            "rfauto.service.envelope::ok_envelope/error_envelope/skipped_envelope",
            "tests/unit/test_w2_c_json_coverage.py（--json 棘轮）",
        ),
        "success_shape": "服务返回信封原样 JSON 直出（console.print_json，"
                         "indent=2）；ok/skipped 两态均 ok=True",
        "error_shape": "失败信封（ok=False）：result 既有 errors/error 原样带上，"
                       "两者都缺时 fail_msg 兜底入 errors 一元列表；挂 hints 键后直出",
        "failure_invariants": {
            "exit_code_service_failure": 1,
            "exit_code_usage_error": 2,
            "error_output_channel": "envelope_json_stdout",
            "fail_msg_fallback_into_errors": True,
            "hints_key_attached_on_failure": True,
            "hints_best_effort": True,
            "usage_error_via_error_envelope": True,
            "payload_parse_errors_via_error_envelope": True,
            "watch_timeout_via_error_envelope": True,
            "envelope_constructors": _ENVELOPE_CONSTRUCTORS,
        },
        "leak_bans": (
            "--json 下 stdout 不得出现非 JSON（红字/表格/进度行）——VI-5 W6-B 家法",
            "失败路径不得裸文本（#ge1㉙ 契约：usage 错同受此约束）",
            "stderr 内容（日志/下一步指针）不参与解析——stdout 单信道契约",
        ),
        "notes": (
            "hints 键恒存在（未命中=空表如实回显，不编造提示）",
            "I-1/I-2 已清偿（aurora_p F3L1，2026-11-02）：_watch_poll 超时与 "
            "_load_json_file/_kv_floats 参数错在 --json 下走 error_envelope "
            "信封（audit 登记 runs/aurora_p/f3/AUDIT.md §2；修前/修后 "
            "bytecmp 对照在 runs/aurora_p/f3l1/）",
        ),
    },
    DOMAIN_UI_SSE: {
        "surface": (
            "rfauto.ui.routes.event_bus::sse_frame（业务帧单源）",
            "rfauto.ui.routes.event_bus::control_frame（控制帧单源）",
            "rfauto.ui.routes.events::make_stream_generator/_events_stream_response",
            "rfauto.ui.routes.runs::api_run_events_stream（既有 runs 桥）",
            "rfauto.ui.server::_param_error_handler（400 信封单源）",
        ),
        "success_shape": "业务帧 event=<kind> + id=<seq> + data=<统一事件信封 "
                         "JSON>（信封键 seq/ts/kind/domain/payload；id=续传锚）",
        "error_shape": "端点级错误走 HTTP JSONResponse + error_envelope 信封"
                       "（sse-starlette 缺装/订阅满员=503；ParamError=400）；"
                       "流内不设错误 kind（观测面 #105 降级为该轮无事件）",
        "failure_invariants": {
            "frame_keys": ("event", "id", "data"),
            "event_envelope_keys": _EVENT_ENVELOPE_KEYS,
            "control_frame_kinds": ("hello", "resync"),
            "control_frame_omits_id": True,
            "control_frame_domain": "system",
            "end_frame_shape": "raw_event_data_no_id",
            "bridge_error_frame_envelope": True,
            "endpoint_error_envelope": True,
            "endpoint_error_status_sse_capacity": 503,
            "endpoint_error_status_param": 400,
        },
        "leak_bans": (
            "控制帧（hello/resync）不得携带 id 行——EventSource 语义下不清"
            "客户端 Last-Event-ID 游标（UI-R9 P1-A）",
            "业务帧 data 必须是统一事件信封 JSON（runs 域旧字段在 payload "
            "里原样透传，一个不消失）",
            "读面故障降级为该轮无事件，不得炸流（#105：观测面不阻塞业务）",
        ),
        "notes": (
            "end 帧直出裸 dict（terminal/exists 顶层，无 id 行）——与既有"
            " runs 桥同语义的兼容锚，非 control_frame 统一信封",
            "I-3 已清偿（aurora_p F3L1，2026-11-02）：runs 桥流内 error 帧 "
            "data 走 error_envelope 信封（ok=False+errors list；前端 sse.js "
            "error 监听只判 data 是 string 不解析内容，消费零改动）",
            "Last-Event-ID 头续传=Channel link 对照锚（游标语义，环形窗口"
            "背压截断走 resync 控制帧）",
        ),
    },
    DOMAIN_MCP: {
        "surface": (
            "rfauto.mcp_tools._core::mcp（FastMCP 实例单源）",
            "rfauto.mcp_tools/*.py（@mcp.tool 薄壳，零逻辑转发 service）",
            "rfauto.service.envelope::ok_envelope/error_envelope/skipped_envelope",
            "tests/unit/test_mcp_tool_consistency.py（逐工具双检）",
            "tests/unit/test_mcp_server.py（工具计数钉）",
        ),
        "success_shape": "service 信封原样 dict 返回（ok/skipped 两态 ok=True），"
                         "FastMCP 序列化为 JSON-RPC 结果",
        "error_shape": "失败=返回 ok=False 信封（error_envelope 构造，errors "
                       "恒 list[str]）——不抛异常，错误不升协议层",
        "failure_invariants": {
            "tool_decorator": "@mcp.tool",
            "error_path": "return_envelope_no_raise",
            "raise_count": 0,
            "envelope_constructors": _ENVELOPE_CONSTRUCTORS,
            "consistency_guard": "tests/unit/test_mcp_tool_consistency.py",
            "count_guard": "tests/unit/test_mcp_server.py",
            "stdout_is_jsonrpc_channel": True,
        },
        "leak_bans": (
            "工具失败不得 raise——raise 会升为协议层错误而非信封（错误面"
            "绕过契约；零 raise 靠纪律维持，无结构强制，见 notes）",
            "stdout 是 JSON-RPC 信道，main() 禁止任何直印（#278：子进程级"
            "零 stdout 字节钉在 test_mcp_server）",
        ),
        "notes": (
            "工具计数（166，2026-11-01 实测）由 test_mcp_server 权威钉住，"
            "本表不复制易变数字（在飞席位加工具时只动权威钉）",
            "缺口登记：无全局异常 handler/统一包装器——零 raise 是约定非结构"
            "强制，硬化方案见 runs/aurora_p/f3/AUDIT.md §4（移交裁量）",
        ),
    },
}


class PolicyMismatch(Exception):
    """策略表与观察面不一致（自检失败；attributes 见构造）。"""

    def __init__(self, domain: str, mismatches: list[tuple[str, Any, Any]]) -> None:
        self.domain = domain
        self.mismatches = list(mismatches)
        lines = "\n".join(
            f"  {key}: 表={expected!r} 观察={actual!r}"
            for key, expected, actual in mismatches
        )
        super().__init__(f"domain={domain!r} 与策略表不一致（{len(mismatches)} 条）:\n{lines}")


def list_domains() -> tuple[str, ...]:
    """返回策略表覆盖的全部域（与 DOMAINS 同序）。"""
    return DOMAINS


def get_policy(domain: str) -> dict[str, Any]:
    """取域策略（表项本体，约定只读）；未知域抛 PolicyMismatch。

    键集恒为 POLICY_FIELDS（覆盖面自检：表缺域/域缺键都视为表自身损坏）。
    """
    try:
        policy = DOMAIN_POLICIES[domain]
    except KeyError:
        raise PolicyMismatch(
            domain,
            [("domain", tuple(DOMAINS), domain)],
        ) from None
    missing = [f for f in POLICY_FIELDS if f not in policy]
    if missing:
        raise PolicyMismatch(domain, [(f, "存在", "缺失") for f in missing])
    return policy


def _norm(value: Any) -> Any:
    """tuple/list 归一为 tuple（观察面采集形态与表形态解耦）。"""
    if isinstance(value, (list, tuple)):
        return tuple(_norm(v) for v in value)
    return value


def collect_surface_mismatches(
    domain: str, observed: Mapping[str, Any]
) -> list[tuple[str, Any, Any]]:
    """观察面 vs 策略表逐条比对（不抛异常版；返回 (键, 表值, 观察值) 列表）。

    只比对表内 ``failure_invariants`` 的键（观察面多余键忽略——采集面可以
    超集）；比对前 tuple/list 双侧归一，值语义为全等。
    """
    invariants = get_policy(domain)["failure_invariants"]
    mismatches: list[tuple[str, Any, Any]] = []
    for key, expected in invariants.items():
        if key not in observed:
            mismatches.append((key, expected, "观察面缺键"))
            continue
        actual = observed[key]
        if _norm(expected) != _norm(actual):
            mismatches.append((key, expected, actual))
    return mismatches


def assert_surface_matches(domain: str, observed: Mapping[str, Any]) -> None:
    """自检：观察面必须与策略表逐条一致，否则抛 PolicyMismatch（钉红）。

    ``observed`` 是对真实发射面**当前行为**的结构化采集（源码结构/探针
    实测，采集姿势见 tests/unit/test_channel_policy.py）——现状与表冲突
    即红（诚实性：钉描述现状，不掩盖）。
    """
    mismatches = collect_surface_mismatches(domain, observed)
    if mismatches:
        raise PolicyMismatch(domain, mismatches)
