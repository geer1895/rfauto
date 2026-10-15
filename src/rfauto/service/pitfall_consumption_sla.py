"""坑账消费 SLA 检查函数（T15-B12；SPECS3 §3.3——终结 66 条死库）。

定位：坑账（knowledge/pitfalls_index.json 结构化子集 + 项目规则 踩坑速查
人读面）的**消费 SLA 面**——solver 四类（openems/hfss/comsol/elmer）的
每条 pitfall 必须在二消费面之一有指针，且"新会话/新席位的最低消费点"
（pitfall_index_service 检索 / premortem 注入 / hint_for_message 错误
提示）必须活体可达。

指针二面（spec §3.3 原文）：

(a) knowledge/diagnostics/playbook.yaml 某规则 pit_refs 含其坑号——
    症状可机器观测族（playbook 设计约束"只收确定性指纹"必须尊重，
    无检测器支撑的坑不硬塞 playbook，#122 哲学）；
(b) knowledge/pitfall_consumption.yaml 消费指针登记行
    （surface+pointer+note；W5-E 口径=13 条仅消费说明——逐条登记
    检索/提示面的消费方式，不为凑门把规则硬塞 playbook）。

surface 词表（封闭，未知 surface → 违例，防面名漂移）：

- spec 六面（B4/EC-6 等 UX 批落地前的预登记名；届时行翻 surface 字段，
  门零改）：doctor_hint / explain_run_note / ui_pitfalls / mcp_search /
  rag_query / guidelines；
- 现树已接线的真实消费面（ground 2026-10-05，W5-E B12 实证）：
  premortem_note（service/premortem_service.py:29 _pitfall_notes 注入，
  FU-16 清偿）/ error_hint（service/error_hints_service.py hint 规则
  refs，症状文本匹配）/ index_search（service/pitfall_index_service.py
  pitfall_search·pitfall_notes_for，新会话最低消费点）。

设计约束：索引文件零改写（index 是生成产物，指针面独立文件防生成器
漂移，两文件以 id 关联）；坏账多报不放过（#316：dangling ref/未知
surface/幽灵 id 一律违例）；纯函数零网络零 LLM（铁律 7）；路径可注入
（synthetic 目录双态钉），缺省=仓内真档。
"""

from __future__ import annotations

import contextlib
import inspect
import re
from pathlib import Path
from typing import Any

import yaml

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.pitfall_index_service import (
    load_pitfall_index,
    pitfall_notes_for,
)

#: SLA 输出 schema 标识（消费者据此识别）。
SLA_SCHEMA = "rfauto-pitfall-consumption-sla/1"

#: 消费指针登记面 schema（knowledge/pitfall_consumption.yaml）。
CONSUMPTION_SCHEMA = "pitfall-consumption/v1"

#: solver 四类（spec §3.3：这四类的坑必须有消费指针）。
SOLVER_CATEGORIES = ("openems", "hfss", "comsol", "elmer")

#: 消费面词表（封闭；语义见模块 docstring）。
SURFACES = frozenset({
    # spec 六面（预登记名，UX 批挂点落地即启用）
    "doctor_hint", "explain_run_note", "ui_pitfalls", "mcp_search",
    "rag_query", "guidelines",
    # 现树已接线真实面（ground 2026-10-05）
    "premortem_note", "error_hint", "index_search",
})

#: 缺省三文件路径（与 pitfall_index_service 同源口径：parents[3]）。
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PLAYBOOK_PATH = _REPO_ROOT / "knowledge" / "diagnostics" / "playbook.yaml"
DEFAULT_CONSUMPTION_PATH = _REPO_ROOT / "knowledge" / "pitfall_consumption.yaml"
DEFAULT_LEDGER_DOC_PATH = _REPO_ROOT / "PROJECT_RULES.md"

#: 坑号 token（#NNN / A_xyz 形；compound id 按同样 token 拆开比对）。
_TOKEN_RE = re.compile(r"#\d+|A\d+")


