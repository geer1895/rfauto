"""阵列族（patch_array_1x4/2x2/series + patch_eep_2x2/1x4）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

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
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

ARRAY_TEMPLATES: tuple[str, ...] = (
    "patch_array_1x4", "patch_array_2x2", "patch_array_series")
_ARR_SPACING_FRAC = 0.484        # 单元间距 / λ0（略缩 λ0/2，见段首约束）
_ARR_INSET_FRAC = 0.3            # 插入深度 / L（synthesize_patch 同口径）
_ARR_NOTCH_CLEAR_MM = 0.5        # 缺口两侧净空（缺口宽 = 馈线宽 + 2×净空）
_ARR_ROW_Y_MM = 20.0             # 1×4 行中心 / 2×2 栅格中心 y
_ARR_TREE_Y_MM = {"patch_array_1x4": -4.0, "patch_array_2x2": -13.0}   # J 线 y0
_ARR_TRUNK_MM = 8.0              # 主干长（J0 → 探针中心）
_ARR_PROBE_HALF_X_MM = 0.1       # 底探针盒 x 半宽（patch 官方 0.2mm 盒）
_ARR_PROBE_HALF_Y_MM = 1.0       # 底探针盒 y 半宽（patch 官方 2mm 盒）
_ARR_CORRIDOR_CLEAR_MM = 2.0     # 2×2 顶排走廊距元列外缘净空
_ARR_SERIES_N = 3
_ARR_SERIES_FEED_MARGIN_MM = 8.0
_ARR_BOARD_MM = 60.0             # 与 render_script BOARD=60e-3 同值（mm）


def array_quarter_len_mm(w_mm: float, f0_ghz: float, er: float = 3.66,
                         h_mm: float = 0.508) -> float:
    """λ/4 变换段长 = c/(4f0√εeff(w))（HJ εeff @线宽）。"""
    eps = _ant2_eps_eff(float(w_mm), float(f0_ghz), float(er), float(h_mm))
    return _ARR_C_MM_GHZ / (4.0 * float(f0_ghz) * math.sqrt(eps))


def array_half_guided_len_mm(w_mm: float, f0_ghz: float, er: float = 3.66,
                             h_mm: float = 0.508) -> float:
    """串馈互联 λg/2 = c/(2f0√εeff(w))（HJ εeff @线宽）。"""
    return 2.0 * array_quarter_len_mm(w_mm, f0_ghz, er, h_mm)


def array_design_params(template: str, f0_ghz: float = 5.8, er: float = 3.66,
                        h_mm: float = 0.508) -> dict[str, Any]:
    """C2 三模板全参数设计链（4 位舍入；ARRAY_NOMINAL = 本函数 @5.8GHz，单测互检）。

    线宽先舍入再算 εeff（λ/4、λg/2 以渲染实际线宽为准，与标称常数逐位一致）。
    """
    if template not in ARRAY_TEMPLATES:
        raise KeyError(f"非 C2 阵列模板: {template}（可用 {ARRAY_TEMPLATES}）")
    f0 = float(f0_ghz)
    w_raw = array_elem_w_mm(f0, er)
    l_raw = array_elem_len_mm(f0, w_raw, er, h_mm)
    feed_w = round(array_line_w_mm(50.0, f0, er, h_mm), 4)
    params: dict[str, Any] = {
        "elem_len_mm": round(l_raw, 4),
        "elem_w_mm": round(w_raw, 4),
    }
    if template == "patch_array_series":
        params["feed_w_mm"] = feed_w
        params["link_len_mm"] = round(array_half_guided_len_mm(feed_w, f0, er, h_mm), 4)
        params["feed_margin_mm"] = _ARR_SERIES_FEED_MARGIN_MM
        return params
    spacing = round(_ARR_SPACING_FRAC * _ARR_C_MM_GHZ / f0, 4)
    q_w = round(array_line_w_mm(50.0 * math.sqrt(2.0), f0, er, h_mm), 4)
    params["elem_feed_mm"] = round(_ARR_INSET_FRAC * l_raw, 4)
    if template == "patch_array_1x4":
        params["spacing_mm"] = spacing
    else:
        params["spacing_x_mm"] = spacing
        params["spacing_y_mm"] = spacing
    params["feed_w_mm"] = feed_w
    params["q_w_mm"] = q_w
    params["q_len_mm"] = round(array_quarter_len_mm(q_w, f0, er, h_mm), 4)
    return params


# 各模板标称设计点 @5.8GHz（= array_design_params 4 位舍入，单测互检）
ARRAY_NOMINAL: dict[str, dict[str, Any]] = {
    "patch_array_1x4": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_mm": 25.0172, "feed_w_mm": 1.112, "q_w_mm": 0.6025,
        "q_len_mm": 7.8217,
    },
    "patch_array_2x2": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_x_mm": 25.0172, "spacing_y_mm": 25.0172, "feed_w_mm": 1.112,
        "q_w_mm": 0.6025, "q_len_mm": 7.8217,
    },
    "patch_array_series": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "feed_w_mm": 1.112,
        "link_len_mm": 15.2876, "feed_margin_mm": 8.0,
    },
}

_ARR_ELEM_SEMANTICS = (
    "elem_len_mm=单元谐振长 L（沿 y；Balanis Ch.14 传输线模型 c/(2f0√εeff)−2ΔL，"
    "fake 谐振为其精确逆），elem_w_mm=单元宽 W（沿 x；c/(2f0)√(2/(εr+1))，"
    "决定 εeff/ΔL 与 H 面波束）")
_ARR_TREE_SEMANTICS = (
    "feed_w_mm=50Ω 线宽（主干/透明连线/缺口内馈段；HJ 1.112mm），q_w_mm=70.7Ω "
    "λ/4 变换段宽（HJ 0.6025mm），q_len_mm=变换段长 λ/4=c/(4f0√εeff(q_w))=7.8217mm"
    "（J0→J1± 与各元入缺口最后一段共用），elem_feed_mm=插入馈深度 y0（缺口深=馈线"
    "终点=馈点；Rin(y0)=Rin(0)cos²(πy0/L)，0.3L≈100Ω 口径）")

ARRAY_META: dict[str, dict[str, Any]] = {
    "patch_array_1x4": {
        "f0_ghz": 5.8, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（底探针馈 corporate 1×4 贴片阵：谷位/谷深"
                      "；方向图走 far_field=True nf2ff，离线裁判=积定理闭式：主瓣 0°、"
                      "HPBW 对照 broadside_hpbw_deg(4,d/λ0)、无栅瓣；未真机冒烟）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_mm",
                   "feed_w_mm", "q_w_mm", "q_len_mm"],
        "topology": "1×4 直线贴片阵（§10.3 C2）：4 元沿 x 等距 spacing、行中心 y=20mm，"
                    "单元 L 沿 y/W 沿 x、插入馈缺口开在 −y 边（3 盒贴片）；corporate 树"
                    "=主干 50Ω（底探针→J0）+ J0→J1± λ/4 70.7Ω + J1± 50Ω 透明连线（y0 横"
                    "走/各元 x 竖走）+ 每元最后一段 λ/4 70.7Ω 入缺口；基板 + z-min PEC 地",
        "param_semantics": _ARR_ELEM_SEMANTICS + "，spacing_mm=单元中心距 d（0.484λ0="
                           "25.0172mm，略缩 λ0/2 以满足审计扰动域 3d+W≤120mm；栅瓣判据 "
                           "d<λ0），" + _ARR_TREE_SEMANTICS,
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/树/探针）精确"
                     "入网（#198）",
    },
    "patch_array_2x2": {
        "f0_ghz": 5.8, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（底探针馈 H-tree 2×2 贴片阵：谷位/谷深；方向图"
                      "走 far_field=True nf2ff，离线裁判=平面阵可分离积 AF_x·AF_y 逐点；"
                      "未真机冒烟）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_x_mm",
                   "spacing_y_mm", "feed_w_mm", "q_w_mm", "q_len_mm"],
        "topology": "2×2 平面贴片阵（§10.3 C2）：栅格中心 (0,20mm)，元列 x=±dx/2、元排 "
                    "y=20∓dy/2；底排缺口向 −y 自下入，顶排缺口向 +y——馈线经 J1± 沿 y0 外走"
                    "到元列外侧走廊 x=±(dx/2+W/2+2mm) 上行、顶排上方内折、变换段自上向下入"
                    "缺口（同层零交叉）；H-tree 阻抗账同 1×4；基板 + z-min PEC 地",
        "param_semantics": _ARR_ELEM_SEMANTICS + "，spacing_x_mm/spacing_y_mm=元列/元排"
                           "中心距（均 0.484λ0=25.0172mm；可分离栅格），"
                           + _ARR_TREE_SEMANTICS,
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘精确入网（#198）",
    },
    "patch_array_series": {
        "f0_ghz": 5.8, "n_ports": 1,
        "extraction": "S11 @ MSLPort 1（1×3 共线串馈贴片阵，端接=链末开路辐射边：谷位/"
                      "谷深；方向图走 far_field=True nf2ff，离线裁判=积定理闭式（同相侧射"
                      "）；未真机冒烟）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "feed_w_mm", "link_len_mm",
                   "feed_margin_mm"],
        "topology": "1×3 串馈贴片阵（§10.3 C2）：3 元共线沿 y（x=0 居中，L 沿 y/W 沿 x），"
                    "相邻元以 λg/2 50Ω 互联接辐射边中心；MSLPort 自 y=−BOARD 入、自画馈段"
                    "至链首元 −y 边（feed_margin）；链末开路。相位账：λg/2 段 180°+λ/2 贴片"
                    "两边场反相 180° ⇒ 同相侧射；单轴 PML（y）；基板 + z-min PEC 地",
        "param_semantics": _ARR_ELEM_SEMANTICS + "，feed_w_mm=50Ω 馈线/互联宽（HJ "
                           "1.112mm），link_len_mm=互联长 λg/2=c/(2f0√εeff(feed_w))="
                           "15.2876mm（HJ），feed_margin_mm=板边到链首元的馈段长（MSLPort"
                           " 自画，MeasPlaneShift=margin/3）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；贴片/互联/馈段盒缘精确入网（#198）",
    },
}

# ── 注册：同对象入 TEMPLATE_META/TEMPLATE_NOMINAL（单一事实源；antenna2 同款）──
# 四处同步：① docs/templates/<t>/meta.yaml ×3；② test_template_geometry_audit.
# EXPECTED_TEMPLATES（+3）；③ fake_adapter 派发 _array_sparams；④ models/
# template_specs._register_patch_array。
for _arr_name in ARRAY_TEMPLATES:
    TEMPLATE_META[_arr_name] = ARRAY_META[_arr_name]
    TEMPLATE_NOMINAL[_arr_name] = ARRAY_NOMINAL[_arr_name]
del _arr_name


def array_meta(template: str) -> dict[str, Any]:
    """返回 C2 阵列族某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in ARRAY_TEMPLATES:
        raise KeyError(f"非 C2 阵列模板: {template}（可用 {ARRAY_TEMPLATES}）")
    meta = dict(ARRAY_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(ARRAY_NOMINAL[template])
    return meta


def _arr_layout(
    template: str,
    params: dict[str, Any],
    sub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """C2 阵列族单一事实源（mm）：金属盒 / 端口 / 单元中心 / z 网格线。

    渲染段（_arr_body）、近场加密（_near_points 分支）、UI 预览（geometry_spec
    分支）与离线审计（test_array_templates / test_template_geometry_audit）四方
    消费——单源防漂移（_ant2_layout / _hairpin_layout 同制度）。
    盒元组 = (金属属性名, 盒名, x0, y0, z0, x1, y1, z1)，全部零厚顶面 z=h
    （官方金属面口径）；集总馈口激励向 z 跨度 = h > 0（#174）。
    几何守卫显式 ValueError（超板/重叠/缺口越界），不静默夹紧——审计 ×1.37
    扰动域已按标称常数预核（段首"设计点与几何约束"）。
    """
    if template not in ARRAY_TEMPLATES:
        raise ValueError(f"未知 C2 阵列模板: {template}")
    sub = sub or _DEFAULT_SUB
    er = float(sub["er"])
    h = float(sub["h_mm"])
    nom = ARRAY_NOMINAL[template]

    def g(key: str) -> float:
        return float(params.get(key, nom[key]))

    length = g("elem_len_mm")
    width = g("elem_w_mm")
    fw = g("feed_w_mm")
    if not (length > 0.0 and width > 0.0 and fw > 0.0):
        raise ValueError(f"{template}: 单元 L/W 与馈线宽须正")
    if fw >= width:
        raise ValueError(f"{template}: 馈线宽 {fw} 须小于单元宽 {width}")
    board = _ARR_BOARD_MM
    lim = board - _ARR_EDGE_MARGIN_MM
    prop_patch = f"{template}_patch"
    prop_line = f"{template}_line"
    prop_q = f"{template}_qline"
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    ports: list[dict[str, Any]] = []
    elements: list[tuple[float, float]] = []

    def hline(tag: str, x0: float, x1: float, y: float, w: float, prop: str) -> None:
        boxes.append((prop, tag, min(x0, x1), y - w / 2, h, max(x0, x1), y + w / 2, h))

    def vline(tag: str, x: float, y0: float, y1: float, w: float, prop: str) -> None:
        boxes.append((prop, tag, x - w / 2, min(y0, y1), h, x + w / 2, max(y0, y1), h))

    if template == "patch_array_series":
        link = g("link_len_mm")
        margin = g("feed_margin_mm")
        if not (link > 0.0 and margin > 0.0):
            raise ValueError("patch_array_series: 互联长/馈段长须正")
        if width / 2 > lim:
            raise ValueError("patch_array_series: 单元宽超板")
        y = -board + margin
        for k in range(_ARR_SERIES_N):
            boxes.append((prop_patch, f"e{k}", -width / 2, y, h, width / 2, y + length, h))
            elements.append((0.0, y + length / 2))
            if k < _ARR_SERIES_N - 1:
                vline(f"link{k}", 0.0, y + length, y + length + link, fw, prop_line)
            y += length + link
        chain_top = y - link
        if chain_top > lim:
            raise ValueError(
                f"patch_array_series: 链顶 {chain_top:.3f}mm 超板（≤{lim}mm；"
                f"{_ARR_SERIES_N}·L + {_ARR_SERIES_N - 1}·λg/2 + margin）")
        ports.append({"kind": "msl", "nr": 1, "metal_prop": prop_line,
                      "start_mm": (fw / 2, -board, h),
                      "stop_mm": (-fw / 2, -board + margin, 0.0),
                      "prop_dir": "y", "exc_dir": "z", "excite": 1,
                      "meas_shift_mm": margin / 3.0})
    else:
        d_in = g("elem_feed_mm")
        qw = g("q_w_mm")
        ql = g("q_len_mm")
        nw = fw + 2.0 * _ARR_NOTCH_CLEAR_MM
        if not (0.0 < d_in < length / 2):
            raise ValueError(f"{template}: 插入深度 {d_in} 须落在 (0, L/2={length / 2})")
        if nw >= width:
            raise ValueError(f"{template}: 缺口宽 {nw} 须小于单元宽 {width}")
        if not (qw > 0.0 and ql > 0.0):
            raise ValueError(f"{template}: 变换段宽/长须正")
        y0 = _ARR_TREE_Y_MM[template]
        y_probe = y0 - _ARR_TRUNK_MM
        cy = _ARR_ROW_Y_MM

        def inset_elem(tag: str, cx: float, cyl: float, mouth_sign: int) -> float:
            """插入馈贴片 3 盒 + 缺口内 50Ω 馈段；返回缺口口沿 y（mouth）。

            mouth_sign=−1：缺口开在 −y 边（自下入）；+1：开在 +y 边（自上入）。
            馈段终点触缺口顶盒 = 馈点（连通即由此面接触建立）。
            """
            y_lo, y_hi = cyl - length / 2, cyl + length / 2
            boxes.append((prop_patch, f"{tag}_l", cx - width / 2, y_lo, h,
                          cx - nw / 2, y_hi, h))
            boxes.append((prop_patch, f"{tag}_r", cx + nw / 2, y_lo, h,
                          cx + width / 2, y_hi, h))
            if mouth_sign < 0:
                boxes.append((prop_patch, f"{tag}_c", cx - nw / 2, y_lo + d_in, h,
                              cx + nw / 2, y_hi, h))
                mouth = y_lo
            else:
                boxes.append((prop_patch, f"{tag}_c", cx - nw / 2, y_lo, h,
                              cx + nw / 2, y_hi - d_in, h))
                mouth = y_hi
            vline(f"{tag}_stub", cx, mouth, mouth - mouth_sign * d_in, fw, prop_line)
            elements.append((cx, cyl))
            return mouth

        # 主干（探针盒完全位于主干金属下方）+ J0→J1± λ/4 变换段
        vline("trunk", 0.0, y_probe - _ARR_PROBE_HALF_Y_MM, y0, fw, prop_line)
        hline("q_j0_l", -ql, 0.0, y0, qw, prop_q)
        hline("q_j0_r", 0.0, ql, y0, qw, prop_q)
        if template == "patch_array_1x4":
            s = g("spacing_mm")
            if s <= width:
                raise ValueError(f"patch_array_1x4: 中心距 {s} 须大于单元宽 {width}（重叠）")
            if ql >= s / 2:
                raise ValueError(f"patch_array_1x4: λ/4 段 {ql} 须小于半间距 {s / 2}")
            if 1.5 * s + width / 2 > board:
                raise ValueError(
                    f"patch_array_1x4: 跨度 3d+W={3 * s + width:.3f}mm 超 {2 * board}mm 板")
            if cy + length / 2 > lim:
                raise ValueError("patch_array_1x4: 单元顶超板")
            mouth = cy - length / 2
            y_ts = mouth - ql
            if y_ts <= y0 + fw:
                raise ValueError(
                    f"patch_array_1x4: 变换段起点 {y_ts:.3f} 须在 J 线 {y0} 上方")
            for i in range(4):
                cx = (i - 1.5) * s
                sgn = -1.0 if cx < 0.0 else 1.0
                hline(f"run{i}", sgn * ql, cx, y0, fw, prop_line)
                vline(f"rise{i}", cx, y0, y_ts, fw, prop_line)
                vline(f"q{i}", cx, y_ts, mouth, qw, prop_q)
                inset_elem(f"e{i}", cx, cy, -1)
        else:  # patch_array_2x2
            dx = g("spacing_x_mm")
            dy = g("spacing_y_mm")
            if dx <= width or dy <= length:
                raise ValueError(f"patch_array_2x2: 中心距 ({dx},{dy}) 须大于单元 ({width},{length})")
            if ql >= dx / 2:
                raise ValueError(f"patch_array_2x2: λ/4 段 {ql} 须小于半列距 {dx / 2}")
            row_b, row_t = cy - dy / 2, cy + dy / 2
            mouth_b = row_b - length / 2
            mouth_t = row_t + length / 2
            y_tsb = mouth_b - ql
            y_ta = mouth_t + ql
            x_c = dx / 2 + width / 2 + _ARR_CORRIDOR_CLEAR_MM
            if y_tsb <= y0 + fw:
                raise ValueError(
                    f"patch_array_2x2: 底排变换段起点 {y_tsb:.3f} 须在 J 线 {y0} 上方")
            if y_ta + qw / 2 > lim:
                raise ValueError(f"patch_array_2x2: 顶排走线 y={y_ta:.3f} 超板顶")
            if x_c + fw / 2 > lim:
                raise ValueError(f"patch_array_2x2: 走廊 x={x_c:.3f} 超板边")
            for cx in (-dx / 2, dx / 2):
                sgn = -1.0 if cx < 0.0 else 1.0
                tag = "l" if cx < 0.0 else "r"
                # 底排：J1 沿 y0 外走（共享段，顺带覆盖到走廊起点）→ 元列竖走 → 变换段 → 缺口
                hline(f"run_b_{tag}", sgn * ql, sgn * x_c, y0, fw, prop_line)
                vline(f"rise_b_{tag}", cx, y0, y_tsb, fw, prop_line)
                vline(f"q_b_{tag}", cx, y_tsb, mouth_b, qw, prop_q)
                inset_elem(f"e_b_{tag}", cx, row_b, -1)
                # 顶排：走廊上行 → 顶排上方内折 → 变换段自上向下 → 缺口（同层零交叉）
                vline(f"corr_{tag}", sgn * x_c, y0, y_ta, fw, prop_line)
                hline(f"run_t_{tag}", sgn * x_c, cx, y_ta, fw, prop_line)
                vline(f"q_t_{tag}", cx, y_ta, mouth_t, qw, prop_q)
                inset_elem(f"e_t_{tag}", cx, row_t, +1)
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-_ARR_PROBE_HALF_X_MM, y_probe - _ARR_PROBE_HALF_Y_MM, 0.0),
                      "stop_mm": (_ARR_PROBE_HALF_X_MM, y_probe + _ARR_PROBE_HALF_Y_MM, h),
                      "exc_dir": "z", "excite": 1})
    return {
        "boxes": boxes,
        "ports": ports,
        "elements_mm": elements,
        "z_lines_mm": [0.0, h],
        "element_top_mm": h,
        "air_below": False,
        "substrate": True,
        "er": er, "h_mm": h,
    }


