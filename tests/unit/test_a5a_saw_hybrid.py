"""架构批 A5-A 席锚树：saw_idt 三键（同步设计双向/δ 模型频响/延迟线）+
hybrid_junction 三键（魔 T S 矩阵/H·E 面三口结/和差合成）。

数值断言口径（#118 不自证——恒等式/独立常数/独立路线/跨键互证，不用
自身推导互证）：
- SAW 同步：f0=v/λ0 测试侧独立换算；pitch→f0→pitch 往返逐位；Δf_NN·N_p=
  2f0、L=N_p·λ0、τ=L/v 恒等式；ST 石英 pitch=1µm→3.158GHz 教科书常数窗
  （v_R=3158 m/s 文献典型值注入，常数链测试侧独立换算）。
- SAW 频响：测试侧几何级数逐项 cmath 求和（独立实现）vs 内核 Dirichlet 闭
  式 ≤1e-12；峰点 0dB；首零点 f0(1±1/N) |H|²<1e-24；半零点 (2/π)² 经典常
  数窗（独立常数 4/π²）；栅瓣 2f0 归一功率=1（混叠如实）；内核 exact-vs-geo
  内检残差 ≤1e-12。
- SAW 延迟线：τ=L/v 测试侧独立换算（3.158mm/3158→恰 1.0µs 整点）；f×2→
  损耗×4 标度；双端双向辐射损耗 2×10lg2=6.0206dB 常数（20log10(2) 独立
  常数式）；总损耗=传播+双向恒等式。
- 魔 T：numpy SS†=I 独立复算 ≤1e-12（内核残差字段为纯 Python 路线）；
  S14=S41=0 隔离、|S21|²=0.5 均分、S=Sᵀ 互易、σmax=1 无源；激励 1/4 的
  侧臂相位差 0°/180° 恒等；激励 2→和/差口各半。
- 三口结：KCL/KVL 约束方程组 numpy linalg 独立重解（并联星形 KCL+串联
  环形 KVL，与内核常数矩阵异路线）≤1e-12；S_E=−S_H 对偶逐元素；|S11|=
  1/3、20lg(2/3)=−3.5218dB、回损 9.5424dB 常数；幺正残差复算。
- 和差合成：能量守恒残差 ≤1e-12；等幅同相→差口 null（frac=0）、反相→
  和口 null；正交等幅→两口各恰=输入 dBm（−0.00dB 拆分恒等）；不等幅混
  合点测试侧 cmath 独立重算；跨键=魔 T 4 口矩阵乘 b=S·a 匹配负载口径
  逐位互证（独立路线）。
- 描述形态门：六键 describe 带中文名描述+组名（匹配·功分·衰减·耦合 ×3 /
  滤波器与耦合矩阵 ×3）+参数元数据齐备。
"""

from __future__ import annotations

import cmath
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calculators import CALCULATOR_REGISTRY
from rfauto.service.calculator_service import run_calculator

_V_ST_QUARTZ = 3158.0             # m/s（ST-cut 石英声速，文献典型值注入）
_HALF_NULL_CONST = (2.0 / math.pi) ** 2   # Dirichlet 半零点经典常数（独立式）


# ─── 公共小工具 ──────────────────────────────────────────────────────────────


def _run(key: str, params: dict) -> dict:
    out = run_calculator(key, params)
    assert out["ok"] is True, f"{key} 未成功: {out.get('error')!r}"
    return out["result"]


def _reject(key: str, params: dict) -> None:
    out = run_calculator(key, params)
    assert out["ok"] is False, f"{key} 越界输入未拒绝: {params!r}"
    assert out.get("error"), f"{key} 报错缺 error 字段: {out!r}"


def _geo_power(f_over_f0: float, n_p: int) -> float:
    """测试侧独立实现：指纹格几何级数逐项 cmath 求和（vs 内核 Dirichlet
    闭式——同物理异数值路线，#118 双实现互证载体）。"""
    acc = 0.0 + 0.0j
    for n in range(n_p):
        acc += cmath.exp(-2j * math.pi * n * f_over_f0)
    return (abs(acc) / n_p) ** 2


