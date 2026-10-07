"""参数扫描后端——粗扫→精调默认编排（P2-D3）。

流程：
1. Phase 1（粗扫）：LHS 均匀采样覆盖全参数空间
2. Phase 2（精调）：从粗扫 top-N 结果出发，局部网格细化

适配器连接一次，每个组合只 update vars + solve（与 optimizer 一致）。
"""

from __future__ import annotations

import contextlib
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


def random_sweep(
    param_ranges: dict[str, tuple[float, float]],
    n_samples: int = 100,
    seed: int = 42,
) -> list[dict[str, float]]:
    """随机采样（确定性）。

    seed: 显式随机种子（仓内合成器"显式 seed"惯例，参照 sample_design.lhs_points）。
    同 seed 同参数两次调用逐位相等（审查 D1-4：原先用全局未种子化
    np.random.uniform，同输入两次调用产生不同点集，违反可复现红线）；
    seed=None 显式报错（不接受"隐式不可复现"路径）。
    """
    if seed is None:
        raise ValueError(
            "random_sweep 的 seed 须显式给出（int）——None 会导致同输入两次"
            "调用产生不同点集（审查 D1-4 可复现红线）；需要新轨迹请换 seed 值")
    if not isinstance(seed, (int, np.integer)):
        raise ValueError(f"seed 须为整数，得 {type(seed).__name__}")
    rng = np.random.RandomState(seed)
    names = sorted(param_ranges.keys())
    combos = []
    for _ in range(n_samples):
        combo = {}
        for n in names:
            lo, hi = param_ranges[n]
            combo[n] = float(rng.uniform(lo, hi))
        combos.append(combo)
    return combos


