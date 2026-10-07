"""bench 子命令组（WP3.7/F6：goldset 回归门 + AgentBench 智能体基准门 +
AD-1 系统提示词回归门 + AD-4 pass^k 一致性门）。

薄壳层，零业务逻辑（军规 10）——全部转发 service 层确定性函数：
  rfauto bench goldset             → service.goldset_service.run_goldset_regression
  rfauto bench agentbench          → service.agent_bench.run_agentbench_regression
  rfauto bench prompt-regression   → service.agent_bench.run_prompt_regression
  rfauto bench consistency         → service.agent_bench.evaluate_agentbench_consistency

注册说明：bench_app 已在 cli/main.py 注册上线（``app.add_typer(bench_app,
name="bench")``）；也可用 CliRunner / typer 直接驱动本 app
（tests/unit/test_pass_at_k.py 即如此做），行为与注册后完全一致。

三道门都是离线、确定性、零网络：真实 runtime/LLM 轨迹由 --trajectories/
--records（已记录埋点）或 service 层 provider 注入；不带输入时用离线参考
回放（门自洽正控），绝不空跑绿；LLM 通道按 #139 一律由调用方注入/钉住。

VI-5 W2-C --json 归一（2026-10-05）：五命令自始即 JSON 信封直出（本文件
_emit），故 --json 为归一兼容旗标——接受但两形态同输出（缺省路径逐字节
不变铁纪律优先于纯切换形态）。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

bench_app = typer.Typer(
    help="AgentBench/goldset 回归门（WP3.7/F6）——离线、确定性、零网络")

# VI-5 W2-C：归一兼容旗标（bench 五命令缺省即 JSON 信封，旗标两形态同输出）
_JSON_COMPAT_HELP = (
    "JSON 信封输出（成功+失败同构；本命令缺省即 JSON 信封，旗标为归一兼容位）"
)


def _load_trajectories(path: str) -> list[dict]:
    """读已记录轨迹/埋点 JSON（[{"id","trajectory",...}, ...]）。"""
    p = Path(path)
    if not p.exists():
        typer.echo(f"✗ 轨迹文件不存在: {p}")
        raise typer.Exit(code=2)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        typer.echo(f"✗ 轨迹文件不可读: {exc}")
        raise typer.Exit(code=2) from None
    if not isinstance(data, list):
        typer.echo("✗ 轨迹文件必须是 JSON 数组")
        raise typer.Exit(code=2)
    return data


def _runtime_tools(spec: str | None) -> list[str] | None:
    """--runtime-tools 解析：None=不查协议面；'auto'=agent 聊天通道内置工具面。"""
    if spec is None:
        return None
    if spec.strip().lower() == "auto":
        from rfauto.service.agent_runtime import default_tool_specs

        return [t.name for t in default_tool_specs()]
    return [tok.strip() for tok in spec.split(",") if tok.strip()]


def _emit(result: dict) -> None:
    """JSON 进出（服务层契约直出）+ 门色退出码（PASS=0 / FAIL=1）。"""
    typer.echo(json.dumps(result, ensure_ascii=False, indent=1))
    raise typer.Exit(code=0 if result.get("ok") else 1)


@bench_app.command("goldset")
def goldset(
    trajectories: str = typer.Option(
        None, "--trajectories", "-t",
        help="已记录轨迹 JSON（[{'id','trajectory'}]）；缺省用离线参考回放（门自洽正控）"),
    goldset: str = typer.Option(
        None, "--goldset",
        help="金标集路径（缺省 tests/gold/agent_goldset.yaml）"),
    runtime_tools: str = typer.Option(
        None, "--runtime-tools",
        help="逗号分隔工具名做协议面覆盖检查；'auto'=读 agent_runtime 内置工具面"),
    min_tsa: float = typer.Option(0.9, "--min-tsa", help="TSA 阈值"),
    min_fca: float = typer.Option(0.9, "--min-fca", help="FCA 阈值"),
    min_pass3: float = typer.Option(0.0, "--min-pass3", help="pass3 阈值"),
    lenient: bool = typer.Option(
        False, "--lenient", help="不要求轨迹覆盖全部金标任务"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """工具调用层金标回归门（runtime/协议变更后一键回归）。"""
    from rfauto.service.goldset_service import (
        reference_trajectory_provider,
        run_goldset_regression,
    )

    traj_arg: list[dict] | None = None
    provider = None
    if trajectories:
        traj_arg = _load_trajectories(trajectories)
    else:
        provider = reference_trajectory_provider
    _emit(run_goldset_regression(
        traj_arg,
        goldset_path=goldset,
        runtime_tools=_runtime_tools(runtime_tools),
        trajectory_provider=provider,
        min_tsa=min_tsa,
        min_fca=min_fca,
        min_pass3=min_pass3,
        require_full_coverage=not lenient,
    ))


@bench_app.command("agentbench")
def agentbench(
    records: str = typer.Option(
        None, "--records", "-r",
        help="已记录埋点 JSON（[{'id','trajectory','artifacts','numeric'}]）；"
             "缺省用离线参考回放（门自洽正控）"),
    public_set: str = typer.Option(
        None, "--public-set", help="公开集路径（缺省 tests/gold/agentbench_public.yaml）"),
    private_set: str = typer.Option(
        None, "--private-set",
        help="私有集路径（缺省读环境变量 RFAUTO_AGENTBENCH_PRIVATE_SET；私有集不入库防污染）"),
    runtime_tools: str = typer.Option(
        None, "--runtime-tools",
        help="逗号分隔工具名做协议面覆盖检查；'auto'=读 agent_runtime 内置工具面"),
    min_abstraction: float = typer.Option(
        0.9, "--min-abstraction", help="任务抽象轴阈值（方法与工具选择）"),
    min_execution: float = typer.Option(
        0.8, "--min-execution", help="执行轴阈值（工件齐全性+数值 vs ground truth）"),
    require_private: bool = typer.Option(
        False, "--require-private", help="私有集未配置/不可用即 FAIL（终评口径）"),
    lenient: bool = typer.Option(
        False, "--lenient", help="不要求记录覆盖全部基准任务"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """AgentBench 智能体基准回归门（两轴打分 + 公开/私有双集防污染）。"""
    from rfauto.service.agent_bench import (
        reference_agentbench_provider,
        run_agentbench_regression,
    )

    rec_arg: list[dict] | None = None
    provider = None
    if records:
        rec_arg = _load_trajectories(records)
    else:
        provider = reference_agentbench_provider
    _emit(run_agentbench_regression(
        rec_arg,
        trajectory_provider=provider,
        public_path=public_set,
        private_path=private_set,
        runtime_tools=_runtime_tools(runtime_tools),
        min_abstraction=min_abstraction,
        min_execution=min_execution,
        require_private=require_private,
        require_full_coverage=not lenient,
    ))


@bench_app.command("level2")
def level2(
    records: str = typer.Option(
        None, "--records", "-r",
        help="已记录设计链 JSON（[{'id','trajectory','artifacts','numeric'}]）；"
             "缺省对验收集逐句跑确定性参考链（零 LLM、零网络、fake 离线）"),
    design_set: str = typer.Option(
        None, "--set",
        help="验收集路径（缺省 tests/gold/level2_design_public.yaml）"),
    min_success: int = typer.Option(
        7, "--min-success", help="成功任务数门限（§10.10:671 ≥7/10）"),
    enable_optimize: bool = typer.Option(
        False, "--enable-optimize",
        help="开启可选第 8 环节·优化发起：对每句达标任务真实发起一次小预算"
             "代理寻优（fake 采样器、seed 固定），kickoff_status 进结果；"
             "缺省关（门口径仍是七环节，kickoff 不参与 pass 判定）；"
             "仅对缺省自跑链生效，--records 已成记录不重跑"),
    optimize_out_dir: str = typer.Option(
        None, "--optimize-out-dir",
        help="配合 --enable-optimize：环返回体落盘目录（缺省不落盘，不污染 runs）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """§10.10 Level 2 端到端门：10 句 NL 设计任务成功率 ≥7/10 + 七环节覆盖矩阵。"""
    from rfauto.service.level2_design import run_level2_acceptance

    rec_arg: list[dict] | None = None
    if records:
        rec_arg = _load_trajectories(records)
    _emit(run_level2_acceptance(
        rec_arg,
        set_path=design_set,
        min_success=min_success,
        enable_optimize=enable_optimize,
        optimize_out_dir=optimize_out_dir,
    ))


def _read_prompt_text(path: str, flag: str) -> str:
    """读提示词文本文件（--prompt-a/--prompt-b 用），缺文件/不可读即退出码 2。"""
    p = Path(path)
    if not p.exists():
        typer.echo(f"✗ {flag} 文件不存在: {p}")
        raise typer.Exit(code=2)
    try:
        return p.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"✗ {flag} 不可读: {exc}")
        raise typer.Exit(code=2) from None


@bench_app.command("prompt-regression")
def prompt_regression(
    prompt_a: str = typer.Option(
        ..., "--prompt-a", help="基线（A）系统提示词文本文件路径"),
    prompt_b: str = typer.Option(
        ..., "--prompt-b", help="候选（B）系统提示词文本文件路径"),
    version_a: str = typer.Option(
        None, "--version-a", help="A 版本标签（进指纹落档，如 configs/prompts frontmatter version）"),
    version_b: str = typer.Option(
        None, "--version-b", help="B 版本标签（进指纹落档）"),
    public_set: str = typer.Option(
        None, "--public-set", help="公开集路径（缺省 tests/gold/agentbench_public.yaml）"),
    records_a: str = typer.Option(
        None, "--records-a", help="A 臂已记录埋点 JSON（[{'id','trajectory','artifacts','numeric'}]）；"
                                  "缺省离线参考回放（门自洽正控，不消费 prompt 内容）"),
    records_b: str = typer.Option(
        None, "--records-b", help="B 臂已记录埋点 JSON；与 --records-a 成对给出"),
    runtime_tools_a: str = typer.Option(
        None, "--runtime-tools-a",
        help="A 臂工具面（逗号分隔，协议面覆盖检查）；'auto'=读 agent_runtime 内置工具面"),
    runtime_tools_b: str = typer.Option(
        None, "--runtime-tools-b", help="B 臂工具面（同上；两臂必须一致，否则 n_tools 判红）"),
    pass_threshold: float = typer.Option(
        1.0, "--pass-threshold", help="任务过判定阈值（execution 轴，翻转检测口径）"),
    max_regression_pp: float = typer.Option(
        2.0, "--max-regression-pp", help="abstraction/execution 允许的最大回归（百分点）"),
    adjudicate_flips: str = typer.Option(
        None, "--adjudicate-flips",
        help="已人工逐列裁决放行的翻转任务 id（逗号分隔；未裁决翻转即门红）"),
    cache_dir: str = typer.Option(
        None, "--cache-dir", help="轨迹缓存目录（缺省 runs/prompt_regression）"),
    no_persist: bool = typer.Option(False, "--no-persist", help="不落轨迹缓存"),
    lenient: bool = typer.Option(
        False, "--lenient", help="不要求记录覆盖全部基准任务"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """系统提示词 A/B 回归门（AD-1 §D-4）：两版 prompt × 公开 goldset 四指标差分。

    pass 判据：abstraction/execution 各不低于基线 2 个百分点 + n_tools 一致
    + 无任务 pass→fail 翻转（翻转逐列列出，人工裁决后经 --adjudicate-flips
    放行）。离线零网络：假通道/预录埋点由调用方注入（#139）。
    """
    from rfauto.service.agent_bench import run_prompt_regression

    rec_a = _load_trajectories(records_a) if records_a else None
    rec_b = _load_trajectories(records_b) if records_b else None
    adjudicated = ([s.strip() for s in adjudicate_flips.split(",") if s.strip()]
                   if adjudicate_flips else [])
    _emit(run_prompt_regression(
        _read_prompt_text(prompt_a, "--prompt-a"),
        _read_prompt_text(prompt_b, "--prompt-b"),
        version_a=version_a or None,
        version_b=version_b or None,
        records_a=rec_a,
        records_b=rec_b,
        public_path=public_set,
        runtime_tools_a=_runtime_tools(runtime_tools_a),
        runtime_tools_b=_runtime_tools(runtime_tools_b),
        pass_threshold=pass_threshold,
        max_regression_pp=max_regression_pp,
        adjudicated_flips=adjudicated,
        require_full_coverage=not lenient,
        persist=not no_persist,
        cache_dir=cache_dir,
    ))


@bench_app.command("consistency")
def consistency(
    trials: str = typer.Option(
        ..., "--trials", "-t",
        help="多 trial 埋点 JSON（[{'id','trajectory','artifacts','numeric','cost'?}]；"
             "同一 id 重复出现=同一任务的多次独立尝试）"),
    k: int = typer.Option(
        3, "--k", help="pass^k 尝试数（round15 AD-4：缺省 3 进月门）"),
    pass_threshold: float = typer.Option(
        1.0, "--pass-threshold", help="任务过判定阈值（execution 轴，缺省 1.0=声明维度全对）"),
    public_set: str = typer.Option(
        None, "--public-set", help="公开集路径（缺省 tests/gold/agentbench_public.yaml）"),
    private_set: str = typer.Option(
        None, "--private-set",
        help="私有集路径（缺省读环境变量 RFAUTO_AGENTBENCH_PRIVATE_SET；私有集不入库防污染）"),
    min_pass_hat_k: float = typer.Option(
        None, "--min-pass-hat-k", help="pass^k 宏平均门阈值（给定后不达即 FAIL）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """pass^k × 成本一致性评测门（AD-4）：每任务多次独立 trial 的无偏
    pass^k（METR 口径）与成本线性外推；k 缺省 3（月门口径）。

    离线零网络：trials 必须由调用方注入（已记录埋点），门自身不发请求
    （#139）；任务零 trial 覆盖/未知 id/宏平均不达一律 FAIL，不空跑绿。
    """
    from rfauto.service.agent_bench import evaluate_agentbench_consistency

    _emit(evaluate_agentbench_consistency(
        _load_trajectories(trials),
        k=k,
        pass_threshold=pass_threshold,
        public_path=public_set,
        private_path=private_set,
        min_pass_hat_k=min_pass_hat_k,
    ))


@bench_app.command("netlist-goldset")
def netlist_goldset(
    goldset: str = typer.Option(
        ..., "--goldset",
        help="网表 goldset YAML（schema 见 service.netlist_goldset_service 模块 docstring）"),
    engine: str = typer.Option(
        "qucsator", "--engine",
        help="模拟器通道（v1 仅 qucsator；可执行缺席 fail-closed 显式报缺不静默）"),
    min_pass_rate: float = typer.Option(
        1.0, "--min-pass-rate", help="PASS 率阈值（透传 service 判定门）"),
    exe: str = typer.Option(
        None, "--exe",
        help="qucsatorRF 可执行显式路径（缺省走 resolve_qucsator_exe 四源回退）"),
    json_output: bool = typer.Option(False, "--json", help=_JSON_COMPAT_HELP),
) -> None:
    """网表 goldset 回放门（AI-6/F-10 批B）：注入 qucsatorRF 真通道逐任务回放对照 gold 值。

    通道由 service.netlist_sim_channels 构造（resolve_qucsator_exe 四源
    回退→子进程→dataset 解析→文档化指标约定 sXX_mag/db_min/max 等）；
    通道异常任务判 ERROR 与 FAIL 分列（不混判）；指标约定外无发明语义。

    示例：rfauto bench netlist-goldset --goldset my_netlist_goldset.yaml
    """
    from rfauto.service.netlist_goldset_service import replay_netlist_goldset
    from rfauto.service.netlist_sim_channels import build_simulator_channel

    try:
        channel = build_simulator_channel(engine, exe or None)
    except (FileNotFoundError, ValueError) as exc:
        _emit({"ok": False, "gate": "FAIL", "engine": engine, "n_cases": 0,
               "reasons": [f"模拟器通道构造失败（fail-closed，不静默）: {exc}"]})
        return
    _emit(replay_netlist_goldset(
        goldset_path=goldset, simulator=channel, min_pass_rate=min_pass_rate))
