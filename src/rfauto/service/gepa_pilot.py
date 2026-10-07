"""gepa_pilot：GEPA 式离线提示词进化试点（AD-6，round15 §五；实验面）。

规格：研究扩充 round15 AD-6「dspy GEPA 以
goldset 为 metric 优化 prompt 候选，人工裁决入库（P2/L）」；no-go 行明文：
「LangGraph/DSPy 进生产硬依赖」「GEPA 产物免审入库」。

本模块是**实验脚本面**（服务层库形态，无 CLI/MCP 新面——席 B1 纪律 4）：
- 产品路径仍静态：系统提示词单源=configs/prompts/system_prompt.md（AD-1），
  本模块只产候选与证据到 runs/gepa_pilot/，绝不写产品提示词；
- dspy 为可选依赖（MIT）：未安装时走 ``builtin_reflective`` 后端（自研
  反射式进化：变异池+精英保留，分数只出自确定性打分内核），装了 dspy 也
  不自动切换——后端由调用方显式传参选择，行为可预期；
- 人工裁决门：候选落盘带 ``approved: False``；``promote_candidate`` 必须
  显式 ``approved=True`` 且带复核注记，产物只进 runs/gepa_pilot/promoted/
  （仍是 runs/ 实验区，产品采纳=人工按 AD-1 面编辑外置提示词并走
  bench prompt-regression 门）。

铁律落地：
- 铁律 7：分数只出自 agent_bench.score_agent_task 确定性打分内核；LLM
  只出现在两处注入缝——``mutation_fn``（产候选变异）与
  ``trajectory_provider``（产任务轨迹），本模块自身零网络；测试一律
  monkeypatch/scripted 钉死通道（#139）。
- 判据预声明：选择=分数降序、同分按候选名字典序（无墙钟无随机进决策）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

GEPA_PILOT_SCHEMA = "rfauto-gepa-pilot-v1"
GEPA_PILOT_DIR = Path("runs") / "gepa_pilot"

#: 每轮保留的精英数（含全局最佳；GEPA 文本池保留语义的简化版）。
KEEP_TOP_DEFAULT = 2

# LLM 通道类型（注入缝，#139）：
#   mutation_fn(prompt_text, round_no, feedback) -> [{"name", "prompt_text"}]
#   trajectory_provider(task, prompt_text) -> 轨迹序列或完整 record
MutationFn = Callable[[str, int, Mapping[str, Any]], list[dict[str, Any]]]
TrajectoryProvider = Callable[[Mapping[str, Any], str], Any]


def dspy_available() -> bool:
    """dspy 是否已安装（可选依赖探测，零导入副作用）。"""
    import importlib.util

    return importlib.util.find_spec("dspy") is not None


def _seed_prompt_default() -> str:
    """缺省种子提示词=当前生效系统提示词（AD-1 外置单源；失败回退占位）。"""
    try:
        from rfauto.service.r3_services import get_system_prompt

        text = get_system_prompt()
        if text and text.strip():
            return text
    except Exception:  # 提示词面不可用不阻塞试点（#105）
        pass
    return "你是 rfauto 助手。（内置回退种子——外置提示词不可用，#105）"


def score_prompt(prompt_text: str, tasks: Sequence[Mapping[str, Any]],
                 trajectory_provider: TrajectoryProvider | None,
                 ) -> dict[str, Any]:
    """单候选提示词在任务集上的确定性得分（两轴宏平均，零网络）。

    trajectory_provider 注入轨迹通道（#139：调用方/测试注入，本函数不发
    任何请求）；provider(task, prompt_text) 返回映射视为完整 record、返回
    序列视为轨迹（按 goldset 评测同款兼容口径）。单任务打分失败如实计 0
    并留痕（不抛、不凑）。
    """
    from rfauto.service.agent_bench import score_agent_task

    per_task: list[dict[str, Any]] = []
    abs_sum = exec_sum = 0.0
    n_scored = 0
    errors: list[str] = []
    for task in tasks:
        tid = str(task.get("id") or "")
        try:
            raw = (trajectory_provider(task, prompt_text)
                   if trajectory_provider is not None else {})
            record = raw if isinstance(raw, Mapping) else {
                "id": tid, "trajectory": list(raw or [])}
            scored = score_agent_task(task, record)
            if "error" in scored:
                errors.append(f"{tid}: {scored['error']}")
                per_task.append({"id": tid, "error": scored["error"]})
                continue
            abstraction = float(scored.get("abstraction") or 0.0)
            execution = float(scored.get("execution") or 0.0)
        except Exception as exc:  # 通道异常=该任务 0 分留痕（#105）
            errors.append(f"{tid}: {type(exc).__name__}: {exc}")
            per_task.append({"id": tid, "error": str(exc)})
            continue
        abs_sum += abstraction
        exec_sum += execution
        n_scored += 1
        per_task.append({"id": tid, "abstraction": abstraction,
                         "execution": execution})
    n = max(len(tasks), 1)
    return {
        "ok": not errors,
        "score": (abs_sum + exec_sum) / (2 * n),
        "abstraction": abs_sum / n,
        "execution": exec_sum / n,
        "n_tasks": len(tasks), "n_scored": n_scored,
        "errors": errors, "per_task": per_task,
    }


def _builtin_mutations(prompt_text: str, round_no: int,
                       feedback: Mapping[str, Any]) -> list[dict[str, Any]]:
    """无 LLM 通道时的确定性内置变异池（试点离线可跑；实验语义）。

    三个模板变异：追加工具预算提醒 / 追加"先只读后写"顺序提醒 /
    追加数值溯源提醒——全部为提示词工程常用通用项，不产生任何物理数字。
    """
    variants = [
        ("budget_reminder", "\n注意：单轮任务尽量在 6 次工具调用内完成并给出最终答复。"),
        ("readonly_first", "\n注意：先做只读探索（至多 1-2 次），再考虑提案类工具。"),
        ("provenance", "\n注意：引用数值时说明它来自哪个工具的实测返回。"),
    ]
    return [{"name": f"r{round_no}_{name}",
             "prompt_text": prompt_text + suffix}
            for name, suffix in variants]


def _prompt_sha(prompt_text: str) -> str:
    return hashlib.sha256(str(prompt_text).encode("utf-8")).hexdigest()[:12]


def evolve_prompts(seed_prompt: str, tasks: Sequence[Mapping[str, Any]],
                   trajectory_provider: TrajectoryProvider | None,
                   *, rounds: int = 2,
                   mutation_fn: MutationFn | None = None,
                   keep_top: int = KEEP_TOP_DEFAULT) -> dict[str, Any]:
    """反射式提示进化主环（确定性选择，通道全部注入）。

    每轮：当前池逐候选打分 → 分数降序（同分按名字典序）保留 top keep_top →
    以最佳者分数轨迹为反馈调 mutation_fn 产下一代变异（mutation_fn 缺省=
    内置确定性变异池，零 LLM 可跑）。全局最佳全程追踪，trace 逐轮留痕。
    """
    if not tasks:
        return error_envelope(["任务集为空：拒绝空跑（防空转）"])
    mutation = mutation_fn or _builtin_mutations
    pool: dict[str, str] = {"seed": str(seed_prompt)}
    best_name, best_score, best_text = "seed", None, str(seed_prompt)
    trace: list[dict[str, Any]] = []
    for round_no in range(1, max(1, int(rounds)) + 1):
        scored: list[dict[str, Any]] = []
        for name in sorted(pool):
            result = score_prompt(pool[name], tasks, trajectory_provider)
            scored.append({"name": name, "score": result["score"],
                           "abstraction": result["abstraction"],
                           "execution": result["execution"],
                           "prompt_text": pool[name],
                           "sha": _prompt_sha(pool[name]),
                           "errors": result["errors"]})
            if best_score is None or result["score"] > best_score:
                best_score, best_name, best_text = (
                    result["score"], name, pool[name])
        scored.sort(key=lambda c: (-c["score"], c["name"]))
        survivors = scored[:max(1, int(keep_top))]
        trace.append({"round": round_no,
                      "scored": [{k: v for k, v in c.items()
                                  if k != "prompt_text"} for c in scored],
                      "survivors": [c["name"] for c in survivors],
                      "best_score": best_score})
        base = survivors[0]
        for variant in mutation(base["prompt_text"], round_no,
                                {"best_score": base["score"],
                                 "best_name": base["name"],
                                 "errors": base["errors"]}):
            vname = str(variant.get("name") or f"r{round_no}_variant")
            vtext = str(variant.get("prompt_text") or "")
            if vtext:
                pool[vname] = vtext
    return ok_envelope(
        best={"name": best_name, "score": best_score,
                     "prompt_text": best_text, "sha": _prompt_sha(best_text)},
        trace=trace,
        rounds=max(1, int(rounds)),
        errors=[],
    )


def run_gepa_pilot(*, seed_prompt: str | None = None,
                   tasks: Sequence[Mapping[str, Any]] | None = None,
                   public_path: str | Path | None = None,
                   trajectory_provider: TrajectoryProvider | None = None,
                   mutation_fn: MutationFn | None = None,
                   rounds: int = 2, keep_top: int = KEEP_TOP_DEFAULT,
                   backend: str | None = None,
                   out_dir: str | Path | None = GEPA_PILOT_DIR,
                   ) -> dict[str, Any]:
    """AD-6 试点入口：goldset 任务集为 metric 的离线提示词进化（永不抛）。

    backend：None=按 dspy 可用性如实记录（``dspy``/``builtin_reflective``），
    但**两种情况下执行核相同**（自研反射环）——dspy 只是可选加速器，不是
    本模块的执行依赖（no-go：DSPy 进生产硬依赖）。tasks 缺省=公开 goldset
    任务集（agent_bench.load_bench_set）。
    out_dir 非空时结果落 <out_dir>/pilot_<best_sha>.json，带 approved=False。
    """
    try:
        seed = seed_prompt if seed_prompt is not None else _seed_prompt_default()
        if tasks is None:
            from rfauto.service.agent_bench import default_public_path, load_bench_set

            bench = load_bench_set(public_path or default_public_path())
            if not bench.get("ok"):
                return {"ok": False, "schema_version": GEPA_PILOT_SCHEMA,
                        "errors": [f"goldset 加载失败: "
                                   f"{list(bench.get('errors') or [])}"]}
            tasks = list(bench.get("tasks") or [])
        evolved = evolve_prompts(seed, tasks, trajectory_provider,
                                 rounds=rounds, mutation_fn=mutation_fn,
                                 keep_top=keep_top)
        record: dict[str, Any] = {
            "ok": evolved["ok"], "schema_version": GEPA_PILOT_SCHEMA,
            "gate_kind": "gepa_pilot",
            "backend": backend or ("dspy" if dspy_available()
                                   else "builtin_reflective"),
            "dspy_installed": dspy_available(),
            "product_path": "static（本试点不写产品提示词，人工裁决后走 AD-1 面）",
            "seed_sha": _prompt_sha(seed),
            "best": evolved.get("best"), "trace": evolved.get("trace"),
            "rounds": evolved.get("rounds"),
            "approved": False,
            "errors": list(evolved.get("errors") or []),
        }
        if out_dir is not None and record["ok"]:
            target = Path(out_dir)
            target.mkdir(parents=True, exist_ok=True)
            path = target / f"pilot_{record['best']['sha']}.json"
            path.write_text(json.dumps(record, ensure_ascii=False, indent=1,
                                       default=str), encoding="utf-8")
            record["record_path"] = str(path)
        return record
    except Exception as exc:  # 试点面永不阻塞主路径（#105）
        return {"ok": False, "schema_version": GEPA_PILOT_SCHEMA,
                "errors": [f"{type(exc).__name__}: {exc}"]}


def promote_candidate(record: Mapping[str, Any], *, approved: bool,
                      reviewer_note: str = "",
                      promoted_dir: str | Path | None = None,
                      ) -> dict[str, Any]:
    """人工裁决门：GEPA 产物免审入库=no-go——approved 与复核注记缺一即拒。

    产物只进 runs/gepa_pilot/promoted/（实验区），返回候选文本与目标路径；
    产品提示词（configs/prompts/system_prompt.md）本函数**永不触碰**。
    """
    if not approved:
        return {"ok": False, "promoted": False,
                "errors": ["未获人工批准（approved=False）——GEPA 产物免审"
                           "入库是 no-go（round15 §五）"]}
    note = str(reviewer_note or "").strip()
    if not note:
        return {"ok": False, "promoted": False,
                "errors": ["缺复核注记（reviewer_note）——裁决必须留痕"]}
    best = record.get("best") or {}
    text = str(best.get("prompt_text") or "")
    if not text.strip():
        return {"ok": False, "promoted": False, "errors": ["候选正文为空"]}
    target_dir = Path(promoted_dir) if promoted_dir else (
        GEPA_PILOT_DIR / "promoted")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{_prompt_sha(text)}.md"
    path.write_text(text, encoding="utf-8")
    return ok_envelope(
        promoted=True,
        path=str(path),
        sha=_prompt_sha(text),
        reviewer_note=note,
        adoption="产品采纳须人工编辑 configs/prompts/system_prompt.md"
                        " 并过 bench prompt-regression 门（AD-1）",
    )
