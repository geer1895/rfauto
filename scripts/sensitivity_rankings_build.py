"""X7 敏感性排序数据面生成器：可算模板闭式弹性 → knowledge/sensitivity_rankings.yaml。

W8 桥（scripts/capability_cards_export.resolve_sensitivity，review_ge8e F1 处置②）
的消费端闭环件：登记表落档后重跑 capability_cards_export.py，卡面敏感性节自动
从 teaching/回退态升级为 computed（W8 机制零代码改动）。

方法（可复现口径，全确定性、离线、零随机、零仿真）：
    对每模板的注册名义参数（TEMPLATE_NOMINAL 单源，adapters/oe_templates/
    registry.py + render_antenna2 合并块）逐个中心差分扰动：
      连续参数 ±1%（相对步长）；整数参数（n_segments/helix_turns）±1 单位步；
      score = |Δln(y)/Δln(x)|（归一化弹性，取绝对值——登记表 schema 只收
      非负分数；符号语义见各 _target_* docstring）。
    目标量 y = 模板核心闭式输出（按模板族选型，逐模板定义见 _TARGETS），
    全部复用仓内既有确定性内核（core/synthesis.forward_z0/forward_media、
    core/calc_families/rf_line 共形映射闭式、core/calc_families/rf_match
    E4 衰减器闭式、core/coupled_microstrip KJ 偶/奇模、fake_adapter.
    antenna2_resonance_ghz 设计式精确逆）——不自造物理数字（铁律 7）。
    εeff 弱色散：在模板 meta f0_ghz 处取值（antenna2 fake 同口径）。
    n_samples = 1 + 2·n_params（名义点 + 每参数 ± 两点）。

可算集判定（首批 18 + 架构批 A3-D 扩批 +22 + R8-KN 扩批 +4
    + 架构批 SENS-ANC 复核扩批 +2 = 46；架构批 W4-S19 全覆盖批 +24
    = 70/72；架构批 W6-S4 sir_bpf 名义重注册解锁 +1 = 71/72，余 1 族
    如实留缺，见「W4-S19 全覆盖批」节）：
    首批 X7（2026-10-04）：25 个模板有确定性闭式目标量可扰动（19
    TEMPLATE_NOMINAL 原生 + 6 antenna2 设计式精确逆）；其中 9 个已有
    meta.yaml teaching.sensitivity_ranking（wilkinson/branchline/cpw/dipole/
    hairpin/mline/patch/pyramid_horn/ratrace）——本批不入表，理由：① W8
    回归钉 test_w6_sensitivity_face_non_regression 逐字节冻结
    wilkinson(teaching)/ring_resonator(回退)卡节，入表即红（钉前提="该
    模板当前无登记表条目"）；② teaching 面（EP-5 名次）另含 er/h 基板
    敏感性而闭式几何弹性不含，teaching 卡保留无信息损失；③ 升级面从
    None→computed，teaching 卡与回退卡逐字节零变化，卡面 diff 可审计。
    架构批 A3-D 扩批（2026-10-11）：新 +22 目标（nway_wilkinson/
    branchline_2sect/cline_coupler/lange/fgcpw/slotline/slotline_lumped/
    embedded_ms/inverted_ms/isl_shielded/sicl/coil_nfc/ms_patch/
    ms_ring_patch/ms_cross/ms_jcross/ms_mushroom/siw/hmsiw/vivaldi_tsa/
    marchand_balun/msl_slot_transition）——全部复用仓内核闭式（fgcpw/
    embedded/inverted/isl/sicl/slotline/hmsiw/amc/vivaldi/nfc 专族内核 +
    forward_media/coupled_microstrip 既有单源），目标量定义逐条见
    _target_* docstring。ridged_wg/coax_waveguide_transition/sma_launcher
    三模板名义参数含 0 值（h_mm=0 空气波导/tan_d_fill=0），正域守卫不可
    扰动，如实不入表（teaching-only）。**双源并存政策（本批起）**：这批
    模板同时持有 meta.yaml teaching 卡（EP-5 名次+依据）与登记表幅值条目
    ——W8 消费优先级 computed > teaching（capability_cards_export.
    resolve_sensitivity 三态①），卡面显示幅值分、teaching 名次保留在
    teaching CLI 面，两源不冲突；首批 9 模板维持不入表（卡面字节钉前提
    不变）。
    架构批 R8-KN 扩批（2026-10-13）：新 +4 目标（diplexer/schiffman/
    msl_cpw/msl_siw_taper）——A3-D 批「级联/过渡需逐模板装配」判定按
    marchand_balun/msl_slot_transition 同款先例收窄：过渡/网络族的段
    参数与内核相位单点闭式可扰动即入表（diplexer=CR 对偶 fc 臂定标
    diplexer_lpf_hpf 单源；schiffman=Δφ(f0) 内核相位链
    schiffman_delta_phase+KJ 偶/奇模正演；msl_siw_taper=SIW 段 Cassivi
    截止与 siw 同式；msl_cpw=CPWG 段 _cpwg_ri 单源）——四族名义回代
    设计点逐位核验（Δφ=90.0°/fc=2.5000 与 6.6667/Z0=50.000）。其余
    仍无单点闭式目标量的模板如实不入表（不硬凑）：①滤波器链 gaps_mm/
    widths_mm 列表参数型（combline/coupled_bpf/interdigital/sir_bpf/
    qwt_multisection，弹性管线非数值拒收）；②无名义推导锚的级联/交叉
    耦合（xcheb_bpf4/hairpin_alt/varactor_bpf）；③阵列族（patch_array_*/
    patch_eep_*/ms_array_NxN/mmwave_series_array：cell_map/列表参数或
    阵列级装配；单元级谐振属 patch 族教学面口径）；④ring_resonator
    闭式恒等式在档（r_mean=c/(2πf√εeff)）但为 W8 回退卡字节钉代表
    （test_w6_sensitivity_face_non_regression +
    test_sensitivity_rankings_registry 双钉位），入表需先移钉（跨席
    契约，非数据批授权）；⑤edb_* 五模板=EDB 快车道信息文档形态，
    不入 TEMPLATE_NOMINAL 注册面（meta 自述 72 项冻结不扫描），
    capability_cards 消费面不覆盖，登记表 universe=注册模板（72 口径）。
    架构批 SENS-ANC 复核扩批（2026-10-14）：+2（varactor_bpf/xcheb_bpf4）
    ——R8-KN「缺推导锚」组的 #222 树面复核勘误：两族名义推导链实为纯闭式
    内核单源（varactor.varactor_bpf_design 装载谐振链：突变结 C(bias)→主谐
    振方程正解，c823ac45 引入；cross_coupled_map.cross_coupled_bpf_design
    开路环周长恒等式 perimeter=λg/2−2Δl、a=perimeter/4，897eba0f 引入），
    名义回代 f0=2.499997/2.499993（4 位舍入传播带内）。同组 hairpin_alt
    维持不入表——arm_len 名义含经验先验乘子 c_f0=1.0370（render_hairpin
    段头「alt 真机复标后可改」）且 campaign_capable=False（kgap 门未过），
    非稳定闭式恒等。

    架构批 W4-S19 全覆盖批（2026-10-18）：+24（teaching 首批 9 模板全部
    入表转双源并存 + coax_waveguide_transition/ridged_wg/sma_launcher/
    ring_resonator/qwt_multisection/coupled_bpf/combline/interdigital/
    hairpin/hairpin_alt/pyramid_horn + 6 阵列族 patch_array_1x4/2x2/
    series、patch_eep_1x4/2x2、mmwave_series_array），登记表 46→70/72。
    ① **首批 9 teaching 模板入表**：W6 卡面字节钉前提按本批任务书裁决
    解除（钉测试同批重生成——computed 幅值面上卡、teaching EP-5 名次保留
    teaching CLI 面，W8 消费优先级 computed>teaching 不变）。
    ② **hairpin/hairpin_alt 入表勘误（SENS-ANC 留缺判定复核）**：fake
    裁判谐振式 _HAIRPIN_F0_CORR=1.0370（B2 pt4 真机标定常数，fake_adapter
    单源，K_HELIX 同性质）本就是恒等式一部分——y=c_f0·c/(2·arm·√εeff)
    名义回代 2.502/2.502（+0.1% 带内），「非稳定闭式」判定按 #222 树面
    复核勘误。
    ③ **列表参数管线扩展**：gaps_mm/widths_mm/lengths_mm 等正数值列表
    按整体 ±1% 等比缩放扰动（弹性分母=ln(1.01)−ln(0.99)，与连续参数
    相对步长同语义）；非数值列表（ms_array_NxN cell_map）不可扰动。
    ④ **零值名义参数**（h_mm=0/tan_d_fill=0）：正域守卫不可扰动，登记
    0 分并在 NON_PERTURBABLE 声明缘由（显式「不进恒等式」陈述，非缺失）。
    ⑤ **如实留缺 1 族**：(a) sir_bpf——**已于 架构批 W6-S4 解锁入表**
    （2026-10-19，R3 审计「解锁性最高」处方）：名义重注册 l_high
    6.7818（旧档=理想短路 7.1055 − 登记⑨+R1 校准 0.125nH 过孔缩短
    0.3237，恒等式名义回代 2.5586GHz 失自洽=留缺主因）→ 7.1055（理想
    短路缺省链输出 4 位舍入，render_c3.SIR_BPF_NOMINAL+meta.yaml 同笔
    回填），恒等式 tanθ1·tanθ2=Z_lo/Z_hi 名义回代 2.5000（4 位舍入带
    内）——第 71 族解锁；过孔补偿留 render 通道 l_via_h 锚运行时行为；
    (b) ms_array_NxN——单元几何全部埋在
    cell_map 非数值结构（list[list[dict]]），无标量几何自由度可扰动，
    阵列级（n_x/n_y/period）无单点闭式目标量，全零登记无信息量，留缺。
    ⑥ **名义档代际偏移（如实登记，不改名义）**：branchline arm_len 系
    #252 诊断的 (εr+1)/2 薄线极限捷径遗留档（回代 2.116 vs meta 2.4，恒
    等式取综合内核 XA-3 HJ 口径）；dipole 58mm 系 #194 冒烟板遗留（回代
    2.584）；patch (34.9/50) 系注册期设计点（现行 synthesize_patch 缺省
    设计点 32.08/40.92，回代 2.240）；interdigital/combline res_len 名义
    早于现行 Δl 口径（回代 2.564/2.63）——弹性分数刻画的是恒等式局部
    敏感性，名义档龄不改变分数有效性，逐模板 docstring 记录回代值。

写入契约（runs/qw5_b32_capability_cards/design_note.md）：schema
sensitivity_rankings/v1；运行时只读、写入只经人工 commit（anchors.yaml 家法）。
本脚本只负责确定性重生成；source_run 指针指向本脚本（可重跑证据面）。

用法：
    python scripts/sensitivity_rankings_build.py             # 写登记表+摘要
    python scripts/sensitivity_rankings_build.py --check     # 只校验不写
    python scripts/sensitivity_rankings_build.py --template cps
"""

