"""W3-E RB-ALG-2：MIP 量化阵列域面门（scipy.milp 精确解）。

判据（spec sa_specs2 §7.3 ALG-2 预声明门值）：
1. 小规模穷举对拍：8 元 2-bit（+衰减 2 档，8 码/元）全码字空间
   8^8=16,777,216 vs milp 解——目标值逐位一致（最优性精确验证，#118
   合成回收家法；非平凡构型：副瓣水平负偏移使全零码不可行）。
2. 连续解对照：同 spec 无量化（chebyshev 满幅基线）PSLL 对比——量化
   劣化 ≤1.5dB@6bit / ≤3.5dB@4bit（缺省 min-误差目标下实测 0.0，如实）。
3. 码字表直连：MIP 输出相位→firmware beam_codeword_table→
   beam_backsub_audit 回代判据全绿（端到端）。
4. 规模带：16/32/64 元 wall-time 实测（硬上限防失控，实测值入 REPORT）。
内核语义补充钉：不可行 ok=False（不凑，spec §7.4 风险③）、确定性复跑
逐字节一致（G15 同源）、开关掩码、CALC 注册壳 service 契约。
"""
from __future__ import annotations

import itertools
import json
import time

import numpy as np
import pytest

from rfauto.core.array_synthesis import chebyshev_weights
from rfauto.core.quantized_array_milp import (
    quantized_array_milp,
    sidelobe_grid,
)

# 8 元 b=2 G=2 非平凡对拍构型（探针 2026-10-05 标定：offset=−0.5 时全零码
# 不可行、可行解 err>0——穷举门有判别力；G=1 时任意负偏移皆不可行，
# 90° 相位粒度剃不动峰，模型如实 ok=False）
_EXH_CFG = dict(
    n_bits=2, atten_steps=2, atten_step_db=1.0, element_switch=False,
    max_mainlobe_loss_db=1.0, n_sidelobe_points=24, n_tangent=8,
    sl_level_offset_db=-0.5, mip_rel_gap=0.0,
)


def _sum_psll_db(weights: np.ndarray) -> float:
    """裁判=模块自有 peak_sidelobe_level_db（主瓣=最靠近 u=0 的局部极大）。

    直接复数求值（array_factor 校验会丢虚部/拒零和——复权专用）。"""
    from rfauto.core.array_synthesis import peak_sidelobe_level_db

    w = np.asarray(weights, dtype=complex)
    u = np.linspace(-1.0, 1.0, 120001)
    phase = np.exp(1j * np.pi * 2.0 * 0.5
                   * np.outer(u, np.arange(w.size)))
    mag = np.abs(phase @ w)
    return peak_sidelobe_level_db(mag, u)


