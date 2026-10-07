"""MM-7 均匀化通用内核：三混合式+Wiener 界+SRR μ+线媒质 ωp+等效参数反演。

规格（研究扩充 round17 §五 :154，B 流超材料）：
「三混合式提升通用 core 内核+Wiener 界+Pendry 1999 SRR μ 公式+线媒质 ωp
（Pendry 1996 PRL）」。

五面与法源（铁律 5：来源写 docstring；裁判=独立路径/合成回收，不自证，
#118）：

- **三混合式通用核**（自 core/humidity_drift 的实数湿度语境提升为复数
  通用面，depolarization 因子 L 可调形状族）：
  - Maxwell-Garnett（球夹杂稀疏极限，J.C.M. Garnett, Phil. Trans. R.
    Soc. Lond. A 203:385 (1904)，式取基质 ε_m 相），椭球夹杂 L 因子
    广义：ε_eff = ε_m + ε_m·v(ε_i−ε_m)/(ε_m + L(1−v)(ε_i−ε_m))；
    L=1/3 逐式退化回 humidity_drift.maxwell_garnett_mix（跨模块一致性
    测试钉 rel≤1e-12）。
  - Bruggeman 对称有效介质（D.A.G. Bruggeman, Ann. Phys. 416:636
    (1935)）：v(ε_a−ε)/(ε_b+Aε) + (1−v)(ε_b−ε)/(ε_b+Aε) 同形两相和=0
    （A=(1−L)/L，两相同形状 L）→ 二次方程 A·ε²+c·ε−ε_a·ε_b=0，
    c = v·ε_b+(1−v)·ε_a − A(v·ε_a+(1−v)·ε_b)；物理根=两根中距线性混合
    v·ε_a+(1−v)·ε_b 最近者（v→0 连续性定理化；实数正输入下等价于
    Re>0 根选择，humidity_drift 闭式根 rel≤1e-12 一致钉）。L=0 极限
    方程退化显式拒绝（诚实边界）。
  - Looyenga（H. Looyenga, Physica 31:401 (1965)）：ε_eff^(1/3) 按体积
    分数线性加权，复数取主枝立方根（Re>0、Im≥0 输入下 arg∈[0,π) →
    主枝根 arg/3 连续）。L=1/3 实数正输入与 humidity_drift.looyenga_mix
    逐式一致（rel≤1e-12 钉）。
- **Wiener 界**（A. Wiener 1912 资格界）：算术平均（并联板，上界）
  (1−v)ε_m+v·ε_i 与调和平均（串联板，下界）1/((1−v)/ε_m+v/ε_i)。
  实数正输入下三混合式结果必落界内（负例测试裁判）；形状极限恒等式：
  MG 取 L→0（沿场细棒）=上界、L=1（法向薄片）=下界——两极限即
  Wiener 界本身（物理锚）。
- **形状族 depolarization 因子闭式**：sphere/cube=(1/3,1/3,1/3)
  （立方对称等分；球为椭球 L 恒等式 ΣL=1 的对称点）、disk=(0,0,1)
  （无穷薄片：面内 0、法向 1）、rod=(0,1/2,1/2)（无穷细棒：轴向 0、
  横向 1/2）。ΣL=1 恒等式逐形状钉。各向异性张量面：L 按轴入参即得
  单轴 ε_eff（rod 轴向走 Wiener 上界/横向走中庸、disk 法向走下界）；
  独立张量综合机制规格未给，显式不做。
- **Pendry 1999 SRR μ**（J.B. Pendry, A.J. Holden, D.J. Robbins,
  W.J. Stewart, "Magnetism from conductors and enhanced nonlinear
  phenomena", IEEE Trans. MTT 47(11):2075 (1999) Lorentz 形，arXiv
  2006.13861 同式口径互证）：
      μ(ω) = 1 − F·ω²/(ω² − ω0² + iΓω)
  F=填充因子 ∈(0,1)、ω0=环谐振角频、Γ=阻尼。解析锚：μ(0)=1、
  μ(∞)=1−F；无损（Γ=0）μ=0 精确点 ω_mp=ω0/√(1−F)（磁等离子频率，
  等价参数化 F=1−(f_res/f_mp)²）、Re μ<0 带恰为 (ω0, ω_mp)；Γ>0 时
  Im μ>0 全带（无源性，同式原文保证 μ″>0）。诚实边界：SRR 几何闭式
  ω0(环半径/宽度/间隙) 原文常数需回 PDF 逐位核（#118 家族纪律），
  本面只收 Lorentz 参数化，几何→ω0 换算留 MM-11 极化率库。
- **线媒质等离子频率**（J.B. Pendry, A.J. Holden, W.J. Stewart,
  I. Youngs, "Extremely Low Frequency Plasmons in Metallic
  Mesostructures", Phys. Rev. Lett. 76:4773 (1996)）：
      ωp² = 2π·c0²/(a²·ln(a/r))
  a=晶格常数、r=线半径（a/r>1）；Drude 型 ε(ω)=1−ωp²/(ω(ω+jν))
  （e^{−jωt} 口径：ν>0 → Im ε>0 无损正性；ν=0、ω<ωp → Re ε<0；
  ω=ωp 精确零点）。锚：a=1mm、r=1µm → f_p≈45.6 GHz（比金属光学等
  离子频率低约 5 个量级——"extremely low frequency" 量化锚）。
- **等效参数反演**（法向入射对称面板，Smith 2002 PRB 65:195104 同族
  口径）：(S11,S21) → Z=√[((1+S11)²−S21²)/((1−S11)²−S21²)]、
  P=S11+S21=(Γ+τ)/(1+Γτ) Möbius 反演 τ=(P−Γ)/(1−P·Γ)
  （Γ=(Z−1)/(Z+1)）、n=(−j·Ln(τ)+2π·branch_m)/(k0·d)（Ln=主枝对数，
  branch_m∈ℤ 显式支编号；d=面板厚度）、ε=n/Z、μ=n·Z。
  时间约定 e^{−jωt}（openEMS 同口径）：τ=e^{+jk0·n·d}，无耗 Im(n)=0、
  有耗 Im(n)>0（|τ|=e^{−k0·Im(n)·d}≤1）。无源守卫：|S11|²+|S21|²≤
  1+1e-9、|τ|≤1+1e-9、Im(n)<0 显式拒绝。诚实边界：分支自动判据/
  Kramers-Kronig 因果核=MM-5 显式不做（本面 branch_m 手动显式）；
  GSTC χ 面（mm-3）与平板 (n,Z) 面是两种参数化（薄板极限非正则），
  统一换算显式不做。

设计约束：core 层（math/cmath，零求解器零新依赖，标量面）；非法输入
显式 ValueError 不静默兜底；shell（calc_families）负责 JSON 化
（complex→[re,im]），本模块直接返回 complex（core 直调消费者口径）。
"""

