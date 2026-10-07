"""AP-6/AP-8 ITU 大气/雨衰包锚测试（规格深案 §A-8）。

批次口径（任务书预声明 + #122 判据先写后跑）：

- **AP-6 骨架批**：式面逐式对照官方 PDF 视觉核verify（证据 runs/ap6），
  系数表空哨位时公共函数域守卫后 ValueError 拒产数（铁律 7）；式机件
  锚点用合成常数注入（零 ITU 值）。
- **AP-8 录入批（2026-10-02）**：P.676-13 Table 1 全 44 行 / Table 2 全
  35 行（含 1780GHz 伪线）/ P.838-3 Tables 1-4 四组系数逐值落表（证据
  runs/ap8/：文本层机械抽取 + 前席 dump 逐 token 对拍 all-equal 553 值
  + PNG 视觉抽检；P.838-3 另经官方 Table 5 全量 116 频点对拍 max rel
  dev 0.112%）。has_676_tables()/has_838_coeffs() 转 True，**量级锚
  skipif 自动转正且窗值不回调**（窗=AP-6 批先于任何落表钉死，#122）：
  γO(60GHz,1013hPa,15℃,干空气)∈[11.25,18.75]dB/km（≈15±25%）、
  γW(22.235GHz,7.5g/m³,15℃)∈[0.133,0.247]dB/km（≈0.19±30%，湿减干）。
- P.837 R0.01 仍 UNVERIFIED（ITU 数据文件不捆绑，PV-011）——占位
  显式 ValueError 拒产数的钉保留。
- 录入后新增：谱线共振结构锚（60GHz 带峰位/带翼比、118.75GHz O2 线、
  183.31GHz H2O 线局部极大）与 P.838-3 Table 5 spot 值引用对拍
  （代表频点 ≤0.5%；全量 116 点对拍在 runs/ap8/crosscheck_838.csv）。
- 机件锚点（合成常数，闭式恒等）：线形共振 F(f0)=1/Δf+Δf/((2f0)²+Δf²)、
  离谐精确点、式(6b) O2 Zeeman 地板/H2O Doppler 展宽恒等、式(7) δ 点值、
  式(8/9) 干连续谱 Debye 半功率点+低频线性极限、式(1)/(2a)/(2b) 装配
  恒等、P.838-3 单 Gauss 峰位/幂律线性档/γ_R=k·R^α 恒等。
- 无雨 R=0 → 0.0 不触系数守卫（无雨无衰减是零元，非产数路径）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import itu_atmosphere as itu
from rfauto.core.itu_atmosphere import (
    OxygenLine,
    RainCoeffs,
    WaterLine,
    data_status,
    gamma_gasses_db_per_km,
    gamma_rain_db_per_km,
    rain_attenuation_db,
    rain_rate_r001_mmh,
)

# ─── 状态与录入契约（AP-8 录入批后：676/838 verified，837 占位）──────────────


def test_data_status_entry_batch():
    st = data_status()
    assert set(st) == {
        "p676_o2_table1", "p676_wv_table2", "p838_rain_coeffs", "p837_r001_coeffs"
    }
    assert st["p676_o2_table1"] == "verified"
    assert st["p676_wv_table2"] == "verified"
    assert st["p838_rain_coeffs"] == "verified"
    assert st["p837_r001_coeffs"] == "unverified"  # PV-011：数据文件不捆绑，占位如实
    assert itu.has_676_tables() is True
    assert itu.has_838_coeffs() is True


def test_entered_table_shapes_and_source_counts():
    """落表形状钉：O2 44 行 / H2O 35 行（含 1780 伪线）/ 838 双极化齐备。"""
    assert len(itu._O2_LINES) == 44
    assert len(itu._WV_LINES) == 35
    assert itu._WV_LINES[-1].f0_ghz == 1780.0  # 伪线末行
    # 首末行端点值（印刷值逐位，防录入错位）
    assert itu._O2_LINES[0].f0_ghz == 50.474214
    assert itu._O2_LINES[-1].f0_ghz == 834.145546
    assert itu._WV_LINES[0].f0_ghz == 22.235080
    assert set(itu._RAIN_COEFFS) == {"h", "v"}


def test_table_entry_contracts():
    """录入批契约钉：NamedTuple 字段名与 P.676-13/P.838-3 表列一一对应。"""
    assert OxygenLine._fields == ("f0_ghz", "a1", "a2", "a3", "a4", "a5", "a6")
    assert WaterLine._fields == ("f0_ghz", "b1", "b2", "b3", "b4", "b5", "b6")
    assert RainCoeffs._fields == (
        "k_a", "k_b", "k_c", "k_m", "k_c0",
        "a_a", "a_b", "a_c", "a_m", "a_c0",
    )


# ─── 域守卫（先于系数守卫触发；bool 显式拒收 #364④）──────────────────────────


@pytest.mark.parametrize(
    "args, kwargs, frag",
    [
        ((0.0, 1013.25, 288.15, 0.0), {}, "f_hz 有效域"),
        ((1500e9, 1013.25, 288.15, 0.0), {}, "f_hz 有效域"),
        ((60e9, 0.0, 288.15, 0.0), {}, "p_hpa"),
        ((60e9, 1013.25, 0.0, 0.0), {}, "t_k"),
        ((60e9, 1013.25, 288.15, -0.1), {}, "rho_wv_g_m3"),
        ((True, 1013.25, 288.15, 0.0), {}, "bool"),
        ((float("nan"), 1013.25, 288.15, 0.0), {}, "有限数"),
    ],
)
def test_gas_domain_guards_before_unverified(args, kwargs, frag):
    with pytest.raises(ValueError, match=frag):
        gamma_gasses_db_per_km(*args, **kwargs)


@pytest.mark.parametrize(
    "args, kwargs, frag",
    [
        ((0.5, 5.0), {}, "f_ghz 有效域"),
        ((1001.0, 5.0), {}, "f_ghz 有效域"),
        ((10.0, -0.1), {}, "rain_rate_mmh"),
        ((10.0, 5.0), {"pol": "x"}, "pol"),
        ((True, 5.0), {}, "bool"),
    ],
)
def test_rain_domain_guards_before_unverified(args, kwargs, frag):
    with pytest.raises(ValueError, match=frag):
        gamma_rain_db_per_km(*args, **kwargs)


def test_path_len_guard_and_boundary_frequencies_produce():
    with pytest.raises(ValueError, match="path_len_km"):
        rain_attenuation_db(10.0, 5.0, 0.0)
    # 域边界含端点（1 与 1000 GHz）落表后产有限正数（AP-8 前拒 UNVERIFIED）
    for f in (1.0, 1000.0):
        g = gamma_rain_db_per_km(f, 5.0)
        assert math.isfinite(g) and g > 0.0


# ─── 系数守卫消息契约（落表后不可达；直调私有守卫钉消息内容，防回退）──────────


def test_gas_unverified_guard_message():
    with pytest.raises(ValueError) as ei:
        itu._require_676_tables()
    msg = str(ei.value)
    for frag in ("UNVERIFIED", "Table 1", "Table 2", "44 行", "runs/ap6"):
        assert frag in msg, frag


def test_rain_unverified_guard_message():
    with pytest.raises(ValueError) as ei:
        itu._require_838_coeffs()
    msg = str(ei.value)
    for frag in ("UNVERIFIED", "P.838-3", "Tables 1-4"):
        assert frag in msg, frag


def test_rain_attenuation_produces_after_entry():
    a = rain_attenuation_db(10.0, 25.0, 3.0)
    assert a == pytest.approx(3.0 * gamma_rain_db_per_km(10.0, 25.0), rel=1e-15)


def test_r001_placeholder_rejects():
    with pytest.raises(ValueError, match="UNVERIFIED"):
        rain_rate_r001_mmh()


def test_zero_rain_is_zero_without_coeffs():
    """无雨恒无衰减（零元路径，不触系数守卫、非产数）。"""
    assert gamma_rain_db_per_km(10.0, 0.0) == 0.0
    assert gamma_rain_db_per_km(10.0, 0.0, pol="v") == 0.0
    assert rain_attenuation_db(10.0, 0.0, 12.0) == 0.0


# ─── 式机件（合成常数注入，零 ITU 值）——P.676-13 Annex 1 ────────────────────


def test_line_shape_resonance_and_offresonance_points():
    # 式(5) 共振点（δ=0）：F(f0) = 1/Δf + Δf/((2f0)²+Δf²)（主项+镜像项）
    f0, df = 50.0, 1.0
    got = itu._line_shape_5(f0, f0, df, 0.0)
    assert got == pytest.approx(1.0 / df + df / ((2.0 * f0) ** 2 + df**2), rel=1e-15)
    # 离谐精确点（δ=0.5）：逐项手算交叉核装配
    got = itu._line_shape_5(51.0, 50.0, 1.0, 0.5)
    expect = (51.0 / 50.0) * (
        (1.0 - 0.5 * (50.0 - 51.0)) / ((50.0 - 51.0) ** 2 + 1.0)
        + (1.0 - 0.5 * (50.0 + 51.0)) / ((50.0 + 51.0) ** 2 + 1.0)
    )
    assert got == pytest.approx(expect, rel=1e-15)


def test_width_6b_o2_zeeman_floor():
    assert itu._width_6b_o2(2.0) == pytest.approx(math.sqrt(4.0 + 2.25e-6), rel=1e-15)
    assert itu._width_6b_o2(0.0) == pytest.approx(1.5e-3, rel=1e-15)  # 纯 Zeeman 地板


def test_width_6b_wv_doppler_form():
    got = itu._width_6b_wv(1.0, 22.235, 1.0)
    assert got == pytest.approx(
        0.535 * 1.0 + math.sqrt(0.217 + 2.1316e-12 * 22.235**2), rel=1e-15)


def test_delta_7_o2_point():
    # 式(7)：δ=(a5+a6θ)×10⁻⁴(p+e)θ^0.8；θ=1、p=1000、e=10 → 3×10⁻⁴·1010
    assert itu._delta_7_o2(1.0, 2.0, 1000.0, 10.0, 1.0) == pytest.approx(0.303, rel=1e-15)


def test_dry_continuum_debye_half_power_and_low_f_limit():
    # 式(8/9)：f=d 处 Debye 项=半功率 6.14e-5/(2d)，N2 项可忽略（<1e-3 相对）
    p, e, theta = 1013.25, 10.0, 1.0
    d = 5.6e-4 * (p + e) * theta**0.8
    nd = itu._dry_continuum_89(d, p, e, theta)
    assert nd == pytest.approx(p * 6.14e-5 / 2.0, rel=2e-3)
    # 低频极限 f<<d：N″D ≈ f·p·θ²·[6.14e-5/d + 1.4e-12·p^1.5]（两支皆∝f）
    f_tiny = 1e-6 * d
    nd = itu._dry_continuum_89(f_tiny, p, e, theta)
    assert nd == pytest.approx(
        f_tiny * p * theta**2 * (6.14e-5 / d + 1.4e-12 * p**1.5), rel=1e-6)


def test_gamma_assembly_identity_eq1_2a_2b():
    """式(1)/(2a)/(2b) 装配恒等：γ=0.1820f·(ΣSF+N″D+ΣSF)，逐部分手算交叉核。"""
    theta, p = 300.0 / 288.15, 1013.25
    e = 7.5 * 288.15 / 216.7
    o2 = OxygenLine(f0_ghz=60.0, a1=100.0, a2=1.0, a3=10.0, a4=0.0, a5=1.0, a6=2.0)
    wv = WaterLine(f0_ghz=22.235, b1=0.5, b2=-1.0, b3=5.0, b4=0.7, b5=3.0, b6=0.9)
    f = 40.0
    g_dry, g_wet = itu._gamma_dry_wet(f, p, theta, e, (o2,), (wv,))
    # O2 支手算
    df = o2.a3 * 1e-4 * (p * theta ** (0.8 - o2.a4) + 1.1 * e * theta)
    df = itu._width_6b_o2(df)
    delta = itu._delta_7_o2(o2.a5, o2.a6, p, e, theta)
    s = o2.a1 * 1e-7 * p * theta**3 * math.exp(o2.a2 * (1.0 - theta))
    n_o = itu._dry_continuum_89(f, p, e, theta) + s * itu._line_shape_5(f, o2.f0_ghz, df, delta)
    # H2O 支手算
    dfw = wv.b3 * 1e-4 * (p * theta ** wv.b4 + wv.b5 * e * theta ** wv.b6)
    dfw = itu._width_6b_wv(dfw, wv.f0_ghz, theta)
    sw = wv.b1 * 1e-1 * e * theta**3.5 * math.exp(wv.b2 * (1.0 - theta))
    n_w = sw * itu._line_shape_5(f, wv.f0_ghz, dfw, 0.0)
    assert g_dry == pytest.approx(0.1820 * f * n_o, rel=1e-15)
    assert g_wet == pytest.approx(0.1820 * f * n_w, rel=1e-15)


# ─── 式机件——P.838-3（合成系数注入）──────────────────────────────────────────


def _synthetic_rain_coeffs() -> RainCoeffs:
    """合成系数：k 与 α 各=单 Gauss（峰 f=20GHz，宽 c=0.5 dex），峰高 k=10/α=2。"""
    b1 = math.log10(20.0)
    return RainCoeffs(
        k_a=(1.0, 0.0, 0.0, 0.0), k_b=(b1, 0.0, 0.0, 0.0), k_c=(0.5, 1.0, 1.0, 1.0),
        k_m=0.0, k_c0=0.0,
        a_a=(2.0, 0.0, 0.0, 0.0, 0.0), a_b=(b1, 0.0, 0.0, 0.0, 0.0),
        a_c=(0.5, 1.0, 1.0, 1.0, 1.0), a_m=0.0, a_c0=0.0,
    )


def test_rain_gauss_peak_and_two_dex_decay():
    sc = _synthetic_rain_coeffs()
    k, alpha = itu._rain_k_alpha(20.0, sc)
    assert k == pytest.approx(10.0, rel=1e-15)  # 峰值 log10 k = a1 = 1
    assert alpha == pytest.approx(2.0, rel=1e-15)
    # 离峰 1 dex：q=(Δlog f)/c=2 → 因子 exp(−4)
    k2, alpha2 = itu._rain_k_alpha(200.0, sc)
    assert k2 == pytest.approx(10.0 ** math.exp(-4.0), rel=1e-15)
    assert alpha2 == pytest.approx(2.0 * math.exp(-4.0), rel=1e-15)


def test_rain_linear_only_power_law():
    sc = RainCoeffs(
        k_a=(0.0, 0.0, 0.0, 0.0), k_b=(0.0, 0.0, 0.0, 0.0), k_c=(1.0, 1.0, 1.0, 1.0),
        k_m=2.0, k_c0=1.0,
        a_a=(0.0,) * 5, a_b=(0.0,) * 5, a_c=(1.0,) * 5, a_m=0.0, a_c0=2.0,
    )
    k, alpha = itu._rain_k_alpha(7.3, sc)
    assert k == pytest.approx(10.0 * 7.3**2, rel=1e-15)  # k = 10^(m·log f + c0)
    assert alpha == pytest.approx(2.0, rel=1e-15)


def test_rain_gamma_identity_k_r_alpha(monkeypatch):
    """式(1) 恒等：γ_R(f,R)=k·R^α（合成系数经公共入口注入，h/v 须齐——
    has_838_coeffs 恒要求双极化，单极化半录入态一律拒产数）。"""
    sc = _synthetic_rain_coeffs()
    monkeypatch.setattr(itu, "_RAIN_COEFFS", {"h": sc, "v": sc})
    k, alpha = itu._rain_k_alpha(20.0, sc)
    got = gamma_rain_db_per_km(20.0, 3.0, pol="h")
    assert got == pytest.approx(k * 3.0**alpha, rel=1e-15)
    assert got == pytest.approx(10.0 * 9.0, rel=1e-12)
    # 半录入态（仅 h）仍拒产数
    monkeypatch.setattr(itu, "_RAIN_COEFFS", {"h": sc})
    with pytest.raises(ValueError, match="UNVERIFIED"):
        gamma_rain_db_per_km(20.0, 3.0, pol="h")


def test_gas_public_path_with_synthetic_lines(monkeypatch):
    """公共入口装配（合成谱线注入）：与 _gamma_dry_wet 直调逐位一致。"""
    o2 = OxygenLine(f0_ghz=60.0, a1=100.0, a2=1.0, a3=10.0, a4=0.0, a5=1.0, a6=2.0)
    wv = WaterLine(f0_ghz=22.235, b1=0.5, b2=-1.0, b3=5.0, b4=0.7, b5=3.0, b6=0.9)
    monkeypatch.setattr(itu, "_O2_LINES", (o2,))
    monkeypatch.setattr(itu, "_WV_LINES", (wv,))
    theta, p, t = 300.0 / 288.15, 1013.25, 288.15
    e = 7.5 * t / 216.7
    direct = itu._gamma_dry_wet(40.0, p, theta, e, (o2,), (wv,))
    got = gamma_gasses_db_per_km(40e9, p, t, 7.5)
    assert got == pytest.approx(sum(direct), rel=1e-15)


# ─── 落表后谱线共振结构锚（AP-8 录入批；相对断言不发明绝对幅度）───────────────


def test_o2_60ghz_band_peak_and_wing_ratio():
    """60GHz O2 吸收带：带内值远高于带翼（海平面压力展宽成连续吸收带）。"""

    def g(f: float) -> float:
        return gamma_gasses_db_per_km(f * 1e9, 1013.25, 288.15, 0.0)

    g60 = g(60.0)
    assert _ANCHOR_G_O[0] <= g60 <= _ANCHOR_G_O[1]  # 与量级锚同窗（汇总）
    assert g60 > 20.0 * g(50.0)  # 带翼 50/70GHz 低于带心 20 倍以上
    assert g60 > 20.0 * g(70.0)  # （实测比值 ~43/50×，钉 20× 留网格余量）


def test_o2_118ghz_line_resonance_elevated():
    """118.750334GHz O2 线：线心 γ 高于近旁离谐点（共振位置正确）。"""

    def g(f: float) -> float:
        return gamma_gasses_db_per_km(f * 1e9, 1013.25, 288.15, 0.0)

    assert g(118.750334) > 1.5 * g(117.0)  # 实测 1.468 vs 0.799


def test_h2o_183ghz_line_local_maximum():
    """183.310087GHz H2O 线：水汽贡献在线心呈局部极大（两侧离谐点更低）。"""

    def gw(f: float) -> float:
        return (
            gamma_gasses_db_per_km(f * 1e9, 1013.25, 288.15, 7.5)
            - gamma_gasses_db_per_km(f * 1e9, 1013.25, 288.15, 0.0)
        )

    peak = gw(183.310087)
    assert peak > gw(180.0) and peak > gw(187.0)  # 实测 28.0 vs 13.7/13.3


# ─── P.838-3 Table 5 spot 值引用对拍（AP-8；全量 116 点见 runs/ap8/ 证据）──────

# 官方 Table 5 印刷值（R-REC-P.838-3.pdf 页索引 4-7）；容差 0.5%=
# 4 位有效数字印刷舍入界（实测最大 0.112% @ 1.5GHz kH）。
_TABLE5_SPOTS = [
    # (f_GHz, kH, αH, kV, αV)
    (1.0, 0.0000259, 0.9691, 0.0000308, 0.8592),
    (10.0, 0.01217, 1.2571, 0.01129, 1.2156),
    (29.0, 0.2224, 0.9580, 0.2124, 0.9203),
    (100.0, 1.3671, 0.6815, 1.3680, 0.6765),
    (300.0, 1.6286, 0.6296, 1.6286, 0.6262),
    (1000.0, 1.3795, 0.6396, 1.3822, 0.6365),
]


@pytest.mark.parametrize("f,kh,ah_,kv,av", _TABLE5_SPOTS)
def test_rain_table5_spot_reference(f, kh, ah_, kv, av):
    """k/α 高斯和式 vs 官方 Table 5 印刷值（h/v 双极化，≤0.5%）。"""
    kh_c, ah_c = itu._rain_k_alpha(f, itu._RAIN_COEFFS["h"])
    kv_c, av_c = itu._rain_k_alpha(f, itu._RAIN_COEFFS["v"])
    assert kh_c == pytest.approx(kh, rel=5e-3)
    assert ah_c == pytest.approx(ah_, rel=5e-3)
    assert kv_c == pytest.approx(kv, rel=5e-3)
    assert av_c == pytest.approx(av, rel=5e-3)


def test_rain_gamma_spot_29ghz_300ghz():
    """雨衰量级 spot（任务书预声明 29/300GHz 档）：γ_R 有限且随 R 单调增。"""
    for f in (29.0, 300.0):
        g25 = gamma_rain_db_per_km(f, 25.0)
        g50 = gamma_rain_db_per_km(f, 50.0)
        assert math.isfinite(g25) and g25 > 0.0
        assert g50 > g25  # R↑ → γ_R↑（α>0）
        assert gamma_rain_db_per_km(f, 25.0, pol="v") > 0.0


# ─── 预声明量级锚（AP-6 批 skipif 守卫——AP-8 落表后自动转正，窗值不得回调 #122）──

# 规格原文（§A-8）："γO(60GHz,1013hPa,15℃)≈15dB/km、γW(22.235,7.5g/m³)≈0.19dB/km"
# 窗=≈值 ±25%（γO）/±30%（γW），本批钉死。
_ANCHOR_G_O = (11.25, 18.75)
_ANCHOR_G_W = (0.133, 0.247)

_SKIP_676 = pytest.mark.skipif(
    not itu.has_676_tables(),
    reason="P.676-13 Table 1/2 逐值 UNVERIFIED（铁律 7）——录入批落表后自动转正",
)


@_SKIP_676
def test_anchor_gamma_o_60ghz_dry():
    g = gamma_gasses_db_per_km(60e9, 1013.25, 288.15, 0.0)
    assert _ANCHOR_G_O[0] <= g <= _ANCHOR_G_O[1], f"γO={g}"


@_SKIP_676
def test_anchor_gamma_w_22ghz_water_only():
    wet = gamma_gasses_db_per_km(22.235e9, 1013.25, 288.15, 7.5)
    dry = gamma_gasses_db_per_km(22.235e9, 1013.25, 288.15, 0.0)
    g_w = wet - dry
    assert _ANCHOR_G_W[0] <= g_w <= _ANCHOR_G_W[1], f"γW={g_w}"
