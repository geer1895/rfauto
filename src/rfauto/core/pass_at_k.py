"""pass_at_k：pass@k / pass^k 无偏估计纯函数内核（AD-4 接线批，round15 规格）。

规格出处：研究扩充 round15 AD-4「evaluate_agentbench_
consistency CLI/MCP 暴露，k=3 进月门」（round14 AI 补强条同口径「agent_bench
pass^k 接线（与 AD-4 合并）」）。service/agent_bench.py 的
pass_hat_k/evaluate_agentbench_consistency 是既有纯内核（零接线），本模块为
core 侧配套估计面——**分层约束**：core 禁 import service（import-linter），
故 pass^k（METR 口径）在 core 内镜像为 :func:`pass_at_k_all`，与
agent_bench.pass_hat_k 逐位同式，由测试对钉（只读 import 比对，不改其语义）。

两个口径并存、语义不同、禁混称：

- **pass@k**（HumanEval/Codex 口径，本模块主口径）：k 次独立尝试**至少
  一次**通过的概率，无偏组合式估计 ``1 − C(n−c, k)/C(n, k)``（n=尝试数、
  c=通过数、k≤n）。含义：从 n 次尝试的无放回 k 子集中恰含 ≥1 次通过的
  比例，是"再跑 k 次至少成一次"的无偏估计。
- **pass^k**（METR 口径，:func:`pass_at_all` 别名 :func:`pass_at_k_all`）：
  k 次独立尝试**全部**通过的概率，无偏估计 ``C(c, k)/C(n, k)``——
  agent_bench.evaluate_agentbench_consistency 的 pass_hat_k 即此口径。

经验档（:func:`pass_at_k_empirical`）：对 trial 级 0/1 通过序列做 MC 无放回
抽 k 子集的"至少一过"频率——收敛到解析 pass@k，作独立来源数值交叉锚
（#118：估计量的裁判是独立来源，不是自己的推导）。

消费面（:func:`pass_at_k_from_rows`）：只读消费
agent_bench.evaluate_agentbench_consistency 产出的 per-task 行
（``{"id", "n_trials", "n_pass", ...}``）——不修改输入（#316 多报方向：
不可估行如实列 reasons，不静默丢）。

铁律 7：本模块只做概率换算，零网络、零全局随机态（经验档 RNG 由 seed
参数注入、确定性可复现），不产生任何物理数字。
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "pass_at_k",
    "pass_at_k_all",
    "pass_at_k_empirical",
    "pass_at_k_from_rows",
]

ROW_SCHEMA_VERSION = 1


def _require_counts(n_pass: int, n_trials: int, k: int) -> None:
    """fail-closed 计数校验（镜像 agent_bench.pass_hat_k 拒收面）。

    bool/非整数、n_trials<1、k 出界 [1, n_trials]（**含 n<k**）、n_pass 出界
    [0, n_trials] 一律 ValueError——绝不做"看起来合理"的夹持。
    """
    for name, v in (("n_pass", n_pass), ("n_trials", n_trials), ("k", k)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"{name} 必须是 int（拒 bool），得 {v!r}")
    if n_trials < 1:
        raise ValueError(f"n_trials 必须 ≥1，得 {n_trials}")
    if not 1 <= k <= n_trials:
        raise ValueError(
            f"k 必须在 [1, n_trials]=[1, {n_trials}] 内（n≥k），得 {k}")
    if not 0 <= n_pass <= n_trials:
        raise ValueError(f"n_pass 必须在 [0, {n_trials}] 内，得 {n_pass}")


def pass_at_k(n_pass: int, n_trials: int, k: int) -> float:
    """无偏 pass@k（HumanEval/Codex 口径）：``1 − C(n−c, k)/C(n, k)``。

    锚例（tests/unit/test_pass_at_k.py 预声明）：

    - pass_at_k(3, 5, 2) = 1 − C(2,2)/C(5,2) = 1 − 1/10 = 0.9；
    - c=n（全过）→ 1.0；c=0 → 0.0；k=1 退化为通过率 c/n；
    - k=n → c≥1 时 1.0（n 个全取必含通过），c=0 时 0.0；
    - C(n−c,k) 在 k>n−c 时组合式恒 0（任取 k 个必含通过）→ 1.0，自洽。

    数值面：math.comb 整数精确计数后单次舍入——Python 大整数真除对
    [0,1] 商不溢出（分子分母各自转 float 才会溢出），任意 n 稳定。

    拒收面（fail-closed）：n<k（含 k 出界）ValueError——n<k 时"至少一过"
    概率恒 1 但样本不足声明，宁可报错不夹持（任务规格显式要求）。
    """
    _require_counts(n_pass, n_trials, k)
    n_fail = n_trials - n_pass
    denom = math.comb(n_trials, k)
    numer = math.comb(n_fail, k)
    if numer == 0:
        return 1.0
    if numer == denom:
        return 0.0
    return 1.0 - numer / denom


def pass_at_k_all(n_pass: int, n_trials: int, k: int) -> float:
    """无偏 pass^k（METR 口径）：``C(c, k)/C(n, k)``。

    与 service.agent_bench.pass_hat_k 同式镜像（core 禁 import service，
    见模块 docstring）；语义="k 次独立重跑全部通过"的无偏估计。
    拒收面与 :func:`pass_at_k` 完全一致。
    """
    _require_counts(n_pass, n_trials, k)
    numer = math.comb(n_pass, k)
    if numer == 0:
        return 0.0
    return numer / math.comb(n_trials, k)


def pass_at_k_empirical(
    passes: Sequence[int | bool], k: int, *,
    n_draws: int = 100_000, seed: int = 0,
) -> float:
    """经验档 pass@k：MC 无放回抽 k 子集的"至少一过"频率。

    对 n 个 trial 的 0/1 通过序列，独立抽 n_draws 个大小 k 的无放回下标
    子集，返回"子集内至少一次通过"的频率——总体比例即解析 pass@k，
    本函数是其 Monte Carlo 交叉锚（标准误 ≈ sqrt(q(1−q)/n_draws)）。
    RNG=random.Random(seed) 确定性可复现（ge1⑦ 固定 rng 惯例）。

    拒收面（fail-closed）：passes 空、元素非 bool/int{0,1}（拒 float/str/
    其他整数）、k 出界 [1, n]、n_draws<1 或非 int——不静默清洗。
    """
    if isinstance(k, bool) or not isinstance(k, int):
        raise ValueError(f"k 必须是 int（拒 bool），得 {k!r}")
    if isinstance(n_draws, bool) or not isinstance(n_draws, int) or n_draws < 1:
        raise ValueError(f"n_draws 必须 ≥1 的 int，得 {n_draws!r}")
    vals: list[bool] = []
    for i, v in enumerate(passes):
        if isinstance(v, bool):
            vals.append(v)
        elif isinstance(v, int) and v in (0, 1):
            vals.append(bool(v))
        else:
            raise ValueError(
                f"passes[{i}] 必须是 0/1/bool，得 {v!r}")
    n = len(vals)
    if n < 1:
        raise ValueError("passes 不得为空")
    if not 1 <= k <= n:
        raise ValueError(f"k 必须在 [1, n]=[1, {n}] 内（n≥k），得 {k}")
    idx = range(n)
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_draws):
        if any(vals[j] for j in rng.sample(idx, k)):
            hits += 1
    return hits / n_draws


def pass_at_k_from_rows(
    rows: Sequence[Mapping[str, Any]], k: int, *,
    min_pass_at_k: float | None = None,
) -> dict[str, Any]:
    """只读消费 per-task pass 记录，算 pass@k 逐任务 + 宏平均 + 门。

    rows 形态=agent_bench.evaluate_agentbench_consistency()["results"]：
    ``[{"id", "n_trials", "n_pass", ...}, ...]``（多余键忽略；输入零改写）。
    k 为任务级尝试数下界只要求 ≥1（逐任务 n≥k 不满足时该行如实不可估）。

    不可估行（#316 多报方向，进 reasons 不静默丢）：

    - n_trials==0 → "任务零 trial 覆盖"（与 service 防空转同语，进 reasons）；
    - 0<n_trials<k → "n<k 不可估"（无偏组合式要求 n≥k）；
    - 行非 Mapping / 缺 n_trials/n_pass / 计数非法 → 逐行列因。

    门面：reasons 非空或无可估行 → gate=FAIL；min_pass_at_k 给定且宏平均
    不达（或不可得）→ FAIL。与 evaluate_agentbench_consistency 契约同构
    （绝不让门空跑绿）。
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError(f"k 必须是 ≥1 的 int（拒 bool），得 {k!r}")
    if min_pass_at_k is not None \
            and (isinstance(min_pass_at_k, bool)
                 or not isinstance(min_pass_at_k, (int, float))
                 or not math.isfinite(float(min_pass_at_k))):
        raise ValueError(f"min_pass_at_k 必须是有限实数，得 {min_pass_at_k!r}")

    results: list[dict[str, Any]] = []
    reasons: list[str] = []
    for pos, row in enumerate(rows):
        rid: Any = row.get("id") if isinstance(row, Mapping) else None
        label = str(rid) if rid is not None else f"<row#{pos}>"
        if not isinstance(row, Mapping):
            reasons.append(f"{label}: 行非 Mapping，不可估")
            continue
        n_trials = row.get("n_trials")
        n_pass = row.get("n_pass")
        if isinstance(n_trials, bool) or not isinstance(n_trials, int) \
                or isinstance(n_pass, bool) or not isinstance(n_pass, int):
            reasons.append(f"{label}: n_trials/n_pass 缺失或非 int，不可估")
            continue
        if n_trials == 0:
            results.append({"id": rid, "n_trials": 0, "n_pass": n_pass,
                            "pass_at_k": None, "error": "任务零 trial 覆盖"})
            continue
        bad = None
        if n_trials < 1:
            bad = f"n_trials={n_trials} 非法（须 ≥1）"
        elif not 0 <= n_pass <= n_trials:
            bad = f"n_pass={n_pass} 出界 [0, {n_trials}]"
        elif n_trials < k:
            bad = f"n_trials={n_trials}<k={k} 不可估（无偏组合式要求 n≥k）"
        if bad is not None:
            reasons.append(f"{label}: {bad}")
            continue
        results.append({"id": rid, "n_trials": n_trials, "n_pass": n_pass,
                        "pass_at_k": pass_at_k(n_pass, n_trials, k)})

    scored = [r for r in results if r.get("pass_at_k") is not None]
    macro = (sum(float(r["pass_at_k"]) for r in scored) / len(scored)
             if scored else None)
    zero_cov = [str(r["id"]) for r in results if r.get("error")]
    if zero_cov:
        reasons.append(
            f"{len(zero_cov)} 个任务零 trial 覆盖 → {zero_cov[:5]}")
    if not scored:
        reasons.append("无任何任务可估 pass@k（防空转）")
    if min_pass_at_k is not None and macro is not None \
            and macro < float(min_pass_at_k):
        reasons.append(
            f"pass@{k} 宏平均 {macro:.4f} < 阈值 {float(min_pass_at_k):.4f}")
    if min_pass_at_k is not None and macro is None:
        reasons.append(f"pass@{k} 宏平均不可得（无可估任务）——门不空跑绿")

    return {
        "ok": not reasons and bool(scored),
        "gate": "PASS" if (not reasons and scored) else "FAIL",
        "schema_version": ROW_SCHEMA_VERSION,
        "k": k,
        "min_pass_at_k": (float(min_pass_at_k)
                          if min_pass_at_k is not None else None),
        "pass_at_k_macro": macro,
        "results": results,
        "reasons": reasons,
    }
