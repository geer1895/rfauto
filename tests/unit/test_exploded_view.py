"""exploded_view_service 测试（T-Q37 席位 Q-X37，aurora_q 方向 CAD 3D）。

覆盖面（零网络零真机零仿真，全离线秒级）：
1. layered_stack 源场景（layout 单源直通+offsets 单源+分层围合计数+腔体
   透明化盒）；
2. kicad 源场景（s-expr 线性扫描：叠层 mm 换算/走线/过孔/板框回落/
   未知层如实跳过/严格 εr）；
3. geometry_lint 闭环（名义零 ERROR 恰 2 WARN 镜 Q-X4 口径+零 ERROR 才
   渲染门+过孔不进 lint 投影声明面）；
4. 三形态渲染钉（SVG 结构与交互 CSS/JS 在场+three.js 场景图+PNG 确定性
   sha256 双跑逐字节）；
5. CLI 叶（--json 双路径+exit 2 usage 信封+注册面+域本地计数链——绝对
   总数钉归共享面，本文件只钉域内与和一致性，㉑ 并发计数协议）；
6. STEP/GLB 接口预留声明（NotImplementedError+docstring 边界）；
7. U+FFFD=0 产物卫生。
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.cli.help_groups import top_level_panel_names
from rfauto.cli.main import app as cli_app
from rfauto.service import exploded_view_service as evs
from rfauto.service.exploded_view_service import (
    _EXPLODED_VIEW_SCHEMA_VERSION,
    EXPLODE_FACTOR_DEFAULT,
    LAYER_GAP_SOURCE,
    _gate_errors,
    _lint_projection_kicad,
    build_scene,
    export_glb,
    export_step,
    render_exploded_view,
)

runner = CliRunner()

_KICAD_FIXTURE = (REPO / "tests" / "unit" / "fixtures" / "format_overview" /
                  "minimal_board.kicad_pcb")


def _render(content: dict, tmp_path: Path, **kw: object) -> dict:
    return render_exploded_view(
        content, out_dir=tmp_path, spec_path=tmp_path / "spec.json", **kw)


def _kicad_content(**extra: object) -> dict:
    out: dict = {"source": "kicad", "pcb_path": str(_KICAD_FIXTURE),
                 "scene_name": "kicad_minimal"}
    out.update(extra)
    return out


def _write_pcb(tmp_path: Path, text: str) -> str:
    p = tmp_path / "board.kicad_pcb"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _load_check_numbers():
    import importlib.util

    spec_ = importlib.util.spec_from_file_location(
        "check_numbers", REPO / "scripts" / "check_numbers.py")
    module = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(module)
    return module


# ─── 1) 常量与口径声明 ──────────────────────────────────────────────────


def test_schema_version_and_declared_constants():
    """schema 版本与声明常量（任务书文法缺省=1.5；层距单源=max 层厚）。"""
    assert _EXPLODED_VIEW_SCHEMA_VERSION == "exploded-view/v0"
    assert EXPLODE_FACTOR_DEFAULT == 1.5
    assert LAYER_GAP_SOURCE == "max_layer_thickness"


# ─── 2) layered_stack 源场景 ────────────────────────────────────────────


class TestLayeredScene:
    def test_layers_and_offsets_symmetric(self):
        """5 层 bottom→top；偏移=（i−中心）·gap·factor 对称（和恒 0，居中展开）。"""
        scene = build_scene({"source": "layered_stack"})
        assert scene["source_kind"] == "layered_stack"
        assert [lay["name"] for lay in scene["layers"]] == [
            "0:silicon", "1:gold", "2:silicon", "3:gold", "4:silicon"]
        gap = scene["explode"]["gap_mm"]
        assert gap == 0.25  # max 层厚=0.25（silicon 层）
        offsets = scene["explode"]["offsets_mm"]
        assert offsets["0"] == pytest.approx(-2 * gap * 1.5)
        assert offsets["2"] == pytest.approx(0.0)
        assert offsets["4"] == pytest.approx(2 * gap * 1.5)
        assert sum(offsets.values()) == pytest.approx(0.0)
        for lay in scene["layers"]:
            assert lay["offset_mm"] == offsets[str(lay["index"])]

    def test_layered_segmentation_counts_and_strip(self):
        """分层围合计数（11 固体+7 零厚片=6 腔壁+strip）+strip 贴带面零厚。"""
        scene = build_scene({"source": "layered_stack"})
        c = scene["counts"]
        assert c == {"n_layers": 5, "n_solids": 11, "n_sheets": 7,
                     "n_traces": 0, "n_vias": 0, "n_cavity": 1}
        strip = next(s for s in scene["solids"] if s["name"] == "strip")
        assert strip["kind"] == "sheet" and strip["layer_index"] == 2
        assert strip["box_mm"][2] == strip["box_mm"][5] == 0.0  # 带面 z=0
        wall_names = {s["name"] for s in scene["solids"]
                      if s["name"].startswith("cavity_wall")}
        assert len(wall_names) == 6  # top/bottom+上腔侧壁×2+下腔侧壁×2
        # sheet=某轴零厚（顶/底/strip=z 零厚；侧壁=y 零厚竖片）——不猜轴向
        assert all(
            (s["box_mm"][0] == s["box_mm"][3])
            or (s["box_mm"][1] == s["box_mm"][4])
            or (s["box_mm"][2] == s["box_mm"][5])
            for s in scene["solids"] if s["kind"] == "sheet")

    def test_cavity_transparent_volume_attached_to_conductor_layer(self):
        """腔体透明化盒=贯通全长×腔截面×z 区间，挂导体层（偏移随动）。"""
        scene = build_scene({"source": "layered_stack"})
        cav = scene["cavity"]
        assert cav is not None and cav["layer_index"] == 2
        assert cav["box_mm"] == pytest.approx(
            [-2.55, -0.45, -0.25, 2.55, 0.45, 0.25])  # x=±line_len/2
        assert cav["offset_mm"] == scene["explode"]["offsets_mm"]["2"]

    def test_zero_factor_collapses_offsets(self):
        """factor=0=收拢回名义叠放（全部偏移 0，坐标=layout 直通）。"""
        scene = build_scene({"source": "layered_stack"}, explode_factor=0.0)
        assert all(v == 0.0 for v in scene["explode"]["offsets_mm"].values())

    def test_invalid_factor_rejected(self):
        """负/非有限/非数 factor fail-loud（build 抛 ValueError，信封 ok=False）。"""
        for bad in (-1.0, float("inf"), float("nan"), "x", True):
            with pytest.raises(ValueError):
                build_scene({"source": "layered_stack"}, explode_factor=bad)
        # 信封路径：factor 校验先行，不触渲染（out_dir=None 合法）
        r = render_exploded_view({"source": "layered_stack"},
                                 explode_factor=-1.0, out_dir=None)
        assert r["ok"] is False and r["errors"]


# ─── 3) kicad 源场景 ────────────────────────────────────────────────────


class TestKicadScene:
    def test_layers_mm_conversion_bottom_up(self):
        """叠层 s-expr→mm 显式 ×1e3（米→毫米），bottom→top 序+max 层厚 gap。"""
        scene = build_scene(_kicad_content())
        names = [lay["name"] for lay in scene["layers"]]
        assert names == ["B.Cu", "dielectric 1", "F.Cu"]
        assert [lay["kind"] for lay in scene["layers"]] == [
            "metal", "dielectric", "metal"]
        assert scene["layers"][0]["z0_mm"] == pytest.approx(0.0, abs=1e-12)
        assert scene["layers"][1]["z0_mm"] == pytest.approx(0.035)
        assert scene["layers"][2]["z1_mm"] == pytest.approx(1.58)
        assert scene["explode"]["gap_mm"] == pytest.approx(1.51)

    def test_traces_vias_and_counts(self):
        """走线盒=定向足迹四边形的精确 AABB（方帽 ±w/2），z=所在层顶面（零厚）；
        过孔全厚跨层挂 None。

        y 轴=KiCad 屏幕系翻转（y_model=−y_kicad）：段 (10,10)→(15,10) w0.2
        → x∈[9.9,15.1]、y∈[−10.1,−9.9]；竖段 (15,10)→(15,15) 非退化
        （#212 目检抓出的"竖段 dx=0 整段不可见"回归钉）；过孔中心 y=−10。
        """
        scene = build_scene(_kicad_content())
        c = scene["counts"]
        assert c["n_traces"] == 3 and c["n_vias"] == 1 and c["n_solids"] == 3
        t0 = next(s for s in scene["solids"] if s["name"] == "trace_0000")
        assert t0["box_mm"] == pytest.approx(
            [9.9, -10.1, 1.58, 15.1, -9.9, 1.58])
        assert t0["layer_index"] == 2  # F.Cu
        t1 = next(s for s in scene["solids"] if s["name"] == "trace_0001")
        assert t1["box_mm"] == pytest.approx(
            [14.9, -15.1, 1.58, 15.1, -9.9, 1.58])  # 竖段：x 向也有 w 宽
        via = next(s for s in scene["solids"] if s["kind"] == "via")
        assert via["layer_index"] is None
        assert (via["box_mm"][1] + via["box_mm"][4]) / 2.0 == pytest.approx(-10.0)
        assert via["box_mm"][2] == pytest.approx(0.0, abs=1e-12)
        assert via["box_mm"][5] == pytest.approx(1.58)

    def test_every_trace_renders_one_positive_area_polygon(self):
        """每条走线恰出 1 枚正面积多边形（退化盒零面=整段静默消失的回归钉）。"""
        scene = build_scene(_kicad_content())
        polys = evs._scene_polygons(scene)
        trace_polys = [p for p in polys
                       if p["group"] in ("l0", "l2") and not p["dashed"]]
        assert len(trace_polys) == scene["counts"]["n_traces"] == 3

        def _area(pts):  # 鞋带公式（独立于构造式的面积裁判，#118）
            return abs(sum(pts[i][0] * pts[(i + 1) % 4][1]
                           - pts[(i + 1) % 4][0] * pts[i][1]
                           for i in range(4))) / 2.0

        for p in trace_polys:
            assert _area(p["pts3"]) > 0.0

    def test_trace_quad_diagonal_independent_check(self):
        """斜向段足迹：鞋带面积=(L+w)·w、形心=段中点（独立几何裁判）。"""
        quad = evs._trace_quad([[0.0, 0.0], [3.0, 4.0]], 0.2, 7.0)
        area = abs(sum(quad[i][0] * quad[(i + 1) % 4][1]
                       - quad[(i + 1) % 4][0] * quad[i][1]
                       for i in range(4))) / 2.0
        assert area == pytest.approx((5.0 + 0.2) * 0.2)
        cx = sum(q[0] for q in quad) / 4.0
        cy = sum(q[1] for q in quad) / 4.0
        assert (cx, cy) == pytest.approx((1.5, 2.0))
        assert all(q[2] == 7.0 for q in quad)

    def test_diagonal_trace_rendered_as_oriented_quad_not_aabb(self, tmp_path):
        """斜向走线渲染=定向四边形（面积=(L+w)·w），非 AABB 大矩形（变异钉：
        渲染路径退回 AABB 时面积≈(dx+w)(dy+w) 远大于真足迹即红）。"""
        text = _KICAD_FIXTURE.read_text(encoding="utf-8")
        diag = ('  (segment (start 0 0) (end 3 4) (width 0.2) '
                '(layer "F.Cu") (net 1))\n')
        patched = text.replace("	(gr_rect", diag + "	(gr_rect", 1)
        assert "(end 3 4)" in patched
        scene = build_scene(_kicad_content(pcb_path=_write_pcb(tmp_path, patched)))
        diag_ent = next(s for s in scene["solids"]
                        if s["kind"] == "trace" and s["segment_mm"][1] == [3.0, -4.0])
        polys = evs._scene_polygons(scene)
        z_top = diag_ent["box_mm"][2] + diag_ent["offset_mm"]

        def _area(pts):
            n = len(pts)
            return abs(sum(pts[i][0] * pts[(i + 1) % n][1]
                           - pts[(i + 1) % n][0] * pts[i][1]
                           for i in range(n))) / 2.0

        cands = [p for p in polys if p["group"] == "l2" and not p["dashed"]
                 and all(abs(q[2] - z_top) < 1e-12 for q in p["pts3"])
                 and any(abs(q[0]) < 0.5 and abs(q[1]) < 0.5 for q in p["pts3"])]
        assert len(cands) == 1
        assert _area(cands[0]["pts3"]) == pytest.approx((5.0 + 0.2) * 0.2)

    def test_kicad_axis_flip_no_mirror_and_no_negative_zero(self):
        """KiCad y 翻转声明（顶视不镜像）+ 板框 y=0 边不产 −0.0（0.0−y 写法）。"""
        import math

        scene = build_scene(_kicad_content())
        outline = scene["notes"]["board_outline_mm"]
        assert outline == [0.0, -20.0, 30.0, 0.0]  # KiCad (0,0)-(30,20) 翻转
        assert math.copysign(1.0, outline[3]) == 1.0  # +0.0 非 −0.0
        assert "y_model=−y_kicad" in scene["notes"]["kicad_axis_convention"]

    def test_outline_fallback_warning(self, tmp_path):
        """无 Edge.Cuts 板框→走线包络回落+warning 如实登记（零编造板框）。"""
        text = _KICAD_FIXTURE.read_text(encoding="utf-8")
        stripped = "\n".join(line for line in text.splitlines()
                             if not line.strip().startswith("(gr_rect"))
        pcb = _write_pcb(tmp_path, stripped)
        r = _render(_kicad_content(pcb_path=pcb), tmp_path)
        assert r["ok"] is True
        assert any("板框" in w for w in r["warnings"])
        scene = r["view"]
        x0s = [s["box_mm"][0] for s in scene["solids"] if s["kind"] == "solid"]
        x1s = [s["box_mm"][3] for s in scene["solids"] if s["kind"] == "solid"]
        assert min(x0s) == pytest.approx(10.0) and max(x1s) == pytest.approx(20.0)

    def test_unknown_layer_segment_skipped_with_warning(self, tmp_path):
        """segment 层名不在叠层名单→如实跳过+warning 计数（不猜归属）。"""
        text = _KICAD_FIXTURE.read_text(encoding="utf-8")
        extra = '  (segment (start 1 1) (end 2 2) (width 0.2) (layer "In1.Cu") (net 1))\n'
        patched = text.replace("	(gr_rect", extra + "	(gr_rect", 1)
        assert '(layer "In1.Cu")' in patched  # 注入生效（替换命中自证）
        pcb = _write_pcb(tmp_path, patched)
        r = _render(_kicad_content(pcb_path=pcb), tmp_path)
        assert r["ok"] is True
        assert any("segment" in w and "跳过" in w for w in r["warnings"])
        assert r["counts"]["n_traces"] == 3  # 4 解析−1 跳过

    def test_missing_pcb_path_fail_loud(self, tmp_path):
        """pcb_path 缺失/不存在显式报错（#144 同族：零缺省落位）。"""
        r1 = _render({"source": "kicad"}, tmp_path)
        assert r1["ok"] is False and any("pcb_path" in e for e in r1["errors"])
        r2 = _render(_kicad_content(pcb_path=str(tmp_path / "nope.kicad_pcb")),
                     tmp_path)
        assert r2["ok"] is False and any("不存在" in e for e in r2["errors"])

    def test_missing_epsilon_strict(self, tmp_path):
        """介质层缺 εr 严格报错（require_epsilon_r 缺省 True——全层消费不猜）。"""
        text = _KICAD_FIXTURE.read_text(encoding="utf-8")
        patched = text.replace("(epsilon_r 4.5) ", "")
        pcb = _write_pcb(tmp_path, patched)
        r = _render(_kicad_content(pcb_path=pcb), tmp_path)
        assert r["ok"] is False and any("epsilon_r" in e for e in r["errors"])


