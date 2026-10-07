"""hairpin 发夹滤波器族（同向 hairpin + 交替取向 hairpin_alt）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from rfauto.core.coupled_microstrip import (
    HAIRPIN_50OHM_W_MM as _HAIRPIN_50OHM_W_MM,
)
from rfauto.core.coupled_microstrip import (
    coupled_microstrip_even_odd_ohm as coupled_microstrip_even_odd_ohm,
)
from rfauto.core.coupled_microstrip import (
    hairpin_arm_len_mm as hairpin_arm_len_mm,
)
from rfauto.core.coupled_microstrip import (
    hairpin_gap_mm_from_k as hairpin_gap_mm_from_k,
)
from rfauto.core.coupled_microstrip import (
    hairpin_k_from_gap_mm as hairpin_k_from_gap_mm,
)
from rfauto.core.coupled_microstrip import (
    hairpin_qe_from_tap_frac as hairpin_qe_from_tap_frac,
)
from rfauto.core.coupled_microstrip import (
    hairpin_tap_frac_from_qe as hairpin_tap_frac_from_qe,
)
from rfauto.core.synthesis import (
    hairpin_design_from_order as hairpin_design_from_order,
)

from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

# ═══════════════════════════════════════════════════════════════════════════════
# WP2.3 Tier 1：hairpin（发夹线）带通滤波器——理论核验轮 + 离线几何审计
# （2026-09-12 增量；**附加模板**：不注册进 TEMPLATE_META，见段末"注册边界"）
# ═══════════════════════════════════════════════════════════════════════════════
# 拓扑：N 个半波谐振器折成 U 形（发夹）沿 x 并排，相邻谐振器外臂之间以耦合缝
# 做平行耦合；输入/输出 = 50Ω 抽头馈线（T 形，自 x=∓BOARD 板边接至首/末
# 谐振器外臂的抽头点）。两端均在 x 边界 → 单轴 PML；底 z-min PEC 地。
#
# ── 理论核验轮（口径/假设/来源逐条；裁判=独立来源，不自证）──
# 1) 谐振器展开长度：L_tot = λg/2 = c/(2·f0·√εeff)。来源：Pozar《Microwave
#    Engineering》半波开路线谐振器；与本仓 core/thermo_mech.py 的
#    hairpin_resonance_ghz 同式（单测互检）。εeff 一律走 skrf
#    Hammerstad-Jensen（core/synthesis.forward_z0；铁律 1c 唯一线宽口径）。
# 2) 耦合系数 ↔ 缝：同步平行耦合半波谐振器 k = (Z0e − Z0o)/(Z0e + Z0o)。
#    来源：Hong《Microstrip Filters for RF/Microwave Applications》§5.4；
#    Matthaei/Young/Jones《Microwave Filters, Impedance-Matching Networks and
#    Coupling Structures》§5。Z0e/Z0o 取耦合微带准静态闭式：Kirschning &
#    Jansen, IEEE Trans. MTT-32(1), 1984（偶/奇模填充因子 + Q 因子族），
#    零金属厚、无盖口径；对照实现 Qucs/transcalc c_microstrip.cpp
#    （C. Girardi / S. Jahn，GPL；KiCad pcb_calculator 同源）。
#    反解缝宽用 brentq（k(s) 单调递减，单测钉住）。**不采用 Akhtarzad(1975)
#    闭式综合**：本轮实测其在弱耦合（k≲0.05、s/h≳2）严重偏离 KJ 分析
#    （k=0.02：Akhtarzad 给 s=10.65mm，KJ 反解 2.15mm）——不强用，分歧以
#    数值记录在单测（诚实口径，不静默）。
# 3) 外部 Q ↔ 抽头位置：抽头在半波谐振器上距开路端 t 处接入，抽头处两段开路
#    线并联电纳 Y_res = j·Y_r·[tan(θ·τ)+tan(θ·(1−τ))]（τ=t/L_tot，θ=β·L_tot，
#    谐振 θ=π）。电纳斜率 b=(ω0/2)·dB/dω=(π/2)·Y_r·sec²(πτ)，负载 G=1/Z0
#    ⇒ Q_e = (π/2)·(Z0/Z_r)·sec²(πτ)。反解 τ=arccos(√((π/2)(Z0/Z_r)/Q_e))/π。
#    **独立校核**（#118 小步长数值）：对精确 Y_res(ω) 数值微分，与闭式逐位一致
#    （单测）。**假设**：无损（Q_e 即外部 Q）；理想 T 抽头（不连续性进器件）；
#    U 形同臂耦合与弯角造成的 f0 下移不在本级修正（待冒烟实测校准）。
# 4) C13 耦合矩阵映射（裁判口径）：core 的 synthesize_bpf_model /
#    coupling_matrix_synthesize_n2 给归一化 N+2 矩阵 M（0=源、1..N=谐振器、
#    N+1=载）。k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)。
#    来源：Hong §5.2/§5.3；Cameron 归一化口径外部耦合在 m_0i/m_iL。
#    独立裁判（单测）：与经典切比雪夫 g 值闭式（Pozar §8.4，
#    core/matching.chebyshev_g_values）互检：Q_e=g0·g1/FBW、
#    k_{i,i+1}=FBW/√(g_i·g_{i+1})。
#    本文件只做"k/Q_e → 几何"的确定性映射；矩阵综合在 core（数值只在内核）。
#
# ── 注册边界（#230 跨轨契约；2026-09-12 合流待办①起注册已补齐）──
# 本模板最初为**附加模板**（不进注册表，#230 增量文件面所限）；注册四件套
# （docs/templates/hairpin/meta.yaml、test_template_geometry_audit 的
# EXPECTED_TEMPLATES、fake_adapter 派发、models/template_specs）已于合流轮
# 补齐——注册动作见 HAIRPIN_NOMINAL 之后的 TEMPLATE_META/TEMPLATE_NOMINAL
# 赋值块（渲染段零改动，hairpin 渲染自 680e6e7 已入库）。

# ── 闭式内核已下沉 core（WP2.3 收口 ⑦，2026-09-16）：KJ 偶/奇模、k↔缝、Q_e↔τ、
# λg/2 臂长在 core/coupled_microstrip；C13→几何映射 hairpin_design_from_order 与
# spec 综合入口 synthesize_hairpin_model 在 core/synthesis。本段只做再导出，不留
# 本地函数体副本（#116）；topology_service/fake/scripts/tests 经本模块名零改动消费。




# ═══════════════════════════════════════════════════════════════════════════════
# WP2.3 Tier 1：hairpin（发夹线）带通滤波器——理论核验轮 + 离线几何审计
# （2026-09-12 增量；**附加模板**：不注册进 TEMPLATE_META，见段末"注册边界"）
# ═══════════════════════════════════════════════════════════════════════════════
# 拓扑：N 个半波谐振器折成 U 形（发夹）沿 x 并排，相邻谐振器外臂之间以耦合缝
# 做平行耦合；输入/输出 = 50Ω 抽头馈线（T 形，自 x=∓BOARD 板边接至首/末
# 谐振器外臂的抽头点）。两端均在 x 边界 → 单轴 PML；底 z-min PEC 地。
#
# ── 理论核验轮（口径/假设/来源逐条；裁判=独立来源，不自证）──
# 1) 谐振器展开长度：L_tot = λg/2 = c/(2·f0·√εeff)。来源：Pozar《Microwave
#    Engineering》半波开路线谐振器；与本仓 core/thermo_mech.py 的
#    hairpin_resonance_ghz 同式（单测互检）。εeff 一律走 skrf
#    Hammerstad-Jensen（core/synthesis.forward_z0；铁律 1c 唯一线宽口径）。
# 2) 耦合系数 ↔ 缝：同步平行耦合半波谐振器 k = (Z0e − Z0o)/(Z0e + Z0o)。
#    来源：Hong《Microstrip Filters for RF/Microwave Applications》§5.4；
#    Matthaei/Young/Jones《Microwave Filters, Impedance-Matching Networks and
#    Coupling Structures》§5。Z0e/Z0o 取耦合微带准静态闭式：Kirschning &
#    Jansen, IEEE Trans. MTT-32(1), 1984（偶/奇模填充因子 + Q 因子族），
#    零金属厚、无盖口径；对照实现 Qucs/transcalc c_microstrip.cpp
#    （C. Girardi / S. Jahn，GPL；KiCad pcb_calculator 同源）。
#    反解缝宽用 brentq（k(s) 单调递减，单测钉住）。**不采用 Akhtarzad(1975)
#    闭式综合**：本轮实测其在弱耦合（k≲0.05、s/h≳2）严重偏离 KJ 分析
#    （k=0.02：Akhtarzad 给 s=10.65mm，KJ 反解 2.15mm）——不强用，分歧以
#    数值记录在单测（诚实口径，不静默）。
# 3) 外部 Q ↔ 抽头位置：抽头在半波谐振器上距开路端 t 处接入，抽头处两段开路
#    线并联电纳 Y_res = j·Y_r·[tan(θ·τ)+tan(θ·(1−τ))]（τ=t/L_tot，θ=β·L_tot，
#    谐振 θ=π）。电纳斜率 b=(ω0/2)·dB/dω=(π/2)·Y_r·sec²(πτ)，负载 G=1/Z0
#    ⇒ Q_e = (π/2)·(Z0/Z_r)·sec²(πτ)。反解 τ=arccos(√((π/2)(Z0/Z_r)/Q_e))/π。
#    **独立校核**（#118 小步长数值）：对精确 Y_res(ω) 数值微分，与闭式逐位一致
#    （单测）。**假设**：无损（Q_e 即外部 Q）；理想 T 抽头（不连续性进器件）；
#    U 形同臂耦合与弯角造成的 f0 下移不在本级修正（待冒烟实测校准）。
# 4) C13 耦合矩阵映射（裁判口径）：core 的 synthesize_bpf_model /
#    coupling_matrix_synthesize_n2 给归一化 N+2 矩阵 M（0=源、1..N=谐振器、
#    N+1=载）。k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)。
#    来源：Hong §5.2/§5.3；Cameron 归一化口径外部耦合在 m_0i/m_iL。
#    独立裁判（单测）：与经典切比雪夫 g 值闭式（Pozar §8.4，
#    core/matching.chebyshev_g_values）互检：Q_e=g0·g1/FBW、
#    k_{i,i+1}=FBW/√(g_i·g_{i+1})。
#    本文件只做"k/Q_e → 几何"的确定性映射；矩阵综合在 core（数值只在内核）。
#
# ── 注册边界（#230 跨轨契约；2026-09-12 合流待办①起注册已补齐）──
# 本模板最初为**附加模板**（不进注册表，#230 增量文件面所限）；注册四件套
# （docs/templates/hairpin/meta.yaml、test_template_geometry_audit 的
# EXPECTED_TEMPLATES、fake_adapter 派发、models/template_specs）已于合流轮
# 补齐——注册动作见 HAIRPIN_NOMINAL 之后的 TEMPLATE_META/TEMPLATE_NOMINAL
# 赋值块（渲染段零改动，hairpin 渲染自 680e6e7 已入库）。

# ── 闭式内核已下沉 core（WP2.3 收口 ⑦，2026-09-16）：KJ 偶/奇模、k↔缝、Q_e↔τ、
# λg/2 臂长在 core/coupled_microstrip；C13→几何映射 hairpin_design_from_order 与
# spec 综合入口 synthesize_hairpin_model 在 core/synthesis。本段只做再导出，不留
# 本地函数体副本（#116）；topology_service/fake/scripts/tests 经本模块名零改动消费。

HAIRPIN_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（发夹线 BPF：带内回波纹波 + 带外"
                  "抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm",
               "tap_frac"],
    "topology": "发夹线带通（WP2.3 Tier1 滤波器族）：N 个 λg/2 半波谐振器折成"
                " U 形沿 x 并排，相邻外臂平行耦合（缝 gap_mm）；输入/输出为"
                " 50Ω 抽头馈线（T 形，板边 x=∓BOARD 至首/末谐振器外臂，抽头"
                " 位置 tap_frac 自开路端计）",
    "param_semantics": "order=谐振器阶数 N，w_mm=谐振器/馈线宽（50Ω，skrf HJ "
                       "综合），arm_len_mm=展开中心线总长 λg/2（2·臂长+臂间距），"
                       "arm_gap_mm=U 内两臂缝（边缘到边缘；须 ≳3×线宽量级，名义 3.0mm："
                       "同臂自耦 k_self(3.0)=0.0115 ≪ 互耦 0.0515，旧 1.0 的 k_self="
                       "0.0602 反超互耦致四轮真机 FAIL，2026-09-16 定版），gap_mm=相邻谐振器"
                       "耦合缝（锚=等缝口径；非等 k 逐缝变体走 gaps_mm 列表，"
                       "不进本 meta；**同向拓扑 gap→k 须经结构修正 c(gap)**："
                       "k_EM=c(gap)·k_KJ，c=0.12-0.26 且非单调、k_EM 上限 ~0.0155"
                       "≪ KJ 名义 0.0515——相邻臂开路端对齐致电/磁耦合反号相消，"
                       "core.coupled_microstrip.HAIRPIN_KGAP_TABLE_MM 真机表，"
                       "2026-09-17 W4④；根修见 hairpin_alt 交替取向变体），"
                       "tap_frac=抽头位置比例 τ=t/L_tot",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部臂缘/弯带缘/抽头缘精确入网（#198 精确入网）",
}

HAIRPIN_NOMINAL: dict[str, Any] = {
    "order": 3,
    # ── 2026-09-16 名义定版（WP2.3 收口 A2）：四项几何统一由闭式链
    # hairpin_design_from_order(3, 2.5, 0.05, 20.0) 生成并按 scripts/hairpin_calib
    # 的 design_params 同规则舍入（w/arm_len/gap 4 位、τ 6 位）——名义 = 设计链 =
    # 标定脚本 design_params 逐位同源，消 w 1.1134/1.1117（旧硬编码 50Ω 宽 vs
    # inverse_width 精算 49.95Ω/50.00Ω）与 arm_len 35.4653/35.4676 双份微漂；单测钉住。
    "w_mm": 1.1117,            # lossless_width_mm(50Ω @2.5GHz，εr3.66 h0.508 无耗档；XC-W 单源
                               # core/synthesis.lossless_width_mm——与 yaml 层叠档 1.1134 并存
                               # 系 tanδ 参数系不同非同参漂移，test_width_single_source 钉)
    # 闭式 λg/2=35.4676（εeff=2.8578 @w，HJ）× 真机谐振修正 c_f0=1.0370（B2 pt4：
    # N=3 通带中心 2.5925 vs 2.5，U 弯+开路端等效缩短；f∝1/L → L·f0_act/f0）；
    # fake 端同源常数 fake_adapter._HAIRPIN_F0_CORR
    "arm_len_mm": 36.7799,
    # U 内两臂缝 3.0（≳2.7×线宽）：k_self(3.0)=0.0115 < 互耦 k=0.0515 < k_self(1.0)
    # =0.0602——旧名义 1.0 同臂自耦反超互耦是四轮 FAIL 的结构性根因（pt1 实证）
    "arm_gap_mm": 3.0,
    # C13 N=3/RL=20dB/FBW=0.05 → k=0.051514 → KJ 反解 s=1.132829mm
    "gap_mm": 1.1328,
    # Q_e=17.0689（=g0·g1/FBW 同源）；B1 真机标定 c(τ)=1.37437−0.75218·τ（τ=0.40/0.43
    # 两点，runs/hairpin_q_extract/summary.json）→ τ*=0.398159 重解（0.401892 闭式；
    # B3 终验轮 pt5 用单点解 0.398227，Δτ=6.8e-5≈2.5µm≪0.4mm 网格），消费端
    # hairpin_qe_from_tap_frac(τ)×c(τ) 见 fake_adapter._HAIRPIN_QE_CORR
    "tap_frac": 0.398159,
}

# ── 注册（2026-09-12 合流待办①）：hairpin 升格为正式注册模板 ──
# 四处同步：① docs/templates/hairpin/meta.yaml；②
# test_template_geometry_audit.EXPECTED_TEMPLATES（17→18）；③
# fake_adapter 派发分支（_hairpin_sparams）；④ models/template_specs
# （_register_hairpin）。同对象注册（非拷贝）钉死单一事实源，防双份
# 字典漂移；渲染段零改动。
TEMPLATE_META["hairpin"] = HAIRPIN_META
TEMPLATE_NOMINAL["hairpin"] = HAIRPIN_NOMINAL


def hairpin_meta() -> dict[str, Any]:
    """返回 hairpin 模板元数据（与 template_meta("hairpin") 同构的便捷别名）。"""
    meta = dict(HAIRPIN_META)
    meta["template"] = "hairpin"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(HAIRPIN_NOMINAL)
    return meta


_HAIRPIN_ORIENTATIONS: tuple[str, ...] = ("same", "alternating")


def _hairpin_layout(p: dict[str, Any], *,
                    orientation: str = "same") -> dict[str, Any]:
    """hairpin 几何统一计算（单位：米）——render/_near_points/geometry_spec 共用。

    防三处各自推导几何造成漂移（#212 审计口径）。参数与 HAIRPIN_META 一致；
    可选 gaps_mm（长度 order−1 的列表，mm）给出逐缝非等耦合变体。
    order≥1：N=1 为单谐振器双抽头探针（XS=[左臂, 右臂] 两抽头各距开路端
    τ·L_tot，天然对称双端口；B1 Q_u/Q_e 标定用），无耦合缝。

    orientation（2026-09-18 w2g，0dk 根修）："same"=全部 U 同向（开路端齐在 y0、
    弯带齐在 y1，hairpin 模板口径，既有键逐位不变）；"alternating"=奇数序谐振器
    上下翻转（弯带在 y0 侧、开路端在 y1），相邻臂开路端交替 → 电/磁耦合同号叠加
    （hairpin_alt 模板口径）。两取向臂盒 y 跨度同为 [y0, y1]，仅弯带/开路端互换，
    耦合长度与网格配方不变（A/B 只隔离拓扑变量）。增量键：orientation/flips/
    y_open/y_bend（逐腔）/y_taps=[输入, 输出]/y_tap_out（末腔翻转时输出抽头自
    其开路端 y1 向下计 τ·L_tot；同向时恒 = y_tap）。
    """
    if orientation not in _HAIRPIN_ORIENTATIONS:
        raise ValueError(
            f"hairpin orientation 须为 {_HAIRPIN_ORIENTATIONS}（得 {orientation!r}）")
    n = int(p.get("order", 3))
    if n < 1:
        raise ValueError("hairpin 阶数须 ≥1（order=1 为单谐振器双抽头探针）")
    wf = float(p.get("w_mm", _HAIRPIN_50OHM_W_MM)) * 1e-3
    total = float(p.get("arm_len_mm", 35.46)) * 1e-3
    arm_gap = float(p.get("arm_gap_mm", 3.0)) * 1e-3   # 2026-09-16 名义定版 3.0
    tap_frac = float(p.get("tap_frac", 0.402))
    if not 0.0 < tap_frac < 0.5:
        raise ValueError("tap_frac 须在 (0,0.5)")
    if wf <= 0.0 or total <= 0.0 or arm_gap <= 0.0:
        raise ValueError("hairpin 几何参数须 >0")
    b = wf + arm_gap                        # U 内两臂中心距
    l_arm = (total - b) / 2.0               # 展开 = 2·l_arm + b = L_tot
    if l_arm <= 0.0:
        raise ValueError("arm_len_mm 必须大于 U 臂间距（折叠不成立）")
    gaps_raw = p.get("gaps_mm")
    if gaps_raw is None:
        gaps = [float(p.get("gap_mm", 1.133)) * 1e-3] * (n - 1)
    else:
        gaps = [float(v) * 1e-3 for v in gaps_raw]
        if len(gaps) != n - 1:
            raise ValueError(f"gaps_mm 长度须为 order-1={n - 1}")
    if any(gap <= 0.0 for gap in gaps):
        raise ValueError("耦合缝须 >0")

    centres: list[float] = []
    xs: list[float] = []
    xc = 0.0
    for i in range(n):
        centres.append(xc)
        xs += [xc - b / 2.0, xc + b / 2.0]
        if i < n - 1:
            xc += b + wf + gaps[i]
    shift = -0.5 * (centres[0] + centres[-1])   # 阵列 x 居中
    xs = [v + shift for v in xs]
    centres = [v + shift for v in centres]

    y0 = -total / 4.0
    y1 = y0 + l_arm
    y_tap = y0 + tap_frac * total
    if y_tap >= y1:
        raise ValueError(
            f"抽头位置 τ={tap_frac} 超出单臂（y_tap={y_tap:.4f}m ≥ 臂顶"
            f" {y1:.4f}m）；减小 tap_frac 或 arm_gap_mm")
    # 取向：flips[i]=第 i 腔上下翻转（alternating 下奇数序腔），开路端/弯带互换；
    # 输出抽头随末腔取向自其开路端计 τ·L_tot（翻转腔开路端在 y1 → 向下计）
    flips = [orientation == "alternating" and (i % 2 == 1) for i in range(n)]
    y_open = [y1 if f else y0 for f in flips]
    y_bend = [y0 if f else y1 for f in flips]
    y_tap_out = (y1 - tap_frac * total) if flips[-1] else y_tap
    return {"n": n, "wf": wf, "arm_gap": arm_gap, "b": b, "l_arm": l_arm,
            "total": total, "gaps": gaps, "xs": xs, "centres": centres,
            "y0": y0, "y1": y1, "y_tap": y_tap, "tap_frac": tap_frac,
            "x_feed_in": xs[0], "x_feed_out": xs[-1],
            "orientation": orientation, "flips": flips,
            "y_open": y_open, "y_bend": y_bend,
            "y_taps": [y_tap, y_tap_out], "y_tap_out": y_tap_out}


def _hairpin_lines(p: dict[str, Any]) -> str:
    # 发夹线 BPF（WP2.3 Tier1 附加模板）：N 个 U 形 λg/2 谐振器沿 x 并排，
    # 相邻外臂平行耦合；50Ω 抽头馈线（T 形）自板边接首/末外臂。等缝口径
    # gap_mm；逐缝非等耦合走 gaps_mm 列表。口径见文末 WP2.3 hairpin 段。
    lay = _hairpin_layout(p)
    return f'''N = {lay["n"]}
WF = {lay["wf"]!r}                       # 谐振器/馈线宽（50Ω，HJ）
B = {lay["b"]!r}                         # U 内两臂中心距
LARM = {lay["l_arm"]!r}                  # 单臂长（展开 2·LARM+B=λg/2）
Y0 = {lay["y0"]!r}                       # U 开路端 y
Y1 = {lay["y1"]!r}                       # 臂顶/弯带中心 y
YT = {lay["y_tap"]!r}                    # 抽头 y（自开路端计 τ·λg/2）
XS = {lay["xs"]!r}                       # 各谐振器 [左臂心, 右臂心]（m）
hairpin = CSX.AddMetal("hairpin")
for _i in range(N):
    _xl = XS[2 * _i]
    _xr = XS[2 * _i + 1]
    hairpin.AddBox((_xl - WF / 2, Y0, H_SUB),
                   (_xl + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xr - WF / 2, Y0, H_SUB),
                   (_xr + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xl - WF / 2, Y1 - WF / 2, H_SUB),
                   (_xr + WF / 2, Y1 + WF / 2, H_SUB), priority=10)
# 抽头馈线（T 形）：板边 x=∓BOARD → 首/末谐振器外臂中心
hairpin.AddBox((-BOARD, YT - WF / 2, H_SUB),
               (XS[0], YT + WF / 2, H_SUB), priority=10)
hairpin.AddBox((XS[-1], YT - WF / 2, H_SUB),
               (BOARD, YT + WF / 2, H_SUB), priority=10)
# 去嵌（WP2.3 收口 A1，2026-09-16）：测量面自板边推到抽头结前 10·NEAR+4·H_SUB
# （≈3mm，首版纯 10·NEAR≈1mm 落进结区网格加密过渡带——三探针 U_delta=[0.28, 0.19]mm
# 非均匀，openEMS β 二阶差分假定均匀间距 → β 金标准恒定 −23%（τ=0.30 实测，全带平
# 坦）；4·H_SUB≈2mm 回到均匀 base 网格，β 恢复）。残量 ≈3mm≈0.043λg，且 |S| 幅值
# 类指标本与参考面位置无关（无损馈线上平移不改幅值）；旧口径 feed_len/3 留 2/3
# ≈34mm≈0.49λg 未去嵌才是相位类分析的问题。端口 start/stop/FeedShift 不动，
# 其它模板仍用官方 端口段长/3（均匀通线口径）。
_port1 = MSLPort(CSX, port_nr=1, metal_prop=hairpin,
                 start=np.array([-BOARD, YT + WF / 2, H_SUB]),
                 stop=np.array([XS[0], YT - WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=hairpin,
                 start=np.array([BOARD, YT - WF / 2, H_SUB]),
                 stop=np.array([XS[-1], YT + WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in hairpin.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''


# ── hairpin_alt：交替取向发夹线（2026-09-18 w2g，TODO 0dk 根修 / audit #11）──
# 物理（0dk 真机结论）：同向 U 并排时相邻臂开路端对齐，电耦合
# （开路端电压反节点对齐）与磁耦合（弯带电流反节点对齐、相邻臂电流反向）反号相消，
# k_EM=c(gap)·k_KJ 非单调、极大 0.0155@0.65 ≪ KJ 名义 0.0515（比值上限 ≈0.30），
# FBW5% 名义在同向参数空间内无自洽设计点。经典 hairpin 排布（Hong《Microstrip
# Filters》§5.6）把相邻谐振器交替翻转：相邻臂一端开路/一端弯带互补，电/磁耦合同号
# 叠加，k_EM 应回到平行耦合线闭式量级——本变体即此拓扑。
# 名义（铁律 #1c/#252：全部综合精算，无手抄毫米数）= hairpin_design_from_order
# (3, 2.5, 0.05, 20.0) **纯 KJ 链**（kgap_corrected=False：同向 c(gap) 表是同向
# 结构效应，对交替取向不适用；c_alt(gap)≈1 是预声明假设，待真机 k(gap) 图谱以
# scripts/hairpin_q_extract.hairpin_alt_kgap_gate 判读）按 hairpin 同规则舍入
# （w/arm_len/gap 4 位、τ 6 位）；arm_len × c_f0=1.0370（B2 同向 pt4 标定的 U 弯+
# 开路端等效缩短，属逐腔几何效应、与相邻取向无关——先验沿用，alt 真机复标后可改）；
# τ 走 c(τ) 修正重解（B1 单腔标定，抽头结构逐腔相同）。四项名义与 hairpin 逐位相同
# 是设计链的必然结果（唯一变量=取向），单测按链复算钉住而非拷贝。
# 选型理由（另立模板名而非改 hairpin 缺省）：① 同向 c(gap) 表/名义定版/A1-B3 标定
# 链全部绑定同向拓扑，改缺省会让既有标定与 fake 通道口径失效；② fake 派发按模板名
# 选修正链（hairpin 乘 c(gap)、hairpin_alt 纯 KJ），双模板即双口径无歧义；③ 注册
# 四件套契约现成（#247 既有键不重排：本段注册在 hairpin 之后、coupled_bpf 之前，
# 槽线族仍居字典尾）。orientation="same" 保留为 hairpin_alt 的布局选项（不进 params/
# nominal：字符串非几何量，审计扰动器只吃数值），用于同网格 A/B 对照渲染。
HAIRPIN_ALT_META: dict[str, Any] = {
    "f0_ghz": 2.5, "n_ports": 2,
    "extraction": "S11/S21 @ MSLPort 1-2（交替取向发夹线 BPF：带内回波纹波 + 带外"
                  "抑制；裁判=C13 耦合矩阵闭式 coupling_matrix_response，gap→k 纯 KJ）",
    "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
    "params": ["order", "w_mm", "arm_len_mm", "arm_gap_mm", "gap_mm",
               "tap_frac"],
    "topology": "交替取向发夹线带通（0dk 根修变体）：N 个 λg/2 半波谐振器折成 U 形"
                " 沿 x 并排，**奇数序谐振器上下翻转**（弯带/开路端 y 逐腔轮替），"
                " 相邻臂开路端交替 → 电/磁耦合同号叠加；相邻外臂平行耦合（缝"
                " gap_mm）；输入/输出为 50Ω 抽头馈线（板边 x=∓BOARD 至首/末谐振器"
                " 外臂，抽头位置 tap_frac 各自开路端计，末腔翻转时输出抽头自 y1 向下）",
    "param_semantics": "order=谐振器阶数 N，w_mm=谐振器/馈线宽（50Ω，skrf HJ "
                       "综合），arm_len_mm=展开中心线总长 λg/2（2·臂长+臂间距）×"
                       "c_f0（U 弯/开路端等效缩短先验 1.0370），arm_gap_mm=U 内两臂缝"
                       "（名义 3.0：k_self(3.0)=0.0115 ≪ 互耦 0.0515），gap_mm=相邻"
                       "谐振器耦合缝——**纯 KJ 口径** k=(Z0e−Z0o)/(Z0e+Z0o)，不乘同向"
                       "结构修正 c(gap)（预声明 c_alt∈[0.6,1.2]，真机 k(gap) 图谱判读"
                       "门 hairpin_alt_kgap_gate 未过前 campaign_capable=False），"
                       "tap_frac=抽头位置比例 τ=t/L_tot（各自开路端计）；可选布局"
                       "选项 orientation=alternating|same（缺省 alternating，same="
                       "同网格同向对照，不进 params）",
    "mesh_note": "mesh_resolution_mm=网格 base 覆盖（mm）；0=自动 λ_sub/50；"
                 "全部臂缘/逐腔弯带缘/开路端/两抽头缘精确入网（#198），网格配方"
                 "与 hairpin 同源（A/B 只隔离取向）",
}

HAIRPIN_ALT_NOMINAL: dict[str, Any] = {
    "order": 3,
    # 名义 = hairpin_design_from_order(3, 2.5, 0.05, 20.0) 纯 KJ 链舍入（w/arm_len/
    # gap 4 位、τ 6 位）；test_hairpin_alt_template 按链复算钉住（#252，非拷贝）
    "w_mm": 1.1117,            # lossless_width_mm(50Ω @2.5GHz，εr3.66 h0.508 无耗档；XC-W 单源
                               # core/synthesis.lossless_width_mm——与 yaml 层叠档 1.1134 并存
                               # 系 tanδ 参数系不同非同参漂移，test_width_single_source 钉)
    # 闭式 λg/2=35.4676（εeff=2.8578 @w，HJ）× c_f0 1.0370（fake_adapter._HAIRPIN_F0_CORR
    # 先验；逐腔 U 弯+开路端效应，与取向无关）
    "arm_len_mm": 36.7799,
    "arm_gap_mm": 3.0,         # k_self(3.0)=0.0115 < 互耦 0.0515（同 hairpin A2 理由）
    # C13 N=3/RL=20dB/FBW=0.05 → k=0.051514 → KJ 反解 s=1.132829mm（不乘 c(gap)）
    "gap_mm": 1.1328,
    # Q_e=17.0689 → c(τ)=1.37437−0.75218·τ 修正重解 τ*=0.398159（闭式 0.401892）
    "tap_frac": 0.398159,
}

# 注册四件套：① docs/templates/hairpin_alt/meta.yaml；② test_template_geometry_audit
# .EXPECTED_TEMPLATES（42→43，单源）；③ fake_adapter 派发（hairpin 分支并列、纯 KJ）；
# ④ models/template_specs（_register_hairpin_alt）。同对象注册，既有键不重排（#247）。
TEMPLATE_META["hairpin_alt"] = HAIRPIN_ALT_META
TEMPLATE_NOMINAL["hairpin_alt"] = HAIRPIN_ALT_NOMINAL


def hairpin_alt_meta() -> dict[str, Any]:
    """返回 hairpin_alt 模板元数据（与 template_meta("hairpin_alt") 同构的便捷别名）。"""
    meta = dict(HAIRPIN_ALT_META)
    meta["template"] = "hairpin_alt"
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(HAIRPIN_ALT_NOMINAL)
    return meta


def _hairpin_alt_orientation(p: dict[str, Any]) -> str:
    """hairpin_alt 布局取向选项：缺省 alternating；"same" 渲染同向对照（同网格 A/B）。"""
    orientation = str(p.get("orientation", "alternating"))
    if orientation not in _HAIRPIN_ORIENTATIONS:
        raise ValueError(
            f"hairpin_alt orientation 须为 {_HAIRPIN_ORIENTATIONS}（得 {orientation!r}）")
    return orientation


def _hairpin_alt_layout(p: dict[str, Any]) -> dict[str, Any]:
    """hairpin_alt 几何单源（render/_near_points/geometry_spec 共用）。"""
    return _hairpin_layout(p, orientation=_hairpin_alt_orientation(p))


def _hairpin_alt_lines(p: dict[str, Any]) -> str:
    # 交替取向发夹线 BPF：几何与 _hairpin_lines 同源（_hairpin_layout），差异只在
    # 逐腔弯带 y（YBEND[i]）与两抽头 y（YT[0]/YT[1]）；端口/去嵌/priority 口径照抄
    # hairpin（A1 去嵌 10·NEAR+4·H_SUB，均匀馈段三探针）。
    lay = _hairpin_alt_layout(p)
    return f'''N = {lay["n"]}
ORIENTATION = {lay["orientation"]!r}     # alternating=奇数序腔翻转 / same=同向对照
WF = {lay["wf"]!r}                       # 谐振器/馈线宽（50Ω，HJ）
B = {lay["b"]!r}                         # U 内两臂中心距
LARM = {lay["l_arm"]!r}                  # 单臂长（展开 2·LARM+B=λg/2）
Y0 = {lay["y0"]!r}                       # 臂下端 y（未翻转腔的开路端）
Y1 = {lay["y1"]!r}                       # 臂上端 y（未翻转腔的弯带中心）
YOPEN = {lay["y_open"]!r}                # 各谐振器开路端 y（交替：Y0/Y1 轮替）
YBEND = {lay["y_bend"]!r}                # 各谐振器弯带中心 y（与 YOPEN 互补）
YT = {lay["y_taps"]!r}                   # [输入, 输出] 抽头 y（各自开路端计 τ·λg/2）
XS = {lay["xs"]!r}                       # 各谐振器 [左臂心, 右臂心]（m）
hairpin = CSX.AddMetal("hairpin")
for _i in range(N):
    _xl = XS[2 * _i]
    _xr = XS[2 * _i + 1]
    hairpin.AddBox((_xl - WF / 2, Y0, H_SUB),
                   (_xl + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xr - WF / 2, Y0, H_SUB),
                   (_xr + WF / 2, Y1, H_SUB), priority=10)
    hairpin.AddBox((_xl - WF / 2, YBEND[_i] - WF / 2, H_SUB),
                   (_xr + WF / 2, YBEND[_i] + WF / 2, H_SUB), priority=10)
# 抽头馈线（T 形）：板边 x=∓BOARD → 首/末谐振器外臂中心（末腔翻转时 YT[1]≠YT[0]）
hairpin.AddBox((-BOARD, YT[0] - WF / 2, H_SUB),
               (XS[0], YT[0] + WF / 2, H_SUB), priority=10)
hairpin.AddBox((XS[-1], YT[1] - WF / 2, H_SUB),
               (BOARD, YT[1] + WF / 2, H_SUB), priority=10)
# 去嵌口径同 hairpin（WP2.3 收口 A1）：测量面 = 抽头结前 10·NEAR+4·H_SUB
_port1 = MSLPort(CSX, port_nr=1, metal_prop=hairpin,
                 start=np.array([-BOARD, YT[0] + WF / 2, H_SUB]),
                 stop=np.array([XS[0], YT[0] - WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=1, FeedShift=10 * NEAR,
                 MeasPlaneShift=(XS[0] + BOARD) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
_port2 = MSLPort(CSX, port_nr=2, metal_prop=hairpin,
                 start=np.array([BOARD, YT[1] - WF / 2, H_SUB]),
                 stop=np.array([XS[-1], YT[1] + WF / 2, 0]),
                 prop_dir="x", exc_dir="z", excite=0, FeedShift=10 * NEAR,
                 MeasPlaneShift=(BOARD - XS[-1]) - 10 * NEAR - 4 * H_SUB,
                 priority=10)
# MSLPort 自动补画的馈线原语 priority 统一提到 10（官方口径）
for _prim in hairpin.GetAllPrimitives():
    if _prim.GetPriority() < 10:
        _prim.SetPriority(10)
'''
