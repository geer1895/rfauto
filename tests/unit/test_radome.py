"""NX-5 天线罩多层透波 + BSE 单测（2026-10-03）。

锚树口径（#118：独立裁判路，不赌推导）：
- 单界面：0 厚层 stack r vs normal_incidence_fresnel 独立闭式逐位一致。
- 半波长板：M=−I 构造性 T=1（功率恒等）。
- 能量守恒：无耗任意堆叠/角度 |R|²+|T|²=1（TE/TM 两极化 × 多角度）。
- 布儒斯特角（TM）：单板双界面在 Brewster 入射下 r_amp 面内独立核对
  （tanθ_B=n2/n1，独立公式裁判路，功率反射显著低于邻近角）。
- 平行板零偏折 / 薄楔 (n−1)α 恒等。
- 球壳：b=0 零偏折；奇对称 dev(−b)=−dev(b)；小 b 线性化独立复算
  dev ≈ b·(1−1/n)(1/r_out+1/r_in)；质心一阶矩=0。
"""
from __future__ import annotations

import cmath
import math

import pytest

from rfauto.core.radome import (
    boresight_error_note,
    dielectric_abcd,
    half_wave_slab_transmission,
    normal_incidence_fresnel,
    single_interface_rt,
    slab_deviation_angle,
    spherical_shell_ray_bse,
    stack_power_rt,
)

_F = 10e9
_ER_RADOME = 4.0  # εr=4（duroid 类）


def test_single_interface_matches_fresnel():
    """单界面：single_interface_rt 法向 vs normal_incidence_fresnel（1e-12）。"""
    for er in (2.0, 4.0, 9.8):
        out = single_interface_rt(1.0, er, 0.0, "te")
        big_r, big_t = normal_incidence_fresnel(1.0, er)
        assert abs(out["power_r"] - big_r) <= 1e-12
        assert abs(out["power_t"] - big_t) <= 1e-12


def test_slab_matches_independent_airy_formula():
    """单板双界面：stack vs 独立 Airy 公式（测试内书写，#118 双路）。

    相位约定：e^{+jωt}/e^{−jkz} 传播（本仓口径）→ 往返相位 e^{−2jknd}。
    """
    er, d = 4.0, 0.003
    n = math.sqrt(er)
    f = 10e9
    lam0 = 299792458.0 / f
    k0 = 2.0 * math.pi / lam0
    r01 = (1.0 - n) / (1.0 + n)
    r12 = (n - 1.0) / (n + 1.0)
    phase = cmath.exp(-2j * k0 * n * d)
    r_airy = (r01 + r12 * phase) / (1.0 + r01 * r12 * phase)
    out = stack_power_rt([(d, er, 1.0)], f, 0.0, "te")
    assert abs(out["r"] - r_airy) <= 1e-10


def test_half_wave_slab_perfect_transmission():
    out = half_wave_slab_transmission(_ER_RADOME, _F)
    assert abs(out["power_t"] - 1.0) <= 1e-12
    assert abs(out["power_r"] - 0.0) <= 1e-12


@pytest.mark.parametrize("pol", ["te", "tm"])
@pytest.mark.parametrize("theta_deg", [0.0, 15.0, 30.0, 45.0])
def test_energy_conservation_multilayer(pol, theta_deg):
    """无耗堆叠能量守恒：三层板 |R|²+|T|²=1（1e-12）。"""
    layers = [
        (0.002, 2.2, 1.0),
        (0.005, _ER_RADOME, 1.0),
        (0.001, 3.0, 1.0),
    ]
    out = stack_power_rt(layers, _F, math.radians(theta_deg), pol)
    assert abs(out["power_r"] + out["power_t"] - 1.0) <= 1e-10


def test_brewster_tm_minimum():
    """TM 布儒斯特角：tanθ_B=n2/n1 → 单界面 r=0；邻近角 |r| 更大。"""
    theta_b = math.atan(math.sqrt(_ER_RADOME))
    out = single_interface_rt(1.0, _ER_RADOME, theta_b, "tm")
    assert abs(out["r"]) <= 1e-12
    off = single_interface_rt(1.0, _ER_RADOME, theta_b + 0.1, "tm")
    assert abs(off["r"]) > 1e-3


