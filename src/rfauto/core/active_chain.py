"""有源链路确定性内核（LNA/PA 匹配+噪声+load-pull 口径）。

设计范围:
    "LNA/PA 匹配网络 EM 提取+ADS 非线性/噪声协同（场-路：EM S 参数进 ADS
    电路层）；PA 验收含 ADS 负载牵引仿真口径（谐波平衡 load-pull，无需硬件）；
    匹配网络 EM↔ADS 联合 vs 手工口径；load-pull 等增益/等功率圈合理性"。

本模块只放零依赖（numpy）的确定性射频内核，全部公式为教科书口径
（Pozar《Microwave Engineering》ch.12 有源网络稳定性/增益/噪声；
Cripps《RF Power Amplifiers for Wireless Communications》ch.3 解析
load-pull 恒功率圈），LLM 不参与任何数值。

口径说明:
- 增益内核接受 2x2 S 矩阵（单频点）+ 源/负载反射系数 ΓS/ΓL；
- 双共轭匹配（K>1 无条件稳定时）给出 ΓMS/ΓML 与匹配点最大增益（独立
  电路求解双侧验证，见 simultaneous_conjugate_match docstring）；
- 恒增益圈/恒噪声圈给圆心+半径（Smith 图口径）；
- Cripps load-pull：器件输出建模为理想基波电流源（限幅 Isw=I_max）∥ C_out，
  电压摆幅限 Vsw=VDD−V_knee——P(ΓL) 有闭式（admittance 平面上恒功率集
  是过原点圆族，Möbius 变换到 Γ 平面仍是广义圆），等功率圈的"圆性/嵌套/
  最优点"可离线数值裁判，无需真机。
- 混合π小信号模型 Y 参数→S 参数（源极接地 2 端口），供合成 LNA/PA
  测试器件（与 load-pull 物理同源）。

诚实边界: Cripps 恒功率圈是解析近似（单级、基波、电流源∥Cout 模型），
不替代 ADS 谐波平衡真机 load-pull（B 档通道见 linkage/ads_active_chain）；
两者的一致性验收按 field_circuit_anchor 同款"注入 sim 只验管线、真机承载
验收数字"的纪律分层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 默认系统阻抗（欧）。
DEFAULT_Z0 = 50.0

_EPS = 1e-15


# --------------------------------------------------------------------------- #
# 反射系数 / 阻抗互转
# --------------------------------------------------------------------------- #
def gamma_to_z(gamma: complex, z0: float = DEFAULT_Z0) -> complex:
    """反射系数 → 阻抗（z = z0 (1+Γ)/(1−Γ)，Γ=1 发散处返回 inf+infj）。"""
    gamma = complex(gamma)
    if abs(1.0 - gamma) < _EPS:
        return complex(float("inf"), float("inf"))
    return z0 * (1.0 + gamma) / (1.0 - gamma)


def z_to_gamma(z: complex, z0: float = DEFAULT_Z0) -> complex:
    """阻抗 → 反射系数（Γ = (z−z0)/(z+z0)）。"""
    z = complex(z)
    if abs(z + z0) < _EPS:
        return complex(float("inf"), 0.0)
    return (z - z0) / (z + z0)


# --------------------------------------------------------------------------- #
# 稳定性与增益内核（Pozar ch.12）
# --------------------------------------------------------------------------- #
@dataclass
class StabilityMargins:
    """稳定性余量（单频点 2 端口）。

    K>1 且 |Δ|<1 为无条件稳定（Rollett 判据双条件）；
    μ>1 与之等价（Edwards-Sinsky），一并给出。
    """

    k_factor: float
    delta_abs: float
    mu_factor: float
    unconditionally_stable: bool

    def to_dict(self) -> dict[str, Any]:
        def _r(v: float) -> float | None:
            v = float(v)
            return round(v, 6) if np.isfinite(v) else None

        return {
            "k_factor": _r(self.k_factor),
            "delta_abs": _r(self.delta_abs),
            "mu_factor": _r(self.mu_factor),
            "unconditionally_stable": self.unconditionally_stable,
        }


def stability_margins(s: np.ndarray) -> StabilityMargins:
    """Rollett K / |Δ| / Edwards-Sinsky μ（单频点 2x2 S 矩阵）。

    与 core/cosim.check_stability_k 的 K/μ 公式同源（一致性由单测钉死）。
    """
    s = np.asarray(s, dtype=complex)
    if s.shape != (2, 2):
        raise ValueError(f"期望 2x2 S 矩阵, 得到 {s.shape}")
    s11, s12, s21, s22 = s[0, 0], s[0, 1], s[1, 0], s[1, 1]
    delta = s11 * s22 - s12 * s21
    d_abs = abs(delta)
    denom = 2.0 * abs(s12) * abs(s21)
    k = float("inf") if denom < _EPS else (1 - abs(s11) ** 2 - abs(s22) ** 2 + d_abs**2) / denom
    mu_den = abs(s22 - delta * np.conj(s11)) + abs(s12) * abs(s21)
    mu = float("inf") if mu_den < _EPS else (1 - abs(s11) ** 2) / mu_den
    return StabilityMargins(
        k_factor=k, delta_abs=d_abs, mu_factor=mu,
        unconditionally_stable=bool(k > 1 and d_abs < 1),
    )


def _unpack(s: np.ndarray) -> tuple[complex, complex, complex, complex]:
    s = np.asarray(s, dtype=complex)
    if s.shape != (2, 2):
        raise ValueError(f"期望 2x2 S 矩阵, 得到 {s.shape}")
    return s[0, 0], s[0, 1], s[1, 0], s[1, 1]


def input_gamma(s: np.ndarray, gamma_l: complex) -> complex:
    """输入反射系数 Γin = S11 + S12·S21·ΓL/(1−S22·ΓL)。"""
    s11, s12, s21, s22 = _unpack(s)
    return s11 + s12 * s21 * gamma_l / (1.0 - s22 * gamma_l)


def output_gamma(s: np.ndarray, gamma_s: complex) -> complex:
    """输出反射系数 Γout = S22 + S12·S21·ΓS/(1−S11·ΓS)。"""
    s11, s12, s21, s22 = _unpack(s)
    return s22 + s12 * s21 * gamma_s / (1.0 - s11 * gamma_s)


def transducer_gain_db(s: np.ndarray, gamma_s: complex, gamma_l: complex) -> float:
    """变换增益 GT（dB），任意 ΓS/ΓL 双线性精确公式。

    GT = |S21|² (1−|ΓS|²)(1−|ΓL|²) / |(1−S11ΓS)(1−S22ΓL) − S12S21ΓSΓL|²
    （与 Pozar 分式形式 |1−ΓinΓS| 等价, 恒等式由单测钉死。）
    """
    s11, s12, s21, s22 = _unpack(s)
    num = abs(s21) ** 2 * (1 - abs(gamma_s) ** 2) * (1 - abs(gamma_l) ** 2)
    den = abs((1 - s11 * gamma_s) * (1 - s22 * gamma_l) - s12 * s21 * gamma_s * gamma_l) ** 2
    if den < _EPS:
        return float("-inf")
    return 10.0 * np.log10(num / den + _EPS)


def unilateral_transducer_gain_db(s: np.ndarray, gamma_s: complex, gamma_l: complex) -> float:
    """单向变换增益 GTU（dB，忽略 S12）。

    GTU = |S21|²(1−|ΓS|²)(1−|ΓL|²)/(|1−S11ΓS|²|1−S22ΓL|²)
    """
    s11, _, s21, s22 = _unpack(s)
    num = abs(s21) ** 2 * (1 - abs(gamma_s) ** 2) * (1 - abs(gamma_l) ** 2)
    den = abs(1 - s11 * gamma_s) ** 2 * abs(1 - s22 * gamma_l) ** 2
    if den < _EPS:
        return float("-inf")
    return 10.0 * np.log10(num / den + _EPS)


def operating_power_gain_db(s: np.ndarray, gamma_l: complex) -> float:
    """工作功率增益 GP（dB，与源端无关）。

    GP = |S21|²(1−|ΓL|²)/((1−|Γin|²)|1−S22ΓL|²), Γin 见 input_gamma。
    """
    s11, s12, s21, s22 = _unpack(s)
    gin = s11 + s12 * s21 * gamma_l / (1.0 - s22 * gamma_l)
    num = abs(s21) ** 2 * (1 - abs(gamma_l) ** 2)
    den = (1 - abs(gin) ** 2) * abs(1 - s22 * gamma_l) ** 2
    if den < _EPS:
        return float("-inf")
    return 10.0 * np.log10(num / den + _EPS)


def available_power_gain_db(s: np.ndarray, gamma_s: complex) -> float:
    """可用功率增益 GA（dB，与负载端无关）。

    GA = |S21|²(1−|ΓS|²)/((1−|Γout|²)|1−S11ΓS|²), Γout 见 output_gamma。
    """
    s11, s12, s21, s22 = _unpack(s)
    gout = s22 + s12 * s21 * gamma_s / (1.0 - s11 * gamma_s)
    num = abs(s21) ** 2 * (1 - abs(gamma_s) ** 2)
    den = (1 - abs(gout) ** 2) * abs(1 - s11 * gamma_s) ** 2
    if den < _EPS:
        return float("-inf")
    return 10.0 * np.log10(num / den + _EPS)


@dataclass
class ConjugateMatchResult:
    """双共轭匹配结果（ΓMS/ΓML + GT,max）。"""

    gamma_s: complex
    gamma_l: complex
    gt_max_db: float
    margins: StabilityMargins

    def to_dict(self) -> dict[str, Any]:
        return {
            "gamma_s": {"re": round(self.gamma_s.real, 9), "im": round(self.gamma_s.imag, 9)},
            "gamma_l": {"re": round(self.gamma_l.real, 9), "im": round(self.gamma_l.imag, 9)},
            "gt_max_db": round(self.gt_max_db, 6),
            "stability": self.margins.to_dict(),
        }


def simultaneous_conjugate_match(s: np.ndarray) -> ConjugateMatchResult:
    """双共轭匹配（ΓMS/ΓML 闭式二次方程解，需 K>1 且 |Δ|<1）。

    ΓMS = (B1 ± √(B1²−4|C1|²))/(2C1)，取使 |ΓMS|<1 的符号；ΓML 同理（B2/C2）。
    GT,max = GT(ΓMS,ΓML)（在匹配点直接求值——本内核已经独立 ABCD 电路
    暴力求解与 Γ 网格搜索双侧验证：匹配点处 GT=GP=GA 且为全局最大；
    常被引用的 |S21/S12|·(K−√(K²−4)) 闭式在本内核数值检验中被证伪
    （无源 6dB 衰减器例: 闭式给 +1.58dB、真值 −6dB），不采用。
    K=1 稳定边界处的最大增益即 MSG = |S21/S12|，本函数结果恒 ≤ MSG。

    单向器件（S12≈0, K→∞）走精确单向分支：ΓMS=S11*, ΓML=S22*，
    GT,max = |S21|²/((1−|S11|²)(1−|S22|²))（教科书闭式）。

    器件不稳定（K≤1 或 |Δ|≥1）时 ValueError——此时双共轭匹配无定义，
    不得给出"匹配到不稳定点"的方案。
    """
    s11, s12, s21, s22 = _unpack(s)
    margins = stability_margins(s)
    if not margins.unconditionally_stable:
        raise ValueError(
            f"器件非无条件稳定 (K={margins.k_factor:.3f}, |Δ|={margins.delta_abs:.3f}), "
            "双共轭匹配无定义; 请先加稳定网络或改用有条件稳定搜索"
        )
    if abs(s12) < 1e-12:
        # 单向精确分支（K=inf 也在此路径）
        gamma_s = np.conj(s11)
        gamma_l = np.conj(s22)
        gt_max = unilateral_transducer_gain_db(s, gamma_s, gamma_l)
        return ConjugateMatchResult(
            gamma_s=complex(gamma_s), gamma_l=complex(gamma_l),
            gt_max_db=gt_max, margins=margins,
        )
    delta = s11 * s22 - s12 * s21
    b1 = 1 + abs(s11) ** 2 - abs(s22) ** 2 - abs(delta) ** 2
    b2 = 1 + abs(s22) ** 2 - abs(s11) ** 2 - abs(delta) ** 2
    c1 = s11 - delta * np.conj(s22)
    c2 = s22 - delta * np.conj(s11)

    def _pick(b: float, c: complex) -> complex:
        disc = b * b - 4.0 * abs(c) ** 2
        if disc < 0:
            if disc > -1e-9:
                disc = 0.0  # 浮点边缘（|Sii|≈1 的纯电抗输入）
            else:
                raise ValueError("双共轭匹配判别式为负（不应发生在 K>1 器件上）")
        root = np.sqrt(disc)
        if abs(c) < _EPS:
            return complex(0.0, 0.0)  # C1=0（如匹配衰减器）: Γ=0 即共轭匹配
        plus = (b + root) / (2.0 * c)
        minus = (b - root) / (2.0 * c)
        for cand in (minus, plus):
            if abs(cand) < 1.0:
                return cand
        raise ValueError("B1/B2 两符号均给出 |Γ|≥1（数值异常）")

    gamma_s = _pick(b1, c1)
    gamma_l = _pick(b2, c2)
    gt_max_db = transducer_gain_db(s, gamma_s, gamma_l)
    return ConjugateMatchResult(
        gamma_s=complex(gamma_s), gamma_l=complex(gamma_l),
        gt_max_db=gt_max_db, margins=margins,
    )


@dataclass
class Circle:
    """Smith 图上的广义圆（恒增益/恒噪声/恒功率圈统一形态）。"""

    center: complex
    radius: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": {"re": round(self.center.real, 9), "im": round(self.center.imag, 9)},
            "radius": round(self.radius, 9),
        }


def constant_gain_circle(
    s: np.ndarray, gain_db: float, side: str = "output",
) -> Circle:
    """单向恒增益圈（精确条件 S12=0；小 S12 时为近似）。

    圆族方程 g = (1−|Γ|²)/|1−Sii·Γ|²（g = 目标增益/|S21|²）配方得:
    center = g·conj(Sii)/(1+g|Sii|²), radius = √(1−g(1−|Sii|²))/(1+g|Sii|²)。
    （配方恒等式已由"圈上点增益 == 目标增益"数值检验钉死到 1e-15。）
    side="output": 负载侧恒 GTU 圈（ΓL 平面）; side="input": 源侧恒 GA 圈。
    增益超出该侧可达范围（g ≤ 1/(1−|Sii|²)）时 ValueError。
    """
    s11, _, s21, s22 = _unpack(s)
    if side not in ("input", "output"):
        raise ValueError(f"side 须为 input/output, 得到 {side!r}")
    sii = s11 if side == "input" else s22
    g = 10.0 ** (gain_db / 10.0) / abs(s21) ** 2  # 侧增益因子 gs / gl
    sii2 = abs(sii) ** 2
    g_max = 1.0 / (1.0 - sii2)
    if g <= 0 or g > g_max + 1e-9:
        raise ValueError(
            f"增益 {gain_db:.3f} dB 超出 {side} 侧可达范围 (上限 "
            f"{10 * np.log10(g_max * abs(s21) ** 2):.3f} dB)"
        )
    denom = 1.0 + g * sii2
    center = g * np.conj(sii) / denom
    rad_term = 1.0 - g * (1.0 - sii2)
    radius = 0.0 if rad_term <= 0 else float(np.sqrt(rad_term) / denom)
    return Circle(center=complex(center), radius=radius)


# --------------------------------------------------------------------------- #
# 噪声内核（Pozar 12.33-12.36）
# --------------------------------------------------------------------------- #
def noise_figure_db(
    fmin_db: float, gamma_opt: complex, rn_norm: float, gamma_s: complex,
) -> float:
    """噪声系数 F(ΓS)（dB）。

    F = Fmin + 4·rn·|ΓS−Γopt|² / ((1−|ΓS|²)|1+Γopt|²)，rn=Rn/Z0 归一化。
    """
    gamma_opt = complex(gamma_opt)
    gamma_s = complex(gamma_s)
    fmin = 10.0 ** (fmin_db / 10.0)
    num = 4.0 * rn_norm * abs(gamma_s - gamma_opt) ** 2
    den = (1.0 - abs(gamma_s) ** 2) * abs(1.0 + gamma_opt) ** 2
    if den < _EPS:
        return float("inf")
    return 10.0 * np.log10(fmin + num / den)


def noise_figure_circle(
    fmin_db: float, gamma_opt: complex, rn_norm: float, f_db: float,
) -> Circle:
    """恒噪声系数圈（ΓS 平面）。

    由 F−Fmin = 4rn|ΓS−Γopt|²/((1−|ΓS|²)|1+Γopt|²) 配方（注意分母是
    |1+Γopt|²，非 1+|Γopt|²）:
    N = (F−Fmin)|1+Γopt|²/(4rn); center = Γopt/(1+N);
    radius = √(N(N+1−|Γopt|²))/(1+N)。
    圈上点回代 F == 目标（恒等式检验钉死到 1e-15）。
    f_db < Fmin 时 ValueError。
    """
    gamma_opt = complex(gamma_opt)
    f_min = 10.0 ** (fmin_db / 10.0)
    f_t = 10.0 ** (f_db / 10.0)
    if f_t < f_min - 1e-12:
        raise ValueError(f"目标噪声 {f_db:.3f} dB 低于 Fmin {fmin_db:.3f} dB")
    y_opt = abs(1.0 + gamma_opt) ** 2
    n = (f_t - f_min) * y_opt / (4.0 * rn_norm)
    center = gamma_opt / (1.0 + n)
    radius = float(np.sqrt(n * (n + 1.0 - abs(gamma_opt) ** 2)) / (1.0 + n))
    return Circle(center=complex(center), radius=radius)


# --------------------------------------------------------------------------- #
# 混合π 小信号模型（合成测试器件, 与 load-pull 物理同源）
# --------------------------------------------------------------------------- #
@dataclass
class HybridPiModel:
    """共源混合π小信号模型（源极接地, 2 端口 G/D）。

    单位: gm [S], rds [Ω], 电容 [F]。物理口径与 Cripps load-pull 的
    输出电流源∥Cout 一致（Cout=Cds）。
    rg_ohm: 栅串联电阻（真实工艺寄生）。纯电容输入使 |S11|=1、K 恒差——
    加 rg 后才能合成 K>1 的无条件稳定器件（与真实 FET 口径一致）。
    """

    gm_s: float
    rds_ohm: float
    cgs_f: float
    cds_f: float
    cgd_f: float = 0.0
    rg_ohm: float = 0.0

    def yparams(self, f_hz: float) -> np.ndarray:
        """节点导纳矩阵 [[Y11,Y12],[Y21,Y22]]（源极接地）。"""
        w = 2.0 * np.pi * f_hz
        gds = 1.0 / self.rds_ohm
        jw = 1j * w
        return np.array([
            [jw * (self.cgs_f + self.cgd_f), -jw * self.cgd_f],
            [self.gm_s - jw * self.cgd_f, gds + jw * (self.cds_f + self.cgd_f)],
        ], dtype=complex)

    def to_sparams(self, f_hz: float, z0: float = DEFAULT_Z0) -> np.ndarray:
        """Y 参数 → S 参数（含栅串联电阻 rg 的 ABCD 级联）。

        Y→ABCD: A=−Y22/Y21, B=−1/Y21, C=−ΔY/Y21, D=−Y11/Y21;
        ABCD→S（未归一 B/z0, C·z0）按标准四式。Y21≈0 时 ValueError。
        """
        y = self.yparams(f_hz)
        if abs(y[1, 0]) < _EPS:
            raise ValueError("Y21≈0, 无法变换 ABCD")
        dy = y[0, 0] * y[1, 1] - y[0, 1] * y[1, 0]
        abcd = np.array([
            [-y[1, 1] / y[1, 0], -1.0 / y[1, 0]],
            [-dy / y[1, 0], -y[0, 0] / y[1, 0]],
        ], dtype=complex)
        if self.rg_ohm > 0:
            series = np.array([[1.0, complex(self.rg_ohm)], [0.0, 1.0]], dtype=complex)
            abcd = series @ abcd
        a, b, c, d = abcd[0, 0], abcd[0, 1] / z0, abcd[1, 0] * z0, abcd[1, 1]
        denom = a + b + c + d
        return np.array([
            [(a + b - c - d) / denom, 2.0 * (a * d - b * c) / denom],
            [2.0 / denom, (-a + b - c + d) / denom],
        ], dtype=complex)


# --------------------------------------------------------------------------- #
# Cripps 解析 load-pull（PA 恒功率圈口径）
# --------------------------------------------------------------------------- #
@dataclass
class LoadPullDevice:
    """Cripps load-pull 器件物理参数（限幅电流源 ∥ C_out 口径）。

    vdd_v: 漏极供电电压; imax_a: 最大基波电流摆幅（Isw）;
    vknee_v: 膝点电压（默认 0.5V 量级）; cout_f: 输出电容（与混合π Cds 同源）。
    """

    vdd_v: float
    imax_a: float
    cout_f: float
    vknee_v: float = 0.3

    @property
    def vsw_v(self) -> float:
        """可用电压摆幅 Vsw = VDD − V_knee。"""
        return self.vdd_v - self.vknee_v

    @property
    def gopt_s(self) -> float:
        """最优负载电导 G_opt = Isw / Vsw（1/Ropt）。"""
        if self.vsw_v <= 0:
            raise ValueError("VDD 必须大于膝点电压")
        return self.imax_a / self.vsw_v

    def optimal_load_impedance(self, f_hz: float, z0: float = DEFAULT_Z0) -> complex:
        """最优负载阻抗 Z_L,opt = 1/(G_opt − jωC_out)（使 Y_t 实化为 G_opt）。

        z0 形参仅为接口对称（Γ 口径需 z0），阻抗口径不依赖它。
        """
        w = 2.0 * np.pi * f_hz
        return 1.0 / (self.gopt_s - 1j * w * self.cout_f)

    def optimal_gamma(self, f_hz: float, z0: float = DEFAULT_Z0) -> complex:
        """最优负载反射系数 Γ_L,opt（等功率圈顶点）。"""
        return z_to_gamma(self.optimal_load_impedance(f_hz, z0), z0)

    def max_power_dbm(self) -> float:
        """Class-A 式最大基波输出功率 Pmax = Vsw·Isw/2（dBm）。"""
        return 10.0 * np.log10(0.5 * self.vsw_v * self.imax_a / 1e-3)


def load_pull_power_dbm(
    gamma_l: np.ndarray | complex,
    device: LoadPullDevice,
    f_hz: float,
    z0: float = DEFAULT_Z0,
) -> np.ndarray:
    """给定负载反射系数网格的基波输出功率（dBm, Cripps 模型闭式）。

    物理口径: 漏极节点 Y_t = Y_L + jωC_out; 基波电流幅 |I1| =
    min(Isw, Vsw·|Y_t|)（电流限幅/电压摆幅限幅统一式）;
    P = 0.5·|I1|²·Re{Y_L}/|Y_t|²。
    Re{Y_L}≤0（负阻/开路数值奇异）的点判 P=−inf（无功率交付）。
    """
    gamma_arr = np.atleast_1d(np.asarray(gamma_l, dtype=complex))
    w = 2.0 * np.pi * f_hz
    z = np.where(
        np.abs(1.0 - gamma_arr) < _EPS,
        complex(np.inf, np.inf),
        z0 * (1.0 + gamma_arr) / (1.0 - gamma_arr),
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        y_l = np.where(np.isfinite(z), 1.0 / z, 0.0)
    y_t = y_l + 1j * w * device.cout_f
    gl = y_l.real
    valid = np.isfinite(z) & (gl > 0) & (np.abs(y_t) > _EPS)
    i1 = np.minimum(device.imax_a, device.vsw_v * np.abs(y_t))
    p = np.where(valid, 0.5 * i1**2 * gl / np.abs(y_t) ** 2, 0.0)
    with np.errstate(divide="ignore"):
        p_dbm = 10.0 * np.log10(np.where(p > 0, p, np.nan) / 1e-3)
    p_dbm = np.where(valid, p_dbm, -np.inf)
    return p_dbm[0] if np.ndim(gamma_l) == 0 else p_dbm


@dataclass
class LoadPullScan:
    """load-pull 扫描结果（ΓL 极坐标网格 + 功率/增益面 + 解析等功率线）。"""

    gamma_mag: np.ndarray      # |ΓL| 网格（轴 0）
    gamma_phase: np.ndarray    # arg(ΓL) 网格（轴 1）
    power_dbm: np.ndarray
    gain_db: np.ndarray | None
    f_hz: float
    z0: float
    device: LoadPullDevice
    contours: list[dict[str, Any]] = field(default_factory=list)

    def gamma_grid(self) -> np.ndarray:
        """ΓL 复数网格 = mag·exp(j·phase)。"""
        return self.gamma_mag * np.exp(1j * self.gamma_phase)

    def to_dict(self, max_grid: int = 40) -> dict[str, Any]:
        """JSON 摘要（网格降采样, 解析等功率线与最优点全量保留）。"""
        step = max(1, self.gamma_mag.size // max_grid)
        return {
            "f_hz": self.f_hz,
            "z0": self.z0,
            "gamma_mag_sub": np.round(self.gamma_mag[::step, ::step], 6).tolist(),
            "gamma_phase_sub": np.round(self.gamma_phase[::step, ::step], 6).tolist(),
            "power_dbm_sub": np.round(self.power_dbm[::step, ::step], 4).tolist(),
            "contours": self.contours,
            "optimum": self.optimum_dict(),
        }

    def optimum_dict(self) -> dict[str, Any]:
        flat = np.where(np.isfinite(self.power_dbm), self.power_dbm, -np.inf)
        idx = np.unravel_index(int(np.argmax(flat)), self.power_dbm.shape)
        g_opt_grid = complex(self.gamma_mag[idx] * np.exp(1j * self.gamma_phase[idx]))
        pred = self.device.optimal_gamma(self.f_hz, self.z0)
        return {
            "gamma_grid": {"re": round(g_opt_grid.real, 6), "im": round(g_opt_grid.imag, 6)},
            "gamma_model": {"re": round(pred.real, 6), "im": round(pred.imag, 6)},
            "gamma_dist": round(float(abs(g_opt_grid - pred)), 6),
            "power_dbm": round(float(self.power_dbm[idx]), 4),
            "power_model_dbm": round(self.device.max_power_dbm(), 4),
        }


def _fit_circle(points: np.ndarray) -> tuple[complex, float, float]:
    """代数（Kåsa）最小二乘圆拟合 → (圆心, 半径, rms 残差/半径)。"""
    x = points.real
    y = points.imag
    a = np.column_stack([2.0 * x, 2.0 * y, np.ones_like(x)])
    b = x**2 + y**2
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy, c = sol
    center = complex(cx, cy)
    radius = float(np.sqrt(c + cx**2 + cy**2))
    resid = np.abs(np.abs(points - center) - radius)
    rel = float(np.sqrt(np.mean(resid**2)) / max(radius, _EPS))
    return center, radius, rel


def cripps_contour_locus(
    device: LoadPullDevice, f_hz: float, backoff_db: float, z0: float = DEFAULT_Z0,
) -> dict[str, Any]:
    """Cripps 等功率线的解析闭式（电流限弧 + 电压限弦, Yt 平面）。

    物理口径（与 load_pull_power_dbm 严格同源）:
    Yt = YL + jωC_out ≡ G + jBt。P = 0.5·min(Isw, Vsw|Yt|)²·G/|Yt|²,
    p = P/Pmax = 10^(−backoff/10):
    - 电流限分支（|Yt| ≥ G_opt）: Norton 圆 (G−g0)² + Bt² = g0², g0 = G_opt/(2p);
    - 电压限分支（|Yt| ≤ G_opt）: 弦 G = p·G_opt, |Bt| ≤ G_opt√(1−p²);
    - 两支在 |Yt| = G_opt, Bt = ±G_opt√(1−p²) 处闭合相接（两模型在此
      连续, 解析可证）。
    返回 dict 含圆参数、弦参数、结点与采样折线（Γ 平面, 精确逐点 Möbius）。
    """
    p = 10.0 ** (-backoff_db / 10.0)
    g_opt = device.gopt_s
    w = 2.0 * np.pi * f_hz
    g0 = g_opt / (2.0 * p)
    bt_j = g_opt * np.sqrt(max(1.0 - p * p, 0.0))
    # Γ 平面采样: 圆弧（|Yt|≥G_opt 一段）+ 弦
    theta_arc = np.arccos(np.clip((g_opt - g0) / g0, -1.0, 1.0))  # 弧端角
    ts = np.linspace(-theta_arc, theta_arc, 33)
    yt = g0 + g0 * np.exp(1j * ts)  # 圆心 (g0,0), 过原点
    keep = np.abs(yt) >= g_opt - 1e-12
    arc_y = yt[keep]
    chord_b = np.linspace(-bt_j, bt_j, 17)
    chord_y = p * g_opt + 1j * chord_b
    y_all = np.concatenate([arc_y, chord_y])

    def _yt_to_gamma(yt_val: np.ndarray) -> np.ndarray:
        yl = yt_val - 1j * w * device.cout_f
        zl = np.where(np.abs(yl) > _EPS, 1.0 / yl, np.inf)
        return np.where(np.abs(zl) < np.inf, (zl - z0) / (zl + z0), 1.0)

    gamma_pts = _yt_to_gamma(y_all)
    return {
        "backoff_db": backoff_db,
        "level_dbm": round(device.max_power_dbm() - backoff_db, 6),
        "p_ratio": round(p, 8),
        "norton_circle": {"center_g": round(g0, 9), "radius_g": round(g0, 9)},
        "chord_g": round(p * g_opt, 9),
        "junction_bt": round(bt_j, 9),
        "gamma_polyline": [
            {"re": round(c.real, 8), "im": round(c.imag, 8)} for c in gamma_pts
        ],
    }


def _locus_residual(
    gamma_pts: np.ndarray, device: LoadPullDevice, f_hz: float, p: float,
    z0: float = DEFAULT_Z0,
) -> np.ndarray:
    """采样点到解析等功率线（弧∪弦）的最小距离（Yt 平面, 电导归一）。"""
    w = 2.0 * np.pi * f_hz
    gam = np.asarray(gamma_pts, dtype=complex)
    z = np.where(np.abs(1.0 - gam) < _EPS, np.inf, z0 * (1.0 + gam) / (1.0 - gam))
    with np.errstate(divide="ignore", invalid="ignore"):
        yl = np.where(np.isfinite(z), 1.0 / z, 0.0)
    g = yl.real
    bt = yl.imag + w * device.cout_f
    g_opt = device.gopt_s
    g0 = g_opt / (2.0 * p)
    res_arc = np.abs(np.sqrt((g - g0) ** 2 + bt**2) - g0)
    res_chord = np.abs(g - p * g_opt)
    return np.minimum(res_arc, res_chord)


def _ray_level_radius(
    gamma_opt: complex, direction: complex, level_dbm: float,
    power_fn: Any, r_max: float = 0.999,
) -> complex | None:
    """沿 Γopt→方向射线找功率降至 level_dbm 的半径（线性插值）。"""
    rs = np.linspace(0.0, r_max, 256)
    pts = gamma_opt + rs * direction
    p = power_fn(pts)
    p = np.where(np.isfinite(p), p, -np.inf)
    diff = p - level_dbm
    cross = np.where((diff[:-1] >= 0) & (diff[1:] < 0))[0]
    if cross.size == 0:
        return None
    i = int(cross[-1])
    denom = diff[i] - diff[i + 1]
    t = 0.0 if abs(denom) < _EPS else diff[i] / denom
    t = float(np.clip(t, 0.0, 1.0))
    r = rs[i] + t * (rs[i + 1] - rs[i])
    return complex(gamma_opt + r * direction)


def load_pull_scan(
    device: LoadPullDevice,
    f_hz: float,
    *,
    n_grid: int = 81,
    r_max: float = 0.9,
    backoff_db: tuple[float, ...] = (1.0, 2.0, 3.0),
    sparams: np.ndarray | None = None,
    z0: float = DEFAULT_Z0,
) -> LoadPullScan:
    """Cripps load-pull 全扫描: 数值功率面 + 解析等功率线 + 恒增益面。

    网格: ΓL 极坐标 (r∈[0,r_max], θ∈[0,2π)); 功率面 = load_pull_power_dbm;
    增益面 = operating_power_gain_db（sparams 提供时, 仅 |ΓL|<1 有效区）。
    每个回退电平:
    - 解析等功率线 = cripps_contour_locus（电流限 Norton 圆弧 ∪ 电压限弦,
      闭式可证）;
    - 数值等值点 = 从 Γ_opt 沿 16 方向射线找电平交点;
    - locus_max_dev = 数值点到解析线的最大距（数值↔闭式互证的裁判量）;
    - arc_circle_fit = 仅电流限弧段（|Yt|≥G_opt）点的 Kåsa 圆拟合相对
      残差（"等功率圈圆性"的量化, 信息量; 整圈含弦不喷圆拟合）。
    """
    rr = np.linspace(0.0, r_max, n_grid)
    tt = np.linspace(0.0, 2.0 * np.pi, n_grid)
    rg, tg = np.meshgrid(rr, tt, indexing="ij")
    grid = rg * np.exp(1j * tg)
    p_dbm = load_pull_power_dbm(grid, device, f_hz, z0).reshape(grid.shape)

    gain = None
    if sparams is not None:
        gain = np.full(grid.shape, -np.inf)
        finite = np.abs(grid) < 1.0 - 1e-6
        for idx, gpt in zip(np.argwhere(finite), grid[finite], strict=False):
            gain[idx[0], idx[1]] = operating_power_gain_db(sparams, complex(gpt))

    def power_fn(pts: np.ndarray) -> np.ndarray:
        return np.asarray(
            load_pull_power_dbm(np.asarray(pts, dtype=complex), device, f_hz, z0)
        )

    gamma_opt = device.optimal_gamma(f_hz, z0)
    w = 2.0 * np.pi * f_hz
    contours: list[dict[str, Any]] = []
    for bo in backoff_db:
        level = device.max_power_dbm() - bo
        dirs = [np.exp(1j * a) for a in np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False)]
        pts = [
            gp for d in dirs if (gp := _ray_level_radius(gamma_opt, d, level, power_fn)) is not None
        ]
        entry: dict[str, Any] = {
            "backoff_db": bo,
            "level_dbm": round(level, 4),
            "n_points": len(pts),
        }
        if len(pts) >= 6:
            arr = np.asarray(pts)
            p_ratio = 10.0 ** (-bo / 10.0)
            dev = _locus_residual(arr, device, f_hz, p_ratio, z0)
            entry["locus_max_dev"] = round(float(np.max(dev)), 9)
            # 仅电流限弧段（|Yt| ≥ G_opt）做圆拟合 → "圆性"量化
            z_arr = z0 * (1.0 + arr) / (1.0 - arr)
            yl = 1.0 / z_arr
            yt_mag = np.abs(yl + 1j * w * device.cout_f)
            arc_pts = arr[yt_mag >= device.gopt_s * (1.0 - 1e-6)]
            if len(arc_pts) >= 6:
                _, _, rel = _fit_circle(np.asarray(arc_pts))
                entry["arc_circle_fit_rel_rms"] = round(rel, 6)
        entry["locus"] = cripps_contour_locus(device, f_hz, bo, z0)
        contours.append(entry)
    return LoadPullScan(
        gamma_mag=rg, gamma_phase=tg, power_dbm=p_dbm, gain_db=gain,
        f_hz=f_hz, z0=z0, device=device, contours=contours,
    )


def load_pull_plausibility(
    scan: LoadPullScan,
    *,
    grid_gamma_tol: float = 0.05,
    locus_dev_tol: float = 0.005,
    gain_peak_dist_tol: float = 0.15,
    sparams: np.ndarray | None = None,
) -> dict[str, Any]:
    """等功率/等增益圈合理性裁判（验收口径的确定性落地）。

    五项检查:
    1. optimum_matches_model: 网格最优点 ≈ 模型 Γ_L,opt（G_opt−jωC_out）;
    2. power_is_class_a: 网格最大功率 ≈ Vsw·Isw/2 闭式（≤0.5 dB）;
    3. contours_on_analytic_locus: 射线提取的数值等值点到解析等功率线
       （Norton 圆弧 ∪ 电压限弦）的最大距 ≤ tol——数值面与闭式物理互证;
    4. contours_nest: 解析线弦电导 p·G_opt 随回退单调下降（圈层单调收缩/扩张）;
    5. gain_peak_matches_conj_match: 恒增益面顶点 ≈ ΓML 且峰值 ≈ GT,max
       （GP(ΓML)=GT,max 是双共轭匹配点的教科书恒等式, 网格自洽性互证;
       仅 sparams 提供且器件无条件稳定时才检查——不稳定器件的 GP 面在
       稳定边界发散, 增益峰无定义, 记 skipped）。
    """
    checks: dict[str, Any] = {}
    opt = scan.optimum_dict()
    checks["optimum_matches_model"] = {
        "ok": bool(opt["gamma_dist"] <= grid_gamma_tol),
        "gamma_dist": opt["gamma_dist"], "tol": grid_gamma_tol,
    }
    p_dev = float(np.nanmax(np.where(np.isfinite(scan.power_dbm), scan.power_dbm, -np.inf)))
    d_p = abs(p_dev - scan.device.max_power_dbm())
    checks["power_is_class_a"] = {
        "ok": bool(d_p <= 0.5), "grid_power_dbm": round(float(p_dev), 4),
        "model_power_dbm": round(scan.device.max_power_dbm(), 4), "delta_db": round(d_p, 4),
    }
    devs = [c.get("locus_max_dev") for c in scan.contours if c.get("locus_max_dev") is not None]
    checks["contours_on_analytic_locus"] = {
        "ok": bool(devs) and max(devs) <= locus_dev_tol,
        "locus_max_dev": [round(d, 9) for d in devs],
        "tol": locus_dev_tol,
    }
    chords = [c["locus"]["chord_g"] for c in scan.contours]
    nested = all(chords[i] > chords[i + 1] for i in range(len(chords) - 1))
    checks["contours_nest"] = {
        "ok": bool(len(chords) >= 2 and nested),
        "chord_g": [round(c, 6) for c in chords],
    }
    if scan.gain_db is not None and sparams is not None:
        margins = stability_margins(sparams)
        if not margins.unconditionally_stable:
            checks["gain_peak_matches_conj_match"] = {
                "ok": True, "status": "skipped",
                "reason": "器件非无条件稳定, GP 面在稳定边界发散, 增益峰无定义",
            }
        else:
            finite_gain = np.where(np.isfinite(scan.gain_db), scan.gain_db, -np.inf)
            idx = np.unravel_index(int(np.argmax(finite_gain)), scan.gain_db.shape)
            g_peak = complex(scan.gamma_mag[idx] * np.exp(1j * scan.gamma_phase[idx]))
            cm = simultaneous_conjugate_match(sparams)
            d_g = float(abs(g_peak - cm.gamma_l))
            d_v = abs(float(scan.gain_db[idx]) - cm.gt_max_db)
            checks["gain_peak_matches_conj_match"] = {
                "ok": bool(d_g <= gain_peak_dist_tol and d_v <= 0.5),
                "dist": round(d_g, 6), "dist_tol": gain_peak_dist_tol,
                "peak_gain_db": round(float(scan.gain_db[idx]), 4),
                "gt_max_db": round(cm.gt_max_db, 4), "value_tol_db": 0.5,
            }
    all_ok = all(bool(v.get("ok")) for v in checks.values())
    return {"plausible": all_ok, "checks": checks}
