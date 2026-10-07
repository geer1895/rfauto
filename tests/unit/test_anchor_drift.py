"""QW-16 锚漂移预警内核测试（Mann-Kendall 手算钉 + 指纹 + 组合 verdict）。

#118 纪律：MK 统计量与 z 值以测试内独立暴力枚举（双循环逐对符号和）+
手算文字钉双重复核，不与被测实现共享同一公式路径；指纹分位数另以
numpy percentile（linear 法）独立来源对拍。全部确定性、零 IO、零网络。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.anchor_drift import (
    anchor_drift_report,
    drift_fingerprint,
    mann_kendall,
)


def _brute_force_s(values: list[float]) -> int:
    """独立暴力实现：S = Σ_{i<j} sign(x_j − x_i)（不 import 被测路径）。"""
    total = 0
    for i in range(len(values) - 1):
        for j in range(i + 1, len(values)):
            diff = values[j] - values[i]
            total += 1 if diff > 0 else (-1 if diff < 0 else 0)
    return total


# ─── mann_kendall：手算例钉（#118） ─────────────────────────────────────────

class TestMannKendallHandCalc:
    def test_monotone_increasing_hand_pinned(self):
        # 手算：n=5 全递增 → S = C(5,2) = 10；无结
        # var_S = 5·4·15/18 = 300/18；z = (S−1)/√var_S = 9/4.0825 = 2.20454
        # p = 2(1−Φ(2.20454)) = 0.02749 < 0.05 → increasing
        series = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert _brute_force_s(series) == 10
        mk = mann_kendall(series)
        assert mk["n"] == 5
        assert mk["S"] == 10
        assert mk["var_S"] == pytest.approx(300.0 / 18.0)
        assert mk["z"] == pytest.approx(9.0 / math.sqrt(300.0 / 18.0))
        assert mk["z"] == pytest.approx(2.2045, abs=1e-3)  # 手算文字钉
        assert mk["p"] == pytest.approx(0.02749, abs=1e-4)
        assert mk["trend"] == "increasing"

    def test_monotone_decreasing_z_symmetric(self):
        mk = mann_kendall([5.0, 4.0, 3.0, 2.0, 1.0])
        assert mk["S"] == -10
        assert mk["z"] == pytest.approx(-2.2045, abs=1e-3)
        assert mk["trend"] == "decreasing"

    def test_tie_correction_hand_pinned(self):
        # 手算：[1,2,2,4] 逐对符号 → S = 1+1+1+0+1+1 = 5
        # 结组 t=2（两个 2）→ var_S = (4·3·13 − 2·1·9)/18 = 138/18
        # z = (5−1)/√(138/18) = 1.4444
        series = [1.0, 2.0, 2.0, 4.0]
        assert _brute_force_s(series) == 5
        mk = mann_kendall(series)
        assert mk["S"] == 5
        assert mk["var_S"] == pytest.approx(138.0 / 18.0)
        assert mk["z"] == pytest.approx(4.0 / math.sqrt(138.0 / 18.0))
        assert mk["trend"] == "no_trend"  # p ≈ 0.1486 > 0.05

    def test_all_equal_var_zero_guard(self):
        # 全结 → S=0 且 var_S=0（tie 项吃满）→ z=0/p=1 守卫分支
        mk = mann_kendall([3.0, 3.0, 3.0])
        assert mk["S"] == 0
        assert mk["var_S"] == 0.0
        assert mk["z"] == 0.0
        assert mk["p"] == 1.0
        assert mk["trend"] == "no_trend"

    def test_alpha_override_flips_trend(self):
        # z=2.2045 → p=0.0275：alpha=0.02 时不再显著
        assert mann_kendall([1, 2, 3, 4, 5], alpha=0.02)["trend"] == "no_trend"
        assert mann_kendall([1, 2, 3, 4, 5], alpha=0.05)["trend"] == (
            "increasing")

    def test_bool_and_non_numeric_rejected(self):
        with pytest.raises(ValueError, match="bool"):
            mann_kendall([True, False, True])
        with pytest.raises(ValueError, match="非数值"):
            mann_kendall([1.0, "2", 3.0])  # type: ignore[list-item]

    def test_non_finite_and_short_rejected(self):
        with pytest.raises(ValueError, match="非有限"):
            mann_kendall([1.0, float("nan"), 2.0])
        with pytest.raises(ValueError, match="至少需要 3"):
            mann_kendall([1.0, 2.0])
        with pytest.raises(ValueError, match="至少需要 3"):
            mann_kendall([])


# ─── drift_fingerprint：字面钉 + numpy 独立对拍 ─────────────────────────────

class TestDriftFingerprint:
    def test_literal_pin(self):
        # 手算：mean=2.5；样本 std=√(5/3)=1.29099；median=2.5
        # q25: pos=0.75 → 1+0.75·1=1.75；q75: pos=2.25 → 3+0.25·1=3.25
        fp = drift_fingerprint([1.0, 2.0, 3.0, 4.0])
        assert fp["n"] == 4
        assert fp["mean"] == pytest.approx(2.5)
        assert fp["std"] == pytest.approx(math.sqrt(5.0 / 3.0))
        assert fp["median"] == pytest.approx(2.5)
        assert fp["q25"] == pytest.approx(1.75)
        assert fp["q75"] == pytest.approx(3.25)
        assert fp["iqr"] == pytest.approx(1.5)

    def test_quantiles_match_numpy_independent(self):
        values = [3.1, -0.5, 2.7, 1.0, 9.4, 0.0, -2.2, 5.5, 1.618]
        fp = drift_fingerprint(values)
        np_q = np.percentile(values, [25, 50, 75], method="linear")
        assert fp["q25"] == pytest.approx(float(np_q[0]))
        assert fp["median"] == pytest.approx(float(np_q[1]))
        assert fp["q75"] == pytest.approx(float(np_q[2]))

    def test_single_value_std_zero(self):
        fp = drift_fingerprint([7.0])
        assert fp["n"] == 1
        assert fp["std"] == 0.0
        assert fp["mean"] == 7.0

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="空序列"):
            drift_fingerprint([])

    def test_bool_rejected(self):
        with pytest.raises(ValueError, match="bool"):
            drift_fingerprint([True, False])


# ─── anchor_drift_report：组合 verdict ──────────────────────────────────────

class TestReportSeriesMode:
    def test_trend_plus_shift_drifted(self):
        # 劈半 mean 1→4.5 + MK p=0.0275 双线成立 → drifted
        out = anchor_drift_report([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        assert out["ok"] is True
        assert out["verdict"] == "drifted"
        assert out["mode"] == "series"
        assert out["trend"]["trend"] == "increasing"
        assert out["fingerprint_shift"]["shift_flag"] is True

    def test_shift_only_warning(self):
        # [0,1,0,1,0,10,0,10]：手算逐对符号 S=8（暴力枚举复核）、
        # 结组 {0:4,1:2,10:2} → var_S = (8·7·21 − (4·3·13+2·1·9+2·1·9))/18
        # = 984/18 = 54.667；z = (8−1)/7.394 = 0.947 → p ≈ 0.344 不显著；
        # 劈半 mean 0.5→5 + std 0.577→5.77 双越限 → 指纹差分线单线成立
        # → warning
        series = [0.0, 1.0, 0.0, 1.0, 0.0, 10.0, 0.0, 10.0]
        assert _brute_force_s(series) == 8
        out = anchor_drift_report(series)
        assert out["verdict"] == "warning"
        assert out["trend"]["trend"] == "no_trend"
        assert out["trend"]["S"] == 8
        assert out["trend"]["var_S"] == pytest.approx(984.0 / 18.0)
        assert out["fingerprint_shift"]["shift_flag"] is True

    def test_stable(self):
        # 手算 S=−4（暴力枚举复核）、z=(−4+1)/√(28.333)=−0.564 → p≈0.573；
        # 劈半 mean −0.05→0.05（尺度归一后 0.12<0.5）+ std 比 0.855 ∈
        # (0.5, 2) → 两线皆不成立 → stable
        series = [1.0, -0.5, 0.3, -1.0, 0.8, -0.2, -0.9, 0.5]
        assert _brute_force_s(series) == -4
        out = anchor_drift_report(series)
        assert out["verdict"] == "stable"
        assert out["fingerprint_shift"]["mean_shift_flag"] is False
        assert out["fingerprint_shift"]["std_flag"] is False

    def test_insufficient_and_no_data(self):
        out = anchor_drift_report([1.0, 2.0, 3.0])
        assert out["verdict"] == "insufficient"
        assert out["trend"] is None
        assert out["fingerprint"]["n"] == 3
        out_empty = anchor_drift_report([])
        assert out_empty["verdict"] == "no_data"
        assert out_empty["ok"] is True

    def test_thresholds_configurable(self):
        # 0.5→5 均值跳变在缺省阈值下 flag；阈值放宽到 20 后不 flag
        series = [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 5.0, 5.0]
        tight = anchor_drift_report(series)
        loose = anchor_drift_report(series, mean_shift_rel_max=20.0,
                                    std_ratio_max=100.0)
        assert tight["fingerprint_shift"]["shift_flag"] is True
        assert loose["verdict"] == "stable"


class TestReportSnapshotMode:
    def test_two_snapshot_step_warning(self):
        # 两快照：只有指纹差分线可用（<3 无 MK 线）→ 单线上限 warning
        snaps = [{"at": "t0", "values": [0.0, 0.0, 0.0, 0.0]},
                 {"at": "t1", "values": [10.0, 10.0, 10.0, 10.0]}]
        out = anchor_drift_report(snaps)
        assert out["verdict"] == "warning"
        assert out["mode"] == "snapshots"
        assert out["n_snapshots"] == 2
        assert out["fingerprint_shift"]["snapshot_first_at"] == "t0"
        assert out["fingerprint_shift"]["snapshot_last_at"] == "t1"

    def test_single_snapshot_insufficient(self):
        out = anchor_drift_report([{"values": [1.0, 1.0, 1.0]}])
        assert out["verdict"] == "insufficient"
        assert out["reasons"][0].startswith("快照数 1")

    def test_five_snapshots_rising_drifted(self):
        # 快照均值序列 [1..5]：MK z=2.2045（同手算钉）显著 + 首末指纹差分
        # （mean 1→5，尺度归一 4>0.5）双线成立 → drifted
        snaps = [{"at": f"t{i}", "values": [float(i)] * 3}
                 for i in range(1, 6)]
        out = anchor_drift_report(snaps)
        assert out["verdict"] == "drifted"
        assert out["trend"]["trend"] == "increasing"
        assert out["trend"]["z"] == pytest.approx(2.2045, abs=1e-3)
        assert out["n_points"] == 15

    def test_flat_snapshots_stable(self):
        snaps = [{"values": [1.0, 1.0, 1.0]} for _ in range(4)]
        out = anchor_drift_report(snaps)
        assert out["verdict"] == "stable"

    def test_mixed_input_rejected(self):
        with pytest.raises(ValueError, match="混搭"):
            anchor_drift_report([1.0, {"values": [2.0]}])

    def test_bad_snapshot_shape_rejected(self):
        with pytest.raises(ValueError, match="缺 values"):
            anchor_drift_report([{"at": "t0"}])
