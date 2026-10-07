"""倒置微带（inverted microstrip）确定性内核（TA-7 批 Wave A 席 1）。

结构口径（Wadell《Transmission Line Design Handbook》倒置微带定义；金属/
介质 z 序相对普通微带对调）：地面 z=0（域 PEC 底界），零厚度条带悬于
z=h_air（条带下表面=空气隙顶），基板板 z∈[h_air, h_air+h_sub] 上覆，其上
开放空气域（无上地）。

**内核形态如实登记（#122）**：文献闭式不可达（Wadell/Bahl-Trivedi 倒置
微带闭式系数在可达来源中均无原文数字——反爬/纸本受限；凭记忆复写系数
的引用腐坏风险被 #df6-⑬ 先例否决），本内核设计链以 **2D 准静态 FD
Laplace 裁判**（core/quasistatic_fd.inverted_microstrip_quasistatic，本批
新增几何族）brentq 反解为数字真值：

- FD 裁判求解器资格（core/quasistatic_fd 模块头）：微带 vs HJ 静态
  +0.18~0.32%、CPS 半空间极限 −0.1%、Cohn 空气带线 −0.5%、h→b εr 精确
  四锚已过；
- 新几何族族内验证锚（test_ta_wave_a_templates）：εr=1（无介质边界）与
  微带族同物理互检（实测 ~0.22%）、1≤εeff≤εr 括号、单调性；
- 近似级别如实声明：准静态（无色散）、零厚度带、PEC 地、介质无损；
  数值地板=FD 离散+Richardson 外推（族内实测 ~0.2-0.5%）。

真机冒烟与 HFSS 仲裁属后续批次（本批零发射，meta smoke_note 登记）。
"""

from __future__ import annotations

import math

__all__ = ["inverted_ms_design_params", "inverted_ms_fd"]


def inverted_ms_fd(w_mm: float, h_air_mm: float, h_sub_mm: float,
                   eps_r: float) -> object:
    """倒置微带 FD 裁判单点（core/quasistatic_fd 薄再导出，#116 零副本）。

    返回 QuasiStaticResult（eps_eff/c_air_f_per_m/z0_ohm/d0_mm/richardson…）。
    """
    from rfauto.core.quasistatic_fd import inverted_microstrip_quasistatic

    return inverted_microstrip_quasistatic(float(w_mm), float(h_air_mm),
                                           float(h_sub_mm), float(eps_r))


def inverted_ms_design_params(z0_ohm: float = 50.0,
                              h_air_mm: float = 0.508,
                              h_sub_mm: float = 0.508,
                              er: float = 3.66,
                              line_len_mm: float = 40.0,
                              f0_ghz: float = 2.5) -> dict[str, float]:
    """设计链：目标 Z0 → 条带宽 w（FD 裁判 brentq 反解，回代自洽）。

    返回 w_mm（4 位舍入）/ z0_actual_ohm / eps_eff / line_len_mm 及派生
    λg@f0（准静态口径，色散未计如实声明）。Z0 随 w 单调递减（物理：
    宽带→低阻；单测网格钉）。单次反解 ~1s（richardson 双档 ×4 solve）。
    """
    from scipy.optimize import brentq

    from rfauto.core.quasistatic_fd import inverted_microstrip_quasistatic

    z_t = float(z0_ohm)
    if not (math.isfinite(z_t) and z_t > 0.0):
        raise ValueError(f"inverted_ms: z0_ohm 须为正有限数，得到 {z0_ohm!r}")
    for name, v in (("h_air_mm", h_air_mm), ("h_sub_mm", h_sub_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"inverted_ms: {name} 须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        raise ValueError(f"inverted_ms: er 须 ≥1，得到 {er!r}")

    def objective(w_mm: float) -> float:
        r = inverted_microstrip_quasistatic(w_mm, float(h_air_mm),
                                            float(h_sub_mm), float(er))
        return r.z0_ohm - z_t

    lo, hi = 0.05 * (h_air_mm + h_sub_mm), 60.0 * (h_air_mm + h_sub_mm)
    z_lo, z_hi = objective(lo), objective(hi)
    if z_lo < 0.0 or z_hi > 0.0:
        raise ValueError(
            f"目标 {z_t}Ω 超出倒置微带可达范围 [{z_hi + z_t:.1f}, "
            f"{z_lo + z_t:.1f}]Ω（w∈[{lo:.4f}, {hi:.4f}]mm 括号扫描）")
    w_mm = float(brentq(objective, lo, hi, xtol=1e-9))
    r = inverted_microstrip_quasistatic(round(w_mm, 4), float(h_air_mm),
                                        float(h_sub_mm), float(er))
    eps_eff = float(r.eps_eff)
    lam_g_mm = 299.792458 / (float(f0_ghz) * math.sqrt(eps_eff))
    return {
        "w_mm": round(w_mm, 4),
        "z0_actual_ohm": round(float(r.z0_ohm), 3),
        "eps_eff": round(eps_eff, 5),
        "lambda_g_mm": round(lam_g_mm, 4),
        "line_len_mm": float(line_len_mm),
        "h_air_mm": float(h_air_mm),
        "h_sub_mm": float(h_sub_mm),
        "er": float(er),
    }
