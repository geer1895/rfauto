"""mcts_search：MCTS + 代理值函数的设计搜索（阶段 7.3 首片）。

从游戏 AI（AlphaGo 系）借：把调参建模为"设计步"序列（每步一个有界
修改，如 arm_len +0.3mm），值函数 = 校准代理预测的 cost，UCT 选择 +
种子化随机 rollout——与 Optuna 的无模型逐点采样本质不同，捕捉的是
"调参路径"的顺序结构。

确定性内核：代理即值函数（无学习组件），rollout 用种子
化随机游走；合成数据自博弈（fake 伪轨迹训策略）留待 7.4 飞轮语料
就位后的增量。
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

_UCB_C = 1.4142135623730951  # sqrt(2)


class _Node:
    """搜索树节点：状态 = 归一化参数向量 [0,1]^d。"""

    __slots__ = ("children", "move", "parent", "value", "vec", "visits")

    def __init__(self, vec: list[float],
                 move: tuple[int, float] | None = None,
                 parent: _Node | None = None) -> None:
        self.vec = vec
        self.visits = 0
        self.value = 0.0
        self.children: list[_Node] = []
        self.move = move
        self.parent = parent


def mcts_search(
    samples_path: str | Path,
    *,
    n_simulations: int = 200,
    n_steps: int = 6,
    step_size: float = 0.1,
    kind: str = "poly_ridge",
    seed: int = 42,
) -> dict[str, Any]:
    """从样本集最优点出发做 MCTS 定向序列探索。

    值函数 = 校准代理（samples.json 训练）预测 cost（越低越好）；
    选择用 UCT，扩展走法 = 每轴 ±step_size（越界走法不生成），rollout
    为种子化随机游走。返回最优末端状态、路径与代理预测。
    """
    import numpy as np

    from rfauto.service.calibration_service import _make_model

    path = Path(samples_path)
    if not path.exists():
        return {"ok": False, "errors": [f"样本集不存在: {path}"]}
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = list(data.get("samples") or [])
    bounds_raw = data.get("bounds") or {}
    if len(samples) < 5:
        return {"ok": False, "errors": ["样本点不足（需 ≥5）"]}
    bounds = {k: (float(v[0]), float(v[1])) for k, v in bounds_raw.items()}
    names = sorted(bounds)
    lower = [bounds[n][0] for n in names]
    span = [max(bounds[n][1] - bounds[n][0], 1e-12) for n in names]

    model = _make_model(kind, bounds, order=2, ridge_lambda=0.1)
    model.fit(samples)

    def predict_cost(vec: list[float]) -> float:
        params = {n: lower[i] + vec[i] * span[i] for i, n in enumerate(names)}
        try:
            pred = model.predict(params)
        except Exception:
            return math.inf
        vals = [float(v) for v in pred.values()
                if isinstance(v, (int, float))]
        return sum(vals) / len(vals) if vals else math.inf

    def norm_of(s: dict[str, Any]) -> list[float]:
        return [min(max((float(s["params"][n]) - lower[i]) / span[i], 0.0), 1.0)
                for i, n in enumerate(names)]

    best = min(samples, key=lambda s: float(
        s.get("cost") if s.get("cost") is not None else math.inf))
    root = _Node(norm_of(best))

    rng = np.random.default_rng(seed)
    moves = [(i, sign * step_size) for i in range(len(names))
             for sign in (-1.0, 1.0)]

    def legal_moves(vec: list[float]) -> list[tuple[int, float]]:
        return [(i, d) for i, d in moves if 0.0 <= vec[i] + d <= 1.0]

    best_cost = predict_cost(root.vec)
    best_vec, best_seq = list(root.vec), []
    for _ in range(int(n_simulations)):
        node = root
        seq: list[tuple[int, float]] = []
        depth = 0
        # ① UCT 选择 + ② 扩展（每模拟至多扩一个新节点）
        while depth < n_steps:
            legal = legal_moves(node.vec)
            if not legal:
                break
            tried = {c.move for c in node.children}
            untried = [m for m in legal if m not in tried]
            if untried:
                i, d = untried[int(rng.integers(len(untried)))]
                nv = list(node.vec)
                nv[i] = min(max(nv[i] + d, 0.0), 1.0)
                child = _Node(nv, move=(i, d), parent=node)
                node.children.append(child)
                node = child
                seq.append((i, d))
                depth += 1
                break
            node = max(
                node.children,
                key=lambda c: (c.value / c.visits
                               + _UCB_C * math.sqrt(
                                   math.log(max(node.visits, 1))
                                   / max(c.visits, 1))))
            seq.append(node.move)  # type: ignore[arg-type]
            depth += 1
        # ③ rollout：随机游走补满剩余步数
        roll_vec = list(node.vec)
        while depth < n_steps:
            legal = legal_moves(roll_vec)
            if not legal:
                break
            i, d = legal[int(rng.integers(len(legal)))]
            roll_vec[i] = min(max(roll_vec[i] + d, 0.0), 1.0)
            depth += 1
        value = predict_cost(roll_vec)
        # ④ 回传（cost 越低越好 → 节点值累计负 cost）
        cur: _Node | None = node
        while cur is not None:
            cur.visits += 1
            cur.value += -value
            cur = cur.parent
        if value < best_cost:
            best_cost = value
            best_vec = list(node.vec)
            best_seq = list(seq)

    params = {n: round(lower[i] + best_vec[i] * span[i], 6)
              for i, n in enumerate(names)}
    return {
        "ok": True,
        "samples_path": str(path),
        "surrogate_kind": kind,
        "n_simulations": n_simulations,
        "n_steps": n_steps,
        "root_cost_pred": round(predict_cost(root.vec), 6),
        "best_cost_pred": round(best_cost, 6),
        "best_params": params,
        "best_path_moves": [
            {"param": names[i], "delta_norm": round(d, 3)}
            for i, d in best_seq],
        "note": "值函数=校准代理预测；路径候选需真机复核（置信度归 gate）",
    }


# ─── 通用离散 MCTS（E14：UCB1 选择/扩展/回传 + 可注入动作/奖励）───────────────
# 与上面的代理搜索共用 UCB1 常数，但状态/动作/奖励完全由调用方注入：合成离散
# 问题（K 臂老虎机、网格最短路）与 C13 滤波器阶数选择都走同一条搜索内核。
# 数值只在确定性评估器（调用方传入）内产生，本层不造物理数字。


class _PlanNode:
    """通用 MCTS 节点：``state`` 任意（可哈希则缓存评估），动作须可哈希。"""

    __slots__ = ("action", "children", "parent", "reward_sum", "state", "tried",
                 "visits")

    def __init__(self, state: Any, parent: _PlanNode | None = None,
                 action: Any = None) -> None:
        self.state = state
        self.parent = parent
        self.action = action
        self.children: list[_PlanNode] = []
        self.visits = 0
        self.reward_sum = 0.0
        self.tried: set[Any] = set()

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.visits if self.visits else 0.0


def _ucb1(mean_reward: float, visits: int, parent_visits: int,
          c: float = _UCB_C) -> float:
    """UCB1 分数：未访问子节点 = +inf（保证先探索再利用）。

    ``mean_reward + c·sqrt(ln(parent_visits)/visits)``；奖励口径为
    「越大越好」，调用方负责把 cost 取负后再传入。
    """
    if visits <= 0:
        return math.inf
    return mean_reward + c * math.sqrt(
        math.log(max(int(parent_visits), 1)) / visits)


def mcts_plan(
    root_state: Any,
    actions: Callable[[Any], Iterable[Any]],
    transition: Callable[[Any, Any], Any],
    evaluate: Callable[[Any], float],
    *,
    n_simulations: int = 200,
    max_depth: int = 10,
    seed: int = 42,
    ucb_c: float = _UCB_C,
    is_terminal: Callable[[Any], bool] | None = None,
) -> dict[str, Any]:
    """通用离散 MCTS：UCB1 选择 + 每模拟至多一次扩展 + rollout + 回传。

    参数（全部可注入，不依赖任何物理内核）：

    - ``actions(state)``：合法动作序列（动作须可哈希）；
    - ``transition(state, action)``：状态转移（应为纯函数）；
    - ``evaluate(state)``：状态奖励，**越大越好**（确定性评估器提供）；
    - ``is_terminal(state)``：终态判定（缺省全部非终态）；
    - ``n_simulations`` / ``max_depth``：预算与深度上限；
    - ``seed``：未扩展动作顺序与 rollout 的种子（同种子逐位可复现）。

    搜索语义：每个模拟沿 UCB1 下钻到首个尚有未扩展动作的节点，扩展一个新
    节点并**立即评估该节点状态**（故树内每个状态都参与最优追踪，不论
    rollout 去向），再从新节点用随机策略 rollout 到深度上限，把 rollout
    叶奖励回传到根。返回最优状态、根到最优的动作策略与统计量。
    """
    for name, fn in (("actions", actions), ("transition", transition),
                     ("evaluate", evaluate)):
        if not callable(fn):
            raise TypeError(f"{name} 必须是可调用对象，当前 {type(fn).__name__}")
    n_simulations = int(n_simulations)
    max_depth = int(max_depth)
    if n_simulations < 1:
        raise ValueError(f"n_simulations 必须 ≥1，当前 {n_simulations}")
    if max_depth < 1:
        raise ValueError(f"max_depth 必须 ≥1，当前 {max_depth}")
    if not math.isfinite(ucb_c) or ucb_c < 0:
        raise ValueError(f"ucb_c 必须为有限非负数，当前 {ucb_c}")

    rng = random.Random(seed)
    _miss = object()

    def key_of(state: Any) -> Any:
        try:
            hash(state)
        except TypeError:
            return _miss
        return state

    cache: dict[Any, float] = {}
    n_evaluations = 0

    def score(state: Any) -> float:
        nonlocal n_evaluations
        k = key_of(state)
        if k is not _miss and k in cache:
            return cache[k]
        n_evaluations += 1
        value = float(evaluate(state))
        if k is not _miss:
            cache[k] = value
        return value

    terminal = is_terminal if is_terminal is not None else (lambda _s: False)

    root = _PlanNode(root_state)
    best_state: Any = root_state
    best_reward = score(root_state)
    best_node = root
    best_suffix: list[Any] = []
    n_nodes = 1
    max_depth_reached = 0

    for _ in range(n_simulations):
        node = root
        depth = 0
        # ① 选择 + ② 扩展（每个模拟至多扩一个新节点）
        while depth < max_depth and not terminal(node.state):
            moves = list(actions(node.state))
            untried = [a for a in moves if a not in node.tried]
            if untried:
                action = untried[rng.randrange(len(untried))]
                child = _PlanNode(transition(node.state, action), parent=node,
                                  action=action)
                node.tried.add(action)
                node.children.append(child)
                node = child
                n_nodes += 1
                depth += 1
                reward = score(node.state)
                if reward > best_reward:
                    best_reward, best_state = reward, node.state
                    best_node, best_suffix = node, []
                break
            if not node.children:
                break
            node = max(node.children, key=lambda c: _ucb1(
                c.mean_reward, c.visits, node.visits, ucb_c))
            depth += 1
        # ③ rollout：随机策略补满剩余深度（记录后缀动作，保证策略可复现叶状态）
        state = node.state
        rollout_actions: list[Any] = []
        rollout_depth = depth
        while rollout_depth < max_depth and not terminal(state):
            moves = list(actions(state))
            if not moves:
                break
            action = moves[rng.randrange(len(moves))]
            state = transition(state, action)
            rollout_actions.append(action)
            rollout_depth += 1
        max_depth_reached = max(max_depth_reached, rollout_depth)
        rollout_reward = score(state)
        if rollout_reward > best_reward:
            best_reward, best_state = rollout_reward, state
            best_node, best_suffix = node, list(rollout_actions)
        # ④ 回传（奖励越大越好，直接累计）
        cur: _PlanNode | None = node
        while cur is not None:
            cur.visits += 1
            cur.reward_sum += rollout_reward
            cur = cur.parent

    prefix: list[Any] = []
    cur = best_node
    while cur is not None and cur.parent is not None:
        prefix.append(cur.action)
        cur = cur.parent
    prefix.reverse()
    policy: list[Any] = prefix + best_suffix

    return {
        "ok": True,
        "best_state": best_state,
        "best_reward": best_reward,
        "best_policy": policy,
        "n_simulations": n_simulations,
        "n_simulations_used": n_simulations,
        "n_nodes": n_nodes,
        "n_evaluations": n_evaluations,
        "max_depth": max_depth,
        "max_depth_reached": max_depth_reached,
        "ucb_c": ucb_c,
        "seed": seed,
        "root_visits": root.visits,
        "root_mean_reward": root.mean_reward,
        "root_children": [
            {"action": c.action, "visits": c.visits,
             "mean_reward": c.mean_reward}
            for c in sorted(root.children, key=lambda c: -c.visits)],
    }


# ─── E14 × C13：滤波器阶数选择（coupling_matrix 内核作确定性评估器）──────────


def _omega_band_edge_freq(f0_ghz: float, fbw: float, omega: float) -> float:
    """Ω=(f/f0−f0/f)/fbw 的反解：给 Ω 返回正频率带缘。

    由 Ω·fbw·f0·f = f²−f0² 得二次式 f² − Ω·fbw·f0·f − f0² = 0，取正根。
    """
    b = -omega * fbw * f0_ghz
    disc = b * b + 4.0 * f0_ghz * f0_ghz
    return (-b + math.sqrt(disc)) / 2.0


def filter_order_search(
    *,
    f0_ghz: float,
    fbw: float,
    min_return_loss_db: float = 20.0,
    stopband_freq_ghz: float | None = None,
    min_stopband_rejection_db: float | None = None,
    min_order: int = 1,
    max_order: int = 8,
    design_rl_db: float | None = None,
    transmission_zeros: list[float] | None = None,
    freq_ghz: list[float] | None = None,
    n_simulations: int = 200,
    max_depth: int | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """在给定指标下用 MCTS 选滤波器阶数 N（评估器 = 已入库 C13 内核）。

    评估器：``coupling_matrix_synthesize_n2``（阶数+回损→N+2 矩阵）→
    ``coupling_matrix_response``（带内 S11 / 阻带 S21）。奖励越大越好：

    - 同时满足带内最小回波损耗与阻带最小抑制 → ``1 + (max_order−N)/max_order``
      （可行解中阶数越低越优 ⇒ 最优 = 最小可行阶数）；
    - 否则 = 负的指标亏欠（dB），据此朝可行方向搜索；全不可行时返回亏欠最小者。

    返回 ``best_order``、``best_metrics``、``feasible``、逐阶 ``evaluated_orders``、
    folded 拓扑可实现性 ``realizability``，以及底层 ``search`` 统计。非法参数
    不抛出，返回 ``{"ok": False, "errors": [...]}``（服务层 JSON 口径）。
    """
    errors: list[str] = []
    f0 = float(f0_ghz)
    bw = float(fbw)
    if not math.isfinite(f0) or f0 <= 0:
        errors.append(f"f0_ghz 必须为正有限值，当前 {f0_ghz}")
    if not math.isfinite(bw) or not 0 < bw <= 1:
        errors.append(f"fbw 须在 (0,1]，当前 {fbw}")
    lo, hi = int(min_order), int(max_order)
    if lo < 1:
        errors.append(f"min_order 必须 ≥1，当前 {lo}")
    if hi < lo:
        errors.append(f"max_order({hi}) 必须 ≥ min_order({lo})")
    rl_floor = float(min_return_loss_db)
    if not math.isfinite(rl_floor) or rl_floor <= 0:
        errors.append(f"min_return_loss_db 必须 >0，当前 {rl_floor}")
    rej_floor = (None if min_stopband_rejection_db is None
                 else float(min_stopband_rejection_db))
    if rej_floor is not None and (not math.isfinite(rej_floor) or rej_floor <= 0):
        errors.append(f"min_stopband_rejection_db 必须 >0，当前 {rej_floor}")
    f_stop = None if stopband_freq_ghz is None else float(stopband_freq_ghz)
    if f_stop is not None and (not math.isfinite(f_stop) or f_stop <= 0):
        errors.append(f"stopband_freq_ghz 必须为正有限值，当前 {f_stop}")
    if rej_floor is not None and f_stop is None:
        errors.append("给定了 min_stopband_rejection_db 但缺 stopband_freq_ghz")
    if int(n_simulations) < 1:
        errors.append(f"n_simulations 必须 ≥1，当前 {n_simulations}")
    if errors:
        return {"ok": False, "errors": errors}

    from rfauto.core.calculators import CALCULATOR_REGISTRY

    synth = CALCULATOR_REGISTRY.get("coupling_matrix_synthesize_n2").func
    resp = CALCULATOR_REGISTRY.get("coupling_matrix_response").func
    design_rl = (float(design_rl_db) if design_rl_db is not None
                 else max(rl_floor, 20.0))
    tz = [float(z) for z in (transmission_zeros or [])]
    if freq_ghz:
        band = [float(f) for f in freq_ghz]
    else:
        f_lo = _omega_band_edge_freq(f0, bw, -1.0)
        f_hi = _omega_band_edge_freq(f0, bw, 1.0)
        band = [f_lo + (f_hi - f_lo) * k / 20.0 for k in range(21)]

    metrics: dict[int, dict[str, Any]] = {}

    def measure(order: int) -> dict[str, Any]:
        if order in metrics:
            return metrics[order]
        out = synth(order=order, rl_db=design_rl, transmission_zeros=list(tz))
        r = resp(freq_ghz=band, f0_ghz=f0, fbw=bw,
                 matrix=out["coupling_matrix"])
        entry: dict[str, Any] = {
            "order": order,
            "synthesis_ok": bool(out["ok"]),
            "worst_return_loss_db": round(-max(r["s11_db"]), 6),
            "min_insertion_loss_db": round(-min(r["s21_db"]), 6),
            "band_ghz": [round(band[0], 9), round(band[-1], 9)],
            "n_band_points": len(band),
            "matrix_shape": out["matrix_shape"],
        }
        if f_stop is not None:
            rs = resp(freq_ghz=[f_stop], f0_ghz=f0, fbw=bw,
                      matrix=out["coupling_matrix"])
            entry["stopband_freq_ghz"] = f_stop
            entry["stopband_rejection_db"] = round(-rs["s21_db"][0], 6)
        metrics[order] = entry
        return entry

    def reward(order: int) -> float:
        m = measure(order)
        deficit = max(0.0, rl_floor - m["worst_return_loss_db"])
        if rej_floor is not None:
            deficit += max(0.0, rej_floor
                           - float(m.get("stopband_rejection_db", 0.0)))
        if deficit <= 0.0:
            return 1.0 + (hi - order) / max(hi, 1)
        return -deficit

    def actions(order: int) -> list[int]:
        return [d for d in (-1, 1) if lo <= order + d <= hi]

    depth_cap = int(max_depth) if max_depth is not None else max(hi - lo + 1, 2)
    search = mcts_plan(
        lo, actions, lambda s, a: s + a, reward,
        n_simulations=int(n_simulations), max_depth=depth_cap, seed=seed)

    best_order = int(search["best_state"])
    best_metrics = measure(best_order)
    feasible = (
        best_metrics["worst_return_loss_db"] >= rl_floor
        and (rej_floor is None
             or float(best_metrics.get("stopband_rejection_db", -math.inf))
             >= rej_floor))

    synth_out = synth(order=best_order, rl_db=design_rl, transmission_zeros=list(tz))
    folded = CALCULATOR_REGISTRY.get("coupling_matrix_folded").func(
        synth_out["coupling_matrix"])

    return {
        "ok": True,
        "best_order": best_order,
        "best_reward": search["best_reward"],
        "feasible": bool(feasible),
        "best_metrics": best_metrics,
        "evaluated_orders": {str(k): metrics[k] for k in sorted(metrics)},
        "realizability": {
            "folded_ok": bool(folded["ok"]),
            "pattern_residual": folded["pattern_residual"],
            "cross_family": folded["cross_family"],
        },
        "spec": {
            "f0_ghz": f0, "fbw": bw, "design_rl_db": design_rl,
            "min_return_loss_db": rl_floor,
            "stopband_freq_ghz": f_stop,
            "min_stopband_rejection_db": rej_floor,
            "min_order": lo, "max_order": hi,
            "transmission_zeros": list(tz),
        },
        "search": search,
        "note": "评估器=coupling_matrix 确定性内核；奖励越大越好，"
                "可行解中阶数越低越优（最优=最小可行阶数）",
    }
