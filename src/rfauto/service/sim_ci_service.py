"""sim_ci_service：仿真 CI / DesignOps（阶段 7.5，SDL 范式【近】项）。

夜间设计回归：遍历 recipes/ 全配方 → validate + fake 回归（零成本）
→ 与 runs 索引中同配方最近一次同通道 run 的指标对照 → 指标劣化超阈
即记 regression。产物：runs/<rid>/sim_ci_report.json + 人读 markdown。

回归判定（确定性）：s11_db_max_in_band 等关键指标劣化 > 容差（默认
1.0dB）且两 run 适配器同通道。无历史基线时记 baseline_missing，不算失败。

XD-5（sa_specs2 §八，2026-10-05 W2-D）golden 基线钉定面：
- metrics.json 标准：``write_standard_metrics``/``read_standard_metrics``
  ——run_dir/metrics.json 统一 schema（指标名对齐 49 锚 quantity 名集，
  未对齐如实标 unanchored，判据 4 对齐率进报告）；
- golden 基线：``pin_baseline``/``compare_baseline``/``baseline_drift``
  ——把最近同通道 run 的判读 digest 钉进 knowledge/simci_baseline.yaml
  （ORFS metadata-base-ok.json 语义）；``nightly_regression`` 读 golden
  优先（golden 在→对照 golden digest，判定不再随新 run 滚动；golden
  不在→回退现行滚动索引，现状行为逐位不变）。更新走显式 ``update=True``
  重钉，信封携带旧→新 digest 审计串（#325 精神：基线是证据，更新必留痕）。

§10.20 补强⑫（加性）：nightly_multisource_regression 在既有 fake 全量
回归之外编排三源——fake 全量 + openEMS 冒烟抽检 + HFSS 周抽检——产出
逐源回归报告（pass/fail/skipped）、G14 成本表（pipeline/quota_guard 的
CostLedger.rollup）与"红即 issue 化"的 issue 列表/JSON。openEMS/HFSS 两源
走可注入 runner：本服务不直接启动求解器，真机由调度层注入，单测注入
fake runner（无网络、无真机、确定性）。
"""

from __future__ import annotations

import importlib.metadata
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

_REGRESSION_METRIC = "s11_db_max_in_band"
_REGRESSION_TOLERANCE_DB = 1.0

#: 三源（稳定顺序）——fake 全量 / openEMS 冒烟抽检 / HFSS 周抽检。
SOURCES: tuple[str, ...] = ("fake", "openems", "hfss")

#: 可注入 runner 契约：runner(recipe_path_str) -> dict，至少含 ok。
_Runner = Callable[[str], dict[str, Any]]


def _golden_metric_lookup(
    golden: dict[str, Any] | None, model: Any
) -> dict[str, Any] | None:
    """golden 基线里查某模板的回归判据基值（XD-5 判据 5 的对照面）。

    命中条件：golden.baselines 中有该 model 且判据指标存在且为数值。
    返回 {"value": float, "run_id": pinned_run_id}；未命中 None。
    """
    if not golden:
        return None
    baselines = golden.get("baselines")
    values = baselines.get(model) if isinstance(baselines, dict) else None
    if not isinstance(values, dict):
        return None
    base = values.get(_REGRESSION_METRIC)
    if not isinstance(base, (int, float)) or isinstance(base, bool):
        return None
    return {"value": float(base),
            "run_id": str(golden.get("pinned_run_id") or "")}


def _baseline_run_ids(
    entries: list[dict[str, Any]] | None,
    regressions: list[dict[str, Any]] | None,
) -> list[str]:
    """XD-1（W3-B）：report run 的被比较/被解释 run id 集（sorted 去重）。

    边来源=调用方上下文（entries.baseline.run_id 与
    regressions[].baseline_run_id，扫描期已落盘的显式引用），不做目录名
    猜测（规格 §10.2.1）；零命中返回空列表（存在才写边）。
    """
    ids: set[str] = set()
    for entry in entries or []:
        baseline = entry.get("baseline")
        if isinstance(baseline, dict) and baseline.get("run_id"):
            ids.add(str(baseline["run_id"]))
    for reg in regressions or []:
        if reg.get("baseline_run_id"):
            ids.add(str(reg["baseline_run_id"]))
    return sorted(ids)


