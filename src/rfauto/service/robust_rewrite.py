"""robust_rewrite：工具调用层基准的 Δrobust 改写表（阶段 2.2 增量）。

Δrobust 稳健改写方法论：同一任务改写表述（不改工具可调用
意图）后重测 agent 得分，得分差 = 表述敏感性。分工：
- 改写表生成 = LLM harness（表述是语言问题，LLM 生成；通道可注入，
  单测 monkeypatch 钉住——#139：配了 key 也不许测试真打外网）；
- Δrobust 打分 = 既有确定性打分器（score_trajectory），零 LLM。

验收口径（消融参照）：去掉工具选择规则的改写掉分应显著
——Δrobust 是 curbed system prompt 有效性的度量，不是模型分。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rfauto.service.goldset_service import evaluate_trajectory_set, load_goldset

_REWRITE_SYSTEM = (
    "你是 RF 仿真调优助手任务的改写器。把用户任务改写成 n 个语义等价的"
    "变体：变化措辞/语序/礼貌程度/称谓，但不得增删任何可执行的约束、"
    "数值、频段或目标。只输出 JSON：{\"paraphrases\": [\"...\", ...]}"
)

DEFAULT_TABLE_PATH = Path("runs") / "gold" / "rewrite_table.json"


def _default_completion(messages: list[dict[str, Any]]) -> str:
    """LLM harness 默认通道（chat settings 未配置时显式报错，不打网络）。"""
    from rfauto.service.r3_services import get_chat_settings

    if not get_chat_settings().get("configured"):
        raise RuntimeError(
            "LLM 通道未配置（configs/chat_settings.yaml 无 api_key）——"
            "改写表生成需要 LLM harness，或注入 completion_fn 做离线测试")
    from rfauto.service.agent_runtime import openai_chat_completion

    resp = openai_chat_completion(messages, [])
    return resp.get("content", "") if isinstance(resp, dict) else str(resp)


def build_rewrite_table(
    goldset_path: str | Path | None = None,
    *,
    n_per_task: int = 2,
    out_path: str | Path | None = None,
    completion_fn: Callable[[list[dict[str, Any]]], str] | None = None,
) -> dict[str, Any]:
    """对 gold set 每个任务生成 n 条语义等价改写（LLM harness）。

    completion_fn：可注入的 LLM 传输（messages → text）。缺省走 chat
    settings 通道；测试必须注入（#139）。产出改写表 JSON：
    {task_id: {"original": prompt, "paraphrases": [...]}}，逐条去重、
    与原文不同才算数。
    """
    gold = load_goldset(goldset_path)
    if not gold.get("ok"):
        return gold
    fn = completion_fn or _default_completion
    table: dict[str, Any] = {}
    failures: list[str] = []
    for task in gold["tasks"]:
        messages = [
            {"role": "system", "content": _REWRITE_SYSTEM.replace(
                "n 个", f"{n_per_task} 个")},
            {"role": "user",
             "content": f"原任务：{task['prompt']}\n输出 JSON。"},
        ]
        try:
            text = fn(messages)
            data = json.loads(text[text.index("{"):text.rindex("}") + 1])
            paras: list[str] = [str(x).strip() for x in
                                data.get("paraphrases", [])]
        except Exception as exc:
            failures.append(f"{task['id']}: {exc}")
            continue
        seen = {task["prompt"].strip().lower()}
        uniq: list[str] = []
        for p in paras:
            if p and p.lower() not in seen:
                seen.add(p.lower())
                uniq.append(p)
            if len(uniq) >= n_per_task:
                break
        table[task["id"]] = {"original": task["prompt"],
                             "paraphrases": uniq}
    out = Path(out_path) if out_path else DEFAULT_TABLE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"rewrite_schema": "rfauto-rewrite-table-v1",
         "n_per_task": n_per_task, "table": table,
         "failures": failures},
        ensure_ascii=False, indent=1), encoding="utf-8")
    n_ok = sum(1 for v in table.values() if v["paraphrases"])
    return {"ok": n_ok > 0 and not failures,
            "path": str(out), "n_tasks": len(table),
            "n_tasks_with_paraphrases": n_ok,
            "failures": failures,
            "table": table}


def evaluate_robustness(
    trajectories_rewritten: list[dict[str, Any]],
    rewrite_table_path: str | Path | None = None,
    goldset_path: str | Path | None = None,
    *,
    trajectories_original: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """改写轨迹 vs 原始轨迹的 Δrobust（确定性打分，零 LLM）。

    trajectories_rewritten 条目 = {"id": 任务id, "trajectory": [...]}，
    与 gold set 同约定。原始缺省按"原 prompt 直接可解"理想化处理
    （Δ=改写分-1），传入 trajectories_original 则用实测基线。
    """
    gold = load_goldset(goldset_path)
    if not gold.get("ok"):
        return gold
    table_path = Path(rewrite_table_path) if rewrite_table_path \
        else DEFAULT_TABLE_PATH
    if not table_path.exists():
        return {"ok": False, "errors": [f"改写表不存在: {table_path}"]}
    table = (json.loads(table_path.read_text(encoding="utf-8"))
             or {}).get("table", {})

    base = evaluate_trajectory_set(
        trajectories_original or [], goldset_path)
    re = evaluate_trajectory_set(trajectories_rewritten, goldset_path)
    if not (base.get("ok") and re.get("ok")):
        return {"ok": False, "errors": ["轨迹评测失败",
                                        base.get("errors"),
                                        re.get("errors")]}
    by_id = {r["id"]: r for r in re["results"]}
    orig_by_id = {r["id"]: r for r in base["results"]}
    rows = []
    for task in gold["tasks"]:
        tid = task["id"]
        if tid not in table:
            continue
        r = by_id.get(tid)
        if r is None or "error" in r:
            continue
        o = orig_by_id.get(tid)
        orig = o if (o is not None and "error" not in o) else {
            "tsa": 1, "fca": 1, "pass3": 1}  # 未实测基线：理想化 1
        delta = {
            "tsa": r["tsa"] - orig["tsa"],
            "fca": r["fca"] - orig["fca"],
            "pass3": r["pass3"] - orig["pass3"],
        }
        rows.append({"id": tid, **r, "delta": delta})
    n = max(len(rows), 1)
    macro = {
        "delta_tsa": sum(r["delta"]["tsa"] for r in rows) / n,
        "delta_fca": sum(r["delta"]["fca"] for r in rows) / n,
        "delta_pass3": sum(r["delta"]["pass3"] for r in rows) / n,
        "tsa_rewritten": sum(r["tsa"] for r in rows) / n,
    }
    return {
        "ok": True,
        "rewrite_table": str(table_path),
        "n_tasks_scored": len(rows),
        "macro": macro,
        "robust_gate": "PASS" if macro["delta_tsa"] >= -0.1 else "FAIL",
        "rows": rows,
        "note": "Δrobust=改写后-改写前（负值=表述敏感性掉分）；"
                "口径 ΔTSA≥-0.1 为稳健线",
    }
