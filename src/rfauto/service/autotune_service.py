"""autotune_loop：确定性 critique 自治调优环（阶段 2.1，与既有闭环调优环同构）。

环结构（无人在环，HFSS 仅终验）：
    synthesis/名义点 → openEMS 快验证 → 确定性评判器 critique_point →
    带界修正建议（typed dict）→ 应用（限幅+限步长）→ 复验 … N 轮或 PASS。

铁律落地：
- 数值只在确定性内核（阶段 2.3）：评判器产出的每条 fix 都是 typed dict
  （参数名/方向/步长/依据），不经过任何 LLM；
- FAIL 如实记录：budget 用尽未达标 = verdict FAIL + 未决 issue 清单；
- 采样执行与环逻辑分离：sampler_fn 注入（真机 openEMS / 测试 fake）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ─── 确定性评判器 ────────────────────────────────────────────────────────────

_LENGTH_HINTS = ("len", "length", "_l_")
_WIDTH_HINTS = ("_w", "width")


def _is_length_param(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in _LENGTH_HINTS)


def _is_width_param(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in _WIDTH_HINTS) and not _is_length_param(name)


def critique_point(
    metrics: dict[str, float],
    objectives: list[dict[str, Any]],
    *,
    valley_ghz: float | None = None,
    bounds: dict[str, tuple[float, float]] | None = None,
    current_params: dict[str, float] | None = None,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """确定性评判（无 LLM）：指标+谷位 → PASS/issues/typed fixes。

    规则（v1，全部带界）：
    1. objectives 违约检查（SpecEvaluator 口径一致）；
    2. 谷位偏离带中心 > f0_tolerance → 长度类参数按频率比缩放
       （谷偏低=电长偏长 → 缩短），步长限 max_step_pct；
    3. 谷位准但回损浅于 rl_floor_db → 宽度类参数进入坐标探测队列
       （方向由环内探测决定，评判器只发 typed 指令）。
    """
    issues: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []

    # 规则 1：objectives 违约
    from rfauto.core.objectives import Objective, SpecEvaluator

    objs = [Objective(**o) for o in objectives]
    violations = {
        o.metric: float(metrics.get(o.metric, 0.0))
        for o in objs
        if SpecEvaluator.evaluate_objectives(metrics, [o]) > 0
    }

    band_center = None
    for o in objs:
        if isinstance(o.band, (list, tuple)) and len(o.band) == 2:
            band_center = (float(o.band[0]) + float(o.band[1])) / 2
            break

    # 规则 2：频率尺度（谷位 vs 带中心）。f ∝ 1/L：谷偏低（ratio<1）→ 缩短
    freq_ok = True
    if valley_ghz is not None and band_center is not None and band_center > 0:
        ratio = float(valley_ghz) / band_center
        if abs(1 - ratio) > f0_tolerance:
            freq_ok = False
            scale = ratio  # L_new = L × (fv/fc)
            scale = max(1.0 - max_step_pct, min(1.0 + max_step_pct, scale))
            for name, value in (current_params or {}).items():
                if _is_length_param(name):
                    new_v = float(value) * scale
                    if bounds and name in bounds:
                        new_v = max(bounds[name][0], min(bounds[name][1], new_v))
                    fixes.append({
                        "param": name, "op": "scale", "value": round(new_v, 6),
                        "reason": f"valley {valley_ghz:.3f}GHz vs band center "
                                  f"{band_center:.3f}GHz（偏 {1 - ratio:+.0%}）",
                        "kind": "freq_scale",
                    })
            if not any(f["kind"] == "freq_scale" for f in fixes):
                issues.append({
                    "kind": "freq_scale_no_param",
                    "detail": "谷位偏离但无长度类可调参数",
                })

    # 规则 3：匹配深度（谷位准但 RL 浅）→ 宽度类坐标探测
    rl = metrics.get("s11_db_max_in_band")
    if rl is not None and freq_ok and rl > rl_floor_db:
        width_params = [n for n in (current_params or {}) if _is_width_param(n)]
        if width_params:
            fixes.append({
                "param": width_params,
                "op": "coord_probe",
                "value": max_step_pct / 2,
                "reason": f"RL {rl:.1f}dB 浅于地板 {rl_floor_db}dB（谷位准）",
                "kind": "rl_probe",
            })
        else:
            issues.append({
                "kind": "rl_shallow",
                "detail": f"RL {rl:.1f}dB 浅于 {rl_floor_db}dB 且无宽度类参数",
            })

    for m, v in violations.items():
        issues.append({"kind": "objective_violation", "metric": m, "value": v})

    verdict = "PASS" if (not violations and not fixes) else "FAIL"
    return {"verdict": verdict, "issues": issues, "fixes": fixes,
            "violations": violations}


# ─── 环编排 ──────────────────────────────────────────────────────────────────

def _make_openems_sampler(model: str, freq_range: tuple[float, float],
                          objectives: list[dict[str, Any]], *,
                          mesh_resolution_mm: float,
                          work_root: Path) -> Callable[[dict[str, float]], dict[str, Any]]:
    """openEMS 快验证采样器：params → {"metrics", "valley_ghz"}（真机）。

    与 calibration_service 的采样器同口径；额外提取 |S11| 谷位供确定性
    评判器做频率尺度规则（谷位不可得时返回 None，评判器保守降级，#105）。
    """
    import skrf

    from rfauto.adapters.em_solver_base import (
        EMSolverConfig,
        resolve_openems_exe,
    )
    from rfauto.adapters.openems_solver import OpenEMSSolver
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.service.calibration_service import _template_for

    template = _template_for(model)
    objs = [Objective(**o) for o in objectives]

    def run(params: dict[str, float]) -> dict[str, Any]:
        work = work_root / f"pt_{int(time.time() * 1000) % 10**10}"
        solver = OpenEMSSolver(EMSolverConfig(
            solver_type="openems",
            exe_path=resolve_openems_exe(),
            working_dir=str(work),
            freq_range_ghz=tuple(freq_range),
            mesh_resolution_mm=mesh_resolution_mm,
        ))
        if not solver.connect():
            raise RuntimeError("openEMS 不可用（exe 未找到）")
        if not solver.build_geometry({"template": template, "params": params}):
            raise RuntimeError("openEMS 几何构建失败")
        result = solver.solve()
        if not result.success or result.s_params is None:
            raise RuntimeError(f"openEMS 求解失败: {result.message}")
        network = skrf.Network(
            frequency=skrf.Frequency(
                result.freq_ghz[0], result.freq_ghz[-1],
                len(result.freq_ghz), unit="ghz"),
            s=result.s_params, z0=50.0)
        metrics = SpecEvaluator.compute_metrics(network, objs)
        valley = _s11_valley_ghz(network)
        return {"metrics": metrics, "valley_ghz": valley}

    return run


def _s11_valley_ghz(network: Any) -> float | None:
    """|S11| 主谷频率（GHz）；全通/无谷返回 None。"""
    import numpy as np

    try:
        f = np.asarray(network.f, dtype=float)  # Hz
        mag = np.abs(network.s[:, 0, 0])
        if len(f) < 3:
            return None
        i = int(np.argmin(mag))
        if 0 < i < len(mag) - 1:  # 内点才是谷（端点是截断）
            return float(f[i] / 1e9)
    except Exception:
        return None
    return None

def _apply_fixes(params: dict[str, float], fixes: list[dict[str, Any]],
                 bounds: dict[str, tuple[float, float]]) -> dict[str, float]:
    """应用 typed fixes（全部限界）。"""
    out = dict(params)
    for f in fixes:
        name = f["param"]
        if isinstance(name, list):  # coord_probe 的宽度参数组
            continue
        if name not in out:
            continue
        v = float(f["value"])
        if bounds and name in bounds:
            v = max(bounds[name][0], min(bounds[name][1], v))
        out[name] = v
    return out


def _coord_probe(param: str, base: dict[str, float], bounds: dict[str, tuple[float, float]],
                 step_pct: float, sampler_fn: Callable[[dict[str, float]], dict[str, Any]],
                 cost_fn: Callable[[dict[str, float]], float]) -> tuple[dict[str, float], float] | None:
    """单参数 ±step 探测，返回更优者（确定性坐标下降）。"""
    best = None
    for sign in (+1.0, -1.0):
        trial = dict(base)
        v = float(base[param]) * (1 + sign * step_pct)
        if param in bounds:
            v = max(bounds[param][0], min(bounds[param][1], v))
        if v == float(base[param]):
            continue
        trial[param] = v
        try:
            res = sampler_fn(trial)
            c = cost_fn(res["metrics"])
        except Exception:
            continue
        if best is None or c < best[1]:
            best = (trial, c)
    return best


def autotune_loop(
    recipe_path: str | Path,
    *,
    sampler_fn: Callable[[dict[str, float]], dict[str, Any]] | None = None,
    budget: int = 3,
    mesh_resolution_mm: float = 0.0,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
    probes_per_round: int = 4,
    replan_plan_path: str | Path | None = None,
) -> dict[str, Any]:
    """自治调优环：budget 轮「求解→评判→界内修正→复验」，无人在环。

    sampler_fn 返回 {"metrics": {...}, "valley_ghz": float|None}；
    缺省用 openEMS 快验证通道（真机，串行纪律）。返回 JSON 契约，
    verdict=PASS|FAIL（FAIL 如实，附未决 issues 与逐轮历史）。

    R3 opt-in（缺省关，零行为变化）：replan_plan_path 给出时，环结束即把
    本批（fake 批=stage1）cost 历史走 replan_service 退化判定+决策表，
    决策落 checkpoint 一等对象（判据/决策表预声明于 runs/df7_r3aqe/
    criteria.md；#195/#207 常数陷阱拦在烧真机之前）。缺省 None 时结果
    契约逐键不变。
    """
    import yaml

    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, write_meta

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    opt = recipe.get("optimization") or {}
    bounds = {k: (float(v["low"]), float(v["high"]))
              for k, v in (opt.get("params") or {}).items()}
    objectives = list(recipe.get("objectives", []))
    if not objectives:
        return {"ok": False, "errors": ["配方无 objectives，无从评判"]}
    freq_range = tuple((recipe.get("setup") or {}).get("freq_range_ghz", (1.0, 5.0)))

    if sampler_fn is None:
        sampler_fn = _make_openems_sampler(
            str(recipe.get("model", "")), freq_range, objectives,
            mesh_resolution_mm=mesh_resolution_mm,
            work_root=Path("runs") / f"autotune_work_{generate_run_id()}")

    def cost_of(metrics: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(
            metrics, [Objective(**o) for o in objectives])

    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)

    current = {k: (float(v[0]) + float(v[1])) / 2 for k, v in bounds.items()}
    # 名义点优先（配方 params 中与 bounds 对应者）
    for k in current:
        pv = (recipe.get("params") or {}).get(k)
        if isinstance(pv, dict) and isinstance(pv.get("value"), (int, float)):
            current[k] = float(pv["value"])

    history: list[dict[str, Any]] = []
    verdict = "FAIL"
    best: dict[str, Any] | None = None
    t0 = time.time()

    for rnd in range(1, budget + 1):
        try:
            res = sampler_fn(current)
        except Exception as exc:
            history.append({"round": rnd, "params": current, "error": str(exc)})
            break
        metrics = res["metrics"]
        cost = cost_of(metrics)
        c = critique_point(metrics, objectives, valley_ghz=res.get("valley_ghz"),
                           bounds=bounds, current_params=current,
                           f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
                           max_step_pct=max_step_pct)
        entry = {"round": rnd, "params": current, "metrics": metrics,
                 "cost": cost, "verdict": c["verdict"],
                 "issues": c["issues"], "fixes": c["fixes"]}
        history.append(entry)
        if best is None or cost < best["cost"]:
            best = {"round": rnd, "params": current, "metrics": metrics,
                    "cost": cost}
        if c["verdict"] == "PASS":
            verdict = "PASS"
            break

        # 应用 typed fixes
        applied = _apply_fixes(current, c["fixes"], bounds)
        # coord_probe：宽度类坐标下降（限 probes_per_round）
        n_probes = 0
        for f in c["fixes"]:
            if f.get("op") != "coord_probe" or n_probes >= probes_per_round:
                continue
            for pname in f["param"]:
                if n_probes >= probes_per_round:
                    break
                probe = _coord_probe(pname, applied, bounds,
                                     float(f["value"]), sampler_fn, cost_of)
                n_probes += 1
                if probe is not None and probe[1] < cost:
                    applied, cost = probe[0], probe[1]
        if applied == current:
            # 无 fix 可应用：环已无确定性改进方向，如实停
            verdict = "FAIL"
            break
        current = applied

    elapsed = time.time() - t0

    # R3 opt-in（缺省关）：fake 批产出即查 cost 分布退化 → 决策 checkpoint
    replan_plan: dict[str, Any] | None = None
    if replan_plan_path is not None:
        from rfauto.service.replan_service import (
            assess_cost_degeneration,
            replan_route,
            save_replan_checkpoint,
        )

        points = [{"cost": h["cost"], "round": h["round"]}
                  for h in history if "cost" in h]
        assessment = assess_cost_degeneration(points)
        decision = replan_route(assessment, {"stage": "fake_batch"})
        saved = save_replan_checkpoint(replan_plan_path, decision)
        replan_plan = {"assessment": assessment, "decision": decision,
                       "checkpoint": saved}

    result: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "verdict": verdict,
        "budget": budget,
        "rounds_used": len(history),
        "best": best,
        "final_params": current,
        "history": history,
        "elapsed_s": round(elapsed, 1),
    }
    if replan_plan is not None:
        result["replan_plan"] = replan_plan
    (run_dir / "autotune.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    write_meta(run_dir, {
        "run_id": run_id, "model": str(recipe.get("model", "")),
        "status": "done", "adapter": "autotune:openems",
        "algorithm": "autotune_loop",
        "metrics": {"verdict": verdict, "rounds": len(history),
                    "best_cost": best["cost"] if best else None}})
    record_run(record={
        "run_id": run_id, "model": str(recipe.get("model", "")),
        "adapter": "autotune:openems", "status": "done",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {"verdict": verdict}})
    return result


def autotune_to_sandbox(
    recipe_path: str | Path,
    run_id: str,
    *,
    sandbox: Any | None = None,
) -> dict[str, Any]:
    """自治环结果 → 沙箱草稿（阶段 2.5：人审点保留）。

    读取 runs/<run_id>/autotune.json 的 final_params，经 RecipeSandbox
    合并进草稿；promote 走既有三层 Gate（本函数不直接改真实配方——
    agent 写面隔离）。
    """
    from rfauto.service.agent_sandbox import RecipeSandbox

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    autotune_json = Path("runs") / run_id / "autotune.json"
    if not autotune_json.exists():
        return {"ok": False, "errors": [f"自治环产物不存在: {autotune_json}"]}
    data = json.loads(autotune_json.read_text(encoding="utf-8"))
    final_params = data.get("final_params") or {}
    if not final_params:
        return {"ok": False, "errors": ["自治环产物无 final_params"]}

    sb = sandbox or RecipeSandbox()
    applied = sb.apply_param_edits(path, final_params)
    if not applied.get("ok"):
        return {**applied, "ok": applied.get("ok", False)}
    return {
        "ok": True,
        "run_id": run_id,
        "recipe": str(path),
        "draft": applied["draft"],
        "applied_params": applied.get("applied", final_params),
        "verdict": data.get("verdict"),
        "next": "promote 走既有三层 Gate（rfauto inbox / agent apply）",
    }


def orchestrate_tournament(
    recipe_path: str | Path,
    variants: list[dict[str, float]],
    *,
    sampler_factory: Any | None = None,
    small_budget: int = 2,
    mesh_resolution_mm: float = 0.0,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
) -> dict[str, Any]:
    """Goal 编排锦标赛（阶段 5.4 首片，Co-Scientist 式：variants=假设起点）。

    每个变体以小预算跑一轮确定性自治环 → 按 best cost 排序出胜者。
    变体由调用方给定（LLM 只出假设参数起点——typed；数值裁决归自治环）；
    全程无人在环，HFSS 仅终验。
    """
    import yaml as _yaml

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = _yaml.safe_load(f) or {}
    if not variants:
        return {"ok": False, "errors": ["variants 为空（至少 1 个假设起点）"]}

    trials = []
    for idx, start_params in enumerate(variants):
        patched = dict(recipe)
        params_sec = dict(patched.get("params") or {})
        for name, value in start_params.items():
            entry = params_sec.get(name)
            if isinstance(entry, dict):
                patched_entry = dict(entry)
                patched_entry["value"] = value
                params_sec[name] = patched_entry
            else:
                params_sec[name] = value
        patched["params"] = params_sec
        # 变体是临时工作文件：源配方在 recipes/ 下时经守卫重定向到
        # runs/recipe_workcopy/（禁在 recipes/ 生成 *_variantN.yaml）
        from rfauto.infra.recipe_guard import write_recipe_yaml

        variant_path = write_recipe_yaml(
            path.parent / (path.stem + f"_variant{idx}.yaml"), patched, redirect=True)
        r = autotune_loop(
            variant_path,
            sampler_fn=(sampler_factory(idx) if sampler_factory else None),
            budget=small_budget, mesh_resolution_mm=mesh_resolution_mm,
            f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
            max_step_pct=max_step_pct)
        best = r.get("best") or {}
        trials.append({
            "variant_index": idx,
            "start_params": start_params,
            "run_id": r.get("run_id"),
            "verdict": r.get("verdict"),
            "best_cost": best.get("cost"),
            "rounds_used": r.get("rounds_used"),
        })
        variant_path.unlink(missing_ok=True)

    ranked = sorted(
        (t for t in trials if t.get("best_cost") is not None),
        key=lambda t: t["best_cost"])
    winner = ranked[0] if ranked else None
    return {
        "ok": True,
        "recipe": str(path),
        "n_variants": len(variants),
        "trials": trials,
        "winner": winner,
        "note": "胜者加大预算复验前，先按 2.5 落沙箱草稿走三层 Gate",
    }


# ─── WP3.5 自验证环收口：propose→verify→fix 闭环 + milestone 由易到难 ────────
# 方案 §4 WP3.5 口径：
#   propose（LLM/优化器，typed call）→ verify（确定性内核：引擎基准+闭式对照）
#   → fix（确定性 critique_point）闭环；propose 必须输出"由易到难 milestone
#   分解"（粗网格→细网格、单点→战役，逐里程碑验收）；执行看板（暂停/接管）
#   见 service/loop_board.py（CLI 批处理 + GUI 观察的折中路线）。

def decompose_milestones(
    recipe: dict[str, Any],
    *,
    f0_tolerance: float = 0.15,
    fine_epsilon: float = 0.2,
) -> list[dict[str, Any]]:
    """由易到难 milestone 分解（v1.2 增强，确定性内核，无 LLM）。

    粗网格→细网格、单点→战役；每个里程碑带显式验收判据（逐里程碑验收）。
    id 固定 M1..M5、难度严格递增；self_verify_loop 按此顺序推进并逐项标注
    pending/running/passed/failed/skipped。返回结构是纯数据（可被 proposer
    以 typed call 覆写，但字段形状必须一致）。
    """
    return [
        {"id": "M1", "name": "名义点粗网格单点快验证", "difficulty": "easy",
         "acceptance": "单次评估产出非空 metrics，基线 cost 记录在案",
         "status": "pending", "detail": None},
        {"id": "M2", "name": "频率尺度修正（粗网格）", "difficulty": "easy",
         "acceptance": f"|S11| 谷位进入带中心 ±{f0_tolerance:.0%}"
                       "（无长度类参数或谷位不可得时跳过）",
         "status": "pending", "detail": None},
        {"id": "M3", "name": "指标达标（粗网格）", "difficulty": "medium",
         "acceptance": "objectives 零违约（SpecEvaluator cost=0）",
         "status": "pending", "detail": None},
        {"id": "M4", "name": "细网格复验（跨网格一致性）", "difficulty": "hard",
         "acceptance": f"细网格 cost ≤ 粗网格 best×(1+{fine_epsilon:g})"
                       "（跨保真一致性锚）",
         "status": "pending", "detail": None},
        {"id": "M5", "name": "沙箱草稿+三层 Gate 提案（移交战役）", "difficulty": "hard",
         "acceptance": "final_params 落沙箱草稿，人审通道（三层 Gate）就绪",
         "status": "pending", "detail": None},
    ]


def _band_center_ghz(objectives: list[dict[str, Any]]) -> float | None:
    """首个带限 objective 的带中心（与 critique_point 同口径）。"""
    for o in objectives:
        band = o.get("band") if isinstance(o, dict) else None
        if isinstance(band, (list, tuple)) and len(band) == 2:
            return (float(band[0]) + float(band[1])) / 2
    return None


def _clip_to_bounds(params: dict[str, Any],
                    bounds: dict[str, tuple[float, float]]) -> dict[str, float]:
    """proposer 参数限界收敛（typed call 的假设值也要过确定性守卫）。"""
    out: dict[str, float] = {}
    for k, v in params.items():
        if k not in bounds:
            continue  # 声明空间之外的参数不进环
        fv = max(float(bounds[k][0]), min(float(bounds[k][1]), float(v)))
        out[k] = fv
    return out


def _default_proposal(recipe: dict[str, Any],
                      bounds: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """确定性缺省 proposer：名义点（配方值优先，界中心兜底）。"""
    current = {k: (float(lo) + float(hi)) / 2 for k, (lo, hi) in bounds.items()}
    for k in current:
        pv = (recipe.get("params") or {}).get(k)
        if isinstance(pv, dict) and isinstance(pv.get("value"), (int, float)):
            current[k] = float(pv["value"])
    return {"params": current, "milestones": None,
            "note": "确定性名义点（配方值优先，界中心兜底）"}


def self_verify_loop(
    recipe_path: str | Path,
    *,
    sampler_fn: Callable[[dict[str, float]], dict[str, Any]] | None = None,
    fine_sampler_fn: Callable[[dict[str, float]], dict[str, Any]] | None = None,
    proposer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    board: Any | None = True,
    budget_coarse: int = 3,
    mesh_coarse_mm: float = 1.0,
    mesh_fine_mm: float = 0.5,
    f0_tolerance: float = 0.15,
    rl_floor_db: float = -8.0,
    max_step_pct: float = 0.2,
    probes_per_round: int = 4,
    fine_epsilon: float = 0.2,
    pause_timeout_s: float = 3600.0,
    pause_poll_s: float = 0.05,
    sandbox: bool = True,
) -> dict[str, Any]:
    """自验证环（WP3.5 收口）：propose→verify→fix 闭环，无人在环、HFSS 仅终验。

    - propose：proposer(state) typed call（LLM/优化器只出假设参数起点与可选
      milestone 分解；缺省为确定性名义点）。参数一律限界收敛后才进环。
    - verify：确定性内核——sampler（引擎基准）+ SpecEvaluator（objectives）
      + critique_point 的谷位/带中心闭式对照。
    - fix：critique_point 的 typed fixes（限幅限步长+坐标探测），同 autotune_loop。
    - milestone：decompose_milestones 由易到难推进，逐项验收
      （passed/failed/skipped 如实标注，FAIL 不凑绿）。
    - board：LoopBoard 执行看板（默认自建；CLI 批处理写、UI 读+发暂停/接管令，
      环只在步骤边界协作式响应）。

    verdict：PASS=全部非 skipped 里程碑通过；FAIL=如实；TAKEN_OVER=人接管
    （best-so-far 仍落沙箱草稿供人续跑）。产物写 runs/<run_id>/autotune.json
    （同名产物：dataset_service/rationale_memory 等既有消费者直接复用）。
    """
    import yaml

    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, write_meta
    from rfauto.service.loop_board import LoopBoard, create_board

    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe = yaml.safe_load(f) or {}
    opt = recipe.get("optimization") or {}
    bounds = {k: (float(v["low"]), float(v["high"]))
              for k, v in (opt.get("params") or {}).items()}
    objectives = list(recipe.get("objectives", []))
    if not objectives:
        return {"ok": False, "errors": ["配方无 objectives，无从评判"]}
    freq_range = tuple((recipe.get("setup") or {}).get("freq_range_ghz", (1.0, 5.0)))
    band_center = _band_center_ghz(objectives)

    if sampler_fn is None:
        sampler_fn = _make_openems_sampler(
            str(recipe.get("model", "")), freq_range, objectives,
            mesh_resolution_mm=mesh_coarse_mm,
            work_root=Path("runs") / f"autotune_work_{generate_run_id()}")
        if mesh_fine_mm > 0 and mesh_fine_mm != mesh_coarse_mm:
            # 真机缺省路径：粗→细两把采样器（M4 跨网格一致性锚才成立）
            fine_sampler_fn = _make_openems_sampler(
                str(recipe.get("model", "")), freq_range, objectives,
                mesh_resolution_mm=mesh_fine_mm,
                work_root=Path("runs") / f"autotune_work_{generate_run_id()}")
    want_fine = fine_sampler_fn is not None or (
        mesh_fine_mm > 0 and mesh_fine_mm != mesh_coarse_mm)
    eff_fine_sampler = fine_sampler_fn or sampler_fn

    def cost_of(metrics: dict[str, float]) -> float:
        return SpecEvaluator.evaluate_objectives(
            metrics, [Objective(**o) for o in objectives])

    # ── milestone 分解（propose 可覆写，形状必须一致）────────────────────
    milestones = decompose_milestones(
        recipe, f0_tolerance=f0_tolerance, fine_epsilon=fine_epsilon)
    m_by_id = {m["id"]: m for m in milestones}
    proposal_note = None

    # ── 执行看板（缺省自建；None/False 关闭）─────────────────────────────
    if isinstance(board, LoopBoard):
        brd: LoopBoard | None = board
    elif board:
        brd = create_board(str(path), milestones)
    else:
        brd = None
    if brd is not None:
        brd.start(str(path), milestones, meta={
            "budget_coarse": budget_coarse, "mesh_coarse_mm": mesh_coarse_mm,
            "mesh_fine_mm": mesh_fine_mm, "loop": "self_verify"})

    # ── propose ──────────────────────────────────────────────────────────
    t0 = time.time()
    state = {"recipe": str(path), "bounds": dict(bounds),
             "objectives": objectives, "freq_range_ghz": freq_range}
    if brd is not None:
        brd.step("propose", detail="typed call（LLM/优化器假设起点）")
    if proposer is not None:
        raw = proposer(state) or {}
        params_raw = raw.get("params") or {}
        current = _clip_to_bounds(params_raw, bounds) or _default_proposal(
            recipe, bounds)["params"]
        proposal_note = str(raw.get("note") or "外部 proposer typed call")
        ms_raw = raw.get("milestones")
        if (isinstance(ms_raw, list) and ms_raw
                and all(isinstance(m, dict) and m.get("id") and m.get("name")
                        and m.get("acceptance") for m in ms_raw)):
            milestones = [{**m, "status": "pending", "detail": None}
                          for m in ms_raw]
            m_by_id = {m["id"]: m for m in milestones}
            if brd is not None:
                brd.set_milestones(milestones)
    else:
        default = _default_proposal(recipe, bounds)
        current = dict(default["params"])
        proposal_note = default["note"]
    if brd is not None:
        brd.step_done({"params": dict(current), "note": proposal_note})

    # M2 可跑性：无长度类参数 → 如实跳过（验收列口径）
    if not any(_is_length_param(n) for n in bounds):
        m2 = m_by_id.get("M2")
        if m2 is not None:
            m2["status"] = "skipped"
            m2["detail"] = "bounds 内无长度类参数，频率尺度规则不适用"
    if not want_fine:
        m4 = m_by_id.get("M4")
        if m4 is not None:
            m4["status"] = "skipped"
            m4["detail"] = "未启用细网格通道（fine_sampler/mesh_fine 未配）"

    takeover = False
    timeout_notes: list[str] = []
    last_critique_pass = False

    def control_gate() -> str:
        """步骤边界协作式控制：pause 等待、takeover 如实停。返回 go|takeover。"""
        nonlocal takeover
        if brd is None:
            return "go"
        cmd = brd.pending_command()
        if cmd == "resume":
            brd.clear_command()  # 无暂停上下文的 resume：噪声，清掉
            return "go"
        if cmd == "takeover":
            takeover = True
            return "takeover"
        if cmd == "pause":
            outcome = brd.handle_pause(pause_timeout_s, pause_poll_s)
            if outcome == "taken_over":
                takeover = True
                return "takeover"
            if outcome == "timeout":
                timeout_notes.append(
                    f"暂停等待 {pause_timeout_s:g}s 超时无 resume，自动续跑")
            return "go"
        return "go"

    history: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    stop_note: str | None = None
    coarse_ids = ("M1", "M2", "M3")
    known_coarse = [i for i in coarse_ids if i in m_by_id]

    def evaluate_milestones(c: dict[str, Any], valley: float | None,
                            cost: float) -> None:
        m1 = m_by_id.get("M1")
        if m1 is not None and m1["status"] == "pending":
            m1["status"] = "passed"
            m1["detail"] = f"基线 cost={cost:.4g}"
        m2 = m_by_id.get("M2")
        if (m2 is not None and m2["status"] not in ("passed", "skipped")
                and valley is not None and band_center is not None
                and band_center > 0):
            ratio = float(valley) / band_center
            if abs(1 - ratio) <= f0_tolerance:
                m2["status"] = "passed"
                m2["detail"] = f"谷位 {valley:.3f}GHz 在带中心 ±{f0_tolerance:.0%}"
            else:
                m2["status"] = "running"
                m2["detail"] = f"谷位 {valley:.3f}GHz 偏 {1 - ratio:+.0%}"
        m3 = m_by_id.get("M3")
        if m3 is not None and m3["status"] != "passed":
            m3["status"] = "passed" if not c["violations"] else "running"
            m3["detail"] = ("零违约" if not c["violations"]
                            else f"违约 {sorted(c['violations'])}")

    def coarse_done(c: dict[str, Any]) -> bool:
        if not known_coarse:
            # proposer 全自定义里程碑：阶段出口=确定性评判 PASS（验收语义
            # 无法被环内建规则解释时，唯一确定性裁判是 critique 本身）
            return c["verdict"] == "PASS"
        return all(m_by_id[i]["status"] in ("passed", "skipped")
                   for i in known_coarse)

    # ── verify→fix 粗网格主环 ────────────────────────────────────────────
    for rnd in range(1, max(1, int(budget_coarse)) + 1):
        if brd is not None:
            brd.step("verify", milestone="M1", detail=f"round {rnd}",
                     params=dict(current))
        if control_gate() == "takeover":
            stop_note = "人工接管"
            break
        try:
            res = sampler_fn(current)
        except Exception as exc:
            history.append({"round": rnd, "phase": "coarse",
                            "params": dict(current), "error": str(exc)})
            if brd is not None:
                brd.step_done({"error": str(exc)})
            stop_note = f"采样失败: {exc}"
            break
        metrics = res["metrics"]
        valley = res.get("valley_ghz")
        cost = cost_of(metrics)
        c = critique_point(metrics, objectives, valley_ghz=valley,
                           bounds=bounds, current_params=current,
                           f0_tolerance=f0_tolerance, rl_floor_db=rl_floor_db,
                           max_step_pct=max_step_pct)
        history.append({"round": rnd, "phase": "coarse", "params": dict(current),
                        "metrics": metrics, "cost": cost,
                        "verdict": c["verdict"], "issues": c["issues"],
                        "fixes": c["fixes"]})
        if brd is not None:
            brd.step_done({"cost": cost, "verdict": c["verdict"]})
        if best is None or cost < best["cost"]:
            best = {"round": rnd, "phase": "coarse", "params": dict(current),
                    "metrics": metrics, "cost": cost, "valley_ghz": valley}
            if brd is not None:
                brd.set_best(best)
        evaluate_milestones(c, valley, cost)
        last_critique_pass = c["verdict"] == "PASS"
        if brd is not None:
            for mid in coarse_ids:
                if mid in m_by_id:
                    brd.milestone(mid, m_by_id[mid]["status"],
                                  m_by_id[mid]["detail"])
        if coarse_done(c):
            break

        # fix：应用 typed fixes（限界）+ 宽度类坐标探测（同 autotune_loop）
        applied = _apply_fixes(current, c["fixes"], bounds)
        n_probes = 0
        for f in c["fixes"]:
            if f.get("op") != "coord_probe" or n_probes >= probes_per_round:
                continue
            for pname in f["param"]:
                if n_probes >= probes_per_round:
                    break
                probe = _coord_probe(pname, applied, bounds,
                                     float(f["value"]), sampler_fn, cost_of)
                n_probes += 1
                if probe is not None and probe[1] < cost:
                    applied, cost = probe[0], probe[1]
                    if best is None or cost < best["cost"]:
                        best = {"round": rnd, "phase": "coarse",
                                "params": dict(applied), "metrics": None,
                                "cost": cost, "valley_ghz": None}
                        if brd is not None:
                            brd.set_best(best)
        if applied == current:
            stop_note = "无确定性改进方向（fix 空/越界无变化）"
            break
        current = applied

    if stop_note and not takeover:
        for mid in coarse_ids:  # 未达标里程碑如实 failed（FAIL 不凑绿）
            m = m_by_id.get(mid)
            if m is not None and m["status"] not in ("passed", "skipped"):
                m["status"] = "failed"
                m["detail"] = f"{m['detail'] or ''}（{stop_note}）".strip()
    if brd is not None:
        for mid in coarse_ids:
            if mid in m_by_id:
                brd.milestone(mid, m_by_id[mid]["status"], m_by_id[mid]["detail"])
    # proposer 自定义里程碑（非 M*）：环内建验收规则只认 M*；自定义项的
    # 确定性裁判 = 粗网格阶段末次 critique verdict
    for m in milestones:
        if m["id"] not in ("M1", "M2", "M3", "M4", "M5") and m["status"] == "pending":
            m["status"] = "passed" if last_critique_pass else "failed"
            m["detail"] = (m["detail"] or "") + (
                "（末次 critique PASS）" if last_critique_pass
                else "（末次 critique 未 PASS）")

    # ── M4 细网格复验（跨网格一致性锚）───────────────────────────────────
    m4 = m_by_id.get("M4")
    if (m4 is not None and m4["status"] == "pending" and best is not None
            and best.get("metrics") is not None):
        if brd is not None:
            brd.step("verify_fine", milestone="M4", detail="细网格复验 best 点",
                     params=dict(best["params"]))
        if control_gate() != "takeover":
            try:
                res_f = eff_fine_sampler(dict(best["params"]))
                fine_cost = cost_of(res_f["metrics"])
                ok = fine_cost <= best["cost"] * (1 + fine_epsilon) + 1e-9
                m4["status"] = "passed" if ok else "failed"
                m4["detail"] = (f"fine cost {fine_cost:.4g} vs coarse best "
                                f"{best['cost']:.4g}（ε={fine_epsilon:g}）")
                history.append({"round": len(history) + 1, "phase": "fine",
                                "params": dict(best["params"]),
                                "metrics": res_f["metrics"],
                                "cost": fine_cost})
                if fine_cost < best["cost"]:
                    best = {"round": len(history), "phase": "fine",
                            "params": dict(best["params"]),
                            "metrics": res_f["metrics"], "cost": fine_cost,
                            "valley_ghz": res_f.get("valley_ghz")}
                    if brd is not None:
                        brd.set_best(best)
            except Exception as exc:
                m4["status"] = "failed"
                m4["detail"] = f"细网格复验失败: {exc}"
            if brd is not None:
                brd.milestone("M4", m4["status"], m4["detail"])
                brd.step_done({"milestone": "M4", "status": m4["status"]})

    # ── M5 沙箱草稿（接管时同样执行：人需要草稿续跑）────────────────────
    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    final_params = dict(best["params"]) if best else dict(current)
    elapsed = time.time() - t0
    result: dict[str, Any] = {
        "ok": True, "run_id": run_id, "run_dir": str(run_dir),
        "board_id": brd.board_id if brd is not None else None,
        "verdict": "PENDING", "loop": "self_verify",
        "proposer_note": proposal_note, "budget_coarse": budget_coarse,
        "rounds_used": len(history), "best": best,
        "final_params": final_params, "history": history,
        "milestones": milestones, "sandbox": None,
        "elapsed_s": round(elapsed, 1),
    }
    (run_dir / "autotune.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")

    m5 = m_by_id.get("M5")
    sandbox_result: dict[str, Any] | None = None
    if m5 is not None and sandbox and best is not None:
        if brd is not None:
            brd.step("sandbox", milestone="M5",
                     detail="final_params → 沙箱草稿（三层 Gate 通道）")
        sandbox_result = autotune_to_sandbox(path, run_id)
        m5["status"] = "passed" if sandbox_result.get("ok") else "failed"
        m5["detail"] = (str(sandbox_result.get("draft"))
                        if sandbox_result.get("ok")
                        else str(sandbox_result.get("errors")))
        result["sandbox"] = sandbox_result
        if brd is not None:
            brd.milestone("M5", m5["status"], m5["detail"])
            brd.step_done({"draft": sandbox_result.get("draft")})
    elif m5 is not None:
        m5["status"] = "skipped"
        m5["detail"] = "sandbox 关闭或无 best 点"

    if takeover:
        verdict = "TAKEN_OVER"
    else:
        verdict = ("PASS" if all(m["status"] in ("passed", "skipped")
                                 for m in milestones) else "FAIL")
    result["verdict"] = verdict
    if timeout_notes:
        result["pause_notes"] = timeout_notes
    (run_dir / "autotune.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    write_meta(run_dir, {
        "run_id": run_id, "model": str(recipe.get("model", "")),
        "status": "done", "adapter": "autotune:self_verify",
        "algorithm": "self_verify_loop",
        "metrics": {"verdict": verdict, "rounds": len(history),
                    "best_cost": best["cost"] if best else None,
                    "board_id": result["board_id"]}})
    record_run(record={
        "run_id": run_id, "model": str(recipe.get("model", "")),
        "adapter": "autotune:self_verify", "status": "done",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": {"verdict": verdict}})
    if brd is not None:
        for m in milestones:  # 终态前全量同步（含 proposer 自定义项）
            brd.milestone(m["id"], m["status"], m["detail"])
        if best is not None:
            board_summary = (f"verdict={verdict} · best_cost={best['cost']:.4g}")
        else:
            board_summary = f"verdict={verdict} · 无有效评估点"
        brd.finish(
            "taken_over" if takeover else ("done" if verdict == "PASS" else "failed"),
            summary=board_summary)
    return result
