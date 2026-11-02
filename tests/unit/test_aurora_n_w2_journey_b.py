"""aurora_n w2 journey-B 席位定向门（F-P2-4 + F-P3-1）：sweep 落点 help + playground 互指钉。

- F-P2-4：sweep 产物实际落在 ``runs/<run_id>/sweep_results/``
  （optimization/sweep_backend.py run_sweep 建目录，w6_a SN-11 测试已钉
  后端行为）——``sweep --help`` 文案必须写明 run 级完整落点，新用户不再
  只看到裸 sweep_results/ 而找不到产物。
- F-P3-1：代理 Playground 是纯 UI 面（#/playground 页，/api/playground/*
  路由；CLI 无对应命令）——主 help 头与 ``ui --help`` 各留一行互指引路；
  反向互指不成立（playground 页无 CLI 相关操作，纯代理预测/探索）。
- 指针有效性：互指目标（UI playground 页壳）存在性一并钉住——help 指进
  虚空比不指更伤旅程。
- 字符纪律（D-06）：新增 help 文案零裸 ``[`` 零 ``%``——
  test_cli_help_text_hygiene 全树门自动覆盖本批文案，此处不重复建门。
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

runner = CliRunner()


def _help_text(args: list[str]) -> str:
    from rfauto.cli.main import app

    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.output


class TestSweepHelpArtifactLocation:
    """F-P2-4：sweep --help 写明产物落点 runs/<run_id>/sweep_results/。"""

    def test_sweep_help_names_run_scoped_results_dir(self):
        text = _help_text(["sweep", "--help"])
        assert "runs/<run_id>/sweep_results/" in text, (
            "sweep --help 必须写明产物落点 runs/<run_id>/sweep_results/"
            "（F-P2-4：裸 sweep_results/ 让新用户找不到产物）"
        )
        assert "run_id" in text, "落点说明须含 run_id 查找指引"

    def test_pointer_target_backend_dir_is_run_scoped(self):
        """文案与后端同源：run_sweep 建目录源码含 run_dir / 'sweep_results'。"""
        src = Path(
            Path(__file__).parent.parent.parent
            / "src" / "rfauto" / "optimization" / "sweep_backend.py"
        ).read_text(encoding="utf-8")
        assert 'run_dir / "sweep_results"' in src, (
            "落点文案锚定的后端实现已变——同步改 sweep docstring 与本钉"
        )


class TestPlaygroundCrossRef:
    """F-P3-1：CLI 面互指 UI #/playground 页（主 help 头 + ui --help）。"""

    def test_main_help_mentions_playground_page(self):
        text = _help_text(["--help"])
        assert "#/playground" in text, (
            "主 help 头须有交互式代理试验台互指（F-P3-1：CLI 用户不知道"
            "有滑条实时看代理预测能力）"
        )
        assert "rfauto ui" in text, "互指须带入口命令"

    def test_ui_help_mentions_playground_page(self):
        text = _help_text(["ui", "--help"])
        assert "#/playground" in text, "ui --help 须指到代理 Playground 页"
        assert "代理" in text

    def test_pointer_target_ui_page_exists(self):
        """指针有效性：UI 壳确有 playground 页（导航按钮+视图 section+页面模块）。"""
        static = (
            Path(__file__).parent.parent.parent
            / "src" / "rfauto" / "ui" / "static"
        )
        index = (static / "index.html").read_text(encoding="utf-8")
        assert 'data-v="playground"' in index, "导航缺 playground 按钮"
        assert 'id="view-playground"' in index, "缺 playground 视图 section"
        assert (static / "pages" / "view_playground.js").is_file(), (
            "缺 playground 页面模块"
        )
