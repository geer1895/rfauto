r"""AP-14 波纹/Potter 喇叭综合确定性内核（**登记级**，ge8b Wave B 席 B9，
2026-10-03）。

规格：研究扩充 round17 §三 :82「AP-14 波纹/
Potter 喇叭综合（P2/M）：λ/4 槽深+混合模平衡+双模阶跃比」+ 席 B9 任务书
「波纹喇叭（Potter/波纹口径闭式）：混合模 EH11 条件+波纹深度闭式
（登记级闭式函数，不做全波）」。

规格边界（#122 如实；登记级=只交付闭式函数+测试锚，无模板渲染、无全波）
--------------------
- λ/4 槽深闭式 + 槽纹面 reactance 模型 + 混合模（HE11）平衡诊断面；
- **Potter 双模阶跃比不入码**：Potter 1963 双模锥喇叭的阶跃半径比/相位
  补偿长度等设计常数未回原文逐位核对（citation-rot 纪律，#118），登记
  注记不做数；
- 波纹离散（环形槽的径向模严格解/槽间耦合）与全波验证（方向图/交叉
  极化）= 模板/真机面，不在本内核。

法源与公式（出处逐式）
--------------------
- **λ/4 槽深**（波纹喇叭标准口径，Clarricoats & Olver《Corrugated Horns
  for Microwave Antennas》IET 工程通称；**二手转写如实**）：

      d_qw = λ0/4 = c/(4f)

  短路槽（径向 stub）深度四分之一波长 → 槽口呈现开路（tan(k0·d)→∞），
  壁面对纵向电流呈 PMC 性 → TE11/TM11 简并牵引出平衡混合模 HE11。
- **槽纹面等效表面电抗**（短路 TEM stub 输入电抗 + 占空比平均，工程
  近似口径；严格径向波导槽模/槽间耦合未建模如实登记）：

      X_s(f; d, η_g) = η_g · η₀ · tan(k₀·d)，  k₀=2πf/c
      η_g = p_groove/(p_groove + t_tooth)      （槽占空系数）

  精确极限（测试钉）：d=λ/4 → tan(π/2) 发散（开路/PMC）；d=λ/2 → 0
  （短路/PEC）；η_g→1 → 裸短路线上电抗 tan(k0 d)。
- **混合模条件（EH11/HE11 平衡诊断面）**：光壁圆波导中 TE11 与 TM11
  截止波数**不**简并（J₁'(x)=0 首根 1.84118 vs J₁(x)=0 首根 3.83171，
  scipy 双源核对=测试独立裁判）；波纹壁电抗增大把 TM11 截止向 TE11
  牵引，深度 λ/4 档即工程平衡点。本内核交付：
  * te11/tm11 归一化截止常数（scipy 求根精确值，硬编码文献字面量
    仅作测试对拍锚）；
  * 平衡裕量诊断：|k₀d − π/2| 相位距 + 电抗区符号（感性/容性）。

单位 SI；e^{−jωt}；core 纯函数零 IO、不注册 calculators 键（本席纪律 3，
amc_mushroom 同款）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.dielectric_extract import C0
from rfauto.core.metasurface_lut import ETA0_OHM

__all__ = [
    "TE11_KC_A",
    "TM11_KC_A",
    "bessel_root_j1_first",
    "bessel_root_j1p_first",
    "grooved_surface_reactance_ohm",
    "he11_balance_report",
    "quarter_wave_depth_m",
]


#: TE11 归一化截止常数（kc·a = J₁'(x) 第一正根）：文献值 1.8411837831。
TE11_KC_A = 1.8411837831
#: TM11 归一化截止常数（kc·a = J₁(x) 第一正根）：文献值 3.8317059702。
TM11_KC_A = 3.8317059702


def _require_positive(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限实数，got {value!r}")
    return v


def _require_unit_range(name: str, value: float) -> float:
    v = float(value)
    if not math.isfinite(v) or not 0.0 < v <= 1.0:
        raise ValueError(f"{name} 必须在 (0,1]，got {value!r}")
    return v


def quarter_wave_depth_m(f_hz: float) -> float:
    """λ/4 槽深 d = c/(4f)（m；定义式恒等，测试双向回收钉）。"""
    f = _require_positive("f_hz", f_hz)
    return C0 / (4.0 * f)


def bessel_root_j1p_first() -> float:
    """J₁'(x) 第一正根（scipy 求根精确值；TE11 归一化截止常数）。"""
    from scipy.optimize import brentq
    from scipy.special import jvp

    return float(brentq(lambda x: jvp(1, x, 1), 1.0, 3.0, xtol=1e-12))


def bessel_root_j1_first() -> float:
    """J₁(x) 第一正根（scipy 求根精确值；TM11 归一化截止常数）。"""
    from scipy.optimize import brentq
    from scipy.special import j1

    return float(brentq(lambda x: j1(x), 3.0, 4.5, xtol=1e-12))


def grooved_surface_reactance_ohm(f_hz: float, d_m: float,
                                  duty: float = 1.0) -> float:
    """槽纹面等效表面电抗 X_s = η_g·η₀·tan(k₀·d)（Ω；短路 stub 工程
    近似口径）。

    极限（测试钉）：d=λ/4 → +∞（开路/PMC）；d=λ/2 → 0（短路/PEC）；
    duty→1 → 裸短路线上电抗。d>λ/2 后符号翻转（容性区）随 tan 周期。
    """
    f = _require_positive("f_hz", f_hz)
    d = _require_positive("d_m", d_m)
    eta_g = _require_unit_range("duty", duty)
    k0 = 2.0 * math.pi * f / C0
    phase = k0 * d
    # tan 在 π/2 奇点邻域数值发散是**物理开路口径**，直接抛带语义的错
    if abs(phase - math.pi / 2.0) < 1e-12:
        return math.inf
    return eta_g * ETA0_OHM * math.tan(phase)


def he11_balance_report(f_hz: float, a_m: float, d_m: float,
                        duty: float = 1.0) -> dict[str, Any]:
    """混合模（HE11）平衡诊断面：TE11/TM11 截止分离 + 槽深相位距 +
    电抗区符号（登记级；无全波/无 Potter 双模常数）。"""
    f = _require_positive("f_hz", f_hz)
    _require_positive("a_m", a_m)   # 口径半径只进诊断语义（截止分离与 d 无关）
    d = _require_positive("d_m", d_m)
    eta_g = _require_unit_range("duty", duty)
    k0 = 2.0 * math.pi * f / C0
    phase = k0 * d
    x_s = grooved_surface_reactance_ohm(f, d, duty)
    return {
        "te11_kc_a": bessel_root_j1p_first(),
        "tm11_kc_a": bessel_root_j1_first(),
        "te11_kc_a_literal": TE11_KC_A,
        "tm11_kc_a_literal": TM11_KC_A,
        # 光壁分离度（TM11/TE11 截止比；波纹电抗把它向 1 牵引）
        "smooth_guide_separation": bessel_root_j1_first()
        / bessel_root_j1p_first(),
        "k0d": phase,
        "quarter_wave_phase_gap_rad": phase - math.pi / 2.0,
        "xs_ohm": x_s,
        "reactance_regime": ("open_pmc" if not math.isfinite(x_s)
                             else ("inductive" if x_s > 0 else "capacitive")),
        "duty": eta_g,
        "boundary_note": "登记级：槽模离散/槽间耦合/Potter 双模阶跃常数"
                         "未建模（citation-rot 纪律），全波=模板面",
    }
