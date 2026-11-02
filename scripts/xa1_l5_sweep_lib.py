"""XA-1 语义终裁·L5 扫频差分批·纯核（拟合/判读/座位设计/合成器）。

判据面 = runs/xa1_arbitration/l5_sweep/criteria.md（#122 判据先行，发射前
冻结；本模块是其可执行镜像——阈值常量与判据文本逐条对应，改动须同笔）。

背景（#222 接前席 runs/xa1_arbitration/xa1_arbitration_evidence.json
INCONCLUSIVE）：单点锚 K=f_dip·L 的 ±5% 不确定度吞掉两语义差（0.02%）。
扫频差分法：同一 W 档扫 5 点贴片长 L，逐座测引擎谷位 f_dip(L)，模型
Y=c0/(2·f_dip) = √εeff·(L+X) 对 L **恒等线性**——OLS 斜率=√εeff_eff、
截距=√εeff·X，X̂=截距/斜率与 εeff 模型误差无关（二维量一次回归同时解出）。

数值只在确定性内核（铁律 7）：本模块全部函数纯 numpy/闭式，无随机性
（合成器显式 seed）；LLM/agent 不产生物理数字。

合成回收钉（#340 范式）：`synthesize_sweep` 按 A/B 语义造合成谷位 →
`judge_sweep` 必须判回同语义——判读函数独立测试
（tests/unit/test_xa1_l5_sweep.py），防止"裁判先射箭后画靶"。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# ── 冻结常量（与 criteria.md 逐条对应）────────────────────────────────────

C0_MM_GHZ = 299.792458          # mm·GHz（光速，core/synthesis 同值口径）
ER = 3.66                        # _DEFAULT_SUB rogers4350b
H_MM = 0.508
TAN_D = 0.0037
F_DESIGN_GHZ = 2.4               # W 档设计频率（closedform.array_elem_w_mm 口径）
RIN_T_OHM = 50.0                 # 馈电目标阻抗（系统阻抗）

L_POINTS: tuple[float, ...] = (30.0, 35.0, 40.0, 45.0, 50.0)
X_MID_N_DL = 3.0                 # f_exp 语义无关中心 = 3ΔL（A/B 中点）
BAND_LO_RATIO = 0.88             # 座位频带 = f_exp × [0.88, 1.12]
BAND_HI_RATIO = 1.12

X_BAND_HALF_MM = 0.20            # 判定带半宽 = 0.4×语义差（冻结 0.2，带间不重叠）
MAX_CI95_HALF_MM = 0.10          # 拟合质量门：CI95 半宽上限
MIN_SEATS = 4                    # 拟合质量门：有效座位数下限
MIN_SPAN_MM = 15.0               # 拟合质量门：有效座位 L 跨度下限
EPS_EFF_SANITY = (0.85, 1.15)    # εeff_fit / εeff_qs 完整性带（防错模归属）
Z95 = 1.959963984540054          # 双侧 95% 正态分位

DIP_MAX_DB = -6.0                # 谷门：谷深上限（匹配失败/无谷剔座）
DIP_EDGE_MARGIN = 0.05           # 谷门：argmin 距带缘 ≥5% 带宽（interior）

SEAT_NAME_FMT = "l{:03d}"


# ── 目标值（单源消费，禁改面只读）──────────────────────────────────────────

def arbitration_targets() -> dict[str, Any]:
    """A/B 语义目标值（W=40.9168 档；单源=core.synthesis.
    patch_fringing_delta_l 经 oe_templates.closedform._array_patch_eps_dl，
    数值与前席 xa1_arbitration_evidence.json criterion1 逐位一致）。

    返回 dict：w_mm/eps_eff_qs/delta_l_edge_mm/x_a_mm(=2ΔL)/x_b_mm(=4ΔL)/
    gap_mm/band_half_mm/band_a/band_b/no_man_land（区间 tuple，mm）。
    """
    from rfauto.adapters.oe_templates.closedform import (
        _array_patch_eps_dl,
        array_elem_w_mm,
    )

    w_mm = float(array_elem_w_mm(F_DESIGN_GHZ, ER))
    eps_eff_qs, x_a_mm = _array_patch_eps_dl(w_mm, ER, H_MM)
    # _array_patch_eps_dl 的 dl = 2×patch_fringing_delta_l = 两边缘合计 = X_A；
    # X_B = 调用侧再 ×2（三副本现行口径，前席证据 JSON 语义 B）。
    x_a_mm = float(x_a_mm)
    delta_l_edge_mm = x_a_mm / 2.0
    x_b_mm = 2.0 * x_a_mm
    lo_a, hi_a = x_a_mm - X_BAND_HALF_MM, x_a_mm + X_BAND_HALF_MM
    lo_b, hi_b = x_b_mm - X_BAND_HALF_MM, x_b_mm + X_BAND_HALF_MM
    return {
        "w_mm": w_mm,
        "eps_eff_qs": float(eps_eff_qs),
        "delta_l_edge_mm": delta_l_edge_mm,
        "x_a_mm": x_a_mm,
        "x_b_mm": x_b_mm,
        "gap_mm": x_b_mm - x_a_mm,
        "band_half_mm": X_BAND_HALF_MM,
        "band_a": (lo_a, hi_a),
        "band_b": (lo_b, hi_b),
        "no_man_land": (hi_a, lo_b),
    }


# ── 座位设计（criteria.md §二 座位表的可执行源）──────────────────────────

def seat_name(l_mm: float) -> str:
    return SEAT_NAME_FMT.format(round(l_mm))


def design_seats(l_points: tuple[float, ...] | list[float] = L_POINTS) -> list[dict[str, Any]]:
    """逐座位设计（纯闭式，零渲染）：L 档 → f_exp/频带/馈偏/渲染参数。

    f_exp = c0/(2·(L+3ΔL)·√εeff_qs)（语义无关中心）；频带 = f_exp×[0.88,1.12]
    （A/B 语义偏移最大 ±0.80%，距带缘 ≥8 个频栅步）；feed_offset =
    (L/π)·arcsin√(Rin_t/Rin_edge(f_exp))（synthesis.patch_rin_edge_balanis
    闭式，只影响匹配深度）；params 直通 render_script("patch", …)。
    越域守卫：Rin_edge<Rin_t 或 off≥L/2 显式 ValueError（不外推，#122）。
    """
    from rfauto.core.synthesis import patch_rin_edge_balanis

    targets = arbitration_targets()
    ee = targets["eps_eff_qs"]
    x_mid = X_MID_N_DL * targets["delta_l_edge_mm"]
    seats: list[dict[str, Any]] = []
    for l_mm in l_points:
        l_mm = float(l_mm)
        if not l_mm > 0.0:
            raise ValueError(f"L 档须正，得 {l_mm!r}")
        f_exp = C0_MM_GHZ / (2.0 * (l_mm + x_mid) * math.sqrt(ee))
        f_a = C0_MM_GHZ / (2.0 * (l_mm + targets["x_a_mm"]) * math.sqrt(ee))
        f_b = C0_MM_GHZ / (2.0 * (l_mm + targets["x_b_mm"]) * math.sqrt(ee))
        rin_edge = float(patch_rin_edge_balanis(targets["w_mm"], H_MM, f_exp))
        if not rin_edge > RIN_T_OHM:
            raise ValueError(
                f"L={l_mm}: Rin_edge={rin_edge:.1f}Ω ≤ 目标 {RIN_T_OHM}Ω——"
                "馈点不可达（越域不外推）")
        off = (l_mm / math.pi) * math.asin(math.sqrt(RIN_T_OHM / rin_edge))
        if not off < l_mm / 2.0:
            raise ValueError(f"L={l_mm}: feed_offset={off:.3f} 越出 ±L/2")
        band = (BAND_LO_RATIO * f_exp, BAND_HI_RATIO * f_exp)
        seats.append({
            "name": seat_name(l_mm),
            "l_mm": l_mm,
            "w_mm": targets["w_mm"],
            "f_exp_ghz": f_exp,
            "band_ghz": band,
            "feed_offset_mm": off,
            "rin_edge_ohm": rin_edge,
            "f_sem_ghz": {"a": f_a, "b": f_b},
            "params": {
                "patch_len_mm": round(l_mm, 4),
                "patch_w_mm": round(targets["w_mm"], 4),
                "feed_offset_mm": round(off, 4),
            },
        })
    return seats


# ── 谷位提取与谷门（criteria.md §四 座位有效性门·谷门）───────────────────

def extract_dip(freq_ghz: Any, s11_complex: Any) -> tuple[float, dict[str, Any]]:
    """单座谷位提取（单源=service.wp39_benchmark.locate_dip_ghz）。

    |S11|(dB) → argmin + 三点抛物线插值细分；返回 (f_dip_ghz, meta)
    （meta: argmin_ghz/dip_db/refined/n_points）。惰性 import 保本模块
    零 rfauto 顶层依赖（纯核可独立消费）。
    """
    from rfauto.service.wp39_benchmark import locate_dip_ghz

    f = np.asarray(freq_ghz, dtype=float)
    s = np.asarray(s11_complex)
    if s.ndim != 1 or s.shape != f.shape:
        raise ValueError(
            f"freq/s11 形状不一致：{f.shape} vs {s.shape}（须同长 1 维）")
    if not np.all(np.isfinite(s)):
        raise ValueError("S11 含非有限值（数据损坏，如实拒绝提取）")
    s11_db = 20.0 * np.log10(np.abs(s) + 1e-12)
    return locate_dip_ghz(f, s11_db)


def dip_gates(dip_meta: dict[str, Any], band_ghz: tuple[float, float],
              *, max_dip_db: float = DIP_MAX_DB,
              edge_margin: float = DIP_EDGE_MARGIN) -> dict[str, Any]:
    """谷门（纯函数）：refined 抛物线生效 + interior 距带缘 ≥5% 带宽 +
    深度 ≤ max_dip_db。任一不过 = 座位剔除（criteria §四），reasons 明细。

    dip_meta = extract_dip/locate_dip_ghz 的 meta（argmin_ghz/dip_db/refined）。
    """
    lo, hi = float(band_ghz[0]), float(band_ghz[1])
    span = hi - lo
    argmin = float(dip_meta["argmin_ghz"])
    dip_db = float(dip_meta["dip_db"])
    refined = bool(dip_meta.get("refined"))
    interior = bool(lo + edge_margin * span <= argmin <= hi - edge_margin * span)
    deep_enough = bool(dip_db <= max_dip_db)
    reasons: list[str] = []
    if not refined:
        reasons.append("谷位在采样端点或曲率非极小（refined=False，插值未生效）")
    if not interior:
        reasons.append(
            f"argmin={argmin:.5f}GHz 距带缘 <{edge_margin:.0%} 带宽 "
            f"（带 [{lo:.5f},{hi:.5f}]，截断伪谷嫌疑 #262 族）")
    if not deep_enough:
        reasons.append(f"谷深 {dip_db:.2f}dB > {max_dip_db}dB（匹配失败/无谷）")
    return {"refined": refined, "interior": interior,
            "deep_enough": deep_enough, "ok": not reasons,
            "reasons": reasons}


# ── 拟合（criteria.md §三 冻结模型）──────────────────────────────────────

def fit_x_total(l_mm_seq: Any, f_dip_ghz_seq: Any) -> dict[str, Any]:
    """L5 差分拟合：Y=c0/(2·f_dip)=√εeff·(L+X) 对 L 的 OLS 线性反演。

    斜率 m=√εeff_eff、截距 b=m·X → X̂=b/m（与 εeff 模型误差无关）；
    CI95 = delta 法：(m,b) OLS 协方差 C=σ̂²(XᵀX)⁻¹，
    Var(X̂)=C_bb/m² + b²·C_mm/m⁴ − 2·b·C_mb/m³。
    退化输入（<2 点/零跨度/m≤0）显式 ValueError，不外推。

    返回 dict：x_hat_mm/ci95_half_mm/eps_eff_fit/slope_m/intercept_b/
    resid_rms_mm/n/span_mm/points（逐点 Y 实测与拟合值，审计用）。
    """
    l_arr = np.asarray(l_mm_seq, dtype=float)
    f = np.asarray(f_dip_ghz_seq, dtype=float)
    if l_arr.ndim != 1 or f.ndim != 1 or l_arr.shape != f.shape \
            or l_arr.size < 2:
        raise ValueError(
            f"拟合输入须同长 1 维且 ≥2 点，得 {l_arr.shape}/{f.shape}")
    if not (np.all(np.isfinite(l_arr)) and np.all(np.isfinite(f))):
        raise ValueError("拟合输入含非有限值")
    if not np.all(f > 0.0):
        raise ValueError("f_dip 须全正")
    span = float(l_arr.max() - l_arr.min())
    if span <= 0.0:
        raise ValueError("L 零跨度（差分法不可辨识）")
    y = C0_MM_GHZ / (2.0 * f)
    n = int(l_arr.size)
    x_mean = float(l_arr.mean())
    y_mean = float(y.mean())
    sxx = float(((l_arr - x_mean) ** 2).sum())
    sxy = float(((l_arr - x_mean) * (y - y_mean)).sum())
    m = sxy / sxx
    b = y_mean - m * x_mean
    if not m > 0.0:
        raise ValueError(f"OLS 斜率 m={m!r} ≤ 0（√εeff 须正——数据非 TM10 形态）")
    resid = y - (m * l_arr + b)
    dof = n - 2
    sigma2 = float((resid ** 2).sum() / dof) if dof > 0 else 0.0
    # C = sigma2 * inv(XᵀX)，X=[L,1]：C_mm=sigma2/sxx、C_bb=sigma2(1/n+x̄²/sxx)、
    # C_mb=-sigma2·x̄/sxx（OLS 标准闭式）
    c_mm = sigma2 / sxx
    c_bb = sigma2 * (1.0 / n + x_mean ** 2 / sxx)
    c_mb = -sigma2 * x_mean / sxx
    var_x = c_bb / m ** 2 + (b ** 2) * c_mm / m ** 4 - 2.0 * b * c_mb / m ** 3
    var_x = max(float(var_x), 0.0)     # 数值负守卫（delta 法理论非负）
    x_hat = b / m
    return {
        "x_hat_mm": float(x_hat),
        "ci95_half_mm": float(Z95 * math.sqrt(var_x)),
        "eps_eff_fit": float(m * m),
        "slope_m": float(m),
        "intercept_b": float(b),
        "resid_rms_mm": float(math.sqrt(float((resid ** 2).mean()))),
        "n": n,
        "span_mm": span,
        "points": [
            {"l_mm": float(li), "y_mm": float(yi), "y_fit_mm": float(m * li + b)}
            for li, yi in zip(l_arr, y, strict=True)
        ],
    }


# ── 判读（criteria.md §四 冻结判定；§340 合成回收钉的被测面）───────────────

def judge_sweep(records: list[dict[str, Any]],
                targets: dict[str, Any] | None = None) -> dict[str, Any]:
    """L5 扫频终判（纯函数；verdict ∈ {"A","B","INCONCLUSIVE"}）。

    records = 逐座 {"name","l_mm","ok":bool,"f_dip_ghz":float|None,
    "status":str,"reason":str}（座位有效性门在驱动面完成，本函数只认
    ok 位）。判据顺序（criteria §四 冻结）：
      ① 质量门 1：有效座 ≥4 且跨度 ≥15mm；
      ② 拟合（退化=INCONCLUSIVE）；
      ③ 质量门 2/3：CI95 半宽 ≤0.1mm、εeff_fit ∈ [0.85,1.15]×εeff_qs；
      ④ 落带：CI95 全落 A 带判 A / 全落 B 带判 B / 否则 INCONCLUSIVE。
    任一不过如实 INCONCLUSIVE 并给 reasons 明细——绝不凑 A/B（#122）。
    """
    t = targets if targets is not None else arbitration_targets()
    reasons: list[str] = []
    valid = [r for r in records if r.get("ok") and r.get("f_dip_ghz")]
    seats_view = [
        {"name": r.get("name"), "l_mm": r.get("l_mm"),
         "status": r.get("status"),
         "f_dip_ghz": (float(r["f_dip_ghz"]) if r.get("f_dip_ghz") else None),
         "used_in_fit": bool(r.get("ok") and r.get("f_dip_ghz")),
         "reason": r.get("reason", "")}
        for r in records
    ]
    if not valid:
        return {"verdict": "INCONCLUSIVE",
                "reasons": ["无有效座位（数据面异常）——无法拟合，如实不判"],
                "seats": seats_view, "fit": None, "gates": {"g1_seats": False}}
    fit = None
    gates: dict[str, Any] = {}
    try:
        fit = fit_x_total([r["l_mm"] for r in valid],
                          [r["f_dip_ghz"] for r in valid])
    except ValueError as exc:
        reasons.append(f"拟合退化：{exc}")
        gates["g1_seats"] = True
        gates["g2_ci95"] = None
        gates["g3_eps_eff"] = None
        return {"verdict": "INCONCLUSIVE", "reasons": reasons,
                "seats": seats_view, "fit": None, "gates": gates}

    lo, hi = fit["x_hat_mm"] - fit["ci95_half_mm"], fit["x_hat_mm"] + fit["ci95_half_mm"]
    gates["g1_seats"] = bool(fit["n"] >= MIN_SEATS and fit["span_mm"] >= MIN_SPAN_MM)
    gates["g2_ci95"] = bool(fit["ci95_half_mm"] <= MAX_CI95_HALF_MM)
    eps_lo = EPS_EFF_SANITY[0] * t["eps_eff_qs"]
    eps_hi = EPS_EFF_SANITY[1] * t["eps_eff_qs"]
    gates["g3_eps_eff"] = bool(eps_lo <= fit["eps_eff_fit"] <= eps_hi)
    if not gates["g1_seats"]:
        reasons.append(
            f"质量门1 未过：有效座 {fit['n']}/{len(records)}（须 ≥{MIN_SEATS}）"
            f"、跨度 {fit['span_mm']:.1f}mm（须 ≥{MIN_SPAN_MM:g}）——欠功如实")
    if not gates["g2_ci95"]:
        reasons.append(
            f"质量门2 未过：CI95 半宽 {fit['ci95_half_mm']:.4f}mm > "
            f"{MAX_CI95_HALF_MM}mm——散布主导，差分法前提失效")
    if not gates["g3_eps_eff"]:
        reasons.append(
            f"质量门3 未过：εeff_fit={fit['eps_eff_fit']:.4f} 越出 "
            f"[{eps_lo:.4f},{eps_hi:.4f}]（量的疑似非 TM10 模）")
    verdict = "INCONCLUSIVE"
    if gates["g1_seats"] and gates["g2_ci95"] and gates["g3_eps_eff"]:
        a_lo, a_hi = t["band_a"]
        b_lo, b_hi = t["band_b"]
        in_a = bool(lo >= a_lo and hi <= a_hi)
        in_b = bool(lo >= b_lo and hi <= b_hi)
        gates["ci_in_band_a"] = in_a
        gates["ci_in_band_b"] = in_b
        if in_a and not in_b:
            verdict = "A"
            reasons.append(
                f"X̂={fit['x_hat_mm']:.4f}mm CI95=[{lo:.4f},{hi:.4f}] 全落 A 带 "
                f"[{a_lo:.4f},{a_hi:.4f}]（X=2ΔL 语义）")
        elif in_b and not in_a:
            verdict = "B"
            reasons.append(
                f"X̂={fit['x_hat_mm']:.4f}mm CI95=[{lo:.4f},{hi:.4f}] 全落 B 带 "
                f"[{b_lo:.4f},{b_hi:.4f}]（X=4ΔL 语义）")
        else:
            reasons.append(
                f"CI95=[{lo:.4f},{hi:.4f}] 未全落任一目标带 "
                f"（A [{a_lo:.4f},{a_hi:.4f}] / B [{b_lo:.4f},{b_hi:.4f}]）"
                "——骑带/落无人区，双落不裁如实 INCONCLUSIVE")
    return {"verdict": verdict, "reasons": reasons, "seats": seats_view,
            "fit": fit, "gates": gates}


# ── 合成器（#340 回收钉数据面；显式 seed 确定性）──────────────────────────

def synthesize_sweep(l_points: tuple[float, ...] | list[float],
                     x_true_mm: float, eps_eff: float,
                     *, noise_std_mm: float = 0.0,
                     seed: int | None = None) -> list[dict[str, Any]]:
    """按给定语义（x_true_mm, eps_eff）造合成逐座记录（真模型 + Y 域高斯
    噪声 mm 级，seed 确定性）。返回 judge_sweep records 形态
    （ok=True, f_dip_ghz=反演真模型）。噪声加在 Y=c0/(2f) 上等价于
    X 域同方差噪声（差分法噪声模型，criteria §三）。
    """
    if not x_true_mm > 0.0:
        raise ValueError(f"x_true_mm 须正，得 {x_true_mm!r}")
    if not eps_eff > 1.0:
        raise ValueError(f"eps_eff 须 >1，得 {eps_eff!r}")
    rng = np.random.default_rng(seed)
    records: list[dict[str, Any]] = []
    for l_mm in l_points:
        l_mm = float(l_mm)
        y_true = math.sqrt(eps_eff) * (l_mm + x_true_mm)
        noise = (float(rng.normal(0.0, noise_std_mm))
                 if noise_std_mm > 0 else 0.0)
        f_dip = C0_MM_GHZ / (2.0 * (y_true + noise))
        records.append({"name": seat_name(l_mm), "l_mm": l_mm, "ok": True,
                        "f_dip_ghz": float(f_dip), "status": "PASS",
                        "reason": ""})
    return records
