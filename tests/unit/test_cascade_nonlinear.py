"""ME-18/ME-19 非线性级联扩展单测：双路径裁判 + 恒等式锚 + 勘误钉（#118/#122）。

判据书：任务书 ME-18/ME-19 判据 + 本文件双路径独立精算（测试侧表达式不
import 被测实现的中间量）。口径来源见 core/cascade.py §4 节头注（Kundert
intercept-point.pdf 式(1)(30)(33)(35) + RF Cafe ip2/ip3/p1db 页，2026-09-27
实测抓取逐式核对）。

**规格书勘误钉**：任务书 "IM_n(dBc)=n·(Pin−IPn)" 与双源相反，正确为
(n−1)·(Pin−IPn)（IM5 @ Pin−IP5=−10 dB → **−40 dBc**，非任务书判据的 −50）。
本文件 test_im5_erratum_not_minus_50 如实钉正确值并注明勘误出处。

覆盖：
① IPn 逐对/级联合并（等值 −3.01 dB 锚、弱级渐近、单级恒等、线性域 ≤0 拒收）；
② IMn 单级外推（IM3 −20 dBc 教科书值、IM5 勘误钉、外推域守卫）；
③ P1dB 估计（Δ=11.7 缺省/10 可配逐位、Kundert 9.6 dB 常量双路径）；
④ 最先压缩级定位（前强后弱构造例逐位、回退量表、OIP3 三级解析）；
⑤ 三阶幂级数 AM-AM/AM-PM（IM3 手算、复 a₃ 相位、v1db→Kundert αCP 退化、
   IP3−P1dB 间距 9.6357 dB 独立回收）；
⑥ 级联 AM-PM 加权（单级恒等、主导级、均值锚、无压缩 None、fail-fast）；
⑦ cascade_nonlinear_scan 端到端 + to_dict JSON 往返 + 既有 cascade_budget
   返回结构冻结钉（#315 同源：新面零改变既有消费者）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.cascade import (
    CP1_IP3_DELTA_THIRD_ORDER_DB,
    DEFAULT_P1DB_DELTA_DB,
    am_am_pm_third_order,
    cascade_am_pm,
    cascade_budget,
    cascade_compression_scan,
    cascade_ipn_merge,
    cascade_nonlinear_scan,
    im_products_extrapolate,
    ipn_merge_linear,
    p1db_from_oip3,
)

TOL = 1e-9


# ─── ① IPn 级联合并 ──────────────────────────────────────────────────────────

class TestCascadeIpnMerge:
    """1/IPn_tot = Σ G_pre,i/IPn_i（线性 mW 功率域）；锚与渐近。"""

    def test_two_stage_pairwise_formula_exact(self):
        # 手算：1/IIPn = 1/10^(−1) + 10^2/10^0 = 10 + 100 = 110 → 1/110 mW
        r = cascade_ipn_merge(
            [{"name": "lna", "gain_db": 20.0, "ipn_dbm": -10.0},
             {"name": "mix", "gain_db": 10.0, "ipn_dbm": 0.0}], order=3)
        expect = 10.0 * math.log10(1.0 / 110.0)
        assert abs(r["ipn_total_input_dbm"] - expect) <= TOL
        assert abs(expect - (-20.41392685158225)) <= TOL
        # OIPn = IIPn + G_tot 恒等式（逐位）
        assert (r["ipn_total_output_dbm"]
                == r["ipn_total_input_dbm"] + r["gain_total_db"])
        assert r["gain_total_db"] == 30.0

    def test_equal_ips_g1_minus_3db(self):
        # 判据锚：两级同值 IPn、G=1 → 合并 = 单级 −3.01 dB（等功率叠加；
        # 独立路径 10log10(2·10^(x/10)) 与 1/(1/x+1/x) 双算，rel 1e-9）
        x = -10.0
        r = cascade_ipn_merge(
            [{"gain_db": 0.0, "ipn_dbm": x}, {"gain_db": 0.0, "ipn_dbm": x}],
            order=3)
        # 独立路径：1/IPn_tot = 2/IPn → IPn_tot = IPn/2（线性 mW 减半）
        independent = 10.0 * math.log10(10.0 ** (x / 10.0) / 2.0)
        assert abs(r["ipn_total_input_dbm"] - independent) <= 1e-9
        assert abs((r["ipn_total_input_dbm"] - x)
                   - (10.0 * math.log10(0.5))) <= 1e-9

    def test_weak_second_stage_asymptote(self):
        # 判据锚：IPn_2 ≫ IPn_1·G → 合并 → IPn_1（渐近带）
        r = cascade_ipn_merge(
            [{"gain_db": 0.0, "ipn_dbm": -10.0},
             {"gain_db": 0.0, "ipn_dbm": 60.0}], order=3)
        assert abs(r["ipn_total_input_dbm"] - (-10.0)) < 1e-6

    def test_single_stage_identity(self):
        r = cascade_ipn_merge([{"gain_db": 12.0, "ipn_dbm": 7.0}], order=2)
        assert r["ipn_total_input_dbm"] == 7.0
        assert r["ipn_total_output_dbm"] == 19.0
        assert r["dominant_stage"] == 0
        assert r["contributions"][0]["share"] == 1.0

    def test_order_metadata_any_order(self):
        # 合并代数与阶数无关：order=2/5 同数值，order 元数据如实回显
        stages = [{"gain_db": 20.0, "ipn_dbm": -10.0},
                  {"gain_db": 10.0, "ipn_dbm": 0.0}]
        r2 = cascade_ipn_merge(stages, order=2)
        r5 = cascade_ipn_merge(stages, order=5)
        assert r2["ipn_total_input_dbm"] == r5["ipn_total_input_dbm"]
        assert (r2["order"], r5["order"]) == (2, 5)
        assert "更高阶" in r5["order_scope_note"]

    def test_invalid_inputs_rejected(self):
        with pytest.raises(ValueError, match="非空"):
            cascade_ipn_merge([], order=3)
        with pytest.raises(ValueError, match="ipn_dbm"):
            cascade_ipn_merge([{"gain_db": 1.0}], order=3)
        with pytest.raises(ValueError, match="order 必须"):
            cascade_ipn_merge([{"gain_db": 1.0, "ipn_dbm": 0.0}], order=1)
        with pytest.raises(ValueError, match="整数"):
            cascade_ipn_merge([{"gain_db": 1.0, "ipn_dbm": 0.0}], order=3.0)
        with pytest.raises(ValueError, match="gain_db"):
            cascade_ipn_merge([{"ipn_dbm": 0.0}], order=3)
        with pytest.raises(ValueError, match="有限"):
            cascade_ipn_merge(
                [{"gain_db": 1.0, "ipn_dbm": float("nan")}], order=3)

    def test_linear_core_rejects_nonpositive(self):
        # "IPn≤0 → ValueError" 判据落点=线性域入口（dBm 负值物理合法，
        # 混频器 IIP3<0 dBm 与 cascade_budget 口径一致——如实登记的边界）
        with pytest.raises(ValueError, match="ipn_linear"):
            ipn_merge_linear([0.0], [1.0])
        with pytest.raises(ValueError, match="ipn_linear"):
            ipn_merge_linear([-1.0, 5.0], [1.0, 1.0])
        with pytest.raises(ValueError, match="gain_pre_linear"):
            ipn_merge_linear([1.0], [0.0])
        with pytest.raises(ValueError, match="同长非空"):
            ipn_merge_linear([], [])
        # 正确性：单级恒等 + 两级等分
        assert abs(ipn_merge_linear([2.0], [1.0]) - 2.0) <= TOL
        assert abs(ipn_merge_linear([2.0, 2.0], [1.0, 1.0]) - 1.0) <= TOL


# ─── ② IMn 单级外推（含规格书勘误钉）─────────────────────────────────────────

class TestImProductsExtrapolate:
    def test_im3_minus_20dbc_at_10db_backoff(self):
        # 教科书普适值：IM3(dBc) = 2·(Pin − IIP3)
        r = im_products_extrapolate(-20.0, -10.0, 3)
        assert r["im_n_dbc"] == -20.0
        assert r["order"] == 3 and r["pin_dbm"] == -20.0 and r["ipn_dbm"] == -10.0

    def test_im5_erratum_not_minus_50(self):
        # 规格书勘误钉：任务书写 IM5 = 5·(−10) = −50 dBc，双源（Kundert 式(1)
        # IPn = P + ΔP/(n−1) 反解 + RF Cafe P_n = n·P_out − (n−1)·IPn）一致给
        # (n−1)·(Pin−IPn) = 4·(−10) = −40 dBc（IM5 斜率 4 dB/dB）。本钉如实
        # 钉正确值，spec_erratum 字段登记勘误（#122 不凑判据书原值）。
        r = im_products_extrapolate(-30.0, -20.0, 5)
        assert r["im_n_dbc"] == -40.0
        assert abs(r["im_n_dbc"] - 4.0 * (-30.0 - (-20.0))) <= TOL
        assert "笔误" in r["spec_erratum"]
        assert "待证" in r["cascade_status"]

    def test_im2_slope_one(self):
        r = im_products_extrapolate(-30.0, -20.0, 2)
        assert r["im_n_dbc"] == -10.0

    def test_at_intercept_zero_dbc(self):
        # Pin == IPn → 0 dBc 逐位（交截点定义恒等式）
        r = im_products_extrapolate(-10.0, -10.0, 3)
        assert r["im_n_dbc"] == 0.0

    def test_extrapolation_domain_and_order_rejected(self):
        # 外推域守卫：Pin > IPn → 非物理正 dBc，显式拒绝
        with pytest.raises(ValueError, match="外推域越界"):
            im_products_extrapolate(-9.0, -10.0, 3)
        with pytest.raises(ValueError, match="order 必须"):
            im_products_extrapolate(-20.0, -10.0, 1)
        with pytest.raises(ValueError, match="整数"):
            im_products_extrapolate(-20.0, -10.0, True)
        with pytest.raises(ValueError, match="有限"):
            im_products_extrapolate(float("nan"), -10.0, 3)


# ─── ③ P1dB 估计 ─────────────────────────────────────────────────────────────

class TestP1dbEstimate:
    def test_default_delta_and_configurable(self):
        # Δ=11.7（RF Cafe 53 datasheet 统计均值）缺省逐位；Δ=10 可配逐位
        assert abs(p1db_from_oip3(30.0) - 18.3) <= TOL
        assert p1db_from_oip3(30.0, delta_db=10.0) == 20.0
        assert DEFAULT_P1DB_DELTA_DB == 11.7

    def test_kundert_constant_dual_path(self):
        # 纯三阶模型 IP3−CP1 间距：常量 vs 测试侧独立表达式（rel 1e-12 双路径）
        independent = -10.0 * math.log10(1.0 - 10.0 ** (-1.0 / 20.0))
        assert abs(CP1_IP3_DELTA_THIRD_ORDER_DB - independent) <= 1e-12
        # Kundert 式(35) verbatim "iCP1dB = iIP3 − 9.6 dB"（1 位小数锚）
        assert round(CP1_IP3_DELTA_THIRD_ORDER_DB, 1) == 9.6

    def test_invalid_rejected(self):
        with pytest.raises(ValueError, match="oip3_dbm"):
            p1db_from_oip3(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="delta_db"):
            p1db_from_oip3(30.0, delta_db=-1.0)
        with pytest.raises(ValueError, match="有限"):
            p1db_from_oip3(float("inf"))


# ─── ④ 最先压缩级定位 + 回退量表 ─────────────────────────────────────────────

class TestCompressionScan:
    def test_first_compression_stage_located(self):
        # 前级强后级弱构造例：L1=20 < OP1dB₁=30（余量 10）；L2=20 > OP1dB₂=5
        # → 最先压缩级 = 第 2 级（index 1），逐位
        r = cascade_compression_scan(
            [{"name": "pa1", "gain_db": 30.0, "p1db_dbm": 30.0},
             {"name": "pa2", "gain_db": 0.0, "p1db_dbm": 5.0}],
            pin_dbm=-10.0, oip3_dbm=30.0)
        assert r["first_compression_stage"] == 1
        assert r["first_compression_name"] == "pa2"
        assert r["n_compressing"] == 1
        rows = r["stages"]
        assert rows[0]["level_out_dbm"] == 20.0
        assert rows[0]["headroom_db"] == 10.0
        assert rows[1]["level_out_dbm"] == 20.0
        assert rows[1]["headroom_db"] == -15.0
        assert rows[1]["compressing"] is True
        assert rows[0]["compressing"] is False
        assert r["min_headroom_db"] == -15.0

    def test_no_compression_returns_none_with_table(self):
        # 回退量表：无级压缩 → first=None，量表仍在（min_headroom 判裕量）
        r = cascade_compression_scan(
            [{"gain_db": 10.0, "p1db_dbm": 20.0}], pin_dbm=0.0,
            oip3_dbm=30.0)
        assert r["first_compression_stage"] is None
        assert r["min_headroom_db"] == 10.0
        assert r["stages"][0]["compressing"] is False

    def test_delta_default_and_explicit(self):
        r = cascade_compression_scan(
            [{"gain_db": 0.0, "p1db_dbm": 10.0}], pin_dbm=-20.0,
            oip3_dbm=30.0, delta_db=10.0)
        assert r["p1db_estimate_dbm"] == 20.0
        assert r["delta_db"] == 10.0
        assert "53" in r["delta_reference"]
        r_default = cascade_compression_scan(
            [{"gain_db": 0.0, "p1db_dbm": 10.0}], pin_dbm=-20.0,
            oip3_dbm=30.0)
        assert abs(r_default["p1db_estimate_dbm"] - 18.3) <= TOL

    def test_oip3_from_stage_merge_when_no_explicit(self):
        # OIP3 三级解析：全级带 ipn_dbm → 内部 order=3 合并（输出参考）− Δ
        stages = [{"gain_db": 20.0, "ipn_dbm": -10.0, "p1db_dbm": 30.0},
                  {"gain_db": 10.0, "ipn_dbm": 0.0, "p1db_dbm": 5.0}]
        r = cascade_compression_scan(stages, pin_dbm=-20.0)
        merge = cascade_ipn_merge(stages, order=3)
        assert r["oip3_source"] == "stage_merge_order3"
        assert r["oip3_dbm"] == merge["ipn_total_output_dbm"]
        assert (r["p1db_estimate_dbm"]
                == merge["ipn_total_output_dbm"] - DEFAULT_P1DB_DELTA_DB)
        # 该链第二级先压缩（L2 = −20+30 = 10 > OP1dB₂=5）
        assert r["first_compression_stage"] == 1

    def test_oip3_unresolvable_estimate_none(self):
        # 两级皆无 IPn 且无显式 OIP3 → 估计 None（不臆造），量表照常出
        r = cascade_compression_scan(
            [{"gain_db": 10.0, "p1db_dbm": 20.0}], pin_dbm=0.0)
        assert r["oip3_dbm"] is None
        assert r["p1db_estimate_dbm"] is None
        assert r["oip3_source"] is None
        assert r["first_compression_stage"] is None

    def test_invalid_rejected(self):
        with pytest.raises(ValueError, match="非空"):
            cascade_compression_scan([], pin_dbm=0.0)
        with pytest.raises(ValueError, match="gain_db"):
            cascade_compression_scan([{"p1db_dbm": 1.0}], pin_dbm=0.0)
        with pytest.raises(ValueError, match="有限"):
            cascade_compression_scan(
                [{"gain_db": 1.0}], pin_dbm=float("nan"))


# ─── ⑤ 三阶幂级数 AM-AM/AM-PM ───────────────────────────────────────────────

class TestAmAmPmThirdOrder:
    def test_im3_dual_path(self):
        # 双路径：公式 20log10(¾|a₃/a₁|v²) vs 测试侧独立精算（rel 1e-12）
        r = am_am_pm_third_order(1.0, -0.01, 0.1)
        independent = 20.0 * math.log10(0.75 * 0.01 * 0.1 * 0.1)
        assert abs(r["im3_dbc"] - independent) <= 1e-12
        assert abs(r["im3_dbc"] - (-82.498774732166)) <= 1e-9

    def test_am_pm_phase_complex_a3(self):
        # 复 a₃ → AM-PM 相位 = arg(1 + ¾(a₃/a₁)v²)（测试侧 atan 独立路径）；
        # 实 a₃ → 相位恒 0（逐位）
        r = am_am_pm_third_order(1.0, 0.01j, 0.1)
        independent = math.degrees(math.atan(0.75 * 0.01 * 0.1 * 0.1))
        assert abs(r["am_pm_phase_deg"] - independent) <= 1e-12
        r_real = am_am_pm_third_order(1.0, -0.01, 0.1)
        assert r_real["am_pm_phase_deg"] == 0.0

    def test_v1db_reduces_to_kundert_acp(self):
        # a₃ 实负：v1db 严格退化为 Kundert 式(33)（αCP²=(4a₁/(3|a₃|))·
        # (1−10^(−1/20))，αCP=幅度=[·]^½，rel 1e-12）
        a1, a3 = 1.0, -0.01
        r = am_am_pm_third_order(a1, a3, 0.1)
        independent = ((4.0 * abs(a1) / (3.0 * abs(a3)))
                       * (1.0 - 10.0 ** (-1.0 / 20.0))) ** 0.5
        assert abs(r["v_1db_v"] - independent) <= 1e-12

    def test_ip3_p1db_spacing_nine_point_six(self):
        # 独立回收：同一幂级数的 IP3 与 P1dB 电压 → 功率间距 ≡ 9.6357 dB
        # （Kundert 式(35) 的 −9.6 dB；双路径：间距 vs 常量 rel 1e-9）
        r = am_am_pm_third_order(1.0, -0.01, 0.1)
        spacing = 10.0 * math.log10(
            (r["iip3_amplitude_v"] / r["v_1db_v"]) ** 2)
        assert abs(spacing - CP1_IP3_DELTA_THIRD_ORDER_DB) <= 1e-9
        assert r["cp1_ip3_delta_db"] == CP1_IP3_DELTA_THIRD_ORDER_DB

    def test_zero_a3_linear_limit(self):
        # a3=0：IM3/IIP3/v1db 如实 None，AM-AM/AM-PM 严格 0
        r = am_am_pm_third_order(2.0, 0.0, 0.5)
        assert r["im3_dbc"] is None
        assert r["iip3_amplitude_v"] is None
        assert r["v_1db_v"] is None
        assert r["am_am_delta_db"] == 0.0
        assert r["am_pm_phase_deg"] == 0.0
        assert r["small_signal_gain_db"] == 20.0 * math.log10(2.0)

    def test_invalid_rejected(self):
        with pytest.raises(ValueError, match="a1"):
            am_am_pm_third_order(0.0, -0.01, 0.1)
        with pytest.raises(ValueError, match="v_in"):
            am_am_pm_third_order(1.0, -0.01, 0.0)
        with pytest.raises(ValueError, match="实数或复数"):
            am_am_pm_third_order(True, -0.01, 0.1)
        with pytest.raises(ValueError, match="有限"):
            am_am_pm_third_order(float("nan"), -0.01, 0.1)


# ─── ⑥ 级联 AM-PM 加权（工程近似）────────────────────────────────────────────

def _amp_stage(gain, op1db, alpha, psat=None, name=None):
    st = {"gain_db": gain, "p1db_dbm": op1db, "alpha_deg_per_db": alpha}
    if psat is not None:
        st["p_sat_dbm"] = psat
    if name is not None:
        st["name"] = name
    return st


class TestCascadeAmPm:
    def test_single_stage_identity(self):
        # 锚：单级链 w=1 → α_tot ≡ α_1（逐位）
        r = cascade_am_pm([_amp_stage(20.0, 25.0, 1.5, psat=27.0)],
                          pin_dbm=10.0)
        assert r["alpha_total_deg_per_db"] == 1.5
        assert r["weights"] == [1.0]
        assert r["dominant_stage"] == 0
        assert r["status"] == "engineering_approximation"
        assert "工程近似" in r["note"] and "#122" in r["note"]

    def test_dominant_saturated_stage(self):
        # 近饱和主导级加权：级 1 未压缩（w=0）、级 2 满压缩（w=1）→ α_tot=α₂
        r = cascade_am_pm(
            [_amp_stage(10.0, 40.0, 0.5, psat=45.0, name="driver"),
             _amp_stage(10.0, 10.0, 2.0, psat=20.0, name="pa")],
            pin_dbm=0.0)
        assert r["weights"] == [0.0, 1.0]
        assert r["alpha_total_deg_per_db"] == 2.0
        assert r["dominant_stage"] == 1

    def test_equal_compression_is_mean(self):
        # 等压缩等权 → 算术均值（(1.0+3.0)/2 = 2.0 逐位）
        stages = [_amp_stage(0.0, 10.0, 1.0, psat=14.0),
                  _amp_stage(0.0, 10.0, 3.0, psat=14.0)]
        r = cascade_am_pm(stages, pin_dbm=12.0)
        # L=12，comp = (12−10)/(14−10) = 0.5（归一中点）
        assert all(abs(c - 0.5) <= 1e-12 for c in
                   [row["comp"] for row in r["per_stage"]])
        assert r["alpha_total_deg_per_db"] == 2.0

    def test_no_compression_gives_none(self):
        r = cascade_am_pm([_amp_stage(10.0, 40.0, 1.0, psat=45.0)],
                          pin_dbm=-20.0)
        assert r["alpha_total_deg_per_db"] is None
        assert r["status"] == "no_stage_in_compression"
        assert r["weights"] == [0.0]

    def test_fail_fast_validation(self):
        # alpha 无 p1db → ValueError；p_sat ≤ OP1dB → ValueError；缺 alpha →
        with pytest.raises(ValueError, match="p1db_dbm"):
            cascade_am_pm([{"gain_db": 1.0, "alpha_deg_per_db": 1.0}],
                          pin_dbm=0.0)
        with pytest.raises(ValueError, match="p_sat_dbm"):
            cascade_am_pm([_amp_stage(1.0, 10.0, 1.0, psat=9.0)], pin_dbm=0.0)
        with pytest.raises(ValueError, match="alpha_deg_per_db"):
            cascade_am_pm([{"gain_db": 1.0, "p1db_dbm": 10.0}], pin_dbm=0.0)


# ─── ⑦ 端到端扫描 + 结构冻结 ─────────────────────────────────────────────────

class TestNonlinearScan:
    def test_end_to_end_and_to_dict_json(self):
        stages = [
            {"name": "lna", "gain_db": 20.0, "ipn_dbm": -10.0,
             "p1db_dbm": -12.0, "p_sat_dbm": -10.0, "alpha_deg_per_db": 0.5},
            {"name": "mix", "gain_db": 10.0, "ipn_dbm": 0.0,
             "p1db_dbm": 5.0, "alpha_deg_per_db": 1.0},
        ]
        # pin=−30 须低于合并 IIPn≈−20.41 dBm（外推域内）
        scan = cascade_nonlinear_scan(stages, order=3, pin_dbm=-30.0,
                                      oip3_dbm=30.0)
        d = scan.to_dict()
        # JSON 往返（allow_nan=False：不得含 NaN/Inf）
        payload = json.loads(json.dumps(d, allow_nan=False))
        assert payload["order"] == 3
        assert abs(payload["merge"]["ipn_total_input_dbm"]
                   - (-20.41392685158225)) <= TOL
        # im_at_pin：合并 IIPn 在 pin=−30 处的 IM3 = 2·(−30−(−20.4139…))
        expect_im = 2.0 * (-30.0 - payload["merge"]["ipn_total_input_dbm"])
        assert abs(payload["im_at_pin"]["im_n_dbc"] - expect_im) <= 1e-12
        assert payload["compression"]["oip3_source"] == "explicit"
        assert payload["compression"]["p1db_estimate_dbm"] == 18.3
        # L1=−10 > OP1dB₁=−12 → LNA 即最先压缩级；comp1=1 → AM-PM 主导级 0
        assert payload["compression"]["first_compression_stage"] == 0
        assert payload["am_pm"]["status"] == "engineering_approximation"
        assert payload["am_pm"]["alpha_total_deg_per_db"] == 0.5
        assert payload["am_pm"]["weights"] == [1.0, 0.0]

    def test_mixed_ipn_stages_merge_none(self):
        # 混合缺 ipn / 混合缺 alpha：合并与 AM-PM 如实 None（不部分造假），
        # 压缩面照常
        scan = cascade_nonlinear_scan(
            [{"gain_db": 1.0, "ipn_dbm": 0.0},
             {"gain_db": 1.0, "p1db_dbm": 100.0, "alpha_deg_per_db": 1.0}],
            pin_dbm=-10.0)
        d = scan.to_dict()
        assert d["merge"] is None
        assert d["im_at_pin"] is None
        assert d["am_pm"] is None
        assert d["compression"] is not None

    def test_am_pm_requires_pin(self):
        with pytest.raises(ValueError, match="pin_dbm"):
            cascade_nonlinear_scan(
                [{"gain_db": 1.0, "p1db_dbm": 0.0, "alpha_deg_per_db": 1.0}])

    def test_existing_budget_result_shape_frozen(self):
        # 结构冻结钉（#315 同源）：新面零改变既有 cascade_budget 消费者——
        # 顶层键集合冻结；新增非线性键一旦混入即红
        r = cascade_budget(
            [{"type": "atten", "gain_db": -3.0, "nf_db": 3.0},
             {"type": "amp", "gain_db": 20.0, "nf_db": 2.0,
              "iip3_dbm": -10.0}],
            snr_min_db=10.0, rx_power_dbm=-90.0, bw_hz=1e6)
        frozen = {
            "n_stages", "gain_total_db", "nf_total_db", "iip3_total_dbm",
            "oip3_total_dbm", "p1db_out_dbm", "p1db_in_dbm",
            "p1db_convention", "iip3_convention", "bw_hz", "bw_source",
            "t_kelvin", "thermal_floor_dbm_per_hz", "noise_floor_dbm",
            "sfdr_db", "snr_min_db", "sensitivity_dbm", "rx_power_dbm",
            "link_margin_db", "stages",
        }
        assert set(r.keys()) == frozen


class TestServices:
    """两个薄服务信封（JSON 进出；错误 ok=False 不抛，service 层规则 4）。"""

    def test_nonlinear_cascade_report_ok_and_error(self):
        from rfauto.service.cascade_service import nonlinear_cascade_report

        stages = [{"name": "lna", "gain_db": 20.0, "ipn_dbm": -10.0,
                   "p1db_dbm": -12.0, "alpha_deg_per_db": 0.5},
                  {"name": "mix", "gain_db": 10.0, "ipn_dbm": 0.0,
                   "p1db_dbm": 5.0, "alpha_deg_per_db": 1.0}]
        out = nonlinear_cascade_report(stages, order=3, pin_dbm=-30.0)
        assert out["ok"] is True
        result = out["result"]
        assert abs(result["merge"]["ipn_total_input_dbm"]
                   - (-20.41392685158225)) <= TOL
        assert result["compression"]["first_compression_stage"] == 0
        assert result["am_pm"]["alpha_total_deg_per_db"] == 0.5
        bad = nonlinear_cascade_report([{"ipn_dbm": 0.0}], order=3)
        # 缺 gain_db → core 显式 ValueError → ok=False 信封（不抛出）
        assert bad["ok"] is False and "gain_db" in bad["error"]

    def test_pim_products_report_ok_and_error(self):
        from rfauto.service.cascade_service import pim_products_report

        out = pim_products_report(2.4e9, 2.41e9, p_max=3,
                                  rx_center_hz=2.39e9, rx_bw_hz=1e6,
                                  amplitudes=[{"m": 2, "n": 1, "side": "-",
                                               "dbc": -160.0}])
        assert out["ok"] is True
        assert out["result"]["n_products"] == 6
        assert out["result"]["n_in_band"] == 1
        bad = pim_products_report(2.4e9, 2.4e9)
        assert bad["ok"] is False and "退化单载波" in bad["error"]