from __future__ import annotations

import cmath
import math
from typing import Any

from rfauto.core.metasurface_lut import C0_M_S

__all__ = [
    "bruggeman_eff",
    "depolarization_factors",
    "looyenga_eff",
    "maxwell_garnett_eff",
    "mix_eff",
    "retrieve_eff_params",
    "slab_panel_rt",
    "srr_permeability",
    "wiener_bounds",
    "wire_media_plasma",
]

#: 规格 §C-2 同款无源守卫容差（GSTC 先例口径）
_ENERGY_TOL = 1e-9

_SHAPE_FACTORS: dict[str, tuple[float, float, float]] = {
    "sphere": (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
    "cube": (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0),
    "disk": (0.0, 0.0, 1.0),
    "rod": (0.0, 0.5, 0.5),
}


def _as_complex(value: Any, name: str) -> complex:
    """标量实数或 [re, im] 对 → complex（service JSON 复数约定，gstc 同款）。"""
    if isinstance(value, complex):
        if not (math.isfinite(value.real) and math.isfinite(value.imag)):
            raise ValueError(f"{name} 含非有限值（NaN/Inf）")
        return value
    if isinstance(value, bool):
        raise ValueError(f"{name} 须为实数或 [re, im] 对，收到 bool")
    if isinstance(value, (int, float)):
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"{name} 含非有限值（NaN/Inf）")
        return complex(v, 0.0)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            re, im = float(value[0]), float(value[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 须为实数或 [re, im] 对，收到 {value!r}") from exc
        if not (math.isfinite(re) and math.isfinite(im)):
            raise ValueError(f"{name} 含非有限值（NaN/Inf）")
        return complex(re, im)
    raise ValueError(f"{name} 须为实数或 [re, im] 对，收到 {value!r}")


def _as_passive_eps(value: Any, name: str) -> complex:
    """无耗/有耗介质 ε 入参收敛：Re>0 且 Im≥0（e^{−jωt} 口径，Im<0=增益）。"""
    eps = _as_complex(value, name)
    if eps.real <= 0.0:
        raise ValueError(
            f"{name} 须 Re>0（介质极化正定性），实际 Re={eps.real}")
    if eps.imag < 0.0:
        raise ValueError(
            f"{name} Im<0 即增益介质（e^{{-jωt}} 口径无源性要求 Im≥0），"
            f"实际 Im={eps.imag}")
    return eps


def _as_fraction(value: Any, name: str) -> float:
    """体积分数入参收敛 ∈[0,1]（端点合法，混合式端点恒等分支直返）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 须为 [0,1] 实数，收到 bool")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 须为 [0,1] 实数，收到 {value!r}") from exc
    if not math.isfinite(v) or not 0.0 <= v <= 1.0:
        raise ValueError(f"{name} 须 ∈ [0,1]，实际 {v}")
    return v


def _as_positive_float(value: Any, name: str) -> float:
    """正有限实数入参收敛。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 须为正有限实数，收到 bool")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 须为正有限实数，收到 {value!r}") from exc
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 须为正有限实数，收到 {value!r}")
    return v


# ─── 形状族：depolarization 因子闭式 ─────────────────────────────────────────


def depolarization_factors(shape: str) -> tuple[float, float, float]:
    """椭球极限形状的 depolarization 因子 (Lx, Ly, Lz) 闭式。

    sphere/cube=(1/3,1/3,1/3)（立方对称等分）、disk=(0,0,1)（无穷薄片，
    z=法向）、rod=(0,1/2,1/2)（无穷细棒，z=轴向）。ΣL=1 恒等式恒成立。
    """
    if not isinstance(shape, str) or shape not in _SHAPE_FACTORS:
        raise ValueError(
            f"shape={shape!r} 非法：支持 {'/'.join(sorted(_SHAPE_FACTORS))}")
    return _SHAPE_FACTORS[shape]


def _depol_scalar(depol: Any) -> float:
    """depolarization 因子标量收敛 ∈[0,1]（0=沿场细棒极限，仅 MG 通道定义）。"""
    if isinstance(depol, bool):
        raise ValueError("depol 须为 [0,1] 实数（depolarization 因子）")
    try:
        dep_l = float(depol)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"depol 须为 [0,1] 实数，收到 {depol!r}") from exc
    if not math.isfinite(dep_l) or not 0.0 <= dep_l <= 1.0:
        raise ValueError(f"depol 须 ∈ [0,1]（depolarization 因子），实际 {dep_l}")
    return dep_l


