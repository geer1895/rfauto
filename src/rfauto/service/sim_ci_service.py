"""sim_ci_service：仿真 CI / DesignOps（阶段 7.5，SDL 范式【近】项）。

夜间设计回归：遍历 recipes/ 全配方 → validate + fake 回归（零成本）
→ 与 runs 索引中同配方最近一次同通道 run 的指标对照 → 指标劣化超阈
即记 regression。产物：runs/<rid>/sim_ci_report.json + 人读 markdown。

回归判定（确定性）：s11_db_max_in_band 等关键指标劣化 > 容差（默认
1.0dB）且两 run 适配器同通道。无历史基线时记 baseline_missing，不算失败。

 加性扩展：nightly_multisource_regression 在既有 fake 全量
回归之外编排三源——fake 全量 + openEMS 冒烟抽检 + HFSS 周抽检——产出
逐源回归报告（pass/fail/skipped）、G14 成本表（pipeline/quota_guard 的
CostLedger.rollup）与"红即 issue 化"的 issue 列表/JSON。openEMS/HFSS 两源
走可注入 runner：本服务不直接启动求解器，真机由调度层注入，单测注入
fake runner（无网络、无真机、确定性）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REGRESSION_METRIC = "s11_db_max_in_band"
_REGRESSION_TOLERANCE_DB = 1.0

#: 三源（稳定顺序）——fake 全量 / openEMS 冒烟抽检 / HFSS 周抽检。
SOURCES: tuple[str, ...] = ("fake", "openems", "hfss")

#: 可注入 runner 契约：runner(recipe_path_str) -> dict，至少含 ok。
_Runner = Callable[[str], dict[str, Any]]


def _scan_recipe_files(
  recipe_files: list[Path],
  *,
  adapter: str,
  tolerance_db: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
  """fake 全量扫描：validate + run_once + runs 索引历史对照。

  纯扫描——不创建 run 目录、不写 meta，供 nightly_regression 与
  nightly_multisource_regression 共用，保证两条路径的回归判定逐位一致。

  返回 (entries, regressions)。
  """
  import yaml

  from rfauto.service.api import run_once
  from rfauto.service.runs_stats import query_runs

  entries: list[dict[str, Any]] = []
  regressions: list[dict[str, Any]] = []

  for rf in recipe_files:
    entry: dict[str, Any] = {"recipe": rf.name}
    validation_ok = True
    try:
      with open(rf, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
      validation_ok = bool(recipe.get("objectives"))
    except Exception as exc:
      entry.update({"status": "invalid", "error": str(exc)})
      entries.append(entry)
      continue
    if not validation_ok:
      entry["status"] = "invalid"
      entries.append(entry)
      continue

    r = run_once(str(rf), adapter_name=adapter)
    if not r.get("ok"):
      entry.update({"status": "error", "error": str(r.get("errors"))})
      entries.append(entry)
      continue
    metrics = r.get("metrics") or {}
    entry.update({"status": "done", "run_id": r.get("run_id"),
           "metrics": metrics})

    # 对照同配方最近一次同通道 run（排除本次）
    history = query_runs(adapter="fake", limit=20)
    prior = next((h for h in history.get("runs", [])
           if h.get("model") == recipe.get("model")
           and h.get("run_id") != r.get("run_id")
           and (h.get("metrics") or {}).get(_REGRESSION_METRIC)
           is not None), None)
    if prior is None:
      entry["baseline"] = "missing"
    else:
      cur = metrics.get(_REGRESSION_METRIC)
      base = prior["metrics"][_REGRESSION_METRIC]
      if cur is not None:
        delta = float(cur) - float(base)
        entry["baseline"] = {"run_id": prior["run_id"],
                   "base": base, "delta_db": round(delta, 3)}
        if delta > tolerance_db: # s11 是 max_below 指标：升高=劣化
          regressions.append({"recipe": rf.name,
                    "metric": _REGRESSION_METRIC,
                    "current": cur, "baseline": base,
                    "delta_db": round(delta, 3),
                    "baseline_run_id": prior["run_id"]})
    entries.append(entry)

  return entries, regressions


def nightly_regression(
  recipes_dir: str | Path = "recipes",
  *,
  adapter: str = "fake",
  tolerance_db: float = _REGRESSION_TOLERANCE_DB,
) -> dict[str, Any]:
  """全配方回归：validate+run → 对照 runs 索引历史 → diff 报告。"""
  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, write_meta

  root = Path(recipes_dir)
  if not root.exists():
    return {"ok": False, "errors": [f"配方目录不存在: {root}"]}
  recipe_files = sorted(root.glob("*.yaml"))
  if not recipe_files:
    return {"ok": False, "errors": [f"{root} 下无配方"]}

  run_id = generate_run_id()
  run_dir = create_run_dir(Path(".").resolve(), run_id)
  entries, regressions = _scan_recipe_files(
    recipe_files, adapter=adapter, tolerance_db=tolerance_db)

  report = {
    "ok": True,
    "run_id": run_id,
    "run_dir": str(run_dir),
    "adapter": adapter,
    "n_recipes": len(recipe_files),
    "n_done": sum(1 for e in entries if e.get("status") == "done"),
    "n_regressions": len(regressions),
    "regressions": regressions,
    "entries": entries,
  }
  (run_dir / "sim_ci_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1, default=str),
    encoding="utf-8")
  lines = ["# 仿真 CI 夜间回归", "",
       f"- 配方：{report['n_recipes']} 个（完成 {report['n_done']}）",
       f"- 回归：{report['n_regressions']} 个"
       f"（阈值 {_REGRESSION_METRIC} 劣化 > {tolerance_db}dB）", ""]
  for e in entries:
    lines.append(f"- {e['recipe']}: {e.get('status')}")
  (run_dir / "sim_ci_report.md").write_text(
    "\n".join(lines) + "\n", encoding="utf-8")
  write_meta(run_dir, {
    "run_id": run_id, "model": "sim_ci", "status": "done",
    "adapter": f"sim_ci:{adapter}", "algorithm": "nightly_regression",
    "metrics": {"n_recipes": report["n_recipes"],
          "n_regressions": report["n_regressions"]}})
  return report


# ---------------------------------------------------------------------------
# 三源夜间回归 + G14 成本表 + 红即 issue 化
# ---------------------------------------------------------------------------

def _even_sample(items: list[Any], n: int) -> list[Any]:
  """确定性等距抽检：在 items 中等距取 n 个（n >= len 时全取）。

  抽检集合只依赖 (items, n)，与运行环境/时间无关——两次同输入得到同一子集。
  """
  n = int(n)
  if n <= 0 or not items:
    return []
  if n >= len(items):
    return list(items)
  if n == 1:
    return [items[0]]
  step = (len(items) - 1) / (n - 1)
  indices = sorted({round(i * step) for i in range(n)})
  return [items[i] for i in indices]


def _run_one(runner: _Runner, recipe_path: str) -> dict[str, Any]:
  """调用注入 runner；异常/非 dict 返回值显式转为失败结果（不抛出）。"""
  try:
    raw = runner(recipe_path)
  except Exception as exc: # runner 是外部注入点：失败记为抽检失败
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
  if not isinstance(raw, dict):
    return {"ok": False, "error": f"runner 返回非 dict: {type(raw).__name__}"}
  return raw


def _ledger_add(ledger: Any, batch: str, actor: str,
        cost: dict[str, Any]) -> None:
  """把 runner 上报的 cost 累加进 G14 CostLedger（仅 LEDGER_FIELDS 子集）。"""
  from rfauto.pipeline.quota_guard import LEDGER_FIELDS

  fields = {key: float(cost[key]) for key in LEDGER_FIELDS if key in cost}
  if fields:
    ledger.add(batch, actor, **fields)


def _external_source(
  *,
  source: str,
  recipe_files: list[Path],
  sample: int,
  runner: _Runner | None,
  ledger: Any,
  skipped_reason: str | None = None,
  extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """编排一个可注入 runner 的外部源（openEMS 冒烟抽检 / HFSS 周抽检）。"""
  picked = _even_sample(recipe_files, sample)
  info: dict[str, Any] = {
    "requested_sample": int(sample),
    "n_sampled": len(picked),
    "sample": [p.name for p in picked],
    "results": [],
    "n_pass": 0,
    "n_fail": 0,
  }
  if extra:
    info.update(extra)

  if skipped_reason is not None:
    info.update({"status": "skipped", "skipped_reason": skipped_reason})
    return info
  if runner is None:
    info.update({"status": "skipped", "skipped_reason": "no_runner"})
    return info
  if int(sample) <= 0:
    info.update({"status": "skipped", "skipped_reason": "sample_zero"})
    return info
  if not picked:
    info.update({"status": "skipped", "skipped_reason": "no_recipes"})
    return info

  results: list[dict[str, Any]] = []
  for path in picked:
    res = _run_one(runner, str(path))
    row: dict[str, Any] = {"recipe": path.name, "ok": bool(res.get("ok"))}
    if "metrics" in res:
      row["metrics"] = res["metrics"]
    cost = res.get("cost")
    if isinstance(cost, dict):
      row["cost"] = dict(cost)
      try:
        _ledger_add(ledger, source, path.name, cost)
      except (TypeError, ValueError) as exc:
        row["ok"] = False
        row["error"] = f"cost 非法: {exc}"
    if not row["ok"]:
      row.setdefault(
        "error", str(res.get("error") or res.get("errors") or "unknown"))
    results.append(row)

  n_fail = sum(1 for r in results if not r["ok"])
  info.update({
    "status": "fail" if n_fail else "pass",
    "results": results,
    "n_pass": len(results) - n_fail,
    "n_fail": n_fail,
  })
  return info


def _build_issues(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
  """红即 issue 化：任一源 status == fail 产出一条 issue，否则空列表。"""
  issues: list[dict[str, Any]] = []
  for source in SOURCES:
    info = sources.get(source) or {}
    if info.get("status") != "fail":
      continue
    if source == "fake":
      failed = [e for e in info.get("entries", [])
           if e.get("status") != "done"]
      issues.append({
        "id": "sim-ci-fake",
        "source": "fake",
        "severity": "error",
        "title": (f"fake 全量回归失败：{info.get('n_regressions', 0)} 项劣化，"
             f"{len(failed)} 个配方未完成"),
        "detail": {
          "n_regressions": info.get("n_regressions", 0),
          "regressions": info.get("regressions", []),
          "failed_recipes": [e.get("recipe") for e in failed],
        },
      })
    else:
      failures = [r for r in info.get("results", []) if not r.get("ok")]
      issues.append({
        "id": f"sim-ci-{source}",
        "source": source,
        "severity": "error",
        "title": (f"{source} 抽检失败：{len(failures)}/"
             f"{info.get('n_sampled', 0)}"),
        "detail": {
          "failures": [{"recipe": r.get("recipe"),
                 "error": r.get("error")} for r in failures],
        },
      })
  return issues


def _render_md(report: dict[str, Any]) -> str:
  """人读 markdown：逐源状态 + G14 成本表（空表不渲染）。"""
  src = report["sources"]
  lines = [
    "# 仿真 CI 夜间回归（三源）", "",
    f"- 配方：{report['n_recipes']} 个（完成 {report['n_done']}）",
    f"- 总体：{report['status']}",
    f"- 回归：{report['n_regressions']} 个"
    f"（阈值 {_REGRESSION_METRIC} 劣化 > {report['tolerance_db']}dB）",
    f"- issue：{len(report['issues'])} 个", "",
    "| 源 | 状态 | 详情 |", "| --- | --- | --- |",
    f"| fake | {src['fake']['status']} | "
    f"{src['fake']['n_done']}/{src['fake']['n_recipes']} 完成，"
    f"{src['fake']['n_regressions']} 劣化 |",
  ]
  for name in ("openems", "hfss"):
    info = src[name]
    detail = (info.get("skipped_reason")
         or f"{info['n_pass']} pass / {info['n_fail']} fail")
    lines.append(f"| {name} | {info['status']} | {detail} |")
  lines.append("")
  if report["cost_table"]:
    lines.append("## G14 成本表")
    lines.append("")
    for batch in sorted(report["cost_table"]):
      row = report["cost_table"][batch]
      lines.append(f"- {batch}: solve_s={row['solve_s']} "
             f"seat_hours={row['seat_hours']} "
             f"total_tokens={row['total_tokens']} "
             f"cost={row['cost']}")
    lines.append("")
  return "\n".join(lines) + "\n"


def nightly_multisource_regression(
  recipes_dir: str | Path = "recipes",
  *,
  adapter: str = "fake",
  tolerance_db: float = _REGRESSION_TOLERANCE_DB,
  openems_sample: int = 0,
  hfss_sample: int = 0,
  openems_runner: _Runner | None = None,
  hfss_runner: _Runner | None = None,
  hfss_due: bool = False,
  ledger: Any = None,
  run_id: str | None = None,
) -> dict[str, Any]:
  """三源夜间回归（⑫）：fake 全量 + openEMS 冒烟 + HFSS 周抽检。

  * fake 全量：复用 _scan_recipe_files（validate + fake run + 历史对照），
   零成本、确定性，是"现在就能跑的那种"；
  * openEMS 冒烟抽检 / HFSS 周抽检：由调用方注入 runner(recipe_path)->dict
   （至少含 ok；可选 metrics/cost）。单测注入 fake runner；真机由 CLI/
   调度层注入，本服务不直接启动求解器。缺 runner / sample<=0 / HFSS 非
   出检周 → 该源 skipped 且 runner 不被调用；
  * G14 成本表：ledger 可为注入的 CostLedger（默认新建）；runner 上报的
   cost（LEDGER_FIELDS 子集）累加进对应 source batch，cost_table 即
   CostLedger.rollup()；
  * 红即 issue 化：任一源 fail → issues 非空，落盘 sim_ci_issues.json；
   全绿 → issues == []（防空转）。

  产物：runs/<run_id>/sim_ci_report.json（sort_keys，同输入逐字节一致）、
  sim_ci_report.md、sim_ci_issues.json、meta.json。

  返回 {"ok": False, "errors": [...]}（显式、不落盘）的情形：配方目录
  不存在/无配方、sample 非非负整数、runner 非可调用、ledger 非 CostLedger、
  run_id 非非空字符串。
  """
  from rfauto.core.state import generate_run_id
  from rfauto.infra.run_store import create_run_dir, write_meta
  from rfauto.pipeline.quota_guard import CostLedger

  errors: list[str] = []
  if run_id is not None and (not isinstance(run_id, str) or not run_id):
    errors.append("run_id 必须是非空字符串")
  for label, value in (("openems_sample", openems_sample),
             ("hfss_sample", hfss_sample)):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
      errors.append(f"{label} 必须是非负整数，得到 {value!r}")
  for label, runner in (("openems_runner", openems_runner),
             ("hfss_runner", hfss_runner)):
    if runner is not None and not callable(runner):
      errors.append(f"{label} 必须是可调用对象（runner(recipe_path)->dict）")
  if ledger is not None and not isinstance(ledger, CostLedger):
    errors.append("ledger 必须是 pipeline.quota_guard.CostLedger 实例")

  root = Path(recipes_dir)
  if not root.exists():
    errors.append(f"配方目录不存在: {root}")
  recipe_files = sorted(root.glob("*.yaml")) if root.exists() else []
  if root.exists() and not recipe_files:
    errors.append(f"{root} 下无配方")
  if errors:
    return {"ok": False, "errors": errors}

  if ledger is None:
    ledger = CostLedger()
  if run_id is None:
    run_id = generate_run_id()
  run_dir = create_run_dir(Path(".").resolve(), run_id)

  entries, regressions = _scan_recipe_files(
    recipe_files, adapter=adapter, tolerance_db=tolerance_db)
  n_done = sum(1 for e in entries if e.get("status") == "done")
  fake_failed = any(e.get("status") != "done" for e in entries)
  fake_source: dict[str, Any] = {
    "status": "fail" if (regressions or fake_failed) else "pass",
    "n_recipes": len(recipe_files),
    "n_done": n_done,
    "n_failed": len(recipe_files) - n_done,
    "n_regressions": len(regressions),
    "regressions": regressions,
    # 内层 run_id 每次不同，剔除后报告可逐字节复现；证据本体在
    # runs/<内层 run_id>/，由 regressions[].baseline_run_id 引用。
    "entries": [{k: v for k, v in e.items() if k != "run_id"}
          for e in entries],
  }

  openems_source = _external_source(
    source="openems", recipe_files=recipe_files, sample=openems_sample,
    runner=openems_runner, ledger=ledger)
  hfss_source = _external_source(
    source="hfss", recipe_files=recipe_files, sample=hfss_sample,
    runner=hfss_runner, ledger=ledger,
    skipped_reason=None if hfss_due else "not_due",
    extra={"due": bool(hfss_due)})

  sources = {"fake": fake_source, "openems": openems_source,
        "hfss": hfss_source}
  issues = _build_issues(sources)
  statuses = [sources[s]["status"] for s in SOURCES]
  if "fail" in statuses:
    status = "fail"
  elif "pass" in statuses:
    status = "pass"
  else:
    status = "skipped"

  issue_file = run_dir / "sim_ci_issues.json"
  report: dict[str, Any] = {
    "ok": True,
    "algorithm": "nightly_multisource_regression",
    "status": status,
    "run_id": run_id,
    "run_dir": str(run_dir),
    "adapter": adapter,
    "tolerance_db": tolerance_db,
    "n_recipes": len(recipe_files),
    "n_done": n_done,
    "n_regressions": len(regressions),
    "n_sources": len(SOURCES),
    "n_sources_pass": statuses.count("pass"),
    "n_sources_fail": statuses.count("fail"),
    "n_sources_skipped": statuses.count("skipped"),
    "sources": sources,
    "regressions": regressions,
    "issues": issues,
    "issue_file": str(issue_file),
    "cost_table": ledger.rollup(),
  }
  (run_dir / "sim_ci_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True,
          default=str), encoding="utf-8")
  issue_file.write_text(
    json.dumps(issues, ensure_ascii=False, indent=1, sort_keys=True,
          default=str), encoding="utf-8")
  (run_dir / "sim_ci_report.md").write_text(
    _render_md(report), encoding="utf-8")
  write_meta(run_dir, {
    "run_id": run_id, "model": "sim_ci", "status": "done",
    "adapter": f"sim_ci:{adapter}",
    "algorithm": "nightly_multisource_regression",
    "metrics": {"n_recipes": report["n_recipes"],
          "n_regressions": report["n_regressions"],
          "n_issues": len(issues),
          "n_sources_pass": report["n_sources_pass"]}})
  return report
