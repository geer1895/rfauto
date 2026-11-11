"""主动学习环测试（aurora_r R-07，service/active_learning_loop）。

覆盖面（席位任务书§4）：
- 纯函数正负例：σ 阈值边界（σ==threshold 合格）/批量/空候选/NaN σ；
- fake 通道端到端 1-2 轮环：固定 seed 确定性断言（轮 2 选点与轮 1 σ
  分布逐位可复现）+ 报告落盘；
- 回填幂等：同点（canonical 口径）不重复采、不重复评估；
- σ 输出缺省零变化钉：core gp_tensor_kernel.regression_predict 输出
  键面 {mean, std, nugget} 零改动（本席零 core hunk 的回归钉）。
"""

from __future__ import annotations

import copy
import json
import math
from typing import ClassVar

import numpy as np
import pytest

import rfauto.service.active_learning_loop as al_loop_mod
from rfauto.service.active_learning_loop import (
    STOP_REASONS,
    canonical_param_key,
    run_active_learning_loop,
    select_by_sigma,
)

BOUNDS = {"x": (0.0, 1.0), "y": (0.0, 1.0)}


def _bowl(p: dict[str, float]) -> float:
    """确定性闭式响应（fake 真值通道；数据工厂 response_fn 同构）。"""
    return float((p["x"] - 0.35) ** 2 + 2.0 * (p["y"] - 0.65) ** 2) + 0.5


def _seed_samples(n: int = 10, seed: int = 7) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        p = {"x": float(rng.uniform(0.0, 1.0)),
             "y": float(rng.uniform(0.0, 1.0))}
        out.append({"params": p, "metrics": {"cost": _bowl(p)}})
    return out


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """隔离体收编 tests/conftest.py::isolated（T5 首批单源化）。"""
    yield


# ─── 采集策略纯函数 ─────────────────────────────────────────────────────────


