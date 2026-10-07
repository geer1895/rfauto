"""k/Qe 标定键（模分裂 k 与群时延 Qe，df6 A1 R4）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .cm_extract import _cm_as_complex
from .registry import register_calculator

# ─── k/Qe 标定键（df6 A1 R4 产品化，2026-09-25；签名出处
# runs/df6_a1_r4/calculator_signatures.md；内核与 scripts/df6_a1_r4_runner.py
# 提取面同式移植——test_kqe_registry_keys 跨实现互证钉防漂移）───────────────

_KSPLIT_RULE = {
    # 先于运行写死；prominence 与 HFSS 锚 analyze_driven_s2p 同款
    # （出处 scripts/hairpin_alt_ksplit.py KSPLIT_RULE，hairpin 先例）
    "prominence_db": 0.5,
    "neighborhood_ghz": 0.3,
    "level_floor_db": 15.0,
    "valley_resolved_db": 3.0,
}


def _ksplit_find_mode_pair(freq_hz: Any, s21_db: Any) -> dict:
    """|S21| dB 曲线通带邻域模对查找（KSPLIT_RULE；确定性）。"""
    from scipy.signal import find_peaks

    f = np.asarray(freq_hz, dtype=float)
    db = np.asarray(s21_db, dtype=float)
    if f.shape != db.shape or f.ndim != 1 or f.size < 5:
        raise ValueError("freq_hz/s21_db 须为等长一维且 ≥5 点")
    i_main = int(np.argmax(db))
    f_main = float(f[i_main])
    pk, props = find_peaks(db, prominence=float(_KSPLIT_RULE["prominence_db"]))
    prom_by_idx = {int(i): float(v) for i, v in
                   zip(pk, props["prominences"], strict=True)}
    cand = [int(i) for i in pk
            if abs(float(f[i]) - f_main) <= float(_KSPLIT_RULE["neighborhood_ghz"]) * 1e9
            and float(db[i]) >= float(db[i_main]) - float(_KSPLIT_RULE["level_floor_db"])]
    cands = [{"f_ghz": float(f[i]) / 1e9, "level_db": float(db[i]),
              "prominence_db": prom_by_idx[i]} for i in cand]
    out: dict = {"n_candidates": len(cand), "candidates": cands,
                 "f1_ghz": None, "f2_ghz": None, "level1_db": None,
                 "level2_db": None, "valley_depth_db": None,
                 "quality": "single_peak"}
    if len(cand) < 2:
        return out
    lo, hi = sorted(sorted(cand, key=lambda i: prom_by_idx[i], reverse=True)[:2])
    valley = float(db[lo:hi + 1].min())
    depth = float(min(db[lo], db[hi]) - valley)
    out.update({
        "f1_ghz": float(f[lo]) / 1e9, "f2_ghz": float(f[hi]) / 1e9,
        "level1_db": float(db[lo]), "level2_db": float(db[hi]),
        "valley_depth_db": depth,
        "quality": ("resolved" if depth >= float(_KSPLIT_RULE["valley_resolved_db"])
                    else "shallow_valley")})
    return out


def _ksplit_parabolic_refine(f: Any, y: Any, i: int) -> float:
    """三点抛物线顶点（log|S| 域峰位细化）；边界/退化回退网格点。"""
    f = np.asarray(f, dtype=float)
    y = np.asarray(y, dtype=float)
    if i <= 0 or i >= len(f) - 1:
        return float(f[i])
    d0, d1, d2 = float(y[i - 1]), float(y[i]), float(y[i + 1])
    den = d0 - 2.0 * d1 + d2
    if den == 0.0:
        return float(f[i])
    off = 0.5 * (d0 - d2) / den
    if not -1.0 < off < 1.0:
        return float(f[i])
    return float(f[i] + off * (f[i + 1] - f[i]))


def _ksplit_bias_invert(k_raw: float, raw_grid: Any, true_grid: Any) -> float:
    """合成偏置曲线逆映射（log-log 内插——偏置近幂律；线性域曲率实测
    致 midnode 回收 7.6% 偏差，#118 数值裁判弃线性域内插）。"""
    rg = np.log(np.asarray(raw_grid, dtype=float))
    tg = np.log(np.asarray(true_grid, dtype=float))
    if rg.size < 2 or not bool(np.all(np.diff(rg) > 0)):
        raise ValueError("偏置曲线 raw 栅格须严格递增")
    return float(math.exp(float(np.interp(math.log(k_raw), rg, tg))))


