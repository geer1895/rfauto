"""ge6 pool1：mask→滤波器规格综合闭环单测（mask_min_order/mask_margin_report/
mask_filter_synthesize + core/mask_filter_synthesis 内核）。

锚值口径（#118 双路径纪律）：教科书闭式（Pozar §8.3 / Cameron ch.6 的
acosh 最小阶式）在测试内**独立重写**为 inline 函数，与模块输出逐位对拍；
矩阵频响裕量用既有注册键 chebyshev_refl_fn（多项式闭式，独立代码路径）
作第三方裁判；手算字面锚（N=5/N=6/N=8/N=25）抓系统性错。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY, chebyshev_refl_fn
from rfauto.core.mask_filter_synthesis import (
    MaskSegment,
    MaskSpec,
    channel_fbw,
    chebyshev_min_order,
    get_mask_template,
    mask_margin_report,
    mask_template_names,
    min_order_for_mask,
    offset_to_omega,
    omega_to_offset,
    synthesize_from_mask,
)
from rfauto.service.calculator_service import run_calculator

# ─── 夹具 ────────────────────────────────────────────────────────────────────
# 合成双段遮罩：f0=2 GHz/通道 100 MHz/RL 20 dB；段 1（40 dB@偏移 150 MHz，
# Ω=2.931）与段 2（60 dB@300 MHz，Ω=5.678）闭式逐段阶均 5 → 最小阶 5
# （手算：acosh(√(9999·99))/acosh(2.93109)=7.59533/1.73809=4.370→5；
#  acosh(√(999999·99))/acosh(5.678)=9.89755/2.41418=4.100→5）
_MASK = {
    "name": "synthetic_dual", "source": "synthetic",
    "f0_ghz": 2.0, "channel_bw_ghz": 0.1, "ref_power_dbm": 20.0,
    "segments": [
        {"offset_low_ghz": 0.15, "offset_high_ghz": 0.3, "limit_dbc": -40.0},
        {"offset_low_ghz": 0.3, "offset_high_ghz": None, "limit_dbc": -60.0},
    ],
    "axis": "center", "rl_db": 20.0, "guard_offset_ghz": 0.0,
    "mask_type": "sem_psd", "notes": "",
}


def _spec(d: dict) -> MaskSpec:
    return MaskSpec.from_dict(d)


def _inline_min_order(offset_ghz: float, f0_ghz: float, fbw: float,
                      atten_db: float, rl_db: float) -> int:
    """教科书 acosh 最小阶式（测试内独立重写；与内核同式不同代码路径）。"""
    x = offset_ghz / f0_ghz
    omega = ((1.0 + x) - 1.0 / (1.0 + x)) / fbw
    k = 10.0 ** (rl_db / 10.0) - 1.0
    arg = (10.0 ** (atten_db / 10.0) - 1.0) * k
    if arg <= 1.0:
        return 0
    return max(1, math.ceil(math.acosh(math.sqrt(arg)) / math.acosh(omega)))


# ─── 几何映射（Ω↔频偏）───────────────────────────────────────────────────────

def test_channel_fbw_exact_band_edge():
    """fbw 精确反解：Ω(±通道半宽)=±1 逐位成立（一阶捷径 fbw≈ch/f0 的
    二阶偏差 0.98→1 修正）。"""
    fbw = channel_fbw(2.0, 0.1)
    assert fbw == pytest.approx(0.025 * 2.025 / 1.025, rel=1e-15)
    assert offset_to_omega(2.0, fbw, 0.05) == pytest.approx(1.0, abs=1e-12)
    assert offset_to_omega(2.44, channel_fbw(2.44, 0.02), 0.01) == pytest.approx(
        1.0, abs=1e-12)


def test_offset_omega_roundtrip():
    """Ω↔频偏解析互逆（两式独立：映射 vs 二次方程正根）。"""
    fbw = channel_fbw(2.0, 0.1)
    for off in (0.06, 0.15, 0.3, 1.0):
        assert omega_to_offset(2.0, fbw, offset_to_omega(2.0, fbw, off)) == (
            pytest.approx(off, rel=1e-9))


# ─── 最小阶闭式（教科书值逐位）───────────────────────────────────────────────

def test_chebyshev_min_order_textbook_pins():
    """RL=20 dB 下 40 dB@Ω=2 → 6 阶、60 dB@Ω=2 → 8 阶（手算：
    acosh(√(9999·99))/acosh(2)=7.59533/1.31696=5.767；9.89755/1.31696=7.515）。"""
    assert chebyshev_min_order(40.0, 20.0, 2.0) == 6
    assert chebyshev_min_order(60.0, 20.0, 2.0) == 8


def test_chebyshev_min_order_free_below_ripple():
    """要求衰减 ≤ 带内纹波（RL=20 → 0.0436 dB）时任何阶免费满足（0）。"""
    assert chebyshev_min_order(0.01, 20.0, 1.0) == 0
    assert chebyshev_min_order(0.01, 20.0, 2.0) == 0


def test_chebyshev_min_order_ceil_fp_tolerance():
    """ceil 带 1e-9 容差：n_raw 恰为整数时不多加一阶（fp 恰等纪律）。"""
    k = 10.0 ** (20.0 / 10.0) - 1.0
    omega_exact = math.cosh(math.acosh(math.sqrt((10.0 ** 4.0 - 1.0) * k)) / 4.0)
    assert chebyshev_min_order(40.0, 20.0, omega_exact) == 4


def test_chebyshev_min_order_band_edge_raises():
    """约束点在通带边缘且要求超纹波 → 显式 ValueError（不静默放宽）。"""
    with pytest.raises(ValueError, match="通带边缘"):
        chebyshev_min_order(20.0, 20.0, 1.0)


def test_min_order_dual_segment_literal_and_inline():
    """合成双段遮罩最小阶=5（手算字面锚）+ 教科书 inline 重写逐位对拍。"""
    m = _spec(_MASK)
    r = min_order_for_mask(m)
    assert r["order"] == 5
    assert r["ripple_db"] == pytest.approx(0.043648054, abs=1e-9)
    assert [s["segment_order"] for s in r["segments"]] == [5, 5]
    fbw = channel_fbw(2.0, 0.1)
    assert _inline_min_order(0.15, 2.0, fbw, 40.0, 20.0) == 5
    assert _inline_min_order(0.3, 2.0, fbw, 60.0, 20.0) == 5
    assert r["governing_segment"] == 1  # 段 2 Ω=5.678 更深为绑定段（裕量视角）
    assert r["segments"][0]["omega_norm"] == pytest.approx(2.931094, abs=1e-6)
    assert r["segments"][1]["omega_norm"] == pytest.approx(5.677939, abs=1e-6)


def test_min_order_matches_chebyshev_refl_fn_referee():
    """独立裁判：既有键 chebyshev_refl_fn 在段约束点 Ω 上复现"5 阶满足/
    4 阶不满足"（两路径同错的双保险）。"""
    m = _spec(_MASK)
    fbw = channel_fbw(2.0, 0.1)
    omega1 = offset_to_omega(2.0, fbw, 0.15)
    ok5 = chebyshev_refl_fn(n=5, rz_db=20.0, omega=[omega1])
    ok4 = chebyshev_refl_fn(n=4, rz_db=20.0, omega=[omega1])
    assert -20.0 * math.log10(ok5["s21_mag"][0]) >= 40.0
    assert -20.0 * math.log10(ok4["s21_mag"][0]) < 40.0
    assert min_order_for_mask(m)["order"] == 5


