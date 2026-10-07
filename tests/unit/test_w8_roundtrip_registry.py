"""W8 round-trip 导出器环回测试制度：登记表驱动（表外导出器 = review 红）。

制度口径（monthly_enhancement_plan F 流 W8）：每个交换格式导出器必须有
一张登记行 {exporter, module, exports, roundtrip_test, status}，其中
roundtrip_test 指向**已制度化的环回测试**（export→import→逐位/容差比对）：

1. ``test_roundtrip_tests_exist``——表内每个 roundtrip_test 节点可解析
   （import 测试模块并按 Class::test 归属断言存在）；引用既有测试而非
   重跑，避免双维护；
2. ``test_exporter_surface_covered``——受治理模块面上所有公开导出函数
   （``export_*``/``write_*``，本模块定义）必须被 ≥1 张登记行的 exports
   覆盖；新导出器不进表 → 本测试红（review 门强制）；
3. ``test_minimal_live_roundtrip_smoke``——每族一个最小环回真跑
   （layout gdsii / 互操作 mdif / touchstone v2），证明登记的环回契约
   当下可执行，而非仅登记历史。

layout_interchange 的 verify_round_trip（导出→读回→裁判单入口）与
interchange 的 max_complex_delta（复数逐位差）是既有裁判件，本文件直接
复用。全部确定性、零网络、tmp_path 隔离。
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest
import skrf

from rfauto.adapters.interchange import (
    export_interchange,
    max_complex_delta,
    read_interchange,
)
from rfauto.adapters.layout_interchange import (
    Layout,
    LayoutLayer,
    LayoutPath,
    LayoutPolygon,
    verify_round_trip,
)
from rfauto.adapters.touchstone_interop import write_touchstone_v2

#: W8 环回登记表：新导出器落地必须同时新增本行（review 门强制）。
W8_ROUNDTRIP_REGISTRY: list[dict[str, object]] = [
    # ── 版图互操作（B2：GDSII/DXF/IPC-2581/ODB++）──
    {"exporter": "layout_interchange.export_layout",
     "module": "rfauto.adapters.layout_interchange",
     "exports": ["export_layout", "export_gdsii", "export_dxf",
                 "export_ipc2581", "export_odbpp"],
     "roundtrip_test": "tests/unit/test_layout_interchange.py::"
                       "test_roundtrip_lossless_all_formats",
     "status": "governed"},
    {"exporter": "layout_interchange.export_layout(b1_bridge)",
     "module": "rfauto.adapters.layout_interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_layout_interchange.py::"
                       "test_b1_bridge_roundtrip_all_formats",
     "status": "governed"},
    # ── Touchstone 2.1 直写（件 1）──
    {"exporter": "touchstone_interop.write_touchstone_v2",
     "module": "rfauto.adapters.touchstone_interop",
     "exports": ["write_touchstone_v2"],
     "roundtrip_test": "tests/unit/test_touchstone_interop.py::"
                       "TestWriteTouchstoneV2::"
                       "test_roundtrip_s_and_freq_within_1e12",
     "status": "governed"},
    # ── G16 互操作矩阵（Touchstone 1.0/2.0 × MDIF × CITI）──
    {"exporter": "interchange.export_touchstone",
     "module": "rfauto.adapters.interchange",
     "exports": ["export_touchstone", "export_interchange"],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestTouchstoneRoundtrip::"
                       "test_touchstone_versions_roundtrip_all_port_counts",
     "status": "governed"},
    {"exporter": "interchange.export_touchstone(v1/v2 2port)",
     "module": "rfauto.adapters.interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestTouchstoneRoundtrip::"
                       "test_touchstone1_two_port_roundtrip",
     "status": "governed"},
    {"exporter": "interchange.export_touchstone(v1/v2 2port)",
     "module": "rfauto.adapters.interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestTouchstoneRoundtrip::"
                       "test_touchstone2_two_port_roundtrip",
     "status": "governed"},
    {"exporter": "interchange.export_mdif",
     "module": "rfauto.adapters.interchange",
     "exports": ["export_mdif"],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestMdifRoundtrip::test_mdif_roundtrip_all_port_counts",
     "status": "governed"},
    {"exporter": "interchange.export_citi",
     "module": "rfauto.adapters.interchange",
     "exports": ["export_citi"],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestCitiRoundtrip::test_citi_roundtrip_all_port_counts",
     "status": "governed"},
    {"exporter": "interchange.export_*(non-50 z0)",
     "module": "rfauto.adapters.interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestReferenceImpedance::"
                       "test_uniform_non_50_ohm_roundtrip",
     "status": "governed"},
    {"exporter": "interchange.export_*(per-port z0)",
     "module": "rfauto.adapters.interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestReferenceImpedance::"
                       "test_touchstone2_per_port_z0_roundtrip",
     "status": "governed"},
    {"exporter": "interchange.export_*(per-port z0)",
     "module": "rfauto.adapters.interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestReferenceImpedance::"
                       "test_citi_per_port_z0_roundtrip",
     "status": "governed"},
    {"exporter": "interchange.export_mdif_table",
     "module": "rfauto.adapters.interchange",
     "exports": ["export_mdif_table"],
     "roundtrip_test": "tests/unit/test_interchange_matrix.py::"
                       "TestTabularMdifRoundtrip::"
                       "test_roundtrip_two_columns_bitexact",
     "status": "governed"},
    {"exporter": "interchange.read_interchange(contract)",
     "module": "rfauto.adapters.interchange",
     "exports": [],
     "roundtrip_test": "tests/unit/test_interchange_and_gain_db.py::"
                       "TestInterchange::test_read_export_roundtrip_with_contract",
     "status": "governed"},
]

#: 受治理的导出器模块（表面函数须被登记表覆盖）
_GOVERNED_MODULES = ("rfauto.adapters.layout_interchange",
                     "rfauto.adapters.touchstone_interop",
                     "rfauto.adapters.interchange")


def _resolve_test_object(node_id: str):
    """节点 id → 测试对象（importlib + Class::test 归属解析）。"""
    rel, *parts = node_id.split("::")
    module_name = rel.replace("/", ".").removesuffix(".py")
    obj = importlib.import_module(module_name)
    for part in parts:
        obj = getattr(obj, part)
    return obj


@pytest.mark.parametrize("row", W8_ROUNDTRIP_REGISTRY,
                         ids=[str(r["exporter"]) for r in
                              W8_ROUNDTRIP_REGISTRY])
def test_roundtrip_tests_exist(row: dict[str, object]) -> None:
    """登记行指向的环回测试真实存在且可调用（节点 id 逐行可解析）。"""
    assert row["status"] == "governed"
    obj = _resolve_test_object(str(row["roundtrip_test"]))
    assert callable(obj)


def test_registry_rows_wellformed() -> None:
    """登记表结构契约：必需键齐、exports 均为字符串、node id 形态。"""
    assert len(W8_ROUNDTRIP_REGISTRY) >= 10
    for row in W8_ROUNDTRIP_REGISTRY:
        for key in ("exporter", "module", "exports", "roundtrip_test",
                    "status"):
            assert key in row, f"登记行缺键 {key}: {row}"
        exports = row["exports"]
        assert isinstance(exports, list)
        assert all(isinstance(e, str) for e in exports)
        node_id = str(row["roundtrip_test"])
        assert node_id.startswith("tests/unit/test_") and "::" in node_id


def test_exporter_surface_covered() -> None:
    """受治理模块面上全部公开导出函数被 ≥1 张登记行覆盖。

    新增 export_* / write_* 不进 W8_ROUNDTRIP_REGISTRY → 本测试红
    （W8 制度的 review 强制点）。
    """
    covered = {name for row in W8_ROUNDTRIP_REGISTRY
               for name in row["exports"]}
    missing: list[str] = []
    for module_name in _GOVERNED_MODULES:
        module = importlib.import_module(module_name)
        for name, obj in vars(module).items():
            if not name.startswith(("export_", "write_")):
                continue
            if not callable(obj):
                continue
            if getattr(obj, "__module__", None) != module_name:
                continue  # re-export 的外来件不在本模块治理面
            if inspect.ismodule(obj):
                continue
            if name not in covered:
                missing.append(f"{module_name}.{name}")
    assert not missing, (
        "导出器未进 W8 环回登记表（新导出器必须带 roundtrip 测试并登记）: "
        f"{missing}")


def test_registry_modules_exist() -> None:
    """登记行 module 字段全部可导入（防改名后登记表悬空）。"""
    for row in W8_ROUNDTRIP_REGISTRY:
        importlib.import_module(str(row["module"]))


# ─── 最小环回真跑（每族一件，证明登记契约当下可执行）───────────────────────

def _tiny_layout() -> Layout:
    layer = LayoutLayer(name="F.Cu", gds_layer=1, gds_datatype=0)
    return Layout(
        name="w8_smoke",
        layers=(layer, LayoutLayer(name="Edge.Cuts", gds_layer=2,
                                   gds_datatype=0)),
        items=(LayoutPolygon(points=((0.0, 0.0), (10.0, 0.0), (10.0, 5.0),
                                     (0.0, 5.0)),
                             layer="Edge.Cuts"),
               LayoutPath(points=((2.0, 2.5), (8.0, 2.5)), width_mm=0.25,
                          layer="F.Cu")),
    )


def test_minimal_live_roundtrip_layout_gdsii(tmp_path: Path) -> None:
    """layout 族：verify_round_trip 单入口环回，gdsii nm 格点无损。"""
    verdict = verify_round_trip(_tiny_layout(), "gdsii", tmp_path)
    assert verdict["lossless"] is True
    assert verdict["delta"] == 0.0


def test_minimal_live_roundtrip_mdif(tmp_path: Path) -> None:
    """互操作族：mdif 导出→读回→复数逐位差 0（max_complex_delta 裁判）。"""
    freq = skrf.Frequency(1.0, 3.0, 5, unit="GHz")
    net = skrf.Network(
        frequency=freq,
        s=[[[-0.1]], [[0.5 + 0.2j]], [[-0.1]], [[0.5 - 0.2j]],
           [[-0.1]]],
        z0=50.0, name="w8_smoke")
    path = export_interchange(net, tmp_path / "w8.mdif", "mdif")
    back = read_interchange(path, "mdif")[0]
    assert back.number_of_ports == 1
    assert max_complex_delta(net.s, back.s) == 0.0


def test_minimal_live_roundtrip_touchstone_v2(tmp_path: Path) -> None:
    """touchstone v2 直写族：写出→skrf 读回，S/f/z0 全对拍。"""
    freq = skrf.Frequency(1.0, 2.0, 3, unit="GHz")
    net = skrf.Network(frequency=freq,
                       s=[[[0.1]], [[-0.2j]], [[0.15]]], z0=50.0)
    path = write_touchstone_v2(net, tmp_path / "w8.s2p")
    back = skrf.Network(str(path))
    assert back.number_of_ports == 1
    assert max_complex_delta(net.s, back.s) == 0.0
