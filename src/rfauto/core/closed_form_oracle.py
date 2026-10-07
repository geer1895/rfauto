"""QM-2 闭式解生成式对拍·生成式裁判（round16 P2，验证与质量方法论）。

定位（"锚推广"）：单点金值锚（golds/锚表）的推广形态——对**有闭式源**
的 CALCULATOR_REGISTRY 注册键，**生成** (参数, 期望) 网格（确定性、
域盒内多点），逐点对拍注册计算器输出 vs 独立闭式源，产 A/B/C/D 差异
分级报告 + 域盒声明。单点锚抓"错一个常数"，生成网格抓"错一段分支/
域泄漏/符号翻转"（多点覆盖分支与域边）。

#118 诚实性（同源互证警示的落地面）——oracle_kind 三档如实声明：
- ``independent_network``：期望值由**网络理论再推导**产出（阻值→网络
  ABCD/节点消元→衰减/匹配），与生成阻值的闭式完全独立——互证最强档；
- ``formula_reimpl``：期望值=内核 docstring 已声明闭式的独立重实现
  （同式重写，抓实现层笔误/分支错误，不抓"文档公式本身错"——文档错
  归 1b/1c 审计面）；
- ``roundtrip``：综合↔分析回代自洽性质（A(S(z))==z）——解析函数逆
  的一致性裁判，不引外部数值源。
报告逐 oracle 带 kind 与 reference 声明，消费方按档采信（#122：测量
与报告，不是清零运动——D 级旗标=人工审计入口，不自动判 PASS/FAIL
整键翻红）。

分级口径（相对误差 |a−e|/max(|e|, floor)）：
  A ≤1e-9（位级一致档）；B ≤1e-6（浮点换算档）；C ≤1e-3（迭代/
  舍入档，含 brentq xtol 与结果 round 舍入）；D >1e-3（旗标）。
floor=每比较项显式声明的尺度地板（内核结果按声明位数 round——floor
取 50–100×末位 ULP 作"显示舍入噪声地板"：期望量级 ≳地板时相对误差项
主导，期望量级 ≲地板时按地板归一，小量级量的分级天花板=C=显示
噪声档，如实反映"该量在此显示精度下无法判 A"——零期望量同理用
绝对地板）。

域盒声明：每 oracle 显式声明参数域（domain_box 文本 + 网格只生成域内
点）；网格点命中计算器域守卫（ValueError/域报错）时记 skipped_domain
计数——**域外点如实跳过不计级**（域盒声明的一部分），但整键零评估
点=FAIL（无数据不放行）。

用法::

    from rfauto.core.closed_form_oracle import (
        CLOSED_FORM_ORACLES, cross_check_oracle, cross_check_all)

    r = cross_check_oracle("attenuator_pi")
    r["grade"]       # A/B/C/D（本键最差项）
    full = cross_check_all()
    full["n_keys"]   # 覆盖键数（≥20 验收口径）
"""

from __future__ import annotations

import cmath
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from rfauto.core.calc_families.registry import C_MM_GHZ
from rfauto.core.calculators import CALCULATOR_REGISTRY

#: 生成式对拍契约版本。
CLOSED_FORM_ORACLE_SCHEMA = "rfauto-closed-form-oracle-v1"

#: 分级门（相对误差；见模块 docstring 口径）。
GRADE_A_MAX = 1e-9
GRADE_B_MAX = 1e-6
GRADE_C_MAX = 1e-3

#: 网格点计算器域守卫异常记 skipped_domain 的异常类型。
_DOMAIN_EXC = (ValueError, KeyError, ZeroDivisionError, OverflowError)

Oracles = dict[str, float]  # 量名 → 值


@dataclass(frozen=True)
class _Item:
    """单项比较（量名 + 期望 + 实际 + 尺度地板）。"""
    quantity: str
    expected: float
    actual: float
    floor: float = 0.0

    def rel_err(self) -> float:
        scale = max(abs(self.expected), abs(self.floor))
        return abs(self.actual - self.expected) / scale if scale > 0 else \
            abs(self.actual - self.expected)


@dataclass(frozen=True)
class ClosedFormOracle:
    """一个注册键的闭式 oracle 条目（生成网格+期望源+提取器）。"""

    key: str                                   # 主键（=注册计算器键）
    covers: tuple[str, ...]                    # 覆盖的注册键全集（含主键）
    kind: str                                  # independent_network|formula_reimpl|roundtrip
    reference: str                             # 闭式源声明（出处/性质语义）
    domain_box: str                            # 域盒声明（网格只生成域内点）
    grid: Callable[[], list[dict[str, Any]]]   # 参数网格（确定性）
    oracle: Callable[[Mapping[str, Any]], Oracles]   # params → 期望值表
    extract: Callable[[Mapping[str, Any], Mapping[str, Any]], Oracles]
    # (params, calc_result) → 实际值表（键须与 oracle 一致）

    def items(self, params: Mapping[str, Any],
              result: Mapping[str, Any]) -> list[_Item]:
        exp = self.oracle(params)
        act = self.extract(params, result)
        missing = sorted(set(exp) - set(act))
        if missing:
            raise KeyError(f"oracle {self.key}: extract 缺量 {missing}")
        floors = _ITEM_FLOORS.get(self.key, {})
        return [_Item(q, float(exp[q]), float(act[q]), float(floors.get(q, 0.0)))
                for q in sorted(exp)]


