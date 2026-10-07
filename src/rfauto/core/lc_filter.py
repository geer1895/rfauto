"""TF-1 可实现 LC 滤波器综合内核：原型面 + Cauer I 梯形 + Foster + 可实现化。

法源（铁律 5：来源写 docstring；裁判=独立来源不自证，#118）：

- 原型面：scipy.signal（butter/cheby1/cheby2/bessel，analog、Wn=1 归一化低通）
  的极零/多项式。cheby1/cheby2 的 Wn=1 与文献口径一致（cheby1=纹波带缘、
  cheby2=阻带起点），实测 |H(jω)|² 与闭式逐点一致（tests 钉）。
- 功率损耗比 PLR(ω) = 1/|H|²−1 闭式：butter 1+ω^{2N}；cheby1 ε²T_N²(ω)、
  ε²=10^{r/10}−1；cheby2 1/(ε₂²T_N²(1/ω))、ε₂²=1/(10^{As/10}−1)。
  T_N 幂系数由 numpy.polynomial.chebyshev.cheb2poly 展开。
- Cauer I 综合（文献第二路径，#118 双路径）：g_k 闭式
  butter g_k=2sin((2k−1)π/2N)（Wikipedia "Butterworth filter" Cauer 节转录，
  引 Bennett 1932 专利/Mattaei-Young-Jones pp.104-107）；chebyshev 递式
  G1=2A₁/γ、G_k=4A_{k−1}A_k/(B_{k−1}G_{k−1})、γ=sinh(β/2n)、β=ln coth(δ/17.37)
  （17.37=40/ln10 精确值；Wikipedia "Chebyshev filter" 节转录，引
  Matthaei-Young-Jones 1964 §4.05）。两条路径与本文综合互证 ≤3e-13（实测）。
- 文献 g_k 表（4 位）：按上式重算后钉入 tests（0.1/0.5 dB，N=3/5/7；
  butter N=2..7 用闭式），表值舍入精度 ±5e-5 rel（预声明）。

**Darlington 口径钉死**（任务书预声明）：双端接、等源/负载阻抗（g0=g_{N+1}=1）、
最小电抗、全极点低通原型的简化 Darlington（插入损耗法）——S11 由
1+PLR 谱因子化（LHP 根）构造，Cauer I（s=∞ 处极点/零点的连分式展开）得梯形
g_k。**不支持**：chebyshev2（有限传输零点，需一般 Darlington 零点提取）与
chebyshev1 偶数阶（偶阶等纹波原型在 DC 处 |S11|≠0，等端接不可实现，需
g_{N+1}≠1 的不等端接口径）——均显式 ValueError。**bessel 只入原型面**：
DC 归一化 bessel 的等端接 Cauer I 连分式实测产生非正元件（2026-09-27 实证，
N=2..7 全部），如实受限不做。

精度等级（实测，tests 钉）：g_k vs 闭式/MYJ 递式 ≤3e-13；理想梯形 ABCD 频响
vs 闭式 |H|² ≤1e-12（预声明 1e-6 判据的实测余量 6 个量级）；Foster 回代恒等式
≤1e-9（预声明）。

可实现化（vendor_passives 同源约定）：Q→ESR 换算 esr_from_q（Q=ωL/ESR 或
Q=1/(ωC·ESR)，与 core/vendor_passives.q_factor 的 Im/Re 口径一致）；
容差注入后 f_c 漂移按 worst_case（全 ±tol 两极，频率伸缩定理下精确
fc→fc/(1+tol)）与 monte_carlo（固定 seed 的 numpy Generator）双口径。

纯函数零 IO（numpy/scipy.signal）；数值只在确定性内核（铁律 7）；数值 0.0
合法，判缺失一律 is not None（#364④）；bool 显式拒收（df7+⑯）。单位钉在
参数名（Hz/Ω/H/F）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.polynomial import chebyshev as _cheb
from scipy import signal

__all__ = [
    "CAUER_RESPONSES",
    "RESPONSES",
    "CauerLadder",
    "FosterNetwork",
    "FosterTank",
    "LadderElement",
    "PrototypeSpec",
    "ToleranceStudy",
    "cauer_ladder_gk",
    "denormalize_ladder",
    "esr_from_q",
    "find_fc_3db_hz",
    "foster_i_synthesis",
    "foster_ii_synthesis",
    "foster_impedance",
    "ladder_sparams",
    "make_prototype",
    "power_gain_ideal",
    "power_loss_ratio",
    "prototype_pz",
    "tolerance_study",
]

#: 支持的原型响应面（scipy.signal 全集）
RESPONSES = ("butterworth", "chebyshev1", "chebyshev2", "bessel")
#: Cauer I 梯形综合支持的响应（全极点 + 等端接可实现；见模块 docstring 口径钉死）
CAUER_RESPONSES = ("butterworth", "chebyshev1")

#: 连分式提取时的多项式剪枝相对容差（相对最大系数；实测残余 ≤1e-13）
_PRUNE_RTOL = 1e-10
#: S11 零点聚簇容差（u 域；cheby 零点间隔 O(1/N²) 远大于此）
_CLUSTER_RTOL = 1e-6
#: Foster 部分分式残数虚部容差（LC 阻抗函数残数必为实数）
_RESIDUE_IMAG_RTOL = 1e-8
#: g_load 等端接恒等判据
_GLOAD_RTOL = 1e-9
#: monte_carlo 缺省 seed（固定可复现）
_DEFAULT_SEED = 20260927


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


def _order(value: int, name: str) -> int:
    """阶数收敛：int 且 >=1（N<1 → ValueError，任务书判据）。"""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} 必须为 int，实际 {type(value).__name__}")
    out = int(value)
    if out < 1:
        raise ValueError(f"{name} 必须 >=1（N<1 无定义），实际 {out}")
    return out


def _prune(coeffs: np.ndarray, rtol: float = _PRUNE_RTOL) -> np.ndarray:
    """多项式剪枝：去掉 |c| <= rtol·max|c| 的前导系数（浮点残差≈解析零）。"""
    arr = np.asarray(coeffs, dtype=float)
    if arr.size == 0:
        return np.array([0.0])
    scale = float(np.max(np.abs(arr)))
    idx = np.nonzero(np.abs(arr) > rtol * scale)[0]
    return arr[idx[0]:] if idx.size else np.array([0.0])


# ─── 1. 原型面（scipy.signal 极零 + 闭式 |H|²）────────────────────────────────


@dataclass(frozen=True)
class PrototypeSpec:
    """归一化低通原型规格（ω_c=1，|H|² 峰值归一）。"""

    response: str  # RESPONSES 之一
    order: int  # N >= 1
    ripple_db: float | None = None  # cheby1 通带纹波（>0）
    stopband_atten_db: float | None = None  # cheby2 阻带衰减（>0）

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "order": int(self.order),
            "ripple_db": self.ripple_db,
            "stopband_atten_db": self.stopband_atten_db,
        }


def make_prototype(
    response: str,
    order: int,
    ripple_db: float | None = None,
    stopband_atten_db: float | None = None,
) -> PrototypeSpec:
    """构造并校验原型规格。

    判据（#122 先行）：response 不在 RESPONSES / N<1 / cheby1 纹波<=0 /
    cheby2 衰减<=0 → ValueError。butter 的纹波/衰减参数不消费（给 None）。
    """
    if response not in RESPONSES:
        raise ValueError(f"response 必须是 {RESPONSES} 之一，实际 {response!r}")
    n = _order(order, "order")
    if response == "chebyshev1":
        if ripple_db is None:
            raise ValueError("chebyshev1 必须给 ripple_db（>0）")
        if _finite(ripple_db, "ripple_db") <= 0.0:
            raise ValueError(f"chebyshev1 纹波必须 >0，实际 {ripple_db}")
    if response == "chebyshev2":
        if stopband_atten_db is None:
            raise ValueError("chebyshev2 必须给 stopband_atten_db（>0）")
        if _finite(stopband_atten_db, "stopband_atten_db") <= 0.0:
            raise ValueError(f"chebyshev2 阻带衰减必须 >0，实际 {stopband_atten_db}")
    return PrototypeSpec(
        response=response,
        order=n,
        ripple_db=None if ripple_db is None else float(ripple_db),
        stopband_atten_db=None if stopband_atten_db is None else float(stopband_atten_db),
    )


def _scipy_call(spec: PrototypeSpec, output: str = "zpk") -> tuple[Any, ...]:
    """scipy.signal 原型调用（Wn=1，模拟，归一化低通）。"""
    if spec.response == "butterworth":
        return signal.butter(spec.order, 1, "lowpass", analog=True, output=output)
    if spec.response == "chebyshev1":
        return signal.cheby1(
            spec.order, spec.ripple_db, 1, "lowpass", analog=True, output=output
        )
    if spec.response == "chebyshev2":
        return signal.cheby2(
            spec.order,
            spec.stopband_atten_db,
            1,
            "lowpass",
            analog=True,
            output=output,
        )
    return signal.bessel(
        spec.order, 1, "lowpass", analog=True, output=output, norm="mag"
    )


def prototype_pz(spec: PrototypeSpec) -> tuple[np.ndarray, np.ndarray]:
    """原型极零（scipy.signal zpk）：返回 (zeros, poles)，复数组。"""
    z, p, _k = _scipy_call(spec, output="zpk")
    return np.asarray(z, dtype=complex), np.asarray(p, dtype=complex)


def power_gain_ideal(spec: PrototypeSpec, omega: float | np.ndarray) -> np.ndarray:
    """理想归一化功率增益 |H(jω)|²（ω 为归一化角频率，ω_c=1）。

    butter/cheby1/cheby2 用闭式（tests 与 scipy 极零评估互证 ≤1e-12）；
    bessel 无初等闭式常用口径，经 scipy 极零评估 |H|²=k²/Π|jω−p|²。
    """
    w = np.atleast_1d(np.asarray(omega, dtype=float))
    cheb_coeffs = np.eye(spec.order + 1)[spec.order]  # T_N 的 Chebyshev 基系数
    if spec.response == "butterworth":
        gain = 1.0 / (1.0 + w ** (2 * spec.order))
    elif spec.response == "chebyshev1":
        eps2 = 10.0 ** (spec.ripple_db / 10.0) - 1.0
        tn = _cheb.chebval(w, cheb_coeffs)
        gain = 1.0 / (1.0 + eps2 * tn**2)
    elif spec.response == "chebyshev2":
        eps2 = 1.0 / (10.0 ** (spec.stopband_atten_db / 10.0) - 1.0)
        tn = _cheb.chebval(1.0 / w, cheb_coeffs)
        t2 = tn**2
        with np.errstate(divide="ignore", invalid="ignore"):
            # PLR = 1/(ε₂²T_N²(1/ω))：传输零点（T=0）处 PLR→∞、|H|²→0
            gain = 1.0 / (1.0 + 1.0 / (eps2 * t2))
        gain = np.where(t2 > 0.0, gain, 0.0)
    else:
        _z, p, k = _scipy_call(spec, output="zpk")
        hjw = np.full(w.shape, complex(k), dtype=complex)
        for pole in p:
            hjw = hjw / (1j * w - pole)
        gain = np.abs(hjw) ** 2
    return gain


def power_loss_ratio(spec: PrototypeSpec, omega: float | np.ndarray) -> np.ndarray:
    """功率损耗比 PLR(ω) = 1/|H|²−1（特征函数平方口径）。

    cheby2 传输零点处 |H|²=0 → PLR=∞（inf，errstate 压 divide 告警）。
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        gain = power_gain_ideal(spec, omega)
        plr = 1.0 / gain - 1.0
    return np.where(np.isfinite(gain) & (gain > 0.0), plr, math.inf)


