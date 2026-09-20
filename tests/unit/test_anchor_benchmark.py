"""G8 引擎基准扩容四锚判读内核单测（纯函数零真机，合成数组钉门边界）。

覆盖 core/anchor_benchmark 四函数（ratrace/atten/via/msl_cpw）：
① 归档真值回放（runs/*_smoke 离线复算所得，本会话实测）→ PASS；
② 每门 PASS/FAIL 边界（≤ 与 < 语义逐门钉死，防静默放水）；
③ None/NaN 诚实性：任一输入缺失 → 对应门 FAIL + reason 写明「不可判」
   （#122 不凑绿）；
④ 门常量钉值：改门=显式重标定决策，须同步本文件与 golden 快照；
⑤ msl_cpw 无源上界（20260915b 增补）：|S21| 带内 max ≤1.02 上侧门
   与 mean ≥0.90 下侧门共同折入 thru_ok；首轮真跑归档（mean 1.0296 /
   带内 max 1.290）在旧纯下侧门 PASS、现门如实 FAIL；带内 max 缺失
   （旧四参调用）→ 不可判 FAIL 而非静默过门；
⑥ via 无源上界（20260918a 增补）：与 msl_cpw 完全同构
   （双侧门=均值下界+峰值上界共折 thru_ok，passive_ok 诊断键）；合成
   max|S21|>1.02 负控制 → verdict FAIL 且 passive_ok=False；归档 pt3
   （带内 max 0.9503 离线复算）现门零翻转；带内 max 缺失（旧五参调用）
   → 不可判 FAIL 而非静默过门。
"""

from __future__ import annotations

import math

import pytest

from rfauto.core import anchor_benchmark as ab
from rfauto.core.anchor_verdict import S11_HEALTH_DB

# 归档真值（离线复算，与 smoke 归档日志逐值一致）
RATRACE_PT9 = dict(delta_eps_pct=0.89, s21_db=-3.11, s41_db=-3.27,
                   s31_db=-24.32, s24_db=-23.81, s11_db=-26.57,
                   recip_lin=0.0017)
ATTEN_PI_PT2 = dict(delta_eps_pct=0.96, s21_db_band_mean=-9.66,
                    s11_db_band_max=-12.77)
ATTEN_T_PT1 = dict(delta_eps_pct=0.96, s21_db_band_mean=-9.64,
                   s11_db_band_max=-15.34)
VIA_PT3 = dict(delta_eps1_pct=0.79, s11_db_band_max=-26.01,
               s21_lin_mean=0.944, recip_db=0.0, delta_eps2_pct=10.93,
               # 带内 max 为 20260918a 新增统计量：runs/via_smoke/pt3
               # sparams.csv 离线复算（401 点，max@2.25GHz）
               s21_lin_band_max=0.9503)
# msl_cpw 合成通过点（真机结果见 golden 快照，本文件只钉门语义）
CPW_GOOD = dict(delta_eps1_pct=1.0, delta_eps2_pct=-1.5,
                s11_db_band_max=-15.0, s21_lin_mean=0.95,
                s21_lin_band_max=0.98)
# msl_cpw 首轮真跑归档（runs/benchmark/msl_cpw_m0.4 sparams.csv 离线复算，
# 2026-09-15）：旧门 20260915 PASS，现门 20260915b 无源上界如实 FAIL
CPW_ARCHIVE_M04 = dict(delta_eps1_pct=0.373, delta_eps2_pct=-1.04,
                       s11_db_band_max=-15.29, s21_lin_mean=1.0296,
                       s21_lin_band_max=1.2902)


