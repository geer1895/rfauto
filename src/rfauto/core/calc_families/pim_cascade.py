"""PIM 多节点累计/级联预算族（aurora72 A4-B 席域 3，R7 第二梯队 T11）。

出处（PIM 测量规范口径+第一性合成式，正文物理口径节转录）：
- pim_nodes_combine：多节点 PIM 电平双口径合成（非相干功率和
  10log10ΣP/相干同相上界 20log10Σ√P，对数域恒等式第一性；极限
  语义=IEC 62037/运营商验收惯例双口径）。
- pim_cascade_budget：载波功率幂级数平移律 order n 产物∝V^n→n·ΔP
  （幂级数第一性；参考条件=IEC 62037 双音每载波 +43dBm）。

两键：pim_nodes_combine（多节点无源互调电平合成：相干同相最坏情形
20log10Σ√P 与非相干功率和 10log10ΣP 双口径 + 节点占比） /
pim_cascade_budget（工程链：参考条件电平→斜率平移到实际载波功率→
双口径累计→限值裕量；order=IM2/IM3… 通用阶数口径）。

与既有互调面的边界（语义防撞，R7 §③ T11 + 本次 triple-grep 证据）
--------------------------------------------------------
- cascade_budget（calc_families/budget.py，有源链）= 增益加权**截点**
  级联（Friis 1/IIP3_tot=Σ G_pre/IIP3_i + B5 IIP2 同式幂和）——逐级
  参考"截点"；本族只做**多节点 PIM 绝对电平累计**（实测电平注入式，
  无增益加权语义），两者不撞。
- core/cascade.py cascade_ipn_merge / budget.Budget（core 函数，未注册
  键）= 同上有源链口径；budget.py B5 docstring 明示"二阶电压相干相加
  的最坏上限……须自行换算"——本族 coherent 分支即该口径在**电平注入
  式**下的实现（20log10Σ√P），与有源链截点式互补不重复。
- core/pim_products.py / pim_empirical.py（core 函数面，未注册键）=
  **单节点**产物枚举与斜率换算（PIM 绝对电平"不产幅度预测数字"铁律
  沿用——本族节点电平全部实测注入，不做绝对值预测）；本键斜率平移
  消费其幂级数精确律（order n 产物平移 n·ΔP）与 IEC 62037 +43dBm
  参考条件常数，不复制枚举产核。
- R7 §② 复核："功率容量/PIM 已覆盖"（R2 证伪段）指 power_capacity
  面——多节点累计键面全仓 grep 零命中（本次 triple-grep：pim|级联|
  相干 三路均无累计语义键），立项无重复。

物理口径（docstring 写死，#1c/#300 出处纪律）
----------------------------------------------
- 节点电平合成（同一 IM 产物频点、N 个无源节点，IEC 62037/运营商
  口径双极限）：

      非相干功率和（随机相位统计口径，业界验收惯例）
          P_tot = 10·log10( Σ_i 10^{P_i/10} )                [dBm]
      相干同相最坏情形（电压线性相加上界，最坏相位对齐）
          P_worst = 20·log10( Σ_i 10^{P_i/20} )              [dBm]

  恒等式（测试钉）：N 等电平节点 → 非相干 +10log10N、相干 +20log10N；
  两等电平 → +3.0103 / +6.0206 dB；spread=P_worst−P_tot ∈
  [0, 20log10N]（等电平取上界）。相位统计带如实以双口径+spread 呈现
  （中间相位分布不做伪精确统计假设）。
- 载波功率平移（幂级数精确律，pim_empirical 同口径）：order n 产物
  ∝ V^n → 载波功率变化 ΔP 平移 n·ΔP（IM3 缺省斜率 3 dB/dB）；实测
  斜率普遍偏离（接触非线性机理，pim_empirical 登记文献 2–5 常见，
  其硬守卫 [1,6]）——slope_db_per_db 覆盖值须 >0，缺省=order（精确
  律）。参考条件=IEC 62037 双音每载波 +43 dBm（pim_empirical 同源
  常数）。

验证（in-output xcheck + 测试侧独立重算，#118 不自证）
------------------------------------------------------
- 合成键：双口径测试侧独立重算逐位；N=1 退化恒等（双口径=本级电平、
  spread=0）；等电平 10log10N/20log10N 恒等；spread∈[0,20log10N] 界。
- 预算键：p_carrier=p_ref → 与合成键同电平输入结果逐位一致（跨键
  互证）；ΔP=1dB/IM3 → 每节点与总量恰 +3.0dB；单节点退化=本级电平
  平移；限值裕量=limit−total 恒等式。

守卫：levels_dbm 非空且逐元素有限实数；nodes 非空且逐条 level_dbm
有限；order∈[2, MAX_PIM_ORDER]（与 pim_products 同上限，函数内惰性
import 单源）；p_carrier_dbm/p_ref_dbm 有限（p_ref 缺省 43）；slope
覆盖值>0；pim_limit_dbm 有限可选；越界一律显式拒绝。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

# IEC 62037 双音每载波参考条件（pim_empirical 同源常数口径）
_IEC62037_REF_DBM = 43.0
# order 防呆下限（互调产物最低二阶；上限与 pim_products.MAX_PIM_ORDER
# 函数内惰性单源对齐）
_ORDER_MIN = 2

_SOURCES = {
    "combine": "IEC 62037/运营商口径双极限：非相干 10log10ΣP 与相干同相 "
               "20log10Σ√P（N 等电平 +10log10N / +20log10N 恒等）",
    "budget": "幂级数精确律（order n 产物平移 n·ΔP，pim_empirical 同口径）+ "
              "IEC 62037 双音 +43dBm/载波参考条件；实测斜率偏离见 pim_empirical "
              "登记（常见 2–5，覆盖值须 >0）",
}


def _combine_levels_dbm(levels_dbm: list[float]) -> dict[str, Any]:
    """双口径合成核心（纯函数）：→（非相干 dBm，相干 dBm，spread）。"""
    p_lin = [10.0 ** (lv / 10.0) for lv in levels_dbm]
    p_incoherent_dbm = 10.0 * math.log10(sum(p_lin))
    v_sum = sum(math.sqrt(p) for p in p_lin)
    p_coherent_dbm = 20.0 * math.log10(v_sum)
    spread_db = p_coherent_dbm - p_incoherent_dbm
    return p_incoherent_dbm, p_coherent_dbm, spread_db


# ─── 键 1：多节点电平合成 ────────────────────────────────────────────────────

@register_calculator(
    "pim_nodes_combine",
    "多节点 PIM 电平累计：同一 IM 产物频点上 N 个无源节点实测电平双口径"
    "合成——非相干功率和 10log10Σ10^(Pi/10)（随机相位统计，验收惯例）与"
    "相干同相最坏 20log10Σ10^(Pi/20)（电压线性相加上界），spread=两者差"
    "（相位统计带如实以双极限呈现）；节点占比+主导节点直出。锚：N 等电平"
    "→+10log10N/+20log10N 恒等；两等电平 +3.0103/+6.0206dB；N=1 退化恒等",
    (("levels_dbm", "list[float] dBm 各节点同一产物的实测电平（≥1 个，"
      "逐元素有限；电平实测注入——PIM 绝对值不可预测铁律沿用）"),),
    required=("levels_dbm",),
)
def pim_nodes_combine(levels_dbm: list[float]) -> dict[str, Any]:
    if not isinstance(levels_dbm, (list, tuple)):
        raise ValueError(
            f"pim_nodes_combine: levels_dbm 须为数值列表，得到 "
            f"{type(levels_dbm).__name__}")
    if len(levels_dbm) == 0:
        raise ValueError(
            "pim_nodes_combine: levels_dbm 须非空（至少 1 个节点电平）")
    levels = [_finite(lv, f"levels_dbm[{i}]")
              for i, lv in enumerate(levels_dbm)]
    p_inc, p_coh, spread = _combine_levels_dbm(levels)
    p_lin = [10.0 ** (lv / 10.0) for lv in levels]
    p_sum = sum(p_lin)
    shares_pct = [100.0 * p / p_sum for p in p_lin]
    dominant = max(range(len(levels)), key=lambda i: levels[i])
    return {
        "n_nodes": len(levels),
        "levels_dbm": [round(lv, 12) for lv in levels],
        "p_incoherent_dbm": round(p_inc, 12),
        "p_coherent_dbm": round(p_coh, 12),
        "spread_db": round(spread, 12),
        "shares_pct": [round(s, 9) for s in shares_pct],
        "dominant_index": dominant,
        "note": (
            "双口径=相位统计带的双极限（非相干=随机相位功率和、相干=同相"
            "最坏上界），spread∈[0,20log10N]（等电平取上界）；中间相位"
            "分布不做伪精确统计假设；节点电平必须同产物频点（跨频点电平"
            "不可直接合成）"),
        "source": _SOURCES["combine"],
    }


# ─── 键 2：PIM 级联预算（参考条件→平移→累计→限值裕量）──────────────────────

@register_calculator(
    "pim_cascade_budget",
    "PIM 级联预算：N 节点实测电平（IEC 62037 双音 +43dBm/载波参考条件，"
    "缺省口径）按幂级数精确律平移到实际载波功率（order n 产物平移 "
    "n·ΔP，IM3 缺省斜率 3；实测斜率偏离走 slope_db_per_db 覆盖）→ 双口"
    "径累计（pim_nodes_combine 同核）→ 可选 pim_limit_dbm 裕量（双口径各"
    "给，相干裕量负=最坏情形超限如实报告）。锚：p_carrier=p_ref 与合成"
    "键逐位互证；ΔP=1dB/IM3 → 每节点恰 +3.0dB；单节点退化=本级电平平移",
    (("nodes", "list[dict] 节点清单（每条 {'level_dbm': 参考条件实测电平, "
      "'name': 可选}；≥1 条）"),
     ("p_carrier_dbm", "float dBm 实际每载波载波功率（双音口径，有限）"),
     ("order", "int 互调产物阶数（IM2/IM3…，∈[2,64] 与 pim_products 同上限"
      "口径，缺省 3）"),
     ("p_ref_dbm", "float dBm 参考条件每载波功率（缺省 43=IEC 62037 口径）"),
     ("slope_db_per_db", "float 实测斜率覆盖（>0 可选；缺省=order 精确律；"
      "实测常见 2–5，pim_empirical 硬守卫 [1,6] 口径注记）"),
     ("pim_limit_dbm", "float dBm 系统限值（可选；给则输出双口径裕量）")),
    required=("nodes", "p_carrier_dbm"),
)
def pim_cascade_budget(nodes: list[dict[str, Any]], p_carrier_dbm: float,
                       order: int = 3, p_ref_dbm: float = _IEC62037_REF_DBM,
                       slope_db_per_db: float | None = None,
                       pim_limit_dbm: float | None = None) -> dict[str, Any]:
    from rfauto.core.pim_products import MAX_PIM_ORDER  # 上限单源（惰性）

    if not isinstance(nodes, (list, tuple)):
        raise ValueError(
            f"pim_cascade_budget: nodes 须为 list[dict]，得到 "
            f"{type(nodes).__name__}")
    if len(nodes) == 0:
        raise ValueError(
            "pim_cascade_budget: nodes 须非空（至少 1 个节点）")
    if isinstance(order, bool) or not isinstance(order, int):
        raise ValueError(
            f"pim_cascade_budget: order 须为整数（IM_n 阶数），得到 "
            f"{order!r}")
    if not _ORDER_MIN <= order <= MAX_PIM_ORDER:
        raise ValueError(
            f"pim_cascade_budget: order 须 ∈[{_ORDER_MIN},{MAX_PIM_ORDER}]"
            f"（与 pim_products 同上限口径），得到 {order!r}")
    p_carrier = _finite(p_carrier_dbm, "p_carrier_dbm")
    p_ref = _finite(p_ref_dbm, "p_ref_dbm")
    if slope_db_per_db is not None:
        slope = _finite(slope_db_per_db, "slope_db_per_db")
        if slope <= 0.0:
            raise ValueError(
                "pim_cascade_budget: slope_db_per_db 必须 >0（实测斜率偏离"
                "精确律的登记值，pim_empirical 常见 2–5），得到 "
                f"{slope_db_per_db!r}")
    else:
        slope = float(order)
    limit: float | None = None
    if pim_limit_dbm is not None:
        limit = _finite(pim_limit_dbm, "pim_limit_dbm")

    shift_db = slope * (p_carrier - p_ref)
    node_rows: list[dict[str, Any]] = []
    levels_at_carrier: list[float] = []
    for i, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise ValueError(
                f"pim_cascade_budget: nodes[{i}] 须为 dict（含 level_dbm），"
                f"得到 {type(raw).__name__}")
        if "level_dbm" not in raw:
            raise ValueError(
                f"pim_cascade_budget: nodes[{i}] 缺 level_dbm（参考条件实测"
                "电平，必填）")
        level_ref = _finite(raw["level_dbm"], f"nodes[{i}].level_dbm")
        level_at = level_ref + shift_db
        levels_at_carrier.append(level_at)
        node_rows.append({
            "name": str(raw.get("name", f"node{i}")),
            "level_ref_dbm": round(level_ref, 12),
            "level_at_carrier_dbm": round(level_at, 12),
        })
    p_inc, p_coh, spread = _combine_levels_dbm(levels_at_carrier)
    margin_inc = None if limit is None else limit - p_inc
    margin_coh = None if limit is None else limit - p_coh
    note_tail = (
        "；相干裕量为负=最坏相位对齐情形超限，如实报告不拒绝"
        if limit is not None and margin_coh < 0.0 else "")
    return {
        "n_nodes": len(nodes),
        "order": order,
        "slope_db_per_db": round(slope, 12),
        "p_carrier_dbm": p_carrier,
        "p_ref_dbm": p_ref,
        "shift_db": round(shift_db, 12),
        "pim_limit_dbm": limit,
        "nodes": node_rows,
        "levels_at_carrier_dbm": [round(lv, 12) for lv in levels_at_carrier],
        "p_incoherent_dbm": round(p_inc, 12),
        "p_coherent_dbm": round(p_coh, 12),
        "spread_db": round(spread, 12),
        "margin_incoherent_db": (
            None if margin_inc is None else round(margin_inc, 12)),
        "margin_coherent_db": (
            None if margin_coh is None else round(margin_coh, 12)),
        "note": (
            "节点电平=参考条件实测注入（PIM 绝对值不可预测铁律沿用）；"
            "平移=幂级数精确律 slope·ΔP（缺省 slope=order，实测斜率偏离"
            "按覆盖值——跨功率窗机理转变时须实测复检，pim_empirical 登记纪"
            "律）；累计=双口径相位统计带（相干=最坏上界，与有源链 budget."
            "py B5'二阶最坏情形须自行换算'口径互补——本键即电平注入式实现）"
            + note_tail),
        "source": _SOURCES["budget"],
    }
