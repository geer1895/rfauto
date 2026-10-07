"""TA-7/8/9 三模板（ge8b 批 Wave A 席 1，2026-10-03）：倒置微带 inverted_ms +
半模基片集成波导 hmsiw + 有限地共面波导 fgcpw（render_fns 分发路径；
hmsiw 走 layout 单源字面注入，siw 同款机制）。

闭式/设计链内核（core 单源，本模块零几何数字副本 #116/#252）：
- inverted_ms → core/inverted_ms.py（FD 裁判反演设计链；文献闭式不可达
  如实登记，见该模块 docstring）；
- hmsiw → core/hmsiw.py（Lai-Fumeaux 2009 T-MTT 式 (8)-(14)，文献数值锚）；
- fgcpw → core/fgcpw.py（Ghione-Naldi 1984 交叉参考 + FD 裁判反演设计链，
  文献闭式系统偏差如实入账 #302 同族）。

注册清单（同对象注册钉死单一事实源；render_fns 分发 + registry 轴/辐射器
面 + grid 近场线 + render_core z 网格/基板/底界/β 块/DOM 注入 + 审计
EXPECTED_TEMPLATES/RECT_DOMAIN/TEMPLATE_MESH_MM + docs meta.yaml + 锚）。
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from rfauto.core.hmsiw import hmsiw_closed_form

from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

_MESH_FLOOR_M = 10e-6   # 显式近场线最小间距地板（#349，siw/lange 同值）


# ═══ TA-7 inverted_ms（倒置微带均匀段）══════════════════════════════════════
# 结构：地面=z=0 域 PEC 底界（金属/介质 z 序相对微带对调）；零厚条带悬于
# z=h_air（空气隙顶=基板下表面）；基板 z∈[h_air, h_air+h_sub] 上覆；其上
# 开放（top MUR）。端口=双 MSLPort 板边入（mline 口径，端口面贴板边 PML），
# 端口馈电模式=空气隙内的准微带模。设计链=FD 反演（core/inverted_ms）。

def _inverted_ms_lines(p: dict[str, Any]) -> str:
    # 均匀倒置微带段：一条直带悬于 z=h_air，两端 MSLPort（mline 手法，
    # 金属面 z=h_air；stop z=0=端口激励跨空气隙到地面）。
    # 参数：w_mm=条带宽（FD 反演 50Ω 名义 2.1359mm）、h_air_mm=空气隙
    # （地面→条带）、line_len_mm=两端口间线长。
    return f'''W = {p.get("w_mm", 2.1359)!r} * 1e-3
HA = {p.get("h_air_mm", 0.508)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Z_STRIP = HA                  # 条带 z=空气隙顶（基板下表面；z 网格字面同源）
Y0 = -L / 2
Y1 = L / 2
inv_ms = CSX.AddMetal("inverted_ms")
inv_ms.AddBox((-W / 2, Y0, Z_STRIP), (W / 2, Y1, Z_STRIP), priority=10)
_port1 = MSLPort(CSX, port_nr=1, metal_prop=inv_ms,
                 start=np.array([W / 2, -BOARD, Z_STRIP]),
                 stop=np.array([-W / 2, Y0, 0]),
                 prop_dir="y", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=inv_ms,
                 start=np.array([-W / 2, BOARD, Z_STRIP]),
                 stop=np.array([W / 2, Y1, 0]),
                 prop_dir="y", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in inv_ms.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


INV_MS_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（倒置微带均匀线：S21 相位斜率→εeff，"
                  "β 金标准 mline 同口径；|S11| 显著非零=端口/网格判废信号）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "h_air_mm", "line_len_mm"],
    "topology": "倒置微带均匀段（TA-7）：金属/介质 z 序相对微带对调——地面="
                "z=0 域 PEC 底界，零厚条带悬于 z=h_air 空气隙顶（基板下表面），"
                "基板 [h_air, h_air+h_sub] 上覆、其上开放（top MUR）；双 MSLPort "
                "板边入（端口面贴 PML）",
    "param_semantics": "w_mm=条带宽（设计链 core/inverted_ms.inverted_ms_design_"
                       "params：50Ω FD 裁判反演，名义 2.1359mm@h_air=h_sub=0.508"
                       "/εr=3.66）、h_air_mm=地面→条带空气隙（倒置微带定义参数，"
                       "效应=空气填充率高→εeff 低于同叠层微带）、line_len_mm=两"
                       "端口间线长；h_sub/er/tan_d 走 substrate/nominal",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "条带缘 x 向 + 线两端 y 向精确入网（#198）；z 网格=空气隙 2 层"
                 "+基板 _sub_cells 层+AIR_TOP（条带 z 面恰在网格线，#212 审计①）",
    "smoke_note": "离线审计先行（#212，test_ta_wave_a_templates）；近似级别如实"
                  "登记：准静态/零厚带/PEC 地/无色散，设计链=FD 裁判反演（文献"
                  "闭式不可达——core/inverted_ms docstring 如实账）；真机冒烟与 "
                  "HFSS 仲裁属后续批次（本批零发射）",
}

INV_MS_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c，无手抄毫米数）：inverted_ms_design_params(50Ω,
    # h_air=h_sub=0.508, er=3.66) FD 反演 → w=2.1359（回代 49.9994Ω，
    # εeff=1.2467——空气隙填充率高，εeff 显著低于同叠层微带 2.85 属倒置
    # 微带定义性质）；test_ta_wave_a_templates 单点 FD 带内钉（设计链整链
    # 复算 ~1s 在门内，richardson 缺省档）。
    "w_mm": 2.1359, "h_air_mm": 0.508, "line_len_mm": 40.0,
    "h_mm": 0.508, "h_sub_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
}


# ═══ TA-8 hmsiw（半模基片集成波导均匀段）════════════════════════════════════
# 结构：基板矩形域（DOM_X/DOM_Y 字面注入，siw 同款）；底板=显式零厚板贴
# z=0（与域底 PEC 等电势冗余，siw 同款）+顶开放（MUR，无上板——HMSIW 定义
# 性质）；单列过孔藩篱 x=+w/2（藩篱止于端口面=v2 端面口径）、开路边 x=−w/2
# （磁壁，域向 MUR 余量 weff/2）。端口=两端面 LumpedPort z 桥（跨介质孔径
# x∈[−w/2,+w/2]、跨全高、R=Z_PV=2h·Z_TE/w_eff 闭式，siw v2 端口即终端负载
# 口径）。设计链=hmsiw_design_params（fc 目标反解 w，式 (8)(9)(13)(10)(11)）。

_HMSIW_PORT_INSET_BASE = 16.0   # 端口面出 PML_8 净距（×BASE；#253/H4，siw 同值）


def hmsiw_layout(params: dict[str, Any], freq_range_ghz: tuple[float, float],
                 base_m: float, h_m: float) -> dict[str, Any]:
    """hmsiw 几何/端口/域单一事实源（mm 入参 → 米字面量+守卫；siw_layout
    同构）。闭式链=core/hmsiw（声明域复核/设计规则内嵌，违规 ValueError
    拒渲染）；网格守卫：过孔直径 ≥4·NEAR、孔间缝 >NEAR（siw 口径）、显式
    近场线 10µm 地板（#349）。"""
    from rfauto.core.calculators import siw_check_design_rules
    from rfauto.core.hmsiw import hmsiw_beta_rad_m, hmsiw_z_pv_ohm

    w = float(params.get("w_mm", 5.5829)) * 1e-3
    d = float(params.get("d_mm", 0.6)) * 1e-3
    s = float(params.get("s_mm", 1.0)) * 1e-3
    line_len = float(params.get("line_len_mm", 63.0721)) * 1e-3
    er = float(params.get("er", _DEFAULT_SUB["er"]))
    f0 = 0.5 * (float(freq_range_ghz[0]) + float(freq_range_ghz[1])) * 1e9
    if not (math.isfinite(line_len) and line_len > 0.0):
        raise ValueError(f"hmsiw_layout: line_len_mm 必须为正有限，得到 {line_len!r}")
    if not (math.isfinite(base_m) and base_m > 0.0):
        raise ValueError(f"hmsiw_layout: base 必须为正有限，得到 {base_m!r}")
    if not (math.isfinite(h_m) and h_m > 0.0):
        raise ValueError(f"hmsiw_layout: h 必须为正有限，得到 {h_m!r}")
    # 闭式全链（声明域 εr/h/w 复核内嵌，越界 ValueError）+ 设计规则（siw 单源）
    chain = hmsiw_closed_form(w * 1e3, h_m * 1e3, er, d * 1e3, s * 1e3)
    weff = chain["w_eff_hmsiw_mm"] * 1e-3
    siw_check_design_rules(w * 1e3, d * 1e3, s * 1e3, er, freq_ghz=f0 / 1e9)
    beta, fc = hmsiw_beta_rad_m(weff * 1e3, er, f0 / 1e9)
    if not (math.isfinite(beta) and beta > 0.0):
        raise ValueError(
            f"hmsiw_layout: 频带中心 {f0 / 1e9:.4g}GHz 低于准 TE0.5 截止 "
            f"fc={fc:.4f}GHz（线段必须工作在传播区；式 (11) 链）")
    near = base_m / 4.0
    if not d >= 4.0 * near:
        raise ValueError(
            f"hmsiw_layout: 网格欠分辨——过孔直径 d={d * 1e3:.4g}mm < "
            f"4·NEAR={4.0 * near * 1e3:.4g}mm（BASE={base_m * 1e3:.4g}mm；"
            "收紧 mesh_resolution_mm，siw 同口径）")
    via_gap = s - d
    if not via_gap > near * (1.0 + 1e-9):
        raise ValueError(
            f"hmsiw_layout: 孔间缝 s−d={via_gap * 1e3:.4g}mm ≤ NEAR="
            f"{near * 1e3:.4g}mm（缝内零内部网格线，#311 先例口径；siw 同款）")
    py = near                        # 端口盒 y 半长（=NEAR，siw 同款）
    port_inset = _HMSIW_PORT_INSET_BASE * base_m
    y1 = -line_len / 2.0
    y2 = line_len / 2.0
    # v2 端面口径：藩篱止于端口面（末孔缘不越端口面），端口背后直接是基板
    # 平行板区入 PML_8（端口即终端负载，siw v2_criteria §1 同款）；单列藩篱
    # x=+w/2，开路边 x=−w/2 磁壁
    k_half = math.floor((line_len / 2.0 - d / 2) / s + 1e-9)
    if k_half < 1:
        raise ValueError(
            f"hmsiw_layout: 藩篱止于端口面后无线段区过孔（line_len/2−d/2="
            f"{(line_len / 2.0 - d / 2) * 1e3:.4g}mm < s={s * 1e3:.4g}mm）"
            "——加大 line_len_mm（siw v2 同款）")
    if not k_half * s + d / 2 < line_len / 2.0:
        raise ValueError(
            f"hmsiw_layout: 末孔缘 {k_half * s + d / 2!r} 越过端口面 "
            f"{line_len / 2.0!r}（数值容差外）")
    via_y = tuple(k * s for k in range(-k_half, k_half + 1))
    dom_y = line_len / 2.0 + port_inset
    # 开路边（x=−w/2）MUR 余量 weff/2（siw 藩篱泄漏截断 e^−π≈4% 同口径，
    # 论文第一等效模型：开路边外场快速衰减）；藩篱侧 x=+w/2 孔缘外伸 d/2
    # < weff/2（d<weff 恒成立，闭合）
    dom_x = w / 2.0 + weff / 2.0
    # 显式近场线集最小间距地板（#349，siw 同款）：x=开路边/藩篱三线对
    # （w/2∓d/2、w/2）/端口盒边（±w/2 与开路边重合，set 去重）；y=每孔三线
    # +端口盒边
    x_lines = {0.0, w / 2 - d / 2, w / 2, w / 2 + d / 2, -w / 2}
    y_lines = {y1 - py, y1, y1 + py, y2 - py, y2, y2 + py}
    for _yk in via_y:
        y_lines.update((_yk - d / 2, _yk, _yk + d / 2))
    for _name, _lines in (("x", sorted(x_lines)), ("y", sorted(y_lines))):
        _gaps = [b - a for a, b in pairwise(_lines)]
        _gmin = min(_gaps) if _gaps else float("inf")
        if not _gmin > _MESH_FLOOR_M:
            raise ValueError(
                f"hmsiw_layout: {_name} 向显式网格线最小间距 {_gmin * 1e6:.3f}µm "
                f"≤ {_MESH_FLOOR_M * 1e6:.0f}µm 地板（#349 CFL 塌缩守卫；"
                "调整 d/s/line_len）")
    r_port, _ = hmsiw_z_pv_ohm(weff * 1e3, h_m * 1e3, er, f0 / 1e9)
    if not (math.isfinite(r_port) and r_port > 0.0):
        raise ValueError(
            f"hmsiw_layout: Z_PV 非正（f0={f0 / 1e9:.4g}GHz ≤ fc={fc:.4f}GHz？）")
    return {"w": w, "d": d, "s": s, "h": h_m, "er": er, "f0": f0,
            "weff": weff, "fc": fc, "beta": beta, "near": near,
            "rx": w / 2.0, "py": py, "port_inset": port_inset,
            "y1": y1, "y2": y2, "dom_x": dom_x, "dom_y": dom_y,
            "k_half": k_half, "via_y": via_y, "r_port": r_port,
            "delta_w_mm": chain["delta_w_mm"],
            "w_eff_prime_mm": chain["w_eff_prime_mm"]}