# ─── 4) lint 闭环（零 ERROR 才渲染）─────────────────────────────────────


class TestLintGate:
    def test_layered_nominal_zero_error_two_warn(self, tmp_path):
        """名义 spec：lint_pass=True、0 ERROR 恰 2 WARN（镜 Q-X4 名义口径）。"""
        r = _render({"source": "layered_stack", "spec": {}}, tmp_path)
        assert r["ok"] is True and r["lint_pass"] is True
        assert r["lint"]["counts"] == {"error": 0, "warn": 2}
        lint_disk = json.loads(
            Path(r["outputs"]["lint_json"]["path"]).read_text(encoding="utf-8"))
        assert lint_disk["lint_pass"] is True
        assert lint_disk["counts"] == r["lint"]["counts"]

    def test_kicad_lint_clean_and_via_excluded(self):
        """kicad 投影=层板+走线零厚片（过孔显式排除——检查④误报声明面）。"""
        scene = build_scene(_kicad_content())
        proj = _lint_projection_kicad(scene)
        names = [b["name"] for b in proj["boxes"]]
        assert any(n.startswith("layer0") for n in names)
        assert any(n.startswith("trace_") for n in names)
        assert not any(n.startswith("via_") for n in names)
        from rfauto.service.geometry_lint_service import lint_geometry

        rep = lint_geometry(proj)
        assert rep["ok"] is True and rep["lint_pass"] is True
        assert rep["counts"]["error"] == 0

    def test_gate_errors_blocks_and_passes(self):
        """门函数三态：0 ERROR 放行/ERROR 拦截带计数/信封异常拦截。"""
        assert _gate_errors({"ok": True, "counts": {"error": 0}}) == []
        blocked = _gate_errors({"ok": True, "counts": {"error": 2},
                                "issues": [{"level": "ERROR", "check": "x",
                                            "objects": ["a"], "message": "m"}]})
        assert len(blocked) >= 1 and "2" in blocked[0]
        assert _gate_errors({"ok": False, "errors": ["bad schema"]})

    def test_error_report_blocks_rendering(self, tmp_path, monkeypatch):
        """lint ERROR=渲染拦截：ok=False 且渲染产物零落盘（闭环核心钉）。"""
        def _bad_report(scene, content):
            return {"ok": True, "lint_pass": False,
                    "counts": {"error": 1, "warn": 0},
                    "issues": [{"check": "partial_intersection",
                                "level": "ERROR", "objects": ["a", "b"],
                                "message": "部分相交"}],
                    "model_units": "mm",
                    "summary": {"boxes": 0, "ports": 0, "variables": 0}}

        monkeypatch.setattr(evs, "_lint_report_for_scene", _bad_report)
        r = _render({"source": "layered_stack"}, tmp_path)
        assert r["ok"] is False and r["lint_pass"] is False
        assert r.get("rendered") is False
        assert any("拦截" in e for e in r["errors"])
        assert not list(tmp_path.glob("*.svg"))
        assert not list(tmp_path.glob("*.png"))
        assert not list(tmp_path.glob("*.json"))  # lint json 也不落（渲染零落盘）


