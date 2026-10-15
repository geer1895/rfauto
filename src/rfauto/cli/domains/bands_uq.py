"""bands/template-spec/uq/farfield 子应用（WP3.3 CLI 半边主块；recipe_guard 写出口在本模块）（AU-1 自 cli/main.py 机械拆分，2026-09-30；campaign 面 UX-B6 独立迁 cli/domains/campaign.py，本模块薄壳 re-export+注册位保留）。"""

from __future__ import annotations

import json

import typer
from rich.table import Table

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _kv_floats as _kv_floats
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.cli.domains.calc_vna import _coerce_param as _coerce_param
from rfauto.cli.domains.campaign import campaign_app as campaign_app
from rfauto.cli.domains.campaign import campaign_event_cmd as campaign_event_cmd
from rfauto.cli.domains.campaign import campaign_list_cmd as campaign_list_cmd
from rfauto.cli.domains.campaign import campaign_plan_cmd as campaign_plan_cmd
from rfauto.cli.domains.campaign import campaign_run_cmd as campaign_run_cmd
from rfauto.cli.domains.campaign import campaign_status_cmd as campaign_status_cmd
from rfauto.service.envelope import ok_envelope

# ─── bands（D9 频段/环境包络注册表十接口；WP3.3 CLI 半边 0bp②） ───────────────

bands_app = typer.Typer(help="标准频段/环境包络注册表（D9，十接口；数值只出自 core/bands 常量表）")
app.add_typer(bands_app, name="bands")


