"""COMSOL 官方 Application Library 例「Microwave Oven」(model 1424) 复现（a6-mwoven）。

任务：§10.21 A6 补强 / §10.3 D3-2 —— 在 comsol_adapter 的加性多物理扩展之上
真机复现 COMSOL 官方微波炉例：金属腔体 + 矩形波导馈（TE10，2.45 GHz，1 kW）
+ 玻璃盘 + 土豆介质负载，跑「频域 Maxwell → 稳态传热」并导出 T_max 与温度场。

官方口径来源（本机 COMSOL 6.3 安装，逐条实录；纪律 1c/#215：禁止凭想象写 API/数值）：
- applications/RF_Module/Microwave_Heating/microwave_oven.mph（model 1424，
  usedlicenses=COMSOL+RF，lastComputationTime 53.4 s）及其同目录
  microwave_oven_parameters.txt（几何/材料参数逐行实录）；
- doc/help/.../com.comsol.help.models.rf.microwave_oven/microwave_oven.html
  （模型描述、TE10 截止 1.92-3.84 GHz、土豆 eps_r=65-20j、官方报告值）；
- 该 .mph 内 dmodel.xml（物理/耦合/study 特征类型串与属性名逐条对照，见
  src/rfauto/adapters/comsol_adapter.py 多物理常量区的出处注释）。

官方例报告值（唯一标量验收基准）：
- 土豆吸收功率 631 W（full model，1 kW 输入；官方 Results 节 Volume
  Integration of ht.Qtot over Potato）；定性口径 "about 60% of the input"；
  半模型 314 W。

**温度场验证口径（官方文档检索定论）**：
官方对温度场**无任何标量参考量**——模型文档全文（本机 PDF 30 页逐页核）
只有 Figure 3 瞬态中心温度曲线（图，无数值）；"中心的温度最终达到 100℃"
是沸腾物理叙述且明示本模型未建该非线性；RF Module User's Guide 第 6 章
（Microwave Heating 接口，pp.311-317）仅接口说明；姊妹模型
rotating_microwave_oven 文档唯一温度数字 "average temperature gradually
approaches 380 K" 属**相变封顶（373.15 K）+ 旋转 + 变介电常数**的另一模型，
对本模型不构成参考量。故走**能量守恒自洽锚**（如实标注非官方）：
  - transient（官方 study 型，绝热）：∫P dt = m·Cp·ΔT_mean 精确成立
    （单向耦合 + 材料温度无关 + 无热汇），偏差只来自求解器容差；
  - stationary（本脚本口径）：∮ht.ntflux dS = ∫ht.Qtot dV 稳态闭合；
  - 中心温度取官方三维截点位 (wo/2, 0, rpot+bp+hp)（官方 dmodel.xml
    CutPoint3D 实录），对照官方 Figure 2/3 定性"中心峰化"：
    ΔT_center ≥ ΔT_mean。

**口径差异（如实声明）**：官方例是 Frequency-Transient（range(0,1,5) 单向
电磁加热）。本脚本默认跑 Frequency-Stationary（COMSOL 预设
"Frequency-Stationary, One-Way Electromagnetic Heating"）。稳态热必须有热沉，
否则纯体积源问题奇异，故在土豆表面加对流换热边界（h_conv/Text 可配）。
因此稳态 T_max **不是**官方报告值（官方只给 Figure 3 的瞬态中心温度曲线，
无标量），其量级由 h_conv 决定。替代性确定性检查（不编造数值）：
  (1) 能量守恒 + 无源性：P_absorbed <= P_input，反射 = 输入 − 吸收；
  (2) 与独立教科书闭式（Incropera & DeWitt / Carslaw & Jaeger 球体均匀源
      稳态中心温升）对比数量级；
  (3) 温度场自洽：有限值 + t_min <= t_avg <= t_max；
  (4) §10.24 新增能量守恒自洽锚（transient 绝热 m·Cp·ΔT / stationary
      边界热流闭合），如实标注"自洽锚非官方"。
真正的官方对照验收门是吸收功率 631 W 的 ±5%（ACCEPTANCE_TOL）。

纪律：mph.start(version="6.3") 显式钉版本（#215）；单 Client；用完
client.remove(model) 释放；不保存/覆盖任何用户 .mph；产物只落 runs/。

用法::

    .venv/Scripts/python.exe scripts/comsol_microwave_oven.py --dry-run
    .venv/Scripts/python.exe scripts/comsol_microwave_oven.py
    .venv/Scripts/python.exe scripts/comsol_microwave_oven.py --thermal transient

退出码：0=完成且官方吸收功率对照通过；1=完成但官方对照超差（报告已落盘，
不伪装绿）；2=求解/环境异常；3=MPh 不可用；4=超时看门狗触发。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.adapters import comsol_adapter as ca

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO / "runs" / "comsol_microwave_oven"

# ── 官方例参数（microwave_oven_parameters.txt 逐行实录，COMSOL 6.3 本机）──────
MICROWAVE_OVEN_DEFAULTS: dict[str, float] = {
    "wo_mm": 267.0,     # wo   微波炉宽度
    "do_mm": 270.0,     # do   微波炉深度
    "ho_mm": 188.0,     # ho   微波炉高度
    "wg_mm": 50.0,      # wg   波导宽度
    "dg_mm": 78.0,      # dg   波导深度
    "hg_mm": 18.0,      # hg   波导高度
    "rp_mm": 113.5,     # rp   玻璃盘半径
    "hp_mm": 6.0,       # hp   玻璃盘高度
    "bp_mm": 15.0,      # bp   玻璃盘与底部的距离
    "rpot_mm": 31.5,    # rpot 土豆半径
    "t0_degc": 8.0,     # T0   土豆初始温度
    "freq_ghz": 2.45,   # 激励频率（TE10 单模 1.92-3.84 GHz）
    "pin_w": 1000.0,    # 端口输入功率（full model 1 kW；半模型 500 W）
}
# 材料（官方 html「Model Definition」+ dmodel 材料表 def 组实录）
POTATO_EPS_R_EXPR = "65-20*j"    # 复相对介电常数（虚部=介电损耗）
POTATO_K_W_MK = 0.55             # 热导率 W/(m*K)
POTATO_RHO_KG_M3 = 1050.0        # 密度 kg/m^3
POTATO_CP_J_KG_K = 3.64e3        # 定压比热 J/(kg*K)
GLASS_EPS_R = 2.55               # 玻璃盘（仅电磁，不参与热模型）
COPPER_SIGMA_S_M = 5.998e7       # 铜电导率（COMSOL 材料库口径），阻抗边界用
# 官方报告值（html Results 节实录）
OFFICIAL_ABSORBED_POWER_W = 631.0      # full model，1 kW 输入
OFFICIAL_ABSORBED_FRACTION = 0.60      # "about 60% of the input microwave power"
OFFICIAL_HALF_MODEL_POWER_W = 314.0    # 半模型，500 W 输入
ACCEPTANCE_TOL = 0.05                  # 官方对照 ±5% 验收门
# 网格/热边界默认值（口径写进报告，可 CLI 覆盖）
DEFAULT_MESH_HMAX_MM = 15.0            # 空气/腔体全局最大单元尺寸（约 lambda0/8）
DEFAULT_POTATO_HMAX_MM = 3.0           # 土豆细化（官方例源强中心峰化）
DEFAULT_H_CONV_W_M2K = 10.0            # 稳态热沉：自然对流量级（可配）
SUPPORTED_THERMAL_MODES = ("stationary", "transient")
# 官方三维截点位（dmodel.xml CutPoint3D cpt1 逐属性实录：wo/2, 0, rpot+bp+hp）
OFFICIAL_CENTER_POINT_EXPRS = ("wo/2", "0", "rpot+bp+hp")


def normalize_oven_params(params: dict[str, Any] | None = None, *,
                          freq_ghz: float | None = None,
                          pin_w: float | None = None) -> dict[str, float]:
    """官方例参数规范化：补默认、转 float、正数校验（确定性内核）。"""
    spec = dict(MICROWAVE_OVEN_DEFAULTS)
    for key, value in (params or {}).items():
        if key in MICROWAVE_OVEN_DEFAULTS:
            spec[key] = float(value)
    if freq_ghz is not None:
        spec["freq_ghz"] = float(freq_ghz)
    if pin_w is not None:
        spec["pin_w"] = float(pin_w)
    for key, value in spec.items():
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"微波炉参数 {key} 必须为正有限值，得到 {value}")
    return spec


def oven_comsol_parameters(spec: dict[str, float]) -> dict[str, str]:
    """rfauto 参数（mm/degC/GHz/W）→ COMSOL 全局参数表达式（带单位字符串）。

    参数名与官方例 microwave_oven_parameters.txt 保持一致
    （wo/do/ho/wg/dg/hg/rp/hp/bp/rpot/T0），几何特征一律引用参数名表达式。
    """
    return {
        "wo": f"{spec['wo_mm']:g}[mm]",
        "do": f"{spec['do_mm']:g}[mm]",
        "ho": f"{spec['ho_mm']:g}[mm]",
        "wg": f"{spec['wg_mm']:g}[mm]",
        "dg": f"{spec['dg_mm']:g}[mm]",
        "hg": f"{spec['hg_mm']:g}[mm]",
        "rp": f"{spec['rp_mm']:g}[mm]",
        "hp": f"{spec['hp_mm']:g}[mm]",
        "bp": f"{spec['bp_mm']:g}[mm]",
        "rpot": f"{spec['rpot_mm']:g}[mm]",
        "T0": f"{spec['t0_degc']:g}[degC]",
        "freq": f"{spec['freq_ghz']:g}[GHz]",
        "Pin": f"{spec['pin_w']:g}[W]",
    }


def geometry_bounds(spec: dict[str, float]) -> dict[str, dict[str, tuple[float, float]]]:
    """四个几何体的包围盒（mm）。官方例几何（html Modeling Instructions 实录）：

    blk1 腔体 (wo,do,ho) @ (0,-do/2,0)；blk2 波导 (wg,dg,hg) @ (-wg,-dg/2,ho-hg)；
    cyl1 玻璃盘 r=rp,h=hp @ (wo/2,0,bp)；sph1 土豆 r=rpot @ (wo/2,0,rpot+bp+hp)。
    """
    wo, do, ho = spec["wo_mm"], spec["do_mm"], spec["ho_mm"]
    wg, dg, hg = spec["wg_mm"], spec["dg_mm"], spec["hg_mm"]
    rp, hp, bp = spec["rp_mm"], spec["hp_mm"], spec["bp_mm"]
    rpot = spec["rpot_mm"]
    cx = wo / 2.0
    pot_z0 = bp + hp
    return {
        "oven": {"x": (0.0, wo), "y": (-do / 2.0, do / 2.0), "z": (0.0, ho)},
        "waveguide": {"x": (-wg, 0.0), "y": (-dg / 2.0, dg / 2.0),
                      "z": (ho - hg, ho)},
        "plate": {"x": (cx - rp, cx + rp), "y": (-rp, rp), "z": (bp, bp + hp)},
        "potato": {"x": (cx - rpot, cx + rpot), "y": (-rpot, rpot),
                   "z": (pot_z0, pot_z0 + 2.0 * rpot)},
    }


def material_selection_boxes(spec: dict[str, float], *, tol: float = 1e-3) -> dict[
        str, tuple[int, tuple[float, float, float], tuple[float, float, float]]]:
    """域选择盒（土豆/玻璃盘）：entitydim=3 + condition=inside（域整体在盒内）。"""
    b = geometry_bounds(spec)
    out: dict[str, tuple[int, tuple[float, float, float],
                         tuple[float, float, float]]] = {}
    for tag, key in (("sel_potato", "potato"), ("sel_plate", "plate")):
        box = b[key]
        lo = (box["x"][0] - tol, box["y"][0] - tol, box["z"][0] - tol)
        hi = (box["x"][1] + tol, box["y"][1] + tol, box["z"][1] + tol)
        out[tag] = (3, lo, hi)
    return out


def boundary_selection_boxes(spec: dict[str, float], *, tol: float = 1e-3) -> dict[
        str, tuple[int, tuple[float, float, float], tuple[float, float, float]]]:
    """边界选择盒（entitydim=2）：端口面 / 土豆表面 / 金属壁。

    金属壁按平面逐面拆分（面整体落在薄盒内才被 inside 选中），逐条避开两个
    非金属内部边界：波导-腔体交界面（x=0 开口，y=+-dg/2，z=ho-hg..ho）与
    土豆-玻璃盘接触面。腔体 x=0 壁若被 Form Union 切成单个 U 形面（其包围盒
    含开口），则不会被任何薄盒完整包含 -> 保持接口默认 PEC；这是已知且极小
    的口径偏差（该面约占腔壁面积 1/8，铜壁损耗本身只有输入功率的百分之几），
    报告 honest_notes 如实标注。
    """
    b = geometry_bounds(spec)
    ox0, ox1 = b["oven"]["x"]
    oy0, oy1 = b["oven"]["y"]
    oz0, oz1 = b["oven"]["z"]
    wx0, wx1 = b["waveguide"]["x"]
    wy0, wy1 = b["waveguide"]["y"]
    wz0, wz1 = b["waveguide"]["z"]
    pot = b["potato"]

    boxes: dict[str, tuple[int, tuple[float, float, float],
                            tuple[float, float, float]]] = {}
    # 端口面：波导外端面 x=-wg（z 向跨整个波导高度）
    boxes["sel_port"] = (2, (wx0 - tol, wy0 - tol, wz0 - tol),
                         (wx0 + tol, wy1 + tol, wz1 + tol))
    # 土豆表面（对流热沉选择面）
    boxes["sel_potato_surface"] = (
        2,
        (pot["x"][0] - tol, pot["y"][0] - tol, pot["z"][0] - tol),
        (pot["x"][1] + tol, pot["y"][1] + tol, pot["z"][1] + tol),
    )
    # 金属壁：腔体 5 个外包面（x=0 壁单独处理）+ 波导 3 个包裹面
    boxes["sel_metal_bottom"] = (2, (ox0, oy0, oz0 - tol), (ox1, oy1, oz0 + tol))
    boxes["sel_metal_top"] = (2, (wx0, oy0, oz1 - tol), (ox1, oy1, oz1 + tol))
    boxes["sel_metal_front"] = (2, (ox0, oy0 - tol, oz0), (ox1, oy0 + tol, oz1))
    boxes["sel_metal_back"] = (2, (ox0, oy1 - tol, oz0), (ox1, oy1 + tol, oz1))
    boxes["sel_metal_right"] = (2, (ox1 - tol, oy0, oz0), (ox1 + tol, oy1, oz1))
    # x=0 壁：开口以下整段（若为 U 形面则不被选中，见 docstring）
    boxes["sel_metal_left_lower"] = (2, (ox0 - tol, oy0, oz0),
                                     (ox0 + tol, oy1, wz0 + tol))
    # x=0 壁：开口左右两小块（避开开口）
    boxes["sel_metal_left_front"] = (2, (ox0 - tol, oy0, wz0 - tol),
                                     (ox0 + tol, wy0 + tol, oz1))
    boxes["sel_metal_left_back"] = (2, (ox0 - tol, wy1 - tol, wz0 - tol),
                                    (ox0 + tol, oy1, oz1))
    # 波导底/两侧（端口面单独处理，顶面并入腔体顶面）
    boxes["sel_metal_wg_bottom"] = (2, (wx0 - tol, wy0 - tol, wz0 - tol),
                                    (wx1, wy1 + tol, wz0 + tol))
    boxes["sel_metal_wg_front"] = (2, (wx0 - tol, wy0 - tol, wz0 - tol),
                                   (wx1, wy0 + tol, oz1))
    boxes["sel_metal_wg_back"] = (2, (wx0 - tol, wy1 - tol, wz0 - tol),
                                  (wx1, wy1 + tol, oz1))
    return boxes


def potato_volume_m3(spec: dict[str, float]) -> float:
    """土豆球体积 [m^3] = 4/3*pi*r^3（官方例 sph1 半径 rpot）。"""
    r_m = spec["rpot_mm"] * 1e-3
    return 4.0 / 3.0 * math.pi * r_m ** 3


def potato_mass_kg(spec: dict[str, float]) -> float:
    """土豆质量 [kg] = rho*V（官方材料表 rho=1050 kg/m^3，能量锚 m·Cp 用）。"""
    return POTATO_RHO_KG_M3 * potato_volume_m3(spec)


def transient_times_s(t_list: str | None) -> list[float]:
    """COMSOL tlist 语法 → 输出时刻序列 [s]（确定性解析，能量锚 Δt 用）。

    支持 range(start,step,stop)（官方例 range(0,1,5) → [0,1,2,3,4,5]）
    与空白分隔显式列表；stop 非整步时末时刻 = start+floor((stop-start)/step)*step。
    """
    text = str(t_list or "range(0,1,5)").strip()
    m = re.match(r"range\(([^)]*)\)$", text)
    if m:
        nums = [float(p) for p in m.group(1).split(",") if p.strip()]
        if len(nums) != 3:
            raise ValueError(f"range 语法需要 3 个参数，得到 {nums}")
        start, step, stop = nums
        if step <= 0:
            raise ValueError(f"range 步长必须为正，得到 {step}")
        n = math.floor((stop - start) / step + 1e-9)
        if n < 0:
            raise ValueError(f"range 区间为空: {text}")
        return [start + k * step for k in range(n + 1)]
    return [float(p) for p in text.split()]


def potato_power_density_w_m3(spec: dict[str, float], p_absorbed_w: float) -> float:
    """土豆体积平均热源密度 [W/m^3] = P_absorbed / V_potato（教科书裁判输入量）。"""
    return float(p_absorbed_w) / potato_volume_m3(spec)


def _box_selection(comp: Any, tag: str, dim: int,
                   lo: tuple[float, float, float],
                   hi: tuple[float, float, float]) -> None:
    """Box 选择集（属性名 xmin..zmax/condition 口径同适配器 _box_selection）。"""
    sel = comp.selection().create(tag, "Box")
    sel.set("entitydim", str(dim))  # JPype 整数属性传字符串（#217④）
    for axis, value in zip(("x", "y", "z"), lo, strict=True):
        sel.set(f"{axis}min", value)
    for axis, value in zip(("x", "y", "z"), hi, strict=True):
        sel.set(f"{axis}max", value)
    sel.set("condition", "inside")


def build_oven_model(client: Any, spec: dict[str, float],
                     opts: dict[str, Any]) -> Any:
    """在 Client 内构建官方微波炉模型（几何/材料/emw+ht/study/网格）。

    纯 Java API 序列，可被记录桩离线断言（见 tests/unit/test_comsol_microwave_oven.py）。
    """
    model = client.create(f"rfauto_microwave_oven_{int(time.time())}")
    j = model.java
    for name, expr in oven_comsol_parameters(spec).items():
        j.param().set(name, expr)

    j.component().create("comp1", True)
    comp = j.component("comp1")
    geom = comp.geom().create("geom1", 3)
    geom.lengthUnit("mm")
    # 官方几何：腔体 + 波导 + 玻璃盘 + 土豆（位置/尺寸表达式逐条实录）
    blk1 = geom.create("blk1", "Block")
    blk1.set("base", "corner")
    blk1.set("pos", ["0", "-do/2", "0"])
    blk1.set("size", ["wo", "do", "ho"])
    blk2 = geom.create("blk2", "Block")
    blk2.set("base", "corner")
    blk2.set("pos", ["-wg", "-dg/2", "ho-hg"])
    blk2.set("size", ["wg", "dg", "hg"])
    cyl1 = geom.create("cyl1", "Cylinder")
    cyl1.set("r", "rp")
    cyl1.set("h", "hp")
    cyl1.set("pos", ["wo/2", "0", "bp"])
    sph1 = geom.create("sph1", "Sphere")
    sph1.set("r", "rpot")
    sph1.set("pos", ["wo/2", "0", "rpot+bp+hp"])
    geom.run()

    # 选择集（域：土豆/玻璃盘；边界：端口/土豆表面/金属壁）
    for tag, (dim, lo, hi) in material_selection_boxes(spec).items():
        _box_selection(comp, tag, dim, lo, hi)
    boundary_boxes = boundary_selection_boxes(spec)
    for tag, (dim, lo, hi) in boundary_boxes.items():
        _box_selection(comp, tag, dim, lo, hi)

    # 材料：air 先全选，土豆/玻璃盘后建覆盖（对应官方 mat1 Air / mat2 Potato /
    # mat3 Glass 的节点顺序；COMSOL 材料按节点序后建覆盖同名域）
    mat_air = comp.material().create("mat_air", "Common")
    mat_air.selection().all()
    grp = mat_air.propertyGroup("def")
    grp.set("relpermittivity", ["1"])
    grp.set("relpermeability", ["1"])
    grp.set("electricconductivity", ["0"])
    mat_pot = comp.material().create("mat_potato", "Common")
    mat_pot.selection().named("sel_potato")
    grp = mat_pot.propertyGroup("def")
    grp.set("relpermittivity", [POTATO_EPS_R_EXPR])
    grp.set("relpermeability", ["1"])
    grp.set("electricconductivity", ["0"])
    grp.set("thermalconductivity", [f"{POTATO_K_W_MK:g}"])
    grp.set("density", [f"{POTATO_RHO_KG_M3:g}"])
    grp.set("heatcapacity", [f"{POTATO_CP_J_KG_K:g}"])
    mat_glass = comp.material().create("mat_glass", "Common")
    mat_glass.selection().named("sel_plate")
    grp = mat_glass.propertyGroup("def")
    grp.set("relpermittivity", [f"{GLASS_EPS_R:g}"])
    grp.set("relpermeability", ["1"])
    grp.set("electricconductivity", ["0"])

    # emw：矩形端口单模 TE10 激励 + 金属壁阻抗边界（铜电导率显式 userdef）
    phys = comp.physics().create(ca.PHYSICS_TAG, ca.PHYSICS_TYPE, "geom1")
    port = phys.create("port1", "Port", 2)
    port.selection().named("sel_port")
    port.set("PortName", "1")
    port.set("PortType", "Rectangular")
    port.set("PortModeNumber", "10")
    port.set("Pin", "Pin")
    port.set("PortExcitation", "on")
    for tag in boundary_boxes:
        if not tag.startswith("sel_metal_"):
            continue
        imp = phys.create(f"imp_{tag.removeprefix('sel_metal_')}", "Impedance", 2)
        imp.selection().named(tag)
        imp.set("definedBy", "conductivity")
        # 三个 *_mat 查找全部显式 userdef：真机 run2 实证——只改 sigma/mu 时
        # COMSOL 仍会为外部金属壁查材料属性 epsilonr 并报「未定义」（外侧=真空，
        # 边界材料缺失）；显式给外侧真空口径 epsilonr=1 即无需材料查找。
        imp.set("sigmabnd_mat", "userdef")
        imp.set("sigmabnd", f"{COPPER_SIGMA_S_M:g}[S/m]")
        imp.set("murbnd_mat", "userdef")
        imp.set("murbnd", "1")
        imp.set("epsilonr_mat", "userdef")
        imp.set("epsilonr", "1")

    # 多物理：ht（只解土豆域）+ emw->ht 单向耦合（ElectromagneticHeating）
    ht = ca.ComsolAdapter.add_heat_transfer(
        comp, selection="sel_potato", t_init="T0")
    if opts["thermal"] == "stationary":
        ca.ComsolAdapter.add_convective_heat_flux(
            ht, selection="sel_potato_surface", h_expr="hconv", t_ext_expr="Text")
    ca.ComsolAdapter.add_electromagnetic_heating(comp)
    j.param().set("hconv", f"{opts['h_conv_w_m2k']:g}[W/(m^2*K)]")
    j.param().set("Text", f"{opts['t_ext_degc']:g}[degC]")

    # study：Frequency -> Stationary / Transient（类型串出厂自官方实录）
    study_kind = ("frequency_stationary" if opts["thermal"] == "stationary"
                  else "frequency_transient")
    ca.ComsolAdapter.build_multiphysics_study(
        j, study_kind=study_kind, freqs_ghz=[spec["freq_ghz"]],
        t_list=opts.get("t_list"), thermal_physics=(ca.HT_PHYSICS_TAG,))

    # 网格：全局粗 + 土豆域细化（域级 Size + 命名选择，真机验证手法）
    mesh = comp.mesh().create("mesh1")
    size = mesh.feature("size")
    size.set("custom", "on")
    size.set("hmax", opts["mesh_hmax_mm"])
    size_pot = mesh.create("size_potato", "Size")
    size_pot.selection().named("sel_potato")
    size_pot.set("custom", "on")
    size_pot.set("hmax", opts["potato_hmax_mm"])
    mesh.create("ftet1", "FreeTet")
    mesh.run()
    return model


def _dataset_candidates(model: Any) -> list[str | None]:
    """数据集候选序：默认解优先，其后按标签倒序（新建靠后=新解靠前）。

    真机实证：双步 study 的默认数据集可能是
    频率步解（无 T 场/ht 变量）→ 全 NaN 或报错；逐候选重试兜底
    （best-effort，不阻塞主读数）。
    """
    tags: list[str | None] = [None]
    try:
        for t in model.java.result().dataset().tags():
            s = str(t)
            if s not in tags:
                tags.append(s)
    except Exception:  # 桩对象/版本差异：只有默认候选
        pass
    return [tags[0], *reversed(tags[1:])]


def _extract_valid(model: Any, fetch: Callable[[str | None, int], Any]) -> Any:
    """逐数据集候选提取，首个成功者胜出（候选耗尽则如实抛错）。"""
    last_exc: Exception | None = None
    for k, ds in enumerate(_dataset_candidates(model)):
        try:
            return fetch(ds, k)
        except Exception as exc:  # JPype 异常族难枚举，逐候选吞（best-effort #105）
            last_exc = exc
    raise RuntimeError(f"所有数据集候选提取失败: {last_exc}")


def evaluate_oven(model: Any, spec: dict[str, float], opts: dict[str, Any],
                  *, wall_time_s: float) -> tuple[dict[str, Any], np.ndarray | None]:
    """求解后取功率/温度/温度场并做确定性检查与官方对照。

    返回 (报告片段, 温度场数组或 None)。所有判定都是确定性纯函数，便于离线复算。
    温度场验证口径（§10.24 d3-2 收口）：官方无温度场标量（模型文档全文检索
    定论），按替代口径输出能量守恒自洽锚（transient 绝热 m·Cp·ΔT /
    stationary 边界热流闭合）+ 官方截点位中心温度（中心峰化定性对照），
    报告内如实标注"自洽锚非官方"。
    """
    thermal = opts["thermal"]
    p_absorbed = _extract_valid(
        model, lambda ds, k: ca.ComsolAdapter.extract_absorbed_power(
            model, selection="sel_potato", expr=f"{ca.HT_PHYSICS_TAG}.Qtot",
            unit="W", dataset=ds, tag=f"int_pabs_{k}"))
    temp = _extract_valid(
        model, lambda ds, k: ca.ComsolAdapter.extract_temperature(
            model, selection="sel_potato", unit="degC", dataset=ds,
            tag_prefix=f"tstat_{k}_"))
    center_series = _extract_valid(
        model, lambda ds, k: ca.ComsolAdapter.evaluate_point_series(
            model, expr="T", point_exprs=OFFICIAL_CENTER_POINT_EXPRS,
            unit="degC", dataset=ds, tag=f"pt_center_{k}"))
    # 先落关键读数（后续步骤即使失败也留下真实数值，避免整轮白跑）
    print(f"[extract] P_absorbed={p_absorbed:.3f} W "
          f"T_max={temp['t_max_c']:.3f} degC T_avg={temp['t_avg_c']:.3f} degC "
          f"T_center={float(center_series[-1]):.3f} degC",
          flush=True)
    field = ca.ComsolAdapter.temperature_field(model, expr="T", unit="degC")
    field_stats: dict[str, Any] = {"available": False}
    if field is not None:
        try:  # 场统计是观测性产物：不得成为主路径故障点（#105）
            field_stats = {"available": True, **ca.temperature_summary(field)}
        except ValueError as exc:
            field_stats = {"available": False, "error": str(exc)}

    balance = ca.energy_balance(spec["pin_w"], p_absorbed)
    agreement = ca.reference_agreement(p_absorbed, OFFICIAL_ABSORBED_POWER_W,
                                       ACCEPTANCE_TOL)
    # 中心温度（官方截点位，dmodel.xml CutPoint3D 实录）+ 中心峰化定性对照
    t_init = spec["t0_degc"]
    center_last = float(center_series[-1])
    center_delta = center_last - t_init
    mean_delta = temp["t_avg_c"] - t_init
    ratio_center = (center_delta / mean_delta
                    if math.isfinite(mean_delta) and mean_delta > 0.0
                    else float("nan"))
    center_probe = {
        "point_exprs": list(OFFICIAL_CENTER_POINT_EXPRS),
        "point_source": "官方 dmodel.xml CutPoint3D cpt1（Figure 3 截点位）",
        "t_center_c": center_last,
        # 逐输出时刻中心温度序列（官方 Figure 3 对照数据——
        # 此前只落末值，整条曲线未存，Figure 3 形态对照无从做起）
        "t_center_series_c": [float(v) for v in np.asarray(center_series, float)],
        "center_delta_t_k": center_delta,
        "center_over_mean_delta": ratio_center,
        # 官方 Figure 2 定性叙述：源中心峰化（"中心具有很高的峰值"）→
        # 中心温升不得低于平均温升（无标量可对，只做定性一致性）
        "center_peaked": bool(math.isfinite(ratio_center) and ratio_center >= 1.0),
    }
    # 独立教科书裁判（球体均匀源**稳态**中心温升）——仅适用于 stationary
    # （有热沉的稳态边值问题）；transient 的 5s 场远未到稳态，对照稳态闭式
    # 属场景错配（真机实证：ratio 0.038 假性超档），改判"不适用"并注明理由，
    # 瞬态闭式裁判由能量锚（temperature_anchor）承担。
    q_vol = potato_power_density_w_m3(spec, p_absorbed)
    if thermal == "stationary":
        h_conv = float(opts["h_conv_w_m2k"])
        excess = ca.sphere_uniform_source_center_excess(
            q_vol, spec["rpot_mm"] * 1e-3, POTATO_K_W_MK, h_conv)
        t_ext = float(opts["t_ext_degc"])
        measured_excess = temp["t_max_c"] - t_ext
        ratio = measured_excess / excess if excess else float("nan")
        analytic: dict[str, Any] = {
            "applies": True,
            "model": ("uniform volumetric source in a sphere "
                      "(Incropera & DeWitt / Carslaw & Jaeger)"),
            "q_vol_w_m3": q_vol,
            "h_conv_w_m2k": h_conv,
            "predicted_center_excess_k": excess,
            "predicted_center_degc": t_ext + excess,
            "measured_max_excess_k": measured_excess,
            "measured_over_predicted": ratio,
            "order_of_magnitude_ok": bool(math.isfinite(ratio)
                                          and 0.4 <= ratio <= 5.0),
        }
    else:
        analytic = {
            "applies": False,
            "reason": ("稳态均匀源闭式不适用于绝热瞬态（5s 场远未到稳态）；"
                       "瞬态闭式裁判=能量锚 temperature_anchor + 中心峰化"
                       " center_probe"),
            "q_vol_w_m3": q_vol,
        }
    checks: dict[str, Any] = {
        "energy_conserved": balance["conserved"],
        "official_power_agreement": agreement["ok"],
        "center_peaked": center_probe["center_peaked"],
    }
    # §10.24 d3-2：能量守恒自洽锚（替代官方缺失的温度场标量，如实标注）
    temperature_anchor: dict[str, Any] = {"applies": False}
    if thermal == "transient":
        times = transient_times_s(opts.get("t_list"))
        anchor = ca.transient_energy_anchor(
            p_absorbed, float(times[-1] - times[0]), potato_mass_kg(spec),
            POTATO_CP_J_KG_K, temp["t_avg_c"], t_init)
        temperature_anchor = {"applies": True, "times_s": times, **anchor}
    else:
        q_out = _extract_valid(
            model, lambda ds, k: ca.ComsolAdapter.extract_surface_integral(
                model, selection="sel_potato_surface",
                expr=f"{ca.HT_PHYSICS_TAG}.ntflux", unit="W", dataset=ds,
                tag=f"int_qout_{k}"))
        temperature_anchor = {
            "applies": True,
            "mode": "stationary",
            **ca.energy_closure(p_absorbed, q_out),
        }
    checks["temperature_anchor_ok"] = bool(temperature_anchor.get("ok", False))
    if thermal == "stationary":
        checks["analytic_order_of_magnitude"] = analytic[
            "order_of_magnitude_ok"]
    report = {
        "power": {
            **balance,
            "reference_w": OFFICIAL_ABSORBED_POWER_W,
            "reference_note": ("官方 html Results：Volume Integration of "
                               "ht.Qtot over Potato = 631 W"),
            "official_absorbed_fraction_note": OFFICIAL_ABSORBED_FRACTION,
            "agreement": agreement,
        },
        "temperature_c": temp,
        "temperature_field": field_stats,
        "center_probe": center_probe,
        "temperature_anchor": temperature_anchor,
        "analytic_judge": analytic,
        "wall_time_s": round(wall_time_s, 1),
        "checks": checks,
    }
    return report, field


def write_field_csv(path: Path, field: np.ndarray | None) -> str | None:
    """温度场落 CSV（证据产物，best-effort #105）。"""
    if field is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = ["node_index,t_degc"]
        rows += [f"{k},{v:.6e}" for k, v in enumerate(np.asarray(field, float))]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return str(path)
    except OSError:
        return None


