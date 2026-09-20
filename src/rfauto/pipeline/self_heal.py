"""自愈编排——掉线重连 + 几何失败重建。

此前 reconnect_with_backoff（hfss_session）已实现但零调用方；
几何建模失败也没有编排层重试。本模块提供两个编排原语，供
service/api.run_once 与 optimization/optimizer 接线：

- solve_with_self_heal：solve 抛异常或健康检查失败时，
  ensure_connected()（带退避重连）后重试一次
- build_with_self_heal：插件几何构建失败时重建重试一次
  （HFSS 建模常见瞬态失败：上一次会话残留、对象名冲突等）
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from rfauto.pipeline import log_distiller

logger = logging.getLogger(__name__)


def solve_with_self_heal(
    adapter: Any,
    setup_name: str,
    *,
    retries: int = 1,
) -> Any:
    """带掉线自愈的求解。返回 SolveReport；重试耗尽后异常/失败报告透传。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if not adapter.health_check():
                logger.warning("健康检查失败（第 %d 次），尝试自愈重连", attempt + 1)
                adapter.ensure_connected()
            return adapter.solve(setup_name)
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            logger.warning(
                "求解异常（第 %d 次），自愈重连后重试: %s", attempt + 1, exc,
            )
            adapter.ensure_connected()
    assert last_exc is not None
    raise last_exc


def build_with_self_heal(
    build_fn: Callable[[], None],
    *,
    retries: int = 1,
) -> None:
    """带几何失败自愈的构建。首次失败后重试（重建）一次，仍失败则抛出。"""
    for attempt in range(retries + 1):
        try:
            build_fn()
            return
        except Exception:
            if attempt >= retries:
                raise
            logger.warning("几何构建失败（第 %d 次），重建重试", attempt + 1)


# ---------------------------------------------------------------------------
# 最小自愈环
# ---------------------------------------------------------------------------
# LogDistiller digest → 确定性 critique（失败签名 → 根因/建议动作）→
# 可选重试。**本环不调用任何 LLM**：llm_explainer 只作预留接口接受，绝不在
# 环内触发（判定与建议只在确定性内核，LLM 只编排与解释）。