def test_exhaustive_8el_2bit_matches_milp_objective_exactly():
    """spec §7.3-ALG2-1 门：全码字空间穷举 vs MILP 目标值逐位一致。"""
    n = 8
    res = quantized_array_milp(n, -30.0, **_EXH_CFG)
    assert res["ok"] is True
    taper = chebyshev_weights(n, -30.0)
    grid = sidelobe_grid(n, 0.5, 0.0, None, _EXH_CFG["n_sidelobe_points"],
                         reference_weights=taper)
    rho0 = taper.sum() * 10 ** (-_EXH_CFG["max_mainlobe_loss_db"] / 20.0)
    level = taper.sum() * 10 ** ((-30.0 + _EXH_CFG["sl_level_offset_db"])
                                 / 20.0)
    theta = 2.0 * np.pi * np.arange(_EXH_CFG["n_tangent"]) \
        / _EXH_CFG["n_tangent"]
    psi = 2.0 * np.pi * 0.5 * (grid - 0.0)
    steer = np.exp(1j * np.outer(psi, np.arange(n)))
    n_codes = 2 * 4                                  # g∈{0,1} × q∈{0..3}
    cw = np.zeros((n_codes, n), dtype=complex)
    ce = np.zeros((n_codes, n))
    for c, (g, q) in enumerate([(g, q) for g in range(2) for q in range(4)]):
        cw[c] = taper * 10 ** (-g * 1.0 / 20.0) \
            * np.exp(1j * 2.0 * np.pi * q / 4.0)
        ce[c, :] = np.abs(cw[c] - taper) ** 2
    idx = np.arange(n)
    best = np.inf
    chunk = 200_000
    for start in range(0, n_codes ** n, chunk):
        digits = np.arange(start, min(start + chunk, n_codes ** n),
                           dtype=np.int64)
        cs = np.stack([(digits // n_codes ** k) % n_codes
                       for k in range(n)], axis=1)
        wsel = cw[cs]
        wd = wsel[:, idx, idx]
        field = wd @ steer.T
        proj = np.real(field[:, :, None] * np.exp(-1j * theta)[None, None, :])
        feas = (proj.max(axis=(1, 2)) <= level) & \
               (np.real(wd.sum(axis=1)) >= rho0)
        if not feas.any():
            continue
        vals = ce[cs, idx[None, :]].sum(axis=1)
        vals[~feas] = np.inf
        best = min(best, float(vals.min()))
    assert np.isfinite(best), "穷举空间无可行解（构型标定失效）"
    # 目标值逐位一致（最优性精确验证）
    assert res["quantization_error"] == pytest.approx(best, abs=1e-9)


def test_exhaustive_8el_2bit_spec_literal_offset_zero():
    """spec 字面构型（G=1、全 65536 码字、offset=0）：目标值逐位一致。"""
    cfg = dict(n_bits=2, atten_steps=1, max_mainlobe_loss_db=1.0,
               n_sidelobe_points=24, n_tangent=8, sl_level_offset_db=0.0,
               mip_rel_gap=0.0)
    res = quantized_array_milp(8, -30.0, **cfg)
    assert res["ok"] is True
    taper = chebyshev_weights(8, -30.0)
    # 全零码可行（参考=声明电平带内）→ 最优误差=0（min-误差语义下解析已知）
    assert res["quantization_error"] == pytest.approx(0.0, abs=1e-12)
    # 穷举验证：任一码组合的误差 ≥ 0 且全零码可达 0 → 最优=0 逐位互证
    best = min(
        float(np.sum(np.abs(
            taper * np.exp(1j * 2.0 * np.pi * np.asarray(codes) / 4.0)
            - taper) ** 2))
        for codes in itertools.product(range(4), repeat=8))
    assert res["quantization_error"] == pytest.approx(best, abs=1e-12)


@pytest.mark.parametrize("n_bits,gate_db", [(6, 1.5), (4, 3.5)])
def test_quantization_degradation_within_declared_band(n_bits, gate_db):
    """spec §7.3-ALG2-2 门：量化劣化 ≤1.5dB@6bit / ≤3.5dB@4bit。"""
    res = quantized_array_milp(16, -30.0, n_bits=n_bits, atten_steps=1)
    assert res["ok"] is True
    # 基线：无量化 chebyshev 满幅 PSLL
    baseline = _sum_psll_db(chebyshev_weights(16, -30.0))
    assert baseline == pytest.approx(-30.0, abs=0.1)
    assert res["psll_degradation_db"] <= gate_db
    # 回代口径与独立重算一致（回代可信性旁证）
    wcomplex = np.asarray(res["weights_complex"], dtype=float)
    assert res["psll_db_realized"] == pytest.approx(
        _sum_psll_db(wcomplex[:, 0] + 1j * wcomplex[:, 1]), abs=0.05)


def test_codeword_table_direct_connection_backsub_green():
    """spec §7.3-ALG2-3 门：相位→beam_codeword_table→beam_backsub_audit
    回代判据全绿（端到端，fake 相位面=确定性扫描斜坡，spec 原文口径）+
    MIP 输出相位列直连入表（取整链单源核验）。"""
    from rfauto.core.firmware_export import beam_backsub_audit, beam_codeword_table
    from rfauto.core.metasurface_lut import quantize_phase_deg

    # (a) fake 相位面（确定性扫描斜坡，u0=0.3、d=λ/2：φn=−54n°）→ 全绿
    ramp = [(-54.0 * k) % 360.0 for k in range(8)]
    table = beam_codeword_table(
        element_ids=list(range(8)),
        x_mm=[float(v) for v in np.arange(8) * 4.0],
        y_mm=[0.0] * 8,
        phase_target_deg=ramp,
        bits=2,
    )
    audit = beam_backsub_audit(table)
    assert audit["verdict"] == "PASS"
    assert audit["phase_ok"] is True

    # (b) MIP 输出相位列直连：phase_deg 逐元 = 码字×步长（内核同源），
    # 经 codeword 表取整链与 metasurface_lut 单源一致
    res = quantized_array_milp(8, -30.0, n_bits=2, atten_steps=1)
    assert res["ok"] is True
    table_mip = beam_codeword_table(
        element_ids=list(range(8)),
        x_mm=[float(v) for v in np.arange(8) * 4.0],
        y_mm=[0.0] * 8,
        phase_target_deg=res["phase_deg"],
        bits=2,
    )
    for row in table_mip["rows"]:
        tgt = res["phase_deg"][row["element_id"]]
        assert row["phase_quant_deg"] == pytest.approx(
            quantize_phase_deg(tgt, 2) % 360.0, abs=1e-9)
        assert row["code_word"] == res["phase_code"][row["element_id"]]


@pytest.mark.parametrize("n_elements", [16, 32, 64])
def test_scale_band_wall_time(n_elements):
    """spec §7.3-ALG2-4：16/32/64 元求解规模带（硬上限防失控）。"""
    kwargs = {}
    if n_elements == 64:
        from rfauto.core.array_synthesis import taylor_weights

        # N=64 chebyshev 既有实现数值退化（w.min()=0，主代理备忘），
        # 规模档参考锥削换 taylor（非负、稳健）
        kwargs["reference_weights"] = taylor_weights(64, -30.0, nbar=6)
    t0 = time.perf_counter()
    res = quantized_array_milp(n_elements, -30.0, n_bits=4, atten_steps=1,
                               **kwargs)
    wall = time.perf_counter() - t0
    assert res["ok"] is True
    # 秒-分级（spec §7.2）；上限给 10 倍裕量防 CI 抖动
    assert wall < 120.0


def test_infeasible_returns_ok_false_honestly():
    """spec §7.4 风险③：spec 过紧 → ok=False 如实（不凑）。"""
    res = quantized_array_milp(8, -30.0, n_bits=1, atten_steps=1,
                               sl_level_offset_db=-0.1)
    assert res["ok"] is False
    assert res["reason"] == "milp_infeasible_or_failed"
    assert "solver_status" in res


def test_deterministic_rerun_byte_identical():
    """G15 同源钉：同输入复跑 JSON 逐字节一致（确定性内核）。"""
    kwargs = dict(n_bits=3, atten_steps=2, atten_step_db=0.5,
                  n_sidelobe_points=32, n_tangent=8,
                  sl_level_offset_db=-0.2, mip_rel_gap=0.0)
    a = quantized_array_milp(10, -28.0, **kwargs)
    b = quantized_array_milp(10, -28.0, **kwargs)
    assert json.dumps(a, sort_keys=True, allow_nan=False) == \
        json.dumps(b, sort_keys=True, allow_nan=False)


def test_element_switch_thinning_contract():
    """开关模式：掩码 0/1、与实现权一致、主瓣约束满足。"""
    res = quantized_array_milp(12, -25.0, n_bits=1, atten_steps=1,
                               element_switch=True)
    assert res["ok"] is True
    mask = np.asarray(res["activation_mask"])
    assert set(np.unique(mask)) <= {0, 1}
    wcomplex = np.asarray(res["weights_complex"], dtype=float)
    w = wcomplex[:, 0] + 1j * wcomplex[:, 1]
    np.testing.assert_allclose((np.abs(w) > 1e-12).astype(float),
                               mask.astype(float))


def test_invalid_inputs_explicit():
    with pytest.raises(ValueError, match="n_bits"):
        quantized_array_milp(16, -30.0, n_bits=0)
    with pytest.raises(ValueError, match="n_bits"):
        quantized_array_milp(16, -30.0, n_bits=9)
    with pytest.raises(ValueError, match="atten_steps"):
        quantized_array_milp(16, -30.0, n_bits=4, atten_steps=0)
    with pytest.raises(ValueError, match="负的有限值"):
        quantized_array_milp(16, 30.0, n_bits=4)
    with pytest.raises(ValueError, match="非负"):
        quantized_array_milp(16, -30.0, n_bits=4, atten_step_db=-1.0)
    with pytest.raises(ValueError, match="reference_weights"):
        quantized_array_milp(16, -30.0, n_bits=4,
                             reference_weights=[1.0, -2.0, 0.5])


# ─── CALC 注册壳（service 契约/豁免位）───────────────────────────────────────

def test_calc_array_keys_service_contract():
    """四键经 service 出口：ok=True 信封 + result dict + JSON 化。"""
    from rfauto.service.calculator_service import run_calculator

    out = run_calculator("array.bayliss_weights",
                         {"n_elements": 20, "sidelobe_level_db": -30.0})
    assert out["ok"] is True
    assert isinstance(out["result"], dict)
    assert out["result"]["psll_db_realized"] == pytest.approx(-30.0, abs=0.5)
    json.dumps(out, allow_nan=False)

    out_v = run_calculator("array.villeneuve_weights",
                           {"n_elements": 32, "sidelobe_level_db": -30.0})
    assert out_v["ok"] is True

    out_s = run_calculator(
        "array.schelkunoff_nulls",
        {"n_elements": 8,
         "null_positions": [2.0 * k / 8 for k in range(1, 8)]})
    assert out_s["ok"] is True
    assert out_s["result"]["is_real"] is True

    out_m = run_calculator("array.quantized_milp",
                           {"n_elements": 8, "sidelobe_level_db": -30.0,
                            "n_bits": 2, "atten_steps": 1})
    assert out_m["ok"] is True


def test_calc_array_quantized_milp_infeasible_service_false():
    """CALC 壳层：内核不可行 → service ok=False 通道（不凑）。"""
    from rfauto.service.calculator_service import run_calculator

    out = run_calculator(
        "array.quantized_milp",
        {"n_elements": 8, "sidelobe_level_db": -30.0, "n_bits": 1,
         "atten_steps": 1, "sl_level_offset_db": -0.1})
    assert out["ok"] is False
    assert out.get("error")


def test_calc_array_keys_reciprocal_false():
    """spec §7.3-5：阵列方向图非端口网络 → reciprocal=False 豁免位
    （QM-1 §D-7；豁免清单封闭断言消费，主代理合流同步清单）。"""
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    for key in ("array.bayliss_weights", "array.villeneuve_weights",
                "array.schelkunoff_nulls", "array.quantized_milp"):
        assert CALCULATOR_REGISTRY.get(key).reciprocal is False
        assert CALCULATOR_REGISTRY.get(key).experimental is False
