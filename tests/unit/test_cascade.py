"""DP-5 系统级预算引擎 + spur search 单测：回收钉 + 注册表契约 + service/CLI。

判据书：runs/df6_dp5cascade/criteria.md（锚值来源 compute_anchors.py，
独立精算脚本不 import rfauto——#118 口径）。回收钉一律 ≤1e-12 逐位对拍；
唯一例外 ΔN_floor=ΔNF_tot（criteria §1 钉 3：浮点结合序尾差，门 1e-12）。

覆盖：
① 钉 1 衰减器首级 NF 退化（NF_tot ≡ 5.0 dB 解析恒等式）+ IIP3 折算
   （IIP3_tot ≡ −7.0 dBm 解析恒等式）；
② 钉 2 三级含 mixer 后级参考面折算（Friis 第三项与 IIP3 第三项均含
   mixer 变频损耗进前级增益积）；
③ 钉 3 filter 插损差传播（ΔG_tot=1.0 逐位）+ service 层 skrf 实取插损
   vs 常数插损两口径输出逐字节一致（联动钉）；
④ spur 教科书钉（2.4/2.1 GHz 组态 2RF−2LO、3RF−3LO 落带判定）；
⑤ IF 规划扫掠钉（f_RF/k 干扰点族 + 闭式落带窗）；
⑥ 注册表/service/CLI 契约（#231 消费者面）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.cascade import (
    cascade_budget,
    if_plan_sweep,
    spur_search,
)

TOL = 1e-12

# 钉 1：atten(−3,3) + amp(20,2,IIP3=−10,OP1dB=5)
NAIL1_STAGES = [
    {"type": "atten", "gain_db": -3.0, "nf_db": 3.0},
    {"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
     "iip3_dbm": -10.0, "p1db_dbm": 5.0},
]
# 钉 2：amp + mixer + amp（mixer 后级参考面折算）
NAIL2_STAGES = [
    {"type": "amp", "gain_db": 25.0, "nf_db": 1.5,
     "iip3_dbm": -5.0, "p1db_dbm": 0.0},
    {"type": "mixer", "gain_db": -8.0, "nf_db": 8.0,
     "iip3_dbm": 18.0, "p1db_dbm": 8.0},
    {"type": "amp", "gain_db": 30.0, "nf_db": 3.0,
     "iip3_dbm": 5.0, "p1db_dbm": 20.0},
]
# 钉 3：amp + filter(il) + amp（插损差传播）
NAIL3_BASE = [{"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
               "iip3_dbm": 10.0, "p1db_dbm": 5.0}]
NAIL3_TAIL = {"type": "amp", "gain_db": 10.0, "nf_db": 3.0,
              "iip3_dbm": 15.0, "p1db_dbm": 15.0}


class TestNail1AttenFirstDegradation:
    """钉 1：衰减器首级 NF 退化 + IIP3 折算（criteria §1 钉 1）。"""

    def setup_method(self):
        self.r = cascade_budget(NAIL1_STAGES, snr_min_db=10.0,
                                rx_power_dbm=-90.0, bw_hz=1e6)

    def test_gain_total(self):
        assert abs(self.r["gain_total_db"] - 17.0) <= TOL

    def test_nf_exact_five_db(self):
        # 解析恒等式：F = 10^0.3 + (10^0.2−1)·10^0.3 = 10^0.5 → NF ≡ 5.0 dB
        # （首级 3dB 衰减器把链路 NF 精确退化为 3+2 dB——教科书经典结论）
        assert abs(self.r["nf_total_db"] - 5.0) <= TOL

    def test_iip3_exact_minus_seven(self):
        # 解析恒等式：1/IIP3 = 10^(−0.3)/10^(−1.0) = 10^0.7 → IIP3 ≡ −7.0 dBm
        assert abs(self.r["iip3_total_dbm"] + 7.0) <= TOL
        assert abs(self.r["oip3_total_dbm"] - 10.0) <= TOL

    def test_noise_floor_sfdr_sensitivity_margin(self):
        assert abs(self.r["thermal_floor_dbm_per_hz"]
                   + 173.97518719422808) <= TOL
        assert abs(self.r["noise_floor_dbm"] + 108.97518719422808) <= 1e-9
        assert abs(self.r["sfdr_db"] - 67.98345812948538) <= TOL
        assert abs(self.r["sensitivity_dbm"] + 98.97518719422808) <= TOL
        assert abs(self.r["link_margin_db"] - 8.975187194228084) <= TOL

    def test_p1db_single_contributor_identity(self):
        # 单个 OP1dB 贡献级 → 幂和恰回自身（经验口径的自退化为恒等）
        assert abs(self.r["p1db_out_dbm"] - 5.0) <= TOL
        assert abs(self.r["p1db_in_dbm"] + 12.0) <= TOL
        # 逐级输出参考折算表（首级衰减器无 OP1dB → None）
        assert self.r["stages"][0]["op1db_out_referred_dbm"] is None
        assert abs(self.r["stages"][1]["op1db_out_referred_dbm"] - 5.0) <= TOL


class TestNail2MixerReferencePlane:
    """钉 2：三级含 mixer 后级参考面折算（criteria §1 钉 2）。"""

    def setup_method(self):
        self.r = cascade_budget(NAIL2_STAGES, bw_hz=1e7)

    def test_friis_with_mixer_loss_in_denominator(self):
        # (F₃−1)/(G₁G₂) 的 G₂ 含 mixer 变频损耗（10^(−0.8)）——参考面折算钉
        assert abs(self.r["nf_total_db"] - 1.6112412504984066) <= TOL
        assert abs(self.r["gain_total_db"] - 47.0) <= TOL

    def test_iip3_third_term_refers_through_mixer(self):
        # 第三项 = G₁·G₂/IIP3₃，G₂ 含变频损耗（后级 IIP3 折算到链路输入）
        assert abs(self.r["iip3_total_dbm"] + 13.806287222778524) <= TOL
        # OIP3 = IIP3 + G_tot 恒等式逐位
        assert (self.r["oip3_total_dbm"]
                == self.r["iip3_total_dbm"] + self.r["gain_total_db"])
        assert abs(self.r["oip3_total_dbm"] - 33.19371277722148) <= TOL

    def test_noise_floor_sfdr(self):
        assert abs(self.r["noise_floor_dbm"] + 102.36394594372968) <= 1e-9
        assert abs(self.r["sfdr_db"] - 59.038439147300764) <= 1e-9
        assert abs(self.r["sensitivity_dbm"] + 92.36394594372968) <= 1e-9

    def test_p1db_power_sum_output_referred(self):
        # 输出参考 {22, 38, 20} dBm → 幂和 17.8335748646276 dBm
        referred = [s["op1db_out_referred_dbm"] for s in self.r["stages"]]
        assert abs(referred[0] - 22.0) <= TOL
        assert abs(referred[1] - 38.0) <= TOL
        assert abs(referred[2] - 20.0) <= TOL
        assert abs(self.r["p1db_out_dbm"] - 17.8335748646276) <= TOL
        assert abs(self.r["p1db_in_dbm"] + 29.1664251353724) <= TOL


class TestNail3FilterIlPropagation:
    """钉 3：filter 插损差传播（criteria §1 钉 3）。"""

    def setup_method(self):
        self.a = cascade_budget(
            [*NAIL3_BASE, {"type": "filter", "gain_db": -1.0}, NAIL3_TAIL],
            bw_hz=1e6)
        self.b = cascade_budget(
            [*NAIL3_BASE, {"type": "filter", "gain_db": -2.0}, NAIL3_TAIL],
            bw_hz=1e6)

    def test_gain_difference_is_il_difference_exact(self):
        assert self.a["gain_total_db"] - self.b["gain_total_db"] == 1.0
        assert abs(self.a["gain_total_db"] - 29.0) <= TOL

    def test_noise_floor_difference_tracks_nf(self):
        # ΔN_floor = ΔNF_tot（同一 B、T）；实测尾差 ~6e-15（浮点结合序，
        # criteria §1 钉 3 注记），门 1e-12
        assert abs((self.a["noise_floor_dbm"] - self.b["noise_floor_dbm"])
                   - (self.a["nf_total_db"] - self.b["nf_total_db"])) <= TOL

    def test_anchor_values(self):
        assert abs(self.a["nf_total_db"] - 2.041232552632053) <= TOL
        assert abs(self.a["iip3_total_dbm"] + 4.169542892795331) <= TOL
        assert abs(self.a["p1db_out_dbm"] - 11.46098108956133) <= TOL
        assert abs(self.b["nf_total_db"] - 2.0588504687563836) <= TOL
        assert abs(self.b["iip3_total_dbm"] + 3.2123840191425526) <= TOL
        assert abs(self.b["p1db_out_dbm"] - 10.875573972056603) <= TOL


class TestBudgetSemantics:
    """口径与守卫：无源 NF 缺省、bw 解析、透明级、显式报错。"""

    def test_passive_nf_defaults_to_loss(self):
        r = cascade_budget([{"type": "cable", "gain_db": -2.0},
                            {"type": "amp", "gain_db": 20.0, "nf_db": 2.0}],
                           bw_hz=1e6)
        assert abs(r["nf_total_db"] - 4.0) <= TOL
        assert r["stages"][0].get("nf_derived") is True

    def test_bw_resolution_last_stage_and_explicit(self):
        r = cascade_budget([{"type": "amp", "gain_db": 10.0, "nf_db": 2.0,
                             "bw_hz": 2e6}])
        assert r["bw_hz"] == 2e6 and r["bw_source"] == "last_stage"
        r2 = cascade_budget([{"type": "amp", "gain_db": 10.0, "nf_db": 2.0,
                              "bw_hz": 2e6}], bw_hz=3e6)
        assert r2["bw_hz"] == 3e6 and r2["bw_source"] == "explicit"

    def test_bw_unresolvable_explicit_error(self):
        with pytest.raises(ValueError, match="噪声带宽无法解析"):
            cascade_budget([{"type": "amp", "gain_db": 10.0, "nf_db": 2.0}])

    def test_no_ip3_stages_gives_none_not_fabricated(self):
        r = cascade_budget([{"type": "amp", "gain_db": 10.0, "nf_db": 2.0}],
                           bw_hz=1e6)
        assert r["iip3_total_dbm"] is None
        assert r["oip3_total_dbm"] is None
        assert r["sfdr_db"] is None
        assert r["noise_floor_dbm"] is not None  # 噪声面照常出

    def test_empty_and_invalid_stages_rejected(self):
        with pytest.raises(ValueError, match="非空"):
            cascade_budget([])
        with pytest.raises(ValueError, match="type"):
            cascade_budget([{"type": "transformer", "gain_db": 1.0}])
        with pytest.raises(ValueError, match="nf_db"):
            cascade_budget([{"type": "amp", "gain_db": 10.0}])

    def test_determinism_byte_identical(self):
        a = cascade_budget(NAIL2_STAGES, bw_hz=1e7)
        b = cascade_budget(NAIL2_STAGES, bw_hz=1e7)
        assert json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(
            b, sort_keys=True, allow_nan=False)


class TestSpurSearchTextbook:
    """spur 钉：2.4/2.1 GHz 组态（criteria §2）。"""

    def setup_method(self):
        self.spurs = spur_search(2.4e9, 2.1e9, if_center_hz=600e6,
                                 if_bw_hz=1e5)

    def _find(self, spurs, m, n, side):
        return next(s for s in spurs
                    if (s["m"], s["n"], s["side"]) == (m, n, side))

    def test_2rf_minus_2lo_in_band(self):
        s = self._find(self.spurs, 2, 2, "-")
        assert s["f_spur_hz"] == 600000000.0
        assert s["in_band"] is True
        assert s["order"] == 4 and s["hazard"] == "medium"

    def test_3rf_minus_3lo_out_of_band_narrow(self):
        s = self._find(self.spurs, 3, 3, "-")
        assert s["f_spur_hz"] == 900000000.0
        assert s["in_band"] is False

    def test_3rf_minus_3lo_in_band_wide_rf(self):
        # rf_bw=350e6 → 3RF−3LO 产物带宽 1050e6，矩形卷积落带
        wide = spur_search(2.4e9, 2.1e9, if_center_hz=600e6, if_bw_hz=1e5,
                           rf_bw_hz=350e6)
        s = self._find(wide, 3, 3, "-")
        assert s["in_band"] is True and s["bw_spur_hz"] == 1050e6

    def test_fundamental_tagged_not_spur(self):
        s = self._find(self.spurs, 1, 1, "-")
        assert s["role"] == "fundamental"
        assert s["f_spur_hz"] == 300000000.0

    def test_max_order_exclusion_and_bound(self):
        assert all(s["order"] <= 7 for s in self.spurs)
        assert self._find(self.spurs, 3, 3, "-") is not None
        # (4,4) 阶 8 缺席
        with pytest.raises(StopIteration):
            self._find(self.spurs, 4, 4, "-")
        narrow = spur_search(2.4e9, 2.1e9, if_center_hz=600e6,
                             max_order=3)
        with pytest.raises(StopIteration):
            self._find(narrow, 3, 3, "-")

    def test_hazard_ladder(self):
        assert self._find(self.spurs, 2, 1, "-")["hazard"] == "high"  # 阶 3
        assert self._find(self.spurs, 3, 2, "-")["hazard"] == "medium"  # 阶 5
        assert self._find(self.spurs, 3, 3, "-")["hazard"] == "low"   # 阶 6
        assert self._find(self.spurs, 4, 3, "-")["hazard"] == "low"   # 阶 7

    def test_dc_product_skipped(self):
        # m·f_RF == n·f_LO 无公共谐波（2.4/2.1 比非整数），换 2.4/1.2 →
        # (1,1)−? no: |2.4−1.2|=1.2；(2,1)+=4.8；(1,2)? |2.4−2.4|=0 → DC 剔除
        spurs = spur_search(2.4e9, 1.2e9, if_center_hz=300e6)
        assert all(s["f_spur_hz"] > 0.0 for s in spurs)

    def test_default_if_center_is_natural_if(self):
        spurs = spur_search(2.4e9, 2.1e9)
        s = self._find(spurs, 1, 1, "-")
        assert s["in_band"] is True
        assert s["f_spur_hz"] == abs(2.4e9 - 2.1e9)

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError, match="f_rf_hz"):
            spur_search(0.0, 2.1e9)
        with pytest.raises(ValueError, match="max_order"):
            spur_search(2.4e9, 2.1e9, max_order=0)
        with pytest.raises(ValueError, match="if_center_hz"):
            spur_search(2.4e9, 2.4e9)


class TestIfPlanSweepTextbook:
    """IF 规划扫掠钉：f_RF/k 干扰点族 + 闭式落带窗（criteria §2）。"""

    def setup_method(self):
        self.plan = if_plan_sweep(2.4e9, if_lo_hz=1e8, if_hi_hz=1e9,
                                  n_points=9001, if_bw_hz=1e6)

    def _probe(self, if_hz):
        return min(self.plan["points"],
                   key=lambda p: abs(p["if_center_hz"] - if_hz))

    def test_probe_grid_resolution(self):
        pts = self.plan["points"]
        assert abs(pts[0]["if_center_hz"] - 1e8) <= 1e-9
        assert abs(pts[-1]["if_center_hz"] - 1e9) <= 1e-9
        assert len(pts) == 9001

    def test_spurious_free_region(self):
        p = self._probe(3e8)
        assert p["spurious_free"] is True and p["n_spurs_in_band"] == 0

    def test_order3_zone_at_f_rf_over_3(self):
        # (1,2)：f_spur=|f_RF−2f_LO|=|f_RF−2IF|；落带窗 (f_RF∓if_bw/2)/3
        p = self._probe(799900000.0)
        assert p["spurious_free"] is False
        assert p["worst_hazard"] == "high"
        assert (p["worst_spur"]["m"], p["worst_spur"]["n"]) == (1, 2)
        q = self._probe(799700000.0)  # 窗外（窗下沿 799833333.33）
        assert q["spurious_free"] is True

    def test_order5_zone_at_f_rf_over_4(self):
        # (2,3)：f_spur=|2f_RF−3f_LO|=|3IF−f_RF|；落带窗 (f_RF∓if_bw/2)/4
        p = self._probe(600000000.0)
        assert p["spurious_free"] is False
        assert p["worst_hazard"] == "medium"
        assert (p["worst_spur"]["m"], p["worst_spur"]["n"]) == (2, 3)
        q = self._probe(599700000.0)  # 窗外（窗下沿 599875000）
        assert q["spurious_free"] is True

    def test_order7_zone_at_f_rf_over_5(self):
        # (3,4)：f_spur=|3f_RF−4f_LO|=|4IF−f_RF|；落带窗 (f_RF∓if_bw/2)/5
        p = self._probe(480000000.0)
        assert p["spurious_free"] is False
        assert p["worst_hazard"] == "low"
        assert (p["worst_spur"]["m"], p["worst_spur"]["n"]) == (3, 4)

    def test_windows_consistent_with_points(self):
        assert self.plan["n_points_free"] == sum(
            w["n_points"] for w in self.plan["windows"])
        # 窗口互不重叠、单调递增
        starts = [w["start_hz"] for w in self.plan["windows"]]
        assert starts == sorted(starts)
        for w0, w1 in zip(self.plan["windows"], self.plan["windows"][1:],
                          strict=False):
            assert w0["end_hz"] < w1["start_hz"]
        # 每 480/600/800 MHz 干扰带在窗口表里留出空档
        free_spans = [(w["start_hz"], w["end_hz"])
                      for w in self.plan["windows"]]
        assert not any(s <= 800000000.0 <= e for s, e in free_spans)
        assert not any(s <= 600000000.0 <= e for s, e in free_spans)

    def test_high_side_injection(self):
        plan = if_plan_sweep(2.4e9, if_lo_hz=1e8, if_hi_hz=3e8, side="high",
                             n_points=201, if_bw_hz=1e3)
        p = min(plan["points"], key=lambda x: abs(x["if_center_hz"] - 2e8))
        assert p["f_lo_hz"] == 2.6e9  # high 侧：f_LO=f_RF+IF
        assert p["spurious_free"] is True

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError, match="if_lo_hz"):
            if_plan_sweep(2.4e9, if_lo_hz=5e8, if_hi_hz=1e8)
        with pytest.raises(ValueError, match="side"):
            if_plan_sweep(2.4e9, if_lo_hz=1e8, if_hi_hz=3e8, side="middle")
        with pytest.raises(ValueError, match="low 侧"):
            if_plan_sweep(2.4e9, if_lo_hz=1e8, if_hi_hz=3e9)
        with pytest.raises(ValueError, match="n_points"):
            if_plan_sweep(2.4e9, if_lo_hz=1e8, if_hi_hz=3e8, n_points=1)


# ─── 注册表/service/CLI 契约（#231 消费者面）─────────────────────────────────


class TestRegistryContract:
    def test_three_keys_registered(self):
        from rfauto.core.calculators import CALCULATOR_REGISTRY

        for key in ("cascade_budget", "spur_search", "if_plan_sweep"):
            spec = CALCULATOR_REGISTRY.get(key)
            assert spec.func is not None
            assert not spec.experimental

    def test_run_calculator_service_contract(self):
        from rfauto.service.calculator_service import run_calculator

        out = run_calculator("cascade_budget", {
            "stages": NAIL1_STAGES, "rx_power_dbm": -90.0, "bw_hz": 1e6})
        assert out["ok"] is True
        assert abs(out["result"]["nf_total_db"] - 5.0) <= TOL
        out2 = run_calculator("spur_search", {
            "f_rf_hz": 2.4e9, "f_lo_hz": 2.1e9, "if_center_hz": 600e6,
            "if_bw_hz": 1e5})
        assert out2["ok"] is True
        assert out2["result"]["n_spurs_in_band"] >= 1
        out3 = run_calculator("if_plan_sweep", {
            "f_rf_hz": 2.4e9, "if_lo_hz": 1e8, "if_hi_hz": 5e8,
            "n_points": 21, "if_bw_hz": 1e6})
        assert out3["ok"] is True and out3["result"]["windows"]

    def test_service_json_error_translation(self):
        from rfauto.service.cascade_service import cascade_budget_report

        out = cascade_budget_report([])
        assert out["ok"] is False and out["error"]


class TestServiceNetworkIllinkage:
    """联动钉：skrf 实取插损 vs 常数插损——同一链两口径输出逐字节一致。"""

    @pytest.fixture()
    def network_s2p(self, tmp_path):
        """合成 2 端口 S 参数：S21 ≈ −1.5 dB 平坦（2–3 GHz）。"""
        skrf = pytest.importorskip("skrf")
        import numpy as np

        freq = skrf.Frequency(2, 3, 21, unit="GHz")
        s21 = 10.0 ** (-1.5 / 20.0)
        s = np.zeros((21, 2, 2), dtype=complex)
        s[:, 0, 0] = 0.01
        s[:, 1, 0] = s21
        s[:, 0, 1] = s21
        s[:, 1, 1] = 0.01
        nw = skrf.Network(frequency=freq, s=s, z0=50.0)
        path = tmp_path / "filter_il15.s2p"
        nw.write_touchstone(str(path))
        return path

    def _chain(self, filter_stage):
        tail = dict(NAIL3_TAIL)
        tail["bw_hz"] = 1e6
        return [*NAIL3_BASE, dict(filter_stage, type="filter"), tail]

    @staticmethod
    def _physics_json(result):
        """剥掉逐级插损来源字段后的物理面 JSON（来源字段如实保留口径差异，
        数值面必须逐位一致——criteria §1 钉 3 联动钉口径）。"""
        payload = json.loads(json.dumps(result))
        for st in payload["stages"]:
            for key in ("il_source", "network_path", "il_freq_hz", "il_db"):
                st.pop(key, None)
        return json.dumps(payload, sort_keys=True)

    def test_sparam_vs_constant_byte_identical(self, network_s2p):
        from rfauto.service.cascade_service import cascade_budget_report

        by_network = cascade_budget_report(self._chain({
            "network_path": str(network_s2p), "il_freq_hz": 2.4e9}))
        assert by_network["ok"] is True, by_network
        stage = by_network["result"]["stages"][1]
        assert stage["il_source"] == "sparam"
        resolved_il = -stage["gain_db"]
        # Touchstone 文本精度内还原 −1.5 dB 名义值
        assert abs(resolved_il - 1.5) < 1e-9
        # 同值常数口径 → 物理面输出逐字节一致（两口径输出差=插损差=0）
        by_constant = cascade_budget_report(self._chain({"il_db": resolved_il}))
        assert by_constant["ok"] is True
        assert by_constant["result"]["stages"][1]["il_source"] == "constant"
        assert (self._physics_json(by_network["result"])
                == self._physics_json(by_constant["result"]))

    def test_two_networks_difference_is_il_difference(self, network_s2p, tmp_path):
        """插损差传播：实取 v vs 常数 1.0 → G_tot 差 = v−1.0（钉 3 的 service 面）。"""
        from rfauto.service.cascade_service import cascade_budget_report

        by_network = cascade_budget_report(self._chain({
            "network_path": str(network_s2p), "il_freq_hz": 2.4e9}))
        by_c1 = cascade_budget_report(self._chain({"il_db": 1.0}))
        assert by_network["ok"] and by_c1["ok"]
        v = -by_network["result"]["stages"][1]["gain_db"]
        # 实取链多 v−1.0 dB 插损 → 其 G_tot 少 v−1.0 dB（符号：损耗降增益）
        assert abs((by_c1["result"]["gain_total_db"]
                    - by_network["result"]["gain_total_db"]) - (v - 1.0)) <= TOL

    def test_missing_asset_requires_explicit_degradation(self, tmp_path):
        from rfauto.service.cascade_service import cascade_budget_report

        out = cascade_budget_report(self._chain({
            "network_path": str(tmp_path / "nope.s2p"),
            "il_freq_hz": 2.4e9}))
        assert out["ok"] is False
        assert "S 参数资产缺失" in out["error"]
        assert "il_db" in out["error"]  # 错误消息显式指路常数降级

    def test_no_il_source_requires_explicit_choice(self):
        from rfauto.service.cascade_service import cascade_budget_report

        out = cascade_budget_report(self._chain({}))
        assert out["ok"] is False
        assert "插损来源" in out["error"]

    def test_network_and_constant_conflict_rejected(self, network_s2p):
        from rfauto.service.cascade_service import cascade_budget_report

        out = cascade_budget_report(self._chain({
            "network_path": str(network_s2p), "il_freq_hz": 2.4e9,
            "il_db": 1.0}))
        assert out["ok"] is False and "二选一" in out["error"]

    def test_il_freq_outside_network_rejected(self, network_s2p):
        from rfauto.service.cascade_service import cascade_budget_report

        out = cascade_budget_report(self._chain({
            "network_path": str(network_s2p), "il_freq_hz": 10e9}))
        assert out["ok"] is False and "不外推" in out["error"]


class TestCliCascadeApp:
    """CLI 接线（薄壳烟测：budget|spur|plan 三命令 + --help 可构建，#305）。"""

    @pytest.fixture()
    def runner(self):
        from typer.testing import CliRunner

        return CliRunner()

    def _write_stages(self, tmp_path):
        stages = [dict(s) for s in NAIL1_STAGES]
        stages[-1]["bw_hz"] = 1e6
        path = tmp_path / "stages.json"
        path.write_text(json.dumps(stages), encoding="utf-8")
        return path

    def test_budget_json(self, runner, tmp_path):
        from rfauto.cli.main import app

        result = runner.invoke(
            app, ["cascade", "budget", str(self._write_stages(tmp_path)),
                  "--rx-power", "-90", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert abs(payload["nf_total_db"] - 5.0) <= TOL

    def test_budget_table_and_error(self, runner, tmp_path):
        from rfauto.cli.main import app

        ok = runner.invoke(
            app, ["cascade", "budget", str(self._write_stages(tmp_path))])
        assert ok.exit_code == 0 and "总增益" in ok.output
        bad = runner.invoke(app, ["cascade", "budget", str(tmp_path / "no.json")])
        assert bad.exit_code == 1

    def test_spur_and_plan(self, runner):
        from rfauto.cli.main import app

        spur = runner.invoke(app, [
            "cascade", "spur", "--rf", "2.4e9", "--lo", "2.1e9",
            "--if-center", "600e6", "--if-bw", "1e5", "--json"])
        assert spur.exit_code == 0, spur.output
        payload = json.loads(spur.output)
        assert payload["n_spurs_in_band"] >= 1
        plan = runner.invoke(app, [
            "cascade", "plan", "--rf", "2.4e9", "--if-lo", "1e8",
            "--if-hi", "5e8", "--points", "41", "--json"])
        assert plan.exit_code == 0, plan.output
        assert json.loads(plan.output)["windows"]
        # --help 构建（% 转义回归，#305）
        for cmd in ("budget", "spur", "plan"):
            assert runner.invoke(app, ["cascade", cmd, "--help"]).exit_code == 0
