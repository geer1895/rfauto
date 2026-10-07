"""coax_waveguide_transition 同轴-波导过渡族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

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

# ═══ §ME-6 波导-同轴过渡 coax_waveguide_transition（2026-09-26 ME-6 离线段，
# ═══ 文末注册块）════════════════════════════════════════════════════════════
# 方案锚：月度增强方案 §三 A 流 ME-6——openEMS
# 官方 Coax-to-Waveguide 教程参数化直抄起手 + HFSS 仲裁；复用 sma_launcher
# 经验链。真机冒烟与 HFSS 仲裁=Ph3 窗（本批零发射）。
# 教程出处（#1c 直抄起手，双源）：
# ① wiki.openems.de "Tutorial: Coax to Waveguide Adapter"（Matlab，WR-75，
#   10-15 GHz）：结构=探针穿宽壁 + 背短路板（BackShort=短路面到探针中心距）
#   + 同轴口与波导口异阻抗 S21 校正 s21=sqrt(ZL1/ZL2)·uf_ref2/uf_inc1
#   （wiki 原式按反向定义端口成立；本模板 port2 朝向向外，透射取 uf_inc
#   ——docs/audit/oe3_coax_fail_audit_20260929.md §3，后处理段同注）；
# ② docs.openems.de（openEMS 0.37 Python）"Horn Antenna with Coaxial Pin
#   Feed"：探针柱数值口径直抄——wg_t=2.0mm 壁厚、pin_length=0.55·b_wg、
#   pin_r=0.5mm（≈SMA 内导体）、port_h=1.0mm 集总口隙高、feed_R=50Ω、
#   back_short=λg/4（四分之一导波波长背短路）、LumpedPort 探针基桥激励。
# 端口口径决定（实测绑定可用性 + 仓内经验链）：
# - CoaxialPort 绑定存在但**不用**：仓内 sma_launcher pt2 真机判废先例
#   （β=4166 vs TEM 闭式 68、|S21|=−240dB，_sma_launcher_lines 段头注释）
#   + 官方讨论 #437 报告 AddCoaxialPort 尺寸上限病态；且柱面原语的零厚/进
#   网格审计与 #212 盒原语口径不兼容。
# - 采纳=探针柱（PEC 盒，sma_launcher 经验链阶梯化口径）+ LumpedPort 同轴
#   截面集总桥（R=50Ω，官方 Python 教程逐参数直抄）+ RectWGPort 解析 TE10
#   （pyramid_horn 同款）。
# 几何（轴 +z=波导轴）：WR-90 腔 a×b（x×y）×l_wg，四壁+背短路板厚 wg_t
# （官方教程矩形厚壁，非零厚片）；探针经底壁（y=−b/2 侧）伸入腔内，针轴
# 平行 TE10 E 场（沿 y，tutorial 口径）；探针中心 z=z_pin=backshort（距
# 背短路内侧面）。port1=LumpedPort 探针基桥（壁内侧面→针底，隙高 port_h）；
# port2=RectWGPort @ z=l_wg−meas_len→l_wg（腔端面）。
# **绑定参数序**（RectWGPort 源码口径）：exc_dir=z 时 ny_P=(z+1)%3=x、
# ny_PP=(z+2)%3=y——a 绑 x（宽边）、b 绑 y（窄边），TE10（M=1,N=0）E 场
# 沿 y、半波沿 x，kc=π/a 绑定自算（与 pyramid_horn 的 y 轴绑定换序不同，
# z 轴物理序恰好一致，无需换手）。
# 名义值：a/b=wr_lookup("WR-90")（22.86/10.16，表单源）；backshort=λg/4@
# 10 GHz 导入期闭式精算字面落表（零手抄毫米数 #1c）；其余探针参数=官方
# Python 教程直抄（见①②）。
# 边界：z 轴（端口轴）双端 PML_8（#154 端口面贴 PML_8 域边；背面为金属
# 背短路无场区，PML 同置无害），x/y MUR。封闭 PEC 腔无外漏场，x/y 余量
# 仅 PML 过渡+网格缓冲（6mm≈λ0/5@10GHz，非辐射器件 5mm 档同量级）。

#: 波导-同轴过渡族模板名集（render_script/geometry_spec 早分发，同族同款）
COAX_WG_TEMPLATES: frozenset[str] = frozenset({"coax_waveguide_transition"})

#: 名义 WR 档与设计频点（WR-90 推荐带 8.2-12.4 GHz，f0=带内圆整档）
_COAX_WG_WR_NAME = "WR-90"
_COAX_WG_F0_GHZ = 10.0
#: 波导腔长（mm；官方教程 feed_length=50mm 为喇叭馈管口径，本过渡取
#: 背腔+探针+>λ0/2 传输段=30mm，参数可调）
_COAX_WG_L_WG_MM = 30.0
#: 壁厚（mm，官方 Python 教程 wg_t=2.0 直抄——矩形厚壁腔，非零厚片）
_COAX_WG_WG_T_MM = 2.0
#: 探针伸入深比例（官方 Python 教程 pin_length=b_wg·0.55 直抄，"tune for
#: best impedance match"调挡余量）
_COAX_WG_PIN_LEN_RATIO = 0.55
#: 探针截面半宽（mm，官方 Python 教程 pin_r=0.5 直抄，"≈ SMA inner
#: conductor"）
_COAX_WG_PIN_R_MM = 0.5
#: 集总口隙高（mm，官方 Python 教程 port_h=1.0 直抄——壁内侧面到针底的
#: 同轴连接器间隙理想化）
_COAX_WG_PORT_H_MM = 1.0
#: 馈电阻（Ω，官方 Python 教程 feed_R=50 直抄）
_COAX_WG_FEED_R_OHM = 50.0
#: 侧向/背面空气余量（mm；封闭 PEC 腔无外漏场，仅 PML 过渡+网格缓冲）
_COAX_WG_AIR_MARGIN_MM = 6.0


def _coax_wg_nominal() -> dict[str, Any]:
    """名义设计点（mm，导入期 wr_lookup+闭式精算，零手抄毫米数 #1c）。"""
    from rfauto.core.rw_tables import wr_lookup

    rec = wr_lookup(_COAX_WG_WR_NAME)
    fc10 = 299.792458 / (2.0 * rec.a_mm)        # TE10 截止（mm/GHz 口径）
    lam0 = 299.792458 / _COAX_WG_F0_GHZ
    lam_g = lam0 / math.sqrt(1.0 - (fc10 / _COAX_WG_F0_GHZ) ** 2)
    return {
        "a_mm": rec.a_mm,
        "b_mm": rec.b_mm,
        "l_wg_mm": _COAX_WG_L_WG_MM,
        "wg_t_mm": _COAX_WG_WG_T_MM,
        "pin_len_mm": _COAX_WG_PIN_LEN_RATIO * rec.b_mm,
        "pin_r_mm": _COAX_WG_PIN_R_MM,
        "port_h_mm": _COAX_WG_PORT_H_MM,
        "backshort_mm": lam_g / 4.0,
        "er": 1.0,
        "h_mm": 0.0,
    }


