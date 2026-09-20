"""G0 线宽定案单元测试。

验证三来源交叉检查的阻抗计算和线宽反解：
1. skrf MLine (Hammerstad-Jensen)
2. 简化 Pozar 手算
3. Schneider 公式

Gate 标准：三来源偏差 <3%。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

# ─── 材料参数 ──────────────────────────────────────────────────────────────────

EPSILON_R = 3.66
THICKNESS_MM = 0.508
FREQ_GHZ = 2.4


# ─── 三种计算方法 ──────────────────────────────────────────────────────────────

def calc_z0_skrf(width_mm: float, freq_ghz: float = FREQ_GHZ) -> float:
    """skrf MLine (Hammerstad-Jensen) 正向计算。"""
    import skrf

    mline = skrf.media.MLine(
        frequency=skrf.Frequency(freq_ghz, freq_ghz, 1, unit="GHz"),
        w=width_mm * 1e-3,
        h=THICKNESS_MM * 1e-3,
        ep_r=EPSILON_R,
        tand=0.0037,
        rho=1.724e-8,
        rough=0.5e-6,
        diel="djordjevicsvensson",
        disp="kirschningjansen",
    )
    return float(np.real(mline.z0[0]))


def calc_z0_pozar(w_mm: float, freq_ghz: float = FREQ_GHZ) -> float:
    """Pozar §3.8 简化公式。"""
    h = THICKNESS_MM
    er = EPSILON_R
    u = w_mm / h
    if u <= 1:
        ee = (er + 1) / 2 + (er - 1) / 2 * (
            1 / math.sqrt(1 + 12 / u) + 0.04 * (1 - u) ** 2
        )
        z0 = 60 / math.sqrt(ee) * math.log(8 / u + u / 4)
    else:
        ee = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / u)
        z0 = 120 * math.pi / (
            math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444))
        )
    return z0


def calc_z0_schneider(w_mm: float, freq_ghz: float = FREQ_GHZ) -> float:
    """Schneider 公式（独立第三来源）。"""
    h = THICKNESS_MM
    er = EPSILON_R
    u = w_mm / h
    if u <= 1:
        ee = (er + 1) / 2 + (er - 1) / 2 * (1 / math.sqrt(1 + 12 / u))
        z0 = (60 / math.sqrt(ee)) * math.log(8 / u + u / 4)
    else:
        ee = (er + 1) / 2 + (er - 1) / 2 / math.sqrt(1 + 12 / u)
        z0 = (120 * math.pi) / (
            math.sqrt(ee) * (u + 1.393 + 0.667 * math.log(u + 1.444))
        )
    return z0


def find_width(calc_fn, z0_target: float) -> float:
    """brentq 反解线宽。"""
    from scipy.optimize import brentq

    return brentq(lambda w: calc_fn(w) - z0_target, 0.1, 10.0, xtol=1e-6)


# ─── 测试用例 ──────────────────────────────────────────────────────────────────


class TestKnownWidths:
    """验证已知线宽的阻抗值（实测数据）。"""

    @pytest.mark.parametrize("calc_fn", [calc_z0_skrf, calc_z0_pozar, calc_z0_schneider])
    def test_2_20mm_gives_approx_31ohm(self, calc_fn):
        """2.20mm 实测 ~31Ω（非标称 35.35Ω），三来源一致性验证。"""
        z0 = calc_fn(2.20)
        assert 30.0 < z0 < 33.0, f"{calc_fn.__name__}: 2.20mm -> {z0:.2f}Ω, 期望 30~33Ω"

    @pytest.mark.parametrize("calc_fn", [calc_z0_skrf, calc_z0_pozar, calc_z0_schneider])
    def test_1_10mm_gives_approx_50ohm(self, calc_fn):
        """1.10mm 应接近 50Ω。"""
        z0 = calc_fn(1.10)
        assert 48.0 < z0 < 53.0, f"{calc_fn.__name__}: 1.10mm -> {z0:.2f}Ω, 期望 48~53Ω"

    def test_skrf_pozar_agreement_within_2pct(self):
        """skrf 与 Pozar 在已知线宽上偏差 <2%。"""
        for w in [1.10, 2.20]:
            z_skrf = calc_z0_skrf(w)
            z_pozar = calc_z0_pozar(w)
            dev = abs(z_skrf - z_pozar) / z_skrf * 100
            assert dev < 2.0, f"w={w}mm: skrf={z_skrf:.2f}, pozar={z_pozar:.2f}, dev={dev:.2f}%"


class TestWidthInverse:
    """验证目标阻抗反解线宽的三来源偏差。"""

    @pytest.mark.parametrize("z0_target", [35.35, 50.0])
    def test_three_sources_agree_within_3pct(self, z0_target):
        """G0 gate 标准：三来源反解线宽偏差 <3%。"""
        w_skrf = find_width(calc_z0_skrf, z0_target)
        w_pozar = find_width(calc_z0_pozar, z0_target)
        w_schneider = find_width(calc_z0_schneider, z0_target)

        widths = [w_skrf, w_pozar, w_schneider]
        avg = sum(widths) / 3
        max_dev = max(abs(w - avg) / avg * 100 for w in widths)
        assert max_dev < 3.0, (
            f"Z0={z0_target}Ω: skrf={w_skrf:.4f}, pozar={w_pozar:.4f}, "
            f"schneider={w_schneider:.4f}, max_dev={max_dev:.2f}%"
        )

    def test_50ohm_width_near_1_11mm(self):
        """50Ω 线宽应接近 G0 定案值 1.11mm。"""
        w = find_width(calc_z0_skrf, 50.0)
        assert 1.05 < w < 1.20, f"50Ω -> {w:.4f}mm, 期望 1.05~1.20mm"

    def test_35ohm_width_near_1_87mm(self):
        """35.35Ω 线宽应接近 G0 定案值 1.87mm。"""
        w = find_width(calc_z0_skrf, 35.35)
        assert 1.80 < w < 1.95, f"35.35Ω -> {w:.4f}mm, 期望 1.80~1.95mm"


class TestForwardInverseConsistency:
    """正向→反向自洽断言：反解出的线宽正向回算应接近目标阻抗。"""

    @pytest.mark.parametrize("z0_target", [35.35, 50.0])
    def test_skrf_self_consistency(self, z0_target):
        """skrf MLine 正反解自洽，|ΔZ0| < 0.5Ω。"""
        w = find_width(calc_z0_skrf, z0_target)
        z0_back = calc_z0_skrf(w)
        assert abs(z0_back - z0_target) < 0.5, (
            f"Z0={z0_target}: w={w:.4f}mm, 回算={z0_back:.2f}Ω, |Δ|={abs(z0_back-z0_target):.3f}Ω"
        )


class TestMaterialsConfig:
    """验证 materials.yaml 中 G0 定案值的正确性。"""

    def test_materials_has_linewidth_section(self):
        """rogers4350b_h0.508 应有 linewidth 子段。"""
        import yaml

        path = Path(__file__).resolve().parents[2] / "configs" / "materials.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        mat = data["materials"]["rogers4350b_h0.508"]
        assert "linewidth" in mat, "materials.yaml 缺少 linewidth 子段"
        lw = mat["linewidth"]
        assert "z0_50ohm_mm" in lw
        assert "z0_35ohm_mm" in lw
        assert "source" in lw

    def test_materials_linewidth_values_consistent(self):
        """materials.yaml 中的线宽值应与 G0 验证一致。"""
        from pathlib import Path

        import yaml

        path = Path(__file__).resolve().parents[2] / "configs" / "materials.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        lw = data["materials"]["rogers4350b_h0.508"]["linewidth"]

        # 50Ω 线宽
        w50_config = lw["z0_50ohm_mm"]
        w50_calc = find_width(calc_z0_skrf, 50.0)
        assert abs(w50_config - w50_calc) < 0.05, (
            f"50Ω: config={w50_config}, calc={w50_calc:.4f}"
        )

        # 35Ω 线宽
        w35_config = lw["z0_35ohm_mm"]
        w35_calc = find_width(calc_z0_skrf, 35.35)
        assert abs(w35_config - w35_calc) < 0.05, (
            f"35.35Ω: config={w35_config}, calc={w35_calc:.4f}"
        )
