"""ge6 pool3 chipless RFID 零点编码闭式单测（chipless_tag_plan/encode/decode）。

裁判口径（任务书指定）：编码→合成谱→解码 round-trip 零误码 + 谷深对 Q
的敏度钉。锚值口径（#118 双路径纪律）：
- 谷深闭式 |S21_min|=2R/(2R+Z0)（R=x/Q）在 f0 处与精确复数响应逐位一致
  （f0 处电抗恒为零——恒等式级锚）；
- 字面锚 x=1e4 Ω/Q=2000/Z0=50：R=5 Ω → −15.563025007672874 dB；
- 槽格 [2,3] GHz/8 槽中心=2062.5+125k MHz。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_X_SLOPE = 10000.0  # Ω（电抗斜率；FWHM=f0·Z0/(2x)≈5 MHz@2.06 GHz）
_Q = 2000.0
_CODE = [1, 0, 1, 0, 0, 0, 1, 0]
_BAND = (2.0e9, 3.0e9)


def _synth_spectrum(code: list[int], n_pts: int = 4001,
                    x: float = _X_SLOPE, q: float = _Q) -> tuple[list, list]:
    """编码→合成谱（级联闭式；隔离假设，core/chipless_rfid.docstring）。"""
    from rfauto.core.chipless_rfid import bank_s21_mag, plan_resonator_bank

    plan = plan_resonator_bank(code, _BAND[0], _BAND[1], q, x)
    freqs = [_BAND[0] + i * (_BAND[1] - _BAND[0]) / (n_pts - 1)
             for i in range(n_pts)]
    res = [r["freq_hz"] for r in plan["resonators"]]
    s21 = [20.0 * math.log10(max(bank_s21_mag(f, res, q, x), 1e-300))
           for f in freqs]
    return freqs, s21


# ─── 注册面（接口先行）───────────────────────────────────────────────────────

def test_chipless_keys_registered_and_described():
    names = CALCULATOR_REGISTRY.names()
    keys = {"chipless_tag_plan", "chipless_tag_encode", "chipless_tag_decode"}
    assert keys <= set(names)
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    for key in keys:
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.description and not spec.experimental
        assert {p["name"] for p in described[key]["params"]} >= set(spec.required)


# ─── 谷深闭式：精确复数式 vs 2R/(2R+Z0) 恒等 + 字面锚 + Q 敏度 ────────────────

def test_notch_depth_closed_form_identity_and_literal_anchor():
    """f0 处电抗恒为零 → 精确式=闭式（恒等式级锚）；字面 −15.563025 dB。"""
    out = run_calculator("chipless_tag_plan", {
        "code": _CODE, "f_start_hz": _BAND[0], "f_stop_hz": _BAND[1],
        "q_unloaded": _Q, "slope_ohm": _X_SLOPE})["result"]
    r_ohm = _X_SLOPE / _Q
    assert out["notch_depth_db_common"] == pytest.approx(
        20.0 * math.log10(2.0 * r_ohm / (2.0 * r_ohm + 50.0)), rel=1e-9)
    # 字面锚（输出 round 9 位 → rel 1e-9 容差）
    assert out["notch_depth_db_common"] == pytest.approx(
        -15.563025007672874, rel=1e-9)
    # 精确复数响应在 f0 处逐位同值（20log10(|S21(f0)|)）
    from rfauto.core.chipless_rfid import bank_s21_mag

    f0 = out["resonators"][0]["freq_hz"]
    exact = 20.0 * math.log10(bank_s21_mag(f0, [f0], _Q, _X_SLOPE))
    assert exact == pytest.approx(out["notch_depth_db_common"], rel=1e-9)


def test_depth_monotone_in_q_and_in_r():
    """谷深对 Q 敏度钉：Q↑（R=x/Q↓）→ 谷深单调变深；R→0 极限=完美零点。"""
    depths = []
    for q in (200.0, 500.0, 1000.0, 2000.0, 5000.0):
        out = run_calculator("chipless_tag_plan", {
            "code": [1, 0], "f_start_hz": 2.0e9, "f_stop_hz": 2.4e9,
            "q_unloaded": q, "slope_ohm": _X_SLOPE})["result"]
        depths.append(out["notch_depth_db_common"])
    assert all(depths[i] > depths[i + 1] for i in range(len(depths) - 1)), (
        depths)  # 深谷单调加深（dB 值单调下降）
    q_inf = 20.0 * math.log10(2.0 * (_X_SLOPE / 1e7)
                              / (2.0 * (_X_SLOPE / 1e7) + 50.0))
    assert q_inf < depths[-1]  # R→0 更深（未达极限）


# ─── round-trip 裁判：编码→合成谱→解码零误码（含噪声鲁棒）────────────────────

def test_roundtrip_encode_plan_decode_zero_bit_error():
    """裁判钉：码字→规划→级联合成谱→解码逐位复原（汉明 0）。"""
    from rfauto.core.chipless_rfid import decode_from_spectrum, encode_tag_code

    freqs, s21 = _synth_spectrum(_CODE)
    dec = decode_from_spectrum(freqs, s21, _BAND[0], _BAND[1], len(_CODE))
    assert dec["code"] == _CODE
    assert dec["n_unresolved_slots"] == 0
    # 反向编码闭合：解码出的谷频（槽中心）回 encode 逐位复原
    plan = run_calculator("chipless_tag_plan", {
        "code": _CODE, "f_start_hz": _BAND[0], "f_stop_hz": _BAND[1],
        "q_unloaded": _Q, "slope_ohm": _X_SLOPE})["result"]
    enc = encode_tag_code([r["freq_hz"] for r in plan["resonators"]],
                          _BAND[0], _BAND[1], len(_CODE))
    assert enc["code"] == _CODE


def test_roundtrip_robust_to_noise():
    """±0.5 dB 谱噪声下零误码（谷深 −15.6 dB ≫ 门限 3 dB+噪声）。"""
    import random

    from rfauto.core.chipless_rfid import decode_from_spectrum

    freqs, s21 = _synth_spectrum(_CODE)
    rng = random.Random(7)
    noisy = [v + rng.uniform(-0.5, 0.5) for v in s21]
    dec = decode_from_spectrum(freqs, noisy, _BAND[0], _BAND[1], len(_CODE))
    assert dec["code"] == _CODE


def test_decode_codebook_hamming_report():
    """给码本：真码在册 → 匹配+汉明 0；真码不在册 → 最近合法码字与
    汉明距离如实报告（_CODE 有 3 个 1 → 距全零码汉明 3）。"""
    from rfauto.core.chipless_rfid import decode_from_spectrum

    freqs, s21 = _synth_spectrum(_CODE)
    book_with_truth = [_CODE, [0] * len(_CODE)]
    dec0 = decode_from_spectrum(freqs, s21, _BAND[0], _BAND[1], len(_CODE),
                                codebook=book_with_truth)
    assert dec0["matched_codebook_code"] == _CODE
    assert dec0["hamming_distance"] == 0
    book_without_truth = [[0] * len(_CODE), [1] * len(_CODE)]
    dec3 = decode_from_spectrum(freqs, s21, _BAND[0], _BAND[1], len(_CODE),
                                codebook=book_without_truth)
    assert dec3["matched_codebook_code"] == [0] * len(_CODE)
    assert dec3["hamming_distance"] == 3


# ─── 槽格与编码容差 ──────────────────────────────────────────────────────────

def test_slot_grid_centers_and_encode_tolerance():
    from rfauto.core.chipless_rfid import encode_tag_code, slot_grid

    grid = slot_grid(2.0e9, 3.0e9, 8)
    assert grid[0] == pytest.approx(2062.5e6, rel=1e-12)
    assert grid[2] == pytest.approx(2312.5e6, rel=1e-12)
    # 恰落槽中心合法；偏 0.4×槽距=50 MHz 恰等容差内合法
    enc = encode_tag_code([grid[3] + 49.9e6], 2.0e9, 3.0e9, 8)
    assert enc["code"][3] == 1
    # 偏 0.5×槽距（落两槽正中）超 0.4 容差 → 显式拒绝
    with pytest.raises(ValueError, match="超容差"):
        encode_tag_code([grid[3] + 62.5e6], 2.0e9, 3.0e9, 8)


def test_encode_conflict_and_band_rejects_are_explicit():
    from rfauto.core.chipless_rfid import encode_tag_code, slot_grid

    grid = slot_grid(2.0e9, 3.0e9, 8)
    with pytest.raises(ValueError, match="同一槽位"):
        encode_tag_code([grid[2], grid[2] + 1.0e6], 2.0e9, 3.0e9, 8)
    with pytest.raises(ValueError, match="扫描带外"):
        encode_tag_code([1.5e9], 2.0e9, 3.0e9, 8)


def test_decode_unresolved_slots_reported_honestly():
    """稀疏谱：部分槽窗内采样 <2 → 如实 unresolved 不猜码（#314 同源）。"""
    from rfauto.core.chipless_rfid import decode_from_spectrum

    freqs = [2.0e9, 2.1e9, 2.2e9, 2.3e9, 2.4e9, 2.5e9, 2.6e9, 2.7e9,
             2.8e9, 2.9e9, 3.0e9]
    s21 = [0.0] * len(freqs)
    dec = decode_from_spectrum(freqs, s21, 2.0e9, 3.0e9, 8)
    assert dec["n_unresolved_slots"] == 8
    assert dec["code"] == [0] * 8


