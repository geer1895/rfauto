"""RF 暴露限值表（FCC 47 CFR §1.1310 Table 1 + ICNIRP 2020 Table 5）
与 EIRP 合规距离闭式（远场球面反解）。

权威口径（公开规范事实；2026-09-30 逐段回原文核对并逐位抄录，
铁律 1c / #df6⑬：禁凭记忆写表值）
---------------------------------------------------------------------------
- FCC：47 CFR §1.1310(e)(1) Table 1 "Limits for Maximum Permissible
  Exposure (MPE)"（eCFR 当前版实测取表，2026-09-29 更新版）：
  * (i) Occupational/Controlled（职业/受控）：
      0.3–3.0 MHz:   E=614 V/m,  H=1.63 A/m,  S=(100) mW/cm²,  avg≤6 min
      3.0–30 MHz:    E=1842/f,   H=4.89/f,   S=(900/f²)
      30–300 MHz:    E=61.4 V/m, H=0.163 A/m, S=1.0 mW/cm²
      300–1500 MHz:  S=f/300 mW/cm²
      1500–100000:   S=5 mW/cm²
  * (ii) General Population/Uncontrolled（公众/非受控）：
      0.3–1.34 MHz:  E=614 V/m,  H=1.63 A/m,  S=(100) mW/cm²,  avg<30 min
      1.34–30 MHz:   E=824/f,    H=2.19/f,    S=(180/f²)
      30–300 MHz:    E=27.5 V/m, H=0.073 A/m, S=0.2 mW/cm²
      300–1500 MHz:  S=f/1500 mW/cm²
      1500–100000:   S=1.0 mW/cm²
    f=MHz；*(括号) = plane-wave equivalent power density（远场平面波
    等效口径，§1.1310 表脚注）。注意公众段 30–300 MHz 的 H=0.073
    （eCFR 表原文两位写法，非 0.0729）。
- ICNIRP："Guidelines for Limiting Exposure to Electromagnetic Fields
  (100 kHz to 300 GHz)", Health Phys. 118(5):483-524; 2020（官方 PDF
  本地逐位核对）。本模块入库 **Table 5（全身平均，30 min 平均）公众
  （General public）参考水平**（任务口径"ICNIRP 2020 公众限值"）：
      0.1–30 MHz:    E=300/f_M^0.7 V/m,  H=2.2/f_M A/m,  S=NA
      >30–400 MHz:   E=27.7 V/m, H=0.073 A/m, S=2 W/m²
      >400–2000 MHz: E=1.375·f_M^0.5, H=0.0037·f_M^0.5, S=f_M/200 W/m²
      >2–300 GHz:    S=10 W/m²
    （f_M=MHz； occupational 行不入库——本模块域=公众限值，如实收窄）
  连续性自证：30 MHz 处 E=300/30^0.7=27.69≈27.7、H=2.2/30=0.0733≈0.073；
  400 MHz 处 S=400/200=2；2000 MHz 处 S=2000/200=10（单测逐位钉）。
- 合规距离（远场球面）：R = √(EIRP_W/(4π·S_lim))（EIRP 定义
  S=EIRP/(4πR²) 反解；同一几何下远场 E=√(30·EIRP)/R，与
  S=E²/η0 恒等——η0=4π·30，双路径单测互证）。只在远场意义下成立
  （反应近场/辐射近场须按标准另行评估，输出 note 如实声明）。

域守卫：FCC 表定义域 0.3–100000 MHz、ICNIRP 100 kHz–300 GHz；带外
显式 ValueError（越域拒绝不外推）。单位纪律：表值入库为 SI
（V/m、A/m、W/m²），FCC 的 mW/cm² ×10 入库；返回 JSON 可序列化。
"""

from __future__ import annotations

import math
from typing import Any

_C0 = 299792458.0  # m/s
_ETA0_OHM = 376.730313668  # 真空波阻抗（与 calc_families.shield 同值）