# ─── 2. Cauer I 梯形综合（连分式）────────────────────────────────────────────


def _plr_poly_u_butter(n: int) -> np.ndarray:
    """P(u)=1+PLR(ω²=−u)=1+(−u)^N，u 升幂（butter：|D(jω)|²/k² 口径）。"""
    pu = np.zeros(n + 1)
    pu[n] = (-1.0) ** n
    pu[0] += 1.0
    return pu


def _plr_poly_u_cheby1(n: int, ripple_db: float) -> np.ndarray:
    """P(u)=1+ε²T_N²(ω)|ω²=−u，u 升幂（cheby1：峰值归一 |H|²=1/P）。"""
    tn = _cheb.cheb2poly(np.eye(n + 1)[n])
    q = np.convolve(tn, tn)  # T_N² ω 升幂（convolve 不截断，长度 2n+1）
    even = q[::2]  # (ω²)^j 系数
    pu = np.zeros(n + 1)
    for j, c in enumerate(even):
        pu[j] = c * ((-1.0) ** j)  # ω²=−u
    eps2 = 10.0 ** (ripple_db / 10.0) - 1.0
    out = eps2 * pu
    out[0] += 1.0
    return out


def _u_roots_to_lhp_s(u_roots: np.ndarray) -> np.ndarray:
    """单实 u 根 → 单 LHP s 根（谱因子化专用：极点不在 jω 轴，无重根问题）。"""
    out = []
    for u in u_roots:
        r = np.sqrt(complex(u))
        r = -r if r.real > 0 else r
        out.append(r)
    return np.asarray(out, dtype=complex)