def _scan_recipe_files(
    recipe_files: list[Path],
    *,
    adapter: str,
    tolerance_db: float,
    golden: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """fake 全量扫描：validate + run_once + runs 索引历史对照。

    纯扫描——不创建 run 目录、不写 meta，供 nightly_regression 与
    nightly_multisource_regression 共用，保证两条路径的回归判定逐位一致。

    golden（XD-5）非 None 时：该模板在 golden.baselines 有判据指标基值
    则对照 golden（判定不随 runs 湖滚动），否则回退该模板的滚动索引
    历史（向后兼容钉：golden 覆盖不到的模板维持现状行为）。

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

        # 对照基线：golden（XD-5）优先，未命中回退同配方最近一次同通道 run
        golden_base = _golden_metric_lookup(golden, recipe.get("model"))
        if golden_base is not None:
            cur = metrics.get(_REGRESSION_METRIC)
            base = golden_base["value"]
            if cur is not None:
                delta = float(cur) - float(base)
                entry["baseline"] = {"source": "golden",
                                     "run_id": golden_base["run_id"],
                                     "base": base, "delta_db": round(delta, 3)}
                if delta > tolerance_db:  # s11 是 max_below 指标：升高=劣化
                    regressions.append({"recipe": rf.name,
                                        "metric": _REGRESSION_METRIC,
                                        "current": cur, "baseline": base,
                                        "delta_db": round(delta, 3),
                                        "baseline_run_id":
                                            golden_base["run_id"],
                                        "baseline_source": "golden"})
        else:
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
                                         "base": base,
                                         "delta_db": round(delta, 3)}
                    if delta > tolerance_db:  # s11 是 max_below 指标：升高=劣化
                        regressions.append({"recipe": rf.name,
                                            "metric": _REGRESSION_METRIC,
                                            "current": cur, "baseline": base,
                                            "delta_db": round(delta, 3),
                                            "baseline_run_id":
                                                prior["run_id"]})
        entries.append(entry)

    return entries, regressions


def nightly_regression(
    recipes_dir: str | Path = "recipes",
    *,
    adapter: str = "fake",
    tolerance_db: float = _REGRESSION_TOLERANCE_DB,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """全配方回归：validate+run → 对照基线 → diff 报告（XD-5 golden 优先）。

    基线解析（XD-5 判据 5 双态）：``baseline_path`` 显式给出时必须存在
    （缺失=程序性错误，error 信封不静默）；缺省 None 时咨询仓库缺省
    golden 路径（``default_baseline_path``），不存在→回退现行滚动索引，
    行为与 golden 面引入前逐位一致。
    """
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, write_meta

    root = Path(recipes_dir)
    if not root.exists():
        return error_envelope([f"配方目录不存在: {root}"])
    recipe_files = sorted(root.glob("*.yaml"))
    if not recipe_files:
        return error_envelope([f"{root} 下无配方"])

    if baseline_path is not None:
        golden = load_baseline(baseline_path)
        if golden is None:
            return error_envelope(
                [f"golden 基线文件不存在或不可解析: {baseline_path}"])
        baseline_mode = "golden"
    else:
        golden = load_baseline(default_baseline_path())
        baseline_mode = "golden" if golden else "rolling"

    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    entries, regressions = _scan_recipe_files(
        recipe_files, adapter=adapter, tolerance_db=tolerance_db,
        golden=golden)

    report = ok_envelope(
        run_id=run_id,
        run_dir=str(run_dir),
        adapter=adapter,
        baseline_mode=baseline_mode,
        n_recipes=len(recipe_files),
        n_done=sum(1 for e in entries if e.get("status") == "done"),
        n_regressions=len(regressions),
        regressions=regressions,
        entries=entries,
    )
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
                    "n_regressions": report["n_regressions"]}},
        derived_from=_baseline_run_ids(entries, regressions),
        edge_kind="report")
    return report


# ---------------------------------------------------------------------------
# §10.20 补强⑫ — 三源夜间回归 + G14 成本表 + 红即 issue 化
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
    except Exception as exc:  # runner 是外部注入点：失败记为抽检失败
        return error_envelope(f"{type(exc).__name__}: {exc}")
    if not isinstance(raw, dict):
        return error_envelope(f"runner 返回非 dict: {type(raw).__name__}")
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
            # 消费兼容读（契约 §3 按序回退）：error（注入 runner 遗留形）→
            # errors[0]（error_envelope 行）
            _errs = res.get("errors")
            _msg = _errs[0] if isinstance(_errs, list) and _errs else None
            row.setdefault(
                "error",
                str(res.get("error") or _msg or res.get("errors") or "unknown"))
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
    """三源夜间回归（§10.20 ⑫）：fake 全量 + openEMS 冒烟 + HFSS 周抽检。

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
        return error_envelope(errors, )

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
    report: dict[str, Any] = ok_envelope(
        algorithm="nightly_multisource_regression",
        status=status,
        run_id=run_id,
        run_dir=str(run_dir),
        adapter=adapter,
        tolerance_db=tolerance_db,
        n_recipes=len(recipe_files),
        n_done=n_done,
        n_regressions=len(regressions),
        n_sources=len(SOURCES),
        n_sources_pass=statuses.count("pass"),
        n_sources_fail=statuses.count("fail"),
        n_sources_skipped=statuses.count("skipped"),
        sources=sources,
        regressions=regressions,
        issues=issues,
        issue_file=str(issue_file),
        cost_table=ledger.rollup(),
    )
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
                    "n_sources_pass": report["n_sources_pass"]}},
        derived_from=_baseline_run_ids(entries, regressions),
        edge_kind="report")
    return report