def _arr_body(template: str, p: dict[str, Any]) -> str:
    """由 _arr_layout 单源渲染几何段（金属盒 + 端口 + priority 收口；_ant2_body 同构）。

    坐标全部走布局字面量（米），渲染==布局==审计三方一致；单端口模板
    _port2=_port1（patch 单端口 fallback 口径）。
    """
    lay = _arr_layout(template, p)
    out: list[str] = []
    m = lambda v: repr(float(v) * 1e-3)   # noqa: E731  mm→m 字面量
    metal_names: list[str] = []
    for box in lay["boxes"]:
        if box[0] not in metal_names:
            metal_names.append(box[0])
    for prop in metal_names:
        out.append(f'{prop} = CSX.AddMetal("{prop}")')
    for (prop, name, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f'{prop}.AddBox(({m(x0)}, {m(y0)}, {m(z0)}), '
                   f'({m(x1)}, {m(y1)}, {m(z1)}), priority=10)  # {name}')
    for port in lay["ports"]:
        s, t = port["start_mm"], port["stop_mm"]
        nr = int(port["nr"])
        if port["kind"] == "lumped":
            out.append(
                f'_port{nr} = LumpedPort(CSX, port_nr={nr}, R={port["R"]!r},\n'
                f'                    start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                    stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                    exc_dir="{port["exc_dir"]}", '
                f'excite={int(port["excite"])}, priority=5)')
        else:
            out.append(
                f'_port{nr} = MSLPort(CSX, port_nr={nr}, '
                f'metal_prop={port["metal_prop"]},\n'
                f'                 start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                 stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                 prop_dir="{port["prop_dir"]}", '
                f'exc_dir="{port["exc_dir"]}", excite={int(port["excite"])},\n'
                f'                 FeedShift=10 * NEAR, '
                f'MeasPlaneShift={float(port["meas_shift_mm"]) * 1e-3!r},\n'
                f'                 priority=10)')
    if len(lay["ports"]) == 1:
        out.append('_port2 = _port1   # 单端口模板：footer fallback 口径')
    for prop in metal_names:
        out.append(f'for _prim in {prop}.GetAllPrimitives():\n'
                   '    if _prim.GetPriority() < 10:\n'
                   '        _prim.SetPriority(10)')
    return "\n".join(out) + "\n"


