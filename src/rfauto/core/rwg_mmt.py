"""自研 RWG/SIW 解析模基 MMT（GSM）求解器（DP-1 P1 内核）。

纯算法 numpy-only 零 IO 零外部进程（铁律 7 合规）；参照 adapters/ngsolve_modes.py
先例不进 @register_calculator（免 #231 注册表消费者三表同步），导出函数供
service 层直接调。规格 = docs/plan_deepdive_specs_20260924.md DP-1 §2；
判据预声明 = runs/df6_dp1mmt/criteria.md（先写后跑，#122）。

数学口径（推导在档，#1b 先验模型）
----------------------------------
时谐约定 e^{+jωt}，行波因子 e^{−jβz}；倏逝模取 β=−jα（α>0）保证
e^{−jβz}=e^{−αz} 衰减（规格 §2.1 符号约定）。

模基（TE_{m0} 单族，H 面首例域）：H_z=H0·cos(mπx/a)·e^{−jβz}，横向电场
e_m(x,y)=ŷ·N_m·sin(mπx/a)，N_m=√(2/(ab))（∫|e_m|²dS=1 功率归一）；
k_c=mπ/a、fc=c·m/(2a√εr)、β=√(k²−k_c²)（k=k0√εr）；Z^TE=ωμ/β（倏逝
+ jωμ/α 感性）。

结面 GSM（功率波归一，规格 §2.3 勘误后，见 junction_gsm docstring 与
criteria §0）：Petrov 域=E 连续投影主侧全域(e1)/H 连续投影口径窗(e2)
——规格印式的投影域恰为转置（校准实证该变体不收敛到物理解）。两侧
同时激励消元（p+q=Ĉ(r+s)、s−r=Ĉᵀ(p−q)，**Ĉ=D1⁻¹·Hᵀ·D2**，H_nm=
∫e2_n·e1_m dS，纯转置无共轭）得 M=ĈĈᵀ、N=ĈᵀĈ：
S11=(M−I)(M+I)⁻¹、S21=2Ĉᵀ(I+M)⁻¹、S12=2(I+M)⁻¹Ĉ、S22=(I−N)(I+N)⁻¹。
自检锚：同波导 H=I→S11=S22=0、S21=I；单模 H=1→S11=(Z2−Z1)/(Z1+Z2)、
S22=−S11（与传输线台阶 Γ 闭式一致）；宽口径膜片对一阶 Marcuvitz 旁证
（informational）与独立单平面口径场公式逐位一致。

阶梯耦合积分（规格 §2.2）：H-plane 窗口积分离变量化为一维初等积分。
**规格书 §2.2 原式勘误（#1b，动工前裁决）**：cos-分子显式式代入平凡自检
（m=m'、满口径）得 0 而积分真值 a/2——cos-分子是 ∫sin(πΔx)dx 的原函数，
属笔误。本实现用数学等价的半角稳定形式（Δ→0 极限自动精确）：

    ∫_{x0}^{x0+w} cos(πΔx)dx = w·cos(πΔ·x_c)·sinc(πΔw/2/π)
    ∫_{x0}^{x0+w} sin(πΔx)dx = w·sin(πΔ·x_c)·sinc(πΔw/2/π)，x_c=x0+w/2

sin-sin = ½[cos(πΔx)−cos(πΣx)]、cos-cos = ½[cos(πΔx)+cos(πΣx)]、
sin-cos = ½[sin(πΔx)+sin(πΣx)]、cos-sin = ½[sin(πΣx)−sin(πΔx)]，
Δ=m/a−m'/a'、Σ=m/a+m'/a'（Wexler 1967 / Masterman-Clarricoats 1971
矩形闭式特例口径）。居中 H 面阶梯/膜片的两侧波导局部原点不同——全局
坐标换元 u=x−o1 后第二模场按 sin(m2π(u+δ)/a2) 和差展开为 cosφ·S_ss+
sinφ·S_sc（φ=m2π(o1−o2)/a2），仍全闭式（aperture_h_matrix 内实现）。

级联：均匀段 S21=diag(e^{−jβL}·e^{−αL})；Redheffer 星积四式（规格 §2.3）。
末端取传播模 2×2（TE10/TE10），处于各端口 TE10 模阻抗基（Z^TE=ωμ/β），
同时输出 Z_PV=2b/a·Z^TE（与 core/calculators.py siw_analysis Z_PV 同形
口径）；50Ω 归一由 renormalize_2port（功率波 Z 矩阵中转，正实 z0）完成。

损耗闭式（规格 §2.6，TE10 微扰口径）：α_c=Rs/(b·η·√(1−(fc/f)²))·
(1+2b/a·(fc/f)²)、α_d=k²·tanδ/(2β)；作为均匀衰减因子作用于段传输指数
（高阶倏逝模衰减由 β=−jα 主导，微扰损耗对过传响应可忽略——已声明近似）。

膜片（规格 §2.5）：对称感性膜片=[HStep(a→a_iris), Uniform(a_iris,t),
HStep(a_iris→a)] 三件级联，全部复用阶梯构件；零厚度 t=0 走**零长段**
三件级联（两口径面经子波导倏逝模耦合由 Redheffer 级联精确处理——单结
面只给主→子散射而非膜片过传，校准实证后修正，criteria §0）。

出处：Wexler 1967 / Masterman-Clarricoats 1971 / Eleftheriades 1994（×2
收敛判据）/ Marcuvitz Waveguide Handbook / Pozar §3 场分量式 / meow
（Apache-2.0 EME 架构参照）。
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

import numpy as np

C0 = 299792458.0
MU0 = 4.0e-7 * math.pi
EPS0 = 1.0 / (MU0 * C0 * C0)

# 近截止病态带半宽（规格 §2.5 风险⑤：<5% 频点显式标 undetermined 不外推）
_NEAR_CUTOFF_FRAC = 0.05


# ── 波导与模基 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Waveguide:
    """矩形波导段（SI 单位：米；非磁性、均匀填充）。"""

    a: float
    b: float
    eps_r: float = 1.0
    tan_d: float = 0.0
    sigma: float | None = None  # 电导率 S/m；None=PEC（α_c=0）

    def __post_init__(self) -> None:
        for name, v in (("a", self.a), ("b", self.b)):
            if not (math.isfinite(v) and v > 0.0):
                raise ValueError(f"waveguide: {name} 必须为正有限数，得到 {v!r}")
        if not (math.isfinite(self.eps_r) and self.eps_r >= 1.0):
            raise ValueError(f"waveguide: eps_r 必须 ≥1 的有限数，得到 {self.eps_r!r}")
        if not (math.isfinite(self.tan_d) and self.tan_d >= 0.0):
            raise ValueError(f"waveguide: tan_d 必须非负有限数，得到 {self.tan_d!r}")
        if self.sigma is not None and not (math.isfinite(self.sigma) and self.sigma > 0.0):
            raise ValueError(f"waveguide: sigma 必须为正有限数或 None(PEC)，得到 {self.sigma!r}")

    def kc(self, m: int) -> float:
        return m * math.pi / self.a

    def fc_mn(self, m: int, n: int = 0) -> float:
        """TE/TM_mn 截止频率 Hz（TE_m0: fc=c·m/(2a√εr)）。"""
        return C0 * math.sqrt((m * math.pi / self.a) ** 2 + (n * math.pi / self.b) ** 2) / (
            2.0 * math.pi * math.sqrt(self.eps_r)
        )


@dataclass(frozen=True)
class ModeBasis:
    """某频点某波导的前 N 个 TE_{m0} 模基（功率归一）。"""

    wg: Waveguide
    f_hz: float
    m: np.ndarray  # (N,) 模序号 1..N
    kc: np.ndarray  # (N,)
    fc: np.ndarray  # (N,)
    beta: np.ndarray  # (N,) complex；倏逝 β=−jα（α>0）
    z_te: np.ndarray  # (N,) complex = ωμ0/β
    e_norm: float  # √(2/(ab))（TE_m0 各模同值）
    k_medium: float  # k=k0√εr（无耗介质波数）

    @property
    def propagating(self) -> np.ndarray:
        return np.abs(self.beta.imag) == 0.0


def mode_basis(wg: Waveguide, n_modes: int, f_hz: float) -> ModeBasis:
    """TE_{m0} 模基：k_c/fc/β/Z^TE 与功率归一系数（§2.1）。

    β 分支显式选取：k>k_c → 实 β；k≤k_c → β=−jα（保证衰减）。恰在截止
    （β=0）时 Z^TE→∞ 病态，显式报错（solve_chain 在上游以 5% 近截止带
    标 undetermined，正常不会走到）。
    """
    if not (math.isfinite(f_hz) and f_hz > 0.0):
        raise ValueError(f"mode_basis: f_hz 必须为正有限数，得到 {f_hz!r}")
    if not (isinstance(n_modes, int) and n_modes >= 1):
        raise ValueError(f"mode_basis: n_modes 必须为正整数，得到 {n_modes!r}")
    k0 = 2.0 * math.pi * f_hz / C0
    k = k0 * math.sqrt(wg.eps_r)
    m = np.arange(1, n_modes + 1, dtype=float)
    kc = m * math.pi / wg.a
    k2 = k * k
    over = k2 > kc * kc
    beta = np.where(over, np.sqrt(np.where(over, k2 - kc * kc, 0.0)),
                    -1j * np.sqrt(np.where(over, 0.0, kc * kc - k2)))
    beta = beta.astype(complex)
    if np.any(beta == 0.0):
        raise ValueError(
            f"mode_basis: 模恰在截止（β=0）@{f_hz / 1e9:.6g}Hz wg.a={wg.a}m——"
            "近截止病态点应由调用方以 undetermined 标记排除，不外推（criteria §0）")
    omega = 2.0 * math.pi * f_hz
    z_te = omega * MU0 / beta
    fc = C0 * m / (2.0 * wg.a * math.sqrt(wg.eps_r))
    return ModeBasis(wg=wg, f_hz=f_hz, m=m.astype(int), kc=kc, fc=fc, beta=beta,
                     z_te=z_te.astype(complex), e_norm=math.sqrt(2.0 / (wg.a * wg.b)),
                     k_medium=k)


# ── 损耗闭式（§2.6） ─────────────────────────────────────────────────────────


def alpha_c_te10(wg: Waveguide, f_hz: float) -> float:
    """TE10 导体衰减 Np/m：α_c=Rs/(b·η·√(1−(fc/f)²))·(1+2b/a·(fc/f)²)。

    推导（动工前手推在档，criteria §0）：壁电流 |J|² 沿周向积分
    P_l=(RsA²/2)(a k²+2b k_c²)、P=E0·A·a·b·β/4，相除即得；f→∞ 极限
    Rs/(bη)、f→fc⁺ 发散均为自检锚。f≤fc 或 PEC（sigma=None）→ 显式报错/
    返回 0，不外推。
    """
    fc = wg.fc_mn(1)
    if f_hz <= fc:
        raise ValueError(f"alpha_c_te10: f={f_hz / 1e9:.6g}Hz ≤ fc10={fc / 1e9:.6g}Hz，"
                         "截止以下不外推（criteria §0）")
    if wg.sigma is None:
        return 0.0
    rs = math.sqrt(math.pi * f_hz * MU0 / wg.sigma)
    eta = math.sqrt(MU0 / (EPS0 * wg.eps_r))
    x = (fc / f_hz) ** 2
    return rs / (wg.b * eta * math.sqrt(1.0 - x)) * (1.0 + 2.0 * wg.b / wg.a * x)


def alpha_d_te10(wg: Waveguide, f_hz: float, beta: float | None = None) -> float:
    """TE10 介质衰减 Np/m：α_d=k²·tanδ/(2β)（Pozar 微扰式；截止下不外推）。"""
    fc = wg.fc_mn(1)
    if f_hz <= fc:
        raise ValueError(f"alpha_d_te10: f={f_hz / 1e9:.6g}Hz ≤ fc10={fc / 1e9:.6g}Hz，"
                         "截止以下不外推（criteria §0）")
    if beta is None:
        beta = float(mode_basis(wg, 1, f_hz).beta[0].real)
    k = 2.0 * math.pi * f_hz * math.sqrt(wg.eps_r) / C0
    return k * k * wg.tan_d / (2.0 * beta)


# ── 一维闭式重叠积分族（§2.2，含规格书原式勘误，criteria §0） ─────────────────


def _int_cos(x0: float, w: float, k: np.ndarray | float) -> np.ndarray | float:
    """∫_{x0}^{x0+w} cos(k·x)dx = w·cos(k·x_c)·sinc(k·w/2)，x_c=x0+w/2。

    半角稳定形式：k→0 极限自动为 w，无数值分支（criteria §0 勘误式）。
    """
    u = 0.5 * np.asarray(k) * w
    return w * np.cos(np.asarray(k) * (x0 + 0.5 * w)) * np.sinc(u / np.pi)


def _int_sin(x0: float, w: float, k: np.ndarray | float) -> np.ndarray | float:
    """∫_{x0}^{x0+w} sin(k·x)dx = w·sin(k·x_c)·sinc(k·w/2)；k→0 极限为 0。"""
    u = 0.5 * np.asarray(k) * w
    return w * np.sin(np.asarray(k) * (x0 + 0.5 * w)) * np.sinc(u / np.pi)


def overlap_1d(kind: str, a1: float, m1: int, a2: float, m2: int,
               x0: float, w: float) -> float:
    """一维重叠积分 ∫_{x0}^{x0+w} f(π m1 x/a1)·g(π m2 x/a2)dx，闭式。

    kind ∈ {"sin_sin","cos_cos","sin_cos","cos_sin"}；Δ→0 极限精确
    （半角稳定形式）。sin_sin 满口径平凡自检：a1=a2、m1=m2、x0=0、w=a
    → a/2（测试 A8 锚）。
    """
    delta = math.pi * (m1 / a1 - m2 / a2)
    sigma = math.pi * (m1 / a1 + m2 / a2)
    if kind == "sin_sin":
        val = 0.5 * (_int_cos(x0, w, delta) - _int_cos(x0, w, sigma))
    elif kind == "cos_cos":
        val = 0.5 * (_int_cos(x0, w, delta) + _int_cos(x0, w, sigma))
    elif kind == "sin_cos":
        val = 0.5 * (_int_sin(x0, w, delta) + _int_sin(x0, w, sigma))
    elif kind == "cos_sin":
        val = 0.5 * (_int_sin(x0, w, sigma) - _int_sin(x0, w, delta))
    else:
        raise ValueError(f"overlap_1d: kind 必须为 sin_sin/cos_cos/sin_cos/cos_sin，"
                         f"得到 {kind!r}")
    return float(val)


def overlap_sin_sin_matrix(a1: float, m1_arr: np.ndarray, a2: float,
                           m2_arr: np.ndarray, x0: float, w: float) -> np.ndarray:
    """sin-sin 重叠积分矩阵 (N1,N2)（向量化，H 矩阵构件）。"""
    m1 = np.asarray(m1_arr, dtype=float)[:, None] / a1
    m2 = np.asarray(m2_arr, dtype=float)[None, :] / a2
    delta = math.pi * (m1 - m2)
    sigma = math.pi * (m1 + m2)
    return 0.5 * (_int_cos(x0, w, delta) - _int_cos(x0, w, sigma))


def overlap_sin_cos_matrix(a1: float, m1_arr: np.ndarray, a2: float,
                           m2_arr: np.ndarray, x0: float, w: float) -> np.ndarray:
    """sin(m1πx/a1)·cos(m2πx/a2) 重叠积分矩阵（坐标偏移展开用）。"""
    m1 = np.asarray(m1_arr, dtype=float)[:, None] / a1
    m2 = np.asarray(m2_arr, dtype=float)[None, :] / a2
    delta = math.pi * (m1 - m2)
    sigma = math.pi * (m1 + m2)
    return 0.5 * (_int_sin(x0, w, delta) + _int_sin(x0, w, sigma))


# ── GSM 构件（§2.3） ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Gsm:
    """广义散射矩阵块（s11:(n1,n1) s12:(n1,n2) s21:(n2,n1) s22:(n2,n2)）。"""

    s11: np.ndarray
    s12: np.ndarray
    s21: np.ndarray
    s22: np.ndarray

    @property
    def n_in(self) -> int:
        return int(self.s11.shape[0])

    @property
    def n_out(self) -> int:
        return int(self.s22.shape[0])


def aperture_h_matrix(basis1: ModeBasis, basis2: ModeBasis, x0: float, w: float,
                      offset1: float = 0.0, offset2: float = 0.0) -> np.ndarray:
    """结面耦合矩阵 H[n2,m1]=∫_ap e2_n·e1_m dS，形状 (n2,n1)（H 面单族）。

    全局 x 坐标下两波导各自的局部原点为 offset1/offset2（居中 H 面阶梯
    必须带偏移：窄波导中心对齐宽波导时 o=(a_wide−a_narrow)/2），口径窗
    [x0,x0+w] 为全局坐标。换元 u=x−offset2（按行侧模坐标）展开列侧模场：
    sin(m1π(u+δ)/a1)=cosφ·sin(m1πu/a1)+sinφ·cos(m1πu/a1)，δ=offset2−
    offset1、φ=m1πδ/a1 → H=cosφ·S_ss+sinφ·S_sc（仍全闭式，逐列相位）。
    零偏移时退化为纯 sin-sin。

    b 不一致（全 2D 窗口）显式报错不降级（criteria §0 首例域声明）。
    """
    b1, b2 = basis1.wg.b, basis2.wg.b
    if abs(b1 - b2) > 1e-9 * max(b1, b2):
        raise ValueError("aperture_h_matrix: 两侧 b 不一致（TE↔TM 全 2D 窗口未开放，"
                         "DP-1 首例域为 H 面 TE_{m0} 单族）")
    a1, a2 = basis1.wg.a, basis2.wg.a
    lo = max(offset1, offset2)
    hi = min(offset1 + a1, offset2 + a2)
    tol = 1e-9 * max(a1, a2)
    if not (w > 0.0 and -tol <= x0 - lo and x0 + w <= hi + tol):
        raise ValueError(f"aperture_h_matrix: 口径窗 [x0,x0+w]=[{x0},{x0 + w}] 必须"
                         f"落在两波导交集 [{lo},{hi}] 内且 w>0")
    u0 = x0 - offset2
    delta_o = offset2 - offset1
    m1 = np.asarray(basis1.m, dtype=float)
    phi = m1 * math.pi * delta_o / a1
    # 行侧（basis2）为第一函数、列侧（basis1）为第二函数 → 输出 (n2,n1)
    ss = overlap_sin_sin_matrix(a2, basis2.m, a1, basis1.m, u0, w)
    if abs(delta_o) < 1e-15 * max(a1, a2):
        return basis2.e_norm * basis1.e_norm * b1 * ss
    sc = overlap_sin_cos_matrix(a2, basis2.m, a1, basis1.m, u0, w)
    val = np.cos(phi)[None, :] * ss + np.sin(phi)[None, :] * sc
    return basis2.e_norm * basis1.e_norm * b1 * val


def junction_gsm(h: np.ndarray, z1: np.ndarray, z2: np.ndarray) -> Gsm:
    """结面 GSM（功率波归一，Petrov 域=E 投影主侧全域/H 投影口径窗）。

    **规格书 §2.3 四式勘误（#1b，动工前由独立单平面口径场公式+一阶
    Marcuvitz 对拍裁决）**：规格印式（C=D2⁻¹HD1，S11=(I−CᵀC)(I+CᵀC)⁻¹
    等四式）对应"Petrov 域=E 投影口径窗(e2)/H 投影主侧全域(e1)"的转置
    问题——该校准实证不收敛到物理解（膜片 S11 实部为正、非并联族、
    镜像方向 0.66 级分歧；d=16mm 宽口径 B/Y0：一阶 Marcuvitz −0.451 =
    独立单平面式 −0.443，转置变体 −0.246）。正确投影域=E 连续投影主侧
    全域（金属缘 E_t=0 一并约束）、H 连续投影口径窗（H 连续仅在窗口
    成立，金属缘为面电流）。推导（两侧同时激励，纯转置无共轭）：

        Ĉ = D1⁻¹·Hᵀ·D2（n1×n2，D_k=diag(√Z_k)）
        (1) E-cont: p+q = Ĉ(r+s)          （v1 = Ĉ v2）
        (2) H-cont: s−r = Ĉᵀ(p−q)          （u2 = Ĉᵀ u1）
        → M=ĈĈᵀ, N=ĈᵀĈ：
        S11=(M−I)(M+I)⁻¹  S21=2Ĉᵀ(I+M)⁻¹
        S12=2(I+M)⁻¹Ĉ     S22=(I−N)(I+N)⁻¹

    C†C 类共轭转置不可用（实模基正交归一投影 ∫e_n·e_m=δ 给纯转置；
    共轭转置在含倏逝模组态破坏互易与守恒——校准实证互易破坏 0.199）。
    TEM 台阶锚（单模 H=1）：S11=(Z2−Z1)/(Z1+Z2)=Γ₁、S22=−Γ₁、
    S21=S12=2√(Z1Z2)/(Z1+Z2)——标量退化下修正集与转置变体同值（故该
    雷须以宽口径膜片+Marcuvitz 旁证钉）。同波导 H=I（Z 同）→ M=N=I →
    S11=S22=0、S21=I。含倏逝模：S=Sᵀ（互易，S12=S21ᵀ 恒等式由
    push-through 保证）+ 传播受限子块 σmax≤1（功率守恒收缩性）。
    """
    h = np.asarray(h, dtype=complex)
    z1 = np.asarray(z1, dtype=complex)
    z2 = np.asarray(z2, dtype=complex)
    n2, n1 = h.shape
    if z1.shape != (n1,) or z2.shape != (n2,):
        raise ValueError(f"junction_gsm: H{h.shape}（应为 (n2,n1)）与 "
                         f"z1{z1.shape}/z2{z2.shape} 维数不匹配")
    if np.any(z1 == 0) or np.any(z2 == 0):
        raise ValueError("junction_gsm: 波阻抗出现 0（β→∞ 非物理）")
    d1 = np.sqrt(z1)
    d2 = np.sqrt(z2)
    c_mat = h.T * d2[None, :] / d1[:, None]  # Ĉ = D1⁻¹ Hᵀ D2 (n1,n2)
    eye_n1 = np.eye(n1, dtype=complex)
    eye_n2 = np.eye(n2, dtype=complex)
    m_mat = c_mat @ c_mat.T  # M = ĈĈᵀ (n1,n1)
    n_mat = c_mat.T @ c_mat  # N = ĈᵀĈ (n2,n2)
    # I±M / I±N 可交换（同一矩阵多项式）→ S11/S22 对称
    s11 = np.linalg.solve(eye_n1 + m_mat, m_mat - eye_n1)
    s21 = 2.0 * np.linalg.solve(eye_n1 + m_mat, c_mat).T   # 2 Ĉᵀ(I+M)⁻¹
    s12 = 2.0 * np.linalg.solve(eye_n1 + m_mat, c_mat)     # 2 (I+M)⁻¹Ĉ
    s22 = np.linalg.solve(eye_n2 + n_mat, eye_n2 - n_mat)
    return Gsm(s11=s11, s12=s12, s21=s21, s22=s22)


def section_gsm(basis: ModeBasis, length_m: float) -> Gsm:
    """均匀段：S21=S12=diag(e^{−jβL}·e^{−α_tot·L})、S11=S22=0（§2.3）。

    α_tot=α_c+α_d 仅 TE10 微扰口径（倏逝模衰减由 β=−jα 主导，微扰损耗
    不作用——criteria §0 已声明近似）；TE10 截止下损耗置 0（频点应由
    上游 undetermined 规则排除）。
    """
    if not (math.isfinite(length_m) and length_m >= 0.0):
        raise ValueError(f"section_gsm: length_m 必须非负有限数，得到 {length_m!r}")
    n = int(basis.m.size)
    beta = basis.beta
    alpha_tot = 0.0
    wg = basis.wg
    if (wg.tan_d > 0.0 or wg.sigma is not None) and float(beta[0].imag) == 0.0:
        alpha_tot = alpha_c_te10(wg, basis.f_hz)
        if wg.tan_d > 0.0:
            alpha_tot += alpha_d_te10(wg, basis.f_hz, beta=float(beta[0].real))
    trans = np.exp(-1j * beta * length_m - alpha_tot * length_m)
    zero = np.zeros((n, n), dtype=complex)
    diag = np.diag(trans)
    return Gsm(s11=zero.copy(), s12=diag.copy(), s21=diag.copy(), s22=zero.copy())


def gsm_cascade(a: Gsm, b: Gsm) -> Gsm:
    """Redheffer 星积（A 后接 B；多重反射级数/界面线性方程组双推导一致）：

        S11 = A11 + A12·B11·(I−A22B11)⁻¹·A21 = A12(I−B11A22)⁻¹B11A21
        S12 = A12·(I−B11A22)⁻¹·B12
        S21 = B21·(I−A22B11)⁻¹·A21
        S22 = B22 + B21·A22·(I−B11A22)⁻¹·B12

    （df7_dp1fix 缺陷② Fix-A：v1 版 s12/s21 的中间逆互换（s12 误用
    (I−A22B11)⁻¹、s21 误用 (I−B11A22)⁻¹）——两逆仅当 A22B11 可交换
    （标量/对角/单模或 B11=0，即直段与单结面链）时相等，≥2 结面级联的
    S12/S21 被污染。s11/s22 两式 v1 已为正确形（push-through 等价形），
    逐位不动。）逆用 solve 不用 inv。
    """
    if a.n_out != b.n_in:
        raise ValueError(f"gsm_cascade: 维数不衔接 A.n_out={a.n_out} vs B.n_in={b.n_in}")
    n_mid = a.n_out
    eye_mid = np.eye(n_mid, dtype=complex)
    inv1 = np.linalg.solve(eye_mid - a.s22 @ b.s11, eye_mid)  # (I−S22A·S11B)⁻¹
    inv2 = np.linalg.solve(eye_mid - b.s11 @ a.s22, eye_mid)  # (I−S11B·S22A)⁻¹
    return Gsm(
        s11=a.s11 + a.s12 @ b.s11 @ inv1 @ a.s21,
        s12=a.s12 @ inv2 @ b.s12,
        s21=b.s21 @ inv1 @ a.s21,
        s22=b.s22 + b.s21 @ a.s22 @ inv2 @ b.s12,
    )


def gsm_flip(g: Gsm) -> Gsm:
    """端口交换翻转（镜像对称根治，df7_dp1fix 缺陷② Fix-B）。

    同一结构自端口 2 视看的 GSM = 端口 1 视看的精确块交换（模基随各自
    波导走，块不转置）：flip 的 S11/S12/S21/S22 依次取原 S22/S21/S12/S11。
    junction_gsm 的 Petrov 投影域（E 连续投影主侧全域 / H 连续投影口径窗）
    在换向**重解**时测试基换侧，直接重解的 J(w2→w1) ≠ flip(J(w1→w2))
    （截断级非镜像协变，镜像对称链 S11≠S22 的根因之一，criteria §1 H3）
    ——solve_at_counts 对 a_left<a_right 的结面按几何孪生（宽→窄 canonical）
    计算后经本函数翻转，使镜像对称链 S11==S22、S12==S21 成为代数恒等。
    """
    return Gsm(s11=g.s22, s12=g.s21, s21=g.s12, s22=g.s11)


def gsm_to_2x2(g: Gsm) -> np.ndarray:
    """取两端 TE10（模序 0）的 2×2：[[S11,S12],[S21,S22]]。"""
    return np.array([[g.s11[0, 0], g.s12[0, 0]],
                     [g.s21[0, 0], g.s22[0, 0]]], dtype=complex)


def shunt_admittance_from_s11(s11: complex) -> complex:
    """由并联导纳结面的反射恢复归一并联导纳 ybar=−2S11/(1+S11)。

    短路点 S11→−1 时 ybar→∞ 病态，显式报错。用于感性膜片 B/Y0 提取
    （等效电路：主波导 TE10 线上并联 ybar=jB/Y0……感性 B<0）。
    """
    s11 = complex(s11)
    if abs(1.0 + s11) < 1e-14:
        raise ValueError("shunt_admittance_from_s11: S11→−1（短路），并联导纳病态")
    return -2.0 * s11 / (1.0 + s11)


def renormalize_2port(s2: np.ndarray, z0_from, z0_to) -> np.ndarray:
    """2×2 功率波 S 参考阻抗变换（仅支持正实 z0；Z 矩阵中转，纯 numpy）。

    Z=√z0(I−S)⁻¹(I+S)√z0；S'=D'⁻¹(Z−Z0')(Z+Z0')⁻¹D'（D'=diag(√z0')）。
    奇异（I−S 或 Z+Z0'）显式报错。skrf renormalize 为独立裁判（测试 A7）。
    """
    s2 = np.asarray(s2, dtype=complex)
    if s2.shape != (2, 2):
        raise ValueError(f"renormalize_2port: s2 必须为 2×2，得到 {s2.shape}")
    zf = np.asarray(z0_from, dtype=float)
    zt = np.asarray(z0_to, dtype=float)
    for name, z in (("z0_from", zf), ("z0_to", zt)):
        if z.shape != (2,) or np.any(~np.isfinite(z)) or np.any(z <= 0):
            raise ValueError(f"renormalize_2port: {name} 必须为 2 个正实数，得到 {z!r}")
    eye = np.eye(2, dtype=complex)
    z_mat = np.sqrt(zf)[:, None] * np.linalg.solve(eye - s2, eye + s2) * np.sqrt(zf)[None, :]
    zp = np.diag(zt)
    d_inv = np.diag(1.0 / np.sqrt(zt))
    d_mat = np.diag(np.sqrt(zt))
    return d_inv @ (z_mat - zp) @ np.linalg.solve(z_mat + zp, d_mat)


# ── 段表、模式数策略与 solve_chain（§2.4/§2.5） ──────────────────────────────


@dataclass(frozen=True)
class UniformSection:
    """均匀波导段（左=右=wg；相邻段 guide 不一致须显式插 HStepJunction）。"""

    wg: Waveguide
    length_m: float


@dataclass(frozen=True)
class HStepJunction:
    """H 面阶梯/零厚度感性膜片结面（全局坐标口径窗 [x0, x0+w]）。

    offset_left/right_m 为两波导局部原点在全局坐标的位置（居中阶梯：
    窄波导 offset=(a_wide−a_narrow)/2、宽波导 0）。缺省（None）=共原点、
    口径窗取交集居中；居中阶梯用 centered_step 构造。
    """

    wg_left: Waveguide
    wg_right: Waveguide
    x0_m: float | None = None  # None=交集内居中
    aperture_m: float | None = None  # None=交集宽
    offset_left_m: float = 0.0
    offset_right_m: float = 0.0

    @classmethod
    def centered_step(cls, wg_left: Waveguide, wg_right: Waveguide,
                      aperture_m: float | None = None) -> HStepJunction:
        """构造几何居中的 H 面阶梯（窄波导中心对齐宽波导全局坐标）。

        窄侧局部原点在全局 (a_wide−a_narrow)/2 处、宽侧原点 0（校准实证
        修正：原实现把偏移挂错侧，交集退化空窗）。
        """
        if wg_left.a >= wg_right.a:
            return cls(wg_left, wg_right,
                       offset_left_m=(wg_left.a - wg_right.a) / 2.0,
                       offset_right_m=0.0, aperture_m=aperture_m)
        return cls(wg_left, wg_right,
                   offset_left_m=(wg_right.a - wg_left.a) / 2.0,
                   offset_right_m=0.0, aperture_m=aperture_m)

    def resolved(self) -> tuple[float, float, float, float]:
        """→(x0, w, offset_left, offset_right)，校验口径窗落在两波导交集内。"""
        lo = max(self.offset_left_m, self.offset_right_m)
        hi = min(self.offset_left_m + self.wg_left.a,
                 self.offset_right_m + self.wg_right.a)
        span = hi - lo
        w = float(self.aperture_m) if self.aperture_m is not None else span
        x0 = lo + (span - w) / 2.0 if self.x0_m is None else float(self.x0_m)
        tol = 1e-9 * max(self.wg_left.a, self.wg_right.a)
        if not (w > 0.0 and -tol <= x0 - lo and x0 + w <= hi + tol):
            raise ValueError(f"HStepJunction: 口径窗 [{x0},{x0 + w}] 必须落在两波导"
                             f"交集 [{lo},{hi}] 内且 w>0")
        return x0, w, self.offset_left_m, self.offset_right_m


@dataclass(frozen=True)
class InductiveIris:
    """对称感性膜片（口径 a_iris 居中缩窄 a 向；零厚度=单结面快档）。"""

    wg: Waveguide
    aperture_m: float
    thickness_m: float = 0.0

    def __post_init__(self) -> None:
        if not (0.0 < self.aperture_m <= self.wg.a):
            raise ValueError(f"InductiveIris: aperture_m 必须落在 (0, a={self.wg.a}]，"
                             f"得到 {self.aperture_m!r}")
        if not (math.isfinite(self.thickness_m) and self.thickness_m >= 0.0):
            raise ValueError(f"InductiveIris: thickness_m 必须非负有限数，"
                             f"得到 {self.thickness_m!r}")

    def segments(self) -> list[UniformSection | HStepJunction]:
        """展开为构件序列（§2.5）：[主→子阶梯, 子波导段(可为 0 长), 子→主阶梯]。

        零厚度也走两结面夹 **零长段** 的三件级联——单结面只给出主→子的
        散射而非膜片两侧主波导间的过传（校准实证后修正，criteria §0）；
        零长段恒等阵下 Redheffer 级联精确处理两口径面经子波导倏逝模的
        耦合（零厚度膜片的标准 MMT 口径）。
        """
        wg_sub = replace(self.wg, a=self.aperture_m)
        x0 = (self.wg.a - self.aperture_m) / 2.0  # 子波导居中于主波导
        fwd = HStepJunction(self.wg, wg_sub, x0_m=x0, aperture_m=self.aperture_m,
                            offset_left_m=0.0, offset_right_m=x0)
        back = HStepJunction(wg_sub, self.wg, x0_m=x0, aperture_m=self.aperture_m,
                             offset_left_m=x0, offset_right_m=0.0)
        return [fwd, UniformSection(wg_sub, self.thickness_m), back]


@dataclass(frozen=True)
class ModePolicy:
    """模式数策略（§2.4）：比例法则 + 截断充分性守卫 + ×2 收敛门。"""

    n_modes_ref: int = 15  # 最窄侧基准模式数
    n_modes_max: int = 120  # 比例法则单侧上限（防极窄子波导爆模式数）
    n_doublings_max: int = 3  # ×2 收敛探测次数上限（n_ref→2n_ref→…）
    convergence_tol: float = 0.01  # G2：传播模 2×2 复模差
    evanescent_decay_min: float = 3.0  # 截断充分性：α_M·L≥3
    strict_truncation_guard: bool = True  # False→降级 result.warnings
    n_modes_override: dict[int, int] | None = None  # guide 序→模式数（触发比例守卫）
    ratio_tolerance: float = 0.25

    def __post_init__(self) -> None:
        if not (isinstance(self.n_modes_ref, int) and self.n_modes_ref >= 1):
            raise ValueError(f"ModePolicy: n_modes_ref 必须为正整数，得到 {self.n_modes_ref!r}")
        if not (isinstance(self.n_doublings_max, int) and self.n_doublings_max >= 0):
            raise ValueError("ModePolicy: n_doublings_max 必须为非负整数，"
                             f"得到 {self.n_doublings_max!r}")


@dataclass
class SolveResult:
    """solve_chain 输出（numpy 数组直出；service 层负责 JSON/Touchstone 面上）。"""

    freqs_hz: np.ndarray  # (F,)
    s2x2: np.ndarray  # (F,2,2) complex；端口 TE10 模阻抗基；undetermined 行=NaN
    z_te_ports: np.ndarray  # (F,2) complex 各端口 TE10 Z^TE=ωμ/β
    z_pv_ports: np.ndarray  # (F,2) complex Z_PV=2b/a·Z^TE（siw_analysis 同形口径）
    beta_te10_ports: np.ndarray  # (F,2) complex
    undetermined: np.ndarray  # (F,) bool 近截止/过传通道截止标记
    converged: bool  # G2 ×2 收敛门
    n_modes: list[int]  # 各 guide 最终模式数
    n_modes_tested: list[list[int]]  # 收敛探测逐级模式数
    warnings: list[str]


def mode_counts(widths: list[float], policy: ModePolicy) -> list[int]:
    """比例法则模式数：N_i=round(n_ref·a_i/min(a))，上限 n_modes_max；
    override 走比例守卫（不封顶，显式值即最终值）。

    比例守卫（§2.4 防相对收敛假收敛）：显式 override 的两侧模式数比偏离
    口径宽比超过 ratio_tolerance 即 ValueError（测试⑥负例）。
    """
    if not widths:
        raise ValueError("mode_counts: widths 为空")
    a_min = min(widths)
    if policy.n_modes_override is not None:
        counts = [1] * len(widths)
        for gi, n in policy.n_modes_override.items():
            if not (0 <= gi < len(widths)):
                raise ValueError(f"mode_counts: override guide 序 {gi} 越界")
            if not (isinstance(n, int) and n >= 1):
                raise ValueError(f"mode_counts: override 模式数必须为正整数，得到 {n!r}")
            counts[gi] = n
        for i in range(len(widths)):
            for j in range(i + 1, len(widths)):
                expected = widths[i] / widths[j]
                actual = counts[i] / counts[j]
                if abs(actual - expected) > policy.ratio_tolerance * expected:
                    raise ValueError(
                        f"mode_counts: 模式数比失衡守卫——N{i}/N{j}={actual:.4g} 偏离"
                        f"口径宽比 a{i}/a{j}={expected:.4g} 超容差 {policy.ratio_tolerance}"
                        "（比例法则，§2.4 防相对收敛假收敛）")
        return counts
    cap = max(policy.n_modes_max, policy.n_modes_ref)
    return [min(cap, max(1, round(policy.n_modes_ref * a / a_min)))
            for a in widths]


def _guide_list(chain: list) -> tuple[list, list]:
    """展开段表为构件序列并收集有序去重的 guide 表。

    返回 (elements, guides)：elements=[("J", step) | ("S", wg, L)]；
    相邻构件 guide 不衔接（缺显式 HStepJunction）显式报错。

    guide 表契约（P1 缺陷根治后口径）：按 **值语义**（frozen
    dataclass 逐字段相等）去重与反查——链中"值相等但实例不同"的 Waveguide
    （JSON 段表逐段新造、调用方分开构造）必须命中同一 guide 序；消费端
    禁止 id() 反查（曾致 KeyError，见 solve_at_counts）。
    """
    elements: list[tuple] = []
    for item in chain:
        if isinstance(item, UniformSection):
            elements.append(("S", item.wg, item.length_m))
        elif isinstance(item, HStepJunction):
            elements.append(("J", item))
        elif isinstance(item, InductiveIris):
            for seg in item.segments():
                if isinstance(seg, UniformSection):
                    elements.append(("S", seg.wg, seg.length_m))
                else:
                    elements.append(("J", seg))
        else:
            raise TypeError(f"solve_chain: 不支持的段类型 {type(item).__name__}")
    if not elements:
        raise ValueError("solve_chain: 段表为空")

    def left(el: tuple) -> Waveguide:
        return el[1] if el[0] == "S" else el[1].wg_left

    def right(el: tuple) -> Waveguide:
        return el[1] if el[0] == "S" else el[1].wg_right

    for el_cur, el_next in itertools.pairwise(elements):
        if left(el_next) != right(el_cur):
            raise ValueError("solve_chain: 相邻段波导不一致（几何须逐字段相等）——"
                             "请显式插入 HStepJunction，勿静默隐式阶梯")
    guides: list[Waveguide] = []
    for el in elements:
        for g in (left(el), right(el)):
            if g not in guides:
                guides.append(g)
    return elements, guides


def solve_chain(chain: list, freqs_hz, policy: ModePolicy | None = None) -> SolveResult:
    """段表→全模 GSM 级联→末端传播模 2×2 提取（§2.3/§2.4）。

    - 模式数：比例法则（两侧模式数比≈口径宽比）+ ×2 收敛门（G2：
      保比例加倍后传播模 2×2 复模差 < convergence_tol；触顶如实
      converged=False 不凑门）。
    - 截断充分性守卫：每均匀段（L>0）在链内最高频点校验最高倏逝模
      α_M·L≥3（strict 报错 / opt-out 降级 warnings——criteria §0）。
    - 近截止/过传通道：任一 guide f∈[0.95,1.05]·fc10 或 端口 guide
      f<fc10 → 频点 undetermined（S=NaN 不外推，criteria §0）。
    - 端口基：TE10 模阻抗 Z^TE=ωμ/β；Z_PV=2b/a·Z^TE 同步输出。
    """
    policy = policy if policy is not None else ModePolicy()
    freqs = np.asarray(freqs_hz, dtype=float)
    if freqs.ndim != 1 or freqs.size == 0 or np.any(~np.isfinite(freqs)) or np.any(freqs <= 0):
        raise ValueError("solve_chain: freqs_hz 必须为正有限一维数组")
    elements, guides = _guide_list(chain)
    counts = mode_counts([g.a for g in guides], policy)
    port_left = guides.index(elements[0][1].wg_left if elements[0][0] == "J"
                             else elements[0][1])
    port_right = guides.index(elements[-1][1].wg_right if elements[-1][0] == "J"
                              else elements[-1][1])
    f_max = float(freqs.max())

    # 截断充分性守卫（最高频点衰减最快→最不利；仅对 L>0 均匀段）
    warnings: list[str] = []
    for el in elements:
        if el[0] != "S" or el[2] <= 0.0:
            continue
        wg = el[1]
        gi = guides.index(wg)
        n = counts[gi]
        basis_top = mode_basis(wg, n, f_max)
        beta_top = complex(basis_top.beta[-1])
        if beta_top.imag == 0.0:
            continue  # 最高模仍传播：无倏逝截断问题
        decay = -beta_top.imag * el[2]
        if decay < policy.evanescent_decay_min:
            msg = (f"截断充分性守卫：段 a={wg.a}m L={el[2]}m 最高倏逝模 "
                   f"α_M·L={decay:.3g} < {policy.evanescent_decay_min}（n={n}）")
            if policy.strict_truncation_guard:
                raise ValueError(msg + "——模式数不足或段过短（§2.4；可显式 "
                                       "strict_truncation_guard=False 降级警告）")
            warnings.append(msg)

    # 近截止/过传通道标记（criteria §0）
    undetermined = np.zeros(freqs.size, dtype=bool)
    for f_idx, f_hz in enumerate(freqs):
        for gi, g in enumerate(guides):
            fc10 = g.fc_mn(1)
            if abs(f_hz - fc10) <= _NEAR_CUTOFF_FRAC * fc10:
                undetermined[f_idx] = True  # β→0 病态带
                break
            if f_hz < fc10 and gi in (port_left, port_right):
                undetermined[f_idx] = True  # 过传通道截止，2×2 契约失效
                break

    def solve_at_counts(level_counts: list[int]) -> np.ndarray:
        out = np.full((freqs.size, 2, 2), np.nan + 1j * np.nan, dtype=complex)
        for f_idx, f_hz in enumerate(freqs):
            if undetermined[f_idx]:
                continue
            bases = [mode_basis(g, level_counts[gi], float(f_hz))
                     for gi, g in enumerate(guides)]
            # 按值反查（frozen dataclass 值哈希；_guide_list 按值去重，链中
            # 值相等的不同实例必须命中同一 guide 序——id() 反查会 KeyError，
            # P1 缺陷根治钉 tests/unit/test_rwg_mmt.py::TestGuideValueSemantics）
            guide_idx = {g: gi for gi, g in enumerate(guides)}
            total: Gsm | None = None
            for el in elements:
                if el[0] == "S":
                    gsm = section_gsm(bases[guide_idx[el[1]]], el[2])
                else:
                    step: HStepJunction = el[1]
                    b1 = bases[guide_idx[step.wg_left]]
                    b2 = bases[guide_idx[step.wg_right]]
                    if step.wg_left.a < step.wg_right.a:
                        # 缺陷② Fix-B（df7_dp1fix，criteria §1 H3/§2）：窄→宽
                        # 结面按几何孪生（宽→窄 canonical 方向）计算后精确翻转
                        # ——反向 Petrov 重解非镜像协变（J(w2→w1)≠flip(J(w1→w2))），
                        # 镜像对称链 S11==S22 由本路径成为代数恒等；
                        # a_left≥a_right 走原路径逐位不变（archived 正向计算与
                        # Marcuvitz 校准面保持）。等宽结面（a_left==a_right）
                        # 本身镜像协变（H 为口径窗 Gram 阵对称），不触发。
                        twin = HStepJunction(
                            step.wg_right, step.wg_left, x0_m=step.x0_m,
                            aperture_m=step.aperture_m,
                            offset_left_m=step.offset_right_m,
                            offset_right_m=step.offset_left_m)
                        xc, wc, olc, orc = twin.resolved()
                        h_mat = aperture_h_matrix(b2, b1, xc, wc,
                                                  offset1=olc, offset2=orc)
                        gsm = gsm_flip(junction_gsm(h_mat, b2.z_te, b1.z_te))
                    else:
                        x0, w, off_l, off_r = step.resolved()
                        h_mat = aperture_h_matrix(b1, b2, x0, w,
                                                  offset1=off_l, offset2=off_r)
                        gsm = junction_gsm(h_mat, b1.z_te, b2.z_te)
                total = gsm if total is None else gsm_cascade(total, gsm)
            out[f_idx] = gsm_to_2x2(total)  # type: ignore[arg-type]
        return out

    levels = [[c * 2 ** lv for c in counts] for lv in range(policy.n_doublings_max + 1)]
    prev: np.ndarray | None = None
    s_final = levels[0]
    converged = False
    for level_counts in levels:
        s_now = solve_at_counts(level_counts)
        if prev is not None:
            ok = ~undetermined
            if ok.any() and float(np.max(np.abs(s_now[ok] - prev[ok]))) < policy.convergence_tol:
                s_final = s_now
                converged = True
                break
        prev = s_now
        s_final = s_now

    z_te = np.full((freqs.size, 2), np.nan + 1j * np.nan, dtype=complex)
    z_pv = np.full((freqs.size, 2), np.nan + 1j * np.nan, dtype=complex)
    beta_p = np.full((freqs.size, 2), np.nan + 1j * np.nan, dtype=complex)
    for f_idx, f_hz in enumerate(freqs):
        for p_idx, gi in enumerate((port_left, port_right)):
            b = mode_basis(guides[gi], 1, float(f_hz))
            beta_p[f_idx, p_idx] = b.beta[0]
            z_te[f_idx, p_idx] = b.z_te[0]
            g = guides[gi]
            z_pv[f_idx, p_idx] = 2.0 * g.b / g.a * b.z_te[0]

    return SolveResult(freqs_hz=freqs, s2x2=s_final, z_te_ports=z_te,
                       z_pv_ports=z_pv, beta_te10_ports=beta_p,
                       undetermined=undetermined, converged=converged,
                       n_modes=counts, n_modes_tested=levels, warnings=warnings)


# ── DP-1 风险分流④：G1 触发判定与膜片精化对照归档（df7_dp1r4） ─────────────────
#
# 上游终态（runs/df6_dp1p3/g1_verdict.json）：膜片绝对值
# UNDECIDABLE→规格风险分流④（docs/plan_deepdive_specs_20260924.md DP-1 §5）
# 登记 followUp。本段为**最小诚实交付**（分支选择树与出处核查见
# runs/df7_dp1r4/criteria.md §1，先写死后动工 #122）：
# - 触发判定 helper：判据=scripts/df6_dp1p3_judge.py summarize() 逐位同式
#   （median 符号一致性、|d|<0.05dB 平局剔除、阈值 0.8）——不自造口径；
# - 精化对照归档框架：缺省腿=既有 solve_chain 原路径（零改动，缺省关）；
#   精化腿=槽位制，Xu-Wu 2005 候选式因**原文不可达**（七路核查，criteria
#   §1）如实登记 blocked——blocked 槽位禁止携带数值 S 参数（防冒充钉）。
#   未来原文逐位核对通过（df6 经验⑬⑭ 口径）→ status="active" + 传入
#   refined_chain 才产出双套数值并排归档。


@dataclass(frozen=True)
class G1TriggerVerdict:
    """G1「超差且方向单调」触发判定输出（规格风险④触发条件的确定性裁定）。

    判据（逐位同 runs/df6_dp1p3_judge.py summarize()，criteria §2）：
    sign_consistency = #{sign(d)==sign(median(d))} / max(n−n_tie, 1)，
    d=逐频带符号偏差 dB 序列（HFSS−MMT），|d|<tie_db 平局剔除。
    monotonic_direction 仅是"系统性方向偏差存在"的判定，**不构成**对
    G1 门值（0.5dB 起步门）或 verdict 语义（#350 双记）的任何翻案。
    """

    monotonic_direction: bool
    sign_consistency: float
    signed_median_db: float
    direction: int  # sign(median)：+1=MMT 系统性低反射 / −1=高反射 / 0=无向
    n_judged: int
    n_tie: int
    band_ghz: tuple[float, float] | None  # judged 点频率范围（GHz）

    def to_json_dict(self) -> dict:
        """JSON 面输出（tuple→list；字段确定性排序，无时间戳）。"""
        return {
            "monotonic_direction": self.monotonic_direction,
            "sign_consistency": self.sign_consistency,
            "signed_median_db": self.signed_median_db,
            "direction": self.direction,
            "n_judged": self.n_judged,
            "n_tie": self.n_tie,
            "band_ghz": (list(self.band_ghz)
                         if self.band_ghz is not None else None),
        }


def g1_systematic_bias_check(
    freqs_hz: np.ndarray,
    signed_dev_db: np.ndarray,
    judged: np.ndarray | None = None,
    *,
    sign_fraction_threshold: float = 0.8,
    tie_db: float = 0.05,
) -> G1TriggerVerdict:
    """带符号偏差序列的方向系统性判定（规格风险④触发判定，criteria §2）。

    judged 掩码缺省全判（None）；judged 内非有限值显式报错（不静默）；
    judged 后零点 → ValueError（无点不可判，不凑判 #122）。
    median 由 np.median 给出（偶数点取中二均值——与 judge 同库同式）。
    阈值缺省 0.8/平局 0.05dB = P3 判读在档口径，跨批不得改动。
    """
    f = np.asarray(freqs_hz, dtype=float)
    d = np.asarray(signed_dev_db, dtype=float)
    if f.ndim != 1 or d.ndim != 1 or f.shape != d.shape:
        raise ValueError(f"g1_systematic_bias_check: freqs{f.shape} 与 "
                         f"signed_dev{d.shape} 必须为同长一维数组")
    if f.size == 0:
        raise ValueError("g1_systematic_bias_check: 空序列不可判")
    if judged is None:
        mask = np.ones(f.size, dtype=bool)
    else:
        mask = np.asarray(judged, dtype=bool)
        if mask.shape != f.shape:
            raise ValueError(f"g1_systematic_bias_check: judged{mask.shape} "
                             f"与 freqs{f.shape} 形状不符")
    dj = d[mask]
    if not np.all(np.isfinite(dj)):
        raise ValueError("g1_systematic_bias_check: judged 点含非有限偏差"
                         "（undetermined/深零点应由调用方先剔除或掩码外置）")
    if dj.size == 0:
        raise ValueError("g1_systematic_bias_check: judged 掩码后零点不可判")
    med = float(np.median(dj))
    n_tie = int(np.sum(np.abs(dj) < tie_db))
    n_same = int(np.sum(np.sign(dj) == np.sign(med)))
    denom = max(dj.size - n_tie, 1)
    fj = f[mask]
    return G1TriggerVerdict(
        monotonic_direction=bool(n_same / denom >= sign_fraction_threshold),
        sign_consistency=n_same / denom,
        signed_median_db=med,
        direction=int(np.sign(med)),
        n_judged=int(dj.size),
        n_tie=n_tie,
        band_ghz=(float(fj.min()) / 1e9, float(fj.max()) / 1e9),
    )


@dataclass(frozen=True)
class RefinementSlot:
    """精化式槽位（对照归档的出处/状态元数据；df7_dp1r4 分支 b）。

    status="blocked"：公式候选登记在案但**原文逐位核对未完成**——
    该状态下 :func:`iris_refinement_comparison` 拒绝任何 refined 数值
    （防冒充钉：二级转引不冒充已核对，df6 经验⑬）。status="active"：
    原文核对通过后由后续批翻转，此时传入 refined_chain 产出双套数值。
    """

    formula_id: str
    status: str  # "blocked" | "active"
    candidate_formula: str
    source: str
    verification_note: str

    def __post_init__(self) -> None:
        if self.status not in ("blocked", "active"):
            raise ValueError(f"RefinementSlot: status 须为 blocked/active，"
                             f"得到 {self.status!r}")

    def to_json_dict(self) -> dict:
        return {"formula_id": self.formula_id, "status": self.status,
                "candidate_formula": self.candidate_formula,
                "source": self.source,
                "verification_note": self.verification_note}


#: Xu-Wu 2005 精化式候选（SIW 等效宽度精化族）——原文不可达如实 blocked
#: （七路核查证据 runs/df7_dp1r4/criteria.md §1，2026-09-26）。
XU_WU_2005_REFINEMENT_BLOCKED = RefinementSlot(
    formula_id="xu_wu_2005_w_eff",
    status="blocked",
    candidate_formula="a_eff = a - 1.08*d^2/s + 0.1*d^2/a",
    source=("Feng Xu & Ke Wu, Guided-Wave and Leakage Characteristics of "
            "Substrate Integrated Waveguide, IEEE TMTT 53(1):66-73, 2005, "
            "DOI 10.1109/TMTT.2004.839303"),
    verification_note=(
        "原文逐位核对未完成（2026-09-26 七路核查：IEEE 付费墙/OpenAlex "
        "closed/Unpaywall 无副本/SemanticScholar 回指 DOI/PolyPublie 网络"
        "不可达/ResearchGate 反爬/Scribd 阅读器锁死）——系数形状经二级"
        "转引多源互证（Wikipedia REST+仓内规格书 :15 一致）但不冒充原文"
        "核对；核对通过前本槽位禁止产出任何数值 S 参数"),
)


def _s2x2_json(s: np.ndarray) -> list:
    """(F,2,2) 复数组 → JSON 面（NaN/undetermined 行=None 如实，不外推）。"""
    out: list = []
    for i in range(s.shape[0]):
        row: list = []
        for a in range(2):
            cell: list = []
            for b in range(2):
                c = complex(s[i, a, b])
                if not (math.isfinite(c.real) and math.isfinite(c.imag)):
                    cell.append(None)
                else:
                    cell.append([c.real, c.imag])
            row.append(cell)
        out.append(row)
    return out


def iris_refinement_comparison(
    chain: list,
    freqs_hz,
    policy: ModePolicy | None = None,
    *,
    refined_chain: list | None = None,
    refinement_slot: RefinementSlot | None = None,
) -> dict:
    """膜片精化对照归档（风险④「双公式对照归档」的框架腿，缺省关）。

    缺省腿恒走既有 :func:`solve_chain` 原路径（本函数不触碰缺省数学，
    既有测试全绿钉）；精化腿仅在 refined_chain 与 status="active" 槽位
    同时在场时产出数值——blocked 槽位 + refined_chain、或无槽位裸
    refined_chain 显式报错（不冒充）。返回 JSON 可直接序列化的 dict
    （复数=[re,im]、undetermined=None）。
    """
    if refined_chain is not None:
        if refinement_slot is None:
            raise ValueError(
                "iris_refinement_comparison: refined 数值必须携带槽位元数据"
                "（出处/核对状态；无槽位的精化数值不可归档，#122）")
        if refinement_slot.status == "blocked":
            raise ValueError(
                "iris_refinement_comparison: 精化槽位 status=blocked（原文核对"
                "未完成）不得携带 refined 数值——先完成原文逐位核对并翻转槽位"
                "（criteria §1/#122 不凑绿）")
    res_default = solve_chain(chain, freqs_hz, policy)
    res_refined = (solve_chain(refined_chain, freqs_hz, policy)
                   if refined_chain is not None else None)
    det = ~res_default.undetermined
    out: dict = {
        "schema": "rfauto-mmt-refinement/v1",
        "gate_ref": "runs/df7_dp1r4/criteria.md §1/§3（分支 b 最小诚实交付）",
        "freqs_ghz": [float(f) / 1e9 for f in res_default.freqs_hz],
        "n_points": int(res_default.freqs_hz.size),
        "n_determined": int(det.sum()),
        "default": {
            "converged": bool(res_default.converged),
            "n_modes": list(res_default.n_modes),
            "s2x2": _s2x2_json(res_default.s2x2),
        },
        "refined": None if res_refined is None else {
            "converged": bool(res_refined.converged),
            "n_modes": list(res_refined.n_modes),
            "s2x2": _s2x2_json(res_refined.s2x2),
        },
        "refinement": (refinement_slot.to_json_dict()
                       if refinement_slot is not None else None),
    }
    return out