def _shunt_tee_b() -> list[complex]:
    """并联星形结 KCL 约束方程组独立重解（a1=1 激励）。

    未知 [b1,b2,b3,V]：行 n：b_n − V = −a_n（V=a_n+b_n 节点电压定义）；
    行 4：3V = 2Σa_n（KCL：Σ(2a_n−V)=0）。与内核常数矩阵异路线。"""
    a = [1.0, 0.0, 0.0]
    amat = np.array([
        [1, 0, 0, -1],
        [0, 1, 0, -1],
        [0, 0, 1, -1],
        [0, 0, 0, 3],
    ], dtype=float)
    bvec = np.array([-a[0], -a[1], -a[2], 2 * sum(a)], dtype=float)
    sol = np.linalg.solve(amat, bvec)
    return [complex(v) for v in sol[:3]]


def _series_tee_b() -> list[complex]:
    """串联环形结 KVL 约束方程组独立重解（a1=1 激励）。

    未知 [b1,b2,b3,I]：行 n：b_n + I = a_n（b_n=a_n−I，环路电流共联）；
    行 4：Σb_n = −Σa_n（KVL：Σ(a_n+b_n)=0）。与内核常数矩阵异路线。"""
    a = [1.0, 0.0, 0.0]
    amat = np.array([
        [1, 0, 0, 1],
        [0, 1, 0, 1],
        [0, 0, 1, 1],
        [1, 1, 1, 0],
    ], dtype=float)
    bvec = np.array([a[0], a[1], a[2], -sum(a)], dtype=float)
    sol = np.linalg.solve(amat, bvec)
    return [complex(v) for v in sol[:3]]


def _mat(result: dict, n: int) -> np.ndarray:
    raw = np.asarray(result["s_matrix"], dtype=float)
    assert raw.shape == (n, n, 2)
    return raw[..., 0] + 1j * raw[..., 1]


# ─── saw_idt_sync_design：往返 / 教科书常数 / 恒等式 ─────────────────────────


def test_sync_pitch_to_f0_st_quartz_textbook_constant():
    r = _run("saw_idt_sync_design", {"v_sound_m_s": _V_ST_QUARTZ,
                                     "n_finger_pairs": 30, "pitch_um": 1.0})
    # 教科书常数链（测试侧独立换算）：f0 = v/λ = 3158e6/1e-6·1e-6 m
    f0_direct_ghz = _V_ST_QUARTZ / (1.0e-6) / 1e9
    assert r["f0_ghz"] == pytest.approx(3.158, abs=1e-12)
    assert r["f0_ghz"] == pytest.approx(f0_direct_ghz, rel=1e-15)
    assert r["solve_dir"] == "pitch_to_f0"
    assert r["lambda0_um"] == pytest.approx(1.0, abs=1e-15)


def test_sync_bidirectional_roundtrip_bitwise():
    r1 = _run("saw_idt_sync_design", {"v_sound_m_s": 3488.0,
                                      "n_finger_pairs": 25, "pitch_um": 1.4})
    r2 = _run("saw_idt_sync_design", {"v_sound_m_s": 3488.0,
                                      "n_finger_pairs": 25,
                                      "f0_ghz": r1["f0_ghz"]})
    assert r2["solve_dir"] == "f0_to_pitch"
    assert r2["pitch_um"] == pytest.approx(1.4, rel=1e-14)
    assert r2["f0_ghz"] == pytest.approx(r1["f0_ghz"], rel=1e-15)


def test_sync_bandwidth_length_delay_identities():
    n_p = 30
    r = _run("saw_idt_sync_design", {"v_sound_m_s": _V_ST_QUARTZ,
                                     "n_finger_pairs": n_p, "pitch_um": 1.0})
    f0_ghz = r["f0_ghz"]
    # 恒等式（测试侧独立式）：Δf_NN·N = 2f0；分数带宽 = 2/N
    assert r["null_null_bw_ghz"] * n_p == pytest.approx(2.0 * f0_ghz,
                                                        rel=1e-12)
    assert r["fractional_bw_null_null"] == pytest.approx(2.0 / n_p,
                                                         rel=1e-15)
    # L = N·λ0；τ = L/v（测试侧独立换算）
    assert r["idt_length_um"] == pytest.approx(n_p * r["lambda0_um"],
                                               rel=1e-15)
    delay_direct_us = r["idt_length_um"] * 1e-6 / _V_ST_QUARTZ * 1e6
    assert r["idt_delay_us"] == pytest.approx(delay_direct_us, rel=1e-12)


