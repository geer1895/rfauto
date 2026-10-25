"""stackup schema + 共形介质规划器 + 薄层守卫测试（K9，aurora_k 战役，F10/F2/P15/P7）。

用户实测病灶原值复现钉面（反馈 §6.4 / §一 P7 / §6.1 P15，八角电感工程
μm 制）：IPD 工艺叠层 GaAs 200 / SiNx 0.2 / 金属 5 / 空气隙 3——共形层
（金属上 h1/场区 h2）手工建引发悬空膜/块重叠/柱穿介质 3 bug；0.2 μm SNV
扫掠截面建成"竖墙"（15 高/0.2 宽）SRF 从 6.3 GHz 崩到 0.95 GHz；recipe
示例 mm/GHz vs 工艺 μm 的单位陷阱。

全部确定性：零真机零网络零引擎（纯数值几何）。
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from rfauto.core.errors import ConfigError, ModelBuildError
from rfauto.core.stackup import (
    RECIPE_UNITS,
    ConformalPlanError,
    StackLayer,
    Stackup,
    StackupError,
    assert_thin_layer,
    normalize_units,
    plan_conformal_dielectric,
    to_mm,
)

# ── 病灶场景几何（§6.4 叠层原值，μm 制）────────────────────────────────────
#
# GaAs 200 / SiNx1 0.2 / FM 5（图形化金属）/ SNV 0.2（共形）/ ABM 5
# （空气隙 3，图形化）/ FP 0.3（共形）——z 叠算期望手算钉死。

STACK_64: dict = {
    "substrate": {"material": "GaAs", "thickness": 200, "er": 12.85, "tanD": 0.006},
    "layers": [
        {"name": "SiNx1", "thickness": 0.2, "material": "SiNx", "er": 7.5},
        {"name": "FM", "thickness": 5.0, "material": "Cu/Au", "patterned": True},
        {"name": "SNV", "thickness": 0.2, "material": "SiNx", "er": 7.5,
         "conformal": True},
        {"name": "ABM", "thickness": 5.0, "material": "Cu/Au", "air_gap": 3.0,
         "patterned": True},
        {"name": "FP", "thickness": 0.3, "material": "SiNx", "er": 7.5,
         "conformal": True},
    ],
}

#: 金属 FM：z 0.2–5.2（顶面 5.2）；SNV 共形层槽位 [5.2, 5.4]。
FM_Z = (0.2, 5.2)


# ────────────────────────────────────────────────────────────────────────────
# 1. units helper（P15：recipe mm/GHz vs IPD μm）
# ────────────────────────────────────────────────────────────────────────────


class TestUnitsHelper:
    def test_to_mm_basic_and_aliases(self):
        assert to_mm(200, "um") == pytest.approx(0.2)
        assert to_mm(1.5, "mm") == pytest.approx(1.5)
        # μ 前缀变体按 um 别名（与 NetRegistry/wave_port_planner 同源口径）
        for alias in ("um", "μm", "µm"):
            assert to_mm(5.0, alias) == pytest.approx(5e-3)
        # IPD 工艺全组（P15 原值：衬底 200/金属 5/SiNx 0.2/指隙 8）
        assert to_mm(200, "um") == pytest.approx(0.2)
        assert to_mm(5, "um") == pytest.approx(0.005)
        assert to_mm(0.2, "um") == pytest.approx(2e-4)
        assert to_mm(8, "um") == pytest.approx(0.008)

    def test_normalize_units(self):
        assert normalize_units("mm") == "mm"
        assert normalize_units(" um ") == "um"
        assert RECIPE_UNITS == ("mm", "um")

    @pytest.mark.parametrize("bad", ["cm", "mil", "", "MM", 1, None, True])
    def test_unknown_units_rejected(self, bad):
        with pytest.raises(ConfigError):
            normalize_units(bad)
        with pytest.raises(ConfigError):
            to_mm(1.0, bad)

    def test_nonfinite_value_rejected(self):
        with pytest.raises(ConfigError):
            to_mm(float("nan"), "um")
        with pytest.raises(ConfigError):
            to_mm(float("inf"), "mm")
        with pytest.raises(ConfigError):
            to_mm("5.0", "mm")  # 字符串数值拒绝（YAML 裸数字约定）


# ────────────────────────────────────────────────────────────────────────────
# 2. stackup schema（F10：z 叠算/共形占位/空气隙/装载/校验）
# ────────────────────────────────────────────────────────────────────────────


class TestStackupSchema:
    def test_z_ranges_6_4_example_hand_computed(self):
        """§6.4 叠层原值 z 叠算手算钉：衬底 [-200,0]，层 0 起上叠。"""
        su = Stackup.from_dict(STACK_64)
        zr = su.z_ranges()
        got_names = [(r.name, r.is_air_gap) for r in zr]
        assert got_names == [
            ("substrate", False),
            ("SiNx1", False),
            ("FM", False),
            ("SNV", False),            # 共形槽位=金属面起（占位口径）
            ("ABM__airgap", True),     # 空气隙独立记录
            ("ABM", False),
            ("FP", False),
        ]
        z_expect = [(-200.0, 0.0), (0.0, 0.2), (0.2, 5.2), (5.2, 5.4),
                    (5.4, 8.4), (8.4, 13.4), (13.4, 13.7)]
        for r, (z0, z1) in zip(zr, z_expect, strict=True):
            assert r.z_lo == pytest.approx(z0)
            assert r.z_hi == pytest.approx(z1)
        assert su.total_thickness_um() == pytest.approx(13.7)

    def test_z_ranges_contiguous(self):
        """z 账目连续：每条 z_lo == 前条 z_hi（浮点精确）。"""
        zr = Stackup.from_dict(STACK_64).z_ranges()
        for prev, cur in itertools.pairwise(zr):
            assert cur.z_lo == prev.z_hi

    def test_conformal_occupancy_declaration(self):
        """共形层占位口径：槽位 [z, z+t] 从金属面起（SNV [5.2,5.4]）。

        场区介质坐在金属底面起的低 z 带（FM 底 0.2 → field [0.2,0.4]）——
        那是规划器职责（TestConformalPlanner 钉），schema 只声明占位+携带
        conformal/patterned 旗标供下游消费。
        """
        zr = Stackup.from_dict(STACK_64).z_ranges()
        snv = next(r for r in zr if r.name == "SNV")
        fm = next(r for r in zr if r.name == "FM")
        assert snv.conformal is True and fm.patterned is True
        assert (snv.z_lo, snv.z_hi) == (fm.z_hi, fm.z_hi + 0.2)

    def test_nearest_metal_below(self):
        su = Stackup.from_dict(STACK_64)
        # SNV 下方最近图形化层=FM（金属厚 5 → 规划器 metal_thickness）
        fm = su.nearest_metal_below("SNV")
        assert fm is not None and fm.name == "FM" and fm.thickness_um == 5.0
        # FP 下方跨过 ABM 找到 ABM 自身（patterned）——ABM 就是金属
        abm = su.nearest_metal_below("FP")
        assert abm is not None and abm.name == "ABM"
        # SiNx1 下方无金属（衬底上方第一层）→ None
        assert su.nearest_metal_below("SiNx1") is None
        # 衬底 → None；未知名 → StackupError（不是裸 ValueError）
        assert su.nearest_metal_below("substrate") is None
        with pytest.raises(StackupError):
            su.nearest_metal_below("__nope__")

    def test_layer_by_name(self):
        su = Stackup.from_dict(STACK_64)
        assert su.layer_by_name("ABM").air_gap_um == 3.0
        assert su.layer_by_name("substrate").er == 12.85
        with pytest.raises(StackupError):
            su.layer_by_name("__nope__")

    def test_layer_z_range_as_dict(self):
        zr = Stackup.from_dict(STACK_64).z_ranges()
        gap = next(r for r in zr if r.is_air_gap)
        assert gap.as_dict() == {"name": "ABM__airgap", "z": [5.4, 8.4],
                                 "material": "air", "is_air_gap": True}
        snv = next(r for r in zr if r.name == "SNV")
        assert snv.as_dict()["conformal"] is True

    def test_from_yaml_and_stack_fragment_unwrap(self, tmp_path: Path):
        p = tmp_path / "stack.yaml"
        p.write_text(yaml.safe_dump(STACK_64), encoding="utf-8")
        assert Stackup.from_yaml(p).total_thickness_um() == pytest.approx(13.7)
        # recipe 片段形态 {"stack": {...}}（§6.4 recipe 内嵌）
        frag = tmp_path / "recipe_frag.yaml"
        frag.write_text(yaml.safe_dump({"units": "um", "stack": STACK_64}),
                        encoding="utf-8")
        assert Stackup.from_yaml(frag).z_ranges()[1].z_hi == pytest.approx(0.2)

    def test_from_yaml_error_faces(self, tmp_path: Path):
        with pytest.raises(StackupError):  # 文件不存在
            Stackup.from_yaml(tmp_path / "nope.yaml")
        bad = tmp_path / "bad.yaml"
        bad.write_text("substrate: [unclosed", encoding="utf-8")
        with pytest.raises(StackupError):  # YAML 解析失败
            Stackup.from_yaml(bad)
        nondict = tmp_path / "nondict.yaml"
        nondict.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(StackupError):
            Stackup.from_yaml(nondict)

    def test_empty_layers_allowed(self, tmp_path: Path):
        """裸衬底（减薄 DOE 起点）合法。"""
        p = tmp_path / "bare.yaml"
        p.write_text(yaml.safe_dump(
            {"substrate": {"material": "GaAs", "thickness": 150, "er": 12.85}}),
            encoding="utf-8")
        su = Stackup.from_yaml(p)
        assert su.layers == ()
        assert su.z_ranges()[-1].z_hi == 0.0

    # ── 校验错误面 ────────────────────────────────────────────────────────
    def test_validation_duplicate_names(self):
        with pytest.raises(StackupError, match="重复"):
            Stackup.from_dict({**STACK_64, "layers": [
                {"name": "FM", "thickness": 1, "material": "Cu"},
                {"name": "FM", "thickness": 2, "material": "Au"}]})
        with pytest.raises(StackupError, match="衬底重名"):
            Stackup(substrate=StackLayer("substrate", 200.0, "GaAs", er=12.85),
                    layers=(StackLayer("substrate", 1.0, "SiNx", er=7.5),))

    def test_validation_thickness_and_er(self):
        with pytest.raises(StackupError, match="thickness_um"):
            StackLayer("L", 0.0, "SiNx", er=7.5)
        with pytest.raises(StackupError, match="thickness_um"):
            StackLayer("L", -0.2, "SiNx", er=7.5)
        with pytest.raises(StackupError, match="er"):
            StackLayer("L", 0.2, "SiNx", er=0.0)
        with pytest.raises(StackupError, match="er"):
            StackLayer("L", 0.2, "SiNx", er=-1.0)
        with pytest.raises(StackupError, match="tand"):
            StackLayer("L", 0.2, "SiNx", er=7.5, tand=-0.01)
        with pytest.raises(StackupError, match="air_gap"):
            StackLayer("L", 5.0, "Cu/Au", air_gap_um=-1.0)
        # 导体层 er 省略合法（FM 形态）
        StackLayer("FM", 5.0, "Cu/Au", patterned=True)

    def test_validation_type_strictness(self):
        # bool 不是数值（#175 教训：宽松强转是坑）
        with pytest.raises(StackupError):
            StackLayer("L", True, "SiNx")
        # conformal/patterned 必须裸布尔（YAML 字符串 "true" 拒绝）
        with pytest.raises(StackupError, match="conformal"):
            StackLayer("L", 0.2, "SiNx", conformal="true")
        with pytest.raises(StackupError, match="material"):
            StackLayer("L", 0.2, "")
        with pytest.raises(StackupError, match="层名"):
            StackLayer("  ", 0.2, "SiNx")

    def test_validation_unknown_key_rejected(self):
        with pytest.raises(StackupError, match="未知键"):
            Stackup.from_dict({**STACK_64, "layers": [
                {"name": "L", "thickness": 1, "material": "SiNx", "er": 7.0,
                 "tickness": 2}]})  # 拼写错误当场暴露
        with pytest.raises(StackupError, match="缺 'substrate'"):
            Stackup.from_dict({"layers": []})
        with pytest.raises(StackupError, match="缺 'thickness'"):
            Stackup.from_dict({"substrate": {"material": "GaAs", "er": 12.85}})
        with pytest.raises(StackupError, match="缺 'material'"):
            Stackup.from_dict({"substrate": {"thickness": 200}})
        with pytest.raises(StackupError, match="别名重复"):
            Stackup.from_dict({"substrate": {"material": "GaAs", "thickness": 200,
                                             "thickness_um": 200, "er": 12.85}})
        with pytest.raises(StackupError, match="不接受 air_gap"):
            Stackup.from_dict({"substrate": {"material": "GaAs", "thickness": 200,
                                             "air_gap": 1.0}})

    def test_canonical_key_aliases_accepted(self):
        ly = StackLayer("L", 0.2, "SiNx", er=7.5, tand=0.006, air_gap_um=3.0)
        su = Stackup.from_dict({
            "substrate": {"material": "GaAs", "thickness": 200, "er": 12.85,
                          "tanD": 0.006},
            "layers": [{"name": "L", "thickness_um": 0.2, "material": "SiNx",
                        "er": 7.5, "tan_d": 0.006, "air_gap_um": 3.0}]})
        assert su.layers[0] == ly
        assert su.substrate.tand == 0.006


# ────────────────────────────────────────────────────────────────────────────
# 3. conformal_dielectric 规划器（F2：金属上 h1/场区 h2/开窗/零重叠自检）
# ────────────────────────────────────────────────────────────────────────────


class TestConformalPlanner:
    def test_single_footprint_over_metal_band(self):
        """单足迹：只有金属正上方段（外包络=足迹本身，无场区）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 100.0, 50.0]], thickness=0.2, metal_thickness=5.0,
            z_top_of_metal=205.2)
        assert p["kind"] == "conformal_dielectric_plan"
        assert p["n_over_metal"] == 1 and p["n_field"] == 0
        seg = p["segments"][0]
        assert seg["kind"] == "over_metal" and seg["name"] == "over_metal_00"
        assert seg["rect"] == [0.0, 0.0, 100.0, 50.0]
        assert seg["z"] == [205.2, pytest.approx(205.4)]
        # 场区带基准=金属底面（205.2-5=200.2，F2 原语义：场区坐在金属底起）
        assert p["z_bands"]["field"][0] == pytest.approx(200.2)
        assert p["self_check"]["ok"] is True

    def test_two_footprints_field_bridge(self):
        """双足迹：间隙桥接块在场区带（金属上 h1/场区 h2 的分层）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 40.0, 20.0], [60.0, 0.0, 100.0, 20.0]],
            thickness=0.2, metal_thickness=5.0, z_top_of_metal=205.2)
        assert p["n_over_metal"] == 2 and p["n_field"] == 1
        field = next(s for s in p["segments"] if s["kind"] == "field")
        assert field["rect"] == [40.0, 0.0, 60.0, 20.0]  # 桥接=间隙矩形
        assert field["z"] == [pytest.approx(200.2), pytest.approx(200.4)]
        for s in p["segments"]:
            if s["kind"] == "over_metal":
                assert s["z"][0] == pytest.approx(205.2)

    def test_window_subtraction(self):
        """开窗=差集：窗口把足迹段劈开、贯穿整个介质带（over+field 都扣）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 40.0, 20.0], [60.0, 0.0, 100.0, 20.0]],
            thickness=0.2, metal_thickness=5.0, z_top_of_metal=205.2,
            windows=[[65.0, 5.0, 85.0, 15.0],   # 部分高：足迹 2 劈成 4 条
                     [45.0, -5.0, 55.0, 25.0]])  # 全高：场区桥劈成左右 2 条
        over_rects = [s["rect"] for s in p["segments"] if s["kind"] == "over_metal"]
        field_rects = [s["rect"] for s in p["segments"] if s["kind"] == "field"]
        # 足迹 2 [60,100] 被窗口 [65,85]×[5,15] 劈成 4 条（左/右/中下/中上条）
        got2 = sorted(r for r in over_rects if r[0] >= 60.0)
        assert got2 == [[60.0, 0.0, 65.0, 20.0], [65.0, 0.0, 85.0, 5.0],
                        [65.0, 15.0, 85.0, 20.0], [85.0, 0.0, 100.0, 20.0]]
        # 足迹 1 无窗口相交，原样保留
        assert [0.0, 0.0, 40.0, 20.0] in over_rects
        # 场区桥 [40,60] 被全高窗口 [45,55] 劈成左右 2 条
        assert sorted(field_rects) == [[40.0, 0.0, 45.0, 20.0],
                                       [55.0, 0.0, 60.0, 20.0]]
        assert p["self_check"]["ok"] is True

    def test_window_fully_consumes_footprint_segment(self):
        """过孔整压足迹：正上方段被窗口整吞（合法形态+warning 告知）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 30.0, 30.0], [60.0, 0.0, 100.0, 20.0]],
            thickness=0.2, metal_thickness=5.0, z_top_of_metal=205.2,
            windows=[[-5.0, -5.0, 35.0, 35.0]])  # 整盖足迹 1
        assert all(s["rect"][0] > 0.0 for s in p["segments"])  # 足迹 1 段全没
        assert any("整吞" in w for w in p["warnings"])
        assert p["self_check"]["ok"] is True

    def test_lateral_growth(self):
        """侧壁包覆近似：足迹外扩 g，场区=外包络⊖外扩足迹（零重叠保住）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 10.0, 10.0], [30.0, 0.0, 40.0, 10.0]],
            thickness=0.5, metal_thickness=5.0, z_top_of_metal=205.2,
            lateral_growth=2.0)
        assert p["lateral_growth"] == 2.0
        assert any("lateral_growth" in w for w in p["warnings"])
        overs = [s["rect"] for s in p["segments"] if s["kind"] == "over_metal"]
        assert overs == [[-2.0, -2.0, 12.0, 12.0], [28.0, -2.0, 42.0, 12.0]]
        # 外包络=[-2,-2,42,12]；场区=外包络⊖两外扩足迹=[12,-2,28,12] 一条
        fields = [s["rect"] for s in p["segments"] if s["kind"] == "field"]
        assert fields == [[12.0, -2.0, 28.0, 12.0]]
        assert p["self_check"]["ok"] is True

    def test_zero_metal_thickness_sheet(self):
        """零厚金属 sheet：场区带与正上方段同 z 基（合法+warning）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 40.0, 20.0], [60.0, 0.0, 100.0, 20.0]],
            thickness=0.2, metal_thickness=0.0, z_top_of_metal=205.2)
        assert p["z_bands"]["field"] == p["z_bands"]["over_metal"]
        assert any("零厚" in w for w in p["warnings"])

    def test_segments_pairwise_disjoint_independently(self):
        """零重叠自检的独立复证：测试端自己两两查（不信规划器自报）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 40.0, 20.0], [45.0, 0.0, 100.0, 20.0],
             [0.0, 30.0, 100.0, 40.0]],
            thickness=0.2, metal_thickness=5.0, z_top_of_metal=205.2,
            windows=[[10.0, 33.0, 20.0, 37.0]], lateral_growth=1.0)
        segs = p["segments"]
        assert len(segs) >= 5
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                dx = min(a["rect"][2], b["rect"][2]) - max(a["rect"][0], b["rect"][0])
                dy = min(a["rect"][3], b["rect"][3]) - max(a["rect"][1], b["rect"][1])
                dz = min(a["z"][1], b["z"][1]) - max(a["z"][0], b["z"][0])
                assert not (dx > 1e-9 and dy > 1e-9 and dz > 1e-9), (a, b)
        # 每段 z 跨度 == thickness（总厚度核算）
        for s in segs:
            assert s["z"][1] - s["z"][0] == pytest.approx(0.2, rel=1e-9)
        # 面积核算：段面积和 == 外包络⊖窗口
        env_area = (p["envelope"][2] - p["envelope"][0]) * \
                   (p["envelope"][3] - p["envelope"][1])
        win_area = 10.0 * 4.0
        got = sum((s["rect"][2] - s["rect"][0]) * (s["rect"][3] - s["rect"][1])
                  for s in segs)
        assert got == pytest.approx(env_area - win_area)

    def test_approximation_declared(self):
        """矩形近似边界如实声明（不做弯月面/lateral_growth 用户给）。"""
        p = plan_conformal_dielectric(
            [[0.0, 0.0, 40.0, 20.0]], thickness=0.2, metal_thickness=5.0,
            z_top_of_metal=205.2)
        assert p["approximation"]["model"] == "rectangular_conformal"
        joined = "".join(p["approximation"]["notes"])
        assert "弯月面" in joined and "lateral_growth" in joined
        assert "unite" in joined  # F2：同材料 unite 一体不报 intersect

    # ── 输入错误面 ────────────────────────────────────────────────────────
    def test_overlapping_footprints_rejected(self):
        with pytest.raises(ConformalPlanError, match="原始足迹已相交"):
            plan_conformal_dielectric(
                [[0.0, 0.0, 50.0, 20.0], [40.0, 0.0, 100.0, 20.0]],
                thickness=0.2, metal_thickness=5.0, z_top_of_metal=205.2)

    def test_growth_causes_overlap_rejected(self):
        """间隙 20 < 2×growth=24：外扩相交 fail-fast（提示减 growth）。"""
        with pytest.raises(ConformalPlanError, match="外扩后相交"):
            plan_conformal_dielectric(
                [[0.0, 0.0, 40.0, 20.0], [60.0, 0.0, 100.0, 20.0]],
                thickness=0.2, metal_thickness=5.0, z_top_of_metal=205.2,
                lateral_growth=12.0)

    @pytest.mark.parametrize("kwargs", [
        {"thickness": 0.0}, {"thickness": -0.2}, {"metal_thickness": -1.0},
        {"lateral_growth": -0.5}, {"thickness": float("nan")},
        {"z_top_of_metal": float("inf")},
    ])
    def test_scalar_argument_guards(self, kwargs):
        base = {"thickness": 0.2, "metal_thickness": 5.0, "z_top_of_metal": 205.2}
        with pytest.raises(ConformalPlanError):
            plan_conformal_dielectric([[0.0, 0.0, 10.0, 10.0]],
                                      **{**base, **kwargs})

    def test_degenerate_rects_rejected(self):
        base = {"thickness": 0.2, "metal_thickness": 5.0, "z_top_of_metal": 205.2}
        with pytest.raises(ConformalPlanError, match="4 数矩形"):
            plan_conformal_dielectric([[0.0, 0.0, 10.0]], **base)
        with pytest.raises(ConformalPlanError, match="退化"):
            plan_conformal_dielectric([[0.0, 0.0, 10.0, 0.0]], **base)  # 零高
        with pytest.raises(ConformalPlanError, match="非有限"):
            plan_conformal_dielectric([[0.0, 0.0, float("nan"), 10.0]], **base)
        with pytest.raises(ConformalPlanError, match="退化"):
            plan_conformal_dielectric(
                [[0.0, 0.0, 10.0, 10.0]], windows=[[5.0, 5.0, 5.0, 8.0]], **base)
        with pytest.raises(ConformalPlanError, match="至少一个"):
            plan_conformal_dielectric([], **base)

    def test_conformal_plan_error_is_value_error(self):
        """K7 同款契约：纯规划层错误继承 ValueError（建模脚本可捕）。"""
        assert issubclass(ConformalPlanError, ValueError)
        e = ConformalPlanError("msg", details={"k": 1})
        assert e.details == {"k": 1}


