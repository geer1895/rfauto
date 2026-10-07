"""槽线 + SIW 闭式族（Janaswamy–Schaubert / Cassivi；内核在 core/slotline 等，本模块只做注册壳）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math

from .registry import register_calculator
from .rf_line import _C0_MS, _siw_w_eff_anchor_value

# ─── 槽线（slotline，单面金属开缝、无背板）闭式：Janaswamy–Schaubert 1986 ────────
# 内核在 core/slotline.py（常数双源核对、分段有效域、越界显式拒绝不外推，
# 路线 A 闭式裁判面；文献锚 Table 3.2 五频点 −0.83~−0.97%）。
# 本段只做注册壳：(w, h, εr, f) → (λ'/λ0, εeff, β, Z0) 与 Z0 → w 综合。
# 注意：全部量随频率变化（W/λ0、d/λ0 进入拟合式），freq_ghz 为必需参数；
# 仓库缺省叠层 h=0.508mm@2.5GHz 因 d/λ0=0.0042<0.006 落域外 → 显式 ValueError
# （设计点 RO4350B 60mil h=1.524mm）。

@register_calculator(
    "slotline_analysis",
    "槽线（slotline）分析：Janaswamy–Schaubert 闭式 (w, h, εr, f) → "
    "(λ'/λ0, εeff, β, Z0)；越有效域显式报错不外推。",
    (("w_mm", "float mm 槽宽（金属面上的缝）"),
     ("h_mm", "float mm 基板厚（单面金属，基板下为空气）"),
     ("epsilon_r", "float - 基板相对介电常数（2.22–9.8 两段拟合）"),
     ("freq_ghz", "float GHz 频率（W/λ0、d/λ0 进入拟合式，必需）")),
    required=("w_mm", "h_mm", "epsilon_r", "freq_ghz"),
)
def slotline_analysis(w_mm: float, h_mm: float, epsilon_r: float,
                      freq_ghz: float) -> dict:
    from rfauto.core.slotline import slotline_closed_form

    r = slotline_closed_form(w_mm, h_mm, epsilon_r, freq_ghz)
    lam_g_mm = r.lambda_ratio * _C0_MS / (float(freq_ghz) * 1e9) * 1e3
    return {"z0_ohm": round(r.z0_ohm, 2),
            "eps_eff": round(r.eps_eff, 4),
            "lambda_ratio": round(r.lambda_ratio, 5),
            "beta_rad_m": round(r.beta_rad_m, 4),
            "lambda_g_mm": round(lam_g_mm, 3),
            "segment": r.segment,
            "w_over_lambda0": round(r.w_over_lambda0, 5),
            "d_over_lambda0": round(r.d_over_lambda0, 5)}


@register_calculator(
    "slotline_synthesis",
    "槽线（slotline）综合：目标 Z0 → 槽宽 w（同频窄槽段 0.0015≤W/λ0≤0.075 "
    "括号内 brentq，回代自洽；不可达/越域显式报错）",
    (("z0_ohm", "float Ω 目标特性阻抗（功率-电压定义）"),
     ("h_mm", "float mm 基板厚"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 频率")),
    required=("z0_ohm", "h_mm", "epsilon_r", "freq_ghz"),
)
def slotline_synthesis(z0_ohm: float, h_mm: float, epsilon_r: float,
                       freq_ghz: float) -> dict:
    from scipy.optimize import brentq

    from rfauto.core.slotline import (
        W_OVER_LAMBDA0_NARROW_RANGE,
        slotline_closed_form,
    )

    z_t = float(z0_ohm)
    if not (math.isfinite(z_t) and z_t > 0.0):
        raise ValueError(f"slotline_synthesis: z0_ohm 须为正有限数，得到 {z0_ohm!r}")
    lam0_mm = _C0_MS / (float(freq_ghz) * 1e9) * 1e3
    # 窄槽段有效窗（w/λ0 ∈ [0.0015, 0.075]）内侧留 1e-6 相对余量防边界舍入
    w_lo = W_OVER_LAMBDA0_NARROW_RANGE[0] * lam0_mm * (1.0 + 1e-6)
    w_hi = W_OVER_LAMBDA0_NARROW_RANGE[1] * lam0_mm * (1.0 - 1e-6)

    def objective(w_mm: float) -> float:
        # d/λ0、εr 越域在此处即抛 ValueError（分段判定先于数值）
        return slotline_closed_form(w_mm, h_mm, epsilon_r, freq_ghz).z0_ohm - z_t

    z_lo = objective(w_lo)
    z_hi = objective(w_hi)
    # Z0 随 w 单调上升（√(W/λ0) 主项；数值单调性由单测网格钉住）；括号越界如实报错
    if z_lo > 0.0 or z_hi < 0.0:
        raise ValueError(
            f"目标 {z_t}Ω 超出窄槽段可达范围 "
            f"[{z_lo + z_t:.1f}, {z_hi + z_t:.1f}]Ω"
            f"（w∈[{w_lo:.4f}, {w_hi:.4f}]mm @ {freq_ghz}GHz 括号扫描）")
    w_mm = float(brentq(objective, w_lo, w_hi, xtol=1e-9))
    r = slotline_closed_form(w_mm, h_mm, epsilon_r, freq_ghz)
    lam_g_mm = r.lambda_ratio * lam0_mm
    return {"w_mm": round(w_mm, 4), "z0_actual_ohm": round(r.z0_ohm, 2),
            "eps_eff": round(r.eps_eff, 4),
            "lambda_ratio": round(r.lambda_ratio, 5),
            "beta_rad_m": round(r.beta_rad_m, 4),
            "lambda_g_mm": round(lam_g_mm, 3), "segment": r.segment}


# ─── SIW（基片集成波导）闭式：Cassivi 2002 等效宽度 + RWG TE10 等效 ───────────
# 双源核实与全部常数出处：runs/siw_family/criteria.md §1（铁律 1c）——
# 等效宽度 w_eff = w − d²/(0.95·s)（来源 A：Wikipedia SIW 条目引 Cassivi et al.
# 2002 MWCL 12(9):333–335 / Bozzi 2011 IET 综述；来源 B：Microwaves101 SIW 条目
# eq.4 引 Wu–Deslandes–Cassivi TELSIKS 2003；rfessentials/calculator.academy 文本
# 逐字交叉印证）；TE10 截止与色散按"同宽 w_eff 同填充的介质矩形波导"等效
# （来源 A 明文）：
#   fc10 = c/(2·w_eff·√εr)，β(f) = √((n·k0)² − (π/w_eff)²)，n=√εr，kc=π/w_eff。
# 设计规则（过孔藩篱泄漏控制，来源 B[1]/C 双源）：s ≤ 2·d 且 d < λ_sub/5
# （λ_sub = c/(f·√εr) 为基板内平面波波长；较 λg 口径更严，取严者——
# NW Engineering Solutions SIW 设计条件明文 + Microwaves101 eq.5/6 同源）。
# 波导阻抗口径（确定性内核非手数，#7）：TE10 波阻抗 Z_TE=ωμ0/β（u/i 定义），
# 功率-电压定义 Z_PV = 2·b·Z_TE/w_eff（b=基板厚 h；V=中线全高电压=E0·b、
# P=E0²·a·b/(4·Z_TE) 消元）——渲染层 LumpedPort R 与 OE 锚判读同源消费。
# 回收基准（#118/#300，test_siw_template 钉死）：d→0 极限 w_eff→w 逐位；
# εr=1、a=22.86mm 复现 WR-90 空气波导 fc=6.5571GHz（Pozar 教科书值）。

def siw_effective_width_mm(w_mm: float, d_mm: float, s_mm: float) -> float:
    """Cassivi 2002 等效宽度（mm）：w_eff = w − d²/(0.95·s)。

    只做公式本体；几何设计规则守卫在 siw_check_design_rules。
    值源（DP-3 第二批改道）：优先 siw.w_eff.lit-v1 公式锚
    （knowledge/anchors.yaml，expr=w_mm - d_mm**2/(0.95*s_mm)，双源
    Cassivi 2002 / Wu-Deslandes-Cassivi 2003）；锚不可解析（未注册/失败）
    回退本闭式——回退式与锚式逐位相等（同 op 序，test_anchors_core a4 /
    test_anchor_wire_df7 钉），零行为变化。"""
    got = _siw_w_eff_anchor_value(float(w_mm), float(d_mm), float(s_mm))
    if got is not None:
        return got
    return float(w_mm) - (float(d_mm) ** 2) / (0.95 * float(s_mm))


def siw_check_design_rules(w_mm: float, d_mm: float, s_mm: float,
                           epsilon_r: float, freq_ghz: float | None = None,
                           ref_freq_ghz: float | None = None) -> dict:
    """过孔藩篱设计规则复核（双源出处见 criteria.md §1），违反显式 ValueError。

    - s > d：相邻过孔不得重叠（物理可制造性）；
    - s ≤ 2·d：泄漏控制上界（Microwaves101 eq.5/6 同源；
      NW Engineering 明文 "via spacing s must be less than double the via
      diameter d"）；
    - d < λ_sub/5：直径远小于波长（λ_sub=c/(f·√εr)；ref_freq_ghz 缺省取
      freq_ghz，都缺省用 fc 折算不可行——本检查只在给出频率时执行）。
    返回实测比值表（供判读留痕），全部通过才返回。
    """
    w = float(w_mm)
    d = float(d_mm)
    s = float(s_mm)
    er = float(epsilon_r)
    for name, v in (("w_mm", w), ("d_mm", d), ("s_mm", s)):
        if not (math.isfinite(v) and v > 0.0):
            raise ValueError(f"siw: {name} 必须为正有限数，得到 {v!r}")
    if not (math.isfinite(er) and er >= 1.0):
        # εr=1 合法（空气填充 RWG 极限=回收基准 WR-90 钉用）
        raise ValueError(f"siw: epsilon_r 必须为不小于 1 的有限数，得到 {er!r}")
    if not s > d:
        raise ValueError(f"siw: 过孔心距 s={s}mm 必须大于直径 d={d}mm（孔不重叠）")
    if s > 2.0 * d:
        raise ValueError(
            f"siw: 过孔心距 s={s}mm 超出泄漏控制上界 2·d={2.0 * d:.4g}mm"
            "（设计规则 s≤2d，Microwaves101 eq.5/6 / NWES，criteria.md §1）")
    lam_sub_mm = None
    f_ref = ref_freq_ghz if ref_freq_ghz is not None else freq_ghz
    if f_ref is not None:
        f_hz = float(f_ref) * 1e9
        if not (math.isfinite(f_hz) and f_hz > 0.0):
            raise ValueError(f"siw: 频率必须为正有限数，得到 {f_ref!r}")
        lam_sub_mm = _C0_MS / (f_hz * math.sqrt(er)) * 1e3
        if not d < lam_sub_mm / 5.0:
            raise ValueError(
                f"siw: 过孔直径 d={d}mm 未满足 d<λ_sub/5="
                f"{lam_sub_mm / 5.0:.4g}mm @ {f_ref}GHz"
                "（设计规则，criteria.md §1；λ_sub 口径较 λg 更严取严者）")
    return {"s_over_d": round(s / d, 6),
            "d_over_lambda_sub": (round(d / lam_sub_mm, 6)
                                  if lam_sub_mm is not None else None)}


def siw_beta_rad_m(w_eff_mm: float, epsilon_r: float,
                   freq_ghz: float) -> tuple[float, float]:
    """等效 RWG TE10 色散：返回 (beta_rad_m, fc10_ghz)。

    f≤fc10 时 β 为虚数（倏逝）——返回 NaN，由调用方按截止下衰减
    α=√(kc²−k²) 自行处理（分析键内部已给出 α）。
    """
    weff_m = float(w_eff_mm) * 1e-3
    f_hz = float(freq_ghz) * 1e9
    n = math.sqrt(float(epsilon_r))
    k0 = 2.0 * math.pi * f_hz / _C0_MS
    kc = math.pi / weff_m
    fc10_ghz = _C0_MS / (2.0 * weff_m * n) / 1e9
    k = k0 * n
    if k <= kc:
        return float("nan"), fc10_ghz
    return math.sqrt(k * k - kc * kc), fc10_ghz


@register_calculator(
    "siw_analysis",
    "SIW 分析：Cassivi 2002 等效宽度 + RWG TE10 等效 (w, d, s, εr, f) → "
    "(fc10, weff, β, λg, Z_TE, Z_PV)；过孔设计规则违规显式报错不外推。",
    (("w_mm", "float mm 两过孔列心距（物理宽度）"),
     ("d_mm", "float mm 金属化过孔直径"),
     ("s_mm", "float mm 过孔心距（同列相邻孔中心间距）"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("freq_ghz", "float GHz 工作频率（β/λg/设计规则 d<λ_sub/5 检查）")),
    required=("w_mm", "d_mm", "s_mm", "epsilon_r", "freq_ghz"),
)
def siw_analysis(w_mm: float, d_mm: float, s_mm: float, epsilon_r: float,
                 freq_ghz: float) -> dict:
    f_ghz = float(freq_ghz)
    if not (math.isfinite(f_ghz) and f_ghz > 0.0):
        raise ValueError(f"siw_analysis: freq_ghz 必须为正有限数，得到 {freq_ghz!r}")
    rules = siw_check_design_rules(w_mm, d_mm, s_mm, epsilon_r, freq_ghz=f_ghz)
    weff_mm = siw_effective_width_mm(w_mm, d_mm, s_mm)
    if not weff_mm > 0.0:
        raise ValueError(
            f"siw_analysis: 等效宽度 w_eff={weff_mm:.4f}mm 非正（w 过小或 d/s 过大）")
    weff_m = weff_mm * 1e-3
    n = math.sqrt(float(epsilon_r))
    k0 = 2.0 * math.pi * f_ghz * 1e9 / _C0_MS
    kc = math.pi / weff_m
    fc10_ghz = _C0_MS / (2.0 * weff_m * n) / 1e9
    k = k0 * n
    if k > kc:
        beta = math.sqrt(k * k - kc * kc)
        lam_g_mm = 2.0 * math.pi / beta * 1e3
        z_te = 2.0 * math.pi * f_ghz * 1e9 * 1.25663706212e-6 / beta
        alpha_np_m = 0.0
    else:
        beta = float("nan")
        lam_g_mm = float("nan")
        z_te = float("nan")
        alpha_np_m = math.sqrt(kc * kc - k * k)
    # 功率-电压波阻抗（等效波导 b=h：R=2·b·Z_TE/w_eff；h 未入参——SIW 的
    # fc10/β/Z_TE 与 h 无关（Microwaves101 SIW 条目明文），Z_PV 需 h 时由
    # 渲染层按模板 h 换算，本键只出与 h 无关的量）
    return {"fc10_ghz": round(fc10_ghz, 4),
            "weff_mm": round(weff_mm, 4),
            "kc_rad_m": round(kc, 3),
            "beta_rad_m": (round(beta, 4) if math.isfinite(beta) else None),
            "alpha_below_cutoff_np_m": (None if math.isfinite(beta)
                                        else round(alpha_np_m, 3)),
            "lambda_g_mm": (round(lam_g_mm, 4) if math.isfinite(lam_g_mm)
                            else None),
            "z_te_ohm": (round(z_te, 3) if math.isfinite(z_te) else None),
            "lambda_sub_mm": round(_C0_MS / (f_ghz * 1e9 * n) * 1e3, 4),
            "f_over_fc": round(f_ghz / fc10_ghz, 6),
            "design_rules": rules}


@register_calculator(
    "siw_synthesis",
    "SIW 综合：目标 TE10 截止 fc10 → 两列心距 w（w_eff=c/(2·fc10·√εr) 反解 "
    "Cassivi 式；设计规则违规显式报错；回代自洽）。",
    (("fc10_ghz", "float GHz 目标 TE10 截止频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("d_mm", "float mm 金属化过孔直径"),
     ("s_mm", "float mm 过孔心距")),
    required=("fc10_ghz", "epsilon_r", "d_mm", "s_mm"),
)
def siw_synthesis(fc10_ghz: float, epsilon_r: float, d_mm: float,
                  s_mm: float) -> dict:
    fc = float(fc10_ghz)
    if not (math.isfinite(fc) and fc > 0.0):
        raise ValueError(f"siw_synthesis: fc10_ghz 必须为正有限数，得到 {fc10_ghz!r}")
    weff_mm = _C0_MS / (2.0 * fc * 1e9 * math.sqrt(float(epsilon_r))) * 1e3
    d = float(d_mm)
    s = float(s_mm)
    # w = w_eff + d²/(0.95·s)（Cassivi 式反解）；设计规则检查用 fc10（带内最松
    # 端——λ_sub 随 f 升高缩短，高频端的 d<λ_sub/5 由 siw_analysis 按实查 f 把关）
    w_mm = weff_mm + (d * d) / (0.95 * s)
    rules = siw_check_design_rules(w_mm, d, s, epsilon_r,
                                   ref_freq_ghz=fc)
    weff_back = siw_effective_width_mm(w_mm, d, s)
    fc_back = _C0_MS / (2.0 * weff_back * 1e-3
                        * math.sqrt(float(epsilon_r))) / 1e9
    if abs(fc_back - fc) > 1e-9 * max(1.0, fc):
        raise ValueError("siw_synthesis: 回代自洽失败（数值内部错误）")
    return {"w_mm": round(w_mm, 4),
            "weff_mm": round(weff_mm, 4),
            "weff_roundtrip_mm": round(weff_back, 6),
            "fc10_roundtrip_ghz": round(fc_back, 6),
            "kc_rad_m": round(math.pi / (weff_mm * 1e-3), 3),
            "design_rules": rules}