def _spec_factor_d(p_u: np.ndarray) -> np.ndarray:
    """P(u)（u 升幂）→ D(s)（s 降幂实系数）：1+PLR 的 LHP 谱因子。"""
    u_roots = np.roots(p_u[::-1])  # np.roots 收降幂
    s_poles = _u_roots_to_lhp_s(u_roots)
    d = np.real_if_close(np.poly(s_poles), tol=1000)
    if not np.isrealobj(d):
        raise ValueError("谱因子化失败：D(s) 出现复系数（原型多项式病态）")
    return np.real(d)


def _s11_zeros_cheby1(n: int) -> np.ndarray:
    """cheby1 S11 零点闭式：s=±j·cos((2k−1)π/2N)（T_N 零点），奇数阶再乘 s。

    闭式避免 P(u)−1 的 u 域二重根数值分裂（实测 np.roots 分裂 ~3e-4，
    会破坏共轭封闭性）。
    """
    thetas = (2 * np.arange(1, n + 1) - 1) * np.pi / (2 * n)
    c2 = np.cos(thetas) ** 2
    n_quad = n // 2  # 不同 |cos| 值数（偶数阶 N/2 个；奇数阶 ± 对去掉一份）
    poly = np.array([1.0])
    for ck in c2[:n_quad]:
        poly = np.convolve(poly, np.array([1.0, 0.0, ck]))
    if n % 2 == 1:
        poly = np.convolve(np.array([1.0, 0.0]), poly)
    return poly


def _cauer_continued_fraction(
    num: np.ndarray, den: np.ndarray, n_elements: int
) -> tuple[list[tuple[str, float]], float]:
    """Cauer I 连分式（s=∞ 展开），Z/Y 状态机。

    num/den 为 s 降幂实系数。每步：当前分数在 ∞ 有极点（次数差恰 1）→
    按当前 Z/Y 朝向提取串 L / 并 C；否则取倒数翻转朝向。返回
    ([(kind, value), ...], g_load)。浮点残差经 _prune 收敛后逐位精确
    （实测元素值 vs 闭式 ≤3e-13）。
    """
    num = _prune(num)
    den = _prune(den)
    vals: list[tuple[str, float]] = []
    state = "Z"
    for _ in range(n_elements):
        dn, dd = len(num) - 1, len(den) - 1
        if dn != dd + 1:
            num, den = den, num
            state = "Y" if state == "Z" else "Z"
            dn, dd = len(num) - 1, len(den) - 1
            if dn != dd + 1:
                raise ValueError(
                    f"Cauer I 连分式不可继续（次数 dn={dn} dd={dd}）："
                    "原型在该口径下不可实现为等端接 LC 梯形"
                )
        kind = "series_L" if state == "Z" else "shunt_C"
        value = num[0] / den[0]
        num = _prune(np.polysub(num, value * np.polymul(np.array([1.0, 0.0]), den)))
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"Cauer I 提取出非正元件 {kind}={value!r}：原型不可实现为无源梯形"
            )
        vals.append((kind, float(value)))
    return vals, float(num[0] / den[0])


