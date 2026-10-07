"""D-06（2026-10-04 上门，2026-10-05 W1-D 收紧为全禁）：CLI 命令 help 文本字符卫生常驻门。

静态扫描（构建 typer app → click 树鸭子遍历 #354 口径，零 subprocess）：
- 裸 `[`：typer 的 --help 经 rich 渲染且 markup 开启——ASCII 词元 `[xxx]`
  被当标记静默吞掉（实测 `A [exp] B` 渲染成 `A  B`）、闭合标记 `[/xxx]`
  直接 MarkupError 炸 --help；CJK 词元侥幸字面通过但属不可移植显示面。
- 裸 `%`：argparse `_expand_help` 对 help 做 %-格式展开，单个 `%` 后随
  非法格式符即 `unsupported format character`（#305 坑）。

2026-10-05 W1-D 批清偿历史残留 10 处后收紧为**全禁**断言 current == set()
（原 _FROZEN_VIOLATIONS 冻结基线与 test_frozen_baseline_still_accurate 基线
账实钉同步删除；清偿逐处对账表见 runs/w1_phase1/w1d/REPORT.md，规格=
runs/research_seats_20261004/ra_criteria/SPECS.md §十）。形态裁决：typer/
click 渲染面**禁 `%%`**（会字面双显，仅 argparse scripts/ 面合法）——本门
按"剔除 %% 后仍数 % "判违例，全角％/全角【】/描述化为合规替代。
参数级 help（--param 描述，另 21 处 `[` 残留）不在本门作用域（任务书口径=
"命令 help 文本"），探针已留档（runs/research_seats_20261004/ra_criteria/
_probe_d06_help.py）供后续批清零（followUp 登记）。

E2 席一次性探针（runs/review_ge8e/e2_cli_mcp_ui/evidence/smoke_help_all.py，
198 命令 subprocess 冒烟）转常驻的静态化版本：不逐命令起进程（秒级、零
subprocess），同一棵树同一判定面。
"""

from __future__ import annotations

from typing import Any

import pytest

_REPO_ALL_BANNED_NOTE = (
    "若此处红：命令 help 含裸 [ 或未成对 %——[ 换全角【】/圆括号或描述化，"
    "% 换全角％（typer/click 面禁 %%，会字面双显）。"
)


def _walk_click_tree(group: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """鸭子判别遍历（#354：typer._click 内嵌 click，isinstance click.Group 全漏）。"""
    out: list[tuple[str, Any]] = []
    commands = getattr(group, "commands", None)
    if not isinstance(commands, dict):
        return out
    for name in sorted(commands):
        sub = commands[name]
        path = f"{prefix} {name}".strip()
        out.append((path, sub))
        sub_commands = getattr(sub, "commands", None)
        if isinstance(sub_commands, dict) and sub_commands:
            out.extend(_walk_click_tree(sub, path))
    return out


def _help_violations(nodes: list[tuple[str, Any]]) -> set[tuple[str, str]]:
    """全部节点 help/short_help 的字符卫生违例集（确定性、无渲染副作用）。"""
    violations: set[tuple[str, str]] = set()
    for path, cmd in nodes:
        for text in (getattr(cmd, "help", None) or "",
                     getattr(cmd, "short_help", None) or ""):
            if "[" in text:
                violations.add((path, "bracket"))
            # %% 成对豁免：剔除后再数（未成对 % 判违例）
            if text.replace("%%", "").count("%"):
                violations.add((path, "percent"))
    return violations


@pytest.fixture(scope="module")
def cli_nodes() -> list[tuple[str, Any]]:
    from typer.main import get_command

    from rfauto.cli.main import app

    return _walk_click_tree(get_command(app))


class TestCliHelpTextHygiene:
    """命令 help 字符卫生：裸 [ / 未成对 % 全禁门（零基线，2026-10-05 收紧）。"""

    def test_cli_tree_walked_nonempty(self, cli_nodes):
        """健全性：注册面遍历必须拿到节点（防 app 构建形态变化让门空转）。"""
        assert len(cli_nodes) > 100

    def test_no_help_violations_beyond_frozen_baseline(self, cli_nodes):
        """全禁断言：全树零违例（历史 10 处残留 2026-10-05 清偿后收紧）。"""
        current = _help_violations(cli_nodes)
        assert current == set(), (
            f"help 字符卫生违例 {len(current)} 处: {sorted(current)}。"
            f"{_REPO_ALL_BANNED_NOTE}"
        )

    def test_detector_sensitivity_negative_control(self):
        """探测器灵敏度：裸 [ / 单个 % / 混合违例必被抓；%% 成对豁免不误报。"""

        class _Cmd:  # 最小鸭子样本（walk 消费 help/short_help/commands 三属性）
            help: str = ""
            short_help: str = ""
            commands: dict | None = None

        def _nodes(help_text: str) -> list[tuple[str, Any]]:
            cmd = _Cmd()
            cmd.help = help_text
            return [("x y", cmd)]

        assert _help_violations(_nodes("带 [实验] 标签")) == {("x y", "bracket")}
        assert _help_violations(_nodes("缩减 >= 50% 且 FSV")) == {("x y", "percent")}
        assert _help_violations(_nodes("FBW%%5%% 合规")) == set()
        assert _help_violations(_nodes("")) == set()
        # short_help 面同样受检
        cmd = _Cmd()
        cmd.short_help = "50% 处"
        assert _help_violations([("x y", cmd)]) == {("x y", "percent")}
