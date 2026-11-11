"""layered_stack 族 openEMS 整脚本渲染器（T-Q26d 批 1，aurora_q 席位 Q-X4）。

来源：晶圆键合空腔传输线外部用户实测反馈 §3.4 P1（模板族提案）+ §2.1
实测锚 + §2.2/§2.3 建模约定。族拓扑=**晶圆键合/SIW/SICL/空气腔悬置线**：
多层叠层（中间片载线）+ 挖腔（上下片腔体）+ 腔壁金属化 + 波端口落腔体
截面。布局单一事实源=:func:`rfauto.adapters.layered_stack_spec.
layered_stack_layout`（本模块零几何独立计算——分段/端口/特征线全消费
布局，#198/#212 单源纪律）。

结构（名义 spec=反馈 §3.4 示例 + §2.1 实测锚，米制渲染）：
- 叠层（带面系 z=0=导体层顶面）：介质层=材料盒（分层围合分段——腔足印
  内非导体层挖除，导体层完整横跨）；金属键合层（gold）=**零厚 PEC
  sheet**（片平面=层界面中已入网格的那一面——3µm 次胞体积盒在 FDTD
  网格中心采样下可能整层丢失，sheet 落格确定性；HFSS 侧同层用实体盒
  保厚度，见 hfss_builder_layered 模块头）；
- 腔壁金属化：四壁零厚 PEC sheet（两端截面口不金属化——端口须见腔
  截面；3µm 涂层 RF 等效 PEC，与 HFSS 侧同口径）；
- strip：导体层顶面零厚 PEC 片（体段 x∈[−L/2,L/2]）；
- 端口：双 **StripLinePort**（v0.37 一等支持，suspended_stripline/sicl
  同法：prop_dir="x"、exc_dir="z"、height=带面-腔顶壁距离——spec 校验
  器已锁腔关于带面对称，上下探针 ±height 等效）——β 金标准可用；
- 馈段（匹配端接口径，siw v1「藩篱直入 PML」同源）：腔管截面（膜片
  足迹修至腔宽+四壁+带）自 ±L/2 延续至 ±DOM_X 直入 PML_8——馈区截面
  =腔截面（Exact match），端口测面经 MeasPlaneShift=FEED/3 退嵌。
  四壁延续（Q-X14 Fix1，qx12 调查 RC1 修复）：逐面消费
  ``lay["metal_sheets"]`` 壁盒 (y,z) 字面单源直通（铁律 7：零几何独立
  计算），x 重定到 [−DOM_X,−L_HALF]∪[L_HALF,DOM_X] 发射 2×N 壁延续盒
  （strip 体段不在 metal_sheets——馈段 strip 由 StripLinePort 自画）；
  网格零改动（壁面 y/z 与 ±L_HALF/±DOM_X 全是既有特征线）。渲染端
  fail-loud 守卫（Q-X14 Fix2）：壁延续存在性自检+StripLinePort 探针面
  （x=±(DOM_X−MeasPlaneShift)）z=STRIP_Z±PORT_HEIGHT 地平面金属覆盖
  断言（qx12 probe_plane_check.py 静态判据收编——修复前探针面金属
  命中=0 即 RC1 形态，ValueError 拒绝渲染）。
  **与 HFSS 侧结构性差异如实登记**：HFSS=精确键合体（止于 ±L/2、波
  端口落腔端截面，§2.1 实测形态），openEMS=匹配馈延续（跨引擎仲裁
  属批 2 锚判读，两端口径各自成立）；
- 域：x=±DOM_X=±(L/2+16·BASE)（PML_8 两端）；y/z=结构外 8·BASE（MUR
  ——腔壁金属化封闭横向，泄漏≈0，取 PML 同量级数值裕量）；
- 网格：特征线（带面/膜面/腔壁面/带缘/壁缘/晶圆缘/结构端面）显式入网
  （#198）+ 次胞界面剔除（#349 地板：与必需面 <10µm 的非必需面不入
  网——3µm 键合层界面/叠层顶与腔顶壁 3µm 近撞族）+ x/y NEAR、z BASE
  平滑（mim_cap 同款次序）+ 特征线保护式 #152 去重（1µm 全轴）+
  生成期全轴最小间距与落格断言（#283）。

锚（铁律 7：数值全内核/实测出处，零手抄）：
- 名义几何=§3.4 示例值 + §2.1（line_len=5.1）/§5（wafer_width=1.2、
  频带 85-105GHz）实测锚——全部在 spec 缺省值声明（layered_stack_spec
  模块 docstring 出处表）；
- 闭式锚：core.calculators._suspended_stripline_ri（facade 消费，
  §2.1 同参调用 (w=0.52, b=0.50, h=0.05, εr=11.9)→εeff≈1.59/Z0≈50.2，
  HFSS 实测 |S11|max=−23.5dB 背书 50Ω 点）——嵌入脚本 meta json 供
  判读；如实登记：闭式假设膜对称居中，本族膜在带下单侧（薄膜二阶
  近似，§2.1 经验锚非严格推导）；腔宽 0.9mm 有限壁 vs 无限平面假设
  同属近似面（批 2 真机判读）。
- 网格自动档：base=λ_sub/50@F_MAX（最高 εr 介质材料波长，SIW/sicl
  同口径字符串）；NEAR=base/4；#266 特征分辨守卫 NEAR ≤ strip 宽/3。

批 1 边界（如实登记）：未注册 TEMPLATE_META（#304 五表连锁留批 2），
本渲染器为独立整脚本入口（mim_cap/octagonal_spiral 同款形态）；未冒
烟（离线审计过 #212，test_layered_stack_audit）；真机发射留批 2。

本模块不带 ``__all__``（public_api 快照口径记私有，零漂移）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.adapters.layered_stack_spec import (
    FREQ_RANGE_GHZ_DEFAULT,
    MATERIALS,
    MESH_FLOOR_MM,
    LayeredStackSpec,
    layered_stack_layout,
)
from rfauto.adapters.oe_templates.inset_guard import assert_excitation_inset

#: 端口馈段长（×BASE；端口面出 PML_8=16·BASE 惯例，siw/sicl 同值）
OE_FEED_BASE = 16.0
#: 横向（y/z）MUR 域余量（×BASE；金属化腔封闭，数值裕量口径）
OE_TRANSVERSE_MARGIN_BASE = 8.0
#: FeedShift（×NEAR；官方 MSLPort 口径，SSL/sicl 同值；10·NEAR=2.5·BASE
#: ≥2·BASE 过 #253 激励盒内缩守卫，且 >PML_8=8·NEAR 厚度）
OE_FEED_SHIFT_NEAR = 10.0
#: MeasPlaneShift（馈段长等分；mline (Y0+BOARD)/3 同式）
OE_MEAS_PLANE_FRAC = 3.0
#: 特征分辨守卫（#266 口径）：NEAR ≤ 最细横向特征（strip 宽）/3
_NEAR_OVER_FEATURE = 3.0

#: meta json 判读口径注记（嵌脚本）
_JUDGE_NOTE = (
    "judgement: β/εeff 主判=StripLinePort β 对照闭式锚（|Δ|≤2% 口径同 "
    "stripline 族）；|S11| 带谷=Z0 锚（ref=50，闭式 Z0 偏差见 meta "
    "closed_form 注）；S21 相位斜率×plane_dist 交叉核对。闭式假设膜"
    "对称居中+无限平面腔壁，本族膜单侧+有限壁宽（0.9mm）=近似面如实"
    "登记（§2.1 HFSS 实测 50Ω 点吻合为经验锚）")

#: 金属盒台账条目 (x0, x1, y0, y1, z0, z1)（米；零厚片=该轴 lo==hi）
MetalBox = tuple[float, float, float, float, float, float]
#: 馈段壁延续盒（壁名 + MetalBox；Q-X14 Fix1 数据面）
FeedWallBox = tuple[str, MetalBox]
#: 几何守卫容差（米；nm 级浮点余量，#283 落格同量级）
_BOX_TOL_M = 1e-12


def _feed_wall_continuation_boxes(
    metal_sheets: list[dict[str, Any]], l_half_m: float, dom_x_m: float
) -> list[FeedWallBox]:
    """腔壁 (y,z) 单源直通 → 馈段 x 重定延续盒（Q-X14 Fix1 数据面）。

    每面壁（``lay["metal_sheets"]`` 条目）发射两个延续盒：x∈
    [−DOM_X,−L_HALF] 与 [L_HALF,DOM_X]，(y,z) 取壁原盒字面 ×1e-3 直通
    （铁律 7：壁坐标=layout 单源产出，本函数零几何独立计算；strip 体段
    不在 metal_sheets——馈段 strip 由 StripLinePort 自画，不在此延续）。
    """
    out: list[FeedWallBox] = []
    for wall in metal_sheets:
        _bx0, _bx1, y0, y1, z0, z1 = (float(v) * 1e-3 for v in wall["box"])
        name = str(wall["name"])
        out.append((name, (-dom_x_m, -l_half_m, y0, y1, z0, z1)))
        out.append((name, (l_half_m, dom_x_m, y0, y1, z0, z1)))
    return out


def _assert_feed_walls_complete(
    metal_sheets: list[dict[str, Any]], feed_boxes: list[FeedWallBox],
    l_half_m: float, dom_x_m: float,
) -> None:
    """Fix2 守卫①（存在性自检）：每面腔壁在两个馈段 x 区间都有同 (y,z)
    金属延续盒（对延续盒台账实测，非发射循环自证——防未来重构破坏
    "匹配馈延续"不变量，qx12 RC1 形态回归即红）。"""
    segs = ((-dom_x_m, -l_half_m), (l_half_m, dom_x_m))
    for wall in metal_sheets:
        _bx0, _bx1, y0, y1, z0, z1 = (float(v) * 1e-3 for v in wall["box"])
        name = str(wall["name"])
        for sx0, sx1 in segs:
            hit = any(
                bn == name
                and all(abs(b[i] - v) <= _BOX_TOL_M
                        for i, v in ((2, y0), (3, y1), (4, z0), (5, z1)))
                and b[0] <= min(sx0, sx1) + _BOX_TOL_M
                and b[1] >= max(sx0, sx1) - _BOX_TOL_M
                for bn, b in feed_boxes)
            if not hit:
                raise ValueError(
                    f"layered_stack: 腔壁 {name!r} 馈段 x∈[{min(sx0, sx1)!r}, "
                    f"{max(sx0, sx1)!r}] 缺同 (y,z) 金属延续盒（匹配馈四壁"
                    "延续不变量破坏——qx12 RC1 形态，fail-loud 拒绝渲染）")


def _assert_probe_plane_metal_covered(
    metal_boxes: list[MetalBox], probe_xs: list[float], strip_z_m: float,
    height_m: float, strip_y0_m: float, strip_y1_m: float,
) -> None:
    """Fix2 守卫②（探针面覆盖，fail-loud）：StripLinePort 探针面
    x=±(DOM_X−MeasPlaneShift) 处 z=STRIP_Z±PORT_HEIGHT（上下地平面）
    必须有金属盒覆盖 y∈[STRIP_Y0,STRIP_Y1]——对称电压探针（±height，
    openEMS ports.py L1027/L1130-1142）预设 ±height 存在 PEC 地；命中
    =0 即 qx12 RC1"无回流开域场"形态（β/Z_ref 提取失义），ValueError
    拒绝渲染（qx12 probe_plane_check.py 静态判据收编，#212 零仿真）。"""
    ground_zs = (strip_z_m + height_m, strip_z_m - height_m)
    for xp in probe_xs:
        for zg in ground_zs:
            hits = sum(
                1 for (x0, x1, y0, y1, z0, z1) in metal_boxes
                if x0 - _BOX_TOL_M <= xp <= x1 + _BOX_TOL_M
                and z0 - _BOX_TOL_M <= zg <= z1 + _BOX_TOL_M
                and y0 <= strip_y1_m + _BOX_TOL_M
                and y1 >= strip_y0_m - _BOX_TOL_M)
            if hits <= 0:
                raise ValueError(
                    f"layered_stack: StripLinePort 探针面 x={xp!r} 处 "
                    f"z={zg!r}（±height 地平面）金属盒命中=0（覆盖 "
                    f"y∈[{strip_y0_m!r}, {strip_y1_m!r}] 计 0 盒）——馈段四壁"
                    "未延续=端口电压探针积分到无回流开域场（qx12 RC1 形态），"
                    "fail-loud 拒绝渲染")


