"""c4 耦合器族（cline_coupler/branchline_2sect/lange）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
from .closedform import _fmt_list, coupled_bpf_width_gap_from_zee_zoo
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL
from .render_coupled_bpf import _coupled_section_s4
from .render_hairpin import coupled_microstrip_even_odd_ohm

# ═══════════════════════════════════════════════════════════════════════════════
# §C4 耦合器族 II 本体段：cline_coupler（耦合线定向耦合器）/ branchline_2sect
# （两节分支线）/ lange（展开型 Lange 电桥）——理论核验轮 + 离线几何审计
# （2026-09-16 增量；正式注册进 TEMPLATE_META/TEMPLATE_NOMINAL，见段末注册块）
# ═══════════════════════════════════════════════════════════════════════════════
# ── 理论核验轮（#206 纪律；口径/来源逐条，裁判=独立来源不自证）──
# 1) 耦合线定向耦合器（Pozar《Microwave Engineering》4th ed. §7.6 耦合线定向
#    耦合器节；章节号以版次为准）：电压耦合系数 C=10^(−C_dB/20)；匹配条件
#    Z0²=Z0e·Z0o 下 Z0e=Z0√((1+C)/(1−C))、Z0o=Z0√((1−C)/(1+C))、
#    C=(Z0e−Z0o)/(Z0e+Z0o)；频响（同步 TEM）S31=jC·sinθ/(√(1−C²)cosθ+j·sinθ)、
#    S21=√(1−C²)/(√(1−C²)cosθ+j·sinθ)，S11=S41=0；θ=90° 处 |S31|=C（同相）、
#    S21=−j√(1−C²)。端口约定（后向波耦合器）：1=输入（线 A 近端）、2=直通
#    （线 A 远端）、3=耦合（线 B 近端，与输入同侧）、4=隔离（线 B 远端）。
#    **独立互检**：偶/奇模装配 _coupled_section_s4（coupled_bpf 段既有内核，
#    无耗/互易由构造保证）在 θ=60/75/90/110° 与 Pozar 闭式逐位一致
#    （test_coupler2_templates 钉住）。
#    微带非同步残差（εeff_e≠εeff_o，真 KJ 相速）：名义 10dB 设计 @f0 实测
#    |S31|=−10.045dB、S41=−23.3dB、S11=−32.9dB（定向性 ≈13dB——Pozar 明述的
#    微带耦合线固有极限，未做相速补偿/锯齿缝；fake 默认走真 KJ 相速
#    （coupled_bpf 同口径），synchronous_tem=True 为理想裁判极限，两路单测各钉）。
# 2) 两节分支线（Pozar 4th ed. §7.5 分支线偶/奇模分析推广至两节；Levy & Lind,
#    "Synthesis of Symmetrical Branch-Guide Directional Couplers", IEEE Trans.
#    MTT-16(2), 1968 对称分支导综合口径；Microwaves101 "Two-section branchline
#    coupler" 页二级参照）：沿水平中面二分——支臂切成 λ/8 半桩（偶模 PMC=
#    开路桩 +j·Y_b·tan(θ_b/2)、奇模 PEC=短路桩 −j·Y_b·cot(θ_b/2)），半电路
#    ABCD = 桩(Y_b1)·线(Z_a)·桩(Y_b2)·线(Z_a)·桩(Y_b1)；S11=(Γe+Γo)/2、
#    S21=(Te+To)/2（直通=P2 同线远端）、S31=(Te−To)/2（耦合=P3 对角）、
#    S41=(Γe−Γo)/2（隔离=P4 同侧）。**映射校验**：单节 (Z_a=Z0/√2, Z_b=Z0)
#    代入同式复现 Pozar S21=−j/√2、S31=−1/√2、S11=S41≈0（|S11|~1e-17，
#    单测钉住）。**f0 处解为单参数族**（本轮多起点 least_squares 数值解 +
#    解析归纳）：Z_b1=(1+√2)Z0（外支臂，120.71Ω@50Ω）、Z_b2=√2·Z_a²/Z0
#    （中支臂）、Z_a 自由——Microwaves101 独立表述逐字一致（"end impedances
#    must remain at [1+√2]×Z0 … Z3=√2×Z1²/Z0"）。标称取 Pozar 经典点 Z_a=Z0
#    → (50, 120.71, 70.71)Ω；理想 ±1dB 均分带宽 35.0%（本轮扫描 0.350，
#    Microwaves101 同页 35%）vs 单节 25.8%，−20dB 匹配/隔离带宽 24.2% vs
#    10.4%（两节 ≥ 单节，单测钉住）。最平坦匹配解 Z_a≈0.72·Z0（|S11|² 二阶
#    导零点）作 main_z_ratio 选项保留。f0 处 S21=−1/√2（两 λ/4=λ/2，−180°）、
#    S31=+j/√2（+90°），正交。**几何固有偏差**（gysel 桥带同类）：外/中支臂
#    Z 不同 → εeff 不同 → λ/4 物理长不同（本叠层差 ≈3.1%），矩形拓扑只有
#    一个支臂跨度，取两支臂 λ/4 的算术平均（各 ≈±1.5%，二阶），如实记录。
# 3) Lange 电桥（Pozar 4th ed. §7.6 Lange 节，四指展开型 fig 7.33(b)；原始
#    J. Lange, IEEE-MTT-S 1969；Microwaves101 "Lange Couplers" 页二级参照：
#    "through 与 input 有 DC 连接"）：相邻对 (Z0e,Z0o) → 四线等效两线
#    Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)，耦合
#    C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)；设计式（反解，含 √(9−8C²) 项）
#    Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、Z0o=Z0(4C+3−√(9−8C²))/
#    (2C√((1+C)/(1−C)))。**自洽校验**：3dB（C=1/√2）→ 相邻对
#    (176.216, 52.609)Ω（文献常引 ≈176/52.6 同值）→ 四线换算回 Ze4=120.71、
#    Zo4=20.71 → C=0.707107、Z0=50.000（逐位闭合，单测钉住）。等效两线
#    (Ze4,Zo4) 代入口径 1 偶/奇模内核 → f0 处 |S21|=|S31|=−3.01dB、
#    S31=+1/√2（耦合同相）、S21=−j/√2（直通滞后 90°）、S11=S41=0。
#    几何：展开型（交替指两端各以 air-bridge 并联=Pozar 等效两线模型精确
#    成立的拓扑）；外指承馈（P1/P2=指 1 近/远端、P3/P4=指 4 近/远端，
#    {1,2}=网络 A、{3,4}=网络 B，两网络 DC 隔离）。**相速口径**：fake 默认
#    synchronous_tem=True——相邻对 KJ εeff_e/εeff_o 不是四线等效模相速
#    （多导体模式，Ou 1975），拿来当非同步相位即建模错误；Lange 只给理想
#    裁判（ratrace/gysel 窄带理想化同口径）。KJ 有效域提示：3dB Lange 于
#    rogers4350b h=0.508 反解 s=0.0386mm → g=s/h=0.076 略低于 KJ 标称有效
#    域下限 0.1（如实记录）；单指 w=0.167mm（u=0.33）在域内。非相邻指耦合
#    忽略（一阶 Lange 设计口径）。
# 4) 线宽全部 skrf HJ 精算（inverse_width/forward_z0，铁律 1c）；(Z0e,Z0o)→
#    (w,s) 走 coupled_bpf_width_gap_from_zee_zoo（KJ 二维反解，既有内核）。
# 5) 渲染：三模板四端口 MSLPort 全建 + excite_port 轮转
#    （_FOUR_PORT_ROTATION_TEMPLATES，9 列单激励 CSV，openems_rotation 进程
#    隔离装配 #208）；端口面贴 PML 边界（铁律 §3）；50Ω 馈线比耦合结构宽 →
#    馈线外推 + 横向搭接段（同心直连必短路），搭接段为 bend 族同类不连续性
#    （进冒烟偏差项，不进闭式）。lange air-bridge = 抬高薄金属
#    （z∈[H+g, H+g+t]）+ 竖直立柱（z∈[H, H+g]，不落 z=0 地面——落地即对地
#    短路）；同端两网络桥错位、两端分置，#212 bbox 连通审计恰判"两组 DC
#    隔离、组内全导通"。

_C4_C_MM_GHZ = 299.792458
_C4_COUPLER_TEMPLATES: tuple[str, ...] = ("cline_coupler", "branchline_2sect",
                                          "lange")
# 馈线内缘净距（mm）：两 50Ω 馈线并行段的耦合随缝宽指数衰减，5mm（≈10h）
# 下 ~50mm 并行长度串扰 <−45dB 量级（一阶口径）；同心直连（缝 0）必短路。
_C4_FEED_CLEAR_MM = 5.0
_C4_LANGE_BRIDGE_GAP_MM = 0.1        # 桥底面离金属面高度 g（mm）
_C4_LANGE_BRIDGE_T_MM = 0.05         # 桥金属厚 t（mm）
_C4_LANGE_BRIDGE_W_MM = 0.3          # 桥沿 y 宽 wb（mm）
_C4_LANGE_BRIDGE_INSET_MM = 0.25     # 端侧首桥中心离指端距离（mm）
_C4_LANGE_BRIDGE_STAGGER_MM = 0.55   # 同端 A/B 桥中心距（错位 > wb+净距）


def coupled_line_zee_zoo(coupling_db: float,
                         z0_ohm: float = 50.0) -> tuple[float, float, float]:
    """耦合线定向耦合器综合（Pozar §7.6）：C(dB) → (Z0e, Z0o, C)。

    C=10^(−C_dB/20)；Z0e=Z0√((1+C)/(1−C))、Z0o=Z0√((1−C)/(1+C))
    （匹配条件 Z0e·Z0o=Z0² 由构造保证）。C_dB>0（10 → 10dB 耦合器）。
    """
    c = 10.0 ** (-float(coupling_db) / 20.0)
    if not 0.0 < c < 1.0:
        raise ValueError(f"coupling_db={coupling_db} 须 >0（C∈(0,1)）")
    zee = float(z0_ohm) * math.sqrt((1.0 + c) / (1.0 - c))
    zoo = float(z0_ohm) * math.sqrt((1.0 - c) / (1.0 + c))
    return zee, zoo, c


def lange_pair_zee_zoo(coupling: float, z0_ohm: float = 50.0) -> tuple[float, float]:
    """四指 Lange 设计式（Pozar §7.6 Lange 节）：C → 相邻对 (Z0e, Z0o)。

    Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、
    Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))。
    3dB（C=1/√2）→ (176.216, 52.609)Ω@50Ω（自洽校验见段首口径 3）。
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


