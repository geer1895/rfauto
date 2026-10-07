"""ring_resonator 微带环谐振器族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)

# ═══ §F-A M3 环形谐振器 ring_resonator（2026-09-26 F-A P2 前置段）══════════════
# 方案锚：研究扩充 F-A §2 M3——微带环形谐振器作
# 介质参数提取 fixture（同一工件三用：提取 fixture / 引擎 β 仲裁锚 / VNA 实测
# 样片），闭式 f_n ≈ n·c/(2π·r_mean·√εeff)；tanδ 走 Q 分离
# （1/Q_L = 1/Q_d + 1/Q_c + 1/Q_r）。提取内核（core/dielectric_extract.py）与
# G2 仿真域闭环属后续批次，本模板只交付"几何+渲染+离线审计"四件套。
#
# 近似级别（如实登记，#122；v1 口径）：
# - εeff 取直微带 HJ 值（core/synthesis.forward_z0），未含曲率/色散修正；
# - 间隙耦合按间隙电容口径（耦合度→Q_c 的精确定标属提取批次）；
# - 环带逐网格行栅格化（ratrace 同法，#198 零台阶）但**未做**阶梯化慢波
#   伪象补偿——ratrace_ring_mesh_k 两锚定标于 70.7Ω 线宽，未对本模板的
#   50Ω 环带定标，禁止外推复用；谐振位精度由 G2+HFSS 仲裁另批兑现。
# 几何：闭环环带（r_mean ± w/2）+ 径向对置双 50Ω 馈线（x=0 沿 y，自
# y=±BOARD 板边入，止于环带外缘外 gap 处）；MSLPort 端口面贴 PML_8 域边
# （mline 口径 #154）；FeedShift=10·NEAR、MeasPlaneShift=馈段长/3（官方）。

#: 真空光速（m/s）——环形谐振器闭式 f_n = n·c/(2π·r_mean·√εeff) 单源常量
_C0_M_S = 299792458.0

#: 缺省设计点（与 TEMPLATE_NOMINAL 同源；docs meta.yaml 同值）
RING_RESONATOR_F1_GHZ = 2.5
RING_RESONATOR_W_MM = 1.1134     # 50Ω HJ @2.5GHz rogers4350b（mline/gysel 同源档）
RING_RESONATOR_GAP_MM = 0.4      # 馈线-环带间隙（0.4mm 审计档下 NEAR=0.1≤gap/3）

RING_RESONATOR_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（环形谐振器：S21 谐振指纹 f_n≈n·c/"
                  "(2πr_mean·√εeff) 反演 εr；1/Q_L=1/Q_d+1/Q_c+1/Q_r 分离提"
                  "取 tanδ——F-A M3 口径，提取内核 core/dielectric_extract 属"
                  "后续批次）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["r_mean_mm", "w_mm", "gap_mm", "feed_w_mm"],
    "topology": "微带环形谐振器（F-A M3 材料提取 fixture）：闭环环带"
                "（r_mean±w/2，逐网格行栅格化，ratrace 同法 #198 零台阶）+ "
                "径向对置双 50Ω 间隙耦合馈线（x=0 沿 y，端口面贴 y=±BOARD "
                "PML_8 域边）；对置 180° 馈点对各次模均为场腹（全 n 模可激"
                "励）；z-min PEC 地 + 缺省 rogers4350b 叠层（guided 口径）",
    "param_semantics": "r_mean_mm=环平均半径（谐振尺度：闭环周长 2πr_mean="
                       "n·λg；名义值由 f1 经 HJ εeff 反解 c/(2πf1√εeff)，"
                       "ring_resonator_design_params 单源）；w_mm=环带线宽"
                       "（50Ω HJ 口径 1.1134mm，εeff 随之）；gap_mm=馈线-环"
                       "带间隙（间隙电容耦合 v1 口径，决定 Q_c/抽头强度）；"
                       "feed_w_mm=50Ω 馈线宽（HJ 精算）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
                 "（官方口径）——本模板缺省自动档触发缝分辨守卫（NEAR=0.285mm"
                 "> gap/3），须显式 mesh ≤ 4·gap/3（C3 族同口径）；环带基点缘/"
                 "馈线带缘/馈端与缝缘精确入网 + 缝中线入网（#198/#311）；渲染"
                 "守卫：NEAR≤gap/3（#266 族缝分辨）、feed_len≥42·NEAR（#347 "
                 "族 MeasPlaneShift-FeedShift 分离）、r_in>0；全轴 1µm 近重合"
                 "去重（#152）；端口面贴 PML_8 域边（#154 前节）",
    "smoke_note": "未冒烟（离线审计过，#212，test_ring_resonator_template）；"
                  "近似级别如实登记：v1 闭式未含色散/曲率修正与栅格化慢波补"
                  "偿（见本段头注），εr 提取精度由 G2 闭环+HFSS 仲裁另批兑现",
}


def ring_resonator_design_params(
    f1_ghz: float = RING_RESONATOR_F1_GHZ,
    w_mm: float = RING_RESONATOR_W_MM,
    gap_mm: float = RING_RESONATOR_GAP_MM,
    z0_ohm: float = 50.0,
) -> dict[str, Any]:
    """环形谐振器名义设计点（HJ 精算单源，#1c——名义值禁手算捷径）。

    设计链（方案 F-A M3 闭式）：目标基模 f1 → 50Ω 馈线宽（inverse_width HJ
    自洽回代）→ 环带线宽名义档下 εeff(f1)（forward_z0 HJ）→
    r_mean = c/(2π·f1·√εeff(f1))（基模 n=1：闭环周长=λg）。
    恒等式由 test_ring_resonator_template 综合反解自洽测试钉住（rtol 1e-9）。
    近似级别：εeff 取直微带 HJ 值，未含曲率/色散修正（v1，见段头注）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_feed, _, status = inverse_width(z0_ohm, f1_ghz, sub)
    if status != "ok":
        raise ValueError(f"ring_resonator 馈线宽反解未收敛: {status}")
    _, eeff = forward_z0(w_mm, f1_ghz, sub)
    r_mean_mm = (_C0_M_S / (2.0 * math.pi * f1_ghz * 1e9
                            * math.sqrt(eeff)) * 1e3)
    return {
        "r_mean_mm": r_mean_mm,
        "w_mm": w_mm,
        "gap_mm": gap_mm,
        "feed_w_mm": round(w_feed, 4),
    }


