"""自愈编排测试（计划内缺口 4）—— R5 掉线重连 + R1 几何失败重建。

此前 reconnect_with_backoff（hfss_session）已实现但零调用方；
本文件验证编排层 solve_with_self_heal / build_with_self_heal 及其接线。
"""

from __future__ import annotations

import pytest

from rfauto.core.interfaces import SolveReport
from rfauto.pipeline.self_heal import build_with_self_heal, solve_with_self_heal


class FlakyAdapter:
    """可控故障适配器：前 N 次 solve/health_check 失败，之后恢复。"""

    def __init__(self, solve_failures: int = 0, unhealthy_checks: int = 0):
        self.solve_failures = solve_failures
        self.unhealthy_checks = unhealthy_checks
        self.solve_calls = 0
        self.reconnect_calls = 0
        self.health_calls = 0

    def health_check(self) -> bool:
        self.health_calls += 1
        if self.unhealthy_checks > 0:
            self.unhealthy_checks -= 1
            return False
        return True

    def ensure_connected(self) -> None:
        self.reconnect_calls += 1

    def solve(self, setup_name: str, timeout_s: int = 3600) -> SolveReport:
        self.solve_calls += 1
        if self.solve_failures > 0:
            self.solve_failures -= 1
            raise RuntimeError("gRPC connection dropped")
        return SolveReport(success=True, passes=1, delta_s_final=0.001, message="ok")


class TestSolveWithSelfHeal:
    def test_healthy_path_no_reconnect(self):
        ad = FlakyAdapter()
        report = solve_with_self_heal(ad, "main_setup")
        assert report.success
        assert ad.solve_calls == 1
        assert ad.reconnect_calls == 0

    def test_transient_solve_failure_heals(self):
        """solve 抛异常 → ensure_connected → 重试成功。"""
        ad = FlakyAdapter(solve_failures=1)
        report = solve_with_self_heal(ad, "main_setup")
        assert report.success
        assert ad.solve_calls == 2
        assert ad.reconnect_calls == 1

    def test_unhealthy_check_triggers_reconnect(self):
        """健康检查失败 → 先重连再求解。"""
        ad = FlakyAdapter(unhealthy_checks=1)
        report = solve_with_self_heal(ad, "main_setup")
        assert report.success
        assert ad.reconnect_calls == 1
        assert ad.solve_calls == 1

    def test_exhausted_retries_raises(self):
        ad = FlakyAdapter(solve_failures=99)
        with pytest.raises(RuntimeError, match="gRPC"):
            solve_with_self_heal(ad, "main_setup", retries=1)
        assert ad.solve_calls == 2  # 首次 + 1 次重试
        assert ad.reconnect_calls == 1


class TestBuildWithSelfHeal:
    def test_first_try_success(self):
        calls: list[int] = []
        build_with_self_heal(lambda: calls.append(1))
        assert calls == [1]

    def test_transient_build_failure_retried(self):
        """R1：几何构建首次失败（瞬态）→ 重建重试成功。"""
        attempts: list[int] = []

        def flaky_build():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("对象名冲突/上次会话残留")
            return None

        build_with_self_heal(flaky_build)
        assert len(attempts) == 2

    def test_persistent_build_failure_raises(self):
        def always_fail():
            raise ValueError("真实几何错误")

        with pytest.raises(ValueError, match="真实几何错误"):
            build_with_self_heal(always_fail, retries=1)


