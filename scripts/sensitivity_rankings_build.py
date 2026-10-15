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

可算集判定（首批 18 + aurora72 A3-D 扩批 +22 + R8-KN 扩批 +4
    + aurora_d SENS-ANC 复核扩批 +2 = 46）：
    首批 X7（2026-10-04）：25 个模板有确定性闭式目标量可扰动（19
    TEMPLATE_NOMINAL 原生 + 6 antenna2 设计式精确逆）；其中 9 个已有
    meta.yaml teaching.sensitivity_ranking（wilkinson/branchline/cpw/dipole/
    hairpin/mline/patch/pyramid_horn/ratrace）——本批不入表，理由：① W8
    回归钉 test_w6_sensitivity_face_non_regression 逐字节冻结
    wilkinson(teaching)/ring_resonator(回退)卡节，入表即红（钉前提="该
    模板当前无登记表条目"）；② teaching 面（EP-5 名次）另含 er/h 基板
    敏感性而闭式几何弹性不含，teaching 卡保留无信息损失；③ 升级面从
    None→computed，teaching 卡与回退卡逐字节零变化，卡面 diff 可审计。
    aurora72 A3-D 扩批（2026-10-11）：新 +22 目标（nway_wilkinson/
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
    aurora72 R8-KN 扩批（2026-10-13）：新 +4 目标（diplexer/schiffman/
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
    aurora_d SENS-ANC 复核扩批（2026-10-14）：+2（varactor_bpf/xcheb_bpf4）
    ——R8-KN「缺推导锚」组的 #222 树面复核勘误：两族名义推导链实为纯闭式
    内核单源（varactor.varactor_bpf_design 装载谐振链：突变结 C(bias)→主谐
    振方程正解，c823ac45 引入；cross_coupled_map.cross_coupled_bpf_design
    开路环周长恒等式 perimeter=λg/2−2Δl、a=perimeter/4，897eba0f 引入），
    名义回代 f0=2.499997/2.499993（4 位舍入传播带内）。同组 hairpin_alt
    维持不入表——arm_len 名义含经验先验乘子 c_f0=1.0370（render_hairpin
    段头「alt 真机复标后可改」）且 campaign_capable=False（kgap 门未过），
    非稳定闭式恒等。

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
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "knowledge" / "sensitivity_rankings.yaml"

SCHEMA = "sensitivity_rankings/v1"
BATCH_ID = "aurora_d_sensanc_20261014"
BATCH_DATE = "2026-10-14"
METHOD = "central_finite_difference_elasticity"
SOURCE_RUN = "scripts/sensitivity_rankings_build.py"
REL_STEP = 0.01  # 连续参数相对步长 ±1%
C_MM_GHZ = 299.792458  # mm·GHz（仓内闭式通用光速常数口径）
DEFAULT_STACKUP = "rogers4350b_h0.508"
# 带状线双板压合腔高（synthesize_stripline_model 缺省口径；非名义参数，
# 常量出处同源：两块 0.508mm 板压合）
STRIPLINE_B_MM = 1.016

# teaching 面首批 9 模板（不入表；理由见模块 docstring「可算集判定」①-③：
# 卡面字节钉冻结 + teaching 名次含 er/h。aurora72 批起新 teaching 卡与登记表
# 双源并存——W8 消费优先级 computed > teaching，见 docstring「双源并存政策」）
TEACHING_TEMPLATES = frozenset({
    "wilkinson", "branchline", "cpw", "dipole", "hairpin", "mline",
    "patch", "pyramid_horn", "ratrace",
})


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


# ── aurora72 A3-D 扩批目标量（+25；专族内核/既有单源，符号语义见 docstring）──


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


# ── aurora72 R8-KN 扩批目标量（+4；段参数/内核相位单点闭式，与 A3-D 批
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


