"""Q-X33（aurora_q T-Q22）——SPICE 网表深度解析服务信封单测。

覆盖面：parse_netlist_file/parse_netlist_text 两入口的信封正负例——
- ok 信封五维度键集 + AU-2 构造器合规（ok 恒首键/bool）；
- 文件不存在/目录入参/flavor 词表外 → error 信封（errors 恒 list[str]）；
- include_topology=False → topology=None 且 summary 拓扑派生字段如实
  None 非 0（#117 同族：0 是合法计数，缺失哨兵恒 None）；
- 全量 JSON 原生类型往返（服务层信封直出契约）。

零网络零真机；文件 fixture 全落 tmp_path（#144 家法：零 runs/ 湖写入）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.spice_netlist_service import (
    SPICE_FLAVORS,
    parse_netlist_file,
    parse_netlist_text,
)

FIVE_KEYS = ("elements", "subckts", "controls", "models", "topology")

_NGSPICE_RC = """RC lowpass divider
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 1u
.end
"""


@pytest.fixture()
def netlist_path(tmp_path: Path) -> Path:
    p = tmp_path / "rc_lpf.cir"
    p.write_text(_NGSPICE_RC, encoding="ascii")
    return p


class TestParseNetlistFile:
    def test_ok_envelope_five_keys(self, netlist_path):
        r = parse_netlist_file(netlist_path)
        assert r["ok"] is True
        assert set(FIVE_KEYS).issubset(r.keys())
        assert r["path"] == str(netlist_path)
        assert r["flavor"] == "ngspice"
        assert r["flavor_detected"] is True
        assert r["schema"] == "spice_netlist/1.0"
        assert r["summary"]["n_elements"] == 3
        assert r["summary"]["mna_size"] == 3  # 节点 in,out + V1 分支
        # AU-2 构造器合规：ok=True 信封不带 errors 键
        assert "errors" not in r

    def test_missing_file_error_envelope(self, tmp_path):
        r = parse_netlist_file(tmp_path / "nope.cir")
        assert r["ok"] is False
        assert isinstance(r["errors"], list)
        assert all(isinstance(e, str) for e in r["errors"])
        assert "不存在" in r["errors"][0]

    def test_directory_input_error(self, tmp_path):
        r = parse_netlist_file(tmp_path)
        assert r["ok"] is False
        assert r["errors"]

    def test_bad_flavor_error_envelope(self, netlist_path):
        r = parse_netlist_file(netlist_path, "pads")
        assert r["ok"] is False
        assert "不在词表" in r["errors"][0]
        assert r["flavor_requested"] == "pads"

    def test_explicit_flavor_passthrough(self, netlist_path):
        r = parse_netlist_file(netlist_path, "ngspice")
        assert r["ok"] is True
        assert r["flavor_detected"] is False

    def test_include_topology_off(self, netlist_path):
        r = parse_netlist_file(netlist_path, include_topology=False)
        assert r["ok"] is True
        assert r["topology"] is None
        assert r["include_topology"] is False
        # 拓扑派生 summary 字段如实 None 非 0（#117 同族纪律）
        assert r["summary"]["mna_size"] is None
        assert r["summary"]["n_nodes"] is None
        assert r["summary"]["n_x_instances"] is None
        # 元件面计数不受影响
        assert r["summary"]["n_elements"] == 3

    def test_json_roundtrip_all_native(self, netlist_path):
        r = parse_netlist_file(netlist_path)
        payload = json.loads(json.dumps(r))
        assert payload == json.loads(json.dumps(json.loads(json.dumps(r))))
        assert payload["summary"]["mna_size"] == 3


class TestParseNetlistText:
    def test_text_entry_path_none(self):
        r = parse_netlist_text(_NGSPICE_RC)
        assert r["ok"] is True
        assert r["path"] is None
        assert r["flavor"] == "ngspice"

    def test_text_bad_flavor(self):
        r = parse_netlist_text(_NGSPICE_RC, "spectre!")
        assert r["ok"] is False
        assert "不在词表" in r["errors"][0]

    def test_text_spectre_detection(self):
        text = "simulator lang=spectre\nR1 (a b) resistor r=1k\n"
        r = parse_netlist_text(text)
        assert r["ok"] is True
        assert r["flavor"] == "spectre"

    def test_flavor_wordtable_single_source(self):
        assert SPICE_FLAVORS == ("auto", "ngspice", "hspice", "spectre")

    def test_structural_errors_in_band_not_envelope_failure(self):
        # fail-soft 契约：结构错误进 structural_errors，信封仍 ok=True
        r = parse_netlist_text("ok deck\nR1 a b 1k\n.ends\n")
        assert r["ok"] is True
        assert r["structural_errors"]
        assert r["summary"]["n_structural_errors"] == len(r["structural_errors"])