def branchline_2sect_impedances(z0_ohm: float = 50.0,
                                main_z_ratio: float = 1.0) -> tuple[float, float, float]:
    """两节分支线 f0 阻抗族（段首口径 2）：(Z_a, Z_b1, Z_b2)。

    Z_a=main_z_ratio·Z0（主线节）、Z_b1=(1+√2)Z0（外支臂）、
    Z_b2=√2·Z_a²/Z0（中支臂）。f0 处该族对任意 main_z_ratio>0 均给理想
    3dB 正交响应（匹配/隔离=0）；main_z_ratio=1 为 Pozar 经典点。
    """
    if float(main_z_ratio) <= 0.0:
        raise ValueError(f"main_z_ratio={main_z_ratio} 须 >0")
    za = float(main_z_ratio) * float(z0_ohm)
    zb1 = (1.0 + math.sqrt(2.0)) * float(z0_ohm)
    zb2 = math.sqrt(2.0) * za * za / float(z0_ohm)
    return za, zb1, zb2


def cline_coupler_design(coupling_db: float = 10.0, f0_ghz: float = 2.5,
                         z0_ohm: float = 50.0, *, er: float = 3.66,
                         h_mm: float = 0.508) -> dict[str, Any]:
    """耦合线定向耦合器综合链：C(dB) → (Z0e,Z0o) → KJ (w,s) → 几何。

    确定性映射（数值只在内核；口径见段首 1/4）。返回 {coupling_db, z0_ohm,
    f0_ghz, zee_ohm, zoo_ohm, c, w_mm, s_mm, zee_kj, zoo_kj, ere_e, ere_o,
    ere_avg, lc_mm, w_feed_mm, notes}。lc = λ/4 @ (εeff_e+εeff_o)/2（微带
    耦合段平均 εeff 口径，coupled_bpf 同源）。
    """
    from rfauto.core.synthesis import Stackup, inverse_width

    stackup = Stackup(name="cline_coupler", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    zee, zoo, c = coupled_line_zee_zoo(coupling_db, z0_ohm)
    w_mm, s_mm = coupled_bpf_width_gap_from_zee_zoo(zee, zoo, f0_ghz, er, h_mm)
    ze, zo, ere_e, ere_o = coupled_microstrip_even_odd_ohm(w_mm, s_mm, f0_ghz,
                                                           er, h_mm)
    ere_avg = 0.5 * (ere_e + ere_o)
    lc_mm = _C4_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(ere_avg))
    w_feed = float(inverse_width(float(z0_ohm), float(f0_ghz), stackup)[0])
    notes = [
        f"C={c:.5f}（{coupling_db}dB）→ (Z0e,Z0o)=({zee:.3f},{zoo:.3f})Ω"
        f"（Z0e·Z0o={zee * zoo:.1f}Ω²=Z0²）",
        f"KJ 二维反解 (w,s)=({w_mm:.4f},{s_mm:.4f})mm，回代"
        f" (Z0e,Z0o)=({ze:.3f},{zoo:.3f})Ω、εeff_e={ere_e:.4f}/"
        f"εeff_o={ere_o:.4f} → λ/4={lc_mm:.4f}mm",
        "非同步残差与假设清单见 openems_templates 文末 §C4 段首 1/5",
    ]
    return {"coupling_db": float(coupling_db), "z0_ohm": float(z0_ohm),
            "f0_ghz": float(f0_ghz), "zee_ohm": zee, "zoo_ohm": zoo, "c": c,
            "w_mm": w_mm, "s_mm": s_mm, "zee_kj": ze, "zoo_kj": zo,
            "ere_e": ere_e, "ere_o": ere_o, "ere_avg": ere_avg,
            "lc_mm": lc_mm, "w_feed_mm": w_feed, "notes": notes}