def _patch_array_1x4_lines(p: dict[str, Any]) -> str:
    # §10.3 C2 1×4 corporate 贴片阵：插入馈单元 ×4 + λ/4 70.7Ω 变换树 + 底探针
    # LumpedPort（patch 官方口径）；设计式/布局/审计单源 _arr_layout。
    return _arr_body("patch_array_1x4", p)


def _patch_array_2x2_lines(p: dict[str, Any]) -> str:
    # §10.3 C2 2×2 H-tree 贴片阵：底排自下入缺口、顶排走廊绕行自上入缺口
    # （同层零交叉），底探针 LumpedPort。
    return _arr_body("patch_array_2x2", p)


def _patch_array_series_lines(p: dict[str, Any]) -> str:
    # §10.3 C2 1×3 共线串馈贴片阵：λg/2 互联接辐射边中心，MSLPort 自 y=−BOARD 入
    # （slot 馈段同款自画 + MeasPlaneShift=margin/3）。
    return _arr_body("patch_array_series", p)


# ═══════════════════════════════════════════════════════════════════════════════
# §DP-4 P3 EEP 阵列族（2026-09-24 df6）：patch_eep_2x2 / patch_eep_1x4 ═════════
# 互耦档（EEP）专用阵模板：单元平铺参数化（elem_len/w/feed_mm + spacing_x/y_mm），
# **每元独立 LumpedPort 底探针馈（端口 1..4），无 corporate 馈树**——
# N 次单激励轮转（#208 进程隔离，_FOUR_PORT_ROTATION_TEMPLATES 9 列 CSV footer）
# 逐轮产出第 n 列 S 参数与第 n 元有源方向图（EEPₙ，nf2ff 全局原点参考，
# farfield3d_cplx.csv）；非激励端口=50Ω 集总元端接（EEP 教科书口径）。
#
# ── 理论核验轮（#206/铁律 1b）──
# 1. EEP 定义：F(û)=ΣₙaₙEEPₙ(û)，EEPₙ=第 n 元有源单元方向图（其余元 50Ω 端接
#    被动在场）；Γ_act,n=Σ_m S_nm(a_m/a_n)（DP-4 规格书 §2c；Pozar & Schaubert
#    1984）。叠加可行性前提：各轮 nf2ff 在**同一频率**取值——EEP 轮 f_res=F0
#    固定（设计带中心），非 argmin|S11|（其余元被动在场的单激励轮里 port1
#    的 S11 谷不代表阵列谐振，且逐轮 argmin 会漂到不同频点使叠加失效）。
# 2. 轮间幅度/相位可比前提：各元端口几何全同（R=50 同阻值、同探针盒）且
#    各轮激励幅值一致（excite=1 同脉冲）——EEPₙ 逐轮按同一"单位入射波"尺度
#    落盘（nf2ff 场对激励线性）。非均匀元尺寸阵此前提不成立，如实不外推。
# 3. 单元几何沿用官方 Simple Patch Antenna 底探针口径（_patch_lines/C2 同源
#    闭式：Balanis Ch.14 传输线模型 W=c/(2f0)√(2/(εr+1))、L=c/(2f0√εeff)−2ΔL、
#    插入馈 0.3L≈100Ω 口径；线宽 skrf HJ 精算 #1c）——与 C2 阵列族共用
#    array_elem_w_mm/array_elem_len_mm/array_line_w_mm 设计链（零复制毫米数）。
# 4. 端口取向全 −y（元间同向、同极化）：EEP 阵无馈树约束，不需要 C2 2×2 的
#    顶排翻转（那是同层零交叉布线手段）；同向是 EEP 阵的物理规范形。
#
# ── 设计点与几何约束（复用 C2 预核扰动域，#212 ×1.37+0.013 单键逐键可建）──
# f0=5.8GHz、BOARD=60mm 共享字面量；spacing=0.484λ0=25.0172mm（同 C2：1×4
# 跨度 3d+W=126mm>120 的扰动域由 C2 同款守卫 board=60（非 lim）恰好容纳
# 1.5·s'+W'/2=59.90≤60）；元间 DC 隔离（4 个独立导体分量）=EEP 定义性质，
# 审计 PORT_GROUPS 四组 {1}{2}{3}{4}（非功分器族的单分量判据）。
EEP_TEMPLATES: tuple[str, ...] = ("patch_eep_2x2", "patch_eep_1x4")
_EEP_BOARD_MM = _ARR_BOARD_MM            # 与 render_script BOARD=60e-3 同值（mm）
_EEP_EDGE_MARGIN_MM = _ARR_EDGE_MARGIN_MM
_EEP_ROW_Y_MM = _ARR_ROW_Y_MM            # 阵面行中心 y（1×4 单行 / 2×2 栅格中心）
_EEP_NOTCH_CLEAR_MM = _ARR_NOTCH_CLEAR_MM
_EEP_PROBE_HALF_X_MM = _ARR_PROBE_HALF_X_MM   # 底探针盒 x 半宽（patch 官方 0.2mm 盒）
_EEP_PROBE_HALF_Y_MM = _ARR_PROBE_HALF_Y_MM   # 底探针盒 y 半宽（patch 官方 2mm 盒）
_EEP_SPACING_FRAC = _ARR_SPACING_FRAC    # 单元间距/λ0（同 C2，0.484）

