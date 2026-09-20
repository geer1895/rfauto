"""6j MCP 客户端通道测试（双通道可选之 mcp 路）。

in-memory 连接 get_mcp_server()，验证"对话→MCP tool call→同源结果"；
同源语义：MCP 工具内部调与内嵌通道相同的 service 函数。
"""

from __future__ import annotations

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestMCPAgentChat:
    def test_help_routing(self):
        from rfauto.cli.mcp_chat import MCPAgentChat
        chat = MCPAgentChat()
        result = chat.chat("hello?")
        assert result["action"] == "help"
        assert "MCP" in result["text"]

    def test_models_via_mcp_tool(self):
        from rfauto.cli.mcp_chat import MCPAgentChat
        chat = MCPAgentChat()
        result = chat.chat("models")
        assert result["ok"], result
        assert result["tool"] == "list_models"
        # 同源：结果与 service.list_models 一致
        from rfauto.service.api import list_models
        assert result["result"] == list_models()

    def test_validate_recipe_via_mcp_tool(self, tmp_path):
        recipe = {
            "model": "wilkinson_power_divider", "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
        }
        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        from rfauto.cli.mcp_chat import MCPAgentChat
        chat = MCPAgentChat()
        result = chat.chat(f"validate {path}")
        assert result["ok"], result
        assert result["result"]["ok"] is True

    def test_history_recorded(self):
        from rfauto.cli.mcp_chat import MCPAgentChat
        chat = MCPAgentChat()
        chat.chat("models")
        chat.chat("help")
        assert len(chat.get_history()) == 4

    def test_cli_chat_mcp_channel(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["chat", "models", "--channel", "mcp"])
        assert result.exit_code == 0, result.output
        assert "通道: mcp" in result.output
        # 输出是 JSON（动作卡片渲染）
        assert "wilkinson" in result.output

    def test_cli_chat_unknown_channel_fails(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["chat", "models", "--channel", "smoke"])
        assert result.exit_code == 1