def lange_design(f0_ghz: float = 2.5, z0_ohm: float = 50.0,
                 coupling_db: float = 3.0103, *, er: float = 3.66,
                 h_mm: float = 0.508) -> dict[str, Any]:
    """Lange 电桥综合链：C → 相邻对 (Z0e,Z0o)（Pozar 设计式）→ 四线等效
    (Ze4,Zo4) → KJ (w,s) → 几何（口径见段首 3/4）。

    返回 {coupling_db, z0_ohm, f0_ghz, zee_pair_ohm, zoo_pair_ohm, ze4_ohm,
    zo4_ohm, c, w_mm, s_mm, ere_e, ere_o, finger_len_mm, w_feed_mm, notes}。
    """
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
    finger_len = _C4_C_MM_GHZ / (4.0 * float(f0_ghz)
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


def branchline_2sect_design(f0_ghz: float = 2.5, z0_ohm: float = 50.0, *,
                            main_z_ratio: float = 1.0, er: float = 3.66,
                            h_mm: float = 0.508) -> dict[str, Any]:
    """两节分支线综合链：f0 阻抗族（段首口径 2）→ HJ 线宽 → λ/4 长度。

    main_z_ratio=1（Pozar 经典点）。支臂物理长 = 外/中支臂 λ/4 的算术平均
    （两支臂 εeff 不同 → λ/4 不同，矩形拓扑单跨度的固有二阶偏差 ≈±1.5%，
    段首口径 2）。返回 {f0_ghz, z0_ohm, za_ohm, zb1_ohm, zb2_ohm, w_main_mm,
    w_out_mm, w_mid_mm, w_feed_mm, sect_len_mm, branch_len_mm, ere_main,
    ere_out, ere_mid, notes}。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    stackup = Stackup(name="branchline_2sect", epsilon_r=float(er),
                      thickness_mm=float(h_mm))
    za, zb1, zb2 = branchline_2sect_impedances(z0_ohm, main_z_ratio)
    lengths: list[float] = []
    eres: list[float] = []
    widths: list[float] = []
    for z in (za, zb1, zb2):
        w, _z_act, _st = inverse_width(z, float(f0_ghz), stackup)
        _z0v, ere = forward_z0(w, float(f0_ghz), stackup)
        widths.append(w)
        eres.append(ere)
        lengths.append(_C4_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(ere)))
    w_feed = float(inverse_width(float(z0_ohm), float(f0_ghz), stackup)[0])
    notes = [
        f"两节族：Z_a={za:.2f}Ω（×{main_z_ratio}）、Z_b1=(1+√2)Z0={zb1:.2f}Ω、"
        f"Z_b2=√2·Z_a²/Z0={zb2:.2f}Ω（单参数族推导与 Microwaves101 独立表述"
        "一致，段首口径 2）",
        "HJ 线宽 (w_main,w_out,w_mid)=" + _fmt_list(widths, 4)
        + "mm，εeff=" + _fmt_list(eres, 4),
        f"λ/4: 主线 {lengths[0]:.4f}、外支臂 {lengths[1]:.4f}、中支臂 "
        f"{lengths[2]:.4f}mm → 支臂跨度取均值 "
        f"{0.5 * (lengths[1] + lengths[2]):.4f}mm（固有二阶偏差 "
        f"≈±{(lengths[1] - lengths[2]) / 2:.2%}，段首口径 2）",
    ]
    return {"f0_ghz": float(f0_ghz), "z0_ohm": float(z0_ohm), "za_ohm": za,
            "zb1_ohm": zb1, "zb2_ohm": zb2,
            "w_main_mm": widths[0], "w_out_mm": widths[1],
            "w_mid_mm": widths[2], "w_feed_mm": w_feed,
            "sect_len_mm": lengths[0],
            "branch_len_mm": 0.5 * (lengths[1] + lengths[2]),
            "ere_main": eres[0], "ere_out": eres[1], "ere_mid": eres[2],
            "notes": notes}


def coupled_line_coupler_sparams(
    freq_ghz: Any, zee_ohm: float, zoo_ohm: float, len_mm: float,
    ere_e: float, ere_o: float, *, synchronous_tem: bool = False,
    z_ref: float = 50.0,
) -> np.ndarray:
    """耦合线定向耦合器偶/奇模裁判（(n,4,4)；cline_coupler 与 lange 共用）。

    每耦合段 = 偶/奇模 2 端口叠加构造 4 端口（_coupled_section_s4，无耗/
    互易由构造保证）：端口 1/2=线 A 近/远端（输入/直通）、3/4=线 B 近/远端
    （耦合/隔离）。θ_e/θ_o = k0·l·√εeff_e / k0·l·√εeff_o（真非同步相速，
    coupled_bpf 同口径）；synchronous_tem=True 全段取平均 εeff（理想 TEM
    极限：f0 处精确 S11=S41=0、|S31|=C——教科书闭式裁判）。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    l_m = float(len_mm) * 1e-3
    out = _np.zeros((len(freqs), 4, 4), dtype=complex)
    for k, f_ghz in enumerate(freqs):
        k0 = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        if synchronous_tem:
            th = k0 * l_m * math.sqrt(0.5 * (float(ere_e) + float(ere_o)))
            the = tho = th
        else:
            the = k0 * l_m * math.sqrt(float(ere_e))
            tho = k0 * l_m * math.sqrt(float(ere_o))
        out[k] = _coupled_section_s4(zee_ohm, the, zoo_ohm, tho, z_ref)
    return out


def branchline_2sect_sparams(
    freq_ghz: Any, za_ohm: float, zb1_ohm: float, zb2_ohm: float,
    sect_len_mm: float, branch_len_mm: float, ere_main: float,
    ere_out: float, ere_mid: float, *, z_ref: float = 50.0,
) -> np.ndarray:
    """两节分支线偶/奇模二分裁判（(n,4,4)；闭式见段首口径 2）。

    半电路 ABCD(f) = 桩(Y_b1,θ_b1/2)·线(Z_a,θ_a)·桩(Y_b2,θ_b2/2)·线(Z_a,θ_a)
    ·桩(Y_b1,θ_b1/2)；各段电长按自身物理长+εeff 独立评估（几何参数变化有
    真实频响）。Γ/T 组合 S11=(Γe+Γo)/2、S21=(Te+To)/2、S31=(Te−To)/2、
    S41=(Γe−Γo)/2，矩形双镜面对称填满 4×4。
    """
    import numpy as _np

    freqs = _np.atleast_1d(_np.asarray(freq_ghz, dtype=float))
    la = float(sect_len_mm) * 1e-3
    lb = float(branch_len_mm) * 1e-3
    za, zb1, zb2 = float(za_ohm), float(zb1_ohm), float(zb2_ohm)
    out = _np.zeros((len(freqs), 4, 4), dtype=complex)

    def _line(zc: float, th: float) -> _np.ndarray:
        c, s = math.cos(th), math.sin(th)
        return _np.array([[c, 1j * zc * s], [1j * s / zc, c]])

    def _shunt(y: complex) -> _np.ndarray:
        return _np.array([[1.0, 0.0], [y, 1.0]])

    for k, f_ghz in enumerate(freqs):
        k0 = 2.0 * math.pi * float(f_ghz) * 1e9 / 299792458.0
        th_a = k0 * la * math.sqrt(float(ere_main))
        th_b1 = 0.5 * k0 * lb * math.sqrt(float(ere_out))   # 半支臂 λ/8
        th_b2 = 0.5 * k0 * lb * math.sqrt(float(ere_mid))
        modes = []
        for even in (True, False):
            y1 = (1j / zb1 * math.tan(th_b1) if even
                  else -1j / zb1 / math.tan(th_b1))
            y2 = (1j / zb2 * math.tan(th_b2) if even
                  else -1j / zb2 / math.tan(th_b2))
            m = (_shunt(y1) @ _line(za, th_a) @ _shunt(y2) @ _line(za, th_a)
                 @ _shunt(y1))
            a_, b_, c_, d_ = m[0, 0], m[0, 1], m[1, 0], m[1, 1]
            # ABCD→S（Pozar Table 4.2，参考阻抗 z_ref；B 阻抗形/C 导纳形）：
            # 阻抗按实际 Ω 入矩阵，归一化在此处一次完成（曾误按 Z0=1 归一
            # → S11≡0dB 全反射，fake 预跑抓出）
            den = a_ + b_ / z_ref + c_ * z_ref + d_
            modes.append(((a_ + b_ / z_ref - c_ * z_ref - d_) / den, 2.0 / den))
        ge, te = modes[0]
        go, to = modes[1]
        s = _np.zeros((4, 4), dtype=complex)
        s[0, 0] = s[1, 1] = s[2, 2] = s[3, 3] = (ge + go) / 2.0
        s[0, 1] = s[1, 0] = s[2, 3] = s[3, 2] = (te + to) / 2.0  # 直通对
        s[0, 2] = s[2, 0] = s[1, 3] = s[3, 1] = (te - to) / 2.0  # 耦合对
        s[0, 3] = s[3, 0] = s[1, 2] = s[2, 1] = (ge - go) / 2.0  # 隔离对
        out[k] = s
    return out


def _c4_feed_boxes(
    x_feed: float, wf: float, y_line_end: float, board: float,
    x_line: float, side: int, prefix: str,
) -> tuple[list[tuple[str, float, float, float, float, float, float]], float]:
    """馈线 + 横向搭接段盒清单（米；段首口径 5）。

    side=−1 近端（y<0）/ +1 远端；搭接段从馈线外缘跨到耦合结构中心线
    x_line（保重叠连通、离对侧结构 ≥ 线心距）。返回 (boxes, meas_shift)。
    z 仅存 0 占位（调用方统一填金属面 zm）。
    """
    y_inner = y_line_end + side * wf
    y_outer = float(board) * (1.0 if side > 0 else -1.0)
    lo_y, hi_y = min(y_inner, y_outer), max(y_inner, y_outer)
    if x_feed < 0.0:
        jx_lo, jx_hi = x_feed - wf / 2.0, x_line
    else:
        jx_lo, jx_hi = x_line, x_feed + wf / 2.0
    boxes = [(f"{prefix}_feed", x_feed - wf / 2.0, lo_y, 0.0,
              x_feed + wf / 2.0, hi_y, 0.0)]
    jy_lo, jy_hi = (y_inner, y_line_end) if side < 0 else (y_line_end, y_inner)
    boxes.append((f"{prefix}_jog", jx_lo, jy_lo, 0.0, jx_hi, jy_hi, 0.0))
    return boxes, (float(board) - abs(y_inner)) / 3.0


def _c4_layout(template: str, p: dict[str, Any]) -> dict[str, Any]:
    """§C4 三模板几何单一事实源（米）——render/_near_points/geometry_spec 共用。

    盒元组 = (名, x0, y0, z0, x1, y1, z1)；z 绝对高（0=地面、zm=金属面，
    官方顶面口径）；lange 桥 z∈[zm+g, zm+g+t]、立柱 z∈[zm, zm+g]（不落
    z=0 地面——落地即对地短路）。端口 start/stop=MSLPort 面（start 贴板边）。
    """
    zm = float(_DEFAULT_SUB["h_mm"]) * 1e-3
    board = 0.060
    if template == "cline_coupler":
        w = float(p.get("w_mm", CLINE_COUPLER_NOMINAL["w_mm"])) * 1e-3
        s = float(p.get("gap_mm", CLINE_COUPLER_NOMINAL["gap_mm"])) * 1e-3
        lc = float(p.get("coupled_len_mm",
                         CLINE_COUPLER_NOMINAL["coupled_len_mm"])) * 1e-3
        wf = float(p.get("w_feed_mm",
                         CLINE_COUPLER_NOMINAL["w_feed_mm"])) * 1e-3
        if min(w, s, lc, wf) <= 0.0:
            raise ValueError("cline_coupler 几何须 >0")
        clear = _C4_FEED_CLEAR_MM * 1e-3
        d = w + s
        xa, xb = -d / 2.0, d / 2.0
        xf_a = -(wf / 2.0 + clear / 2.0)
        xf_b = -xf_a
        boxes: list[tuple[str, float, float, float, float, float, float]] = [
            ("line_a", xa - w / 2.0, -lc / 2.0, zm, xa + w / 2.0, lc / 2.0, zm),
            ("line_b", xb - w / 2.0, -lc / 2.0, zm, xb + w / 2.0, lc / 2.0, zm),
        ]
        ports: list[dict[str, Any]] = []
        for (nr, x_line, x_feed, y_end, side, label) in (
                (1, xa, xf_a, -lc / 2.0, -1, "输入（线 A 近端）"),
                (2, xa, xf_a, lc / 2.0, +1, "直通（线 A 远端）"),
                (3, xb, xf_b, -lc / 2.0, -1, "耦合（线 B 近端）"),
                (4, xb, xf_b, lc / 2.0, +1, "隔离（线 B 远端）")):
            fb, meas = _c4_feed_boxes(x_feed, wf, y_end, board, x_line, side,
                                      f"feed_p{nr}")
            for bx in fb:
                boxes.append((bx[0], bx[1], bx[2], zm, bx[4], bx[5], zm))
            if side < 0:
                start = (x_feed + wf / 2.0, -board)
                stop = (x_feed - wf / 2.0, y_end - wf)
            else:
                start = (x_feed - wf / 2.0, board)
                stop = (x_feed + wf / 2.0, y_end + wf)
            ports.append({"nr": nr, "label": label,
                          "start": [start[0], start[1], zm],
                          "stop": [stop[0], stop[1], zm],
                          "prop_dir": "y", "meas_shift": meas})
        return {"boxes": boxes, "ports": ports, "z_lines": []}
    if template == "branchline_2sect":
        wm = float(p.get("w_main_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_main_mm"])) * 1e-3
        wo = float(p.get("w_out_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_out_mm"])) * 1e-3
        wc = float(p.get("w_mid_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_mid_mm"])) * 1e-3
        la = float(p.get("sect_len_mm",
                         BRANCHLINE_2SECT_NOMINAL["sect_len_mm"])) * 1e-3
        lb = float(p.get("branch_len_mm",
                         BRANCHLINE_2SECT_NOMINAL["branch_len_mm"])) * 1e-3
        wf = float(p.get("w_feed_mm",
                         BRANCHLINE_2SECT_NOMINAL["w_feed_mm"])) * 1e-3
        if min(wm, wo, wc, la, lb, wf) <= 0.0:
            raise ValueError("branchline_2sect 几何须 >0")
        yt, yb = lb / 2.0, -lb / 2.0
        boxes = [
            ("arm_top（Z_a 主线）", -la - wo / 2.0, yt - wm / 2.0, zm,
             la + wo / 2.0, yt + wm / 2.0, zm),
            ("arm_bottom（Z_a 主线）", -la - wo / 2.0, yb - wm / 2.0, zm,
             la + wo / 2.0, yb + wm / 2.0, zm),
            ("branch_out_left（Z_b1 外支臂）", -la - wo / 2.0, yb, zm,
             -la + wo / 2.0, yt, zm),
            ("branch_out_right（Z_b1 外支臂）", la - wo / 2.0, yb, zm,
             la + wo / 2.0, yt, zm),
            ("branch_mid（Z_b2 中支臂）", -wc / 2.0, yb, zm, wc / 2.0, yt, zm),
        ]
        meas = (board - la) / 3.0
        ports = []
        for (nr, y_c, label) in ((1, yt, "输入（左上）"),
                                 (2, yt, "直通（右上）"),
                                 (3, yb, "耦合（右下）"),
                                 (4, yb, "隔离（左下）")):
            sign = 1.0 if nr in (2, 3) else -1.0
            if sign > 0:
                x_face, x_joint = board, la
                start = (board, y_c - wf / 2.0)
                stop = (la, y_c + wf / 2.0)
            else:
                x_face, x_joint = -board, -la
                start = (-board, y_c + wf / 2.0)
                stop = (-la, y_c - wf / 2.0)
            boxes.append((f"feed_p{nr}", min(x_face, x_joint),
                          y_c - wf / 2.0, zm, max(x_face, x_joint),
                          y_c + wf / 2.0, zm))
            ports.append({"nr": nr, "label": label,
                          "start": [start[0], start[1], zm],
                          "stop": [stop[0], stop[1], zm],
                          "prop_dir": "x", "meas_shift": meas})
        return {"boxes": boxes, "ports": ports, "z_lines": []}
    if template == "lange":
        w = float(p.get("w_mm", LANGE_NOMINAL["w_mm"])) * 1e-3
        s = float(p.get("gap_mm", LANGE_NOMINAL["gap_mm"])) * 1e-3
        lf = float(p.get("finger_len_mm",
                         LANGE_NOMINAL["finger_len_mm"])) * 1e-3
        wf = float(p.get("w_feed_mm", LANGE_NOMINAL["w_feed_mm"])) * 1e-3
        if min(w, s, lf, wf) <= 0.0:
            raise ValueError("lange 几何须 >0")
        d = w + s
        xs = [(k - 1.5) * d for k in range(4)]    # 四指中心（外指承馈）
        # c4-去桥单变量对照旋钮（wf:c4-debridge，2026-09-19）：params["_bridge"]
        # =0 → 桥金属盒+立柱盒全部不渲染、z_lines 同步清空（桥面 z 网格线随之
        # 消失，_near_y 亦不再含桥 y 缘——单变量="无 air-bridge"）；缺省 1=逐
        # 字节不变（render_base_lange.py 快照自证）。关位 0 是合法值，禁用
        # `or` 缺省惯语（#117 falsy 陷阱）。去桥后指 2/3 无馈无桥=悬浮 PEC
        # （FDTD 良定：PEC 感应电流合法、无需 DC 通路）；连通性/网格逐条审计
        # 归档 runs/c4_debridge/。
        _bridge_on = bool(p.get("_bridge", 1))
        gb = _C4_LANGE_BRIDGE_GAP_MM * 1e-3
        tb = _C4_LANGE_BRIDGE_T_MM * 1e-3
        wb = _C4_LANGE_BRIDGE_W_MM * 1e-3
        ins = _C4_LANGE_BRIDGE_INSET_MM * 1e-3
        stag = _C4_LANGE_BRIDGE_STAGGER_MM * 1e-3
        boxes = [(f"finger_{k + 1}", xs[k] - w / 2.0, -lf / 2.0, zm,
                  xs[k] + w / 2.0, lf / 2.0, zm) for k in range(4)]
        # 桥（两端 × 网络 A=指 1/3、B=指 2/4）：同端 A/B 错位（bbox 不交，
        # #212 审计判两组 DC 隔离）；桥底 z=zm+g、立柱 z∈[zm, zm+g] 不落地
        for (yk, fingers, tag) in (
                (-lf / 2.0 + ins, (0, 2), "a"),
                (-lf / 2.0 + ins + stag, (1, 3), "b"),
                (lf / 2.0 - ins - stag, (1, 3), "b2"),
                (lf / 2.0 - ins, (0, 2), "a2")):
            x_lo = min(xs[fingers[0]], xs[fingers[1]]) - w / 2.0
            x_hi = max(xs[fingers[0]], xs[fingers[1]]) + w / 2.0
            boxes.append((f"bridge_{tag}", x_lo, yk - wb / 2.0, zm + gb,
                          x_hi, yk + wb / 2.0, zm + gb + tb))
            for k in fingers:
                boxes.append((f"post_{tag}_f{k + 1}", xs[k] - w / 2.0,
                              yk - wb / 2.0, zm, xs[k] + w / 2.0,
                              yk + wb / 2.0, zm + gb))
        clear = _C4_FEED_CLEAR_MM * 1e-3
        xf_a = -(wf / 2.0 + clear / 2.0)
        xf_b = -xf_a
        ports = []
        for (nr, k_f, y_end, x_feed, side, label) in (
                (1, 0, -lf / 2.0, xf_a, -1, "输入（指1近端）"),
                (2, 0, lf / 2.0, xf_a, +1, "直通（指1远端）"),
                (3, 3, -lf / 2.0, xf_b, -1, "耦合（指4近端）"),
                (4, 3, lf / 2.0, xf_b, +1, "隔离（指4远端）")):
            fb, meas = _c4_feed_boxes(x_feed, wf, y_end, board, xs[k_f],
                                      side, f"feed_p{nr}")
            for bx in fb:
                boxes.append((bx[0], bx[1], bx[2], zm, bx[4], bx[5], zm))
            if side < 0:
                start = (x_feed + wf / 2.0, -board)
                stop = (x_feed - wf / 2.0, y_end - wf)
            else:
                start = (x_feed - wf / 2.0, board)
                stop = (x_feed + wf / 2.0, y_end + wf)
            ports.append({"nr": nr, "label": label,
                          "start": [start[0], start[1], zm],
                          "stop": [stop[0], stop[1], zm],
                          "prop_dir": "y", "meas_shift": meas})
        if not _bridge_on:
            boxes = [b for b in boxes
                     if not b[0].startswith(("bridge_", "post_"))]
        return {"boxes": boxes, "ports": ports,
                "z_lines": [zm + gb, zm + gb + tb] if _bridge_on else []}
    raise ValueError(f"未知 §C4 模板: {template}（可用 {_C4_COUPLER_TEMPLATES}）")


