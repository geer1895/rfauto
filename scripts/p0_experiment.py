#!/usr/bin/env python3
"""Direction 1 P0 Experiment: Multi-fidelity validation (fake先行).

Compares:
  - Baseline: pure fake TPE 30-trial
  - Multi-fidelity: fake coarse 40-trial + fake fine top-k refinement

Quantification (硬门槛):
  - Spearman rank correlation (rho) >= 0.8 between low/high fidelity rankings
  - Top-5 recall >= 80% (>= 3 of low-fidelity top-5 in high-fidelity top-8)
  - Edge sampling sub-experiment: fake extrapolation distortion distribution

Usage:
    python scripts/p0_experiment.py [--recipe RECIPE] [--seed SEED]

Output:
    runs/p0_experiment/p0_results.json
    runs/p0_experiment/p0_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import yaml


def _spearman_rank_corr(x: list[float], y: list[float]) -> float:
    """Compute Spearman rank-order correlation coefficient.

    任一侧为常数数组时排名无信息量（scipy 返回 nan，校准后 fake 成本趋同
    的真实场景）——按惯例返回 0.0。
    """
    import numpy as _np
    from scipy import stats
    if _np.std(x) == 0 or _np.std(y) == 0:
        return 0.0
    rho, _ = stats.spearmanr(x, y)
    return float(rho)


def _top_k_recall(
    low_best: list[dict],
    high_best: list[dict],
    k_low: int = 5,
    k_high: int = 8,
) -> float:
    """Top-k recall: fraction of low-fidelity top-k_low present in high-fidelity top-k_high.

    Match by parameter proximity (L2 norm < threshold).
    """
    if not low_best or not high_best:
        return 0.0
    low_top = low_best[:k_low]
    high_top = high_best[:k_high]
    matched = 0
    for low_pt in low_top:
        low_params = low_pt.get("params", {})
        for high_pt in high_top:
            high_params = high_pt.get("params", {})
            # Check if parameters are close (same trial found by both)
            if low_params == high_params:
                matched += 1
                break
    return matched / max(len(low_top), 1)


def run_single_fidelity(
    recipe_path: str,
    n_trials: int,
    seed: int,
    adapter_name: str = "fake",
) -> dict:
    """Run single-fidelity TPE optimization."""
    from rfauto.optimization.optimizer import run_optimization

    result = run_optimization(
        recipe_path,
        adapter_name=adapter_name,
        max_trials=n_trials,
        study_name=f"p0_single_{seed}",
        sampler="tpe",
    )
    return result


def run_multi_fidelity(
    recipe_path: str,
    n_coarse: int,
    n_fine: int,
    seed: int,
    adapter_name: str = "fake",
) -> dict:
    """Run multi-fidelity: coarse fake + fine fake (simulating HFSS refinement).

    Phase 1: Run n_coarse trials with fake adapter
    Phase 2: Select top-k from Phase 1, run n_fine more trials around them
    """
    import optuna

    from rfauto.optimization.optimizer import run_optimization

    # Phase 1: Coarse screening
    phase1 = run_single_fidelity(recipe_path, n_coarse, seed, adapter_name)
    if not phase1.get("ok"):
        return {"ok": False, "errors": ["Phase 1 failed", *phase1.get("errors", [])]}

    # Load the study to get all trials ranked
    storage = phase1.get("storage", "")
    study_name = phase1.get("study_name", "")
    study = optuna.load_study(study_name=study_name, storage=storage)
    all_trials = [
        t for t in study.get_trials(deepcopy=False)
        if t.state == optuna.trial.TrialState.COMPLETE
    ]
    all_trials.sort(key=lambda t: t.value if t.value is not None else float("inf"))

    # Phase 2: Refine top-k (simulate by running more trials on same study)
    # In real multi-fidelity, this would use HFSS. For P0, we use fake again
    # but the correlation measurement is between Phase 1 rankings and final rankings.
    phase2 = run_optimization(
        recipe_path,
        adapter_name=adapter_name,
        max_trials=n_fine,
        study_name=study_name,  # same study, continues from Phase 1
    )

    # Get final rankings
    final_study = optuna.load_study(study_name=study_name, storage=storage)
    final_trials = [
        t for t in final_study.get_trials(deepcopy=False)
        if t.state == optuna.trial.TrialState.COMPLETE
    ]
    final_trials.sort(key=lambda t: t.value if t.value is not None else float("inf"))

    return {
        "ok": True,
        "phase1": phase1,
        "phase2": phase2,
        "all_trials_ranked": [
            {"params": dict(t.params), "cost": t.value, "trial_number": t.number}
            for t in all_trials
        ],
        "final_trials_ranked": [
            {"params": dict(t.params), "cost": t.value, "trial_number": t.number}
            for t in final_trials
        ],
    }


def edge_sampling_experiment(
    recipe_path: str,
    n_edge_samples: int,
    seed: int,
    adapter_name: str = "fake",
) -> dict:
    """Edge sampling sub-experiment: quantify fake extrapolation distortion.

    Sample at parameter space edges and compare with center predictions.
    """
    from rfauto.adapters.fake_adapter import FakeAdapter
    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.models.registry import get as get_plugin
    from rfauto.optimization.optimizer import extract_param_ranges

    with open(recipe_path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    param_ranges = extract_param_ranges(recipe_data)
    if not param_ranges:
        return {"ok": False, "errors": ["No optimizable parameters"]}

    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    model_name = recipe_data.get("model", "")
    plugin_cls = get_plugin(model_name)
    setup_cfg = recipe_data.get("setup", {})
    freq_range = setup_cfg.get("freq_range_ghz", [1.5, 3.5])
    freq_points = setup_cfg.get("points", 201)

    rng = np.random.default_rng(seed)
    names = sorted(param_ranges.keys())
    results = []

    for _ in range(n_edge_samples):
        # Sample at edges (0-10% or 90-100% of range)
        params = {}
        for name in names:
            spec = param_ranges[name]
            low, high = spec["low"], spec["high"]
            if rng.random() < 0.5:
                # Low edge
                params[name] = low + rng.random() * 0.1 * (high - low)
            else:
                # High edge
                params[name] = high - rng.random() * 0.1 * (high - low)

        adapter = FakeAdapter(
            freq_ghz=(freq_range[0], freq_range[1], freq_points),
            n_ports=plugin_cls.n_ports,
            model_type=plugin_cls.fake_model_type,
        )
        adapter.connect({})
        try:
            plugin = plugin_cls()
            plugin.build(adapter, plugin.params_model(**params))
            report = adapter.solve("main_setup")
            if report.success:
                network = adapter.get_sparams()
                metrics = SpecEvaluator.compute_metrics(network, objectives)
                cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
                results.append({"params": params, "metrics": metrics, "cost": cost, "edge": True})
        except Exception as e:
            results.append({"params": params, "error": str(e), "edge": True})
        finally:
            adapter.close()

    # Also sample center for comparison
    center_results = []
    for _ in range(min(n_edge_samples, 10)):
        params = {}
        for name in names:
            spec = param_ranges[name]
            low, high = spec["low"], spec["high"]
            params[name] = (low + high) / 2  # center

        adapter = FakeAdapter(
            freq_ghz=(freq_range[0], freq_range[1], freq_points),
            n_ports=plugin_cls.n_ports,
            model_type=plugin_cls.fake_model_type,
        )
        adapter.connect({})
        try:
            plugin = plugin_cls()
            plugin.build(adapter, plugin.params_model(**params))
            report = adapter.solve("main_setup")
            if report.success:
                network = adapter.get_sparams()
                metrics = SpecEvaluator.compute_metrics(network, objectives)
                cost = SpecEvaluator.evaluate_objectives(metrics, objectives)
                center_results.append({"params": params, "metrics": metrics, "cost": cost, "edge": False})
        except Exception:
            pass
        finally:
            adapter.close()

    edge_costs = [r["cost"] for r in results if "cost" in r]
    center_costs = [r["cost"] for r in center_results if "cost" in r]

    return {
        "n_edge_samples": len(results),
        "n_center_samples": len(center_results),
        "edge_cost_mean": float(np.mean(edge_costs)) if edge_costs else None,
        "edge_cost_std": float(np.std(edge_costs)) if edge_costs else None,
        "center_cost_mean": float(np.mean(center_costs)) if center_costs else None,
        "center_cost_std": float(np.std(center_costs)) if center_costs else None,
        "edge_results": results[:10],  # first 10 for inspection
        "center_results": center_results,
    }


def cross_fidelity_experiment(
    recipe_path: str,
    n_samples: int,
    seed: int,
    low_adapter: str = "fake",
    high_adapter: str = "fake",
) -> dict:
    """Cross-fidelity ranking experiment: same params, two independently-evaluated models.

    缺口 #4 修复：原 P0 是同一 study/同一 adapter 自比较——Phase 1 排名是
    最终排名的子集，Spearman/top-5 按构造 ≈1.0，硬门槛永不 FAIL（gate 架空）。
    本实验对同一组参数分别用 low/high 两个保真度求值，再算排序一致性：
    - high != low（如 openems/hfss）：真实跨保真 gate；
    - high == low：退回自比较，gate 明确标注 disabled（不产出有效证据）。
    """
    import yaml

    from rfauto.core.objectives import Objective, SpecEvaluator
    from rfauto.models.registry import get as get_plugin
    from rfauto.optimization.optimizer import extract_param_ranges

    with open(recipe_path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    param_ranges = extract_param_ranges(recipe_data)
    if not param_ranges:
        return {"ok": False, "errors": ["No optimizable parameters"]}
    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    plugin_cls = get_plugin(recipe_data.get("model", ""))

    rng = np.random.default_rng(seed)
    names = sorted(param_ranges.keys())
    samples = []
    for _ in range(n_samples):
        samples.append({
            n: float(param_ranges[n]["low"] + rng.random() * (param_ranges[n]["high"] - param_ranges[n]["low"]))
            for n in names
        })

    model_template = {"wilkinson_power_divider": "wilkinson",
                      "patch_antenna": "patch",
                      "branchline_coupler": "branchline"}.get(recipe_data.get("model", ""))
    base_out = Path("runs") / "p0_cross_fidelity"

    def _evaluate_openems(params: dict, idx: int) -> float | None:
        """openEMS 高保真臂：模板子进程链（与 template_deviation_report 同源）。"""
        from rfauto.adapters.em_solver_base import EMSolverConfig
        from rfauto.adapters.openems_solver import OpenEMSSolver

        workdir = base_out / f"ems_{idx}"
        workdir.mkdir(parents=True, exist_ok=True)
        from rfauto.adapters.em_solver_base import resolve_openems_exe

        cfg = EMSolverConfig(
            solver_type="openems",
            exe_path=os.environ.get("RFAUTO_OPENEMS_EXE", resolve_openems_exe()),
            working_dir=str(workdir),
            freq_range_ghz=tuple(recipe_data["setup"]["freq_range_ghz"]),
            mesh_resolution_mm=float(os.environ.get("RFAUTO_OPENEMS_MESH", "0.5")),
        )
        solver = OpenEMSSolver(cfg)
        if not solver.connect():
            raise RuntimeError("openEMS 不可用（exe/绑定）")
        if not solver.build_geometry({"template": model_template, "params": params}):
            raise RuntimeError("openEMS build_geometry 失败")
        result = solver.solve()
        if not result.success:
            raise RuntimeError(f"openEMS solve 失败: {result.message}")
        import skrf
        frequency = skrf.Frequency(float(result.freq_ghz[0]), float(result.freq_ghz[-1]),
                                   len(result.freq_ghz), unit="GHz")
        network = skrf.Network(frequency=frequency, s=result.s_params)
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        return SpecEvaluator.evaluate_objectives(metrics, objectives)

    def _evaluate_fake(params: dict) -> float | None:
        from rfauto.adapters.fake_adapter import FakeAdapter
        plugin_cls_l = plugin_cls
        adapter = FakeAdapter(
            freq_ghz=(*recipe_data["setup"]["freq_range_ghz"],
                      recipe_data["setup"]["points"]),
            n_ports=plugin_cls_l.n_ports,
            model_type=plugin_cls_l.fake_model_type,
        )
        adapter.connect({})
        try:
            plugin = plugin_cls_l()
            plugin.build(adapter, plugin.params_model(**params))
            report = adapter.solve("main_setup")
            if not report.success:
                return None
            network = adapter.get_sparams()
            metrics = SpecEvaluator.compute_metrics(network, objectives)
            return SpecEvaluator.evaluate_objectives(metrics, objectives)
        finally:
            adapter.close()

    def _evaluate(adapter_name: str, params: dict, idx: int = 0) -> float | None:
        if adapter_name == "openems":
            return _evaluate_openems(params, idx)
        from rfauto.optimization.optimizer import _create_adapter
        adapter, _ver = _create_adapter(adapter_name, None, recipe_data)
        if adapter is None:
            raise RuntimeError(f"adapter {adapter_name} unavailable")
        try:
            plugin = plugin_cls()
            plugin.build(adapter, plugin.params_model(**params))
            report = adapter.solve("main_setup")
            if not report.success:
                return None
            network = adapter.get_sparams()
            metrics = SpecEvaluator.compute_metrics(network, objectives)
            return SpecEvaluator.evaluate_objectives(metrics, objectives)
        finally:
            adapter.close()

    low_costs, high_costs, valid = [], [], []
    for k, params in enumerate(samples):
        try:
            cl = _evaluate(low_adapter, params)
            ch = _evaluate(high_adapter, params, idx=k) if high_adapter != low_adapter \
                else _evaluate(low_adapter, params)
        except Exception as e:
            valid.append({"params": params, "error": str(e)})
            continue
        if cl is None or ch is None:
            continue
        low_costs.append(cl)
        high_costs.append(ch)
        valid.append({"params": params, "cost_low": cl, "cost_high": ch})

    rho = recall = None
    if len(low_costs) >= 3:
        rho = _spearman_rank_corr(low_costs, high_costs)
        low_order = sorted(range(len(low_costs)), key=lambda i: low_costs[i])
        high_order = sorted(range(len(high_costs)), key=lambda i: high_costs[i])
        low_top5 = set(low_order[:5])
        high_top8 = set(high_order[:8])
        recall = len(low_top5 & high_top8) / max(len(low_top5), 1)

    gate = "cross_fidelity" if high_adapter != low_adapter else "self_comparison_disabled"
    return {
        "ok": True,
        "gate": gate,
        "low_adapter": low_adapter,
        "high_adapter": high_adapter,
        "n_evaluated": len(low_costs),
        "spearman_rho": rho,
        "top5_recall": recall,
        "samples": valid[:10],
    }


def main():
    parser = argparse.ArgumentParser(description="Direction 1 P0 Experiment")
    parser.add_argument("--recipe", default="recipes/wilkinson_pd_v1.yaml")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--coarse-trials", type=int, default=40)
    parser.add_argument("--fine-trials", type=int, default=15)
    parser.add_argument("--baseline-trials", type=int, default=30)
    parser.add_argument("--edge-samples", type=int, default=20)
    parser.add_argument("--high-adapter", default="fake",
                        help="High-fidelity adapter for the cross gate (fake|openems|hfss). "
                             "'fake' (default) = same-model self comparison, gate disabled.")
    parser.add_argument("--cross-samples", type=int, default=15,
                        help="Param samples for the cross-fidelity ranking experiment.")
    args = parser.parse_args()

    out_dir = Path("runs/p0_experiment")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"P0 Experiment: {args.recipe}")
    print(f"  Seed: {args.seed}")
    print(f"  Baseline: {args.baseline_trials} trials (pure fake)")
    print(f"  Multi-fidelity: {args.coarse_trials} coarse + {args.fine_trials} fine")
    print(f"  Edge sampling: {args.edge_samples} samples")
    print()

    # 1. Baseline (single fidelity)
    print("=== Phase 1: Baseline (pure fake TPE) ===")
    t0 = time.time()
    baseline = run_single_fidelity(args.recipe, args.baseline_trials, args.seed)
    baseline_time = time.time() - t0
    print(f"  Completed in {baseline_time:.1f}s")
    print(f"  Best cost: {baseline.get('best_cost', 'N/A')}")

    # 2. Multi-fidelity
    print("\n=== Phase 2: Multi-fidelity (fake coarse + fine) ===")
    t0 = time.time()
    mf = run_multi_fidelity(args.recipe, args.coarse_trials, args.fine_trials, args.seed)
    mf_time = time.time() - t0
    print(f"  Completed in {mf_time:.1f}s")

    # 3. Compute Spearman correlation
    print("\n=== Phase 3: Correlation Analysis ===")
    spearman_rho = None
    top5_recall = None
    if mf.get("ok"):
        # Compare Phase 1 rankings with final rankings
        phase1_trials = mf.get("all_trials_ranked", [])
        final_trials = mf.get("final_trials_ranked", [])

        # Build cost lists for common trials (by trial number)
        phase1_by_num = {t["trial_number"]: t["cost"] for t in phase1_trials}
        final_by_num = {t["trial_number"]: t["cost"] for t in final_trials}
        common_nums = sorted(set(phase1_by_num) & set(final_by_num))

        if len(common_nums) >= 3:
            costs_phase1 = [phase1_by_num[n] for n in common_nums]
            costs_final = [final_by_num[n] for n in common_nums]
            spearman_rho = _spearman_rank_corr(costs_phase1, costs_final)
            if args.high_adapter != "fake":
                print(f"  [self-comparison, fake vs fake — 信息性，非验收门槛] "
                      f"Spearman rho: {spearman_rho:.4f}")
            else:
                print(f"  Spearman rho: {spearman_rho:.4f} (threshold: >= 0.8)")

            # Top-5 recall
            # Sort by cost: lower is better
            phase1_sorted = sorted(phase1_trials, key=lambda t: t.get("cost", float("inf")))
            final_sorted = sorted(final_trials, key=lambda t: t.get("cost", float("inf")))
            top5_recall = _top_k_recall(phase1_sorted, final_sorted, k_low=5, k_high=8)
            print(f"  Top-5 recall: {top5_recall:.2%} (threshold: >= 80%)")
        else:
            print("  Not enough common trials for correlation")
    else:
        print(f"  Multi-fidelity failed: {mf.get('errors', [])}")

    # 4. Edge sampling
    print("\n=== Phase 4: Edge Sampling ===")
    edge = edge_sampling_experiment(args.recipe, args.edge_samples, args.seed)
    if edge.get("edge_cost_mean") is not None:
        print(f"  Edge cost mean: {edge['edge_cost_mean']:.4f} (std: {edge.get('edge_cost_std', 0):.4f})")
        print(f"  Center cost mean: {edge.get('center_cost_mean', 'N/A')}")
    else:
        print("  Edge sampling returned no valid results")

    # 5. Cross-fidelity gate（缺口 #4：同模型自比较不再是有效证据）
    print("\n=== Phase 5: Cross-Fidelity Ranking Gate ===")
    cross = cross_fidelity_experiment(
        args.recipe, args.cross_samples, args.seed,
        low_adapter="fake", high_adapter=args.high_adapter,
    )
    cross_rho = cross.get("spearman_rho")
    cross_recall = cross.get("top5_recall")
    gate_active = cross.get("gate") == "cross_fidelity"
    print(f"  Gate mode: {cross.get('gate')}"
          + ("" if gate_active else "（fake vs fake 自比较，不产出跨保真证据）"))

    # 6. Verdict：跨保真 gate 是硬门槛；自比较模式仅报告，不做 PASS 判定
    print("\n=== Verdict ===")
    rho_pass = spearman_rho is not None and spearman_rho >= 0.8
    recall_pass = top5_recall is not None and top5_recall >= 0.8
    if gate_active:
        cross_pass = (cross_rho is not None and cross_rho >= 0.8
                      and cross_recall is not None and cross_recall >= 0.8)
        verdict = "PASS" if cross_pass else "FAIL"
    else:
        verdict = "INCONCLUSIVE"
    print(f"  [self-comparison] Spearman rho >= 0.8: {'PASS' if rho_pass else 'FAIL'} ({spearman_rho})")
    print(f"  [self-comparison] Top-5 recall >= 80%: {'PASS' if recall_pass else 'FAIL'} ({top5_recall})")
    print(f"  [cross-fidelity vs {args.high_adapter}] rho: {cross_rho}, recall: {cross_recall}"
          if gate_active else "  [cross-fidelity] gate disabled (self comparison)")
    print(f"  Overall: {verdict}")

    # Save results
    results = {
        "ok": True,
        "recipe": args.recipe,
        "seed": args.seed,
        "baseline": {
            "n_trials": args.baseline_trials,
            "best_cost": baseline.get("best_cost"),
            "elapsed_s": round(baseline_time, 1),
        },
        "multi_fidelity": {
            "coarse_trials": args.coarse_trials,
            "fine_trials": args.fine_trials,
            "phase1_best_cost": mf.get("phase1", {}).get("best_cost"),
            "phase2_best_cost": mf.get("phase2", {}).get("best_cost"),
            "elapsed_s": round(mf_time, 1),
        },
        "correlation": {
            "spearman_rho": spearman_rho,
            "top5_recall": top5_recall,
            "rho_pass": rho_pass,
            "recall_pass": recall_pass,
        },
        "edge_sampling": {
            "n_samples": edge.get("n_edge_samples"),
            "edge_cost_mean": edge.get("edge_cost_mean"),
            "edge_cost_std": edge.get("edge_cost_std"),
            "center_cost_mean": edge.get("center_cost_mean"),
        },
        "cross_fidelity_gate": {
            "gate": cross.get("gate"),
            "high_adapter": cross.get("high_adapter"),
            "n_evaluated": cross.get("n_evaluated"),
            "spearman_rho": cross_rho,
            "top5_recall": cross_recall,
        },
        "verdict": verdict,
    }
    (out_dir / "p0_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Generate report
    rho_str = f"{spearman_rho:.4f}" if spearman_rho is not None else "N/A"
    recall_str = f"{top5_recall:.2%}" if top5_recall is not None else "N/A"
    conclusion = {
        "PASS": "Multi-fidelity approach is validated for Direction 1 (cross-fidelity gate).",
        "FAIL": "Multi-fidelity failed the cross-fidelity gate. Direction 1 should fall back to fake-only.",
        "INCONCLUSIVE": ("Self-comparison only (high adapter = low adapter): no cross-fidelity evidence. "
                         "Re-run with --high-adapter openems/hfss for a hard gate."),
    }[verdict]
    report = f"""# P0 Experiment Report