# ─── 5) 三形态渲染钉 ────────────────────────────────────────────────────


class TestRenderers:
    def test_svg_structure_and_interactivity(self, tmp_path):
        """SVG=合法 XML+分层图例按钮+ev-off-g 筛选类+rotate/wheel 交互 JS 在场。"""
        r = _render({"source": "layered_stack"}, tmp_path)
        svg_text = Path(r["outputs"]["svg"]["path"]).read_text(encoding="utf-8")
        root = ET.fromstring(svg_text)
        assert root.tag.endswith("svg")
        assert root.get("viewBox")
        assert svg_text.count('class="ev-btn"') == r["counts"]["n_layers"]
        assert ".ev-off-g" in svg_text and "rotate(" in svg_text
        assert "wheel" in svg_text and "<script>" in svg_text
        # 分层筛选按 class 切换几何本体（非仅标签）——每层多边形都带层 class
        assert "querySelectorAll('.ev-l-'" in svg_text
        polys = [el for el in root.iter() if el.tag.endswith("polygon")]
        for i in range(5):
            assert f'id="ev-layer-g-{i}"' in svg_text
            assert any(f"ev-l-{i}" in (el.get("class") or "").split()
                       for el in polys), i

    def test_svg_json_png_lint_deterministic(self, tmp_path):
        """同输入两跑逐字节同（svg/json/png/lint 四产物 sha256 相等）。"""
        r1 = _render({"source": "layered_stack"}, tmp_path / "a")
        r2 = _render({"source": "layered_stack"}, tmp_path / "b")
        for key in ("svg", "json", "png", "lint_json"):
            assert r1["outputs"][key]["sha256"] == r2["outputs"][key]["sha256"], key

    def test_png_magic_bytes(self, tmp_path):
        """PNG=真 PNG（magic 字节）+Agg OO API 产物（非空）。"""
        r = _render({"source": "layered_stack"}, tmp_path)
        raw = Path(r["outputs"]["png"]["path"]).read_bytes()
        assert raw[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(raw) > 10000

    def test_threejson_scene_graph(self, tmp_path):
        """three.js ObjectLoader 场景图：metadata/几何/材质/children+偏移随节点。"""
        r = _render({"source": "layered_stack"}, tmp_path)
        tj = json.loads(
            Path(r["outputs"]["json"]["path"]).read_text(encoding="utf-8"))
        assert tj["metadata"]["type"] == "Object"
        assert tj["metadata"]["version"] == "4.5"
        names = [c["name"] for c in tj["object"]["children"]]
        assert len(names) == len(set(names))
        assert len(tj["materials"]) < len(names)  # 材质按视觉键去重
        assert tj["extras"]["explode"]["factor"] == 1.5
        strip_node = next(c for c in tj["object"]["children"]
                          if c["name"] == "strip")
        assert strip_node["position"][2] == pytest.approx(0.0)  # 带面+2 层零偏移
        sol4 = next(s for s in r["view"]["solids"]
                    if s["name"].startswith("layer4_"))
        expected4 = ((sol4["box_mm"][2] + sol4["box_mm"][5]) / 2.0
                     + sol4["offset_mm"])
        layer4 = next(c for c in tj["object"]["children"]
                      if c["name"].startswith("layer4_"))
        assert layer4["position"][2] == pytest.approx(expected4)

    def test_kicad_trace_planes_rotation_mapping(self, tmp_path):
        """走线=定向 PlaneGeometry（宽=段长+w 方帽、高=w、绕 z 转段方位角）
        +节点 z 携带爆炸偏移。"""
        import math

        r = _render(_kicad_content(), tmp_path, explode_factor=2.0)
        tj = json.loads(
            Path(r["outputs"]["json"]["path"]).read_text(encoding="utf-8"))
        nodes = {c["name"]: c for c in tj["object"]["children"]}
        geoms = {g["uuid"]: g for g in tj["geometries"]}
        t0 = nodes["trace_0000"]
        assert t0["rotation"] == pytest.approx([0.0, 0.0, 0.0])  # 沿 +x
        # trace z=F.Cu 顶面 1.58 + F.Cu 层偏移（index2: (2−1)·1.51·2.0=3.02）
        assert t0["position"][2] == pytest.approx(1.58 + 3.02)
        t1 = nodes["trace_0001"]  # 竖段 (15,−10)→(15,−15)：方位角 −π/2
        assert t1["rotation"][2] == pytest.approx(-math.pi / 2)
        g1 = geoms[t1["geometry"]]
        assert g1["type"] == "PlaneGeometry"
        assert g1["width"] == pytest.approx(5.0 + 0.2)
        assert g1["height"] == pytest.approx(0.2)

    def test_formats_subset_and_validation(self, tmp_path):
        """formats 子集：只写所选形态+lint 报告恒附；未知/空 formats 显式错。"""
        r = _render({"source": "layered_stack"}, tmp_path, formats=("json",))
        assert set(r["outputs"]) == {"json", "lint_json"}
        assert not (tmp_path / "layered_stack.svg").exists()
        assert not (tmp_path / "layered_stack.png").exists()
        r_all = _render({"source": "layered_stack"}, tmp_path, formats="all")
        assert set(r_all["outputs"]) == {"svg", "json", "png", "lint_json"}
        bad = _render({"source": "layered_stack"}, tmp_path / "x",
                      formats=("mp4",))
        assert bad["ok"] is False and any("format" in e for e in bad["errors"])
        empty = _render({"source": "layered_stack"}, tmp_path / "y", formats=())
        assert empty["ok"] is False

    def test_u_fffd_zero_in_all_outputs(self, tmp_path):
        """产物卫生：全部文本产物 UTF-8 解码且零 U+FFFD（#259 家法）。"""
        r = _render({"source": "layered_stack"}, tmp_path)
        for key in ("svg", "json", "lint_json"):
            text = Path(r["outputs"][key]["path"]).read_text(encoding="utf-8")
            assert "\ufffd" not in text, key

    def test_painter_order_far_to_near_derivation(self):
        """画家序推导钉（#212 目检抓出的方向 bug 回归钉）：相机∝(1,1,2sinα)
        与屏幕两轴正交、可见面法向与相机同侧、多边形按 x+y+2sinα·z 升序。"""
        import math

        sin_a = math.sin(math.radians(evs.PROJ_ALPHA_DEG))
        cos_a = math.cos(math.radians(evs.PROJ_ALPHA_DEG))
        cam = (1.0, 1.0, 2.0 * sin_a)
        r_axis = (cos_a, -cos_a, 0.0)          # px 系数
        s_axis = (sin_a, sin_a, -1.0)          # py 系数
        dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
        assert dot(r_axis, cam) == pytest.approx(0.0, abs=1e-12)
        assert dot(s_axis, cam) == pytest.approx(0.0, abs=1e-12)
        for normal in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):  # x1/y1/z1 可见面
            assert dot(normal, cam) > 0.0
        scene = build_scene(_kicad_content())
        polys = evs._scene_polygons(scene)
        depths = [sum(p[0] + p[1] + 2.0 * sin_a * p[2] for p in poly["pts3"]) / 4.0
                  for poly in polys]
        assert depths == sorted(depths)  # 升序=远先画
        # 最底层 B.Cu（l0，最远）先于最顶层 F.Cu（l2）出现
        first = {g: next(i for i, p in enumerate(polys) if p["group"] == g)
                 for g in ("l0", "l2")}
        assert first["l0"] < first["l2"]

    def test_kicad_copper_envelope_transparent(self):
        """KiCad 铜层=半透明 dashed 包络（真实铜=走线不透明；#212 目检实证）。"""
        scene = build_scene(_kicad_content())
        polys = evs._scene_polygons(scene)
        cu = [p for p in polys if p["group"] in ("l0", "l2") and p["dashed"]]
        assert cu and all(p["opacity"] == evs.ENVELOPE_OPACITY for p in cu)
        diel = [p for p in polys if p["group"] == "l1"]
        assert diel and all(p["opacity"] == evs.SOLID_OPACITY for p in diel)
        traces = [p for p in polys if p["group"] == "l2" and not p["dashed"]]
        assert traces and all(p["opacity"] == evs.SHEET_OPACITY for p in traces)


