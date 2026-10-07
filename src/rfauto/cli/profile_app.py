"""profile 子命令组（PR-8 剖析入口：py-spy 火焰图落 runs）。

薄壳层，零业务逻辑（军规 10）——全部转发 service 层确定性函数：
  rfauto profile status            → service.profile_service.profile_status
  rfauto profile run               → service.profile_service.profile_run

宏图口径=研究扩充 round16 §四 PR-8：
"``rfauto profile`` 封装 py-spy（MIT）火焰图落 runs/"。此前 ge8b Wave B
席B2 按当时任务书收窄为 UI 面（api/profile + 剖析页）；本席补 CLI 面——
py-spy 可用性探测与采样封装对 CLI 脚本/CI 同样可发现可驱动。

注册说明：profile_app 在 cli/main.py 注册上线（``app.add_typer(profile_app,
name="profile")``，bench_app 同款独立子应用文件）；顶层无同名 `profile`
命令（#df6① 冲突检查 2026-10-04：全 CLI 树零撞名）。

py-spy 为可选依赖（MIT）：未装时 status 如实 available=False+安装提示
（exit 0，探测不是门）；run 显错退出码 1（#105：不阻塞其余面）。
"""

from __future__ import annotations

import json

import typer

profile_app = typer.Typer(
    help="剖析入口（PR-8）：py-spy 火焰图落 runs/（py-spy 为可选依赖）")


def _emit(result: dict) -> None:
    """JSON 进出（服务层契约直出）。"""
    typer.echo(json.dumps(result, ensure_ascii=False, indent=1))


@profile_app.command("status")
def status(
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """py-spy 可用性探测（JSON 信封；未装=available=false+安装提示）。"""
    from rfauto.service.profile_service import profile_status

    result = profile_status()
    _emit(result)  # VI-5 W6-B：缺省即 JSON 信封直出，旗标为归一兼容位（两形态同输出）
    # 探测是信息面不是门：available 与否都 exit 0（缺装提示在载荷里）
    raise typer.Exit(code=0)


@profile_app.command("run")
def run(
    pid: int | None = typer.Option(
        None, "--pid", help="附着既有进程 pid（与 --cmd 二选一）"),
    cmd: str | None = typer.Option(
        None, "--cmd",
        help="新起被测命令（按空白分词，如 \"python scripts/x.py --flag\"；与 --pid 二选一）"),
    out_dir: str = typer.Option(
        "runs/profile", "--out-dir", help="产物目录（缺省 runs/profile，随 /runs 静态可看）"),
    duration: float = typer.Option(
        30.0, "--duration", help="采样时长秒（[1, 3600]）"),
    rate: int = typer.Option(
        100, "--rate", help="采样频率 Hz（[10, 1000]）"),
    fmt: str = typer.Option(
        "flamegraph", "--format", help="输出格式：flamegraph(.svg) | speedscope(.json)"),
    out_name: str | None = typer.Option(
        None, "--out-name", help="显式产物名（缺省 pyspy_<slug>.<ext>；同名覆盖）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """py-spy record 封装：采样落盘 runs/（火焰图 .svg 浏览器直接看）。"""
    from rfauto.service.profile_service import profile_run

    result = profile_run(
        pid=pid,
        cmd=cmd.split() if cmd else None,
        out_dir=out_dir,
        duration_s=duration,
        rate_hz=rate,
        fmt=fmt,
        out_name=out_name,
    )
    _emit(result)  # VI-5 W6-B：缺省即 JSON 信封直出，旗标为归一兼容位（两形态同输出）
    raise typer.Exit(code=0 if result.get("ok") else 1)
