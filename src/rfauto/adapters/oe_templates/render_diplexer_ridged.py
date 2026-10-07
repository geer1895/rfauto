"""TA-5 Diplexer（LP+HP T 结）+ TA-6 空气脊波导（TA 批第三批，2026-10-02）。

方案锚：研究扩充 round15 §二·2 TA-5/TA-6——
「内核就绪缺模板」件：闭式全套在 core（diplexer_compose.diplexer_lpf_hpf /
ridged_waveguide 双源闭式族），本模块只做几何渲染注册与名义设计链
（#1c：数值全部内核精算，零手抄毫米数；本文件零物理数字产出——铁律 7）。

── TA-5 diplexer（一阶常阻互补对偶 CR 型，3 端口）────────────────────────
器件=输入 T 结（理想集总节点物理化为微带 T 接头）分两臂——LPF 臂（一阶
串联 L）+ HPF 臂（一阶串联 C，LP→HP 对偶）——集总元件经 LumpedElement
桥接断口实现（atten_pi 串臂/nway 隔离电阻同法），三端口：port1=antenna
（公共口，−BOARD 板边）、port2=LP（+x 板边）、port3=HP（−x 板边）。
- 拓扑选择（如实登记）：内核 ≥2 阶 Butterworth 对的复合回损有固有地板
  （T 结两臂阻抗状态交互，实测 ~−7dB @3/3 阶、内核 docstring 判据节；
  无耗互易三口不可全匹配 Pozar §7.5）——渲染取内核 CR 一阶对
  （lpf_order=hpf_order=1，g_eff=1 定标）：S11≡0、|S21|²+|S31|²≡1、
  交越精确 fc 三锚闭式精确（内核恒等式），EM 版才有可判读的判读门
  （|S11| 深谷全带）；选择性 20dB/dec 为一阶固有，smoke_note 如实登记；
- 名义设计点：fc=2.5GHz、Z0=50 → L=Z0/ωc=3.1831nH、C=1/(ωc·Z0)=1.2732pF
  （内核 element_values 单源）+ 50Ω 馈线宽（nominal_width_mm，XC-W 单源）；
- 集总实现口径：元件间 50Ω 连接线/馈线 stub 的电长度寄生不进闭式裁判
  （qwt 节间阶梯/branchline T 叉同口径）——元件紧凑排布（近端 4mm、断口
  0.4mm ≪ λg/4）使寄生段电小；离线裁判=内核同参精确复算+四门 verdict。

── TA-6 ridged_wg（空气单脊波导均匀段，2 端口）──────────────────────────
器件=空气填充单脊矩形波导（外廓 a×b + 顶壁居中脊 s×d）+ 两端加宽馈波导
（a_feed×b，H 面对称阶跃）——脊降低主模截止（横磁共振方程，Cohn 1947→
Hopfer 1955→Pyle 1966 传导链，core/ridged_waveguide 一阶闭式）。
- 端口=双 RectWGPort 解析 TE10（pyramid_horn 同法）打在**加宽馈段**：
  馈段截止 fc_feed=0.75·fc_ridge（a_feed=c/(2·fc_feed) 结构性 >4a/3>a，
  构造保证宽于脊段外廓）——判读带底须 >fc_feed（馈段行波）且带顶
  < min(1.5·fc_ridge=馈段 TE20, c/(2a)=外廓 TE10)（单模域），layout 守卫；
- 判读锚（预声明，真机窗）：交越膝点 |S21| −3dB 落 fc·(1±8%)（脊段
  消逝衰减 @0.8fc ≈22dB/40mm 使过渡陡峭）+ 带底消逝衰减斜率对照内核
  evanescent_attenuation_db；XC-P 精度域声明：名义 g/b=0.454≥0.4
  （kc 对独立 FEM +1.5%~+8% 分档域，深脊 g/b<0.4 拒渲染守卫移植）；
- 名义设计点：a=22.86/b=10.16（b/a=0.5 标准档）、s/a=0.4、
  fc_target=5.0GHz → design_ridge_depth 反解 d=5.5434mm（g/b=0.454）；
  WR-90 宽边口径（outline TE10 fc=6.557GHz，带顶 6.3<6.557 单模）；
- 空气填充全金属器件：er=1.0 只进渲染脚本 summary 回显、h_mm=0.0 占位键
  （pyramid_horn 审计④口径，MATERIAL_VALUE_PARAMS 豁免）；整脚本渲染器
  早分发（horn 同款，无 BOARD 共享字面量）。

近似级别（如实登记，#122）：diplexer=理想集总 LumpedElement（无寄生
L/C/自谐振）+元件间连接线电长度寄生不进闭式裁判；ridged_wg=一阶横磁
共振闭式（遗漏脊缘杂散电容，+1.5~+8% @g/b≥0.4 分档域，内核精度档案）+
H 面阶跃结反射不进闭式裁判（v1 直阶跃无渐变）+RectWGPort 打在馈段
（脊模经阶跃结的耦合损耗计入 S21）；真机冒烟与 HFSS 仲裁属后续批次
（本批零发射）。
"""

from __future__ import annotations

import math
from typing import Any

from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)

#: 板边半宽——与 render_script 共享字面量 BOARD=60mm 同源（禁改共享字面量，
#: 布局守卫按此值核算；_board_mm 旋钮渲染期单变量覆盖时不经本模块）
_BOARD_MM = 60.0

# ═══ TA-5 diplexer ═══════════════════════════════════════════════════════

#: 缺省设计点常量（与 design_params 缺省实参同源）
DIPLEXER_F0_GHZ = 2.5
DIPLEXER_Z0_OHM = 50.0
DIPLEXER_LPF_ORDER = 1         # 一阶 CR 对（见段头拓扑选择注）
DIPLEXER_HPF_ORDER = 1
#: 布局常量（mm）：串接元件断口近端离 T 点距离 / 断口长（电小寄生段口径）
_DIP_X_ELEM_MM = 4.0
_DIP_GAP_MM = 0.4


