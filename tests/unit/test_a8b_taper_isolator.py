"""架构批 A8-B 席锚树：taper_classic 两键（经典渐变线线性/指数剖面频响/
综合）+ isolator_circulator 两键（隔离器/环行器理想 S 口径）。

数值断言口径（#118 不自证——闭式测试侧独立重解/教科书极限恒等/异构路线
互证/判废对照，不用实现侧公式互证自身）：
- 指数剖面：|Γ|=(|δ|/2)|sinc(βL)| 测试侧纯 math 重算逐位 1e-12；测试侧
  独立 Simpson 数值积分（无 scipy）互证 ≤1e-9；βL=π sinc 零点 |Γ|≤1e-12；
  βL→0 阶跃极限 |δ|/2。
- 线性剖面：Ei 闭式 vs 测试侧独立 Simpson 剖面核积分 ≤1e-9（实现侧
  scipy.expi 路线与测试侧手写 Simpson 异构）；剖面反转 |Γ| 不变对称
  1e-12；第一旁瓣 (0,π) 单调下降。
- 综合：ρ_max@f_min 反解 → 频响回代 |Γ(f_min)|=ρ 1e-9（两剖面）；指数
  剖面测试侧二分法独立解 sinc 方程对照 ≤1e-6；第一瓣通带上界
  f_max=π·f_min/x* 恒等式；半长判废 |Γ|>ρ；ρ≥|δ|/2 阶跃极限显式拒绝。
- 隔离器：理想极限档 canonical [[0,0],[1,0]] 逐位；dB 参数化
  10^(−dB/20) 测试侧重算 1e-12；无源性守卫违约显式拒绝（理想无耗+有限
  回损必违约的物理事实）；IL=Iso 互易退化档 S 对称；spec.reciprocal
  is False 豁免位钉。
- 环行器：理想极限档 cw 置换矩阵逐位（S21=S32=S13=1，与
  circulator_synthesis SENSE_FORWARD 同布局独立核对）；sense 翻转恒等式
  S_ccw=S_cwᵀ 逐位（有耗档）；总能量 Σ|S|²=3(γ²+c²+i²) 测试侧重算；
  无耗+零隔离违约酉性守卫拒绝；spec.reciprocal is False。
- 新键 description 首行"中文名：全角冒号"形态门（中文名含 CJK ≤24 字符）。
"""

from __future__ import annotations

import cmath
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_C0_GHZ_MM = 299.792458


def _run(name: str, **params: object) -> dict:
    out = run_calculator(name, params)
    assert out["ok"], f"{name} 失败: {out.get('error')!r}"
    return out["result"]


def _fail(name: str, **params: object) -> None:
    out = run_calculator(name, params)
    assert out["ok"] is False and out.get("error"), (
        f"{name}({params}) 应显式拒绝，得到 ok={out.get('ok')!r}")


NEW_KEYS = (
    "classic_taper_response", "classic_taper_synthesize",
    "isolator_ideal_sparams", "circulator_ideal_sparams")


# ─── 描述形态门（R5 §①：中文名全由 description 自带）────────────────────────

@pytest.mark.parametrize("key", NEW_KEYS)
def test_description_zh_head_form(key: str) -> None:
    import re

    spec = CALCULATOR_REGISTRY.get(key)
    head = re.split(r"[：:]", str(spec.description or ""))[0].strip()
    assert head and re.search(r"[\u4e00-\u9fff]", head)
    assert len(head) <= 24, f"{key} 中文名超 24 字符: {head!r}"


# ─── 测试侧独立闭式与数值路线（#118：与实现侧异构）───────────────────────────

def _beta_l(f_ghz: float, length_mm: float, v_f: float = 1.0) -> float:
    return 2.0 * math.pi * f_ghz * length_mm / (_C0_GHZ_MM * v_f)


def _gamma_exp_ref(x_bl: float, z1: float, z2: float) -> float:
    """指数剖面闭式测试侧重算：|Γ|=(|δ|/2)|sinc(βL)|，纯 math。"""
    delta = math.log(z2 / z1)
    if x_bl == 0.0:
        return abs(delta) / 2.0
    return abs(delta) / 2.0 * abs(math.sin(x_bl) / x_bl)


