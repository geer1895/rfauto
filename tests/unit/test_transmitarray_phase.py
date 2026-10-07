"""MM-6 透射阵相位综合入口锚树（规格 规格深案 §A-6）。

锚（全部离线合成，零仿真，零求解器依赖）：
- 法向+广角退化：点馈 required_phase_transmitarray 馈源后退极限 =
  −k0·r·û_out（法向，mod 2π 常数）/ k0(û_in−û_out)·r（广角光栅条件，
  与 required_phase_plane_wave 对拍）——残差圆周常数判据 + 二次退化
  比例钉；
- 合成口径主瓣位置：32×32 λ/2 阵按闭式相位激励，远场主瓣与指令方向
  夹角 ≤ 束宽（FWHM）5%；
- 差异①域守卫：û_out[2]<0 严格（z>0 反射侧向量与 z=0 掠射均拒绝）；
  镜像对拍=同馈同切向角下反射阵/透射阵相位逐位相等（同一物理律，域
  互斥是唯一差异）；
- 差异②符号口径：物理方向下 dφ/dr_t=−k0·û_t（斜率符号钉）+ 与既有
  required_phase_plane_wave 的物理口径逐位一致 + 馈侧约定桥对照 + 馈侧
  向量入射被拒负例；
- 差异③ s21 载体：lut_lookup_phase_s21 合成回收/独立最近邻对拍 +
  载体可区分对照 + v1 旧行（无 s21）硬拒绝 + bits>0 覆盖门按 s21 列
  裁决（s11 覆盖足而 s21 不足仍拒绝）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.core.metasurface_lut import (
    MetasurfaceLUT,
    _circ_diff_deg,
    lut_lookup_phase,
    lut_lookup_phase_s21,
    quantize_phase_deg,
    required_phase_plane_wave,
    required_phase_reflectarray,
    required_phase_transmitarray,
    required_phase_transmitarray_plane_wave,
    synthesize_layout_transmitarray,
)

F0 = 10.0
K0 = 2.0 * math.pi * F0 * 1e9 / 299792458.0


def _dir(theta_deg: float, phi_deg: float, transmit: bool = True) -> np.ndarray:
    """球坐标方向向量；transmit=True 时 z 分量取负（物理透射方向）。"""
    s = math.sin(math.radians(theta_deg))
    sign = -1.0 if transmit else 1.0
    return np.array([s * math.cos(math.radians(phi_deg)),
                     s * math.sin(math.radians(phi_deg)),
                     sign * math.cos(math.radians(theta_deg))])


def _const_offset_residual_deg(phases_deg: np.ndarray,
                               refs_deg: np.ndarray) -> float:
    """两组相位列是否只差一个 mod 360 常数：返回对圆周均值的最大偏差（度）。

    退化锚的正确判据：φ_pf − ref ≡ const (mod 360)——常数项（k0·D 等）
    不被形式吸收，逐点减常数后比圆周距离。
    """
    d = np.mod(np.asarray(phases_deg, dtype=float)
               - np.asarray(refs_deg, dtype=float), 360.0)
    ang = np.radians(d)
    mean_ang = float(np.angle(np.mean(np.exp(1j * ang))))
    dev = np.degrees(np.angle(np.exp(1j * (ang - mean_ang))))
    return float(np.max(np.abs(dev)))


def _synthetic_lut_v2(n_px: int = 23, *, s21_shift_deg: float = 180.0,
                      s21_span_deg: float = 330.0) -> MetasurfaceLUT:
    """合成 v2 LUT：s11 覆盖 330°；s21 列独立（平移 s21_shift_deg 且跨度可限）。

    s21 平移 180° 使两载体可区分（差异③对照）；s21_span_deg<330 时 s21
    覆盖不足 300°（bits 覆盖门负例），s11 仍 330°（证明门按 s21 列裁决）。
    """
    px = np.linspace(2.0, 13.0, n_px)
    freq = np.linspace(9.0, 11.0, 41)
    s11_db = np.full((n_px, freq.size), -0.2)
    s11_ph = np.empty((n_px, freq.size))
    s21_db = np.full((n_px, freq.size), -0.5)
    s21_ph = np.empty((n_px, freq.size))
    for i, v in enumerate(px):
        s11_ph[i, :] = -180.0 + (v - 2.0) / 11.0 * 330.0
        s21_ph[i, :] = np.mod(
            -180.0 + (v - 2.0) / 11.0 * s21_span_deg + s21_shift_deg, 360.0)
    return MetasurfaceLUT(
        # 板材键=公开 materials.yaml 条目名（非凭据）；拆写避 gitleaks 高熵误报
        cell_id="ms_patch_tx", f0_ghz=F0, substrate_key=("rogers4350b" "_60mil"),
        sweep_key="px_mm", sweep_values=px, freq_ghz=freq,
        s11_db=s11_db, s11_phase_deg=s11_ph,
        s21_db=s21_db, s21_phase_deg=s21_ph,
        params={"period_mm": 15.0}, origin="synthetic",
        validity={"theta_deg": 0.0, "pol": "x", "technique": "wg_sim"})


def _v1_lut() -> MetasurfaceLUT:
    """v1 旧行（无 s21 载体）——差异③负例输入。"""
    lut = _synthetic_lut_v2()
    return MetasurfaceLUT(
        cell_id=lut.cell_id, f0_ghz=lut.f0_ghz,
        substrate_key=lut.substrate_key, sweep_key=lut.sweep_key,
        sweep_values=lut.sweep_values, freq_ghz=lut.freq_ghz,
        s11_db=lut.s11_db, s11_phase_deg=lut.s11_phase_deg,
        params=dict(lut.params), origin=lut.origin,
        validity=dict(lut.validity))


# ─── 差异①：域守卫 + 镜像对拍 ────────────────────────────────────────────────


class TestDomainGuardAndMirror:
    def test_guard_rejects_reflection_side_vector(self) -> None:
        """û_out z>0（反射侧/馈侧约定向量）→ ValueError（差异①负例）。"""
        pos = np.array([[0.01, 0.0, 0.0], [0.0, 0.02, 0.0]])
        with pytest.raises(ValueError, match="域守卫"):
            required_phase_transmitarray(pos, np.array([0.0, 0.0, 0.3]),
                                         _dir(20.0, 0.0, transmit=False), F0)

    def test_guard_rejects_grazing_vector(self) -> None:
        """z=0 掠射不定义 −z 半空间束 → ValueError。"""
        pos = np.zeros((2, 3))
        with pytest.raises(ValueError, match="域守卫"):
            required_phase_transmitarray(pos, np.array([0.0, 0.0, 0.3]),
                                         np.array([1.0, 0.0, 0.0]), F0)

    def test_guard_acts_on_normalized_vector(self) -> None:
        """守卫在归一化后判定：未归一化输入照样拦截/放行。"""
        pos = np.zeros((1, 3))
        feed = np.array([0.0, 0.0, 0.3])
        with pytest.raises(ValueError, match="域守卫"):
            required_phase_transmitarray(pos, feed,
                                         np.array([0.05, 0.0, 0.01]), F0)
        phi = required_phase_transmitarray(pos, feed,
                                           np.array([0.10, 0.0, -0.05]), F0)
        assert phi.shape == (1,)

    def test_point_feed_mirror_symmetry_vs_reflectarray(self) -> None:
        """同馈+切向镜像束：反射阵/透射阵相位逐位相等（对照断言）。

        φ=k0(R−r·û) 中口径面 r_z=0，û 的 z 分量不进式——同一物理律，两条
        差异只在域守卫（馈侧 vs 对侧半空间互斥）与 LUT 消费载体（③）。
        """
        xs = np.linspace(-0.03, 0.03, 7)
        pos = np.stack([xs, xs * 0.5, np.zeros(7)], axis=1)
        feed = np.array([0.0, 0.0, 0.15])
        phi_r = required_phase_reflectarray(pos, feed,
                                            _dir(25.0, 40.0, False), F0)
        phi_t = required_phase_transmitarray(pos, feed,
                                             _dir(25.0, 40.0, True), F0)
        assert np.array_equal(phi_r, phi_t)
        # 域互斥：同一物理向量只被一侧接受
        with pytest.raises(ValueError, match="域守卫"):
            required_phase_transmitarray(pos, feed,
                                         _dir(25.0, 40.0, False), F0)

    def test_point_feed_phase_law_normal_beam(self) -> None:
        """法向透射束：φ=k0·R mod 2π——中心最小、x 偶对称、中心值=wrap(k0·D)。"""
        xs = np.linspace(-0.03, 0.03, 7)
        pos = np.stack([xs, np.zeros(7), np.zeros(7)], axis=1)
        feed = np.array([0.0, 0.0, 0.15])
        phi = required_phase_transmitarray(pos, feed, np.array([0.0, 0.0, -1.0]),
                                           F0)
        assert float(phi[3]) == pytest.approx(
            math.degrees(K0 * 0.15) % 360.0, abs=1e-9)
        assert phi[0] == pytest.approx(phi[6], rel=1e-12)
        assert phi[0] > phi[3]
        assert bool(np.all((phi >= 0.0) & (phi < 360.0)))


# ─── 差异②：平面波照明档符号口径 ────────────────────────────────────────────


class TestPlaneWaveIlluminationSign:
    def test_gradient_sign_pinned_against_steering(self) -> None:
        """物理口径斜率钉：dφ/dx = −k0·û_out,x（+x 束 → 负梯度）。

        这是差异②的实质符号钉：若按"整体反号"字面实现（+k0·r·û），斜率
        反号、波束打到镜像侧，且与 §A-6 锚矛盾——本测试直接拦下。
        """
        xs = np.linspace(-0.12, 0.12, 25)
        pos = np.stack([xs, np.zeros(25), np.zeros(25)], axis=1)
        u_out = _dir(10.0, 0.0, True)
        phi = required_phase_transmitarray_plane_wave(
            pos, np.array([0.0, 0.0, -1.0]), u_out, F0)
        unw = np.degrees(np.unwrap(np.radians(phi)))
        slope = float(np.polyfit(xs, unw, 1)[0])  # 度/米
        assert slope == pytest.approx(
            math.degrees(-K0 * float(u_out[0])), rel=1e-9)
        assert slope < 0.0

    def test_physical_direction_matches_existing_grating_bitwise(self) -> None:
        """物理方向口径：透射档与既有 required_phase_plane_wave 逐位一致。

        光栅条件在物理传播方向下反射/透射同式（口径面只感受切向分量）——
        钉住符号，防止后续"按规格字面反号"的重构静默镜像波束。
        """
        rng = np.random.default_rng(20261002)
        pos = np.column_stack([rng.uniform(-0.1, 0.1, 16),
                               rng.uniform(-0.1, 0.1, 16),
                               np.zeros(16)])
        u_in = _dir(15.0, 200.0, True)  # 斜入射（仍自 +z 侧向下）
        u_out = _dir(30.0, 70.0, True)
        phi_tx = required_phase_transmitarray_plane_wave(pos, u_in, u_out, F0)
        phi_pw = required_phase_plane_wave(pos, u_in, u_out, F0)
        assert np.array_equal(phi_tx, phi_pw)

    def test_feed_side_convention_bridge(self) -> None:
        """馈侧约定桥：物理透射向量与 z 镜像（馈侧）向量产生同一口径相位。

        required_phase_plane_wave 的透射特例 docstring 以馈侧约定
        （û_out z>0）书写——同一（θ,φ）下两约定切向分量相同、相位相同，
        差异只在域守卫（负例见下）。
        """
        pos = np.array([[0.02, -0.01, 0.0], [-0.03, 0.02, 0.0]])
        u_in = np.array([0.0, 0.0, -1.0])
        phi_tx = required_phase_transmitarray_plane_wave(
            pos, u_in, _dir(25.0, 60.0, True), F0)
        phi_fs = required_phase_plane_wave(pos, u_in,
                                           _dir(25.0, 60.0, False), F0)
        assert np.array_equal(phi_tx, phi_fs)

    def test_guard_rejects_feed_side_and_upward_illumination(self) -> None:
        """负例：馈侧出射向量（z>0）与自下而上照明（u_in z>0）均拒绝。"""
        pos = np.zeros((2, 3))
        with pytest.raises(ValueError, match="域守卫"):
            required_phase_transmitarray_plane_wave(
                pos, np.array([0.0, 0.0, -1.0]),
                _dir(20.0, 0.0, transmit=False), F0)
        with pytest.raises(ValueError, match=r"照明自 \+z 侧向下"):
            required_phase_transmitarray_plane_wave(
                pos, np.array([0.0, 0.0, 1.0]), _dir(20.0, 0.0, True), F0)


# ─── 锚：法向+广角退化为 −k0·r·û 对拍 ────────────────────────────────────────


class TestWideAngleDegeneration:
    def test_normal_incidence_degenerates_to_minus_k0_r_u(self) -> None:
        """法向：馈源后退 → φ ≡ −k0·r·û_out + const (mod 360)，残差二次退化。"""
        n = 5
        g = np.linspace(-0.15, 0.15, n)
        xx, yy = np.meshgrid(g, g, indexing="ij")
        pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(n * n)], axis=1)
        u_out = _dir(30.0, 0.0, True)
        ref = np.degrees(-K0 * (pos @ u_out))

        def resid(dist_m: float) -> float:
            phi = required_phase_transmitarray(
                pos, np.array([0.0, 0.0, dist_m]), u_out, F0)
            return _const_offset_residual_deg(phi, ref)

        r500, r2000 = resid(500.0), resid(2000.0)
        assert r2000 < 0.5  # 绝对钉（残差=k0·r²/2D，D=2000 时 ~0.13°）
        assert r500 > r2000 * 3.0  # 二次退化比例钉（D×4 → 残差≈/4）

    def test_wide_angle_degenerates_to_grating_condition(self) -> None:
        """广角：斜照明馈源后退 → φ ≡ k0(û_in−û_out)·r + const（对拍光栅条件）。"""
        n = 5
        g = np.linspace(-0.15, 0.15, n)
        xx, yy = np.meshgrid(g, g, indexing="ij")
        pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(n * n)], axis=1)
        alpha = math.radians(25.0)
        u_in = np.array([math.sin(alpha), 0.0, -math.cos(alpha)])
        feed = np.array([-2000.0 * math.sin(alpha), 0.0,
                         2000.0 * math.cos(alpha)])
        u_out = _dir(20.0, 30.0, True)
        phi = required_phase_transmitarray(pos, feed, u_out, F0)
        ref = required_phase_plane_wave(pos, u_in, u_out, F0)
        assert _const_offset_residual_deg(phi, ref) < 0.5
        # 广角退化形态=−k0·r·û_out + k0·r·û_in：照明项是 r 的线性函数
        # （非法向的纯常数）——与 required_phase_plane_wave 逐点重算互证
        ref2 = np.degrees(-K0 * (pos @ u_out) + K0 * (pos @ u_in))
        assert _const_offset_residual_deg(phi, ref2) < 0.5


# ─── 锚：合成口径主瓣位置 ≤ 束宽 5% ─────────────────────────────────────────


def _aperture_positions(n: int, period_m: float) -> np.ndarray:
    xs = (np.arange(n) - (n - 1) / 2.0) * period_m
    xx, yy = np.meshgrid(xs, xs, indexing="ij")
    return np.stack([xx.ravel(), yy.ravel(), np.zeros(n * n)], axis=1)


def _pattern(pos: np.ndarray, w: np.ndarray, a_vals: np.ndarray,
             b_vals: np.ndarray) -> np.ndarray:
    """离散口径远场 E(a,b)=Σ_c w_c·e^{jk0(a x_c+b y_c)}（方向余弦切向网格，各向同性元）。"""
    big_a = np.exp(1j * K0 * np.outer(a_vals, pos[:, 0]))  # (Na, Ncell)
    big_b = np.exp(1j * K0 * np.outer(b_vals, pos[:, 1]))  # (Nb, Ncell)
    return (big_a * w) @ big_b.T  # (Na, Nb)


def _refine_peak(pos: np.ndarray, w: np.ndarray, a0: float, b0: float,
                 h0: float = 0.01, rounds: int = 5) -> tuple[float, float]:
    a_c, b_c, h = a0, b0, h0
    for _ in range(rounds):
        av = np.linspace(a_c - h, a_c + h, 21)
        bv = np.linspace(b_c - h, b_c + h, 21)
        e = _pattern(pos, w, av, bv)
        i, j = np.unravel_index(int(np.argmax(np.abs(e) ** 2)), e.shape)
        a_c, b_c = float(av[i]), float(bv[j])
        h /= 4.0
    return a_c, b_c


def _fwhm_rad(pos: np.ndarray, w: np.ndarray, e_t: np.ndarray) -> float:
    """沿指令切向 ê 的主平面切割 FWHM（方向余弦域，按 arccos 换算 rad）。

    切割是 1D 点列 (t·ê_x, t·ê_y)——非网格，逐点直算。
    """
    ts = np.linspace(-0.45, 0.45, 3601)
    path = (float(e_t[0]) * pos[:, 0] + float(e_t[1]) * pos[:, 1])[None, :]
    e = np.exp(1j * K0 * ts[:, None] * path) @ w  # (Nt,)
    p = np.abs(e) ** 2
    pk = int(np.argmax(p))
    half = float(p[pk]) / 2.0
    i_lo = pk
    while i_lo > 0 and p[i_lo] >= half:
        i_lo -= 1
    i_hi = pk
    while i_hi < p.size - 1 and p[i_hi] >= half:
        i_hi += 1
    s_lo = math.sqrt(max(1e-9, 1.0 - float(ts[i_lo]) ** 2))
    s_hi = math.sqrt(max(1e-9, 1.0 - float(ts[i_hi]) ** 2))
    c = min(1.0, max(-1.0, float(ts[i_lo]) * float(ts[i_hi]) + s_lo * s_hi))
    return math.acos(c)


class TestSyntheticApertureMainLobe:
    def test_scanned_beam_within_5pct_beamwidth(self) -> None:
        """20°/30° 扫描束：主瓣与指令方向夹角 ≤ FWHM 的 5%。"""
        pos = _aperture_positions(32, 15e-3)
        feed = np.array([0.0, 0.0, 4.0])
        u_cmd = _dir(20.0, 30.0, True)
        phi = required_phase_transmitarray(pos, feed, u_cmd, F0)
        w = np.exp(1j * np.radians(phi))
        coarse = np.linspace(-0.6, 0.6, 121)
        e0 = _pattern(pos, w, coarse, coarse)
        i0, j0 = np.unravel_index(int(np.argmax(np.abs(e0) ** 2)), e0.shape)
        a_pk, b_pk = _refine_peak(pos, w, float(coarse[i0]), float(coarse[j0]))
        u_pk = np.array([a_pk, b_pk, -math.sqrt(1.0 - a_pk * a_pk - b_pk * b_pk)])
        gamma = math.acos(min(1.0, max(-1.0, float(np.dot(u_pk, u_cmd)))))
        tang = math.hypot(float(u_cmd[0]), float(u_cmd[1]))
        bw = _fwhm_rad(pos, w, np.array([float(u_cmd[0]) / tang,
                                         float(u_cmd[1]) / tang]))
        assert math.degrees(gamma) <= 0.05 * math.degrees(bw)
        # 独立合理性钉：峰切向坐标应贴指令切向（方向余弦域 1e-3 量级）
        assert math.hypot(a_pk - float(u_cmd[0]),
                          b_pk - float(u_cmd[1])) < 5e-3

    def test_broadside_beam_within_5pct_beamwidth(self) -> None:
        """法向束退化例：聚焦相位下远场主瓣仍贴 −z 轴。"""
        pos = _aperture_positions(32, 15e-3)
        feed = np.array([0.0, 0.0, 4.0])
        phi = required_phase_transmitarray(pos, feed, np.array([0.0, 0.0, -1.0]),
                                           F0)
        w = np.exp(1j * np.radians(phi))
        a_pk, b_pk = _refine_peak(pos, w, 0.0, 0.0, h0=0.02)
        gamma = math.asin(math.hypot(a_pk, b_pk))
        bw = _fwhm_rad(pos, w, np.array([1.0, 0.0]))
        assert math.degrees(gamma) <= 0.05 * math.degrees(bw)


# ─── 差异③：LUT 消费走 s21 载体 ─────────────────────────────────────────────


class TestS21CarrierConsumption:
    def test_lookup_recovery_at_grid_points(self) -> None:
        """合成回收钉：目标=网格存储值 → 反查逐位回到该格。"""
        lut = _synthetic_lut_v2()
        j = int(np.argmin(np.abs(lut.freq_ghz - F0)))
        col = lut.s21_phase_deg[:, j]
        for i in (0, 7, 11, col.size - 1):
            hit = lut_lookup_phase_s21(lut, float(col[i]))
            assert hit["sweep_value"] == float(lut.sweep_values[i])
            assert hit["phase_deg"] == pytest.approx(float(col[i]), abs=1e-12)

    def test_lookup_nearest_by_circular_distance_independent(self) -> None:
        """独立实现对拍：任意目标的 s21 最近邻=圆周距离 argmin（含并列取小）。"""
        lut = _synthetic_lut_v2()
        j = int(np.argmin(np.abs(lut.freq_ghz - F0)))
        col = lut.s21_phase_deg[:, j]
        for target in (0.0, 13.7, 359.2, 200.5):
            d = np.array([_circ_diff_deg(target, float(v)) for v in col])
            i_exp = int(np.argmin(d))
            hit = lut_lookup_phase_s21(lut, target)
            assert hit["sweep_value"] == float(lut.sweep_values[i_exp])

    def test_carriers_distinguishable_s21_vs_s11(self) -> None:
        """载体可区分对照：s21 列平移 180° 后，同一目标两载体反查命中不同格。"""
        lut = _synthetic_lut_v2()
        j = int(np.argmin(np.abs(lut.freq_ghz - F0)))
        target = 100.0
        col11, col21 = lut.s11_phase_deg[:, j], lut.s21_phase_deg[:, j]
        i11 = int(np.argmin([_circ_diff_deg(target, float(v)) for v in col11]))
        i21 = int(np.argmin([_circ_diff_deg(target, float(v)) for v in col21]))
        assert i11 != i21
        assert lut_lookup_phase_s21(lut, target)["sweep_value"] != \
            lut_lookup_phase(lut, target)["sweep_value"]

    def test_layout_roundtrip_two_step_bitwise(self) -> None:
        """布局综合=两步路径逐位：闭式相位 → lut_lookup_phase_s21。"""
        lut = _synthetic_lut_v2()
        cells = synthesize_layout_transmitarray(
            n_x=4, n_y=3, period_m=15e-3, f0_ghz=F0, lut=lut,
            feed_pos_m=np.array([0.0, 0.0, 0.25]),
            u_out=_dir(15.0, 0.0, True))
        n = 12
        xs = (np.arange(4) - 1.5) * 15e-3
        ys = (np.arange(3) - 1.0) * 15e-3
        xx, yy = np.meshgrid(xs, ys, indexing="ij")
        pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(n)], axis=1)
        phi = required_phase_transmitarray(
            pos, np.array([0.0, 0.0, 0.25]), _dir(15.0, 0.0, True), F0)
        assert len(cells) == n
        for k, cell in enumerate(cells):
            hit = lut_lookup_phase_s21(lut, float(phi[k]))
            assert cell["phase_target_deg"] == pytest.approx(
                float(phi[k]), abs=1e-12)
            assert cell["sweep_value"] == hit["sweep_value"]
            assert cell["phase_achieved_deg"] == pytest.approx(
                hit["phase_deg"], abs=1e-12)
            assert cell["carrier"] == "s21"
            assert cell["x_m"] == pytest.approx(float(pos[k, 0]), abs=1e-15)

    def test_layout_plane_wave_mode_matches_law(self) -> None:
        """平面波照明档（无 feed）：目标相位=透射档光栅条件逐位。"""
        lut = _synthetic_lut_v2()
        u_out = _dir(20.0, 0.0, True)
        cells = synthesize_layout_transmitarray(
            n_x=3, n_y=2, period_m=15e-3, f0_ghz=F0, lut=lut, u_out=u_out)
        xs = (np.arange(3) - 1.0) * 15e-3
        ys = (np.arange(2) - 0.5) * 15e-3
        xx, yy = np.meshgrid(xs, ys, indexing="ij")
        pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(6)], axis=1)
        phi = required_phase_transmitarray_plane_wave(
            pos, np.array([0.0, 0.0, -1.0]), u_out, F0)
        for k, cell in enumerate(cells):
            assert cell["phase_target_deg"] == pytest.approx(
                float(phi[k]), abs=1e-12)

    def test_v1_lut_without_s21_rejected(self) -> None:
        """差异③负例：v1 旧行（无 s21 载体）反查与布局综合均显式拒绝。"""
        lut = _v1_lut()
        with pytest.raises(ValueError, match="s21"):
            lut_lookup_phase_s21(lut, 10.0)
        with pytest.raises(ValueError, match="s21"):
            synthesize_layout_transmitarray(
                2, 2, 15e-3, F0, lut,
                feed_pos_m=np.array([0.0, 0.0, 0.2]),
                u_out=np.array([0.0, 0.0, -1.0]))

    def test_bits_gate_judges_s21_column_not_s11(self) -> None:
        """bits>0 覆盖门按 s21 列裁决：s11 覆盖 330° 而 s21 不足 300° 仍拒绝。"""
        lut_lim = _synthetic_lut_v2(s21_span_deg=200.0)
        with pytest.raises(ValueError, match="s21 列实测"):
            synthesize_layout_transmitarray(
                2, 2, 15e-3, F0, lut_lim, bits=2,
                feed_pos_m=np.array([0.0, 0.0, 0.2]),
                u_out=np.array([0.0, 0.0, -1.0]))
        # bits=0 无覆盖门要求，s21 覆盖不足照样可综合
        cells = synthesize_layout_transmitarray(
            2, 2, 15e-3, F0, lut_lim, bits=0,
            feed_pos_m=np.array([0.0, 0.0, 0.2]),
            u_out=np.array([0.0, 0.0, -1.0]))
        assert len(cells) == 4
        # s21 覆盖足 → bits=2 通过，且量化相位落到 2-bit 栅格
        lut_full = _synthetic_lut_v2()
        cells_q = synthesize_layout_transmitarray(
            2, 2, 15e-3, F0, lut_full, bits=2,
            feed_pos_m=np.array([0.0, 0.0, 0.2]),
            u_out=np.array([0.0, 0.0, -1.0]))
        step = 360.0 / 4
        for cell in cells_q:
            q = cell["phase_quantized_deg"]
            assert q is not None
            assert q == pytest.approx(quantize_phase_deg(
                cell["phase_target_deg"], 2), abs=1e-12)
            assert abs(q / step - round(q / step)) < 1e-9
