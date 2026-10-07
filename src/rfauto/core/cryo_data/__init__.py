"""MA-9 低温数据面：NIST 低温材料拟合表 + tanδ(T) 点带 + 积分量闭式。

规格：研究扩充 round17 §六 MA-9（低温数据面，
P2/M）——"tanδ(T) 点表（NIST/Krupka/Braginsky，band+single_source）+
∫κ(T)dT 热流与 ∫α dT 收缩（NIST 低温材料库免费表数字化）+低温焊料/
键合线 σ(T)"。数据包形态：data/nist_cryo_fits.json（NIST log10 多项式
拟合系数逐格转录，双源核对面见 JSON provenance）+ data/
tandelta_cryo_points.csv（本仓 cryo_materials 既有登记带承接，不新录
数字）+ 本加载器/积分器。纯函数叶子，零网络 IO、不进 calculators。

模块面
------
- ``load_nist_fits``：JSON 加载（provenance+fits dict）。
- ``eval_nist_fit``：logpoly（log10(y)=Σaᵢ(log10 T)ⁱ）与 poly（y=ΣaᵢTⁱ）
  求值；出温度范围 → clamp+extrapolated 标记（不静默）。
- ``integral_kappa``：∫_{T1}^{T2} κ(T)dT（复合 Simpson；物理量=单位
  截面单位梯度热流 W/m——热沉设计的直接设计量）。
- ``contraction_delta_l``：NIST linear_expansion 拟合是 ΔL/L 曲线
  （非 α）——收缩 = ΔL_native(T_ref)−ΔL_native(T)，原生单位如实报
  +公开带锚定的单位换算注记（native=1e-5 m/m，single_source 判定）。
- ``sigma_cu_ofhc``：Cu OFHC ρ(T) nΩ·m 拟合 → σ(T)（键合线/互连
  低温 σ(T) 面；焊料无 NIST 拟合——awaiting_data 不产数，如实登记）。
- ``tandelta_band``：tanδ(T) 点带表 log10(T) 线性插值（band 插值，
  产物显式标 interpolated）。

出处
----
1. round 文档：round17 §六 MA-9。
2. NIST Cryogenic Material Properties Database（Marquardt-Le-Radebaugh,
   Cryocoolers 11, 2002 pp.681-687 口径名，页码 UNVERIFIED）；系数逐格
   双源（cryocalc + CMB-S4 两仓转录，逐格一致性见 JSON provenance 与
   单测互证）。tanδ 带沿 cryo_materials 登记面（Krupka/OSTI 路线）。
"""
from __future__ import annotations

import csv
import json
import math
from itertools import pairwise
from pathlib import Path
from typing import Any

__all__ = [
    "NATIVE_EXPANSION_UNIT_FACTOR",
    "NIST_PROVENANCE",
    "contraction_delta_l",
    "eval_nist_fit",
    "integral_kappa",
    "load_nist_fits",
    "load_tandelta_points",
    "sigma_cu_ofhc",
    "tandelta_band",
]

_DATA = Path(__file__).parent / "data"
NATIVE_EXPANSION_UNIT_FACTOR = 1.0e-5  # 6061 ΔL/L 拟合原生单位（锚定判定）
NIST_PROVENANCE = (
    "NIST Cryogenic Material Properties Database（Marquardt-Le-Radebaugh "
    "Cryocoolers 11 口径名，页码 UNVERIFIED）；系数双源=circuitqed/"
    "cryocalc + CMB-S4/Cryogenic_Material_Properties（检索 2026-10-03，"
    "逐格一致性见 data/nist_cryo_fits.json provenance 与单测）"
)