def latin_hypercube_sweep(
    param_ranges: dict[str, tuple[float, float]],
    n_samples: int = 100,
    seed: int = 42,
) -> list[dict[str, float]]:
    """拉丁超方采样（LHS）——比随机采样覆盖更均匀。

    seed: 显式随机种子（缺省 42 与历史硬编码值一致，兼容既有调用方）。
    """
    try:
        from scipy.stats import qmc
    except ImportError:
        return random_sweep(param_ranges, n_samples, seed=seed)

    names = sorted(param_ranges.keys())
    d = len(names)
    sampler = qmc.LatinHypercube(d=d, seed=seed)
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
    progress_cb: Any = None,
    resume_run_id: str | None = None,
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
        progress_cb: 可选 ``cb(done, total, tag)`` 逐组合进度（SN-11；异常
            吞掉不阻塞；None=零行为）。
        resume_run_id: 可选断点续扫源 run（SN-11）：读其
            ``sweep_results/checkpoint.jsonl``，命中组合跳过真跑并携带原
            结果；新 run 的 checkpoint 自包含全部历史（可再续）。组合生成
            全链确定性（seed 缺省 42），同配方同参数下命中键稳定。

    Returns:
        {ok, run_id, run_dir, method, total_combos, results, best,
        resumed_combos}
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

    # SN-11：断点源（先于新 run 目录创建读取——源损坏 fail-fast 不建脏目录）
    prior_results: list[dict[str, Any]] = []
    if resume_run_id:
        src_cp = (Path("runs") / str(resume_run_id)
                  / "sweep_results" / "checkpoint.jsonl")
        if not src_cp.is_file():
            return {"ok": False, "errors": [
                f"resume 源无 checkpoint: {src_cp}"
                "（仅 run_sweep 产出的 run（sweep_results/checkpoint.jsonl）可续）"]}
        prior_results = load_sweep_checkpoint(src_cp.parent)

    # 创建 run 目录
    run_id = generate_run_id()
    run_dir = create_run_dir(Path(".").resolve(), run_id)
    snapshot_recipe(run_dir, recipe_data)
    results_dir = run_dir / "sweep_results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # SN-11：断点账本。resume 时先把源 checkpoint 结果写入新 run 的
    # checkpoint.jsonl（新 run 自包含全部历史，可继续续跑），命中键跳过
    # 真跑；非 resume 时为空集零行为变化。
    checkpoint_file = results_dir / "checkpoint.jsonl"
    done_keys = {_combo_key(r["params"]) for r in prior_results}
    if prior_results:
        with open(checkpoint_file, "a", encoding="utf-8") as cp0:
            for r in prior_results:
                cp0.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    # SN-11：全局进度账（跨 phase 累计；tag=coarse/fine；回调异常已在
    # _run_combos 侧吞掉，这里不再包一层）
    def _phase_progress(tag: str) -> Any:
        if progress_cb is None:
            return None
        base_done = len(prior_results)

        def cb(done: int, total: int) -> None:
            progress_cb(base_done + done, base_done + total, tag)
        return cb

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
                checkpoint_file=checkpoint_file, done_keys=done_keys,
                on_done=_phase_progress("coarse"),
            )
        elif method == "grid":
            phase1_combos = grid_sweep(param_ranges, min(10, coarse_samples))[:max_combos]
            phase1_results = _run_combos(
                adapter, param_system, phase1_combos, objectives, results_dir,
                prefix="coarse", setup_name=setup_name,
                name_map=getattr(plugin_cls, "hfss_var_map", {}),
                checkpoint_file=checkpoint_file, done_keys=done_keys,
                on_done=_phase_progress("coarse"),
            )
        elif method == "random":
            phase1_combos = random_sweep(param_ranges, coarse_samples)[:max_combos]
            phase1_results = _run_combos(
                adapter, param_system, phase1_combos, objectives, results_dir,
                prefix="coarse", setup_name=setup_name,
                name_map=getattr(plugin_cls, "hfss_var_map", {}),
                checkpoint_file=checkpoint_file, done_keys=done_keys,
                on_done=_phase_progress("coarse"),
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
                checkpoint_file=checkpoint_file, done_keys=done_keys,
                on_done=_phase_progress("fine"),
            )
        else:
            return {"ok": False, "errors": [f"未知方法: {method}"]}

        # SN-11：resume 时 top 选择与统计把携带的 checkpoint 结果并入
        # （命中组合未重跑，但其结果必须参与 top-N 排序，否则精调中心漂移）
        phase1_effective = list(prior_results) + list(phase1_results) \
            if prior_results else list(phase1_results)

        # ─── Phase 2: 精调（auto 模式） ─────────────────────────────────
        phase2_combos: list[dict[str, float]] = []
        phase2_results: list[dict[str, Any]] = []

        if method == "auto" and phase1_effective:
            # 按 cost 排序，取 top_n
            sorted_results = sorted(phase1_effective, key=lambda r: r.get("cost", float("inf")))
            top_results = sorted_results[:top_n]

            for _i, top in enumerate(top_results):
                center = top["params"]
                radius = {k: (param_ranges[k][1] - param_ranges[k][0]) / 8 for k in param_ranges}
                local_combos = local_grid_sweep(center, radius, fine_points_per_dim)
                # 去重：跳过已在粗扫中出现的组合（resume 时含 checkpoint 携带集）
                existing = {_combo_key(c) for c in phase1_combos}
                existing |= {_combo_key(r["params"]) for r in prior_results}
                new_combos = [c for c in local_combos if _combo_key(c) not in existing]
                phase2_combos.extend(new_combos)

            # 限制总数：剩余配额为负时不补充（原先负下标切片语义相反，会保留大量组合）
            remaining = max_combos - len(phase1_combos)
            if phase2_combos and remaining > 0:
                phase2_combos = phase2_combos[:remaining]
                phase2_results = _run_combos(
                    adapter, param_system, phase2_combos, objectives, results_dir,
                    prefix="fine", setup_name=setup_name,
                    name_map=getattr(plugin_cls, "hfss_var_map", {}),
                    checkpoint_file=checkpoint_file, done_keys=done_keys,
                    on_done=_phase_progress("fine"),
                )
    finally:
        adapter.close()

    elapsed = time.time() - start_time

    # 汇总结果（SN-11：resume 时携带的 checkpoint 结果并入全量排序；
    # coarse_combos/fine_combos 语义保持"本 run 新跑数"，resumed 单列）
    all_results = list(prior_results) + phase1_results + phase2_results
    all_results.sort(key=lambda r: r.get("cost", float("inf")))

    # 写入汇总文件
    summary = {
        "run_id": run_id,
        "method": method,
        "elapsed_s": round(elapsed, 1),
        "total_combos": len(all_results),
        "coarse_combos": len(phase1_results),
        "fine_combos": len(phase2_results),
        "resumed_combos": len(prior_results),
        "resume_source": str(resume_run_id or ""),
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
    record_run(record={
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
        "resumed_combos": len(prior_results),
        "results": all_results[:20],  # 返回前 20 个结果（避免过大）
        "best": all_results[0] if all_results else None,
    }


# ─── 计划面（SN-18 dry-run：只算账不建适配器不求解不写盘） ──────────────────

def plan_sweep(
    recipe_path: str | Path,
    *,
    method: str = "auto",
    coarse_samples: int = 30,
    fine_per_top: int = 5,
    top_n: int = 3,
    fine_points_per_dim: int = 5,
    max_combos: int = 100,
) -> dict[str, Any]:
    """扫描计划预览（SN-18 ``sweep --dry-run``）：组合数/方法/参数范围实算，
    零执行零写盘（不建 run 目录、不建适配器）。

    组合数按 method 与 run_sweep 同源生成器实算（确定性：lhs/random seed
    缺省 42），phase1 截 max_combos；auto 模式的 phase2 数额依赖真跑 top
    结果，如实标注 ``phase2: depends_on_results``（不臆造）。
    """
    path = Path(recipe_path)
    if not path.exists():
        return {"ok": False, "errors": [f"配方文件不存在: {path}"]}
    with open(path, encoding="utf-8") as f:
        recipe_data = yaml.safe_load(f)

    try:
        param_ranges = _extract_ranges(recipe_data)
    except Exception as exc:
        return {"ok": False, "errors": [f"参数范围解析失败: {exc}"]}
    if not param_ranges:
        return {"ok": False, "errors": [
            "无可选扫描参数。请在配方中添加 optimization.params 段或 params.<name>.bounds。"]}
    try:
        objectives = [Objective(**o) for o in recipe_data.get("objectives", [])]
    except Exception as exc:
        return {"ok": False, "errors": [f"objectives 段非法: {exc}"]}
    if not objectives:
        return {"ok": False, "errors": ["缺少 objectives 段"]}
    if method not in ("auto", "lhs", "grid", "random", "fine_only"):
        return {"ok": False, "errors": [f"未知方法: {method}"]}

    if method in ("auto", "lhs"):
        p1 = latin_hypercube_sweep(param_ranges, coarse_samples)[:max_combos]
    elif method == "grid":
        p1 = grid_sweep(param_ranges, min(10, coarse_samples))[:max_combos]
    elif method == "random":
        p1 = random_sweep(param_ranges, coarse_samples)[:max_combos]
    else:
        center = {k: (v[0] + v[1]) / 2 for k, v in param_ranges.items()}
        radius = {k: (v[1] - v[0]) / 4 for k, v in param_ranges.items()}
        p1 = local_grid_sweep(center, radius, fine_points_per_dim)[:max_combos]

    model_name = recipe_data.get("model", "")
    return {
        "ok": True,
        "mode": "dry-run",
        "recipe": str(path),
        "model": model_name,
        "adapter_note": "适配器未创建（dry-run 不连接不求解）",
        "method": method,
        "param_ranges": {k: list(v) for k, v in param_ranges.items()},
        "n_objectives": len(objectives),
        "phase1_combos": len(p1),
        "phase2": ("depends_on_results（top-N 精调，run 时按粗扫 top 实算）"
                    if method == "auto" else 0),
        "max_combos": int(max_combos),
    }


def _combo_key(combo: dict[str, float]) -> str:
    """组合 → 确定性键（JSON 浮点 round-trip 精确；checkpoint 匹配用）。"""
    return json.dumps({k: combo[k] for k in sorted(combo)}, sort_keys=True)


def load_sweep_checkpoint(results_dir: Path) -> list[dict[str, Any]]:
    """读 sweep checkpoint（SN-11：逐组合 JSONL，逐行落盘即时断点）。

    损坏行跳过（单行损坏不丢整卷，与 trials/*.json 读取同纪律）；文件
    缺失返回空表。行结构=_run_combos 单结果 dict（params/cost/metrics/...）。
    """
    cp = Path(results_dir) / "checkpoint.jsonl"
    if not cp.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in cp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("params"), dict):
            out.append(data)
    return out


def _run_combos(
    adapter: Any,
    param_system: ParameterSystem,
    combos: list[dict[str, float]],
    objectives: list[Objective],
    results_dir: Path,
    prefix: str = "sweep",
    setup_name: str = "main_setup",
    name_map: dict[str, str] | None = None,
    checkpoint_file: Path | None = None,
    done_keys: set[str] | None = None,
    on_done: Any = None,
) -> list[dict[str, Any]]:
    """执行一组参数组合的仿真，返回结果列表。

    SN-11（W6-A，2026-10-06）增量（全部可选，缺省零行为变化）：
    - ``checkpoint_file``：给定时每个组合结果**先落 JSONL 再继续**（逐行
      append+flush，中途死只丢在跑组合，不丢已完成序列）；
    - ``done_keys``：已键集合（``_combo_key``），命中组合跳过真跑、原样
      携带 checkpoint 结果返回（resume 的"数据不丢且不重跑"半边）；
    - ``on_done(done, total)``：逐组合进度回调（异常吞掉，#105）。
    """
    results = []
    done = 0
    total = len(combos)
    cp_handle = None
    if checkpoint_file is not None:
        # 循环生命周期句柄（逐行 append+flush），finally 统一关闭
        cp_handle = open(checkpoint_file, "a", encoding="utf-8")  # noqa: SIM115

    def _register(result: dict[str, Any]) -> None:
        """记账闭合：计数+断点行+进度回调（本 phase 内三处出口共用）。"""
        nonlocal done
        done += 1
        if cp_handle is not None:
            cp_handle.write(json.dumps(
                result, ensure_ascii=False, default=str) + "\n")
            cp_handle.flush()
        if on_done is not None:
            with contextlib.suppress(Exception):
                on_done(done, total)

    try:
        for i, combo in enumerate(combos):
            key = _combo_key(combo)
            if done_keys and key in done_keys:
                # resume 命中：不重跑；结果由 run_sweep 预注入（checkpoint 携带）
                done += 1
                if on_done is not None:
                    with contextlib.suppress(Exception):
                        on_done(done, total)
                continue
            # 更新参数 + 求解（单组合异常只记失败不中断整个扫描，
            # 与 optimizer 的"失败即剪枝"哲学一致）
            try:
                param_system.update(combo)
                param_system.write_to_adapter(adapter, name_map=name_map)
                report = adapter.solve(setup_name)
            except Exception as e:
                _register({
                    "combo_index": i,
                    "params": combo,
                    "cost": float("inf"),
                    "metrics": {},
                    "error": str(e),
                })
                continue

            if not report.success:
                _register({
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
            # SN-11：断点行（单行 JSON，先于下一组合求解落盘）
            _register(result)
    finally:
        if cp_handle is not None:
            cp_handle.close()

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
