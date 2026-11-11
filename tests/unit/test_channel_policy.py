"""四域信道塑形策略表结构钉（aurora_p F3 席）。

钉的口径：``src/rfauto/service/channel_policy.py`` 的 DOMAIN_POLICIES 是
**现状的描述性单源**——本文件把表里每条 ``failure_invariants`` 与四条
真实发射面的**当前源码结构/探针实测**逐条对上：

- cli-human / cli-json：``rfauto.cli.domains._core`` 的 ``_emit`` /
  ``_emit_usage_error`` AST 结构（exit 码、双分支、hints 挂载、信封兜底）；
  F3L1 增钉：``_load_json_file``/``_kv_floats``/``_watch_poll`` 错误分支
  收编信封单源（I-1/I-2 清偿后的结构面）；
- ui-sse：``rfauto.ui.routes.event_bus`` 探针实测（帧形态/control 帧）+
  routes/events.py、runs.py 的 yield 帧字面量 AST + 端点错误面文本；
  F3L1 增钉：runs 桥流内 error 帧 data 走 error_envelope（I-3 清偿后）；
- mcp：``rfauto.mcp_tools`` 全包 AST raise 计数（=0）+ 守卫文件存在性。

诚实性：钉**描述现状**——现状若与表冲突则钉红如实暴露（不掩盖）；
F3 审计登记的四域不一致（runs/aurora_p/f3/AUDIT.md §2/§3）已由 F3L1 席
2026-11-02 清偿，表与钉同笔更新为修后行为（原"零改行为"口径随之退役）。
发射面零策略表引用纪律不变（下方结构钉）。

变异探针：≥2 条"改假面字段→钉红"用例钉住自检函数自身有效（探针红=
自检能抓不一致；探针全绿=自检失明）。
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path
from typing import Any

import pytest

from rfauto.cli.domains import _core as cli_core
from rfauto.service import channel_policy as cp
from rfauto.service.channel_policy import (
    DOMAIN_CLI_HUMAN,
    DOMAIN_CLI_JSON,
    DOMAIN_MCP,
    DOMAIN_UI_SSE,
    DOMAINS,
    POLICY_FIELDS,
    PolicyMismatch,
    assert_surface_matches,
    collect_surface_mismatches,
    get_policy,
)
from rfauto.service.envelope import (
    error_envelope,
    ok_envelope,
    skipped_envelope,
)
from rfauto.ui.routes import event_bus as eb

_REPO = Path(__file__).resolve().parents[2]
_MCP_TOOLS_DIR = _REPO / "src" / "rfauto" / "mcp_tools"
_UI_ROUTES_DIR = _REPO / "src" / "rfauto" / "ui" / "routes"
_UI_SERVER_PY = _REPO / "src" / "rfauto" / "ui" / "server.py"


# ── AST helpers（源码结构采集面）─────────────────────────────────────────

def _func_node(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"源码中找不到函数 {name}")


def _exit_codes(fn_node: ast.AST) -> list[int]:
    """收集函数体内 typer.Exit(code=N) 调用的 code 值列表。"""
    codes: list[int] = []
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "Exit":
            for kw in node.keywords:
                if kw.arg == "code" and isinstance(kw.value, ast.Constant):
                    codes.append(int(kw.value.value))
    return codes


def _yield_dict_literals(path: Path) -> list[tuple[str, ...]]:
    """收集模块内所有 ``yield {字面 dict}`` 的字符串键集（SSE 帧形态面）。"""
    out: list[tuple[str, ...]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Yield) or not isinstance(node.value, ast.Dict):
            continue
        keys = node.value.keys
        if all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in keys):
            out.append(tuple(str(k.value) for k in keys))  # type: ignore[union-attr]
    return out


# 守卫/装配面豁免（aurora_r M-7 合流笔 2026-11-10 精化）：资源面
# （skill://，_resources.py）读取失败的 raise 是 MCP 协议资源错误的合法
# 传播形态（fastmcp 包成 is_error 响应）；_annotations.py 的 RuntimeError
# 是 import 期防漂移自证（非工具执行期）。不变量本义=**工具函数体**零
# raise——机械全目录计数对首个带守卫的 mcp 模块（R-13/R-10）误报。
_RAISE_EXEMPT_FILES = {"_annotations.py", "_resources.py"}


def _raise_count_dir(directory: Path) -> int:
    """目录下全部 .py 的 ast.Raise 节点总数（MCP 域零 raise 结构面；守卫/
    装配面豁免见 _RAISE_EXEMPT_FILES）。"""
    total = 0
    for py in sorted(directory.glob("*.py")):
        if py.name in _RAISE_EXEMPT_FILES:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        total += sum(isinstance(n, ast.Raise) for n in ast.walk(tree))
    return total


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── 1. 表自身形状（覆盖面自检）───────────────────────────────────────────

class TestTableShape:
    def test_domains_covered_exactly(self):
        assert set(cp.DOMAIN_POLICIES) == set(DOMAINS)
        assert len(cp.DOMAIN_POLICIES) == 4
        assert cp.list_domains() == DOMAINS

    def test_uniform_policy_fields(self):
        for domain in DOMAINS:
            policy = cp.DOMAIN_POLICIES[domain]
            assert set(policy) == set(POLICY_FIELDS), domain
            invariants = policy["failure_invariants"]
            assert isinstance(invariants, dict) and invariants, domain
            assert policy["surface"] and policy["leak_bans"], domain

    def test_get_policy_returns_entry_and_rejects_unknown(self):
        for domain in DOMAINS:
            assert get_policy(domain) is cp.DOMAIN_POLICIES[domain]
        with pytest.raises(PolicyMismatch, match=r"不一致"):
            get_policy("no-such-domain")

    def test_get_policy_deterministic(self):
        # 确定性：同一域两次取表逐键相等（描述表无常量漂移）
        for domain in DOMAINS:
            assert get_policy(domain) == get_policy(domain)

    def test_shared_constants_match_authoritative_sources(self):
        # 表内共享常量与权威单源一致（信封构造器名/事件信封键集）——
        # 经 get_policy 公开面比对，不触模块私有名
        for domain in (DOMAIN_CLI_JSON, DOMAIN_MCP):
            assert get_policy(domain)["failure_invariants"][
                "envelope_constructors"] == (
                "ok_envelope", "error_envelope", "skipped_envelope")
        assert get_policy(DOMAIN_UI_SSE)["failure_invariants"][
            "event_envelope_keys"] == tuple(eb.EVENT_ENVELOPE_KEYS)


# ── 2. CLI 双域钉（cli-human / cli-json：_emit/_emit_usage_error AST）────

class TestCliDomainPins:
    def _cli_observed(self) -> dict[str, dict[str, Any]]:
        emit_src = inspect.getsource(cli_core._emit)
        usage_src = inspect.getsource(cli_core._emit_usage_error)
        emit_node = _func_node(emit_src, "_emit")
        usage_node = _func_node(usage_src, "_emit_usage_error")
        service_codes = _exit_codes(emit_node)
        usage_codes = _exit_codes(usage_node)
        assert service_codes == [1], \
            f"_emit 应恰一次 Exit(code=1)，实测 {service_codes}"
        assert usage_codes == [2], "_emit_usage_error 应恰一次 Exit(code=2)"
        # 成功人读分支零输出：顶层第二个 if json_output 无 else，体内仅 print_json
        top_ifs = [n for n in emit_node.body if isinstance(n, ast.If)]
        assert len(top_ifs) == 2, "_emit 顶层应为失败 if + 成功 json 分支两个 if"
        success_branch = top_ifs[1]
        assert success_branch.orelse == [], "成功路径不得有 human 公共渲染（归各叶）"
        attach_idx = emit_src.index("_attach_error_hints(envelope)")
        print_idx = emit_src.index("print_json")
        return {
            DOMAIN_CLI_JSON: {
                "exit_code_service_failure": service_codes[0],
                "exit_code_usage_error": usage_codes[0],
                "error_output_channel": (
                    "envelope_json_stdout"
                    if (attach_idx < print_idx and "error_envelope(" in usage_src
                        and "print_json" in usage_src)
                    else "other"
                ),
                "fail_msg_fallback_into_errors": 'envelope["errors"] = [fail_msg]' in emit_src,
                "hints_key_attached_on_failure": "_attach_error_hints(envelope)" in emit_src,
                "hints_best_effort": (
                    "except Exception" in inspect.getsource(cli_core._attach_error_hints)
                    and "setdefault" in inspect.getsource(cli_core._attach_error_hints)
                ),
                "usage_error_via_error_envelope": "error_envelope(" in usage_src,
                "payload_parse_errors_via_error_envelope": (
                    "_emit_usage_error(" in inspect.getsource(cli_core._load_json_file)
                    and "_emit_usage_error(" in inspect.getsource(cli_core._kv_floats)
                    and "json_output" in inspect.getsource(cli_core._load_json_file)
                    and "json_output" in inspect.getsource(cli_core._kv_floats)
                ),
                "watch_timeout_via_error_envelope": (
                    "error_envelope(" in inspect.getsource(cli_core._watch_poll)
                ),
                "envelope_constructors": (
                    "ok_envelope", "error_envelope", "skipped_envelope"),
            },
            DOMAIN_CLI_HUMAN: {
                "exit_code_service_failure": service_codes[0],
                "exit_code_usage_error": usage_codes[0],
                "error_output_channel": (
                    "red_text_stdout" if "[red]✗ {fail_msg}" in emit_src else "other"),
                "next_steps_channel": (
                    "stderr" if "file=sys.stderr"
                    in inspect.getsource(cli_core._print_next_steps_stderr)
                    else "other"),
                "hints_rule_source": (
                    "rfauto.service.error_hints_service"
                    if "error_hints_service"
                    in inspect.getsource(cli_core._print_next_steps_stderr)
                    else "other"),
            },
        }

    def test_cli_json_surface_matches_policy(self):
        observed = self._cli_observed()[DOMAIN_CLI_JSON]
        assert_surface_matches(DOMAIN_CLI_JSON, observed)

    def test_cli_human_surface_matches_policy(self):
        observed = self._cli_observed()[DOMAIN_CLI_HUMAN]
        assert_surface_matches(DOMAIN_CLI_HUMAN, observed)

    def test_envelope_constructors_are_the_contract_single_source(self):
        # 表引用的信封构造器三元组=契约单源（构造行为与
        # test_envelope_contract 交叉印证；此处只钉"表所指即实物"）
        assert ok_envelope(x=1) == {"ok": True, "x": 1}
        assert next(iter(ok_envelope())) == "ok"  # ok 恒首键
        assert error_envelope("boom") == {"ok": False, "errors": ["boom"]}
        assert skipped_envelope("r")["reason"] == "r"

    def test_usage_error_branch_is_json_envelope(self):
        # #ge1㉙：usage 错在 --json 下必须 error_envelope 信封（非红字裸文本）
        usage_src = inspect.getsource(cli_core._emit_usage_error)
        json_branch = usage_src.split("if json_output:")[1].split("else:")[0]
        assert "error_envelope(" in json_branch
        assert "print_json" in json_branch


# ── 3. UI SSE 域钉（event_bus 探针 + yield 帧字面量 + 端点错误面）─────────

class TestUiSsePins:
    def _sse_observed(self) -> dict[str, Any]:
        events_src = _read(_UI_ROUTES_DIR / "events.py")
        runs_src = _read(_UI_ROUTES_DIR / "runs.py")
        server_src = _read(_UI_SERVER_PY)
        frame = eb.sse_frame({"seq": 3, "ts": 0.0, "kind": "progress",
                              "domain": "runs", "payload": {"k": 1}})
        control = eb.control_frame("hello", {"cursor": 0})
        control_data = json.loads(control["data"])
        # end 帧=裸 dict 直出（event/data 两键、无 id、event 值=="end"）
        yield_literals = _yield_dict_literals(_UI_ROUTES_DIR / "events.py") + \
            _yield_dict_literals(_UI_ROUTES_DIR / "runs.py")
        end_literal = any(
            keys == ("event", "data") and len(keys) == 2 for keys in yield_literals)
        end_event_value = any(
            '"event": "end"' in src for src in (events_src, runs_src))
        # ParamError handler 切片：server.py 中 _param_error_handler 函数体
        handler_match = re.search(
            r"def _param_error_handler\(.*?(?=\n(?:async )?def |\nclass )",
            server_src, re.DOTALL)
        handler_src = handler_match.group(0) if handler_match else ""
        return {
            "frame_keys": tuple(frame),  # 线序（sse_frame 字面量键序）
            "event_envelope_keys": tuple(eb.EVENT_ENVELOPE_KEYS),
            "control_frame_kinds": (
                "hello", "resync") if (
                'control_frame("hello"' in events_src
                and 'control_frame("resync"' in events_src) else (),
            "control_frame_omits_id": "id" not in control,
            "control_frame_domain": control_data.get("domain"),
            "end_frame_shape": (
                "raw_event_data_no_id" if end_literal and end_event_value else "other"),
            "bridge_error_frame_envelope": "error_envelope(snap.get(" in runs_src,
            "endpoint_error_envelope": events_src.count("error_envelope(") >= 2
                and "error_envelope(" in handler_src,
            "endpoint_error_status_sse_capacity": (
                503 if events_src.count("status_code=503") == 2 else -1),
            "endpoint_error_status_param": 400 if "400" in handler_src else -1,
        }

    def test_sse_surface_matches_policy(self):
        assert_surface_matches(DOMAIN_UI_SSE, self._sse_observed())

    def test_business_frame_wire_shape(self):
        # 业务帧：event=<kind> + id=<seq> + data=<统一信封 JSON>（id=续传锚）
        frame = eb.sse_frame({"seq": 7, "ts": 1.0, "kind": "trial_new",
                              "domain": "tune", "payload": {}})
        assert frame["event"] == "trial_new"
        assert frame["id"] == "7"
        assert json.loads(frame["data"])["payload"] == {}

    def test_control_frames_omit_id_and_use_system_domain(self):
        # UI-R9 P1-A：控制帧省略 id 行（不清 Last-Event-ID 游标）
        for kind in ("hello", "resync"):
            frame = eb.control_frame(kind, {"cursor": 5})
            assert "id" not in frame, kind
            data = json.loads(frame["data"])
            assert data["domain"] == "system"
            assert data["seq"] == 0  # seq=0 仅表"非业务帧"
            assert data["kind"] == kind

    def test_every_yield_frame_literal_is_sse_shape(self):
        # 两条流（统一流+runs 桥）所有 yield 字面 dict 都是 SSE 帧形态：
        # 必含 event+data，至多 event/id/data（无第四键泄漏）
        for name in ("events.py", "runs.py"):
            for keys in _yield_dict_literals(_UI_ROUTES_DIR / name):
                assert {"event", "data"} <= set(keys), (name, keys)
                assert set(keys) <= {"event", "id", "data"}, (name, keys)


# ── 4. MCP 域钉（全包零 raise + 守卫文件存在性）───────────────────────────

class TestMcpPins:
    def _mcp_observed(self) -> dict[str, Any]:
        tool_files = sorted(_MCP_TOOLS_DIR.glob("*.py"))
        decorator_hits = sum(
            len(re.findall(r"^@mcp\.tool\b", _read(p), re.MULTILINE))
            for p in tool_files)
        consistency_guard = _REPO / "tests" / "unit" / "test_mcp_tool_consistency.py"
        count_guard = _REPO / "tests" / "unit" / "test_mcp_server.py"
        raises = _raise_count_dir(_MCP_TOOLS_DIR)
        return {
            "tool_decorator": "@mcp.tool" if decorator_hits >= 1 else "",
            "error_path": (
                "return_envelope_no_raise" if raises == 0 and decorator_hits >= 1
                else "other"),
            "raise_count": raises,
            "envelope_constructors": (
                "ok_envelope", "error_envelope", "skipped_envelope")
                if any("error_envelope" in _read(p) for p in tool_files) else (),
            "consistency_guard": (
                "tests/unit/test_mcp_tool_consistency.py"
                if consistency_guard.exists() else "missing"),
            "count_guard": (
                "tests/unit/test_mcp_server.py" if count_guard.exists() else "missing"),
            "stdout_is_jsonrpc_channel": (
                "JSON-RPC" in _read(count_guard) and "stdout" in _read(count_guard)),
        }

    def test_mcp_surface_matches_policy(self):
        assert_surface_matches(DOMAIN_MCP, self._mcp_observed())

    def test_raise_exempt_files_have_no_tools(self):
        # 豁免面收紧钉：豁免文件必须零真工具装饰（行首 @mcp.tool；docstring
        # 提及合法——否则豁免通道可被滥用藏工具 raise）
        import re as _re

        for name in _RAISE_EXEMPT_FILES:
            src = _read(_MCP_TOOLS_DIR / name)
            hit = _re.findall(r"^@mcp\.tool", src, flags=_re.M)
            assert not hit, f"{name} 持豁免却含工具装饰器（{len(hit)} 处）"

    def test_mcp_tools_never_raise(self):
        # 错误路径结构面：工具失败=返回信封，全包零 raise（docstring 提及
        # "raise" 不算——AST 口径）
        assert _raise_count_dir(_MCP_TOOLS_DIR) == 0

    def test_mcp_tools_are_thin_shells_forwarding_to_service(self):
        # 薄壳纪律面：工具组经 _core 单点取 FastMCP 实例 + 转发 service.api
        tool_sources = [_read(p) for p in sorted(_MCP_TOOLS_DIR.glob("*.py"))]
        assert any("from rfauto.mcp_tools._core import mcp" in s for s in tool_sources)
        assert any("from rfauto.service.api import" in s for s in tool_sources)


# ── 5. 变异探针（自检函数自身有效性：改假面字段→钉红）─────────────────────

class TestMutationProbes:
    """探针红=自检能抓不一致（≥2 条家法）；探针若全绿=自检失明必修。"""

    def _real_observed(self, domain: str) -> dict[str, Any]:
        real: dict[str, dict[str, Any]] = {
            DOMAIN_CLI_JSON: TestCliDomainPins()._cli_observed()[DOMAIN_CLI_JSON],
            DOMAIN_UI_SSE: TestUiSsePins()._sse_observed(),
            DOMAIN_MCP: TestMcpPins()._mcp_observed(),
        }
        return dict(real[domain])

    def test_probe_cli_json_exit_code_mutation_cought(self):
        observed = self._real_observed(DOMAIN_CLI_JSON)
        observed["exit_code_service_failure"] = 0  # 变异：exit 码被改
        mismatches = collect_surface_mismatches(DOMAIN_CLI_JSON, observed)
        assert [m[0] for m in mismatches] == ["exit_code_service_failure"]
        with pytest.raises(PolicyMismatch, match="exit_code_service_failure"):
            assert_surface_matches(DOMAIN_CLI_JSON, observed)

    def test_probe_ui_sse_envelope_keys_mutation_cought(self):
        observed = self._real_observed(DOMAIN_UI_SSE)
        observed["event_envelope_keys"] = ("seq", "ts", "kind", "domain")  # 丢 payload
        mismatches = collect_surface_mismatches(DOMAIN_UI_SSE, observed)
        assert [m[0] for m in mismatches] == ["event_envelope_keys"]
        with pytest.raises(PolicyMismatch, match="event_envelope_keys"):
            assert_surface_matches(DOMAIN_UI_SSE, observed)

    def test_probe_mcp_raise_mutation_cought(self):
        observed = self._real_observed(DOMAIN_MCP)
        observed["raise_count"] = 1  # 变异：工具开始抛异常
        mismatches = collect_surface_mismatches(DOMAIN_MCP, observed)
        assert [m[0] for m in mismatches] == ["raise_count"]
        with pytest.raises(PolicyMismatch, match="raise_count"):
            assert_surface_matches(DOMAIN_MCP, observed)


# ── 6. 零行为变更结构钉（本席交付时点口径）────────────────────────────────

class TestZeroBehaviorChange:
    def test_policy_module_has_zero_rfauto_imports(self):
        # 描述表零内部 import——结构上不可能改变任何发射路径（分层+零耦合）
        src = _read(_REPO / "src" / "rfauto" / "service" / "channel_policy.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith("rfauto") for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("rfauto")

    def test_no_emission_surface_imports_the_policy_table(self):
        # 本席交付时点发射面零引用（表=纯描述）；后续席把表接入发射面做
        # 运行时强制时须同笔更新本钉与策略表（棘轮纪律：显式评审动作）
        guarded = [
            _REPO / "src" / "rfauto" / "cli",
            _REPO / "src" / "rfauto" / "ui",
            _REPO / "src" / "rfauto" / "mcp_tools",
            _REPO / "src" / "rfauto" / "mcp_server.py",
        ]
        hits = []
        for base in guarded:
            files = base.rglob("*.py") if base.is_dir() else [base]
            for py in files:
                if "channel_policy" in py.read_text(encoding="utf-8"):
                    hits.append(str(py))
        assert hits == [], f"发射面出现了策略表引用（须同笔更新钉）: {hits}"
