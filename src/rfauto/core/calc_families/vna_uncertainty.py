"""VNA 测量不确定度族（aurora72 A4-A 席域 1，R7 第二梯队 T7=G19）。

三键：vna_reflection_uncertainty（反射测量不确定度：方向性/源匹配/跟踪
三残差项经典纹波合成）/ vna_transmission_uncertainty（传输测量不确定度：
串扰/负载匹配/跟踪三残差项）/ three_antenna_gain（三天线法/比较法增益
定标）。

与既有测量面的边界（语义防撞，R7 §③ T7 三重搜索证据）
--------------------------------------------------------
- tnvna_extender_error_model/tnvna_band_stitch = THz 扩频变频链误差模型
  与跨带拼接（ed/es/er 修正曲线口径）；本族是**标准同频 VNA S 参数残差
  不确定度传播**（校准后残差→测量不确定度），不做变频/拼接。
- trl_standards_design/trl_line_electric_scan = 校准件设计与线标准电长
  度扫描（校准上游）；本族消费**校准后残差**（校准下游）。
- power_cal_chain = 功率计校准链；nf_measurement（service 面）=噪声系
  数 Y 因子；material_uncertainty=Dk 容差传播——均不并入。
- 雷达检测面（radar_eq/radar_detection_ext）不并入；三天线法增益定标
  是天线增益计量口径（与 gt_ratio=链路预算 G/T 组合键语义不同）。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
校准后残差误差箱线性化传播（Rytting 误差模型口径；EURAMET cg-12
*Evaluation of Vector Network Analysers* Type-B 评定惯例；Keysight AN
1287 误差模型应用口径）：

- 反射（单端口三残差模型）：校准后残差方向性 Ed、源匹配 Es、反射跟踪
  残差 ΔTr（|Er|=1+ΔTr），测得 Γm = Ed + Er·Γ/(1−Es·Γ)，一阶展开

      δΓ ≈ Ed + ΔTr·Γ + Es·Γ²

  最坏情形纹波界 |δΓ| ≤ |Ed| + |ΔTr|·|Γ| + |Es|·|Γ|²（三误差项经典
  合成式；单误差项退化恒等=锚：只留方向性时 |δΓ|=|Ed|，Γ=0 的理想负
  载测得回波损耗地板 = −20lg|Ed|，即"残差方向性限定可测最佳回损"）。
- 传输（四误差模型的传输侧）：残差串扰 Xt、负载匹配 El、传输跟踪残差
  ΔEt：S21m = Xt + Et·S21/(1−El·S21)，一阶展开

      δS21 ≈ Xt + ΔEt·S21 + El·S21²

  最坏情形界同构（单误差项退化：S21=0 时串扰限定隔离度地板=−20lg|Xt|）。
- 残差量纲：directivity/source_match/crosstalk/load_match 以 20lg|残差
  系数|（dB，<0）给入；tracking 以 ±dB 纹波给入（线性化 |ΔT| =
  10^(±dB/20)−1，如 ±0.05dB→0.577%）。
- 统计口径：worst=线性相加最坏界（纹波包络）；rss=各项视为均匀分布
  Type-B（界/√3）方和根 → 标准不确定度 u，扩展不确定度 U=k·u（k 缺省
  2，EURAMET cg-12 惯例）。回损/增益域换算：RL=−20lg|Γ| 的线性化
  u_RL=8.686·u_Γ/|Γ| dB；最坏情形窗口取 Γ±e 双侧。
- 三天线法（far-field Friis 口径，IEEE Std 149 天线测量惯例）：同
  R/λ 下三对插入损耗 ILij 含自由空间路径损耗 FS=20lg(4πR/λ)
  （λ=C_MM_GHZ/f 单源），G_i+G_j=FS−IL_ij 线性解三元组：

      G1 = (FS − IL12 − IL13 + IL23)/2（G2/G3 轮换）

  构造恒等式 G_i+G_j=FS−IL_ij 随输出 pair_sum_max_err 自检；比较法
  （同场地下参考天线替代）G_dut = G_ref + (IL_ref − IL_dut)。
  插入损耗须先扣电缆/接头损耗并做失配与极化校正（不校正=系统增益
  口径，如实 note，不做隐藏修正）。

数值锚（#118 独立来源；锚树 tests/unit/test_a4a_vna_swerling.py）
----------------------------------------------------------------
- 反射：Γ=0/Ed=−40dB → 纹波=0.01、回损地板 40.00dB 恒等；单误差项
  退化逐位；20dB 负载@40dB 残差经典例（纹波 ~±0.9dB 文献口径带）；
- 传输：S21=0/Xt=−90dB → 隔离地板 90.00dB 恒等；1×直通@El=−20dB →
  增益纹波 20lg(1.1)=0.828dB 独立重算；
- 三天线：对称插入损耗 → 三增益相等恒等；给定真增益经 Friis 正演
  IL 再反演=逐位回收（独立 FSPL 92.45+20lgf_GHz+20lgd_km 常数式
  双源对照）；比较法平移恒等。

守卫：gamma_mag∈[0,1]（0=理想负载合法，方向性地板演示）；s21_mag≥0
有限（>1 有源器件线性化口径照算）；各残差 dB 有限且 <0（0dB=残差模
1 非物理）；tracking_db∈[0,10]；combine∈{"worst","rss"}；k≥1；三天
线法 f>0/R>0/IL 有限、method∈{"three_antenna","comparison"} 且对应参
数组齐备（缺一显式拒绝）。越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator

_UNIF_DENOM = math.sqrt(3.0)  # 均匀分布 Type-B：界/√3（EURAMET cg-12 惯例）
_COMBINES = ("worst", "rss")


def _req_neg_db(value: Any, name: str, key: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and v < 0.0):
        raise ValueError(
            f"{key}: {name} 必须为 <0 的有限 dB 数（残差系数模 20lg 口径，"
            f"0dB=残差模 1 非物理），得到 {value!r}")
    return v


def _req_track_db(value: Any, key: str) -> float:
    v = float(value)
    if not (math.isfinite(v) and 0.0 <= v <= 10.0):
        raise ValueError(
            f"{key}: tracking_db 必须为 [0,10] 内的 ±dB 纹波，得到 "
            f"{value!r}")
    return v


def _req_mag(value: Any, name: str, key: str, lo: float,
             hi: float | None) -> float:
    v = float(value)
    if not math.isfinite(v) or v < lo or (hi is not None and v > hi):
        upper = "" if hi is None else f"，且 ≤{hi:g}"
        raise ValueError(
            f"{key}: {name} 必须为 ≥{lo:g}{upper} 的有限线性量，得到 "
            f"{value!r}")
    return v


def _db_from_mag(mag: float) -> float | None:
    return None if mag <= 0.0 else 20.0 * math.log10(mag)


def _uncertainty_terms(names: tuple[str, str, str], ed: float,
                       tr_lin: float, es: float,
                       mag: float) -> tuple[list[tuple[str, float]], float, float]:
    """三误差项分解 → ([(名称, 项)], 最坏和, rss 标准不确定度)。

    反射=(directivity, tracking, source_match)；传输=(crosstalk, tracking,
    load_match)——同构 δ=X+ΔT·M+E·M² 逐项分解，名称按口径面区分。"""
    terms = [
        (names[0], ed),
        (names[1], tr_lin * mag),
        (names[2], es * mag * mag),
    ]
    worst = sum(abs(v) for _, v in terms)
    u = math.sqrt(sum((abs(v) / _UNIF_DENOM) ** 2 for _, v in terms))
    return terms, worst, u


def _dominant(terms: list[tuple[str, float]]) -> str:
    return max(terms, key=lambda kv: abs(kv[1]))[0]


# ─── 键 1：反射测量不确定度 ──────────────────────────────────────────────────

@register_calculator(
    "vna_reflection_uncertainty",
    "反射测量不确定度：VNA 校准后残差三误差项经典纹波合成（单端口模型）"
    "——δΓ≈Ed+ΔTr·Γ+Es·Γ² 一阶展开，最坏界 |δΓ|≤|Ed|+|ΔTr||Γ|+|Es||Γ|²，"
    "方向性/跟踪/源匹配逐项分解+主导项判读；rss 档按均匀分布 Type-B（界/"
    "√3）方和根给 u 与扩展 U=k·u（EURAMET cg-12 惯例）。回损域换算 RL="
    "−20lg|Γ|（最坏窗口/u_RL=8.686u/|Γ|）。残差 dB 口径：方向性/源匹配="
    "20lg|残差系数|（<0），跟踪=±dB 纹波（线性化 10^(dB/20)−1）。锚：Γ=0 "
    "回损地板=−directivity_db 恒等；20dB 负载@40dB 残差纹波 ~±0.9dB 经典"
    "带。出处 Rytting 误差模型/EURAMET cg-12/Keysight AN 1287",
    (("gamma_mag", "float - 反射系数幅值 |Γ|（[0,1]；0=理想负载合法）"),
     ("directivity_db", "float dB 残差方向性 |Ed|（20lg 口径，<0；校准后"
      "典型 −45~−55）"),
     ("source_match_db", "float dB 残差源匹配 |Es|（20lg 口径，<0；校准后"
      "典型 −40~−50）"),
     ("tracking_db", "float dB 反射跟踪残差 ±dB 纹波（[0,10]，缺省 0）"),
     ("combine", "str 合成方式 'worst'（最坏纹波界，缺省）|'rss'（Type-B "
      "方和根）"),
     ("k", "float 扩展不确定度包含因子（rss 档，≥1，缺省 2）")),
    required=("gamma_mag", "directivity_db", "source_match_db"),
)
def vna_reflection_uncertainty(
    gamma_mag: float, directivity_db: float, source_match_db: float,
    tracking_db: float = 0.0, combine: str = "worst",
    k: float = 2.0) -> dict[str, Any]:
    key = "vna_reflection_uncertainty"
    gamma = _req_mag(gamma_mag, "gamma_mag", key, 0.0, 1.0)
    ed = 10.0 ** (_req_neg_db(directivity_db, "directivity_db", key) / 20.0)
    es = 10.0 ** (_req_neg_db(source_match_db, "source_match_db", key) / 20.0)
    tr_lin = 10.0 ** (_req_track_db(tracking_db, key) / 20.0) - 1.0
    if combine not in _COMBINES:
        raise ValueError(
            f"{key}: combine 须 'worst'|'rss'，得到 {combine!r}")
    k_fac = float(k)
    if not (math.isfinite(k_fac) and k_fac >= 1.0):
        raise ValueError(f"{key}: k 必须为 ≥1 的有限数，得到 {k!r}")

    terms, e_worst, u_std = _uncertainty_terms(
        ("directivity", "tracking", "source_match"), ed, tr_lin, es, gamma)
    rl_db = _db_from_mag(gamma)
    out: dict[str, Any] = {
        "gamma_mag": gamma,
        "return_loss_db": None if rl_db is None else round(rl_db, 6),
        "ed_lin": ed,
        "es_lin": es,
        "tr_lin": tr_lin,
        "terms": {name: round(val, 15) for name, val in terms},
        "e_gamma_worst": round(e_worst, 15),
        "gamma_meas_min": round(max(gamma - e_worst, 0.0), 15),
        "gamma_meas_max": gamma + e_worst,
        "combine": combine,
        "k_factor": k_fac,
        "u_gamma_rss": round(u_std, 15),
        "u_gamma_expanded": round(k_fac * u_std, 15),
        "dominant_term": _dominant(terms),
        "note": (
            "最坏纹波界=三误差项线性相加（经典包络口径）；rss 档=各项均匀"
            "分布 Type-B 界/√3 方和根（EURAMET cg-12），u 与 U=k·u 并列"
            "输出；Γ±e 窗口在 e>|Γ| 时下界触 0（线性域失真，如实保留）"),
        "source": ("Rytting 误差模型（单端口三残差一阶展开）；EURAMET "
                   "cg-12 Type-B 评定惯例；Keysight AN 1287"),
    }
    if rl_db is not None:
        out["rl_meas_min_db"] = round(-20.0 * math.log10(gamma + e_worst), 6)
        hi = gamma - e_worst
        out["rl_meas_max_db"] = (None if hi <= 0.0
                                 else round(-20.0 * math.log10(hi), 6))
        out["rl_u_db"] = round(8.685890 / gamma * u_std, 6)
    else:
        # 理想负载：方向性地板恒等（|δΓ|=|Ed| → 回损地板=−directivity_db）
        out["rl_floor_db"] = round(-_req_neg_db(
            directivity_db, "directivity_db", key), 6)
    return out


# ─── 键 2：传输测量不确定度 ──────────────────────────────────────────────────

@register_calculator(
    "vna_transmission_uncertainty",
    "传输测量不确定度：VNA 校准后残差三误差项经典纹波合成（传输侧四误差"
    "模型）——δS21≈Xt+ΔEt·S21+El·S21² 一阶展开，最坏界 |δS21|≤|Xt|+"
    "|ΔEt||S21|+|El||S21|²，串扰/跟踪/负载匹配逐项分解+主导项判读；rss 档"
    "均匀分布 Type-B（界/√3）方和根 u 与扩展 U=k·u。增益域换算 G=20lg|"
    "S21|（最坏窗口/u_G=8.686u/|S21|）。锚：S21=0 隔离地板=−crosstalk_db "
    "恒等；直通@El=−20dB 纹波 20lg(1.1)=0.828dB 独立重算。出处 Rytting 误"
    "差模型/EURAMET cg-12/Keysight AN 1287",
    (("s21_mag", "float - 传输系数幅值 |S21|（≥0 有限；>1 有源器件线性化"
      "口径照算）"),
     ("crosstalk_db", "float dB 残差串扰/泄漏 |Xt|（20lg 口径，<0；典型 "
      "−80~−100）"),
     ("load_match_db", "float dB 残差负载匹配 |El|（20lg 口径，<0；典型 "
      "−35~−45）"),
     ("tracking_db", "float dB 传输跟踪残差 ±dB 纹波（[0,10]，缺省 0）"),
     ("combine", "str 合成方式 'worst'（最坏纹波界，缺省）|'rss'（Type-B "
      "方和根）"),
     ("k", "float 扩展不确定度包含因子（rss 档，≥1，缺省 2）")),
    required=("s21_mag", "crosstalk_db", "load_match_db"),
)
def vna_transmission_uncertainty(
    s21_mag: float, crosstalk_db: float, load_match_db: float,
    tracking_db: float = 0.0, combine: str = "worst",
    k: float = 2.0) -> dict[str, Any]:
    key = "vna_transmission_uncertainty"
    s21 = _req_mag(s21_mag, "s21_mag", key, 0.0, None)
    xt = 10.0 ** (_req_neg_db(crosstalk_db, "crosstalk_db", key) / 20.0)
    el = 10.0 ** (_req_neg_db(load_match_db, "load_match_db", key) / 20.0)
    tr_lin = 10.0 ** (_req_track_db(tracking_db, key) / 20.0) - 1.0
    if combine not in _COMBINES:
        raise ValueError(
            f"{key}: combine 须 'worst'|'rss'，得到 {combine!r}")
    k_fac = float(k)
    if not (math.isfinite(k_fac) and k_fac >= 1.0):
        raise ValueError(f"{key}: k 必须为 ≥1 的有限数，得到 {k!r}")

    terms, e_worst, u_std = _uncertainty_terms(
        ("crosstalk", "tracking", "load_match"), xt, tr_lin, el, s21)
    g_db = _db_from_mag(s21)
    out: dict[str, Any] = {
        "s21_mag": s21,
        "s21_db": None if g_db is None else round(g_db, 6),
        "xt_lin": xt,
        "el_lin": el,
        "tr_lin": tr_lin,
        "terms": {name: round(val, 15) for name, val in terms},
        "e_s21_worst": round(e_worst, 15),
        "s21_meas_min": round(max(s21 - e_worst, 0.0), 15),
        "s21_meas_max": s21 + e_worst,
        "combine": combine,
        "k_factor": k_fac,
        "u_s21_rss": round(u_std, 15),
        "u_s21_expanded": round(k_fac * u_std, 15),
        "dominant_term": _dominant(terms),
        "note": (
            "最坏纹波界=三误差项线性相加；rss 档=各项均匀分布 Type-B 界/"
            "√3 方和根（EURAMET cg-12）；|S21|−e 触 0 时线性域失真如实"
            "保留；本式为传输侧四误差模型一阶展开（源匹配经双向 S11·S22 "
            "耦合的二阶项不在 v1 口径，如实注记）"),
        "source": ("Rytting 误差模型（传输侧串扰/负载匹配/跟踪残差）；"
                   "EURAMET cg-12 Type-B 评定惯例；Keysight AN 1287"),
    }
    if g_db is not None:
        lo = s21 - e_worst
        out["g21_meas_min_db"] = (None if lo <= 0.0
                                  else round(20.0 * math.log10(lo), 6))
        out["g21_meas_max_db"] = round(20.0 * math.log10(s21 + e_worst), 6)
        out["g21_u_db"] = round(8.685890 / s21 * u_std, 6)
    else:
        # 理想隔离：串扰地板恒等（|δS21|=|Xt| → 隔离地板=−crosstalk_db）
        out["isolation_floor_db"] = round(-_req_neg_db(
            crosstalk_db, "crosstalk_db", key), 6)
    return out


# ─── 键 3：三天线法/比较法增益定标 ──────────────────────────────────────────

@register_calculator(
    "three_antenna_gain",
    "三天线法增益定标：同 R/λ 三对插入损耗 ILij（须先扣电缆/接头并做失"
    "配与极化校正）经 Friis 口径 G_i+G_j=FS−IL_ij 线性解三元组 G1=(FS−"
    "IL12−IL13+IL23)/2（G2/G3 轮换），FS=20lg(4πR/λ)、λ=C_MM_GHZ/f 单"
    "源；构造恒等式 G_i+G_j=FS−IL_ij 随 pair_sum_max_err 自检（机器精度"
    "级）。可选 method='comparison' 增益比较法：同场地参考替代 G_dut=G_"
    "ref+(IL_ref−IL_dut)。锚：对称 IL→三增益相等恒等；Friis 正演→反演"
    "逐位回收（独立 92.45+20lgf_GHz+20lgd_km 常数式双源）。出处 IEEE "
    "Std 149 天线测量惯例/Friis 传输公式",
    (("method", "str 定标方法 'three_antenna'（缺省）|'comparison'"),
     ("il12_db", "float dB 天线 1-2 对插入损耗（失配/极化校正后）"),
     ("il13_db", "float dB 天线 1-3 对插入损耗"),
     ("il23_db", "float dB 天线 2-3 对插入损耗"),
     ("f_ghz", "float GHz 定标频率（三天线法必需）"),
     ("range_m", "float m 收发距离（三天线法必需，远场条件须另行满足）"),
     ("ref_gain_db", "float dBi 参考天线增益（比较法必需）"),
     ("il_ref_db", "float dB 参考天线对插入损耗（比较法必需）"),
     ("il_dut_db", "float dB 被测天线对插入损耗（比较法必需）")),
    required=(),
)
def three_antenna_gain(
    method: str = "three_antenna",
    il12_db: float | None = None, il13_db: float | None = None,
    il23_db: float | None = None, f_ghz: float | None = None,
    range_m: float | None = None, ref_gain_db: float | None = None,
    il_ref_db: float | None = None, il_dut_db: float | None = None,
) -> dict[str, Any]:
    key = "three_antenna_gain"

    def _req_finite(value: Any, name: str) -> float:
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(
                f"{key}: {name} 必须为有限数，得到 {value!r}")
        return v

    if method == "three_antenna":
        missing = [nm for nm, v in (
            ("il12_db", il12_db), ("il13_db", il13_db),
            ("il23_db", il23_db), ("f_ghz", f_ghz),
            ("range_m", range_m)) if v is None]
        if missing:
            raise ValueError(
                f"{key}: method='three_antenna' 缺参数 {missing}（显式"
                "拒绝）")
        freq = _req_mag(f_ghz, "f_ghz", key, 0.0, None)  # type: ignore[arg-type]
        rng = _req_mag(range_m, "range_m", key, 0.0, None)  # type: ignore[arg-type]
        il12 = _req_finite(il12_db, "il12_db")
        il13 = _req_finite(il13_db, "il13_db")
        il23 = _req_finite(il23_db, "il23_db")
        lam_m = C_MM_GHZ / freq * 1e-3
        fs_db = 20.0 * math.log10(4.0 * math.pi * rng / lam_m)
        g1 = (fs_db - il12 - il13 + il23) / 2.0
        g2 = (fs_db - il12 - il23 + il13) / 2.0
        g3 = (fs_db - il13 - il23 + il12) / 2.0
        pair_err = max(
            abs((g1 + g2) - (fs_db - il12)),
            abs((g1 + g3) - (fs_db - il13)),
            abs((g2 + g3) - (fs_db - il23)))
        return {
            "method": method,
            "freq_ghz": freq,
            "range_m": rng,
            "wavelength_m": round(lam_m, 12),
            "fspl_db": round(fs_db, 9),
            "il12_db": il12, "il13_db": il13, "il23_db": il23,
            "gain1_db": round(g1, 9),
            "gain2_db": round(g2, 9),
            "gain3_db": round(g3, 9),
            "pair_sum_max_err": round(pair_err, 15),
            "note": (
                "三天线法消去未知 ηrad 依赖（三对测量解三未知增益）；插入"
                "损耗须先扣电缆/接头损耗并做失配与极化校正（不校正=系统"
                "增益口径）；远场条件（R≫2D²/λ）与多径抑制须另行保障，"
                "本键不校验"),
            "source": ("IEEE Std 149 天线测量惯例（三天线法）；Friis 传输"
                       "公式（同 R/λ 口径）"),
        }
    if method == "comparison":
        missing = [nm for nm, v in (
            ("ref_gain_db", ref_gain_db), ("il_ref_db", il_ref_db),
            ("il_dut_db", il_dut_db)) if v is None]
        if missing:
            raise ValueError(
                f"{key}: method='comparison' 缺参数 {missing}（显式拒绝）")
        g_ref = _req_finite(ref_gain_db, "ref_gain_db")
        il_ref = _req_finite(il_ref_db, "il_ref_db")
        il_dut = _req_finite(il_dut_db, "il_dut_db")
        g_dut = g_ref + (il_ref - il_dut)
        return {
            "method": method,
            "ref_gain_db": g_ref,
            "il_ref_db": il_ref,
            "il_dut_db": il_dut,
            "gain_dut_db": round(g_dut, 9),
            "note": (
                "增益比较法：同场地/同 R/λ 下参考天线替代测量，插入损耗差"
                "即增益差（须同极化与失配校正口径）；本键不做距离/频率一"
                "致性校验（输入侧责任，如实注记）"),
            "source": ("IEEE Std 149 天线测量惯例（增益比较法）；Friis "
                       "传输公式"),
        }
    raise ValueError(
        f"{key}: method 须 'three_antenna'|'comparison'，得到 {method!r}")