_C4_COUPLED_BOX_PREFIX: tuple[str, ...] = ("line_", "finger_")


def _c4_gap_midlines(boxes: list[tuple[str, float, float, float,
                                        float, float, float]]) -> list[float]:
    """§C4 相邻耦合导体（line_*/finger_*）x 向缝中点列表（米）——缝中线加密。

    按 x0 排序后相邻两盒 x1<x0' 即一条缝，取中点；branchline_2sect 无耦合缝
    返回空。cline_coupler 缝中点=0（nx 本已含）、lange 三缝中点 0/±(w+s)/2。
    """
    cond = sorted((b for b in boxes if b[0].startswith(_C4_COUPLED_BOX_PREFIX)),
                  key=lambda b: b[1])
    return [(a[4] + b[1]) / 2.0 for a, b in pairwise(cond) if b[1] > a[4]]


def _c4_body_lines(template: str, p: dict[str, Any]) -> str:
    """§C4 三模板渲染几何段（布局字面量 + excite_port 轮转激励 + priority 收口）。"""
    lay = _c4_layout(template, p)
    ep = max(1, min(4, int(p.get("_excite_port", 1) or 1)))
    out: list[str] = [f"EP = {ep}",
                      f'{template} = CSX.AddMetal("{template}")']
    for (nm, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f"{template}.AddBox(({x0!r}, {y0!r}, {z0!r}), "
                   f"({x1!r}, {y1!r}, {z1!r}), priority=10)  # {nm}")
    for pt in lay["ports"]:
        sx, sy, _ = pt["start"]
        tx, ty, _ = pt["stop"]
        out.append(
            f'_port{pt["nr"]} = MSLPort(CSX, port_nr={pt["nr"]}, '
            f"metal_prop={template},\n"
            f"                 start=np.array([{sx!r}, {sy!r}, H_SUB]),\n"
            f"                 stop=np.array([{tx!r}, {ty!r}, 0]),\n"
            f'                 prop_dir="{pt["prop_dir"]}", exc_dir="z", '
            f"excite=1 if EP == {pt['nr']} else 0,\n"
            f"                 FeedShift=10 * NEAR, "
            f'MeasPlaneShift={float(pt["meas_shift"])!r}, priority=10)')
    out.append(f"for _prim in {template}.GetAllPrimitives():\n"
               "    if _prim.GetPriority() < 10:\n"
               "        _prim.SetPriority(10)")
    return "\n".join(out) + "\n"


