"""EP-3 成本模块单测（core/cost_model + service/cost_entry_service）。

裁判独立性（#118）：利用率/插值/合计全部手工闭式对拍；零内置价格断言=
空账本取价必须 ValueError（无任何缺省价可走）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core import cost_model as cm
from rfauto.service import cost_entry_service as cs


def _pt(item="panel_fr4", qty=100.0, unit_price=12.5, **kw):
    base = {
        "item": item,
        "qty": qty,
        "unit_price": unit_price,
        "source": "https://example.example/quote",
        "tier": "user-recorded",
        "retrieved_date": "2026-10-03",
    }
    base.update(kw)
    return base


class TestPanelUtilization:
    def test_no_rotation_beats(self):
        # 50×40 板 on 200×100 拼板：原方向 4×2=8；旋转 floor(200/40)*floor(100/50)=5*2=10 → 旋转胜（利用率 1.0）
        r = cm.panel_utilization(50, 40, 200, 100)
        assert r["boards_per_panel"] == 10
        assert r["rotated"] is True
        assert abs(r["utilization"] - 1.0) <= 1e-12
        # 原方向胜例：40×50 on 120×60：原 3×1=3；旋转 floor(120/50)*floor(60/40)=2*1=2
        r0 = cm.panel_utilization(40, 50, 120, 60)
        assert r0["boards_per_panel"] == 3 and r0["rotated"] is False
        assert abs(r0["utilization"] - 3 * 40 * 50 / (120 * 60)) <= 1e-12

    def test_rotation_wins(self):
        # 40×50 on 120×60：原方向 floor(120/40)*floor(60/50)=3*1=3；旋转 floor(120/50)*floor(60/40)=2*1=2 → 原方向胜
        r2 = cm.panel_utilization(40, 50, 120, 60)
        assert r2["boards_per_panel"] == 3 and r2["rotated"] is False
        # 55×45 on 180×95：原 3×2=6；旋转 floor(180/45)*floor(95/55)=4*1=4 → 原方向 6 胜
        r3 = cm.panel_utilization(55, 45, 180, 95)
        assert r3["boards_per_panel"] == 6
        # 真旋转胜例：45×95 on 190×50：原 floor(190/45)*floor(50/95)=4*0=0；旋转 floor(190/95)*floor(50/45)=2*1=2
        r4 = cm.panel_utilization(45, 95, 190, 50)
        assert r4["boards_per_panel"] == 2 and r4["rotated"] is True

    def test_guards(self):
        with pytest.raises(ValueError):
            cm.panel_utilization(0, 40, 200, 100)
        with pytest.raises(ValueError):
            cm.panel_utilization(True, 40, 200, 100)  # type: ignore[arg-type]


class TestQuantityPriceCurve:
    def test_curve_sorted_and_knot_price(self):
        curve = cm.quantity_price_curve(
            [_pt(qty=100, unit_price=12.5), _pt(qty=10, unit_price=20.0),
             _pt(qty=1000, unit_price=9.0)]
        )
        assert curve["qty"] == [10.0, 100.0, 1000.0]
        at = cm.unit_price_at(curve, 100)
        assert at["unit_price"] == 12.5 and at["interpolated"] is False
        at0 = cm.unit_price_at(curve, 10)
        assert at0["unit_price"] == 20.0

    def test_interpolation_bracket_math(self):
        curve = cm.quantity_price_curve([_pt(qty=10, unit_price=20.0), _pt(qty=110, unit_price=9.0)])
        at = cm.unit_price_at(curve, 60)
        # t = (60-10)/(110-10)=0.5 → 20 + 0.5*(9-20) = 14.5（手工闭式对拍）
        assert abs(at["unit_price"] - 14.5) <= 1e-12
        assert at["interpolated"] is True
        assert at["bracket"]["qty_lo"] == 10.0

    def test_extrapolation_refused(self):
        curve = cm.quantity_price_curve([_pt(qty=10, unit_price=20.0), _pt(qty=100, unit_price=12.5)])
        with pytest.raises(ValueError, match="拒绝外推"):
            cm.unit_price_at(curve, 5)
        with pytest.raises(ValueError, match="拒绝外推"):
            cm.unit_price_at(curve, 101)

    def test_conflict_and_provenance_guards(self):
        with pytest.raises(ValueError, match="同量双价"):
            cm.quantity_price_curve([_pt(qty=10, unit_price=20.0), _pt(qty=10, unit_price=21.0)])
        with pytest.raises(ValueError, match="tier"):
            cm.quantity_price_curve([_pt(tier="cheap")])
        with pytest.raises(ValueError, match="source"):
            cm.quantity_price_curve([_pt(source="")])
        with pytest.raises(ValueError, match="retrieved_date"):
            cm.quantity_price_curve([_pt(retrieved_date="")])


class TestBomTotals:
    def test_sum_hand_check(self):
        r = cm.bom_totals(
            [
                {"item": "a", "qty": 10, "unit_price": 2.0},
                {"item": "b", "qty": 3, "unit_price": 0.5},
            ]
        )
        assert abs(r["total"] - 21.5) <= 1e-12
        assert r["n_lines"] == 2

    def test_mixed_currency_refused(self):
        with pytest.raises(ValueError, match="混币种"):
            cm.bom_totals(
                [
                    {"item": "a", "qty": 1, "unit_price": 2.0, "currency": "CNY"},
                    {"item": "b", "qty": 1, "unit_price": 2.0, "currency": "USD"},
                ]
            )

    def test_resolver_binding(self):
        def resolve(item, qty):
            assert item == "x"
            return 1.0 / qty if qty else 0.0

        r = cm.bom_totals([{"item": "x", "qty": 4}], resolve_price=resolve)
        # total = qty × price = 4 × 0.25 = 1.0
        assert abs(r["total"] - 1.0) <= 1e-12
        with pytest.raises(ValueError, match="resolve_price"):
            cm.bom_totals([{"item": "x", "qty": 4}])
        with pytest.raises(ValueError):
            cm.bom_totals([])


class TestServiceBook:
    def test_empty_book_has_no_prices(self):
        book = cs.empty_book()
        assert book["price_points"] == []
        # 零内置价格：空账本取价必须 ValueError（无缺省价可走）
        with pytest.raises(ValueError, match="无自录散点"):
            cs.cost_usd_estimate(book, [{"item": "panel", "qty": 10}])

    def test_add_estimate_roundtrip(self, tmp_path):
        book = cs.add_price_points(
            cs.empty_book(),
            [_pt(item="panel_fr4", qty=10, unit_price=20.0),
             _pt(item="panel_fr4", qty=100, unit_price=12.5)],
        )
        assert book["schema"] == "rfauto-cost-book/v1"
        est = cs.cost_usd_estimate(book, [{"item": "panel_fr4", "qty": 55}])
        # t=(55-10)/90=0.5 → 20+0.5*(12.5-20)=16.25；total=55×16.25=893.75
        assert abs(est["items"][0]["unit_price"] - 16.25) <= 1e-12
        assert abs(est["total"] - 893.75) <= 1e-12
        p = tmp_path / "book.json"
        cs.save_book(book, p)
        reloaded = cs.load_book(p)
        assert json.loads(json.dumps(reloaded)) == book

    def test_panelized_board_cost_hand_check(self):
        book = cs.add_price_points(
            cs.empty_book(), [_pt(item="panel_fr4", qty=1, unit_price=10.0),
                              _pt(item="panel_fr4", qty=10, unit_price=10.0)]
        )
        # 50×40 on 200×100 → 10 板/拼板（旋转胜）；需求 16 板 → 2 拼板 × 10.0 = 20.0
        r = cs.panelized_board_cost(
            book, panel_item="panel_fr4",
            board_w_mm=50, board_h_mm=40, panel_w_mm=200, panel_h_mm=100,
            n_boards=16,
        )
        assert r["panels_needed"] == 2
        assert abs(r["totals"]["total"] - 20.0) <= 1e-12
        assert abs(r["cost_per_board"] - 20.0 / 16) <= 1e-12
        # 缺省 n_boards=1 拼板基准 → per_board = 10.0/10
        r2 = cs.panelized_board_cost(
            book, panel_item="panel_fr4",
            board_w_mm=50, board_h_mm=40, panel_w_mm=200, panel_h_mm=100,
        )
        assert abs(r2["cost_per_board"] - 10.0 / 10) <= 1e-12