# ---------------------------------------------------------------------------
# XD-5（sa_specs2 §八）——metrics.json 标准 + golden 基线钉定/对照/漂移
# ---------------------------------------------------------------------------

#: metrics.json 标准 schema 版本（<量>_<单位> 命名规范面随此版本走）。
STANDARD_METRICS_SCHEMA_VERSION = "1"

#: 标准指标文件名（run_dir/metrics.json；与 sim_ci_report.json 互不挤占）。
STANDARD_METRICS_FILENAME = "metrics.json"

#: golden 基线文件 schema 串（knowledge/simci_baseline.yaml）。
BASELINE_SCHEMA = "simci_baseline/v1"

#: 仓库缺省 golden 落点（src/rfauto/service/ → parents[3] = 仓库根）。
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: 缺省锚注册表路径（49 锚 quantity 名集=指标名对齐面）。
_DEFAULT_ANCHORS_YAML = _REPO_ROOT / "knowledge" / "anchors.yaml"


def default_baseline_path() -> Path:
    """仓库缺省 golden 基线路径（knowledge/simci_baseline.yaml）。"""
    return _REPO_ROOT / "knowledge" / "simci_baseline.yaml"


def anchor_metric_names(anchors_path: str | Path | None = None) -> list[str]:
    """锚注册表 quantity 名集（排序；读 knowledge/anchors.yaml，best-effort）。

    anchors.yaml 缺失/不可解析 → 空表（对齐面退化为全 unanchored，如实，
    #105：观测面不阻塞写面）。同名去重（多锚可同名 quantity，如 dev_pct 族）。
    """
    import yaml

    path = Path(anchors_path) if anchors_path else _DEFAULT_ANCHORS_YAML
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        anchors = data.get("anchors") or []
        names = set()
        for a in anchors:
            if isinstance(a, dict):
                q = a.get("quantity")
                if isinstance(q, dict) and q.get("name"):
                    names.add(str(q["name"]))
        return sorted(names)
    except Exception:  # yaml OSError/ParseError 等——对齐面不阻塞写面
        return []


