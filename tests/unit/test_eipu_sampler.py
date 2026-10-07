"""M3 EIpu 成本感知 BO（cost GP + EI/c）+ R9 排序承诺件定向测试。

被测对象：src/rfauto/optimization/eipu.py（suggest 循环内核 + 采集
分数审计面 + R9 commitment_order）。零 IO 零真机（合成裁判）。

合成裁判判据（**预声明后冻结**，原型 scripts 阶段实测后落门，不事后
改门；换判据=显式重标定）：

1. **机制钉（acquisition 排序翻转）**：固定观测集
   X={0.2,0.4,0.6,0.8}、y={−0.55,−0.30,−0.40,−0.62}（右谷更深=纯 EI
   吸力）、cost={1,1,50,50}（阶跃：0.5 右=昂贵档，openEMS 秒级 vs
   HFSS 分钟级的极限形态），探针 A=0.10（廉价谷侧翼）/ B=0.90（昂贵
   谷侧翼）：
   - ĉ(A) < 5 且 ĉ(B) > 10（cost GP 梯度真实存在）；
   - 纯 EI 偏好 B：EI(B) > EI(A)（cost-blind 被深谷吸走）；
   - EIpu 翻转：score(A) > score(B）（EI/(ĉ+ε) 把排序翻向廉价侧）。
   原型实测边距：EI(B)/EI(A)≈1.8×、score(A)/score(B)≈4.5×——
   双向都有 >1.5× 余量才冻结。

2. **环裁判（等预算 A/B，7 seeds）**：f=双谷（廉价谷 −0.50@0.18 /
   昂贵谷 −0.62@0.82，w=0.18）、cost 阶跃 1/50@0.5、init=[0.48,0.58]
   （两档各一，剥初始化彩票）、n_iters=10、预算 110：
   - EIpu 预算截断 best-f 优于纯 EI 于 ≥6/7 seeds（实测 7/7）；
   - EIpu 命中廉价谷（bf ≤ −0.45）于 ≥6/7 seeds（实测 7/7，
     bf≈−0.498 vs 纯 EI≈−0.32——纯 EI 的 greedy 被深谷吸去连烧
     50 代价档，预算死于半途）。
   边距（≈0.17 f 单位）远大于跨跑漂移（确定性 GP + 固定 seed）。

3. **确定性/退化钉**：同 seed 轨迹逐位一致；strategy="ei" 对 cost
   置乱不变（cost-blind 语义）；score_candidates 与 suggest 在同点
   同值（同一 GP 同一口径）；EI 解析值（Φ/φ 恒等式）；校验面显式
   拒绝（形状/cost 非正/strategy 未知/样本不足/init 缺参）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from rfauto.optimization.eipu import (
    EIPUConfig,
    commitment_order,
    expected_improvement_min,
    run_eipu_loop,
    score_candidates,
    suggest_next_point,
)

BOUNDS_1D = {"x": (0.0, 1.0)}


# ── EI 解析钉 ─────────────────────────────────────────────────────────────

def test_expected_improvement_analytic() -> None:
    """EI 恒等式：μ=y* 时 EI=σ·φ(0)；μ=y*−1、σ=1 时 Φ(1)+φ(1)；σ→0 截断。"""
    y_best = 0.0
    # μ=y*, σ=1, ξ=0 → EI = 0·Φ(0) + 1·φ(0) = 0.398942...
    ei = expected_improvement_min(np.array([0.0]), np.array([1.0]), y_best, xi=0.0)
    assert ei[0] == pytest.approx(1.0 / math.sqrt(2.0 * math.pi), rel=1e-9)
    # μ=y*−1, σ=1, ξ=0 → EI = 1·Φ(1) + φ(1)
    ei = expected_improvement_min(np.array([-1.0]), np.array([1.0]), y_best, xi=0.0)
    assert ei[0] == pytest.approx(
        0.8413447460685429 + 0.24197072451914337, rel=1e-9)
    # ξ 扣减：improvement 整体下移
    ei0 = expected_improvement_min(np.array([-1.0]), np.array([1.0]), y_best, xi=0.0)
    ei1 = expected_improvement_min(np.array([-1.0]), np.array([1.0]), y_best, xi=0.5)
    assert ei1[0] < ei0[0]
    # σ 地板：确定性退化 max(0, y*−ξ−μ)（μ=−0.5 → 0−0.1+0.5=0.4）
    ei = expected_improvement_min(np.array([-0.5, -2.0]), np.array([0.0, 0.0]),
                                  y_best, xi=0.1)
    assert ei[0] == pytest.approx(0.4)
    assert ei[1] == pytest.approx(1.9)


def test_expected_improvement_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="形状不一致"):
        expected_improvement_min(np.array([0.0, 1.0]), np.array([1.0]), 0.0)
    with pytest.raises(ValueError, match="非有限"):
        expected_improvement_min(np.array([np.nan]), np.array([1.0]), 0.0)
    with pytest.raises(ValueError, match="非负"):
        expected_improvement_min(np.array([0.0]), np.array([-1.0]), 0.0)


# ── 机制钉：acquisition 排序翻转（判据预声明见模块 docstring）────────────

_MECH_X = np.array([[0.2], [0.4], [0.6], [0.8]])
_MECH_Y = np.array([-0.55, -0.30, -0.40, -0.62])
_MECH_C = np.array([1.0, 1.0, 50.0, 50.0])


def test_mechanism_cost_conditioned_ranking_flip() -> None:
    """EIpu 在纯 EI 偏好昂贵侧时把排序翻向廉价侧（机制级裁判）。"""
    cfg = EIPUConfig(seed=0)
    probes = [{"x": 0.10}, {"x": 0.90}]  # A=廉价谷侧翼, B=昂贵谷侧翼
    rows_eipu = score_candidates(_MECH_X, _MECH_Y, _MECH_C, probes,
                                 BOUNDS_1D, strategy="eipu", config=cfg)
    rows_ei = score_candidates(_MECH_X, _MECH_Y, None, probes,
                               BOUNDS_1D, strategy="ei", config=cfg)
    a, b = rows_eipu
    ae, be = rows_ei
    # cost GP 梯度真实存在（廉价侧 ĉ 压到观测档量级，昂贵侧显著抬升）
    assert a["c_hat"] < 5.0, f"廉价侧 ĉ 未下压: {a['c_hat']}"
    assert b["c_hat"] > 10.0, f"昂贵侧 ĉ 未抬升: {b['c_hat']}"
    # cost-blind 偏好昂贵侧（深谷吸力）
    assert be["ei"] > ae["ei"], (
        f"纯 EI 应偏好昂贵侧 B: EI(A)={ae['ei']:.4f} vs EI(B)={be['ei']:.4f}")
    # EIpu 翻转：廉价侧分数胜出
    assert a["score"] > b["score"], (
        f"EIpu 未翻转: score(A)={a['score']:.5f} vs score(B)={b['score']:.5f}")


def test_score_candidates_consistent_with_suggest() -> None:
    """score_candidates 与 suggest_next_point 同点同值（同一 GP 同口径）。"""
    cfg = EIPUConfig(seed=3)
    pick, diag = suggest_next_point(_MECH_X, _MECH_Y, _MECH_C, BOUNDS_1D,
                                    strategy="eipu", config=cfg)
    row = score_candidates(_MECH_X, _MECH_Y, _MECH_C, [pick], BOUNDS_1D,
                           strategy="eipu", config=cfg)[0]
    assert row["ei"] == pytest.approx(diag["ei"], rel=1e-9, abs=1e-12)
    assert row["c_hat"] == pytest.approx(diag["c_hat"], rel=1e-9)
    assert row["score"] == pytest.approx(diag["score"], rel=1e-9)


def test_suggest_ei_strategy_is_cost_blind() -> None:
    """strategy="ei" 对 cost 置乱不变（cost-blind 语义钉）。"""
    cfg = EIPUConfig(seed=5)
    cost_a = np.array([1.0, 1.0, 50.0, 50.0])
    cost_b = cost_a[::-1].copy()
    pick_a, _ = suggest_next_point(_MECH_X, _MECH_Y, cost_a, BOUNDS_1D,
                                   strategy="ei", config=cfg)
    pick_b, _ = suggest_next_point(_MECH_X, _MECH_Y, cost_b, BOUNDS_1D,
                                   strategy="ei", config=cfg)
    assert pick_a == pick_b
    # cost=None 亦合法（ei 不需要 cost）
    pick_c, _ = suggest_next_point(_MECH_X, _MECH_Y, None, BOUNDS_1D,
                                   strategy="ei", config=cfg)
    assert pick_c == pick_a


# ── 环裁判：等预算 A/B（判据预声明见模块 docstring）──────────────────────

def _referee_f(p: dict[str, float]) -> float:
    x = p["x"]
    return float(-0.62 * math.exp(-((x - 0.82) / 0.18) ** 2)
                 - 0.50 * math.exp(-((x - 0.18) / 0.18) ** 2))


def _referee_cost(p: dict[str, float]) -> float:
    return 1.0 if p["x"] <= 0.5 else 50.0


_REF_INIT = [{"x": 0.48}, {"x": 0.58}]
_REF_ITERS = 10
_REF_BUDGET = 110.0
_REF_SEEDS = tuple(range(7))
#: 预声明门（原型 7/7 实测后冻结）：EIpu 优于纯 EI ≥6/7；命中廉价谷 ≥6/7
_REF_WIN_MIN = 6
_REF_HIT_MIN = 6


def _budget_truncated_best_f(traj: dict) -> float:
    """预算截断 best-f：累计代价 ≤BUDGET 的末个 trial 的 best_f。"""
    bf = None
    for c, b in zip(traj["cum_cost"], traj["best_f_history"], strict=True):
        if c <= _REF_BUDGET:
            bf = b
    if bf is None:
        bf = traj["best_f_history"][0]
    return float(bf)


def test_loop_budget_referee_eipu_beats_ei() -> None:
    """等预算 A/B（7 seeds）：EIpu 优于纯 EI ≥6/7 且命中廉价谷 ≥6/7。"""
    wins = 0
    hits = 0
    detail = []
    for seed in _REF_SEEDS:
        cfg = EIPUConfig(seed=seed)
        t_eipu = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D,
                               n_iters=_REF_ITERS, strategy="eipu",
                               config=cfg, init_points=_REF_INIT)
        t_ei = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D,
                             n_iters=_REF_ITERS, strategy="ei",
                             config=cfg, init_points=_REF_INIT)
        bf_eipu = _budget_truncated_best_f(t_eipu)
        bf_ei = _budget_truncated_best_f(t_ei)
        win = bf_eipu < bf_ei
        hit = bf_eipu <= -0.45
        wins += int(win)
        hits += int(hit)
        detail.append((seed, bf_eipu, bf_ei))
    assert wins >= _REF_WIN_MIN, f"EIpu 胜场不足: {wins}/{len(_REF_SEEDS)} {detail}"
    assert hits >= _REF_HIT_MIN, (
        f"EIpu 廉价谷命中不足: {hits}/{len(_REF_SEEDS)} {detail}")


def test_loop_determinism_same_seed() -> None:
    """同 seed 两遍轨迹逐位一致（确定性红线）。"""
    cfg = EIPUConfig(seed=11)
    t1 = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D,
                       n_iters=4, strategy="eipu", config=cfg,
                       init_points=_REF_INIT)
    t2 = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D,
                       n_iters=4, strategy="eipu", config=cfg,
                       init_points=_REF_INIT)
    assert t1 == t2


def test_loop_bounds_respected() -> None:
    """建议点全部落在参数盒内（BO 循环约束）。"""
    cfg = EIPUConfig(seed=13)
    traj = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D,
                         n_iters=5, strategy="eipu", config=cfg)
    assert traj["strategy"] == "eipu"
    for t in traj["trials"]:
        assert 0.0 <= t["params"]["x"] <= 1.0
    # 记账面：cum_cost 与 budget_used 自洽
    assert traj["budget_used"] == pytest.approx(traj["cum_cost"][-1])
    best = min(t["y"] for t in traj["trials"])
    assert traj["best_f_history"][-1] == pytest.approx(best)


# ── 校验面 ────────────────────────────────────────────────────────────────

def _obs(n: int = 4) -> tuple[np.ndarray, np.ndarray]:
    x = np.linspace(0.1, 0.9, n).reshape(-1, 1)
    y = np.array([-0.2, -0.35, -0.4, -0.45][:n])
    return x, y


def test_suggest_validation() -> None:
    x, y = _obs()
    cfg = EIPUConfig(seed=0)
    with pytest.raises(ValueError, match="未知 strategy"):
        suggest_next_point(x, y, np.ones(4), BOUNDS_1D, strategy="ucb",
                           config=cfg)
    with pytest.raises(ValueError, match="形状不一致"):
        suggest_next_point(x.T, y, np.ones(4), BOUNDS_1D, config=cfg)
    with pytest.raises(ValueError, match="至少需要 2"):
        suggest_next_point(x[:1], y[:1], np.ones(1), BOUNDS_1D, config=cfg)
    with pytest.raises(ValueError, match=r"eipu.*cost|cost"):
        suggest_next_point(x, y, None, BOUNDS_1D, strategy="eipu", config=cfg)
    for bad in (np.array([0.0, 1.0, 50.0, -1.0]),   # 非正
                np.array([1.0, np.nan, 50.0, 1.0]),  # 非有限
                np.ones(3)):                          # 长度不符
        with pytest.raises(ValueError, match="cost"):
            suggest_next_point(x, y, bad, BOUNDS_1D, strategy="eipu",
                               config=cfg)
    with pytest.raises(ValueError, match="不一致"):
        suggest_next_point(x, y, np.ones(4), {"x": (0, 1), "z": (0, 1)},
                           config=cfg)


def test_loop_init_points_validation() -> None:
    with pytest.raises(ValueError, match="缺参数"):
        run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D, n_iters=1,
                      init_points=[{"y": 0.5}])


# ── 观测空间饱和显式信号（P3-2）──────────────────────────────────────────

def test_suggest_full_dedup_returns_saturated_signal() -> None:
    """候选全被已评估点去重 → params=None + diag.saturated=True。

    触发构造：候选池（seed 确定性）与已观测点逐点重合——原实现 argmax
    对全 -inf 静默返回索引 0（重复观测点，零信息）；修复后显式信号。
    """
    cfg = EIPUConfig(seed=42, n_candidates=4)
    rng = np.random.default_rng(42)  # 与 _candidate_pool 同源同序
    cands = rng.uniform(0.0, 1.0, 4).reshape(-1, 1)
    y = np.array([-0.10, -0.20, -0.15, -0.25])
    cost = np.array([1.0, 2.0, 1.5, 2.5])
    params, diag = suggest_next_point(cands, y, cost, BOUNDS_1D,
                                      strategy="eipu", config=cfg)
    assert params is None
    assert diag["saturated"] is True
    assert diag["n_deduped"] == 4
    # 正常路径 diag 显式带 saturated=False（形态钉，消费方可统一判键）
    _, diag_ok = suggest_next_point(_MECH_X, _MECH_Y, _MECH_C, BOUNDS_1D,
                                    strategy="eipu", config=EIPUConfig(seed=0))
    assert diag_ok["saturated"] is False
    assert diag_ok["n_deduped"] == 0


def test_loop_breaks_on_saturation() -> None:
    """观测空间饱和 → 循环提前停 + saturated 标记（不重复评估已观测点）。"""
    cfg = EIPUConfig(seed=7, n_candidates=2)
    rng = np.random.default_rng(7)
    init = [{"x": float(c)} for c in rng.uniform(0.0, 1.0, 2)]
    traj = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D, n_iters=3,
                         strategy="eipu", config=cfg, init_points=init)
    assert traj["saturated"] is True
    assert len(traj["trials"]) == 2  # 只有 init 两点，零重复评估
    # 正常环：saturated=False 且跑满 n_iters
    traj_ok = run_eipu_loop(_referee_f, _referee_cost, BOUNDS_1D, n_iters=2,
                            strategy="eipu", config=EIPUConfig(seed=8),
                            init_points=_REF_INIT)
    assert traj_ok["saturated"] is False
    assert len(traj_ok["trials"]) == len(_REF_INIT) + 2


# ── R9 排序承诺件 ─────────────────────────────────────────────────────────

def test_commitment_order_ranks_sensitive_first() -> None:
    """R9：高敏感先钉死；平局按参数名升序（稳定可复现）。"""
    out = commitment_order({"er": 0.31, "h": 0.87, "w": 0.31, "l": 0.02})
    assert [d["param"] for d in out] == ["h", "er", "w", "l"]
    assert [d["rank"] for d in out] == [1, 2, 3, 4]
    assert out[0]["score"] == pytest.approx(0.87)
    # 返回结构为 JSON 安全纯值
    for d in out:
        assert set(d) == {"rank", "param", "score"}


def test_commitment_order_rejects_bad_scores() -> None:
    with pytest.raises(ValueError, match="为空"):
        commitment_order({})
    with pytest.raises(ValueError, match="有限"):
        commitment_order({"a": float("nan")})
    with pytest.raises(ValueError, match="≥0"):
        commitment_order({"a": -0.1})
    with pytest.raises(ValueError, match="str"):
        commitment_order({1: 0.5})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="有限"):
        commitment_order({"a": True})  # type: ignore[dict-item] —— bool 显式拒收
    # str 数字显式拒收（P3-1）：float("0.9") 会静默接受字符串数字
    for bad_str in ("0.9", "3", "1e-3"):
        with pytest.raises(ValueError, match="拒收"):
            commitment_order({"a": bad_str})  # type: ignore[dict-item]
