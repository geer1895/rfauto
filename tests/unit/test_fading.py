"""AP-7 多径衰落统计包锚测试（规格深案 §A-9，2026-10-02）。

锚口径（任务书预声明 + 一手出处实测核 #118 裁判纪律；探测证据见模块
docstring，本文件只钉可复跑数字）：

- Rice/Rayleigh 退化：**任务书预写 "K→∞ Rice→Rayleigh" 系笔误实测
  勘误**——物理极限是 K→0（镜射分量消失）退化为 Rayleigh（实测分数
  偏差 3e-17，门 1e-6 达余量）；K→∞ 是无衰落极限（outage→0，K=50
  @20dB 实测 3.8e-20）。
- Nakagami m=1 ≡ Rayleigh 恒等（gammainc(1,h)=1−e^(−h)，实测 3e-17）。
- Rayleigh 闭式 vs scipy.stats.rayleigh 数值互证（Ω=2 口径，
  P(r<√(hΩ); σ=√(Ω/2)) = 1−exp(−h)，实测 5e-17）。
- 对数正态：0.5·erfc(M/(σ√2)) ≡ Φ(−M/σ)（scipy norm 互证）；M=σ →
  15.866%（1σ 经典锚）；M=0 → 50%。
- margin→outage 严格单调下降（四种 kind，0–40dB 网格）。
- Vigants-Barnett（Barnett 1972 BSTJ 51(2) §6.3 一手核）：Table II
  West Unity 回核——4GHz/28.5mi/average（c=1e-5）→ P(F=0)=0.2315，
  与原刊实测系数 0.25 差 0.34dB（原刊自述 ±1dB 实验误差内）；气候档
  单调 over_water ≥ average ≥ rough ≥ dry_mountain；未知档显式
  ValueError；浅衰落越域截断到 1.0。
- P.530-18（§2.3.1 式(7) 2021-09 版文本层逐位核）：d≤5km 记 0 中断
  （Rec 原文口径）；margin→availability→margin 往返闭合 ≤1e-9。
- V-B vs P.530-18 同参差异带：锚点 6GHz/50km/30dB（C=1 vs
  log10_k=−2/εp=10mrad/hc=500m/hL=100m）实测中断比 ≈0.212——**不设
  对错门，如实记录带**（断言只钉有限性+宽包络 [0.02,50]，包络本身
  入档；两式把地形/气候/几何折标量的方式不同，差异带是映射约定的
  函数，见 core/fading.py 模块 docstring）。

零外部数据捆绑：全部锚=闭式恒等式/一手文献实测回核/scipy 互证，无
ITU/BJT 数据文件依赖。
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.core.fading import (
    availability_margin,
    fade_outage_percent,
    vigants_barnett_outage,
)
from rfauto.service.calculator_service import run_calculator

_KEYS = ("fade_outage_percent", "availability_margin")


# ─── 注册面（#231 五钉之一：test_calculators EXPECTED 见同批追加）────────────


@pytest.mark.parametrize("key", _KEYS)
def test_registered_and_json_contract(key: str):
    assert key in set(CALCULATOR_REGISTRY.names())
    spec = CALCULATOR_REGISTRY.get(key)
    assert spec.description and not spec.experimental
    described = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    assert {p["name"] for p in described[key]["params"]} >= set(spec.required)
    json.dumps(described[key], ensure_ascii=False)


# ─── 小尺度衰落 CDF 族：退化/恒等/scipy 互证 ────────────────────────────────


@pytest.mark.parametrize("margin_db", [0.0, 5.0, 10.0, 20.0, 30.0, 40.0])
def test_rice_k_to_zero_degenerates_to_rayleigh(margin_db: float):
    """K→0 退化为 Rayleigh（任务书 "K→∞" 方向系笔误，实测勘误）。"""
    ray = fade_outage_percent(margin_db, kind="rayleigh")
    rice = fade_outage_percent(margin_db, kind="rice", k=1e-12)
    assert abs(rice - ray) <= 1e-6  # 任务书口径 ≤1e-6（实测 ~3e-15%）


def test_rice_large_k_no_fading_limit():
    """K→∞ 无衰落极限：outage→0（K=50 @20dB 实测 3.8e-20）。"""
    outage = fade_outage_percent(20.0, kind="rice", k=50.0)
    assert 0.0 <= outage < 1e-12


def test_rice_monotone_decreasing_in_k():
    """K 增大（镜射分量变强）→ 中断下降。"""
    lo = fade_outage_percent(20.0, kind="rice", k=0.5)
    hi = fade_outage_percent(20.0, kind="rice", k=20.0)
    assert hi < lo


@pytest.mark.parametrize("margin_db", [0.0, 5.0, 10.0, 20.0, 30.0, 40.0])
def test_nakagami_m1_identity_rayleigh(margin_db: float):
    """m=1 Nakagami ≡ Rayleigh 恒等（gammainc(1,h)=1−e^(−h)）。"""
    ray = fade_outage_percent(margin_db, kind="rayleigh")
    nak = fade_outage_percent(margin_db, kind="nakagami", m=1.0)
    assert abs(nak - ray) <= 1e-12  # 实测 ~3e-15%


def test_rayleigh_closed_form_vs_scipy_crosscheck():
    """Rayleigh 闭式 vs scipy.stats.rayleigh 数值互证（Ω=2 口径）。"""
    from scipy.stats import rayleigh as _rayleigh_dist

    omega = 2.0  # A=0、σ=1 时 E[r²]=2σ²
    for margin_db in (0.0, 6.0, 13.0, 25.0):
        h = 10.0 ** (-margin_db / 10.0)
        closed = 1.0 - math.exp(-h)
        scipy_val = float(
            _rayleigh_dist.cdf(math.sqrt(h * omega), scale=math.sqrt(omega / 2))
        )
        got = fade_outage_percent(margin_db, kind="rayleigh") / 100.0
        assert abs(closed - scipy_val) <= 1e-9
        assert abs(got - scipy_val) <= 1e-9


def test_lognormal_erfc_vs_norm_and_sigma_anchor():
    """对数正态：erfc 形式 ≡ Φ(−M/σ)（scipy norm 互证）+1σ/M=0 锚。"""
    from scipy.stats import norm

    for sigma_db in (4.0, 8.0, 12.0):
        for margin_db in (0.0, 8.0, 25.0):
            got = fade_outage_percent(
                margin_db, kind="lognormal", sigma_db=sigma_db)
            ref = 100.0 * float(norm.cdf(-margin_db / sigma_db))
            assert abs(got - ref) <= 1e-9
    # 1σ 经典锚：M=σ → 15.866%
    assert abs(
        fade_outage_percent(8.0, kind="lognormal", sigma_db=8.0)
        - 15.865525393145708
    ) <= 1e-9
    # M=0 → 半数时间低于中值
    assert fade_outage_percent(0.0, kind="lognormal") == pytest.approx(50.0)


@pytest.mark.parametrize("kind", ["rice", "rayleigh", "nakagami", "lognormal"])
def test_margin_outage_strictly_monotone(kind: str):
    """margin→outage 严格单调下降（四种 kind，0–40dB 网格）。"""
    margins = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0]
    outages = [fade_outage_percent(mg, kind=kind) for mg in margins]
    for earlier, later in itertools.pairwise(outages):
        assert later < earlier


def test_fade_outage_negative_guards():
    """域守卫负例：kind 拼写/负裕量/K<0/m<0.5/σ≤0 显式 ValueError。"""
    with pytest.raises(ValueError, match="kind"):
        fade_outage_percent(20.0, kind="weibull")
    with pytest.raises(ValueError, match="margin_db"):
        fade_outage_percent(-1.0, kind="rayleigh")
    with pytest.raises(ValueError, match="k"):
        fade_outage_percent(20.0, kind="rice", k=-0.5)
    with pytest.raises(ValueError, match="m"):
        fade_outage_percent(20.0, kind="nakagami", m=0.4)
    with pytest.raises(ValueError, match="sigma_db"):
        fade_outage_percent(20.0, kind="lognormal", sigma_db=0.0)


# ─── Vigants-Barnett：Table II 回核/档位单调/域守卫 ─────────────────────────


def test_vb_table_ii_west_unity_crosscheck():
    """一手回核：Barnett Table II West Unity（4GHz/28.5mi，1966）。

    原刊实测多径出现因子系数 P≈0.25·L²（±1dB 实验误差自述）；实现
    c=1e-5（average）·(4/4)·1e-5·28.5³=0.23149 → 差 0.34dB。
    """
    got = vigants_barnett_outage(4.0, 28.5 * 1.609344, 0.0, climate="average")
    assert got == pytest.approx(1e-5 * 28.5**3, rel=1e-12)
    assert 10.0 * math.log10(0.25 / got) <= 1.0  # 原刊 ±1dB 误差带内


def test_vb_margin_law_and_climate_monotone():
    """10^(−F/10) 幂律逐点 + 气候档单调（越湿越滑越差）。"""
    base = vigants_barnett_outage(6.0, 50.0, 30.0, climate="average")
    assert base == pytest.approx(
        1.0 * (6.0 / 4.0) * 1e-5 * (50.0 / 1.609344) ** 3 * 10 ** (-3.0),
        rel=1e-12,
    )
    outages = [
        vigants_barnett_outage(6.0, 50.0, 30.0, climate=cl)
        for cl in ("over_water", "average", "rough", "dry_mountain")
    ]
    assert outages[0] > outages[1] > outages[2] > outages[3] > 0.0


def test_vb_decrease_with_margin_and_clamp():
    """裕量↑ → 中断↓；浅衰落越域（短裕量超长路径）截断到 1.0。"""
    assert vigants_barnett_outage(
        6.0, 50.0, 40.0, climate="average"
    ) < vigants_barnett_outage(6.0, 50.0, 20.0, climate="average")
    assert vigants_barnett_outage(11.0, 300.0, 0.0, climate="over_water") == 1.0


def test_vb_negative_guards():
    """域守卫负例：未知气候档/负裕量/零距离显式 ValueError。"""
    with pytest.raises(ValueError, match="climate"):
        vigants_barnett_outage(6.0, 50.0, 30.0, climate="gulf_coast")
    with pytest.raises(ValueError, match="fade_margin_db"):
        vigants_barnett_outage(6.0, 50.0, -5.0)
    with pytest.raises(ValueError, match="d_km"):
        vigants_barnett_outage(6.0, 0.0, 30.0)


# ─── availability_margin：往返闭合/P.530 短路径口径/差异带报告 ───────────────


@pytest.mark.parametrize("margin_db", [20.0, 30.0, 40.0])
def test_roundtrip_margin_availability_margin(margin_db: float):
    """margin→availability→margin 往返闭合（两模型幂律反解，≤1e-9）。"""
    out = availability_margin(6.0, 50.0, fade_margin_db=margin_db)
    vb_avail = out["vb"]["availability_percent"]
    back_vb = availability_margin(
        6.0, 50.0, availability_percent=vb_avail
    )["vb"]["fade_margin_db"]
    assert abs(back_vb - margin_db) <= 1e-9
    p530_avail = out["p530"]["availability_percent"]
    back_p530 = availability_margin(
        6.0, 50.0, availability_percent=p530_avail
    )["p530"]["fade_margin_db"]
    assert abs(back_p530 - margin_db) <= 1e-9


def test_p530_short_path_zero_outage():
    """P.530-18 口径：d≤5km 多径中断记 0（Rec 原文 'longer than 5 km'）。

    裕量方向：中断 0/可用度 100；可用度方向：裕量无定义如实 None。
    """
    out = availability_margin(6.0, 4.9, fade_margin_db=30.0)
    assert out["p530"]["outage_fraction"] == 0.0
    assert out["p530"]["availability_percent"] == 100.0
    out2 = availability_margin(6.0, 4.9, availability_percent=99.999)
    assert out2["p530"]["fade_margin_db"] is None
    # V-B 侧不受益于该口径（正常计算）
    assert out["vb"]["outage_fraction"] > 0.0


def test_availability_margin_diff_band_reported():
    """V-B vs P.530-18 同参差异带：如实记录，不设对错门。

    锚点（6GHz/50km/30dB，C=1 ↔ log10_k=−2/εp=10mrad/hc=500/hL=100）
    实测中断比 ≈0.212（≈−6.7dB）——断言只钉有限性+宽包络 [0.02,50]
    （映射约定敏感性见 core/fading.py docstring；带值本身入档）。
    """
    out = availability_margin(6.0, 50.0, fade_margin_db=30.0)
    band = out["diff_band"]
    ratio = band["outage_ratio_p530_over_vb"]
    assert math.isfinite(ratio)
    assert 0.02 <= ratio <= 50.0
    # 方向可用度→裕量：diff_band 走 margin 差形态
    out2 = availability_margin(6.0, 50.0, availability_percent=99.999)
    band2 = out2["diff_band"]
    diff = band2["margin_diff_db_p530_minus_vb"]
    assert math.isfinite(diff)
    # 幂律族 margin 差与目标可用度无关（同 10^(-A/10) 指数）：
    out3 = availability_margin(6.0, 50.0, availability_percent=99.99)
    assert out3["diff_band"]["margin_diff_db_p530_minus_vb"] == pytest.approx(
        diff, abs=1e-9
    )
    print(
        "[ap7 diff band] margin 方向中断比="
        f"{ratio:.4f}; 99.999% 裕量差={diff:.2f}dB "
        f"(VB={band2['vb_margin_db']:.2f} / "
        f"P530={band2['p530_margin_db']:.2f})"
    )


def test_availability_margin_negative_guards():
    """域守卫负例：双方向缺一/都给/可用度越界/未知档/负倾角。"""
    with pytest.raises(ValueError, match="二选一"):
        availability_margin(6.0, 50.0)
    with pytest.raises(ValueError, match="二选一"):
        availability_margin(
            6.0, 50.0, availability_percent=99.999, fade_margin_db=30.0)
    with pytest.raises(ValueError, match="availability_percent"):
        availability_margin(6.0, 50.0, availability_percent=100.0)
    with pytest.raises(ValueError, match="climate"):
        availability_margin(6.0, 50.0, climate="harsh")
    with pytest.raises(ValueError, match="eps_p_mrad"):
        availability_margin(
            6.0, 50.0, fade_margin_db=30.0, eps_p_mrad=-1.0)


# ─── service 面冒烟（ok 契约；G15 通用不变量在 physics_invariants）──────────


@pytest.mark.parametrize(
    "key, params",
    [
        ("fade_outage_percent",
         {"margin_db": 30.0, "kind": "rice", "k": 10.0}),
        ("availability_margin",
         {"f_ghz": 6.0, "d_km": 50.0, "fade_margin_db": 30.0}),
    ],
)
def test_service_run_ok_and_json(key: str, params: dict):
    out = run_calculator(key, params, allow_experimental=True)
    assert out["ok"] is True, out.get("error")
    json.dumps(out, ensure_ascii=False, allow_nan=False)
