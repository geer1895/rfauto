"""aurora_e W4-S18：EC-21 极化传输面度量 CALC 注册面单测（ΔIPD/ΔIL/轴比/
微分群延迟差）。

裁判口径（内核立规注记 铁律 5/#118：来源写明、双源/回收互证、不自证）：

- **薄度守卫（主判据）**：三键 wrapper 输出与 core/polarization 直调路径
  **逐位一致**（``==`` 原子比较）——wrapper 零数值变换（pol_axial_ratio
  仅 deg→rad 单点换算，与 core 直调同式复刻），字段映射 note/source 另计。
- **#118 数值锚**：
  - cot 恒等：等幅 δ=45° → AR=1+√2=cot(22.5°)（Balanis §4.4 等幅椭圆
    特例独立闭式，与 D-判别式路线互证）；
  - 圆极化：E1=E2, δ=±90° → AR=1（0 dB）、δ=+90° → LH（IEEE Std
    145-1983，x̂−jŷ=RH 同构反号）；
  - 时域第三法：闭式 vs axial_ratio_time_domain（独立实现）一致 ≤1e-6 dB；
  - 群延迟回收：线性相位网络 φ=−360·f·τ 合成系数 → τ_g 精确回收
    （20/50 ps，rel ≤1e-9）；等延迟纯转换（ΔIPD 常数 ±90°）→ delta_tau_g
    =0；ΔIPD 主值扫描一致性。
- **单源性**：pol_delta_ipd_il 的极化态字段与 core polarization_state
  直调逐位一致（同一 §4.4 链，非第二实现）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.polarization_reg import (
    pol_axial_ratio,
    pol_delta_ipd_il,
    pol_group_delay_diff,
)
from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY
from rfauto.core.polarization import (
    SENSE_LH,
    SENSE_LINEAR,
    SENSE_RH,
    _wrap180_deg,
    axial_ratio,
    axial_ratio_db,
    axial_ratio_time_domain,
    delta_ipd_il,
    polarization_state,
    tilt_angle_deg,
)

# 等幅 δ=45° 解析锚：AR = cot(δ/2) = 1+√2（Balanis §4.4 特例恒等）
_AR_45_DEG_EXPECT = 1.0 + math.sqrt(2.0)


# ─── pol_axial_ratio：锚 + 薄度守卫 ──────────────────────────────────────────

def test_pol_axial_ratio_circular_and_45deg_anchors():
    """圆极化 0 dB 主锚 + 等幅 45° cot 恒等（#118 双式互证）。"""
    out = pol_axial_ratio(1.0, 1.0, -90.0)
    assert out["ar_linear"] == 1.0
    assert out["ar_db"] == 0.0
    assert out["ar_db_time_domain"] == pytest.approx(0.0, abs=1e-6)
    out45 = pol_axial_ratio(1.0, 1.0, 45.0)
    assert out45["ar_linear"] == pytest.approx(_AR_45_DEG_EXPECT, rel=1e-12)
    assert out45["ar_linear"] == pytest.approx(
        1.0 / math.tan(math.radians(22.5)), rel=1e-12)
    assert out45["ar_db"] == pytest.approx(
        20.0 * math.log10(_AR_45_DEG_EXPECT), rel=1e-12)


def test_pol_axial_ratio_linear_cap_and_third_method():
    """线极化封顶 100 dB（真值发散如实）+ 时域第三法一致（数值地板 2e-5 dB）。"""
    for delta in (0.0, 180.0):
        out = pol_axial_ratio(1.0, 0.5, delta)
        assert out["ar_db"] == 100.0  # AR_LINEAR_DB_CAP
        # 第三法（独立数值实现）在同一封顶语义下逐点对照闭式
        assert out["ar_db_time_domain"] == pytest.approx(out["ar_db"], abs=2e-5)
    # 一般椭圆点闭式 vs 时域（4096 点采样地板 ~1e-5 dB，门取 2e-5 预声明）
    out = pol_axial_ratio(0.8, 1.0, 30.0)
    td = 20.0 * math.log10(axial_ratio_time_domain(0.8, 1.0, math.radians(30.0)))
    assert out["ar_db"] == pytest.approx(td, abs=2e-5)
    assert out["tilt_deg"] == tilt_angle_deg(0.8, 1.0, math.radians(30.0))


def test_pol_axial_ratio_thinness_guard_bitwise():
    """薄度守卫：wrapper 输出与 core 直调逐位一致（== 原子比较）。"""
    e1, e2, d_deg = 0.6, 1.0, -123.0
    d_rad = d_deg * math.pi / 180.0
    out = pol_axial_ratio(e1, e2, d_deg)
    assert out["ar_linear"] == axial_ratio(e1, e2, d_rad)
    assert out["ar_db"] == axial_ratio_db(e1, e2, d_rad)
    assert out["tilt_deg"] == tilt_angle_deg(e1, e2, d_rad)


