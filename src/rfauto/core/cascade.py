"""DP-5 系统级预算引擎 + 混频杂散搜索（纯函数，零 IO，微秒级确定性内核）。

规格：规格深案 §DP-5；判据书：
runs/df6_dp5cascade/criteria.md（回收钉锚值与来源）。

公式口径（§0，含规格书勘误 1 处）：
- 总增益 G_tot = Σ G_i (dB)。
- Friis 噪声级联（功率域线性）：F_tot = F₁ + (F₂−1)/G₁ + (F₃−1)/(G₁G₂) + …
- IIP3 级联（功率域求和式）::

      1/IIP3_tot = Σᵢ G_pre,i / IIP3ᵢ      （线性 mW，G_pre,i=该级之前全部级
                                             增益之积）

  规格书 §2 字面写作 ``1/(IIP3ᵢ·Π_{j<i}G_j)``（增益落分母），与教科书推导
  （Pozar《Microwave Engineering》级联非线性一节；本仓 core/budget.py
  LinkBudget 同口径且已有单测）相反：后级 IIP3 折算到链路输入应**除以**
  其前级增益（20 dB LNA 之后的混频器对链路输入的 IP3 贡献缩小 100 倍）。
  本模块按教科书口径实现，criteria.md §0 有解析恒等式锚（钉 1
  IIP3_tot ≡ −7.0 dBm）。
- OIP3_tot = IIP3_tot + G_tot（恒等式）。
- 噪声底 N_floor = 10·log10(k_B·T·1e3) + 10·log10(B) + NF_tot [dBm]，
  k_B = 1.380649e-23（SI 精确值）、T 缺省 290 K（教科书 −174 dBm/Hz 的
  精确化）。带宽 B 解析顺序：显式入参 bw_hz > 末级 stage bw_hz > 显式报错。
- SFDR = (2/3)·(IIP3_tot − N_floor)；灵敏度 P_sens = N_floor + SNR_min；
  链路裕量 = P_rx − P_sens。
- P1dB 级联为**经验口径**（无教科书闭式，如实标注）：各级 OP1dB（输出参考）
  加其后全部级增益折算到链路输出后取功率域幂和
  ``1/P1dB_out = Σᵢ 1/(OP1dBᵢ + G_after,i)``——与级联 IP3 同形的饱和功率
  叠加工程惯例（链路预算工具实践口径）。p1db_dbm 约定=该级**输出** 1dB
  压缩点（与 core/budget.py LinkBudget 同约定）。

spur search：f_spur = |m·f_RF ± n·f_LO| 全阶枚举（缺省 m+n ≤ max_order=7）；
带内判据=矩形近似卷积 |f_spur − f_center| ≤ (BW_spur + BW_band)/2（BW_spur =
m·RF带宽 + n·LO带宽，谐波带宽线性缩放）；危险等级=阶数反比（≤3 high、
≤5 medium、其余 low）。只报频率落带不报电平（幅度需器件特性，out-of-scope）。

stage schema（顺序=信号流向）::

    {type: amp|mixer|filter|atten|cable, gain_db, nf_db?, iip3_dbm?,
     p1db_dbm?, bw_hz?, name?, il_source?}

- 无源级（filter/atten/cable）缺省 NF = −gain_db（T0 口径无源损耗 NF=插损）；
  amp/mixer 的 nf_db 缺失显式报错。
- skrf Network 实取插损的解析在 service 层（core 零 IO）：service 把实取值
  以显式 gain_db/il_source 传入，本模块不感知来源。

零 IO、不 import numpy/scipy/skrf（纯 math）——铁律 7 合规。
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Any

# k_B：SI 定义精确值（2019 SI，不引入 scipy.constants 依赖）
K_BOLTZMANN = 1.380649e-23  # J/K
DEFAULT_T_KELVIN = 290.0
DEFAULT_SNR_MIN_DB = 10.0
DEFAULT_MAX_ORDER = 7

STAGE_TYPES = ("amp", "mixer", "filter", "atten", "cable")
PASSIVE_TYPES = ("filter", "atten", "cable")  # T0 口径 NF=损耗
MAX_ABS_GAIN_DB = 1000.0  # 防溢出守卫（10^(±100) 线性域）

_HAZARD_HIGH_MAX_ORDER = 3
_HAZARD_MEDIUM_MAX_ORDER = 5
_HAZARD_ORDER = {"high": 0, "medium": 1, "low": 2}


# ─── 校验底座 ────────────────────────────────────────────────────────────────

def _finite(value: Any, name: str) -> float:
    """收敛入参为有限实数，否则 ValueError（纯数值守卫，不臆造）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def _finite_bounded(value: Any, name: str, *, lo: float,
                    allow_eq: bool = True) -> float:
    out = _finite(value, name)
    ok = out >= lo if allow_eq else out > lo
    if not ok:
        op = ">=" if allow_eq else ">"
        raise ValueError(f"{name} 必须 {op} {lo}，收到 {value!r}")
    return out


def _hazard_for_order(order: int) -> str:
    if order <= _HAZARD_HIGH_MAX_ORDER:
        return "high"
    if order <= _HAZARD_MEDIUM_MAX_ORDER:
        return "medium"
    return "low"


def _normalize_stage(index: int, raw: Any) -> dict[str, Any]:
    """校验并归一单级（无源级 NF 缺省=损耗；多余键原样透传）。"""
    if not isinstance(raw, dict):
        raise ValueError(f"stages[{index}] 必须是 dict，收到 {type(raw)!r}")
    stage = dict(raw)
    stype = stage.get("type")
    if stype not in STAGE_TYPES:
        raise ValueError(
            f"stages[{index}].type={stype!r} 未支持；可选 {list(STAGE_TYPES)}")
    if "gain_db" not in stage:
        raise ValueError(
            f"stages[{index}]（type={stype!r}）缺 gain_db；"
            "filter/atten 若由 S 参数取插损，请在 service 层解析后传入")
    gain_db = _finite_bounded(stage["gain_db"], f"stages[{index}].gain_db",
                              lo=-MAX_ABS_GAIN_DB)
    if gain_db > MAX_ABS_GAIN_DB:
        raise ValueError(
            f"stages[{index}].gain_db 必须 ≤ {MAX_ABS_GAIN_DB}，收到 {gain_db!r}")
    if "nf_db" in stage and stage["nf_db"] is not None:
        nf_db = _finite_bounded(stage["nf_db"], f"stages[{index}].nf_db", lo=0.0)
    elif stype in PASSIVE_TYPES:
        # T0 口径：无源损耗级的 NF = 插损（F = 1/G，损耗在 T0 全额转噪声）
        nf_db = -gain_db
        stage["nf_derived"] = True
    else:
        raise ValueError(
            f"stages[{index}]（type={stype!r}）缺 nf_db；"
            f"有源级 {list(STAGE_TYPES)} 中的 amp/mixer 必须显式给 NF，"
            "无源级缺省按 NF=插损（T0 口径）")
    for key in ("iip3_dbm", "p1db_dbm"):
        if stage.get(key) is not None:
            stage[key] = _finite(stage[key], f"stages[{index}].{key}")
    if stage.get("bw_hz") is not None:
        stage["bw_hz"] = _finite_bounded(stage["bw_hz"],
                                         f"stages[{index}].bw_hz", lo=0.0,
                                         allow_eq=False)
    stage["type"] = stype
    stage["gain_db"] = gain_db
    stage["nf_db"] = nf_db
    return stage