def _cline_coupler_lines(p: dict[str, Any]) -> str:
    # 耦合线定向耦合器（§C4 口径 1）：两条 λ/4 平行线（KJ (w,s)），四端口
    # 全建（后向波：1 输入/2 直通/3 耦合近端/4 隔离远端）；50Ω 馈线外推+
    # 横向搭接段（同心直连短路）。几何单源 _c4_layout。
    return _c4_body_lines("cline_coupler", p)


def _branchline_2sect_lines(p: dict[str, Any]) -> str:
    # 两节分支线（§C4 口径 2）：主线 Z_a 两节 + 外/中支臂 Z_b1/Z_b2，四角
    # 50Ω 馈线沿 x 引出（P1 左上输入/P2 右上直通/P3 右下耦合/P4 左下隔离）。
    # 支臂跨度 = 两支臂 λ/4 均值（固有二阶偏差 ±1.5%，段首口径 2）。
    return _c4_body_lines("branchline_2sect", p)


def _lange_lines(p: dict[str, Any]) -> str:
    # 展开型 Lange 电桥（§C4 口径 3）：四指交替并联（网络 A=指1/3、B=指2/4），
    # 桥=抬高薄金属+竖直立柱（同端 A/B 桥错位、两端分置——#212 bbox 审计
    # 判两组 DC 隔离）；外指承馈 P1/P2/P3/P4。params["_bridge"]=0 → 去桥
    # 对照变体（单变量，判据 runs/c4_debridge/criteria.md）。
    return _c4_body_lines("lange", p)