# ─── 6) 源分发与 STEP/GLB 预留 ──────────────────────────────────────────


class TestSourceDispatchAndStubs:
    def test_unknown_or_missing_source_rejected(self, tmp_path):
        """source 缺失/未知→显式错误并列出可用源（不静默猜）。"""
        for content in ({}, {"source": "gds"}, {"source": None}):
            r = _render(content, tmp_path)
            assert r["ok"] is False, content
            assert any("layered_stack" in e and "kicad" in e
                       for e in r["errors"]), content

    def test_non_dict_spec_rejected(self):
        r = render_exploded_view(["not", "a", "dict"], out_dir=None)  # type: ignore[arg-type]
        assert r["ok"] is False and any("JSON 对象" in e for e in r["errors"])

    def test_export_step_glb_stubs_declared(self, tmp_path):
        """STEP/GLB=接口预留（NotImplementedError+docstring 边界声明在位）。"""
        scene = build_scene({"source": "layered_stack"})
        with pytest.raises(NotImplementedError):
            export_step(scene, tmp_path / "out.step")
        with pytest.raises(NotImplementedError):
            export_glb(scene, tmp_path / "out.glb")
        assert "v0 接口预留" in (export_step.__doc__ or "")
        assert "glTF 2.0" in (export_glb.__doc__ or "")
        assert "B-rep" in (export_step.__doc__ or "")