def diplexer_design_params(
    f0_ghz: float = DIPLEXER_F0_GHZ,
    z0_ohm: float = DIPLEXER_Z0_OHM,
    lpf_order: int = DIPLEXER_LPF_ORDER,
    hpf_order: int = DIPLEXER_HPF_ORDER,
) -> dict[str, Any]:
    """Diplexer 名义设计点（内核精算单源，#1c——名义值禁手算捷径）。

    设计链：core.diplexer_compose.diplexer_lpf_hpf(fc) 逐元件值（一阶 CR
    对：LPF 臂单串联 L=Z0/ωc、HPF 臂单串联 C=1/(ωc·Z0)，g_eff=1 定标）→
    50Ω 馈线宽 nominal_width_mm（XC-W 单源）。渲染 v1 只支持一阶 CR 对
    （≥2 阶对复合回损固有地板 ~−7dB，判读门不可判读——段头拓扑选择注），
    其他阶显式 ValueError 不静默兜底。逐键一致性由
    test_diplexer_ridged_templates 独立闭式复算钉住。
    """
    from rfauto.core.diplexer_compose import diplexer_lpf_hpf
    from rfauto.core.synthesis import nominal_width_mm

    fc_hz = float(f0_ghz) * 1e9
    d = diplexer_lpf_hpf([fc_hz], fc_hz, int(lpf_order), int(hpf_order),
                         float(z0_ohm))
    lpf = list(d["element_values"]["lpf"])   # type: ignore[arg-type]
    hpf = list(d["element_values"]["hpf"])   # type: ignore[arg-type]
    if (int(lpf_order) != 1 or int(hpf_order) != 1
            or len(lpf) != 1 or lpf[0][0] != "series_L"
            or len(hpf) != 1 or hpf[0][0] != "series_C"):
        raise ValueError(
            "diplexer 渲染 v1 只支持一阶 CR 对（lpf_order=hpf_order=1："
            "S11≡0/互补≡1/交越=fc 三锚闭式精确；≥2 阶对复合回损固有地板"
            " ~−7dB 判读门不可判读），得到 "
            f"lpf_order={lpf_order}/hpf_order={hpf_order}")
    sub50 = "rogers4350b_h0.508"
    return {
        "w_feed_mm": float(nominal_width_mm(float(z0_ohm), float(f0_ghz),
                                            sub50)),
        "l_lpf_nh": round(float(lpf[0][1]) * 1e9, 4),
        "c_hpf_pf": round(float(hpf[0][1]) * 1e12, 4),
    }


DIPLEXER_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 3,
    "extraction": "S11/S21/S31 @ MSLPort 1-3 单激励 7 列 CSV（port1=antenna "
                  "公共口激励，port2=LP/port3=HP 探针；3 端口轮转 footer，"
                  "#208 口径）。裁判=core.diplexer_compose 同参精确复算 + "
                  "diplexer_verdict 四门：能量守恒（幺正性恒等式 ≤1e-8）、"
                  "交越=fc（|S21|=|S31| 交点 ±tol）、通带 |S11|、互补亏缺；"
                  "CR 一阶对闭式锚 S11≡0/|S21|²+|S31|²≡1/交越精确 fc",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_feed_mm", "l_lpf_nh", "c_hpf_pf"],
    "topology": "Diplexer LP+HP T 结（TA-5，一阶常阻互补对偶 CR 型）：输入 "
                "50Ω 馈线（port1=antenna，−BOARD 板边）→ 微带 T 结 → LPF 臂"
                "（+x：50Ω 短段+LumpedElement 串联 L 断口桥接+50Ω stub 至 "
                "+BOARD=port2）与 HPF 臂（−x 镜像，串联 C=port3）；集总元件 "
                " atten_pi 串臂同法（ny=0 断口桥接）；全金属同层零交叉",
    "param_semantics": "w_feed_mm=全臂 50Ω 馈线/连接线宽（nominal_width_mm "
                       "单源）；l_lpf_nh=LPF 臂串联电感（=Z0/ωc，内核 "
                       "element_values 单源，LumpedElement L 值——进元件值"
                       "不进导体几何，qwt z_load_ohm 同口径豁免）；c_hpf_pf="
                       "HPF 臂串联电容（=1/(ωc·Z0)，对偶值同口径豁免）。"
                       "f0=交越频率 fc（meta f0_ghz）；元件位置/断口长为版"
                       "图常量（近端 4mm/断口 0.4mm，电小寄生段口径）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
                 "（官方口径）；全盒缘（馈线/T 条/臂带缘/元件断口缘）+ 端口"
                 " junction 精确入网（#198）；全轴 1µm 近重合去重（#152）；"
                 "端口面贴 PML_8 域边（#154 前节）；#347 输入段测量面-激励"
                 "分离守卫",
    "smoke_note": "未冒烟（离线审计过，#212，test_diplexer_ridged_templates）；"
                  "近似级别如实登记：①理想集总 LumpedElement（无寄生 L/C/"
                  "自谐振——2.5GHz 下 nH/pF 级元件自谐振 ≫fc，PCB 集总现实"
                  "口径如实登记）；②元件间 50Ω 连接线/馈线 stub 电长度寄生"
                  "不进闭式裁判（qwt 节间阶梯同口径，元件紧凑排布使寄生段"
                  "电小）；③≥2 阶对固有回损地板使其判读门不可判读——v1 取"
                  "一阶 CR 对（20dB/dec 选择性为一阶固有）；真机冒烟与 "
                  "HFSS 仲裁属后续批次（本批零发射）",
}

#: 名义设计点（2026-10-02 由 diplexer_design_params() 缺省实参导入期精算，
#: horn/coil_nfc 导入期综合同款；逐键一致性由测试独立闭式复算钉住）：
#: fc=2.5GHz → ωc=2π·2.5e9 → L=Z0/ωc=3.1831nH、C=1/(ωc·Z0)=1.2732pF；
#: w_feed=nominal_width_mm(50)@2.5GHz rogers4350b=1.1134（W50_MM 同源档）
DIPLEXER_NOMINAL: dict[str, Any] = diplexer_design_params()