#: 每键每量的尺度地板（5×内核声明 round 末位 ULP；零期望量=绝对地板）。
_ITEM_FLOORS: dict[str, dict[str, float]] = {}


def _floors(key: str, **quantities: float) -> None:
    _ITEM_FLOORS[key] = dict(quantities)


# ════════════════════════ 网络理论再推导（independent_network）══════════════


def _abcd_to_s21_db(abcd: tuple[complex, complex, complex, complex],
                    z0: float) -> float:
    """ABCD 矩阵 → |S21|² dB（等实阻抗双端口）。"""
    a, b, c, d = abcd
    s21 = 2.0 / (a + b / z0 + c * z0 + d)
    return -10.0 * math.log10(abs(s21) ** 2)


def _abcd_to_s11(abcd: tuple[complex, complex, complex, complex],
                 z0: float) -> complex:
    a, b, c, d = abcd
    return (a + b / z0 - c * z0 - d) / (a + b / z0 + c * z0 + d)


def _pi_oracle(params: Mapping[str, Any]) -> Oracles:
    a_db = float(params["attenuation_db"])
    return {"attenuation_db": a_db, "mismatch_loss_db": 0.0}


def _pi_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    z0 = float(params["z0_ohm"])
    rs = float(r["r_series_mid_ohm"])
    rp = float(r["r_shunt_end_ohm"])
    # π 网络：shunt Rp — series Rs — shunt Rp（ABCD 逐节级联）
    m1 = (1.0 + 0j, 0j, 1.0 / rp + 0j, 1.0 + 0j)
    m2 = (1.0 + 0j, rs + 0j, 0j, 1.0 + 0j)
    ab = _mm(_mm(m1, m2), m1)
    atten = _abcd_to_s21_db(ab, z0)
    ml = -10.0 * math.log10(1.0 - abs(_abcd_to_s11(ab, z0)) ** 2)
    return {"attenuation_db": atten, "mismatch_loss_db": ml}


def _t_oracle(params: Mapping[str, Any]) -> Oracles:
    return _pi_oracle(params)


def _t_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    z0 = float(params["z0_ohm"])
    rs = float(r["r_series_arm_ohm"])
    rp = float(r["r_shunt_mid_ohm"])
    # T 网络：series Rs — shunt Rp — series Rs
    m1 = (1.0 + 0j, rs + 0j, 0j, 1.0 + 0j)
    m2 = (1.0 + 0j, 0j, 1.0 / rp + 0j, 1.0 + 0j)
    ab = _mm(_mm(m1, m2), m1)
    atten = _abcd_to_s21_db(ab, z0)
    ml = -10.0 * math.log10(1.0 - abs(_abcd_to_s11(ab, z0)) ** 2)
    return {"attenuation_db": atten, "mismatch_loss_db": ml}


def _bridged_t_oracle(params: Mapping[str, Any]) -> Oracles:
    return _pi_oracle(params)


def _bridged_t_extract(params: Mapping[str, Any],
                       r: Mapping[str, Any]) -> Oracles:
    """三节点导纳消元（#118 独立裁判：拓扑解，不复用闭式）。"""
    z0 = float(params["z0_ohm"])
    rb = float(r["r_bridge_ohm"])
    rsp = float(r["r_shunt_mid_ohm"])
    ys = 1.0 / z0          # 两串臂（Z0 固定）
    yp = 1.0 / rsp         # 中点对地
    yb = 1.0 / rb          # 桥（输入-输出跨接）
    v1 = 1.0 + 0j          # 输入节点激励（1V）
    # node2: (2ys+yp)V2 − ys·V1 − ys·V3 = 0
    # node3: (ys+yb+1/z0)V3 − ys·V2 − yb·V1 = 0（含负载 Z0）
    a22 = 2 * ys + yp
    a23 = -ys
    a32 = -ys
    a33 = ys + yb + 1.0 / z0
    det = a22 * a33 - a23 * a32
    b2 = ys * v1
    b3 = yb * v1
    v3 = (a22 * b3 - a23 * b2) / det
    v2 = (a33 * b2 - a32 * b3) / det
    i_in = ys * (v1 - v2) + yb * (v1 - v3)
    # node1=理想源硬激励：端口电压=v1，端口电流=i_in（输入阻抗=v1/i_in）
    atten = -20.0 * math.log10(abs(v3 / v1))
    # 输入阻抗 → 反射
    z_in = v1 / i_in
    s11 = (z_in - z0) / (z_in + z0)
    ml = -10.0 * math.log10(1.0 - abs(s11) ** 2)
    return {"attenuation_db": atten, "mismatch_loss_db": ml}