# ─── saw_idt_frequency_response：双路线互证 / 零点栅格 / 经典常数 ────────────


@pytest.mark.parametrize("f_ghz", [0.95, 0.99, 1.0, 1.0033333333333333,
                                   1.05, 1.5, 2.0])
def test_response_geometric_series_crosscheck(f_ghz):
    n_p = 30
    r = _run("saw_idt_frequency_response",
             {"f0_ghz": 1.0, "n_finger_pairs": n_p, "freq_ghz": [f_ghz]})
    row = r["points"][0]
    u = (f_ghz - 1.0) / 1.0
    # 独立路线：几何级数逐项和 vs 内核 Dirichlet 闭式
    assert row["power_exact"] == pytest.approx(_geo_power(f_ghz, n_p),
                                               rel=1e-9, abs=1e-18)
    if row["power_exact"] > 1e-20:
        # 内核自检列（exact vs 内核自己的几何级数路线；深零点两侧同为
        # 浮点噪声、相对偏差无意义，只钉深零点本身 <1e-20）
        assert row["exact_vs_geo_rel_dev"] <= 1e-12
    else:
        assert row["power_exact"] < 1e-20
        assert row["power_geometric_sum"] < 1e-20
    assert row["detune_frac"] == pytest.approx(u, rel=1e-12)


def test_response_peak_nulls_and_half_null_constant():
    n_p = 30
    freqs = [1.0, 1.0 - 1.0 / n_p, 1.0 + 1.0 / n_p, 1.0 + 1.0 / (2 * n_p)]
    r = _run("saw_idt_frequency_response",
             {"f0_ghz": 1.0, "n_finger_pairs": n_p, "freq_ghz": freqs})
    p_peak, p_null_lo, p_null_hi, p_half = [
        row["power_exact"] for row in r["points"]]
    assert p_peak == pytest.approx(1.0, rel=1e-15)
    assert r["points"][0]["mag_db"] == pytest.approx(0.0, abs=1e-12)
    # 首零点：|H|²→0（浮点下 <1e-24）
    assert p_null_lo < 1e-24 and p_null_hi < 1e-24
    # 半零点经典常数（独立常数式 (2/π)²，sinc 高阶项 1e-3 相对窗）
    assert p_half == pytest.approx(_HALF_NULL_CONST, rel=1e-3)
    # 零点栅格字段恒等式
    assert r["first_null_offsets_ghz"] == pytest.approx(
        [1.0 - 1.0 / n_p, 1.0 + 1.0 / n_p], rel=1e-12)
    assert r["null_null_bw_ghz"] == pytest.approx(2.0 / n_p, rel=1e-12)


def test_response_grating_lobe_aliasing_reported():
    n_p = 30
    r = _run("saw_idt_frequency_response",
             {"f0_ghz": 1.0, "n_finger_pairs": n_p, "freq_ghz": [2.0, 3.0]})
    for row in r["points"]:
        # 栅瓣 f=(m+1)f0：δ 阵列因子归一功率=1（混叠如实报告）
        assert row["power_exact"] == pytest.approx(1.0, rel=1e-12)
        assert row["mag_db"] == pytest.approx(0.0, abs=1e-10)


# ─── saw_delay_line：τ 恒等 / f² 标度 / 6.0206dB 常数 ────────────────────────


def test_delay_identity_and_one_microsecond_anchor():
    r = _run("saw_delay_line", {"f0_ghz": 1.0, "v_sound_m_s": _V_ST_QUARTZ,
                                "idt_gap_mm": 3.158,
                                "loss_db_per_us_1ghz": 0.5})
    # 整点锚：3.158mm @3158m/s → 恰 1.0µs（测试侧独立换算）
    delay_direct_us = 3.158e-3 / _V_ST_QUARTZ * 1e6
    assert r["delay_us"] == pytest.approx(1.0, abs=1e-12)
    assert r["delay_us"] == pytest.approx(delay_direct_us, abs=1e-12)
    # 3.158mm @λ0=3.158µm → 1000 波长（测试侧独立换算）
    assert r["gap_wavelengths"] == pytest.approx(
        3.158e3 / (r["lambda0_um"]), rel=1e-12)
    # 损耗预算恒等式：α = α₁·f²·τ
    assert r["propagation_loss_db"] == pytest.approx(0.5 * 1.0 * 1.0,
                                                     rel=1e-12)
    # 双向 IDT 辐射损耗常数：2×10lg2（独立常数式 20log10(2)）
    assert r["bilateral_idt_loss_db_total"] == pytest.approx(
        20.0 * math.log10(2.0), rel=1e-12)
    assert r["total_loss_db"] == pytest.approx(
        0.5 + 20.0 * math.log10(2.0), rel=1e-12)