class TestAdapterInterface:
    def test_fake_adapter_ensure_connected(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        ad = FakeAdapter()
        ad.connect({})
        assert ad.health_check()
        ad._connected = False
        assert not ad.health_check()
        ad.ensure_connected()
        assert ad.health_check()

    def test_interface_has_optional_method(self):
        from rfauto.adapters.fake_adapter import FakeAdapter
        from rfauto.adapters.hfss_adapter import HfssAdapter
        from rfauto.core.interfaces import SimulatorAdapter

        for cls in (FakeAdapter, HfssAdapter):
            assert hasattr(cls, "ensure_connected"), f"{cls.__name__} 缺 ensure_connected"
        assert hasattr(SimulatorAdapter, "ensure_connected")


class TestLogDistillerWP36:
    """WP3.6：openEMS/HFSS/审计 JSON → 结构化 digest（纯规则、best-effort）。"""

    def test_openems_stdout_digested(self):
        from rfauto.pipeline.log_distiller import distill_log

        log = "\n".join([
            "[openEMS] CSXCAD: domain 0..40mm",
            "[openEMS] Time step: 7.7e-19 s",
            "Warning: near-coincident mesh lines detected",
            "Traceback (most recent call last):",
            "IndexError: list index out of range",
            "[openEMS] CalcPort: port 2 failed",
        ])
        digest = distill_log(log)
        assert digest["ok"] is True
        assert digest["source"] == "openems"
        assert digest["metrics"]["timestep_s"] == pytest.approx(7.7e-19)
        assert "timestep_collapse" in digest["signatures"]
        assert "calcport_index_error" in digest["signatures"]
        assert "near_coincident_mesh" in digest["signatures"]
        assert digest["errors"]

    def test_hfss_log_digested(self):
        from rfauto.pipeline.log_distiller import distill_log

        log = "\n".join([
            "PyAEDT INFO: Solving setup main_setup",
            "Adaptive Pass 3",
            "Delta S: 0.0012",
            "Solution completed",
            "Total solve time: 120 s",
        ])
        digest = distill_log(log)
        assert digest["source"] == "hfss"
        assert digest["metrics"]["delta_s"] == pytest.approx(0.0012)
        assert digest["metrics"]["adaptive_passes"] == 3
        assert digest["metrics"]["solve_time_s"] == pytest.approx(120.0)

    def test_audit_json_mapping(self):
        from rfauto.pipeline.log_distiller import distill_log

        digest = distill_log({
            "rc": 1,
            "errors": ["CalcPort failed"],
            "warnings": ["mesh coarse"],
            "metrics": {"s11_db_min": -14.2},
            "timestep_s": 3.1e-13,
        })
        assert digest["source"] == "audit_json"
        assert digest["rc"] == 1
        assert digest["errors"] == ["CalcPort failed"]
        assert digest["metrics"]["s11_db_min"] == pytest.approx(-14.2)
        assert digest["metrics"]["timestep_s"] == pytest.approx(3.1e-13)

    def test_audit_json_text_parsed(self):
        from rfauto.pipeline.log_distiller import distill_log

        digest = distill_log('{"rc": 2, "errors": ["solver failed"]}')
        assert digest["source"] == "audit_json"
        assert digest["rc"] == 2
        assert digest["errors"] == ["solver failed"]

    @pytest.mark.parametrize("bad", ["", "   \n ", None, 123, object()])
    def test_best_effort_never_raises(self, bad):
        from rfauto.pipeline.log_distiller import distill_log

        digest = distill_log(bad)
        assert digest["ok"] is False
        assert digest["source"] in {"empty", "unparsed"}
        assert digest["signatures"] == []
        assert digest["errors"] == []

    def test_corrupt_json_falls_back_to_text(self):
        from rfauto.pipeline.log_distiller import distill_log

        digest = distill_log('{"broken": [1, 2,')
        assert digest["ok"] is True
        assert digest["notes"]

    def test_distill_file_missing_is_best_effort(self, tmp_path):
        from rfauto.pipeline.log_distiller import distill_file

        digest = distill_file(tmp_path / "nope.log")
        assert digest["ok"] is False
        assert digest["notes"]


class TestMinimalSelfHealLoop:
    """F5：LogDistiller → 确定性 critique → 最小自愈环（LLM 只留接口不调用）。"""

    _CALCPORT_LOG = (
        "[openEMS] Time step: 7.7e-19 s\n"
        "IndexError: list index out of range\n"
        "[openEMS] CalcPort: port 2 failed"
    )

    def test_known_failure_log_root_cause(self):
        from rfauto.pipeline.self_heal import critique_failure

        crit = critique_failure(self._CALCPORT_LOG)
        assert crit["verdict"] == "diagnosed"
        assert crit["root_cause_id"] == "calcport_index_error"
        assert crit["actions"]
        assert any("最小间距" in action for action in crit["actions"])

    def test_license_signature(self):
        from rfauto.pipeline.self_heal import critique_failure

        crit = critique_failure("FLEXlm error: license not available for hfss_solver")
        assert crit["root_cause_id"] == "license_unavailable"

    def test_grpc_session_lost_signature(self):
        from rfauto.pipeline.self_heal import critique_failure

        crit = critique_failure("PyAEDT ERROR: gRPC connection dropped")
        assert crit["root_cause_id"] == "hfss_session_lost"

    def test_clean_log_no_root_cause(self):
        from rfauto.pipeline.self_heal import critique_failure

        crit = critique_failure("PyAEDT INFO: Solution completed")
        assert crit["verdict"] == "clean"
        assert crit["root_cause_id"] is None
        assert crit["actions"] == []

    def test_unknown_failure_gets_generic_actions(self):
        from rfauto.pipeline.self_heal import critique_failure

        crit = critique_failure("ERROR: novel failure mode 42")
        assert crit["verdict"] == "unknown_failure"
        assert crit["actions"]

    def test_loop_retries_and_applies_deterministic_fix(self):
        from rfauto.pipeline.self_heal import self_heal_loop

        attempts = []
        fixed = []

        def attempt():
            attempts.append(1)
            if len(attempts) == 1:
                return self._CALCPORT_LOG
            return "PyAEDT INFO: Solution completed"

        report = self_heal_loop(
            attempt, retries=1, apply_fix=lambda c: fixed.append(c["root_cause_id"]))
        assert report["ok"] is True
        assert report["attempts"] == 2
        assert fixed == ["calcport_index_error"]
        assert report["llm_used"] is False

    def test_loop_exhausted_returns_last_critique(self):
        from rfauto.pipeline.self_heal import self_heal_loop

        report = self_heal_loop(lambda: self._CALCPORT_LOG, retries=2)
        assert report["ok"] is False
        assert report["attempts"] == 3
        assert report["critique"]["root_cause_id"] == "calcport_index_error"

    def test_loop_captures_exception_as_failure_log(self):
        from rfauto.pipeline.self_heal import self_heal_loop

        calls = []

        def attempt():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("gRPC connection dropped")
            return "Solution completed"

        report = self_heal_loop(attempt, retries=1)
        assert report["ok"] is True
        assert report["history"][0]["critique"]["root_cause_id"] == "hfss_session_lost"

    def test_llm_explainer_interface_never_called(self):
        from rfauto.pipeline.self_heal import self_heal_loop

        def boom(_critique):
            raise AssertionError("LLM 不应被调用（本项只留接口）")

        report = self_heal_loop(
            lambda: "PyAEDT INFO: Solution completed", llm_explainer=boom)
        assert report["ok"] is True
        assert report["llm_used"] is False
        assert report["llm_explainer_available"] is True
