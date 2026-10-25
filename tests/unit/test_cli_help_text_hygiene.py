"""D-06（2026-10-04 上门，2026-10-05 W1-D 收紧为全禁）：CLI 命令 help 文本字符卫生常驻门。

静态扫描（构建 typer app → click 树鸭子遍历 #354 口径，零 subprocess）：
- 裸 `[`：typer 的 --help 经 rich 渲染且 markup 开启——ASCII 词元 `[xxx]`
  被当标记静默吞掉（实测 `A [exp] B` 渲染成 `A  B`）、闭合标记 `[/xxx]`
  直接 MarkupError 炸 --help；CJK 词元侥幸字面通过但属不可移植显示面。
- 裸 `%`：argparse `_expand_help` 对 help 做 %-格式展开，单个 `%` 后随
  非法格式符即 `unsupported format character`（#305 坑）。

2026-10-05 W1-D 批清偿历史残留 10 处后收紧为**全禁**断言 current == set()
（原 _FROZEN_VIOLATIONS 冻结基线与 test_frozen_baseline_still_accurate 基线
账实钉同步删除；清偿逐处对账表见 内部证据档，规格=
内部证据档 §十）。形态裁决：typer/
click 渲染面**禁 `%%`**（会字面双显，仅 argparse scripts/ 面合法）——本门
按"剔除 %% 后仍数 % "判违例，全角％/全角【】/描述化为合规替代。
参数级 help（--param 描述，另 21 处 `[` 残留）不在本门作用域（任务书口径=
"命令 help 文本"），探针已留档（内部证据档
_probe_d06_help.py）供后续批清零（followUp 登记）。

2026-10-11 aurora36 W5-C：参数级 21 处残留清偿（bench_app×5/domains×14/
profile_app×2，改写口径同上：全角【】/圆括号/描述化，语义不变），D-06
参数级欠账闭合——新增 TestParamHelpTextHygiene 下探 cmd.params 逐
click.Parameter.help（同一棵树同一判定面），裸 `[` 全禁棘轮（参数 help 无
%-展开，% 面不进参数级门）。源码级归因工具=scripts/check_cli_help_bracket
.py（AST 静态扫，merge_preflight 检查面）。

E2 席一次性探针（内部证据档，
198 命令 subprocess 冒烟）转常驻的静态化版本：不逐命令起进程（秒级、零
subprocess），同一棵树同一判定面。

2026-10-24 aurora_l Wave-H H4：新增 TestHelpCopyBlacklist——
docs/style/ui-copy-humanize.md（aurora_k K1 定稿）R2 套话黑名单+R3 空洞尾
在 CLI help/docstring 面的全树零基线棘轮（文案词汇面，与上方字符卫生门
同判定面；豁免与未入册面见该类 docstring）。
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


class TestParamHelpTextHygiene:
    """D-06 参数级清偿（2026-10-11 aurora36 W5-C）：参数 help 同禁裸 [。

    命令级门（上方 TestCliHelpTextHygiene）只查 cmd.help/short_help；本类
    下探 cmd.params 逐 click.Parameter.help——typer.Option/Argument 的 help
    字面同经 rich 渲染，裸 `[` 同样吞词元（`A [exp] B`→`A  B`）或炸
    MarkupError。清偿前残留 21 处（bench_app×5、cli/domains×14、
    profile_app×2，2026-10-11 W5-C 清偿，改写=全角【】/圆括号/描述化），
    清偿后全禁棘轮（零基线）。参数 help 经 click 无 %-展开，% 面不进本门。
    源码级归因工具=scripts/check_cli_help_bracket.py（preflight 检查面）。
    """

    def test_param_tree_has_params(self, cli_nodes):
        """健全性：参数面必须非空（防 app 构建形态变化让门空转）。"""
        total = sum(len(getattr(cmd, "params", None) or []) for _, cmd in cli_nodes)
        assert total > 500

    @staticmethod
    def _param_bracket_violations(
            nodes: list[tuple[str, Any]]) -> list[tuple[str, str, str]]:
        """全部节点 params 的 help 裸 `[` 违例清单（确定性、无渲染副作用）。"""
        out: list[tuple[str, str, str]] = []
        for path, cmd in nodes:
            for param in getattr(cmd, "params", None) or []:
                text = getattr(param, "help", None) or ""
                if "[" in text:
                    out.append((path, str(getattr(param, "name", "?")), text))
        return out

    def test_no_param_help_brackets(self, cli_nodes):
        """全禁断言：全树参数 help 零裸 [（D-06 参数级 2026-10-11 清偿后收紧）。"""
        current = self._param_bracket_violations(cli_nodes)
        assert current == [], (
            f"参数级 help 含裸 [ 共 {len(current)} 处: {sorted(current)}。"
            f"{_REPO_ALL_BANNED_NOTE}"
        )

    def test_param_detector_sensitivity_negative_control(self):
        """探测器灵敏度：参数 help 含裸 [ 必被抓；无 [ 不误报。"""

        class _Cmd:  # 最小鸭子样本（walk 消费 params 属性）
            help: str = ""
            short_help: str = ""
            commands: dict | None = None
            params: list | None = None

        cmd = _Cmd()
        cmd.params = [_ParamStub('JSON 文件（键 samples，值为数值数组）')]
        assert self._param_bracket_violations([("x y", cmd)]) == []
        cmd.params = [_ParamStub('规范限 [metric,op,value] 格式')]
        assert self._param_bracket_violations([("x y", cmd)]) == [
            ("x y", "p", '规范限 [metric,op,value] 格式')
        ]


class TestHelpCopyBlacklist:
    """aurora_l Wave-H H4（2026-10-24）：R2 套话黑名单+R3 空洞尾全树零基线棘轮。

    docs/style/ui-copy-humanize.md（aurora_k K1 定稿）词汇层在 CLI help 面
    （cmd.help/short_help + 参数 help，与上方字符卫生门同判定面）的移植：
    零容忍逐词检索，命中即红，棘轮只收不放。与 i18n 扫描器分工相同——
    本门=机械面（词面命中），守则=人工判据（误杀边界最终裁定）。

    豁免与未入册面（2026-10-24 全树 355 节点盘点实证）：
    - "智能体"（agent 术语）剥除后再匹配"智能"（营销义）——bench
      agentbench 首行"智能体基准"为全树唯一近误报源，先剥后匹配零误报；
    - "闭环"控制回路义（design close/campaign run/vna）按守则物理义
      豁免条款留人工判据，不进机械门；
    - "口径"（计量基准义：mm 口径/GUM 口径/METR 口径，全树 22 处）与
      "一键"（单命令义，全树 5 处）存量另册未入本门——技术义非营销义，
      清偿与否属全站专项，非本席裁；
    - en 侧词表（R15）误报率高（robust/harness/unlock 在工程语境合法），
      留 i18n 扫描器人工面，不进本门。
    """

    # R2 词汇层零容忍黑名单（zh；ui-copy-humanize.md §一 R2 逐词清单）
    _R2_BLACKLIST = (
        "值得注意的是", "标志着", "彰显", "凸显", "奠定了基础", "助力",
        "赋能", "抓手", "一站式", "全方位", "多维度", "轻松", "强大",
        "智能", "完美", "一目了然", "清晰直观", "深耕", "海量",
        "丰富多彩", "保驾护航", "致力于", "旨在", "卓越", "极致", "无缝",
    )
    # R3 空洞尾同族（预测读者反应，删掉不缺信息）
    _R3_TAILS = ("帮助你", "帮你", "让你轻松", "从此", "尽情")

    @classmethod
    def _copy_violations(cls, nodes) -> list[tuple[str, str, str]]:
        """全树 help 面 R2+R3 黑名单命中清单（确定性，无渲染副作用）。"""
        out: list[tuple[str, str, str]] = []
        for path, cmd in nodes:
            texts = [getattr(cmd, "help", None) or "",
                     getattr(cmd, "short_help", None) or ""]
            for p in getattr(cmd, "params", None) or []:
                texts.append(getattr(p, "help", None) or "")
            for text in texts:
                # "智能体"（agent 术语）豁免：剥除后再匹配营销义"智能"
                probe = text.replace("智能体", "")
                for word in cls._R2_BLACKLIST + cls._R3_TAILS:
                    if word in probe:
                        out.append((path, word, text))
        return out

    def test_tree_copy_blacklist_zero(self, cli_nodes):
        """全树 help/docstring 面 R2+R3 黑名单零命中（零基线棘轮）。"""
        current = self._copy_violations(cli_nodes)
        assert current == [], (
            f"help 文案黑名单命中 {len(current)} 处"
            f"（R2 套话/R3 空洞尾，守则=docs/style/ui-copy-humanize.md）："
            f"{sorted(current)}。"
            "改法=删词后句意不变就删；句意塌了塞 rfauto 专属事实"
            "（命令/文件名/数值），不换同族空话。"
        )

    def test_detector_sensitivity_negative_control(self):
        """探测器灵敏度：黑名单词必被抓；"智能体"豁免不误报。"""

        class _Cmd:  # 最小鸭子样本（walk 消费 help/short_help/params 三属性）
            help: str = ""
            short_help: str = ""
            commands: dict | None = None
            params: list | None = None

        def _nodes(help_text: str) -> list[tuple[str, Any]]:
            cmd = _Cmd()
            cmd.help = help_text
            return [("x y", cmd)]

        assert self._copy_violations(_nodes("一键轻松管理")) == [
            ("x y", "轻松", "一键轻松管理")]
        assert self._copy_violations(_nodes("一目了然地帮助你")) == [
            ("x y", "一目了然", "一目了然地帮助你"),
            ("x y", "帮助你", "一目了然地帮助你"),
        ]
        assert self._copy_violations(_nodes("智能体基准回归门")) == []
        assert self._copy_violations(_nodes("内存闸与指纹对拍")) == []


class _ParamStub:
    """click.Parameter 最小鸭子替身（name/help 两属性）。"""

    def __init__(self, help_text: str, name: str = "p") -> None:
        self.help = help_text
        self.name = name
