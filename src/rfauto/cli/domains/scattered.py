"""WP3.3 散装薄壳：electrothermal/parasitic/topology/vna-replay/report-narrative + rationale/rag/self-heal/logs/materials 子应用（AU-1 自 cli/main.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import json

import typer

from rfauto.cli.domains._core import _emit as _emit
from rfauto.cli.domains._core import _kv_floats as _kv_floats
from rfauto.cli.domains._core import _load_json_file as _load_json_file
from rfauto.cli.domains._core import app as app
from rfauto.cli.domains._core import console as console

# ─── electrothermal / parasitic（WP4.4a/4.4b 链路；0br④/0bv③） ───────────────

@app.command("electrothermal")
def electrothermal_cmd(
    payload: str = typer.Argument(..., help="电-热链输入 JSON（case/thermal/material/resonator/band）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """Wilkinson 隔离电阻损耗 → 温升 → 材料温漂 → S 参数失谐（+带内判据），纯闭式。"""
    from rfauto.service.electrothermal_service import run_wilkinson_electrothermal

    # VI-5 W6-B：缺省即 _emit 信封直出，旗标为归一兼容位（两形态同输出）。
    _emit(run_wilkinson_electrothermal(_load_json_file(payload, "payload")),
          "电-热链失败", json_output=True)


@app.command("parasitic")
def parasitic_cmd(
    payload: str = typer.Argument(..., help="寄生提取链输入 JSON（pcb/substrate/...）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """PCB 互连 RLC 提取链：pcell 几何 → RF-DRC 门 → 闭式锚 →（Q3D 注入对比 ≤5％ 门）。"""
    from rfauto.service.parasitic_service import extract_interconnect_rlc

    result = extract_interconnect_rlc(_load_json_file(payload, "payload"))
    if not result.get("ok") and result.get("stage") == "drc":
        console.print("[red]✗ RF-DRC 门不过（不进提取）[/red]")
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        raise typer.Exit(code=1)
    _emit(result, "寄生提取失败", json_output=True)


# ─── tolerance-allocate（M-7 公差分配；W1-A 孤儿接线单元9）───────────────────
# 顶层单命令不立子应用——防与既有顶层 tolerance（MC 良率）同名遮蔽
# （#df6①；#157 家族同名遮蔽判例）。数值全部出自确定性内核
# core/tolerance_allocation（拉格朗日闭式/二分+对照法+Cpk），本叶零计算。


@app.command("tolerance-allocate")
def tolerance_allocate_cmd(
    payload: str = typer.Option(..., "--payload",
                                help="公差分配输入 JSON 文件路径（sensitivities 与 cost_coeffs 必填，mode 三选一）"),
    json_output: bool = typer.Option(False, "--json", "-j",
                                     help="JSON 信封输出（供门禁/脚本消费）"),
) -> None:
    """cost-aware 公差分配（敏感度×成本系数 → 逐参数公差建议 + 对照法 + Cpk）。

    mode 三选一：cost_budget 预算 C 或 budget_t 公差和 T 或 min_cost RSS
    上限 R；compare=true 附 greedy 与 proportional 两对照法；spec 段可选
    出 Cpk 重算。优化不可行 → ok=False 信封（不抛）。
    """
    from rfauto.service.tolerance_allocation_service import tolerance_allocate

    result = tolerance_allocate(_load_json_file(payload, "payload"))
    _emit(result, "公差分配失败", json_output=json_output)
    if json_output:
        return
    allocation = result.get("allocation") or {}
    console.print(f"[green]✓ 公差分配完成[/green]  mode={result.get('mode')}"
                  f"  参数 {len(allocation)} 个  schema v{result.get('schema_version')}")
    for name, row in allocation.items():
        console.print(f"  {name}: {row}", markup=False)
    if result.get("comparison"):
        console.print("  对照法 comparison 段随 --json 输出（greedy 与 proportional）")


# ─── topology（WP4.6 生成式综合 E10；0by③） ──────────────────────────────────

@app.command("topology")
def topology_cmd(
    f0: float = typer.Option(..., "--f0", help="中心频率 GHz"),
    fbw: float = typer.Option(..., "--fbw", help="相对带宽 (0,1]"),
    rl: float = typer.Option(20.0, "--rl", help="带内回损目标 dB"),
    stop_rejection: float = typer.Option(None, "--stop-rejection", help="阻带抑制要求 dB（选阶用）"),
    stop_fbw_mult: float = typer.Option(2.0, "--stop-fbw-mult", help="阻带边 = f0·(1±mult·fbw/2)"),
    order: int = typer.Option(None, "--order", "-n", help="显式阶数（否则规则选阶/默认 3）"),
    family: str = typer.Option(None, "--family", help="家族提示（coupled_bpf/hairpin）"),
    proposer: str = typer.Option("rule_based", "--proposer", help="提议器注册名"),
    campaign: bool = typer.Option(False, "--campaign", help="跑小战役精算（电路裁判，离线秒级）"),
    n_trials: int = typer.Option(80, "--n-trials", help="战役 TPE 试验数"),
    seed: int = typer.Option(20260914, "--seed", help="战役随机种子"),
    sandbox_name: str = typer.Option(None, "--sandbox-name", help="落沙箱草稿名（不 promote）"),
    promote: bool = typer.Option(False, "--promote", help="草稿走 L1/L2/L3 准入链迁 promoted/（需 --sandbox-name）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """滤波器拓扑提议（typed，禁数值字段）→ 综合初值 →（--campaign）小战役精算。"""
    from rfauto.service.topology_service import propose_topology

    spec: dict = {"f0_ghz": f0, "fbw": fbw, "rl_db": rl, "stop_fbw_mult": stop_fbw_mult}
    if stop_rejection is not None:
        spec["stop_rejection_db"] = stop_rejection
    if order is not None:
        spec["order_hint"] = order
    if family is not None:
        spec["family_hint"] = family
    _emit(propose_topology(spec, proposer=proposer, campaign=campaign,
                           n_trials=n_trials, seed=seed, sandbox_name=sandbox_name,
                           promote=promote),
          "拓扑提议失败", json_output=True)


# ─── vna-replay（补强17 VNA 软侧离线回放；0bx② 透传） ─────────────────────────

@app.command("vna-replay")
def vna_replay_cmd(
    measured: str = typer.Argument(..., help="历史测量 Touchstone（供 MockVNAInstrument）"),
    sim: str = typer.Option(None, "--sim", help="仿真 Touchstone（缺省=同文件自比对）"),
    threshold_db: float = typer.Option(3.0, "--threshold", "-t", help="相关性 dB 偏差门"),
    session: str = typer.Option(None, "--session", help="会话 JSONL 落盘路径"),
    json_output: bool = typer.Option(False, "--json",
                                     help="JSON 信封输出（成功+失败同构）"),
) -> None:
    """mock 仪表采集→校准→相关全链回放（零硬件；硬件阻塞下的回归入口）。

    与 ``vna replay`` 子命令互为别名（同一 service 链路）；退出码同口径：
    调用失败或相关性判读未过门（is_correlated=False）均 exit 1（E2-3 统一）。
    """
    from rfauto.service.api import vna_offline_replay

    result = vna_offline_replay(measured, sim, threshold_db=threshold_db,
                                session_path=session)
    if json_output:
        # VI-5 W6-B：失败信封（成功本即 JSON 直出，两形态同形）；未过门 exit 1 保持
        _emit(result, "离线回放失败", json_output=True)
        corr = result.get("correlation") or {}
        if corr and not corr.get("is_correlated", True):
            raise typer.Exit(code=1)
        return
    if not result.get("ok"):
        console.print("[red]✗ 离线回放失败[/red]")
        for err in result.get("errors") or ([result["error"]] if result.get("error") else []):
            console.print(f"  [red]- {err}[/red]")
        raise typer.Exit(code=1)
    console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    corr = result.get("correlation") or {}
    if corr and not corr.get("is_correlated", True):
        raise typer.Exit(code=1)


# ─── report-narrative（F9 报告叙述位；0bj） ───────────────────────────────────

@app.command("report-narrative")
def report_narrative_cmd(
    run_id: str = typer.Argument(..., help="已完成 run（runs/<run_id>/meta.json 须存在）"),
    text: str = typer.Option(None, "--text", help="外来叙述文本：审计其数字（缺省=生成模板叙述）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """F9 叙述位：run 白名单 → 确定性模板叙述，或审计外来叙述（未授权数字定位；不调 LLM）。"""
    from rfauto.service.report_narrative import report_narrative_for_run

    result = report_narrative_for_run(run_id, narrative=text)
    if result.get("errors"):
        _emit(result, "叙述生成失败")
    if json_output:
        console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(result.get("narrative", ""))
        for v in result.get("violations") or []:
            console.print(f"  [red]! 未授权数字 {v.get('text')} @{v.get('start')}: {v.get('reason')}[/red]")
    raise typer.Exit(code=0 if result.get("ok") else 1)


# ─── rationale（F11 经验记忆 / F2 理由检索；0z） ──────────────────────────────

rationale_app = typer.Typer(help="设计理由/经验记忆（F11 typed 经验检索 + F2 runs 理由语料 TF-IDF）")
app.add_typer(rationale_app, name="rationale")


@rationale_app.command("recall")
def rationale_recall_cmd(
    task: str = typer.Argument(..., help="任务描述（模板名/场景关键词）"),
    memory: str = typer.Option(None, "--memory", "-m", help="外部经验记忆 JSON（save_entries 产物）"),
    top_k: int = typer.Option(5, "--top-k", help="命中数上限"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """任务描述 → 命中历史坑/核对表/动作（确定性关键词匹配，无 embedding/网络）。"""
    from rfauto.service.rationale_memory import recall_with_memory

    result = recall_with_memory(task, memory_path=memory, top_k=top_k)
    _emit(result, "经验检索失败", json_output=json_output)
    if json_output:
        return
    if not result["hits"]:
        console.print("[green]无命中历史经验[/green]")
        return
    gate = "[red]先离线审计[/red]" if result["require_offline_audit"] else "[dim]无门禁[/dim]"
    console.print(f"[bold]命中 {len(result['hits'])} 条[/bold]（{result['n_entries']} 池）  {gate}")
    for h in result["hits"]:
        console.print(f"  [cyan]{h['lesson_id']}[/cyan] {h['checklist']} ← {', '.join(h['matched'])}")
        console.print(f"    结论：{h['conclusion']}")
        console.print(f"    动作：{h['action']}")


@rationale_app.command("checklist")
def rationale_checklist_cmd(
    template: str = typer.Argument(..., help="模板名（如 patch、cyl_grid）"),
    extras: str = typer.Option(None, "--extras", help="场景补充关键词"),
    memory: str = typer.Option(None, "--memory", "-m", help="外部经验记忆 JSON"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """冒烟前核对表门禁：模板名 → 核对表 + gate（命中即要求先离线审计），可嵌入任务书。"""
    from rfauto.service.rationale_memory import checklist_with_memory

    result = checklist_with_memory(template, extras=extras, memory_path=memory)
    _emit(result, "核对表生成失败", json_output=json_output)
    if json_output:
        return
    if result.get("gate"):
        console.print(f"[red]{result['gate']}[/red]")
    console.print(result.get("markdown") or "[green]无命中历史经验，无门禁[/green]")


@rationale_app.command("search")
def rationale_search_cmd(
    query: str = typer.Argument(..., help="查询文本"),
    runs_dir: str = typer.Option("runs", "--runs-dir", help="理由语料根目录"),
    top_k: int = typer.Option(5, "--top-k", help="返回条数"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """runs/ 产物理由语料 TF-IDF 余弦检索（为什么这么做：autotune issues/fixes/meta）。"""
    from rfauto.service.rationale_memory import search_runs_rationale

    _emit(search_runs_rationale(query, runs_dir=runs_dir, top_k=top_k),
          "理由检索失败", json_output=True)


# ─── rag (F2⑥ RAG 知识库检索，只读薄壳) ──────────────────────────────────────

rag_app = typer.Typer(help="RAG 知识库词法检索（BM25，只读、citation 可溯）")
app.add_typer(rag_app, name="rag")


def _rag_scope_dirs(docs: str, runs: str, scope: str) -> tuple[str | None, str | None]:
    """--scope → (docs_dir, runs_dir)；None=跳过该来源（壳层参数装配）。"""
    if scope == "docs":
        return docs, None
    if scope == "runs":
        return None, runs
    if scope == "all":
        return docs, runs
    raise typer.BadParameter(f"--scope 仅支持 docs|runs|all，收到: {scope}")


@rag_app.command("index")
def rag_index_cmd(
    docs: str = typer.Option("docs", "--docs", help="文档目录"),
    runs: str = typer.Option("runs", "--runs", help="runs 历史目录"),
    scope: str = typer.Option("all", "--scope", help="索引范围: docs|runs|all"),
    runs_limit: int = typer.Option(None, "--runs-limit", help="最多索引 N 个 run 目录"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """构建 RAG 索引并输出统计快照（JSON 直出，零写副作用）。"""
    from rfauto.service.rag_service import index_corpus

    docs_dir, runs_dir = _rag_scope_dirs(docs, runs, scope)
    _emit(index_corpus(docs_dir=docs_dir, runs_dir=runs_dir,
                       base_dir=".", runs_limit=runs_limit),
          "RAG 索引构建失败", json_output=True)


@rag_app.command("query")
def rag_query_cmd(
    text: str = typer.Argument(..., help="查询文本（词法 BM25，中英文皆可）"),
    top_k: int = typer.Option(5, "--top-k", min=1, help="返回命中数上限"),
    docs: str = typer.Option("docs", "--docs", help="文档目录"),
    runs: str = typer.Option("runs", "--runs", help="runs 历史目录"),
    scope: str = typer.Option("all", "--scope", help="检索范围: docs|runs|all"),
    runs_limit: int = typer.Option(None, "--runs-limit", help="最多索引 N 个 run 目录"),
    mode: str = typer.Option("lexical", "--mode",
                             help="检索模式: lexical（BM25 词法）|semantic（确定性 hashing/TF-IDF 降级语义档）|hybrid（BM25×语义混合）"),
    alpha: float = typer.Option(0.5, "--alpha", min=0.0, max=1.0,
                                help="hybrid 模式融合系数（0=纯词法排序，1=纯稠密排序）"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """RAG 检索（JSON 直出：hits + citation + snippet，只读）。

    --mode 三选一（D-08 薄壳）：lexical 缺省词法 BM25、semantic 确定性
    语义档（离线零网络，非真 embedding）、hybrid 混合排序（--alpha 融合）。
    """
    docs_dir, runs_dir = _rag_scope_dirs(docs, runs, scope)
    if mode == "lexical":
        from rfauto.service.rag_service import query_corpus

        _emit(query_corpus(text, top_k=top_k, docs_dir=docs_dir,
                           runs_dir=runs_dir, base_dir=".",
                           runs_limit=runs_limit), "RAG 检索失败")
    elif mode == "semantic":
        from rfauto.service.rag_service import semantic_query_corpus

        _emit(semantic_query_corpus(text, top_k=top_k, docs_dir=docs_dir,
                                    runs_dir=runs_dir, base_dir=".",
                                    runs_limit=runs_limit), "RAG 检索失败")
    elif mode == "hybrid":
        from rfauto.service.rag_service import hybrid_query_corpus

        _emit(hybrid_query_corpus(text, top_k=top_k, alpha=alpha,
                                  docs_dir=docs_dir, runs_dir=runs_dir,
                                  base_dir=".", runs_limit=runs_limit),
              "RAG 检索失败")
    else:
        raise typer.BadParameter(
            f"--mode 仅支持 lexical|semantic|hybrid，收到: {mode}")


@rag_app.command("explain")
def rag_explain_cmd(
    text: str = typer.Argument(..., help="查询文本"),
    top_k: int = typer.Option(5, "--top-k", min=1, help="返回命中数上限"),
    docs: str = typer.Option("docs", "--docs", help="文档目录"),
    runs: str = typer.Option("runs", "--runs", help="runs 历史目录"),
    scope: str = typer.Option("all", "--scope", help="检索范围: docs|runs|all"),
    runs_limit: int = typer.Option(None, "--runs-limit", help="最多索引 N 个 run 目录"),
    json_output: bool = typer.Option(
        False, "--json",
        help="JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"),
) -> None:
    """RAG 检索 + 逐词 BM25 分数明细（tf/df/idf/contribution，打分可溯）。"""
    from rfauto.service.rag_service import explain_corpus

    docs_dir, runs_dir = _rag_scope_dirs(docs, runs, scope)
    _emit(explain_corpus(text, top_k=top_k, docs_dir=docs_dir, runs_dir=runs_dir,
                         base_dir=".", runs_limit=runs_limit),
          "RAG 检索失败", json_output=True)


# ─── self-heal（WP3.5 F5 自愈环只读诊断；审查 D 分片 M1 装车） ────────────────

self_heal_app = typer.Typer(help="自愈环只读诊断（F5：日志面→确定性 critique→根因/建议）")
app.add_typer(self_heal_app, name="self-heal")


@self_heal_app.command("run")
def self_heal_run_cmd(
    run_id: str = typer.Argument(..., help="已落盘 run（runs/<run_id>/meta.json 须存在）"),
    retries: int = typer.Option(0, "--retries", help="自愈环重试次数（只读模式 attempt 确定性重读）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """对既有 run 跑一次只读自愈环（零真机；只诊断+建议，不自动改配方）。"""
    from rfauto.service.self_heal_service import self_heal_run_for_run

    result = self_heal_run_for_run(run_id, retries=retries)
    _emit(result, f"自愈环诊断失败（{run_id}）", json_output=json_output)
    if json_output:
        return
    color = {"clean": "green", "diagnosed": "red", "unknown_failure": "yellow"}.get(
        str(result.get("verdict")), "yellow")
    console.print(f"[{color}]verdict={result.get('verdict')}[/{color}]  "
                  f"root_cause_id={result.get('root_cause_id')}  "
                  f"lesson_ref={result.get('lesson_ref')}  attempts={result.get('attempts')}")
    for action in result.get("actions") or []:
        console.print(f"  - {action}")
    console.print(f"[dim]{result.get('note')}[/dim]")


# ─── logs（WP3.6 LogDistiller 消费端装车；审查 D 分片 M5） ────────────────────

logs_app = typer.Typer(help="日志语义蒸馏（LogDistiller：stdout/审计 JSON→结构化 digest）")
app.add_typer(logs_app, name="logs")


@logs_app.command("digest")
def logs_digest_cmd(
    path: str = typer.Argument(..., help="日志文件 / 审计 JSON / run 目录"),
    source: str = typer.Option("auto", "--source", help="数据源: auto|openems|hfss|audit_json|generic"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """日志 → 结构化 digest（rc/errors/warnings/指标/失败签名；只读不落文件）。"""
    from rfauto.service.self_heal_service import log_digest_for_path

    result = log_digest_for_path(path, source=source)
    _emit(result, f"日志蒸馏失败（{path}）", json_output=json_output)
    if json_output:
        return
    digest = result.get("digest") or {}
    console.print(
        f"source={digest.get('source')}  rc={digest.get('rc')}  "
        f"n_lines={digest.get('n_lines')}  "
        f"errors={len(digest.get('errors') or [])}  "
        f"warnings={len(digest.get('warnings') or [])}  "
        f"signatures={digest.get('signatures') or []}")
    for key, val in (digest.get("metrics") or {}).items():
        console.print(f"  metric {key} = {val}")


# ─── materials（D1 色散材料库装车；审查 C 分片 D1 最小安全口径） ──────────────

materials_app = typer.Typer(help="材料库工具（D1 色散适应性报告；只读）")
app.add_typer(materials_app, name="materials")


@materials_app.command("dispersion-report")
def materials_dispersion_report_cmd(
    material: str = typer.Argument(..., help="materials.yaml 材料键（须含 dispersion 条目）"),
    f_low_ghz: float = typer.Argument(None, help="频带下沿 GHz（缺省用 D-S 拟合频带）"),
    f_high_ghz: float = typer.Argument(None, help="频带上沿 GHz（缺省用 D-S 拟合频带）"),
    max_eps_r_drift: float = typer.Option(0.02, "--max-drift", help="常数 εr 近似门（相对漂移）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON 输出"),
) -> None:
    """材料在频带内的色散适应性报告（εr/tanδ 漂移 + 常数近似判定 + 修正建议）。"""
    from rfauto.service.dispersion_service import dispersion_fitness_report

    band = None if (f_low_ghz is None and f_high_ghz is None) else [f_low_ghz, f_high_ghz]
    result = dispersion_fitness_report(
        material, band, max_eps_r_drift=max_eps_r_drift)
    _emit(result, f"色散报告失败（{material}）", json_output=json_output)
    if json_output:
        return
    gate = result.get("gate") or {}
    color = "green" if gate.get("passed") else "red"
    console.print(
        f"[{color}]{gate.get('verdict')}[/{color}]  "
        f"εr 漂移 {result.get('eps_r_drift_pct', 0):.3f}%  "
        f"tanδ 漂移 {result.get('tan_delta_drift_pct', 0):.3f}%  "
        f"（带 {result.get('band_ghz')} GHz，测量点 {result.get('f_meas_ghz')} GHz）")
    console.print(f"  {gate.get('message')}")
    if result.get("correction"):
        console.print("  [yellow]建议：模板改用 Djordjevic-Sarkar/多极 Debye 色散渲染"
                      "（correction 段含 openEMS AddDjordjevicSarkarMaterial 参数，--json 查看）[/yellow]")


# ─── pcell（LC-2 pcell_dsl 孤儿复活：消费接线 + 渲染桥直产 Layout）───────────
# 薄壳域内惰性 import core/pcell_dsl 直连（PT-1/2/3 同款口径）；数值只在
# 确定性内核（铁律 7）：本子应用零逻辑，求值/旋转/内核全部出自 pcell_dsl。


def _pcell_geometry_to_layout(geo, name: str | None = None):
    """渲染桥（LC-2）：PCellGeometry → layout_interchange.Layout（求值产物直产）。

    盒→xy 外接多边形、路径→LayoutPath、多边形→LayoutPolygon、过孔→
    LayoutVia；层号 assign_gds_layers 确定性分配；坐标域=毫米（LC-2 新
    单元口径）零换算直出——迁移的 3 个米制模板（mline/cpw/wstep）须由
    调用方自行换算单位后求值，本桥不做隐式单位改写。
    """
    from rfauto.adapters.layout_interchange import (
        Layout,
        LayoutPath,
        LayoutPolygon,
        LayoutVia,
        assign_gds_layers,
    )

    items: list = []
    for b in geo.boxes:
        (x0, y0, _), (x1, y1, _) = b.lo, b.hi
        items.append(LayoutPolygon(
            points=((x0, y0), (x1, y0), (x1, y1), (x0, y1)), layer=b.layer))
    for p in geo.paths:
        items.append(LayoutPath(
            points=tuple(p.points), width_mm=p.width, layer=p.layer))
    for p in geo.polygons:
        items.append(LayoutPolygon(points=tuple(p.points), layer=p.layer))
    for v in geo.vias:
        items.append(LayoutVia(
            position=v.position, pad_diameter_mm=v.pad_diameter,
            drill_diameter_mm=v.drill_diameter, pad_layer=v.pad_layer))
    layer_names: list[str] = []
    for it in items:
        lname = it.pad_layer if isinstance(it, LayoutVia) else it.layer
        if lname not in layer_names:
            layer_names.append(lname)
    return Layout(
        name=name or geo.pcell,
        layers=assign_gds_layers(layer_names),
        items=tuple(items),
        annotations={"source": "pcell_dsl", "pcell": geo.pcell,
                     "params_json": json.dumps(geo.params, sort_keys=True)},
    )


pcell_app = typer.Typer(help="PCell 参数化单元 DSL（LC-2 复活：库清单/定义/"
                            "求值/渲染 Layout 出口）")
app.add_typer(pcell_app, name="pcell")


def _pcell_eval_or_exit(name: str, param: list[str] | None,
                        context: list[str] | None):
    """求值薄壳共用体：未知单元/参数错 → 红字+退出码 2（不抛裸 traceback）。"""
    from rfauto.core.pcell_dsl import evaluate_pcell, get_pcell

    try:
        return evaluate_pcell(
            get_pcell(name), _kv_floats(param, "--param"),
            _kv_floats(context, "--context"))
    except (KeyError, ValueError) as exc:
        console.print(f"[red]✗ PCell 求值失败: {exc}[/red]")
        raise typer.Exit(code=2) from None


@pcell_app.command("list")
def pcell_list_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """列出 PCell 库：单元名/参数边界/原语构成（3 迁移模板 + LC-2 新单元）。"""
    from rfauto.core.pcell_dsl import PCELL_LIBRARY

    cells = []
    for cell_name in sorted(PCELL_LIBRARY):
        d = PCELL_LIBRARY[cell_name]
        n_prims = (len(d.boxes) + len(d.paths) + len(d.polygons)
                   + len(d.vias) + (1 if d.kernel is not None else 0))
        cells.append({
            "name": cell_name,
            "description": d.description,
            "kernel": d.kernel,
            "n_primitives": n_prims,
            "params": {p.name: {"default": p.default, "lo": p.lo, "hi": p.hi}
                       for p in d.params},
        })
    if json_output:
        console.print_json(json.dumps(
            {"ok": True, "data": {"n_cells": len(cells), "cells": cells}},
            ensure_ascii=False))
        return
    console.print(f"PCell 库共 {len(cells)} 个单元：")
    for c in cells:
        params = ", ".join(
            f"{k}={v['default']}" for k, v in c["params"].items())
        kernel = "" if c["kernel"] is None else f" kernel={c['kernel']}"
        console.print(
            f"  {c['name']}  [{c['n_primitives']} 原语]{kernel}  {params}")


@pcell_app.command("show")
def pcell_show_cmd(
    name: str = typer.Argument(..., help="PCell 名（rfauto pcell list 查看）"),
    json_output: bool = typer.Option(False, "--json", "-j", help="输出 dict 而非 YAML"),
) -> None:
    """显示 PCell 定义（DSL 文本面：参数/派生量/原语声明/内核名）。"""
    from rfauto.core.pcell_dsl import def_to_dict, def_to_yaml, get_pcell

    try:
        defn = get_pcell(name)
    except KeyError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(code=2) from None
    if json_output:
        console.print_json(json.dumps(
            {"ok": True, "data": {"definition": def_to_dict(defn)}},
            ensure_ascii=False))
        return
    console.print(def_to_yaml(defn))


@pcell_app.command("eval")
def pcell_eval_cmd(
    name: str = typer.Argument(..., help="PCell 名"),
    param: list[str] = typer.Option(None, "--param", "-p", help="参数名=值（可多次）"),  # noqa: B008
    context: list[str] = typer.Option(None, "--context", "-c", help="上下文常量名=值（可多次，如 H_SUB=5.08e-4）"),  # noqa: B008
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """求值 PCell：参数点 → 原语几何（JSON 进出；数值全出确定性内核）。"""
    geo = _pcell_eval_or_exit(name, param, context)
    payload = {"ok": True,
               "data": {"pcell": geo.pcell, "params": geo.params,
                        "n_primitives": len(geo.to_dicts()),
                        "primitives": geo.to_dicts()}}
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    console.print(f"[green]✓[/green] {geo.pcell}: {len(geo.to_dicts())} 原语"
                  f"（params={geo.params}）")
    for row in geo.to_dicts():
        console.print(f"  [{row['kind']}] {row.get('name') or '-'}"
                      f" layer={row['layer']}")


@pcell_app.command("render")
def pcell_render_cmd(
    name: str = typer.Argument(..., help="PCell 名（须为毫米口径单元）"),
    param: list[str] = typer.Option(None, "--param", "-p", help="参数名=值（可多次）"),  # noqa: B008
    context: list[str] = typer.Option(None, "--context", "-c", help="上下文常量名=值（可多次）"),  # noqa: B008
    out: str = typer.Option(None, "--out", help="输出文件路径（给则按 --fmt 导出）"),
    fmt: str = typer.Option("gdsii", "--fmt", help="导出格式: gdsii|dxf|ipc2581|odbpp"),
    json_output: bool = typer.Option(False, "--json", "-j", help="输出完整 JSON"),
) -> None:
    """渲染 PCell → Layout（求值产物直产）→ 可选 GDSII/DXF/IPC-2581/ODB++ 导出。"""
    geo = _pcell_eval_or_exit(name, param, context)
    layout = _pcell_geometry_to_layout(geo)
    out_path = None
    if out is not None:
        from rfauto.adapters.layout_interchange import export_layout

        try:
            out_path = str(export_layout(layout, out, fmt))
        except (ValueError, ImportError) as exc:
            console.print(f"[red]✗ Layout 导出失败: {exc}[/red]")
            raise typer.Exit(code=2) from None
    payload = {"ok": True,
               "data": {"pcell": geo.pcell, "params": geo.params,
                        "n_items": len(layout.items),
                        "layers": layout.layer_names(),
                        "name": layout.name, "fmt": fmt, "out": out_path}}
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return
    where = f" → {out_path}（{fmt}）" if out_path else "（未导出，--out 落盘）"
    console.print(f"[green]✓[/green] {layout.name}: {len(layout.items)} 图元"
                  f" 层={layout.layer_names()}{where}")
