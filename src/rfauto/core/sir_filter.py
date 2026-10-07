"""TF-4 双通带 SIR（阶跃阻抗谐振器）滤波器内核：谐振条件 + 杂散比 + 双带映射。

法源（铁律 5：来源写 docstring；裁判=独立来源不自证，#118）：

- SIR 框架与记号：M. Makimoto & S. Yamashita《Microwave Resonators and
  Filters for Wireless Communication Theory》Springer 1980
  （doi:10.1007/978-3-642-81759-3）Ch.2——**馆藏原文不可达，公式号未逐位
  核对**；本文件全部闭式由传输线代数自推导，经双路径裁判（Z_in 闭式 vs
  ABCD 级联，rel ≤1e-15）与数值求根互证（rel ≤5e-16）后钉死（#118：
  数值算法的裁判是独立来源数值，不是文献转述）。文献只锚定框架与术语
  （SIR/阻抗比/杂散谐振口径）。
- 基本单元：短端 λg/4 型 SIR——输入端阻抗 Z1（电长 θ1）、短路段 Z2
  （θ2），输入阻抗闭式
      Z_in = j·Z1·(Z1·tanθ1 + Z2·tanθ2) / (Z1 − Z2·tanθ1·tanθ2)。
  并联谐振（Z_in→∞）条件：**tanθ1·tanθ2 = Z1/Z2 ≡ Rz**。
  记号登记：本模块 Rz := Z1/Z2（输入段/短路段）。任务书首句
  "Rz=Z2/Z1" 与其自身给定的等长闭式 θ=atan(√Rz)（代入谐振条件
  tan²θ=Rz 才自洽）矛盾——按任务书闭式一致口径钉死为 Rz=Z1/Z2，
  与原始推导一致。
- 等长闭式：θ1=θ2=θ 时 θ = atan(√Rz)，恒等式 tan²(atan(√Rz)) = Rz
  逐位（tests 钉）。第一杂散（并联谐振族，基频之上最小解）：
  **f_s1/f0 = π/θ − 1 = π/atan(√Rz) − 1**，对全部 Rz>0 成立
  （解族 r ∈ {π/θ−1, 1, 1+π/θ, ...} 按 θ 与 π/4 的关系排序后
  π/θ−1 恒为最小的大于 1 的解；θ→π/4⁻（UIR，Rz=1）时给出 3，与
  λ/4 UIR 杂散谱 3f0,5f0,7f0 一致，逐位锚）。任务书引
  "π/(2·atan(√Rz))−1 量级"在 Rz=1 处给 1 而非 3，判为转述笔误
  （其自带"按原文式钉死"与"量级"两处留白），本文件按自推导 +
  brentq 求根（rel 5e-16，tests 钉）钉死，如实在此登记偏差。
- 双带映射（等长闭式）：令第一杂散承载第二通带 f2，r = f2/f1 > 1：
  r = π/atan(√Rz) − 1 ⇒ atan(√Rz) = π/(r+1) ⇒
  **Rz = tan²(π/(r+1))**。往返（rz_from_band_ratio ∘
  band_ratio_from_rz）rel 1e-9 门（实测 0）。锚点：r=3 ⇔ Rz=1（UIR，
  float 下 rel 1e-15——tan(π/4) 最近浮点为 1−1.1e-16，非逐位）；
  r=5 ⇔ Rz=1/3（tan²(π/6)，rel 1e-12）。
- 半闭式（θ1 给定的不等长设计）：给定 r 与 θ1（θ1∈(0,π/2) 且
  r·θ1 不落正切极点），解 θ2 使两频率同时并联谐振：
  tanθ1·tanθ2 = tan(r·θ1)·tan(r·θ2)。经积化和差化为**无极点方程**
  (1−κ)·sin((1+r)θ2) = (1+κ)·sin((r−1)θ2)，κ = tan(r·θ1)/tan(θ1)，
  细网格扫符号变化 + brentq 取最小正根（κ=−1 即等长情形，根
  θ2 = π/(1+r) 闭式复现，tests 钉）；随后 Rz = tanθ1·tanθ2。
  三通带（f3 由第二杂散承载）按任务书如实缓做。
- 耦合面（两谐振器双带网，标准式）：外部 Q 与耦合系数
  **Qe = g0·g1/FBW**、**k12 = FBW/√(g1·g2)**（Hong & Lancaster 2001
  §5.3 / Cameron-Kudesia-Mansour 口径的耦合谐振器标准式）；倒置器
  J_01 = sqrt(b̄/(Qe·Z0))、J_12 = k12·b̄（b̄ = (ω0/2)·dIm(Y)/dω|_{f1}
  为 SIR 电纳斜率参数，中心差分数值——声明近似源，差分步 h=1e-5·f0，
  tests 以 UIR 锚 b̄=π/(4·Z_S) 针定）。J-inverter ABCD =
  [[0, j/J], [j·J, 0]]（admittance 倒置器口径）。
- 频响验证面：[J01][SIR₁][J12][SIR₂][J01] ABCD 级联，双峰位置对
  f1/f2 实测 rel ≤0.01%（预声明门 ±5%，500× 余量；tests 钉）。
  近似源如实登记：b̄ 数值差分、窄带耦合理论（J 逐频常数）。

纯算法零 IO；不进 calculators 注册表。判缺失一律 is not None（#364④）；
bool 显式拒收（df7+⑯）；数值入参 0.0 的合法性逐函数注明。单位钉在
参数名（Hz/Ω/rad）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import brentq

__all__ = [
    "SirGeometry",
    "SirTwoPoleCoupling",
    "band_ratio_from_rz",
    "rz_from_band_ratio",
    "sir_coupling",
    "sir_geometry",
    "sir_resonance_residual",
    "sir_slope",
    "sir_theta2_unequal",
    "sir_theta_equal",
    "sir_two_pole_sparams",
    "sir_zin",
    "sir_zin_abcd",
]

#: 双带等长映射的反演锚（r=3 ⇔ UIR，docstring 口径）
_UIR_RATIO = 3.0
#: 电纳斜率数值差分的相对步长（声明近似源）
_SLOPE_REL_STEP = 1e-5
#: 不等长求根的粗扫格点数
_ROOT_SCAN_N = 4096


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _theta_open(value: float, name: str) -> float:
    """电长度收敛：有限且落在 (0, π/2)（任务书判据 θ∉(0,π/2)→ValueError）。"""
    out = _finite(value, name)
    if not (0.0 < out < math.pi / 2.0):
        raise ValueError(f"{name} 必须落在 (0, π/2)，实际 {out}")
    return out


# ─── 1. 阻抗闭式与谐振条件 ───────────────────────────────────────────────────


def sir_zin(z1: float, z2: float, theta1: float, theta2: float) -> complex:
    """短端 λg/4 型 SIR 输入阻抗（纯虚，jX 形态）。

    z1/z2：两段特征阻抗（>0，Ω）；theta1/theta2：电长度（rad，(0, π/2)
    之外为外推域，本函数放行但不保证极点族语义——谐振面用
    sir_resonance_residual）。Z_in = j·Z1·(Z1·tanθ1+Z2·tanθ2)/
    (Z1−Z2·tanθ1·tanθ2)；分母为 0（恰在并联谐振点）时显式 ValueError
    （无穷不是有限 float，调用方以 residual 判谐振）。
    """
    za = _positive(z1, "z1")
    zb = _positive(z2, "z2")
    t1 = _finite(theta1, "theta1")
    t2 = _finite(theta2, "theta2")
    den = za - zb * math.tan(t1) * math.tan(t2)
    if den == 0.0:
        raise ValueError("Z_in 分母为 0（恰在并联谐振点），以 sir_resonance_residual 判谐振")
    return complex(0.0, za * (za * math.tan(t1) + zb * math.tan(t2)) / den)


def sir_zin_abcd(z1: float, z2: float, theta1: float, theta2: float) -> complex:
    """同一输入阻抗的独立路径：两段传输线 ABCD 矩阵级联 + 短路负载 → B/D。

    #118 双路径裁判专用（与 sir_zin 的 tan 代数完全不同源，tests 钉
    rel ≤1e-12，实测 ~1e-15）。实现取矩阵乘积 B/D 元素式（不做手写
    展开转录，杜绝抄写因子丢失）。短路负载 V2=0 ⇒ Z_in = B/D。
    """
    za = _positive(z1, "z1")
    zb = _positive(z2, "z2")
    t1 = _finite(theta1, "theta1")
    t2 = _finite(theta2, "theta2")
    c1, s1 = math.cos(t1), math.sin(t1)
    c2, s2 = math.cos(t2), math.sin(t2)
    line1 = np.array([[c1, 1j * za * s1], [1j * s1 / za, c1]], dtype=complex)
    line2 = np.array([[c2, 1j * zb * s2], [1j * s2 / zb, c2]], dtype=complex)
    cascade = line1 @ line2
    d_tot = cascade[1, 1]
    if d_tot == 0.0:
        raise ValueError("ABCD 路径 D=0（并联谐振点），以 sir_resonance_residual 判谐振")
    return cascade[0, 1] / d_tot


def sir_resonance_residual(z1: float, z2: float, theta1: float, theta2: float) -> float:
    """并联谐振残差 Z1 − Z2·tanθ1·tanθ2（=0 即谐振；单位 Ω）。

    恒等式：等长 θ=atan(√Rz) 时 |residual| ≤ 1e-12·Z1（tests 钉 2.2e-16）。
    """
    za = _positive(z1, "z1")
    zb = _positive(z2, "z2")
    t1 = _finite(theta1, "theta1")
    t2 = _finite(theta2, "theta2")
    return za - zb * math.tan(t1) * math.tan(t2)


def sir_theta_equal(rz: float) -> float:
    """等长 SIR 电长度 θ = atan(√Rz)（rad；恒等式 tan²θ = Rz 逐位，tests 钉）。

    rz = Z1/Z2 > 0（判据：rz<=0 → ValueError，任务书）。
    """
    r = _positive(rz, "rz")
    return math.atan(math.sqrt(r))


# ─── 2. 杂散比与双带映射 ─────────────────────────────────────────────────────


def band_ratio_from_rz(rz: float) -> float:
    """等长 SIR 第一杂散比 f_s1/f0 = π/atan(√Rz) − 1（对全部 Rz>0 成立）。

    锚点：Rz=1（UIR）→ 3.0（λ/4 UIR 杂散谱 3f0，逐位）；Rz→0 → ∞；
    Rz→∞ → 1（退化）。数值求根互证 rel ≤5e-16（tests 钉）。
    """
    r = _positive(rz, "rz")
    return math.pi / math.atan(math.sqrt(r)) - 1.0


def rz_from_band_ratio(ratio: float) -> float:
    """双带映射（等长闭式）：f2/f1 = r → Rz = tan²(π/(r+1))。

    判据：ratio > 1（f2>f1，ratio<=1 → ValueError，任务书带宽域）。
    往返 band_ratio_from_rz ∘ rz_from_band_ratio 逐位（tests 钉 1e-9 门，
    实测 0）。锚点：r=3 → Rz=1（UIR）逐位；r=5 → Rz=1/3（rel 1e-12）。
    """
    r = _finite(ratio, "ratio")
    if r <= 1.0:
        raise ValueError(f"ratio 必须 >1（第二通带高于基频），实际 {r}")
    return math.tan(math.pi / (r + 1.0)) ** 2


@dataclass(frozen=True)
class SirGeometry:
    """SIR 几何（电学口径）：阻抗对 + 电长度对 + 参考频率。

    miniaturization_frac = 1 − (θ1+θ2)/(π/2)：相对等长 UIR 的长度缩短
    份额（>0 短于 UIR，<0 长于 UIR——Rz>1 的低比双带设计合法地长于
    UIR）。物理长度/线宽经 core/synthesis.py 在 service 层实现（本内
    核只出电学量，不消费 εr，规避名义几何口径漂移）。
    """

    z1_ohm: float
    z2_ohm: float
    theta1_rad: float
    theta2_rad: float
    f0_hz: float | None = None  # 基频（None=未指定，判缺失 is not None）

    @property
    def rz(self) -> float:
        """阻抗比 Rz = Z1/Z2（本模块口径，docstring 登记）。"""
        return self.z1_ohm / self.z2_ohm

    @property
    def miniaturization_frac(self) -> float:
        return 1.0 - (self.theta1_rad + self.theta2_rad) / (math.pi / 2.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "z1_ohm": self.z1_ohm,
            "z2_ohm": self.z2_ohm,
            "theta1_rad": self.theta1_rad,
            "theta2_rad": self.theta2_rad,
            "f0_hz": self.f0_hz,
            "rz": self.rz,
            "miniaturization_frac": self.miniaturization_frac,
        }


def sir_geometry(
    z1: float,
    z2: float,
    theta1: float,
    theta2: float,
    f0_hz: float | None = None,
) -> SirGeometry:
    """构造并校验 SIR 几何（全部入参过守卫；f0 可缺省 None）。"""
    za = _positive(z1, "z1")
    zb = _positive(z2, "z2")
    t1 = _theta_open(theta1, "theta1")
    t2 = _theta_open(theta2, "theta2")
    f0 = None if f0_hz is None else _positive(f0_hz, "f0_hz")
    return SirGeometry(z1_ohm=za, z2_ohm=zb, theta1_rad=t1, theta2_rad=t2, f0_hz=f0)


def sir_theta2_unequal(theta1: float, ratio: float) -> tuple[float, float]:
    """不等长双带半闭式：给定 θ1 与通带比 r，解 (θ2, Rz)。

    方程：tanθ1·tanθ2 = tan(r·θ1)·tan(r·θ2)（两频同时并联谐振）。经积
    和差化为无极点形式 (1−κ)·sin((1+r)θ2) − (1+κ)·sin((r−1)θ2) = 0，
    κ = tan(r·θ1)/tan(θ1)，粗扫符号变化 + brentq 取最小正根。
    判据：θ1 ∈ (0, π/2) 且 r·θ1 不得落在正切极点（cos(r·θ1)=0）——
    基频族（r·θ1<π/2，κ>0）与杂散族（π/2<r·θ1<π，κ<0，等长双带即
    此支 κ=−1）均支持；θ2=0 平凡根显式排除。κ=−1 时根 = π/(1+r)
    （等长复现，tests 钉 1e-9）。
    """
    t1 = _finite(theta1, "theta1")
    r = _finite(ratio, "ratio")
    if r <= 1.0:
        raise ValueError(f"ratio 必须 >1，实际 {r}")
    if not (0.0 < t1 < math.pi / 2.0):
        raise ValueError(f"theta1 必须落在 (0, π/2)，实际 {t1}")
    if math.cos(r * t1) == 0.0:
        raise ValueError(f"r·theta1={r * t1!r} 落在正切极点，κ 无定义")
    kappa = math.tan(r * t1) / math.tan(t1)

    def eq(t2: float) -> float:
        return (1.0 - kappa) * math.sin((1.0 + r) * t2) - (1.0 + kappa) * math.sin(
            (r - 1.0) * t2
        )

    grid = np.linspace(0.0, math.pi / 2.0, _ROOT_SCAN_N + 1)
    vals = np.array([eq(float(t)) for t in grid])
    root: float | None = None
    for i in range(1, _ROOT_SCAN_N + 1):
        if vals[i - 1] == 0.0:
            continue
        if vals[i - 1] * vals[i] < 0.0:
            root = brentq(eq, float(grid[i - 1]), float(grid[i]), xtol=1e-15, rtol=8.9e-16)
            break
    if root is None or root <= 1e-9:
        raise ValueError(
            f"在 (0, π/2) 内未找到非平凡 θ2 根（theta1={t1}, ratio={r}）"
        )
    rz = math.tan(t1) * math.tan(root)
    if not (rz > 0.0 and math.isfinite(rz)):
        raise ValueError(f"解出的 Rz 非正有限：{rz!r}")
    return float(root), float(rz)


# ─── 3. 耦合面（两谐振器双带网）──────────────────────────────────────────────


@dataclass(frozen=True)
class SirTwoPoleCoupling:
    """两谐振器双带耦合网参数（外部 Q + k12 + 倒置器值）。

    标准式：Qe = g0·g1/FBW、k12 = FBW/√(g1·g2)（Hong-Lancaster §5.3 /
    Cameron 口径）；J_01 = sqrt(b̄/(Qe·Z0))、J_12 = k12·b̄（b̄ 为 SIR
    电纳斜率参数，sir_slope 数值给出——声明近似源）。
    """

    qe: float
    k12: float
    j01: float  # 端倒置器值（S）
    j12: float  # 谐振器间倒置器值（S）
    slope: float  # b̄（S；数值差分，声明近似源）

    def to_dict(self) -> dict[str, Any]:
        return {
            "qe": self.qe,
            "k12": self.k12,
            "j01": self.j01,
            "j12": self.j12,
            "slope": self.slope,
        }


def sir_slope(
    z1: float, z2: float, theta1: float, theta2: float, f0_hz: float
) -> float:
    """SIR 电纳斜率参数 b̄ = (ω0/2)·dIm(Y_in)/dω|_{f0}（中心差分，声明近似源）。

    差分相对步长 1e-5（模块常量 _SLOPE_REL_STEP）。锚点：等长
    z1=z2=Z_S（UIR，θ1=θ2=45°）时 b̄ = π/(4·Z_S)（λ/4 短路 stub 闭式，
    tests 钉 1e-8）。
    """
    za = _positive(z1, "z1")
    zb = _positive(z2, "z2")
    t1 = _finite(theta1, "theta1")
    t2 = _finite(theta2, "theta2")
    f0 = _positive(f0_hz, "f0_hz")
    h = _SLOPE_REL_STEP * f0
    y_plus = 1.0 / sir_zin(za, zb, t1 * (f0 + h) / f0, t2 * (f0 + h) / f0)
    y_minus = 1.0 / sir_zin(za, zb, t1 * (f0 - h) / f0, t2 * (f0 - h) / f0)
    d_y_per_hz = (y_plus.imag - y_minus.imag) / (2.0 * h)
    # b̄ = (ω0/2)·dY/dω，dY/dω = (dY/df)/(2π) ⇒ b̄ = f0·(dY/df)/2
    return f0 * d_y_per_hz / 2.0


def sir_coupling(
    g: list[float], fbw: float, slope: float, z0_ohm: float
) -> SirTwoPoleCoupling:
    """两谐振器耦合网参数：Qe/k12/J01/J12（g = [g0, g1, g2, g3]，N=2 口径）。"""
    if not isinstance(g, (list, tuple)) or len(g) != 4:
        raise ValueError(f"g 必须为 [g0, g1, g2, g3]（N=2 口径），实际 {g!r}")
    gvals = [_positive(v, f"g[{i}]") for i, v in enumerate(g)]
    f = _finite(fbw, "fbw")
    if not (0.0 < f < 1.0):
        raise ValueError(f"fbw 必须落在 (0,1)，实际 {f}")
    b = _positive(slope, "slope")
    z0 = _positive(z0_ohm, "z0_ohm")
    qe = gvals[0] * gvals[1] / f
    k12 = f / math.sqrt(gvals[1] * gvals[2])
    j01 = math.sqrt(b / (qe * z0))
    j12 = k12 * b
    return SirTwoPoleCoupling(qe=qe, k12=k12, j01=j01, j12=j12, slope=b)


def sir_two_pole_sparams(
    freqs_hz: np.ndarray,
    geom: SirGeometry,
    coupling: SirTwoPoleCoupling,
    z0_ohm: float = 50.0,
) -> tuple[np.ndarray, np.ndarray]:
    """两谐振器双带网频响：[J01][SIR₁][J12][SIR₂][J01] ABCD → (S11, S21)。

    SIR 以并联支路 Y_in = 1/Z_in(f) 进入（电长随频率线性缩放：
    θ_i(f) = θ_i·f/f0，f0 = geom.f0_hz）。J-inverter ABCD =
    [[0, j/J],[j·J, 0]]（admittance 倒置器口径；几何须带 f0_hz）。
    """
    if geom.f0_hz is None:
        raise ValueError("geom.f0_hz 缺失（None），两谐振器网频响需参考频率")
    f0 = geom.f0_hz
    z0 = _positive(z0_ohm, "z0_ohm")
    freqs = np.atleast_1d(np.asarray(freqs_hz, dtype=float))

    def _jinv(j: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return (
            np.zeros_like(freqs, dtype=complex),
            1j / j * np.ones_like(freqs, dtype=complex),
            1j * j * np.ones_like(freqs, dtype=complex),
            np.zeros_like(freqs, dtype=complex),
        )

    def _sir_abcd() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        t1 = geom.theta1_rad * freqs / f0
        t2 = geom.theta2_rad * freqs / f0
        with np.errstate(divide="ignore", invalid="ignore"):
            den = geom.z1_ohm - geom.z2_ohm * np.tan(t1) * np.tan(t2)
            y = (
                geom.z1_ohm * (geom.z1_ohm * np.tan(t1) + geom.z2_ohm * np.tan(t2))
                / den
            )
            y = 1.0 / (1j * y)
        return (
            np.ones_like(freqs, dtype=complex),
            np.zeros_like(freqs, dtype=complex),
            y,
            np.ones_like(freqs, dtype=complex),
        )

    a = np.ones_like(freqs, dtype=complex)
    b = np.zeros_like(freqs, dtype=complex)
    c = np.zeros_like(freqs, dtype=complex)
    d = np.ones_like(freqs, dtype=complex)
    for j_inv, then_sir in ((coupling.j01, True), (coupling.j12, True), (coupling.j01, False)):
        ja, jb, jc, jd = _jinv(j_inv)
        a, b, c, d = a * ja + b * jc, a * jb + b * jd, c * ja + d * jc, c * jb + d * jd
        if then_sir:
            sa, sb, sc, sd = _sir_abcd()
            a, b, c, d = a * sa + b * sc, a * sb + b * sd, c * sa + d * sc, c * sb + d * sd
    den = a + b / z0 + c * z0 + d
    s21 = 2.0 / den
    s11 = (a + b / z0 - c * z0 - d) / den
    return s11, s21