from __future__ import annotations

import argparse
import math
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "knowledge" / "sensitivity_rankings.yaml"

SCHEMA = "sensitivity_rankings/v1"
BATCH_ID = "架构批"
BATCH_DATE = "2026-10-19"
METHOD = "central_finite_difference_elasticity"
SOURCE_RUN = "scripts/sensitivity_rankings_build.py"
REL_STEP = 0.01  # 连续参数相对步长 ±1%
C_MM_GHZ = 299.792458  # mm·GHz（仓内闭式通用光速常数口径）
DEFAULT_STACKUP = "rogers4350b_h0.508"
# 带状线双板压合腔高（synthesize_stripline_model 缺省口径；非名义参数，
# 常量出处同源：两块 0.508mm 板压合）
STRIPLINE_B_MM = 1.016

# teaching 卡并存集合（W4-S19 全覆盖批起这 9 模板同时持有 teaching EP-5
# 名次卡与登记表幅值条目——W8 消费优先级 computed>teaching，teaching 名次
# 保留 teaching CLI 面；不再作为入表排除面，历史排除语义见模块 docstring
# 「架构批 W4-S19 全覆盖批」节①）
TEACHING_TEMPLATES = frozenset({
    "wilkinson", "branchline", "cpw", "dipole", "hairpin", "mline",
    "patch", "pyramid_horn", "ratrace",
})

# 零值名义参数（正域守卫不可扰动）：登记 0 分（「不进目标恒等式」显式
# 陈述——schema 只收非负分数，0 分语义见 test 钉），缘由逐条声明
NON_PERTURBABLE: dict[str, dict[str, str]] = {
    "pyramid_horn": {
        "h_mm": "h_mm 名义 0.0（空气填充无介质板，meta nominal_derivation）——"
                "零值不可中心差分；er=1.0 可扰动但增益内核（horn_gain_direct）"
                "不消费介质通道，弹性自然为 0",
    },
    "coax_waveguide_transition": {
        "h_mm": "h_mm 名义 0.0（波导段无介质板）——零值不可中心差分",
    },
    "ridged_wg": {
        "h_mm": "h_mm 名义 0.0（空气填充脊波导，内核=空气 PEC 壁口径）——"
                "零值不可中心差分",
    },
    "sma_launcher": {
        "tan_d_fill": "tan_d_fill 名义 0.0（无耗填充口径）——零值不可中心差分",
    },
}


# ── 目标量定义（逐模板闭式恒等式；全部 live import 仓内内核）────────────────

def _meta(template: str) -> dict[str, Any]:
    """模板注册元数据（TEMPLATE_META+TEMPLATE_NOMINAL 合并单源）。"""
    from rfauto.adapters.openems_templates import template_meta

    return template_meta(template)


def _params(template: str) -> dict[str, Any]:
    """注册名义参数（单源；卡面「名义参数」表同源）。"""
    return dict(_meta(template)["nominal_params"])


def _substrate(template: str) -> tuple[float, float]:
    """(er, h_mm)（meta substrate；缺省回退 rogers4350b 名义口径）。"""
    sub = _meta(template).get("substrate") or {}
    return float(sub.get("er", 3.66)), float(sub.get("h_mm", 0.508))


def _f0(template: str) -> float:
    """εeff 取值频率（meta f0_ghz；弱色散口径，antenna2 fake 同源）。"""
    return float(_meta(template)["f0_ghz"])


def _stackup():
    from rfauto.core.synthesis import Stackup

    return Stackup.from_materials_yaml(DEFAULT_STACKUP)


def _z0_of(w_mm: float, f_ghz: float):
    """skrf HJ 正向 (Z0, εeff)（core/synthesis 唯一介质口径，铁律 1c）。"""
    from rfauto.core.synthesis import forward_z0

    return forward_z0(float(w_mm), float(f_ghz), _stackup())


def _eps_eff_of(w_mm: float, f_ghz: float) -> float:
    return float(_z0_of(w_mm, f_ghz)[1])


# 每模板目标量：param dict → float（核心闭式输出；符号语义见 docstring）
_TARGETS: dict[str, Callable[[dict[str, Any]], float]] = {}


def _target(name: str):
    def _deco(fn: Callable[[dict[str, Any]], float]):
        _TARGETS[name] = fn
        return fn
    return _deco


@_target("cps")
def _t_cps(p: dict[str, Any]) -> float:
    """y=Z0（Wadell 均匀线+板映射+FD 定标，_cps_ri 单源）。
    符号：dw→Z0 降（负）、dgap→Z0 升（正）；line_len 不进 Z0 恒等式（0）。"""
    from rfauto.core.calc_families.rf_line import _cps_ri

    er, h = _substrate("cps")
    return float(_cps_ri(p["w_mm"], p["gap_mm"], h, er)[1])


@_target("stripline")
def _t_stripline(p: dict[str, Any]) -> float:
    """y=Z0（零厚度对称共形映射 _stripline_z0，TEM εeff=εr）。
    符号：dw→Z0 降；line_len 不进 Z0（0）。"""
    from rfauto.core.calc_families.rf_line import _stripline_z0

    er, _h = _substrate("stripline")
    return float(_stripline_z0(p["w_mm"], STRIPLINE_B_MM, er))


@_target("suspended_stripline")
def _t_suspended_stripline(p: dict[str, Any]) -> float:
    """y=Z0（悬置带线 FD 重定标闭式 _suspended_stripline_ri）。
    符号：dw→Z0 降、db→Z0 升（b 腔电容摊薄）；line_len 不进 Z0（0）。"""
    from rfauto.core.calc_families.rf_line import _suspended_stripline_ri

    er, h = _substrate("suspended_stripline")
    return float(_suspended_stripline_ri(
        p["w_mm"], p["b_mm"], h, er)[1])


@_target("wstep")
def _t_wstep(p: dict[str, Any]) -> float:
    """y=阶跃反射 |Γ|=|Z2−Z1|/(Z2+Z1)（synthesize_wstep_model 同式）。
    符号：dZ1=dw1→|Γ| 升（负向差增大）、dw2 对称；line_len 不进（0）。"""
    f0 = _f0("wstep")
    z1, _ = _z0_of(p["w1_mm"], f0)
    z2, _ = _z0_of(p["w2_mm"], f0)
    return abs((z2 - z1) / (z2 + z1))


@_target("tjunc")
def _t_tjunc(p: dict[str, Any]) -> float:
    """y=全臂 Z0（对称均分口径的设计恒等式，synthesize_tjunc_model 同源：
    结点地板 Sii=−1/3 由对称性给出，与臂长无关）。
    符号：dw→Z0 降；through/branch_len 不进（0）。"""
    z0, _ = _z0_of(p["w_feed_mm"], _f0("tjunc"))
    return float(z0)


@_target("bend")
def _t_bend(p: dict[str, Any]) -> float:
    """y=臂 Z0（未切角弯折基元设计恒等式，synthesize_bend_model 同源）。
    符号：dw→Z0 降；arm_len 不进 Z0（0）。"""
    z0, _ = _z0_of(p["w_mm"], _f0("bend"))
    return float(z0)


@_target("via")
def _t_via(p: dict[str, Any]) -> float:
    """y=反焊盘同轴口径 Z_via=(60/√εr)·ln(r_pad/r_via)
    （synthesize_via_model 设计规则同式；antipad_mm=r_pad）。
    符号：dantipad→Z 升（+1）、dr_via→Z 降（−1）；w 不进（0）。"""
    er, _h = _substrate("via")
    return 60.0 / math.sqrt(er) * math.log(p["antipad_mm"] / p["r_via_mm"])


@_target("atten_pi")
def _t_atten_pi(p: dict[str, Any]) -> float:
    """y=π 型中串电阻 r_series_mid=E4 闭式(atten_db, Z0(w))
    （synthesize_atten_pi_model 主输出）。
    符号：dZ0=dw→R 升（线性）、datten_db→R 升（n²−1 通道，10dB 档弹性
    ~0.14<|dlnZ0/dlnw|）；shunt_off 不进（0）。"""
    from rfauto.core.calc_families.rf_match import attenuator_pi

    z0, _ = _z0_of(p["w_mm"], _f0("atten_pi"))
    return float(attenuator_pi(p["atten_db"], z0)["r_series_mid_ohm"])


@_target("atten_t")
def _t_atten_t(p: dict[str, Any]) -> float:
    """y=T 型串臂电阻 r_series_arm=E4 闭式(atten_db, Z0(w))
    （synthesize_atten_t_model 主输出）。符号语义同 atten_pi。"""
    from rfauto.core.calc_families.rf_match import attenuator_t

    z0, _ = _z0_of(p["w_mm"], _f0("atten_t"))
    return float(attenuator_t(p["atten_db"], z0)["r_series_arm_ohm"])


@_target("stepped_impedance")
def _t_stepped_impedance(p: dict[str, Any]) -> float:
    """y=SIR 基模 f0：θ_total(f0)=π（λ/2 谐振），段链奇偶交替
    （_stepped_lines 渲染同源：偶段 z1/奇段 z2，各 seg_len）⇒
    f0=c/(2·Σ L_i√εeff_i)。符号：dlen→f0 降（−1 族）、dw→εeff 升→f0 降
    （负小量）；feed_w 为 50Ω 馈线（不进段链谐振式，0）；n_segments 整数
    弹性（±1 单位步）≈−1。"""
    n = int(p["n_segments"])
    n1 = (n + 1) // 2  # 偶数段（0 基）走 z1
    n2 = n - n1
    f0 = _f0("stepped_impedance")
    ee1 = _eps_eff_of(p["z1_width_mm"], f0)
    ee2 = _eps_eff_of(p["z2_width_mm"], f0)
    seg = float(p["seg_len_mm"])
    return C_MM_GHZ / (2.0 * (n1 * seg * math.sqrt(ee1)
                              + n2 * seg * math.sqrt(ee2)))