def write_standard_metrics(
    run_dir: str | Path,
    stage: str,
    metrics: dict[str, Any],
    *,
    run_id: str = "",
    adapter: str = "",
    template: str = "",
    gate: dict[str, Any] | None = None,
    anchors_path: str | Path | None = None,
) -> dict[str, Any]:
    """写 run_dir/metrics.json 标准 metrics 文件（XD-5 判据 4 对齐面）。

    schema：{schema_version:"1", run_id, stage, adapter, template,
    metrics, metric_alignment{anchored,unanchored}, gate_digest,
    created_at}——指标名优先对齐锚注册表 quantity 名集；不在锚名集的键
    如实进 unanchored（新指标命名规范：<量>_<单位>，登记后进锚注册表）。

    gate 给定时 gate_digest=sha256(canonical(gate))，否则 null。
    返回 ok 信封（path/n_metrics/anchored/unanchored/alignment_ratio）；
    metrics 非 dict / run_dir 不可写 → error 信封。
    """
    from rfauto.infra.dag_cache import canonical_json, sha256_text

    base = Path(run_dir)
    if not isinstance(metrics, dict):
        return error_envelope(
            [f"metrics 必须是 dict，得到 {type(metrics).__name__}"])
    anchored = anchor_metric_names(anchors_path)
    anchored_set = set(anchored)
    keys = sorted(str(k) for k in metrics)
    hit = [k for k in keys if k in anchored_set]
    miss = [k for k in keys if k not in anchored_set]
    payload: dict[str, Any] = {
        "schema_version": STANDARD_METRICS_SCHEMA_VERSION,
        "run_id": str(run_id),
        "stage": str(stage),
        "adapter": str(adapter),
        "template": str(template),
        "metrics": {str(k): v for k, v in metrics.items()},
        "metric_alignment": {"anchored": hit, "unanchored": miss},
        "gate_digest": (sha256_text(canonical_json(gate))
                        if gate is not None else None),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        base.mkdir(parents=True, exist_ok=True)
        dest = base / STANDARD_METRICS_FILENAME
        dest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True,
                       default=str),
            encoding="utf-8")
    except OSError as exc:
        return error_envelope([f"metrics.json 写入失败: {exc}"])
    ratio = (round(len(hit) / len(keys), 4) if keys else None)
    return ok_envelope(
        path=str(dest), schema_version=STANDARD_METRICS_SCHEMA_VERSION,
        n_metrics=len(keys), anchored=hit, unanchored=miss,
        alignment_ratio=ratio, gate_digest=payload["gate_digest"])


def read_standard_metrics(run_dir: str | Path) -> dict[str, Any]:
    """读 run_dir/metrics.json（schema_version 校验；缺失/损坏 → error 信封）。"""
    path = Path(run_dir) / STANDARD_METRICS_FILENAME
    if not path.is_file():
        return error_envelope([f"metrics.json 不存在: {path}"])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return error_envelope([f"metrics.json 不可读: {exc}"])
    if not isinstance(data, dict):
        return error_envelope(["metrics.json 必须是 JSON 对象"])
    if str(data.get("schema_version")) != STANDARD_METRICS_SCHEMA_VERSION:
        return error_envelope(
            [f"schema_version 不支持: {data.get('schema_version')!r}"
             f"（当前标准 {STANDARD_METRICS_SCHEMA_VERSION}）"])
    return ok_envelope(path=str(path), data=data)