def coax_wg_design_params(
    wr_name: str = _COAX_WG_WR_NAME,
    f0_ghz: float = _COAX_WG_F0_GHZ,
    l_wg_mm: float = _COAX_WG_L_WG_MM,
) -> dict[str, Any]:
    """WR 表联动设计点（wr_lookup 单源；换 WR 档/频点重算探针与背腔）。

    a/b=WR 表口径；pin_len=0.55·b（官方教程比例）；backshort=λg/4@f0
    （官方教程口径，λg=λ0/√(1−(fc10/f0)²)，fc10=c0/2a TE10 闭式）。
    """
    from rfauto.core.rw_tables import wr_lookup

    rec = wr_lookup(wr_name)
    fc10 = 299.792458 / (2.0 * rec.a_mm)
    lam0 = 299.792458 / f0_ghz
    lam_g = lam0 / math.sqrt(1.0 - (fc10 / f0_ghz) ** 2)
    return {
        "a_mm": rec.a_mm,
        "b_mm": rec.b_mm,
        "l_wg_mm": float(l_wg_mm),
        "wg_t_mm": _COAX_WG_WG_T_MM,
        "pin_len_mm": _COAX_WG_PIN_LEN_RATIO * rec.b_mm,
        "pin_r_mm": _COAX_WG_PIN_R_MM,
        "port_h_mm": _COAX_WG_PORT_H_MM,
        "backshort_mm": lam_g / 4.0,
    }