def _simpson_gamma(z1: float, z2: float, profile: str, x_bl: float,
                   n: int = 40_001) -> float:
    """剖面核 Γ=∫₀¹ K(u)·e^(−2j·x_bl·u) du 的测试侧独立复合 Simpson
    （无 scipy——与实现侧闭式/实现侧 simpson 均异构）。"""
    assert n % 2 == 1
    h = 1.0 / (n - 1)

    def kernel(u: float) -> complex:
        if profile == "exponential":
            return math.log(z2 / z1) / 2.0
        return 0.5 * (z2 - z1) / (z1 + (z2 - z1) * u)

    total = complex(0.0)
    for i in range(n):
        u = i * h
        w = 1 if i in (0, n - 1) else (4 if i % 2 == 1 else 2)
        total += w * kernel(u) * cmath.exp(-2j * x_bl * u)
    return abs(total * h / 3.0)


def _sinc_inv_half(c_target: float) -> float:
    """测试侧二分法解 sinc(x)=c_target（x∈(0,π) 单调下降，指数剖面综合
    独立求根路线）。"""
    lo, hi = 1e-12, math.pi - 1e-12
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if math.sin(mid) / mid > c_target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _s_json(row: list) -> list[list[complex]]:
    return [[complex(c["re"], c["im"]) for c in r] for r in row]


# ─── 经典渐变线频响键 ────────────────────────────────────────────────────────

