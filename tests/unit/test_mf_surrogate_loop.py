"""E7 多保真代理寻优环单测（#18 optstack 收口）。

验收口径（原文「多保真同精度细网格次数减半（合成）」）：合成双保真裁判 ×2——
- Forrester 文献对（高保真 (6x−2)²sin(12x−4)、低保真 0.5·high+4(x−0.5)−1，
  与 test_smt_mfk.py 同型；低保真最优 x≈0.53 vs 高保真 x≈0.757，系统偏差
  显著，必须靠 co-kriging 融合而非低保真直选）；
- 二维 bowl 推广（test_surrogate_loop.bowl_metrics 同型：高保真谷心
  (0.30,0.62)；低保真谷心偏移到 (0.45,0.45) 且谷深浅 1.5 dB）。
判据：MF 环细评次数 median（3 种子）≤ 细-only 环 n_real×50%，且 final best
（细保真 cost）不劣于细-only best + margin。细-only 参考用 tol_rounds=99 钉死
预算停（n_real 恰为 max_real，50% 阈值确定）。

冻结常量来自 2026-09-15 校准实测（5 种子 Forrester / 3 种子 bowl）：
- Forrester：细-only 16 评 best ∈ [0.984, 1.845]；MF 8 细评 best ∈ [0.979,
  1.161]，逐种子 MF−fine 最大 +0.177 → margin 0.5（极值之上留 2.8×，#207）；
- bowl：细-only 18 评 best ∈ [0.863, 1.005]；MF 9 细评 best ∈ [0.762, 1.460]，
  逐种子最大 +0.46 → margin 0.6。
smt（SMT 2.x）为可选 extra：无 smt 时两判据 skip（与 test_smt_mfk 同惯例），
poly_ridge 混拟通道与单保真逐字节回归不依赖 smt。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.objectives import MetricOp, Objective
from rfauto.optimization.surrogate_loop import run_surrogate_loop

SEEDS = (7, 2026, 42)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


def _median(values: list[float]) -> float:
    s = sorted(values)
    return s[len(s) // 2]


# ─── 裁判 1：Forrester 文献双保真对（一维）────────────────────────────────────

F_BOUNDS = {"x": (0.0, 1.0)}
# value=-7 低于全局最小 −6.02 → cost=f+7 ≥ 0.98 无零平台（#207 种子彩票防线）
F_OBJS = [Objective(metric="f", band=[2.3, 2.5], op=MetricOp.MAX_BELOW,
                    value=-7.0, weight=1.0)]


def forrester_high(p: dict[str, float]) -> dict[str, float]:
    x = p["x"]
    return {"f": (6.0 * x - 2.0) ** 2 * math.sin(12.0 * x - 4.0)}


def forrester_low(p: dict[str, float]) -> dict[str, float]:
    return {"f": 0.5 * forrester_high(p)["f"] + 4.0 * (p["x"] - 0.5) - 1.0}


# ─── 裁判 2：二维 bowl 推广 ───────────────────────────────────────────────────

B_BOUNDS = {"x_mm": (0.0, 1.0), "y_mm": (0.0, 1.0)}
B_OBJS = [Objective(metric="s11_db_min", band=[2.3, 2.5],
                    op=MetricOp.MAX_BELOW, value=-47.0, weight=1.0)]


def _bowl(x: float, y: float, cx: float, cy: float) -> float:
    dx, dy = x - cx, y - cy
    d = -46.0 + 180.0 * dx * dx + 150.0 * dy * dy - 120.0 * dx * dy
    return d + 1.5 * math.sin(3.0 * math.pi * x) * math.sin(3.0 * math.pi * y)


def bowl_high(p: dict[str, float]) -> dict[str, float]:
    return {"s11_db_min_in_band": _bowl(p["x_mm"], p["y_mm"], 0.30, 0.62)}


def bowl_low(p: dict[str, float]) -> dict[str, float]:
    return {"s11_db_min_in_band": _bowl(p["x_mm"], p["y_mm"], 0.45, 0.45) + 1.5}


def _judge(bounds, objs, high, low, *, fine_max_real, fine_n_init,
           mf_fine_budget, mf_n_init, mf_max_real, margin):
    """三种子对照：返回 (mf 细评次数列表, mf best 列表, fine-only best 列表)。"""
    n_high: list[int] = []
    mf_best: list[float] = []
    fine_best: list[float] = []
    for seed in SEEDS:
        fine = run_surrogate_loop(
            bounds, objs, high, n_init=fine_n_init, top_k=3,
            max_real=fine_max_real, virtual_trials=250, seed=seed,
            tol_rounds=99)
        assert fine["ok"] and fine["best"] is not None
        # 参考环钉死预算停：n_real 恰为 max_real（50% 阈值确定，无早停漂移）
        assert fine["stop_reason"] == "budget"
        assert fine["n_real_used"] == fine_max_real
        assert "n_high_used" not in fine  # 单保真返回体无 E7 键
        mf = run_surrogate_loop(
            bounds, objs, high, evaluate_low_fn=low,
            n_init=mf_n_init, top_k=3, max_real=mf_max_real,
            fine_budget=mf_fine_budget, virtual_trials=250, seed=seed,
            tol_rounds=99, surrogate_kind="smt_mfk")
        assert mf["ok"], mf
        assert mf["fidelity"] == "multi"
        assert mf["stop_reason"] == "budget", mf["stop_reason"]
        assert mf["best"] is not None
        assert mf["n_high_used"] <= mf_fine_budget
        # best 必由细保真背书：best 的 params 在细评集合内且 cost=细保真重算
        bp = mf["best"]["params"]
        assert mf["best"]["cost"] == pytest.approx(
            high(bp)[next(iter(high(bp)))] - objs[0].value, abs=1e-9)
        delta = mf["fidelity_delta"]
        assert delta["n_matched_pairs"] == mf["n_high_used"]  # 细评点 ⊆ 低评点（嵌套）
        assert isinstance(delta["rank_flip_count"], int)
        assert 0 <= delta["rank_flip_count"] <= math.comb(delta["n_matched_pairs"], 2)
        n_high.append(mf["n_high_used"])
        mf_best.append(mf["best"]["cost"])
        fine_best.append(fine["best"]["cost"])
        # 逐种子质量：MF 细保真 best 不劣于细-only best + margin
        assert mf["best"]["cost"] <= fine["best"]["cost"] + margin, (
            f"seed={seed} mf={mf['best']['cost']:.4f} fine={fine['best']['cost']:.4f}")
    return n_high, mf_best, fine_best


class TestMultiFidelityAcceptance:
    """§10.23 #23：多保真同精度细网格次数减半（合成裁判）。"""

    def test_forrester_half_fine_evaluations(self):
        pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")
        fine_max = 16
        n_high, mf_best, fine_best = _judge(
            F_BOUNDS, F_OBJS, forrester_high, forrester_low,
            fine_max_real=fine_max, fine_n_init=6,
            mf_fine_budget=fine_max // 2, mf_n_init=6, mf_max_real=30,
            margin=0.5)
        assert _median(n_high) <= fine_max * 0.5, n_high
        assert _median(mf_best) <= _median(fine_best) + 0.5, (mf_best, fine_best)

    def test_bowl_2d_half_fine_evaluations(self):
        pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")
        fine_max = 18
        n_high, mf_best, fine_best = _judge(
            B_BOUNDS, B_OBJS, bowl_high, bowl_low,
            fine_max_real=fine_max, fine_n_init=8,
            mf_fine_budget=fine_max // 2, mf_n_init=8, mf_max_real=30,
            margin=0.6)
        assert _median(n_high) <= fine_max * 0.5, n_high
        assert _median(mf_best) <= _median(fine_best) + 0.6, (mf_best, fine_best)