def id_tokens(text: Any) -> list[str]:
    """任意文本 → 坑号 token 表（去重保序；compound id 拆分比对）。"""
    if not isinstance(text, str):
        return []
    seen: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        if tok not in seen:
            seen.append(tok)
    return seen


def _load_ledger_tokens(entries: list[dict[str, Any]],
                        agents_path: str | Path | None,
                        violations: list[dict[str, Any]]) -> set[str]:
    """坑账全集体 token 集（index 结构化子集 ∪ 项目规则 踩坑速查人读面）。

    项目规则 缺席/不可读 → 如实降级为仅 index 集（violation 不加——速查面
    是助记人读面，缺席不构成消费 SLA 红旗；但此时 index 外 ref 会按
    dangling 多报，#316 方向=多报不放过）。
    """
    toks: set[str] = set()
    for entry in entries:
        toks.update(id_tokens(entry.get("id")))
    path = Path(agents_path) if agents_path else DEFAULT_LEDGER_DOC_PATH
    with contextlib.suppress(OSError):
        toks.update(id_tokens(path.read_text(encoding="utf-8")))
    return toks


def check_pitfall_consumption_sla(
    index_path: str | Path | None = None,
    playbook_path: str | Path | None = None,
    consumption_path: str | Path | None = None,
    agents_path: str | Path | None = None,
) -> dict[str, Any]:
    """坑账消费 SLA 全检（JSON 进出；violation 空表=门绿）。

    检查面（违例 kind 词表）：index_load / playbook_load / consumption_load
    / consumption_schema / dangling_pit_ref / unknown_surface / empty_pointer
    / unknown_row_id / uncovered_solver_pitfall / dead_face / row_pointer_false。

    - faces=最低消费点活体探针（index 检索回环 / premortem 接线在源 /
      hint 规则表非空）——挂点被拆即红（seat 指令"最低消费点检查"）；
    - surface=error_hint 的行做**逐行指针实证**：行 id token 必须真在
      hint 规则 refs 中命中（登记必须真，#122）；
    - 反查全集=**坑账全集体**（index 结构化子集 ∪ 项目规则 踩坑速查人读面
      的坑号 token，seat 口径"坑账=index+项目规则 速查"）——pit_ref 指向
      未入结构化子集的真坑（如 #262/#84）合法，指向两边都不存在的号
      （typo/虚构）才红（W5-E 实证：playbook 19 个 index 外 ref 全部
      项目规则/ 在案）。
    """
    violations: list[dict[str, Any]] = []

    # ── 1) 索引加载（坏账如实报，不静默回退空账——#316 同向）─────────
    idx = load_pitfall_index(index_path)
    if not idx.get("ok"):
        violations.append({"kind": "index_load",
                           "detail": f"坑账索引加载失败：{idx.get('errors')}"})
        return _finish(violations, coverage=[], n_solver=0, faces={})
    entries = idx["entries"]
    ledger_tokens = _load_ledger_tokens(entries, agents_path, violations)

    # ── 2) playbook pit_refs 全量反查（防 typo 空指针，spec 判据③）──
    pb_path = Path(playbook_path) if playbook_path else DEFAULT_PLAYBOOK_PATH
    playbook_rules: list[dict[str, Any]] = []
    try:
        pb = yaml.safe_load(pb_path.read_text(encoding="utf-8"))
        if not isinstance(pb, dict):
            raise TypeError("playbook 根必须是映射")
        rules = pb.get("rules")
        if isinstance(rules, list):
            playbook_rules = [r for r in rules if isinstance(r, dict)]
    except Exception as exc:
        violations.append({"kind": "playbook_load",
                           "detail": f"playbook 加载失败：{exc}"})

    playbook_ref_tokens: set[str] = set()
    for rule in playbook_rules:
        rule_id = str(rule.get("id") or "?")
        for tok in id_tokens(" ".join(rule.get("pit_refs") or [])):
            playbook_ref_tokens.add(tok)
            if tok not in ledger_tokens:
                violations.append({
                    "kind": "dangling_pit_ref",
                    "detail": (f"playbook 规则 {rule_id!r} pit_refs 坑号 "
                               f"{tok} 在坑账全集体（index∪项目规则 速查）"
                               "反查不到（typo 空指针）"),
                })

    # ── 3) 消费指针登记面（(b) 面）──────────────────────────────────
    cp_path = (Path(consumption_path) if consumption_path
               else DEFAULT_CONSUMPTION_PATH)
    rows: list[dict[str, Any]] = []
    try:
        cp = yaml.safe_load(cp_path.read_text(encoding="utf-8"))
        if not isinstance(cp, dict):
            raise TypeError("consumption 根必须是映射")
        if cp.get("schema") != CONSUMPTION_SCHEMA:
            violations.append({
                "kind": "consumption_schema",
                "detail": (f"schema 必须 == {CONSUMPTION_SCHEMA!r}，得 "
                           f"{cp.get('schema')!r}"),
            })
        raw_rows = cp.get("rows")
        if isinstance(raw_rows, list):
            rows = [r for r in raw_rows if isinstance(r, dict)]
    except FileNotFoundError:
        violations.append({"kind": "consumption_load",
                           "detail": f"消费指针登记面缺失：{cp_path}"})
    except Exception as exc:
        violations.append({"kind": "consumption_load",
                           "detail": f"消费指针登记面加载失败：{exc}"})

    # hint 规则 refs 全量 token（error_hint 行的逐行实证锚）
    hint_ref_tokens: set[str] = set()
    try:
        from rfauto.service.error_hints_service import list_hint_rules

        hints = list_hint_rules()
        if hints.get("ok"):
            for rule in hints.get("rules") or []:
                hint_ref_tokens.update(id_tokens(str(rule.get("refs") or "")))
    except Exception:
        pass  # hint 表不可达：error_hint 行实证按零命中处理（行实证会红）

    row_cover: dict[str, list[str]] = {}
    for pos, row in enumerate(rows):
        surface = row.get("surface")
        pointer = row.get("pointer")
        toks = id_tokens(str(row.get("id") or ""))
        if surface not in SURFACES:
            violations.append({
                "kind": "unknown_surface",
                "detail": (f"消费行#{pos} surface={surface!r} 不在封闭词表"
                           f"（防面名漂移）"),
            })
        if not isinstance(pointer, str) or not pointer.strip():
            violations.append({
                "kind": "empty_pointer",
                "detail": f"消费行#{pos}（id={row.get('id')!r}）pointer 为空",
            })
        if not toks:
            violations.append({
                "kind": "unknown_row_id",
                "detail": (f"消费行#{pos} id={row.get('id')!r} 无可解析坑号"),
            })
        for tok in toks:
            if tok not in ledger_tokens:
                violations.append({
                    "kind": "unknown_row_id",
                    "detail": (f"消费行#{pos} 坑号 {tok} 在坑账全集体"
                               "（index∪项目规则 速查）反查不到"
                               "（多报不放过，#316）"),
                })
        if (surface == "error_hint" and toks
                and not set(toks) & hint_ref_tokens):
            violations.append({
                "kind": "row_pointer_false",
                "detail": (f"消费行#{pos}（id={row.get('id')!r}）登记 "
                           f"surface=error_hint 但 hint 规则 refs 无其"
                           f"坑号——登记必须真（#122）"),
            })
        for tok in toks:
            row_cover.setdefault(tok, []).append(f"row#{pos}:{surface}")

    # ── 4) solver 四类逐条覆盖 SLA（spec 判据：13/13 及未来新增）────
    coverage: list[dict[str, Any]] = []
    n_solver = 0
    for entry in entries:
        if entry.get("category") not in SOLVER_CATEGORIES:
            continue
        n_solver += 1
        eid = str(entry.get("id"))
        toks = id_tokens(eid)
        covered_by: list[str] = []
        for tok in toks:
            if tok in playbook_ref_tokens:
                covered_by.append("playbook:pit_refs")
            for anchor in row_cover.get(tok) or []:
                if anchor not in covered_by:
                    covered_by.append(anchor)
        if not covered_by:
            violations.append({
                "kind": "uncovered_solver_pitfall",
                "id": eid,
                "detail": (f"solver 类坑 {eid}"
                           f"（{entry.get('category')}）无任何消费指针——"
                           "playbook pit_refs 与 consumption 行二选一"),
            })
        coverage.append({
            "id": eid, "category": entry.get("category"),
            "tokens": toks, "covered_by": covered_by,
            "covered": bool(covered_by),
        })

    # ── 5) 最低消费点活体探针（新会话/新席位可实际消费）────────────
    solver_entries = [e for e in entries
                      if e.get("category") in SOLVER_CATEGORIES]
    faces = _probe_consumption_faces(idx, solver_entries, violations)

    return _finish(violations, coverage, n_solver, faces)