@_target("coupled_line")
def _t_coupled_line(p: dict[str, Any]) -> float:
    """y=耦合段 λ/4 谐振 f0=c/(4·L·√εeff_avg)，εeff_avg=(εe+εo)/2
    （KJ 偶/奇模填充因子，coupled_microstrip_even_odd_ohm 单源；λ/4 耦合
    节拍口径）。符号：dlen→f0 降（−1）；dw/dgap 经偶/奇模填充二阶进入。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    er, h = _substrate("coupled_line")
    _ze, _zo, ee, eo = coupled_microstrip_even_odd_ohm(
        p["line_w_mm"], p["gap_mm"], _f0("coupled_line"), er, h)
    return C_MM_GHZ / (4.0 * p["coupled_len_mm"]
                       * math.sqrt(0.5 * (ee + eo)))


@_target("gysel")
def _t_gysel(p: dict[str, Any]) -> float:
    """y=臂 λ/4 谐振 f0=c/(4·arm_len·√εeff(w_arm))（XA-3 迭代序：臂线宽
    自身 εeff，forward_media 单源）。符号：darm_len→f0 降（−1）、dw_arm→
    εeff 升→f0 降（负小量）；w_feed/iso_len 不进臂谐振式（0）。"""
    from rfauto.core.synthesis import forward_media

    media = forward_media(p["w_arm_mm"], _f0("gysel"), _stackup())
    return C_MM_GHZ / (4.0 * p["arm_len_mm"] * math.sqrt(media.er_eff))


@_target("monopole")
def _t_monopole(p: dict[str, Any]) -> float:
    """y=λ0/4 设计式精确逆 f=c/(4·L)（antenna2_resonance_ghz 同式）。
    符号：dL→f 降（−1）；mon_w/feed_gap 不进谐振式（0）。"""
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    er, h = _substrate("monopole")
    return antenna2_resonance_ghz("monopole", p, eps_eval_ghz=_f0("monopole"),
                                  er=er, h_mm=h)


@_target("pifa")
def _t_pifa(p: dict[str, Any]) -> float:
    """y=L 路径式精确逆 f=c/(4·L·√εeff(W))（HJ @W；居中短路板不绕行，
    真机两轮实证定版口径）。符号：dL→f 降（−1）、dW→εeff 升→f 降（负小量）；
    Ws/pin_back/pin_y 不进谐振式（0，param_semantics 明示）。"""
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    er, h = _substrate("pifa")
    return antenna2_resonance_ghz("pifa", p, eps_eval_ghz=_f0("pifa"),
                                  er=er, h_mm=h)


@_target("ifa")
def _t_ifa(p: dict[str, Any]) -> float:
    """y=臂 λ/4 设计式精确逆 f=c/(4·L·√εeff(w))（HJ @臂宽）。
    符号：dL→f 降（−1）、dw→负小量；feed_off 不进谐振式（0）。"""
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    er, h = _substrate("ifa")
    return antenna2_resonance_ghz("ifa", p, eps_eval_ghz=_f0("ifa"),
                                  er=er, h_mm=h)


@_target("loop")
def _t_loop(p: dict[str, Any]) -> float:
    """y=自由空间环设计式精确逆 f=c/(4a)（一周长 C=4a≈λ0，2026-09-16
    v2 定版口径）。符号：da→f 降（−1）；loop_w/loop_gap 不进（0）。"""
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    er, h = _substrate("loop")
    return antenna2_resonance_ghz("loop", p, eps_eval_ghz=_f0("loop"),
                                  er=er, h_mm=h)


@_target("helix")
def _t_helix(p: dict[str, Any]) -> float:
    """y=总线长设计式精确逆 f=K_HELIX·c/(4·(4dN+Np))（k_helix=1.3615
    HFSS 仲裁单源）。符号：d/dN/dp 全部线性进 wire（弹性=各自份额
    <1）；helix_w/feed_gap 不进（0）。"""
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    er, h = _substrate("helix")
    return antenna2_resonance_ghz("helix", p, eps_eval_ghz=_f0("helix"),
                                  er=er, h_mm=h)


@_target("slot")
def _t_slot(p: dict[str, Any]) -> float:
    """y=Booker 对偶+半空间均值设计式精确逆 f=c/(2·L·√((1+εr)/2))
    （#190：k_slot 待仲裁不进设计式）。符号：dL→f 降（−1）；
    slot_w/feed_w/feed_margin 不进（0）。"""
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    er, h = _substrate("slot")
    return antenna2_resonance_ghz("slot", p, eps_eval_ghz=_f0("slot"),
                                  er=er, h_mm=h)


# ── 架构批 A3-D 扩批目标量（+25；专族内核/既有单源，符号语义见 docstring）──


def _stackup_params(template: str, p: dict[str, Any]):
    """模板参数自带的 (er, h_mm) Stackup（er/h 为名义参数的模板用），
    缺键回退 meta substrate（与 _substrate 同口径）。"""
    from rfauto.core.synthesis import Stackup

    er, h = _substrate(template)
    return Stackup(f"{template}_sens", float(p.get("er", er)),
                   float(p.get("h_mm", h)))


def forward_z0_eps(w_mm: float, f_ghz: float, stackup) -> float:
    """参数自带叠层的 HJ εeff（forward_z0 单源）。"""
    from rfauto.core.synthesis import forward_z0

    return float(forward_z0(w_mm, f_ghz, stackup)[1])


@_target("nway_wilkinson")
def _t_nway_wilkinson(p: dict[str, Any]) -> float:
    """y=臂 λ/4 谐振 f0=c/(4·arm_len·√εeff(w_arm))（XA-3 迭代序：臂线宽自身
    εeff，forward_media 单源；gysel 同式）。符号：darm_len→f0 降（−1）、
    dw_arm→εeff 升→f0 降（负小量）；w_feed/iso_r_ohm 不进臂谐振式（0）。"""
    from rfauto.core.synthesis import forward_media

    media = forward_media(p["w_arm_mm"], _f0("nway_wilkinson"), _stackup())
    return C_MM_GHZ / (4.0 * p["arm_len_mm"] * math.sqrt(media.er_eff))


@_target("branchline_2sect")
def _t_branchline_2sect(p: dict[str, Any]) -> float:
    """y=主线节 λ/4 谐振 f0=c/(4·sect_len·√εeff(w_main))（Pozar 经典点
    Z_a=Z0 主线节电长度 θ=90°；forward_media 单源）。符号：dsect_len→f0 降
    （−1）、dw_main→负小量；w_out/w_mid/w_feed/branch_len 不进主线谐振式
    （0——支臂跨度为外/中支臂 λ/4 均值的矩形拓扑二阶折衷，无单值闭式）。"""
    from rfauto.core.synthesis import forward_media

    media = forward_media(p["w_main_mm"], _f0("branchline_2sect"), _stackup())
    return C_MM_GHZ / (4.0 * p["sect_len_mm"] * math.sqrt(media.er_eff))


@_target("cline_coupler")
def _t_cline_coupler(p: dict[str, Any]) -> float:
    """y=耦合段 λ/4 谐振 f0=c/(4·L·√εeff_avg)，εeff_avg=(εe+εo)/2（KJ 偶/
    奇模填充因子，coupled_microstrip_even_odd_ohm 单源；§13.1 名义 λ/4
    @平均 εeff 同口径）。符号：dL→f0 降（−1）；dw/dgap 经偶/奇模填充进入。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    er, h = _substrate("cline_coupler")
    _ze, _zo, ee, eo = coupled_microstrip_even_odd_ohm(
        p["w_mm"], p["gap_mm"], _f0("cline_coupler"), er, h)
    return C_MM_GHZ / (4.0 * p["coupled_len_mm"] * math.sqrt(0.5 * (ee + eo)))


