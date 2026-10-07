"""MM-1 吸波体族+Rozanov 门锚测试（规格 规格深案 §A-4）。

全部离线合成零仿真。判据：

- Salisbury：λ/4 设计点**精确求值** Γ<−140dB（数值精度内，实测 ≈−319～−330dB；
  带栅格采样点因离零点有限距离只能到 −80～−120dB，那是物理不是锚）；设计式
  往返 design→reflection 谷位=f0（带取 [0.5,2]f0——Salisbury 在 3f0/5f0…
  奇数倍频还有等深零点，宽带 argmin 会漂到别处，非缺陷）；
- Jaumann：两层 vs 独立逐层 Zin 手链（传输线公式从 PEC 往前）≤0.1dB
  （实测 ~2e−14dB，锚收紧到 1e−6dB）；单层 εr=1 精确退化为 Salisbury
  （跨原语一致；εr>1 时两入口介质约定不同——jaumann 入射=自由空间、
  salisbury=同介质——不应相等）；低频电短→|Γ|→1（PEC 极限）；
- CA（circuit analog）：常数片阻抗三种入口（标量/标量 callable/常数表）
  与 salisbury_reflection 逐位一致（合成回收）；频变表线性插值中点 vs
  手工级联逐位回收；逆序/乱序表 ValueError；
- Rozanov（分频带下界语义）：|Γ|=1 带 → d_min=0 精确；平 Γ 带 → d_min 与
  闭式 Δλ·|lnΓ0|/(2π²) 逐位互证且 Γ0 减半 → d_min 恰翻倍；Salisbury 理想 Γ
  带积分 → 0<d_min≤d(λ/4)（下界≤实际厚度）且宽带积分收敛到 d（Salisbury
  已知饱和 Rozanov 界）。
- 守卫负例：rs≤0 / d≤0 / εr<1 / f≤0 / sheets 空·缺键 / 表逆序乱序 /
  callable 形状不符 / 频带逆序·乱序 / Γ=0 与 Γ>1 样本 → ValueError。

**规格 §A-4 勘误记档（#122：学术诚信优先于验收表全勾）**：规格退化例
"Γ=0 全吸收带→d_min→0" 方向与 Rozanov 定理原文（TAP 48(8):1230-1234,
2000：|∫ln|Γ|dλ|≤2π²d，深吸收⇒|∫| 增大⇒需更厚；全反 |Γ|=1 ⇒ d_min=0）
相反——本件按定理原文实现（web 检索复核 2026-10-02），Γ=0 样本按发散
如实 ValueError（理想零反射是测度零点；Salisbury 的孤立零点靠避开栅格
处理）。勘误待规格 D 载体裁决回写，测试不凑该反向锚。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.absorber import (
    circuit_analog_reflection,
    jaumann_reflection,
    rozanov_min_thickness,
    salisbury_design,
    salisbury_reflection,
)
from rfauto.core.metasurface_lut import C0_M_S, ETA0_OHM, _abcd_shunt, _abcd_tl

F0 = 10e9


# ─── Salisbury：设计式 + λ/4 零点 + 往返 ─────────────────────────────────────


def test_salisbury_design_formula():
    des = salisbury_design(F0)
    assert des["rs_ohm"] == pytest.approx(ETA0_OHM, rel=1e-12)
    assert des["d_m"] == pytest.approx(C0_M_S / (4.0 * F0), rel=1e-12)
    # 介质约定：η0/√εr 与 λ0/(4√εr)
    des4 = salisbury_design(F0, eps_r=4.0)
    assert des4["rs_ohm"] == pytest.approx(ETA0_OHM / 2.0, rel=1e-12)
    assert des4["d_m"] == pytest.approx(C0_M_S / (8.0 * F0), rel=1e-12)


@pytest.mark.parametrize("eps_r", [1.0, 2.2, 4.0])
def test_salisbury_exact_null_depth_at_quarter_wave(eps_r):
    """λ/4 设计点精确求值：Zin=Rs=η_in → Γ=0，数值精度内 <−140dB。"""
    des = salisbury_design(F0, eps_r)
    out = salisbury_reflection(np.array([F0]), des["d_m"], des["rs_ohm"], eps_r)
    assert out["gamma_db"][0] < -140.0


def test_salisbury_valley_roundtrip_dielectric():
    """design→reflection 谷位=f0 往返（带 [0.5,2]f0 只含第一零点，见模块头注）。"""
    eps_r = 2.2
    des = salisbury_design(F0, eps_r)
    f = np.linspace(0.5 * F0, 2.0 * F0, 30001)
    out = salisbury_reflection(f, des["d_m"], des["rs_ohm"], eps_r)
    iv = int(np.argmin(out["gamma_db"]))
    assert abs(f[iv] - F0) <= f[1] - f[0]
    assert out["gamma_db"][iv] < -60.0  # 有限栅格离零点的物理深度（精确零点另锚）


def test_salisbury_guards():
    with pytest.raises(ValueError):
        salisbury_reflection([F0], 1e-3, 0.0)  # rs=0
    with pytest.raises(ValueError):
        salisbury_reflection([F0], 1e-3, -377.0)  # rs<0
    with pytest.raises(ValueError):
        salisbury_reflection([F0], 0.0, 377.0)  # d=0
    with pytest.raises(ValueError):
        salisbury_reflection([F0], -1e-3, 377.0)  # d<0
    with pytest.raises(ValueError):
        salisbury_reflection([F0], 1e-3, 377.0, eps_r=0.5)  # εr<1
    with pytest.raises(ValueError):
        salisbury_reflection([-1.0], 1e-3, 377.0)  # f≤0
    with pytest.raises(ValueError):
        salisbury_design(0.0)
    with pytest.raises(ValueError):
        salisbury_design(F0, eps_r=0.9)


# ─── Jaumann：两层合成回收 + 退化 + 极限 ─────────────────────────────────────


def _manual_jaumann_gamma(f_hz, sheets):
    """独立逐层 Zin 手链（传输线公式，从 PEC 往前；与 ABCD 路径互为独立实现）。"""
    gammas = []
    for fv in np.atleast_1d(f_hz):
        z = 0.0 + 0.0j  # PEC
        for sh in reversed(sheets):
            eta = ETA0_OHM / math.sqrt(sh["eps_r"])
            th = 2.0 * math.pi * float(fv) * math.sqrt(sh["eps_r"]) / C0_M_S * sh["d_m"]
            z = eta * (z + 1j * eta * np.tan(th)) / (eta + 1j * z * np.tan(th))
            z = sh["rs_ohm"] * z / (sh["rs_ohm"] + z)
        gammas.append((z - ETA0_OHM) / (z + ETA0_OHM))
    return np.asarray(gammas, dtype=complex)


SHEETS_2L = [
    {"rs_ohm": 450.0, "d_m": 5.1e-3, "eps_r": 1.5},
    {"rs_ohm": 150.0, "d_m": 3.4e-3, "eps_r": 2.2},
]


def test_jaumann_two_layer_recovery_vs_manual_chain():
    f = np.linspace(1e9, 40e9, 4001)
    out = jaumann_reflection(f, SHEETS_2L)
    gm = _manual_jaumann_gamma(f, SHEETS_2L)
    diff_db = np.abs(20.0 * np.log10(np.abs(out["gamma"])) - 20.0 * np.log10(np.abs(gm)))
    # 实测 ~2e-14dB（同机确定性内核）；规格门 0.1dB，锚收紧到 1e-6dB 抓回归
    assert diff_db.max() <= 1e-6


def test_jaumann_single_layer_reduces_to_salisbury():
    """单层 εr=1、Rs=η0、d=λ0/4 精确退化为经典 Salisbury（两入口约定一致点）。"""
    des = salisbury_design(F0)
    f = np.linspace(1e9, 30e9, 2001)
    out_j = jaumann_reflection(f, [{"rs_ohm": des["rs_ohm"], "d_m": des["d_m"], "eps_r": 1.0}])
    out_s = salisbury_reflection(f, des["d_m"], des["rs_ohm"], 1.0)
    assert np.allclose(out_j["gamma"], out_s["gamma"], rtol=0.0, atol=1e-12)


def test_jaumann_low_freq_tends_pec():
    """低频电短：介质段→短路，片被短路→|Γ|→1（PEC 极限）。"""
    out = jaumann_reflection(np.array([1e6]), SHEETS_2L)
    assert abs(out["gamma"][0]) > 0.99


def test_jaumann_guards():
    with pytest.raises(ValueError):
        jaumann_reflection([F0], [])
    with pytest.raises(ValueError):
        jaumann_reflection([F0], [{"rs_ohm": -1.0, "d_m": 1e-3}])
    with pytest.raises(ValueError):
        jaumann_reflection([F0], [{"rs_ohm": 377.0, "d_m": 0.0}])
    with pytest.raises(ValueError):
        jaumann_reflection([F0], [{"rs_ohm": 377.0}])  # 缺 d
    with pytest.raises(ValueError):
        jaumann_reflection([F0], [{"rs_ohm": 377.0, "d_m": 1e-3, "eps_r": 0.8}])


# ─── CA：频变片阻抗入口（常数回收 + 表插值回收 + 守卫）───────────────────────


def test_circuit_analog_constant_sheet_equals_salisbury():
    """常数片阻抗三种入口（标量/标量 callable/常数表）== salisbury（逐位）。"""
    f = np.array([1e9, 10e9, 20e9, 40e9])
    des = salisbury_design(F0)
    ref = salisbury_reflection(f, des["d_m"], 300.0, 1.0)
    for entry in (
        300.0 + 0j,
        lambda x: 300.0 + 0j,
        lambda x: np.full(np.shape(x), 300.0 + 0j),
        (np.array([0.5e9, 100e9]), np.array([300.0 + 0j, 300.0 + 0j])),
    ):
        out = circuit_analog_reflection(f, entry, des["d_m"], 1.0)
        assert np.array_equal(out["gamma"], ref["gamma"])


def test_circuit_analog_freq_table_linear_interp_midpoint():
    """频变表：带内中点线性插值（实部/虚部分别）vs 手工常数级联逐位回收。"""
    tab_f = np.array([1e9, 21e9])
    tab_z = np.array([300.0 + 50.0j, 400.0 - 50.0j])
    f_mid = 11e9  # 线性插值中点 → z=(300+50j+400-50j)/2=350+0j
    des = salisbury_design(F0)
    out = circuit_analog_reflection(np.array([f_mid]), (tab_f, tab_z), des["d_m"], 1.0)
    abcd = _abcd_shunt(350.0 + 0j) @ _abcd_tl(
        ETA0_OHM, 2.0 * math.pi * f_mid / C0_M_S, des["d_m"]
    )
    zin = complex(abcd[0, 1] / abcd[1, 1])
    gamma_manual = (zin - ETA0_OHM) / (zin + ETA0_OHM)
    assert out["gamma"][0] == pytest.approx(gamma_manual, rel=1e-12, abs=1e-12)


def test_circuit_analog_guards():
    des = salisbury_design(F0)
    with pytest.raises(ValueError):
        circuit_analog_reflection([F0], (np.array([2e9, 1e9]), np.array([300j, 300j])), des["d_m"])
    with pytest.raises(ValueError):  # 乱序
        circuit_analog_reflection(
            [F0], (np.array([1e9, 3e9, 2e9]), np.array([300j] * 3)), des["d_m"]
        )
    with pytest.raises(ValueError):  # callable 形状不符
        circuit_analog_reflection([F0], lambda x: np.array([1.0, 2.0]), des["d_m"])
    with pytest.raises(ValueError):  # Z=0 短路屏超出 shunt 原语域
        circuit_analog_reflection([F0], (np.array([1e9, 2e9]), np.array([0j, 0j])), des["d_m"])
    with pytest.raises(ValueError):
        circuit_analog_reflection([F0], 300.0 + 0j, 0.0)
    with pytest.raises(ValueError):
        circuit_analog_reflection([F0], (np.array([1e9]), np.array([300j])), des["d_m"])  # 表 <2 点


# ─── Rozanov：分频带下界语义（含规格退化例方向勘误，见文件头注）──────────────


def test_rozanov_flat_total_reflection_gives_zero():
    """全反带（|Γ|=1，ln|Γ|=0）→ d_min=0 精确（定理方向的退化锚）。"""
    f = np.linspace(1e9, 20e9, 400)
    r = rozanov_min_thickness(f, np.ones_like(f))
    assert r["d_min_m"] == 0.0
    assert r["band_hz"] == (1e9, 20e9)
    assert r["band_lambda_m"] == pytest.approx((C0_M_S / 20e9, C0_M_S / 1e9), rel=1e-12)


def test_rozanov_flat_gamma_exact_proportional():
    """平 Γ 带：d_min 与闭式 Δλ·|lnΓ0|/(2π²) 互证；Γ0 减半 → d_min 恰翻倍。"""
    f = np.linspace(1e9, 20e9, 400)
    r_half = rozanov_min_thickness(f, np.full_like(f, 0.5))
    r_quart = rozanov_min_thickness(f, np.full_like(f, 0.25))
    closed = (C0_M_S / 1e9 - C0_M_S / 20e9) * abs(math.log(0.5)) / (2.0 * math.pi**2)
    assert r_half["d_min_m"] == pytest.approx(closed, rel=1e-12)
    assert r_quart["d_min_m"] / r_half["d_min_m"] == pytest.approx(2.0, rel=1e-12)


def test_rozanov_salisbury_band_lower_bound_self_consistent():
    """Salisbury 理想 Γ 带积分：0<d_min≤d(λ/4)（下界≤实际厚度）+ 宽带收敛到 d。

    分带下界随带宽增长趋向实际厚度（Salisbury 已知饱和全谱 Rozanov 界）；
    栅格避开 f0 的孤立零点（Γ=0 测度零点，见文件头注勘误）。
    """
    des = salisbury_design(F0)
    d_actual = des["d_m"]
    for lo, hi, n, ratio_lo in ((2e9, 50e9, 24001, 0.5), (0.5e9, 100e9, 48001, 0.85)):
        fb = np.linspace(lo, hi, n)
        fb = fb[np.abs(fb - F0) > 1.0]
        gb = salisbury_reflection(fb, des["d_m"], des["rs_ohm"])
        r = rozanov_min_thickness(fb, np.abs(gb["gamma"]))
        assert 0.0 < r["d_min_m"] <= d_actual * (1.0 + 1e-9)
        assert r["d_min_m"] / d_actual > ratio_lo


def test_rozanov_guards():
    f = np.linspace(1e9, 20e9, 100)
    with pytest.raises(ValueError):  # 频带逆序
        rozanov_min_thickness(f[::-1], np.full(100, 0.5))
    with pytest.raises(ValueError):  # 乱序
        rozanov_min_thickness(np.array([2e9, 1e9, 3e9]), np.full(3, 0.5))
    with pytest.raises(ValueError):  # Γ=0 样本（ln0 发散；测度零点须避开栅格）
        rozanov_min_thickness(f, np.full(100, 0.0))
    with pytest.raises(ValueError):  # Γ>1 非无源
        rozanov_min_thickness(f, np.full(100, 1.2))
    with pytest.raises(ValueError):
        rozanov_min_thickness(f, np.full(50, 0.5))  # 长度不匹配
    with pytest.raises(ValueError):
        rozanov_min_thickness([1e9], [0.5])  # 单点不成带
