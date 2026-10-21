"""templates 子应用——EC-8 全模板 golden 几何回归仓薄壳（架构批 W2-S8）。

零逻辑转发 service/template_golden_service（规则 4 薄壳；stats.py 先例：
域内自注册模块级 add_typer，main.py 只 re-export——二次 add_typer 会双
注册打红 zero-shadow 钉）。顶层无同名 `templates` 域（#df6① 冲突检查
2026-10-18：全 CLI 树零撞名；唯一近名 `template-spec` 是 bands 域子应用
TemplateSpec 注册表，语义不同）。

JSON 信封直出（stats 同款口径）：本命令缺省即 JSON 信封，--json 为归一
兼容位；diff 命中漂移/缺失时退出码 1（判定=verdict 字段：clean|drift|
missing，信封仍 ok=True——调用成立、回归状态非零，Unix diff 门惯例）。
"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import app as app
from rfauto.service.envelope import error_envelope, ok_envelope

templates_app = typer.Typer(
    help="模板 golden 几何回归仓（EC-8：渲染哈希+CSX 摘要逐族对比）")
app.add_typer(templates_app, name="templates")

#: 本域 CLI 信封 schema 版本（stats 同款无戳域补戳；1.0=首批口径）
TEMPLATES_GOLDEN_SCHEMA_VERSION = "1.0"


def _emit(result: dict, *, fail_verdict: bool = False) -> None:
    """JSON 信封直出；fail_verdict=True 且 verdict 非 clean → 退出码 1
    （golden-diff 门语义：调用成立 ok=True、回归状态非零，Unix diff 惯例）。"""
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=1)
    if fail_verdict and result.get("verdict", "clean") != "clean":
        raise typer.Exit(code=1)


@templates_app.command("golden-diff")
def templates_golden_diff_cmd(
    accept: bool = typer.Option(
        False, "--accept",
        help="重生成 golden（显式意图门：接受当前渲染为新基线，防误吞真回归）"),
    template: str = typer.Option(
        "", "--template",
        help="限定单族模板名（缺省=全部注册族；未知族名报错信封）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """模板渲染产物 vs golden 快照逐族对比（脚本 sha256+CSX 几何摘要+网格）。"""
    from rfauto.service import template_golden_service as svc

    names: list[str] | None = [template] if template else None
    try:
        result = (svc.accept_template_golden(names) if accept
                  else svc.diff_template_golden(names))
    except KeyError as exc:
        _emit(error_envelope(
            str(exc), schema_version=TEMPLATES_GOLDEN_SCHEMA_VERSION))
        return
    except OSError as exc:
        _emit(error_envelope(
            f"golden 快照读写失败: {exc}",
            schema_version=TEMPLATES_GOLDEN_SCHEMA_VERSION))
        return
    _emit(ok_envelope(schema_version=TEMPLATES_GOLDEN_SCHEMA_VERSION, **result),
          fail_verdict=not accept)
