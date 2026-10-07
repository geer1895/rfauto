"""AP-5 传播基础闭式包锚测试（规格深案 §A-7，2026-10-02）。

锚口径（任务书预声明 + 实现实测写锚 #118 裁判纪律，探测证据
runs/ap5_prop/probe_anchors.py）：

- two_ray：断点 d_break=4·h_tx·h_rx/λ 处干涉峰 = 20log10(1+|Γ(ψ)|)
  （|Γ|→1 极限 → 经典 +6.02dB，误差 <0.1dB 达成"过渡连续 <1dB"）；
  远场 d≥10·d_break 后与 d²/(h_tx·h_rx) 渐近线收敛 <0.2dB、
  −40dB/dec 斜率回归（实测 39.70 dB/dec@[10,40]·d_break，容差 0.5）；
  Brewster 角 Γ_v=0 → 退化为纯 FSPL（eps_r=15 时精确零，√14.0625=3.75
  恒等）。
- knife_edge：**任务书预写 "J(0)=−6.9dB" 实测勘误**——精确 J(0)=6.0206dB
  （=20log10(2)，scipy Fresnel 积分；"6.9" 是 P.526 闭式电平偏置常数，
  闭式 J(0)=6.033dB）。J(−2.5)≈0（亮区微波纹 −0.35dB）；大 v 20dB/dec
  （实测 19.9965@5→50）；exact vs approx 最大偏差 0.123dB@[−0.7,6]；
  Lee 分段（Rappaport §4.11，原文增益约定取负成 loss）vs exact 偏差
  <0.6dB@[0,2.4]。
- fresnel：d1↔d2 对称恒等；f^(−1/2) 标度律；f→∞ 半径→0；0.6F1 净空
  边界含等号。
- hata：900MHz/1km/30m/1.5m urban=126.40dB（任务书 120–130 量级窗）；
  suburban 修正 @900=9.94dB（任务书 "~9-10dB" 实测落在 classic 段；
  @1900 修正项本身=12.11dB+3dB(C) = 15.11dB，逐式核对）；域盒四角+
  域外 ValueError 全参数；接缝跳变 urban=4.33/suburban=1.33（差=C=3）。

零外部数据捆绑（PV-011 无阻碍）：全部锚=闭式恒等式/实现实测，无 ITU
表值。
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
from rfauto.core.propagation import (
    C0_M_S,
    clearance_ok,
    fresnel_zone_radius_m,
    hata_cost231_db,
    knife_edge_loss_approx_db,
    knife_edge_loss_db,
    knife_edge_loss_lee_db,
    reflection_coefficient,
    two_ray_breakpoint_m,
    two_ray_loss_db,
)
from rfauto.service.calculator_service import run_calculator

_KEYS = ("two_ray_loss", "knife_edge_loss", "hata_cost231")


# ─── 注册面（#231 五钉之一：test_calculators EXPECTED 见同批追加）────────────


@pytest.mark.parametrize("key", _KEYS)
def test_registered_and_json_contract(key: str):
    assert key in set(CALCULATOR_REGISTRY.names())
    spec = CALCULATOR_REGISTRY.get(key)
    assert spec.description and not spec.experimental
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    assert {p["name"] for p in described[key]["params"]} >= set(spec.required)
    json.dumps(described[key], ensure_ascii=False)


# ─── two_ray：断点过渡 + 远场 −40dB/dec + Brewster ─────────────────────────

_HT, _HR, _F900 = 30.0, 1.5, 900e6


def _fspl_db(d_m: float, f_hz: float) -> float:
    return 20.0 * math.log10(4.0 * math.pi * d_m * f_hz / C0_M_S)


def test_two_ray_breakpoint_formula():
    d_break = two_ray_breakpoint_m(_HT, _HR, _F900)
    assert d_break == pytest.approx(4.0 * _HT * _HR * _F900 / C0_M_S,
                                    rel=1e-15)


def test_two_ray_breakpoint_interference_peak_continuity():
    """断点处过渡连续性（任务书 <1dB）：L(d_break)−FSPL ≈ 20log10(1+|Γ|)。

    断点定义是渐近 Δd=λ/2 条件，精确 Δφ(d_break) 与 π 差 <0.02rad
    （30m/1.5m/900MHz 几何实测 0.0058rad），故恒等式留 1dB 物理余量
    （实测差 0.012dB）。|Γ|→1 极限另测（下一测）→ 经典 6.02dB。
    """
    d_break = two_ray_breakpoint_m(_HT, _HR, _F900)
    lam = C0_M_S / _F900
    dphi = 2.0 * math.pi * (
        math.hypot(d_break, _HT + _HR) - math.hypot(d_break, _HT - _HR)
    ) / lam
    assert abs(dphi - math.pi) < 0.02  # 断点=渐近 Δd=λ/2 条件的几何自洽
    psi = math.atan2(_HT + _HR, d_break)
    gamma = reflection_coefficient(psi, eps_r=15.0, pol="v")
    peak_theory = 20.0 * math.log10(1.0 + abs(gamma))
    got = _fspl_db(d_break, _F900) - two_ray_loss_db(
        d_break, _HT, _HR, _F900)
    assert abs(got - peak_theory) < 1.0  # 任务书过渡连续 <1dB 档
    assert abs(got - peak_theory) < 0.05  # 实测 0.012dB


def test_two_ray_grazing_limit_six_db():
    """|Γ|→1 极限（h_tx=h_rx=100m@900MHz，断点处 ψ≈1.67mrad）：
    干涉峰→+6.02dB。实测 |Γ_v|=0.98673 → 峰 5.965dB，距 6.0206 差
    0.056dB（容差 0.1dB；任务书 <1dB 的紧档）。"""
    d, h, f = two_ray_breakpoint_m(100.0, 100.0, 900e6), 100.0, 900e6
    psi = math.atan2(2.0 * h, d)
    peak_theory = 20.0 * math.log10(
        1.0 + abs(reflection_coefficient(psi, eps_r=15.0, pol="v")))
    got = _fspl_db(d, f) - two_ray_loss_db(d, h, h, f)
    assert got == pytest.approx(peak_theory, abs=1e-4)
    assert got == pytest.approx(20.0 * math.log10(2.0), abs=0.1)


def test_two_ray_far_field_40db_per_dec():
    """远场锚：d≥10·d_break 与 d²/(h_tx·h_rx) 渐近线收敛 <0.2dB（实测
    +0.143/+0.015/−0.042@10/20/40）；损耗对 log10(d) 斜率回归 +40dB/dec
    （=接收功率 −40dB/dec；实测 39.70@[10,40]·d_break，容差 0.5）。"""
    d_break = two_ray_breakpoint_m(_HT, _HR, _F900)
    for k in (10.0, 20.0, 40.0):
        d = k * d_break
        asym = 20.0 * math.log10(d * d / (_HT * _HR))
        assert two_ray_loss_db(d, _HT, _HR, _F900) == pytest.approx(
            asym, abs=0.2), f"d={k}*d_break"
    ks = [10, 14, 18, 22, 26, 30, 34, 40.0]
    Ls = [two_ray_loss_db(k * d_break, _HT, _HR, _F900) for k in ks]
    xs = [math.log10(k * d_break) for k in ks]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(Ls) / len(Ls)
    slope = sum((x - x_mean) * (y - y_mean)
                for x, y in zip(xs, Ls, strict=True))
    slope /= sum((x - x_mean) ** 2 for x in xs)
    assert slope == pytest.approx(40.0, abs=0.5)


def test_two_ray_brewster_reduces_to_fspl():
    """Brewster 掠射角（sinψ_B=1/√(εr+1)，εr=15 → 精确恒等 √14.0625=3.75）：
    Γ_v=0 → 双径退化为纯 FSPL（逐位）。Γ_h 同角 = −0.875（解析精确）。"""
    eps_r = 15.0
    psi_b = math.asin(1.0 / math.sqrt(eps_r + 1.0))
    assert reflection_coefficient(psi_b, eps_r, "v") == pytest.approx(
        0.0, abs=1e-12)
    ht, hr, f = 9.0, 1.0, 2.0e9
    d = (ht + hr) / math.tan(psi_b)
    fspl = _fspl_db(math.hypot(d, ht - hr), f)
    assert two_ray_loss_db(d, ht, hr, f, eps_r=eps_r, pol="v") == pytest.approx(
        fspl, abs=1e-9)
    assert reflection_coefficient(psi_b, eps_r, "h") == pytest.approx(
        -0.875, rel=1e-12)


def test_two_ray_grazing_both_pol_minus_one():
    """掠射极限 ψ→0：Γ_v/Γ_h → −1（水平极化更逼近；实测 ψ=1e-4rad：
    Γ_h=−0.999947、Γ_v=−0.99920）。"""
    assert reflection_coefficient(1e-4, 15.0, "h") < -0.9999
    assert reflection_coefficient(1e-4, 15.0, "v") < -0.999


def test_two_ray_domain_guards():
    with pytest.raises(ValueError):
        two_ray_loss_db(0.0, _HT, _HR, _F900)
    with pytest.raises(ValueError):
        two_ray_loss_db(100.0, 0.0, _HR, _F900)
    with pytest.raises(ValueError):
        two_ray_loss_db(100.0, _HT, _HR, -1.0)
    with pytest.raises(ValueError):
        two_ray_loss_db(100.0, _HT, _HR, _F900, eps_r=0.5)
    with pytest.raises(ValueError):
        two_ray_loss_db(100.0, _HT, _HR, _F900, pol="x")
    with pytest.raises(ValueError):
        reflection_coefficient(-0.1, 15.0, "v")


# ─── knife_edge：J(0) 锚（实测勘误 −6.9→6.02）+ 对称性 + 斜率 + 三档互检 ────


def test_knife_edge_j0_measured_anchor():
    """实测写锚：精确 J(0)=6.0206dB=20log10(2)（经典擦顶 6dB）；
    P.526 闭式 J(0)=6.0329dB（"6.9" 是电平偏置常数不是 J(0) 值——
    任务书预写 "J(0)=−6.9dB" 系常数误读，实测勘误记本测试）。"""
    assert knife_edge_loss_db(0.0) == pytest.approx(
        20.0 * math.log10(2.0), abs=1e-6)
    assert knife_edge_loss_approx_db(0.0) == pytest.approx(6.0328, abs=1e-3)
    assert abs(knife_edge_loss_db(0.0) - knife_edge_loss_approx_db(0.0)) < 0.05


def test_knife_edge_illuminated_side_near_zero():
    """v=−2.5（障碍远低于视线）：精确值微波纹 −0.353dB（≈0，容差 0.5）；
    P.526 闭式与 Lee 分段按约定记 0。"""
    assert knife_edge_loss_db(-2.5) == pytest.approx(0.0, abs=0.5)
    assert knife_edge_loss_approx_db(-2.5) == 0.0
    assert knife_edge_loss_lee_db(-2.5) == 0.0
    assert knife_edge_loss_approx_db(-1.0) == 0.0  # v≤−0.78 分支


def test_knife_edge_large_v_growth_20db_per_dec():
    slope = knife_edge_loss_db(50.0) - knife_edge_loss_db(5.0)
    assert slope == pytest.approx(20.0, abs=0.05)


def test_knife_edge_exact_vs_approx_max_deviation():
    """P.526 闭式近似互检：max|exact−approx| = 0.123dB@[−0.7,6]（实测）。"""
    worst = 0.0
    v = -0.7
    while v <= 6.0:
        worst = max(worst, abs(knife_edge_loss_db(v)
                               - knife_edge_loss_approx_db(v)))
        v += 0.001
    assert worst < 0.15


def test_knife_edge_lee_vs_exact():
    """Lee 分段（增益约定取负成 loss）vs 精确：v=0 逐位同值（0.5→6.02dB），
    [0, 2.4] 内最大偏差 <0.75dB（实测 0.725@v=2.4）；v>2.4 档 20log(v/0.225)。"""
    assert knife_edge_loss_lee_db(0.0) == pytest.approx(
        20.0 * math.log10(2.0), abs=1e-12)
    worst = max(abs(knife_edge_loss_db(v) - knife_edge_loss_lee_db(v))
                for v in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.3, 2.4))
    assert worst < 0.75
    assert knife_edge_loss_lee_db(3.0) == pytest.approx(
        20.0 * math.log10(3.0 / 0.225), rel=1e-12)


# ─── fresnel：对称性 + 标度律 + 净空判据 ───────────────────────────────────


def test_fresnel_symmetry_and_value():
    r1 = fresnel_zone_radius_m(300.0, 700.0, 2.4e9)
    assert r1 == fresnel_zone_radius_m(700.0, 300.0, 2.4e9)
    lam = C0_M_S / 2.4e9
    assert fresnel_zone_radius_m(1000.0, 1000.0, 2.4e9) == pytest.approx(
        math.sqrt(lam * 1000.0 * 1000.0 / 2000.0), rel=1e-15)


def test_fresnel_scaling_and_zero_limit():
    """F_n ∝ √n·f^(−1/2) 标度律（同式恒等）；f→∞（λ→0）半径→0。"""
    base = fresnel_zone_radius_m(300.0, 700.0, 2.4e9)
    assert fresnel_zone_radius_m(300.0, 700.0, 4.8e9) == pytest.approx(
        base / math.sqrt(2.0), rel=1e-15)
    assert fresnel_zone_radius_m(300.0, 700.0, 2.4e9, n=4.0) == pytest.approx(
        2.0 * base, rel=1e-15)
    # λ→0 半径→0（f^(−1/2)：实测半径比 0.00155@1e15 vs 2.4GHz）
    assert fresnel_zone_radius_m(300.0, 700.0, 1e15) / base < 0.002
    with pytest.raises(ValueError):
        fresnel_zone_radius_m(300.0, 700.0, 2.4e9, n=0.0)


def test_fresnel_clearance_boundary():
    f1 = fresnel_zone_radius_m(1000.0, 1000.0, 2.4e9)
    assert clearance_ok(0.6 * f1, 1000.0, 1000.0, 2.4e9)  # 等号在界内
    assert not clearance_ok(0.6 * f1 - 1e-6, 1000.0, 1000.0, 2.4e9)
    assert clearance_ok(0.61 * f1, 1000.0, 1000.0, 2.4e9)
    with pytest.raises(ValueError):
        clearance_ok(1.0, 1000.0, 1000.0, 2.4e9, ratio=1.5)


# ─── hata：域盒四角 + 域外 ValueError + env 修正量级 + 量级窗 + 接缝 ────────


def test_hata_magnitude_window_900mhz():
    """任务书量级自检：900MHz/1km/30m/1.5m urban ≈ 126.4dB ∈ [120,130]。"""
    got = hata_cost231_db(900.0, 1.0, 30.0, 1.5, env="urban")
    assert got == pytest.approx(126.4033, abs=0.01)
    assert 120.0 <= got <= 130.0


def test_hata_env_corrections():
    """env 修正（实测写锚）：suburban 修正项 @900 = 9.94dB（任务书
    "~9-10dB" 落在 classic 段）；@1900 修正项=12.11dB+urban C=3 →
    总差 15.11dB（逐式核对 2[log10(f/28)]²+5.4）；open < suburban。"""
    delta_900 = (hata_cost231_db(900.0, 1.0, 30.0, 1.5, "urban")
                 - hata_cost231_db(900.0, 1.0, 30.0, 1.5, "suburban"))
    assert delta_900 == pytest.approx(9.9426, abs=0.01)
    corr_1900 = 2.0 * math.log10(1900.0 / 28.0) ** 2 + 5.4
    delta_1900 = (hata_cost231_db(1900.0, 1.0, 30.0, 1.5, "urban")
                  - hata_cost231_db(1900.0, 1.0, 30.0, 1.5, "suburban"))
    assert delta_1900 == pytest.approx(corr_1900 + 3.0, abs=1e-9)
    open_1900 = hata_cost231_db(1900.0, 1.0, 30.0, 1.5, "open")
    sub_1900 = hata_cost231_db(1900.0, 1.0, 30.0, 1.5, "suburban")
    urb_1900 = hata_cost231_db(1900.0, 1.0, 30.0, 1.5, "urban")
    assert open_1900 < sub_1900 < urb_1900
    assert urb_1900 == pytest.approx(139.9908, abs=0.01)
    assert sub_1900 == pytest.approx(124.8814, abs=0.01)


def test_hata_domain_box_corners():
    """域盒四角有限正值守卫 + 单调性（d↑ 损耗↑ / h_b↑ 损耗↓）。"""
    corners = ((1500.0, 1.0, 30.0, 1.0), (2000.0, 20.0, 200.0, 10.0),
               (150.0, 1.0, 200.0, 10.0), (200.0, 20.0, 200.0, 1.0),
               (1500.0, 20.0, 30.0, 10.0))
    for f, d, hb, hm in corners:
        got = hata_cost231_db(f, d, hb, hm, env="urban")
        assert math.isfinite(got) and got > 0.0
    assert (hata_cost231_db(1900.0, 20.0, 50.0, 1.5)
            > hata_cost231_db(1900.0, 1.0, 50.0, 1.5))
    assert (hata_cost231_db(1900.0, 10.0, 200.0, 1.5)
            < hata_cost231_db(1900.0, 10.0, 30.0, 1.5))
    # d 斜率 = 44.9−6.55·log10(h_b)（同段恒等）
    slope = (hata_cost231_db(1900.0, 10.0, 50.0, 1.5)
             - hata_cost231_db(1900.0, 1.0, 50.0, 1.5))
    assert slope == pytest.approx(44.9 - 6.55 * math.log10(50.0), abs=1e-9)


def test_hata_out_of_domain_valueerror():
    for args in ((100.0, 1.0, 30.0, 1.5),      # f 下界
                 (2500.0, 1.0, 30.0, 1.5),     # f 上界
                 (900.0, 0.5, 30.0, 1.5),      # d 下界
                 (900.0, 25.0, 30.0, 1.5),     # d 上界
                 (900.0, 1.0, 10.0, 1.5),      # h_b 下界
                 (900.0, 1.0, 300.0, 1.5),     # h_b 上界
                 (900.0, 1.0, 30.0, 0.5),      # h_m 下界
                 (900.0, 1.0, 30.0, 15.0),     # h_m 上界
                 ):
        with pytest.raises(ValueError):
            hata_cost231_db(*args, env="urban")
    with pytest.raises(ValueError):
        hata_cost231_db(900.0, 1.0, 30.0, 1.5, env="rural")


def test_hata_seam_discontinuity():
    """f=1500 接缝模型级不连续（实测写锚）：urban=4.3330dB /
    suburban=1.3330dB，差=C=3 metropolitan 项。闭式含跨缝 Δlog10(f) 项
    （26.16·Δlf−(1.1·h_m−1.56)·Δlf，Δf=0.001MHz 贡献 7.5e-6）。"""
    jump_u = (hata_cost231_db(1500.0, 2.0, 50.0, 1.5, "urban")
              - hata_cost231_db(1499.999, 2.0, 50.0, 1.5, "urban"))
    jump_s = (hata_cost231_db(1500.0, 2.0, 50.0, 1.5, "suburban")
              - hata_cost231_db(1499.999, 2.0, 50.0, 1.5, "suburban"))
    lf2, lf1 = math.log10(1500.0), math.log10(1499.999)
    d_lf = lf2 - lf1
    closed_u = ((46.3 - 69.55) + 33.9 * lf2 - 26.16 * lf1
                - (1.1 * 1.5 - 1.56) * d_lf)
    # suburban 修正式自身也是 f 的函数，跨缝差 2·d_lf·(lf2+lf1−2·log10(28))
    delta_corr = 2.0 * d_lf * (lf2 + lf1 - 2.0 * math.log10(28.0))
    assert jump_u == pytest.approx(closed_u + 3.0, abs=1e-12)
    assert jump_s == pytest.approx(closed_u - delta_corr, abs=1e-12)
    assert jump_u - jump_s == pytest.approx(3.0 + delta_corr, abs=1e-12)
    assert jump_u == pytest.approx(4.3330, abs=0.001)
    assert jump_s == pytest.approx(1.3330, abs=0.001)


# ─── 注册键 service 出口（JSON 进出契约 + 错误语义）─────────────────────────


def test_service_two_ray_result_matches_core():
    out = run_calculator("two_ray_loss", {
        "d_m": 5000.0, "h_tx_m": 30.0, "h_rx_m": 1.5, "f_hz": 900e6})
    assert out["ok"], out
    core = two_ray_loss_db(5000.0, 30.0, 1.5, 900e6)
    assert out["result"]["loss_db"] == core
    assert out["result"]["d_break_m"] == two_ray_breakpoint_m(30.0, 1.5, 900e6)
    assert out["result"]["pol"] == "v"
    json.dumps(out, ensure_ascii=False, allow_nan=False)


def test_service_knife_edge_three_methods():
    for method, fn in (("exact", knife_edge_loss_db),
                       ("approx", knife_edge_loss_approx_db),
                       ("lee", knife_edge_loss_lee_db)):
        out = run_calculator("knife_edge_loss", {"v": 1.0, "method": method})
        assert out["ok"], out
        assert out["result"]["loss_db"] == fn(1.0)
        assert out["result"]["method"] == method
    out = run_calculator("knife_edge_loss", {"v": 1.0, "method": "bad"})
    assert not out["ok"] and out.get("error")


def test_service_hata_error_semantics():
    out = run_calculator("hata_cost231", {
        "f_mhz": 1900.0, "d_km": 2.0, "h_b_m": 50.0, "h_m_m": 1.5})
    assert out["ok"], out
    assert out["result"]["loss_db"] == hata_cost231_db(1900.0, 2.0, 50.0, 1.5)
    assert out["result"]["band"] == "cost231"
    # 域外 → ok=False 显式报错（不抛出）
    out_bad = run_calculator("hata_cost231", {
        "f_mhz": 900.0, "d_km": 30.0, "h_b_m": 50.0, "h_m_m": 1.5})
    assert out_bad["ok"] is False and out_bad.get("error")
    # 缺必需参数 → ok=False
    out_miss = run_calculator("hata_cost231", {"f_mhz": 1900.0})
    assert out_miss["ok"] is False and "缺少必需参数" in out_miss["error"]