def _diplexer_layout(p: dict[str, Any]) -> dict[str, Any]:
    """diplexer 几何单源（mm 入参 → 米制派生量 + 近场线清单 + 守卫）。

    守卫（渲染期显式抛错）：参数正有限、馈线宽 ≤ 板宽、元件断口在板内
    （×1.37 审计扰动域核算）、#347 输入段测量面-激励分离、断口缘与馈线缘
    显式近场线 #349 最小间距地板。
    """
    wf_mm = float(p.get("w_feed_mm", _nominal_width.W50_MM))
    l_nh = float(p.get("l_lpf_nh", DIPLEXER_NOMINAL["l_lpf_nh"]))
    c_pf = float(p.get("c_hpf_pf", DIPLEXER_NOMINAL["c_hpf_pf"]))
    for label, v in (("w_feed_mm", wf_mm), ("l_lpf_nh", l_nh),
                     ("c_hpf_pf", c_pf)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"diplexer: {label} 必须为正有限，得到 {v!r}")
    base_m = float(p.get("_base_mm", 0.4)) * 1e-3
    near_m = base_m / 4.0
    board_m = _BOARD_MM * 1e-3
    wf = wf_mm * 1e-3
    x_e = _DIP_X_ELEM_MM * 1e-3
    gap = _DIP_GAP_MM * 1e-3
    if wf >= board_m / 4.0:
        raise ValueError(
            f"diplexer: 馈线宽 w={wf_mm:.4g}mm 须 ≤ 板宽 1/4"
            f"（T 结可布前提），BOARD={_BOARD_MM:.0f}mm")
    # 元件断口在板内（×1.37 审计扰动域核算——断口位置为版图常量不受参数
    # 扰动，守卫按 _DIP_X_ELEM_MM 常量上界登记）
    if x_e + gap >= board_m - 4.0 * near_m:
        raise ValueError(
            f"diplexer: 元件断口 x={x_e * 1e3 + gap * 1e3:.3f}mm 越板边余量"
            f"（≤{board_m * 1e3 - 4.0 * near_m * 1e3:.3f}mm）——检查布局常量")
    # #347：输入段测量面（(Y_T+BOARD)/3，Y_T=0）与 FeedShift（10·NEAR）分离
    meas1 = board_m / 3.0
    if not meas1 - 10.0 * near_m >= 3.9 * near_m:
        raise ValueError(
            f"diplexer: 输入段 MeasPlaneShift/FeedShift 间距 "
            f"{(meas1 - 10.0 * near_m) * 1e6:.1f}µm < 3.9·NEAR（#347；"
            "粗网格档收紧 mesh_resolution_mm）")
    near_x = [-wf / 2, wf / 2, x_e, x_e + gap, -x_e, -(x_e + gap)]
    near_y = [-wf / 2, wf / 2, 0.0]
    return {
        "wf": wf, "l1": l_nh * 1e-9, "c1": c_pf * 1e-12,
        "x_e": x_e, "gap": gap, "board": board_m,
        "near_x": near_x, "near_y": near_y,
    }