# ─── 1. 级联预算 ─────────────────────────────────────────────────────────────

def cascade_budget(
    stages: list[dict[str, Any]],
    *,
    snr_min_db: float = DEFAULT_SNR_MIN_DB,
    rx_power_dbm: float | None = None,
    bw_hz: float | None = None,
    t_kelvin: float = DEFAULT_T_KELVIN,
) -> dict[str, Any]:
    """级联预算：stage 列表 → 总增益/Friis NF/IIP3·OIP3/P1dB/噪声底/SFDR/
    灵敏度/链路裕量。公式口径见模块 docstring（§0）。

    Args:
        stages: 级表（顺序=信号流向），schema 见模块 docstring。
        snr_min_db: 解调所需最小 SNR（灵敏度口径）。
        rx_power_dbm: 接收功率（给定时输出链路裕量）。
        bw_hz: 系统噪声带宽 [Hz]；缺省取最后一个带 bw_hz 的级，两者皆无则
            显式报错（不静默默认）。
        t_kelvin: 等效热噪声温度 [K]（缺省 290）。

    Examples
    --------
    衰减器首级 + LNA（钉值与 tests/unit/test_cascade.py 钉 1 同源——
    解析恒等式：首级 3dB 衰减器把链路 NF 精确退化为 3+2 dB）：

    >>> from rfauto.core.cascade import cascade_budget
    >>> stages = [
    ...     {"type": "atten", "gain_db": -3.0, "nf_db": 3.0},
    ...     {"type": "amp", "gain_db": 20.0, "nf_db": 2.0, "iip3_dbm": -10.0},
    ... ]
    >>> r = cascade_budget(stages, snr_min_db=10.0, rx_power_dbm=-90.0,
    ...                    bw_hz=1e6)
    >>> r["gain_total_db"], r["nf_total_db"]
    (17.0, 5.0)
    >>> r["iip3_total_dbm"], r["oip3_total_dbm"]
    (-7.0, 10.0)
    >>> round(r["sfdr_db"], 9)
    67.983458129

    显式报错语义（不静默默认）：

    >>> cascade_budget([])
    Traceback (most recent call last):
        ...
    ValueError: stages 必须是非空级表（按信号流向排序）
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    norm = [_normalize_stage(i, s) for i, s in enumerate(stages)]

    snr = _finite_bounded(snr_min_db, "snr_min_db", lo=0.0)
    t_k = _finite_bounded(t_kelvin, "t_kelvin", lo=0.0, allow_eq=False)
    rx_dbm = None if rx_power_dbm is None else _finite(rx_power_dbm, "rx_power_dbm")

    gain_total_db = 0.0
    noise_factor = 0.0
    iip3_inv_sum = 0.0
    has_iip3 = False
    op1db_out_referred: list[tuple[int, float]] = []  # (级号, 输出参考 dBm)
    for i, st in enumerate(norm):
        gain_db = st["gain_db"]
        nf_lin = 10.0 ** (st["nf_db"] / 10.0)
        gain_before_db = gain_total_db
        gain_before_lin = 10.0 ** (gain_before_db / 10.0)
        if i == 0:
            noise_factor = nf_lin
        else:
            noise_factor += (nf_lin - 1.0) / gain_before_lin
        gain_total_db += gain_db
        if st.get("iip3_dbm") is not None:
            # 规格书勘误修正口径（见模块 docstring）：1/IIP3_tot = Σ G_pre/IIP3_i
            iip3_i_lin = 10.0 ** (st["iip3_dbm"] / 10.0)
            iip3_inv_sum += gain_before_lin / iip3_i_lin
            has_iip3 = True
        if st.get("p1db_dbm") is not None:
            op1db_out_referred.append((i, st["p1db_dbm"]))
        st["index"] = i
        st["gain_before_db"] = gain_before_db
        st["cum_gain_db"] = gain_total_db
        st["cum_nf_db"] = 10.0 * math.log10(noise_factor)
    # 二遍：每级之后的全部级增益和（P1dB 输出参考折算用）
    for i, st in enumerate(norm):
        st["gain_after_db"] = sum(s["gain_db"] for s in norm[i + 1:])
        st["op1db_out_referred_dbm"] = (
            None if st.get("p1db_dbm") is None
            else st["p1db_dbm"] + st["gain_after_db"])

    nf_total_db = 10.0 * math.log10(noise_factor)
    iip3_total_dbm = (10.0 * math.log10(1.0 / iip3_inv_sum)
                      if has_iip3 else None)
    oip3_total_dbm = (None if iip3_total_dbm is None
                      else iip3_total_dbm + gain_total_db)

    # P1dB 经验幂和（输出参考面；口径出处见模块 docstring——工程惯例非闭式）。
    # 必须用二遍折算后的 op1db_out_referred_dbm（OP1DB_i + G_after,i），
    # 不是本级原始 OP1dB——首版实现此处错用原始值（定向回收钉当场抓出）。
    p1db_out_dbm = None
    if op1db_out_referred:
        p1db_inv = sum(
            10.0 ** (-norm[i]["op1db_out_referred_dbm"] / 10.0)
            for i, _ in op1db_out_referred)
        p1db_out_dbm = 10.0 * math.log10(1.0 / p1db_inv)
    p1db_in_dbm = (None if p1db_out_dbm is None
                   else p1db_out_dbm - gain_total_db)

    if bw_hz is not None:
        bw_resolved = _finite_bounded(bw_hz, "bw_hz", lo=0.0, allow_eq=False)
        bw_source = "explicit"
    else:
        bw_resolved = next(
            (st["bw_hz"] for st in reversed(norm) if st.get("bw_hz") is not None),
            None)
        if bw_resolved is None:
            raise ValueError(
                "噪声带宽无法解析：未显式传 bw_hz，且没有任何级带 bw_hz——"
                "请显式传 bw_hz 或在末级（信道滤波）stage 给 bw_hz")
        bw_source = "last_stage"

    thermal_dbm_per_hz = 10.0 * math.log10(K_BOLTZMANN * t_k * 1e3)
    noise_floor_dbm = thermal_dbm_per_hz + 10.0 * math.log10(bw_resolved) + nf_total_db
    sensitivity_dbm = noise_floor_dbm + snr
    sfdr_db = (None if iip3_total_dbm is None
               else (2.0 / 3.0) * (iip3_total_dbm - noise_floor_dbm))
    link_margin_db = None if rx_dbm is None else rx_dbm - sensitivity_dbm

    return {
        "n_stages": len(norm),
        "gain_total_db": gain_total_db,
        "nf_total_db": nf_total_db,
        "iip3_total_dbm": iip3_total_dbm,
        "oip3_total_dbm": oip3_total_dbm,
        "p1db_out_dbm": p1db_out_dbm,
        "p1db_in_dbm": p1db_in_dbm,
        "p1db_convention": (
            "经验口径：各级 OP1dB 折算到链路输出后功率域幂和 "
            "1/P1dB=Σ 1/(OP1dB_i+G_after,i)（工程惯例，非教科书闭式）；"
            "p1db_dbm=该级输出 1dB 压缩点"),
        "iip3_convention": (
            "1/IIP3_tot = Σ G_pre,i/IIP3_i（线性 mW；教科书口径，规格书 "
            "§2 字面公式增益落分母系笔误，见模块 docstring 勘误）"),
        "bw_hz": bw_resolved,
        "bw_source": bw_source,
        "t_kelvin": t_k,
        "thermal_floor_dbm_per_hz": thermal_dbm_per_hz,
        "noise_floor_dbm": noise_floor_dbm,
        "sfdr_db": sfdr_db,
        "snr_min_db": snr,
        "sensitivity_dbm": sensitivity_dbm,
        "rx_power_dbm": rx_dbm,
        "link_margin_db": link_margin_db,
        "stages": norm,
    }


# ─── 2. 混频杂散搜索 ─────────────────────────────────────────────────────────

def spur_search(
    f_rf_hz: float,
    f_lo_hz: float,
    *,
    if_center_hz: float | None = None,
    if_bw_hz: float = 0.0,
    rf_bw_hz: float = 0.0,
    lo_bw_hz: float = 0.0,
    max_order: int = DEFAULT_MAX_ORDER,
) -> list[dict[str, Any]]:
    """混频杂散落带搜索：f_spur = |m·f_RF ± n·f_LO| 全阶枚举（纯频率几何，
    不报电平——幅度需器件特性，out-of-scope）。

    带内判据（矩形近似卷积）：|f_spur − f_center| ≤ (BW_spur + BW_band)/2，
    BW_spur = m·rf_bw_hz + n·lo_bw_hz。危险等级=阶数反比（≤3 high、≤5 medium、
    其余 low）。(1,1) 产物标记 role="fundamental"（期望变频产物）不计 spur。

    Args:
        f_rf_hz: RF 中心频率 [Hz]（>0）。
        f_lo_hz: 本振频率 [Hz]（>0）。
        if_center_hz: 目标 IF 中心 [Hz]；缺省 |f_RF − f_LO|。
        if_bw_hz: 目标 IF（或 RF）带宽 [Hz]（≥0）。
        rf_bw_hz: RF 信号带宽 [Hz]（≥0，谐波带宽线性缩放）。
        lo_bw_hz: LO 带宽 [Hz]（≥0；理想 LO 给 0）。
        max_order: 最大阶数 m+n（≥1，缺省 7）。

    Examples
    --------
    教科书组态（f_RF=2.4 GHz / f_LO=2.1 GHz、目标 IF=600 MHz；钉值与
    tests/unit/test_cascade.py TestSpurSearchTextbook 同源）：

    >>> from rfauto.core.cascade import spur_search
    >>> spurs = spur_search(2.4e9, 2.1e9, if_center_hz=600e6, if_bw_hz=1e5)
    >>> s = next(x for x in spurs
    ...          if (x["m"], x["n"], x["side"]) == (2, 2, "-"))
    >>> int(s["f_spur_hz"]), s["order"], s["hazard"], s["in_band"]
    (600000000, 4, 'medium', True)

    期望变频产物 (1,1) 标记为 fundamental，不混入 spur 计数：

    >>> fund = next(x for x in spurs if x["role"] == "fundamental")
    >>> (fund["m"], fund["n"]), int(fund["f_spur_hz"])
    ((1, 1), 300000000)
    """
    f_rf = _finite_bounded(f_rf_hz, "f_rf_hz", lo=0.0, allow_eq=False)
    f_lo = _finite_bounded(f_lo_hz, "f_lo_hz", lo=0.0, allow_eq=False)
    if_bw = _finite_bounded(if_bw_hz, "if_bw_hz", lo=0.0)
    rf_bw = _finite_bounded(rf_bw_hz, "rf_bw_hz", lo=0.0)
    lo_bw = _finite_bounded(lo_bw_hz, "lo_bw_hz", lo=0.0)
    if isinstance(max_order, bool) or not isinstance(max_order, int):
        raise ValueError(f"max_order 必须是整数，收到 {max_order!r}")
    if max_order < 1:
        raise ValueError(f"max_order 必须 ≥1，收到 {max_order!r}")
    if if_center_hz is None:
        if f_rf == f_lo:
            raise ValueError(
                "f_RF 与 f_LO 相等（自然 IF=0）且未显式给 if_center_hz——"
                "请显式传 if_center_hz")
        if_center = abs(f_rf - f_lo)
    else:
        if_center = _finite_bounded(if_center_hz, "if_center_hz", lo=0.0)

    spurs: list[dict[str, Any]] = []
    for m in range(0, max_order + 1):
        for n in range(0, max_order + 1):
            order = m + n
            if order < 1 or order > max_order:
                continue
            bw_spur = m * rf_bw + n * lo_bw
            for side, f_spur in (
                ("+", m * f_rf + n * f_lo),
                ("-", abs(m * f_rf - n * f_lo)),
            ):
                if f_spur <= 0.0:  # DC 产物（|m·f_RF − n·f_LO| ≡ 0）不入表
                    continue
                offset = f_spur - if_center
                in_band = abs(offset) <= 0.5 * (bw_spur + if_bw)
                role = "fundamental" if (m, n) == (1, 1) else "spur"
                spurs.append({
                    "m": m,
                    "n": n,
                    "side": side,
                    "order": order,
                    "f_spur_hz": f_spur,
                    "offset_from_if_hz": offset,
                    "bw_spur_hz": bw_spur,
                    "in_band": in_band,
                    "hazard": _hazard_for_order(order),
                    "role": role,
                })
    spurs.sort(key=lambda s: (s["order"], abs(s["offset_from_if_hz"]),
                              s["m"], s["n"], s["side"]))
    return spurs


# ─── 3. IF 频率规划扫掠 ──────────────────────────────────────────────────────

def if_plan_sweep(
    f_rf_hz: float,
    *,
    if_lo_hz: float,
    if_hi_hz: float,
    side: str = "low",
    n_points: int = 201,
    if_bw_hz: float = 0.0,
    rf_bw_hz: float = 0.0,
    lo_bw_hz: float = 0.0,
    max_order: int = DEFAULT_MAX_ORDER,
) -> dict[str, Any]:
    """IF 候选扫掠 → spurious-free 窗口（频率规划辅助）。

    每个候选 IF 重取本振（low 侧 f_LO=f_RF−IF；high 侧 f_LO=f_RF+IF，期望
    (1,1) 产物恒落在候选 IF 上），再按 spur_search 同口径判落带（排除
    fundamental）；输出逐点判定表 + 连续 spur-free 窗口（窗口边界=网格
    分辨率内的连续 free 点首末，不外推）。
    """
    f_rf = _finite_bounded(f_rf_hz, "f_rf_hz", lo=0.0, allow_eq=False)
    if_lo = _finite_bounded(if_lo_hz, "if_lo_hz", lo=0.0, allow_eq=False)
    if_hi = _finite_bounded(if_hi_hz, "if_hi_hz", lo=0.0, allow_eq=False)
    if if_lo >= if_hi:
        raise ValueError(
            f"if_lo_hz 必须 < if_hi_hz，收到 [{if_lo_hz!r}, {if_hi_hz!r}]")
    if side not in ("low", "high"):
        raise ValueError(f"side 必须是 'low' 或 'high'，收到 {side!r}")
    if isinstance(n_points, bool) or not isinstance(n_points, int):
        raise ValueError(f"n_points 必须是整数，收到 {n_points!r}")
    if n_points < 2:
        raise ValueError(f"n_points 必须 ≥2，收到 {n_points!r}")
    if side == "low" and if_hi >= f_rf:
        raise ValueError(
            f"low 侧注入要求 f_LO=f_RF−IF>0，即 if_hi_hz < f_rf_hz="
            f"{f_rf_hz!r}，收到 if_hi_hz={if_hi_hz!r}")

    points: list[dict[str, Any]] = []
    for k in range(n_points):
        if_c = if_lo + (if_hi - if_lo) * k / (n_points - 1)
        f_lo = f_rf - if_c if side == "low" else f_rf + if_c
        products = spur_search(
            f_rf, f_lo, if_center_hz=if_c, if_bw_hz=if_bw_hz,
            rf_bw_hz=rf_bw_hz, lo_bw_hz=lo_bw_hz, max_order=max_order)
        band_spurs = [p for p in products
                      if p["in_band"] and p["role"] == "spur"]
        if band_spurs:
            worst = min(band_spurs,
                        key=lambda p: (_HAZARD_ORDER[p["hazard"]],
                                       abs(p["offset_from_if_hz"])))
            worst_hazard = worst["hazard"]
            worst_spur = {"m": worst["m"], "n": worst["n"],
                          "side": worst["side"], "order": worst["order"],
                          "hazard": worst["hazard"],
                          "f_spur_hz": worst["f_spur_hz"]}
        else:
            worst_hazard = None
            worst_spur = None
        points.append({
            "if_center_hz": if_c,
            "f_lo_hz": f_lo,
            "n_spurs_in_band": len(band_spurs),
            "worst_hazard": worst_hazard,
            "worst_spur": worst_spur,
            "spurious_free": not band_spurs,
        })

    windows: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []
    for pt in [*points, None]:  # 哨兵收尾
        if pt is not None and pt["spurious_free"]:
            run.append(pt)
            continue
        if run:
            windows.append({"start_hz": run[0]["if_center_hz"],
                            "end_hz": run[-1]["if_center_hz"],
                            "n_points": len(run)})
            run = []
    n_free = sum(1 for pt in points if pt["spurious_free"])
    return {
        "side": side,
        "f_rf_hz": f_rf,
        "if_lo_hz": if_lo,
        "if_hi_hz": if_hi,
        "n_points": n_points,
        "if_bw_hz": if_bw_hz,
        "rf_bw_hz": rf_bw_hz,
        "lo_bw_hz": lo_bw_hz,
        "max_order": max_order,
        "n_points_free": n_free,
        "points": points,
        "windows": windows,
    }


# ─── 4. 非线性级联扩展（ME-18：IPn 合并 / IMn 外推 / P1dB 估计与压缩定位；
#        ME-19：AM-AM/AM-PM 多项式模型与级联加权）─────────────────────────────
#
# 口径来源（2026-09-27 实测抓取逐式核对，非转述记忆）：
# - Kundert《Accurate and Rapid Measurement of IP2 and IP3》
#   (www.designers-guide.org/Analysis/intercept-point.pdf, v1b 2002-05-22)：
#   · 式(1) IPn = P + ΔP/(n−1)——P=基波功率 dBm、ΔP=基波与 n 阶产物功率差 dB；
#     反解即 IMn(dBc) = (n−1)·(Pin − IPn)。
#   · 式(30) iIP3 = dB20(4a/3c)——三阶幂级数 x = a·u + c·u³ 的 IP3 电压闭式。
#   · 式(33) αCP² = (4a/3c)(1−10^(−1/20))（αCP 为幅度，即 [·]^½）与式(35)
#     iCP1dB ≈ iIP3 − 9.6 dB（纯三阶压缩估计；本文件常量
#     CP1_IP3_DELTA_THIRD_ORDER_DB = −10·log10(1−10^(−1/20)) = 9.6357 dB
#     即其精确值）。
# - RF Cafe "Cascaded 2-Tone, 2nd-Order Intercept Point (IP2)" 与
#   "…3rd-Order…(IP3)"（references/electrical/ip2.htm / ip3.htm）：级联合并式
#   1/IPn = Σ G_pre,i/IPn_i（线性 mW、逐对迭代；"do not use dB and dBm
#   values" verbatim）；产物电平 P_n = n·P_out − (n−1)·IPn（与 Kundert 式(1)
#   同构反解）。
# - RF Cafe "Cascaded 1 dB Compression Point (P1dB)"（references/electrical/
#   p1db.htm）：53 份随机选取 amp/mixer datasheet 的 IP3−P1dB 间距统计均值
#   11.7 dB（σ=2.9 dB，~68% 落 8.8–14.6 dB）——**单源统计口径**。
#
# 规格书勘误（先例：cascade_budget 的 iip3_convention 勘误注记）：任务书
# monthly_plan J 系写作 "IM_n(dBc) = n·(Pin−IPn)"，与上述双源相反——正确为
# (n−1)·(Pin−IPn)（IM3 斜率 2 dB/dB、IM5 斜率 4 dB/dB 为教科书普适结论；
# n 倍形式连 IM2 的 1 dB/dB 斜率都不满足）。本模块按权威双源实现，
# im_products_extrapolate 返回值带 spec_erratum 注记字段（判据书"Pin−IP5=−10
# → IM5=−50 dBc"同源笔误，正确值 −40 dBc）。
#
# 级联合并的叠加口径：**功率域（线性 mW）非相干叠加**——判据锚=两级等值
# IPn、G=1 → 合并值=单级−3.01 dB（等功率叠加；若同相电压叠加则 −6.02 dB，
# Kundert 论文未给级联相关性定论，如实缺位）。合并式权威源=RF Cafe ip2/ip3
# 级联页 + Pozar 教科书（见 cascade_budget docstring 同口径先引）。
# 更高阶（IP4+）合并式与 IP2/IP3 同构系业界工具惯例外推，无逐阶权威源核对
# （#122 如实标注）。级联 IMn 幅度直并式缺位（待证）：IMn 电平可经合并后的
# IIPn_tot 单级外推（cascade_ipn_merge → im_products_extrapolate），IMn 幅度
# 直接级联合并无权威闭式——不实现（Kundert 论文无此式）。
#
# 非线性面 stage schema（与 cascade_budget 键兼容但校验独立——不要求 type/
# nf_db，非线性扫描只消费增益与非线性参数）::
#
#     {gain_db, name?, ipn_dbm?, p1db_dbm?, p_sat_dbm?, alpha_deg_per_db?}
#
# - ipn_dbm：该级输入参考 n 阶截断点（IIPn，dBm）；p1db_dbm：该级**输出**
#   参考 1dB 压缩点（OP1dB，与 cascade_budget 同约定）；p_sat_dbm：饱和输出
#   功率（AM-PM 压缩深度归一用，可选）；alpha_deg_per_db：AM-PM 系数（°/dB）。
# - 数值 0.0 合法；判缺失一律 is not None（#364④）。

DEFAULT_P1DB_DELTA_DB = 11.7  # RF Cafe 53 份 datasheet 统计均值（σ=2.9 dB；单源）
# 纯三阶幂级数模型的 IP3−CP1 间距（dB）：−10·log10(1−10^(−1/20))。
# Kundert 式(35) verbatim："iCP1dB = iIP3 − 9.6 dB"（本常量=其精确值 9.6357…）。
CP1_IP3_DELTA_THIRD_ORDER_DB = -10.0 * math.log10(1.0 - 10.0 ** (-1.0 / 20.0))

_IPN_MERGE_CONVENTION = (
    "1/IPn_tot = Σ G_pre,i/IPn_i（线性 mW 功率域非相干叠加；RF Cafe ip2/ip3 "
    "级联页 + Pozar 教科书口径；锚=两级等值 IPn、G=1 → 合并=单级−3.01 dB）")
_IM_CONVENTION = (
    "IMn(dBc) = (n−1)·(Pin − IPn)——Kundert intercept-point.pdf 式(1) "
    "IPn = P + ΔP/(n−1) 反解；RF Cafe P_n = n·P_out − (n−1)·IPn 同构")
_IM_CASCADE_PENDING = (
    "级联 IMn 幅度直并式缺位（待证）：可经合并 IIPn_tot 单级外推"
    "（cascade_ipn_merge → 本函数）；IMn 幅度直接级联合并无权威闭式，不臆造")


def _complex_coeff(value: Any, name: str) -> complex:
    """收敛入参为有限复数（bool/str 显式拒收，df7+⑯ 同源）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, complex)):
        raise ValueError(f"{name} 必须是实数或复数，收到 {value!r}")
    c = complex(value)
    if not (math.isfinite(c.real) and math.isfinite(c.imag)):
        raise ValueError(f"{name} 必须为有限复数，收到 {value!r}")
    return c


