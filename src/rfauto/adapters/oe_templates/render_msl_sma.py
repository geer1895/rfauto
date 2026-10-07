"""msl_cpw 共面波导 + sma_launcher 连接器族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .registry import TEMPLATE_META, TEMPLATE_NOMINAL

# ─── WP2.5 Tier 2 过渡结构（2026-09-16 wp25-sma-launcher-rootcause 正式注册）────
# msl_cpw：微带↔共面波导（接地 CPWG）过渡；sma_launcher：SMA 边缘弹射
# （end-launch 同轴↔微带，夹具口径，port1=同轴截面集总桥——CoaxialPort 真机
# 判废见 _sma_launcher_lines 注）。MSL↔slotline（Marchand）随 openEMS
# slotline 端口原语缺失阻塞（方案 C5 行，勿烧）。
#
# 注册四件套（文末 TEMPLATE_META/TEMPLATE_NOMINAL 同对象入表 + docs/templates/
# <t>/meta.yaml + test_template_geometry_audit.EXPECTED_TEMPLATES + fake_adapter
# 派发分支 + models/template_specs），钉在 test_msl_cpw_template /
# test_sma_launcher_template 的 test_registered_*。
#
# 锚判据口径（Tier 2 无谐振，wstep/via 族同型）：
# - msl_cpw：双端口 β 金标准（port1→HJ εeff、port2→CPWG 共形映射闭式）+
#   skrf 两段理想 TL 级联裁判（渐变/地缘/过孔栅栏寄生=引擎-理想偏差）。
#   真机 PASS 留档 runs/wp25_tier2_smoke/pt1_msl_cpw3（|S11|@2.5G −20.0dB、
#   β +0.37%/−1.04%，1076s@0.4mm）——几何冻结勿动。
# - sma_launcher：port2 β→HJ（port1 集总桥无 β 属性）；|S11| 文献曲线门
#   （edge-launch SMA 带内回损常规 15-20dB、保守地板 -10dB，方案行口径
#   "验收靠文献曲线"；docs/rf_template_references.md SMA 节）。

# XC-W 单源口径：本常数=nominal_width_mm(50,2.5,rogers4350b)@round4=1.1134
# 逐位同值的归档字面量（字面量落表避免模块导入期 brentq，一致性测试钉）；
# 「同 hairpin 口径」系旧注笔误——hairpin 链是无耗裸层叠档（tanδ=0）1.1117，
# 本档与 mline/gysel/wstep 同为 yaml 层叠（tanδ=0.0037）档。
_MSL_CPW_50OHM_W_MM = 1.1134   # 50Ω 微带（HJ inverse_width 1.113400）
_SMA_RI_MM = 0.635             # SMA 中心针半径（Ø1.27mm 标准针，IEC 61169-15）
_SMA_ER_FILL = 2.1             # PTFE 填充（TEM 口径 εeff=εr 精确）
_SMA_SHELL_T_MM = 0.25         # 外导体壁厚（r_os = r_o + 壁厚，派生量）
# port1 面距 y-min 边界的网格 cell 数：越过 PML_8（8 cells）再留 4 cells 净空
# （根治前 port1 距边界 0.5mm 整体落在 PML_8 内，H4 实证）
_SMA_PORT_CELLS_FROM_BOUNDARY = 12

MSL_CPW_NOMINAL: dict[str, Any] = {
    "w_msl_mm": _MSL_CPW_50OHM_W_MM,   # 50Ω 微带（inverse_width）
    "w_cpw_mm": 0.849,    # 50Ω CPWG @gap0.2（_cpwg_ri brentq 反解 0.848999）
    "gap_cpw_mm": 0.2,
    "line_len_mm": 40.0,  # 总长（过渡区居中，MSL/CPW 直段各半）
    "trans_len_mm": 10.0,
    "r_via_mm": 0.15,     # 接地过孔半径（via 基元同款）
    "via_spacing_mm": 2.0,
    "via_offset_mm": 0.5,  # 地内缘→过孔中心
}

SMA_LAUNCHER_NOMINAL: dict[str, Any] = {
    "w_msl_mm": _MSL_CPW_50OHM_W_MM,
    "r_i_mm": _SMA_RI_MM,
    # 50Ω 同轴闭式 r_o = r_i·exp(Z0·√εr/60)（PTFE εr=2.1 → 2.124389）
    "r_o_mm": 2.1244,
    "shell_t_mm": _SMA_SHELL_T_MM,   # 外导体壁厚（r_os=2.3744 派生）
    "er_fill": _SMA_ER_FILL,
    "shell_len_mm": 5.0,  # 同轴段长：port1 面 → 板边（切口面 Y_E）
    "pin_lay_mm": 2.0,    # 针搭焊段：板边外伸、水平搭在微带上（焊锡填实）
    "line_len_mm": 40.0,  # 微带体带长（板边 Y_E → Y1；port2 自画 Y1→BOARD）
    "port_len_mm": 0.2,   # 集总桥 y 向厚（针顶→壳内壁顶 z 向桥，E 沿径向）
    # ③ 变体：PTFE 介质损耗 tanδ → AddMaterial kappa（同基板 TAND 口径）；
    # 名义无耗 0.0（与理想级联裁判/真机 pt3 同口径），有耗变体走 recipe 覆盖
    "tan_d_fill": 0.0,
}


def sma_launcher_r_o_mm(r_i_mm: float, er_fill: float = _SMA_ER_FILL,
                        z0_ohm: float = 50.0) -> float:
    """50Ω 同轴外径内缘闭式：Z0 = (60/√εr)·ln(r_o/r_i) 反解（TEM 精确）。"""
    return float(r_i_mm) * math.exp(z0_ohm * math.sqrt(er_fill) / 60.0)


def sma_launcher_layout(p: dict[str, Any], h_sub_m: float,
                        base_m: float, board_m: float = 0.060) -> dict[str, float]:
    """sma_launcher 几何单源（米）——render/_near_points/z 网格/geometry_spec/审计共用。

    夹具口径（edge-launch，2026-09-16 根治）：针轴高 Z_AX=r_os（壳底切 z=0 PEC
    夹具底板），PCB 抬高 Z_G=r_os−r_i−H_SUB 使针底切线恰为基板顶 Z_TOP（针水平
    搭焊微带）；同轴段 y∈[Y_B, Y_E]（Y_E=板边切口面，Y_B=port1 面后退 2 cells
    的开口同轴端），针延至 Y_PE=Y_E+pin_lay 搭在微带上；夹具金属块填 PCB 下方
    z∈[0,Z_G]、y∈[Y_E,BOARD]，前脸 y=Y_E 与壳端实触（地链：壳—夹具—PEC 底板）。
    浮点运算顺序在此单源固定，渲染脚本内同名量按同序重算（字面同源）。
    """
    ri = float(p.get("r_i_mm", 0.635)) * 1e-3
    ro = float(p.get("r_o_mm", 2.1244)) * 1e-3
    t = float(p.get("shell_t_mm", _SMA_SHELL_T_MM)) * 1e-3
    ros = ro + t
    z_ax = ros
    z_g = ros - ri - h_sub_m
    z_top = z_g + h_sub_m
    y_p0 = -board_m + _SMA_PORT_CELLS_FROM_BOUNDARY * base_m
    y_b = y_p0 - 2 * base_m
    y_e = y_p0 + float(p.get("shell_len_mm", 5.0)) * 1e-3
    y_pe = y_e + float(p.get("pin_lay_mm", 2.0)) * 1e-3
    y1 = y_e + float(p.get("line_len_mm", 40.0)) * 1e-3
    if not (ri < ro):
        raise ValueError(f"sma_launcher: r_i={ri * 1e3:.4g}mm 须 < r_o={ro * 1e3:.4g}mm")
    if not (t > 0.0):
        raise ValueError(f"sma_launcher: shell_t_mm={t * 1e3:.4g} 须 >0")
    if not (z_g > 0.0):
        raise ValueError(
            f"sma_launcher: r_os−r_i={(ros - ri) * 1e3:.4g}mm 须 > H_SUB="
            f"{h_sub_m * 1e3:.4g}mm（针底切线高于夹具底板才能抬板）")
    if not (y1 < board_m):
        raise ValueError(f"sma_launcher: 体带终点 Y1={y1 * 1e3:.4g}mm 越出板 {board_m * 1e3:g}mm")
    # 连接器体前脸（v2，2026-09-16 pt3 v1 真跑 |S11|=−4dB 后增设）：与板边齐平的
    # 金属面墙（厂商口径"connector face flush with PCB edge"，refs §14.2），孔径由
    # PTFE 环/针以优先级挖空；半宽/高度 = 壳外径 + 2 cells，厚 2 cells（体尺寸为
    # 通用连接器体口径，非物理拟合量）
    f_w = ros + 2 * base_m
    f_t = 2 * base_m
    f_z = z_ax + ros + 2 * base_m
    return {"ri": ri, "ro": ro, "t": t, "ros": ros, "z_ax": z_ax, "z_g": z_g,
            "z_top": z_top, "y_b": y_b, "y_p0": y_p0, "y_e": y_e, "y_pe": y_pe,
            "y1": y1, "w_m": float(p.get("w_msl_mm", _nominal_width.W50_MM)) * 1e-3,
            "plen": float(p.get("port_len_mm", 0.2)) * 1e-3,
            "f_w": f_w, "f_t": f_t, "f_z": f_z}


def _msl_cpw_lines(p: dict[str, Any]) -> str:
    # MSL↔CPWG 过渡（WP2.5 Tier 2）：微带直段 → 中心导体阶梯渐变
    # （NT 段等分过渡区）→ CPW 中心段+两侧地（延至板边）+ 接地过孔栅栏
    # （CPWG 地缝合底板 PEC，抑制平行板模——过渡族必要件）。
    # port1=MSLPort（50Ω 微带口径）、port2=CPWPort（CPWG 口径，地自画——
    # cpw 锚模板同口径）。双段 β 金标准见 render_script beta_block。
    return f'''W_M = {p.get("w_msl_mm", _nominal_width.W50_MM)!r} * 1e-3
W_C = {p.get("w_cpw_mm", 0.849)!r} * 1e-3
GAP = {p.get("gap_cpw_mm", 0.2)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
TL = {p.get("trans_len_mm", 10.0)!r} * 1e-3
NT = 4
RV = {p.get("r_via_mm", 0.15)!r} * 1e-3
SV = {p.get("via_spacing_mm", 2.0)!r} * 1e-3
VO = {p.get("via_offset_mm", 0.5)!r} * 1e-3
Y0 = -L / 2
YM = -TL / 2
YT = TL / 2
Y1 = L / 2
mslcpw = CSX.AddMetal("msl_cpw")
# 微带直段（MSLPort 自画 -BOARD→Y0 馈线）
mslcpw.AddBox((-W_M / 2, Y0, H_SUB), (W_M / 2, YM, H_SUB), priority=10)
# 中心导体阶梯渐变（等分过渡区，段宽线性内插 W_M→W_C）
for _i in range(NT):
    _ya = YM + _i * TL / NT
    _yb = YM + (_i + 1) * TL / NT
    _w = W_M + (_i + 0.5) * (W_C - W_M) / NT
    mslcpw.AddBox((-_w / 2, _ya, H_SUB), (_w / 2, _yb, H_SUB), priority=10)
# CPW 中心段 + 两侧地（自渐变终点延至板边；端口段地须自画——cpw 同口径）
mslcpw.AddBox((-W_C / 2, YT, H_SUB), (W_C / 2, Y1, H_SUB), priority=10)
mslcpw.AddBox((-BOARD, YT, H_SUB), (-(W_C / 2 + GAP), BOARD, H_SUB),
              priority=10)
mslcpw.AddBox((W_C / 2 + GAP, YT, H_SUB), (BOARD, BOARD, H_SUB), priority=10)
# 接地过孔栅栏（地内缘外 VO 处双列，至板边——寄生方向性最小的最简栅栏）
mslcpw_via = CSX.AddMetal("msl_cpw_via")
_k = 0
while YT + VO + _k * SV <= BOARD - VO:
    _yv = YT + VO + _k * SV
    for _xv in (-(W_C / 2 + GAP + VO), (W_C / 2 + GAP + VO)):
        mslcpw_via.AddCylinder([_xv, _yv, 0.0], [_xv, _yv, H_SUB],
                               radius=RV, priority=10)
    _k += 1
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mslcpw,
                 start=np.array([W_M / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_M / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = CPWPort(CSX, port_nr=2, metal_prop=mslcpw,
                 start=np.array([W_C / 2, BOARD, H_SUB]),
                 stop=np.array([-W_C / 2, Y1, H_SUB]),
                 prop_dir="y", exc_dir="x", gap_width=GAP,
                 excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in mslcpw.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in mslcpw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _sma_launcher_lines(p: dict[str, Any]) -> str:
    # SMA 边缘弹射（WP2.5 Tier 2，2026-09-16 根治重构，edge-launch 夹具口径）：
    # 真机 FAIL 根因（scripts/diag_sma_launcher.py 精确接触图实证，legacy 留档
    # runs/wp25_tier2_smoke/pt3_sma_launcher_diag/legacy_contacts.json）：
    #   H2 引脚柱盒与壳底壁实交叠——信号链对接地壳短路（|S21|≈−375dB）；
    #   H1 地侧针与壳/墙/底板零接触——串馈集总口基准端悬空；
    #   H4 port1 距 y-min 边界 0.5mm 整体落在 PML_8 内；H5 壳顶距域顶 0.25mm。
    # 新几何（连接器厂商 end-launch 图纸口径，docs/rf_template_references.md
    # SMA 节）：针水平搭焊微带（针底切线=基板顶）、壳体在板边切口之外、地链
    # 壳—夹具块—PEC 底板实触；port1 = 同轴截面集总桥（LumpedPort R=50Ω，
    # 针顶→壳内壁顶沿 z=径向，官方 LumpedPort 口径——CoaxialPort 真机判废：
    # pt2 冒烟 β=4166 vs TEM 闭式 68、|S21|=−240dB）。PTFE 填充 TEM 口径
    # εeff=εr；同轴 50Ω 由 r_o 闭式保证（sma_launcher_r_o_mm）。
    # 几何单源 sma_launcher_layout（render_script 注入 _sma_layout 字面量，
    # z 网格/基板块/近场线同源）。
    lay = p.get("_sma_layout") or sma_launcher_layout(
        p, 0.508e-3, float(p.get("_base_mm", 0.4)) * 1e-3)
    return f'''W_M = {lay["w_m"]!r}
RI = {lay["ri"]!r}
RO = {lay["ro"]!r}
ROS = {lay["ros"]!r}           # r_o + shell_t（外导体外径，派生）
ER_FILL = {p.get("er_fill", 2.1)!r}
PT_TAND = {p.get("tan_d_fill", 0.0)!r}   # PTFE tanδ（③ 变体；名义 0=无耗）
Z_AX = {lay["z_ax"]!r}         # 针轴高 = r_os（壳底切 z=0 PEC 夹具底板）
Z_G = {lay["z_g"]!r}           # PCB 地面 = 夹具块顶（r_os − r_i − H_SUB）
Z_TOP = {lay["z_top"]!r}       # 基板顶 = 微带面 = 针底切线（针水平搭焊）
Y_B = {lay["y_b"]!r}           # 开口同轴端（port1 面后退 2 cells）
Y_P0 = {lay["y_p0"]!r}         # port1 面（越过 y-min PML_8 + 4 cells 净空）
Y_PL = {lay["y_p0"] + lay["plen"]!r}   # 集总桥 y 向终面
Y_E = {lay["y_e"]!r}           # 板边切口面 = 壳端 = 微带起点
Y_PE = {lay["y_pe"]!r}         # 针端（搭焊段终点）
Y1 = {lay["y1"]!r}             # 体带终点（port2 自画 Y1→BOARD）
F_W = {lay["f_w"]!r}           # 连接器体前脸半宽（r_os + 2 cells）
F_T = {lay["f_t"]!r}           # 前脸厚（2 cells，y∈[Y_E−F_T, Y_E]）
F_Z = {lay["f_z"]!r}           # 前脸顶（壳顶 + 2 cells）
# 夹具金属块：PCB 下方 z∈[0,Z_G] 实心（PCB 地 = 块顶；前脸 y=Y_E 与壳端实触）
sma_gnd = CSX.AddMetal("sma_gnd")
sma_gnd.AddBox((-BOARD, Y_E, 0.0), (BOARD, BOARD, Z_G), priority=10)
# 连接器体前脸（v2）：与板边齐平的金属面墙，优先级 4 < PTFE 环 5 / 针 10 →
# 孔径处按材料优先级挖空（针穿孔而过，PTFE 隔离）；不进 priority 抬升循环
sma_face = CSX.AddMetal("sma_face")
sma_face.AddBox((-F_W, Y_E - F_T, 0.0), (F_W, Y_E, F_Z), priority=4)
# 板边切口：y<Y_E 无基板（空气盒盖过基板层；优先级 1>基板 0，<PTFE 5/金属 10）
sma_notch = CSX.AddMaterial("sma_notch", epsilon=1.0)
sma_notch.AddBox((-BOARD, -BOARD, Z_G), (BOARD, Y_E, Z_TOP), priority=1)
# 同轴段 y∈[Y_B, Y_E]：PTFE 填充环（tanδ→kappa 同基板口径）+ 外导体壳（壳底切
# z=0 夹具底板，实触）
ptfe = CSX.AddMaterial("ptfe", epsilon=ER_FILL,
                       kappa=PT_TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER_FILL)
ptfe.AddCylindricalShell(np.array([0.0, Y_B, Z_AX]), np.array([0.0, Y_E, Z_AX]),
                         0.5 * (RI + RO), RO - RI, priority=5)
sma_shell = CSX.AddMetal("sma_shell")
sma_shell.AddCylindricalShell(np.array([0.0, Y_B, Z_AX]),
                              np.array([0.0, Y_E, Z_AX]),
                              0.5 * (RO + ROS), ROS - RO, priority=10)
# 中心针：同轴内穿出板边切口面，水平搭在微带上至 Y_PE（针底切线 = Z_TOP）
sma_pin = CSX.AddMetal("sma_pin")
sma_pin.AddCylinder(np.array([0.0, Y_B, Z_AX]), np.array([0.0, Y_PE, Z_AX]),
                    radius=RI, priority=10)
# 针顶接触垫：阶梯网格下保证集总桥下电极（z=Z_AX+RI 切线）金属边连续
sma_pin.AddBox((-RI / 2, Y_P0, Z_AX), (RI / 2, Y_PL, Z_AX + RI), priority=10)
# 搭焊焊锡：针下半侧填实至微带面（针—微带实接触，宽度=微带宽）
sma_pin.AddBox((-W_M / 2, Y_E, Z_TOP), (W_M / 2, Y_PE, Z_AX), priority=10)
# port1：同轴截面集总桥（针顶 z=Z_AX+RI → 壳内壁顶 z=Z_AX+RO，E 沿 z=径向；
# 优先级 6：高于 PTFE 5（桥内为集总元件）、低于金属 10（端面归金属）
_port1 = LumpedPort(CSX, port_nr=1, R=50.0,
                    start=np.array([-RI / 2, Y_P0, Z_AX + RI]),
                    stop=np.array([RI / 2, Y_PL, Z_AX + RO]),
                    exc_dir="z", excite=1, priority=6)
sma_strip = CSX.AddMetal("sma_strip")
sma_strip.AddBox((-W_M / 2, Y_E, Z_TOP), (W_M / 2, Y1, Z_TOP), priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=sma_strip,
                 start=np.array([-W_M / 2, BOARD, Z_TOP]),
                 stop=np.array([W_M / 2, Y1, Z_G]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _metal in (sma_gnd, sma_shell, sma_pin, sma_strip):
    for _prim in _metal.GetAllPrimitives():
        if _prim.GetPriority() < 10:
            _prim.SetPriority(10)
'''


# ── WP2.5 两模板 META/NOMINAL（2026-09-16 正式注册，hairpin/coupled_bpf 同款
# 同对象入表；四件套其余三处：docs/templates/{msl_cpw,sma_launcher}/meta.yaml、
# test_template_geometry_audit.EXPECTED_TEMPLATES、fake_adapter 派发分支、
# models/template_specs _register_msl_cpw/_register_sma_launcher）──
MSL_CPW_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1 / CPWPort 2（MSL↔CPWG 过渡：双端口 β 金标准"
                  "（port1→HJ、port2→CPWG 共形映射）+ skrf 两段理想 TL 级联裁判）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_msl_mm", "w_cpw_mm", "gap_cpw_mm", "line_len_mm",
               "trans_len_mm", "r_via_mm", "via_spacing_mm", "via_offset_mm"],
    "topology": "微带↔接地共面波导过渡（WP2.5 Tier 2）：微带直段 → 4 段等分"
                "阶梯渐变（线宽线性内插）→ CPW 中心带 + 两侧地（延至板边）+ 双列"
                "接地过孔栅栏（地缝合底板 PEC，抑制平行板模）；过渡区居中",
    "param_semantics": "w_msl_mm=50Ω 微带宽（HJ 反解），w_cpw_mm=50Ω CPWG 中心"
                       "带宽（_cpwg_ri brentq 反解 @gap），gap_cpw_mm=CPW 缝宽，"
                       "line_len_mm=总长（MSL/CPW 直段各半），trans_len_mm=渐变区"
                       "长，r_via_mm/via_spacing_mm/via_offset_mm=接地过孔半径/"
                       "列间距/地内缘→过孔中心",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "微带带缘 + CPW 四条几何边（带缘/地内缘）+ 缝中线 + 渐变区两端"
                 "精确入网（#198）",
}

SMA_LAUNCHER_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ LumpedPort 1（同轴截面集总桥）/ MSLPort 2（SMA edge-"
                  "launch：port2 β→HJ 金标准 + |S11| 文献曲线门 -10dB 保守地板）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_msl_mm", "r_i_mm", "r_o_mm", "shell_t_mm", "er_fill",
               "shell_len_mm", "pin_lay_mm", "line_len_mm", "port_len_mm",
               "tan_d_fill"],
    "topology": "SMA 边缘弹射（WP2.5 Tier 2，end-launch 夹具口径）：PTFE 填充"
                " 50Ω 同轴段（针/壳圆柱自画）在板边切口之外，针水平穿出搭焊在"
                " 微带上（针底切线=基板顶），壳底切 z=0 PEC 夹具底板、壳端与"
                " PCB 下方夹具金属块前脸实触（地链）；port1=同轴截面集总桥"
                "（针顶→壳内壁顶），port2=板边 MSLPort",
    "param_semantics": "w_msl_mm=50Ω 微带宽（HJ），r_i_mm=针半径，r_o_mm=PTFE 外"
                       "径/壳内径（50Ω 闭式 r_i·exp(Z0√εr/60)），shell_t_mm=外导"
                       "体壁厚（r_os=r_o+t 派生），er_fill=PTFE εr（材料参数，"
                       "不驱动导体几何），shell_len_mm=同轴段长（port1 面→板边），"
                       "pin_lay_mm=针搭焊外伸长，line_len_mm=微带体带长，"
                       "port_len_mm=集总桥 y 向厚，tan_d_fill=PTFE tanδ（材料"
                       "参数→kappa，名义 0 无耗；③ 有耗变体 recipe 覆盖）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "同轴三半径 x/z 向柱面界 + 桥盒边 + 板边/针端/带端 y 面精确"
                 "入网；port1 面距 y-min 边界 12 cells（越过 PML_8）",
}

TEMPLATE_META["msl_cpw"] = MSL_CPW_META
TEMPLATE_NOMINAL["msl_cpw"] = MSL_CPW_NOMINAL
TEMPLATE_META["sma_launcher"] = SMA_LAUNCHER_META
TEMPLATE_NOMINAL["sma_launcher"] = SMA_LAUNCHER_NOMINAL
