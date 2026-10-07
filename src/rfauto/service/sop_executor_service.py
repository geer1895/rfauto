"""EP-8 SOP 执行器化（检查单→可执行步骤；文档即代码，dry-run 面）。

规格 研究扩充 round18 §二 EP-8：playbook 条目
加 ``commands`` 字段→CLI 序列+dry-run（文档即代码）；通用 SOP 五段式模板。

**安全语义（本模块永不执行命令）**：``dry_run`` 只做解析与校验——shlex
分词、allowlist 前缀核对、危险令牌扫描、缺省输出计划（plan）。执行面
留 CLI 归属批次（本席禁改 cli）；"执行器化"落点是**文档即代码的校验链**：
SOP 文本里的每条命令可机检（可解析/在 allowlist 内/无危险令牌），离开
allowlist 的命令如实标 blocked 而非静默放行（#316 多报不放过）。

**通用 SOP 五段式模板**（rfauto-sop/v1）::

    {"id": "SOP-...", "title": "...",
     "purpose": "目的",                     # 段①目的
     "prerequisites": ["前置条件", ...],     # 段②前置条件
     "steps": [                             # 段③步骤（commands 字段=可执行面）
       {"name": "...", "commands": ["rfauto ...", ...], "note"?: "..."}, ...],
     "verification": ["验证判据（预声明）", ...],  # 段④验证
     "rollback": ["回滚/记录动作", ...]}     # 段⑤回滚与记录

**playbook 条目接入**：``sop_from_playbook_entry`` 消费 explain 面
（knowledge/diagnostics/playbook.yaml 同构）条目形态——{id/name/checklist/
steps:[...]}，commands 字段给定时转五段式；缺 steps 诚实 ValueError。

接口纪律：dict/JSON 进出；shlex 确定性解析；零 subprocess 零 IO 零网络。
"""

from __future__ import annotations

import shlex
from typing import Any

__all__ = [
    "DANGEROUS_TOKENS",
    "DEFAULT_ALLOWLIST",
    "SOP_SCHEMA",
    "dry_run",
    "render_sop_markdown",
    "sop_from_playbook_entry",
    "validate_sop",
]

SOP_SCHEMA = "rfauto-sop/v1"

#: dry-run 缺省 allowlist（前缀语义：argv[0] 或 "argv[0] argv[1]" 前缀匹配；
#: 本仓 CLI 命令面——执行面归属批次扩表时以实注册表为准）
DEFAULT_ALLOWLIST: tuple[str, ...] = (
    "rfauto",
    "python -m rfauto",
    ".venv/Scripts/python -m rfauto",
)

#: 危险令牌（词元级精确匹配；任一命中=blocked——dry-run 面永不放行）
DANGEROUS_TOKENS: frozenset[str] = frozenset({
    "rm", "rmdir", "del", "rd", "format", "taskkill", "Stop-Process",
    "Remove-Item", "shutdown", "mkfs", "dd", "git", "pip", "curl", "wget",
    "Invoke-WebRequest", "schtasks", "reg", "wmic",
})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须为非空字符串")
    return value


def _str_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{name} 必须为非空字符串列表")
    return [_text(v, name) for v in value]


def validate_sop(sop: Any) -> dict[str, Any]:
    """五段式 SOP 校验+归一（段③ steps.commands 强制存在——执行器化的
    最小契约；无 commands 的纯散文 SOP 如实拒绝，不冒充可执行）。"""
    if not isinstance(sop, dict):
        raise ValueError("SOP 必须为 dict（rfauto-sop/v1）")
    out: dict[str, Any] = {
        "schema": SOP_SCHEMA,
        "id": _text(sop.get("id"), "id"),
        "title": _text(sop.get("title"), "title"),
        "purpose": _text(sop.get("purpose"), "purpose"),
        "prerequisites": _str_list(sop.get("prerequisites"), "prerequisites"),
    }
    steps_raw = sop.get("steps")
    if not isinstance(steps_raw, (list, tuple)) or not steps_raw:
        raise ValueError("steps 必须为非空列表（执行器化最小契约）")
    steps: list[dict[str, Any]] = []
    for i, raw in enumerate(steps_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"steps[{i}] 必须为 dict")
        step: dict[str, Any] = {
            "name": _text(raw.get("name"), f"steps[{i}].name"),
            "commands": _str_list(raw.get("commands"), f"steps[{i}].commands"),
        }
        if raw.get("note") is not None:
            step["note"] = _text(raw.get("note"), f"steps[{i}].note")
        steps.append(step)
    out["steps"] = steps
    out["verification"] = _str_list(sop.get("verification"), "verification")
    out["rollback"] = _str_list(sop.get("rollback"), "rollback")
    return out


