"""octagonal_spiral 八角螺旋电感族（aurora_k K11，反馈 F1）。

GaAs 薄膜 IPD 工艺八角螺旋电感（W/S/N/Din 全 μm 标量参数）——集总无源
模板族首件。整脚本渲染器（coil_nfc 同款早分发）：八角折线螺旋
（across-flats 口径，45° 切角阶梯化）+ 内端过孔上引中跳线桥（lange
air-bridge 同法）+ 外端-焊盘水平桥隙 LumpedPort（**串联绕组口径**——
端口串在绕组回路里，Zin=R+jωL，SRF=绕组寄生并联谐振峰，电感 1 端口
L/SRF/Q 测量的标准拓扑）+ 可选底地平面（ground_plane）。

单位接线（K9 units:um helper 首个消费模板）：μm 参数经
core.stackup.to_mm(v, "um") 单源换算（渲染入口唯一换算 helper，P15）；
h_mm 基板厚走仓内基板惯例（mm）。d_out 闭式导出 d_in+2nW+2(n−1)S 与
CALC 键 octagonal_spiral_inductance 同语义（#154 同名同语义）。

闭式锚：Mohan 电流片式八角系数（core/nfc_coil 单源，Table IV 原文
锚在案）；质量门 L±25%/SRF>2×f0 由 CALC 键面承载（本模板 meta 只
登记判读口径，门函数零复制）。真机验证留登记（内部证据档）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import TEMPLATE_META, TEMPLATE_NOMINAL

# ── §OCTAGONAL_SPIRAL GaAs IPD 八角螺旋电感（2026-10-23 K11，文末注册块）────
# 名义设计点=反馈 F1 用户实测参考同量级档（n=5, din=80, w=10, s=5μm →
# L_闭式=4.1147nH，对 HFSS 实测 4.226/4.312nH 偏差 +2.7%/+4.8%，±25% 门内）；
# 基板 GaAs 半绝缘典型值（er=12.9/tanδ=0.0006/h=100μm 薄膜 IPD 档）。
OCTAGONAL_SPIRAL_TEMPLATES: frozenset[str] = frozenset({"octagonal_spiral"})

#: 45° 切角顶点偏移比 = tan(π/8)（across-flats 半宽 → 切角起点，与
#: core/nfc_coil.polygon_loop_vertices("octagon") 顶点角 π/8+k·π/4 同口径）
_CUT = math.tan(math.pi / 8.0)

OCTAGONAL_SPIRAL_META: dict[str, Any] = {
    "f0_ghz": 2.0, "n_ports": 1,
    "extraction": "S11 @ LumpedPort 1（外端-焊盘水平桥隙，R=50Ω CalcPort 同参考；"
                  "Zin=50(1+S11)/(1−S11)→低频段 L=Im(Zin)/(2πf) 提取，"
                  "Im(Zin) 过零/|Zin| 峰=SRF 判读——串联绕组提取，绕组寄生"
                  "并联谐振；L±25%/SRF>2×f0 质量判据由 CALC 键 "
                  "octagonal_spiral_inductance 承载）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_turns", "din_um", "w_um", "s_um", "gap_um", "h_mm",
               "ground_plane"],
    "topology": "GaAs IPD 八角螺旋电感：八角折线螺旋（across-flats 口径，"
                "d_out 闭式=d_in+2nW+2(n−1)S，45° 切角阶梯化渲染）+ 内端过孔"
                "上引中跳线桥（lange air-bridge 同法，把内端引出到外端端口"
                "同侧）+ 外端-焊盘水平桥隙 LumpedPort（端口串在绕组回路，"
                "Zin=R+jωL，SRF=寄生并联谐振峰）；可选底地平面"
                "（ground_plane=1 时全域金属地板，镜像降 L/Q 属物理）；"
                "全域 MUR（电小器件近场主导）",
    "param_semantics": "n_turns=匝数 N（渲染取整），din_um=内径 D_in（μm，"
                       "最内缘跨面宽），w_um=线宽 W（μm），s_um=匝间距 S（μm），"
                       "gap_um=外端-焊盘桥隙（μm，端口 x 向跨距），h_mm=基板厚"
                       "（仓内基板惯例 mm，GaAs 100μm 档），ground_plane=底地"
                       "平面开关（0/1，真值即开）；er/tan_d 走 substrate/nominal"
                       "（GaAs 半绝缘）——W/S/N/Din 全 μm 为 IPD 工艺口径，"
                       "经 core.stackup.to_mm(v,'um') 单源换算（μm 帮手函数"
                       "首个消费模板）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 max(w,s,gap)/4"
                 "（μm 尺度几何驱动网格，禁 λ_sub/50 口径——2GHz λ_sub/50"
                 "≈6mm 装不下 0.2mm 器件）；螺旋缘/切角阶梯盒缘/焊盘/过孔棱/"
                 "端口盒边精确入网（#198）；NEAR≤min(s,gap)/3 渲染期守卫"
                 "（#266）；全轴 1µm 近重合去重（#152）；45° 切角=步长 w 阶梯"
                 "盒（相邻盒重叠保证导通，阶梯缘与平边最小间距 ≥w/4）；端口盒"
                 "三向 ≥NEAR 厚、边全入网（#174/#283）",
    "smoke_note": "未冒烟（离线审计过，#212，test_octagonal_spiral_template）；"
                  "真机发射留登记（L/SRF/Q 三量 HFSS 对拍+Q 预算区间判据"
                  "待真机批，本批零发射）",
}
OCTAGONAL_SPIRAL_NOMINAL: dict[str, Any] = {
    "n_turns": 5,
    "din_um": 80.0,
    "w_um": 10.0,
    "s_um": 5.0,
    "gap_um": 10.0,
    "h_mm": 0.1,   # GaAs 100μm 薄膜 IPD 档（仓内基板惯例 mm）
    "ground_plane": 0,
    "er": 12.9, "tan_d": 0.0006,   # GaAs 半绝缘典型值
}

TEMPLATE_META["octagonal_spiral"] = OCTAGONAL_SPIRAL_META
TEMPLATE_NOMINAL["octagonal_spiral"] = OCTAGONAL_SPIRAL_NOMINAL


def _octagonal_spiral_layout(params: dict[str, Any],
                             freq_range_ghz: tuple[float, float],
                             mesh_resolution_mm: float = 0.0) -> dict[str, Any]:
    """octagonal_spiral 几何/端口/域单源（米）。

    几何拓扑（全部 z=H_SUB 顶层金属除桥/过孔/可选地板）：
    - 八角折线螺旋：turn k 中心线 across-flats 半宽 a_k=a_0−k·p（p=w+s），
      a_0=d_out/2−w/2、d_out=d_in+2nW+2(n−1)S 闭式导出（CALC 同语义）；
      每匝 8 段=右/上/左/下四平边（轴对齐）+四 45° 切角（阶梯化）；换匝
      过渡=下平边内延至 a_{k+1}+竖尾上接次匝右平边下端（coil_nfc 方螺旋
      尾语义的八角推广，末匝下平边止于内端 x=0）；
    - 中跳线桥：内端 (0,−a_min) 过孔上引 z=H+h_b，沿 +y 至中线再沿 +x 越
      右平边至焊盘，过孔下引落 pad；
    - 端口：LumpedPort 外端右缘↔焊盘左缘（x 向跨距=gap_um，串联绕组口径）。
    """

    # K9 units helper（渲染入口唯一换算单源）
    from rfauto.core.stackup import assert_thin_layer, to_mm

    n = round(float(params.get("n_turns",
                               OCTAGONAL_SPIRAL_NOMINAL["n_turns"])))
    if n < 1:
        raise ValueError(f"octagonal_spiral: n_turns 须 ≥1，收到 {n}")
    # μm 参数经 to_mm(v,"um") 单源换算（IPD 工艺口径；K9 helper 首个消费模板）
    din = to_mm(float(params.get("din_um",
                                 OCTAGONAL_SPIRAL_NOMINAL["din_um"])), "um") * 1e-3
    w = to_mm(float(params.get("w_um",
                               OCTAGONAL_SPIRAL_NOMINAL["w_um"])), "um") * 1e-3
    s = to_mm(float(params.get("s_um",
                               OCTAGONAL_SPIRAL_NOMINAL["s_um"])), "um") * 1e-3
    gap = to_mm(float(params.get("gap_um",
                                 OCTAGONAL_SPIRAL_NOMINAL["gap_um"])), "um") * 1e-3
    h = float(params.get("h_mm",
                         OCTAGONAL_SPIRAL_NOMINAL["h_mm"])) * 1e-3
    ground = bool(params.get("ground_plane",
                             OCTAGONAL_SPIRAL_NOMINAL["ground_plane"]))
    for name, v in (("din_um", din), ("w_um", w), ("s_um", s),
                    ("gap_um", gap), ("h_mm", h)):
        if not (math.isfinite(v) and v > 0):
            raise ValueError(f"octagonal_spiral: {name} 必须为正有限，得到 {v!r}")
    # P7 薄层朝向守卫接线（E1，aurora_l）：GaAs 薄膜基板盒（0.1mm 档，
    # h << d_out 足迹——薄层朝向域）z 跨度 vs 声明厚度（h_mm→to_mm("mm")
    # →mm→×1e-3 m 单源换算，K12 换算惯例同款）。线圈/跳线桥=零厚金属面
    # （z 跨度恒 0，无薄层厚度可校验）如实跳过；
    # 介质薄层本模板无，P7 主病灶面=mim_cap。
    assert_thin_layer(
        h,
        to_mm(float(params.get("h_mm",
                                OCTAGONAL_SPIRAL_NOMINAL["h_mm"])), "mm") * 1e-3,
        axis="z")
    # d_out 闭式导出（d_in+2nW+2(n−1)S，CALC 键 #154 同语义）
    d_out = din + 2.0 * n * w + 2.0 * (n - 1.0) * s
    a0 = d_out / 2.0 - w / 2.0
    pitch = w + s
    a_min = a0 - (n - 1) * pitch
    if a_min <= 2.0 * w:
        raise ValueError(
            f"octagonal_spiral: 几何不可行（内圈半宽 {a_min * 1e6:.4g}μm ≤ 2w，"
            "减小 n_turns 或线宽/间距）")
    # 网格：显式覆盖优先；自动档=几何驱动（μm 尺度禁 λ 口径，meta mesh_note）
    base = (max(w, s, gap) / 4.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm) * 1e-3)
    near = base / 4.0
    if near > min(s, gap) / 3.0:
        raise ValueError(
            f"octagonal_spiral: NEAR={near * 1e6:.4g}μm > min(s,gap)/3="
            f"{min(s, gap) / 3.0 * 1e6:.4g}μm（#266 耦合缝守卫，收紧 "
            "mesh_resolution_mm）")
    h_bridge = max(2.0 * near, base)   # 桥高（≥base，桥面独立 z 网格层）
    # 单折线匝梯：平边（轴对齐）+ 切角（45° 阶梯化）+ 换匝尾
    flats: list[tuple[float, float, float, float]] = []
    diags: list[tuple[float, float, float, float]] = []   # (x0,y0,x1,y1) 45°
    for k in range(n):
        a = a0 - k * pitch
        ca = _CUT * a
        flats.append((a, -ca, a, ca))                     # R_k（外端在 R0 下端）
        diags.append((a, ca, ca, a))                      # TR 切角
        flats.append((ca, a, -ca, a))                     # T_k
        diags.append((-ca, a, -a, ca))                    # TL 切角
        flats.append((-a, ca, -a, -ca))                   # L_k
        diags.append((-a, -ca, -ca, -a))                  # BL 切角
        # B_k：内延至次匝竖尾 x=a_{k+1}（coil_nfc 尾语义八角推广）；
        # 末匝止于内端 x=0
        x_end = (a0 - (k + 1) * pitch) if k < n - 1 else 0.0
        flats.append((-ca, -a, x_end, -a))
        if k < n - 1:
            a_nxt = a0 - (k + 1) * pitch
            flats.append((a_nxt, -a, a_nxt, -_CUT * a_nxt))   # 换匝竖尾
    # 内端/焊盘/端口/桥（焊盘在螺旋右侧，端口水平跨 gap）
    via_up_xy = (0.0, -a_min)
    pad_cx = a0 + w / 2.0 + gap + w / 2.0     # 焊盘中心 x
    pad = (pad_cx - w / 2.0, -w / 2.0, pad_cx + w / 2.0, w / 2.0)
    port_box = (a0 + w / 2.0, -w / 2.0, a0 + w / 2.0 + gap, w / 2.0)
    bridge_segs = [(0.0, -a_min, 0.0, 0.0), (0.0, 0.0, pad_cx, 0.0)]
    via_down_xy = (pad_cx, 0.0)
    # 域：结构外 d_out/2 余量（电小器件近场主导，λ0/4 级余量在 2GHz 不可行
    # ——0.22mm 器件对 150mm 波长为电小极限，MUR 近场吸收充分；右侧含焊盘）
    margin = d_out / 2.0
    dom_x = pad_cx + w / 2.0 + margin
    dom_y = a0 + w / 2.0 + margin
    # 导带总长（渲染匝梯实长：平边+阶梯折线+换匝尾；跳桥属附加不记）
    track = 0.0
    for x0, y0, x1, y1 in flats:
        track += math.hypot(x1 - x0, y1 - y0)
    for x0, y0, x1, y1 in diags:
        track += math.hypot(x1 - x0, y1 - y0) * math.sqrt(2.0)   # 阶梯化折线长
    return {
        "n": n, "d_out": d_out, "din": din, "w": w, "s": s, "gap": gap,
        "h": h, "ground": ground, "a0": a0, "pitch": pitch, "a_min": a_min,
        "base": base, "near": near, "h_bridge": h_bridge,
        "flats": flats, "diags": diags, "via_up": via_up_xy,
        "via_down": via_down_xy, "pad": pad, "pad_cx": pad_cx,
        "port_box": port_box, "bridge_segs": bridge_segs,
        "dom_x": dom_x, "dom_y": dom_y, "track": track,
    }


def _oct_diag_boxes(x0: float, y0: float, x1: float, y1: float, w: float,
                    z: float) -> list[tuple[float, float, float, float,
                                            float, float]]:
    """45° 对角段 → 侧长 w 的中心式重叠阶梯盒列（保证导通）。

    逐轴步长 ≤w/2（N=ceil(|dx|/(w/2))），相邻盒逐轴重叠 ≥w/2——阶梯
    折线保持在中心线 ±w/2 带内、连接无断点；阶梯缘与平边金属缘最小
    间距 ≥w/2−|步长偏差|（w≥4µm 档全部过 1µm 去重带，#152 渲染端
    前提；w<4µm 极端档近重合线由脚本 1µm 去重收敛，几何误差 ≤1µm
    如实）。z 为零厚面（顶层金属面）。
    """
    dx = x1 - x0
    dy = y1 - y0
    if abs(abs(dx) - abs(dy)) > 1e-12 * max(abs(dx), abs(dy), 1.0):
        raise ValueError("octagonal_spiral: 切角段须为 45°（|dx|=|dy|）")
    n_steps = max(1, math.ceil(abs(dx) / (w / 2.0)))
    boxes: list[tuple[float, float, float, float, float, float]] = []
    for i in range(n_steps):
        cx = x0 + (i + 0.5) * dx / n_steps
        cy = y0 + (i + 0.5) * dy / n_steps
        boxes.append((cx - w / 2.0, cy - w / 2.0, z,
                      cx + w / 2.0, cy + w / 2.0, z))
    return boxes


def _oct_flat_box(x0: float, y0: float, x1: float, y1: float, w: float,
                  z: float) -> tuple[float, float, float, float, float, float]:
    """轴对齐中心线段 → 金属薄盒 (x0,y0,z0,x1,y1,z1)，横向加宽 w/2。"""
    if abs(y0 - y1) <= 1e-15:      # 水平段
        return (min(x0, x1), y0 - w / 2.0, z,
                max(x0, x1), y0 + w / 2.0, z)
    return (x0 - w / 2.0, min(y0, y1), z,
            x0 + w / 2.0, max(y0, y1), z)


def octagonal_spiral_geometry_spec(params: dict[str, Any],
                                   substrate: dict[str, Any]) -> dict[str, Any]:
    """octagonal_spiral UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _octagonal_spiral_layout(params, (2.0, 2.0))

    def to_mm(v: float) -> float:
        return v * 1e3
    a0, w = lay["a0"], lay["w"]
    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-to_mm(lay["dom_x"]), -to_mm(lay["dom_y"]), 0.0],
         "stop_mm": [to_mm(lay["dom_x"]), to_mm(lay["dom_y"]),
                     to_mm(lay["h"])]},
        {"name": "spiral（八角螺旋，外接框）", "material": "metal",
         "start_mm": [-to_mm(a0 + w / 2.0), -to_mm(a0 + w / 2.0),
                      to_mm(lay["h"])],
         "stop_mm": [to_mm(a0 + w / 2.0), to_mm(a0 + w / 2.0),
                     to_mm(lay["h"])]},
        {"name": "pad（外端焊盘）", "material": "metal",
         "start_mm": [to_mm(lay["pad"][0]), to_mm(lay["pad"][1]),
                      to_mm(lay["h"])],
         "stop_mm": [to_mm(lay["pad"][2]), to_mm(lay["pad"][3]),
                     to_mm(lay["h"])]},
        {"name": "bridge（中跳线桥，外接框）", "material": "metal",
         "start_mm": [0.0, to_mm(-lay["a_min"]),
                      to_mm(lay["h"] + lay["h_bridge"])],
         "stop_mm": [to_mm(lay["pad_cx"]), 0.0,
                     to_mm(lay["h"] + lay["h_bridge"])]},
    ]
    if lay["ground"]:
        boxes.append({"name": "ground（底地平面）", "material": "metal",
                      "start_mm": [-to_mm(lay["dom_x"]),
                                   -to_mm(lay["dom_y"]), 0.0],
                      "stop_mm": [to_mm(lay["dom_x"]), to_mm(lay["dom_y"]),
                                  0.0]})
    px0, py0, px1, py1 = lay["port_box"]
    ports = [{"name": "Port1（外端-焊盘桥隙 LumpedPort，R=50Ω）",
              "pos_mm": [to_mm((px0 + px1) / 2.0), to_mm((py0 + py1) / 2.0),
                         to_mm(lay["h"])],
              "dir": [1.0, 0.0, 0.0]}]
    sub_view = dict(substrate)
    sub_view.update({"er": OCTAGONAL_SPIRAL_NOMINAL["er"],
                     "h_mm": OCTAGONAL_SPIRAL_NOMINAL["h_mm"],
                     "tan_d": OCTAGONAL_SPIRAL_NOMINAL["tan_d"]})
    return {"template": "octagonal_spiral", "substrate": sub_view,
            "boxes": boxes, "ports": ports, "elements": []}