class TestGateConstantsPinned:
    """门常量钉值（改门须显式重标定并附真机证据）。"""

    def test_gate_version(self):
        assert ab.GATE_VERSION == "20260918a"

    def test_s11_health_single_source(self):
        # -10dB 门单一事实源在 core/anchor_verdict（只 import 不改）
        assert S11_HEALTH_DB == -10.0

    def test_constants(self):
        assert ab.EPS_EFF_TOL_PCT == 2.0
        assert (ab.RATRACE_SPLIT_TARGET_DB, ab.RATRACE_SPLIT_TOL_DB,
                ab.RATRACE_BALANCE_MAX_DB) == (-3.0, 1.0, 0.5)
        assert (ab.RATRACE_ISO_DELTA_MAX_DB, ab.RATRACE_ISO_OUT_MAX_DB,
                ab.RATRACE_RECIP_MAX_LIN) == (-20.0, -15.0, 0.02)
        assert (ab.ATTEN_TARGET_DB, ab.ATTEN_FLAT_TOL_DB,
                ab.ATTEN_S11_FLOOR_DB) == (-10.0, 0.5, -12.0)
        assert (ab.VIA_S21_MIN_LIN, ab.VIA_RECIP_MAX_DB) == (0.90, 0.5)
        # via 无源上界 = 理想无源地板 + 2% 数值裕量（20260918a，与 CPW 同式）
        assert abs(ab.VIA_S21_MAX_LIN - 1.02) < 1e-12
        assert ab.VIA_S21_MAX_LIN > 1.0 and ab.VIA_S21_MIN_LIN < 1.0
        assert (ab.CPW_S21_MIN_LIN, ab.CPW_IDEAL_S21_LIN) == (0.90, 1.0)
        # 无源上界 = 理想级联地板 + 2% 数值裕量（20260915b）
        assert abs(ab.CPW_S21_MAX_LIN - 1.02) < 1e-12
        assert ab.CPW_S21_MAX_LIN > ab.CPW_IDEAL_S21_LIN > ab.CPW_S21_MIN_LIN


# ─── ratrace 七门 ─────────────────────────────────────────────────────────────

class TestRatraceVerdict:

    def test_archive_pt9_passes_all_seven_gates(self):
        r = ab.ratrace_benchmark_verdict(**RATRACE_PT9)
        assert r["verdict"] == "PASS"
        assert r["reason"] == ""
        assert all(r[k] for k in ("beta_ok", "split_ok", "balance_ok",
                                  "iso_delta_ok", "iso_out_ok",
                                  "match_ok", "recip_ok"))
        assert r["balance_db"] == pytest.approx(0.16, abs=1e-9)

    @pytest.mark.parametrize("delta,ok", [(2.0, True), (-2.0, True),
                                          (2.01, False), (-2.01, False)])
    def test_beta_boundary_inclusive(self, delta, ok):
        r = ab.ratrace_benchmark_verdict(**{**RATRACE_PT9,
                                            "delta_eps_pct": delta})
        assert r["beta_ok"] is ok
        assert (r["verdict"] == "PASS") is ok
        if not ok:
            assert "β 金标准超门" in r["reason"]

    @pytest.mark.parametrize("s21,s41,split_ok,balance_ok", [
        (-4.0, -3.5, True, True),      # |S21| 恰在 -3±1 下沿；均分差 0.5 上沿
        (-4.01, -3.5, False, False),   # |S21| 越下沿；均分差 0.51 超
        (-2.0, -2.0, True, True),      # 上沿
        (-1.99, -2.0, False, True),    # 越上沿，均分差 0.01 仍过
        (-2.75, -3.25, True, True),    # 均分差恰 0.5
        (-2.7, -3.3, True, False),     # 两者在 ±1 内但均分差 0.6 超
    ])
    def test_split_and_balance_boundaries(self, s21, s41, split_ok,
                                          balance_ok):
        r = ab.ratrace_benchmark_verdict(**{**RATRACE_PT9, "s21_db": s21,
                                            "s41_db": s41})
        assert r["split_ok"] is split_ok
        assert r["balance_ok"] is balance_ok
        assert (r["verdict"] == "PASS") is (split_ok and balance_ok)

    @pytest.mark.parametrize("key,flag,pass_v,fail_v", [
        ("s31_db", "iso_delta_ok", -20.0, -19.99),
        ("s24_db", "iso_out_ok", -15.0, -14.99),
        ("s11_db", "match_ok", -10.0, -9.99),
        ("recip_lin", "recip_ok", 0.02, 0.0201),
    ])
    def test_single_gate_boundaries_inclusive(self, key, flag, pass_v,
                                              fail_v):
        r_pass = ab.ratrace_benchmark_verdict(**{**RATRACE_PT9, key: pass_v})
        assert r_pass[flag] is True and r_pass["verdict"] == "PASS"
        r_fail = ab.ratrace_benchmark_verdict(**{**RATRACE_PT9, key: fail_v})
        assert r_fail[flag] is False and r_fail["verdict"] == "FAIL"
        # 其它门不受影响
        others = [k for k in ("beta_ok", "split_ok", "balance_ok",
                              "iso_delta_ok", "iso_out_ok", "match_ok",
                              "recip_ok") if k != flag]
        assert all(r_fail[k] for k in others)

    @pytest.mark.parametrize("key,flags", [
        ("delta_eps_pct", ("beta_ok",)),
        ("s21_db", ("split_ok", "balance_ok")),
        ("s41_db", ("split_ok", "balance_ok")),
        ("s31_db", ("iso_delta_ok",)),
        ("s24_db", ("iso_out_ok",)),
        ("s11_db", ("match_ok",)),
        ("recip_lin", ("recip_ok",)),
    ])
    def test_none_input_is_honest_fail(self, key, flags):
        r = ab.ratrace_benchmark_verdict(**{**RATRACE_PT9, key: None})
        assert r["verdict"] == "FAIL"
        for f in flags:
            assert r[f] is False
        assert "不可判" in r["reason"] and "如实 FAIL" in r["reason"]

    def test_nan_treated_as_missing(self):
        r = ab.ratrace_benchmark_verdict(**{**RATRACE_PT9,
                                            "recip_lin": math.nan})
        assert r["verdict"] == "FAIL" and r["recip_ok"] is False
        assert "不可判" in r["reason"]

    def test_all_none_every_gate_false(self):
        r = ab.ratrace_benchmark_verdict(None, None, None, None, None,
                                         None, None)
        assert r["verdict"] == "FAIL"
        assert not any(r[k] for k in ("beta_ok", "split_ok", "balance_ok",
                                      "iso_delta_ok", "iso_out_ok",
                                      "match_ok", "recip_ok"))
        assert r["balance_db"] is None


