"""mim_cap MIM 叠层电容族（aurora_k K12，反馈 F1）。

GaAs 薄膜 IPD 工艺 MIM 电容（金属-绝缘体-金属三明治，W/L/D 全 μm 标量
参数）——集总无源电容模板族首件。整脚本渲染器（octagonal_spiral 同款
早分发）：下极板（零厚金属面，z=H）- 介质薄层（真实体块，z∈[H,H+d]）-
上极板（零厚金属面，z=H+d）+ **竖直 LumpedPort 跨介质**（上极板-下极板
之间，exc 沿 z，并联口径 Zin=1/(jωC)+串联寄生——C 的标准 1 端口测量
拓扑；并联/串联自洽口径见 fake 通道 docstring）。

**K9 stackup/共形消费示范**（本模板的 stackup 面职责）：
- z 叠算走 core.stackup.Stackup.from_dict→z_ranges()（衬底 [-h,0] +
  mim_diel 层 [0,d]，渲染 z = 叠算 z + H 单源映射，z 账目连续不加手算）；
- 介质层=共形层**单足迹退化档**：plan_conformal_dielectric（下极板
  足迹，metal_thickness=0 零厚面）→ over_metal 单段 [0,d]——规划器
  三自检（零重叠/厚度/面积核算）随 plan 透传（F2 语义）；
- 薄层朝向守卫：P7 assert_thin_layer 在 _mim_cap_layout 对账 stackup
  链（d_um→z_ranges μm→m）vs params 链（d_um→to_mm→mm→m）的介质
  z 跨度（aurora_l E1 接线——竖墙病灶 0.2μm 建成 15μm 渲染期
  fail-fast，全仓 P7 病灶原型模板）。

网格（薄层守卫纪律）：介质厚 d=0.2μm 是全模板最小特征——z 向 H、
H+d/2、H+d 三线显式入网（端口激励体积 ≥2 格，#283）；#152 去重阈值
**z 轴降为 d/4**（全局 1µm 阈值会吞掉介质线——薄层模板的 #152 族
适配）；x/y 维持 1µm 档。CFL 代价如实声明：min z-cell=d/2=0.1μm →
dt≈0.33fs（薄介质 FDTD 物理成本，真机预算留登记 内部证据档）。

闭式锚：平行板 C=ε0·εr·A/d 单源 core/package_interconnect.mim_
capacitance（复用零复制）；质量门 C±25%（精确几何档）/SRF>2×f0 由
CALC 键 mim_capacitance 承载（meta 只登记判读口径，门函数零复制）。
真机验证留登记（内部证据档）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import TEMPLATE_META, TEMPLATE_NOMINAL

# ── §MIM_CAP GaAs IPD MIM 电容（2026-10-23 K12，文末注册块）─────────────────
# 名义设计点=反馈 F1 同量级档（w=l=20μm 叠合、d=0.2μm SiNx → C_闭式=
# 132.81fF，面密度 0.333fF/μm²——0.2μm SiNx IPD 工艺典型档）；基板 GaAs
# 半绝缘典型值（er=12.9/tanδ=0.0006/h=100μm 薄膜 IPD 档，K11 同板）。
MIM_CAP_TEMPLATES: frozenset[str] = frozenset({"mim_cap"})

MIM_CAP_META: dict[str, Any] = {
    "f0_ghz": 2.0, "n_ports": 1,
    "extraction": "S11 @ LumpedPort 1（上极板-下极板竖直跨介质，R=50Ω "
                  "CalcPort 同参考；Zin=50(1+S11)/(1−S11)→低频段 "
                  "C=−1/(ω·Im(Zin)) 提取，Im(Zin) 过零=串联 SRF 判读——"
                  "并联形式，Zin=R_s+jωL_s+1/(jωC)；C±25%/SRF>2×f0 质量"
                  "判据由 CALC 键 mim_capacitance 承载）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_um", "l_um", "d_um", "bot_overhang_um", "port_um",
               "h_mm", "er_diel", "tand_diel"],
    "topology": "GaAs IPD MIM 电容：下极板（零厚金属面 z=H，上极板足迹"
                "外扩 bot_overhang）- 介质薄层（真实体块 z∈[H,H+d]，SiNx）"
                "- 上极板（零厚金属面 z=H+d，W×L 叠合面积=C 的 A）；竖直 "
                "LumpedPort 跨介质（上-下极板之间，exc 沿 z，并联形式）；"
                "全域 MUR（电小器件近场主导）；stackup z 叠算+共形介质"
                "单足迹退化档消费（render 模块头）",
    "param_semantics": "w_um/l_um=上极板叠合区宽/长（μm，C 的 A=w·l），"
                       "d_um=介质厚（μm，SiNx 0.2μm 典型档），"
                       "bot_overhang_um=下极板四周外伸（μm，抑制边缘场集"
                       "中），port_um=端口盒 x/y 跨距（μm，≥2 格 #283），"
                       "h_mm=基板厚（仓内基板惯例 mm，GaAs 100μm 档）；"
                       "er_diel/tand_diel=介质 εr/损耗（SiNx）；er/tan_d 走 "
                       "substrate/nominal（GaAs）——W/L/D 全 μm 为 IPD 工艺"
                       "口径，经 core.stackup.to_mm(v,'um') 单源换算（μm "
                       "帮手函数）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 "
                 "max(port,d)（μm 尺度几何驱动网格——base 取最细 x/y 特征"
                 "端口盒，#266 守卫 NEAR=base/4 ≤ port/3；禁 λ_sub/50 "
                 "口径）；"
                 "极板缘/端口盒边+中线精确入网（#198）；介质薄层 z 向三线"
                 "（H、H+d/2、H+d）显式入网——端口激励体积 ≥2 格（#283），"
                 "#152 去重阈值 z 轴降为 d/4（全局 1µm 阈值吞介质线——薄层"
                 "适配）；NEAR≤port/3 渲染期守卫（#266——最细 x/y 特征="
                 "端口盒；介质 z 线显式不受 NEAR 平滑影响）；min "
                 "z-cell=d/2 → dt≈d/2c（薄介质 FDTD 物理成本，真机预算留"
                 "登记）",
    "smoke_note": "未冒烟（离线审计过，#212，test_k12_ipc_caps）；真机发射"
                  "留登记（C/SRF 低频回收对拍待真机批，本批零发射）",
}
MIM_CAP_NOMINAL: dict[str, Any] = {
    "w_um": 20.0,
    "l_um": 20.0,
    "d_um": 0.2,
    "bot_overhang_um": 5.0,
    "port_um": 2.5,
    "h_mm": 0.1,   # GaAs 100μm 薄膜 IPD 档（仓内基板惯例 mm）
    "er_diel": 7.5, "tand_diel": 0.001,   # SiNx 典型档
    "er": 12.9, "tan_d": 0.0006,          # GaAs 半绝缘典型值（substrate）
}

TEMPLATE_META["mim_cap"] = MIM_CAP_META
TEMPLATE_NOMINAL["mim_cap"] = MIM_CAP_NOMINAL


def _mim_cap_layout(params: dict[str, Any],
                    freq_range_ghz: tuple[float, float],
                    mesh_resolution_mm: float = 0.0) -> dict[str, Any]:
    """mim_cap 几何/端口/域单源（米）。

    z 叠算单源：Stackup.from_dict（衬底+mim_diel 层）→z_ranges()——
    渲染 z = 叠算 z + H（叠算 z=0 为衬底顶）；介质段单源：
    plan_conformal_dielectric 单足迹退化档（over_metal 单段，三自检
    随 plan 透传）。
    """
    from rfauto.core.stackup import (
        Stackup,
        assert_thin_layer,
        plan_conformal_dielectric,
        to_mm,
    )

    # μm 参数经 to_mm(v,"um") 单源换算（IPD 工艺口径）
    w = to_mm(float(params.get("w_um", MIM_CAP_NOMINAL["w_um"])), "um") * 1e-3
    lp = to_mm(float(params.get("l_um", MIM_CAP_NOMINAL["l_um"])), "um") * 1e-3
    d = to_mm(float(params.get("d_um", MIM_CAP_NOMINAL["d_um"])), "um") * 1e-3
    ov = to_mm(float(params.get("bot_overhang_um",
                                MIM_CAP_NOMINAL["bot_overhang_um"])), "um") * 1e-3
    pw = to_mm(float(params.get("port_um",
                                MIM_CAP_NOMINAL["port_um"])), "um") * 1e-3
    h = float(params.get("h_mm", MIM_CAP_NOMINAL["h_mm"])) * 1e-3
    er_diel = float(params.get("er_diel", MIM_CAP_NOMINAL["er_diel"]))
    tand_diel = float(params.get("tand_diel",
                                 MIM_CAP_NOMINAL["tand_diel"]))
    for name, v in (("w_um", w), ("l_um", lp), ("d_um", d), ("bot_overhang_um", ov),
                    ("port_um", pw), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"mim_cap: {name} 必须为正有限，得到 {v!r}")
    for name, v in (("er_diel", er_diel), ("tand_diel", tand_diel)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"mim_cap: {name} 必须为正有限，得到 {v!r}")
    # K9 z 叠算单源：衬底 + mim_diel 层（μm 制）→ 渲染 z = 叠算 z + H
    stack = Stackup.from_dict({
        "substrate": {"name": "GaAs", "material": "GaAs",
                      "thickness": float(h) * 1e6, "er": 12.9},
        "layers": [{"name": "mim_diel", "material": "SiNx",
                    "thickness": float(d) * 1e6, "er": er_diel}],
    })
    zr = {r.name: r for r in stack.z_ranges()}
    z_diel_lo = zr["mim_diel"].z_lo * 1e-6 + h     # 渲染系（m）
    z_diel_hi = zr["mim_diel"].z_hi * 1e-6 + h
    # P7 薄层朝向守卫接线（E1，aurora_l；层盒创建即校验，fail-fast 不带病
    # 求解）：介质薄层实测 z 跨度（stackup 链：d_um→Stackup thickness μm→
    # z_ranges→×1e-6 m）vs 声明厚度（params 链：d_um→to_mm("um")→mm→
    # ×1e-3 m）——两条独立换算链在此对账，单位错配/竖墙病灶（0.2μm SiNx
    # 建成 15μm 竖墙，实测/声明差两个数量级）渲染期必红，换向指引随
    # ModelBuildError 抛出（K12 消费示范的守卫半区，mim_cap 是全仓 P7
    # 病灶原型模板）。
    assert_thin_layer(z_diel_hi - z_diel_lo, d, axis="z")
    if abs(z_diel_lo - h) > 1e-15 or abs(z_diel_hi - (h + d)) > 1e-15:
        raise ValueError("mim_cap: stackup z 叠算与 d_um 不一致（内部错误）")
    # K9 共形介质规划器（单足迹退化档：over_metal 单段=介质板块）
    bot = (-(w / 2.0 + ov), -(lp / 2.0 + ov), w / 2.0 + ov, lp / 2.0 + ov)
    plan = plan_conformal_dielectric([tuple(v * 1e6 for v in bot)],
                                     thickness=float(d) * 1e6,
                                     metal_thickness=0.0, z_top_of_metal=0.0)
    if len(plan["segments"]) != 1 or plan["segments"][0]["kind"] != "over_metal":
        raise ValueError("mim_cap: 共形规划器单足迹档应恰 1 段 over_metal")
    top = (-w / 2.0, -lp / 2.0, w / 2.0, lp / 2.0)
    # 端口盒（竖直跨介质，居上极板中部；x/y ≥2 格由显式中线保证 #283）
    port_box = (-pw / 2.0, -pw / 2.0, h, pw / 2.0, pw / 2.0, h + d)
    if pw >= min(w, lp) / 2.0:
        raise ValueError(
            f"mim_cap: port_um={params.get('port_um')!r} ≥ 极板半宽"
            "（端口盒须内含于叠合区）")
    # 网格：显式覆盖优先；自动档=几何驱动（μm 尺度禁 λ 口径）——base 取
    # 最细 x/y 特征（端口盒 pw；#266 守卫 NEAR=base/4 ≤ pw/3 要求
    # base ≤ 4pw/3，取 base=pw 留 1.33 倍余量；介质 z 向三线显式入网
    # 不受 base/NEAR 平滑影响）
    base = (max(pw, d) if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    if near > pw / 3.0:
        raise ValueError(
            f"mim_cap: NEAR={near * 1e6:.4g}μm > port/3="
            f"{pw / 3.0 * 1e6:.4g}μm（#266 特征分辨守卫——最细 x/y 特征="
            "端口盒；介质 z 向三线显式入网不受 NEAR 平滑影响，收紧 "
            "mesh_resolution_mm）")
    # 域：结构外 max(w,l)/2+ov 余量（电小器件近场主导，MUR 近场吸收）
    margin = max(w, lp) / 2.0 + ov
    dom_x = w / 2.0 + ov + margin
    dom_y = lp / 2.0 + ov + margin
    area = w * lp
    return {
        "w": w, "l": lp, "d": d, "ov": ov, "pw": pw, "h": h,
        "er_diel": er_diel, "tand_diel": tand_diel,
        "bot": bot, "top": top, "port_box": port_box,
        "z_diel": (z_diel_lo, z_diel_hi),
        "n_plan_segments": len(plan["segments"]),
        "base": base, "near": near, "dom_x": dom_x, "dom_y": dom_y,
        "area_m2": area,
    }


def mim_cap_geometry_spec(params: dict[str, Any],
                          substrate: dict[str, Any]) -> dict[str, Any]:
    """mim_cap UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _mim_cap_layout(params, (2.0, 2.0))

    def mm(v: float) -> float:
        return v * 1e3

    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-mm(lay["dom_x"]), -mm(lay["dom_y"]), 0.0],
         "stop_mm": [mm(lay["dom_x"]), mm(lay["dom_y"]), mm(lay["h"])]},
        {"name": "bot_plate（下极板）", "material": "metal",
         "start_mm": [mm(lay["bot"][0]), mm(lay["bot"][1]), mm(lay["h"])],
         "stop_mm": [mm(lay["bot"][2]), mm(lay["bot"][3]), mm(lay["h"])]},
        {"name": "mim_diel（介质薄层）", "material": "mim_diel",
         "start_mm": [mm(lay["bot"][0]), mm(lay["bot"][1]),
                      mm(lay["z_diel"][0])],
         "stop_mm": [mm(lay["bot"][2]), mm(lay["bot"][3]),
                     mm(lay["z_diel"][1])]},
        {"name": "top_plate（上极板）", "material": "metal",
         "start_mm": [mm(lay["top"][0]), mm(lay["top"][1]),
                      mm(lay["z_diel"][1])],
         "stop_mm": [mm(lay["top"][2]), mm(lay["top"][3]),
                     mm(lay["z_diel"][1])]},
    ]
    px0, py0, pz0, px1, py1, pz1 = lay["port_box"]
    ports = [{"name": "Port1（上-下极板竖直跨介质 LumpedPort，R=50Ω）",
              "pos_mm": [mm((px0 + px1) / 2.0), mm((py0 + py1) / 2.0),
                         mm((pz0 + pz1) / 2.0)],
              "dir": [0.0, 0.0, 1.0]}]
    sub_view = dict(substrate)
    sub_view.update({"er": MIM_CAP_NOMINAL["er"],
                     "h_mm": MIM_CAP_NOMINAL["h_mm"],
                     "tan_d": MIM_CAP_NOMINAL["tan_d"]})
    return {"template": "mim_cap", "substrate": sub_view,
            "boxes": boxes, "ports": ports, "elements": []}