def _hmsiw_lines(p: dict[str, Any]) -> str:
    # hmsiw 直线段几何段（layout 单源字面注入，米）。必须经 render_script
    # 渲染（_hmsiw_layout 注入）——直调缺布局显式报错（siw 同款 #283 纪律）。
    lay = p.get("_hmsiw_layout")
    if lay is None:
        raise ValueError(
            "hmsiw 几何段缺 _hmsiw_layout：必须经 render_script 渲染（布局单源注入）")
    via_y = list(lay["via_y"])
    return f'''# ── hmsiw 直线段几何（layout 单源字面量，米；Lai-Fumeaux 2009 T-MTT 口径）──
W = {lay["w"]!r}              # HMSIW 宽（过孔列心 x=+W/2 → 开路边 x=−W/2）
D_VIA = {lay["d"]!r}          # 过孔直径
S_PITCH = {lay["s"]!r}        # 过孔心距（藩篱止于端口面=v2 端面口径）
R_PORT = {round(lay["r_port"], 4)!r}   # LumpedPort R = Z_PV=2h·Z_TE/w_eff（闭式；CalcPort 同参考）
PY = {lay["py"]!r}            # 端口盒 y 半长（=NEAR）
Y0 = {lay["y1"]!r}            # port1 测量面（端口盒中心，cps/siw 命名契约）
Y1 = {lay["y2"]!r}            # port2 测量面
# 底板：显式零厚盒贴 z 边界（与 z 底 PEC 等电势冗余——桥-板-藩篱连通图
# 物理化，#212 审计③可判；顶开放=HMSIW 定义性质，top MUR）
hmsiw_plates = CSX.AddMetal("hmsiw_plates")
hmsiw_plates.AddBox((-DOM_X, -DOM_Y, 0.0), (DOM_X, DOM_Y, 0.0), priority=10)
# 单列金属化过孔 PEC 圆柱（z∈[0,H_SUB] 贯通；x=+W/2 藩篱止于端口面，
# 端口背后无 HMSIW 延拓支路；开路边 x=−W/2=磁壁）
hmsiw_via = CSX.AddMetal("hmsiw_via")
_VIA_Y = {via_y!r}
for _vy in _VIA_Y:
    hmsiw_via.AddCylinder([W / 2, _vy, 0.0], [W / 2, _vy, H_SUB],
                          radius=D_VIA / 2, priority=10)
# 两端 LumpedPort 端面口径（跨介质孔径 x∈[-W/2,+W/2]、跨全高 0..H_SUB，
# R=Z_PV 闭式同源）：端口即终端负载而非中间抽头（siw v2_criteria §2 同款）；
# 盒三向边全部入网（#198/#283），端口面出 PML_8（16·BASE 净距，#253/H4）
_port1 = FDTD.AddLumpedPort(1, R_PORT, np.array([-W / 2, Y0 - PY, 0.0]),
                            np.array([W / 2, Y0 + PY, H_SUB]), "z", 1.0,
                            priority=5)
_port2 = FDTD.AddLumpedPort(2, R_PORT, np.array([-W / 2, Y1 - PY, 0.0]),
                            np.array([W / 2, Y1 + PY, H_SUB]), "z", 0.0,
                            priority=5)
# 生成期网格守卫：#152 去重后全轴最小间距复测（CFL 塌缩哨兵）+ 端口盒/
# 开路边/藩篱心线落格断言（#283：盒边=结构线，siw 同款）
for _ax in ("x", "y", "z"):
    _dl = np.diff(np.asarray(mesh.GetLines(_ax), dtype=float))
    if _dl.size and not bool(np.all(_dl > 1e-6)):
        raise SystemExit("hmsiw #" + "152" + ": "
                         + _ax + " 轴网格含 ≤1µm 近重合线（CFL 塌缩守卫）")
def _hmsiw_on_line(_ax, _v):
    _ls = np.asarray(mesh.GetLines(_ax), dtype=float)
    _j = int(np.searchsorted(_ls, _v))
    return (_j < _ls.size and abs(float(_ls[_j]) - _v) <= 1e-9) or (
        _j > 0 and abs(float(_ls[_j - 1]) - _v) <= 1e-9)
for _ax, _v in (("x", -W / 2), ("x", W / 2),
                ("y", Y0 - PY), ("y", Y0), ("y", Y0 + PY),
                ("y", Y1 - PY), ("y", Y1), ("y", Y1 + PY),
                ("z", 0.0), ("z", H_SUB)):
    if not _hmsiw_on_line(_ax, _v):
        raise SystemExit("hmsiw #" + "283" + ": 端口盒/开路边边 "
                         + _ax + "=" + repr(_v) + " 未落在网格线上")
for _prim in hmsiw_plates.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
for _prim in hmsiw_via.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


HMSIW_META: dict[str, Any] = {
    "f0_ghz": 10.0, "n_ports": 2,
    "extraction": "LumpedPort z 桥×2 端面口径（R=闭式 Z_PV=2h·Z_TE/w_eff，"
                  "CalcPort 同参考）：β/εeff 主判=S21 解缠相位斜率÷port_beta.csv "
                  "实测 plane_dist（cps/siw 同契约，LumpedPort 无 β 属性）；fc "
                  "由带内 φ(f)=−β(f；fc)·L+φ0 单参数拟合对照式 (11) 链（预声明门"
                  "归真机窗）",
    "max_time_ns": 45.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "d_mm", "s_mm", "line_len_mm"],
    "topology": "HM-SIW 半模基片集成波导均匀段（TA-8）：基板矩形域，底板=显式"
                "零厚板贴 z=0 PEC 底界+单列过孔藩篱 x=+w/2（藩篱止于端口面），"
                "开路边 x=−w/2=磁壁（域 MUR 余量 w_eff/2）、顶开放（MUR，无上板"
                "——HMSIW 定义性质）；端口=两端面 LumpedPort z 桥（跨介质孔径、"
                "R=Z_PV，端口即终端负载 siw v2 口径）——准 TE0.5 模 fc 由式 (11) "
                "链给出（Lai-Fumeaux 2009 T-MTT 式 (8)-(14)）",
    "param_semantics": "w_mm=HMSIW 宽（过孔列心到开路边；设计链 core/hmsiw."
                       "hmsiw_design_params：fc 目标=f0/1.5 反解，式 (8)(9)(13)"
                       "(10)(11) 联立 brentq，名义 5.5829mm@fc=6.6667GHz/er=3.66/"
                       "h=0.508/d=0.6/s=1.0）、d_mm=过孔直径、s_mm=过孔心距"
                       "（渲染按 k·s 精确栅格、藩篱止于端口面）、line_len_mm=两"
                       "端口测量面间距；h/er/tan_d 走 substrate/nominal（式 (13) "
                       "声明域 εr∈(2.2,15)/h∈(0.254,2.54)mm/w∈(2.5,10)mm，"
                       "hmsiw_check_validity 越界拒渲染）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖；0=自动 λ_sub/50@F_MAX；"
                 "过孔直径 ≥4·NEAR 守卫、孔间缝 ≥1 内部线（siw 同款）、显式近场"
                 "线 10µm 地板（#349）、端口盒边/开路边/藩篱心线落格（#283，生成"
                 "期断言）、基板 z 4 层",
    "smoke_note": "离线审计先行（#212，test_ta_wave_a_templates）；内核数字裁判="
                  "论文图面数值锚三方互证（Fig.6/7：fc 4.789/20.746GHz、β(12GHz)"
                  "342 rad/m，test_ta_wave_a_templates 钉）；近似级别如实登记："
                  "式 (13) 拟合 <2%（论文声明域内）、过孔藩篱离散化未经真机仲裁"
                  "（siw 经验迁移）、端面 LumpedPort R=Z_PV 对 1/4 余弦场分布的"
                  "功率-电压近似（siw v1/v2 同族近似级）；真机冒烟与 HFSS 仲裁属"
                  "后续批次（本批零发射）",
}

HMSIW_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c）：hmsiw_design_params(fc 目标=f0/1.5=6.6667GHz,
    # er=3.66, h=0.508, d=0.6, s=1.0) → w=5.5829（w_eff,HMSIW=5.8764、
    # Δw=0.48629、fc 回代 6.666664）；line_len=round(3λg@10GHz,4)=63.0721
    # （β=298.85711 rad/m 式 (12)、λg=21.02404mm——siw 同构造 3λg 口径）；
    # Z_PV=2h·Z_TE/w_eff=45.6781Ω（渲染层精算）；设计规则 s/d=1.667≤2 ✔、
    # d=0.6<λ_sub/5 ✔（siw 同源档 d/s）。
    # test_ta_wave_a_templates 按链复算逐键钉（闭式链毫秒级，#252 口径）。
    "w_mm": 5.5829, "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 63.0721,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
}


# ═══ TA-9 fgcpw（有限地共面波导均匀段，无底地=真 CPW 口径）═════════════════
# 结构：基板 0..H_SUB（底=域界 MUR——无底地，cps 口径；与 cpw 模板 CPWG
# 强制底地相区别）；中心条带+两有限宽接地（全长度，含端口段）；端口=双
# CPWPort 板边入（cpw 手法，gap_width 口径）。设计链=FD 反演
# （core/fgcpw，含有限地同参；G-N 文献闭式交叉参考偏差如实入账）。

def _fgcpw_lines(p: dict[str, Any]) -> str:
    # 均匀有限地 CPW 段：中心带+两有限宽地（全长度，端口段地已含——cpw
    # "端口段的地须自画"口径由全长度地盒满足）。端口=CPWPort（板边，
    # gap_width 口径，cpw 同款绑定源码口径）。
    # 参数：w_mm=中心带宽（FD 反演 50Ω 名义 4.3466mm@gap0.2/gnd4.0）、
    # gap_mm=缝宽、gnd_mm=单侧地宽（有限地 FGCPW 定义参数）、
    # line_len_mm=两端口间线长。
    return f'''W = {p.get("w_mm", 4.3466)!r} * 1e-3