def _probe_consumption_faces(idx: dict[str, Any],
                             solver_entries: list[dict[str, Any]],
                             violations: list[dict[str, Any]]) -> dict[str, Any]:
    """三个已接线消费面的活体探针（挂点被拆即红，#105 不阻塞主路径）。"""
    faces: dict[str, Any] = {}
    # index 检索回环：按首条 solver 坑的标题词检索必命中自身
    try:
        probe_kw = str(solver_entries[0]["title"]).split()[0]
        notes = pitfall_notes_for(idx, [probe_kw])
        ok = bool(notes)
    except Exception:
        ok = False
    faces["index_search"] = {"ok": ok,
                             "probe": "pitfall_notes_for 首条 solver 坑标题词"}
    if not ok:
        violations.append({
            "kind": "dead_face", "detail": "index_search 消费面探针失败"
                                           "（pitfall_notes_for 空返回）"})
    # premortem 接线在源（FU-16 清偿回归钉）：pitfall_notes_for 引用必须在
    # premortem_service 源内（注入点被拆即红）
    try:
        from rfauto.service import premortem_service

        src = inspect.getsource(premortem_service)
        ok = ("pitfall_notes_for" in src) and callable(
            getattr(premortem_service, "premortem_report", None))
    except Exception:
        ok = False
    faces["premortem_note"] = {"ok": ok,
                               "probe": "premortem_service 源内 pitfall 注入接线"}
    if not ok:
        violations.append({
            "kind": "dead_face", "detail": ("premortem_note 消费面探针失败"
                                            "（premortem 注入接线被拆）")})
    # error_hint 规则表非空（hint_for_message 底座）
    try:
        from rfauto.service.error_hints_service import list_hint_rules

        hints = list_hint_rules()
        ok = bool(hints.get("ok")) and int(hints.get("n_rules") or 0) > 0
        n_rules = int(hints.get("n_rules") or 0)
    except Exception:
        ok = False
        n_rules = 0
    faces["error_hint"] = {"ok": ok, "n_rules": n_rules,
                           "probe": "list_hint_rules 非空规则表"}
    if not ok:
        violations.append({
            "kind": "dead_face", "detail": "error_hint 消费面探针失败"
                                           "（hint 规则表不可达）"})
    return faces


def _finish(violations: list[dict[str, Any]],
            coverage: list[dict[str, Any]], n_solver: int,
            faces: dict[str, Any]) -> dict[str, Any]:
    """报告收口（契约 §4：service 信封走构造器，新代码禁裸 ok 字面量）。

    - 绿：ok_envelope（violations=[]）；
    - 红：error_envelope——errors=违例一行串投影（人读），violations=
      结构化明细字段（机器消费，tests/门链用）。
    """
    fields: dict[str, Any] = {
        "schema": SLA_SCHEMA,
        "n_solver_entries": n_solver,
        "n_covered": sum(1 for c in coverage if c["covered"]),
        "coverage": coverage,
        "faces": faces,
        "violations": violations,
    }
    if violations:
        return error_envelope(
            [f"{v.get('kind')}: {v.get('detail')}" for v in violations],
            **fields)
    return ok_envelope(**fields)