COAX_WG_META: dict[str, Any] = {
    "f0_ghz": _COAX_WG_F0_GHZ, "n_ports": 2,
    "extraction": "S 参数 @ LumpedPort 1（探针基同轴截面集总桥，Z_ref=R="
                  "50Ω 实常数）+ RectWGPort 2（解析 TE10，Z_ref=ZL=k·Z0/β"
                  " 色散）；跨口传输含 sqrt(ZL1/ZL2) 阻抗校正（官方 wiki "
                  "Coax-to-Waveguide 教程口径）；HFSS 仲裁=Ph3 窗",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["a_mm", "b_mm", "l_wg_mm", "wg_t_mm", "pin_len_mm",
               "pin_r_mm", "port_h_mm", "backshort_mm"],
    "topology": "波导-同轴探针过渡：WR-90 矩形厚壁腔（a×b×l_wg，四壁+背短"
                "路板厚 wg_t，封闭 PEC 腔）+ 探针柱经底壁伸入腔内（针轴平"
                "行 TE10 E 场沿 y，针中心距背短路内侧面 backshort=λg/4）；"
                "port1=探针基 LumpedPort 集总桥（R=50Ω），port2=腔端面 "
                "RectWGPort 解析 TE10；z 轴双端 PML_8、x/y MUR",
    "param_semantics": "a_mm=波导宽边（x 向，WR 表口径）；b_mm=波导窄边"
                       "（y 向，WR 表口径）；l_wg_mm=腔长（背短路内侧面"
                       " z=0 到腔端面）；wg_t_mm=壁厚（官方教程 2.0 直"
                       "抄）；pin_len_mm=探针伸入深（壁内侧面起算，官方教"
                       "程 0.55·b 比例档）；pin_r_mm=探针截面半宽（官方教"
                       "程 0.5 直抄）；port_h_mm=集总口隙高（壁内侧面到针"
                       "底，官方教程 1.0 直抄）；backshort_mm=探针中心距"
                       "背短路内侧面（λg/4@f0 精算档）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50"
                 "（空气口径，官方 base 级）；NEAR=base/4；全部壁面/探针"
                 "特征站线（±a/2、±(a/2+wg_t)、±b/2、±(b/2+wg_t)、±pin_r、"
                 "−b/2+port_h、−b/2+pin_len、背短路面、探针 z 缘、端口校准"
                 "面）显式入网（#198）+ 全轴 1µm 近重合去重（#152）；背面"
                 "空气余量 6mm≈λ0/5（封闭腔无外漏场）",
    "smoke_note": "未冒烟（离线审计过，#212，test_coax_wg_template）；近"
                  "似级别如实登记：①探针柱为矩形盒阶梯化（官方教程亦为矩"
                  "形截面 pin，非圆柱）；②同轴连接器理想化为探针基集总桥"
                  "（官方 Python 教程口径，不含连接器体/介质填充）；③S21 "
                  "跨口阻抗校正按 wiki 教程 sqrt(ZL1/ZL2) 一阶口径；④真机"
                  "冒烟与 HFSS 仲裁=Ph3 窗（本批零发射）",
}