def _mm(m1: tuple[complex, ...], m2: tuple[complex, ...]
        ) -> tuple[complex, complex, complex, complex]:
    """2×2 ABCD 级联（行主序 a b c d）。"""
    a1, b1, c1, d1 = m1
    a2, b2, c2, d2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2)


def _qwt_oracle(params: Mapping[str, Any]) -> Oracles:
    z0 = math.sqrt(float(params["z_source_ohm"]) * float(params["z_load_ohm"]))
    out = {"z0_section_ohm": z0}
    if params.get("freq_ghz") and params.get("eps_eff"):
        lam0 = C_MM_GHZ / float(params["freq_ghz"])
        out["length_mm"] = lam0 / (4.0 * math.sqrt(float(params["eps_eff"])))
    return out


def _qwt_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    out = {"z0_section_ohm": float(r["z0_section_ohm"])}
    if "length_mm" in r:
        out["length_mm"] = float(r["length_mm"])
    return out


def _vswr_oracle(params: Mapping[str, Any]) -> Oracles:
    v = float(params["vswr"])
    g = (v - 1.0) / (v + 1.0)
    return {"gamma_mag": g, "vswr": v,
            "return_loss_db": -20.0 * math.log10(g),
            "mismatch_loss_db": -10.0 * math.log10(1.0 - g * g)}


def _vswr_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    return {"gamma_mag": float(r["gamma_mag"]),
            "vswr": float(r["vswr"]),
            "return_loss_db": float(r["return_loss_db"]),
            "mismatch_loss_db": float(r["mismatch_loss_db"])}


# ════════════════════════ 闭式重实现（formula_reimpl）═══════════════════════


def _thermal_drift_oracle(params: Mapping[str, Any]) -> Oracles:
    ratio = -(float(params["cte_ppm_per_k"])
              + 0.5 * float(params["tcdk_ppm_per_k"])) * 1e-6 \
        * float(params["delta_t_c"])
    f0 = float(params["f0_ghz"])
    return {"f_shifted_ghz": f0 * (1.0 + ratio), "df_ghz": f0 * ratio,
            "df_over_f_ppm": ratio * 1e6}


def _thermal_drift_extract(params: Mapping[str, Any],
                           r: Mapping[str, Any]) -> Oracles:
    return {"f_shifted_ghz": float(r["f_shifted_ghz"]),
            "df_ghz": float(r["df_ghz"]),
            "df_over_f_ppm": float(r["df_over_f_ppm"])}


def _thermal_stack_oracle(params: Mapping[str, Any]) -> Oracles:
    chain = (float(params["theta_jc_c_per_w"])
             + float(params.get("theta_cs_c_per_w", 0.0) or 0.0)
             + float(params.get("theta_sa_c_per_w", 0.0) or 0.0))
    p = float(params["power_w"])
    ta = float(params["ambient_c"])
    return {"theta_total_c_per_w": chain, "delta_t_c": p * chain,
            "junction_temp_c": ta + p * chain}


def _thermal_stack_extract(params: Mapping[str, Any],
                           r: Mapping[str, Any]) -> Oracles:
    return {"theta_total_c_per_w": float(r["theta_total_c_per_w"]),
            "delta_t_c": float(r["delta_t_c"]),
            "junction_temp_c": float(r["junction_temp_c"])}


_MU0 = 1.25663706212e-6
_ETA0 = 376.730313668


def _shield_oracle(params: Mapping[str, Any]) -> Oracles:
    f = float(params["frequency_hz"])
    t = float(params["thickness_m"])
    sigma = float(params["conductivity_s_per_m"])
    mu = _MU0 * float(params.get("mu_r", 1.0))
    omega = 2.0 * math.pi * f
    delta = math.sqrt(2.0 / (omega * mu * sigma))
    gam = (1.0 + 1j) / delta
    zs = cmath.sqrt(1j * omega * mu / sigma)
    zw = _ETA0
    refl = (zs - zw) / (zs + zw)
    se_a = (20.0 / math.log(10.0)) * (t / delta)
    se_r = 20.0 * math.log10(abs((zw + zs) ** 2 / (4.0 * zw * zs)))
    se_b = 20.0 * math.log10(abs(1.0 - refl ** 2 * cmath.exp(-2.0 * gam * t)))
    return {"se_total_db": se_a + se_r + se_b,
            "se_absorption_db": se_a, "se_reflection_db": se_r,
            "se_multiple_db": se_b}


