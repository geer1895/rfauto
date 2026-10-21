"""MM-4 CRLH 单元计算器族（内核在 core/crlh.py，本模块只做注册壳）。

出处（CRLH 传输线经典口径，内核 core/crlh.py §3.1 转录）：
- crlh_unit_cell_report：CRLH T 型单元色散/平衡条件/ZOR/漏波角闭式
  （C. Caloz & T. Itoh, Electromagnetic Metamaterials: Transmission Line
  Theory and Microwave Applications, Wiley 2006 §3.1；二级转引 A. Lai,
  C. Caloz, T. Itoh, IEEE Microwave Mag. 5(3), 2004）。
- crlh_balanced_synthesize：四元 LC 平衡综合（内核 §8 第一性联立消元，
  平衡条件 L_R·C_L=L_L·C_R 同上 Caloz-Itoh 口径）。

round17 §五 :146 规格「MM-4 CRLH 计算器：色散 β(ω)/平衡条件/
ZOR ω0=1/√(L_L·C_R)/漏波角闭式+skrf 级联仿真」（2026-10-02；翻案声明：
前轮 no-go 仅限 openEMS 模板形态，计算器+skrf 形态成立）。单键
crlh_unit_cell_report（单元点分析：谐振对/ZOR/平衡判定/频段/复 β/
Z_CRLH/衰减/漏波角报告）；crlh_beta/crlh_bloch_impedance/
crlh_image_impedance_t/imbalance_parameter/leaky_wave_angle_deg/
crlh_s21_closed_form/crlh_skrf_cascade_s21 为 core 纯函数不注册
（级联对拍面走 core 直调+test_crlh.py 锚树；≤0.1dB/1° 验收在传播
频段，阻带镜像阻抗纯虚在 power-wave S 下无定义）。

架构批 W2-S2 席增键 crlh_balanced_synthesize（R2_core_tier4 §③ Top8
C5——分析面既有、综合面 `crlh.*synth|crlh.*design` 全仓零的补口）：
(f0, Z0, C_L|L_R 恰给其一)→四元 LC 平衡综合闭式；内核
core/crlh.crlh_balanced_synthesis（§8，第一性联立消元），回判面=本族
crlh_unit_cell_report 分析键（δ=0/Z(f0)=Z0/f_se=f_sh=f0 同文件双路径，
#118）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "crlh_unit_cell_report",
    "CRLH单元分析：MM-4 CRLH（复合左/右手传输线）单元点分析（round17 §五 :146，"
    "Caloz & Itoh Wiley 2006 §3.1 口径）：T 型单元（串 L_R+C_L / 并 "
    "C_R+L_L）在单频点的谐振对 f_se=1/(2π√(L_R C_L))、f_sh=1/(2π√(L_L C_R))、"
    "ZOR（规格口径 1/√(L_L C_R)，短路边界 N=0 模；开路边径=ω_se 另提"
    "供）、平衡判定（δ=2(f_se−f_sh)/(f_se+f_sh)，平衡=0 阻带闭合）、"
    "频段归类（left_hand/right_hand/stopband；平衡单元 f_se=f_sh 为 "
    "transition 无缝过渡点）、复 Bloch 色散 β(ω)（左手频段 β<0 相位超"
    "前/右手 β>0/非平衡阻带 β 纯虚 Im≤0，深阻带 Bloch 相位 ±π/d）、"
    "CRLH 阻抗 Z_CRLH=√(Z/Y)（平衡时 ≡√(L_R/C_R) 与频率无关；ω→ω_sh "
    "阻带高阻/开路极限）、衰减（Np/m 与 dB/单元）与漏波角 "
    "θ=arcsin(Re β/k0)（|Re β|≥k0 或阻带 → None 不辐射不外推）",
    (("l_r_nh", "float 右手串联电感 L_R nH（>0）"),
     ("c_l_pf", "float 左手串联电容 C_L pF（>0）"),
     ("l_l_nh", "float 左手并联电感 L_L nH（>0）"),
     ("c_r_pf", "float 右手并联电容 C_R pF（>0）"),
     ("f_ghz", "float 分析频率 GHz（>0）"),
     ("cell_len_mm", "float 单元周期 d mm（>0；缺省 1.0）"),
     ("balance_rtol", "float 平衡判定相对容差（缺省 1e-6）")),
    required=("l_r_nh", "c_l_pf", "l_l_nh", "c_r_pf", "f_ghz"),
)
def crlh_unit_cell_report(
    l_r_nh: float,
    c_l_pf: float,
    l_l_nh: float,
    c_r_pf: float,
    f_ghz: float,
    cell_len_mm: float = 1.0,
    balance_rtol: float = 1.0e-6,
) -> dict:
    from rfauto.core.crlh import crlh_unit_cell_report as _report

    return _report(
        l_r_nh * 1.0e-9,
        c_l_pf * 1.0e-12,
        l_l_nh * 1.0e-9,
        c_r_pf * 1.0e-12,
        f_ghz * 1.0e9,
        cell_len_m=cell_len_mm * 1.0e-3,
        balance_rtol=balance_rtol,
    )


@register_calculator(
    "crlh_balanced_synthesize",
    "CRLH 平衡单元综合：分析面 complement（R2_core_tier4 §③ C5）——"
    "(f0, Z0, 串联支路 C_L 或 L_R 恰给其一)→四元 (L_R, C_L, L_L, C_R) "
    "闭式——平衡条件 L_R·C_L=L_L·C_R=1/ω0² + 转移点阻抗 Z_CRLH=√(L_R/"
    "C_R)=Z0（平衡单元频率无关）联立消元；三残差（平衡×2+阻抗）构造级"
    "~机器精度随输出自检；f0 即转移频率（f_se=f_sh=f0、β(f0)=0、阻带闭"
    "合）——回判面=crlh_unit_cell_report 分析键（同文件双路径 #118）",
    (("f0_ghz", "float GHz 平衡（转移）频率（>0）"),
     ("z0_ohm", "float Ω 转移点阻抗 Z_CRLH（>0）"),
     ("c_l_pf", "float pF 左手串联电容 C_L 种子（与 l_r_nh 恰给其一）"),
     ("l_r_nh", "float nH 右手串联电感 L_R 种子（与 c_l_pf 恰给其一）")),
    required=("f0_ghz", "z0_ohm"),
)
def crlh_balanced_synthesize(
    f0_ghz: float,
    z0_ohm: float,
    c_l_pf: float | None = None,
    l_r_nh: float | None = None,
) -> dict:
    from rfauto.core.crlh import crlh_balanced_synthesis as _synth

    out = _synth(
        f0_ghz * 1.0e9,
        z0_ohm,
        c_l_f=(None if c_l_pf is None else c_l_pf * 1.0e-12),
        l_r_h=(None if l_r_nh is None else l_r_nh * 1.0e-9),
    )
    return {
        "f0_ghz": round(f0_ghz, 12),
        "z0_ohm": out["z0_ohm"],
        "l_r_nh": round(out["l_r_h"] * 1.0e9, 12),
        "c_l_pf": round(out["c_l_f"] * 1.0e12, 12),
        "l_l_nh": round(out["l_l_h"] * 1.0e9, 12),
        "c_r_pf": round(out["c_r_f"] * 1.0e12, 12),
        "resid_balance_se": out["resid_balance_se"],
        "resid_balance_sh": out["resid_balance_sh"],
        "resid_z_ohm": out["resid_z_ohm"],
        "note": out["note"],
        "source": out["source"],
    }
