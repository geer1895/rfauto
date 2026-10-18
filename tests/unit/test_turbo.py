"""EC-18 turbo（TuRBO-1）单测：8 维球面合成基准 + 确定性 + 零破坏（全离线）。

合成基准（已知真值回收）：8 维平移球面 argmin=c 闭式已知——同预算
（60 真评）下 TuRBO best cost 显著优于同 seed LHS 随机搜索，best 点
Linf 距离闭式 argmin 收敛；信任域按 TuRBO-1 语义收缩（length_trace）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.stats import qmc

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization import trust_region
from rfauto.optimization import turbo as turbo_mod
from rfauto.optimization.turbo import run_turbo

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

D = 8
C_TRUE = np.array([0.71, 0.19, 0.83, 0.40, 0.62, 0.15, 0.90, 0.55])
BOUNDS = {f"x{i}": (0.0, 1.0) for i in range(D)}
#: MAX_BELOW(f, 0) 的 violation = f 本身（cost 越小越好，零平台在 argmin）
OBJECTIVES = [Objective(metric="f", op=MetricOp.MAX_BELOW, value=0.0)]


def _sphere(params: dict[str, float]) -> dict[str, float]:
    u = np.array([params[f"x{i}"] for i in range(D)])
    return {"f": float(np.sum((u - C_TRUE) ** 2))}


class TestTurbo:
    def test_beats_random_search_same_budget(self):
        """合成基准：同预算（60 评）TuRBO 显著优于同 seed 随机搜索。"""
        r = run_turbo(BOUNDS, OBJECTIVES, _sphere, n_init=16, n_iter=44,
                      seed=42)
        assert r["ok"] and r["algorithm"] == "turbo1"
        assert r["n_real_used"] == 60 and r["n_attempts"] == 60
        u_rand = qmc.LatinHypercube(d=D, seed=42).random(n=60)
        best_rand = min(float(np.sum((u - C_TRUE) ** 2)) for u in u_rand)
        assert r["best"]["cost"] < 0.5 * best_rand

    def test_converges_to_known_argmin_and_region_shrinks(self):
        """best 点贴近闭式 argmin + 信任域收缩（TuRBO-1 语义行为证据）。"""
        r = run_turbo(BOUNDS, OBJECTIVES, _sphere, n_init=16, n_iter=44,
                      seed=42)
        best_u = np.array([r["best"]["params"][f"x{i}"] for i in range(D)])
        assert float(np.max(np.abs(best_u - C_TRUE))) < 0.15
        assert max(r["length_trace"]) <= 0.4  # 初值不越 length_init
        assert r["length_trace"][-1] < 0.4  # 收缩发生过
        assert r["failures"] == []  # 全成功基准面无失败记录

    def test_deterministic_and_seed_sensitive(self):
        """同 seed 逐位可复现（C4）；换 seed 轨迹不同。"""
        r1 = run_turbo(BOUNDS, OBJECTIVES, _sphere, n_init=16, n_iter=44,
                       seed=42)
        r2 = run_turbo(BOUNDS, OBJECTIVES, _sphere, n_init=16, n_iter=44,
                       seed=42)
        assert r1["best"] == r2["best"]
        assert r1["length_trace"] == r2["length_trace"]
        r3 = run_turbo(BOUNDS, OBJECTIVES, _sphere, n_init=16, n_iter=44,
                       seed=7)
        assert r3["best"]["params"] != r1["best"]["params"]

    def test_evaluate_failure_counted_not_fatal(self):
        """evaluate_fn 抛异常 → 诚实计数入 attempts/failures，不中断。"""
        state = {"n": 0}

        def flaky(params: dict[str, float]) -> dict[str, float]:
            state["n"] += 1
            if state["n"] <= 3:  # 前 3 次全失败（LHS 预热前 3 点）
                raise RuntimeError("真机通道模拟失败")
            return _sphere(params)

        r = run_turbo(BOUNDS, OBJECTIVES, flaky, n_init=6, n_iter=10,
                      seed=42)
        assert r["failures"] == [{"phase": "init", "index": 0},
                                 {"phase": "init", "index": 1},
                                 {"phase": "init", "index": 2}]
        assert r["n_attempts"] == 16
        assert r["n_real_used"] == 13

    def test_zero_touch_existing_trust_region_surface(self):
        """零破坏：trust_region 既有公开面原样可用（平行模块不寄生）。"""
        for name in ("refine_trust_region", "run_two_stage"):
            assert hasattr(trust_region, name)
        # turbo 未注册任何 surrogate kind（注册表键面只增不改）
        assert turbo_mod.__all__ == ["DEFAULT_LENGTH_INIT",
                                     "DEFAULT_LENGTH_MIN", "run_turbo"]
