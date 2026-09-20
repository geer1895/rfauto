"""2D 准静态 FD Laplace 裁判内核（core/quasistatic_fd.py）验证锚（#118 独立来源）。

裁判本身必须先过已知闭式基准才有资格裁判闭式（#118 纪律）：
- 解析精确：平行板/串联双层板（场均匀 → FD 逐位精确，钉 ε 权重与能量法系数）；
- 微带 vs Hammerstad–Jensen（skrf MLine，含 εr=9.8）；
- CPS 半空间极限 (1+εr)/2、空气 CPS vs 共形映射闭式 Z0（MathWorks MoM 对拍口径）；
- 零厚度带状线空气 Z0 vs Cohn 闭式 `_stripline_z0`；悬置带线 h→b/h→0 两支精确极限。
标称裁判值（refs §11.1/§11.2 真值来源）在本文件钉住。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.calculators import _cps_ri, _stripline_z0
from rfauto.core.quasistatic_fd import (
    QuasiStaticResult,
    concat_lines,
    cps_quasistatic,
    energy_quasistatic,
    graded_lines,
    microstrip_quasistatic,
    richardson_first_order,
    suspended_stripline_quasistatic,
    uniform_lines,
)

ER, H = 3.66, 0.508


# ─── 解析精确基准（场均匀 → FD 逐位精确）────────────────────────────────────

def test_parallel_plate_energy_is_exact():
    """宽 W、距 d 平行板：C = ε·W/d（ε0 单位）。上板 φ=1、下板 φ=0，侧边 Neumann。"""
    xs = np.linspace(0.0, 2.0, 9)
    zs = np.linspace(0.0, 0.5, 6)
    nx, nz = xs.size, zs.size
    eps = np.full((nx - 1, nz - 1), 4.0)
    diri = {i * nz: 0.0 for i in range(nx)}
    diri.update({i * nz + nz - 1: 1.0 for i in range(nx)})
    w = energy_quasistatic(xs, zs, eps, diri)
    assert 2.0 * w == pytest.approx(4.0 * 2.0 / 0.5, rel=1e-12)


def test_series_two_layer_plate_pins_eps_weighting():
    """双层串联板（ε1 厚 d1 + ε2 厚 d2）：C = W/(d1/ε1 + d2/ε2)——介质面落网格线，
    场逐层均匀，钉住"边两侧 cell 半格加权"的 ε 口径。"""
    xs = np.linspace(0.0, 1.0, 5)
    zs = concat_lines(uniform_lines(0.0, 0.3, 0.1), uniform_lines(0.3, 1.0, 0.1))
    nx, nz = xs.size, zs.size
    eps = np.ones((nx - 1, nz - 1))
    zc = 0.5 * (zs[:-1] + zs[1:])
    eps[:, zc < 0.3] = 3.0
    diri = {i * nz: 0.0 for i in range(nx)}
    diri.update({i * nz + nz - 1: 1.0 for i in range(nx)})
    c = 2.0 * energy_quasistatic(xs, zs, eps, diri)
    assert c == pytest.approx(1.0 / (0.3 / 3.0 + 0.7 / 1.0), rel=1e-12)


def test_grid_helpers_contract():
    g = graded_lines(1.0, 9.0, 0.1, 1.2)
    assert g[0] == 1.0 and g[-1] == 9.0
    assert np.all(np.diff(g) > 0)
    assert np.diff(g)[-1] >= 0.1 * 0.999          # 末格不塌缩为 nm 级（#152 同族）
    assert graded_lines(2.0, 2.0, 0.1).tolist() == [2.0]
    u = uniform_lines(0.0, 1.0, 0.3)
    assert u.size == 4 and u[-1] == 1.0
    c = concat_lines(np.array([0.0, 0.5]), np.array([0.5, 1.0]), np.array([1.0]))
    assert c.tolist() == [0.0, 0.5, 1.0]
    with pytest.raises(ValueError):
        concat_lines(np.array([0.0, 1.0]), np.array([0.5]))
    assert richardson_first_order(1.0, 1.1) == pytest.approx(1.2)
    with pytest.raises(ValueError):
        energy_quasistatic(np.linspace(0, 1, 3), np.linspace(0, 1, 3),
                           np.ones((2, 2)), {})


# ─── 已知闭式基准 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("w, h, er", [
    (1.1134, 0.508, 3.66), (0.5, 0.508, 3.66), (3.0, 0.508, 3.66), (1.0, 1.0, 9.8),
])
def test_microstrip_matches_hammerstad_jensen(w, h, er):
    """微带静态 εeff vs HJ（skrf MLine，HJ 自身精度 ~0.2%）：实测 +0.1~+0.3%。"""
    skrf = pytest.importorskip("skrf")
    f = skrf.Frequency(1, 1, 1, unit="GHz")
    m = skrf.media.MLine(frequency=f, w=w * 1e-3, h=h * 1e-3, t=None, ep_r=er,
                         model="hammerstadjensen", disp="none",
                         diel="frequencyinvariant")
    e_hj = float(np.real(np.atleast_1d(m.ep_reff)[0]))
    r = microstrip_quasistatic(w, h, er)
    assert r.eps_eff == pytest.approx(e_hj, rel=5e-3), (r.eps_eff, e_hj)
    assert isinstance(r, QuasiStaticResult) and r.richardson


def test_cps_half_space_limit_and_air_line():
    """h→∞：εeff→(1+εr)/2 精确；εr=1：εeff=1 且 Z0 与共形映射闭式（Wadell/
    MathWorks MoM 口径）一致（20·b 域，实测 +0.03%）。"""
    r = cps_quasistatic(0.5, 0.5, 8.0, ER)
    assert r.eps_eff == pytest.approx((1 + ER) / 2, rel=3e-3)
    air = cps_quasistatic(2.95, 0.5, H, 1.0)
    assert air.eps_eff == pytest.approx(1.0, abs=1e-12)
    assert air.z0_air_ohm == pytest.approx(_cps_ri(2.95, 0.5, 1e6, 1.0)[1], rel=5e-3)


def test_cps_nominal_referee_pinned():
    """CPS 标称 w=2.95 gap=0.5 h=0.508 εr=3.66：εeff_FD=1.667（Richardson；单档
    1.671/1.669），与收尾批未入库临时 FD 的 ≈1.68 一致 ≤1%（refs §11.1 真值）。"""
    r = cps_quasistatic(2.95, 0.5, H, ER)
    assert r.eps_eff == pytest.approx(1.667, abs=0.006)
    assert abs(r.eps_eff / 1.68 - 1.0) <= 0.01
    assert r.eps_eff_coarse > r.eps_eff_fine > r.eps_eff     # 单调收敛向下
    assert r.z0_ohm == pytest.approx(150.42 / np.sqrt(r.eps_eff), rel=5e-3)


def test_suspended_stripline_limits_and_cohn_air():
    """h→b 全填充 εeff=εr、h→0 空气 εeff=1（精确）；空气 Z0 vs Cohn `_stripline_z0`
    零厚度闭式（Richardson 后 −0.1%）。"""
    full = suspended_stripline_quasistatic(0.731, 1.016, 1.016, ER, richardson=False)
    assert full.eps_eff == pytest.approx(ER, rel=1e-9)
    air = suspended_stripline_quasistatic(0.731, 1.016, 0.0, ER, richardson=False)
    assert air.eps_eff == pytest.approx(1.0, abs=1e-12)
    r = suspended_stripline_quasistatic(0.731, 1.016, H, ER)
    assert r.z0_air_ohm == pytest.approx(_stripline_z0(0.731, 1.016, 1.0), rel=5e-3)


def test_suspended_stripline_nominal_referee_pinned():
    """悬置带线标称 w=0.731 b=1.016 h=0.508 εr=3.66：εeff_FD=2.092（单档 2.084/
    2.088 收敛向上）、Z0=56.1Ω（refs §11.2 真值，FD 裁判本身不随闭式重定标变）——
    旧 q 式 2.641 高 +26%（重定标批已修：闭式现 −0.58%），旧口径 3.02/2.36 两份
    临时 FD 均撤（未过本文件基准）。"""
    r = suspended_stripline_quasistatic(0.731, 1.016, H, ER)
    assert r.eps_eff == pytest.approx(2.092, abs=0.01)
    assert r.eps_eff_coarse < r.eps_eff_fine < r.eps_eff
    assert r.z0_ohm == pytest.approx(56.1, abs=0.5)
    keys = set(r.as_dict())
    assert {"eps_eff", "z0_ohm", "z0_air_ohm", "d0_mm", "richardson", "n_nodes"} <= keys


def test_suspended_stripline_closed_form_tracks_referee_after_recalibration():
    """重定标闭式 `_suspended_stripline_ri`（2026-09-18 定标，softmin
    修正族）跟踪裁判（w=0.6 b=1.6 序列）：h/b=0.5 +0.23%、0.994 −0.12%（旧
    q 式中段 +22% 高估方向钉随重定标撤，换向为"残余 ≤2%"防静默漂移）。"""
    from rfauto.core.calculators import _suspended_stripline_ri

    mid = suspended_stripline_quasistatic(0.6, 1.6, 0.8, ER)
    assert abs(_suspended_stripline_ri(0.6, 1.6, 0.8, ER)[0]
               / mid.eps_eff - 1) < 0.02
    near_full = suspended_stripline_quasistatic(0.6, 1.6, 0.994 * 1.6, ER)
    assert abs(_suspended_stripline_ri(0.6, 1.6, 0.994 * 1.6, ER)[0]
               / near_full.eps_eff - 1) < 0.02


def test_domain_errors():
    with pytest.raises(ValueError):
        cps_quasistatic(0.0, 0.5, H, ER)
    with pytest.raises(ValueError):
        suspended_stripline_quasistatic(0.5, 1.0, 1.2, ER)
    with pytest.raises(ValueError):
        microstrip_quasistatic(1.0, 0.5, 0.5)