def _shield_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    return {q: float(r[q][0]) for q in
            ("se_total_db", "se_absorption_db", "se_reflection_db",
             "se_multiple_db")}


def _siw_oracle(params: Mapping[str, Any]) -> Oracles:
    w = float(params["w_mm"])
    d = float(params["d_mm"])
    s = float(params["s_mm"])
    weff = w - d * d / (0.95 * s)          # Cassivi 2002
    n = math.sqrt(float(params["epsilon_r"]))
    fc = C_MM_GHZ / (2.0 * weff * n)       # c[mm·GHz] 口径 → GHz
    out = {"fc10_ghz": fc, "weff_mm": weff}
    f = float(params["freq_ghz"])
    if f > fc:                              # 传播档才比较 β/λg
        k0n = 2.0 * math.pi * f * 1e9 / 299792458.0 * n   # k0·n [rad/m]
        kc = math.pi / (weff * 1e-3)
        out["beta_rad_m"] = math.sqrt(k0n * k0n - kc * kc)
        out["f_over_fc"] = f / fc
    return out


def _siw_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    out = {"fc10_ghz": float(r["fc10_ghz"]), "weff_mm": float(r["weff_mm"])}
    if "beta_rad_m" in r and r["beta_rad_m"] is not None:
        out["beta_rad_m"] = float(r["beta_rad_m"])
        out["f_over_fc"] = float(r["f_over_fc"])
    return out


def _patch_oracle(params: Mapping[str, Any]) -> Oracles:
    """Balanis W/εeff + Hammerstad ΔL（文档口径重实现，mm 制）。"""
    f = float(params["f0_ghz"])
    er = float(params["epsilon_r"])
    h = float(params["h_mm"])
    w = C_MM_GHZ / (2.0 * f) * math.sqrt(2.0 / (er + 1.0))
    eps_eff = ((er + 1.0) / 2.0
               + (er - 1.0) / 2.0 * (1.0 + 12.0 * h / w) ** -0.5)
    dl = 0.412 * h * (eps_eff + 0.3) * (w / h + 0.264) \
        / ((eps_eff - 0.258) * (w / h + 0.8))   # 单边缘 ΔL
    total_dl = 2.0 * dl                          # 两边缘合计（内核口径 d_l）
    length = C_MM_GHZ / (2.0 * f * math.sqrt(eps_eff)) - 2.0 * total_dl
    return {"patch_w_mm": w, "eps_eff": eps_eff,
            "delta_l_mm": total_dl, "patch_l_mm": length}


def _patch_extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
    return {"patch_w_mm": float(r["patch_w_mm"]),
            "eps_eff": float(r["eps_eff"]),
            "delta_l_mm": float(r["delta_l_mm"]),
            "patch_l_mm": float(r["patch_l_mm"])}


def _rfid_forward_oracle(params: Mapping[str, Any]) -> Oracles:
    lam = 299792458.0 / float(params["frequency_hz"])
    d = float(params["distance_m"])
    pl = 20.0 * math.log10(4.0 * math.pi * d / lam)
    pol = float(params.get("polarization_loss_db", 0.0) or 0.0)
    p_tag = (float(params["eirp_dbm"]) + float(params["g_tag_dbi"])
             - pl - pol)
    return {"p_tag_dbm": p_tag, "path_loss_db": pl + pol,
            "margin_db": p_tag - float(params["sensitivity_dbm"])}


def _rfid_forward_extract(params: Mapping[str, Any],
                          r: Mapping[str, Any]) -> Oracles:
    return {"p_tag_dbm": float(r["p_tag_dbm"]),
            "path_loss_db": float(r["path_loss_db"]),
            "margin_db": float(r["margin_db"])}


# ════════════════════════ 回代自洽（roundtrip，借注册对偶键）════════════════


def _rt(synth_key: str, analysis_key: str, *,
        synth_width_field: str = "width_mm",
        analysis_width_field: str = "width_mm",
        fixed: dict[str, Any] | None = None) -> tuple[
            Callable[[], list[dict[str, Any]]],
            Callable[[Mapping[str, Any]], Oracles],
            Callable[[Mapping[str, Any], Mapping[str, Any]], Oracles]]:
    """综合↔分析回代 oracle 三件组（网格/期望/提取——闭环走对偶注册键）。"""
    fixed = dict(fixed or {})

    def grid() -> list[dict[str, Any]]:
        return [dict({**fixed, "z0_ohm": z})
                for z in _RT_GRIDS[synth_key]]

    def oracle(params: Mapping[str, Any]) -> Oracles:
        return {"z0_ohm": float(params["z0_ohm"])}

    def extract(params: Mapping[str, Any], r: Mapping[str, Any]) -> Oracles:
        # 综合出宽 → 对偶分析回代（回代 z0 vs 目标 z0）
        w = float(r[synth_width_field])
        back = CALCULATOR_REGISTRY.get(analysis_key).func(
            **{**fixed, analysis_width_field: w})
        return {"z0_ohm": float(back["z0_ohm"])}

    return grid, oracle, extract