GAP = {p.get("gap_mm", 0.2)!r} * 1e-3
GND = {p.get("gnd_mm", 4.0)!r} * 1e-3
L = {p.get("line_len_mm", 40.0)!r} * 1e-3
Y0 = -L / 2
Y1 = L / 2
fgcpw = CSX.AddMetal("fgcpw")
fgcpw.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB), priority=10)
# 两有限宽地：全长度（含端口段——CPWPort 端口段地已由本盒覆盖），外缘
# x=±(W/2+GAP+GND) 精确入网（#198）
fgcpw.AddBox((-(W / 2 + GAP + GND), Y0, H_SUB), (-(W / 2 + GAP), Y1, H_SUB),
             priority=10)
fgcpw.AddBox((W / 2 + GAP, Y0, H_SUB), (W / 2 + GAP + GND, Y1, H_SUB),
             priority=10)
_port1 = CPWPort(CSX, port_nr=1, metal_prop=fgcpw,
                 start=np.array([W / 2, -BOARD, H_SUB]),
                 stop=np.array([-W / 2, Y0, H_SUB]),
                 prop_dir="y", exc_dir="x", gap_width=GAP,
                 excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(Y0 + BOARD) / 3, priority=10)
_port2 = CPWPort(CSX, port_nr=2, metal_prop=fgcpw,
                 start=np.array([-W / 2, BOARD, H_SUB]),
                 stop=np.array([W / 2, Y1, H_SUB]),
                 prop_dir="y", exc_dir="x", gap_width=GAP,
                 excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - Y1) / 3, priority=10)