def _normalize_nl_stage(index: int, raw: Any) -> dict[str, Any]:
    """非线性面级表校验（轻量独立于 _normalize_stage：不要求 type/nf_db；
    可选键缺失=None 语义，数值 0.0 合法，判缺失 is not None）。"""
    if not isinstance(raw, dict):
        raise ValueError(f"stages[{index}] 必须是 dict，收到 {type(raw)!r}")
    stage = dict(raw)
    if "gain_db" not in stage:
        raise ValueError(f"stages[{index}] 缺 gain_db")
    gain_db = _finite_bounded(stage["gain_db"], f"stages[{index}].gain_db",
                              lo=-MAX_ABS_GAIN_DB)
    if gain_db > MAX_ABS_GAIN_DB:
        raise ValueError(
            f"stages[{index}].gain_db 必须 ≤ {MAX_ABS_GAIN_DB}，收到 {gain_db!r}")
    stage["gain_db"] = gain_db
    if stage.get("name") is not None and not isinstance(stage["name"], str):
        raise ValueError(f"stages[{index}].name 必须是 str，收到 {stage['name']!r}")
    for key in ("ipn_dbm", "p1db_dbm", "p_sat_dbm", "alpha_deg_per_db"):
        if stage.get(key) is not None:
            stage[key] = _finite(stage[key], f"stages[{index}].{key}")
    return stage