def test_min_order_service_path_and_margin_accounting():
    """service 通道 + required_margin_db 进闭式（+12 dB → 阶 6）。"""
    r = run_calculator("mask_min_order", {"mask": _MASK})
    assert r["ok"] and r["result"]["order"] == 5
    r2 = run_calculator("mask_min_order",
                        {"mask": _MASK, "required_margin_db": 12.0})
    assert r2["ok"] and r2["result"]["order"] == 6


# ─── 裕量报告（矩阵频响 × 第三方裁判）────────────────────────────────────────

def test_margin_report_order5_pass_and_referee():
    """5 阶报告：双段 PASS、最紧段=0；段衰减与 chebyshev_refl_fn 逐点一致
    （矩阵频响 vs 多项式闭式两路径）。"""
    m = _spec(_MASK)
    rep = mask_margin_report(m, 5)
    assert rep["pass"] is True
    assert rep["tightest_segment"] == 0
    fbw = channel_fbw(2.0, 0.1)
    for seg, off in zip(rep["segments"], (0.15, 0.3), strict=True):
        omega = offset_to_omega(2.0, fbw, off)
        ref = chebyshev_refl_fn(n=5, rz_db=20.0, omega=[omega])
        assert seg["achieved_atten_db"] == pytest.approx(
            -20.0 * math.log10(ref["s21_mag"][0]), abs=1e-4)
        assert seg["required_atten_db"] == pytest.approx(
            -_MASK["segments"][seg["segment_index"]]["limit_dbc"])
        assert seg["pass"] is True
    assert rep["segments"][0]["margin_db"] == pytest.approx(9.506283, abs=1e-5)
    assert rep["matrix_shape"] == [7, 7]
    assert rep["external_q"] == [1.0, 1.0]
    # 响应采样与耦合矩阵在档（回验产物可复算）
    assert len(rep["response_sample"]["offset_ghz"]) == 161
    assert len(rep["response_sample"]["atten_db"]) == 161