def latest_channel_baselines(
    adapter: str = "fake",
    *,
    db_path: str | Path | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """同通道最近 run 的逐模板指标图（XD-5 判读 digest 的原料面）。

    runs 索引按 timestamp 倒序扫（query_runs），status=done 且 metrics
    非空的 run，每模板取最新一条；digest=sha256(canonical({model: metrics}))。
    索引库缺失/查询失败 → 原样透传 error 信封。
    """
    from rfauto.infra.dag_cache import canonical_json, sha256_text
    from rfauto.service.runs_stats import query_runs

    r = query_runs(db_path, adapter=adapter, limit=limit)
    if not r.get("ok"):
        return r
    baselines: dict[str, dict[str, Any]] = {}
    model_run_ids: dict[str, str] = {}
    pinned_run_id = ""
    pinned_at = ""
    for run in r.get("runs", []):
        m = run.get("metrics")
        if not isinstance(m, dict) or not m:
            continue
        if str(run.get("status") or "") != "done":
            continue
        model = str(run.get("model") or "")
        if model and model not in baselines:
            baselines[model] = m
            model_run_ids[model] = str(run.get("run_id") or "")
        if not pinned_run_id:
            pinned_run_id = str(run.get("run_id") or "")
            pinned_at = str(run.get("timestamp") or "")
    digest = sha256_text(canonical_json(baselines))
    return ok_envelope(
        adapter=adapter, baselines=baselines, model_run_ids=model_run_ids,
        n_models=len(baselines), metrics_digest=digest,
        pinned_run_id=pinned_run_id, pinned_at=pinned_at)


def load_baseline(
    baseline_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """读 golden 基线（缺失/损坏/schema 不符 → None；调用方按双态处理）。"""
    import yaml

    path = Path(baseline_path) if baseline_path else default_baseline_path()
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("schema")) != BASELINE_SCHEMA:
        return None
    return data


def _metric_deltas(
    golden: dict[str, Any], current: dict[str, Any]
) -> tuple[list[dict[str, Any]], float]:
    """golden×current 共有模型共有指标的数值漂移表 + 最大绝对漂移。"""
    gb = golden.get("baselines") or {}
    cb = current.get("baselines") or {}
    rows: list[dict[str, Any]] = []
    max_abs = 0.0
    for model in sorted(set(gb) & set(cb)):
        gv, cv = gb[model], cb[model]
        if not isinstance(gv, dict) or not isinstance(cv, dict):
            continue
        for metric in sorted(set(gv) & set(cv)):
            a, b = gv[metric], cv[metric]
            numeric = (isinstance(a, (int, float))
                       and isinstance(b, (int, float))
                       and not isinstance(a, bool) and not isinstance(b, bool))
            if numeric:
                delta = float(b) - float(a)
                max_abs = max(max_abs, abs(delta))
                rows.append({"model": model, "metric": metric,
                             "golden": float(a), "current": float(b),
                             "delta": round(delta, 6)})
    return rows, max_abs


def pin_baseline(
    *,
    adapter: str = "fake",
    channel: str | None = None,
    db_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    update: bool = False,
) -> dict[str, Any]:
    """把最近同通道 run 的判读 digest 钉成 golden 基线（XD-5 pin 动作）。

    已有 golden 且未显式 ``update=True`` → 拒绝（error 信封；ORFS
    make update_ok 语义：基线更新必须显式留痕，防静默漂基线）。update
    信封携带 previous_metrics_digest 与旧→新 digest 审计串（commit
    message 模板，提交归调用方工作流——服务层零 git 写面）。
    """
    import yaml

    from rfauto.infra.dag_cache import env_fingerprint

    dest = Path(baseline_path) if baseline_path else default_baseline_path()
    previous_digest = ""
    if dest.is_file():
        old = load_baseline(dest)
        if old is not None:
            if not update:
                return error_envelope(
                    [f"golden 基线已存在: {dest}"
                     "（更新必须显式 update=True 重钉，#325 留痕铁律）"],
                    baseline_path=str(dest),
                    previous_metrics_digest=str(
                        old.get("metrics_digest") or ""))
            previous_digest = str(old.get("metrics_digest") or "")

    cur = latest_channel_baselines(adapter, db_path=db_path)
    if not cur.get("ok"):
        return cur
    if cur.get("n_models", 0) == 0:
        return error_envelope(
            [f"通道 {adapter} 无可钉基线（索引无 status=done 且带指标的 run）"],
            adapter=adapter)

    chan = channel or adapter
    git_sha = str(env_fingerprint(_REPO_ROOT).get("git_sha") or "")
    try:
        package_version = importlib.metadata.version("rfauto")
    except Exception:
        package_version = ""
    record: dict[str, Any] = {
        "schema": BASELINE_SCHEMA,
        "pinned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pinned_run_id": cur["pinned_run_id"],
        "adapter": adapter,
        "channel": chan,
        "metrics_digest": cur["metrics_digest"],
        "baselines": cur["baselines"],
        "model_run_ids": cur["model_run_ids"],
        "tool_versions": {"engine": "", "package": package_version},
        "git_sha": git_sha,
    }
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            yaml.safe_dump(record, allow_unicode=True, sort_keys=True),
            encoding="utf-8")
    except OSError as exc:
        return error_envelope([f"golden 基线写入失败: {exc}"])

    action = "update" if update else "pin"
    if update:
        audit_line = (f"simci golden update: {previous_digest[:12]}… -> "
                      f"{record['metrics_digest'][:12]}…"
                      f"（channel={chan}）")
    else:
        audit_line = (f"simci golden pin: {record['metrics_digest'][:12]}…"
                      f"（channel={chan}）")
    return ok_envelope(
        baseline_path=str(dest), action=action,
        pinned_run_id=record["pinned_run_id"], channel=chan,
        metrics_digest=record["metrics_digest"],
        previous_metrics_digest=previous_digest or None,
        n_models=len(record["baselines"]),
        git_sha=git_sha, update_audit=audit_line)