#: EEP 3D 复数远场网格（度；模板脚本与 core.farfield 契约共同遵守）
EEP_FF_THETA_DEG = (0.0, 180.0, 5.0)
EEP_FF_PHI_DEG = (0.0, 360.0, 5.0)


def eep_n_ports(template: str) -> int:
    """EEP 模板端口数（=单元数，恒 4——excite_port 钳位 1..4 恰容 2×2）。"""
    if template not in EEP_TEMPLATES:
        raise KeyError(f"非 EEP 阵列模板: {template}（可用 {EEP_TEMPLATES}）")
    return 4


def eep_design_params(template: str, f0_ghz: float = 5.8, er: float = 3.66,
                      h_mm: float = 0.508) -> dict[str, Any]:
    """EEP 两模板全参数设计链（4 位舍入；EEP_NOMINAL = 本函数 @5.8GHz，单测互检）。

    全部尺寸出自确定性闭式（#1c）：单元 W/L（Balanis Ch.14，array_elem_w/len_mm）、
    插入馈深 0.3L（~100Ω 口径）、间距 0.484λ0（同 C2，栅瓣判据 d<λ0）、
    馈线宽（skrf HJ inverse_width 50Ω）。先舍入再出的口径与 ARRAY_NOMINAL 一致。
    """
    if template not in EEP_TEMPLATES:
        raise KeyError(f"非 EEP 阵列模板: {template}（可用 {EEP_TEMPLATES}）")
    f0 = float(f0_ghz)
    w_raw = array_elem_w_mm(f0, er)
    l_raw = array_elem_len_mm(f0, w_raw, er, h_mm)
    params: dict[str, Any] = {
        "elem_len_mm": round(l_raw, 4),
        "elem_w_mm": round(w_raw, 4),
        "elem_feed_mm": round(_ARR_INSET_FRAC * l_raw, 4),
        "spacing_x_mm": round(_EEP_SPACING_FRAC * _ARR_C_MM_GHZ / f0, 4),
        "feed_w_mm": round(array_line_w_mm(50.0, f0, er, h_mm), 4),
    }
    if template == "patch_eep_2x2":
        params["spacing_y_mm"] = params["spacing_x_mm"]
    return params


