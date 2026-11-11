"""citi 子应用——CITIfile（HP/Keysight 仪器数据格式）读取 CLI 薄壳
（aurora_q 席位 Q-X35）。

零逻辑转发 service/citi_service（Q-X35 单源；规则 4 薄壳；铁律 7 不
涉——解析/解码全在 service+core 确定性内核）：
  rfauto citi info <path> [--max-values N]
  rfauto citi segments <path> [--name S[1,1] ...] [--include-raw]
  rfauto citi network <path>

三叶全部带 --json（合流期"新面必红清单"①：新 CLI 叶必须带 --json 旗
标）；读取面只读零落盘（#105 观测面纪律）。

**注册形态说明（合流契约，主代理接线时照此一步到位）**：本模块自带
独立 typer 根 ``citi_app``（**不**在模块级 add_typer 到共享 app——
tests/gold/cli_registration_order.json 与 test_check_numbers 的
count_cli()==305 锚均为冻结面，Q-X35 禁改；先接线后重锚是显式评审动
作）。合流接线两步：
  1. main.py 追加 re-export（vendor_docs 同款）::
       from rfauto.cli.domains.citi import citi_app as citi_app
       from rfauto.cli.domains._core import app as _citi_reg_app  # noqa
       _citi_reg_app.add_typer(citi_app, name="citi")
  2. 金快照重钉（+1 顶层 citi、+3 叶 =306）::
       .venv/Scripts/python.exe tests/unit/test_cli_registration_order.py --write-gold
     并把 tests/unit/test_check_numbers.py 的 CLI 锚 305→306。
本席测试经 ``citi_app`` 直连（CliRunner），零共享 app 污染、零金快照
漂移（自证测试钉住本模块不被 cli.main 导入）。
"""

from __future__ import annotations

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import console as console

citi_app = typer.Typer(
    help="CITIfile（HP/Keysight 仪器数据格式）读取：结构化解析+skrf 桥接探针")


@citi_app.command("info")
def citi_info_cmd(
    path: str = typer.Argument(..., help="CITIfile (.cti) 路径"),
    max_values: int | None = typer.Option(
        None, "--max-values", help="单值列截断上限（None=不截断）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """包级结构化信息（header/版本/变量/段概览；--max-values 截断值列）。"""
    from rfauto.service.citi_service import citi_info  # lazy: 叶内延迟导入

    result = citi_info(path, max_values=max_values)
    _emit(result, "CITI 解析失败", json_output=json_output)
    if json_output:
        return
    for idx, s in enumerate(result.get("summary") or []):
        console.print(
            f"[green]✓[/green] pkg{idx}"
            f" version={s.get('version')} name={s.get('name')}"
            f" segments={s.get('n_segments')} warnings={s.get('n_warnings')}")
        console.print(f"  segments: {s.get('segment_names')}")


@citi_app.command("segments")
def citi_segments_cmd(
    path: str = typer.Argument(..., help="CITIfile (.cti) 路径"),
    # list[str] 注解触发 B008（str 不触）——vendor_docs --root 同款 noqa 先例
    name: list[str] = typer.Option(  # noqa: B008
        None, "--name", help="段名过滤（可多次，如 S【1,1】；缺省=全段）"),
    include_raw: bool = typer.Option(
        False, "--include-raw", help="undecodable 段带 raw_records 原文"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """数据段解码值读取（complex 值 JSON 形态=re、im 成对）。"""
    from rfauto.service.citi_service import citi_read_segments  # lazy: run-path（Q-X36 补冒号）

    result = citi_read_segments(path, names=name, include_raw=include_raw)
    _emit(result, "CITI 段读取失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓[/green] {result.get('n_segments')} 段")
    for seg in result.get("segments") or []:
        console.print(
            f"  [{seg.get('type')}] {seg.get('var_name')}"
            f" format={seg.get('format')} status={seg.get('decode_status')}"
            f" records={seg.get('n_records')}")
    missing = result.get("missing_names") or []
    if missing:
        console.print(f"  [yellow]未命中段名: {missing}[/yellow]")


@citi_app.command("network")
def citi_network_cmd(
    path: str = typer.Argument(..., help="CITIfile (.cti) 路径"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """skrf 桥接探针（条件匹配才桥；不满足走 skipped 信封如实给原因）。"""
    from rfauto.service.citi_service import citi_network_probe  # lazy: run-path（Q-X36 补冒号）

    result = citi_network_probe(path)
    # skipped 是"能力不适用"不是失败（信封契约三态）——--json 下原样
    # 信封输出（skipped=True）；人读分支按状态着色。
    _emit(result, "CITI skrf 桥接失败", json_output=json_output)
    if json_output:
        return
    if result.get("skipped"):
        console.print(f"[yellow]⚠ skipped: {result.get('reason')}[/yellow]")
        return
    for b in result.get("bridged_packages") or []:
        console.print(
            f"[green]✓[/green] pkg{b.get('package_index')} name={b.get('name')}"
            f" ports={b.get('n_ports')} n_freq={b.get('n_freq')}"
            f" f=[{b.get('f_min_hz'):.6g}, {b.get('f_max_hz'):.6g}] Hz"
            f" z0={b.get('z0_source')}")
