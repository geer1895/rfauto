"""SIW 族（siw + msl_siw_taper + compose pin 契约）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

# ══ SIW 族首族：直 SIW 传输线段（2026-09-22 siw-family 立项）══════════════════
# 权威口径：runs/siw_family/criteria.md（文献双源/闭式/激励方案利弊/预声明门全账）。
# 结构：基板 z∈[0,h]（上下显式零厚金属板贴 z 边界 PEC——与边界等电势冗余，使
# 桥-板-过孔连通图物理化）+ 两列金属化过孔 PEC 圆柱（x=±w/2，心距 s，贯通
# 全域直入 PML——slotline_lumped"匹配端接"口径，端口背后无开路 stub/短路面）。
# 端口：两端 LumpedPort z 桥（中线 x=0、跨全高；TE10 的 E_z 沿 z 在中线最大，
# 带内高阶模全倏逝——criteria.md §3），R=闭式 Z_PV=2b·Z_TE/w_eff。
# 域：x 半宽 = w/2 + w_eff/2（藩篱外倏逝尾 e^−π≈4% 处截断，侧界 MUR 吸收
# 泄漏）；y 半宽 = line_len/2 + 16·BASE（端口出 PML_8，slotline_lumped
# PORT_INSET_BASE=16 先例）——BOARD=60e-3 共享字面量对本模板不适用（自动档
# 约 20M cells 超预算），DOM_X/DOM_Y 由 layout 字面注入（机制层 per-template
# 分支，他模板渲染文本逐字节不变）。
# β 判读：LumpedPort 无 beta 属性（cps 同坑）→ port_beta.csv 落端口元 y 坐标
# + plane_dist_m（cps 契约复用）；WaveguidePort 解析 β=闭式自证不可作判据
# （criteria.md §3 弃用理由 2，#118 不自证）。
# 端口方案 v2（2026-09-23 df5-SE，runs/siw_family/v2_criteria.md）：opt-in
# 旋钮 params["_port_mode"]="v2"=藩篱止于端口面+端面口径 LumpedPort（跨介质
# 孔径 ±W/2、R=Z_PV 不变）——按原 G3 门重裁的 §R2 路线；缺省 v1 渲染逐字节
# 不变（字节钉 test_siw_v1_default_render_byte_pin）。

_SIW_PORT_INSET_BASE = 16.0   # 端口面→y 域边界净距（×BASE；PML_8≈8·BASE 的 2×）
_SIW_MESH_FLOOR_M = 10e-6     # 显式近场线最小间距地板（#349，渲染期 ValueError）


def _siw_r_port_ohm(w_mm: float, d_mm: float, s_mm: float, epsilon_r: float,
                    h_mm: float, f0_ghz: float) -> float:
    """LumpedPort R = 等效 RWG TE10 功率-电压阻抗 Z_PV=2·b·Z_TE/w_eff（Ω）。

    确定性闭式（#7）：V=中线全高电压=E0·b、P=E0²·a·b/(4·Z_TE) 消元 ⇒
    Z_PV=2b·Z_TE/w_eff，Z_TE=ωμ0/β（criteria.md §2；与 OE 锚判读同源）。
    """
    from rfauto.core.calculators import siw_beta_rad_m, siw_effective_width_mm

    weff_mm = siw_effective_width_mm(w_mm, d_mm, s_mm)
    beta, _fc = siw_beta_rad_m(weff_mm, epsilon_r, f0_ghz)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"siw: 频带中心 {f0_ghz}GHz 低于 TE10 截止（fc10={_fc:.4f}GHz）"
            "——SIW 线段必须工作在传播区")
    z_te = 2.0 * math.pi * f0_ghz * 1e9 * 1.25663706212e-6 / beta
    return 2.0 * float(h_mm) * 1e-3 * z_te / (weff_mm * 1e-3)


def siw_layout(params: dict[str, Any], freq_range_ghz: tuple[float, float],
               base_m: float, h_m: float) -> dict[str, Any]:
    """直 SIW 线段几何/端口/域单一事实源（mm 入参 → 米字面量 + 守卫）。

    所有名义派生量（w_eff/β/λg/R_port/过孔栅格/端口盒）在此一次计算，body/
    近场线/机制分支（DOM_X/DOM_Y、substrate、z 网格）同源消费——#198/#212
    单源纪律。设计规则违规/网格欠分辨显式 ValueError 拒渲染。
    """
    from rfauto.core.calculators import (
        siw_beta_rad_m,
        siw_check_design_rules,
        siw_effective_width_mm,
    )

    w = float(params.get("w_mm", 12.1317)) * 1e-3
    d = float(params.get("d_mm", 0.6)) * 1e-3
    s = float(params.get("s_mm", 1.0)) * 1e-3
    line_len = float(params.get("line_len_mm", 63.0724)) * 1e-3
    er = float(params.get("er", _DEFAULT_SUB["er"]))
    f0 = 0.5 * (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) * 1e9
    if not (math.isfinite(line_len) and line_len > 0.0):
        raise ValueError(f"siw_layout: line_len_mm 必须为正有限，得到 {line_len!r}")
    if not (math.isfinite(base_m) and base_m > 0.0):
        raise ValueError(f"siw_layout: base 必须为正有限，得到 {base_m!r}")
    if not (math.isfinite(h_m) and h_m > 0.0):
        raise ValueError(f"siw_layout: h 必须为正有限，得到 {h_m!r}")
    # 设计规则（双源出处 criteria.md §1）：违规拒渲染
    siw_check_design_rules(w * 1e3, d * 1e3, s * 1e3, er, freq_ghz=f0 / 1e9)
    weff = siw_effective_width_mm(w * 1e3, d * 1e3, s * 1e3) * 1e-3
    if not weff > 0.0:
        raise ValueError(f"siw_layout: 等效宽度非正 w_eff={weff!r}")
    beta, fc10 = siw_beta_rad_m(weff * 1e3, er, f0 / 1e9)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"siw_layout: 频带中心 {f0 / 1e9:.4g}GHz 低于 TE10 截止 "
            f"fc10={fc10:.4f}GHz（线段必须工作在传播区）")
    near = base_m / 4.0
    # 过孔可分辨守卫（criteria §4.2）：直径 ≥4·NEAR（2 格硬下限的 2× 余量）
    if not d >= 4.0 * near:
        raise ValueError(
            f"siw_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm）")
    # 孔间缝渲染守卫（#311 先例口径，round6 B-LOW#4）：相邻过孔缝隙 s−d
    # 须容得下 ≥1 内部网格线——SmoothMeshLines 只细分 >NEAR 的区间（#311），
    # 缝 ≤ NEAR ⇒ 缝内零内部线（缝缘线不算），藩篱等效面/泄漏建模粗。
    # 判据=严格 >（含 1e-9 浮点余量，与 #266/#283 同一口径）
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"siw_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm）——缝内零内部"
            "网格线（#311 先例口径：SmoothMesh 不细分 ≤NEAR 区间），藩篱"
            f"泄漏建模粗；收紧 mesh_resolution_mm ≤ "
            f"{4.0 * via_gap * 1e3:.4g}mm 或加大 s−d（设计规则域内）")
    # 端口方案旋钮（runs/siw_family/v2_criteria.md §1/§2，2026-09-23 df5-SE
    # 批；criteria.md §R2 归因裁定后用户选 v2 路线）：
    #   v1（缺省）=z 桥探针悬在贯通 PML 的连续 SIW 中间——端面三支路节点分光，
    #     fixture 汇 ≥0.385，理想探针天花板 −3.10dB（§R2 构造性证明）；
    #   v2=藩篱止于端口面+端面口径 LumpedPort（跨介质孔径 ±W/2）——端口即终端
    #     负载而非中间抽头，消除"端口背后 3.5mm 延拓"与探针耗散两条结构性
    #     吞噬路径；R=Z_PV 闭式不变（v2_criteria.md §2 选型论证）。
    #   其他值显式拒绝（不静默回退）。
    port_mode = str(params.get("_port_mode", "v1"))
    if port_mode not in ("v1", "v2"):
        raise ValueError(
            f"siw_layout: _port_mode 只接受 'v1'/'v2'，得到 {port_mode!r}")
    rx = near if port_mode == "v1" else w / 2.0
    # 端口盒 x 半宽（#283 盒边=结构线：v1=NEAR 窄桥 2 格；v2=跨介质孔径 ±W/2，
    # 复用过孔列心线零新增网格线）
    py = near                       # 端口盒 y 半长
    port_inset = _SIW_PORT_INSET_BASE * base_m
    # 激励盒内缩守卫（#253 单源 raise 型，R4-2；字面量 16·BASE 现状充裕，
    # 本门防未来旋钮/接入照抄缺省静默内缩不足；只校验不改几何——字节钉
    # test_siw_v1_default_render_byte_pin 依据）
    from .inset_guard import assert_excitation_inset
    assert_excitation_inset(
        port_inset, base_m, label="siw 端口/激励盒→y 域边内缩")
    y1 = -line_len / 2.0
    y2 = line_len / 2.0
    dom_x = w / 2.0 + weff / 2.0    # 侧界 MUR：藩篱外倏逝尾 e^−π≈4% 截断
    if port_mode == "v1":
        # 过孔藩篱贯通全域直入 PML（端口背后=匹配端接，无短路面/开路 stub）；
        # 心距取精确 s 的全域栅格：y_k = k·s，覆盖 |y| ≤ K·s ≥ line_len/2+
        # port_inset；dom_y 吸收藩篱端孔外缘（结构线不得越出域界——SmoothMesh
        # 会把网格撑到结构线处，域变量与实际网格必须一致，#212 审计④口径）
        dom_y_min = line_len / 2.0 + port_inset
        k_half = math.ceil(dom_y_min / s - 1e-9)
        dom_y = max(dom_y_min, k_half * s + d / 2)
    else:
        # v2（v2_criteria.md §1）：藩篱止于端口面——过孔只在 |k·s|+d/2 ≤
        # line_len/2 线段区（末孔缘不越端口面），端口面背后直接是基板平行板
        # 区入 PML_8（无 SIW 延拓支路）；dom_y=端口面+16·BASE 精确值
        # （无藩篱端孔要吸收，全部结构线 < dom_y，#212 审计④仍闭合）
        dom_y = line_len / 2.0 + port_inset
        k_half = math.floor((line_len / 2.0 - d / 2) / s + 1e-9)
        if k_half < 1:
            raise ValueError(
                f"siw_layout: v2 藩篱止于端口面后无线段区过孔（line_len/2−d/2="
                f"{(line_len / 2.0 - d / 2) * 1e3:.4g}mm < s={s * 1e3:.4g}mm）"
                "——加大 line_len_mm")
        if not k_half * s + d / 2 < line_len / 2.0:
            raise ValueError(
                f"siw_layout: v2 末孔缘 {k_half * s + d / 2!r} 越过端口面 "
                f"{line_len / 2.0!r}（数值容差外）")
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    # 显式近场线集最小间距地板（#349，渲染期确定性守卫）：x 集=过孔列三线对
    # （±(w/2∓d/2)、±w/2）+ 端口盒边，y 集=每孔三线（k·s∓d/2、k·s）+
    # 端口盒边——与 _near_points 注入集合同源（v2 端口盒边=±w/2 与列心线
    # 是同一条结构线：set 去重后守卫，重合不是近撞；v1 无重合逐字节原路径）
    x_lines = [0.0, w / 2 - d / 2, w / 2, w / 2 + d / 2,
               rx, -rx]
    y_lines = [y1 - py, y1, y1 + py, y2 - py, y2, y2 + py]
    for _yk in via_y:
        y_lines += [_yk - d / 2, _yk, _yk + d / 2]
    for _name, _lines in (("x", x_lines), ("y", y_lines)):
        _arr = sorted(_lines if port_mode == "v1" else set(_lines))
        _gaps = [b - a for a, b in pairwise(_arr)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _SIW_MESH_FLOOR_M:
            raise ValueError(
                f"siw_layout: {_name} 向显式网格线最小间距 {_gmin * 1e6:.3f}µm "
                f"≤ {_SIW_MESH_FLOOR_M * 1e6:.0f}µm 地板（#349 CFL 塌缩守卫；"
                "过孔栅格/端口盒与结构线近撞，调整 d/s/line_len）")
    r_port = _siw_r_port_ohm(w * 1e3, d * 1e3, s * 1e3, er, h_m * 1e3,
                             f0 / 1e9)
    return {"w": w, "d": d, "s": s, "h": h_m, "er": er, "f0": f0,
            "weff": weff, "beta": beta, "fc10": fc10, "near": near,
            "port_mode": port_mode,
            "rx": rx, "py": py, "port_inset": port_inset,
            "y1": y1, "y2": y2, "dom_x": dom_x, "dom_y": dom_y,
            "k_half": k_half, "via_y": via_y, "r_port": r_port}


def _siw_lines(p: dict[str, Any]) -> str:
    # 直 SIW 线段几何段（layout 单源字面注入，米）。必须经 render_script 渲染
    # （_siw_layout 注入）——直调缺布局显式报错，不做静默兜底（#283 渲染期守卫
    # 纪律：守卫条件与消费端同源）。
    lay = p.get("_siw_layout")
    if lay is None:
        raise ValueError(
            "siw 几何段缺 _siw_layout：必须经 render_script 渲染（布局单源注入）")
    via_y = list(lay["via_y"])
    v2 = lay.get("port_mode") == "v2"
    # 模式条件注释（仅注释行随端口方案变；几何/端口/守卫代码同一条 f-string，
    # v1 缺省路径渲染文本逐字节不变——字节钉 test_siw_v1_default_render_byte_pin）
    s_pitch_note = (
        "过孔心距（线段区精确栅格 y_k = k·S_PITCH，藩篱止于端口面 v2_criteria.md"
        " §1）" if v2 else "过孔心距（全域精确栅格 y_k = k·S_PITCH）")
    fence_note = (
        "# 两列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；藩篱止于端口面=v2 端面\n"
        "# 口径，端口背后无 SIW 延拓支路——v2_criteria.md §1/§3）"
        if v2 else
        "# 两列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；藩篱直入 PML=匹配端接，\n"
        "# slotline_lumped 口径——端口背后无短路面/开路 stub）")
    port_note = (
        "# 两端 LumpedPort 端面口径（跨介质孔径 x∈[-W/2,+W/2]、跨全高 0..H_SUB，\n"
        "# R=Z_PV 闭式同源）：端口即终端负载而非中间抽头（v2_criteria.md §2/§3）；\n"
        "# 盒三向边全部入网（#198/#283），端口面出 PML_8（16·BASE−NEAR 净距，\n"
        "# #253/H4）"
        if v2 else
        "# 两端 LumpedPort z 桥（中线 x=0、跨全高 0..H_SUB）：TE10 的 E_z 中线最大、\n"
        "# 带内高阶模倏逝（criteria §3）；盒三向边全部入网（#198/#283），端口面出\n"
        "# PML_8（16·BASE−NEAR 净距，#253/H4）")
    rx_note = (
        "端口盒 x 半宽（=W/2 跨介质孔径，盒边=列心线 v2_criteria.md §1）"
        if v2 else "端口盒 x 半宽（=NEAR，盒宽 2 格 #283）")
    return f'''# ── siw 直线段几何（layout 单源字面量，米；criteria.md §2/§4）──
W = {lay["w"]!r}              # 两过孔列心距（Cassivi 等效宽度 w_eff 的物理宽度）
D_VIA = {lay["d"]!r}          # 过孔直径
S_PITCH = {lay["s"]!r}        # {s_pitch_note}
R_PORT = {round(lay["r_port"], 4)!r}   # LumpedPort R = Z_PV=2b·Z_TE/w_eff（闭式；CalcPort 同参考）
RX = {lay["rx"]!r}            # {rx_note}
PY = {lay["py"]!r}            # 端口盒 y 半长（=NEAR）
Y0 = {lay["y1"]!r}            # port1 测量面（端口盒中心，cps 命名契约）
Y1 = {lay["y2"]!r}            # port2 测量面（端口盒中心）
# 上下金属板：显式零厚盒贴 z 边界（与 z 边界 PEC 等电势冗余——桥-板-过孔
# 连通图物理化，#212 审计③可判）
siw_plates = CSX.AddMetal("siw_plates")
siw_plates.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)
siw_plates.AddBox((-DOM_X, -DOM_Y, H_SUB), (DOM_X, DOM_Y, H_SUB), priority=10)
{fence_note}
siw_via = CSX.AddMetal("siw_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    siw_via.AddCylinder([-W / 2, _vy, 0.0], [-W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
    siw_via.AddCylinder([W / 2, _vy, 0.0], [W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
{port_note}
_port1 = FDTD.AddLumpedPort(1, R_PORT, np.array([-RX, Y0 - PY, 0.0]),
                            np.array([RX, Y0 + PY, H_SUB]), "z", 1.0,
                            priority=5)
_port2 = FDTD.AddLumpedPort(2, R_PORT, np.array([-RX, Y1 - PY, 0.0]),
                            np.array([RX, Y1 + PY, H_SUB]), "z", 0.0,
                            priority=5)
# 生成期网格守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）+ 端口盒/
# 中线边落格断言（#283：盒边=结构线，中线恰在网格线上探针才逐位落位）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("siw #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _siw_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", 0.0), ("x", -RX), ("x", RX),
                ("y", Y0 - PY), ("y", Y0), ("y", Y0 + PY),
                ("y", Y1 - PY), ("y", Y1), ("y", Y1 + PY),
                ("z", 0.0), ("z", H_SUB)):
    if not _siw_on_line(_ax, _v):
        raise SystemExit("siw #" + "283" + ": 端口盒/中线边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")
for _prim in siw_plates.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in siw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 元数据（TEMPLATE_META 公约；nominal 全闭式精算 #1c，出处 criteria.md §2）──
SIW_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "LumpedPort z 桥×2（R=闭式 Z_PV=2b·Z_TE/w_eff，CalcPort 同参考）："
                  "原始 S=带载比值（#250 口径，slotline_lumped 同）；β/εeff 主判="
                  "S21 解缠相位斜率÷port_beta.csv 实测 plane_dist（cps 同契约，"
                  "LumpedPort 无 β 属性）；fc10 由带内 φ(f)=−β(f；fc)·L+φ0 单参数"
                  "拟合（OE 锚 G1，预声明 runs/siw_family/criteria.md §6）",
    "max_time_ns": 45.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "d_mm", "s_mm", "line_len_mm"],
    "topology": "直 SIW 传输线段：基板 z∈[0,h] 上下显式零厚金属板（贴 z 边界 "
                "PEC）+ 两列金属化过孔 PEC 圆柱（x=±w/2、心距 s、全域精确栅格、"
                "藩篱直入 PML=匹配端接）；端口=两端 LumpedPort z 桥（中线、跨全"
                "高、盒边入网、16·BASE 出 PML_8）；域 x 半宽=w/2+w_eff/2（侧界 "
                "MUR 吸收泄漏）、y 半宽=line_len/2+16·BASE（PML_8）——矩形域，"
                "BOARD=60e-3 不适用（机制层 DOM_X/DOM_Y 字面注入）",
    "param_semantics": "w_mm=两过孔列心距（物理宽度，Cassivi 等效宽度 "
                       "w_eff=w−d²/(0.95s) 的输入）、d_mm=过孔直径、s_mm=过孔"
                       "心距（渲染按全域 k·s 精确栅格）、line_len_mm=两端口测量"
                       "面间距（名义 3λg@f0 闭式精算）；h/er/tan_d 走 substrate/"
                       "nominal（TE10 截止与 β 与 h 无关，Microwaves101 SIW 条目）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；"
                 "全域 NEAR=base/4（SmoothMesh 全轴均匀化实测）；过孔直径 ≥4·"
                 "NEAR 守卫、孔间缝 ≥1 内部线（#311 类比）、显式近场线 10µm "
                 "地板（#349）、端口盒 ≥2 格且中线落格（#283，生成期断言）、"
                 "基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）",
    "smoke_note": "离线审计先行（#212，test_siw_template）；真机锚已落判"
                  "（df4f：G1 勘误 PASS/G2 PASS/G3 口径裁定/G4 PASS，"
                  "runs/siw_family/，驱动 scripts/siw_anchor_smoke.py）；"
                  "预声明门与预算见 runs/siw_family/criteria.md §6",
}

SIW_NOMINAL: dict[str, Any] = {
    "w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 63.0724,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
    # 全闭式精算（#1c，criteria.md §2）：fc10 目标=f0/1.5=6.6667GHz（f0=10GHz
    # 预声明设计点）→ w_eff=c/(2·fc·√3.66)=11.7528 → w=w_eff+d²/(0.95·s)
    # =12.1317（Cassivi 2002 反解）；line_len=round(3λg@10GHz,4)=63.0724
    # （β=298.856 rad/m 闭式、λg=21.0241——链路与 synthesize_siw_model 逐位
    # 同源：4 位舍入 w 起算）；R_port=Z_PV=2b·Z_TE/w_eff=22.8393Ω（渲染层
    # 精算，非手数）；设计规则复核：s/d=1.667≤2 ✔、d=0.6<λ_sub/5=3.134 ✔
}

# （siw 注册在槽线族四件套之前：#247 尾部追加契约要求槽线族保持字典尾，
#   见文末 SIW 段元数据定义与注册行——2026-09-22 siw-family）

# ── 注册（2026-09-22 siw-family：SIW 族首族=直 SIW 传输线段；坑 #247 尾部
#    追加契约=槽线族四件套保持字典尾，故本键先于槽线族注册行执行；同对象
#    注册钉死单一事实源，同对象注册钉死单一事实源）──
TEMPLATE_META["siw"] = SIW_META
TEMPLATE_NOMINAL["siw"] = SIW_NOMINAL

# ══ SIW 族第二成员：MSL 锥形过渡 + SIW 直段（2026-09-24 df6 A2 立项）══════════
# 权威口径：runs/df6_a2siwmsl/criteria.md（Deslandes-Wu 两段论/文献互证账/
# G3' 预声明门/预算）。结构：基板填满矩形域（z=0 PEC 底界=MSL 地+SIW 底壁
# 共用+SIW 区显式零厚底板；顶界 MUR 开放——MSL 区是微带环境），顶层金属单
# 属性 msl_top 三段（50Ω 馈线 → 线性锥 AddPolygon 梯形 → SIW 顶壁显式板，
# 锥末 SEAM 搭接进板区防共棱浮岛）；两列过孔 PEC 圆柱藩篱止于板缘（siw v2
# 口径）。端口=双 MSLPort（线基，CalcPort ref=50 主口径；line_z0="engine"
# 反演+renormalize 判读旋钮沿 openems_rotation #250/#280 先例留判读侧），
# 端口面=域边界贴 PML_8（#174）、端口段=均匀 50Ω 线（refs §3.2）。
# 设计式（criteria §1）：锥=50Ω MSL → Z_PV=2b·Z_TE/w_eff 阻抗变换器（电压
# 基连续性：MSLPort u 探针电压=跨板全高，Z_PV 同基；u/i 口径 Z_TE=264Ω
# 反解线宽 <0.1mm 不可制造，任何已发表版图均无此形态）+ 锥末-SIW 台阶；
# w50/w_end=inverse_width（skrf HJ 单源，渲染期同参精算非手数 #1c）；
# 缺省锥长 λg/2（criteria §1.1 一阶互证：λg/4 在本阻抗比 50/22.84=2.19 下
# 带内 RL≈10.6dB 达不到 15dB 门，如实收档只作旋钮变体）。
# R*=2·Z_PV/π=14.5402Ω 旋钮（siw v2_criteria.md §2 条件触发项）在 MSL 线基
# 端口下语义废弃——匹配由锥形几何承担，Z_PV 只进锥末宽度设计式；v2 历史
# 档与其触发条件不删（#122 收档纪律）。

_MSL_SIW_SEAM_NEAR = 0.25     # 锥末搭接顶板深度（×NEAR；slotline METAL_SEAM 同式）
_MSL_SIW_FEED_BASE = 14.0     # MSLPort 端口段长（×BASE；MSL_PORT_CLEAR_BASE 同款）
_MSL_SIW_MESH_FLOOR_M = 10e-6  # 显式近场线最小间距地板（#349，与 siw 同值）


def msl_siw_taper_layout(params: dict[str, Any],
                         freq_range_ghz: tuple[float, float],
                         base_m: float, h_m: float) -> dict[str, Any]:
    """MSL 锥形过渡+SIW 直段几何/端口/域单一事实源（mm 入参 → 米字面量+守卫）。

    所有名义派生量（w_eff/β/λg/Z_PV/w50/w_end/锥装配/过孔栅格/端口段）在此
    一次计算，body/近场线/机制分支（DOM_X/DOM_Y、substrate、beta_block）同源
    消费——#198/#212 单源纪律。设计规则违规/网格欠分辨/反解未自洽显式
    ValueError 拒渲染。
    """
    from rfauto.core.calculators import (
        siw_beta_rad_m,
        siw_check_design_rules,
        siw_effective_width_mm,
    )
    from rfauto.core.synthesis import Stackup, inverse_width

    w = float(params.get("w_mm", 12.1317)) * 1e-3
    d = float(params.get("d_mm", 0.6)) * 1e-3
    s = float(params.get("s_mm", 1.0)) * 1e-3
    siw_len = float(params.get("siw_len_mm", 63.0724)) * 1e-3
    taper_len = float(params.get("taper_len_mm", 10.5121)) * 1e-3
    er = float(params.get("er", _DEFAULT_SUB["er"]))
    tan_d = float(params.get("tan_d", _DEFAULT_SUB.get("tan_d", 0.0037)))
    f0 = 0.5 * (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) * 1e9
    for _name, _v in (("siw_len_mm", siw_len), ("taper_len_mm", taper_len)):
        if not (math.isfinite(_v) and _v > 0.0):
            raise ValueError(
                f"msl_siw_taper_layout: {_name} 必须为正有限，得到 {_v!r}")
    if not (math.isfinite(base_m) and base_m > 0.0):
        raise ValueError(f"msl_siw_taper_layout: base 必须为正有限，得到 {base_m!r}")
    if not (math.isfinite(h_m) and h_m > 0.0):
        raise ValueError(f"msl_siw_taper_layout: h 必须为正有限，得到 {h_m!r}")
    # 设计规则（siw 单源复用，criteria §1）：违规拒渲染
    siw_check_design_rules(w * 1e3, d * 1e3, s * 1e3, er, freq_ghz=f0 / 1e9)
    weff = siw_effective_width_mm(w * 1e3, d * 1e3, s * 1e3) * 1e-3
    if not weff > 0.0:
        raise ValueError(f"msl_siw_taper_layout: 等效宽度非正 w_eff={weff!r}")
    beta, fc10 = siw_beta_rad_m(weff * 1e3, er, f0 / 1e9)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"msl_siw_taper_layout: 频带中心 {f0 / 1e9:.4g}GHz 低于 TE10 截止 "
            f"fc10={fc10:.4f}GHz（SIW 直段必须工作在传播区）")
    # 注意：不设"带低频>fc10"守卫——锚运行口径带 (6,13)GHz 有意含 6.2GHz
    # 截止下频点（G2 波导性滚降门，siw 同款），带缘倏逝是设计意图非误用
    near = base_m / 4.0
    # 过孔可分辨守卫（siw 同款）：直径 ≥4·NEAR
    if not d >= 4.0 * near:
        raise ValueError(
            f"msl_siw_taper_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm）")
    # 孔间缝渲染守卫（#311 先例口径，siw_layout 共用判据）：s−d 须 > NEAR
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"msl_siw_taper_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm）——缝内零内部"
            "网格线（#311 先例口径），藩篱泄漏建模粗；收紧 mesh_resolution_mm")
    # MSL 锥两端线宽（skrf HJ 单源精算，同参 substrate——#1c 禁抄毫米数；
    # inverse_width 返回 mm，此处收敛到米）
    stackup = Stackup(name="render_substrate", epsilon_r=er,
                      thickness_mm=h_m * 1e3, loss_tangent=tan_d)
    w50_mm, _z50, st50 = inverse_width(50.0, f0 / 1e9, stackup)
    if st50 != "ok":
        raise ValueError(
            f"msl_siw_taper_layout: 50Ω 线宽反解未自洽（status={st50!r}）")
    w50 = w50_mm * 1e-3
    z_te = 2.0 * math.pi * f0 * 1.25663706212e-6 / beta
    z_pv = 2.0 * h_m * z_te / weff
    if not z_pv < 50.0:
        raise ValueError(
            f"msl_siw_taper_layout: Z_PV={z_pv:.4f}Ω ≥ 50Ω 出设计域"
            "（锥反向/无匹配意义，criteria §1 选型域为 Z_PV<50）")
    w_end_mm, _zend, stend = inverse_width(z_pv, f0 / 1e9, stackup)
    if stend != "ok":
        raise ValueError(
            f"msl_siw_taper_layout: Z_PV={z_pv:.4f}Ω 线宽反解未自洽"
            f"（status={stend!r}）")
    w_end = w_end_mm * 1e-3
    if not (w50 >= 4.0 * near and w_end >= 4.0 * near):
        raise ValueError(
            f"msl_siw_taper_layout: 线宽欠分辨——w50={w50 * 1e3:.4g}mm/"
            f"w_end={w_end * 1e3:.4g}mm < 4·NEAR={4.0 * near * 1e3:.4g}mm"
            "（收紧 mesh_resolution_mm）")
    if not w_end / 2.0 < w / 2.0 - d / 2.0:
        raise ValueError(
            f"msl_siw_taper_layout: 锥末宽越过过孔藩篱（w_end/2="
            f"{w_end / 2.0 * 1e3:.4g}mm ≥ w/2−d/2={(w / 2.0 - d / 2.0) * 1e3:.4g}mm）")
    # 几何装配（criteria §3）：端口面=域边界；feed→taper→SIW（对称）
    feed_len = _MSL_SIW_FEED_BASE * base_m
    y_plate = siw_len / 2.0          # 顶板缘=锥末（波导区 |y|≤y_plate）
    y_feed_in = y_plate + taper_len  # 锥起点=馈线内端
    dom_y = y_feed_in + feed_len
    dom_x = w / 2.0 + weff / 2.0     # 侧界 MUR：藩篱外倏逝尾截断（siw 同式）
    seam = _MSL_SIW_SEAM_NEAR * near
    # #347：MeasPlaneShift(=feed_len/3) 与 FeedShift(=10·NEAR) 间距 ≥3.9·NEAR
    # （留浮点余量，恰等会炸——msl_slot_transition #347 口径；layout+body 双保险）
    if not feed_len / 3.0 - 10.0 * near >= 3.9 * near:
        raise ValueError(
            f"msl_siw_taper_layout: MeasPlaneShift/FeedShift 间距 "
            f"{(feed_len / 3.0 - 10.0 * near) * 1e6:.1f}µm < 3.9·NEAR（#347；"
            "加大 _MSL_SIW_FEED_BASE）")
    k_half = math.floor((y_plate - d / 2) / s + 1e-9)
    if k_half < 1:
        raise ValueError(
            f"msl_siw_taper_layout: 藩篱装不下（y_plate−d/2="
            f"{(y_plate - d / 2) * 1e3:.4g}mm < s={s * 1e3:.4g}mm）——加大 siw_len_mm")
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    # 显式近场线集（与 _near_points 注入同源）最小间距地板（#349，siw 同款）
    x_lines = [0.0, w50 / 2, -w50 / 2, w_end / 2, -w_end / 2,
               w / 2 - d / 2, w / 2, w / 2 + d / 2,
               -(w / 2 - d / 2), -w / 2, -(w / 2 + d / 2)]
    # 注意：锥-板搭接缘（y_plate−seam）不入显式线集——多边形顶点允许阶梯化
    # （非端口/非零厚板平面），入集会造出 25µm 级近线把 CFL dt 拉低 ~40%
    #（NrTS 预算触顶，#152/#283 家族预算面教训；y 最小线距保持与 siw 锚同构）
    y_lines = [dom_y, -dom_y, y_feed_in, -y_feed_in,
               y_plate, -y_plate]
    for _yk in via_y:
        y_lines += [_yk - d / 2, _yk, _yk + d / 2]
    for _name, _lines in (("x", x_lines), ("y", y_lines)):
        _arr = sorted(set(_lines))
        _gaps = [b - a for a, b in pairwise(_arr)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _MSL_SIW_MESH_FLOOR_M:
            raise ValueError(
                f"msl_siw_taper_layout: {_name} 向显式网格线最小间距 "
                f"{_gmin * 1e6:.3f}µm ≤ {_MSL_SIW_MESH_FLOOR_M * 1e6:.0f}µm "
                "地板（#349 CFL 塌缩守卫；锥缘/板缘/过孔栅格近撞，调整 "
                "siw_len/taper_len/d/s）")
    return {"w": w, "d": d, "s": s, "h": h_m, "er": er, "tan_d": tan_d,
            "f0": f0, "weff": weff, "beta": beta, "fc10": fc10,
            "near": near, "w50": w50, "w_end": w_end, "z_te": z_te,
            "z_pv": z_pv, "siw_len": siw_len, "taper_len": taper_len,
            "feed_len": feed_len, "y_plate": y_plate,
            "y_feed_in": y_feed_in, "seam": seam,
            "dom_x": dom_x, "dom_y": dom_y,
            "k_half": k_half, "via_y": via_y}


def _msl_siw_taper_lines(p: dict[str, Any]) -> str:
    # MSL 锥形过渡+SIW 直段几何段（layout 单源字面注入，米）。必须经
    # render_script 渲染（layout 注入）——直调缺布局显式报错（#283 纪律）。
    lay = p.get("_msl_siw_taper_layout")
    if lay is None:
        raise ValueError(
            "msl_siw_taper 几何段缺 _msl_siw_taper_layout：必须经 render_script "
            "渲染（布局单源注入）")
    via_y = list(lay["via_y"])
    return f'''# ── msl_siw_taper 几何（layout 单源字面量，米；runs/df6_a2siwmsl/criteria.md §1/§3）──
# Deslandes-Wu 两段论：50Ω MSL 馈线 → 线性锥（W50→W_END=Z_PV 阻抗变换器）
# → 锥末-SIW 台阶 → SIW 直段（顶壁板+两列过孔藩篱止于板缘=siw v2 口径）
W = {lay["w"]!r}              # 两过孔列心距（=siw 名义，Cassivi w_eff 输入）
D_VIA = {lay["d"]!r}          # 过孔直径
S_PITCH = {lay["s"]!r}        # 过孔心距（线段区精确栅格 y_k = k·S_PITCH）
W50 = {lay["w50"]!r}          # 50Ω MSL 馈线宽（inverse_width skrf HJ，f0 带心精算 #1c）
W_END = {lay["w_end"]!r}      # 锥末宽（=Z_PV 的微带当宽；电压基连续性 criteria §1）
Z_PV = {round(lay["z_pv"], 4)!r}       # SIW TE10 功率-电压阻抗（w_eff 闭式同源；设计 provenance）
Y_PLATE = {lay["y_plate"]!r}  # SIW 顶板缘=锥末（波导区 |y|≤Y_PLATE）
Y_FEED_IN = {lay["y_feed_in"]!r}  # 锥起点=馈线内端（taper_len=λg/2 缺省 criteria §1.1）
SEAM = {lay["seam"]!r}        # 锥末搭接顶板深度（×NEAR，防共棱浮岛 slotline 先例）
FEED_LEN = {lay["feed_len"]!r}    # MSLPort 端口段长（14·BASE）
# 顶层金属单属性 msl_top 三段（馈线/锥/顶壁板）：同属性+锥末 SEAM 搭接保证
# 馈线-锥-板连通图（#212 审计③；#310 共边不连通教训的预防性搭接）
msl_top = CSX.AddMetal("msl_top")
msl_top.AddBox((-W50 / 2, -DOM_Y, H_SUB), (W50 / 2, -Y_FEED_IN, H_SUB), priority=10)
msl_top.AddBox((-W50 / 2, Y_FEED_IN, H_SUB), (W50 / 2, DOM_Y, H_SUB), priority=10)
# 线性锥（梯形多边形；y 向 [±(Y_PLATE−SEAM), ±Y_FEED_IN]，宽 W50→W_END）
msl_top.AddPolygon(([-W50 / 2, W50 / 2, W_END / 2, -W_END / 2],
                    [-Y_FEED_IN, -Y_FEED_IN, -(Y_PLATE - SEAM), -(Y_PLATE - SEAM)]),
                   norm_dir="z", elevation=H_SUB, priority=10)
msl_top.AddPolygon(([-W50 / 2, W50 / 2, W_END / 2, -W_END / 2],
                    [Y_FEED_IN, Y_FEED_IN, Y_PLATE - SEAM, Y_PLATE - SEAM]),
                   norm_dir="z", elevation=H_SUB, priority=10)
# SIW 顶壁显式零厚板（域顶=MUR 开放——MSL 区微带环境，板只盖波导区）
msl_top.AddBox((-DOM_X, -Y_PLATE, H_SUB), (DOM_X, Y_PLATE, H_SUB), priority=10)
# SIW 底壁显式零厚板（与 z-min PEC 边界等电势冗余——过孔连通图物理化，siw 同款）
siw_bot = CSX.AddMetal("siw_bot")
siw_bot.AddBox((-DOM_X, -Y_PLATE, 0.0), (DOM_X, Y_PLATE, 0.0), priority=10)
# 两列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；藩篱止于板缘）
siw_via = CSX.AddMetal("siw_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    siw_via.AddCylinder([-W / 2, _vy, 0.0], [-W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
    siw_via.AddCylinder([W / 2, _vy, 0.0], [W / 2, _vy, H_SUB],
                        radius=D_VIA / 2, priority=10)
# 双 MSLPort（线基：CalcPort 自算 Z_ref/β；ref=50 归一主口径，line_z0="engine"
# 反演+renormalize 判读旋钮沿 openems_rotation #250/#280 先例留判读侧）：
# 端口面=域边界贴 PML_8（#174）、端口段=均匀 50Ω 线（refs §3.2）、
# FeedShift=10·NEAR 与 MeasPlaneShift=FEED_LEN/3 间距 #347 断言
if not FEED_LEN / 3.0 - 10 * NEAR >= 3.9 * NEAR:
    raise SystemExit("msl_siw_taper #" + "347" + ": "
                     "MeasPlaneShift/FeedShift 间距不足 3.9·NEAR")
_port1 = MSLPort(CSX, port_nr=1, metal_prop=msl_top,
                 start=np.array([W50 / 2, -DOM_Y, H_SUB]),
                 stop=np.array([-W50 / 2, -Y_FEED_IN, 0.0]),
                 prop_dir="y", exc_dir="z", excite=1.0,
                 FeedShift=10 * NEAR, MeasPlaneShift=FEED_LEN / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=msl_top,
                 start=np.array([-W50 / 2, DOM_Y, H_SUB]),
                 stop=np.array([W50 / 2, Y_FEED_IN, 0.0]),
                 prop_dir="y", exc_dir="z", excite=0.0,
                 FeedShift=10 * NEAR, MeasPlaneShift=FEED_LEN / 3, priority=10)
# 生成期网格守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）+ 锥缘/板缘/
# 端口边落格断言（#283：盒边=结构线）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("msl_siw_taper #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _mslsiw_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", 0.0), ("x", -W50 / 2), ("x", W50 / 2),
                ("x", -W_END / 2), ("x", W_END / 2),
                ("y", -DOM_Y), ("y", DOM_Y),
                ("y", -Y_FEED_IN), ("y", Y_FEED_IN),
                ("y", -Y_PLATE), ("y", Y_PLATE),
                ("z", 0.0), ("z", H_SUB)):
    if not _mslsiw_on_line(_ax, _v):
        raise SystemExit("msl_siw_taper #" + "283" + ": 端口/锥/板缘边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")
for _prim in msl_top.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in siw_bot.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in siw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── 元数据（TEMPLATE_META 公约；nominal 全闭式精算 #1c，出处 criteria.md §1）──
MSL_SIW_TAPER_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（线基：CalcPort ref=50 主口径；"
                  "port_beta.csv 落双端口 β+引擎自算 ZL（ReadUIData 重读，"
                  "wstep/mline W3② 法）+测量面间距 plane_dist_m——line_z0="
                  "'engine' 线基反演+renormalize 判读旋钮消费，#250/#280）；"
                  "fc10 主判=G1' 带内相位拟合 φ=−β_siw(f;fc)·L_siw+(a+b·f)"
                  "（线性项吸收馈线/锥群延迟，预声明 "
                  "runs/df6_a2siwmsl/criteria.md §4）",
    "max_time_ns": 45.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "d_mm", "s_mm", "taper_len_mm", "siw_len_mm"],
    "topology": "MSL 锥形过渡+SIW 直段（Deslandes-Wu 两段论）：50Ω MSL 馈线 "
                "→ 线性锥（w50→w_end=Z_PV 微带当宽的阻抗变换器+锥末-SIW 台阶"
                "不连续）→ SIW 直段（顶壁显式板+两列过孔藩篱止于板缘=siw v2 "
                "口径+底壁板）；基板填满矩形域，z=0 PEC 底界，顶界 MUR（MSL 区"
                "微带环境）；端口=双 MSLPort（面贴域界 PML_8、端口段=均匀 50Ω 线）",
    "param_semantics": "w_mm=两过孔列心距（=TEMPLATE_NOMINAL['siw'] 同名同义）、"
                       "d_mm=过孔直径、s_mm=过孔心距、taper_len_mm=锥形段长"
                       "（缺省 λg/2@f0，criteria §1.1 一阶互证收档）、"
                       "siw_len_mm=SIW 直段长（顶板缘间距，缺省 3λg）；w50/"
                       "w_end=inverse_width 渲染期同参精算（非参数，#1c）；"
                       "h/er/tan_d 走 substrate/nominal（er/h 进锥宽设计链）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；"
                 "全域 NEAR=base/4；过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线"
                 "（#311）、显式近场线 10µm 地板（#349）、锥缘/板缘/端口边落格"
                 "断言（#283）、FeedShift/MeasPlaneShift 间距 ≥3.9·NEAR"
                 "（#347）；基板 z 4 层（TE10 的 E_z 沿 z 均匀，z 分辨非限制项）",
    "smoke_note": "离线审计先行（#212，test_msl_siw_taper_template）；OE 锚"
                  "发射面备妥（驱动 scripts/siw_anchor_smoke.py --template "
                  "msl_siw_taper，发射前置=A1 队列清空+.oe_collect.lock 空，"
                  "见 战役任务书）；预声明门与预算见 "
                  "runs/df6_a2siwmsl/criteria.md §4/§6；R*=14.5402Ω 旋钮（siw "
                  "v2_criteria.md §2 条件触发项）在 MSL 线基端口下语义废弃——"
                  "匹配由锥形几何承担，Z_PV 只进锥末宽度设计式（如实收档，v2 "
                  "历史档不删）",
}

MSL_SIW_TAPER_NOMINAL: dict[str, Any] = {
    "w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0,
    "taper_len_mm": 10.5121, "siw_len_mm": 63.0724,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
    # 全闭式精算（#1c，runs/df6_a2siwmsl/criteria.md §1/§1.1）：w/d/s=
    # TEMPLATE_NOMINAL["siw"] 同源沿用（fc10=6.6667GHz=f0/1.5 设计点）；
    # λg=21.0241mm（β=298.856 rad/m 闭式）→ taper_len=round(λg/2,4)=10.5121
    # （缺省锥长；λg/4=5.256 只作旋钮变体——对称双锥确定性级联实测带内
    # |S11| max −7.8dB 达不到 15dB 预声明门，criteria §1.1 两轮勘误账如实
    # 收档）；siw_len=round(3λg,4)=63.0724（与 siw line_len 同链同值）；
    # w50=1.1198/w_end=3.361（inverse_width @Z_PV=22.8393Ω，渲染期同参
    # 精算非手数）
}

# ── 注册（2026-09-24 df6 A2：SIW 族第二成员=MSL 锥形过渡+SIW 直段；坑 #247
#    尾部追加契约=槽线族四件套保持字典尾，本键在槽线族注册行之前执行）──
TEMPLATE_META["msl_siw_taper"] = MSL_SIW_TAPER_META
TEMPLATE_NOMINAL["msl_siw_taper"] = MSL_SIW_TAPER_NOMINAL


# ══ DP-8：模板 pin 契约 + 几何组合契约（2026-09-24 df6；openems_templates.py
#    唯一增量面=port_pins 注册 + layout 契约，缺省渲染零变化——字节钉复验为门，
#    runs/df6_dp8compose/criteria.md §0/§3）════════════════════════════════════
# 契约形态（图元化，非文本拼接）：compose_layout(params, band, base, h, frame)
# → {pins, dom/bbox, primitives, plates_top, bottom_plate, bc_compat,
#    face_on_boundary, clearance_m, span_m, substrate, guards_text}；
# 文本发射由 core.compose.layout_netlist 单一发射器承担（图元→CSXCAD 语句，
# 属性名由引擎加 "__<instance_id>" 命名空间）。

#: siw pin schema（静态声明；position=名义局部坐标米、z_ref_ohm=None=Z_PV
#: 闭式同源注入（layout 期按本次参数精算，与 R_PORT 字面量同源）、
#: direction=外法向单位向量（±x/±y 四向枚举）、n_modes 预留）。
SIW_PORT_PINS: list[dict[str, Any]] = [
    {
        "pin_id": "p1",
        "position": [0.0, -0.0315362],
        "direction": [0, -1],
        "z_ref_ohm": None,
        "ref_plane_offset_m": 0.0,
        "port_type": "lumped",
        "n_modes": None,
        "cross_section": {"kind": "siw", "w_mm": 12.1317, "d_mm": 0.6,
                          "s_mm": 1.0, "h_mm": 0.508, "er": 3.66},
    },
    {
        "pin_id": "p2",
        "position": [0.0, 0.0315362],
        "direction": [0, 1],
        "z_ref_ohm": None,
        "ref_plane_offset_m": 0.0,
        "port_type": "lumped",
        "n_modes": None,
        "cross_section": {"kind": "siw", "w_mm": 12.1317, "d_mm": 0.6,
                          "s_mm": 1.0, "h_mm": 0.508, "er": 3.66},
    },
]

#: msl_siw_taper pin schema（msl 端=50Ω 馈线端面（贴域界）；siw 端=顶板缘
#: 截面（Z_PV 闭式注入）。position 名义=TEMPLATE_NOMINAL 缺省参数值）。
MSL_SIW_TAPER_PORT_PINS: list[dict[str, Any]] = [
    {
        "pin_id": "msl",
        "position": [0.0, -0.0476483],
        "direction": [0, -1],
        "z_ref_ohm": 50.0,
        "ref_plane_offset_m": 0.0,
        "port_type": "msl",
        "n_modes": None,
        "cross_section": {"kind": "msl", "w_mm": 1.1198, "h_mm": 0.508,
                          "er": 3.66},
    },
    {
        "pin_id": "siw",
        "position": [0.0, 0.0315362],
        "direction": [0, 1],
        "z_ref_ohm": None,
        "ref_plane_offset_m": 0.0,
        "port_type": "lumped",
        "n_modes": None,
        "cross_section": {"kind": "siw", "w_mm": 12.1317, "d_mm": 0.6,
                          "s_mm": 1.0, "h_mm": 0.508, "er": 3.66},
    },
]

# 注册（opt-in 渐进：改值不改键——TEMPLATE_META 字典键集/尾部序不受影响，
# #247 槽线族尾部追加契约保持；五消费者对既有模板增值均不敏感）
TEMPLATE_META["siw"]["port_pins"] = SIW_PORT_PINS
TEMPLATE_META["msl_siw_taper"]["port_pins"] = MSL_SIW_TAPER_PORT_PINS


def _compose_pin(pin_id: str, position: tuple[float, float],
                 direction: tuple[float, float], *, z_ref: float,
                 port_type: str, cross_section: dict[str, Any],
                 width_m: float, ref_plane: float = 0.0,
                 n_modes: int | None = None) -> dict[str, Any]:
    """layout 期 pin 解析值（schema 静态声明的运行时对应物，frame 已仿射）。"""
    return {"pin_id": pin_id,
            "position": [float(position[0]), float(position[1])],
            "direction": [float(direction[0]), float(direction[1])],
            "z_ref_ohm": float(z_ref), "ref_plane_offset_m": float(ref_plane),
            "port_type": port_type, "n_modes": n_modes,
            "cross_section": cross_section, "width_m": float(width_m)}


def _siw_compose_layout(params: dict[str, Any],
                        freq_range_ghz: tuple[float, float], base_m: float,
                        h_m: float,
                        frame: tuple[float, float, bool]) -> dict[str, Any]:
    """siw 组合契约（dp8）：结构限于段内（_port_mode 强制 v2——藩篱止于端口
    面；v1 藩篱贯通域与组合不相容，显式报错。standalone 缺省 v1 不受影响）。
    顶板=段区间显式零厚盒（组合域顶 MUR，SIW 顶壁由板承担）；底板声明=局部
    域覆盖（引擎统一整域单盒发射）。全部坐标按 frame 仿射到全局（米）。"""
    from rfauto.core.compose.layout_netlist import frame_apply_dir, frame_apply_point

    p = dict(params)
    mode = str(p.setdefault("_port_mode", "v2"))
    if mode != "v2":
        raise ValueError(
            f"siw 组合契约要求 _port_mode='v2'（藩篱止于端口面=结构限于段内；"
            f"得到 {mode!r}——v1 藩篱贯通全域与组合域合并不相容；standalone "
            "缺省 v1 不受本契约影响")
    lay = siw_layout(p, freq_range_ghz, base_m, h_m)
    h = float(lay["h"])
    er = float(lay["er"])
    w, d = float(lay["w"]), float(lay["d"])
    dom_x, dom_y = float(lay["dom_x"]), float(lay["dom_y"])
    y1, y2 = float(lay["y1"]), float(lay["y2"])
    via_y = tuple(frame_apply_point(frame, (0.0, float(vy)))[1]
                  for vy in lay["via_y"])
    y1g = frame_apply_point(frame, (0.0, y1))[1]
    y2g = frame_apply_point(frame, (0.0, y2))[1]
    y1g, y2g = min(y1g, y2g), max(y1g, y2g)
    x0 = frame_apply_point(frame, (-dom_x, 0.0))[0]
    x1 = frame_apply_point(frame, (dom_x, 0.0))[0]
    xlo, xhi = min(x0, x1), max(x0, x1)
    ydom0 = frame_apply_point(frame, (0.0, -dom_y))[1]
    ydom1 = frame_apply_point(frame, (0.0, dom_y))[1]
    ylo, yhi = min(ydom0, ydom1), max(ydom0, ydom1)
    r_port = round(float(lay["r_port"]), 4)
    xs_siw = {"kind": "siw", "w_mm": w * 1e3, "d_mm": d * 1e3,
              "s_mm": float(lay["s"]) * 1e3, "h_mm": h * 1e3, "er": er}
    pins = {
        "p1": _compose_pin("p1", frame_apply_point(frame, (0.0, y1)),
                           frame_apply_dir(frame, (0, -1)), z_ref=r_port,
                           port_type="lumped", cross_section=xs_siw,
                           width_m=w),
        "p2": _compose_pin("p2", frame_apply_point(frame, (0.0, y2)),
                           frame_apply_dir(frame, (0, 1)), z_ref=r_port,
                           port_type="lumped", cross_section=xs_siw,
                           width_m=w),
    }
    prims: list[dict[str, Any]] = [
        # SIW 顶壁显式零厚板（段区间；组合域顶=MUR，顶壁由本板承担）
        {"kind": "box", "prop": "siw_top",
         "start": [xlo, y1g, h], "stop": [xhi, y2g, h], "priority": 10},
    ]
    for vy in via_y:
        for vx in (-w / 2.0, w / 2.0):
            prims.append({"kind": "cylinder", "prop": "siw_via",
                          "start": [vx, vy, 0.0], "stop": [vx, vy, h],
                          "radius": d / 2.0, "priority": 10})
    for pin_id, y_face in (("p1", y1), ("p2", y2)):
        pos = frame_apply_point(frame, (0.0, y_face))
        x_a = frame_apply_point(frame, (-w / 2.0, 0.0))[0]
        x_b = frame_apply_point(frame, (w / 2.0, 0.0))[0]
        py = float(lay["py"])
        prims.append({"kind": "port", "pin": pin_id, "port_type": "lumped",
                      "prop": "siw_top",
                      "start": [min(x_a, x_b), pos[1] - py, 0.0],
                      "stop": [max(x_a, x_b), pos[1] + py, h],
                      "axis": "z", "ref_impedance": r_port, "priority": 5})
    return {"pins": pins,
            "dom": (min(xlo, xhi), ylo, max(xlo, xhi), yhi),
            "bbox": (xlo, y1g, xhi, y2g),
            "primitives": prims,
            "plates_top": [(xlo, y1g, xhi, y2g)],
            "bottom_plate": (min(xlo, xhi), ylo, max(xlo, xhi), yhi),
            "bc_compat": "siw_family",
            "face_on_boundary": {"p1": False, "p2": False},
            "clearance_m": {"p1": 16.0 * base_m, "p2": 16.0 * base_m},
            "span_m": {"p1": float(y2 - y1), "p2": float(y2 - y1)},
            "substrate": {"h_m": h, "er": er, "tan_d": 0.0037},
            "guards_text": []}


def _msl_siw_taper_compose_layout(params: dict[str, Any],
                                  freq_range_ghz: tuple[float, float],
                                  base_m: float, h_m: float,
                                  frame: tuple[float, float, bool]
                                  ) -> dict[str, Any]:
    """msl_siw_taper 组合契约（dp8）：msl pin 内连显式不支持（馈线延伸 P3+
    预留，引擎 D4 拒绝）；全部坐标按 frame 仿射到全局（米）。"""
    from rfauto.core.compose.layout_netlist import frame_apply_dir, frame_apply_point

    lay = msl_siw_taper_layout(params, freq_range_ghz, base_m, h_m)
    h = float(lay["h"])
    er = float(lay["er"])
    tan_d = float(lay["tan_d"])
    w, d = float(lay["w"]), float(lay["d"])
    w50, w_end = float(lay["w50"]), float(lay["w_end"])
    dom_x, dom_y = float(lay["dom_x"]), float(lay["dom_y"])
    y_plate, y_feed_in = float(lay["y_plate"]), float(lay["y_feed_in"])
    seam = float(lay["seam"])
    feed_len = float(lay["feed_len"])
    near = float(lay["near"])

    def xy(local: tuple[float, float]) -> tuple[float, float]:
        return frame_apply_point(frame, local)

    xlo = min(xy((-dom_x, 0.0))[0], xy((dom_x, 0.0))[0])
    xhi = max(xy((-dom_x, 0.0))[0], xy((dom_x, 0.0))[0])
    ylo = xy((0.0, -dom_y))[1]
    yhi = xy((0.0, dom_y))[1]
    y_plate_g = sorted((xy((0.0, -y_plate))[1], xy((0.0, y_plate))[1]))
    y_feed_g = sorted((xy((0.0, -y_feed_in))[1], xy((0.0, y_feed_in))[1]))
    # 两段 50Ω 馈线（域界→锥起点）与双锥（梯形多边形，宽 w50→w_end）
    feed_segs = [(ylo, y_feed_g[0]), (y_feed_g[1], yhi)]
    taper_polys = [(y_feed_g[0], y_plate_g[0] - seam),
                   (y_plate_g[1] + seam, y_feed_g[1])]
    prims: list[dict[str, Any]] = []
    for _ya, _yb in feed_segs:
        prims.append({"kind": "box", "prop": "msl_top",
                      "start": [xy((-w50 / 2.0, 0.0))[0], min(_ya, _yb), h],
                      "stop": [xy((w50 / 2.0, 0.0))[0], max(_ya, _yb), h],
                      "priority": 10})
    for _ya, _yb in taper_polys:
        _ys = sorted((xy((0.0, _ya))[1], xy((0.0, _yb))[1]))
        prims.append({"kind": "polygon", "prop": "msl_top",
                      "xs": [xy((-w50 / 2.0, 0.0))[0],
                             xy((w50 / 2.0, 0.0))[0],
                             xy((w_end / 2.0, 0.0))[0],
                             xy((-w_end / 2.0, 0.0))[0]],
                      "ys": [_ys[0], _ys[0], _ys[1], _ys[1]],
                      "elevation": h, "priority": 10})
    # SIW 顶壁显式板（波导区 |y|≤y_plate；组合域顶=MUR，顶壁由本板承担）
    prims.append({"kind": "box", "prop": "msl_top",
                  "start": [xlo, y_plate_g[0], h],
                  "stop": [xhi, y_plate_g[1], h], "priority": 10})
    via_y = tuple(frame_apply_point(frame, (0.0, float(vy)))[1]
                  for vy in lay["via_y"])
    for vy in via_y:
        for vx in (-w / 2.0, w / 2.0):
            prims.append({"kind": "cylinder", "prop": "siw_via",
                          "start": [vx, vy, 0.0], "stop": [vx, vy, h],
                          "radius": d / 2.0, "priority": 10})
    xs_msl = {"kind": "msl", "w_mm": w50 * 1e3, "h_mm": h * 1e3, "er": er}
    xs_siw = {"kind": "siw", "w_mm": w * 1e3, "d_mm": d * 1e3,
              "s_mm": float(lay["s"]) * 1e3, "h_mm": h * 1e3, "er": er}
    pins = {
        "msl": _compose_pin("msl", xy((0.0, -dom_y)),
                            frame_apply_dir(frame, (0, -1)), z_ref=50.0,
                            port_type="msl", cross_section=xs_msl,
                            width_m=w50),
        "siw": _compose_pin("siw", xy((0.0, y_plate)),
                            frame_apply_dir(frame, (0, 1)),
                            z_ref=round(float(lay["z_pv"]), 4),
                            port_type="lumped", cross_section=xs_siw,
                            width_m=w),
    }
    # msl pin 端口图元（面贴域界 #174）：端点=standalone 端口的精确刚体变换
    #（start=(W50/2,−DOM_Y,H_SUB)→stop=(−W50/2,−Y_FEED_IN,0) 逐点仿射，非
    # min/max 近似——rot180 下馈线在全局 +y 侧，FaceShift 方向语义=P3 真跑
    # 核对项，criteria.md §5）
    _face = xy((0.0, -dom_y))
    _inner = xy((0.0, -y_feed_in))
    prims.append({"kind": "port", "pin": "msl", "port_type": "msl",
                  "prop": "msl_top",
                  "start": [xy((w50 / 2.0, 0.0))[0], _face[1], h],
                  "stop": [xy((-w50 / 2.0, 0.0))[0], _inner[1], 0.0],
                  "axis": "y", "feed_shift": 10.0 * near,
                  "meas_plane_shift": feed_len / 3.0, "priority": 10})
    guards_text = [
        f'if not {feed_len / 3.0!r} - {10.0 * near!r} >= {3.9 * near!r}:',
        '    raise SystemExit("msl_siw_taper #" + "347" + ": "',
        '                     "MeasPlaneShift/FeedShift 间距不足 3.9·NEAR")',
    ]
    return {"pins": pins, "dom": (xlo, min(ylo, yhi), xhi, max(ylo, yhi)),
            "bbox": (xlo, min(ylo, yhi), xhi, max(ylo, yhi)),
            "primitives": prims,
            "plates_top": [(xlo, y_plate_g[0], xhi, y_plate_g[1])],
            "bottom_plate": (xlo, min(ylo, yhi), xhi, max(ylo, yhi)),
            "bc_compat": "siw_family",
            "face_on_boundary": {"msl": True, "siw": False},
            "clearance_m": {"msl": 0.0, "siw": 16.0 * base_m},
            "span_m": {"msl": 2.0 * dom_y, "siw": y_plate + dom_y},
            "substrate": {"h_m": h, "er": er, "tan_d": tan_d},
            "guards_text": guards_text}


#: 组合契约注册表（opt-in：service/compose_service 注入引擎；模板未在此注册
#: 即不可被组合引用——显式报错即正确行为）。
COMPOSE_CONTRACTS: dict[str, dict[str, Any]] = {
    "siw": {"layout": _siw_compose_layout},
    "msl_siw_taper": {"layout": _msl_siw_taper_compose_layout},
}