@dataclass(frozen=True)
class LadderElement:
    """梯形元件（归一化 g 值或去归一化物理值）。

    esr_ohm：等效串联电阻（可实现化注入；None=理想无耗，判缺失 is not None）。
    """

    kind: str  # "L" | "C"
    role: str  # "series" | "shunt"
    value: float  # H（L）或 F（C）；归一化梯形里为无量纲 g 值
    esr_ohm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "role": self.role,
            "value": self.value,
            "esr_ohm": self.esr_ohm,
        }


@dataclass
class CauerLadder:
    """Cauer I 综合结果：梯形元件表（源端→负载端）+ 终接与出处。"""

    response: str
    order: int
    elements: list[LadderElement]
    g_load: float  # 终接 g_{N+1}（等端接口径 ≈1.0）
    first_element: str  # "series_L" | "shunt_C"
    fc_hz: float | None = None  # None=归一化（ω_c=1, Z0=1）；去归一化后为物理值
    z0_ohm: float | None = None
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.response,
            "order": int(self.order),
            "elements": [el.to_dict() for el in self.elements],
            "g_load": self.g_load,
            "first_element": self.first_element,
            "fc_hz": self.fc_hz,
            "z0_ohm": self.z0_ohm,
            "sources": dict(self.sources),
        }


def cauer_ladder_gk(spec: PrototypeSpec, first_element: str = "series") -> CauerLadder:
    """原型 → Cauer I 梯形 g_k（归一化 ω_c=1、Z0=1、g0=g_{N+1}=1）。

    口径钉死（模块 docstring）：全极点等端接简化 Darlington。chebyshev2 /
    chebyshev1 偶数阶 / bessel → ValueError（如实受限）。
    first_element: "series"（g1=串 L，缺省）或 "shunt"（g1=并 C；对称原型
    两口径 g 值相同，tests 钉恒等）。
    """
    if first_element not in ("series", "shunt"):
        raise ValueError(f"first_element 必须是 series/shunt，实际 {first_element!r}")
    if spec.response not in CAUER_RESPONSES:
        if spec.response == "chebyshev2":
            raise ValueError(
                "chebyshev2 含有限传输零点，不属于全极点 Cauer I 口径"
                "（需一般 Darlington 零点提取，本内核不支持）"
            )
        raise ValueError(
            "bessel 等端接 Cauer I 连分式实测产生非正元件（2026-09-27 实证 "
            "N=2..7），只支持原型面不支持梯形综合（口径见模块 docstring）"
        )
    if spec.response == "chebyshev1" and spec.order % 2 == 0:
        raise ValueError(
            "chebyshev1 偶数阶在 DC 处 |S11|≠0，等端接（g_{N+1}=1）不可实现；"
            "请用奇数阶或文献不等端接口径（本内核不支持）"
        )

    if spec.response == "butterworth":
        p_u = _plr_poly_u_butter(spec.order)
        n11 = np.zeros(spec.order + 1)
        n11[0] = 1.0  # butter S11 零点全在 s=0：N11=s^N
    else:
        p_u = _plr_poly_u_cheby1(spec.order, spec.ripple_db)
        n11 = _s11_zeros_cheby1(spec.order)

    d = _spec_factor_d(p_u)
    dn = d / d[0]
    n11 = n11 / n11[0] * dn[0]  # 首一匹配 → S11(∞)=+1
    num, den = (dn + n11, dn - n11) if first_element == "series" else (dn - n11, dn + n11)
    vals, g_load = _cauer_continued_fraction(num, den, spec.order)
    if abs(g_load - 1.0) > _GLOAD_RTOL:
        raise ValueError(
            f"终接 g_{{N+1}}={g_load!r} ≠1（等端接口径被破坏）：原型不可实现"
        )
    elements = [
        LadderElement(
            kind="L" if kind == "series_L" else "C",
            role="series" if kind == "series_L" else "shunt",
            value=value,
        )
        for kind, value in vals
    ]
    return CauerLadder(
        response=spec.response,
        order=spec.order,
        elements=elements,
        g_load=g_load,
        first_element="series_L" if first_element == "series" else "shunt_C",
        sources={
            "synthesis": "Cauer I continued fraction on LHP spectral factor of 1+PLR",
            "gk_reference": "Zverev Handbook of Filter Synthesis; MYJ 1964 formulas "
            "(per Wikipedia Chebyshev/Butterworth filter transcriptions)",
        },
    )


def denormalize_ladder(ladder: CauerLadder, fc_hz: float, z0_ohm: float) -> CauerLadder:
    """归一化梯形 → 物理梯形：L'=L·Z0/ω_c，C'=C/(Z0·ω_c)，ω_c=2π·fc。

    频率伸缩定理：全体 L、C 同乘 (1+δ) ⇔ 响应在 ω 轴压缩 (1+δ) 倍
    （worst_case 容差漂移的解析依据，tests 钉恒等）。
    """
    fc = _positive(fc_hz, "fc_hz")
    z0 = _positive(z0_ohm, "z0_ohm")
    w_c = 2.0 * math.pi * fc
    elements = [
        LadderElement(
            kind=el.kind,
            role=el.role,
            value=el.value * z0 / w_c if el.kind == "L" else el.value / (z0 * w_c),
            esr_ohm=el.esr_ohm,
        )
        for el in ladder.elements
    ]
    return CauerLadder(
        response=ladder.response,
        order=ladder.order,
        elements=elements,
        g_load=ladder.g_load,
        first_element=ladder.first_element,
        fc_hz=fc,
        z0_ohm=z0,
        sources=dict(ladder.sources),
    )