class TestSelectBySigma:
    CANDS: ClassVar[list[dict[str, float]]] = [
        {"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.5}, {"x": 0.9, "y": 0.9}]

    def test_topk_desc_and_contract(self):
        r = select_by_sigma(self.CANDS, [0.0, 1.0, 0.2], [0.3, 0.8, 0.3],
                            bounds=BOUNDS, k=2)
        assert [s["index"] for s in r["selected"]] == [1, 0]
        assert r["k_requested"] == 2
        assert r["n_eligible"] == 3
        assert r["n_invalid"] == 0
        assert r["sigma_pool"]["max"] == pytest.approx(0.8)
        for s in r["selected"]:
            assert math.isfinite(s["mu"]) and s["sigma"] >= 0.0

    def test_threshold_boundary_is_inclusive(self):
        """σ == threshold 合格（≥ 判据）；低一分即排除并计数。"""
        kw = dict(bounds=BOUNDS, k=3)
        r_eq = select_by_sigma(self.CANDS, [0.0, 0.0, 0.0],
                               [0.3, 0.3, 0.3], sigma_threshold=0.3, **kw)
        assert r_eq["n_eligible"] == 3
        assert r_eq["n_below_threshold"] == 0
        r_lo = select_by_sigma(self.CANDS, [0.0, 0.0, 0.0],
                               [0.3, 0.3, 0.3], sigma_threshold=0.3 + 1e-12,
                               **kw)
        assert r_lo["n_eligible"] == 0
        assert r_lo["n_below_threshold"] == 3
        assert r_lo["selected"] == []

    def test_empty_candidates(self):
        r = select_by_sigma([], [], [], bounds=BOUNDS, k=2)
        assert r["selected"] == []
        assert r["n_eligible"] == 0
        assert r["sigma_pool"] == {"max": 0.0, "mean": 0.0, "median": 0.0}

    def test_nan_sigma_and_mu_excluded(self):
        r = select_by_sigma(self.CANDS, [0.0, 1.0, 0.2],
                            [float("nan"), 0.8, float("inf")],
                            bounds=BOUNDS, k=3)
        assert r["n_invalid"] == 2
        assert [s["index"] for s in r["selected"]] == [1]
        r_mu = select_by_sigma(self.CANDS, [float("nan"), 1.0, 0.2],
                               [0.3, 0.8, 0.3], bounds=BOUNDS, k=3)
        assert r_mu["n_invalid"] == 1  # NaN μ 同样显式排除

    def test_negative_sigma_invalid(self):
        r = select_by_sigma(self.CANDS, [0.0, 1.0, 0.2],
                            [-0.1, 0.8, 0.3], bounds=BOUNDS, k=3)
        assert r["n_invalid"] == 1
        assert all(s["index"] != 0 for s in r["selected"])

    def test_min_dist_diversity(self):
        """两个高 σ 候选近邻时只取其一（方差贪心 × 距离双重准则）。"""
        cands = [{"x": 0.50, "y": 0.50}, {"x": 0.52, "y": 0.50},
                 {"x": 0.9, "y": 0.9}]
        r = select_by_sigma(cands, [0.0, 0.0, 0.0], [0.9, 0.8, 0.5],
                            bounds=BOUNDS, k=2, min_dist=0.05)
        assert len(r["selected"]) == 2
        assert r["n_rejected_by_min_dist"] >= 1
        picked = [s["index"] for s in r["selected"]]
        assert 0 in picked and 1 not in picked

    def test_existing_points_filter(self):
        r = select_by_sigma(self.CANDS, [0.0, 0.0, 0.0], [0.9, 0.8, 0.5],
                            bounds=BOUNDS, k=3, min_dist=0.2,
                            existing_points=[{"x": 0.5, "y": 0.5}])
        assert all(s["index"] != 1 for s in r["selected"])

    def test_deterministic_tie_break(self):
        """σ 全等 → 按下标升序（零随机源，逐位复现）。"""
        r1 = select_by_sigma(self.CANDS, [0.0, 0.0, 0.0],
                             [0.5, 0.5, 0.5], bounds=BOUNDS, k=3)
        r2 = select_by_sigma(self.CANDS, [0.0, 0.0, 0.0],
                             [0.5, 0.5, 0.5], bounds=BOUNDS, k=3)
        assert [s["index"] for s in r1["selected"]] == [0, 1, 2]
        assert r1 == r2

    def test_inputs_not_mutated(self):
        cands = [dict(c) for c in self.CANDS]
        mu, sigma = [0.0, 1.0, 0.2], [0.3, 0.8, 0.3]
        select_by_sigma(cands, mu, sigma, bounds=BOUNDS, k=2)
        assert cands == self.CANDS and mu == [0.0, 1.0, 0.2]

    @pytest.mark.parametrize("kw", [
        {"k": 0}, {"k": -1}, {"min_dist": -0.1},
        {"sigma_threshold": -0.5}, {"sigma_threshold": float("nan")},
    ])
    def test_invalid_params_raise(self, kw):
        with pytest.raises(ValueError):
            select_by_sigma(self.CANDS, [0.0, 1.0, 0.2], [0.3, 0.8, 0.3],
                            bounds=BOUNDS, **kw)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="数量不对齐"):
            select_by_sigma(self.CANDS, [0.0, 1.0], [0.3, 0.8, 0.3],
                            bounds=BOUNDS)


class TestCanonicalParamKey:
    def test_order_insensitive(self):
        a = canonical_param_key({"b": 0.1, "a": 0.5})
        b = canonical_param_key({"a": 0.5, "b": 0.1})
        assert a == b

    def test_rounding_window(self):
        """1e-13 抖动=同点（canonical 闸只吸收尾数）；1e-9=异点。"""
        base = canonical_param_key({"x": 0.123456789012345})
        jitter = canonical_param_key({"x": 0.123456789012345 + 1e-13})
        far = canonical_param_key({"x": 0.123456789012345 + 1e-9})
        assert base == jitter
        assert base != far

    def test_key_set_must_match(self):
        assert canonical_param_key({"x": 0.5}) != \
            canonical_param_key({"x": 0.5, "y": 0.5})

    @pytest.mark.parametrize("bad", [
        {"x": float("nan")}, {"x": True}, {"x": "0.5"}, {"x": None},
    ])
    def test_nonfinite_rejected(self, bad):
        with pytest.raises(ValueError):
            canonical_param_key(bad)


# ─── fake 通道端到端环 ──────────────────────────────────────────────────────


class TestRunActiveLearningLoop:
    def test_end_to_end_two_rounds_fake_channel(self, tmp_path):
        samples = _seed_samples()
        calls: list[dict] = []

        def evaluate_fn(p):
            calls.append(dict(p))
            return {"cost": _bowl(p)}

        r = run_active_learning_loop(
            BOUNDS, samples, evaluate_fn, metric_key="cost",
            batch_k=2, max_rounds=2, candidate_n=64, min_dist=0.02,
            seed=11, report_dir=tmp_path / "reports")
        assert r["ok"], r.get("errors")
        assert r["stop_reason"] == "rounds_exhausted"
        assert r["stop_reason"] in STOP_REASONS
        assert r["n_rounds"] == 2
        assert r["n_evals_used"] == 4
        assert r["n_backfilled"] == 4
        assert r["max_evals"] == 4  # None → max_rounds×batch_k
        assert len(calls) == 4
        # 选点带 σ（后验输出面）且在域内
        for rnd in r["rounds"]:
            for s in rnd["selected"]:
                assert math.isfinite(s["sigma"]) and s["sigma"] >= 0.0
                assert 0.0 <= s["params"]["x"] <= 1.0
                assert 0.0 <= s["params"]["y"] <= 1.0
            assert rnd["gp_refit"]["ok"]
            assert math.isfinite(rnd["gp_refit"]["loocv_mse"])
        # 回填行 = 真值通道产出
        assert len(r["backfilled"]) == 4
        for row in r["backfilled"]:
            assert row["metrics"]["cost"] == pytest.approx(
                _bowl(row["params"]))
        # 每轮报告落盘（runs/ 产物惯例；此处 tmp 隔离）。写回执在返回体
        # 轮报告内（落盘 JSON 是写前快照，不含自身回执——#105 面语义）
        files = sorted((tmp_path / "reports").glob("*.json"))
        assert len(files) == 2
        assert r["rounds"][0]["report_write"]["ok"] is True
        assert r["rounds"][0]["report_write"]["path"] == str(files[0])
        assert r["rounds"][1]["report_write"]["ok"] is True
        rep0 = json.loads(files[0].read_text(encoding="utf-8"))
        assert rep0["round"] == 0
        assert rep0["selected"] and rep0["evals"]
        assert r["report_files"] == [str(p) for p in files]

    def test_deterministic_two_runs_bit_identical(self):
        """同 seed 同输入：轮选点与 σ 分布逐位复现（唯一随机源=LHS 种子）。"""
        samples = _seed_samples()

        def run():
            return run_active_learning_loop(
                BOUNDS, samples, lambda p: {"cost": _bowl(p)},
                metric_key="cost", batch_k=2, max_rounds=2,
                candidate_n=64, min_dist=0.02, seed=11)

        r1, r2 = run(), run()
        assert r1["ok"] and r2["ok"]
        assert r1["sigma_trace"] == r2["sigma_trace"]  # 轮 σ 分布逐位同
        sel1 = [[s["params"] for s in rd["selected"]] for rd in r1["rounds"]]
        sel2 = [[s["params"] for s in rd["selected"]] for rd in r2["rounds"]]
        assert sel1 == sel2  # 轮选点逐位同（含轮 2）
        assert r1["backfilled"] == r2["backfilled"]

    def test_sigma_saturated_stops_with_zero_evals(self):
        """阈值高于一切 σ → 饱和停环，零真值预算消耗（Keysight 语义）。"""
        r = run_active_learning_loop(
            BOUNDS, _seed_samples(), lambda p: {"cost": _bowl(p)},
            metric_key="cost", batch_k=2, max_rounds=3,
            sigma_threshold=1e9, candidate_n=32, min_dist=0.02)
        assert r["ok"]
        assert r["stop_reason"] == "sigma_saturated"
        assert r["n_evals_used"] == 0
        assert r["n_backfilled"] == 0

    def test_eval_budget_exhausted(self):
        r = run_active_learning_loop(
            BOUNDS, _seed_samples(), lambda p: {"cost": _bowl(p)},
            metric_key="cost", batch_k=2, max_rounds=3, max_evals=3,
            candidate_n=64, min_dist=0.02)
        assert r["ok"]
        assert r["stop_reason"] == "eval_budget_exhausted"
        assert r["n_evals_used"] == 3
        assert r["n_backfilled"] == 3

    def test_failing_channel_records_failures_not_crash(self):
        def bad_fn(p):
            raise RuntimeError("求解失败: fake")

        r = run_active_learning_loop(
            BOUNDS, _seed_samples(), bad_fn, metric_key="cost",
            batch_k=1, max_rounds=3, candidate_n=64, min_dist=0.02)
        assert r["ok"]  # 环本身成立，失败如实入账（不炸环）
        assert r["stop_reason"] == "no_new_samples"
        assert r["n_evals_used"] == 1
        assert r["n_failed"] == 1
        assert "求解失败" in r["failures"][0]["error"]

    def test_refit_false_reuses_first_fit(self):
        r = run_active_learning_loop(
            BOUNDS, _seed_samples(), lambda p: {"cost": _bowl(p)},
            metric_key="cost", batch_k=2, max_rounds=2,
            candidate_n=64, min_dist=0.02, refit=False)
        assert r["ok"]
        assert r["n_rounds"] == 2
        assert r["rounds"][0]["gp_refit"]["refit"] is True
        assert r["rounds"][1]["gp_refit"]["refit"] is False
        # 复用首轮拟合：两轮重训指标逐位相同
        assert r["rounds"][0]["gp_refit"]["loocv_mse"] == \
            r["rounds"][1]["gp_refit"]["loocv_mse"]

    def test_input_samples_not_mutated(self):
        samples = _seed_samples()
        snapshot = copy.deepcopy(samples)
        r = run_active_learning_loop(
            BOUNDS, samples, lambda p: {"cost": _bowl(p)},
            metric_key="cost", batch_k=2, max_rounds=2,
            candidate_n=64, min_dist=0.02)
        assert r["ok"]
        assert samples == snapshot  # 回填只进内部副本，入参零突变
        assert len(samples) == len(snapshot)

    def test_dup_gate_skips_eval_without_budget(self, monkeypatch):
        """回填幂等：选中点与既有样本 canonical 同点 → 跳过评估不烧预算。

        近邻闸（min_dist）由 fake 采集函数绕过——证明 canonical 闸是
        独立的第二道防线（模块头"两道闸独立生效"语义钉）。
        """
        samples = _seed_samples()
        real = al_loop_mod.select_by_sigma
        dup_params = dict(samples[0]["params"])

        def fake_select(candidates, mu, sigma, **kw):
            r = real(candidates, mu, sigma, **kw)
            r = dict(r)
            r["selected"] = [{"index": -1, "params": dict(dup_params),
                              "mu": 0.0, "sigma": 999.0}]
            return r

        monkeypatch.setattr(al_loop_mod, "select_by_sigma", fake_select)
        calls: list[dict] = []

        def evaluate_fn(p):
            calls.append(dict(p))
            return {"cost": _bowl(p)}

        r = run_active_learning_loop(
            BOUNDS, samples, evaluate_fn, metric_key="cost",
            batch_k=1, max_rounds=2, candidate_n=64, min_dist=0.02)
        assert r["ok"]
        assert calls == []  # 同点零重复评估
        assert r["n_dup_skipped"] == 1
        assert r["n_evals_used"] == 0
        assert r["n_backfilled"] == 0
        assert r["stop_reason"] == "no_new_samples"
        assert r["rounds"][0]["evals"][0]["skipped"] == "duplicate"

    def test_dup_gate_via_pool_collision(self, monkeypatch):
        """回填幂等（真实环流）：候选池与既有样本精确撞点 → canonical 闸
        拦截、零重复评估，另一新鲜点照常评估回填。

        只桩候选池（复现"池点=既有样本"的真实撞点形态，如 GP 排除行
        或跨轮池换种子），GP/采集/闸全走真实链路。
        """
        samples = _seed_samples()
        dup_pt = dict(samples[0]["params"])
        fresh_pt = {"x": 0.42, "y": 0.83}

        def fake_lhs(bounds, n_points, seed=42, **kw):
            return {"points": [dict(dup_pt), dict(fresh_pt)],
                    "design": {"kind": "stub", "n_points": 2,
                               "seed": seed, "skipped_close": 0}}

        monkeypatch.setattr(
            "rfauto.optimization.sample_design.lhs_points", fake_lhs)
        calls: list[dict] = []

        def evaluate_fn(p):
            calls.append(dict(p))
            return {"cost": _bowl(p)}

        r = run_active_learning_loop(
            BOUNDS, samples, evaluate_fn, metric_key="cost",
            batch_k=2, max_rounds=1, candidate_n=2, min_dist=0.0)
        assert r["ok"]
        assert calls == [dict(fresh_pt)]  # 撞点零评估，新鲜点恰一次
        assert r["n_dup_skipped"] == 1
        assert r["n_backfilled"] == 1
        assert r["stop_reason"] == "rounds_exhausted"
        evals = r["rounds"][0]["evals"]
        # 选点按 σ 降序（撞点=训练位 σ 被压低，序位不定）——按内容断言
        skipped = [e for e in evals if e.get("skipped") == "duplicate"]
        ok_evals = [e for e in evals if e.get("ok") is True]
        assert len(skipped) == 1 and skipped[0]["params"] == dup_pt
        assert len(ok_evals) == 1 and ok_evals[0]["params"] == fresh_pt

    @pytest.mark.parametrize("kwargs,frag", [
        ({"bounds": {}}, "bounds"),
        ({"bounds": {"x": (1.0, 1.0)}}, "low < high"),
        ({"metric_key": ""}, "metric_key"),
        ({"metric_key": "nope"}, "有效样本不足"),
        ({"batch_k": 0}, "batch_k"),
        ({"max_rounds": 0}, "max_rounds"),
        ({"max_evals": 0}, "max_evals"),
        ({"sigma_threshold": -1.0}, "sigma_threshold"),
        ({"candidate_n": 0}, "candidate_n"),
        ({"min_dist": -0.5}, "min_dist"),
    ])
    def test_error_envelopes_zero_side_effect(self, kwargs, frag):
        samples = _seed_samples()
        r = run_active_learning_loop(
            kwargs.pop("bounds", BOUNDS), samples,
            lambda p: {"cost": _bowl(p)},
            metric_key=kwargs.pop("metric_key", "cost"),
            batch_k=kwargs.pop("batch_k", 2),
            max_rounds=kwargs.pop("max_rounds", 2),
            candidate_n=kwargs.pop("candidate_n", 32),
            max_evals=kwargs.pop("max_evals", None),
            sigma_threshold=kwargs.pop("sigma_threshold", None),
            min_dist=kwargs.pop("min_dist", 0.02),
            **kwargs)
        assert r["ok"] is False
        assert r["errors"] and frag in r["errors"][0]
        assert len(samples) == 10  # 负例零副作用


# ─── σ 输出缺省零变化钉（本席零 core hunk 的回归钉） ────────────────────────


class TestSigmaOutputZeroChangePin:
    def test_regression_predict_output_keys_unchanged(self):
        """core GP 预测链输出键面 {mean, std, nugget} 零改动——σ 是既有
        附加键，本席只消费不改名（缺省路径零变化钉，模块头任务①）。"""
        from rfauto.core.gp_tensor_kernel import regression_predict

        x = np.asarray([[0.0], [0.5], [1.0]], dtype=float)
        y = np.asarray([1.0, 2.0, 0.5], dtype=float)
        out = regression_predict(x, y, np.asarray([[0.25], [0.75]]),
                                 lengthscale=0.5)
        assert set(out) == {"mean", "std", "nugget"}
        assert out["std"].shape == (2,)
        assert all(math.isfinite(float(v)) and float(v) >= 0.0
                   for v in out["std"])

    def test_loop_report_carries_sigma(self):
        """环报告的选点逐点带有限非负 σ（后验 σ 触发面端到端在场）。"""
        r = run_active_learning_loop(
            BOUNDS, _seed_samples(), lambda p: {"cost": _bowl(p)},
            metric_key="cost", batch_k=2, max_rounds=1,
            candidate_n=64, min_dist=0.02)
        assert r["ok"]
        sigmas = [s["sigma"] for s in r["rounds"][0]["selected"]]
        assert len(sigmas) == 2
        assert all(math.isfinite(v) and v >= 0.0 for v in sigmas)
        # σ 池统计与选点一致（max=榜首 σ）
        assert r["sigma_trace"][0]["max"] == pytest.approx(max(sigmas))