for _prim in fgcpw.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


FGCPW_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ CPWPort 1-2（有限地共面波导均匀线：S21 相位斜率"
                  "→εeff，β 金标准 #162 cpw 同口径；|S11| 显著非零=端口/网格判"
                  "废信号）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["w_mm", "gap_mm", "gnd_mm", "line_len_mm"],
    "topology": "有限地共面波导 FGCPW 均匀段（TA-9，真 CPW 口径）：基板上表面"
                "中心条带+两有限宽接地（全长度含端口段），**无底地**（基板下方"
                "空气、域底 MUR——cps 口径；与 cpw 模板 CPWG 强制底地相区别，"
                "registry CPW 段注释自证）；双 CPWPort 板边入（端口面贴 PML）",
    "param_semantics": "w_mm=中心带宽（设计链 core/fgcpw.fgcpw_design_params："
                       "50Ω FD 裁判反演含有限地同参，名义 4.3466mm@gap=0.2/"
                       "gnd=4.0/h=0.508/εr=3.66；真 CPW 无底地故 50Ω 条带显著宽"
                       "于 CPWG 的 0.849 属定义性质）、gap_mm=缝宽、gnd_mm=单侧"
                       "地宽（有限地定义参数；地效应 FD 实测名义 ≤2% 带，guard "
                       "gnd≥2·gap+0.5·w）、line_len_mm=两端口间线长",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "六条带/地缘（±w/2、±(w/2+gap)、±(w/2+gap+gnd)）+缝中线 x 向"
                 "精确入网（#198/cpw pt4 同源）+线两端 y 向；基板 z 8 层（CPW/"
                 "槽下场族 G3 分档）",
    "smoke_note": "离线审计先行（#212，test_ta_wave_a_templates）；内核数字裁判="
                  "FD 裁判两精确极限（k=1/√2 空气线 Z0=30π、h→∞ 半空间 "
                  "εeff=(1+εr)/2）+G-N/skrf 第三方对拍（设计点 ≤1% 带）；G-N 文"
                  "献闭式系统偏差如实入账（名义点 εeff −6.6%/Z0 −3.6%，#302 同"
                  "族，设计链以 FD 为准）；近似级别：准静态/零厚金属/无损；真机"
                  "冒烟与 HFSS 仲裁属后续批次（本批零发射）",
}

