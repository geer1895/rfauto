"""core/filter_temp_drift.py 单测（MT-8 谐振频率温漂）。

判据（#118 双路径）：
- 闭式 τ_f vs f ∝ 1/(L√ε) 数值差分（独立路径）逐位一致；
- 双路径（闭式一阶 vs dk_at_temperature 精确根链）小 ΔT 收敛 + 偏离随
  ΔT 增长量化；
- material_library 消费面（ro3003 真条目 + 温度域守卫 + KeyError）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

import pytest

from rfauto.core.filter_temp_drift import (
    drift_from_material,
    laminate_resonance_drift,
    resonant_frequency_at_temperature,
    tcf_from_tcdk_cte,
)
from rfauto.core.material_library import dk_at_temperature


class TestTcfClosedForm:
    def test_dr_classic(self):
        # τ_f = −(α_L + τ_ε/2)：τ_ε=−6、α=10 → −7（DR 零漂设计组量级）
        assert tcf_from_tcdk_cte(-6.0, 10.0) == -7.0
        # τ_ε=0 → τ_f=−α 逐位
        assert tcf_from_tcdk_cte(0.0, 12.0) == -12.0

    def test_s_eps_partial_field(self):
        # s_ε=0.5：介电项减半
        assert tcf_from_tcdk_cte(-60.0, 10.0, 0.5) == -(10.0 - 15.0)
        assert tcf_from_tcdk_cte(-60.0, 10.0, 0.5) == 5.0
        # s_ε=0：纯机械膨胀
        assert tcf_from_tcdk_cte(-60.0, 10.0, 0.0) == -10.0

    def test_s_eps_guard(self):
        for bad in (-0.1, 1.1):
            try:
                tcf_from_tcdk_cte(-3.0, 15.0, bad)
            except ValueError:
                continue
            raise AssertionError(f"s_eps={bad!r} 应报 ValueError")

    def test_closed_form_vs_finite_difference(self):
        """闭式 vs f(T)=k/(L(T)·√ε(T)) 的对数差分（独立路径，1e-6）。"""
        tc, cte, s = -30.0, 12.0, 1.0
        tcf = tcf_from_tcdk_cte(tc, cte, s)
        eps0, l0 = 9.5, 10e-3

        def f_of_t(dt_c: float) -> float:
            eps = eps0 * (1.0 + tc * 1e-6 * dt_c)
            length = l0 * (1.0 + cte * 1e-6 * dt_c)
            return 1.0 / (length * math.sqrt(eps))

        h = 1e-3
        dlnf = (math.log(f_of_t(h)) - math.log(f_of_t(-h))) / (2.0 * h)
        assert abs(dlnf * 1e6 - tcf) < 1e-4


class TestTwoPath:
    def test_identity_at_zero_delta_t(self):
        r = drift_from_material(3.0, -3.0, 15.0, 0.0)
        assert r["f_ratio_closed_form"] == 1.0
        assert r["f_ratio_exact_root_chain"] == 1.0
        assert r["two_path_dev_ppm"] == 0.0

    def test_root_chain_consumes_dk_at_temperature(self):
        """路径②的 ε(T) 与 material_library.dk_at_temperature 直调逐位同。"""
        r = drift_from_material(3.0, -3.0, 15.0, 60.0, t_ref_c=23.0)
        dk_t = dk_at_temperature(3.0, -3.0, 83.0, t_ref_c=23.0)
        assert r["dk_at_t"] == round(dk_t, 15)
        expect = math.sqrt(3.0 / dk_t) / (1.0 + 15.0 * 1e-6 * 60.0)
        assert abs(r["f_ratio_exact_root_chain"] - round(expect, 15)) < 1e-15

    def test_two_path_convergence_and_growth(self):
        """小 ΔT 双路径差 →0（O(ΔT²)）；ΔT 增大偏离单调增长（量化登记）。"""
        devs = []
        for dt in (1.0, 10.0, 100.0, 400.0):
            r = drift_from_material(3.0, 300.0, 20.0, dt)  # 大 τ_ε 拉开差
            devs.append(abs(r["two_path_dev_ppm"]))
        assert devs[0] < 1.0
        assert devs == sorted(devs) and devs[-1] > 100 * devs[0]

    def test_first_order_frequency_shift(self):
        # ΔT=0 逐位；一阶线性口径
        assert resonant_frequency_at_temperature(2.45e9, -13.5, 0.0) == 2.45e9
        f = resonant_frequency_at_temperature(2.45e9, -13.5, 100.0)
        assert abs(f - 2.45e9 * (1.0 - 13.5e-4)) < 1e-3


class TestLaminateConsumption:
    def test_ro3003_real_entry(self):
        r = laminate_resonance_drift("rogers_ro3003", 24.0e9, 60.0, 15.0)
        assert r["laminate_id"] == "rogers_ro3003"
        assert r["tcdk_ppm_c"] == -3.0
        assert r["tcf_ppm_c"] == -13.5
        assert r["dk_source"] == "dk_design"
        assert r["f_at_t_hz"] < 24.0e9  # 负 τ_f 升温降频
        assert "dk_at_temperature" in r["consumes"]

    def test_temperature_domain_guard_propagates(self):
        """ro3003 域 [−50,150]°C：ΔT=200 → 223°C 超域 → ValueError 不外推。"""
        with pytest.raises(ValueError, match=r"外推|domain|域"):
            laminate_resonance_drift("rogers_ro3003", 24.0e9, 200.0, 15.0)

    def test_unknown_laminate(self):
        with pytest.raises(KeyError):
            laminate_resonance_drift("no_such_board", 1e9, 10.0, 15.0)

    def test_cte_guard(self):
        with pytest.raises(ValueError):
            laminate_resonance_drift("rogers_ro3003", 24.0e9, 10.0,
                                     float("nan"))
