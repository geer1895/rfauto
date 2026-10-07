"""lake 子应用（runs 湖六+二命令）+ constraints 子应用 + runs stats/export-tracking/certify/solid-import/port-gate（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from pathlib import Path

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _kv_floats as _kv_floats
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console
from rfauto.cli.domains.surrogate import runs_app as runs_app

# ─── lake（df7 F3 runs 湖索引+分层压实薄壳：index/query/pack/verify/restore） ──
# 五命令零逻辑转发 service/lake_service（规则 4，JSON 进出走 service）；
# 路径参数一律 str 注解（#269 B008）；缺省落点口径单源在 service
# （索引库 runs/.lake_index.duckdb、偏移清单 <pack>.manifest.json），壳层不复制。

lake_app = typer.Typer(
    help="runs/ 湖索引与分层压实（df7 F3：DuckDB 索引 + tar.zst 内容寻址归档）")
app.add_typer(lake_app, name="lake")


@lake_app.command("index")
def lake_index_cmd(
    runs_dir: str = typer.Option("runs", "--runs-dir",
                                 help="runs 根目录（扫一级战役+二级 run 点两层）"),
    db: str | None = typer.Option(None, "--db",
                                  help="索引库路径（缺省 runs/.lake_index.duckdb）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """扫 runs/ 重建 DuckDB 湖索引（幂等重建；缺失字段如实 NULL 不臆造）。"""
    from rfauto.service.lake_service import build_runs_index

    result = build_runs_index(runs_dir, db_path=db)
    _emit(result, "湖索引重建失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ rows={result['n_rows']}[/green]  "
                  f"meta={result['n_meta_rows']}"
                  f"  verdict={result['n_verdict_rows']}  db={result['db_path']}")
    if result.get("note"):
        console.print(f"  [dim]{result['note']}[/dim]")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")


@lake_app.command("query")
def lake_query_cmd(
    template: str | None = typer.Option(None, "--template",
                                        help="模板过滤（meta.model 等值）"),
    adapter: str | None = typer.Option(None, "--adapter",
                                       help="适配器过滤（meta.adapter 等值）"),
    study: str | None = typer.Option(None, "--study",
                                     help="study 过滤（meta.study_name 等值）"),
    campaign: str | None = typer.Option(None, "--campaign",
                                        help="战役目录名过滤"),
    date_from: str | None = typer.Option(None, "--date-from",
                                         help="起始日期 YYYY-MM-DD（created_date 闭区间）"),
    date_to: str | None = typer.Option(None, "--date-to",
                                       help="截止日期 YYYY-MM-DD（created_date 闭区间）"),
    limit: int = typer.Option(200, "--limit", help="返回行数上限"),
    order_by: str | None = typer.Option(None, "--order-by",
                                        help="排序列（SN-14：索引列白名单，如 created_ts、size_bytes）"),
    order: str = typer.Option("desc", "--order", help="排序方向 asc 或 desc（缺省 desc）"),
    db: str | None = typer.Option(None, "--db",
                                  help="索引库路径（缺省 runs/.lake_index.duckdb）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """湖索引只读查询（等值过滤+日期段；JSON 进出走 service，值只进 ? 绑定）。"""
    from rfauto.service.lake_service import query_runs_index

    result = query_runs_index(
        db, template=template, adapter=adapter, study=study,
        campaign=campaign, date_from=date_from, date_to=date_to, limit=limit,
        order_by=order_by, order=order)
    _emit(result, "湖索引查询失败", json_output=json_output)
    if json_output:
        return
    names = ("path", "template", "adapter", "study", "created_date", "n_files")
    console.print("  ".join(names))
    for row in result.get("rows") or []:
        console.print("  ".join(str(row.get(n)) for n in names))
    console.print(f"[dim]{result['n_rows']} 行[/dim]")


@lake_app.command("pack")
def lake_pack_cmd(
    campaign_dir: str = typer.Argument(..., help="战役目录（只读，原目录零改动）"),
    out: str | None = typer.Option(None, "--out",
                                   help="归档落点 tar.zst（缺省 <campaign_dir>.tar.zst）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """战役目录 → tar.zst + 偏移清单（确定性排序+归一化头，内容寻址锚）。"""
    from rfauto.service.lake_service import pack_campaign

    out_path = out if out is not None else str(Path(campaign_dir)) + ".tar.zst"
    result = pack_campaign(campaign_dir, out_path)
    _emit(result, "战役打包失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ files={result['n_files']}[/green]  "
                  f"total={result['total_bytes']}B  pack={result['pack_path']}")
    console.print(f"  sha256={result['pack_sha256']}  "
                  f"manifest={result['manifest_path']}")


@lake_app.command("verify")
def lake_verify_cmd(
    pack: str = typer.Argument(..., help="归档 tar.zst"),
    manifest: str = typer.Argument(..., help="偏移清单 JSON（<pack>.manifest.json）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """归档校验：整包 sha256 快校验 + 逐文件 sha256 重算（如实逐文件报告）。"""
    from rfauto.service.lake_service import verify_campaign

    result = verify_campaign(pack, manifest)
    if json_output:
        _emit(result, "归档校验未通过", json_output=True)
        return
    # 文本面：逐文件 ok 表摘要（失败也要看到逐文件定位），再走信封出口
    console.print(f"pack_sha256_ok={result['pack_sha256_ok']}  "
                  f"ok={result['n_ok']}  fail={result['n_fail']}")
    for f in result.get("files") or []:
        if f["ok"]:
            console.print(f"  [green]ok[/green]  {f['path']}")
        else:
            console.print(f"  [red]FAIL[/red]  {f['path']}  {f.get('reason')}")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")
    if not result.get("ok"):
        raise typer.Exit(code=1)


@lake_app.command("restore")
def lake_restore_cmd(
    pack: str = typer.Argument(..., help="归档 tar.zst"),
    manifest: str = typer.Argument(..., help="偏移清单 JSON"),
    target: str = typer.Argument(..., help="恢复目标目录（必须不存在——绝不覆盖）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """恢复归档到新目录（目标已存在即拒；拒绝覆盖语义由 service 透传）。"""
    from rfauto.service.lake_service import restore_campaign

    result = restore_campaign(pack, manifest, target)
    _emit(result, "归档恢复失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ restored={result['n_verified']}/{result['n_files']}[/green]"
                  f"  bytes={result['total_bytes']}  target={result['target_dir']}")


@lake_app.command("sweep")
def lake_sweep_cmd(
    runs_dir: str = typer.Option("runs", "--runs-dir",
                                 help="runs 根目录（只读清点，零改写零移动）"),
    max_list: int = typer.Option(200, "--max-list", help="incomplete 明细行数上限"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """incomplete/半产物只读清点报告（QW-13；DP-9 的 gc 视角，零改写）。

    分类：complete=有 meta；empty=零文件空壳；incomplete=无 meta 但有
    产物证据（trials//samples.json/sparams.csv/calib.json——在跑或中断，
    meta 结束才落盘 #144）；unannotated=无 meta 无已知产物。
    """
    from rfauto.service.lake_service import sweep_runs

    result = sweep_runs(runs_dir, max_list=max_list)
    _emit(result, "lake sweep 失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ dirs={result['n_dirs']}[/green]  "
                  f"complete={result['n_complete']}  "
                  f"incomplete={result['n_incomplete']}  "
                  f"empty={result['n_empty']}  "
                  f"unannotated={result['n_unannotated']}")
    for row in result.get("incomplete") or []:
        console.print(f"  [yellow]{row['path']}[/yellow]  "
                      f"files={row['n_files']}  markers={row['markers']}")
    for err in result.get("errors") or []:
        console.print(f"  [dim]- {err}[/dim]")


@lake_app.command("export-parquet")
def lake_export_parquet_cmd(
    db: str = typer.Option(None, "--db",
                           help="索引库路径（缺省 runs/.lake_index.duckdb）"),
    out_dir: str = typer.Option(None, "--out-dir",
                                help="parquet 冷层目录（缺省 <db 去后缀>.parquet）"),
    partition_by: str = typer.Option("created_date", "--partition-by",
                                     help="hive 分区列（空串=不分区）"),
    overwrite: bool = typer.Option(False, "--overwrite",
                                   help="目标目录已存在时允许覆盖写入"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """湖索引表→parquet 冷层（P-5 COPY PARTITION_BY 接口；外部引擎直读）。"""
    from rfauto.service.lake_service import export_index_parquet

    result = export_index_parquet(db, out_dir,
                                  partition_by=partition_by or None,
                                  overwrite=overwrite)
    _emit(result, "冷层导出失败", json_output=json_output)
    if json_output:
        return
    console.print(f"[green]✓ rows={result['n_rows']}[/green]  "
                  f"partition_by={result['partition_by']}  "
                  f"out={result['out_dir']}")
    console.print(f"  files: {len(result.get('files') or [])} parquet")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")


# ─── XD-9 audit-stale（湖陈旧审计：Snakemake --list-code-changes 湖级版）────
# 只读零改写（判据 3）；退出码语义：0=无失效 / 1=有失效行 / 2=程序性错误
# （runs 根缺失、config-diff 非法）。--json 走 ok 信封（house style）。

@lake_app.command("audit-stale")
def lake_audit_stale_cmd(
    render_commit: str = typer.Option(
        None, "--render-commit",
        help="当前渲染 commit SHA（缺省=git HEAD；run 的 git_sha 与之不等"
             "即 code 类失效）"),
    engine_version: str = typer.Option(
        None, "--engine-version",
        help="当前引擎版本指纹（与 dag 键成分/meta 记录对照，不等即 engine 类）"),
    config_diff: str = typer.Option(
        None, "--config-diff",
        help="配置变化 JSON 文件（键表/键到新值映射/old-new 三形皆收）"),
    runs_root: str = typer.Option("runs", "--runs-root",
                                  help="runs 根目录（纯读零改写）"),
    max_list: int = typer.Option(200, "--max-list",
                                 help="失效/unknown 明细行数上限"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """扫全湖产出将失效 run 清单与原因分类（code/params/engine/env/budget）。

    示例：rfauto lake audit-stale --runs-root runs --json
    退出码：0 无失效；1 有失效行；2 程序性错误。
    """
    import json

    from rfauto.service.lake_service import audit_stale_runs

    diff_payload = None
    if config_diff:
        diff_payload = _load_json_file(config_diff, "config-diff")
    result = audit_stale_runs(
        runs_root, render_commit=render_commit,
        engine_version=engine_version, config_diff=diff_payload,
        max_detail=max_list)
    if not result.get("ok"):
        if json_output:
            console.print_json(json.dumps(result, indent=2,
                                          ensure_ascii=False, default=str))
        else:
            console.print("[red]✗ audit-stale 失败[/red]")
            for err in result.get("errors") or []:
                console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=2)

    if json_output:
        console.print_json(json.dumps(result, indent=2,
                                      ensure_ascii=False, default=str))
    else:
        sel = result.get("selectors") or {}
        cc = result.get("class_counts") or {}
        console.print(
            f"[green]✓ dirs={result.get('n_dirs')}[/green]  "
            f"checked={result.get('n_checked')}  "
            f"stale={result.get('n_stale')}  "
            f"fresh={result.get('n_fresh')}  "
            f"unknown_meta={result.get('n_unknown_meta')}")
        console.print(
            f"  code={cc.get('code', 0)}  params={cc.get('params', 0)}  "
            f"engine={cc.get('engine', 0)}  env={cc.get('env', 0)}  "
            f"budget={cc.get('budget', 0)}  "
            f"（render_commit 来源 {sel.get('render_commit_source')}）")
        for row in result.get("stale") or []:
            console.print(
                f"  [yellow]{row['path']}[/yellow]  "
                f"{','.join(row.get('classes') or [])}")
            for reason in row.get("reasons") or []:
                console.print(f"      - {reason}")
        for row in result.get("unknown") or []:
            console.print(f"  [dim]unknown {row['path']}[/dim]  "
                          f"{row.get('reason')}")
        for err in result.get("errors") or []:
            console.print(f"  [dim]- {err}[/dim]")

    if int(result.get("n_stale") or 0) > 0:
        raise typer.Exit(code=1)


# ─── XD-1 lake lineage（跨 run 血缘三跳查询：数据集→上游 run→渲染 commit）──
# 零逻辑转发 service/lake_service.query_lineage（规则 4）；依赖湖索引库的
# runs_lake_index+run_lineage 两表（先 rfauto lake index 建索引）；--up/--down
# 布尔对旗标（缺省向上），md 缩进树走服务层渲染；--expand 防边家族爆炸摘要。

@lake_app.command("lineage")
def lake_lineage_cmd(
    run: str = typer.Option(..., "--run",
                            help="起点 run id（湖索引目录名或数据集名）"),
    up: bool = typer.Option(True, "--up/--down",
                            help="方向：向上查祖先血缘（缺省）或向下查影响面"),
    hops: int = typer.Option(3, "--hops",
                             help="展开跳数上限（1-10，缺省 3）"),
    fmt: str = typer.Option("md", "--format",
                            help="输出形态：md 缩进树或 json 信封"),
    db: str | None = typer.Option(None, "--db",
                                  help="湖索引库路径（缺省 runs/.lake_index.duckdb）"),
    expand: bool = typer.Option(False, "--expand",
                                help="展开全部节点明细（缺省 cap 摘要防边家族爆炸）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """跨 run 血缘查询：数据集到上游 run 到渲染 commit 端点，或反向影响面。

    示例：rfauto lake lineage --run 20260901_120000_ab12 --hops 3
    依赖湖索引库含 run_lineage 边表（先 rfauto lake index 重建）。
    """
    import json

    from rfauto.service.lake_service import query_lineage, render_lineage_md

    want_json = json_output or fmt.strip().lower() == "json"
    result = query_lineage(db, run, direction="down" if not up else "up",
                           hops=hops, expand=expand)
    if not result.get("ok"):
        _emit(result, "血缘查询失败", json_output=want_json)
        return
    if want_json:
        console.print_json(json.dumps(result, indent=2,
                                      ensure_ascii=False, default=str))
        return
    typer.echo(render_lineage_md(result))


# ─── RB-WN-1 lake compact（W3-A 湖语义压缩：h5 白名单保留+et/ht 去重）─────
# 零逻辑转发 service/lake_compact_service（规则 4）；**缺省 dry-run 纯读**，
# 真删/真链接必须显式 --apply，且 --apply 有 XD-5 前置互锁（sim_ci golden
# 基线已 pin——simci_baseline.yaml 在档且 schema 合法），未 pin 一律拒绝
# （真实湖面破坏性动作等用户窗，W3-A criteria 预声明）。W6-G 起 apply 缺省
# 走可逆路径（blob 化+manifest 审计，禁裸删；用户豁免子树 --exempt-subtree
# 白名单口径），--no-reversible 保留历史直删路径。

@lake_app.command("compact")
def lake_compact_cmd(
    runs_root: str = typer.Option("runs", "--runs-root",
                                  help="runs 根目录（dry-run 纯读）"),
    policy: str = typer.Option("whitelist", "--policy",
                               help="h5 保留策略（当前仅 whitelist 推导式白名单）"),
    dedup_et_ht: bool = typer.Option(
        False, "--dedup-et-ht/--no-dedup-et-ht",
        help="附带 et/ht 内容寻址去重（blob store+硬链接）"),
    h5_tier: str = typer.Option(
        "medium", "--h5-tier",
        help="h5 删除档位：conservative 或 medium 或 aggressive（三档统计全给）"),
    keep_recent_n: int = typer.Option(
        0, "--keep-recent-n",
        help="每战役豁免最新 N 个候选 run 的 h5（保留策略用户裁材料）"),
    min_age_h: float = typer.Option(
        24.0, "--min-age-h",
        help="meta 落盘距今不足该小时数的 run 一律不动（并发生产防误碰）"),
    exempt_subtree: list[str] = typer.Option(  # noqa: B008
        None, "--exempt-subtree",
        help="用户豁免子树（runs 下相对路径，可多次；仅解除该子树 no_meta "
             "保护，其余子树维持保护不进清单）"),
    reversible: bool = typer.Option(
        True, "--reversible/--no-reversible",
        help="apply 走可逆路径（blob 化+manifest 审计，禁裸删；缺省开）"),
    observation_days: int = typer.Option(
        30, "--observation-days",
        help="可逆 apply 的观察窗天数（窗满 purge 落物理释放）"),
    baseline_path: str | None = typer.Option(
        None, "--baseline-path",
        help="XD-5 golden 基线文件路径（缺省 knowledge/simci_baseline.yaml）"),
    manifest: str | None = typer.Option(
        None, "--manifest", help="删除/去重 manifest 落点（--apply 时必写）"),
    apply: bool = typer.Option(
        False, "--apply", help="真删/真链接（缺省 dry-run；需 XD-5 已 pin）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """湖语义压缩规划与执行：h5 白名单保留+et/ht 去重（缺省 dry-run 纯读）。

    示例：rfauto lake compact --runs-root runs --json（纯读规划三档统计）
    --apply 前置互锁：XD-5 golden 基线未 pin 时拒绝（先 rfauto
    simci-pin-baseline pin 放量）。缺省 --reversible：apply 把删除清单 h5
    blob 化进 runs/.blob_store（内容寻址+manifest 审计，观察窗内可恢复回填，
    禁裸删），窗满 purge 落物理释放；--no-reversible 走历史直删路径。
    """
    import json as _json

    from rfauto.service.lake_compact_service import (
        apply_et_ht_dedup,
        apply_h5_retention,
        apply_h5_retention_reversible,
        plan_et_ht_dedup,
        plan_h5_retention,
    )
    from rfauto.service.sim_ci_service import (
        BASELINE_SCHEMA,
        default_baseline_path,
        load_baseline,
    )

    if policy != "whitelist":
        console.print(f"[red]✗ 未知 policy: {policy}（当前仅 whitelist）[/red]")
        raise typer.Exit(code=2)
    if exempt_subtree and not reversible:
        console.print(
            "[red]✗ --no-reversible 不支持 --exempt-subtree（豁免子树只走"
            "可逆路径：blob 化+manifest 审计，禁裸删）[/red]")
        raise typer.Exit(code=2)

    plan = plan_h5_retention(runs_root, tier=h5_tier,
                             keep_recent_n=keep_recent_n,
                             min_age_h=min_age_h,
                             exempt_subtrees=exempt_subtree)
    dedup_plan = plan_et_ht_dedup(runs_root, min_age_h=min_age_h) \
        if dedup_et_ht else None

    if not apply:
        # dry-run：纯读报告（破坏性放量面清单+预估收益，用户裁 --apply 依据）
        if json_output:
            payload = dict(plan)
            if dedup_plan is not None:
                payload["dedup_plan"] = dedup_plan
            console.print_json(_json.dumps(payload, indent=2,
                                           ensure_ascii=False, default=str))
            return
        keep = plan.get("keep_reasons") or {}
        console.print(
            f"[green]✓ dry-run（零写零删）[/green]  h5={plan.get('n_h5')}  "
            f"total={plan.get('total_bytes')}B  tier={plan.get('tier')}")
        console.print(
            f"  保留理由: {keep}  n_protected_dirs="
            f"{plan.get('n_protected_dirs')}")
        for t_name, t_stat in (plan.get("tiers") or {}).items():
            console.print(
                f"  档位 {t_name}: 删 {t_stat['n_delete']} 个 h5 / "
                f"{t_stat['bytes_delete']}B")
        console.print(
            f"  当前档可删 {plan.get('n_delete')} 个 / "
            f"{plan.get('bytes_delete')}B  （--apply 需 XD-5 已 pin）")
        if dedup_plan is not None:
            console.print(
                f"  et/ht 去重: files={dedup_plan.get('n_files')}  "
                f"重复面={dedup_plan.get('n_dup_files')} 个 / "
                f"{dedup_plan.get('bytes_dup_total')}B  "
                f"protected={dedup_plan.get('n_protected')}")
        audit = plan.get("golden_rewrite_audit") or {}
        if audit.get("violations"):
            console.print("[red]  golden 零改写断言违反:[/red]")
            for v in audit["violations"][:10]:
                console.print(f"    - {v}")
        return

    # ── apply 路径：XD-5 前置互锁（golden 基线已 pin 才放行真删） ──
    baseline_file = Path(baseline_path) if baseline_path \
        else default_baseline_path()
    golden = load_baseline(baseline_file)
    if golden is None:
        console.print(
            "[red]✗ --apply 拒绝：XD-5 golden 基线未 pin "
            f"（{baseline_file} 缺失或 schema 非 {BASELINE_SCHEMA}）——"
            "先 rfauto simci-pin-baseline pin 再放量[/red]")
        raise typer.Exit(code=2)
    if plan.get("golden_rewrite_audit", {}).get("violations"):
        _emit(plan, "golden 零改写断言失败（零删拒绝）", json_output=json_output)
        raise typer.Exit(code=2)
    m_path = manifest or str(Path(runs_root) / ".compact_manifest"
                             / "h5_compact_manifest.json")
    if reversible:
        result = apply_h5_retention_reversible(
            plan, manifest_path=m_path, runs_root=runs_root,
            observation_days=observation_days)
    else:
        result = apply_h5_retention(plan, manifest_path=m_path,
                                    runs_root=runs_root)
    if dedup_et_ht:
        result["dedup"] = apply_et_ht_dedup(
            runs_root, min_age_h=min_age_h,
            manifest_path=None if manifest is None
            else str(Path(m_path).with_name("etht_dedup_manifest.json")))
    _emit(result, "lake compact apply 失败", json_output=json_output)
    if json_output:
        return
    console.print(
        f"[green]✓ deleted={result.get('n_deleted')}[/green]  "
        f"freed={result.get('bytes_freed')}B  manifest={result.get('manifest_path')}")
    if result.get("n_moved") is not None:
        console.print(
            f"  可逆路径: moved={result.get('n_moved')}  "
            f"dedup={result.get('n_dedup_existing')}  "
            f"retained={result.get('bytes_retained')}B  "
            f"blob_store={result.get('blob_store')}  "
            f"purge_after={result.get('purge_after')}")
    dedup = result.get("dedup")
    if dedup:
        console.print(
            f"  et/ht 去重: linked={dedup.get('n_linked')}  "
            f"saved={dedup.get('bytes_saved')}B  manifest="
            f"{dedup.get('manifest_path')}")
    for err in result.get("errors") or []:
        console.print(f"  [yellow]- {err}[/yellow]")


# ─── constraints（df7+ R4：渲染前声明式几何约束一次求解薄壳） ─────────────────
# 零逻辑转发 service/render_constraint_service（规则 4）；配置文件解析在
# service 层（#90）；路径参数 str 注解（#269 B008）；z3 缺装降级在 core
# 内完成（ok=False/status="unavailable" 如实进 verdict，不阻塞）。

constraints_app = typer.Typer(
    help="渲染前声明式几何约束检查（R4：z3 一次求解，UNSAT 冲突组+witness）")
app.add_typer(constraints_app, name="constraints")


@constraints_app.command("check")
def constraints_check_cmd(
    config_path: str = typer.Argument(
        ..., help="约束配置文件（JSON/YAML；键见 service.evaluate_render_constraints）"),
    pretty: bool = typer.Option(False, "--pretty",
                                help="缩进美化输出（缺省单行紧凑 JSON）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 直出，旗标为归一兼容位）"),
) -> None:
    """渲染前一次求解：约束配置 → verdict+冲突规则（JSON 进出薄壳）。

    示例：rfauto constraints check config.json --pretty
    config 键（全部可选）：mesh_resolution_mm / near_ratio / gaps_mm /
    min_gap_mm / gap_cells_min / min_line_spacing_mm / mesh_lines_mm /
    param_bounds / max_conflict_groups。
    """
    import json as _json

    from rfauto.service.render_constraint_service import (
        evaluate_render_constraints_from_file,
    )

    try:
        verdict = evaluate_render_constraints_from_file(config_path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=1) from exc
    # verdict.ok=False（UNSAT/z3 缺装）是检查本身的正常产出——退出码 0，
    # 判定交给消费方读 JSON；程序性错误（文件/形状）才走非零退出。
    typer.echo(_json.dumps(verdict, ensure_ascii=False,
                           indent=2 if pretty else None))


# ─── ME-17a 接线批第一组（纯薄壳×5） ────────────────────────────────────────
# runs stats / runs export-tracking / certify / solid-import / port-gate：
# 零逻辑转发既有 service 面（规则 4）；路径参数 str 注解（#269 B008）；
# 出口统一 _emit ok 契约。solid_import/certify_design/port_gate 同批接 MCP
# 工具面（mcp_server.py 第 36 节）；tracking_export 的 service 单次产出
# MLflow 目录 + W&B JSONL，故单命令 export-tracking 不按目标拆分；
# port_gate 真机发射走对象面（HfssPortDriver 注入），JSON 面只到合成回放。


@runs_app.command("stats")
def runs_stats_cmd(
    db_path: str | None = typer.Option(None, "--db",
                                       help="runs 索引库路径（缺省注册表缺省库）"),
    since: str | None = typer.Option(None, "--since",
                                     help="只统计 timestamp >= since（字符串比较口径）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """runs 总览统计：总数、按 model/adapter/status 分组计数、最近 10 条。"""
    from rfauto.service.runs_stats import runs_summary

    # VI-5 W2-C：ME-17a 起 _emit 缺省 json_output=True——本命令缺省即信封直出；
    # 归一旗标接受但两形态同输出（缺省路径逐字节不变铁纪律优先于纯切换形态）。
    _emit(runs_summary(db_path, since=since), "runs 统计失败", json_output=True)


@runs_app.command("export-tracking")
def runs_export_tracking_cmd(
    run_id: str = typer.Argument(..., help="run_id（runs_root 下的目录名）"),
    runs_root: str = typer.Option("runs", "--runs-root", help="runs 根目录"),
    out_dir: str | None = typer.Option(None, "--out-dir",
                                       help="导出落点（缺省 runs/tracking）"),
    experiment_name: str | None = typer.Option(
        None, "--experiment", help="MLflow 实验名（缺省按 meta 推导）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """run trials 单向导出为 MLflow 目录 + W&B JSONL（G10；校验先于写入）。"""
    from rfauto.service.tracking_export import export_run_tracking_safe

    # VI-5 W2-C：同 runs stats——缺省即信封直出，旗标归一兼容位（两形态同输出）。
    _emit(export_run_tracking_safe(
        run_id, runs_root=runs_root, out_dir=out_dir,
        experiment_name=experiment_name), "追踪导出失败", json_output=True)


@app.command("certify")
def certify_cmd(
    samples_path: str = typer.Argument(
        ..., help="公差盒样本集 JSON（bounds/objectives/samples 同款 schema）"),
    param: list[str] = typer.Option(None, "--param", help="中心参数 名=值（可多次；每轴必给）"),  # noqa: B008
    tolerance_pct: float = typer.Option(
        0.02, "--tolerance-pct", help="每参数 ±公差（相对该轴 span 百分比）"),
    n_grid: int = typer.Option(9, "--n-grid",
                               help="Lipschitz 有限差分每轴网格数"),
    kind: str = typer.Option("poly_ridge", "--kind", help="代理模型类型"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """公差盒 → 指标区间证书（三值门面：逐目标 PASS/FAIL/UNKNOWN + 总 verdict）。"""
    from rfauto.service.certify_design import certify_design

    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(certify_design(samples_path, _kv_floats(param, "--param"),
                         tolerance_pct=tolerance_pct, n_grid=n_grid, kind=kind),
          "证书生成失败", json_output=True)


@app.command("solid-import")
def solid_import_cmd(
    path: str = typer.Argument(..., help="STL 文件路径（STEP 属显式缺口，如实拒绝）"),
    material: str = typer.Option("metal", "--material", help="分类材料标签"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """STL 实体导入：解析+分类+CSX 载荷（B3；一切失败 ok=False 不抛出）。"""
    from rfauto.service.solid_import_service import import_solid_payload

    _emit(import_solid_payload(path, material=material), "实体导入失败", json_output=True)


@app.command("port-gate")
def port_gate_cmd(
    payload_path: str = typer.Argument(
        ..., help="payload JSON 文件（键见 port_gate_service.port_gate_from_json）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """端口尺寸收敛前置门（合成回放 JSON 面；防 #191/#254 浪费求解席位）。"""
    from rfauto.service.port_gate_service import port_gate_from_json

    payload = _load_json_file(payload_path, "payload")
    try:
        result = port_gate_from_json(payload)
    except (KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"payload 非法: {exc}"]}
    _emit(result, "端口门检查失败", json_output=True)
