"""HS-5 core/sso_ground_bounce.py 单测（round4 中件包一判据，先写后跑 #122）。

裁判口径（#118，不自证）：
- 恒等式逐位：N=1、L=1、di/dt=1 → V=1.0 逐位；L=1、di/dt=1 时 V(N)=N
  逐位（整数值 float 乘法精确）；
- 频域求和 vs 手算网格逐位（测试表达式与被测同序左结合求和）；
- 集成钉（pdn 只读复用）：pdn_impedance_profile 产 |Z_PDNI| →
  rail_noise_peak，端到端等于手算逐谐波和；
- 边界：负参数/空谱/长度不配/bool → ValueError（0.0 合法，#364④）；
- 门边界：V == margin 判 pass（utilization=1.0 逐位），恰超即 fail。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core.pdn import pdn_impedance_profile
from rfauto.core.sso_ground_bounce import (
    IBIS_POWER_AWARE_STATUS,
    SsoMarginVerdict,
    ground_bounce_voltage,
    rail_noise_contributions,
    rail_noise_peak,
    sso_bounce_gate,
    sso_margin_gate,
)

# ─── 1. ground_bounce_voltage：恒等式与线性缩放 ──────────────────────────────


def test_ground_bounce_identity_exact():
    assert ground_bounce_voltage(1, 1.0, 1.0) == 1.0  # 逐位
    # 物理量级：N=8 驱动、L_eff=2.5nH、di/dt=20mA/ns → V=8·2.5e-9·2e7=0.4V
    assert ground_bounce_voltage(8, 2.5e-9, 20e-3 / 1e-9) == pytest.approx(0.4, rel=1e-15)


def test_ground_bounce_n_scaling_bitwise():
    # L=di/dt=1 时 V(N)=N 逐位（整数值 float 运算精确）
    for n in range(0, 9):
        assert ground_bounce_voltage(n, 1.0, 1.0) == float(n)
    # 一般参数线性缩放（rel 1e-15，浮点结合序差以内）
    v1 = ground_bounce_voltage(1, 2.5e-9, 20e-3 / 1e-9)
    for n in (2, 3, 7, 16):
        assert ground_bounce_voltage(n, 2.5e-9, 20e-3 / 1e-9) == pytest.approx(n * v1, rel=1e-15)


def test_ground_bounce_zero_legal():
    # 0.0 合法（#364④）：di/dt=0 / L=0 / N=0 → V=0.0 逐位
    assert ground_bounce_voltage(4, 2.5e-9, 0.0) == 0.0
    assert ground_bounce_voltage(4, 0.0, 20e6) == 0.0
    assert ground_bounce_voltage(0, 2.5e-9, 20e6) == 0.0


def test_ground_bounce_guards():
    with pytest.raises(ValueError):
        ground_bounce_voltage(-1, 1e-9, 1e6)  # 负开关数
    with pytest.raises(ValueError):
        ground_bounce_voltage(1.5, 1e-9, 1e6)  # 非整数开关数
    with pytest.raises(ValueError):
        ground_bounce_voltage(True, 1e-9, 1e6)  # bool 拒收（df7+⑯）
    with pytest.raises(ValueError):
        ground_bounce_voltage(4, -1e-9, 1e6)  # 负电感
    with pytest.raises(ValueError):
        ground_bounce_voltage(4, 1e-9, -1e6)  # 负斜率
    with pytest.raises(ValueError):
        ground_bounce_voltage(4, float("nan"), 1e6)  # NaN
    with pytest.raises(ValueError):
        ground_bounce_voltage(4, 1e-9, float("inf"))  # 非有限


# ─── 2. rail_noise_peak：频域求和逐位与边界 ──────────────────────────────────


def test_rail_noise_peak_hand_grid_bitwise():
    z = [0.1, 0.5, 2.0]
    i = [0.01, 0.002, 0.0001]
    expected = 0.1 * 0.01 + 0.5 * 0.002 + 2.0 * 0.0001  # 同序左结合 → 逐位
    assert rail_noise_peak(z, i) == expected
    assert expected == pytest.approx(0.0022, rel=1e-12)  # 手算量级锚


def test_rail_noise_peak_empty_and_mismatch():
    with pytest.raises(ValueError):
        rail_noise_peak([], [])  # 空谱
    with pytest.raises(ValueError):
        rail_noise_peak([0.1], [])  # 单侧空
    with pytest.raises(ValueError):
        rail_noise_peak([0.1, 0.2], [0.01])  # 长度不配
    with pytest.raises(ValueError):
        rail_noise_contributions([], [0.01])


def test_rail_noise_peak_negative_and_nan():
    with pytest.raises(ValueError):
        rail_noise_peak([-0.1, 0.2], [0.01, 0.01])  # 负 |Z|
    with pytest.raises(ValueError):
        rail_noise_peak([0.1, 0.2], [0.01, -0.01])  # 负电流谱
    with pytest.raises(ValueError):
        rail_noise_peak([float("nan"), 0.2], [0.01, 0.01])  # NaN
    with pytest.raises(ValueError):
        rail_noise_peak([0.1, True], [0.01, 0.01])  # bool 拒收


def test_rail_noise_contributions_match_peak():
    z = [0.1, 0.5, 2.0, 0.05]
    i = [0.01, 0.002, 0.0001, 0.02]
    contrib = rail_noise_contributions(z, i)
    assert len(contrib) == 4
    for zk, ik, ck in zip(z, i, contrib, strict=True):
        assert ck == zk * ik  # 逐元素逐位
    assert sum(contrib) == rail_noise_peak(z, i)  # 同构逐位（峰=贡献之和）


def test_rail_noise_peak_with_pdn_profile_integration():
    # 集成钉（pdn 只读复用）：Z_PDNI 面由 pdn.py 产出，本模块只消费 |Z| 数组。
    # 取 decap 单支路（vrm=None）使 |Z| 有独立闭式：|Z| = √(esr² + (ωL−1/ωC)²)
    c, esr, esl = 100e-6, 5e-3, 0.5e-9
    freqs = [1e6, 10e6, 100e6]
    currents = [0.01, 0.005, 0.002]
    z_complex = pdn_impedance_profile(None, None, [(c, esr, esl)], freqs)
    mags = [abs(z) for z in z_complex]
    for f_hz, mag in zip(freqs, mags, strict=True):
        x = 2.0 * math.pi * f_hz * esl - 1.0 / (2.0 * math.pi * f_hz * c)
        assert mag == pytest.approx(math.sqrt(esr**2 + x**2), rel=1e-12)  # 双路径
    expected = mags[0] * currents[0] + mags[1] * currents[1] + mags[2] * currents[2]
    assert rail_noise_peak(mags, currents) == expected  # 逐位
    assert 5e-4 < expected < 1.5e-3  # mΩ→Ω 扫程的手算量级带（5.2e-5+1.6e-4+6.3e-4）


# ─── 3. 裕度门与 NO-GO 登记 ──────────────────────────────────────────────────


def test_sso_margin_gate_boundary():
    verdict = sso_margin_gate(0.05, 0.05)
    assert verdict.verdict == "pass"  # 恰等门限判 pass
    assert verdict.margin_v == 0.0  # 逐位
    assert verdict.utilization == 1.0  # 逐位
    over = sso_margin_gate(0.05 + 1e-12, 0.05)
    assert over.verdict == "fail"
    assert over.margin_v == pytest.approx(-1e-12, rel=1e-9)  # 负=超限量
    assert over.utilization > 1.0


def test_sso_bounce_gate_composition():
    # 门面组合一致：sso_bounce_gate == margin_gate(bounce_voltage(...)) 全字段
    direct = sso_margin_gate(ground_bounce_voltage(8, 2.5e-9, 20e-3 / 1e-9), 0.5)
    composed = sso_bounce_gate(8, 2.5e-9, 20e-3 / 1e-9, 0.5)
    assert composed == direct  # frozen dataclass 逐字段相等
    assert composed.verdict == "pass"
    assert composed.noise_v == pytest.approx(0.4, rel=1e-15)


def test_sso_margin_gate_guards():
    with pytest.raises(ValueError):
        sso_margin_gate(-0.01, 0.05)  # 负噪声电平
    with pytest.raises(ValueError):
        sso_margin_gate(0.01, 0.0)  # 裕度必须 >0
    with pytest.raises(ValueError):
        sso_margin_gate(0.01, -0.05)  # 负裕度
    with pytest.raises(ValueError):
        sso_margin_gate(float("nan"), 0.05)  # NaN
    with pytest.raises(ValueError):
        sso_margin_gate(0.01, True)  # bool 拒收


def test_sso_margin_gate_to_dict_json():
    verdict = sso_margin_gate(0.04, 0.05)
    payload = verdict.to_dict()
    assert isinstance(payload, dict)
    assert set(payload) == {"verdict", "noise_v", "noise_margin_v", "margin_v", "utilization"}
    assert json.loads(json.dumps(payload))["verdict"] == "pass"
    assert SsoMarginVerdict(**payload) == verdict  # 往返一致


def test_ibis_power_aware_no_go_registered():
    # IBIS power-aware 波形级 = NO-GO 登记（不开实现）：常量在位 + 法源在 docstring
    assert IBIS_POWER_AWARE_STATUS == "no_go"
    import rfauto.core.sso_ground_bounce as mod

    assert "IBIS" in mod.__doc__
    assert "NO-GO" in mod.__doc__
    # 除登记常量自身外，无任何波形级/IBIS 实现入口泄漏（公开面只有闭式与门）
    violators = [
        name
        for name in vars(mod)
        if not name.startswith("_")
        and name != "IBIS_POWER_AWARE_STATUS"
        and ("ibis" in name.lower() or "waveform" in name.lower())
    ]
    assert violators == []
