"""aurora_d W3-CORE9：CORE8 遗留收口三键单测。

doa_crb_stochastic（calc_families/doa_crb.py 原位扩展）/
schiffman_phaser + switched_network_phaser（calc_families/phase_shifter.py
原位扩展）。

裁判口径（#118 双路径：实现路线=各键闭式；独立第二路线=本文件不同
算法重算——naive N×N 全参数 Slepian-Bangs FIM/模态 S21 解缠/ABCD 数值
级联，实现前独立复算（runs/aurora_d/_core9_verify_derivation.py 轨迹）
后写死）：

- **随机 CRB**：naive N×N 全参数 FIM（θ + Q 实参数化 + σ²）逐块构造
  后 Schur 消元（不走 M×M 约简）→ CRB 对角元 rel<1e-12（ρ=0 与 ρ=0.5
  两档）；M=1 退化比值恒等式 stoch/det=1+1/(pN)（rel≤1e-12）；σ²/Q 已
  知 vs 未知不敏感（ULA m=0 约定 FIM_θσ=FIM_θq=0，两口径逐位）；闭式
  vs 精确面全域恰等（closed_vs_exact_max_rel≤1e-12）；锚 N8/T256/
  15dB/−10°=1.542380056288487e-07、比值=1.0039528470752104。
- **Schiffman**：模态 S21=−j(a+b)/(1+ab+j(a−b)) 独立算法（均匀介质
  Z0e·Z0o=Z0²、低频锚梯解缠）vs 闭式 arccos 连续支（逐象限 ≤1e-9°）；
  经典锚 θ₀=90°/B=3 → Δφ(f₀)=90° 精确；频带响应锚（ρ=3：0.5f₀→75°、
  0.75f₀→93.8143°、1.25f₀→86.1857°、1.5f₀→105°）；平坦综合锚 Δφ=120°
  → ρ*=7.535831/θ*=69.1219°+平坦峰核验>0；定 ρ 设计 roundtrip；全通
  匹配 Z0e·Z0o=Z0²。
- **开关网络**：ABCD 数值级联（[Zs/2|Yp|Zs/2]）第二路线——f₀ 处
  |S11|≈0（镜像匹配）+S21 相位=−φ roundtrip（≤1e-9）；L/C 锚
  @2GHz/50Ω（90°→7.957747nH/1.591549pF）；截止恒等式
  f_c=f₀/sin(φ/2)；镜像阻抗恒等式 Z_T(f₀)=Z0；位态级联（权重和=
  360−LSB、量化 RMS=LSB/√12、开关插损 |S21|=2Z0/(2Z0+R_on) 累加）。
- **域拒绝**：service ok=False 面（service envelope）+ 直调 ValueError。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.calc_families.doa_crb import (
    doa_crb_stochastic,
    doa_crb_ula,
    doa_crb_ula_multisource,
)
from rfauto.core.calc_families.phase_shifter import (
    schiffman_phaser,
    switched_network_phaser,
)
from rfauto.service.calculator_service import run_calculator

# ─── 独立第二路线算子（实现前复算，不同算法）────────────────────────────────


def _ula_a(theta_rad: float, n: int, d_lam: float) -> np.ndarray:
    m = np.arange(n, dtype=float)
    return np.exp(1j * (2.0 * math.pi * d_lam * math.sin(theta_rad)) * m)


def _ula_d(theta_rad: float, n: int, d_lam: float) -> np.ndarray:
    m = np.arange(n, dtype=float)
    return 1j * (2.0 * math.pi * d_lam * math.cos(theta_rad)) * m * _ula_a(
        theta_rad, n, d_lam)


def _naive_sb_crb(angles_deg: list[float], q_mat: np.ndarray, n: int,
                  t_snap: int, d_lam: float) -> np.ndarray:
    """第二路线（独立算法）：naive N×N 全参数 Slepian-Bangs FIM（θ +
    Q 实参数化 + σ²）逐块构造后一次性 Schur 消元——不走内核 M×M 约简
    （σ²=1 口径）。"""
    m_src = len(angles_deg)
    th = [math.radians(a) for a in angles_deg]
    a_mat = np.column_stack([_ula_a(t, n, d_lam) for t in th])
    d_mat = np.column_stack([_ula_d(t, n, d_lam) for t in th])
    r_mat = a_mat @ q_mat @ a_mat.conj().T + np.eye(n)
    r_inv = np.linalg.inv(r_mat)
    d_r_th = [d_mat[:, i:i + 1] @ q_mat[i:i + 1, :] @ a_mat.conj().T
              + (a_mat @ q_mat[:, i:i + 1]) @ d_mat[:, i:i + 1].conj().T
              for i in range(m_src)]
    q_params = []
    for k in range(m_src):
        e_m = np.zeros((m_src, m_src))
        e_m[k, k] = 1.0
        q_params.append(a_mat @ e_m @ a_mat.conj().T)
    for k in range(m_src):
        for l_i in range(k + 1, m_src):
            e_r = np.zeros((m_src, m_src))
            e_r[k, l_i] = 1.0
            e_r[l_i, k] = 1.0
            q_params.append(a_mat @ e_r @ a_mat.conj().T)
            e_i = np.zeros((m_src, m_src), dtype=complex)
            e_i[k, l_i] = 1.0j
            e_i[l_i, k] = -1.0j
            q_params.append(a_mat @ e_i @ a_mat.conj().T)
    nq = len(q_params)
    dim = m_src + nq + 1
    fim = np.zeros((dim, dim))
    for i in range(m_src):
        for j in range(m_src):
            fim[i, j] = t_snap * np.trace(
                r_inv @ d_r_th[i] @ r_inv @ d_r_th[j]).real
    for a_i, d_rq in enumerate(q_params):
        fim[m_src + a_i, m_src + a_i] = t_snap * np.trace(
            r_inv @ d_rq @ r_inv @ d_rq).real
        for j in range(m_src):
            v = t_snap * np.trace(r_inv @ d_r_th[j] @ r_inv @ d_rq).real
            fim[m_src + a_i, j] = v
            fim[j, m_src + a_i] = v
        for b_i in range(a_i):
            v = t_snap * np.trace(
                r_inv @ q_params[b_i] @ r_inv @ d_rq).real
            fim[m_src + a_i, m_src + b_i] = v
            fim[m_src + b_i, m_src + a_i] = v
    i_sig = m_src + nq
    for j in range(m_src):
        v = t_snap * np.trace(r_inv @ d_r_th[j]).real
        fim[i_sig, j] = v
        fim[j, i_sig] = v
    for a_i, d_rq in enumerate(q_params):
        fim[i_sig, m_src + a_i] = fim[m_src + a_i, i_sig] = (
            t_snap * np.trace(r_inv @ d_rq).real)
    fim[i_sig, i_sig] = t_snap * np.trace(r_inv @ r_inv).real
    fr = fim[np.ix_(list(range(m_src)) + list(range(m_src, dim)),
                    list(range(m_src)) + list(range(m_src, dim)))]
    f_tt = fr[:m_src, :m_src] - fr[:m_src, m_src:] @ np.linalg.solve(
        fr[m_src:, m_src:], fr[m_src:, :m_src])
    return np.diag(np.linalg.inv(f_tt))


def _schiffman_modal_phi_c_deg(theta_deg: float, rho: float) -> float:
    """第二路线（独立算法）：均匀介质模态 S21 解缠相位。

    S21=−j(a+b)/(1+ab+j(a−b))，a=(Z0/Z0e)tanθ、b=(Z0/Z0o)/tanθ（Z0=1
    归一、Z0e=√ρ、Z0o=1/√ρ）；低频锚梯（θ 自 1e-6 爬升至目标）解缠到
    连续支——与 arccos 闭式不同算法（QW-10 同链形态、本文件独立重写）。"""
    z0e = math.sqrt(rho)
    z0o = 1.0 / math.sqrt(rho)
    thetas = np.geomspace(1e-6, max(theta_deg * math.pi / 180.0, 1e-6),
                          20000)
    aa = (1.0 / z0e) * np.tan(thetas)
    bb = (1.0 / z0o) / np.tan(thetas)
    s21 = -1j * (aa + bb) / (1.0 + aa * bb + 1j * (aa - bb))
    phi = -np.unwrap(np.angle(s21))
    return float(math.degrees(phi[-1]))


def _lc_t_abcd(l_nh: float, c_pf: float, f_ghz: float, z0: float
               ) -> tuple[complex, complex]:
    """第二路线（独立算法）：LC 低通 T 节 ABCD 数值级联（[Zs/2|Yp|Zs/2]）。

    单位口径：GHz/ns/Ω 自洽（nH·rad/ns=Ω；pF·1e-3=ns/Ω）。"""
    w = 2.0 * math.pi * f_ghz
    zs = 1j * w * l_nh
    yp = 1j * w * c_pf * 1e-3
    m1 = np.array([[1.0, zs / 2.0], [0.0, 1.0]])
    m2 = np.array([[1.0, 0.0], [yp, 1.0]])
    mat = m1 @ m2 @ m1
    a_v, b_v = mat[0, 0], mat[0, 1]
    c_v, d_v = mat[1, 0], mat[1, 1]
    s21 = 2.0 / (a_v + b_v / z0 + c_v * z0 + d_v)
    s11 = (a_v + b_v / z0 - c_v * z0 - d_v) / (
        a_v + b_v / z0 + c_v * z0 + d_v)
    return s11, s21


# ─── doa_crb_stochastic ──────────────────────────────────────────────────

N_EL, T_SNAP, D_LAM = 8, 256, 0.5


def _snr_cov(snr_lin: list[float], rho: float) -> np.ndarray:
    m_src = len(snr_lin)
    r_mat = (1.0 - rho) * np.eye(m_src) + rho * np.ones((m_src, m_src))
    root = np.sqrt(np.asarray(snr_lin, dtype=float))
    return np.outer(root, root) * r_mat


class TestDoaCrbStochastic:
    def test_m1_anchor_and_ratio_identity(self):
        """M=1 锚 + 比值恒等式 stoch/det=1+1/(pN)（随机≥确定性）。"""
        r = doa_crb_stochastic(n_elements=N_EL, snapshots=T_SNAP,
                               angles_deg=[-10.0], snr_db=15.0,
                               spacing_lambda=D_LAM)
        assert r["crb_var_rad2"][0] == pytest.approx(
            1.542380056288487e-07, rel=1e-12)
        assert r["m1_stoch_over_det_ratio"] == pytest.approx(
            1.0039528470752104, rel=1e-12)
        assert r["m1_ratio_identity"] == pytest.approx(
            1.0 + 1.0 / (10.0 ** 1.5 * N_EL), rel=1e-15)
        assert r["m1_stoch_over_det_ratio"] > 1.0
        # 高 SNR 渐近相等方向
        r_hi = doa_crb_stochastic(n_elements=N_EL, snapshots=T_SNAP,
                                  angles_deg=[-10.0], snr_db=40.0,
                                  spacing_lambda=D_LAM)
        assert (r_hi["m1_stoch_over_det_ratio"]
                < r["m1_stoch_over_det_ratio"])

    def test_m1_degeneracy_vs_deterministic_key(self):
        """M=1 与确定性键的关系：crb_stoch=crb_det×(1+1/(pN)) 互证。"""
        r = doa_crb_stochastic(n_elements=N_EL, snapshots=T_SNAP,
                               angles_deg=[20.0], snr_db=12.0,
                               spacing_lambda=D_LAM)
        d = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP, snr_db=12.0,
                        spacing_lambda=D_LAM, angle_deg=20.0)
        expect = d["crb_var_rad2"] * (1.0 + 1.0
                                      / (10.0 ** 1.2 * N_EL))
        assert r["crb_var_rad2"][0] == pytest.approx(expect, rel=1e-12)

    def test_naive_sb_second_route(self):
        """第二路线：naive N×N 全参数 FIM Schur 消元 vs 内核精确面
        rel<1e-12（ρ=0 与 ρ=0.5 两档）。"""
        n, t2, d_lam = 5, 32, 0.5
        for rho in (0.0, 0.5):
            snr = [15.0, 9.0]
            q_mat = _snr_cov([10.0 ** (s / 10.0) for s in snr], rho)
            crb_ref = _naive_sb_crb([-10.0, 25.0], q_mat, n, t2, d_lam)
            m = doa_crb_stochastic(n_elements=n, snapshots=t2,
                                   angles_deg=[-10.0, 25.0], snr_db=snr,
                                   spacing_lambda=d_lam, corr_coef=rho)
            for i in range(2):
                assert m["sb_exact_crb_var_rad2"][i] == pytest.approx(
                    float(crb_ref[i]), rel=1e-12)

    def test_closed_equals_exact_everywhere(self):
        """celebrated 闭式=精确面全域恰等（Q/σ² 全消元前提，内建互证面）。"""
        for rho, snr in ((0.0, 15.0), (0.3, [10.0, 6.0]), (0.5, 12.0),
                         (0.8, [3.0, 20.0])):
            m = doa_crb_stochastic(n_elements=6, snapshots=48,
                                   angles_deg=[-15.0, 30.0], snr_db=snr,
                                   spacing_lambda=D_LAM, corr_coef=rho)
            assert m["closed_vs_exact_max_rel"] <= 1e-12
            for c, s in zip(m["crb_var_rad2"],
                            m["sb_exact_crb_var_rad2"], strict=True):
                assert c == pytest.approx(s, rel=1e-12)

    def test_m1_sigma_q_invariance(self):
        """ULA m=0 约定下 FIM_θσ=FIM_θq=0 → σ²/Q 已知与否不敏感（fp
        精度内逐位，两口径不同代码路径 1 ULP 尾差）。"""
        r = doa_crb_stochastic(n_elements=N_EL, snapshots=T_SNAP,
                               angles_deg=[-10.0], snr_db=15.0,
                               spacing_lambda=D_LAM)
        assert r["crb_var_rad2"][0] == pytest.approx(
            r["sb_exact_crb_var_rad2"][0], rel=1e-12)

    def test_fim_symmetry_and_stoch_ge_det_multisource(self):
        """FIM 实对称 + 多源随机面 ≥ 确定性面（同参 doa_crb_ula_
        multisource 对照——Stoica-Nehorai 两模型对照主题）。"""
        m = doa_crb_stochastic(n_elements=N_EL, snapshots=T_SNAP,
                               angles_deg=[-10.0, 25.0],
                               snr_db=[15.0, 9.0], spacing_lambda=D_LAM,
                               corr_coef=0.5)
        fim = np.asarray(m["fim_stoch"])
        assert fim.ndim == 2 and np.allclose(fim, fim.T, atol=1e-6)
        det = doa_crb_ula_multisource(n_elements=N_EL, snapshots=T_SNAP,
                                      angles_deg=[-10.0, 25.0],
                                      snr_db=[15.0, 9.0],
                                      spacing_lambda=D_LAM, corr_coef=0.5)
        for c_st, c_det in zip(m["crb_var_rad2"], det["crb_var_rad2"],
                               strict=True):
            assert c_st >= c_det * (1.0 - 1e-12)

    def test_anchor_values_and_service_envelope(self):
        m = doa_crb_stochastic(n_elements=N_EL, snapshots=T_SNAP,
                               angles_deg=[-10.0, 25.0],
                               snr_db=[15.0, 9.0], spacing_lambda=D_LAM,
                               corr_coef=0.5)
        assert m["crb_var_rad2"][0] == pytest.approx(
            1.6330297631077587e-07, rel=1e-12)
        assert m["crb_var_rad2"][1] == pytest.approx(
            7.767471441111438e-07, rel=1e-12)
        assert m["worst_source_index"] == 1
        params = {"n_elements": N_EL, "snapshots": T_SNAP,
                  "angles_deg": [-10.0, 10.0], "snr_db": 15.0,
                  "spacing_lambda": D_LAM, "corr_coef": 0.3}
        import json
        env = run_calculator("doa_crb_stochastic", params)
        assert env["ok"] is True
        env2 = run_calculator("doa_crb_stochastic", params)
        assert json.dumps(env, sort_keys=True) == json.dumps(
            env2, sort_keys=True)

    def test_domain_rejections(self):
        base = {"n_elements": N_EL, "snapshots": T_SNAP,
                "angles_deg": [-10.0, 10.0], "snr_db": 15.0,
                "spacing_lambda": D_LAM}
        for bad in ({"n_elements": 2}, {"angles_deg": [1.0, 1.0]},
                    {"angles_deg": [90.0, 20.0]}, {"corr_coef": 1.0},
                    {"angles_deg": [20.0], "corr_coef": 0.5},
                    {"spacing_lambda": 1.5}, {"snapshots": 0},
                    {"snr_db": [15.0]}):
            out = run_calculator("doa_crb_stochastic", {**base, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"


# ─── schiffman_phaser ────────────────────────────────────────────────────

F_SCH, ER_SCH = 10.0, 3.0


class TestSchiffmanPhaser:
    def test_classic_90deg_anchor(self):
        """经典锚：θ₀=90°/B=3（λ/4 耦合段 vs 3λ/4 参考段）→ Δφ(f₀)=90°
        精确（Schiffman 1958 主题口径）。"""
        a = schiffman_phaser(f_ghz=F_SCH, ereff=ER_SCH, rho=3.0,
                             theta0_deg=90.0)
        assert a["route"] == "analysis"
        assert a["delta_phi_f0_deg"] == pytest.approx(90.0, rel=1e-12)
        assert a["phi_c_f0_deg"] == pytest.approx(180.0, rel=1e-12)

    def test_closed_vs_modal_second_route_all_quadrants(self):
        """第二路线：模态 S21 解缠相位 vs 闭式 arccos 连续支——三档 ρ ×
        七个 θ（跨 90°/180° 象限）逐点 ≤1e-9°。"""
        for rho in (2.3, 3.0, 5.83):
            for th_deg in (20.0, 45.0, 67.5, 90.0, 110.0, 150.0, 175.0):
                a = schiffman_phaser(f_ghz=F_SCH, ereff=ER_SCH, rho=rho,
                                     theta0_deg=th_deg)
                phi_modal = _schiffman_modal_phi_c_deg(th_deg, rho)
                assert a["phi_c_f0_deg"] == pytest.approx(
                    phi_modal, abs=1e-9)

    def test_band_response_anchors(self):
        """频带响应锚（ρ=3/B=3/θ₀=90°，连续支全域）：75/93.8143/86.1857/
        105——平坦区 ±5°@0.75..1.25 f₀。"""
        a = schiffman_phaser(f_ghz=F_SCH, ereff=ER_SCH, rho=3.0,
                             theta0_deg=90.0)
        band = a["band_response_deg"]
        assert band["0.5"] == pytest.approx(75.0, rel=1e-9)
        assert band["0.75"] == pytest.approx(93.81425964946558, rel=1e-9)
        assert band["0.9"] == pytest.approx(93.68110102689738, rel=1e-9)
        assert band["1.25"] == pytest.approx(86.18574035053445, rel=1e-9)
        assert band["1.5"] == pytest.approx(105.0, rel=1e-9)
        assert a["flatness_dev_deg"] == pytest.approx(
            max(abs(v - 90.0) for v in band.values()), rel=1e-12)

    def test_flat_design_anchor_120deg(self):
        """平坦综合锚：Δφ_target=120° → ρ*=7.535831/θ*=69.1219°（双条件
        brentq）+平坦峰核验（θ*±0.5° 均低于峰值）+全通匹配。"""
        fl = schiffman_phaser(f_ghz=F_SCH, ereff=ER_SCH,
                              delta_phi_deg=120.0)
        assert fl["route"] == "design_flat"
        assert fl["rho"] == pytest.approx(7.535830750878457, rel=1e-9)
        assert fl["theta0_deg"] == pytest.approx(69.12190857543709,
                                                 rel=1e-9)
        assert fl["delta_phi_f0_deg"] == pytest.approx(120.0, rel=1e-9)
        assert fl["flatness_peak_check_deg"] > 0.0
        assert fl["z0e_ohm"] == pytest.approx(
            50.0 * math.sqrt(fl["rho"]), rel=1e-12)
        assert fl["z0o_ohm"] == pytest.approx(
            50.0 / math.sqrt(fl["rho"]), rel=1e-12)
        assert fl["allpass_match_dev"] <= 1e-9

    def test_design_from_delta_phi_roundtrip(self):
        """定 ρ 设计（上升支首解）→ 分析回代 roundtrip 逐位。"""
        d = schiffman_phaser(f_ghz=F_SCH, ereff=ER_SCH, rho=3.0,
                             delta_phi_deg=60.0)
        assert d["route"] == "design_from_delta_phi"
        assert d["theta0_deg"] == pytest.approx(34.36071546369415,
                                                rel=1e-9)
        assert 0.0 < d["theta0_deg"] <= 90.0
        a = schiffman_phaser(f_ghz=F_SCH, ereff=ER_SCH, rho=3.0,
                             theta0_deg=d["theta0_deg"])
        assert a["delta_phi_f0_deg"] == pytest.approx(60.0, rel=1e-9)
        # 物理长度联动
        assert d["coupled_len_mm"] == pytest.approx(
            d["theta0_deg"] / 360.0 * d["lambda_g_mm"], rel=1e-12)
        assert d["ref_len_mm"] == pytest.approx(
            3.0 * d["coupled_len_mm"], rel=1e-12)

    def test_service_envelope_and_domain(self):
        env = run_calculator("schiffman_phaser",
                             {"f_ghz": F_SCH, "ereff": ER_SCH, "rho": 3.0,
                              "theta0_deg": 90.0})
        assert env["ok"] is True
        import json
        env2 = run_calculator("schiffman_phaser",
                              {"f_ghz": F_SCH, "ereff": ER_SCH,
                               "rho": 3.0, "theta0_deg": 90.0})
        assert json.dumps(env, sort_keys=True) == json.dumps(
            env2, sort_keys=True)
        base_ok = {"f_ghz": F_SCH, "ereff": ER_SCH}
        for bad in ({"theta0_deg": 90.0, "delta_phi_deg": 60.0},
                    {"rho": 1.0, "theta0_deg": 90.0},
                    {"rho": 3.0, "theta0_deg": 200.0},
                    {"rho": 3.0, "delta_phi_deg": 170.0},
                    {"delta_phi_deg": 90.0},
                    {"delta_phi_deg": 300.0},
                    {"theta0_deg": 90.0}):
            out = run_calculator("schiffman_phaser", {**base_ok, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"


# ─── switched_network_phaser ─────────────────────────────────────────────

F_SW, Z0_SW = 2.0, 50.0


class TestSwitchedNetworkPhaser:
    def test_design_anchor_90deg(self):
        """单网络锚 @2GHz/50Ω：90°→L=7.957747nH/C=1.591549pF、截止
        2.828427GHz=f₀/sin45°、镜像阻抗恒等 Z_T(f₀)=Z0。"""
        s = switched_network_phaser(f_ghz=F_SW, phi_deg=90.0)
        assert s["route"] == "single_network"
        assert s["series_L_total_nH"] == pytest.approx(7.957747154594766,
                                                       rel=1e-9)
        assert s["shunt_C_pf"] == pytest.approx(1.5915494309189533,
                                                rel=1e-9)
        assert s["cutoff_ghz"] == pytest.approx(2.0 / math.sin(
            math.radians(45.0)), rel=1e-12)
        assert s["image_z0_dev"] <= 1e-9
        assert s["group_delay_ns"] == pytest.approx(
            2.0 * math.sin(math.radians(45.0)) / (2.0 * math.pi * 2.0),
            rel=1e-12)

    def test_abcd_second_route_roundtrip(self):
        """第二路线：ABCD 数值级联——f₀ 处 |S11|≈0（镜像匹配）+S21 相位
        =−φ roundtrip（多档位）。"""
        for phi_t in (22.5, 45.0, 90.0, 135.0, 170.0):
            s = switched_network_phaser(f_ghz=F_SW, phi_deg=phi_t)
            s11, s21 = _lc_t_abcd(s["series_L_total_nH"], s["shunt_C_pf"],
                                  F_SW, Z0_SW)
            assert abs(s11) <= 1e-9, phi_t
            assert abs(s21) == pytest.approx(1.0, rel=1e-9)
            phase = -math.degrees(math.atan2(s21.imag, s21.real))
            assert phase == pytest.approx(phi_t, abs=1e-9)

    def test_cutoff_identity_across_phi(self):
        """截止恒等式 f_c=f₀/sin(φ/2) 全档位（镜像阻抗实数域上限）。"""
        for phi_t in (22.5, 45.0, 90.0, 135.0):
            s = switched_network_phaser(f_ghz=F_SW, phi_deg=phi_t)
            expect = F_SW / math.sin(math.radians(phi_t) / 2.0)
            assert s["cutoff_ghz"] == pytest.approx(expect, rel=1e-12)
            assert s["cutoff_ratio_f_over_f0"] == pytest.approx(
                1.0 / math.sin(math.radians(phi_t) / 2.0), rel=1e-12)

    def test_switch_loss_cascade(self):
        """开关插损 |S21|=2Z0/(2Z0+R_on)（与 pa_arch pin_diode_limiter
        同口径）：单网络 2 只、解析恒等式。"""
        r_on = 2.0
        s = switched_network_phaser(f_ghz=F_SW, phi_deg=90.0, r_on_ohm=r_on)
        il_sw = -20.0 * math.log10(2.0 * Z0_SW / (2.0 * Z0_SW + r_on))
        assert s["switch_loss_db"] == pytest.approx(2 * il_sw, rel=1e-12)
        assert s["insertion_loss_db"] == pytest.approx(2 * il_sw, rel=1e-12)

    def test_bitfield_cascade(self):
        """N 位级联锚：4 位权重 [180,90,45,22.5]、全开 337.5=360−LSB、
        量化 RMS=LSB/√12、总插损=2N 只开关累加。"""
        r_on = 2.0
        b = switched_network_phaser(f_ghz=F_SW, n_bits=4, r_on_ohm=r_on)
        assert b["route"] == "bitfield_cascade"
        assert b["weights_deg"] == [180.0, 90.0, 45.0, 22.5]
        assert b["delta_phi_all_on_deg"] == pytest.approx(337.5, rel=1e-12)
        assert b["delta_phi_max_deg"] == pytest.approx(337.5, rel=1e-12)
        assert b["quantization_rms_deg"] == pytest.approx(
            22.5 / math.sqrt(12.0), rel=1e-12)
        il_sw = -20.0 * math.log10(2.0 * Z0_SW / (2.0 * Z0_SW + r_on))
        assert b["insertion_loss_db"] == pytest.approx(8 * il_sw, rel=1e-12)
        assert len(b["bits"]) == 4
        # MSB=180° 单节不可实现（L→∞）——如实 None+realizable=False
        assert b["bits"][0]["realizable_single_cell"] is False
        assert b["bits"][0]["series_L_total_nH"] is None
        # 其余位可实现且 L 随位权重递减单调（MSB→LSB：90/45/22.5 → L 降序）
        sub = b["bits"][1:]
        l_vals = [c["series_L_total_nH"] for c in sub]
        assert l_vals == sorted(l_vals, reverse=True)
        for c in b["bits"]:
            assert c["cutoff_ghz"] == pytest.approx(
                F_SW / math.sin(math.radians(c["phi_deg"]) / 2.0), rel=1e-12)

    def test_22p5deg_anchor(self):
        """22.5° 位锚 @2GHz/50Ω：L=1.582894nH/C=0.609060pF（复算轨迹）。"""
        s = switched_network_phaser(f_ghz=F_SW, phi_deg=22.5)
        assert s["series_L_total_nH"] == pytest.approx(1.582894, rel=1e-6)
        assert s["shunt_C_pf"] == pytest.approx(0.609060, rel=1e-6)

    def test_service_envelope_and_domain(self):
        env = run_calculator("switched_network_phaser",
                             {"f_ghz": F_SW, "phi_deg": 90.0,
                              "r_on_ohm": 2.0})
        assert env["ok"] is True
        import json
        env2 = run_calculator("switched_network_phaser",
                              {"f_ghz": F_SW, "phi_deg": 90.0,
                               "r_on_ohm": 2.0})
        assert json.dumps(env, sort_keys=True) == json.dumps(
            env2, sort_keys=True)
        for bad in ({"phi_deg": 0.0}, {"phi_deg": 180.0},
                    {"phi_deg": 45.0, "n_bits": 4}, {},
                    {"n_bits": 0}, {"n_bits": 9}, {"n_bits": 2.5},
                    {"phi_deg": 45.0, "r_on_ohm": -1.0}):
            out = run_calculator("switched_network_phaser",
                                 {"f_ghz": F_SW, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"