_ROOT_CAUSE_CATALOG: dict[str, dict[str, Any]] = {
    log_distiller.SIG_CALCPORT_INDEX_ERROR: {
        "root_cause": "CFL 时间步塌缩致 CalcPort 越界（网格近重合线，非端口设置错）",
        "lesson_ref": "#152",
        "severity": "error",
        "priority": 100,
        "actions": [
            "网格构建末尾做最小间距守卫（AddEdges2Grid/SmoothMesh 后去重，间距 ≥1µm，#152）",
            "核对 timestep 量级是否塌缩（正常 1e-12~1e-13，塌缩后 <1e-16）",
            "勿按端口 deembed/尺寸方向排查：症状（CalcPort IndexError）具有误导性",
        ],
    },
    log_distiller.SIG_TIMESTEP_COLLAPSE: {
        "root_cause": "CFL 时间步塌缩（网格近重合线，症状常为 CalcPort IndexError）",
        "lesson_ref": "#152",
        "severity": "error",
        "priority": 95,
        "actions": [
            "回写去重网格线并复核 timestep 量级恢复（≥1e-13 s）",
            "排查 AddEdges2Grid 边缘线与浮点误差撞出的 nm 级近重合线",
        ],
    },
    log_distiller.SIG_NEAR_COINCIDENT_MESH: {
        "root_cause": "网格近重合线（最小间距守卫未生效）",
        "lesson_ref": "#152",
        "severity": "error",
        "priority": 90,
        "actions": [
            "在网格构建末尾设置最小间距守卫（间距 ≥1µm）后重跑",
        ],
    },
    log_distiller.SIG_EXCITATION_DEAD: {
        "root_cause": "激励体积死（零宽盒/盒边未进网格）",
        "lesson_ref": "#174",
        "severity": "error",
        "priority": 85,
        "actions": [
            "检查激励体积是否为零宽/未落入网格（#174），先修几何再谈校准",
            "核对端口面/馈线终点是否随域扩同步移动（辐射器件开路 stub 陷阱）",
        ],
    },
    log_distiller.SIG_WAVE_PORT_OFFICIAL: {
        "root_cause": "波端口尺寸/口径不符官方惯例",
        "lesson_ref": "#191",
        "severity": "error",
        "priority": 80,
        "actions": [
            "先查官方文档核对波端口尺寸/参考面（#191：HFSS 异常几乎必是建模错误）",
            "对照官方例口径重设端口后重跑，勿在校准层补偿",
        ],
    },
    log_distiller.SIG_LICENSE_UNAVAILABLE: {
        "root_cause": "license 席位不可用（HFSS/COMSOL 许可被占或未授权）",
        "lesson_ref": "稀缺资源调度",
        "severity": "warning",
        "priority": 70,
        "actions": [
            "等待/串行化 license 类作业（同一席位不可并发）",
            "核对 license 服务与席位占用，勿盲目重试烧机时",
        ],
    },
    log_distiller.SIG_SESSION_LOST: {
        "root_cause": "求解器会话掉线（gRPC/连接中断）",
        "lesson_ref": "#157/#208",
        "severity": "warning",
        "priority": 65,
        "actions": [
            "ensure_connected() 带退避重连后重试（solve_with_self_heal 既有路径）",
            "重试前确认旧会话/残留对象已清理，避免对象名冲突",
        ],
    },
    log_distiller.SIG_NONCONVERGENCE: {
        "root_cause": "求解未收敛/出现 NaN（网格或时间步不足）",
        "lesson_ref": "#152/#219",
        "severity": "error",
        "priority": 60,
        "actions": [
            "核对网格收敛档与 timestep 量级；补网格收敛研究后再采信结果",
            "检查端口激励与边界是否自洽（先验模型）",
        ],
    },
    log_distiller.SIG_GEOMETRY_BUILD: {
        "root_cause": "几何构建瞬态失败（对象名冲突/残留会话）",
        "lesson_ref": "几何重建自愈",
        "severity": "warning",
        "priority": 55,
        "actions": [
            "清理残留会话/对象后重建重试（build_with_self_heal 既有路径）",
        ],
    },
    log_distiller.SIG_NONPHYSICAL_GAIN: {
        "root_cause": "非物理增益（无源网络 |S|>1）",
        "lesson_ref": "#174",
        "severity": "error",
        "priority": 50,
        "actions": [
            "先排查激励体积/端口面是否有效（#174），再核对无源性",
        ],
    },
    log_distiller.SIG_NONZERO_EXIT: {
        "root_cause": "子进程非零退出（无更具体的已知失败签名）",
        "lesson_ref": "rc",
        "severity": "warning",
        "priority": 10,
        "actions": [
            "保留完整日志原文并人工判读；补该失败模式的指纹规则",
        ],
    },
}

_GENERIC_UNKNOWN_ACTIONS = [
    "保留完整日志原文并人工判读（未命中已知失败签名）",
    "先审计建模与官方例口径，再考虑调参",
]


def _has_failure_evidence(digest: dict[str, Any]) -> bool:
    """digest 是否包含失败证据（错误行或非零 rc）。"""
    if digest.get("errors"):
        return True
    rc = digest.get("rc")
    return rc is not None and rc != 0