# ─── Wiener 界 ────────────────────────────────────────────────────────────────


def wiener_bounds(er_matrix: Any, er_inclusion: Any,
                  v_inclusion: Any) -> dict[str, complex]:
    """Wiener 资格界：算术（并联/上界）与调和（串联/下界）平均。

    实数正输入下一切各向同性混合式的 ε_eff 必落 [lower, upper] 内；
    复数输入界不有序（原样返回代数量，in_bounds 判读归调用方）。
    端点 v=0/1 逐位直返（退化物理恒等分支）。
    """
    em = _as_passive_eps(er_matrix, "er_matrix")
    ei = _as_passive_eps(er_inclusion, "er_inclusion")
    v = _as_fraction(v_inclusion, "v_inclusion")
    if v == 0.0:
        return {"upper_arithmetic": em, "lower_harmonic": em}
    if v == 1.0:
        return {"upper_arithmetic": ei, "lower_harmonic": ei}
    upper = (1.0 - v) * em + v * ei
    lower = 1.0 / ((1.0 - v) / em + v / ei)
    return {"upper_arithmetic": upper, "lower_harmonic": lower}


# ─── 三混合式通用核 ───────────────────────────────────────────────────────────


def maxwell_garnett_eff(er_matrix: Any, er_inclusion: Any,
                        v_inclusion: Any, depol: Any = 1.0 / 3.0) -> complex:
    """Maxwell-Garnett 椭球夹杂广义（基质 ε_m 相）。

    ε_eff = ε_m + ε_m·v(ε_i−ε_m)/(ε_m + L(1−v)(ε_i−ε_m))；L=1/3 逐式
    退化 humidity_drift.maxwell_garnett_mix 球形闭式；L=0（沿场细棒）
    =Wiener 上界线性并联、L=1（法向薄片）=Wiener 下界调和串联。端点
    v=0/1 逐位直返。
    """
    em = _as_passive_eps(er_matrix, "er_matrix")
    ei = _as_passive_eps(er_inclusion, "er_inclusion")
    v = _as_fraction(v_inclusion, "v_inclusion")
    dep_l = _depol_scalar(depol)
    if v == 0.0:
        return em
    if v == 1.0:
        return ei
    delta = ei - em
    return em + em * v * delta / (em + dep_l * (1.0 - v) * delta)


