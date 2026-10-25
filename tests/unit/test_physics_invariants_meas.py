"""G15 物理不变量·预言机自证面（§4.5 四族负例注入 + 契约非空洞 + 有限 δ）。

aurora_h W2-S4 拆分批自 test_physics_invariants.py 迁出（R1 立项 #7）：
本件是预言机自身可失败性的元测试（meta-oracle）——故意破坏的输入必须被
检出，防止写成恒真断言：

1. 契约检查器对 NaN/Inf/ok=False 注入必须失败（self-check 非空洞）；
2. 全部违例度量函数（互易/镜像/置换/尺度/叠加/无源）返回有限非负浮点
   （防 NaN 比较恒假=恒真绿色）；
3. §4.5 四族负例：互易扫描（豁免位真被消费）/线性叠加（非线性注入）/
   无源门（放大注入）/相位积分（β 错源）各配一个注入负例。

共享常数/引擎见 _invariants_helpers.py。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from rfauto.core.calculators import CalculatorRegistry, CalculatorSpec
from rfauto.service.calculator_service import run_calculator
from tests.unit._invariants_helpers import (
    _MIRROR_TOL,
    _QM1_FREQ,
    _QM1_FREQ_PAIRS,
    _QM1_PASSIVITY_TOL,
    _QM1_PHASE_TOL,
    _QM1_SUPERPOS_SEED,
    _QM1_SUPERPOS_TOL,
    _calculator_inputs,
    _cm_response_variants,
    _fake_sparams,
    _max_mirror_violation,
    _max_permutation_violation,
    _max_reciprocity_violation,
    _max_sigma_max,
    _qm1_fake_splanes,
    _qm1_line_beta_models,
    _reciprocity_exempt_names,
    _scale_violation,
    _superposition_violation,
    assert_service_result_contract,
)


def test_service_contract_oracle_is_not_vacuous() -> None:
    """self-check：契约检查器对注入 NaN/Inf/ok=False 必须失败。"""
    good = run_calculator("microstrip_analysis",
                          _calculator_inputs()["microstrip_analysis"])
    assert_service_result_contract(good)

    nan_result = json.loads(json.dumps(good))
    nan_result["result"]["z0_ohm"] = float("nan")
    with pytest.raises(AssertionError):
        assert_service_result_contract(nan_result)

    inf_result = json.loads(json.dumps(good))
    inf_result["result"]["eps_eff"] = float("inf")
    with pytest.raises(AssertionError):
        assert_service_result_contract(inf_result)

    failed = {"ok": False, "error": "boom"}
    with pytest.raises(AssertionError):
        assert_service_result_contract(failed)


def test_all_invariant_functions_expose_finite_deltas() -> None:
    """格式自检：预言机返回的是有限浮点（防止 NaN 比较恒假=恒真绿色）。"""
    s = _fake_sparams("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                      (2.0, 3.0, 101), 2, 2.5)
    for value in (
        _max_reciprocity_violation(s),
        _max_mirror_violation(s),
        _max_permutation_violation(s, [0, 1]),
        _scale_violation("mline", {"w_mm": 1.113, "line_len_mm": 40.0},
                         ["line_len_mm"], 2, 2.5, 2.0),
    ):
        assert math.isfinite(value) and value >= 0.0


# ─── §4.5 自证可失败：四族负例注入（沿 §2/§3 :816/:935/:944 模式）────────────


def test_reciprocity_scan_oracle_detects_violation() -> None:
    """①负例：破坏 S12 的对称性必须被互易扫描预言机检出；豁免位真被消费。"""
    s = _cm_response_variants()["default"].copy()
    s[:, 0, 1] *= 1.2  # 破坏互易
    assert _max_reciprocity_violation(s) > 1e-6
    with pytest.raises(AssertionError):
        assert _max_reciprocity_violation(s) <= _MIRROR_TOL

    # 豁免位消费面：scratch 注册表挂 reciprocal=False 键 → 读出器检出
    scratch = CalculatorRegistry()
    scratch.register(CalculatorSpec(
        name="qm1_ferrite_stub", description="scratch 非互易占位",
        func=lambda **kwargs: {"ok": True}, params=(), required=(),
        reciprocal=False))
    assert _reciprocity_exempt_names(scratch) == {"qm1_ferrite_stub"}
    # 缺省位：未显式声明的新键 reciprocal=True（不进豁免）
    scratch.register(CalculatorSpec(
        name="qm1_default_stub", description="scratch 缺省互易",
        func=lambda **kwargs: {"ok": True}, params=(), required=()))
    assert "qm1_default_stub" not in _reciprocity_exempt_names(scratch)


def test_superposition_oracle_detects_nonlinearity() -> None:
    """②负例：非线性响应算子（+ε·a|a|²）必须被叠加预言机检出。"""
    s = _qm1_fake_splanes()["mline"]
    n = s.shape[-1]
    rng = np.random.default_rng(_QM1_SUPERPOS_SEED)
    a1 = rng.standard_normal((_QM1_FREQ[2], n)) + 1j * rng.standard_normal(
        (_QM1_FREQ[2], n))
    a2 = rng.standard_normal((_QM1_FREQ[2], n)) + 1j * rng.standard_normal(
        (_QM1_FREQ[2], n))
    # 同一组矢量：线性算子过、注入三阶非线性后爆
    assert _superposition_violation(s, a1, a2) <= _QM1_SUPERPOS_TOL

    gain = 1e-3

    def nonlinear_response(x: np.ndarray) -> np.ndarray:
        return (s @ x[..., None]
                + (gain * x * np.abs(x) ** 2)[..., None])[..., 0]

    viol = float(np.max(np.abs(
        nonlinear_response(a1 + a2)
        - nonlinear_response(a1) - nonlinear_response(a2))))
    assert viol > 1e-6, f"叠加预言机对非线性注入不敏感: {viol:.3e}"


def test_passivity_oracle_detects_amplification() -> None:
    """③负例：单元素放大注入必须被无源门检出；有耗无源样例照常通过。"""
    s = _qm1_fake_splanes()["stripline"]
    assert _max_sigma_max(s) <= 1.0 + _QM1_PASSIVITY_TOL

    amplified = s.copy()
    amplified[:, 0, 1] *= 1.5
    sig = _max_sigma_max(amplified)
    assert sig > 1.0 + _QM1_PASSIVITY_TOL, (
        f"无源预言机对放大注入不敏感: σmax={sig:.3e}")
    with pytest.raises(AssertionError):
        assert sig <= 1.0 + _QM1_PASSIVITY_TOL


def test_phase_integral_oracle_detects_wrong_beta() -> None:
    """④负例：β 源错替换成体介电常数（εr=3.66 ≠ εeff≈2.85）必须被检出。"""
    s = _qm1_fake_splanes()["mline"]
    phi = np.unwrap(np.angle(s[:, 0, 1]))
    beta, length_m = _qm1_line_beta_models()["mline"]
    i1, i2 = _QM1_FREQ_PAIRS[0]
    assert abs(float(phi[i2] - phi[i1])
               + float(beta[i2] - beta[i1]) * length_m) <= _QM1_PHASE_TOL

    f_hz = np.linspace(_QM1_FREQ[0], _QM1_FREQ[1], _QM1_FREQ[2]) * 1e9
    beta_bulk = 2.0 * np.pi * f_hz * math.sqrt(3.66) / 299792458.0
    err = abs(float(phi[i2] - phi[i1])
              + float(beta_bulk[i2] - beta_bulk[i1]) * length_m)
    assert err > 0.1, f"相位预言机对 β 错源不敏感: {err:.3e}"