def test_margin_report_order4_fail():
    """4 阶（闭式下界之下）如实 FAIL：段 1 裕量为负。"""
    rep = mask_margin_report(_spec(_MASK), 4)
    assert rep["pass"] is False
    assert rep["segments"][0]["margin_db"] < 0.0
    assert rep["tightest_segment"] == 0


def test_margin_report_edge_adjacent_honest_fail():
    """贴滤波器责任起点段（Ω=1）如实按纹波电平判 FAIL（不 raise 不放宽）：
    DSSS 阶梯形态 guard=0、9 阶——贴边段衰减=纹波 0.0436 dB。"""
    edge = {**_MASK, "f0_ghz": 2.44, "channel_bw_ghz": 0.022,
            "segments": [
                {"offset_low_ghz": 0.011, "offset_high_ghz": 0.020,
                 "limit_dbc": -30.0},
                {"offset_low_ghz": 0.020, "offset_high_ghz": None,
                 "limit_dbc": -50.0}]}
    rep = mask_margin_report(_spec(edge), 9)
    assert rep["pass"] is False
    first = rep["segments"][0]
    assert first["at_duty_start"] is True
    assert first["achieved_atten_db"] == pytest.approx(0.043648, abs=1e-4)
    assert first["margin_db"] == pytest.approx(-29.956352, abs=1e-3)
    assert first["pass"] is False
    assert rep["segments"][1]["pass"] is True


# ─── 闭环（自动 +1 轨迹）────────────────────────────────────────────────────

def test_synthesize_first_try_pass_and_payload():
    """闭式阶首试即过（闭式已含裕量会计）：载荷含耦合矩阵/裕量/闭式明细。"""
    out = synthesize_from_mask(_spec(_MASK))
    assert out["ok"] is True and out["pass"] is True
    assert out["order"] == 5
    assert out["min_order_closed_form"] == 5
    assert out["start_order"] == 5
    assert len(out["trajectory"]) == 1 and out["trajectory"][0]["pass"] is True
    assert out["margin_report"]["min_margin_db"] == pytest.approx(
        9.506283, abs=1e-5)
    assert out["matrix_shape"] == [7, 7]
    json.dumps(out, allow_nan=False)  # JSON 进出契约


def test_synthesize_trajectory_from_order1_recovers_closed_form():
    """从 1 阶起步自动 +1：轨迹恰在闭式最小阶 5 处首次转绿（1..4 全 FAIL）
    ——闭环发现阶=闭式阶（双路径回收）。"""
    out = synthesize_from_mask(_spec(_MASK), min_order_override=1,
                               max_order_extra=4)
    assert [t["order"] for t in out["trajectory"]] == [1, 2, 3, 4, 5]
    assert [t["pass"] for t in out["trajectory"]] == [
        False, False, False, False, True]
    assert out["order"] == 5 and out["ok"] is True


def test_synthesize_cap_exhausted_honest_fail():
    """次数上限内无解 → ok=False + 轨迹如实（order=None，不假绿）。"""
    out = synthesize_from_mask(_spec(_MASK), min_order_override=1,
                               max_order_extra=3)
    assert out["ok"] is False and out["pass"] is False
    assert out["order"] is None
    assert [t["order"] for t in out["trajectory"]] == [1, 2, 3, 4]
    assert all(not t["pass"] for t in out["trajectory"])


