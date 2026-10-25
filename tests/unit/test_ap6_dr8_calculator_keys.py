"""快赢席 W2 键面收口定向门（2026-10-08）：AP-6 ITU 三键 + DR-8 CDR mask 键。

注册薄壳（calc_families/itu_link.py + cdr_mask.py）的键面回归钉；数值真值
锚在 core 层测试（test_itu_atmosphere / test_w4_c_p10_itu_p618 /
test_dr_stream_seat6），本文件钉的是**注册面可达性 + 官方印刷值双路径
一致性 + 跨键一致性 + JSON 契约**。

锚出处（#118：裁判=独立来源，非自证）：
- P.838-3 Table 5 印刷 (k,α) spot 值（官方 PDF 页索引 4-7，2026-10-08
  web 抓取留档 内部证据档）——
  与模块 Gauss 和式路径（Tables 1-4 系数）构成双路径对拍。
- CDR：JT(fc)=√2、高频平台→1、peaking 闭式（core 模块 docstring 内证，
  test_dr_stream_seat6 已钉 core 面，此处钉计算器面透传）。
"""

from __future__ import annotations

import json
import math
from typing import ClassVar

import pytest

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

# P.838-3 Table 5 印刷 spot 值（f_GHz, kH, αH, kV, αV）——4 位有效数字印刷
# 舍入界内与 Gauss 路径对拍（rtol 2e-3：舍入传播 ~5.6e-4，系数转录错=
# 百分级偏移，两量级裕度）
TABLE5_SPOTS = [
    (1.0, 0.0000259, 0.9691, 0.0000308, 0.8592),
    (10.0, 0.01217, 1.2571, 0.01129, 1.2156),
    (40.0, 0.4431, 0.8673, 0.4274, 0.8421),
]

NEW_KEYS = ("gaseous_attenuation", "rain_specific_attenuation",
            "rain_attenuation_r001", "cdr_jitter_mask")


class TestRegistrySurface:
    def test_new_keys_registered_not_experimental(self):
        names = set(CALCULATOR_REGISTRY.names())
        assert set(NEW_KEYS) <= names
        for k in NEW_KEYS:
            assert CALCULATOR_REGISTRY.get(k).experimental is False

    def test_describe_json_ready(self):
        rows = CALCULATOR_REGISTRY.describe(include_experimental=True)
        by = {r["name"]: r for r in rows}
        for k in NEW_KEYS:
            json.dumps(by[k], ensure_ascii=False, allow_nan=False)


class TestAp6RainDoublePath:
    """γ_R 双路径：官方 Table 5 印刷 (k,α) 直算 vs 模块 Gauss 和式路径。"""

    @pytest.mark.parametrize("f,kh,ah,kv,av", TABLE5_SPOTS)
    @pytest.mark.parametrize("pol,k_ref,a_ref", [
        ("h", "kh", "ah"), ("v", "kv", "av"),
    ])
    def test_gamma_matches_printed_coefficients(self, f, kh, ah, kv, av,
                                                pol, k_ref, a_ref):
        k = {"kh": kh, "kv": kv}[k_ref]
        a = {"ah": ah, "av": av}[a_ref]
        expected = k * 42.0 ** a  # R=42 mm/h 设计点（印刷系数直算）
        out = run_calculator("rain_specific_attenuation",
                             {"f_ghz": f, "rain_rate_mmh": 42.0, "pol": pol})
        assert out["ok"] is True, out
        gamma = out["result"]["gamma_rain_db_per_km"]
        assert gamma == pytest.approx(expected, rel=2e-3), (
            f"Gauss 路径 vs Table 5 印刷值漂移 @f={f}/{pol}")

    def test_zero_rain_zero_branch(self):
        out = run_calculator("rain_specific_attenuation",
                             {"f_ghz": 10.0, "rain_rate_mmh": 0.0})
        assert out["ok"] is True and out["result"]["gamma_rain_db_per_km"] == 0.0

    def test_chain_gamma_cross_key_consistency(self):
        """链内 γR 步（Step5）与 rain_specific_attenuation 键同源逐位一致。"""
        common = {"f_ghz": 12.0, "rain_rate_mmh": 30.0, "pol": "v"}
        chain = run_calculator("rain_attenuation_r001", {
            "f_ghz": 12.0, "r001_mmh": 30.0, "elevation_deg": 30.0,
            "h0_km": 3.0, "h_s_km": 0.1, "lat_deg": 40.0, "pol": "v"})
        assert chain["ok"] is True, chain
        direct = run_calculator("rain_specific_attenuation", common)
        assert chain["result"]["gamma_r_dbkm"] == pytest.approx(
            direct["result"]["gamma_rain_db_per_km"], rel=1e-12)

    def test_chain_zero_branches_via_calculator(self):
        z = run_calculator("rain_attenuation_r001", {
            "f_ghz": 12.0, "r001_mmh": 0.0, "elevation_deg": 30.0,
            "h0_km": 3.0, "h_s_km": 0.1, "lat_deg": 40.0})
        assert z["ok"] is True
        assert z["result"]["a001_db"] == 0.0
        assert "zero_reason" in z["result"]
        below = run_calculator("rain_attenuation_r001", {
            "f_ghz": 12.0, "r001_mmh": 30.0, "elevation_deg": 30.0,
            "h0_km": 0.5, "h_s_km": 1.0, "lat_deg": 40.0})
        assert below["ok"] is True
        assert below["result"]["a001_db"] == 0.0
        assert "zero_reason" in below["result"]

    def test_gas_plumbing_identity_and_json(self):
        from rfauto.core.itu_atmosphere import gamma_gasses_db_per_km

        args = {"f_hz": 12e9, "p_hpa": 1013.25, "t_k": 288.15,
                "rho_wv_g_m3": 7.5}
        out = run_calculator("gaseous_attenuation", args)
        assert out["ok"] is True
        assert out["result"]["gamma_db_per_km"] == gamma_gasses_db_per_km(
            12e9, 1013.25, 288.15, 7.5)
        # 12GHz 干+湿大气量级窗（<0.2 dB/km；真值锚在 core 层逐式测试）
        assert 0.0 < out["result"]["gamma_db_per_km"] < 0.2
        json.dumps(out, ensure_ascii=False, allow_nan=False)


