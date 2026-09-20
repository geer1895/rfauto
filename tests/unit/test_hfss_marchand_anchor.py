"""hfss_marchand_anchor 判读纯函数合成回收单测。

反演核必须在合成数据上精确回收设计值（#118：数值算法的裁判=独立来源
解析值/合成回收），合成两条独立路线：
- 模态路线：偶/奇模 TL 的 S（z_to_s 解析构造，含各自相速）拼 4×4 模态
  S（grouped 与 interleaved 两种端口序）→ coupled_anchor_from_s4 回收；
- 标准 4 端口路线：core coupled_line_z_matrix（与 adapters Pozar (7.83)/(7.84)
  独立同源的两份实现之一）→ 50Ω 归一 S → 镜面分解反演回收。
不 import pyaedt；HFSS 面（build/solve）不做离线测试。
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.slotline_transitions import (
    coupled_line_z_matrix,
    z_to_s,
)

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "hfss_marchand_anchor.py"


def _load():
    spec = importlib.util.spec_from_file_location("hfss_marchand_anchor", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()
FREQ_HZ = np.linspace(2.0e9, 3.0e9, 101)


@pytest.fixture(scope="module")
def ctx():
    return mod.design_context()


def _tl_s2(freq_hz, z0_ohm, eps_eff, ell_m, z_ref=50.0):
    """均匀线段 2 端口 S（解析 TL Z 参数 → z_to_s，独立于被测实现）。"""
    beta = 2.0 * np.pi * np.asarray(freq_hz, dtype=float) * math.sqrt(eps_eff) / 299792458.0
    th = beta * ell_m
    z2 = np.empty((th.shape[0], 2, 2), dtype=complex)
    z2[:, 0, 0] = z2[:, 1, 1] = -1j * z0_ohm / np.tan(th)
    z2[:, 0, 1] = z2[:, 1, 0] = -1j * z0_ohm / np.sin(th)
    return z_to_s(z2, np.array([float(z_ref)] * 2))


def _modal_s4(freq_hz, ze, zo, ere, ero, ell_m, order="grouped"):
    """偶/奇模各自相速的模态 4×4 S（grouped 或 interleaved 端口序）。

    ze/zo 为单线偶/奇模阻抗；端口模式按 HFSS 双导体端口约定发射
    **共模 Z_c=ze/2、差模 Z_d=2·zo**（真机实证基准，脚本反演内含换算）。
    """
    se = _tl_s2(freq_hz, 0.5 * ze, ere, ell_m)
    so = _tl_s2(freq_hz, 2.0 * zo, ero, ell_m)
    nf = se.shape[0]
    s4 = np.zeros((nf, 4, 4), dtype=complex)
    for (blk, idx) in ((se, (0, 2)), (so, (1, 3))):
        s4[:, idx[0], idx[0]] = blk[:, 0, 0]
        s4[:, idx[0], idx[1]] = blk[:, 0, 1]
        s4[:, idx[1], idx[0]] = blk[:, 1, 0]
        s4[:, idx[1], idx[1]] = blk[:, 1, 1]
    if order == "interleaved":
        i = np.array([0, 2, 1, 3])
        s4 = s4[:, i][:, :, i]
    return s4


def test_mode_line_recovers_synthetic_tline():
    """单线合成回收：Z0/β/εeff（独立 z_to_s 构造）。"""
    z0, ere, ell = 80.0, 2.5, 18.467e-3
    s2 = _tl_s2(FREQ_HZ, z0, ere, ell)
    out = mod.mode_line_from_s2(FREQ_HZ, s2, ell)
    assert abs(np.real(out["z0_ohm"]) - z0).max() < 1e-6
    assert np.abs(out["eps_eff"] - ere).max() / ere < 1e-9
    beta_true = 2.0 * np.pi * FREQ_HZ * math.sqrt(ere) / 299792458.0
    assert np.abs(out["beta_rad_m"] - beta_true).max() / beta_true.max() < 1e-9


def test_mode_line_rejects_out_of_domain():
    """ℓ ≥ λ'/2 扫频下 βℓ 折叠呈锯齿非单调 → 显式报错不外推（单频混叠固有不可判）。"""
    s2 = _tl_s2(FREQ_HZ, 80.0, 2.5, 200e-3)      # 200mm @2–3GHz ≈ 2.1–3.2λ'
    with pytest.raises(ValueError, match="越出"):
        mod.mode_line_from_s2(FREQ_HZ, s2, 200e-3)


