"""mmwave_series_array 毫米波串联阵列族（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .closedform import (
    _ARR_C_MM_GHZ,
    _ARR_EDGE_MARGIN_MM,
    _ant2_eps_eff,
    array_elem_len_mm,
    array_elem_w_mm,
    array_line_w_mm,
)
from .registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)

# ═══════════════════════════════════════════════════════════════════════════════
# §MMWAVE_SERIES_ARRAY 串馈毫米波阵（2026-09-26 df7 C10d，文末注册块，coil_nfc
# 同款口径）═════════════════════════════════════════════════════════════════════
# 汽车雷达 76-81GHz 行波串馈贴片阵：微带串馈线 + N×λ/2 贴片（边接互联）+
# 链末匹配集总负载到地（行波阵；openEMS 惯例=shunt LumpedElement R=Z0 到
# z-min PEC 地，atten_pi shunt 同款渲染机制）。与 C2 patch_array_series 的
# 差异（§10.3 C2=λg/2 谐振式驻波阵、链末开路、同相侧射）：本族互联长 s 为
# 自由设计参数——行波渐进相位 Δφ = π + βg·s 逐元递推（π=λ/2 贴片两辐射边场
# 反相，C2 相位账同源）→ 波束倾斜 u0 = (Δφ−2πm)/(k0·d) 可设计（core/
# array_synthesis.series_feed_* 闭式，2026-09-26 C10d 加法式扩展）。
# 名义尺寸全闭式精算（#1c/#252，导入期 mmwave_series_design_params() 非手抄）：
# 单元 W/L=Balanis Ch.14（array_elem_w_mm/len_mm 复用，er/h 参数化）、
# 线宽=skrf HJ inverse_width 50Ω、βg=k0·√εeff(HJ @feed_w)、s=倾斜式反解。
# 基板 RO3003 类（er=3.0/h=0.127/tan_d=0.001，模板参数基板——ms 族「er/tan_d
# 走 substrate/nominal」同口径；0.508 缺省板在 78GHz 非物理厚）。
# 真机面：预算预声明 runs/df7_c10d/criteria.md §d（~3.6e7 cells/dt~4.8e-14s/
# NrTS~2.5e4/墙钟数小时～半天每点），本批零发射。
MMWAVE_SERIES_TEMPLATES: frozenset[str] = frozenset({"mmwave_series_array"})
_MMWAVE_DOM_MM = 20.0            # 方域半宽（40×40mm 板，criteria §d 域）
_MMWAVE_AIR_TOP_MM = 1.0         # 空气隙（≈λ0/4 @78GHz + MUR 余量）
_MMWAVE_TAN_D = 0.001            # RO3003 类损耗（设计点典型值）
_MMWAVE_FEED_MARGIN_MM = 3.0     # 板边到链首元馈段长（#347 守卫下限核算见下）
_MMWAVE_LOAD_R_OHM = 50.0        # 端接=线 Z0（一阶未载入口径，如实不进锚）


def mmwave_series_design_params(
    f0_ghz: float = 78.0,
    tilt_u0: float = 0.30,
    n_elem: int = 4,
    er: float = 3.0,
    h_mm: float = 0.127,
    tan_d: float = _MMWAVE_TAN_D,
    feed_margin_mm: float = _MMWAVE_FEED_MARGIN_MM,
    load_r_ohm: float = _MMWAVE_LOAD_R_OHM,
) -> dict[str, Any]:
    """C10d 串馈毫米波阵全参数设计链（4 位舍入；MMWAVE_SERIES_NOMINAL=
    本函数缺省调用，单测互检 #252）。

    闭合链：W/L（Balanis Ch.14，array_elem_w_mm/len_mm）→ feed_w（skrf HJ
    50Ω，先舍入再算 εeff——C2 同口径）→ βg=k0√εeff → 互联长 s 由倾斜设计式
    反解：u0 = (π + βg·s − 2π)/(k0·(L+s))  ⇒  s = (u0·k0·L + π)/(βg − u0·k0)
    （主分支 m=1，s∈(0, λg) 域）。设计守卫：u0 落可见区（闭式内部）、
    栅瓣判据 d/λ0 < 1/(1+u0)（Balanis Ch.6；越界显式 ValueError——
    名义 u0=0.30 时 d/λ0=0.696 < 0.769 余量 0.073λ0，u0≳0.37 即入栅瓣域）。
    """
    f0 = float(f0_ghz)
    u0_target = float(tilt_u0)
    n = int(n_elem)
    if not (f0 > 0.0 and 0.0 < u0_target < 1.0):
        raise ValueError("f0 须正且 tilt_u0 须落在 (0, 1)")
    if n < 2:
        raise ValueError(f"n_elem 须 ≥2（串馈阵定义），收到 {n_elem!r}")
    if not (float(er) > 1.0 and float(h_mm) > 0.0):
        raise ValueError("er 须 >1 且 h_mm 须正")
    w_raw = array_elem_w_mm(f0, er)
    l_raw = array_elem_len_mm(f0, w_raw, er, h_mm)
    fw = round(array_line_w_mm(50.0, f0, er, h_mm), 4)
    lam0 = _ARR_C_MM_GHZ / f0
    k0 = 2.0 * math.pi / lam0
    beta_g = k0 * math.sqrt(_ant2_eps_eff(fw, f0, er, h_mm))
    s_raw = (u0_target * k0 * l_raw + math.pi) / (beta_g - u0_target * k0)
    if not (0.0 < s_raw < lam0):
        raise ValueError(
            f"串馈倾斜设计式 s={s_raw:.6g}mm 落 (0, λg) 域外（u0={u0_target}）")
    # 设计式公式自检在舍入前（未舍入闭合往返 ≤1e-9）；舍入后重建偏差由
    # 4 位舍入主导（≤~4e-5，不作为公式错判据）
    u0_raw = (math.pi + beta_g * s_raw - 2.0 * math.pi) / (k0 * (l_raw + s_raw))
    if abs(u0_raw - u0_target) > 1e-9:
        raise ValueError(
            f"倾斜设计式往返失配：u0 重建 {u0_raw:.9g} != 目标 {u0_target}")
    s = round(s_raw, 4)
    length = round(l_raw, 4)
    pitch = length + s
    u0_recon = (math.pi + beta_g * s - 2.0 * math.pi) / (k0 * pitch)
    from rfauto.core.array_synthesis import has_grating_lobe

    if has_grating_lobe(pitch / lam0, u0_recon):
        raise ValueError(
            f"串馈设计点入栅瓣域：d/λ0={pitch / lam0:.4g} ≥ 1/(1+u0)="
            f"{1.0 / (1.0 + u0_recon):.4g}（u0={u0_recon:.4g}）——调小 tilt_u0")
    params: dict[str, Any] = {
        "n_elem": n,
        "elem_len_mm": length,
        "elem_w_mm": round(w_raw, 4),
        "link_len_mm": s,
        "feed_w_mm": fw,
        "feed_margin_mm": round(float(feed_margin_mm), 4),
        "load_r_ohm": round(float(load_r_ohm), 4),
        "h_mm": round(float(h_mm), 4),
        "er": round(float(er), 4),
        "tan_d": round(float(tan_d), 4),
    }
    return params


# 名义设计点 @78GHz/u0=0.30/N=4（导入期闭式合成，非手抄 #252）
MMWAVE_SERIES_NOMINAL: dict[str, Any] = mmwave_series_design_params()

MMWAVE_SERIES_META: dict[str, Any] = {
    "f0_ghz": 78.0, "n_ports": 1,
    "extraction": "S11 @ MSLPort 1（1×4 行波串馈贴片阵，链末 50Ω 集总匹配到"
                  "地：谷位=单元谐振设计式精确逆 patch_resonance_hj_ghz；方向"
                  "图走 far_field=True nf2ff，离线裁判=相位递推闭式主瓣指向 "
                  "core/array_synthesis.series_feed_beam_direction_cosine；"
                  "未真机冒烟）",
    "max_time_ns": 60.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["n_elem", "elem_len_mm", "elem_w_mm", "link_len_mm",
               "feed_w_mm", "feed_margin_mm", "h_mm"],
    "topology": "1×N 串馈毫米波阵（§18.3d C10d）：N 元共线沿 y（x=0 居中，"
                "L 沿 y/W 沿 x），相邻元以互联线接辐射边中心（互联长 s=自由"
                "设计参数，行波渐进相位 βg·s）；MSLPort 自 y=−DOM 入、自画馈"
                "段至链首元（feed_margin）；链末 stub+匹配集总负载到地（R="
                "线 Z0 一阶）——行波阵口径，与 C2 patch_array_series（λg/2 "
                "谐振式、链末开路）分族；基板 + z-min PEC 地，y 轴 PML_8",
    "param_semantics": "n_elem=单元数（≥2），elem_len_mm=单元谐振长 L（沿 y；"
                       "Balanis Ch.14 c/(2f0√εeff)−2ΔL，fake 谷位为其精确"
                       "逆），elem_w_mm=单元宽 W（c/(2f0)√(2/(εr+1))），"
                       "link_len_mm=互联线长 s（行波渐进相位自由度：u0=(π+"
                       "βg·s−2π)/(k0·d)，d=L+s；s=λg/2 退化为 C2 同相侧"
                       "射），feed_w_mm=50Ω 馈线/互联宽（HJ 0.3259mm @78GHz），"
                       "feed_margin_mm=板边到链首元馈段长（MSLPort 自画，"
                       "MeasPlaneShift=margin/3），h_mm=基板厚（毫米波板 "
                       "0.127）；er/tan_d 走 substrate/nominal（RO3003 类）",
    "mesh_note": "辐射器件：上方空气隙 λ0/4+、侧向至域界（MUR）；贴片/互联/"
                 "stub/负载盒缘精确入网（#198）；渲染守卫：NEAR≤feed_w/3"
                 "（#266 族，线宽分辨）、|MeasPlaneShift−FeedShift|≥3.9·NEAR"
                 "（#347）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边"
                 "（#154 前节）",
    "smoke_note": "未冒烟（离线审计过，#212，test_mmwave_series_array_"
                  "template）；真机发射面=预算预声明 runs/df7_c10d/criteria."
                  "md §d（0.1mm 格 ~3.6e7 cells、dt~4.8e-14s、NrTS~2.5e4、"
                  "墙钟数小时～半天/点，发射前以 exec 实测为准），本批零发射",
}

# ── 注册：同对象入 TEMPLATE_META/TEMPLATE_NOMINAL（单一事实源；尾部追加 #247）──
TEMPLATE_META["mmwave_series_array"] = MMWAVE_SERIES_META
TEMPLATE_NOMINAL["mmwave_series_array"] = MMWAVE_SERIES_NOMINAL
_TEMPLATE_PORT_AXES["mmwave_series_array"] = ("y",)
_TEMPLATE_RADIATOR["mmwave_series_array"] = True


def mmwave_series_meta(template: str) -> dict[str, Any]:
    """返回 C10d 串馈毫米波阵元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in MMWAVE_SERIES_TEMPLATES:
        raise KeyError(f"非串馈毫米波阵模板: {template}")
    meta = dict(MMWAVE_SERIES_META)
    meta["template"] = template
    meta["substrate"] = {
        "er": MMWAVE_SERIES_NOMINAL["er"],
        "h_mm": MMWAVE_SERIES_NOMINAL["h_mm"],
        "tan_d": MMWAVE_SERIES_NOMINAL["tan_d"],
    }
    meta["nominal_params"] = dict(MMWAVE_SERIES_NOMINAL)
    return meta


