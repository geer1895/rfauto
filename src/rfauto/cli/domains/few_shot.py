"""few-shot 子应用——成功会话挖掘→相关性精选→注入节（VI-1 孤儿接线批 W1-C 单元 15）。

零逻辑转发 service/few_shot_service（AD-3 全管线；精选与渲染全在
确定性内核，铁律 7——本子应用只编排与落盘，永不产生物理数字）：
  rfauto few-shot build --task "..." [--sessions-dir DIR] [--k N] [--out f.md]

单命令子应用（build；spec VI-1 表行 15 "单命令"以子应用形态落，
命令文法=rfauto few-shot build）；`few-shot` 名带连字符，#df6① 冲突
检查 2026-10-05：全 CLI 树零撞名。JSON 信封经 _emit 单点出口。
"""

from __future__ import annotations

from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

few_shot_app = typer.Typer(help="成功会话 few-shot 精选（AD-3：挖掘→精选→注入节）")
app.add_typer(few_shot_app, name="few-shot")


@few_shot_app.command("build")
def few_shot_build_cmd(
    task: str = typer.Option(..., "--task",
                             help="当前任务描述（精选相关性依据）"),
    sessions_dir: str = typer.Option(None, "--sessions-dir",
                                     help="会话档目录（缺省= runs 会话双根收敛）"),
    k: int = typer.Option(None, "--k", help="精选条数上限（缺省=内核缺省）"),
    out: str = typer.Option(None, "--out",
                            help="注入节 markdown 落盘路径（缺省只出信封）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """挖掘成功会话 → 相关性精选 top-k → 系统提示词注入节（零网络）。

    示例：rfauto few-shot build --task "综合 2.4GHz wilkinson 功分器并跑校准"
    """
    from rfauto.service.few_shot_service import build_few_shot_system

    kwargs: dict = {}
    if k is not None:
        kwargs["k"] = int(k)
    result = build_few_shot_system(task, sessions_dir=sessions_dir, **kwargs)
    if result.get("ok") and out and result.get("section"):
        Path(out).write_text(str(result["section"]), encoding="utf-8")
        result = dict(result)
        result["section_path"] = out
    _emit(result, "few-shot 构建失败", json_output=json_output)
    if not json_output and result.get("ok"):
        n_ex = len(result.get("exemplars") or [])
        console.print(f"[green]✓ few-shot 注入节[/green] "
                      f"候选={result.get('n_candidates')} 精选={n_ex}")
        if result.get("section_path"):
            console.print(f"  落盘 → [cyan]{result['section_path']}[/cyan]")
    raise typer.Exit(code=0)