def critique_failure(raw: Any, *, source: str = "auto") -> dict[str, Any]:
    """确定性 critique：日志/digest → 有序根因清单 + 建议动作。

    输入可为 LogDistiller digest（dict）或原始日志/审计 JSON（自动蒸馏）。
    返回 JSON 友好结构（根因按 priority 排序，root_cause_id 为 top-1）。

    本函数不调用任何 LLM；verdict ∈ {clean, diagnosed, unknown_failure}。
    """
    digest = raw if (isinstance(raw, dict) and "signatures" in raw and "source" in raw) \
        else log_distiller.distill_log(raw, source=source)
    signatures = list(digest.get("signatures", []))
    causes: list[dict[str, Any]] = []
    for order, signature in enumerate(signatures):
        spec = _ROOT_CAUSE_CATALOG.get(signature)
        if spec is None:
            continue
        causes.append({
            "id": signature,
            "root_cause": spec["root_cause"],
            "lesson_ref": spec["lesson_ref"],
            "severity": spec["severity"],
            "priority": spec["priority"],
            "order": order,
            "actions": list(spec["actions"]),
        })
    causes.sort(key=lambda c: (-c["priority"], c["order"]))
    for cause in causes:
        cause.pop("order", None)

    if causes:
        verdict = "diagnosed"
    elif _has_failure_evidence(digest):
        verdict = "unknown_failure"
    else:
        verdict = "clean"

    top = causes[0] if causes else None
    if top is not None:
        actions = list(top["actions"])
    elif verdict == "unknown_failure":
        actions = list(_GENERIC_UNKNOWN_ACTIONS)
    else:
        actions = []

    return {
        "ok": True,
        "verdict": verdict,
        "root_cause_id": top["id"] if top else None,
        "root_cause": top["root_cause"] if top else None,
        "lesson_ref": top["lesson_ref"] if top else None,
        "severity": top["severity"] if top else None,
        "causes": causes,
        "signatures": signatures,
        "actions": actions,
        "digest": digest,
    }


def self_heal_loop(
    attempt: Callable[[], Any],
    *,
    log_of: Callable[[Any], Any] | None = None,
    retries: int = 1,
    apply_fix: Callable[[dict[str, Any]], Any] | None = None,
    source: str = "auto",
    llm_explainer: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """最小自愈环：attempt → digest → 确定性 critique → apply_fix → 重试。

    参数：
        attempt: 被测动作（返回结果对象/日志/字符串；抛异常也算失败）。
        log_of: 从 attempt 结果提取日志的函数（缺省直接把结果当日志）。
        retries: 首次失败后的重试次数（总尝试 = retries + 1）。
        apply_fix: 确定性修复回调，收到 critique（含根因/建议）后执行。
        source: 日志数据源（"auto" 按内容判定）。
        llm_explainer: **预留接口，绝不调用**（本项不引入 LLM；返回报告里
            以 llm_explainer_available / llm_used 如实披露）。

    返回 JSON 友好结构：{"ok", "attempts", "result", "critique", "history",
    "llm_used", "llm_explainer_available"}。成功判定=无异常且 critique 为
    clean（无日志时仅看异常与 result.success）。
    """
    if retries < 0:
        retries = 0
    history: list[dict[str, Any]] = []
    last_result: Any = None
    last_critique: dict[str, Any] | None = None

    for index in range(retries + 1):
        exc_text: str | None = None
        try:
            result = attempt()
        except Exception as exc:  # 动作异常 → 记入日志，走 critique
            result = None
            exc_text = f"{type(exc).__name__}: {exc}"

        raw: Any = None
        if result is not None and log_of is not None:
            try:
                raw = log_of(result)
            except Exception as exc:
                raw = f"log_of 失败（已降级）: {exc!r}"
        elif result is not None:
            raw = result
        if exc_text:
            prefix = f"{raw}\n" if isinstance(raw, str) and raw else ""
            raw = f"{prefix}{exc_text}"

        critique = critique_failure(raw, source=source) if raw is not None else None
        if critique is not None:
            last_critique = critique
        last_result = result

        success_flag = exc_text is None and getattr(result, "success", True) is not False
        if success_flag and (critique is None or critique["verdict"] == "clean"):
            return {
                "ok": True,
                "attempts": index + 1,
                "result": result,
                "critique": critique,
                "history": history,
                "llm_used": False,
                "llm_explainer_available": llm_explainer is not None,
            }

        history.append({"attempt": index + 1, "error": exc_text, "critique": critique})
        if index >= retries:
            break
        if apply_fix is not None and critique is not None:
            try:
                apply_fix(critique)
            except Exception as exc:
                history[-1]["apply_fix_error"] = repr(exc)

    return {
        "ok": False,
        "attempts": len(history),
        "result": last_result,
        "critique": last_critique,
        "history": history,
        "llm_used": False,
        "llm_explainer_available": llm_explainer is not None,
    }