# ─── 3. 可实现化：ESR(Q) 注入 + 频响面 ────────────────────────────────────────


def esr_from_q(q: float, kind: str, value: float, f0_hz: float) -> float:
    """Q→ESR 换算（与 core/vendor_passives.q_factor 的 Im/Re 口径一致）。

    L：Q=ωL/ESR → ESR=ωL/Q；C：Q=1/(ωC·ESR) → ESR=1/(ωC·Q)。ω 在 f0_hz 处取值。
    """
    if kind not in ("L", "C"):
        raise ValueError(f"kind 必须是 L/C，实际 {kind!r}")
    qv = _positive(q, "q")
    val = _positive(value, "value")
    f0 = _positive(f0_hz, "f0_hz")
    omega = 2.0 * math.pi * f0
    if kind == "L":
        return omega * val / qv
    return 1.0 / (omega * val * qv)


def ladder_sparams(
    elements: list[LadderElement],
    omega: np.ndarray,
    z0_ohm: float = 50.0,
) -> tuple[np.ndarray, np.ndarray]:
    """梯形频响：ABCD 级联 → (S11, S21)（复数组，端接 z0_ohm）。

    元件表按源端→负载端序。串 L 含 ESR 时阻抗 = ESR + jωL；并 C 含 ESR 时
    支路阻抗 = ESR + 1/(jωC)（ESR 串联于 C，判缺失 is not None，#364④）。
    """
    z0 = _positive(z0_ohm, "z0_ohm")
    w = np.atleast_1d(np.asarray(omega, dtype=float))
    a_mat = np.ones_like(w, dtype=complex)
    b_mat = np.zeros_like(w, dtype=complex)
    c_mat = np.zeros_like(w, dtype=complex)
    d_mat = np.ones_like(w, dtype=complex)
    for el in elements:
        if el.role == "series":
            z_branch = 1j * w * el.value
            if el.esr_ohm is not None:
                z_branch = z_branch + el.esr_ohm
            am, bm, cm, dm = (
                np.ones_like(w, dtype=complex),
                z_branch,
                np.zeros_like(w, dtype=complex),
                np.ones_like(w, dtype=complex),
            )
        else:
            z_branch = 1.0 / (1j * w * el.value)
            if el.esr_ohm is not None:
                z_branch = z_branch + el.esr_ohm
            am, bm, cm, dm = (
                np.ones_like(w, dtype=complex),
                np.zeros_like(w, dtype=complex),
                1.0 / z_branch,
                np.ones_like(w, dtype=complex),
            )
        a_mat, b_mat, c_mat, d_mat = (
            a_mat * am + b_mat * cm,
            a_mat * bm + b_mat * dm,
            c_mat * am + d_mat * cm,
            c_mat * bm + d_mat * dm,
        )
    den = a_mat + b_mat / z0 + c_mat * z0 + d_mat
    s21 = 2.0 / den
    s11 = (a_mat + b_mat / z0 - c_mat * z0 - d_mat) / den
    return s11, s21


def find_fc_3db_hz(freqs_hz: np.ndarray, s21: np.ndarray) -> float | None:
    """|S21|² 首次跌破 0.5（−3.0103 dB）的频率（线性插值）；无穿越 → None。"""
    freqs = np.asarray(freqs_hz, dtype=float)
    p = np.abs(np.asarray(s21, dtype=complex)) ** 2
    for i in range(1, freqs.size):
        if p[i - 1] >= 0.5 > p[i]:
            frac = (p[i - 1] - 0.5) / (p[i - 1] - p[i])
            return float(freqs[i - 1] + frac * (freqs[i] - freqs[i - 1]))
    return None


@dataclass
class ToleranceStudy:
    """容差/Q 注入漂移研究（worst_case 或 monte_carlo 单口径）。

    fc_ideal_hz：理想元件 −3dB 频率；shifted 系列注入容差（与可选 ESR）。
    worst_case 另报两极 fc_all_up_hz/fc_all_down_hz（频率伸缩定理：全体
    L,C ×(1+tol) ⇔ fc ÷(1+tol)，解析恒等，tests 钉 ≤1e-9）。
    monte_carlo 另报样本统计（固定 seed 可复现）。
    """

    mode: str  # "worst_case" | "monte_carlo"
    tol_frac: float
    fc_ideal_hz: float
    fc_shifted_hz: float | None  # worst_case=min(两极)；monte_carlo=样本均值
    fc_shift_rel: float | None
    il_ideal_db: float  # 带内（f<=fc_ideal）最大插入损耗（正值 dB）
    il_shifted_db: float | None
    fc_all_up_hz: float | None = None
    fc_all_down_hz: float | None = None
    fc_samples: list[float] = field(default_factory=list)
    n_samples: int = 0
    seed: int | None = None
    q_l: float | None = None
    q_c: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "tol_frac": self.tol_frac,
            "fc_ideal_hz": self.fc_ideal_hz,
            "fc_shifted_hz": self.fc_shifted_hz,
            "fc_shift_rel": self.fc_shift_rel,
            "il_ideal_db": self.il_ideal_db,
            "il_shifted_db": self.il_shifted_db,
            "fc_all_up_hz": self.fc_all_up_hz,
            "fc_all_down_hz": self.fc_all_down_hz,
            "fc_samples": list(self.fc_samples),
            "n_samples": int(self.n_samples),
            "seed": self.seed,
            "q_l": self.q_l,
            "q_c": self.q_c,
        }


