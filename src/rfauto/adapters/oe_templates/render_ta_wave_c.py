"""TA-11/14 三模板（ge8d Wave D 席 D2，2026-10-03）：嵌入式微带 embedded_ms +
交叉耦合开路环四重奏 BPF xcheb_bpf4（render_fns 分发路径；embedded_ms 走
mline/inverted_ms 同款均匀线结构，xcheb_bpf4 走 layout 单源字面注入）。

闭式/设计链内核（core 单源，本模块零几何数字副本 #116/#252）：
- embedded_ms → core/embedded_line.py（FD 裁判反演设计链；Wadell/Edwards&
  Steer 闭式系数不可达如实登记，见该模块 docstring）；
- xcheb_bpf4 → core/cross_coupled_map.py（cm_core 折叠矩阵——含**非相邻**
  交叉耦合条目——→ k_ij/Q_e/缝闭式映射 + 开路环布局定点；cm_core 纯消费
  禁改；χ 一阶部分长耦合近似如实入账）。

注册清单（同对象注册钉死单一事实源；render_fns 分发 + registry 轴/辐射器
面 + grid 近场线 + render_core z 网格/基板/布局注入 + 审计
EXPECTED_TEMPLATES/TEMPLATE_MESH_MM/DOMAIN_DRIVEN + docs meta.yaml + 锚）。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.synthesis import lossless_width_mm as _lossless_w  # XC-W 单源（尾部 import 移顶，ruff E402 收口）

from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

_MESH_FLOOR_M = 10e-6   # 显式近场线最小间距地板（#349，siw/hmsiw 同值）
_BOARD_M = 0.060        # 渲染 harness 固定板边（coupled_bpf 同值）


# ═══ TA-11 embedded_ms（嵌入式微带均匀段）════════════════════════════════════
# 结构：地面=z=0 域 PEC 底界；基板 z∈[0,H_SUB]；零厚条带 z=H_SUB（基板上
# 表面）；同 εr 覆盖层 z∈[H_SUB, H_SUB+H2]（嵌埋介质——单材料盒电气精确）；
# 其上开放（top MUR）。端口=双 MSLPort 板边入（inverted_ms/mline 口径）。
# 设计链=FD 反演（core/embedded_line）。

def _embedded_ms_lines(p: dict[str, Any]) -> str:
    # 嵌入式微带均匀段：一条直带埋于 z=H_SUB（基板顶=覆盖层底界面），两端
    # MSLPort（mline 手法，金属面 z=H_SUB；stop z=0=端口激励跨介质到地面）。
    # 参数：w_mm=条带宽（FD 反演 50Ω 名义 1.0014mm@h1=0.508/h2=0.254）、
    # h2_mm=覆盖层厚（嵌埋定义参数）、line_len_mm=两端口间线长。
    return f'''W = {p.get("w_mm", 1.0014)!r} * 1e-3
H2 = {p.get("h2_mm", 0.254)!r} * 1e-3   # 覆盖层厚（z 网格/基板盒字面同源）
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Z_STR = H_SUB                  # 条带 z=基板上表面=覆盖层下界面
Y0 = -L / 2
Y1 = L / 2
emb_ms = CSX.AddMetal("emb_ms")
emb_ms.AddBox((-W / 2, Y0, Z_STR), (W / 2, Y1, Z_STR), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=emb_ms,
                 start=np.array([W / 2, -BOARD, Z_STR]),
                 stop=np.array([-W / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=emb_ms,
                 start=np.array([-W / 2, BOARD, Z_STR]),
                 stop=np.array([W / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in emb_ms.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


EMB_MS_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（嵌入式微带均匀线：S21 相位斜率→εeff，"
                  "β 金标准 mline 同口径；|S11| 显著非零=端口/网格判废信号）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "h2_mm", "line_len_mm"],
    "topology": "嵌入式微带均匀段（TA-11）：地面=z=0 域 PEC 底界，基板 "
                "[0,H_SUB]，零厚条带 z=H_SUB，同 εr 覆盖层 [H_SUB, H_SUB+H2]"
                "（嵌埋介质单材料盒，均匀嵌埋电气精确），其上开放（top MUR）；"
                "双 MSLPort 板边入（端口面贴 PML）",
    "param_semantics": "w_mm=条带宽（设计链 core/embedded_line."
                       "embedded_ms_design_params：50Ω FD 裁判反演，名义 "
                       "1.0014mm@h1=H_SUB=0.508/h2=0.254/εr=3.66）、h2_mm="
                       "覆盖层厚（嵌埋定义参数，效应=介质填充率升→εeff 升至 "
                       "εr、同 w 阻抗降）、line_len_mm=两端口间线长；"
                       "h1/er/tan_d 走 substrate/nominal",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "条带缘 x 向 + 线两端 y 向精确入网（#198）；z 网格=基板 "
                 "_sub_cells 层+覆盖层 _sub_cells 层+AIR_TOP（条带 z 面恰在"
                 "网格线，#212 审计①）",
    "smoke_note": "离线审计先行（#212，test_ta_wave_c_templates）；内核数字"
                  "裁判=FD 四锚（h2→0 退化微带跨族互检/thick overlay εeff→εr/"
                  "εr=1 精确同解/括号单调，test_ta_wave_c_templates 钉）；"
                  "近似级别如实登记：准静态/零厚带/PEC 地/无色散，设计链=FD "
                  "裁判反演（Wadell 闭式系数不可达——core/embedded_line "
                  "docstring 如实账）；真机冒烟与 HFSS 仲裁属后续批次（本批"
                  "零发射）",
}

EMB_MS_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c，无手抄毫米数）：embedded_ms_design_params(50Ω,
    # h1=0.508, h2=0.254, er=3.66) FD 反演 → w=1.0014（回代 49.999Ω，
    # εeff=3.24008——覆盖层介质填充率高，εeff 显著高于同叠层敞开微带 2.85
    # 属嵌埋定义性质）；test_ta_wave_c_templates 单点 FD 带内钉。
    "w_mm": 1.0014, "h2_mm": 0.254, "line_len_mm": 40.0,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
}


# ═══ TA-14 xcheb_bpf4（交叉耦合开路环四重奏 BPF）════════════════════════════
# 结构：四个方形开路环谐振器（周长 λg/2，C 形三边半+开缝第四边）2×2 排布
# （环1 左上/环2 右上/环3 右下/环4 左下）；耦合：1-2 顶行水平缝（KJ 边耦
# 合）、2-3 右侧竖缝（主线）、3-4 底行水平缝（χ 错位修正）、4-1 左侧竖缝
# （**非相邻交叉耦合**——cm_core folded m14）；馈电=环 1/4 左侧边抽头
# （T 形 50Ω 馈线自 x=−BOARD 板边，hairpin 同款 A1 去嵌）。
# 开缝位（环 1 顶边 g_pos 自左上角/环 4 底边镜像/环 2 右边居中/环 3 底边
# 居中）与抽头位 t 由 Q_e 闭式链给（路径=开缝中点→角→抽头沿环）。

def _xcheb_bpf4_layout(p: dict[str, Any], base_m: float) -> dict[str, Any]:
    """xcheb_bpf4 几何统一计算（米）——render/_near_points/geometry_spec
    共用。base_m 用于 #266 耦合缝分辨守卫（NEAR=base/4 ≤ 缝_min/3，违反
    抛错拒绝渲染——守卫是正确行为，C3 族同口径）。"""
    wf = float(p.get("w_mm", _lossless_w(50.0, 2.5))) * 1e-3  # XC-W 单源（hairpin 无耗档 1.1117）
    a = float(p.get("a_mm", 8.7626)) * 1e-3
    g12 = float(p.get("g12_mm", 0.3581)) * 1e-3
    g23 = float(p.get("g23_mm", 0.4253)) * 1e-3
    g34 = float(p.get("g34_mm", 0.2885)) * 1e-3
    g14 = float(p.get("g14_mm", 1.6526)) * 1e-3
    g_open = float(p.get("g_open_mm", 0.3)) * 1e-3
    g_pos = float(p.get("g_pos_mm", 6.1338)) * 1e-3
    t_tap = float(p.get("tap_t_mm", 8.1454)) * 1e-3
    if min(wf, a, g12, g23, g34, g14, g_open, g_pos, t_tap) <= 0.0:
        raise ValueError("xcheb_bpf4 几何参数须 >0")
    if not g_open < g_pos < a:
        raise ValueError(
            f"xcheb_bpf4 开缝位 g_pos={g_pos * 1e3:.4g}mm 须在 "
            f"(g_open, a={a * 1e3:.4g})mm 内（开缝完整落在自由边段）")
    # #266 耦合缝分辨守卫：NEAR=base/4 ≤ 缝_min/3（渲染期抛错，C3 同口径；
    # 审计档 TEMPLATE_MESH_MM=0.35 → NEAR=0.0875 ≤ 0.2885/3=0.0962 过守卫）
    near = base_m / 4.0
    g_min = min(g12, g23, g34)
    if not near <= g_min / 3.0:
        raise ValueError(
            f"xcheb_bpf4: 网格欠分辨——NEAR={near * 1e3:.4g}mm > "
            f"缝_min/3={g_min / 3.0 * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}"
            "mm；收紧 mesh_resolution_mm，#266 C3 族同口径守卫）")

    h_r = (a + wf) / 2.0
    xc1 = xc4 = 0.0
    xc2 = 2.0 * h_r + g12
    xc3 = 2.0 * h_r + g34
    yc1 = yc2 = 0.0
    yc3 = -(2.0 * h_r + g23)
    yc4 = -(2.0 * h_r + g14)
    # x 居中（域 BOARD 方形板）
    x_lo = min(xc1, xc4) - h_r
    x_hi = max(xc2, xc3) + h_r
    shift = -(x_lo + x_hi) / 2.0
    if x_hi - x_lo > 2.0 * (_BOARD_M - 2e-3):
        raise ValueError("xcheb_bpf4 阵列超出 60mm 板（含 2mm 边距）")
    cen = [(xc1 + shift, yc1), (xc2 + shift, yc2),
           (xc3 + shift, yc3), (xc4 + shift, yc4)]
    y_tap1 = (yc1 + h_r) - t_tap      # 环 1 左边抽头（自顶角下行 t）
    y_tap4 = (yc4 - h_r) + t_tap      # 环 4 左边抽头（自底角上行 t，镜像）
    if not (yc1 - h_r) < y_tap1 < (yc1 + h_r - wf):
        raise ValueError("环 1 抽头位超出左边段（tap_t_mm 越界）")
    if not (yc4 - h_r + wf) < y_tap4 < (yc4 + h_r):
        raise ValueError("环 4 抽头位超出左边段（tap_t_mm 越界）")
    y_taps = [y_tap1, y_tap4]

    def ring(cx: float, cy: float, gap_side: str, gap_c_off: float,
             gap_centered: bool) -> list[tuple[float, float, float, float]]:
        """单环盒清单（外廓 ±h_r，线宽 wf；开缝所在边拆两段）。gap_side ∈
        top/bottom/right/left；gap_c_off=开缝中心自由边角起算偏置
        （centered=True 时居中）。角部重叠（水平边全宽/竖边全高）保证连通
        图物理化（#310 共边不连通教训——CSXCAD 同 priority 重叠=并集）。"""
        x0, x1 = cx - h_r, cx + h_r
        y0, y1 = cy - h_r, cy + h_r
        boxes = [
            (x0, y0, x0 + wf, y1),            # 左边（全高）
            (x1 - wf, y0, x1, y1),            # 右边（全高）
            (x0, y0, x1, y0 + wf),            # 底边（全宽）
            (x0, y1 - wf, x1, y1),            # 顶边（全宽，先整边）
        ]
        # 开缝：从对应边"挖"掉 [c−g/2, c+g/2]（拆分该边为两段；角部由相邻
        # 全长边覆盖，连通不受开缝影响）
        if gap_side == "top":
            c = y1 - wf / 2.0
            gx0 = (x0 + x1) / 2.0 - g_open / 2.0 if gap_centered else (
                x0 + gap_c_off - g_open / 2.0)
            boxes[3] = (x0, c, gx0, y1)
            boxes.append((gx0 + g_open, c, x1, y1))
        elif gap_side == "bottom":
            c = y0 + wf / 2.0
            gx0 = (x0 + x1) / 2.0 - g_open / 2.0 if gap_centered else (
                x0 + gap_c_off - g_open / 2.0)
            boxes[2] = (x0, y0, gx0, c)
            boxes.append((gx0 + g_open, c, x1, y0 + wf))
        elif gap_side == "right":
            c = (y0 + y1) / 2.0
            boxes[1] = (x1 - wf, y0, x1, c - g_open / 2.0)
            boxes.append((x1 - wf, c + g_open / 2.0, x1, y1))
        else:   # left
            c = (y0 + y1) / 2.0
            boxes[0] = (x0, y0, x0 + wf, c - g_open / 2.0)
            boxes.append((x0, c + g_open / 2.0, x0 + wf, y1))
        return boxes

    # 环 1：顶边开缝（g_pos 自左上角）；环 2：右边居中；环 3：底边居中；
    # 环 4：底边开缝（g_pos 自左下角，环 1 镜像）
    boxes: list[tuple[float, float, float, float]] = []
    boxes += ring(cen[0][0], cen[0][1], "top", g_pos, False)
    boxes += ring(cen[1][0], cen[1][1], "right", 0.0, True)
    boxes += ring(cen[2][0], cen[2][1], "bottom", 0.0, True)
    boxes += ring(cen[3][0], cen[3][1], "bottom", g_pos, False)
    feeds = [(-_BOARD_M, y_tap1 - wf / 2.0, cen[0][0] - h_r, y_tap1 + wf / 2.0),
             (-_BOARD_M, y_tap4 - wf / 2.0, cen[3][0] - h_r, y_tap4 + wf / 2.0)]
    # 缝中线（#311：耦合缝中点精确入网——四耦合缝各一）
    gap_mids = [
        ((cen[0][0] + h_r + cen[1][0] - h_r) / 2.0, None),     # 1-2 竖缝 x
        (None, (yc2 - h_r + yc3 + h_r) / 2.0),                 # 2-3 横缝 y
        ((cen[3][0] + h_r + cen[2][0] - h_r) / 2.0, None),     # 3-4 竖缝 x
        (None, (yc1 - h_r + yc4 + h_r) / 2.0),                 # 4-1 横缝 y
    ]
    return {"wf": wf, "a": a, "h_r": h_r, "cen": cen, "boxes": boxes,
            "feeds": feeds, "y_taps": y_taps, "gap_mids": gap_mids,
            "gaps_mm": [g12, g23, g34, g14], "g_open": g_open,
            "g_pos": g_pos, "t_tap": t_tap, "shift": shift,
            "board": _BOARD_M}


