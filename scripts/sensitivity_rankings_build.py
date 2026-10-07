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

可算集判定（18 个 = 25 可算 − 9 teaching 重叠）：
    25 个模板有确定性闭式目标量可扰动（19 TEMPLATE_NOMINAL 原生 + 6
    antenna2 设计式精确逆）；其中 9 个已有 meta.yaml teaching.sensitivity_ranking
    （wilkinson/branchline/cpw/dipole/hairpin/mline/patch/pyramid_horn/ratrace）
    ——本批不入表，理由：① W8 回归钉 test_w6_sensitivity_face_non_regression
    逐字节冻结 wilkinson(teaching)/ring_resonator(回退)卡节，入表即红
    （钉前提="该模板当前无登记表条目"）；② teaching 面（EP-5 名次）另含
    er/h 基板敏感性而闭式几何弹性不含，teaching 卡保留无信息损失；③ 升级面
    从None→computed，teaching 卡与回退卡逐字节零变化，卡面 diff 可审计。
    其余 46 模板无单点闭式目标量（级联/阵列/滤波器族走 fake 链式模型，
    一阶弹性需逐模板模型装配），如实不入表（卡面维持回退态，不硬凑）。

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
BATCH_ID = "x7_sens_data_20261004"
BATCH_DATE = "2026-10-04"
METHOD = "central_finite_difference_elasticity"
SOURCE_RUN = "scripts/sensitivity_rankings_build.py"
REL_STEP = 0.01  # 连续参数相对步长 ±1%
C_MM_GHZ = 299.792458  # mm·GHz（仓内闭式通用光速常数口径）
DEFAULT_STACKUP = "rogers4350b_h0.508"
# 带状线双板压合腔高（synthesize_stripline_model 缺省口径；非名义参数，
# 常量出处同源：两块 0.508mm 板压合）
STRIPLINE_B_MM = 1.016

# teaching 面已覆盖模板（不入表；理由见模块 docstring「可算集判定」③）
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


# 可算集（字母序）：18 = 25 可算 − 9 teaching 重叠（模块 docstring 判定③）
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
            "敏感性排序登记表（X7 数据面填充批；W8 桥消费端）。逐模板 "
            "score=|Δln y/Δln x| 中心差分弹性：连续参数 ±1%、整数参数 ±1 "
            "单位步；目标量 y=模板核心闭式输出（逐模板 target_quantity 与 "
            "scripts/sensitivity_rankings_build.py _target_* docstring）。"
            "全确定性零随机零仿真（seed=null）；运行时只读、写入只经人工 "
            "commit（anchors.yaml 家法）。teaching 面已覆盖的 9 模板不入表"
            "（test_w6_sensitivity_face_non_regression 钉前提+teaching 另含 "
            "er/h 基板敏感性）。"
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