class TestMultiFidelityLoopMechanics:
    """环机制（不依赖 smt）：poly_ridge 混拟通道、预算分层、返回体键。"""

    def test_poly_ridge_mixed_fit_channel(self):
        calls = {"low": 0, "high": 0}

        def low(p):
            calls["low"] += 1
            return forrester_low(p)

        def high(p):
            calls["high"] += 1
            return forrester_high(p)

        res = run_surrogate_loop(F_BOUNDS, F_OBJS, high, evaluate_low_fn=low,
                                 n_init=5, top_k=2, max_real=12, fine_budget=4,
                                 virtual_trials=80, seed=42, tol_rounds=99)
        assert res["ok"] and res["fidelity"] == "multi"
        assert res["surrogate_kind"] == "poly_ridge"
        assert res["n_low_used"] == calls["low"] == 12  # max_real 只计低保真
        assert res["n_high_used"] == calls["high"] == 4  # 细预算独立
        assert res["fine_budget"] == 4
        assert res["n_real_used"] == 16  # 并集
        assert res["best"] is not None
        # 每轮细评 ≤ fine_top_k=1 且历史带 E7 键
        rounds = [r for r in res["rounds"] if r["round"] > 0]
        assert rounds and all(r["n_fine"] <= 1 for r in rounds)
        assert rounds[-1]["n_high_total"] == 4
        assert res["fidelity_delta"]["n_matched_pairs"] == 4

    def test_fine_budget_zero_means_no_fine_evaluations(self):
        res = run_surrogate_loop(F_BOUNDS, F_OBJS, forrester_high,
                                 evaluate_low_fn=forrester_low,
                                 n_init=4, top_k=2, max_real=8, fine_budget=0,
                                 virtual_trials=50, seed=7, tol_rounds=99)
        assert res["ok"] and res["n_high_used"] == 0
        assert res["best"] is None  # 无细保真背书 → 如实无 best（不拿低保真凑）
        assert res["n_low_used"] == 8

    def test_smt_mfk_without_enough_fine_seed_stops_honestly(self):
        pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")
        # 细预算 2 < min_high_samples=3：smt_mfk 无混拟通道 → 如实
        # surrogate_fit_failed（不静默换代理）
        res = run_surrogate_loop(F_BOUNDS, F_OBJS, forrester_high,
                                 evaluate_low_fn=forrester_low,
                                 n_init=5, top_k=2, max_real=10, fine_budget=2,
                                 virtual_trials=50, seed=7,
                                 surrogate_kind="smt_mfk")
        assert res["ok"] and res["stop_reason"] == "surrogate_fit_failed"
        assert res["n_high_used"] == 2

    def test_fine_failures_burn_fine_budget_not_loop(self):
        def flaky_high(p):
            raise RuntimeError("细保真求解失败注入")

        res = run_surrogate_loop(F_BOUNDS, F_OBJS, flaky_high,
                                 evaluate_low_fn=forrester_low,
                                 n_init=4, top_k=2, max_real=8, fine_budget=3,
                                 virtual_trials=50, seed=7, tol_rounds=99)
        assert res["ok"]
        assert res["n_high_used"] == 0 and res["best"] is None
        assert res["n_failures"] == 3  # 细预算 3 次全烧在失败上
        assert all(f["fidelity"] == "high" for f in res["failures"])
        assert res["n_low_used"] == 8  # 低保真环照常跑满

    def test_constraints_with_multifidelity_judged_on_fine(self):
        cons = [Objective(metric="s21_db", band=[2.3, 2.5],
                          op=MetricOp.MIN_ABOVE, value=0.0, weight=1.0)]

        def high(p):
            d = forrester_high(p)
            d["s21_db_mean_in_band"] = 5.0 - 60.0 * abs(p["x"] - 0.8)
            return d

        def low(p):
            d = forrester_low(p)
            d["s21_db_mean_in_band"] = 5.0 - 60.0 * abs(p["x"] - 0.8)
            return d

        res = run_surrogate_loop(F_BOUNDS, F_OBJS, high, evaluate_low_fn=low,
                                 n_init=6, top_k=2, max_real=14, fine_budget=6,
                                 virtual_trials=120, seed=42, tol_rounds=99,
                                 constraints=cons)
        assert res["ok"]
        assert "n_feasible" in res and "best_feasible" in res
        if res["best"] is not None:
            bx = res["best"]["params"]["x"]
            assert 0.8 - 1 / 12 - 1e-9 <= bx <= 0.8 + 1 / 12 + 1e-9
        else:
            assert res["all_infeasible"] is True