def _xcheb_bpf4_lines(p: dict[str, Any]) -> str:
    # 交叉耦合开路环四重奏 BPF：几何由 _xcheb_bpf4_layout 统一计算后以字面
    # 清单落脚本（layout 单一事实源）。必须经 render_script 渲染（布局注入）。
    lay = p.get("_xcheb_layout")
    if lay is None:
        raise ValueError(
            "xcheb_bpf4 几何段缺 _xcheb_layout：必须经 render_script 渲染"
            "（布局单源注入，hmsiw 同款纪律）")
    x_ring1 = lay["cen"][0][0] - lay["h_r"]
    x_ring4 = lay["cen"][3][0] - lay["h_r"]
    yt1 = lay["y_taps"][0]
    yt4 = lay["y_taps"][1]
    return f'''N_RING = 4
BOXES = {lay["boxes"]!r}                 # 环盒 [(x0,y0,x1,y1)]（m，layout 单源）
FEEDS = {lay["feeds"]!r}                 # 抽头馈线盒（x=−BOARD → 环 1/4 左边）
xcheb = CSX.AddMetal("xcheb_bpf4")
for _b in BOXES:
    xcheb.AddBox((_b[0], _b[1], H_SUB), (_b[2], _b[3], H_SUB), priority=10)
for _b in FEEDS:
    xcheb.AddBox((_b[0], _b[1], H_SUB), (_b[2], _b[3], H_SUB), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=xcheb,
                 start=np.array([-BOARD, {yt1 + lay["wf"] / 2.0!r}, H_SUB]),
                 stop=np.array([{x_ring1!r}, {yt1 - lay["wf"] / 2.0!r}, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=({x_ring1!r} + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=xcheb,
                 start=np.array([-BOARD, {yt4 + lay["wf"] / 2.0!r}, H_SUB]),
                 stop=np.array([{x_ring4!r}, {yt4 - lay["wf"] / 2.0!r}, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=({x_ring4!r} + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in xcheb.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


XCHEB_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（交叉耦合开路环 BPF：带内回波纹波+"
                  "带外抑制+**有限传输零点**（TZ，交叉耦合指纹）；裁判=C13 "
                  "耦合矩阵闭式 coupling_matrix_response（cm_core 折叠矩阵消"
                  "费），缝→k 纯 KJ+χ 一阶部分长标度",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "a_mm", "g12_mm", "g23_mm", "g34_mm", "g14_mm",
               "g_open_mm", "g_pos_mm", "tap_t_mm"],
    "topology": "交叉耦合开路环四重奏（TA-14）：四个 λg/2 方形开路环 2×2 排布"
                "（环1 左上/2 右上/3 右下/4 左下）；耦合=1-2 顶行水平缝 + "
                "2-3 右侧竖缝 + 3-4 底行水平缝 + **4-1 左侧竖缝（非相邻交叉"
                "耦合，cm_core folded m14 映射）**；馈电=环 1/4 左边抽头"
                "（50Ω 馈线自 x=−BOARD 板边，hairpin A1 去嵌口径）",
    "param_semantics": "w_mm=环线宽（50Ω HJ 单源）、a_mm=环边段长（周长="
                       "4a=λg/2−2Δl）、g12/g23/g34_mm=主线耦合缝（1-2/2-3/"
                       "3-4，KJ 反解 k/χ）、g14_mm=**交叉耦合缝**（4-1，非"
                       "相邻矩阵条目 m14 映射——本模板的存在理由）、g_open_"
                       "mm=环开缝宽（开路端）、g_pos_mm=环 1/4 开缝中心自"
                       "自由边角偏置（Q_e 路径的一部分）、tap_t_mm=抽头自角"
                       "距离（Q_e 闭式 τ·周长−g_pos）；er/tan_d 走 substrate/"
                       "nominal",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "#266 耦合缝守卫 NEAR≤缝_min/3（layout 抛错拒渲染）；全部"
                 "环边/开缝缘/馈线缘精确入网（#198）+四耦合缝中线入网"
                 "（#311）；审计档 TEMPLATE_MESH_MM=0.35（NEAR=0.0875 ≤ "
                 "0.2885/3 过守卫）",
    "smoke_note": "离线审计先行（#212，test_ta_wave_c_templates）；内核数字"
                  "裁判三锚（test_cross_coupled_map）：①全极点退化对 classical "
                  "g 值闭式（独立综合路径，max rel dev 1.2e-5）②KJ 往返+矩阵"
                  "频响一致性（max|ΔS|≤1e-6 实测 7.5e-7）③TZ=[±2.0] 传输零点"
                  "保持（−88dB 谷映射前后一致）；χ 一阶部分长耦合与环角/开缝"
                  "结构效应未经 EM 校准（hairpin c(gap) 同族待标定项，#122 "
                  "如实登记）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）",
}

XCHEB_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c）：cross_coupled_ring_quad_design(f0=2.5, fbw=0.05,
    # rl=20, TZ=[2.0]) 定点收敛 → 见各值；test_ta_wave_c_templates 按链复算
    # 逐键钉（闭式链 ~1s 在门预算内，#252 口径）。
    "w_mm": 1.1117, "a_mm": 8.7626,
    "g12_mm": 0.3581, "g23_mm": 0.4253, "g34_mm": 0.2885, "g14_mm": 1.6526,
    "g_open_mm": 0.3, "g_pos_mm": 6.1338, "tap_t_mm": 8.1454,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
}


# ═══ 注册（同对象注册钉死单一事实源；追加在 vivaldi_tsa 之后——#247 尾部
# 追加契约：槽线族保持字典尾）══════════════════════════════════════════════
TEMPLATE_META["embedded_ms"] = EMB_MS_META
TEMPLATE_NOMINAL["embedded_ms"] = EMB_MS_NOMINAL
TEMPLATE_META["xcheb_bpf4"] = XCHEB_META
TEMPLATE_NOMINAL["xcheb_bpf4"] = XCHEB_NOMINAL


def embedded_ms_meta() -> dict[str, Any]:
    """返回 embedded_ms 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(EMB_MS_META)
    meta["template"] = "embedded_ms"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(EMB_MS_NOMINAL)
    return meta


def xcheb_bpf4_meta() -> dict[str, Any]:
    """返回 xcheb_bpf4 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(XCHEB_META)
    meta["template"] = "xcheb_bpf4"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(XCHEB_NOMINAL)
    return meta