@bands_app.command("list")
def bands_list_cmd(
    standard: str = typer.Option(None, "--standard", help="按 standard 子串过滤（如 3GPP）"),
    kind: str = typer.Option(None, "--kind", help="按类型过滤（cellular/ism/...）"),
    region: str = typer.Option(None, "--region", help="按区域过滤"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出标准频段注册表（3GPP/Wi-Fi/UWB/ISM/EMC 等，自动生成清单）。"""
    from rfauto.service.bands_service import bands_list

    result = bands_list(standard=standard, kind=kind, region=region)
    _emit(result, "频段查询失败", json_output=json_output)
    if json_output:
        return
    table = Table(title=f"频段注册表（{result['count']}/{result['total']}）")
    for col in ("key", "standard", "kind", "f_low_ghz", "f_high_ghz", "region"):
        table.add_column(col, style="cyan" if col == "key" else None)
    for b in result["bands"]:
        table.add_row(*(str(b.get(c, "")) for c in
                        ("key", "standard", "kind", "f_low_ghz", "f_high_ghz", "region")))
    console.print(table)


@bands_app.command("get")
def bands_get_cmd(
    key: str = typer.Argument(..., help="频段键（如 gpp_n78）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """按 key 取单条频段详情（边界/出处/区域）。"""
    from rfauto.service.bands_service import bands_get

    # VI-5 W2-C：D9 面自始 _emit 信封直出（json_output 缺省 True）；归一旗标
    # 接受但两形态同输出——缺省路径逐字节不变铁纪律优先于纯切换形态。
    _emit(bands_get(key), f"未知频段 {key}", json_output=True)


@bands_app.command("find")
def bands_find_cmd(
    freq_ghz: float = typer.Argument(..., help="频率 GHz"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """查包含给定频率的全部频段条目。"""
    from rfauto.service.bands_service import bands_find

    _emit(bands_find(freq_ghz), "频率查询失败", json_output=True)


@bands_app.command("spec-bounds")
def bands_spec_bounds_cmd(
    key: str = typer.Argument(..., help="频段键"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """频段键 → SpecEvaluator band 结构（f_low/f_high 二元组，喂 objectives）。"""
    from rfauto.service.bands_service import bands_spec_bounds

    _emit(bands_spec_bounds(key), f"未知频段 {key}", json_output=True)


@bands_app.command("env-list")
def bands_env_list_cmd(
    standard: str = typer.Option(None, "--standard", help="按 standard 子串过滤"),
    kind: str = typer.Option(None, "--kind", help="按类型过滤"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """列出环境包络注册表（工业/AEC-Q100/ECSS/IEC 60068 温区等级）。"""
    from rfauto.service.bands_service import bands_env_list

    _emit(bands_env_list(standard=standard, kind=kind), "环境包络查询失败",
          json_output=True)


@bands_app.command("env-get")
def bands_env_get_cmd(
    key: str = typer.Argument(..., help="环境包络键（如 aec_q100_grade1）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """按 key 取单条环境包络详情（温区/等级/出处）。"""
    from rfauto.service.bands_service import bands_env_get

    _emit(bands_env_get(key), f"未知环境包络 {key}", json_output=True)


@bands_app.command("env-find")
def bands_env_find_cmd(
    t_c: float = typer.Argument(..., help="温度 °C"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """查温区覆盖给定温度的全部环境包络。"""
    from rfauto.service.bands_service import bands_env_find

    _emit(bands_env_find(t_c), "温度查询失败", json_output=True)


@bands_app.command("env-delta-t")
def bands_env_delta_t_cmd(
    key: str = typer.Argument(..., help="环境包络键"),
    t_ref_c: float = typer.Option(None, "--t-ref", help="参考温度 °C（缺省用条目自身）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """环境包络 → ΔT 上下限（D3 温区扫描 / D8 UQ / WP4.2 良率消费）。"""
    from rfauto.service.bands_service import bands_env_delta_t

    _emit(bands_env_delta_t(key, t_ref_c), f"未知环境包络 {key}", json_output=True)


@bands_app.command("env-uq-axis")
def bands_env_uq_axis_cmd(
    key: str = typer.Argument(..., help="环境包络键"),
    t_ref_c: float = typer.Option(None, "--t-ref", help="参考温度 °C（缺省用条目自身）"),
    k_sigma: float = typer.Option(3.0, "--k-sigma", help="σ 倍数"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """环境包络 → UQ/良率温度轴（名义点 + σ + ΔT 上下限）。"""
    from rfauto.service.bands_service import bands_env_uq_axis

    _emit(bands_env_uq_axis(key, t_ref_c, k_sigma), f"未知环境包络 {key}",
          json_output=True)


@bands_app.command("env-points")
def bands_env_points_cmd(
    key: str = typer.Argument(..., help="环境包络键"),
    n: int = typer.Option(5, "--n", help="采样点数（含两端）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """环境包络温区等距采样点（供 D3 温区扫描）。"""
    from rfauto.service.bands_service import bands_env_points

    _emit(bands_env_points(key, n), f"未知环境包络 {key}", json_output=True)


# ─── campaign（UX-B6 独立：命令面定义迁 cli/domains/campaign.py，本处仅
# 薄壳 re-export + 注册位保留——click 树注册序金快照零漂移） ─────────────

app.add_typer(campaign_app, name="campaign")


# ─── template-spec（E2 模板库注册表；WP3.3 CLI 半边） ─────────────────────────

template_spec_app = typer.Typer(help="模板库 TemplateSpec 注册表（E2：清单 + 综合草稿）")
app.add_typer(template_spec_app, name="template-spec")


@template_spec_app.command("list")
def template_spec_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """列出全部模板 spec（组件齐备性 render_script/synthesizer/fake_model/hfss_plugin）。"""
    from rfauto.service.template_spec_service import list_template_specs

    result = list_template_specs()
    _emit(result, "模板库查询失败", json_output=json_output)
    if json_output:
        return
    table = Table(title=f"模板库（{len(result['templates'])}）")
    table.add_column("name", style="cyan")
    for comp in ("render_script", "synthesizer", "fake_model", "hfss_plugin"):
        table.add_column(comp)
    table.add_column("physics_roles")
    for t in result["templates"]:
        comps = t.get("components") or {}
        table.add_row(t["name"],
                      *("[green]✓[/green]" if comps.get(c) else "[red]✗[/red]"
                        for c in ("render_script", "synthesizer", "fake_model", "hfss_plugin")),
                      ", ".join(sorted((t.get("physics_roles") or {}).keys())))
    console.print(table)


@template_spec_app.command("draft")
def template_spec_draft_cmd(
    name: str = typer.Argument(..., help="模板名（template-spec list 查看）"),
    param: list[str] | None = typer.Option(None, "--param", "-p",  # noqa: B008
                                           help="综合入口参数 k=v（可重复）"),
    output: str = typer.Option(None, "--output", "-o", help="配方草稿写出 YAML 路径"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """按模板 spec 的综合入口产出配方草稿（零求解、零 license；线宽等由综合内核精算）。"""
    from rfauto.service.template_spec_service import draft_recipe_from_spec

    params: dict = {}
    for item in param or []:
        key, sep, raw = item.partition("=")
        if not sep:
            console.print(f"[red]✗ --param 需要 k=v 形式: {item}[/red]")
            raise typer.Exit(code=2)
        params[key.strip()] = _coerce_param(raw.strip())
    result = draft_recipe_from_spec(name, params)
    if not result.get("ok"):
        # 失败面自始即 _emit 信封（缺省路径逐字节不动）；--json 只切换成功面。
        _emit(result, f"模板 {name} 草稿生成失败")
    if output:
        # --output 由用户显式指定 → 显式保存入口；序列化/落盘走守卫统一出口
        from rfauto.infra.recipe_guard import write_recipe_yaml

        written = write_recipe_yaml(output, result["recipe_draft"], explicit=True)
        if json_output:
            # VI-5 W6-B：--json 信封（落盘副作用保持，路径/覆盖审计并入信封）
            console.print_json(json.dumps(
                ok_envelope(
                    written=str(written),
                    overwritten=bool(getattr(written, "overwritten", False))),
                ensure_ascii=False, default=str))
            return
        console.print(f"[green]✓ 配方草稿已写出[/green] → {written}")
        if getattr(written, "overwritten", False):
            # R2-D-03：explicit 覆盖受保护 recipes/ 既有原件时明示，消除盲写
            console.print("[yellow]⚠ 已覆盖受保护 recipes/ 既有原件"
                          "（overwritten=true）[/yellow]")
    elif json_output:
        # VI-5 W6-B：无 --output 缺省本即 JSON 直出——旗标为归一兼容位
        pass
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))


@template_spec_app.command("recommend")
def template_spec_recommend_cmd(
    f0_ghz: float = typer.Option(..., "--f0-ghz", help="查询中心频率，单位 GHz"),
    topology: str = typer.Option(None, "--topology", help="族键、族标签或拓扑文本子串（如 filter、bpf、喇叭）"),
    n_ports: int = typer.Option(None, "--n-ports", help="端口数相等过滤"),
    keywords: str = typer.Option(None, "--keywords", help="子串过滤词，空格分词 AND 语义（命中 name/topology/param_semantics）"),
    top_k: int = typer.Option(5, "--top-k", help="返回条数，缺省 5"),
    f0_tol: float = typer.Option(0.30, "--f0-tol", help="f0 带内容差（0 至 1 之间，缺省 0.30）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """按指标查询推荐模板（确定性 filter+rank，零 LLM 零物理数字产出）。

    filter：topology 族匹配、n_ports 相等、f0 带内 tol 0.30、keywords 子串；
    rank 主键 f0 贴近度、次键 param_semantics 覆盖数、三键闭式预览通道命中、
    并列模板名字典序（全序确定性）。
    """
    from rfauto.service.gallery_service import recommend_templates

    result = recommend_templates(
        f0_ghz=f0_ghz, topology=topology, n_ports=n_ports,
        keywords=keywords, top_k=top_k, f0_tol=f0_tol)
    _emit(result, "模板推荐失败", json_output=json_output)
    if json_output:
        return
    if result.get("degraded"):
        console.print(f"[yellow]⚠ 降级：{result.get('degrade_reason')}[/yellow]")
    recs = result.get("recommendations") or []
    if not recs:
        console.print("[yellow]⚠ 无命中候选（放宽 topology/keywords/f0-tol 再试）[/yellow]")
        return
    table = Table(title=f"模板推荐（top {len(recs)}/{result['n_candidates']} 候选）")
    table.add_column("name", style="cyan")
    table.add_column("family")
    table.add_column("f0_ghz")
    table.add_column("n_ports")
    table.add_column("f0_dev")
    table.add_column("sem_cover")
    table.add_column("preview")
    table.add_column("docs_link")
    for c in recs:
        rank = c.get("rank") or {}
        table.add_row(
            str(c.get("name")), str(c.get("family") or ""),
            str(c.get("f0_ghz")), str(c.get("n_ports")),
            f"{float(rank.get('f0_dev') or 0.0):.4f}",
            str(rank.get("semantics_covered")),
            "[green]✓[/green]" if c.get("preview") else "-",
            str(c.get("docs_link") or ""))
    console.print(table)


# ─── uq（WP4.2 良率收口三接口；0bw①） ───────────────────────────────────────

uq_app = typer.Typer(help="公差/良率收口（WP4.2：名义点良率 / 设计中心化 / D9 温区良率）")
app.add_typer(uq_app, name="uq")


@uq_app.command("yield-at")
def uq_yield_at_cmd(
    samples: str = typer.Argument(..., help="校准样本集 samples.json"),
    tol: list[str] | None = typer.Option(None, "--tol", help="公差 σ 参数名=值（可多次）"),  # noqa: B008
    at: list[str] | None = typer.Option(None, "--at", help="名义点 参数名=值（可多次，须覆盖公差参数）"),  # noqa: B008
    n: int = typer.Option(10000, "--n", help="蒙特卡洛抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """显式名义点的代理蒙特卡洛良率（良率目标函数点值形式）。"""
    from rfauto.service.uq_service import surrogate_yield_at

    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(surrogate_yield_at(samples, _kv_floats(tol, "--tol"), _kv_floats(at, "--at"),
                             n=n, seed=seed, kind=kind), "良率求值失败", json_output=True)


@uq_app.command("design-center")
def uq_design_center_cmd(
    samples: str = typer.Argument(..., help="校准样本集 samples.json"),
    tol: list[str] | None = typer.Option(None, "--tol", help="公差 σ 参数名=值（可多次）"),  # noqa: B008
    k_sigma: float = typer.Option(3.0, "--k-sigma", help="容差盒半宽 = k_sigma·σ"),
    n_levels: int = typer.Option(3, "--n-levels", help="每维网格层数"),
    max_iter: int = typer.Option(40, "--max-iter", help="坐标搜索最大迭代"),
    n_mc: int = typer.Option(2000, "--n-mc", help="前后认证 MC 抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """良率目标函数 + 设计中心化（容差盒网格违约 cost≤0 良率，坐标搜索；MC 只做前后认证）。"""
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import yield_design_center

    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(annotate_contract("yield_design_center", yield_design_center(
        samples, _kv_floats(tol, "--tol"), k_sigma=k_sigma, n_levels=n_levels,
        max_iter=max_iter, n_mc=n_mc, seed=seed, kind=kind)), "设计中心化失败",
        json_output=True)


@uq_app.command("temp-zone")
def uq_temp_zone_cmd(
    samples: str = typer.Argument(..., help="校准样本集 samples.json（含 t_c 维）"),
    env_key: str = typer.Argument(..., help="环境包络键（bands env-list 查询）"),
    tol: list[str] | None = typer.Option(None, "--tol", help="几何公差 σ 参数名=值（可多次，可空）"),  # noqa: B008
    t_ref_c: float = typer.Option(None, "--t-ref", help="参考温度 °C（缺省用包络自身）"),
    k_sigma: float = typer.Option(3.0, "--k-sigma", help="σ_c = 包络半宽/k_sigma"),
    n: int = typer.Option(10000, "--n", help="蒙特卡洛抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """温区良率（D9 环境包络 → 温度轴 σ 并入 MC + 温区两端角点确定性评估，FAIL 如实）。"""
    from rfauto.service.contracts import annotate_contract
    from rfauto.service.uq_service import temperature_zone_yield

    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(annotate_contract("temperature_zone_yield", temperature_zone_yield(
        samples, _kv_floats(tol, "--tol"), env_key, t_ref_c=t_ref_c, k_sigma=k_sigma,
        n=n, seed=seed, kind=kind)), "温区良率失败", json_output=True)


@uq_app.command("robustness")
def uq_robustness_cmd(
    source: str = typer.Argument(..., help="samples.json | 数据集名 | run id"),
    spec: list[str] = typer.Option(..., "--spec", help="规范限 'metric,op,value,weight'，weight 段可省略（可多次）"),  # noqa: B008
    profile: str | None = typer.Option(None, "--profile", help="公差剖面 YAML 路径或内联 JSON（优先于 --tol）"),
    tol: list[str] | None = typer.Option(None, "--tol", help="公差 σ 参数名=值（可多次；无 profile 时生效）"),  # noqa: B008
    n_mc: int = typer.Option(100000, "--n-mc", help="MC 抽样数"),
    seed: int = typer.Option(42, "--seed", help="随机种子"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理类型 poly_ridge|nn"),
    form_engine: str = typer.Option("auto", "--form-engine", help="FORM 引擎 auto|internal|openturns|uqpy"),
    persist: bool = typer.Option(False, "--persist", help="MC 抽样落盘 Parquet"),
    store_name: str | None = typer.Option(None, "--store-name", help="落盘数据集名"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """稳健性报告：良率 MC（向量化）+FORM Pf+worst-case 角点+逐规范 Cpk（DP-15 C3）。"""
    import json as _json

    from rfauto.service.contracts import annotate_contract
    from rfauto.service.robustness_service import robustness_report

    specs = []
    for raw in spec:
        parts = [s.strip() for s in raw.split(",")]
        if len(parts) < 3:
            raise typer.BadParameter(f"--spec 须为 metric,op,value[,weight]: {raw}")
        entry = {"metric": parts[0], "op": parts[1], "value": float(parts[2])}
        if len(parts) >= 4:
            entry["weight"] = float(parts[3])
        specs.append(entry)
    prof: str | dict | None = profile
    if profile is not None:
        try:
            prof = _json.loads(profile)
        except ValueError:
            prof = profile  # YAML/路径原样交给 service
    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(annotate_contract("robustness_report", robustness_report(
        source, specs, profile=prof, tolerances=_kv_floats(tol, "--tol"),
        n_mc=n_mc, seed=seed, kind=kind, form_engine=form_engine,
        persist=persist, store_name=store_name)), "稳健性报告失败", json_output=True)


# ─── farfield（WP4.1 nf2ff 远场；0bu③） ──────────────────────────────────────

farfield_app = typer.Typer(help="远场方向图/增益/效率/SAR（WP4.1 nf2ff 产物视图）")
app.add_typer(farfield_app, name="farfield")


@farfield_app.command("list")
def farfield_list_cmd(
    limit: int = typer.Option(50, "--limit", "-n", help="返回条数上限"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """含远场/SAR 产物的 run 清单。"""
    from rfauto.service.nf2ff_service import farfield_runs

    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(farfield_runs(limit=limit), "远场 run 清单失败", json_output=True)


@farfield_app.command("view")
def farfield_view_cmd(
    run_id: str = typer.Argument(..., help="含 nf2ff 产物的 run ID"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """单 run 远场视图：φ 切面 θ-dB 序列 + Dmax/效率/HPBW/F/B + SAR（core/farfield 确定性解析）。"""
    from rfauto.service.nf2ff_service import farfield_view

    _emit(farfield_view(run_id), f"远场视图失败 {run_id}", json_output=True)
