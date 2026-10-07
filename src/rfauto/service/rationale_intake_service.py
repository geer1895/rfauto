"""EP-7 专家经验采集框架（访谈结构 YAML → 经验条目/rules 候选 verify 分级）。

规格 研究扩充 round18 §二 EP-7：访谈结构
YAML→rules 候选走 verify 分级；消费面=service/rationale_memory（F11 自
进化经验记忆，本模块只读复用其 ExperienceEntry/recall_for，不修改）。

**访谈结构 schema**（rfauto-interview/v1）::

    {"interviewee": "...", "date": "...", "topic": "...",
     "entries": [
       {"situation": "什么场景/症状",          # 必填非空
        "decision": "一句话结论",              # 必填非空 → ExperienceEntry.conclusion
        "rationale": "为什么/怎么做",          # 必填非空 → ExperienceEntry.action
        "applies_to": ["关键词", ...],         # 缺省 [situation]
        "evidence": ["路径/坑号", ...],        # 可选 → evidence_paths
        "pit_no": "#198",                     # 可选 → lesson_id（缺省 INTAKE-<i>）
        "requires_offline_audit": true,       # 可选
        "checklist": "网格伪象核对表",         # 可选
        "rule": {                             # 可选：rules.yaml 同构候选
          "id": "R010", "category": "diagnosis",
          "hint": "...", "applicable_models": ["all"],
          "machine_check": {"test": "tests/...", "runner": "pytest"}
        }}}]

**verify 分级**（rules.yaml 先例：R001/R005-R007 带 verify、R002-R004
"不可机器验证"显式省略不凑绿）：rule 候选带合法 machine_check（test/runner
皆非空串）→ ``verify`` 字段照录 + grading="machine"；否则 verify 显式
省略 + grading="manual"（分级随行披露，不冒充可机检）。

**消费面**：``to_experience_entries`` 产出 typed ExperienceEntry 列表，
可直接喂 rationale_memory.recall_for/checklist_for（冒烟/任务书生成前
检索命中）——采集→记忆→检索闭环全确定性（零 LLM）。

**沉淀面**（ge8e J1-2 补全）：``save_intake_entries`` 把访谈条目以 JSONL
追加持久化到 ``knowledge/rationale/intake_entries.jsonl``（缺省；目录不
存在则建；knowledge/ 既有资产零改写——本面只写自己新建的单一追加文件），
按 lesson_id 去重幂等，原子 tmp+replace 落盘；``load_intake_entries``
重启后（新实例）回读 typed 条目。设计流注入（冒烟/critique 前自动消费
记忆文件）**只登记不实施**——注入点选择需用户裁决，留 followUp 票。

接口纪律：dict/JSON/YAML 进出；零网络零 LLM；访谈文件只读；写面仅限
本模块的 JSONL 记忆文件（原子替换）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.rationale_memory import ExperienceEntry

__all__ = [
    "INTAKE_MEMORY_DIRNAME",
    "INTAKE_MEMORY_FILENAME",
    "INTERVIEW_SCHEMA",
    "default_intake_memory_path",
    "intake_review",
    "load_intake_entries",
    "load_interview_yaml",
    "save_intake_entries",
    "to_experience_entries",
]

INTERVIEW_SCHEMA = "rfauto-interview/v1"

# 沉淀面（J1-2）：knowledge/ 下唯一写面（新建子目录+单一 JSONL 追加文件）
INTAKE_MEMORY_DIRNAME = "rationale"
INTAKE_MEMORY_FILENAME = "intake_entries.jsonl"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须为非空字符串")
    return value


def _str_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [_text(v, name) for v in value]
    raise ValueError(f"{name} 必须为字符串或字符串列表")


def load_interview_yaml(path: str | Path) -> dict[str, Any]:
    """访谈 YAML 文件 → 结构 dict（yaml.safe_load 只读）。"""
    p = Path(path)
    import yaml

    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("访谈 YAML 顶层必须为映射（rfauto-interview/v1）")
    return data


def _normalize_entry(raw: Any, index: int, errors: list[str]) -> dict[str, Any] | None:
    """单条访谈 → 归一条目（字段错误进 errors 不炸整批——采集面宽容收
    录、逐条报告，与 recall 面的严格性分离）。"""
    where = f"entries[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: 条目必须为 dict")
        return None
    try:
        situation = _text(raw.get("situation"), f"{where}.situation")
        decision = _text(raw.get("decision"), f"{where}.decision")
        rationale = _text(raw.get("rationale"), f"{where}.rationale")
    except ValueError as exc:
        errors.append(str(exc))
        return None
    pit_no = raw.get("pit_no")
    rule = raw.get("rule")
    rule_out: dict[str, Any] | None = None
    if rule is not None:
        if not isinstance(rule, dict):
            errors.append(f"{where}.rule: 必须为 dict")
        else:
            try:
                rule_out = {
                    "id": _text(rule.get("id"), f"{where}.rule.id"),
                    "category": _text(rule.get("category"), f"{where}.rule.category"),
                    "description": decision,
                }
                if rule.get("hint") is not None:
                    rule_out["hint"] = _text(rule.get("hint"), f"{where}.rule.hint")
                models = _str_list(rule.get("applicable_models"), f"{where}.rule.applicable_models")
                if models:
                    rule_out["applicable_models"] = models
                mc = rule.get("machine_check")
                if mc is not None:
                    mc_ok = (
                        isinstance(mc, dict)
                        and isinstance(mc.get("test"), str) and mc["test"].strip()
                        and isinstance(mc.get("runner"), str) and mc["runner"].strip()
                    )
                    if mc_ok:
                        rule_out["verify"] = {
                            "test": mc["test"],
                            "runner": mc["runner"],
                        }
                        rule_out["grading"] = "machine"
                    else:
                        rule_out["grading"] = "manual"
                        rule_out["grading_note"] = "machine_check 缺合法 test/runner——verify 显式省略（不凑绿）"
                else:
                    rule_out["grading"] = "manual"
                    rule_out["grading_note"] = "无 machine_check——verify 显式省略（rules.yaml R002-R004 先例）"
            except ValueError as exc:
                errors.append(str(exc))
                rule_out = None
    return {
        "lesson_id": _text(pit_no, f"{where}.pit_no") if pit_no is not None else f"INTAKE-{index:03d}",
        "conclusion": decision,
        "action": rationale,
        "applies_to": _str_list(raw.get("applies_to"), f"{where}.applies_to") or [situation],
        "evidence_paths": _str_list(raw.get("evidence"), f"{where}.evidence"),
        "checklist": _text(raw.get("checklist"), f"{where}.checklist") if raw.get("checklist") is not None else "访谈采集核对表",
        "requires_offline_audit": bool(raw.get("requires_offline_audit", False)),
        "rule_candidate": rule_out,
    }


def intake_review(payload: Any) -> dict[str, Any]:
    """访谈结构 → {ok, errors, entries, rule_candidates, grading 汇总}。

    ok=True 当且仅当 errors 为空且至少一条有效（空访谈如实 ok=False）。
    """
    if not isinstance(payload, dict):
        raise ValueError("访谈载荷必须为 dict（rfauto-interview/v1）")
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, (list, tuple)):
        raise ValueError("访谈载荷必须含 entries 列表")
    errors: list[str] = []
    norm: list[dict[str, Any]] = []
    for i, raw in enumerate(entries_raw):
        item = _normalize_entry(raw, i, errors)
        if item is not None:
            norm.append(item)
    rule_candidates = [
        dict(e["rule_candidate"]) for e in norm if e["rule_candidate"] is not None
    ]
    n_machine = sum(1 for r in rule_candidates if r.get("grading") == "machine")
    return {
        "schema": INTERVIEW_SCHEMA,
        "interviewee": payload.get("interviewee"),
        "topic": payload.get("topic"),
        "ok": not errors and bool(norm),
        "errors": errors,
        "n_entries": len(norm),
        "entries": norm,
        "rule_candidates": rule_candidates,
        "grading_summary": {"machine": n_machine, "manual": len(rule_candidates) - n_machine},
    }


def to_experience_entries(payload: Any) -> list[ExperienceEntry]:
    """访谈结构 → typed ExperienceEntry 列表（rationale_memory 消费面）。

    有字段级错误时 ValueError（消费面前置严格校验——记忆库不收残条目）。
    """
    review = intake_review(payload)
    if not review["ok"]:
        raise ValueError(f"访谈条目存在错误，不入记忆库：{review['errors']}")
    return [
        ExperienceEntry(
            lesson_id=e["lesson_id"],
            conclusion=e["conclusion"],
            evidence_paths=tuple(e["evidence_paths"]),
            applies_to=tuple(e["applies_to"]),
            action=e["action"],
            checklist=e["checklist"],
            requires_offline_audit=e["requires_offline_audit"],
        )
        for e in review["entries"]
    ]


# ─── 沉淀面（ge8e J1-2 补全）：JSONL 追加持久化 + 重启回读 ──────────────────
# 设计流注入（冒烟/critique 前自动消费记忆文件）只登记不实施——注入点选择
# 需用户裁决，留 followUp 票（见模块 docstring「沉淀面」节）。


def default_intake_memory_path() -> Path:
    """经验记忆缺省落盘路径：<repo>/knowledge/rationale/intake_entries.jsonl。

    （源码布局推导，与 infra/anchors_store 的注册表缺省路径同口径。）
    """
    return (Path(__file__).resolve().parents[3] / "knowledge"
            / INTAKE_MEMORY_DIRNAME / INTAKE_MEMORY_FILENAME)


def _load_jsonl_records(target: Path) -> tuple[list[dict[str, Any]], int]:
    """读 JSONL 记录（坏行跳过计数，不抛——读面 best-effort #105）。"""
    records: list[dict[str, Any]] = []
    bad = 0
    for line in target.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except ValueError:
            bad += 1
            continue
        if isinstance(rec, dict):
            records.append(rec)
        else:
            bad += 1
    return records, bad


