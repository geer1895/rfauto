"""批 B Wave3 G15+G16：Yagi-Uda（NBS TN688）与波导缝隙阵（Stevenson）锚树。

裁判口径（规格包 内部证据目录，2026-10-13 实现席
独立复算；G16 以 RESOLVED 裁决版为公式权威）：

- **G16 式形态=RESOLVED 裁决式**（规格包式 S1 已证伪勘误）：
  g(x) = 2.09·(a/b)·(λg/λ0)·cos²(πλ0/(2λg))·sin²(πx/a)——含 (a/b) 与
  cos² 两因子，四路独立二手源逐字互证+WR90 数值逐位（RESOLVED §2）；
  规格包"带 cos² 则 g_max<1 物理不可能"的否定论证系漏乘 (a/b)=2.25 的
  错误否定（A8 作废），正确形态 g_max(WR90,10GHz)=0.877747、
  g_max(9.375GHz)=1.235286 与全波实测逐位相容。
- **锚值双路径**（#118）：实现路线=registry 键；独立第二路线=本文件
  纯 math 重算（λg/正解闭式）+g_max=1 边界频率二分求根（不同算法）+
  RESOLVED 勘误表 A1-A7/N1-N4 六位小数三源互证；另钉 S1 源
  （arXiv:2608.21231）Table II 跨源值 0.12765（5 位）。
- **G15 锚=NBS TN688 原文文本级验证值**（Viezbicke 1976，public domain，
  §4/例题/Fig.13-19 图注逐字）：B1 六档增益阶梯/B2 dBi 恒等/B3 反射器
  0.2λ/B4 例题 1 长度（恒等复核 ±0.003λ 截断容差）/B6 例题 2 几何/
  B7 档位单元数。经验面（非闭式）如实标注——插值档显式 interpolated
  标记，Table 1 全表数字化维持待有书不硬造。
"""

from __future__ import annotations

import math
import sys
from itertools import pairwise
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.service.calculator_service import run_calculator

C_MM_GHZ_TEST = 299.792458  # 测试侧独立常数（与 registry 单源同值，双写防篡改）
assert C_MM_GHZ_TEST == C_MM_GHZ

A_MM, B_MM = 22.86, 10.16  # WR-90 内尺寸（RESOLVED §4 复算环境）


# ─── 第二路线：纯 math 独立重算（不 import 实现模块的内部函数）───────────────

def _lam0(f_ghz: float) -> float:
    return C_MM_GHZ_TEST / f_ghz


def _lamg(f_ghz: float, a_mm: float) -> float:
    l0 = _lam0(f_ghz)
    return l0 / math.sqrt(1.0 - (l0 / (2.0 * a_mm)) ** 2)


def _gmax(f_ghz: float, a_mm: float = A_MM, b_mm: float = B_MM) -> float:
    """RESOLVED 式 R 前因子（本文件独立重算路线）。"""
    l0, lg = _lam0(f_ghz), _lamg(f_ghz, a_mm)
    return 2.09 * (a_mm / b_mm) * (lg / l0) * math.cos(
        math.pi * l0 / (2.0 * lg)) ** 2


def _g_of(f_ghz: float, x_mm: float) -> float:
    return _gmax(f_ghz) * math.sin(math.pi * x_mm / A_MM) ** 2


def _gmax1_boundary_ghz() -> float:
    """g_max(f)=1 边界频率二分求根（第二路线，与 RESOLVED 一行式不同算法）。"""
    lo, hi = 7.0, 12.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _gmax(mid) > 1.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _run(name: str, params: dict) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} {params} 未过: {out.get('error')!r}"
    return out["result"]


def _run_err(name: str, params: dict) -> str:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name} {params} 应显式拒绝: {out!r}")
    return out["error"]


# ═══ G16 键 1：slot_stevenson_conductance（RESOLVED 勘误表逐钉）══════════════

@pytest.mark.parametrize("f_ghz,anchor", [
    (10.0, 6.557140),      # A1 fc(TE10)
    (9.375, 6.557140),     # fc 与 f 无关（同 a）
])
def test_g16_a1_cutoff(f_ghz: float, anchor: float) -> None:
    r = _run("slot_stevenson_conductance",
             {"f_ghz": f_ghz, "a_mm": A_MM, "b_mm": B_MM,
              "offset_x_mm": 1.0})
    assert round(r["fc_ghz"], 6) == anchor


