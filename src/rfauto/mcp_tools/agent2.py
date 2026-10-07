"""even_odd_report/mcts_search/inverse_prefilter（ME-17b 第二组agent 原语）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool
def even_odd_report(template: str, params: dict[str, Any] | None = None,
                    freq_ghz: float | None = None) -> dict[str, Any]:
    """奇偶模分解报告（agent2 域）：模板+参数 → 对称性检查+半模型切割表。

    ME-17b 零逻辑转发 even_odd_service；对称性检查+半模型切割
    （even=PMC/odd=PEC）+端口改写表+重装配守卫，report 口径不抛对称性
    异常（ok=False+细节如实）。数值只出确定性内核（core.even_odd_split /
    KJ 闭式），LLM 不产生物理数字（铁律 7）。无副作用只读面，无时序约束。

    Args:
        template: 模板名（cline_coupler|branchline_2sect）
        params: 参数覆盖（mm 浮点；None=标称）
        freq_ghz: 频率（None=模板 f0）

    Returns:
        dict: {ok, template, axis, plane, symmetry_check, half_models,
               port_rewrite_table, mode_table, guards, ...}
    """
    from rfauto.service.even_odd_service import even_odd_split_report
    return even_odd_split_report(template, params, freq_ghz=freq_ghz)


@mcp.tool
def mcts_search(samples_path: str, n_simulations: int = 200,
                n_steps: int = 6, step_size: float = 0.1,
                kind: str = "poly_ridge", seed: int = 42) -> dict[str, Any]:
    """MCTS 设计搜索（agent2 域）：样本集最优点 → 定向序列探索最优候选。

    无副作用只读样本集；代理值函数搜索不替代 Optuna 战役（候选须仿真
    复核），数值只出确定性内核（铁律 7）。样本集缺失/点数不足 →
    ok=False errors 如实。只读无时序约束。

    Args:
        samples_path: 样本集 JSON（{"samples": [{params, cost}...],
            "bounds": {name: [low, high]}}，≥5 点）
        n_simulations: 模拟次数
        n_steps: 序列最大步数
        step_size: 每步归一化步长
        kind: 代理模型种类（poly_ridge 等，同校准面）
        seed: 随机种子

    Returns:
        dict: {ok, best: {params, cost_pred}, path, ...}；样本集缺失/非法
        → ok=False errors
    """
    from rfauto.service.mcts_search import mcts_search as _mcts_search
    return _mcts_search(samples_path, n_simulations=n_simulations,
                        n_steps=n_steps, step_size=step_size, kind=kind,
                        seed=seed)


@mcp.tool
def inverse_prefilter(recipe_path: str,
                      target_metrics: dict[str, float],
                      n_corpus: int = 400, k: int = 20,
                      jitter: float = 0.03, seed: int = 42) -> dict[str, Any]:
    """逆设计前滤波（agent2 域）：目标指标 → k 个候选参数起点（fake 语料）。

    无副作用（fake 通道全内存零落盘）；只做优化器前滤波不替代真机寻优，
    候选须中/高保真仿真复核。配方缺失/无搜索空间/空目标 → ok=False
    errors 如实。只读无时序约束。

    Args:
        recipe_path: 配方路径（读 optimization.params 搜索空间）
        target_metrics: 目标指标 {metric: value}（未指定的不计距离）
        n_corpus: 语料点数（fake 通道全内存零落盘）
        k: 返回候选数
        jitter: 抖动幅度（占各轴跨度比例）
        seed: 随机种子

    Returns:
        dict: {ok, candidates: [{params, seed_params, corpus_distance,
               corpus_metrics}], n_corpus, generator, ...}；配方/目标非法
        → ok=False errors
    """
    from rfauto.service.inverse_prefilter import prefilter_candidates
    return prefilter_candidates(recipe_path, target_metrics,
                                n_corpus=n_corpus, k=k, jitter=jitter,
                                seed=seed)