def _band_il_db(freqs_hz: np.ndarray, s21: np.ndarray, fc_hz: float) -> float:
    """带内（f<=fc_hz）最大插入损耗 −10·log10(min|S21|²)（正值 dB）。"""
    p = np.abs(s21) ** 2
    mask = freqs_hz <= fc_hz
    if not bool(np.any(mask)):
        return float("inf")
    p_min = float(np.min(p[mask]))
    return math.inf if p_min <= 0.0 else -10.0 * math.log10(p_min)


def _fc_on_grid(elements: list[LadderElement], fc_hz: float, z0_ohm: float) -> float | None:
    """两阶段找 −3dB 交越：粗网格定位 + 窄带细化（网格无关性 ~1e-10，
    供频率伸缩恒等判据 ≤1e-7 消费）。"""
    coarse = np.linspace(fc_hz / 50.0, fc_hz * 3.0, 2001)
    _s11, s21 = ladder_sparams(elements, 2.0 * math.pi * coarse, z0_ohm)
    fc1 = find_fc_3db_hz(coarse, s21)
    if fc1 is None:
        return None
    fine = np.linspace(fc1 * (1.0 - 5e-3), fc1 * (1.0 + 5e-3), 4001)
    _s11, s21 = ladder_sparams(elements, 2.0 * math.pi * fine, z0_ohm)
    fc2 = find_fc_3db_hz(fine, s21)
    return fc2 if fc2 is not None else fc1


def tolerance_study(
    ladder: CauerLadder,
    tol_frac: float,
    q_l: float | None = None,
    q_c: float | None = None,
    mode: str = "worst_case",
    n_samples: int = 200,
    seed: int = _DEFAULT_SEED,
) -> ToleranceStudy:
    """vendor 容差 + Q（ESR）注入 → f_c/带内损耗漂移估计。

    tol_frac：每元件 ± 相对容差（>=0；0 → 漂移逐位 0，tests 钉）。
    q_l/q_c：可选品质因数（f_c 处定义，经 esr_from_q 注入 ESR；
    None=该类元件理想无耗，判缺失 is not None）。
    mode：worst_case（全 +tol / 全 −tol 两极）或 monte_carlo（每元件独立
    U[−tol,+tol]，numpy default_rng(seed) 固定可复现）。
    """
    if mode not in ("worst_case", "monte_carlo"):
        raise ValueError(f"mode 必须是 worst_case/monte_carlo，实际 {mode!r}")
    tol = _finite(tol_frac, "tol_frac")
    if tol < 0.0:
        raise ValueError(f"tol_frac 必须 >=0，实际 {tol}")
    if ladder.fc_hz is None or ladder.z0_ohm is None:
        raise ValueError("ladder 必须先经 denormalize_ladder 去归一化（fc_hz/z0 非缺）")
    fc = _positive(ladder.fc_hz, "ladder.fc_hz")
    z0 = _positive(ladder.z0_ohm, "ladder.z0_ohm")
    n_draw = _order(n_samples, "n_samples") if mode == "monte_carlo" else 0

    ideal_elems = ladder.elements
    # 网格显式含 fc（带内损耗解析锚：理想 butter 在 fc 处 |S21|²=0.5 逐位）
    freqs = np.unique(np.concatenate([np.linspace(fc / 50.0, fc * 3.0, 6001), [fc]]))
    omega = 2.0 * math.pi * freqs
    _s11, s21_ideal = ladder_sparams(ideal_elems, omega, z0)
    fc_ideal = _fc_on_grid(ideal_elems, fc, z0)
    if fc_ideal is None:
        raise ValueError("理想梯形在探测带内无 −3dB 交越（网格/原型异常）")
    il_ideal = _band_il_db(freqs, s21_ideal, fc_ideal)

    def _with(tol_signed: np.ndarray | None) -> list[LadderElement]:
        out = []
        for idx, el in enumerate(ideal_elems):
            value = el.value if tol_signed is None else el.value * (1.0 + tol_signed[idx])
            esr = None
            if el.kind == "L" and q_l is not None:
                esr = esr_from_q(q_l, "L", value, fc)
            elif el.kind == "C" and q_c is not None:
                esr = esr_from_q(q_c, "C", value, fc)
            out.append(LadderElement(el.kind, el.role, value, esr_ohm=esr))
        return out

    if mode == "worst_case":
        ups = _with(np.full(len(ideal_elems), tol))
        downs = _with(np.full(len(ideal_elems), -tol))
        fc_up = _fc_on_grid(ups, fc, z0)
        fc_down = _fc_on_grid(downs, fc, z0)
        fc_shifted = min(x for x in (fc_up, fc_down) if x is not None)
        il_up = _band_il_db(freqs, ladder_sparams(ups, omega, z0)[1], fc_ideal)
        il_down = _band_il_db(freqs, ladder_sparams(downs, omega, z0)[1], fc_ideal)
        return ToleranceStudy(
            mode=mode,
            tol_frac=tol,
            fc_ideal_hz=fc_ideal,
            fc_shifted_hz=fc_shifted,
            fc_shift_rel=fc_shifted / fc_ideal - 1.0,
            il_ideal_db=il_ideal,
            il_shifted_db=max(il_up, il_down),
            fc_all_up_hz=fc_up,
            fc_all_down_hz=fc_down,
            q_l=q_l,
            q_c=q_c,
        )

    rng = np.random.default_rng(int(seed))
    draws = rng.uniform(-tol, tol, size=(n_draw, len(ideal_elems)))
    fc_samples: list[float] = []
    il_shifted = 0.0
    for row in draws:
        elems = _with(row)
        fc_i = _fc_on_grid(elems, fc, z0)
        if fc_i is None:
            continue
        fc_samples.append(fc_i)
        il_shifted = max(il_shifted, _band_il_db(freqs, ladder_sparams(elems, omega, z0)[1], fc_ideal))
    if not fc_samples:
        raise ValueError("monte_carlo 全部样本无 −3dB 交越（容差/网格异常）")
    fc_mean = float(np.mean(fc_samples))
    return ToleranceStudy(
        mode=mode,
        tol_frac=tol,
        fc_ideal_hz=fc_ideal,
        fc_shifted_hz=fc_mean,
        fc_shift_rel=fc_mean / fc_ideal - 1.0,
        il_ideal_db=il_ideal,
        il_shifted_db=il_shifted,
        fc_samples=fc_samples,
        n_samples=len(fc_samples),
        seed=int(seed),
        q_l=q_l,
        q_c=q_c,
    )