FGCPW_NOMINAL: dict[str, Any] = {
    # 全链内核精算（#1c）：fgcpw_design_params(50Ω, gap=0.2, gnd=4.0,
    # h=0.508, er=3.66) FD 反演 → w=4.3466（回代 50.000Ω，εeff=1.8303）。
    # G-N 文献闭式交叉参考在同点偏差 εeff −6.6%/Z0 −3.6%（系统低估，#302
    # 同族；设计链以 FD 为准，core/fgcpw docstring 如实账）。
    # test 单点 FD 带内钉（设计链整链复算 ~25s 超门预算，不整链复算——
    # 名义点守卫 |Z0_fd(w_nom)−50|≤0.5Ω 单点即可，#122 口径如实登记）。
    "w_mm": 4.3466, "gap_mm": 0.2, "gnd_mm": 4.0, "line_len_mm": 40.0,
    "h_mm": 0.508, "er": 3.66, "tan_d": 0.0037,
}


# ═══ 注册（同对象注册钉死单一事实源；追加在 schiffman/qwt/sicl/nway/
# diplexer/ridged_wg 之后——#247 尾部追加契约：槽线族保持字典尾）════════════
TEMPLATE_META["inverted_ms"] = INV_MS_META
TEMPLATE_NOMINAL["inverted_ms"] = INV_MS_NOMINAL
TEMPLATE_META["hmsiw"] = HMSIW_META
TEMPLATE_NOMINAL["hmsiw"] = HMSIW_NOMINAL
TEMPLATE_META["fgcpw"] = FGCPW_META
TEMPLATE_NOMINAL["fgcpw"] = FGCPW_NOMINAL


def inverted_ms_meta() -> dict[str, Any]:
    """返回 inverted_ms 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(INV_MS_META)
    meta["template"] = "inverted_ms"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(INV_MS_NOMINAL)
    return meta


def hmsiw_meta() -> dict[str, Any]:
    """返回 hmsiw 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(HMSIW_META)
    meta["template"] = "hmsiw"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(HMSIW_NOMINAL)
    return meta


def fgcpw_meta() -> dict[str, Any]:
    """返回 fgcpw 模板元数据（template_meta 同构便捷别名）。"""
    meta = dict(FGCPW_META)
    meta["template"] = "fgcpw"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(FGCPW_NOMINAL)
    return meta