def test_pol_axial_ratio_invalid_inputs():
    """幅度负值/全零（core 守卫透传）+ bool 拒收（deg→rad 面本族自守）。"""
    with pytest.raises(ValueError, match="幅度必须"):
        pol_axial_ratio(-1.0, 1.0, 0.0)
    with pytest.raises(ValueError, match="全零"):
        pol_axial_ratio(0.0, 0.0, 45.0)
    with pytest.raises(ValueError, match="不接受 bool"):
        pol_axial_ratio(1.0, 1.0, True)


# ─── pol_delta_ipd_il：ΔIPD/ΔIL 锚 + 单源性 ─────────────────────────────────

def test_pol_delta_ipd_il_circular_pair_anchors():
    """±90° 等幅 → ΔIPD/ΔIL/AR/旋向全锚（LH/RH 反号，IEEE 145 口径）。"""
    lh = pol_delta_ipd_il([1.0, 0.0], [0.0, 1.0])  # δ=+90°
    assert lh["delta_ipd_deg"] == 90.0
    assert lh["delta_il_db"] == 0.0
    assert lh["ar_linear"] == 1.0
    assert lh["ar_db"] == 0.0
    assert lh["sense_code"] == SENSE_LH
    assert lh["sense"] == "LH"
    assert lh["regime"] == "circular"
    rh = pol_delta_ipd_il([1.0, 0.0], [0.0, -1.0])  # δ=−90°
    assert rh["delta_ipd_deg"] == -90.0
    assert rh["sense_code"] == SENSE_RH


def test_pol_delta_ipd_il_wrapping_and_il_anchor():
    """主值包裹（±120° 构造+跨界对）+ ΔIL=20log10(|ty|/|tx|) 幅度锚。"""
    out = pol_delta_ipd_il(1.0 + 0j, complex(-1.0, math.sqrt(3.0)))  # +120°
    assert out["delta_ipd_deg"] == pytest.approx(120.0, rel=1e-12)
    crossed = pol_delta_ipd_il(1.0 + 0j, complex(-1.0, -math.sqrt(3.0)))
    assert crossed["delta_ipd_deg"] == pytest.approx(-120.0, rel=1e-12)
    imb = pol_delta_ipd_il(1.0 + 0j, 0.5 + 0j)  # 同相幅度失衡
    assert imb["delta_ipd_deg"] == 0.0
    assert imb["delta_il_db"] == pytest.approx(20.0 * math.log10(0.5), rel=1e-12)
    assert imb["sense_code"] == SENSE_LINEAR
    assert imb["regime"] == "linear"


def test_pol_delta_ipd_il_single_source_vs_polarization_state():
    """单源性：极化态字段与 core polarization_state 直调逐位一致（#118）。"""
    tx = complex(0.8, -0.2)
    ty = complex(0.3, 0.95)
    out = delta_ipd_il(tx, ty)
    ref = polarization_state(tx, ty)
    assert out["ar_linear"] == ref["ar_linear"]
    assert out["ar_db"] == ref["ar_db"]
    assert out["tilt_deg"] == ref["tilt_deg"]
    assert out["sense_code"] == ref["sense_code"]


def test_pol_delta_ipd_il_zero_component_rejected():
    """任一分量为 0 → ValueError（相位无定义不猜，预声明）。"""
    with pytest.raises(ValueError, match="相位无定义"):
        delta_ipd_il(0.0, 1.0 + 0j)
    with pytest.raises(ValueError, match="相位无定义"):
        delta_ipd_il(1.0 + 0j, 0.0)


# ─── pol_group_delay_diff：群延迟回收锚 ──────────────────────────────────────

def _linear_phase_coeff(f_ghz: float, tau_s: float, *, extra_phase_deg: float = 0.0) -> list[float]:
    """线性相位网络合成透射系数 [re,im]：φ(f)=−360·f·τ+extra（度）。"""
    ph_deg = -360.0 * f_ghz * 1e9 * tau_s + extra_phase_deg
    ph = math.radians(ph_deg)
    return [math.cos(ph), math.sin(ph)]


