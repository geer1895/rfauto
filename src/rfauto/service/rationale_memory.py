"""rationale_memory：设计理由记忆（阶段 7.7，MemGPT 类比【近】项）。

把散在 runs/ 产物里的"为什么这么做"（autotune 评判 issues/fixes、
校准报告、agent 提案 rationale、meta 快照）建成可检索索引——
决策理由与数据同权重沉淀，agent/新人可问答检索。

实现：手写 TF-IDF 余弦检索（零重依赖；向量库可后换）。
索引构建 best-effort（#105）：坏产物跳过不阻塞。

F11 增量（自进化经验记忆， F11 / 第 8 条，与 F2/F3 并轨）：
在上面的"理由语料检索"之外，把踩坑教训/判读结论沉淀为 typed 经验条目
（坑编号/结论/证据路径/适用场景/动作/核对表），并提供确定性检索
（recall_for / checklist_for，关键词与标签子串匹配，无 embedding、无网络、
无 LLM）。新模板冒烟 / critique 生成前调用，命中相关经验即要求先离线审计。
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def _tokenize(text: str) -> list[str]:
  return [t.lower() for t in _TOKEN.findall(text or "")]


def _collect_docs(runs_dir: Path) -> list[dict[str, str]]:
  """扫描 runs/ 产物，收集 (doc_id, text) 理由语料。"""
  docs: list[dict[str, str]] = []
  for run in sorted(runs_dir.iterdir()):
    if not run.is_dir() or run.name.startswith(("agent_proposals", ".")):
      continue
    meta = run / "meta.json"
    if meta.exists():
      try:
        m = json.loads(meta.read_text(encoding="utf-8"))
        docs.append({"id": f"{run.name}/meta",
               "text": json.dumps(m.get("metrics", {})
                        | {"algorithm": m.get("algorithm", ""),
                          "adapter": m.get("adapter", ""),
                          "model": m.get("model", "")},
                        ensure_ascii=False)})
      except Exception:
        pass
    autotune = run / "autotune.json"
    if autotune.exists():
      try:
        a = json.loads(autotune.read_text(encoding="utf-8"))
        reasons = []
        for h in a.get("history", []):
          for i in h.get("issues", []):
            reasons.append(json.dumps(i, ensure_ascii=False))
          for fx in h.get("fixes", []):
            reasons.append(f"{fx.get('kind')} {fx.get('param')} "
                    f"{fx.get('reason')}")
        if reasons:
          docs.append({"id": f"{run.name}/autotune",
                 "text": " ".join(reasons)})
      except Exception:
        pass
    report = run / "calibration" / "report.md"
    if report.exists():
      with contextlib.suppress(Exception):
        docs.append({"id": f"{run.name}/calibration",
               "text": report.read_text(encoding="utf-8")})
  proposals = runs_dir / "agent_proposals"
  if proposals.exists():
    for pf in sorted(proposals.glob("*.json")):
      with contextlib.suppress(Exception):
        docs.append({"id": f"agent_proposals/{pf.name}",
               "text": pf.read_text(encoding="utf-8")})
  return docs


def build_index(runs_dir: str | Path = "runs") -> dict[str, Any]:
  """构建 TF-IDF 索引（内存态；大库可持久化）。"""
  runs = Path(runs_dir)
  if not runs.exists():
    return {"ok": False, "errors": [f"runs 目录不存在: {runs}"]}
  docs = _collect_docs(runs)
  if not docs:
    return {"ok": False, "errors": ["未收集到任何理由语料"]}
  tok = [_tokenize(d["text"]) for d in docs]
  n = len(docs)
  df: dict[str, int] = {}
  for terms in tok:
    for t in set(terms):
      df[t] = df.get(t, 0) + 1
  idf = {t: math.log(n / c) + 1.0 for t, c in df.items()}
  vectors = []
  for terms in tok:
    tf: dict[str, int] = {}
    for t in terms:
      tf[t] = tf.get(t, 0) + 1
    vec = {t: (c / len(terms)) * idf[t] for t, c in tf.items() if t in idf}
    vectors.append(vec)
  return {"ok": True, "n_docs": n, "docs": [d["id"] for d in docs],
      "idf": idf, "vectors": vectors,
      "raw": {d["id"]: d["text"] for d in docs}}


def search_rationale(query: str, index: dict[str, Any], *,
           top_k: int = 5) -> dict[str, Any]:
  """检索：查询与理由语料的 TF-IDF 余弦相似度 top-k。"""
  if not index.get("ok"):
    return index
  q_terms = _tokenize(query)
  if not q_terms:
    return {"ok": False, "errors": ["空查询"]}
  tf: dict[str, int] = {}
  for t in q_terms:
    tf[t] = tf.get(t, 0) + 1
  q_vec = {t: (c / len(q_terms)) * index["idf"].get(t, 0.0)
       for t, c in tf.items()}
  q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
  scored = []
  for doc_id, vec in zip(index["docs"], index["vectors"], strict=True):
    dot = sum(q_vec[t] * vec.get(t, 0.0) for t in q_vec)
    d_norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    scored.append((dot / (q_norm * d_norm), doc_id))
  scored.sort(reverse=True)
  hits = [{"doc_id": doc_id, "score": round(s, 6),
       "snippet": index["raw"].get(doc_id, "")[:300]}
      for s, doc_id in scored[:top_k] if s > 0]
  return {"ok": True, "query": query, "n_docs": index["n_docs"],
      "hits": hits}


# ---------------------------------------------------------------------------
# F11 自进化经验记忆：typed 经验条目 + 确定性检索
# （F11 / 第 8 条，与 F2 理由检索 / F3 技能库并轨）
# ---------------------------------------------------------------------------
# 与上面的 TF-IDF 理由检索并存而非替换：上面回答"为什么这么做"（runs/ 产物
# 语料），本段回答"这个坑踩过没有"（踩坑教训/判读结论的 typed 记忆）。
# 检索是确定性关键词/标签子串匹配——无 embedding、无网络、无 LLM（硬约束 6/7），
# 同一输入两次结果逐字节一致。

EXPERIENCE_SCHEMA_VERSION = 1

# 新模板冒烟 / critique 前的强制动作前缀（验收口径：命中即"先离线审计"）
OFFLINE_AUDIT_ACTION_PREFIX = "先离线审计"

# 核对表名（与 core/mesh_artifact.py 的网格病判据同源，#198/#219/#152）
MESH_ARTIFACT_CHECKLIST = "网格伪象核对表"


def _as_text(value: Any) -> str:
  if value is None:
    return ""
  return value if isinstance(value, str) else str(value)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
  """松散值 → 字符串元组（str 视为单元素；映射取文本；其余逐项转文本）。"""
  if value is None:
    return ()
  if isinstance(value, str):
    return (value,)
  if isinstance(value, Mapping):
    return (_as_text(value),)
  return tuple(_as_text(v) for v in value)


@dataclass(frozen=True)
class ExperienceEntry:
  """typed 经验条目（坑编号 + 结论 + 证据链 + 适用场景 + 动作）。

  - lesson_id：坑编号（如 "#198"），与内核 lesson_ref 同源
  - conclusion：一句话结论（战役判读，不含未经核验的新数值）
  - evidence_paths：证据链（测试 / 产物路径），承载可回溯性
  - applies_to：适用场景关键词/标签（确定性匹配用，中英文均可）
  - action：命中后的动作（如"先离线审计……"）
  - checklist：核对表名（如"网格伪象核对表"），同类坑归并到同一张表
  - requires_offline_audit：是否要求冒烟/真跑前先做离线审计（零仿真）
  """

  lesson_id: str
  conclusion: str
  evidence_paths: tuple[str, ...]
  applies_to: tuple[str, ...]
  action: str
  checklist: str
  requires_offline_audit: bool = False
  schema_version: int = EXPERIENCE_SCHEMA_VERSION

  def to_dict(self) -> dict[str, Any]:
    """typed 条目 → JSON 友好 dict（往返 schema）。"""
    return {
      "schema_version": self.schema_version,
      "lesson_id": self.lesson_id,
      "conclusion": self.conclusion,
      "evidence_paths": list(self.evidence_paths),
      "applies_to": list(self.applies_to),
      "action": self.action,
      "checklist": self.checklist,
      "requires_offline_audit": self.requires_offline_audit,
    }

  @classmethod
  def from_dict(cls, data: Mapping[str, Any]) -> ExperienceEntry:
    """JSON 友好 dict → typed 条目（缺字段取空/默认，不抛）。"""
    return cls(
      lesson_id=_as_text(data.get("lesson_id")),
      conclusion=_as_text(data.get("conclusion")),
      evidence_paths=_as_str_tuple(data.get("evidence_paths")),
      applies_to=_as_str_tuple(data.get("applies_to")),
      action=_as_text(data.get("action")),
      checklist=_as_text(data.get("checklist")),
      requires_offline_audit=bool(data.get("requires_offline_audit", False)),
      schema_version=int(data.get("schema_version", EXPERIENCE_SCHEMA_VERSION)),
    )


# 松散条目的键别名（中文键可直接喂给 entry_from_lesson）
_LESSON_KEYS: dict[str, tuple[str, ...]] = {
  "lesson_id": ("lesson_id", "坑编号", "编号", "id"),
  "conclusion": ("conclusion", "结论", "判读", "detail"),
  "evidence_paths": ("evidence_paths", "证据路径", "证据", "evidence"),
  "applies_to": ("applies_to", "适用场景", "场景", "标签", "tags"),
  "action": ("action", "动作", "处置"),
  "checklist": ("checklist", "核对表"),
  "requires_offline_audit": ("requires_offline_audit", "先离线审计"),
}


def entry_from_lesson(lesson: Mapping[str, Any]) -> ExperienceEntry:
  """松散 dict（中英文键均可）→ typed 经验条目。"""
  flat: dict[str, Any] = {}
  for name, aliases in _LESSON_KEYS.items():
    for alias in aliases:
      if alias in lesson:
        flat[name] = lesson[alias]
        break
  return ExperienceEntry.from_dict(flat)


def entries_from_lessons(
  lessons: Sequence[Mapping[str, Any]],
) -> list[ExperienceEntry]:
  """批量沉淀：教训列表 → typed 经验条目列表（保序）。"""
  return [entry_from_lesson(lesson) for lesson in lessons]


# 内置经验（#198/#219/#152 网格病 + 带缘未入网），开箱即可在冒烟前检索命中。
BUILTIN_ENTRIES: tuple[ExperienceEntry, ...] = (
  ExperienceEntry(
    lesson_id="#198",
    conclusion="带缘/断口/端口面未精确入网会让激励体积为零或结构对却激励"
          "不起来（几何画法对 ≠ 入网对）",
    evidence_paths=(
      "src/rfauto/adapters/openems_templates.py（带缘精确入网注释）",
      "tests/unit/test_ratrace_template.py（#212 离线几何审计）",
    ),
    applies_to=("ratrace", "环形", "环带", "带缘", "bend", "弯折", "微带", "断口"),
    action=f"{OFFLINE_AUDIT_ACTION_PREFIX}：渲染 → exec 几何段 → CSXCAD 实测"
        "带宽/连通性/带缘是否入网（零仿真），通过前不得冒烟",
    checklist=MESH_ARTIFACT_CHECKLIST,
    requires_offline_audit=True,
  ),
  ExperienceEntry(
    lesson_id="#219",
    conclusion="0.4mm 阶梯环慢波/容性栅格化伪象：六门在带内低端几乎全过、随 f "
          "单调劣化；等效 εeff 超微带闭式物理上限",
    evidence_paths=(
      "src/rfauto/core/mesh_artifact.py（D11 网格病诊断链）",
    ),
    applies_to=("ratrace", "环形", "环带", "栅格化", "阶梯化", "网格伪象"),
    action=f"{OFFLINE_AUDIT_ACTION_PREFIX}：核对等效 εeff 是否超闭式上限 + 网格"
        "细化中心是否上移；未定性前不得进入校准/细调（先验模型铁律）",
    checklist=MESH_ARTIFACT_CHECKLIST,
    requires_offline_audit=True,
  ),
  ExperienceEntry(
    lesson_id="#152",
    conclusion="AddEdges2Grid/SmoothMesh 留下 nm 级近重合网格线 → CFL 时间步"
          "塌缩 6 个量级，症状是 CalcPort IndexError 而非网格报错",
    evidence_paths=(
      "src/rfauto/core/mesh_artifact.py（timestep_collapse 检查）",
    ),
    applies_to=("网格", "网格线", "网格间距", "timestep", "CFL", "CalcPort", "openems"),
    action=f"{OFFLINE_AUDIT_ACTION_PREFIX}：确认网格构建末尾最小间距守卫（间距"
        " ≥1µm）并核对 timestep 量级恢复",
    checklist=MESH_ARTIFACT_CHECKLIST,
    requires_offline_audit=True,
  ),
)


def _task_text(task: Any) -> str:
  """任务描述（str / 映射 / 列表）→ 确定性扁平文本（键排序，无集合遍历）。"""
  if isinstance(task, Mapping):
    return " ".join(_task_text(task[k]) for k in sorted(task, key=str))
  if isinstance(task, (list, tuple)):
    return " ".join(_task_text(v) for v in task)
  return _as_text(task)


def _matched_terms(text: str, applies_to: Sequence[str]) -> list[str]:
  """命中的场景关键词（子串匹配，排序去重 → 确定性）。"""
  lowered = text.lower()
  return sorted({term for term in applies_to if term and term.lower() in lowered})


def recall_for(task: Any, entries: Sequence[ExperienceEntry] | None = None, *,
        top_k: int = 5, min_score: int = 1) -> dict[str, Any]:
  """新模板冒烟 / critique 前的确定性经验检索（无 embedding、无网络）。

  返回 JSON 契约：ok / task / n_entries / hits / checklists / actions /
  require_offline_audit。hits 按 (-score, lesson_id) 排序，同输入结果一致。
  """
  text = _task_text(task).strip()
  if not text:
    return {"ok": False, "errors": ["空任务描述：无法检索经验记忆"]}
  pool = list(BUILTIN_ENTRIES if entries is None else entries)
  hits: list[dict[str, Any]] = []
  for entry in pool:
    matched = _matched_terms(text, entry.applies_to)
    if len(matched) < min_score:
      continue
    hits.append({
      "lesson_id": entry.lesson_id,
      "score": float(len(matched)),
      "matched": matched,
      "checklist": entry.checklist,
      "action": entry.action,
      "conclusion": entry.conclusion,
      "evidence_paths": list(entry.evidence_paths),
      "requires_offline_audit": entry.requires_offline_audit,
    })
  hits.sort(key=lambda h: (-h["score"], h["lesson_id"]))
  hits = hits[: max(int(top_k), 0)]
  checklists = sorted({h["checklist"] for h in hits if h["checklist"]})
  actions: list[str] = []
  for h in hits:
    if h["action"] and h["action"] not in actions:
      actions.append(h["action"])
  return {
    "ok": True,
    "task": text,
    "n_entries": len(pool),
    "hits": hits,
    "checklists": checklists,
    "actions": actions,
    "require_offline_audit": any(h["requires_offline_audit"] for h in hits),
  }


def checklist_for(template: Any, entries: Sequence[ExperienceEntry] | None = None, *,
         extras: Any = None, top_k: int = 5) -> dict[str, Any]:
  """模板名（可带 extras 场景补充）→ 核对表门禁（冒烟前调用）。

  命中即返回 checklists 与 gate（"先离线审计……"）；未命中则空表、无门禁。
  """
  task: dict[str, Any] = {"template": _task_text(template)}
  if extras is not None:
    task["extras"] = _task_text(extras)
  result = recall_for(task, entries, top_k=top_k)
  if not result.get("ok"):
    return result
  gate = (f"{OFFLINE_AUDIT_ACTION_PREFIX}（离线审计通过前不得冒烟/真跑）"
      if result["require_offline_audit"] else "")
  return {
    "ok": True,
    "template": _task_text(template),
    "checklists": result["checklists"],
    "actions": result["actions"],
    "hits": result["hits"],
    "require_offline_audit": result["require_offline_audit"],
    "gate": gate,
  }


def render_checklist(
  result: Mapping[str, Any],
  *,
  heading: str = "## 历史经验核对表（冒烟/critique 前必读）",
) -> str:
  """检索结果 → 确定性 markdown 章节（无 LLM；未命中返回空串）。"""
  if not result.get("ok"):
    return ""
  hits = list(result.get("hits") or [])
  if not hits:
    return ""
  lines = [heading, ""]
  if result.get("require_offline_audit"):
    lines += [f"> 命中历史经验：冒烟前必须{OFFLINE_AUDIT_ACTION_PREFIX}"
         "（离线几何/物理解析审计，零仿真）。", ""]
  grouped: dict[str, list[Mapping[str, Any]]] = {}
  for hit in hits:
    grouped.setdefault(_as_text(hit.get("checklist")) or "未归类", []).append(hit)
  for name in sorted(grouped):
    group = grouped[name]
    lessons = "/".join(sorted({_as_text(h.get("lesson_id")) or "?" for h in group}))
    lines.append(f"- [ ] {name}（{lessons}）")
    for hit in group:
      lines.append(f" - 结论：{_as_text(hit.get('conclusion'))}")
      lines.append(f" - 动作：{_as_text(hit.get('action'))}")
      for path in hit.get("evidence_paths") or []:
        lines.append(f" - 证据：{_as_text(path)}")
  lines.append("")
  return "\n".join(lines)


def entries_to_payload(entries: Sequence[ExperienceEntry]) -> dict[str, Any]:
  """typed 条目列表 → 可持久化 payload。"""
  return {"schema_version": EXPERIENCE_SCHEMA_VERSION,
      "entries": [e.to_dict() for e in entries]}


def entries_from_payload(payload: Any) -> list[ExperienceEntry]:
  """可持久化 payload（或裸列表）→ typed 条目列表。"""
  raw = payload.get("entries", []) if isinstance(payload, Mapping) else (payload or [])
  return [ExperienceEntry.from_dict(item) for item in raw]


def save_entries(path: str | Path,
         entries: Sequence[ExperienceEntry]) -> dict[str, Any]:
  """经验记忆落盘（UTF-8 / JSON，键排序 → 同内容字节稳定）。"""
  target = Path(path)
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(
    json.dumps(entries_to_payload(entries), ensure_ascii=False, indent=2,
          sort_keys=True),
    encoding="utf-8",
  )
  return {"ok": True, "path": str(target), "n_entries": len(entries)}


def load_entries(path: str | Path) -> dict[str, Any]:
  """读取经验记忆文件（JSON 契约：ok/path/n_entries/entries）。"""
  target = Path(path)
  if not target.exists():
    return {"ok": False, "errors": [f"经验记忆文件不存在: {target}"]}
  try:
    payload = json.loads(target.read_text(encoding="utf-8"))
  except Exception as exc:
    return {"ok": False, "errors": [f"经验记忆文件解析失败: {exc}"]}
  entries = entries_from_payload(payload)
  return {"ok": True, "path": str(target), "n_entries": len(entries),
      "entries": entries}



# ─── F11 CLI/MCP 薄壳入口（JSON 进出、可选外部经验记忆文件）────


def _entries_for(memory_path: str | Path | None,
         include_builtin: bool = True) -> tuple[list[ExperienceEntry] | None, list[str]]:
  """经验池解析：None→内置；给文件则读取（可选并入内置）。返回 (entries, errors)。"""
  if memory_path is None:
    return None, []
  loaded = load_entries(memory_path)
  if not loaded.get("ok"):
    return None, list(loaded.get("errors") or ["经验记忆文件不可用"])
  pool = list(loaded["entries"])
  if include_builtin:
    pool = list(BUILTIN_ENTRIES) + pool
  return pool, []


def recall_with_memory(task: Any, *, memory_path: str | Path | None = None,
            include_builtin: bool = True, top_k: int = 5,
            min_score: int = 1) -> dict[str, Any]:
  """recall_for 的文件面壳：任务描述 + 可选经验记忆 JSON → 命中经验（JSON）。"""
  entries, errors = _entries_for(memory_path, include_builtin)
  if errors:
    return {"ok": False, "errors": errors}
  result = recall_for(task, entries, top_k=top_k, min_score=min_score)
  if result.get("ok"):
    result["memory_path"] = None if memory_path is None else str(memory_path)
  return result


def checklist_with_memory(template: Any, *, extras: Any = None,
             memory_path: str | Path | None = None,
             include_builtin: bool = True,
             top_k: int = 5) -> dict[str, Any]:
  """checklist_for 的文件面壳：模板名（+extras）→ 核对表门禁 + markdown 渲染。"""
  entries, errors = _entries_for(memory_path, include_builtin)
  if errors:
    return {"ok": False, "errors": errors}
  result = checklist_for(template, entries, extras=extras, top_k=top_k)
  if result.get("ok"):
    result["markdown"] = render_checklist(result)
    result["memory_path"] = None if memory_path is None else str(memory_path)
  return result


def search_runs_rationale(query: str, *, runs_dir: str | Path = "runs",
             top_k: int = 5) -> dict[str, Any]:
  """理由语料检索壳：build_index(runs_dir) + search_rationale（TF-IDF 余弦）。

  索引每次调用现建（内存态、确定性）；runs 目录不存在/无语料 ok=False。
  """
  index = build_index(runs_dir)
  if not index.get("ok"):
    return index
  result = search_rationale(query, index, top_k=top_k)
  if result.get("ok"):
    result["runs_dir"] = str(runs_dir)
    result["n_docs"] = index["n_docs"]
  return result
