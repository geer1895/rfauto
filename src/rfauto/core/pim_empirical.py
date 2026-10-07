"""PIM 阶数/功率经验换算面（NX-12 星载 PIM：PIM3 幅值经验式+登记边界）。

ge8d 波·席D4（runs/ge8_followup/wave_d/seat_d_all.md §席D4）；条目
研究扩充 round14 NX-12「星载 PIM 多载波扩展：
pim_products 双载波→列表载波+下行带落入扫描+微放电裕度口径」及其一致性
审计注记「N 载波扩展子件与 EM-6 同件，以 EM-6 为唯一产核；本件保留星载
场景注记消费」。

本件只落席任务书口径「无源互调**阶数/功率闭式**（PIM3 幅值经验式双源+
登记边界；真机 no-go 如实）」。与邻接件关系（全部消费、零修改、零复制
产核）：
- core/pim_products.py：双载波产物**枚举+实测 dBc 归并**面（既有铁律 7
  口径"不产幅度预测数字"不变）。本件不扩 N 载波枚举（EM-6 唯一产核
  注记），只在"已有实测参考点"的前提下做**功率换算外推**。
- core/multipactor.py：微放电面（multi_carrier_equivalent_power_w N 载波
  等效功率 + multipactor_susceptibility_check 裕度）——星载下行注记
  经此消费，本件不复制机制内核。
- EM-6（core/spur_templates.py）：限值评估面；N 载波枚举产核归属处。

出处等级（#118：双源=可复算推导+文献；#df6-⑨ 检索不可达=如实 UNVERIFIED）
----------------------------------------------------------------------
- 阶数/功率闭式（**精确**，来自幂级数非线性模型，可复算推导）：
  产物 (m,n) 幅度 ∝ V₁ᵐ·V₂ⁿ → 载波功率变化时产物绝对电平（dBm）平移
      ΔP_pim(dB) = m·ΔP₁ + n·ΔP₂。
  双载波同升 ΔP：阶 k=m+n 产物升 k dB（三阶 3dB/dB、五阶 5dB/dB）；
  只升 f₁：2f₁−f2 升 2 dB（m=2 贡献）。tests 以幂级数 i(v)=v+εv³ 双音
  整数周期 DFT 独立复核（零泄漏），斜率实测=3.00…/2.00…。
- PIM3 幅值经验式（**经验**，需实测锚点，非绝对预测）：
      PIM3(P) [dBm] = PIM3(P_ref) [dBm] + k·(P − P_ref)
      PIM3(P) [dBc] = PIM3(P_ref) [dBc] + (k−1)·(P − P_ref)
  理论斜率 k=3（三次项）；文献实测斜率普遍偏离（接触非线性/铁磁材料
  机理不同）——**双源**：
    源①（可复算推导）：幂级数三次项 P∝P³ ⟹ 3 dB/dB（tests 数值复核）；
    源②（文献，2026-10-03 检索实取片段）：PIM 行业训练材料「~3 dB
    change in PIM level for every 1 dB carrier power」（PIM Training
    deck, scribd 片段）；「Theoretically PIM products will grow by 3 dB
    for 1 dB change in input power」（Innovative PIM & S-parameter
    measurement 讲义片段, ampnuts.ru 镜像）；Zelenchuk et al. 2008
    （微带 PIM3 ∝ P³）。同批片段明示实测斜率偏离 3 dB/dB 的机理面。
  参考测试条件：IEC 62037 双音每载波 +43 dBm（core/pim_products 同源
  口径）。斜率登记域：硬守卫 [1.0, 6.0]（实测报道常见 2–5；域外=输入
  错误，不静默钳位）。
- 登记边界（真机 no-go，如实）：
    ① PIM **绝对电平**不可由本面预测——材质/镀层/接触压力/扭转/老化工
      艺强相关，无通用权威闭式（core/pim_products 铁律 7 口径沿用）；
      一切绝对值必须实测注入。
    ② N>2 载波 PIM 枚举不在本件（EM-6 唯一产核注记）；本件换算式对
      任意 (m,n) 成立，但枚举域仍以 pim_products 双载波/EM-6 为准。
    ③ 星载场景：微放电（multipactor）与 PIM 是**两种独立机理**，裕度
      各自评估；本面仅注记消费 multipactor 面，不做机理合成。
    ④ 经验外推只在斜率真实为 k 的功率窗内有效——跨窗（机理转变/压缩）
      外推无效，调用方须自带实测复检（登记级如实）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.multipactor import (
    multi_carrier_equivalent_power_w,
    multipactor_susceptibility_check,
)
from rfauto.core.pim_products import MAX_PIM_ORDER, enumerate_pim_products

# PIM3 理论斜率（三次幂级数）：双载波同升 1 dB → IM3 升 3 dB
IM3_POWER_SLOPE_DB_PER_DB = 3.0
# 斜率硬守卫域（实测报道常见 2–5；域外=输入错误不钳位）
PIM_SLOPE_GUARD = (1.0, 6.0)
# 行业参考测试条件（IEC 62037 口径，与 core/pim_products 同源）
IEC62037_REF_CARRIER_DBM = 43.0

_NO_GO_REGISTRY: tuple[dict[str, str], ...] = (
    {"id": "no_absolute_pim_prediction",
     "statement": "PIM 绝对电平不可预测（材质/工艺强相关无通用闭式）——"
                  "绝对值必须实测注入（IEC 62037 双音 +43 dBm 参考条件）",
     "scope": "本面与 core/pim_products 共同遵守"},
    {"id": "no_ncarrier_enumeration_here",
     "statement": "N>2 载波 PIM 枚举以 EM-6 为唯一产核（round14 一致性"
                  "审计注记）；本件只做 (m,n) 功率换算",
     "scope": "本件"},
    {"id": "no_multipactor_pim_synthesis",
     "statement": "微放电与 PIM 机理独立，裕度各自评估，不做机理合成",
     "scope": "星载注记面"},
    {"id": "no_real_machine_claim",
     "statement": "本面为经验换算面，无真机标定——真机验证 no-go，"
                  "跨功率窗外推须实测复检",
     "scope": "本件"},
)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限实数，收到 {value!r}")
    return out


def product_level_shift_db(m: int, n: int, dp1_db: float,
                           dp2_db: float) -> float:
    """阶 (m,n) 产物绝对电平平移 ΔP = m·ΔP₁ + n·ΔP₂（幂级数精确闭式）。

    Examples
    --------
    >>> from rfauto.core.pim_empirical import product_level_shift_db
    >>> product_level_shift_db(2, 1, 1.0, 1.0)   # IM3 双载波同升 1 dB
    3.0
    >>> product_level_shift_db(2, 1, 1.0, 0.0)   # 只升 f1 → +2 dB
    2.0
    """
    mi = _order_index(m, "m")
    ni = _order_index(n, "n")
    if mi + ni > MAX_PIM_ORDER:
        raise ValueError(
            f"m+n={mi + ni} 超出防呆上限 {MAX_PIM_ORDER}（与 pim_products "
            "同上限口径）")
    return mi * _finite(dp1_db, "dp1_db") + ni * _finite(dp2_db, "dp2_db")


def _order_index(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须是整数，收到 {value!r}")
    if value < 1:
        raise ValueError(f"{name} 必须 ≥1（互调产物两侧载波均参与），"
                         f"收到 {value!r}")
    return int(value)


def extrapolate_pim3(dbc_at_ref: float, p_ref_dbm_per_carrier: float,
                     p_dbm_per_carrier: float,
                     *, slope_db_per_db: float = IM3_POWER_SLOPE_DB_PER_DB
                     ) -> dict[str, Any]:
    """PIM3 幅值经验外推（需实测参考点；k=3 理论斜率，实测斜率可传）。

    PIM3(P)[dBm] = (dbc_at_ref + P_ref) + k·(P − P_ref)；
    PIM3(P)[dBc] = dbc_at_ref + (k−1)·(P − P_ref)。
    k 缺省 3（三次幂级数理论斜率——源①可复算推导 / 源②行业训练材料
    实取片段，见 docstring 双源）；实测斜率偏离时显式传 slope_db_per_db
    （硬守卫 [1,6]，实测常见 2–5）。

    Examples
    --------
    >>> from rfauto.core.pim_empirical import extrapolate_pim3
    >>> r = extrapolate_pim3(-110.0, 43.0, 46.0)
    >>> r["pim_dbm"], r["pim_dbc"]
    (-58.0, -104.0)
    """
    dbc = _finite(dbc_at_ref, "dbc_at_ref")
    p_ref = _finite(p_ref_dbm_per_carrier, "p_ref_dbm_per_carrier")
    p = _finite(p_dbm_per_carrier, "p_dbm_per_carrier")
    k = _finite(slope_db_per_db, "slope_db_per_db")
    lo, hi = PIM_SLOPE_GUARD
    if not (lo <= k <= hi):
        raise ValueError(
            f"slope_db_per_db 必须在 [{lo}, {hi}]（实测报道常见 2–5；"
            f"域外=输入错误不钳位），收到 {slope_db_per_db!r}")
    dp = p - p_ref
    pim_dbm = dbc + p_ref + k * dp
    pim_dbc = dbc + (k - 1.0) * dp
    return {
        "pim_dbm": round(pim_dbm, 12),
        "pim_dbc": round(pim_dbc, 12),
        "slope_db_per_db": k,
        "p_ref_dbm_per_carrier": p_ref,
        "p_dbm_per_carrier": p,
        "reference_condition": f"IEC 62037 双音每载波 +{IEC62037_REF_CARRIER_DBM}"
                               " dBm 口径（参考点须实测注入）",
        "provenance": "k=3：幂级数三次项（可复算推导，tests 数值复核）+"
                      "行业 PIM 训练材料 ~3dB/1dB（2026-10-03 实取片段）；"
                      "实测斜率偏离机理面已登记",
    }


def product_power_shift(m: int, n: int, dp1_db: float, dp2_db: float,
                        dbc_at_ref: float) -> dict[str, Any]:
    """阶 (m,n) 产物在新载波功率下的电平（dBm 平移精确 + dBc 重基）。

    dBc 参考取 f₁ 载波（调用方语义；参考载波平移 = dp1_db）。
    """
    shift = product_level_shift_db(m, n, dp1_db, dp2_db)
    dbc = _finite(dbc_at_ref, "dbc_at_ref")
    return {
        "m": m, "n": n,
        "level_shift_db": round(shift, 12),
        "dbc_at_new_power": round(dbc + shift - _finite(dp1_db, "dp1_db"), 12),
        "note": "dBc 参考取 f₁ 载波；绝对电平=参考点实测 dBm+shift（本函数"
                "不持绝对参考点，见 no_absolute_pim_prediction 登记）",
    }


def no_go_registry() -> list[dict[str, str]]:
    """登记边界（真机 no-go）只读视图。"""
    return [dict(x) for x in _NO_GO_REGISTRY]


def satellite_multipactor_annotation(freq_hz: float, gap_m: float,
                                     carrier_powers_w: list,
                                     *,
                                     required_margin_db: float = 6.0,
                                     coherent: bool = False,
                                     z0_ohm: float = 50.0) -> dict[str, Any]:
    """星载下行注记：N 载波等效功率→微放电裕度（消费 multipactor 面）。

    纯消费包装：multi_carrier_equivalent_power_w（N 载波等效功率/峰值
    电压）+ multipactor_susceptibility_check（裕度判定）；PIM 面与本面
    机理独立（登记 no_multipactor_pim_synthesis）。本函数不产 PIM 数字。

    Examples
    --------
    >>> from rfauto.core.pim_empirical import satellite_multipactor_annotation
    >>> r = satellite_multipactor_annotation(8.4e9, 0.5e-3, [10.0, 10.0])
    >>> r["equivalent"]["n_carriers"]
    2
    """
    f = _finite(freq_hz, "freq_hz")
    if f <= 0.0:
        raise ValueError(f"freq_hz 必须为正，收到 {freq_hz!r}")
    d = _finite(gap_m, "gap_m")
    if d <= 0.0:
        raise ValueError(f"gap_m 必须为正，收到 {gap_m!r}")
    if not isinstance(carrier_powers_w, list) or not carrier_powers_w:
        raise ValueError("carrier_powers_w 须为非空 list（星载多载波口径）")
    eq = multi_carrier_equivalent_power_w(carrier_powers_w, coherent=coherent,
                                          z0_ohm=z0_ohm)
    chk = multipactor_susceptibility_check(
        f, d, carrier_powers_w=carrier_powers_w, carrier_coherent=coherent,
        z0_ohm=z0_ohm, required_margin_db=required_margin_db)
    return {
        "equivalent": eq,
        "multipactor": chk,
        "note": "微放电与 PIM 机理独立（no_multipactor_pim_synthesis）；"
                "N 载波 PIM 枚举以 EM-6 为唯一产核（no_ncarrier_"
                "enumeration_here）",
    }


def pim_products_power_note(f1_hz: float, f2_hz: float, *, p_max: int = 7,
                            dp1_db: float = 0.0, dp2_db: float = 0.0,
                            amplitudes: list[dict[str, Any]] | None = None
                            ) -> dict[str, Any]:
    """消费 pim_products 枚举：给已注入实测 dBc 的产物附 (m,n) 功率平移
    注记——枚举+实测归并产核仍在 pim_products（amplitudes 透传），本函数
    只加注记，不产幅度（铁律 7）。"""
    ps = enumerate_pim_products(f1_hz, f2_hz, p_max=p_max,
                                amplitudes=amplitudes)
    d1 = _finite(dp1_db, "dp1_db")
    d2 = _finite(dp2_db, "dp2_db")
    noted = []
    for prod in ps.products:
        if prod.dbc is None:
            continue
        noted.append(product_power_shift(prod.m, prod.n, d1, d2, prod.dbc)
                     | {"key": {"m": prod.m, "n": prod.n, "side": prod.side}})
    return {
        "n_products": ps.n_products,
        "n_with_measured_dbc": len(noted),
        "power_shift_notes": noted,
        "note": "枚举+实测归并产核=core/pim_products（不变）；本函数只对"
                "已注入实测 dBc 的产物附功率平移注记",
    }
