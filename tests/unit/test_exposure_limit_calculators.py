"""ge6 pool3 RF 暴露限值表单测（exposure_mpe_limit / exposure_compliance_distance）。

锚值口径（#118 双路径纪律；表值 2026-09-30 逐位回原文核对——
FCC=eCFR 47 CFR §1.1310(e)(1) Table 1 当前版实测，ICNIRP=官方 PDF
Table 5 General public 逐位抄录；出处注记见 core/exposure_limits.py）：
- FCC 公众段字面锚：614/1.63@1 MHz、824/f·2.19/f@10 MHz（82.4/0.219）、
  27.5/0.073/2.0@100 MHz、f/1500@915 MHz=6.1、10@2.4 GHz；
- FCC 职业段：61.4/0.163/1.0·10@100 MHz、9000/f²@10 MHz=90 W/m²、50@2.4 GHz；
- ICNIRP 2020 公众：27.7/0.073/2@100 MHz、300/f^0.7@10 MHz、
  1.375√f·0.0037√f·f/200@1 GHz、10 W/m²@2.45 GHz（>2–300 GHz 段）；
- 段界连续性（表内恒等式）：ICNIRP 400 MHz S=400/200=2（与下段常量
  逐位同值）、2000 MHz S=2000/200=10（与上段常量逐位同值）；
- 距离锚：100 W EIRP@2.4 GHz（FCC 公众 S=10 W/m²）→
  R=√(100/(40π))=0.892062... m（手算互证）；同几何 E=√(30·EIRP)/R
  与 E=√(S·η0)、η0=4π·30 恒等（双路径）。
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

_ETA0 = 376.730313668  # Ω（=4π·30 恒等由测试本身复核）


# ─── 注册面（接口先行）───────────────────────────────────────────────────────

def test_exposure_keys_registered_and_described():
    names = CALCULATOR_REGISTRY.names()
    keys = {"exposure_mpe_limit", "exposure_compliance_distance"}
    assert keys <= set(names)
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    for key in keys:
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.description and not spec.experimental
        assert {p["name"] for p in described[key]["params"]} >= set(spec.required)


def test_eta0_identity_4pi30():
    """η0 与 4π·30：√(μ0/ε0)=376.7303 vs 4π·30=376.9911——远场 E 公式的
    "30" 是 η0/(4π)=29.9792 的取整口径（OET-65 惯用式），偏差 0.069%。"""
    assert pytest.approx(4.0 * math.pi * 30.0, rel=1e-3) == _ETA0
    assert pytest.approx(29.979246, rel=1e-3) == 30.0  # 取整口径如实标注


# ─── FCC Table 1：三段字面钉（公众/职业）─────────────────────────────────────

@pytest.mark.parametrize("freq_hz,field,expected", [
    (1.0e6, "e_v_per_m", 614.0),          # 0.3–1.34 MHz 段常量
    (1.0e6, "h_a_per_m", 1.63),
    (1.0e6, "s_w_per_m2", 1000.0),        # (100) mW/cm²→1 W/... ×10
    (10.0e6, "e_v_per_m", 82.4),          # 824/f
    (10.0e6, "h_a_per_m", 0.219),         # 2.19/f
    (10.0e6, "s_w_per_m2", 18.0),         # 180/f²=1.8 mW/cm²→18 W/m²
    (100.0e6, "e_v_per_m", 27.5),         # 30–300 段常量
    (100.0e6, "h_a_per_m", 0.073),
    (100.0e6, "s_w_per_m2", 2.0),
    (915.0e6, "s_w_per_m2", 6.1),         # f/1500（300–1500 段公式）
    (2400.0e6, "s_w_per_m2", 10.0),       # ≥1500 段常量
])
def test_fcc_general_population_table_values(freq_hz, field, expected):
    out = run_calculator("exposure_mpe_limit",
                         {"freq_hz": freq_hz, "standard": "fcc_general"})
    assert out["ok"]
    # 输出 round 9 位 → rel 1e-9 容差
    assert out["result"][field] == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize("freq_hz,field,expected", [
    (100.0e6, "e_v_per_m", 61.4),         # 职业 30–300 段
    (100.0e6, "h_a_per_m", 0.163),
    (100.0e6, "s_w_per_m2", 10.0),
    (10.0e6, "s_w_per_m2", 90.0),         # 900/f² mW/cm²→90 W/m²
    (2400.0e6, "s_w_per_m2", 50.0),       # ≥1500 段常量 5 mW/cm²
    (1.0e6, "e_v_per_m", 614.0),          # 0.3–3 段常量
])
def test_fcc_occupational_table_values(freq_hz, field, expected):
    out = run_calculator("exposure_mpe_limit",
                         {"freq_hz": freq_hz, "standard": "fcc_occupational"})
    assert out["ok"]
    assert out["result"][field] == pytest.approx(expected, rel=1e-9)


def test_fcc_band_edges_and_averaging_times():
    """段界行为：1.34 MHz 落 [1.34,30) 段公式 824/f=614.93（与表印常量
    614 在取整内一致）；平均时间 6 vs 30 min。"""
    edge = run_calculator("exposure_mpe_limit",
                          {"freq_hz": 1.34e6,
                           "standard": "fcc_general"})["result"]
    assert edge["e_v_per_m"] == pytest.approx(824.0 / 1.34, rel=1e-9)
    # 表印常量 614 与公式值 614.93 取整一致（<0.16%）
    assert edge["e_v_per_m"] == pytest.approx(614.0, rel=2e-3)
    assert edge["averaging_time_min"] == 30.0
    below = run_calculator("exposure_mpe_limit",
                           {"freq_hz": 1.3399e6,
                            "standard": "fcc_general"})["result"]
    assert below["e_v_per_m"] == pytest.approx(614.0, rel=1e-9)  # 下段常量
    occ = run_calculator("exposure_mpe_limit",
                         {"freq_hz": 100e6,
                          "standard": "fcc_occupational"})["result"]
    assert occ["averaging_time_min"] == 6.0


# ─── ICNIRP 2020 Table 5 公众段：字面钉 + 段界恒等 ───────────────────────────

@pytest.mark.parametrize("freq_hz,field,expected", [
    (100.0e6, "e_v_per_m", 27.7),          # >30–400 段常量
    (100.0e6, "h_a_per_m", 0.073),
    (100.0e6, "s_w_per_m2", 2.0),
    (10.0e6, "e_v_per_m", 300.0 / 10 ** 0.7),   # 0.1–30 段公式
    (10.0e6, "h_a_per_m", 2.2 / 10.0),
    (1000.0e6, "e_v_per_m", 1.375 * math.sqrt(1000.0)),   # >400–2000 段
    (1000.0e6, "h_a_per_m", 0.0037 * math.sqrt(1000.0)),
    (1000.0e6, "s_w_per_m2", 1000.0 / 200.0),
    (2450.0e6, "s_w_per_m2", 10.0),        # >2–300 GHz 段常量
])
def test_icnirp_public_table_values(freq_hz, field, expected):
    out = run_calculator("exposure_mpe_limit",
                         {"freq_hz": freq_hz, "standard": "icnirp_public"})
    assert out["ok"]
    # 输出 round 9 位：小值（0.1 量级）用 abs 兜底，大值 rel 1e-9
    assert out["result"][field] == pytest.approx(expected, rel=1e-9, abs=5e-10)


def test_icnirp_band_edge_continuity_exact():
    """表内连续性恒等式：f=400 MHz 落 >400 段？否——[400,2000) 段公式
    f/200 在 400 处恰=2.0（与 >30–400 段常量逐位同值）；f=2000 MHz 落
    末段闭端常量 10=2000/200——表构造自证（公式段界与常量逐位闭合）。"""
    at400 = run_calculator("exposure_mpe_limit",
                           {"freq_hz": 400.0e6,
                            "standard": "icnirp_public"})["result"]
    assert at400["s_w_per_m2"] == pytest.approx(2.0, rel=1e-12)
    assert 400.0 / 200.0 == 2.0  # 公式段上界值=下段常量（逐位恒等）
    at2g = run_calculator("exposure_mpe_limit",
                          {"freq_hz": 2000.0e6,
                           "standard": "icnirp_public"})["result"]
    assert at2g["s_w_per_m2"] == pytest.approx(10.0, rel=1e-12)  # 末段闭端
    assert 2000.0 / 200.0 == 10.0  # 公式段上界值=上段常量（逐位恒等）


# ─── 合规距离：手算锚 + 双路径恒等 ───────────────────────────────────────────

def test_distance_literal_anchor_100w_2p4ghz():
    """100 W EIRP@2.4 GHz（FCC 公众 10 W/m²）→ R=√(100/(40π)) 手算锚。"""
    out = run_calculator("exposure_compliance_distance",
                         {"eirp_w": 100.0, "freq_hz": 2.4e9,
                          "standard": "fcc_general"})["result"]
    expected = math.sqrt(100.0 / (4.0 * math.pi * 10.0))
    assert out["distance_m"] == pytest.approx(expected, rel=1e-9)
    assert out["distance_m"] == pytest.approx(0.8920620580763856, rel=1e-9)
    assert out["s_limit_w_per_m2"] == 10.0


def test_distance_dual_path_e_identity():
    """双路径：E=√(30·EIRP)/R 与 E=√(S·η0)——"30"=η0/(4π)=29.9792 的
    取整口径 → 两路径一致在 0.1% 内（近似容差，非逐位恒等）。"""
    out = run_calculator("exposure_compliance_distance",
                         {"eirp_w": 100.0, "freq_hz": 2.4e9,
                          "standard": "fcc_general"})["result"]
    path_a = math.sqrt(30.0 * 100.0) / out["distance_m"]
    path_b = math.sqrt(out["s_limit_w_per_m2"] * _ETA0)
    assert path_a == pytest.approx(path_b, rel=1e-3)
    assert out["e_at_limit_v_per_m"] == pytest.approx(path_a, rel=1e-9)


def test_distance_scales_with_eirp_square_root():
    out1 = run_calculator("exposure_compliance_distance",
                          {"eirp_w": 10.0, "freq_hz": 2.4e9})["result"]
    out2 = run_calculator("exposure_compliance_distance",
                          {"eirp_w": 100.0, "freq_hz": 2.4e9})["result"]
    assert out2["distance_m"] / out1["distance_m"] == pytest.approx(
        math.sqrt(10.0), rel=1e-9)


def test_distance_plane_wave_equiv_band_flagged():
    """FCC <300 MHz 段 S 列=平面波等效口径 → 标志位如实 True。"""
    out = run_calculator("exposure_compliance_distance",
                         {"eirp_w": 100.0, "freq_hz": 100e6})["result"]
    assert out["plane_wave_equiv_basis"] is True
    assert out["s_limit_w_per_m2"] == pytest.approx(2.0, rel=1e-12)
    high = run_calculator("exposure_compliance_distance",
                          {"eirp_w": 100.0, "freq_hz": 2.4e9})["result"]
    assert high["plane_wave_equiv_basis"] is False


# ─── 域守卫与入参契约 ────────────────────────────────────────────────────────

def test_domain_and_contract_errors_are_explicit():
    out = run_calculator("exposure_mpe_limit", {"freq_hz": 2e5})
    assert not out["ok"] and "定义域" in out["error"]  # 0.2 MHz < 0.3 MHz
    out = run_calculator("exposure_mpe_limit", {"freq_hz": 4e11})
    assert not out["ok"] and "定义域" in out["error"]  # 400 GHz > 300 GHz
    out = run_calculator("exposure_mpe_limit",
                         {"freq_hz": 2.4e9, "standard": "itu_xx"})
    assert not out["ok"] and out.get("error")
    out = run_calculator("exposure_compliance_distance",
                         {"eirp_w": 0.0, "freq_hz": 2.4e9})
    assert not out["ok"] and out.get("error")
    out = run_calculator("exposure_compliance_distance",
                         {"eirp_w": True, "freq_hz": 2.4e9})
    assert not out["ok"] and "bool" in out["error"]
    # ICNIRP 0.1–30 MHz：恒近场域 → 距离口径显式拒绝（不凑数）
    out = run_calculator("exposure_compliance_distance",
                         {"eirp_w": 100.0, "freq_hz": 10e6,
                          "standard": "icnirp_public"})
    assert not out["ok"] and "近场" in out["error"]
    # 缺必需参数 / 未知参数
    out = run_calculator("exposure_compliance_distance", {"freq_hz": 2.4e9})
    assert not out["ok"] and "缺少必需参数" in out["error"]
    out = run_calculator("exposure_mpe_limit",
                         {"freq_hz": 2.4e9, "bogus_k": 1})
    assert not out["ok"]


def test_service_results_json_serializable():
    for key, params in (
        ("exposure_mpe_limit", {"freq_hz": 2.4e9}),
        ("exposure_mpe_limit", {"freq_hz": 10e6, "standard": "icnirp_public"}),
        ("exposure_compliance_distance",
         {"eirp_w": 100.0, "freq_hz": 2.4e9}),
    ):
        out = run_calculator(key, params)
        assert out["ok"], (key, out)
        json.dumps(out, ensure_ascii=False, allow_nan=False)
