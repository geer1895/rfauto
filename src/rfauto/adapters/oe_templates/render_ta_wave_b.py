"""TA-10/AP-11 两模板（ge8b 批 Wave B 席 B9，2026-10-03）：ISL 屏蔽悬置线
isl_shielded + Vivaldi 端射张口槽线天线 vivaldi_tsa（render_fns 分发路径；
isl 走 layout 单源字面注入，hmsiw 同款机制）。

闭式/设计链内核（core 单源，本模块零几何数字副本 #116/#252）：
- isl_shielded → core/isl_line.py（悬置/倒置微带 εeff 准静态近似；双半腔
  Cohn 电容分解，对称退化/全空气/w→∞ 三极限裁判）；
- vivaldi_tsa → core/vivaldi_tsa.py（Gibson 1979 指数张口律 + 口面半波
  低截止工程准则；Yngvesson 1985 介质加载修正如实不入码，citation-rot）。

注册清单（同对象注册钉死单一事实源；render_fns 分发 + registry 轴/辐射器
面 + grid 近场线 + render_core z 网格/基板/底界块 + 审计
EXPECTED_TEMPLATES/TEMPLATE_MESH_MM/MATERIAL_VALUE_PARAMS + docs meta.yaml
+ 锚）。分发接线为 render_core.py **最小追加**（席1 既有行零改动，append-only；
本席纪律偏离已在交付报告披露）。
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from rfauto.core.coupled_microstrip import HAIRPIN_50OHM_W_MM
from rfauto.core.isl_line import suspended_ms_qs
from rfauto.core.vivaldi_tsa import (
    vivaldi_low_cutoff_ghz,
    vivaldi_slot_half_width_mm,
    vivaldi_taper_k_per_mm,
)

from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

_MESH_FLOOR_M = 10e-6   # 显式近场线最小间距地板（#349，siw/hmsiw 同值）
_VIVALDI_N_SEG = 24     # 指数槽阶梯化站数（单侧；ratrace 栅格化同手法）
_VIVALDI_EDGE_STANDOFF_MM = 5.0   # 口面/喉部到板边 MUR 最小净距


# ═══ TA-10 isl_shielded（ISL 屏蔽悬置线均匀段）══════════════════════════════
# 结构：地面=z=0 域 PEC 底界；空气隙 z∈[0,g]；基板 z∈[g,g+h_sub]（悬浮）；
# 零厚条带 z=g+h_sub（基板上表面）；条带上空气 h_top 至屏蔽顶板 z=z_wall
# （显式零厚板）；两列过孔藩篱 x=±wall_x 连接底地与顶板（藩篱止于端口面，
# hmsiw/siw v2 端面口径）。端口=双 MSLPort 板边入（inverted_ms 口径，
# 端口面贴板边 PML）。设计链=core/isl_line.suspended_ms_qs 准静态。

def isl_layout(params: dict[str, Any], base_m: float,
               h_m: float) -> dict[str, Any]:
    """isl_shielded 几何/端口/域单一事实源（mm 入参 → 米字面量+守卫；
    hmsiw_layout 同构）。闭式链=core/isl_line（准静态 εeff/Z0 回代）；
    网格守卫：过孔直径 ≥4·NEAR、孔间缝 >NEAR（hmsiw 口径）、显式近场线
    10µm 地板（#349）。"""
    w = float(params.get("w_mm", ISL_NOMINAL["w_mm"])) * 1e-3
    g = float(params.get("g_air_mm", ISL_NOMINAL["g_air_mm"])) * 1e-3
    hs = float(h_m)
    ht = float(params.get("h_top_mm", ISL_NOMINAL["h_top_mm"])) * 1e-3
    d = float(params.get("d_mm", ISL_NOMINAL["d_mm"])) * 1e-3
    s = float(params.get("s_mm", ISL_NOMINAL["s_mm"])) * 1e-3
    line_len = float(params.get("line_len_mm", ISL_NOMINAL["line_len_mm"])) * 1e-3
    er = float(params.get("er", _DEFAULT_SUB["er"]))
    for name, value in (("w_mm", w), ("g_air_mm", g), ("h_top_mm", ht),
                        ("d_mm", d), ("s_mm", s), ("line_len_mm", line_len)):
        if not (math.isfinite(value) and value > 0.0):
            raise ValueError(f"isl_layout: {name} 必须为正有限，得到 {value!r}")
    if not (math.isfinite(base_m) and base_m > 0.0):
        raise ValueError(f"isl_layout: base 必须为正有限，得到 {base_m!r}")
    near = base_m / 4.0
    if not d >= 4.0 * near:
        raise ValueError(
            f"isl_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm，hmsiw 同口径）")
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"isl_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（缝内零内部网格线，#311 先例口径）")
    y_half = line_len / 2.0
    k_half = math.floor((y_half - d / 2) / s + 1e-9)
    if k_half < 1:
        raise ValueError(
            f"isl_layout: 藩篱止于端口面后无线段区过孔（line_len/2−d/2="
            f"{(y_half - d / 2) * 1e3:.4g}mm < s={s * 1e3:.4g}mm）——"
            "加大 line_len_mm（hmsiw 同款）")
    if not k_half * s + d / 2 < y_half:
        raise ValueError(
            f"isl_layout: 末孔缘 {k_half * s + d / 2!r} 越过端口面 "
            f"{y_half!r}（数值容差外）")
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    z_strip = g + hs
    z_wall = z_strip + ht
    # 腔半宽=条带半宽+2×腔高（侧壁场余量；d<2·(z_wall) 恒成立闭合）
    wall_x = w / 2.0 + 2.0 * z_wall
    if not d < 2.0 * z_wall:
        raise ValueError(
            f"isl_layout: 过孔直径 d={d * 1e3:.4g}mm ≥ 2×腔高 "
            f"{2.0 * z_wall * 1e3:.4g}mm（藩篱穿透顶板）")
    # 显式近场线集最小间距地板（#349，hmsiw 同款）：x=条带缘/藩篱三线对
    # （±wall_x∓d/2、±wall_x）；y=线端 ±y_half + 每孔三线
    x_lines = {0.0, w / 2, -w / 2, wall_x - d / 2, wall_x,
               -(wall_x - d / 2), -wall_x}
    y_lines = {-y_half, y_half}
    for _yk in via_y:
        y_lines.update((_yk - d / 2, _yk, _yk + d / 2))
    for _name, _lines in (("x", sorted(x_lines)), ("y", sorted(y_lines))):
        _gaps = [b - a for a, b in pairwise(_lines)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _MESH_FLOOR_M:
            raise ValueError(
                f"isl_layout: {_name} 向显式网格线最小间距 {_gmin * 1e6:.3f}µm "
                f"≤ {_MESH_FLOOR_M * 1e6:.0f}µm 地板（#349 CFL 塌缩守卫；"
                "调整 d/s/line_len）")
    # 准静态链（core 单源）：50Ω 名义回代自洽 + εeff 报告
    chain = suspended_ms_qs(w * 1e3, g * 1e3, hs * 1e3, er, ht * 1e3)
    if not chain["z0_ohm"] > 0.0:
        raise ValueError("isl_layout: 准静态 Z0 非正（内核异常）")
    return {"w": w, "g": g, "hs": hs, "ht": ht, "d": d, "s": s,
            "er": er, "line_len": line_len, "near": near,
            "z_strip": z_strip, "z_wall": z_wall, "wall_x": wall_x,
            "y_half": y_half, "via_y": via_y,
            "eps_eff": chain["eps_eff"], "z0_ohm": chain["z0_ohm"]}


def _isl_lines(p: dict[str, Any]) -> str:
    # ISL 直线段几何段（layout 单源字面注入，米）。必须经 render_script
    # 渲染（_isl_layout 注入）——直调缺布局显式报错（hmsiw 同款 #283 纪律）。
    lay = p.get("_isl_layout")
    if lay is None:
        raise ValueError(
            "isl_shielded 几何段缺 _isl_layout：必须经 render_script 渲染"
            "（布局单源注入）")
    via_y = list(lay["via_y"])
    return f'''# ── ISL 屏蔽悬置线几何（layout 单源字面量，米；TA-10 准静态口径）──
W = {lay["w"]!r}              # 条带宽（50Ω 准静态反解，core/isl_line）
Z_STRIP = {lay["z_strip"]!r}  # 条带 z=空气隙顶+基板（基板上表面，z 网格字面同源）
Z_WALL = {lay["z_wall"]!r}    # 屏蔽顶板 z（腔高 = g_air+h_sub+h_top）
WALL_X = {lay["wall_x"]!r}    # 藩篱列心 x=±WALL_X（条带半宽+2×腔高）
D_VIA = {lay["d"]!r}          # 过孔直径
S_PITCH = {lay["s"]!r}        # 过孔心距（藩篱止于端口面=hmsiw v2 端面口径）
Y0 = {-lay["y_half"]!r}       # port1 测量面（线端）
Y1 = {lay["y_half"]!r}        # port2 测量面
isl_strip = CSX.AddMetal("isl_strip")
isl_strip.AddBox((-W / 2, Y0, Z_STRIP), (W / 2, Y1, Z_STRIP), priority=10)
# 屏蔽顶板：显式零厚板 z=Z_WALL（腔内屏蔽；其上 AIR_TOP+MUR 域界）
isl_wall = CSX.AddMetal("isl_wall")
isl_wall.AddBox((-WALL_X - D_VIA / 2, Y0, Z_WALL),
                (WALL_X + D_VIA / 2, Y1, Z_WALL), priority=10)
# 两列过孔藩篱 PEC 圆柱（z∈[0,Z_WALL] 贯通：底=域 PEC 地、顶=顶板，
# 侧屏蔽=ISL/SISL 定义性质；条带居腔内与藩篱净距 >d，DC 隔离）
isl_via = CSX.AddMetal("isl_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    isl_via.AddCylinder([-WALL_X, _vy, 0.0], [-WALL_X, _vy, Z_WALL],
                        radius=D_VIA / 2, priority=10)
    isl_via.AddCylinder([WALL_X, _vy, 0.0], [WALL_X, _vy, Z_WALL],
                        radius=D_VIA / 2, priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=isl_strip,
                 start=np.array([W / 2, -BOARD, Z_STRIP]),
                 stop=np.array([-W / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=isl_strip,
                 start=np.array([-W / 2, BOARD, Z_STRIP]),
                 stop=np.array([W / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in isl_strip.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in isl_wall.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in isl_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


ISL_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（ISL 屏蔽悬置线均匀线：S21 相位"
                  "斜率→εeff，β 金标准 mline 同口径；|S11| 显著非零=端口/"
                  "网格判废信号）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "g_air_mm", "h_top_mm", "d_mm", "s_mm",
               "line_len_mm"],
    "topology": "ISL 屏蔽悬置线均匀段（TA-10，准静态口径如实）：地面=z=0 "
                "域 PEC 底界→空气隙 g→基板 [g, g+h_sub]（悬浮）→零厚条带"
                "（基板上表面）→空气 h_top→屏蔽顶板（显式零厚板 z=z_wall）；"
                "两列过孔藩篱 x=±wall_x 贯通底地与顶板（藩篱止于端口面，"
                "hmsiw v2 端面口径）；双 MSLPort 板边入（端口面贴 PML）",
    "param_semantics": "w_mm=条带宽（设计链 core/isl_line.isl_design_params："
                       "50Ω 准静态反解，名义 2.4818mm@g=0.508/h_sub=0.508/"
                       "h_top=1.016/εr=3.66，εeff=1.2854——空气份额高，εeff "
                       "显著低于同叠层微带属悬置定义性质）、g_air_mm=地面→"
                       "基板空气隙（悬置定义参数）、h_top_mm=条带→顶板腔高、"
                       "d_mm/s_mm=过孔藩篱直径/心距、line_len_mm=两端口测量"
                       "面间距；h_sub/er/tan_d 走 substrate/nominal",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "条带缘/藩篱三线对 x 向 + 线两端/每孔三线 y 向精确入网"
                 "（#198）；过孔直径 ≥4·NEAR、孔间缝 ≥1 内部线（hmsiw 同守"
                 "卫）、显式近场线 10µm 地板（#349）；基板 z 4 层+空气隙 2 "
                 "层（z 网格字面与基板盒/条带同源）",
    "smoke_note": "离线审计先行（#212，test_ta_wave_b_templates）；内核数字"
                  "裁判=三精确极限（对称退化≡_stripline_z0 逐位/εr=1→εeff=1/"
                  "w→∞ 串联层精确），文献频变闭式不可达如实账（round15 IET "
                  "口径，core/isl_line docstring）；近似级别如实登记：准静态"
                  "/零厚带/PEC 墙/无色散，双半腔非对称一阶误差 O(|h1−h2|/D)"
                  "（模型 wide-limit 与逐径混合差异，h1=h2 点恒等已钉）；真机"
                  "冒烟与 HFSS 仲裁属后续批次（本批零发射）",
}

ISL_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c，无手抄毫米数）：isl_design_params(50Ω, g=0.508,
    # h_sub=0.508, h_top=1.016, er=3.66) brentq 反解 → w=2.4818（回代
    # 50.0000Ω，εeff=1.2854）；test_ta_wave_b_templates 按链复算逐键钉
    # （准静态链毫秒级，#252 口径）。
    "w_mm": 2.4818, "g_air_mm": 0.508, "h_top_mm": 1.016,
    "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 40.0,
    "er": 3.66, "tan_d": 0.0037,
}


# ═══ AP-11 vivaldi_tsa（Vivaldi 端射指数张口槽线天线）══════════════════════
# 结构：有限地面 z=0（槽区=指数张口缝自喉部向口面张开，阶梯化栅格化
# ratrace 同手法）；基板 z∈[0,H_SUB] 上覆；50Ω 微带馈线 z=H_SUB 顶面沿
# x 跨槽（slot 模板已证跨槽耦合机理；巴伦=独立馈电件留登记注记）；
# 双 MSLPort 板边入（prop_dir=x，端口面贴板边 PML）。槽沿 y：喉部 y=−L/2、
# 口面 y=+L/2（板缘 MUR 净距 ≥5mm 守卫）。设计链=core/vivaldi_tsa
# （指数律+口面半波低截止准则）。

def vivaldi_layout(params: dict[str, Any]) -> dict[str, Any]:
    """vivaldi_tsa 几何/端口单一事实源（mm 入参 → 布局字面量表；
    antenna2 _ant2_layout 同构，纯几何无网格依赖）。"""
    w_throat = float(params.get("w_throat_mm",
                                VIVALDI_NOMINAL["w_throat_mm"]))
    w_mouth = float(params.get("w_mouth_mm",
                               VIVALDI_NOMINAL["w_mouth_mm"]))
    l_mm = float(params.get("l_mm", VIVALDI_NOMINAL["l_mm"]))
    feed_w = float(params.get("feed_w_mm", VIVALDI_NOMINAL["feed_w_mm"]))
    for name, value in (("w_throat_mm", w_throat), ("w_mouth_mm", w_mouth),
                        ("l_mm", l_mm), ("feed_w_mm", feed_w)):
        if not (math.isfinite(value) and value > 0.0):
            raise ValueError(f"vivaldi_layout: {name} 必须为正有限，"
                             f"得到 {value!r}")
    if w_mouth <= w_throat:
        raise ValueError(
            f"vivaldi_layout: 口面宽 {w_mouth:.4g} ≤ 喉宽 {w_throat:.4g}"
            "（指数张开律）")
    y_throat = -l_mm / 2.0
    y_mouth = l_mm / 2.0
    for name, value in (("喉部", y_throat), ("口面", y_mouth)):
        if abs(value) > 60.0 - _VIVALDI_EDGE_STANDOFF_MM:
            raise ValueError(
                f"vivaldi_layout: {name} {value:.4g}mm 越出板缘 MUR 净距 "
                f"{_VIVALDI_EDGE_STANDOFF_MM}mm 守卫（|y|≤"
                f"{60.0 - _VIVALDI_EDGE_STANDOFF_MM}）")
    k = vivaldi_taper_k_per_mm(w_throat, w_mouth, l_mm)
    y_feed = y_throat + 1.0
    hw_feed = vivaldi_slot_half_width_mm(y_feed - y_throat, w_throat, k)
    stations_y = [y_throat + l_mm * j / _VIVALDI_N_SEG
                  for j in range(_VIVALDI_N_SEG + 1)]
    stations_hw = [vivaldi_slot_half_width_mm(y - y_throat, w_throat, k)
                   for y in stations_y]
    f_low = vivaldi_low_cutoff_ghz(w_mouth)
    if not f_low > 0.0:
        raise ValueError("vivaldi_layout: 低截止非正（内核异常）")
    return {"w_throat": w_throat, "w_mouth": w_mouth, "l_mm": l_mm,
            "feed_w": feed_w, "k_per_mm": k, "y_throat": y_throat,
            "y_mouth": y_mouth, "y_feed": y_feed, "hw_feed": hw_feed,
            "stations_y": stations_y, "stations_hw": stations_hw,
            "f_low_ghz": f_low}


def _vivaldi_lines(p: dict[str, Any]) -> str:
    # Vivaldi 几何段（layout 纯函数直调，antenna2 _ant2_body 同构）：
    # 阶梯化地面（槽区按站恒宽近似指数律）+ 顶面跨槽微带馈线 + 双 MSLPort。
    # 布局为 mm 口径（_ant2_layout 同款）——全部字面量经 m() 转米
    # （#140 单位口径家族；缺转=盒子画到 ±40"米"，2026-10-03 本席实测）。
    lay = vivaldi_layout(p)

    def m(v: float) -> str:
        return repr(float(v) * 1e-3)

    stations = list(zip(lay["stations_y"][:-1], lay["stations_y"][1:],
                        lay["stations_hw"][:-1], strict=True))
    gnd_boxes: list[str] = []
    for j, (ya, yb, hw) in enumerate(stations):
        gnd_boxes.append(
            f'vivaldi_gnd.AddBox((-BOARD, {m(ya)}, 0.0), ({m(-hw)}, {m(yb)}, '
            f'0.0), priority=10)  # stair{j}L')
        gnd_boxes.append(
            f'vivaldi_gnd.AddBox(({m(hw)}, {m(ya)}, 0.0), (BOARD, {m(yb)}, '
            f'0.0), priority=10)  # stair{j}R')
    gnd_tail = (
        f'vivaldi_gnd.AddBox((-BOARD, {m(lay["y_mouth"])}, 0.0), '
        f'(BOARD, BOARD, 0.0), priority=10)  # 口面外地（截断口径）')
    hw_feed_m = lay["hw_feed"] * 1e-3
    y_feed_m = lay["y_feed"] * 1e-3
    feed_half_m = lay["feed_w"] * 1e-3 / 2
    return f'''# ── Vivaldi 端射张口槽线几何（layout 单源字面量，米；AP-11）──
HW_FEED = {hw_feed_m!r}       # 馈电点槽半宽（w(y_feed)/2，米）
vivaldi_gnd = CSX.AddMetal("vivaldi_gnd")
{chr(10).join(gnd_boxes)}
{gnd_tail}
# 50Ω 微带馈线（z=H_SUB 顶面，沿 x 跨槽于 y=y_feed；slot 模板跨槽耦合
# 已证机理；巴伦=独立馈电件留登记注记不做）
vivaldi_feed = CSX.AddMetal("vivaldi_feed")
vivaldi_feed.AddBox((-BOARD, {y_feed_m - feed_half_m!r}, H_SUB),
                    (BOARD, {y_feed_m + feed_half_m!r}, H_SUB),
                    priority=10)
# 上游 MSLPort 检查要求 start/stop 三分量全不等（ports.py:264）——stop 的
# y 分量取馈线缘（馈段语义：自板边金属面跨到对侧馈缘，slot 模板同构转置）
_port1 = MSLPort(CSX, port_nr=1, metal_prop=vivaldi_feed,
                 start=np.array([-BOARD, {y_feed_m!r}, H_SUB]),
                 stop=np.array([BOARD, {y_feed_m - 2 * feed_half_m!r}, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - {hw_feed_m * 2!r}) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=vivaldi_feed,
                 start=np.array([BOARD, {y_feed_m!r}, H_SUB]),
                 stop=np.array([-BOARD, {y_feed_m + 2 * feed_half_m!r}, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - {hw_feed_m * 2!r}) / 3, priority=10)
for _prim in vivaldi_gnd.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in vivaldi_feed.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''

VIVALDI_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（跨槽耦合馈；|S11| 谷=槽线模"
                  "建立判读，f_low 由口面半波准则预声明）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_throat_mm", "w_mouth_mm", "l_mm", "feed_w_mm"],
    "topology": "Vivaldi 端射张口槽线天线（AP-11）：有限地面 z=0 带指数"
                "张口槽（喉部 y=−L/2 向口面 y=+L/2 指数张开，阶梯化栅格"
                "化），基板上覆、顶面 50Ω 微带跨槽馈（slot 模板已证机理；"
                "巴伦=独立馈电件留登记注记）；双 MSLPort 板边入（prop_dir=x）",
    "param_semantics": "w_throat_mm=喉部槽宽（Gibson 1979 指数律 w(x)="
                       "w_throat·exp(kx)）、w_mouth_mm=口面槽宽（低截止"
                       "f_low=c/(2·w_mouth) 口面半波准则，名义 24.982705mm↔"
                       "6GHz）、l_mm=喉→口面轴向长（k=ln(w_mouth/w_throat)"
                       "/L，板缘 MUR 净距 ≥5mm 守卫）、feed_w_mm=跨槽微带"
                       "馈线宽（50Ω HJ 1.1134）；er/tan_d 走 substrate/nominal",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "阶梯化站缘 x 向 + 馈线缘精确入网（#198）；底 MUR+域 z 下延"
                 "（slot 同款：槽向下半空间辐射）；显式近场线 10µm 地板（#349）",
    "smoke_note": "离线审计先行（#212，test_ta_wave_b_templates）；内核数字"
                  "裁判=指数律往返恒等+口面↔截止双向回收+单调性（core/"
                  "vivaldi_tsa tests 钉）；近似级别如实登记：低截止=二手工程"
                  "准则（Yngvesson 1985 介质加载修正未回原文不入码，citation-"
                  "rot），巴伦面未做（登记注记），增益/方向图全波面不在本批；"
                  "真机冒烟与 HFSS 仲裁属后续批次（本批零发射）",
}

VIVALDI_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c）：vivaldi_tsa_design(f_low=6GHz, w_throat=0.3,
    # l=80) → w_mouth=c/(2·6GHz)=24.982705（6 位舍入，回代 6.000000GHz
    # 逐位；k=ln(24.982705/0.3)/80=0.05527695729/mm，test 按链复算逐键钉）。
    "w_throat_mm": 0.3, "w_mouth_mm": 24.982705, "l_mm": 80.0,
    "feed_w_mm": float(HAIRPIN_50OHM_W_MM), "er": 3.66, "tan_d": 0.0037,
}


# ═══ 注册（同对象注册钉死单一事实源；尾部追加——#247 契约：追加不改旧行）═══
TEMPLATE_META["isl_shielded"] = ISL_META
TEMPLATE_NOMINAL["isl_shielded"] = ISL_NOMINAL
TEMPLATE_META["vivaldi_tsa"] = VIVALDI_META
TEMPLATE_NOMINAL["vivaldi_tsa"] = VIVALDI_NOMINAL


def isl_shielded_meta() -> dict[str, Any]:
    """返回 isl_shielded 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(ISL_META)
    meta["template"] = "isl_shielded"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(ISL_NOMINAL)
    return meta


def vivaldi_tsa_meta() -> dict[str, Any]:
    """返回 vivaldi_tsa 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(VIVALDI_META)
    meta["template"] = "vivaldi_tsa"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(VIVALDI_NOMINAL)
    return meta