def bruggeman_eff(er_phase_a: Any, er_phase_b: Any, v_phase_a: Any,
                  depol: Any = 1.0 / 3.0) -> complex:
    """Bruggeman 对称有效介质（两相同形状 L）二次闭式。

    v(ε_a−ε)/(ε_a+Aε) + (1−v)(ε_b−ε)/(ε_b+Aε) = 0（A=(1−L)/L）→
    A·ε²+c·ε−ε_a·ε_b=0。物理根=距线性混合最近者（v→0 连续性；实数正
    输入下即 Re>0 根）。L=1/3 退化 humidity_drift.bruggeman_mix 闭式
    （c→−c'、4A=8、2A=4 逐式对应）；端点 v=0/1 逐位直返；L=0 方程
    退化显式拒绝。
    """
    ea = _as_passive_eps(er_phase_a, "er_phase_a")
    eb = _as_passive_eps(er_phase_b, "er_phase_b")
    v = _as_fraction(v_phase_a, "v_phase_a")
    dep_l = _depol_scalar(depol)
    if dep_l <= 0.0:
        raise ValueError(
            "bruggeman 通道要求 depol∈(0,1]：L=0 时两相极化均无退极化项，"
            "对称方程退化（沿场细棒极限请走 maxwell_garnett L=0 通道）")
    if v == 0.0:
        return eb
    if v == 1.0:
        return ea
    a_coef = (1.0 - dep_l) / dep_l
    c_coef = (v * eb + (1.0 - v) * ea) - a_coef * (v * ea + (1.0 - v) * eb)
    blend = v * ea + (1.0 - v) * eb
    disc = cmath.sqrt(c_coef * c_coef + 4.0 * a_coef * ea * eb)
    root1 = (-c_coef + disc) / (2.0 * a_coef)
    root2 = (-c_coef - disc) / (2.0 * a_coef)
    return root1 if abs(root1 - blend) <= abs(root2 - blend) else root2


def looyenga_eff(er_matrix: Any, er_inclusion: Any,
                 v_inclusion: Any) -> complex:
    """Looyenga 立方根混合：ε_eff = [(1−v)·ε_m^{1/3}+v·ε_i^{1/3}]³。

    复数取主枝立方根（Re>0、Im≥0 输入下连续）；实数正输入与
    humidity_drift.looyenga_mix 逐式一致。端点 v=0/1 逐位直返。
    """
    em = _as_passive_eps(er_matrix, "er_matrix")
    ei = _as_passive_eps(er_inclusion, "er_inclusion")
    v = _as_fraction(v_inclusion, "v_inclusion")
    if v == 0.0:
        return em
    if v == 1.0:
        return ei
    return ((1.0 - v) * em ** (1.0 / 3.0) + v * ei ** (1.0 / 3.0)) ** 3


_MIX_RULES = ("maxwell_garnett", "bruggeman", "looyenga")


