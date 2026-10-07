"""ge6 pool3 T-match 闭式单测（t_match_impedance / t_match_design）。

锚值口径（#118 双路径纪律；出处=core/t_match.py docstring：Balanis 3ed
§9.7.3 式 (9-48)–(9-55)，2026-09-30 原文 PDF 逐位核对）：
- 等半径 α=1（任意间距）→ 步升 (1+α)²=4；
- 折合极限 l'≈λ/2：Zin→4×(73+j42.5)=292+j170 Ω（(9-53)/(9-54)，教科书
  普适折合偶极子锚；数值取 l'=0.499999λ 时 291.999/170.000）；
- 等效半径等半径极限 a_e=√(a·s)（(9-49) 闭式手算：ln a_e=(ln a+ln s)/2）；
- 设计 73+j0→50 双路径：测试独立解二次式正根 Y=Rp·√(R0/(Rp−R0))
  （Rp=292）→ Y=132.72888...，回代分析链 rin_re_check=50（恰等回收）。
- 量纲自洽：等效半径 m/mm 同值（(9-49) 系数和归一，单位无关）。
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

_F0 = 300e6
_A = 1e-3          # 主棒半径 m
_AP = 1e-3         # T 棒半径 m（等半径锚）
_S = 5e-3          # 中心距 m
_LAMBDA = 299792458.0 / _F0
_ANA = {"freq_hz": _F0, "main_radius_m": _A, "bar_radius_m": _AP,
        "spacing_m": _S}
_DES = {**_ANA, "za_re_ohm": 73.0, "za_im_ohm": 0.0, "target_rin_ohm": 50.0}


# ─── 注册面（接口先行）───────────────────────────────────────────────────────

def test_tmatch_keys_registered_and_described():
    names = CALCULATOR_REGISTRY.names()
    keys = {"t_match_impedance", "t_match_design"}
    assert keys <= set(names)
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    for key in keys:
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.description and not spec.experimental
        assert {p["name"] for p in described[key]["params"]} >= set(spec.required)


# ─── α 电流分配因子：(9-48) 三锚 ─────────────────────────────────────────────

def test_alpha_equal_radii_is_unity_any_spacing():
    """等半径（u=1）→ acosh 两参数同为 v/2 → α=1、步升 4（(9-54) 前提）。"""
    for s in (3e-3, 5e-3, 20e-3):
        out = run_calculator("t_match_impedance",
                             {**_ANA, "spacing_m": s,
                              "tbar_length_m": 0.1,
                              "dipole_length_m": 0.5})["result"]
        assert out["alpha"] == pytest.approx(1.0, rel=1e-12)
        assert out["stepup_ratio"] == pytest.approx(4.0, rel=1e-12)


def test_alpha_matches_thin_wire_approx_and_monotone_in_bar_radius():
    """细线近似式 ln(v)/(ln(v)−ln(u)) 的一致性（v≫u 收敛）+ 方向钉：
    T 棒越细（Balanis 馈棒口径）α 越大 → 步升越大。"""
    out = run_calculator("t_match_impedance",
                         {**_ANA, "bar_radius_m": 0.2e-3,
                          "tbar_length_m": 0.1,
                          "dipole_length_m": 0.5})["result"]
    # u=a/a'=5, v=s/a'=25：近似式与 acosh 式同阶一致（非逐位——两式即近似关系）
    u, v = 5.0, 25.0
    approx = math.log(v) / (math.log(v) - math.log(u))
    assert out["alpha"] == pytest.approx(approx, rel=0.05)
    # 方向：棒变细 → α 增大
    out_fat = run_calculator("t_match_impedance",
                             {**_ANA, "bar_radius_m": 2.0e-3,
                              "spacing_m": 4.0e-3, "tbar_length_m": 0.1,
                              "dipole_length_m": 0.5})["result"]
    out_thin = run_calculator("t_match_impedance",
                              {**_ANA, "bar_radius_m": 0.25e-3,
                               "tbar_length_m": 0.1,
                               "dipole_length_m": 0.5})["result"]
    assert out_thin["alpha"] > 1.0 > out_fat["alpha"]
    assert out_thin["stepup_ratio"] > 4.0 > out_fat["stepup_ratio"]


def test_alpha_domain_requires_non_overlapping_wires():
    """v < u+1（⟺ s<a+a'）acosh 定义域外 → 显式拒绝（恰等也拒）。"""
    out = run_calculator("t_match_impedance",
                         {**_ANA, "spacing_m": 1.5e-3,
                          "tbar_length_m": 0.1, "dipole_length_m": 0.4})
    assert not out["ok"] and "相交" in out["error"]