#: 名义设计点（2026-09-26 由 ring_resonator_design_params() 缺省实参精算，
#: 字面量落表避免模块导入期 IO；逐位一致性由自洽测试钉住）：
#: εeff(w=1.1134, 2.5GHz)=2.852725152270805 → r_mean=11.299802692199101mm
RING_RESONATOR_NOMINAL: dict[str, Any] = {
    "r_mean_mm": 11.299802692199101,
    "w_mm": 1.1134,
    "gap_mm": 0.4,
    "feed_w_mm": 1.1134,
}


def _ring_resonator_layout(p: dict[str, Any]) -> dict[str, float]:
    """环形谐振器几何单源（mm 入参 → 米制派生量 + 守卫）。

    守卫（渲染期显式抛错，#266/#347 族口径）：
    - NEAR = base/4 ≤ gap/3（缝分辨，#266；违反=抽头区场不分辨）；
    - feed_len ≥ 42·NEAR（|MeasPlaneShift−FeedShift|≥3.9·NEAR 的安全侧，
      #347；馈段过短时测量面落进激励盒近场）；
    - r_in > 0（环孔存在）且 y_end ≤ BOARD（馈线长为正）。
    """
    w_m = float(p.get("w_mm", RING_RESONATOR_W_MM)) * 1e-3
    fw_m = float(p.get("feed_w_mm", RING_RESONATOR_W_MM)) * 1e-3
    gap_m = float(p.get("gap_mm", RING_RESONATOR_GAP_MM)) * 1e-3
    rm_m = float(p.get("r_mean_mm", 11.299802692199101)) * 1e-3
    base_m = float(p.get("_base_mm", 0.4)) * 1e-3
    near_m = base_m / 4.0
    board_m = 60e-3
    r_out = rm_m + w_m / 2.0
    r_in = rm_m - w_m / 2.0
    y_end = r_out + gap_m
    feed_len = board_m - y_end
    if r_in <= 0:
        raise ValueError(f"ring_resonator: 环孔非正（r_in={r_in * 1e3:.4f}mm）")
    if y_end >= board_m:
        raise ValueError(f"ring_resonator: 馈线长非正（y_end={y_end * 1e3:.3f}mm"
                         f" ≥ BOARD={board_m * 1e3:.1f}mm）")
    if near_m > gap_m / 3.0:
        raise ValueError(
            f"ring_resonator: NEAR={near_m * 1e3:.4f}mm > gap/3="
            f"{gap_m / 3.0 * 1e3:.4f}mm（#266 缝分辨守卫）——请加密 "
            f"mesh_resolution_mm ≤ {4.0 * gap_m / 3.0 * 1e3:.4f}mm 或加大 gap")
    if feed_len < 42.0 * near_m:
        raise ValueError(
            f"ring_resonator: feed_len={feed_len * 1e3:.3f}mm < 42·NEAR="
            f"{42.0 * near_m * 1e3:.3f}mm（#347 测量面-激励分离守卫）")
    return {"w": w_m, "fw": fw_m, "gap": gap_m, "rm": rm_m,
            "r_out": r_out, "r_in": r_in, "y_end": y_end,
            "feed_len": feed_len}


