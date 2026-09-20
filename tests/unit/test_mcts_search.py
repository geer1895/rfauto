"""E14 MCTS 设计搜索单测：通用离散 MCTS + C13 滤波器阶数选择端到端。

确定性（无网络 / 无真机）：

- 合成 K 臂老虎机与 4×4 网格最短路用解析已知最优钉住 UCB1 选择/扩展/回传，
  并断言"策略逐步回放 == 返回的最优状态"（策略可复现性）；
- C13 阶数选择用已入库 coupling_matrix 内核作评估器，并以经典切比雪夫闭式
  |S21|²=1/(1+ε²T_N(Ω)²) 独立复算门槛（#118，不赌内核自证）。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.mcts_search import (
    _ucb1,
    filter_order_search,
    mcts_plan,
)

_DIRS = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}
_NEG = -1e9


def _bandit(payoffs):
    """K 臂老虎机：根状态 ()，("arm", i) 为终态，奖励 = 该臂收益。"""

    def actions(_state):
        return list(range(len(payoffs)))

    def transition(_state, action):
        return ("arm", action)

    def evaluate(state):
        if state and state[0] == "arm":
            return float(payoffs[state[1]])
        return _NEG

    return actions, transition, evaluate


def _grid(goal, size=4):
    """4×4 网格：奖励 = −曼哈顿距离（目标处 = 0，为唯一最优）。"""

    def actions(state):
        r, c = state
        return [name for name, (dr, dc) in _DIRS.items()
                if 0 <= r + dr < size and 0 <= c + dc < size]

    def transition(state, action):
        dr, dc = _DIRS[action]
        return (state[0] + dr, state[1] + dc)

    def evaluate(state):
        return -float(abs(state[0] - goal[0]) + abs(state[1] - goal[1]))

    return actions, transition, evaluate


def _replay(transition, start, policy):
    state = start
    for action in policy:
        state = transition(state, action)
    return state


def _chebyshev_rejection_db(order, rl_db, omega):
    """经典全极点切比雪夫阻带抑制（正 dB），独立于内核的闭式裁判。"""
    eps = 1.0 / math.sqrt(10.0 ** (rl_db / 10.0) - 1.0)
    t_prev, t_cur = 1.0, float(omega)
    for _ in range(order - 1):
        t_prev, t_cur = t_cur, 2.0 * omega * t_cur - t_prev
    return 10.0 * math.log10(1.0 + eps * eps * t_cur * t_cur)


# ─── 合成离散问题：已知最优 ─────────────────────────────────────────────────

def test_mcts_plan_bandit_finds_known_best_arm():
    payoffs = [0.2, -0.5, 0.9, 0.35, -0.1]
    best_arm = max(range(len(payoffs)), key=lambda i: payoffs[i])
    a, t, e = _bandit(payoffs)
    out = mcts_plan((), a, t, e, n_simulations=64, max_depth=1, seed=7,
                    is_terminal=lambda s: s != ())
    assert out["ok"] is True
    assert out["best_state"] == ("arm", best_arm)
    assert out["best_reward"] == pytest.approx(payoffs[best_arm])
    assert out["best_policy"] == [best_arm]
    assert out["best_state"] == _replay(t, (), out["best_policy"])


def test_mcts_plan_bandit_ucb1_concentrates_visits_on_best_arm():
    payoffs = [0.2, -0.5, 0.9, 0.35, -0.1]
    best_arm = max(range(len(payoffs)), key=lambda i: payoffs[i])
    worst_arm = min(range(len(payoffs)), key=lambda i: payoffs[i])
    a, t, e = _bandit(payoffs)
    out = mcts_plan((), a, t, e, n_simulations=64, max_depth=1, seed=7,
                    is_terminal=lambda s: s != ())
    visits = {c["action"]: c["visits"] for c in out["root_children"]}
    assert set(visits) == set(range(len(payoffs)))
    assert visits[best_arm] == max(visits.values())
    assert visits[best_arm] > visits[worst_arm]


def test_mcts_plan_grid_reaches_known_goal():
    goal = (3, 3)
    actions, transition, evaluate = _grid(goal)
    out = mcts_plan((0, 0), actions, transition, evaluate,
                    n_simulations=400, max_depth=8, seed=3)
    assert out["best_state"] == goal
    assert out["best_reward"] == pytest.approx(0.0)
    # 策略回放确实到达目标，且不可能短于曼哈顿下界
    assert _replay(transition, (0, 0), out["best_policy"]) == goal
    assert len(out["best_policy"]) >= 6


def test_mcts_plan_grid_success_rate_over_seeds():
    goal = (3, 3)
    actions, transition, evaluate = _grid(goal)
    successes = 0
    for seed in range(20):
        out = mcts_plan((0, 0), actions, transition, evaluate,
                        n_simulations=400, max_depth=8, seed=seed)
        if out["best_state"] == goal:
            successes += 1
    assert successes == 20, f"仅 {successes}/20 个种子到达目标"


# ─── 通用搜索语义：确定性 / 参数校验 / 退化输入 / 统计 ──────────────────────

def test_mcts_plan_same_seed_reproducible():
    def actions(_state):
        return [0, 1, 2]

    def transition(state, action):
        return (state[0] + 1, action)

    def evaluate(state):
        return math.sin(state[1] + 1.0) - 0.1 * state[0]

    kwargs = {"n_simulations": 50, "max_depth": 4, "seed": 11}
    first = mcts_plan((0, 0), actions, transition, evaluate, **kwargs)
    second = mcts_plan((0, 0), actions, transition, evaluate, **kwargs)
    assert first == second


@pytest.mark.parametrize("kwargs, match", [
    ({"n_simulations": 0}, "n_simulations"),
    ({"max_depth": 0}, "max_depth"),
    ({"ucb_c": -1.0}, "ucb_c"),
    ({"ucb_c": math.inf}, "ucb_c"),
])
def test_mcts_plan_invalid_params_raise(kwargs, match):
    a, t, e = _bandit([1.0])
    with pytest.raises(ValueError, match=match):
        mcts_plan((), a, t, e, **kwargs)


def test_mcts_plan_non_callable_raises_type_error():
    with pytest.raises(TypeError, match="actions"):
        mcts_plan((), None, lambda s, a: s, lambda s: 0.0)


def test_mcts_plan_empty_actions_degenerate():
    out = mcts_plan("only", lambda _s: [], lambda s, _a: s, lambda _s: 0.5,
                    n_simulations=10, max_depth=3, seed=1)
    assert out["ok"] is True
    assert out["n_nodes"] == 1
    assert out["best_state"] == "only"
    assert out["best_reward"] == pytest.approx(0.5)
    assert out["best_policy"] == []
    assert out["root_visits"] == 10
    assert out["n_evaluations"] == 1
    assert out["root_children"] == []


def test_mcts_plan_single_simulation_returns_policy():
    a, t, e = _bandit([0.1, 0.9, 0.5])
    out = mcts_plan((), a, t, e, n_simulations=1, max_depth=1, seed=0,
                    is_terminal=lambda s: s != ())
    assert out["n_simulations_used"] == 1
    assert out["n_nodes"] == 2
    assert out["root_visits"] == 1
    assert len(out["best_policy"]) == 1
    assert out["best_state"] == ("arm", out["best_policy"][0])


def test_ucb1_formula_and_unvisited_priority():
    assert _ucb1(0.0, 0, 10) == math.inf
    c = 2.0
    assert _ucb1(0.5, 4, 100, c) == pytest.approx(
        0.5 + c * math.sqrt(math.log(100) / 4))
    # 未访问优先于任何已访问（哪怕均值极高）
    assert _ucb1(1e9, 0, 1) > _ucb1(1e9, 1, 1)
    # 同父下访问更少的子节点探索项更大
    assert _ucb1(0.0, 1, 100) > _ucb1(0.0, 25, 100)


def test_mcts_plan_backprop_visits_and_evaluation_cache():
    a, t, e = _bandit([0.3, 0.8, 0.5, 0.1])
    out = mcts_plan((), a, t, e, n_simulations=40, max_depth=1, seed=5,
                    is_terminal=lambda s: s != ())
    assert out["root_visits"] == 40
    assert sum(c["visits"] for c in out["root_children"]) == out["root_visits"]
    # 状态可哈希 → 评估缓存命中：4 臂 + 根 = 5 次
    assert out["n_evaluations"] == 5


def test_mcts_plan_respects_max_depth():
    def actions(state):
        return [d for d in (-1, 1) if 0 <= state + d <= 20]

    out = mcts_plan(0, actions, lambda s, a: s + a, lambda s: float(s),
                    n_simulations=60, max_depth=3, seed=2)
    assert out["max_depth_reached"] <= 3
    assert len(out["best_policy"]) <= 3
    assert out["best_reward"] <= 3.0
    assert out["best_state"] <= 3
    assert _replay(lambda s, a: s + a, 0, out["best_policy"]) == out["best_state"]


def test_mcts_plan_supports_unhashable_state():
    def actions(state):
        return [1] if state["n"] < 5 else []

    def transition(state, action):
        return {"n": state["n"] + action}

    def evaluate(state):
        return float(state["n"])

    out = mcts_plan({"n": 0}, actions, transition, evaluate,
                    n_simulations=20, max_depth=5, seed=4)
    assert out["best_state"] == {"n": 5}
    assert out["best_reward"] == pytest.approx(5.0)
    assert out["n_evaluations"] > 1  # 不可哈希 → 无缓存，逐次评估


# ─── C13 端到端：coupling_matrix 内核作评估器选阶数 ─────────────────────────

def test_filter_order_search_selects_minimal_feasible_order():
    f0, fbw, f_stop = 2.0, 0.1, 2.5
    rl_floor, rej_floor = 19.0, 40.0
    out = filter_order_search(
        f0_ghz=f0, fbw=fbw, stopband_freq_ghz=f_stop,
        min_return_loss_db=rl_floor,
        min_stopband_rejection_db=rej_floor,
        max_order=8, n_simulations=200, seed=42)
    assert out["ok"] is True
    assert out["best_order"] == 4
    assert out["feasible"] is True
    metrics = out["best_metrics"]
    assert metrics["worst_return_loss_db"] >= rl_floor
    assert metrics["stopband_rejection_db"] >= rej_floor
    # 低阶评估结果确实不达阻带门槛 → 4 是最小可行阶数
    for order in (1, 2, 3):
        assert out["evaluated_orders"][str(order)][
            "stopband_rejection_db"] < rej_floor
    # 独立裁判（#118）：经典切比雪夫闭式复算 Ω=4.5 处抑制
    omega = (f_stop / f0 - f0 / f_stop) / fbw
    assert omega == pytest.approx(4.5, abs=1e-12)
    assert _chebyshev_rejection_db(3, 20.0, omega) < rej_floor
    assert _chebyshev_rejection_db(4, 20.0, omega) >= rej_floor
    assert metrics["stopband_rejection_db"] == pytest.approx(
        _chebyshev_rejection_db(4, 20.0, omega), abs=0.05)


def test_filter_order_search_invalid_spec_returns_errors():
    out = filter_order_search(f0_ghz=-1.0, fbw=0.0, min_order=0, max_order=-2,
                              min_return_loss_db=0.0, n_simulations=0)
    assert out["ok"] is False
    assert len(out["errors"]) >= 4
    missing = filter_order_search(f0_ghz=2.0, fbw=0.1,
                                  min_stopband_rejection_db=40.0)
    assert missing["ok"] is False
    assert any("stopband_freq_ghz" in e for e in missing["errors"])


def test_filter_order_search_infeasible_reports_deficit():
    out = filter_order_search(
        f0_ghz=2.0, fbw=0.1, stopband_freq_ghz=2.5,
        min_return_loss_db=19.0, min_stopband_rejection_db=200.0,
        max_order=2, n_simulations=40, seed=1)
    assert out["ok"] is True
    assert out["feasible"] is False
    assert out["best_reward"] < 0.0
    assert out["best_order"] == 2  # 抑制最强（亏欠最小）的最高阶
    best_rej = max(e["stopband_rejection_db"]
                   for e in out["evaluated_orders"].values())
    assert out["best_metrics"]["stopband_rejection_db"] == pytest.approx(best_rej)


def test_filter_order_search_same_seed_reproducible():
    kwargs = dict(f0_ghz=2.0, fbw=0.1, stopband_freq_ghz=2.5,
                  min_return_loss_db=19.0,
                  min_stopband_rejection_db=40.0,
                  max_order=8, n_simulations=60, seed=9)
    first = filter_order_search(**kwargs)
    second = filter_order_search(**kwargs)
    assert first == second


def test_filter_order_search_reports_folded_topology_realizability():
    out = filter_order_search(
        f0_ghz=2.0, fbw=0.1, stopband_freq_ghz=2.5,
        min_return_loss_db=19.0, min_stopband_rejection_db=40.0,
        max_order=8, n_simulations=120, seed=42)
    realiz = out["realizability"]
    assert realiz["folded_ok"] is True
    assert realiz["pattern_residual"] <= 1e-9
    assert realiz["cross_family"] == "none"  # 全极点 → 无交叉耦合族
