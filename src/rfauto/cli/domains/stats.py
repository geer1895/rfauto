"""stats 子应用——PT-1/2/3 量产三件套薄壳（规格书 §B-5，2026-10-02）。

零逻辑转发 core/manufacturing_stats（规则 4 薄壳；数值只在确定性内核，
铁律 7；synth.py 先例：纯计算命令域内惰性 import core 直连）：
  rfauto stats guardband  判定规则与保护带（ILAC-G8 保护带接受限）
  rfauto stats cpk        过程能力指数 Cp/Cpk/Ppk + 置信区间
  rfauto stats weibull    右删失 Weibull MLE（Fisher/LR 双口径区间+B10）

JSON 信封直出（ok=false → 退出码 1）；长列表走 --file JSON
（{"samples": [...]} / {"failures": [...], "censored": [...]}）。
"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import app as app

stats_app = typer.Typer(help="量产统计三件套（保护带/能力指数/Weibull 寿命，§B-5）")
app.add_typer(stats_app, name="stats")


def _emit_stats(result: dict) -> None:
    """JSON 信封直出；ok=False → 退出码 1（fab_app._emit 同款口径）。"""
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise typer.Exit(code=1)


def _split_floats(spec: str, name: str) -> list[float]:
    """逗号分隔串 → float 列表（空串/非法 → ValueError 由内核出口统一兜）。"""
    try:
        return [float(t) for t in spec.split(",") if t.strip()]
    except ValueError as exc:
        raise ValueError(f"{name} 含非数值 token: {spec!r}") from exc


def _num_list(samples_opt: str, file_opt: str, key: str, name: str) -> list[float]:
    """--samples/--failures 逗号串 或 --file JSON（{key: [...]}）二选一。"""
    if samples_opt:
        return _split_floats(samples_opt, name)
    if file_opt:
        from rfauto.cli.domains._core import _load_json_file

        data = _load_json_file(file_opt, f"{name} JSON 文件")
        if key not in data:
            raise ValueError(f"{name} JSON 文件缺 {key!r} 键")
        return list(data[key])
    raise ValueError(f"需要 --{key} 列表或 --file JSON")


@stats_app.command("guardband")
def stats_guardband_cmd(
    value: float = typer.Argument(..., help="被测量值（与规格限同单位）"),
    u95: float = typer.Option(..., "--u95", help="95%% 展开不确定度 U（en_report GUM 口径）"),
    tu: float = typer.Option(None, "--tu", help="上规格限 TU（upper/both 侧必填）"),
    tl: float = typer.Option(None, "--tl", help="下规格限 TL（lower/both 侧必填）"),
    side: str = typer.Option("upper", "--side", help="upper|lower|both"),
    pfa: float = typer.Option(0.02, "--pfa", help="误接受概率目标 PFA"),
    k: float = typer.Option(1.96, "--k", help="U 的包含因子（en_report U=k=2 时传 2）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """保护带接受限与判定（ILAC-G8：AL=TU−w、w=m·U、m=z_{1−PFA}/k）."""
    from rfauto.core.manufacturing_stats import guardband_limits

    if side == "upper":
        spec: object = tu
    elif side == "lower":
        spec = tl
    else:
        if tu is None or tl is None:
            typer.echo("both 侧需要 --tu 与 --tl", err=True)
            raise typer.Exit(code=2)
        spec = (tl, tu)
    try:
        result = guardband_limits(value, u95, spec, pfa, side, k=k)
    except ValueError as exc:
        _emit_stats({"ok": False, "error": str(exc)})
        return
    _emit_stats(result)


@stats_app.command("cpk")
def stats_cpk_cmd(
    samples: str = typer.Option("", "--samples", help="样本逗号串（与 --file 二选一）"),
    file: str = typer.Option("", "--file", help="JSON 文件 {\"samples\": [...]}"),
    lsl: float = typer.Option(None, "--lsl", help="下规格限 LSL（与 --usl 至少其一）"),
    usl: float = typer.Option(None, "--usl", help="上规格限 USL（与 --lsl 至少其一）"),
    confidence: float = typer.Option(0.95, "--confidence", help="置信水平"),
    ppk_method: str = typer.Option("normal", "--ppk-method", help="normal|lognormal（dB 域走 normal）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """Cp/Cpk/Ppk 点估计+置信区间（σ̂=s/c4(n)；Cpk CI=Bissell 1990 近似）."""
    from rfauto.core.manufacturing_stats import cpk_ci

    try:
        xs = _num_list(samples, file, "samples", "samples")
        result = cpk_ci(xs, lsl, usl, confidence, ppk_method=ppk_method)
    except ValueError as exc:
        _emit_stats({"ok": False, "error": str(exc)})
        return
    _emit_stats(result)


@stats_app.command("weibull")
def stats_weibull_cmd(
    failures: str = typer.Option("", "--failures", help="失效时间逗号串（与 --file 二选一）"),
    censored: str = typer.Option("", "--censored", help="右删失时间逗号串（可空）"),
    file: str = typer.Option("", "--file", help="JSON 文件 {\"failures\": [...], \"censored\": [...]}"),
    confidence: float = typer.Option(0.95, "--confidence", help="置信水平"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """右删失 Weibull MLE（scipy CensoredData；Fisher/LR 双口径区间+B10 下限）."""
    from rfauto.core.manufacturing_stats import weibull_mle

    try:
        if file:
            from rfauto.cli.domains._core import _load_json_file

            data = _load_json_file(file, "failures JSON 文件")
            if "failures" not in data:
                raise ValueError("failures JSON 文件缺 'failures' 键")
            xf = list(data["failures"])
            raw_c = data.get("censored")
            xc = list(raw_c) if raw_c is not None else None
        elif failures:
            xf = _split_floats(failures, "failures")
            xc = _split_floats(censored, "censored") if censored else None
        else:
            raise ValueError("需要 --failures 列表或 --file JSON")
        result = weibull_mle(xf, xc, confidence=confidence)
    except ValueError as exc:
        _emit_stats({"ok": False, "error": str(exc)})
        return
    _emit_stats(result)