def render_center_curve_png(times_s: list[float], temps_c: list[float],
                            path: Path) -> str | None:
    """中心温度-时间曲线落 PNG（官方 Figure 3 对照我方曲线，#26③）。

    确定性渲染（matplotlib Agg，无随机性）；官方 Figure 3 无数值轴值可对，
    仅形态对照（中心峰化/趋稳量级）由 figure3_check 流程做多模态判读。
    渲染失败返回 None（观测性产物不阻塞主路径 #105）。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6.0, 4.0), dpi=120)
        ax.plot(np.asarray(times_s, float), np.asarray(temps_c, float),
                "o-", color="#1f77b4")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("T (degC)")
        ax.set_title("Potato center temperature (official CutPoint3D) — "
                     "cf. official model PDF Figure 3")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path)
        plt.close(fig)
        return str(path)
    except Exception:
        return None


def plan_report(spec: dict[str, float], opts: dict[str, Any]) -> dict[str, Any]:
    """离线计划报告（--dry-run）：参数/选择集/边界盒，全确定性、零真机。"""
    return {
        "probe": "a6-mwoven-comsol-microwave-oven",
        "schema": 1,
        "mode": "dry-run",
        "official_model": {
            "application_library": "RF_Module/Microwave_Heating/microwave_oven",
            "model_number": 1424,
            "study_official": "Frequency-Transient (one-way electromagnetic heating)",
            "study_here": opts["thermal"],
            "reference_absorbed_power_w": OFFICIAL_ABSORBED_POWER_W,
            "acceptance_tol": ACCEPTANCE_TOL,
            "temperature_reference": (
                "无官方标量（模型文档仅 Figure 3 瞬态中心温度曲线）→ "
                "能量守恒自洽锚（§10.24 d3-2，official=False）"),
        },
        "official_center_point": list(OFFICIAL_CENTER_POINT_EXPRS),
        "potato_mass_kg": potato_mass_kg(spec),
        "params": spec,
        "comsol_parameters": oven_comsol_parameters(spec),
        "geometry_bounds_mm": geometry_bounds(spec),
        "material_selections": {k: [v[0], list(v[1]), list(v[2])]
                                for k, v in material_selection_boxes(spec).items()},
        "boundary_selections": {k: [v[0], list(v[1]), list(v[2])]
                                for k, v in boundary_selection_boxes(spec).items()},
        "options": opts,
        "potato_volume_m3": potato_volume_m3(spec),
    }


def build_opts(args: argparse.Namespace) -> dict[str, Any]:
    """CLI → 求解选项（确定性）。"""
    return {
        "thermal": args.thermal,
        "h_conv_w_m2k": float(args.h_conv),
        "t_ext_degc": float(args.t_ext_degc),
        "mesh_hmax_mm": float(args.mesh_hmax_mm),
        "potato_hmax_mm": float(args.potato_hmax_mm),
        "t_list": args.t_list,
    }


def run_real(args: argparse.Namespace, spec: dict[str, float],
             opts: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray | None]:
    """真机路径：起 Client → 建模 → 求解 → 取功率/温度 → 释放模型（finally）。"""
    import mph  # 延迟导入：dry-run / 离线单测不触发 JVM

    t0 = time.time()
    client = mph.start(version=args.version, cores=args.cores)
    model = None
    field: np.ndarray | None = None
    try:
        model = build_oven_model(client, spec, opts)
        solve_t0 = time.time()
        model.java.study(ca.STUDY_TAG).run()  # Java 建的 study 用 tag().run()（#217③）
        solve_s = time.time() - solve_t0
        report, field = evaluate_oven(model, spec, opts, wall_time_s=solve_s)
    finally:
        if model is not None:
            with contextlib.suppress(Exception):  # license 席位释放 best-effort
                client.remove(model)
    report["mode"] = "real"
    report["solve_wall_time_s"] = round(solve_s, 1)
    report["total_wall_time_s"] = round(time.time() - t0, 1)
    return report, field


def render_summary(report: dict[str, Any]) -> str:
    """人类可读摘要（真机执行时打印）。"""
    if report.get("mode") == "dry-run":
        model = report["official_model"]
        return (f"DRY-RUN {model['application_library']}#{model['model_number']} "
                f"thermal={model['study_here']} params={report['params']}")
    power = report.get("power", {})
    temp = report.get("temperature_c", {})
    agreement = power.get("agreement", {})
    dev = agreement.get("rel_deviation")
    dev_txt = f"{dev * 100:.2f}%" if isinstance(dev, (int, float)) else "N/A"
    anchor = report.get("temperature_anchor", {})
    anchor_dev = anchor.get("rel_deviation")
    anchor_txt = (f"{anchor_dev * 100:.3f}%" if isinstance(anchor_dev, (int, float))
                  else "N/A")
    center = report.get("center_probe", {})
    return "\n".join([
        f"study={report.get('study_kind')} freq={report.get('freq_ghz')} GHz "
        f"Pin={power.get('p_input_w')} W",
        f"potato absorbed={power.get('p_absorbed_w')} W "
        f"(official {power.get('reference_w')} W, dev={dev_txt}, "
        f"ok={agreement.get('ok')})",
        f"temperature degC: Tmax={temp.get('t_max_c')} Tavg={temp.get('t_avg_c')} "
        f"Tmin={temp.get('t_min_c')}",
        f"T_center(official cut point)={center.get('t_center_c')} degC "
        f"center/mean ΔT={center.get('center_over_mean_delta')}",
        f"energy anchor ({anchor.get('anchor', 'N/A')}, official=False): "
        f"rel_dev={anchor_txt} ok={anchor.get('ok')}",
        f"checks={report.get('checks')}",
    ])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=ca.COMSOL_VERSION_PIN,
                        help="COMSOL 版本钉扎（默认 6.3；#215）")
    parser.add_argument("--cores", type=int, default=2)
    parser.add_argument("--freq-ghz", type=float, default=None,
                        help="激励频率（默认官方例 2.45 GHz）")
    parser.add_argument("--pin-w", type=float, default=None,
                        help="端口输入功率 W（默认官方例 full model 1 kW）")
    parser.add_argument("--thermal", choices=SUPPORTED_THERMAL_MODES,
                        default="stationary",
                        help="stationary=本脚本缺省的 Frequency-Stationary；"
                             "transient=官方例 Frequency-Transient")
    parser.add_argument("--h-conv", type=float, default=DEFAULT_H_CONV_W_M2K,
                        help="稳态对流换热系数 W/(m^2*K)（stationary 用）")
    parser.add_argument("--t-ext-degc", type=float, default=None,
                        help="外部环境温度 degC（默认 = T0）")
    parser.add_argument("--t-list", default="range(0,1,5)",
                        help="transient 输出时刻（COMSOL range 语法）")
    parser.add_argument("--mesh-hmax-mm", type=float, default=DEFAULT_MESH_HMAX_MM)
    parser.add_argument("--potato-hmax-mm", type=float,
                        default=DEFAULT_POTATO_HMAX_MM)
    parser.add_argument("--timeout-s", type=float, default=0.0,
                        help="求解硬超时秒数（0=不限；到点看门狗终止进程）")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--fig3-curve", action="store_true",
                        help="追加渲染中心温度-时间曲线 PNG（官方 Figure 3 "
                             "对照，#26③；transient 跑有效）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只输出计划（参数/选择集），不启 COMSOL")
    return parser.parse_args(argv)


def _arm_watchdog(timeout_s: float) -> threading.Timer | None:
    """超时看门狗：到点打印 TIMEOUT 并硬退出（进程级保护）。

    注意：硬退出不走 MPh 正常关闭路径，可能留下 comsolmphserver 进程；该取舍
    在 docstring 声明（可用 Get-Process comsolmphserver 复查并清理）。
    """
    if not timeout_s or timeout_s <= 0:
        return None

    def _fire() -> None:
        print(f"[TIMEOUT] 求解超过 {timeout_s:.0f}s，进程硬退出（退出码 4）",
              flush=True)
        os._exit(4)

    timer = threading.Timer(timeout_s, _fire)
    timer.daemon = True
    timer.start()
    return timer


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.t_ext_degc is None:
        args.t_ext_degc = MICROWAVE_OVEN_DEFAULTS["t0_degc"]
    spec = normalize_oven_params(freq_ghz=args.freq_ghz, pin_w=args.pin_w)
    opts = build_opts(args)
    out_dir = Path(args.out)

    if args.dry_run:
        report = plan_report(spec, opts)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "dry_run_plan.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(render_summary(report))
        return 0

    if not ca.mph_installed():
        print("[ERROR] MPh 未安装，COMSOL 通道不可用（退出码 3）", file=sys.stderr)
        return 3

    watchdog = _arm_watchdog(args.timeout_s)
    field: np.ndarray | None = None
    try:
        report, field = run_real(args, spec, opts)
    except Exception as exc:  # 真机异常如实落报告，不伪装成功
        print(f"[ERROR] COMSOL 复现失败: {exc}", file=sys.stderr)
        failure = {
            "probe": "a6-mwoven-comsol-microwave-oven",
            "schema": 1,
            "mode": "real",
            "status": "failed",
            "error": repr(exc),
            "params": spec,
            "options": opts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "oven_report.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        return 2
    finally:
        if watchdog is not None:
            watchdog.cancel()

    field_path = write_field_csv(out_dir / "temperature_field.csv", field)
    fig3_path: str | None = None
    if args.fig3_curve and opts["thermal"] == "transient":
        # 官方 Figure 3 对照曲线（逐输出时刻中心温度，#26③；best-effort）
        fig3_path = render_center_curve_png(
            report["temperature_anchor"]["times_s"],
            report["center_probe"]["t_center_series_c"],
            out_dir / "center_curve_fig3.png")
    report.update({
        "probe": "a6-mwoven-comsol-microwave-oven",
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comsol_version": args.version,
        "params": spec,
        "options": opts,
        "study_kind": ("frequency_stationary" if opts["thermal"] == "stationary"
                       else "frequency_transient"),
        "freq_ghz": spec["freq_ghz"],
        "wall_sigma_s_m": COPPER_SIGMA_S_M,
        "field_csv": field_path,
        "center_curve_fig3_png": fig3_path,
        "honest_notes": [
            "官方例是 Frequency-Transient；本跑为 Frequency-Stationary（本脚本口径）"
            if opts["thermal"] == "stationary" else
            "官方例即 Frequency-Transient，本跑与其同 study 型",
            "稳态 T_max 不是官方报告值（官方只给瞬态中心温度曲线），量级由 h_conv 决定"
            if opts["thermal"] == "stationary" else
            "瞬态末态温度为物理量级（绝热 5s 平均温升 = P·Δt/(m·Cp)，能量锚校验）",
            "官方标量验收门只有土豆吸收功率 631 W (full model, 1 kW) 的 ±5%",
            "温度场无官方标量（官方文档检索定论：模型 PDF 仅 Figure 3 "
            "瞬态曲线；姊妹模型 rotating_microwave_oven 的 380 K 属相变封顶物理，"
            "不适用）——temperature_anchor 为能量守恒自洽锚，official=False",
            "腔体 x=0 壁若为单个 U 形面则保持默认 PEC（薄盒无法完整包含该面），"
            "属已知极小口径偏差",
        ],
    })
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "oven_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(render_summary(report))
    print(f"report -> {out_dir / 'oven_report.json'}")
    return 0 if report["checks"]["official_power_agreement"] else 1


if __name__ == "__main__":
    sys.exit(main())