def ipn_merge_linear(ipn_linear: list[float],
                     gain_pre_linear: list[float]) -> float:
    """n 阶截断点合并核（线性域）：1/IPn = Σ G_pre,i/IPn_i → IPn（线性 mW）。

    ipn_linear[i]：第 i 级输入参考 IPn（线性功率，必须 >0——线性域 ≤0 即
    ValueError，本函数是"IPn≤0 → ValueError"判据的落点；dBm 入口不禁负 dBm，
    混频器 IIP3<0 dBm 物理合法，与 cascade_budget 口径一致，如实登记）。
    gain_pre_linear[i]：该级之前全部级增益之积（线性，必须 >0）。空表 ValueError。
    """
    if not ipn_linear or len(ipn_linear) != len(gain_pre_linear):
        raise ValueError(
            "ipn_linear 与 gain_pre_linear 必须同长非空，收到 "
            f"{len(ipn_linear)}/{len(gain_pre_linear)}")
    inv = 0.0
    for i, (ipn, g) in enumerate(zip(ipn_linear, gain_pre_linear, strict=True)):
        if not isinstance(ipn, (int, float)) or isinstance(ipn, bool) \
                or not math.isfinite(float(ipn)) or ipn <= 0.0:
            raise ValueError(f"ipn_linear[{i}] 必须为正的有限实数，收到 {ipn!r}")
        if not isinstance(g, (int, float)) or isinstance(g, bool) \
                or not math.isfinite(float(g)) or g <= 0.0:
            raise ValueError(
                f"gain_pre_linear[{i}] 必须为正的有限实数，收到 {g!r}")
        inv += g / ipn
    return 1.0 / inv


