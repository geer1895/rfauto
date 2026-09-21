"""B2/B5 版图服务层测试：JSON 进出薄壳（layout_service.py）。确定性离线。"""

from __future__ import annotations

import pytest

from rfauto.adapters.layout_generator import generate_microstrip
from rfauto.adapters.layout_interchange import LayoutPath
from rfauto.service.layout_service import (
    generate_layout_payload,
    import_layout_payload,
    laymap_conflicts,
    layout_from_payload,
    layout_to_payload,
    load_laymap,
    round_trip_delta_payload,
    round_trip_report,
)

MICROSTRIP_PARAMS = {
    "width_mm": 0.25,
    "length_mm": 10.0,
    "via_fence": {"pitch_mm": 2.5, "pad_diameter_mm": 0.6, "drill_diameter_mm": 0.3},
}


def test_payload_roundtrip_preserves_layout():
    layout = generate_microstrip(MICROSTRIP_PARAMS)
    payload = layout_to_payload(layout)
    # JSON 可序列化（不含 tuple）
    rebuilt = layout_from_payload(payload)
    assert rebuilt.name == layout.name
    assert len(rebuilt.items) == len(layout.items)
    assert payload["layers"][0]["name"] == "B.Cu" or any(
        lay["name"] == "F.Cu" for lay in payload["layers"]
    )
    kinds = {node["kind"] for node in payload["items"]}
    assert kinds == {"polygon", "path", "via"}
    delta = round_trip_delta_payload(payload, layout_to_payload(rebuilt), "ipc2581")
    assert delta == 0.0


def test_payload_from_bare_items_infers_layers():
    payload = {
        "name": "bare",
        "items": [
            {"kind": "path", "points": [[0.0, 0.0], [1.0, 0.0]], "width_mm": 0.2, "layer": "F.Cu"}
        ],
    }
    layout = layout_from_payload(payload)
    assert [lay.name for lay in layout.layers] == ["F.Cu"]
    assert isinstance(layout.items[0], LayoutPath)


def test_generate_and_export(tmp_path):
    out = tmp_path / "ms.gds"
    result = generate_layout_payload(
        "microstrip", MICROSTRIP_PARAMS, fmt="gdsii", output_path=str(out)
    )
    assert result["exported_path"] == str(out)
    assert out.exists()
    readback = import_layout_payload(str(out), "gdsii")
    assert len(readback["items"]) == len(result["layout"]["items"])
    assert round_trip_delta_payload(result["layout"], readback, "gdsii") == 0.0


def test_generate_requires_output_path_with_fmt():
    with pytest.raises(ValueError, match="output_path"):
        generate_layout_payload("microstrip", MICROSTRIP_PARAMS, fmt="dxf")


def test_round_trip_report_all_formats(tmp_path):
    result = generate_layout_payload("microstrip", MICROSTRIP_PARAMS)
    report = round_trip_report(result["layout"], str(tmp_path))
    assert report["all_lossless"] is True
    assert set(report["formats"]) == {"gdsii", "dxf", "ipc2581", "odbpp"}
    for fmt, verdict in report["formats"].items():
        assert verdict["delta"] == 0.0, f"{fmt}"
    assert report["formats"]["ipc2581"]["carries_drill"] is True
    assert report["formats"]["gdsii"]["carries_drill"] is False
    assert "microstrip" in report["generators_registered"]


def test_round_trip_report_unknown_format(tmp_path):
    result = generate_layout_payload("microstrip", MICROSTRIP_PARAMS)
    with pytest.raises(ValueError, match="不支持的版图互操作格式"):
        round_trip_report(result["layout"], str(tmp_path), formats=["gerber"])


# ---------------------------------------------------------------------------
# P2⑳ laymap：外部层名映射文件消费（load_laymap + import_layout_payload 接线）
# ---------------------------------------------------------------------------


def test_load_laymap_json(tmp_path):
    path = tmp_path / "laymap.json"
    path.write_text('{"1": "F.Cu", "20": "Edge.Cuts"}', encoding="utf-8")
    assert load_laymap(path) == {"1": "F.Cu", "20": "Edge.Cuts"}


def test_load_laymap_yaml_int_keys_normalized(tmp_path):
    """YAML 整型键坑：YAML 里 ``1:`` 解析成 int 键——统一 str(int(key)) 归一。"""
    yml = tmp_path / "laymap.yaml"
    yml.write_text("1: F.Cu\n20: Edge.Cuts\n", encoding="utf-8")
    assert load_laymap(yml) == {"1": "F.Cu", "20": "Edge.Cuts"}
    yml_short = tmp_path / "laymap.yml"
    yml_short.write_text("2: B.Cu\n", encoding="utf-8")
    assert load_laymap(yml_short) == {"2": "B.Cu"}


def test_load_laymap_non_int_key_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("F.Cu: F.Cu\n", encoding="utf-8")
    with pytest.raises(ValueError, match="层号"):
        load_laymap(path)


def test_load_laymap_unknown_suffix_and_missing_file(tmp_path):
    toml_like = tmp_path / "laymap.toml"
    toml_like.write_text("1 = 'F.Cu'", encoding="utf-8")
    with pytest.raises(ValueError, match="后缀"):
        load_laymap(toml_like)
    with pytest.raises(FileNotFoundError):
        load_laymap(tmp_path / "missing.json")


def test_load_laymap_top_level_must_be_mapping(tmp_path):
    path = tmp_path / "list.json"
    path.write_text('["F.Cu"]', encoding="utf-8")
    with pytest.raises(ValueError, match="映射"):
        load_laymap(path)