class TestClassicTaperResponse:
    def test_exponential_closed_form_vs_testside(self):
        """指数剖面：闭式 vs 测试侧 sinc 重算逐位 1e-12 + 独立 Simpson
        互证 ≤1e-9（βL∈(0.3, 9.4) 六点含第二瓣）。"""
        z1, z2, length = 50.0, 100.0, 30.0
        freqs = [x * _C0_GHZ_MM / (2 * math.pi * length)
                 for x in (0.3, 1.2, 2.5, math.pi, 5.5, 9.4)]
        r = _run("classic_taper_response", z1_ohm=z1, z2_ohm=z2,
                 length_mm=length, freq_ghz=freqs, profile="exponential")
        for x_bl, mag in zip(r["beta_l"], r["gamma_mag"], strict=True):
            assert mag == pytest.approx(
                _gamma_exp_ref(x_bl, z1, z2), rel=1e-11, abs=1e-12)
            assert mag == pytest.approx(
                _simpson_gamma(z1, z2, "exponential", x_bl),
                rel=1e-9, abs=1e-12)

    def test_linear_ei_vs_independent_simpson(self):
        """线性剖面：Ei 闭式 vs 测试侧独立 Simpson 剖面核积分 ≤1e-9
        （跨阻抗比/长度/频点网格）。"""
        for z1, z2 in ((50.0, 100.0), (100.0, 50.0), (15.0, 75.0)):
            length = 24.0
            freqs = [x * _C0_GHZ_MM / (2 * math.pi * length)
                     for x in (0.4, 1.8, 3.0, 6.0)]
            r = _run("classic_taper_response", z1_ohm=z1, z2_ohm=z2,
                     length_mm=length, freq_ghz=freqs, profile="linear")
            for x_bl, mag in zip(r["beta_l"], r["gamma_mag"], strict=True):
                assert mag == pytest.approx(
                    _simpson_gamma(z1, z2, "linear", x_bl),
                    rel=1e-9, abs=1e-12)

    def test_step_limit_and_envelope(self):
        """βL→0 阶跃极限 |Γ|→|δ|/2（两剖面，rel 1e-9）；包络上界
        |Γ|≤|δ|/2 全频成立；第一旁瓣内单调下降。"""
        z1, z2, length = 50.0, 100.0, 30.0
        limit = abs(math.log(z2 / z1)) / 2.0
        # βL=1e-5 → sinc 相对偏差 (1e-5)²/6≈1.7e-11 < rel 1e-9 容差
        f_low = 1e-5 * _C0_GHZ_MM / (2 * math.pi * length)
        for profile in ("exponential", "linear"):
            r = _run("classic_taper_response", z1_ohm=z1, z2_ohm=z2,
                     length_mm=length, freq_ghz=[f_low], profile=profile)
            assert r["gamma_mag"][0] == pytest.approx(limit, rel=1e-9)
            assert r["envelope_bound_ok"] is True
            assert r["step_reflection_limit"] == pytest.approx(
                limit, rel=1e-12)
        # 第一旁瓣 (0,π) 单调下降（βL=0.5..2.5 rad 五点）
        freqs = [x * _C0_GHZ_MM / (2 * math.pi * length)
                 for x in (0.5, 1.0, 1.5, 2.0, 2.5)]
        r = _run("classic_taper_response", z1_ohm=z1, z2_ohm=z2,
                 length_mm=length, freq_ghz=freqs, profile="linear")
        mags = r["gamma_mag"]
        assert mags == sorted(mags, reverse=True)

    def test_exponential_sinc_zero(self):
        """βL=π sinc 零点：|Γ|≤1e-12（f=C/(2L) 精确常数链）。"""
        length = 30.0
        f_pi = _C0_GHZ_MM / (2.0 * length)
        r = _run("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
                 length_mm=length, freq_ghz=[f_pi], profile="exponential")
        assert abs(r["beta_l"][0] - math.pi) <= 1e-9
        assert r["gamma_mag"][0] <= 1e-12

    def test_profile_reversal_symmetry_and_z_sample(self):
        """剖面反转（z1↔z2）|Γ| 逐点不变 1e-12；剖面样本端点=z1/z2 精确。"""
        length = 20.0
        freqs = [1.0, 4.0, 9.0]
        r1 = _run("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
                  length_mm=length, freq_ghz=freqs, profile="exponential")
        r2 = _run("classic_taper_response", z1_ohm=100.0, z2_ohm=50.0,
                  length_mm=length, freq_ghz=freqs, profile="exponential")
        for a, b in zip(r1["gamma_mag"], r2["gamma_mag"], strict=True):
            assert abs(a - b) <= 1e-12
        assert r1["z_profile_ohm"][0] == pytest.approx(50.0, rel=1e-12)
        assert r1["z_profile_ohm"][-1] == pytest.approx(100.0, rel=1e-12)
        r3 = _run("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
                  length_mm=length, freq_ghz=freqs, profile="linear")
        assert r3["z_profile_ohm"][0] == pytest.approx(50.0, rel=1e-12)
        assert r3["z_profile_ohm"][-1] == pytest.approx(100.0, rel=1e-12)

    def test_guards(self):
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=50.0,
              length_mm=30.0, freq_ghz=[1.0])  # z1==z2 无渐变
        _fail("classic_taper_response", z1_ohm=0.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[1.0])
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=-100.0,
              length_mm=30.0, freq_ghz=[1.0])
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=0.0, freq_ghz=[1.0])
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[])
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[0.0])
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[1.0], profile="bogus")
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[1.0], v_f=0.0)
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[1.0], v_f=1.5)
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[1.0], n_quad=50)
        _fail("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
              length_mm=30.0, freq_ghz=[1.0], n_profile=3)


# ─── 经典渐变线综合键 ────────────────────────────────────────────────────────

