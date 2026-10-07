"""AP-7 多径衰落统计包（规格深案 §A-9，2026-10-02）。

衰落域主线首件：小尺度衰落 CDF 族（Rice/Rayleigh/Nakagami-m/对数正态）
+ 微波视距链路多径中断双模型（Vigants-Barnett 简式 / ITU-R P.530-18 正
式式）+ 可用性↔裕量换算器。全部**纯函数零 IO**、单位口径显式、返回
JSON 可序列化值。零求解器依赖（§A 包跨件裁决）、零 ITU 数据文件捆绑。

出处与口径（逐条实测核，#118 裁判纪律）：
- 衰落 CDF 族：h = 10^(-margin_db/10) 为**功率**门限（相对平均功率 Ω
  归一）。
  - Rayleigh：P_out = 1 - exp(-h)（Ω 基经典闭式）。
  - Rice（Ricean，K 因子=镜射/漫散射功率比，线性值）：r²/σ² ~
    非中心 χ²(df=2, nc=2K)，P_out = P(r² < hΩ) = ncx2.cdf(2h(K+1);
    df=2, nc=2K)（≡ 1 - Marcum-Q1(√(2K), √(2h(K+1)))）。scipy 1.18.1
    **无 scipy.special.marcumq**（实测 ImportError），走
    scipy.special.chndtr 非中心卡方 CDF 等价路径（与闭式互证实测一致）。
    **任务书 "K→∞ Rice→Rayleigh 退化" 系笔误**——物理极限是 K→0
    （镜射分量消失→纯漫散射）退化为 Rayleigh（实测偏差 3e-17）；
    K→∞ 是无衰落极限（outage→0）。
  - Nakagami-m：P_out = P(m, m·h)（正则化下不完全 Gamma，
    scipy.special.gammainc）；m=1 恒等于 Rayleigh（实测 3e-17）；物理
    域 m ≥ 0.5。
  - 对数正态（阴影衰落，Gudmundson 模型口径）：P_out = Φ(-M/σ_db)
    = 0.5·erfc(M/(σ_db·√2))。
- Vigants-Barnett 简式：**一手出处 W.T. Barnett, "Multipath Propagation
  at 4, 6, and 11 GHz", BSTJ 51(2), 1972, pp.321-361，§6.3 式(6)+Fig.8**
  （bitsavers 原刊文本层核：Pr(v<L)=rL²、L<0.1、r=c·(f/4)·D³、f/GHz、
  D/英里；Fig.8 题注 "P = rL² = c(f/4)D³L²"）。L=10^(-F/20)（F=衰落
  裕量 dB）→ **P_out = c·(f/4)·1e-5·D_mi³·10^(-F/10)**。c 档位
  （BSTJ 文本层核）：4=over-water and Gulf Coast / 1=average terrain /
  0.25=mountains and dry climate；**1e-5 尺度因子**系原刊式(6)排版图未
  进 OCR 文本层，由 Table II West Unity 实测系数回核恢复（4GHz/28.5mi
  路径 r≈0.25 → c=1.08e-5，Pathloss 4.0 手册同式转述亦含 1e-5）。
  第四档 rough=0.5 为常见二手文献插值档，**UNVERIFIED**（一手只有三
  档）。适用域：深衰落 L<0.1（F≳20dB）；数据基础 4-11GHz/20-40mi。
- ITU-R P.530-18 正式式（§2.3.1 式(7)，2021-09 版，itu.int PDF 文本
  层逐位核）：**p_w[%] = K · d^3.51 · (f²+13)^0.447 · 10^(-0.376·tanh(
  (h_c-147)/125) - 0.334·|ε_p| - 0.00027·h_L + 17.85·v_sr - A/10)**，
  K 为地理气候因子（%口径，Rec 附带 LogK.csv 网格查表——**本仓零外部
  数据捆绑，K 以 log10_k 参数显式传入，缺省 -2.0 系典型温带占位，
  UNVERIFIED 待 LogK 网格接入**）；d>5km 才需计算（短路径记 0，Rec
  原文口径）；模型回归数据域 7.5-300km / 0.45-37GHz。
- 两式同参差异：V-B 把地形/气候/几何全部折进单标量 c，P.530-18 把它
  们显式拆成 K/ε_p/h_c/h_L/v_sr——"同参对照"必须先固定一个映射约定，
  差异带是映射的函数（锚点实测 P.530/V-B ≈ 0.21，见
  availability_margin 返回的 diff_band 与 test_fading.py 差异带报告）。
  **不设对错门，如实记录带**（任务书口径）。

参考：规格深案 §A-9；calc_families/propagation.py
注册薄壳先例；锚树 tests/unit/test_fading.py。
"""