# ─── 7) CLI 叶（薄壳+--json 双路径+exit 2 usage 信封）───────────────────


class TestCliLeaf:
    def test_leaf_registered_with_render_only(self):
        """exploded-view 域恰 render 一叶+help 面板映射在位（#df6① 零撞名）。"""
        from typer.main import get_command

        cmd = get_command(cli_app)
        assert "exploded-view" in cmd.commands
        assert set(cmd.commands["exploded-view"].commands) == {"render"}
        assert top_level_panel_names().get("exploded-view") == "综合与设计"

    def test_cli_render_json_success(self, tmp_path):
        """--json 成功路径：exit 0+信封 ok=True+四产物键。"""
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps({"source": "layered_stack"}),
                             encoding="utf-8")
        r = runner.invoke(cli_app, ["exploded-view", "render", str(spec_file),
                                    "--json"])
        assert r.exit_code == 0, r.output
        envelope = json.loads(r.output)
        assert envelope["ok"] is True
        assert envelope["lint_pass"] is True
        assert set(envelope["outputs"]) == {"svg", "json", "png", "lint_json"}
        assert Path(envelope["outputs"]["svg"]["path"]).exists()

    def test_cli_render_format_svg(self, tmp_path):
        """--format svg=只写 SVG（+lint 报告恒附）。"""
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps({"source": "layered_stack"}),
                             encoding="utf-8")
        r = runner.invoke(cli_app, ["exploded-view", "render", str(spec_file),
                                    "--format", "svg", "--json"])
        assert r.exit_code == 0, r.output
        envelope = json.loads(r.output)
        assert set(envelope["outputs"]) == {"svg", "lint_json"}

    def test_cli_kicad_end_to_end(self, tmp_path):
        """kicad 源 CLI 端到端（相对 pcb_path 按 spec 同目录解析）。"""
        import shutil

        shutil.copy(_KICAD_FIXTURE, tmp_path / "board.kicad_pcb")
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(
            {"source": "kicad", "pcb_path": "board.kicad_pcb"}),
            encoding="utf-8")
        r = runner.invoke(cli_app, ["exploded-view", "render", str(spec_file),
                                    "--json"])
        assert r.exit_code == 0, r.output
        envelope = json.loads(r.output)
        assert envelope["ok"] is True and envelope["counts"]["n_traces"] == 3

    def test_cli_bad_format_exit2_json_envelope(self, tmp_path):
        """--format 非法=exit 2+JSON 信封（#ge1㉙：usage 错禁裸文本）。"""
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps({"source": "layered_stack"}),
                             encoding="utf-8")
        r = runner.invoke(cli_app, ["exploded-view", "render", str(spec_file),
                                    "--format", "mp4", "--json"])
        assert r.exit_code == 2
        envelope = json.loads(r.output)
        assert envelope["ok"] is False and envelope["errors"]

    def test_cli_bad_factor_exit2(self, tmp_path):
        """--explode-factor=-1（等号形直击守卫）=exit 2+JSON 信封。"""
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps({"source": "layered_stack"}),
                             encoding="utf-8")
        r = runner.invoke(cli_app, ["exploded-view", "render", str(spec_file),
                                    "--explode-factor=-1", "--json"])
        assert r.exit_code == 2
        envelope = json.loads(r.output)
        assert envelope["ok"] is False

    def test_cli_missing_spec_file_exit2(self, tmp_path):
        """spec 文件不存在=exit 2（_load_json_file usage 信封通道）。"""
        r = runner.invoke(cli_app, ["exploded-view", "render",
                                    str(tmp_path / "ghost.json"), "--json"])
        assert r.exit_code == 2
        envelope = json.loads(r.output)
        assert envelope["ok"] is False

    def test_cli_business_failure_exit1(self, tmp_path):
        """业务失败（spec 解析失败）=exit 1（三档契约中档）。"""
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps({"source": "kicad", "pcb_path": "无.kicad_pcb"}),
            encoding="utf-8")
        r = runner.invoke(cli_app, ["exploded-view", "render", str(spec_file),
                                    "--json"])
        assert r.exit_code == 1
        envelope = json.loads(r.output)
        assert envelope["ok"] is False

    def test_cli_count_chain_domain_local(self):
        """域本地计数链：exploded-view 恰 1 叶+和一致性（绝对总数钉归共享面——
        ㉑ 并发加叶计数时序协议：本席不钉 30X 字面，合流批统一重钉）。"""
        check_numbers = _load_check_numbers()
        counts = check_numbers.cli_leaf_counts()
        assert counts.get("exploded-view") == 1
        assert sum(counts.values()) == check_numbers.count_cli()