def mim_cap_render(template: str, params: dict[str, Any],
                   freq_range_ghz: tuple[float, float],
                   mesh_resolution_mm: float = 0.0,
                   substrate: dict[str, Any] | None = None,
                   excite_port: int = 1) -> str:
    """mim_cap 整脚本渲染器（早分发自 render_script；octagonal_spiral 同款）。

    单端口（LumpedPort 上-下极板竖直跨介质，并联口径）：低频段
    Zin≈1/(jωC) → C 提取；串联寄生（R_s+jωL_s）致 Im(Zin) 过零=SRF
    判读位。域全 MUR；_nrts 旋钮缺省逐字节不变。er/tan_d 走
    params/NOMINAL（GaAs 板材）；er_diel/tand_diel 介质自带。
    """
    del substrate   # 板材走 params/NOMINAL（GaAs），显式弃用全局缺省
    er = float(params.get("er", MIM_CAP_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", MIM_CAP_NOMINAL["tan_d"]))
    lay = _mim_cap_layout(params, freq_range_ghz, mesh_resolution_mm)
    if excite_port != 1:
        raise ValueError(
            f"mim_cap: 单端口模板，excite_port 须为 1，收到 {excite_port}")
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    nrts = int(params.get("_nrts", 100000) or 100000)
    # 特征线收集（#198 精确入网）：极板缘 + 端口盒边/中线
    bot, top = lay["bot"], lay["top"]
    px0, py0, pz0, px1, py1, pz1 = lay["port_box"]
    xs = [bot[0], bot[2], top[0], top[2], px0, px1, (px0 + px1) / 2.0]
    ys = [bot[1], bot[3], top[1], top[3], py0, py1, (py0 + py1) / 2.0]
    # z：衬底分层 + 介质三线（H、H+d/2、H+d——端口激励体积 ≥2 格 #283）
    zs = [0.0, lay["h"] / 4.0, lay["h"] / 2.0, 3.0 * lay["h"] / 4.0,
          lay["h"], (lay["h"] + lay["z_diel"][1]) / 2.0, lay["z_diel"][1]]
    z_dedup = min(1e-6, lay["d"] / 4.0)   # #152 z 轴薄层适配（吞介质线警戒）

    def uniq15(vals: list[float]) -> list[float]:
        return sorted(set(round(float(v), 15) for v in vals))
    xs_t, ys_t, zs_t = uniq15(xs), uniq15(ys), uniq15(zs)
    xs_lit = ", ".join(repr(v) for v in xs_t)
    ys_lit = ", ".join(repr(v) for v in ys_t)
    zs_lit = ", ".join(repr(v) for v in zs_t)
    z_thr_lit = repr(z_dedup)
    return f'''#!/usr/bin/env python3
"""openEMS mim_cap script (rfauto aurora_k K12 auto-generated).

几何/端口/网格口径见
src/rfauto/adapters/oe_templates/render_mim_cap.py 模块头。
GaAs IPD μm 工艺 MIM 电容：并联口径（竖直 LumpedPort 跨介质，
Zin=R_s+jωL_s+1/(jωC)），μm 参数经 core.stackup.to_mm(v,"um") 单源换算。
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
from openEMS.ports import LumpedPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}   # 基板 GaAs（scope["ER"] 审计契约键名，K11 同名）
TAND_SUB = {tan_d!r}
ER_DIEL = {lay["er_diel"]!r}
TAND_DIEL = {lay["tand_diel"]!r}
H_SUB = {lay["h"]!r}
D_MIM = {lay["d"]!r}   # 介质厚（全模板最小特征，z 向三线显式入网 #283）
NEAR = {lay["near"]!r}   # 近特征区 = base/4
BASE = {lay["base"]!r}   # 网格 base：自动档 max(port,d)（最细 x/y 特征驱动）
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 电小器件近场主导：全 MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 极板缘/端口盒边+中线精确入网（#198），先 NEAR 后域界（octagonal_spiral
# 同款次序：域界平滑后补入，外侧粗格不触 CFL——CFL 由 min cell 决定）
for _x in np.array([{xs_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{ys_lit}]):
    mesh.AddLine("y", _y)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
# z：衬底分层 + 介质三线（H、H+d/2、H+d）先入，平滑（只细分 >BASE 的大
# 间隙，介质细线保留），域界最后补入
for _z in np.array([{zs_lit}]):
    mesh.AddLine("z", _z)
mesh.SmoothMeshLines("z", BASE)
mesh.AddLine("z", np.array([-0.5 * (DOM_X - NEAR), H_SUB + 0.5 * (DOM_X - NEAR)]))
# 近重合网格线守卫（#152×#198 联合）：显式特征线（极板缘/端口盒边+中线/
# 介质三线，_feat_* 保护集）全部保留（nm 级自去重），其余平滑产物线只在
# 距全部已保留线 >thr 时收编——特征线永不被去重吞掉（否则端口盒边/介质
# 面落格漂移 ≤1µm，#283 探针吸附面），且终集无 <thr 近重合线。x/y 轴
# 1µm 档；z 轴阈值降为 D_MIM/4（全局 1µm 阈值会吞掉介质薄层三线——薄层
# 模板 #152 族适配）。GetLines 必须先排序：上游 0.7.0 绑定按插入序返回
# （docstring "sorted and unique" 失实，octagonal_spiral 首次真跑实证）。
_feat_x = np.array([{xs_lit}])
_feat_y = np.array([{ys_lit}])
_feat_z = np.array([{zs_lit}])
for _ax, _thr, _feat in (("x", 1e-6, _feat_x), ("y", 1e-6, _feat_y),
                         ("z", {z_thr_lit}, _feat_z)):
    _ls = np.sort(np.asarray(mesh.GetLines(_ax), dtype=float))
    _keep: list = []
    for _v in np.sort(np.unique(np.round(_feat, 12))):
        if not _keep or _v - _keep[-1] > 1e-9:
            _keep.append(float(_v))
    for _v in _ls:
        if all(abs(_v - _k) > _thr for _k in _keep):
            _keep.append(float(_v))
            _keep.sort()
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：GaAs 基板 + 下极板/介质/上极板三明治 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND_SUB * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
diel = CSX.AddMaterial("mim_diel", epsilon=ER_DIEL,
                       kappa=TAND_DIEL * 2 * np.pi * F0 * 8.854187817e-12 * ER_DIEL)
diel.AddBox(({bot[0]!r}, {bot[1]!r}, H_SUB), ({bot[2]!r}, {bot[3]!r}, H_SUB + D_MIM), priority=0)
metal = CSX.AddMetal("metal")
# 下极板（z=H 零厚面，上极板足迹外扩 BOT_OV）
metal.AddBox(({bot[0]!r}, {bot[1]!r}, H_SUB), ({bot[2]!r}, {bot[3]!r}, H_SUB), priority=10)
# 上极板（z=H+D_MIM 零厚面，W×L 叠合区=C 的 A）
metal.AddBox(({top[0]!r}, {top[1]!r}, H_SUB + D_MIM), ({top[2]!r}, {top[3]!r}, H_SUB + D_MIM), priority=10)

# ── 端口：LumpedPort 上-下极板竖直跨介质（并联口径，盒三向非零：
#    z 跨介质两层格 #283；exc 沿 z=主电流方向）──
_port1 = LumpedPort(CSX, 1, 50.0,
                    np.array([{px0!r}, {py0!r}, {pz0!r}]),
                    np.array([{px1!r}, {py1!r}, {pz1!r}]),
                    "z", excite=1, priority=5)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（Zin=50(1+S11)/(1−S11)；低频段 C=−1/(ω·Im(Zin))，
#    Im(Zin) 过零=串联 SRF 判读位）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port1.uf_ref / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag])
summary = {{
    "ok": True,
    "template": "mim_cap",
    "f0_hz": F0, "fc_hz": FC,
    "w_m": {lay["w"]!r}, "l_m": {lay["l"]!r}, "d_m": D_MIM,
    "bot_overhang_m": {lay["ov"]!r}, "port_box_m": {lay["port_box"]!r},
    "h_sub_m": H_SUB,
    "er_sub": ER, "tan_d_sub": TAND_SUB,
    "er_diel": ER_DIEL, "tan_d_diel": TAND_DIEL,
    "overlap_area_m2": {lay["area_m2"]!r},
    "judgement_note": "C=−1/(ω·Im(Zin)) 低频段提取（并联形式）；SRF="
                      "Im(Zin) 过零（串联寄生谐振）；质量判据 C±25%/SRF>2×f0 "
                      "见 CALC mim_capacitance",
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "mim_cap_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto mim_cap simulation done")
'''