def mix_eff(rule: str, er_matrix: Any, er_inclusion: Any, v_inclusion: Any,
            depol: Any = 1.0 / 3.0) -> dict[str, Any]:
    """三混合式统一面：rule ∈ {maxwell_garnett, bruggeman, looyenga}。

    返回 eps_eff + Wiener 双界；in_bounds 只在全部输入实数（Im=0）时
    判读（复数界不有序，如实 None 不凑判）。bruggeman 的 (matrix,
    inclusion, v) 语义映射为 (phase_a=ε_i, phase_b=ε_m, v_phase_a=v)
    ——v 恒指夹杂（同 humidity_drift 统一语义换序先例）。
    """
    if rule not in _MIX_RULES:
        raise ValueError(f"rule={rule!r} 非法：支持 {'/'.join(_MIX_RULES)}")
    em = _as_passive_eps(er_matrix, "er_matrix")
    ei = _as_passive_eps(er_inclusion, "er_inclusion")
    v = _as_fraction(v_inclusion, "v_inclusion")
    if rule == "maxwell_garnett":
        eff = maxwell_garnett_eff(em, ei, v, depol)
    elif rule == "bruggeman":
        eff = bruggeman_eff(ei, em, v, depol)
    else:
        eff = looyenga_eff(em, ei, v)
    bounds = wiener_bounds(em, ei, v)
    lo, hi = bounds["lower_harmonic"], bounds["upper_arithmetic"]
    all_real = (em.imag == 0.0 and ei.imag == 0.0
                and eff.imag == 0.0 and lo.imag == 0.0 and hi.imag == 0.0)
    in_bounds: bool | None = (
        lo.real - 1e-12 * max(1.0, abs(lo.real)) <= eff.real
        <= hi.real + 1e-12 * max(1.0, abs(hi.real))
    ) if all_real else None
    return {
        "eps_eff": eff,
        "rule": rule,
        "depol": _depol_scalar(depol),
        "wiener_lower": lo,
        "wiener_upper": hi,
        "in_wiener_bounds": in_bounds,
    }


# ─── Pendry 1999 SRR 磁导率（Lorentz 形）─────────────────────────────────────


def srr_permeability(freq_ghz: Any, f_res_ghz: Any,
                     fill_factor: Any = None, f_mp_ghz: Any = None,
                     gamma_ghz: Any = 0.0) -> dict[str, Any]:
    """Pendry 1999 SRR 阵列等效磁导率 Lorentz 形。

    μ(ω)=1−F·ω²/(ω²−ω0²+iΓω)。F 与 f_mp（磁等离子频率）二选一入参
    （都给/都不给显式拒绝；f_mp>f_res，F=1−(f_res/f_mp)²）。解析锚：
    μ(0)=1、μ(∞)=1−F、无损 μ(f_mp)=0、Re μ<0 带=(f_res, f_mp)、
    Γ>0 全带 Im μ>0（无源性）。无损谐振点（分母零）显式拒绝。
    """
    f = _as_positive_float(freq_ghz, "freq_ghz")
    f0 = _as_positive_float(f_res_ghz, "f_res_ghz")
    gamma = 0.0
    if gamma_ghz is not None:
        if isinstance(gamma_ghz, bool):
            raise ValueError("gamma_ghz 须为非负有限实数")
        gamma = float(gamma_ghz)
        if not math.isfinite(gamma) or gamma < 0.0:
            raise ValueError(f"gamma_ghz 须 ≥0，实际 {gamma_ghz!r}")
    if fill_factor is None and f_mp_ghz is None:
        raise ValueError("fill_factor 与 f_mp_ghz 至少给一个（二选一）")
    if fill_factor is not None and f_mp_ghz is not None:
        raise ValueError("fill_factor 与 f_mp_ghz 二选一，不可同时给")
    if fill_factor is not None:
        if isinstance(fill_factor, bool):
            raise ValueError("fill_factor 须为 (0,1) 实数")
        ffill = float(fill_factor)
        if not math.isfinite(ffill) or not 0.0 < ffill < 1.0:
            raise ValueError(
                f"fill_factor 须 ∈ (0,1)，实际 {fill_factor!r}")
        f_mp = f0 / math.sqrt(1.0 - ffill)
    else:
        f_mp = _as_positive_float(f_mp_ghz, "f_mp_ghz")
        if f_mp <= f0:
            raise ValueError(
                f"f_mp_ghz 须 > f_res_ghz（f_mp=f_res/√(1−F)>f_res），"
                f"实际 f_mp={f_mp} ≤ f_res={f0}")
        ffill = 1.0 - (f0 / f_mp) ** 2
    omega = 2.0 * math.pi * f * 1e9
    omega0 = 2.0 * math.pi * f0 * 1e9
    gamma_rad = 2.0 * math.pi * gamma * 1e9
    den = omega * omega - omega0 * omega0 + 1j * gamma_rad * omega
    if den == 0:
        raise ValueError(
            "无损谐振点 μ 极点（ω=ω0 且 Γ=0）无有限值，显式拒绝")
    mu = 1.0 - ffill * omega * omega / den
    return {
        "mu": mu,
        "mu_prime": mu.real,
        "mu_double_prime": mu.imag,
        "fill_factor": ffill,
        "f_res_ghz": f0,
        "f_mp_ghz": f_mp,
        "gamma_ghz": gamma,
        "negative_mu": bool(mu.real < 0.0),
    }


