"""layered_stack 族批 1 测试（T-Q26d，aurora_q 席位 Q-X4）：schema 严格契约
+ HFSS plan 中间形态 + geometry_lint 六检查零 ERROR 闭环 + T-Q26a 积分线
数值校验消费 + 闭式锚回放。

零网络零真机零仿真（秒级）：本文件不 exec openEMS 脚本（CSXCAD 实测在
test_layered_stack_audit.py），HFSS 侧以 plan 声明式中间形态结构断言为准
（批 1 零真机口径）。

出处：D:/晶圆键合/rfauto_反馈与实测经验.md §3.4 P1 模板族提案 + §2.1
实测锚 + §2.2/§2.3 建模约定 + §4 质检门表。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pydantic import ValidationError

from rfauto.adapters.hfss_adapter import _enforce_geometry_lint_report
from rfauto.adapters.hfss_builder_layered import (
    PLAN_KIND,
    build_layered_stack,
    layered_stack_hfss_plan,
)
from rfauto.adapters.hfss_session import validate_integration_line
from rfauto.adapters.layered_stack_spec import (
    FREQ_RANGE_GHZ_DEFAULT,
    MATERIALS,
    MESH_FLOOR_MM,
    CavitySpec,
    ConductorSpec,
    LayeredStackSpec,
    layered_stack_layout,
    layered_stack_lint_projection,
    stack_z_ranges_mm,
)
from rfauto.core.errors import ModelBuildError
from rfauto.service.geometry_lint_service import (
    lint_geometry,
)

NOMINAL_LAYERS = [("silicon", 0.25), ("gold", 0.003), ("silicon", 0.05),
                  ("gold", 0.003), ("silicon", 0.25)]


def _make_spec(**overrides: object) -> LayeredStackSpec:
    return LayeredStackSpec(**overrides)


def _lint_report(spec: LayeredStackSpec) -> dict:
    return lint_geometry(layered_stack_lint_projection(
        layered_stack_layout(spec)))


# ─── 1) 名义缺省值=反馈实测锚（铁律 7：零拍脑袋）──────────────────────────────


class TestNominalDefaults:
    def test_nominal_defaults_match_feedback_3_4(self):
        """缺省 spec=反馈 §3.4 spec 示例值逐项（layers/cavity/conductor/
        ports/cavity_metalization）。"""
        spec = _make_spec()
        assert spec.layers == NOMINAL_LAYERS
        assert spec.cavity.w_mm == pytest.approx(0.9)
        assert spec.cavity.h_mm == pytest.approx(0.5)
        assert spec.cavity.z0_mm == pytest.approx(-0.25)
        assert spec.cavity.x_center_mm == 0.0
        assert spec.cavity.y_center_mm == 0.0
        assert spec.conductor.layer == 2
        assert spec.conductor.width_mm == pytest.approx(0.52)
        assert spec.conductor.pattern == "strip"
        assert spec.ports.kind == "wave"
        assert spec.ports.plane == "YZ"
        assert spec.ports.size_mm is None   # 自动=腔体截面
        assert spec.cavity_metalization_mm == pytest.approx(0.003)

    def test_nominal_anchors_match_feedback_2_1_and_5(self):
        """§2.1/§5 实测锚：line_len=5.1（空气腔 0.9×0.5×5.1）、
        wafer_width=1.2（W2_Membrane 宽）、频带 85-105GHz（§5 复现
        片段扫频）、silicon εr=11.9（§2.1 闭式调用口径）。"""
        spec = _make_spec()
        assert spec.line_len_mm == pytest.approx(5.1)
        assert spec.wafer_width_mm == pytest.approx(1.2)
        assert FREQ_RANGE_GHZ_DEFAULT == (85.0, 105.0)
        assert MATERIALS["silicon"].er == pytest.approx(11.9)
        assert MATERIALS["silicon"].is_metal is False
        assert MATERIALS["gold"].is_metal is True

    def test_stack_z_ranges_strip_plane_origin(self):
        """z 账单源：z=0=导体层顶面（带面系）；叠层底=−(下方厚度和)，
        顶=+(上方厚度和)——§3.4 示例：膜顶 0、底 −0.303、顶 0.253。"""
        spec = _make_spec()
        zr = stack_z_ranges_mm(spec)
        assert zr[2] == (pytest.approx(-0.05), pytest.approx(0.0))
        assert zr[0][0] == pytest.approx(-0.303)
        assert zr[-1][1] == pytest.approx(0.253)


# ─── 2) schema 严格契约（extra=forbid + 几何 fail-loud）───────────────────────


class TestSpecStrictContract:
    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            _make_spec(unknown_key=1)
        with pytest.raises(ValidationError):
            _make_spec(cavity=CavitySpec(w_mm=0.9, h_mm=0.5, z0_mm=-0.25,
                                         depth_mm=1))

    def test_rejects_bad_layers(self):
        with pytest.raises(ValidationError):
            _make_spec(layers=[("silicon", 0.0)])
        with pytest.raises(ValidationError):
            _make_spec(layers=[("silicon", -0.1)])
        with pytest.raises(ValidationError):
            _make_spec(layers=[("fr4", 0.2)])   # 未知材料（表封闭）

    def test_rejects_conductor_layer_out_of_range(self):
        with pytest.raises(ValidationError, match="越界"):
            _make_spec(conductor=ConductorSpec(layer=5))

    def test_rejects_metal_conductor_layer(self):
        """v1 约束：strip=介质层顶面零厚 PEC 片，金属层作走线层留批 2。"""
        with pytest.raises(ValidationError, match="金属层"):
            _make_spec(conductor=ConductorSpec(layer=1))

    def test_rejects_cavity_outside_stack(self):
        with pytest.raises(ValidationError, match="越出叠层"):
            _make_spec(cavity=CavitySpec(w_mm=0.9, h_mm=0.5, z0_mm=-0.4))

    def test_rejects_cavity_partial_overlap_conductor(self):
        """腔部分挖膜=非本族形态（部分重叠显式拒绝，不静默兜底）。"""
        with pytest.raises(ValidationError, match="部分重叠"):
            _make_spec(cavity=CavitySpec(w_mm=0.9, h_mm=0.03, z0_mm=-0.04))

    def test_rejects_cavity_not_containing_conductor(self):
        """strip 须穿越腔体衔接两端端口（腔不含导体层=断链）显式拒绝。"""
        with pytest.raises(ValidationError, match="未包含导体层"):
            _make_spec(cavity=CavitySpec(w_mm=0.9, h_mm=0.2, z0_mm=0.05))

    def test_rejects_asymmetric_cavity(self):
        """StripLinePort 对称探针口径：腔 z 中心=带面（不对称腔留批 2）。"""
        with pytest.raises(ValidationError, match="对称"):
            _make_spec(cavity=CavitySpec(w_mm=0.9, h_mm=0.4, z0_mm=-0.3))

    def test_rejects_strip_wider_than_cavity(self):
        with pytest.raises(ValidationError, match="悬置"):
            _make_spec(conductor=ConductorSpec(width_mm=1.0))

    def test_rejects_cavity_wider_than_wafer(self):
        with pytest.raises(ValidationError, match="键合环"):
            _make_spec(wafer_width_mm=0.8)

    def test_rejects_nonzero_cavity_x_center(self):
        """v1 腔体贯通全长（端口落腔端截面=模型端面）——无 x 自由度。"""
        with pytest.raises(ValidationError, match="贯通全长"):
            _make_spec(cavity=CavitySpec(w_mm=0.9, h_mm=0.5, z0_mm=-0.25,
                                         x_center_mm=1.0))

    def test_rejects_port_size_mismatch(self):
        """端口截面=腔体截面（§2.1 实测形态；§2.3 断言 3 建模期锁死）。"""
        with pytest.raises(ValidationError, match="腔体截面"):
            _make_spec(ports={"kind": "wave", "plane": "YZ",
                              "size_mm": (0.8, 0.5)})

    def test_rejects_negative_metalization(self):
        with pytest.raises(ValidationError):
            _make_spec(cavity_metalization_mm=-0.001)


# ─── 3) 布局单源（分层围合 + §2.2 真空约定）──────────────────────────────────


class TestLayout:
    def test_layout_cavity_carve_segmentation(self):
        """分层围合：腔足印内非导体层挖除（layer0 保腔底以下段/layer4 保
        腔顶以上段/gold 层足印内无盒）、导体层完整横跨。"""
        lay = layered_stack_layout(_make_spec())
        solids = lay["stack_solids"]
        by_layer: dict[int, list[tuple]] = {}
        for seg in solids:
            by_layer.setdefault(seg["layer"], []).append(seg["box"])
        # 导体层（2）完整横跨：单盒全宽
        (mem,) = by_layer[2]
        assert mem[2] == pytest.approx(-0.6) and mem[3] == pytest.approx(0.6)
        assert mem[4] == pytest.approx(-0.05) and mem[5] == pytest.approx(0.0)
        # layer0：两侧段 + 足印内腔底以下段（−0.303..−0.25）
        l0 = by_layer[0]
        assert any(b[4] == pytest.approx(-0.303) and b[5] == pytest.approx(-0.25)
                   and b[2] == pytest.approx(-0.45) for b in l0)
        # layer1/3 gold：足印内无盒（腔 z 区间完整覆盖层厚→全挖）
        for li in (1, 3):
            for b in by_layer[li]:
                inside = (b[2] > -0.451 and b[3] < 0.451)
                assert not inside, f"layer{li} 足印内未挖除: {b}"
        # layer4：足印内保腔顶以上段（0.25..0.253）
        assert any(b[4] == pytest.approx(0.25) and b[5] == pytest.approx(0.253)
                   for b in by_layer[4])

    def test_layout_vacuum_encloses_all_solids(self):
        """§2.2：真空盒完全包住全部固体（含容差贴边）；真空=普通盒
        （layout 无布尔字段）。"""
        lay = layered_stack_layout(_make_spec())
        vx0, vx1, vy0, vy1, vz0, vz1 = lay["vacuum_box_mm"]
        for seg in lay["stack_solids"]:
            bx0, bx1, by0, by1, bz0, bz1 = seg["box"]
            assert vx0 <= bx0 and bx1 <= vx1
            assert vy0 <= by0 and by1 <= vy1
            assert vz0 <= bz0 and bz1 <= vz1
        sx0, sx1, sy0, sy1, sz0, sz1 = lay["strip"]
        assert vx0 <= sx0 and sx1 <= vx1 and vy0 <= sy0 and sy1 <= vy1
        assert vz0 <= sz0 and sz1 <= vz1

    def test_layout_vacuum_end_faces_coplanar_with_structure(self):
        """真空盒 x 端面=结构端面=±L/2（端口落外边界前提，lint ①）。"""
        lay = layered_stack_layout(_make_spec())
        vx0, vx1 = lay["vacuum_box_mm"][0], lay["vacuum_box_mm"][1]
        assert vx0 == pytest.approx(-2.55) and vx1 == pytest.approx(2.55)
        for seg in lay["stack_solids"]:
            assert seg["box"][0] == pytest.approx(vx0)
            assert seg["box"][1] == pytest.approx(vx1)

    def test_layout_ports_on_end_faces_with_numeric_line(self):
        """双波端口：截面=腔体截面、pos=±L/2、积分线数值坐标（带面→腔顶
        壁，T-Q26a 口径）。"""
        lay = layered_stack_layout(_make_spec())
        assert len(lay["ports"]) == 2
        p1, p2 = lay["ports"]
        assert p1["pos_mm"] == pytest.approx(-2.55)
        assert p2["pos_mm"] == pytest.approx(2.55)
        for pt in (p1, p2):
            assert pt["u_mm"] == (pytest.approx(-0.45), pytest.approx(0.45))
            assert pt["v_mm"] == (pytest.approx(-0.25), pytest.approx(0.25))
            start, stop = pt["integration_line_mm"]
            assert all(isinstance(v, float) for v in start + stop)
            assert start[2] == pytest.approx(0.0)    # 带面（信号导体）
            assert stop[2] == pytest.approx(0.25)    # 腔顶壁（参考导体）
            assert start[0] == pytest.approx(pt["pos_mm"])
            assert start[1] == pytest.approx(0.0)

    def test_layout_feature_lines_floor_and_subcell_drop(self):
        """特征线：#349 地板（≥10µm）；次胞界面剔除（叠层顶 0.253 与腔顶
        壁 0.25 近撞→0.253 不入网）；必需面（带面/膜面/腔壁面）全保留。"""
        lay = layered_stack_layout(_make_spec())
        feat = lay["feature_lines_mm"]

        def has(ax: str, v: float) -> bool:
            return any(abs(x - v) <= 1e-12 for x in feat[ax])

        assert has("z", 0.0)            # 带面
        assert has("z", -0.05)          # 膜底
        assert has("z", 0.25) and has("z", -0.25)   # 腔壁面
        assert not has("z", 0.253)      # 叠层顶与腔顶壁 3µm 近撞→剔除
        assert not has("z", 0.003)      # 键合层顶面次胞剔除
        assert not has("z", -0.053)     # 键合层底面次胞剔除
        for ax, lines in feat.items():
            gaps = [lines[i + 1] - lines[i]
                    for i in range(len(lines) - 1)]
            assert min(gaps) >= MESH_FLOOR_MM - 1e-12, (ax, min(gaps))

    def test_layout_wall_sheets_excluding_port_faces(self):
        """腔壁金属化：四壁零厚片；两端截面口无壁（端口须见腔截面）。"""
        lay = layered_stack_layout(_make_spec())
        names = {w["name"] for w in lay["metal_sheets"]}
        assert {"cavity_wall_top", "cavity_wall_bottom",
                "cavity_wall_side_upper_p", "cavity_wall_side_upper_n",
                "cavity_wall_side_lower_p", "cavity_wall_side_lower_n"} == names
        for w in lay["metal_sheets"]:
            bx = w["box"]
            zero_axis = (abs(bx[0] - bx[1]) < 1e-12
                         or abs(bx[2] - bx[3]) < 1e-12
                         or abs(bx[4] - bx[5]) < 1e-12)
            assert zero_axis, "壁须为零厚片形态"


# ─── 4) geometry_lint 六检查闭环（批 1 验收核心）─────────────────────────────


class TestLintClosure:
    def test_nominal_zero_error_and_expected_warns(self):
        """名义 spec 六检查零 ERROR（lint_pass=True）；恰 2 条 WARN（每端
        口 1 条截面连通性——膜横跨腔截面把空气区分上下两腔=族固有形态，
        §2.1 实测单模传输线正常工作，不豁免不隐瞒）。"""
        rep = _lint_report(_make_spec())
        assert rep["ok"] is True
        assert rep["lint_pass"] is True
        assert rep["counts"]["error"] == 0
        assert rep["counts"]["warn"] == 2
        checks = {it["check"] for it in rep["issues"]}
        assert checks == {"port_cross_section_connectivity"}

    def test_envelope_hook_accepts_nominal_report(self):
        """报告信封可直接喂 build_and_setup 的 geometry_lint_report 钩子
        （T-Q26b 消费面）：零 ERROR 不抛。"""
        rep = _lint_report(_make_spec())
        _enforce_geometry_lint_report(rep)   # 不抛即过

    def test_envelope_hook_blocks_error_report(self):
        """ERROR 级报告在 build 出口/solve 前被 ModelBuildError 拦截
        （T-Q26b 门语义）。"""
        bad = _lint_report(_make_spec())
        bad["issues"].append({"check": "port_on_outer_boundary",
                              "level": "ERROR", "objects": ["Port1"],
                              "message": "synthetic"})
        bad["counts"]["error"] += 1
        bad["lint_pass"] = False
        with pytest.raises(ModelBuildError, match="geometry_lint"):
            _enforce_geometry_lint_report(bad)

    def test_trap_partial_intersection_detected(self):
        """§2.2/§5 情形 2 复现钉：真空盒缩到腔宽级（固体穿出真空盒边界）
        → partial_intersection ERROR。"""
        spec = _make_spec()
        proj = layered_stack_lint_projection(layered_stack_layout(spec))
        for box in proj["boxes"]:
            c = list(box["coords"])
            if box["name"] == "VacuumBox":
                c[1], c[4] = -0.5, 0.5   # 真空 y 缩至腔宽级（晶圆 ±0.6 穿出）
            box["coords"] = tuple(c)
        rep = lint_geometry(proj)
        assert rep["ok"] is True and rep["lint_pass"] is False
        assert any(it["check"] == "partial_intersection"
                   and it["level"] == "ERROR" for it in rep["issues"])

    def test_trap_internal_port_detected(self):
        """§2.3 断言 1 复现钉：端口埋入模型内部 → port_on_outer_boundary
        ERROR。"""
        spec = _make_spec()
        proj = layered_stack_lint_projection(layered_stack_layout(spec))
        for pt in proj["ports"]:
            pt["sheet"]["pos"] = 0.0   # 埋到模型中面
        rep = lint_geometry(proj)
        assert rep["lint_pass"] is False
        assert any(it["check"] == "port_on_outer_boundary" for it in rep["issues"])

    def test_trap_no_solve_inside_detected(self):
        """§2.3 形态 A 复现钉：全部体 solve_inside=False（依赖背景介质）
        → port_adjacent_solve_inside ERROR。"""
        spec = _make_spec()
        proj = layered_stack_lint_projection(layered_stack_layout(spec))
        for box in proj["boxes"]:
            box["solve_inside"] = False
        rep = lint_geometry(proj)
        assert rep["lint_pass"] is False
        assert any(it["check"] == "port_adjacent_solve_inside"
                   for it in rep["issues"])

    def test_trap_bare_number_variable_detected(self):
        """反馈 §4 末条真坑钉：加性位置无量纲裸数（w_s+0.04 被 HFSS 按
        米解释）→ variable_units ERROR（全数值 plan 缺省零暴露）。"""
        spec = _make_spec()
        proj = layered_stack_lint_projection(layered_stack_layout(spec))
        assert proj["variables"] == []
        proj["variables"].append({"name": "w_s", "expression": "w_s+0.04"})
        rep = lint_geometry(proj)
        assert rep["lint_pass"] is False
        assert any(it["check"] == "variable_units" for it in rep["issues"])

    def test_lint_projection_dict_validates_via_service_schema(self):
        """投影 dict 经 service LintGeometry schema 校验（service JSON 进出
        形态；adapters 禁 import service——plain dict 契约）。"""
        rep = _lint_report(_make_spec())
        assert rep["model_units"] == "mm"
        assert rep["summary"]["boxes"] > 0
        assert rep["summary"]["ports"] == 2


# ─── 5) HFSS plan 中间形态（批 1 零真机结构断言面）───────────────────────────


class TestHfssPlan:
    def test_plan_shape_and_object_lint_name_parity(self):
        plan = layered_stack_hfss_plan(_make_spec())
        assert plan["kind"] == PLAN_KIND
        assert plan["model_units"] == "mm"
        names = sorted(o["name"] for o in plan["objects"])
        lint_names = sorted(b["name"] for b in plan["lint"]["boxes"])
        assert names == lint_names, "plan 与 lint 投影盒名须 1:1（可追溯）"
        assert "VacuumBox" in names and "strip" in names
        assert plan["lint"]["model_units"] == "mm"

    def test_plan_vacuum_ordinary_box_no_boolean(self):
        """§2.2 约定书钉：真空=普通盒（material=vacuum、实体形态、完全
        包住）；plan 全量 create_box 形态（无布尔减字段——挖腔=分层围合）。"""
        plan = layered_stack_hfss_plan(_make_spec())
        vac = next(o for o in plan["objects"] if o["name"] == "VacuumBox")
        assert vac["material"] == "vacuum"
        assert vac["solve_inside"] is True
        assert vac["is_sheet"] is False
        assert all(o.get("op") is None for o in plan["objects"])
        assert set(plan.keys()) == {"kind", "model_units", "objects",
                                    "ports", "lint", "notes"}
        assert "部分相交" in plan["notes"]["vacuum_convention"]

    def test_plan_metal_render_dispatch(self):
        """金属形态分派：gold 键合层=实体盒（保厚度，材质 gold）；strip/
        腔壁=零厚 PEC 片（wilkinson GROUND 官方 sheet 形态）。"""
        plan = layered_stack_hfss_plan(_make_spec())
        golds = [o for o in plan["objects"] if o["material"] == "gold"]
        assert len(golds) == 4   # layer1/3 两侧段
        for g in golds:
            assert g["is_sheet"] is False
            (_x0, _x1, _y0, _y1, z0, z1) = g["coords"]
            assert z1 - z0 == pytest.approx(0.003)   # 声明厚度保留
        pecs = [o for o in plan["objects"] if o["material"] == "pec"]
        assert len(pecs) == 7   # strip + 6 壁
        for p in pecs:
            assert p["is_sheet"] is True
            assert p["solve_inside"] is False
        strip = next(o for o in plan["objects"] if o["name"] == "strip")
        assert strip["coords"][4] == pytest.approx(0.0)
        assert strip["coords"][5] == pytest.approx(0.0)
        assert strip["coords"][2] == pytest.approx(-0.26)
        assert strip["coords"][3] == pytest.approx(0.26)

    def test_plan_ports_numeric_integration_line_tq26a(self):
        """T-Q26a 消费：plan 积分线过 validate_integration_line（纯数值）；
        表达式字符串在同一校验器下 ValueError 参数错误（不得落 pyaedt
        边界创建失败）。"""
        plan = layered_stack_hfss_plan(_make_spec())
        assert len(plan["ports"]) == 2
        for pt in plan["ports"]:
            assert pt["sheet"]["orientation"] == "YZ"
            assert pt["modes"] == 1 and pt["impedance"] == 50.0
            assert pt["renormalize"] is True
            validate_integration_line(pt["integration_line"],
                                      param=f"{pt['name']} integration_line")
        with pytest.raises(ValueError, match="must be numeric coordinates"):
            validate_integration_line(
                [[-2.55, 0.0, "-H_cav/2"], [-2.55, 0.0, 0.25]])

    def test_plan_ports_cover_cavity_cross_section(self):
        """端口 sheet=腔体截面矩形（§2.1 实测形态：波端口覆盖整个腔截面）。"""
        plan = layered_stack_hfss_plan(_make_spec())
        for pt in plan["ports"]:
            sh = pt["sheet"]
            assert sh["origin"][1] == pytest.approx(-0.45)
            assert sh["origin"][2] == pytest.approx(-0.25)
            assert sh["origin"][0] == pytest.approx(pt["sheet"]["origin"][0])
            assert sh["sizes"][0] == pytest.approx(0.9)
            assert sh["sizes"][1] == pytest.approx(0.5)

    def test_plan_accepts_dict_spec(self):
        """dict spec 与模型实例同 plan（service JSON 进出形态）。"""
        a = layered_stack_hfss_plan(_make_spec())
        b = layered_stack_hfss_plan(_make_spec().model_dump())
        assert a["objects"] == b["objects"]
        assert a["ports"] == b["ports"]
        assert a["lint"] == b["lint"]


# ─── 6) build 面形态守卫（零真机：mock 会话接口形态断言）─────────────────────


class _FakeModeler:
    """pyaedt modeler 形态最小桩（记录调用；不画真几何）。"""

    def __init__(self) -> None:
        self.boxes: list[dict] = []
        self.rects: list[dict] = []
        self.faces: dict[str, list[int]] = {}

    def create_box(self, origin, sizes, name, material):
        self.boxes.append({"origin": list(origin), "sizes": list(sizes),
                           "name": name, "material": material})
        self.faces[name] = [1000 + len(self.boxes)]
        return name

    def create_rectangle(self, orientation, origin, sizes, name):
        self.rects.append({"orientation": orientation, "origin": list(origin),
                           "sizes": list(sizes), "name": name})
        self.faces[name] = [2000 + len(self.rects)]
        return name

    def get_object_faces(self, name):
        return self.faces[name]


class _FakeApp:
    def __init__(self) -> None:
        self.modeler = _FakeModeler()
        self.ports: list[dict] = []

    def wave_port(self, **kwargs):
        self.ports.append(kwargs)


class TestBuildShapeGuard:
    def test_build_rejects_foreign_plan(self):
        with pytest.raises(ModelBuildError, match="layered_stack_hfss_plan"):
            build_layered_stack(_FakeApp(), {"kind": "other"})

    def test_build_numeric_integration_line_passthrough(self):
        """build 面把数值积分线直传 wave_port（T-Q26a 校验器放行形态）；
        单位串几何（mm 后缀）与零厚 sheet 形态走 create_box。"""
        app = _FakeApp()
        plan = layered_stack_hfss_plan(_make_spec())
        rep = build_layered_stack(app, plan)
        assert len(app.modeler.boxes) == len(plan["objects"])
        assert len(app.ports) == 2
        for called, declared in zip(app.ports, plan["ports"], strict=True):
            assert called["integration_line"] == declared["integration_line"]
            assert called["name"] == declared["name"]
        assert rep["objects"]["VacuumBox"] == "VacuumBox"
        rect = app.modeler.rects[0]
        assert rect["orientation"] == "YZ"
        assert rect["sizes"] == ["0.9mm", "0.5mm"]

    def test_build_rejects_expression_line_before_pyaedt(self):
        """hand-crafted plan 带表达式积分线 → ValueError（T-Q26a 前置校验
        在任何 pyaedt 调用之前——不落边界创建失败）。"""
        app = _FakeApp()
        plan = layered_stack_hfss_plan(_make_spec())
        plan["ports"][0]["integration_line"] = [
            [-2.55, 0.0, "-H_cav/2"], [-2.55, 0.0, 0.25]]
        with pytest.raises(ValueError, match="must be numeric coordinates"):
            build_layered_stack(app, plan)
        assert len(app.ports) == 0   # 未触 wave_port


# ─── 7) 闭式锚回放（确定性内核 ↔ 反馈 §2.1 实测）────────────────────────────


class TestClosedFormAnchor:
    def test_suspended_stripline_ri_reproduces_feedback_anchor(self):
        """_suspended_stripline_ri(0.52, 0.50, 0.05, 11.9) → εeff≈1.59、
        Z0≈50.2（反馈 §2.1 实测口径；HFSS |S11|max=-23.5dB 背书 50Ω 点）
        ——内核回放容差 2%（闭式族 FD 定标误差声明域内）。"""
        from rfauto.core.calculators import _suspended_stripline_ri

        eps_eff, z0 = _suspended_stripline_ri(0.52, 0.50, 0.05, 11.9)
        assert eps_eff == pytest.approx(1.59, rel=0.02)
        assert z0 == pytest.approx(50.2, rel=0.02)


# ─── 8) 馈段四壁延续（Q-X14 Fix1/2，qx12 调查 RC1 修复钉）────────────────────


class TestFeedWallContinuation:
    """Q-X14 Fix1（四壁馈段延续）+ Fix2（渲染端 fail-loud 守卫）钉。

    RC1（qx12 INVESTIGATION §0）：修复前馈段 |x|>±L/2 四壁零金属——
    StripLinePort 探针面 z=±height 地平面命中=0，探针拾取无回流开域场。
    Fix1=消费 ``lay["metal_sheets"]`` (y,z) 字面单源直通重定 x；Fix2=
    延续存在性+探针面金属覆盖双守卫（ValueError fail-loud）。
    本类=数据面/文本面快钉（CSXCAD 实测在 test_layered_stack_audit）。
    """

    def test_feed_continuation_helper_single_source_yz(self):
        """Fix1 单源直通：_feed_wall_continuation_boxes 对每面壁发射恰 2 盒
        （[−DOM_X,−L_HALF] 与 [L_HALF,DOM_X]），(y,z) 与 layout 壁盒字面
        逐位一致（×1e-3 米制；铁律 7——零几何独立计算）。"""
        from rfauto.adapters.oe_templates.render_layered_stack import (
            _feed_wall_continuation_boxes,
        )

        lay = layered_stack_layout(_make_spec())
        l_half = float(lay["l_half_mm"]) * 1e-3
        dom_x = l_half + 16.0 * 0.4e-3   # 审计档 BASE=0.4mm 同款
        boxes = _feed_wall_continuation_boxes(lay["metal_sheets"], l_half,
                                              dom_x)
        assert len(boxes) == 2 * len(lay["metal_sheets"])
        for wall in lay["metal_sheets"]:
            _bx0, _bx1, y0, y1, z0, z1 = (float(v) * 1e-3
                                          for v in wall["box"])
            for x0, x1 in ((-dom_x, -l_half), (l_half, dom_x)):
                hit = [b for b in boxes
                       if b[0] == wall["name"] and b[1] == (x0, x1, y0, y1,
                                                            z0, z1)]
                assert len(hit) == 1, (wall["name"], (x0, x1))

    def test_feed_guard_existence_fail_loud(self):
        """Fix2 守卫①：缺任一面壁的馈段延续盒 → ValueError（"馈段"字样）；
        完整延续盒集放行。"""
        from rfauto.adapters.oe_templates.render_layered_stack import (
            _assert_feed_walls_complete,
            _feed_wall_continuation_boxes,
        )

        lay = layered_stack_layout(_make_spec())
        l_half = float(lay["l_half_mm"]) * 1e-3
        dom_x = l_half + 16.0 * 0.4e-3
        boxes = _feed_wall_continuation_boxes(lay["metal_sheets"], l_half,
                                              dom_x)
        _assert_feed_walls_complete(lay["metal_sheets"], boxes, l_half,
                                    dom_x)   # 不抛即过
        with pytest.raises(ValueError, match="馈段"):
            _assert_feed_walls_complete(lay["metal_sheets"], boxes[:-1],
                                        l_half, dom_x)

    def test_probe_guard_rejects_uncovered_synthetic(self):
        """Fix2 守卫②：探针面地平面金属命中=0 的合成台账 → ValueError
        （"命中=0"字样）；含覆盖盒的台账放行。"""
        from rfauto.adapters.oe_templates.render_layered_stack import (
            _assert_probe_plane_metal_covered,
        )

        sz, h = 0.0, 0.25e-3
        sy0, sy1 = -0.26e-3, 0.26e-3
        probe_x = 2.9767e-3
        # 修复前 RC1 形态：馈段只有 strip（z=0）——地平面命中=0
        strip_only = [(-3.19e-3, -2.55e-3, sy0, sy1, sz, sz)]
        with pytest.raises(ValueError, match="命中=0"):
            _assert_probe_plane_metal_covered(strip_only, [probe_x], sz, h,
                                              sy0, sy1)
        # 修复后形态：顶/底壁延续盒覆盖探针面地平面
        fixed = [*strip_only,
                 (2.55e-3, 3.19e-3, -0.45e-3, 0.45e-3, h, h),
                 (2.55e-3, 3.19e-3, -0.45e-3, 0.45e-3, -h, -h)]
        _assert_probe_plane_metal_covered(fixed, [probe_x], sz, h,
                                          sy0, sy1)   # 不抛即过

    def test_probe_guard_rejects_partial_y_coverage(self):
        """守卫② y 覆盖口径：命中盒 y 范围不含 [STRIP_Y0,STRIP_Y1]（如
        侧壁 y=±0.45 零厚片）不算地平面命中——只有顶/底壁形态可满足。"""
        from rfauto.adapters.oe_templates.render_layered_stack import (
            _assert_probe_plane_metal_covered,
        )

        sz, h = 0.0, 0.25e-3
        sy0, sy1 = -0.26e-3, 0.26e-3
        probe_x = 2.9767e-3
        side_walls_only = [(2.55e-3, 3.19e-3, 0.45e-3, 0.45e-3, h, h),
                           (2.55e-3, 3.19e-3, -0.45e-3, -0.45e-3, -h, -h)]
        with pytest.raises(ValueError, match="命中=0"):
            _assert_probe_plane_metal_covered(side_walls_only, [probe_x],
                                              sz, h, sy0, sy1)

    def test_render_invokes_probe_guard(self, monkeypatch):
        """守卫接线钉：渲染路径真实调用探针面守卫（monkeypatch 投掷即
        传播——守卫被绕过/删除时本钉红）。"""
        import rfauto.adapters.oe_templates.render_layered_stack as rl

        def _boom(*_a: object, **_k: object) -> None:
            raise RuntimeError("probe-guard-not-wired")

        monkeypatch.setattr(rl, "_assert_probe_plane_metal_covered", _boom)
        with pytest.raises(RuntimeError, match="probe-guard-not-wired"):
            rl.render_layered_stack(_make_spec(), mesh_resolution_mm=0.4)

    def test_render_text_feed_continuation_lines(self):
        """渲染文本：每面壁恰 3 条金属线（体段+两馈段延续，延续行带
        Q-X14 Fix1 标记）；延续行总数=2×壁数。"""
        from rfauto.adapters.oe_templates.render_layered_stack import (
            render_layered_stack,
        )

        lay = layered_stack_layout(_make_spec())
        text = render_layered_stack(_make_spec(), mesh_resolution_mm=0.4)
        marker = "馈段延续（匹配馈 Q-X14 Fix1）"
        feed_lines = [ln for ln in text.splitlines() if marker in ln]
        assert len(feed_lines) == 2 * len(lay["metal_sheets"])
        for wall in lay["metal_sheets"]:
            n = sum(1 for ln in text.splitlines()
                    if wall["name"] in ln and "priority=10" in ln)
            assert n == 3, (wall["name"], n)