def test_g16_a2_lambda0() -> None:
    r = _run("slot_stevenson_conductance",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "offset_x_mm": 1.0})
    assert round(r["lambda_0_mm"], 6) == 29.979246


@pytest.mark.parametrize("f_ghz,anchor", [(10.0, 39.707119),        # A3
                                          (9.375, 44.742883)])      # A4
def test_g16_lambda_g(f_ghz: float, anchor: float) -> None:
    r = _run("slot_stevenson_conductance",
             {"f_ghz": f_ghz, "a_mm": A_MM, "b_mm": B_MM, "offset_x_mm": 1.0})
    assert round(r["lambda_g_mm"], 6) == anchor
    # 第二路线独立重算逐位
    assert r["lambda_g_mm"] == pytest.approx(_lamg(f_ghz, A_MM), rel=0, abs=1e-12)


def test_g16_a5_gmax_two_routes() -> None:
    """A5 勘误锚 g_max(10GHz)=0.877747 + N2 g_max(9.375)=1.235286（6 位）。"""
    r10 = _run("slot_stevenson_conductance",
               {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": 0.5})
    r9375 = _run("slot_stevenson_conductance",
                 {"f_ghz": 9.375, "a_mm": A_MM, "b_mm": B_MM, "g": 0.5})
    assert round(r10["g_max"], 6) == 0.877747
    assert round(r9375["g_max"], 6) == 1.235286
    # 实现路线 vs 本文件独立重算逐位
    assert r10["g_max"] == pytest.approx(_gmax(10.0), rel=0, abs=1e-12)
    assert r9375["g_max"] == pytest.approx(_gmax(9.375), rel=0, abs=1e-12)


def test_g16_a5_x_at_half_wave_equals_gmax() -> None:
    """x=a/2 恰值接受 → g=g_max 逐位（贴壁缝理想口径）。"""
    r = _run("slot_stevenson_conductance",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
              "offset_x_mm": A_MM / 2.0})
    assert r["conductance"] == r["g_max"]


def test_g16_a6_offsets() -> None:
    """A6 勘误锚 g(1/2/3mm)@10GHz = 0.0164733/0.0646566/0.1409327（7 位）。"""
    for x, anchor in ((1.0, 0.0164733), (2.0, 0.0646566), (3.0, 0.1409327)):
        r = _run("slot_stevenson_conductance",
                 {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
                  "offset_x_mm": x})
        assert round(r["conductance"], 7) == anchor
        assert r["conductance"] == pytest.approx(
            _g_of(10.0, x), rel=0, abs=1e-12)


def test_g16_sin2_half_angle_second_route() -> None:
    """同域两条代数路径：sin²θ=(1−cos2θ)/2 半角恒等式重算 ≤1e-12。"""
    for x in (0.5, 2.0, 5.0, 8.0):
        g_impl = _run("slot_stevenson_conductance",
                      {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
                       "offset_x_mm": x})["conductance"]
        prefactor = _gmax(10.0)
        half_angle = prefactor * (
            1.0 - math.cos(2.0 * math.pi * x / A_MM)) / 2.0
        assert g_impl == pytest.approx(half_angle, rel=0, abs=1e-12)
        assert g_impl == pytest.approx(
            prefactor * math.sin(math.pi * x / A_MM) ** 2, rel=0, abs=1e-12)


def test_g16_a7_reject_and_alternative_anchors() -> None:
    """A7 勘误：f=10GHz g=1 不可达（显式拒绝）+ 替代锚①②正解值。"""
    err = _run_err("slot_stevenson_conductance",
                   {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": 1.0})
    assert "g_max" in err and "0.877747" in err
    # 替代锚①：g=1 @9.375GHz → x=8.143710mm（x/a=0.356243）
    r1 = _run("slot_stevenson_conductance",
              {"f_ghz": 9.375, "a_mm": A_MM, "b_mm": B_MM, "g": 1.0})
    assert round(r1["offset_x_mm"], 6) == 8.143710
    assert round(r1["offset_frac"], 6) == 0.356243
    # 替代锚②：g=0.5 @10GHz → x=6.223392mm（x/a=0.272239）
    r2 = _run("slot_stevenson_conductance",
              {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": 0.5})
    assert round(r2["offset_x_mm"], 6) == 6.223392
    assert round(r2["offset_frac"], 6) == 0.272239


def test_g16_n1_boundary_frequency() -> None:
    """N1：g_max(f)=1 边界频率=9.753118 GHz（二分第二路线）+ 六参考点。"""
    assert round(_gmax1_boundary_ghz(), 6) == 9.753118
    refs = [(8.0, 3.172828), (9.0, 1.548308), (9.375, 1.235286),
            (10.0, 0.877747), (11.0, 0.543655), (12.0, 0.357935)]
    for f, anchor in refs:
        r = _run("slot_stevenson_conductance",
                 {"f_ghz": f, "a_mm": A_MM, "b_mm": B_MM, "g": 0.01})
        assert round(r["g_max"], 6) == anchor, f


def test_g16_n3_n4_s1_cross_source() -> None:
    """N3 g(6mm)@9.375=0.665976（S2 源曲线互证）+ N4 分解 + S1 源跨源钉。"""
    r = _run("slot_stevenson_conductance",
             {"f_ghz": 9.375, "a_mm": A_MM, "b_mm": B_MM, "offset_x_mm": 6.0})
    assert round(r["conductance"], 6) == 0.665976
    # N4：cos²(10GHz)=0.140927、(a/b)=2.25、λg/λ0=1.324487（docstring 分解）
    l0, lg = _lam0(10.0), _lamg(10.0, A_MM)
    assert round(math.cos(math.pi * l0 / (2 * lg)) ** 2, 6) == 0.140927
    assert round(A_MM / B_MM, 6) == 2.25
    assert round(lg / l0, 6) == 1.324487
    # S1 源（arXiv:2608.21231 Table II）跨源钉：x=2.3814mm@9.375 → 0.12765
    r2 = _run("slot_stevenson_conductance",
              {"f_ghz": 9.375, "a_mm": A_MM, "b_mm": B_MM,
               "offset_x_mm": 2.3814})
    assert round(r2["conductance"], 6) == 0.127649
    assert abs(r2["conductance"] - 0.12765) < 1e-5


@pytest.mark.parametrize("x_mm", [0.5, 2.0, 6.223392, 8.0])
def test_g16_roundtrip(x_mm: float) -> None:
    """offset→g→offset roundtrip ≤1e-12（反解 arcsin 主支单调）。"""
    fwd = _run("slot_stevenson_conductance",
               {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
                "offset_x_mm": x_mm})
    back = _run("slot_stevenson_conductance",
                {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
                 "g": fwd["conductance"]})
    assert back["offset_x_mm"] == pytest.approx(x_mm, rel=0, abs=1e-12)


def test_g16_zero_and_cap_identities() -> None:
    """恰等行为：x=0 ⇔ g=0 双向恒等；g=g_max ⇔ x=a/2 双向。"""
    z = _run("slot_stevenson_conductance",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "offset_x_mm": 0.0})
    assert z["conductance"] == 0.0
    z2 = _run("slot_stevenson_conductance",
              {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": 0.0})
    assert z2["offset_x_mm"] == 0.0
    cap = _run("slot_stevenson_conductance",
               {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": 0.8777474746031757})
    assert cap["offset_x_mm"] == pytest.approx(A_MM / 2.0, rel=0, abs=1e-9)


def test_g16_g_just_above_cap_rejected() -> None:
    gmax10 = _gmax(10.0)
    _run_err("slot_stevenson_conductance",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
              "g": gmax10 * (1.0 + 1e-9)})


def test_g16_monotonic_and_asymptotics() -> None:
    """g 依 x 严格单调增；λg 对 f 单调降且 f→fc⁺ 发散（λg/λ0>15）。

    （规格包 §② 恒等式清单"λg 对 f 单调增"系方向笔误——其自身锚
    A3 λg(10)=39.71 < A4 λg(9.375)=44.74 已证单调试向；λg 实为对
    λ0（降 f 方向）单调增，此处按数值事实钉。）
    """
    fc = C_MM_GHZ_TEST / (2 * A_MM)
    gs = [_run("slot_stevenson_conductance",
               {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM,
                "offset_x_mm": x})["conductance"]
          for x in (0.5, 1.0, 2.0, 4.0, 8.0, 11.0)]
    assert all(b > a for a, b in pairwise(gs))
    lgs = [_run("slot_stevenson_conductance",
                {"f_ghz": f, "a_mm": A_MM, "b_mm": B_MM,
                 "offset_x_mm": 1.0})["lambda_g_mm"]
           for f in (7.0, 8.0, 9.0, 10.0, 12.0)]
    assert all(b < a for a, b in pairwise(lgs))
    near = _run("slot_stevenson_conductance",
                {"f_ghz": 1.001 * fc, "a_mm": A_MM, "b_mm": B_MM,
                 "offset_x_mm": 1.0})
    assert near["lambda_g_mm"] / near["lambda_0_mm"] > 15.0


@pytest.mark.parametrize("f_ghz", [6.557140376202975,  # fc 恰值
                                   0.999 * 6.557140376202975,
                                   2 * 6.557140376202975])
def test_g16_single_mode_domain_reject(f_ghz: float) -> None:
    _run_err("slot_stevenson_conductance",
             {"f_ghz": f_ghz, "a_mm": A_MM, "b_mm": B_MM, "offset_x_mm": 2.0})


def test_g16_route_and_finite_guards() -> None:
    """route 同给/全缺显式拒绝；NaN/inf 拒绝（_finite 口径）。"""
    base = {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM}
    both = dict(base, offset_x_mm=2.0, g=0.1)
    assert "二选一" in _run_err("slot_stevenson_conductance", both)
    assert "须给其一" in _run_err("slot_stevenson_conductance", dict(base))
    assert "有限" in _run_err(
        "slot_stevenson_conductance", dict(base, offset_x_mm=float("inf")))
    assert "有限" in _run_err(
        "slot_stevenson_conductance", dict(base, g=float("nan")))


# ═══ G16 键 2：slot_array_synthesis_resonant ═══════════════════════════════

def test_g16_array_uniform_ladder_identities() -> None:
    """均匀 8 缝 g_total=1：gn=1/8、Σgn=g_total、λg/2 间距、短路=末缝+λg/4。"""
    r = _run("slot_array_synthesis_resonant",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": 10.16, "n_slots": 8,
              "weights": [1.0] * 8})
    lg = r["lambda_g_mm"]
    assert all(g == pytest.approx(0.125, rel=0, abs=1e-15)
               for g in r["conductances"])
    assert r["sum_conductance"] == pytest.approx(1.0, rel=0, abs=1e-12)
    assert r["positions_mm"] == [pytest.approx(i * lg / 2.0, rel=0, abs=1e-12)
                                 for i in range(8)]
    assert r["short_position_mm"] == pytest.approx(
        r["positions_mm"][-1] + lg / 4.0, rel=0, abs=1e-12)


def test_g16_array_taper_and_alternating_signs() -> None:
    """锥度权重 gn∝wn²/Σw² + 相邻缝交替换边符号序列 + 偏置幅值反解一致性。"""
    w = [1.0, 0.5, 0.5, 1.0]
    r = _run("slot_array_synthesis_resonant",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "n_slots": 4,
              "weights": w, "g_total": 0.6})
    w2sum = sum(v * v for v in w)
    expect = [0.6 * v * v / w2sum for v in w]
    assert r["conductances"] == pytest.approx(expect, rel=0, abs=1e-15)
    assert r["sum_conductance"] == pytest.approx(0.6, rel=0, abs=1e-12)
    assert r["offset_signs"] == [1.0, -1.0, 1.0, -1.0]
    # 偏置幅值 = 键 1 反解同源（跨键同源恒等）
    for g_n, off in zip(r["conductances"], r["offset_x_mm"], strict=True):
        inv = _run("slot_stevenson_conductance",
                   {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": g_n})
        assert abs(off) == pytest.approx(inv["offset_x_mm"], rel=0, abs=1e-12)


def test_g16_array_gtotal1_at_high_f_rejected() -> None:
    """RESOLVED note 守卫：f=10GHz g_max=0.8777<1 → 均匀 4 缝 g_total=1
    单缝 gn=0.25 可行；改 2 缝 gn=0.5 仍可行；1 缝域外（n≥2 下界）；
    g_total=4.0/4 缝 gn=1.0>g_max 拒绝并提示分摊。"""
    _run("slot_array_synthesis_resonant",
         {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "n_slots": 4,
          "weights": [1.0] * 4})
    err = _run_err("slot_array_synthesis_resonant",
                   {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "n_slots": 4,
                    "weights": [1.0] * 4, "g_total": 4.0})
    assert "g_max" in err


def test_g16_array_zero_weight_slot_placeholder() -> None:
    """零权重缝 offset=0 如实输出（占位不辐射），Σgn 不变。"""
    r = _run("slot_array_synthesis_resonant",
             {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "n_slots": 3,
              "weights": [1.0, 0.0, 1.0]})
    assert r["offset_x_mm"][1] == 0.0
    assert r["conductances"][1] == 0.0
    assert r["sum_conductance"] == pytest.approx(1.0, rel=0, abs=1e-12)


# ═══ G15 键 1：yagi_gain_nbs_tn688（B1/B2 锚 + 插值面）══════════════════════

_B1 = [(0.4, 7.1), (0.8, 9.2), (1.2, 10.2), (2.2, 12.3), (3.2, 13.4),
       (4.2, 14.2)]  # NBS TN688 §4 p.16 逐字（B1）


@pytest.mark.parametrize("boom,gain", _B1)
def test_g15_b1_anchor_ladder(boom: float, gain: float) -> None:
    r = _run("yagi_gain_nbs_tn688", {"boom_length_lambda": boom})
    assert r["gain_dbd"] == gain
    assert r["interpolated"] is False
    assert r["class_lambda"] == boom


@pytest.mark.parametrize("boom,gain", _B1)
def test_g15_b2_dbi_identity(boom: float, gain: float) -> None:
    """B2：dBi = dBd + 2.15 恒等逐位（六档 + 插值档同式）；十进制锚 2 位。"""
    r = _run("yagi_gain_nbs_tn688", {"boom_length_lambda": boom})
    assert r["gain_dbi"] == r["gain_dbd"] + 2.15
    assert round(r["gain_dbi"], 2) == round(gain + 2.15, 2)
    # 插值档取域内邻点（4.2 为上端点，向内取）
    boom_i = boom - 0.05 if boom == 4.2 else boom + 0.05
    r_i = _run("yagi_gain_nbs_tn688", {"boom_length_lambda": boom_i})
    assert r_i["gain_dbi"] == r_i["gain_dbd"] + 2.15
    assert r_i["interpolated"] is True


def test_g15_interpolation_midpoint_and_monotonic() -> None:
    """档间线性插值独立重算（boom=1.0 → (9.2+10.2)/2=9.7）+ 六点单调。"""
    r = _run("yagi_gain_nbs_tn688", {"boom_length_lambda": 1.0})
    assert r["gain_dbd"] == pytest.approx(0.5 * 9.2 + 0.5 * 10.2,
                                          rel=0, abs=1e-12)
    assert r["class_lambda"] == 0.8  # 恰中点取低档（min 首见语义）
    steps = [0.4 + i * (4.2 - 0.4) / 60 for i in range(61)]
    gains = [_run("yagi_gain_nbs_tn688",
                  {"boom_length_lambda": round(s, 6)})["gain_dbd"]
             for s in steps]
    assert all(b >= a for a, b in pairwise(gains))


def test_g15_domain_and_output_filter() -> None:
    """端点外拒绝不外推；output 单选过滤；非法 output 拒绝。"""
    assert "不外推" in _run_err("yagi_gain_nbs_tn688",
                                {"boom_length_lambda": 0.39})
    assert "不外推" in _run_err("yagi_gain_nbs_tn688",
                                {"boom_length_lambda": 4.21})
    r = _run("yagi_gain_nbs_tn688",
             {"boom_length_lambda": 2.2, "output": "dbi"})
    assert round(r["gain_dbi"], 2) == 14.45 and r["gain_dbd"] is None
    r = _run("yagi_gain_nbs_tn688",
             {"boom_length_lambda": 2.2, "output": "dbd"})
    assert r["gain_dbd"] == 12.3 and r["gain_dbi"] is None
    _run_err("yagi_gain_nbs_tn688",
             {"boom_length_lambda": 2.2, "output": "bogus"})


# ═══ G15 键 2：yagi_geometry_nbs_tn688（B3/B4/B5/B6/B7）════════════════════

_B7 = [(0.4, 3), (0.8, 5), (1.2, 6), (2.2, 12), (3.2, 17), (4.2, 15)]


@pytest.mark.parametrize("cls,n_el", _B7)
def test_g15_b7_element_counts(cls: float, n_el: int) -> None:
    r = _run("yagi_geometry_nbs_tn688", {"class_lambda": cls, "f_ghz": 0.4})
    assert r["n_elements"] == n_el
    assert r["reflector_spacing_lambda"] == 0.2  # B3：Fig.1 实测最优（峰 2.6 dBd）
    assert "2.6" in r["note"]  # B3 增益口径注记在案
    # 跨键同源：档位增益与键 1 六档表逐位
    g = _run("yagi_gain_nbs_tn688", {"boom_length_lambda": cls})
    assert r["gain_dbd"] == g["gain_dbd"]
    assert r["gain_dbi"] == g["gain_dbi"]


def test_g15_b4_b5_example1_lengths_and_identity() -> None:
    """B4/B5：0.8λ 档例题 1（50.1MHz）——长度/修正单点+恒等复核（±0.003λ）。"""
    lam_m = C_MM_GHZ_TEST / 0.0501 / 1000.0  # 测试侧独立 c/f
    assert round(lam_m, 4) == 5.9839          # B5 恒等（原文口径）
    r = _run("yagi_geometry_nbs_tn688",
             {"class_lambda": 0.8, "f_ghz": 0.0501})
    assert r["lambda_m"] == pytest.approx(lam_m, rel=0, abs=1e-12)
    assert r["director_spacing_lambda"] == 0.2
    assert r["reflector_length_lambda"] == 0.485      # 未补偿（例题 Step2）
    assert r["director_length_lambda"] == 0.442
    assert r["boom_correction_lambda"] == 0.005       # 修正单点 D/λ=0.0085
    assert r["reflector_length_corrected_lambda"] == 0.490
    assert r["director_length_corrected_lambda"] == 0.447
    # 恒等复核：0.490λ=293.2cm vs 原文 293cm、0.447λ=267.5cm vs 原文 267cm
    tol_cm = 0.003 * lam_m * 100.0
    assert abs(0.490 * lam_m * 100.0 - 293.0) <= tol_cm
    assert abs(0.447 * lam_m * 100.0 - 267.0) <= tol_cm
    # 位置面：反射器 -0.2λ、有源元原点、三指向元 0.2λ 等距（米制）
    pos = r["element_positions_m"]
    assert pos["reflector_m"] == pytest.approx(-0.2 * lam_m, rel=0, abs=1e-12)
    assert pos["driven_m"] == 0.0
    assert pos["directors_m"] == [
        pytest.approx(0.2 * lam_m * (i + 1), rel=0, abs=1e-12)
        for i in range(3)]


def test_g15_b6_example2_geometry() -> None:
    """B6：4.2λ 档例题 2（827MHz）——λ/间距/总长恒等 + 单元数 15。"""
    lam_cm = C_MM_GHZ_TEST / 0.827 / 10.0  # mm→cm（测试侧独立 c/f）
    assert round(lam_cm, 2) == 36.25  # c/f 精确（原文印 36.3 系粗印）
    r = _run("yagi_geometry_nbs_tn688", {"class_lambda": 4.2, "f_ghz": 0.827})
    assert r["n_elements"] == 15
    assert r["gain_dbd"] == 14.2
    assert r["director_spacing_lambda"] == 0.308
    tol_cm = 0.003 * lam_cm
    assert abs(0.308 * lam_cm - 11.2) <= tol_cm   # 原文 11.2cm
    # 原文总长 152cm 系 4.2λ=152.25cm 的厘米位粗印（0.007λ）——用 0.01λ 容差
    assert abs(4.2 * lam_cm - 152.0) <= 0.01 * lam_cm
    pos = r["element_positions_m"]
    assert len(pos["directors_m"]) == 13          # 15 − 反射器 − 有源元
    assert pos["directors_m"][0] == pytest.approx(
        0.308 * lam_cm / 100.0, rel=0, abs=1e-12)


def test_g15_unverified_class_nulls_no_fabrication() -> None:
    """未文本验证档（如 1.2λ）：间距/长度 null+注记（禁编造）；位置面 null。"""
    r = _run("yagi_geometry_nbs_tn688", {"class_lambda": 1.2, "f_ghz": 0.4})
    assert r["director_spacing_lambda"] is None
    assert r["reflector_length_lambda"] is None
    assert r["director_length_lambda"] is None
    assert r["boom_correction_lambda"] is None
    assert r["element_positions_m"] is None
    assert "null" in r["note"] or "禁编造" in r["note"]


def test_g15_closed_enum_and_guards() -> None:
    """class 六档封闭枚举（1.0 拒绝）；f≤0 拒绝；d/λ≤0 拒绝、越合理域注记。"""
    assert "封闭枚举" in _run_err("yagi_geometry_nbs_tn688",
                                  {"class_lambda": 1.0, "f_ghz": 0.4})
    assert "封闭枚举" in _run_err("yagi_geometry_nbs_tn688",
                                  {"class_lambda": 2.0, "f_ghz": 0.4})
    _run_err("yagi_geometry_nbs_tn688", {"class_lambda": 0.8, "f_ghz": 0.0})
    _run_err("yagi_geometry_nbs_tn688",
             {"class_lambda": 0.8, "f_ghz": 0.4, "element_d_lambda": 0.0})
    r = _run("yagi_geometry_nbs_tn688",
             {"class_lambda": 0.8, "f_ghz": 0.4, "element_d_lambda": 0.1})
    assert r["warnings"], "d/λ 越合理域应带 warnings 注记"
    # 非基准 d/λ：修正单点不外推 → null+warning
    r2 = _run("yagi_geometry_nbs_tn688",
              {"class_lambda": 0.8, "f_ghz": 0.4, "element_d_lambda": 0.0042})
    assert r2["boom_correction_lambda"] is None
    assert r2["reflector_length_corrected_lambda"] is None
    assert r2["warnings"]


def test_g15_experimental_honesty_markers() -> None:
    """经验面诚实标注（规格包 §④）：note 含实测经验/非闭式字样，非闭式。"""
    for name, params in (
            ("yagi_gain_nbs_tn688", {"boom_length_lambda": 2.2}),
            ("yagi_geometry_nbs_tn688", {"class_lambda": 0.8, "f_ghz": 0.4})):
        r = _run(name, params)
        assert "实测经验" in r["note"] and "非闭式" in r["note"]


# ═══ 信封契约（ok/error 构造器路径，service 薄壳同证）══════════════════════

@pytest.mark.parametrize("name,params", [
    ("slot_stevenson_conductance",
     {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "offset_x_mm": 2.0}),
    ("slot_array_synthesis_resonant",
     {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "n_slots": 4,
      "weights": [1.0] * 4}),
    ("yagi_gain_nbs_tn688", {"boom_length_lambda": 2.2}),
    ("yagi_geometry_nbs_tn688", {"class_lambda": 0.8, "f_ghz": 0.4}),
])
def test_envelope_ok_path(name: str, params: dict) -> None:
    import json
    out = run_calculator(name, params)
    assert out["ok"] is True and "error" not in out
    json.dumps(out, allow_nan=False, ensure_ascii=False)  # JSON 进出契约


@pytest.mark.parametrize("name,params", [
    ("slot_stevenson_conductance",
     {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "g": 1.0}),
    ("yagi_gain_nbs_tn688", {"boom_length_lambda": 9.9}),
    ("yagi_geometry_nbs_tn688", {"class_lambda": 1.0, "f_ghz": 0.4}),
    ("slot_array_synthesis_resonant",
     {"f_ghz": 10.0, "a_mm": A_MM, "b_mm": B_MM, "n_slots": 1,
      "weights": [1.0]}),
])
def test_envelope_error_path(name: str, params: dict) -> None:
    import json
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error")
    json.dumps(out, allow_nan=False, ensure_ascii=False)
