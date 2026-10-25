"""net-aware 几何登记薄测试（K6，aurora_k 战役，P13/F11：HFSS 建模侧 net）。

用户实测病灶原值复现钉面（反馈 §6.1，2026-10-23）：

- Ø80 植球压在 CPW 信号引线上（坐标 (−360,10)，球顶把信号经球短到盖板，
  S21≈−99.6 dB）→ check_net_overlaps/check_keepouts 必红；建模侧登记 →
  to_doctor_manifest → K5 run_em_doctor 检查#8/#12 必红（用户验收口径
  "把植球放回 (−360,10)，em doctor 必须报 bump 与 signal net 相交"的
  建模侧形态端到端）。
- pad2 与最外偶指共面接触，railA/railB 短路（S21≈0 dB、串联电阻为负）
  → check_connectivity series 期望 2 分量必红。

全部确定性：零真机零网络（modeler 用 mock 同形态：obj=modeler[name] +
obj.bounding_box=模型单位 6 数）；模块默认登记薄每测 reset 隔离
（pytest-randomly 顺序无关）。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from rfauto.adapters.hfss_builder_utils import (
    SERIES_SIGNAL_COMPONENTS,
    SHUNT_SIGNAL_COMPONENTS,
    Keepout,
    NetRegistry,
    check_connectivity,
    check_keepouts,
    check_net_overlaps,
    filter_keepout_candidates,
    net_add,
    net_begin,
    net_keepout,
    nets_report,
    reset_net_registry,
    to_doctor_manifest,
)
from rfauto.core.errors import ModelBuildError
from rfauto.service.em_doctor_service import load_model_manifest, run_em_doctor

# ── mock pyaedt modeler（鸭子形态：modeler[name].bounding_box=6 数）────────


class _MockCadObject:
    def __init__(self, bbox: list[float]) -> None:
        self.bounding_box = list(bbox)


class _MockModeler:
    """pyaedt ``app.modeler`` 的最小形态（测试零真机）。"""

    def __init__(self) -> None:
        self._objs: dict[str, _MockCadObject] = {}

    def add(self, name: str, bbox: list[float]) -> None:
        self._objs[name] = _MockCadObject(bbox)

    def __getitem__(self, name: str) -> _MockCadObject:
        if name not in self._objs:
            raise KeyError(name)
        return self._objs[name]


@pytest.fixture(autouse=True)
def _fresh_default_registry() -> None:
    """模块级默认登记薄每测重置（无跨测状态泄漏）。"""
    reset_net_registry()


# ── 病灶场景几何（用户原值：Ø80 球 @(−360,10)，um 制）───────────────────────

#: CPW 信号引线（经过 (−360,10)，z 在 FM 金属层 200.2–205.2）。
_FEED_L_BBOX = [-420, -10, 200.2, -300, 30, 205.2]
#: Ø80 植球外接框（80×80 footprint，中心 (−360,10)，球顶 z=300 触盖板）。
_BUMP_17_BBOX = [-400, -30, 200.2, -320, 50, 300.0]
#: 盖板（lid，球顶经它把信号短到地）。
_LID_BBOX = [-800, -700, 300.0, 800, 700, 305.2]


def _disease_registry() -> NetRegistry:
    """Ø80 球压信号线的病模登记薄（用户第一病灶原值形态）。"""
    reg = NetRegistry(units="um")
    reg.net_begin("signal")
    reg.net_add("feed_l", bbox=_FEED_L_BBOX)
    reg.net_begin("ground")
    reg.net_add("bump_17", bbox=_BUMP_17_BBOX, material="SAC305")
    reg.net_add("lid", bbox=_LID_BBOX)
    return reg


# ── 登记：net_begin/net_add/net_keepout/nets_report ─────────────────────────


class TestNetRegistration:
    def test_net_begin_sets_active_net(self) -> None:
        reg = NetRegistry()
        reg.net_begin("ground")
        rec = reg.net_add("Lid", bbox=[0, 0, 0, 10, 10, 1])
        assert rec.net == "ground"

    def test_net_begin_invalid_net_rejected(self) -> None:
        reg = NetRegistry()
        with pytest.raises(ModelBuildError, match=r"signal.*ground.*other"):
            reg.net_begin("power")

    def test_net_add_without_any_net_rejected(self) -> None:
        reg = NetRegistry()
        with pytest.raises(ModelBuildError, match="无活动 net"):
            reg.net_add("FeedLine", bbox=[0, 0, 0, 1, 1, 1])

    def test_net_add_explicit_net_overrides_active(self) -> None:
        reg = NetRegistry()
        reg.net_begin("ground")
        rec = reg.net_add("TraceInput", net="signal", bbox=[0, 0, 0, 1, 1, 1])
        assert rec.net == "signal"

    def test_net_add_invalid_kind_rejected(self) -> None:
        reg = NetRegistry()
        with pytest.raises(ModelBuildError, match=r"metal.*dielectric"):
            reg.net_add("Weird", net="other", bbox=[0, 0, 0, 1, 1, 1],
                        kind="vacuum")

    def test_net_add_rejects_auto_generated_name(self) -> None:
        reg = NetRegistry()
        with pytest.raises(ModelBuildError, match="命名规范"):
            reg.net_add("Box1", net="signal", bbox=[0, 0, 0, 1, 1, 1])

    def test_net_add_duplicate_name_rejected(self) -> None:
        reg = NetRegistry()
        reg.net_begin("signal")
        reg.net_add("FeedLine", bbox=[0, 0, 0, 1, 1, 1])
        with pytest.raises(ModelBuildError, match="同名对象已登记"):
            reg.net_add("FeedLine", bbox=[0, 0, 0, 1, 1, 1])

    def test_invalid_units_rejected(self) -> None:
        with pytest.raises(ModelBuildError, match=r"um.*mm.*m"):
            NetRegistry(units="mil")

    def test_net_add_fetches_bbox_from_modeler(self) -> None:
        modeler = _MockModeler()
        modeler.add("PatchMain", [0.0, 0.0, 0.0, 30.0, 24.0, 1.6])
        reg = NetRegistry(modeler, units="mm")
        reg.net_begin("signal")
        rec = reg.net_add("PatchMain")
        assert rec.box == ((0.0, 0.0, 0.0), (30.0, 24.0, 1.6))

    def test_net_add_modeler_lookup_failure_is_model_build_error(self) -> None:
        reg = NetRegistry(_MockModeler(), units="mm")
        reg.net_begin("signal")
        with pytest.raises(ModelBuildError, match="bounding_box 失败"):
            reg.net_add("Ghost")

    def test_net_add_without_modeler_or_bbox_rejected(self) -> None:
        reg = NetRegistry()
        reg.net_begin("signal")
        with pytest.raises(ModelBuildError, match="未给 bbox"):
            reg.net_add("FeedLine")

    def test_bbox_normalized_axis_swapped(self) -> None:
        reg = NetRegistry(units="um")
        rec = reg.net_add("Odd", net="other", bbox=[10, 10, 10, -10, -10, -10])
        assert rec.box == ((-10.0, -10.0, -10.0), (10.0, 10.0, 10.0))


class TestNetsReport:
    def test_report_shape_and_bbox_union(self) -> None:
        reg = _disease_registry()
        report = reg.nets_report()
        assert report["units"] == "um"
        assert report["n_objects"] == 3
        # signal net：对象清单 + bbox 并集
        assert report["nets"]["signal"]["objects"] == ["feed_l"]
        assert report["nets"]["signal"]["bbox_union"] == _FEED_L_BBOX
        # ground net：bump_17 ∪ lid 的外接并集
        assert report["nets"]["ground"]["objects"] == ["bump_17", "lid"]
        assert report["nets"]["ground"]["bbox_union"] == [
            -800, -700, 200.2, 800, 700, 305.2]
        # 逐对象记录（bbox 6 数展开 + 可选字段）
        by_name = {o["name"]: o for o in report["objects"]}
        assert by_name["bump_17"]["net"] == "ground"
        assert by_name["bump_17"]["material"] == "SAC305"
        assert by_name["bump_17"]["bbox"] == _BUMP_17_BBOX
        assert "material" not in by_name["feed_l"]

    def test_report_keepouts_doctor_shape(self) -> None:
        reg = NetRegistry(units="um")
        reg.net_keepout("feed_l_slot", [-70, -720, 30, -60],
                        clearance=30, applies_to=("bump_17",))
        assert reg.nets_report()["keepouts"] == [
            {"name": "feed_l_slot", "rect": [-70, -720, 30, -60],
             "clearance": 30, "applies_to": ["bump_17"]}]


# ── 检查一：异 net 交叠（表#8 语义）─────────────────────────────────────────


class TestCheckNetOverlaps:
    def test_bump_on_signal_line_reported(self) -> None:
        """用户验收场景：Ø80 球 @(−360,10) 压 CPW 信号线 → violation 必报。"""
        result = _disease_registry().check_net_overlaps()
        assert result["ok"] is False
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert set(v["objects"]) == {"bump_17", "feed_l"}
        assert set(v["nets"]) == {"ground", "signal"}
        assert v["overlap_volume"] == pytest.approx(80 * 40 * 5.0)

    def test_same_net_overlap_not_flagged(self) -> None:
        reg = NetRegistry(units="um")
        reg.net_begin("ground")
        reg.net_add("gnd_a", bbox=[0, 0, 0, 100, 100, 5])
        reg.net_add("gnd_b", bbox=[50, 50, 0, 150, 150, 5])
        assert reg.check_net_overlaps()["ok"] is True

    def test_face_touch_is_warning_not_violation(self) -> None:
        reg = NetRegistry(units="um")
        reg.net_add("sig", net="signal", bbox=[0, 0, 0, 100, 100, 5])
        reg.net_add("gnd", net="ground", bbox=[100, 0, 0, 200, 100, 5])
        result = reg.check_net_overlaps()
        assert result["ok"] is True
        assert len(result["warnings"]) == 1
        assert set(result["warnings"][0]["objects"]) == {"sig", "gnd"}

    def test_dielectric_overlap_not_flagged(self) -> None:
        reg = NetRegistry(units="um")
        reg.net_add("sig", net="signal", bbox=[0, 0, 0, 100, 100, 5])
        reg.net_add("sub", net="other", kind="dielectric",
                    bbox=[0, 0, 0, 100, 100, 5])
        assert reg.check_net_overlaps()["ok"] is True


# ── 检查二：keepout 侵入/净距（表#12 语义）──────────────────────────────────


class TestCheckKeepouts:
    def _disease_with_keepout(self) -> NetRegistry:
        reg = _disease_registry()
        # keepout=信号引线外扩 10（"植球外接框 ∩ 信号引线矩形"的引线侧）
        reg.net_keepout("feed_l_slot", [-430, -20, -290, 40],
                        applies_to=("bump_17",), clearance=30)
        return reg

    def test_bump_intrusion_reported(self) -> None:
        result = self._disease_with_keepout().check_keepouts()
        assert result["ok"] is False
        assert len(result["violations"]) == 1
        v = result["violations"][0]
        assert v["object"] == "bump_17"
        assert v["keepout"] == "feed_l_slot"
        assert v["overlap"][0] == pytest.approx(80.0)
        assert v["overlap"][1] == pytest.approx(60.0)  # 球 y[-30,50]∩ko y[-20,40]

    def test_clearance_warning_when_close_but_not_intruding(self) -> None:
        reg = NetRegistry(units="um")
        reg.net_add("pad", net="signal", bbox=[0, 0, 0, 80, 80, 5])
        # keepout 距 pad 净距 20（轴向对齐）< 声明清距 30 → warning（不翻红）
        reg.net_keepout("ko", [100, 0, 200, 80], clearance=30)
        result = reg.check_keepouts()
        assert result["ok"] is True
        assert len(result["warnings"]) == 1
        assert result["warnings"][0]["distance"] == pytest.approx(20.0)

    def test_z_range_scoping_skips_other_layers(self) -> None:
        reg = _disease_registry()
        # keepout 只限 z 400–500 层（球/线都在 200–305）→ 侵入不成立
        reg.net_keepout("high_layer_only", [-430, -20, -290, 40],
                        z_range=[400, 500])
        assert reg.check_keepouts()["ok"] is True

    def test_applies_to_unknown_ref_warned(self) -> None:
        reg = _disease_registry()
        reg.net_keepout("ko", [-430, -20, -290, 40], applies_to=("ghost",))
        result = reg.check_keepouts()
        assert result["ok"] is True  # 多报不放过：清单对不上是 warning
        assert any("ghost" in w["detail"] for w in result["warnings"])

    def test_no_keepouts_trivially_ok(self) -> None:
        assert _disease_registry().check_keepouts()["ok"] is True


# ── 检查三：连通分量（表#7 语义：series 2 / shunt 1）────────────────────────


def _idc_rails(reg: NetRegistry, *, bridged: bool) -> None:
    """IDC 家族信号网：railA/railB 两分量；bridged=True 时 pad2 把两轨短接。"""
    reg.net_begin("signal")
    reg.net_add("railA", bbox=[-500, -60, 200.2, -100, -20, 205.2])
    reg.net_add("railB", bbox=[100, -60, 200.2, 500, -20, 205.2])
    if bridged:
        # pad2 与两轨共面接触（用户第二病灶：S21≈0 dB、串联电阻为负）
        reg.net_add("pad2", bbox=[-110, -60, 200.2, 110, -20, 205.2])
    reg.net_begin("ground")
    reg.net_add("gnd_slab", bbox=[-800, 100, 200.2, 800, 700, 205.2])


class TestCheckConnectivity:
    def test_series_default_two_rails_pass(self) -> None:
        reg = NetRegistry(units="um")
        _idc_rails(reg, bridged=False)
        result = reg.check_connectivity()  # 缺省 topology="series"
        assert SERIES_SIGNAL_COMPONENTS == 2
        assert result["ok"] is True
        assert result["by_net"]["signal"]["components"] == 2

    def test_pad_bridge_collapses_to_one_component_fail(self) -> None:
        reg = NetRegistry(units="um")
        _idc_rails(reg, bridged=True)
        result = reg.check_connectivity()
        assert result["ok"] is False
        v = result["violations"][0]
        assert v["net"] == "signal"
        assert v["components"] == 1 and v["expected"] == 2
        assert "短接" in v["detail"]

    def test_shunt_topology_expects_one(self) -> None:
        assert SHUNT_SIGNAL_COMPONENTS == 1
        reg = NetRegistry(units="um")
        _idc_rails(reg, bridged=False)
        result = reg.check_connectivity(topology="shunt")
        assert result["ok"] is False  # 两轨未连 → shunt 期望 1 分量必红
        assert result["expected"]["signal"] == 1

    def test_expected_dict_override(self) -> None:
        reg = NetRegistry(units="um")
        _idc_rails(reg, bridged=False)
        result = reg.check_connectivity({"signal": 2, "ground": 1})
        assert result["ok"] is True

    def test_ground_split_is_warning_not_violation(self) -> None:
        reg = NetRegistry(units="um")
        reg.net_begin("ground")
        reg.net_add("gnd_l", bbox=[0, 0, 0, 100, 100, 5])
        reg.net_add("gnd_r", bbox=[300, 0, 0, 400, 100, 5])
        result = reg.check_connectivity()
        assert result["ok"] is True  # 地网分裂=WARN（经植球连通属正常形态）
        assert len(result["warnings"]) == 1

    def test_invalid_topology_rejected(self) -> None:
        with pytest.raises(ModelBuildError, match=r"series.*shunt"):
            NetRegistry().check_connectivity(topology="cascade")


# ── 落点前过滤：植球候选的 keepout 剔除（用户手工修复 API 化）──────────────


def _bump_grid() -> list[tuple[str, tuple[float, float, float, float]]]:
    """Ø80 植球候选网格（外接框 80×80），含用户病灶位 (−360,10)。"""
    out = []
    for cx in (-500, -440, -360, -280):
        out.append((f"bump_{cx}", (cx - 40, 10 - 40, cx + 40, 10 + 40)))
    return out


class TestFilterKeepoutCandidates:
    def test_diseased_position_skipped_with_honest_reason(self) -> None:
        keepout = Keepout("feed_l_slot", (-430, -20, -290, 40))
        result = filter_keepout_candidates(_bump_grid(), [keepout])
        assert result["n_kept"] == 1 and result["n_skipped"] == 3
        skipped_names = {s["candidate"] for s in result["skipped"]}
        # Ø80 球外接框 80 宽：病灶位 (−360,10) 与邻位 (−440/−280,10)（外接
        # 框搭上 keepout 边 30）都被剔除——按外接框判，如实不手软
        assert skipped_names == {"bump_-360", "bump_-440", "bump_-280"}
        hit = next(s for s in result["skipped"] if s["candidate"] == "bump_-360")
        assert hit["keepout"] == "feed_l_slot"
        assert hit["overlap"] == [pytest.approx(80.0), pytest.approx(60.0)]
        assert "剔除" in hit["detail"]

    def test_kept_candidates_excludes_skipped(self) -> None:
        result = filter_keepout_candidates(
            _bump_grid(), [Keepout("feed_l_slot", (-430, -20, -290, 40))])
        kept = {k["name"] for k in result["kept"]}
        assert kept == {"bump_-500"}

    def test_bare_rects_accepted(self) -> None:
        result = filter_keepout_candidates(
            [[-400, -30, -320, 50], [0, 0, 10, 10]],  # 候选：病灶框 + 无关框
            [[-430, -20, -290, 40]],                  # keepout：裸矩形
        )
        assert result["n_skipped"] == 1
        assert result["skipped"][0]["candidate"] == "candidate[0]"
        assert result["skipped"][0]["keepout"] == "keepout[0]"

    def test_registry_filter_uses_registered_keepouts(self) -> None:
        reg = _disease_registry()
        reg.net_keepout("feed_l_slot", [-430, -20, -290, 40])
        result = reg.filter_candidates(_bump_grid())
        assert {s["candidate"] for s in result["skipped"]} == {
            "bump_-360", "bump_-440", "bump_-280"}


# ── 转换桥：to_doctor_manifest → K5 run_em_doctor 端到端 ────────────────────


class TestDoctorBridge:
    def test_manifest_fields_align_doctor_schema(self) -> None:
        reg = _disease_registry()
        reg.net_keepout("feed_l_slot", [-430, -20, -290, 40],
                        clearance=30, applies_to=("bump_17",))
        manifest = reg.to_doctor_manifest(device_topology="series")
        assert manifest["units"] == "um"
        assert manifest["device_topology"] == "series"
        by_name = {o["name"]: o for o in manifest["objects"]}
        assert by_name["feed_l"]["net"] == "signal"
        assert by_name["feed_l"]["kind"] == "metal"
        assert by_name["bump_17"]["bbox"] == _BUMP_17_BBOX
        assert manifest["keepouts"][0]["rect"] == [-430, -20, -290, 40]

    def test_diseased_manifest_fails_doctor_checks_8_and_12(self) -> None:
        """用户验收口径端到端：建模侧造植球压线 → manifest → doctor #8/#12 红。"""
        reg = _disease_registry()
        reg.net_keepout("feed_l_slot", [-430, -20, -290, 40],
                        applies_to=("bump_17",))
        report = run_em_doctor(reg.to_doctor_manifest(device_topology="series"))
        assert report["ok"] is False
        rows = {c["table_ref"]: c for c in report["checks"]}
        # #8 异 net 交叠：bump 与 signal net 相交（用户验收原话）
        assert rows[8]["status"] == "FAIL"
        assert "bump_17" in rows[8]["detail"] and "feed_l" in rows[8]["detail"]
        # #12 keepout 侵入
        assert rows[12]["status"] == "FAIL"
        assert "bump_17" in rows[12]["detail"] and "feed_l_slot" in rows[12]["detail"]

    def test_manifest_survives_doctor_loader_json_roundtrip(
            self, tmp_path: Any) -> None:
        """清单 JSON 落盘 → load_model_manifest 零错误（schema 硬对齐）。"""
        reg = _disease_registry()
        p = tmp_path / "model_manifest.json"
        p.write_text(json.dumps(reg.to_doctor_manifest(), ensure_ascii=False),
                     encoding="utf-8")
        loaded = load_model_manifest(p)
        assert loaded["ok"] is True, loaded.get("errors")
        report = run_em_doctor(loaded["manifest"])
        assert report["ok"] is False  # 病模经文件链路仍红

    def test_healthy_builder_session_doctor_pass(self) -> None:
        reg = NetRegistry(units="um")
        _idc_rails(reg, bridged=False)
        report = run_em_doctor(reg.to_doctor_manifest(
            device_topology="series"))
        assert report["ok"] is True
        rows = {c["table_ref"]: c for c in report["checks"]}
        assert rows[7]["status"] == "PASS"   # 信号 2 分量=series 期望
        assert rows[8]["status"] == "PASS"   # 跨 net 零交叠


