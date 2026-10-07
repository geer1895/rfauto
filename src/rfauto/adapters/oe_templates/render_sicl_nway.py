"""TA-3 SICL 基片集成同轴线 + TA-4 N-way Wilkinson 功分器（TA 批第二批，2026-10-02）。

方案锚：研究扩充 round15 §二·2 TA-3/TA-4——
「内核就绪缺模板」件：闭式全套在 core（sicl_line.sicl_closed_form /
synthesize_nway_wilkinson），本模块只做几何渲染注册与名义设计链（#1c：
数值全部内核精算，零手抄毫米数；本文件零物理数字产出——铁律 7）。

── TA-3 sicl（基片集成同轴线均匀段，2 端口）──────────────────────────────
器件=矩形同轴腔：上下地板（域 z 边界 PEC + 显式零厚板，siw 同款）+ 两列
接地过孔墙（x=±a/2 过孔中心线距=a，腔高 b=H_SUB）+ 零厚度内导体条带
（w，中面 z=b/2）——准 TEM 主模。设计链=core.sicl_line.sicl_closed_form
（Gatti 2006 开山口径的屏蔽带状线共形闭式族：Howe/Cristal-Gunston 矩形
同轴，UNVERIFIED-1 如实登记见内核 docstring；本模块不抄原文常数）：
- 名义设计点：Z0=50Ω @2.5GHz、a/b=2.5（声明域 [1.5,4] 中档）、均匀介质
  εr=3.66（h_frac=None，RO4350B 双板腔 b=1.016=2×0.508，stripline 同源）、
  t=0 零厚带——内导体宽 w 对 Z0 目标 brentq 反解（设计链消费闭式反函数，
  回代自洽 1e-9 钉住）；w/b=0.545∈[0.3,0.9]、gap/b=0.977≥0.5、t/b=0：
  全部落 FD 裁判声明域（SiclResult.in_referee_band=True，εeff=εr TEM）；
- 过孔墙按 SIW 经验迁移（内核 docstring 登记面）：d=0.6、s=1.0（siw 同源
  档，s/d=1.667≤2、d<λ_sub/5），渲染守卫 d≥4·NEAR + 孔间缝>NEAR（#311
  先例口径）+ 显式近场线 10µm 地板（#349）；
- 端口=双 StripLinePort（v0.37 一等支持，height=b/2=带-地半高对称电压
  探针，suspended_stripline 同法）——β 金标准可用（εeff 锚），|S11| 带谷
  =Z0 锚（cps 口径；名义反解 Z0=50 故 ref=50 逐字节 footer 不变）；
- 域：x 半宽=a/2+边距（过孔墙外平行板区 MUR 吸收，siw 泄漏尾截断同理）、
  y 半宽=line_len/2+14·BASE（端口面出 PML_8，msl_siw_taper 同款）——
  矩形域 DOM_X/DOM_Y 字面注入（BOARD 共享字面量不适用，siw 同口径）。

── TA-4 nway_wilkinson（N=4 树形 Wilkinson 功分器，5 端口）────────────────
器件=1 分 4 树形功分器：两级经典 2-way 单元级联（内核
synthesize_nway_wilkinson(n=4, topology="tree")：每级臂 √2·Z0=70.7107Ω、
隔离 R=2·Z0=100Ω，2 级 6 臂 3 电阻）+ 各臂 λ/4（HJ 链精算）+ 端口全 50Ω。
拓扑选择（渲染面，如实登记）：内核 star（Pon 1961 星形，臂 √N·Z0、N 支
R=Z0 接公共浮点节点）在单层板上对 N≥3 不可布——三个臂端被辐射臂+输出
馈线分隔，浮点节点/等效 Δ 环的任一闭合路径必与边界馈线交叉（单层无跨
接）；N=3 的 Y↔Δ 三端精确变换（R_Δ=3·Z0）同样受环闭合阻塞。故渲染取
内核 tree 分支（阻抗级同源消费），两级同构 2-way 单元全轴对齐零交叉；
N=2 退化为经典 2-way（与既有 wilkinson 模板同解，不重复注册）、N≥8
（9 端口）超本批轮转管线规模——渲染守卫显式拒 n_way≠4 不静默兜底。
- 名义设计点：Z0=50 → arm_z=√2·Z0=70.7107（内核单源）→ HJ 线宽
  0.6035mm（gysel 同源档）、λ/4=18.1624mm（εeff=2.72456）；隔离 R=100Ω
  （LumpedElement 值，qwt z_load_ohm 同口径豁免导体签名）；
- 布局：输入馈线（port1，−BOARD 板边）→ 一级 T 叉（双臂 x 向并列，间距
  9mm，wilkinson GAP 口径放大版）→ 50Ω 支线 → 二级双 T 叉（各叉臂间距
  5.5mm）→ 四路 50Ω 输出馈线（port2..5，+BOARD 板边）；隔离电阻在各臂
  端面跨接（LumpedElement ny=0，wilkinson 同法）；全金属同层零交叉；
- 5 端口整 S 矩阵：进程隔离激励轮转 5 run（#208 口径推广，rotation 管线
  n_ports 参数化），单激励 11 列 CSV（freq + 5×(re,im)，openems_rotation
  _load_round_csv P2⑬ 通用列消费）。

近似级别（如实登记，#122）：sicl=准静态闭式（无色散/零厚带/均匀填充，
FD 裁判 ±5% 声明域，内核登记面）；过孔墙离散化（s=1.0mm 间隔圆柱）对
理想连续壁的等效性未经真机仲裁；nway=λ/4 臂窄带理想口径（T 叉/弯折/
臂端电阻位结点寄生不进闭式裁判，gysel/branchline 同口径）、隔离电阻
LumpedElement 零厚度集总（qwt 端接同法）；真机冒烟与 HFSS 仲裁属后续
批次（本批零发射）。
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from .registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)

# ═══ TA-3 sicl ═══════════════════════════════════════════════════════════

#: 缺省设计点常量（与 TEMPLATE_NOMINAL/design_params 缺省实参同源）
SICL_F0_GHZ = 2.5
SICL_Z0_OHM = 50.0
SICL_A_OVER_B = 2.5          # 外腔宽高比（声明域 [1.5,4] 中档）
SICL_B_MM = 1.016            # 腔高（RO4350B 双板 2×0.508，stripline 同源）
#: 过孔墙边距：域 x 半宽 = a/2 + 本值（过孔墙外平行板泄漏区 MUR 截断）
_SICL_DOM_MARGIN_MM = 2.5
#: 端口段长（×BASE；msl_siw_taper _MSL_SIW_FEED_BASE 同款，#347 断言同式）
_SICL_FEED_BASE = 14.0
#: 显式近场线最小间距地板（#349，siw 同值）
_SICL_MESH_FLOOR_M = 10e-6


SICL_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ StripLinePort 1-2（height=b/2 带-地半高对称探针，"
                  "suspended_stripline 同法）：β 金标准→εeff 对照内核闭式 "
                  "εeff=εr=3.66（均匀填充 TEM，|Δ|≤2% 口径同 stripline 族）；"
                  "|S11| 带谷=Z0 锚（名义反解 Z0=50 故 ref=50；cps 口径）。"
                  "内核裁判=sicl_line.sicl_closed_form（FD 裁判 ±5% 声明域，"
                  "名义点 in_referee_band=True）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "a_mm", "d_mm", "s_mm", "line_len_mm"],
    "topology": "SICL 基片集成同轴线均匀段（TA-3）：矩形同轴腔（上下地板="
                "域 z 边界 PEC+显式零厚板 siw 同款；两列接地过孔墙 x=±a/2、"
                "心距 s、藩篱贯通全域直入 PML=匹配端接 siw v1 口径）+ 零厚度"
                "内导体条带（w，中面 z=b/2=H_SUB/2）；端口=双 StripLinePort"
                "（面贴 ±DOM_Y 域边界 PML_8）；矩形域 DOM_X/DOM_Y 字面注入",
    "param_semantics": "w_mm=内导体条带宽（Z0=50Ω 对 sicl_closed_form 共形"
                       "闭式 brentq 反解，sicl_design_params 单源）；a_mm="
                       "两过孔列心距（外腔宽，a/b=2.5 名义）；d_mm=过孔直径、"
                       "s_mm=过孔心距（SIW 经验迁移 s≤2d、d<λ_sub/5，内核 "
                       "docstring 登记面；siw 同源档 0.6/1.0）；line_len_mm="
                       "条带两端间距；腔高 b=H_SUB=nominal h_mm=1.016"
                       "（RO4350B 双板，stripline 同源）；er/tan_d 只进基板"
                       "材料（MATERIAL_VALUE_PARAMS 豁免）——w 的 Z0 联动仅在"
                       "名义设计点（sicl_design_params），渲染期 er 扰动不改"
                       "导体（slotline/siw 同口径）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
                 "（官方口径）；条带缘/过孔墙三线对（列心±d/2、列心）/条带"
                 "两端/端口面精确入网（#198）；条带中面 z=b/2 落格依赖基板 "
                 "z 偶数格（_sub_cells 缺省 4，生成期断言 #283 口径）；过孔"
                 "直径 ≥4·NEAR + 孔间缝>NEAR（#311 先例口径）守卫；显式近场"
                 "线 10µm 地板（#349）；全轴 1µm 近重合去重（#152）",
    "smoke_note": "未冒烟（离线审计过，#212，test_sicl_nway_templates）；"
                  "近似级别如实登记：①准静态闭式无色散/零厚带/均匀填充"
                  "（内核 FD 裁判 ±5% 声明域，UNVERIFIED-1 公式族归属如实"
                  "登记）；②过孔墙离散化（s=1.0mm 圆柱列）对理想连续壁的"
                  "等效性未经真机仲裁（SIW 经验迁移，内核 docstring 登记"
                  "面）；③StripLinePort 端口段=屏蔽腔内均匀延伸无过渡"
                  "（同 stripline 口径）；真机冒烟与 HFSS 仲裁属后续批次"
                  "（本批零发射）",
}


def sicl_design_params(
    f0_ghz: float = SICL_F0_GHZ,
    z0_ohm: float = SICL_Z0_OHM,
    a_over_b: float = SICL_A_OVER_B,
    b_mm: float = SICL_B_MM,
    eps_r: float = 3.66,
) -> dict[str, Any]:
    """SICL 名义设计点（内核精算单源，#1c——名义值禁手算捷径）。

    设计链：a/b 比选档（声明域 [1.5,4] 中档）→ a=a_over_b·b → 内导体宽 w
    对 sicl_line.sicl_z0 共形闭式 brentq 反解（Z0 目标 50Ω，回代自洽
    |ΔZ0|≤1e-9·Z0 断言）→ 过孔墙 siw 同源档（d=0.6/s=1.0，设计规则复核）。
    恒等式由 test_sicl_nway_templates 综合反解自洽测试钉住（逐键 rtol
    1e-9 对 TEMPLATE_NOMINAL 字面量）。
    """
    from scipy.optimize import brentq

    from rfauto.core.calc_families.slotline_siw import siw_check_design_rules
    from rfauto.core.sicl_line import sicl_closed_form, sicl_z0

    a_mm = float(a_over_b) * float(b_mm)
    w_mm = brentq(
        lambda w: sicl_z0(w, a_mm, float(b_mm), 0.0, float(eps_r), None)
        - float(z0_ohm),
        1e-3 * float(b_mm), 0.99 * float(b_mm), xtol=1e-12)
    # 反解回代自洽（未舍入值，brentq 质量门 1e-9 相对）
    z_chk = sicl_z0(w_mm, a_mm, float(b_mm), 0.0, float(eps_r), None)
    if abs(z_chk - float(z0_ohm)) > 1e-9 * float(z0_ohm):
        raise ValueError(
            f"sicl_design_params: 反解回代不自洽 |ΔZ0|={abs(z_chk - z0_ohm):.4g}Ω"
            f"（Z0={z_chk:.9f} vs {z0_ohm}）")
    # 4 位舍入回代（字面量落表档；ΔZ0=4 位舍入固有，门 1e-4 相对=0.005Ω）
    res = sicl_closed_form(round(w_mm, 4), a_mm, float(b_mm), 0.0,
                           float(eps_r), None)
    if abs(res.z0_ohm - float(z0_ohm)) > 1e-4 * float(z0_ohm):
        raise ValueError(
            f"sicl_design_params: 4 位舍入回代 |ΔZ0|="
            f"{abs(res.z0_ohm - z0_ohm):.4g}Ω 超 1e-4 相对门"
            f"（Z0={res.z0_ohm:.6f} vs {z0_ohm}）")
    # 过孔墙 SIW 经验迁移设计规则复核（内核 docstring 登记面口径；siw 单源）
    siw_check_design_rules(a_mm, 0.6, 1.0, float(eps_r), freq_ghz=float(f0_ghz))
    return {
        "w_mm": round(float(w_mm), 4),
        "a_mm": round(float(a_mm), 6),
        "d_mm": 0.6,
        "s_mm": 1.0,
        "line_len_mm": 40.0,
    }


#: 名义设计点（2026-10-02 由 sicl_design_params() 缺省实参精算，字面量落表
#: 避免模块导入期 IO；逐位一致性由自洽测试钉住）：a/b=2.5 → a=2.54mm；
#: Z0=50Ω 反解 w=0.55395262mm（共形模数 k=0.71901068）→ 4 位舍入 0.5540
#: 回代 Z0=49.9976Ω（−0.0024Ω，4 位舍入固有，如实登记）；w/b=0.5452、
#: gap/b=0.9774、t/b=0：FD 裁判声明域内（in_referee_band=True）；εeff=εr
#: =3.66（均匀填充 TEM）。d/s=0.6/1.0 siw 同源档；h_mm=1.016 腔高
SICL_NOMINAL: dict[str, Any] = {
    "w_mm": 0.554,
    "a_mm": 2.54,
    "d_mm": 0.6,
    "s_mm": 1.0,
    "line_len_mm": 40.0,
    "h_mm": 1.016,
    "er": 3.66,
    "tan_d": 0.0037,
}


def sicl_layout(params: dict[str, Any], freq_range_ghz: tuple[float, float],
                base_m: float, h_m: float) -> dict[str, Any]:
    """sicl 几何/端口/域单一事实源（mm 入参 → 米字面量 + 守卫）。

    所有派生量（域 DOM_X/DOM_Y/过孔栅格/近场线集）在此一次计算，body/
    近场线/机制分支（DOM 注入、z 网格、基板块）同源消费——#198/#212 单源
    纪律。网格欠分辨/显式线近撞显式 ValueError 拒渲染。
    """
    w = float(params.get("w_mm", 0.554)) * 1e-3
    a = float(params.get("a_mm", 2.54)) * 1e-3
    d = float(params.get("d_mm", 0.6)) * 1e-3
    s = float(params.get("s_mm", 1.0)) * 1e-3
    line_len = float(params.get("line_len_mm", 40.0)) * 1e-3
    for label, v in (("w_mm", w), ("a_mm", a), ("d_mm", d), ("s_mm", s),
                     ("line_len_mm", line_len)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(
                f"sicl_layout: {label} 必须为正有限，得到 {v!r}")
    if not w < a:
        raise ValueError(
            f"sicl_layout: 内导体宽 w={w * 1e3:.4g}mm 须小于外腔宽 "
            f"a={a * 1e3:.4g}mm（sicl_line 同款前提）")
    if not (math.isfinite(base_m) and base_m > 0.0 and math.isfinite(h_m)
            and h_m > 0.0):
        raise ValueError(
            f"sicl_layout: base/h 必须为正有限，得到 ({base_m!r}, {h_m!r})")
    near = base_m / 4.0
    # 过孔可分辨守卫（siw 同款）：直径 ≥4·NEAR
    if not d >= 4.0 * near:
        raise ValueError(
            f"sicl_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm）")
    # 孔间缝渲染守卫（#311 先例口径，siw 共用判据）：s−d 须 > NEAR
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"sicl_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm）——缝内零内部"
            "网格线（#311 先例口径：SmoothMesh 不细分 ≤NEAR 区间），过孔墙"
            f"泄漏建模粗；收紧 mesh_resolution_mm ≤ "
            f"{4.0 * via_gap * 1e3:.4g}mm 或加大 s−d（设计规则域内）")
    # 域：x 半宽=墙外平行板泄漏区截断；y 半宽=端口面出 PML_8（14·BASE）
    feed_len = _SICL_FEED_BASE * base_m
    dom_x = a / 2.0 + _SICL_DOM_MARGIN_MM * 1e-3
    y0 = -line_len / 2.0
    y1 = line_len / 2.0
    port_inset = feed_len
    dom_y_min = line_len / 2.0 + port_inset
    k_half = math.ceil(dom_y_min / s - 1e-9)
    dom_y = max(dom_y_min, k_half * s + d / 2)
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    # #347：StripLinePort 测量面（feed_len/3）与 FeedShift（10·NEAR）间距
    # ≥3.9·NEAR（msl_siw_taper 同式；14·BASE 档下恒 2.1667·BASE，留余量）
    if not feed_len / 3.0 - 10.0 * near >= 3.9 * near:
        raise ValueError(
            f"sicl_layout: MeasPlaneShift/FeedShift 间距 "
            f"{(feed_len / 3.0 - 10.0 * near) * 1e6:.1f}µm < 3.9·NEAR（#347；"
            "加大 _SICL_FEED_BASE）")
    # 显式近场线集（与 _near_points 注入同源）最小间距地板（#349，siw 同款；
    # 共享缘去重后核——条带端面落过孔心线（line_len 整倍 s）是合法重合）
    x_lines = [0.0, w / 2, -w / 2,
               a / 2 - d / 2, a / 2, a / 2 + d / 2,
               -(a / 2 - d / 2), -a / 2, -(a / 2 + d / 2)]
    y_lines = [y0, y1]
    for _yk in via_y:
        y_lines += [_yk - d / 2, _yk, _yk + d / 2]

    def _dedup(vs: list[float]) -> list[float]:
        out: list[float] = []
        for v in sorted(vs):
            if not out or v - out[-1] > 1e-6:
                out.append(v)
        return out

    for _name, _lines in (("x", x_lines), ("y", y_lines)):
        _arr = _dedup(_lines)
        _gaps = [b - a2 for a2, b in pairwise(_arr)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _SICL_MESH_FLOOR_M:
            raise ValueError(
                f"sicl_layout: {_name} 向显式网格线最小间距 "
                f"{_gmin * 1e6:.3f}µm ≤ {_SICL_MESH_FLOOR_M * 1e6:.0f}µm "
                "地板（#349 CFL 塌缩守卫；条带缘/过孔栅格近撞，调整 "
                "w/a/d/s）")
    return {"w": w, "a": a, "d": d, "s": s, "h": h_m,
            "line_len": line_len, "near": near, "feed_len": feed_len,
            "y0": y0, "y1": y1, "dom_x": dom_x, "dom_y": dom_y,
            "k_half": k_half, "via_y": via_y}


def _sicl_lines(p: dict[str, Any]) -> str:
    # SICL 几何段（layout 单源字面量，米）。必须经 render_script 渲染
    # （_sicl_layout 注入）——直调缺布局显式报错（#283 渲染期守卫纪律）。
    lay = p.get("_sicl_layout")
    if lay is None:
        raise ValueError(
            "sicl 几何段缺 _sicl_layout：必须经 render_script 渲染（布局单源"
            "注入）")
    via_y = list(lay["via_y"])
    return f'''# ── sicl 几何（layout 单源字面量，米；round15 TA-3）──
W = {lay["w"]!r}              # 内导体条带宽（Z0=50Ω 共形闭式反解 #1c）
A = {lay["a"]!r}              # 两过孔列心距（外腔宽，a/b=2.5）
D_VIA = {lay["d"]!r}          # 过孔直径（SIW 经验迁移档）
S_PITCH = {lay["s"]!r}        # 过孔心距（全域精确栅格 y_k = k·S_PITCH）
ZC = H_SUB / 2                # 条带中面（z 轴偶数格落格，#283 生成期断言）
Y0 = {lay["y0"]!r}            # 条带近端（port1 侧）
Y1 = {lay["y1"]!r}            # 条带远端（port2 侧）
# 上下地板：显式零厚盒贴 z 边界（与 z 边界 PEC 等电势冗余——板-墙连通图
# 物理化，siw 同款）
sicl_plates = CSX.AddMetal("sicl_plates")
sicl_plates.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)
sicl_plates.AddBox((-DOM_X, -DOM_Y, H_SUB), (DOM_X, DOM_Y, H_SUB), priority=10)
# 内导体条带（零厚度，中面）
sicl_strip = CSX.AddMetal("sicl_strip")
sicl_strip.AddBox((-W / 2, Y0, ZC), (W / 2, Y1, ZC), priority=10)
# 两列接地过孔墙（z∈[0,H_SUB] 贯通；藩篱直入 PML=匹配端接，siw v1 口径）
sicl_via = CSX.AddMetal("sicl_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    sicl_via.AddCylinder([-A / 2, _vy, 0.0], [-A / 2, _vy, H_SUB],
                         radius=D_VIA / 2, priority=10)
    sicl_via.AddCylinder([A / 2, _vy, 0.0], [A / 2, _vy, H_SUB],
                         radius=D_VIA / 2, priority=10)
# 双 StripLinePort（height=b/2=带-地半高对称电压探针，suspended_stripline
# 同法）：端口面=域边界贴 PML_8（#174）、端口段=屏蔽腔内均匀延伸、
# FeedShift=10·NEAR 与 MeasPlaneShift=FEED_LEN/3 间距 #347 断言
FEED_LEN = {lay["feed_len"]!r}
if not FEED_LEN / 3.0 - 10 * NEAR >= 3.9 * NEAR:
    raise SystemExit("sicl #" + "347" + ": "
                     "MeasPlaneShift/FeedShift 间距不足 3.9·NEAR")
_port1 = StripLinePort(CSX, port_nr=1, metal_prop=sicl_strip,
                       start=np.array([W / 2, -DOM_Y, ZC]),
                       stop=np.array([-W / 2, Y0, ZC]),
                       prop_dir="y", exc_dir="z", height=ZC,
                       excite=1, FeedShift=10 * NEAR,
                       MeasPlaneShift=FEED_LEN / 3, priority=10)
_port2 = StripLinePort(CSX, port_nr=2, metal_prop=sicl_strip,
                       start=np.array([-W / 2, DOM_Y, ZC]),
                       stop=np.array([W / 2, Y1, ZC]),
                       prop_dir="y", exc_dir="z", height=ZC,
                       excite=0, FeedShift=10 * NEAR,
                       MeasPlaneShift=FEED_LEN / 3, priority=10)
# 生成期网格守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）+ 条带缘/
# 中面/过孔列心落格断言（#283：盒边=结构线；中面落格依赖 z 偶数格）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("sicl #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _sicl_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", -W / 2), ("x", W / 2),
                ("x", -A / 2), ("x", A / 2),
                ("y", Y0), ("y", Y1),
                ("z", ZC), ("z", 0.0), ("z", H_SUB)):
    if not _sicl_on_line(_ax, _v):
        raise SystemExit("sicl #" + "283" + ": 条带/墙/中面边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")
for _prim in sicl_plates.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in sicl_strip.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in sicl_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ═══ TA-4 nway_wilkinson ═════════════════════════════════════════════════

#: 缺省设计点常量（与 TEMPLATE_NOMINAL/design_params 缺省实参同源）
NWAY_F0_GHZ = 2.5
NWAY_Z0_OHM = 50.0
NWAY_N_WAY = 4
#: 布局常量（mm；一级叉臂间距=wilkinson GAP=8mm 口径放大档——二级叉臂
#: 间距与内对输出馈线 3·h_sub 净空联动核算见 _nway_layout 守卫）
_NWAY_G1_MM = 9.0
_NWAY_G2_MM = 5.5
_NWAY_Y_T1_MM = -45.0         # 一级叉 T 点 y（输入馈线末端）
_NWAY_Y_T2_MM = -10.0         # 二级叉 T 点 y（50Ω 支线末端）


NWAY_WILKINSON_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 5,
    "extraction": "全 S 矩阵 5×5 @ .s5p（进程隔离激励轮转 5 run，#208 口径"
                  "推广；openems_rotation n_ports 参数化；port1=输入、"
                  "port2..5=输出 x=∓(XA1±XA2)）。裁判=内核 "
                  "synthesize_nway_wilkinson(tree) 阻抗级：@f0 均分 "
                  "−6.02dB（1/4 功率）、全端口匹配 |S11| 深谷、输出对隔离"
                  "（每级 R=2·Z0 经典 2-way 单元级联保证）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_arm_mm", "w_feed_mm", "arm_len_mm", "iso_r_ohm"],
    "topology": "N-way Wilkinson 功分器（TA-4，树形 N=4）：输入馈线（port1，"
                "−BOARD 板边）→ 一级 T 叉（双 λ/4 臂 √2·Z0，x 向并列间距 "
                "G1=9mm，wilkinson GAP 口径）→ 50Ω 支线 → 二级双 T 叉（各"
                "叉臂间距 G2=5.5mm）→ 四路 50Ω 输出馈线（port2..5，+BOARD "
                "板边）；隔离电阻 R=2·Z0 各臂端面跨接（LumpedElement ny=0，"
                "共 3 支）；全金属同层零交叉。拓扑选择：内核 star 分支（Pon "
                "1961 浮点节点）单层 N≥3 不可布（浮点节点/Δ 环闭合路径必与"
                "边界馈线交叉）——渲染取内核 tree 分支（阻抗级同源），N=2 "
                "与 wilkinson 模板同解、N≥8 超轮转管线规模（渲染守卫拒 "
                "n_way≠4）",
    "param_semantics": "w_arm_mm=λ/4 臂宽（√2·Z0=70.7107Ω HJ 精算，gysel "
                       "同源档）；w_feed_mm=50Ω 馈线/支线/输出线宽"
                       "（1.1134，mline 同源档）；arm_len_mm=臂 λ/4 长"
                       "（εeff=2.72456 精算 18.1624mm@2.5GHz）；iso_r_ohm="
                       "隔离电阻值（=2·Z0，LumpedElement R 值——进元件值不"
                       "进导体几何，qwt z_load_ohm 同口径豁免）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
                 "（官方口径）；全部盒缘（叉臂带缘/T 条缘/电阻盒边/支线与"
                 "输出馈线缘）+ 端口 junction 精确入网（#198）；显式近场线 "
                 "10µm 地板（#349）；全轴 1µm 近重合去重（#152）；端口面贴 "
                 "PML_8 域边（#154 前节）",
    "smoke_note": "未冒烟（离线审计过，#212，test_sicl_nway_templates）；"
                  "近似级别如实登记：①λ/4 臂窄带理想口径——T 叉/臂端电阻位"
                  "结点寄生不进闭式裁判（gysel/branchline 同口径，离线裁判"
                  "=skrf 理想 2-way 单元级联装配）；②隔离电阻 LumpedElement"
                  " 零厚度集总（qwt 端接同法，寄生 L/C 未建模）；③star 分支"
                  "单层不可布为渲染面拓扑约束（非内核语义变更）；真机冒烟与"
                  " HFSS 仲裁属后续批次（本批零发射）",
}


def nway_wilkinson_design_params(
    f0_ghz: float = NWAY_F0_GHZ,
    z0_ohm: float = NWAY_Z0_OHM,
    n_way: int = NWAY_N_WAY,
) -> dict[str, Any]:
    """N-way 树形功分器名义设计点（内核精算单源，#1c——名义值禁手算捷径）。

    设计链：synthesize_nway_wilkinson(n, topology="tree") 阻抗级（臂
    √2·Z0、隔离 R=2·Z0）→ 各臂 HJ inverse_width 精算线宽 → λ/4 物理长
    （forward_z0 的 εeff 精算）。恒等式由 test_sicl_nway_templates 综合
    反解自洽测试钉住。渲染面 v1 只支持 n_way=4（见 _nway_layout 守卫）。
    """
    from rfauto.core.synthesis import (
        Stackup,
        forward_z0,
        inverse_width,
        synthesize_nway_wilkinson,
    )

    d = synthesize_nway_wilkinson(int(n_way), float(z0_ohm), topology="tree")
    sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
    arm_z = float(d["params"]["arm_z_ohm"])
    w_arm, _, status = inverse_width(arm_z, float(f0_ghz), sub)
    if status != "ok":
        raise ValueError(f"nway_wilkinson 臂宽反解未收敛: {status}")
    w_feed, _, status = inverse_width(float(z0_ohm), float(f0_ghz), sub)
    if status != "ok":
        raise ValueError(f"nway_wilkinson 馈线宽反解未收敛: {status}")
    _, eps_eff = forward_z0(w_arm, float(f0_ghz), sub)
    l_arm = 299792458.0 / (4.0 * float(f0_ghz) * 1e9
                           * math.sqrt(eps_eff)) * 1e3
    return {
        "w_arm_mm": round(float(w_arm), 4),
        "w_feed_mm": round(float(w_feed), 4),
        "arm_len_mm": round(float(l_arm), 4),
        "iso_r_ohm": round(float(d["params"]["isolation_r_ohm"]), 4),
    }


#: 名义设计点（2026-10-02 由 nway_wilkinson_design_params() 缺省实参精算，
#: 字面量落表避免模块导入期 IO；逐位一致性由自洽测试钉住）：N=4 tree →
#: arm_z=√2·Z0=70.7107Ω（内核单源）→ HJ w_arm=0.6035mm（εeff=2.72456 →
#: λ/4=18.1624mm）；w_feed=1.1134（50Ω，mline 同源档）；iso_r=2·Z0=100Ω
NWAY_WILKINSON_NOMINAL: dict[str, Any] = {
    "w_arm_mm": 0.6035,
    "w_feed_mm": 1.1134,
    "arm_len_mm": 18.1624,
    "iso_r_ohm": 100.0,
}


def _nway_layout(p: dict[str, Any]) -> dict[str, Any]:
    """nway_wilkinson 几何单源（mm 入参 → 米制盒清单 + 近场线集 + 守卫）。

    守卫（渲染期显式抛错）：n_way=4（渲染 v1 域）；参数正有限；全金属
    板内（arm_len ×1.37 审计扰动域核算）；相邻输出馈线边距 ≥3·h_sub
    （DC 邻道净空，schiffman 净空口径）；#347 输入段测量面-激励分离；
    显式近场线 10µm 地板（#349）。
    """
    n_way = int(p.get("n_way", NWAY_N_WAY) or NWAY_N_WAY)
    if n_way != 4:
        raise ValueError(
            f"nway_wilkinson: 渲染 v1 只支持 n_way=4（树形两级；N=2 与 "
            f"wilkinson 模板同解、N≥8 超本批轮转管线规模），得到 {n_way}")
    wa_mm = float(p.get("w_arm_mm", NWAY_WILKINSON_NOMINAL["w_arm_mm"]))
    wf_mm = float(p.get("w_feed_mm", NWAY_WILKINSON_NOMINAL["w_feed_mm"]))
    la_mm = float(p.get("arm_len_mm", NWAY_WILKINSON_NOMINAL["arm_len_mm"]))
    for label, v in (("w_arm_mm", wa_mm), ("w_feed_mm", wf_mm),
                     ("arm_len_mm", la_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(
                f"nway_wilkinson: {label} 必须为正有限，得到 {v!r}")
    base_m = float(p.get("_base_mm", 0.4)) * 1e-3
    near_m = base_m / 4.0
    h_m = float(p.get("_h_sub_mm", 0.508)) * 1e-3
    board_m = 60.0 * 1e-3
    wa = wa_mm * 1e-3
    wf = wf_mm * 1e-3
    la = la_mm * 1e-3
    g1 = _NWAY_G1_MM * 1e-3
    g2 = _NWAY_G2_MM * 1e-3
    xa1 = g1 / 2.0 + wa / 2.0        # 一级叉臂中心 x（±）
    xa2 = g2 / 2.0 + wa / 2.0        # 二级叉臂中心 x（相对叉心 ±）
    y_t1 = _NWAY_Y_T1_MM * 1e-3
    y_e1 = y_t1 + la
    y_t2 = _NWAY_Y_T2_MM * 1e-3
    y_e2 = y_t2 + la
    # 板内守卫（arm_len ×1.37 审计扰动域核算：底=T1、顶=二级叉末端+臂半宽）
    if y_t1 <= -board_m + 4.0 * near_m:
        raise ValueError(
            f"nway_wilkinson: 一级叉 T 点 y={y_t1 * 1e3:.3f}mm 越板边余量 "
            f"(≥{-board_m * 1e3 + 4.0 * near_m * 1e3:.3f}mm)——上移 _NWAY_Y_T1_MM")
    if y_e2 + wa / 2.0 >= board_m - 4.0 * near_m:
        raise ValueError(
            f"nway_wilkinson: 二级叉末端 y={y_e2 * 1e3:.3f}mm 越板边余量 "
            f"(≤{board_m * 1e3 - 4.0 * near_m * 1e3:.3f}mm)——缩短 arm_len_mm")
    # 相邻输出馈线边距 ≥3·h_sub（DC 邻道净空；最紧=内对输出 x=±(XA1−XA2)）
    inner_gap = 2.0 * (xa1 - xa2) - wf
    if inner_gap < 3.0 * h_m:
        raise ValueError(
            f"nway_wilkinson: 内对输出馈线边距 {inner_gap * 1e3:.3f}mm < "
            f"3·h_sub={3.0 * h_m * 1e3:.3f}mm——加大 G1 或缩小 G2")
    # #347：输入段测量面（(Y_T1+BOARD)/3）与 FeedShift（10·NEAR）分离
    meas1 = (y_t1 + board_m) / 3.0
    if not meas1 - 10.0 * near_m >= 3.9 * near_m:
        raise ValueError(
            f"nway_wilkinson: 输入段 MeasPlaneShift/FeedShift 间距 "
            f"{(meas1 - 10.0 * near_m) * 1e6:.1f}µm < 3.9·NEAR（#347；"
            "粗网格档收紧 mesh_resolution_mm 或下移 _NWAY_Y_T1_MM）")
    # ── 盒清单（米；(x0, y0, x1, y1)，z=H_SUB 零厚）───────────────────────
    # 输入/输出 50Ω 馈线由 MSLPort 自动补画（wilkinson 同口径，不画实体盒）；
    # 盒清单=T 条/臂/支线导体实体。
    boxes: list[tuple[str, float, float, float, float]] = []
    # 一级 T 条 + 双臂
    boxes.append(("t1_bar", -xa1 - wa / 2.0, y_t1, xa1 + wa / 2.0, y_t1 + wa))
    boxes.append(("arm1_up", -xa1 - wa / 2.0, y_t1, -xa1 + wa / 2.0, y_e1))
    boxes.append(("arm1_dn", xa1 - wa / 2.0, y_t1, xa1 + wa / 2.0, y_e1))
    # 50Ω 支线（臂端→二级叉）
    boxes.append(("branch_up", -xa1 - wf / 2.0, y_e1, -xa1 + wf / 2.0, y_t2))
    boxes.append(("branch_dn", xa1 - wf / 2.0, y_e1, xa1 + wf / 2.0, y_t2))
    # 二级双 T 条 + 各双臂（叉心 xc=±XA1）
    for tag, sgn in (("u", -1.0), ("d", 1.0)):
        xc = sgn * xa1
        boxes.append((f"t2_{tag}", xc - xa2 - wa / 2.0, y_t2,
                      xc + xa2 + wa / 2.0, y_t2 + wa))
        boxes.append((f"arm2_{tag}a", xc - xa2 - wa / 2.0, y_t2,
                      xc - xa2 + wa / 2.0, y_e2))
        boxes.append((f"arm2_{tag}b", xc + xa2 - wa / 2.0, y_t2,
                      xc + xa2 + wa / 2.0, y_e2))
    # 隔离电阻盒（LumpedElement ny=0；一级 1 支 x∈[±G1/2]、二级 2 支）
    res_boxes = [
        ("res1", -g1 / 2.0, y_e1 - wa / 2.0, g1 / 2.0, y_e1 + wa / 2.0),
    ]
    for tag, sgn in (("u", -1.0), ("d", 1.0)):
        xc = sgn * xa1
        res_boxes.append((f"res2_{tag}", xc - g2 / 2.0, y_e2 - wa / 2.0,
                          xc + g2 / 2.0, y_e2 + wa / 2.0))
    out_x = sorted({-(xa1 + xa2), -(xa1 - xa2), xa1 - xa2, xa1 + xa2})
    # 近场线集：全部盒缘 + 输入/输出馈线带缘精确入网（#198；共享缘去重后
    # #349 地板守卫——电阻盒边=臂缘同线是常态，不去重即假红）
    near_x = [-wf / 2.0, wf / 2.0]
    for xo in out_x:
        near_x += [xo - wf / 2.0, xo + wf / 2.0]
    near_y: list[float] = []
    for _nm, x0, yy0, x1, yy1 in [*boxes, *res_boxes]:
        near_x += [x0, x1]
        near_y += [yy0, yy1]

    def _dedup(vs: list[float]) -> list[float]:
        out: list[float] = []
        for v in sorted(vs):
            if not out or v - out[-1] > 1e-6:
                out.append(v)
        return out

    for _name, _lines in (("x", near_x), ("y", near_y)):
        _arr = _dedup(_lines)
        _gaps = [b - a2 for a2, b in pairwise(_arr)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > 10e-6:
            raise ValueError(
                f"nway_wilkinson: {_name} 向显式网格线最小间距 "
                f"{_gmin * 1e6:.3f}µm ≤ 10µm 地板（#349 CFL 塌缩守卫；"
                "布局常量/臂宽近撞，调整 G1/G2/Y_T*）")
    return {
        "wa": wa, "wf": wf, "la": la,
        "xa1": xa1, "xa2": xa2, "g1": g1, "g2": g2,
        "y_t1": y_t1, "y_e1": y_e1, "y_t2": y_t2, "y_e2": y_e2,
        "board": board_m, "iso_r": float(p.get(
            "iso_r_ohm", NWAY_WILKINSON_NOMINAL["iso_r_ohm"])),
        "boxes": boxes, "res_boxes": res_boxes,
        "out_x": out_x,
        "near_x": _dedup(near_x), "near_y": _dedup(near_y),
    }


def _nway_lines(p: dict[str, Any]) -> str:
    # N-way 树形功分器几何段（layout 单源盒清单字面量注入，米）。
    # 五端口激励轮转（#208 推广）：excite 由渲染器注入的 _excite_port 参数化。
    lay = _nway_layout(p)
    metal_txt = ""
    for nm, x0, y0, x1, y1 in lay["boxes"]:
        metal_txt += (f"nway.AddBox(({x0!r}, {y0!r}, H_SUB), "
                      f"({x1!r}, {y1!r}, H_SUB), priority=10)   # {nm}\n")
    res_txt = ""
    for nm, x0, y0, x1, y1 in lay["res_boxes"]:
        res_txt += (f"_r = CSX.AddLumpedElement(\"{nm}\", ny=0, caps=True, "
                    f"R=ISO_R)\n_r.AddBox(({x0!r}, {y0!r}, H_SUB), "
                    f"({x1!r}, {y1!r}, H_SUB), priority=5)   # {nm}\n")
    y_t1 = lay["y_t1"]
    y_e2 = lay["y_e2"]
    wf = lay["wf"]
    board = lay["board"]
    ports_txt = ""
    # port1 输入（−BOARD 板边）
    ports_txt += f'''_port1 = MSLPort(CSX, port_nr=1, metal_prop=nway,
                 start=np.array([{wf / 2.0!r}, -BOARD, H_SUB]),
                 stop=np.array([{-wf / 2.0!r}, {y_t1!r}, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == 1 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=({y_t1!r} + BOARD) / 3, priority=10)
'''
    # port2..5 输出（+BOARD 板边，x=∓(XA1±XA2) 排序）
    for k, xo in enumerate(lay["out_x"], start=2):
        ports_txt += f'''_port{k} = MSLPort(CSX, port_nr={k}, metal_prop=nway,
                 start=np.array([{xo + wf / 2.0!r}, {board!r}, H_SUB]),
                 stop=np.array([{xo - wf / 2.0!r}, {y_e2!r}, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == {k} else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - {y_e2!r}) / 3, priority=10)
'''
    return f'''# ── nway_wilkinson 几何（layout 单源字面量，米；round15 TA-4）──
ISO_R = {lay["iso_r"]!r}       # 隔离电阻（=2·Z0，LumpedElement R 值）
nway = CSX.AddMetal("nway_wilkinson")
{metal_txt}{res_txt}# 五端口激励轮转（#208 推广）：主 run 仅端口 ep 激励，其余探针
_PORT_EP = {int(p.get("_excite_port", 1) or 1)}
{ports_txt}# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in nway.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 注册：同对象入表（单一事实源；尾部追加 #247 键集口径）─────────────────
TEMPLATE_META["sicl"] = SICL_META
TEMPLATE_NOMINAL["sicl"] = SICL_NOMINAL
_TEMPLATE_PORT_AXES["sicl"] = ("y",)
_TEMPLATE_RADIATOR["sicl"] = False

TEMPLATE_META["nway_wilkinson"] = NWAY_WILKINSON_META
TEMPLATE_NOMINAL["nway_wilkinson"] = NWAY_WILKINSON_NOMINAL
_TEMPLATE_PORT_AXES["nway_wilkinson"] = ("y",)
_TEMPLATE_RADIATOR["nway_wilkinson"] = False
