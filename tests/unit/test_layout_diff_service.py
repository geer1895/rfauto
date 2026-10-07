"""LC-6 版图 diff 三面语义 diff 单测（service/layout_diff_service.py）。确定性离线。"""

from __future__ import annotations

import copy

import pytest

from rfauto.adapters.layout_generator import generate_microstrip
from rfauto.service.layout_diff_service import DEFAULT_TOL_NM, diff_layout_payload
from rfauto.service.layout_service import layout_to_payload

MICROSTRIP_PARAMS = {
    "width_mm": 0.25,
    "length_mm": 10.0,
    "via_fence": {"pitch_mm": 2.5, "pad_diameter_mm": 0.6, "drill_diameter_mm": 0.3},
}


@pytest.fixture()
def microstrip_payload() -> dict:
    return layout_to_payload(
        generate_microstrip(MICROSTRIP_PARAMS))


class TestItemsFace:
    def test_identical_payload_differs_nowhere(self, microstrip_payload):
        r = diff_layout_payload(microstrip_payload, microstrip_payload)
        assert r["ok"] and r["identical"] is True
        assert r["items"]["n_common"] == len(microstrip_payload["items"])
        assert r["items"]["added"] == [] and r["items"]["removed"] == []

    def test_width_change_is_add_plus_remove_not_silent(self, microstrip_payload):
        b = copy.deepcopy(microstrip_payload)
        changed = 0
        for node in b["items"]:
            if node["kind"] == "path":
                node["width_mm"] += 0.05
                changed += 1
        assert changed > 0  # fixture 里有 path
        r = diff_layout_payload(microstrip_payload, b)
        assert r["identical"] is False
        assert len(r["items"]["added"]) == changed
        assert len(r["items"]["removed"]) == changed

    def test_sub_nm_jitter_absorbed_by_grid(self, microstrip_payload):
        b = copy.deepcopy(microstrip_payload)
        for node in b["items"]:
            if node["kind"] == "polygon":
                node["points"] = [[x + 2e-7, y - 2e-7] for x, y in node["points"]]
        r = diff_layout_payload(microstrip_payload, b)
        assert r["identical"] is True  # 0.2nm < 1nm 栅格=浮点噪声被吸收

    def test_real_geometry_change_not_absorbed(self, microstrip_payload):
        b = copy.deepcopy(microstrip_payload)
        for node in b["items"]:
            if node["kind"] == "polygon":
                node["points"] = [[x + 1e-3, y] for x, y in node["points"]]  # 1µm 位移
        r = diff_layout_payload(microstrip_payload, b)
        assert r["identical"] is False

    def test_fine_grid_absorbs_more(self, microstrip_payload):
        b = copy.deepcopy(microstrip_payload)
        for node in b["items"]:
            if node["kind"] == "polygon":
                node["points"] = [[x + 3e-6, y] for x, y in node["points"]]  # 3nm
        loose = diff_layout_payload(microstrip_payload, b, tol_nm=10.0)
        strict = diff_layout_payload(microstrip_payload, b)
        assert loose["identical"] is True and strict["identical"] is False

    def test_duplicate_count_matched_by_multiset(self):
        a = {"name": "a", "items": [
            {"kind": "circle", "center": [0, 0], "radius_mm": 0.3, "layer": "F.Cu"},
            {"kind": "circle", "center": [1, 0], "radius_mm": 0.3, "layer": "F.Cu"},
        ]}
        b = {"name": "b", "items": [
            {"kind": "circle", "center": [0, 0], "radius_mm": 0.3, "layer": "F.Cu"},
        ]}
        r = diff_layout_payload(a, b)
        assert len(r["items"]["removed"]) == 1
        assert r["items"]["n_common"] == 1


class TestLayersFace:
    def test_layer_add_remove_change(self):
        a = {"name": "a", "layers": [
            {"name": "F.Cu", "gds_layer": 1, "gds_datatype": 0},
            {"name": "Edge.Cuts", "gds_layer": 20, "gds_datatype": 0},
        ], "items": []}
        b = {"name": "b", "layers": [
            {"name": "F.Cu", "gds_layer": 1, "gds_datatype": 2},  # datatype 变
            {"name": "B.Cu", "gds_layer": 2, "gds_datatype": 0},  # 新增
        ], "items": []}
        r = diff_layout_payload(a, b)
        assert r["layers"]["added"] == ["B.Cu"]
        assert r["layers"]["removed"] == ["Edge.Cuts"]
        assert r["layers"]["changed"] == [{
            "name": "F.Cu",
            "a": {"gds_layer": 1, "gds_datatype": 0},
            "b": {"gds_layer": 1, "gds_datatype": 2},
        }]
        assert r["identical"] is False


class TestPortsFace:
    @classmethod
    def port_kw(cls) -> dict:
        """每处现造（resolve_ports 不改写入参，ClassVar 可变缺省只是 lint 面）。"""
        return {"heuristic": True, "heuristic_layers": ["F.Cu"]}

    def _payload_with_trace(self) -> dict:
        return {"name": "t", "items": [
            {"kind": "path", "points": [[0.0, 0.0], [5.0, 0.0]],
             "width_mm": 0.3, "layer": "F.Cu"},
        ]}

    def test_ports_face_opt_in(self):
        p = self._payload_with_trace()
        r = diff_layout_payload(p, p)
        assert r["ok"] and r["ports"] is None  # 未启用=如实 None
        r2 = diff_layout_payload(p, p, port_kwargs=self.port_kw())
        assert r2["ports"] is not None
        assert r2["ports"]["added"] == [] and r2["ports"]["removed"] == []

    def test_port_added_removed_and_width_change(self):
        a = self._payload_with_trace()
        b = {"name": "t2", "items": [
            {"kind": "path", "points": [[0.0, 0.0], [5.0, 0.0]],
             "width_mm": 0.4, "layer": "F.Cu"},
            {"kind": "path", "points": [[10.0, 0.0], [12.0, 0.0]],
             "width_mm": 0.3, "layer": "F.Cu"},  # 新开路段=两端各一候选
        ]}
        r = diff_layout_payload(a, b, port_kwargs=self.port_kw())
        assert r["ports"] is not None
        assert len(r["ports"]["added"]) == 2  # 新路段两个开路端
        assert r["ports"]["changed"], "宽度 0.3→0.4 应记 changed"

    def test_resolve_conflict_is_error_envelope_not_crash(self):
        # 无端口来源启用 → resolve_ports ValueError → error 信封（不静默）
        p = {"name": "t", "items": []}
        r = diff_layout_payload(p, p, port_kwargs={})
        assert r["ok"] is False and r["errors"]


class TestGuards:
    def test_bad_payload_is_error_envelope(self):
        r = diff_layout_payload({"items": [{"kind": "nope"}]}, {"items": []})
        assert r["ok"] is False and "解析失败" in r["errors"][0]

    def test_nonpositive_tol_rejected(self, microstrip_payload):
        r = diff_layout_payload(microstrip_payload, microstrip_payload, tol_nm=0)
        assert r["ok"] is False and "tol_nm" in r["errors"][0]

    def test_default_tol_is_1nm(self):
        assert DEFAULT_TOL_NM == 1.0