def test_delay_f_squared_scaling():
    base = _run("saw_delay_line", {"f0_ghz": 1.0,
                                   "v_sound_m_s": _V_ST_QUARTZ,
                                   "idt_gap_mm": 3.158,
                                   "loss_db_per_us_1ghz": 0.5})
    doubled = _run("saw_delay_line", {"f0_ghz": 2.0,
                                      "v_sound_m_s": _V_ST_QUARTZ,
                                      "idt_gap_mm": 3.158,
                                      "loss_db_per_us_1ghz": 0.5})
    # f² 标度：f×2 → 传播损耗恰 ×4（同 gap 同 τ）
    assert doubled["delay_us"] == pytest.approx(base["delay_us"], rel=1e-12)
    assert doubled["propagation_loss_db"] == pytest.approx(
        4.0 * base["propagation_loss_db"], rel=1e-12)


# ─── magic_tee_s_matrix：幺正 / 常数 / 相位行为 ──────────────────────────────


def test_magic_tee_unitarity_reciprocity_constants():
    r = _run("magic_tee_s_matrix", {"excite_port": 1})
    s = _mat(r, 4)
    # numpy 独立复算（内核残差字段=纯 Python 路线，异路线互证）
    assert np.max(np.abs(s @ s.conj().T - np.eye(4))) <= 1e-12
    assert r["unitarity_residual"] <= 1e-12
    assert np.max(np.abs(s - s.T)) == 0.0            # 互易 S=Sᵀ
    assert abs(s[0, 3]) == 0.0 and abs(s[3, 0]) == 0.0   # E/H 臂隔离
    assert abs(s[0, 0]) == 0.0 and abs(s[3, 3]) == 0.0   # 全匹配
    assert abs(abs(s[1, 0]) - 1.0 / math.sqrt(2.0)) <= 1e-15
    assert abs(s[1, 0]) ** 2 == pytest.approx(0.5, abs=1e-15)
    assert r["isolation_s14_linear"] == 0.0
    assert r["split_power_db"] == pytest.approx(-3.010299956639812,
                                                rel=1e-12)
    # σmax=1（无源且无损=幺正推论）
    assert np.linalg.svd(s, compute_uv=False)[0] <= 1.0 + 1e-12


def test_magic_tee_excite_port_float_int_accepted():
    """A1-P2-2 回归钉：整值 float（JSON 通道 2.0）经 _as_int 家族宽口径
    收敛通过且行为与 int 同口径；非整值/bool/nan 仍显式拒绝。"""
    r_int = _run("magic_tee_s_matrix", {"excite_port": 2})
    r_float = _run("magic_tee_s_matrix", {"excite_port": 2.0})
    assert r_float["excite_port"] == 2
    assert r_float["s_matrix"] == r_int["s_matrix"]
    assert r_float["output_powers_frac"] == r_int["output_powers_frac"]
    _reject("magic_tee_s_matrix", {"excite_port": 2.5})   # 非整值仍拒
    _reject("magic_tee_s_matrix", {"excite_port": True})  # bool 显式拒收
    _reject("magic_tee_s_matrix", {"excite_port": "2"})   # 字符串仍拒


@pytest.mark.parametrize("excite,phase_deg", [(1, 0.0), (4, 180.0)])
def test_magic_tee_phase_behavior_sum_diff(excite, phase_deg):
    r = _run("magic_tee_s_matrix", {"excite_port": excite})
    powers = r["output_powers_frac"]
    # 匹配口径：激励口无反射（|S_xx|=0），功率全部分给侧臂
    assert powers[excite - 1] == pytest.approx(0.0, abs=1e-15)
    assert powers[1] == pytest.approx(0.5, abs=1e-15)
    assert powers[2] == pytest.approx(0.5, abs=1e-15)
    assert powers[0] == pytest.approx(0.0, abs=1e-15)
    assert powers[3] == pytest.approx(0.0, abs=1e-15)
    assert r["phase_pair"] == [2, 3]
    assert r["phase_diff_deg"] == pytest.approx(phase_deg, abs=1e-9)