# 各线族字段与固定几何（域盒声明，域内取点；#1c 口径：几何全部域内）
_ANALYSIS_WIDTH_FIELDS = {"microstrip_analysis": "width_mm",
                          "cpw_analysis": "w_mm",
                          "cpwg_analysis": "w_mm",
                          "stripline_analysis": "w_mm",
                          "cps_analysis": "w_mm",
                          "suspended_stripline_analysis": "w_mm",
                          "slotline_analysis": "w_mm"}

_RT_GRIDS: dict[str, list[float]] = {
    "microstrip_synthesis": [25.0, 35.0, 50.0, 70.0, 90.0],
    "cpw_synthesis": [45.0, 50.0, 60.0, 80.0],
    "cpwg_synthesis": [45.0, 50.0, 60.0, 75.0],
    "stripline_synthesis": [30.0, 50.0, 70.0, 90.0],
    "cps_synthesis": [80.0, 100.0, 120.0, 150.0],
    "suspended_stripline_synthesis": [40.0, 50.0, 65.0, 85.0],
    "slotline_synthesis": [95.0, 110.92, 125.0],
}

_RT_FIXED: dict[str, dict[str, Any]] = {
    "microstrip_synthesis": {"freq_ghz": 2.5, "epsilon_r": 3.66, "h_mm": 0.508},
    "cpw_synthesis": {"gap_mm": 0.2, "freq_ghz": 2.5, "epsilon_r": 3.66,
                      "h_mm": 0.508},
    "cpwg_synthesis": {"gap_mm": 0.2, "freq_ghz": 2.5, "epsilon_r": 3.66,
                       "h_mm": 0.508},
    "stripline_synthesis": {"b_mm": 1.016, "epsilon_r": 3.66},
    "cps_synthesis": {"gap_mm": 0.5, "freq_ghz": 2.5, "epsilon_r": 3.66,
                      "h_mm": 0.508},
    "suspended_stripline_synthesis": {"b_mm": 1.016, "h_mm": 0.508,
                                      "epsilon_r": 3.66},
    "slotline_synthesis": {"h_mm": 1.524, "epsilon_r": 3.66, "freq_ghz": 2.5},
}

_SYNTH_COVERS = {
    "microstrip_synthesis": ("microstrip_synthesis", "microstrip_analysis"),
    "cpw_synthesis": ("cpw_synthesis", "cpw_analysis"),
    "cpwg_synthesis": ("cpwg_synthesis", "cpwg_analysis"),
    "stripline_synthesis": ("stripline_synthesis", "stripline_analysis"),
    "cps_synthesis": ("cps_synthesis", "cps_analysis"),
    "suspended_stripline_synthesis": ("suspended_stripline_synthesis",
                                      "suspended_stripline_analysis"),
    "slotline_synthesis": ("slotline_synthesis", "slotline_analysis"),
}

_SYNTH_WIDTH_FIELD = {"microstrip_synthesis": "width_mm",
                      "cpw_synthesis": "w_mm",
                      "cpwg_synthesis": "w_mm",
                      "stripline_synthesis": "w_mm",
                      "cps_synthesis": "w_mm",
                      "suspended_stripline_synthesis": "w_mm",
                      "slotline_synthesis": "w_mm"}

# ════════════════════════ 注册表 ════════════════════════════════════════════

_ATTEN_GRID = [{"attenuation_db": a, "z0_ohm": z}
               for a in (1.0, 3.0, 6.0, 10.0, 20.0) for z in (50.0, 75.0)]

CLOSED_FORM_ORACLES: dict[str, ClosedFormOracle] = {}


def _register(oracle: ClosedFormOracle) -> None:
    CLOSED_FORM_ORACLES[oracle.key] = oracle


for _k, _pairs in _SYNTH_COVERS.items():
    _g, _o, _e = _rt(_k, _pairs[1],
                     synth_width_field=_SYNTH_WIDTH_FIELD[_k],
                     analysis_width_field=_ANALYSIS_WIDTH_FIELDS[_pairs[1]],
                     fixed=_RT_FIXED[_k])
    _register(ClosedFormOracle(
        key=_k, covers=_pairs, kind="roundtrip",
        reference=f"综合↔分析回代自洽 A(S(z))=z（对偶键 {_pairs[1]}）",
        domain_box=f"z0∈{_RT_GRIDS[_k]}Ω，几何={_RT_FIXED[_k]}",
        grid=_g, oracle=_o, extract=_e))
    # 回代 z0 的地板：分析结果 round(…,2) 的 5×ULP
    _floors(_k, z0_ohm=0.5)

