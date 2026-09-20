"""参数扫描后端——粗扫→精调默认编排（P2-D3）。

流程：
1. Phase 1（粗扫）：LHS 均匀采样覆盖全参数空间
2. Phase 2（精调）：从粗扫 top-N 结果出发，局部网格细化

适配器连接一次，每个组合只 update vars + solve（与 optimizer 一致）。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from rfauto.core.objectives import Objective, SpecEvaluator
from rfauto.core.parameters import ParameterSystem, ParamValue

logger = logging.getLogger(__name__)


# ─── 采样器 ──────────────────────────────────────────────────────────────────

def grid_sweep(param_ranges: dict[str, tuple[float, float]], points_per_dim: int = 10) -> list[dict[str, float]]:
    """网格扫描：遍历所有参数组合。"""
    names = sorted(param_ranges.keys())
    grids = [np.linspace(param_ranges[n][0], param_ranges[n][1], points_per_dim) for n in names]
    mesh = np.meshgrid(*grids, indexing="ij")
    combos = []
    for idx in np.ndindex(mesh[0].shape):
        combos.append({names[i]: float(mesh[i][idx]) for i in range(len(names))})
    return combos


def random_sweep(param_ranges: dict[str, tuple[float, float]], n_samples: int = 100) -> list[dict[str, float]]:
    """随机采样。"""
    names = sorted(param_ranges.keys())
    combos = []
    for _ in range(n_samples):
        combo = {}
        for n in names:
            lo, hi = param_ranges[n]
            combo[n] = float(np.random.uniform(lo, hi))
        combos.append(combo)
    return combos


def latin_hypercube_sweep(param_ranges: dict[str, tuple[float, float]], n_samples: int = 100) -> list[dict[str, float]]:
    """拉丁超方采样（LHS）——比随机采样覆盖更均匀。"""
    try:
        from scipy.stats import qmc
    except ImportError:
        return random_sweep(param_ranges, n_samples)

    names = sorted(param_ranges.keys())
    d = len(names)
    sampler = qmc.LatinHypercube(d=d, seed=42)
    sample = sampler.random(n=n_samples)

    ranges = np.array([param_ranges[n] for n in names])
    lows = ranges[:, 0]
    spans = ranges[:, 1] - ranges[:, 0]

    scaled = qmc.scale(sample, lows, lows + spans)
    return [{names[j]: float(scaled[i, j]) for j in range(d)} for i in range(n_samples)]


def local_grid_sweep(
    center: dict[str, float],
    radius: dict[str, float],
    points_per_dim: int = 5,
) -> list[dict[str, float]]:
    """以 center 为中心、radius 为半径的局部网格。"""
    names = sorted(center.keys())
    grids = [
        np.linspace(center[n] - radius[n], center[n] + radius[n], points_per_dim)
        for n in names
    ]
    mesh = np.meshgrid(*grids, indexing="ij")
    combos = []
    for idx in np.ndindex(mesh[0].shape):
        combos.append({names[i]: float(mesh[i][idx]) for i in range(len(names))})
    return combos


# ─── 参数范围提取（复用 optimizer） ──────────────────────────────────────────

def _extract_ranges(recipe_data: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """从配方提取参数范围（与 optimizer 共用逻辑）。"""
    from rfauto.optimization.optimizer import extract_param_ranges
    ranges_dict = extract_param_ranges(recipe_data)
    return {k: (v["low"], v["high"]) for k, v in ranges_dict.items()}


# ─── 主入口 ─────────────────────────────────────────────────────────────────

def run_sweep(
    recipe_path: str | Path,
    *,
    adapter_name: str = "fake",
    method: str = "auto",
    coarse_samples: int = 30,
    fine_per_top: int = 5,
    top_n: int = 3,
    fine_points_per_dim: int = 5,
    max_combos: int = 100,
    adapter_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行参数扫描（粗扫→精调）。

    Args:
        recipe_path: 配方文件路径
        adapter_name: "fake" | "hfss"
        method: "auto"（粗扫+精调）| "grid" | "random" | "lhs" | "fine_only"
        coarse_samples: 粗扫采样数
        fine_per_top: 每个 top 结果的局部网格样本数
        top_n: 从粗扫取前 N 个结果做精调
        fine_points_per_dim: 局部网格每维点数
        max_combos: 最大组合数（安全上限）
        adapter_kwargs: 额外适配器构造参数

    Returns:
        {ok, run_id, run_dir, method, total_combos, results, best}
    """
    from rfauto.core.state import generate_run_id
    from rfauto.infra.run_store import create_run_dir, record_run, snapshot_recipe, write_meta

    # 加载配方
    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方文件不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    # 提取参数范围
    param_ranges = _extract_ranges(recipe_data)
    if not param_ranges:
        return {
            "ok": False,
            "errors": [
                "无可选扫描参数。请在配方中添加 optimization.params 段或 params.<name>.bounds。"
            ],
        }

    # 解析目标函数
    objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    if not objectives:
        return {"ok": False, "errors": ["缺少 objectives 段"]}

    # 创建 run 目录
    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)
    results_dir = run_dir / "sweep_results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # 创建适配器
    adapter, aedt_version = _create_adapter(adapter_name, adapter_kwargs, recipe_data)
    if adapter is None:
        return {"ok": False, "errors": [f"适配器创建失败: {adapter_name}"]}

    # adapter 会话由 finally 统一回收：任何中途异常/提前返回都不泄漏 AEDT 会话与
    # license（审查发现：原先 _run_combos 内异常会带着已连接会话直接逃逸）
    try:
        # 获取模型插件 + 构建
        model_name = recipe_data.get("model", "")
        try:
            from rfauto.models.registry import get as get_plugin_cls
            plugin_cls = get_plugin_cls(model_name)
            plugin = plugin_cls()
        except KeyError:
            return {"ok": False, "errors": [f"未知模型: {model_name}"]}

        # 解析参数
        params_data = recipe_data.get("params", {})
        param_values: dict[str, ParamValue] = {}
        for k, v in params_data.items():
            if isinstance(v, dict):
                param_values[k] = ParamValue(
                    name=k,
                    value=v.get("value", 0),
                    unit=v.get("unit", "mm"),
                    bounds=tuple(v["bounds"]) if v.get("bounds") else None,
                )
            else:
                param_values[k] = ParamValue(name=k, value=v)

        param_system = ParameterSystem(param_values)

        # 构建模型（一次性）
        try:
            plugin.build(
                adapter,
                plugin.params_model(**{
                    k: (v["value"] if isinstance(v, dict) else v) for k, v in params_data.items()
                }),
            )
            param_system.write_to_adapter(
                adapter, name_map=getattr(plugin_cls, "hfss_var_map", {})
            )
        except Exception as e:
            return {"ok": False, "errors": [f"模型构建失败: {e}"]}

        # setup 通道（C4 修复，与 optimizer 一致）：HFSS 模式按配方 setup 段
        # 创建 Setup + Sweep 并用返回名求解；fake 忽略 setup 名
        setup_name = "main_setup"
        if adapter_name == "hfss":
            setup_name = adapter.configure_setup(recipe_data.get("setup", {}))

        # ─── Phase 1: 粗扫（max_combos 安全上限同样约束粗扫阶段）──────────
        start_time = time.time()
        phase1_combos: list[dict[str, float]] = []
        phase1_results: list[dict[str, Any]] = []

        if method in ("auto", "lhs"):
            phase1_combos = latin_hypercube_sweep(param_ranges, coarse_samples)[:max_combos]
            phase1_results = _run_combos(
                adapter, param_system, phase1_combos, objectives, results_dir,
                prefix="coarse", setup_name=setup_name,
                name_map=getattr(plugin_cls, "hfss_var_map", {}),
            )
        elif method == "grid":
            phase1_combos = grid_sweep(param_ranges, min(10, coarse_samples))[:max_combos]
            phase1_results = _run_combos(
                adapter, param_system, phase1_combos, objectives, results_dir,
                prefix="coarse", setup_name=setup_name,
                name_map=getattr(plugin_cls, "hfss_var_map", {}),
            )
        elif method == "random":
            phase1_combos = random_sweep(param_ranges, coarse_samples)[:max_combos]
            phase1_results = _run_combos(
                adapter, param_system, phase1_combos, objectives, results_dir,
                prefix="coarse", setup_name=setup_name,
                name_map=getattr(plugin_cls, "hfss_var_map", {}),
            )
        elif method == "fine_only":
            # 跳过粗扫，直接在全空间做局部网格（以中心值为起点）
            center = {k: (v[0] + v[1]) / 2 for k, v in param_ranges.items()}
            radius = {k: (v[1] - v[0]) / 4 for k, v in param_ranges.items()}
            phase1_combos = local_grid_sweep(center, radius, fine_points_per_dim)[:max_combos]
            phase1_results = _run_combos(
                adapter, param_system, phase1_combos, objectives, results_dir,
                prefix="fine", setup_name=setup_name,
                name_map=getattr(plugin_cls, "hfss_var_map", {}),
            )
        else:
            return {"ok": False, "errors": [f"未知方法: {method}"]}

        # ─── Phase 2: 精调（auto 模式） ─────────────────────────────────
        phase2_combos: list[dict[str, float]] = []
        phase2_results: list[dict[str, Any]] = []

        if method == "auto" and phase1_results:
            # 按 cost 排序，取 top_n
            sorted_results = sorted(phase1_results, key=lambda r: r.get("cost", float("inf")))
            top_results = sorted_results[:top_n]

            for _i, top in enumerate(top_results):
                center = top["params"]
                radius = {k: (param_ranges[k][1] - param_ranges[k][0]) / 8 for k in param_ranges}
                local_combos = local_grid_sweep(center, radius, fine_points_per_dim)
                # 去重：跳过已在粗扫中出现的组合
                existing = {tuple(sorted(c.items())) for c in phase1_combos}
                new_combos = [c for c in local_combos if tuple(sorted(c.items())) not in existing]
                phase2_combos.extend(new_combos)

            # 限制总数：剩余配额为负时不补充（原先负下标切片语义相反，会保留大量组合）
            remaining = max_combos - len(phase1_combos)
            if phase2_combos and remaining > 0:
                phase2_combos = phase2_combos[:remaining]
                phase2_results = _run_combos(
                    adapter, param_system, phase2_combos, objectives, results_dir,
                    prefix="fine", setup_name=setup_name,
                    name_map=getattr(plugin_cls, "hfss_var_map", {}),
                )
    finally:
        adapter.close()

    elapsed = time.time() - start_time

    # 汇总结果
    all_results = phase1_results + phase2_results
    all_results.sort(key=lambda r: r.get("cost", float("inf")))

    # 写入汇总文件
    summary = {
        "run_id": run_id,
        "method": method,
        "elapsed_s": round(elapsed, 1),
        "total_combos": len(all_results),
        "coarse_combos": len(phase1_results),
        "fine_combos": len(phase2_results),
        "param_ranges": {k: list(v) for k, v in param_ranges.items()},
        "results": all_results,
    }
    (results_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # 写 meta
    write_meta(run_dir, {
        "run_id": run_id,
        "model": model_name,
        "adapter": adapter_name,
        "aedt_version": aedt_version,
        "status": "done",
        "method": method,
        "metrics": all_results[0]["metrics"] if all_results else {},
    })
    record_run(Path("runs") / "index.db", {
        "run_id": run_id,
        "model": model_name,
        "adapter": adapter_name,
        "status": "done",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": all_results[0]["metrics"] if all_results else {},
    })

    return {
        "ok": True,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "method": method,
        "elapsed_s": round(elapsed, 1),
        "total_combos": len(all_results),
        "coarse_combos": len(phase1_results),
        "fine_combos": len(phase2_results),
        "results": all_results[:20],  # 返回前 20 个结果（避免过大）
        "best": all_results[0] if all_results else None,
    }


def _run_combos(
    adapter: Any,
    param_system: ParameterSystem,
    combos: list[dict[str, float]],
    objectives: list[Objective],
    results_dir: Path,
    prefix: str = "sweep",
    setup_name: str = "main_setup",
    name_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """执行一组参数组合的仿真，返回结果列表。"""
    results = []
    for i, combo in enumerate(combos):
        # 更新参数 + 求解（单组合异常只记失败不中断整个扫描，
        # 与 optimizer 的"失败即剪枝"哲学一致）
        try:
            param_system.update(combo)
            param_system.write_to_adapter(adapter, name_map=name_map)
            report = adapter.solve(setup_name)
        except Exception as e:
            results.append({
                "combo_index": i,
                "params": combo,
                "cost": float("inf"),
                "metrics": {},
                "error": str(e),
            })
            continue

        if not report.success:
            results.append({
                "combo_index": i,
                "params": combo,
                "cost": float("inf"),
                "metrics": {},
                "error": report.message,
            })
            continue

        # 获取 S 参数 + 计算指标
        network = adapter.get_sparams()
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)

        result = {
            "combo_index": i,
            "params": combo,
            "cost": cost,
            "metrics": metrics,
        }
        results.append(result)

        # 写入单个结果文件
        result_file = results_dir / f"{prefix}_{i:04d}.json"
        result_file.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    return results


# ─── 适配器工厂（复用 optimizer） ────────────────────────────────────────────

def _create_adapter(
    adapter_name: str,
    adapter_kwargs: dict[str, Any] | None,
    recipe_data: dict[str, Any],
) -> tuple[Any | None, str]:
    """创建并连接适配器。"""
    from rfauto.optimization.optimizer import _create_adapter as _ca
    return _ca(adapter_name, adapter_kwargs, recipe_data)