def cascade_ipn_merge(stages: list[dict[str, Any]], *,
                      order: int) -> dict[str, Any]:
    """n 阶截断点级联合并（IP2/IP3/通用 IPn 同一幂和式——合并代数与阶数无关，
    order 只进元数据与产出注记）。

    闭式（线性 mW）：1/IPn_tot = Σᵢ G_pre,i/IPn_i，G_pre,i=该级之前全部级增益
    之积；输出参考恒等式 OIPn_tot = IIPn_tot + G_tot（dB）。

    Examples
    --------
    两级（LNA IIPn=−10 dBm、增益 20 dB；混频 IIPn=0 dBm、增益 10 dB）：

    >>> from rfauto.core.cascade import cascade_ipn_merge
    >>> r = cascade_ipn_merge(
    ...     [{"name": "lna", "gain_db": 20.0, "ipn_dbm": -10.0},
    ...      {"name": "mix", "gain_db": 10.0, "ipn_dbm": 0.0}], order=3)
    >>> round(r["ipn_total_input_dbm"], 6)
    -20.413927
    >>> r["ipn_total_output_dbm"] == r["ipn_total_input_dbm"] + r["gain_total_db"]
    True
    >>> r["dominant_stage"]
    1
    """
    if isinstance(order, bool) or not isinstance(order, int):
        raise ValueError(f"order 必须是整数，收到 {order!r}")
    if order < 2:
        raise ValueError(f"order 必须 ≥2（截断点从 2 阶起），收到 {order!r}")
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    norm = [_normalize_nl_stage(i, s) for i, s in enumerate(stages)]
    ipn_lin: list[float] = []
    g_pre: list[float] = []
    g_run = 1.0
    gain_total_db = 0.0
    for i, st in enumerate(norm):
        v = st.get("ipn_dbm")
        if v is None:
            raise ValueError(
                f"stages[{i}] 缺 ipn_dbm——合并式要求全级提供（跳过=静默造假）；"
                "如需'缺 IPn 级跳过'语义请改用 cascade_budget")
        ipn_lin.append(10.0 ** (v / 10.0))
        g_pre.append(g_run)
        g_run *= 10.0 ** (st["gain_db"] / 10.0)
        if not math.isfinite(g_run) or g_run > 1e300:
            raise ValueError(
                f"stages[{i}] 处前级增益积溢出（>1e300）——增益表异常")
        gain_total_db += st["gain_db"]
    total_lin = ipn_merge_linear(ipn_lin, g_pre)
    inv = 1.0 / total_lin  # = Σ g_pre/ipn（ipn_merge_linear 的分子）
    contributions = [
        {"index": i,
         "name": norm[i].get("name"),
         "share": (g_pre[i] / ipn_lin[i]) / inv}
        for i in range(len(norm))]
    dominant = max(range(len(norm)), key=lambda i: contributions[i]["share"])
    order_note = (
        "合并代数与阶数无关（任意 IPn 同构）；IP2/IP3 有 RF Cafe 明示式，"
        "更高阶为业界工具惯例外推（无逐阶权威源核对，#122 标注）")
    return {
        "order": order,
        "n_stages": len(norm),
        "gain_total_db": gain_total_db,
        "ipn_total_input_dbm": 10.0 * math.log10(total_lin),
        "ipn_total_output_dbm": 10.0 * math.log10(total_lin) + gain_total_db,
        "contributions": contributions,
        "dominant_stage": dominant,
        "convention": _IPN_MERGE_CONVENTION,
        "order_scope_note": order_note,
        "im_cascade_status": _IM_CASCADE_PENDING,
    }