@_target("lange")
def _t_lange(p: dict[str, Any]) -> float:
    """y=指长 λ/4 谐振 f0=c/(4·finger_len·√εeff_avg)（相邻对 KJ 偶/奇模平均
    填充；§13.3 名义指长 λ/4 @平均 εeff=2.4972 同口径）。符号：
    dfinger_len→f0 降（−1）；dw/dgap 经 KJ 填充进入；w_feed 不进（0）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    er, h = _substrate("lange")
    _ze, _zo, ee, eo = coupled_microstrip_even_odd_ohm(
        p["w_mm"], p["gap_mm"], _f0("lange"), er, h)
    return C_MM_GHZ / (4.0 * p["finger_len_mm"] * math.sqrt(0.5 * (ee + eo)))


@_target("fgcpw")
def _t_fgcpw(p: dict[str, Any]) -> float:
    """y=Z0（FGCPW FD 准静态裁判链 fgcpw_fd 单源：Richardson 外推零厚准静态）。
    符号：dw→Z0 降、dgap→Z0 升、dgnd→Z0 微降（有限地回电流展宽，名义 ≤2% 带）、
    der→Z0 降；line_len/tan_d 不进 Z0 恒等式（0）。"""
    from rfauto.core.fgcpw import fgcpw_fd

    return float(fgcpw_fd(
        p["w_mm"], p["gap_mm"], p["h_mm"], p["er"],
        gnd_mm=p["gnd_mm"]).z0_ohm)


@_target("slotline")
def _t_slotline(p: dict[str, Any]) -> float:
    """y=Z0（Janaswamy–Schaubert 分段闭式 slotline_z0 单源；声明域 d/λ0≥0.006，
    名义 1.524mm@2.5GHz 落域内）。符号：dw→Z0 降、dh→Z0 升（缝下场约束减弱）、
    der→Z0 降；line_len/tan_d 不进（0）。"""
    from rfauto.core.slotline import slotline_z0

    return float(slotline_z0(
        p["w_mm"], p["h_mm"], p["er"], _f0("slotline")))


@_target("slotline_lumped")
def _t_slotline_lumped(p: dict[str, Any]) -> float:
    """y=Z0（同 slotline：JS 闭式 slotline_z0 单源；LumpedPort 路线 B 与
    WaveguidePort 路线 A 共享同一槽线闭式，r_port 缺省=本值）。符号语义同
    slotline；line_len/tan_d 不进（0）。"""
    from rfauto.core.slotline import slotline_z0

    return float(slotline_z0(
        p["w_mm"], p["h_mm"], p["er"], _f0("slotline_lumped")))


@_target("embedded_ms")
def _t_embedded_ms(p: dict[str, Any]) -> float:
    """y=Z0（嵌埋微带 FD 准静态 embedded_ms_quasistatic 单源，Richardson
    外推；h1=名义 h_mm）。符号：dw→Z0 降、dh2→Z0 降（覆盖层填充率升→εeff
    升）、der→Z0 降；line_len/tan_d 不进（0）。"""
    from rfauto.core.embedded_line import embedded_ms_quasistatic

    return float(embedded_ms_quasistatic(
        p["w_mm"], p["h_mm"], p["h2_mm"], p["er"]).z0_ohm)


@_target("inverted_ms")
def _t_inverted_ms(p: dict[str, Any]) -> float:
    """y=Z0（倒置微带 FD inverted_ms_fd 单源：空气隙高填充率）。符号：
    dw→Z0 降、dh_air→Z0 升（空气隙升→电容降）、der→Z0 降；line_len/
    h_mm（历史名义字段，目标式消费 h_sub_mm）/tan_d 不进（0）。"""
    from rfauto.core.inverted_ms import inverted_ms_fd

    return float(inverted_ms_fd(
        p["w_mm"], p["h_air_mm"], p["h_sub_mm"], p["er"]).z0_ohm)


@_target("isl_shielded")
def _t_isl_shielded(p: dict[str, Any]) -> float:
    """y=Z0（ISL 悬置准静态 suspended_ms_qs 单源；er 取名义参数、h_sub 取
    meta substrate——名义参数面无 h_sub 键）。符号：dw→Z0 降、dg_air→Z0 升
    （空气份额升）、dh_top→Z0 升（腔电容摊薄）、der→Z0 降；d/s（过孔
    藩篱）/line_len/tan_d 不进准静态 Z0（0）。"""
    from rfauto.core.isl_line import suspended_ms_qs

    _er_sub, h_sub = _substrate("isl_shielded")
    return float(suspended_ms_qs(
        p["w_mm"], p["g_air_mm"], h_sub, float(p["er"]),
        p["h_top_mm"])["z0_ohm"])


@_target("sicl")
def _t_sicl(p: dict[str, Any]) -> float:
    """y=Z0（SICL 矩形同轴共形闭式 sicl_z0 单源，k=tanh(πa/2b)·sech(πw/2b)，
    b=名义 h_mm 双板腔高）。符号：dw→Z0 降、da→Z0 升、dh→Z0 降（腔高电容
    增）、der→Z0 降；d/s（过孔墙）/line_len/tan_d 不进（0）。"""
    from rfauto.core.sicl_line import sicl_z0

    return float(sicl_z0(
        p["w_mm"], p["a_mm"], p["h_mm"], t_mm=0.0, eps_r=p["er"]))


@_target("coil_nfc")
def _t_coil_nfc(p: dict[str, Any]) -> float:
    """y=L（Mohan 电流片式平面螺旋电感 spiral_inductance 单源，µH 级；
    名义 2.9310µH 回代相对差 1.4e-16）。符号：dn_turns→L 升（n² 通道，
    整数 ±1 单位步）、dd_out→L 升（平均直径主项）、dw/ds→L 变（填充/
    间距修正项）；gap/h/er/tan_d 不进电感式（0——谐振频率由外匹配电容
    联动，47pF 不进几何）。"""
    from rfauto.core.nfc_coil import CoilGeometry, spiral_inductance

    geom = CoilGeometry(
        "square", float(p["n_turns"]), p["d_out_mm"] * 1e-3,
        p["w_mm"] * 1e-3, p["s_mm"] * 1e-3)
    return float(spiral_inductance(geom)) * 1e6


@_target("ms_patch")
def _t_ms_patch(p: dict[str, Any]) -> float:
    """y=单元谐振 f0=c/(2·px·√εeff(px))（Balanis 腔模型方贴片、HJ εeff
    @w=边长——ms_patch_resonant_len_mm 不动点式的精确逆，metasurface_lut
    同口径）。符号：dpx/dpy→f0 降（−1 族）、der 经 εeff 负小量；
    period（阵格 λ0/2 无光栅瓣口径）/h/tan_d 不进谐振式（h 经 εeff 弱进入，
    计入 der 通道）。"""
    ee = forward_z0_eps(p["px_mm"], _f0("ms_patch"),
                        _stackup_params("ms_patch", p))
    return C_MM_GHZ / (2.0 * p["px_mm"] * math.sqrt(ee))


@_target("ms_ring_patch")
def _t_ms_ring_patch(p: dict[str, Any]) -> float:
    """y=内贴片谐振 f0=c/(2·patch_px·√εeff(patch_px))（复用 ms_patch 口径；
    环/槽环境第二谐振为双谐振宽摆幅机理，不入单点目标）。符号语义同
    ms_patch；period/h/tan_d 同前（0/弱通道）。"""
    ee = forward_z0_eps(p["patch_px_mm"], _f0("ms_ring_patch"),
                        _stackup_params("ms_ring_patch", p))
    return C_MM_GHZ / (2.0 * p["patch_px_mm"] * math.sqrt(ee))


@_target("ms_cross")
def _t_ms_cross(p: dict[str, Any]) -> float:
    """y=单元谐振 f0=c/(2·(2·arm_len)·√((1+εr)/2))（十字臂总跨=λ0/(2√εeff)、
    单侧基板加载 εeff=(1+εr)/2（Luukkonen eq.3），meta nominal_derivation
    同式）。符号：darm_len→f0 降（−1）、der→负 1/2 通道；arm_w/period/h/
    tan_d 不进（0——arm_w=总跨/10 为派生版图常量）。"""
    ee = 0.5 * (1.0 + float(p["er"]))
    return C_MM_GHZ / (2.0 * (2.0 * p["arm_len_mm"]) * math.sqrt(ee))


@_target("ms_jcross")
def _t_ms_jcross(p: dict[str, Any]) -> float:
    """y=主缝谐振 f0=c/(4·slot_len·√((1+εr)/2))（主缝=λg/4、εeff=(1+εr)/2
    同 ms_cross；Marcuvitz 网格 EC 初值口径，meta nominal_derivation 同式）。
    符号：dslot_len→f0 降（−1）、der→负 1/2 通道；slot_w/stub_len/period/
    h/tan_d 不进（0——端枝 λg/8 为派生电长度）。"""
    ee = 0.5 * (1.0 + float(p["er"]))
    return C_MM_GHZ / (4.0 * p["slot_len_mm"] * math.sqrt(ee))


@_target("ms_mushroom")
def _t_ms_mushroom(p: dict[str, Any]) -> float:
    """y=AMC 谐振 f=1/(2π√(L·C))（Sievenpiper LC 模型：L=μ0·h
    amc_via_inductance_h 单源、C=Luukkonen eq.4 amc_gap_capacitance_f
    （εeff=(1+εr)/2）、amc_resonance_hz 单源；单位 mm→m 换算）。
    符号：dgap→f 降（C 通道，ln csc 律）、dh→f 升（L 通道）、der→f 降；
    period（进入 C 的 2D/π 因子，非零弱通道）/tan_d 不进谐振式
    （tan_d 无定义=0）。"""
    from rfauto.core.amc_mushroom import (
        amc_gap_capacitance_f,
        amc_resonance_hz,
        amc_via_inductance_h,
    )

    l_via = float(amc_via_inductance_h(p["h_mm"] * 1e-3))
    c_gap = float(amc_gap_capacitance_f(
        p["period_mm"] * 1e-3, p["gap_mm"] * 1e-3,
        0.5 * (1.0 + float(p["er"]))))
    return float(amc_resonance_hz(l_via, c_gap)) / 1e9


@_target("siw")
def _t_siw(p: dict[str, Any]) -> float:
    """y=TE10 截止 fc=c/(2·w_eff·√εr)，w_eff=w−d²/(0.95·s)（Cassivi 2002
    过孔藩篱等效腔宽反解式的正向；synthesize_siw_model 与 meta
    nominal_derivation 同源：w=12.1317 → w_eff=11.7528 → fc=6.6667）。
    符号：dw→fc 降（−1）、dd/ds→fc 升/降（w_eff 修正项通道）、der→负 1/2；
    line_len/h/tan_d 不进截止式（0）。"""
    w_eff = float(p["w_mm"]) - float(p["d_mm"]) ** 2 / (0.95 * float(p["s_mm"]))
    return C_MM_GHZ / (2.0 * w_eff * math.sqrt(float(p["er"])))


@_target("hmsiw")
def _t_hmsiw(p: dict[str, Any]) -> float:
    """y=准 TE0.5 截止 fc（Lai-Fumeaux 2009 式 (8)-(14) 链 hmsiw_closed_form
    单源：w_eff_siw→半宽修正→fc_te05）。符号：dw→fc 降（−1 族）、dd/ds→
    过孔修正通道、der→负 1/2；line_len/tan_d 不进（0）。"""
    from rfauto.core.hmsiw import hmsiw_closed_form

    out = hmsiw_closed_form(
        p["w_mm"], p["h_mm"], p["er"], p["d_mm"], p["s_mm"])
    return float(out["fc_te05_ghz"])


@_target("vivaldi_tsa")
def _t_vivaldi_tsa(p: dict[str, Any]) -> float:
    """y=低截止 f_low=c/(2·w_mouth)（口面半波准则 vivaldi_low_cutoff_ghz
    单源；空气侧准则不依赖 εr——二手工程准则近似级别如实）。符号：
    dw_mouth→f_low 降（−1）；w_throat/l/feed_w/er/tan_d 不进口面准则（0）。"""
    from rfauto.core.vivaldi_tsa import vivaldi_low_cutoff_ghz

    return float(vivaldi_low_cutoff_ghz(p["w_mouth_mm"]))


@_target("marchand_balun")
def _t_marchand_balun(p: dict[str, Any]) -> float:
    """y=槽臂 Z0（Janaswamy–Schaubert slotline_z0 单源 @槽宽 w_slot；双槽臂
    Marchand 耦合段的槽线本体口径——设计级两节综合见
    core/slotline_transitions.synthesize_marchand_two_section，本目标取槽臂
    单点闭式）。符号：dw_slot→Z0 降、dh→Z0 升、der→Z0 降；x_port/tan_d
    不进（0）。"""
    from rfauto.core.slotline import slotline_z0

    return float(slotline_z0(
        p["w_slot_mm"], p["h_mm"], p["er"], float(p["f0_ghz"])))


@_target("msl_slot_transition")
def _t_msl_slot_transition(p: dict[str, Any]) -> float:
    """y=槽线臂 Z0（slotline_z0 单源 @w_slot；Roberts/Knorr 过渡的槽线段
    本体口径，λg'/4 短路臂设计依赖此值）。符号语义同 marchand_balun；
    x_port/tan_d 不进（0）。"""
    from rfauto.core.slotline import slotline_z0

    return float(slotline_z0(
        p["w_slot_mm"], p["h_mm"], p["er"], float(p["f0_ghz"])))


# ── 架构批 R8-KN 扩批目标量（+4；段参数/内核相位单点闭式，与 A3-D 批
#    marchand_balun/msl_slot_transition「过渡族取段自身线参数」先例同类）──


@_target("diplexer")
def _t_diplexer(p: dict[str, Any]) -> float:
    """y=交越（截止）fc_GHz=Z0/(2π·L_lpf_nH)（一阶常阻互补对偶 CR 臂定标
    L=Z0/ωc，core/diplexer_compose.diplexer_lpf_hpf element_values 单源；
    交越锁定 fc 三锚闭式精确，名义回代 fc=2.5000/2.5001 GHz 双通道同点）。
    符号：dl_lpf→fc 降（反比恒等式，弹性=1）；c_hpf 为 CR 对偶
    C=L/Z0² 锁定同一 ωc（非独立维，0——HPF 臂通道与 L 臂完全相关）；
    w_feed 不进截止式（0，Z0=50 系统参考阻抗为设计常量非 w_feed 函数）。"""
    return 50.0 / (2.0 * math.pi * float(p["l_lpf_nh"]))


@_target("schiffman")
def _t_schiffman(p: dict[str, Any]) -> float:
    """y=差分相移 Δφ(f0)（度）（core/synthesis.schiffman_delta_phase 单源：
    Δφ=β_ref·L_ref−Φ_c；εeff_e/o 成对显式旁路取 KJ 偶/奇模正演
    coupled_microstrip_even_odd_ohm 单源——synthesize_schiffman 合成链
    同口径，名义回代 Δφ(f0)=90.0°）。符号：dl_ref→Δφ 升（β_ref·L_ref
    =Φ_c(f0)+90° 通道，主控）、dl_coupled→Φ_c 通道（耦合段 ABCD 插入
    相位对 l 非线性，无解析常值——不钉手推幅值）、dw/dgap 经 KJ
    εeff_e/o 进入；w_ref 不进相位式（0——内核 v1 参考段 εeff 取偶/奇模
    相速平均口径，显式非按 w_ref 独立取 HJ）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm
    from rfauto.core.synthesis import schiffman_delta_phase

    er, h = _substrate("schiffman")
    f0 = _f0("schiffman")
    ze, zo, ee, eo = coupled_microstrip_even_odd_ohm(
        p["w_mm"], p["gap_mm"], f0, er, h)
    return float(schiffman_delta_phase(
        f0, p["l_coupled_mm"] * 1e-3, ze, zo, er, h * 1e-3,
        l_reference_m=p["l_ref_mm"] * 1e-3,
        eps_eff_even=ee, eps_eff_odd=eo)[0])


