"""skill_autopilot：run PASS → skill 自动沉淀消费侧闭环（AD-7，round15 §五）。

规格：「run PASS → 自动 experience_to_skill 落盘 + 对齐 agentskills.io
渐进披露」（P2/M）。现状痛点（调研 §五现状）：skill_service 的
recipe_to_skill/experience_to_skill **零调用方**——本模块补消费侧闭环：
PASS 判定（确定性）→ 经验核对表技能包（复用 experience_to_skill）→
agentskills.io 对齐落盘（frontmatter + 渐进披露），全链零 LLM、零网络
（铁律 7：沉淀内容只来自经验条目与 run 溯源指针，无新数字）。

PASS 判据（预声明）：verdict 规范化后 ∈ PASS_VERDICTS
（{"PASS", "HEALTHY", "PASSED"}——覆盖 autotune critique / health_check_run /
campaign gate 三源口径）；FAIL/SUSPECT/UNHEALTHY/缺 verdict 一律不沉淀，
返回 {"ok": True, "deposited": False, "reason": ...}（如实不凑，#122）。

agentskills.io（SKILL.md 开放标准）对齐口径：
- frontmatter：``name`` 须匹配 ^[a-z0-9][a-z0-9-]*$，``description``
  1..1024 字符，``version`` 正整数（version 为仓内 skill_service 既有
  惯例字段，保留）；
- 渐进披露三层：元数据（frontmatter，常驻）→ SKILL.md 正文（触发即读，
  保持概览+工作流）→ references/ 明细（按需加载：核对表全文进
  references/checklists.md，正文只留指引）。

落盘位置：缺省 ``skills/``（与 skill_service.write_experience_skill 同缺省；
审计 D 轴 followUp 建议 knowledge/skills/，交由调用方显式传 output_dir
决定——本模块不写 knowledge/ 运行时只读区）。全部写路径 best-effort
（#105）：失败返回 ok=False 不抛。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

SKILL_AUTOPILOT_SCHEMA = "rfauto-skill-autopilot-v1"

#: PASS 判据白名单（三源 verdict 口径，见模块 docstring）。
PASS_VERDICTS = frozenset({"PASS", "HEALTHY", "PASSED"})

#: agentskills.io frontmatter name 规则（小写字母数字与连字符）。
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: description 长度上限（agentskills.io 口径）。
DESCRIPTION_MAX = 1024

#: 渐进披露明细层缺省文件名。
REFERENCES_DIRNAME = "references"
CHECKLISTS_FILENAME = "checklists.md"

#: 已沉淀 run 去重集（ge8e J1-1 生产接线幂等：同一 run id 只沉淀一次）。
#: record 直给路径不去重（显式调用语义归调用方）；进程生命周期内存态。
_DEPOSITED_RUN_IDS: set[str] = set()


def normalize_verdict(record: Mapping[str, Any]) -> str | None:
    """从 record 提取并规范化 verdict（verdict/gate/status 三键按序）。"""
    for key in ("verdict", "gate", "status"):
        value = record.get(key)
        if value is not None:
            return str(getattr(value, "value", value)).strip().upper()
    return None


def _default_skill_name(task: Any) -> str:
    text = str(task or "")
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:40].strip("-")
    return f"rfauto-run-{slug}" if slug else "rfauto-run-pass"


def _checklists_reference(skill_result: Mapping[str, Any]) -> str:
    """experience_to_skill 正文 → references/checklists.md 明细层内容。"""
    content = str(skill_result.get("content") or "")
    marker = "## 经验条目总表"
    idx = content.find(marker)
    if idx < 0:
        return content
    return content[idx:]


def _overview_body(skill_result: Mapping[str, Any], record: Mapping[str, Any],
                   skill_name: str, task: Any) -> str:
    """SKILL.md 概览正文（渐进披露第二层：触发即读的精简层）。"""
    lines = [
        f"# rfauto 运行技能包：{skill_name}",
        "",
        "> 来源：run PASS 自动沉淀（skill_autopilot，零 LLM）；核对表明细见",
        f"[{CHECKLISTS_FILENAME}]({REFERENCES_DIRNAME}/{CHECKLISTS_FILENAME})"
        "（渐进披露按需加载层）。",
        "",
        "## 使用口径（硬约束）",
        "",
        "- 命中 requires_offline_audit 的条目必须先离线审计（零仿真）再冒烟；",
        "- 数值由确定性内核产出，本技能包只给场景与动作（铁律 7）；",
        "- 对配方的任何修改走沙箱草稿 → 三层 Gate（agent 写面隔离，铁律 6）。",
        "",
    ]
    run_id = record.get("run_id") or record.get("id")
    if run_id:
        lines += ["## 溯源", "",
                  f"- 沉淀来源 run：`{run_id}`（verdict {record.get('verdict')}）"]
        recipe = record.get("recipe_path")
        if recipe:
            lines.append(f"- 配方：`{recipe}`")
        if task:
            lines.append(f"- 任务语境：{task}")
        lines.append("")
    return "\n".join(lines)


def build_run_skill(record: Mapping[str, Any], *, skill_name: str | None = None,
                    task: Any = None,
                    entries: Sequence[Any] | None = None) -> dict[str, Any]:
    """PASS record → agentskills.io 对齐的技能包文件映射（纯构造，零 IO）。"""
    from rfauto.service.skill_service import experience_to_skill

    verdict = normalize_verdict(record)
    if verdict is None:
        return {"ok": False, "deposited": False,
                "errors": ["record 缺 verdict/gate/status——判据缺失不沉淀"]}
    if verdict not in PASS_VERDICTS:
        return {"ok": False, "deposited": False,
                "errors": [f"verdict={verdict} 不在 PASS 白名单 "
                           f"{sorted(PASS_VERDICTS)}——失败/存疑如实不沉淀"]}

    skill_result = experience_to_skill(entries, skill_name="pending", task=task)
    name = skill_name or _default_skill_name(task)
    if not SKILL_NAME_RE.match(name):
        return {"ok": False, "deposited": False,
                "errors": [f"skill_name={name!r} 不符 agentskills.io "
                           "name 规则（^[a-z0-9][a-z0-9-]*$）"]}
    description = (f"rfauto PASS 运行沉淀技能包（{skill_result.get('n_entries', 0)} "
                   f"条 typed 经验，含证据链；verdict {verdict}）")[:DESCRIPTION_MAX]
    frontmatter = (f"---\nname: {name}\ndescription: {description}\n"
                   "version: 1\n---\n")
    body = _overview_body(skill_result, record, name, task)
    skill_md = frontmatter + "\n" + body
    checklists_md = (f"# {name} · 核对表明细（渐进披露按需加载层）\n\n"
                     + _checklists_reference(skill_result))
    return {
        "ok": True, "deposited": False,  # deposited 由 write_run_skill 翻转
        "skill_name": name, "verdict": verdict,
        "description": description,
        "files": {
            "SKILL.md": skill_md,
            f"{REFERENCES_DIRNAME}/{CHECKLISTS_FILENAME}": checklists_md,
        },
        "n_entries": skill_result.get("n_entries"),
        "schema_version": SKILL_AUTOPILOT_SCHEMA,
        "errors": [],
    }


def write_run_skill(record: Mapping[str, Any], *, output_dir: str | Path = "skills",
                    skill_name: str | None = None, task: Any = None,
                    entries: Sequence[Any] | None = None) -> dict[str, Any]:
    """构造 + 落盘：<output_dir>/<skill_name>/SKILL.md + references/。

    返回构造契约并补 output_path/deposited；写失败如实 ok=False（#105）。
    """
    built = build_run_skill(record, skill_name=skill_name, task=task,
                            entries=entries)
    if not built.get("ok"):
        return built
    try:
        skill_dir = Path(output_dir) / built["skill_name"]
        skill_dir.mkdir(parents=True, exist_ok=True)
        for rel, content in built["files"].items():
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    except OSError as exc:
        # ge8e W2 快偿（R5-06）：混合 **unpack 裸信封 → 包裹重建（D5 二批
        # 同款：内层字面量保持"后者覆盖"语义，键集/键序零变化）
        return ok_envelope(**{**built, "ok": False,
                              "errors": built["errors"] + [f"落盘失败: {exc}"]})
    return {**built, "deposited": True,
            "output_path": str(Path(output_dir) / built["skill_name"] / "SKILL.md")}


def validate_agentskills_md(path: str | Path) -> dict[str, Any]:
    """SKILL.md 对 agentskills.io 口径的确定性校验（frontmatter+渐进披露）。"""
    import yaml

    p = Path(path)
    errors: list[str] = []
    if not p.exists():
        return error_envelope([f"SKILL.md 不存在: {p}"])
    raw = p.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        errors.append("缺 YAML frontmatter 开头（须以 '---' 行起）")
        return error_envelope(errors, )
    close = raw.find("\n---\n", 4)
    if close < 0:
        return error_envelope(["缺 frontmatter 收尾（'---' 行）"])
    try:
        front = yaml.safe_load(raw[4:close]) or {}
    except ValueError as exc:
        return error_envelope([f"frontmatter 解析失败: {exc}"])
    if not isinstance(front, dict):
        return error_envelope(["frontmatter 必须是映射"])
    name = str(front.get("name") or "")
    if not SKILL_NAME_RE.match(name):
        errors.append(f"name={name!r} 不符 ^[a-z0-9][a-z0-9-]*$")
    description = str(front.get("description") or "")
    if not description.strip():
        errors.append("description 为空（agentskills.io 必填）")
    elif len(description) > DESCRIPTION_MAX:
        errors.append(f"description 超 {DESCRIPTION_MAX} 字符")
    version = front.get("version")
    if version is not None and (isinstance(version, bool) or not isinstance(
            version, int) or version < 1):
        errors.append(f"version={version!r} 须为正整数")
    body = raw[close + 5:]
    if not body.strip():
        errors.append("正文为空")
    refs = re.findall(r"\]\((references/[^)]+)\)", body)
    for rel in refs:
        if not (p.parent / rel).exists():
            errors.append(f"渐进披露引用缺失: {rel}")
    # ge8e W2 快偿（R5-06）：裸 ok 信封 → 构造器（键集/键序/语义零变化）
    if errors:
        return error_envelope(errors, name=name, n_references=len(refs))
    return ok_envelope(errors=errors, name=name, n_references=len(refs))


def auto_deposit_hook(record: Mapping[str, Any] | None = None,
                      run_id: str | None = None, *,
                      output_dir: str | Path = "skills",
                      skill_name: str | None = None, task: Any = None,
                      entries: Sequence[Any] | None = None) -> dict[str, Any]:
    """接线钩子：record 直给或 run_id（经 health_check_run 判定）二选一。

    run_id 路径 best-effort：health 面不可用/verdict 非 healthy 都如实
    不沉淀（{"ok": True, "deposited": False, reason}），不抛不阻塞；
    同一 run id 沉淀成功后再次触发幂等跳过（ge8e J1-1，_DEPOSITED_RUN_IDS）。
    """
    from_run_id = record is None
    if record is None:
        if not run_id:
            return {"ok": False, "deposited": False,
                    "errors": ["record 与 run_id 至少给一个"]}
        try:
            from rfauto.service.health_service import health_check_run

            report = health_check_run(str(run_id))
        except Exception as exc:  # health 面不可用：如实不沉淀（#105）
            return ok_envelope(
                deposited=False,
                reason=f"health 判定不可用（{type(exc).__name__}），"
                              "不沉淀",
                errors=[],
            )
        verdict = str(report.get("verdict") or "").upper()
        if verdict != "HEALTHY":
            return ok_envelope(
                deposited=False,
                reason=f"health verdict={verdict or 'UNKNOWN'} 非 "
                              "HEALTHY，不沉淀",
                errors=[],
            )
        if str(run_id) in _DEPOSITED_RUN_IDS:  # 幂等：同 run 只沉淀一次
            return ok_envelope(
                deposited=False,
                reason=f"run {run_id} 已沉淀过（幂等跳过，J1-1）",
                errors=[],
            )
        record = {"verdict": "HEALTHY", "run_id": run_id}
    result = write_run_skill(record, output_dir=output_dir,
                             skill_name=skill_name, task=task, entries=entries)
    if from_run_id and result.get("deposited"):
        _DEPOSITED_RUN_IDS.add(str(run_id))
    return result