@register_calculator(
    "k_split_pair",
    "双峰模分裂耦合系数（Hong & Lancaster 精确式 k=(f2²−f1²)/(f2²+f1²)，"
    "df6 A1 R4）：|S21| dB 双主峰抛物线细化+KSPLIT_RULE 峰检（prominence "
    "0.5dB HFSS 锚同款+通带邻域守卫）；偏置曲线 log-log 逆映射修正；双峰不"
    "可分如实 None（#122）",
    (("freq_hz", "ndarray Hz 升序扫频栅格"),
     ("s21", "ndarray complex 复 S21（等长）"),
     ("bias_raw_grid", "list|None 偏置曲线 raw k 节点（缺省 None 不修正）"),
     ("bias_true_grid", "list|None 对应 true k 节点")),
    required=("freq_hz", "s21"),
)
def k_split_pair(freq_hz: Any, s21: Any,
                 bias_raw_grid: Any = None,
                 bias_true_grid: Any = None) -> dict:
    """双峰模分裂耦合系数（Hong & Lancaster 精确式；df6 A1 R4）。

    k=(f2²−f1²)/(f2²+f1²)，f1<f2 为 |S21| dB 双主峰（抛物线细化）；峰检
    KSPLIT_RULE（prominence 0.5dB HFSS 锚同款+通带邻域两守卫）。双峰不可分
    → k_raw/k_corr=None（如实不硬提，#122）。k_corr=偏置曲线 log-log 逆映射
    修正值（bias_*_grid 缺省 None 时与 k_raw 相等）；窄带近似只作旁证列。
    """
    f = np.asarray(freq_hz, dtype=float)
    g = _cm_as_complex(s21, "s21", f.size)
    db = 20.0 * np.log10(np.abs(g) + 1e-12)
    pair = _ksplit_find_mode_pair(f, db)
    out: dict = {"pair": pair, "f1_ghz": None, "f2_ghz": None,
                 "k_raw": None, "k_corr": None, "k_narrowband": None,
                 "valley_db": pair.get("valley_depth_db"),
                 "quality": pair.get("quality", "single_peak")}
    if pair["f1_ghz"] is None or pair["f2_ghz"] is None:
        return out
    i1 = int(np.argmin(np.abs(f - pair["f1_ghz"] * 1e9)))
    i2 = int(np.argmin(np.abs(f - pair["f2_ghz"] * 1e9)))
    fr1 = _ksplit_parabolic_refine(f, db, i1)
    fr2 = _ksplit_parabolic_refine(f, db, i2)
    f1, f2 = sorted((fr1, fr2))
    if f1 <= 0.0 or f2 <= f1:
        return out
    k = (f2 * f2 - f1 * f1) / (f2 * f2 + f1 * f1)
    out.update({"f1_ghz": f1 / 1e9, "f2_ghz": f2 / 1e9,
                "k_raw": float(k),
                "k_narrowband": float(2.0 * (f2 - f1) / (f2 + f1))})
    if out["k_raw"] is not None and bias_raw_grid is not None             and bias_true_grid is not None:
        out["k_corr"] = _ksplit_bias_invert(out["k_raw"], bias_raw_grid,
                                            bias_true_grid)
    elif out["k_raw"] is not None:
        out["k_corr"] = out["k_raw"]
    return out