@_target("msl_siw_taper")
def _t_msl_siw_taper(p: dict[str, Any]) -> float:
    """y=SIW 段 TE10 截止 fc=c/(2·w_eff·√εr)，w_eff=w−d²/(0.95·s)
    （Cassivi 2002 正向；_t_siw 同式同链——meta nominal_derivation 自证
    w/d/s=TEMPLATE_NOMINAL["siw"] 同源沿用、fc10=6.6667GHz=f0/1.5 设计点，
    名义回代 6.6667 逐位一致）。符号：dw→fc 降（w/w_eff 通道，siw 同值
    1.0322）、dd/ds→w_eff 修正通道、der→−1/2；taper_len/siw_len（传输
    段长，不进截止式）/h/tan_d 不进（0——渐变匹配/λg 口径留教学面，
    两源口径不同不混写）。"""
    w_eff = float(p["w_mm"]) - float(p["d_mm"]) ** 2 / (0.95 * float(p["s_mm"]))
    return C_MM_GHZ / (2.0 * w_eff * math.sqrt(float(p["er"])))


@_target("msl_cpw")
def _t_msl_cpw(p: dict[str, Any]) -> float:
    """y=CPWG 段 Z0（core/calc_families/rf_line._cpwg_ri 准静态共形映射
    单源——meta nominal_derivation 同链：w_cpw=brentq(_cpwg_ri, 50) 反解，
    名义回代 Z0=50.000）。符号：dw_cpw→Z0 降、dgap_cpw→Z0 升、der/dh
    （substrate）经接地介质板映射进入；w_msl（微带段独立 50Ω HJ 反解维）/
    line_len/trans_len/r_via/via_spacing/via_offset（渐变与缝合版图量）
    不进 CPWG Z0 恒等式（0）。"""
    from rfauto.core.calc_families.rf_line import _cpwg_ri

    er, h = _substrate("msl_cpw")
    return float(_cpwg_ri(p["w_cpw_mm"], p["gap_cpw_mm"], h, er)[1])


@_target("varactor_bpf")
def _t_varactor_bpf(p: dict[str, Any]) -> float:
    """y=装载臂谐振 f0（varactor_bpf_design 主谐振方程正解单源：
    C=突变结 C(bias)=cj0·(1+V/φ)^−1/2 → varactor_line_f0_ghz(C, arm_len,
    50, εeff)，εeff=forward_z0(w @f_unloaded=2.8GHz 设计缺省、bare Stackup
    同设计链)；名义回代 f0=2.499997（bias/arm 4 位舍入传播带内）。符号：
    darm_len→f0 降、dcj0_pf/dbias_v/dphi_v→C 通道→f0 降、dw_mm→εeff 升→
    f0 降；order/arm_gap_mm/gap_mm/tap_frac 不进装载谐振式（0——耦合缝/
    抽头属 C13+loaded 廓线链非谐振式）。渲染端 C_literal=C(V)−C_geo 盒寄生
    修正属物理件口径，不进本设计链目标。"""
    from rfauto.core.synthesis import Stackup, forward_z0
    from rfauto.core.varactor import (
        abrupt_junction_capacitance_pf,
        varactor_line_f0_ghz,
    )

    er, h = _substrate("varactor_bpf")
    stackup = Stackup("varactor_bpf_sens", float(er), float(h))
    _, ereff = forward_z0(float(p["w_mm"]), 2.8, stackup)
    c_bias = abrupt_junction_capacitance_pf(
        float(p["bias_v"]), float(p["cj0_pf"]), float(p["phi_v"]))
    return float(varactor_line_f0_ghz(
        c_bias, float(p["arm_len_mm"]), 50.0, ereff))


@_target("xcheb_bpf4")
def _t_xcheb_bpf4(p: dict[str, Any]) -> float:
    """y=开路环谐振 f0=c/(2·(4·a+2Δl)·√εeff(w))（cross_coupled_bpf_design
    周长恒等式正向：周长=λg/2−2Δl（双开路端边缘延伸）、a=周长/4、
    Δl=patch_fringing_delta_l；εeff=HJ @w（参数自带 er/h Stackup））；
    名义回代 f0=2.499993（a 4 位舍入传播带内）。符号：da_mm→f0 降（≈−1）、
    dw_mm/der/dh_mm 经 εeff 与 Δl 双通道进入（负小量）；g12/g23/g34/g14
    （主线/交叉耦合缝）与 g_open/g_pos/tap_t/tan_d 不进环谐振式（0——
    耦合缝属 C13+χ·KJ 链、抽头属版图量）。"""
    from rfauto.core.synthesis import patch_fringing_delta_l

    h = float(p.get("h_mm", _substrate("xcheb_bpf4")[1]))
    ee = forward_z0_eps(float(p["w_mm"]), _f0("xcheb_bpf4"),
                        _stackup_params("xcheb_bpf4", p))
    dl = patch_fringing_delta_l(float(p["w_mm"]) * 1e-3, h * 1e-3, ee) * 1e3
    perimeter = 4.0 * float(p["a_mm"]) + 2.0 * dl
    return C_MM_GHZ / (2.0 * perimeter * math.sqrt(ee))


# ── 架构批 W4-S19 全覆盖批目标量（+24；teaching 9 全入表 + 15 补族；
#    列表参数=整体 ±1% 等比缩放，零值参数走 NON_PERTURBABLE=0 分声明）────


def _hairpin_f0_corr() -> float:
    """hairpin 真机谐振修正 c_f0（fake_adapter 单源，K_HELIX 同性质常数）。"""
    from rfauto.adapters.fake_adapter import _HAIRPIN_F0_CORR

    return float(_HAIRPIN_F0_CORR)


@_target("wilkinson")
def _t_wilkinson(p: dict[str, Any]) -> float:
    """y=臂 λ/4 谐振 f0=c/(4·arm_len·√εeff(series_w))（XA-3 迭代序：臂线宽
    自身 εeff，forward_media 单源；gysel/nway 同式——synthesize_wilkinson
    综合链精确逆）。符号：darm_len→f0 降（−1）、dseries_w→εeff 升→f0 降
    （负小量）；shunt_w（50Ω 馈线宽）不进臂谐振式（0）。名义回代
    2.5062（+0.25%，round4 名义档带内）。"""
    from rfauto.core.synthesis import forward_media

    media = forward_media(p["series_w_mm"], _f0("wilkinson"), _stackup())
    return C_MM_GHZ / (4.0 * p["arm_len_mm"] * math.sqrt(media.er_eff))


@_target("branchline")
def _t_branchline(p: dict[str, Any]) -> float:
    """y=串联臂 λ/4 谐振 f0=c/(4·arm_len·√εeff(series_w))（XA-3 迭代序 HJ
    口径，synthesize_branchline 综合链同源；并臂 Z0 同构恒等式取串联臂
    代表）。符号：darm_len→f0 降（−1）、dseries_w→负小量；shunt_w 不进
    串联臂谐振式（0）。名义回代 2.1158（arm_len 名义系 #252 诊断的
    (εr+1)/2 薄线极限捷径遗留档，meta 2.4——恒等式本身 HJ 单源）。"""
    from rfauto.core.synthesis import forward_media

    media = forward_media(p["series_w_mm"], _f0("branchline"), _stackup())
    return C_MM_GHZ / (4.0 * p["arm_len_mm"] * math.sqrt(media.er_eff))


