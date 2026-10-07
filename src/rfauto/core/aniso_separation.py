"""MA-6 各向异性 εr 张量主轴分离闭式（ge8d 席 D1；round17 §MA-6 简版）。

规格：研究扩充 round17 :188（"各向异性 z/y 分离
（P3）：stripline（Z 向）vs 微带（混合）联合反演——与 Design Dk 锚直接衔
接"）+ 任务书席 D1（"εr 张量主轴分离闭式（单调介质板测量口径的解析面
简版——**登记级边界如实**）"）。

物理口径与严格性声明（登记级边界，预声明）
------------------------------------------
对象=叠层板单向（uniaxial）各向异性：主轴 ε_z（厚度向）与 ε_xy（面内，
横观各向同性退化）。三条**教科书严格**闭式 + 一条**声明式近似**：

1. **平行板电容感 ε_z**（严格）：极板法向沿 z 的电容 C=ε0·ε_z·A/t——
   单向介质中 D=ε_z·E_z 精确（场纯 z 向），无近似。
2. **全嵌入对称带线感 ε_xy**（结构严格+边界声明）：对称全嵌入带线 TEM
   主模场横向（xy 面内），ε_eff=ε_xy（边缘场/色散忽略——边界声明）。
3. **Wiener 界**（严格定理）：任意场分布下混合有效介电常数
   ε_eff ∈ [调和界, 算术界]，p_z 为 z 向场能量分数：
   调和（串联）1/ε_eff = p_z/ε_z + (1−p_z)/ε_xy；
   算术（并联）ε_eff = p_z·ε_z + (1−p_z)·ε_xy。
4. **微带联合反演（声明式近似——登记级）**：准 TEM 微带场跨厚度为主，
   取串联（调和）混合模型 + 调用方声明 p_z（**无发明缺省**）：
   1/ε_eff ≈ p_z/ε_z + (1−p_z)/ε_xy ⟹
   ε_xy = (1−p_z)/(1/ε_eff − p_z/ε_z)（闭式反解）。
   该近似的地位如实：p_z 无法从单条微带测量自洽解出（欠定），联合
   反演的 p_z 依赖声明或仿真标定——**登记为边界**，不是裁决级反演。

裁判面（#118：合成回收 + 独立路径，不自证）
------------------------------------------
- 各向同性退化恒等：ε_z=ε_xy → 全函数面坍缩到同一值（构造恒等）；
- Wiener 界排序：调和 ≤ 几何 ≤ 算术（p_z∈(0,1) 时严格）；
- 平行板合成回收：已知 ε_z/A/t → C 正算 → 反演回收 ε_z（≤1e-12）；
- 反解 round-trip：series_mix→separate 逐位回代；
- 单调性：ε_xy↑ → ε_eff↑（两混合模型 + 反解）。

复用与边界
----------
消费 core/synthesis.forward_z0（HJ 微带正模型，禁改）提供"各向同性
等效 Design-Dk"锚（inverse εeff——隔离面，与闭式反解独立）；不修改
material_library/design-dk 面。**不做**：波导/谐振法各向异性提取、
边缘场修正、色散——UNVERIFIED 清单登记（round17 原条目为 P3 登记
级，真机提取归 MA-1..5 表征链）。

接口：纯函数零 IO 零外部进程；JSON 可序列化；不进 @register_calculator、
不定义 __all__（PK-1/PK-7 先例）。
"""

from __future__ import annotations

import math
from typing import Any

#: 真空介电常数（F/m；CODATA 2018 推荐值）
EPS0_F_PER_M = 8.8541878128e-12


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，收到 {value!r}")
    return out


def _eps_rel(value: Any, name: str) -> float:
    out = _positive(value, name)
    if out < 1.0:
        raise ValueError(f"{name} 必须为相对介电常数（>=1），收到 {value!r}")
    return out


# ─── 感测面（严格闭式）───────────────────────────────────────────────────────