# 可算集（字母序）：首批 18 + aurora72 A3-D 扩批 22 + R8-KN 扩批 4
# + SENS-ANC 复核扩批 2 = 46（模块 docstring 判定）
COMPUTABLE_TEMPLATES: tuple[str, ...] = tuple(sorted(
    name for name in _TARGETS if name not in TEACHING_TEMPLATES))


# ── 有限差分弹性管线 ─────────────────────────────────────────────────────────

def elasticity(target: Callable[[dict[str, Any]], float],
               params: dict[str, Any], param: str,
               rel: float = REL_STEP) -> float:
    """单参数归一化弹性 |Δln y/Δln x|（中心差分；整数参数 ±1 单位步）。"""
    x = params[param]
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(f"参数 {param}={x!r} 非数值，不可扰动")
    is_int = isinstance(x, int)
    x_lo = x - 1 if is_int else x * (1.0 - rel)
    x_hi = x + 1 if is_int else x * (1.0 + rel)
    if x_lo <= 0.0 or x_hi <= 0.0:
        raise ValueError(f"参数 {param} 扰动越正域：{x_lo}..{x_hi}")
    p_lo = dict(params, **{param: x_lo})
    p_hi = dict(params, **{param: x_hi})
    y_lo = float(target(p_lo))
    y_hi = float(target(p_hi))
    for y in (y_lo, y_hi):
        if not (math.isfinite(y) and y > 0.0):
            raise ValueError(
                f"目标量越正域（{param}: y_lo={y_lo}, y_hi={y_hi}）——"
                "禁emit坏数据，先核目标量定义")
    return abs((math.log(y_hi) - math.log(y_lo))
               / (math.log(x_hi) - math.log(x_lo)))


def build_entry(template: str) -> dict[str, Any]:
    """单模板登记条目（method/n_samples/source_run/registered_at+ranking）。"""
    target = _TARGETS[template]
    params = _params(template)
    ranking = [
        {"param": name, "score": round(elasticity(target, params, name), 6)}
        for name in sorted(params)
    ]
    # 登记表内按 R9 同款键序预排（-score, param）——人读序=normalize 后序
    ranking.sort(key=lambda item: (-item["score"], item["param"]))
    return {
        "method": METHOD,
        # 评估次数=名义点 1 + 每参数 ± 两点（中心差分口径）
        "n_samples": 1 + 2 * len(params),
        "seed": None,
        "source_run": SOURCE_RUN,
        "registered_at": BATCH_DATE,
        "target_quantity": target.__doc__.strip().splitlines()[0]
        if target.__doc__ else "",
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
            "敏感性排序登记表（X7 数据面批 + aurora72 A3-D 扩批 + R8-KN 扩批"
            "+ aurora_d SENS-ANC 复核扩批；W8 桥消费端）。逐模板 "
            "score=|Δln y/Δln x| 中心差分弹性：连续参数 ±1%、整数参数 ±1 "
            "单位步；目标量 y=模板核心闭式输出（逐模板 target_quantity 与 "
            "scripts/sensitivity_rankings_build.py _target_* docstring）。"
            "全确定性零随机零仿真（seed=null）；运行时只读、写入只经人工 "
            "commit（anchors.yaml 家法）。首批 9 模板（wilkinson/branchline/"
            "cpw/dipole/hairpin/mline/patch/pyramid_horn/ratrace）不入表"
            "（卡面字节钉前提）；aurora72 批起其余模板可 teaching 卡+登记表"
            "双源并存——W8 消费优先级 computed>teaching，两源口径不同不混写。"
            "R8-KN 扩批（2026-10-13）+4（diplexer/schiffman/msl_cpw/"
            "msl_siw_taper，段参数/内核相位单点闭式，marchand/"
            "msl_slot_transition 先例同类）；SENS-ANC 复核扩批（2026-10-14）"
            "+2（varactor_bpf/xcheb_bpf4——装载谐振/开路环周长纯闭式链，"
            "R8-KN「缺推导锚」组 #222 树面复核勘误，名义回代 2.49999/"
            "2.49999）；其余族不可扩判定与原因见模块 docstring「可算集判定」。"
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
