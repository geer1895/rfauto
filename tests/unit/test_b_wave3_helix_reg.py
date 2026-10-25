"""批 B Wave3 G17：helical（轴向模螺旋）CALC 注册面薄注册单测。

裁判口径（规格包 runs/aurora_c/batch_b_wave3_specs/G17_helical_axial.md ④）：

- **薄度守卫（主判据）**：三键 wrapper 输出与 core/helix_axial 直调路径
  **逐位一致**（``==`` 原子比较，非 approx）——wrapper 只做参数单位换算
  （GHz→Hz ×1e9、mm→m ×1e-3 及输出逆向同式换算）与字段映射，不做任何
  数值变换/round；本测试按"同一换算式作用于 core 直调值"逐字段复刻。
- **#118 纪律**：数值锚树（Balanis §10.3.1 工作例 H1-H4、N×2 标度 H5、
  恰等出域 H6）已在 tests/unit/test_helix_axial.py 落库——本文件不重复
  裁判物理，只新增 H1 锚值经 wrapper 的透传复核（同一实现路径，非第二
  路线）与注册面五钉行为（透传拒绝/恰等 verdict/warnings 透传/信封）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import helix_axial
from rfauto.core.calc_families.helix_axial_reg import (
    helix_axial_bandwidth,
    helix_axial_design,
    helix_axial_performance,
)
from rfauto.service.calculator_service import run_calculator

# Balanis §10.3.1 工作例（与 test_helix_axial.py 同源常量；此处只作透传复核）
_F0_GHZ, _N, _ALPHA, _CL = 10.0, 10.0, 14.0, 0.95


# ─── 薄度守卫（主判据）：wrapper == core 直调逐位 ─────────────────────────────


def test_performance_thin_wrapper_bitwise() -> None:
    perf = helix_axial.kraus_performance(
        _F0_GHZ * 1e9, _N, _ALPHA, c_lambda=_CL).to_dict()
    out = helix_axial_performance(
        _F0_GHZ, _N, _ALPHA, c_lambda=_CL)
    # 数值字段：同一换算式作用于 core 直调值后逐位 ==
    assert out["f0_ghz"] == perf["f0_hz"] / 1e9
    assert out["wavelength_mm"] == perf["wavelength_m"] * 1e3
    assert out["diameter_mm"] == perf["diameter_m"] * 1e3
    assert out["circumference_mm"] == perf["circumference_m"] * 1e3
    assert out["pitch_mm"] == perf["pitch_m"] * 1e3
    # 透传字段（角度/无量纲/嵌套）逐位
    for key in ("n_turns", "alpha_deg", "c_lambda", "s_lambda", "hpbw_deg",
                "fnbw_deg", "directivity", "directivity_db",
                "input_impedance_ohm", "axial_ratio", "polarization"):
        assert out[key] == perf[key], key
    assert out["axial_mode"] == perf["axial_mode"]
    assert out["warnings"] == perf["warnings"]


def test_performance_thin_wrapper_diameter_route_bitwise() -> None:
    d_mm = 9.06555580255019
    perf = helix_axial.kraus_performance(
        _F0_GHZ * 1e9, _N, _ALPHA, diameter_m=d_mm * 1e-3,
        include_axial_ratio=False).to_dict()
    out = helix_axial_performance(
        _F0_GHZ, _N, _ALPHA, diameter_mm=d_mm, include_axial_ratio=False)
    assert out["diameter_mm"] == perf["diameter_m"] * 1e3
    assert out["wavelength_mm"] == perf["wavelength_m"] * 1e3
    assert out["hpbw_deg"] == perf["hpbw_deg"]
    assert out["axial_ratio"] is None  # include_axial_ratio=False 透传
    assert perf["axial_ratio"] is None


def test_design_thin_wrapper_bitwise_for_n_turns() -> None:
    design = helix_axial.design_for_n_turns(
        _F0_GHZ * 1e9, 10.0, 13.0,
        target_metric="directivity", target_value=30.0).to_dict()
    out = helix_axial_design(
        _F0_GHZ, n_turns=10.0, alpha_deg=13.0,
        target_metric="directivity", target_value=30.0)
    assert out["route"] == "for_n_turns"
    assert out["f0_ghz"] == design["f0_hz"] / 1e9
    assert out["diameter_mm"] == design["diameter_m"] * 1e3
    assert out["circumference_mm"] == design["circumference_m"] * 1e3
    assert out["pitch_mm"] == design["pitch_m"] * 1e3
    assert out["axial_length_mm"] == design["axial_length_m"] * 1e3
    for key in ("n_turns", "alpha_deg", "target_metric", "target_value",
                "c_lambda", "warnings"):
        assert out[key] == design[key], key
    assert out["performance"]["hpbw_deg"] == design["performance"]["hpbw_deg"]
    assert out["performance"]["pitch_mm"] == (
        design["performance"]["pitch_m"] * 1e3)


def test_design_optimal_route_bitwise() -> None:
    design = helix_axial.design_optimal(
        _F0_GHZ * 1e9, 13.0, target_metric="hpbw_deg", target_value=36.0,
        n_min=4, n_max=32).to_dict()
    out = helix_axial_design(
        _F0_GHZ, alpha_deg=13.0, target_metric="hpbw_deg",
        target_value=36.0, n_min=4, n_max=32)
    assert out["route"] == "optimal"
    assert out["n_turns"] == design["n_turns"]
    assert out["c_lambda"] == design["c_lambda"]
    assert out["diameter_mm"] == design["diameter_m"] * 1e3
    # optimal=扫 N 选 |C_λ-1| 最小：核验 route 语义（重算扫描一致）
    tan_a = math.tan(math.radians(13.0))
    best = min(
        ((abs((52.0 / (36.0 * math.sqrt(n * tan_a))) ** (2.0 / 3.0) - 1.0),
          n)
         for n in range(4, 33)), key=lambda t: (t[0], t[1]))
    assert out["n_turns"] == float(best[1])


def test_bandwidth_thin_wrapper_bitwise() -> None:
    bw = helix_axial.axial_mode_bandwidth(_F0_GHZ * 1e9, _CL)
    out = helix_axial_bandwidth(_F0_GHZ, _CL)
    assert out["f_low_ghz"] == bw["f_low_hz"] / 1e9
    assert out["f_high_ghz"] == bw["f_high_hz"] / 1e9
    assert out["bandwidth_ghz"] == bw["bandwidth_hz"] / 1e9
    assert out["ratio"] == bw["ratio"]
    assert out["f0_in_band"] == bw["f0_in_band"]
    # 带边恒等式随行（f_low/f_high 即 0.75/4-3 映射）
    assert out["f_low_ghz"] == _F0_GHZ * 0.75 / _CL
    assert out["f_high_ghz"] == _F0_GHZ * (4.0 / 3.0) / _CL


# ─── H1 工作例经 wrapper 透传复核（同实现路径，锚树 test_helix_axial 为主裁）──


def test_balanis_example_passthrough() -> None:
    out = run_calculator("helix_axial_performance", {
        "f0_ghz": _F0_GHZ, "n_turns": _N, "alpha_deg": _ALPHA,
        "c_lambda": _CL})
    assert out["ok"], out
    r = out["result"]
    # 与 core 锚树常量逐位（同一实现路径的透传，非第二裁判路线）
    assert r["hpbw_deg"] == helix_axial.KRAUS_HPBW_NUM / (
        _CL * math.sqrt(_N * _CL * math.tan(math.radians(_ALPHA))))
    assert r["input_impedance_ohm"] == 140.0 * _CL
    assert r["axial_ratio"] == 1.0 + 1.0 / (2.0 * _N)
    # α=14° 恰在 (12,14) 严格上界 → 恰等出域 verdict 透传（H6）
    assert r["axial_mode"]["verdict"] == "out_of_band"
    assert r["axial_mode"]["alpha_in_band"] is False
    assert r["axial_mode"]["alpha_margin_high_deg"] == 0.0


# ─── 透传拒绝面（守卫在 core 侧，wrapper 只验透传）───────────────────────────


def test_performance_passthrough_domain_rejections() -> None:
    with pytest.raises(ValueError, match="f0_hz"):
        helix_axial_performance(0.0, _N, _ALPHA, c_lambda=_CL)
    with pytest.raises(ValueError, match="n_turns"):
        helix_axial_performance(_F0_GHZ, 0.5, _ALPHA, c_lambda=_CL)
    with pytest.raises(ValueError, match="alpha_deg"):
        helix_axial_performance(_F0_GHZ, _N, 90.0, c_lambda=_CL)
    # 尺寸全缺显式报错（#364④ is not None 口径）
    with pytest.raises(ValueError, match="给其一"):
        helix_axial_performance(_F0_GHZ, _N, _ALPHA)
    # c_lambda 与 diameter 不一致（1e-9 容差恰值外）显式报错
    bad_mm = _CL * 299792458.0 / _F0_GHZ / math.pi * 1e3 * (1.0 + 1e-6)
    with pytest.raises(ValueError, match="不一致"):
        helix_axial_performance(
            _F0_GHZ, _N, _ALPHA, c_lambda=_CL, diameter_mm=bad_mm)
    # 恰值一致（相对偏差 <1e-9）接受
    good_mm = helix_axial.kraus_performance(
        _F0_GHZ * 1e9, _N, _ALPHA, c_lambda=_CL).diameter_m * 1e3
    out = helix_axial_performance(
        _F0_GHZ, _N, _ALPHA, c_lambda=_CL, diameter_mm=good_mm)
    assert out["c_lambda"] == _CL


def test_design_passthrough_rejections() -> None:
    with pytest.raises(ValueError, match="target_metric"):
        helix_axial_design(_F0_GHZ, n_turns=10.0, target_metric="bogus")
    with pytest.raises(ValueError, match="n_turns"):
        helix_axial_design(_F0_GHZ, n_turns=0.0)
    with pytest.raises(ValueError, match="n_min"):
        helix_axial_design(_F0_GHZ, n_min=0)


def test_bandwidth_passthrough_rejections() -> None:
    with pytest.raises(ValueError, match="f0_hz"):
        helix_axial_bandwidth(0.0, _CL)
    with pytest.raises(ValueError, match="c_lambda"):
        helix_axial_bandwidth(_F0_GHZ, 0.0)


# ─── 信封（service ok/error 构造器）───────────────────────────────────────────


def test_service_envelope_ok_and_error() -> None:
    ok = run_calculator("helix_axial_performance", {
        "f0_ghz": _F0_GHZ, "n_turns": _N, "alpha_deg": _ALPHA,
        "c_lambda": _CL})
    assert ok["ok"] is True and ok["calculator"] == "helix_axial_performance"
    err = run_calculator("helix_axial_performance", {
        "f0_ghz": -1.0, "n_turns": _N, "alpha_deg": _ALPHA,
        "c_lambda": _CL})
    assert err["ok"] is False and err.get("error")
    err2 = run_calculator("helix_axial_bandwidth", {"f0_ghz": 10.0})
    assert err2["ok"] is False and err2.get("error")


def test_n_le_3_invalid_domain_warning_passthrough() -> None:
    out = helix_axial_performance(10.0, 3.0, 13.0, c_lambda=0.95)
    assert any("失效域" in w for w in out["warnings"])
    assert out["axial_mode"]["verdict"] == "out_of_band"