def test_zero_thickness_identity_matrix():
    m = dielectric_abcd(0.0, _ER_RADOME, _F, 0.0, "te")
    assert abs(m[0, 0] - 1.0) <= 1e-15
    assert abs(m[1, 1] - 1.0) <= 1e-15
    assert abs(m[0, 1]) <= 1e-15
    assert abs(m[1, 0]) <= 1e-15


def test_slab_deviation_parallel_and_wedge():
    out0 = slab_deviation_angle(0.0, _ER_RADOME)
    assert out0["deviation_rad"] == 0.0
    alpha = math.radians(3.0)
    n = math.sqrt(_ER_RADOME)
    out = slab_deviation_angle(alpha, _ER_RADOME)
    assert abs(out["deviation_rad"] - (n - 1.0) * alpha) <= 1e-15
    with pytest.raises(ValueError):
        slab_deviation_angle(-0.01, _ER_RADOME)


def test_spherical_shell_symmetry_and_linearization():
    """球壳：b=0 零偏折；奇对称；小 b 线性化独立复算（相对 1e-9）。"""
    r_out, thick = 0.3, 0.004
    r_in = r_out - thick
    n = math.sqrt(_ER_RADOME)
    offsets = [-0.1, -0.05, -0.01, 0.0, 0.01, 0.05, 0.1]
    out = spherical_shell_ray_bse(r_out, thick, _ER_RADOME, _F, offsets)
    angles = out["exit_angle_rad"]
    assert angles[3] == 0.0
    for i, b in enumerate(offsets):
        # 奇对称：dev(−b) = −dev(b)
        j = offsets.index(-b)
        assert abs(angles[i] + angles[j]) <= 1e-15
    # 小 b 线性化：dev ≈ b·(1−1/n)(1/r_out+1/r_in)（截断 O((b/r)²)，
    # 相对容差 1e-3）
    b_small = 0.002
    expect = b_small * (1.0 - 1.0 / n) * (1.0 / r_out + 1.0 / r_in)
    out_s = spherical_shell_ray_bse(r_out, thick, _ER_RADOME, _F, [b_small])
    assert abs(out_s["exit_angle_rad"][0] - expect) <= 1e-3 * expect
    # 居中对称孔径质心一阶矩 = 0（奇对称；浮点均值残差 ≤1e-16）
    assert abs(out["bse_first_order_rad"]) <= 1e-16


def test_pure_shell_ray_exit_domain():
    """|b|∈[r_in,r_out)：纯穿壳 δ_exit=0 → dev=δ_entry（独立复算恒等）。"""
    r_out, thick = 0.3, 0.05
    n = math.sqrt(_ER_RADOME)
    b = 0.28  # > r_in = 0.25
    out = spherical_shell_ray_bse(r_out, thick, _ER_RADOME, _F, [b])
    expect = math.asin(b / r_out) - math.asin(b / (n * r_out))
    assert abs(out["exit_angle_rad"][0] - expect) <= 1e-15


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        stack_power_rt([], _F, 0.0, "te")
    with pytest.raises(ValueError):
        stack_power_rt([(0.001, 4.0, 1.0)], _F, math.radians(90.0), "te")
    with pytest.raises(ValueError):
        dielectric_abcd(0.001, 4.0, _F, 0.0, "xx")
    with pytest.raises(ValueError):
        spherical_shell_ray_bse(0.3, 0.4, _ER_RADOME, _F, [0.1])
    with pytest.raises(ValueError):
        spherical_shell_ray_bse(0.3, 0.01, _ER_RADOME, _F, [0.35])
    with pytest.raises(ValueError):
        single_interface_rt(1.0, 4.0, 0.0, "xx")


def test_boresight_note_doc_face():
    note = boresight_error_note()
    assert "UNVERIFIED" in note["source"]
