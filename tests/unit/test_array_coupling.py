"""EC-24 单元胞互耦→阵列级传播管线回归钉（core+service+2x2 回放）。

覆盖面：
- core.array_coupling 纯函数：指数/表值互耦模型、任意几何耦合矩阵合成
  （互易对称）、一阶多重散射嵌入方向图（零耦极限≡孤立元×AF 恒等）、
  指数模型拟合（合成已知量回收钉——#118：裁判=回收残差，非自证）；
- service.array_coupling_service：JSON 进出信封（ok/error）、扫 d×角表；
- 2x2 回放（fixture=仓内归档实测产物提取（原目录公开分发视图不随附），provenance 在
  fixture 内）：拟合→重建矩阵→Γ_act/嵌入方向图传播链对拍（同单元基，
  无口径风险）；绝对 model-vs-measured 面报告参考（theta=180 读出口径
  注记，不进硬门——J4b 报告门同口径）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.array_coupling import (
    coupled_array_pattern,
    coupling_matrix_from_positions,
    effective_excitations,
    exponential_coupling,
    fit_exponential_coupling,
    tabulated_coupling,
)
from rfauto.core.array_scan import active_reflection

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "ec24_eep2x2_f0.json"


# ── core：模型与矩阵合成 ────────────────────────────────────────────────────

def test_exponential_coupling_shape_and_validation() -> None:
    d = np.array([0.01, 0.02, 0.05])
    c = exponential_coupling(d, freq_hz=5.8e9, c0=0.3, decay_len_m=0.03,
                             eps_eff_phase=2.85)
    assert c.shape == d.shape
    assert np.all(np.abs(c) <= 0.3 + 1e-15)
    assert np.all(np.diff(np.abs(c)) < 0.0)          # 单调衰减
    with pytest.raises(ValueError, match="c0"):
        exponential_coupling(d, freq_hz=5.8e9, c0=1.0, decay_len_m=0.03,
                             eps_eff_phase=2.85)
    with pytest.raises(ValueError, match="decay_len_m"):
        exponential_coupling(d, freq_hz=5.8e9, c0=0.3, decay_len_m=-1.0,
                             eps_eff_phase=2.85)
    with pytest.raises(ValueError, match="eps_eff_phase"):
        exponential_coupling(d, freq_hz=5.8e9, c0=0.3, decay_len_m=0.03,
                             eps_eff_phase=0.5)


def test_tabulated_coupling_interp_and_clamp() -> None:
    d = np.array([0.0, 0.015, 0.02, 0.08])
    mag, ph = tabulated_coupling(
        d, d_samples_m=[0.01, 0.02, 0.05], mag_samples=[0.1, 0.05, 0.01],
        phase_deg_samples=[0.0, -90.0, -180.0])
    assert mag[1] == pytest.approx(0.075)            # 线性内插（中点）
    assert mag[0] == pytest.approx(0.1)              # 端点截断（外推禁）
    assert mag[3] == pytest.approx(0.01)
    assert ph[2] == pytest.approx(np.deg2rad(-90.0))  # 恰落样本点
    with pytest.raises(ValueError, match="升序"):
        tabulated_coupling(d, d_samples_m=[0.02, 0.01], mag_samples=[1, 1],
                           phase_deg_samples=[0, 0])


def test_coupling_matrix_reciprocal_symmetric() -> None:
    pos = np.array([[0, 0], [0.025, 0], [0, 0.025], [0.025, 0.025]])
    s = coupling_matrix_from_positions(
        pos, lambda d: exponential_coupling(
            d, freq_hz=5.8e9, c0=0.2, decay_len_m=0.03, eps_eff_phase=2.85),
        s11_diag=complex(-0.1, 0.0))
    assert s.shape == (4, 4)
    assert np.allclose(s, s.T)                        # 互易对称（构造性）
    assert np.allclose(np.diag(s), -0.1)
    # 距离档两档：邻位/对角
    assert s[0, 1] == pytest.approx(s[0, 2], abs=1e-15)
    assert s[0, 3] != pytest.approx(s[0, 1], rel=1e-3)


# ── core：一阶嵌入方向图（零耦恒等+耦合分离）────────────────────────────────

def _grid():
    th = np.arange(0.0, 180.0, 10.0)
    ph = np.arange(0.0, 360.0, 10.0)
    et = np.outer(np.cos(np.radians(th)) ** 2, np.ones_like(ph))
    return th, ph, et, np.zeros((th.size, ph.size))


def test_coupled_pattern_zero_coupling_identity() -> None:
    th, ph, et, ep = _grid()
    pos = np.array([[0, 0], [0.03, 0], [0, 0.03], [0.03, 0.03]])
    a = np.ones(4, dtype=complex)
    f_none = coupled_array_pattern(
        pos, a, elem_pattern_theta=et, elem_pattern_phi=ep,
        theta_deg=th, phi_deg=ph, freq_hz=5.8e9, s_matrix=None)
    f_zero = coupled_array_pattern(
        pos, a, elem_pattern_theta=et, elem_pattern_phi=ep,
        theta_deg=th, phi_deg=ph, freq_hz=5.8e9,
        s_matrix=np.zeros((4, 4)))
    assert np.array_equal(f_none[0], f_zero[0])
    assert np.array_equal(f_none[1], f_zero[1])


def test_coupled_pattern_effective_excitation_face() -> None:
    """耦合方向图≡孤立元×a_eff 激励的 AF（a_eff=(I+S)a 恒等面）。"""
    th, ph, et, ep = _grid()
    pos = np.array([[0, 0], [0.025, 0], [0, 0.025], [0.025, 0.025]])
    a = np.array([1.0, 1.0, 1.0, 1.0], dtype=complex)
    s = coupling_matrix_from_positions(
        pos, lambda d: exponential_coupling(
            d, freq_hz=5.8e9, c0=0.3, decay_len_m=0.03, eps_eff_phase=2.85),
        s11_diag=complex(-0.2, 0.05))
    f_c, _ = coupled_array_pattern(
        pos, a, elem_pattern_theta=et, elem_pattern_phi=ep,
        theta_deg=th, phi_deg=ph, freq_hz=5.8e9, s_matrix=s)
    a_eff = effective_excitations(a, s)
    f_ref, _ = coupled_array_pattern(
        pos, a_eff, elem_pattern_theta=et, elem_pattern_phi=ep,
        theta_deg=th, phi_deg=ph, freq_hz=5.8e9, s_matrix=np.zeros((4, 4)))
    assert np.allclose(f_c[0], f_ref[0], atol=1e-12)


# ── core：拟合回收钉（合成已知量 → 参数回收，#118）──────────────────────────

def test_fit_exponential_recovers_synthetic_truth() -> None:
    f = 5.8e9
    c0_true, xi_true, ee_true = 0.30, 0.032, 2.85
    pos = np.array([[0, 0], [0.0250172, 0], [0, 0.0250172],
                    [0.0250172, 0.0250172]])

    def model(d):
        return exponential_coupling(d, freq_hz=f, c0=c0_true,
                                    decay_len_m=xi_true,
                                    eps_eff_phase=ee_true)

    s = coupling_matrix_from_positions(pos, model, s11_diag=complex(-0.2, 0))
    fit = fit_exponential_coupling(s, pos, freq_hz=f)
    assert fit.c0 == pytest.approx(c0_true, rel=1e-9)
    assert fit.decay_len_m == pytest.approx(xi_true, rel=1e-9)
    k_true = 2.0 * np.pi * f * np.sqrt(ee_true) / 299792458.0
    assert fit.k_eff_rad_per_m == pytest.approx(k_true, rel=1e-5)
    assert fit.eps_eff_implied == pytest.approx(ee_true, rel=1e-5)
    assert fit.mag_resid_max_abs < 1e-12
    assert fit.phase_resid_max_rad < 1e-5
    assert not fit.degenerate
    assert len(fit.distances_m) == 2                  # 邻位/对角两档


def test_fit_rejects_degenerate_diagonal_matrix() -> None:
    pos = np.array([[0, 0], [0.03, 0]])
    s = np.diag([-0.2, -0.2]).astype(complex)
    with pytest.raises(ValueError, match="近零幅度"):
        fit_exponential_coupling(s, pos, freq_hz=5.8e9)


# ── service：JSON 信封 ─────────────────────────────────────────────────────

def test_service_pipeline_ok_and_error_envelope() -> None:
    from rfauto.service.array_coupling_service import unit_cell_coupling_pipeline

    out = unit_cell_coupling_pipeline({
        "f0_ghz": 5.8,
        "coupling": {"kind": "exponential", "c0": 0.15,
                     "decay_len_mm": 30.0, "eps_eff_phase": 2.85},
    })
    assert out["ok"] is True
    r = out["result"]
    assert r["n"] == 4 and r["tier"] == "coupled_model"
    assert len(r["s_matrix"]) == 16
    assert r["coupling_max_db"] < -20.0               # c0=0.15/ξ=30mm 带内
    assert r["deviation_report"]["n_points"] > 0
    # error 信封：AU-2 收敛语义（ok=False + errors 列表）
    bad = unit_cell_coupling_pipeline({"f0_ghz": -1.0})
    assert bad["ok"] is False and isinstance(bad["errors"], list)
    bad2 = unit_cell_coupling_pipeline({"f0_ghz": 5.8,
                                        "coupling": {"kind": "bogus"}})
    assert bad2["ok"] is False


def test_service_coupling_sweep_table() -> None:
    from rfauto.service.array_coupling_service import coupling_sweep

    out = coupling_sweep({"f0_ghz": 5.8,
                          "spacings_mm": [20.0, 30.0],
                          "scan_deg_list": [0.0, 30.0]})
    assert out["ok"] is True
    rows = out["result"]["rows"]
    assert len(rows) == 4
    by_key = {(r["spacing_mm"], r["scan_deg"]): r for r in rows}
    # 20mm=0.387λ <0.5λ → invalid_fast_tier；30mm=0.58λ 侧射无栅瓣放行
    assert by_key[(20.0, 0.0)]["invalid_fast_tier"] is True
    assert by_key[(30.0, 0.0)]["tier"] == "fast"
    # 互耦随间距衰减（同角度行）
    assert by_key[(30.0, 0.0)]["coupling_max_db"] < by_key[(20.0, 0.0)][
        "coupling_max_db"]
    empty = coupling_sweep({"f0_ghz": 5.8, "spacings_mm": [],
                            "scan_deg_list": [0.0]})
    assert empty["ok"] is False


def test_service_fit_from_s_matrix_flat_and_nested() -> None:
    """P1-1 修复钉：公开服务入口直测（此前零行为测试）。

    展平+嵌套两形态等价受理（嵌套=逐元 [re,im] 的 (N,N,2)），合成已知量
    回收（#118：裁判=回收残差非自证），非法输入 error 信封不炸。
    """
    from rfauto.service.array_coupling_service import fit_coupling_model_from_s_matrix

    f = 5.8e9
    pos = np.array([[0, 0], [0.0250172, 0], [0, 0.0250172],
                    [0.0250172, 0.0250172]])
    s = coupling_matrix_from_positions(
        pos, lambda d: exponential_coupling(
            d, freq_hz=f, c0=0.30, decay_len_m=0.032, eps_eff_phase=2.85),
        s11_diag=complex(-0.2, 0.0))
    pos_mm = (pos * 1e3).tolist()
    # 展平形态（既有契约，行为不变）
    out = fit_coupling_model_from_s_matrix({
        "s_matrix": [[float(v.real), float(v.imag)] for v in s.ravel()],
        "positions_mm": pos_mm, "f0_ghz": 5.8})
    assert out["ok"] is True
    assert out["result"]["c0"] == pytest.approx(0.30, rel=1e-8)
    assert out["result"]["decay_len_mm"] == pytest.approx(32.0, rel=1e-8)
    assert out["result"]["degenerate"] is False
    # 嵌套形态（docstring 第二承诺）：等价受理且逐键同结果
    nested = [[[float(v.real), float(v.imag)] for v in row] for row in s]
    out_n = fit_coupling_model_from_s_matrix({
        "s_matrix": nested, "positions_mm": pos_mm, "f0_ghz": 5.8})
    assert out_n == out
    # 非法输入：非完全平方长度 / 嵌套形态畸形 → error 信封
    bad = fit_coupling_model_from_s_matrix({
        "s_matrix": [[0.1, 0.0], [0.05, 0.01], [0.02, 0.0]],
        "positions_mm": [[0.0, 0.0], [25.0, 0.0]], "f0_ghz": 5.8})
    assert bad["ok"] is False and bad["errors"]
    bad2 = fit_coupling_model_from_s_matrix({
        "s_matrix": [[[0.1, 0.0], [0.05, 0.01]]],
        "positions_mm": [[0.0, 0.0], [25.0, 0.0]], "f0_ghz": 5.8})
    assert bad2["ok"] is False and "嵌套" in bad2["errors"][0]


def test_service_coupling_sweep_nonfinite_gamma_annotated(monkeypatch) -> None:
    """P2-1 修复钉：gamma 非有限（[None,None] 对）→ 行内 max 置 None+注记，
    不依赖 TypeError 兜底报错（monkeypatch 钉 pipeline 产非有限 gamma）。"""
    from rfauto.service import array_coupling_service as svc

    fake = {
        "gamma_act": [[0.2, 0.1], [None, None]],
        "coupling_max_db": -20.0,
        "tier_gate": {"tier": "fast", "invalid_fast_tier": False,
                      "checks": {"grating_lobe_free": {"lobes": 0}}},
    }
    monkeypatch.setattr(svc, "unit_cell_coupling_pipeline",
                        lambda _req: {"ok": True, "result": fake})
    out = svc.coupling_sweep({"f0_ghz": 5.8, "spacings_mm": [20.0],
                              "scan_deg_list": [0.0]})
    assert out["ok"] is True
    row = out["result"]["rows"][0]
    assert row["gamma_act_max_abs"] is None
    assert "gamma_note" in row and "None" in row["gamma_note"]


def test_service_coupling_sweep_healthy_rows_stay_finite() -> None:
    """P2-1 健康路径回归：真实 pipeline 下 max 为正有限 float 且无注记键
    （行 schema 对健康档保持不变）。"""
    from rfauto.service.array_coupling_service import coupling_sweep

    out = coupling_sweep({"f0_ghz": 5.8, "spacings_mm": [30.0],
                          "scan_deg_list": [0.0]})
    assert out["ok"] is True
    row = out["result"]["rows"][0]
    assert isinstance(row["gamma_act_max_abs"], float)
    assert row["gamma_act_max_abs"] > 0.0
    assert "gamma_note" not in row


# ── 2x2 回放（fixture=仓内归档实测产物提取）─────────────────────────

@pytest.fixture(scope="module")
def replay():
    if not _FIXTURE.exists():
        pytest.skip("EC-24 回放 fixture 不在树（tests/fixtures/）")
    fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    n = 4
    s = np.array([complex(x, y) for x, y in fx["s_matrix_f0"]],
                 dtype=complex).reshape(n, n)
    pos = np.asarray(fx["positions_mm"], dtype=float) * 1e-3
    g = fx["measured_grid"]
    th = np.asarray(g["theta_deg"], dtype=float)
    ph = np.asarray(g["phi_deg"], dtype=float)
    f_meas = np.array([complex(x, y) for x, y in g["F_meas"]],
                      dtype=complex).reshape(th.size, ph.size)
    return fx, s, pos, th, ph, f_meas


def test_replay_measured_s_reciprocity(replay) -> None:
    """实测装配 S 互易性数据哨（|S_nm−S_mn| 级）。"""
    _, s, *_ = replay
    asym = np.abs(s - s.T)[~np.eye(4, dtype=bool)]
    assert float(asym.max()) < 1e-3


def test_replay_fit_rebuild_matrix_and_gamma(replay) -> None:
    """拟合→重建矩阵→Γ_act 传播对拍（模型 S vs 实测 S，同激励）。

    模型局限如实钉（2026-10-18 实测 2x2 回放发现，#122 不凑）：
    (a) 各向同性指数幅度模型在 E/H 平面方向分裂（|S12|=−20.36 vs
        |S13|=−20.75dB，同距异向 0.39dB）上残差 0.19（S 绝对单位）；
    (b) 纯 −k_eff·d 相位斜率模型对贴片对互耦**不成立**（同距 25.02mm
        四对相位 −2.55…+1.84 rad 散布 4.4rad——近场反应性耦合法向
        依赖，非单一导波斜率；相干度拟合残差 ~3.1rad 如实报告）。
    方向感知模型属 followUp；本门只钉传播机器对实测数据的容差。
    """
    fx, s_meas, pos, *_ = replay
    f0 = float(fx["f0_ghz"])
    fit = fit_exponential_coupling(s_meas, pos, freq_hz=f0 * 1e9)
    assert not fit.degenerate                          # 两档距离
    assert 0.0 < fit.c0 < 1.0                          # 物理幅度域
    # (a) 各向异性实证钉：同距 x/y 邻位对幅度分裂 >0.2dB
    mag_db = 20.0 * np.log10(np.abs(s_meas))
    assert mag_db[0, 1] - mag_db[0, 2] > 0.2
    # 相位模型局限钉：折叠主值残差 ≤π（ folding sanity，非拟合质量）
    assert fit.phase_resid_max_rad <= np.pi + 1e-9
    # 重建矩阵（对角=实测孤立反射，非对角=拟合模型）
    def model(d):
        return exponential_coupling(
            d, freq_hz=f0 * 1e9, c0=fit.c0,
            decay_len_m=fit.decay_len_m,
            eps_eff_phase=max(fit.eps_eff_implied, 1.0 + 1e-9))

    s_model = coupling_matrix_from_positions(
        pos, model, s11_diag=complex(np.mean(np.diag(s_meas))))
    off = ~np.eye(4, dtype=bool)
    assert float(np.max(np.abs(s_model - s_meas)[off])) < 0.25
    a = np.asarray(fx["excitations"], dtype=complex)
    a = a[:, 0] + 1j * a[:, 1]
    g_meas = active_reflection(s_meas, a)
    g_model = active_reflection(s_model, a)
    assert float(np.max(np.abs(g_model - g_meas))) < 0.3


def test_replay_propagation_chain_same_element_basis(replay) -> None:
    """端到端传播链（同单元基）：F(实测 S) vs F(重建 S) 偏差逐格。"""
    fx, s_meas, pos, th, ph, _ = replay
    f0 = float(fx["f0_ghz"])
    fit = fit_exponential_coupling(s_meas, pos, freq_hz=f0 * 1e9)

    def model(d):
        return exponential_coupling(
            d, freq_hz=f0 * 1e9, c0=fit.c0,
            decay_len_m=fit.decay_len_m,
            eps_eff_phase=max(fit.eps_eff_implied, 1.0 + 1e-9))

    s_model = coupling_matrix_from_positions(
        pos, model, s11_diag=complex(np.mean(np.diag(s_meas))))
    a = np.asarray(fx["excitations"], dtype=complex)
    a = a[:, 0] + 1j * a[:, 1]
    elem = fx["elem"]
    from rfauto.core.array_synthesis import patch_element_field

    thg = th[:, None] * np.ones((1, ph.size))
    phg = ph[None, :] * np.ones((th.size, 1))
    upper = thg <= 90.0 + 1e-9
    th_eval = np.where(upper, thg, 0.0)
    et = np.where(upper, np.asarray(patch_element_field(
        th_eval, phg, len_mm=float(elem["len_mm"]),
        width_mm=float(elem["width_mm"]), freq_ghz=f0, axis="y",
        component="theta"), dtype=float), 0.0)
    ep = np.where(upper, np.asarray(patch_element_field(
        th_eval, phg, len_mm=float(elem["len_mm"]),
        width_mm=float(elem["width_mm"]), freq_ghz=f0, axis="y",
        component="phi"), dtype=float), 0.0)
    f_meas_s, _ = coupled_array_pattern(
        pos, a, elem_pattern_theta=et, elem_pattern_phi=ep,
        theta_deg=th, phi_deg=ph, freq_hz=f0 * 1e9, s_matrix=s_meas)
    f_model_s, _ = coupled_array_pattern(
        pos, a, elem_pattern_theta=et, elem_pattern_phi=ep,
        theta_deg=th, phi_deg=ph, freq_hz=f0 * 1e9, s_matrix=s_model)
    db_meas = 20.0 * np.log10(np.maximum(np.abs(f_meas_s), 1e-300))
    db_model = 20.0 * np.log10(np.maximum(np.abs(f_model_s), 1e-300))
    # #370 深谷教训：dB 域偏差门必须带地板（深零点小矩阵差即大 dB 摆），
    # 统计域=上半球 ∩ 峰值下 30dB（J4b 地板同型）
    mask = upper & (db_meas > db_meas.max() - 30.0)
    assert int(np.count_nonzero(mask)) > 100
    dev = np.abs(db_model - db_meas)
    # 传播面同单元基（只差拟合矩阵残差——各向异性/相位局限注记见
    # test_replay_fit_rebuild_matrix_and_gamma）：上地板域 ≤3dB
    assert float(dev[mask].max()) < 3.0


def test_replay_fixture_provenance_and_structure(replay) -> None:
    """fixture 哨兵：provenance/sha/网格结构/实测主瓣方向记录一致。

    绝对 model-vs-measured 方向图对拍**不设测试门**（如实账）：实测主瓣
    在 theta=180（旋转装配 -z 读出口径）而闭式元域守卫在 theta<=90——
    两口径无重叠主瓣域，绝对对拍需镜像约定核实（followUp），结论记
    判读报告归档 §三。传播链验证由同单元基两钉承担。
    """
    fx, s_meas, _pos, th, ph, f_meas = replay
    prov = fx["provenance"]
    assert prov["source_dir"] == "仓内归档/eep_2x2"
    assert len(prov["source_sha256"]) == 4
    assert all(len(v) == 64 for v in prov["source_sha256"].values())
    assert float(fx["f0_ghz"]) == 5.8
    assert fx["f0_index"] == 200
    assert th.size == 19 and ph.size == 37              # ::2 精简网格
    assert f_meas.shape == (th.size, ph.size)
    # 实测主瓣方向记录（旋转装配 -z 读出）——演进哨：换口径须改 fixture
    pk = int(np.argmax(np.abs(f_meas)))
    assert th[pk // ph.size] == pytest.approx(180.0)
    assert abs(float(np.mean(np.diag(s_meas)))) < 1.0    # 数据合理域
