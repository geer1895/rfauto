"""EP-3 成本录入容器服务面（用户自录——零内置价格，规则 4 service 先行）。

规格 研究扩充 round18 §二 EP-3。数值全在
core/cost_model.py（铁律 7）；本模块是录入容器（成本账本 book 的
增查/合计/装载）与 resolve_price 绑定面，零物理数字零内置快照价。

**objectives cost_usd 帕累托维接线**：core/objectives.py 为既有文件
（本席只新增），接线留归属面批次——本文件提供 cost_usd 标量语义
（bom_totals/cost_usd_estimate 返回值）。

接口纪律：dict/JSON 进出；load/save 只走 JSON 文件；无 CLI/MCP 面。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.cost_model import (
    PRICE_TIERS,
    bom_totals,
    panel_utilization,
    quantity_price_curve,
    unit_price_at,
    validate_price_point,
)

__all__ = [
    "PRICE_TIERS",
    "add_price_points",
    "cost_usd_estimate",
    "empty_book",
    "load_book",
    "panelized_board_cost",
    "save_book",
]

_BOOK_SCHEMA = "rfauto-cost-book/v1"


def empty_book() -> dict[str, Any]:
    """空成本账本（零内置价格：初始价表为空表是唯一缺省语义）。"""
    return {"schema": _BOOK_SCHEMA, "price_points": []}


def add_price_points(book: Any, points: Any) -> dict[str, Any]:
    """向账本追加用户自录价格散点（逐条 validate_price_point 校验）。"""
    if not isinstance(book, dict) or "price_points" not in book:
        raise ValueError("book 必须为成本账本 dict（见 empty_book）")
    if not isinstance(points, (list, tuple)):
        raise ValueError("points 必须为列表")
    rows = [validate_price_point(p) for p in points]
    book = {
        "schema": _BOOK_SCHEMA,
        "price_points": list(book.get("price_points", [])) + rows,
    }
    return book


def _curve_for(book: dict[str, Any], item: str) -> dict[str, Any]:
    pts = [p for p in book["price_points"] if p["item"] == item]
    if not pts:
        raise ValueError(
            f"item={item!r} 在成本账本中无自录散点——零内置价格，请先录入"
        )
    return quantity_price_curve(pts)


def cost_usd_estimate(book: Any, bom_lines: Any) -> dict[str, Any]:
    """BOM 成本估算：行级无单价时从账本自录曲线按量插值（域外拒绝外推）。"""
    if not isinstance(book, dict):
        raise ValueError("book 必须为成本账本 dict")
    curves: dict[str, dict[str, Any]] = {}

    def resolve(item: str, qty: float) -> float:
        if item not in curves:
            curves[item] = _curve_for(book, item)
        return float(unit_price_at(curves[item], qty)["unit_price"])

    return bom_totals(bom_lines, resolve_price=resolve)


def panelized_board_cost(
    book: Any,
    *,
    panel_item: str,
    board_w_mm: float,
    board_h_mm: float,
    panel_w_mm: float,
    panel_h_mm: float,
    n_boards: int | None = None,
    extra_lines: Any = None,
) -> dict[str, Any]:
    """拼板口径单板成本：利用率几何 × 拼板自录价（按拼板量档取价）。

    n_boards 缺省=该拼板可铺板数（panel_utilization.boards_per_panel）；
    拼板需求片数 = ceil(n_boards / boards_per_panel)，片数即 panel_item 的
    购买量档（从账本曲线取价）。extra_lines 透传进 BOM 合计（工艺边/表面
    处理等用户自录行）。
    """
    if not isinstance(book, dict):
        raise ValueError("book 必须为成本账本 dict")
    util = panel_utilization(board_w_mm, board_h_mm, panel_w_mm, panel_h_mm)
    per_panel = util["boards_per_panel"]
    if per_panel < 1:
        raise ValueError("拼板铺不下单板（boards_per_panel<1）——尺寸/拼板不自洽")
    need_panels = 1 if n_boards is None else -(-int(n_boards) // per_panel)
    curve = _curve_for(book, panel_item)
    price = float(unit_price_at(curve, float(need_panels))["unit_price"])
    lines: list[dict[str, Any]] = [
        {
            "item": panel_item,
            "qty": float(need_panels),
            "unit_price": price,
        }
    ]
    if extra_lines is not None:
        lines.extend(dict(r) for r in extra_lines)
    totals = bom_totals(lines)
    per_board = totals["total"] / (n_boards if n_boards is not None else per_panel)
    return {
        "utilization": util,
        "n_boards_basis": per_panel if n_boards is None else int(n_boards),
        "panels_needed": need_panels,
        "totals": totals,
        "cost_per_board": per_board,
        "note": "单价来自用户自录曲线（域外拒绝外推）；金额币种语义随 totals.currency",
    }


def load_book(path: str | Path) -> dict[str, Any]:
    """从 JSON 文件装载成本账本（只读）。"""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        book = json.load(fh)
    if not isinstance(book, dict) or "price_points" not in book:
        raise ValueError("JSON 不含 price_points——不是成本账本（rfauto-cost-book/v1）")
    return book


def save_book(book: dict[str, Any], path: str | Path) -> None:
    """账本落 JSON（用户自录数据的持久化；目录须已存在）。"""
    p = Path(path)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(book, fh, ensure_ascii=False, indent=2)