def render_layered_stack(
    spec: LayeredStackSpec | dict[str, Any],
    freq_range_ghz: tuple[float, float] = FREQ_RANGE_GHZ_DEFAULT,
    mesh_resolution_mm: float = 0.0,
    excite_port: int = 1,
    nrts: int | None = None,
) -> str:
    """layered_stack 整脚本渲染（CSXCAD 文本；离线审计 exec 几何段）。

    Parameters
    ----------
    spec : LayeredStackSpec | dict
        族 spec（dict 走 model_validate 同契约）。
    freq_range_ghz : (f_lo, f_lo)
        激励频带 GHz（缺省=§5 实测扫频 85-105）。
    mesh_resolution_mm : float
        网格 base（mm）；0=自动 λ_sub/50@F_MAX（最高 εr 介质）。
    excite_port : int
        主激励端口（1/2 轮转；#208 整 S 矩阵=逐激励进程隔离渲染）。
    nrts : int | None
        FDTD 步数上限（None=100000 官方口径）。
    """
    if isinstance(spec, dict):
        spec = LayeredStackSpec.model_validate(spec)
    if excite_port not in (1, 2):
        raise ValueError(
            f"layered_stack: 双端口模板，excite_port 须为 1/2，收到 "
            f"{excite_port!r}")
    lay = layered_stack_layout(spec)

    # ── 频带/网格尺度 ────────────────────────────────────────────────────
    f_lo, f_hi = float(freq_range_ghz[0]), float(freq_range_ghz[1])
    if not (0.0 < f_lo < f_hi):
        raise ValueError(
            f"layered_stack: freq_range_ghz 须 0<f_lo<f_hi，得到 "
            f"{freq_range_ghz!r}")
    f0 = 0.5 * (f_lo + f_hi) * 1e9
    fc = 0.5 * (f_hi - f_lo) * 1e9
    diel_mats_in_spec = {m for m, _t in spec.layers
                         if not MATERIALS[m].is_metal}
    er_max = max(float(MATERIALS[m].er) for m in diel_mats_in_spec)
    # 网格 base：λ_sub/50@F_MAX（最高 εr 介质材料；SIW/sicl 同口径）
    if mesh_resolution_mm and mesh_resolution_mm > 0:
        base_mm = float(mesh_resolution_mm)
    else:
        lambda0_max_mm = 299.792458 / f_hi   # mm（c=299.792458 mm·GHz）
        base_mm = lambda0_max_mm / math.sqrt(er_max) / 50.0
    near_mm = base_mm / 4.0
    base_m = base_mm * 1e-3
    near_m = near_mm * 1e-3
    # #266 特征分辨守卫：NEAR ≤ strip 宽/3（最细横向特征）
    strip_w_mm = float(spec.conductor.width_mm)
    if near_mm > strip_w_mm / _NEAR_OVER_FEATURE:
        raise ValueError(
            f"layered_stack: NEAR={near_mm * 1e3:.4g}µm > strip 宽/"
            f"{_NEAR_OVER_FEATURE:g}={strip_w_mm / _NEAR_OVER_FEATURE * 1e3:.4g}"
            f"µm（BASE={base_mm * 1e3:.4g}µm，#266 特征分辨守卫）——收紧 "
            "mesh_resolution_mm")
    # #349 显式特征线地板（布局已剔除次胞面，此处复检 fail-loud）
    for ax in ("x", "y", "z"):
        lines = [float(v) for v in lay["feature_lines_mm"][ax]]
        gaps = [lines[i + 1] - lines[i]
                for i in range(len(lines) - 1)]
        gmin = min(gaps) if gaps else float("inf")
        if gmin < MESH_FLOOR_MM:
            raise ValueError(
                f"layered_stack: {ax} 向显式特征线最小间距 {gmin * 1e3:.4g}µm "
                f"< {MESH_FLOOR_MM * 1e3:.0f}µm 地板（#349 CFL 塌缩守卫）"
                "——调整 spec 几何（膜厚/腔位/叠层界面间距）")
    # #253 激励盒内缩守卫（FeedShift=10·NEAR=2.5·BASE ≥2·BASE）
    assert_excitation_inset(OE_FEED_SHIFT_NEAR * near_m, base_m,
                            label="layered_stack StripLinePort 激励盒")

    # ── 几何账（mm → 米）────────────────────────────────────────────────
    l_half = float(lay["l_half_mm"]) * 1e-3
    feed = OE_FEED_BASE * base_m
    dom_x = l_half + feed
    wy = float(spec.wafer_width_mm) / 2.0 * 1e-3
    dom_y = wy + OE_TRANSVERSE_MARGIN_BASE * base_m
    zr_m = [(lo * 1e-3, hi * 1e-3) for lo, hi in lay["z_ranges_mm"]]
    z_bot_dom = zr_m[0][0] - OE_TRANSVERSE_MARGIN_BASE * base_m
    z_top_dom = zr_m[-1][1] + OE_TRANSVERSE_MARGIN_BASE * base_m
    cav = lay["cavity_mm"]
    cy = float(cav["y_center"]) * 1e-3
    cy0, cy1 = float(cav["y0"]) * 1e-3, float(cav["y1"]) * 1e-3
    cz_lo, cz_hi = float(cav["z0"]) * 1e-3, float(cav["z1"]) * 1e-3
    strip_z = float(lay["strip_z_mm"]) * 1e-3
    strip_y0 = float(lay["strip"][2]) * 1e-3
    strip_y1 = float(lay["strip"][3]) * 1e-3
    height_m = cz_hi - strip_z   # 带面→腔顶壁（spec 已锁对称，=带面-腔底壁）
    feat_x = [float(v) * 1e-3 for v in lay["feature_lines_mm"]["x"]]
    feat_y = [float(v) * 1e-3 for v in lay["feature_lines_mm"]["y"]]
    feat_z = [float(v) * 1e-3 for v in lay["feature_lines_mm"]["z"]]
    nrts_v = int(nrts if nrts is not None else 100000)

    # 介质材料卡（按声明材料聚合；kappa=tan_d·2πf0·ε0·er，mim_cap 同式）
    diel_mats: dict[str, dict[str, float]] = {}
    for mat, _t in spec.layers:
        props = MATERIALS[mat]
        if props.is_metal or mat in diel_mats:
            continue
        kappa = float(props.tan_d) * 2.0 * math.pi * f0 * 8.854187817e-12 \
            * float(props.er)
        diel_mats[mat] = {"er": float(props.er), "kappa": kappa}

    # 金属层 sheet 平面单源：层界面中已入特征线集的那一面（z_hi 优先，
    # 否则 z_lo；两面皆不入线=设计错误 fail-loud）
    def _metal_sheet_z(lo_mm: float, hi_mm: float) -> float:
        tol = 1e-12
        feat_z_mm = [float(v) for v in lay["feature_lines_mm"]["z"]]
        if any(abs(hi_mm - v) <= tol for v in feat_z_mm):
            return hi_mm * 1e-3
        if any(abs(lo_mm - v) <= tol for v in feat_z_mm):
            return lo_mm * 1e-3
        raise ValueError(
            f"layered_stack: 金属层界面 [{lo_mm!r}, {hi_mm!r}] 两面皆未入"
            "特征线集（次胞剔除后无落格面）——调整膜厚/腔位或叠层界面")

    # 闭式锚（确定性内核 facade 消费；§2.1 同参实测背书）
    from rfauto.core.calculators import _suspended_stripline_ri
    membrane_thick_mm = float(spec.layers[spec.conductor_index()][1])
    eps_eff, z0_ohm = _suspended_stripline_ri(
        strip_w_mm, float(spec.cavity.h_mm), membrane_thick_mm,
        float(MATERIALS[
            spec.layers[spec.conductor_index()][0]].er))

    # ── 字面量装配（米；repr 往返精确）──────────────────────────────────
    x_all = sorted(set(feat_x) | {-dom_x, dom_x})
    y_all = sorted(set(feat_y) | {-dom_y, dom_y})
    z_all = sorted(set(feat_z) | {z_bot_dom, z_top_dom})
    xs_lit = ", ".join(repr(v) for v in x_all)
    ys_lit = ", ".join(repr(v) for v in y_all)
    zs_lit = ", ".join(repr(v) for v in z_all)
    feat_xs_lit = ", ".join(repr(v) for v in feat_x)
    feat_ys_lit = ", ".join(repr(v) for v in feat_y)
    feat_zs_lit = ", ".join(repr(v) for v in feat_z)

    # 介质材料卡定义文本（AddMaterial；kappa=tan_d·2πf0·ε0·er，mim_cap 同式）
    mat_defs: list[str] = []
    for mat in sorted(diel_mats):
        props = diel_mats[mat]
        mat_defs.append(
            f'{_mat_var(mat)} = CSX.AddMaterial({mat!r}, '
            f'epsilon={props["er"]!r}, kappa={props["kappa"]!r})')
    mat_def_txt = "\n".join(mat_defs)

    # 介质盒文本（stack_solids 非金属分段 + 馈段膜片）
    diel_boxes: list[str] = []
    for seg in lay["stack_solids"]:
        if seg["is_metal"]:
            continue
        bx0, bx1, by0, by1, bz0, bz1 = (float(v) * 1e-3 for v in seg["box"])
        diel_boxes.append(
            f'{_mat_var(str(seg["material"]))}.AddBox('
            f'({bx0!r}, {by0!r}, {bz0!r}), ({bx1!r}, {by1!r}, {bz1!r}), '
            "priority=0)")
    # 馈段膜片（导体层材料，足迹修至腔宽=腔截面精确延续）
    cond_mat = str(spec.layers[spec.conductor_index()][0])
    cond_lo_m, cond_hi_m = zr_m[spec.conductor_index()]
    diel_boxes.append(
        f"# 馈段膜片（腔管截面精确延续至 PML——匹配端接口径，siw v1 同源）\n"
        f"{_mat_var(cond_mat)}.AddBox((-{dom_x!r}, {cy0!r}, {cond_lo_m!r}), "
        f"(-{l_half!r}, {cy1!r}, {cond_hi_m!r}), priority=0)")
    diel_boxes.append(
        f"{_mat_var(cond_mat)}.AddBox(({l_half!r}, {cy0!r}, {cond_lo_m!r}), "
        f"({dom_x!r}, {cy1!r}, {cond_hi_m!r}), priority=0)")
    diel_box_txt = "\n".join(diel_boxes)

    # 金属键合层 sheet 文本（stack_solids is_metal 分段 → 零厚片）
    # + 金属盒台账（Q-X14 Fix2 守卫数据面：全部 metal.AddBox 盒入账，
    # 探针面覆盖断言在台账上实测——与发射文本同源不两张皮）
    metal_box_ledger: list[MetalBox] = []
    metal_sheet_txts: list[str] = []
    for seg in lay["stack_solids"]:
        if not seg["is_metal"]:
            continue
        bx0, bx1, by0, by1, bz0, bz1 = (float(v) for v in seg["box"])
        sheet_z = _metal_sheet_z(bz0, bz1)
        metal_sheet_txts.append(
            f'# 键合金属层 layer{seg["layer"]}（{seg["name"]}）3µm 次胞体积'
            "盒→零厚 PEC sheet 落格确定性\n"
            f"metal.AddBox(({bx0 * 1e-3!r}, {by0 * 1e-3!r}, {sheet_z!r}), "
            f"({bx1 * 1e-3!r}, {by1 * 1e-3!r}, {sheet_z!r}), priority=10)")
        metal_box_ledger.append((bx0 * 1e-3, bx1 * 1e-3, by0 * 1e-3,
                                 by1 * 1e-3, sheet_z, sheet_z))
    metal_sheet_txt = "\n".join(metal_sheet_txts) if metal_sheet_txts else (
        "# （spec 无金属键合层）")

    # 腔壁金属化 sheet 文本 + 馈段四壁延续（Q-X14 Fix1，qx12 调查 RC1
    # 修复：注释声称的"腔管截面（膜片+四壁）同步延续"兑现为代码——逐面
    # 消费 lay["metal_sheets"] 壁盒 (y,z) 字面单源直通（铁律 7），x 重定
    # 到 [−DOM_X,−L_HALF]∪[L_HALF,DOM_X]；strip 体段不在 metal_sheets
    # （馈段 strip 由 StripLinePort 自画）；网格零改动：壁面 y/z 与
    # ±L_HALF/±DOM_X 全是既有特征线，PEC 片不增 cell）
    wall_txts: list[str] = []
    for wall in lay["metal_sheets"]:
        bx0, bx1, by0, by1, bz0, bz1 = (float(v) * 1e-3 for v in wall["box"])
        wall_txts.append(
            f'metal.AddBox(({bx0!r}, {by0!r}, {bz0!r}), '
            f'({bx1!r}, {by1!r}, {bz1!r}), priority=10)  # {wall["name"]}')
        metal_box_ledger.append((bx0, bx1, by0, by1, bz0, bz1))
    feed_wall_boxes = _feed_wall_continuation_boxes(lay["metal_sheets"],
                                                    l_half, dom_x)
    # Fix2 守卫①：壁延续存在性自检（延续盒台账实测，非发射循环自证）
    _assert_feed_walls_complete(lay["metal_sheets"], feed_wall_boxes,
                                l_half, dom_x)
    for _wname, _fb in feed_wall_boxes:
        _fx0, _fx1, _fy0, _fy1, _fz0, _fz1 = _fb
        wall_txts.append(
            f"metal.AddBox(({_fx0!r}, {_fy0!r}, {_fz0!r}), "
            f"({_fx1!r}, {_fy1!r}, {_fz1!r}), priority=10)  "
            f"# {_wname} 馈段延续（匹配馈 Q-X14 Fix1）")
        metal_box_ledger.append(_fb)
    wall_txt = "\n".join(wall_txts)
    # strip 体段盒入台账（文本在下方模板内联；z=带面零厚，不参与地平面
    # 覆盖判据，仅台账完整性）
    metal_box_ledger.append((-l_half, l_half, strip_y0, strip_y1,
                             strip_z, strip_z))
    # Fix2 守卫②：双 StripLinePort 探针面（x=±(DOM_X−MeasPlaneShift)）
    # z=STRIP_Z±PORT_HEIGHT 地平面金属覆盖断言（RC1 静态判据收编，
    # fail-loud）
    meas_shift = feed / OE_MEAS_PLANE_FRAC
    _assert_probe_plane_metal_covered(
        metal_box_ledger, [-(dom_x - meas_shift), dom_x - meas_shift],
        strip_z, height_m, strip_y0, strip_y1)

    # StripLinePort 装配（prop_dir="x"、exc_dir="z"、width=y=带缘）
    # （meas_shift=feed/OE_MEAS_PLANE_FRAC 已在腔壁守卫段单源计算）
    exc1 = 1 if excite_port == 1 else 0
    exc2 = 1 if excite_port == 2 else 0
    feed_shift = OE_FEED_SHIFT_NEAR * near_m

    return f'''#!/usr/bin/env python3
"""openEMS layered_stack script (rfauto aurora_q Q-X4 auto-generated).

晶圆键合叠层+空腔+截面端口族（T-Q26d 批 1）。几何/端口/网格口径见
src/rfauto/adapters/oe_templates/render_layered_stack.py 模块头与
src/rfauto/adapters/layered_stack_spec.py 模块 docstring（§2.2 真空
约定/§2.3 端口断言出处、名义值锚表）。
"""
import csv
import json
import os

_OE_BIN = os.environ.get("RFAUTO_OPENEMS_BIN",
                         r"E:\\\\rfauto_workspace\\\\vendor\\\\openEMS\\\\install\\\\bin")
if os.path.isdir(_OE_BIN):
    os.environ["PATH"] = _OE_BIN + os.pathsep + os.environ.get("PATH", "")
    os.add_dll_directory(_OE_BIN)

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.ports import StripLinePort

F0 = {f0!r}
FC = {fc!r}
NRTS = {nrts_v}
BASE = {base_m!r}   # 网格 base（自动档=λ_sub/50@F_MAX，最高 εr 介质）
NEAR = {near_m!r}   # 近特征区 = base/4
FEED = {feed!r}     # 端口馈段长（16·BASE，端口面出 PML_8）
DOM_X = {dom_x!r}   # x 半宽（=L/2+FEED，PML_8 两端）
DOM_Y = {dom_y!r}   # y 半宽（=晶圆半宽+8·BASE，MUR）
Z_BOT_DOM = {z_bot_dom!r}
Z_TOP_DOM = {z_top_dom!r}
L_HALF = {l_half!r}        # 结构半长（晶圆体止于此，馈段延续至 DOM_X）
CY = {cy!r}                # 腔/带横向中心
CY0 = {cy0!r}              # 腔 y 下缘（壁面）
CY1 = {cy1!r}              # 腔 y 上缘（壁面）
CZ_LO = {cz_lo!r}          # 腔底（壁面）
CZ_HI = {cz_hi!r}          # 腔顶（壁面）
STRIP_Y0 = {strip_y0!r}
STRIP_Y1 = {strip_y1!r}
STRIP_Z = {strip_z!r}      # 带面（导体层顶面）
PORT_HEIGHT = {height_m!r} # 带面-腔壁距离（StripLinePort 对称探针高度）
Z_BOT_DOM_LINE = {z_bot_dom!r}
Z_TOP_DOM_LINE = {z_top_dom!r}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 传播轴（x）两端 PML_8（端口面出 PML：FEED=16·BASE 净距，激励
# FeedShift=10·NEAR 在 PML 外）；横向 y/z MUR（金属化腔封闭，泄漏≈0）
FDTD.SetBoundaryCond(["PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 特征线显式入网（#198：带面/膜面/腔壁面/带缘/壁缘/晶圆缘/结构端面/域界；
# 次胞界面已由布局单源剔除——#349 地板），全轴平滑
# （x 轴馈段须有网格——激励/探针落格；siw「SmoothMesh 全轴均匀化」口径）
mesh.AddLine("x", np.array([{xs_lit}]))
mesh.AddLine("y", np.array([{ys_lit}]))
mesh.AddLine("z", np.array([{zs_lit}]))
mesh.SmoothMeshLines("x", NEAR)
mesh.SmoothMeshLines("y", NEAR)
mesh.SmoothMeshLines("z", BASE)
# 特征线保护式 #152 去重（mim_cap 同款）：显式特征线全保留（nm 级自
# 去重），平滑产物线只在距全部已保留线 >thr 时收编。GetLines 先排序
# （上游 0.7.0 绑定按插入序返回，#331 家族）。
_feat_x = np.array([{feat_xs_lit}])
_feat_y = np.array([{feat_ys_lit}])
_feat_z = np.array([{feat_zs_lit}])
for _ax, _feat in (("x", _feat_x), ("y", _feat_y), ("z", _feat_z)):
    _ls = np.sort(np.asarray(mesh.GetLines(_ax), dtype=float))
    _keep: list = []
    for _v in np.sort(np.unique(np.round(_feat, 12))):
        if not _keep or _v - _keep[-1] > 1e-9:
            _keep.append(float(_v))
    for _v in _ls:
        if all(abs(_v - _k) > 1e-6 for _k in _keep):
            _keep.append(float(_v))
            _keep.sort()
    mesh.SetLines(_ax, np.array(_keep))
# 生成期守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("layered_stack #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
# 落格断言（#283：特征面恰在网格线上——壁面/带面/端口盒边）
def _on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", -L_HALF), ("x", L_HALF),
                ("y", CY0), ("y", CY1), ("y", STRIP_Y0), ("y", STRIP_Y1),
                ("z", CZ_LO), ("z", CZ_HI), ("z", STRIP_Z)):
    if not _on_line(_ax, _v):
        raise SystemExit("layered_stack #" + "283" + ": 特征面 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")

# ── 几何：叠层（分层围合）+ 腔壁金属化 + strip ──
# 介质材料卡（spec 声明材料；tan_d 缺省 0 → kappa=0）
{mat_def_txt}
# 介质层盒（腔足印内非导体层挖除=不产生盒；导体层完整横跨）
{diel_box_txt}

metal = CSX.AddMetal("layered_stack_metal")
{metal_sheet_txt}
# 腔壁金属化（四壁零厚 PEC；两端截面口不金属化——端口须见腔截面）
# + 馈段四壁延续盒（Q-X14 Fix1：匹配馈区截面=腔截面，探针 ±height 落
# 真实 PEC 地——siw v1 匹配端接口径兑现）
{wall_txt}
# strip 体段（导体层顶面零厚 PEC；馈段由 StripLinePort 自画补齐到域界）
metal.AddBox((-L_HALF, STRIP_Y0, STRIP_Z), (L_HALF, STRIP_Y1, STRIP_Z), priority=10)
for _prim in metal.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)

# ── 端口：双 StripLinePort（suspended_stripline/sicl 同法；height=
#    带面-腔壁距离，spec 校验器已锁腔关于带面对称）──
# 馈段：strip 金属自 ±L/2 延续至 ±DOM_X（端口盒自画），腔管截面
# （膜片+四壁）同步延续=匹配端接（siw v1 口径）；激励 FeedShift=10·NEAR
# （#253 过守卫 2.5·BASE≥2·BASE 且在 PML_8=8·NEAR 外），测量面
# MeasPlaneShift=FEED/3（mline (Y0+BOARD)/3 同式）
_port1 = StripLinePort(CSX, port_nr=1, metal_prop=metal,
                       start=np.array([-DOM_X, STRIP_Y0, STRIP_Z]),
                       stop=np.array([-L_HALF, STRIP_Y1, STRIP_Z]),
                       prop_dir="x", exc_dir="z", height=PORT_HEIGHT,
                       excite={exc1}, FeedShift={feed_shift!r},
                       MeasPlaneShift={meas_shift!r}, priority=10)
_port2 = StripLinePort(CSX, port_nr=2, metal_prop=metal,
                       start=np.array([DOM_X, STRIP_Y0, STRIP_Z]),
                       stop=np.array([L_HALF, STRIP_Y1, STRIP_Z]),
                       prop_dir="x", exc_dir="z", height=PORT_HEIGHT,
                       excite={exc2}, FeedShift={feed_shift!r},
                       MeasPlaneShift={meas_shift!r}, priority=10)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：S11/S21（单激励 run，ref=50；β 金标准 port_beta.csv 契约
#    列=SSL/sicl 8 列逐字节不变）──
f = np.linspace(F0 - FC, F0 + FC, 201)
_port1.CalcPort(SIM_PATH, f, ref_impedance=50.0)
_port2.CalcPort(SIM_PATH, f, ref_impedance=50.0)
S11 = _port1.uf_ref / _port1.uf_inc
S21 = _port2.uf_ref / _port1.uf_inc

_port1.ReadUIData(SIM_PATH, f)
_port2.ReadUIData(SIM_PATH, f)
_plane_dist = float(2 * DOM_X - _port1.measplane_shift - _port2.measplane_shift)
with open(os.path.join(SCRIPT_DIR, "port_beta.csv"), "w", newline="") as _bfh:
    _bw = csv.writer(_bfh)
    _bw.writerow(["freq_hz", "beta_rad_per_m", "beta2_rad_per_m",
                  "re_zl1_ohm", "im_zl1_ohm", "re_zl2_ohm", "im_zl2_ohm",
                  "plane_dist_m"])
    for _i, _fi in enumerate(f):
        _bw.writerow([_fi, float(np.real(_port1.beta[_i])),
                      float(np.real(_port2.beta[_i])),
                      float(np.real(_port1.Z_ref[_i])),
                      float(np.imag(_port1.Z_ref[_i])),
                      float(np.real(_port2.Z_ref[_i])),
                      float(np.imag(_port2.Z_ref[_i])), _plane_dist])

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag,
                     S21[_i].real, S21[_i].imag])
summary = {{
    "ok": True,
    "template": "layered_stack",
    "excite_port": {excite_port},
    "f0_hz": F0, "fc_hz": FC,
    "line_len_mm": {float(spec.line_len_mm)!r},
    "wafer_width_mm": {float(spec.wafer_width_mm)!r},
    "cavity_mm": {{"w": {float(spec.cavity.w_mm)!r}, "h": {float(spec.cavity.h_mm)!r},
                   "z0": {float(spec.cavity.z0_mm)!r}}},
    "strip_width_mm": {strip_w_mm!r},
    "conductor_layer": {spec.conductor_index()},
    "layers": {[(m, t) for m, t in spec.layers]!r},
    "cavity_metalization_mm": {float(spec.cavity_metalization_mm)!r},
    "closed_form": {{"epsilon_eff": {eps_eff!r}, "z0_ohm": {z0_ohm!r},
                     "source": "core.calculators._suspended_stripline_ri"
                     "(w=0.52, b=0.50, h=0.05, εr=11.9)——反馈 §2.1 实测锚"
                     "（HFSS |S11|max=-23.5dB 背书 50Ω 点）；假设面=膜对称"
                     "居中+无限平面腔壁（本族膜单侧+有限壁宽，近似如实登记）"}},
    "mesh_lines": [int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
    "base_mm": {base_mm!r}, "near_mm": {near_mm!r},
    "dom_x_m": DOM_X, "feed_m": FEED,
    "nrts": NRTS,
    "note": {_JUDGE_NOTE!r},
}}
with open(os.path.join(SCRIPT_DIR, "layered_stack_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto layered_stack simulation done")
'''


def _mat_var(material: str) -> str:
    """材料名 → 脚本变量名（标识符安全）。"""
    safe = "".join(ch if ch.isalnum() else "_" for ch in material)
    if not safe or safe[0].isdigit():
        safe = f"mat_{safe}"
    return f"m_{safe}"