# ─── atten（π/T 共用）三门 ────────────────────────────────────────────────────

class TestAttenVerdict:

    @pytest.mark.parametrize("vals,dev", [(ATTEN_PI_PT2, 0.34),
                                          (ATTEN_T_PT1, 0.36)])
    def test_archives_pass_under_calibrated_floor(self, vals, dev):
        r = ab.atten_benchmark_verdict(**vals)
        assert r["verdict"] == "PASS" and r["reason"] == ""
        assert r["atten_dev_db"] == pytest.approx(dev, abs=1e-9)

    def test_old_minus20_gate_would_have_failed_pi(self):
        # 旧 -20 门（校准前）对 pt2 -12.77dB 判 FAIL；
        # 现门 -12 商用 lumped 地板 PASS——内核只认现门，旧判定归 provenance
        assert ATTEN_PI_PT2["s11_db_band_max"] > -20.0
        assert ab.atten_benchmark_verdict(**ATTEN_PI_PT2)["match_ok"] is True

    @pytest.mark.parametrize("mean,ok", [(-10.5, True), (-9.5, True),
                                         (-10.51, False), (-9.49, False)])
    def test_flatness_boundary_inclusive(self, mean, ok):
        r = ab.atten_benchmark_verdict(0.0, mean, -20.0)
        assert r["atten_ok"] is ok and (r["verdict"] == "PASS") is ok
        if not ok:
            assert "衰减超门" in r["reason"]

    @pytest.mark.parametrize("s11,ok", [(-12.01, True), (-12.0, False),
                                        (-11.99, False)])
    def test_match_floor_is_strict_less_than(self, s11, ok):
        r = ab.atten_benchmark_verdict(0.0, -10.0, s11)
        assert r["match_ok"] is ok and (r["verdict"] == "PASS") is ok

    @pytest.mark.parametrize("delta,ok", [(2.0, True), (2.01, False)])
    def test_beta_boundary(self, delta, ok):
        r = ab.atten_benchmark_verdict(delta, -10.0, -20.0)
        assert r["beta_ok"] is ok

    def test_custom_target(self):
        r = ab.atten_benchmark_verdict(0.0, -20.3, -20.0,
                                       atten_target_db=-20.0)
        assert r["atten_ok"] is True
        assert r["atten_dev_db"] == pytest.approx(0.3, abs=1e-9)

    @pytest.mark.parametrize("key,flag", [
        ("delta_eps_pct", "beta_ok"),
        ("s21_db_band_mean", "atten_ok"),
        ("s11_db_band_max", "match_ok"),
    ])
    def test_none_input_is_honest_fail(self, key, flag):
        r = ab.atten_benchmark_verdict(**{**ATTEN_PI_PT2, key: None})
        assert r["verdict"] == "FAIL" and r[flag] is False
        assert "不可判" in r["reason"]
        if key == "s21_db_band_mean":
            assert r["atten_dev_db"] is None