class TestSingleFidelityUnchanged:
    """缺省 evaluate_low_fn=None：返回体不带 E7 键，行为与既有回归一致。"""

    def test_no_e7_keys_and_history_shape(self):
        res = run_surrogate_loop(F_BOUNDS, F_OBJS, forrester_high,
                                 n_init=5, top_k=2, max_real=9,
                                 virtual_trials=60, seed=42)
        assert res["ok"]
        for key in ("fidelity", "n_low_used", "n_high_used", "fine_budget",
                    "fidelity_delta"):
            assert key not in res
        for r in res["rounds"]:
            assert "n_fine" not in r and "n_high_total" not in r
        assert res["best"]["cost"] == pytest.approx(min(res["real_cost_trace"]))


# ─── 服务入口：run_multifidelity_sbo_tune（fake+fake 冒烟）─────────────────────

def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "substrate": "rogers4350b_h0.508",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.58},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 101},
        "objectives": [
            {"metric": "s11_db_min", "band": [2.3, 2.5], "op": "max_below", "value": -40},
        ],
        "optimization": {"params": {
            "series_w_mm": {"low": 0.2, "high": 0.8},
            "shunt_w_mm": {"low": 0.6, "high": 2.0},
        }},
    }
    path = tmp_path / "mf_sbo_recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


class TestService:
    _KWARGS: ClassVar[dict] = {"n_init": 4, "top_k": 2, "max_real": 8,
                               "fine_budget": 3, "virtual_trials": 60, "seed": 42}

    def test_mf_sbo_service_smoke(self, tmp_path):
        from rfauto.service.api import run_multifidelity_sbo_tune

        res = run_multifidelity_sbo_tune(
            _recipe(tmp_path), adapter_low="fake", adapter_high="fake",
            surrogate_kind="poly_ridge", **self._KWARGS)
        assert res["ok"], res.get("errors")
        assert res["fidelity"] == "multi"
        assert res["adapter"] == "mf_sbo:fake+fake"
        assert res["n_high_used"] <= 3 and res["n_low_used"] <= 8
        run_dir = Path(res["run_dir"])
        assert (run_dir / "surrogate_loop.json").is_file()
        meta = yaml.safe_load((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["algorithm"] == "multifidelity_surrogate_loop"
        assert meta["adapter"] == "mf_sbo:fake+fake"
        assert meta["metrics"]["n_high_used"] == res["n_high_used"]

    def test_service_rejects_missing_recipe_and_reexport_identity(self):
        from rfauto.service import api, v3_services

        assert api.run_multifidelity_sbo_tune is v3_services.run_multifidelity_sbo_tune
        assert not api.run_multifidelity_sbo_tune("no_such.yaml")["ok"]