# ─── Pendry 1996 线媒质等离子频率 ────────────────────────────────────────────


def wire_media_plasma(lattice_mm: Any, wire_radius_mm: Any,
                      freq_ghz: Any = None,
                      nu_rad_s: Any = 0.0) -> dict[str, Any]:
    """Pendry 1996 线媒质等离子频率 ωp²=2π·c0²/(a²·ln(a/r)) + Drude ε(ω)。

    a=晶格常数、r=线半径（a/r>1）；ε(ω)=1−ωp²/(ω(ω+jν))（e^{−jωt}：
    ν>0 → Im ε>0；ν=0、ω<ωp → Re ε<0；ω=ωp 精确零点）。freq_ghz 给出
    时附 ε 报告；nu_rad_s=碰撞频率（缺省无损）。
    """
    a_m = _as_positive_float(lattice_mm, "lattice_mm") * 1e-3
    r_m = _as_positive_float(wire_radius_mm, "wire_radius_mm") * 1e-3
    if r_m >= a_m:
        raise ValueError(
            f"wire_radius_mm 须 < lattice_mm（a/r>1 才有 ln(a/r)>0），"
            f"实际 r={r_m * 1e3} ≥ a={a_m * 1e3}")
    ln_ratio = math.log(a_m / r_m)
    if ln_ratio < 0.693:  # a/r<2：ln 项病态（近邻线接触），显式拒绝
        raise ValueError(
            f"a/r={a_m / r_m:.6g} < 2：ln(a/r)<ln2 稀疏口径失效，显式拒绝")
    omega_p_sq = 2.0 * math.pi * C0_M_S * C0_M_S / (a_m * a_m * ln_ratio)
    omega_p = math.sqrt(omega_p_sq)
    nu = 0.0
    if nu_rad_s is not None:
        if isinstance(nu_rad_s, bool):
            raise ValueError("nu_rad_s 须为非负有限实数")
        nu = float(nu_rad_s)
        if not math.isfinite(nu) or nu < 0.0:
            raise ValueError(f"nu_rad_s 须 ≥0，实际 {nu_rad_s!r}")
    out: dict[str, Any] = {
        "omega_p_rad_s": omega_p,
        "f_p_ghz": omega_p / (2.0 * math.pi) / 1e9,
        "ln_a_over_r": ln_ratio,
        "nu_rad_s": nu,
    }
    if freq_ghz is not None:
        omega = 2.0 * math.pi * _as_positive_float(freq_ghz, "freq_ghz") * 1e9
        den = omega * (omega + 1j * nu)
        if den == 0:
            raise ValueError("ν=0 且 f=0 的 dc 点 Drude 分母零，显式拒绝")
        eps = 1.0 - omega_p_sq / den
        out["eps"] = eps
        out["eps_prime"] = eps.real
        out["eps_double_prime"] = eps.imag
        out["negative_eps"] = bool(eps.real < 0.0)
    return out


# ─── 等效参数反演（对称面板 Smith 2002 同族）────────────────────────────────


def slab_panel_rt(freq_ghz: Any, n_eff: Any, z_eff: Any,
                  thickness_mm: Any) -> dict[str, complex]:
    """法向入射对称平板 (n,Z,d) → (S11, S21) 正向闭式（反演对偶面）。

    Γ=(Z−1)/(Z+1)、τ=e^{+jk0·n·d}（e^{−jωt} 口径）、
    S11=Γ(1−τ²)/(1−Γ²τ²)、S21=τ(1−Γ²)/(1−Γ²τ²)。无耗面板满足
    |S11|²+|S21|²=1 代数恒等。core 直调纯函数（不注册，反演对拍用）。
    """
    f = _as_positive_float(freq_ghz, "freq_ghz")
    n = _as_complex(n_eff, "n_eff")
    z = _as_complex(z_eff, "z_eff")
    if abs(z + 1.0) == 0.0:
        raise ValueError("z_eff=-1 的 Γ 极点显式拒绝")
    d_m = _as_positive_float(thickness_mm, "thickness_mm") * 1e-3
    k0 = 2.0 * math.pi * f * 1e9 / C0_M_S
    gamma = (z - 1.0) / (z + 1.0)
    tau = cmath.exp(1j * k0 * n * d_m)
    den = 1.0 - gamma * gamma * tau * tau
    if den == 0:
        raise ValueError("面板 Fabry-Pérot 分母零（Γτ=±1）显式拒绝")
    s11 = gamma * (1.0 - tau * tau) / den
    s21 = tau * (1.0 - gamma * gamma) / den
    return {"s11": s11, "s21": s21, "k0_rad_m": complex(k0, 0.0)}


