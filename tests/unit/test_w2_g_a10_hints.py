"""UX-A10 错误三段式残差测试（W2-G）：红字面 human 分支 hints 注入。

A10/A3-1 规格（r4 外壳审计）：CLI 红字统一三段式 ✗ 原因 → 建议 → 文档锚。
W1 已挂 --json 分支（_attach_error_hints）；本批补 human 分支
（_print_error_hints_text，best-effort #105）。零网络（#139：映射层纯内存）。
"""

from __future__ import annotations

import json

import pytest
import typer
from typer.testing import CliRunner

from rfauto.cli.domains._core import _emit, _print_error_hints_text

runner = CliRunner()

_KNOWN_ERR = "网格欠分辨：特征尺寸 0.05mm < 4·NEAR=0.125mm（渲染守卫）"
_UNKNOWN_ERR = "totally unknown failure xyzzy"

_app = typer.Typer()


@_app.command("fail-probe")
def fail_probe(json_out: bool = typer.Option(True, "--json/--no-json")) -> None:
    """_emit 失败路径探针（服务返回已知/未知错误各一档由 env 切）。"""
    import os

    err = _KNOWN_ERR if os.environ.get("W2G_PROBE") == "known" else _UNKNOWN_ERR
    _emit({"ok": False, "errors": [err]}, "探针失败", json_output=json_out)


class TestHumanBranchHints:
    def test_known_error_prints_suggestion_and_refs(self, monkeypatch):
        """命中规则：红字面出现"→ 建议"段与 refs 文档锚（三段式②③段）。"""
        monkeypatch.setenv("W2G_PROBE", "known")
        result = runner.invoke(_app, ["--no-json"])
        assert result.exit_code == 1
        assert "✗ 探针失败" in result.output          # ① 原因（既有段）
        assert _KNOWN_ERR in result.output            # ① 错误原文逐字节不动
        assert "→ 建议" in result.output              # ② 建议段（本批补）
        assert "#311" in result.output                # ③ 文档锚/坑号

    def test_unknown_error_zero_hint_lines(self, monkeypatch):
        """未命中规则：零 hint 输出（不编造提示），原错误照常退出 1。"""
        monkeypatch.setenv("W2G_PROBE", "unknown")
        result = runner.invoke(_app, ["--no-json"])
        assert result.exit_code == 1
        assert "✗ 探针失败" in result.output
        assert "- " + _UNKNOWN_ERR in result.output
        assert "→ 建议" not in result.output

    def test_hint_service_failure_swallowed(self, monkeypatch):
        """#105：hint 生成抛错 → 红字主路径照常，无 ②③ 段。"""
        import rfauto.cli.domains._core as core

        def boom(_text):
            raise RuntimeError("hint layer down")

        monkeypatch.setenv("W2G_PROBE", "known")
        monkeypatch.setattr(core, "console", core.console)  # 锚定引用
        monkeypatch.setattr(
            "rfauto.service.error_hints_service.hint_for_message", boom)
        result = runner.invoke(_app, ["--no-json"])
        assert result.exit_code == 1
        assert "✗ 探针失败" in result.output
        assert "→ 建议" not in result.output

    def test_json_branch_unchanged_hints_key(self, monkeypatch):
        """--json 分支回归：W1 hints 键照旧、输出仍为 JSON 信封。"""
        monkeypatch.setenv("W2G_PROBE", "known")
        result = runner.invoke(_app, ["--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["ok"] is False
        assert data["errors"] == [_KNOWN_ERR]
        assert isinstance(data["hints"], list) and data["hints"]


class TestHintFunctionUnit:
    def test_direct_call_known_and_unknown(self, capsys):
        _print_error_hints_text([_KNOWN_ERR])
        out = capsys.readouterr().out
        assert "→ 建议" in out and "#311" in out
        _print_error_hints_text([_UNKNOWN_ERR])
        assert "→ 建议" not in capsys.readouterr().out

    def test_empty_and_bad_input_never_raise(self):
        _print_error_hints_text([])
        _print_error_hints_text(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("out_flag", ["--json", "--no-json"])
def test_exit_code_always_one(out_flag, monkeypatch):
    monkeypatch.setenv("W2G_PROBE", "known")
    result = runner.invoke(_app, [out_flag])
    assert result.exit_code == 1