def test_plan_rejects_notch_bw_ge_slot_spacing():
    """A-06：陷波带宽≳槽距域全槽误判——规划面显式 ValueError 带参数回显
    （band 2.0–2.4 GHz/2 槽 df=200 MHz，x=250 → bw=f0·Z0/(2x)=210 MHz
    ≥ 槽距；x=300 → 175 MHz 域内照常）。"""
    from rfauto.core.chipless_rfid import plan_resonator_bank

    with pytest.raises(ValueError, match=r"槽位 0.*陷波全宽.*槽距"):
        plan_resonator_bank([1, 0], 2.0e9, 2.4e9, 200.0, 250.0)
    ok = plan_resonator_bank([1, 0], 2.0e9, 2.4e9, 200.0, 300.0)
    assert ok["resonators"][0]["notch_bw_approx_hz"] == pytest.approx(
        2.1e9 * 50.0 / (2.0 * 300.0), rel=1e-6)  # 175 MHz < 200 MHz


def test_decode_all_ones_flagged_as_wide_notch_ambiguous():
    """A-06：全槽（无 unresolved）解码全 1 与'陷波带宽≳槽距'全域误判特征
    同象——谱面不可区分合法全 1 标签，降级注记不拒绝（all_slots_decode_one）；
    非全 1 解码不误标。"""
    from rfauto.core.chipless_rfid import decode_from_spectrum

    freqs, s21 = _synth_spectrum([1, 1, 1, 1])
    dec = decode_from_spectrum(freqs, s21, _BAND[0], _BAND[1], 4)
    assert dec["code"] == [1, 1, 1, 1]
    assert dec["all_slots_decode_one"] is True
    assert "带宽" in dec["note"] and "槽距" in dec["note"]
    freqs2, s212 = _synth_spectrum(_CODE)  # 含 0 槽的常规码
    dec2 = decode_from_spectrum(freqs2, s212, _BAND[0], _BAND[1],
                                len(_CODE))
    assert dec2["code"] == _CODE
    assert dec2["all_slots_decode_one"] is False


