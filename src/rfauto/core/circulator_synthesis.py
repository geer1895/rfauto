"""F-K.B 铁氧体结环形器综合内核（Bosma 全闭式）：Polder 张量 → 盘半径/耦合角/
偏置初值 → 理想/准理想三端口 S 矩阵 → Wu-Rosenbaum 带宽登记 → 集总 LC 低频版。

法源与核验状态（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- **Polder 张量磁导率**（饱和铁氧体，Gilbert 进动方程解）：Polder, D.,
  "On the Theory of Ferromagnetic Resonance", Phil. Mag. 40:99-115 (1949)
  ——原文未逐位复读，公式按任务书钉死口径实现（二级文献通行式）：
  μ = 1 + ω_m·(ω_h + jαω) / ((ω_h + jαω)² − ω²)，
  κ = ω_m·ω / ((ω_h + jαω)² − ω²)。
  **单位口径钉死 SI**：Ms（A/m）、H_i（A/m，内场）、ω_m = γ·μ0·Ms、
  ω_h = γ·μ0·H_i，γ = 1.76085962784e11 rad/(s·T)（电子旋磁比，NIST
  CODATA 现行值 2026-09-27 实取；γ/2π = 28.0249513861 GHz/T）。
  CGS 换算注记：ω_m = γ·4πMs（Ms 取高斯）与
  SI 口径恒等（1 G 对应 μ0·(10³/(4π)) A/m，见 :data:`GAUSS_TO_A_PER_M`）。
  线宽耦合：α = γ·μ0·ΔH/ω（任务书钉死）。注：该式恰为 Bosma 原文归一化
  线宽 s = ΔH/H₀（H₀ = ω/γ 为铁磁共振场，原文 Eq.76）；文献中 Gilbert α
  与 FWHM 线宽的通行换算常带因子 2（半高全宽 vs 半宽口径），调用方须按
  自家 ΔH 定义选用，本内核不做二次换算。
- **Bosma 结环行理论**：H. Bosma, "On Stripline Y-Circulation at UHF",
  IEEE Trans. Microwave Theory Tech., MTT-12(1):61-72, Jan 1964。
  **原文 PDF（mtt.org 公开件）已逐式核对**，本文件实现的原文条目：
  Eq.8 耦合角 W = arcsin(v/(2R))（v=带线宽、R=盘半径）；
  Eq.13 μ_eff = (μ²−κ²)/μ；Eq.14 k² = ω²μ0ε0·μ_eff·εr；
  Eq.58 x = kR；Eq.65 结环行调整点 J₁′(x₁,₁)=0、x₁,₁ = 1.84（原文 verbatim；
  本内核数值求根自证，见 :func:`j1_prime_first_root`）；
  Eq.76 s = ΔH/H₀；Eq.77/78 远共振闭式 μ_eff ≈ (h+m)/h、κ ≈ m/h²
  （h = H_i/H₀、m = 4πM/H₀，原文归一化口径，仅作独立交叉核对路径）。
  **设计点复现（外部锚）**：原文 §Design 例（450 MHz、4πM=1750 G、
  ΔH=150 G、εr=14.2、v=15 mm → 原文印刷值 Hi=935 Oe、h=5.82、κ/μ=0.112、
  R=3.07 cm、v/R=0.48）由本内核无损 Polder 复现至 ~1%（单测钉）。
  耦合角与结阻抗的环行条件式（原文 Eq.69）**未实现**：原文 PDF 文本层
  数学区乱码，系数位置（4/π 等）无法逐位核对——见
  :func:`bosma_coupling_angle_estimate` 的 UNVERIFIED 登记。
- **Wu-Rosenbaum 带宽**：Y.S. Wu, F.J. Rosenbaum, "Wideband Operation of
  Microstrip Circulators", IEEE Trans. Microwave Theory Tech., MTT-22(10):
  849-856, Oct 1974。**原文未读**；二手文献（2025 S-Band stripline
  circulator 论文、多篇学位论文）一致转述：弱耦合+减小耦合角可实现
  倍频程（2:1）带宽设计法。精确"隔离度-带宽上限曲线/百分比数字"不可达
  原文 → **UNVERIFIED**，本内核只登记倍频程带的分数带宽算术恒等式与
  出处，不臆造百分比上限（任务书预声明纪律）。
- **集总 LC 环形器**：Konishi (1965) 集总元件环形器——出处按任务书/二手
  文献转述登记（原文未读，UNVERIFIED）；本文件只做任务书钉死的简化面：
  三对称 L、C 谐振恒等式 f₀ = 1/(2π√(LC)) + 理想环行 S 的 120° 旋转对称
  （循环置换相似 + 本征值 120° 相位序），不建集总非互易耦合的场模型。

**仿真面边界（任务书登记，本内核不做仿真、不产出真机裁决）**：openEMS
源码级确认仅支持对角张量磁导率（Polder 非对角 κ 不可表达，adapter 能力
矩阵由后续接线批显式标注）；HFSS 原生 ferrite + Magnetic Bias（pyaedt 1.4
无一级 API，走原生脚本）与 COMSOL App 库 968/10302 环形器范例为真机窗
仲裁锚。本内核全部输出为**设计初值**，最终以真机仲裁为准。

接口：纯函数零 IO；math/cmath 为主，scipy（Bessel 求根）惰性导入、
numpy 仅本征值分解使用。全部返回 JSON 可序列化结构（复数在 to_dict 里
拆 re/im，浮点/字符串/bool/None）；数值 0.0 合法（判缺失一律 is not
None，禁 ``or 缺省``，#364④）；bool 显式拒收（df7+⑯）。不进 calculators
注册表（消费者是 service 层，与 core/aging.py 同约定）。
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field

import numpy as np

# ─── 常数（SI；来源逐条标注） ────────────────────────────────────────────────

#: 真空磁导率 μ0（N/A²），CODATA 2018 = 1.25663706212e-6（2019 SI 起
#: 不再是精确定义值 4π×10⁻⁷；本模块统一用 CODATA 值，测试同源取用）
MU_0 = 1.25663706212e-6


#: 真空光速 c（m/s，SI 精确定义值）
C_0 = 299792458.0

#: 真空介电常数 ε0 = 1/(μ0·c²)（F/m，由上两条导出）
EPS_0 = 1.0 / (MU_0 * C_0 * C_0)

#: 电子旋磁比 γ（rad/(s·T)）＝ 1.760 859 627 84(55)e11 s⁻¹T⁻¹（NIST CODATA
#: 现行值，physics.nist.gov 2026-09-27 实取；任务书钉值 1.760859e11 的 7 位
#: 有效数字一致）
GYRO_RAD_S_T = 1.76085962784e11

#: 电子旋磁比 γ/(2π)（GHz/T）＝ 28.0249513861（与上行 γ 同源自洽：
#: γ/(2π) 除法逐位复核；NIST 列表值同此）
GYRO_OVER_2PI_GHZ_T = 28.0249513861

#: 1 G（cgs 磁感应强度）对应的 μ0·M（T）：SI/CGS 换算注记的实现载体。
#: Ms[A/m] = 4πMs[G] × 1e-4 / μ0；1 Oe = 10³/(4π) A/m ≈ 79.5775 A/m。
GAUSS_TO_A_PER_M = 1.0e-4 / MU_0

#: Bosma 原文 Eq.65 verbatim 经典设计点（无单位）：x₁,₁ = 1.84
KR_CLASSIC_1P84 = 1.84

#: 理想环行 S 的环行方向枚举：+1 = 1→2→3→1（S21=S32=S13）；−1 = 反向
SENSE_FORWARD = 1
SENSE_REVERSE = -1

#: 集总 LC service schema 版本之外的模块级登记（recipe_version 与
#: schema_version 语义区分，#106；本模块无 schema，仅 provenance 用）
CIRCULATOR_SYNTHESIS_PROVENANCE = {
    "polder": "Polder 1949 Phil.Mag.40:99-115 (任务书钉死口径；原文未逐位复读)",
    "bosma": "Bosma 1964 IEEE Trans.MTT-12(1):61-72（原文 PDF 逐式核对）",
    "wu_rosenbaum": "Wu & Rosenbaum 1974 IEEE Trans.MTT-22(10):849-856（原文未读，"
    "倍频程结论按二手文献；精确百分比 UNVERIFIED）",
    "konishi": "Konishi 1965 集总环形器（二手文献转述，UNVERIFIED）",
}


# ─── 入参收敛守卫（与 core/aging.py 同口径） ─────────────────────────────────


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


# ─── 1. Polder 张量磁导率 ────────────────────────────────────────────────────


@dataclass(frozen=True)
class PolderResult:
    """Polder 张量磁导率结果（复数 μ、κ + 归一化量，JSON 走 to_dict）。"""

    f_hz: float
    ms_a_per_m: float
    h_i_a_per_m: float
    alpha: float
    omega_rad_s: float
    omega_h_rad_s: float
    omega_m_rad_s: float
    mu: complex
    kappa: complex

    def to_dict(self) -> dict:
        """JSON 可序列化（复数拆 re/im）。"""
        return {
            "f_hz": self.f_hz,
            "ms_a_per_m": self.ms_a_per_m,
            "h_i_a_per_m": self.h_i_a_per_m,
            "alpha": self.alpha,
            "omega_rad_s": self.omega_rad_s,
            "omega_h_rad_s": self.omega_h_rad_s,
            "omega_m_rad_s": self.omega_m_rad_s,
            "mu": {"re": self.mu.real, "im": self.mu.imag},
            "kappa": {"re": self.kappa.real, "im": self.kappa.imag},
        }


def alpha_from_linewidth(delta_h_a_per_m: float, f_hz: float) -> float:
    """线宽 → 阻尼/归一化线宽系数 α = γ·μ0·ΔH/ω（任务书钉死口径）。

    delta_h_a_per_m：共振线宽 ΔH（A/m，>=0，0=无损）；f_hz：频率（Hz，>0）。
    注：该式 = Bosma 原文归一化线宽 s = ΔH/H₀（Eq.76，H₀=ω/γ）；文献
    Gilbert α 与 FWHM 线宽换算常带因子 2，口径差异见模块 docstring。
    """
    dh = _finite(delta_h_a_per_m, "delta_h_a_per_m")
    if dh < 0.0:
        raise ValueError("delta_h_a_per_m 必须 >=0")
    f = _positive(f_hz, "f_hz")
    omega = 2.0 * math.pi * f
    return GYRO_RAD_S_T * MU_0 * dh / omega


def polder_permeability(
    f_hz: float,
    ms_a_per_m: float,
    h_i_a_per_m: float,
    delta_h_a_per_m: float | None = None,
    alpha: float | None = None,
    h_sat_a_per_m: float | None = None,
) -> PolderResult:
    """饱和铁氧体 Polder 张量磁导率（SI 口径，输出复数 (μ, κ)）。

    f_hz：工作频率（Hz，>0）；ms_a_per_m：饱和磁化强度 Ms（A/m，>0）；
    h_i_a_per_m：内偏置场 H_i（A/m，>0）。

    **饱和判据口径（登记）**：真实饱和条件为内场 H_int = H_app − N·4πMs·
    （几何退磁因子 N 相关）> 0，N 依赖几何，超本内核范围——本内核把 H_i
    一律视为**调用方已做退磁修正的内场**，只强制 H_i > 0（H_i≤0 即偏置
    不足以饱和/反向偏置，ValueError）；如需机器可查的饱和守卫，传
    h_sat_a_per_m（材料口径饱和场下界，如各向异性场+退磁场上界），
    H_i < h_sat 即 ValueError("未饱和")。

    损耗通道（二选一，同给即报错；两者都缺=无损 α=0）：
    - delta_h_a_per_m：共振线宽 ΔH（A/m）→ α = γ·μ0·ΔH/ω；
    - alpha：直接给阻尼/归一化线宽系数（>=0）。

    极限行为（单测钉）：ω→0 时 μ→1+ω_m/ω_h、κ→0；ω→∞ 时 μ→1、κ→0；
    ω=ω_h 共振点 κ 实部 → −ω_m/(4ω_h)（α→0），环行支 μ−κ 实部 →
    1+ω_m/(2ω_h)（有限共振值，见测试文件推导注记）。
    """
    f = _positive(f_hz, "f_hz")
    ms = _positive(ms_a_per_m, "ms_a_per_m")
    h_i = _positive(h_i_a_per_m, "h_i_a_per_m")
    if h_sat_a_per_m is not None:
        h_sat = _positive(h_sat_a_per_m, "h_sat_a_per_m")
        if h_i < h_sat:
            raise ValueError(
                f"未饱和：H_i={h_i} A/m < 饱和场判据 h_sat={h_sat} A/m"
                "（口径见 docstring：本内核要求调用方传入退磁修正后的内场）"
            )
    if delta_h_a_per_m is not None and alpha is not None:
        raise ValueError("delta_h_a_per_m 与 alpha 只能二选一（损耗通道歧义）")
    alpha_val = 0.0
    if delta_h_a_per_m is not None:
        alpha_val = alpha_from_linewidth(delta_h_a_per_m, f)
    elif alpha is not None:
        alpha_val = _finite(alpha, "alpha")
        if alpha_val < 0.0:
            raise ValueError("alpha 必须 >=0")

    omega = 2.0 * math.pi * f
    omega_h = GYRO_RAD_S_T * MU_0 * h_i
    omega_m = GYRO_RAD_S_T * MU_0 * ms
    denom = (omega_h + 1j * alpha_val * omega) ** 2 - omega**2
    if denom == 0:
        raise ValueError(
            "Polder 分母为零（无损 α=0 且 ω=ω_h 的共振奇点，μ/κ 发散）："
            "评估共振点请给出损耗通道（delta_h_a_per_m 或 alpha）"
        )
    mu = 1.0 + omega_m * (omega_h + 1j * alpha_val * omega) / denom
    kappa = omega_m * omega / denom
    return PolderResult(
        f_hz=f,
        ms_a_per_m=ms,
        h_i_a_per_m=h_i,
        alpha=alpha_val,
        omega_rad_s=omega,
        omega_h_rad_s=omega_h,
        omega_m_rad_s=omega_m,
        mu=mu,
        kappa=kappa,
    )


def bosma_far_above_resonance(f_hz: float, ms_a_per_m: float, h_i_a_per_m: float) -> dict:
    """Bosma 原文 Eq.76-78 远共振归一化闭式（独立交叉核对路径，非主实现）。

    返回 {"h", "m", "mu_eff_approx", "kappa_approx", "kappa_over_mu_eff"}：
    H₀ = ω/γ（铁磁共振场）、h = H_i/H₀、m = Ms/H₀（原文 4πM/H₀ 的 SI
    等价：μ0·Ms/H₀·… 归一化后同无量纲）、μ_eff ≈ (h+m)/h（Eq.77）、
    κ ≈ m/h²（Eq.78，归一化频率 ω/ωH₀ = 1）、κ/μ_eff ≈ m/(h(h+m))。
    仅在 ω ≪ ω_h（远共振、κ/μ≪1）近似成立；与 :func:`polder_permeability`
    全式的偏差由单测按原文自报精度（~1%）钉住。
    """
    f = _positive(f_hz, "f_hz")
    ms = _positive(ms_a_per_m, "ms_a_per_m")
    h_i = _positive(h_i_a_per_m, "h_i_a_per_m")
    omega = 2.0 * math.pi * f
    h0 = omega / (GYRO_RAD_S_T * MU_0)  # A/m（铁磁共振场 H₀：ω = γ·μ0·H₀）
    h = h_i / h0
    m = ms / h0
    mu_eff = (h + m) / h
    kappa = m / (h * h)
    return {
        "h": h,
        "m": m,
        "mu_eff_approx": mu_eff,
        "kappa_approx": kappa,
        "kappa_over_mu_eff": kappa / mu_eff,
    }


# ─── 2. 有效磁导率与截止守卫 ─────────────────────────────────────────────────


def mu_effective(mu: complex, kappa: complex) -> complex:
    """盘内模式有效磁导率 μ_eff = (μ²−κ²)/μ（Bosma Eq.13，复数进出）。

    Re(μ_eff) ≤ 0 为截止带（负值合法返回，守卫字段由上层
    :func:`disk_design` 输出 cutoff 标记）。
    """
    mu_c = complex(mu)
    kappa_c = complex(kappa)
    if mu_c == 0:
        raise ValueError("mu=0 无法计算 μ_eff（非物理输入）")
    return (mu_c * mu_c - kappa_c * kappa_c) / mu_c


# ─── 3. J₁′ 第一零点与结盘半径设计 ───────────────────────────────────────────


def j1_prime_first_root() -> float:
    """J₁′(x) 第一正零点 x₁,₁（结环行调整点 kR，Bosma Eq.65：x₁,₁=1.84）。

    数值路径：scipy.special.jvp（Bessel 导数）+ brentq 在 [1.5, 2.5] 内
    求根（J₁′ 在 1.5 处 >0、2.5 处 <0，符号差自证唯一性）；scipy 惰性导入。
    独立核对路径（J₁′ = J₀ − J₁/x 恒等式）与印刷值 1.84118378… 由单测钉。
    """
    import scipy.special as sp
    from scipy.optimize import brentq

    def _j1p(x: float) -> float:
        return float(sp.jvp(1, x, n=1))

    return float(brentq(_j1p, 1.5, 2.5, xtol=1e-14, rtol=1e-15, maxiter=200))


@dataclass(frozen=True)
class DiskDesign:
    """结盘半径设计初值（k·R = x₁,₁ 口径，Bosma Eq.58/65）。"""

    f_hz: float
    er: float
    mu_eff: complex
    k_rad_per_m: float | None
    kr_target: float
    r_mm: float | None
    cutoff: bool
    provenance: dict = field(default_factory=lambda: dict(CIRCULATOR_SYNTHESIS_PROVENANCE))

    def to_dict(self) -> dict:
        """JSON 可序列化（复数拆 re/im）。"""
        return {
            "f_hz": self.f_hz,
            "er": self.er,
            "mu_eff": {"re": self.mu_eff.real, "im": self.mu_eff.imag},
            "k_rad_per_m": self.k_rad_per_m,
            "kr_target": self.kr_target,
            "r_mm": self.r_mm,
            "cutoff": self.cutoff,
            "provenance": dict(self.provenance),
        }


def disk_design(
    f_hz: float,
    er: float,
    ms_a_per_m: float,
    h_i_a_per_m: float,
    delta_h_a_per_m: float | None = None,
    alpha: float | None = None,
    h_sat_a_per_m: float | None = None,
) -> DiskDesign:
    """(f0, εr, Ms, H_i) → 结盘半径 R 初值（毫米）。

    k = ω·√(μ0·ε0·εr·Re(μ_eff))（Bosma Eq.14 的各向同性化口径，取
    Re(μ_eff)，损耗归入 S 矩阵耗散面）；R = x₁,₁/k，x₁,₁ =
    :func:`j1_prime_first_root`（≈1.8412）。Re(μ_eff) ≤ 0 → 截止：
    cutoff=True、r_mm=None、μ_eff 负值如实保留（不做钳位）。
    er：相对介电常数（>0）。
    """
    f = _positive(f_hz, "f_hz")
    er_val = _positive(er, "er")
    polder = polder_permeability(
        f,
        ms_a_per_m,
        h_i_a_per_m,
        delta_h_a_per_m=delta_h_a_per_m,
        alpha=alpha,
        h_sat_a_per_m=h_sat_a_per_m,
    )
    mu_eff_c = mu_effective(polder.mu, polder.kappa)
    kr = j1_prime_first_root()
    mu_eff_re = mu_eff_c.real
    if mu_eff_re <= 0.0:
        return DiskDesign(
            f_hz=f,
            er=er_val,
            mu_eff=mu_eff_c,
            k_rad_per_m=None,
            kr_target=kr,
            r_mm=None,
            cutoff=True,
        )
    k = polder.omega_rad_s * math.sqrt(MU_0 * EPS_0 * er_val * mu_eff_re)
    r_mm = kr / k * 1.0e3
    return DiskDesign(
        f_hz=f,
        er=er_val,
        mu_eff=mu_eff_c,
        k_rad_per_m=k,
        kr_target=kr,
        r_mm=r_mm,
        cutoff=False,
    )


# ─── 4. 理想 / 准理想三端口结 S 矩阵 ─────────────────────────────────────────


def _permutation_matrix(sense: int) -> tuple[tuple[complex, ...], ...]:
    """理想环行置换矩阵：sense=+1 → S21=S32=S13=1；sense=−1 → 反向。"""
    if sense == SENSE_FORWARD:
        return ((0 + 0j, 0 + 0j, 1 + 0j), (1 + 0j, 0 + 0j, 0 + 0j), (0 + 0j, 1 + 0j, 0 + 0j))
    if sense == SENSE_REVERSE:
        return ((0 + 0j, 1 + 0j, 0 + 0j), (0 + 0j, 0 + 0j, 1 + 0j), (1 + 0j, 0 + 0j, 0 + 0j))
    raise ValueError("sense 只能取 +1（1→2→3→1）或 -1（1→3→2→1）")


@dataclass(frozen=True)
class CirculatorSMatrix:
    """三端口结 S 矩阵（理想无耗或准理想均匀耗散口径）。"""

    matrix: tuple[tuple[complex, ...], ...]
    sense: int
    loss_frac: float
    phase_rad: float = 0.0

    @property
    def total_energy(self) -> float:
        """Σ_ij |S_ij|²（无耗=3；耗散口径=3(1−loss)，单调递减）。"""
        return sum(abs(v) ** 2 for row in self.matrix for v in row)

    def to_dict(self) -> dict:
        """JSON 可序列化（复数拆 re/im 的 3×3 嵌套）。"""
        return {
            "matrix": [[{"re": v.real, "im": v.imag} for v in row] for row in self.matrix],
            "sense": self.sense,
            "loss_frac": self.loss_frac,
            "phase_rad": self.phase_rad,
            "total_energy": self.total_energy,
        }


def ideal_junction_s_matrix(sense: int = SENSE_FORWARD, phase_rad: float = 0.0) -> CirculatorSMatrix:
    """理想（无耗对称）三端口结环行器 S 矩阵（Bosma 无耗解极限）。

    环行方向旋量参数化：S = e^{jφ}·P_sense（φ=端口相位参考，3 重旋转
    对称允许的全体系相位）。sense=+1：|S21|=|S32|=|S13|=1 其余 0
    （1→2→3→1）；sense=−1 反向。无耗极限：酉矩阵、总能量 Σ|S|²=3、
    本征值 e^{jφ}·{1, e^{±j2π/3}}（120° 相位序，见
    :func:`junction_eigenvalues`）。
    """
    phi = _finite(phase_rad, "phase_rad")
    rot = cmath.exp(1j * phi)
    mat = tuple(tuple(rot * v for v in row) for row in _permutation_matrix(sense))
    return CirculatorSMatrix(matrix=mat, sense=sense, loss_frac=0.0, phase_rad=phi)


def quasi_ideal_lossy_s_matrix(loss_frac: float, sense: int = SENSE_FORWARD) -> CirculatorSMatrix:
    """准理想带耗散口径：均匀衰减 → 环行项幅值 √(1−loss)。

    **简化面（预声明）**：Bosma 精确场解（Green 函数逐项+端口展宽积分）
    超出本内核范围，此处只做能量守恒口径——单位渡越损耗分数 loss（
    [0,1)）作用于全部环行项幅值，隔离/反射结构不建模。loss=0 退化为
    :func:`ideal_junction_s_matrix`；loss≥1 非物理（环行完全湮灭）报错。
    """
    lf = _finite(loss_frac, "loss_frac")
    if lf < 0.0:
        raise ValueError("loss_frac 必须 >=0（增益口径不物理，超出本简化面）")
    if lf >= 1.0:
        raise ValueError("loss_frac 必须 <1（loss>=1 环行项幅值为零/虚数）")
    scale = math.sqrt(1.0 - lf)
    mat = tuple(tuple(scale * v for v in row) for row in _permutation_matrix(sense))
    return CirculatorSMatrix(matrix=mat, sense=sense, loss_frac=lf)


def magnetic_loss_fraction(polder: PolderResult) -> float:
    """Polder 结果 → 单位渡越磁损耗分数（准理想 S 的 loss 输入，简化面）。

    loss = −Im(μ_eff)/Re(μ_eff)（磁损耗角正切口径；本内核 e^{+jωt} 约定
    下有耗响应 Im(μ)<0，取负号使 loss≥0）。Re(μ_eff)≤0（截止带）或
    loss≥1 报错——该口径下准理想 S 不成立。**登记**：渡越次数/场分布
    依赖的精确插损是 Bosma 场解范畴，本式只是能量守恒口径的量级入口。
    """
    mu_eff_c = mu_effective(polder.mu, polder.kappa)
    if mu_eff_c.real <= 0.0:
        raise ValueError("Re(μ_eff)<=0（截止带）：准理想耗散口径不适用")
    loss = -mu_eff_c.imag / mu_eff_c.real
    if loss < 0.0:
        raise ValueError("Im(μ_eff)>0（增益型响应）超出本简化面")
    if loss >= 1.0:
        raise ValueError(f"磁损耗分数 loss={loss}>=1：准理想口径不适用（深损耗带）")
    return 0.0 if loss == 0.0 else loss


def junction_eigenvalues(s_matrix: CirculatorSMatrix) -> tuple[complex, ...]:
    """3×3 S 矩阵本征值（按辐角排序）。

    理想环行矩阵本征值 = e^{jφ}·{1, e^{±j2π/3}}——三重旋转对称的 120°
    相位序（环行方向的旋量表征）；耗散口径整体系数 √(1−loss)。
    用 numpy 全特征分解（对 monomial 矩阵无病态），测试侧另以解析值
    双路径核对。
    """
    arr = np.array([[complex(v) for v in row] for row in s_matrix.matrix])
    eigs = np.linalg.eigvals(arr)
    ordered = sorted((complex(e) for e in eigs), key=cmath.phase)
    return tuple(ordered)


# ─── 5. Wu-Rosenbaum 带宽登记（不臆造数字） ──────────────────────────────────


def wu_rosenbaum_bandwidth_reference(f_low_hz: float) -> dict:
    """Wu-Rosenbaum 倍频程带宽登记（只登记出处+算术恒等式，UNVERIFIED 显式标）。

    **已核实（二手文献一致转述）**：Wu & Rosenbaum 1974（MTT-22(10):
    849-856）给出微带环形器倍频程（2:1）带宽设计法——弱耦合条件+减小
    耦合角。**UNVERIFIED**：原文未读，精确的"隔离度-分数带宽上限百分比"
    数字（如某隔离度下 ~N%）不可达单源，不内嵌（任务书预声明纪律：
    不臆造数字）。另有 Bosma 原文自报实验锚（第一手）：端口串联 LC 补偿
    后 310-420 MHz 带宽 ~30%、VSWR≤1.2、隔离 ≥19.5 dB、插损 ≤1.1 dB
    （原文 §Bandwidth Enlargement verbatim），作量级旁证登记。

    返回 f_low_hz 对应倍频程带的算术恒等式：f_high=2·f_low、几何中心
    √(f1·f2)、分数带宽（算术中心 2/3、几何中心 1/√2）。
    """
    f1 = _positive(f_low_hz, "f_low_hz")
    f2 = 2.0 * f1
    f_geo = math.sqrt(f1 * f2)
    return {
        "f_low_hz": f1,
        "f_high_hz": f2,
        "f_center_arith_hz": 0.5 * (f1 + f2),
        "f_center_geo_hz": f_geo,
        "fbw_arith": (f2 - f1) / (0.5 * (f1 + f2)),
        "fbw_geo": (f2 - f1) / f_geo,
        "claim_verified": "octave(2:1) bandwidth design via weak coupling / reduced coupling angle",
        "claim_source": CIRCULATOR_SYNTHESIS_PROVENANCE["wu_rosenbaum"],
        "unverified": [
            "精确隔离度-带宽上限百分比（原文未读，二手文献不给数）",
        ],
        "bosma_experiment_anchor": {
            "band_mhz": [310.0, 420.0],
            "bandwidth_frac": 1.0 / 3.0,
            "vswr_max": 1.2,
            "isolation_db_min": 19.5,
            "insertion_loss_db_max": 1.1,
            "source": "Bosma 1964 §Bandwidth Enlargement（原文第一手）",
        },
    }


# ─── 6. 耦合角 / 匹配 ────────────────────────────────────────────────────────


def quarter_wave_transformer_impedance(z_junction_ohm: float, z0_ohm: float = 50.0) -> float:
    """λ/4 变换段特性阻抗 Z_T = √(Z_j·Z0)（传输线教科书恒等式）。

    结阻抗 Z_j → 50 Ω 系统的单节匹配初值；z_junction_ohm/z0_ohm 均 >0。
    """
    zj = _positive(z_junction_ohm, "z_junction_ohm")
    z0 = _positive(z0_ohm, "z0_ohm")
    return math.sqrt(zj * z0)


def coupling_angle_from_stripline_width(r_mm: float, v_mm: float) -> float:
    """耦合角 ψ = arcsin(v/(2R))（Bosma Eq.8 verbatim，弧度）。

    r_mm：盘半径（mm，>0）；v_mm：带线宽（mm，>0，v ≤ 2R 否则非物理）。
    """
    r = _positive(r_mm, "r_mm")
    v = _positive(v_mm, "v_mm")
    if v > 2.0 * r:
        raise ValueError(f"v={v} mm > 2R={2.0 * r} mm：带线宽超出盘周非物理")
    return math.asin(v / (2.0 * r))


def stripline_width_from_coupling_angle(r_mm: float, psi_rad: float) -> float:
    """Bosma Eq.8 反演：v = 2R·sin(ψ)（mm）；ψ ∈ (0, π/2]。"""
    r = _positive(r_mm, "r_mm")
    psi = _finite(psi_rad, "psi_rad")
    if not 0.0 < psi <= math.pi / 2.0:
        raise ValueError("psi_rad 必须在 (0, π/2]")
    return 2.0 * r * math.sin(psi)


def bosma_coupling_angle_estimate(
    kappa_over_mu: float, mu_eff_re: float, er: float
) -> dict:
    """环行条件耦合角初值估计 ψ ≈ (π/4)·(κ/μ)·√(εr/μ_eff)。

    **UNVERIFIED（显式登记）**：对应 Bosma 原文 Eq.69（环行条件的
    κ/μ-耦合角关系）；原文 PDF 文本层数学区乱码，系数 (4/π) 的位置
    无法逐位核对。用原文自报设计点反核：κ/μ=0.112、μ_eff≈2.89、
    εr=14.2 → 本式给 ψ≈0.195 rad，而原文几何 v/R=0.48 → ψ_actual =
    arcsin(0.24) ≈ 0.2424 rad——**偏低 ~20%（量级正确）**。仅作初值
    生成辅助，最终耦合角以真机/HFSS 仲裁窗为准；不通过本式做任何
    判定（#122：判据先行，UNVERIFIED 不进判）。
    """
    km = _finite(kappa_over_mu, "kappa_over_mu")
    mue = _positive(mu_eff_re, "mu_eff_re")
    er_val = _positive(er, "er")
    psi = (math.pi / 4.0) * km * math.sqrt(er_val / mue)
    return {
        "psi_rad": psi,
        "unverified": [
            "Bosma Eq.69 系数 (4/π) 位置：原文 PDF 文本层乱码，未经第二来源逐位核对；"
            "对原文设计点自核偏差 ~20%",
        ],
        "provenance": CIRCULATOR_SYNTHESIS_PROVENANCE["bosma"]
        + " Eq.69（UNVERIFIED 系数）",
    }


# ─── 7. 集总 LC 环形器（Konishi 1965 低频版，简化面） ────────────────────────


@dataclass(frozen=True)
class LumpedLCCirculator:
    """三对称 LC 集总环形器低频版（谐振恒等式 + 理想环行 S）。"""

    l_h: float
    c_f: float
    f0_hz: float
    sense: int
    s_matrix: CirculatorSMatrix
    provenance: dict = field(default_factory=lambda: dict(CIRCULATOR_SYNTHESIS_PROVENANCE))

    def to_dict(self) -> dict:
        """JSON 可序列化。"""
        return {
            "l_h": self.l_h,
            "c_f": self.c_f,
            "f0_hz": self.f0_hz,
            "sense": self.sense,
            "s_matrix": self.s_matrix.to_dict(),
            "provenance": dict(self.provenance),
        }


def lumped_lc_circulator(l_h: float, c_f: float, sense: int = SENSE_FORWARD) -> LumpedLCCirculator:
    """三对称 L、C → 集总环行频率 f₀ = 1/(2π√(LC)) + 理想环行 S。

    **简化面（预声明）**：Konishi (1965) 集总环形器的非互易耦合场模型
    超出本内核范围；此处只实现任务书钉死的恒等式面——三支路对称
    L（H）、C（F）的 LC 谐振恒等式（逐位可逆）+ 理想环行 S 矩阵的
    120° 旋转对称（S = P·S·P⁻¹，本征值 120° 相位序）。l_h/c_f >0。
    """
    l_val = _positive(l_h, "l_h")
    c_val = _positive(c_f, "c_f")
    f0 = 1.0 / (2.0 * math.pi * math.sqrt(l_val * c_val))
    s_mat = ideal_junction_s_matrix(sense=sense)
    return LumpedLCCirculator(l_h=l_val, c_f=c_val, f0_hz=f0, sense=sense, s_matrix=s_mat)


def cyclic_permutation_similarity(s_matrix: CirculatorSMatrix) -> bool:
    """检查 3×3 S 满足 120° 旋转对称 S = P·S·P⁻¹（P=循环置换，1→2→3）。

    P 取 sense=+1 的理想环行矩阵（纯实置换）；对理想/准理想环行 S
    恒成立（S 与 P 可交换——同为循环代数元），任意打破 3 重对称的
    矩阵不成立。浮点比较容差 1e-12（相对）。
    """
    p = np.array(_permutation_matrix(SENSE_FORWARD), dtype=complex)
    s = np.array([[complex(v) for v in row] for row in s_matrix.matrix])
    lhs = p @ s @ p.T  # P⁻¹ = Pᵀ（置换矩阵正交）
    scale = max(1.0, float(np.max(np.abs(s))))
    return bool(np.max(np.abs(lhs - s)) <= 1e-12 * scale)
