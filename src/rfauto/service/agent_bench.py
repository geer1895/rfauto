"""agent_bench：WP3.7 AgentBench 智能体基准内核（v1.2 新增，E11 落地）。

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
- A3 一致性轴（月计划 I 流 B2 增量）：pass^k 无偏估计（每任务 k 次独立
  trial 全过概率，METR 口径）× 成本轴（trial cost 线性外推 cost_at_k），
  evaluate_agentbench_consistency / pass_hat_k——零接线纯内核，CLI/MCP
  接线留 followUp（走五钉）

铁律 7：本模块只做"比较"——轨迹与数值均由调用方（确定性内核产出）注入，
基准自身不产生任何物理数字；公开集 ground truth 逐任务引用
docs/rf_template_references.md（官方例验收基准/闭式 sanity/HFSS 仲裁），
provenance 可溯。真实 runtime/LLM 通道由调用方经 trajectory_provider 注入——
门自身不发任何网络请求（#139：测试一律 monkeypatch 钉住通道）。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
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

# AD-1（§D-4）：agent_bench 记录增 prompt{version, sha256} 指纹块
PROMPT_REGRESSION_SCHEMA_VERSION = 1
PROMPT_REGRESSION_MAX_REGRESSION_PP = 2.0  # pass 判据：abstraction/execution 各 ≥−2pp
PROMPT_REGRESSION_CACHE_DIR = Path("runs") / "prompt_regression"
_PROMPT_REGRESSION_METRICS = ("tsa", "fca", "abstraction", "execution")

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

    AgentBench 专属：family 必填（E11 任务族：模板渲染/诊断根因/修端口/
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
        return error_envelope(errors, path=str(path))
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

    # ge8e W2 快偿（R5-06）：裸 ok 信封 → 构造器（键集/键序/语义零变化）
    if errors:
        return error_envelope(
            errors,
            public=public,
            private=private,
            private_status=status,
            private_path=str(resolved) if resolved is not None else None,
            overlap_ids=overlap,
        )
    return ok_envelope(
        errors=errors,
        public=public,
        private=private,
        private_status=status,
        private_path=str(resolved) if resolved is not None else None,
        overlap_ids=overlap,
    )


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
        return error_envelope(list(sets.get("errors") or []), private_status=sets.get("private_status"))
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
    return ok_envelope(
        schema_version=AGENTBENCH_SCHEMA_VERSION,
        private_status=sets.get("private_status"),
        contamination={"overlap_ids": sets.get("overlap_ids") or []},
        unknown_ids=unknown,
        sets={"public": public_report, "private": private_report},
        combined=combined,
    )


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


def _default_prompt_fingerprint() -> dict[str, Any]:
    """当前生效系统提示词的指纹（AD-1：agent_bench 记录增 prompt{version,sha256}）。

    惰性导入 r3_services（同层服务，避免模块加载环）；指纹是"本次门跑时生效
    提示词"的溯源记录——参考回放模式不消费 prompt 内容，指纹不代表消费。
    失败如实记 None 不猜（#105 观测不阻塞主路径）。
    """
    try:
        from rfauto.service.r3_services import get_system_prompt_meta

        meta = get_system_prompt_meta()
        return {"version": meta.get("version"), "sha256": meta.get("sha256")}
    except Exception:
        return {"version": None, "sha256": None}


def prompt_fingerprint(text: str, version: str | None = None) -> dict[str, Any]:
    """提示词文本 → {version, sha256} 指纹（确定性，落档与跨 run 比对用）。"""
    return {"version": version,
            "sha256": hashlib.sha256(str(text).encode("utf-8")).hexdigest()}


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
    prompt: Mapping[str, Any] | None = None,
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
      require_full_coverage —— 记录必须覆盖全部已加载任务（默认是）；
      prompt —— 本次评测所用系统提示词指纹 {version, sha256}（AD-1）；缺省
          自动取当前生效提示词指纹（get_system_prompt_meta）。

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
    expected_protocol = protocol_surface(
        expected_tools,
        prompt_sha256=(prompt or {}).get("sha256")
        if isinstance(prompt, Mapping) else None)

    runtime_protocol: dict[str, Any] | None = None
    missing_tools: list[str] = []
    prompt_fp = (dict(prompt) if isinstance(prompt, Mapping)
                 else _default_prompt_fingerprint())

    def _result(ok: bool, reasons: list[str], *,
                errors: list[str] | None = None,
                n_scored: int = 0,
                report: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": ok,
            "gate": "PASS" if ok else "FAIL",
            "schema_version": AGENTBENCH_SCHEMA_VERSION,
            "prompt": prompt_fp,
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
            runtime_protocol = protocol_surface(
                runtime_tools, prompt_sha256=prompt_fp.get("sha256"))
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


# ---------------------------------------------------------------------------
# A3：pass^k × 成本双轴（月计划 I 流 B2 增量；一致性口径）
# ---------------------------------------------------------------------------

def pass_hat_k(n_pass: int, n_trials: int, k: int) -> float:
    """无偏 pass^k 估计量（METR pass^k 口径）：C(n_pass,k)/C(n_trials,k)。

    语义：从 n_trials 次独立尝试里任取 k 次、k 次全部通过的比例——是
    "k 次独立重跑全部通过的概率"的无偏估计。合成回收钉（#118 预声明，
    tests/unit/test_agent_bench_consistency.py）：

    - pass_hat_k(3, 5, 2) = C(3,2)/C(5,2) = 3/10 = 0.3（逐位）；
    - k=1 退化为通过率 p/n；p≥n（全过）且 k=n → 1.0；
    - n_pass<k → 0.0（样本内不存在全过的 k 子集）。

    拒收面（fail-closed）：bool/非整数、n_trials<1、k 出界 [1, n_trials]、
    n_pass 出界 [0, n_trials] 一律 ValueError——绝不做"看起来合理"的夹持。
    """
    for name, v in (("n_pass", n_pass), ("n_trials", n_trials), ("k", k)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{name} 必须是 int（拒 bool），得 {v!r}")
    if n_trials < 1:
        raise ValueError(f"n_trials 必须 ≥1，得 {n_trials}")
    if not 1 <= k <= n_trials:
        raise ValueError(f"k 必须在 [1, n_trials]=[1, {n_trials}] 内，得 {k}")
    if not 0 <= n_pass <= n_trials:
        raise ValueError(f"n_pass 必须在 [0, {n_trials}] 内，得 {n_pass}")
    numer = math.comb(n_pass, k)
    if numer == 0:
        return 0.0
    return numer / math.comb(n_trials, k)


def _trial_cost(record: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """取单 trial 成本（record["cost"]）：合法返回 float，缺失 (None,None)，
    非法返回 (None, 错误串)——非法不静默丢（#316 多报方向）。"""
    if "cost" not in record or record.get("cost") is None:
        return None, None
    raw = record.get("cost")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, f"cost 必须是实数（拒 bool/str），得 {raw!r}"
    cost = float(raw)
    if not math.isfinite(cost) or cost < 0:
        return None, f"cost 必须有限且 ≥0，得 {raw!r}"
    return cost, None


