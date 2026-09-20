"""E11 "同族真跑次数再降 ≥30%" 验收战役（fake 通道验证面）。

对照设计：同族 recipe（默认仓内 recipes/wilkinson_pd_v1.yaml 的 fake 通道）
在相同预算 budget 下跑 冷启动 vs warm-start（数据集源=runs/ 已注册数据集，
或当场造历史 run 后 materialize）各 N 次（N≥3 个优化种子），统计
"达到目标 cost 的真评估次数"（time-to-target，配对）并按
"平均缩减 ≥30% → PASS" 判定；不足时给出差距数字与逐种子明细（如实，不凑）。

方法学要点（诚实性设计）：
- **种子机制**：run_optimization 硬编码 TPESampler(seed=42)（无 seed 参数，
  产品面局限→followUps）。本战役在**战役进程内**用 _seeded_tpe_sampler
  上下文按种子重挂 TPESampler 子类（用后还原）——这是战役编排层的实验
  变量注入，不改 service/optimization 任何文件。
- **真评估口径**：进程级设 RFAUTO_CACHE=off——warm 臂注入的历史先验点
  一律真评估（缓存命中会把历史点白送成"0 次真跑"，虚增 warm 优势）。
- **配对判据**（target 偏置修复）：target **先验固定**——缺省取各配对
  **冷臂末代累计 best**（warm-start 对照的先验基线），或调用方显式传入
  judge_campaign(target=...)；trials_to_target = 累计 best 首次 ≤
  target+ε 的 trial 序数。缩减率只统计双臂都达同一 target 的种子；任一
  臂未达标记 censored（不进均值），censored 种子数在 n_censored/verdict
  透出。旧口径 min(双臂末代 best) 是**事后 target**——末代质量优势会被
  合成"次数缩减"（warm 每个前缀都不优于 cold 也能 PASS），已废弃。
- **通道口径**：campaign_verdict 带顶层 ``channel``
  字段（=adapter_name：fake|openems|hfss…），meta 记 cold/warm 双臂通道
  与 adapter——fake 通道数字不得填"真跑次数"判据，判据引用必须带通道。
- **历史集上界剔除**：warm 历史集构造
  （build_history_samples，纯函数）剔除全部 ``cost ≤ target+ε`` 的
  上界/目标点（target 与判据同款：先验固定或逐配对冷臂末代 best）——
  历史集含最优点时 warm 首 trial 即命中（e11c_main 实证 95.5% 为构造
  上界），注入先验不再可能平推达标；构造集为空则该种子如实跳过。
- **隔离**（#144）：默认在 runs/e11_warm_campaign/<tag>/ 沙箱 cwd 内跑，
  不污染真实 runs/；study 名带 tag 防复跑串 study。
- 判定逻辑（cumulative_best / trials_to_target / judge_campaign）是纯函数，
  由 tests/unit/test_e11_campaign_logic.py 合成数据钉死——零真机零长跑。

用法：
  .venv\\Scripts\\python.exe scripts/e11_warm_start_campaign.py
  .venv\\Scripts\\python.exe scripts/e11_warm_start_campaign.py \\
      --seeds 11,22,33 --budget 30 --history-seeds 101,102 --history-budget 30
  # 复用已注册数据集（跳过造史）：
  .venv\\Scripts\\python.exe scripts/e11_warm_start_campaign.py --dataset <name>

退出码：0=PASS；1=未达标（FAIL）；2=战役执行错误。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

__all__ = [
    "build_campaign_recipe",
    "build_history_samples",
    "cumulative_best",
    "judge_campaign",
    "main",
    "run_campaign",
    "study_trajectory",
    "trials_to_target",
]


# ─── 纯判定逻辑（零重依赖，单测钉死面） ───────────────────────────────────────

def cumulative_best(costs: list[float | None]) -> list[float]:
    """逐 trial 累计最优（running min；None=失败 trial 跳过不更新）。"""
    out: list[float] = []
    best = float("inf")
    for c in costs:
        if c is None:
            out.append(best)
            continue
        best = min(best, float(c))
        out.append(best)
    return out


def trials_to_target(
    costs: list[float | None],
    target: float,
    budget: int,
    epsilon: float = 1e-12,
) -> int:
    """达到 target 的真评估次数（1-based trial 序数；未达标按整预算=censored）。

    target 取"该配对最终达到的水平"时的标准 time-to-target 口径：更早
    达标 = 更少真评估。空轨迹/未达标一律返回 budget（保守，不虚构缩减）。
    """
    best = float("inf")
    for i, c in enumerate(costs, start=1):
        if c is None:
            continue
        best = min(best, float(c))
        if best <= float(target) + float(epsilon):
            return i
    return max(int(budget), 1)


def judge_campaign(
    pairs: dict[str, dict[str, list[float | None]]],
    budget: int,
    threshold_pct: float = 30.0,
    epsilon: float = 1e-12,
    target: float | None = None,
) -> dict[str, Any]:
    """战役判定（纯函数）：配对 time-to-target → 平均缩减率 ≥ 阈值判 PASS。

    target 口径（target 偏置修复）：**先验固定**——调用方显式传入
    ``target`` 时全战役统一用它；缺省逐配对取**冷臂末代累计 best**
    （warm-start 对照的先验基线）。旧口径 min(双臂末代 best) 是事后
    target：末代质量优势会被合成"次数缩减"（warm 每个前缀都不优于
    cold 也能 PASS），已废弃。

    缩减率只统计双臂都达同一 target 的种子；任一臂未达标（censored）
    的种子**不进均值**，其 censored 臂与种子数在 per_seed/n_censored/
    verdict 透出（trials_to_target 未达标仍按整预算保守计）。

    Args:
        pairs: ``{seed: {"cold": [cost...], "warm": [cost...]}}``——各臂
            按 trial 序排列的单点 cost 轨迹（失败 trial 用 None 占位）。
        budget: 每臂真评估预算（=轨迹长度上限）。
        threshold_pct: PASS 阈值（平均缩减率 %，默认 30）。
        epsilon: 达标判定的相对容差尾数（绝对值，默认 1e-12）。
        target: 先验固定 target；None=逐配对取冷臂末代 best。

    Returns:
        dict：per_seed 明细（target_cost/cold_trials/warm_trials/
        reduction_pct（censored 种子为 None）/reached 标志/censored/
        censored_arm）、n_seeds（进均值种子数）、n_censored、
        mean/median_reduction_pct、threshold_pct、pass、verdict、errors。
    """
    per_seed: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    reductions: list[float] = []
    n_censored = 0
    for seed, arms in pairs.items():
        cold = list(arms.get("cold") or [])
        warm = list(arms.get("warm") or [])
        if not cold or not warm:
            errors.append(f"seed={seed}: 轨迹为空（cold={len(cold)}/warm={len(warm)}），跳过")
            continue
        cold_curve = cumulative_best(cold)
        warm_curve = cumulative_best(warm)
        if target is not None:
            tgt = float(target)
        else:
            cold_final = cold_curve[-1]
            if cold_final is None or cold_final == float("inf"):
                errors.append(f"seed={seed}: 冷臂无有效 cost，无法定先验 target，跳过")
                continue
            tgt = cold_final
        cold_t = trials_to_target(cold, tgt, budget, epsilon)
        warm_t = trials_to_target(warm, tgt, budget, epsilon)
        tol = float(tgt) + float(epsilon)
        cold_reached = bool(cold_curve) and cold_curve[-1] <= tol
        warm_reached = bool(warm_curve) and warm_curve[-1] <= tol
        row: dict[str, Any] = {
            "target_cost": tgt,
            "cold_trials_to_target": cold_t,
            "warm_trials_to_target": warm_t,
            "cold_reached": cold_reached,
            "warm_reached": warm_reached,
            "cold_final_best": cold_curve[-1],
            "warm_final_best": warm_curve[-1],
        }
        if cold_reached and warm_reached:
            reduction = (cold_t - warm_t) / cold_t * 100.0
            row["reduction_pct"] = round(reduction, 2)
            row["censored"] = False
            reductions.append(reduction)
        else:
            if not cold_reached and not warm_reached:
                row["censored_arm"] = "both"
            elif not cold_reached:
                row["censored_arm"] = "cold"
            else:
                row["censored_arm"] = "warm"
            row["reduction_pct"] = None
            row["censored"] = True
            n_censored += 1
        per_seed[str(seed)] = row

    n = len(reductions)
    mean_red = statistics.fmean(reductions) if reductions else 0.0
    median_red = statistics.median(reductions) if reductions else 0.0
    passed = n > 0 and mean_red >= float(threshold_pct)
    censored_note = (
        f"；另有 {n_censored} 种子 censored（未达 target，未计入）"
        if n_censored else "")
    if n == 0 and n_censored == 0:
        verdict = "FAIL: 无有效配对种子，无法判定"
    elif n == 0:
        verdict = f"FAIL: {n_censored} 种子全部 censored（未达先验 target），无可统计缩减样本"
    elif passed:
        verdict = (
            f"PASS: {n} 种子平均真评估次数缩减 {mean_red:.1f}% ≥ {threshold_pct:.0f}%"
            f"{censored_note}"
        )
    else:
        verdict = (
            f"FAIL: {n} 种子平均真评估次数缩减 {mean_red:.1f}% < {threshold_pct:.0f}%"
            f"（差 {threshold_pct - mean_red:.1f} 个百分点；中位数 {median_red:.1f}%）"
            f"{censored_note}"
        )
    return {
        "pass": passed,
        "verdict": verdict,
        "n_seeds": n,
        "n_censored": n_censored,
        "mean_reduction_pct": round(mean_red, 2),
        "median_reduction_pct": round(median_red, 2),
        "threshold_pct": float(threshold_pct),
        "budget": int(budget),
        "per_seed": per_seed,
        "errors": errors,
    }


def build_history_samples(
    samples: list[dict[str, Any]],
    target: float,
    epsilon: float = 1e-12,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """构造 warm 历史集：剔除会让判据虚高的上界/目标点（纯函数，单测钉死）。

    设计动机：历史集本身
    含最优点（cost ≤ target）时 warm 首 trial 即命中 target，"次数缩减"
    是**构造上界**而非 warm-start 方法红利（e11c_main 实证 95.5% 即此）。
    本函数按与判据同款的 target 语义（先验固定或逐配对冷臂末代 best），
    从全量历史样本中剔除全部 ``cost ≤ target + ε`` 的样本——注入先验
    不再可能平推达标，缩减率只能量化真实的方法红利。

    cost 非有限数值（bool/NaN/Inf/缺失）的样本不参与剔除判定、原样保留：
    物化/喂料面（dataset_service/warm_start_data）已在源头拦截此类坏行，
    纯函数不静默丢数据；removed_indices 让"全量集 − 构造集 = 恰为上界点"
    可断言、可追溯。

    Args:
        samples: 全量历史样本（collect_warm_start_samples 的输出形态，
            每点含 params/cost/run_id/point_index）。
        target: 剔除阈值（判据同款 target）：cost ≤ target+ε 的样本剔除。
        epsilon: 达标判定的相对容差尾数（与 judge_campaign 同默认）。

    Returns:
        ``(kept_samples, stats)``；stats 带 n_total/n_removed/n_kept/
        removal_threshold/removed_indices（战役 verdict meta 透出）。
    """
    tol = float(target) + float(epsilon)
    kept: list[dict[str, Any]] = []
    removed_idx: list[int] = []
    for i, s in enumerate(samples):
        c = s.get("cost") if isinstance(s, dict) else None
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            kept.append(s)  # 非数值 cost：不参与判定，原样保留
            continue
        cf = float(c)
        if math.isnan(cf) or math.isinf(cf):
            kept.append(s)
            continue
        if cf <= tol:
            removed_idx.append(i)
            continue
        kept.append(s)
    stats = {
        "n_total": len(samples),
        "n_removed": len(removed_idx),
        "n_kept": len(kept),
        "removal_threshold": float(target),
        "epsilon": float(epsilon),
        "removed_indices": removed_idx,
    }
    return kept, stats


# ─── 战役编排（IO/真跑面） ────────────────────────────────────────────────────

def build_campaign_recipe(
    repo_recipe: Path,
    workdir: Path,
    budget: int,
    points: int = 11,
) -> Path:
    """把仓内 recipe 裁成战役版（降 sweep 点数提速 + 按预算改 limits），写 workdir。"""
    import yaml

    data = yaml.safe_load(Path(repo_recipe).read_text(encoding="utf-8"))
    setup = data.get("setup") or {}
    setup["points"] = int(points)
    data["setup"] = setup
    data["limits"] = {"max_trials": int(budget), "max_wall_hours": 2}
    dest = workdir / "recipe.yaml"
    dest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return dest


@contextlib.contextmanager
def _seeded_tpe_sampler(seed: int):
    """战役进程内按种子重挂 optuna TPESampler（用后还原；产品面 seed 硬编码 42）。"""
    import optuna

    original = optuna.samplers.TPESampler

    class _SeededTPE(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["seed"] = int(seed)
            super().__init__(*args, **kwargs)

    optuna.samplers.TPESampler = _SeededTPE  # type: ignore[misc]
    try:
        yield
    finally:
        optuna.samplers.TPESampler = original  # type: ignore[misc]


def study_trajectory(study_name: str, storage_url: str | None = None) -> list[float | None]:
    """按 trial 序回读 study 的单点 cost 轨迹（COMPLETE 值；无值 trial 以 None 占位）。"""
    import optuna

    from rfauto.optimization.optimizer import get_storage_path

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.load_study(
        study_name=study_name, storage=storage_url or get_storage_path())
    trials = sorted(study.get_trials(deepcopy=False), key=lambda t: t.number)
    return [float(t.value) if t.value is not None else None for t in trials]


def run_campaign(
    workdir: Path,
    repo_recipe: Path,
    seeds: list[int],
    budget: int = 30,
    history_seeds: list[int] | None = None,
    history_budget: int = 30,
    dataset_name: str | None = None,
    threshold_pct: float = 30.0,
    tag: str | None = None,
    points: int = 11,
    adapter_name: str = "fake",
    target: float | None = None,
) -> dict[str, Any]:
    """跑整场战役（真评估走 adapter_name 通道，默认 fake），返回判定 JSON。

    通道与历史上界剔除：verdict 顶层带 ``channel``=adapter_name，
    meta 记 cold/warm 双臂通道（配对来源可追溯）；warm 臂注入的历史先验经
    build_history_samples 剔除全部 cost ≤ target+ε 的上界/目标点（target
    与判据同款：显式传入或逐配对冷臂末代 best），剔除统计在
    meta.history_filter 透出；某种子剔除后历史集为空 → 该种子如实跳过
    （warm 臂无法诚实构建，不静默降级冷启动）。
    """
    from rfauto.optimization.optimizer import run_optimization
    from rfauto.service.dataset_service import materialize_dataset
    from rfauto.service.warm_start_data import collect_warm_start_samples

    os.environ["RFAUTO_CACHE"] = "off"  # 真评估口径：历史点也真跑，不吃缓存
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    tag = tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    history_seeds = history_seeds or [s * 7 + 3 for s in seeds]

    prev_cwd = os.getcwd()
    os.chdir(workdir)
    try:
        recipe_path = build_campaign_recipe(repo_recipe, workdir, budget, points)
        errors: list[str] = []

        # ─── 数据集源：已注册数据集，或当场造史（独立种子的探索 run） ───
        hist_run_ids: list[str] = []
        if dataset_name is None:
            dataset_name = "e11_history"
            for hs in history_seeds:
                with _seeded_tpe_sampler(hs):
                    r = run_optimization(
                        str(recipe_path), adapter_name=adapter_name,
                        max_trials=history_budget,
                        study_name=f"e11_{tag}_hist_s{hs}",
                        adapter_kwargs={"seed": hs})
                if not r.get("ok"):
                    errors.append(f"造史 run s{hs} 失败: {r.get('errors')}")
                    continue
                hist_run_ids.append(str(r["run_id"]))
            mat = materialize_dataset(run_ids=hist_run_ids or None, name=dataset_name)
            if not mat.get("ok"):
                return {"pass": False, "channel": adapter_name,
                        "verdict": "战役执行错误：数据集物化失败",
                        "errors": errors + list(mat.get("errors") or [])}
            if mat.get("skipped_runs") or mat.get("unhealthy_runs"):
                errors.append(
                    f"物化跳过 run: skipped={mat.get('skipped_runs')} "
                    f"unhealthy={mat.get('unhealthy_runs')}")

        # ─── 全量历史样本（一次收集）；构造集按种子剔除上界点后注入 ───
        coll = collect_warm_start_samples(dataset_name)
        if not coll.get("ok"):
            return {"pass": False, "channel": adapter_name,
                    "verdict": "战役执行错误：历史数据集查询失败",
                    "errors": errors + list(coll.get("errors") or ["历史数据集查询失败"])}
        history_samples = list(coll.get("samples") or [])
        if not history_samples:
            return {"pass": False, "channel": adapter_name,
                    "verdict": "战役执行错误：历史数据集无可用样本",
                    "errors": errors}
        history_filter: dict[str, Any] = {
            "rule": "build_history_samples: cost ≤ target+ε 剔除（判据同款 target）",
            "n_full_samples": len(history_samples),
            "target": target,
            "per_seed": {},
        }

        # ─── 配对双臂：同预算、同种子（TPE 注入），冷 vs warm ─────────────
        pairs: dict[str, dict[str, list[float | None]]] = {}
        warm_start_n: dict[str, int] = {}
        for s in seeds:
            with _seeded_tpe_sampler(s):
                cold = run_optimization(
                    str(recipe_path), adapter_name=adapter_name, max_trials=budget,
                    study_name=f"e11_{tag}_cold_s{s}", adapter_kwargs={"seed": s})
                if not cold.get("ok"):
                    errors.append(f"冷臂 s{s} 失败: {cold.get('errors')}")
                    continue
                cold_traj = study_trajectory(str(cold["study_name"]))
                # 上界剔除阈值 = 判据同款 target（先验固定或冷臂末代 best）
                cold_curve = cumulative_best(cold_traj)
                if target is not None:
                    tgt: float | None = float(target)
                else:
                    tgt = cold_curve[-1] if cold_curve else None
                if tgt is None or tgt == float("inf"):
                    errors.append(f"seed={s}: 冷臂无有效 cost，无法定上界剔除阈值，跳过")
                    continue
                warm_priors, hstats = build_history_samples(history_samples, tgt)
                history_filter["per_seed"][str(s)] = hstats
                if not warm_priors:
                    errors.append(
                        f"seed={s}: 剔除上界/目标点（cost ≤ {tgt:.4g}）后历史集为空，"
                        "warm 臂无法诚实构建，跳过")
                    continue
                warm = run_optimization(
                    str(recipe_path), adapter_name=adapter_name, max_trials=budget,
                    study_name=f"e11_{tag}_warm_s{s}", adapter_kwargs={"seed": s},
                    warm_start=warm_priors)
            if not warm.get("ok"):
                errors.append(f"热臂 s{s} 失败: {warm.get('errors')}")
                continue
            warm_start_n[str(s)] = int(warm.get("warm_start_n") or 0)
            pairs[str(s)] = {
                "cold": cold_traj,
                "warm": study_trajectory(str(warm["study_name"])),
            }

        verdict = judge_campaign(pairs, budget, threshold_pct, target=target)
        verdict["channel"] = adapter_name
        verdict["meta"] = {
            "tag": tag,
            "channel": adapter_name,
            "channels": {"cold": adapter_name, "warm": adapter_name},
            "seeds": list(seeds),
            "budget": int(budget),
            "target": target,
            "history_seeds": list(history_seeds),
            "history_budget": int(history_budget),
            "dataset": str(dataset_name),
            "recipe": str(Path(repo_recipe).resolve()),
            "warm_start_n": warm_start_n,
            "history_filter": history_filter,
            "hist_run_ids": hist_run_ids,
            "campaign_workdir": str(workdir.resolve()),
        }
        verdict.setdefault("errors", []).extend(errors)
        out = workdir / "campaign_verdict.json"
        out.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
        return verdict
    finally:
        os.chdir(prev_cwd)


def main() -> int:
    ap = argparse.ArgumentParser(description="E11 warm-start 同族真跑缩减验收战役（fake 通道）")
    ap.add_argument("--recipe", default=str(REPO_ROOT / "recipes" / "wilkinson_pd_v1.yaml"))
    ap.add_argument("--workdir", default=None,
                    help="沙箱目录（默认 runs/e11_warm_campaign/<tag>）")
    ap.add_argument("--seeds", default="11,22,33", help="配对种子列表（逗号分隔，N≥3）")
    ap.add_argument("--budget", type=int, default=30, help="每臂真评估预算")
    ap.add_argument("--history-seeds", default=None, help="造史 run 种子（默认 7s+3 派生）")
    ap.add_argument("--history-budget", type=int, default=30)
    ap.add_argument("--dataset", default=None, help="复用已注册数据集名（跳过造史）")
    ap.add_argument("--threshold-pct", type=float, default=30.0)
    ap.add_argument("--adapter", default="fake",
                    help="通道/适配器（写入 verdict.channel；真机通道需配真机 recipe 与预算）")
    ap.add_argument("--target", type=float, default=None,
                    help="先验固定 target（缺省=逐配对冷臂末代 best；同时作历史集上界剔除阈值）")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--points", type=int, default=11, help="fake sweep 点数（提速）")
    args = ap.parse_args()

    seeds = [int(x) for x in str(args.seeds).split(",") if x.strip()]
    if len(seeds) < 3:
        print("[e11-campaign] 种子数 N<3，拒跑（验收口径要求 N≥3）")
        return 2
    history_seeds = (
        [int(x) for x in str(args.history_seeds).split(",") if x.strip()]
        if args.history_seeds else None)
    workdir = (
        Path(args.workdir) if args.workdir
        else REPO_ROOT / "runs" / "e11_warm_campaign" / (args.tag or datetime.now().strftime("%Y%m%d_%H%M%S")))

    verdict = run_campaign(
        workdir, Path(args.recipe), seeds, budget=args.budget,
        history_seeds=history_seeds, history_budget=args.history_budget,
        dataset_name=args.dataset, threshold_pct=args.threshold_pct,
        tag=args.tag, points=args.points,
        adapter_name=args.adapter, target=args.target)

    print("=" * 72)
    print(f"[channel] {verdict.get('channel')}")
    print(verdict["verdict"])
    for seed, row in verdict.get("per_seed", {}).items():
        if row.get("censored"):
            print(
                f"  seed={seed}: target={row['target_cost']:.4g}  "
                f"cold={row['cold_trials_to_target']}  "
                f"warm={row['warm_trials_to_target']}  "
                f"censored（{row.get('censored_arm')} 臂未达 target，未计入缩减）")
        else:
            print(
                f"  seed={seed}: target={row['target_cost']:.4g}  "
                f"cold={row['cold_trials_to_target']} 真评估  "
                f"warm={row['warm_trials_to_target']} 真评估  "
                f"缩减 {row['reduction_pct']}%")
    if verdict.get("n_censored"):
        print(f"  censored 种子: {verdict['n_censored']}（未达先验 target，未计入均值）")
    meta = verdict.get("meta") or {}
    if meta.get("warm_start_n"):
        print(f"  warm-start 注入数: {meta['warm_start_n']}")
    hf = meta.get("history_filter") or {}
    if hf.get("n_full_samples") is not None:
        n_removed = sum(
            int((h or {}).get("n_removed") or 0)
            for h in (hf.get("per_seed") or {}).values())
        print(f"  历史上界剔除: 全量 {hf['n_full_samples']} 点，"
              f"剔除 {n_removed} 点（cost ≤ target+ε，防构造上界）")
    for err in verdict.get("errors") or []:
        print(f"  [warn] {err}")
    print(f"  明细: {workdir / 'campaign_verdict.json'}")
    print("=" * 72)
    return 0 if verdict.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