# ── 名义设计点（设计函数 @2.5GHz rogers4350b 的 4 位舍入；再生口径由
# test_coupler2_templates 逐键钉住：round(设计函数, 4) == 标称 逐位）──
CLINE_COUPLER_NOMINAL: dict[str, Any] = {
    # C=10^(−10/20)=0.31623 → (Z0e,Z0o)=(69.371,36.038)Ω → KJ 反解 (w,s)
    "w_mm": 0.9243,
    "gap_mm": 0.082,
    # λ/4 @ (εeff_e+εeff_o)/2=2.7292 → 18.1469mm
    "coupled_len_mm": 18.1469,
    "w_feed_mm": 1.1117,
}

BRANCHLINE_2SECT_NOMINAL: dict[str, Any] = {
    # Pozar 经典点 (Z_a,Z_b1,Z_b2)=(50,120.71,70.71)Ω → HJ 线宽
    "w_main_mm": 1.1117,
    "w_out_mm": 0.162,
    "w_mid_mm": 0.6024,
    "w_feed_mm": 1.1117,
    # 主线节 λ/4（εeff=2.8579）；支臂跨度=(18.7144+18.1465)/2（外/中支臂均值）
    "sect_len_mm": 17.7338,
    "branch_len_mm": 18.4304,
}