def im_products_extrapolate(pin_dbm: float, ipn_dbm: float,
                            order: int) -> dict[str, Any]:
    """单级 IMn 产物外推：IMn(dBc) = (n−1)·(Pin − IPn)（Kundert 式(1) 反解）。

    外推域守卫：Pin ≤ IPn（Pin > IPn 时外推律预测产物高于载波=非物理，交截
    点即模型有效域边界；Pin == IPn → 0.0 dBc 逐位合法）。

    Examples
    --------
    >>> from rfauto.core.cascade import im_products_extrapolate
    >>> im_products_extrapolate(-20.0, -10.0, 3)["im_n_dbc"]
    -20.0
    >>> im_products_extrapolate(-30.0, -20.0, 5)["im_n_dbc"]
    -40.0
    """
    if isinstance(order, bool) or not isinstance(order, int):
        raise ValueError(f"order 必须是整数，收到 {order!r}")
    if order < 2:
        raise ValueError(f"order 必须 ≥2（IM 产物从 2 阶起），收到 {order!r}")
    pin = _finite(pin_dbm, "pin_dbm")
    ipn = _finite(ipn_dbm, "ipn_dbm")
    if pin > ipn:
        raise ValueError(
            f"外推域越界：Pin={pin} dBm > IPn={ipn} dBm——外推律在该域预测"
            "产物高于载波（正 dBc）非物理；Pin ≤ IPn 为有效域（等号=0 dBc）")
    return {
        "order": order,
        "pin_dbm": pin,
        "ipn_dbm": ipn,
        "im_n_dbc": (order - 1.0) * (pin - ipn),
        "convention": _IM_CONVENTION,
        "spec_erratum": (
            "任务书 monthly_plan J 系 'IM_n(dBc)=n·(Pin−IPn)' 系笔误：正确为 "
            "(n−1)·(Pin−IPn)（Kundert 式(1)/RF Cafe 双源一致；IM3 斜率 2、"
            "IM5 斜率 4 dB/dB），本字段如实登记勘误"),
        "cascade_status": _IM_CASCADE_PENDING,
    }


def p1db_from_oip3(oip3_dbm: float, *,
                   delta_db: float = DEFAULT_P1DB_DELTA_DB) -> float:
    """P1dB 工程估计：P1dB ≈ OIP3 − Δ（Δ 缺省 11.7 dB）。

    Δ=11.7 dB 出处（单源注明）：RF Cafe "Cascaded 1 dB Compression Point"
    页对 53 份随机选取 amp/mixer datasheet 的统计均值（σ=2.9 dB，~68% 落
    8.8–14.6 dB）。纯三阶幂级数模型的理论间距见
    CP1_IP3_DELTA_THIRD_ORDER_DB（9.6357 dB，Kundert 式(35) "−9.6 dB"）。
    适用前提：链路各级均未工作于饱和区（RF Cafe verbatim 口径，见
    cascade_compression_scan 的 caution 字段）。

    >>> from rfauto.core.cascade import p1db_from_oip3
    >>> p1db_from_oip3(30.0)
    18.3
    >>> p1db_from_oip3(30.0, delta_db=10.0)
    20.0
    """
    o = _finite(oip3_dbm, "oip3_dbm")
    d = _finite_bounded(delta_db, "delta_db", lo=0.0)
    return o - d