@pytest.mark.parametrize("excite,phase_deg", [(2, 0.0), (3, 180.0)])
def test_magic_tee_side_arm_excitation(excite, phase_deg):
    r = _run("magic_tee_s_matrix", {"excite_port": excite})
    powers = r["output_powers_frac"]
    # 激励侧臂 → 和口/差口各半（侧臂姊妹口隔离）
    assert powers[0] == pytest.approx(0.5, abs=1e-15)
    assert powers[3] == pytest.approx(0.5, abs=1e-15)
    assert powers[1] == pytest.approx(0.0, abs=1e-15)
    assert powers[2] == pytest.approx(0.0, abs=1e-15)
    assert powers[excite - 1] == pytest.approx(0.0, abs=1e-15)
    assert r["phase_pair"] == [1, 4]
    assert r["phase_diff_deg"] == pytest.approx(phase_deg, abs=1e-9)


# ─── waveguide_tee_s_matrix：KCL/KVL 独立重解 / 对偶 / 常数 ─────────────────


@pytest.mark.parametrize("tee_type,solver", [
    ("h_plane", _shunt_tee_b),
    ("e_plane", _series_tee_b),
])
def test_tee_kcl_kvl_independent_resolve(tee_type, solver):
    r = _run("waveguide_tee_s_matrix", {"tee_type": tee_type})
    s = _mat(r, 3)
    expect = solver()          # 约束方程组独立重解（异路线）
    got = [s[0, 0], s[1, 0], s[2, 0]]     # 激励口 1 的输出列
    for g, e in zip(got, expect, strict=True):
        assert g == pytest.approx(e, rel=1e-12, abs=1e-15)
    # 幺正 + 互易 + 常数
    assert np.max(np.abs(s @ s.conj().T - np.eye(3))) <= 1e-12
    assert r["unitarity_residual"] <= 1e-12
    assert np.max(np.abs(s - s.T)) <= 1e-15
    assert r["s11_mag"] == pytest.approx(1.0 / 3.0, rel=1e-15)
    assert r["s11_return_loss_db"] == pytest.approx(-20.0 * math.log10(1.0 / 3.0),
                                                    rel=1e-12)
    assert r["side_split_db"] == pytest.approx(20.0 * math.log10(2.0 / 3.0),
                                               rel=1e-12)
    assert r["side_to_side_linear"] == pytest.approx(2.0 / 3.0, rel=1e-15)


def test_tee_dual_identity_s_e_minus_s_h():
    h = _mat(_run("waveguide_tee_s_matrix", {"tee_type": "h_plane"}), 3)
    e = _mat(_run("waveguide_tee_s_matrix", {"tee_type": "e_plane"}), 3)
    # 对偶恒等式：S_E = −S_H（逐元素，测试侧独立检查）
    assert np.max(np.abs(e + h)) <= 1e-15
    for r in (_run("waveguide_tee_s_matrix", {"tee_type": "h_plane"}),
              _run("waveguide_tee_s_matrix", {"tee_type": "e_plane"})):
        assert r["duality_residual"] <= 1e-15


# ─── hybrid_sum_difference：守恒 / 双 null / 正交拆分 / 跨键互证 ─────────────


def test_sumdiff_inphase_diff_port_null():
    r = _run("hybrid_sum_difference", {"p2_dbm": 10.0, "p3_dbm": 10.0,
                                       "phase_deg": 0.0})
    assert r["p_diff_dbm"] is None                 # 隔离 null 如实 None
    assert r["frac_diff"] == pytest.approx(0.0, abs=1e-15)
    assert r["frac_sum"] == pytest.approx(1.0, abs=1e-15)
    assert r["dominant_port"] == "sum"
    assert r["isolation_null"] is True
    assert r["p_sum_dbm"] == pytest.approx(13.010299956639812, rel=1e-12)
    assert r["conservation_residual"] <= 1e-12


def test_sumdiff_antiphase_sum_port_null():
    r = _run("hybrid_sum_difference", {"p2_dbm": 10.0, "p3_dbm": 10.0,
                                       "phase_deg": 180.0})
    assert r["p_sum_dbm"] is None
    assert r["frac_sum"] == pytest.approx(0.0, abs=1e-15)
    assert r["dominant_port"] == "diff"
    assert r["p_diff_dbm"] == pytest.approx(13.010299956639812, rel=1e-12)