def save_intake_entries(payload: Any, *,
                        path: str | Path | None = None) -> dict[str, Any]:
    """访谈结构 → 经验记忆 JSONL 追加持久化（幂等去重 + 原子落盘）。

    - 目标：``path`` 或缺省 ``knowledge/rationale/intake_entries.jsonl``
      （目录不存在则建；knowledge/ 既有资产零改写——本面只写自己新建的
      单一追加文件）；
    - 追加语义：lesson_id 已在档的条目跳过（重复 intake 同一访谈只落一次
      ——幂等），新条目追加在既有内容尾部，既有字节零改写；
    - 原子写：同目录 tmp + ``os.replace``（J1-2 预声明口径）；
    - 访谈条目有字段级错误 → error_envelope（不凑绿，与 to_experience_entries
      同一严格门前置）。

    Returns:
        {ok, path, n_appended, n_total, skipped, n_bad_lines}
    """
    target = Path(path) if path is not None else default_intake_memory_path()
    try:
        entries = to_experience_entries(payload)
    except ValueError as exc:
        return error_envelope([str(exc)])
    if not entries:
        return error_envelope(["无有效条目可持久化"])
    existing: list[dict[str, Any]] = []
    bad_before = 0
    if target.exists():
        existing, bad_before = _load_jsonl_records(target)
    known_ids = {str(rec.get("lesson_id") or "") for rec in existing}
    new_entries = [e for e in entries if e.lesson_id not in known_ids]
    skipped = [e.lesson_id for e in entries if e.lesson_id in known_ids]
    if not new_entries:
        return ok_envelope(path=str(target), n_appended=0,
                           n_total=len(existing), skipped=skipped,
                           n_bad_lines=bad_before)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        lines = [json.dumps(e.to_dict(), ensure_ascii=False, sort_keys=True)
                 for e in new_entries]
        merged = original
        if merged and not merged.endswith("\n"):
            merged += "\n"
        merged += "\n".join(lines) + "\n"
        tmp = target.with_name(f"{target.name}.tmp{os.getpid()}")
        tmp.write_text(merged, encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        return error_envelope([f"经验记忆落盘失败: {exc}"])
    return ok_envelope(path=str(target), n_appended=len(new_entries),
                       n_total=len(existing) + len(new_entries),
                       skipped=skipped, n_bad_lines=bad_before)


def load_intake_entries(path: str | Path | None = None) -> dict[str, Any]:
    """经验记忆 JSONL → typed 条目（重启后新实例可见；坏行跳过留痕）。

    Returns:
        {ok, path, n_entries, entries, n_bad_lines}；文件不存在 → ok=False。
    """
    target = Path(path) if path is not None else default_intake_memory_path()
    if not target.exists():
        return error_envelope([f"经验记忆文件不存在: {target}"])
    records, bad = _load_jsonl_records(target)
    entries = [ExperienceEntry.from_dict(rec) for rec in records]
    return ok_envelope(path=str(target), n_entries=len(entries),
                       entries=entries, n_bad_lines=bad)