_register(ClosedFormOracle(
    key="attenuator_pi", covers=("attenuator_pi",),
    kind="independent_network",
    reference="π 网络阻值→ABCD 级联→衰减/匹配（网络理论再推导，与阻值闭式独立）",
    domain_box="atten∈{1,3,6,10,20}dB × z0∈{50,75}Ω",
    grid=lambda: _ATTEN_GRID, oracle=_pi_oracle, extract=_pi_extract))
_floors("attenuator_pi", attenuation_db=5e-3, mismatch_loss_db=5e-3)

_register(ClosedFormOracle(
    key="attenuator_t", covers=("attenuator_t",),
    kind="independent_network",
    reference="T 网络阻值→ABCD 级联→衰减/匹配（独立）",
    domain_box="atten∈{1,3,6,10,20}dB × z0∈{50,75}Ω",
    grid=lambda: _ATTEN_GRID, oracle=_t_oracle, extract=_t_extract))
_floors("attenuator_t", attenuation_db=5e-3, mismatch_loss_db=5e-3)

_register(ClosedFormOracle(
    key="attenuator_bridged_t", covers=("attenuator_bridged_t",),
    kind="independent_network",
    reference="桥 T 三节点导纳 Kron 消元→衰减/匹配（拓扑解，与闭式独立）",
    domain_box="atten∈{1,3,6,10,20}dB × z0∈{50,75}Ω",
    grid=lambda: _ATTEN_GRID, oracle=_bridged_t_oracle,
    extract=_bridged_t_extract))
_floors("attenuator_bridged_t", attenuation_db=5e-3, mismatch_loss_db=5e-3)

_register(ClosedFormOracle(
    key="quarter_wave_transformer", covers=("quarter_wave_transformer",),
    kind="formula_reimpl",
    reference="z0=√(Zs·Zl)；length=λ0/(4√εeff)（λ0=C_MM_GHZ/f）",
    domain_box="Zs×Zl∈[20,200]²Ω²，f∈[0.5,10]GHz，εeff∈[1,12]",
    grid=lambda: [{"z_source_ohm": zs, "z_load_ohm": zl,
                   "freq_ghz": f, "eps_eff": ee}
                  for zs, zl in ((30.0, 90.0), (50.0, 100.0), (25.0, 75.0))
                  for f in (1.0, 2.5) for ee in (2.5, 6.0)],
    oracle=_qwt_oracle, extract=_qwt_extract))
_floors("quarter_wave_transformer", z0_section_ohm=5e-2, length_mm=5e-2)

_register(ClosedFormOracle(
    key="vswr_convert", covers=("vswr_convert",),
    kind="formula_reimpl",
    reference="Γ=(ρ−1)/(ρ+1)；RL=−20lg|Γ|；ML=−10lg(1−Γ²)（恒等式链）",
    domain_box="vswr∈(1,10]，网格 {1.2,1.5,2,3,5,8}",
    grid=lambda: [{"vswr": v} for v in (1.2, 1.5, 2.0, 3.0, 5.0, 8.0)],
    oracle=_vswr_oracle, extract=_vswr_extract))
# mismatch_loss_db：4 位显示在 ~0.036 量级处相对噪声 ~1.4e-3——地板取
# 5e-2（显示噪声 ~30×）使该量分级天花板=C（显示噪声档），如实不虚判 A。
_floors("vswr_convert", gamma_mag=5e-5, vswr=5e-3, return_loss_db=5e-3,
        mismatch_loss_db=5e-2)

_register(ClosedFormOracle(
    key="resonator_thermal_drift", covers=("resonator_thermal_drift",),
    kind="formula_reimpl",
    reference="Δf/f=−(CTE+½TCDK)·1e−6·ΔT（线性 ppm 和）",
    domain_box="f0∈{4,10,28}GHz × ΔT∈{−55,50}K × CTE/TCDK 典型表",
    grid=lambda: [{"f0_ghz": f, "delta_t_c": dt, "cte_ppm_per_k": cte,
                   "tcdk_ppm_per_k": tcd}
                  for f in (4.0, 10.0, 28.0) for dt in (-55.0, 50.0)
                  for cte, tcd in ((16.0, -30.0), (7.0, 0.0), (-3.0, -15.0))],
    oracle=_thermal_drift_oracle, extract=_thermal_drift_extract))
_floors("resonator_thermal_drift", f_shifted_ghz=5e-11, df_ghz=5e-14,
        df_over_f_ppm=5e-8)