class TestClassicTaperSynthesize:
    def test_roundtrip_response_both_profiles(self):
        """综合→频响回代：|Γ(f_min)|=rho_max 1e-9（两剖面）；半长判废
        |Γ|>rho（设计点更短=电长度减半落第一瓣单调段上游）。"""
        for profile in ("exponential", "linear"):
            s = _run("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
                     f_min_ghz=2.0, rho_max=0.05, profile=profile)
            r = _run("classic_taper_response", z1_ohm=50.0, z2_ohm=100.0,
                     length_mm=s["length_mm"], freq_ghz=[2.0],
                     profile=profile)
            assert abs(r["gamma_mag"][0] - 0.05) <= 1e-9
            assert s["achieved_residual"] <= 1e-12
            # 半长判废：βL 减半 → |Γ| 上移（第一瓣单调段）
            r_half = _run("classic_taper_response", z1_ohm=50.0,
                          z2_ohm=100.0, length_mm=s["length_mm"] / 2.0,
                          freq_ghz=[2.0], profile=profile)
            assert r_half["gamma_mag"][0] > 0.05

    def test_exponential_independent_bisection(self):
        """指数剖面综合 vs 测试侧二分法独立解 sinc 方程 ≤1e-6（长度）。"""
        z1, z2, rho = 50.0, 100.0, 0.05
        c_target = 2.0 * rho / abs(math.log(z2 / z1))
        x_ref = _sinc_inv_half(c_target)
        s = _run("classic_taper_synthesize", z1_ohm=z1, z2_ohm=z2,
                 f_min_ghz=2.0, rho_max=rho, profile="exponential")
        beta_min = 2.0 * math.pi * 2.0 / _C0_GHZ_MM
        assert abs(s["length_mm"] - x_ref / beta_min) <= 1e-6

    def test_first_lobe_passband_bound(self):
        """第一瓣通带上界恒等式 f_max=π·f_min/x*（1e-9）；预览点全落第一
        瓣内且 |Γ|≤ρ、单调不升。"""
        s = _run("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
                 f_min_ghz=2.0, rho_max=0.05, profile="exponential")
        x_star = s["beta_l_at_f_min"]
        assert s["f_passband_max_ghz_estimate"] == pytest.approx(
            math.pi / x_star * 2.0, rel=1e-9)
        mags = [p["gamma_mag"] for p in s["response_preview"]]
        assert all(m <= 0.05 + 1e-12 for m in mags)
        assert mags == sorted(mags, reverse=True)
        assert s["response_preview"][0]["gamma_mag"] == pytest.approx(
            0.05, rel=1e-9)

    def test_step_limit_degenerate_guard(self):
        """ρ≥|δ|/2 阶跃极限显式拒绝（零长即可满足）；ρ≤0 拒绝。"""
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=abs(math.log(2.0)) / 2.0)
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=0.4)
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=0.0)
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=-0.05)

    def test_guards(self):
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=50.0,
              f_min_ghz=2.0, rho_max=0.05)  # z1==z2
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=0.0, rho_max=0.05)
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=0.05, profile="bogus")
        _fail("classic_taper_synthesize", z1_ohm=50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=0.05, v_f=1.2)
        _fail("classic_taper_synthesize", z1_ohm=-50.0, z2_ohm=100.0,
              f_min_ghz=2.0, rho_max=0.05)


# ─── 隔离器理想 S 键 ─────────────────────────────────────────────────────────