# ─── 折合极限与经典 4× 锚（(9-53)/(9-54)）────────────────────────────────────

def test_folded_limit_292_plus_j170_literal_anchor():
    """l'≈λ/2 → Zin→(1+α)²Za；等半径半波锚 4×(73+j42.5)=292+j170 Ω。"""
    out = run_calculator("t_match_impedance",
                         {**_ANA, "tbar_length_m": 0.499999 * _LAMBDA,
                          "dipole_length_m": _LAMBDA,
                          "za_re_ohm": 73.0, "za_im_ohm": 42.5})["result"]
    assert out["zin_re_ohm"] == pytest.approx(292.0, rel=1e-5)
    assert out["zin_im_ohm"] == pytest.approx(170.0, rel=1e-5)


def test_z0_two_wire_folded_limit_formula():
    """(9-50a)：等半径 Z0=60·acosh((s²−2a²)/(2a²))≈276·log10(s/a) 互证。"""
    out = run_calculator("t_match_impedance",
                         {**_ANA, "tbar_length_m": 0.1,
                          "dipole_length_m": 0.5})["result"]
    z0_exact = 60.0 * math.acosh((_S * _S - 2.0 * _A * _A)
                                 / (2.0 * _A * _A))
    z0_approx = 276.0 * math.log10(_S / _A)
    assert out["z0_two_wire_ohm"] == pytest.approx(z0_exact, rel=1e-9)
    assert z0_exact == pytest.approx(z0_approx, rel=0.05)  # 细线近似互证


def test_equivalent_radius_equal_radii_sqrt_anchor_and_dimension_free():
    """(9-49)：等半径极限 a_e=√(a·s)（手算）；m/mm 单位无关（量纲自消）。"""
    from rfauto.core.t_match import equivalent_radius

    ae = equivalent_radius(_A, _A, _S)
    assert ae == pytest.approx(math.sqrt(_A * _S), rel=1e-12)
    ae_mm = equivalent_radius(_A * 1e3, _A * 1e3, _S * 1e3)
    assert ae_mm == pytest.approx(ae * 1e3, rel=1e-12)  # mm 回乘=同值


# ─── 设计闭式：73→50 双路径回收 + (9-55) 电容 ────────────────────────────────

