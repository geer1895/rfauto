"""recipes → agent skill 格式（阶段 2.4，LLM×EDA 调研行动项）。

把配方 YAML 确定性生成为 SKILL.md（YAML frontmatter + 工作流正文，
Claude/Copilot 通用 skill 约定），agent 可据此驱动 rfauto 的
run/tune/autotune/calibrate 命令或生成 PyAEDT/openEMS 扫描 notebook。

设计红线：纯确定性变换（LLM 不参与生成）；内容全部来自配方本身与
rfauto 固定命令面——agent 拿到的是可执行的编排知识，不是自由发挥空间。
"""

from __future__ import annotations

import json
import re
import textwrap
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope


def recipe_to_skill(recipe_path: str | Path) -> dict[str, Any]:
    """配方 → SKILL.md 内容（JSON 契约：ok/content/skill_name/output_path）。"""
    import yaml

    path = Path(recipe_path)
    if not path.exists():
        return error_envelope([f"配方不存在: {path}"])
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
    return ok_envelope(
        skill_name=skill_name,
        content=content,
        # T-Q10 #144 修复：信封 output_path 与 write_skill 实际落盘位置
        # （<配方目录>/<skill_name>/SKILL.md）对齐——旧值缺 skill_name
        # 子目录组件，按信封路径自行写盘的调用方会写错位置。
        output_path=str(path.parent / skill_name / "SKILL.md"),
        model=model,
        n_params=len(opt_params),
        n_objectives=len(objectives),
    )


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
    return ok_envelope(
        skill_name=skill_name,
        content=content,
        n_entries=len(typed),
        checklists=sorted({e.checklist for e in typed if e.checklist}),
        recall=recall,
        output_path=f"{skill_name}/SKILL.md",
    )


def write_experience_skill(entries: Sequence[Any] | None = None,
                           output_dir: str | Path | None = None, *,
                           skill_name: str = "rfauto-experience-checklists",
                           task: Any = None) -> dict[str, Any]:
    """经验核对表技能包落盘（<output_dir>/<skill_name>/SKILL.md）。

    T-Q10 #144 修复：``output_dir`` 必填（旧缺省 ``"skills"`` 按 cwd 相对
    解析——调用方不 chdir 时包被静默写进真实 skills/ 工作区湖，实测复现
    于 runs/aurora_q/r9 探针）。现在缺省 None → 拒写并给可执行报错，
    不再静默选目录；要写真实 skills/ 请显式传 output_dir。
    """
    if output_dir is None:
        return error_envelope(
            ["output_dir 必填（#144 缺省目录纪律：旧缺省 \"skills\" 按 cwd "
             "相对解析，未 chdir 的调用方会把包静默写进真实 skills/ 湖——"
             "请显式给出输出目录）"])
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


# ---------------------------------------------------------------------------
# T-Q10（aurora_q Q-W6-1）：capability/kernel 卡 → agentskills.io SKILL.md
# 标准能力包（第三条产线）
# ---------------------------------------------------------------------------
# 规格：runs/aurora_q/r9/SKILL_ECO.md §8（frontmatter 规格/目录结构/机生
# 规则）。设计红线：
#   - 纯确定性变换（铁律 7）：内容逐字取自卡文件 / 调用方记录的内核实跑
#     JSON / 显式入参；产线自身零计算、零新数值；
#   - #144 缺省目录纪律：仓库锚（卡目录/materials/LICENSE）一律由
#     __file__ 推导、与调用方 cwd 无关；write_card_skill 的 output_dir
#     必填（born clean，不做 cwd 相对缺省）；
#   - 再生门：同入参两次生成逐字节同（tests/unit/test_card_to_skill.py
#     逐字节比对，同 test_kernel_cards 保鲜门口径）。
# frontmatter：name=rfauto-<slug>（=目录名）、description ≤1024 零流程词、
# 私有键全部进 metadata（禁顶层 version/argument-hint 等客户端方言键）。

SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SKILL_NAME_MAX = 64
SKILL_DESCRIPTION_MAX = 1024
SKILL_BODY_MAX_LINES = 500

#: description 流程词钉（R9 §8.4：description 只写触发条件，禁工作流叙述）。
_SKILL_FLOW_WORD_RE = re.compile(r"然后|首先|接着|先[^。；\n]{0,16}再")

_SKILL_HEADING_RE = re.compile(r"^## (.+?)\s*$")