**Recipe**: {args.recipe}
**Seed**: {args.seed}
**Verdict**: {verdict}

## Results

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Spearman rho (self) | {rho_str} | >= 0.8 | {'PASS' if rho_pass else 'FAIL'} |
| Top-5 recall (self) | {recall_str} | >= 80% | {'PASS' if recall_pass else 'FAIL'} |
| Cross-gate rho (vs {args.high_adapter}) | {f'{cross_rho:.4f}' if cross_rho is not None else 'N/A'} | >= 0.8 | {'ACTIVE' if gate_active else 'DISABLED'} |
| Cross-gate recall (vs {args.high_adapter}) | {f'{cross_recall:.2%}' if cross_recall is not None else 'N/A'} | >= 80% | {'ACTIVE' if gate_active else 'DISABLED'} |

## Configuration

- Baseline: {args.baseline_trials} trials (pure fake TPE)
- Multi-fidelity: {args.coarse_trials} coarse + {args.fine_trials} fine
- Edge sampling: {args.edge_samples} samples

## Edge Sampling Analysis

- Edge cost mean: {edge.get('edge_cost_mean', 'N/A')}
- Center cost mean: {edge.get('center_cost_mean', 'N/A')}

## Conclusion

{conclusion}
"""
    (out_dir / "p0_report.md").write_text(report, encoding="utf-8")
    print(f"\nResults saved to {out_dir}/")
    print("  p0_results.json")
    print("  p0_report.md")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