# ─── via 四门（β1 单判，β2 诊断） ─────────────────────────────────────────────

class TestViaVerdict:

    def test_archive_pt3_passes_beta1_single_judge(self):
        r = ab.via_benchmark_verdict(**VIA_PT3)
        assert r["verdict"] == "PASS" and r["reason"] == ""
        assert all(r[k] for k in ("beta1_ok", "match_ok", "thru_ok",
                                  "recip_ok"))
        # β2 +10.93% 只作诊断回传，不参与判定（real_modal_difference）
        assert r["beta2_modal_difference_pct"] == pytest.approx(10.93)

    def test_beta2_never_gates(self):
        for d2 in (None, 0.0, 10.93, 100.0, math.nan):
            r = ab.via_benchmark_verdict(**{**VIA_PT3, "delta_eps2_pct": d2})
            assert r["verdict"] == "PASS"
        assert ab.via_benchmark_verdict(
            **{**VIA_PT3, "delta_eps2_pct": None})[
            "beta2_modal_difference_pct"] is None

    @pytest.mark.parametrize("key,flag,pass_v,fail_v", [
        ("delta_eps1_pct", "beta1_ok", 2.0, 2.01),
        ("s11_db_band_max", "match_ok", -10.01, -10.0),   # 严格 <
        ("s21_lin_mean", "thru_ok", 0.90, 0.8999),        # ≥
        ("recip_db", "recip_ok", 0.5, 0.501),             # ≤
    ])
    def test_gate_boundaries(self, key, flag, pass_v, fail_v):
        r_pass = ab.via_benchmark_verdict(**{**VIA_PT3, key: pass_v})
        assert r_pass[flag] is True and r_pass["verdict"] == "PASS"
        r_fail = ab.via_benchmark_verdict(**{**VIA_PT3, key: fail_v})
        assert r_fail[flag] is False and r_fail["verdict"] == "FAIL"

    @pytest.mark.parametrize("key,flag", [
        ("delta_eps1_pct", "beta1_ok"),
        ("s11_db_band_max", "match_ok"),
        ("s21_lin_mean", "thru_ok"),
        ("recip_db", "recip_ok"),
        ("s21_lin_band_max", "thru_ok"),   # 上侧缺失同样折入 thru_ok
    ])
    def test_none_input_is_honest_fail(self, key, flag):
        r = ab.via_benchmark_verdict(**{**VIA_PT3, key: None})
        assert r["verdict"] == "FAIL" and r[flag] is False
        assert "不可判" in r["reason"]
        if key == "s21_lin_band_max":
            assert r["passive_ok"] is False

    def test_recip_missing_archive_log_reason_names_cause(self):
        # sparams.csv 无 S22 列——互易值只能来自归档日志；缺失时如实 FAIL
        r = ab.via_benchmark_verdict(**{**VIA_PT3, "recip_db": None})
        assert "无 S22 列" in r["reason"]


# ─── via 无源上界（20260918a 增补） ─────────────────────────────────────