def evaluate_agentbench_consistency(
    trials: Sequence[Mapping[str, Any]],
    *,
    k: int,
    pass_threshold: float = 1.0,
    public_path: str | Path | None = None,
    private_path: str | Path | None = None,
    min_pass_hat_k: float | None = None,
) -> dict[str, Any]:
    """pass^k × 成本双轴评测（A3 一致性口径；每任务多次独立 trial）。

    与 :func:`evaluate_agentbench`（单记录/任务、两轴打分）的关系：本函数
    复用同一任务集与同一打分器（score_agent_task），把"通过"预声明为
    **execution ≥ pass_threshold**（缺省 1.0=声明维度全对；不偷用
    abstraction 轴），对每任务 n 次独立 trial 计算无偏 pass^k
    （:func:`pass_hat_k`）与成本轴。

    trials = [{"id", "trajectory", "artifacts", "numeric", "cost"?}, ...]：
    同一 id 可重复出现（每次=一次独立尝试）；cost 可选（token/墙钟/元，
    口径由调用方声明，本函数只做聚合不产生数字——铁律 7）。成本轴模型
    预声明为**线性外推**：cost_at_k = k × cost_mean（无提前终止信用；
    k 次尝试全跑完的口径，诚实不折算）。

    防空转/fail-closed：任务集加载失败、k 出界、已知任务零 trial 覆盖、
    未知 trial id、min_pass_hat_k 给定且宏平均不达 → gate=FAIL 带原因；
    cost 全缺 → 成本轴如实 None（不虚构 0）。
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"k 必须是 ≥1 的 int（拒 bool），得 {k!r}")
    sets = load_bench_sets(public_path, private_path)
    if not sets.get("ok"):
        return {"ok": False, "gate": "FAIL",
                "errors": list(sets.get("errors") or []),
                "private_status": sets.get("private_status")}
    by_id: dict[Any, Mapping[str, Any]] = {}
    for bench_set in (sets["public"], sets.get("private")):
        if bench_set is None:
            continue
        for task in bench_set.get("tasks") or []:
            by_id[task["id"]] = task

    per_task: dict[Any, dict[str, Any]] = {}
    unknown_ids: list[str] = []
    for item in trials:
        if not isinstance(item, Mapping):
            continue
        tid = item.get("id")
        task = by_id.get(tid)
        if task is None:
            unknown_ids.append(str(tid))
            continue
        entry = per_task.setdefault(tid, {
            "id": tid, "n_trials": 0, "n_pass": 0,
            "costs": [], "cost_errors": []})
        entry["n_trials"] += 1
        scored = score_agent_task(task, item)
        if float(scored["execution"]) >= float(pass_threshold):
            entry["n_pass"] += 1
        cost, cost_err = _trial_cost(item)
        if cost_err is not None:
            entry["cost_errors"].append(cost_err)
        elif cost is not None:
            entry["costs"].append(cost)

    results: list[dict[str, Any]] = []
    for tid in sorted((str(t) for t in by_id),
                      key=lambda s: [not s.isdigit(), s]):
        entry = per_task.get(tid)
        if entry is None or entry["n_trials"] == 0:
            results.append({"id": tid, "n_trials": 0, "n_pass": 0,
                            "pass_hat_k": None,
                            "error": "任务零 trial 覆盖（防空转）"})
            continue
        n, p = entry["n_trials"], entry["n_pass"]
        pk = pass_hat_k(p, n, k)
        cost_mean = (sum(entry["costs"]) / len(entry["costs"])
                     if entry["costs"] else None)
        cost_at_k = (k * cost_mean) if cost_mean is not None else None
        efficiency = (pk / cost_at_k
                      if cost_at_k is not None and cost_at_k > 0 else None)
        row: dict[str, Any] = {
            "id": tid, "n_trials": n, "n_pass": p, "pass_hat_k": pk,
            "cost_n": len(entry["costs"]),
            "cost_mean": cost_mean, "cost_at_k": cost_at_k,
            "efficiency": efficiency,
        }
        if entry["cost_errors"]:
            row["cost_errors"] = entry["cost_errors"]
        results.append(row)

    scored_rows = [r for r in results if r.get("pass_hat_k") is not None]
    pk_macro = (sum(float(r["pass_hat_k"]) for r in scored_rows)
                / len(scored_rows)) if scored_rows else None
    cost_rows = [r for r in scored_rows if r["cost_mean"] is not None]
    cost_macro = (sum(float(r["cost_mean"]) for r in cost_rows)
                  / len(cost_rows)) if cost_rows else None

    reasons: list[str] = []
    if not scored_rows:
        reasons.append("无任何任务拿到有效 trial（防空转）")
    missing = [r["id"] for r in results if r.get("pass_hat_k") is None]
    if missing:
        reasons.append(f"{len(missing)} 个任务零 trial 覆盖 → {missing[:5]}")
    if unknown_ids:
        reasons.append(f"trial 含未知任务 id: {sorted(set(unknown_ids))[:5]}")
    if min_pass_hat_k is not None and pk_macro is not None \
            and float(pk_macro) < float(min_pass_hat_k):
        reasons.append(
            f"pass^{k} 宏平均 {pk_macro:.4f} < 阈值 {float(min_pass_hat_k):.4f}")
    if min_pass_hat_k is not None and pk_macro is None:
        reasons.append(f"pass^{k} 宏平均不可得（无有效 trial）——门不空跑绿")

    return {
        "ok": not reasons and bool(scored_rows),
        "gate": "PASS" if (not reasons and scored_rows) else "FAIL",
        "schema_version": AGENTBENCH_SCHEMA_VERSION,
        "private_status": sets.get("private_status"),
        "k": k,
        "pass_threshold": float(pass_threshold),
        "min_pass_hat_k": (float(min_pass_hat_k)
                           if min_pass_hat_k is not None else None),
        "pass_hat_k_macro": pk_macro,
        "cost_mean_macro": cost_macro,
        "unknown_trial_ids": sorted(set(unknown_ids)),
        "results": results,
        "reasons": reasons,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# AD-1：系统提示词回归门（plan_deepdive_specs §D-4；两版 prompt × 公开 goldset）
# ---------------------------------------------------------------------------

def _provider_arity(fn: Callable[..., Any]) -> int:
    """轨迹提供器位置参数容量（≥2 = 接 (task, system_prompt)，否则按 1 参调）。

    兼容两类提供器：prompt 回归门原生 2 参（task, system_prompt）与
    goldset/agentbench 门遗留 1 参（task）。*args 视为 2 参容量；
    签名不可读（内建/包装器）按 2 参试。AKA 检查只在调用前做一次。
    """
    import inspect

    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return 2
    params = list(sig.parameters.values())
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return 2
    positional = [p for p in params if p.kind in (
        inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    return 2 if len(positional) >= 2 else 1


def _persist_prompt_regression(record: dict[str, Any], persist: bool,
                               cache_dir: str | Path | None) -> None:
    """轨迹缓存（best-effort，#105：观测路径不得阻塞门主路径）。

    落 runs/prompt_regression/（或显式 cache_dir）；失败如实记
    cache_path=None，不抛。文件名含时间戳与两版指纹前 8 位。
    """
    if not persist:
        return
    try:
        d = Path(cache_dir) if cache_dir is not None else PROMPT_REGRESSION_CACHE_DIR
        d.mkdir(parents=True, exist_ok=True)
        sha8_a = str((record.get("prompt_a") or {}).get("sha256") or "")[:8]
        sha8_b = str((record.get("prompt_b") or {}).get("sha256") or "")[:8]
        ts = str(record.get("generated_at") or "").replace(":", "").replace("-", "")
        p = d / f"prompt_regression_{ts}_{sha8_a}-{sha8_b}.json"
        p.write_text(json.dumps(record, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        record["cache_path"] = str(p)
    except OSError:
        record["cache_path"] = None


def load_prompt_regression_record(path: str | Path) -> dict[str, Any]:
    """读回缓存记录（旧档兼容：缺字段读回 None，不炸）。

    AD-1 之前的档位没有 prompt 块/prompt_sha256/flips 字段——一律 ``.get``
    容错读回 None/空序列，绝不让旧档把读面打炸（#316 多报不误伤方向相反：
    读面只回填缺省，不改写归档原文）。
    """
    p = Path(path)
    if not p.exists():
        return error_envelope([f"记录不存在: {p}"])
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return error_envelope([f"记录不可读: {exc}"])
    if not isinstance(data, dict):
        return error_envelope(["记录必须是 JSON 映射"])
    return ok_envelope(
        gate=data.get("gate"),
        mode=data.get("mode"),
        prompt_a_sha256=(data.get("prompt_a") or {}).get("sha256"),
        prompt_b_sha256=(data.get("prompt_b") or {}).get("sha256"),
        metrics=data.get("metrics"),
        flips=data.get("flips") or [],
        raw=data,
    )


def run_prompt_regression(
    prompt_a: str,
    prompt_b: str,
    *,
    version_a: str | None = None,
    version_b: str | None = None,
    trajectory_provider: Callable[[Mapping[str, Any], str], Any] | None = None,
    records_a: Sequence[Mapping[str, Any]] | None = None,
    records_b: Sequence[Mapping[str, Any]] | None = None,
    public_path: str | Path | None = None,
    runtime_tools_a: Iterable[str] | None = None,
    runtime_tools_b: Iterable[str] | None = None,
    pass_threshold: float = 1.0,
    max_regression_pp: float = PROMPT_REGRESSION_MAX_REGRESSION_PP,
    adjudicated_flips: Sequence[str] = (),
    require_full_coverage: bool = True,
    persist: bool = True,
    cache_dir: str | Path | None = None,
) -> dict[str, Any]:
    """系统提示词 A/B 回归门（AD-1 §D-4）：两版 prompt × 公开 goldset。

    流程（与 goldset/agentbench 门同构）：公开集加载 → 双臂逐任务取轨迹
    （通道注入点）→ _score_one_set 四指标（tsa/fca/abstraction/execution）
    差分（B−A）→ 预声明判据判定。

    pass 判据（预声明，#122）：
      ① abstraction/execution 各 ≥ −max_regression_pp（缺省 −2pp）；
      ② n_tools 一致（两臂工具面相同——prompt 变体比较的公平性前提，
         工具面变了就是混淆变量，拒绝判分）；
      ③ 无任务 pass→fail 翻转（pass := execution ≥ pass_threshold，与 A3
         同口径）。翻转逐条列出（含两臂 execution 明细）供**人工逐列裁决**；
         已裁决放行的 id 走 adjudicated_flips 显式传入，报告如实区分
         翻转/已裁决两组。

    通道注入（#139：门自身零网络，LLM 对话通道必须由调用方注入）：
      trajectory_provider(task, system_prompt) —— 逐任务调用，返回映射视为
          完整埋点记录、返回序列视为轨迹；离线假通道（预录回复序列）或
          runtime_ab.scripted_prompt_track 双轨驱动均可；亦按签名自动兼容
          goldset/agentbench 门遗留 1 参 provider（task，不消费 prompt）；
      records_a/records_b —— 已记录埋点（与 provider 二选一，provider 优先）；
      都缺省 → reference_agentbench_provider 离线参考回放（门自洽正控——
      回放不消费 prompt 内容，只证明门管道自洽，不构成 prompt 质量证据）。

    防空转：公开集加载失败 / 两版 prompt 指纹相同（sha256 一致，无差可回归）/
    任一臂未覆盖全部任务 / 提供器异常 → 直接 FAIL，绝不空跑绿。
    轨迹缓存：结果记录 JSON 落 runs/prompt_regression/（persist=False 关；
    best-effort，写失败不阻塞门）。
    """
    bench = load_bench_set(public_path or default_public_path())
    fp_a = prompt_fingerprint(prompt_a, version_a)
    fp_b = prompt_fingerprint(prompt_b, version_b)
    record: dict[str, Any] = {
        "gate_kind": "prompt_regression",
        "schema_version": PROMPT_REGRESSION_SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": ("provider" if trajectory_provider is not None
                 else "records" if (records_a is not None and records_b is not None)
                 else "reference_replay"),
        "public_path": str(bench.get("path") or public_path
                           or default_public_path()),
        "prompt_a": fp_a, "prompt_b": fp_b,
        "pass_threshold": float(pass_threshold),
        "max_regression_pp": float(max_regression_pp),
    }

    def _finish(ok: bool, reasons: list[str]) -> dict[str, Any]:
        record["ok"] = ok
        record["gate"] = "PASS" if ok else "FAIL"
        record["reasons"] = reasons
        _persist_prompt_regression(record, persist, cache_dir)
        return record

    if not bench.get("ok"):
        return _finish(False, [f"公开集加载失败: {list(bench.get('errors') or [])}"])
    tasks = list(bench.get("tasks") or [])
    if not tasks:
        return _finish(False, ["公开集为空：拒绝空跑（防空转）"])
    if str(fp_a["sha256"]) == str(fp_b["sha256"]):
        return _finish(False, [
            "两版 prompt 指纹相同（sha256 一致）：无差可回归（防空转）"])

    known_ids = {t["id"] for t in tasks}
    expected_tools = goldset_expected_tools(bench)
    expected_protocol = protocol_surface(expected_tools)
    record["n_tasks"] = len(tasks)
    record["expected_protocol"] = expected_protocol

    arms: dict[str, dict[str, Any]] = {}
    for key, p_text, fp, recs, tools in (
            ("a", prompt_a, fp_a, records_a, runtime_tools_a),
            ("b", prompt_b, fp_b, records_b, runtime_tools_b)):
        if record["mode"] == "records":
            if not isinstance(recs, (list, tuple)):
                return _finish(False, [f"records_{key} 必须是序列"])
            items: list[Mapping[str, Any]] = [
                i for i in recs if isinstance(i, Mapping)]
            if not items:
                return _finish(False, [f"records_{key} 为空：拒绝空跑（防空转）"])
        else:
            provider = trajectory_provider or (
                lambda task, _sys, _ref=reference_agentbench_provider: _ref(task))
            provider_arity = _provider_arity(provider)
            provided: list[Mapping[str, Any]] = []
            for task in tasks:
                try:
                    produced = (provider(task, p_text) if provider_arity >= 2
                                else provider(task))
                except Exception as exc:  # 通道（LLM/假通道）异常即门红，不掩盖
                    return _finish(False, [
                        f"轨迹提供器异常（arm={key} task={task.get('id')}）: {exc}"])
                if isinstance(produced, Mapping):
                    item = dict(produced)
                elif isinstance(produced, (list, tuple)):
                    item = {"trajectory": list(produced)}
                else:
                    return _finish(False, [
                        f"轨迹提供器返回类型非法（arm={key} "
                        f"task={task.get('id')}）"])
                item.setdefault("id", task.get("id"))
                provided.append(item)
            items = provided

        unknown = sorted({str(i.get("id")) for i in items
                          if i.get("id") not in known_ids})
        if unknown:
            return _finish(False, [f"arm {key} 记录含未知任务 id: {unknown[:5]}"])
        seen = {i.get("id") for i in items}
        if require_full_coverage and seen != known_ids:
            absent = sorted(known_ids - seen)
            return _finish(False, [
                f"arm {key} 未覆盖全部基准任务：缺 {len(absent)} 个 {absent[:5]}"])

        arm_report = _score_one_set(bench, items)
        if tools is None:
            arm_protocol = protocol_surface(expected_tools,
                                            prompt_sha256=fp["sha256"])
            tools_note = "defaulted_to_expected"
        else:
            if isinstance(tools, (str, bytes)):
                return _finish(False, [
                    f"runtime_tools_{key} 必须是工具名序列，不是字符串"])
            arm_protocol = protocol_surface(list(tools),
                                            prompt_sha256=fp["sha256"])
            missing = [t for t in expected_protocol["tools"]
                       if t not in set(arm_protocol["tools"])]
            if missing:
                return _finish(False, [
                    f"协议面回归：arm {key} 工具面缺基准期望工具 "
                    f"{len(missing)} 个 → {missing[:5]}"])
            tools_note = "provided"
        arms[key] = {"prompt": fp, "protocol": arm_protocol,
                     "report": arm_report, "tools_note": tools_note}
        record[f"arm_{key}"] = arms[key]

    metrics = {m: {"a": arms["a"]["report"][m], "b": arms["b"]["report"][m],
                   "delta": round(arms["b"]["report"][m]
                                  - arms["a"]["report"][m], 6)}
               for m in _PROMPT_REGRESSION_METRICS}
    record["metrics"] = metrics
    n_tools_consistent = (arms["a"]["protocol"]["tools"]
                          == arms["b"]["protocol"]["tools"])
    record["n_tools_consistent"] = n_tools_consistent
    record["n_scored"] = min(arms["a"]["report"]["n_scored"],
                             arms["b"]["report"]["n_scored"])

    # 任务级 pass/fail 与翻转（execution ≥ pass_threshold 为过，A3 同口径；
    # 打分错误条目无 execution 字段 → 记 fail，多报不放过，#316 方向）
    def _rows(arm_key: str) -> dict[Any, Mapping[str, Any]]:
        return {r.get("id"): r for r in arms[arm_key]["report"]["results"]
                if "error" not in r}

    rows_a, rows_b = _rows("a"), _rows("b")

    def _passed(row: Mapping[str, Any] | None) -> bool:
        return bool(row is not None and "execution" in row
                    and float(row["execution"]) >= float(pass_threshold))

    adjud = {str(x) for x in adjudicated_flips}
    flips: list[dict[str, Any]] = []
    flips_adjudicated: list[dict[str, Any]] = []
    for tid in sorted(known_ids, key=lambda s: str(s)):
        if _passed(rows_a.get(tid)) and not _passed(rows_b.get(tid)):
            row = {"id": tid,
                   "execution_a": (rows_a.get(tid) or {}).get("execution"),
                   "execution_b": (rows_b.get(tid) or {}).get("execution"),
                   "abstraction_a": (rows_a.get(tid) or {}).get("abstraction"),
                   "abstraction_b": (rows_b.get(tid) or {}).get("abstraction")}
            (flips_adjudicated if str(tid) in adjud else flips).append(row)
    record["flips"] = flips
    record["flips_adjudicated"] = flips_adjudicated

    reasons: list[str] = []
    for m, label in (("abstraction", "任务抽象轴"), ("execution", "执行轴")):
        delta = metrics[m]["delta"]
        if delta < -float(max_regression_pp) / 100.0:
            reasons.append(
                f"{label}回归 {delta:+.4f}（B−A）超出 −{float(max_regression_pp):.1f}pp 门")
    if not n_tools_consistent:
        reasons.append("n_tools 不一致：两臂工具面不同（混淆变量，拒绝判分）")
    if flips:
        reasons.append(
            f"{len(flips)} 个任务 pass→fail 翻转：{[f['id'] for f in flips]}"
            f"（逐列人工裁决后经 adjudicated_flips 放行）")
    if reasons:
        return _finish(False, reasons)
    deltas = "、".join(f"{m} {metrics[m]['delta']:+.4f}"
                       for m in _PROMPT_REGRESSION_METRICS)
    return _finish(True, [
        f"全绿：四指标差分在门内（{deltas}）、"
        f"n_tools 一致（{arms['a']['protocol']['n_tools']}）、无 pass→fail 翻转"])