# ─── 域守卫与入参契约 ────────────────────────────────────────────────────────

def test_domain_and_contract_errors_are_explicit():
    base = {"code": _CODE, "f_start_hz": _BAND[0], "f_stop_hz": _BAND[1],
            "q_unloaded": _Q, "slope_ohm": _X_SLOPE}
    # 缺必需参数 / 未知参数
    out = run_calculator("chipless_tag_plan", {"code": _CODE})
    assert not out["ok"] and "缺少必需参数" in out["error"]
    out = run_calculator("chipless_tag_plan", {**base, "bogus_k": 1})
    assert not out["ok"]
    # 带倒置 / 槽数下界 / Q 下界 / 码字取值域
    for bad in ({**base, "f_start_hz": _BAND[1], "f_stop_hz": _BAND[0]},
                {**base, "q_unloaded": 0.5},
                {**base, "code": [1, 0, 2, *_CODE[3:]]}):
        out = run_calculator("chipless_tag_plan", bad)
        assert not out["ok"] and out.get("error")
    # 解码：f_stop<f_start / 阈值非正 / 长度不齐
    dec_base = {"freq_hz": [2e9, 2.1e9, 2.2e9, 2.3e9],
                "s21_db": [0.0, 0.0, 0.0, 0.0]}
    for bad in ({**dec_base, "f_start_hz": 3e9, "f_stop_hz": 2e9,
                 "n_slots": 8},
                {**dec_base, "f_start_hz": 2e9, "f_stop_hz": 3e9,
                 "n_slots": 8, "depth_threshold_db": 0.0},
                {**dec_base, "f_start_hz": 2e9, "f_stop_hz": 3e9,
                 "n_slots": 8, "s21_db": [0.0, 0.0]}):
        out = run_calculator("chipless_tag_decode", bad)
        assert not out["ok"] and out.get("error")
    # bool 拒收（df7+⑯）
    out = run_calculator("chipless_tag_plan", {**base, "q_unloaded": True})
    assert not out["ok"] and "bool" in out["error"]


def test_service_results_json_serializable():
    freqs, s21 = _synth_spectrum(_CODE, n_pts=801)
    for key, params in (
        ("chipless_tag_plan", {"code": _CODE, "f_start_hz": _BAND[0],
                               "f_stop_hz": _BAND[1], "q_unloaded": _Q,
                               "slope_ohm": _X_SLOPE}),
        ("chipless_tag_encode", {"resonance_freqs_hz": [2062.5e6, 2312.5e6],
                                 "f_start_hz": _BAND[0],
                                 "f_stop_hz": _BAND[1], "n_slots": 8}),
        ("chipless_tag_decode", {"freq_hz": freqs, "s21_db": s21,
                                 "f_start_hz": _BAND[0],
                                 "f_stop_hz": _BAND[1], "n_slots": 8}),
    ):
        out = run_calculator(key, params)
        assert out["ok"], (key, out)
        json.dumps(out, ensure_ascii=False, allow_nan=False)