def cascade_compression_scan(
    stages: list[dict[str, Any]],
    *,
    pin_dbm: float,
    delta_db: float = DEFAULT_P1DB_DELTA_DB,
    oip3_dbm: float | None = None,
) -> dict[str, Any]:
    """逐级压缩余量扫描 + "最先压缩级"定位 + OIP3−Δ 的 P1dB 估计（回退量表）。

    信号电平链 L_i = Pin + Σ_{j≤i} G_j（第 i 级输出电平）；压缩余量
    headroom_i = OP1dB_i − L_i（OP1dB=该级输出参考 P1dB，与 cascade_budget
    同约定）；首个 headroom < 0 的级即最先压缩级（headroom == 0 恰在阈值、
    不计压缩）。oip3_dbm 显式入参 > 级表合并（全级带 ipn_dbm 时按 order=3
    幂和取输出参考）> None——两级皆无则 p1db_estimate_dbm=None（不臆造）。

    Examples
    --------
    前级强后级弱构造例（第二级先压缩）：

    >>> from rfauto.core.cascade import cascade_compression_scan
    >>> r = cascade_compression_scan(
    ...     [{"name": "pa1", "gain_db": 30.0, "p1db_dbm": 30.0},
    ...      {"name": "pa2", "gain_db": 0.0, "p1db_dbm": 5.0}],
    ...     pin_dbm=-10.0, oip3_dbm=30.0)
    >>> r["first_compression_stage"], r["first_compression_name"]
    (1, 'pa2')
    >>> r["p1db_estimate_dbm"]
    18.3
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    norm = [_normalize_nl_stage(i, s) for i, s in enumerate(stages)]
    pin = _finite(pin_dbm, "pin_dbm")
    delta = _finite_bounded(delta_db, "delta_db", lo=0.0)
    oip3_in = None if oip3_dbm is None else _finite(oip3_dbm, "oip3_dbm")

    level = pin
    rows: list[dict[str, Any]] = []
    first_idx: int | None = None
    for i, st in enumerate(norm):
        level += st["gain_db"]
        op1db = st.get("p1db_dbm")
        headroom = None if op1db is None else op1db - level
        compressing = headroom is not None and headroom < 0.0
        if compressing and first_idx is None:
            first_idx = i
        rows.append({
            "index": i,
            "name": st.get("name"),
            "gain_db": st["gain_db"],
            "level_out_dbm": level,
            "op1db_dbm": op1db,
            "headroom_db": headroom,
            "compressing": compressing,
        })

    if oip3_in is not None:
        oip3_resolved = oip3_in
        oip3_source = "explicit"
    elif all(st.get("ipn_dbm") is not None for st in norm):
        oip3_resolved = cascade_ipn_merge(norm, order=3)["ipn_total_output_dbm"]
        oip3_source = "stage_merge_order3"
    else:
        oip3_resolved = None
        oip3_source = None
    headrooms = [r["headroom_db"] for r in rows if r["headroom_db"] is not None]
    return {
        "pin_dbm": pin,
        "delta_db": delta,
        "delta_reference": (
            "RF Cafe 53 份 amp/mixer datasheet 统计：均值 11.7 dB、σ=2.9 dB"
            "（单源口径）"),
        "oip3_dbm": oip3_resolved,
        "oip3_source": oip3_source,
        "p1db_estimate_dbm": None if oip3_resolved is None else oip3_resolved - delta,
        "first_compression_stage": first_idx,
        "first_compression_name": (
            None if first_idx is None else rows[first_idx]["name"]),
        "n_compressing": sum(1 for r in rows if r["compressing"]),
        "min_headroom_db": min(headrooms) if headrooms else None,
        "stages": rows,
        "caution": (
            "OIP3−Δ 估计仅当各级均未工作于饱和/压缩区成立（RF Cafe verbatim："
            "'only holds when none of the stages are normally operating "
            "outside of the linear region'）；first_compression_stage 非 None "
            "时该前提已破，估计值只作参考，以逐级 headroom 表（回退量表）为准"),
    }


def am_am_pm_third_order(a1: float, a3: float, v_in: float) -> dict[str, Any]:
    """三阶幂级数单级模型 x = a₁·u + a₃·u³ 的 AM-AM/AM-PM/IM3/1dB 压缩闭式。

    口径（Kundert intercept-point.pdf §4，逐式核对）：
    - 单音驱动（β=0，式(31)）：基波 phasor = a₁v·(1 + ¾(a₃/a₁)v²)，记
      r = ¾(a₃/a₁)v²——AM-AM 增益变化 = 20log10|1+r|，AM-PM 相位误差 =
      arg(1+r)（a₃ 复数时非零、实数时恒 0）；
    - 双音等幅 IM3（α=β=v，式(25)）：IM3(dBc) = 20log10(¾|a₃/a₁|v²)；
      iIP3 电压 = √(4|a₁|/(3|a₃|))（式(30) dB20(4a/3c) 电压域）；
    - 1dB 压缩幅度：|1+xu|² = 10^(−1/10)（u=v²、x=¾a₃/a₁）二次方程的较小正根
      ——a₃ 实负时严格退化为 Kundert 式(33)：αCP² = (4a₁/(3|a₃|))
      (1−10^(−1/20))，αCP=[·]^½（判据：与独立闭式 rel 1e-12 逐位带）。

    幅度域=电压（V）；功率换算需调用方给参考阻抗（本模块不臆造 50Ω）。
    a3=0 合法（线性：IM3/压缩/IIP3 如实 None，AM-AM/AM-PM 严格 0）。

    Examples
    --------
    >>> from rfauto.core.cascade import am_am_pm_third_order
    >>> r = am_am_pm_third_order(1.0, -0.01, 0.1)
    >>> round(r["im3_dbc"], 6)
    -82.498775
    >>> r["am_pm_phase_deg"]
    0.0
    """
    a1c = _complex_coeff(a1, "a1")
    a3c = _complex_coeff(a3, "a3")
    v = _finite_bounded(v_in, "v_in", lo=0.0, allow_eq=False)
    if abs(a1c) == 0.0:
        raise ValueError("a1 必须非零（小信号增益系数）")
    r = 0.75 * (a3c / a1c) * v * v
    has_a3 = a3c != 0
    # 1dB 压缩：|1+xu|² = 10^(−1/10)（u=v²）二次方程较小正根
    v1db = None
    no_compress_note = None
    if has_a3:
        x = r / (v * v)
        quad_a = abs(x) ** 2
        quad_b = 2.0 * x.real
        disc = quad_b * quad_b - 4.0 * quad_a * (1.0 - 10.0 ** (-0.1))
        if disc < 0.0:
            no_compress_note = "判别式<0：该模型在实域无 1dB 压缩交越（增益扩张型）"
        else:
            u = (-quad_b - math.sqrt(disc)) / (2.0 * quad_a)
            if u > 0.0:
                v1db = math.sqrt(u)
            else:
                no_compress_note = "首个正交越非压缩（增益扩张先于压缩），如实不报"
    return {
        "a1": a1c,
        "a3": a3c,
        "v_in_v": v,
        "small_signal_gain_db": 20.0 * math.log10(abs(a1c)),
        "am_am_gain_db": 20.0 * math.log10(abs(a1c * (1.0 + r))),
        "am_am_delta_db": 20.0 * math.log10(abs(1.0 + r)),
        "am_pm_phase_deg": math.degrees(cmath.phase(1.0 + r)),
        "im3_dbc": (None if not has_a3
                    else 20.0 * math.log10(0.75 * abs(a3c / a1c) * v * v)),
        "iip3_amplitude_v": (None if not has_a3
                             else math.sqrt(4.0 * abs(a1c) / (3.0 * abs(a3c)))),
        "v_1db_v": v1db,
        "no_compression_note": no_compress_note,
        "cp1_ip3_delta_db": CP1_IP3_DELTA_THIRD_ORDER_DB,
        "conventions": {
            "am_am_am_pm": "单音 β=0（Kundert 式(31)）：基波=a₁v(1+¾(a₃/a₁)v²)",
            "im3": "双音等幅 α=β=v（Kundert 式(25)）：IM3=20log10(¾|a₃/a₁|v²)",
            "v_1db": "|1+xu|²=10^(−1/10) 较小正根；a₃ 实负→Kundert 式(33) αCP",
        },
    }


def cascade_am_pm(stages: list[dict[str, Any]], *,
                  pin_dbm: float) -> dict[str, Any]:
    """级联 AM-PM 主导级加权估计（**工程近似**——无标准级联闭式，#122 如实标注）。

    公式（本模块约定定义，非权威源推导；与 core/pa_architectures.py
    "IP5/AM-PM 级联式缺权威源=待证标注"的预声明同口径）::

        L_i    = Pin + Σ_{j≤i} G_j                                （级输出电平）
        comp_i = clip((L_i − OP1dB_i)/(P_sat_i − OP1dB_i), 0, 1)  （P_sat 给定）
               = max(0, L_i − OP1dB_i)                            （无 P_sat）
        w_i    = comp_i / Σⱼ compⱼ                                （近饱和主导）
        α_tot  = Σᵢ w_i·α_i                                （°/dB，输入每 dB）

    Σcomp = 0（无级处于压缩区）→ α_tot=None（不外推不臆造）。
    锚（单测钉）：单级链 w=1 → α_tot ≡ α_1（逐位）；等压缩等 α → 算术均值。

    Examples
    --------
    >>> from rfauto.core.cascade import cascade_am_pm
    >>> r = cascade_am_pm(
    ...     [{"gain_db": 20.0, "p1db_dbm": 25.0, "p_sat_dbm": 27.0,
    ...       "alpha_deg_per_db": 1.5}], pin_dbm=10.0)
    >>> r["alpha_total_deg_per_db"]
    1.5
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    norm = [_normalize_nl_stage(i, s) for i, s in enumerate(stages)]
    pin = _finite(pin_dbm, "pin_dbm")
    for i, st in enumerate(norm):
        if st.get("alpha_deg_per_db") is None:
            raise ValueError(f"stages[{i}] 缺 alpha_deg_per_db（AM-PM 面全级必填，"
                             "fail-fast 不静默跳级）")
        if st.get("p1db_dbm") is None:
            raise ValueError(f"stages[{i}] 缺 p1db_dbm（压缩深度度量需要 OP1dB）")
        psat = st.get("p_sat_dbm")
        if psat is not None and psat <= st["p1db_dbm"]:
            raise ValueError(
                f"stages[{i}].p_sat_dbm={psat} 必须 > p1db_dbm="
                f"{st['p1db_dbm']}（饱和点低于 1dB 压缩点非物理）")

    level = pin
    comps: list[float] = []
    rows: list[dict[str, Any]] = []
    for i, st in enumerate(norm):
        level += st["gain_db"]
        op1db = st["p1db_dbm"]
        psat = st.get("p_sat_dbm")
        if psat is not None:
            raw = (level - op1db) / (psat - op1db)
            comp = min(1.0, max(0.0, raw))
        else:
            comp = max(0.0, level - op1db)
        comps.append(comp)
        rows.append({"index": i, "name": st.get("name"),
                     "level_out_dbm": level, "op1db_dbm": op1db,
                     "p_sat_dbm": psat, "comp": comp,
                     "alpha_deg_per_db": st["alpha_deg_per_db"]})
    comp_sum = math.fsum(comps)
    weights = [0.0] * len(comps)
    alpha_total: float | None = None
    status = "no_stage_in_compression"
    if comp_sum > 0.0:
        weights = [c / comp_sum for c in comps]
        alpha_total = math.fsum(
            w * rows[i]["alpha_deg_per_db"] for i, w in enumerate(weights))
        status = "engineering_approximation"
    dominant = max(range(len(rows)),
                   key=lambda i: (weights[i], -i)) if comp_sum > 0.0 else None
    return {
        "pin_dbm": pin,
        "alpha_total_deg_per_db": alpha_total,
        "dominant_stage": dominant,
        "weights": weights,
        "per_stage": rows,
        "status": status,
        "formula": ("comp_i=clip((L_i−OP1dB_i)/(P_sat_i−OP1dB_i),0,1)；"
                    "w_i=comp_i/Σcomp；α_tot=Σ w_i·α_i（本模块约定定义）"),
        "note": (
            "工程近似（#122 如实标注）：级联 AM-PM 无标准闭式（与 "
            "core/pa_architectures.py 预声明同口径）——加权式为约定定义，"
            "非权威源推导；单级链恒等 α_tot≡α_1 为其自洽锚"),
    }


