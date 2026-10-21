"""Lange 电桥专属综合内核（架构批 W1-S3 席域，R2_core_tier3 §⑤ F1 设计案）。

出处（经典文献，文末「出处」节转录）：
- lange_synthesize / lange_response：四指 Lange 电桥设计式与四线等效
  两线闭式（J. Lange, "Interdigitated stripline quadrature hybrid",
  IEEE Trans. MTT 17(12), 1969；二级转引 Pozar, Microwave Engineering
  4th ed. §7.6；多导体模式相速口径 W. P. Ou, IEEE Trans. MTT, 1975）。

四指展开型 Lange 电桥的 core 层闭式链——此前全链在
adapters/oe_templates/render_c4.py:202（core 零模块零键零卡）。本模块为
**提升式重构**：``lange_pair_zee_zoo`` / ``lange_equivalent_zee_zoo`` /
``lange_design`` 函数体自 render_c4 原样下沉（逐字节未动），render_c4 改为
消费 core（再导出零改动，#116 不留本地遮蔽副本）；提升前后同参输出逐位一致
（字节级对拍钉 tests/unit/test_w1s3_lange_stepped.py，重构前基线
内部证据目录）。

物理口径（docstring 写死，#1c/#300 出处纪律；与 render_c4 §C4 口径 3 同源）
--------------------------------------------------------
- 四指设计式：耦合 C=10^(−C_dB/20) → 相邻对 (Z0e,Z0o)
  （Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、
  Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))，须 8C²<9）。
- 四线等效两线：Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)；
  耦合 C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)——回代自证（3dB → 相邻对
  (176.216,52.609)Ω → (Ze4,Zo4)=(120.71,20.71)Ω → C=0.707107、Z0=50.000
  逐位闭合，单测钉）。
- 几何链：(Z0e,Z0o) → KJ 二维反解 (w,s)（core/coupled_microstrip.
  coupled_bpf_width_gap_from_zee_zoo，本席同批提升）→ εeff_e/εeff_o（KJ
  正向）→ 指长 λ/4 @ (εeff_e+εeff_o)/2；馈线宽 inverse_width（skrf HJ，
  铁律 1c 唯一线宽口径）。
- 频响键：偶/奇模各自 2 端口线 S 叠加构造 4 端口（(Se+So)/2 口径——与
  calc_families.coupled_line_bpf._section_s4 / adapters._coupled_section_s4
  同构造异路线，测试互证 ≤1e-12 #118）；同步 TEM 档（缺省）取平均 εeff：
  相邻对 KJ εeff_e/εeff_o 不是四线等效模相速（多导体模式，Ou 1975）——拿来
  当非同步相位即建模错误，Lange 只给理想裁判（ratrace/gysel 窄带理想化同
  口径）；**非相邻指耦合忽略（一阶 Lange 设计口径）**如实登记。
- KJ 有效域提示（render_c4 §C4 口径 3 原文）：3dB Lange 于 rogers4350b
  h=0.508 反解 s=0.0386mm → g=s/h=0.076 略低于 KJ 标称有效域下限 0.1
  （如实记录，不拦截）。

边界防撞（#222 triple-grep，2026-10-18 实测）
--------------------------------------------------------
- coupled_line_bpf=耦合谐振器 BPF（交叉口开路端接，非直通 4 口）、
  cline_coupler=单节耦合线定向耦合器模板、multisection_coupler=直通 4 口
  多节级联、edb_templates.lange=HFSS 同链模板级——本族只做**四指交叉连接
  拓扑**的 core 综合/频响键。

出处
----
- D. Pozar, Microwave Engineering 4th ed. §7.6（Lange 节四指设计式与四线
  等效式；章节号以版次为准）。
- J. Lange, "Interdigitated stripline quadrature hybrid", IEEE Trans. MTT
  1969（原始拓扑文献，二级转引）。
- W. P. Ou, "Design equations for an interdigitated directional coupler",
  IEEE Trans. MTT 1975（多导体模式相速口径，非同步修正不做之依据，二级转引）。

守卫：coupling∈(0,1) 且 8C²<9（设计式可达域）；C_dB>0；几何/Z0/εr/h>0；
response 键 Ze4>Zo4>0、频率>0；全部越界显式 ValueError。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

__all__ = [
    "lange_design",
    "lange_equivalent_zee_zoo",
    "lange_pair_zee_zoo",
    "lange_response",
    "lange_synthesize",
]


def lange_pair_zee_zoo(coupling: float, z0_ohm: float = 50.0) -> tuple[float, float]:
    """四指 Lange 设计式（Pozar §7.6 Lange 节）：C → 相邻对 (Z0e, Z0o)。

    Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、
    Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))。
    3dB（C=1/√2）→ (176.216, 52.609)Ω@50Ω（自洽校验见模块头口径）。
    """
    c = float(coupling)
    if not 0.0 < c < 1.0:
        raise ValueError(f"coupling={coupling} 须在 (0,1)")
    if 8.0 * c * c >= 9.0:
        raise ValueError(f"coupling={coupling} 超出设计式可达（须 8C²<9）")
    rt = math.sqrt(9.0 - 8.0 * c * c)
    zee = (float(z0_ohm) * (4.0 * c - 3.0 + rt)
           / (2.0 * c * math.sqrt((1.0 - c) / (1.0 + c))))
    zoo = (float(z0_ohm) * (4.0 * c + 3.0 - rt)
           / (2.0 * c * math.sqrt((1.0 + c) / (1.0 - c))))
    return zee, zoo


def lange_equivalent_zee_zoo(zee_pair: float,
                             zoo_pair: float) -> tuple[float, float]:
    """四指 Lange 相邻对 (Z0e,Z0o) → 四线等效两线 (Ze4, Zo4)（Pozar §7.6）。

    Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)；其耦合
    C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)（test_coupler2_templates 逐位钉）。
    """
    ze = float(zee_pair)
    zo = float(zoo_pair)
    if not ze > zo > 0.0:
        raise ValueError(f"须 Z0e > Z0o > 0，得 ({ze}, {zo})")
    s = ze + zo
    return ze * s / (3.0 * zo + ze), zo * s / (3.0 * ze + zo)


def lange_design(f0_ghz: float = 2.5, z0_ohm: float = 50.0,
                 coupling_db: float = 3.0103, *, er: float = 3.66,
                 h_mm: float = 0.508) -> dict[str, Any]:
    """Lange 电桥综合链：C → 相邻对 (Z0e,Z0o)（Pozar 设计式）→ 四线等效
    (Ze4,Zo4) → KJ (w,s) → 几何（口径见模块头；render_c4.lange_design 同
    函数——本模块为提升式重构单一事实源，adapters 只再导出）。

    返回 {coupling_db, z0_ohm, f0_ghz, zee_pair_ohm, zoo_pair_ohm, ze4_ohm,
    zo4_ohm, c, w_mm, s_mm, ere_e, ere_o, finger_len_mm, w_feed_mm, notes}。
    """
    from rfauto.core.coupled_microstrip import (
        coupled_bpf_width_gap_from_zee_zoo,
        coupled_microstrip_even_odd_ohm,
    )
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="lange", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    c = 10.0 ** (-float(coupling_db) / 20.0)
    zee_p, zoo_p = lange_pair_zee_zoo(c, z0_ohm)
    ze4, zo4 = lange_equivalent_zee_zoo(zee_p, zoo_p)
    w_mm, s_mm = coupled_bpf_width_gap_from_zee_zoo(zee_p, zoo_p, f0_ghz,
                                                    er, h_mm)
    _ze_kj, _zo_kj, ere_e, ere_o = coupled_microstrip_even_odd_ohm(
        w_mm, s_mm, f0_ghz, er, h_mm)
    finger_len = C_MM_GHZ / (4.0 * float(f0_ghz)
                             * math.sqrt(0.5 * (ere_e + ere_o)))
    w_feed = float(inverse_width(float(z0_ohm), float(f0_ghz), stackup)[0])
    notes = [
        f"C={c:.6f} → 相邻对 (Z0e,Z0o)=({zee_p:.3f},{zoo_p:.3f})Ω → 四线等效"
        f" (Ze4,Zo4)=({ze4:.3f},{zo4:.3f})Ω（C 回代={(ze4 - zo4) / (ze4 + zo4):.6f}、"
        f"Z0=√(Ze4·Zo4)={math.sqrt(ze4 * zo4):.3f}Ω）",
        f"KJ 反解 (w,s)=({w_mm:.4f},{s_mm:.4f})mm（g=s/h={s_mm / h_mm:.3f}，"
        f"KJ 标称有效域下限 0.1 提示见段首 3）、指长 λ/4={finger_len:.4f}mm",
        "非相邻指耦合忽略；air-bridge 尺寸为 FDTD 网格尺度选择（真工艺 µm 级）；"
        "假设清单见 openems_templates 文末 §C4 段首 3",
    ]
    return {"coupling_db": float(coupling_db), "z0_ohm": float(z0_ohm),
            "f0_ghz": float(f0_ghz), "zee_pair_ohm": zee_p,
            "zoo_pair_ohm": zoo_p, "ze4_ohm": ze4, "zo4_ohm": zo4, "c": c,
            "w_mm": w_mm, "s_mm": s_mm, "ere_e": ere_e, "ere_o": ere_o,
            "finger_len_mm": finger_len, "w_feed_mm": w_feed, "notes": notes}


# ─── 键 1：lange_synthesize（C, z0, f0, er, h → 几何 + 回代自证）─────────────

@register_calculator(
    "lange_synthesize",
    "Lange 电桥综合：C(dB) → 相邻对 (Z0e,Z0o)（Pozar §7.6 四指设计式）→ "
    "四线等效 (Ze4,Zo4) → KJ 二维反解 (w,s) → 指长 λ/4 @平均 εeff + 50Ω "
    "馈线宽。回代自证 C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4) 逐位闭合；"
    "g=s/h 有效域提示随 notes。锚：3dB → (176.216,52.609)→(120.71,20.71)Ω "
    "教科书闭合链 + (w,s) KJ 正向回代 ≤0.5Ω",
    (("coupling_db", "float dB 目标耦合度（正数口径：3.0103=3dB 电桥）"),
     ("f0_ghz", "float GHz 中心频率（>0，缺省 2.5）"),
     ("z0_ohm", "float Ω 端口/馈线阻抗（>0，缺省 50）"),
     ("er", "float 基板相对介电常数（>1，缺省 3.66 rogers4350b）"),
     ("h_mm", "float mm 基板厚度（>0，缺省 0.508）")),
    required=("coupling_db",),
)
def lange_synthesize(coupling_db: float, f0_ghz: float = 2.5,
                     z0_ohm: float = 50.0, *, er: float = 3.66,
                     h_mm: float = 0.508) -> dict[str, Any]:
    """CALC 键入口（同参透传 lange_design，签名序按设计案 C 优先；零数值）。"""
    return lange_design(float(f0_ghz), float(z0_ohm), float(coupling_db),
                        er=float(er), h_mm=float(h_mm))


# ─── 键 2：lange_response（四线等效两线偶/奇模频响）──────────────────────────

def _tl_s2(zc: float, th: float, z_ref: float) -> tuple[complex, complex]:
    """2 端口均匀线 S（参考 z_ref；与 coupled_line_bpf._tl_s2 同式独立实现）。"""
    gam = (zc - z_ref) / (zc + z_ref)
    e = complex(math.cos(th), -math.sin(th))
    e2 = e * e
    den = 1.0 - gam * gam * e2
    return gam * (1.0 - e2) / den, e * (1.0 - gam * gam) / den


def _lange_s4(ze4: float, zo4: float, the: float, tho: float,
              z_ref: float) -> list[list[complex]]:
    """四线等效两线节 4 端口 S（偶/奇模叠加 (Se±So)/2；端口 1/2=A 近/远、
    3/4=B 近/远；构造恒无耗/互易——测试对 adapters._coupled_section_s4
    双路线互证 ≤1e-12）。"""
    se = _tl_s2(ze4, the, z_ref)
    so = _tl_s2(zo4, tho, z_ref)
    s = [[0j] * 4 for _ in range(4)]
    s[0][0] = s[1][1] = s[2][2] = s[3][3] = (se[0] + so[0]) / 2.0
    s[0][1] = s[1][0] = s[2][3] = s[3][2] = (se[1] + so[1]) / 2.0
    s[0][2] = s[2][0] = s[1][3] = s[3][1] = (se[0] - so[0]) / 2.0
    s[0][3] = s[3][0] = s[1][2] = s[2][1] = (se[1] - so[1]) / 2.0
    return s


@register_calculator(
    "lange_response",
    "Lange 电桥频响裁判：四线等效两线 (Ze4,Zo4) 偶/奇模 2 端口线 S 叠加 "
    "4 端口（构造恒无耗/互易，幅度 dB 列表+守恒/互易残差）。同步 TEM 档"
    "（缺省）取平均 εeff——相邻对 KJ εeff_e/εeff_o 不是四线等效模相速"
    "（多导体模式，Ou 1975），理想裁判口径；非相邻指耦合忽略（一阶设计口径）"
    "如实登记。f0 处 |S21|=|S31|=−3.01dB、S11=S41=0（3dB 配对下）",
    (("ze4_ohm", "float Ω 四线等效偶模阻抗（>zo4_ohm；lange_synthesize 出口）"),
     ("zo4_ohm", "float Ω 四线等效奇模阻抗（>0）"),
     ("finger_len_mm", "float mm 指长（λ/4 口径物理长）"),
     ("ere_e", "float 偶模有效介电常数（≥1）"),
     ("ere_o", "float 奇模有效介电常数（≥1）"),
     ("freq_ghz", "array GHz 频率轴（>0）"),
     ("z_ref_ohm", "float Ω 参考阻抗（>0，缺省 50）"),
     ("synchronous_tem", "bool True=取平均 εeff 理想 TEM 极限（缺省）；"
                         "False=偶/奇模各自 εeff 真非同步相速")),
    required=("ze4_ohm", "zo4_ohm", "finger_len_mm", "ere_e", "ere_o",
              "freq_ghz"),
)
def lange_response(ze4_ohm: float, zo4_ohm: float, finger_len_mm: float,
                   ere_e: float, ere_o: float, freq_ghz: list,
                   z_ref_ohm: float = 50.0,
                   synchronous_tem: bool = True) -> dict[str, Any]:
    """偶/奇模频响（|S|dB 列表面——非复 S 矩阵产出，G15 归类标量面）。"""
    ze = _finite(ze4_ohm, "ze4_ohm")
    zo = _finite(zo4_ohm, "zo4_ohm")
    if not ze > zo > 0.0:
        raise ValueError(
            f"lange_response: 须 ze4_ohm > zo4_ohm > 0，得到 ({ze}, {zo})")
    lf = _finite(finger_len_mm, "finger_len_mm")
    if lf <= 0.0:
        raise ValueError(
            f"lange_response: finger_len_mm 必须 >0，得到 {lf!r}")
    ee = _finite(ere_e, "ere_e")
    eo = _finite(ere_o, "ere_o")
    if min(ee, eo) < 1.0:
        raise ValueError(
            f"lange_response: ere_e/ere_o 须 ≥1，得到 ({ee}, {eo})")
    zr = _finite(z_ref_ohm, "z_ref_ohm")
    if zr <= 0.0:
        raise ValueError(f"lange_response: z_ref_ohm 必须 >0，得到 {zr!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("lange_response: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("lange_response: 频率须 >0")

    ere_avg = 0.5 * (ee + eo)
    l_m = lf * 1e-3
    s11: list[float] = []
    s21: list[float] = []
    s31: list[float] = []
    s41: list[float] = []
    passivity_dev = 0.0
    reciprocity_dev = 0.0
    for f in freqs:
        k0 = 2.0 * math.pi * f * 1e9 / 299792458.0
        if synchronous_tem:
            th = k0 * l_m * math.sqrt(ere_avg)
            the = tho = th
        else:
            the = k0 * l_m * math.sqrt(ee)
            tho = k0 * l_m * math.sqrt(eo)
        s = _lange_s4(ze, zo, the, tho, zr)
        # 幅度 dB 列表（0 基端口 1/2/3/4 = 输入/直通/耦合/隔离）
        s11.append(20.0 * math.log10(max(abs(s[0][0]), 1e-300)))
        s21.append(20.0 * math.log10(max(abs(s[0][1]), 1e-300)))
        s31.append(20.0 * math.log10(max(abs(s[0][2]), 1e-300)))
        s41.append(20.0 * math.log10(max(abs(s[0][3]), 1e-300)))
        # 无耗守恒 |S11|²+|S21|²+|S31|²+|S41|²=1（第一行即全部能量；构造
        # 恒满足，残差随值并列报告）
        p1 = (abs(s[0][0]) ** 2 + abs(s[0][1]) ** 2 + abs(s[0][2]) ** 2
              + abs(s[0][3]) ** 2)
        passivity_dev = max(passivity_dev, abs(p1 - 1.0))
        for i in range(4):
            for j in range(4):
                reciprocity_dev = max(reciprocity_dev, abs(s[i][j] - s[j][i]))
    return {
        "n_points": len(freqs),
        "freq_ghz": freqs,
        "s11_db": s11,
        "s21_db": s21,
        "s31_db": s31,
        "s41_db": s41,
        "energy_residual_max": passivity_dev,
        "reciprocity_residual_max": reciprocity_dev,
        "ere_avg": ere_avg,
        "synchronous_tem": bool(synchronous_tem),
        "notes": [
            "端口语义：1=输入/2=直通/3=耦合（同侧近端）/4=隔离（远端）；"
            "f0 处理想 3dB 配对 |S21|=|S31|=−3.01dB、S11=S41=0、S31 与输入"
            "同相（+1/√2）、S21 滞后 90°（−j/√2）",
            "同步 TEM 档取平均 εeff：相邻对 KJ εeff_e/εeff_o 不是四线等效模"
            "相速（多导体模式，Ou 1975）——理想裁判口径，与 fake 通道"
            "（synchronous_tem=True）同口径",
            "非相邻指耦合忽略（一阶 Lange 设计口径）；桥缝耦合寄生于理想"
            "裁判之外（render_c4 §C4 口径 3）",
        ],
    }
