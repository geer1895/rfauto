"""preflight 子应用——XC-F 开工前统一预检薄壳（round18 XC 清单+deepdive B-4）。

零逻辑转发 service/preflight_service（规则 4 薄壳；门面判定全在确定性
service 内核，铁律 7）：
  rfauto preflight run            五门联合预检（缺段=unknown 不阻塞，#105）
  rfauto preflight gates          列门名与缺省序

JSON 信封直出（verdict=issues → 退出码 1；attention/clean → 0）。
payload 来源：--file JSON / --template / --gates 逗号串（三选可组合）。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rfauto.cli.domains._core import app as app

preflight_app = typer.Typer(help="XC-F 开工前统一预检（极限/功率/热/加工/精度档案五门联合）")
app.add_typer(preflight_app, name="preflight")


def _load_payload(template: str, file: str, gates: str) -> dict:
    payload: dict = {}
    if template:
        payload["template"] = template
    if file:
        raw = Path(file).read_text(encoding="utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError(f"--file JSON 顶层须为对象: {type(loaded).__name__}")
        payload.update(loaded)
    if gates:
        names = [g.strip() for g in gates.split(",") if g.strip()]
        if names:
            payload["gates"] = names
    return payload


@preflight_app.command("run")
def preflight_run_cmd(
    template: str = typer.Option("", "--template", help="模板名（精算档案门主键）"),
    file: str = typer.Option("", "--file", help="payload JSON 文件（段结构见 service docstring）"),
    gates: str = typer.Option("", "--gates", help="逗号分隔门子集（缺省五门全跑）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 直出，旗标为归一兼容位）"),
) -> None:
    """五门联合预检；verdict=issues 时退出码 1（拦截语义）。"""
    from rfauto.service.preflight_service import preflight

    payload = _load_payload(template, file, gates)
    result = preflight(payload or None)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("verdict") == "issues":
        raise typer.Exit(code=1)


@preflight_app.command("gates")
def preflight_gates_cmd(
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 直出兼容位（本命令缺省即 JSON，两形态同输出）"),
) -> None:
    """列出门名与缺省顺序（零 payload 只读面）。"""
    from rfauto.service import preflight_service as svc

    typer.echo(json.dumps({"gates": list(svc._GATES)}, ensure_ascii=False))