def parallel_plate_eps_z(capacitance_f: float, area_m2: float,
                         thickness_m: float) -> float:
    """平行板电容反演 ε_z（厚度向主轴；严格式 ε_z = C·t/(ε0·A)）。

    合成回收锚：ε_z=4.0、A=1e-4 m²、t=100 µm → C=3.5417e-12 F 回收
    4.0（≤1e-12 相对，单测钉）。
    """
    c = _positive(capacitance_f, "capacitance_f")
    area = _positive(area_m2, "area_m2")
    t = _positive(thickness_m, "thickness_m")
    return c * t / (EPS0_F_PER_M * area)


def parallel_plate_capacitance_f(eps_z: float, area_m2: float,
                                 thickness_m: float) -> float:
    """平行板正算（反演的构造对偶）：C = ε0·ε_z·A/t。"""
    ez = _eps_rel(eps_z, "eps_z")
    area = _positive(area_m2, "area_m2")
    t = _positive(thickness_m, "thickness_m")
    return EPS0_F_PER_M * ez * area / t


def stripline_eps_xy_from_eff(eps_eff_stripline: float) -> float:
    """全嵌入对称带线 ε_eff → ε_xy（结构严格：TEM 主模场横向；边缘场
    忽略为声明边界）。恒等式实现——感测映射本身是定义。"""
    return _eps_rel(eps_eff_stripline, "eps_eff_stripline")


# ─── Wiener 界与混合模型 ─────────────────────────────────────────────────────


def series_mix_eps_eff(eps_z: float, eps_xy: float, p_z: float) -> float:
    """串联（调和）混合：1/ε_eff = p_z/ε_z + (1−p_z)/ε_xy（Wiener 下界）。"""
    ez = _eps_rel(eps_z, "eps_z")
    exy = _eps_rel(eps_xy, "eps_xy")
    p = _mix_fraction(p_z)
    return 1.0 / (p / ez + (1.0 - p) / exy)


def parallel_mix_eps_eff(eps_z: float, eps_xy: float, p_z: float) -> float:
    """并联（算术）混合：ε_eff = p_z·ε_z + (1−p_z)·ε_xy（Wiener 上界）。"""
    ez = _eps_rel(eps_z, "eps_z")
    exy = _eps_rel(eps_xy, "eps_xy")
    p = _mix_fraction(p_z)
    return p * ez + (1.0 - p) * exy


def _mix_fraction(p_z: float) -> float:
    p = _finite(p_z, "p_z")
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"场能量分数 p_z 必须在 [0,1]，收到 {p_z!r}")
    return p


def wiener_bounds(eps_z: float, eps_xy: float, p_z: float) -> dict[str, float]:
    """Wiener 界 [调和, 算术]（任意场分布下 ε_eff 的严格包络）。"""
    return {
        "harmonic_lower": series_mix_eps_eff(eps_z, eps_xy, p_z),
        "arithmetic_upper": parallel_mix_eps_eff(eps_z, eps_xy, p_z),
    }


# ─── 微带联合反演（声明式近似——登记级）──────────────────────────────────────