def test_pol_group_delay_diff_recovers_linear_phase_tau():
    """线性相位回收锚：τ_x=20ps/τ_y=50ps → 逐路精确回收（rel ≤1e-9）。"""
    f1, f2 = 10.0, 10.01
    tau_x, tau_y = 20e-12, 50e-12
    out = pol_group_delay_diff(
        f1, f2,
        _linear_phase_coeff(f1, tau_x), _linear_phase_coeff(f2, tau_x),
        _linear_phase_coeff(f1, tau_y), _linear_phase_coeff(f2, tau_y))
    assert out["tau_g_x_ps"] == pytest.approx(20.0, rel=1e-9)
    assert out["tau_g_y_ps"] == pytest.approx(50.0, rel=1e-9)
    assert out["delta_tau_g_ps"] == pytest.approx(30.0, rel=1e-9)
    # 恒定 ΔIPD（=−360·f0·Δτ@f1 处）与扫频变化量小而一致
    expected_ipd_f1 = -360.0 * f1 * 1e9 * (tau_y - tau_x)  # −108°
    assert out["delta_ipd_deg_f1"] == pytest.approx(expected_ipd_f1, rel=1e-9)
    expected_ipd_f2 = -360.0 * f2 * 1e9 * (tau_y - tau_x)
    assert out["delta_ipd_sweep_deg"] == pytest.approx(
        expected_ipd_f2 - expected_ipd_f1, rel=1e-6)


def test_pol_group_delay_diff_equal_delay_pure_conversion_zero_delta():
    """等延迟纯转换锚：ΔIPD 常数 ±90° → delta_tau_g=0（三角往返 ulp 地板下）。"""
    f1, f2 = 10.0, 10.5
    out = pol_group_delay_diff(
        f1, f2,
        _linear_phase_coeff(f1, 30e-12), _linear_phase_coeff(f2, 30e-12),
        _linear_phase_coeff(f1, 30e-12, extra_phase_deg=90.0),
        _linear_phase_coeff(f2, 30e-12, extra_phase_deg=90.0))
    # atan2/cos/sin 往返 ulp 噪声地板 ~1e-14 ps（实测 1.8e-14），门取 1e-9 ps
    assert abs(out["delta_tau_g_ps"]) <= 1e-9
    assert out["delta_ipd_deg_f1"] == pytest.approx(90.0, rel=1e-9)
    assert out["delta_ipd_deg_f2"] == pytest.approx(90.0, rel=1e-9)
    assert abs(out["delta_ipd_sweep_deg"]) <= 1e-9
    # 与 delta_ipd_il 单点口径互证（f1 频点）
    single = delta_ipd_il(
        _linear_phase_coeff(f1, 30e-12),
        _linear_phase_coeff(f1, 30e-12, extra_phase_deg=90.0))
    assert single["delta_ipd_deg"] == pytest.approx(
        out["delta_ipd_deg_f1"], rel=1e-12)


def test_pol_group_delay_diff_invalid_inputs():
    """f2<=f1 / 零系数 / bool → ValueError（core 守卫透传）。"""
    c = _linear_phase_coeff(10.0, 20e-12)
    with pytest.raises(ValueError, match="必须 > f1_ghz"):
        pol_group_delay_diff(10.0, 10.0, c, c, c, c)
    with pytest.raises(ValueError, match="相位无定义"):
        pol_group_delay_diff(
            10.0, 11.0, [0.0, 0.0], c, c, c)
    with pytest.raises(ValueError):
        pol_group_delay_diff(True, 11.0, c, c, c, c)


# ─── core 面小件：主值包裹 / 复数收敛器 ──────────────────────────────────────

def test_wrap180_deg_principal_interval():
    """主值包裹 (−180°, 180°]：边界 +180 归 +180、−180 归 +180（半开）。"""
    assert _wrap180_deg(0.0) == 0.0
    assert _wrap180_deg(90.0) == 90.0
    assert _wrap180_deg(180.0) == 180.0
    assert _wrap180_deg(-180.0) == 180.0
    assert _wrap180_deg(270.0) == -90.0
    assert _wrap180_deg(-270.0) == 90.0
    assert _wrap180_deg(540.0) == 180.0
    assert _wrap180_deg(-90.0 - 360.0 * 3) == -90.0


def test_pol_keys_registered_in_registry_with_group():
    """注册表三键在册 + 天线与阵列分组 + required 元数据自洽。"""
    for key in ("pol_axial_ratio", "pol_delta_ipd_il", "pol_group_delay_diff"):
        spec = CALCULATOR_REGISTRY.get(key)
        assert spec.name == key
        rows = {r["name"]: r for r in
                CALCULATOR_REGISTRY.describe(include_experimental=True)}
        assert rows[key]["group"] == "天线与阵列"
        assert rows[key]["experimental"] is False
    req = CALCULATOR_REGISTRY.get("pol_group_delay_diff").required
    assert set(req) == {"f1_ghz", "f2_ghz", "t_x_f1", "t_x_f2",
                        "t_y_f1", "t_y_f2"}


def test_pol_service_envelope_ok():
    """service 层信封 ok=True（薄壳直连，信封构造器口径）。"""
    from rfauto.service.calculator_service import run_calculator

    res = run_calculator("pol_delta_ipd_il",
                         {"t_x": [1.0, 0.0], "t_y": [0.0, 1.0]})
    assert res["ok"] is True
    assert res["result"]["delta_ipd_deg"] == 90.0
    assert res["result"]["ar_db"] == 0.0