#: 各模板标称设计点 @5.8GHz（= eep_design_params 4 位舍入，单测互检）
EEP_NOMINAL: dict[str, dict[str, Any]] = {
    "patch_eep_2x2": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_x_mm": 25.0172, "spacing_y_mm": 25.0172, "feed_w_mm": 1.112,
    },
    "patch_eep_1x4": {
        "elem_len_mm": 12.9058, "elem_w_mm": 16.9311, "elem_feed_mm": 3.8717,
        "spacing_x_mm": 25.0172, "feed_w_mm": 1.112,
    },
}

_EEP_ELEM_SEMANTICS = (
    "elem_len_mm=单元谐振长 L（沿 y；Balanis Ch.14 c/(2f0√εeff)−2ΔL，fake 谐振为"
    "精确逆），elem_w_mm=单元宽 W（沿 x；c/(2f0)√(2/(εr+1))），elem_feed_mm=插入"
    "馈深度（缺口深=探针馈点；Rin(y0)=Rin(0)cos²(πy0/L)，0.3L≈100Ω 口径），"
    "feed_w_mm=缺口内馈段/探针邻域线宽（HJ 50Ω 1.112mm）")

EEP_META: dict[str, dict[str, Any]] = {
    "patch_eep_2x2": {
        "f0_ghz": 5.8, "n_ports": 4,
        "extraction": "整 4×4 S @ LumpedPort 1-4（单激励 9 列 CSV，excite_port=1..4 "
                      "进程隔离轮转装配 → .s4p，#208）+ EEPₙ @ farfield3d_cplx.csv"
                      "（far_field=True，f_res=F0 固定口径，轮间同频可叠加）；互耦档"
                      "判据 J4 见 runs/df6_dp4p3/criteria.md",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_x_mm",
                   "spacing_y_mm", "feed_w_mm"],
        "topology": "2×2 EEP 贴片阵（§DP-4 P3）：栅格中心 (0,20mm)，元列 x=±dx/2、"
                    "元排 y=20∓dy/2，四元同向（缺口全开 −y）；每元独立 LumpedPort "
                    "底探针（端口 1..4=行主序 x 外层 y 内层），无 corporate 馈树，"
                    "元间 DC 隔离=EEP 定义性质；基板 + z-min PEC 地",
        "param_semantics": _EEP_ELEM_SEMANTICS + "，spacing_x_mm/spacing_y_mm=元列/"
                           "元排中心距（均 0.484λ0=25.0172mm，同 C2 扰动域预核）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/探针）精确"
                     "入网（#198）",
    },
    "patch_eep_1x4": {
        "f0_ghz": 5.8, "n_ports": 4,
        "extraction": "整 4×4 S @ LumpedPort 1-4（单激励 9 列 CSV，excite_port=1..4 "
                      "进程隔离轮转装配 → .s4p，#208）+ EEPₙ @ farfield3d_cplx.csv"
                      "（far_field=True，f_res=F0 固定口径，轮间同频可叠加）；互耦档"
                      "判据 J4 见 runs/df6_dp4p3/criteria.md",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["elem_len_mm", "elem_w_mm", "elem_feed_mm", "spacing_x_mm",
                   "feed_w_mm"],
        "topology": "1×4 EEP 贴片阵（§DP-4 P3）：4 元沿 x 等距 spacing（行中心 "
                    "y=20mm），缺口全开 −y；每元独立 LumpedPort 底探针（端口 1..4 "
                    "=x 升序），无 corporate 馈树，元间 DC 隔离=EEP 定义性质；基板 + "
                    "z-min PEC 地",
        "param_semantics": _EEP_ELEM_SEMANTICS + "，spacing_x_mm=单元中心距 d"
                           "（0.484λ0=25.0172mm；栅瓣判据 d<λ0，1×4 跨度 3d+W 扰动域"
                           "与 C2 同款预核 ≤120mm 板）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；全部盒缘（贴片/缺口/探针）精确"
                     "入网（#198）",
    },
}