def test_design_73_to_50_dual_path_quadratic_recovery():
    """测试独立解二次式特形根 Y=Rp·√(R0/(Rp−R0))（Rp=292、R0=50 →
    有理数 Y=292·5/11=1460/11），回代分析链 Re(Zin)=50（恰等回收）+
    字面锚 Y/tbar/C。"""
    out = run_calculator("t_match_design", _DES)["result"]
    assert out["alpha"] == pytest.approx(1.0, rel=1e-12)
    rp = 4.0 * 73.0
    y_expected = rp * math.sqrt(50.0 / (rp - 50.0))
    assert out["stub_total_reactance_ohm"] == pytest.approx(y_expected,
                                                            rel=1e-9)
    # 独立路径 B：Xp=0 特形 (Rp−R0)Y²=R0·Rp² 直接解
    y_b = math.sqrt(50.0 * rp * rp / (rp - 50.0))
    assert y_b == pytest.approx(y_expected, rel=1e-12)
    # T 棒长：l'=2·atan((Y/2)/Z0)/k（tan 主支反解）
    z0 = out["z0_two_wire_ohm"]
    k = 2.0 * math.pi / _LAMBDA
    assert out["tbar_length_m"] == pytest.approx(
        2.0 * math.atan((y_expected / 2.0) / z0) / k, rel=1e-9)
    # 恰等回收：正向 rin_re_check=target（输出 round 9 位 → abs 1e-6 容差）
    assert out["rin_re_check_ohm"] == pytest.approx(50.0, abs=1e-6)
    # (9-55)：两只串联电容各 Xc=1/(2πfC)，合计=残量 Xin；C 输出 round
    # 15 位（~1e-4 相对）→ 本检查容差 5e-4（rounding 主导，非公式误差）
    c_each = out["resonating_cap_each_f"]
    assert 2.0 / (2.0 * math.pi * _F0 * c_each) == pytest.approx(
        out["zin_im_ohm"], rel=5e-4)
    # 字面锚（独立手算落定）：Y=292·5/11=1460/11（有理数！）、
    # l'=107.933121300 mm、C=9.646 pF、残量 Xin=110 Ω
    assert y_expected == pytest.approx(1460.0 / 11.0, rel=1e-12)
    assert out["stub_total_reactance_ohm"] == pytest.approx(132.727272727273,
                                                            rel=1e-9)
    assert out["tbar_length_m"] == pytest.approx(0.107933121300327, rel=1e-9)
    assert out["zin_im_ohm"] == pytest.approx(110.0, rel=1e-9)
    assert out["resonating_cap_each_f"] == pytest.approx(9.645754127e-12,
                                                         rel=1e-8)


def test_design_monotone_in_target_and_stepup_guard():
    """目标 Rin↑ → 需更短/更弱的短截线（Re(Zin) 随 Y 单调升、Y→∞ 时
    Re→步升值）：目标 50 比 30 更接近步升 292 → Y/l' 更大；目标 ≥ 步升
    实部 → 显式报错（并联结构只能把实部从步升值往下拉）。"""
    out50 = run_calculator("t_match_design", _DES)["result"]
    out30 = run_calculator("t_match_design",
                           {**_DES, "target_rin_ohm": 30.0})["result"]
    assert out30["stub_total_reactance_ohm"] < out50["stub_total_reactance_ohm"]
    assert out30["tbar_length_m"] < out50["tbar_length_m"]
    out = run_calculator("t_match_design",
                         {**_DES, "target_rin_ohm": 400.0})
    assert not out["ok"] and "步升" in out["error"]


# ─── 域守卫与入参契约 ────────────────────────────────────────────────────────

def test_domain_and_contract_errors_are_explicit():
    ana = {**_ANA, "tbar_length_m": 0.1, "dipole_length_m": 0.45}
    out = run_calculator("t_match_impedance", {"freq_hz": _F0})
    assert not out["ok"] and "缺少必需参数" in out["error"]
    out = run_calculator("t_match_impedance", {**ana, "bogus_k": 1})
    assert not out["ok"]
    # l'>l（T-match 定义违反）/ l'≥λ（tan 主支越域）/ bool 拒收
    for bad in ({**ana, "tbar_length_m": 0.5},
                {**ana, "tbar_length_m": 1.5, "dipole_length_m": 2.0},
                {**ana, "tbar_length_m": True}):
        out = run_calculator("t_match_impedance", bad)
        assert not out["ok"] and out.get("error"), bad


def test_service_results_json_serializable():
    for key, params in (("t_match_impedance",
                         {**_ANA, "tbar_length_m": 0.1,
                          "dipole_length_m": 0.45}),
                        ("t_match_design", _DES)):
        out = run_calculator(key, params)
        assert out["ok"], (key, out)
        json.dumps(out, ensure_ascii=False, allow_nan=False)
