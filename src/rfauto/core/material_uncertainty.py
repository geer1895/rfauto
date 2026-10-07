"""MA-8 材料不确定度闭环内核（round17 §六 MA-8：Dk ±tol→阻抗/谐振频率
敏感度传播 + 78GHz Design Dk 锚量化）。

链路（数值只在确定性内核，规则 7；闭式出处见各函数 docstring）：

1. **准静态微带 δZ/δDk 闭式**（Pozar《Microwave Engineering》/Balanis
   《Antenna Theory》标准口径）：Z0(εr)=Z_air(W,h)/√εeff(W,h,εr)，
   εeff=(εr+1)/2+(εr−1)/2·F、F=(1+12h/W)^(−1/2)——Z_air 只依赖几何，
   故 ∂lnZ0/∂lnεr = −0.5·∂lnεeff/∂lnεr = −(εr/εeff)·(1+F)/4 是**模型内
   构造性恒等式**（单测闭式↔中心差分逐位级互证，非近似拟合）。
2. **谐振频率 δf/δDk**：贴片 f0=c/(2(L+2ΔL)√εeff)。冻结 ΔL 时与阻抗同
   一恒等式（闭式档）；全模型档（ΔL(εeff) 非线性，仓内裁判
   core/symbolic_fit.patch_resonance_hj_ghz 口径）走中心差分数值敏感度
   ——两档差异 ~9%（ΔL 修正项），如实双报。
3. **容差传播**：线性档 half_width=|S|·nominal·(tol/Dk)（一阶）；
   Monte Carlo 档（均匀 Dk±tol，numpy default_rng 固定种子）给端点/
   分位/std——两档一致性是单测门（≤2%），MC 是交叉验证不是替代。
4. **78GHz Design Dk 锚案例**（C10d 语境钉死，runs/ge6_anchor/criteria.md
   §0 + runs/df7_c10d/smoke_nominal 渲染字面量）：RO3003 process Dk
   3.00±0.04 的容差带对 78 GHz 谐振的传播量级 ~±0.45 GHz，而 C10d 实测
   谷位缺口 1.80 GHz（−2.31%）≈ 容差带的 4 倍——**制造容差解释不了，
   方法域 Dk 差（process vs circuit 差 ~5%，本库 material_library 冲突
   注记实证）才是主项**，故 78 GHz 必须落电路域 Design Dk 锚（已注册
   mmwave.design_dk.ro3003-oe-hfss-v2=3.1025 constant/active，ge8b 批
   K-4 双引擎 AGREE 后消费自 v1=3.1434 pointer 封档切至 v2），量化
   "为什么 datasheet 名义值不可直移"（#302 方法域铁律的数值演绎）。

诚实边界（预声明）：
1. 准静态闭式是 Wheeler/Pozar 教科书口径，与本仓综合链 skrf HJ 有 ~1%
   绝对口径差（C10d 馈线 49.6 vs 50 Ω）——敏感度结论不受影响，绝对
   阻抗以仓内综合链为准（本模块不替代综合链）。
2. 全模型敏感度是中心差分数值解（O(h²)，h=1e-4 相对步长），不是解析
   解——解析恒等只对冻结 ΔL 档成立，两档差异如实双报。
3. MC 均匀采样假设 process 容差带均匀分布（datasheet 未给分布形状）；
   正态假设下 std 面走 linear_std·√3 换算，不另行编分布参数。
4. 78GHz 案例的 f_dip=76.20 GHz 是 OE 单引擎单点真跑（runs/df7_c10d），
   锚 er_design=3.1434 是 pointer/experimental（constant 待 HFSS 仲裁腿）
   ——本模块量化的是缺口量级归因，不产新材料常数。
5. 温度档只覆盖线性 TCDk 系数（material_library.dk_at_temperature），
   tanδ(T) 无官方点值不建模。

分层与注册：core 层纯函数零 IO（numpy 唯一依赖）；**不进 calculators
注册表**（F-C P1 域内约定，同 cryo_materials.py/material_library.py
先例）；规格 MA-8 未列 CLI/MCP 面。同层消费 core/symbolic_fit
（patch_resonance_hj_ghz=fa3/C10d 判裁判面）与 core/material_library
（datasheet 域/冲突注记引用），禁反向依赖上层的分层契约不受影响。

接口：全部函数返回 JSON 可序列化 dict/float/str/bool/None；数值 0.0
合法（判缺失一律 ``is not None``，#364④）；bool 显式拒收（df7+⑯）。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

import numpy as np

from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

logger = logging.getLogger(__name__)

__all__ = [
    "C10D_CASE",
    "back_out_design_dk",
    "back_out_design_dk_full_cf",
    "case_78ghz_design_dk",
    "dk_log_sensitivity_numeric",
    "eps_eff_quasi_static",
    "propagate_dk_tolerance",
    "quasi_static_microstrip",
    "resolve_anchor_er_design",
    "z0_air_quasi_static",
    "z0_sensitivity_closed_form",
]

#: 光速（mm·GHz）——与 core/synthesis.py、core/symbolic_fit.py 同口径
_C_MM_GHZ = 299.792458

#: C10d 串馈毫米波阵名义（runs/ge6_anchor/criteria.md §1「旧名义 G_old」，
#: 源=render_mmwave.MMWAVE_SERIES_NOMINAL @er=3.0 导入期闭式合成；f_dip=
#: runs/df7_c10d/smoke_nominal sparams.csv |S11| 谷位 76.20 GHz）
C10D_CASE: dict[str, Any] = {
    "f0_ghz": 78.0,
    "l_mm": 0.9271,
    "w_mm": 1.3589,
    "h_mm": 0.127,
    "er_nominal": 3.0,
    "f_dip_ghz": 76.20,
    "anchor_id": "mmwave.design_dk.ro3003-oe-hfss-v2",
    # J1-3 改道（ge8e 审查批 F8）：本值自此只作 fallback——value 单源=
    # knowledge/anchors.yaml 活注册表（resolve_anchor_er_design 消费期解析，
    # 锚升版时改表即可，模块副本不再陈旧）；数值与改道前逐位一致。
    "anchor_er_design": 3.1025,
    "anchor_status": "constant/active（K-4 双引擎 AGREE：HFSS 平方法口径 "
                     "3.1025 与 OE 3.1434 交叉证差 1.32%≤FA3 带 5.2%；"
                     "v1 pointer 零改写封档）",
    "provenance": (
        "runs/ge6_anchor/verdict.json（C10d 离线复判 PASS，R0–R4 全真）+"
        "runs/df7_c10d/smoke_nominal；几何=旧名义 "
        "G_old 闭式链字面量"
    ),
}


def resolve_anchor_er_design(f_ghz: float) -> dict[str, Any]:
    """78GHz Design Dk 锚值单源解析：活锚注册表优先，常量仅 fallback。

    J1-3 改道（ge8e 审查批 F8）：core 零 IO，经 core/anchors 的
    ``live_anchor_set()`` 接插点惰性取活注册表（provider 由
    infra/anchors_store 导入时反向注册，core/calc_families/rf_line.py
    同款消费惯例）。锚缺席/provider 未注册/stale/域外/任何故障 → 回退
    ``C10D_CASE["anchor_er_design"]`` 常量 + 模块级 warning 留痕
    （#105：观测性不阻塞业务主路径），数值与改道前逐位一致。

    Returns:
        {value, source: "anchor"|"fallback", reason, anchor_id}——source
        随行披露（消费面可区分锚值与回退值）。
    """
    fallback = float(C10D_CASE["anchor_er_design"])
    reason: str | None = None
    try:
        from rfauto.core.anchors import live_anchor_set

        anchor_set = live_anchor_set()
        if anchor_set is not None:
            got = anchor_set.resolve_anchor(str(C10D_CASE["anchor_id"]),
                                            {"f_ghz": float(f_ghz)})
            value = got.get("value")
            if (got.get("hit") and got.get("source") == "anchor"
                    and not got.get("stale")
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))):
                return {"value": float(value), "source": "anchor",
                        "reason": None,
                        "anchor_id": str(C10D_CASE["anchor_id"])}
            reason = str(got.get("reason") or "not_resolvable")
        else:
            reason = "registry_unavailable"
    except Exception as exc:  # best-effort：锚内核任何故障都走回退（#105）
        reason = f"error:{type(exc).__name__}"
    logger.warning("锚 %s 不可解析（%s）——回退模块常量 %.4f（#105 留痕）",
                   C10D_CASE["anchor_id"], reason, fallback)
    return {"value": fallback, "source": "fallback", "reason": reason,
            "anchor_id": str(C10D_CASE["anchor_id"])}


# ─── 入参收敛守卫（aging/cryo/library 同口径）───────────────────────────────


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正数，收到 {out}")
    return out


def _geo(w_mm: float, h_mm: float) -> tuple[float, float]:
    return _positive(w_mm, "w_mm"), _positive(h_mm, "h_mm")


# ─── 准静态微带闭式（Pozar/Balanis 口径）────────────────────────────────────


def eps_eff_quasi_static(w_mm: float, h_mm: float, er: float) -> float:
    """有效介电常数 εeff=(εr+1)/2+(εr−1)/2·F，F=(1+12h/W)^(−1/2)。

    对 εr 线性（构造性）——∂εeff/∂εr=(1+F)/2 是闭式敏感度的根基。
    """
    w, h = _geo(w_mm, h_mm)
    er_v = _finite(er, "er")
    if er_v <= 1.0:
        raise ValueError(f"er 必须 > 1，收到 {er_v}")
    fill = (1.0 + 12.0 * h / w) ** -0.5
    return (er_v + 1.0) / 2.0 + (er_v - 1.0) / 2.0 * fill


def z0_air_quasi_static(w_mm: float, h_mm: float) -> float:
    """空气微带阻抗 Z_air（纯几何，Pozar 两分支口径）。

    W/h ≥ 1：Z_air=120π/(W/h+1.393+0.667·ln(W/h+1.444))；
    W/h < 1：Z_air=60·ln(8h/W+W/(4h))。
    """
    w, h = _geo(w_mm, h_mm)
    ratio = w / h
    if ratio >= 1.0:
        return 120.0 * math.pi / (
            ratio + 1.393 + 0.667 * math.log(ratio + 1.444))
    return 60.0 * math.log(8.0 * h / w + w / (4.0 * h))


def quasi_static_microstrip(w_mm: float, h_mm: float, er: float) -> dict[str, Any]:
    """准静态微带 Z0/εeff/fill_factor（Z0=Z_air/√εeff 构造性分解）。"""
    er_v = _finite(er, "er")
    if er_v <= 1.0:
        raise ValueError(f"er 必须 > 1，收到 {er_v}")
    w, h = _geo(w_mm, h_mm)
    eps_eff = eps_eff_quasi_static(w, h, er_v)
    z_air = z0_air_quasi_static(w, h)
    return {
        "z0_ohm": z_air / math.sqrt(eps_eff),
        "eps_eff": eps_eff,
        "fill_factor": (1.0 + 12.0 * h / w) ** -0.5,
        "z0_air_ohm": z_air,
        "w_over_h": w / h,
    }


def z0_sensitivity_closed_form(w_mm: float, h_mm: float, er: float) -> dict[str, Any]:
    """∂lnZ0/∂lnDk 闭式（模型内构造性恒等，非近似）。

    S_Z = −0.5·(εr/εeff)·(1+F)/2 = −(εr/εeff)·(1+F)/4。
    恒等锚：Z_air 与 εr 无关 ⇒ ∂lnZ0/∂lnεr = −0.5·∂lnεeff/∂lnεr。
    """
    q = quasi_static_microstrip(w_mm, h_mm, er)
    er_v = float(er)
    s_eps = (er_v / q["eps_eff"]) * (1.0 + q["fill_factor"]) / 2.0
    return {
        "s_z0": -0.5 * s_eps,
        "s_eps_eff": s_eps,
        "eps_eff": q["eps_eff"],
        "fill_factor": q["fill_factor"],
        "z0_ohm": q["z0_ohm"],
        "identity": "Z0=Z_air/√εeff（Z_air 纯几何）⇒ S_Z=−S_εeff/2",
    }


def dk_log_sensitivity_numeric(
    fn: Callable[[float], float],
    er: float,
    *,
    rel_step: float = 1e-4,
) -> float:
    """任意 εr-入口正值模型的中心差分对数敏感度 dlnf/dlnεr（O(h²)）。"""
    er_v = _positive(er, "er")
    h = _positive(rel_step, "rel_step")
    f_hi = float(fn(er_v * (1.0 + h)))
    f_lo = float(fn(er_v * (1.0 - h)))
    if not (f_hi > 0.0 and f_lo > 0.0):
        raise ValueError("模型输出必须为正（对数敏感度定义域）")
    return (math.log(f_hi) - math.log(f_lo)) / (2.0 * h)


def f_res_frozen_dl(l_mm: float, w_mm: float, er: float, h_mm: float,
                    dl_mm: float) -> float:
    """冻结 ΔL 的贴片谐振闭式 f=c/(2(L+2ΔL)√εeff)（恒等锚模型档）。"""
    l_p = _positive(l_mm, "l_mm")
    dl = _finite(dl_mm, "dl_mm")
    eps_eff = eps_eff_quasi_static(w_mm, h_mm, er)
    return _C_MM_GHZ / (2.0 * (l_p + 2.0 * dl) * math.sqrt(eps_eff))


# ─── 容差传播（线性 + MC 交叉）──────────────────────────────────────────────


def propagate_dk_tolerance(
    er: float,
    tol: float,
    model_fn: Callable[[float], float],
    *,
    n_mc: int = 10000,
    seed: int = 20261002,
) -> dict[str, Any]:
    """Dk ±tol → 模型输出量级的传播（线性一阶 + Monte Carlo 交叉）。

    Args:
        er: 名义 Dk。
        tol: 容差半宽（同单位）。
        model_fn: callable(er)->float（正输出：谐振频率 GHz / 阻抗 Ω 等）。
        n_mc: MC 样本数（均匀 Dk±tol）。
        seed: MC 种子（缺省=本批日期，可复现）。

    Returns:
        {nominal, s_numeric, linear_half_width, mc_half_width, mc_std,
        linear_std, mc_p05, mc_p95, agreement_half_width_rel,
        agreement_std_rel, n_mc, seed, method}
        agreement_*_rel = |linear−mc|/mc（线性一阶 vs 全模型 MC 的一致性；
        容差带窄时 ≪1%，是单测门不是物理常量）。
    """
    er_v = _positive(er, "er")
    tol_v = _finite(tol, "tol")
    if tol_v < 0.0:
        raise ValueError(f"tol 必须 ≥0，收到 {tol_v}")
    if n_mc < 2:
        raise ValueError(f"n_mc 须 ≥2，收到 {n_mc}")
    nominal = _positive(model_fn(er_v), "model_fn(er)")
    s = dk_log_sensitivity_numeric(model_fn, er_v)
    linear_hw = abs(s) * nominal * (tol_v / er_v)
    rng = np.random.default_rng(seed)
    samples = er_v + tol_v * (2.0 * rng.random(int(n_mc)) - 1.0)
    outs = np.array([float(model_fn(float(x))) for x in samples])
    mc_hw = float(np.max(np.abs(outs - nominal)))
    mc_std = float(np.std(outs, ddof=1))
    linear_std = abs(s) * nominal * tol_v / (er_v * math.sqrt(3.0))
    p05, p95 = (float(v) for v in np.percentile(outs, [5.0, 95.0]))
    agreement_hw = abs(linear_hw - mc_hw) / mc_hw if mc_hw > 0.0 else 0.0
    agreement_std = abs(linear_std - mc_std) / mc_std if mc_std > 0.0 else 0.0
    return {
        "nominal": nominal,
        "s_numeric": s,
        "linear_half_width": linear_hw,
        "mc_half_width": mc_hw,
        "mc_std": mc_std,
        "linear_std": linear_std,
        "mc_p05": p05,
        "mc_p95": p95,
        "agreement_half_width_rel": agreement_hw,
        "agreement_std_rel": agreement_std,
        "n_mc": int(n_mc),
        "seed": int(seed),
        "method": "linear first-order vs uniform Monte Carlo（dk±tol）",
    }


# ─── Design Dk 反推（FA3 平方法 + 全闭式交叉）───────────────────────────────


def back_out_design_dk(
    er_nominal: float, f_target_ghz: float, f_observed_ghz: float,
) -> float:
    """平方法反推 er_design=er·(f_target/f_obs)²（FA3 report §4 预声明口径）。

    语义：谐振位置法（#301 合规——只消费谷位非深度）。f_obs<f_target 时
    er_design>er_nominal（板比名义"慢"）。
    """
    er0 = _positive(er_nominal, "er_nominal")
    f_t = _positive(f_target_ghz, "f_target_ghz")
    f_o = _positive(f_observed_ghz, "f_observed_ghz")
    return er0 * (f_t / f_o) ** 2


def back_out_design_dk_full_cf(
    l_mm: float, w_mm: float, h_mm: float,
    er_nominal: float, f_observed_ghz: float,
    *,
    n_iter: int = 80,
) -> float:
    """全闭式自洽反解：er′ s.t. patch_resonance_hj_ghz(L,W,er′,h)=f_obs。

    bisection（f 单调递减于 εr，几何不变）；C10d verdict R1 的
    ``er_design_full_cf`` 口径（informational，非注册值）。
    """
    _positive(l_mm, "l_mm")
    _positive(w_mm, "w_mm")
    _positive(h_mm, "h_mm")
    er0 = _positive(er_nominal, "er_nominal")
    f_obs = _positive(f_observed_ghz, "f_observed_ghz")
    lo, hi = 0.5 * er0, 2.0 * er0
    if not (patch_resonance_hj_ghz(l_mm, w_mm, lo, h_mm) > f_obs
            > patch_resonance_hj_ghz(l_mm, w_mm, hi, h_mm)):
        raise ValueError(
            f"f_obs={f_obs} 不在 er∈[{lo},{hi}] 的模型值域内——反解无解")
    for _ in range(int(n_iter)):
        mid = 0.5 * (lo + hi)
        if patch_resonance_hj_ghz(l_mm, w_mm, mid, h_mm) > f_obs:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ─── 78GHz Design Dk 锚案例（C10d 语境）─────────────────────────────────────


def case_78ghz_design_dk(
    *,
    dk_tols: tuple[float, ...] = (0.04, 0.05),
    n_mc: int = 10000,
    seed: int = 20261002,
) -> dict[str, Any]:
    """78GHz RO3003「为什么必须 Design Dk 锚」的确定性量化（零仿真）。

    链路：旧名义 er=3.0 设计链自检（R4）→ 实测缺口（−2.31%）→ 容差带
    传播量级（线性+MC）→ 缺口/容差带比值 → 方法域 Dk 差与锚值互证。
    判定语义沿用 runs/ge6_anchor/criteria.md §2 门宽（1%/0.1%），如实
    输出布尔量与比值，不凑绿。

    Returns:
        {geometry, f_old_cf_ghz, r4_self_check_ok, f_dip_ghz, gap_pct,
        er_design_square_law, er_design_full_cf, square_vs_full_rel,
        f_pred_ghz, anchor_explains_gap(≤1%), s_f_full_hj, s_f_frozen_dl,
        sensitivity_split_rel, tolerance_bands: [{dk_tol, linear_half_width,
        mc_half_width, agreement_half_width_rel, gap_to_band_ratio,
        band_explains_gap}], design_domain_covers_78, web_tool_design_dk,
        web_tool_vs_anchor_rel, web_tool_vs_process_rel_pct,
        verdict, provenance}
    """
    g = C10D_CASE
    l_mm, w_mm, h_mm = g["l_mm"], g["w_mm"], g["h_mm"]
    er0, f0, f_dip = g["er_nominal"], g["f0_ghz"], g["f_dip_ghz"]
    # J1-3 改道：锚值消费期单源解析（活注册表优先，fallback=模块常量）
    anchor_res = resolve_anchor_er_design(f0)

    f_old = patch_resonance_hj_ghz(l_mm, w_mm, er0, h_mm)
    r4_ok = abs(f_old - f0) / f0 <= 1e-3  # criteria §2 R4 门宽
    gap_pct = (f_dip - f0) / f0 * 100.0
    er_sq = back_out_design_dk(er0, f0, f_dip)
    er_cf = back_out_design_dk_full_cf(l_mm, w_mm, h_mm, er0, f_dip)
    square_vs_full = abs(er_cf - er_sq) / er_sq  # criteria §2 R1 门宽 1%
    f_pred = patch_resonance_hj_ghz(l_mm, w_mm, er_sq, h_mm)
    anchor_ok = abs(f_pred - f_dip) / f_dip <= 0.01  # criteria §2 R3 主门

    # 敏感度：全裁判链（ΔL 非线性）数值档 + 冻结 ΔL 闭式恒等档
    def model(er: float) -> float:
        return patch_resonance_hj_ghz(l_mm, w_mm, er, h_mm)

    s_full = dk_log_sensitivity_numeric(model, er0)

    def _dl(er: float) -> float:
        ee = eps_eff_quasi_static(w_mm, h_mm, er)
        return (0.824 * h_mm * (ee + 0.3) * (w_mm / h_mm + 0.264)
                / ((ee - 0.258) * (w_mm / h_mm + 0.8)))

    # 冻结 ΔL 档：f=c/(2(L+2ΔL₀)√εeff) 的数值敏感度（模型内构造性恒等
    # =z0_sensitivity_closed_form 的 −0.5·S_εeff，单测互证）
    dl0 = _dl(er0)
    s_frozen = dk_log_sensitivity_numeric(
        lambda er: f_res_frozen_dl(l_mm, w_mm, er, h_mm, dl0), er0)
    sens_split = abs(s_full - s_frozen) / abs(s_frozen)

    bands = []
    for tol in dk_tols:
        t = _positive(tol, "dk_tol")
        prop = propagate_dk_tolerance(
            er0, t, model, n_mc=n_mc, seed=seed)
        ratio = abs(f_dip - f0) / prop["mc_half_width"]
        bands.append({
            "dk_tol": t,
            "linear_half_width_ghz": prop["linear_half_width"],
            "mc_half_width_ghz": prop["mc_half_width"],
            "agreement_half_width_rel": prop["agreement_half_width_rel"],
            "gap_to_band_ratio": ratio,
            "band_explains_gap": bool(abs(f_dip - f0) <= prop["mc_half_width"]),
        })

    # 库面互证（同层 import material_library——datasheet 域与冲突注记）
    from rfauto.core.material_library import VENDOR_LAMINATES

    ro = VENDOR_LAMINATES["rogers_ro3003"]
    band_ghz = ro["dk_design"]["f_band_ghz"]
    covers = bool(band_ghz[0] <= f0 <= band_ghz[1])
    web_tool_dk = 3.1629  # rogerscorp.com RO3003 属性表 Design 档（2026-10-02）
    return {
        "geometry": {"l_mm": l_mm, "w_mm": w_mm, "h_mm": h_mm,
                     "er_nominal": er0, "f0_ghz": f0},
        "f_old_cf_ghz": f_old,
        "r4_self_check_ok": r4_ok,
        "f_dip_ghz": f_dip,
        "gap_pct": gap_pct,
        "gap_ghz": abs(f_dip - f0),
        "er_design_square_law": er_sq,
        "er_design_full_cf": er_cf,
        "square_vs_full_rel": square_vs_full,
        "f_pred_ghz": f_pred,
        "anchor_explains_gap": anchor_ok,
        "s_f_full_hj": s_full,
        "s_f_frozen_dl": s_frozen,
        "sensitivity_split_rel": sens_split,
        "tolerance_bands": bands,
        "design_domain_covers_78": covers,
        "web_tool_design_dk": web_tool_dk,
        "web_tool_vs_anchor_rel": abs(web_tool_dk - er_sq) / er_sq,
        "web_tool_vs_process_rel_pct": (web_tool_dk - 3.00) / 3.00 * 100.0,
        "anchor_id": g["anchor_id"],
        "anchor_er_design": anchor_res["value"],
        "anchor_source": anchor_res["source"],
        "anchor_status": g["anchor_status"],
        "verdict": (
            "process 容差带（±0.04/±0.05）对 78GHz 谐振的传播量级 "
            f"~±{bands[0]['mc_half_width_ghz']:.2f} GHz，实测缺口 "
            f"{abs(f_dip - f0):.2f} GHz（{gap_pct:.2f}%）≈ 容差带的 "
            f"{bands[0]['gap_to_band_ratio']:.1f} 倍——制造容差解释不了；"
            "方法域 Dk 差（process vs circuit ~5%，库内冲突注记+官网工具 "
            "Design 3.1629 实证）是主项，故 78GHz 必须电路域 Design Dk 锚"
            "（datasheet design 域 8–40 GHz 不覆盖 78，外推禁用）"
        ),
        "provenance": g["provenance"],
    }