# ── 注册（单一事实源；C2 同款）：同对象入 TEMPLATE_META/TEMPLATE_NOMINAL ──
for _eep_name in EEP_TEMPLATES:
    TEMPLATE_META[_eep_name] = EEP_META[_eep_name]
    TEMPLATE_NOMINAL[_eep_name] = EEP_NOMINAL[_eep_name]
del _eep_name


def eep_meta(template: str) -> dict[str, Any]:
    """返回 EEP 阵列族某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in EEP_TEMPLATES:
        raise KeyError(f"非 EEP 阵列模板: {template}（可用 {EEP_TEMPLATES}）")
    meta = dict(EEP_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(EEP_NOMINAL[template])
    return meta


def _eep_layout(
    template: str,
    params: dict[str, Any],
    sub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """EEP 两模板单一事实源（mm）：金属盒 / 端口 / 单元中心 / z 网格线。

    渲染段（_eep_body）、近场加密（_near_points 分支）、UI 预览（geometry_spec
    分支）与离线审计（test_eep_templates / test_template_geometry_audit）四方
    消费——单源防漂移（_arr_layout 同制度）。盒元组 =
    (金属属性名, 盒名, x0, y0, z0, x1, y1, z1)，全部零厚顶面 z=h；
    集总馈口激励向 z 跨度 = h > 0（#174）。
    端口次序（叠加/扫描相位记账的行主序契约，服务层同序消费）：
    1x4 = x 升序；2x2 = x 外层 y 内层 (−dx,−dy),(−dx,+dy),(+dx,−dy),(+dx,+dy)。
    """
    if template not in EEP_TEMPLATES:
        raise ValueError(f"未知 EEP 阵列模板: {template}")
    sub = sub or _DEFAULT_SUB
    er = float(sub["er"])
    h = float(sub["h_mm"])
    nom = EEP_NOMINAL[template]

    def g(key: str) -> float:
        return float(params.get(key, nom[key]))

    length = g("elem_len_mm")
    width = g("elem_w_mm")
    fw = g("feed_w_mm")
    d_in = g("elem_feed_mm")
    dx = g("spacing_x_mm")
    if not (length > 0.0 and width > 0.0 and fw > 0.0):
        raise ValueError(f"{template}: 单元 L/W 与馈线宽须正")
    if fw >= width:
        raise ValueError(f"{template}: 馈线宽 {fw} 须小于单元宽 {width}")
    if not (0.0 < d_in < length / 2):
        raise ValueError(f"{template}: 插入深度 {d_in} 须落在 (0, L/2={length / 2})")
    nw = fw + 2.0 * _EEP_NOTCH_CLEAR_MM
    if nw >= width:
        raise ValueError(f"{template}: 缺口宽 {nw} 须小于单元宽 {width}")
    if dx <= width:
        raise ValueError(f"{template}: 列距 {dx} 须大于单元宽 {width}（重叠）")
    board = _EEP_BOARD_MM
    lim = board - _EEP_EDGE_MARGIN_MM
    cy = _EEP_ROW_Y_MM
    prop_patch = f"{template}_patch"
    prop_line = f"{template}_line"
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    ports: list[dict[str, Any]] = []
    elements: list[tuple[float, float]] = []

    def inset_elem(tag: str, cx: float, cyl: float, nr: int) -> float:
        """插入馈贴片 3 盒 + 缺口内 50Ω 馈段 + 底探针 LumpedPort（返回馈点 y）。

        缺口开在 −y 边（四元同向）；探针从 z=0（PEC 地）跨基板到 z=h，
        盒顶面与缺口内馈段/缺口顶盒相接（连通即由此面接触建立，#174 激励
        体积=z 向 h>0）；excite 随 _excite_port 四态切换（ratrace 范式）。
        """
        y_lo, y_hi = cyl - length / 2, cyl + length / 2
        boxes.append((prop_patch, f"{tag}_l", cx - width / 2, y_lo, h,
                      cx - nw / 2, y_hi, h))
        boxes.append((prop_patch, f"{tag}_r", cx + nw / 2, y_lo, h,
                      cx + width / 2, y_hi, h))
        boxes.append((prop_patch, f"{tag}_c", cx - nw / 2, y_lo + d_in, h,
                      cx + nw / 2, y_hi, h))
        # 缺口内馈段：mouth → 缺口底（+y 向 d_in；终点=缺口顶盒底缘=馈点）
        boxes.append((prop_line, f"{tag}_stub", cx - fw / 2, y_lo, h,
                      cx + fw / 2, y_lo + d_in, h))
        yf = y_lo + d_in
        ep = int(params.get("_excite_port", 1) or 1)
        ports.append({
            "kind": "lumped", "nr": nr, "R": 50.0,
            "start_mm": (cx - _EEP_PROBE_HALF_X_MM, yf - _EEP_PROBE_HALF_Y_MM, 0.0),
            "stop_mm": (cx + _EEP_PROBE_HALF_X_MM, yf + _EEP_PROBE_HALF_Y_MM, h),
            "exc_dir": "z", "excite": 1 if ep == nr else 0})
        elements.append((cx, cyl))
        return yf

    if template == "patch_eep_1x4":
        if 1.5 * dx + width / 2 > board:
            raise ValueError(
                f"patch_eep_1x4: 跨度 3d+W={3 * dx + width:.3f}mm 超 {2 * board}mm 板")
        if cy + length / 2 > lim:
            raise ValueError("patch_eep_1x4: 单元顶超板")
        for i in range(4):
            inset_elem(f"e{i}", (i - 1.5) * dx, cy, i + 1)
    else:  # patch_eep_2x2
        dy = g("spacing_y_mm")
        if dy <= length:
            raise ValueError(f"patch_eep_2x2: 排距 {dy} 须大于单元长 {length}（重叠）")
        row_b, row_t = cy - dy / 2, cy + dy / 2
        if row_t + length / 2 > lim or row_b - length / 2 < -lim:
            raise ValueError("patch_eep_2x2: 元排越板")
        nr = 0
        for cx in (-dx / 2, dx / 2):          # x 外层
            for cyl in (row_b, row_t):        # y 内层（行主序=端口次序契约）
                nr += 1
                inset_elem(f"e{nr}", cx, cyl, nr)
    return {
        "boxes": boxes,
        "ports": ports,
        "elements_mm": elements,
        "z_lines_mm": [0.0, h],
        "element_top_mm": h,
        "air_below": False,
        "substrate": True,
        "er": er, "h_mm": h,
    }


def _eep_body(template: str, p: dict[str, Any]) -> str:
    """由 _eep_layout 单源渲染几何段（金属盒 + 端口 + priority 收口）。

    四端口 excite 随 _excite_port 四态切换（ratrace/branchline 范式）——
    非激励端口 excite=0 仅探针仍记录（LumpedPort u/i 探针无条件创建），
    渲染脚本尾部走单激励 9 列 CSV（_FOUR_PORT_ROTATION_TEMPLATES footer）。
    """
    lay = _eep_layout(template, p)
    out: list[str] = []
    m = lambda v: repr(float(v) * 1e-3)   # noqa: E731  mm→m 字面量
    metal_names: list[str] = []
    for box in lay["boxes"]:
        if box[0] not in metal_names:
            metal_names.append(box[0])
    for prop in metal_names:
        out.append(f'{prop} = CSX.AddMetal("{prop}")')
    for (prop, name, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f'{prop}.AddBox(({m(x0)}, {m(y0)}, {m(z0)}), '
                   f'({m(x1)}, {m(y1)}, {m(z1)}), priority=10)  # {name}')
    for port in lay["ports"]:
        s, t = port["start_mm"], port["stop_mm"]
        nr = int(port["nr"])
        out.append(
            f'_port{nr} = LumpedPort(CSX, port_nr={nr}, R={port["R"]!r},\n'
            f'                    start=np.array([{m(s[0])}, {m(s[1])}, '
            f'{m(s[2])}]),\n'
            f'                    stop=np.array([{m(t[0])}, {m(t[1])}, '
            f'{m(t[2])}]),\n'
            f'                    exc_dir="{port["exc_dir"]}", '
            f'excite={int(port["excite"])}, priority=5)')
    for prop in metal_names:
        out.append(f'for _prim in {prop}.GetAllPrimitives():\n'
                   '    if _prim.GetPriority() < 10:\n'
                   '        _prim.SetPriority(10)')
    return "\n".join(out) + "\n"


def _patch_eep_2x2_lines(p: dict[str, Any]) -> str:
    # §DP-4 P3 2×2 EEP 阵：四元同向独立探针（端口 1..4 行主序），无馈树。
    return _eep_body("patch_eep_2x2", p)


def _patch_eep_1x4_lines(p: dict[str, Any]) -> str:
    # §DP-4 P3 1×4 EEP 阵：四元同向独立探针（端口 1..4 x 升序），无馈树。
    return _eep_body("patch_eep_1x4", p)