def _diplexer_lines(p: dict[str, Any]) -> str:
    # Diplexer 几何段（TA-5）：输入馈线 + 微带 T 结 + LPF/HPF 双臂（一阶
    # CR 对，LumpedElement 断口桥接）。派生量以字面量注入（layout 单源
    # _diplexer_layout，含守卫）。三端口激励轮转（#208）：excite 由渲染器
    # 注入的 _excite_port 参数化。
    lay = _diplexer_layout(p)
    wf = lay["wf"]
    x_e = lay["x_e"]
    x_eg = lay["x_e"] + lay["gap"]
    return f'''# ── diplexer 几何（layout 单源字面量，米；round15 TA-5）──
WF = {wf!r}            # 50Ω 馈线宽（nominal_width_mm 单源，XC-W）
L_LPF = {lay["l1"]!r}       # LPF 臂串联电感（=Z0/ωc，内核 element_values）
C_HPF = {lay["c1"]!r}       # HPF 臂串联电容（=1/(ωc·Z0)，LP→HP 对偶）
XE = {x_e!r}            # 元件断口近端 x（版图常量，电小寄生段）
GAP = {lay["gap"]!r}         # 断口长
diplexer = CSX.AddMetal("diplexer")
# 输入馈线（y 向，−BOARD→T 点 y=0）
diplexer.AddBox((-WF / 2, -BOARD, H_SUB), (WF / 2, 0, H_SUB), priority=10)
# LPF 臂（+x）：短段+串联 L 断口+stub 至 +BOARD（port2）
diplexer.AddBox((0.0, -WF / 2, H_SUB), (XE, WF / 2, H_SUB), priority=10)
diplexer.AddBox(({x_eg!r}, -WF / 2, H_SUB), (BOARD, WF / 2, H_SUB), priority=10)
# HPF 臂（−x 镜像）：短段+串联 C 断口+stub 至 −BOARD（port3）
diplexer.AddBox((-XE, -WF / 2, H_SUB), (0.0, WF / 2, H_SUB), priority=10)
diplexer.AddBox((-BOARD, -WF / 2, H_SUB), ({-x_eg!r}, WF / 2, H_SUB), priority=10)
# 一阶 CR 对集总元件（ny=0 断口桥接，atten_pi 串臂同法）
_lpf_l = CSX.AddLumpedElement("lpf_l", ny=0, caps=True, L=L_LPF)
_lpf_l.AddBox((XE, -WF / 2, H_SUB), (XE + GAP, WF / 2, H_SUB), priority=5)
_hpf_c = CSX.AddLumpedElement("hpf_c", ny=0, caps=True, C=C_HPF)
_hpf_c.AddBox((-XE - GAP, -WF / 2, H_SUB), (-XE, WF / 2, H_SUB), priority=5)
# 三端口激励轮转（#208）：主 run 仅端口 ep 激励，其余探针
_PORT_EP = {int(p.get("_excite_port", 1) or 1)}
_port1 = MSLPort(CSX, port_nr=1, metal_prop=diplexer,
                 start=np.array([WF / 2, -BOARD, H_SUB]),
                 stop=np.array([-WF / 2, 0, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == 1 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=BOARD / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=diplexer,
                 start=np.array([BOARD, WF / 2, H_SUB]),
                 stop=np.array([{x_eg!r}, -WF / 2, 0]),
                 prop_dir="x", exc_dir="z",
                 excite=1 if _PORT_EP == 2 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - {x_eg!r}) / 3, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=diplexer,
                 start=np.array([-BOARD, -WF / 2, H_SUB]),
                 stop=np.array([{-x_eg!r}, WF / 2, 0]),
                 prop_dir="x", exc_dir="z",
                 excite=1 if _PORT_EP == 3 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - {x_eg!r}) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in diplexer.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ═══ TA-6 ridged_wg ══════════════════════════════════════════════════════

#: 缺省设计点常量（与 design_params 缺省实参同源；a/b/s/l_* 为版图选择
#: 常量，d 由设计链反解——#1c 名义值禁手抄）
RIDGED_WG_A_MM = 22.86         # 外廓宽边（WR-90 口径）
RIDGED_WG_B_MM = 10.16         # 外廓窄边（b/a=0.5 标准档）
RIDGED_WG_S_MM = 9.144         # 脊宽（s/a=0.4 档）
RIDGED_WG_FC_TARGET_GHZ = 5.0  # 目标主模截止（设计链输入）
RIDGED_WG_L_RIDGE_MM = 40.0    # 脊段长（消逝衰减 ≈22dB@0.8fc 口径）
RIDGED_WG_L_FEED_MM = 25.0     # 单侧加宽馈段最短长
#: 馈段截止比（fc_feed=本值×fc_ridge；0.75 档使判读带底 0.8fc>fc_feed）
RIDGED_WG_FC_FEED_RATIO = 0.75
#: 判读带相对域（×fc_ridge）：带底/带顶——带顶 < 馈段 TE20（1.5fc 结构性）
#: 且 < 外廓 TE10（layout 守卫核算）
RIDGED_WG_F_LO_RATIO = 0.8
RIDGED_WG_F_HI_RATIO = 1.26
#: 侧向/端向空气余量（mm；≈λ0/4@带顶+4mm 圆整档，pyramid_horn 同款）
_RIDGED_WG_AIR_MARGIN_MM = 12.0
#: 端口两面内移（×BASE；horn 端口纪律：激励盒/探针面均须在 PML_8 外）
_RIDGED_WG_PORT_INSET_BASE = 16.0


#: TA-6 ridged_wg 族模板名集（render_script/geometry_spec 早分发，horn 同款）
RIDGED_WG_TEMPLATES: frozenset[str] = frozenset({"ridged_wg"})


def _ridged_wg_nominal() -> dict[str, Any]:
    """名义设计点（mm，导入期内核精算单源，#1c——horn 同款导入期综合）。"""
    return ridged_wg_design_params()


def ridged_wg_design_params(
    a_mm: float = RIDGED_WG_A_MM,
    b_mm: float = RIDGED_WG_B_MM,
    s_mm: float = RIDGED_WG_S_MM,
    fc_target_ghz: float = RIDGED_WG_FC_TARGET_GHZ,
    l_ridge_mm: float = RIDGED_WG_L_RIDGE_MM,
    l_feed_mm: float = RIDGED_WG_L_FEED_MM,
    double: bool = False,
) -> dict[str, Any]:
    """空气单脊波导名义设计点（内核精算单源，#1c——名义值禁手算捷径）。

    设计链：core.ridged_waveguide.design_ridge_depth 对 fc_target 反解脊深
    d（横磁共振方程 fc(d) 单调降二分）→ **XC-P 精度域守卫**：g/b≥0.4
    （kc 对独立 FEM +1.5%~+8% 分档域；深脊 g/b<0.4 定量不可信，内核
    docstring 精度域节）违反即 ValueError。逐键一致性由
    test_diplexer_ridged_templates 独立闭式复算钉住（4 位舍入档回代
    |Δfc|/fc ≤1e-4）。
    """
    from rfauto.core.ridged_waveguide import design_ridge_depth

    r = design_ridge_depth(float(fc_target_ghz) * 1e9, float(a_mm) * 1e-3,
                           float(b_mm) * 1e-3, float(s_mm) * 1e-3,
                           bool(double))
    if not r["gap_ratio"] >= 0.4:
        raise ValueError(
            f"ridged_wg: 名义设计点 g/b={r['gap_ratio']:.4f} < 0.4——深脊落"
            "内核精度域外（kc 对独立 FEM +1.5%~+21% 分档域只保 g/b≥0.4，"
            "内核 docstring 精度域节）；提高 fc_target 或加大 s_mm")
    return {
        "a_mm": round(float(a_mm), 4),
        "b_mm": round(float(b_mm), 4),
        "s_mm": round(float(s_mm), 4),
        "d_mm": round(float(r["d_m"]) * 1e3, 4),
        "l_ridge_mm": round(float(l_ridge_mm), 4),
        "l_feed_mm": round(float(l_feed_mm), 4),
        "er": 1.0,
        "h_mm": 0.0,
    }


RIDGED_WG_META: dict[str, Any] = {
    "f0_ghz": 5.2, "n_ports": 2,
    "extraction": "S11/S21 @ RectWGPort 1-2（解析 TE10 打在加宽馈段，Z_ref="
                  "解析波导阻抗；S21=port2.uf_inc 口径——自然升序定义端口"
                  "透射在 uf_inc，coax_wg 同款）。判读锚（预声明，真机窗）："
                  "①交越膝点 |S21| −3dB 落内核 fc·(1±8%)（脊段消逝衰减 "
                  "@0.8fc≈22dB/40mm 使过渡陡峭）；②带底消逝衰减斜率对照 "
                  "evanescent_attenuation_db；③带内 |S21| 平台≈1（馈段/脊段"
                  "单模行波）。内核裁判=ridged_waveguide.cutoff_fc_hz 同参"
                  "复算（XC-P 精度域 g/b≥0.4，名义 0.454）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["a_mm", "b_mm", "s_mm", "d_mm", "l_ridge_mm", "l_feed_mm"],
    "topology": "空气单脊矩形波导均匀段（TA-6）：脊段外廓 a×b+顶壁居中脊 "
                "s×d（y∈±l_ridge/2）+ 两端加宽馈波导 a_feed×b（H 面对称"
                "阶跃，a_feed=c/(2·0.75·fc_ridge) 结构性 >4a/3）+ 阶跃端面"
                "框板闭合（零泄漏）；双 RectWGPort 打在馈段（激励/探针面均"
                "内移 16·BASE 出 PML_8）；空气填充全金属（无介质板）",
    "param_semantics": "a_mm/b_mm=脊段外廓宽/窄边（b/a=0.5 标准档）；s_mm="
                       "脊宽（s/a=0.4 档）；d_mm=脊深（design_ridge_depth "
                       "对 fc_target=5.0GHz 反解，名义 g/b=0.454 落 XC-P "
                       "精度域 ≥0.4；g=b−d 单脊）；l_ridge_mm=脊段长"
                       "（40mm→消逝衰减 ≈22dB@0.8fc）；l_feed_mm=单侧馈段"
                       "最短长（实际域长自动外推保端口两面+余量，horn 同"
                       "款）；er=1.0/h_mm=0.0 为空气填充占位键（MATERIAL_"
                       "VALUE_PARAMS 豁免）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ0/50"
                 "（空气口径，horn 同款）；全部壁面站线（外廓缘/脊缘/馈段"
                 "缘/阶跃框/端口面）显式入网（#198）+ 全轴 1µm 近重合去重"
                 "（#152）；渲染守卫：NEAR ≤ min(s,g)/3（#266 族特征分辨）、"
                 "g/b≥0.4（XC-P 精度域）、判读带 ⊂（fc_feed, min(1.5·fc_ridge, "
                 "外廓 TE10)）单模域",
    "smoke_note": "未冒烟（离线审计过，#212，test_diplexer_ridged_templates）；"
                  "近似级别如实登记：①一阶横磁共振闭式遗漏脊缘杂散电容"
                  "（kc 高估 +1.5~+8% @g/b≥0.4 分档域，内核精度档案 WARN）；"
                  "②H 面阶跃结反射不进闭式裁判（v1 直阶跃无渐变——工程实"
                  "践为 λ/4 锥削过渡，后续变体）；③RectWGPort 打在馈段，"
                  "脊模经阶跃结的耦合损耗计入 S21；真机冒烟与 HFSS 仲裁属"
                  "后续批次（本批零发射）",
}


def ridged_wg_layout(
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    mesh_resolution_mm: float = 0.0,
) -> dict[str, Any]:
    """ridged_wg 几何/端口/域/网格单源（mm 入出；渲染器/预览 spec 同消费）。

    守卫（渲染期显式抛错）：参数正有限且几何合法（s<a、0<d<b）；
    g/b≥0.4（XC-P 精度域，深脊拒渲染）；NEAR ≤ min(s,g)/3（#266 族）；
    判读带单模域（带底 >fc_feed、带顶 <min(馈段 TE20, 外廓 TE10) 带 3%
    余量）；端口两面 + 余量由 dom_y 自动外推保证（horn 同款 #174 族）。
    """
    from rfauto.core.ridged_waveguide import (
        C0,
        RidgedWaveguide,
        cutoff_fc_hz,
        evanescent_attenuation_db,
        lambda_g_m,
    )

    nom = RIDGED_WG_NOMINAL
    a_mm = float(params.get("a_mm", nom["a_mm"]))
    b_mm = float(params.get("b_mm", nom["b_mm"]))
    s_mm = float(params.get("s_mm", nom["s_mm"]))
    d_mm = float(params.get("d_mm", nom["d_mm"]))
    lr_mm = float(params.get("l_ridge_mm", nom["l_ridge_mm"]))
    lf_mm = float(params.get("l_feed_mm", nom["l_feed_mm"]))
    for label, v in (("a_mm", a_mm), ("b_mm", b_mm), ("s_mm", s_mm),
                     ("d_mm", d_mm), ("l_ridge_mm", lr_mm),
                     ("l_feed_mm", lf_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"ridged_wg: {label} 必须为正有限，得到 {v!r}")
    if not s_mm < a_mm:
        raise ValueError(
            f"ridged_wg: 脊宽 s={s_mm:.4g}mm 须 < 外廓宽 a={a_mm:.4g}mm"
            "（ridged_waveguide 同款前提）")
    if not d_mm < b_mm:
        raise ValueError(
            f"ridged_wg: 脊深 d={d_mm:.4g}mm 须 < 窄边 b={b_mm:.4g}mm"
            "（单脊 g=b−d>0）")
    f0 = 0.5 * (freq_range_ghz[0] + freq_range_ghz[1])
    fc_band = abs(freq_range_ghz[1] - freq_range_ghz[0]) / 2.0
    f_lo = f0 - fc_band
    f_hi = f0 + fc_band
    wg = RidgedWaveguide(a=a_mm * 1e-3, b=b_mm * 1e-3, s=s_mm * 1e-3,
                         d=d_mm * 1e-3, double=False)
    gap_ratio = wg.gap_ratio
    if not gap_ratio >= 0.4:
        raise ValueError(
            f"ridged_wg: g/b={gap_ratio:.4f} < 0.4——深脊落内核精度域外"
            "（XC-P：kc 对独立 FEM +1.5%~+21% 分档域只保 g/b≥0.4；提高 "
            "fc_target 或减小 d_mm/加大 b_mm）")
    fc_ridge = cutoff_fc_hz(wg)
    fc_outline = C0 / (2.0 * a_mm * 1e-3)
    fc_feed = RIDGED_WG_FC_FEED_RATIO * fc_ridge
    a_feed_mm = C0 / (2.0 * fc_feed) * 1e3
    if not a_feed_mm > a_mm:
        raise ValueError(
            f"ridged_wg: 馈段宽 a_feed={a_feed_mm:.4g}mm 须 > 外廓 "
            f"a={a_mm:.4g}mm（构造不变式 1.333a 违背——检查 fc_feed 比）")
    # 判读带单模域守卫（GHz 面）：带底馈段行波（>fc_feed 留 3% 余量）、
    # 带顶低于馈段 TE20（=1.5·fc_ridge）与外廓 TE10 二者的 97%
    fc_feed_ghz = fc_feed / 1e9
    f_min_ok = fc_feed_ghz * 1.03
    f_max_cap = min(RIDGED_WG_FC_FEED_RATIO / 0.5 * fc_ridge,
                    fc_outline) / 1e9 * 0.97
    if not f_lo > f_min_ok:
        raise ValueError(
            f"ridged_wg: 判读带底 {f_lo:.4g}GHz ≤ 馈段截止 1.03·fc_feed="
            f"{f_min_ok:.4g}GHz（馈段须行波）——上移频带")
    if not f_hi < f_max_cap:
        raise ValueError(
            f"ridged_wg: 判读带顶 {f_hi:.4g}GHz ≥ 单模上限 "
            f"{f_max_cap:.4g}GHz（min(馈段 TE20, 外廓 TE10)·0.97）——下移频带")
    lambda0_mm = 299.792458 / f_hi   # 带顶空气波长 mm（f_hi GHz）
    base_mm = (float(mesh_resolution_mm) if mesh_resolution_mm
               else lambda0_mm / 50.0)
    near_mm = base_mm / 4.0
    feat_mm = min(s_mm, (b_mm - d_mm))
    if not near_mm <= feat_mm / 3.0:
        raise ValueError(
            f"ridged_wg: NEAR={near_mm:.4g}mm > 最小特征 min(s,g)/3="
            f"{feat_mm / 3.0:.4g}mm（#266 族特征分辨守卫）——加密 "
            "mesh_resolution_mm")
    # 域：x/z 侧向 MUR 余量；y 端向含脊段+馈段+端口两面+余量（自动外推）
    dom_x_mm = a_feed_mm / 2.0 + _RIDGED_WG_AIR_MARGIN_MM
    dom_z_mm = b_mm / 2.0 + _RIDGED_WG_AIR_MARGIN_MM
    port_inset_mm = _RIDGED_WG_PORT_INSET_BASE * base_mm
    meas_len_mm = max(6.0 * near_mm, 1.0, port_inset_mm)
    need_y = lr_mm / 2.0 + port_inset_mm + meas_len_mm + 4.0 * base_mm
    dom_y_mm = max(lr_mm / 2.0 + lf_mm, need_y)
    port1_y0 = -dom_y_mm + port_inset_mm
    port1_y1 = port1_y0 + meas_len_mm
    port2_y1 = dom_y_mm - port_inset_mm
    port2_y0 = port2_y1 - meas_len_mm
    # 壁面站线（#198）
    x_lines = sorted({-a_feed_mm / 2, -a_mm / 2, -s_mm / 2, s_mm / 2,
                      a_mm / 2, a_feed_mm / 2})
    z_lines = sorted({-b_mm / 2, b_mm / 2 - d_mm, b_mm / 2})
    y_lines = sorted({-dom_y_mm, port1_y0, port1_y1, -lr_mm / 2, lr_mm / 2,
                      port2_y0, port2_y1, dom_y_mm})
    # 内核判读锚（渲染脚本 summary 回显字面量；真机判读同源）。锚点取声明
    # 判读带相对域（0.8·fc，恒消逝域）而非渲染频带——geometry_spec 以零宽
    # 频带调本函数（f_lo=f_hi=f0），渲染频带不必跨截止
    atten_lo_db = evanescent_attenuation_db(
        lr_mm * 1e-3, RIDGED_WG_F_LO_RATIO * fc_ridge, wg)
    lam_g_f0_mm = (lambda_g_m(f0 * 1e9, wg) * 1e3
                   if f0 * 1e9 > fc_ridge else None)
    return {
        "a_mm": a_mm, "b_mm": b_mm, "s_mm": s_mm, "d_mm": d_mm,
        "l_ridge_mm": lr_mm, "l_feed_mm": lf_mm, "er": 1.0,
        "f0_ghz": f0, "fc_band_ghz": fc_band, "f_lo_ghz": f_lo,
        "f_hi_ghz": f_hi, "lambda0_mm": lambda0_mm,
        "base_mm": base_mm, "near_mm": near_mm,
        "gap_ratio": gap_ratio, "fc_ridge_ghz": fc_ridge / 1e9,
        "fc_outline_ghz": fc_outline / 1e9, "fc_feed_ghz": fc_feed / 1e9,
        "a_feed_mm": a_feed_mm,
        "atten_lo_db": atten_lo_db, "lam_g_f0_mm": lam_g_f0_mm,
        "dom_x_mm": dom_x_mm, "dom_y_mm": dom_y_mm, "dom_z_mm": dom_z_mm,
        "port_inset_mm": port_inset_mm, "meas_len_mm": meas_len_mm,
        "port1_y0_mm": port1_y0, "port1_y1_mm": port1_y1,
        "port2_y0_mm": port2_y0, "port2_y1_mm": port2_y1,
        "x_lines_mm": x_lines, "y_lines_mm": y_lines, "z_lines_mm": z_lines,
        "port": {
            "start_mm": [-a_feed_mm / 2, port1_y0, -b_mm / 2],
            "stop_mm": [a_feed_mm / 2, port1_y1, b_mm / 2],
            # 绑定参数序（horn 同款）：a=第一横向轴（exc_dir=y 时=z）=b、
            # b=第二横向轴（=x）=a_feed，mode="TE01"（E 沿 z、半波沿 x）
            "a_bind_mm": b_mm, "b_bind_mm": a_feed_mm,
            "start2_mm": [-a_feed_mm / 2, port2_y0, -b_mm / 2],
            "stop2_mm": [a_feed_mm / 2, port2_y1, b_mm / 2],
        },
    }


def ridged_wg_geometry_spec(
    params: dict[str, Any],
    substrate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ridged_wg UI 预览 spec（mm；early-dispatch 自 geometry_spec）。"""
    del substrate   # 空气填充器件，无板材（段头注释）
    lay = ridged_wg_layout(
        params, (RIDGED_WG_META["f0_ghz"], RIDGED_WG_META["f0_ghz"]))
    a, b = lay["a_mm"], lay["b_mm"]
    af, lr, lfed = lay["a_feed_mm"], lay["l_ridge_mm"], lay["dom_y_mm"]
    s, d = lay["s_mm"], lay["d_mm"]
    boxes = [
        {"name": "ridge_wall_xp（脊段壁）", "material": "metal",
         "start_mm": [a / 2, -lr / 2, -b / 2], "stop_mm": [a / 2, lr / 2, b / 2]},
        {"name": "ridge_wall_xm（脊段壁）", "material": "metal",
         "start_mm": [-a / 2, -lr / 2, -b / 2],
         "stop_mm": [-a / 2, lr / 2, b / 2]},
        {"name": "ridge_wall_zp（脊段壁）", "material": "metal",
         "start_mm": [-a / 2, -lr / 2, b / 2], "stop_mm": [a / 2, lr / 2, b / 2]},
        {"name": "ridge_wall_zm（脊段壁）", "material": "metal",
         "start_mm": [-a / 2, -lr / 2, -b / 2],
         "stop_mm": [a / 2, lr / 2, -b / 2]},
        {"name": "ridge_block（顶壁居中脊）", "material": "metal",
         "start_mm": [-s / 2, -lr / 2, b / 2 - d],
         "stop_mm": [s / 2, lr / 2, b / 2]},
        {"name": "feed_wall_xp（加宽馈段壁，±y 对称）", "material": "metal",
         "start_mm": [af / 2, -lfed, -b / 2],
         "stop_mm": [af / 2, -lr / 2, b / 2]},
        {"name": "feed_wall_xm（加宽馈段壁，±y 对称）", "material": "metal",
         "start_mm": [-af / 2, -lfed, -b / 2],
         "stop_mm": [-af / 2, -lr / 2, b / 2]},
        {"name": "feed_wall_zp（加宽馈段壁，±y 对称）", "material": "metal",
         "start_mm": [-af / 2, -lfed, b / 2],
         "stop_mm": [af / 2, -lr / 2, b / 2]},
        {"name": "feed_wall_zm（加宽馈段壁，±y 对称）", "material": "metal",
         "start_mm": [-af / 2, -lfed, -b / 2],
         "stop_mm": [af / 2, -lr / 2, -b / 2]},
        {"name": "feed_wall_xp（加宽馈段壁，+y）", "material": "metal",
         "start_mm": [af / 2, lr / 2, -b / 2],
         "stop_mm": [af / 2, lfed, b / 2]},
        {"name": "feed_wall_xm（加宽馈段壁，+y）", "material": "metal",
         "start_mm": [-af / 2, lr / 2, -b / 2],
         "stop_mm": [-af / 2, lfed, b / 2]},
        {"name": "feed_wall_zp（加宽馈段壁，+y）", "material": "metal",
         "start_mm": [-af / 2, lr / 2, b / 2],
         "stop_mm": [af / 2, lfed, b / 2]},
        {"name": "feed_wall_zm（加宽馈段壁，+y）", "material": "metal",
         "start_mm": [-af / 2, lr / 2, -b / 2],
         "stop_mm": [af / 2, lfed, -b / 2]},
        {"name": "frame（H 面阶跃端面框板，±y 对称）", "material": "metal",
         "start_mm": [a / 2, -lr / 2, -b / 2],
         "stop_mm": [af / 2, -lr / 2, b / 2]},
        {"name": "frame（H 面阶跃端面框板，−x 侧）", "material": "metal",
         "start_mm": [-af / 2, -lr / 2, -b / 2],
         "stop_mm": [-a / 2, -lr / 2, b / 2]},
        {"name": "frame（H 面阶跃端面框板，+y 端）", "material": "metal",
         "start_mm": [a / 2, lr / 2, -b / 2],
         "stop_mm": [af / 2, lr / 2, b / 2]},
        {"name": "frame（H 面阶跃端面框板，+y −x 侧）", "material": "metal",
         "start_mm": [-af / 2, lr / 2, -b / 2],
         "stop_mm": [-a / 2, lr / 2, b / 2]},
    ]
    ports = [
        {"name": "Port1（RectWGPort，解析 TE10，−y 馈段）",
         "pos_mm": [0.0, lay["port1_y0_mm"], 0.0], "dir": [0.0, 1.0, 0.0]},
        {"name": "Port2（RectWGPort，解析 TE10，+y 馈段）",
         "pos_mm": [0.0, lay["port2_y1_mm"], 0.0], "dir": [0.0, 1.0, 0.0]},
    ]
    return {"template": "ridged_wg",
            "substrate": {"er": 1.0, "h_mm": 0.0, "tan_d": 0.0},
            "boxes": boxes, "ports": ports, "elements": []}


def ridged_wg_render(
    template: str,
    params: dict[str, Any],
    freq_range_ghz: tuple[float, float],
    *,
    mesh_resolution_mm: float = 0.0,
    substrate: dict[str, Any] | None = None,
    excite_port: int = 1,
    far_field: bool = False,
) -> str:
    """ridged_wg 整脚本渲染器（早分发自 render_script；horn 同款结构）。

    双 RectWGPort 解析 TE10 打在加宽馈段（Z_ref=解析波导阻抗）；y 轴双端
    PML_8、x/z MUR；空气填充无介质板。2 端口单激励（S21 同 run 直接可判，
    无轮转开销——excite_port 仅接受 1，显式拒绝不静默）；far_field 拒绝
    （封闭导波器件，render_script 通用守卫已挡，此处显式冗余登记）。
    """
    if int(excite_port) != 1:
        raise ValueError(
            f"ridged_wg 双端口单激励模板（无轮转），excite_port={excite_port}")
    if far_field:
        raise ValueError(
            "ridged_wg: 封闭导波器件无远场面（render_script 通用守卫冗余登记）")
    del template, substrate
    lay = ridged_wg_layout(params, freq_range_ghz, mesh_resolution_mm)
    f0 = lay["f0_ghz"] * 1e9
    fc = lay["fc_band_ghz"] * 1e9
    base = lay["base_mm"] * 1e-3
    near = lay["near_mm"] * 1e-3
    dom_x = lay["dom_x_mm"] * 1e-3
    dom_y = lay["dom_y_mm"] * 1e-3
    dom_z = lay["dom_z_mm"] * 1e-3
    nrts = int(params.get("_nrts", 100000) or 100000)

    def m(v: float) -> float:
        return float(v) * 1e-3

    a = m(lay["a_mm"])
    b = m(lay["b_mm"])
    s = m(lay["s_mm"])
    d = m(lay["d_mm"])
    lr = m(lay["l_ridge_mm"])
    af = m(lay["a_feed_mm"])
    # 盒顶点字面量预计算（复杂 f-string 表达式易错——#108 纪律，插值只用
    # 简单变量 repr）
    axp, axm = a / 2, -a / 2
    zbp, zbm = b / 2, -b / 2
    zrg = b / 2 - d              # 脊块底面 z
    yrp, yrm = lr / 2, -lr / 2
    sxp, sxm = s / 2, -s / 2
    afp, afm = af / 2, -af / 2
    dom_y_ = dom_y
    box_txt = f'''# 脊段四壁 + 顶壁居中脊（y∈±LR）