class TestViaPassiveUpperBound:
    """|S21| 带内 max ≤ VIA_S21_MAX_LIN 上侧门：与 msl_cpw 20260915b 同构。

    无源二端口逐频 |S21|≤1 是能量守恒硬约束；纯下侧 mean 门（旧 20260915b
    口径）对 >1 的端口提取伪象会非物理放行。合成数据钉：健康线过门；
    max|S21|>1.02 负控制如实 FAIL 且 passive_ok=False；上界缺失（旧五参
    调用）不可判 FAIL 而非静默过门；归档 pt3 现门零翻转（收紧为预防性）。
    """

    def test_passive_line_passes(self):
        # 有耗过孔过渡合理形态：mean 0.95、带内 max 0.98（< 1 且 < 上界）
        r = ab.via_benchmark_verdict(0.5, -20.0, 0.95, 0.0, 5.0,
                                     s21_lin_band_max=0.98)
        assert r["verdict"] == "PASS" and r["reason"] == ""
        assert r["thru_ok"] is True and r["passive_ok"] is True

    def test_s21_1p03_trips_upper_bound(self):
        # 负控制：mean 1.03 过旧纯下侧门（≥0.90），带内 max 1.03>1.02 → FAIL
        r = ab.via_benchmark_verdict(0.5, -20.0, 1.03, 0.0, 5.0,
                                     s21_lin_band_max=1.03)
        assert r["verdict"] == "FAIL"
        assert r["passive_ok"] is False and r["thru_ok"] is False
        assert "无源上界超门" in r["reason"]
        assert "1.0300" in r["reason"] and "1.02" in r["reason"]
        # 其余门不受牵连
        assert all(r[k] for k in ("beta1_ok", "match_ok", "recip_ok"))

    @pytest.mark.parametrize("band_max,ok", [
        (1.02, True),      # 恰在上界（≤ 语义，含端点）
        (1.0200001, False),
        (1.0, True),       # 理想无源地板
        (0.90, True),
    ])
    def test_upper_bound_boundary_inclusive(self, band_max, ok):
        r = ab.via_benchmark_verdict(**{**VIA_PT3,
                                        "s21_lin_band_max": band_max})
        assert r["passive_ok"] is ok
        assert (r["verdict"] == "PASS") is ok

    def test_floor_and_ceiling_independent_but_both_gate_thru(self):
        # 下侧破、上侧好：thru FAIL 但 passive_ok True
        r = ab.via_benchmark_verdict(**{**VIA_PT3, "s21_lin_mean": 0.85,
                                        "s21_lin_band_max": 0.90})
        assert r["thru_ok"] is False and r["passive_ok"] is True
        assert "传输超门" in r["reason"] and "无源上界" not in r["reason"]
        # 下侧好、上侧破：thru FAIL 且 passive_ok False
        r = ab.via_benchmark_verdict(**{**VIA_PT3, "s21_lin_mean": 0.95,
                                        "s21_lin_band_max": 1.5})
        assert r["thru_ok"] is False and r["passive_ok"] is False
        assert "无源上界超门" in r["reason"] and "传输超门" not in r["reason"]

    def test_archive_pt3_zero_flip_under_tightened_gate(self):
        # 归档 pt3 离线复算带内 max 0.9503：旧纯下侧门 PASS、现门仍 PASS
        # ——收紧是预防性（无历史误判需要翻案），非 msl_cpw 改判情形
        r = ab.via_benchmark_verdict(**VIA_PT3)
        assert r["verdict"] == "PASS" and r["passive_ok"] is True
        assert VIA_PT3["s21_lin_mean"] >= ab.VIA_S21_MIN_LIN  # 旧门本就过
        assert VIA_PT3["s21_lin_band_max"] <= ab.VIA_S21_MAX_LIN

    def test_mean_below_unity_does_not_rescue_band_max_over_bound(self):
        # mean 健康（0.944）不能稀释带内 max 超门——上界取带内 max 语义
        r = ab.via_benchmark_verdict(**{**VIA_PT3, "s21_lin_band_max": 1.021})
        assert r["verdict"] == "FAIL" and r["passive_ok"] is False

    def test_legacy_five_positional_call_is_honest_fail_not_silent_pass(self):
        # 旧 harness 五位置参数调用：不抛 TypeError，但上界不可判 → FAIL
        r = ab.via_benchmark_verdict(0.5, -20.0, 0.95, 0.0, 5.0)
        assert r["verdict"] == "FAIL" and r["passive_ok"] is False
        assert "不可判" in r["reason"] and "s21_lin_band_max" in r["reason"]