def test_coupled_anchor_recovers_design_point(ctx):
    """模态路线合成回收设计名义点（Z0e/Z0o/εeff_e/εeff_o），两种端口序。"""
    kj = ctx["kj_ref"]
    ell = ctx["l_sect_mm"] * 1e-3
    for order in ("grouped", "interleaved"):
        s4 = _modal_s4(FREQ_HZ, kj["z0e_ohm"], kj["z0o_ohm"],
                       kj["ere_e"], kj["ere_o"], ell, order=order)
        res = mod.coupled_anchor_from_s4(FREQ_HZ, s4, ell)
        assert res["order"] == order
        assert abs(np.real(res["z0e_ohm"][res["i0"]]) - kj["z0e_ohm"]) < 1e-6
        assert abs(np.real(res["z0o_ohm"][res["i0"]]) - kj["z0o_ohm"]) < 1e-6
        # 原始模阻抗=共模/差模基准（换算前）
        assert abs(np.real(res["z_common_ohm"][res["i0"]]) - 0.5 * kj["z0e_ohm"]) < 1e-6
        assert abs(np.real(res["z_diff_ohm"][res["i0"]]) - 2.0 * kj["z0o_ohm"]) < 1e-6
        assert abs(res["ere_e"][res["i0"]] - kj["ere_e"]) / kj["ere_e"] < 1e-6
        assert abs(res["ere_o"][res["i0"]] - kj["ere_o"]) / kj["ere_o"] < 1e-6
        assert res["cross_mode_resid"] < 1e-12
        assert res["reciprocity_max_abs"] < 1e-12


def test_coupled_anchor_std_recovers_circuit_matrix(ctx):
    """标准 4 端口路线：core coupled_line_z_matrix → 50Ω S → 镜面分解回收。

    独立裁判：core 的四端口 Z（Pozar §7.6 偶/奇叠加）与本案镜面分解互为
    两份独立实现；公共 β ⇒ εeff_e/o 应同收 (εeff_e+εeff_o)/2。
    """
    kj = ctx["kj_ref"]
    ell = ctx["l_sect_mm"] * 1e-3
    theta = 0.5 * np.pi * FREQ_HZ / (ctx["f0_ghz"] * 1e9)
    z4 = coupled_line_z_matrix(kj["z0e_ohm"], kj["z0o_ohm"], theta)
    s4 = z_to_s(z4, np.array([50.0] * 4))
    # core 端口序 (1近,1远,2近,2远) → 本案 (1近,2近,1远,2远)
    i = np.array([0, 2, 1, 3])
    s4 = s4[:, i][:, :, i]
    res = mod.coupled_anchor_from_s4_std(FREQ_HZ, s4, ell)
    assert abs(np.real(res["z0e_ohm"][res["i0"]]) - kj["z0e_ohm"]) / kj["z0e_ohm"] < 1e-6
    assert abs(np.real(res["z0o_ohm"][res["i0"]]) - kj["z0o_ohm"]) / kj["z0o_ohm"] < 1e-6
    ere_avg = 0.5 * (kj["ere_e"] + kj["ere_o"])
    # core θ=(π/2)f/f0 隐含未圆整 ℓ；本案 ℓ 取 nominal 4 位圆整 → 隐含 εeff 差
    # ≈2·(5e-5/18.467)≈5e-6（圆整而非算法误差），容差 1e-4
    assert abs(res["ere_e"][res["i0"]] - ere_avg) / ere_avg < 1e-4
    assert abs(res["ere_o"][res["i0"]] - ere_avg) / ere_avg < 1e-4
    assert res["asym_resid"] < 1e-12