wall.AddBox(({axp!r}, {yrm!r}, {zbm!r}), ({axp!r}, {yrp!r}, {zbp!r}), priority=10)
wall.AddBox(({axm!r}, {yrm!r}, {zbm!r}), ({axm!r}, {yrp!r}, {zbp!r}), priority=10)
wall.AddBox(({axm!r}, {yrm!r}, {zbp!r}), ({axp!r}, {yrp!r}, {zbp!r}), priority=10)
wall.AddBox(({axm!r}, {yrm!r}, {zbm!r}), ({axp!r}, {yrp!r}, {zbm!r}), priority=10)
wall.AddBox(({sxm!r}, {yrm!r}, {zrg!r}), ({sxp!r}, {yrp!r}, {zbp!r}), priority=10)   # 脊块（顶壁悬出）
# 加宽馈段四壁 ×2（y∈[−DOM_Y,−LR/2] 与 [LR/2,DOM_Y]）+ H 面阶跃端面框板 ×2×2
for _sgn in (-1.0, 1.0):
    _ya, _yb = sorted((_sgn * {yrp!r}, _sgn * {dom_y_!r}))
    wall.AddBox(({afp!r}, _ya, {zbm!r}), ({afp!r}, _yb, {zbp!r}), priority=10)
    wall.AddBox(({afm!r}, _ya, {zbm!r}), ({afm!r}, _yb, {zbp!r}), priority=10)
    wall.AddBox(({afm!r}, _ya, {zbp!r}), ({afp!r}, _yb, {zbp!r}), priority=10)
    wall.AddBox(({afm!r}, _ya, {zbm!r}), ({afp!r}, _yb, {zbm!r}), priority=10)
    # 阶跃端面框板（y=±LR/2 平面，x∈[A/2,AF/2] 与镜像；闭合腔壁零泄漏）
    _yj = _sgn * {yrp!r}
    wall.AddBox(({axp!r}, _yj, {zbm!r}), ({afp!r}, _yj, {zbp!r}), priority=10)
    wall.AddBox(({afm!r}, _yj, {zbm!r}), ({axm!r}, _yj, {zbp!r}), priority=10)