def test_synthesize_required_margin_bumps_order():
    """设计裕量要求进闭式：+12 dB → 6 阶首试即过（段 1 裕量≥12）。"""
    out = synthesize_from_mask(_spec(_MASK), required_margin_db=12.0)
    assert out["order"] == 6 and out["min_order_closed_form"] == 6
    assert out["pass"] is True and len(out["trajectory"]) == 1
    assert all(s["margin_db"] >= 12.0 - 1e-9
               for s in out["margin_report"]["segments"])


def test_synthesize_guard_recovery_on_template():
    """ACLR 型模板 guard=0 闭式拒绝 → guard=10 MHz 后闭环 1..5 轨迹转绿。"""
    aclr = get_mask_template("nr_aclr_20mhz_envelope")
    with pytest.raises(ValueError, match="通带边缘"):
        synthesize_from_mask(aclr)
    guarded = MaskSpec.from_dict(
        {**aclr.to_dict(), "guard_offset_ghz": 0.010})
    out = synthesize_from_mask(guarded, min_order_override=1,
                               max_order_extra=6)
    assert [t["pass"] for t in out["trajectory"]] == [
        False, False, False, False, True]
    assert out["order"] == 5
    assert out["margin_report"]["min_margin_db"] > 0.0


# ─── 内置遮罩模板（公开规范限值事实钉）───────────────────────────────────────

def test_template_registry_names_and_sources():
    assert set(mask_template_names()) == {
        "fcc_15_247_dts_2g4", "ieee_80211_dsss_2g4", "nr_aclr_20mhz_envelope"}
    for name in mask_template_names():
        t = get_mask_template(name)
        assert t.source and t.notes
    with pytest.raises(KeyError, match="未知遮罩模板"):
        get_mask_template("no_such_mask")


def test_fcc_15_247_template_staircase_and_min_order():
    """FCC §15.247(c)(3) DTS 阶梯逐值钉（20/30/50 dB @ 0.24/1.5/2.5 MHz，
    channel_edge 轴）+ 最小阶字面锚 25（手算：acosh(99)/acosh(1.02395)
    =5.28827/0.21849=24.20→25；240 kHz 贴边过渡是规范物理）。"""
    t = get_mask_template("fcc_15_247_dts_2g4")
    assert [(s.offset_low_ghz, s.offset_high_ghz, s.limit_dbc)
            for s in t.segments] == [
        (0.00024, 0.0015, -20.0), (0.0015, 0.0025, -30.0),
        (0.0025, None, -50.0)]
    assert t.axis == "channel_edge" and "15.247" in t.source
    r = min_order_for_mask(t)
    assert r["order"] == 25
    assert [s["segment_order"] for s in r["segments"]] == [25, 12, 13]
    f0, ch, rl = t.f0_ghz, t.channel_bw_ghz, t.rl_db
    fbw = channel_fbw(f0, ch)
    half = ch / 2.0
    assert _inline_min_order(half + 0.00024, f0, fbw, 20.0, rl) == 25
    assert _inline_min_order(half + 0.0015, f0, fbw, 30.0, rl) == 12
    assert _inline_min_order(half + 0.0025, f0, fbw, 50.0, rl) == 13


def test_dsss_template_staircase_and_guard_paths():
    """IEEE 802.11 DSSS 阶梯逐值钉（30/50/70 dBr @ 11/20/30 MHz，center 轴）；
    首段贴通带边缘（11 MHz=22 MHz 半宽）：guard=0 闭式显式拒绝，
    guard=1 MHz → 阶 16（inline 对拍）。"""
    t = get_mask_template("ieee_80211_dsss_2g4")
    assert [(s.offset_low_ghz, s.offset_high_ghz, s.limit_dbc)
            for s in t.segments] == [
        (0.011, 0.020, -30.0), (0.020, 0.030, -50.0), (0.030, None, -70.0)]
    assert t.axis == "center" and "802.11" in t.source
    with pytest.raises(ValueError, match="通带边缘"):
        min_order_for_mask(t)
    guarded = MaskSpec.from_dict({**t.to_dict(), "guard_offset_ghz": 0.001})
    r = min_order_for_mask(guarded)
    assert r["order"] == 16
    fbw = channel_fbw(t.f0_ghz, t.channel_bw_ghz)
    assert _inline_min_order(0.011 + 0.001, t.f0_ghz, fbw, 30.0, t.rl_db) == 16
    assert _inline_min_order(0.020 + 0.001, t.f0_ghz, fbw, 50.0, t.rl_db) <= 16


