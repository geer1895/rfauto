"""bench 子命令组（WP3.7/F6：goldset 回归门 + AgentBench 智能体基准门）。

薄壳层，零业务逻辑（军规 10）——全部转发 service 层确定性函数：
 rfauto bench goldset   → service.goldset_service.run_goldset_regression
 rfauto bench agentbench → service.agent_bench.run_agentbench_regression

注册说明：cli/main.py 本轮对其他轨冻结（共享文件防冲突），本模块独立成文
件，窗口开放后在 main.py 加一行即可上线：
  from rfauto.cli.bench_app import bench_app
  app.add_typer(bench_app, name="bench")
在那之前可用 CliRunner / typer 直接驱动本 app（tests/unit/test_agent_bench.py
即如此做），行为与注册后完全一致。

两道门都是离线、确定性、零网络：真实 runtime/LLM 轨迹由 --trajectories
（已记录埋点）或 service 层 provider 注入；不带输入时用离线参考回放
（门自洽正控），绝不空跑绿。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

bench_app = typer.Typer(
  help="AgentBench/goldset 回归门（WP3.7/F6）——离线、确定性、零网络")


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
    7, "--min-success", help="成功任务数门限（≥7/10）"),
  enable_optimize: bool = typer.Option(
    False, "--enable-optimize",
    help="开启可选第 8 环节·优化发起：对每句达标任务真实发起一次小预算"
       "代理寻优（fake 采样器、seed 固定），kickoff_status 进结果；"
       "缺省关（门口径仍是七环节，kickoff 不参与 pass 判定）；"
       "仅对缺省自跑链生效，--records 已成记录不重跑"),
  optimize_out_dir: str = typer.Option(
    None, "--optimize-out-dir",
    help="配合 --enable-optimize：环返回体落盘目录（缺省不落盘，不污染 runs/）"),
) -> None:
  """ Level 2 端到端门：10 句 NL 设计任务成功率 ≥7/10 + 七环节覆盖矩阵。"""
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
