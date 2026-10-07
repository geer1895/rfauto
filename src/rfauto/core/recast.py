"""RECAST 判据重放扩面（月计划 F 流 B4）——判据×产物 的通用重放路径。

#222 三查接地（2026-09-28）：DP-12 先例=core/vv_mapping.py（verdict→V&V
映射 + u_num）+ knowledge/criteria/v2/*.yaml（三个已注册判据，三种
decision_rule 形态）+ tests/unit/test_vv_recast.py（两历史档 bespoke 重放，
同向不翻案钉）。本模块补的是**通用重放机器**：新判据注册进 criteria/v2
（或新引擎产物到达）后，无需 bespoke 测试即可对任意（判据×产物）对自动
重算门、映射 V&V 状态、并做 same/flip/not_judged 三向标注——重放输出是
**新增报告**，归档判读零改写（#325/#326：只读输入，绝不回写 verdict）。

支持形态（预声明；与三个已注册判据一一对应）：

- ``multi_gate_all_pass``（df5_c3fix_sentinel.yaml）：decision_rule.gates
  每 {op, threshold, evidence} 全过 → PASS；可选 budget_conditional
  （evidence_fields 里 budget.declared/budget.actual）超 ratio_limit →
  PARTIAL 注记（硬门优先：gates 有 FAIL 一律 FAIL）；
- ``threshold_gate``（df6_dp10_scan.yaml）：decision_rule.{threshold,
  comparison} + 调用方显式 evidence_path（criteria 未内嵌证据绑定，按
  claim.quantity 对应产物路径给出；不给 → not_judged 不虚构）；
- ``nearest_reference_gate``（hfss_interdigital_check_m1.yaml）：非机器
  直放（<setup> 参数化证据路径 + preflight 程序语义）→ 登记
  not_machine_replayable（bespoke 重放钉已在 test_vv_recast.py）。

三向标注（fail-closed，#122/#316）：

- ``same``：归档 verdict 与重放 verdict 的 V&V 类相同（validated↔validated、
  not_validated↔not_validated、conditionally_validated↔同）；
- ``flip``：类不同——**翻案必须显式浮出，绝不静默**；
- ``not_judged``：任一侧证据缺失/不可判（含归档 verdict 落 validation_
  not_attempted/not_judged/out_of_scope/preflight_invalid 开向类）——
  缺失方向多报，不冒充 same 也不虚构 flip。

加载面：非 criteria/v2 schema、缺必备键（test_criteria_v2_pilot.REQUIRED_TOP
同款合同）、YAML 损坏 → error 条目**登记不静默跳**；批量重放对坏条目
继续（多故障叠加报告形态，与 R5 混沌档同向）。

LLM/agent 永不产生物理数字：全部数值来自调用方传入的
判据声明值与产物证据字段，本模块只做确定性重算与比较。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rfauto.core.vv_mapping import (
    VV_CONDITIONALLY_VALIDATED,
    VV_NOT_JUDGED,
    VV_NOT_VALIDATED,
    VV_OUT_OF_SCOPE,
    VV_PREFLIGHT_INVALID,
    VV_VALIDATED,
    VV_VALIDATION_NOT_ATTEMPTED,
    map_verdict,
)

__all__ = [
    "DIRECTION_FLIP",
    "DIRECTION_NOT_JUDGED",
    "DIRECTION_SAME",
    "RECAST_SCHEMA",
    "load_criteria_dir",
    "replay_batch",
    "replay_one",
]

#: 重放报告 schema 标识（消费者据此识别）
RECAST_SCHEMA = "rfauto-recast-replay/1"

DIRECTION_SAME = "same"
DIRECTION_FLIP = "flip"
DIRECTION_NOT_JUDGED = "not_judged"

#: 判据注册合同（knowledge/criteria/v2 REQUIRED_TOP，test_criteria_v2_pilot 同款）
REQUIRED_TOP = ("schema", "criteria_id", "title", "status", "runner_binding",
                "claim", "evidence_fields", "u_val", "decision_rule",
                "verdict_map", "provenance")

#: 机器直放支持的 decision_rule.form
_FORM_MULTI_GATE = "multi_gate_all_pass"
_FORM_THRESHOLD = "threshold_gate"
_FORM_NEAREST_REF = "nearest_reference_gate"

#: V&V 状态三向分类：开向类（无法与 validated/not_validated 对向比较）
_OPEN_STATUSES = frozenset({
    VV_VALIDATION_NOT_ATTEMPTED, VV_NOT_JUDGED, VV_OUT_OF_SCOPE,
    VV_PREFLIGHT_INVALID,
})


def _dig(obj: Any, dotted: str) -> Any:
    """点路径取值（如 four_gates.dev_db.obs）；路径缺失 → KeyError。"""
    cur: Any = obj
    for part in str(dotted).split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def _cmp(obs: Any, op: str, threshold: Any) -> bool:
    """门算子（与现行 gate 口径一致：≤/≥ 边界含；<、> 为严格）。"""
    if op == "<=":
        return float(obs) <= float(threshold)
    if op == ">=":
        return float(obs) >= float(threshold)
    if op == "<":
        return float(obs) < float(threshold)
    if op == ">":
        return float(obs) > float(threshold)
    raise ValueError(f"未声明门算子：{op!r}")


def _vv_class(status: str | None) -> str | None:
    """V&V 状态 → 三向类（validated/not_validated/conditionally/open）。"""
    if status is None:
        return None
    if status == VV_VALIDATED:
        return "validated"
    if status == VV_NOT_VALIDATED:
        return "not_validated"
    if status == VV_CONDITIONALLY_VALIDATED:
        return "conditionally"
    if status in _OPEN_STATUSES:
        return "open"
    return "open"  # 未识别状态按开向处理（多报 not_judged，不冒险判 flip）


def load_criteria_dir(criteria_dir: str | Path) -> list[dict[str, Any]]:
    """加载判据目录：每个 *.yaml 一条记录；坏条目 error 登记不静默跳。

    合同：schema 必须 == "criteria/v2"；REQUIRED_TOP 必备键齐全（与
    test_criteria_v2_pilot 同款注册合同——新判据注册即须过此门）。
    """
    out: list[dict[str, Any]] = []
    base = Path(criteria_dir)
    paths = sorted(base.glob("*.yaml")) if base.is_dir() else []
    for path in paths:
        entry: dict[str, Any] = {"path": str(path), "name": path.name}
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            entry.update(ok=False, errors=[f"YAML 解析失败: {exc}"])
            out.append(entry)
            continue
        if not isinstance(data, Mapping):
            entry.update(ok=False, errors=["判据根必须是映射"])
            out.append(entry)
            continue
        errors: list[str] = []
        if data.get("schema") != "criteria/v2":
            errors.append(f"schema 必须 == 'criteria/v2'，得 {data.get('schema')!r}")
        missing = [k for k in REQUIRED_TOP if not data.get(k)]
        if missing:
            errors.append(f"缺必备键 {missing}")
        form = (data.get("decision_rule") or {}).get("form")
        if form not in (_FORM_MULTI_GATE, _FORM_THRESHOLD, _FORM_NEAREST_REF):
            errors.append(f"未声明可重放 form：{form!r}")
        entry.update(ok=not errors,
                     errors=errors,
                     criteria_id=data.get("criteria_id"),
                     decision_rule_form=form,
                     criteria=dict(data))
        out.append(entry)
    return out


def _replay_multi_gate(artifact: Mapping[str, Any],
                       rule: Mapping[str, Any]) -> dict[str, Any]:
    gates_detail: dict[str, Any] = {}
    all_ok = True
    for name, spec in (rule.get("gates") or {}).items():
        try:
            obs = _dig(artifact, spec["evidence"])
            ok = _cmp(obs, spec["op"], spec["threshold"])
        except (KeyError, TypeError, ValueError) as exc:
            gates_detail[name] = {"ok": None, "error": f"证据不可评: {exc}"}
            all_ok = None
            continue
        gates_detail[name] = {"ok": ok, "obs": obs,
                              "op": spec["op"], "threshold": spec["threshold"]}
        if not ok:
            all_ok = False
    if all_ok is None:
        return {"replay_verdict": None, "gates": gates_detail,
                "reason": "证据缺失→not_judged（不虚构）"}
    # budget 注记（PARTIAL 语义）：evidence_fields 声明 budget.declared/actual
    # 且 decision_rule.budget_conditional 在场时才评；硬门 FAIL 优先。
    budget = rule.get("budget_conditional")
    if all_ok and isinstance(budget, Mapping) and budget.get("ratio_limit"):
        try:
            declared = float(_dig(artifact, "budget.declared"))
            actual = float(_dig(artifact, "budget.actual"))
            ratio = actual / declared if declared else None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            ratio = None
        if ratio is not None and float(ratio) > float(budget["ratio_limit"]):
            return {"replay_verdict": "PARTIAL", "gates": gates_detail,
                    "budget_ratio": ratio,
                    "reason": (f"预算比 {ratio:g}>{budget['ratio_limit']:g}"
                               "→ conditionally_validated 注记（哨 1.3× 口径）")}
        if ratio is not None:
            gates_detail["budget_ratio"] = ratio
    return {"replay_verdict": "PASS" if all_ok else "FAIL",
            "gates": gates_detail}


def _replay_threshold(artifact: Mapping[str, Any],
                      rule: Mapping[str, Any],
                      evidence_path: str | None) -> dict[str, Any]:
    if not evidence_path:
        return {"replay_verdict": None,
                "reason": "threshold_gate 未绑定 evidence_path（调用方按 "
                          "claim.quantity 给出；criteria 未内嵌绑定，不猜）"}
    try:
        obs = _dig(artifact, evidence_path)
        ok = _cmp(obs, rule["comparison"], rule["threshold"])
    except (KeyError, TypeError, ValueError) as exc:
        return {"replay_verdict": None, "reason": f"证据不可评: {exc}"}
    return {"replay_verdict": "PASS" if ok else "FAIL",
            "obs": obs, "comparison": rule["comparison"],
            "threshold": rule["threshold"]}


def replay_one(artifact: Mapping[str, Any], criteria: Mapping[str, Any],
               *, evidence_path: str | None = None,
               archived_verdict_path: str | None = "verdict",
               ) -> dict[str, Any]:
    """单（判据×产物）对重放：重算门 → verdict_map → V&V 类 → 三向标注。

    - artifact：产物 JSON（只读——本函数零写入零原地改，输入对象内容
      逐键不变；归档零改写=#325/#326 的显式证据）；
    - criteria：criteria/v2 YAML 数据（load_criteria_dir 条目的 criteria 键）；
    - evidence_path：threshold_gate 形态的显式证据绑定；
    - archived_verdict_path：产物内归档 verdict 字符串的点路径（缺省
      "verdict"；None=不比归档侧，方向恒 not_judged）。

    返回 dict（JSON 友好）：criteria_id / replay_verdict / replay_vv_status /
    archived_verdict / archived_vv_status / direction / detail；归档串
    原样保留（map_verdict 附加字段语义，零改名）。
    """
    rule = criteria.get("decision_rule") or {}
    form = rule.get("form")
    vmap: Mapping[str, str] = criteria.get("verdict_map") or {}

    if form == _FORM_MULTI_GATE:
        detail = _replay_multi_gate(artifact, rule)
    elif form == _FORM_THRESHOLD:
        detail = _replay_threshold(artifact, rule, evidence_path)
    else:
        detail = {"replay_verdict": None,
                  "reason": f"form {form!r} 非机器直放（bespoke 重放钉先行例）"}

    replay_verdict = detail.get("replay_verdict")
    replay_status = vmap.get(replay_verdict) if replay_verdict else None

    archived_verdict: str | None = None
    archived_status: str | None = None
    if archived_verdict_path:
        try:
            raw = _dig(artifact, archived_verdict_path)
            archived_verdict = str(raw)
            archived_status = map_verdict(archived_verdict)["vv_status"]
        except (KeyError, TypeError, ValueError):
            archived_verdict = None

    direction = DIRECTION_NOT_JUDGED
    notes: list[str] = []
    if replay_status is None:
        notes.append(detail.get("reason") or "重放侧不可判")
    arch_class = _vv_class(archived_status)
    replay_class = _vv_class(replay_status)
    if arch_class == "open":
        notes.append(f"归档侧开向（{archived_status}）——无可对向 claim，"
                     "如实 not_judged")
    if arch_class not in (None, "open") and replay_class == "validated":
        direction = (DIRECTION_SAME if arch_class == replay_class
                     else DIRECTION_FLIP)
    elif arch_class in (None, "open") or replay_class is None:
        direction = DIRECTION_NOT_JUDGED
    else:
        # 非 validated 侧（not_validated/conditionally）与重放类比较
        direction = (DIRECTION_SAME if arch_class == replay_class
                     else DIRECTION_FLIP)
    if direction == DIRECTION_FLIP:
        notes.append(f"翻案：归档 {archived_status!r} vs 重放 {replay_status!r}"
                     "——翻案必须显式浮出（#122 如实）")

    return {
        "schema": RECAST_SCHEMA,
        "criteria_id": criteria.get("criteria_id"),
        "decision_rule_form": form,
        "replay_verdict": replay_verdict,
        "replay_vv_status": replay_status,
        "archived_verdict": archived_verdict,
        "archived_vv_status": archived_status,
        "direction": direction,
        "detail": detail,
        "notes": notes,
    }


def replay_batch(artifacts: Mapping[str, Mapping[str, Any]],
                 criteria_dir: str | Path, *,
                 evidence_paths: Mapping[str, str] | None = None,
                 archived_verdict_path: str | None = "verdict",
                 ) -> dict[str, Any]:
    """批量重放：全部已注册判据 × 全部产物（新判据→旧产物 / 新引擎产物→
    全部判据，两个方向同一条路径）。坏判据条目 error 登记、重放继续。

    artifacts = {产物名: 产物 dict}（只读）；evidence_paths =
    {criteria_id: 点路径}（threshold_gate 判据的证据绑定）。
    输出 summary 计数 same/flip/not_judged——flip 计数 >0 即上层判读链
    必须人工介入的信号（不静默、不凑绿）。
    """
    entries = load_criteria_dir(criteria_dir)
    crit_report: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for entry in entries:
        crit_report.append({
            "path": entry["path"], "name": entry["name"],
            "ok": entry["ok"], "criteria_id": entry.get("criteria_id"),
            "decision_rule_form": entry.get("decision_rule_form"),
            "errors": entry.get("errors") or [],
        })
        if not entry["ok"]:
            continue
        for art_name, artifact in (artifacts or {}).items():
            rep = replay_one(
                artifact, entry["criteria"],
                evidence_path=((evidence_paths or {}).get(
                    str(entry.get("criteria_id")))),
                archived_verdict_path=archived_verdict_path)
            pairs.append({"artifact": art_name, **rep})

    summary = {
        "n_criteria": len(entries),
        "n_criteria_error": sum(1 for c in crit_report if not c["ok"]),
        "n_pairs": len(pairs),
        "n_same": sum(1 for p in pairs if p["direction"] == DIRECTION_SAME),
        "n_flip": sum(1 for p in pairs if p["direction"] == DIRECTION_FLIP),
        "n_not_judged": sum(1 for p in pairs
                            if p["direction"] == DIRECTION_NOT_JUDGED),
    }
    return {
        "schema": RECAST_SCHEMA,
        "criteria": crit_report,
        "pairs": pairs,
        "summary": summary,
        "ok": summary["n_criteria_error"] == 0 and summary["n_pairs"] > 0,
    }