def sop_from_playbook_entry(entry: Any) -> dict[str, Any]:
    """playbook/explain 面条目 → 五段式 SOP（commands 字段=可执行面）。

    接受形态：{id/name, checklist?, steps: [{name, commands, note?}...]，
    evidence_paths?→verification 缺省段}；五段缺省段如实填占位文本
    （"（原条目未提供——人工补齐）"），不冒充已完备。
    """
    if not isinstance(entry, dict):
        raise ValueError("playbook 条目必须为 dict")
    sop_id = _text(entry.get("id"), "id")
    title = _text(entry.get("title") or entry.get("name"), "title/name")
    steps_raw = entry.get("steps")
    if not isinstance(steps_raw, (list, tuple)) or not steps_raw:
        raise ValueError(f"playbook 条目 {sop_id} 无 steps——不可执行器化（如实拒绝）")
    steps: list[dict[str, Any]] = []
    for i, raw in enumerate(steps_raw):
        if not isinstance(raw, dict):
            raise ValueError(f"steps[{i}] 必须为 dict")
        cmds = raw.get("commands")
        steps.append({
            "name": _text(raw.get("name") or raw.get("action"), f"steps[{i}].name"),
            "commands": _str_list(cmds, f"steps[{i}].commands") if cmds is not None else [],
        })
    placeholder = "（原条目未提供——人工补齐）"
    return validate_sop({
        "id": sop_id,
        "title": title,
        "purpose": str(entry.get("purpose") or entry.get("description") or placeholder),
        "prerequisites": entry.get("prerequisites") or [placeholder],
        "steps": steps,
        "verification": entry.get("verification") or entry.get("evidence_paths") or [placeholder],
        "rollback": entry.get("rollback") or [placeholder],
    })


def dry_run(sop: Any, *, allowlist: Any = None) -> dict[str, Any]:
    """SOP → dry-run 计划（**永不执行**）。

    逐命令：shlex 分词 → allowlist 前缀核对 → 危险令牌扫描；命令不可解析
    （shlex ValueError）如实 blocked。返回 {ok, n_commands, n_blocked,
    plan, blocked}——ok=False 当且仅当有 blocked（校验链语义：文档即代码
    的门=零 blocked）。
    """
    doc = validate_sop(sop)
    allowed = tuple(allowlist) if allowlist is not None else DEFAULT_ALLOWLIST
    plan: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for step in doc["steps"]:
        for cmd in step["commands"]:
            item: dict[str, Any] = {"step": step["name"], "command": cmd}
            try:
                argv = shlex.split(cmd, posix=True)
            except ValueError:
                item.update({"status": "blocked", "reason": "shlex 解析失败"})
                blocked.append(dict(item))
                plan.append(dict(item))
                continue
            item["argv"] = argv
            joined = " ".join(argv)
            danger = [tok for tok in argv if tok in DANGEROUS_TOKENS]
            if danger:
                item.update({"status": "blocked", "reason": f"危险令牌：{danger}"})
                blocked.append(dict(item))
            elif not any(joined == a or joined.startswith(a + " ") for a in allowed):
                item.update({"status": "blocked",
                             "reason": f"不在 allowlist（前缀词表 {list(allowed)}）"})
                blocked.append(dict(item))
            else:
                item["status"] = "ok"
            plan.append(dict(item))
    return {
        "schema": SOP_SCHEMA,
        "sop_id": doc["id"],
        "ok": not blocked,
        "n_commands": len(plan),
        "n_blocked": len(blocked),
        "plan": plan,
        "blocked": blocked,
        "note": "dry-run 面永不执行命令；执行面留 CLI 归属批次（allowlist 以实注册表为准）",
    }


def render_sop_markdown(sop: Any) -> str:
    """SOP → markdown（五段式文档即代码：命令在 fenced block 里可复制）。"""
    doc = validate_sop(sop)
    lines = [
        f"# SOP：{doc['id']} {doc['title']}",
        "",
        "## ① 目的",
        "",
        doc["purpose"],
        "",
        "## ② 前置条件",
        "",
    ]
    lines += [f"- {p}" for p in doc["prerequisites"]]
    lines += ["", "## ③ 步骤", ""]
    for step in doc["steps"]:
        lines.append(f"### {step['name']}")
        lines.append("")
        for cmd in step["commands"]:
            lines.append("```bash")
            lines.append(cmd)
            lines.append("```")
        if step.get("note"):
            lines.append("")
            lines.append(f"注：{step['note']}")
        lines.append("")
    lines += ["## ④ 验证（预声明判据）", ""]
    lines += [f"- {v}" for v in doc["verification"]]
    lines += ["", "## ⑤ 回滚与记录", ""]
    lines += [f"- {r}" for r in doc["rollback"]]
    return "\n".join(lines) + "\n"
