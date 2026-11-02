"""W1-E UX-A12 定向门——cli run 失败路径尾部接 explain_run 根因候选摘要。

判据（runs/w1_phase1/criteria.md §W1-E）：
- 注入已知指纹的合成失败 run（tmp_path 构造）→ 输出含"根因候选"摘要段；
- 原错误文本逐字节保留（摘要不得遮蔽/改写原错误，#105 best-effort）；
- 缺 run_dir / explain_run 抛异常 → 摘要静默降级，原错误与退出码不变。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.cli.main import app

runner = CliRunner()

# 短错误串（<60 字符）：rich console 80 列内不折行，逐字节保留断言才稳。
_ORIGINAL_ERROR = "求解失败: BOOM_MARK_42"
_SELECTION_ERROR_TEXT = "Objects or Faces selected do not exist: PortSheet1"


def _make_failed_run(tmp_path: Path) -> str:
    """合成失败 run：meta status=failed + 已知指纹（hfss_selection_error）。

    指纹→规则映射走真仓 playbook（pyaedt_geometry_selection_api，
    applicable_templates=["*"]，无 meta.model 也命中）。
    """
    run_dir = tmp_path / "runs" / "syn_failed"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(
        json.dumps({"run_id": "syn_failed", "status": "failed"}),
        encoding="utf-8")
    (run_dir / "case.err").write_text(
        f"Traceback\n{_SELECTION_ERROR_TEXT}\n", encoding="utf-8")
    return str(run_dir)


def _invoke_run(monkeypatch: pytest.MonkeyPatch, envelope: dict):
    monkeypatch.setattr("rfauto.service.api.run_once", lambda *a, **k: envelope)
    return runner.invoke(app, ["run", "recipes/__w1e_syn__.yaml"])


class TestExplainTailWired:
    def test_failed_run_with_dir_prints_candidates(self, tmp_path,
                                                   monkeypatch):
        run_dir = _make_failed_run(tmp_path)
        result = _invoke_run(monkeypatch, {
            "ok": False,
            "errors": [_ORIGINAL_ERROR],
            "run_id": "syn_failed",
            "run_dir": run_dir,
        })
        assert result.exit_code == 1
        # 摘要段在
        assert "根因候选" in result.output
        assert "pyaedt_geometry_selection_api" in result.output
        # 原错误文本逐字节保留（摘要之前出现，不被改写）
        assert _ORIGINAL_ERROR in result.output
        assert result.output.index(_ORIGINAL_ERROR) < \
            result.output.index("根因候选")

    def test_no_hit_no_summary_no_hardfit(self, tmp_path, monkeypatch):
        """零指纹 run（完全空目录）→ 不输出摘要段（no_hit 不硬凑，#122）。

        注意：仅 meta.json status=failed 也构成 meta_status_failed 指纹
        （→ run_execution_failed 候选，真命中会出摘要）——真 no_hit 必须
        连 meta 都没有。
        """
        run_dir = tmp_path / "runs" / "syn_empty"
        run_dir.mkdir(parents=True)
        result = _invoke_run(monkeypatch, {
            "ok": False,
            "errors": [_ORIGINAL_ERROR],
            "run_dir": str(run_dir),
        })
        assert result.exit_code == 1
        assert "根因候选" not in result.output
        assert _ORIGINAL_ERROR in result.output

    def test_status_failed_meta_yields_run_execution_failed(self, tmp_path,
                                                             monkeypatch):
        """仅 meta status=failed = 真指纹：摘要段给 run_execution_failed 候选。"""
        run_dir = tmp_path / "runs" / "syn_status_only"
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(
            json.dumps({"run_id": "syn_status_only", "status": "failed"}),
            encoding="utf-8")
        result = _invoke_run(monkeypatch, {
            "ok": False,
            "errors": [_ORIGINAL_ERROR],
            "run_dir": str(run_dir),
        })
        assert result.exit_code == 1
        assert "根因候选" in result.output
        assert "run_execution_failed" in result.output
        assert _ORIGINAL_ERROR in result.output

    def test_missing_run_dir_silently_skips(self, monkeypatch):
        result = _invoke_run(monkeypatch, {
            "ok": False,
            "errors": [_ORIGINAL_ERROR],
        })
        assert result.exit_code == 1
        assert "根因候选" not in result.output
        assert _ORIGINAL_ERROR in result.output

    def test_explain_failure_does_not_break_error_path(self, monkeypatch):
        """#105 best-effort：explain_run 抛异常 → 一行降级提示，原错误照常。"""
        def _boom(*a, **k):
            raise RuntimeError("playbook 引擎炸了")
        monkeypatch.setattr("rfauto.service.explain_run.explain_run", _boom)
        result = _invoke_run(monkeypatch, {
            "ok": False,
            "errors": [_ORIGINAL_ERROR],
            "run_dir": "runs/whatever",
        })
        assert result.exit_code == 1
        assert _ORIGINAL_ERROR in result.output
        assert "根因候选摘要不可用" in result.output

    def test_success_path_unchanged(self, monkeypatch):
        """成功路径零变化（摘要只在失败分支）。"""
        monkeypatch.setattr("rfauto.service.api.run_once", lambda *a, **k: {
            "ok": True, "run_id": "r1", "run_dir": "runs/r1",
            "cost": 0.1, "metrics": {},
        })
        result = runner.invoke(app, ["run", "recipes/__w1e_syn__.yaml"])
        assert result.exit_code == 0
        assert "根因候选" not in result.output
        assert "✓ 仿真完成" in result.output
