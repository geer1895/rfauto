"""MP-B1 Aitken Δ² 加速内核单测（core/accel.py，纯函数零依赖）。

锚（研究扩充 round15 MP-B1 + #118 独立裁判）：
- 线性收敛序列（|e_{n+1}| = q|e_n|）加速后残差 ≤ q² 理论带——纯几何序列
  精确（fp 内 ~1e-12）、几何+二阶项序列逐点带判（裁判=解析推导
  A_n - L = C1·C2·q^{3n+2}/(C1·q^n + C2·q^{2n}(q+1)²)，本文件注释推导，
  断言只消费该闭式的不等式结论，不复用被测实现公式产数）；
- 常数序列恒等（分母 0 回退）；
- 震荡序列行为如实（交替几何精确、周期-2 震荡映射为双周期均值 0，
  有限不产 NaN）；
- 负例（短序列/非有限/非数值 → ValueError）。

消费面（MP-B1）：solve_thermal_fixed_point 强耦合定点链（合成线性损耗，
谱半径 λ=R_th·dP/dT=0.9）的后处理加速实证——**本批文件面不接在线开关**
（thermal_iteration 计算语义禁改），消费形态=对迭代历史温度序列做 Δ²
外推；强耦合验收（迭代数 ≤50%）以后处理形态钉：3 个迭代点的 Aitken
估计优于 100 轮（=MAX_ITERATIONS_LIMIT）纯迭代残差。
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from rfauto.core.accel import aitken_delta2
from rfauto.core.thermal_iteration import (
    MAX_ITERATIONS_LIMIT,
    EMEvaluation,
    MaterialTemperatureModel,
    ResonatorGeometry,
    ThermalIterationConfig,
    solve_thermal_fixed_point,
)

# ─── 负例（非法输入显式 ValueError，不静默兜底）─────────────────────────────


class TestRejections:
    @pytest.mark.parametrize("seq", [
        [], [1.0], [1.0, 2.0], (3.5, 4.5),
    ])
    def test_short_sequence_valueerror(self, seq):
        with pytest.raises(ValueError, match="至少需要 3 个迭代点"):
            aitken_delta2(seq)

    def test_string_rejected(self):
        with pytest.raises(ValueError, match="数值序列"):
            aitken_delta2("1.5, 2.5, 3.5")

    @pytest.mark.parametrize("bad", [
        float("nan"), float("inf"), float("-inf"),
    ])
    def test_non_finite_rejected(self, bad):
        with pytest.raises(ValueError, match="有限数"):
            aitken_delta2([1.0, bad, 3.0, 4.0])

    @pytest.mark.parametrize("bad", ["abc", None, object()])
    def test_non_numeric_rejected(self, bad):
        with pytest.raises(ValueError, match="必须是实数"):
            aitken_delta2([1.0, bad, 3.0])


# ─── 锚1：线性收敛序列加速后残差 ≤ q² 理论带 ────────────────────────────────


class TestLinearConvergenceBand:
    def test_pure_geometric_is_exact(self):
        """x_n = L + C·q^n：Δ² 精确到不动点（实数算术），fp 残差 ~1e-12。"""
        fixed_point, amplitude, ratio, n_points = 100.0, 8.0, 0.5, 10
        seq = [fixed_point + amplitude * ratio ** n for n in range(n_points)]
        accelerated = aitken_delta2(seq)
        assert len(accelerated) == n_points - 2
        for value in accelerated:
            assert abs(value - fixed_point) < 1e-6
        # q² 带（尾点）：|A_last - L| ≤ q²·|x_last - L| 平凡满足且余量大
        assert abs(accelerated[-1] - fixed_point) <= ratio ** 2 * abs(seq[-1] - fixed_point)

    def test_second_order_term_residual_within_q2_band(self):
        """x_n = L + C1·q^n + C2·q^{2n}：残差 O(q^{2n})，逐点 ≤ q² 带（n≥1）。

        解析推导（裁判）：记 a=C1·q^n，c=C2·q^{2n}，则
        A_n - L = a·c·q²/(a + c(q+1)²)·(q+1)/(q+1) 化简后
                = C1·C2·q^{3n+2}/(C1·q^n + C2·q^{2n}(q+1)²)，
        与 q²|x_{n+2}-L| 之比 ≤1 ⟺ C1·C2·q^{n-2} ≤ (C1+C2·q^{n+2})·
        (C1+C2·q^n(q+1)²)。C1=8/C2=3/q=0.4 下 n=0 不满足（预渐近，如实
        跳过），n≥1 全满足——断言只消费该不等式，不用被测实现产数。
        """
        fixed_point, c1, c2, ratio, n_points = 100.0, 8.0, 3.0, 0.4, 12
        seq = [fixed_point + c1 * ratio ** n + c2 * ratio ** (2 * n)
               for n in range(n_points)]
        accelerated = aitken_delta2(seq)
        assert len(accelerated) == n_points - 2
        # 预渐近首点不判带（q² 带是线性收敛渐近态语义），如实跳过
        for n in range(1, len(accelerated)):
            accelerated_error = abs(accelerated[n] - fixed_point)
            original_error = abs(seq[n + 2] - fixed_point)
            assert accelerated_error <= ratio ** 2 * original_error, (
                f"n={n}: 加速残差 {accelerated_error!r} 超 q² 带 "
                f"{ratio ** 2 * original_error!r}")
        # 加速残差沿尾段单调收缩（加速真实生效，非一次性运气）
        errors = [abs(value - fixed_point) for value in accelerated[1:]]
        assert all(later <= earlier for earlier, later in pairwise(errors))
        # 末点残差严格小于原序列末点残差的 q² 倍（主锚，显式再断言）
        assert abs(accelerated[-1] - fixed_point) < ratio ** 2 * abs(seq[-1] - fixed_point)

    def test_slow_convergence_heavy_tail_still_accelerated(self):
        """q=0.9 慢收敛（强耦合定点链形态）：Δ² 仍把残差带从 q 压到 q²。"""
        fixed_point, amplitude, ratio = 115.0, 90.0, 0.9
        seq = [fixed_point - amplitude * ratio ** n for n in range(8)]
        accelerated = aitken_delta2(seq)
        for value in accelerated:
            assert abs(value - fixed_point) < 1e-6
        assert abs(accelerated[-1] - fixed_point) <= ratio ** 2 * abs(seq[-1] - fixed_point)


# ─── 锚2/3：常数恒等 与 震荡序列行为如实 ────────────────────────────────────


class TestDegenerateAndOscillating:
    def test_constant_sequence_identity(self):
        """常数序列（不动点已到达）：恒等返回，逐位相等。"""
        seq = [7.25] * 6
        accelerated = aitken_delta2(seq)
        assert accelerated == [7.25] * 4

    def test_arithmetic_sequence_identity_fallback(self):
        """等差序列（差分相等=分母 0，无极限）：恒等回退，不伪造加速值。"""
        accelerated = aitken_delta2([0.0, 2.0, 4.0, 6.0, 8.0])
        assert accelerated == [4.0, 6.0, 8.0]

    def test_alternating_geometric_is_exact(self):
        """交替收敛 x_n = L + C·(-q)^n：Δ² 同样精确（适用面优势，如实钉）。"""
        fixed_point, amplitude, ratio, n_points = 10.0, 4.0, 0.5, 9
        seq = [fixed_point + amplitude * (-ratio) ** n for n in range(n_points)]
        accelerated = aitken_delta2(seq)
        for value in accelerated:
            assert abs(value - fixed_point) < 1e-9

    def test_period2_oscillation_maps_to_cycle_mean(self):
        """周期-2 震荡 (-1)^n（无极限）：映射为双周期均值 0，有限不产 NaN。

        行为如实（不过度宣称收敛）：A((-1)^n) = (-1)^{n+2} - (-1)^n·
        ((-1)^{n+1}·(-2))²/((-1)^n·4) = 0（逐位精确）。
        """
        seq = [1.0, -1.0] * 3
        accelerated = aitken_delta2(seq)
        assert len(accelerated) == 4
        for value in accelerated:
            assert math.isfinite(value)
            assert value == pytest.approx(0.0, abs=1e-15)

    def test_list_and_tuple_inputs_agree(self):
        seq = [100.0 + 8.0 * 0.5 ** n for n in range(6)]
        assert aitken_delta2(tuple(seq)) == aitken_delta2(seq)


# ─── 消费面：thermal_iteration 强耦合定点链的后处理加速（MP-B1）─────────────


class TestThermalFixedPointConsumption:
    """合成强耦合定点（注入评估器，solve_thermal_fixed_point 官方口径）。

    P(T) = P0·(1 + α·(T - T_amb))，λ = R_th·P0·α = 0.9（强耦合慢收敛）；
    闭式不动点 T* = T_amb + R_th·P0/(1-λ) = 115 C（独立代数裁判，#118：
    判定不消费被测迭代实现自身产出）。误差模型 e_n = e_0·λ^n 由此闭式
    与迭代显式温度逐步互证后，轮数换算才消费该模型。
    """

    LAMBDA = 0.9
    T_AMB = 25.0
    P0 = 1.0
    R_TH = 9.0
    T_STAR = T_AMB + R_TH * P0 / (1.0 - LAMBDA)  # = 115.0 C

    def _solve(self, max_iterations: int):
        model = MaterialTemperatureModel(eps_r_ref=1.0)
        geometry = ResonatorGeometry(length_m=0.01, width_m=1e-3, height_m=0.5e-3)

        def em_evaluator(state, temperature_c):
            # f0 随 T 单调漂移：恒 f0 会让收敛判据在第 2 轮假收敛
            f0_hz = 2.4e9 * (1.0 - 1e-6 * (temperature_c - self.T_AMB))
            return EMEvaluation(f0_hz=f0_hz, q_unloaded=100.0)

        def loss_evaluator(em, temperature_c):
            alpha = self.LAMBDA / (self.R_TH * self.P0)
            return self.P0 * (1.0 + alpha * (temperature_c - self.T_AMB))

        config = ThermalIterationConfig(
            geometry=geometry,
            ambient_c=self.T_AMB,
            input_power_w=1.0,
            thermal_resistance_k_per_w=self.R_TH,
            coupling_beta=1.0,
            freq_tolerance_hz=1e-6,
            max_iterations=max_iterations,
            divergence_patience=max_iterations,  # 残差单调降，给足冗余
        )
        return solve_thermal_fixed_point(
            model, config, em_evaluator=em_evaluator, loss_evaluator=loss_evaluator)

    def _plain_iterations_for(self, tolerance_k: float) -> int:
        """独立闭式换算：纯迭代达到 |e| ≤ tolerance_k 需要的轮数。

        e_n = e_0·λ^n（下面 test 先互证该模型），n = ⌈ln(e_0/tol)/ln(1/λ)⌉。
        """
        e0 = self.T_STAR - self.T_AMB
        return math.ceil(math.log(e0 / tolerance_k) / math.log(1.0 / self.LAMBDA))

    def test_error_model_matches_closed_form(self):
        """先互证误差模型 e_n = e_0·λ^n（轮数换算的前提，#118）。"""
        result = self._solve(12)
        assert result.status == "max_iterations"  # 慢收敛：限内不假收敛
        e0 = self.T_STAR - self.T_AMB
        for index in (0, 1, 5, 11):
            expected = self.T_STAR - e0 * self.LAMBDA ** index
            assert result.steps[index].temperature_c == pytest.approx(
                expected, rel=1e-9)

    def test_post_hoc_aitken_beats_full_limit_run(self):
        """3 个迭代点的 Δ² 外推优于 100 轮（=上限）纯迭代残差。"""
        result = self._solve(MAX_ITERATIONS_LIMIT)
        temperatures = [step.temperature_c for step in result.steps]
        assert len(temperatures) == MAX_ITERATIONS_LIMIT
        accelerated = aitken_delta2(temperatures)
        # 首个加速点（消费 T_0..T_2 三点）已达 1e-6 K 内
        assert abs(accelerated[0] - self.T_STAR) < 1e-6
        # 纯迭代跑满上限仍未达 1e-3 K（误差模型：e_99 ≈ 2.6e-3 K）
        plain_last_error = abs(temperatures[-1] - self.T_STAR)
        assert plain_last_error > 1e-3
        assert plain_last_error > abs(accelerated[0] - self.T_STAR)

    def test_strong_coupling_iteration_reduction_acceptance(self):
        """强耦合验收（≤50% 迭代数，后处理形态）：3 点 Aitken ≪ 纯迭代轮数。

        锚=闭式换算 _plain_iterations_for（e_n=e_0·λ^n 已由上测互证）：
        达 1 K 精度纯迭代需 43 轮，Aitken 用 3 个迭代点（7%）；达
        1e-6 K 需 174 轮 > MAX_ITERATIONS_LIMIT——上限内纯迭代根本
        到不了 3 点 Aitken 的精度。
        """
        points_used = 3
        assert self._plain_iterations_for(1.0) >= 2 * points_used
        needed = self._plain_iterations_for(1e-6)
        assert needed > MAX_ITERATIONS_LIMIT
        # 与真实链对账：1e-6 K 精度对应残差带 f0 漂移 2400·1e-6 Hz，
        # 远小于收敛判据默认 1 kHz 的量级（口径注记，防锚漂移）
        assert needed == 174