def load_nist_fits() -> dict[str, Any]:
    """加载 NIST 拟合表（拷贝面）。"""
    with (_DATA / "nist_cryo_fits.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def eval_nist_fit(fit: dict[str, Any], t_k: Any) -> dict[str, Any]:
    """NIST 拟合单点求值（logpoly/poly 两型；出界 clamp+标记）。

    logpoly: log10(y) = Σ aᵢ·(log10 T)ⁱ；poly: y = Σ aᵢ·Tⁱ。
    返回 {value, extrapolated, t_range_k}。
    """
    t = _positive(t_k, "t_k")
    co = [float(c) for c in fit["coefficients"]]
    lo, hi = (float(x) for x in fit["t_range_k"])
    t_clamped = min(max(t, lo), hi)
    extrapolated = t < lo or t > hi
    if fit["type"] == "logpoly":
        x = math.log10(t_clamped)
        value = 10.0 ** math.fsum(c * x**i for i, c in enumerate(co))
    elif fit["type"] == "poly":
        value = math.fsum(c * t_clamped**i for i, c in enumerate(co))
    else:
        raise ValueError(f"未知拟合类型 {fit['type']!r}")
    return {"value": value, "extrapolated": extrapolated,
            "t_range_k": (lo, hi)}


def _simpson(f: Any, t1: float, t2: float, n: int = 400) -> float:
    """复合 Simpson 积分（n 偶数）。"""
    if n % 2 == 1:
        n += 1
    h = (t2 - t1) / n
    total = f(t1) + f(t2)
    for i in range(1, n):
        weight = 4.0 if i % 2 == 1 else 2.0
        total += weight * f(t1 + i * h)
    return total * h / 3.0


def integral_kappa(fit_key: str, t1_k: Any, t2_k: Any,
                   fits: dict[str, Any] | None = None) -> dict[str, Any]:
    """∫κ(T)dT（W/m）——单位截面单位温度梯度热流（热沉设计量）。

    κ 拟合须为 thermal_conductivity_w_m_k 型；T1<T2（反向积分取负号
    如实处理：∫_{T1}^{T2} = −∫_{T2}^{T1}）。独立裁判=scipy.quad（测试）。
    """
    db = fits if fits is not None else load_nist_fits()["fits"]
    if fit_key not in db:
        raise ValueError(f"未知拟合键 {fit_key!r}；可选 {sorted(db)}")
    fit = db[fit_key]
    if fit["property"] != "thermal_conductivity_w_m_k":
        raise ValueError(f"{fit_key} 非 thermal_conductivity 拟合")
    t1 = _positive(t1_k, "t1_k")
    t2 = _positive(t2_k, "t2_k")
    if t1 == t2:
        return {"integral_w_m": 0.0, "sign_flipped": False}
    sign = 1.0
    a, b = t1, t2
    if t1 > t2:
        a, b = t2, t1
        sign = -1.0
    clamped = lambda t: min(max(t, fit["t_range_k"][0]), fit["t_range_k"][1])  # noqa: E731
    val = _simpson(lambda t: eval_nist_fit(fit, clamped(t))["value"], a, b)
    return {"integral_w_m": sign * val,
            "sign_flipped": t1 > t2,
            "extrapolated": (t1 < fit["t_range_k"][0]
                             or t2 > fit["t_range_k"][1])}


def contraction_delta_l(fit_key: str, t_ref_k: Any, t_k: Any,
                        fits: dict[str, Any] | None = None) -> dict[str, Any]:
    """∫α dT 收缩量 = ΔL_native(T_ref) − ΔL_native(T)（原生单位）。

    NIST linear_expansion 拟合直接给 ΔL/L 曲线（非 α 本身）——积分
    面以曲线差实现（数学恒等）。原生单位 1e-5 m/m（6061 锚定判定，
    single_source），同时给出换算后的无量纲值。
    """
    db = fits if fits is not None else load_nist_fits()["fits"]
    if fit_key not in db:
        raise ValueError(f"未知拟合键 {fit_key!r}；可选 {sorted(db)}")
    fit = db[fit_key]
    if fit["property"] != "delta_l_over_l_native":
        raise ValueError(f"{fit_key} 非 delta_l_over_l_native 拟合")
    tr = _positive(t_ref_k, "t_ref_k")
    t = _positive(t_k, "t_k")
    dl_ref = eval_nist_fit(fit, tr)["value"]
    dl_t = eval_nist_fit(fit, t)["value"]
    native = dl_ref - dl_t
    return {
        "native": native,
        "native_unit": "1e-5 m/m（293→4K≈0.414% 公开带锚定，"
                       "single_source 判定）",
        "dimensionless": native * NATIVE_EXPANSION_UNIT_FACTOR,
    }


def sigma_cu_ofhc(t_k: Any, fits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cu OFHC（general）σ(T)：ρ 拟合（nΩ·m）→ σ（S/m）。键合线/互连面。

    焊料（SnPb/SAC）无 NIST 拟合——awaiting_data 不产数（如实，规格
    no-go"厂商多批次不产数"延续）。
    """
    db = fits if fits is not None else load_nist_fits()["fits"]
    out = eval_nist_fit(db["cu_ofhc_resistivity"], t_k)
    rho_nohm_m = out["value"]
    sigma = 1.0 / (rho_nohm_m * 1e-9)
    return {"sigma_s_per_m": sigma, "rho_nohm_m": rho_nohm_m,
            "extrapolated": out["extrapolated"], "note": (
                "焊料 σ(T) 无 NIST 拟合——awaiting_data 不产数（如实）")}


def load_tandelta_points() -> list[dict[str, Any]]:
    """tanδ(T) 点带表加载（逐行 dict）。"""
    with (_DATA / "tandelta_cryo_points.csv").open("r", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    rows = []
    for row in csv.DictReader(lines):
        if not row.get("t_key", "").strip():
            continue
        rows.append({
            "t_key": row["t_key"].strip(),
            "f_ghz": float(row["f_ghz"]),
            "t_k": float(row["t_k"]),
            "tan_delta_low": float(row["tan_delta_low"]),
            "tan_delta_high": float(row["tan_delta_high"]),
            "source_ref": row["source_ref"].strip(),
        })
    return rows


def tandelta_band(t_key: Any, f_ghz: Any, t_k: Any,
                  rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """tanδ band 的 log10(T) 轴线性插值（band 插值，interpolated 标记）。

    band 在 log10(tanδ) 空间插值（数量级量跨 4K/300K 的合理口径）；
    端点外不外推（clamp+extrapolated=True）；f_ghz 不同 → 如实
    ValueError（点表只登记 10 GHz 口径，频段外推未标注，不虚构）。
    """
    tkey = str(t_key)
    f = _positive(f_ghz, "f_ghz")
    t = _positive(t_k, "t_k")
    data = rows if rows is not None else load_tandelta_points()
    pts = sorted([r for r in data if r["t_key"] == tkey], key=lambda r: r["t_k"])
    if not pts:
        raise ValueError(f"未知 t_key {tkey!r}；可选 "
                         f"{sorted({r['t_key'] for r in data})}")
    if any(abs(r["f_ghz"] - f) > 1e-9 for r in pts):
        raise ValueError(f"点表只登记 f_ghz={pts[0]['f_ghz']} 口径，"
                         f"频段外推未标注（不虚构），实际 {f}")
    ts = [r["t_k"] for r in pts]
    tc = min(max(t, ts[0]), ts[-1])
    if len(pts) == 1 or tc == ts[0] or tc == ts[-1]:
        idx = min(range(len(pts)), key=lambda i: abs(pts[i]["t_k"] - tc))
        row = pts[idx]
        return {"tan_delta_low": row["tan_delta_low"],
                "tan_delta_high": row["tan_delta_high"],
                "interpolated": False, "extrapolated": t != tc,
                "t_k": tc}
    # 区间内：log10(T) 线性 × log10(tanδ) 线性（band 两端各自插）
    lt = math.log10(tc)
    for r0, r1 in pairwise(pts):
        if r0["t_k"] <= tc <= r1["t_k"]:
            w = (lt - math.log10(r0["t_k"])) / (
                math.log10(r1["t_k"]) - math.log10(r0["t_k"]))
            lo = 10.0 ** ((1 - w) * math.log10(r0["tan_delta_low"])
                          + w * math.log10(r1["tan_delta_low"]))
            hi = 10.0 ** ((1 - w) * math.log10(r0["tan_delta_high"])
                          + w * math.log10(r1["tan_delta_high"]))
            return {"tan_delta_low": lo, "tan_delta_high": hi,
                    "interpolated": True, "extrapolated": False, "t_k": tc}
    raise AssertionError("unreachable")  # pragma: no cover
