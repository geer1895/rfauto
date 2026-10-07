"""M-2.2 口径全息反演核：平面近场 → 口径场 FFT 反演 + 加窗。

职责（铁律 7：数值只在确定性内核；本模块 = 纯 numpy 叶子，零 IO、不进
注册表，不 import 本仓求解器/正变换面——nf2ff 正变换（core/nf_transform.py）
仅作同族口径只读参考）：
- ``near_field_to_aperture``：z=d 扫描面 u×v 复近场 → 二维 FFT → 平面波谱
  P(kx,ky) → 反向传播因子 exp(+jkz·d) → IFFT → 口径场 E_ap(x,y)（z=0）；
  渐逝分量（kx²+ky²>k²）置零+计数；
- ``aperture_to_near_field``：对偶正变换（同一算子族，正逆共用核——
  往返恒等测试的基础）；渐逝分量按物理衰减 exp(−α·d) 保留、不置零；
- ``roundtrip_identity``：near→aperture→near 往返恒等（≤1e-12 门，
  无窗无渐逝截断条件下；含窗/含渐逝时 rel_err 如实报告不虚判）；
- ``nyquist_guard``：采样间距逐轴判据 du ≤ π/k = λ/2。

物理口径（平面波谱/角谱法，e^{+jωt} 时谐约定，前向波 exp(−jk·r)，全 SI，
k=2π/λ）——逐式出处见下"出处"节：

- 谱综合式（离散，numpy DFT 网格 kx_p = 2π·fftfreq(M, du)）::

      P[p,q]    = FFT2{ E[·,·; z=0] }
      E[m,n; z] = IFFT2{ P[p,q] · exp(−j·kz(p,q)·z) }
      kz = sqrt(k² − kx² − ky²)（传播分量取正实根）

  kz 只依赖 kx²+ky²，故 DFT 频率轴符号约定不影响传播因子（算子自洽）。

- 渐逝截止：kx²+ky²>k² 时 kz = −jα（α = sqrt(kx²+ky²−k²)）——正行进
  （口径 z=0 → 近场 z=d）因子 exp(−α·d) 衰减（正变换如实保留）；反向
  传播因子 exp(+α·d) 指数放大（噪声/泄漏灾难）→ 逆变换置零+计数
  （谱域低通正则化）。

- ``evanescent_count`` 语义：分析谱中幅度超过相对地板（1e-12×谱峰）的
  渐逝 bin 数——即本次变换被置零（逆）/被衰减（正）的**实际谱分量数**。
  纯几何 bin 计数（kx²+ky²>k² 的网格点数）对空谱无物理意义，不采用；
  地板 1e-12 与 FFT 舍入尾（~1e-14 相对量级）间留 100× 余量。

- 加窗：有限扫描窗硬截断 → 谱泄漏（矩形窗锐边 sinc 旁瓣）——Hann 可
  分离窗 w[m,n] = hann(M)[m]·hann(N)[n] 抑制（与本仓正变换
  nf_transform.py 同族实践）；窗只作用于近场分析方向（测量域）。
  往返恒等因此仅在 window="none" 下成立；带窗往返重建严格等于
  w·E_near（同算子族互逆的直接推论），rel_err 形态 = ‖(1−w)·E‖/‖E‖
  （解析可预期，测试钉死）。

- 能量诊断 ``energy_ratio`` = 输出面/输入面离散能量比：Parseval 恒等下
  无窗无置零 == 1（浮点 ~1e-16）；带窗 ≈ Σ|w·E|²/Σ|E|²（窗缘削蚀）；
  含渐逝置零 = 1 − 渐逝能量份额。截断/正则化损失如实可见，不凑 1。

- 采样判据（逐轴独立适用）：采样谱支撑 |kx| ≤ π/du 必须覆盖传播支撑
  |kx| ≤ k ⟺ du ≤ π/k = λ/2；扫描距离 d>0 处渐逝分量已衰减（有效带宽
  收窄），λ/2 对任意 d 为保守 canonical 判据。

出处（等级如实标注，2026-09-26 实测可达性）：

- 任务书指定出处 JPL DESCANSO Monograph Series Report 10（W. A. Imbriale,
  "Large Antennas of the Deep Space Network", Wiley 2003）Ch.8 "Antenna
  Calibration"（Rochblatt 等，微波全息计量 MHM：远场幅相 → 口径场逆
  变换 → 反射面/单元级误差图）——本环境今日实测 descanso.jpl.nasa.gov
  WebFetch 超时 + web_reader 403，**公式级不可达**（monograph 身份经
  检索确认：series10 = Imbriale 专著、ch8 = 天线校准/全息计量章）。
  按任务书预案降级为公开教材双源，公式级出处：
  * D. M. Kerns, "Plane-Wave Scattering-Matrix Theory of Antennas and
    Antenna-Antenna Interactions", NBS Monograph 162 (1981) §2.3——平面
    波谱展开、传播因子与渐逝截止（本仓 core/nf_transform.py 正变换同族
    口径，时谐约定一致）；
  * J. W. Goodman, "Introduction to Fourier Optics" 3rd ed., §3.8——角谱
    传递函数、渐逝波衰减与反向传播病态性（Goodman 用 e^{−jωt}/
    exp(+jkz·z)，与本模块 e^{+jωt}/exp(−jkz·z) 互为共轭，逐式换算一致）；
  以上两源独立一致（双源）。单源项逐条标注：Hann 窗谱泄漏抑制为经典
  单源 F. J. Harris, "On the Use of Windows for Harmonic Analysis with
  the Discrete Fourier Transform", Proc. IEEE 66(1), 1978；采样判据
  du ≤ λ/2 为本模块自推导（谱支撑覆盖论证），与 Kerns §2.3 采样口径
  一致。
- 月计划引用的 He 2021 激励误差校准综述（IEEE，docs/monthly_enhancement_plan_
  20260926.md 引文[35]，M-2 行"在线校准口径"）：2026-09-29 多轮 web 检索无题录级
  命中，**公式级不可达**（c-stream-residual 批实测）——本模块按预案落在上述经典
  ASM 双源口径；He 2021 在线校准语义（与互耦 poke 协议对齐）留硬件批接地。
- 形状/守卫约定对齐兄弟件 core/array_calib.py（M-2.1：实数输入按虚部为
  零转复数；bool/NaN/Inf/非二维拒收；数值标量显式拒收 bool）。

接线说明：本模块为 core 隔离件，array_service holography/calibrate 端点
挂接留后续批次（规格见 研究扩充 §三 M-2）。
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "C0",
    "EVANESCENT_FLOOR",
    "ROUNDTRIP_TOL",
    "WINDOW_CHOICES",
    "aperture_to_near_field",
    "near_field_to_aperture",
    "nyquist_guard",
    "roundtrip_identity",
]

#: 真空波速（m/s，与仓内 nf_transform/openEMS 模板同源常数）
C0 = 299792458.0

#: 往返恒等门（任务书 M-2 判据③：NF 正逆变换往返恒等 ≤1e-12，合成口径场）
ROUNDTRIP_TOL = 1e-12

#: 渐逝分量计数相对地板（×谱峰）：低于该幅度的渐逝 bin 视为 FFT 舍入尾
#: 不计入（与典型舍入尾 ~1e-14 间留 100× 余量）
EVANESCENT_FLOOR = 1e-12

#: 支持窗族（作用于近场分析方向两轴的可分离乘积）
WINDOW_CHOICES = ("none", "hann")

_TWO_PI = 2.0 * np.pi


# ─── 守卫（对齐 array_calib.py 口径） ────────────────────────────────────────

def _as_complex_2d(x: object, name: str) -> np.ndarray:
    """校验并转换为二维复数场；bool/非数值/非二维/NaN/Inf 拒收（实数转复数）。"""
    arr = np.asarray(x)
    if arr.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，拒绝（数值入参不得含 bool）")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值数组，得到 dtype={arr.dtype}")
    arr = arr.astype(complex)
    if arr.ndim != 2:
        raise ValueError(f"{name} 必须是二维 (n_u, n_v) 采样场，得到 ndim={arr.ndim}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf，拒绝")
    return arr


def _scalar_float(x: object, name: str, *, minimum: float, allow_zero: bool) -> float:
    """校验标量数值参数：bool/非数值/非标量/非有限/越下界一律拒收。

    minimum+allow_zero=False → 严格 >minimum；allow_zero=True → ≥minimum。
    """
    if isinstance(x, (bool, np.bool_)):
        raise ValueError(f"{name} 是 bool，拒绝（float(True)=1.0 静默污染，显式拒收）")
    arr = np.asarray(x)
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值，得到 dtype={arr.dtype}")
    if arr.size != 1:
        raise ValueError(f"{name} 必须是标量，得到 size={arr.size}")
    value = float(arr.reshape(()))
    if not np.isfinite(value):
        raise ValueError(f"{name} 必须有限，得到 {value}")
    if allow_zero:
        if value < minimum:
            raise ValueError(f"{name} 必须 ≥ {minimum}，得到 {value}")
    elif value <= minimum:
        raise ValueError(f"{name} 必须 > {minimum}，得到 {value}")
    return value


def _validate_window(window: object) -> str:
    """窗名守卫：必须是 WINDOW_CHOICES 之一。"""
    if not isinstance(window, str) or window not in WINDOW_CHOICES:
        raise ValueError(f"window 必须是 {WINDOW_CHOICES} 之一，得到 {window!r}")
    return window


# ─── 谱网格与传播算子 ────────────────────────────────────────────────────────

def _kz_grid(
    du: float, dv: float, shape: tuple[int, int], k: float
) -> tuple[np.ndarray, np.ndarray]:
    """谱网格 kz(p,q) 与渐逝掩码。

    kx_p = 2π·fftfreq(n_u, du)、ky_q = 2π·fftfreq(n_v, dv)；kz = sqrt(k²−k⊥²)
    （传播分量正实根）；渐逝（k⊥²>k²）取 kz = −jα（α = sqrt(k⊥²−k²)，
    正行进 exp(−αz) 衰减的根）。返回 (kz 复二维, evanescent bool 二维)。
    """
    n_u, n_v = shape
    kx = _TWO_PI * np.fft.fftfreq(n_u, d=du)
    ky = _TWO_PI * np.fft.fftfreq(n_v, d=dv)
    if not (np.all(np.isfinite(kx)) and np.all(np.isfinite(ky))):
        raise ValueError("采样间距过小导致谱网格非有限（du/dv 与 1/f 量级失配），拒绝")
    k_perp_sq = kx[:, None] ** 2 + ky[None, :] ** 2
    evanescent = k_perp_sq > k * k
    kz = np.sqrt(np.maximum(k * k - k_perp_sq, 0.0)).astype(complex)
    kz[evanescent] = -1j * np.sqrt(k_perp_sq[evanescent] - k * k)
    return kz, evanescent


def _hann_2d(n_u: int, n_v: int) -> np.ndarray:
    """可分离 Hann 窗 w[m,n] = hann(M)[m]·hann(N)[n]（对称窗，谱泄漏抑制）。"""
    return np.hanning(n_u)[:, None] * np.hanning(n_v)[None, :]


def _evanescent_content_count(
    spectrum: np.ndarray, evanescent: np.ndarray
) -> int:
    """内容感知渐逝计数：幅度 > EVANESCENT_FLOOR×谱峰 的渐逝 bin 数。

    谱峰为 0（全零场）时无内容可数，返回 0。
    """
    if not np.any(evanescent):
        return 0
    peak = float(np.max(np.abs(spectrum)))
    if peak <= 0.0:
        return 0
    return int(np.count_nonzero(np.abs(spectrum[evanescent]) > EVANESCENT_FLOOR * peak))


# ─── 逆变换：近场 → 口径（全息反演主入口） ──────────────────────────────────

def near_field_to_aperture(
    e_near: np.ndarray,
    du_m: float,
    dv_m: float,
    d_m: float,
    f_hz: float,
    window: str = "none",
) -> dict[str, object]:
    """平面近场 → 口径场反演：P=FFT2{E_near}，E_ap=IFFT2{P·exp(+jkz·d)}。

    算子链（出处见模块 docstring"出处"节；逐式：谱综合式 Kerns NBS 162
    §2.3 + Goodman 3rd §3.8 双源；渐逝置零 = 反向传播病态性正则化，
    Goodman §3.8，反向因子 exp(+α·d) 放大噪声故低通截止）：

    1. 分析（含可选 Hann 窗抑制有限扫描窗泄漏）：P = FFT2{w·E_near}；
    2. 反向传播：传播分量 ×exp(+jkz·d)（kz 正实根，纯相位）；
       渐逝分量置零（计数见 EVANESCENT_FLOOR 语义）；
    3. 综合：E_ap = IFFT2{...}，口径场定义在与近场同一 u×v 横向网格
       （z=0 平面，横向配准 1:1——平面近场全息的标准假设）。

    形状/单位约定：e_near shape (n_u, n_v) 复数（实数按虚部为零转复数，
    bool/NaN/Inf 拒收）；du_m/dv_m 采样间距（m，>0）；d_m 近场面到口径面
    距离（m，≥0，d=0 时退化为谱域低通）；f_hz 频率（Hz，>0）；全 SI。

    返回 dict：
    - ``e_aperture``：复口径场，shape 同 e_near；
    - ``evanescent_count``：被置零的渐逝谱分量数（内容感知，见模块注释）；
    - ``energy_ratio``：口径能量/近场能量（Parseval 下无窗无置零 == 1，
      带窗/置零 <1——截断诊断，如实不凑 1；全零场返回 NaN）；
    - ``window``：生效窗名。
    """
    e = _as_complex_2d(e_near, "e_near")
    du = _scalar_float(du_m, "du_m", minimum=0.0, allow_zero=False)
    dv = _scalar_float(dv_m, "dv_m", minimum=0.0, allow_zero=False)
    d = _scalar_float(d_m, "d_m", minimum=0.0, allow_zero=True)
    f = _scalar_float(f_hz, "f_hz", minimum=0.0, allow_zero=False)
    win = _validate_window(window)

    k = _TWO_PI * f / C0
    kz, evanescent = _kz_grid(du, dv, e.shape, k)

    e_analysis = e * _hann_2d(*e.shape) if win == "hann" else e
    spectrum = np.fft.fft2(e_analysis)

    # 反向传播因子：传播分量纯相位 exp(+jkz·d)；渐逝分量置零（只在传播
    # 分量上取 exp，避免 exp(α·d) 溢出告警）
    w_inv = np.zeros(e.shape, dtype=complex)
    w_inv[~evanescent] = np.exp(1j * kz[~evanescent] * d)

    e_aperture = np.fft.ifft2(spectrum * w_inv)

    near_energy = float(np.sum(np.abs(e) ** 2))
    ap_energy = float(np.sum(np.abs(e_aperture) ** 2))
    energy_ratio = ap_energy / near_energy if near_energy > 0.0 else float("nan")

    return {
        "e_aperture": e_aperture,
        "evanescent_count": _evanescent_content_count(spectrum, evanescent),
        "energy_ratio": energy_ratio,
        "window": win,
    }


# ─── 正变换（对偶）：口径 → 近场 ─────────────────────────────────────────────

def aperture_to_near_field(
    e_aperture: np.ndarray,
    du_m: float,
    dv_m: float,
    d_m: float,
    f_hz: float,
) -> dict[str, object]:
    """口径场 → 近场正变换（对偶算子）：E_near = IFFT2{FFT2{E_ap}·exp(−jkz·d)}。

    与 ``near_field_to_aperture`` 共用同一算子族（往返恒等测试的基础）。
    渐逝分量按物理衰减 exp(−α·d) 如实保留、不置零（正向传播是良态的）；
    正变换无窗（加窗是测量域/分析方向的操作）。

    出处：谱综合式与传播因子同 near_field_to_aperture（Kerns NBS 162
    §2.3 + Goodman 3rd §3.8 双源）。

    返回 dict：
    - ``e_near``：z=d 平面复近场，shape 同 e_aperture；
    - ``evanescent_count``：口径谱中幅度超地板的渐逝分量数（被衰减保留，
      不置零——仅诊断）；
    - ``energy_ratio``：近场能量/口径能量（渐逝衰减使其 ≤1；全零场 NaN）。
    """
    e = _as_complex_2d(e_aperture, "e_aperture")
    du = _scalar_float(du_m, "du_m", minimum=0.0, allow_zero=False)
    dv = _scalar_float(dv_m, "dv_m", minimum=0.0, allow_zero=False)
    d = _scalar_float(d_m, "d_m", minimum=0.0, allow_zero=True)
    f = _scalar_float(f_hz, "f_hz", minimum=0.0, allow_zero=False)

    k = _TWO_PI * f / C0
    kz, evanescent = _kz_grid(du, dv, e.shape, k)

    # 正向传播因子：传播分量 exp(−jkz·d)（纯相位）；渐逝分量 exp(−α·d)
    # 衰减（kz=−jα → −j·kz·d = −α·d；可安全下溢为 0，numpy underflow 缺省
    # 静默，不产生告警）
    w_fwd = np.empty(e.shape, dtype=complex)
    w_fwd[~evanescent] = np.exp(-1j * kz[~evanescent] * d)
    w_fwd[evanescent] = np.exp(kz[evanescent].imag * d)

    e_near = np.fft.ifft2(np.fft.fft2(e) * w_fwd)

    ap_energy = float(np.sum(np.abs(e) ** 2))
    near_energy = float(np.sum(np.abs(e_near) ** 2))
    energy_ratio = near_energy / ap_energy if ap_energy > 0.0 else float("nan")

    return {
        "e_near": e_near,
        "evanescent_count": _evanescent_content_count(np.fft.fft2(e), evanescent),
        "energy_ratio": energy_ratio,
    }


# ─── 往返恒等门 ──────────────────────────────────────────────────────────────

def roundtrip_identity(
    e_near: np.ndarray,
    du_m: float,
    dv_m: float,
    d_m: float,
    f_hz: float,
    window: str = "none",
) -> dict[str, object]:
    """near→aperture→near 往返恒等：门 ≤1e-12（无窗、谱无渐逝内容条件下）。

    数学条件：正逆算子互逆 ⟺ exp(+jkz·d)·exp(−jkz·d)=1 对传播分量恒成立
    （浮点内 ~1e-15）；以下两类偏差为**刻意行为**而非误差，如实进 rel_err：
    1. window != "none"：往返重建 = w·E_near（窗是分析方向的测量操作），
       rel_err = ‖(1−w)·E‖/‖E‖（解析形态，测试钉死）；
    2. 谱含渐逝内容：逆变换置零后正变换无法复原，rel_err ≈ 渐逝能量
       份额 sqrt（Parseval）。

    返回 dict：
    - ``max_abs_err``：逐点最大复模偏差（max |E_rec − E|）；
    - ``rel_err``：Frobenius 相对偏差 ‖Δ‖/‖E‖（全零场且偏差 0 → 0.0，
      全零场有偏差 → inf）；
    - ``passed``：rel_err ≤ ROUNDTRIP_TOL（1e-12）。判据条件（无窗无渐逝）
      之外调用方应读 rel_err 形态而非 passed。
    """
    e0 = _as_complex_2d(e_near, "e_near")
    inv = near_field_to_aperture(e0, du_m, dv_m, d_m, f_hz, window=window)
    fwd = aperture_to_near_field(inv["e_aperture"], du_m, dv_m, d_m, f_hz)
    e_rec = fwd["e_near"]

    diff = e_rec - e0
    max_abs_err = float(np.max(np.abs(diff)))
    base = float(np.sqrt(np.sum(np.abs(e0) ** 2)))
    if base > 0.0:
        rel_err = float(np.sqrt(np.sum(np.abs(diff) ** 2)) / base)
    else:
        rel_err = 0.0 if max_abs_err == 0.0 else float("inf")
    return {
        "max_abs_err": max_abs_err,
        "rel_err": rel_err,
        "passed": bool(rel_err <= ROUNDTRIP_TOL),
    }


# ─── 采样判据守卫 ────────────────────────────────────────────────────────────

def nyquist_guard(du_m: float, d_m: float, f_hz: float) -> dict[str, object]:
    """奈奎斯特采样守卫（逐轴）：du ≤ π/k = λ/2。

    判据推导（自推导，与 Kerns NBS 162 §2.3 采样口径一致，单源标注）：
    采样谱支撑 |kx| ≤ π/du 必须覆盖传播支撑 |kx| ≤ k ⟺ du ≤ π/k = λ/2。
    与扫描距离 d 无关地保守成立（d>0 处渐逝分量已衰减、有效带宽更窄，
    λ/2 为 canonical 保守判据）；d_m 仅进 note 作语境记录。

    返回 dict：
    - ``ok``：du_m ≤ max_du_allowed；
    - ``max_du_allowed``：λ/2（m）；
    - ``note``：判据式与违反后果（高角谱分量混叠进传播域）说明；
      判据逐轴独立适用（dv 同式另行调用）。
    """
    du = _scalar_float(du_m, "du_m", minimum=0.0, allow_zero=False)
    d = _scalar_float(d_m, "d_m", minimum=0.0, allow_zero=True)
    f = _scalar_float(f_hz, "f_hz", minimum=0.0, allow_zero=False)

    lam = C0 / f
    max_du_allowed = lam / 2.0
    ok = bool(du <= max_du_allowed)
    if ok:
        note = (
            f"采样间距 du={du:.6g} m ≤ π/k=λ/2={max_du_allowed:.6g} m（f={f:.6g} Hz，"
            f"λ={lam:.6g} m），采样谱支撑 |kx|≤π/du 覆盖传播支撑 |kx|≤k，判据满足；"
            f"扫描距离 d={d:.6g} m 下渐逝分量已衰减，λ/2 为保守判据；判据逐轴适用"
            "（dv 同式另行调用）"
        )
    else:
        note = (
            f"采样间距 du={du:.6g} m > π/k=λ/2={max_du_allowed:.6g} m（f={f:.6g} Hz，"
            f"λ={lam:.6g} m），采样谱支撑不足，高角（|kx|>π/du 方向）传播分量将"
            f"混叠进低角谱域，反演结果不可信；判据逐轴适用（dv 同式另行调用）；"
            f"扫描距离 d={d:.6g} m 不改变该判据（λ/2 为任意距离下的保守口径）"
        )
    return {"ok": ok, "max_du_allowed": max_du_allowed, "note": note}
