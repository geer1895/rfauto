"""rlsf_corpus：RLSF 数据飞轮首片（阶段 7.4，ML 系统类比【近】项）。

runs/ 里积累的每次调参轨迹都是模仿学习/RL 的训练样本——每个真实
项目都在为 rfauto 生产训练数据。本模块把 Optuna study（runs/.optuna）
中的 trial 序列抽取为结构化语料：

  {"recipe", "adapter", "steps": [{"trial", "params", "cost",
   "metrics"}], "best_step"}

下游：行为克隆（SFT on 成功轨迹）、预算调度器学习（7.4 第二片）。
确定性内核，纯 stdlib+optuna 读取，无 LLM 参与。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

CORPUS_SCHEMA_VERSION = 1


def _iter_studies(storage_path: Path) -> list[tuple[str, Any]]:
  """列出 storage 里全部 study（best-effort：损坏库跳过）。"""
  import optuna

  optuna.logging.set_verbosity(optuna.logging.WARNING)
  out = []
  try:
    for s in optuna.get_all_study_names(
        f"sqlite:///{storage_path.as_posix()}"):
      try:
        study = optuna.load_study(
          study_name=s,
          storage=f"sqlite:///{storage_path.as_posix()}")
        out.append((s, study))
      except Exception:
        continue
  except Exception:
    pass
  return out


def extract_corpus(
  runs_dir: str | Path = "runs",
  *,
  min_steps: int = 3,
  limit_studies: int | None = None,
) -> dict[str, Any]:
  """从 Optuna storage 抽取全部调参轨迹语料（JSON 契约）。"""
  runs = Path(runs_dir)
  storage = runs / ".optuna" / "optuna.db"
  if not storage.exists():
    return {"ok": False, "errors": [f"Optuna storage 不存在: {storage}"]}
  studies = _iter_studies(storage)
  if limit_studies:
    studies = studies[: int(limit_studies)]
  import optuna

  trajectories = []
  for name, study in studies:
    steps = []
    for t in study.get_trials(deepcopy=False):
      if t.state != optuna.trial.TrialState.COMPLETE or t.value is None:
        continue
      steps.append({
        "trial": t.number,
        "params": {k: float(v) for k, v in t.params.items()},
        "cost": float(t.value),
        "metrics": {
          k: float(v)
          for k, v in (t.user_attrs.get("metrics") or {}).items()
          if isinstance(v, (int, float))
        },
      })
    if len(steps) < min_steps:
      continue
    best = min(steps, key=lambda s: s["cost"])
    trajectories.append({
      "study_name": name,
      "n_steps": len(steps),
      "steps": steps,
      "best_step": best["trial"],
      "best_cost": best["cost"],
    })
  return {
    "ok": True,
    "corpus_schema_version": CORPUS_SCHEMA_VERSION,
    "storage": str(storage),
    "n_trajectories": len(trajectories),
    "n_steps_total": sum(t["n_steps"] for t in trajectories),
    "trajectories": trajectories,
  }


def save_corpus(corpus: dict[str, Any],
        out_path: str | Path | None = None) -> Path:
  """语料落盘（默认 runs/rlsf_corpus/corpus_v{ver}.json）。"""
  out = (Path(out_path) if out_path
      else Path("runs") / "rlsf_corpus"
      / f"corpus_v{CORPUS_SCHEMA_VERSION}.json")
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(json.dumps(corpus, ensure_ascii=False, indent=1),
          encoding="utf-8")
  return out


# ---------------------------------------------------------------------------
# ：语料喂 F11 经验记忆 / WP3.7 任务集（加性；既有 API 不变）
# ---------------------------------------------------------------------------
# 上游仍是 extract_corpus 的确定性 JSON 契约；这里只做纯转换——不发网络、
# 不调 LLM、不产生任何新数值（所有数字都来自语料本身）。

CORPUS_TASKSET_SCHEMA_VERSION = 1
RLSF_CORPUS_CHECKLIST = "RLSF 语料复用核对表"


def _validate_corpus(corpus: Any) -> list[str]:
  """语料契约自检（空错误列表 = 可喂料）。"""
  if not isinstance(corpus, Mapping):
    return ["corpus 必须是映射（extract_corpus 的 JSON 契约）"]
  if not corpus.get("ok"):
    return ["corpus.ok 非真：提取失败或空语料"]
  if not isinstance(corpus.get("trajectories"), (list, tuple)):
    return ["corpus.trajectories 必须是序列"]
  return []


def _trajectories(corpus: Mapping[str, Any],
         limit: int | None) -> list[Mapping[str, Any]]:
  """按 study_name 排序的轨迹列表（确定性；可选截断）。"""
  trajs = [t for t in corpus.get("trajectories") or []
       if isinstance(t, Mapping)]
  trajs.sort(key=lambda t: str(t.get("study_name") or ""))
  if limit is not None:
    trajs = trajs[: max(int(limit), 0)]
  return trajs


def _steps_of(trajectory: Mapping[str, Any]) -> list[Mapping[str, Any]]:
  return [s for s in trajectory.get("steps") or [] if isinstance(s, Mapping)]


def _best_step(trajectory: Mapping[str, Any],
        steps: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
  """最优步：优先按 best_step 的 trial 号定位，退回 cost 最小（确定性）。"""
  best_trial = trajectory.get("best_step")
  for step in steps:
    if step.get("trial") == best_trial:
      return step
  if steps:
    return min(steps, key=lambda s: float(s.get("cost") or 0.0))
  return {}


def _params_of(step: Mapping[str, Any]) -> dict[str, Any]:
  """最优步参数（键排序 → 确定性）。"""
  params = step.get("params") if isinstance(step, Mapping) else None
  if not isinstance(params, Mapping):
    return {}
  return dict(sorted(((str(k), v) for k, v in params.items()),
            key=lambda kv: kv[0]))


def _fmt(value: Any) -> str:
  """数值 → 稳定文本（6 位有效数字；非数值原样 str）。"""
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return str(value)
  return f"{float(value):.6g}"


def corpus_to_experience_entries(
  corpus: Any,
  *,
  checklist: str = RLSF_CORPUS_CHECKLIST,
  limit: int | None = None,
) -> list[Any]:
  """语料 → F11 typed 经验条目（rationale_memory.ExperienceEntry 列表）。

  非法/空语料返回 []（不发网络、不调 LLM）；所有数字来自语料本身。
  """
  from rfauto.service.rationale_memory import ExperienceEntry

  if _validate_corpus(corpus):
    return []
  storage = str(corpus.get("storage") or "")
  entries: list[Any] = []
  for trajectory in _trajectories(corpus, limit):
    name = str(trajectory.get("study_name") or "")
    steps = _steps_of(trajectory)
    best = _best_step(trajectory, steps)
    params = _params_of(best)
    param_text = ", ".join(f"{k}={_fmt(v)}" for k, v in params.items())
    applies = list(dict.fromkeys([name, *params]))
    evidence = [
      f"{storage}#{name}" if storage else f"runs/.optuna/optuna.db#{name}",
      f"study={name} best_trial={best.get('trial')}",
    ]
    entries.append(ExperienceEntry(
      lesson_id=f"rlsf:{name}",
      conclusion=(f"{name} 的最优 trial #{best.get('trial')} "
            f"cost={_fmt(best.get('cost'))}（{len(steps)} 步）"
            + (f"；参数 {param_text}" if param_text else "")),
      evidence_paths=tuple(evidence),
      applies_to=tuple(x for x in applies if x),
      action=f"先离线审计：用 study inject 回放 {name} 最优参数，"
          "复现 cost 一致后再改动",
      checklist=checklist,
      requires_offline_audit=True,
    ))
  return entries


def corpus_to_taskset(
  corpus: Any,
  *,
  level: int = 3,
  limit: int | None = None,
) -> dict[str, Any]:
  """语料 → WP3.7 goldset 形任务集（id/level/prompt/expected.calls 齐全）。

  每任务把 study 最优参数回放成 "study inject" typed 调用（金标同构）；
  provenance 保留 study_name/best_step/best_cost/n_steps 供溯源。
  """
  errors = _validate_corpus(corpus)
  if errors:
    return {"ok": False, "errors": errors}
  storage = str(corpus.get("storage") or "")
  tasks: list[dict[str, Any]] = []
  for trajectory in _trajectories(corpus, limit):
    name = str(trajectory.get("study_name") or "")
    steps = _steps_of(trajectory)
    best = _best_step(trajectory, steps)
    tasks.append({
      "id": f"rlsf_{name}",
      "level": int(level),
      "category": "rlsf_replay",
      "prompt": (f"复现 study {name} 的最优参数（最优 trial "
            f"#{best.get('trial')}，cost={_fmt(best.get('cost'))}，"
            f"共 {len(steps)} 步）"),
      "expected": {"calls": [{
        "tool": "study inject",
        "args": {"study_name": name, "params": _params_of(best)},
      }]},
      "provenance": {
        "source": "rlsf_corpus",
        "study_name": name,
        "best_step": best.get("trial"),
        "best_cost": best.get("cost"),
        "n_steps": len(steps),
        "storage": storage,
      },
    })
  return {
    "ok": True,
    "taskset_schema_version": CORPUS_TASKSET_SCHEMA_VERSION,
    "source": "rlsf_corpus",
    "storage": storage,
    "n_tasks": len(tasks),
    "tasks": tasks,
  }


def feed_rationale_memory(
  corpus: Any,
  path: str | Path,
  *,
  checklist: str = RLSF_CORPUS_CHECKLIST,
  limit: int | None = None,
) -> dict[str, Any]:
  """喂料接口：语料 → F11 经验条目 → 落盘（rationale_memory.save_entries）。"""
  from rfauto.service.rationale_memory import save_entries

  errors = _validate_corpus(corpus)
  if errors:
    return {"ok": False, "errors": errors}
  entries = corpus_to_experience_entries(corpus, checklist=checklist,
                      limit=limit)
  saved = save_entries(path, entries)
  return {**saved, "n_entries": len(entries), "checklist": checklist}
