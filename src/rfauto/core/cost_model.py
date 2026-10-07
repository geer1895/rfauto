"""EP-3 成本模块确定性内核（用户自录容器——零内置价格，铁律 7）。

规格书 研究扩充 round18 §二 EP-3：price_tier
声明式（verified-web 纪律）+ 板材利用率几何 + 批量-单价参数化容器
（**用户自录散点，不内置厂商快照**）。

口径：

- **零内置价格**：本模块任何函数都不持有、不缺省、不回填任何价格数值；
  单价只能来自用户自录条目（每个条目强制带 provenance 三键
  source/retrieved_date/tier——fab_profiles 逐字段 source_url/retrieved_
  date/verification 外部数据治理范式同源）。verified-web 纪律=条目声明
  tier + 来源，内核不做网络验证（离线确定性，验证语义留消费面）。
- **price_tier 声明式词表**：``proto``（打样档）/``volume``（批量档）/
  ``web-verified``（网页已核档）/``quoted``（供应商报价档）/
  ``user-recorded``（用户自录其他）；词表外 ValueError（声明式=枚举闭合，
  防自由文本漂移）。
- **板材利用率几何**：panel（拼板）上轴对齐铺 board（不重叠、不出界），
  两摆放（原方向 / 旋转 90°）取优：n = floor(W_p/w)·floor(H_p/h) 与
  floor(W_p/h)·floor(H_p/w) 的较大者；utilization = n·w·h/(W_p·H_p)。
  一阶平铺几何（不含工艺边/间距/混合摆放排样——如实在缺省注记披露，
  排样 NP 问题不冒充最优，只做两方向轴对齐包络）。
- **批量-单价参数化容器**：同一条目（item key）的多档散点
  [(qty, unit_price)] 按量升序成阶梯插值曲线：区间内线性插值、恰在节点
  取节点价、**域外如实 ValueError 拒绝外推**（#316 多报不放过——外推价
  是编造数字，违反铁律 7 精神）。同量双价=数据冲突 ValueError。
- **合计面**：Σ(qty × unit_price)，全部条目 currency 标签一致才可相加
  （混币种 ValueError——币种换算是外部语义，静默相加=编造）。

**objectives 的 cost_usd 帕累托维**：core/objectives.py 为既有文件（本席
只新增不改动），接线留归属面批次——本内核提供 cost_usd 标量语义
（bom_totals.total），可被 objectives 消费。

接口纪律：同 core/production_data.py（纯 stdlib、dict 进出 JSON 可序列
化、bool 显式拒收、非法 ValueError、无 IO、无全局状态）。
"""

from __future__ import annotations

import itertools
import math
from typing import Any

__all__ = [
    "PRICE_TIERS",
    "bom_totals",
    "panel_utilization",
    "quantity_price_curve",
    "unit_price_at",
    "validate_price_point",
]

PRICE_TIERS = ("proto", "volume", "web-verified", "quoted", "user-recorded")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: Any, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须为非空字符串")
    return value


def validate_price_point(raw: Any) -> dict[str, Any]:
    """单条价格散点校验+归一（provenance 三键强制：item/source/tier +
    retrieved_date；unit_price>0、qty 正数）。

    **零内置**：本函数不提供任何缺省价；缺 provenance 即 ValueError。
    """
    if not isinstance(raw, dict):
        raise ValueError("价格条目必须为 dict")
    item = _text(raw.get("item"), "item")
    qty = _positive(raw.get("qty"), "qty")
    unit_price = _positive(raw.get("unit_price"), "unit_price")
    source = _text(raw.get("source"), "source")
    tier = _text(raw.get("tier"), "tier")
    if tier not in PRICE_TIERS:
        raise ValueError(f"tier 必须在声明式词表内 {list(PRICE_TIERS)}，得 {tier!r}")
    retrieved = _text(raw.get("retrieved_date"), "retrieved_date")
    out: dict[str, Any] = {
        "item": item,
        "qty": qty,
        "unit_price": unit_price,
        "source": source,
        "tier": tier,
        "retrieved_date": retrieved,
    }
    if raw.get("currency") is not None:
        out["currency"] = _text(raw.get("currency"), "currency")
    if raw.get("note") is not None:
        out["note"] = _text(raw.get("note"), "note")
    return out


def quantity_price_curve(points: Any) -> dict[str, Any]:
    """同一条目的批量-单价散点 → 升序阶梯曲线（节点去重冲突检查）。"""
    if not isinstance(points, (list, tuple)) or not points:
        raise ValueError("points 必须为非空列表")
    rows = sorted(
        (validate_price_point(p) for p in points), key=lambda r: r["qty"]
    )
    for a, b in itertools.pairwise(rows):
        if a["qty"] == b["qty"] and a["unit_price"] != b["unit_price"]:
            raise ValueError(
                f"item={a['item']!r} 同量双价冲突 qty={a['qty']}: "
                f"{a['unit_price']} vs {b['unit_price']}（数据冲突如实拒绝）"
            )
    # 同量同价=重复录入，去重保留一条（确定性：保留首条来源）
    deduped: list[dict[str, Any]] = []
    for r in rows:
        if deduped and r["qty"] == deduped[-1]["qty"]:
            continue
        deduped.append(r)
    return {
        "item": deduped[0]["item"],
        "qty": [r["qty"] for r in deduped],
        "unit_price": [r["unit_price"] for r in deduped],
        "points": deduped,
    }