def _mmwave_series_layout(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """C10d 串馈毫米波阵单一事实源（mm）：金属盒 / 端口 / 单元中心 / 特征线。

    渲染段（mmwave_series_render）、UI 预览（mmwave_series_geometry_spec）、
    离线审计（#212 exec 截断）与本模板单测四方消费——单源防漂移（_arr_layout
    同制度）。金属盒元组 = (属性名, 盒名, x0, y0, z0, x1, y1, z1)，零厚顶面
    z=h（官方金属面口径）；端接集总负载单列（LumpedElement 盒 z=0..h）。
    相位/波束闭式自洽：layout 内调 core/array_synthesis.
    series_feed_beam_direction_cosine 守卫（主波束落可见区外显式 ValueError）。
    """
    if "mmwave_series_array" not in MMWAVE_SERIES_TEMPLATES:  # pragma: no cover
        raise ValueError("注册表漂移")
    nom = MMWAVE_SERIES_NOMINAL

    def g(key: str) -> Any:
        return params.get(key, nom[key])

    n = int(float(g("n_elem")))
    if n < 2:
        raise ValueError(f"mmwave_series_array: n_elem 须 ≥2，收到 {n}")
    length = float(g("elem_len_mm"))
    width = float(g("elem_w_mm"))
    s = float(g("link_len_mm"))
    fw = float(g("feed_w_mm"))
    margin = float(g("feed_margin_mm"))
    load_r = float(g("load_r_ohm"))
    h = float(g("h_mm"))
    er = float(g("er"))
    for label, v in (("elem_len_mm", length), ("elem_w_mm", width),
                     ("link_len_mm", s), ("feed_w_mm", fw),
                     ("feed_margin_mm", margin), ("load_r_ohm", load_r),
                     ("h_mm", h)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"mmwave_series_array: {label} 必须为正有限，得到 {v!r}")
    if fw >= width:
        raise ValueError(f"mmwave_series_array: 馈线宽 {fw} 须小于单元宽 {width}")
    dom = _MMWAVE_DOM_MM
    f0 = (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) / 2.0
    lam0 = _ARR_C_MM_GHZ / f0
    k0 = 2.0 * math.pi / lam0
    beta_g = k0 * math.sqrt(_ant2_eps_eff(fw, f0, er, h))
    pitch = length + s
    from rfauto.core.array_synthesis import series_feed_beam_direction_cosine

    u0_pred = series_feed_beam_direction_cosine(pitch, k0, s, beta_g)
    # 网格：显式覆盖优先；自动档=线宽驱动（毫米波几何驱动，meta mesh_note）
    base = (fw / 4.0 if not mesh_resolution_mm
            else float(mesh_resolution_mm))
    near = base / 4.0
    if near > fw / 3.0:
        raise ValueError(
            f"mmwave_series_array: NEAR={near:.4g}mm > feed_w/3={fw / 3.0:.4g}mm"
            "（#266 族线宽分辨守卫，收紧 mesh_resolution_mm）")
    feed_shift = 10.0 * near
    meas_shift = margin / 3.0
    if abs(meas_shift - feed_shift) < 3.9 * near:
        raise ValueError(
            f"mmwave_series_array: |MeasPlaneShift({meas_shift:.4g})−FeedShift"
            f"({feed_shift:.4g})| < 3.9·NEAR={3.9 * near:.4g}mm（#347 探针入"
            "激励盒近场守卫，加大 feed_margin_mm）")
    # 链几何（mm）
    load_seg = 2.0 * fw                 # 端接 stub 长（负载盒占后半段）
    y_start = -dom + margin             # 链首元 −y 边
    chain_top = y_start + n * length + (n - 1) * s
    y_end = chain_top + load_seg
    if y_end > dom - _ARR_EDGE_MARGIN_MM:
        raise ValueError(
            f"mmwave_series_array: 链顶+端接 {y_end:.3f}mm 超域（≤{dom - _ARR_EDGE_MARGIN_MM:.3f}mm；"
            f"{n}·L + {n - 1}·s + margin + 端接）")
    prop_line = "mmwave_series_array_line"
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    elements: list[tuple[float, float]] = []
    x_lines: list[float] = [-width / 2, width / 2, -fw / 2, fw / 2, 0.0]
    y_lines: list[float] = [-dom, -dom + margin, y_start, y_end]
    y = y_start
    for k in range(n):
        boxes.append((prop_line, f"e{k}", -width / 2, y, h, width / 2, y + length, h))
        elements.append((0.0, y + length / 2))
        y_lines += [y, y + length]
        if k < n - 1:
            boxes.append((prop_line, f"link{k}", -fw / 2, y + length, h,
                          fw / 2, y + length + s, h))
            y_lines.append(y + length + s)
        y += length + s
    boxes.append((prop_line, "load_stub", -fw / 2, chain_top, h,
                  fw / 2, y_end, h))
    # 行波端接：匹配集总负载到地（shunt ny=z；atten_pi shunt 同款机制）
    load_box = (-fw / 2, chain_top + fw, 0.0, fw / 2, y_end, h)
    y_lines += [chain_top + fw]
    port = {"kind": "msl", "nr": 1, "metal_prop": prop_line,
            "start_mm": (fw / 2, -dom, h),
            "stop_mm": (-fw / 2, -dom + margin, 0.0),
            "prop_dir": "y", "exc_dir": "z", "excite": 1,
            "meas_shift_mm": meas_shift}
    return {
        "n": n, "f0_ghz": f0, "lam0_mm": lam0, "k0_rad_mm": k0,
        "beta_g_rad_mm": beta_g, "u0_pred": u0_pred,
        "pitch_mm": pitch, "elem_len_mm": length, "elem_w_mm": width,
        "link_len_mm": s, "dom_mm": dom, "h_mm": h, "er": er,
        "base_mm": base, "near_mm": near,
        "feed_shift_mm": feed_shift, "meas_shift_mm": meas_shift,
        "boxes": boxes, "load_box": load_box, "load_r_ohm": load_r,
        "port": port, "elements_mm": elements,
        "x_lines_mm": x_lines, "y_lines_mm": y_lines,
        "air_top_mm": _MMWAVE_AIR_TOP_MM,
    }


def mmwave_series_geometry_spec(
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """mmwave_series_array UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    lay = _mmwave_series_layout(params, (MMWAVE_SERIES_META["f0_ghz"],
                                         MMWAVE_SERIES_META["f0_ghz"]))
    xs = [b[2] for b in lay["boxes"]] + [b[5] for b in lay["boxes"]]
    ys = [b[3] for b in lay["boxes"]] + [b[6] for b in lay["boxes"]]
    dom = lay["dom_mm"]
    h = lay["h_mm"]
    boxes = [
        {"name": "substrate", "material": "substrate",
         "start_mm": [-dom, -dom, 0.0], "stop_mm": [dom, dom, h]},
        {"name": "series_chain（串馈链+端接 stub）", "material": "metal",
         "start_mm": [min(xs), min(ys), h], "stop_mm": [max(xs), max(ys), h]},
    ]
    ports = [{"name": "Port1（MSLPort，行波串馈馈入）",
              "pos_mm": [0.0, -dom, h], "dir": [0.0, -1.0, 0.0]}]
    sub_view = {"er": lay["er"], "h_mm": h,
                "tan_d": float(params.get("tan_d",
                                          MMWAVE_SERIES_NOMINAL["tan_d"]))}
    return {"template": "mmwave_series_array", "substrate": sub_view,
            "boxes": boxes, "ports": ports,
            "elements": [{"name": "load_termination", "kind": "lumped_r",
                          "r_ohm": lay["load_r_ohm"], "ny": "z",
                          "span_mm": [lay["load_box"][1], lay["load_box"][4]],
                          "y_mm": lay["load_box"][4]}]}


def mmwave_series_render(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    far_field: bool = False,
) -> str:
    """mmwave_series_array 整脚本渲染器（早分发自 render_script；coil_nfc
    同款结构）。

    单端口（MSLPort 自 PML_8 域边入）+ 链末匹配集总负载到地：S11=单元谐振
    谷口径（行波阵的带内吸收谷，fake 同源精确逆判读）；y=PML_8 端口轴、
    x=MUR、z0=PEC 地、z1=MUR。er/tan_d/h 从 params/NOMINAL 消费（模板自带
    RO3003 类板材；render_script 顶层会把缺省 substrate 重绑为 RO4350B——
    本族不用全局缺省板材）。_nrts 旋钮缺省逐字节不变；far_field=True 注入
    官方 nf2ff 盒（z 底=PEC 接地分支，CreateNF2FFBox 自动镜像口径）。
    """
    del substrate, template   # 板材/域全由 params/NOMINAL 单源（段头注释）
    lay = _mmwave_series_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = (freq_range_ghz[0] + freq_range_ghz[1]) / 2 * 1e9
    fc = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2 * 1e9
    er = float(params.get("er", MMWAVE_SERIES_NOMINAL["er"]))
    tan_d = float(params.get("tan_d", MMWAVE_SERIES_NOMINAL["tan_d"]))
    nrts = int(params.get("_nrts", 60000) or 60000)
    h = lay["h_mm"] * 1e-3
    dom = lay["dom_mm"] * 1e-3
    air_top = lay["air_top_mm"] * 1e-3
    base = lay["base_mm"] * 1e-3
    near = lay["near_mm"] * 1e-3
    load_r = lay["load_r_ohm"]

    def m(v: float) -> float:
        return float(v) * 1e-3

    box_lit = "\n".join(
        f'line.AddBox(({m(b[2])!r}, {m(b[3])!r}, {m(b[4])!r}), '
        f'({m(b[5])!r}, {m(b[6])!r}, {m(b[7])!r}), priority=10)  # {b[1]}'
        for b in lay["boxes"])
    lb = lay["load_box"]
    load_lit = (f'load.AddBox(({m(lb[0])!r}, {m(lb[1])!r}, {m(lb[2])!r}), '
                f'({m(lb[3])!r}, {m(lb[4])!r}, {m(lb[5])!r}), priority=10)')
    x_lit = ", ".join(repr(m(v)) for v in sorted(set(lay["x_lines_mm"])))
    y_lit = ", ".join(repr(m(v)) for v in sorted(set(lay["y_lines_mm"])))
    p = lay["port"]
    ff_setup = ""
    ff_calc = ""
    if far_field:
        ff_setup = (
            "\n# ── nf2ff 盒（官方 Simple Patch Antenna：域缩 4×网格；"
            "z 底=PEC 边界自动镜像）──\n"
            "_FF_MARGIN = 4 * BASE\n"
            "_FF_START = np.array([-DOM_X + _FF_MARGIN, -DOM_Y + _FF_MARGIN, 0.0])\n"
            "_FF_STOP = np.array([DOM_X - _FF_MARGIN, DOM_Y - _FF_MARGIN,\n"
            "                     H_SUB + AIR_TOP - _FF_MARGIN])\n"
            "_FF = FDTD.CreateNF2FFBox('nf2ff', _FF_START, _FF_STOP)\n")
        ff_calc = (
            "\n# ── nf2ff 远场（f_res=|S11| 谷；Dmax/η best-effort #105；"
            "η 注意 PEC 镜像 Prad 双计口径 #249，主判=主瓣指向 vs 相位递推"
            "闭式）──\n"
            "try:\n"
            "    _f_res_i = int(np.argmin(np.abs(S11)))\n"
            "    _f_res = float(f[_f_res_i])\n"
            "    _THETA_CUT = np.arange(-180.0, 181.0, 1.0)\n"
            "    _PHI_CUT = [0.0, 90.0]\n"
            "    _ffr = _FF.CalcNF2FF(SIM_PATH, _f_res, _THETA_CUT, _PHI_CUT)\n"
            "    _db = np.asarray(_ffr.E_norm[0], dtype=float)\n"
            "    _db = 20 * np.log10(_db / max(_db.max(), 1e-300) + 1e-300)\n"
            "    _peak = int(np.argmax(_db[:, 1]))\n"
            "    _meta = dict(ok=True, f_res_hz=_f_res,\n"
            "                 peak_theta_deg=float(_THETA_CUT[_peak]),\n"
            "                 phi_cut_deg=_PHI_CUT,\n"
            "                 note='PEC 镜像 Prad 双计口径 #249；主判=指向')\n"
            "    with open(os.path.join(SCRIPT_DIR, 'farfield_meta.json'),\n"
            "              'w', encoding='utf-8') as _mh:\n"
            "        json.dump(_meta, _mh, ensure_ascii=False, indent=1)\n"
            "except Exception as _ffe:\n"
            "    print('rfauto nf2ff 链失败（不阻塞 S 参数）:', _ffe)\n")
    return f'''#!/usr/bin/env python3
"""openEMS mmwave_series_array script (rfauto df7 C10d auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/openems_templates.py 文末
MMWAVE_SERIES_ARRAY 段。行波串馈（βg·s 渐进相位递推，波束倾斜 u0=
{lay["u0_pred"]:.4f} 闭式 core/array_synthesis）+ 链末匹配集总负载到地；
真机预算预声明 runs/df7_c10d/criteria.md §d（本批零发射）。
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
from openEMS.ports import MSLPort

F0 = {f0!r}
FC = {fc!r}
ER = {er!r}
TAND = {tan_d!r}
H_SUB = {h!r}
AIR_TOP = {air_top!r}   # 空气隙（≈λ0/4 @78GHz + MUR 余量）
BASE = {base!r}   # 网格 base：自动档 feed_w/4（毫米波几何驱动）
NEAR = {near!r}   # 近特征区 = base/4
DOM_X = {dom!r}
DOM_Y = {dom!r}
LOAD_R = {load_r!r}   # 行波端接=线 Z0（一阶未载入口径）
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)   # 官方口径：不设 EndCriteria，能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 行波串馈链（辐射口径）：y=PML_8 端口轴（#154 前节）、x=MUR、z0=PEC 地
FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"])

mesh = CSX.GetGrid()
# 链/端口/负载全部特征线精确入网（#198）：特征区 NEAR 细分→域界补入→
# 空气区 BASE 粗化（细格只在特征走廊，空气区 λ0/BASE≈38 格够；dt 由最小
# 格 NEAR 定，双档平滑不放宽 CFL——预算随最小格走，criteria §d）
for _x in np.array([{x_lit}]):
    mesh.AddLine("x", _x)
for _y in np.array([{y_lit}]):
    mesh.AddLine("y", _y)
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.AddLine("x", np.array([-DOM_X, DOM_X]))
mesh.AddLine("y", np.array([-DOM_Y, DOM_Y]))
mesh.SmoothMeshLines("x", BASE)
mesh.SmoothMeshLines("y", BASE)
mesh.AddLine("z", np.linspace(0, H_SUB, 5))
mesh.AddLine("z", np.array([H_SUB + AIR_TOP]))
mesh.SmoothMeshLines("z", BASE)
# 近重合网格线守卫（#152）：平滑后按最小间距 1µm 去重
for _ax in ("x", "y", "z"):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _keep = [_ls[0]]
    for _v in _ls[1:]:
        if _v - _keep[-1] > 1e-6:
            _keep.append(_v)
    mesh.SetLines(_ax, np.array(_keep))

# ── 几何：RO3003 类基板 + 串馈链（贴片×{lay["n"]} + 互联 + 端接 stub）──
sub = CSX.AddMaterial("substrate", epsilon=ER,
                      kappa=TAND * 2 * np.pi * F0 * 8.854187817e-12 * ER)
sub.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, H_SUB), priority=0)
line = CSX.AddMetal("line")
{box_lit}
# 行波端接：链末匹配集总负载到地（shunt ny=z，R=线 Z0 一阶口径）
load = CSX.AddLumpedElement("load", ny=2, caps=True, R=LOAD_R)
{load_lit}