@_target("cpw")
def _t_cpw(p: dict[str, Any]) -> float:
    """y=CPWG 段 Z0（底接地共形映射 _cpwg_ri 单源——synthesize_cpw_model
    #193 同口径参照系）。符号：dw→Z0 降、dgap→Z0 升、der/dh（substrate）
    经接地介质板映射进入；line_len 不进 Z0 恒等式（0）。名义回代
    Z0=50.000（mline/cpw 名义 round4 带内）。"""
    from rfauto.core.calc_families.rf_line import _cpwg_ri

    er, h = _substrate("cpw")
    return float(_cpwg_ri(p["w_mm"], p["gap_mm"], h, er)[1])


@_target("mline")
def _t_mline(p: dict[str, Any]) -> float:
    """y=微带 Z0（skrf HJ 正向 forward_z0 单源——XC-W 唯一线宽计算源）。
    符号：dw→Z0 降（HJ 域弹性 ~0.6）、der/dh（substrate）正向通道；
    line_len 不进 Z0 恒等式（0）。名义回代 Z0=49.963（round4 带内）。"""
    return float(_z0_of(p["w_mm"], _f0("mline"))[0])


@_target("dipole")
def _t_dipole(p: dict[str, Any]) -> float:
    """y=半波振子设计式精确逆 f=c/(2·L)（自由空间 λ/2 闭式，
    synthesize_dipole_model 同式）。符号：dL→f 降（−1）；
    dipole_w/gap 不进 λ/2 恒等式（0）。名义回代 2.5844（58mm 系 #194
    冒烟板遗留名义档，meta 2.4——恒等式本身精确）。"""
    return C_MM_GHZ / (2.0 * float(p["dipole_len_mm"]))


@_target("hairpin")
def _t_hairpin(p: dict[str, Any]) -> float:
    """y=臂 λg/2 谐振×真机修正 f0=c_f0·c/(2·arm_len·√εeff(w))
    （hairpin_arm_len_mm 的精确逆×_HAIRPIN_F0_CORR=1.0370——B2 pt4 真机
    标定常数单源，fake 裁判谐振式同链；U 弯+开路端等效缩短 +3.7%）。
    符号：darm_len→f0 降（−1）、dw→εeff 通道；order/arm_gap/gap/tap_frac
    不进单臂谐振式（0——耦合缝/抽头属 C13+KJ 链）。名义回代 2.502
    （+0.1% round4 带内）。"""
    eps = _eps_eff_of(p["w_mm"], _f0("hairpin"))
    return _hairpin_f0_corr() * C_MM_GHZ / (
        2.0 * p["arm_len_mm"] * math.sqrt(eps))


@_target("hairpin_alt")
def _t_hairpin_alt(p: dict[str, Any]) -> float:
    """y=臂 λg/2 谐振×真机修正（同 hairpin：c_f0·c/(2·arm·√εeff)；alt
    与 v1 共享同一臂谐振恒等式与 c_f0 常数——SENS-ANC「非稳定闭式」留缺
    判定按 #222 树面复核勘误：c_f0=1.0370 已是真机标定单源常数）。
    符号语义同 hairpin。名义回代 2.502（+0.1% 带内）。"""
    eps = _eps_eff_of(p["w_mm"], _f0("hairpin_alt"))
    return _hairpin_f0_corr() * C_MM_GHZ / (
        2.0 * p["arm_len_mm"] * math.sqrt(eps))


@_target("patch")
def _t_patch(p: dict[str, Any]) -> float:
    """y=贴片腔模谐振 f0=c/(2·(L+2ΔL)·√εeff(W))（synthesize_patch 设计式
    L=c/(2f0√εeff)−2ΔL 的精确逆；ΔL=patch_fringing_delta_l、εeff=HJ，
    弱色散 @meta f0 取值）。符号：dL→f0 降（<1，ΔL 稀释）、dW 经
    εeff+ΔL 双通道、der/dh（substrate）经 εeff；feed_offset 不进谐振式
    （0——馈点属阻抗匹配面）。名义回代 2.240（名义 (34.9/50) 系注册期
    设计点，现行 synthesize_patch 缺省设计点 32.08/40.92——恒等式同链）。"""
    er, h = _substrate("patch")
    from rfauto.core.synthesis import Stackup, forward_z0, patch_fringing_delta_l

    f0m = _f0("patch")
    _z, eps = forward_z0(float(p["patch_w_mm"]), f0m,
                         Stackup("patch_sens", float(er), float(h)))
    dl = patch_fringing_delta_l(
        float(p["patch_w_mm"]) * 1e-3, float(h) * 1e-3, float(eps)) * 1e3
    return C_MM_GHZ / (2.0 * (float(p["patch_len_mm"]) + 2.0 * dl)
                       * math.sqrt(float(eps)))


@_target("ratrace")
def _t_ratrace(p: dict[str, Any]) -> float:
    """y=环谐振 f0=1.5·c/(2π·r_ring·√εeff(w_ring))（synthesize_ratrace
    周长恒等式 C=1.5λg、R=C/(2π) 的精确逆；环线宽自身 εeff）。
    符号：dr_ring→f0 降（−1）、dw_ring→负小量；w_feed 不进环谐振式
    （0）。名义回代 2.4976（round4 带内）。"""
    eps = _eps_eff_of(p["w_ring_mm"], _f0("ratrace"))
    return 1.5 * C_MM_GHZ / (2.0 * math.pi * float(p["r_ring_mm"])
                             * math.sqrt(eps))


@_target("pyramid_horn")
def _t_pyramid_horn(p: dict[str, Any]) -> float:
    """y=喇叭增益线性 G=(4π/λ²)·A·B·e（Orfanidis (21.4.2)/(21.4.3)，
    horn_gain_direct 单源正算 @meta f0=10GHz——综合目标 15dB 恒等）。
    符号：da1/db1（口径）主通道、da/db 经 σa=a1/a/σb=b1/b 进效率 e、
    dl_flare 经几何 σ 关系；l_feed 不进增益式（0）；er 可扰动但内核
    空气填充口径不消费（0）；h_mm 零值不可扰动（NON_PERTURBABLE=0 分）。
    名义回代 G=31.6228（15.000dB 逐位）。"""
    from rfauto.core.horn_synthesis import horn_gain_direct

    out = horn_gain_direct(
        float(p["a_mm"]), float(p["b_mm"]), float(p["a1_mm"]),
        float(p["b1_mm"]), float(p["l_flare_mm"]), _f0("pyramid_horn"))
    return float(out["gain_linear"])


@_target("coax_waveguide_transition")
def _t_coax_waveguide_transition(p: dict[str, Any]) -> float:
    """y=波导段 TE10 截止 fc10=c0/(2·a·√εr)（meta nominal_derivation 同式：
    fc10=c0/2a=6.557140GHz 审计钉；er 名义 1.0 空气，扰动展示介质通道）。
    符号：da→fc 降（−1）、der→−1/2；l_wg/wg_t/pin_*/port_h/backshort
    （探针/背短路段版图量）不进截止式（0）；h_mm 零值
    （NON_PERTURBABLE=0 分）。名义回代 6.5571 逐位。"""
    return C_MM_GHZ / (2.0 * float(p["a_mm"])
                       * math.sqrt(float(p["er"])))


@_target("ridged_wg")
def _t_ridged_wg(p: dict[str, Any]) -> float:
    """y=脊波导 TE10 主模截止 fc=c0·k_c/(2π)（core/ridged_waveguide.
    cutoff_kc 单源：谐振函数 tan(k·s/2)·tan(k·l_side)=R 二分求根——
    ridged_wg_design_params 反解链正向，名义回代 fc=4.99998GHz 逐位）。
    符号：da/db/ds/dd 经横截面谐振条件进入（dd→fc 降主通道）；l_ridge/
    l_feed 不进截止式（0）；er 空气填充口径不消费（0）；h_mm 零值
    （NON_PERTURBABLE=0 分）。"""
    from rfauto.core.ridged_waveguide import RidgedWaveguide, cutoff_kc

    wg = RidgedWaveguide(
        float(p["a_mm"]) * 1e-3, float(p["b_mm"]) * 1e-3,
        float(p["s_mm"]) * 1e-3, float(p["d_mm"]) * 1e-3, double=False)
    return 299792458.0 * float(cutoff_kc(wg)) / (2.0 * math.pi) / 1e9


@_target("sma_launcher")
def _t_sma_launcher(p: dict[str, Any]) -> float:
    """y=同轴段 Z=(60/√εr_fill)·ln(r_o/r_i)（反焊盘同轴口径同式——
    via 族设计规则；名义回代 Z=50.014 逐位口径）。符号：dr_o/dr_i 对数
    比值通道（弹性=1/ln(r_o/r_i)≈4.81 同向）、der_fill→−1/2；
    w_msl（微带段独立维）/shell_*/pin_lay/line_len/port_len 不进同轴
    恒等式（0）；tan_d_fill 零值（NON_PERTURBABLE=0 分）。"""
    return 60.0 / math.sqrt(float(p["er_fill"])) * math.log(
        float(p["r_o_mm"]) / float(p["r_i_mm"]))


@_target("ring_resonator")
def _t_ring_resonator(p: dict[str, Any]) -> float:
    """y=环基模谐振 f0=c/(2π·r_mean·√εeff(w))（闭环周长=λg 恒等式，
    meta nominal_derivation/test_ring_resonator_template 同式——W8 回退卡
    字节钉前提按本批任务书解除，钉测试同批重生成）。符号：dr_mean→f0 降
    （−1）、dw→εeff 通道；gap/feed_w 不进环谐振式（0）。名义回代 2.4976
    （round4 带内；W6 回退卡面升级为 computed 同批）。"""
    eps = _eps_eff_of(p["w_mm"], _f0("ring_resonator"))
    return C_MM_GHZ / (2.0 * math.pi * float(p["r_mean_mm"]) * math.sqrt(eps))


@_target("qwt_multisection")
def _t_qwt_multisection(p: dict[str, Any]) -> float:
    """y=首节 λ/4 谐振 f0=c/(4·L_1·√εeff(w_1))（synthesize_multisection_
    quarter_wave 各节 λ/4 恒等式取首节代表——各节同构恒等式逐一在档，
    branchline_2sect 主线节先例同类；widths_mm/lengths_mm 列表按整体
    ±1% 等比缩放扰动，首元弹性=整表同缩口径）。符号：dlengths→f0 降
    （−1）、dwidths→εeff 负小量；feed_w 不进节谐振式（0）、z_load 不进
    谐振式（0——变换比属阻抗面）。名义回代 2.4976（round4 带内）。"""
    eps = _eps_eff_of(float(p["widths_mm"][0]), _f0("qwt_multisection"))
    return C_MM_GHZ / (4.0 * float(p["lengths_mm"][0]) * math.sqrt(eps))