# ────────────────────────────────────────────────────────────────────────────
# 4. 薄层朝向守卫（P7：0.2 μm 介质 vs 15 μm 线宽截面建反成"竖墙"）
# ────────────────────────────────────────────────────────────────────────────


class TestAssertThinLayer:
    def test_pass_exact_and_within_tol(self):
        r = assert_thin_layer(0.2, 0.2)
        assert r["ok"] is True and r["axis"] == "z"
        assert r["abs_err"] == 0.0
        # 容差内通过（0.201 vs 0.2 → rel 0.5% < 1%）
        assert assert_thin_layer(0.201, 0.2)["ok"] is True
        assert assert_thin_layer(15.0, 15.0, axis="y")["axis"] == "y"

    def test_p7_wall_scenario_rejected(self):
        """P7 病灶原值：0.2 μm SNV 扫掠建成 15 μm 高"竖墙"→ 报错带证据。"""
        with pytest.raises(ModelBuildError) as ei:
            assert_thin_layer(15.0, 0.2)
        msg = str(ei.value)
        assert "15" in msg and "0.2" in msg and "竖墙" in msg
        assert ei.value.details["measured"] == 15.0
        assert ei.value.details["declared"] == 0.2
        assert ei.value.details["axis"] == "z"

    def test_too_thin_also_rejected(self):
        """反向建反（实建比声明薄）同样拦——mm 制数值也验。"""
        with pytest.raises(ModelBuildError):
            assert_thin_layer(0.2, 15.0)
        with pytest.raises(ModelBuildError):
            assert_thin_layer(1.113, 2.7825)  # mm 制薄层

    def test_boundary_and_argument_guards(self):
        # 恰在容差边界（0.1% 增厚在 1% 内通过；1.5% 超容拦）
        assert assert_thin_layer(0.2002, 0.2, rel_tol=0.01)["ok"] is True
        with pytest.raises(ModelBuildError):
            assert_thin_layer(0.203, 0.2, rel_tol=0.01)
        for bad_axis in ("w", "Z", 3):
            with pytest.raises(ModelBuildError):
                assert_thin_layer(0.2, 0.2, axis=bad_axis)
        for kwargs in ({"measured_span": -1.0, "declared_h": 0.2},
                       {"measured_span": float("nan"), "declared_h": 0.2},
                       {"measured_span": 0.2, "declared_h": 0.0},
                       {"measured_span": "0.2", "declared_h": 0.2}):
            with pytest.raises(ModelBuildError):
                assert_thin_layer(**kwargs)
        with pytest.raises(ModelBuildError):
            assert_thin_layer(0.2, 0.2, rel_tol=-0.01)