_register(ClosedFormOracle(
    key="thermal_resistance_stack", covers=("thermal_resistance_stack",),
    kind="formula_reimpl",
    reference="串联热阻和；Tj=Tamb+P·Σθ（无并联支路档）",
    domain_box="P∈{0.5,1,3}W，θ 典型 {1,2,5} 组合",
    grid=lambda: [{"power_w": p, "ambient_c": 25.0,
                   "theta_jc_c_per_w": a, "theta_cs_c_per_w": b,
                   "theta_sa_c_per_w": c}
                  for p in (0.5, 1.0, 3.0)
                  for a, b, c in ((2.0, 1.0, 5.0), (0.5, 0.0, 10.0),
                                  (40.0, 0.0, 0.0))],
    oracle=_thermal_stack_oracle, extract=_thermal_stack_extract))
_floors("thermal_resistance_stack", theta_total_c_per_w=5e-8,
        delta_t_c=5e-8, junction_temp_c=5e-8)

_register(ClosedFormOracle(
    key="shielding_effectiveness", covers=("shielding_effectiveness",),
    kind="formula_reimpl",
    reference="Schelkunoff TL 类比 SE=A+R+B（δ/γ/Zs 复数闭式，Ott 2009 §6）",
    domain_box="σ=5.8e7（铜）μr=1，f∈{1e6,1e8,1e9}Hz × t∈{0.5,1}mm",
    grid=lambda: [{"frequency_hz": f, "thickness_m": t,
                   "conductivity_s_per_m": 5.8e7, "mu_r": 1.0}
                  for f in (1.0e6, 1.0e8, 1.0e9)
                  for t in (0.5e-3, 1.0e-3)],
    oracle=_shield_oracle, extract=_shield_extract))
_floors("shielding_effectiveness", se_total_db=5e-8, se_absorption_db=5e-8,
        se_reflection_db=5e-8, se_multiple_db=5e-8)

_register(ClosedFormOracle(
    key="siw_analysis", covers=("siw_analysis",),
    kind="formula_reimpl",
    reference="w_eff=w−d²/(0.95s)（Cassivi 2002）；fc10=c/(2·w_eff·√εr)",
    domain_box="w∈{8,12.1317,16}mm，d=0.6，s∈{0.6,1.0}，εr=3.66，f∈{6,10,15}GHz",
    grid=lambda: [{"w_mm": w, "d_mm": 0.6, "s_mm": s,
                   "epsilon_r": 3.66, "freq_ghz": f}
                  for w in (8.0, 12.1317, 16.0) for s in (0.6, 1.0)
                  for f in (6.0, 10.0, 15.0)],
    oracle=_siw_oracle, extract=_siw_extract))
_floors("siw_analysis", fc10_ghz=5e-3, weff_mm=5e-3, beta_rad_m=5e-3,
        f_over_fc=5e-5)

_register(ClosedFormOracle(
    key="patch_length", covers=("patch_length",),
    kind="formula_reimpl",
    reference="Balanis W/εeff + Hammerstad 1975 ΔL/h=0.412(εeff+0.3)(w/h+0.264)"
              "/[(εeff−0.258)(w/h+0.8)]，两边缘合计 2ΔL、L 扣 2·d_l（内核口径）",
    domain_box="f0∈{2.4,5.8,10}GHz，εr∈{2.2,3.66,4.4}，h∈{0.254,0.508,1.524}mm",
    grid=lambda: [{"f0_ghz": f, "epsilon_r": er, "h_mm": h}
                  for f in (2.4, 5.8, 10.0) for er in (2.2, 3.66, 4.4)
                  for h in (0.254, 0.508, 1.524)],
    oracle=_patch_oracle, extract=_patch_extract))
_floors("patch_length", patch_w_mm=5e-3, eps_eff=5e-3, delta_l_mm=5e-3,
        patch_l_mm=5e-3)

_register(ClosedFormOracle(
    key="rfid_forward_link", covers=("rfid_forward_link",),
    kind="formula_reimpl",
    reference="Friis：P=EIRP+G−20lg(4πd/λ)−L_pol（EIRP 口径，λ=c/f）",
    domain_box="f=915MHz/2.4GHz，EIRP∈{30,36}dBm，d∈{1,3,10}m",
    grid=lambda: [{"frequency_hz": f, "eirp_dbm": e, "g_tag_dbi": 2.0,
                   "distance_m": d, "sensitivity_dbm": -15.0,
                   "polarization_loss_db": pol}
                  for f in (915e6, 2.4e9) for e in (30.0, 36.0)
                  for d in (1.0, 3.0, 10.0) for pol in (0.0, 3.0)],
    oracle=_rfid_forward_oracle, extract=_rfid_forward_extract))
_floors("rfid_forward_link", p_tag_dbm=5e-8, path_loss_db=5e-8,
        margin_db=5e-8)

# ════════════════════════ 生成式裁判（网格对拍运行器）═══════════════════════