LANGE_NOMINAL: dict[str, Any] = {
    # C=1/√2 → 相邻对 (176.216,52.609)Ω → KJ 反解（g=s/h=0.076 提示见段首 3）
    "w_mm": 0.1672,
    "gap_mm": 0.0386,
    # 指长 λ/4 @ (εeff_e+εeff_o)/2=2.4972 → 18.9712mm
    "finger_len_mm": 18.9712,
    "w_feed_mm": 1.1117,
}

CLINE_COUPLER_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208 进程隔离"
                  "；同 ratrace footer 9 列单激励 CSV）。裁判=偶/奇模频响"
                  " coupled_line_coupler_sparams（Pozar §7.6 闭式）：f0 处"
                  " |S31|=C、S21=−j√(1−C²)、S11=S41=0（同步极限）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "gap_mm", "coupled_len_mm", "w_feed_mm"],
    "topology": "耦合线定向耦合器（后向波，C4 族）：两条 λ/4 平行耦合线"
                "（KJ (w,s) 反解）+ 四条 50Ω 馈线外推+横向搭接段（同心直连"
                "短路）；1=输入/2=直通（线 A 远端）/3=耦合（线 B 近端，与"
                "输入同侧）/4=隔离",
    "param_semantics": "w_mm=耦合段单线宽，gap_mm=耦合缝（边到边），"
                       "coupled_len_mm=耦合段物理长（λ/4 @平均 εeff），"
                       "w_feed_mm=50Ω 馈线宽——fake/openEMS 两通道同名同语义",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部盒缘精确入网（#198；_c4_layout 单源）",
    "smoke_note": "真机未跑（followUp）：非同步残差预期 S41≈−23dB/S11≈−33dB"
                  "（定向性 ≈13dB，微带耦合线固有，段首口径 1），冒烟按此判读",
}