def _coax_wg_layout(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """波导-同轴过渡几何/端口/域/网格单源（mm 入出；渲染器/预览 spec 同消费）。

    守卫（渲染期显式抛错，设计约束声明）：探针体非正（pin_len≤port_h）、
    探针触顶壁短路（pin_len≥b）、探针截面超宽边（2·pin_r≥a）、背腔距非正
    （backshort≤0）、探针越背短路板（z_pin−pin_r<0，"探针不进腔"）、探针
    伸入端口校准段（z_pin+pin_r>l_wg−meas_len）。
    """
    nom = COAX_WG_NOMINAL
    a_mm = float(params.get("a_mm", nom["a_mm"]))
    b_mm = float(params.get("b_mm", nom["b_mm"]))
    l_wg_mm = float(params.get("l_wg_mm", nom["l_wg_mm"]))
    t_mm = float(params.get("wg_t_mm", nom["wg_t_mm"]))
    pin_len_mm = float(params.get("pin_len_mm", nom["pin_len_mm"]))
    pin_r_mm = float(params.get("pin_r_mm", nom["pin_r_mm"]))
    port_h_mm = float(params.get("port_h_mm", nom["port_h_mm"]))
    backshort_mm = float(params.get("backshort_mm", nom["backshort_mm"]))
    er = float(params.get("er", nom["er"]))
    if pin_len_mm <= port_h_mm:
        raise ValueError(
            f"coax_waveguide_transition: 探针体非正（pin_len={pin_len_mm:.3f}"
            f" <= port_h={port_h_mm:.3f}）——针底须高于集总口隙顶面")
    if pin_len_mm >= b_mm:
        raise ValueError(
            f"coax_waveguide_transition: 探针触顶壁短路（pin_len="
            f"{pin_len_mm:.3f} >= b={b_mm:.3f}）")
    if 2.0 * pin_r_mm >= a_mm:
        raise ValueError(
            f"coax_waveguide_transition: 探针截面超波导宽边（2·pin_r="
            f"{2.0 * pin_r_mm:.3f} >= a={a_mm:.3f}）")
    if backshort_mm <= 0.0:
        raise ValueError(
            f"coax_waveguide_transition: 背腔距非正（backshort="
            f"{backshort_mm:.3f}）")
    f0 = 0.5 * (freq_range_ghz[0] + freq_range_ghz[1])
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2.0
    lambda0_mm = 299.792458 / (f0 + fc)   # 频带最高频空气波长（保守 base）
    base_mm = (float(mesh_resolution_mm) if mesh_resolution_mm
               else lambda0_mm / 50.0)
    near_mm = base_mm / 4.0
    # 端口面纪律（审查轨 B P0-1）：port2 探针面原贴 z=l_wg 域边=PML 最外
    # 平面（激励面亦在 PML 内）——两面内移 ≥16·BASE（slotline 纪律）
    port_inset_mm = 16.0 * base_mm   # stop（探针）面内移出 PML；meas_len 维持
    meas_len_mm = max(6.0 * near_mm, 1.0)  # 原口径（start 更深无害，勿抬升挤占腔长）
    z_pin_mm = backshort_mm   # 探针中心 z=距背短路内侧面（官方教程口径）
    if z_pin_mm - pin_r_mm < 0.0:
        raise ValueError(
            f"coax_waveguide_transition: 探针越背短路板/不进腔（z_pin−"
            f"pin_r={z_pin_mm - pin_r_mm:.3f} < 0）")
    port_stop_z = l_wg_mm - port_inset_mm
    port_start_z = port_stop_z - meas_len_mm
    if z_pin_mm + pin_r_mm >= port_start_z:
        raise ValueError(
            f"coax_waveguide_transition: 探针伸入端口校准段（z_pin+pin_r="
            f"{z_pin_mm + pin_r_mm:.3f} >= 端口起面="
            f"{port_start_z:.3f}）——l_wg 不足或背腔距过大")
    dom_x_mm = a_mm / 2.0 + t_mm + _COAX_WG_AIR_MARGIN_MM
    dom_y_mm = b_mm / 2.0 + t_mm + _COAX_WG_AIR_MARGIN_MM
    z_lo_mm = -(t_mm + _COAX_WG_AIR_MARGIN_MM)
    xa = a_mm / 2.0
    xb = a_mm / 2.0 + t_mm
    yb = b_mm / 2.0
    ybt = b_mm / 2.0 + t_mm
    boxes: list[tuple[str, float, float, float, float, float, float]] = [
        # 四壁 + 背短路板（矩形厚壁封闭腔，官方教程结构；z=0=背短路内侧面）
        ("wall_bottom", -xb, -ybt, -t_mm, xb, -yb, l_wg_mm),
        ("wall_top", -xb, yb, -t_mm, xb, ybt, l_wg_mm),
        ("wall_left", -xb, -yb, -t_mm, -xa, yb, l_wg_mm),
        ("wall_right", xa, -yb, -t_mm, xb, yb, l_wg_mm),
        ("backshort_lid", -xb, -ybt, -t_mm, xb, ybt, 0.0),
        # 探针柱（底壁 y=−b/2 伸入，针底=集总口隙顶面；官方教程 pin 口径）
        ("probe_pin", -pin_r_mm, -yb + port_h_mm, z_pin_mm - pin_r_mm,
         pin_r_mm, -yb + pin_len_mm, z_pin_mm + pin_r_mm),
    ]
    x_lines = sorted({-dom_x_mm, -xb, -xa, -pin_r_mm, pin_r_mm,
                      xa, xb, dom_x_mm})
    y_lines = sorted({-dom_y_mm, -ybt, -yb, -yb + port_h_mm,
                      -yb + pin_len_mm, yb, ybt, dom_y_mm})
    z_lines = sorted({z_lo_mm, -t_mm, 0.0, z_pin_mm - pin_r_mm,
                      z_pin_mm + pin_r_mm, port_start_z, port_stop_z,
                      l_wg_mm})
    return {
        "a_mm": a_mm, "b_mm": b_mm, "l_wg_mm": l_wg_mm, "wg_t_mm": t_mm,
        "pin_len_mm": pin_len_mm, "pin_r_mm": pin_r_mm,
        "port_h_mm": port_h_mm, "backshort_mm": backshort_mm, "er": er,
        "f0_ghz": f0, "fc_ghz": fc, "lambda0_mm": lambda0_mm,
        "base_mm": base_mm, "near_mm": near_mm,
        "dom_x_mm": dom_x_mm, "dom_y_mm": dom_y_mm,
        "z_lo_mm": z_lo_mm, "z_hi_mm": l_wg_mm,
        "boxes": boxes,
        "x_lines_mm": x_lines, "y_lines_mm": y_lines, "z_lines_mm": z_lines,
        "meas_len_mm": meas_len_mm, "z_pin_mm": z_pin_mm,
        "port1": {"start_mm": [-pin_r_mm, -yb, z_pin_mm - pin_r_mm],
                  "stop_mm": [pin_r_mm, -yb + port_h_mm,
                              z_pin_mm + pin_r_mm],
                  "r_ohm": _COAX_WG_FEED_R_OHM, "p_dir": "y"},
        "port2": {"start_mm": [-xa, -yb, port_start_z],
                  "stop_mm": [xa, yb, port_stop_z],
                  "a_bind_mm": a_mm, "b_bind_mm": b_mm, "mode": "TE10"},
    }


def coax_wg_geometry_spec(
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """coax_waveguide_transition UI 预览 spec（mm；early-dispatch 自
    geometry_spec）。"""
    del substrate   # 空气填充器件，无板材（段头注释）
    lay = _coax_wg_layout(
        params, (COAX_WG_META["f0_ghz"], COAX_WG_META["f0_ghz"]))
    t = lay["wg_t_mm"]
    boxes = [
        {"name": "wall_bottom（底壁，探针穿入）", "material": "metal",
         "start_mm": [-lay["a_mm"] / 2 - t, -lay["b_mm"] / 2 - t, -t],
         "stop_mm": [lay["a_mm"] / 2 + t, -lay["b_mm"] / 2,
                     lay["l_wg_mm"]]},
        {"name": "wall_top（顶壁）", "material": "metal",
         "start_mm": [-lay["a_mm"] / 2 - t, lay["b_mm"] / 2, -t],
         "stop_mm": [lay["a_mm"] / 2 + t, lay["b_mm"] / 2 + t,
                     lay["l_wg_mm"]]},
        {"name": "wall_left（侧壁）", "material": "metal",
         "start_mm": [-lay["a_mm"] / 2 - t, -lay["b_mm"] / 2, -t],
         "stop_mm": [-lay["a_mm"] / 2, lay["b_mm"] / 2, lay["l_wg_mm"]]},
        {"name": "wall_right（侧壁）", "material": "metal",
         "start_mm": [lay["a_mm"] / 2, -lay["b_mm"] / 2, -t],
         "stop_mm": [lay["a_mm"] / 2 + t, lay["b_mm"] / 2,
                     lay["l_wg_mm"]]},
        {"name": "backshort_lid（背短路板）", "material": "metal",
         "start_mm": [-lay["a_mm"] / 2 - t, -lay["b_mm"] / 2 - t, -t],
         "stop_mm": [lay["a_mm"] / 2 + t, lay["b_mm"] / 2 + t, 0.0]},
        {"name": "probe_pin（同轴探针柱）", "material": "metal",
         "start_mm": [-lay["pin_r_mm"], -lay["b_mm"] / 2
                      + lay["port_h_mm"], lay["z_pin_mm"] - lay["pin_r_mm"]],
         "stop_mm": [lay["pin_r_mm"], -lay["b_mm"] / 2
                     + lay["pin_len_mm"], lay["z_pin_mm"] + lay["pin_r_mm"]]},
    ]
    ports = [
        {"name": "Port1（LumpedPort，探针基集总桥 R=50Ω）",
         "pos_mm": lay["port1"]["start_mm"], "dir": [0.0, 1.0, 0.0]},
        {"name": "Port2（RectWGPort，解析 TE10）",
         "pos_mm": [0.0, 0.0, lay["l_wg_mm"]], "dir": [0.0, 0.0, 1.0]},
    ]
    return {"template": "coax_waveguide_transition",
            "substrate": {"er": lay["er"], "h_mm": 0.0, "tan_d": 0.0},
            "boxes": boxes, "ports": ports, "elements": []}


def coax_wg_render(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    *,
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    far_field: bool = False,
) -> str:
    """coax_waveguide_transition 整脚本渲染器（早分发自 render_script）。

    port1=探针基 LumpedPort 集总桥（R=50Ω）、port2=RectWGPort 解析 TE10；
    z 轴双端 PML_8、x/y MUR；空气填充无介质板。far_field 不接受（封闭
    PEC 腔无辐射口径，nf2ff 不适用；显式报错不静默降级）。excite_port∈
    {1,2}：单激励 5 列 sparams.csv（反射列=激励口反射、传输列=跨口校正
    传输，summary 记 excite_port——#314 单激励掩码口径）。
    """
    del template, substrate   # 单模板渲染器；板材/域全由 params/NOMINAL 单源
    if far_field:
        raise ValueError(
            "coax_waveguide_transition: 封闭 PEC 腔无辐射口径，far_field/"
            "nf2ff 不适用（显式拒绝，不静默降级）")
    if int(excite_port) not in (1, 2):
        raise ValueError(
            f"coax_waveguide_transition 双端口模板，excite_port={excite_port}"
            f" 越界（1=同轴探针口，2=波导口）")
    lay = _coax_wg_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = lay["f0_ghz"] * 1e9
    fc = lay["fc_ghz"] * 1e9
    er = lay["er"]
    base = lay["base_mm"] * 1e-3
    near = lay["near_mm"] * 1e-3
    dom_x = lay["dom_x_mm"] * 1e-3
    dom_y = lay["dom_y_mm"] * 1e-3
    z_lo = lay["z_lo_mm"] * 1e-3
    z_hi = lay["z_hi_mm"] * 1e-3
    nrts = int(params.get("_nrts", 100000) or 100000)

    def m(v: float) -> float:
        return float(v) * 1e-3

    wall_lit = "\n".join(
        f'wall.AddBox(({m(bx[1])!r}, {m(bx[2])!r}, {m(bx[3])!r}), '
        f'({m(bx[4])!r}, {m(bx[5])!r}, {m(bx[6])!r}), priority=10)  # '
        f'{bx[0]}'
        for bx in lay["boxes"] if bx[0] != "probe_pin")
    pin = next(bx for bx in lay["boxes"] if bx[0] == "probe_pin")
    pin_lit = (
        f'pin.AddBox(({m(pin[1])!r}, {m(pin[2])!r}, {m(pin[3])!r}), '
        f'({m(pin[4])!r}, {m(pin[5])!r}, {m(pin[6])!r}), priority=10)')
    x_lit = ", ".join(repr(m(v)) for v in lay["x_lines_mm"])
    y_lit = ", ".join(repr(m(v)) for v in lay["y_lines_mm"])
    z_lit = ", ".join(repr(m(v)) for v in lay["z_lines_mm"])
    p1 = lay["port1"]
    p2 = lay["port2"]
    p1_lit = (
        f"    start=np.array([{m(p1['start_mm'][0])!r}, "
        f"{m(p1['start_mm'][1])!r}, {m(p1['start_mm'][2])!r}]),\n"
        f"    stop=np.array([{m(p1['stop_mm'][0])!r}, "
        f"{m(p1['stop_mm'][1])!r}, {m(p1['stop_mm'][2])!r}]),\n")
    p2_lit = (
        f"    start=np.array([{m(p2['start_mm'][0])!r}, "
        f"{m(p2['start_mm'][1])!r}, {m(p2['start_mm'][2])!r}]),\n"
        f"    stop=np.array([{m(p2['stop_mm'][0])!r}, "
        f"{m(p2['stop_mm'][1])!r}, {m(p2['stop_mm'][2])!r}]),\n")
    a_wr = m(lay["a_mm"])
    exc1 = 1 if int(excite_port) == 1 else 0
    exc2 = 0 if int(excite_port) == 1 else 1
    return f'''#!/usr/bin/env python3
"""openEMS coax_waveguide_transition script (rfauto ME-6 auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/openems_templates.py 文末
COAX_WG 段。波导-同轴探针过渡（官方 openEMS Coax-to-Waveguide Adapter
wiki 教程结构 + 官方 Python "Horn Antenna with Coaxial Pin Feed" 教程
pin/集总桥参数直抄）；真机冒烟与 HFSS 仲裁=Ph3 窗（本批零发射）。
"""
import csv
import json
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         "D:/rf_workspace/vendor/openEMS/install/bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import RectWGPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}   # 空气填充（TE10 截止/波导波长 summary 回显消费；无介质板）
H_SUB = 0.0   # 无介质板器件占位（审计④域口径；段头注释）
BASE = {base!r}   # 网格 base：自动档 λ0/50（空气口径）
NEAR = {near!r}   # 近特征区 = base/4
DOM_X = {dom_x!r}
DOM_Y = {dom_y!r}
Z_LO = {z_lo!r}
Z_HI = {z_hi!r}
NRTS = {nrts}
EXCITE_PORT = {int(excite_port)}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)   # 官方口径：不设 EndCriteria，能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 封闭 PEC 腔（波导-同轴过渡=非辐射器件）：z 轴（端口轴）双端 PML_8
# （port2 面贴 z=Z_HI PML_8 域边，#154 前节；背面为金属背短路无场区），
# x/y MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "PML_8", "PML_8"])

mesh = CSX.GetGrid()
# 全部壁面/探针特征站线显式入网（#198）：特征区 NEAR 细分→域界补入→
# 空气区 BASE 粗化（双档平滑把细格限于壁面走廊）
for _x in np.array([{x_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{y_lit}]):
    mesh.AddLine("y", _y)
for _z in np.array([{z_lit}]):
    mesh.AddLine("z", _z)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.SmoothMeshLines("z", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.array([Z_LO, Z_HI]))
mesh.SmoothMeshLines("x", BASE)
mesh.SmoothMeshLines("y", BASE)
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：矩形厚壁波导腔（四壁+背短路板）+ 探针柱（底壁伸入）──
wall = CSX.AddMetal("wg_wall")
{wall_lit}
pin = CSX.AddMetal("wg_pin")
{pin_lit}

# ── 端口 1：探针基同轴截面集总桥（官方 Python 教程 LumpedPort 口径，
#    R=50Ω 实常数 Z_ref；壁内侧面→针底，隙高 port_h，exc 沿 y）──
_port1 = FDTD.AddLumpedPort(1, {p1['r_ohm']!r},
{p1_lit}    p_dir="{p1['p_dir']}", excite={exc1}, priority=5)

# ── 端口 2：RectWGPort 解析 TE10（Pozar 模式函数，绑定自算 kc=π/a）──
# 绑定参数序（exc_dir=z）：ny_P=x、ny_PP=y——a 绑宽边 x、b 绑窄边 y，
# mode="TE10"（M=1,N=0：E 沿 y、半波沿 x，与探针轴平行=耦合口径）。
# Z_ref 缺省=解析波导阻抗 ZL=k·Z0/β（WaveguidePort.CalcPort 填）。
_port2 = RectWGPort(CSX, port_nr=2,
{p2_lit}    exc_dir="z", a={m(p2['a_bind_mm'])!r}, b={m(p2['b_bind_mm'])!r},
    mode_name="{p2['mode']}", excite={exc2})

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单激励 S 参数（#314 单激励 5 列掩码口径：反射列=激励口反
#    射、传输列=跨口传输；跨口含 sqrt(ZL1/ZL2) 阻抗校正——官方 wiki
#    Coax-to-Waveguide 教程口径，同轴 50Ω vs 波导 ZL 色散异阻抗）。
#    透射通道按 port2 朝向选取：CalcPort 波分解 uf_inc=沿 direction 正向
#    行波、uf_ref=逆向行波——"port2 uf_ref=到达行波"仅对反向定义端口
#    （MSL/CPW/SSL 族 port2 stop 指向电路内侧）成立；本模板 port2 按
#    自然升序定义（direction=+1 向外），透射在 uf_inc ──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f)
_port2.CalcPort(SIM_PATH, f)
_zl_wg = np.real(_port2.ZL)          # 解析 TE10 波导阻抗 k·Z0/β（色散）
if EXCITE_PORT == 1:
    s_refl = _port1.uf_ref / _port1.uf_inc           # Z_ref=50Ω
    # 透射=port2.uf_inc（朝向依据：port2 start z < stop z → RectWGPort
    # direction=+1 向外，uf_inc=出腔行波=透射；uf_ref 在此朝向是 port2
    # 测量面外 16mm 短路 stub+PML 回波，实测 −51…−54dB≈PML 回损量级。
    # 根因审计 docs/audit/oe3_coax_fail_audit_20260929.md §3/§5，
    # wf:oe3-coax-fail-audit 2026-09-29）
    s_tran = np.sqrt(50.0 / _zl_wg) * _port2.uf_inc / _port1.uf_inc
    refl_name, tran_name = "S11", "S21"
else:
    # 注意：excite_port=2 反激励分支未经朝向审计闭环（上审计只钉
    # excite_port=1 主口径，且本模板当前判读链只消费 port1 激励），
    # 反激励产物判读前须按同法先复判通道朝向
    s_refl = _port2.uf_ref / _port2.uf_inc           # Z_ref=ZL_WG
    s_tran = np.sqrt(_zl_wg / 50.0) * _port1.uf_ref / _port2.uf_inc
    refl_name, tran_name = "S22", "S12"

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_" + refl_name, "im_" + refl_name,
                 "re_" + tran_name, "im_" + tran_name])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, s_refl[_i].real, s_refl[_i].imag,
                     s_tran[_i].real, s_tran[_i].imag])

# TE10 截止/导波波长闭式回显（er 消费面；WR 口径自洽由审计测试钉）
_fc_te10 = 299792458.0 / (2.0 * {a_wr!r} * (ER ** 0.5))
_lam_g = (299792458.0 / F0) / (1.0 - (_fc_te10 / F0) ** 2) ** 0.5
summary = dict(
    ok=True, template="coax_waveguide_transition", f0_hz=F0, fc_hz=FC,
    excite_port=EXCITE_PORT, refl=refl_name, tran=tran_name,
    wr_a_mm={lay["a_mm"]!r}, wr_b_mm={lay["b_mm"]!r},
    l_wg_mm={lay["l_wg_mm"]!r}, wg_t_mm={lay["wg_t_mm"]!r},
    pin_len_mm={lay["pin_len_mm"]!r}, pin_r_mm={lay["pin_r_mm"]!r},
    port_h_mm={lay["port_h_mm"]!r}, backshort_mm={lay["backshort_mm"]!r},
    h_sub_placeholder_mm=H_SUB, fc_te10_hz=float(_fc_te10),
    lambda_g_mm=float(_lam_g), zl_wg_f0_ohm=float(np.interp(F0, f, _zl_wg)),
    nrts=NRTS,
    mesh_lines=[int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
)
with open(os.path.join(SCRIPT_DIR, "coax_wg_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto coax_waveguide_transition simulation done")
'''


# ── 注册：同对象入表（单一事实源；尾部追加 #247——coax_waveguide_transition
# ── 居尾 1、pyramid_horn 居尾 2）──
COAX_WG_NOMINAL: dict[str, Any] = _coax_wg_nominal()
TEMPLATE_META["coax_waveguide_transition"] = COAX_WG_META
TEMPLATE_NOMINAL["coax_waveguide_transition"] = COAX_WG_NOMINAL
_TEMPLATE_PORT_AXES["coax_waveguide_transition"] = ("z",)
_TEMPLATE_RADIATOR["coax_waveguide_transition"] = False