# ────────────────────────────────────────────────────────────────────────────
# 5. recipe units 字段装载面（P15：缺省 mm=现状零变化）
# ────────────────────────────────────────────────────────────────────────────


class TestRecipeUnitsField:
    @staticmethod
    def _write(tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "recipe.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        return p

    def test_units_um_accepted_with_honest_warning(self, tmp_path: Path):
        """units: um 登记+如实 interim 警告（模板接线归模板族席）。"""
        from rfauto.service.api import validate_recipe

        p = self._write(tmp_path, {"model": "wilkinson_power_divider",
                                   "params": {"w_mm": 1.0}, "setup": {},
                                   "units": "um"})
        r = validate_recipe(p)
        assert r["ok"] is True
        assert not r["errors"]
        assert any("um" in w and "模板" in w for w in r["warnings"])

    def test_units_mm_no_warning(self, tmp_path: Path):
        """units: mm=现状等价（无警告）。"""
        from rfauto.service.api import validate_recipe

        p = self._write(tmp_path, {"model": "wilkinson_power_divider", "params": {},
                                   "setup": {}, "units": "mm"})
        r = validate_recipe(p)
        assert r["ok"] is True
        assert r["warnings"] == []

    def test_units_missing_zero_change(self, tmp_path: Path):
        """无 units 字段：现状零变化（无错误无警告）。"""
        from rfauto.service.api import validate_recipe

        p = self._write(tmp_path, {"model": "wilkinson_power_divider", "params": {},
                                   "setup": {}})
        r = validate_recipe(p)
        assert r["ok"] is True
        assert r["warnings"] == []

    @pytest.mark.parametrize("bad", ["cm", "mil", 5, None, True])
    def test_units_invalid_rejected(self, tmp_path: Path, bad):
        from rfauto.service.api import validate_recipe

        p = self._write(tmp_path, {"model": "wilkinson_power_divider", "params": {},
                                   "setup": {}, "units": bad})
        r = validate_recipe(p)
        assert r["ok"] is False
        assert any("'units'" in e for e in r["errors"])