#: 仓库锚（#144：由 __file__ 推导，与 cwd 无关；非 editable 安装时资产
#: 缺位 → 明确报错而非猜路径）。
_REPO_ROOT = Path(__file__).resolve().parents[3]

_SKILL_LICENSE_LINE = "Complete terms in LICENSE.txt"
_SKILL_COMPATIBILITY = (
    "Requires the rfauto CLI on PATH (pip install rfauto). Closed-form "
    "synthesis steps run offline; engine-backed steps need openEMS or HFSS "
    "installed locally.")
_SKILL_ALLOWED_TOOLS = "Bash(rfauto:*) Read"


def _skill_slug(card_id: str) -> str:
    """卡 ID → 目录安全 slug（下划线转连字符；复用 skill_autopilot 口径）。"""
    return re.sub(r"[^a-z0-9]+", "-", card_id.strip().lower()).strip("-")


def _split_card_sections(md_text: str) -> dict[str, list[str]]:
    """'## 标题' → 节正文行（不含标题行；首节前的导语行不采集）。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in md_text.splitlines():
        m = _SKILL_HEADING_RE.match(line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def _section_lines(sections: Mapping[str, list[str]],
                   heading_prefix: str) -> list[str]:
    """按标题前缀取节（卡节名含装饰后缀，如「敏感性排序（R9 先承诺）」）。"""
    for head, lines in sections.items():
        if head.startswith(heading_prefix):
            return list(lines)
    return []


def _bullet_texts(lines: Sequence[str]) -> list[str]:
    """节内非空行 → 去掉列表标记 '-' 的正文（保持原文其余逐字不变）。"""
    out: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        out.append(text[1:].strip() if text.startswith("- ") else text)
    return out


def _machine_description(card_id: str,
                         sections: Mapping[str, list[str]]) -> str:
    """卡「适用场景/名义参数」→ agentskills.io description（R9 §8.4 机生）。

    英文触发句框架 + 卡面中文原句（中文触发词随卡文并入）；含流程词的
    卡面子句如实丢弃（不是改写卡文）；超长按可选子句从尾丢弃，核心句
    仍超限 → 调用方收到明确报错。
    """
    bullets = _bullet_texts(_section_lines(sections, "适用场景"))

    def _bullet(prefix: str) -> str:
        for text in bullets:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return ""

    topology = _bullet("拓扑：")
    params = _bullet("参数：")
    extraction = _bullet("提取口径：")
    if not topology and bullets:
        topology = bullets[0]
    # 逐子句流程词检查（卡文含流程词则丢弃该子句——不悄悄改写卡文）
    topology = "" if _SKILL_FLOW_WORD_RE.search(topology) else topology
    params = "" if _SKILL_FLOW_WORD_RE.search(params) else params
    extraction = "" if _SKILL_FLOW_WORD_RE.search(extraction) else extraction

    core = f"Use when the user works with the rfauto `{card_id}` card"
    core += f": {topology}." if topology else "."
    core += f" Adjustable parameters: {params}." if params else ""
    optional = [
        f" Extraction: {extraction}." if extraction else "",
        f" Triggers: {card_id}.",
        (" Do NOT use for other card families — pick the matching rfauto "
         "card or skill instead."),
        (" Numbers come only from the rfauto kernel and the card files under"
         " references/ (deterministic sources)."),
    ]
    parts = [core] + [p for p in optional if p]
    while len("".join(parts)) > SKILL_DESCRIPTION_MAX and len(parts) > 1:
        parts.pop()
    description = "".join(parts)
    if len(description) > SKILL_DESCRIPTION_MAX:
        raise ValueError(
            f"description {len(description)} > {SKILL_DESCRIPTION_MAX}"
            f"（card_id={card_id}，核心句仍超限）")
    return description


def _fm_description_block(text: str) -> str:
    """description 折叠块（YAML >- 定长折叠，确定性换行）。

    break_on_hyphens=False：YAML 折叠回读时以空格重接断行，按连字符
    断行会把 "current-capacity" 之类词读成 "current- capacity"——断点
    只允许落在空格上，保证 frontmatter 解析值与原文逐字一致。
    """
    wrapped = textwrap.wrap(text, width=88, break_on_hyphens=False)
    return "description: >-\n" + "\n".join(f"  {line}" for line in wrapped)


def _render_skill_frontmatter(name: str, description: str, card_kind: str,
                              card_id: str, source_cards: Sequence[str],
                              with_license: bool) -> str:
    import yaml

    metadata: dict[str, Any] = {
        "author": "rfauto",
        "version": "1",
        "rfauto_card": card_id,
        "card_kind": card_kind,
        "generator": "rfauto.service.skill_service.card_to_skill",
        "source_cards": ", ".join(source_cards),
    }
    metadata_lines = yaml.safe_dump(
        metadata, sort_keys=False, allow_unicode=True,
        default_flow_style=False).strip().splitlines()
    lines = ["---", f"name: {name}", _fm_description_block(description)]
    if with_license:
        lines.append(f"license: {_SKILL_LICENSE_LINE}")
    lines.append(f"compatibility: {_SKILL_COMPATIBILITY}")
    lines.append("metadata:")
    lines += [f"  {line}" for line in metadata_lines]
    lines.append(f"allowed-tools: {_SKILL_ALLOWED_TOOLS}")
    lines.append("---")
    return "\n".join(lines)


def _card_anchor_lines(sections: Mapping[str, list[str]],
                       card_id: str) -> list[str]:
    """「引擎精度卡」节中本卡专属锚行（``<card_id>.`` 前缀命中）。"""
    marker = f"`{card_id}."
    return [line.rstrip() for line in _section_lines(sections, "引擎精度卡")
            if marker in line]


def _render_pitfalls_md(card_id: str,
                        sections: Mapping[str, list[str]]) -> str | None:
    """「已知边界」节的失败模式坑账链子树 → references/pitfalls.md。

    子树原样抽出（症状→坑号→处置逐字保留）；无坑账链子树 → None（不产
    空文件）。坑号 #NNN 是 DEVLOG 出处标记（D1 裁决保留项，非泄漏）。
    """
    boundary = _section_lines(sections, "已知边界")
    try:
        start = next(i for i, line in enumerate(boundary)
                     if "失败模式坑账链" in line)
    except StopIteration:
        return None
    intro = boundary[start].strip()
    entries = [line.rstrip() for line in boundary[start + 1:]
               if line.strip().startswith("- ")]
    if not entries:
        return None
    lines = [
        f"# rfauto {card_id} · failure-mode playbook",
        "",
        f"> Extracted verbatim from the capability card「失败模式坑账链」"
        f"section (docs/capability_cards/{card_id}.md; deterministic",
        "> regeneration). Pit numbers (#NNN) are rfauto DEVLOG ledger",
        "> markers. Symptom → pitfall chain → disposition; open this file",
        "> when a run shows one of the listed symptoms.",
        "",
        intro,
        "",
    ]
    lines += entries
    lines.append("")
    return "\n".join(lines)


_SKILL_VERIFY_SCRIPT_TEMPLATE = '''"""Deterministic output verifier for the rfauto {card_id} skill package.