@dataclass
class NonlinearCascadeResult:
    """ME-18/ME-19 非线性级联扫描结果容器（新 dataclass——既有
    cascade_budget/spur_search/if_plan_sweep 的返回结构零改动）。

    merge：cascade_ipn_merge 输出（全级带 ipn_dbm 时）；im_at_pin：合并后
    IIPn 在 pin_dbm 处的单级 IMn 外推；compression：cascade_compression_scan
    输出（含 P1dB 估计与最先压缩级，需 pin_dbm）；am_pm：cascade_am_pm 输出
    （任一级带 alpha_deg_per_db 时）。
    """

    order: int
    merge: dict[str, Any] | None
    im_at_pin: dict[str, Any] | None
    compression: dict[str, Any] | None
    am_pm: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化平面字典（纯透传，不再加工）。"""
        return {
            "order": self.order,
            "merge": self.merge,
            "im_at_pin": self.im_at_pin,
            "compression": self.compression,
            "am_pm": self.am_pm,
        }


def cascade_nonlinear_scan(
    stages: list[dict[str, Any]],
    *,
    order: int = 3,
    pin_dbm: float | None = None,
    delta_db: float = DEFAULT_P1DB_DELTA_DB,
    oip3_dbm: float | None = None,
) -> NonlinearCascadeResult:
    """一站式非线性扫描：IPn 合并 + IMn 外推 + 压缩定位/P1dB 估计 + AM-PM 加权。

    子面可用性规则（缺输入如实 None，不臆造）：
    - merge：全级带 ipn_dbm 才合并（混合缺级=静默造假，记 None）；
    - im_at_pin：merge 可用且给 pin_dbm 时，对合并 IIPn 单级外推（阶数同 order）；
    - compression：给 pin_dbm 即出表（P1dB 估计需 oip3：显式入参 > order=3 级表
      合并 > None）；pin_dbm=None 时 compression/im_at_pin 均缺；
    - am_pm：全级带 alpha_deg_per_db 时需要 pin_dbm（缺即显式报错）；
      混合缺级记 None（all-or-None，与 merge 同语义）。
    """
    if not isinstance(stages, (list, tuple)) or not stages:
        raise ValueError("stages 必须是非空级表（按信号流向排序）")
    norm = [_normalize_nl_stage(i, s) for i, s in enumerate(stages)]
    has_ipn = [st.get("ipn_dbm") is not None for st in norm]

    merge = cascade_ipn_merge(norm, order=order) if all(has_ipn) else None
    im_at_pin = None
    compression = None
    am_pm = None
    if pin_dbm is not None:
        if merge is not None:
            im_at_pin = im_products_extrapolate(
                _finite(pin_dbm, "pin_dbm"),
                merge["ipn_total_input_dbm"], order)
        compression = cascade_compression_scan(
            norm, pin_dbm=pin_dbm, delta_db=delta_db, oip3_dbm=oip3_dbm)
    if all(st.get("alpha_deg_per_db") is not None for st in norm):
        # all-or-None（与 merge 同语义）：混合缺 alpha 走 cascade_am_pm 的
        # fail-fast 会误伤其余子面——扫描面如实记 None
        if pin_dbm is None:
            raise ValueError(
                "级表全级带 alpha_deg_per_db（AM-PM 面）但未给 pin_dbm——"
                "压缩深度度量需要工作电平，请补 pin_dbm")
        am_pm = cascade_am_pm(norm, pin_dbm=pin_dbm)
    return NonlinearCascadeResult(
        order=order, merge=merge, im_at_pin=im_at_pin,
        compression=compression, am_pm=am_pm)