BRANCHLINE_2SECT_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208）。"
                  "裁判=偶/奇模二分频响 branchline_2sect_sparams（Pozar §7.5"
                  " 推广 + Levy & Lind 1968）：f0 处 |S21|=|S31|=−3.01dB、"
                  "S11=S41=0；两节 ≥ 单节带宽（±1dB 均分 35.0% vs 25.8%）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_main_mm", "w_out_mm", "w_mid_mm", "sect_len_mm",
               "branch_len_mm", "w_feed_mm"],
    "topology": "两节分支线 3dB 正交耦合器（C4 族，Pozar 经典点）：主线 Z_a"
                "=Z0 两节 + 外支臂 (1+√2)Z0 + 中支臂 √2·Z_a²/Z0（单参数族，"
                "main_z_ratio 可调）；四角 50Ω 馈线沿 x 引出，P1 左上输入/"
                "P2 右上直通/P3 右下耦合/P4 左下隔离",
    "param_semantics": "w_main_mm/w_out_mm/w_mid_mm=主线/外支臂/中支臂线宽"
                       "（HJ 精算），sect_len_mm=主线节长（λ/4 @εeff(Z_a)），"
                       "branch_len_mm=支臂跨度（外/中支臂 λ/4 均值——两支臂"
                       "εeff 不同致 ≈±1.5% 固有二阶偏差，段首口径 2），"
                       "w_feed_mm=50Ω 馈线宽",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部盒缘精确入网（#198；_c4_layout 单源）",
    "smoke_note": "真机未跑（followUp）：预期引擎偏差项=T 结不连续性+拐角"
                  "（理想闭式不含），冒烟对照 branchline 单节同门",
}

LANGE_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（excite_port 轮转 4 run，#208）。"
                  "裁判=四线等效两线偶/奇模频响（Pozar §7.6 Lange 节设计式"
                  "自洽回代 C/Z0 逐位闭合）：f0 处 |S21|=|S31|=−3.01dB、"
                  "S31=+1/√2（耦合同相）、S21=−j/√2、S11=S41=0",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "gap_mm", "finger_len_mm", "w_feed_mm"],
    "topology": "展开型 Lange 电桥（3dB 正交，C4 族）：四指交替并联（网络 A="
                "指1/3、B=指2/4，DC 隔离），air-bridge=抬高薄金属+竖直立柱"
                "（同端 A/B 桥错位、两端分置）；外指承馈 P1/P2/P3/P4，等效"
                "两线 (Ze4,Zo4)=(120.71,20.71)Ω 精确成立",
    "param_semantics": "w_mm=单指宽，gap_mm=指缝（边到边；3dB 于本叠层 "
                       "s=0.0386mm，g=s/h=0.076 略低于 KJ 标称有效域下限 0.1，"
                       "段首口径 3 如实记录），finger_len_mm=指长（λ/4 @平均 "
                       "εeff），w_feed_mm=50Ω 馈线宽",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "指缝/桥/立柱盒缘精确入网（#198；air-bridge z 底/顶面入网）",
    "smoke_note": "真机未跑（followUp）：指缝 38.6µm 小于 0.4mm 审计网格"
                  "（near 加密入网）；桥缝耦合寄生于理想裁判之外，冒烟按 "
                  "g=0.076 提示与一阶口径判读",
}

# ── 注册（2026-09-16）：C4 耦合器族 II 三模板升格正式注册 ──
# 四处同步：① docs/templates/{cline_coupler,branchline_2sect,lange}/meta.yaml；
# ② test_template_geometry_audit.EXPECTED_TEMPLATES（HEAD 25 → 合流时实际值，
# 同轮 C3/CPS 等多轨在制、计数以合流实测为准，不得写死）；③ fake_adapter
# 派发分支；④ models/template_specs（_register_cline_coupler/_register_
# branchline_2sect/_register_lange）。同对象注册（非拷贝）钉死单一事实源。
TEMPLATE_META["cline_coupler"] = CLINE_COUPLER_META
TEMPLATE_NOMINAL["cline_coupler"] = CLINE_COUPLER_NOMINAL
TEMPLATE_META["branchline_2sect"] = BRANCHLINE_2SECT_META
TEMPLATE_NOMINAL["branchline_2sect"] = BRANCHLINE_2SECT_NOMINAL
TEMPLATE_META["lange"] = LANGE_META
TEMPLATE_NOMINAL["lange"] = LANGE_NOMINAL