def compare_baseline(
    *,
    adapter: str = "fake",
    channel: str | None = None,
    db_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """当前同通道判读 digest 对照 golden（XD-5 compare 动作；零写面）。

    outcome：match=逐位一致；drift=digest 不一致（deltas 附量化）；
    missing_golden=金样例缺失（双态钉：无 golden 环境回退滚动是合法态）。
    """
    golden = load_baseline(baseline_path)
    if golden is None:
        return ok_envelope(
            outcome="missing_golden", adapter=adapter,
            channel=channel or adapter,
            baseline_path=str(baseline_path or default_baseline_path()),
            note="golden 基线缺失（回退滚动索引语义，pin 后进入对照态）")
    current = latest_channel_baselines(adapter, db_path=db_path)
    if not current.get("ok"):
        return error_envelope(
            current.get("errors") or ["runs 索引查询失败"], outcome="error")
    digest_match = (str(golden.get("metrics_digest") or "")
                    == current["metrics_digest"])
    deltas, max_abs = _metric_deltas(golden, current)
    return ok_envelope(
        outcome="match" if digest_match else "drift",
        digest_match=digest_match,
        metrics_digest=current["metrics_digest"],
        golden_metrics_digest=str(golden.get("metrics_digest") or ""),
        pinned_run_id=str(golden.get("pinned_run_id") or ""),
        channel=str(golden.get("channel") or channel or adapter),
        n_models_current=current["n_models"],
        n_models_golden=len(golden.get("baselines") or {}),
        deltas=deltas, max_abs_delta=max_abs,
        n_deltas=len(deltas))


def baseline_drift(
    *,
    adapter: str = "fake",
    channel: str | None = None,
    db_path: str | Path | None = None,
    baseline_path: str | Path | None = None,
    tolerance: float = 0.0,
) -> dict[str, Any]:
    """golden→当前逐指标漂移量化（XD-5 drift 动作；超限=显式 verdict）。

    判超限：任一共有指标 |delta| > tolerance，**或** digest 不一致
    （模型集/非数值面变化无法被数值漂移表覆盖——如实计入超限，不放过）。
    outcome：within / exceeded / missing_golden / error。
    """
    golden = load_baseline(baseline_path)
    if golden is None:
        return ok_envelope(
            outcome="missing_golden", adapter=adapter,
            channel=channel or adapter,
            baseline_path=str(baseline_path or default_baseline_path()),
            note="golden 基线缺失（先 pin 再 drift）")
    current = latest_channel_baselines(adapter, db_path=db_path)
    if not current.get("ok"):
        return error_envelope(
            current.get("errors") or ["runs 索引查询失败"], outcome="error")
    digest_match = (str(golden.get("metrics_digest") or "")
                    == current["metrics_digest"])
    deltas, max_abs = _metric_deltas(golden, current)
    exceeded = [d for d in deltas if abs(d["delta"]) > float(tolerance)]
    if not digest_match or exceeded:
        reason = ("逐指标漂移超限" if exceeded
                  else "digest 不一致（模型集或非数值面变化）")
        return ok_envelope(
            outcome="exceeded", digest_match=digest_match,
            tolerance=float(tolerance), max_abs_delta=max_abs,
            n_exceeded=len(exceeded), exceeded=exceeded, deltas=deltas,
            reason=reason, metrics_digest=current["metrics_digest"],
            golden_metrics_digest=str(golden.get("metrics_digest") or ""))
    return ok_envelope(
        outcome="within", digest_match=True, tolerance=float(tolerance),
        max_abs_delta=max_abs, n_exceeded=0, exceeded=[], deltas=deltas,
        reason="", metrics_digest=current["metrics_digest"],
        golden_metrics_digest=str(golden.get("metrics_digest") or ""))