# ─── 4. Foster 综合（谐振子部分分式）─────────────────────────────────────────


@dataclass(frozen=True)
class FosterTank:
    """单个谐振子（Foster I：并 L、C 的串联谐振支路→等效并联谐振腔）。"""

    l_h: float
    c_f: float
    omega0: float  # 1/sqrt(LC)（弧度/秒）

    def to_dict(self) -> dict[str, Any]:
        return {"l_h": self.l_h, "c_f": self.c_f, "omega0": self.omega0}


@dataclass
class FosterNetwork:
    """Foster 综合结果（I：串联谐振腔链；II：其对偶）。

    I：Z(s) = L∞·s + 1/(C0·s) + Σ (L_i s)/(L_iC_i s²+1)（各腔串联）。
    II：对偶口径，Y(s) 部分分式（各串联 LC 腔并联），输入阻抗仍等于原 Z。
    """

    kind: str  # "foster_i" | "foster_ii"
    tanks: list[FosterTank]
    l_inf_h: float  # ∞ 处极点项（I：串 L；II：0=无）
    c0_f: float  # s=0 极点项（I：串 C；None 语义经 is None 判）
    num: np.ndarray = field(repr=False, default_factory=lambda: np.array([0.0]))
    den: np.ndarray = field(repr=False, default_factory=lambda: np.array([1.0]))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tanks": [t.to_dict() for t in self.tanks],
            "l_inf_h": self.l_inf_h,
            "c0_f": self.c0_f,
        }