class TestIsolatorIdeal:
    def test_canonical_ideal_limit(self):
        """理想极限档（全缺省）：S=[[0,0],[1,0]] canonical 逐位；ideal 标
        志与非互易度字段。"""
        r = _run("isolator_ideal_sparams")
        s = _s_json(r["s_matrix"])
        assert s[0][0] == 0 and s[0][1] == 0
        assert s[1][0] == 1 and s[1][1] == 0
        assert r["ideal_limit"] is True
        assert r["nonreciprocity_db"] is None
        # 口 1 前向全通 → 功率预算恰饱和（余量 0）；口 2 反向全隔离 →
        # 预算空闲（余量 1）
        assert r["port1_power_margin"] == pytest.approx(0.0, abs=1e-15)
        assert r["port2_power_margin"] == pytest.approx(1.0, abs=1e-15)

    def test_db_parameterization_independent(self):
        """dB 参数化：s21/s12/s11=10^(−dB/20) 测试侧重算 1e-12；非互易度
        =Iso−IL 恒等式。"""
        il, iso, rl = 0.5, 25.0, 20.0
        r = _run("isolator_ideal_sparams", il_db=il, isolation_db=iso,
                 rl_db=rl)
        s = _s_json(r["s_matrix"])
        g, c, i_rev = (10 ** (-rl / 20.0), 10 ** (-il / 20.0),
                       10 ** (-iso / 20.0))
        assert abs(s[1][0] - c) <= 1e-12
        assert abs(s[0][1] - i_rev) <= 1e-12
        assert abs(s[0][0] - g) <= 1e-12 and abs(s[1][1] - g) <= 1e-12
        assert r["nonreciprocity_db"] == pytest.approx(iso - il, rel=1e-12)
        assert r["ideal_limit"] is False
        assert r["reciprocal_degenerate"] is False
        # 无源性余量测试侧重算
        assert r["port1_power_margin"] == pytest.approx(
            1.0 - g * g - c * c, rel=1e-12, abs=1e-15)
        assert r["port2_power_margin"] == pytest.approx(
            1.0 - g * g - i_rev * i_rev, rel=1e-12, abs=1e-15)

    def test_reciprocal_degenerate_symmetric(self):
        """IL=Iso 互易退化档：S 对称（s12=s21 逐位）+标志位。"""
        r = _run("isolator_ideal_sparams", il_db=4.0, isolation_db=4.0)
        s = _s_json(r["s_matrix"])
        assert r["reciprocal_degenerate"] is True
        assert s[0][1] == s[1][0]
        assert r["nonreciprocity_db"] == pytest.approx(0.0, abs=1e-12)

    def test_passivity_violation_rejected(self):
        """无源性守卫：理想无耗+有限回损/隔离组合必违约 → 显式拒绝（耗散
        必须去某处的物理事实）。"""
        _fail("isolator_ideal_sparams", il_db=0.0, isolation_db=40.0,
              rl_db=0.0)  # γ=1 全反射+无耗前向 → 2>1
        _fail("isolator_ideal_sparams", il_db=0.0, isolation_db=40.0,
              rl_db=3.0)  # γ=0.708²+c² >1
        _fail("isolator_ideal_sparams", il_db=0.0, isolation_db=0.0,
              rl_db=3.0)  # c=i=1 全通+全反
        # 合法有耗档对照（同参数放低回损后过守卫）
        r = _run("isolator_ideal_sparams", il_db=1.0, isolation_db=20.0,
                 rl_db=20.0)
        assert r["port1_power_margin"] > 0.0

    def test_reciprocal_flag_false(self):
        """豁免位钉：spec.reciprocal is False（非互易铁氧体件）。"""
        assert CALCULATOR_REGISTRY.get(
            "isolator_ideal_sparams").reciprocal is False

    def test_guards(self):
        _fail("isolator_ideal_sparams", il_db=-0.5)
        _fail("isolator_ideal_sparams", isolation_db=-25.0)
        _fail("isolator_ideal_sparams", rl_db=-20.0)
        _fail("isolator_ideal_sparams", il_db="x")


# ─── 环行器理想 S 键 ─────────────────────────────────────────────────────────

