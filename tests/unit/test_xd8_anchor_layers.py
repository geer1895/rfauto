"""XD-8 锚点分层声明测试（closure/component/system，2026-10-08 快赢席 W1）。

判据（预声明）：
- live 注册表（knowledge/anchors.yaml）60 锚全量声明 layer，值域
  = core ANCHOR_LAYERS 三值；
- 分类规则钉：来源段 closedform/fdref/lit → closure；阵列/系统族
  （patch_array*/mmwave_series_array）→ system；引擎对仲裁单器件
  物理量 → component（三档均非空，防退化全一档）；
- core 构造期：越界 layer 拒（ValueError）；缺 layer 兼容（None，
  合成 fixture/旧条目零破坏）；
- infra validate 门：live 全过（无 layer issue）；缺 layer 如实报
  issue（institutionalize：新增锚不声明分层即门红）；
- service 摘要行加性透出 layer 键（行面既有键零破坏）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "knowledge" / "anchors.yaml"

# 阵列/系统级模板族（XD-8 分类规则第二支，与注入脚本/头注同口径）
_SYSTEM_FAMILIES = ("patch_array", "mmwave_series_array")


def _live_anchor_set():
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors()


def _classify(anchor_id: str, template_family: list[str]) -> str:
    if any(str(f).startswith(_SYSTEM_FAMILIES) for f in template_family):
        return "system"
    if any(anchor_id.endswith(f".{src}-v1")
           for src in ("closedform", "fdref", "lit")):
        return "closure"
    return "component"


def test_live_registry_all_anchors_have_valid_layer() -> None:
    from rfauto.core.anchors import ANCHOR_LAYERS

    anchor_set = _live_anchor_set()
    assert len(anchor_set.load_errors) == 0
    assert len(anchor_set) == 75  # ANCH-D 批 70→75（SENS-ANC 60→70 沿革，store test 同钉）
    for rec in anchor_set.records:
        assert rec.layer in ANCHOR_LAYERS, (
            f"{rec.anchor_id}: layer={rec.layer!r} 越界/缺失")


def test_layer_classification_rule_and_non_degenerate() -> None:
    from rfauto.core.anchors import ANCHOR_LAYERS

    anchor_set = _live_anchor_set()
    got = {layer: [] for layer in ANCHOR_LAYERS}
    for rec in anchor_set.records:
        expect = _classify(rec.anchor_id, rec.template_family)
        assert rec.layer == expect, (
            f"{rec.anchor_id}: layer={rec.layer!r} != 规则期望 {expect!r}")
        got[expect].append(rec.anchor_id)
    # 三档均非空（分类不退化；ANCH-D 批后口径：closure 57 / component 14 / system 4）
    assert len(got["closure"]) == 57  # ANCH-D 批 +5 全 closure（56→62 有锚族）
    assert len(got["component"]) == 14
    assert len(got["system"]) == 4
    assert set(got["system"]) == {
        "patch_array_1x4.f_res.openems-hfss-v1",
        "patch_array.f_res.openems-hfss-v1",
        "mmwave.design_dk.ro3003-oe-v1",
        "mmwave.design_dk.ro3003-oe-hfss-v2",
    }


def test_from_dict_unknown_layer_rejected() -> None:
    from rfauto.core.anchors import AnchorRecord

    with pytest.raises(ValueError, match="未知分层"):
        AnchorRecord.from_dict({
            "anchor_id": "x.y.z-v1", "kind": "constant", "status": "active",
            "layer": "galaxy", "value": 1.0,
        })


def test_from_dict_absent_layer_backward_compatible() -> None:
    """缺 layer = None（合成 fixture/旧条目零破坏——消费者零破坏钉）。"""
    from rfauto.core.anchors import AnchorRecord

    rec = AnchorRecord.from_dict({
        "anchor_id": "x.y.z-v1", "kind": "constant", "status": "active",
        "value": 1.0,
    })
    assert rec.layer is None


def test_validate_live_registry_clean_of_layer_issues() -> None:
    from rfauto.infra.anchors_store import validate_anchor_set

    report = validate_anchor_set(_live_anchor_set(),
                                 registry_path=_REGISTRY_PATH)
    assert report["ok"], f"issues: {report['issues']}"
    assert report["expected_match"] and report["count"] == 75
    assert not any("layer" in i for i in report["issues"])


def test_validate_missing_layer_reports_issue() -> None:
    """institutionalize 钉：不声明 layer 的锚 validate 如实报 issue。"""
    from rfauto.core.anchors import AnchorSet
    from rfauto.infra.anchors_store import validate_anchor_set

    anchor_set = AnchorSet([{
        "anchor_id": "x.y.z-v1", "kind": "constant", "status": "experimental",
        "value": 1.0, "template_family": ["t"],
    }])
    report = validate_anchor_set(anchor_set, repo_root=_REPO_ROOT)
    assert report["ok"] is False
    assert any("layer 缺失" in i for i in report["issues"])


def test_service_summary_rows_carry_layer_key() -> None:
    """service 摘要行加性透出 layer（行面既有键零破坏）。"""
    from rfauto.service.anchors_service import list_anchors

    listed = list_anchors()
    assert listed["ok"] and listed["count"] == 75
    legacy_keys = ("anchor_id", "kind", "status", "value", "uncertainty")
    for row in listed["anchors"]:
        assert "layer" in row, row.get("anchor_id")
        for k in legacy_keys:  # 既有键仍在（加性，零破坏）
            assert k in row, (row.get("anchor_id"), k)