def test_import_layout_payload_laymap_path_end_to_end(tmp_path):
    """服务层接线全链：生成→GDS 导出→laymap 消费读回，层名与原版对齐、裁判中性、
    payload 契约不变（键集合一致、无新增键；缺省读回仍为层号串名）。"""
    result = generate_layout_payload(
        "microstrip", MICROSTRIP_PARAMS, fmt="gdsii", output_path=str(tmp_path / "ms.gds")
    )
    laymap_path = tmp_path / "laymap.json"
    laymap_path.write_text('{"1": "F.Cu", "20": "Edge.Cuts"}', encoding="utf-8")
    readback = import_layout_payload(
        str(tmp_path / "ms.gds"), "gdsii", laymap_path=str(laymap_path)
    )
    assert {lay["name"] for lay in readback["layers"]} == {"F.Cu", "Edge.Cuts"}
    assert {node["layer"] for node in readback["items"]} == {"F.Cu", "Edge.Cuts"}
    assert round_trip_delta_payload(result["layout"], readback, "gdsii") == 0.0
    bare = import_layout_payload(str(tmp_path / "ms.gds"), "gdsii")
    assert set(bare) == set(readback)
    assert {lay["name"] for lay in bare["layers"]} == {"1", "20"}


def test_import_layout_payload_laymap_non_gdsii_rejected(tmp_path):
    laymap_path = tmp_path / "laymap.json"
    laymap_path.write_text('{"1": "F.Cu"}', encoding="utf-8")
    with pytest.raises(ValueError, match="laymap"):
        import_layout_payload(str(tmp_path / "x.dxf"), "dxf", laymap_path=str(laymap_path))


def test_import_layout_payload_laymap_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        import_layout_payload(
            str(tmp_path / "ms.gds"), "gdsii", laymap_path=str(tmp_path / "gone.json")
        )


# ---------------------------------------------------------------------------
# laymap 值冲突告警级校验（P2⑳ 批登记 followUp：冲突不检重留告警级校验）
# ---------------------------------------------------------------------------


def test_laymap_conflicts_clean_mapping_returns_empty():
    assert laymap_conflicts({"1": "F.Cu", "2": "B.Cu", "20": "Edge.Cuts"}) == []
    # 空/None 语义与 load_laymap 一致（空映射原样返回，无冲突可报）
    assert laymap_conflicts({}) == []


def test_laymap_conflicts_duplicate_value_detected():
    """登记主项：多个 GDS 层号映射到同一目标层名——_apply_laymap 会把两个
    不同 GDS 层静默合并为同一 KiCad 层，冲突清单须可定位到层号与目标名。"""
    conflicts = laymap_conflicts({"1": "F.Cu", "2": "F.Cu", "20": "Edge.Cuts"})
    assert len(conflicts) == 1
    assert "值冲突" in conflicts[0]
    assert "'1'" in conflicts[0] and "'2'" in conflicts[0] and "F.Cu" in conflicts[0]


def test_laymap_conflicts_key_normalization_collision():
    """同族静默丢失：原始键 "01" 与 1 归一后同键，dict 构造后者静默覆盖前者。"""
    conflicts = laymap_conflicts({"01": "F.Cu", 1: "B.Cu"})
    assert len(conflicts) == 1
    assert "键归一冲突" in conflicts[0]
    assert "01" in conflicts[0] and "'1'" in conflicts[0]


def test_laymap_conflicts_skips_non_layer_keys():
    """非层号键不参与冲突盘点（报错职责在 load_laymap 的 ValueError，不重复）。"""
    assert laymap_conflicts({"F.Cu": "F.Cu", 1: "F.Cu"}) == []


def test_load_laymap_clean_file_emits_no_warning(tmp_path):
    import warnings as _w

    path = tmp_path / "laymap.json"
    path.write_text('{"1": "F.Cu", "20": "Edge.Cuts"}', encoding="utf-8")
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        assert load_laymap(path) == {"1": "F.Cu", "20": "Edge.Cuts"}
    assert [w for w in caught if "冲突" in str(w.message)] == []


def test_load_laymap_warns_on_conflicting_file_and_keeps_semantics(tmp_path):
    """告警级：warn 可定位（路径+冲突键值）、返回 dict 语义不变（不 raise）。"""
    import warnings as _w

    path = tmp_path / "laymap_dup.json"
    path.write_text('{"1": "F.Cu", "2": "F.Cu"}', encoding="utf-8")
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        result = load_laymap(path)
    matches = [w for w in caught if "冲突" in str(w.message)]
    assert len(matches) == 1
    assert issubclass(matches[0].category, UserWarning)
    msg = str(matches[0].message)
    assert str(path) in msg and "值冲突" in msg and "F.Cu" in msg
    assert result == {"1": "F.Cu", "2": "F.Cu"}  # 语义不变、导入不阻塞


def test_import_layout_payload_conflicting_laymap_still_imports(tmp_path):
    """端到端：冲突 laymap 走 import_layout_payload 只告警不阻塞主路径。"""
    import warnings as _w

    generate_layout_payload(
        "microstrip", MICROSTRIP_PARAMS, fmt="gdsii", output_path=str(tmp_path / "ms.gds")
    )
    laymap_path = tmp_path / "laymap_merge.json"
    laymap_path.write_text('{"1": "F.Cu", "20": "F.Cu"}', encoding="utf-8")
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        readback = import_layout_payload(
            str(tmp_path / "ms.gds"), "gdsii", laymap_path=str(laymap_path)
        )
    assert any("冲突" in str(w.message) for w in caught)
    assert readback["items"]  # 主路径完成：层合并不阻塞导入
    assert {node["layer"] for node in readback["items"]} == {"F.Cu"}