class TestCirculatorIdeal:
    def test_canonical_cw_permutation(self):
        """理想极限档 cw：S21=S32=S13=1 置换矩阵逐位（1→2→3→1）；总能量
        =3；与 circulator_synthesis SENSE_FORWARD 布局独立核对。"""
        r = _run("circulator_ideal_sparams", sense="cw")
        s = _s_json(r["s_matrix"])
        assert s[1][0] == 1 and s[2][1] == 1 and s[0][2] == 1
        assert s[0][1] == 0 and s[1][2] == 0 and s[2][0] == 0
        assert all(s[i][i] == 0 for i in range(3))
        assert r["total_energy"] == pytest.approx(3.0, rel=1e-12)
        assert r["circulation_path"] == "1→2→3→1"
        assert r["ideal_limit"] is True

    def test_sense_flip_transpose_identity(self):
        """sense 翻转恒等式 S_ccw=S_cwᵀ 逐位（有耗参数档，构造级）。"""
        kw = dict(il_db=0.3, isolation_db=22.0, rl_db=18.0)
        cw = _run("circulator_ideal_sparams", sense="cw", **kw)
        ccw = _run("circulator_ideal_sparams", sense="ccw", **kw)
        s_cw = _s_json(cw["s_matrix"])
        s_ccw = _s_json(ccw["s_matrix"])
        for i in range(3):
            for j in range(3):
                assert s_ccw[i][j] == s_cw[j][i]
        assert ccw["circulation_path"] == "1→3→2→1"

    def test_db_parameterization_independent(self):
        """dB 参数化：cw 环行项/隔离项/对角=10^(−dB/20) 测试侧重算
        1e-12；总能量=3(γ²+c²+i²) 恒等式。"""
        il, iso, rl = 0.5, 25.0, 20.0
        r = _run("circulator_ideal_sparams", sense="cw", il_db=il,
                 isolation_db=iso, rl_db=rl)
        s = _s_json(r["s_matrix"])
        g, c, i_rev = (10 ** (-rl / 20.0), 10 ** (-il / 20.0),
                       10 ** (-iso / 20.0))
        for pair in ((1, 0), (2, 1), (0, 2)):
            assert abs(s[pair[0]][pair[1]] - c) <= 1e-12
        for pair in ((0, 1), (1, 2), (2, 0)):
            assert abs(s[pair[0]][pair[1]] - i_rev) <= 1e-12
        assert all(abs(s[i][i] - g) <= 1e-12 for i in range(3))
        assert r["total_energy"] == pytest.approx(
            3.0 * (g * g + c * c + i_rev * i_rev), rel=1e-12)
        assert r["nonreciprocity_db"] == pytest.approx(iso - il, rel=1e-12)
        assert r["port_power_margin"] == pytest.approx(
            1.0 - g * g - c * c - i_rev * i_rev, rel=1e-12, abs=1e-15)

    def test_reciprocal_degenerate_and_unitary_limit(self):
        """IL=Iso 退化档 S 对称；理想极限档酉性（S†S=I）测试侧核对。"""
        r = _run("circulator_ideal_sparams", sense="cw", il_db=4.0,
                 isolation_db=4.0)
        s = _s_json(r["s_matrix"])
        assert r["reciprocal_degenerate"] is True
        assert all(s[i][j] == s[j][i] for i in range(3) for j in range(3))
        # 理想极限档：置换矩阵酉性（P†P=I 逐位）
        r0 = _run("circulator_ideal_sparams", sense="cw")
        s0 = _s_json(r0["s_matrix"])
        for i in range(3):
            for j in range(3):
                dot = sum(s0[k][i].conjugate() * s0[k][j]
                          for k in range(3))
                expect = 1.0 if i == j else 0.0
                assert abs(dot - expect) <= 1e-12

    def test_passivity_violation_rejected(self):
        """无耗+有限隔离组合违约酉性 → 显式拒绝（γ²+c²+i²>1）。"""
        _fail("circulator_ideal_sparams", sense="cw", il_db=0.0,
              isolation_db=40.0, rl_db=0.0)  # γ=1+c² >1
        _fail("circulator_ideal_sparams", sense="cw", il_db=0.0,
              isolation_db=0.0, rl_db=30.0)  # c=i=1 → 2>1
        _fail("circulator_ideal_sparams", sense="cw", il_db=0.5,
              isolation_db=3.0, rl_db=3.0)  # c²+i²+γ² >1
        r = _run("circulator_ideal_sparams", sense="cw", il_db=0.5,
                 isolation_db=25.0, rl_db=20.0)  # 合法档对照
        assert r["port_power_margin"] > 0.0

    def test_reciprocal_flag_false(self):
        """豁免位钉：spec.reciprocal is False（非互易铁氧体件）。"""
        assert CALCULATOR_REGISTRY.get(
            "circulator_ideal_sparams").reciprocal is False

    def test_guards(self):
        _fail("circulator_ideal_sparams", sense="bogus")
        _fail("circulator_ideal_sparams", sense=1)
        _fail("circulator_ideal_sparams", il_db=-0.5)
        _fail("circulator_ideal_sparams", isolation_db=-25.0)
        _fail("circulator_ideal_sparams", rl_db=-20.0)
