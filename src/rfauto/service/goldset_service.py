"""goldset_service：工具调用层基准（阶段 2.2，TSA/FCA/pass3 移植）。

gold set（tests/gold/agent_goldset.yaml）定义期望的 typed 工具调用序列；
score_trajectory 把一条 agent 轨迹对照期望打分：
- TSA Tool Selection Accuracy：期望命令按子序列出现在轨迹中
- FCA Full Call Accuracy：命令 + args 子集匹配（"<...>" 占位视为存在即可）
- pass3：期望序列在轨迹前 3 个调用内完整出现
宏平均聚合，验收口径 TSA≥90%。确定性内核——打分不经过任何 LLM。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

_GOLDSET_PATH = Path(__file__).resolve().parent.parent.parent.parent / \
  "tests" / "gold" / "agent_goldset.yaml"

_READONLY_TOOLS = {"doctor", "audit", "validate", "runs", "solvers", "inbox"}


def load_goldset(path: str | Path | None = None) -> dict[str, Any]:
  """加载 gold set（结构自检：id 唯一、必要字段齐全）。"""
  import yaml

  p = Path(path) if path else _GOLDSET_PATH
  if not p.exists():
    return {"ok": False, "errors": [f"gold set 不存在: {p}"]}
  data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
  tasks = data.get("tasks") or []
  errors: list[str] = []
  ids = [t.get("id") for t in tasks]
  if len(ids) != len(set(ids)):
    errors.append("任务 id 重复")
  for t in tasks:
    for field in ("id", "level", "prompt", "expected"):
      if field not in t:
        errors.append(f"{t.get('id', '?')} 缺字段 {field}")
    calls = (t.get("expected") or {}).get("calls") or []
    if not calls:
      errors.append(f"{t.get('id', '?')} expected.calls 为空")
  if errors:
    return {"ok": False, "errors": errors}
  return {"ok": True, "path": str(p), "n_tasks": len(tasks), "tasks": tasks}


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
  it = iter(haystack)
  return all(any(tok == h for h in it) for tok in needle)


def _args_match(expected_args: dict[str, Any], actual_args: dict[str, Any]) -> bool:
  """期望 args 的子集匹配；"<...>" 占位值视为"键存在即可"。"""
  for k, v in expected_args.items():
    if k not in actual_args:
      return False
    av = actual_args[k]
    if isinstance(v, str) and v.startswith("<") and v.endswith(">"):
      if av in (None, "", {}):
        return False
      continue
    if isinstance(v, dict):
      if not isinstance(av, dict) or not _args_match(v, av):
        return False
      continue
    if av != v:
      return False
  return True


def score_trajectory(task: dict[str, Any], trajectory: list[dict[str, Any]]) -> dict[str, Any]:
  """单任务打分：{"tsa": 0/1, "fca": 0/1, "pass3": 0/1}。

  轨迹格式：[{"tool": str, "args": dict}, ...]。子序列匹配天然容忍
  穿插任何额外调用（含只读的 doctor/audit/validate——"先查后动"免罚）。
  pass3 = 期望序列在轨迹前 3 个调用内完整出现。
  """
  expected_calls = (task.get("expected") or {}).get("calls") or []
  exp_tools = [c["tool"] for c in expected_calls]
  exp_arg_list = [c.get("args") or {} for c in expected_calls]

  traj_tools = [c.get("tool", "") for c in trajectory]

  tsa = _is_subsequence(exp_tools, traj_tools)

  # FCA：逐期望调用找首个命令+args 匹配的实现（贪心，按序消耗）
  fca = True
  pos = 0
  for want_args, tool in zip(exp_arg_list, exp_tools, strict=True):
    found = False
    for j in range(pos, len(trajectory)):
      c = trajectory[j]
      if c.get("tool") == tool and _args_match(want_args, c.get("args") or {}):
        pos = j + 1
        found = True
        break
    if not found:
      fca = False
      break

  # pass3：期望序列在轨迹前 3 个调用内完整出现
  pass3 = int(tsa and _is_subsequence(exp_tools, traj_tools[:3]))

  return {"id": task.get("id"), "tsa": int(tsa), "fca": int(fca),
      "pass3": int(pass3)}


def evaluate_trajectory_set(
  trajectories: list[dict[str, Any]],
  goldset_path: str | Path | None = None,
) -> dict[str, Any]:
  """批量评测：trajectories = [{"id": 任务id, "trajectory": [...]}]。

  返回宏平均 TSA/FCA/pass3 + 逐任务明细；TSA≥0.9 为验收线。
  """
  gold = load_goldset(goldset_path)
  if not gold.get("ok"):
    return gold
  by_id = {t["id"]: t for t in gold["tasks"]}
  results = []
  for item in trajectories:
    task = by_id.get(item.get("id"))
    if task is None:
      results.append({"id": item.get("id"), "error": "未知任务"})
      continue
    results.append(score_trajectory(task, item.get("trajectory") or []))
  scored = [r for r in results if "error" not in r]
  n = max(len(scored), 1)
  return {
    "ok": True,
    "n_tasks": len(trajectories),
    "tsa": sum(r["tsa"] for r in scored) / n,
    "fca": sum(r["fca"] for r in scored) / n,
    "pass3": sum(r["pass3"] for r in scored) / n,
    "gate_tsa": "PASS" if sum(r["tsa"] for r in scored) / n >= 0.9 else "FAIL",
    "results": results,
  }


# ---------------------------------------------------------------------------
# ：金标轨迹作 runtime/协议变更回归门（WP3.7/F6）
# ---------------------------------------------------------------------------
# 加性：上面的 load_goldset / score_trajectory / evaluate_trajectory_set 行为不变。
# 门 = ① 协议面检查（当前 runtime 暴露的工具是否仍覆盖金标期望工具面）
#   ② 金标轨迹打分阈值（TSA/FCA/pass3）。
# runtime 变更后一键跑：
#  run_goldset_regression(trajectory_provider=<当前 runtime 提供器>,
#             runtime_tools=<当前 runtime 工具面>)
# 真实 runtime/LLM 通道由调用方经 trajectory_provider 注入——门自身不发任何
# 网络请求；测试按 #139 一律 monkeypatch 钉住该通道。

REGRESSION_SCHEMA_VERSION = 1
DEFAULT_MIN_TSA = 0.9
DEFAULT_MIN_FCA = 0.9
DEFAULT_MIN_PASS3 = 0.0


def goldset_expected_tools(goldset: Mapping[str, Any]) -> list[str]:
  """金标集期望工具面（全部任务 expected.calls 的工具名，去重排序）。"""
  names: set[str] = set()
  for task in goldset.get("tasks") or []:
    for call in (task.get("expected") or {}).get("calls") or []:
      name = str(call.get("tool") or "").strip()
      if name:
        names.add(name)
  return sorted(names)


def protocol_surface(tools: Iterable[str]) -> dict[str, Any]:
  """工具面 → 规范化指纹（排序去重 + sha256）：确定性、可跨 run 比对。"""
  names: set[str] = set()
  for tool in tools:
    name = str(tool).strip()
    if name:
      names.add(name)
  ordered = sorted(names)
  digest = hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()
  return {"n_tools": len(ordered), "tools": ordered, "sha256": digest}


def reference_trajectory_provider(task: Mapping[str, Any]) -> list[dict[str, Any]]:
  """离线参考提供器：回放金标期望序列（确定性、无网络、无 LLM）。

  仅作门自身的正控（证明金标与打分器自洽、门能跑通），不构成对真实 agent
  质量的判据。真实 runtime 变更回归请注入实际 runtime 的 provider。
  """
  calls = (task.get("expected") or {}).get("calls") or []
  return [{"tool": str(call.get("tool") or ""),
       "args": dict(call.get("args") or {})}
      for call in calls]


def run_goldset_regression(
  trajectories: Sequence[Mapping[str, Any]] | None = None,
  *,
  goldset_path: str | Path | None = None,
  runtime_tools: Iterable[str] | None = None,
  trajectory_provider: Callable[[Mapping[str, Any]], Any] | None = None,
  min_tsa: float = DEFAULT_MIN_TSA,
  min_fca: float = DEFAULT_MIN_FCA,
  min_pass3: float = DEFAULT_MIN_PASS3,
  require_full_coverage: bool = True,
) -> dict[str, Any]:
  """金标回归门：当前 runtime/协议下跑金标轨迹 → 阈值判定 PASS/FAIL。

  参数：
   trajectories —— 已记录轨迹 [{"id": 任务id, "trajectory": [...]}]；
   trajectory_provider —— 每任务调用一次的提供器（LLM/agent 通道注入点）；
   runtime_tools —— 当前 runtime 暴露的工具名；给定时校验金标期望工具面
            是否仍被完全覆盖，缺一即 FAIL（协议变更回归）；
   min_tsa/min_fca/min_pass3 —— 阈值（默认 TSA/FCA ≥0.9，pass3 ≥0）；
   require_full_coverage —— 轨迹是否必须覆盖全部金标任务（默认是）。

  防空转：既无 trajectories 又无 provider / 轨迹为空 / 未覆盖任何金标任务
  或含未知任务 id → 直接 FAIL，绝不空跑绿。
  """
  gold = load_goldset(goldset_path)
  gold_ok = bool(gold.get("ok"))
  tasks = list(gold.get("tasks") or []) if gold_ok else []
  expected_protocol = protocol_surface(
    goldset_expected_tools(gold) if gold_ok else [])

  runtime_protocol: dict[str, Any] | None = None
  missing_tools: list[str] = []

  def _result(ok: bool, reasons: list[str], *,
        errors: list[str] | None = None,
        n_scored: int = 0,
        report: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
      "ok": ok,
      "gate": "PASS" if ok else "FAIL",
      "schema_version": REGRESSION_SCHEMA_VERSION,
      "n_tasks": len(tasks),
      "n_scored": n_scored,
      "expected_protocol": expected_protocol,
      "runtime_protocol": runtime_protocol,
      "missing_tools": missing_tools,
      "min_tsa": float(min_tsa),
      "min_fca": float(min_fca),
      "min_pass3": float(min_pass3),
      "report": report,
      "reasons": reasons,
      "errors": errors if errors is not None else ([] if ok else list(reasons)),
    }

  if not gold_ok:
    return _result(False, list(gold.get("errors") or ["金标集加载失败"]))
  if not tasks:
    return _result(False, ["金标集为空：拒绝空跑（防空转）"])

  if runtime_tools is not None:
    if isinstance(runtime_tools, (str, bytes)):
      return _result(False, ["runtime_tools 必须是工具名序列，不是字符串"])
    try:
      runtime_protocol = protocol_surface(runtime_tools)
    except TypeError as exc:
      return _result(False, [f"runtime_tools 非法: {exc}"])
    runtime_set = set(runtime_protocol["tools"])
    missing_tools = [t for t in expected_protocol["tools"]
             if t not in runtime_set]
    if missing_tools:
      return _result(False, [
        f"协议面回归：runtime 缺金标期望工具 {len(missing_tools)} 个 "
        f"→ {missing_tools[:5]}"])

  if trajectory_provider is not None:
    provided: list[dict[str, Any]] = []
    for task in tasks:
      try:
        produced = trajectory_provider(task)
      except Exception as exc: # 提供器（LLM/agent 通道）异常即门红
        return _result(False, [
          f"轨迹提供器异常（task={task.get('id')}）: {exc}"])
      if not isinstance(produced, (list, tuple)):
        return _result(False, [
          f"轨迹提供器返回非序列（task={task.get('id')}）"])
      provided.append({"id": task.get("id"), "trajectory": list(produced)})
    items: list[Mapping[str, Any]] = provided
  elif trajectories is not None:
    if not isinstance(trajectories, (list, tuple)):
      return _result(False, ["trajectories 必须是序列"])
    items = list(trajectories)
    if not items:
      return _result(False, ["轨迹为空：拒绝空跑（防空转）"])
  else:
    return _result(False, [
      "未提供 trajectories 或 trajectory_provider：拒绝空跑（防空转）"])

  known_ids = {t["id"] for t in tasks}
  seen: set[Any] = set()
  unknown: list[str] = []
  for item in items:
    if not isinstance(item, Mapping):
      return _result(False, ["轨迹项必须是映射 {id, trajectory}"])
    tid = item.get("id")
    if tid in known_ids:
      seen.add(tid)
    else:
      unknown.append(str(tid))
    traj = item.get("trajectory")
    if traj is not None and not isinstance(traj, (list, tuple)):
      return _result(False, [
        f"轨迹 trajectory 必须是序列（task={item.get('id')}）"])
  if unknown:
    return _result(False, [f"轨迹含未知任务 id: {unknown[:5]}"],
            n_scored=len(seen))
  if not seen:
    return _result(False, ["轨迹未覆盖任何金标任务（防空转）"])
  if require_full_coverage and seen != known_ids:
    absent = sorted(known_ids - seen)
    return _result(False, [
      f"轨迹未覆盖全部金标任务：缺 {len(absent)} 个 {absent[:5]}"],
      n_scored=len(seen))

  report = evaluate_trajectory_set(items, goldset_path)
  if not report.get("ok"):
    return _result(False, ["金标打分失败"],
            errors=list(report.get("errors") or []),
            n_scored=len(seen))
  reasons: list[str] = []
  if float(report["tsa"]) < float(min_tsa):
    reasons.append(f"TSA {report['tsa']:.4f} < 阈值 {float(min_tsa):.4f}")
  if float(report["fca"]) < float(min_fca):
    reasons.append(f"FCA {report['fca']:.4f} < 阈值 {float(min_fca):.4f}")
  if float(report["pass3"]) < float(min_pass3):
    reasons.append(f"pass3 {report['pass3']:.4f} < 阈值 {float(min_pass3):.4f}")
  if reasons:
    return _result(False, reasons, n_scored=len(seen), report=report)
  return _result(True, ["全绿：协议面完整且金标回归达标"],
          n_scored=len(seen), report=report)