def test_detect_modal_order():
    """模序识别：两序合成矩阵均识别正确，且统一后逐位一致。"""
    ell = 18.467e-3
    s_g = _modal_s4(FREQ_HZ, 95.21, 36.49, 2.4, 2.1, ell, order="grouped")
    s_i = _modal_s4(FREQ_HZ, 95.21, 36.49, 2.4, 2.1, ell, order="interleaved")
    assert mod.detect_modal_order(s_g[50]) == "grouped"
    assert mod.detect_modal_order(s_i[50]) == "interleaved"
    assert np.allclose(mod.s4_to_grouped(s_i, "interleaved"), s_g)
    with pytest.raises(ValueError):
        mod.s4_to_grouped(s_g, "bogus")


def test_verdict_of_gates():
    """(a) 预声明门边界：≤5 AGREE / 5–15 PARTIAL / >15 DISAGREE。"""
    assert mod.verdict_of(5.0) == "AGREE"
    assert mod.verdict_of(5.0001) == "PARTIAL"
    assert mod.verdict_of(15.0) == "PARTIAL"
    assert mod.verdict_of(15.1) == "DISAGREE"


def test_design_point_single_source(ctx):
    """单源读取钉住设计任务数字（禁手抄的对账基准）。"""
    kj = ctx["kj_ref"]
    assert abs(kj["z0e_ohm"] - 95.21) <= 0.01
    assert abs(kj["z0o_ohm"] - 36.49) <= 0.01
    assert abs(ctx["w_mm"] - 1.7616) <= 1e-4
    assert abs(ctx["s_mm"] - 0.1016) <= 1e-4
    assert abs(ctx["l_sect_mm"] - 18.4670) <= 1e-4
    assert abs(ctx["w_feed_mm"] - 3.3439) <= 1e-4
    assert abs(ctx["w_bal_mm"] - 0.2981) <= 1e-4
    assert ctx["r_bal_se_ohm"] == pytest.approx(140.0, abs=0.01)
    assert ctx["design_ideal"]["realizable"] is True
    # 电路级自检（主代理实测回读 model_metrics：−19.75dB / 1.8e-14 / 0.0°）
    m = ctx["circuit_self_check"]
    assert m["all_gates_pass"] is True
    assert m["band_max_s11_db"] == pytest.approx(-19.75, rel=0.02)
    assert m["band_max_abs_imbalance_db"] < 1e-10
    assert m["band_max_phase_error_deg"] < 1e-6


def test_analyze_anchor_b_on_perturbed_circuit(ctx):
    """(b) 判读链路：微扰电路级 S 充当"HFSS"数据，门与差值方向正确。"""
    s_c = mod.circuit_sparams_grid(ctx, FREQ_HZ)
    s_h = s_c.copy()
    s_h[:, 0, 0] *= 1.02                     # S11 +0.17dB 微扰
    res = mod.analyze_anchor_b(FREQ_HZ, s_h, ctx, {}, {})
    assert res["gates_circuit_self_check"]["all_pass"] is True
    assert res["verdict"] == "PASS"
    assert res["all_gates_pass"] is True
    d = res["vs_circuit"]["s11_db_f0"]
    expect = 20.0 * math.log10(1.02)
    assert d["delta"] == pytest.approx(expect, abs=0.02)
    assert d["delta"] > 0                     # HFSS 侧回损更差
    # 未扰动的 S21 差值 ≈0
    assert abs(res["vs_circuit"]["s21_db_f0"]["delta"]) < 1e-9
    # 相位差恒 180°（理想对称模型）
    assert abs(res["hfss_metrics"]["phase_diff_deg_f0"]) == pytest.approx(180.0, abs=1e-6)


def test_anchor_c_offline(tmp_path, monkeypatch):
    """(c) 离线判读：闭式重算 + 既有仲裁数字复现（不依赖真机）。"""
    src = REPO / "runs" / "slotline_port_b" / "result.json"
    if not src.exists():
        pytest.skip("既有 slotline_port_b 产物缺失（真机历史产物）")
    res = mod.analyze_anchor_c()
    assert res["verdict"] in ("AGREE", "PARTIAL")
    assert abs(res["beta_rad_m"]["closed_form"] - 67.22687889224117) < 1e-3
    assert abs(res["beta_rad_m"]["hfss_wide_gamma"] - 66.7666393022851) < 1e-9
    assert res["reproduced"] is True
