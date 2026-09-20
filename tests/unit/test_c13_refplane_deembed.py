"""C13 参考面去嵌闭门（2026-09-15）。

闭环对象：topology_service 旧边界注记——
「coupling_matrix_extract 对含馈线/λ/4 参考面相位的电路裁判输出不收敛
（rms ~7e-2 > 1e-2 门，相位非有理可吸收）」。本文件用名义设计链
（coupled_bpf_design_from_order → coupled_bpf_circuit_sparams）逐项复现、
定位根因并给出收敛口径，全部离线秒级（无真机段）。

根因账（探针实测，本文件逐项可复现）：
- 原始反提 rms=0.060（±5% 窗，色散裁判）>1e-2 门 → raise（即旧注记 ~7e-2）。
- 根因链：① 50Ω 馈线平移相位 e^{−j2πfτ} 在 Ω=(f/f0−f0/f)/fbw 域非有理；
  ② λ/4 耦合段 commensurate 级联在 Ω 域非有理（Richards 变量 tan(θ) ≠
  Ω 映射）；③ 窄带下错 τ 可被「多项式翘曲」补偿（探针实测 rms 1.3e−5 处
  拟合极点全飞），Y 留数重建把离流形距离放大 ~10³ 倍（重建 vs 拟合
  2.6e−2 ≫ rms 1.3e−5）。
- 已败三策略复盘：相位滚转 ±（全局常数相位，污染物是 f 的函数，滚不动）；
  ABCD 精确逆（λ/4 段=2 导体 4 端口+交叉口开路复合结构，不是可分离级联件，
  夹具网络不可知）；纯时延去嵌（能开门不收敛：馈线量 τ_feed 精确去嵌后
  rms 7.2e−3 过门，但 kij 0.08、响应偏差 0.15——ok=False 如实关死）。
- 收敛口径 = domain="magnitude" 幅值域反提：|S11|²=F(jΩ)F(−jΩ)/E(jΩ)E(−jΩ)
  是 Ω² 的实有理函数（相位天然免疫），线性 Cauchy+谱分解重建。sync TEM
  裁判（综合方程精确成立口径）实测：±3% 窗 fit 8.7e−3（过 1e-2 门）+
  kij 逐元素 1.95e−2；±1.5% 窗 kij 1.85e−2。
- 色散模式（默认 εeff_e/o）裁判与理想矩阵带内 |S11| 差 ~0.16（真偶/奇模
  模型差异，不是反提问题）——裁判模型问题只记录不改，归 #11（本项禁改
  openems_templates.py）。

数值口径（#118）：容差取实测达到值的 1.5 倍以内；kij 参考矩阵用
coupling_matrix_synthesize_n2（transversal 形，与反提输出同拓扑——设计链
coupling_matrix_matrix 为 folded 形，|kij| 跨拓扑不可比，两形频响等价）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    coupled_bpf_circuit_sparams,
    coupled_bpf_design_from_order,
)
from rfauto.core.calculators import (
    _cm_fit_rms,
    _cm_rational_fit,
    coupling_matrix_extract,
    coupling_matrix_synthesize_n2,
)
from rfauto.core.deembed import C0

_F0 = 2.5
_FBW = 0.05
_ORDER = 3
# 窗口（GHz 轴）：±3% 是幅值域收敛与 τ 扫描开门的钉窗口；±5% 是旧注记
# rms ~7e-2 的复现窗口；±1.5% 是幅值域 kij 最优窗口。
_WIN_3 = np.linspace(2.5 * 0.97, 2.5 * 1.03, 161)
_WIN_5 = np.linspace(2.5 * 0.95, 2.5 * 1.05, 161)
_WIN_15 = np.linspace(2.5 * 0.985, 2.5 * 1.015, 161)


def _design() -> dict:
    return coupled_bpf_design_from_order(_ORDER, _F0, _FBW, 20.0)


def _sparams(design: dict, freq: np.ndarray, *, sync: bool):
    s = coupled_bpf_circuit_sparams(freq, design, synchronous_tem=sync)
    return ([[float(v.real), float(v.imag)] for v in s[:, 0, 0]],
            [[float(v.real), float(v.imag)] for v in s[:, 1, 0]])


def _kij_ref() -> np.ndarray:
    """transversal 形参考矩阵（与反提输出同拓扑，|kij| 逐元素可比）。"""
    out = coupling_matrix_synthesize_n2(order=_ORDER, rl_db=20.0)
    return np.array([[complex(re, im) for re, im in row]
                     for row in out["coupling_matrix"]])


def _mag_kij(m_list: list) -> float:
    m = np.array([[complex(re, im) for re, im in row] for row in m_list])
    return float(np.max(np.abs(np.abs(m) - np.abs(_kij_ref()))))


# ── ① 原始不收敛复现（旧边界注记的 rms ~7e-2）────────────────────────────────

def test_circuit_judge_raw_extraction_fails_gate_honestly():
    """名义设计电路裁判（色散模式，±5% 窗）原始反提：拟合残差 0.060（实测，
    即旧注记的 ~7e-2 档）超 1e-2 门 → 显式 raise，不凑绿。"""
    design = _design()
    s11, s21 = _sparams(design, _WIN_5, sync=False)
    # 门前的拟合残差（独立量一遍，钉住「不收敛」的量级）
    om = (_WIN_5 / _F0 - _F0 / _WIN_5) / _FBW
    f_s, p_s, e_s = _cm_rational_fit(om, np.array([complex(a, b) for a, b in s11]),
                                     np.array([complex(a, b) for a, b in s21]),
                                     _ORDER, 0)
    rms = _cm_fit_rms(f_s, p_s, e_s, om,
                      np.array([complex(a, b) for a, b in s11]),
                      np.array([complex(a, b) for a, b in s21]))
    assert 0.03 < rms < 0.12
    with pytest.raises(ValueError, match="拟合残差过大"):
        coupling_matrix_extract(freq_ghz=[float(v) for v in _WIN_5],
                                s11=s11, s21=s21, order=_ORDER,
                                f0_ghz=_F0, fbw=_FBW)


# ── ② 纯时延去嵌：开门不收敛（已败策略③的定量账）────────────────────────────

def test_feed_delay_deembed_opens_gate_but_response_honest():
    """馈线时延（设计量 τ_feed=feed_len/c，裁判馈线=真空相位）经
    deembed_reference_delay 精确去嵌：rms 7.2e−3 过 1e-2 门，但重建响应
    偏差 0.15 ≫ 拟合水平 → ok=False 如实关死（λ/4 段相位非时延型，
    任何参考面时延都吸收不了），kij 0.08 不可信——不凑绿。"""
    design = _design()
    tau_feed = float(design["feed_len_mm"]) * 1e-3 / C0
    s11, s21 = _sparams(design, _WIN_3, sync=True)
    ex = coupling_matrix_extract(
        freq_ghz=[float(v) for v in _WIN_3], s11=s11, s21=s21,
        order=_ORDER, f0_ghz=_F0, fbw=_FBW, ref_delay_s=tau_feed)
    assert ex["ref_delay_s"] == pytest.approx(tau_feed, rel=1e-9)
    assert ex["fit_rms"] <= 1e-2            # 门开了（实测 7.2e−3）
    assert ex["ok"] is False                # 但重建不复现数据（假绿关死）
    assert ex["response_max_err"] > 0.05
    assert _mag_kij(ex["coupling_matrix"]) > 0.05


def test_tau_scan_opens_gate_lower_but_still_not_converged():
    """τ̂ 扫描（仿 f0 精化的多轮栅格）：把拟合残差压到 6.8e−5（靠多余 TZ
    吸收残余相位，n_finite_tz=1 结构性过拟合），重建偏差仍 0.94 →
    ok=False。实证「时延扫描不是收敛解」：错 τ 被多项式翘曲补偿，
    Y 留数重建把离流形距离放大约 10³ 倍。"""
    design = _design()
    s11, s21 = _sparams(design, _WIN_3, sync=True)
    ex = coupling_matrix_extract(
        freq_ghz=[float(v) for v in _WIN_3], s11=s11, s21=s21,
        order=_ORDER, f0_ghz=_F0, fbw=_FBW, ref_delay_scan=True)
    assert ex["fit_rms"] <= 1e-2
    assert 100e-12 < ex["ref_delay_s"] < 300e-12   # 实测 196ps（物理量级）
    assert ex["n_finite_tz"] == 1                  # 多余 TZ 吸收（机制钉住）
    assert ex["ok"] is False
    assert ex["response_max_err"] > 0.05
    assert _mag_kij(ex["coupling_matrix"]) > 0.1


# ── ③ 收敛口径：幅值域反提（|S|² 相位免疫）───────────────────────────────────

@pytest.mark.parametrize("win,kij_pin", [(_WIN_15, 0.0185), (_WIN_3, 0.0195)])
def test_magnitude_domain_extraction_recovers_kij(win, kij_pin):
    """domain="magnitude"（sync TEM 裁判，名义 N=3 设计）：fit ≤1e-2（实测
    5.5e−4/8.7e−3）、kij 逐元素 ≤0.03（实测 1.85e−2/1.95e−2）、重建响应
    ≤0.05（实测 6.9e−3/3.1e−2）、n_finite_tz=0、ok=True。精度损失（如实）：
    F/P 全局符号与单侧 TZ ±Ω 由幅值不可辨识（本例全极点无 TZ 不受影响）；
    kij 地板 ~2e−2 由裁判 εeff 模型与理想矩阵的固有差异决定（非反提误差）。"""
    design = _design()
    s11, s21 = _sparams(design, win, sync=True)
    ex = coupling_matrix_extract(
        freq_ghz=[float(v) for v in win], s11=s11, s21=s21,
        order=_ORDER, f0_ghz=_F0, fbw=_FBW, domain="magnitude")
    assert ex["ok"], ex["ok_reason"]
    assert ex["coefficient_path"] == "magnitude"
    assert ex["method"] == "magnitude_squared_cauchy+cameron_residue"
    assert ex["fit_rms"] <= 1e-2
    assert ex["response_max_err"] <= 0.05
    kij = _mag_kij(ex["coupling_matrix"])
    assert kij <= 0.03, kij
    assert kij <= 2.0 * kij_pin             # 钉实测（1.85e−2 / 1.95e−2）
    assert ex["n_finite_tz"] == 0
    assert ex["external_q"][0] > 0.0 and ex["external_q"][1] > 0.0


def test_dispersive_judge_model_gap_dominates_honestly():
    """色散模式（默认 εeff_e/o）裁判：其响应与理想矩阵带内 |S11| 差 ~0.16
    （真偶/奇模模型差异，非反提问题）——幅值域反提在 ±3% 窗拟合残差
    8.7e−2 仍超门 → raise 如实；裁判模型问题只记录不改（归 #11）。"""
    design = _design()
    s11, s21 = _sparams(design, _WIN_3, sync=False)
    with pytest.raises(ValueError, match="拟合残差过大"):
        coupling_matrix_extract(
            freq_ghz=[float(v) for v in _WIN_3], s11=s11, s21=s21,
            order=_ORDER, f0_ghz=_F0, fbw=_FBW, domain="magnitude")
    # 模型差钉值：裁判 |S11| vs 理想矩阵 |S11| 带内最大差 >0.05（实测 0.16）
    from rfauto.core.calculators import coupling_matrix_response

    resp = coupling_matrix_response(freq_ghz=[float(v) for v in _WIN_3],
                                    f0_ghz=_F0, fbw=_FBW,
                                    matrix=[[[float(v.real), float(v.imag)]
                                             for v in row] for row in _kij_ref()])
    sc = np.array(resp["s_matrix"])
    s11_ideal = np.abs(sc[:, 0, 0, 0] + 1j * sc[:, 0, 0, 1])
    sj = coupled_bpf_circuit_sparams(_WIN_3, design)
    gap = float(np.max(np.abs(np.abs(sj[:, 0, 0]) - s11_ideal)))
    assert gap > 0.05