@_target("coupled_bpf")
def _t_coupled_bpf(p: dict[str, Any]) -> float:
    """y=谐振器 λ/2 谐振 f0=c/(2·(res_len+Δl_end+Δl_mid)·√εeff_gm)
    （coupled_bpf_design_from_order 同链精确逆：εeff_gm=全节 KJ 偶/奇模
    平均 εeff 的均值、Δl=开路端修正 @端/中节宽；widths_mm/gaps_mm 列表
    整体 ±1% 等比缩放）。符号：dres_len→f0 降（≈−1 族）、dwidths/dgaps
    经 εeff_gm+Δl 通道；order/w_feed/feed_len 不进谐振式（0）。名义回代
    2.4997（res_len 名义=现行链 round4 逐位）。"""
    from rfauto.adapters.oe_templates.render_c3 import _open_end_delta_mm
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    er, h = _substrate("coupled_bpf")
    f0m = _f0("coupled_bpf")
    widths = [float(v) for v in p["widths_mm"]]
    gaps = [float(v) for v in p["gaps_mm"]]
    aves = []
    for w_i, g_i in zip(widths, gaps, strict=True):
        _ze, _zo, e_e, e_o = coupled_microstrip_even_odd_ohm(
            w_i, g_i, f0m, er, h)
        aves.append(0.5 * (e_e + e_o))
    ere_gm = sum(aves) / len(aves)
    dl_e = _open_end_delta_mm(widths[0], f0m, er, h)
    dl_m = _open_end_delta_mm(widths[1], f0m, er, h)
    return C_MM_GHZ / (2.0 * (float(p["res_len_mm"]) + dl_e + dl_m)
                       * math.sqrt(ere_gm))


@_target("combline")
def _t_combline(p: dict[str, Any]) -> float:
    """y=梳状谐振器谐振 f0（render_c3.combline_design_from_order 谐振条件
    cot θr=ω0·C·Z_r 与 θr=ω0·res_len·√εeff/c 联立的唯一正根，εeff/Z_r
    弱色散 @meta f0 固定、brentq 型二分求根；C 装载电容缩短恒等式单源）。
    符号：dres_len→f0 降（反比主通道）、dc_load→f0 降（装载越强谐振越
    高的电长度通道）、dw→εeff/Z_r 通道；order/gaps/feed_len 不进单棒
    谐振式（0）。名义回代 2.63（res_len 名义早于现行 Δl 口径档，C 名义
    round4 逐位）。"""
    from rfauto.adapters.oe_templates.render_c3 import _c3_single_line

    er, h = _substrate("combline")
    f0m = _f0("combline")
    z_r, ere = _c3_single_line(float(p["w_mm"]), f0m, er, h)
    c_f = float(p["c_load_pf"]) * 1e-12
    res_len = float(p["res_len_mm"])

    def _g(f_ghz: float) -> float:
        theta = 2.0 * math.pi * f_ghz * res_len * math.sqrt(ere) / C_MM_GHZ
        return (1.0 / math.tan(theta)
                - 2.0 * math.pi * f_ghz * 1e9 * c_f * z_r)

    return _bisect_root(_g, 0.3, 0.9 * C_MM_GHZ
                        / (4.0 * res_len * math.sqrt(ere)))


def _bisect_root(fn: Callable[[float], float], lo: float, hi: float,
                 iters: int = 200) -> float:
    """确定性二分求根（目标量级联专用；fn 必须在 (lo,hi) 恰一变号根）。"""
    f_lo, f_hi = fn(lo), fn(hi)
    if not (f_lo * f_hi < 0.0):
        raise ValueError(f"二分括号无变号根：f({lo})={f_lo}, f({hi})={f_hi}")
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        f_mid = fn(mid)
        if f_lo * f_mid <= 0.0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


@_target("interdigital")
def _t_interdigital(p: dict[str, Any]) -> float:
    """y=交指棒 λ/4 谐振 f0=c/(4·(res_len+Δl)·√εeff(w))（render_c3.
    interdigital_design_from_order 同式精确逆：λ/4 短路棒电长−开路端 Δl，
    棒=50Ω 单线 HJ）。符号：dres_len→f0 降（≈−1 族）、dw 经 εeff+Δl
    通道；order/gaps/feed_len 不进单棒谐振式（0）。名义回代 2.564
    （res_len 名义早于现行 Δl 口径档，gaps 名义现行链 round4 逐位）。"""
    from rfauto.adapters.oe_templates.render_c3 import (
        _c3_single_line,
        _open_end_delta_mm,
    )

    er, h = _substrate("interdigital")
    f0m = _f0("interdigital")
    _z_r, ere = _c3_single_line(float(p["w_mm"]), f0m, er, h)
    dl = _open_end_delta_mm(float(p["w_mm"]), f0m, er, h)
    return C_MM_GHZ / (4.0 * (float(p["res_len_mm"]) + dl) * math.sqrt(ere))


@_target("sir_bpf")
def _t_sir_bpf(p: dict[str, Any]) -> float:
    """y=SIR 基模谐振 f0（tanθ1·tanθ2=Z_lo/Z_hi 对称恒等式回代：Z/εeff 弱
    色散 @meta f0 固定 HJ 回读、低阻段开路端 Δl 等效长度、接地端高阻段无
    Δl、二分求根——render_c3.sir_bpf_design_from_order 同一恒等式的数值
    逆）。符号：dl_low/dl_high→f0 降（两段电长度主通道，对称分θ 各半 <1）、
    dw_low→Z_lo 恒等式分子+εeff 双通道同向降、dw_high→Z_hi 分母通道升/
    εeff 通道降（双通道对冲，净号按实测弹性）；dw_feed/dgaps/dfeed_len/
    order 不进单棒谐振恒等式（0）。名义回代 2.5000（架构批 W6-S4 名义
    重注册 l_high=7.1055 理想短路口径后 4 位舍入带内，第 71 族解锁）。"""
    from rfauto.adapters.oe_templates.render_c3 import (
        _c3_single_line,
        _open_end_delta_mm,
    )

    er, h = _substrate("sir_bpf")
    f0m = _f0("sir_bpf")
    z_lo, ere_lo = _c3_single_line(float(p["w_low_mm"]), f0m, er, h)
    z_hi, ere_hi = _c3_single_line(float(p["w_high_mm"]), f0m, er, h)
    dl = _open_end_delta_mm(float(p["w_low_mm"]), f0m, er, h)
    l_lo = float(p["l_low_mm"]) + dl
    l_hi = float(p["l_high_mm"])
    ratio = z_lo / z_hi

    def _g(f_ghz: float) -> float:
        t1 = math.tan(2.0 * math.pi * f_ghz * l_lo * math.sqrt(ere_lo)
                      / C_MM_GHZ)
        t2 = math.tan(2.0 * math.pi * f_ghz * l_hi * math.sqrt(ere_hi)
                      / C_MM_GHZ)
        return t1 * t2 - ratio

    # 括号内恰一变号根：g 单调升直到首极点（θ1/θ2 触 π/2 在 >6GHz 档），
    # g(0.05)≈−ratio<0、g(6.0)>0（名义回代 2.5 邻域 ±1% 扰动恒在括号内）
    return _bisect_root(_g, 0.05, 6.0)


@_target("patch_array_1x4")
def _t_patch_array_1x4(p: dict[str, Any]) -> float:
    """y=单元谐振（array_resonance_ghz 精确逆：Balanis Ch.14 传输线模型
    f0=c/(2(L+2ΔL)√εeff(W))，准静态 εeff/ΔL 无频率项故逆式闭合；C2 三
    模板单元同型、互联/馈电变换树不改一阶谐振——ms_ring_patch 单元级
    口径先例同类）。符号：delem_len→f0 降（<1，ΔL 稀释）、delem_w 经
    εeff+ΔL 通道；elem_feed/spacing/feed_w/q_w/q_len（阵列版图量）不进
    单元谐振式（0）。"""
    from rfauto.adapters.fake_adapter import array_resonance_ghz

    er, h = _substrate("patch_array_1x4")
    return float(array_resonance_ghz("patch_array_1x4", p, er=er, h_mm=h))


@_target("patch_array_2x2")
def _t_patch_array_2x2(p: dict[str, Any]) -> float:
    """y=单元谐振（同 patch_array_1x4：array_resonance_ghz 精确逆，单元
    同型）。符号语义同 patch_array_1x4（spacing_x/spacing_y 为阵列版图
    量=0）。"""
    from rfauto.adapters.fake_adapter import array_resonance_ghz

    er, h = _substrate("patch_array_2x2")
    return float(array_resonance_ghz("patch_array_2x2", p, er=er, h_mm=h))


@_target("patch_array_series")
def _t_patch_array_series(p: dict[str, Any]) -> float:
    """y=单元谐振（同 patch_array_1x4：array_resonance_ghz 精确逆；串馈
    互联 link_len 不改一阶单元谐振=0）。符号语义同 patch_array_1x4。"""
    from rfauto.adapters.fake_adapter import array_resonance_ghz

    er, h = _substrate("patch_array_series")
    return float(array_resonance_ghz("patch_array_series", p, er=er, h_mm=h))


@_target("patch_eep_1x4")
def _t_patch_eep_1x4(p: dict[str, Any]) -> float:
    """y=单元谐振 f0=c/(2(L+2·dl)·√εeff)（array_elem_len_mm 设计式精确逆，
    ee/dl 走 _array_patch_eps_dl 准静态单源——EEP 单元与 C2 阵列单元同型
    同链，fake _EEP_TEMPLATES 通道不含 array_resonance_ghz 成员门故直调
    同源算术）。符号：delem_len→f0 降（<1，ΔL 稀释）、delem_w 经 εeff+ΔL
    通道；elem_feed/spacing/feed_w（EEP 版图量）不进单元谐振式（0）。"""
    from rfauto.adapters.oe_templates.closedform import _array_patch_eps_dl

    er, h = _substrate("patch_eep_1x4")
    ee, dl = _array_patch_eps_dl(float(p["elem_w_mm"]), er, h)
    return C_MM_GHZ / (2.0 * (float(p["elem_len_mm"]) + 2.0 * dl)
                       * math.sqrt(ee))


