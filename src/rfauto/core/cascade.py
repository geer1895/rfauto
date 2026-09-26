"""DP-5 系统级预算引擎 + 混频杂散搜索（纯函数，零 IO，微秒级确定性内核）。

规格：docs/plan_deepdive_specs_20260924.md §DP-5；判据书：
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

import math
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