# ─── FCC 47 CFR §1.1310(e)(1) Table 1（逐位抄录；S 列 mW/cm²→W/m² 入库）───
# 段元组：(f_lo_MHz, f_hi_MHz, E_const_V_m, E_formula, H_const_A_m,
#          H_formula, S_const_W_m2, S_formula, plane_wave_equiv, avg_min)
# formula: ("const", v) | ("k_over_f", k) | ("k_over_f2", k) | ("f_over_k", k)
#          | ("k_times_sqrt_f", k) | ("k_over_pow", k, p)（ICNIRP 用）
# 公式列一律为 SI 值（FCC S 列公式已按 ×10 换算：900/f² mW/cm²→9000/f²
# W/m²、f/300 mW/cm²→f_MHz/30 W/m²、180/f²→1800/f²、f/1500→f_MHz/150；
# ICNIRP 表本身 SI 原样）。
_FCC_OCCUPATIONAL: tuple[tuple, ...] = (
    (0.3, 3.0, 614.0, ("const", 614.0), 1.63, ("const", 1.63),
     1000.0, ("const", 1000.0), True, 6.0),
    (3.0, 30.0, None, ("k_over_f", 1842.0), None, ("k_over_f", 4.89),
     None, ("k_over_f2", 9000.0), True, 6.0),
    (30.0, 300.0, 61.4, ("const", 61.4), 0.163, ("const", 0.163),
     10.0, ("const", 10.0), True, 6.0),
    (300.0, 1500.0, None, None, None, None,
     None, ("f_over_k", 30.0), False, 6.0),
    (1500.0, 100000.0, None, None, None, None,
     50.0, ("const", 50.0), False, 6.0),
)
_FCC_GENERAL: tuple[tuple, ...] = (
    (0.3, 1.34, 614.0, ("const", 614.0), 1.63, ("const", 1.63),
     1000.0, ("const", 1000.0), True, 30.0),
    (1.34, 30.0, None, ("k_over_f", 824.0), None, ("k_over_f", 2.19),
     None, ("k_over_f2", 1800.0), True, 30.0),
    (30.0, 300.0, 27.5, ("const", 27.5), 0.073, ("const", 0.073),
     2.0, ("const", 2.0), True, 30.0),
    (300.0, 1500.0, None, None, None, None,
     None, ("f_over_k", 150.0), False, 30.0),
    (1500.0, 100000.0, None, None, None, None,
     10.0, ("const", 10.0), False, 30.0),
)

# ─── ICNIRP 2020 Table 5 General public（全身平均 30 min；逐位抄录）────────
_ICNIRP_PUBLIC: tuple[tuple, ...] = (
    (0.1, 30.0, None, ("k_over_pow", 300.0, 0.7), None,
     ("k_over_pow", 2.2, 1.0), None, None, False, 30.0),
    (30.0, 400.0, 27.7, ("const", 27.7), 0.073, ("const", 0.073),
     2.0, ("const", 2.0), False, 30.0),
    (400.0, 2000.0, None, ("k_times_sqrt_f", 1.375), None,
     ("k_times_sqrt_f", 0.0037), None, ("f_over_k", 200.0), False, 30.0),
    (2000.0, 300000.0, None, None, None, None,
     10.0, ("const", 10.0), False, 30.0),
)

_STANDARDS: dict[str, tuple[tuple, ...]] = {
    "fcc_occupational": _FCC_OCCUPATIONAL,
    "fcc_general": _FCC_GENERAL,
    "icnirp_public": _ICNIRP_PUBLIC,
}

_F_MHZ_MAX = {"fcc_occupational": 100000.0, "fcc_general": 100000.0,
              "icnirp_public": 300000.0}
_F_MHZ_MIN = {"fcc_occupational": 0.3, "fcc_general": 0.3,
              "icnirp_public": 0.1}


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _eval_formula(formula: tuple | None, f_mhz: float) -> float | None:
    """按段公式求值（f 单位 MHz，返回 SI 值或 None=该量该段未列）。"""
    if formula is None:
        return None
    kind = formula[0]
    if kind == "const":
        return float(formula[1])
    if kind == "k_over_f":
        return float(formula[1]) / f_mhz
    if kind == "k_over_f2":
        return float(formula[1]) / (f_mhz * f_mhz)
    if kind == "f_over_k":
        return f_mhz / float(formula[1])
    if kind == "k_times_sqrt_f":
        return float(formula[1]) * math.sqrt(f_mhz)
    if kind == "k_over_pow":
        return float(formula[1]) / (f_mhz ** float(formula[2]))
    raise ValueError(f"未知公式类型 {kind}")


def _find_band(standard: str, freq_hz: float) -> tuple:
    if standard not in _STANDARDS:
        raise ValueError(
            f"未知标准 {standard!r}（可用: {sorted(_STANDARDS)}）")
    f = _num(freq_hz, "freq_hz")
    if f <= 0.0:
        raise ValueError("freq_hz 必须 >0")
    f_mhz = f / 1e6
    lo = _F_MHZ_MIN[standard]
    hi = _F_MHZ_MAX[standard]
    if not (lo <= f_mhz <= hi):
        raise ValueError(
            f"freq_hz={f} 落在 {standard} 表定义域外 "
            f"[{lo}, {hi}] MHz（越域拒绝不外推）")
    for band in _STANDARDS[standard]:
        f_lo, f_hi = band[0], band[1]
        # 末段闭区间含上端点，其余 [lo, hi)
        if band is _STANDARDS[standard][-1]:
            if f_lo <= f_mhz <= f_hi:
                return band
        elif f_lo <= f_mhz < f_hi:
            return band
    raise ValueError(f"freq_hz={f} 未落入 {standard} 任一频段（表构造异常）")