'''
    x_lit = ", ".join(repr(m(v)) for v in lay["x_lines_mm"])
    y_lit = ", ".join(repr(m(v)) for v in lay["y_lines_mm"])
    z_lit = ", ".join(repr(m(v)) for v in lay["z_lines_mm"])
    p = lay["port"]
    a_bind = m(p["a_bind_mm"])
    b_bind = m(p["b_bind_mm"])
    port_lit = (
        f"    start=np.array([{m(p['start_mm'][0])!r}, "
        f"{m(p['start_mm'][1])!r}, {m(p['start_mm'][2])!r}]),\n"
        f"    stop=np.array([{m(p['stop_mm'][0])!r}, "
        f"{m(p['stop_mm'][1])!r}, {m(p['stop_mm'][2])!r}]),\n")
    port2_lit = (
        f"    start=np.array([{m(p['start2_mm'][0])!r}, "
        f"{m(p['start2_mm'][1])!r}, {m(p['start2_mm'][2])!r}]),\n"
        f"    stop=np.array([{m(p['stop2_mm'][0])!r}, "
        f"{m(p['stop2_mm'][1])!r}, {m(p['stop2_mm'][2])!r}]),\n")
    return f'''#!/usr/bin/env python3
"""openEMS ridged_wg script (rfauto round15 TA-6 auto-generated).

几何/端口/网格口径见 src/rfauto/adapters/oe_templates/render_diplexer_ridged.py
段头注。空气单脊矩形波导均匀段+两端加宽馈段（H 面对称阶跃）；闭式裁判=
core/ridged_waveguide（一阶横磁共振，XC-P 精度域 g/b≥0.4）；真机冒烟与
HFSS 仲裁=后续窗（本批零发射）。
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
ER = {lay["er"]!r}   # 空气填充（summary 回显消费；无介质板）
H_SUB = 0.0   # 无介质板器件占位（审计④域口径；段头注释）
BASE = {base!r}   # 网格 base：自动档 λ0/50（空气口径）
NEAR = {near!r}   # 近特征区 = base/4
DOM_X = {dom_x!r}
DOM_Y = {dom_y!r}
DOM_Z = {dom_z!r}
NRTS = {nrts}
SIM_PATH = os.path.abspath("fdtd")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CSX = ContinuousStructure()
FDTD = openEMS(NrTS=NRTS)   # 官方口径：不设 EndCriteria，能量判据停机
FDTD.SetCSX(CSX)
FDTD.SetGaussExcite(F0, FC)
# 封闭导波器件：y 轴（端口轴）双端 PML_8（端口面贴 PML 域边内移 16·BASE，
# horn 端口纪律），x/z MUR
FDTD.SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "MUR", "MUR"])

mesh = CSX.GetGrid()
# 全部壁面站线显式入网（#198）：特征区 NEAR 细分→域界补入→空气区 BASE
# 粗化（双档平滑把细格限于壁面走廊）
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
mesh.AddLine("z", np.array([-DOM_Z, DOM_Z]))
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

# ── 几何：脊段（外廓 a×b+顶壁居中脊 s×d）+ 两端加宽馈段（a_feed×b，H 面
#    对称阶跃）+ 阶跃端面框板（零泄漏）；零厚 PEC 片+脊块实体 ──
wall = CSX.AddMetal("ridged_wg_wall")
{box_txt}
# ── 端口：双 RectWGPort 解析 TE10 打在加宽馈段（pyramid_horn 同法）──
# 绑定参数序：a=第一横向轴（exc_dir=y 时=z）=b、b=第二横向轴（=x）=
# a_feed、mode="TE01"（M=0,N=1：E 沿 z、半波沿 x）。Z_ref 缺省=解析波导
# 阻抗 ZL=k·Z0/β（WaveguidePort.CalcPort 填）。
_port1 = RectWGPort(CSX, port_nr=1,
{port_lit}    exc_dir="y", a={a_bind!r}, b={b_bind!r},
    mode_name="TE01", excite=1)
_port2 = RectWGPort(CSX, port_nr=2,
{port2_lit}    exc_dir="y", a={a_bind!r}, b={b_bind!r},
    mode_name="TE01", excite=0)

# ── 求解 ──
# RFAUTO_SKIP_RUN=1：只重跑后处理（复用既有 fdtd/ 时域产物；几何段未变时合法）
if os.environ.get("RFAUTO_SKIP_RUN") != "1":
    FDTD.Run(SIM_PATH, verbose=0, disable_dumps=True, cleanup=True)

# ── 后处理：双端口 S 参数（Z_ref=馈段解析 TE10 波导阻抗）──
# port1=−y 侧（direction=+1 指向结构内）：S11=uf_ref/uf_inc（uf_ref=反向
# 行波=反射）；port2=+y 侧自然升序定义（direction=+1 向外）——透射行波
# 在 uf_inc（coax_wg 同款口径）。
f = np.linspace(F0 - FC, F0 + FC, 401)
_port1.CalcPort(SIM_PATH, f)
_port2.CalcPort(SIM_PATH, f)
S11 = _port1.uf_ref / _port1.uf_inc
S21 = _port2.uf_inc / _port1.uf_inc

with open(os.path.join(SCRIPT_DIR, "sparams.csv"), "w", newline="") as fh:
    w_ = csv.writer(fh)
    w_.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
    for _i, _fi in enumerate(f):
        w_.writerow([_fi, S11[_i].real, S11[_i].imag, S21[_i].real, S21[_i].imag])

# 内核判读锚回显（渲染期 layout 内核精算字面量；真机判读同源单源）
summary = dict(
    ok=True, template="ridged_wg", f0_hz=F0, fc_hz=FC,
    freq_band_ghz=[(F0 - FC) / 1e9, (F0 + FC) / 1e9],
    a_mm={lay["a_mm"]!r}, b_mm={lay["b_mm"]!r}, s_mm={lay["s_mm"]!r},
    d_mm={lay["d_mm"]!r}, l_ridge_mm={lay["l_ridge_mm"]!r},
    a_feed_mm={lay["a_feed_mm"]!r}, gap_ratio={lay["gap_ratio"]!r},
    fc_ridge_ghz={lay["fc_ridge_ghz"]!r},
    fc_outline_ghz={lay["fc_outline_ghz"]!r},
    fc_feed_ghz={lay["fc_feed_ghz"]!r},
    evanescent_atten_band_lo_db={lay["atten_lo_db"]!r},
    lambda_g_f0_mm={lay["lam_g_f0_mm"]!r},
    nrts=NRTS,
    mesh_lines=[int(len(mesh.GetLines(_a))) for _a in ("x", "y", "z")],
)
with open(os.path.join(SCRIPT_DIR, "ridged_wg_meta.json"), "w",
          encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=1)
print("rfauto ridged_wg simulation done")
'''


# ═══ 名义设计点（导入期内核精算，horn 同款）══════════════════════════════
RIDGED_WG_NOMINAL: dict[str, Any] = _ridged_wg_nominal()


# ── 注册：同对象入表（单一事实源；尾部追加 #247 键集口径）─────────────────
TEMPLATE_META["diplexer"] = DIPLEXER_META
TEMPLATE_NOMINAL["diplexer"] = DIPLEXER_NOMINAL
_TEMPLATE_PORT_AXES["diplexer"] = ("x", "y")
_TEMPLATE_RADIATOR["diplexer"] = False

TEMPLATE_META["ridged_wg"] = RIDGED_WG_META
TEMPLATE_NOMINAL["ridged_wg"] = RIDGED_WG_NOMINAL
_TEMPLATE_PORT_AXES["ridged_wg"] = ("y",)
_TEMPLATE_RADIATOR["ridged_wg"] = False