# ─── msl_cpw 五门（四门 + 20260915b 无源上界折入 thru_ok） ───────────────────

class TestMslCpwVerdict:

    def test_synthetic_pass_and_info_field(self):
        r = ab.msl_cpw_benchmark_verdict(**CPW_GOOD)
        assert r["verdict"] == "PASS" and r["reason"] == ""
        assert all(r[k] for k in ("beta1_ok", "beta2_ok", "match_ok",
                                  "thru_ok"))
        assert r["s21_vs_ideal_lin_dev"] == pytest.approx(0.05, abs=1e-9)

    def test_ideal_cascade_deviation_is_info_only(self):
        # |S21|=0.90 对理想级联 1.0 偏差 0.10——只记信息量，不设门
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, "s21_lin_mean": 0.90})
        assert r["verdict"] == "PASS"
        assert r["s21_vs_ideal_lin_dev"] == pytest.approx(0.10, abs=1e-9)

    @pytest.mark.parametrize("key,flag,pass_v,fail_v", [
        ("delta_eps1_pct", "beta1_ok", -2.0, -2.01),
        ("delta_eps2_pct", "beta2_ok", 2.0, 2.01),
        ("s11_db_band_max", "match_ok", -10.01, -10.0),   # 严格 <
        ("s21_lin_mean", "thru_ok", 0.90, 0.8999),        # ≥
    ])
    def test_gate_boundaries(self, key, flag, pass_v, fail_v):
        r_pass = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, key: pass_v})
        assert r_pass[flag] is True and r_pass["verdict"] == "PASS"
        r_fail = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, key: fail_v})
        assert r_fail[flag] is False and r_fail["verdict"] == "FAIL"

    def test_port2_cpwg_gate_independent_of_port1(self):
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, "delta_eps2_pct": 5.0})
        assert r["beta1_ok"] is True and r["beta2_ok"] is False
        assert "副锚超门" in r["reason"] and "CPWG" in r["reason"]

    @pytest.mark.parametrize("key,flag", [
        ("delta_eps1_pct", "beta1_ok"),
        ("delta_eps2_pct", "beta2_ok"),
        ("s11_db_band_max", "match_ok"),
        ("s21_lin_mean", "thru_ok"),
        ("s21_lin_band_max", "thru_ok"),   # 上侧缺失同样折入 thru_ok
    ])
    def test_none_input_is_honest_fail(self, key, flag):
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, key: None})
        assert r["verdict"] == "FAIL" and r[flag] is False
        assert "不可判" in r["reason"]
        if key == "s21_lin_mean":
            assert r["s21_vs_ideal_lin_dev"] is None
        if key == "s21_lin_band_max":
            assert r["passive_ok"] is False

    def test_all_none(self):
        r = ab.msl_cpw_benchmark_verdict(None, None, None, None,
                                         s21_lin_band_max=None)
        assert r["verdict"] == "FAIL"
        assert r["reason"].count("不可判") == 5   # 五门（含无源上界）


# ─── msl_cpw 无源上界（20260915b 增补） ──────────────────────────────────