class TestDr8CdrMaskKey:
    FREQ: ClassVar[list[float]] = [1e6, 1e7, 1e9]
    FC: ClassVar[float] = 1e7

    def test_first_order_anchors_via_calculator(self):
        out = run_calculator("cdr_jitter_mask",
                             {"freq_hz": self.FREQ, "fc_hz": self.FC})
        r = out["result"]
        assert r["order"] == "first" and r["peaking"] is None
        # JT(fc)=√2（锚字段 jt_fc_ui 与曲线内点双钉）
        assert r["jt_fc_ui"] == pytest.approx(math.sqrt(2.0), rel=1e-12)
        assert r["jt_ui"][1] == pytest.approx(math.sqrt(2.0), rel=1e-12)
        # 高频平台 →1（√(1+1e-4)−1≈5e-5）
        assert r["jt_ui"][2] == pytest.approx(1.0, abs=1e-4)
        # 低频十倍程 → √101（−20dB/dec 段）
        assert r["jt_ui"][0] == pytest.approx(math.sqrt(101.0), rel=1e-12)

    def test_second_order_peaking_and_plateau(self):
        out = run_calculator("cdr_jitter_mask", {
            "freq_hz": self.FREQ, "order": "second",
            "fn_hz": self.FC, "zeta": 0.3})
        r = out["result"]
        assert r["order"] == "second"
        # peaking 闭式 1/(2ζ√(1−ζ²))（ζ=0.3）
        assert r["peaking"] == pytest.approx(
            1.0 / (2.0 * 0.3 * math.sqrt(1.0 - 0.09)), rel=1e-12)
        # 高频 |1−H|→1 → JT→1（O(1/f) 收敛：100·fn 处偏差 ~1.0e-4）
        assert r["jt_ui"][2] == pytest.approx(1.0, abs=2e-4)

    def test_second_order_requires_fn_and_zeta(self):
        out = run_calculator("cdr_jitter_mask",
                             {"freq_hz": self.FREQ, "order": "second"})
        assert out["ok"] is False and out.get("error")

    def test_mask_margin_passthrough_and_verdict(self):
        """mask 点列落在 JT 网格频点上（插值恒等）：逐点 margin 手算可验。"""
        out = run_calculator("cdr_jitter_mask", {
            "freq_hz": self.FREQ, "fc_hz": self.FC,
            "mask": [[1e6, 10.0], [1e7, 2.0], [1e9, 1.001]]})
        r = out["result"]
        m = r["mask"]
        assert m["verdict"] == "fail"  # 1e6 点 JT=10.0499 > mask 10.0 → 负余量
        assert m["worst_margin_db"] == pytest.approx(
            20.0 * math.log10(10.0 / math.sqrt(101.0)), rel=1e-9)
        assert m["worst_freq_hz"] == 1e6
        assert m["jt_at_mask_ui"][1] == pytest.approx(math.sqrt(2.0), rel=1e-9)
        # 正余量点：mask=2 @fc 处 20log10(2/√2)=+3.01dB
        assert m["margins_db"][1] == pytest.approx(
            20.0 * math.log10(2.0 / math.sqrt(2.0)), rel=1e-9)
        json.dumps(out, ensure_ascii=False, allow_nan=False)

    def test_fewer_than_two_freqs_rejected(self):
        out = run_calculator("cdr_jitter_mask", {"freq_hz": [1e7],
                                                 "fc_hz": 1e7})
        assert out["ok"] is False and "freq_hz" in out.get("error", "")