def unit_price_at(curve: Any, qty: Any) -> dict[str, Any]:
    """给定量 → 单价（节点取节点价；区间内线性插值；域外 ValueError 拒绝外推）。

    返回带 ``interpolated`` 标志与相邻节点（插值语义可复核）。
    """
    qs = [_positive(q, "qty") for q in curve["qty"]]
    ps = [_positive(p, "unit_price") for p in curve["unit_price"]]
    q = _positive(qty, "qty")
    if q < qs[0] or q > qs[-1]:
        raise ValueError(
            f"qty={q} 落在自录散点域 [{qs[0]}, {qs[-1]}] 之外——拒绝外推"
            f"（外推价=编造数字，请先补录该量档散点）"
        )
    for i, knot in enumerate(qs):
        if q == knot:
            return {
                "unit_price": ps[i],
                "interpolated": False,
                "bracket": None,
                "qty": q,
            }
    hi = next(i for i, knot in enumerate(qs) if knot > q)
    lo = hi - 1
    t = (q - qs[lo]) / (qs[hi] - qs[lo])
    price = ps[lo] + t * (ps[hi] - ps[lo])
    return {
        "unit_price": price,
        "interpolated": True,
        "bracket": {"qty_lo": qs[lo], "qty_hi": qs[hi], "price_lo": ps[lo], "price_hi": ps[hi]},
        "qty": q,
    }


def panel_utilization(
    board_w_mm: Any,
    board_h_mm: Any,
    panel_w_mm: Any,
    panel_h_mm: Any,
) -> dict[str, Any]:
    """拼板利用率（两方向轴对齐包络，取优；不含工艺边/间距——如实披露）。"""
    w = _positive(board_w_mm, "board_w_mm")
    h = _positive(board_h_mm, "board_h_mm")
    pw = _positive(panel_w_mm, "panel_w_mm")
    ph = _positive(panel_h_mm, "panel_h_mm")
    n0 = math.floor(pw / w) * math.floor(ph / h)
    n90 = math.floor(pw / h) * math.floor(ph / w)
    if n0 >= n90:
        n, rotated = n0, False
    else:
        n, rotated = n90, True
    area = w * h
    return {
        "boards_per_panel": n,
        "rotated": rotated,
        "board_area_mm2": area,
        "panel_area_mm2": pw * ph,
        "utilized_area_mm2": n * area,
        "utilization": (n * area) / (pw * ph),
        "note": "轴对齐两方向包络；不含工艺边/板间距/异形混合排样（一阶几何，非排样最优）",
    }


def bom_totals(lines: Any, *, resolve_price: Any = None) -> dict[str, Any]:
    """BOM 合计：Σ(qty × unit_price)。

    - lines：[{"item", "qty", "unit_price"?, "currency"?}...]；带 unit_price
      的行直用（行级自录价），不带则必须给 resolve_price(item, qty)→float
      回调（消费面用 unit_price_at 绑定，内核不持价——零内置价格）。
    - currency 全表一致才可相加；混币种/单行缺失且他行有币种标签时
      ValueError（币种语义不静默混算）。
    """
    if not isinstance(lines, (list, tuple)):
        raise ValueError("lines 必须为列表")
    if not lines:
        raise ValueError("lines 不能为空（空 BOM 合计=0 是编造语义，如实拒绝）")
    currencies: set[str] = set()
    total = 0.0
    items_out: list[dict[str, Any]] = []
    for raw in lines:
        if not isinstance(raw, dict):
            raise ValueError("BOM 行必须为 dict")
        item = _text(raw.get("item"), "item")
        qty = _positive(raw.get("qty"), "qty")
        if raw.get("unit_price") is not None:
            price = _positive(raw.get("unit_price"), "unit_price")
        else:
            if resolve_price is None:
                raise ValueError(f"item={item!r} 无行级单价且未提供 resolve_price")
            price = _positive(resolve_price(item, qty), f"resolve_price({item!r})")
        if raw.get("currency") is not None:
            currencies.add(_text(raw.get("currency"), "currency"))
        line_total = qty * price
        total += line_total
        items_out.append({"item": item, "qty": qty, "unit_price": price, "total": line_total})
    if len(currencies) > 1:
        raise ValueError(f"混币种 {sorted(currencies)} 不可相加（币种换算是外部语义）")
    out: dict[str, Any] = {
        "items": items_out,
        "total": total,
        "n_lines": len(items_out),
    }
    if currencies:
        out["currency"] = next(iter(currencies))
    return out
