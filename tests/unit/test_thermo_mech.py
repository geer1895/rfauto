"""D14 stage-1 热-结构-电磁单向链单测（§10.3 D14 / §10.21）。

裁判口径（#118）：闭式锚来自教科书（Pozar 谐振温漂 / Balanis 贴片设计式），
单向链是几何重算；两者来源独立、不互相自证。所有用例确定性、无网络、无真机。
示例材料参数（CTE=14 ppm/K、TCDk=+50 ppm/K）仅用于验证链的自洽与数量级，
不构成厂商数据背书——真实材料参数应由调用方注入。
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import calculators
from rfauto.core import thermo_mech as tm

# 贴片示例几何（recipes/patch_antenna_v1.yaml 档位量级）
PATCH = {"patch_len_mm": 40.0, "patch_w_mm": 50.0, "h_mm": 0.508, "eps_r": 3.66}
# hairpin 折叠半波谐振器：展开总长 + 有效介电常数
HAIRPIN = {"line_len_mm": 30.0, "eps_eff": 2.5}
CTE = 14.0
TCDK = 50.0
REF_C = 25.0


# ─── 1. 等温一维热膨胀闭式 ───────────────────────────────────────────────────

def test_linear_thermal_expansion_closed_form():
    out = tm.scale_dimension(50.0, cte_ppm_per_k=17.0, delta_t_c=100.0)
    assert out["delta_mm"] == pytest.approx(50.0 * 17e-6 * 100.0, rel=1e-12)
    assert out["deformed_mm"] == pytest.approx(50.0 + 0.085, rel=1e-12)
    strain = tm.thermal_strain(17.0, 100.0)
    assert strain["strain"] == pytest.approx(17e-6 * 100.0, rel=1e-12)
    assert strain["cte_per_k"] == pytest.approx(17e-6, rel=1e-12)


# ─── 2. CTE=0 → 几何不变、漂移为零 ───────────────────────────────────────────

def test_zero_cte_no_geometry_change_and_zero_drift():
    geo = tm.update_template_geometry(
        {"patch_len_mm": 40.0, "patch_w_mm": 50.0},
        cte_ppm_per_k=0.0, delta_t_c=125.0)
    assert geo["deformed"] == geo["nominal"]
    assert geo["delta_mm"] == {"patch_len_mm": 0.0, "patch_w_mm": 0.0}
    chain = tm.thermo_mech_chain(
        "patch", delta_t_c=125.0, cte_ppm_per_k=0.0, tcdk_ppm_per_k=0.0, **PATCH)
    assert chain["oneway_df_over_f"] == 0.0
    assert chain["oneway_drift_ppm"] == 0.0
    assert chain["closed_form_df_over_f"] == 0.0
    assert chain["within_20pct"] is True


# ─── 3. 闭式实现与 calculators.resonator_thermal_drift 数值一致 ──────────────

@pytest.mark.parametrize("dt,cte,tcdk", [
    (-65.0, 14.0, 50.0),
    (60.0, 14.0, 50.0),
    (125.0, -8.0, -30.0),
    (0.0, 14.0, 50.0),
])
def test_closed_form_matches_calculators_resonator_thermal_drift(dt, cte, tcdk):
    mine = tm.closed_form_thermal_drift(2.4, dt, cte, tcdk)
    ref = calculators.resonator_thermal_drift(2.4, dt, cte, tcdk)
    assert mine["df_over_f"] == pytest.approx(ref["df_over_f"], abs=1e-15)
    assert mine["df_over_f_ppm"] == pytest.approx(ref["df_over_f_ppm"], abs=1e-9)
    assert mine["f_shifted_ghz"] == pytest.approx(ref["f_shifted_ghz"], abs=1e-12)
    assert mine["cte_term_ppm"] == pytest.approx(ref["cte_term_ppm"], abs=1e-9)
    assert mine["tcdk_term_ppm"] == pytest.approx(ref["tcdk_term_ppm"], abs=1e-9)


# ─── 4. 贴片几何反解与 calculators.patch_length 往返一致 ─────────────────────

@pytest.mark.parametrize("f0,er,h", [(2.4, 3.66, 0.508), (5.8, 2.2, 0.254), (10.0, 9.8, 0.635)])
def test_patch_resonance_inverts_calculators_patch_length(f0, er, h):
    design = calculators.patch_length(f0, er, h)
    back = tm.patch_resonance_ghz(design["patch_l_mm"], design["patch_w_mm"], h, er)
    assert back == pytest.approx(f0, rel=1e-3)


# ─── 5/6. patch/hairpin 单向链 vs 闭式 ≤20% 漂移量（−40~85℃）────────────────

def _sweep(model, geom):
    return {t: tm.thermo_mech_chain(
        model, delta_t_c=t - REF_C, cte_ppm_per_k=CTE, tcdk_ppm_per_k=TCDK, **geom)
        for t in (-40.0, 25.0, 85.0)}


def test_patch_oneway_chain_vs_closed_form_within_20pct_cold_to_hot():
    for t_c, chain in _sweep("patch", PATCH).items():
        assert chain["within_20pct"] is True, (t_c, chain["relative_deviation"])
        if t_c == REF_C:
            assert chain["oneway_drift_ppm"] == 0.0
        else:
            assert chain["relative_deviation"] is not None
            assert chain["relative_deviation"] <= 0.20
            assert abs(chain["oneway_drift_ppm"]) > 0.0


def test_hairpin_oneway_chain_vs_closed_form_within_20pct_cold_to_hot():
    for t_c, chain in _sweep("hairpin", HAIRPIN).items():
        assert chain["within_20pct"] is True, (t_c, chain["relative_deviation"])
        if t_c == REF_C:
            assert chain["oneway_drift_ppm"] == 0.0
        else:
            assert chain["relative_deviation"] is not None
            assert chain["relative_deviation"] <= 0.20


# ─── 7. 单向链输出可供重渲染的修改后模板几何参数（JSON）────────────────────

def test_chain_emits_modified_template_geometry_for_rerender():
    chain = tm.thermo_mech_chain(
        "patch", delta_t_c=100.0, cte_ppm_per_k=CTE, tcdk_ppm_per_k=TCDK, **PATCH)
    geo = chain["geometry"]
    assert set(geo["deformed"]) == {"patch_len_mm", "patch_w_mm"}
    assert geo["deformed"]["patch_len_mm"] > geo["nominal"]["patch_len_mm"]
    assert geo["deformed"]["patch_w_mm"] > geo["nominal"]["patch_w_mm"]
    assert geo["delta_mm"]["patch_len_mm"] == pytest.approx(40.0 * CTE * 1e-6 * 100.0, rel=1e-12)
    assert geo["delta_mm"]["patch_w_mm"] == pytest.approx(50.0 * CTE * 1e-6 * 100.0, rel=1e-12)
    # JSON 进出契约
    json.dumps(chain, ensure_ascii=False)


# ─── 8. 单调性/边界 ──────────────────────────────────────────────────────────

def test_drift_is_monotonic_in_temperature_and_cte():
    drifts = [tm.thermo_mech_chain(
        "patch", delta_t_c=t - REF_C, cte_ppm_per_k=CTE, tcdk_ppm_per_k=TCDK, **PATCH
    )["oneway_df_over_f"] for t in (-40.0, -10.0, 25.0, 55.0, 85.0)]
    assert all(a > b for a, b in itertools.pairwise(drifts))  # 升温单调降频
    lengths = [tm.scale_dimension(40.0, c, 100.0)["deformed_mm"]
               for c in (0.0, 10.0, 20.0, 40.0)]
    assert all(a < b for a, b in itertools.pairwise(lengths))  # 尺寸随 CTE 单调


def test_temperature_envelope_maps_to_delta_t():
    assert tm.delta_t_from_temperature(-40.0, REF_C) == pytest.approx(-65.0)
    assert tm.delta_t_from_temperature(85.0, REF_C) == pytest.approx(60.0)
    assert tm.delta_t_from_temperature(REF_C, REF_C) == 0.0


def test_anisotropic_axis_cte_scales_selected_dims():
    geo = tm.update_template_geometry(
        {"patch_len_mm": 40.0, "patch_w_mm": 50.0},
        cte_ppm_per_k=17.0, delta_t_c=100.0,
        axis_cte_ppm_per_k={"patch_w_mm": 0.0})
    assert geo["delta_mm"]["patch_len_mm"] == pytest.approx(40.0 * 17e-6 * 100.0, rel=1e-12)
    assert geo["delta_mm"]["patch_w_mm"] == 0.0


# ─── 9. 非法输入显式报错 ─────────────────────────────────────────────────────

def test_invalid_inputs_rejected():
    with pytest.raises(ValueError, match="nominal_mm"):
        tm.scale_dimension(0.0, 10.0, 20.0)
    with pytest.raises(ValueError, match="有限数"):
        tm.scale_dimension(10.0, float("nan"), 20.0)
    with pytest.raises(ValueError, match="eps_r"):
        tm.patch_resonance_ghz(30.0, 40.0, 0.5, 0.5)
    with pytest.raises(ValueError, match="line_len_mm"):
        tm.hairpin_resonance_ghz(0.0, 2.5)
    with pytest.raises(ValueError, match="model"):
        tm.thermo_mech_chain("dipole", delta_t_c=10.0, cte_ppm_per_k=10.0)
    with pytest.raises(ValueError, match="patch_len_mm"):
        tm.thermo_mech_chain("patch", delta_t_c=10.0, cte_ppm_per_k=10.0,
                             patch_w_mm=50.0, h_mm=0.5, eps_r=3.0)
    with pytest.raises(ValueError, match="不能为空"):
        tm.update_template_geometry({}, cte_ppm_per_k=10.0, delta_t_c=10.0)


# ─── 10. −40~85℃ patch/hairpin 漂移量 + 闭式对照（验收口径一次性报出）───────

def test_minus40_to_85c_patch_hairpin_drift_vs_closed_form():
    observed = {}
    for model, geom in (("patch", PATCH), ("hairpin", HAIRPIN)):
        for t_c in (-40.0, 85.0):
            chain = tm.thermo_mech_chain(
                model, delta_t_c=t_c - REF_C, cte_ppm_per_k=CTE,
                tcdk_ppm_per_k=TCDK, **geom)
            observed[(model, t_c)] = chain
            # 验收：单向链 vs 闭式在 20% 漂移量以内（pytest.approx rel）
            assert chain["oneway_drift_ppm"] == pytest.approx(
                chain["closed_form_drift_ppm"], rel=0.20)
    # 冷端升频、热端降频（C TE>0、TCDk>0 均为降频方向）
    assert observed[("patch", -40.0)]["oneway_drift_ppm"] > 0
    assert observed[("patch", 85.0)]["oneway_drift_ppm"] < 0
    assert observed[("hairpin", -40.0)]["oneway_drift_ppm"] > 0
    assert observed[("hairpin", 85.0)]["oneway_drift_ppm"] < 0