def mpe_limit(freq_hz: float, standard: str = "fcc_general") -> dict[str, Any]:
    """MPE/参考水平查表：freq_hz+标准 → E/H/S 限值（SI 单位）。"""
    band = _find_band(standard, freq_hz)
    (f_lo, f_hi, e_val, e_form, h_val, h_form, s_val, s_form,
     pw_equiv, avg_min) = band
    f_mhz = _num(freq_hz, "freq_hz") / 1e6
    # E/H 列：段常量直读；段公式求值（E_formula 已含单位换算入表值）
    if e_val is not None:
        e_limit: float | None = float(e_val)
    else:
        e_limit = _eval_formula(e_form, f_mhz)
    if h_val is not None:
        h_limit: float | None = float(h_val)
    else:
        h_limit = _eval_formula(h_form, f_mhz)
    if s_val is not None:
        s_limit: float | None = float(s_val)
    else:
        s_limit = _eval_formula(s_form, f_mhz)
    out: dict[str, Any] = {
        "standard": standard,
        "band_mhz": [float(f_lo), float(f_hi)],
        "e_v_per_m": (None if e_limit is None else round(e_limit, 9)),
        "h_a_per_m": (None if h_limit is None else round(h_limit, 9)),
        "s_w_per_m2": (None if s_limit is None else round(s_limit, 9)),
        "plane_wave_equiv_s": bool(pw_equiv),
        "averaging_time_min": float(avg_min),
        "freq_in_mhz": round(f_mhz, 9),
        "note": "FCC=47 CFR §1.1310(e)(1) Table 1（E/H/S 直接表值；"
                "plane_wave_equiv_s=True 段 S 列为平面波等效口径）；"
                "ICNIRP=2020 Table 5 全身平均公众参考水平（30 min）",
    }
    return out


def mpe_distance(eirp_w: float, freq_hz: float,
                 standard: str = "fcc_general") -> dict[str, Any]:
    """远场合规距离：R = √(EIRP_W/(4π·S_lim))（EIRP 定义球面密度反解）。

    EIRP_W>0（线性瓦，非 dBm——调用方先换算，dBm 见
    calc_families.rfid._dbm_to_w 同式）。S_lim 取该频段功率密度限值；
    E/H-only 段（FCC <300 MHz）S 列为平面波等效口径（表脚注 *）→
    以 S=E²/η0 等效密度算距离并如实标注。远场 E=√(30·EIRP)/R 与
    S=E²/η0 恒等（η0=4π·30），单测双路径互证。"""
    p = _num(eirp_w, "eirp_w")
    if p <= 0.0:
        raise ValueError("eirp_w 必须 >0（线性瓦口径）")
    band = _find_band(standard, freq_hz)
    (f_lo, f_hi, _e, _ef, _h, _hf, s_val, s_form, pw_equiv,
     _avg) = band
    f_mhz = _num(freq_hz, "freq_hz") / 1e6
    s_limit = (float(s_val) if s_val is not None
               else _eval_formula(s_form, f_mhz))
    if s_limit is None or s_limit <= 0.0:
        # ICNIRP 0.1–30 MHz 段 S=NA：ICNIRP 2020 明确 100 kHz–30 MHz
        # "treated as always being within the near-field zone"（原文学
        # 术口径）——远场球面距离不适用，显式拒绝不凑数
        raise ValueError(
            "该频段无功率密度限值列（ICNIRP 0.1–30 MHz 全身参考水平仅 "
            "E/H，且 100 kHz–30 MHz 按 ICNIRP 恒按近场评估——远场球面"
            "距离口径不适用；请用 mpe_limit 的 E/H 限值按标准全评估）")
    dist = math.sqrt(p / (4.0 * math.pi * s_limit))
    e_at_r = math.sqrt(30.0 * p) / dist
    # 远场界参考：Fraunhofer d=2D²/λ 需口径 D——本模块无口径信息，
    # 如实给 λ 级参考（2λ/π = 偶极子类常用远场下界近似）不判合规
    wavelength = _C0 / _num(freq_hz, "freq_hz")
    return {"distance_m": round(dist, 12),
            "s_limit_w_per_m2": round(s_limit, 12),
            "e_at_limit_v_per_m": round(e_at_r, 9),
            "plane_wave_equiv_basis": bool(pw_equiv),
            "lambda_m": round(wavelength, 12),
            "far_field_note": "远场球面口径 R=√(EIRP/(4πS))；"
                              "近场（R≲2D²/λ 或反应近场区）须按标准"
                              "全评估，本结果不作近场合规判据",
            "standard": standard,
            "band_mhz": [float(f_lo), float(f_hi)]}