# ── 端口：MSLPort 自 y=−DOM 域边（PML_8 面）入，自画馈段至链首元 ──
_port1 = MSLPort(CSX, port_nr=1, metal_prop=line,
                 start=np.array([{m(p["start_mm"][0])!r}, {m(p["start_mm"][1])!r}, {m(p["start_mm"][2])!r}]),
                 stop=np.array([{m(p["stop_mm"][0])!r}, {m(p["stop_mm"][1])!r}, {m(p["stop_mm"][2])!r}]),
                 prop_dir="y", exc_dir="z", excite=1,
                 FeedShift=10 * NEAR, MeasPlaneShift={m(p["meas_shift_mm"])!r},
                 priority=10)
{ff_setup}
# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：单端口 S11（单元谐振吸收谷=f0 判读位；R=50Ω 同参考）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port1.uf_ref / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag])
{ff_calc}summary = dict(
    ok=True, template="mmwave_series_array", f0_hz=F0, fc_hz=FC,
    n_elem={lay["n"]}, u0_pred={lay["u0_pred"]!r},
    pitch_mm={lay["pitch_mm"]!r}, beta_g_rad_mm={lay["beta_g_rad_mm"]!r},
    elem_len_mm={lay["elem_len_mm"]!r}, link_len_mm={lay["link_len_mm"]!r},
    load_r_ohm=LOAD_R, nrts=NRTS,
    mesh_lines=[int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
)
with open(os.path.join(SCRIPT_DIR, "mmwave_series_array_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto mmwave_series_array simulation done")
'''