def octagonal_spiral_render(template: str, params: dict[str, Any],
                            freq_range_ghz: tuple[float, float],
                            mesh_resolution_mm: float = 0.0,
                            substrate: dict[str, Any] | None = None,
                            excite_port: int = 1) -> str:
    """octagonal_spiral 整脚本渲染器（早分发自 render_script；coil_nfc 同款）。

    单端口（LumpedPort 外端-焊盘桥隙，串联绕组口径）：Zin=R+jωL 低频段
    → L 提取，寄生并联谐振峰=SRF 判读位；域全 MUR；_nrts 旋钮缺省
    逐字节不变。er/tan_d/h 从 params/NOMINAL 消费（模板自带 GaAs 板材；
    render_script 顶层会把缺省 substrate 重绑为 RO4350B——本族不用
    全局缺省板材，coil_nfc「er/tan_d 走 substrate/nominal」同口径）。
    """
    del substrate   # 板材走 params/NOMINAL（GaAs），显式弃用全局缺省
    er = float(params.get("er", OCTAGONAL_SPIRAL_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", OCTAGONAL_SPIRAL_NOMINAL["tan_d"]))
    lay = _octagonal_spiral_layout(params, freq_range_ghz, mesh_resolution_mm)
    if excite_port != 1:
        raise ValueError(
            f"octagonal_spiral: 单端口模板，excite_port 须为 1，收到 {excite_port}")
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    nrts = int(params.get("_nrts", 100000) or 100000)
    # 特征线收集（全部盒的边 + 端口盒边 + 桥中线；#198 精确入网）
    flat_boxes = [_oct_flat_box(*seg, lay["w"], lay["h"])
                  for seg in lay["flats"]]
    diag_boxes: list[tuple[float, float, float, float, float, float]] = []
    for seg in lay["diags"]:
        diag_boxes.extend(_oct_diag_boxes(*seg, lay["w"], lay["h"]))
    w2 = lay["w"] / 2.0
    via_u = (lay["via_up"][0] - w2, lay["via_up"][1] - w2, lay["h"],
             lay["via_up"][0] + w2, lay["via_up"][1] + w2,
             lay["h"] + lay["h_bridge"])
    via_d = (lay["via_down"][0] - w2, lay["via_down"][1] - w2, lay["h"],
             lay["via_down"][0] + w2, lay["via_down"][1] + w2,
             lay["h"] + lay["h_bridge"])
    bridge_boxes = [_oct_flat_box(*seg, lay["w"], lay["h"] + lay["h_bridge"])
                    for seg in lay["bridge_segs"]]
    pad = (*lay["pad"][:2], lay["h"], *lay["pad"][2:], lay["h"])
    px0, py0, px1, py1 = lay["port_box"]
    metal_boxes = flat_boxes + diag_boxes + bridge_boxes + [via_u, via_d, pad]
    xs: list[float] = []
    ys: list[float] = []
    for b in metal_boxes:
        xs += [b[0], b[3]]
        ys += [b[1], b[4]]
    xs += [px0, px1, 0.0]                       # 端口盒 x 边 + 桥竖腿中线
    ys += [py0, py1, 0.0]                       # 端口盒 y 边 + 桥横腿中线
    zs = [lay["h"] - lay["near"] / 2.0, lay["h"] + lay["near"] / 2.0,
          lay["h"] + lay["h_bridge"]]

    def dedup(vals: list[float]) -> list[float]:
        return sorted(set(round(float(v), 15) for v in vals))
    xs_t, ys_t, zs_t = dedup(xs), dedup(ys), dedup(zs)
    xs_lit = ", ".join(repr(v) for v in xs_t)
    ys_lit = ", ".join(repr(v) for v in ys_t)
    zs_lit = ", ".join(repr(v) for v in zs_t)
    fb_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in flat_boxes)
    db_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in diag_boxes)
    bb_lit = "\n".join(
        f"bridge.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in bridge_boxes)
    via_lit = "\n".join(
        f"coil.AddBox(({b[0]!r}, {b[1]!r}, {b[2]!r}), ({b[3]!r}, {b[4]!r}, "
        f"{b[5]!r}), priority=10)" for b in (via_u, via_d))
    pad_lit = (f"coil.AddBox(({pad[0]!r}, {pad[1]!r}, {pad[2]!r}), "
               f"({pad[3]!r}, {pad[4]!r}, {pad[5]!r}), priority=10)")
    ground_lit = (
        "ground.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=0)"
        if lay["ground"] else
        "# ground_plane=0：无底地平面（IPD 悬空口径）")
    ground_block = (
        "ground = CSX.AddMetal(\"ground\")\n" + ground_lit
        if lay["ground"] else ground_lit)
    return f'''#!/usr/bin/env python3
"""openEMS octagonal_spiral script (rfauto aurora_k K11 auto-generated).

几何/端口/网格口径见
src/rfauto/adapters/oe_templates/render_octagonal_spiral.py 模块头。
GaAs IPD μm 工艺八角螺旋电感：串联绕组口径（Zin=R+jωL，SRF=寄生并联
谐振峰），μm 参数经 core.stackup.to_mm(v,"um") 单源换算。
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
ER = {er!r}
TAND = {tan_d!r}
H_SUB = {lay["h"]!r}
H_BRIDGE = {lay["h_bridge"]!r}   # 跳线桥离板高（桥面=抬高金属层）
NEAR = {lay["near"]!r}   # 近特征区 = base/4
BASE = {lay["base"]!r}   # 网格 base：自动档 max(w,s,gap)/4（μm 几何驱动）
DOM_X = {lay["dom_x"]!r}
DOM_Y = {lay["dom_y"]!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 电小器件近场主导：全 MUR（地平面存在时为显式金属地板，域界仍 MUR）
FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 螺旋/切角阶梯/桥/过孔/焊盘/端口全部特征线精确入网（#198），先 NEAR 后
# BASE 平滑，域界最后补入（平滑保线，coil_nfc 同款次序）
for _x in np.array([{xs_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{ys_lit}]):
    mesh.AddLine("y", _y)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([{zs_lit}]))
mesh.AddLine("z", np.array([-0.5 * (DOM_X - NEAR), H_SUB + 0.5 * (DOM_X - NEAR)]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：按最小间距 1µm 去重。GetLines 必须先排序：
# 上游 0.7.0 绑定 GetLines 按插入序返回（AddLine 尾插不排序，docstring
# "sorted and unique" 失实）——不排序时守卫从最左特征线起步、走到尾部
# -DOM 负间隙即静默丢弃域界线（coil_nfc 首次真跑实证）。排序对新引擎是
# 修正、对旧引擎（本就有序返回）恒等。
for _ax in ("x", "y", "z"):
    _ls = np.sort(np.asarray(mesh.GetLines(_ax), dtype=float))
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：GaAs 基板 + 八角螺旋（平边+切角阶梯）+ 中跳线桥 + 焊盘 ──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
{ground_block}
coil = CSX.AddMetal("coil")
# 平边（轴对齐段：右/上/左/下四边 + 换匝竖尾）
{fb_lit}
# 45° 切角（w×w 重叠阶梯盒，步长 ≤w 保证导通）
{db_lit}
# 过孔×2（内端上引 / 桥端下引落 pad）
{via_lit}
# 中跳线桥（抬高 z=H+H_BRIDGE，越下层走线不接触；lange air-bridge 同法）
bridge = CSX.AddMetal("bridge")
{bb_lit}
# 端口落焊盘（外端右侧）
{pad_lit}

# ── 端口：LumpedPort 外端-焊盘水平桥隙（串联绕组口径，盒三向厚、
#    对称跨 z=H 金属面；exc 沿 +x=主电流方向）──
_port1 = LumpedPort(CSX, 1, 50.0,
                    np.array([{px0!r}, {py0!r}, {lay["h"] - lay["near"] / 2.0!r}]),
                    np.array([{px1!r}, {py1!r}, {lay["h"] + lay["near"] / 2.0!r}]),
                    "x", excite=1, priority=5)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（Zin=50(1+S11)/(1−S11)；低频段 L=Im(Zin)/(2πf)，
#    Im(Zin) 过零/|Zin| 峰=SRF 判读位）──
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
    "template": "octagonal_spiral",
    "f0_hz": F0, "fc_hz": FC,
    "n_turns": {lay["n"]},
    "d_in_m": {lay["din"]!r}, "d_out_m": {lay["d_out"]!r},
    "w_m": {lay["w"]!r}, "s_m": {lay["s"]!r}, "gap_m": {lay["gap"]!r},
    "h_sub_m": H_SUB, "ground_plane": {int(lay["ground"])},
    "er": ER, "tan_d": TAND,
    "track_length_m": {lay["track"]!r},
    "judgement_note": "L=Im(Zin)/(2πf) 低频段提取；SRF=Im(Zin) 过零/|Zin| 峰；"
                      "质量判据 L±25%/SRF>2×f0 见 CALC octagonal_spiral_inductance",
    "nrts": NRTS,
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
}}
with open(os.path.join(SCRIPT_DIR, "octagonal_spiral_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto octagonal_spiral simulation done")
'''
