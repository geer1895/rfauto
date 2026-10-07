"""W6-E D-07 MCP preflight 挂点定向门（Phase 6 批，2026-10-06）。

判据（ra_criteria SPECS §二 D-07 预声明）：
- ①壳体零逻辑：preflight_run 转发 service.preflight_service.preflight
  一行（monkeypatch 钉通道 #139——payload 透传+结果恒等）；
- ②五门缺段 payload → verdict=attention（unknown 不算 fail 语义钉）+
  门子集合成样本 → verdict 聚合正确（clean/issues 双态）；
- ③stdio stdout 零打印（#278 家族回归钉）。

注册面计数（test_mcp_server.py/test_mcp_tool_consistency.py/check_numbers
/docs 三处/注册序金快照）不在本文件作用域（批纪律：主代理合流集中更新）；
本文件只自证本席注册正确性。预期计数链：MCP 146→147（+1，preflight_run）。
"""

from __future__ import annotations

import asyncio

from rfauto.mcp_tools.preflight import preflight_run


class TestShellForwarding:
    def test_forwards_to_service_preflight(self, monkeypatch):
        """零逻辑转发钉：payload 原样透传 + 结果恒等（壳内零加工）。"""
        import rfauto.service.preflight_service as pf

        seen: list = []
        sentinel = {"ok": True, "verdict": "clean", "gates": [],
                    "summary": {}, "blocked": []}

        def _fake(payload=None):
            seen.append(payload)
            return sentinel

        monkeypatch.setattr(pf, "preflight", _fake)
        out = preflight_run({"gates": ["power"]})
        assert out is sentinel
        assert seen == [{"gates": ["power"]}]

    def test_default_none_payload_forwarded(self, monkeypatch):
        import rfauto.service.preflight_service as pf

        seen: list = []
        monkeypatch.setattr(
            pf, "preflight",
            lambda payload=None: seen.append(payload) or {"ok": True})
        assert preflight_run() == {"ok": True}
        assert seen == [None]

    def test_programming_error_returns_error_envelope(self, monkeypatch):
        """未知子门 ValueError（程序性错误）→ ok=False 信封，不抛出不炸会话。"""
        out = preflight_run({"gates": ["nope"]})
        assert out["ok"] is False
        assert out["errors"] and "未知子门" in out["errors"][0]


class TestVerdictAggregation:
    def test_empty_payload_all_unknown_attention(self):
        """五门缺段 payload：全 unknown → attention（unknown 不算 fail）。"""
        out = preflight_run({})
        assert out["ok"] is True
        assert all(g["status"] == "unknown" for g in out["gates"])
        assert out["verdict"] == "attention"
        assert out["summary"]["fail"] == 0
        assert out["summary"]["unknown"] == 5

    def test_subset_both_pass_clean(self):
        """门子集合成样本（power+thermal 双 pass）→ verdict=clean。"""
        out = preflight_run({
            "gates": ["power", "thermal"],
            "power": {"power_levels_w": [1.0, 5.0],
                      "reference_power_w": 1.0,
                      "reference_field_peak_mv_per_m": 1.0,
                      "material": "air"},
            "thermal": {"power_w": 1.0, "theta_jc_c_per_w": 10.0,
                        "max_junction_c": 150.0},
        })
        assert out["ok"] is True
        assert all(g["status"] == "pass" for g in out["gates"])
        assert out["verdict"] == "clean"

    def test_fail_gives_issues(self):
        """检出 fail（功率超参考场）→ verdict=issues（拦截语义）。"""
        out = preflight_run({
            "gates": ["power"],
            "power": {"power_levels_w": [1.0],
                      "reference_power_w": 1.0,
                      "reference_field_peak_mv_per_m": 1e9,
                      "material": "air"},
        })
        assert out["verdict"] == "issues"
        assert out["summary"]["fail"] >= 1


class TestRegistration:
    def test_tool_registered_in_mcp_server(self):
        """注册自证：preflight_run 在 MCP 工具名集（总数钉归主代理计数面）。"""
        from rfauto.mcp_server import mcp

        names = {t.name for t in asyncio.run(mcp.list_tools())}
        assert "preflight_run" in names

    def test_shell_no_stdout(self, capsys):
        """stdio stdout 零打印（#278 家族）：工具调用不污染 JSON-RPC 信道。"""
        preflight_run({})
        preflight_run({"gates": ["nope"]})
        assert capsys.readouterr().out == ""
