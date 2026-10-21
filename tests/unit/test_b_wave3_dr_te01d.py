"""批 B Wave3 G9：圆柱介质谐振器 TE01δ 正解/反解单测（Cohn 磁壁超越方程）。

裁判口径（规格包 内部证据目录 ④，
2026-10-13 实现席独立复算+两处规格勘误，见规格文件勘误注记）：

- **锚值双路径**（#118）：实现路线=scipy brentq；独立第二路线=本文件
  纯二分求根（不同算法）+规格包独立复算值（D1-D5 六位小数）双源；
  两者 ≤1e-9（二分收敛限）互证。
- **规格勘误 1（同仓双源口径）**：material_characterization.courtney_f0_of_er
  径向条件为 J₁ 零点（3.8317，confined 全金属侧壁口径），本族磁壁口径为
  J₀ 零点（2.4048）——同仓互证=**方向锚**（f_磁壁贴面 < f_confined 恒
  成立）+ x01 常数与圆柱腔 TM010 同根钉，非逐位互证。
- **规格勘误 2（L→0 极限）**：式 D1 与式 D2 不存在 L→0 收敛——L→0 时
  式 D1 → 频窗上缘 c0·x01/(2πa)（实测单调趋近）而式 D2 → ∞；正确不变
  量=f_lo < f_TE01δ < f_贴面(D2) 严格（β<π/L 代数推得）+ L→0 单调趋近
  f_hi。
- **εr 标度破缺锚（D5）**：εr×4 → f0 比 0.501011（≠恰 0.5，空气份额）；
  式 D2 才是严格 ÷√εr（εr×4 → 恰 ÷2）——双模型分离性测试点。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from scipy.special import jn_zeros

from rfauto.core.calc_families.dr_te01d import (
    dr_te01d_cohn_f0,
    dr_te01d_design_size,
)
from rfauto.core.calc_families.waveguide_closed_form import (
    circular_cavity_mode_spectrum,
)
from rfauto.core.material_characterization import courtney_f0_of_er
from rfauto.service.calculator_service import run_calculator

C0 = 299792458.0
# D6：x01 常数测试侧独立求值（scipy jn_zeros，同 A2-C 独立常数范式）
X01 = float(jn_zeros(0, 1)[-1])
assert X01 == 2.4048255576957724

# 规格包独立复算锚（六位小数；全精度由本文件二分第二路线独立重算）
D1_SPEC_GHZ = 3.114682   # εr=38、D=15mm、L=7.5mm
D2_SPEC_GHZ = 4.083040   # 同几何端板贴面（式 D2）；比 0.7628
D3_SPEC_GHZ = 3.132377   # εr=81、D=10.6mm、L=4.6mm
D4_SPEC_GHZ = 2.733303   # εr=36.3、D=18.0mm、L=8.0mm
D5_SPEC_RATIO = 0.501011  # D1 几何、εr×4=152 的 f0 比（≠0.5）


def _bisect_cohn_f0_hz(er: float, a_m: float, l_m: float) -> float:
    """独立第二路线：式 D1 纯二分求根（无 scipy，基模支窗口内 200 轮）。"""
    kr = X01 / a_m
    f_lo = C0 * kr / (2.0 * math.pi * math.sqrt(er))
    f_hi = C0 * kr / (2.0 * math.pi)
    f_pole = C0 * math.sqrt(
        kr * kr + (math.pi / l_m) ** 2) / (2.0 * math.pi * math.sqrt(er))
    lo, hi = f_lo, min(f_hi, f_pole) * (1.0 - 1e-12)

    def g(f: float) -> float:
        k0 = 2.0 * math.pi * f / C0
        b2 = er * k0 * k0 - kr * kr
        a2 = kr * kr - k0 * k0
        beta = math.sqrt(b2) if b2 > 0.0 else 0.0
        alpha = math.sqrt(a2) if a2 > 0.0 else 0.0
        if beta == 0.0:
            return -1.0
        tan_term = math.tan(beta * l_m / 2.0)
        if alpha == 0.0:
            return tan_term
        return tan_term - alpha / beta

    assert g(lo) < 0.0 < g(hi)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if g(mid) > 0.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# ─── 锚值（D1-D5：实现 vs 二分第二路线 vs 规格包六位小数）─────────────────────


@pytest.mark.parametrize(
    ("er", "d_mm", "l_mm", "spec_ghz"),
    [(38.0, 15.0, 7.5, D1_SPEC_GHZ),
     (81.0, 10.6, 4.6, D3_SPEC_GHZ),
     (36.3, 18.0, 8.0, D4_SPEC_GHZ)],
)
def test_cohn_anchor_dual_path(er: float, d_mm: float, l_mm: float,
                               spec_ghz: float) -> None:
    out = dr_te01d_cohn_f0(d_mm, l_mm, er)
    f_impl = out["f0_ghz"]
    f_bisect = _bisect_cohn_f0_hz(er, d_mm * 1e-3 / 2.0, l_mm * 1e-3) / 1e9
    # 实现路线 vs 独立二分路线 ≤1e-9（#118 双路径）
    assert abs(f_impl - f_bisect) / f_bisect <= 1e-9
    # 规格包独立复算锚（六位小数，±1e-6 容差=规格粒度）
    assert abs(f_impl - spec_ghz) <= 1e-6


def test_plates_anchor_and_structural_identity() -> None:
    out = dr_te01d_cohn_f0(15.0, 7.5, 38.0)
    # D2 锚：规格包六位小数
    assert abs(out["f0_mw_plates_ghz"] - D2_SPEC_GHZ) <= 1e-6
    # 第二路线：测试侧独立闭式重算（≤1e-12 相对）
    a_m, l_m = 7.5e-3, 7.5e-3
    f_mw = C0 / (2.0 * math.pi * math.sqrt(38.0)) * math.sqrt(
        (X01 / a_m) ** 2 + (math.pi / l_m) ** 2) / 1e9
    assert abs(out["f0_mw_plates_ghz"] - f_mw) / f_mw <= 1e-12
    # 两模型比锚（自由 DR 低于贴面，规格包 0.7628）
    assert abs(out["f0_ghz"] / out["f0_mw_plates_ghz"] - 0.7628) <= 1e-4
    # 结构恒等式：式 D1 基模支 β=π/L 极点频率恰等于式 D2 → f_D1 < f_D2 严格
    assert out["f0_ghz"] < out["f0_mw_plates_ghz"]
    assert out["f_plates_over_cohn"] > 1.0


def test_x01_same_root_as_circular_cavity_tm010() -> None:
    out = dr_te01d_cohn_f0(15.0, 7.5, 38.0)
    assert out["x01"] == X01
    # 与圆柱腔 TM010 同根常数（waveguide_closed_form 用 J_m 零点 p=0）：
    # TM010 f = x01·c0/(2πa)，谱键输出按其内部精度 round——按其粒度比对
    spec = circular_cavity_mode_spectrum(
        radius_mm=10.0, length_mm=10.0, f_min_ghz=1.0, f_max_ghz=30.0)
    tm010 = next(m for m in spec["modes"] if m["mode"] == "TM010")
    f_exact = 299.792458 * X01 / (2.0 * math.pi * 10.0)
    assert abs(tm010["f_ghz"] - f_exact) <= 1e-8


def test_er_scaling_breaks_sqrt_for_cohn_strict_for_plates() -> None:
    # D5 锚：Cohn εr×4 → 比 0.501011（≠恰 0.5，空气份额标度破缺）
    f38 = dr_te01d_cohn_f0(15.0, 7.5, 38.0)["f0_ghz"]
    f152 = dr_te01d_cohn_f0(15.0, 7.5, 152.0)["f0_ghz"]
    ratio = f152 / f38
    assert abs(ratio - D5_SPEC_RATIO) <= 1e-6
    assert ratio > 0.5  # 破缺方向：高 εr 侧空气份额相对更显（比 >0.5）
    f_bisect = _bisect_cohn_f0_hz(152.0, 7.5e-3, 7.5e-3) / 1e9
    assert abs(f152 - f_bisect) / f_bisect <= 1e-9
    # 式 D2 才是严格 ÷√εr：εr×4 → 恰 ÷2（逐位级）
    p38 = dr_te01d_cohn_f0(15.0, 7.5, 38.0)["f0_mw_plates_ghz"]
    p152 = dr_te01d_cohn_f0(15.0, 7.5, 152.0)["f0_mw_plates_ghz"]
    assert p38 / p152 == 2.0


# ─── 边界与无效域 ─────────────────────────────────────────────────────────────


def test_er_boundary_exact_accept_and_reject() -> None:
    out_ok = run_calculator("dr_te01d_cohn_f0", {
        "diameter_mm": 15.0, "height_mm": 7.5, "epsilon_r": 2.0})
    assert out_ok["ok"] is True
    out_bad = run_calculator("dr_te01d_cohn_f0", {
        "diameter_mm": 15.0, "height_mm": 7.5, "epsilon_r": 1.999})
    assert out_bad["ok"] is False and out_bad.get("error")


def test_height_to_diameter_boundary_exact_reject() -> None:
    out = run_calculator("dr_te01d_design_size", {
        "epsilon_r": 38.0, "f0_ghz": 3.0, "height_to_diameter": 2.0})
    assert out["ok"] is False and "开区间" in (out.get("error") or "")
    out_lo = run_calculator("dr_te01d_design_size", {
        "epsilon_r": 38.0, "f0_ghz": 3.0, "height_to_diameter": 0.0})
    assert out_lo["ok"] is False


def test_tand_zero_returns_null_q() -> None:
    out = dr_te01d_cohn_f0(15.0, 7.5, 38.0)
    assert out["q_dielectric"] is None
    out2 = dr_te01d_cohn_f0(15.0, 7.5, 38.0, tan_delta=2e-4)
    assert out2["q_dielectric"] == 1.0 / 2e-4


def test_root_lies_in_window_with_monotone_char_eq() -> None:
    out = dr_te01d_cohn_f0(15.0, 7.5, 38.0)
    assert out["f_window_low_ghz"] < out["f0_ghz"] < out["f_window_high_ghz"]
    # 特征方程在根处残差为 0（求根精度级）
    assert out["char_eq_residual"] <= 1e-9


def test_l_ge_d_warning_not_rejection() -> None:
    raw = dr_te01d_cohn_f0(10.0, 12.0, 38.0)
    assert raw["f0_ghz"] > 0.0
    assert any("高阶" in w for w in raw["warnings"])


@pytest.mark.parametrize(
    "params",
    [{"diameter_mm": 0.0, "height_mm": 7.5, "epsilon_r": 38.0},
     {"diameter_mm": 15.0, "height_mm": -1.0, "epsilon_r": 38.0},
     {"diameter_mm": 15.0, "height_mm": 7.5, "epsilon_r": 1.9},
     {"diameter_mm": 15.0, "height_mm": 7.5, "epsilon_r": 38.0,
      "tan_delta": -0.001},
     {"diameter_mm": float("nan"), "height_mm": 7.5, "epsilon_r": 38.0}],
)
def test_cohn_invalid_domain_explicit(params: dict) -> None:
    out = run_calculator("dr_te01d_cohn_f0", params)
    assert out["ok"] is False and out.get("error"), params


# ─── 反解键：名义回代/roundtrip/单调性/警告 ───────────────────────────────────


def test_design_nominal_roundtrip_d1_anchor() -> None:
    # D1 锚几何回代：εr=38/f0(D1 全精度)/h=0.5 → D=15/L=7.5
    f_d1 = _bisect_cohn_f0_hz(38.0, 7.5e-3, 7.5e-3) / 1e9
    out = dr_te01d_design_size(38.0, f_d1, 0.5)
    assert abs(out["diameter_mm"] - 15.0) / 15.0 <= 1e-9
    assert abs(out["height_mm"] - 7.5) / 7.5 <= 1e-9
    assert out["roundtrip_rel_residual"] <= 1e-10
    # 随行贴面对照频率与 D2 锚一致
    assert abs(out["f0_mw_plates_ghz"] - D2_SPEC_GHZ) <= 1e-6


def test_design_h_ge_1_warning() -> None:
    out = dr_te01d_design_size(38.0, 3.0, 1.2)
    assert any("高阶" in w for w in out["warnings"])


def test_design_f0_monotone_in_d_over_grid() -> None:
    # f0(D) 严格单调降（h=0.4, εr=38 三点）
    freqs = []
    for d_mm in (10.0, 15.0, 30.0):
        freqs.append(dr_te01d_cohn_f0(d_mm, 0.4 * d_mm, 38.0)["f0_ghz"])
    assert freqs[0] > freqs[1] > freqs[2]


# ─── 极限行为（规格勘误 2 的正确不变量）────────────────────────────────────────


def test_thin_limit_approaches_window_edge_not_plates_value() -> None:
    # L→0：f_D1 单调升趋近频窗上缘 c0·x01/(2πa)，而式 D2 → ∞（不收敛）
    f_hi = C0 * X01 / (2.0 * math.pi * 7.5e-3) / 1e9
    prev_f = None
    prev_p = None
    for l_mm in (3.0, 1.0, 0.3, 0.1):
        out = dr_te01d_cohn_f0(15.0, l_mm, 38.0)
        f, p = out["f0_ghz"], out["f0_mw_plates_ghz"]
        assert f < f_hi  # 恒在频窗内
        if prev_f is not None:
            assert f > prev_f  # L 减小 → f 单调升（趋近窗缘）
        if prev_p is not None:
            assert p > prev_p  # 贴面口径 ∝1/L 单调发散
        prev_f, prev_p = f, p
    assert p > 10.0 * f_hi  # L=0.1mm 时贴面口径已发散一个量级
    # L→∞：f_D1 单调降趋近频窗下缘
    f_lo = C0 * X01 / (2.0 * math.pi * math.sqrt(38.0) * 7.5e-3) / 1e9
    prev = None
    for l_mm in (7.5, 30.0, 100.0):
        f = dr_te01d_cohn_f0(15.0, l_mm, 38.0)["f0_ghz"]
        assert f > f_lo
        if prev is not None:
            assert f < prev
        prev = f


def test_free_dr_always_below_courtney_confined_cross_model() -> None:
    # 同仓双模型方向锚（规格勘误 1）：磁壁贴面(J0) < confined 全金属侧壁(J1)
    out = dr_te01d_cohn_f0(15.0, 7.5, 38.0)
    f_confined = courtney_f0_of_er(38.0, 7.5e-3, 7.5e-3) / 1e9
    assert out["f0_mw_plates_ghz"] < out["f0_ghz"] * 2  # sanity：同量级
    assert out["f0_mw_plates_ghz"] < f_confined  # J0 磁壁 < J1 confined
    assert f_confined > out["f0_ghz"]


# ─── 信封 ─────────────────────────────────────────────────────────────────────


def test_service_envelope_ok_and_error() -> None:
    ok = run_calculator("dr_te01d_cohn_f0", {
        "diameter_mm": 15.0, "height_mm": 7.5, "epsilon_r": 38.0})
    assert ok["ok"] is True and ok["calculator"] == "dr_te01d_cohn_f0"
    ok2 = run_calculator("dr_te01d_design_size", {
        "epsilon_r": 38.0, "f0_ghz": 3.1146824935345903,
        "height_to_diameter": 0.5})
    assert ok2["ok"] is True
    err = run_calculator("dr_te01d_design_size", {
        "epsilon_r": 38.0, "f0_ghz": 0.0})
    assert err["ok"] is False and err.get("error")
