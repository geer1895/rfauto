"""Wilkinson 不等分功分器综合（架构批 W3-A 席，R2 空白域 G6）。

单键 unequal_split_wilkinson：二路不等分 Wilkinson（Pozar K 口径）闭式
综合——功分比 → 两臂 λ/4 特性阻抗 + 隔离电阻（含两臂端电阻分配）+ 两输出
λ/4 变换段阻抗 + 中心频率理论分配/回损/隔离说明字段。

公式口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- K 口径：K² = P3/P2（Pozar, *Microwave Engineering*, 4th ed., §7.3
  "Power Dividers and Directional Couplers" 不等分节的功分比定义；K>0，
  K>1 ⇒ 端口 3 为大功率端，K=1 退化为经典等分）。
- 两臂 λ/4 特性阻抗（受惠端=低阻臂，P2/P3 = Z03/Z02 由 λ/4 臂功率流
  P∝Z_end/Z² 与隔离等压条件直接导出）：

      Z02 = Z0·√(K(1+K²))            （端口 2 臂）
      Z03 = Z0·√((1+K²)/K³) = Z02/K²（端口 3 臂）

- 隔离电阻（奇模匹配条件）：

      R  = Z0(1+K²)/K
      R2 = Z0/K（端口 2 臂端）、R3 = K·Z0（端口 3 臂端），R2+R3=R
      （两端电阻分配取 Parad–Moynihan 原文约定：受惠臂端=低阻端；
      中心频率 S 矩阵只依赖总串联 R，分配信息供物理布局）

- 输出变换段（Parad–Moynihan 几何均值选型 Z04·Z05=Z0²，带宽最优化）：

      Z04 = Z0·√K （端口 2 侧）、Z05 = Z0/√K （端口 3 侧）

- 中心频率理论量（无损+全匹配下由功率守恒与设计比直接给出，说明字段）：
  |S21|²=1/(1+K²)、|S31|²=K²/(1+K²)、各端口回损/隔离在 f0 理想无究大，
  带宽内隔离/回损按臂电长度 90° 设计点随频退化（本键只出 f0 闭式）。

出处：Pozar 4th ed. §7.3；原始设计 L. I. Parad & R. L. Moynihan Jr.,
"Split Tee Power Divider", IEEE Trans. MTT-13(1):91–95, 1965-01；
数值锚（独立文献值）：Microwaves101 "Unequal-split Wilkinsons"——
50Ω、P2/P3=2（K=1/√2）→ ZA=51.5Ω、ZB=103Ω、R=106.07Ω、变换段
42.05/59.46Ω（tests/unit/test_w3a_unsplit_bethe.py 钉）。
K=1 退化锚 = 经典等分 Wilkinson：两臂 √2·Z0、R=2·Z0、变换段=Z0（同书
等分节通用结果）。闭式之外另以通用节点导纳分析（λ/4 线 j/Z 倒纳网络）
独立重算全 S 矩阵作裁判（#118：网络解算器与设计闭式互为独立来源）。

守卫：z0_ohm、power_ratio_k 必须为正有限数（K≤0 / 非有限显式拒绝）；
K 无上限（K→∞ 时 Z02→∞、Z03→0 单调连续不产生负值，阻抗可实现性由
调用方按工艺裁定——K≳10 时臂/电阻比 >100:1 已超常规微带可实现域，
结果字段 practical_split=False 如实标注，不拒绝）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator


@register_calculator(
    "unequal_split_wilkinson",
    "不等分功分器：Wilkinson 二路不等分功分器综合（Pozar K 口径 K²=P3/P2）：给定端接 "
    "Z0 与功分比 → 两臂 λ/4 特性阻抗 Z02/Z03 + 隔离电阻 R（含臂端分配 "
    "R2/R3）+ 两输出 λ/4 变换段阻抗 Z04/Z05（Parad–Moynihan 几何均值选型）"
    "+ 中心频率理论分配/极值说明。K=1 退化为等分（臂 √2·Z0、R=2·Z0）；"
    "K≤0 显式拒绝；K 极值下阻抗单调不产生负值（>10:1 如实标 "
    "practical_split=False 不拒绝）。公式出处 Pozar 4th ed §7.3 / "
    "Parad–Moynihan 1965，文献锚 2:1→51.5/103/106.07Ω @50Ω。",
    (("z0_ohm", "float Ω 端接/输入特性阻抗"),
     ("power_ratio_k", "float - 功分比 K（K²=P3/P2，K>0；K>1 端口 3 为"
      "大功率端，K=1 等分）"),
     ("freq_ghz", "float GHz 可选设计频率（给出则附自由空间 λ0/4 参考"
      "长度；不含基板有效介电）")),
    required=("z0_ohm", "power_ratio_k"),
)
def unequal_split_wilkinson(z0_ohm: float, power_ratio_k: float,
                            freq_ghz: float | None = None) -> dict[str, Any]:
    z0 = float(z0_ohm)
    if not (math.isfinite(z0) and z0 > 0.0):
        raise ValueError(
            f"unequal_split_wilkinson: z0_ohm 必须为正有限数，得到 {z0_ohm!r}")
    k = float(power_ratio_k)
    if not math.isfinite(k) or k <= 0.0:
        raise ValueError(
            f"unequal_split_wilkinson: power_ratio_k 必须为正有限数（K²=P3/P2"
            f"口径），得到 {power_ratio_k!r}")

    z02 = z0 * math.sqrt(k * (1.0 + k * k))       # 端口 2 臂（K>1 时=非受惠高阻臂）
    z03 = z0 * math.sqrt((1.0 + k * k) / (k * k * k))  # 端口 3 臂 = Z02/K²
    r_iso = z0 * (1.0 + k * k) / k                 # 隔离电阻（总串联）
    r2 = z0 / k                                    # 端口 2 臂端电阻
    r3 = k * z0                                    # 端口 3 臂端电阻
    z04 = z0 * math.sqrt(k)                        # 端口 2 侧变换段
    z05 = z0 / math.sqrt(k)                        # 端口 3 侧变换段

    # 受惠端口判定与阻抗单调性说明字段
    favored_port = 3 if k > 1.0 else (2 if k < 1.0 else 0)
    p2_frac = 1.0 / (1.0 + k * k)                  # |S21|²
    p3_frac = k * k / (1.0 + k * k)                # |S31|²
    s21_db = 10.0 * math.log10(p2_frac)
    s31_db = 10.0 * math.log10(p3_frac)
    k_max = max(k, 1.0 / k)
    practical = bool(k_max <= 10.0)                # 臂/电阻比 >100:1 超常规可实现域

    freq_note: float | None = None
    if freq_ghz is not None:
        f = float(freq_ghz)
        if not (math.isfinite(f) and f > 0.0):
            raise ValueError(
                f"unequal_split_wilkinson: freq_ghz 必须为正有限数，得到 {freq_ghz!r}")
        freq_note = round(C_MM_GHZ / (4.0 * f), 4)

    return {
        "z0_ohm": round(z0, 6),
        "power_ratio_k": round(k, 9),
        "z02_arm_ohm": round(z02, 4),              # 端口 2 臂 λ/4 阻抗
        "z03_arm_ohm": round(z03, 4),              # 端口 3 臂 λ/4 阻抗
        "r_isolation_ohm": round(r_iso, 4),
        "r2_arm2_ohm": round(r2, 4),               # 臂端分配（总串联合成 R）
        "r3_arm3_ohm": round(r3, 4),
        "z04_transformer_ohm": round(z04, 4),      # 端口 2 侧 λ/4 变换段
        "z05_transformer_ohm": round(z05, 4),      # 端口 3 侧 λ/4 变换段
        "arm_electric_length_deg": 90.0,
        "transformer_electric_length_deg": 90.0,
        "lambda0_quarter_mm": freq_note,
        "favored_port": favored_port,              # 0=等分
        "s21_mag": round(math.sqrt(p2_frac), 9),
        "s31_mag": round(math.sqrt(p3_frac), 9),
        "s21_db": round(s21_db, 6),
        "s31_db": round(s31_db, 6),
        "p2_fraction": round(p2_frac, 12),
        "p3_fraction": round(p3_frac, 12),
        "theory_note": ("f0 理想闭式：全端口匹配、隔离无究大（带宽内随频退化，"
                        "本键只出中心频率设计值）；|S21|²+|S31|²=1"),
        "practical_split": practical,
        "source": "Pozar Microwave Engineering 4ed §7.3; Parad-Moynihan 1965",
    }