@_target("patch_eep_2x2")
def _t_patch_eep_2x2(p: dict[str, Any]) -> float:
    """y=单元谐振（同 patch_eep_1x4：array_elem_len_mm 精确逆、
    _array_patch_eps_dl 单源；EEP 2x2 单元同型）。符号语义同
    patch_eep_1x4（spacing_x/spacing_y 为版图量=0）。"""
    from rfauto.adapters.oe_templates.closedform import _array_patch_eps_dl

    er, h = _substrate("patch_eep_2x2")
    ee, dl = _array_patch_eps_dl(float(p["elem_w_mm"]), er, h)
    return C_MM_GHZ / (2.0 * (float(p["elem_len_mm"]) + 2.0 * dl)
                       * math.sqrt(ee))


@_target("mmwave_series_array")
def _t_mmwave_series_array(p: dict[str, Any]) -> float:
    """y=单元谐振 f0=patch_resonance_hj_ghz(L,W,er,h)（C10d 串馈阵 fake
    裁判 _mmwave_series_sparams 同源：Hammerstad 准静态式逆式闭合；er/h
    为名义参数——毫米波板，禁用全局 stackup 缺省 #154 同名同语义）。
    符号：delem_len→f0 降（<1，ΔL 稀释）、delem_w/der/dh 经 εeff+ΔL
    通道；n_elem/link_len/feed_w/feed_margin/load_r（阵列/互联版图量）
    不进单元谐振式（0）；tan_d 不进准静态谐振式（0）。"""
    from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

    return float(patch_resonance_hj_ghz(
        float(p["elem_len_mm"]), float(p["elem_w_mm"]),
        float(p["er"]), float(p["h_mm"])))


# 可算集（字母序）：首批 18 + 架构批 A3-D 扩批 22 + R8-KN 扩批 4
# + SENS-ANC 复核扩批 2 + W4-S19 全覆盖批 24 + 架构批 W6-S4 sir_bpf
# 名义重注册解锁 1 = 71/72（模块 docstring 判定；
# W4-S19 起 teaching 集合不再排除入表、注册=全部 _TARGETS；
# 留缺 1 族=ms_array_NxN，缘由见 docstring「W4-S19 全覆盖批」节⑤）
COMPUTABLE_TEMPLATES: tuple[str, ...] = tuple(sorted(_TARGETS))


# ── 有限差分弹性管线 ─────────────────────────────────────────────────────────

def elasticity(target: Callable[[dict[str, Any]], float],
               params: dict[str, Any], param: str,
               rel: float = REL_STEP) -> float:
    """单参数归一化弹性 |Δln y/Δln x|（中心差分；整数参数 ±1 单位步；
    正数列表参数整体 ±rel 等比缩放——弹性分母=ln(1+rel)−ln(1−rel)，
    与连续参数相对步长同语义，W4-S19 批扩展）。"""
    x = params[param]
    if isinstance(x, bool) or not isinstance(x, (int, float, list)):
        raise TypeError(f"参数 {param}={x!r} 非数值，不可扰动")
    if isinstance(x, list):
        vals = []
        for v in x:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError(f"参数 {param} 含非数值元素 {v!r}，不可扰动")
            if not (float(v) > 0.0):
                raise ValueError(f"参数 {param} 含非正元素 {v!r}，越正域")
            vals.append(float(v))
        scale_lo, scale_hi = 1.0 - rel, 1.0 + rel
        p_lo = dict(params, **{param: [v * scale_lo for v in vals]})
        p_hi = dict(params, **{param: [v * scale_hi for v in vals]})
        denom = math.log(scale_hi) - math.log(scale_lo)
    else:
        is_int = isinstance(x, int)
        x_lo = x - 1 if is_int else x * (1.0 - rel)
        x_hi = x + 1 if is_int else x * (1.0 + rel)
        if x_lo <= 0.0 or x_hi <= 0.0:
            raise ValueError(f"参数 {param} 扰动越正域：{x_lo}..{x_hi}")
        p_lo = dict(params, **{param: x_lo})
        p_hi = dict(params, **{param: x_hi})
        denom = math.log(x_hi) - math.log(x_lo)
    y_lo = float(target(p_lo))
    y_hi = float(target(p_hi))
    for y in (y_lo, y_hi):
        if not (math.isfinite(y) and y > 0.0):
            raise ValueError(
                f"目标量越正域（{param}: y_lo={y_lo}, y_hi={y_hi}）——"
                "禁emit坏数据，先核目标量定义")
    return abs((math.log(y_hi) - math.log(y_lo)) / denom)


def _first_sentence(doc: str | None) -> str:
    """docstring → 首个语义句（W8-S36，审查波 3 P2-1 截断修复）。

    源 _target_* docstring 按行宽折行，原 ``splitlines()[0]`` 只取首
    物理行，把跨行首句拦腰截断（70 族实测 51 族 target_quantity 括号
    不配对/句子中断，后半句丢失）。语义单元判定：dedent 归一缩进后
    取到第一个『。』（含）为止；无『。』取到首个空行；再无则整段。
    句内折行换行一律归一为单空格（登记表单行值，确定性逐位可复现）。
    """
    if not doc:
        return ""
    text = textwrap.dedent(doc).strip()
    for i, ch in enumerate(text):
        if ch == "。":
            return " ".join(text[:i + 1].split())
    head = text.split("\n\n", 1)[0]
    return " ".join(head.split())


def build_entry(template: str) -> dict[str, Any]:
    """单模板登记条目（method/n_samples/source_run/registered_at+ranking）。"""
    target = _TARGETS[template]
    params = _params(template)
    skipped = NON_PERTURBABLE.get(template, {})
    ranking = []
    for name in sorted(params):
        if name in skipped:
            # 零值名义参数：正域守卫不可扰动——0 分=「不进目标恒等式」
            # 显式陈述（NON_PERTURBABLE 带缘由），非缺失非编造
            ranking.append({"param": name, "score": 0.0})
            continue
        ranking.append({"param": name,
                        "score": round(elasticity(target, params, name), 6)})
    # 登记表内按 R9 同款键序预排（-score, param）——人读序=normalize 后序
    ranking.sort(key=lambda item: (-item["score"], item["param"]))
    return {
        "method": METHOD,
        # 评估次数=名义点 1 + 每参数 ± 两点（中心差分口径）
        "n_samples": 1 + 2 * len(params),
        "seed": None,
        "source_run": SOURCE_RUN,
        "registered_at": BATCH_DATE,
        "target_quantity": _first_sentence(target.__doc__),
        "ranking": ranking,
    }


def build_all() -> dict[str, dict[str, Any]]:
    """全可算集登记映射（模板字母序；全确定性，重跑逐位一致）。"""
    return {name: build_entry(name) for name in COMPUTABLE_TEMPLATES}


def render_yaml(data: dict[str, dict[str, Any]]) -> str:
    """登记表 YAML 文本（确定性：固定键序+模板序，无时间戳随机量）。"""
    import yaml

    doc = {
        "schema": SCHEMA,
        "batch_id": BATCH_ID,
        "generated_by": SOURCE_RUN,
        "notes": (
            "敏感性排序登记表（X7 数据面批 + 架构批 A3-D 扩批 + R8-KN 扩批"
            "+ 架构批 SENS-ANC 复核扩批 + 架构批 W4-S19 全覆盖批；W8 桥"
            "消费端）。逐模板 score=|Δln y/Δln x| 中心差分弹性：连续参数 "
            "±1%、整数参数 ±1 单位步、正数列表参数（gaps/widths/lengths）"
            "整体 ±1% 等比缩放；目标量 y=模板核心闭式输出（逐模板 "
            "target_quantity 与 scripts/sensitivity_rankings_build.py "
            "_target_* docstring）。全确定性零随机零仿真（seed=null）；"
            "运行时只读、写入只经人工 commit（anchors.yaml 家法）。"
            "W4-S19 全覆盖批（2026-10-18）+24=70/72：teaching 首批 9 模板"
            "全部入表转双源并存（W8 消费优先级 computed>teaching，teaching "
            "EP-5 名次保留 teaching CLI 面；W6 卡面字节钉同批解除重生成）；"
            "hairpin/hairpin_alt 入表（c_f0=1.0370 真机标定常数系恒等式一"
            "部分，SENS-ANC 留缺判定 #222 复核勘误）；列表参数管线扩展+"
            "零值名义参数 NON_PERTURBABLE 0 分声明。架构批 W6-S4 解锁批"
            "（2026-10-19）+1=71/72：sir_bpf 名义重注册（l_high 6.7818 旧档"
            "含 R1 校准过孔缩短致恒等式名义回代 2.5586GHz 失自洽，重注册为 "
            "理想短路缺省链输出 7.1055 后名义回代 2.5000 带内——R3 审计处方；"
            "过孔补偿留 render 通道 l_via_h 锚）。如实留缺 1 族："
            "ms_array_NxN（单元几何埋在 cell_map"
            " 非数值结构、无标量几何自由度）。名义档代际偏移逐模板 "
            "docstring 如实登记（branchline/dipole/patch/interdigital/"
            "combline——弹性分数刻画恒等式局部敏感性，名义档龄不改分数"
            "有效性）。其余历史批判定与原因见模块 docstring「可算集判定」。"
        ),
        "templates": data,
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=100)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sensitivity_rankings_build",
        description="X7：可算模板敏感性排序登记表生成器（确定性离线）")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help=f"登记表输出路径（缺省 {DEFAULT_OUT}）")
    parser.add_argument("--check", action="store_true",
                        help="只构建并对照既有文件，不写入")
    parser.add_argument("--template", default=None,
                        help="只构建单模板（调试摘要用，不影响写入集）")
    args = parser.parse_args(argv)

    data = build_all()
    if args.template:
        if args.template not in data:
            raise SystemExit(f"{args.template!r} 不在可算集："
                             f"{'、'.join(data)}")
        data = {args.template: data[args.template]}
    text = render_yaml(data)

    out = Path(args.out)
    if args.check:
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        status = "identical" if current == text else "DIFFERS"
        print(f"check {out}: {status}")
        return 0 if status == "identical" else 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"sensitivity rankings written: {out} "
          f"({len(data)} templates)")
    for name, entry in data.items():
        top = entry["ranking"][0]
        zeros = sum(1 for r in entry["ranking"] if r["score"] == 0.0)
        print(f"  {name:22s} top1 {top['param']}={top['score']:.4f} "
              f"(n={entry['n_samples']}, zero-elasticity params={zeros}/"
              f"{len(entry['ranking'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
