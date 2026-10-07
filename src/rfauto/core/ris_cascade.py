"""NX-4 RIS 级联闭式表征包（研究扩充 round14 §四 :96-97）。

BS-RIS-UE 三段几何级联 + 无源波束指向角谱验证 + 挂 metasurface_lut 相位
量化损失，全部**纯函数零 IO**（numpy/math），单位口径 SI（m/Hz），返回值
JSON 可序列化（报告函数逐键 cast float）。零求解器依赖。

物理口径（出处）：
- **级联信道（product-distance 模型）**：单元 n 的复级联幅度
      a_n = Γ_n · e^{−jk(d1n+d2n)} / (d1n·d2n)
  （Γ_n=RIS 反射系数、d1n=|r_n−r_BS|、d2n=|r_n−r_UE|；各向同性单元
  单位增益口径，天线增益单独乘）。接收功率比
      P_rx/P_tx = Gt·Gr·(λ/4π)⁴·|Σ_n a_n|²。
- **路径损耗 ∝ N²（Björnson TWC 2020，远场）**：共轭匹配相位
  Γ_n=e^{+jk(d1n+d2n)} 下 |Σa_n|=Σ 1/(d1n·d2n)→N/(d1·d2)（远场），
  P_rx/P_tx = Gt·Gr·N²/(FSPL(d1)·FSPL(d2))——N² 律即
  L_cascade = FSPL(d1)+FSPL(d2)−20·log10(N)（coherence=1 时）。
  E. Björnson & Ö. T. Demir，"Intelligent Reflecting Surfaces: Myths,
  Realities, and the Path Ahead"（IEEE TWC 2020/综述口径）。
- **距离律**：级联双段指数 2+2=4（P∝1/(d1²d2²)）vs 直连 FSPL 指数 2；
  同参数下 RIS 链胜过直链的交叉直连距离
      d_cross = 4π·d1·d2/(N·λ)
  （令 N²/FSPL(d1)FSPL(d2) > 1/FSPL(d) 解出；d>d_cross 才划算——RIS
  是远场覆盖扩展工具，短距直链占优的经典结论）。
- **相位面**：共轭匹配相位 φ_n=k(d1n+d2n)（闭式对角化口径，逐元独立
  最优）；随机相位（独立均匀 [0,2π)）的功率增益期望 E|Σ a_n e^{jφ_n}|²
  =Σ a_n²（瑞利游走，交叉项期望为零）——共轭/随机相干增益比
      (Σa_n)²/Σa_n² = N_eff（等幅时恰为 N）
  即经典 "共轭 N² vs 随机 N、比值 N"。任务书量级「≥N·π²/4」：以随机
  基线 N 计，共轭 N² ≥ (π²/4)·N 于 N≥3 恒成立（π²/4≈2.47），锚树
  test_ris_cascade.py 按此两式分别钉（出处注 Björnson TWC 2020 N² 律）。
- **指向角谱验证**：散射远场角谱 A(û)=Σ_n e^{jφ_n}·e^{−jk(d1n−r_n·û)}
  （观测方向 û 球坐标网格）；共轭相位下谱峰应落在 UE 几何方向
  û_UE（远场 UE 时精确对齐；近场 UE 谱峰仍对准其方位角）。均匀阵
  −3dB 束宽锚：全宽 0.886λ/(N·d)/cosθ_peak，边界峰（θ=0）单侧栅格
  如实退为半宽 0.443λ/(N·d)（Balanis Ch.6 量级）。
- **量化损失挂接**：共轭相位经 core/metasurface_lut.quantize_phase_deg
  按 b-bit 栅格取整后重算 |Σa_n|，经验损失 dB 对拍解析
  metasurface_lut.quantization_loss_db(bits)=−10log10(sinc²(1/2^b))
  （均匀量化误差期望 E[e^{jε}]=sinc 的精确口径；经验值受相位栅格
  结构性误差扰动，大 N 收敛到解析带内）。
- **ETSI GR RIS 001（V1.1.1，"RIS; Communication models, methods, and
  use cases"，免费交付物/PV-020 已 verified）**：用例与 KPI 语义参照
  （RIS 辅助链路 path-loss 模型与 achievable-gain 语义）——仅语义
  引用，标准数值不抄录（上传零敏感/版权纪律）。

域与守卫：几何位置有限、单元到 BS/UE 距离 >0（重合显式拒绝）；
频率/距离正值；bits≥1 才量化（0=不量化）；随机相位固定种子可复现。
远场适用性按 Fraunhofer 2D²/λ 逐段标注（不 hard-fail——精确和在场时
近场本就是合法输入，闭式 N² 律越界使用才需要诚实标注）。

参考：研究扩充 round14 §四 :96-97；邻接
core/propagation.py（FSPL 4πd/λ 同口径）、core/array_synthesis.py
（阵因子口径）、core/metasurface_lut.py（量化损失）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.metasurface_lut import (
    quantization_loss_db as _ms_quantization_loss_db,
)
from rfauto.core.metasurface_lut import quantize_phase_deg

# 光速（SI 精确值，与 core/propagation.py/sat_link.py 同源口径）
C0_M_S = 299792458.0

__all__ = [
    "C0_M_S",
    "cascade_geometry_sum",
    "cascade_power_ratio",
    "coherent_vs_random_ratio",
    "conjugate_phases_rad",
    "crossover_direct_distance_m",
    "direct_power_ratio",
    "farfield_cascade_power_ratio",
    "farfield_validity",
    "fspl_db",
    "quantized_conjugate_loss_db",
    "random_gain_mc",
    "ris_cascade_report",
    "ris_positions_ura",
    "steering_spectrum",
]


# ─── 守卫助手（#140：PathLike 同源纪律——入参先收敛再校验）──────────────────


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收；0.0 合法性由各函数域守卫定）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 > 0，得 {out}")
    return out


def _int(value: Any, name: str, minimum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为整数（不接受 bool）")
    out = int(value)
    if out != value or out < minimum:
        raise ValueError(f"{name} 必须为 ≥{minimum} 的整数，得 {value!r}")
    return out


def _vec3(value: Any, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float).reshape(-1)
    if arr.size != 3 or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 必须是 3 元有限向量，得 {value!r}")
    return arr


def _positions(value: Any, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 3 or arr.shape[0] < 1:
        raise ValueError(f"{name} 必须是 (N,3) 有限数组，得 shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值")
    return arr


# ─── FSPL 与几何 ──────────────────────────────────────────────────────────────


def fspl_db(d_m: float, f_hz: float) -> float:
    """自由空间路损 [dB]：FSPL = 20·log10(4π·d/λ)（m/Hz 口径）。

    与 core/propagation.py 双径的 4πd/λ 形态、core/sat_link.py 的
    92.44778…+20log(f_GHz)+20log(d_km) 工程式数学恒等（单源常数各自
    独立复算互证）。域守卫 d>0、f>0。
    """
    d = _pos(d_m, "d_m")
    f = _pos(f_hz, "f_hz")
    lam = C0_M_S / f
    return 20.0 * math.log10(4.0 * math.pi * d / lam)


def ris_positions_ura(n_x: int, n_y: int, period_m: float) -> np.ndarray:
    """均匀矩形阵（URA）单元位置 (N,3)：z=0 口径面，中心对称铺排 [m]。

    x=(i−(n_x−1)/2)·period, y=(j−(n_y−1)/2)·period, z=0。
    """
    nx = _int(n_x, "n_x", 1)
    ny = _int(n_y, "n_y", 1)
    p = _pos(period_m, "period_m")
    xs = (np.arange(nx) - (nx - 1) / 2.0) * p
    ys = (np.arange(ny) - (ny - 1) / 2.0) * p
    xx, yy = np.meshgrid(xs, ys, indexing="ij")
    pos = np.stack([xx.ravel(), yy.ravel(), np.zeros(nx * ny)], axis=1)
    return pos


def _element_distances(
    positions_m: np.ndarray, terminal_m: np.ndarray, label: str
) -> np.ndarray:
    """各单元到端机距离 (N,)，重合（≤0）显式拒绝。"""
    d = np.linalg.norm(positions_m - terminal_m[np.newaxis, :], axis=1)
    if not np.all(np.isfinite(d)) or float(d.min()) <= 0.0:
        raise ValueError(
            f"{label} 与某 RIS 单元重合（距离必须 >0），min={float(d.min())!r}")
    return d


def conjugate_phases_rad(
    positions_m: np.ndarray,
    bs_pos_m: np.ndarray,
    ue_pos_m: np.ndarray,
    f_hz: float,
) -> np.ndarray:
    """共轭匹配反射相位 φ_n = k·(d1n+d2n) mod 2π [rad]（闭式对角化口径）。

    逐元消去双段传播相位 → |Σ a_n| 达上界 Σ 1/(d1n·d2n)（等价于对级联
    信道矩阵做逐元共轭匹配；BS/UE 同侧 +z 为物理反射面惯例，本闭式
    不强制——越侧几何如实计算并在报告里标注）。
    """
    pos = _positions(positions_m, "positions_m")
    bs = _vec3(bs_pos_m, "bs_pos_m")
    ue = _vec3(ue_pos_m, "ue_pos_m")
    f = _pos(f_hz, "f_hz")
    k = 2.0 * math.pi * f / C0_M_S
    d1 = _element_distances(pos, bs, "bs_pos_m")
    d2 = _element_distances(pos, ue, "ue_pos_m")
    return np.mod(k * (d1 + d2), 2.0 * math.pi)


# ─── 级联信道与接收功率 ───────────────────────────────────────────────────────


def cascade_geometry_sum(
    positions_m: np.ndarray,
    bs_pos_m: np.ndarray,
    ue_pos_m: np.ndarray,
    f_hz: float,
    phases_rad: np.ndarray | None = None,
) -> complex:
    """级联信道几何和 h̃ = Σ_n Γ_n·e^{−jk(d1n+d2n)}/(d1n·d2n)（无量纲）。

    phases_rad=None 时取全零相位（裸级联）；共轭匹配下 |h̃| 精确等于
    Σ 1/(d1n·d2n)（相位逐元对消恒等式，锚树独立路径复核）。
    """
    pos = _positions(positions_m, "positions_m")
    bs = _vec3(bs_pos_m, "bs_pos_m")
    ue = _vec3(ue_pos_m, "ue_pos_m")
    f = _pos(f_hz, "f_hz")
    k = 2.0 * math.pi * f / C0_M_S
    d1 = _element_distances(pos, bs, "bs_pos_m")
    d2 = _element_distances(pos, ue, "ue_pos_m")
    ph = np.zeros(pos.shape[0]) if phases_rad is None else np.asarray(
        phases_rad, dtype=float).reshape(-1)
    if ph.size != pos.shape[0]:
        raise ValueError(
            f"phases_rad 长度 {ph.size} ≠ 单元数 {pos.shape[0]}")
    return complex(np.sum(np.exp(-1j * k * (d1 + d2) + 1j * ph) / (d1 * d2)))


def cascade_power_ratio(
    positions_m: np.ndarray,
    bs_pos_m: np.ndarray,
    ue_pos_m: np.ndarray,
    f_hz: float,
    phases_rad: np.ndarray | None = None,
    gt_db: float = 0.0,
    gr_db: float = 0.0,
) -> float:
    """RIS 级联接收功率比 P_rx/P_tx（精确逐元和，近场有效）。

    P_rx/P_tx = Gt·Gr·(λ/4π)⁴·|Σ_n Γ_n e^{−jk(d1n+d2n)}/(d1n·d2n)|²。
    远场时退化为 Gt·Gr·N²/(FSPL(d1)·FSPL(d2))（Björnson N² 律）。
    """
    pos = _positions(positions_m, "positions_m")
    f = _pos(f_hz, "f_hz")
    gt = _num(gt_db, "gt_db")
    gr = _num(gr_db, "gr_db")
    lam = C0_M_S / f
    h = cascade_geometry_sum(pos, bs_pos_m, ue_pos_m, f, phases_rad=phases_rad)
    return (
        10.0 ** (0.1 * (gt + gr))
        * (lam / (4.0 * math.pi)) ** 4
        * abs(h) ** 2
    )


def farfield_cascade_power_ratio(
    d1_m: float,
    d2_m: float,
    n_elements: int,
    f_hz: float,
    coherence: float = 1.0,
    gt_db: float = 0.0,
    gr_db: float = 0.0,
) -> float:
    """远场级联闭式 P_rx/P_tx = Gt·Gr·N²·coh²/(FSPL(d1)·FSPL(d2))。

    coherence=|Σ a_n|/(N/(d1·d2)) > 0（相位对齐因子，远场共轭=1；近场
    共轭可轻微 >1——单元距离失配的二阶凸性效应，如实传入不截断）。
    N² 律出处 Björnson TWC 2020（round14 :96-97 规格引用口径）。
    """
    d1 = _pos(d1_m, "d1_m")
    d2 = _pos(d2_m, "d2_m")
    n = _int(n_elements, "n_elements", 1)
    f = _pos(f_hz, "f_hz")
    coh = _num(coherence, "coherence")
    if coh <= 0.0:
        raise ValueError(f"coherence 必须 > 0，得 {coh}")
    return (
        10.0 ** (0.1 * (_num(gt_db, "gt_db") + _num(gr_db, "gr_db")))
        * (n * coh) ** 2
        / (10.0 ** (0.1 * fspl_db(d1, f)))
        / (10.0 ** (0.1 * fspl_db(d2, f)))
    )


def direct_power_ratio(
    d_m: float, f_hz: float, gt_db: float = 0.0, gr_db: float = 0.0
) -> float:
    """直连链路功率比 = Gt·Gr/FSPL(d)（平方律指数 2，Friis 各向同性口径）。"""
    d = _pos(d_m, "d_m")
    f = _pos(f_hz, "f_hz")
    return 10.0 ** (0.1 * (_num(gt_db, "gt_db") + _num(gr_db, "gr_db"))) / (
        10.0 ** (0.1 * fspl_db(d, f))
    )


def crossover_direct_distance_m(
    d1_m: float, d2_m: float, n_elements: int, f_hz: float
) -> float:
    """RIS 链（共轭、远场）追平直链的直连距离 d_cross = 4π·d1·d2/(N·λ)。

    直连距离 d > d_cross 后 RIS 级联胜出（等天线增益/coh=1 口径）——
    经典"短距直链占优、RIS 是覆盖扩展工具"结论的定量形态。
    """
    d1 = _pos(d1_m, "d1_m")
    d2 = _pos(d2_m, "d2_m")
    n = _int(n_elements, "n_elements", 1)
    f = _pos(f_hz, "f_hz")
    lam = C0_M_S / f
    return 4.0 * math.pi * d1 * d2 / (n * lam)


# ─── 相位面：共轭 vs 随机 ─────────────────────────────────────────────────────


def coherent_vs_random_ratio(weights_m: np.ndarray) -> float:
    """共轭/随机相干增益比 (Σa_n)²/Σa_n²（精确，几何权重任意）。

    随机相位功率增益期望 E|Σ a_n e^{jφ_n}|² = Σ a_n²（瑞利游走，
    交叉项期望为零）；共轭匹配增益 = (Σa_n)²。等幅权重时比值恰为 N
    （经典结论：共轭 N² vs 随机 N，出处 Björnson TWC 2020 N² 律推论）。
    """
    a = np.asarray(weights_m, dtype=float).reshape(-1)
    if a.size < 1 or not np.all(np.isfinite(a)) or float(a.min()) <= 0.0:
        raise ValueError("weights_m 必须是非空正有限数组")
    return float(a.sum() ** 2 / float(np.sum(a * a)))


def random_gain_mc(
    weights_m: np.ndarray, n_trials: int, seed: int = 0
) -> float:
    """随机相位功率增益 Monte-Carlo 均值 mean|Σ a_n e^{jφ_n}|²（固定种子）。

    期望 = Σ a_n²（coherent_vs_random_ratio 的 MC 旁证路径；固定
    seed 的 numpy Generator，逐位可复现）。
    """
    a = np.asarray(weights_m, dtype=float).reshape(-1)
    if a.size < 1 or not np.all(np.isfinite(a)):
        raise ValueError("weights_m 必须是非空有限数组")
    trials = _int(n_trials, "n_trials", 1)
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0.0, 2.0 * math.pi, size=(trials, a.size))
    s = np.exp(1j * ph) @ a
    return float(np.mean(np.abs(s) ** 2))


# ─── 无源波束指向角谱验证 ─────────────────────────────────────────────────────


def _unit_from_spherical(theta_rad: float, phi_rad: float) -> np.ndarray:
    st = math.sin(theta_rad)
    return np.array([st * math.cos(phi_rad), st * math.sin(phi_rad),
                     math.cos(theta_rad)])


def steering_spectrum(
    positions_m: np.ndarray,
    bs_pos_m: np.ndarray,
    ue_pos_m: np.ndarray,
    f_hz: float,
    phases_rad: np.ndarray,
    n_theta: int = 361,
) -> dict[str, Any]:
    """散射远场角谱 |A(û)|²/N²（UE 方位平面扫描）+ 指向验证。

    A(û) = Σ_n e^{jφ_n}·e^{−jk(d1n−r_n·û)}（û=球坐标观测方向，φ_n
    为 RIS 反射相位）；共轭相位下谱峰应落在 UE 几何方向（远场 UE
    精确对齐；近场 UE 谱峰对准其方位角——本函数扫描 UE 方位角平面
    phi=atan2(ue_y,ue_x)）。返回谱峰方向/UE 几何方向/偏角/−3dB 束宽
    （HPBW 数值估计=峰邻域连续 ≥0.5 run 的 θ 跨度；峰在 θ=0 边界时
    栅格单侧只有 +θ 半边 → 如实为半功率**半宽** 0.443λ/(N·d) 量级，
    Balanis 均匀阵口径）。
    """
    pos = _positions(positions_m, "positions_m")
    bs = _vec3(bs_pos_m, "bs_pos_m")
    ue = _vec3(ue_pos_m, "ue_pos_m")
    f = _pos(f_hz, "f_hz")
    ph = np.asarray(phases_rad, dtype=float).reshape(-1)
    if ph.size != pos.shape[0]:
        raise ValueError(
            f"phases_rad 长度 {ph.size} ≠ 单元数 {pos.shape[0]}")
    n_th = _int(n_theta, "n_theta", 16)
    k = 2.0 * math.pi * f / C0_M_S
    d1 = _element_distances(pos, bs, "bs_pos_m")
    phi_scan = math.atan2(float(ue[1]), float(ue[0]))
    ue_geom_deg = math.degrees(
        math.acos(max(-1.0, min(1.0, float(ue[2]) / float(np.linalg.norm(ue))))))
    thetas = np.linspace(0.0, math.pi, n_th)
    us = np.stack([np.sin(thetas) * math.cos(phi_scan),
                   np.sin(thetas) * math.sin(phi_scan),
                   np.cos(thetas)], axis=1)
    # A(û) = Σ e^{jφn}·e^{−jk·d1n}·e^{+jk·r_n·û}
    amp = np.abs(np.exp(1j * ph - 1j * k * d1) @ np.exp(1j * k * (pos @ us.T)))
    pwr = (amp / amp.max()) ** 2
    i_pk = int(np.argmax(pwr))
    # −3dB 束宽：峰位邻域连续 ≥0.5 run（均匀阵宽侧 ±z 双峰，禁全域 span）
    lo = i_pk
    while lo > 0 and pwr[lo - 1] >= 0.5:
        lo -= 1
    hi = i_pk
    while hi < n_th - 1 and pwr[hi + 1] >= 0.5:
        hi += 1
    hpbw_deg = math.degrees(float(thetas[hi] - thetas[lo]))
    return {
        "theta_deg": [math.degrees(t) for t in thetas],
        "pattern_norm": [float(v) for v in pwr],
        "peak_theta_deg": math.degrees(float(thetas[i_pk])),
        "ue_geom_theta_deg": ue_geom_deg,
        "peak_offset_deg": abs(math.degrees(float(thetas[i_pk])) - ue_geom_deg),
        "hpbw_deg": hpbw_deg,
        "coherent_peak": float(amp[i_pk] / pos.shape[0]),  # =1 时完全相干
        "scan_phi_deg": math.degrees(phi_scan),
    }


# ─── 量化损失挂接（metasurface_lut 消费）─────────────────────────────────────


def quantized_conjugate_loss_db(
    positions_m: np.ndarray,
    bs_pos_m: np.ndarray,
    ue_pos_m: np.ndarray,
    f_hz: float,
    bits: int,
) -> dict[str, Any]:
    """共轭相位 b-bit 量化后的级联增益经验损失 vs 解析 sinc² 带。

    经验：φ_n 经 metasurface_lut.quantize_phase_deg 取整后重算
    |h̃_q|/|h̃|；解析：metasurface_lut.quantization_loss_db(bits)
    = −10log10(sinc²(1/2^b))（均匀量化误差期望口径）。经验值受相位
    栅格结构误差扰动，大 N 收敛到解析附近（锚容差 0.4dB@1024 元
    2-bit；结构性偏差如实保留不做拟合修正）。
    """
    pos = _positions(positions_m, "positions_m")
    f = _pos(f_hz, "f_hz")
    b = _int(bits, "bits", 1)
    phi = conjugate_phases_rad(pos, bs_pos_m, ue_pos_m, f)
    h0 = abs(cascade_geometry_sum(pos, bs_pos_m, ue_pos_m, f, phases_rad=phi))
    phi_q = np.radians(
        [quantize_phase_deg(math.degrees(p), b) for p in phi])
    hq = abs(cascade_geometry_sum(pos, bs_pos_m, ue_pos_m, f, phases_rad=phi_q))
    loss_emp = -20.0 * math.log10(max(hq / h0, 1e-15))
    return {
        "bits": b,
        "n_elements": int(pos.shape[0]),
        "gain_loss_db": loss_emp,
        "analytic_loss_db": _ms_quantization_loss_db(b),
        "delta_db": loss_emp - _ms_quantization_loss_db(b),
    }


# ─── 远场适用性 ───────────────────────────────────────────────────────────────


def farfield_validity(
    positions_m: np.ndarray, d1_m: float, d2_m: float, f_hz: float
) -> dict[str, Any]:
    """Fraunhofer 2D²/λ 逐段适用性标注（不 hard-fail，诚实标注面）。"""
    pos = _positions(positions_m, "positions_m")
    d1 = _pos(d1_m, "d1_m")
    d2 = _pos(d2_m, "d2_m")
    f = _pos(f_hz, "f_hz")
    extent = float(np.linalg.norm(
        pos.max(axis=0)[:2] - pos.min(axis=0)[:2]))  # 口径面最大线度
    d_ff = 2.0 * extent ** 2 / (C0_M_S / f)
    return {
        "aperture_extent_m": extent,
        "fraunhofer_m": d_ff,
        "d1_m": d1,
        "d2_m": d2,
        "d1_farfield_ok": bool(d1 >= d_ff),
        "d2_farfield_ok": bool(d2 >= d_ff),
        "n2_law_applicable": bool(d1 >= d_ff and d2 >= d_ff),
    }


# ─── 一键报告（计算器壳消费）─────────────────────────────────────────────────


def _default_geometry(d1_m: float, d2_m: float) -> tuple[np.ndarray, np.ndarray]:
    """缺省几何：BS/UE 对称 30° 仰角（RIS 在原点 xy 面，法向 +z）。"""
    s, c = 0.5, math.sqrt(3.0) / 2.0
    return (np.array([-d1_m * s, 0.0, d1_m * c]),
            np.array([d2_m * s, 0.0, d2_m * c]))


def ris_cascade_report(
    f_hz: float,
    positions_m: np.ndarray,
    bs_pos_m: np.ndarray,
    ue_pos_m: np.ndarray,
    *,
    tx_power_dbm: float = 0.0,
    gt_db: float = 0.0,
    gr_db: float = 0.0,
    phase_mode: str = "conjugate",
    bits: int = 0,
    random_seed: int = 0,
    n_random_trials: int = 4096,
    include_direct: bool = True,
) -> dict[str, Any]:
    """NX-4 一键报告：几何级联 + N² 律闭式 + 指向验证 + 量化损失 + 直连对比。

    phase_mode："conjugate"（闭式共轭匹配）/ "random"（固定种子随机，
    供对比）/ "none"（全零相位=未配相基线）。返回 JSON 可序列化 dict
    （逐键 float cast；numpy 数组只出现在 theta_deg/pattern_norm 列表）。
    """
    pos = _positions(positions_m, "positions_m")
    f = _pos(f_hz, "f_hz")
    if phase_mode not in ("conjugate", "random", "none"):
        raise ValueError(
            f"phase_mode 只收 'conjugate'/'random'/'none'，得 {phase_mode!r}")
    lam = C0_M_S / f
    d1 = _element_distances(pos, _vec3(bs_pos_m, "bs_pos_m"), "bs_pos_m")
    d2 = _element_distances(pos, _vec3(ue_pos_m, "ue_pos_m"), "ue_pos_m")
    n = int(pos.shape[0])

    phi = conjugate_phases_rad(pos, bs_pos_m, ue_pos_m, f)
    if phase_mode == "random":
        rng = np.random.default_rng(random_seed)
        phases = rng.uniform(0.0, 2.0 * math.pi, size=n)
    elif phase_mode == "none":
        phases = np.zeros(n)
    else:
        phases = phi

    h_conj = cascade_geometry_sum(pos, bs_pos_m, ue_pos_m, f, phases_rad=phi)
    p_rx = cascade_power_ratio(pos, bs_pos_m, ue_pos_m, f, phases_rad=phases,
                               gt_db=gt_db, gr_db=gr_db)
    # 远场 N² 闭式的 coherence 修正（精确和归一出；近场可 >1 如实传）
    coherence = abs(h_conj) / (n / (float(d1.mean()) * float(d2.mean())))
    ff = farfield_validity(pos, float(d1.mean()), float(d2.mean()), f)
    fs1, fs2 = fspl_db(float(d1.mean()), f), fspl_db(float(d2.mean()), f)

    out: dict[str, Any] = {
        "f_ghz": f / 1e9,
        "wavelength_mm": lam * 1e3,
        "n_elements": n,
        "geometry": {
            "d1_center_m": float(np.linalg.norm(
                np.asarray(bs_pos_m, dtype=float))),
            "d2_center_m": float(np.linalg.norm(
                np.asarray(ue_pos_m, dtype=float))),
            "d1_mean_m": float(d1.mean()),
            "d2_mean_m": float(d2.mean()),
        },
        "fspl_d1_db": fs1,
        "fspl_d2_db": fs2,
        "phase_mode": phase_mode,
        "cascade_power_ratio": p_rx,
        "received_power_dbm": _num(tx_power_dbm, "tx_power_dbm") + 10.0 * math.log10(
            max(p_rx, 1e-300)),
        "coherence_conj": coherence,
        "farfield_closed_form_ratio": farfield_cascade_power_ratio(
            float(d1.mean()), float(d2.mean()), n, f,
            coherence=coherence, gt_db=gt_db, gr_db=gr_db),
        "farfield": ff,
        "cascade_loss_db": fs1 + fs2 - 20.0 * math.log10(
            n * max(coherence, 1e-15)),
    }

    # 相位面：共轭 vs 随机（等幅权重比值精确 = N；几何权重≈N，1e-3 带）
    w = 1.0 / (d1 * d2)
    ratio = coherent_vs_random_ratio(w)
    mc = random_gain_mc(w, n_random_trials, seed=random_seed)
    mc_exact = float(np.sum(w * w))
    out["phase_surface"] = {
        "conjugate_gain": float(abs(h_conj) ** 2),
        "random_gain_mc": mc,
        "random_gain_exact_expectation": mc_exact,
        "coherent_vs_random_ratio": ratio,
        "ratio_is_n": abs(ratio - n) <= 1e-3 * n,
        # 任务书量级「共轭 ≥ N·π²/4（×单元随机基线）」的量纲一致形态：
        # (Σw)² ≥ (π²/4)·Σw²——两侧同为级联增益（|h̃|² 量纲），随机基线
        # E|Σ w e^{jφ}|²=Σw² 按 N 元摊平后即任务书 N·π²/4 语义；
        # N≥3 恒真（π²/4≈2.47；出处 Björnson TWC 2020 N² 律）。
        "book_magnitude_ok": bool(
            float(np.sum(w)) ** 2 >= math.pi ** 2 / 4.0 * float(np.sum(w * w))),
    }

    # 指向角谱验证（共轭相位面）
    spec = steering_spectrum(pos, bs_pos_m, ue_pos_m, f, phi)
    spec["pattern_norm"] = [round(v, 6) for v in spec["pattern_norm"]]
    out["steering"] = spec

    # 量化损失挂接
    if bits:
        out["quantization"] = quantized_conjugate_loss_db(
            pos, bs_pos_m, ue_pos_m, f, _int(bits, "bits", 1))

    # 直连对比与交叉距离
    if include_direct:
        bs_c = np.asarray(bs_pos_m, dtype=float)
        ue_c = np.asarray(ue_pos_m, dtype=float)
        d_direct = float(np.linalg.norm(ue_c - bs_c))
        p_direct = direct_power_ratio(d_direct, f, gt_db=gt_db, gr_db=gr_db)
        d_cross = crossover_direct_distance_m(
            float(d1.mean()), float(d2.mean()), n, f)
        out["direct_comparison"] = {
            "direct_distance_m": d_direct,
            "direct_power_ratio": p_direct,
            "ris_vs_direct_db": 10.0 * math.log10(max(p_rx, 1e-300) / p_direct),
            "crossover_direct_distance_m": d_cross,
            "direct_wins_below_cross": bool(d_direct < d_cross),
        }
    return out