def separate_eps_xy_from_microstrip(eps_eff_meas: float, eps_z: float,
                                    p_z: float) -> dict[str, Any]:
    """微带 ε_eff 测量 + 已知 ε_z → 反解 ε_xy（串联混合闭式反演）。

    模型：1/ε_eff ≈ p_z/ε_z + (1−p_z)/ε_xy
    ⟹ ε_xy = (1−p_z)/(1/ε_eff − p_z/ε_z)。
    守卫：反解分母 ≤0（p_z/ε_z ≥ 1/ε_eff）→ 模型域外 ValueError；
    ε_xy<1 → 非物理 ValueError。
    边界（如实）：p_z 为调用方声明（欠定反演；仿真/标定供给），近似
    地位见模块 docstring 第 4 条。
    """
    eff = _eps_rel(eps_eff_meas, "eps_eff_meas")
    ez = _eps_rel(eps_z, "eps_z")
    p = _mix_fraction(p_z)
    denom = 1.0 / eff - p / ez
    if denom <= 0.0:
        raise ValueError(
            f"反解分母非正（1/ε_eff={1.0 / eff:.6g} ≤ p_z/ε_z="
            f"{p / ez:.6g}）——p_z 声明与测量不相容，模型域外")
    exy = (1.0 - p) / denom
    if exy < 1.0:
        raise ValueError(f"反解 ε_xy={exy:.6g} < 1 非物理——测量/声明不相容")
    return {
        "eps_xy": exy,
        "eps_z_input": ez,
        "eps_eff_meas": eff,
        "p_z": p,
        "model": "series_mix_declared",
        "anisotropy_ratio": exy / ez,
    }


def anisotropy_report(eps_z: float, eps_xy: float,
                      isotropy_tol: float = 0.02) -> dict[str, Any]:
    """各向异性报告：比、域、等向性判定（|ε_z−ε_xy|/mean ≤ tol）。"""
    ez = _eps_rel(eps_z, "eps_z")
    exy = _eps_rel(eps_xy, "eps_xy")
    tol = _finite(isotropy_tol, "isotropy_tol")
    if tol < 0.0:
        raise ValueError(f"isotropy_tol 必须非负，收到 {isotropy_tol!r}")
    ratio = exy / ez
    rel_dev = abs(ez - exy) / (0.5 * (ez + exy))
    return {
        "eps_z": ez,
        "eps_xy": exy,
        "ratio_xy_over_z": ratio,
        "rel_deviation_from_isotropic": rel_dev,
        "isotropic": bool(rel_dev <= tol),
        "isotropy_tol": tol,
        "higher_axis": "xy" if exy > ez else ("z" if ez > exy else None),
    }


def isotropic_equiv_from_microstrip(eps_eff_meas: float, w_mm: float,
                                    freq_ghz: float, h_mm: float,
                                    *,
                                    tan_d: float = 0.0) -> dict[str, Any]:
    """微带 ε_eff → 各向同性等效 Design-Dk 锚（消费 core/synthesis 正模型
    反解；scipy brentq 数值反演，与闭式反解路径独立）。

    该锚的含义如实：把测得 εeff 归因到**假想各向同性**板的 Dk——
    Design-Dk 口径（板材厂商惯例）；它 ≠ ε_xy（各向异性下两者分离，
    分离幅值用 separate_eps_xy_from_microstrip 评估）。
    """
    from scipy.optimize import brentq

    from rfauto.core.synthesis import Stackup, forward_z0

    eff = _eps_rel(eps_eff_meas, "eps_eff_meas")
    w = _positive(w_mm, "w_mm")
    freq = _positive(freq_ghz, "freq_ghz")
    h = _positive(h_mm, "h_mm")

    def objective(er: float) -> float:
        _, er_eff = forward_z0(
            w, freq,
            Stackup(name="aniso_sep", epsilon_r=er, thickness_mm=h,
                    loss_tangent=float(tan_d), rho=1.68e-8, rough_mm=0.0))
        return er_eff - eff

    lo, hi = max(1.0 + 1e-9, eff * 0.5), max(2.0, eff * 4.0)
    f_lo, f_hi = objective(lo), objective(hi)
    if f_lo > 0.0 or f_hi < 0.0:
        raise ValueError(
            f"ε_eff={eff} 超出 HJ 微带模型可达域 [{w}/{h} 几何]——括号失败")
    er_iso = brentq(objective, lo, hi, xtol=1e-10)
    return {
        "eps_iso_equiv_design_dk": er_iso,
        "eps_eff_target": eff,
        "note": ("isotropic-equivalent anchor; not equal to eps_xy under "
                 "anisotropy (separation via separate_eps_xy_from_microstrip)"),
    }