def test_nr_aclr_template_staircase_and_envelope_semantics():
    """3GPP NR ACLR 型模板（30/33 dBc @ 邻道/次邻道，channel_edge 轴）：
    积分语义的点态包络预检形态（mask_type=aclr_envelope）；guard=0 拒绝、
    guard=10 MHz → 阶 5（inline 对拍：4.90→5）。"""
    t = get_mask_template("nr_aclr_20mhz_envelope")
    assert [(s.offset_low_ghz, s.offset_high_ghz, s.limit_dbc)
            for s in t.segments] == [
        (0.0, 0.020, -30.0), (0.020, 0.040, -33.0)]
    assert t.axis == "channel_edge" and t.mask_type == "aclr_envelope"
    assert "38.101-1" in t.source and "积分" in t.notes
    with pytest.raises(ValueError, match="通带边缘"):
        min_order_for_mask(t)
    guarded = MaskSpec.from_dict({**t.to_dict(), "guard_offset_ghz": 0.010})
    r = min_order_for_mask(guarded)
    assert r["order"] == 5
    fbw = channel_fbw(t.f0_ghz, t.channel_bw_ghz)
    half = t.channel_bw_ghz / 2.0
    assert _inline_min_order(half + 0.010, t.f0_ghz, fbw, 30.0, t.rl_db) == 5
    assert _inline_min_order(half + 0.030, t.f0_ghz, fbw, 33.0, t.rl_db) == 4


# ─── 注册面/数据模型消费者（#231）────────────────────────────────────────────

def test_registry_keys_and_describe():
    names = CALCULATOR_REGISTRY.names()
    assert {"mask_min_order", "mask_margin_report",
            "mask_filter_synthesize"} <= set(names)
    for key in ("mask_min_order", "mask_margin_report",
                "mask_filter_synthesize"):
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.description and not spec.experimental
        described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
        assert {p["name"] for p in described[key]["params"]} >= set(
            spec.required)


def test_service_round_trips_and_error_semantics():
    r = run_calculator("mask_filter_synthesize", {"mask": _MASK})
    assert r["ok"] and r["result"]["order"] == 5
    r2 = run_calculator("mask_min_order", {"mask": _MASK, "bogus_kw": 1})
    assert r2["ok"] is False and r2.get("error")
    r3 = run_calculator("mask_margin_report", {"mask": _MASK})
    assert r3["ok"] is False and "缺少必需参数" in r3["error"]


def test_maskspec_roundtrip_and_validation():
    m = _spec(_MASK)
    assert MaskSpec.from_dict(m.to_dict()) == m  # JSON 往返逐字段相等
    with pytest.raises(ValueError, match="未知键"):
        MaskSpec.from_dict({**_MASK, "nope": 1})
    with pytest.raises(ValueError, match="重叠"):
        MaskSpec.from_dict({**_MASK, "segments": [
            {"offset_low_ghz": 0.1, "offset_high_ghz": 0.3,
             "limit_dbc": -40.0},
            {"offset_low_ghz": 0.2, "offset_high_ghz": None,
             "limit_dbc": -50.0}]})
    with pytest.raises(ValueError, match="limit_dbc"):
        MaskSpec.from_dict({**_MASK, "segments": [
            {"offset_low_ghz": 0.1, "offset_high_ghz": None,
             "limit_dbc": 40.0}]})
    # 单段遮罩（zip 配对边界）合法
    single = MaskSpec.from_dict({**_MASK, "segments": [
        {"offset_low_ghz": 0.15, "offset_high_ghz": None, "limit_dbc": -40.0}]})
    assert len(single.segments) == 1
    assert min_order_for_mask(single)["order"] == 5
    seg = MaskSegment(0.1, 0.2, -40.0)
    assert seg.to_dict() == {"offset_low_ghz": 0.1, "offset_high_ghz": 0.2,
                             "limit_dbc": -40.0}
