"""aurora_r R-18（VB-9）——Spectre ``nport`` 交接片段生成服务单测。

覆盖面（VB-9 预声明验收逐条）：
- ①生成片段经 rfauto spice_netlist_parser（spectre 风格）往返解析，
  实例名/节点/文件参数逐项还原（服务层 roundtrip 自证 + 测试独立
  复核双证）；
- ②端口节点数≠sNp 端口数 → error 信封（errors 恒 list[str]）；
- ③真 Spectre 运行验收 UNVERIFIED-LOCAL 如实登记
  （spectre_run_verified 恒 False + verification_note）；
- ④前置门证据：syntax_source 携带官方 Reference 原文出处 URL + 逐字
  引文（docstring 同源双呈现）。

零网络零真机；文件 fixture 全落 tmp_path（#144 家法：零 runs/ 湖写入）；
零新依赖。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.core.spice_netlist_parser import parse_spice_netlist_text
from rfauto.service.spectre_nport_service import generate_nport_instance

V1_2P_RI = """# GHZ S RI R 50
1.0 1 0 0 0 0.5 0.5 0.2 -0.1
2.0 0.8 0.1 -0.1 0.1 0.4 0.4 0.1 0.1
3.0 0.6 -0.2 0.2 0.1 0.3 0.3 0.05 0.05
"""

# 4 端口用 v2.0（声明 [Number of Ports]=4 与首行 33 值数内容共识）——
# v1.0 首行规则词表只认 3/7/9 值数（1/2 端口形态），4 端口 v1.0 在
# core 嗅探面如实 UNKNOWN（宁 UNKNOWN 不误判，不造数据绕过）。
V2_4P_RI = (
    "[Version] 2.0\n"
    "# GHZ S RI R 50\n"
    "[Number of Ports] 4\n"
    "[Number of Frequencies] 2\n"
    "[Network Data]\n"
    + "1.0 " + "0.5 0 " * 16 + "\n"
    + "2.0 " + "0.4 0 " * 16 + "\n"
    + "[End]\n"
)

# v2.0 规则②（首行 9 token → 2 端口）与规则③（声明 3 频/组 5 token → 1
# 端口）无交集 → rank 冲突如实 UNKNOWN（test_touchstone_parser 同款场景）。
V2_CONFLICT = """[Version] 2.0
# GHZ S RI R 50
[Number of Frequencies] 3
[Network Data]
1 1 0 0.5 0 0.5 0 0.5 0
2 1 0
3 0 1
"""


@pytest.fixture()
def snp2_path(tmp_path: Path) -> Path:
    p = tmp_path / "device.s2p"
    p.write_text(V1_2P_RI, encoding="ascii")
    return p


@pytest.fixture()
def snp4_path(tmp_path: Path) -> Path:
    p = tmp_path / "device4.s4p"
    p.write_text(V2_4P_RI, encoding="ascii")
    return p


# ── ok 信封与片段形态 ──────────────────────────────────────────────────────


class TestOkEnvelope:
    def test_basic_snippet_and_fields(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path)
        assert r["ok"] is True
        assert r["n_ports"] == 2
        assert r["terminals"] == 4
        assert r["master"] == "nport"
        assert r["nodes"] == ["p1", "gnd", "p2", "gnd"]
        assert r["snippet"] == (
            f'nport1 (p1 gnd p2 gnd) nport file="{snp2_path}"'
        )
        assert r["params"]["file"] == f'"{snp2_path}"'
        assert r["format"]["r_ref"] == 50
        assert r["format"]["version"] == "1.0"
        # AU-2 构造器合规：ok=True 信封不带 errors 键
        assert "errors" not in r

    def test_roundtrip_service_selfcheck_green(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path)
        assert r["roundtrip"]["verified"] is True
        assert r["roundtrip"]["name"] == "nport1"
        # 接地别名 gnd → 0（解析器单源行为，信封如实回传）
        assert r["roundtrip"]["nodes"] == ["p1", "0", "p2", "0"]
        assert r["roundtrip"]["master"] == "nport"

    def test_roundtrip_parser_independent(self, snp2_path: Path) -> None:
        # VB-9 验收①：测试独立复核（不经服务层 roundtrip 块）
        snippet = generate_nport_instance(
            snp2_path, instance_name="xmain",
            datafmt="touchstone", interp="linear", scale=2,
        )["snippet"]
        parsed = parse_spice_netlist_text(snippet, "spectre")
        assert len(parsed["elements"]) == 1
        el = parsed["elements"][0]
        assert el["name"] == "xmain"
        assert el["nodes"] == ["p1", "0", "p2", "0"]
        assert el["model"] == "nport"
        assert el["params"]["file"].strip('"') == str(snp2_path)
        assert el["params"]["datafmt"] == "touchstone"
        assert el["params"]["interp"] == "linear"
        assert el["params"]["scale"] == 2.0

    def test_explicit_nodes_used_verbatim(self, snp2_path: Path) -> None:
        r = generate_nport_instance(
            snp2_path, nodes=["rf_in", "gnd", "rf_out", "gnd"],
            expected_n_ports=2,
        )
        assert r["ok"] is True
        assert r["nodes"] == ["rf_in", "gnd", "rf_out", "gnd"]
        assert r["snippet"].startswith(
            "nport1 (rf_in gnd rf_out gnd) nport file="
        )
        assert r["roundtrip"]["verified"] is True

    def test_four_port_auto_nodes(self, snp4_path: Path) -> None:
        r = generate_nport_instance(snp4_path, expected_n_ports=4)
        assert r["ok"] is True
        assert r["n_ports"] == 4
        assert r["terminals"] == 8
        assert r["nodes"] == [
            "p1", "gnd", "p2", "gnd", "p3", "gnd", "p4", "gnd",
        ]
        assert r["roundtrip"]["verified"] is True

    def test_custom_ref_node_and_name(self, snp2_path: Path) -> None:
        r = generate_nport_instance(
            snp2_path, instance_name="X_BPF1", ref_node="vgnd",
        )
        assert r["ok"] is True
        assert r["nodes"] == ["p1", "vgnd", "p2", "vgnd"]
        assert r["snippet"].startswith("X_BPF1 (p1 vgnd p2 vgnd) nport")

    def test_envelope_json_roundtrip(self, snp2_path: Path) -> None:
        # 信封全量 JSON 原生类型往返（服务层直出契约）
        r = generate_nport_instance(snp2_path)
        again = json.loads(json.dumps(r))
        assert again == r

    def test_syntax_source_official_quotes(self, snp2_path: Path) -> None:
        # 前置门证据：官方原文出处 URL + 逐字引文可溯源
        src = generate_nport_instance(snp2_path)["syntax_source"]
        assert src["url"] == (
            "http://eece.cu.edu.eg/~fhussien/Spectre_tutorial.pdf"
        )
        assert "Product Version 5.0" in src["document"]
        assert "Terminals must be given in pairs" in src["instance_definition"]
        assert src["sample_instance_statement"] == (
            'x1 (a1 0 b1 0 b3 0) ndata file="sparam2.data"'
        )
        assert src["sample_model_statement"] == (
            'model ndata nport file="sparam.data" scale=1'
        )
        assert "bbspice" in src["secondary_source"]
        assert "nport_default_interp" in src["secondary_source"]

    def test_unverified_local_registered(self, snp2_path: Path) -> None:
        # VB-9 前置门③：真机验收 UNVERIFIED-LOCAL 如实登记
        r = generate_nport_instance(snp2_path)
        assert r["spectre_run_verified"] is False
        assert "UNVERIFIED-LOCAL" in r["verification_note"]

    def test_scale_float_emitted_and_roundtrip(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path, scale=1.5)
        assert r["params"]["scale"] == "1.5"
        assert "scale=1.5" in r["snippet"]
        assert r["roundtrip"]["verified"] is True


# ── error 信封（显式不静默，#105/#122） ───────────────────────────────────


class TestErrorEnvelopes:
    def test_port_count_mismatch_error(self, snp2_path: Path) -> None:
        # VB-9 验收②：请求端口数 ≠ sNp 端口数 → error 信封
        r = generate_nport_instance(snp2_path, expected_n_ports=3)
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert "3" in r["errors"][0] and "2" in r["errors"][0]
        assert r["expected_n_ports"] == 3
        assert r["file_n_ports"] == 2

    def test_nodes_count_mismatch_error(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path, nodes=["a", "b", "c"])
        assert r["ok"] is False
        assert "端子数不一致" in r["errors"][0]
        assert r["nodes"] == 3 and r["n_ports"] == 2

    def test_rank_conflict_error(self, tmp_path: Path) -> None:
        p = tmp_path / "conflict.s2p"
        p.write_text(V2_CONFLICT, encoding="ascii")
        r = generate_nport_instance(p)
        assert r["ok"] is False
        assert "rank" in r["errors"][0]
        assert r["rank"]["n_ports"] is None

    def test_missing_file_error(self, tmp_path: Path) -> None:
        r = generate_nport_instance(tmp_path / "nope.s2p")
        assert r["ok"] is False
        assert "嗅探失败" in r["errors"][0]

    def test_datafmt_vocab_error(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path, datafmt="s2p")
        assert r["ok"] is False
        assert "datafmt" in r["errors"][0]

    def test_interp_vocab_error(self, snp2_path: Path) -> None:
        # bbspice 是 19.1 新增插值——v5.0 逐字词表外，拒绝产出
        r = generate_nport_instance(snp2_path, interp="bbspice")
        assert r["ok"] is False
        assert "interp" in r["errors"][0]

    def test_instance_name_invalid_error(self, snp2_path: Path) -> None:
        for bad in ("1port", "n port", "n-port!"):
            r = generate_nport_instance(snp2_path, instance_name=bad)
            assert r["ok"] is False, bad
            assert "实例名非法" in r["errors"][0]

    def test_path_whitespace_error(self, tmp_path: Path) -> None:
        p = tmp_path / "has space.s2p"
        p.write_text(V1_2P_RI, encoding="ascii")
        r = generate_nport_instance(p)
        assert r["ok"] is False
        assert "文件路径" in r["errors"][0]

    def test_node_unsafe_char_error(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path, nodes=["a b", "gnd", "c", "d"])
        assert r["ok"] is False
        assert "节点名" in r["errors"][0]

    def test_scale_nonpositive_error(self, snp2_path: Path) -> None:
        for bad in (0, -1.0):
            r = generate_nport_instance(snp2_path, scale=bad)
            assert r["ok"] is False, bad
            assert "scale" in r["errors"][0]

    def test_ref_node_unsafe_error(self, snp2_path: Path) -> None:
        r = generate_nport_instance(snp2_path, ref_node="g nd")
        assert r["ok"] is False
        assert "参考节点名" in r["errors"][0]
