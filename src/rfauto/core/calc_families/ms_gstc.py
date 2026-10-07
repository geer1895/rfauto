"""GSTC 面抗综合族（MM-3，内核 core/gstc.py，本模块只做注册壳）。

规格 规格深案 §C-2（B 流超材料，2026-10-02）；
法源 arXiv:1408.0273v2 = IEEE TAP 63(7) 2015 逐式核到（法向入射单轴
Huygens 面闭式 Eq.(17)/(18)/(19)）。三键：
- gstc_forward：χ_ee/χ_mm（实数或 [re,im]）+ freq_ghz → Eq.(17)/(18)
  T/R（complex→[re,im]）+ 无源守卫 |R|²+|T|²≤1+1e-9（违即 ok=False）
  + 能量/dB/相位报告 + 2×2 S 面（[[R,T],[T,R]]，互易）。
- gstc_synthesize：目标 (T,R) → Eq.(19) χ 反演 + 往返自检（Eq.19↔Eq.17
  逐位 ≤1e-12，违即 RuntimeError→ok=False）；χ→∞ 极点域显式拒绝。
- gstc_lut_crosscheck：频带 (Γ,T) 数组 → χ 反演 → 正演回带内 Δ|T|_dB 门
  （0.5dB 起步；J4 Floquet 锚通道接口面，真机正演腿后接）。
χ_em/χ_me 交叉耦合闭式原文未给，显式不做（参数位保留，传非 None 拒绝）；
无耗口径=χ 实数（|T|²+|R|²=1 代数恒等）、Im χ>0=增益必拒。

锚树 tests/unit/test_gstc.py（对称 χ R=0/实 χ 能量恒等逐位/经典电阻膜
T=2·3/CPA 全吸/PEC 帘渐近/往返/奇点负例/LUT v2 通道桥）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


def _c2j(x: complex) -> list[float]:
    """complex → [re, im]（service JSON 复数约定）。"""
    return [float(x.real), float(x.imag)]


def _freq_to_k(freq_ghz: Any) -> float:
    """freq_ghz（正有限）→ 真空波数 k=2πf/c₀（rad/m，空气侧口径）。"""
    from rfauto.core.metasurface_lut import C0_M_S

    if isinstance(freq_ghz, bool):
        raise ValueError("freq_ghz 须为正有限实数（GHz）")
    f = float(freq_ghz)
    if not math.isfinite(f) or f <= 0.0:
        raise ValueError(f"freq_ghz 须为正有限实数（GHz），收到 {freq_ghz!r}")
    return 2.0 * math.pi * (f * 1e9) / C0_M_S


@register_calculator(
    "gstc_forward",
    "MM-3 GSTC 正向（规格 §C-2，arXiv 1408.0273v2=IEEE TAP 63(7) 2015 "
    "Eq.(17)/(18) 逐式）：法向入射单轴 Huygens 面 χ_ee/χ_mm（米；实数或 "
    "[re,im] 对）→ 共极化 T/R（[re,im]）+ 能量 |R|²+|T|²、dB/相位与 2×2 "
    "S 面（互易）。无源守卫 |R|²+|T|²≤1+1e-9 违即显式报错（本式口径无耗"
    "=χ 实数、Im χ>0=增益非物理）；χ_em/χ_me 交叉耦合闭式原文未给显式不"
    "做（参数位保留，传非 None 拒绝）；x/y 极化法向入射简并同结果。",
    (("chi_ee", "float|[re,im] 面电极化率 χ_ee（米；无耗=实数，Im>0 即增益必拒）"),
     ("chi_mm", "float|[re,im] 面磁极化率 χ_mm（米，同上）"),
     ("freq_ghz", "float 频率 GHz（>0；k=2πf/c₀ 真空口径）"),
     ("polarization", "str 'x'|'y'（法向入射共极化简并；默认 'x'）"),
     ("chi_em", "float|[re,im] 显式不做：传非 None 即 ValueError（闭式原文未给）"),
     ("chi_me", "float|[re,im] 显式不做：传非 None 即 ValueError（闭式原文未给）")),
    required=("chi_ee", "chi_mm", "freq_ghz"),
)
def gstc_forward(chi_ee: Any, chi_mm: Any, freq_ghz: Any,
                 polarization: str = "x",
                 chi_em: Any = None, chi_me: Any = None) -> dict:
    from rfauto.core.gstc import gstc_forward as _forward

    k = _freq_to_k(freq_ghz)
    out = _forward(chi_ee, chi_mm, k, polarization=polarization,
                   chi_em=chi_em, chi_me=chi_me)
    t, r = out["t"], out["r"]
    return {
        "t": _c2j(t), "r": _c2j(r),
        "t_db": out["t_db"], "r_db": out["r_db"],
        "t_phase_deg": out["t_phase_deg"], "r_phase_deg": out["r_phase_deg"],
        "energy": float(out["energy"]),
        "s_matrix": [[_c2j(r), _c2j(t)], [_c2j(t), _c2j(r)]],
        "chi_ee": _c2j(out["chi_ee"]), "chi_mm": _c2j(out["chi_mm"]),
        "k_rad_m": float(out["k_rad_m"]),
        "polarization": out["polarization"],
    }


@register_calculator(
    "gstc_synthesize",
    "MM-3 GSTC 逆解（规格 §C-2，arXiv 1408.0273v2 Eq.(19) 逐式）：目标共极化 "
    "(T,R)（[re,im]）→ 面极化率 χ_ee/χ_mm 反演 + Eq.(19)↔Eq.(17) 往返自检"
    "（逐位 ≤1e-12，违即 RuntimeError 显式失败——代数上应精确恒等）。"
    "|T±R+1|→0 的 χ→∞ 极点域（如 T=−1 全反 Huygens 极限）显式拒绝不外推；"
    "正向无源守卫不套用于本键（实测目标可轻微超物理，χ 可实现性归调用方判读）。",
    (("t", "float|[re,im] 目标透射系数 T（复数）"),
     ("r", "float|[re,im] 目标反射系数 R（复数）"),
     ("freq_ghz", "float 频率 GHz（>0；k=2πf/c₀ 真空口径）")),
    required=("t", "r", "freq_ghz"),
)
def gstc_synthesize(t: Any, r: Any, freq_ghz: Any) -> dict:
    from rfauto.core.gstc import gstc_synthesize as _synth

    k = _freq_to_k(freq_ghz)
    out = _synth(t, r, k)
    return {
        "chi_ee": _c2j(out["chi_ee"]), "chi_mm": _c2j(out["chi_mm"]),
        "k_rad_m": float(out["k_rad_m"]),
        "roundtrip_residual": float(out["roundtrip_residual"]),
        "t_recovered": _c2j(out["t_recovered"]),
        "r_recovered": _c2j(out["r_recovered"]),
    }


@register_calculator(
    "gstc_lut_crosscheck",
    "MM-3 GSTC 带内对拍通道（规格 §C-2：ms 真机单胞 Γ/T→χ 反演→正演回对拍，"
    "J4 Floquet 锚通道接口面；真机正演腿后接）：频带 (Γ,T) 复数组（实数或 "
    "[re,im] 对，freq_ghz 严格升序）→ 逐点 Eq.(19) χ 反演 → 正演回带内 "
    "Δ|T|_dB 门（gate_dt_db 缺省 0.5dB 起步）。返回 verdict/max_dt_db/"
    "逐点 χ 与 Δ|T|。诚实边界：离线通道正反两腿同源闭式 → Δ|T|≈1e-13dB"
    "（门判接口/管线破坏），判别力在 J4 Floquet 锚真机侧到位；|T|=0 点"
    "无有限 dB 诚实剔除（n_dt_excluded 计数，全剔除判 UNKNOWN 不凑 PASS）。",
    (("freq_ghz", "array 频率 GHz（一维严格升序正数）"),
     ("s11", "array 逐频点反射系数 Γ（实数或 [re,im] 对）"),
     ("s21", "array 逐频点透射系数 T（实数或 [re,im] 对）"),
     ("band_ghz", "array [f_lo, f_hi] 带内窗（GHz；缺省全带）"),
     ("gate_dt_db", "float 带内 Δ|T| 门（dB，>0；缺省 0.5）")),
    required=("freq_ghz", "s11", "s21"),
)
def gstc_lut_crosscheck(freq_ghz: list, s11: list, s21: list,
                        band_ghz: list | None = None,
                        gate_dt_db: float = 0.5) -> dict:
    from rfauto.core.gstc import gstc_crosscheck as _cc

    return _cc(freq_ghz, s11, s21, band_ghz=band_ghz,
               gate_dt_db=float(gate_dt_db))
