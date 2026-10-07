"""M-2.2 aperture_holography 定向测试：往返恒等主门 + 加窗泄漏 + 奈奎斯特 + 守卫。

判据（方案书 M-2 判据③）：NF 正逆变换往返恒等 ≤1e-12（合成口径场，
带限无渐逝、无窗条件下）；含渐逝例 rel_err **不设门**、以 Parseval 精确
预言钉形态（#122：不凑绿——渐逝置零是逆变换的刻意正则化，偏差=渐逝
能量份额为正确行为）。窗效应为方向性断言 + 解析形态钉（带窗往返重建
= w·E_near → rel_err = ‖(1−w)E‖/‖E‖）。数值裁判 = 合成构造真值（与被测
实现不同源；#118 家族纪律）。c-stream-residual 批补两规格钉：均匀矩形口
sinc 形状锚（几何级数精确闭式）+ 余弦锥削带相位倾斜反演回收。
"""

from __future__ import annotations

import numpy as np
import pytest

from rfauto.core.aperture_holography import (
    C0,
    EVANESCENT_FLOOR,
    ROUNDTRIP_TOL,
    WINDOW_CHOICES,
    aperture_to_near_field,
    near_field_to_aperture,
    nyquist_guard,
    roundtrip_identity,
)

F_HZ = 10.0e9
LAM = C0 / F_HZ  # 0.03 m
K = 2.0 * np.pi / LAM
N_U = N_V = 96
DU = DV = LAM / 3.0  # 满足奈奎斯特（< λ/2），谱支撑 |kx|≤3k
D_M = 2.0 * LAM


def _hann_2d() -> np.ndarray:
    """与被测实现同式的可分离 Hann 窗（测试侧独立重建）。"""
    return np.hanning(N_U)[:, None] * np.hanning(N_V)[None, :]


def _evanescent_mask(du: float, dv: float) -> np.ndarray:
    """测试侧独立重建渐逝掩码（判据即规格定义：k⊥²>k²，与实现同一定义）。"""
    kx = 2.0 * np.pi * np.fft.fftfreq(N_U, d=du)
    ky = 2.0 * np.pi * np.fft.fftfreq(N_V, d=dv)
    return (kx[:, None] ** 2 + ky[None, :] ** 2) > K * K


def _bandlimited_aperture() -> np.ndarray:
    """合成口径场：矩形均匀孔径 × 高斯锥削 → 谱硬截断到 0.8k 圆盘（带限）。

    带限保证往返恒等门干净（逆变换渐逝置零对该场为 no-op）；0.8k 截止
    与传播边界 k 之间留 6.4 bin 间隔，覆盖 Hann 窗的谱卷积展宽。
    """
    x = np.arange(N_U)[:, None] * DU
    y = np.arange(N_V)[None, :] * DV
    xc = (N_U - 1) * DU / 2.0
    yc = (N_V - 1) * DV / 2.0
    half_x = 0.30 * (N_U - 1) * DU / 2.0
    half_y = 0.30 * (N_V - 1) * DV / 2.0
    sigma = 0.35 * LAM
    aperture = (
        (np.abs(x - xc) <= half_x) & (np.abs(y - yc) <= half_y)
    ) * np.exp(-((x - xc) ** 2 + (y - yc) ** 2) / (2.0 * sigma**2))
    spec = np.fft.fft2(aperture.astype(complex))
    kx = 2.0 * np.pi * np.fft.fftfreq(N_U, d=DU)
    ky = 2.0 * np.pi * np.fft.fftfreq(N_V, d=DV)
    mask = (kx[:, None] ** 2 + ky[None, :] ** 2) <= (0.8 * K) ** 2
    e_ap = np.fft.ifft2(spec * mask)
    return e_ap / np.linalg.norm(e_ap)