from __future__ import annotations

import math
from typing import Any

# V-B 气候-地形档位（c 因子，1e-5 尺度前的无量纲乘子）：
# 三档为一手 BSTJ 51(2) 1972 §6.3 文本层核；rough=0.5 二手插值档
# UNVERIFIED（任务书"系数值用常见文献档并标注"口径）。
_VB_CLIMATE_C: dict[str, float] = {
    "over_water": 4.0,  # over-water and Gulf Coast（BSTJ 一手核）
    "average": 1.0,  # average terrain（BSTJ 一手核）
    "rough": 0.5,  # 二手文献插值档（UNVERIFIED）
    "dry_mountain": 0.25,  # mountains and dry climate（BSTJ 一手核）
}
_KM_PER_MI = 1.609344  # 国际英里精确定义（1 mi = 1609.344 m）

_KINDS = ("rice", "rayleigh", "nakagami", "lognormal")
# 衰落 CDF 族幅度地板：P_out 下限（防 100·P 渲染面出现 -inf/反常，
# physics_invariants 非有限数契约；取 IEEE 双精度下溢安全量级）
_PROB_FLOOR = 1e-300


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯；#364④ 显式 is not None 判缺）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _pos(value: Any, name: str) -> float:
    """正数域守卫（>0）。"""
    out = _num(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须为正，得 {out}")
    return out


def _nonneg(value: Any, name: str) -> float:
    """非负域守卫（>=0）。"""
    out = _num(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须非负，得 {out}")
    return out


# ─── 小尺度衰落 CDF 族 ────────────────────────────────────────────────────


def fade_outage_percent(
    margin_db: float,
    kind: str = "rice",
    k: float = 10.0,
    m: float = 1.0,
    sigma_db: float = 8.0,
) -> float:
    """小尺度/阴影衰落中断概率 [%]：P(接收功率 < 中值 - margin_db)。

    门限 h = 10^(-margin_db/10)（功率比，相对平均功率 Ω=1 归一）。

    kind：
    - "rice"：Ricean 衰落，k = K 因子（镜射/漫射功率比，**线性值**，
      10dB → 10.0）。P_out = ncx2.cdf(2h(K+1); df=2, nc=2K)
      （≡ 1-Marcum-Q1；scipy 1.18.1 无 marcumq，走 chndtr 等价路径）。
      K→0 严格退化为 Rayleigh（实测 3e-17）；K→∞ → 无衰落（outage→0）。
    - "rayleigh"：P_out = 1-exp(-h)（经典闭式）。
    - "nakagami"：Nakagami-m，m ≥ 0.5（物理域）。P_out = P(m, mh)
      （正则化下不完全 Gamma）。m=1 ≡ Rayleigh。
    - "lognormal"：对数正态阴影（dB 域 σ=sigma_db）。P_out = Φ(-M/σ)
      = 0.5·erfc(M/(σ√2))。M=σ 时 15.87%（1σ 经典锚）。

    返回百分数 [0, 100]。margin_db 域守卫 ≥0（负裕量无衰落统计语义）。
    """
    if kind not in _KINDS:
        raise ValueError(f"kind 只收 {_KINDS}，得 {kind!r}")
    margin = _nonneg(margin_db, "margin_db")
    h = 10.0 ** (-margin / 10.0)
    if kind == "rayleigh":
        p = 1.0 - math.exp(-h)
    elif kind == "rice":
        kk = _nonneg(k, "k")
        from scipy.special import chndtr

        p = float(chndtr(2.0 * h * (1.0 + kk), 2, 2.0 * kk))
    elif kind == "nakagami":
        mm = _num(m, "m")
        if mm < 0.5:
            raise ValueError(f"m 必须 >= 0.5（Nakagami 物理域），得 {mm}")
        from scipy.special import gammainc

        p = float(gammainc(mm, mm * h))
    else:  # lognormal
        s = _pos(sigma_db, "sigma_db")
        p = 0.5 * math.erfc(margin / (s * math.sqrt(2.0)))
    return 100.0 * max(p, _PROB_FLOOR)


# ─── Vigants-Barnett 简式（Barnett 1972 BSTJ 一手口径）────────────────────


def vigants_barnett_outage(
    f_ghz: float, d_km: float, fade_margin_db: float, climate: str = "average"
) -> float:
    """Vigants-Barnett 多径中断时间占比（平均最差月，时间分数 [0,1]）。

    Barnett 1972（BSTJ 51(2) §6.3 式(6)+Fig.8，一手文本层核）：

        P_out = c · (f/4) · 1e-5 · D_mi³ · 10^(-F/10)

    f/GHz、D_mi/英里（d_km 换算）、F/ dB（深衰落域 L<0.1，F≳20dB
    有效；浅衰落域幂律低估，见 docstring 头适用域注）。

    climate 四档（→ c）：over_water=4 / average=1 / rough=0.5(UNVERIFIED
    插值档) / dry_mountain=0.25。原始式可超出 1（短裕量超长路径）——
    物理截断到 1.0（模型外推越域，调用方按 availability_margin 的
    metadata 判读）。域守卫 f_ghz>0 / d_km>0 / fade_margin_db>=0。
    """
    f = _pos(f_ghz, "f_ghz")
    d_km_v = _pos(d_km, "d_km")
    margin = _nonneg(fade_margin_db, "fade_margin_db")
    if climate not in _VB_CLIMATE_C:
        raise ValueError(
            f"climate 只收 {sorted(_VB_CLIMATE_C)}，得 {climate!r}")
    c_fac = _VB_CLIMATE_C[climate]
    d_mi = d_km_v / _KM_PER_MI
    r_occurrence = c_fac * (f / 4.0) * 1e-5 * d_mi**3
    p_out = r_occurrence * 10.0 ** (-margin / 10.0)
    return float(min(max(p_out, 0.0), 1.0))


# ─── ITU-R P.530-18 正式式（§2.3.1 式(7)，2021-09 版文本层核）──────────────


def _p530_geom_exponent(
    hc_m: float, eps_p_mrad: float, h_l_m: float, vsr: float
) -> float:
    """式(7) 几何/气象指数项（A/10 之前的部分）。"""
    return (
        -0.376 * math.tanh((hc_m - 147.0) / 125.0)
        - 0.334 * abs(eps_p_mrad)
        - 0.00027 * h_l_m
        + 17.85 * vsr
    )


def _p530_pw_percent(
    f_ghz: float,
    d_km: float,
    fade_margin_db: float,
    log10_k: float,
    eps_p_mrad: float,
    hc_m: float,
    h_l_m: float,
    vsr: float,
) -> float:
    """P.530-18 式(7)：深衰落超过概率 p_w [%]（平均最差月）。"""
    k_pct = 10.0**log10_k
    geom = _p530_geom_exponent(hc_m, eps_p_mrad, h_l_m, vsr)
    return (
        k_pct
        * d_km**3.51
        * (f_ghz * f_ghz + 13.0) ** 0.447
        * 10.0 ** (geom - fade_margin_db / 10.0)
    )


def _p530_margin_db(
    f_ghz: float,
    d_km: float,
    target_pct: float,
    log10_k: float,
    eps_p_mrad: float,
    hc_m: float,
    h_l_m: float,
    vsr: float,
) -> float:
    """P.530-18 幂律反解：达到 p_w=target_pct [%] 所需衰落裕量 [dB]。

    A = 10·log10(K·d^3.51·(f²+13)^0.447·10^geom / target_pct)。
    可为负（目标概率高于 0dB 裕量中断率——浅衰落域，幂律不适用，
    调用方如实透出）。d<=5km 时 Rec 口径记 0 中断 → 裕量无定义，
    返回 inf 语义不合法（非有限数契约），改抛 ValueError。
    """
    if d_km <= 5.0:
        raise ValueError(
            "P.530-18 多径衰落仅对 d>5km 定义（短路径记 0 中断），"
            f"得 d_km={d_km}")
    k_pct = 10.0**log10_k
    geom = _p530_geom_exponent(hc_m, eps_p_mrad, h_l_m, vsr)
    occ = k_pct * d_km**3.51 * (f_ghz * f_ghz + 13.0) ** 0.447 * 10.0**geom
    return 10.0 * math.log10(occ / target_pct)


# ─── 可用性↔裕量换算器（双模型同参对照）───────────────────────────────────


def availability_margin(
    f_ghz: float,
    d_km: float,
    climate: str = "average",
    *,
    availability_percent: float | None = None,
    fade_margin_db: float | None = None,
    log10_k: float = -2.0,
    eps_p_mrad: float = 10.0,
    hc_m: float = 500.0,
    h_l_m: float = 100.0,
    vsr: float = 0.0,
) -> dict[str, Any]:
    """可用性↔衰落裕量双向换算 + V-B/P.530-18 同参差异带报告。

    方向二选一（都给或都不给显式 ValueError）：
    - 给 availability_percent（(0,100) 开区间，最差月时间可用度）：
      反解两模型所需 fade margin [dB]（V-B/P.530 均为 10^(-F/10) 幂律，
      闭式反解；解可为负=浅衰落域越域，如实透出）。
    - 给 fade_margin_db（>=0）：正算两模型中断时间分数与对应可用度。

    同参映射约定（diff_band 的前提，如实透出）：V-B climate 档 → c；
    P.530 侧 K/几何显式参数（缺省 log10_k=-2.0 典型温带占位 UNVERIFIED、
    eps_p_mrad=10、hc_m=500、h_l_m=100、vsr=0）。

    返回（JSON 可序列化）：
    - direction / f_ghz / d_km / worst_month=True
    - vb：{c_factor, climate, outage_fraction 或 fade_margin_db,
      availability_percent}
    - p530：{log10_k, eps_p_mrad, hc_m, h_l_m, vsr, 同上两字段}
    - diff_band：两模型 margin 差 [dB] 与中断比（P.530/V-B）——**不设
      对错门，如实记录带**；margin 差在幂律域与可用度无关（同指数），
      中断比随方向/裕量逐点变化
    - notes：出处与 UNVERIFIED 位标注清单
    """
    f = _pos(f_ghz, "f_ghz")
    d = _pos(d_km, "d_km")
    if climate not in _VB_CLIMATE_C:
        raise ValueError(
            f"climate 只收 {sorted(_VB_CLIMATE_C)}，得 {climate!r}")
    log10_k_v = _num(log10_k, "log10_k")
    eps_p = _nonneg(eps_p_mrad, "eps_p_mrad")
    hc = _num(hc_m, "hc_m")
    h_l = _num(h_l_m, "h_l_m")
    vsr_v = _nonneg(vsr, "vsr")
    if (availability_percent is None) == (fade_margin_db is None):
        raise ValueError(
            "availability_percent 与 fade_margin_db 必须二选一（都给或"
            "都不给均拒绝）")
    if availability_percent is not None:
        avail = _num(availability_percent, "availability_percent")
        if not (0.0 < avail < 100.0):
            raise ValueError(
                f"availability_percent 须在 (0,100) 开区间，得 {avail}")
        p_target_frac = 1.0 - avail / 100.0
        p_target_pct = 100.0 * p_target_frac
        # V-B 闭式反解：F = -10·log10(P_target / (c·(f/4)·1e-5·D³))
        c_fac = _VB_CLIMATE_C[climate]
        d_mi = d / _KM_PER_MI
        r_occ = c_fac * (f / 4.0) * 1e-5 * d_mi**3
        vb_margin = -10.0 * math.log10(p_target_frac / r_occ)
        vb = {
            "climate": climate,
            "c_factor": c_fac,
            "fade_margin_db": vb_margin,
            "availability_percent": avail,
        }
        # P.530 闭式反解（d<=5km 记 0 中断 → 目标可用度恒成立，
        # 裕量无定义：如实以 None 透出）
        if d <= 5.0:
            p530 = {
                "fade_margin_db": None,
                "availability_percent": avail,
                "note": "d<=5km：Rec 口径中断记 0，裕量无定义",
            }
        else:
            p530 = {
                "fade_margin_db": _p530_margin_db(
                    f, d, p_target_pct, log10_k_v, eps_p, hc, h_l, vsr_v),
                "availability_percent": avail,
            }
        direction = "margin_from_availability"
    else:
        margin = _nonneg(fade_margin_db, "fade_margin_db")
        vb_frac = vigants_barnett_outage(f, d, margin, climate=climate)
        avail_vb = 100.0 * (1.0 - vb_frac)
        vb = {
            "climate": climate,
            "c_factor": _VB_CLIMATE_C[climate],
            "outage_fraction": vb_frac,
            "availability_percent": avail_vb,
        }
        if d <= 5.0:
            p530 = {
                "outage_fraction": 0.0,
                "availability_percent": 100.0,
                "note": "d<=5km：Rec 口径中断记 0",
            }
        else:
            pw_pct = _p530_pw_percent(
                f, d, margin, log10_k_v, eps_p, hc, h_l, vsr_v)
            p530_frac = min(max(pw_pct / 100.0, 0.0), 1.0)
            p530 = {
                "outage_fraction": p530_frac,
                "availability_percent": 100.0 * (1.0 - p530_frac),
            }
        direction = "availability_from_margin"

    diff_band: dict[str, Any] = {
        "scope": "worst_month",
        "mapping_note": (
            "V-B 折地形/气候/几何进单标量 c；P.530-18 显式拆 "
            "K/eps_p/hc/hL/vsr——同参对照依赖本函数入参的映射约定，"
            "差异带是映射的函数，不设对错门"),
    }
    vb_m = vb.get("fade_margin_db")
    p530_m = p530.get("fade_margin_db")
    if isinstance(vb_m, float) and isinstance(p530_m, float):
        diff_band["vb_margin_db"] = vb_m
        diff_band["p530_margin_db"] = p530_m
        diff_band["margin_diff_db_p530_minus_vb"] = p530_m - vb_m
    else:
        vb_frac = vb.get("outage_fraction")
        p530_frac = p530.get("outage_fraction")
        if isinstance(vb_frac, float) and isinstance(p530_frac, float):
            diff_band["vb_outage_fraction"] = vb_frac
            diff_band["p530_outage_fraction"] = p530_frac
            if vb_frac > 0.0:
                diff_band["outage_ratio_p530_over_vb"] = p530_frac / vb_frac

    notes = [
        "V-B：Barnett 1972 BSTJ 51(2) pp.321-361 §6.3/Fig.8 一手核；"
        "c 三档(4/1/0.25)一手核，rough=0.5 二手插值 UNVERIFIED；"
        "1e-5 尺度由 Table II 实测回核",
        "P.530-18：§2.3.1 式(7) 2021-09 版 PDF 文本层逐位核；"
        "log10_k 缺省 -2.0 为典型温带占位 UNVERIFIED（LogK.csv 网格"
        "未捆绑，零外部数据原则）",
        "两式均为平均最差月口径（年均值换算走 P.530-18 §2.3.4，未含）",
    ]
    return {
        "direction": direction,
        "f_ghz": f,
        "d_km": d,
        "worst_month": True,
        "vb": vb,
        "p530": p530,
        "diff_band": diff_band,
        "notes": notes,
    }