def _ring_resonator_lines(p: dict[str, Any]) -> str:
    # 环形谐振器几何段（F-A M3）：环带逐 y 网格行栅格化（ratrace 同法，
    # #198 零台阶）+ 双 50Ω 间隙耦合馈线 + MSLPort 端口面贴板边（mline 口径）。
    # 派生量以字面量注入（layout 单源 _ring_resonator_layout，含守卫）。
    lay = _ring_resonator_layout(p)
    return f'''W = {lay["w"]!r}            # 环带线宽（m，layout 单源字面量）
FW = {lay["fw"]!r}           # 馈线宽（m，50Ω HJ 口径）
GAP = {lay["gap"]!r}          # 馈线-环带间隙（m，间隙电容耦合 v1 口径）
R_OUT = {lay["r_out"]!r}   # 环外径 = r_mean + w/2（派生字面量）
R_IN = {lay["r_in"]!r}    # 环内径 = r_mean − w/2
Y_END = {lay["y_end"]!r}   # 馈线端 |y| = R_OUT + GAP
ring = CSX.AddMetal("ring_resonator")

# 环带栅格化：逐 y 网格行，行中心处求环带 x 区间（内/外半径；ratrace 同法 #198）
_yl = np.asarray(mesh.GetLines("y"))
for _k in range(len(_yl) - 1):
    _ya, _yb = _yl[_k], _yl[_k + 1]
    _yc = 0.5 * (_ya + _yb)
    if abs(_yc) > R_OUT:
        continue
    _xo = np.sqrt(max(R_OUT ** 2 - _yc ** 2, 0.0))
    _xi = np.sqrt(max(R_IN ** 2 - _yc ** 2, 0.0))
    if _xi > 1e-9:
        ring.AddBox((-_xo, _ya, H_SUB), (-_xi, _yb, H_SUB), priority=10)
        ring.AddBox((_xi, _ya, H_SUB), (_xo, _yb, H_SUB), priority=10)
    else:
        ring.AddBox((-_xo, _ya, H_SUB), (_xo, _yb, H_SUB), priority=10)

# 间隙耦合馈线（径向对置 180°，x=0 沿 y；对置馈点对各次模均为场腹）
ring.AddBox((-FW / 2, -BOARD, H_SUB), (FW / 2, -Y_END, H_SUB), priority=10)
ring.AddBox((-FW / 2, Y_END, H_SUB), (FW / 2, BOARD, H_SUB), priority=10)

# 端口：MSLPort 端口面贴 y=±BOARD 域边（PML_8；mline 口径 #154），
# MeasPlaneShift=馈段长/3（官方）
_port1 = MSLPort(CSX, port_nr=1, metal_prop=ring,
                 start=np.array([FW / 2, -BOARD, H_SUB]),
                 stop=np.array([-FW / 2, -Y_END, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y_END) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=ring,
                 start=np.array([-FW / 2, BOARD, H_SUB]),
                 stop=np.array([FW / 2, Y_END, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y_END) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in ring.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 注册：同对象入表（单一事实源；尾部追加 #247——ring_resonator 居尾 1）──
TEMPLATE_META["ring_resonator"] = RING_RESONATOR_META
TEMPLATE_NOMINAL["ring_resonator"] = RING_RESONATOR_NOMINAL
_TEMPLATE_PORT_AXES["ring_resonator"] = ("y",)
_TEMPLATE_RADIATOR["ring_resonator"] = False