def _sparse_spectrum_field() -> tuple[np.ndarray, np.ndarray, int]:
    """人为构造谱：5 个传播 bin + 3 个渐逝 bin（幅度同级）→ 近场平面数据。

    渐逝 bin 选在 kx/ky 的 Nyquist bin（±π/du = 3k ≫ k），必然越界。
    """
    kx = 2.0 * np.pi * np.fft.fftfreq(N_U, d=DU)
    ky = 2.0 * np.pi * np.fft.fftfreq(N_V, d=DV)
    k_perp_sq = kx[:, None] ** 2 + ky[None, :] ** 2
    prop_bins = [(0, 0), (1, 0), (0, 1), (3, 2), (2, 4)]
    evan_bins = [(N_U // 2, 0), (N_U // 2, 3), (5, N_V // 2)]
    for p, q in prop_bins:
        assert k_perp_sq[p, q] <= K * K, f"测试自检：({p},{q}) 应为传播 bin"
    for p, q in evan_bins:
        assert k_perp_sq[p, q] > K * K, f"测试自检：({p},{q}) 应为渐逝 bin"
    spec = np.zeros((N_U, N_V), dtype=complex)
    amps = [1.3, 0.9, 1.1, 0.7, 1.0, 1.2, 0.8, 1.05]
    for (p, q), a in zip(prop_bins + evan_bins, amps, strict=True):
        spec[p, q] = a * np.exp(0.3j * (p + q))
    return np.fft.ifft2(spec), spec, len(evan_bins)


# ─── 往返恒等主门（任务书判据③） ────────────────────────────────────────────

def test_roundtrip_identity_bandlimited_gate():
    """合成口径场（矩形均匀+高斯锥削，带限）→ 正变换 → 逆变换往返 ≤1e-12。"""
    e_ap = _bandlimited_aperture()
    e_near = aperture_to_near_field(e_ap, DU, DV, D_M, F_HZ)["e_near"]
    res = roundtrip_identity(e_near, DU, DV, D_M, F_HZ)
    assert res["passed"] is True
    assert isinstance(res["rel_err"], float)
    assert res["rel_err"] <= ROUNDTRIP_TOL
    assert res["max_abs_err"] >= 0.0


def test_parseval_energy_ratio_and_zero_evanescent_bandlimited():
    """带限无窗：能量比 Parseval ==1（1e-12 内），渐逝计数 ==0（内容感知）。"""
    e_ap = _bandlimited_aperture()
    e_near = aperture_to_near_field(e_ap, DU, DV, D_M, F_HZ)["e_near"]
    inv = near_field_to_aperture(e_near, DU, DV, D_M, F_HZ)
    assert inv["evanescent_count"] == 0
    assert abs(inv["energy_ratio"] - 1.0) <= 1e-12
    assert inv["window"] == "none"


def test_forward_tilted_plane_wave_analytic_phase():
    """物理锚：口径面离轴平面波（在栅）→ 正变换相位因子 exp(−jkz·d) 逐点。"""
    p0, q0 = 7, 3
    kx0 = 2.0 * np.pi * p0 / (N_U * DU)
    ky0 = 2.0 * np.pi * q0 / (N_V * DV)
    assert np.sqrt(kx0**2 + ky0**2) < K  # 传播分量（测试自检）
    x = np.arange(N_U)[:, None] * DU
    y = np.arange(N_V)[None, :] * DV
    e_ap = np.exp(-1j * (kx0 * x + ky0 * y))
    out = aperture_to_near_field(e_ap, DU, DV, D_M, F_HZ)
    kz0 = np.sqrt(K * K - kx0**2 - ky0**2)
    expected = e_ap * np.exp(-1j * kz0 * D_M)
    assert np.max(np.abs(out["e_near"] - expected)) <= 1e-10
    assert out["evanescent_count"] == 0
    assert abs(out["energy_ratio"] - 1.0) <= 1e-12


# ─── 渐逝计数与含渐逝往返（如实不设门） ─────────────────────────────────────

def test_evanescent_count_exact_and_zeroing():
    """人为构造超谱分量：evanescent_count 精确 ==3；口径谱渐逝区清零。"""
    e_near, _spec, n_evan = _sparse_spectrum_field()
    res = near_field_to_aperture(e_near, DU, DV, D_M, F_HZ)
    assert res["evanescent_count"] == n_evan
    evan = _evanescent_mask(DU, DV)
    p_ap = np.fft.fft2(res["e_aperture"])
    p_near = np.fft.fft2(e_near)
    peak = float(np.max(np.abs(p_ap)))
    # 置零验证：口径谱在渐逝区低于计数地板（实测值远低于 EVANESCENT_FLOOR）
    assert np.max(np.abs(p_ap[evan])) <= EVANESCENT_FLOOR * peak
    # 传播分量保留：|W⁺|=1 → 谱模不变（相位反向传播，模守恒）；
    # atol 覆盖未放置 bin 的 FFT 舍入尾（~1e-16，噪声比噪声 rtol 无意义）
    np.testing.assert_allclose(
        np.abs(p_ap[~evan]), np.abs(p_near[~evan]), rtol=1e-9, atol=1e-12
    )


def test_roundtrip_evanescent_honest_parseval_pin():
    """含渐逝往返：不设门；rel_err == 渐逝能量份额的 Parseval 精确预言。"""
    e_near, spec, _n = _sparse_spectrum_field()
    evan = _evanescent_mask(DU, DV)
    frac = float(
        np.sqrt(np.sum(np.abs(spec[evan]) ** 2) / np.sum(np.abs(spec) ** 2))
    )
    rt = roundtrip_identity(e_near, DU, DV, D_M, F_HZ)
    assert rt["passed"] is False
    assert rt["rel_err"] > ROUNDTRIP_TOL
    # 刻意置零的精确账：Δ = 渐逝时域分量，rel_err = ‖A_evan‖/‖A‖（1e-9 内）
    assert abs(rt["rel_err"] - frac) <= 1e-9 * frac
    inv = near_field_to_aperture(e_near, DU, DV, D_M, F_HZ)
    assert abs(inv["energy_ratio"] - (1.0 - frac**2)) <= 1e-9


# ─── 加窗：谱泄漏对比 + 能量比方向性 + 带窗往返形态钉 ───────────────────────

def _spectral_concentration(spec: np.ndarray, half: int = 2) -> float:
    """谱能量集中度：|P|² 峰值 bin ±half 邻域（模周期索引）能量占比。"""
    power = np.abs(spec) ** 2
    p_pk, q_pk = np.unravel_index(int(np.argmax(power)), power.shape)
    total = float(np.sum(power))
    acc = 0.0
    for dp in range(-half, half + 1):
        for dq in range(-half, half + 1):
            acc += float(power[(p_pk + dp) % N_U, (q_pk + dq) % N_V])
    return acc / total


def test_window_hann_concentrates_leakage_directional():
    """离栅倾斜平面波（有限扫描窗硬截断）：Hann 谱集中度显著高于矩形。"""
    p0f, q0f = 7.5, 3.5  # 分数 bin（离栅）→ 矩形窗 sinc 泄漏可见
    kx0 = 2.0 * np.pi * p0f / (N_U * DU)
    ky0 = 2.0 * np.pi * q0f / (N_V * DV)
    assert np.sqrt(kx0**2 + ky0**2) < K  # 传播分量（测试自检）
    x = np.arange(N_U)[:, None] * DU
    y = np.arange(N_V)[None, :] * DV
    e_near = np.exp(-1j * (kx0 * x + ky0 * y))
    conc_rect = _spectral_concentration(np.fft.fft2(e_near))
    conc_hann = _spectral_concentration(np.fft.fft2(e_near * _hann_2d()))
    assert conc_hann > 0.98
    # 方向性余量按实测标定（96×96 网格 δ=0.5 bin 实测：Hann ~0.999 vs 矩形
    # ~0.84，余量 0.15 量级——0.5×5bin 二维盒比一维 sinc 估计多收泄漏）
    assert conc_hann > conc_rect + 0.1


def test_window_energy_ratio_directional_and_shape_pin():
    """Hann 能量比 < 矩形（窗缘削蚀）；带窗往返 rel_err = ‖(1−w)E‖/‖E‖ 形态钉。"""
    e_ap = _bandlimited_aperture()
    e_near = aperture_to_near_field(e_ap, DU, DV, D_M, F_HZ)["e_near"]
    r_none = near_field_to_aperture(e_near, DU, DV, D_M, F_HZ)
    r_hann = near_field_to_aperture(e_near, DU, DV, D_M, F_HZ, window="hann")
    assert r_hann["window"] == "hann"
    assert r_hann["energy_ratio"] < r_none["energy_ratio"]

    rt = roundtrip_identity(e_near, DU, DV, D_M, F_HZ, window="hann")
    # 带窗往返重建严格 = w·E_near（同算子族互逆 + 窗只在分析方向）
    w = _hann_2d()
    expected = float(np.linalg.norm((1.0 - w) * e_near) / np.linalg.norm(e_near))
    assert rt["passed"] is False
    assert rt["rel_err"] > 1e-6
    assert abs(rt["rel_err"] - expected) <= 1e-6 * expected


# ─── 奈奎斯特守卫 ────────────────────────────────────────────────────────────

def test_nyquist_guard_ok_boundary_and_violated():
    """满足（λ/3）/边界（==λ/2）/违反（0.75λ）三态；max_du_allowed = λ/2。"""
    res_ok = nyquist_guard(DU, D_M, F_HZ)
    assert res_ok["ok"] is True
    assert abs(res_ok["max_du_allowed"] - LAM / 2.0) <= 1e-15 * LAM
    assert isinstance(res_ok["note"], str) and res_ok["note"]

    res_boundary = nyquist_guard(LAM / 2.0, D_M, F_HZ)
    assert res_boundary["ok"] is True

    res_bad = nyquist_guard(0.75 * LAM, D_M, F_HZ)
    assert res_bad["ok"] is False
    assert abs(res_bad["max_du_allowed"] - LAM / 2.0) <= 1e-15 * LAM
    assert isinstance(res_bad["note"], str) and res_bad["note"]


def test_nyquist_guard_distance_independent():
    """判据与扫描距离 d 无关（λ/2 为任意距离保守口径；d 仅进 note 语境）。"""
    base = nyquist_guard(DU, D_M, F_HZ)
    far = nyquist_guard(DU, 10.0 * LAM, F_HZ)
    assert far["max_du_allowed"] == base["max_du_allowed"]
    assert far["ok"] is True


# ─── 守卫全组 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "bad_e",
    [
        np.zeros((4, 4), dtype=bool),
        np.array([[1.0, np.nan], [0.0, 0.0]]),
        np.array([[1.0, np.inf], [0.0, 0.0]]),
        np.zeros(4),
        np.zeros((2, 2, 2)),
        np.array([["a", "b"], ["c", "d"]]),
    ],
)
def test_guard_e_near_rejections(bad_e):
    """场入参守卫：bool/NaN/Inf/一维/三维/非数值一律 ValueError。"""
    with pytest.raises(ValueError, match="e_near"):
        near_field_to_aperture(bad_e, DU, DV, D_M, F_HZ)


@pytest.mark.parametrize(
    "field_name, bad_value",
    [
        ("du_m", 0.0),
        ("du_m", -1.0),
        ("du_m", True),
        ("du_m", float("nan")),
        ("du_m", float("inf")),
        ("du_m", np.array([1.0, 2.0])),
        ("du_m", "0.01"),
        ("dv_m", 0.0),
        ("dv_m", float("nan")),
        ("d_m", -0.1),
        ("d_m", True),
        ("f_hz", 0.0),
        ("f_hz", -5.0),
        ("f_hz", float("nan")),
    ],
)
def test_guard_scalar_rejections_near_to_aperture(field_name, bad_value):
    """标量入参守卫：零/负/bool/非有限/非标量/非数值一律 ValueError。"""
    kwargs = {"du_m": DU, "dv_m": DV, "d_m": D_M, "f_hz": F_HZ}
    kwargs[field_name] = bad_value
    with pytest.raises(ValueError, match=field_name):
        near_field_to_aperture(np.zeros((8, 8), dtype=complex), **kwargs)


def test_guard_window_name():
    """窗名守卫：非法窗名 ValueError；支持集合恰为 none/hann。"""
    with pytest.raises(ValueError, match="window"):
        near_field_to_aperture(
            np.zeros((8, 8), dtype=complex), DU, DV, D_M, F_HZ, window="hamming"
        )
    with pytest.raises(ValueError, match="window"):
        roundtrip_identity(
            np.zeros((8, 8), dtype=complex), DU, DV, D_M, F_HZ, window="kaiser"
        )
    assert WINDOW_CHOICES == ("none", "hann")


def test_guard_aperture_to_near_field_rejections():
    """正变换守卫抽检：bool 场 / f=0 拒收。"""
    with pytest.raises(ValueError, match="e_aperture"):
        aperture_to_near_field(np.zeros((4, 4), dtype=bool), DU, DV, D_M, F_HZ)
    with pytest.raises(ValueError, match="f_hz"):
        aperture_to_near_field(np.zeros((4, 4), dtype=complex), DU, DV, D_M, 0.0)


def test_real_input_upcast_and_d_zero_allowed():
    """实数场按虚部为零转复数（与显式复数输入同结果）；d=0 合法（退化为低通）。"""
    e_real = np.abs(_bandlimited_aperture()) + 0.5
    out_real = near_field_to_aperture(e_real, DU, DV, D_M, F_HZ)
    out_cplx = near_field_to_aperture(e_real.astype(complex), DU, DV, D_M, F_HZ)
    assert np.iscomplexobj(out_real["e_aperture"])
    np.testing.assert_allclose(
        out_real["e_aperture"], out_cplx["e_aperture"], rtol=0.0, atol=0.0
    )
    out_d0 = near_field_to_aperture(e_real.astype(complex), DU, DV, 0.0, F_HZ)
    assert out_d0["e_aperture"].shape == e_real.shape


def test_all_zero_field_degenerate_but_legal():
    """全零场（合法入参）：不炸，energy_ratio 如实 NaN、渐逝计数 0。"""
    res = near_field_to_aperture(np.zeros((8, 8), dtype=complex), DU, DV, D_M, F_HZ)
    assert res["evanescent_count"] == 0
    assert np.isnan(res["energy_ratio"])
    rt = roundtrip_identity(np.zeros((8, 8), dtype=complex), DU, DV, D_M, F_HZ)
    assert rt["rel_err"] == 0.0
    assert rt["passed"] is True


# ─── c-stream-residual 规格钉：均匀口 sinc 锚 + 余弦锥削带相位回收 ──────────

_N_A = 24  # 均匀矩形口每轴样本数（24×λ/3 = 8λ 口宽；栅对齐整数样本）


def _uniform_rect_aperture() -> np.ndarray:
    """栅对齐均匀矩形口（整数样本数、居中）：幅度 1、零相位。"""
    e = np.zeros((N_U, N_V), dtype=complex)
    m0 = (N_U - _N_A) // 2
    e[m0 : m0 + _N_A, m0 : m0 + _N_A] = 1.0
    return e


def _dirichlet_magnitude(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """栅对齐矩形口 DFT 幅度的精确闭式（几何级数求和，与被测实现独立）。

    |P[p,q]| = |sin(π p N_a/N)/sin(π p/N)|·|sin(π q N_b/N)/sin(π q/N)|；
    p=0（或 q=0）取极限 N_a（N_b）。口位置只进相位，幅度与位置无关。
    """

    def _factor(idx: np.ndarray, n_samples: int) -> np.ndarray:
        num = np.sin(np.pi * idx * n_samples / N_U)
        den_safe = np.where(idx == 0, 1.0, np.sin(np.pi * idx / N_U))
        ratio = np.abs(num / den_safe)
        return np.where(idx == 0, float(n_samples), ratio)

    return _factor(p, _N_A) * _factor(q, _N_A)


def _sinc_norm(idx: np.ndarray) -> np.ndarray:
    """连续 |sinc| 归一形状 |sin(π x)/(π x)|，x = idx·N_a/N（idx=0 → 1）。"""
    x = np.pi * idx * _N_A / N_U
    x_safe = np.where(idx == 0, 1.0, x)
    return np.where(idx == 0, 1.0, np.abs(np.sin(x) / x_safe))


def test_uniform_rect_aperture_sinc_spectrum_anchor():
    """均匀矩形口角谱（远场方向图形状，斜投影因子另计）= 离散 sinc 形状锚。

    三层：① |FFT2| 与几何级数精确闭式逐 bin 一致（rtol 1e-7，零 bin 用
    atol=1e-9×峰覆盖 ~1e-13×峰 舍入尾）；② 栅上零点 bin（π p N_a/N=mπ
    ⟺ p=4m，整数恰落栅）深 ≤1e-10×峰；③ 传播区低角 bin（p,q≤12，k⊥≤
    0.375k）对连续 sinc 贴近 ≤0.03——Dirichlet/sinc 离散校正因子
    c(p)=(π p/N)/sin(π p/N) 在 p≤12 上 ≤1.027，容差如实声明。
    """
    measured = np.abs(np.fft.fft2(_uniform_rect_aperture()))
    p = np.arange(N_U)[:, None]
    q = np.arange(N_V)[None, :]
    expected = _dirichlet_magnitude(p, q)
    peak = float(expected[0, 0])
    np.testing.assert_allclose(measured, expected, rtol=1e-7, atol=1e-9 * peak)
    for m in (1, 2, 3):
        assert measured[4 * m, 0] <= 1e-10 * peak
        assert measured[0, 4 * m] <= 1e-10 * peak
    norm_meas = measured / peak
    norm_sinc = _sinc_norm(p) * _sinc_norm(q)
    keep = (p <= 12) & (q <= 12)
    max_dev = float(np.max(np.abs(norm_meas[keep] - norm_sinc[keep])))
    assert max_dev <= 0.03


def _cosine_taper_tilted_bandlimited() -> tuple[np.ndarray, tuple[int, int]]:
    """余弦锥削口（可分离 cos 锥削）× 栅上相位倾斜 → 谱带限 0.8k。

    幅度+相位兼备：锥削包络供幅度裁判、栅上倾斜供相位裁判；带限化与既有
    fixture 同 device（谱硬截断到 0.8k 圆盘），使逆变换渐逝置零为 no-op、
    回收门干净。返回（真值口径场, 倾斜 bin (p0,q0)）。
    """
    x = np.arange(N_U)[:, None] * DU
    y = np.arange(N_V)[None, :] * DV
    xc = (N_U - 1) * DU / 2.0
    yc = (N_V - 1) * DV / 2.0
    half = _N_A * DU / 2.0  # 8λ 支撑宽（cos 在支撑缘为零，中心为 1）
    taper = np.where(
        np.abs(x - xc) <= half, np.cos(np.pi * (x - xc) / (2.0 * half)), 0.0
    ) * np.where(
        np.abs(y - yc) <= half, np.cos(np.pi * (y - yc) / (2.0 * half)), 0.0
    )
    p0, q0 = 7, 3
    kx0 = 2.0 * np.pi * p0 / (N_U * DU)
    ky0 = 2.0 * np.pi * q0 / (N_V * DV)
    assert np.sqrt(kx0**2 + ky0**2) < K  # 传播倾斜（测试自检，同既有锚）
    e = taper.astype(complex) * np.exp(-1j * (kx0 * x + ky0 * y))
    spec = np.fft.fft2(e)
    kx = 2.0 * np.pi * np.fft.fftfreq(N_U, d=DU)
    ky = 2.0 * np.pi * np.fft.fftfreq(N_V, d=DV)
    mask = (kx[:, None] ** 2 + ky[None, :] ** 2) <= (0.8 * K) ** 2
    e_bl = np.fft.ifft2(spec * mask)
    return e_bl / np.linalg.norm(e_bl), (p0, q0)


def test_cosine_taper_aperture_amplitude_phase_recovery():
    """余弦锥削+相位倾斜口径：正传→反演→口径场回收（任务书预声明 1e-3 量级）。

    回收须同时复现幅度（锥削包络）与相位（倾斜线性相位）：带限 fixture 下
    渐逝置零为 no-op，回收达机器精度（门 1e-10，实测 ~1e-15，远优于预声明
    的 1e-3 量级）；谱峰恰落倾斜 bin（相位存在性方向钉）；
    evanescent_count==0（带限，置零 no-op）。
    """
    e_ref, (p0, q0) = _cosine_taper_tilted_bandlimited()
    e_near = aperture_to_near_field(e_ref, DU, DV, D_M, F_HZ)["e_near"]
    inv = near_field_to_aperture(e_near, DU, DV, D_M, F_HZ)
    e_rec = inv["e_aperture"]
    rel = float(np.linalg.norm(e_rec - e_ref) / np.linalg.norm(e_ref))
    assert rel <= 1e-10
    assert inv["evanescent_count"] == 0
    # 相位存在性：谱峰恰落倾斜谱坐标。物理倾斜 exp(−j k0·r)（与既有锚及
    # 模块 e^{+jωt}/exp(−jk·r) 约定一致）在 numpy DFT（核 exp(−2πi pm/N)）
    # 下峰位于共轭 bin (N−p0, N−q0)——fftfreq 坐标 −kx0，物理谱坐标 kx0 的
    # numpy 记账镜像（符号约定，非物理差异）。
    spec_rec = np.fft.fft2(e_rec)
    p_pk, q_pk = np.unravel_index(int(np.argmax(np.abs(spec_rec))), e_rec.shape)
    assert (p_pk, q_pk) == (N_U - p0, N_V - q0)