Structural checks only — zero physics claims (rfauto rule 7: numbers come
from the rfauto kernel or the card files in references/, never from this
script or from model memory):

  1. every --json file parses as JSON and contains no non-finite floats
     (NaN/Infinity anywhere in the document);
  2. each --expect KEY=VALUE: KEY exists in the JSON, is a finite number,
     and abs(value - VALUE) <= --tol (default 1e-3).

Pass KEY/VALUE pairs only from rfauto kernel output or from the card files
in references/. Exit codes: 0 = all checks pass; 1 = any check fails.
Report FAIL as FAIL (rfauto rule #122); never retry a FAIL into green.
"""
from __future__ import annotations

import argparse
import json
import math
import sys


def _non_finite_paths(node, prefix="$"):
    bad = []
    if isinstance(node, float) and not math.isfinite(node):
        bad.append(prefix)
    elif isinstance(node, dict):
        for key, value in node.items():
            bad += _non_finite_paths(value, prefix + "." + str(key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            bad += _non_finite_paths(value, prefix + "[" + str(i) + "]")
    return bad


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Structural verifier for saved rfauto JSON output.")
    parser.add_argument("--json", action="append", required=True,
                        help="saved rfauto kernel JSON (repeatable)")
    parser.add_argument("--expect", action="append", default=[],
                        help="KEY=VALUE numeric cross-check (repeatable)")
    parser.add_argument("--tol", type=float, default=1e-3)
    args = parser.parse_args(argv)

    failures = []
    for path in args.json:
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as exc:
            failures.append(path + ": unreadable (" + str(exc) + ")")
            continue
        try:
            data = json.loads(raw)
        except ValueError as exc:
            failures.append(path + ": not JSON (" + str(exc) + ")")
            continue
        for where in _non_finite_paths(data):
            failures.append(path + ": non-finite float at " + where)
        if not isinstance(data, dict):
            failures.append(path + ": top-level JSON is not an object")
            continue
        for spec in args.expect:
            key, sep, value = spec.partition("=")
            if not sep:
                failures.append(
                    path + ": bad --expect " + repr(spec) + " (want KEY=VALUE)")
                continue
            if key not in data:
                failures.append(path + ": missing key " + repr(key))
                continue
            try:
                got = float(data[key])
            except (TypeError, ValueError):
                failures.append(path + ": key " + repr(key) + " not numeric")
                continue
            if not math.isfinite(got):
                failures.append(path + ": key " + repr(key) + " non-finite")
                continue
            want = float(value)
            if abs(got - want) > args.tol:
                failures.append(
                    path + ": " + key + "=" + repr(got) + " vs expected "
                    + repr(want) + " (tol " + repr(args.tol) + ")")
    if failures:
        for line in failures:
            print("FAIL " + line)
        return 1
    print("PASS " + str(len(args.json)) + " file(s), "
          + str(len(args.expect)) + " expectation(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _render_stackups_yaml(card_id: str, stackup_keys: Sequence[str],
                          materials_path: Path) -> str:
    """configs/materials.yaml → 本卡层叠键只读子集（assets/stackups.yaml）。"""
    import yaml

    data = yaml.safe_load(materials_path.read_text(encoding="utf-8")) or {}
    materials = data.get("materials") or {}
    missing = [k for k in stackup_keys if k not in materials]
    if missing:
        raise KeyError(
            f"materials.yaml 缺层叠键 {missing}（card_id={card_id}）"
            "——禁猜键名，请核对 configs/materials.yaml")
    subset = {k: materials[k] for k in stackup_keys}
    header = (
        f"# Read-only subset of rfauto configs/materials.yaml for the"
        f" {card_id} skill.\n"
        "# Source of truth: configs/materials.yaml (full provenance:"
        " source / verified_by in that file).\n"
        "# If the user's substrate is not listed here, ask for er / h /\n"
        "# tan_delta instead of guessing a key (no invented values).\n")
    body = yaml.safe_dump({"materials": subset}, sort_keys=False,
                          allow_unicode=True, default_flow_style=False)
    return header + body


def _render_skill_body(card_id: str, sections: Mapping[str, list[str]],
                       has_kernel_card: bool, has_pitfalls: bool,
                       workflow_commands: Sequence[str],
                       reading_guide_rows: Sequence[Sequence[str]],
                       example_json: Mapping[str, Any] | None) -> list[str]:
    """SKILL.md 正文（三层渐进披露：快读 → references 细节 → scripts 核验）。"""
    lines: list[str] = [
        f"# rfauto · {card_id}",
        "",
        "> Generated by `rfauto.service.skill_service.card_to_skill` from the",
        "> rfauto deterministic cards (byte-copied under `references/`);",
        "> regeneration is idempotent. Rule 7: every number must come from the",
        "> rfauto kernel or these cards — never from model memory, never",
        "> invented to be helpful.",
        "",
        "## When this skill applies",
        "",
    ]
    lines += _section_lines(sections, "适用场景")
    lines = [line.rstrip() for line in lines]
    lines += ["", "## Workflow (typed commands; every value comes from the kernel)", ""]
    if workflow_commands:
        lines.append("```bash")
        lines += [f"{cmd}" for cmd in workflow_commands]
        lines.append("```")
    else:
        lines.append(
            f"Run `rfauto --help` and consult the code entry points listed in"
            f" the kernel card (`references/kernel_card.md`, section"
            f"「代码入口」) — the CLI surface for card `{card_id}` is not"
            f" pinned by this package.")
    if reading_guide_rows:
        lines += ["", "How to read the kernel JSON envelope:", "",
                  "| key | meaning | act on it |", "|---|---|---|"]
        for key, meaning, action in reading_guide_rows:
            meaning_cell = meaning.replace("|", "\\|")
            action_cell = action.replace("|", "\\|")
            lines.append(f"| `{key}` | {meaning_cell} | {action_cell} |")

    lines += ["", "## Nominal parameters", ""]
    nominal = [line.rstrip() for line in _section_lines(sections, "名义参数")
               if line.strip()]
    lines += nominal

    sens = [line.rstrip() for line in _section_lines(sections, "敏感性排序")
            if line.strip()]
    if sens:
        lines += ["", "## Sensitivity ranking", ""]
        lines += sens

    judgment = [line.rstrip() for line in _section_lines(sections, "判据")
                if line.strip()]
    if judgment:
        lines += ["", "## Judgment gates and anchors", ""]
        lines += judgment

    own_anchors = _card_anchor_lines(sections, card_id)
    lines += ["", "## Card-specific arbitration anchors", ""]
    if own_anchors:
        lines += own_anchors
        lines.append("")
        lines.append(
            "- Wildcard anchors from other families that also cover this card:"
            " see the「判据」section above and `references/capability_card.md`.")
    else:
        lines.append(
            f"- Card `{card_id}` has no card-specific anchor line; the"
            " wildcard anchors covering it are listed in the「判据」section"
            " above and in `references/capability_card.md`.")

    boundary = []
    raw_boundary = _section_lines(sections, "已知边界")
    in_playbook = False
    for line in raw_boundary:
        if "失败模式坑账链" in line:
            in_playbook = True
            continue
        if in_playbook:
            if line.strip().startswith("- "):
                continue
            if not line.strip():
                continue
            in_playbook = False
        boundary.append(line.rstrip())
    boundary = [line for line in boundary if line.strip()]
    lines += ["", "## Known boundaries", ""]
    lines += boundary
    if has_pitfalls:
        lines.append("")
        lines.append(
            "- Failure-mode playbook (symptom → pitfall → fix, "
            f"{card_id}-relevant): open `references/pitfalls.md` when a run"
            " shows one of the listed symptoms.")

    if example_json is not None:
        lines += [
            "",
            "## Recorded kernel output (real rfauto run, captured at",
            "generation time; ground truth for exactly this input)",
            "",
            "```json",
            json.dumps(example_json, ensure_ascii=False, indent=2,
                       sort_keys=True),
            "```",
        ]

    lines += ["", "## When to open the reference files", "",
              "| you need | open |", "|---|---|"]
    lines += [
        ("| the full capability card (playbook, all anchors, engine"
         " precision) | `references/capability_card.md` |"),
    ]
    if has_kernel_card:
        lines.append(
            "| formulas, docstring pins, precision profile, code entries,"
            " test surface | `references/kernel_card.md` |")
    if has_pitfalls:
        lines.append("| a symptom → pitfall → fix lookup | "
                     "`references/pitfalls.md` |")
    lines += [
        "",
        "## Verify before you finish",
        "",
        "Run `python scripts/verify_output.py --json <saved.json>"
        " [--expect KEY=VALUE ... --tol 1e-3]`.",
        "FAIL is reported as FAIL (rfauto rule #122); never retry a FAIL"
        " into green.",
        "",
    ]
    # 连续空行塌缩为单空行（卡节原文行含节尾空行，逐字并入会堆叠）
    collapsed: list[str] = []
    for line in lines:
        if not line.strip() and (not collapsed or not collapsed[-1].strip()):
            continue
        collapsed.append(line)
    return collapsed


def card_to_skill(
    card_id: str,
    *,
    capability_dir: str | Path | None = None,
    kernel_dir: str | Path | None = None,
    skill_name: str | None = None,
    description: str | None = None,
    workflow_commands: Sequence[str] = (),
    reading_guide_rows: Sequence[Sequence[str]] = (),
    example_json: Mapping[str, Any] | None = None,
    stackup_keys: Sequence[str] = (),
    materials_path: str | Path | None = None,
) -> dict[str, Any]:
    """capability/kernel 卡 → agentskills.io SKILL.md 标准能力包（纯构造）。

    返回信封：``ok / skill_name / card_id / card_kind / description /
    content（SKILL.md 文本）/ files（相对路径→文本，含 SKILL.md 自身）/
    n_files / n_lines``。目录结构（R9 §8.3，按需）：SKILL.md + LICENSE.txt
    + references/{capability_card,kernel_card,pitfalls}.md + scripts/
    verify_output.py + assets/stackups.yaml。references 两卡为源卡逐字节
    副本（再生门逐字节比对）；坑账链抽出进 pitfalls.md；scripts/ 结构性
    核验器（零物理断言，数值必须来自内核/卡）。

    ``example_json``：调用方记录的内核实跑输出（原样内嵌——产线不跑内核、
    零新数值）。``stackup_keys``：materials.yaml 层叠键子集（禁猜键名，
    缺键报错）。缺省目录由 __file__ 仓库锚推导（#144：与 cwd 无关）。
    """
    cap_dir = (Path(capability_dir) if capability_dir
               else _REPO_ROOT / "docs" / "capability_cards")
    ker_dir = (Path(kernel_dir) if kernel_dir
               else _REPO_ROOT / "docs_site" / "kernel_cards")
    cap_path = cap_dir / f"{card_id}.md"
    if not cap_path.exists():
        return error_envelope([f"capability 卡不存在: {cap_path}"])
    cap_text = cap_path.read_text(encoding="utf-8")
    sections = _split_card_sections(cap_text)
    ker_path = ker_dir / f"{card_id}.md"
    ker_text = (ker_path.read_text(encoding="utf-8")
                if ker_path.exists() else None)

    name = skill_name or f"rfauto-{_skill_slug(card_id)}"
    if not SKILL_NAME_RE.match(name) or len(name) > SKILL_NAME_MAX:
        return error_envelope(
            [f"skill_name={name!r} 不符 agentskills.io name 规则"
             f"（^[a-z0-9][a-z0-9-]*$ 且 ≤{SKILL_NAME_MAX} 字符）"])
    if description is None:
        try:
            description = _machine_description(card_id, sections)
        except ValueError as exc:
            return error_envelope([str(exc)])
    flow_hit = _SKILL_FLOW_WORD_RE.search(description)
    if flow_hit:
        return error_envelope(
            [f"description 命中流程词（R9 §8.4 零流程词）: {flow_hit.group(0)!r}"])
    if not description.strip() or len(description) > SKILL_DESCRIPTION_MAX:
        return error_envelope(
            [f"description 空/超限（{len(description)} >"
             f" {SKILL_DESCRIPTION_MAX}）"])

    source_cards = [f"docs/capability_cards/{card_id}.md"]
    card_kind = "capability"
    if ker_text is not None:
        source_cards.append(f"docs_site/kernel_cards/{card_id}.md")
        card_kind = "capability+kernel"

    license_path = _REPO_ROOT / "LICENSE"
    with_license = license_path.exists()

    frontmatter = _render_skill_frontmatter(
        name, description, card_kind, card_id, source_cards, with_license)
    pitfalls_md = _render_pitfalls_md(card_id, sections)
    body_lines = _render_skill_body(
        card_id, sections, has_kernel_card=ker_text is not None,
        has_pitfalls=pitfalls_md is not None,
        workflow_commands=workflow_commands,
        reading_guide_rows=reading_guide_rows,
        example_json=example_json)
    content = frontmatter + "\n\n" + "\n".join(body_lines)
    n_lines = len(content.splitlines())
    if n_lines > SKILL_BODY_MAX_LINES:
        return error_envelope(
            [f"SKILL.md {n_lines} 行 > {SKILL_BODY_MAX_LINES} 行预算"
             f"（R9 §8.2；card_id={card_id}）"])

    files: dict[str, str] = {"SKILL.md": content}
    if with_license:
        files["LICENSE.txt"] = license_path.read_text(encoding="utf-8")
    files["references/capability_card.md"] = cap_text
    if ker_text is not None:
        files["references/kernel_card.md"] = ker_text
    if pitfalls_md is not None:
        files["references/pitfalls.md"] = pitfalls_md
    files["scripts/verify_output.py"] = _SKILL_VERIFY_SCRIPT_TEMPLATE.format(
        card_id=card_id)
    if stackup_keys:
        materials = (Path(materials_path) if materials_path
                     else _REPO_ROOT / "configs" / "materials.yaml")
        if not materials.exists():
            return error_envelope([f"materials.yaml 不存在: {materials}"])
        try:
            files["assets/stackups.yaml"] = _render_stackups_yaml(
                card_id, stackup_keys, materials)
        except KeyError as exc:
            return error_envelope([str(exc)])

    return ok_envelope(
        skill_name=name,
        card_id=card_id,
        card_kind=card_kind,
        description=description,
        content=content,
        files=files,
        n_files=len(files),
        n_lines=n_lines,
    )


def write_card_skill(card_id: str, output_dir: str | Path, **kwargs) -> dict[str, Any]:
    """card_to_skill + 全包落盘（<output_dir>/<skill_name>/，逐文件写）。

    ``output_dir`` 必填（#144 born clean：不提供 cwd 相对缺省，防未显式
    给目录的调用方把包静默写进真实 skills/ 工作区湖）。kwargs 透传
    card_to_skill。返回信封追加 written/output_path/skill_dir/n_files。
    """
    if output_dir is None:
        return error_envelope(
            ["output_dir 必填（#144 缺省目录纪律：card→skill 产线不设 cwd "
             "相对缺省——请显式给出输出目录）"])
    result = card_to_skill(card_id, **kwargs)
    if not result.get("ok"):
        return result
    skill_dir = Path(output_dir) / result["skill_name"]
    try:
        for rel, text in result["files"].items():
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    except OSError as exc:
        return error_envelope([f"落盘失败: {exc}"],
                              skill_name=result["skill_name"])
    return result | {
        "written": True,
        "output_path": str(skill_dir / "SKILL.md"),
        "skill_dir": str(skill_dir),
    }


def card_to_skill_batch(card_ids: Sequence[str], output_dir: str | Path, *,
                        per_card: Mapping[str, Mapping[str, Any]] | None = None,
                        **kwargs) -> dict[str, Any]:
    """批量产线：76 模板族 card → 包（R9 §8.4 批量形态，逐卡落盘）。

    单卡失败不中断批次（逐卡如实收集，不凑绿）；``per_card`` 给逐卡
    curated 入参（description/workflow_commands/example_json 等），其余
    kwargs 全卡透传。``ok`` = 全部卡成功；有失败时 errors 首条为汇总，
    逐卡状态在 results。
    """
    per_card = per_card or {}
    results: list[dict[str, Any]] = []
    n_ok = 0
    failures: list[str] = []
    for cid in card_ids:
        merged = dict(kwargs)
        merged.update(per_card.get(cid, {}))
        result = write_card_skill(cid, output_dir, **merged)
        results.append({
            "card_id": cid,
            "ok": bool(result.get("ok")),
            "skill_name": result.get("skill_name"),
            "errors": [] if result.get("ok") else list(result.get("errors") or []),
        })
        if result.get("ok"):
            n_ok += 1
        else:
            failures.append(f"{cid}: {'; '.join(result.get('errors') or [])}")
    summary = {
        "output_dir": str(output_dir),
        "results": results,
        "n_cards": len(card_ids),
        "n_ok": n_ok,
        "n_fail": len(failures),
    }
    if failures:
        return error_envelope(
            [f"{len(failures)}/{len(card_ids)} 卡失败——逐卡状态见 results",
             *failures], **summary)
    return ok_envelope(**summary)


# ---------------------------------------------------------------------------
# Q-X62（aurora_q，2026-11-08）：SKILL/OCEAN 源码 S-expression 解析面
# ---------------------------------------------------------------------------
# 本文件第三条产线的**解析**方向（前两条=配方→SKILL.md 导出、卡→能力包）：
# SKILL（Cadence Virtuoso 的 Lisp 方言）与 OCEAN（仿真命令面超集）源码的
# 只读结构化解析——脚本静态分析、API 调用清单提取、define/defun 盘点、
# 全局赋值面盘点、define→calls 静态调用图（Virtuoso-Bridge-lite 借鉴化用
# 方向；生成方向见 core/skill_template_engine Q-X32，两模块互不依赖）。
# 词法/S 表达式/结构提取/literal_eval 全在 core/skill_parser 确定性内核
# （铁律 7：零物理数字、永不执行被解析代码）；本节是规则 4 JSON 进出薄
# 壳（AU-2 信封构造器，禁裸 dict）。既有函数（recipe_to_skill / card_to_skill
# 族）行为零变化（加性接线）。
# 错误归一：文件不存在/为空/目录/不可读/词法括号违规（SkillParseError，
# 信封附 line/column 结构化键）→ error 信封（errors 恒 list[str]）；解码
# 链=utf-8 优先、Latin-1 兜底（verilog_netlist_service 同款先例）。


def _read_skill_text(path: str | Path) -> str:
    """读 SKILL 源文件文本：utf-8 优先，Latin-1 兜底（正文 ASCII 口径）。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _parse_skill_or_error(
    path: str | Path,
) -> tuple[list[Any] | None, dict[str, Any]]:
    """读文件+解析两步合成（单次解析，零双读）。

    成功 → (节点树, ok 信封骨架)；失败 → (None, error 信封)。OSError/
    SkillParseError/空文本均在此归一。
    """
    from rfauto.core.skill_parser import SkillParseError, parse_skill

    p = Path(path)
    if not p.exists():
        return None, error_envelope(f"SKILL 文件不存在: {p}")
    if p.is_dir():
        return None, error_envelope(f"SKILL 路径是目录不可读: {p}")
    try:
        text = _read_skill_text(p)
    except OSError as exc:
        return None, error_envelope(f"SKILL 文件不可读: {exc}")
    try:
        tree = parse_skill(text)
    except SkillParseError as exc:
        fields: dict[str, Any] = {}
        if exc.line is not None:
            fields["line"] = exc.line
            fields["column"] = exc.column
        return None, error_envelope(f"SKILL 解析失败: {exc}", **fields)
    if not tree:
        return None, error_envelope(
            f"SKILL 文件为空（或仅含注释）: {p}——非 SKILL 源，拒绝解析")
    return tree, ok_envelope(path=str(path))


def parse_skill_file(path: str | Path) -> dict[str, Any]:
    """SKILL/OCEAN 源文件 → 全结构化信封（顶层节点树平面化+计数面）。

    信封：``{"ok": True, "path", "schema", "forms"（node_to_plain 平面树）,
    "stats"（skill_tree_stats 计数）, "warnings": []}``；文件不存在/为空
    （或纯注释）/目录/不可读/词法括号违规 → error 信封（括号失衡附
    ``line``/``column`` 1 基结构化键）。纯只读：不落盘、零网络、零真机。
    """
    from rfauto.core.skill_parser import (
        PARSER_SCHEMA_VERSION,
        node_to_plain,
        skill_tree_stats,
    )

    tree, base = _parse_skill_or_error(path)
    if tree is None:
        return base
    return ok_envelope(
        path=str(path),
        schema=f"skill/{PARSER_SCHEMA_VERSION}",
        forms=[node_to_plain(form) for form in tree],
        stats=skill_tree_stats(tree),
        warnings=[],
    )


def skill_report(path: str | Path) -> dict[str, Any]:
    """SKILL/OCEAN 源文件 → 报告信封（定义盘点+API 桶+顶层分类+全局变量）。

    parse 全结构化信封的聚合视图（不含 forms 平面树）：definitions
    （skill_definitions）/duplicates、top_level（skill_top_level_forms）、
    api（skill_api_calls 聚合）、globals（skill_globals）。解析失败原样
    透传 error 信封（含 line/column 结构化键）。
    """
    from rfauto.core.skill_parser import (
        skill_api_calls,
        skill_definitions,
        skill_globals,
        skill_top_level_forms,
    )

    tree, base = _parse_skill_or_error(path)
    if tree is None:
        return base
    defs = skill_definitions(tree)
    top = skill_top_level_forms(tree)
    api = skill_api_calls(tree)
    g = skill_globals(tree)
    return ok_envelope(
        path=str(path),
        stats={
            "n_top_level": top["n_top_level"],
            "n_definitions": defs["stats"]["n_definitions"],
            "n_unique_names": defs["stats"]["n_unique_names"],
            "n_duplicates": defs["stats"]["n_duplicates"],
            "n_calls": api["stats"]["n_calls"],
            "n_names": api["stats"]["n_names"],
            "n_unknown_head": api["stats"]["n_unknown_head"],
            "n_globals": g["n_assignments"],
            "n_unique_targets": g["n_unique_targets"],
        },
        definitions=defs["definitions"],
        duplicates=defs["duplicates"],
        top_level=top,
        api={"by_name": api["by_name"], "by_bucket": api["by_bucket"],
             "buckets": api["buckets"], "stats": api["stats"]},
        globals=g["globals"],
        targets=g["targets"],
        warnings=[*defs["warnings"], *g["warnings"]],
    )


def skill_call_graph(path: str | Path) -> dict[str, Any]:
    """SKILL/OCEAN 源文件 → 静态调用图信封（define→calls 边+外部调用面）。

    只按符号名匹配同名 define（无词法作用域分析，core.skill_parser
    skill_call_edges 单源）：递归=caller==callee 边如实；被调名无同名定义
    归 external 如实。解析失败原样透传 error 信封。
    """
    from rfauto.core.skill_parser import skill_call_edges

    tree, base = _parse_skill_or_error(path)
    if tree is None:
        return base
    edges = skill_call_edges(tree)
    return ok_envelope(
        path=str(path),
        defined_names=edges["defined_names"],
        edges=edges["edges"],
        external=edges["external"],
        n_edges=edges["n_edges"],
        n_external=edges["n_external"],
        warnings=[],
    )

