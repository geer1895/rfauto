"""agent_bench：AgentBench 智能体基准内核（v1.2 新增）。

rfauto 自己的智能体基准——任务集 + 两轴打分 + 公开/私有双集（方案 §4 WP3.7，
金标集骨架 goldset_service 之上的智能体任务层）：

- 轴① 任务抽象：方法与工具选择是否正确（复用 goldset_service.score_trajectory
  的 TSA/FCA，宏平均为 abstraction 分）
- 轴② 执行：工件生成齐全性（expected.artifacts）+ 数值 vs ground truth
  （expected.numeric 闭式解/HFSS 仲裁值，tol_pct 相对容差）
- 公开/私有双集防污染（Gridy 经验）：公开集随库
  （tests/gold/agentbench_public.yaml，6.6 基准集开源的智能体侧素材）；
  私有集不入库——显式路径或环境变量 RFAUTO_AGENTBENCH_PRIVATE_SET 注入，
  两集任务 id 交集非空即判污染 FAIL
- 回归门：每次 runtime/协议变更（WP3.1/3.2/3.5）一键跑（与
  goldset_service.run_goldset_regression 同构：协议面 sha256 + 工具面覆盖 +
  两轴阈值 + 防空转）

铁律 7：本模块只做"比较"——轨迹与数值均由调用方（确定性内核产出）注入，
基准自身不产生任何物理数字；公开集 ground truth 逐任务引用
docs/rf_template_references.md（官方例验收基准/闭式 sanity/HFSS 仲裁），
provenance 可溯。真实 runtime/LLM 通道由调用方经 trajectory_provider 注入——
门自身不发任何网络请求（#139：测试一律 monkeypatch 钉住通道）。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.goldset_service import (
    goldset_expected_tools,
    protocol_surface,
    score_trajectory,
)

AGENTBENCH_SCHEMA_VERSION = 1
PUBLIC_SET_FILENAME = "agentbench_public.yaml"
PRIVATE_SET_ENV = "RFAUTO_AGENTBENCH_PRIVATE_SET"

DEFAULT_MIN_ABSTRACTION = 0.9
DEFAULT_MIN_EXECUTION = 0.8

_PRIVATE_STATUS_LOADED = "loaded"
_PRIVATE_STATUS_NOT_CONFIGURED = "not_configured"
_PRIVATE_STATUS_MISSING = "missing"
_PRIVATE_STATUS_INVALID = "invalid"


def default_public_path() -> Path:
    """公开集缺省路径（tests/gold/agentbench_public.yaml，随库）。"""
    return (Path(__file__).resolve().parent.parent.parent.parent
            / "tests" / "gold" / PUBLIC_SET_FILENAME)


# ---------------------------------------------------------------------------
# 任务集加载（公开/私有双集 + 防污染）
# ---------------------------------------------------------------------------

def load_bench_set(path: str | Path | None = None) -> dict[str, Any]:
    """加载单集（缺省公开集；结构自检：goldset 基础校验 + AgentBench 专属字段）。

    AgentBench 专属：family 必填（任务族：模板渲染/诊断根因/修端口/
    跑通战役…）；expected.artifacts 必须是字符串序列；expected.numeric
    每条必须含 metric/value/tol_pct（数值 vs ground truth 判据）。
    """
    from rfauto.service.goldset_service import load_goldset

    base = load_goldset(path or default_public_path())
    if not base.get("ok"):
        return base
    errors: list[str] = []
    for task in base.get("tasks") or []:
        tid = task.get("id", "?")
        if not str(task.get("family") or "").strip():
            errors.append(f"{tid} 缺字段 family")
        expected = task.get("expected") or {}
        artifacts = expected.get("artifacts")
        if artifacts is not None and (
                not isinstance(artifacts, (list, tuple))
                or not all(isinstance(a, str) and a.strip() for a in artifacts)):
            errors.append(f"{tid} expected.artifacts 必须是非空字符串序列")
        numerics = expected.get("numeric")
        if numerics is not None:
            if not isinstance(numerics, (list, tuple)):
                errors.append(f"{tid} expected.numeric 必须是序列")
            else:
                for i, item in enumerate(numerics):
                    if not isinstance(item, Mapping):
                        errors.append(f"{tid} expected.numeric[{i}] 必须是映射")
                        continue
                    for field in ("metric", "value", "tol_pct"):
                        if field not in item:
                            errors.append(f"{tid} expected.numeric[{i}] 缺字段 {field}")
                    tol = item.get("tol_pct")
                    if isinstance(tol, (int, float)) and tol < 0:
                        errors.append(f"{tid} expected.numeric[{i}] tol_pct 不能为负")
                    if "value" in item and not isinstance(item.get("value"), (int, float)):
                        errors.append(f"{tid} expected.numeric[{i}] value 必须是数值")
    if errors:
        return {"ok": False, "errors": errors, "path": str(path)}
    return base


def _resolve_private_path(private_path: str | Path | None) -> str | Path | None:
    """私有集路径解析：显式参数 > 环境变量 > 未配置。"""
    if private_path is not None:
        return private_path
    env = os.environ.get(PRIVATE_SET_ENV, "").strip()
    return env or None


def load_bench_sets(
    public_path: str | Path | None = None,
    private_path: str | Path | None = None,
) -> dict[str, Any]:
    """公开/私有双集加载（防污染：id 交集非空即 FAIL；私有集配置了就必须可用）。

    私有集状态：loaded / not_configured（未给路径且环境变量为空）/
    missing（解析到路径但文件不存在）/ invalid（存在但结构不合法）。
    防静默降级：只要解析到私有集路径，加载失败就是硬错误（ok=False）。
    """
    public = load_bench_set(public_path or default_public_path())
    errors: list[str] = []
    if not public.get("ok"):
        errors.extend(str(e) for e in public.get("errors") or ["公开集加载失败"])

    resolved = _resolve_private_path(private_path)
    private: dict[str, Any] | None = None
    if resolved is None:
        status = _PRIVATE_STATUS_NOT_CONFIGURED
    else:
        p = Path(resolved)
        if not p.exists():
            status = _PRIVATE_STATUS_MISSING
            errors.append(f"私有集已配置但不存在: {p}")
        else:
            private = load_bench_set(p)
            if not private.get("ok"):
                status = _PRIVATE_STATUS_INVALID
                errors.extend(str(e) for e in private.get("errors") or ["私有集结构不合法"])
            else:
                status = _PRIVATE_STATUS_LOADED

    overlap: list[str] = []
    if public.get("ok") and private is not None and private.get("ok"):
        public_ids = {t.get("id") for t in public.get("tasks") or []}
        private_ids = {t.get("id") for t in private.get("tasks") or []}
        overlap = sorted(str(i) for i in (public_ids & private_ids))
        if overlap:
            errors.append(
                f"双集污染：公开/私有任务 id 交集非空（{len(overlap)} 个）→ {overlap[:5]}")

    return {
        "ok": not errors,
        "errors": errors,
        "public": public,
        "private": private,
        "private_status": status,
        "private_path": str(resolved) if resolved is not None else None,
        "overlap_ids": overlap,
    }


# ---------------------------------------------------------------------------
# 两轴打分（轴① 任务抽象 / 轴② 执行）
# ---------------------------------------------------------------------------

def _artifact_score(task: Mapping[str, Any],
                    produced: Sequence[Any] | None) -> tuple[float, list[str]]:
    """工件齐全性：expected.artifacts ∩ produced / |expected.artifacts|。

    未声明工件 →（1.0, []）（该任务执行轴不考核工件维度）。
    """
    expected = (task.get("expected") or {}).get("artifacts")
    if not expected:
        return 1.0, []
    produced_set = {str(a).strip() for a in (produced or []) if str(a).strip()}
    missing = [str(a) for a in expected if str(a).strip() not in produced_set]
    hit = len(expected) - len(missing)
    return hit / len(expected), missing


def _numeric_score(task: Mapping[str, Any],
                   produced: Mapping[str, Any] | None) -> tuple[float, list[str]]:
    """数值 vs ground truth：|produced - truth| ≤ tol_pct/100 × |truth|。

    produced 缺 metric / 非数值 / 超容差都判 0；未声明数值 →（1.0, []）。
    ground truth 数值与容差来自任务集声明（闭式解/HFSS 仲裁，provenance
    引 rf_template_references），本函数只做比较、不产生数字（铁律 7）。
    """
    expected = (task.get("expected") or {}).get("numeric")
    if not expected:
        return 1.0, []
    produced = produced if isinstance(produced, Mapping) else {}
    failed: list[str] = []
    for item in expected:
        metric = str(item.get("metric") or "")
        truth = item.get("value")
        tol_pct = item.get("tol_pct")
        got = produced.get(metric)
        if not metric or not isinstance(truth, (int, float)) or not isinstance(tol_pct, (int, float)):
            failed.append(metric or f"#{len(failed)}")
            continue
        if isinstance(got, bool) or not isinstance(got, (int, float)):
            failed.append(metric)
            continue
        tol_abs = float(tol_pct) / 100.0 * abs(float(truth))
        ok = (got == truth) if tol_abs == 0.0 else abs(float(got) - float(truth)) <= tol_abs
        if not ok:
            failed.append(metric)
    return (len(expected) - len(failed)) / len(expected), failed


def score_agent_task(task: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """单任务两轴打分（确定性、无 LLM、无网络）。

    record 形状（埋点打分的轨迹记录契约）：
      {"trajectory": [{"tool","args"}, ...],          # 轴① 依据
       "artifacts": ["s_params", ...],                # 轴② 工件齐全性
       "numeric": {"f0_ghz": 2.16, ...}}              # 轴② 数值 vs ground truth
    轴① abstraction = (TSA + FCA) / 2（goldset 子序列/子集匹配语义不变）；
    轴② execution = 声明维度的宏平均（只考核任务声明了的维度）。
    """
    traj = record.get("trajectory") or []
    tsa_fca = score_trajectory(dict(task), list(traj))
    abstraction = (tsa_fca["tsa"] + tsa_fca["fca"]) / 2.0
    artifact, missing = _artifact_score(task, record.get("artifacts"))
    numeric, failed = _numeric_score(task, record.get("numeric"))

    facets: list[float] = []
    if (task.get("expected") or {}).get("artifacts"):
        facets.append(artifact)
    if (task.get("expected") or {}).get("numeric"):
        facets.append(numeric)
    execution = sum(facets) / len(facets) if facets else 1.0

    return {
        "id": task.get("id"),
        "tsa": tsa_fca["tsa"],
        "fca": tsa_fca["fca"],
        "abstraction": abstraction,
        "artifact": artifact,
        "numeric": numeric,
        "execution": execution,
        "artifact_missing": missing,
        "numeric_failed": failed,
    }


def _macro(results: list[Mapping[str, Any]], key: str) -> float:
    scored = [r for r in results if key in r]
    if not scored:
        return 0.0
    return sum(float(r[key]) for r in scored) / len(scored)


def _score_one_set(bench_set: Mapping[str, Any],
                   records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """单集评测：逐任务两轴打分 + 宏平均（TSA/FCA/abstraction/execution）。

    传入记录须已按本集 id 过滤（evaluate_agentbench 负责分集与未知 id 归集）；
    记录形状不合法记 error 条目，不中断整体评测。
    """
    by_id = {t["id"]: t for t in bench_set.get("tasks") or []}
    results: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, Mapping):
            results.append({"id": None, "error": "记录项必须是映射"})
            continue
        task = by_id.get(item.get("id"))
        if task is None:
            results.append({"id": item.get("id"), "error": "未知任务"})
            continue
        traj = item.get("trajectory")
        if traj is not None and not isinstance(traj, (list, tuple)):
            results.append({"id": item.get("id"), "error": "trajectory 必须是序列"})
            continue
        if any(not isinstance(c, Mapping) for c in traj or []):
            results.append({"id": item.get("id"), "error": "trajectory 项必须是映射"})
            continue
        if not isinstance(item.get("artifacts", []), (list, tuple)):
            results.append({"id": item.get("id"), "error": "artifacts 必须是序列"})
            continue
        results.append(score_agent_task(task, item))
    scored = [r for r in results if "error" not in r]
    n = max(len(scored), 1)
    return {
        "path": str(bench_set.get("path")),
        "n_tasks": len(by_id),
        "n_scored": len(scored),
        "tsa": sum(r["tsa"] for r in scored) / n,
        "fca": sum(r["fca"] for r in scored) / n,
        "abstraction": sum(r["abstraction"] for r in scored) / n,
        "execution": sum(r["execution"] for r in scored) / n,
        "axis_detail": {
            "artifact": _macro(scored, "artifact"),
            "numeric": _macro(scored, "numeric"),
        },
        "results": results,
    }


def evaluate_agentbench(
    records: Sequence[Mapping[str, Any]],
    *,
    public_path: str | Path | None = None,
    private_path: str | Path | None = None,
) -> dict[str, Any]:
    """智能体基准评测（纯打分，无门判定）：公开/私有双集分别报告 + 合并宏平均。

    records = [{"id", "trajectory", "artifacts", "numeric"}, ...]（埋点记录，
    双集 id 可混装，按集归属拆分）；不属于任何集的 id 进 unknown_ids。
    双集结构/污染问题 → ok=False 与错误清单。
    """
    sets = load_bench_sets(public_path, private_path)
    if not sets.get("ok"):
        return {"ok": False, "errors": list(sets.get("errors") or []),
                "private_status": sets.get("private_status")}
    public_ids = {t["id"] for t in sets["public"].get("tasks") or []}
    private_ids: set[Any] = set()
    if sets.get("private") is not None:
        private_ids = {t["id"] for t in sets["private"].get("tasks") or []}

    pub_records: list[Mapping[str, Any]] = []
    priv_records: list[Mapping[str, Any]] = []
    unknown: list[str] = []
    for item in records:
        tid = item.get("id") if isinstance(item, Mapping) else None
        if tid in public_ids:
            pub_records.append(item)
        elif tid in private_ids:
            priv_records.append(item)
        else:
            unknown.append(str(tid))

    public_report = _score_one_set(sets["public"], pub_records)
    private_report: dict[str, Any] | None = None
    if sets.get("private") is not None:
        private_report = _score_one_set(sets["private"], priv_records)

    all_scored = [r for r in public_report["results"] if "error" not in r]
    if private_report is not None:
        all_scored += [r for r in private_report["results"] if "error" not in r]
    combined = {
        "n_scored": len(all_scored),
        "abstraction": _macro(all_scored, "abstraction"),
        "execution": _macro(all_scored, "execution"),
    }
    return {
        "ok": True,
        "schema_version": AGENTBENCH_SCHEMA_VERSION,
        "private_status": sets.get("private_status"),
        "contamination": {"overlap_ids": sets.get("overlap_ids") or []},
        "unknown_ids": unknown,
        "sets": {"public": public_report, "private": private_report},
        "combined": combined,
    }


# ---------------------------------------------------------------------------
# 回归门（runtime/协议变更一键回归；与 goldset 回归门同构）
# ---------------------------------------------------------------------------

def reference_agentbench_provider(task: Mapping[str, Any]) -> dict[str, Any]:
    """离线参考提供器：回放任务期望（轨迹+工件+声明 ground truth 数值）。

    仅作门自身的正控（证明任务集与两轴打分器自洽、门能跑通），不构成对
    真实 agent 质量的判据。确定性、无网络、无 LLM。
    """
    expected = task.get("expected") or {}
    numeric = {str(n.get("metric")): n.get("value")
               for n in expected.get("numeric") or [] if n.get("metric")}
    return {
        "trajectory": [{"tool": str(c.get("tool") or ""),
                        "args": dict(c.get("args") or {})}
                       for c in expected.get("calls") or []],
        "artifacts": list(expected.get("artifacts") or []),
        "numeric": numeric,
    }


def run_agentbench_regression(
    records: Sequence[Mapping[str, Any]] | None = None,
    *,
    trajectory_provider: Callable[[Mapping[str, Any]], Any] | None = None,
    public_path: str | Path | None = None,
    private_path: str | Path | None = None,
    runtime_tools: Iterable[str] | None = None,
    min_abstraction: float = DEFAULT_MIN_ABSTRACTION,
    min_execution: float = DEFAULT_MIN_EXECUTION,
    require_private: bool = False,
    require_full_coverage: bool = True,
) -> dict[str, Any]:
    """AgentBench 回归门：双集加载（防污染）→ 协议面 → 覆盖 → 两轴阈值。

    参数：
      records / trajectory_provider —— 埋点记录或逐任务提供器（LLM/agent
          通道注入点；provider 返回序列视为轨迹，返回映射视为完整记录）；
      public_path/private_path —— 双集路径（私有集缺省走
          RFAUTO_AGENTBENCH_PRIVATE_SET）；
      runtime_tools —— 当前 runtime 工具名；给定时校验双集期望工具面
          是否被完全覆盖（协议变更回归，与 goldset 门同构）；
      min_abstraction/min_execution —— 两轴阈值；
      require_private —— True 时私有集未配置/不可用即 FAIL（终评口径）；
      require_full_coverage —— 记录必须覆盖全部已加载任务（默认是）。

    防空转：双集加载失败 / 记录与提供器均缺 / 覆盖为零或含未知 id /
    require_private 而私有集缺席 → 直接 FAIL，绝不空跑绿。
    """
    sets = load_bench_sets(public_path, private_path)
    expected_tools: list[str] = []
    n_tasks = 0
    if sets["public"].get("ok"):
        expected_tools = goldset_expected_tools(sets["public"])
        n_tasks += len(sets["public"].get("tasks") or [])
    if sets.get("private") is not None and sets["private"].get("ok"):
        expected_tools = sorted(set(expected_tools)
                                | set(goldset_expected_tools(sets["private"])))
        n_tasks += len(sets["private"].get("tasks") or [])
    expected_protocol = protocol_surface(expected_tools)

    runtime_protocol: dict[str, Any] | None = None
    missing_tools: list[str] = []

    def _result(ok: bool, reasons: list[str], *,
                errors: list[str] | None = None,
                n_scored: int = 0,
                report: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": ok,
            "gate": "PASS" if ok else "FAIL",
            "schema_version": AGENTBENCH_SCHEMA_VERSION,
            "private_status": sets.get("private_status"),
            "n_tasks": n_tasks,
            "n_scored": n_scored,
            "expected_protocol": expected_protocol,
            "runtime_protocol": runtime_protocol,
            "missing_tools": missing_tools,
            "min_abstraction": float(min_abstraction),
            "min_execution": float(min_execution),
            "report": report,
            "reasons": reasons,
            "errors": errors if errors is not None else ([] if ok else list(reasons)),
        }

    if not sets.get("ok"):
        return _result(False, ["双集加载失败"], errors=list(sets.get("errors") or []))
    if require_private and sets.get("private") is None:
        return _result(False, [
            f"require_private=True 但私有集未配置"
            f"（给 --private-set 或环境变量 {PRIVATE_SET_ENV}）"])
    if n_tasks == 0:
        return _result(False, ["任务集为空：拒绝空跑（防空转）"])

    if runtime_tools is not None:
        if isinstance(runtime_tools, (str, bytes)):
            return _result(False, ["runtime_tools 必须是工具名序列，不是字符串"])
        try:
            runtime_protocol = protocol_surface(runtime_tools)
        except TypeError as exc:
            return _result(False, [f"runtime_tools 非法: {exc}"])
        runtime_set = set(runtime_protocol["tools"])
        missing_tools = [t for t in expected_protocol["tools"] if t not in runtime_set]
        if missing_tools:
            return _result(False, [
                f"协议面回归：runtime 缺基准期望工具 {len(missing_tools)} 个 "
                f"→ {missing_tools[:5]}"])

    if trajectory_provider is not None:
        provided: list[Mapping[str, Any]] = []
        for bench_set in (sets["public"], sets.get("private")):
            if bench_set is None:
                continue
            for task in bench_set.get("tasks") or []:
                try:
                    produced = trajectory_provider(task)
                except Exception as exc:  # 提供器（LLM/agent 通道）异常即门红
                    return _result(False, [
                        f"轨迹提供器异常（task={task.get('id')}）: {exc}"])
                if isinstance(produced, Mapping):
                    record: dict[str, Any] = dict(produced)
                elif isinstance(produced, (list, tuple)):
                    record = {"trajectory": list(produced)}
                else:
                    return _result(False, [
                        f"轨迹提供器返回类型非法（task={task.get('id')}）"])
                record.setdefault("id", task.get("id"))
                provided.append(record)
        items: Sequence[Mapping[str, Any]] = provided
    elif records is not None:
        if not isinstance(records, (list, tuple)):
            return _result(False, ["records 必须是序列"])
        items = list(records)
        if not items:
            return _result(False, ["记录为空：拒绝空跑（防空转）"])
    else:
        return _result(False, [
            "未提供 records 或 trajectory_provider：拒绝空跑（防空转）"])

    known_ids = {t["id"] for t in sets["public"].get("tasks") or []}
    if sets.get("private") is not None:
        known_ids |= {t["id"] for t in sets["private"].get("tasks") or []}
    seen: set[Any] = set()
    unknown: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            return _result(False, ["记录项必须是映射 {id, trajectory, ...}"])
        tid = item.get("id")
        if tid in known_ids:
            seen.add(tid)
        else:
            unknown.append(str(tid))
    if unknown:
        return _result(False, [f"记录含未知任务 id: {unknown[:5]}"], n_scored=len(seen))
    if not seen:
        return _result(False, ["记录未覆盖任何基准任务（防空转）"])
    if require_full_coverage and seen != known_ids:
        absent = sorted(known_ids - seen)
        return _result(False, [
            f"记录未覆盖全部基准任务：缺 {len(absent)} 个 {absent[:5]}"],
            n_scored=len(seen))

    report = evaluate_agentbench(items, public_path=public_path,
                                 private_path=private_path)
    if not report.get("ok"):
        return _result(False, ["基准打分失败"],
                       errors=list(report.get("errors") or []), n_scored=len(seen))
    reasons: list[str] = []
    combined = report.get("combined") or {}
    if float(combined.get("abstraction", 0.0)) < float(min_abstraction):
        reasons.append(
            f"任务抽象轴 {combined.get('abstraction'):.4f} < 阈值 {float(min_abstraction):.4f}")
    if float(combined.get("execution", 0.0)) < float(min_execution):
        reasons.append(
            f"执行轴 {combined.get('execution'):.4f} < 阈值 {float(min_execution):.4f}")
    if reasons:
        return _result(False, reasons, n_scored=len(seen), report=report)
    return _result(True, ["全绿：双集干净、协议面完整且两轴达标"],
                   n_scored=len(seen), report=report)