# ── 模块级默认登记薄 + check_all 聚合 ───────────────────────────────────────


class TestModuleLevelApi:
    def test_default_registry_module_functions(self) -> None:
        net_begin("signal")
        net_add("feed_l", bbox=_FEED_L_BBOX)
        net_begin("ground")
        net_add("bump_17", bbox=_BUMP_17_BBOX)
        net_keepout("feed_l_slot", [-430, -20, -290, 40],
                    applies_to=("bump_17",))
        report = nets_report()
        assert report["n_objects"] == 2 and report["n_keepouts"] == 1
        assert check_net_overlaps()["ok"] is False
        assert check_keepouts()["ok"] is False
        # 模块级连通/转换入口同走默认登记薄（reset 缺省 mm 单位制）
        assert check_connectivity()["ok"] is False  # 信号仅 1 分量 vs series 2
        assert to_doctor_manifest(device_topology="series")["units"] == "mm"

    def test_reset_clears_state(self) -> None:
        net_begin("signal")
        net_add("feed_l", bbox=_FEED_L_BBOX)
        reset_net_registry()
        assert nets_report()["n_objects"] == 0

    def test_check_all_aggregates_three_checks(self) -> None:
        reg = _disease_registry()
        reg.net_keepout("feed_l_slot", [-430, -20, -290, 40],
                        applies_to=("bump_17",))
        combined = reg.check_all()
        assert [c["check"] for c in combined["checks"]] == [
            "net_overlap", "keepout_clearance", "net_connectivity"]
        assert combined["ok"] is False

    def test_check_all_healthy_green(self) -> None:
        reg = NetRegistry(units="um")
        _idc_rails(reg, bridged=False)
        combined = reg.check_all(topology="series")
        assert combined["ok"] is True
