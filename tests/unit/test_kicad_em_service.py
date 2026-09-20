"""B6 stage-2 service 测试：CPWG 锚判据 + 确定性代理寻优 + autotune 接线。

零真机：service 只消费 extract_pcb 的产物契约（合成 fixture），代理寻
优走 core 闭式内核（_cpwg_ri/synthesize_cpw_model）；autotune_loop 接
线用注入 sampler（test_autotune.py 同法，chdir 隔离防污染真实 runs/，
#144）。关键数字锚：demo 口径 w=0.849/gap=0.2/h=0.508/er=3.66 →
z0=50.00Ω、εeff=2.5673（core 闭式，与 stage-1 冒烟 eps_ref 同源）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _synthetic_extract(w=0.849, gap=0.2, length=40.0, er=3.66, h=0.508,
                       *, ok=True, tan_d=0.0037):
    """extract_pcb 产物契约的合成 fixture（demo 板口径）。"""
    return {
        "ok": ok,
        "errors": [] if ok else ["注入失败"],
        "board": {
            "kicad_version": "10.0.6-test", "layer_count": 2,
            "copper_layers": ["F.Cu", "B.Cu"], "thickness_mm": h + 0.07,
            "substrate_er": er, "substrate_note": "test",
            "stackup": {"dielectrics": [
                {"name": "dielectric 1", "thickness_mm": h, "er": er,
                 "tan_d": tan_d}]},
        },
        "traces": [
            {"net": "RF1", "layer": "F.Cu", "width_mm": w,
             "length_mm": length, "points_mm": [[10.0, 15.0], [50.0, 15.0]]},
            {"net": "GND", "layer": "B.Cu", "width_mm": 1.0,
             "length_mm": 5.0, "points_mm": [[1.0, 1.0], [6.0, 1.0]]},
        ],
        "vias": [], "outline": {"min_mm": [0.0, 0.0], "max_mm": [60.0, 30.0],
                                "width_mm": 60.0, "height_mm": 30.0},
        "zones": [
            {"net": "GND", "layer": "F.Cu", "layers": ["F.Cu"],
             "clearance_mm": gap, "min_thickness_mm": 0.1, "priority": 0,
             "filled": False,
             "outline_points_mm": [[-2.0, -2.0], [62.0, -2.0],
                                   [62.0, 32.0], [-2.0, 32.0]],
             "n_outlines": 1},
            {"net": "GND", "layer": "B.Cu", "layers": ["B.Cu"],
             "clearance_mm": gap, "min_thickness_mm": 0.1, "priority": 0,
             "filled": False, "outline_points_mm": [], "n_outlines": 1},
        ],
        "footprints": [],
    }


# demo 板 KiCad 10.0.6 实测走廊孔包围盒（mm；test_kicad_extract
# TestFillExtraction 同源数字）：x=pad 边外扩 0.225、y=主线边外扩 0.2005
CORRIDOR_X0, CORRIDOR_Y0, CORRIDOR_X1, CORRIDOR_Y1 = 9.375, 14.375, 50.625, 15.625


def _synthetic_filled_extract(w=0.849, gap=0.2, length=40.0,
                              corridor_half_h=None, **kw):
    """带填充纹理/过孔/焊盘的合成 extract（demo 板全要素口径，零 KiCad）。

    corridor_half_h：走廊孔半高（mm）；缺省 = w/2 + gap（实测缝==clearance
    的理想口径），显式给值可制造实测≠clearance 的不一致场景。
    """
    ex = _synthetic_extract(w=w, gap=gap, length=length, **kw)
    half_h = corridor_half_h if corridor_half_h is not None else w / 2 + gap
    x0, x1 = 10.0 - 0.4 - 0.225, 10.0 + length + 0.4 + 0.225
    corridor = [[x0, 15.0 - half_h], [x1, 15.0 - half_h],
                [x1, 15.0 + half_h], [x0, 15.0 + half_h]]
    outer = [[0.5, 0.5], [59.5, 0.5], [59.5, 29.5], [0.5, 29.5]]
    for z in ex["zones"]:
        z["filled"] = True
        z["outlines_mm"] = [z["outline_points_mm"]] if z["outline_points_mm"] else []
        if z["layer"] == "F.Cu":
            z["filled_polys_mm"] = [{"outer_mm": outer, "holes_mm": [corridor]}]
            z["holes_mm"] = [corridor]
        else:
            z["filled_polys_mm"] = [{"outer_mm": outer, "holes_mm": []}]
            z["holes_mm"] = []
    ex["vias"] = [{"net": "GND", "x_mm": x, "y_mm": 18.0,
                   "pad_diameter_mm": 0.6, "drill_mm": 0.3}
                  for x in (12.0, 24.0, 36.0, 48.0)]
    ex["footprints"] = [{
        "reference": "X1", "value": "CPWG_LAUNCH", "x_mm": 10.0, "y_mm": 15.0,
        "pads": [
            {"number": "1", "net": "RF1", "shape": 1, "x_mm": 10.0,
             "y_mm": 15.0, "w_mm": 0.8, "h_mm": 0.6, "layers": ["F.Cu"]},
            {"number": "2", "net": "RF1", "shape": 1, "x_mm": 10.0 + length,
             "y_mm": 15.0, "w_mm": 0.8, "h_mm": 0.6, "layers": ["F.Cu"]},
        ],
    }]
    return ex


class TestCpwDesignFromExtract:
    def test_demo_design_parsed(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        d = cpw_design_from_extract(_synthetic_extract())
        assert d["w_mm"] == pytest.approx(0.849)
        assert d["gap_mm"] == pytest.approx(0.2)
        assert d["line_len_mm"] == pytest.approx(40.0)
        assert d["h_mm"] == pytest.approx(0.508)
        assert d["er"] == pytest.approx(3.66)
        assert d["tan_d"] == pytest.approx(0.0037)
        assert d["net"] == "RF1"
        assert set(d["sources"]) == {"w_mm", "gap_mm", "er_h"}
        assert "zones[" in d["sources"]["gap_mm"]

    def test_longest_f_cu_trace_wins(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        ex = _synthetic_extract()
        ex["traces"].insert(0, {
            "net": "RF2", "layer": "F.Cu", "width_mm": 0.5,
            "length_mm": 3.0, "points_mm": [[0.0, 0.0], [3.0, 0.0]]})
        d = cpw_design_from_extract(ex)
        assert d["net"] == "RF1" and d["w_mm"] == pytest.approx(0.849)

    def test_gap_takes_min_clearance(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        ex = _synthetic_extract()
        ex["zones"].append(
            {"net": "GND", "layer": "F.Cu", "layers": ["F.Cu"],
             "clearance_mm": 0.15, "min_thickness_mm": 0.1, "priority": 0,
             "filled": False, "outline_points_mm": [], "n_outlines": 1})
        assert cpw_design_from_extract(ex)["gap_mm"] == pytest.approx(0.15)

    def test_b_cu_zone_ignored_for_gap(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        ex = _synthetic_extract()
        ex["zones"][1]["clearance_mm"] = 0.9  # B.Cu 不参与 CPWG gap
        assert cpw_design_from_extract(ex)["gap_mm"] == pytest.approx(0.2)


class TestDesignErrors:
    def test_not_ok_contract(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        with pytest.raises(ValueError, match="ok=False"):
            cpw_design_from_extract(_synthetic_extract(ok=False))

    def test_no_f_cu_trace(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        ex = _synthetic_extract()
        ex["traces"] = [t for t in ex["traces"] if t["layer"] != "F.Cu"]
        with pytest.raises(ValueError, match=r"F\.Cu"):
            cpw_design_from_extract(ex)

    def test_no_gnd_zone(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        ex = _synthetic_extract()
        ex["zones"] = []
        with pytest.raises(ValueError, match="clearance"):
            cpw_design_from_extract(ex)

    def test_no_stackup_dielectric(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        ex = _synthetic_extract()
        ex["board"]["stackup"] = {"dielectrics": []}
        with pytest.raises(ValueError, match="dielectrics"):
            cpw_design_from_extract(ex)

    def test_non_mapping_rejected(self):
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        with pytest.raises(ValueError):
            cpw_design_from_extract("not-a-dict")  # type: ignore[arg-type]


class TestOptimizeCpwFromExtract:
    def test_on_target_verdict_pass(self):
        from rfauto.service.kicad_em_service import optimize_cpw_from_extract

        r = optimize_cpw_from_extract({"extract": _synthetic_extract()})
        assert r["ok"] is True
        assert r["verdict"] == "PASS"
        assert r["analysis"]["z0_extracted_ohm"] == pytest.approx(50.0,
                                                                  abs=0.02)
        assert r["analysis"]["eps_eff_extracted"] == pytest.approx(2.5673,
                                                                   abs=1e-3)
        assert r["optimization"]["w_opt_mm"] == pytest.approx(0.849, abs=5e-4)
        assert r["optimization"]["delta_w_mm"] == pytest.approx(0.0, abs=1e-3)
        assert r["recipe_draft"]["model"] == "cpw"

    def test_too_wide_verdict_fail_with_directional_fix(self):
        from rfauto.core.calculators import _cpwg_ri
        from rfauto.service.kicad_em_service import optimize_cpw_from_extract

        r = optimize_cpw_from_extract({"extract": _synthetic_extract(w=1.113)})
        assert r["ok"] is True
        assert r["verdict"] == "FAIL"  # 宽线 Z0<50，判据如实 FAIL
        _, z0_wide = _cpwg_ri(1.113, 0.2, 0.508, 3.66)
        assert z0_wide < 45.0  # 前提：1.113mm 在该叠层确实远低于 50Ω
        # 修正方向确定性：过宽 → 寻优宽度必须小于提取宽度
        assert r["optimization"]["w_opt_mm"] < 1.113
        assert r["optimization"]["delta_w_mm"] > 0

    def test_too_narrow_verdict_fail_direction_reversed(self):
        from rfauto.service.kicad_em_service import optimize_cpw_from_extract

        r = optimize_cpw_from_extract({"extract": _synthetic_extract(w=0.6)})
        assert r["verdict"] == "FAIL"
        assert r["optimization"]["w_opt_mm"] > 0.6
        assert r["optimization"]["delta_w_mm"] < 0

    def test_tolerance_controls_verdict(self):
        from rfauto.service.kicad_em_service import optimize_cpw_from_extract

        r = optimize_cpw_from_extract({"extract": _synthetic_extract(w=0.9),
                                       "z0_tol_ohm": 0.01})
        assert r["verdict"] == "FAIL"
        r2 = optimize_cpw_from_extract({"extract": _synthetic_extract(w=0.9),
                                        "z0_tol_ohm": 50.0})
        assert r2["verdict"] == "PASS"

    def test_error_contract_not_raised(self):
        from rfauto.service.kicad_em_service import optimize_cpw_from_extract

        r = optimize_cpw_from_extract({"extract": _synthetic_extract(ok=False)})
        assert r["ok"] is False and r["error"]
        r2 = optimize_cpw_from_extract({"nope": 1})
        assert r2["ok"] is False and "未知字段" in r2["error"]
        r3 = optimize_cpw_from_extract({})
        assert r3["ok"] is False and "extract" in r3["error"]


class TestAutotuneWiring:
    """接优化环的文件面：配方落盘 → autotune_loop（注入 sampler）全环。"""

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # #144：防污染真实 runs/

    def test_recipe_lands_from_extract_facts(self, tmp_path):
        from rfauto.service.kicad_em_service import autotune_recipe_from_extract

        r = autotune_recipe_from_extract(
            {"extract": _synthetic_extract()}, tmp_path / "b6_recipe.yaml")
        assert r["ok"] is True
        recipe = r["recipe"]
        assert recipe["model"] == "cpw"
        assert recipe["params"]["w_mm"]["value"] == pytest.approx(0.849)
        assert recipe["params"]["gap_mm"]["value"] == pytest.approx(0.2)
        b = recipe["optimization"]["params"]["w_mm"]
        assert b["low"] < 0.849 < b["high"]  # bounds 包住提取值
        assert recipe["b6_provenance"]["z0_extracted_ohm"] == pytest.approx(
            50.0, abs=0.02)
        assert (tmp_path / "b6_recipe.yaml").exists()

    def test_explicit_bounds_respected(self, tmp_path):
        from rfauto.service.kicad_em_service import autotune_recipe_from_extract

        r = autotune_recipe_from_extract(
            {"extract": _synthetic_extract(),
             "w_bounds_mm": [0.5, 1.2]}, tmp_path / "r.yaml")
        b = r["recipe"]["optimization"]["params"]["w_mm"]
        assert (b["low"], b["high"]) == (0.5, 1.2)

    def test_bad_bounds_rejected(self, tmp_path):
        from rfauto.service.kicad_em_service import autotune_recipe_from_extract

        r = autotune_recipe_from_extract(
            {"extract": _synthetic_extract(),
             "w_bounds_mm": [1.2, 0.5]}, tmp_path / "r.yaml")
        assert r["ok"] is False and "lo < hi" in r["error"]

    def test_autotune_loop_accepts_recipe(self, tmp_path):
        """提取配方 → autotune_loop 注入 sampler → 环收敛（离线全链）。"""
        from rfauto.service.autotune_service import autotune_loop
        from rfauto.service.kicad_em_service import autotune_recipe_from_extract

        rp = tmp_path / "b6_recipe.yaml"
        assert autotune_recipe_from_extract(
            {"extract": _synthetic_extract()}, rp)["ok"] is True

        def sampler(params: dict[str, float]) -> dict[str, Any]:
            # fake 通道：谷位随 w_mm 确定性变化（w 越接近 0.849 谷越准）
            err = abs(params["w_mm"] - 0.849) / 0.849
            valley = 2.5 * (1.0 + err)
            rl = -20.0 if err < 0.02 else -10.0 - err
            return {"metrics": {"s11_db_max_in_band": rl}, "valley_ghz": valley}

        r = autotune_loop(str(rp), sampler_fn=sampler, budget=3)
        assert r["ok"] is True
        assert r["verdict"] == "PASS"
        assert r["best"]["params"]["w_mm"] == pytest.approx(0.849, rel=0.05)


class TestMeasureFillGap:
    """measure_fill_gap_mm：横向射线缝宽（纯计算几何），零 shapely 零 KiCad。"""

    def test_demo_corridor_gap_equals_clearance(self):
        from rfauto.service.kicad_em_service import measure_fill_gap_mm

        ex = _synthetic_filled_extract()
        fz = next(z for z in ex["zones"] if z["layer"] == "F.Cu")
        gap = measure_fill_gap_mm([[10.0, 15.0], [50.0, 15.0]], 0.849,
                                  fz["filled_polys_mm"])
        assert gap == pytest.approx(0.2, abs=1e-9)

    def test_gap_scales_with_corridor(self):
        from rfauto.service.kicad_em_service import measure_fill_gap_mm

        ex = _synthetic_filled_extract(corridor_half_h=0.849 / 2 + 0.35)
        fz = next(z for z in ex["zones"] if z["layer"] == "F.Cu")
        gap = measure_fill_gap_mm([[10.0, 15.0], [50.0, 15.0]], 0.849,
                                  fz["filled_polys_mm"])
        # 横向口径：端墙（焊盘 cutout，端距 0.625→0.2005）不污染侧缝 0.35
        assert gap == pytest.approx(0.35, abs=1e-9)

    def test_no_fill_returns_none(self):
        from rfauto.service.kicad_em_service import measure_fill_gap_mm

        assert measure_fill_gap_mm([[0.0, 0.0], [1.0, 0.0]], 0.5, []) is None

    def test_embedded_trace_returns_none(self):
        """走线嵌在铜内（中线站点落在填充内）：缝不存在 → None。"""
        from rfauto.service.kicad_em_service import measure_fill_gap_mm

        # 填充多边形恰是走线本身的足迹（中线站点在铜内）
        polys = [{"outer_mm": [[10.0, 14.5755], [50.0, 14.5755],
                               [50.0, 15.4245], [10.0, 15.4245]],
                  "holes_mm": []}]
        assert measure_fill_gap_mm([[10.0, 15.0], [50.0, 15.0]], 0.849,
                                   polys) is None

    def test_crossing_copper_returns_none(self):
        from rfauto.service.kicad_em_service import measure_fill_gap_mm

        # 填充矩形横穿走线（x 30..31）：站点 x=30/31 落铜内 → 短路 → None
        polys = [{"outer_mm": [[30.0, 10.0], [31.0, 10.0], [31.0, 20.0],
                               [30.0, 20.0]], "holes_mm": []}]
        assert measure_fill_gap_mm([[10.0, 15.0], [50.0, 15.0]], 0.849,
                                   polys) is None

    def test_geometry_primitives(self):
        from rfauto.service.kicad_em_service import (
            _point_in_fill,
            _point_in_ring,
            _ray_first_hit,
        )

        square = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
        assert _point_in_ring(5.0, 5.0, square) is True
        assert _point_in_ring(15.0, 5.0, square) is False
        polys = [{"outer_mm": square,
                  "holes_mm": [[[4.0, 4.0], [6.0, 4.0], [6.0, 6.0],
                                [4.0, 6.0]]]}]
        assert _point_in_fill(1.0, 1.0, polys) is True
        assert _point_in_fill(5.0, 5.0, polys) is False  # 孔内
        edges = [(square[i], square[(i + 1) % 4]) for i in range(4)]
        # 从 (5,5) 向 +y 射线首交 y=10 边：距离 5
        assert _ray_first_hit(5.0, 5.0, 0.0, 1.0, edges) == pytest.approx(5.0)
        # 向 −x 首交 x=0 边：距离 5；平行边（y=0/y=10）被跳过
        assert _ray_first_hit(5.0, 5.0, -1.0, 0.0, edges) == pytest.approx(5.0)
        # 射线背向所有边：无交
        assert _ray_first_hit(15.0, 5.0, 1.0, 0.0, edges) is None


class TestBoardFactsFromExtract:
    """board_facts_from_extract：全要素事实 + 缝宽三值（实测优先/clearance
    fallback/一致性）。零 KiCad（合成 extract）；真机锚见
    test_kicad_extract.TestFillExtraction.test_measured_fill_gap_matches_clearance。
    """

    def test_measured_gap_preferred_and_consistent(self):
        from rfauto.service.kicad_em_service import board_facts_from_extract

        facts = board_facts_from_extract(_synthetic_filled_extract())
        assert facts["gap_source"] == "measured_fill"
        assert facts["gap_measured_mm"] == pytest.approx(0.2, abs=1e-9)
        assert facts["gap_clearance_mm"] == pytest.approx(0.2)
        assert facts["gap_mm"] == facts["gap_measured_mm"]
        assert facts["gap_consistent"] is True
        assert "一致" in facts["sources"]["gap_mm"]
        assert "不一致" not in facts["sources"]["gap_mm"]

    def test_inconsistent_measured_still_adopted_and_flagged(self):
        from rfauto.service.kicad_em_service import board_facts_from_extract

        ex = _synthetic_filled_extract(corridor_half_h=0.849 / 2 + 0.3)
        facts = board_facts_from_extract(ex)
        assert facts["gap_measured_mm"] == pytest.approx(0.3, abs=1e-9)
        assert facts["gap_clearance_mm"] == pytest.approx(0.2)
        assert facts["gap_consistent"] is False
        assert facts["gap_mm"] == pytest.approx(0.3)  # 板内事实优先
        assert "不一致" in facts["sources"]["gap_mm"]

    def test_unfilled_falls_back_to_clearance(self):
        from rfauto.service.kicad_em_service import board_facts_from_extract

        facts = board_facts_from_extract(_synthetic_extract())  # filled=False
        assert facts["gap_source"] == "zone_clearance"
        assert facts["gap_measured_mm"] is None
        assert facts["gap_mm"] == pytest.approx(0.2)
        assert facts["gap_consistent"] is False
        assert facts["gnd_fill_f"] == [] and facts["gnd_fill_b"] == []
        assert "fallback" in facts["sources"]["gap_mm"]

    def test_filled_flag_without_polys_not_counted(self):
        """filled=True 但 filled_polys_mm 为空（真实板 GUI 未填充/提取失败）：
        不臆造纹理，缝宽退回 clearance。"""
        from rfauto.service.kicad_em_service import board_facts_from_extract

        ex = _synthetic_extract()
        for z in ex["zones"]:
            z["filled"] = True
            z["filled_polys_mm"] = []
        facts = board_facts_from_extract(ex)
        assert facts["gnd_fill_f"] == []
        assert facts["gap_source"] == "zone_clearance"

    def test_no_gap_source_at_all(self):
        from rfauto.service.kicad_em_service import board_facts_from_extract

        ex = _synthetic_extract()
        ex["zones"] = []
        facts = board_facts_from_extract(ex)
        assert facts["gap_mm"] is None and facts["gap_source"] == "none"
        assert "无缝宽事实来源" in facts["sources"]["gap_mm"]

    def test_full_element_census(self):
        from rfauto.service.kicad_em_service import board_facts_from_extract

        facts = board_facts_from_extract(_synthetic_filled_extract())
        assert facts["net"] == "RF1" and facts["layer"] == "F.Cu"
        assert facts["ground_nets"] == ["GND"]
        assert facts["trace"]["points_mm"] == [[10.0, 15.0], [50.0, 15.0]]
        assert facts["trace"]["width_mm"] == pytest.approx(0.849)
        assert facts["trace"]["length_mm"] == pytest.approx(40.0)
        assert [v["x_mm"] for v in facts["vias"]] == [12.0, 24.0, 36.0, 48.0]
        assert all(v["y_mm"] == 18.0 and v["net"] == "GND"
                   for v in facts["vias"])
        assert [(p["x_mm"], p["w_mm"], p["h_mm"]) for p in facts["pads"]] == [
            (10.0, 0.8, 0.6), (50.0, 0.8, 0.6)]
        assert len(facts["gnd_fill_f"]) == 1 and len(facts["gnd_fill_b"]) == 1
        assert len(facts["gnd_fill_f"][0]["holes_mm"]) == 1
        assert facts["board_outline_mm"] == {"min_mm": [0.0, 0.0],
                                             "max_mm": [60.0, 30.0]}
        assert set(facts["sources"]) == {"trace", "gnd_fill", "gap_mm"}

    def test_json_roundtrip(self):
        import json

        from rfauto.service.kicad_em_service import board_facts_from_extract

        facts = board_facts_from_extract(_synthetic_filled_extract())
        assert json.loads(json.dumps(facts)) == facts  # service JSON 进出

    def test_bad_contract_raises(self):
        from rfauto.service.kicad_em_service import board_facts_from_extract

        with pytest.raises(ValueError, match="ok=False"):
            board_facts_from_extract(_synthetic_extract(ok=False))
        ex = _synthetic_filled_extract()
        ex["traces"] = [t for t in ex["traces"] if t["layer"] != "F.Cu"]
        with pytest.raises(ValueError, match=r"F\.Cu"):
            board_facts_from_extract(ex)

    def test_cpw_design_unchanged_by_fill(self):
        """cpw_design_from_extract 仍走 clearance（兼容口径不变，回归绊线）。"""
        from rfauto.service.kicad_em_service import cpw_design_from_extract

        d = cpw_design_from_extract(
            _synthetic_filled_extract(corridor_half_h=0.849 / 2 + 0.3))
        assert d["gap_mm"] == pytest.approx(0.2)  # 不受实测 0.3 影响
        assert "zones[" in d["sources"]["gap_mm"]
