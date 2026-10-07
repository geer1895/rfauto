"""AP-4 反射面闭式设计器（round17 §三 AP-4，P1/M；2026-10-03）。

焦径比/馈源cos^q效率（溢出+照射）/口径场/遮挡/Ruze/卡塞格伦等效/
均匀口径次级方向图/效率预算总表。全部**纯函数零 IO**、numpy（+
惰性 scipy.special.j0/j1——propagation.py scipy.special 惰性导入
同先例）、返回 JSON 可序列化值。零求解器依赖。

出处与口径：
- Ruze 表面公差效率：η_R = exp[−(4π·σ/λ)²]（J. Ruze, "Antenna
  Tolerance Theory—A Review", Proc. IEEE 54(4):633-640, 1966；
  σ=口径面法向 rms 表面误差）。闭式锚：σ=0→1；σ=λ/32→−0.669dB；
  σ=λ/16→−2.673dB；小误差 dB 规则 10log₁₀η ≈ −4.343·(4πσ/λ)²。
- 馈源功率方向图 p(θ)=cos^q(θ)（q=功率指数，Balanis G_f 口径，
  前半球归一 ∫₀^{π/2}cos^q·sinθdθ=1/(q+1)）：
  * 溢出效率 η_s = 1 − cos^{q+1}(θ₀)（θ₀=反射面对馈源所张半角；
    q=0 各向同性馈解析锚 1−cosθ₀）。
  * 口径效率（含溢出+照射，焦馈抛物面射线映射+平面波投影推导）：
        η_ap = 2(q+1)·cot²(θ₀/2)·|∫₀^{θ₀} cos^{q/2}θ·tan(θ/2) dθ|²
    与逐式独立的口径面路径（ρ=2f·tan(θ/2) 射线映射能流守恒 →
    E_a(ρ)=cos²(θ/2)·cos^{q/2}θ → |∫E_a dA|²/(A·P_f)）互证。
    经典数值背景（文献惯引口径）：cos²q=2 馈最优 η_ap≈0.82
    （-10 dB 量级边照惯例）——测试窗 [0.81,0.83]，实现实测落窗。
  * 手积闭式锚（q=2）：∫cosθ·tan(θ/2)dθ = (1−ln2)−(cosθ₀−ln(1+cosθ₀))
    （符号积分），θ₀=60° → η_ap=0.811419（测试按闭式现算比对）。
- 遮挡效率：η_bl = (1−(d_b/D)²)²（中心圆遮挡，Balanis §15 遮挡
  口径；惯例=被遮挡功率仍计入辐射总功率，遮挡散射按宽角扩散——
  若用"遮挡功率移除"口径则场面积比为 1−β²，两口径差一因子
  (1−β²)，消费方按场景选）。次级方向图数值路径互证：环带/满盘
  方向性比 = 1−β²（移除口径的模型精确量，paraxial 容差显式声明）。
- 卡塞格伦等效：双曲副面偏心率 e=(M+1)/(M−1)、等效抛物面焦距
  f_eq = M·f（P.W. Hannan, "Microwave Antennas Derived from the
  Cassegrain Telescope", IRE Trans. AP-9(2):140-153, 1961 等效
  抛物面口径；代数恒等式互证 M=2→e=3、M=4→e=5/3）。
- 均匀圆口径次级方向图：E(θ) ∝ 2J₁(x)/x，x=(πD/λ)·sinθ（Airy）。
  文献常数锚（DLMF 数学常数）：J₁ 第一零点 x=3.8317059 → 第一零点
  sinθ=1.2197λ/D；半功率点 x=1.6163340 → HPBW=58.96°·λ/D。方向性
  均匀口径锚 D₀=4πA/λ²=(πD/λ)²（round17 AP-4 验收锚；整球积分
  复用 core/farfield.directivity_grid 积分器）。

#118/#300 纪律：每件 ≥2 独立基准（闭式极限/手积符号积分/第二数值
路径/文献常数），门值预声明 tests/unit/test_reflector_antenna.py。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.farfield import directivity_grid

#: 光速（SI 精确值，与 propagation/bounds 同值口径）。
C0_M_S = 299792458.0

#: J₁ 第一零点与半功率横坐标（DLMF 数学常数，Airy 方向图文献锚）。
J1_FIRST_ZERO = 3.83170597
J1_HALF_POWER_X = 1.61633400

#: 角度积分节点数（Gauss-Legendre，cos^q 被积函数光滑，~1e-12 精度）。
_QUAD_NODES = 256

#: 口径径向积分节点数（Hankel 变换数值路径）。
_RADIAL_NODES = 2048


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    """正数域守卫（>0）。"""
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，得 {out}")
    return out


def _q_power(value: Any) -> float:
    """馈源功率指数 q ≥ 0 守卫。"""
    out = _num(value, "q_power")
    if out < 0.0:
        raise ValueError(f"q_power（功率指数）必须 ≥0，得 {out}")
    return out


def _theta_edge(value: Any) -> float:
    """口径半角 θ₀ ∈ (0, 90°] 守卫（前半球馈）。"""
    out = _num(value, "theta0_rad")
    if out <= 0.0 or out > math.pi / 2.0:
        raise ValueError(
            f"theta0_rad 须在 (0, π/2] 内（前半球馈口径），得 {out}")
    return out


# ─── Ruze 表面公差效率 ───────────────────────────────────────────────────────


def ruze_efficiency(sigma_m: float, f_hz: float) -> float:
    """Ruze 效率 η_R = exp[−(4πσ/λ)²]（Ruze 1966 Proc IEEE 54(4)）。

    锚：σ=0→1；σ=λ/32→0.857125（−0.669dB）；σ=λ/16→0.539742（−2.673dB）。
    """
    sigma = _num(sigma_m, "sigma_m")
    if sigma < 0.0:
        raise ValueError(f"sigma_m 必须 ≥0，得 {sigma}")
    lam = C0_M_S / _pos(f_hz, "f_hz")
    return math.exp(-((4.0 * math.pi * sigma / lam) ** 2))


def ruze_gain_loss_db(sigma_m: float, f_hz: float) -> float:
    """Ruze 增益损失 [dB] = 10·log10(η_R)（≤0）。"""
    return 10.0 * math.log10(ruze_efficiency(sigma_m, f_hz))


# ─── 馈源效率（cos^q 功率方向图）─────────────────────────────────────────────


def spillover_efficiency(theta0_rad: float, q_power: float) -> float:
    """溢出效率 η_s = 1 − cos^{q+1}(θ₀)（cos^q 功率方向图、前半球馈）。

    解析锚（q=0 各向同性馈）：η_s = 1 − cosθ₀（测试独立数值积分互证）。
    """
    t0 = _theta_edge(theta0_rad)
    q = _q_power(q_power)
    return 1.0 - math.cos(t0) ** (q + 1.0)


def aperture_efficiency(theta0_rad: float, q_power: float) -> float:
    """口径效率（溢出+照射合并，焦馈抛物面）——角域积分路径。

    η_ap = 2(q+1)·cot²(θ₀/2)·|∫₀^{θ₀} cos^{q/2}θ·tan(θ/2)dθ|²
    （cos^q 功率方向图、前半球归一；Gauss-Legendre 数值积分）。
    与 aperture_efficiency_aperture_plane（口径面射线映射路径）互证；
    手积闭式锚 q=2（符号积分，见模块 docstring）。
    """
    t0 = _theta_edge(theta0_rad)
    q = _q_power(q_power)
    nodes, weights = np.polynomial.legendre.leggauss(_QUAD_NODES)
    th = 0.5 * t0 * (nodes + 1.0)
    w = 0.5 * t0 * weights
    integrand = np.cos(th) ** (q / 2.0) * np.tan(th / 2.0)
    integral = float(np.sum(w * integrand))
    return (
        2.0
        * (q + 1.0)
        * math.tan(math.pi / 2.0 - t0 / 2.0) ** 2
        * integral**2
    )


def aperture_efficiency_aperture_plane(
    theta0_rad: float, q_power: float, n_radial: int = _RADIAL_NODES
) -> float:
    """口径效率——口径面射线映射独立路径（与角域积分路径互证）。

    推导链（能流守恒，逐式见模块 docstring）：ρ=2f·tan(θ/2) 射线
    映射 → 口径面功率密度 w(ρ)=p(θ)·sinθ/(ρ·dρ/dθ) → E_a=√w；
    η = |∫E_a dA|²/(A·P_f)。标度取 f=1/(2·tan(θ₀/2))（R=1）、
    P_f=1（前半球归一 p=(q+1)cos^q/(2π)），恒等式 η = 2(q+1)·
    cot²(θ₀/2)·|∫cos^{q/2}θ·tan(θ/2)dθ|² 的独立数值积分域（径向 vs
    角域，#118 两路径独立）。
    """
    t0 = _theta_edge(theta0_rad)
    q = _q_power(q_power)
    if n_radial < 16:
        raise ValueError(f"n_radial 至少 16，得 {n_radial}")
    focal = 1.0 / (2.0 * math.tan(t0 / 2.0))  # R=1 标度
    nodes, weights = np.polynomial.legendre.leggauss(int(n_radial))
    rho = (nodes + 1.0) * 0.5          # ρ ∈ [0, 1)（R=1）
    w_gl = weights * 0.5
    theta = 2.0 * np.arctan(rho * math.tan(t0 / 2.0))  # ρ=2f·tan(θ/2) 反演
    p_feed = (q + 1.0) * np.cos(theta) ** q / (2.0 * math.pi)  # ∫p dΩ = 1
    drho_dtheta = focal / np.cos(theta / 2.0) ** 2
    ea = np.sqrt(p_feed * np.sin(theta) / (rho * drho_dtheta))
    integral = float(np.sum(w_gl * ea * rho))  # ∫E_a ρ dρ（R=1）
    area = math.pi
    return (2.0 * math.pi * integral) ** 2 / area  # P_f = 1


def illumination_efficiency(theta0_rad: float, q_power: float) -> float:
    """照射效率 η_i = η_ap/η_s（剔除溢出后的口径照射质量）。"""
    sp = spillover_efficiency(theta0_rad, q_power)
    if sp <= 0.0:
        raise ValueError("spillover 为 0（θ₀→0 退化），照射效率无定义")
    return aperture_efficiency(theta0_rad, q_power) / sp


# ─── 遮挡 ────────────────────────────────────────────────────────────────────


def blockage_efficiency(d_block_m: float, d_m: float) -> float:
    """中心圆遮挡效率 η_bl = (1−(d_b/D)²)²（Balanis §15 口径）。

    锚：d_b=0→1；d_b/D=0.2→0.9216。惯例=遮挡功率仍计入辐射（散射
    宽角扩散）；"功率移除"口径的场面积比 1−β² 由次级方向图数值
    路径互证（测试，paraxial 容差显式声明）。
    """
    db = _num(d_block_m, "d_block_m")
    if db < 0.0:
        raise ValueError(f"d_block_m 必须 ≥0，得 {db}")
    d = _pos(d_m, "d_m")
    if db > d:
        raise ValueError(f"d_block_m（{db}）不得大于口径 D（{d}）")
    beta = db / d
    return (1.0 - beta * beta) ** 2


# ─── 卡塞格伦等效 ────────────────────────────────────────────────────────────


def cassegrain_geometry(d_m: float, f_over_d: float, magnification: float) -> dict[str, float]:
    """经典卡塞格伦等效几何（Hannan 1961 等效抛物面口径）。

    入参：D 主面口径 [m]、f/D 主面焦径比、M 副面放大倍数
    （M=(e+1)/(e−1)，e=双曲副面偏心率，M>1）。
    返回：e / f_eq_m=M·f / f_eq_over_d / theta_rim_primary_deg
    （主面边缘角 tan(θ/2)=D/4f）/ theta_rim_equivalent_deg
    （等效抛物面边缘角 tan(θ/2)=D/4f_eq）。代数恒等式锚：
    M=2→e=3、M=4→e=5/3、f_eq_over_d=M·f_over_d。
    """
    d = _pos(d_m, "d_m")
    fod = _pos(f_over_d, "f_over_d")
    m = _pos(magnification, "magnification")
    if m <= 1.0:
        raise ValueError(f"放大倍数 M 必须 >1（M→1⁺ 对应 e→∞ 退化），得 {m}")
    f = fod * d
    e = (m + 1.0) / (m - 1.0)
    f_eq = m * f
    return {
        "e": e,
        "f_eq_m": f_eq,
        "f_eq_over_d": f_eq / d,
        "theta_rim_primary_deg": 2.0 * math.degrees(math.atan(d / (4.0 * f))),
        "theta_rim_equivalent_deg": 2.0 * math.degrees(math.atan(d / (4.0 * f_eq))),
    }


# ─── 次级方向图（口径 Hankel 变换）与方向性 ─────────────────────────────────


def circular_aperture_pattern(
    aperture_field: Callable[[np.ndarray], np.ndarray],
    d_m: float,
    f_hz: float,
    theta_deg: np.ndarray | list[float],
    n_radial: int = _RADIAL_NODES,
) -> np.ndarray:
    """轴对称圆口径次级场方向图 E(θ)（口径 Hankel 变换数值路径）。

    E(θ) = 2π·∫₀^R E_a(ρ)·J₀(k·sinθ·ρ)·ρ dρ（恒按解析 boresight
    F(0)=2π·∫E_a·ρdρ 归一——不按提交 θ 列表的子集最大值归一，
    稀疏角度列表（如零点定位两点采样）不会被误归一）。aperture_field(ρ)
    为口径场幅相函数（ρ∈[0,D/2] 米）。惰性导入 scipy.special.j0
    （propagation.py 同先例，模块导入面仍纯 numpy）。
    """
    from scipy.special import j0 as _j0

    d = _pos(d_m, "d_m")
    k = 2.0 * math.pi * _pos(f_hz, "f_hz") / C0_M_S
    radius = d / 2.0
    nodes, weights = np.polynomial.legendre.leggauss(int(n_radial))
    rho = (nodes + 1.0) * 0.5 * radius
    w = weights * 0.5 * radius
    ea = np.asarray(aperture_field(rho), dtype=complex)
    th = np.asarray(theta_deg, dtype=float)
    if np.any(th < 0.0) or np.any(th > 180.0):
        raise ValueError("theta_deg 须在 [0, 180] 内")
    s = np.sin(np.deg2rad(th))
    arg = np.outer(s, k * rho)
    pattern = 2.0 * math.pi * (w * ea * rho) @ _j0(arg).T  # (n_theta,)
    bore = 2.0 * math.pi * complex(np.sum(w * ea * rho))  # F(0)：j0(0)=1
    if abs(bore) <= 0.0:
        raise ValueError("口径场积分为零（方向图无定义）")
    return pattern / bore


def uniform_aperture_field(rho: np.ndarray) -> np.ndarray:
    """均匀口径场（η_ap=1 基准；4πA/λ² 锚消费形态）。"""
    return np.ones_like(np.asarray(rho, dtype=float))


def annulus_aperture_field(inner_m: float, d_m: float):
    """中心遮挡（环带）口径场——blockage 数值互证路径。"""
    r_in = _pos(inner_m, "inner_m")
    r_out = _pos(d_m, "d_m") / 2.0
    if r_in >= r_out:
        raise ValueError(f"inner_m（{r_in}）须小于半径（{r_out}）")

    def field(rho: np.ndarray) -> np.ndarray:
        return np.where(np.asarray(rho) >= r_in, 1.0, 0.0)

    return field


def directivity_uniform_aperture(d_m: float, f_hz: float, n_theta: int = 3601,
                                 n_phi: int = 721) -> float:
    """均匀圆口径方向性数值值（复用 farfield.directivity_grid 积分器）。

    锚：D₀ = 4πA/λ² = (πD/λ)²（round17 AP-4 验收锚）。口径角谱模型
    F(θ)∝J₀ 变换关于 θ=90° 镜像对称（背面 boresight）——全球积分恰
    为物理单面口径功率的 2 倍（对称恒等），故 ×2 还原单面口径；
    farfield.directivity_grid 的 θ/φ 轴契约是弧度。实测残差（trapz
    主瓣离散 + 角谱模型 obliquity）~+0.17%@n_theta=3601、D/λ=40，
    测试门 rel 5e-3 预声明。
    """
    d = _pos(d_m, "d_m")
    _pos(f_hz, "f_hz")
    theta = np.linspace(0.0, 180.0, int(n_theta))
    field = circular_aperture_pattern(
        uniform_aperture_field, d, f_hz, theta, n_radial=1024)
    power = np.abs(field) ** 2
    phi = np.linspace(0.0, 2.0 * math.pi, int(n_phi), endpoint=False)
    grid = np.repeat(power[:, None], phi.size, axis=1)
    d_full = float(directivity_grid(grid, np.deg2rad(theta), phi).max())
    return 2.0 * d_full


def gain_db(d_m: float, f_hz: float, eta_total: float) -> float:
    """反射面增益 [dB] = 10·log10(η_total·(πD/λ)²)。

    η_total 为效率预算总乘积（efficiency_budget()["total"]）。η=1 锚：
    均匀口径 D₀=(πD/λ)²；η=0/负域显式 ValueError（#117 族 falsy 陷阱
    判据用显式比较不用 or）。
    """
    d = _pos(d_m, "d_m")
    lam = C0_M_S / _pos(f_hz, "f_hz")
    eta = _num(eta_total, "eta_total")
    if eta <= 0.0 or eta > 1.0:
        raise ValueError(f"eta_total 须在 (0, 1] 内，得 {eta}")
    return 10.0 * math.log10(eta * (math.pi * d / lam) ** 2)


def efficiency_budget(
    d_m: float,
    f_hz: float,
    theta0_rad: float,
    q_power: float,
    sigma_rms_m: float = 0.0,
    d_block_m: float = 0.0,
) -> dict[str, Any]:
    """效率预算总表（各因子独立相乘；round17 AP-4"效率预算总表"）。

    验收锚（round17 预声明）：σ=0 → ruze=1；d_b=0 → blockage=1；
    total = spillover·illumination·ruze·blockage = aperture_efficiency
    ·ruze·blockage（η_ap=η_s·η_i 恒等，测试钉）。
    """
    sp = spillover_efficiency(theta0_rad, q_power)
    ill = illumination_efficiency(theta0_rad, q_power)
    ruz = ruze_efficiency(sigma_rms_m, f_hz)
    blk = blockage_efficiency(d_block_m, d_m)
    total = sp * ill * ruz * blk
    return {
        "spillover": sp,
        "illumination": ill,
        "ruze": ruz,
        "blockage": blk,
        "total": total,
        "gain_db": gain_db(d_m, f_hz, total),
        "aperture_efficiency": sp * ill,
    }