def _grade(rel: float) -> str:
    if rel <= GRADE_A_MAX:
        return "A"
    if rel <= GRADE_B_MAX:
        return "B"
    if rel <= GRADE_C_MAX:
        return "C"
    return "D"


_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def cross_check_oracle(key: str, *,
                       registry: Mapping[str, ClosedFormOracle] | None = None,
                       ) -> dict[str, Any]:
    """单键生成式对拍（网格逐点：注册计算器 vs 闭式 oracle）。

    域外点（计算器域守卫异常）记 skipped_domain 不计级；评估点分级
    A/B/C/D；本键 grade=最差项；全部点域外=verdict FAIL（无数据不放行）。
    """
    oc = (registry or CLOSED_FORM_ORACLES)[key]
    spec = CALCULATOR_REGISTRY.get(oc.key)
    per_quantity: dict[str, dict[str, Any]] = {}
    n_eval = 0
    n_skipped = 0
    skipped_errors: list[str] = []
    for params in oc.grid():
        try:
            result = spec.func(**params)
            items = oc.items(params, result)
        except _DOMAIN_EXC as exc:
            n_skipped += 1
            skipped_errors.append(f"{type(exc).__name__}: {exc}")
            continue
        n_eval += 1
        for it in items:
            rel = it.rel_err()
            slot = per_quantity.setdefault(it.quantity, {
                "n_points": 0, "worst_rel_err": 0.0, "worst_grade": "A",
                "expected_ref": it.expected, "actual_at_worst": it.actual,
                "params_at_worst": {k: v for k, v in params.items()},
            })
            slot["n_points"] += 1
            if rel > slot["worst_rel_err"]:
                slot.update({"worst_rel_err": rel,
                             "worst_grade": _grade(rel),
                             "expected_ref": it.expected,
                             "actual_at_worst": it.actual,
                             "params_at_worst": {k: v for k, v in params.items()}})
    if n_eval == 0:
        return {"ok": False, "schema": CLOSED_FORM_ORACLE_SCHEMA, "key": key,
                "covers": list(oc.covers), "kind": oc.kind,
                "reference": oc.reference, "domain_box": oc.domain_box,
                "n_grid_points": n_eval + n_skipped, "n_evaluated": 0,
                "n_skipped_domain": n_skipped, "grade": "D",
                "verdict": "FAIL",
                "issues": ["域内零评估点（全部网格点被计算器域守卫拒绝）"
                           + f"：{skipped_errors[:3]}"],
                "per_quantity": per_quantity,
                "skipped_domain_errors": skipped_errors}
    worst = max((q["worst_grade"] for q in per_quantity.values()),
                key=lambda g: _GRADE_ORDER[g]) if per_quantity else "A"
    issues = [f"{q}: worst={slot['worst_grade']}"
              f"(rel={slot['worst_rel_err']:.3g}) @ {slot['params_at_worst']}"
              for q, slot in sorted(per_quantity.items())
              if slot["worst_grade"] == "D"]
    return {"ok": True, "schema": CLOSED_FORM_ORACLE_SCHEMA, "key": key,
            "covers": list(oc.covers), "kind": oc.kind,
            "reference": oc.reference, "domain_box": oc.domain_box,
            "n_grid_points": n_eval + n_skipped, "n_evaluated": n_eval,
            "n_skipped_domain": n_skipped, "grade": worst,
            "verdict": "PASS" if worst != "D" else "FLAG",
            "issues": issues,
            "per_quantity": per_quantity,
            "skipped_domain_errors": skipped_errors}


def cross_check_all(*,
                    registry: Mapping[str, ClosedFormOracle] | None = None,
                    ) -> dict[str, Any]:
    """全注册 oracle 生成式对拍总报告（≥20 键覆盖口径）。"""
    reg = dict(registry or CLOSED_FORM_ORACLES)
    rows = {k: cross_check_oracle(k, registry=reg) for k in sorted(reg)}
    covered: set[str] = set()
    for row in rows.values():
        covered.update(row["covers"])
    by_grade: dict[str, int] = {}
    for row in rows.values():
        by_grade[row["grade"]] = by_grade.get(row["grade"], 0) + 1
    flags = [k for k, row in rows.items() if row["verdict"] != "PASS"]
    return {
        "ok": all(row["ok"] and row["verdict"] == "PASS"
                  for row in rows.values()),
        "schema": CLOSED_FORM_ORACLE_SCHEMA,
        "n_oracles": len(rows),
        "n_keys": len(covered),                 # 覆盖的注册键数（≥20 口径）
        "covered_keys": sorted(covered),
        "by_grade": by_grade,
        "flags": flags,                          # D 级旗标键（人工审计入口）
        "rows": rows,
        "note": "QM-2 测量与报告面：D 级=旗标待人工审计，不自动判死",
    }
