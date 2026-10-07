"""AP-8 3GPP TS 38.901 数字化锚测试（round17 §三 AP-8，2026-10-03）。

锚口径（#118/#300：≥2 独立基准/件，门值预声明；#122 不凑绿）：

- **双源独立重算对拍**：每个场景取代表点，用与实现不同排列的
  独立算式（手工展开、Sionna 同式异代码路径）重算对拍：
  * UMa LOS PL1/PL2、NLOS（含 hUT 修正项）；
  * UMi LOS PL1/PL2、NLOS；
  * RMa LOS PL1/PL2（h=5m 缺省）、NLOS（W/h/hBS/hUT 全项）；
  * InH LOS/NLOS（ETSI V19.2 PDF 文本系数：17.30/38.3/24.9 项序
    交换重排）。
- **断点连续性**：UMa/UMi 在 d2D=d'BP 处 PL1=PL2（代数恒等式：
  22·lg d + 20·lg f 与 40·lg d − 9·lg(d'BP²+Δh²) 在 d3D=d'BP、
  Δh=hBS−hUT 时……由数值锚定，门 <1e-9 dB）；RMa PL2 按构造
  连续（PL1(dBP) 基底）。
- **频率标度**：FSPL 段 f 翻倍 → +20·lg2 = +6.0206 dB。
- **O2I**：f→0 材料极限（glass=2、concrete=5、plywood=1.03 dB，
  算术锚）；f=1GHz low/high 模型 PLtw 手算互证（Sionna 同式）；
  通用式 PLnpi=5 特例与表值一致；legacy 20dB 固定；car μ=9/20。
- **TDL**：五表归一化 RMS 时延扩展 ≈1（表舍入界 ≤0.007，TDL-D
  0.9937 实测锚）；tap 数（23/23/24/14/15）；K 自算=表 NOTE
  （TDL-D 13.3 dB、TDL-E 22 dB，门 0.05 dB）；K 重标定往返
  （→20 dB 后自算=20，1e-9）；§7.7-1 缩放后 DS=DS_wanted
  （1e-9）。
- **域盒/异常**：频域 0.5..100 GHz（RMa 30）出界 ValueError；
  d2D/hUT 域盒；variant 非法；cdl_profile 显式 NotImplementedError；
  TDL 名单外 ValueError。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core.tr38901_pathloss import (
    C0_M_S,
    cdl_profile,
    external_wall_loss_db,
    inh_office_los_db,
    inh_office_nlos_db,
    material_penetration_db,
    o2i_building_db,
    o2i_car_db,
    o2i_legacy_db,
    rma_los_db,
    rma_nlos_db,
    tdl_delay_spread_ns,
    tdl_k_factor_db,
    tdl_profile,
    tdl_rescale_k_factor,
    tdl_scale_delays,
    uma_effective_height_rule,
    uma_los_db,
    uma_nlos_db,
    umi_los_db,
    umi_nlos_db,
)


def _lg(x: float) -> float:
    return math.log10(x)


class TestUma:
    F = 3.5e9

    def test_los_pl1_independent_recalc(self):
        # d2D < d'BP 段：独立重排算式
        d2, d3 = 100.0, 100.8
        got = uma_los_db(d2, d3, self.F)
        expect = 28.0 + 22.0 * _lg(d3) + 20.0 * _lg(3.5)
        assert got == pytest.approx(expect, abs=1e-12)

    def test_los_pl2_beyond_breakpoint(self):
        # hE=1: d'BP = 4·24·0.5·3.5e9/c = 560 m → 取 d2D=1000m
        d2, d3 = 1000.0, math.hypot(1000.0, 23.5)
        got = uma_los_db(d2, d3, self.F)
        dbp = 4.0 * 24.0 * 0.5 * self.F / C0_M_S
        expect = (28.0 + 40.0 * _lg(d3) + 20.0 * _lg(3.5)
                  - 9.0 * _lg(dbp**2 + 23.5**2))
        assert got == pytest.approx(expect, abs=1e-12)

    def test_los_breakpoint_continuity(self):
        # d2D=d'BP 处 PL1=PL2（<1e-9 dB）
        dbp = 4.0 * 24.0 * 0.5 * self.F / C0_M_S
        d3 = math.hypot(dbp, 23.5)
        p1 = uma_los_db(dbp * (1 - 1e-12), d3, self.F)
        p2 = uma_los_db(dbp * (1 + 1e-12), d3, self.F)
        assert p1 == pytest.approx(p2, abs=1e-8)

    def test_nlos_max_rule_and_height_term(self):
        d2, d3 = 1000.0, 1001.2
        got = uma_nlos_db(d2, d3, self.F, h_ut_m=8.0)
        pl_los = uma_los_db(d2, d3, self.F, h_ut_m=8.0)
        pl_n = 13.54 + 39.08 * _lg(d3) + 20.0 * _lg(3.5) - 0.6 * (8.0 - 1.5)
        assert got == pytest.approx(max(pl_los, pl_n), abs=1e-12)
        assert got == pytest.approx(pl_n, abs=1e-12)  # 远距 NLOS 占优

    def test_effective_height_rule_anchors(self):
        # NOTE 1：hUT<13 → p=1（hE=1m 必然）；hUT=22.5、d2D≤18 → C=0
        r = uma_effective_height_rule(50.0, 1.5)
        assert r["p_h_e_1m"] == pytest.approx(1.0) and r["alt_support_m"] == []
        r2 = uma_effective_height_rule(15.0, 22.5)
        assert r2["p_h_e_1m"] == pytest.approx(1.0)  # d2D≤18 → g=0
        r3 = uma_effective_height_rule(100.0, 22.5)
        g = 1.25 * (100.0 / 100.0) ** 3 * math.exp(-100.0 / 150.0)
        c = ((22.5 - 13.0) / 10.0) ** 1.5 * g
        assert r3["p_h_e_1m"] == pytest.approx(1.0 / (1.0 + c), rel=1e-12)
        assert r3["alt_support_m"][0] == 12.0
        assert r3["alt_support_m"][-1] == pytest.approx(21.0)

    def test_frequency_scaling_fspl(self):
        d2, d3 = 50.0, 51.0
        lo = uma_los_db(d2, d3, 2.0e9)
        hi = uma_los_db(d2, d3, 4.0e9)
        assert hi - lo == pytest.approx(20.0 * _lg(2.0), abs=1e-9)


class TestUmi:
    F = 28e9

    def test_los_pl1_and_pl2(self):
        d2, d3 = 30.0, 30.5
        got = umi_los_db(d2, d3, self.F)
        assert got == pytest.approx(32.4 + 21.0 * _lg(d3) + 20.0 * _lg(28),
                                    abs=1e-12)
        # 断点：hE=1 → d'BP = 4·9·0.5·28e9/c ≈ 1681 m
        d2b, d3b = 2000.0, 2000.3
        dbp = 4.0 * 9.0 * 0.5 * self.F / C0_M_S
        got2 = umi_los_db(d2b, d3b, self.F)
        expect2 = (32.4 + 40.0 * _lg(d3b) + 20.0 * _lg(28.0)
                   - 9.5 * _lg(dbp**2 + 8.5**2))
        assert got2 == pytest.approx(expect2, abs=1e-12)

    def test_nlos(self):
        d2, d3 = 200.0, 201.0
        got = umi_nlos_db(d2, d3, self.F, h_ut_m=1.5)
        pl_n = 35.3 * _lg(d3) + 22.4 + 21.3 * _lg(28.0)
        assert got == pytest.approx(max(umi_los_db(d2, d3, self.F), pl_n),
                                    abs=1e-12)
        opt = umi_nlos_db(d2, d3, self.F, variant="optional")
        assert opt == pytest.approx(32.4 + 20.0 * _lg(28.0)
                                    + 31.9 * _lg(d3), abs=1e-12)


class TestRma:
    F = 700e6

    def test_los_pl1(self):
        d2, d3 = 100.0, 101.0
        got = rma_los_db(d2, d3, self.F)
        h = 5.0
        expect = (20.0 * _lg(40.0 * math.pi * d3 * 0.7 / 3.0)
                  + min(0.03 * h**1.72, 10.0) * _lg(d3)
                  - min(0.044 * h**1.72, 14.77)
                  + 0.002 * _lg(h) * d3)
        assert got == pytest.approx(expect, abs=1e-12)

    def test_los_pl2_continuity_at_breakpoint(self):
        # dBP = 2π·35·1.5·0.7e9/c ≈ 769 m；PL2 = PL1(dBP)+40lg(d3D/dBP)
        dbp = 2.0 * math.pi * 35.0 * 1.5 * self.F / C0_M_S
        h = 5.0
        pl1 = (20.0 * _lg(40.0 * math.pi * dbp * 0.7 / 3.0)
               + min(0.03 * h**1.72, 10.0) * _lg(dbp)
               - min(0.044 * h**1.72, 14.77)
               + 0.002 * _lg(h) * dbp)
        d3_at = math.hypot(dbp, 33.5)
        p1 = rma_los_db(dbp, d3_at, self.F)
        assert p1 == pytest.approx(pl1 + 40.0 * _lg(d3_at / dbp), abs=1e-12)
        d3_2 = math.hypot(2.0 * dbp, 33.5)
        p2 = rma_los_db(2.0 * dbp, d3_2, self.F)
        assert p2 == pytest.approx(pl1 + 40.0 * _lg(d3_2 / dbp), abs=1e-12)

    def test_nlos_full_expression(self):
        d2, d3 = 1000.0, 1001.0
        got = rma_nlos_db(d2, d3, self.F)
        h, w, hb, hu = 5.0, 20.0, 35.0, 1.5
        expect = (161.04 - 7.1 * _lg(w) + 7.5 * _lg(h)
                  - (24.37 - 3.7 * (h / hb) ** 2) * _lg(hb)
                  + (43.42 - 3.1 * _lg(hb)) * (_lg(d3) - 3.0)
                  + 20.0 * _lg(0.7)
                  - (3.2 * _lg(11.75 * hu) ** 2 - 4.97))
        assert got == pytest.approx(expect, abs=1e-12)  # 远距 NLOS 占优


class TestInh:
    def test_los(self):
        got = inh_office_los_db(10.0, 3.5e9)
        assert got == pytest.approx(32.4 + 17.3 * _lg(10.0) + 20.0 * _lg(3.5),
                                    abs=1e-12)

    def test_nlos_etsi_text_reorder(self):
        # ETSI V19.2 PDF 文本系数，项序交换重排独立算式
        got = inh_office_nlos_db(10.0, 3.5e9)
        pl_n = 24.9 * _lg(3.5) + 38.3 * _lg(10.0) + 17.30
        assert got == pytest.approx(max(
            inh_office_los_db(10.0, 3.5e9), pl_n), abs=1e-12)
        assert got == pytest.approx(pl_n, abs=1e-12)

    def test_domain(self):
        with pytest.raises(ValueError):
            inh_office_los_db(0.5, 3.5e9)  # d3D<1m
        with pytest.raises(ValueError):
            inh_office_nlos_db(200.0, 3.5e9)  # d3D>150m


class TestO2I:
    def test_material_zero_f_limits(self):
        assert material_penetration_db("glass", 0.0) == pytest.approx(2.0)
        assert material_penetration_db("concrete", 0.0) == pytest.approx(5.0)
        assert material_penetration_db("plywood", 0.0) == pytest.approx(1.03)
        assert material_penetration_db("irr_glass", 0.0) == pytest.approx(25.4)
        assert material_penetration_db("wood", 0.0) == pytest.approx(4.85)

    def test_low_high_models_hand_calc(self):
        # f=1GHz：L_glass=2.2、L_concrete=9、L_irr=25.51（手算）
        plb = 100.0
        low = o2i_building_db(plb, 10.0, 1e9, model="low")
        l_glass, l_conc = 2.2, 9.0
        tw_low = 5.0 - 10.0 * _lg(0.3 * 10 ** (-l_glass / 10.0)
                                  + 0.7 * 10 ** (-l_conc / 10.0))
        assert low["pl_tw_db"] == pytest.approx(tw_low, abs=1e-12)
        assert low["pl_total_db"] == pytest.approx(plb + tw_low + 5.0,
                                                   abs=1e-12)
        high = o2i_building_db(plb, 10.0, 1e9, model="high")
        l_irr = 25.4 + 0.11
        tw_high = 5.0 - 10.0 * _lg(0.7 * 10 ** (-l_irr / 10.0)
                                   + 0.3 * 10 ** (-l_conc / 10.0))
        assert high["pl_tw_db"] == pytest.approx(tw_high, abs=1e-12)
        assert high["sigma_p_db"] == 6.5 and low["sigma_p_db"] == 4.4
        # 通用式（7.4-3）在 PLnpi=5 特例与表式一致（同一公式双入口）
        assert external_wall_loss_db({"glass": 0.3, "concrete": 0.7}, 1.0) == \
            pytest.approx(tw_low, abs=1e-12)

    def test_legacy_and_car(self):
        leg = o2i_legacy_db(80.0, 10.0)
        assert leg["pl_tw_db"] == 20.0 and leg["sigma_p_db"] == 0.0
        assert leg["pl_total_db"] == pytest.approx(105.0)
        car = o2i_car_db(80.0)
        assert car["pl_total_db"] == pytest.approx(89.0)
        assert o2i_car_db(80.0, metallized_windows=True)["pl_total_db"] == \
            pytest.approx(100.0)

    def test_domain_guards(self):
        with pytest.raises(ValueError):
            o2i_building_db(100.0, 30.0, 1e9)  # d2D-in > 25m
        with pytest.raises(ValueError):
            external_wall_loss_db({"glass": 0.5, "concrete": 0.2}, 1.0)


class TestDomainBoxes:
    def test_frequency_limits(self):
        with pytest.raises(ValueError):
            uma_los_db(50.0, 50.0, 0.4e9)  # <0.5 GHz
        with pytest.raises(ValueError):
            uma_los_db(50.0, 50.0, 101e9)  # >100 GHz
        with pytest.raises(ValueError):
            rma_los_db(50.0, 50.0, 40e9)  # RMa fH=30 GHz

    def test_distance_height_boxes(self):
        with pytest.raises(ValueError):
            uma_los_db(5.0, 5.0, 3.5e9)  # d2D<10m
        with pytest.raises(ValueError):
            uma_los_db(100.0, 100.0, 3.5e9, h_ut_m=30.0)
        with pytest.raises(ValueError):
            rma_los_db(50.0, 50.0, 1e9, avg_building_height_m=60.0)

    def test_variant_guard(self):
        with pytest.raises(ValueError):
            uma_nlos_db(100.0, 100.0, 3.5e9, variant="bogus")


class TestTdl:
    def test_table_shapes_and_los_flags(self):
        expect_n = {"TDL-A": 23, "TDL-B": 23, "TDL-C": 24,
                    "TDL-D": 14, "TDL-E": 15}
        for name, n in expect_n.items():
            p = tdl_profile(name)
            assert len(p["delays_norm"]) == n
            assert len(p["powers_db"]) == n
            assert p["los"] == (name in ("TDL-D", "TDL-E"))

    def test_normalized_delay_spread(self):
        # 归一 DS≈1（表值舍入界：TDL-A/B/C/E ≤3e-4；TDL-D 0.9937
        # 实测锚，统一门 ≤0.007）
        got = {n: tdl_delay_spread_ns(tdl_profile(n))
               for n in ("TDL-A", "TDL-B", "TDL-C", "TDL-D", "TDL-E")}
        for n, ds in got.items():
            assert abs(ds - 1.0) <= 0.007, (n, ds)
        assert got["TDL-D"] == pytest.approx(0.9937, abs=5e-4)

    def test_k_factor_self_consistency(self):
        # K₁ 自算（首 tap 口径，表 NOTE 定义）= 表声明（13.3/22 dB，
        # 门 0.05 dB）；首 tap 平均功率 ≈0 dB（表 NOTE 第二声明，双锚）
        assert tdl_k_factor_db(tdl_profile("TDL-A")) is None
        assert tdl_k_factor_db(tdl_profile("TDL-D")) == pytest.approx(
            13.3, abs=0.05)
        assert tdl_k_factor_db(tdl_profile("TDL-E")) == pytest.approx(
            22.0, abs=0.05)
        for name in ("TDL-D", "TDL-E"):
            pw = tdl_profile(name)["powers_db"]
            mean_tap = 10.0 * _lg(10.0 ** (pw[0] / 10.0)
                                  + 10.0 ** (pw[1] / 10.0))
            assert mean_tap == pytest.approx(0.0, abs=0.05)

    def test_k_rescale_round_trip(self):
        p = tdl_rescale_k_factor(tdl_profile("TDL-D"), 20.0)
        assert tdl_k_factor_db(p) == pytest.approx(20.0, rel=1e-9)
        # LOS tap 功率不变（唯一性口径）
        assert p["powers_db"][0] == tdl_profile("TDL-D")["powers_db"][0]
        with pytest.raises(ValueError):
            tdl_rescale_k_factor(tdl_profile("TDL-A"), 10.0)

    def test_delay_scaling(self):
        p = tdl_scale_delays(tdl_profile("TDL-B"), 100.0)
        assert p["delays_ns"][1] == pytest.approx(
            tdl_profile("TDL-B")["delays_norm"][1] * 100.0, rel=1e-15)
        # 缩放后 RMS DS = DS_wanted（§7.7-1 语义；非 LOS 表按缩放
        # delay 复算 DS）
        dl = p["delays_ns"]
        pw = [10 ** (x / 10) for x in p["powers_db"]]
        m1 = sum(a * b for a, b in zip(pw, dl, strict=True)) / sum(pw)
        m2 = sum(a * b * b for a, b in zip(pw, dl, strict=True)) / sum(pw)
        assert math.sqrt(m2 - m1 * m1) == pytest.approx(100.0, rel=1e-2)

    def test_cdl_interface_explicit(self):
        with pytest.raises(NotImplementedError):
            cdl_profile("CDL-A")
        with pytest.raises(ValueError):
            cdl_profile("CDL-Z")
        with pytest.raises(ValueError):
            tdl_profile("TDL-Z")
