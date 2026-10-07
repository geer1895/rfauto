"""XN-6 合成数据工厂测试（ge8c 席C6）。

锚定：
- 分布设计：LHS 分层不变量（每维每层恰一点）+ 全参落界；
- 确定性：同 seed 同 spec 逐字节可复现（C4 红线）；
- 漂移注入：响应级 gain/offset 逐行精确算术 + raw 留痕 + 元数据同源；
  参数级满量程平移落痕；
- 泄漏防护：min_dist 收紧到必中 → eval 近邻点逐点带 reason 移出；
- 独立数值基准（#118）：线性内核逐行精确自洽（response == a·x+b）；
- 负例：非法 spec/不可调用内核/非有限响应/未知漂移参数显式 errors 或
  excluded 留痕；
- 摘要面：min/max/mean 手算核对。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from rfauto.service.synthetic_factory import (
    SYNTH_FACTORY_SCHEMA,
    factory_summary,
    lhs_unit,
    make_dataset,
)

_SPEC = {"w_mm": {"low": 1.0, "high": 5.0}, "l_mm": {"low": 10.0, "high": 40.0}}


def _linear_kernel(params) -> dict:
    # 确定性线性闭式（测试内的"确定性内核"）：y = 2x - 0.5z + 1
    return {"y": 2.0 * params["w_mm"] - 0.5 * params["l_mm"] + 1.0}


class TestLhs:
    def test_stratification_invariant(self) -> None:
        rng = np.random.default_rng(7)
        n, d = 16, 3
        mat = lhs_unit(n, d, rng)
        assert mat.shape == (n, d)
        assert np.all(mat >= 0) and np.all(mat <= 1)
        for j in range(d):
            bins = (mat[:, j] * n).astype(int)
            assert sorted(bins.tolist()) == list(range(n))  # 每层恰一点

    def test_bad_dims(self) -> None:
        with pytest.raises(ValueError):
            lhs_unit(0, 2, np.random.default_rng(0))
        with pytest.raises(ValueError):
            lhs_unit(4, 0, np.random.default_rng(0))


class TestDataset:
    def test_schema_and_shape(self) -> None:
        r = make_dataset(_SPEC, _linear_kernel, n_points=16, seed=3)
        assert r["ok"] is True
        assert r["schema"] == SYNTH_FACTORY_SCHEMA
        assert r["n_points"] == 16
        assert r["n_train"] + r["n_eval"] == 16
        assert 0 < r["n_train"] < 16
        assert r["n_excluded"] == 0
        assert len(r["rows"]) == 16
        for row in r["rows"]:
            assert 1.0 <= row["params"]["w_mm"] <= 5.0
            assert 10.0 <= row["params"]["l_mm"] <= 40.0
            assert row["split"] in ("train", "eval")
            assert row["drift"] is None  # 无漂移配置 → 如实 None

    def test_deterministic_bytes(self) -> None:
        a = json.dumps(make_dataset(_SPEC, _linear_kernel, n_points=12, seed=5),
                       sort_keys=True)
        b = json.dumps(make_dataset(_SPEC, _linear_kernel, n_points=12, seed=5),
                       sort_keys=True)
        assert a == b

    def test_linear_kernel_row_exact(self) -> None:
        # #118 独立基准：线性内核逐行精确自洽（response == a·x + b·z + c）
        r = make_dataset(_SPEC, _linear_kernel, n_points=10, seed=1)
        for row in r["rows"]:
            p = row["params"]
            expect = 2.0 * p["w_mm"] - 0.5 * p["l_mm"] + 1.0
            assert row["response"]["y"] == pytest.approx(expect, rel=1e-12)

    def test_param_drift_recorded(self) -> None:
        r = make_dataset(_SPEC, _linear_kernel, n_points=8, seed=2,
                         param_drift={"w_mm": 0.1})
        span = 4.0
        assert r["drift"]["param"] == {"w_mm": 0.1 * span}
        # 平移后可能越界（漂移考题语义）：逐行 = 原始 LHS 值 + span×0.1
        # 用同 seed 无漂移数据集对点核对
        clean = make_dataset(_SPEC, _linear_kernel, n_points=8, seed=2)
        for rd, rc in zip(r["rows"], clean["rows"], strict=True):
            assert rd["params"]["w_mm"] == pytest.approx(
                rc["params"]["w_mm"] + 0.4, rel=1e-12)

    def test_response_drift_exact(self) -> None:
        r = make_dataset(_SPEC, _linear_kernel, n_points=8, seed=4,
                         drift={"y": {"gain": 1.1, "offset": 0.5}})
        for row in r["rows"]:
            raw = row["response_raw"]["y"]
            assert row["response"]["y"] == pytest.approx(raw * 1.1 + 0.5,
                                                         rel=1e-12)
            assert row["drift"]["response"] == {
                "y": {"gain": 1.1, "offset": 0.5}}

    def test_leakage_guard(self) -> None:
        # min_dist 拉到必中量级 → 全部 eval 点近邻泄漏移出，逐点带 reason
        r = make_dataset(_SPEC, _linear_kernel, n_points=12, seed=6,
                         split_frac=0.5, min_dist=10.0)
        assert r["ok"] is True
        assert r["n_eval"] == 0
        assert r["n_excluded"] == 6
        assert all("near-duplicate" in e["reason"] for e in r["excluded"])

    def test_kernel_exception_row_excluded(self) -> None:
        calls = {"n": 0}

        def flaky(_p) -> dict:
            calls["n"] += 1
            if calls["n"] == 3:
                raise ZeroDivisionError("boom")
            return {"y": 1.0}

        r = make_dataset(_SPEC, flaky, n_points=6, seed=8)
        assert r["ok"] is True
        assert r["n_excluded"] == 1
        assert "boom" in r["excluded"][0]["reason"]

    def test_nonfinite_response_excluded(self) -> None:
        r = make_dataset(
            _SPEC, lambda _p: {"y": float("nan")}, n_points=6, seed=9)
        assert r["n_excluded"] == 6
        assert all("非有限" in e["reason"] for e in r["excluded"])


class TestNegatives:
    def test_bad_spec(self) -> None:
        assert make_dataset({}, _linear_kernel)["ok"] is False
        bad = {"x": {"low": 2.0, "high": 1.0}}
        assert make_dataset(bad, _linear_kernel)["ok"] is False
        bad2 = {"x": {"low": 0.0}}
        assert make_dataset(bad2, _linear_kernel)["ok"] is False

    def test_bad_kernel(self) -> None:
        assert make_dataset(_SPEC, "not-callable")["ok"] is False  # type: ignore[arg-type]

    def test_bad_counts_and_fracs(self) -> None:
        assert make_dataset(_SPEC, _linear_kernel, n_points=3)["ok"] is False
        assert make_dataset(_SPEC, _linear_kernel, n_points=10,
                            split_frac=1.0)["ok"] is False
        assert make_dataset(_SPEC, _linear_kernel, n_points=10,
                            min_dist=0.0)["ok"] is False

    def test_unknown_drift_param(self) -> None:
        r = make_dataset(_SPEC, _linear_kernel, n_points=8,
                         param_drift={"nope": 0.1})
        assert r["ok"] is False

    def test_nonfinite_drift(self) -> None:
        r = make_dataset(_SPEC, _linear_kernel, n_points=8,
                         drift={"y": {"gain": math.nan}})
        assert r["ok"] is False


class TestSummary:
    def test_summary_hand_checked(self) -> None:
        r = make_dataset(_SPEC, lambda p: {"y": 1.0, "z": -2.0},
                         n_points=8, seed=11)
        s = factory_summary(r)
        assert s["ok"] is True
        assert s["n_rows"] == 8
        m = s["metrics"]
        assert m["y"]["min"] == m["y"]["max"] == m["y"]["mean"] == 1.0
        assert m["z"]["min"] == m["z"]["max"] == -2.0
        assert list(m) == sorted(m)

    def test_summary_requires_ok(self) -> None:
        assert factory_summary({"ok": False, "errors": ["x"]})["ok"] is False