def retrieve_eff_params(freq_ghz: Any, s11: Any, s21: Any,
                        thickness_mm: Any,
                        branch_m: Any = 0) -> dict[str, Any]:
    """单频 (S11,S21) → (ε, μ, n, Z) 等效参数反演（对称面板）。

    Z=√[((1+S11)²−S21²)/((1−S11)²−S21²)]（主枝 √，Re(Z)<0 防御翻号）、
    Γ=(Z−1)/(Z+1)、τ=(P−Γ)/(1−P·Γ)（P=S11+S21）、
    n=(−j·Ln(τ)+2π·branch_m)/(k0·d)、ε=n/Z、μ=n·Z。
    无源守卫：能量 |S11|²+|S21|²≤1+1e-9、|τ|≤1+1e-9、Im(n)<−1e-9
    显式拒绝（branch 与无源性矛盾）。branch_m∈ℤ 显式支编号（厚面板
    相位回绕；相邻支差 2π/(k0·d) 恒等式可自检）；分支自动判据=MM-5
    显式不做。
    """
    f = _as_positive_float(freq_ghz, "freq_ghz")
    s11c = _as_complex(s11, "s11")
    s21c = _as_complex(s21, "s21")
    if isinstance(branch_m, bool) or not isinstance(branch_m, int):
        raise ValueError(f"branch_m 须为整数，收到 {branch_m!r}")
    d_m = _as_positive_float(thickness_mm, "thickness_mm") * 1e-3
    energy = abs(s11c) ** 2 + abs(s21c) ** 2
    if energy > 1.0 + _ENERGY_TOL:
        raise ValueError(
            f"|S11|²+|S21|²={energy:.6g} > 1：放大面板非无源，显式拒绝")
    k0 = 2.0 * math.pi * f * 1e9 / C0_M_S
    num = (1.0 + s11c) ** 2 - s21c ** 2
    den = (1.0 - s11c) ** 2 - s21c ** 2
    if den == 0:
        raise ValueError(
            "对称面板阻抗分母 (1−S11)²−S21²=0（Z→∞ 退化域），显式拒绝")
    z = cmath.sqrt(num / den)
    if z.real < 0.0:
        z = -z
    if abs(z + 1.0) == 0.0:
        raise ValueError("z=-1 的 Γ 极点显式拒绝")
    gamma = (z - 1.0) / (z + 1.0)
    panel = s11c + s21c
    den2 = 1.0 - panel * gamma
    if den2 == 0:
        raise ValueError(
            "Möbius 反演分母 1−P·Γ=0（(Γ,τ) 不可分辨退化域），显式拒绝")
    tau = (panel - gamma) / den2
    if tau == 0:
        raise ValueError("τ=0（全阻带）对数无定义，显式拒绝")
    if abs(tau) > 1.0 + _ENERGY_TOL:
        raise ValueError(
            f"|τ|={abs(tau):.6g} > 1：面板增益（Im(n)<0），显式拒绝")
    n_eff = (-1j * cmath.log(tau) + 2.0 * math.pi * branch_m) / (k0 * d_m)
    if n_eff.imag < -1e-9:
        raise ValueError(
            f"Im(n)={n_eff.imag:.6g} < 0 与无源性矛盾（branch/数据不一致），"
            "显式拒绝")
    return {
        "eps_eff": n_eff / z,
        "mu_eff": n_eff * z,
        "n_eff": n_eff,
        "z_eff": z,
        "k0_rad_m": k0,
        "thickness_m": d_m,
        "branch_m": branch_m,
        "energy": energy,
        "tau": tau,
        "gamma_interface": gamma,
    }
