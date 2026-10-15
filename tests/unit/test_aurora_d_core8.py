"""aurora_d W3-CORE8：CORE6 遗留续作+λg 抽键四键单测。

doa_crb_ula_multisource（calc_families/doa_crb.py 原位扩展）/
reflective_phaser（calc_families/phase_shifter.py 原位扩展）/
multiplexer_channel_prototype（calc_families/multiplexer.py 原位扩展）/
waveguide_lambda_g（calc_families/waveguide_iris.py 原位扩展）。

裁判口径（#118 双路径：实现路线=各键闭式；独立第二路线=本文件不同
算法重算——全参数 FIM Schur 消元/T_n 多项式递推/整数阶扫描/阻抗式
数值角/λg kz 形态，实现前独立复算（runs/aurora_d/
_core8_verify_derivation.py 轨迹）后写死）：

- **多源 CRB**：M=1 退化=doa_crb_ula **逐位一致**（== 回归钉，同
  helper 同算子序）；M=2 全参数 FIM（θ+Re/Im s 逐快拍 nuisance）数值
  Schur 消元第二路线（不走投影公式）→ CRB 对角元 rel<1e-12；ρ=0 FIM
  非对角**恒零**（⊙P̄ᵀ 对角零化，逐位 ==0.0）+ 源解耦；全 A 子空间
  投影子空间罚 vs 单源闭式 1.0054@N8（未知波形干扰代价）；对称对 ρ
  单调（0→0.5→0.9 CRB 递增）；ρ=0.5 FIM 非对角非零+PD 特征值全正。
- **反射式**：Γ 阻抗式数值角第二路线（(r+jx−1)/(r+jx+1) 直算取角）
  vs 闭式 φ=180°−2arctan(x)（≤1e-12）；无耗 |Γ|=1 机器精度；设计
  90°→x=±tan(22.5°)=±0.414214、φ 态 135/225、180° 位 x=±1 双有限态；
  design→analysis roundtrip；Δφ=2(arctan x1−arctan x2) 恒等式；变容
  管 x=−10³/(2πfC·Z0) 换算；损耗 r=0.05/x=1 → |Γ|=0.9512492568368084、
  Q=|x|/r=20。
- **阶数原型**：Ω 通带边缘=±1 精确（几何中心变换定义域恒等式）；
  闭式阶数 vs 整数扫描最小阶（不同算法）；Chebyshev cosh 闭式 vs T_n
  递推第二路线；锚 N=3（Chebyshev 0.5dB/Ωs=4.52：raw=2.9006395901696、
  A(N)=41.8891832494≥40>A(N−1)=22.8975187980）与 Butterworth N=4
  （raw=3.0527567578384）；g 值教科书锚（1.5963/1.0967 与 0.7654/
  1.8478）+ Butterworth N≤5 与 core/diplexer_compose 双源逐位互证 +
  Chebyshev g 与 core/matching 单源同链。
- **λg**：三形态互证（fc/f 形态=λ0/2a 形态（slot_array 内嵌式）=
  kz=√(k0²−(π/a)²) 反解形态，rel≤1e-12）；WR90@10GHz 锚 fc=
  6.557140376202975/λg=39.7071192111121/β=158.23825631301972 rad/m；
  vp/c·vg/c=1 恒等式；fc 标度（f→2f λg 收敛 λ0）；λc=2a 恰值。
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

from rfauto.core.calc_families.doa_crb import doa_crb_ula, doa_crb_ula_multisource
from rfauto.core.calc_families.multiplexer import (
    multiplexer_channel_plan,
    multiplexer_channel_prototype,
)
from rfauto.core.calc_families.phase_shifter import reflective_phaser
from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.core.calc_families.waveguide_iris import waveguide_lambda_g
from rfauto.core.diplexer_compose import butterworth_g_values
from rfauto.service.calculator_service import run_calculator

# ─── 独立第二路线算子（实现前复算，不同算法）────────────────────────────────


def _ula_a(theta_rad: float, n: int, d_lam: float) -> np.ndarray:
    m = np.arange(n, dtype=float)
    return np.exp(1j * (2.0 * math.pi * d_lam * math.sin(theta_rad)) * m)


def _ula_d(theta_rad: float, n: int, d_lam: float) -> np.ndarray:
    m = np.arange(n, dtype=float)
    return 1j * (2.0 * math.pi * d_lam * math.cos(theta_rad)) * m * _ula_a(
        theta_rad, n, d_lam)


def _schur_crb(angles_deg: list[float], signal: np.ndarray, n: int,
               d_lam: float) -> np.ndarray:
    """第二路线（独立算法）：全参数 FIM（θ M 维 + Re/Im s 逐快拍 nuisance
    2TM 维）逐块构造后 Schur 消元——不走 DᴴP⊥D 投影公式（σ²=1 口径，
    signal 样本协方差须恰=pbar）。"""
    m_src = len(angles_deg)
    t_snap = signal.shape[1]
    th = [math.radians(a) for a in angles_deg]
    a_vecs = [_ula_a(t, n, d_lam) for t in th]
    d_vecs = [_ula_d(t, n, d_lam) for t in th]
    dim = m_src + 2 * m_src * t_snap
    fim = np.zeros((dim, dim))

    def s_idx(i: int, t: int, part: int) -> int:
        return m_src + 2 * t * m_src + 2 * i + part

    for i in range(m_src):
        for j in range(m_src):
            acc = 0.0
            for t in range(t_snap):
                v = (d_vecs[i] * signal[i, t]).conj() @ (
                    d_vecs[j] * signal[j, t])
                acc += v.real
            fim[i, j] = 2.0 * acc
    for i in range(m_src):
        for t in range(t_snap):
            for j in range(m_src):
                g1 = (d_vecs[i] * signal[i, t]).conj() @ a_vecs[j]
                g2 = (d_vecs[i] * signal[i, t]).conj() @ (1j * a_vecs[j])
                fim[i, s_idx(j, t, 0)] = 2.0 * g1.real
                fim[s_idx(j, t, 0), i] = 2.0 * g1.real
                fim[i, s_idx(j, t, 1)] = 2.0 * g2.real
                fim[s_idx(j, t, 1), i] = 2.0 * g2.real
                for k in range(m_src):
                    aa = a_vecs[j].conj() @ a_vecs[k]
                    fim[s_idx(j, t, 0), s_idx(k, t, 0)] = 2.0 * aa.real
                    fim[s_idx(j, t, 0), s_idx(k, t, 1)] = -2.0 * aa.imag
                    fim[s_idx(j, t, 1), s_idx(k, t, 0)] = 2.0 * aa.imag
                    fim[s_idx(j, t, 1), s_idx(k, t, 1)] = 2.0 * aa.real
    f_tt = fim[:m_src, :m_src]
    f_ts = fim[:m_src, m_src:]
    f_ss = fim[m_src:, m_src:]
    schur = f_tt - f_ts @ np.linalg.solve(f_ss, f_ts.T)
    return np.diag(np.linalg.inv(schur))


def _atten_cheb_poly(n: int, om: float, eps2: float) -> float:
    """Chebyshev 抑制第二路线：T_n 三项递推（不用 cosh 恒等式）。"""
    t0, t1 = 1.0, om
    for _ in range(n - 1):
        t0, t1 = t1, 2.0 * om * t1 - t0
    return 10.0 * math.log10(1.0 + eps2 * t1 * t1)


def _scan_min_order(atten_fn, om_s: float, a_req: float, cap: int = 64
                    ) -> int:
    """最小阶整数扫描（不同算法：不消费闭式阶数公式）。"""
    n_ord = 1
    while atten_fn(n_ord, om_s) < a_req and n_ord < cap:
        n_ord += 1
    return n_ord


# ─── doa_crb_ula_multisource ─────────────────────────────────────────────

N_EL, T_SNAP, D_LAM = 8, 256, 0.5


class TestDoaCrbUlaMultisource:
    def test_m1_bit_exact_degeneracy(self):
        """M=1 退化=doa_crb_ula 逐位一致（== 回归钉：同 helper 同算子序）。"""
        for ang in (0.0, 20.0, -45.0):
            single = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP,
                                 snr_db=15.0, spacing_lambda=D_LAM,
                                 angle_deg=ang)
            multi = doa_crb_ula_multisource(
                n_elements=N_EL, snapshots=T_SNAP, angles_deg=[ang],
                snr_db=15.0, spacing_lambda=D_LAM)
            assert multi["crb_var_rad2"][0] == single["crb_var_rad2"]
            assert multi["crb_std_deg"][0] == single["crb_std_deg"]
            assert multi["n_sources"] == 1

    def test_schur_second_route(self):
        """第二路线：全参数 FIM（θ+Re/Im s）数值 Schur 消元（不走投影
        公式）→ CRB 对角元 rel<1e-12（ρ=0 与 ρ=0.5 两档）。"""
        n, t2 = 4, 4
        v_mat = np.array([[1.0, 1.0, 1.0, 1.0],
                          [1.0, 1.0, -1.0, -1.0]]) / 2.0  # 行正交归一
        for rho in (0.0, 0.5):
            snr = [15.0, 9.0]
            p_lin = [10.0 ** (s / 10.0) for s in snr]
            r_mat = ((1.0 - rho) * np.eye(2) + rho * np.ones((2, 2)))
            pbar = np.outer(np.sqrt(p_lin), np.sqrt(p_lin)) * r_mat
            l_mat = np.linalg.cholesky(pbar)
            signal = math.sqrt(t2) * (l_mat @ v_mat)  # (1/T)SSᴴ=pbar 精确
            crb_ref = _schur_crb([-10.0, 25.0], signal, n, D_LAM)
            m = doa_crb_ula_multisource(
                n_elements=n, snapshots=t2, angles_deg=[-10.0, 25.0],
                snr_db=snr, spacing_lambda=D_LAM, corr_coef=rho)
            for i in range(2):
                assert m["crb_var_rad2"][i] == pytest.approx(
                    float(crb_ref[i]), rel=1e-12)

    def test_rho0_diagonal_decoupling(self):
        """ρ=0 → FIM 非对角恒零（逐位 ==0.0，⊙P̄ᵀ 对角零化）。"""
        m = doa_crb_ula_multisource(
            n_elements=N_EL, snapshots=T_SNAP, angles_deg=[-10.0, 25.0],
            snr_db=[15.0, 9.0], spacing_lambda=D_LAM, corr_coef=0.0)
        assert m["fim_matrix"][0][1] == 0.0
        assert m["fim_matrix"][1][0] == 0.0
        # 解耦对角=1/(2T·p_i·Re[G_ii])（uncoupled 字段同式恒等）
        for i, s_db in enumerate((15.0, 9.0)):
            p_lin = 10.0 ** (s_db / 10.0)
            expect = 1.0 / (2.0 * T_SNAP * p_lin
                            * m["fim_matrix"][i][i] / (2.0 * T_SNAP * p_lin))
            assert m["crb_var_rad2"][i] == pytest.approx(
                1.0 / m["fim_matrix"][i][i], rel=1e-12)
            assert expect == pytest.approx(m["crb_var_rad2"][i], rel=1e-12)

    def test_subspace_penalty_vs_single_source(self):
        """全 A 投影子空间罚：多源 ρ=0 各源 CRB ≥ 单源闭式（实测罚因子
        1.00538@N8 双源——未知波形干扰的子空间代价；M=1 恰=1）。"""
        m = doa_crb_ula_multisource(
            n_elements=N_EL, snapshots=T_SNAP, angles_deg=[-10.0, 25.0],
            snr_db=[15.0, 9.0], spacing_lambda=D_LAM, corr_coef=0.0)
        for i, ang in enumerate((-10.0, 25.0)):
            single = doa_crb_ula(n_elements=N_EL, snapshots=T_SNAP,
                                 snr_db=m["snr_db"][i],
                                 spacing_lambda=D_LAM, angle_deg=ang)
            penalty = m["crb_var_rad2"][i] / single["crb_var_rad2"]
            assert penalty == pytest.approx(1.005383487, rel=1e-6)
            assert penalty > 1.0

    def test_rho_monotonic_symmetric_pair(self):
        """对称对 ±5°：ρ↑ → CRB↑（相关退化单调；实测锚 ρ=0.9→
        5.03651622824423e-07）。"""
        crbs = []
        for rho in (0.0, 0.5, 0.9):
            m = doa_crb_ula_multisource(
                n_elements=N_EL, snapshots=T_SNAP, angles_deg=[-5.0, 5.0],
                snr_db=15.0, spacing_lambda=D_LAM, corr_coef=rho)
            crbs.append(m["crb_var_rad2"][0])
        assert crbs[0] < crbs[1] < crbs[2]
        assert crbs[2] == pytest.approx(5.03651622824423e-07, rel=1e-12)
        assert m["fim_matrix"][0][1] != 0.0  # ρ=0.9 非对角非零
        assert all(v > 0 for v in np.linalg.eigvalsh(
            np.asarray(m["fim_matrix"])))  # 正定

    def test_anchor_values_and_fields(self):
        m = doa_crb_ula_multisource(
            n_elements=N_EL, snapshots=T_SNAP, angles_deg=[-10.0, 25.0],
            snr_db=[15.0, 9.0], spacing_lambda=D_LAM, corr_coef=0.5)
        assert m["crb_var_rad2"][0] == pytest.approx(1.624406131904254e-07,
                                                     rel=1e-12)
        assert m["coupling_penalty"][0] == pytest.approx(
            1.0516828385827615, rel=1e-9)
        assert m["worst_source_index"] == 1
        assert m["crb_std_deg"][1] == pytest.approx(
            math.degrees(math.sqrt(m["crb_var_rad2"][1])), rel=1e-12)
        assert len(m["fim_matrix"]) == 2

    def test_service_envelope_and_domain(self):
        params = {"n_elements": N_EL, "snapshots": T_SNAP,
                  "angles_deg": [-10.0, 10.0], "snr_db": 15.0,
                  "spacing_lambda": D_LAM, "corr_coef": 0.3}
        env = run_calculator("doa_crb_ula_multisource", params)
        assert env["ok"] is True
        import json
        env2 = run_calculator("doa_crb_ula_multisource", params)
        assert json.dumps(env, sort_keys=True) == json.dumps(env2,
                                                             sort_keys=True)
        for bad in ({"n_elements": 2, "angles_deg": [1.0, 2.0]},
                    {"angles_deg": [1.0, 1.0]},
                    {"angles_deg": [90.0, 20.0]},
                    {"corr_coef": 1.0},
                    {"snr_db": [15.0]},
                    {"spacing_lambda": 1.5}):
            out = run_calculator("doa_crb_ula_multisource",
                                 {**params, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"


# ─── reflective_phaser ────────────────────────────────────────────────────

F_GHZ, Z0 = 10.0, 50.0
TAN_22P5 = 0.41421356237309503  # tan(22.5°)=tan(90°/4)


def _gamma_numeric(r_norm: float, x_norm: float) -> complex:
    """第二路线：阻抗式 Γ=(r+jx−1)/(r+jx+1) 直算（不走闭式角）。"""
    z = complex(r_norm, x_norm)
    return (z - 1.0) / (z + 1.0)


class TestReflectivePhaser:
    def test_design_anchor_90deg(self):
        r = reflective_phaser(f_ghz=F_GHZ, delta_phi_deg=90.0, z0_ohm=Z0)
        assert r["route"] == "design_from_delta_phi"
        assert r["x1_norm"] == pytest.approx(TAN_22P5, rel=1e-12)
        assert r["x2_norm"] == pytest.approx(-TAN_22P5, rel=1e-12)
        assert r["gamma1_phase_deg"] == pytest.approx(135.0, rel=1e-9)
        assert r["gamma2_phase_deg"] == pytest.approx(225.0, rel=1e-9)
        assert r["delta_phi_deg"] == pytest.approx(90.0, rel=1e-9)
        assert r["states"][0]["series_L_nH"] == pytest.approx(
            TAN_22P5 * Z0 / (2.0 * math.pi * F_GHZ), rel=1e-9)
        assert r["states"][1]["shunt_C_pf"] == pytest.approx(
            1e3 / (2.0 * math.pi * F_GHZ * TAN_22P5 * Z0), rel=1e-9)

    def test_180bit_two_finite_states(self):
        """180° 位 x=±1 双有限态精确可达（与加载线 b→∞ 的分工）。"""
        r = reflective_phaser(f_ghz=F_GHZ, delta_phi_deg=180.0)
        assert r["x1_norm"] == pytest.approx(1.0, rel=1e-12)
        assert r["x2_norm"] == pytest.approx(-1.0, rel=1e-12)
        assert r["delta_phi_deg"] == pytest.approx(180.0, rel=1e-9)

    def test_lossless_gamma_and_closed_form_angle(self):
        """无耗 |Γ|=1 机器精度；闭式角 φ=180°−2arctan(x) vs 阻抗式数值
        角第二路线（≤1e-12，全档位）。"""
        for x in (-3.0, -1.0, -0.5, 0.5, 1.0, 3.0):
            a = reflective_phaser(f_ghz=F_GHZ, x1_norm=x, x2_norm=-x)
            assert a["gamma1_mag"] == pytest.approx(1.0, rel=1e-12)
            g = _gamma_numeric(0.0, x)
            phi_num = math.degrees(math.atan2(g.imag, g.real)) % 360.0
            phi_closed = (180.0 - 2.0 * math.degrees(math.atan(x))) % 360.0
            assert a["gamma1_phase_deg"] == pytest.approx(phi_num, rel=1e-12)
            assert phi_num == pytest.approx(phi_closed, abs=1e-9)

    def test_delta_phi_arctan_identity_and_roundtrip(self):
        """Δφ=2(arctan x1−arctan x2) 恒等式 + design→analysis roundtrip。"""
        for phi in (22.5, 45.0, 90.0, 135.0, 180.0, 270.0):
            d = reflective_phaser(f_ghz=F_GHZ, delta_phi_deg=phi)
            got = 2.0 * math.degrees(
                math.atan(d["x1_norm"]) - math.atan(d["x2_norm"]))
            assert got == pytest.approx(phi, rel=1e-9)
            assert d["delta_phi_unwrapped_deg"] == pytest.approx(
                phi, rel=1e-9)
            a = reflective_phaser(f_ghz=F_GHZ, x1_norm=d["x1_norm"],
                                  x2_norm=d["x2_norm"])
            assert a["route"] == "analysis_from_reactance"
            assert a["delta_phi_deg"] == pytest.approx(
                phi if phi <= 180.0 else phi - 360.0, rel=1e-9)

    def test_varactor_route(self):
        """变容管路线 x=−10³/(2πfC·Z0)（1pF/2pF@10GHz 50Ω 锚）。"""
        v = reflective_phaser(f_ghz=F_GHZ, c1_pf=1.0, c2_pf=2.0)
        x1 = -1e3 / (2.0 * math.pi * F_GHZ * 1.0 * Z0)
        assert v["route"] == "analysis_from_varactor"
        assert v["x1_norm"] == pytest.approx(x1, rel=1e-12)
        assert v["x2_norm"] == pytest.approx(x1 / 2.0, rel=1e-12)
        assert v["delta_phi_deg"] == pytest.approx(-17.227452144750373,
                                                   rel=1e-9)

    def test_loss_route(self):
        """损耗口径：r=0.05/x=1 → |Γ|=0.9512492568368084、IL=0.434113dB、
        Q=|x|/r=20（阻抗式数值第二路线同值）。"""
        lossy = reflective_phaser(f_ghz=F_GHZ, x1_norm=1.0, x2_norm=-1.0,
                                  r_norm=0.05)
        assert lossy["gamma1_mag"] == pytest.approx(0.9512492568368084,
                                                    rel=1e-12)
        assert abs(_gamma_numeric(0.05, 1.0)) == pytest.approx(
            lossy["gamma1_mag"], rel=1e-12)
        assert lossy["states"][0]["reflection_loss_db"] == pytest.approx(
            0.4341133902733935, rel=1e-9)
        assert lossy["states"][0]["load_q"] == pytest.approx(20.0, rel=1e-12)
        assert lossy["insertion_loss_db"] == pytest.approx(
            0.4341133902733935, rel=1e-9)

    def test_domain_rejections(self):
        with pytest.raises(ValueError, match="360"):
            reflective_phaser(f_ghz=F_GHZ, delta_phi_deg=360.0)
        with pytest.raises(ValueError, match="0"):
            reflective_phaser(f_ghz=F_GHZ, delta_phi_deg=0.0)
        with pytest.raises(ValueError, match="二选"):
            reflective_phaser(f_ghz=F_GHZ, delta_phi_deg=90.0,
                              x1_norm=1.0, x2_norm=2.0)
        with pytest.raises(ValueError, match="全缺"):
            reflective_phaser(f_ghz=F_GHZ)
        with pytest.raises(ValueError, match="同态"):
            reflective_phaser(f_ghz=F_GHZ, x1_norm=1.0, x2_norm=1.0)
        with pytest.raises(ValueError, match="≥0"):
            reflective_phaser(f_ghz=F_GHZ, x1_norm=1.0, x2_norm=2.0,
                              r_norm=-0.1)


# ─── multiplexer_channel_prototype ────────────────────────────────────────

MUX_F0, MUX_BW, MUX_A, MUX_FS, MUX_RIP = 4.0, 0.4, 40.0, 5.0, 0.5


class TestMultiplexerChannelPrototype:
    def test_chebyshev_anchor(self):
        r = multiplexer_channel_prototype(MUX_F0, MUX_BW, MUX_A, MUX_FS,
                                          prototype="chebyshev",
                                          ripple_db=MUX_RIP)
        assert r["order_min"] == 3
        assert r["order_raw"] == pytest.approx(2.9006395901696624, rel=1e-12)
        assert r["attenuation_at_stopband_db"] == pytest.approx(
            41.88918324941373, rel=1e-12)
        assert r["attenuation_order_minus_1_db"] == pytest.approx(
            22.897518797981785, rel=1e-12)
        assert r["minimal"] is True
        assert r["omega_stop"] == pytest.approx(4.5200000000000005,
                                                rel=1e-12)
        assert r["g_values"] == pytest.approx(
            [1.0, 1.5963, 1.0967, 1.5963, 1.0], rel=1e-4)

    def test_omega_band_edge_identity(self):
        """带通→低通几何中心变换：通带边缘 Ω=±1 精确（定义域恒等式）。"""
        r = multiplexer_channel_prototype(MUX_F0, MUX_BW, MUX_A, MUX_FS,
                                          ripple_db=MUX_RIP)
        f0, delta = r["f0_geo_ghz"], r["fractional_bw"]
        for edge in (r["f_low_ghz"], r["f_high_ghz"]):
            assert abs(edge / f0 - f0 / edge) / delta == pytest.approx(
                1.0, rel=1e-12)
        assert f0 == pytest.approx(math.sqrt(r["f_low_ghz"]
                                             * r["f_high_ghz"]), rel=1e-15)

    def test_scan_second_route_and_tn_recurrence(self):
        """第二路线：整数扫描最小阶（不消费闭式）+ T_n 递推抑制（不用
        cosh 恒等式）——双路线与闭式 rel<1e-9。"""
        r = multiplexer_channel_prototype(MUX_F0, MUX_BW, MUX_A, MUX_FS,
                                          ripple_db=MUX_RIP)
        eps2 = 10.0 ** (MUX_RIP / 10.0) - 1.0
        om_s = r["omega_stop"]

        def atten_closed(n_ord: int, om: float) -> float:
            return 10.0 * math.log10(
                1.0 + eps2 * math.cosh(n_ord * math.acosh(om)) ** 2)

        assert _scan_min_order(atten_closed, om_s, MUX_A) == r["order_min"]
        assert _atten_cheb_poly(r["order_min"], om_s, eps2) == pytest.approx(
            r["attenuation_at_stopband_db"], rel=1e-9)
        assert _atten_cheb_poly(r["order_min"] - 1, om_s, eps2) \
            == pytest.approx(r["attenuation_order_minus_1_db"], rel=1e-9)

    def test_butterworth_anchor_and_dual_source_g(self):
        """Butterworth N=4 锚 + g 值双源互证（N≤5 与 core/diplexer_
        compose 逐位；N>5 超 diplexer cap=5 面本族闭式自算可达）。"""
        b = multiplexer_channel_prototype(MUX_F0, MUX_BW, MUX_A, MUX_FS,
                                          prototype="butterworth")
        assert b["order_min"] == 4
        assert b["order_raw"] == pytest.approx(3.0527567578383654,
                                               rel=1e-12)
        assert b["ripple_db"] == pytest.approx(3.0102999566398125, rel=1e-15)
        assert b["g_values"] == pytest.approx(
            [1.0, 0.7654, 1.8478, 1.8478, 0.7654, 1.0], rel=1e-4)
        # 双源互证：本族链 g[1..N] vs core/diplexer_compose 单源（1..5 逐位，
        # 阶数梯 = 同几何下抑制 8/12/20/30/40 dB）
        for n_ord, a_db in ((1, 8.0), (2, 12.0), (3, 20.0), (4, 30.0),
                            (5, 40.0)):
            bb = multiplexer_channel_prototype(
                1.0, 0.5, a_db, 2.0, prototype="butterworth")
            assert bb["order_min"] == n_ord
            assert bb["g_values"][1:1 + n_ord] == pytest.approx(
                list(butterworth_g_values(n_ord)), rel=1e-12)
            assert bb["g_values"][0] == 1.0 and bb["g_values"][-1] == 1.0
        # N>5（diplexer_compose cap=5 之外）：闭式自算 + 教科书 N=7 值
        b7 = multiplexer_channel_prototype(
            1.0, 0.5, 62.0, 2.0, prototype="butterworth")
        assert b7["order_min"] == 7
        assert b7["g_values"][1:8] == pytest.approx(
            [0.4450, 1.2470, 1.8019, 2.0000, 1.8019, 1.2470, 0.4450],
            rel=2e-4)

    def test_per_channel_over_plan(self):
        """逐通道消费：对 channel_plan 逐道调用（各道 Ω_s>1、阶数有界）。"""
        plan = multiplexer_channel_plan(2.0, 8.0, 4)
        for ch in plan["channels"]:
            other = [c["f_center_ghz"] for c in plan["channels"]
                     if c["index"] != ch["index"]]
            fs = min(other, key=lambda v: abs(v - ch["f_center_ghz"]))
            pr = multiplexer_channel_prototype(
                ch["f_center_ghz"], ch["bandwidth_ghz"], 35.0, fs,
                ripple_db=0.1)
            assert pr["omega_stop"] > 1.0
            assert 1 <= pr["order_min"] <= 31
            assert pr["minimal"] is True

    def test_service_envelope_and_domain(self):
        params = {"f_center_ghz": MUX_F0, "channel_bw_ghz": MUX_BW,
                  "rejection_db": MUX_A, "stopband_freq_ghz": MUX_FS,
                  "prototype": "chebyshev", "ripple_db": MUX_RIP}
        env = run_calculator("multiplexer_channel_prototype", params)
        assert env["ok"] is True
        for bad in ({"stopband_freq_ghz": 4.0},
                    {"stopband_freq_ghz": 3.8},
                    {"f_center_ghz": 0.1, "channel_bw_ghz": 0.4},
                    {"prototype": "bessel"},
                    {"ripple_db": None},
                    {"rejection_db": 600.0, "channel_bw_ghz": 0.001,
                     "stopband_freq_ghz": 4.002, "ripple_db": 0.01}):
            out = run_calculator("multiplexer_channel_prototype",
                                 {**params, **bad})
            assert out["ok"] is False, f"{bad} 未显式拒绝"


# ─── waveguide_lambda_g ───────────────────────────────────────────────────

WR90_A, WR90_B, WR90_F = 22.86, 10.16, 10.0


class TestWaveguideLambdaG:
    def test_wr90_anchor(self):
        r = waveguide_lambda_g(a_mm=WR90_A, f_ghz=WR90_F, b_mm=WR90_B)
        assert r["fc10_ghz"] == pytest.approx(6.557140376202975, rel=1e-12)
        assert r["lambda_c_mm"] == pytest.approx(45.72, rel=1e-12)
        assert r["lambda_0_mm"] == pytest.approx(29.979245799999998,
                                                 rel=1e-12)
        assert r["lambda_g_mm"] == pytest.approx(39.7071192111121, rel=1e-12)
        assert r["beta_rad_per_mm"] == pytest.approx(0.15823825631301972,
                                                     rel=1e-12)
        assert r["beta_rad_per_m"] == pytest.approx(158.23825631301972,
                                                    rel=1e-12)
        assert r["b_mm"] == WR90_B

    def test_three_forms_cross_check(self):
        """λg 三形态互证：fc/f 形（键内）= λ0/2a 形（slot_array 内嵌式）
        = kz 反解形（√(k0²−(π/a)²)），rel≤1e-12。"""
        from rfauto.core.calc_families.slot_array import _lambda_g_mm
        r = waveguide_lambda_g(a_mm=WR90_A, f_ghz=WR90_F)
        assert r["lambda_g_mm"] == pytest.approx(
            _lambda_g_mm(WR90_F, WR90_A), rel=1e-12)
        k0 = 2.0 * math.pi * WR90_F / C_MM_GHZ
        kz = math.sqrt(k0 * k0 - (math.pi / WR90_A) ** 2)
        assert r["lambda_g_mm"] == pytest.approx(2.0 * math.pi / kz,
                                                 rel=1e-12)

    def test_beta_and_velocity_identities(self):
        """β=2π/λg 恒等 + vp/c·vg/c=1 + vp>1>vg 色散方向。"""
        r = waveguide_lambda_g(a_mm=WR90_A, f_ghz=WR90_F)
        assert r["beta_rad_per_mm"] == pytest.approx(
            2.0 * math.pi / r["lambda_g_mm"], rel=1e-15)
        assert r["beta_rad_per_m"] == pytest.approx(
            r["beta_rad_per_mm"] * 1e3, rel=1e-15)
        assert r["vp_over_c"] == pytest.approx(
            r["lambda_g_mm"] / r["lambda_0_mm"], rel=1e-15)
        assert r["vp_over_c"] * r["vg_over_c"] == pytest.approx(1.0,
                                                                rel=1e-12)
        assert r["vp_over_c"] > 1.0 > r["vg_over_c"]
        assert r["f_over_fc"] == pytest.approx(WR90_F / r["fc10_ghz"],
                                               rel=1e-15)

    def test_near_cutoff_dispersion(self):
        """截止趋近发散方向（f→fc⁺ λg→∞）+ λc=2a 恰值。"""
        r_hi = waveguide_lambda_g(a_mm=WR90_A, f_ghz=2.0 * WR90_F)
        r_lo = waveguide_lambda_g(a_mm=WR90_A, f_ghz=1.2 * WR90_F)
        assert r_lo["lambda_g_mm"] > r_hi["lambda_g_mm"]
        assert r_hi["lambda_g_mm"] == pytest.approx(
            r_hi["lambda_0_mm"] / math.sqrt(
                1.0 - (r_hi["f_over_fc"]) ** -2), rel=1e-12)
        for r in (r_hi, r_lo):
            assert r["lambda_c_mm"] == pytest.approx(2.0 * WR90_A,
                                                     rel=1e-15)

    def test_domain_rejections(self):
        with pytest.raises(ValueError, match="截止"):
            waveguide_lambda_g(a_mm=WR90_A, f_ghz=6.0)
        with pytest.raises(ValueError, match="≤a_mm"):
            waveguide_lambda_g(a_mm=WR90_A, f_ghz=WR90_F, b_mm=30.0)
        with pytest.raises(ValueError, match=">0"):
            waveguide_lambda_g(a_mm=WR90_A, f_ghz=WR90_F, b_mm=-1.0)
        with pytest.raises(ValueError, match=">0"):
            waveguide_lambda_g(a_mm=0.0, f_ghz=WR90_F)

    def test_service_envelope(self):
        env = run_calculator("waveguide_lambda_g",
                             {"a_mm": WR90_A, "f_ghz": WR90_F,
                              "b_mm": WR90_B})
        assert env["ok"] is True
        import json
        env2 = run_calculator("waveguide_lambda_g",
                              {"a_mm": WR90_A, "f_ghz": WR90_F,
                               "b_mm": WR90_B})
        assert json.dumps(env, sort_keys=True) == json.dumps(env2,
                                                             sort_keys=True)
