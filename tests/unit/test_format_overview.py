"""T-Q5 格式速览层批 1 单测：框架探测/schema 冻结/三格式结构钉/确定性/负例。

批 2 增补（只增）：layout 四格式（gdsii/dxf/ipc2581/odbpp）探测/结构钉/
确定性/负例 + 两处 registry 快照同步更新（schema 冻结钉 + 未注册 kind
示例换批 3 的 ads_ds——#231 惯例）。

口径（席位任务书验收，开工前冻结）：
- 同文件双跑速览 JSON 逐字节同（sha256 钉，三格式全钉）；
- 坏文件/未知格式显式报错信封（非异常裸抛）；
- 每格式速览含 stats+entities+summary 三段（schema 钉）；
- 每格式 schema_version 常量冻结（只增纪律——批 2/3 只增 kind 不改形）。

fixtures（tests/unit/fixtures/format_overview/）为手写小样例，禁用 runs/
湖文件；负例文件在 tmp_path 现场构造（一次性坏件不进仓）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from rfauto.service.format_overview_service import (
    _LOADERS as _LOADERS_VIEW,
)
from rfauto.service.format_overview_service import (
    FORMAT_OVERVIEW_VERSION,
    SCHEMA_VERSIONS,
    SUPPORTED_KINDS,
    detect_format_kind,
    overview_format,
    overview_format_json,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "format_overview"
_SNP = _FIXTURES / "minimal_two_port.s2p"
_KICAD = _FIXTURES / "minimal_board.kicad_pcb"
_DRAWIO = _FIXTURES / "minimal_diagram.drawio"

_OK_KEYS = {"ok", "kind", "schema_version", "framework_version", "path",
            "stats", "entities", "summary"}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 框架：schema 冻结 + kind 探测 + 信封形状
# ---------------------------------------------------------------------------

def test_schema_versions_frozen() -> None:
    """schema 版本冻结钉：各 kind 独立版本，框架版本独立。

    批 3 registry 快照同步（#231 惯例——新 kind 注册即同步覆盖类测试）：
    +ads_ds（Q-W9-3）；框架版本因探测规则扩位（EEsof 二进制 magic 双形态）
    1.1 → 1.2；各 kind 速览 schema 仍各为 1.0（形状未变）。
    """
    assert SCHEMA_VERSIONS == {
        "touchstone": "1.0",
        "kicad_pcb": "1.0",
        "drawio": "1.0",
        "gdsii": "1.0",
        "dxf": "1.0",
        "ipc2581": "1.0",
        "odbpp": "1.0",
        "ads_ds": "1.0",
    }
    assert SUPPORTED_KINDS == (
        "touchstone", "kicad_pcb", "drawio", "gdsii", "dxf", "ipc2581",
        "odbpp", "ads_ds")
    assert FORMAT_OVERVIEW_VERSION == "1.2"


def test_registry_loader_and_schema_consistent() -> None:
    """只增纪律自洽：loader 注册表键集 == schema 版本键集 == SUPPORTED_KINDS。"""
    assert set(_LOADERS_VIEW) == set(SCHEMA_VERSIONS) == set(SUPPORTED_KINDS)


@pytest.mark.parametrize("fixture,expected", [
    (_SNP, "touchstone"),
    (_KICAD, "kicad_pcb"),
    (_DRAWIO, "drawio"),
])
def test_detect_by_extension(fixture: Path, expected: str) -> None:
    assert detect_format_kind(fixture) == expected


@pytest.mark.parametrize("fixture,expected", [
    (_SNP, "touchstone"),
    (_KICAD, "kicad_pcb"),
    (_DRAWIO, "drawio"),
])
def test_detect_by_magic_without_extension(
    fixture: Path, expected: str, tmp_path: Path,
) -> None:
    """扩展名缺失时 magic 头兜底探测（扩展名+magic 双证据）。"""
    bare = tmp_path / "no_extension"
    shutil.copyfile(fixture, bare)
    assert detect_format_kind(bare) == expected


def test_detect_case_insensitive_suffix(tmp_path: Path) -> None:
    upper = tmp_path / "UPPER.S2P"
    shutil.copyfile(_SNP, upper)
    assert detect_format_kind(upper) == "touchstone"
    env = overview_format(upper)
    assert env["ok"] is True and env["kind"] == "touchstone"


def test_detect_unknown_content_returns_none(tmp_path: Path) -> None:
    mystery = tmp_path / "mystery.xyz"
    mystery.write_text("hello world\n", encoding="utf-8")
    assert detect_format_kind(mystery) is None


def test_unknown_format_error_envelope(tmp_path: Path) -> None:
    """未知格式=显式报错信封，非异常裸抛。"""
    mystery = tmp_path / "mystery.xyz"
    mystery.write_text("hello world\n", encoding="utf-8")
    env = overview_format(mystery)
    assert env["ok"] is False
    assert isinstance(env["errors"], list) and env["errors"]
    assert all(isinstance(e, str) for e in env["errors"])
    assert env["kind"] is None


def test_unknown_kind_error_envelope(tmp_path: Path) -> None:
    """未注册 kind（如 pdf）显式报错信封——只增纪律的负面证据。

    批 2 原用 ads_ds 作未注册示例，批 3 该 kind 已注册（#231 惯例换例）。
    """
    env = overview_format(_SNP, kind="pdf")
    assert env["ok"] is False
    assert env["errors"] and "pdf" in env["errors"][0]
    # 坏 kind 不应消费文件内容
    env2 = overview_format(tmp_path / "never_exists.s2p", kind="touchstone")
    assert env2["ok"] is False and env2["kind"] == "touchstone"


def test_missing_file_error_envelope(tmp_path: Path) -> None:
    env = overview_format(tmp_path / "absent.s2p")
    assert env["ok"] is False and env["errors"]


@pytest.mark.parametrize("fixture,expected_kind", [
    (_SNP, "touchstone"),
    (_KICAD, "kicad_pcb"),
    (_DRAWIO, "drawio"),
])
def test_ok_envelope_shape(fixture: Path, expected_kind: str) -> None:
    env = overview_format(fixture)
    assert set(env) == _OK_KEYS
    assert env["ok"] is True
    assert env["kind"] == expected_kind
    assert env["schema_version"] == SCHEMA_VERSIONS[expected_kind]
    assert env["framework_version"] == FORMAT_OVERVIEW_VERSION
    assert isinstance(env["stats"], dict) and env["stats"]
    assert isinstance(env["entities"], dict)
    assert isinstance(env["summary"], str) and env["summary"]


def test_overview_json_on_error_envelope(tmp_path: Path) -> None:
    """规范序列化对错误信封同样成立（JSON 可回读）。"""
    text = overview_format_json(tmp_path / "absent.s2p")
    assert text.endswith("\n")
    back = json.loads(text)
    assert back["ok"] is False


# ---------------------------------------------------------------------------
# touchstone（sNp）
# ---------------------------------------------------------------------------

def test_snp_structure_pins() -> None:
    env = overview_format(_SNP)
    stats = env["stats"]
    assert stats["n_ports"] == 2
    assert stats["n_points"] == 5
    assert stats["frequency_unit"] == "GHz"
    assert stats["f_min_hz"] == 1e9
    assert stats["f_max_hz"] == 3e9
    assert stats["comment_lines"] == 3
    assert stats["option_line"] == "# GHZ S RI R 50"
    assert stats["version"] is None  # TS1 无 [Version] 关键字
    assert stats["n_nonfinite_db"] == 0
    assert stats["z0_first_point_ohm"] == [[50.0, 0.0], [50.0, 0.0]]


def test_snp_per_port_s_ii_db_pins() -> None:
    """逐端口对角 S 参数 dB 极值（手写样例独立预算值——预声明验收）。"""
    per_port = overview_format(_SNP)["entities"]["per_port_s_ii_db"]
    assert [p["label"] for p in per_port] == ["S11", "S22"]
    assert [p["port"] for p in per_port] == [0, 1]
    s11, s22 = per_port
    assert s11["min_db"] == pytest.approx(-6.0206, abs=5e-7)
    assert s11["max_db"] == pytest.approx(-0.861861, abs=5e-7)
    assert s22["min_db"] == pytest.approx(-6.9897, abs=5e-7)
    assert s22["max_db"] == pytest.approx(-1.870866, abs=5e-7)


def test_snp_deterministic_sha256() -> None:
    """同文件两跑速览 JSON 逐字节同（sha256 钉）。"""
    a, b = overview_format_json(_SNP), overview_format_json(_SNP)
    assert a == b
    assert _sha256(a) == _sha256(b)
    assert overview_format(_SNP) == overview_format(_SNP)


def test_snp_touchstone2_version_pin(tmp_path: Path) -> None:
    """TS2 关键字 [Version] 值直读（2.0 档）。"""
    ts2 = tmp_path / "ts2.s2p"
    ts2.write_text(
        "! TS2 fixture\n"
        "[Version] 2.0\n"
        "# GHZ S RI R 50\n"
        "[Number of Ports] 2\n"
        "[Two-Port Data Order] 21_12\n"
        "[Number of Frequencies] 2\n"
        "1.0 0.9 0.1 0.05 0.02 0.05 0.02 0.8 -0.1\n"
        "2.0 0.5 0.3 0.15 0.06 0.15 0.06 0.4 -0.3\n"
        "[End]\n",
        encoding="utf-8",
    )
    env = overview_format(ts2)
    assert env["ok"] is True
    assert env["stats"]["version"] == "2.0"
    assert env["stats"]["n_points"] == 2


def test_snp_garbage_error_envelope(tmp_path: Path) -> None:
    """坏文件（垃圾内容冒充 .s2p）→ 错误信封（#248：不静默猜端口秩）。"""
    bad = tmp_path / "garbage.s2p"
    bad.write_text("not a touchstone file at all\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "touchstone"  # 扩展名已判定，解析失败如实归属
    assert env["errors"]


def test_snp_empty_file_error_envelope(tmp_path: Path) -> None:
    bad = tmp_path / "empty.s2p"
    bad.write_text("", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False and env["errors"]


def test_explicit_kind_bypasses_detection(tmp_path: Path) -> None:
    """显式 kind 直读成立（drawio 件改 .dat 扩展名——纯文本解析器与
    扩展名解耦）。注意 touchstone 不可如此：skrf 按 .sNp 扩展名推断
    端口秩（#248 仓内教训），错扩展名即错误信封，属如实报错不绕。"""
    renamed = tmp_path / "diagram.dat"
    shutil.copyfile(_DRAWIO, renamed)
    env = overview_format(renamed, kind="drawio")
    assert env["ok"] is True and env["stats"]["n_pages"] == 2
    # 同文件 magic 兜底探测也应命中——与显式 kind 产出逐键同（path 除外）
    auto = overview_format(renamed)
    assert auto["kind"] == "drawio"
    assert auto["stats"] == env["stats"]


# ---------------------------------------------------------------------------
# kicad_pcb
# ---------------------------------------------------------------------------

def test_kicad_structure_pins() -> None:
    env = overview_format(_KICAD)
    stats = env["stats"]
    assert stats["n_layers"] == 5
    assert stats["n_stackup_layers"] == 5
    assert stats["n_nets"] == 2  # (net 0 "") 空名不计
    assert stats["n_footprints"] == 2
    assert stats["n_tracks"] == 3
    assert stats["n_vias"] == 1
    assert stats["n_zones"] == 1
    assert stats["track_by_layer"] == {"B.Cu": 1, "F.Cu": 2}


def test_kicad_board_bbox_pins() -> None:
    """板框 bbox=Edge.Cuts 坐标 min/max（声明式聚合）。"""
    bbox = overview_format(_KICAD)["stats"]["board_bbox_mm"]
    assert bbox == {"min_mm": [0.0, 0.0], "max_mm": [30.0, 20.0],
                    "n_points": 2}


def test_kicad_entities_pins() -> None:
    entities = overview_format(_KICAD)["entities"]
    assert [fp["reference"] for fp in entities["footprints"]] == ["R1", "C1"]
    assert [fp["value"] for fp in entities["footprints"]] == ["10k", "100n"]
    assert entities["footprints"][0]["lib_id"] == "Resistor_SMD:R_0603"
    assert entities["footprints"][0]["n_pads"] == 2
    assert entities["footprints"][0]["at_mm"] == [10.0, 10.0]
    assert entities["net_names"] == ["GND", "VCC"]
    layer_names = [ln["name"] for ln in entities["layers"]]
    assert layer_names == ["F.Cu", "B.Cu", "B.SilkS", "F.SilkS", "Edge.Cuts"]
    stack = {sl["name"]: sl for sl in entities["stackup_layers"]}
    assert stack["dielectric 1"]["epsilon_r"] == 4.5
    assert stack["dielectric 1"]["loss_tangent"] == 0.02
    assert stack["F.Cu"]["type"] == "copper"


def test_kicad_deterministic_sha256() -> None:
    a, b = overview_format_json(_KICAD), overview_format_json(_KICAD)
    assert a == b
    assert _sha256(a) == _sha256(b)


def test_kicad_wrong_root_error_envelope(tmp_path: Path) -> None:
    """扩展名 .kicad_pcb 但根表达式是 kicad_sch → 错误信封。"""
    bad = tmp_path / "sch_as_pcb.kicad_pcb"
    bad.write_text("(kicad_sch (version 20250114))\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "kicad_pcb"
    assert env["errors"]


def test_kicad_unbalanced_parens_error_envelope(tmp_path: Path) -> None:
    bad = tmp_path / "broken.kicad_pcb"
    bad.write_text("(kicad_pcb (version 20241229)\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False and env["errors"]


def test_kicad_board_without_edge_cuts_bbox_none(tmp_path: Path) -> None:
    """无 Edge.Cuts 几何 → bbox=None 如实缺席（不猜板框）。"""
    bare = tmp_path / "bare.kicad_pcb"
    bare.write_text(
        '(kicad_pcb (version 20241229) (generator "pcbnew")\n'
        '  (net 1 "GND")\n'
        '  (segment (start 0 0) (end 1 1) (width 0.2) (layer "F.Cu") (net 1))\n'
        ")\n",
        encoding="utf-8",
    )
    env = overview_format(bare)
    assert env["ok"] is True
    assert env["stats"]["board_bbox_mm"] is None
    assert env["stats"]["n_tracks"] == 1


# ---------------------------------------------------------------------------
# drawio
# ---------------------------------------------------------------------------

def test_drawio_structure_pins() -> None:
    env = overview_format(_DRAWIO)
    stats = env["stats"]
    assert stats["n_pages"] == 2
    assert stats["n_vertices"] == 4
    assert stats["n_edges"] == 1
    assert stats["n_layers"] == 2
    assert stats["n_text_values"] == 4


def test_drawio_per_page_pins() -> None:
    """per-page 类型分布/图层/文本计数钉（样式首段=原文直读分组）。"""
    pages = overview_format(_DRAWIO)["entities"]["pages"]
    p1, p2 = pages
    assert (p1["diagram_id"], p1["diagram_name"]) == ("page-one", "Page-1")
    assert p1["n_vertices"] == 3 and p1["n_edges"] == 1
    assert p1["n_layers"] == 1 and p1["layer_names"] == ["Default Layer"]
    assert p1["text_value_count"] == 3  # Source/Load/note text；edge 空值不计
    assert p1["style_head_distribution"] == {
        "ellipse": 1, "rounded=1": 1, "text": 1}
    assert p2["n_vertices"] == 1 and p2["n_edges"] == 0
    assert p2["layer_names"] == ["Second Layer"]
    assert p2["text_value_count"] == 1
    assert p2["style_head_distribution"] == {"rounded=0": 1}


def test_drawio_deterministic_sha256() -> None:
    a, b = overview_format_json(_DRAWIO), overview_format_json(_DRAWIO)
    assert a == b
    assert _sha256(a) == _sha256(b)


def test_drawio_bad_xml_error_envelope(tmp_path: Path) -> None:
    bad = tmp_path / "broken.drawio"
    bad.write_text("<mxfile><diagram><unclosed>\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "drawio"
    assert env["errors"]


def test_drawio_non_mxfile_error_envelope(tmp_path: Path) -> None:
    bad = tmp_path / "html.drawio"
    bad.write_text("<html><body>x</body></html>\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False and env["errors"]


def test_drawio_missing_graph_model_error_envelope(tmp_path: Path) -> None:
    """压缩页形态（缺 mxGraphModel）→ 错误信封（read_diagram v1 边界）。"""
    bad = tmp_path / "compressed.drawio"
    bad.write_text(
        '<mxfile><diagram id="a" name="P">base64blob</diagram></mxfile>\n',
        encoding="utf-8",
    )
    env = overview_format(bad)
    assert env["ok"] is False and env["errors"]


# ---------------------------------------------------------------------------
# 批 2：layout 四格式（gdsii/dxf/ipc2581/odbpp）
#
# fixtures：minimal_layout.gds（gdstk 程序化生成，gdstk 1.0.1 已装）、
# minimal_layout.dxf（R12 子集手写）、minimal_layout.xml（IPC-2581 rev C
# 子集骨架手写）、minimal_odbpp/（子集目录手搭）。tgz 负例在 tmp_path
# 现场打包（archive 一次性件不进仓）。
# ---------------------------------------------------------------------------

_GDS = _FIXTURES / "minimal_layout.gds"
_DXF = _FIXTURES / "minimal_layout.dxf"
_IPC = _FIXTURES / "minimal_layout.xml"
_ODBPP_DIR = _FIXTURES / "minimal_odbpp"

_LAYOUT_STATS_KEYS = {
    "units", "n_layers", "n_items", "n_paths", "n_polygons", "n_circles",
    "n_vias", "per_layer_type_counts", "bbox_mm", "annotations",
}
_LAYOUT_ENTITY_KEYS = {"layout_name", "layers", "per_layer_distribution"}


# ---------------------------------------------------------------------------
# 批 2：kind 探测（扩展名映射/目录形态/二进制 magic 序）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,expected", [
    (_GDS, "gdsii"),
    (_DXF, "dxf"),
    (_IPC, "ipc2581"),
    (_ODBPP_DIR, "odbpp"),
])
def test_detect_layout_by_extension(fixture: Path, expected: str) -> None:
    assert detect_format_kind(fixture) == expected


def test_detect_gdsii_binary_magic_without_extension(tmp_path: Path) -> None:
    """扩展名缺失时二进制 magic 兜底（HEADER 记录头 00 06 00 02）。"""
    bare = tmp_path / "no_extension"
    shutil.copyfile(_GDS, bare)
    assert detect_format_kind(bare) == "gdsii"


def test_detect_ipc2581_magic_without_extension(tmp_path: Path) -> None:
    bare = tmp_path / "no_extension"
    shutil.copyfile(_IPC, bare)
    assert detect_format_kind(bare) == "ipc2581"


def test_detect_gdsii_magic_precedes_text_magic(tmp_path: Path) -> None:
    """二进制 GDSII magic 先于文本格式扫描（任务书扩位动作钉——正文含
    "(kicad_pcb" 也不得误路由）。"""
    trick = tmp_path / "trick"  # 无扩展名：走 magic 扫描路径
    trick.write_bytes(b"\x00\x06\x00\x02\x00\x01" + b"(kicad_pcb fake body)")
    assert detect_format_kind(trick) == "gdsii"


def test_detect_odbpp_directory_form() -> None:
    """目录形态：matrix/matrix 存在性探测（KiCad 10 目录导出口径）。"""
    assert detect_format_kind(_ODBPP_DIR) == "odbpp"
    env = overview_format(_ODBPP_DIR)
    assert env["ok"] is True and env["kind"] == "odbpp"


def test_detect_directory_without_matrix_returns_none(tmp_path: Path) -> None:
    """目录无 matrix/matrix → 不猜 odbpp（如实 None → 未知格式信封）。"""
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    assert detect_format_kind(empty) is None
    env = overview_format(empty)
    assert env["ok"] is False and env["kind"] is None


def test_detect_dxf_without_extension_returns_none(tmp_path: Path) -> None:
    """DXF 组码文本无可靠 magic——无扩展名不猜（如实 None）。"""
    bare = tmp_path / "no_extension"
    shutil.copyfile(_DXF, bare)
    assert detect_format_kind(bare) is None


# ---------------------------------------------------------------------------
# 批 2：layout 共用 schema 形状
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,kind", [
    (_GDS, "gdsii"),
    (_DXF, "dxf"),
    (_IPC, "ipc2581"),
    (_ODBPP_DIR, "odbpp"),
])
def test_layout_ok_envelope_shape(fixture: Path, kind: str) -> None:
    """layout 四格式共用 schema 形状（stats/entities 键集冻结口径）。"""
    env = overview_format(fixture)
    assert set(env) == _OK_KEYS
    assert env["ok"] is True
    assert env["kind"] == kind
    assert env["schema_version"] == "1.0"
    assert set(env["stats"]) == _LAYOUT_STATS_KEYS
    assert set(env["entities"]) == _LAYOUT_ENTITY_KEYS
    assert env["stats"]["units"] == "MM"
    assert isinstance(env["summary"], str) and env["summary"]


# ---------------------------------------------------------------------------
# 批 2：gdsii
# ---------------------------------------------------------------------------

def test_gdsii_structure_pins() -> None:
    env = overview_format(_GDS)
    stats = env["stats"]
    assert stats["units"] == "MM"
    assert stats["n_layers"] == 3
    assert stats["n_items"] == 3
    assert stats["n_paths"] == 1
    assert stats["n_polygons"] == 2  # 圆按 64 段内接多边形承载（GDSII 无原生圆）
    assert stats["n_circles"] == 0
    assert stats["n_vias"] == 0
    assert stats["per_layer_type_counts"] == {
        "1": {"path": 1, "polygon": 0, "circle": 0, "via": 0},
        "2": {"path": 0, "polygon": 1, "circle": 0, "via": 0},
        "20": {"path": 0, "polygon": 1, "circle": 0, "via": 0},
    }
    assert stats["annotations"] == {}


def test_gdsii_layer_name_is_gds_number_string() -> None:
    """GDSII 不携带层名——读回层名=层号字符串口径（批 2 指引钉）。"""
    layers = overview_format(_GDS)["entities"]["layers"]
    assert sorted(ln["name"] for ln in layers) == ["1", "2", "20"]
    for ln in layers:
        assert ln["name"] == str(ln["gds_layer"])
        assert ln["gds_datatype"] == 0
    assert overview_format(_GDS)["entities"]["layout_name"] == "minimal_layout"


def test_gdsii_bbox_pins() -> None:
    """bbox=坐标直读 min/max（不含半径外扩）；n_points=2+4+64。"""
    assert overview_format(_GDS)["stats"]["bbox_mm"] == {
        "min_mm": [0.0, 0.0], "max_mm": [10.0, 6.0], "n_points": 70}


def test_gdsii_deterministic_sha256() -> None:
    a, b = overview_format_json(_GDS), overview_format_json(_GDS)
    assert a == b
    assert _sha256(a) == _sha256(b)


def test_gdsii_garbage_error_envelope(tmp_path: Path) -> None:
    """文本垃圾冒充 .gds → HEADER 预检显式报错信封（不让 gdstk 消费任意
    字节；gdstk 1.0.1 实证对垃圾输入抛 OSError 不崩进程，预检使其更快）。"""
    bad = tmp_path / "garbage.gds"
    bad.write_text("not a gds file at all\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "gdsii"
    assert env["errors"]


def test_gdsii_truncated_after_magic_error_envelope(tmp_path: Path) -> None:
    """magic 头命中但记录损坏 → gdstk 异常照走错误信封（预检放行路径的
    负例——gdstk 1.0.1 实证干净抛 RuntimeError）。"""
    bad = tmp_path / "truncated.gds"
    bad.write_bytes(b"\x00\x06\x00\x02\x00\x01" + b"\x00" * 8)
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "gdsii"
    assert env["errors"]


# ---------------------------------------------------------------------------
# 批 2：dxf
# ---------------------------------------------------------------------------

def test_dxf_structure_pins() -> None:
    env = overview_format(_DXF)
    stats = env["stats"]
    assert stats["units"] == "MM"
    assert stats["n_layers"] == 2  # 层表按几何引用重建（无几何图层不保留）
    assert stats["n_items"] == 3
    assert (stats["n_paths"], stats["n_polygons"],
            stats["n_circles"], stats["n_vias"]) == (1, 1, 1, 0)
    assert stats["per_layer_type_counts"] == {
        "Edge.Cuts": {"path": 0, "polygon": 1, "circle": 0, "via": 0},
        "F.Cu": {"path": 1, "polygon": 0, "circle": 1, "via": 0},
    }
    assert stats["annotations"] == {}
    assert overview_format(_DXF)["entities"]["layout_name"] == "minimal_layout"


def test_dxf_layer_gds_assignment_pins() -> None:
    """DXF 层表按 assign_gds_layers 兜底编号：Edge.Cuts=20、F.Cu=1。"""
    layers = overview_format(_DXF)["entities"]["layers"]
    assert {ln["name"]: ln["gds_layer"] for ln in layers} == {
        "Edge.Cuts": 20, "F.Cu": 1}


def test_dxf_bbox_pins() -> None:
    """n_points=路径 2 + 圆心 1 + 多边形 4。"""
    assert overview_format(_DXF)["stats"]["bbox_mm"] == {
        "min_mm": [0.0, 0.0], "max_mm": [10.0, 6.0], "n_points": 7}


def test_dxf_deterministic_sha256() -> None:
    a, b = overview_format_json(_DXF), overview_format_json(_DXF)
    assert a == b
    assert _sha256(a) == _sha256(b)


def test_dxf_garbage_no_entities_error_envelope(tmp_path: Path) -> None:
    """无 ENTITIES 节 → 预检显式报错（adapter 对垃圾静默空成功的缺口在
    service 面兜住——不静默空成功）。"""
    bad = tmp_path / "garbage.dxf"
    bad.write_text("hello world\nnot a dxf at all\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "dxf"
    assert env["errors"]


def test_dxf_unknown_entity_skipped_annotation(tmp_path: Path) -> None:
    """未知实体（ARC）跳过计数 → annotations 原文透传（跳过如实计数）。"""
    text = _DXF.read_text(encoding="ascii")
    with_arc = text.replace(
        "0\nENDSEC\n0\nEOF",
        "0\nARC\n8\nF.Cu\n10\n1.0\n20\n1.0\n40\n0.5\n50\n0.0\n51\n90.0\n"
        "0\nENDSEC\n0\nEOF",
    )
    assert with_arc != text
    arc = tmp_path / "with_arc.dxf"
    arc.write_text(with_arc, encoding="ascii")
    env = overview_format(arc)
    assert env["ok"] is True
    assert env["stats"]["annotations"] == {"dxf_skipped_entities": "1"}
    assert env["stats"]["n_items"] == 3  # ARC 不进几何


# ---------------------------------------------------------------------------
# 批 2：ipc2581
# ---------------------------------------------------------------------------

def test_ipc2581_structure_pins() -> None:
    env = overview_format(_IPC)
    stats = env["stats"]
    assert stats["units"] == "MM"
    assert stats["n_layers"] == 2
    assert stats["n_items"] == 4
    assert (stats["n_paths"], stats["n_polygons"],
            stats["n_circles"], stats["n_vias"]) == (1, 1, 1, 1)
    assert stats["per_layer_type_counts"] == {
        "F.Cu": {"path": 1, "polygon": 0, "circle": 0, "via": 1},
        "B.Cu": {"path": 0, "polygon": 1, "circle": 1, "via": 0},
    }
    assert stats["annotations"] == {}
    assert overview_format(_IPC)["entities"]["layout_name"] == "minimal_layout"


def test_ipc2581_layer_table_pins() -> None:
    """子集骨架层表 gdsLayer/gdsDatatype 属性原文直读（不重编号）。"""
    assert overview_format(_IPC)["entities"]["layers"] == [
        {"name": "F.Cu", "gds_layer": 1, "gds_datatype": 0},
        {"name": "B.Cu", "gds_layer": 2, "gds_datatype": 0},
    ]


def test_ipc2581_bbox_pins() -> None:
    """n_points=路径 2 + 圆心 1 + 多边形 4 + 圆心 1。"""
    assert overview_format(_IPC)["stats"]["bbox_mm"] == {
        "min_mm": [0.0, 0.0], "max_mm": [10.0, 6.0], "n_points": 8}


def test_ipc2581_deterministic_sha256() -> None:
    a, b = overview_format_json(_IPC), overview_format_json(_IPC)
    assert a == b
    assert _sha256(a) == _sha256(b)


def test_ipc2581_bad_root_error_envelope(tmp_path: Path) -> None:
    """.xml 万金油扩展名误路由 → 根元素硬校验错误信封（kind 如实归属）。"""
    bad = tmp_path / "not_ipc.xml"
    bad.write_text('<?xml version="1.0"?>\n<other-root/>\n', encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "ipc2581"
    assert env["errors"]


# ---------------------------------------------------------------------------
# 批 2：odbpp
# ---------------------------------------------------------------------------

def test_odbpp_structure_pins() -> None:
    env = overview_format(_ODBPP_DIR)
    stats = env["stats"]
    assert stats["units"] == "MM"
    assert stats["n_layers"] == 2
    assert stats["n_items"] == 3
    assert (stats["n_paths"], stats["n_polygons"],
            stats["n_circles"], stats["n_vias"]) == (1, 1, 0, 1)
    assert stats["per_layer_type_counts"] == {
        "Edge.Cuts": {"path": 0, "polygon": 1, "circle": 0, "via": 0},
        "F.Cu": {"path": 1, "polygon": 0, "circle": 0, "via": 1},
    }
    entities = env["entities"]
    assert entities["layout_name"] == "minimal_step"  # step 目录名
    assert {ln["name"]: ln["gds_layer"] for ln in entities["layers"]} == {
        "Edge.Cuts": 20, "F.Cu": 1}


def test_odbpp_bbox_pins() -> None:
    """n_points=路径 2 + 圆心 1 + 多边形 4。"""
    assert overview_format(_ODBPP_DIR)["stats"]["bbox_mm"] == {
        "min_mm": [0.0, 0.0], "max_mm": [10.0, 6.0], "n_points": 7}


def test_odbpp_deterministic_sha256() -> None:
    a, b = overview_format_json(_ODBPP_DIR), overview_format_json(_ODBPP_DIR)
    assert a == b
    assert _sha256(a) == _sha256(b)


def test_odbpp_tgz_form_matches_dir(tmp_path: Path) -> None:
    """目录形态的 .tgz 包同内容同速览（stats/entities 逐键同；跨两次解包
    临时目录逐字节同——解包路径不进速览 JSON）。"""
    tgz = tmp_path / "packed.tgz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(_ODBPP_DIR, arcname=_ODBPP_DIR.name)
    env_dir = overview_format(_ODBPP_DIR)
    env_tgz = overview_format(tgz)
    assert env_tgz["ok"] is True and env_tgz["kind"] == "odbpp"
    assert env_tgz["stats"] == env_dir["stats"]
    assert env_tgz["entities"] == env_dir["entities"]
    assert overview_format_json(tgz) == overview_format_json(tgz)


def test_odbpp_tgz_without_matrix_error_envelope(tmp_path: Path) -> None:
    """tgz 解包后无唯一 matrix/matrix 根 → 显式报错信封。"""
    bad = tmp_path / "empty.tgz"
    with tarfile.open(bad, "w:gz"):
        pass
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "odbpp"
    assert env["errors"]


def test_odbpp_directory_without_matrix_explicit_kind_error_envelope(
    tmp_path: Path,
) -> None:
    """显式 kind=odbpp 但目录无 matrix/matrix → import 如实报错信封。"""
    empty = tmp_path / "no_matrix"
    empty.mkdir()
    env = overview_format(empty, kind="odbpp")
    assert env["ok"] is False
    assert env["kind"] == "odbpp"
    assert env["errors"]


def test_odbpp_tgz_non_tar_file_error_envelope(tmp_path: Path) -> None:
    """.tgz 扩展名但非 tar 内容 → is_tarfile 兜底分支如实报错信封。"""
    bad = tmp_path / "fake.tgz"
    bad.write_text("plain text, not a tar\n", encoding="utf-8")
    env = overview_format(bad)
    assert env["ok"] is False
    assert env["kind"] == "odbpp"
    assert env["errors"]
