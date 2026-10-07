"""core/pim_empirical.py 单测（NX-12 PIM 阶数/功率经验面）。

判据（#118 双源：幂级数可复算推导=源① + 文献登记=源②）：
- 幂级数 i(v)=v+εv³ 双音整数周期 DFT（零泄漏）实测斜率 vs 闭式
  ΔP=m·ΔP₁+n·ΔP₂（IM3 3dB/dB、单音 2dB/dB、IM5 5dB/dB）；
- 经验外推闭式自洽（dBm↔dBc 基换算）+ 斜率守卫；
- pim_products/multipactor 消费面互证 + no-go 登记面。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.pim_empirical import (
    IM3_POWER_SLOPE_DB_PER_DB,
    extrapolate_pim3,
    no_go_registry,
    pim_products_power_note,
    product_level_shift_db,
    product_power_shift,
    satellite_multipactor_annotation,
)
from rfauto.core.pim_products import enumerate_pim_products

# ─── 源①：幂级数数值裁判（可复算推导的独立路径） ─────────────────────────


def _im_bin_amplitude(n_fft: int, bin_index: int, signal: np.ndarray) -> float:
    spec = np.fft.rfft(signal)
    return float(np.abs(spec[bin_index])) * 2.0 / n_fft


def _power_series_two_tone(g1: float, g2: float, eps3: float = 0.05,
                           eps5: float = 0.0):
    """i(v)=v+ε₃·v³(+ε₅·v⁵)，f1=bin13/f2=bin17（整数周期，零泄漏）。"""
    n = 8192
    t = np.arange(n) / n
    v = g1 * 0.7 * np.cos(2 * math.pi * 13 * t) \
        + g2 * 0.4 * np.cos(2 * math.pi * 17 * t)
    return n, v + eps3 * v**3 + eps5 * v**5


class TestPowerSeriesSlope:
    def test_im3_both_carriers_3db_per_db(self):
        g = 10.0 ** (1.0 / 20.0)  # 载波 +1 dB
        n0, i0 = _power_series_two_tone(1.0, 1.0)
        n1, i1 = _power_series_two_tone(g, g)
        a0 = _im_bin_amplitude(n0, 2 * 13 - 17, i0)   # 2f1−f2 → bin 9
        a1 = _im_bin_amplitude(n1, 2 * 13 - 17, i1)
        slope = 20.0 * math.log10(a1 / a0)
        assert abs(slope - 3.0) < 1e-6

    def test_im3_single_carrier_2db_per_db(self):
        g = 10.0 ** (1.0 / 20.0)
        n0, i0 = _power_series_two_tone(1.0, 1.0)
        n1, i1 = _power_series_two_tone(g, 1.0)       # 只升 f1
        a0 = _im_bin_amplitude(n0, 2 * 13 - 17, i0)
        a1 = _im_bin_amplitude(n1, 2 * 13 - 17, i1)
        assert abs(20.0 * math.log10(a1 / a0) - 2.0) < 1e-6

    def test_im5_both_carriers_5db_per_db(self):
        """IM5 (3f1−2f2) 只由五次项产生——系列含 ε₅ 才有该产物。"""
        g = 10.0 ** (1.0 / 20.0)
        n0, i0 = _power_series_two_tone(1.0, 1.0, eps5=0.02)
        n1, i1 = _power_series_two_tone(g, g, eps5=0.02)
        bin5 = 3 * 13 - 2 * 17                         # 3f1−2f2 → bin 5
        a0 = _im_bin_amplitude(n0, bin5, i0)
        a1 = _im_bin_amplitude(n1, bin5, i1)
        assert a0 > 0.0
        assert abs(20.0 * math.log10(a1 / a0) - 5.0) < 1e-4


class TestClosedForms:
    def test_product_level_shift(self):
        assert product_level_shift_db(2, 1, 1.0, 1.0) == 3.0
        assert product_level_shift_db(2, 1, 1.0, 0.0) == 2.0
        assert product_level_shift_db(3, 2, 1.0, 1.0) == 5.0
        assert product_level_shift_db(2, 1, 0.0, -2.0) == -2.0

    def test_shift_guards(self):
        for bad in (0, -1, 2.5, True):
            try:
                product_level_shift_db(bad, 1, 0.0, 0.0)
            except ValueError:
                continue
            raise AssertionError(f"m={bad!r} 应报 ValueError")
        try:
            product_level_shift_db(60, 60, 0.0, 0.0)  # 超 MAX_PIM_ORDER
        except ValueError:
            pass
        else:
            raise AssertionError("m+n 超防呆上限应报 ValueError")

    def test_extrapolate_pim3_identity_at_ref(self):
        """参考点自检：P=P_ref → 平移零（dBm=dbc+P_ref 逐位）。"""
        r = extrapolate_pim3(-153.0, 43.0, 43.0)
        assert r["pim_dbm"] == -110.0
        assert r["pim_dbc"] == -153.0
        assert r["slope_db_per_db"] == IM3_POWER_SLOPE_DB_PER_DB == 3.0

    def test_extrapolate_pim3_both_bases_consistent(self):
        r = extrapolate_pim3(-110.0, 43.0, 46.0)
        assert r["pim_dbm"] == -58.0          # −110+43+3·3
        assert r["pim_dbc"] == -104.0         # −110+(3−1)·3
        # dBm↔dBc 基自洽：pim_dbm − P = pim_dbc
        assert abs(r["pim_dbm"] - 46.0 - r["pim_dbc"]) < 1e-12

    def test_slope_registration_and_guard(self):
        r = extrapolate_pim3(-110.0, 43.0, 50.0, slope_db_per_db=2.4)
        assert abs(r["pim_dbm"] - (-110.0 + 43.0 + 2.4 * 7.0)) < 1e-9
        assert abs(r["pim_dbc"] - (-110.0 + 1.4 * 7.0)) < 1e-9
        for bad in (0.5, 7.0, float("inf")):
            with pytest.raises(ValueError, match="slope"):
                extrapolate_pim3(-110.0, 43.0, 46.0, slope_db_per_db=bad)

    def test_product_power_shift_rebasing(self):
        r = product_power_shift(2, 1, 1.0, 1.0, -110.0)
        assert r["level_shift_db"] == 3.0
        assert r["dbc_at_new_power"] == -108.0  # −110+3−1（dBc 参考 f₁）


class TestConsumptionFaces:
    def test_pim_products_power_note(self):
        """枚举+实测归并产核在 pim_products；本面只附 (m,n) 平移注记。"""
        amps = [{"m": 2, "n": 1, "side": "-", "dbc": -110.0}]
        r = pim_products_power_note(2.4e9, 2.41e9, p_max=3, dp1_db=1.0,
                                    dp2_db=1.0, amplitudes=amps)
        assert r["n_products"] == 6
        assert r["n_with_measured_dbc"] == 1
        note = r["power_shift_notes"][0]
        assert note["key"] == {"m": 2, "n": 1, "side": "-"}
        assert note["level_shift_db"] == 3.0
        assert note["dbc_at_new_power"] == -108.0
        # 未给实测 → 0 注记（铁律 7：无实测不产数）
        r0 = pim_products_power_note(2.4e9, 2.41e9, p_max=3)
        assert r0["n_with_measured_dbc"] == 0 and r0["power_shift_notes"] == []

    def test_note_matches_enumerated_product(self):
        ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3)
        target = next(p for p in ps.products
                      if (p.m, p.n, p.side) == (2, 1, "-"))
        assert abs(target.f_hz - 2.39e9) < 1e-6  # 产核仍在 pim_products

    def test_no_go_registry(self):
        reg = no_go_registry()
        ids = {x["id"] for x in reg}
        assert ids == {"no_absolute_pim_prediction",
                       "no_ncarrier_enumeration_here",
                       "no_multipactor_pim_synthesis",
                       "no_real_machine_claim"}
        assert all("真机" in x["statement"] or "不可" in x["statement"]
                   or "EM-6" in x["statement"] or "独立" in x["statement"]
                   for x in reg)

    def test_satellite_multipactor_annotation(self):
        r = satellite_multipactor_annotation(8.4e9, 0.5e-3, [10.0, 10.0])
        assert r["equivalent"]["n_carriers"] == 2
        assert r["equivalent"]["convention"] == "incoherent_rss"
        # 消费面一致性：等效功率 = ΣPi（非相干）
        assert abs(r["equivalent"]["equivalent_power_w"] - 20.0) < 1e-9
        # verdict/margin 字段存在（multipactor_susceptibility_check 透传）
        assert "pass" in r["multipactor"] or "verdict" in r["multipactor"]

    def test_satellite_annotation_coherent_ge_incoherent(self):
        inc = satellite_multipactor_annotation(8.4e9, 0.5e-3, [10.0, 10.0])
        coh = satellite_multipactor_annotation(8.4e9, 0.5e-3, [10.0, 10.0],
                                               coherent=True)
        assert (coh["equivalent"]["equivalent_power_w"]
                >= inc["equivalent"]["equivalent_power_w"])

    def test_satellite_annotation_guards(self):
        with pytest.raises(ValueError):
            satellite_multipactor_annotation(8.4e9, 0.5e-3, [])
        with pytest.raises(ValueError):
            satellite_multipactor_annotation(-1.0, 0.5e-3, [1.0])
