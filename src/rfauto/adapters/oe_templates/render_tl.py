"""基础传输线族渲染（mline/cpw/stripline/cps/wstep/bend/via/atten/gysel/tjunc/wilkinson/patch/branchline/dipole/coupled/stepped）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .registry import _DEFAULT_SUB

# ─── Template body render functions ──────────────────────────────────────────
# 口径（2026-09-04 官方方法学统一）：金属画在基板顶面 z=H_SUB（地面=z-min PEC
# 边界）；馈线段由 MSLPort 自画（同宽），端口面 = 板边 = 域边界；
# FeedShift=10×NEAR、MeasPlaneShift=端口段长/3（官方口径）。

def _mline_lines(p: dict[str, Any]) -> str:
    # 均匀微带线（WP2.1 锚模板）：一条直带，两端 MSLPort（端口自画馈线
    # 补齐到板边）。验收口径：S21 相位斜率→εeff 对照 skrf HJ ±1%（β 金
    # 标准 #162）；|S11| 显著非零=端口/网格判废信号（refs §3.2）。
    # 参数：w_mm=线宽（skrf HJ 综合，50Ω@rogers4350b=1.113mm），
    # line_len_mm=两端口间线长。
    return f'''W = {p.get("w_mm", _nominal_width.W50_MM_R3)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
mline = CSX.AddMetal("microstrip")
mline.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _cpw_lines(p: dict[str, Any]) -> str:
    # 均匀共面波导（WP2.1 锚族）：中心带 + 两侧地（地延伸到域边）。
    # 端口 = CPWPort（v0.37 一等支持）：start/stop 宽度=中心带宽、
    # gap_width=缝宽、地自画；exc_dir='x'=缝间横向（openEMS 2026-10-02
    # CPWPort exc_dir 语义重定义：旧=面法向/高度方向，新=缝间电场方向
    # =CPW 宽度方向，高度法向改由 prop×exc 叉积自算——绑定源码逐条对照）。
    # 参数：w_mm=中心带宽（CPWG 共形映射闭式综合，50Ω@gap0.2=0.849mm，
    # #198 参照系修正）、gap_mm=缝宽、line_len_mm=两端口间线长。
    body = f'''W = {p.get("w_mm", 0.849)!r} * 1e-3
GAP = {p.get("gap_mm", 0.2)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
cpw = CSX.AddMetal("cpw")
cpw.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
# 两侧地：贯穿全域（CPWPort 只补画中心带段，端口段的地须自画）
cpw.AddBox((-BOARD, -BOARD, H_SUB), (-W / 2 - GAP, BOARD, H_SUB), priority=10)
cpw.AddBox((W / 2 + GAP, -BOARD, H_SUB), (BOARD, BOARD, H_SUB), priority=10)
_port1 = CPWPort(CSX, port_nr=1, metal_prop=cpw,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, Y0, H_SUB]),
                 prop_dir="y", exc_dir="x", gap_width=GAP,
                 excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = CPWPort(CSX, port_nr=2, metal_prop=cpw,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, Y1, H_SUB]),
                 prop_dir="y", exc_dir="x", gap_width=GAP,
                 excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in cpw.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''
    # B6 stage-2 深化钩子：params 含 b6_board（板级事实 dict，出自
    # service.kicad_em_service.board_facts_from_extract）时追加板级全要素
    # 几何块（fill 外轮廓/孔洞切除/via 桶壁/pad/主线折线）。缺省键=既有
    # cpw 渲染逐字节不变。惰性导入（共享文件纪律；渲染模块只反向依赖
    # adapters 内新模块，无环）。
    b6_facts = p.get("b6_board")
    if b6_facts:
        from rfauto.adapters.kicad_board_render import board_geometry_lines

        body += board_geometry_lines(b6_facts)
    return body


def _stripline_lines(p: dict[str, Any]) -> str:
    # 均匀对称带状线（WP2.1 锚族）：中心带在 H_SUB 中面，上下地 = 域
    # z 边界 PEC（底 z=0、顶 z=2·H_SUB）。端口 = StripLinePort（v0.37
    # 一等支持，绑定源码 L914+：height=带-地半高，对称电压探针上下
    # 各一）。TEM 模：εeff=εr（β 锚判据最干净的闭式）。
    return f'''W = {p.get("w_mm", 0.5554)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
stripline = CSX.AddMetal("stripline")
stripline.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
_port1 = StripLinePort(CSX, port_nr=1, metal_prop=stripline,
                       start=np.array([W / 2, -BOARD, H_SUB]),
                       stop=np.array([-W / 2, Y0, H_SUB]),
                       prop_dir="y", exc_dir="z", height=H_SUB,
                       excite=1, FeedShift=10 * NEAR,
                       MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = StripLinePort(CSX, port_nr=2, metal_prop=stripline,
                       start=np.array([-W / 2, BOARD, H_SUB]),
                       stop=np.array([W / 2, Y1, H_SUB]),
                       prop_dir="y", exc_dir="z", height=H_SUB,
                       excite=0, FeedShift=10 * NEAR,
                       MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in stripline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _cps_lines(p: dict[str, Any]) -> str:
    # 共面带 CPS（C9 传输线族 II）：两条等宽带（沿 y）夹中央缝，无地——基板
    # 下方空气（render_script 底 MUR + 域向下 AIR_TOP，slot 同款）。端口 =
    # 两端 LumpedPort 跨缝差分直馈/端接（refs §8 官方 AddLumpedPort 范式，
    # _dipole_lines 同法）：R=闭式 Z0（core/calculators._cps_ri，render_script
    # 按本次基板注入 _cps_r_ohm 并同步作 CalcPort 参考阻抗；直调兜底按
    # _DEFAULT_SUB 精算）。带内 |S11| 深谷 = Z0 锚；εeff 锚 = S21 解缠相位
    # 斜率（LumpedPort 无 β 属性，β 金标准如实降级，见 TEMPLATE_META）。
    # openEMS.ports 无 CPS/slotline 端口原语（本 session 枚举实证），差分
    # 集总馈是唯一不触 C5 阻塞的口径。
    r_ohm = p.get("_cps_r_ohm")
    if r_ohm is None:
        from rfauto.core.calculators import _cps_ri

        r_ohm = round(_cps_ri(float(p.get("w_mm", 2.95)),
                              float(p.get("gap_mm", 0.5)),
                              float(_DEFAULT_SUB["h_mm"]),
                              float(_DEFAULT_SUB["er"]))[1], 4)
    return f'''W = {p.get("w_mm", 2.95)!r} * 1e-3
GAP = {p.get("gap_mm", 0.5)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
R_PORT = {float(r_ohm)!r}   # LumpedPort R = CPS 闭式 Z0（匹配端接；CalcPort 同参考）
cps = CSX.AddMetal("cps")
cps.AddBox((-GAP / 2 - W, Y0, H_SUB), (-GAP / 2, Y1, H_SUB), priority=10)
cps.AddBox((GAP / 2, Y0, H_SUB), (GAP / 2 + W, Y1, H_SUB), priority=10)
# 两端 LumpedPort 跨缝差分（官方 Helical/Dipole 教程口径 AddLumpedPort(
# port_nr, R, start, stop, norm_dir, excite)）：norm='x' 沿缝宽方向，
# port1 激励、port2 无激励=R 端接 + 探针
_port1 = FDTD.AddLumpedPort(1, R_PORT, np.array([-GAP / 2, Y0, H_SUB]),
                            np.array([GAP / 2, Y0, H_SUB]), "x", 1.0, priority=5)
_port2 = FDTD.AddLumpedPort(2, R_PORT, np.array([-GAP / 2, Y1, H_SUB]),
                            np.array([GAP / 2, Y1, H_SUB]), "x", 0.0, priority=5)
for _prim in cps.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _suspended_stripline_lines(p: dict[str, Any]) -> str:
    # 悬置带线（C9 传输线族 II）：腔高 B=b_mm（上下地=域 z 边界 PEC，
    # render_script top_bc PEC 同 stripline），零厚度带在中面 z=B/2；基板
    # H_SUB 以带为中面对称悬浮 [B/2−H/2, B/2+H/2]（substrate_block 按 params
    # 字面注入，面坐标与 z 网格同源）。端口 = StripLinePort（height=B/2=带-地
    # 半高，v0.37 源码 L914+ 口径，同 stripline）→ β 金标准可用。
    return f'''W = {p.get("w_mm", 0.9058)!r} * 1e-3
B = {p.get("b_mm", 1.016)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
ZC = B / 2
Y0 = -L / 2
Y1 = L / 2
ssl = CSX.AddMetal("suspended_stripline")
ssl.AddBox((-W / 2, Y0, ZC), (W / 2, Y1, ZC), priority=10)
_port1 = StripLinePort(CSX, port_nr=1, metal_prop=ssl,
                       start=np.array([W / 2, -BOARD, ZC]),
                       stop=np.array([-W / 2, Y0, ZC]),
                       prop_dir="y", exc_dir="z", height=ZC,
                       excite=1, FeedShift=10 * NEAR,
                       MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = StripLinePort(CSX, port_nr=2, metal_prop=ssl,
                       start=np.array([-W / 2, BOARD, ZC]),
                       stop=np.array([W / 2, Y1, ZC]),
                       prop_dir="y", exc_dir="z", height=ZC,
                       excite=0, FeedShift=10 * NEAR,
                       MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in ssl.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _wstep_lines(p: dict[str, Any]) -> str:
    # 微带宽度阶跃（WP2.2 不连续性基元）：窄段/宽段各半长，单阶梯跃在
    # 中点；两端 MSLPort（手法同 mline）。锚判据=skrf 级联 HJ 闭式
    # （两段理想 TL 级联为确定性裁判，引擎-理想偏差即阶梯寄生贡献）。
    return f'''W1 = {p.get("w1_mm", _nominal_width.W50_MM)!r} * 1e-3
W2 = {p.get("w2_mm", 1.897)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
YM = 0.0
Y1 = L / 2
wstep = CSX.AddMetal("wstep")
wstep.AddBox((-W1 / 2, Y0, H_SUB), (W1 / 2, YM, H_SUB), priority=10)
wstep.AddBox((-W2 / 2, YM, H_SUB), (W2 / 2, Y1, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=wstep,
                 start=np.array([W1 / 2, -BOARD, H_SUB]),
                 stop=np.array([-W1 / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=wstep,
                 start=np.array([-W2 / 2, BOARD, H_SUB]),
                 stop=np.array([W2 / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in wstep.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _bend_lines(p: dict[str, Any]) -> str:
    # 微带直角弯折（WP2.2 不连续性基元）：L 形两臂各 arm_len，未切角
    # 标准口径（mitered 为变体）。裁判=理想级联（同宽两段级联完全
    # 匹配，弯角寄生是引擎唯一反射源）→ |S11| 绝对门 -15dB。
    return f'''W = {p.get("w_mm", _nominal_width.W50_MM)!r} * 1e-3
A = {p.get("arm_len_mm", 20.0)!r} * 1e-3
bend = CSX.AddMetal("bend")
bend.AddBox((-W / 2, -A, H_SUB), (W / 2, 0.0, H_SUB), priority=10)
bend.AddBox((0.0, -W / 2, H_SUB), (A, W / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=bend,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, -A, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-A + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=bend,
                 start=np.array([BOARD, W / 2, H_SUB]),
                 stop=np.array([A, -W / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - A) / 3, priority=10)
for _prim in bend.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _via_lines(p: dict[str, Any]) -> str:
    # 过孔过渡（WP2.2 收官基元）：双层板 z∈[0,2H]，内层地方 sheet z=H
    # 带方反焊盘（四盒拼孔，边长 2*antipad），过孔金属柱 r_via 穿孔
    # 连接顶带（z=2H, port1）与底带（z=0, port2）。
    # 同轴口径 Z≈(60/√εr)·ln(r_pad/r_via)（标称 ≈52.5Ω 近 50Ω）。
    # 过孔柱=CSPrimCylinder（笛卡尔网格阶梯化，r≪cell 不加网格线）。
    # 无 PEC 边界（地=内层 sheet，z 双 MUR）——全站首例。
    return f'''W = {p.get("w_mm", _nominal_width.W50_MM)!r} * 1e-3
AP = {p.get("antipad_mm", 0.8)!r} * 1e-3
RV = {p.get("r_via_mm", 0.15)!r} * 1e-3
Y0 = -BOARD
Y1 = BOARD
H_MID = H_SUB          # 内层地平面（板半高）
H_TOP = 2 * H_SUB      # 顶层带平面
via_gnd = CSX.AddMetal("via_gnd")
via_gnd.AddBox((-BOARD, -BOARD, H_MID), (-AP, AP, H_MID), priority=10)
via_gnd.AddBox((AP, -BOARD, H_MID), (BOARD, AP, H_MID), priority=10)
via_gnd.AddBox((-AP, -BOARD, H_MID), (AP, -AP, H_MID), priority=10)
via_gnd.AddBox((-AP, AP, H_MID), (AP, BOARD, H_MID), priority=10)
via_strip = CSX.AddMetal("via_strip")
via_strip.AddBox((-W / 2, Y0, H_TOP), (W / 2, 0.0, H_TOP), priority=10)
via_strip.AddBox((-W / 2, 0.0, 0.0), (W / 2, Y1, 0.0), priority=10)
via_barrel = CSX.AddMetal("via_barrel")
via_barrel.AddCylinder([0.0, 0.0, 0.0], [0.0, 0.0, H_TOP], radius=RV,
                       priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=via_strip,
                 start=np.array([W / 2, -BOARD, H_TOP]),
                 stop=np.array([-W / 2, 0.0, H_MID]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=via_strip,
                 start=np.array([-W / 2, BOARD, 0.0]),
                 stop=np.array([W / 2, 0.0, H_MID]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
for _prim in via_gnd.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in via_strip.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _atten_pi_lines(p: dict[str, Any]) -> str:
    # π 型电阻衰减器（WP2.3 Tier 1 首族）：串臂 LumpedElement 桥接中点
    # 断口（ny=y），两端对地 shunt LumpedElement（ny=z，短柱接 z-min
    # PEC 地；wilkinson 隔离电阻同款渲染机制已验证）。
    # 电阻值=E4 attenuator_pi ABCD 闭式（确定性裁判，同源）。
    return f'''W = {p.get("w_mm", _nominal_width.W50_MM)!r} * 1e-3
D = {p.get("shunt_off_mm", 6.0)!r} * 1e-3
G = 0.5 * 1e-3
R_SER = {p.get("r_series_mid_ohm", 71.151)!r}
R_SH = {p.get("r_shunt_end_ohm", 96.248)!r}
pi_pad = CSX.AddMetal("pi_pad")
pi_pad.AddBox((-W / 2, -BOARD, H_SUB), (W / 2, -G, H_SUB), priority=10)
pi_pad.AddBox((-W / 2, G, H_SUB), (W / 2, BOARD, H_SUB), priority=10)
_r_series = CSX.AddLumpedElement("r_series", ny=1, caps=True, R=R_SER)
_r_series.AddBox((-W / 2, -G, H_SUB), (W / 2, G, H_SUB), priority=10)
_r_sh1 = CSX.AddLumpedElement("r_shunt1", ny=2, caps=True, R=R_SH)
_r_sh1.AddBox((-W / 2, -D - G / 2, 0.0), (W / 2, -D + G / 2, H_SUB),
              priority=10)
_r_sh2 = CSX.AddLumpedElement("r_shunt2", ny=2, caps=True, R=R_SH)
_r_sh2.AddBox((-W / 2, D - G / 2, 0.0), (W / 2, D + G / 2, H_SUB),
              priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=pi_pad,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, -D, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-D + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=pi_pad,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, D, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - D) / 3, priority=10)
for _prim in pi_pad.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _atten_t_lines(p: dict[str, Any]) -> str:
    # T 型电阻衰减器（WP2.3 横向变体）：±d 断口各串 LumpedElement
    # （ny=y），中点对地全带宽 shunt LumpedElement（ny=z）。
    # 电阻值=E4 attenuator_t ABCD 闭式（确定性裁判，同源）。
    return f'''W = {p.get("w_mm", _nominal_width.W50_MM)!r} * 1e-3
D = {p.get("shunt_off_mm", 6.0)!r} * 1e-3
G = 0.5 * 1e-3
R_SER = {p.get("r_series_arm_ohm", 25.975)!r}
R_MID = {p.get("r_shunt_mid_ohm", 35.136)!r}
t_pad = CSX.AddMetal("t_pad")
t_pad.AddBox((-W / 2, -BOARD, H_SUB), (W / 2, -D - G / 2, H_SUB), priority=10)
t_pad.AddBox((-W / 2, -D + G / 2, H_SUB), (W / 2, D - G / 2, H_SUB),
             priority=10)
t_pad.AddBox((-W / 2, D + G / 2, H_SUB), (W / 2, BOARD, H_SUB), priority=10)
_r_ser1 = CSX.AddLumpedElement("r_series1", ny=1, caps=True, R=R_SER)
_r_ser1.AddBox((-W / 2, -D - G / 2, H_SUB), (W / 2, -D + G / 2, H_SUB),
               priority=10)
_r_ser2 = CSX.AddLumpedElement("r_series2", ny=1, caps=True, R=R_SER)
_r_ser2.AddBox((-W / 2, D - G / 2, H_SUB), (W / 2, D + G / 2, H_SUB),
               priority=10)
_r_mid = CSX.AddLumpedElement("r_shunt_mid", ny=2, caps=True, R=R_MID)
_r_mid.AddBox((-W / 2, -G / 2, 0.0), (W / 2, G / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=t_pad,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, -D, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-D + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=t_pad,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, D, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - D) / 3, priority=10)
for _prim in t_pad.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _gysel_layout(params: dict[str, Any]) -> dict[str, float]:
    """Gysel L-jog 等长变体几何单一事实源（mm）——render/_near_points/geometry_spec 共用。

    P2⑪ 拓扑重设计（2026-09-16 离线审计定版）：矩形六节环的桥带（顶边）继承
    臂 λ/4 跨度 2·arm_len，对 50Ω λ/2 设计值 2·iso_len 有 +2.32% 二阶偏差
    （电路级归因主因：@f0 S32/S11 封顶 -34.8dB，skrf 装配实测）。L-jog 变体把
    负载节点 Δ1/Δ2 移到 x=±iso_len（桥带跨度=2·iso_len=λ/2 精确），隔离线走
    竖直段 YJ + 顶端横移 jog=|arm_len−iso_len|（竖直+横移=iso_len 保 λ/4 电
    长度；两处未切角 90° 弯折构成 EM 地板）。方向无关：arm_len>iso_len 时 Δ
    内移（nominal，jog=0.412mm），反之外移——四参数单键扰动均保持合法
    （审计 ×1.37 扰动口径）。
    守卫：YJ>0 ⟺ arm_len<2·iso_len（否则竖直段不存在，六节环不可实现）。
    候选取舍（四候选 skrf 装配 @2.3/2.5/2.7GHz，test_gysel_template 固化）：
    真斜梯形电路级同构但 0.412mm 横移在 0.4mm 网格=1 胞，斜边逐行栅格化要么
    亚网格步距（~9µm/行）触发 #152 CFL 塌缩、要么退化为折线——不采；桥带
    70.7Ω 变体 @f0 亦理想但带边 2.3GHz S32=-25.3dB 差于矩形 -29.5dB（深度换
    带宽）且偏离 §10 50Ω 桥带官方口径——不采。
    """
    wa = float(params.get("w_arm_mm", 0.6035))
    wf = float(params.get("w_feed_mm", _nominal_width.W50_MM))
    xa = float(params.get("arm_len_mm", 18.162))
    yi = float(params.get("iso_len_mm", 17.75))
    jog = abs(xa - yi)
    yj = yi - jog
    if not yj > 0.0:
        raise ValueError(
            f"gysel L-jog 拓扑：竖直段 YJ=iso_len−|arm_len−iso_len|={yj:.4f}mm ≤0"
            f"（arm_len={xa} ≥ 2·iso_len={2 * yi}），六节环不可实现")
    # C7 followUp（2026-09-21）：_jog_miter_mm 切角旋钮（mitered-jog 变体，
    # opt-in 与 _end_criteria/_sub_cells 先例同构，不入 params/NOMINAL 参数表）。
    # 0（缺省）=未切角基线，渲染逐字节不变；c>0 时每侧 jog 转角外上角开 c×c
    # 台阶缺口（45° 切角的阶梯网格近似），几何恒等=金属并集减两缺口，竖直段/
    # 桥带/端口/电长度口径不动。守卫 0≤c<W_F（c≥W_F 缺口段降高非正；c<W_F
    # 亦蕴含缺口必落在 jog 段全长 |arm−iso|+W_F 内）。缺口语义见
    # _gysel_jog_lines。真机对照轮（TODO 排空五轮 followUps）用它做 A/B。
    _miter_raw = params.get("_jog_miter_mm")
    c_mit = float(_miter_raw) if _miter_raw is not None else 0.0
    if not (math.isfinite(c_mit) and 0.0 <= c_mit < wf):
        raise ValueError(
            f"gysel _jog_miter_mm 须为 0 ≤ c < w_feed_mm={wf!r}（0=未切角"
            f"缺省），得到 {c_mit!r}")
    return {"wa": wa, "wf": wf, "xa": xa, "yi": yi,
            "jog": jog, "yj": yj, "xb": yi, "g": 0.5, "miter": c_mit}


def _gysel_jog_lines(lay: dict[str, float]) -> str:
    """gysel 顶端 L-jog 横移段渲染文本（缺省两盒；``_jog_miter_mm``>0 切角档）。

    切角档（C7 followUp 2026-09-21）：每侧 jog 段拆"主段（全高）+ 缺口段
    （降高 c）"两盒——转角外上角（与竖直段齐平的 jog 端、y=YJ+W_F/2 顶缘）
    开 c×c 台阶缺口，为 45° miter 切角在阶梯网格下的单步近似（bend 模板
    |S11|<-15dB 口径的弯角寄生机理=外角金属集中）。几何恒等：金属并集=原
    jog 段减两侧转角缺口；竖直段/桥带/端口/负载盒不动。缺口只落在 jog 段
    顶带（y>YJ 侧，竖直段止于 YJ 不覆盖），故竖直段无需拆盒。
    """
    c = float(lay["miter"])
    if c <= 0.0:
        return (
            "# 顶端 L-jog 横移段（与桥带共线同宽）：转角 x=±XA → Δ 节点 x=±XB\n"
            "gysel.AddBox((min(-XA, -XB) - W_F / 2, YJ - W_F / 2, H_SUB),\n"
            "             (max(-XA, -XB) + W_F / 2, YJ + W_F / 2, H_SUB), priority=10)\n"
            "gysel.AddBox((min(XA, XB) - W_F / 2, YJ - W_F / 2, H_SUB),\n"
            "             (max(XA, XB) + W_F / 2, YJ + W_F / 2, H_SUB), priority=10)\n")
    # 坐标一律换算米（脚本主体 XA/YJ/W_F 同单位）——2026-09-21 C7 A/B 审计
    # 修正：初版把 mm 字面量直排（盒落 ±17m 越域 1000×，exec 金属原语实测
    # 抓出，#212 制度化面）；缺省分支走符号式变量不受影响。
    wf, yj = float(lay["wf"]) * 1e-3, float(lay["yj"]) * 1e-3
    xa, xb = float(lay["xa"]) * 1e-3, float(lay["xb"]) * 1e-3
    c_m = c * 1e-3
    lines = [f"# 顶端 L-jog 横移段（mitered-jog 切角档 c={c!r}mm：转角外上角"
             "台阶缺口，C7 followUp 2026-09-21；缺口只削 jog 顶带，"
             "竖直段/桥带不动；坐标=米）"]
    for s in (1.0, -1.0):
        m1, m2 = sorted((s * min(xa, xb), s * max(xa, xb)))
        jlo, jhi = m1 - wf / 2, m2 + wf / 2   # 与缺省 min/max 盒完全同区间
        # 转角外上角 x：Δ 内移（xb<xa）时 jog 与竖直段外侧缘齐平（x=±(XA+W_F/2)），
        # 外移时与内侧缘齐平（x=±(XA−W_F/2)）；缺口自角点向 jog 远端延伸 c
        cx = s * (xa + wf / 2) if xb < xa else s * (xa - wf / 2)
        nlo, nhi = (sorted((cx, cx - s * c_m)) if xb < xa
                    else sorted((cx, cx + s * c_m)))
        if abs(nlo - jlo) < 1e-12:      # 缺口在 jog 低端：主段=[nhi, jhi]
            mlo, mhi = nhi, jhi
        else:                           # 缺口在高端：主段=[jlo, nlo]
            mlo, mhi = jlo, nlo
        lines.append(
            f"gysel.AddBox(({mlo!r}, {yj - wf / 2!r}, H_SUB),\n"
            f"             ({mhi!r}, {yj + wf / 2!r}, H_SUB), priority=10)\n"
            f"gysel.AddBox(({nlo!r}, {yj - wf / 2!r}, H_SUB),\n"
            f"             ({nhi!r}, {yj + wf / 2 - c_m!r}, H_SUB), priority=10)")
    return "\n".join(lines) + "\n"


def _gysel_lines(p: dict[str, Any]) -> str:
    # Gysel 功分器（WP2.3 横向变体，#206 理论核验轮定版拓扑 + P2⑪ L-jog 等长
    # 几何重设计 2026-09-16，对照 Microwaves101 "Gysel even/odd mode analysis"
    # 官方口径）：六节 λ/4 环。环序：P1—[70.7Ω λ/4 臂]—P2—[50Ω λ/4 隔离线=
    # 竖直 YJ+顶端横移 jog]—Δ1(x=−iso_len)—[50Ω λ/2 桥带，跨度 2·iso_len 精确，
    # 中点开路=第 6 节点]—Δ2(x=+iso_len)—[50Ω λ/4 隔离线]—P3—[70.7Ω λ/4 臂]—P1；
    # Δ1/Δ2 各接 50Ω LumpedElement 端接（atten_pi shunt 同款：ny=2，盒 z 跨
    # 0→H_SUB 短柱接 z-min PEC 地）。
    # 隔离机制（skrf 六段线+双负载装配 @f0 实证，理论核验轮）：
    # 偶模（输出同相）：臂把 Σ 结点 2·Z0 变换为 Z0（输入匹配）；桥带中点开路
    #   经半段 λ/4 变短路压住 Δ 点、再经 λ/4 隔离线变开路——负载支路在输出
    #   端不可见；奇模（反相）：P1 结点/桥带中点=虚拟地，臂与桥带各经 λ/4 变
    #   开路，输出只见 λ/4 隔离线端接的 50Ω 负载（被吸收）。Γe=Γo=0 →
    #   S22=(Γe+Γo)/2=0 且 S32=(Γe−Γo)/2=0。
    # 判废锚（同轮 skrf 装配证据）：无桥带朴素拓扑 S21=-6.53dB/S11=-9.5dB/
    #   S32=-15.6dB；合并单负载拓扑 S21=-9.03dB/S32=-2.5dB——λ/2 桥带是隔离
    #   的必要环节。
    # 几何（_gysel_layout 单一事实源）：矩形旧版桥带继承 2·arm_len（+2.32%）
    #   电路级把 @f0 S32/S11 封顶 -34.8dB（P2⑪ 归因主因）；L-jog 变体电路级
    #   @f0 ≤-88dB（装配实测），EM 地板由两处未切角 90° 弯折决定（bend 模板
    #   |S11|<-15dB 口径估 -35~-40dB）。#211 pt2 矩形真跑基线 S32=-32.6dB/
    #   S11=-26.7dB；定案看 pt3 改善量如实落账。
    # 门：β±2%、|S21|/|S31| -3±1dB 且差≤0.5dB、|S32|≤-15dB、|S11|≤-10dB。
    lay = _gysel_layout(p)
    jog_src = _gysel_jog_lines(lay)
    return f'''W_A = {lay["wa"]!r} * 1e-3
W_F = {lay["wf"]!r} * 1e-3
XA = {lay["xa"]!r} * 1e-3
YI = {lay["yi"]!r} * 1e-3
JOG = {lay["jog"]!r} * 1e-3   # L-jog 横移 |arm_len−iso_len|
YJ = {lay["yj"]!r} * 1e-3     # 隔离线竖直段 iso_len−jog（竖直+横移=λ/4）
XB = {lay["xb"]!r} * 1e-3     # Δ 节点 x=±iso_len → 桥带跨度 2·iso_len=λ/2
G = {lay["g"]!r} * 1e-3
gysel = CSX.AddMetal("gysel")
# 下边双臂（70.7Ω，λ/4×2）：P1 结点居中分叉
gysel.AddBox((-XA, -W_A / 2, H_SUB), (XA, W_A / 2, H_SUB), priority=10)
# 左右竖边（50Ω λ/4 隔离线竖直段 YJ）：P2/P3 角部 → jog 转角
gysel.AddBox((-XA - W_F / 2, 0.0, H_SUB),
             (-XA + W_F / 2, YJ, H_SUB), priority=10)
gysel.AddBox((XA - W_F / 2, 0.0, H_SUB),
             (XA + W_F / 2, YJ, H_SUB), priority=10)
{jog_src}# 顶边桥带（50Ω λ/2：Δ1→Δ2 跨度 2·XB=2·iso_len 精确，中点开路节点悬空不连接）
gysel.AddBox((-XB - W_F / 2, YJ - W_F / 2, H_SUB),
             (XB + W_F / 2, YJ + W_F / 2, H_SUB), priority=10)
# 隔离负载 Δ1/Δ2（x=±XB）：50Ω LumpedElement 短柱（z 0→H_SUB，ny=2）
_r1 = CSX.AddLumpedElement("iso_load1", ny=2, caps=True, R=50.0)
_r1.AddBox((-XB - W_F / 2, YJ - G / 2, 0.0),
           (-XB + W_F / 2, YJ + G / 2, H_SUB), priority=10)
_r2 = CSX.AddLumpedElement("iso_load2", ny=2, caps=True, R=50.0)
_r2.AddBox((XB - W_F / 2, YJ - G / 2, 0.0),
           (XB + W_F / 2, YJ + G / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=gysel,
                 start=np.array([W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_F / 2, 0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=gysel,
                 start=np.array([-XA + W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([-XA - W_F / 2, 0, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=gysel,
                 start=np.array([XA + W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([XA - W_F / 2, 0, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in gysel.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _tjunc_lines(p: dict[str, Any]) -> str:
    # 微带 T 接头（WP2.2 不连续性基元）：主线沿 y（端口 1/2 在 y 边界，
    # mline 已验证手法），支臂沿 +x（端口 3 在 x 边界，prop_dir='x'）。
    # 全臂同宽 50Ω 对称均分口径。锚判据=skrf 理想三端口结点
    # （S=(1/3)[[-1,2,2],[2,-1,2],[2,2,-1]]）+ 三条 HJ 线级联裁判。
    return f'''W_F = {p.get("w_feed_mm", _nominal_width.W50_MM)!r} * 1e-3
TL = {p.get("through_len_mm", 25.0)!r} * 1e-3
BL = {p.get("branch_len_mm", 20.0)!r} * 1e-3
tjunc = CSX.AddMetal("tjunc")
tjunc.AddBox((-W_F / 2, -TL, H_SUB), (W_F / 2, TL, H_SUB), priority=10)
tjunc.AddBox((0.0, -W_F / 2, H_SUB), (BL, W_F / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=tjunc,
                 start=np.array([W_F / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_F / 2, -TL, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(-TL + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=tjunc,
                 start=np.array([-W_F / 2, BOARD, H_SUB]),
                 stop=np.array([W_F / 2, TL, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - TL) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=tjunc,
                 start=np.array([BOARD, W_F / 2, H_SUB]),
                 stop=np.array([BL, -W_F / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - BL) / 3, priority=10)
for _prim in tjunc.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _wilk_lines(p: dict[str, Any]) -> str:
    # 拓扑：输入馈线 → T 型分叉 → 双 λ/4 臂（x 向并列，臂间距 8mm）→ 两路
    # 输出；臂末端跨接 100Ω 隔离电阻（LumpedElement）。
    # 参数语义（2026-09-04 统一，对齐 recipe/HFSS/fake 三方口径）：
    # series_w_mm = 70.7Ω λ/4 臂宽（窄），shunt_w_mm = 50Ω 馈线宽（宽）。
    return f'''W_IN = {p.get("shunt_w_mm", _nominal_width.W50_MM_R3)!r} * 1e-3
W_ARM = {p.get("series_w_mm", 0.604)!r} * 1e-3
L_ARM = {p.get("arm_len_mm", 18.1)!r} * 1e-3
GAP = 8.0 * 1e-3
XA = GAP / 2 + W_ARM / 2
Y_T = -30e-3
Y_END = Y_T + L_ARM
mline = CSX.AddMetal("microstrip")
mline.AddBox((-XA - W_ARM / 2, Y_T, H_SUB), (XA + W_ARM / 2, Y_T + W_ARM, H_SUB), priority=10)
mline.AddBox((-XA - W_ARM / 2, Y_T, H_SUB), (-XA + W_ARM / 2, Y_END, H_SUB), priority=10)
mline.AddBox((XA - W_ARM / 2, Y_T, H_SUB), (XA + W_ARM / 2, Y_END, H_SUB), priority=10)
resistor = CSX.AddLumpedElement("isolation_resistor", ny=0, caps=True, R=100.0)
resistor.AddBox((-GAP / 2, Y_END - W_ARM / 2, H_SUB), (GAP / 2, Y_END + W_ARM / 2, H_SUB), priority=5)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([W_IN / 2, -BOARD, H_SUB]),
                 stop=np.array([-W_IN / 2, Y_T, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y_T + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([-XA + W_IN / 2, BOARD, H_SUB]),
                 stop=np.array([-XA - W_IN / 2, Y_END, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y_END) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=mline,
                 start=np.array([XA + W_IN / 2, BOARD, H_SUB]),
                 stop=np.array([XA - W_IN / 2, Y_END, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y_END) / 3, priority=10)
# MSLPort 自动补画的馈线原语默认 priority=0，会输给手画金属的 priority=10
# 而被算子判 "Unused primitive"——统一提到 10（官方口径：金属优先级最高）。
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _patch_lines(p: dict[str, Any]) -> str:
    # 结构 = 官方 Simple Patch Antenna（2026-09-05 冒烟审计后重构，对照
    # wiki.openems.de Tutorial: Simple Patch Antenna）：
    # - patch_len_mm = 谐振 λ/2 轴（x 向）；patch_w_mm = 非谐振宽（y 向）；
    # - 馈电 = LumpedPort 底探针（R=50，z 跨基板 0→H_SUB，y 向 2mm 宽、
    #   x 向 0.2mm，位置 x=-feed_offset_mm 沿谐振轴——官方 feed.pos 口径，
    #   feed_offset 自贴片中心起算）。
    #   消费 feed_offset_mm（官方口径 x=-off，本文件即全链单源裁判面；
    #   #154 单源化 2026-10-03：fake R_in=R_edge·sin²(π·off/L)、HFSS probe
    #   (0,-feed_offset) 谐振轴、综合 off=(L/π)·arcsin√(Rin_t/Rin_edge)
    #   四面同基——原"fake/HFSS 自边 cos²"异语义分裂已收口）。
    # 旧边缘微带馈（MSLPort）两处结构性错误（冒烟证据
    # runs/audit_freq_scale/smoke_patch_auto/ 谷位 3.08GHz、s11@2.4=+0.4dB
    # 非物理）：①辐射器件 AIR_SIDE 把域扩到 ±(BOARD+λ0/4)，而端口面仍贴
    # ±BOARD——馈线止于域中，违反"端口面贴 PML 边界"铁律，入射/反射分解
    # 失效；②馈点 x=0 是 patch_len 谐振模的场节点，谐振根本激励不起来。
    # 另：更早"底部零宽探针不耦合（|S11|≡1）"是零宽盒激励体积坍缩（铁律
    # "激励盒必须与网格对齐"）——本版 0.2×2mm 盒 + _near_points 盒边进
    # 网格，官方教程同款。
    return f'''PL = {p.get("patch_len_mm", 34.9)!r} * 1e-3
PW = {p.get("patch_w_mm", 50.0)!r} * 1e-3
FEED_X = -{p.get("feed_offset_mm", 5.5)!r} * 1e-3   # 官方口径：x=-feed_offset
patch = CSX.AddMetal("patch")
patch.AddBox((-PL / 2, -PW / 2, H_SUB), (PL / 2, PW / 2, H_SUB), priority=10)
_port1 = LumpedPort(CSX, port_nr=1, R=50.0,
                    start=np.array([FEED_X - 0.1e-3, -1e-3, 0]),
                    stop=np.array([FEED_X + 0.1e-3, 1e-3, H_SUB]),
                    exc_dir="z", excite=1, priority=5)
_port2 = _port1   # 单端口模板：footer 的 single-port fallback 口径（S21 列≡S11）
'''


def _branchline_lines(p: dict[str, Any]) -> str:
    # 标准角馈 branchline（2026-09-05 重构，对照 Microwaves101/PMC 口径）：
    # 正方形环（横臂 series_w=35.35Ω 串联臂、竖臂 shunt_w=50Ω 并联臂，各 λ/4）
    # + 四角 50Ω 馈线到端口面。
    # 旧版三处结构性错误：横竖阻抗反置 / 臂中点馈电 / 隔离端悬空。
    # 2026-09-16 四端口升级（openems-real-smoke-bundle ④）：port4 隔离端由
    # "馈线延至 PML 端接"改为真 MSLPort（端口面贴板边 x=−BOARD，与 port2 镜像
    # 同口径 MeasPlaneShift），四端口 excite 随 _excite_port 四态切换
    # （ratrace 范式）——渲染脚本尾部走单激励 9 列 CSV，整 4×4 由
    # openems_rotation.solve_smatrix_openems 进程隔离轮转装配（#208）。
    # 端口语义与 linkage.field_circuit_anchor.branchline_smatrix 一致：
    # 串联臂 1-2 / 4-3（横臂 35.35Ω），并联臂 1-4 / 2-3（竖臂 50Ω）；
    # S21=直通、S31=耦合、S41=隔离。
    ep = int(p.get("_excite_port", 1) or 1)
    return f'''ARM_L = {p.get("arm_len_mm", 20.5)!r} * 1e-3
SW = {p.get("series_w_mm", 1.87)!r} * 1e-3      # 横臂 35.35Ω（串联臂）
SHW = {p.get("shunt_w_mm", 1.11)!r} * 1e-3      # 竖臂/馈线 50Ω
HALF = ARM_L / 2
mline = CSX.AddMetal("microstrip")
mline.AddBox((-HALF - SHW / 2, HALF - SW / 2, H_SUB), (HALF + SHW / 2, HALF + SW / 2, H_SUB), priority=10)
mline.AddBox((-HALF - SHW / 2, -HALF - SW / 2, H_SUB), (HALF + SHW / 2, -HALF + SW / 2, H_SUB), priority=10)
mline.AddBox((-HALF - SHW / 2, -HALF, H_SUB), (-HALF + SHW / 2, HALF, H_SUB), priority=10)
mline.AddBox((HALF - SHW / 2, -HALF, H_SUB), (HALF + SHW / 2, HALF, H_SUB), priority=10)
# 四角 50Ω 馈线：p1 左下向下 / p2 右下向右 / p3 右上向上 / p4 隔离端左上向左
# （四端全为 MSLPort，端口面贴板边=域边界；MSLPort 自画同宽馈线段与之重叠）
mline.AddBox((-HALF - SHW / 2, -BOARD, H_SUB), (-HALF + SHW / 2, -HALF, H_SUB), priority=10)
mline.AddBox((HALF, -HALF - SHW / 2, H_SUB), (BOARD, -HALF + SHW / 2, H_SUB), priority=10)
mline.AddBox((HALF - SHW / 2, HALF, H_SUB), (HALF + SHW / 2, BOARD, H_SUB), priority=10)
mline.AddBox((-BOARD, HALF - SHW / 2, H_SUB), (-HALF, HALF + SHW / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([-HALF + SHW / 2, -BOARD, H_SUB]),
                 stop=np.array([-HALF - SHW / 2, -HALF, 0]),
                 prop_dir="y", exc_dir="z", excite={1 if ep == 1 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([BOARD, -HALF + SHW / 2, H_SUB]),
                 stop=np.array([HALF, -HALF - SHW / 2, 0]),
                 prop_dir="x", exc_dir="z", excite={1 if ep == 2 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=mline,
                 start=np.array([HALF + SHW / 2, BOARD, H_SUB]),
                 stop=np.array([HALF - SHW / 2, HALF, 0]),
                 prop_dir="y", exc_dir="z", excite={1 if ep == 3 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
_port4 = MSLPort(CSX, port_nr=4, metal_prop=mline,
                 start=np.array([-BOARD, HALF + SHW / 2, H_SUB]),
                 stop=np.array([-HALF, HALF - SHW / 2, 0]),
                 prop_dir="x", exc_dir="z", excite={1 if ep == 4 else 0}, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - HALF) / 3, priority=10)
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _dipole_lines(p: dict[str, Any]) -> str:
    # 官方口径重写（WP1.3，#191 refs §8：Helical/Dipole-SAR 教程）：
    # 自由空间细带偶极子（无基板无地，域全 MUR 底 MUR），振子沿 x、
    # 位于 z=0 平面，中央 gap 处 LumpedPort 直馈（R=z0_ohm，norm='x'）。
    # 首版（基板顶面 PEC 带 + MSL 微带馈混合怪 + 底 PEC 镜像）按官方
    # 口径废弃（⑭ 拓扑疑问的裁决）。
    return f'''DIP_LEN = {p.get("dipole_len_mm", 58.0)!r} * 1e-3
DIP_W = {p.get("dipole_w_mm", 2.0)!r} * 1e-3
GAP = {p.get("gap_mm", 2.0)!r} * 1e-3
dipole = CSX.AddMetal("dipole")
dipole.AddBox((-DIP_LEN / 2, -DIP_W / 2, 0), (-GAP / 2, DIP_W / 2, 0), priority=10)
dipole.AddBox((GAP / 2, -DIP_W / 2, 0), (DIP_LEN / 2, DIP_W / 2, 0), priority=10)
# 中央 gap LumpedPort 直馈（官方 Helical 教程口径：AddLumpedPort(
# port_nr, R, start, stop, norm_dir, excite)）
_port1 = FDTD.AddLumpedPort(1, 50.0, np.array([-GAP / 2, 0, 0]),
                            np.array([GAP / 2, 0, 0]), "x", 1.0, priority=5)
'''


def _coupled_lines(p: dict[str, Any]) -> str:
    return f'''CL_LEN = {p.get("coupled_len_mm", 20.0)!r} * 1e-3
CL_W = {p.get("line_w_mm", 1.0)!r} * 1e-3
CL_GAP = {p.get("gap_mm", 0.5)!r} * 1e-3
mline = CSX.AddMetal("microstrip")
mline.AddBox((-CL_W - CL_GAP / 2, -CL_LEN / 2, H_SUB), (-CL_GAP / 2, CL_LEN / 2, H_SUB), priority=10)
mline.AddBox((CL_GAP / 2, -CL_LEN / 2, H_SUB), (CL_GAP / 2 + CL_W, CL_LEN / 2, H_SUB), priority=10)
mline.AddBox((-CL_W - CL_GAP / 2, -BOARD, H_SUB), (-CL_GAP / 2, -CL_LEN / 2, H_SUB), priority=10)
mline.AddBox((-CL_W - CL_GAP / 2, CL_LEN / 2, H_SUB), (-CL_GAP / 2, BOARD, H_SUB), priority=10)
mline.AddBox((CL_GAP / 2, -BOARD, H_SUB), (CL_GAP / 2 + CL_W, -CL_LEN / 2, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=mline,
                 start=np.array([-CL_GAP / 2, -BOARD, H_SUB]),
                 stop=np.array([-CL_W - CL_GAP / 2, -CL_LEN / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - CL_LEN / 2) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=mline,
                 start=np.array([-CL_GAP / 2, BOARD, H_SUB]),
                 stop=np.array([-CL_W - CL_GAP / 2, CL_LEN / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - CL_LEN / 2) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=mline,
                 start=np.array([CL_GAP / 2 + CL_W, -BOARD, H_SUB]),
                 stop=np.array([CL_GAP / 2, -CL_LEN / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - CL_LEN / 2) / 3, priority=10)
for _prim in mline.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


def _stepped_lines(p: dict[str, Any]) -> str:
    # 馈线宽度独立参数（六百七十一/#1c 修复批）：feed=50Ω HJ 精算 1.1133mm，
    # MSLPort 端口线=50Ω → Z_k=50Ω，#250 参考系分裂机制连根移除（重归一
    # 链退化为恒等）。缺省回退 z1 宽=修复前口径（存量调用/字节面零漂移）；
    # 阶梯设计段（z1/z2 交替）不动——audit 六百六十八①实证 HFSS 侧与
    # z1=96.9Ω/z2=24.8Ω 闭式级联逐门吻合，段链是设计不是病。
    feed_w = p.get("feed_w_mm")
    if feed_w is None:  # None→z1 回退（与 fake_adapter 语义对齐，ge6 审查片3 P3-3）
        feed_w = p.get("z1_width_mm", 0.3)
    return f'''Z1_W = {p.get("z1_width_mm", 0.3)!r} * 1e-3
Z2_W = {p.get("z2_width_mm", 3.0)!r} * 1e-3
FEED_W = {feed_w!r} * 1e-3
SEG_LEN = {p.get("seg_len_mm", 5.0)!r} * 1e-3
N_SEGS = {int(p.get("n_segments", 5))}
TOTAL = N_SEGS * SEG_LEN
filt = CSX.AddMetal("filter")
filt.AddBox((-FEED_W / 2, -BOARD, H_SUB), (FEED_W / 2, -TOTAL / 2, H_SUB), priority=10)
for i in range(N_SEGS):
    w = Z1_W if i % 2 == 0 else Z2_W
    y0 = -TOTAL / 2 + i * SEG_LEN
    filt.AddBox((-w / 2, y0, H_SUB), (w / 2, y0 + SEG_LEN, H_SUB), priority=10)
filt.AddBox((-FEED_W / 2, TOTAL / 2, H_SUB), (FEED_W / 2, BOARD, H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=filt,
                 start=np.array([FEED_W / 2, -BOARD, H_SUB]),
                 stop=np.array([-FEED_W / 2, -TOTAL / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - TOTAL / 2) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=filt,
                 start=np.array([FEED_W / 2, BOARD, H_SUB]),
                 stop=np.array([-FEED_W / 2, TOTAL / 2, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - TOTAL / 2) / 3, priority=10)
for _prim in filt.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''
