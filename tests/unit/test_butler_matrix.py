"""4×4 Butler 矩阵内核单测（研究扩充 round3 §二 F-F 表件 1）。

裁判口径（#118 双路径，不自证）：
- 路径 A = 闭式层级合成（混合环/交叉结/移相器酉阵·置换阵之积 + 45° 单位
  相位表锚，两套独立书算在内核内互断）；
- 路径 B = skrf Network 级联（端口逐一线缆级联，独立连线簿记）；
  预声明门 max|ΔS| ≤ 1e-9（实测 0.0，逐位一致）。
- 混合环恒等式按无耗口径（每列 Σ|S_ij|²=1）：任务书字面 (−1/2) 前因子
  矩阵每列能量 1/2（有耗）且通路口等相位致波束口简并，系规格书勘误
  （内核 docstring"任务书规格勘误"节），此处按物理正确口径钉。
- 波束角：array_synthesis.array_factor 数值扫角 argmax vs 闭式
  asin((k−2.5)·λ/(N·d))，预声明 ±1° 带（实测 ~1e-4°，网格分辨率限）。
全部确定性、无网络、无真机。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import butler_matrix as bm

TOL = 1e-9


# ─── 1. 混合环恒等式 ─────────────────────────────────────────────────────────


def test_hybrid_unitary():
    s = bm.butler_hybrid_s_matrix()
    assert np.allclose(s @ s.conj().T, np.eye(4), atol=1e-12)
    col_energy = np.sum(np.abs(s) ** 2, axis=0)
    assert np.allclose(col_energy, 1.0, rtol=1e-12)
    # 全矩阵能量（8 个通路口条目）：无耗口径
    assert abs(np.sum(np.abs(s) ** 2) - 4.0) < 1e-12


def test_hybrid_pinned_matrix_anchor():
    # 钉死约定的显式矩阵（内核 docstring），逐条目 rel 1e-12
    expect = (1.0 / math.sqrt(2.0)) * np.array(
        [[0, 1, 1j, 0], [1, 0, 0, 1], [1j, 0, 0, -1j], [0, 1, -1j, 0]], dtype=complex
    )
    s = bm.butler_hybrid_s_matrix()
    assert np.allclose(s, expect, rtol=1e-12, atol=1e-15)


def test_hybrid_quadrature_and_isolation():
    s = bm.butler_hybrid_s_matrix()
    # 匹配：对角全零
    assert np.allclose(np.diag(s), 0.0, atol=1e-15)
    # 隔离对 (1,4) 与 (2,3)（0 基 (0,3)、(1,2)）
    assert s[3, 0] == 0.0 and s[0, 3] == 0.0
    assert s[2, 1] == 0.0 and s[1, 2] == 0.0
    # 3 dB：每个入口两出臂幅度均 1/√2
    for inp, outs in ((0, (1, 2)), (3, (1, 2))):
        for o in outs:
            assert abs(abs(s[o, inp]) - 1.0 / math.sqrt(2.0)) < 1e-12
    # 正交：每入口两出臂相位差恰 ±90°
    d01 = np.angle(s[1, 0] / s[2, 0])
    assert abs(abs(d01) - math.pi / 2) < 1e-12
    d43 = np.angle(s[1, 3] / s[2, 3])
    assert abs(abs(d43) - math.pi / 2) < 1e-12


def test_hybrid_reciprocal():
    s = bm.butler_hybrid_s_matrix()
    assert np.allclose(s, s.T, atol=1e-15)


# ─── 2. 交叉结与移相器 ────────────────────────────────────────────────────────


def test_crossover_permutation_identity():
    s = bm.butler_crossover_s_matrix()
    assert np.allclose(s @ s.conj().T, np.eye(4), atol=1e-15)
    assert np.allclose(s, s.T, atol=1e-15)
    assert set(np.abs(s).ravel().tolist()) <= {0.0, 1.0}
    # 内对角交叉：左上入(0)→右下出(3)，左下入(1)→右上出(2)；直通为零
    assert s[3, 0] == 1.0 and s[2, 1] == 1.0
    assert s[2, 0] == 0.0 and s[3, 1] == 0.0


def test_phase_shifter_unitary_and_normalization():
    for phi in (0.0, math.pi / 4, 1.234, -2.5, 2.0 * math.pi + 0.7):
        s = bm.butler_phase_shifter_s_matrix(phi)
        assert np.allclose(s @ s.conj().T, np.eye(2), atol=1e-12)
    # 规范化：φ 与 φ+2πk 同矩阵（钉死规范化而非报错）
    a = bm.butler_phase_shifter_s_matrix(0.25)
    b = bm.butler_phase_shifter_s_matrix(0.25 + 4.0 * math.pi)
    c = bm.butler_phase_shifter_s_matrix(0.25 - 2.0 * math.pi)
    assert np.allclose(a, b, atol=1e-14)
    assert np.allclose(a, c, atol=1e-14)
    # 相位值精确
    assert abs(np.angle(a[0, 1]) - 0.25) < 1e-12


def test_phase_shifter_guards():
    with pytest.raises(ValueError):
        bm.butler_phase_shifter_s_matrix(True)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        bm.butler_phase_shifter_s_matrix(float("nan"))
    with pytest.raises(ValueError):
        bm.butler_phase_shifter_s_matrix(float("inf"))


# ─── 3. 闭式 4×4 Butler：幅度/无耗/相位表 ────────────────────────────────────


def test_closed_form_equal_amplitude_half():
    s = bm.butler4_s_beam_to_antenna()
    assert np.allclose(np.abs(s), 0.5, rtol=1e-9, atol=1e-12)


def test_closed_form_lossless():
    s = bm.butler4_s_beam_to_antenna()
    assert np.allclose(s @ s.conj().T, np.eye(4), atol=TOL)
    assert np.allclose(np.sum(np.abs(s) ** 2, axis=0), 1.0, atol=TOL)
    assert np.allclose(np.sum(np.abs(s) ** 2, axis=1), 1.0, atol=TOL)


def test_closed_form_phase_table_anchor():
    # 45° 单位相位表（mod 8）逐位等于内核钉死锚（书算独立第二路径）
    s = bm.butler4_s_beam_to_antenna()
    ph = np.round(np.angle(s) / (math.pi / 4)).astype(int) % 8
    assert np.array_equal(ph, np.array(bm._S_PHASE_UNITS, dtype=int))
    # 相位必须恰落在 45° 栅格上（round-trip 残差为零）
    residual = np.angle(s * np.exp(-1j * (math.pi / 4) * ph))
    assert np.allclose(residual, 0.0, atol=1e-12)


def test_closed_form_progression_formula():
    # δ_k = (2k−N−1)·π/N，mod 360；且每行严格几何（n·δ_k）
    s = bm.butler4_s_beam_to_antenna()
    for k in range(1, 5):
        d_closed = (2 * k - 5) * math.pi / 4
        row = s[k - 1, :]
        d_meas = math.degrees(np.angle(row[1] / row[0]))
        assert abs(bm._wrap_deg(d_meas - math.degrees(d_closed))) < 1e-9
        for n in (2, 3):
            got = math.degrees(np.angle(row[n] / row[0]))
            assert abs(bm._wrap_deg(got - n * math.degrees(d_closed))) < 1e-9


def test_full_s8_structure():
    s8 = bm.butler4_s_full()
    s_ba = bm.butler4_s_beam_to_antenna()
    assert np.allclose(s8[:4, :4], 0.0, atol=1e-15)  # 波束口反射/隔离精确 0
    assert np.allclose(s8[4:, 4:], 0.0, atol=1e-15)
    assert np.allclose(s8[:4, 4:], s_ba, atol=1e-15)
    assert np.allclose(s8[4:, :4], s_ba.T, atol=1e-15)  # 互易
    assert np.allclose(s8 @ s8.conj().T, np.eye(8), atol=TOL)


# ─── 4. 双路径互证（#118 主判据） ────────────────────────────────────────────


def test_dual_path_skrf_matches_closed_form_bitwise():
    s_closed = bm.butler4_s_beam_to_antenna()
    s_skrf = bm.butler4_s_beam_to_antenna_skrf()
    assert np.max(np.abs(s_skrf - s_closed)) <= TOL


def test_skrf_full_network_properties():
    s8 = bm.butler4_s_full_skrf()
    assert np.allclose(s8 @ s8.conj().T, np.eye(8), atol=TOL)  # 无耗
    assert float(np.max(np.abs(s8[:4, :4]))) <= TOL  # 波束口间隔离（实测 0.0）
    assert float(np.max(np.abs(s8[4:, 4:]))) <= TOL
    assert np.allclose(s8, s8.T, atol=TOL)  # 互易
    # 两条路径的全 8 口矩阵逐位一致
    assert np.max(np.abs(s8 - bm.butler4_s_full())) <= TOL


# ─── 5. 激励向量与相位递进 ────────────────────────────────────────────────────


def test_beam_excitation_equal_amplitude_and_guards():
    for k in (1, 2, 3, 4):
        w = bm.beam_excitation(k)
        assert w.shape == (4,)
        assert np.allclose(np.abs(w), 0.5, atol=1e-12)
    for bad in (0, 5, -1, True, 1.5, "2", None):
        with pytest.raises(ValueError):
            bm.beam_excitation(bad)


def test_progression_measured_matches_formula():
    s = bm.butler4_s_beam_to_antenna()
    for k in range(1, 5):
        expect = (2 * k - 5) * 45.0
        got = bm._wrap_deg(np.degrees(np.angle(s[k - 1, 1] / s[k - 1, 0])))
        assert abs(bm._wrap_deg(got - expect)) < 1e-9
    # 钉死端口序：δ 集合 = {±45°, ±135°}（按 B1..B4 = −135,−45,+45,+135）
    assert bm._wrap_deg(math.degrees(np.angle(s[0, 1] / s[0, 0]))) == -135.0
    assert bm._wrap_deg(math.degrees(np.angle(s[1, 1] / s[1, 0]))) == -45.0
    assert bm._wrap_deg(math.degrees(np.angle(s[2, 1] / s[2, 0]))) == 45.0
    assert bm._wrap_deg(math.degrees(np.angle(s[3, 1] / s[3, 0]))) == 135.0


# ─── 6. 波束指向验证面 ────────────────────────────────────────────────────────


def test_beam_angles_closed_values():
    rows = bm.beam_angles_closed(0.5)
    assert [r["beam_port"] for r in rows] == [1, 2, 3, 4]
    assert np.allclose([r["sin_theta"] for r in rows], [-0.75, -0.25, 0.25, 0.75], rtol=1e-12)
    assert abs(rows[0]["theta_deg"] - math.degrees(math.asin(-0.75))) < 1e-12
    assert [r["delta_deg"] for r in rows] == [-135.0, -45.0, 45.0, 135.0]


def test_beam_angles_closed_guards():
    with pytest.raises(ValueError):
        bm.beam_angles_closed(0.0)
    with pytest.raises(ValueError):
        bm.beam_angles_closed(-0.5)
    with pytest.raises(ValueError):
        bm.beam_angles_closed(True)
    # d 过小 → 闭式指向越可见区
    with pytest.raises(ValueError):
        bm.beam_angles_closed(0.1)


def test_beam_steering_af_argmax_matches_closed():
    rep = bm.verify_beam_steering()
    assert rep.all_pass
    for err in rep.angle_error_deg:
        assert abs(err) <= bm.ANGLE_BAND_DEG
        assert abs(err) <= 1e-3  # 数值扫角分辨率余量（实测 ~1e-4°）
    # B1 峰角锚（asin(−0.75)）
    assert abs(rep.theta_peak_deg[0] - math.degrees(math.asin(-0.75))) < 1e-3


def test_beam_steering_custom_spacing():
    # d=λ/2 之外的合法间距（d=1.0：sinθ_k = (k−2.5)/4）
    rep = bm.verify_beam_steering(spacing_lambda=1.0, n_points=2001)
    assert rep.all_pass
    assert abs(rep.sin_theta_closed[0] - (1 - 2.5) / 4.0) < 1e-12


def test_verify_guards():
    with pytest.raises(ValueError):
        bm.verify_beam_steering(n_points=100)
    with pytest.raises(ValueError):
        bm.verify_beam_steering(n_points=True)
    with pytest.raises(ValueError):
        bm.verify_beam_steering(spacing_lambda=float("nan"))


def test_steering_report_to_dict_json_serializable():
    rep = bm.verify_beam_steering()
    d = rep.to_dict()
    blob = json.dumps(d)  # 全字段 JSON 可序列化
    back = json.loads(blob)
    assert back["all_pass"] is True
    assert back["dual_path_max_absdiff"] <= TOL
    assert back["beam_isolation_max"] <= TOL
    assert back["amplitude_max_dev"] <= TOL
    assert len(back["theta_peak_deg"]) == 4


# ─── 7. 连线表钉死 ────────────────────────────────────────────────────────────


def test_wiring_table_pinned():
    wt = bm.butler_wiring_table()
    assert wt["beam_port_to_slot"] == {"1": 1, "2": 4, "3": 2, "4": 3}
    assert wt["line_shifters_deg"] == {"a1": 0.0, "b1": 135.0, "a2": 0.0, "b2": 45.0}
    assert wt["crossover1"]["crossed"] == [["b1", "a2"]]
    assert wt["antennas"] == {"A1": "HR1_top_out", "A2": "HR2_top_out",
                              "A3": "HR1_bottom_out", "A4": "HR2_bottom_out"}
    json.dumps(wt)  # JSON 可序列化


def test_wiring_vs_closed_form_consistency():
    """连线表的交叉结/移相器代入独立层级合成（测试内第二实现）逐位复现闭式。"""
    def u(k):
        return np.exp(1j * math.pi / 4.0 * (k % 8))
    b = np.array([[u(0), u(0)], [u(2), u(6)]]) / math.sqrt(2.0)

    def bd2(m):
        z = np.zeros((4, 4), dtype=complex)
        z[:2, :2] = m
        z[2:, 2:] = m
        return z

    d_lines = np.diag([u(x) for x in (0, 3, 0, 1)])  # 连线表: a1,b1,a2,b2
    p_in = np.eye(4, dtype=complex)[[0, 2, 1, 3]]  # RH 输入 = 线 (a1,a2,b1,b2)：交叉结1
    p_out = np.zeros((4, 4), dtype=complex)
    for ant, o in enumerate((0, 2, 1, 3)):  # A1←RH1上, A2←RH2上, A3←RH1下, A4←RH2下
        p_out[ant, o] = 1.0
    s_slots = (p_out @ bd2(b) @ p_in @ d_lines @ bd2(b)).T
    sigma = [s - 1 for s in (1, 4, 2, 3)]  # 连线表 beam_port_to_slot
    expect = s_slots[sigma, :]
    assert np.max(np.abs(expect - bm.butler4_s_beam_to_antenna())) <= TOL


# ─── 8. service 薄壳（JSON 信封，ok=False 不抛） ─────────────────────────────


def test_service_payload_envelope():
    from rfauto.service import butler_matrix_service as svc

    out = svc.butler_matrix_payload()
    assert out["ok"] is True
    data = out["data"]
    assert data["report"]["all_pass"] is True
    assert data["wiring_table"]["beam_port_to_slot"] == {"1": 1, "2": 4, "3": 2, "4": 3}
    # 复矩阵折叠 [re, im]：幅度 0.5 抽查
    re, im = data["s_beam_to_antenna_closed"][0][1]
    assert abs(math.hypot(re, im) - 0.5) < 1e-12
    assert json.dumps(out)  # 全载荷 JSON 可序列化


def test_service_report_envelope_and_error_path():
    from rfauto.service import butler_matrix_service as svc

    out = svc.butler_matrix_report(n_points=2001)
    assert out["ok"] is True
    assert out["data"]["all_pass"] is True
    # 非法入参 → ok=False 信封，绝不抛出
    bad = svc.butler_matrix_report(spacing_lambda=0.0)
    assert bad["ok"] is False
    assert "error" in bad
    bad2 = svc.butler_matrix_report(n_points=5)
    assert bad2["ok"] is False
