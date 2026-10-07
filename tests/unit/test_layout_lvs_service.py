"""LC-7 LVS 最小面单测（service/layout_lvs_service.py）。

shapely 为可选依赖：缺装=诚实 skip（任务书验收门"未装 skip 诚实"）；
本机 venv 已装（extras 建议文本见席 B2 汇报：layout = [gdstk, shapely]）。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.layout_interchange import Layout, LayoutCircle, LayoutPath
from rfauto.service.layout_service import layout_to_payload

shapely = pytest.importorskip("shapely")

from rfauto.service.layout_lvs_service import (
    expected_from_compose_netlist,
    lvs_check,
)


def _two_net_layout() -> dict:
    """两网布局：网 1=P1–P3（线+焊盘+线），网 2=P2（孤岛铜柱）。"""
    lay = Layout(
        items=[
            LayoutPath(points=((0.0, 0.0), (5.0, 0.0)), width_mm=0.5, layer="F.Cu"),
            LayoutCircle(center=(5.2, 0.0), radius_mm=0.4, layer="F.Cu"),
            LayoutPath(points=((5.4, 0.0), (10.0, 0.0)), width_mm=0.5, layer="F.Cu"),
            LayoutCircle(center=(20.0, 20.0), radius_mm=1.0, layer="F.Cu"),
        ])
    return layout_to_payload(lay)


PORTS = [
    {"port_id": "P1", "position_mm": [0.0, 0.0], "direction": [1, 0], "width_mm": 0.5},
    {"port_id": "P2", "position_mm": [20.0, 20.0], "direction": [0, 1], "width_mm": 0.5},
    {"port_id": "P3", "position_mm": [10.0, 0.0], "direction": [-1, 0], "width_mm": 0.5},
]


class TestLvsCore:
    def test_match(self):
        r = lvs_check(_two_net_layout(),
                      {"connections": [["P1", "P3"]], "ports": ["P1", "P2", "P3"]},
                      ports=PORTS)
        assert r["ok"]
        assert r["verdict"] == "LVS_MATCH"
        assert r["connections"] == [{
            "pair": ["P1", "P3"], "flag": "agree", "net": "N1"}]
        assert r["ports_assigned"] == {"P1": "N1", "P2": "N2", "P3": "N1"}
        assert r["missing_ports"] == [] and r["ports_unassigned"] == []

    def test_disagree_flags_with_net_diagnostics(self):
        r = lvs_check(_two_net_layout(), {"connections": [["P1", "P2"]]},
                      ports=PORTS)
        assert r["verdict"] == "LVS_FLAG"
        flag = r["connections"][0]
        assert flag["flag"] == "disagree"
        assert flag["net_a"] == "N1" and flag["net_b"] == "N2"

    def test_unassigned_port_is_flagged(self):
        ports = [dict(p) for p in PORTS]
        ports.append({"port_id": "PX", "position_mm": [50.0, 50.0],
                      "direction": [1, 0], "width_mm": 0.3})
        r = lvs_check(_two_net_layout(), {"connections": [["P1", "P3"]]},
                      ports=ports)
        assert r["verdict"] == "LVS_FLAG"
        assert r["ports_unassigned"] == ["PX"]

    def test_missing_expected_port_fails_verdict(self):
        r = lvs_check(_two_net_layout(),
                      {"connections": [["P1", "P3"]], "ports": ["P1", "P2", "P3", "PZ"]},
                      ports=PORTS)
        assert r["verdict"] == "LVS_FLAG"
        assert r["missing_ports"] == ["PZ"]

    def test_extra_geometry_ports_reported_not_failing(self):
        # 布局有 P3、期望只声明 P1/P2 连接——多出端口如实列出不翻 verdict
        r = lvs_check(_two_net_layout(),
                      {"connections": [["P1", "P3"]], "ports": ["P1", "P3"]},
                      ports=PORTS)
        assert r["verdict"] == "LVS_MATCH"
        assert "P2" in r["extra_geometry_ports"]

    def test_layer_filter_zero_items_is_error(self):
        r = lvs_check(_two_net_layout(), {"connections": []},
                      ports=PORTS, layer="B.Cu")
        assert r["ok"] is False and "层过滤后 0 图元" in r["errors"][0]

    def test_layer_filter_scopes_connectivity(self):
        # 跨层桥焊盘在 B.Cu：F.Cu 单层口径下 P1 与 P3 断开（全层并集口径连通）。
        # 几何留 buffer 余量：线端 buffer cap 外扩 width/2（0.25mm），
        # 桥盘 r=0.9@5.0 跨 [4.1,5.9] 同时压住两段线帽端。
        lay = Layout(items=[
            LayoutPath(points=((0.0, 0.0), (4.0, 0.0)), width_mm=0.5, layer="F.Cu"),
            LayoutCircle(center=(5.0, 0.0), radius_mm=0.9, layer="B.Cu"),  # 跨层桥
            LayoutPath(points=((6.0, 0.0), (10.0, 0.0)), width_mm=0.5, layer="F.Cu"),
        ])
        ports = [
            {"port_id": "P1", "position_mm": [0.0, 0.0], "direction": [1, 0], "width_mm": 0.5},
            {"port_id": "P3", "position_mm": [10.0, 0.0], "direction": [-1, 0], "width_mm": 0.5},
        ]
        single = lvs_check(layout_to_payload(lay), {"connections": [["P1", "P3"]]},
                           ports=ports, layer="F.Cu")
        all_layers = lvs_check(layout_to_payload(lay), {"connections": [["P1", "P3"]]},
                               ports=ports)
        assert single["verdict"] == "LVS_FLAG" and all_layers["verdict"] == "LVS_MATCH"

    def test_no_ports_source_skips_face_honestly(self):
        r = lvs_check(_two_net_layout(), {"connections": []})
        assert r["ok"]
        assert r["verdict"] == "LVS_MATCH"  # 空期望连接=空裁决集
        assert r["ports_face"] and "不参与裁决" in r["ports_face"]


class TestComposeCollapse:
    def test_connections_and_exposed_ports_collapse_to_pins(self):
        exp = expected_from_compose_netlist({
            "schema": "rfauto-netlist-v1",
            "band_ghz": [9.75, 10.25],
            "substrate": {"h_mm": 0.508, "er": 3.66, "tan_d": 0.0037},
            "instances": [
                {"id": "a", "template": "mline", "params": {}},
                {"id": "b", "template": "mline", "params": {}},
            ],
            "connections": [{"a": ["a", "out"], "b": ["b", "in"]}],
            "exposed_ports": [
                {"instance": "a", "pin": "in"}, {"instance": "b", "pin": "out"}],
        })
        assert exp == {"connections": [["out", "in"]], "ports": ["in", "out"]}

    def test_collapse_feeds_lvs_end_to_end(self):
        exp = expected_from_compose_netlist({
            "schema": "rfauto-netlist-v1", "band_ghz": [9.0, 11.0],
            "substrate": {"h_mm": 0.508, "er": 3.66},
            "instances": [{"id": "a", "template": "mline", "params": {}}],
            "connections": [],
            "exposed_ports": [{"instance": "a", "pin": "P1"}],
        })
        r = lvs_check(_two_net_layout(), exp, ports=PORTS)
        # 期望端口 P1 在布局有网、P2 未声明（多出端口如实报告）
        assert r["ok"] and r["verdict"] == "LVS_MATCH"
        assert r["missing_ports"] == []

    def test_bad_schema_rejected(self):
        with pytest.raises(ValueError, match="schema"):
            expected_from_compose_netlist({"schema": "nope"})