@register_calculator(
    "qe_group_delay",
    "单谐振器外部 Q 群时延法（Dishal/Hong 反射单端口径，df6 A1 R4）："
    "τ(f)=A/(1+((f−f0)/w)²)+D 四参数 Lorentzian+基线拟合；无耗单端口 "
    "τmax=4Qe/ω0 ⇒ 缺省 c=4（合成回收 3.9972；/2 口径否决，DP-2 互证）",
    (("freq_hz", "ndarray Hz 升序扫频栅格"),
     ("s11", "ndarray complex 复 S11（单载反射）"),
     ("c", "float - τ→Qe 常数（缺省 4.0；对称双馈 S21 口径配 1.0）")),
    required=("freq_hz", "s11"),
)
def qe_group_delay(freq_hz: Any, s11: Any, c: float = 4.0) -> dict:
    """单谐振器外部 Q 群时延法（Dishal/Hong 反射单端口径；df6 A1 R4）。

    τ(f)=A/(1+((f−f0)/w)²)+D 四参数 Lorentzian+基线拟合（D 吸收馈线往返
    时延+基线；带缘斜率法被谐振器电抗斜率污染实测 3.2×，禁用）。无耗单端
    口理论 τmax=4Qe/ω0 ⇒ **缺省 c=4**（合成回收实测 3.9972，
    runs/df6_a1_r4/selftest_result.json；"/2"口径否决——DP-2 轨独立互证同
    裁决）；对称双馈 S21 口径 τmax=2Q_L/ω0 配 c=1.0（仅记录）。Qe=A·ω0/c。
    """
    from scipy.optimize import curve_fit

    f = np.asarray(freq_hz, dtype=float)
    s = _cm_as_complex(s11, "s11", f.size)
    ph = np.unwrap(np.angle(s))
    tau = -np.gradient(ph, 2.0 * np.pi * f)
    i = int(np.argmax(tau))
    f0_hz = float(f[i])
    span = f[-1] - f[0]
    far = tau[(f <= f[0] + 0.2 * span) | (f >= f[-1] - 0.2 * span)]
    d0 = float(np.median(far))
    a0 = max(float(tau[i]) - d0, 1e-15)
    p0 = [a0, f0_hz, max(3.0e6, 0.02 * f0_hz), d0]

    def _model(ff, a, fc, w, d):
        return a / (1.0 + ((ff - fc) / w) ** 2) + d

    popt, _ = curve_fit(_model, f, tau, p0=p0, maxfev=20000)
    a_fit, fc_fit, w_fit, d_fit = (float(v) for v in popt)
    # 规范化 (A,w)→(-A,-w) 镜像简并（模型对该变换不变，curve_fit 随机落边）：
    # 一律收窄到 w>0，a_fit 的符号才是物理符号（群时延瓣方向）。
    if w_fit < 0:
        a_fit, w_fit = -a_fit, -w_fit
    if w_fit == 0:
        raise ValueError("Lorentzian 拟合宽度退化（数据无谐振特征）")
    # 符号感知（2026-09-25 df6 A1 真机实证）：实测 S11 谐振群时延瓣可为负
    # （馈线相位旋转约定），Qe 由 |A| 定义、符号如实入 sign 字段不硬凑。
    resid = float(np.max(np.abs(tau - _model(f, *popt))))
    qe = abs(a_fit) * 2.0 * math.pi * fc_fit / float(c)
    if qe <= 0:
        raise ValueError("Qe 非正（拟合退化，数据无可用谐振特征）")
    return {"tau_max_s": float(tau[i]), "a_fit_s": a_fit,
            "f_res_ghz": fc_fit / 1e9, "w_fit_hz": w_fit, "d_fit_s": d_fit,
            "fit_max_resid_s": resid,
            "qe": qe,
            "sign": 1 if a_fit > 0 else -1,
            "c": float(c)}
