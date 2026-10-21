"""rest 子应用——REST 面 schema 导出叶（架构批 REST-B 席，2026-10-14）。

零逻辑转发 service/rest_api（规则 4 薄壳；端点清单程序化枚举
``rest_api._ROUTE_TABLE`` 单源，禁手抄清单——防漂移）：
  rfauto rest schema                     端点清单（方法/路径/查询参数/信封形态摘要）
  rfauto rest schema --out rest_schema.json    清单 JSON 落盘（机读面可用）
  rfauto rest schema --openapi --out openapi.json
                                         完整 OpenAPI 3.0.3 spec 落盘（裸 spec
                                         对象非信封包裹；线上同源
                                         GET /api/v1/openapi.json）

registration：域内自注册 add_typer（stats/firmware/recast 同款惯例，
main.py 只 re-export 不二次注册）；顶层无同名 ``rest`` 命令（#df6①
冲突检查 2026-10-14：全 CLI 树零撞名）。全叶带 ``--json``（W2-C 棘轮
门惯例）。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _emit_usage_error as _emit_usage_error
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.service.envelope import error_envelope as error_envelope
from rfauto.service.envelope import ok_envelope as ok_envelope

rest_app = typer.Typer(
    help="REST 面 schema 导出（端点清单与 OpenAPI spec 机读出口，只读）")
app.add_typer(rest_app, name="rest")

# help 渲染安全（#305/#146 家族）：子应用描述禁含裸 % 与方括号
# （recast/edb 同款导入期 assert 钉子应用描述；叶面由 help 卫生常驻门覆盖）。
assert "%" not in (rest_app.info.help or "")
assert "[" not in (rest_app.info.help or "")


def _write_json(path: Path, document: dict) -> None:
    """UTF-8 JSON 落盘（ensure_ascii=False + 尾换行；OSError 上抛由叶统一入信封）。"""
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


@rest_app.command("schema")
def rest_schema_cmd(
    out: str = typer.Option(
        None, "--out", help="JSON 落盘路径（缺省=只 stdout，不写盘）"),
    openapi: bool = typer.Option(
        False, "--openapi",
        help="导出完整 OpenAPI 3.0.3 spec 而非端点清单（须配合 --out 落盘）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """REST 全端点机器可读清单（程序化枚举路由表单源，防手抄漂移）。"""
    from rfauto.service import rest_api

    if not out:
        if openapi:
            _emit_usage_error(
                "--openapi 导出必须给 --out 落盘路径（裸 spec 对象非信封形，"
                "不走 stdout；线上同源 GET /api/v1/openapi.json）",
                json_output=json_output)
        out_path = None
    else:
        out_path = Path(out)

    if openapi:
        spec = rest_api.openapi_spec()
        try:
            _write_json(out_path, spec)
        except OSError as exc:
            _emit(error_envelope(f"OpenAPI spec 落盘失败: {exc}"),
                  "OpenAPI spec 落盘失败", json_output=json_output)
        result = ok_envelope(
            format="openapi", openapi_version=spec["openapi"],
            n_endpoints=len(spec["paths"]), out_path=str(out_path),
            written=True)
        _emit(result, "OpenAPI spec 导出失败", json_output=json_output)
        if not json_output:
            console.print(
                f"[green]✓ OpenAPI {spec['openapi']} spec"
                f"（{len(spec['paths'])} paths）[/green] → {out_path}")
        raise typer.Exit(code=0)

    result = rest_api.endpoint_inventory()
    if out_path is not None:
        try:
            _write_json(out_path, result)
        except OSError as exc:
            _emit(error_envelope(f"端点清单落盘失败: {exc}"),
                  "端点清单落盘失败", json_output=json_output)
        result = {**result, "out_path": str(out_path), "written": True}
    _emit(result, "端点清单导出失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ REST 端点 {result['n_endpoints']} 个"
        f"（前缀 {result['api_prefix']}，操作 {result['n_operations']} 个）"
        f"[/green] ← 完整 spec: GET {result['openapi_endpoint']}"
        + (f" → 落盘 {out_path}" if out_path is not None else ""))
    table = Table(title="rfauto REST 端点清单")
    for col in ("path", "methods", "request", "summary"):
        table.add_column(col, style="cyan" if col == "path" else None)
    for ep in result["endpoints"]:
        table.add_row(
            ep["path"], ",".join(ep["methods"]),
            ep["request_schema"] or "-", ep["summary"])
    console.print(table)
    raise typer.Exit(code=0)
