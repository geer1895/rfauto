"""MM-4 CRLH 单元计算器族（内核在 core/crlh.py，本模块只做注册壳）。

round17 §五 :146 规格「MM-4 CRLH 计算器：色散 β(ω)/平衡条件/
ZOR ω0=1/√(L_L·C_R)/漏波角闭式+skrf 级联仿真」（2026-10-02；翻案声明：
前轮 no-go 仅限 openEMS 模板形态，计算器+skrf 形态成立）。单键
crlh_unit_cell_report（单元点分析：谐振对/ZOR/平衡判定/频段/复 β/
Z_CRLH/衰减/漏波角报告）；crlh_beta/crlh_bloch_impedance/
crlh_image_impedance_t/imbalance_parameter/leaky_wave_angle_deg/
crlh_s21_closed_form/crlh_skrf_cascade_s21 为 core 纯函数不注册
（级联对拍面走 core 直调+test_crlh.py 锚树；≤0.1dB/1° 验收在传播
频段，阻带镜像阻抗纯虚在 power-wave S 下无定义）。
"""

from __future__ import annotations

from .registry import register_calculator


@register_calculator(
    "crlh_unit_cell_report",
    "MM-4 CRLH（复合左/右手传输线）单元点分析（round17 §五 :146，"
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