class TestMslCpwPassiveUpperBound:
    """|S21| 带内 max ≤ CPW_S21_MAX_LIN 上侧门：无源二端口逐频 |S21|≤1 硬约束。

    合成数据钉三件事：无源健康线过门；|S21| 触上界如实 FAIL；首轮真跑
    归档（旧纯下侧门 PASS）在现门如实改判 FAIL（#122 不凑绿，历史 PASS
    不因"曾经过门"而保留）。
    """

    def test_passive_line_passes(self):
        # 40mm 有耗线合理形态：mean 0.95、带内 max 0.98（< 1 且 < 上界）
        r = ab.msl_cpw_benchmark_verdict(1.0, -1.5, -15.0, 0.95,
                                         s21_lin_band_max=0.98)
        assert r["verdict"] == "PASS" and r["reason"] == ""
        assert r["thru_ok"] is True and r["passive_ok"] is True

    def test_s21_1p03_trips_upper_bound(self):
        # |S21| 1.03（mean 与带内 max 同值的平坦合成）：>1.02 上界 → FAIL
        r = ab.msl_cpw_benchmark_verdict(1.0, -1.5, -15.0, 1.03,
                                         s21_lin_band_max=1.03)
        assert r["verdict"] == "FAIL"
        assert r["passive_ok"] is False and r["thru_ok"] is False
        assert "无源上界超门" in r["reason"]
        assert "1.0300" in r["reason"] and "1.02" in r["reason"]
        # 其余门不受牵连
        assert all(r[k] for k in ("beta1_ok", "beta2_ok", "match_ok"))

    @pytest.mark.parametrize("band_max,ok", [
        (1.02, True),      # 恰在上界（≤ 语义，含端点）
        (1.0200001, False),
        (1.0, True),       # 理想级联地板
        (0.90, True),
    ])
    def test_upper_bound_boundary_inclusive(self, band_max, ok):
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD,
                                            "s21_lin_band_max": band_max})
        assert r["passive_ok"] is ok
        assert (r["verdict"] == "PASS") is ok

    def test_floor_and_ceiling_independent_but_both_gate_thru(self):
        # 下侧破、上侧好：thru FAIL 但 passive_ok True
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, "s21_lin_mean": 0.85,
                                            "s21_lin_band_max": 0.90})
        assert r["thru_ok"] is False and r["passive_ok"] is True
        assert "传输超门" in r["reason"] and "无源上界" not in r["reason"]
        # 下侧好、上侧破：thru FAIL 且 passive_ok False
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_GOOD, "s21_lin_mean": 0.95,
                                            "s21_lin_band_max": 1.5})
        assert r["thru_ok"] is False and r["passive_ok"] is False
        assert "无源上界超门" in r["reason"] and "传输超门" not in r["reason"]

    def test_archived_first_run_flips_from_pass_to_fail(self):
        # 首轮真跑归档：β 双锚与匹配门全过、mean 1.0296 过旧下侧门（≥0.90），
        # 但带内 max 1.2902 超无源上界 → 现门如实 FAIL
        r = ab.msl_cpw_benchmark_verdict(**CPW_ARCHIVE_M04)
        assert r["verdict"] == "FAIL"
        assert all(r[k] for k in ("beta1_ok", "beta2_ok", "match_ok"))
        assert CPW_ARCHIVE_M04["s21_lin_mean"] >= ab.CPW_S21_MIN_LIN  # 旧门会放行
        assert r["passive_ok"] is False and r["thru_ok"] is False
        assert "1.2902" in r["reason"] and "能量守恒" in r["reason"]
        # 信息量字段照常回传（mean 对理想地板偏差 0.0296）
        assert r["s21_vs_ideal_lin_dev"] == pytest.approx(0.0296, abs=1e-9)

    def test_legacy_four_positional_call_is_honest_fail_not_silent_pass(self):
        # 旧 harness 四位置参数调用：不抛 TypeError，但上界不可判 → FAIL
        r = ab.msl_cpw_benchmark_verdict(1.0, -1.5, -15.0, 0.95)
        assert r["verdict"] == "FAIL" and r["passive_ok"] is False
        assert "不可判" in r["reason"] and "s21_lin_band_max" in r["reason"]

    def test_mean_above_unity_alone_does_not_pass_via_dilution(self):
        # mean 1.0296 即便配一个"看似温和"的带内 max，只要 max>1.02 仍 FAIL；
        # 上界取带内 max 而非 mean，正是为了不被带内健康点稀释
        r = ab.msl_cpw_benchmark_verdict(**{**CPW_ARCHIVE_M04,
                                            "s21_lin_band_max": 1.021})
        assert r["verdict"] == "FAIL" and r["passive_ok"] is False
