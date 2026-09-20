"""recipes → agent skill 格式（阶段 2.4，LLM×EDA 调研行动项）。

把配方 YAML 确定性生成为 SKILL.md（YAML frontmatter + 工作流正文，
Claude/Copilot 通用 skill 约定），agent 可据此驱动 rfauto 的
run/tune/autotune/calibrate 命令或生成 PyAEDT/openEMS 扫描 notebook。

设计红线：纯确定性变换（LLM 不参与生成）；内容全部来自配方本身与
rfauto 固定命令面——agent 拿到的是可执行的编排知识，不是自由发挥空间。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def recipe_to_skill(recipe_path: str | Path) -> dict[str, Any]:
    """配方 → SKILL.md 内容（JSON 契约：ok/content/skill_name/output_path）。"""
    import yaml

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}

    model = str(recipe.get("model", "unknown"))
    skill_name = f"rfauto-{model.replace('_', '-')}"
    opt_params = (recipe.get("optimization") or {}).get("params") or {}
    objectives = recipe.get("objectives", [])
    setup = recipe.get("setup") or {}
    freq = setup.get("freq_range_ghz", [1.5, 3.5])

    lines: list[str] = [
        "---",
        f"name: {skill_name}",
        f"description: 用 rfauto 调优 {model}"
        f"（{len(opt_params)} 个可调参数，带内目标 {len(objectives)} 项）",
        "version: 1",
        "---",
        "",
        f"# rfauto skill：{model}",
        "",
        "## 器件与目标",
        "",
        f"- 模型插件：`{model}`；扫频 {freq[0]}–{freq[1]} GHz。",
        "- 带内目标（objectives）：",
    ]
    for o in objectives:
        lines.append(f"  - `{o.get('metric')}` {o.get('op')} "
                     f"{o.get('value')} @ {o.get('band')} GHz")
    lines += ["", "## 可调参数（optimization.params）", "",
              "| 参数 | low | high |", "|---|---|---|"]
    for name, spec in opt_params.items():
        lines.append(f"| {name} | {spec.get('low')} | {spec.get('high')} |")

    lines += [
        "",
        "## 标准工作流（typed 命令，数值由确定性内核产出）",
        "",
        "```bash",
        f"rfauto validate {path.name}          # 配方校验",
        f"rfauto run {path.name} -a fake       # fake 快验证（秒级）",
        f"rfauto autotune {path.name} --budget 3   # 确定性 critique 自治环",
        f"rfauto tune {path.name} -a openems --max-trials 30  # 外环寻优",
        f"rfauto calibrate {path.name} --sampler openems  # 代理校准（如接入）",
        "rfauto p0 <recipe> --high-adapter hfss   # 终验（商业求解器收口）",
        "```",
        "",
        "## 扫描 notebook 骨架（openEMS 快验证）",
        "",
        "```python",
        "from rfauto.adapters.em_solver_base import EMSolverConfig",
        "from rfauto.adapters.openems_solver import OpenEMSSolver",
        "",
        "solver = OpenEMSSolver(EMSolverConfig(",
        "    solver_type=\"openems\",",
        "    freq_range_ghz=tuple(" + json.dumps(freq) + "),",
        "    mesh_resolution_mm=0.45,  # 网格 base 覆盖；0=自动 λ_sub/50",
        "))",
        "solver.connect()",
        "solver.build_geometry({\"template\": None, \"params\": {}})  # 填参数点",
        "result = solver.solve()",
        "```",
        "",
        "## 边界（硬约束）",
        "",
        "- LLM/agent 不产生物理数字：所有指标来自求解器与确定性评判器。",
        "- 对配方的任何修改走沙箱草稿 → 三层 Gate 审批（agent 写面隔离）。",
        "- FAIL 如实记录，不凑绿。",
        "",
    ]

    content = "\n".join(lines)
    return {
        "ok": True,
        "skill_name": skill_name,
        "content": content,
        "output_path": str(path.parent / "SKILL.md"),
        "model": model,
        "n_params": len(opt_params),
        "n_objectives": len(objectives),
    }


def write_skill(recipe_path: str | Path,
                output_dir: str | Path | None = None) -> dict[str, Any]:
    """生成并落盘 SKILL.md（默认与配方同目录；显式 output_dir 可覆盖）。"""
    result = recipe_to_skill(recipe_path)
    if not result.get("ok"):
        return result
    out_dir = Path(output_dir) if output_dir else Path(recipe_path).parent
    # Claude/Copilot skill 约定：每个 skill 一个目录（<name>/SKILL.md）
    skill_dir = out_dir / result["skill_name"]
    skill_dir.mkdir(parents=True, exist_ok=True)
    out = skill_dir / "SKILL.md"
    out.write_text(result["content"], encoding="utf-8")
    return result | {"output_path": str(out), "written": True}


# ---------------------------------------------------------------------------
# F11 增量：typed 经验条目 → 可复用技能 / 检查项（加性接线，不改既有 API）
# ---------------------------------------------------------------------------
# 数据源是 rationale_memory 的 typed 经验条目（坑编号/结论/证据路径/适用场景/
# 动作/核对表）。本段只做确定性变换与编排：经验条目 → SKILL.md 章节 / 技能包，
# 并在"新模板冒烟 / critique 前"把检索命中项接到配方技能上（要求先离线审计）。
# 无 LLM、无网络；既有 recipe_to_skill / write_skill 行为不变。


def checklist_section(recall: Mapping[str, Any], *,
                      heading: str = "## 历史经验核对表（冒烟/critique 前必读）") -> str:
    """rationale_memory 检索结果 → SKILL.md 核对表章节（确定性）。"""
    from rfauto.service.rationale_memory import render_checklist

    return render_checklist(recall, heading=heading)


def experience_to_skill(entries: Sequence[Any] | None = None, *,
                        skill_name: str = "rfauto-experience-checklists",
                        task: Any = None) -> dict[str, Any]:
    """typed 经验条目 → 可复用 SKILL.md（核对表技能包）。

    entries=None 时用 rationale_memory.BUILTIN_ENTRIES；条目可以是
    ExperienceEntry 或 JSON 友好 dict。task 非空时附上该任务的检索命中章节。
    """
    from rfauto.service.rationale_memory import (
        BUILTIN_ENTRIES,
        ExperienceEntry,
        recall_for,
        render_checklist,
    )

    pool = list(BUILTIN_ENTRIES if entries is None else entries)
    typed = [
        e if isinstance(e, ExperienceEntry) else ExperienceEntry.from_dict(e)
        for e in pool
    ]
    recall = recall_for(task, typed) if task is not None else None

    lines: list[str] = [
        "---",
        f"name: {skill_name}",
        f"description: rfauto 历史经验核对表技能包（{len(typed)} 条 typed 经验，含证据链）",
        "version: 1",
        "---",
        "",
        f"# rfauto 经验核对表：{skill_name}",
        "",
        "> 生成：rationale_memory typed 经验条目 → skill_service 确定性接线（无 LLM）。",
        "",
        "## 经验条目总表",
        "",
        "| 坑编号 | 核对表 | 适用场景 | 动作 | 证据链 |",
        "|---|---|---|---|---|",
    ]
    for entry in sorted(typed, key=lambda e: e.lesson_id):
        lines.append(
            f"| {entry.lesson_id} | {entry.checklist} | "
            f"{'/'.join(entry.applies_to)} | {entry.action} | "
            f"{'; '.join(entry.evidence_paths)} |"
        )
    lines += [
        "",
        "## 使用口径（硬约束）",
        "",
        "- 新模板冒烟 / critique 前先对本节条目做检索，命中项逐条核对；",
        "- 命中 requires_offline_audit 的条目必须先离线审计（零仿真）再冒烟；",
        "- 数值仍由确定性内核产出，经验条目只给场景与动作（铁律 7）。",
        "",
    ]

    if recall is not None and recall.get("ok"):
        section = render_checklist(recall)
        if section:
            lines += [section]
        else:
            lines += ["## 历史经验核对表（本次任务）", "",
                      "（本次任务未命中历史经验——无相近坑编号）", ""]
    content = "\n".join(lines)
    return {
        "ok": True,
        "skill_name": skill_name,
        "content": content,
        "n_entries": len(typed),
        "checklists": sorted({e.checklist for e in typed if e.checklist}),
        "recall": recall,
        "output_path": f"{skill_name}/SKILL.md",
    }


def write_experience_skill(entries: Sequence[Any] | None = None,
                           output_dir: str | Path = "skills", *,
                           skill_name: str = "rfauto-experience-checklists",
                           task: Any = None) -> dict[str, Any]:
    """经验核对表技能包落盘（<output_dir>/<skill_name>/SKILL.md）。"""
    result = experience_to_skill(entries, skill_name=skill_name, task=task)
    if not result.get("ok"):
        return result
    skill_dir = Path(output_dir) / result["skill_name"]
    skill_dir.mkdir(parents=True, exist_ok=True)
    out = skill_dir / "SKILL.md"
    out.write_text(result["content"], encoding="utf-8")
    return result | {"output_path": str(out), "written": True}


def recipe_to_skill_with_recall(recipe_path: str | Path, task: Any, *,
                                entries: Sequence[Any] | None = None,
                                output_dir: str | Path | None = None) -> dict[str, Any]:
    """recipe_to_skill + F11 经验核对表章节（加性：既有函数与输出不变）。

    task 为本次冒烟/critique 的任务描述（模板名、场景、标签等）。
    命中历史经验时在"边界（硬约束）"章前插入核对表章节。
    """
    from rfauto.service.rationale_memory import recall_for, render_checklist

    result = recipe_to_skill(recipe_path)
    if not result.get("ok"):
        return result
    recall = recall_for(task, entries)
    section = render_checklist(recall) if recall.get("ok") else ""
    content = result["content"]
    if section:
        marker = "## 边界（硬约束）"
        content = (content.replace(marker, section + "\n" + marker, 1)
                   if marker in content else content + "\n" + section)
    out = result | {
        "content": content,
        "recall": recall,
        "offline_audit_required": bool(recall.get("require_offline_audit")),
    }
    if output_dir is not None:
        skill_dir = Path(output_dir) / result["skill_name"]
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / "SKILL.md"
        path.write_text(content, encoding="utf-8")
        out = out | {"output_path": str(path), "written": True}
    return out

