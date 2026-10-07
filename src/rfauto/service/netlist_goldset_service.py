"""AI-6：网表可靠性 goldset——网表回放对照面（round14:72，P2/M）。

仿 NetlistBench（arXiv:2608.12197 提案口径）的仓内落地：网表任务集
（netlist 文本 + 分析说明 + 期望指标）回放进注入的模拟器通道，对照
gold 值按容差打分。与 goldset_service（工具调用轨迹打分）同邻域、同
纪律：确定性内核零 LLM；**模拟器通道是注入点**（Callable），真跑
Qucsator/ngspice/hpeesofsim 由调用方注入，测试一律 mock（#139：禁
网络依赖；真机非本席门）。

Case schema（YAML）::

    version: 1
    tasks:
      - id: rc_lowpass_ac
        netlist: |
          * RC lowpass, fc = 1/(2*pi*R*C)
          ...
        analysis: "ac dec 100 1 1Meg"   # 透传给通道的分析说明
        expected:                        # gold 指标表
          fc_hz: {value: 1591.55, tol: 0.02}          # tol_mode 缺省 rel
          gain_db_1k: {value: -0.0432, tol: 0.01, tol_mode: abs}

判读纪律（#122/#195）：通道缺指标=FAIL 如实记因，不静默不伪造；
通道异常=verdict ERROR（与 FAIL 分列，数据坏≠模型类不覆盖）；
空任务集拒绝空跑（防空转绿，同 goldset_service 门语义）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DEFAULT_TOL",
    "load_netlist_goldset",
    "netlist_fingerprint",
    "replay_case",
    "replay_netlist_goldset",
]

#: rel 容差缺省 5%（round14 AI-6 邻域惯例；abs 模式需显式 tol_mode）
DEFAULT_TOL = 0.05

# 模拟器通道类型：f(netlist_text, analysis) -> {metric: value}
SimulatorChannel = Callable[[str, str], Mapping[str, float]]


def netlist_fingerprint(netlist_text: str) -> str:
    """网表内容指纹（sha256，provenance/跨 run 比对用，同 protocol_surface 口径）。"""
    return hashlib.sha256(netlist_text.encode("utf-8")).hexdigest()


def load_netlist_goldset(path: str | Path) -> dict[str, Any]:
    """加载网表 goldset 并做结构自检（id 唯一/netlist 非空/expected 合法）。"""
    import yaml

    p = Path(path)
    if not p.exists():
        return error_envelope([f"网表 goldset 不存在: {p}"])
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    tasks = data.get("tasks") or []
    errors: list[str] = []
    ids = [t.get("id") for t in tasks if isinstance(t, Mapping)]
    if len(ids) != len(set(ids)):
        errors.append("任务 id 重复")
    for t in tasks:
        tid = str(t.get("id", "?"))
        if not isinstance(t.get("netlist"), str) or not t.get("netlist", "").strip():
            errors.append(f"{tid} netlist 为空")
        expected = t.get("expected")
        if not isinstance(expected, Mapping) or not expected:
            errors.append(f"{tid} expected 为空或非映射")
            continue
        for mname, spec in expected.items():
            if isinstance(spec, Mapping):
                value = spec.get("value")
                tol = spec.get("tol", DEFAULT_TOL)
                mode = spec.get("tol_mode", "rel")
            else:  # 裸数值简写：tol 缺省、rel 模式
                value, tol, mode = spec, DEFAULT_TOL, "rel"
            if not isinstance(value, (int, float)):
                errors.append(f"{tid}.{mname} value 非数值")
            if not isinstance(tol, (int, float)) or tol <= 0:
                errors.append(f"{tid}.{mname} tol 必须为正数")
            if mode not in ("rel", "abs"):
                errors.append(f"{tid}.{mname} tol_mode 非法: {mode}")
    if errors:
        return {"ok": False, "path": str(p), "errors": errors}
    return ok_envelope(path=str(p), n_tasks=len(tasks), tasks=tasks)


def replay_case(
    task: Mapping[str, Any],
    simulator: SimulatorChannel,
    *,
    default_tol: float = DEFAULT_TOL,
) -> dict[str, Any]:
    """单网表任务回放对照：通道注入 → 逐指标容差判读。

    返回 ``{id, netlist_sha256, metrics, deviations, verdict, reasons}``；
    verdict ∈ {"PASS", "FAIL", "ERROR"}——ERROR=通道异常（数据坏），
    FAIL=指标越容差/缺失（模型类不覆盖或通道错），二者分列不混判。
    """
    tid = str(task.get("id", "?"))
    netlist = str(task.get("netlist") or "")
    analysis = str(task.get("analysis") or "")
    fp = netlist_fingerprint(netlist)
    try:
        out = simulator(netlist, analysis)
    except Exception as exc:
        return {"id": tid, "netlist_sha256": fp, "metrics": None,
                "deviations": {}, "verdict": "ERROR",
                "reasons": [f"模拟器通道异常: {type(exc).__name__}: {exc}"]}
    if not isinstance(out, Mapping):
        return {"id": tid, "netlist_sha256": fp, "metrics": None,
                "deviations": {}, "verdict": "ERROR",
                "reasons": [f"模拟器通道返回非映射: {type(out).__name__}"]}

    expected = task.get("expected") or {}
    metrics: dict[str, float] = {}
    deviations: dict[str, float] = {}
    reasons: list[str] = []
    n_pass = 0
    for mname, spec in expected.items():
        if isinstance(spec, Mapping):
            value = float(spec.get("value"))
            tol = float(spec.get("tol", default_tol))
            mode = str(spec.get("tol_mode", "rel"))
        else:
            value, tol, mode = float(spec), float(default_tol), "rel"
        if mname not in out:
            reasons.append(f"{mname}: 通道未产出该指标（缺 {mname}）")
            continue
        got = float(out[mname])
        metrics[mname] = got
        dev = abs(got - value) / max(abs(value), 1e-300) if mode == "rel" \
            else abs(got - value)
        deviations[mname] = dev
        if dev <= tol:
            n_pass += 1
        else:
            reasons.append(
                f"{mname}: |dev|={dev:.4g} > tol={tol:.4g} ({mode}; "
                f"gold={value:.6g}, got={got:.6g})")
    verdict = "PASS" if n_pass == len(expected) else "FAIL"
    return {"id": tid, "netlist_sha256": fp, "metrics": metrics,
            "deviations": deviations, "verdict": verdict,
            "reasons": reasons if reasons else ["全部指标在容差内"]}


def replay_netlist_goldset(
    tasks: Any = None,
    simulator: SimulatorChannel | None = None,
    *,
    goldset_path: str | Path | None = None,
    min_pass_rate: float = 1.0,
    default_tol: float = DEFAULT_TOL,
) -> dict[str, Any]:
    """网表 goldset 回归门：逐任务回放 → PASS 率阈值判定。

    参数二选一：``tasks``（任务记录序列）或 ``goldset_path``（YAML 文件）。
    ``simulator`` 必须显式注入——缺通道直接 FAIL（拒绝空跑，防误绿）。
    返回 ``{ok, gate, n_cases, n_pass, n_fail, n_error, pass_rate,
    min_pass_rate, results, reasons}``。
    """
    if simulator is None:
        return {"ok": False, "gate": "FAIL", "n_cases": 0, "n_pass": 0,
                "n_fail": 0, "n_error": 0, "pass_rate": 0.0,
                "min_pass_rate": float(min_pass_rate), "results": [],
                "reasons": ["未注入模拟器通道：拒绝空跑（防空转）"]}
    if tasks is None:
        if goldset_path is None:
            return {"ok": False, "gate": "FAIL", "n_cases": 0, "n_pass": 0,
                    "n_fail": 0, "n_error": 0, "pass_rate": 0.0,
                    "min_pass_rate": float(min_pass_rate), "results": [],
                    "reasons": ["未提供 tasks 或 goldset_path：拒绝空跑"]}
        gold = load_netlist_goldset(goldset_path)
        if not gold.get("ok"):
            return {"ok": False, "gate": "FAIL", "n_cases": 0, "n_pass": 0,
                    "n_fail": 0, "n_error": 0, "pass_rate": 0.0,
                    "min_pass_rate": float(min_pass_rate), "results": [],
                    "reasons": list(gold.get("errors") or ["goldset 加载失败"])}
        tasks = gold["tasks"]
    tasks = list(tasks)
    if not tasks:
        return {"ok": False, "gate": "FAIL", "n_cases": 0, "n_pass": 0,
                "n_fail": 0, "n_error": 0, "pass_rate": 0.0,
                "min_pass_rate": float(min_pass_rate), "results": [],
                "reasons": ["任务集为空：拒绝空跑（防空转）"]}
    results = [replay_case(t, simulator, default_tol=default_tol) for t in tasks]
    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    n_error = sum(1 for r in results if r["verdict"] == "ERROR")
    n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
    pass_rate = n_pass / len(results)
    reasons: list[str] = []
    if pass_rate < float(min_pass_rate):
        reasons.append(
            f"PASS 率 {pass_rate:.4f} < 阈值 {float(min_pass_rate):.4f}")
    for r in results:
        if r["verdict"] != "PASS":
            reasons.append(f"[{r['verdict']}] {r['id']}: "
                           + ("; ".join(r["reasons"]) or "无明细"))
    ok = pass_rate >= float(min_pass_rate)
    return {"ok": ok, "gate": "PASS" if ok else "FAIL",
            "n_cases": len(results), "n_pass": n_pass,
            "n_fail": n_fail, "n_error": n_error, "pass_rate": pass_rate,
            "min_pass_rate": float(min_pass_rate), "results": results,
            "reasons": reasons if reasons else ["全部网表任务回放达标"]}