def _check_lc_impedance(num: np.ndarray, den: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """LC 阻抗函数校验：分母根为 jω 轴单根。返回 (num, den, 正虚部极点)。

    输入多项式**不剪枝**：物理单位的有理函数动态范围可达 20 个量级
    （如 a4~3e-40 vs max~4e-20），按相对幅值剪枝会把真实高阶项当噪声
    吞掉（实测 ∞ 极点项丢失 → l_inf=0）。
    """
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    if num.size < 1 or den.size < 1:
        raise ValueError("阻抗函数 num/den 多项式阶数不足")
    if den[0] == 0.0:
        raise ValueError("den 首系数为 0（降幂约定被破坏）")
    poles = np.roots(den)
    pos_im = []
    for r in poles:
        if abs(r.real) > 1e-8 * max(1.0, abs(r)):
            raise ValueError(f"极点 {r!r} 不在 jω 轴上：非 LC（无源无耗）阻抗函数")
    for r in poles:
        is_jw = abs(r.real) <= 1e-8 * max(1.0, abs(r))
        if is_jw and r.imag > 0:
            if any(abs(r - q) <= 1e-6 * max(1.0, abs(q)) for q in pos_im):
                raise ValueError(f"极点 {r!r} 为重根：LC 阻抗函数要求单根")
            pos_im.append(r)
    return num, den, np.asarray(sorted(pos_im, key=lambda z: z.imag), dtype=complex)


def _residue_at(num: np.ndarray, den: np.ndarray, pole: complex) -> complex:
    """单极点残数 Res = num(p)/den'(p)。"""
    dp = np.polyder(den)
    return complex(np.polyval(num, pole) / np.polyval(dp, pole))


def _foster_tanks(
    num: np.ndarray, den: np.ndarray, pos_im: np.ndarray, kind: str
) -> list[FosterTank]:
    """正虚部极点 → 谐振子（残数必须实且 >=0，否则非 LC 可实现）。

    部分分式项 = k·s/(s²+ω0²)，k = 2·Re(res)：
    Foster I（Z 口径，并 L 串 C 腔）：Z 腔 = (1/C)·s/(s²+1/(LC)) → C=1/k、
    L=k/ω0²；Foster II（Y 口径，串 L 并 C 腔）：Y 腔同型 → L=1/k、C=k/ω0²。
    """
    tanks = []
    for pole in pos_im:
        w0 = pole.imag
        res = _residue_at(num, den, pole)
        if abs(res.imag) > _RESIDUE_IMAG_RTOL * max(1.0, abs(res)):
            raise ValueError(
                f"极点 j{w0:.6g} 处残数含虚部 {res!r}：非 LC 阻抗函数（残数必为实数）"
            )
        k = 2.0 * res.real
        if k <= 0.0:
            raise ValueError(
                f"极点 j{w0:.6g} 处残数 {res.real!r} <=0：非正实 LC 实现（Foster 判据）"
            )
        if kind == "foster_i":
            tanks.append(FosterTank(l_h=k / w0**2, c_f=1.0 / k, omega0=w0))
        else:
            tanks.append(FosterTank(l_h=1.0 / k, c_f=k / w0**2, omega0=w0))
    return tanks


def foster_i_synthesis(num: np.ndarray, den: np.ndarray) -> FosterNetwork:
    """Foster I：Z(s)=num/den → 串 L∞ + 串 C0 + 串联谐振腔链。

    恒等式（tests 钉 ≤1e-9 频网格）：foster_impedance(net, ω) == Z(jω)。
    num/den 为 s 降幂实系数；deg(num) <= deg(den)+1（∞ 处至多单极点）。
    """
    num_p, den_p, pos_im = _check_lc_impedance(num, den)
    if len(num_p) > len(den_p) + 1:
        raise ValueError("deg(num) > deg(den)+1：∞ 处多重极点，非可实现 LC 阻抗")
    tanks = _foster_tanks(num_p, den_p, pos_im, kind="foster_i")
    l_inf = 0.0
    if len(num_p) == len(den_p) + 1:
        l_inf = float(num_p[0] / den_p[0])
        if l_inf <= 0.0:
            raise ValueError(f"∞ 极点残数 {l_inf!r} <=0：非正实 LC 实现")
    c0 = 0.0
    if den_p[-1] == 0.0:
        a0 = _residue_at(num_p, den_p, 0j)
        if abs(a0.imag) > _RESIDUE_IMAG_RTOL * max(1.0, abs(a0)) or a0.real <= 0.0:
            raise ValueError(f"s=0 极点残数 {a0!r} 非正实：非 LC 可实现")
        c0 = float(1.0 / a0.real)
    return FosterNetwork(
        kind="foster_i",
        tanks=tanks,
        l_inf_h=l_inf,
        c0_f=c0,
        num=num_p,
        den=den_p,
    )


def foster_ii_synthesis(num: np.ndarray, den: np.ndarray) -> FosterNetwork:
    """Foster II：对偶口径，Y(s)=den/num 部分分式 → 并联串联-LC 腔链。

    输入阻抗仍等于原 Z（Y=1/Z 的网络实现）；l_inf_h/c0_f 语义为对偶项
    （Y 的 0/∞ 极点 → 并 L0/并 C∞）。num/den 约定同 foster_i_synthesis。
    """
    num_p, den_p, _pos_im_z = _check_lc_impedance(num, den)
    y_num, y_den = den_p, num_p
    # Y 的极点 = Z 的零点：部分分式与可实现性校验必须对 Y 自身进行
    # （实测错用 Z 的极点频率求 Y 残数 → 回代恒等式爆 3 个量级）
    _yn, y_den_c, pos_im_y = _check_lc_impedance(y_num, y_den)
    if len(y_num) > len(y_den_c) + 1:
        raise ValueError("Y(s) 在 ∞ 处多重极点：Foster II 不可实现该函数")
    tanks = _foster_tanks(y_num, y_den_c, pos_im_y, kind="foster_ii")
    c_inf = 0.0
    if len(y_num) == len(y_den) + 1:
        c_inf_val = float(y_num[0] / y_den[0])
        if c_inf_val <= 0.0:
            raise ValueError(f"Y(∞) 残数 {c_inf_val!r} <=0：非正实 LC 实现")
        c_inf = c_inf_val
    l0 = 0.0
    if y_den[-1] == 0.0:
        a0 = _residue_at(y_num, y_den, 0j)
        if abs(a0.imag) > _RESIDUE_IMAG_RTOL * max(1.0, abs(a0)) or a0.real <= 0.0:
            raise ValueError(f"Y(s) s=0 极点残数 {a0!r} 非正实：非 LC 可实现")
        l0 = float(1.0 / a0.real)
    return FosterNetwork(
        kind="foster_ii",
        tanks=tanks,
        l_inf_h=l0,  # 对偶：Y 的 s=0 极点 → 并 L0（存 l_inf_h 槽位）
        c0_f=c_inf,  # 对偶：Y 的 ∞ 极点 → 并 C∞（存 c0_f 槽位）
        num=num_p,
        den=den_p,
    )


def foster_impedance(net: FosterNetwork, omega: np.ndarray) -> np.ndarray:
    """重建阻抗 Z(jω)（Foster I 直接累加；Foster II 经 1/Y 累加）。

    I：Z = L∞·jω + 1/(C0·jω) + Σ (L_i jω)/(L_iC_i (jω)²+1)；
    II：Y = jωC∞ + 1/(jωL0) + Σ (C_i jω)/(L_iC_i (jω)²+1)，Z=1/Y。
    """
    w = np.atleast_1d(np.asarray(omega, dtype=float))
    jw = 1j * w
    if net.kind == "foster_i":
        z = np.zeros_like(jw)
        if net.l_inf_h > 0.0:
            z = z + net.l_inf_h * jw
        if net.c0_f > 0.0:
            z = z + 1.0 / (net.c0_f * jw)
        for t in net.tanks:
            z = z + (t.l_h * jw) / (t.l_h * t.c_f * jw * jw + 1.0)
        return z
    y = np.zeros_like(jw)
    if net.c0_f > 0.0:  # 对偶槽位：并 C∞
        y = y + net.c0_f * jw
    if net.l_inf_h > 0.0:  # 对偶槽位：并 L0
        y = y + 1.0 / (net.l_inf_h * jw)
    for t in net.tanks:
        y = y + (t.c_f * jw) / (t.l_h * t.c_f * jw * jw + 1.0)
    return 1.0 / y