def test_sumdiff_quadrature_exact_half_split():
    r = _run("hybrid_sum_difference", {"p2_dbm": 10.0, "p3_dbm": 10.0,
                                       "phase_deg": 90.0})
    # 正交等幅：两口各恰=输入 dBm（|b|²=P_mW → 同 dBm 拆分恒等）
    assert r["frac_sum"] == pytest.approx(0.5, abs=1e-15)
    assert r["frac_diff"] == pytest.approx(0.5, abs=1e-15)
    assert r["p_sum_dbm"] == pytest.approx(10.0, rel=1e-12)
    assert r["p_diff_dbm"] == pytest.approx(10.0, rel=1e-12)
    assert r["dominant_port"] == "balanced"


def test_sumdiff_unequal_mix_independent_recompute():
    p2, p3, ph = 10.0, 7.0, 30.0
    r = _run("hybrid_sum_difference", {"p2_dbm": p2, "p3_dbm": p3,
                                       "phase_deg": ph})
    a2 = cmath.sqrt(10.0 ** (p2 / 10.0))
    a3 = cmath.sqrt(10.0 ** (p3 / 10.0)) * cmath.exp(1j * math.radians(ph))
    p_sum_mw = abs((a2 + a3) / math.sqrt(2.0)) ** 2
    p_diff_mw = abs((a2 - a3) / math.sqrt(2.0)) ** 2
    assert r["p_sum_dbm"] == pytest.approx(10.0 * math.log10(p_sum_mw),
                                           rel=1e-12)
    assert r["p_diff_dbm"] == pytest.approx(10.0 * math.log10(p_diff_mw),
                                            rel=1e-12)
    assert r["conservation_residual"] <= 1e-12


def test_sumdiff_crosskey_magic_tee_matrix_mult():
    """跨键互证：4 口矩阵乘 b=S·a（匹配负载口径）vs 和差闭式（独立路线）。"""
    p2, p3, ph = 10.0, 4.0, 60.0
    sd = _run("hybrid_sum_difference", {"p2_dbm": p2, "p3_dbm": p3,
                                        "phase_deg": ph})
    mt = _run("magic_tee_s_matrix", {"excite_port": 2})
    s = _mat(mt, 4)
    a2 = cmath.sqrt(10.0 ** (p2 / 10.0))
    a3 = cmath.sqrt(10.0 ** (p3 / 10.0)) * cmath.exp(1j * math.radians(ph))
    a_vec = np.array([0.0, a2, a3, 0.0])
    b_vec = s @ a_vec
    assert 10.0 * math.log10(abs(b_vec[0]) ** 2) == pytest.approx(
        sd["p_sum_dbm"], rel=1e-12)
    assert 10.0 * math.log10(abs(b_vec[3]) ** 2) == pytest.approx(
        sd["p_diff_dbm"], rel=1e-12)
    # 激励口 2 的姊妹口 3 隔离（矩阵乘口径）
    assert abs(b_vec[2]) == pytest.approx(0.0, abs=1e-15)


# ─── 描述形态门（中文名描述/组名/参数元数据）────────────────────────────────


def test_describe_form_new_six_keys():
    expected_groups = {
        "saw_idt_sync_design": "滤波器与耦合矩阵",
        "saw_idt_frequency_response": "滤波器与耦合矩阵",
        "saw_delay_line": "滤波器与耦合矩阵",
        "magic_tee_s_matrix": "匹配·功分·衰减·耦合",
        "waveguide_tee_s_matrix": "匹配·功分·衰减·耦合",
        "hybrid_sum_difference": "匹配·功分·衰减·耦合",
    }
    by_name = {c["name"]: c for c in CALCULATOR_REGISTRY.describe()}
    for key, group in expected_groups.items():
        entry = by_name[key]
        assert entry["group"] == group, f"{key} 组名不符: {entry['group']!r}"
        assert entry["experimental"] is False
        assert entry["description"], f"{key} 缺描述"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in entry["description"]), (
            f"{key} 描述缺中文名形态: {entry['description']!r}")
        assert all({"name", "desc", "required"} <= set(p)
                   for p in entry["params"])
