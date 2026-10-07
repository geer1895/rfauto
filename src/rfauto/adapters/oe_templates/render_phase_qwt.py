"""TA-1 Schiffman 宽带移相器 + TA-2 多节 λ/4 阻抗变换器（TA 批，2026-10-02）。

方案锚：研究扩充 系列第十五轮（2026-10-02）§二·2
TA-1/TA-2——「内核就绪缺模板」件：闭式全套在 core/synthesis.py
（synthesize_schiffman / schiffman_delta_phase / synthesize_multisection_
quarter_wave），本模块只做几何渲染注册与名义设计链（#1c：数值全部内核
精算，零手抄毫米数；本文件零物理数字产出——铁律 7）。

── TA-1 schiffman（90° 定差移相器，4 端口轮转）──────────────────────────
器件=耦合段（远端桥接的平行耦合 U 形全通段，Schiffman 1958 C-section）
+ 参考直通段（长 L_ref，Schiffman 惯例 3L 语义由内核闭式解出实际值），
双路径同板、DC 隔离——差分相移 Δφ(f)=Φ_ref−Φ_c 是器件定义量，四端口
单激励轮转（#208 口径同 ratrace/lange）一次装配全矩阵后离线取
Δφ(f)=∠S43−∠S21。
- 全通匹配条件 Z0e·Z0o=Z0²（50²）由设计链构造保证（ρ=Z0e/Z0o 名义 2.0）；
- **低 εr 基板可达域上限**：KJ 零厚耦合微带反解在 RO4350B h=0.508mm 上
  ρ≳2.2 即不可达（内核显式 ValueError 不外推；Schiffman 原文 ρ≈3 于
  εr≈9 高 εr 氧化铝）——名义取 ρ=2.0（可达域内经典值），带内平坦度
  ±25% 窗 max|Δφ−90°|≈7.2°（kernel phase_flatness，如实登记不凑 ρ=3）；
- 测量面经 MeasPlaneShift 解嵌到耦合段/参考段端面（段内物理直接对照
  schiffman_delta_phase 闭式）；端面"孤立线↔耦合对"阶跃寄生不建模
  （Schiffman 原文口径，smoke_note 如实登记）；
- 缝分辨：耦合缝名义 0.0692mm < 任何实用 NEAR——按 #311 缝中点精确
  入网法处理（x=0 中线在缺省近点集 + ±gap/2 带缘精确入网 → 缝内内部
  线 ≥1 恒成立），不设 NEAR≤gap/3 硬守卫（C4 决议口径：精确入网线
  SmoothMesh 不吞）。

── TA-2 qwt_multisection（多节 λ/4 阻抗变换器，1 端口）──────────────────
器件=50Ω 馈线 + N 节 λ/4 均匀线级联（节阻抗由
synthesize_multisection_quarter_wave 闭式给出：binomial/chebyshev 一阶
小反射表驱动）+ 末端 LumpedElement R=ZL 端接到地（mmwave_series_array
链末负载同法）——50→ZL 变换器的匹配带 S11 深零/纹波指纹在单端口测量
下完整可判，无轮转开销。
- 名义设计点：Z0=50 → ZL=100、N=3、binomial、Γm=-20dB @2.5GHz
  （Pozar 4ed Binomial Multisection Matching Transformer 节口径；奇数 N
  中心频率精确匹配 |S11(f0)|≈0）；
- 节间阶梯跳宽不连续性不进闭式裁判（stepped_impedance 同口径，离线
  裁判=skrf N 节理想 TL 级联 50Ω 端接，引擎-理想偏差即阶梯寄生贡献）。

近似级别（如实登记，#122）：两模板均准静态 HJ/KJ 闭式链（无色散）、
零厚度金属 PEC、Schiffman 参考段 εeff 取偶/奇模相速平均口径（内核
v1 声明）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import (
    _TEMPLATE_PORT_AXES,
    _TEMPLATE_RADIATOR,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
)

#: 板边半宽——与 render_script 共享字面量 BOARD=60mm 同源（禁改共享字面量，
#: 布局守卫按此值核算；_board_mm 旋钮渲染期单变量覆盖时不经本模块）
_BOARD_MM = 60.0

# ═══ TA-1 schiffman ══════════════════════════════════════════════════════

#: 缺省设计点常量（与 TEMPLATE_NOMINAL/design_params 缺省实参同源）
SCHIFFMAN_F0_GHZ = 2.5
SCHIFFMAN_RHO = 2.0          # ρ=Z0e/Z0o（可达域内经典档，见模块头注）
SCHIFFMAN_Z0_OHM = 50.0
SCHIFFMAN_DELTA_DEG = 90.0
#: 耦合段近端 y（板边侧锚定，mm）——段长扰动向 +y 生长，端口/馈线长度恒定
_SCHIFFMAN_Y0_MM = -50.0
#: 参考段线中心 x（mm）——与耦合对（外缘 ≈0.94mm）净空 ≥3·h_sub 宽裕
_SCHIFFMAN_X_REF_MM = 16.0


SCHIFFMAN_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 4,
    "extraction": "全 S 矩阵 4×4 @ .s4p（官方激励轮转 4 run，#208 口径同 "
                  "ratrace/lange；port1/2=耦合段两端、port3/4=参考段两端）。"
                  "裁判=core.synthesis.schiffman_delta_phase 闭式：Δφ(f)=deg"
                  "(unwrap∠S43)−deg(unwrap∠S21)（两路径测量面经 MeasPlaneShift "
                  "解嵌到段端面），@f0=+90°、带内平坦度对照 kernel "
                  "phase_flatness；openEMS DFT e^{−jωt} 口径（#253②），skrf "
                  "装配侧符号取反如实换算",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "gap_mm", "l_coupled_mm", "l_ref_mm", "w_ref_mm"],
    "topology": "Schiffman 90° 定差移相器（TA-1）：耦合段=远端桥接平行耦合 "
                "U 形全通段（C-section：双带条 x=±(gap/2+w/2) 沿 y、远端桥带 "
                "闭合，port1/2 在 −BOARD 板边近端）+ 参考直通段（50Ω，长 "
                "l_ref，port3/4 在 ±BOARD 板边）；双路径同板 DC 隔离（净空 "
                "≥3·h_sub）；全通匹配 Z0e·Z0o=Z0²=2500 由设计链构造保证",
    "param_semantics": "w_mm=耦合段带条宽（Z0e/Z0o 经 KJ 反解联动，"
                       "schiffman_design_params 单源）；gap_mm=耦合缝宽（同 "
                       "KJ 反解；ρ=Z0e/Z0o 名义 2.0——低 εr 可达域上限见段头"
                       "注）；l_coupled_mm=耦合段长（θ0=ratio·90° 电长度闭式，"
                       "ratio=1 经典 λ/4 耦合段）；l_ref_mm=参考段长（Δφ=90° "
                       "目标对 L_ref 线性一步反解，Schiffman 3L 惯例语义由内"
                       "核解出实际值）；w_ref_mm=参考段/馈线宽（50Ω HJ 精算）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
                 "（官方口径）；耦合缝 0.0692mm<NEAR 按 #311 缝中点精确入网"
                 "（x=0 中线+±gap/2 带缘精确 AddLine，缝内内部线 ≥1 恒成立，"
                 "不设 NEAR≤gap/3 硬守卫——C4 决议口径）；耦合对四带缘/桥带"
                 "缘/段两端/参考段两端/参考带缘精确入网（#198）；真机建议显"
                 "式 mesh_resolution_mm≤0.3（缝邻域分辨）；全轴 1µm 近重合去"
                 "重（#152）；端口面贴 PML_8 域边（#154 前节）",
    "smoke_note": "未冒烟（离线审计过，#212，test_schiffman_qwt_templates）；"
                  "近似级别如实登记：①准静态 εeff 逐模常数化无色散（内核 v1 "
                  "声明）；②参考段 εeff 取偶/奇模相速平均口径（内核 v1）；"
                  "③测量面解嵌到段端面，端面孤立线↔耦合对阶跃寄生不建模"
                  "（Schiffman 原文口径）；④ρ=2.0 平坦度 ±25% 窗 max 偏差 "
                  "≈7.2°（低 εr 可达域内，不凑 ρ=3）；真机冒烟与 HFSS 仲裁"
                  "属后续批次（本批零发射）",
}


def schiffman_design_params(
    f0_ghz: float = SCHIFFMAN_F0_GHZ,
    rho: float = SCHIFFMAN_RHO,
    z0_ohm: float = SCHIFFMAN_Z0_OHM,
    delta_phase_deg: float = SCHIFFMAN_DELTA_DEG,
) -> dict[str, Any]:
    """Schiffman 移相器名义设计点（内核精算单源，#1c——名义值禁手算捷径）。

    设计链：全通匹配条件构造 (Z0e, Z0o)=(Z0·√ρ, Z0/√ρ) →
    synthesize_schiffman 闭式（KJ 反解 (w,s) + θ0 电长度耦合段长 + Δφ=90°
    对 L_ref 一步反解）→ 参考段 50Ω 线宽 inverse_width HJ 精算。
    恒等式由 test_schiffman_qwt_templates 综合反解自洽测试钉住（逐键
    rtol 1e-9 对 TEMPLATE_NOMINAL 字面量）。
    """
    from rfauto.core.synthesis import (
        Stackup,
        inverse_width,
        synthesize_schiffman,
    )

    if not (rho > 1.0):
        raise ValueError(f"rho=Z0e/Z0o 须 >1，得 {rho!r}")
    z_e = float(z0_ohm) * math.sqrt(rho)
    z_o = float(z0_ohm) / math.sqrt(rho)
    sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
    d = synthesize_schiffman(z_e, z_o, float(sub.epsilon_r),
                             float(sub.thickness_mm) * 1e-3, float(f0_ghz),
                             delta_phase_deg=float(delta_phase_deg))
    w_ref, _, status = inverse_width(float(z0_ohm), float(f0_ghz), sub)
    if status != "ok":
        raise ValueError(f"schiffman 参考段线宽反解未收敛: {status}")
    return {
        "w_mm": round(float(d["geometry_mm"]["w_mm"]), 4),
        "gap_mm": round(float(d["geometry_mm"]["s_mm"]), 4),
        "l_coupled_mm": round(float(d["coupled_length_m"]) * 1e3, 6),
        "l_ref_mm": round(float(d["reference_length_m"]) * 1e3, 6),
        "w_ref_mm": round(float(w_ref), 4),
    }


#: 名义设计点（2026-10-02 由 schiffman_design_params() 缺省实参精算，
#: 字面量落表避免模块导入期 IO；逐位一致性由自洽测试钉住）：
#: ρ=2.0 → (Z0e,Z0o)=(70.7107, 35.3553)Ω；KJ 反解 w=0.905113436/s=
#: 0.06920872mm（εeff_e=2.9858/εeff_o=2.4581）→ L_c=18.19263268mm、
#: L_ref=54.577898041mm（Δφ@f0=+90° 精确回代）；w_ref=1.1134（50Ω HJ，
#: mline/gysel 同源档）
SCHIFFMAN_NOMINAL: dict[str, Any] = {
    "w_mm": 0.9051,
    "gap_mm": 0.0692,
    "l_coupled_mm": 18.192633,
    "l_ref_mm": 54.577898,
    "w_ref_mm": 1.1134,
}


def _schiffman_layout(p: dict[str, Any]) -> dict[str, Any]:
    """Schiffman 几何单源（mm 入参 → 米制派生量 + 近场线清单 + 守卫）。

    渲染段（_schiffman_lines）、近场线（grid._near_points，近场线由本单源
    给出——ms_unit_layout 同制度）、UI 预览（render_core.geometry_spec）
    与离线审计四方消费。

    守卫（渲染期显式抛错）：
    - 参数正有限、桥带/参考段在板内（l_ref×1.37 审计扰动域核算）；
    - 路径净空：参考段内缘−耦合对外缘 ≥ 3·h_sub（路径 DC 隔离物理前提）；
    - 测量面-激励分离：段端面距板边 ≥ 20·NEAR（#347 族口径——MeasPlaneShift
      解嵌面不得落进 FeedShift=10·NEAR 激励盒近场）。
    """
    w_mm = float(p.get("w_mm", SCHIFFMAN_NOMINAL["w_mm"]))
    gap_mm = float(p.get("gap_mm", SCHIFFMAN_NOMINAL["gap_mm"]))
    lc_mm = float(p.get("l_coupled_mm", SCHIFFMAN_NOMINAL["l_coupled_mm"]))
    lr_mm = float(p.get("l_ref_mm", SCHIFFMAN_NOMINAL["l_ref_mm"]))
    wr_mm = float(p.get("w_ref_mm", SCHIFFMAN_NOMINAL["w_ref_mm"]))
    for label, v in (("w_mm", w_mm), ("gap_mm", gap_mm),
                     ("l_coupled_mm", lc_mm), ("l_ref_mm", lr_mm),
                     ("w_ref_mm", wr_mm)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"schiffman: {label} 必须为正有限，得到 {v!r}")
    base_m = float(p.get("_base_mm", 0.4)) * 1e-3
    near_m = base_m / 4.0
    h_m = float(p.get("_h_sub_mm", 0.508)) * 1e-3
    y0 = _SCHIFFMAN_Y0_MM * 1e-3
    y1 = y0 + lc_mm * 1e-3
    bridge_hi = y1 + w_mm * 1e-3
    xr = _SCHIFFMAN_X_REF_MM * 1e-3
    board_m = _BOARD_MM * 1e-3
    if bridge_hi >= board_m:
        raise ValueError(
            f"schiffman: 桥带上缘 y={bridge_hi * 1e3:.3f}mm 越板边 "
            f"(BOARD={board_m * 1e3:.1f}mm)——缩短 l_coupled_mm")
    if lr_mm * 1e-3 / 2.0 >= board_m - 4.0 * near_m:
        raise ValueError(
            f"schiffman: 参考段半长 {lr_mm / 2.0:.3f}mm 越板边余量 "
            f"(≤{(board_m - 4.0 * near_m) * 1e3:.3f}mm)——缩短 l_ref_mm")
    clear_m = (xr - wr_mm * 1e-3 / 2.0) - (gap_mm / 2.0 + w_mm) * 1e-3
    if clear_m < 3.0 * h_m:
        raise ValueError(
            f"schiffman: 路径净空 {clear_m * 1e3:.3f}mm < 3·h_sub="
            f"{3.0 * h_m * 1e3:.3f}mm（双路径 DC 隔离前提）——增大参考段偏移")
    plane_feed_m = y0 + board_m   # 板边到耦合段近端面距离（MeasPlaneShift）
    if plane_feed_m < 20.0 * near_m:
        raise ValueError(
            f"schiffman: 段端面距板边 {plane_feed_m * 1e3:.3f}mm < "
            f"20·NEAR={20.0 * near_m * 1e3:.3f}mm（#347 测量面-激励分离）")
    gx = gap_mm * 1e-3 / 2.0
    w_m = w_mm * 1e-3
    wr_m = wr_mm * 1e-3
    lr_m = lr_mm * 1e-3
    return {
        "w": w_m, "gap": gap_mm * 1e-3, "lc": lc_mm * 1e-3,
        "lr": lr_m, "wr": wr_m,
        "y0": y0, "y1": y1, "bridge_hi": bridge_hi, "xr": xr,
        "plane_feed": plane_feed_m,
        "plane_ref": board_m - lr_m / 2.0,
        "near_x": [-gx, gx, -(gx + w_m), gx + w_m,
                   xr - wr_m / 2.0, xr + wr_m / 2.0],
        "near_y": [y0, y1, bridge_hi, -lr_m / 2.0, lr_m / 2.0],
    }


def _schiffman_lines(p: dict[str, Any]) -> str:
    # Schiffman 移相器几何段（TA-1）：耦合段 C-section（双带条+远端桥带）+
    # 参考直通段。派生量以字面量注入（layout 单源 _schiffman_layout，含守卫）。
    # 四端口激励轮转（#208）：excite 由渲染器注入的 _excite_port 参数化。
    # MeasPlaneShift=段端面解嵌（两路径测量面分别贴耦合段近端/参考段两端，
    # 闭式对照含桥带整段——桥带属 C-section 拓扑本体）。
    lay = _schiffman_layout(p)
    return f'''GAP = {lay["gap"]!r}          # 耦合缝宽（m，layout 单源字面量）
W = {lay["w"]!r}            # 耦合带条宽（m）
LC = {lay["lc"]!r}           # 耦合段长（m）
LR = {lay["lr"]!r}           # 参考段长（m）
WR = {lay["wr"]!r}           # 参考段线宽（m，50Ω HJ）
Y0 = {lay["y0"]!r}           # 耦合段近端 y（端口侧锚定）
Y1 = {lay["y1"]!r}           # 耦合段远端 y（桥带侧）
XR = {lay["xr"]!r}           # 参考段线中心 x
schiffman = CSX.AddMetal("schiffman")
# C-section 耦合对：双带条沿 y + 远端桥带闭合（U 形全通段，Schiffman 1958）
schiffman.AddBox((-GAP / 2 - W, Y0, H_SUB), (-GAP / 2, Y1, H_SUB), priority=10)
schiffman.AddBox((GAP / 2, Y0, H_SUB), (GAP / 2 + W, Y1, H_SUB), priority=10)
schiffman.AddBox((-GAP / 2 - W, Y1, H_SUB), (GAP / 2 + W, Y1 + W, H_SUB),
                 priority=10)
# 参考直通段（50Ω，x=XR 沿 y；与耦合对净空 ≥3·h_sub）
schiffman.AddBox((XR - WR / 2, -LR / 2, H_SUB), (XR + WR / 2, LR / 2, H_SUB),
                 priority=10)
# 四端口激励轮转（#208）：主 run 仅端口 ep 激励，其余探针；测量面解嵌到
# 段端面（plane_feed/plane_ref 字面量出自 layout 单源）
_PORT_EP = {int(p.get("_excite_port", 1) or 1)}
_PORT_PLANE_FEED = {lay["plane_feed"]!r}
_PORT_PLANE_REF = {lay["plane_ref"]!r}
_port1 = MSLPort(CSX, port_nr=1, metal_prop=schiffman,
                 start=np.array([-GAP / 2, -BOARD, H_SUB]),
                 stop=np.array([-GAP / 2 - W, Y0, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == 1 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=_PORT_PLANE_FEED, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=schiffman,
                 start=np.array([GAP / 2, -BOARD, H_SUB]),
                 stop=np.array([GAP / 2 + W, Y0, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == 2 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=_PORT_PLANE_FEED, priority=10)
_port3 = MSLPort(CSX, port_nr=3, metal_prop=schiffman,
                 start=np.array([XR + WR / 2, -BOARD, H_SUB]),
                 stop=np.array([XR - WR / 2, -LR / 2, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == 3 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=_PORT_PLANE_REF, priority=10)
_port4 = MSLPort(CSX, port_nr=4, metal_prop=schiffman,
                 start=np.array([XR - WR / 2, BOARD, H_SUB]),
                 stop=np.array([XR + WR / 2, LR / 2, 0]),
                 prop_dir="y", exc_dir="z",
                 excite=1 if _PORT_EP == 4 else 0, FeedShift=10 * NEAR,
                 MeasPlaneShift=_PORT_PLANE_REF, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in schiffman.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ═══ TA-2 qwt_multisection ═══════════════════════════════════════════════

#: 缺省设计点常量（与 TEMPLATE_NOMINAL/design_params 缺省实参同源）
QWT_F0_GHZ = 2.5
QWT_Z0_OHM = 50.0
QWT_ZL_OHM = 100.0
QWT_N_SECTIONS = 3
QWT_RIPPLE_DB = -20.0
#: 馈线末端 y（板边侧锚定，mm）——级联扰动向 +y 生长
_QWT_Y0_MM = -25.0
#: 端接集总盒半长（mm，atten_pi shunt 盒口径）
_QWT_LOAD_HALF_MM = 0.25


QWT_MULTISECTION_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 1,
    "extraction": "S11 @ MSLPort 1（λ/4 节级联 + 末端 LumpedElement R=ZL 端"
                  "接到地，单端口回退 footer 同 patch）。裁判=skrf N 节理想 TL "
                  "级联 50Ω 端接闭式 |S11(f)|：@f0 深零（binomial/chebyshev 奇 "
                  "N 中心精确匹配，内核谱系恒等式）、带内纹波电平=Γm、FBW 对"
                  "照 kernel bandwidth_estimate；引擎-理想偏差=节间阶梯跳宽寄"
                  "生（stepped_impedance 同口径）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": 3,
    "params": ["widths_mm", "lengths_mm", "feed_w_mm", "z_load_ohm"],
    "topology": "多节 λ/4 阻抗变换器（TA-2）：50Ω 馈线（port1，−BOARD 板边入）"
                "+ N 节 λ/4 均匀微带线级联（节阻抗 Z1..ZN 闭式表驱动，沿 y）"
                "+ 末端 LumpedElement R=ZL 端接盒（z=0..H_SUB 对地，"
                "mmwave_series_array 链末负载同法）；z-min PEC 地 + 缺省 "
                "rogers4350b 叠层（guided 口径）",
    "param_semantics": "widths_mm=各节线宽列表（HJ inverse_width 按节阻抗精"
                       "算，schiffman/qwt 设计链单源）；lengths_mm=各节物理 "
                       "λ/4 长（按节 εeff 精算）；feed_w_mm=50Ω 馈线宽"
                       "（1.1134，mline 同源档）；z_load_ohm=端接集总电阻"
                       "（=ZL，LumpedElement R 值——进元件值不进导体几何，"
                       "combline c_load_pf 同口径豁免）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50"
                 "（官方口径）；馈线/各节带缘+节间 junction/端接盒缘精确入网"
                 "（#198）；全轴 1µm 近重合去重（#152）；端口面贴 PML_8 域边",
    "smoke_note": "未冒烟（离线审计过，#212，test_schiffman_qwt_templates）；"
                  "近似级别如实登记：①节间阶梯跳宽不连续性不进闭式裁判"
                  "（离线裁判=理想 TL 级联，偏差即寄生）；②LumpedElement 集"
                  "总端接的寄生电感/电容未建模（零厚度集总口径）；③一阶小反"
                  "射表驱动闭式（N>4 chebyshev 需 Riblet 数值迭代，内核显式拒"
                  "绝）；真机冒烟与 HFSS 仲裁属后续批次（本批零发射）",
}


def qwt_multisection_design_params(
    f0_ghz: float = QWT_F0_GHZ,
    z0_ohm: float = QWT_Z0_OHM,
    zl_ohm: float = QWT_ZL_OHM,
    n_sections: int = QWT_N_SECTIONS,
    profile: str = "binomial",
    ripple_db: float = QWT_RIPPLE_DB,
) -> dict[str, Any]:
    """多节 λ/4 变换器名义设计点（内核精算单源，#1c——名义值禁手算捷径）。

    设计链：synthesize_multisection_quarter_wave 闭式（一阶小反射表驱动
    结点阻抗 + 各节 HJ 线宽/εeff/物理 λ/4 长）→ 50Ω 馈线宽 inverse_width。
    恒等式由 test_schiffman_qwt_templates 综合反解自洽测试钉住。
    """
    from rfauto.core.synthesis import (
        Stackup,
        inverse_width,
        synthesize_multisection_quarter_wave,
    )

    sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
    d = synthesize_multisection_quarter_wave(
        float(z0_ohm), float(zl_ohm), int(n_sections), profile=str(profile),
        ripple_db=float(ripple_db), f0_ghz=float(f0_ghz))
    w_feed, _, status = inverse_width(float(z0_ohm), float(f0_ghz), sub)
    if status != "ok":
        raise ValueError(f"qwt_multisection 馈线宽反解未收敛: {status}")
    return {
        "widths_mm": [round(float(s["width_mm"]), 4) for s in d["sections"]],
        "lengths_mm": [round(float(s["length_mm"]), 4) for s in d["sections"]],
        "feed_w_mm": round(float(w_feed), 4),
        "z_load_ohm": round(float(zl_ohm), 4),
    }


#: 名义设计点（2026-10-02 由 qwt_multisection_design_params() 缺省实参精算，
#: 字面量落表；逐位一致性由自洽测试钉住）：Z0=50→ZL=100、N=3、binomial、
#: Γm=−20dB @2.5GHz——节阻抗 (54.5254, 70.7107, 91.7004)Ω → HJ 线宽
#: (0.966, 0.603, 0.344)mm、物理 λ/4 长 (17.851, 18.162, 18.462)mm；
#: 馈线 1.1134（50Ω HJ）
QWT_MULTISECTION_NOMINAL: dict[str, Any] = {
    "widths_mm": [0.966, 0.603, 0.344],
    "lengths_mm": [17.851, 18.162, 18.462],
    "feed_w_mm": 1.1134,
    "z_load_ohm": 100.0,
}


def _qwt_layout(p: dict[str, Any]) -> dict[str, Any]:
    """qwt_multisection 几何单源（mm 入参 → 米制派生量 + 近场线清单 + 守卫）。

    守卫（渲染期显式抛错）：
    - 参数正有限、widths/lengths 列表等长非空；
    - 级联顶端 + 端接盒在板内（lengths ×1.37 审计扰动域核算）；
    - 测量面-激励分离：馈线长 ≥ 20·NEAR（#347 族口径）。
    """
    widths = p.get("widths_mm", QWT_MULTISECTION_NOMINAL["widths_mm"])
    lengths = p.get("lengths_mm", QWT_MULTISECTION_NOMINAL["lengths_mm"])
    fw_mm = float(p.get("feed_w_mm", QWT_MULTISECTION_NOMINAL["feed_w_mm"]))
    zl = float(p.get("z_load_ohm", QWT_MULTISECTION_NOMINAL["z_load_ohm"]))
    w_list = [float(v) for v in widths]
    l_list = [float(v) for v in lengths]
    if not w_list or len(w_list) != len(l_list):
        raise ValueError(
            f"qwt_multisection: widths_mm/lengths_mm 须等长非空列表，得 "
            f"{len(w_list)}/{len(l_list)}")
    for label, seq in (("widths_mm", w_list), ("lengths_mm", l_list)):
        for k, v in enumerate(seq):
            if not (math.isfinite(v) and v > 0.0):
                raise ValueError(
                    f"qwt_multisection: {label}[{k}] 必须为正有限，得到 {v!r}")
    if not (math.isfinite(fw_mm) and fw_mm > 0.0 and math.isfinite(zl)
            and zl > 0.0):
        raise ValueError(
            f"qwt_multisection: feed_w_mm/z_load_ohm 必须为正有限，得 "
            f"({fw_mm!r}, {zl!r})")
    base_m = float(p.get("_base_mm", 0.4)) * 1e-3
    near_m = base_m / 4.0
    board_m = _BOARD_MM * 1e-3
    y0 = _QWT_Y0_MM * 1e-3
    junctions = [y0]
    y = y0
    for lv in l_list:
        y += lv * 1e-3
        junctions.append(y)
    y_end = junctions[-1]
    load_lo = y_end - _QWT_LOAD_HALF_MM * 1e-3
    if y_end >= board_m - 4.0 * near_m:
        raise ValueError(
            f"qwt_multisection: 级联顶端 y={y_end * 1e3:.3f}mm 越板边余量 "
            f"(≤{board_m * 1e3 - 4.0 * near_m * 1e3:.3f}mm)——缩短 lengths_mm")
    if y0 + board_m < 20.0 * near_m:
        raise ValueError(
            f"qwt_multisection: 馈线长 {y0 + board_m:.4f}m < 20·NEAR="
            f"{20.0 * near_m:.6f}m（#347 测量面-激励分离）")
    near_x = [-fw_mm * 1e-3 / 2.0, fw_mm * 1e-3 / 2.0]
    for wv in w_list:
        near_x += [-wv * 1e-3 / 2.0, wv * 1e-3 / 2.0]
    near_y = [*junctions, load_lo]
    return {
        "fw": fw_mm * 1e-3, "w_list_m": [wv * 1e-3 for wv in w_list],
        "l_list_m": [lv * 1e-3 for lv in l_list], "zl": zl,
        "y0": y0, "junctions": junctions, "y_end": y_end,
        "load_lo": load_lo, "load_half": _QWT_LOAD_HALF_MM * 1e-3,
        "near_x": near_x, "near_y": near_y,
    }


def _qwt_lines(p: dict[str, Any]) -> str:
    # 多节 λ/4 变换器几何段（TA-2）：馈线 + N 节级联 + 末端集总端接盒。
    # 派生量以字面量注入（layout 单源 _qwt_layout，含守卫）。
    lay = _qwt_layout(p)
    boxes_txt = ""
    y_prev = lay["y0"]
    for k, (wv, lv) in enumerate(zip(lay["w_list_m"], lay["l_list_m"],
                                     strict=True), start=1):
        y_next = y_prev + lv
        boxes_txt += (
            f"qwt.AddBox(({-wv / 2.0!r}, {y_prev!r}, H_SUB), "
            f"({wv / 2.0!r}, {y_next!r}, H_SUB), priority=10)   # 节 {k}\n")
        y_prev = y_next
    w_last = lay["w_list_m"][-1]
    return f'''FW = {lay["fw"]!r}           # 馈线宽（m，50Ω HJ，layout 单源字面量）
ZL = {lay["zl"]!r}           # 端接集总电阻（=ZL，LumpedElement R 值）
Y0 = {lay["y0"]!r}           # 馈线末端 y（级联起点）
Y_END = {lay["y_end"]!r}     # 级联顶端 y（末节端=端接面）
LOAD_LO = {lay["load_lo"]!r}   # 端接盒下缘 y
LOAD_HALF = {lay["load_half"]!r}   # 端接盒半长
qwt = CSX.AddMetal("qwt_multisection")
qwt.AddBox((-FW / 2, -BOARD, H_SUB), (FW / 2, Y0, H_SUB), priority=10)   # 50Ω 馈线
{boxes_txt}# 末端 LumpedElement R=ZL 端接到地（ny=2=z 向 shunt，atten_pi 口径；
# 盒 z=0..H_SUB，末节带条压盒顶缘导通）
_qwt_load = CSX.AddLumpedElement("qwt_load", ny=2, caps=True, R=ZL)
_qwt_load.AddBox(({-w_last / 2.0!r}, LOAD_LO, 0.0), ({w_last / 2.0!r}, Y_END, H_SUB),
                 priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=qwt,
                 start=np.array([FW / 2, -BOARD, H_SUB]),
                 stop=np.array([-FW / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in qwt.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 注册：同对象入表（单一事实源；尾部追加 #247 键集口径）─────────────────
TEMPLATE_META["schiffman"] = SCHIFFMAN_META
TEMPLATE_NOMINAL["schiffman"] = SCHIFFMAN_NOMINAL
_TEMPLATE_PORT_AXES["schiffman"] = ("y",)
_TEMPLATE_RADIATOR["schiffman"] = False

TEMPLATE_META["qwt_multisection"] = QWT_MULTISECTION_META
TEMPLATE_NOMINAL["qwt_multisection"] = QWT_MULTISECTION_NOMINAL
_TEMPLATE_PORT_AXES["qwt_multisection"] = ("y",)
_TEMPLATE_RADIATOR["qwt_multisection"] = False
