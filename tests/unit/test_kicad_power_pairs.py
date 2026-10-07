"""KiCad 电源对自动提取（B5-5）单测：fixture .kicad_pcb 文本样本，全离线。

零 KiCad 安装依赖（纯 s-expression 文本解析路线，无 pcbnew 子进程分支——
 硬限 2 的 ABI 面整体绕开）。判据预声明（#122）：
1. sexp 解析：嵌套/引号转义/不配平 ValueError；
2. net 双格式（KiCad 10 内联名 / 旧式码查表）+ zone net_name 优先；
3. 网分类：缺省启发式（GND/VSS 族→地，+/VCC 族→电源）与显式名单**替换**
   语义、地网判定先于电源；
4. 平面偶 span：同层电源/地 zone bbox 正面积交集（6×3mm 锚逐位）；跨层
   /不重叠/零面积贴边不配对；
5. 过孔对：最近邻对心距逐位（0.5/0.7/1.0mm 锚）；统计量=全量、明细截断
   告警；操作量上限跳过告警；
6. 信封契约：文件缺失/文本坏/实参非法 → ok=False；空板 ok=True+告警；
7. 服务集成：pdn_power_pairs → pdn_plane_inputs[0] 直接喂 pdn_gate
   ``plane`` → 腔模 (1,0) 落带 FAIL（闭式 f10=11.7851…GHz 预声明）；
   spacing 链 mount_inductance 有限正值（消费契约守卫）。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from rfauto.adapters.kicad_power_pairs import (
    VIA_PAIR_LIST_DEFAULT,
    _classify_nets,
    extract_power_pairs,
    parse_sexp,
)
from rfauto.core.pdn import C0, mount_inductance
from rfauto.service.pdn_service import PDN_SERVICE_SCHEMA_VERSION, pdn_power_pairs

# ─── fixture 拼装（KiCad 10 新式 / ≤7 旧式两种 net 口径） ────────────────────

_STACKUP = (
    '(stackup (layer "F.Cu" (type "copper") (thickness 0.035))'
    ' (layer "dielectric 1" (type "core") (thickness 0.5) (epsilon_r 4.5)'
    " (loss_tangent 0.02))"
    ' (layer "B.Cu" (type "copper") (thickness 0.035)))'
)


def _zone(net: str, layers: str, rect: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = rect
    pts = f"(xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1})"
    return f'(zone (net "{net}") (net_name "{net}") ({layers}) (polygon (pts {pts})))'


def _via(net: str, x: float, y: float, size: float = 0.6, drill: float = 0.3) -> str:
    return (f'(via (at {x} {y}) (size {size}) (drill {drill})'
            f' (layers "F.Cu" "B.Cu") (net "{net}"))')


def _pcb(items: str, *, stackup: bool = True, old_style: bool = False) -> str:
    if old_style:
        header = (
            "(kicad_pcb (version 20221018) (generator pcbnew)\n"
            '(net 0 "") (net 1 "GND") (net 2 "+3V3") (net 3 "RF1")\n'
        )
    else:
        header = "(kicad_pcb (version 20260206) (generator pcbnew)\n"
    body = (_STACKUP + "\n" if stackup else "") + items + "\n"
    return header + body + ")\n"


_MINIMAL_PAIR_BOARD = _pcb(
    _zone("+3V3", 'layers "F.Cu"', (10.0, 10.0, 20.0, 15.0))
    + _zone("GND", 'layers "F.Cu"', (12.0, 11.0, 18.0, 14.0))
    + _via("+3V3", 15.0, 12.5)
    + _via("GND", 15.7, 12.5)
    + _via("GND", 30.0, 20.0)
)


def _write(tmp_path: Path, text: str, name: str = "board.kicad_pcb") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ─── sexp 解析 ────────────────────────────────────────────────────────────────


class TestParseSexp:
    def test_nested_lists_and_atoms(self) -> None:
        got = parse_sexp('(a (b 1) (c "x y") d)')
        assert got == [["a", ["b", "1"], ["c", "x y"], "d"]]

    def test_quoted_escape(self) -> None:
        got = parse_sexp(r'(name "a\"b\\c")')
        assert got[0][1] == 'a"b\\c'

    def test_unclosed_string_raises(self) -> None:
        with pytest.raises(ValueError, match="未闭合"):
            parse_sexp('(a "abc)')

    def test_extra_close_raises(self) -> None:
        with pytest.raises(ValueError, match="多余的右括号"):
            parse_sexp("(a))")

    def test_unclosed_paren_raises(self) -> None:
        with pytest.raises(ValueError, match="未闭合"):
            parse_sexp("(a (b 1)")


# ─── net 双格式 ───────────────────────────────────────────────────────────────


class TestNetFormats:
    def test_new_style_inline_name(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _MINIMAL_PAIR_BOARD)
        out = extract_power_pairs(p)
        assert out["ok"] is True
        assert out["nets"]["power"] == ["+3V3"]
        assert out["nets"]["ground"] == ["GND"]

    def test_old_style_code_lookup(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (10.0, 10.0, 20.0, 15.0))
            .replace('(net "+3V3") (net_name "+3V3")', "(net 2)")
            + _zone("GND", 'layers "F.Cu"', (12.0, 11.0, 18.0, 14.0)).replace(
                '(net "GND") (net_name "GND")', "(net 1)")
            + _via("+3V3", 15.0, 12.5).replace('(net "+3V3")', "(net 2)")
            + _via("GND", 15.7, 12.5).replace('(net "GND")', "(net 1)")
        )
        p = _write(tmp_path, _pcb(items, old_style=True))
        out = extract_power_pairs(p)
        assert out["ok"] is True
        assert out["nets"]["power"] == ["+3V3"]
        assert len(out["plane_pairs"]) == 1
        assert out["via_pair_stats"]["overall"]["n"] == 1

    def test_zone_net_name_preferred_over_code(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (10.0, 10.0, 20.0, 15.0))
            + _zone("GND", 'layers "F.Cu"', (12.0, 11.0, 18.0, 14.0))
        )
        p = _write(tmp_path, _pcb(items, stackup=False))
        out = extract_power_pairs(p)
        assert out["counts"]["zones_total"] == 2
        assert out["nets"]["ground"] == ["GND"]


# ─── 网分类 ──────────────────────────────────────────────────────────────────


class TestClassify:
    def test_default_heuristics(self) -> None:
        got = _classify_nets(
            ["GND", "AGND", "VSS_PWR", "+3V3", "VCC_MAIN", "VDD", "RF1", "SDA"],
            None, None)
        assert got["ground"] == ["AGND", "GND", "VSS_PWR"]
        assert got["power"] == ["+3V3", "VCC_MAIN", "VDD"]
        assert got["unclassified"] == ["RF1", "SDA"]

    def test_ground_beats_power_when_both_match(self) -> None:
        got = _classify_nets(["VINGND"], None, None)
        assert got["ground"] == ["VINGND"]
        assert got["power"] == []

    def test_explicit_lists_replace_heuristics(self) -> None:
        got = _classify_nets(["+3V3", "VMOTOR", "GND", "GOLD"], ["VMOTOR"], ["GOLD"])
        assert got["power"] == ["VMOTOR"]
        assert got["ground"] == ["GOLD"]
        assert got["unclassified"] == ["+3V3", "GND"]


# ─── 平面偶 span ──────────────────────────────────────────────────────────────


class TestPlanePairs:
    def test_overlap_span_exact(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _MINIMAL_PAIR_BOARD)
        out = extract_power_pairs(p)
        assert len(out["plane_pairs"]) == 1
        pair = out["plane_pairs"][0]
        assert pair["power_net"] == "+3V3"
        assert pair["ground_net"] == "GND"
        assert pair["layer"] == "F.Cu"
        assert pair["a_mm"] == pytest.approx(6.0)
        assert pair["b_mm"] == pytest.approx(3.0)
        assert pair["overlap_area_mm2"] == pytest.approx(18.0)
        entry = out["pdn_plane_inputs"][0]
        assert entry["a_m"] == pytest.approx(0.006)
        assert entry["b_m"] == pytest.approx(0.003)
        assert entry["er"] == pytest.approx(4.5)
        assert entry["layer"] == "F.Cu"

    def test_non_overlapping_zones_no_pair(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (0.0, 0.0, 5.0, 5.0))
            + _zone("GND", 'layers "F.Cu"', (10.0, 10.0, 20.0, 20.0))
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["plane_pairs"] == []
        assert out["pdn_plane_inputs"] == []

    def test_different_layers_no_pair(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (10.0, 10.0, 20.0, 15.0))
            + _zone("GND", 'layers "B.Cu"', (12.0, 11.0, 18.0, 14.0))
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["plane_pairs"] == []

    def test_touching_edge_zero_area_no_pair(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (0.0, 0.0, 10.0, 10.0))
            + _zone("GND", 'layers "F.Cu"', (10.0, 0.0, 20.0, 10.0))
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["plane_pairs"] == []

    def test_multilayer_zone_pair_per_layer(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu" "B.Cu"', (0.0, 0.0, 20.0, 10.0))
            + _zone("GND", 'layers "F.Cu"', (2.0, 1.0, 10.0, 8.0))
            + _zone("GND", 'layers "B.Cu"', (5.0, 2.0, 15.0, 9.0))
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        layers = sorted(p["layer"] for p in out["plane_pairs"])
        assert layers == ["B.Cu", "F.Cu"]
        entry = out["pdn_plane_inputs"][0]
        # pdn_plane_inputs 取重叠面积最大的候选（B.Cu 10×7=70 > F.Cu 8×7=56）
        assert entry["layer"] == "B.Cu"
        assert entry["n_candidate_plane_pairs"] == 2
        assert entry["a_m"] == pytest.approx(0.010)
        assert entry["b_m"] == pytest.approx(0.007)

    def test_arc_only_outline_skipped_with_warning(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (0.0, 0.0, 20.0, 10.0))
            + '(zone (net "GND") (net_name "GND") (layers "F.Cu")'
            " (polygon (pts (arc (start 1 1) (mid 2 2) (end 3 1)))))"
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["plane_pairs"] == []
        assert any("轮廓点 <3" in w for w in out["warnings"])


# ─── 过孔对 ──────────────────────────────────────────────────────────────────


class TestViaPairs:
    def test_nearest_ground_via_exact(self, tmp_path: Path) -> None:
        items = (
            _via("+3V3", 15.0, 12.5)
            + _via("GND", 16.0, 12.5)   # d=1.0
            + _via("GND", 25.0, 12.5)   # d=10.0
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["via_pair_note"] == "ok"
        assert len(out["via_pairs"]) == 1
        pair = out["via_pairs"][0]
        assert pair["spacing_mm"] == pytest.approx(1.0)
        assert pair["ground_via"]["x_mm"] == pytest.approx(16.0)
        assert out["via_pair_stats"]["overall"]["n"] == 1

    def test_stats_over_all_pairs_and_truncation(self, tmp_path: Path) -> None:
        items = (
            _via("+3V3", 15.0, 12.5)
            + _via("+3V3", 16.5, 12.5)
            + _via("GND", 16.0, 12.5)   # d(P1)=1.0, d(P2)=0.5
            + _via("GND", 25.0, 12.5)   # d(P1)=10.0, d(P2)=8.5
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)), max_via_pairs=1)
        assert out["via_pair_stats"]["overall"] == {
            "min": 0.5, "median": 0.75, "max": 1.0, "n": 2}
        assert len(out["via_pairs"]) == 1
        assert out["via_pairs"][0]["spacing_mm"] == pytest.approx(0.5)
        assert any("截断" in w for w in out["warnings"])

    def test_default_list_cap_constant_used(self, tmp_path: Path) -> None:
        items = "".join(_via("+3V3", float(i), 0.0) for i in range(5)) + _via("GND", 0.0, 1.0)
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["via_pair_stats"]["overall"]["n"] == 5
        assert len(out["via_pairs"]) == 5
        assert VIA_PAIR_LIST_DEFAULT == 200  # 缺省上限常量本身不被本用例触发

    def test_no_ground_vias_warns(self, tmp_path: Path) -> None:
        out = extract_power_pairs(_write(tmp_path, _pcb(_via("+3V3", 1.0, 1.0), stackup=False)))
        assert out["via_pairs"] == []
        assert out["via_pair_note"] == "no_power_or_ground_vias"
        assert any("无地网过孔" in w for w in out["warnings"])

    def test_op_cap_skips_pairing(self, tmp_path: Path) -> None:
        n = 2010  # 2010×2010 = 4_040_100 > 4_000_000 上限
        items = "".join(_via("+3V3", float(i % 50), float(i // 50)) for i in range(n))
        items += "".join(_via("GND", 100.0 + float(i % 50), float(i // 50)) for i in range(n))
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["via_pair_note"] == "skipped_op_cap"
        assert out["via_pairs"] == []
        assert any("超操作量上限" in w for w in out["warnings"])

    def test_spacing_feeds_mount_inductance_contract(self, tmp_path: Path) -> None:
        out = extract_power_pairs(_write(tmp_path, _MINIMAL_PAIR_BOARD))
        spacing_m = out["via_pairs"][0]["spacing_mm"] * 1e-3
        radius_m = out["via_pairs"][0]["power_via"]["pad_diameter_mm"] * 1e-3 / 2.0
        assert spacing_m > 2.0 * radius_m  # arcosh 定义域（消费契约）
        l_h = mount_inductance(1.6e-3, radius_m, spacing_m)
        assert math.isfinite(l_h) and l_h > 0.0


# ─── 信封契约 ────────────────────────────────────────────────────────────────


class TestEnvelope:
    def test_missing_file_ok_false(self, tmp_path: Path) -> None:
        out = extract_power_pairs(tmp_path / "nope.kicad_pcb")
        assert out["ok"] is False
        assert "不存在" in out["errors"][0]

    def test_malformed_text_ok_false(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "(kicad_pcb (version 1)")
        out = extract_power_pairs(p)
        assert out["ok"] is False
        assert "解析失败" in out["errors"][0]

    def test_empty_board_ok_true_with_warnings(self, tmp_path: Path) -> None:
        out = extract_power_pairs(_write(tmp_path, _pcb("", stackup=False)))
        assert out["ok"] is True
        assert out["plane_pairs"] == []
        assert out["via_pairs"] == []
        assert out["nets"] == {"ground": [], "power": [], "unclassified": []}
        assert any("无电源网过孔" in w for w in out["warnings"])

    def test_board_version_parsed(self, tmp_path: Path) -> None:
        out = extract_power_pairs(_write(tmp_path, _MINIMAL_PAIR_BOARD))
        assert out["board"]["version"] == 20260206.0

    def test_no_stackup_er_none_with_warning(self, tmp_path: Path) -> None:
        items = (
            _zone("+3V3", 'layers "F.Cu"', (10.0, 10.0, 20.0, 15.0))
            + _zone("GND", 'layers "F.Cu"', (12.0, 11.0, 18.0, 14.0))
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(items, stackup=False)))
        assert out["pdn_plane_inputs"][0]["er"] is None
        assert any("epsilon_r" in w for w in out["warnings"])

    @pytest.mark.parametrize("bad", [0, True, "x"])
    def test_bad_max_via_pairs_ok_false(self, tmp_path: Path, bad: object) -> None:
        out = extract_power_pairs(_write(tmp_path, _MINIMAL_PAIR_BOARD), max_via_pairs=bad)  # type: ignore[arg-type]
        assert out["ok"] is False
        assert any("max_via_pairs" in e for e in out["errors"])


# ─── 服务层信封 + pdn_gate 集成 ──────────────────────────────────────────────


class TestServicePdnPowerPairs:
    def test_envelope_ok_with_schema_version(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _MINIMAL_PAIR_BOARD)
        out = pdn_power_pairs({"pcb_path": str(p)})
        assert out["ok"] is True
        assert out["schema_version"] == PDN_SERVICE_SCHEMA_VERSION
        assert out["pcb_path"] == str(p)
        assert len(out["pdn_plane_inputs"]) == 1

    def test_missing_pcb_path_ok_false(self) -> None:
        out = pdn_power_pairs({})
        assert out["ok"] is False
        assert any("pcb_path" in e for e in out["errors"])

    def test_bad_net_list_ok_false(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _MINIMAL_PAIR_BOARD)
        out = pdn_power_pairs({"pcb_path": str(p), "power_nets": "+3V3"})
        assert out["ok"] is False
        assert any("power_nets" in e for e in out["errors"])

    def test_plane_input_feeds_pdn_gate_cavity_fail(self, tmp_path: Path) -> None:
        """预声明闭式锚：a=6mm/b=3mm/er=4.5 → f10=c0/(2√er)/a=11.7851…GHz 落带。"""
        from rfauto.service.pdn_service import pdn_gate

        p = _write(tmp_path, _MINIMAL_PAIR_BOARD)
        pairs_out = pdn_power_pairs({"pcb_path": str(p)})
        assert pairs_out["ok"] is True
        plane_in = pairs_out["pdn_plane_inputs"][0]
        gate = pdn_gate({
            "plane": {"a_m": plane_in["a_m"], "b_m": plane_in["b_m"],
                      "er": plane_in["er"]},
            "interest_band": {"f_lo_hz": 10e9, "f_hi_hz": 13e9},
        })
        assert gate["ok"] is True
        assert gate["verdict"] == "FAIL"
        assert gate["unknown_reason"] is None
        assert [(m["m"], m["n"]) for m in gate["modes_in_band"]] == [(1, 0)]
        f10 = C0 / (2.0 * math.sqrt(4.5)) / 0.006
        assert gate["modes_in_band"][0]["f_hz"] == pytest.approx(f10, rel=1e-12)


# ─── 去耦电容簇（B5-5 剩余件） ────────────────────────────────────────────────


def _footprint(
    ref: str,
    x: float,
    y: float,
    pads: list[tuple[str, str]],
    value: str = "100nF",
    fp: str = "Capacitor_SMD:C_0402_1005Metric",
) -> str:
    pad_txt = "".join(
        f'(pad "{n}" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu")'
        f' (net "{net}"))'
        for n, net in pads
    )
    return (
        f'(footprint "{fp}" (layer "F.Cu") (at {x} {y})'
        f' (property "Reference" "{ref}" (at 0 0) (layer "F.SilkS"))'
        f' (property "Value" "{value}" (at 0 0) (layer "F.Fab"))'
        + pad_txt + ")"
    )


class TestDecapClusters:
    def test_bridging_footprint_single_cluster(self, tmp_path: Path) -> None:
        board = _pcb(_footprint("C1", 12.0, 13.0, [("1", "+3V3"), ("2", "GND")]))
        out = extract_power_pairs(_write(tmp_path, board))
        assert out["ok"] is True
        assert len(out["decap_clusters"]) == 1
        c = out["decap_clusters"][0]
        assert c["pair_key"] == "+3V3__GND"
        assert c["power_net"] == "+3V3"
        assert c["ground_net"] == "GND"
        assert c["n_decaps"] == 1
        assert c["refs"] == ["C1"]
        assert c["centroid_mm"] == [12.0, 13.0]
        assert c["decaps"][0]["footprint"] == "Capacitor_SMD:C_0402_1005Metric"
        assert c["decaps"][0]["value"] == "100nF"

    def test_centroid_two_decaps_sorted_refs(self, tmp_path: Path) -> None:
        board = _pcb(
            _footprint("C2", 3.0, 4.0, [("1", "+3V3"), ("2", "GND")])
            + _footprint("C1", 1.0, 2.0, [("1", "+3V3"), ("2", "GND")])
        )
        out = extract_power_pairs(_write(tmp_path, board))
        (c,) = out["decap_clusters"]
        assert c["n_decaps"] == 2
        assert c["refs"] == ["C1", "C2"]
        assert c["centroid_mm"] == [2.0, 3.0]
        assert [d["x_mm"] for d in c["decaps"]] == [1.0, 3.0]

    def test_non_bridging_footprint_not_decap(self, tmp_path: Path) -> None:
        board = _pcb(
            _footprint("C1", 1.0, 1.0, [("1", "+3V3"), ("2", "+3V3")])
            + _footprint("R1", 5.0, 5.0, [("1", "+3V3"), ("2", "RF1")])
        )
        out = extract_power_pairs(_write(tmp_path, board))
        assert out["ok"] is True
        assert out["decap_clusters"] == []
        assert out["counts"]["footprints_total"] == 2
        assert out["counts"]["decaps_total"] == 0
        assert out["counts"]["decap_clusters"] == 0

    def test_old_style_net_codes_resolved(self, tmp_path: Path) -> None:
        fp = (
            '(footprint "C:C_0402" (layer "F.Cu") (at 7.0 8.0)'
            ' (property "Reference" "C7" (at 0 0) (layer "F.SilkS"))'
            ' (property "Value" "1uF" (at 0 0) (layer "F.Fab"))'
            ' (pad "1" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net 2))'
            ' (pad "2" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net 1)))'
        )
        out = extract_power_pairs(
            _write(tmp_path, _pcb(fp, old_style=True)))
        assert len(out["decap_clusters"]) == 1
        c = out["decap_clusters"][0]
        assert (c["power_net"], c["ground_net"]) == ("+3V3", "GND")
        assert c["refs"] == ["C7"]
        assert c["decaps"][0]["value"] == "1uF"

    def test_module_fp_text_fallback(self, tmp_path: Path) -> None:
        mod = (
            '(module "CAP" (layer "F.Cu") (at 5.0 5.0)'
            ' (fp_text reference "C9" (at 0 0) (layer "F.SilkS"))'
            ' (fp_text value "10uF" (at 0 0) (layer "F.Fab"))'
            ' (pad "1" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net "+VBUS"))'
            ' (pad "2" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net "GND")))'
        )
        out = extract_power_pairs(_write(tmp_path, _pcb(mod)))
        assert len(out["decap_clusters"]) == 1
        c = out["decap_clusters"][0]
        assert c["pair_key"] == "+VBUS__GND"
        assert c["decaps"][0]["reference"] == "C9"
        assert c["decaps"][0]["footprint"] == "CAP"
        assert c["decaps"][0]["value"] == "10uF"

    def test_multi_rail_bridge_each_pair(self, tmp_path: Path) -> None:
        board = _pcb(_footprint(
            "C1", 2.0, 2.0,
            [("1", "+1V8"), ("2", "+3V3"), ("3", "GND")],
        ))
        out = extract_power_pairs(_write(tmp_path, board))
        keys = [c["pair_key"] for c in out["decap_clusters"]]
        assert keys == ["+1V8__GND", "+3V3__GND"]
        assert all(c["n_decaps"] == 1 for c in out["decap_clusters"])

    def test_counts_consistent(self, tmp_path: Path) -> None:
        board = _pcb(
            _footprint("C1", 1.0, 1.0, [("1", "+3V3"), ("2", "GND")])
            + _footprint("C2", 3.0, 3.0, [("1", "+3V3"), ("2", "GND")])
            + _footprint("C3", 9.0, 9.0, [("1", "RF1"), ("2", "GND")])
        )
        out = extract_power_pairs(_write(tmp_path, board))
        assert out["counts"]["footprints_total"] == 3
        assert out["counts"]["decaps_total"] == 2
        assert out["counts"]["decap_clusters"] == 1

    def test_service_passthrough(self, tmp_path: Path) -> None:
        board = _pcb(_footprint("C1", 1.0, 1.0, [("1", "+3V3"), ("2", "GND")]))
        out = pdn_power_pairs({"pcb_path": str(_write(tmp_path, board))})
        assert out["ok"] is True
        assert out["schema_version"] == PDN_SERVICE_SCHEMA_VERSION
        assert out["counts"]["decap_clusters"] == 1
        assert out["decap_clusters"][0]["refs"] == ["C1"]
