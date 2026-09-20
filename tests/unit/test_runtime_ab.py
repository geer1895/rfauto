"""Runtime A/B token 效率仪表单测（WP3.1，离线确定性，无网络无真模型）。

钉死三件事：① 同一脚本轨迹两轨公平（工具序列/token 同源）；② 结构差恰为
builtin 的催办注入（pydantic_ai 适配器侧 0 注入）——仪表诚实性；③ 默认
裁决在离线+库未装时维持 builtin，切默认门槛三条件缺一不可。
"""

from __future__ import annotations

import pytest

from rfauto.service.pydantic_ai_runtime import RuntimeBudgetExceeded
from rfauto.service.runtime_ab import (
    BuiltinScriptedTransport,
    ScriptedTurn,
    compare_runtime_token_efficiency,
    estimate_tokens,
    lib_available,
    lib_version,
    recommend_default,
)


class TestEstimateTokens:
    def test_heuristic(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("abcd") == 1  # 4 ASCII 字符 ≈ 1 token
        assert estimate_tokens("中文字") == 3  # CJK 记 1 token/字
        assert estimate_tokens("结论：正常。ok") == 6  # 5 CJK + 2 ASCII → 5+1


class TestCompareAB:
    def test_default_scenario_fair_and_nudge_delta(self):
        report = compare_runtime_token_efficiency()
        b = report["runtimes"]["builtin"]
        p = report["runtimes"]["pydantic_ai"]
        # 公平性：同一轨迹，工具序列与脚本 token 完全同源
        assert report["fair"] is True
        assert b["tool_calls"] == p["tool_calls"] == 2
        assert b["prompt_tokens"] == p["prompt_tokens"] == 300
        assert b["completion_tokens"] == p["completion_tokens"] == 60
        # 结构差恰为 builtin 催办注入（max_rounds=4、3 轮：第 3 次调用注入 1 次；
        # JSON 列表插入的 ", " 分隔符 +2 字符/处，仪表已折算进 overhead 字段）
        assert b["nudge_hits"] == 1
        assert b["nudge_chars_total"] > 0
        assert report["structural_delta_chars"] == report["nudge_injection_overhead_chars"]
        assert (report["structural_delta_chars"]
                == b["nudge_chars_total"] + 2 * b["nudge_hits"])
        assert p["runtime_injected_chars"] == 0
        assert b["est_tokens_runtime_added_total"] > 0
        # 两轨收尾一致
        assert b["finish_reason"] == p["finish_reason"] == "stop"
        # 库内序列化差异如实标 unmeasured（不假装测过；装了库也只是换措辞）
        assert report["lib_overhead"] in ("unmeasured_offline", "not_measured_in_offline_mode")

    def test_no_nudge_before_threshold(self):
        # 催办在 round_no == max_rounds-2 注入：2 轮轨迹配 4 轮预算 → 全程在第
        # 3 轮之前完成，催办永不注入，两轨总线逐字符一致
        turns = [ScriptedTurn(tool_calls=[("list_runs", {})]),
                 ScriptedTurn(text="好了")]
        report = compare_runtime_token_efficiency(turns, max_rounds=4)
        assert report["structural_delta_chars"] == 0
        assert report["runtimes"]["builtin"]["nudge_hits"] == 0
        b = report["runtimes"]["builtin"]["wire_chars_per_call"]
        p = report["runtimes"]["pydantic_ai"]["wire_chars_per_call"]
        assert b == p

    def test_budget_scenario_both_exhausted(self):
        turns = [ScriptedTurn(tool_calls=[("list_runs", {})]),
                 ScriptedTurn(tool_calls=[("list_runs", {})])]
        report = compare_runtime_token_efficiency(turns, max_rounds=2)
        b = report["runtimes"]["builtin"]
        p = report["runtimes"]["pydantic_ai"]
        assert b["finish_reason"] == p["finish_reason"] == "budget_exhausted"
        assert report["fair"] is True
        # max_rounds=2：round0 即注入，两次调用载荷都带着催办
        assert b["nudge_hits"] == 2
        assert report["structural_delta_chars"] == report["nudge_injection_overhead_chars"]
        # 真实遥测不对称如实入报告：预算路径 pydantic-ai run_sync 丢 usage
        assert b["prompt_tokens"] == 200 and p["prompt_tokens"] == 0
        assert report["fairness"]["tokens_comparable"] is False
        assert "run_sync" in report["fairness"]["note"]

    def test_deterministic(self):
        r1 = compare_runtime_token_efficiency()
        r2 = compare_runtime_token_efficiency()
        assert r1["runtimes"] == r2["runtimes"]
        assert r1["structural_delta_chars"] == r2["structural_delta_chars"]

    def test_executor_exception_mirror(self):
        # 工具异常在两轨都由 runtime 兜底回传（error 字典），不影响公平性
        def boom(name, args):
            raise ValueError("炸了")

        report = compare_runtime_token_efficiency(
            turns=[ScriptedTurn(tool_calls=[("run_detail", {"run_id": "x"})]),
                   ScriptedTurn(text="收到错误")],
            executor=boom)
        assert report["fair"] is True
        assert report["runtimes"]["builtin"]["tool_calls"] == 1
        assert report["runtimes"]["pydantic_ai"]["tool_calls"] == 1


class TestRecommendDefault:
    def test_offline_keeps_builtin(self):
        report = compare_runtime_token_efficiency()
        decision = report["decision"]
        assert decision["default"] == "builtin"
        assert decision["switch"] is False
        assert decision["metric"] == "wire_chars"  # 离线：按总线字符
        if not lib_available():  # 库装没装取决于环境（可选组 pai），理由行随之
            assert any("未安装" in r for r in decision["reasons"])
        assert any("真机" in r or "真模型" in r for r in decision["reasons"])

    def test_switch_requires_all_three_conditions(self):
        base = compare_runtime_token_efficiency()
        # ① 离线 + 库可用：不切（缺真机 A/B 证据）
        fake_live = dict(base, mode="live", fair=True)
        assert recommend_default(fake_live)["switch"] is False
        # ② 真机 + 库可用 + 节省不足 5%：不切
        small = dict(base, mode="live", fair=True)
        small["runtimes"] = {"builtin": {"wire_chars_total": 100},
                             "pydantic_ai": {"wire_chars_total": 99}}
        assert recommend_default(small)["switch"] is False
        # ③ 三条件齐备：切
        big = dict(base, mode="live", fair=True)
        big["runtimes"] = {"builtin": {"wire_chars_total": 100},
                           "pydantic_ai": {"wire_chars_total": 50}}
        if lib_available():
            assert recommend_default(big)["switch"] is True
        else:
            assert recommend_default(big)["switch"] is False  # 库未装时永不切

    def test_live_metric_prefers_model_reported_tokens(self):
        # live 且两轨都有模型上报 token → 按总 token 计节省（字节序列化器不同只作参考）
        live = {"mode": "live", "fair": True,
                "runtimes": {"builtin": {"wire_chars_total": 100, "prompt_tokens": 900,
                                         "completion_tokens": 100},
                             "pydantic_ai": {"wire_chars_total": 50, "prompt_tokens": 980,
                                             "completion_tokens": 100}}}
        d = recommend_default(live)
        assert d["metric"] == "total_tokens"
        assert d["saving"] == pytest.approx(-0.08)  # pydantic_ai 多用 8% → 永不切
        assert d["switch"] is False
        assert any("真机 token" in r for r in d["reasons"])
        # 缺 token（旧档/离线）→ 回退总线字符
        wire_only = dict(live, runtimes={"builtin": {"wire_chars_total": 100},
                                         "pydantic_ai": {"wire_chars_total": 50}})
        assert recommend_default(wire_only)["metric"] == "wire_chars"

    def test_live_unfair_never_switches(self):
        live = {"mode": "live", "fair": False,
                "runtimes": {"builtin": {"wire_chars_total": 100, "prompt_tokens": 1000,
                                         "completion_tokens": 100},
                             "pydantic_ai": {"wire_chars_total": 50, "prompt_tokens": 500,
                                             "completion_tokens": 50}}}
        d = recommend_default(live)
        assert d["switch"] is False and d["saving"] == 0.5
        assert any("公平性" in r for r in d["reasons"])

    def test_lib_version_shape(self):
        v = lib_version()
        assert v is None or (isinstance(v, str) and v[0].isdigit())
        assert (v is not None) == lib_available()


class TestScriptedTransport:
    def test_transport_records_wire_and_nudge(self):
        tr = BuiltinScriptedTransport([ScriptedTurn(text="done")])
        msgs = [{"role": "system", "content": "工具预算只剩 2 次。请立即完成任务"}]
        tr(msgs, [{"type": "function"}])
        assert tr.nudge_hits == 1 and tr.nudge_chars > 0
        assert len(tr.wire_chars) == 1

    def test_budget_exception_type_importable(self):
        # pai 注入缝的预算哨兵可从 runtime_ab 复用（同源异常契约）
        assert issubclass(RuntimeBudgetExceeded, RuntimeError)
