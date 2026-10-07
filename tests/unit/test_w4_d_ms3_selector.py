"""W4-D MS-3：合成夹具生成器 + 去嵌方法选择裁判域面测试。

预声明门值（se_specs3 §4a，含一处预声明口径的如实处置）：
1. 理想基线回收——**按方法适用域分 corpus 预声明**：分布线语料（25mm
   夹具，0.1-40GHz）上 gated 方法（afr_2xthru/p370_nzc/inhouse_gamma_diff/
   z0_prior_inhouse）s_error_max ≤1e-6；电短语料（0.1mm 夹具，0.1-1GHz）
   上 split_tee/split_pi ≤1e-6。规格原文"五法同语料 ≤1e-6"不可满足：
   NZC 与对切法适用域互斥（分布线 vs 集总等效），ZC 合成语料不达标为
   DP-15 C2 在档结论——偏差升格记 REPORT（#122 如实分级）。
2. 敏感性先证：ΔZ∈{0.5,1,3}Ω 三档，inhouse_gamma_diff s_error 单调上升
   ≥1 个数量级（实测 ~33×）；真先验恢复 ≥100×。
3. 对称性守卫：两侧阻抗不对称（asym_dz_ohm）→ split 显式 inapplicable
   不产数值；纯长度不对称（同 Z0）在 2x-thru 端口 S 参量不可见
   （S11=S22=0，物理实情）——守卫不覆盖该形态，后果由排名面承担
   （split 沉底，实测钉）。
4. 确定性：同输入两次运行逐位一致（噪声档固定种子）。
5. rules 回收：R010 verify 在 tests/unit/test_rules_verify.py 实跑。
6. 零计数自检：service 面，零 CLI/MCP/CALC。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import skrf

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.synthetic_fixture import (
    DegradeOptions,
    build_synthetic_fixture,
    s_param_asymmetry,
)
from rfauto.service.deembed_selector_service import (
    DEEMBED_METHODS,
    select_deembed_method,
)

_DIST_FREQ = skrf.Frequency(0.1, 40.0, 401, "GHz")
_SHORT_FREQ = skrf.Frequency(0.1, 1.0, 201, "GHz")


def _run_selector(fx, *, length_m, prior=None, methods=DEEMBED_METHODS,
                  zc=True):
    nets = {
        "dut_fdf": fx.dut_fdf,
        "twoxthru": fx.twoxthru,
        "dut_reference": fx.dut_reference,
    }
    if zc:
        nets["zc_fix_dut_fix"] = fx.dut_fdf
    opts: dict = {"fixture_length_m": length_m}
    if prior is not None:
        opts["fixture_z0_prior_ohm"] = prior
    if methods is not None:
        opts["methods"] = methods
    return select_deembed_method(nets, opts)


def _by_name(out):
    return {m["method"]: m for m in out["methods"]}


# ── 判据 1：理想基线回收（分域）──────────────────────────────────────────────

def test_ideal_baseline_distributed_corpus() -> None:
    fx = build_synthetic_fixture(_DIST_FREQ, fixture_length_m=25e-3)
    out = _run_selector(fx, length_m=25e-3, prior=fx.left_z0_ohm)
    by = _by_name(out)
    for method in ("afr_2xthru", "p370_nzc", "inhouse_gamma_diff",
                   "z0_prior_inhouse"):
        entry = by[method]
        assert entry["applicable"] and entry["ok"], method
        assert entry["s_error_max"] < out["gate_threshold"], (
            method, entry["s_error_max"])
        assert entry["meets_gate"] is True, method
    # 分布线超对切集总域：数值如实差（排名沉底），不凑绿
    for method in ("split_tee", "split_pi"):
        assert by[method]["s_error_max"] > 1e-3, method
    # ZC 在档结论：结果照出、gated=False、不设门
    assert by["p370_zc"]["ok"] is True and by["p370_zc"]["gated"] is False
    assert out["ranking"][-1] == "p370_zc"
    # 劣化地板与比值面（规格 §4a.4 ②）
    assert out["baseline_s_error_max"] > 0.1
    assert by["z0_prior_inhouse"]["vs_baseline_ratio"] < 1e-12


def test_ideal_baseline_lumped_corpus() -> None:
    fx = build_synthetic_fixture(_SHORT_FREQ, fixture_length_m=0.1e-3)
    out = _run_selector(fx, length_m=0.1e-3, prior=fx.left_z0_ohm,
                        methods=("afr_2xthru", "p370_nzc", "split_tee",
                                 "split_pi", "inhouse_gamma_diff",
                                 "z0_prior_inhouse"))
    by = _by_name(out)
    for method in ("split_tee", "split_pi"):
        assert by[method]["s_error_max"] < out["gate_threshold"], (
            method, by[method]["s_error_max"])


# ── 判据 2：敏感性先证 ───────────────────────────────────────────────────────

def test_dz_sensitivity_monotone_decade() -> None:
    errs = []
    for dz in (0.5, 1.0, 3.0):
        fx = build_synthetic_fixture(
            _DIST_FREQ, degrade=DegradeOptions(dz_ohm=dz))
        out = _run_selector(
            fx, length_m=25e-3, prior=50.0,
            methods=("inhouse_gamma_diff",))
        errs.append(_by_name(out)["inhouse_gamma_diff"]["s_error_max"])
    assert errs[0] < errs[1] < errs[2], f"非单调：{errs}"
    assert errs[0] / errs[2] < 0.1, (
        f"ΔZ 敏感性不足 1 个数量级：{errs[0]:.3e}→{errs[2]:.3e}")


def test_true_prior_recovers_over_no_prior() -> None:
    fx = build_synthetic_fixture(
        _DIST_FREQ, degrade=DegradeOptions(dz_ohm=3.0))
    out_np = _run_selector(fx, length_m=25e-3,
                           methods=("inhouse_gamma_diff",))
    out_p = _run_selector(fx, length_m=25e-3, prior=fx.left_z0_ohm,
                          methods=("z0_prior_inhouse",))
    s_np = _by_name(out_np)["inhouse_gamma_diff"]["s_error_max"]
    s_p = _by_name(out_p)["z0_prior_inhouse"]["s_error_max"]
    assert s_p * 100.0 < s_np, (s_np, s_p)


def test_nzc_insensitive_to_dz() -> None:
    """NZC 自校准面：ΔZ 档位下保持理想量级（敏感性对照面）。"""
    for dz in (0.5, 3.0):
        fx = build_synthetic_fixture(
            _DIST_FREQ, degrade=DegradeOptions(dz_ohm=dz))
        out = _run_selector(fx, length_m=25e-3, methods=("p370_nzc",))
        assert _by_name(out)["p370_nzc"]["s_error_max"] < 1e-6, dz


# ── 判据 3：对称性守卫 ───────────────────────────────────────────────────────

def test_symmetry_guard_inapplicable_on_impedance_asymmetry() -> None:
    fx = build_synthetic_fixture(
        _DIST_FREQ,
        degrade=DegradeOptions(asym_length_ratio=0.2, asym_dz_ohm=3.0))
    assert s_param_asymmetry(fx.twoxthru) > 1e-3
    out = _run_selector(fx, length_m=25e-3,
                        methods=("split_tee", "split_pi"))
    for m in out["methods"]:
        assert m["applicable"] is False
        assert "对称" in m["inapplicable_reason"]
        assert "s_error_max" not in m  # 不产数值


def test_pure_length_asymmetry_undetectable_split_sinks() -> None:
    """纯长度不对称（同 Z0）：2x-thru 端口不可见（物理实情）→ 排名面兜底。"""
    fx = build_synthetic_fixture(
        _DIST_FREQ, degrade=DegradeOptions(asym_length_ratio=0.2))
    assert s_param_asymmetry(fx.twoxthru) < 1e-12  # 端口不可见（守卫不覆盖）
    out = _run_selector(
        fx, length_m=25e-3, prior=50.0,
        methods=("split_tee", "inhouse_gamma_diff", "z0_prior_inhouse"))
    assert out["ranking"][-1] == "split_tee"
    by = _by_name(out)
    assert by["inhouse_gamma_diff"]["s_error_max"] < by["split_tee"]["s_error_max"]


def test_zc_requires_second_artifact() -> None:
    fx = build_synthetic_fixture(_DIST_FREQ, fixture_length_m=25e-3)
    out = _run_selector(fx, length_m=25e-3, zc=False,
                        methods=("p370_zc",))
    entry = out["methods"][0]
    assert entry["applicable"] is False
    assert "fix-dut-fix" in entry["inapplicable_reason"]


def test_missing_required_option_is_inapplicable() -> None:
    fx = build_synthetic_fixture(_DIST_FREQ, fixture_length_m=25e-3)
    out = _run_selector(fx, length_m=None, methods=("inhouse_gamma_diff",))
    assert out["methods"][0]["applicable"] is False
    out2 = _run_selector(fx, length_m=25e-3,
                         methods=("z0_prior_inhouse",))
    assert out2["methods"][0]["applicable"] is False


# ── 判据 4：确定性 ───────────────────────────────────────────────────────────

def test_determinism_bitwise_with_noise() -> None:
    fx_a = build_synthetic_fixture(
        _DIST_FREQ, degrade=DegradeOptions(noise_sigma=0.005, seed=3))
    fx_b = build_synthetic_fixture(
        _DIST_FREQ, degrade=DegradeOptions(noise_sigma=0.005, seed=3))
    assert np.array_equal(fx_a.dut_fdf.s, fx_b.dut_fdf.s)
    assert np.array_equal(fx_a.twoxthru.s, fx_b.twoxthru.s)
    out_a = _run_selector(fx_a, length_m=25e-3, prior=50.0,
                          methods=("inhouse_gamma_diff", "p370_nzc"))
    out_b = _run_selector(fx_b, length_m=25e-3, prior=50.0,
                          methods=("inhouse_gamma_diff", "p370_nzc"))
    assert np.array_equal(
        np.array([m["s_error_max"] for m in out_a["methods"]]),
        np.array([m["s_error_max"] for m in out_b["methods"]]))
    assert out_a["ranking"] == out_b["ranking"]


# ── 生成器域面（DUT 库/劣化旋钮回执）────────────────────────────────────────

def test_generator_dut_kinds_and_degrade_echo() -> None:
    for kind in ("thru", "mismatch_line", "shunt_open_stub"):
        fx = build_synthetic_fixture(_DIST_FREQ, dut=kind)
        assert fx.dut_fdf.nports == 2 and fx.dut_reference.nports == 2
        assert fx.dut_fdf.frequency == fx.dut_reference.frequency
        assert "inverse_width" in fx.note  # 线参数单源链 provenance
    fx_deg = build_synthetic_fixture(
        _DIST_FREQ,
        degrade=DegradeOptions(dz_ohm=1.0, asym_length_ratio=0.1,
                               taper_steps=3, taper_dz_ohm=5.0,
                               drop_lowest_points=5))
    assert abs(fx_deg.left_z0_ohm - 51.0) < 0.01  # inverse_width/forward 回代
    assert fx_deg.right_length_m == pytest.approx(25e-3 * 1.1)
    assert fx_deg.dut_fdf.s.shape[0] == _DIST_FREQ.npoints - 5
    assert fx_deg.options.taper_steps == 3
    with pytest.raises(ValueError, match="未知 DUT"):
        build_synthetic_fixture(_DIST_FREQ, dut="bogus")


def test_noise_breaks_afr_precheck_honestly() -> None:
    """现实噪声口径（S21/S12 独立带噪）：AFR 预检如实失败，选择器照出。"""
    fx = build_synthetic_fixture(
        _DIST_FREQ, degrade=DegradeOptions(noise_sigma=0.005, seed=1))
    out = _run_selector(fx, length_m=25e-3, methods=("afr_2xthru",))
    entry = out["methods"][0]
    assert entry["applicable"] is True and entry["ok"] is False
    assert any("预检" in e for e in entry["errors"])


def test_zero_counter_surface() -> None:
    """判据 6：service 面——零 CALC 键、零 CLI/MCP（v1 不接壳）。"""
    from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY

    assert "vertical_pdn_impedance" not in set(CALCULATOR_REGISTRY.names())
    assert "deembed" not in set(CALCULATOR_REGISTRY.names())
