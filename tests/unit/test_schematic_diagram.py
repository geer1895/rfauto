"""引脚级原理图 .drawio 生成器钉（aurora_p A1 席，2026-11-01）。

七验收钉（任务书口径 A-G；语法出处=linkage/templates/ads 渲染实文，
#215 纪律：解析器对渲染实文逐行实测校验）：
A. 模板族交叉一致——wilkinson_snp / branchline_cascade 渲染网表各解析
   一次，元件清单与 ads_template_family 渲染器拓扑逐一对上（数量+kind+
   节点连接表）；
B. XML 合法+drawio 语义九条——ET 解析/mxfile 骨架/基 cell 0,1/id 页内
   唯一/vertex 全带 geometry/edge relative="1" 且两端 id 存在/未压缩/
   无孤儿 parent/value 转义（parse_diagram 往返）；
C. 引脚连接完整性——每引脚恰被恰一条边引用，或 dangling="1" 显式标记
   （无静默悬空；多引脚网=汇接点辐条形态，同判据）；
D. 确定性——内核两跑逐字节相同 + CLI 子进程两跑 byte_identical；
E. （既有面零改动=对应既有测试文件全绿，不在本文件钉——合流门覆盖）；
F. 计数 293 全链一致（test_check_numbers/test_cli/test_cli_registration_
   order 三钉本席同笔回填，本文件只钉新叶注册面）；
G. 样例落 runs/aurora_p/a1/（交付面，不进门）。

负例面：网表严格校验（未知行/未知元件头/续行/引号不闭合/缺节点/缺必备
参数/节点数与族不符/实例名形态与保留命名空间/实例名重复/同元件节点重复/
Port Num 重复/参数区词表外裸 token/空网表）全显式 ValueError；service
信封 ok=False 同构；CLI usage exit 2 / service 失败 exit 1。
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.core.drawio_xml import parse_diagram
from rfauto.core.schematic_diagram import (
    build_schematic_diagram_xml,
    build_schematic_plan,
    parse_netlist,
)
from rfauto.linkage import ads_template_family as atf
from rfauto.service.schematic_diagram_service import generate_schematic_diagram

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

SWEEP = {"fstart": 1.6, "fstop": 3.2, "npoints": 401, "unit": "GHz"}

#: 分层布局期望（branchline 链 P1→TLIN1→SNP1→TLIN2→P2 信号流向左→右；
#: BFS 分层单源断言——列号随实现细节漂移即显式评审动作）
_BRANCHLINE_CHAIN = ["P1", "TLIN1", "SNP1", "TLIN2", "P2"]


# ─── 渲染 fixtures（模板族实文；显式 sweep 免读 Touchstone） ────────────────


@pytest.fixture(scope="module")
def wilkinson_text() -> str:
    return atf.render_wilkinson_snp(
        "demo_ref.s3p", sweep=dict(SWEEP), n_ports=3, z0=50.0)


@pytest.fixture(scope="module")
def branchline_text() -> str:
    return atf.render_branchline_cascade(
        "demo_ref.s4p", sweep=dict(SWEEP), n_ports=4)


# ─── A. 模板族交叉一致 ──────────────────────────────────────────────────────


class TestFamilyCrossCheck:
    def test_wilkinson_components_match_renderer_topology(
            self, wilkinson_text: str):
        parsed = parse_netlist(wilkinson_text)
        kinds = [(c["name"], c["kind"]) for c in parsed["components"]]
        # 渲染器拓扑：Port×3（Num 1..3，节点 Pi+地）+ SnP×1（3 节点直通）
        assert kinds == [("P1", "Port"), ("P2", "Port"), ("P3", "Port"),
                         ("SNP1", "SnP")]
        snp = parsed["components"][3]
        assert snp["nodes"] == ["P1", "P2", "P3"]
        assert snp["params"]["NumPorts"] == "3"
        for i, port in enumerate(parsed["components"][:3], 1):
            assert port["nodes"] == [f"P{i}", "0"]
            assert port["params"]["Num"] == str(i)
        nets = parse_netlist(wilkinson_text)  # 同参重析恒等（确定性解析）
        assert nets == parsed

    def test_wilkinson_nets_match_renderer_topology(
            self, wilkinson_text: str):
        plan = build_schematic_plan(wilkinson_text)
        nets = {n["name"]: (n["kind"], n["n_pins"]) for n in plan["nets"]}
        # 网=Pi（Port 引脚 1 ↔ SNP 引脚 i 两引脚）+ 地网 "0"（3 地引脚）
        assert nets == {
            "P1": ("wire", 2), "P2": ("wire", 2), "P3": ("wire", 2),
            "0": ("ground", 3),
        }
        assert plan["n_ports"] == 3 and plan["n_elements"] == 1
        assert plan["n_ground_pins"] == 3 and plan["n_ground_stubs"] == 3
        assert plan["n_wires"] == 3 and plan["n_dangling"] == 0
        assert plan["n_controls"] == 4  # Options/S_Param/SweepPlan/OutputPlan
        assert plan["sweep"] == {"start": "1.6", "stop": "3.2",
                                 "npoints": "401", "unit": "GHz"}

    def test_branchline_components_match_renderer_topology(
            self, branchline_text: str):
        parsed = parse_netlist(branchline_text)
        kinds = [(c["name"], c["kind"]) for c in parsed["components"]]
        # 渲染器拓扑：Port×4 + TLIN×2（入线/出线）+ SnP×1（4 节点）
        assert kinds == [("P1", "Port"), ("P2", "Port"), ("P3", "Port"),
                         ("P4", "Port"), ("TLIN1", "TLIN"), ("SNP1", "SnP"),
                         ("TLIN2", "TLIN")]
        tlin1, snp, tlin2 = (parsed["components"][4],
                             parsed["components"][5], parsed["components"][6])
        assert tlin1["nodes"] == ["N_A", "N_B"]
        assert tlin2["nodes"] == ["N_C", "N_D"]
        assert snp["nodes"] == ["N_B", "N_C", "N_T1", "N_T2"]
        assert snp["params"]["NumPorts"] == "4"

    def test_branchline_nets_match_renderer_topology(
            self, branchline_text: str):
        plan = build_schematic_plan(branchline_text)
        nets = {n["name"]: (n["kind"], n["n_pins"]) for n in plan["nets"]}
        # 六个信号网（N_A/N_B/N_C/N_D/N_T1/N_T2 各两引脚）+ 地网（4 地引脚）
        assert nets == {
            "N_A": ("wire", 2), "N_B": ("wire", 2), "N_C": ("wire", 2),
            "N_D": ("wire", 2), "N_T1": ("wire", 2), "N_T2": ("wire", 2),
            "0": ("ground", 4),
        }
        assert plan["n_ports"] == 4 and plan["n_elements"] == 3
        assert plan["n_nets_signal"] == 6 and plan["n_ground_pins"] == 4

    def test_branchline_signal_chain_left_to_right(
            self, branchline_text: str):
        plan = build_schematic_plan(branchline_text)
        col = {c["name"]: c["column"] for c in plan["components"]}
        chain = _BRANCHLINE_CHAIN
        for a, b in itertools.pairwise(chain):
            assert col[a] < col[b], (
                f"信号流向违约：{a}(列 {col[a]}) 应在 {b}(列 {col[b]}) 左侧")


# ─── 严格校验负例（显式 ValueError，不静默） ────────────────────────────────


class TestParserStrictNegatives:
    def test_unknown_line_rejected(self):
        with pytest.raises(ValueError, match="无法识别"):
            parse_netlist("Port:P1  P1 0 Num=1 Z=50 Ohm Noise=yes\nGARBAGE LINE")

    def test_unknown_component_head_rejected(self):
        with pytest.raises(ValueError, match="无法识别"):
            parse_netlist("RES:R1  N_A N_B R=50 Ohm")

    def test_continuation_line_rejected(self):
        with pytest.raises(ValueError, match="续行"):
            parse_netlist("Port:P1  P1 0 Num=1 Z=50 \\")

    def test_unclosed_quote_rejected(self):
        with pytest.raises(ValueError, match="引号不闭合"):
            parse_netlist(
                'SnP:SNP1  N_A NumPorts=1 File="unclosed.s2p Type="touchstone"')

    def test_port_second_node_not_ground_rejected(self):
        with pytest.raises(ValueError, match="第 2 节点=地"):
            parse_netlist("Port:P1  N_A N_B Num=1 Z=50 Ohm")

    def test_port_missing_z_rejected(self):
        with pytest.raises(ValueError, match="缺必备参数 Z"):
            parse_netlist("Port:P1  P1 0 Num=1 Noise=yes")

    def test_port_missing_num_rejected(self):
        with pytest.raises(ValueError, match="缺必备参数 Num"):
            parse_netlist("Port:P1  P1 0 Z=50 Ohm")

    def test_port_num_duplicate_rejected(self):
        with pytest.raises(ValueError, match="Num=1 与既有端口重复"):
            parse_netlist("Port:P1  P1 0 Num=1 Z=50 Ohm\n"
                          "Port:P2  P2 0 Num=1 Z=50 Ohm")

    def test_tlin_missing_e_rejected(self):
        with pytest.raises(ValueError, match="缺必备参数 E"):
            parse_netlist("TLIN:TL1  N_A N_B Z=50 Ohm F=2.4 GHz")

    def test_tlin_wrong_node_count_rejected(self):
        with pytest.raises(ValueError, match="恰 2 节点"):
            parse_netlist("TLIN:TL1  N_A N_B N_C Z=50 Ohm E=90 F=2.4 GHz")

    def test_snp_numports_mismatch_rejected(self):
        with pytest.raises(ValueError, match="NumPorts=2 与节点数 3 不符"):
            parse_netlist(
                'SnP:SNP1  N_A N_B N_C NumPorts=2 File="x.s3p" '
                'Type="touchstone"')

    def test_snp_missing_file_rejected(self):
        with pytest.raises(ValueError, match="缺必备参数 File"):
            parse_netlist(
                'SnP:SNP1  N_A N_B NumPorts=2 Type="touchstone"')

    def test_instance_name_duplicate_rejected(self):
        with pytest.raises(ValueError, match="实例名重复"):
            parse_netlist("Port:P1  P1 0 Num=1 Z=50 Ohm\n"
                          "Port:P1  P1 0 Num=2 Z=50 Ohm")

    def test_instance_name_with_dot_rejected(self):
        with pytest.raises(ValueError, match="必须匹配"):
            parse_netlist("Port:P.1  P1 0 Num=1 Z=50 Ohm")

    def test_instance_name_reserved_rejected(self):
        for name in ("title", "w1", "g2", "j3"):
            with pytest.raises(ValueError, match="保留 id 命名空间"):
                parse_netlist(f"Port:{name}  P1 0 Num=1 Z=50 Ohm")

    def test_same_component_duplicate_node_rejected(self):
        with pytest.raises(ValueError, match="节点重复"):
            parse_netlist("TLIN:TL1  N_A N_A Z=50 Ohm E=90 F=2.4 GHz")

    def test_param_region_stray_bare_token_rejected(self):
        with pytest.raises(ValueError, match="词表外裸 token"):
            parse_netlist("TLIN:TL1  N_A N_B Z=50 Ohm bogus E=90 F=2.4 GHz")

    def test_duplicate_param_key_rejected(self):
        with pytest.raises(ValueError, match="参数 Z 重复"):
            parse_netlist("TLIN:TL1  N_A N_B Z=50 Z=60 Ohm E=90 F=2.4 GHz")

    def test_missing_node_list_rejected(self):
        with pytest.raises(ValueError, match="缺节点表"):
            parse_netlist("TLIN:TL1  Z=50 Ohm E=90 F=2.4 GHz")

    def test_empty_netlist_rejected(self):
        with pytest.raises(ValueError, match="空网表"):
            parse_netlist("* 只有注释\n\n")

    def test_non_string_input_rejected(self):
        with pytest.raises(ValueError, match="必须是 str"):
            parse_netlist(None)  # type: ignore[arg-type]

    def test_params_preserved_verbatim(self):
        """参数原值原样（铁律 7）：值文本逐位保留、不做数值解析换算。"""
        parsed = parse_netlist(
            "TLIN:TL1  N_A N_B Z=50 Ohm E=90 F=2.4 GHz")
        comp = parsed["components"][0]
        assert comp["params"] == {"Z": "50", "E": "90", "F": "2.4"}
        assert comp["param_tokens"] == ["Z=50", "Ohm", "E=90", "F=2.4", "GHz"]

    def test_quoted_path_with_spaces_parsed(self):
        parsed = parse_netlist(
            'SnP:SNP1  N_A NumPorts=1 File="my dir/x y.s2p" '
            'Type="touchstone" InterpDom=""')
        assert parsed["components"][0]["params"]["File"] == "my dir/x y.s2p"
        assert parsed["components"][0]["params"]["InterpDom"] == ""


# ─── B. XML 合法 + drawio 语义九条 ──────────────────────────────────────────


class TestDrawioSemantics:
    @pytest.fixture(scope="class")
    def xml_text(self, branchline_text: str) -> str:
        return build_schematic_diagram_xml(branchline_text)

    def test_1_xml_parses_and_root_is_mxfile(self, xml_text: str):
        root = ET.fromstring(xml_text)
        assert root.tag == "mxfile"

    def test_2_skeleton_diagram_model_root(self, xml_text: str):
        root = ET.fromstring(xml_text)
        assert root.find("diagram") is not None
        model = root.find("diagram/mxGraphModel")
        assert model is not None
        assert model.find("root") is not None

    def test_3_base_cells_0_and_1(self, xml_text: str):
        root = ET.fromstring(xml_text)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")
        ids = [c.get("id") for c in cells]
        assert "0" in ids and "1" in ids
        base1 = next(c for c in cells if c.get("id") == "1")
        assert base1.get("parent") == "0"

    def test_4_cell_ids_page_unique(self, xml_text: str):
        root = ET.fromstring(xml_text)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")
        ids = [c.get("id") for c in cells]
        assert len(ids) == len(set(ids))

    def test_5_every_vertex_has_geometry(self, xml_text: str):
        root = ET.fromstring(xml_text)
        for cell in root.findall("diagram/mxGraphModel/root/mxCell"):
            if cell.get("vertex") == "1":
                geom = cell.find("mxGeometry")
                assert geom is not None, f"vertex {cell.get('id')} 缺 geometry"
                for attr in ("x", "y", "width", "height"):
                    assert geom.get(attr) is not None

    def test_6_edges_have_source_target_existing(self, xml_text: str):
        root = ET.fromstring(xml_text)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")
        ids = {c.get("id") for c in cells}
        for cell in cells:
            if cell.get("edge") == "1":
                assert cell.get("source") in ids
                assert cell.get("target") in ids
                geom = cell.find("mxGeometry")
                assert geom is not None
                assert geom.get("relative") == "1"

    def test_7_uncompressed_native_mxfile(self, xml_text: str):
        root = ET.fromstring(xml_text)
        assert root.find("diagram/mxGraphModel") is not None
        assert "compressed" not in (root.find("diagram").attrib or {})

    def test_8_no_orphan_parents(self, xml_text: str):
        root = ET.fromstring(xml_text)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")
        ids = {c.get("id") for c in cells}
        for cell in cells:
            parent = cell.get("parent")
            if parent is not None:
                assert parent in ids, (
                    f"cell {cell.get('id')} parent {parent} 不存在（孤儿）")

    def test_9_parse_diagram_roundtrip_and_escaping(
            self, xml_text: str, branchline_text: str):
        doc = parse_diagram(xml_text)  # 往返解析成功=转义/骨架合法
        assert doc["n_pages"] == 1
        page = doc["pages"][0]
        # 元件框+引脚点+地符号+标题都在 vertex 面；网名出现在 edge value
        values = " ".join(e["value"] for e in page["edges"])
        for net in ("N_A", "N_B", "N_C", "N_D", "N_T1", "N_T2"):
            assert net in values
        # 无裸 & 残留（合法实体形态 &amp;/&#NN; 除外——ET 转义口径；
        # 标签换行落 &#10; 数值实体=合法）
        assert not re.search(r"&(?!amp;|lt;|gt;|quot;|apos;|#\d+;)", xml_text)


# ─── C. 引脚连接完整性 ──────────────────────────────────────────────────────


_PIN_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*\.\d+")


def _pin_connectivity(xml_text: str) -> tuple[list[str], list[str]]:
    """(引脚引用计数恰 1 的违约表, 悬空未标记者表)——验收 C 判据核。"""
    doc = parse_diagram(xml_text)
    page = doc["pages"][0]
    pins = [v for v in page["vertices"] if _PIN_ID_RE.fullmatch(v["id"])]
    refs: dict[str, int] = {}
    for e in page["edges"]:
        for end in ("source", "target"):
            refs[e[end]] = refs.get(e[end], 0) + 1
    bad: list[str] = []
    unmarked: list[str] = []
    for p in pins:
        n = refs.get(p["id"], 0)
        is_marked_dangling = p["attrs"].get("dangling") == "1"
        if is_marked_dangling:
            if n != 0:
                bad.append(p["id"])
        elif n != 1:
            unmarked.append(p["id"])
    return bad, unmarked


class TestPinConnectivity:
    def test_wilkinson_every_pin_exactly_one_edge(self, wilkinson_text: str):
        xml_text = build_schematic_diagram_xml(wilkinson_text)
        bad, unmarked = _pin_connectivity(xml_text)
        assert bad == [] and unmarked == []

    def test_branchline_every_pin_exactly_one_edge(self, branchline_text: str):
        xml_text = build_schematic_diagram_xml(branchline_text)
        bad, unmarked = _pin_connectivity(xml_text)
        assert bad == [] and unmarked == []

    def test_junction_net_spokes(self):
        """≥3 引脚网=汇接点辐条：每引脚恰一条边 + 汇接点带网名标注。"""
        text = (
            "Port:P1  N_A 0 Num=1 Z=50 Ohm Noise=yes\n"
            "Port:P2  N_A 0 Num=2 Z=50 Ohm Noise=yes\n"
            "Port:P3  N_A 0 Num=3 Z=50 Ohm Noise=yes\n"
        )
        plan = build_schematic_plan(text)
        assert plan["nets"][0]["kind"] == "junction"
        xml_text = plan["xml"]
        doc = parse_diagram(xml_text)
        page = doc["pages"][0]
        juncs = [v for v in page["vertices"] if v["id"].startswith("j")]
        assert len(juncs) == 1 and juncs[0]["value"] == "N_A"
        spokes = [e for e in page["edges"] if e["target"] == juncs[0]["id"]]
        assert len(spokes) == 3
        bad, unmarked = _pin_connectivity(xml_text)
        assert bad == [] and unmarked == []

    def test_dangling_pin_explicitly_marked(self):
        """单引脚网=悬空：红虚线引脚点 + dangling="1" 属性 + warnings。"""
        text = (
            "Port:P1  N_A 0 Num=1 Z=50 Ohm Noise=yes\n"
            "TLIN:TL1  N_A N_LONELY Z=50 Ohm E=90 F=2.4 GHz\n"
        )
        plan = build_schematic_plan(text)
        assert plan["n_dangling"] == 1
        assert plan["dangling"] == ["TL1.2"]
        assert any("TL1.2" in w and "悬空" in w for w in plan["warnings"])
        doc = parse_diagram(plan["xml"])
        page = doc["pages"][0]
        pin = next(v for v in page["vertices"] if v["id"] == "TL1.2")
        assert pin["attrs"].get("dangling") == "1"
        assert "dashed=1" in pin["style"]
        bad, unmarked = _pin_connectivity(plan["xml"])
        assert bad == [] and unmarked == []

    def test_ground_stubs_present(self, branchline_text: str):
        plan = build_schematic_plan(branchline_text)
        doc = parse_diagram(plan["xml"])
        page = doc["pages"][0]
        gnd_syms = [v for v in page["vertices"] if v["id"].endswith(".gnd")]
        gnd_edges = [e for e in page["edges"] if e["id"].startswith("g")]
        assert len(gnd_syms) == 4 and len(gnd_edges) == 4
        assert all(v["value"] == "GND" for v in gnd_syms)
        for v in gnd_syms:  # 地符号=元件子 cell（拖元件跟随）
            assert v["parent"] == v["id"].split(".")[0]


# ─── D. 确定性 ──────────────────────────────────────────────────────────────


class TestDeterminism:
    def test_core_two_runs_byte_identical(self, branchline_text: str):
        a = build_schematic_diagram_xml(branchline_text)
        b = build_schematic_diagram_xml(branchline_text)
        assert a == b

    def test_core_plan_echo_deterministic(self, wilkinson_text: str):
        pa = build_schematic_plan(wilkinson_text)
        pb = build_schematic_plan(wilkinson_text)
        assert pa == pb

    def test_service_two_runs_byte_identical_file(self, tmp_path: Path,
                                                  branchline_text: str):
        net = tmp_path / "net.net"
        net.write_text(branchline_text, encoding="ascii")
        out1, out2 = tmp_path / "a.drawio", tmp_path / "b.drawio"
        r1 = generate_schematic_diagram(out1, netlist_path=str(net))
        r2 = generate_schematic_diagram(out2, netlist_path=str(net))
        assert r1["ok"] and r2["ok"]
        assert out1.read_bytes() == out2.read_bytes()

    def test_cli_subprocess_byte_identical(self, tmp_path: Path):
        """CLI 子进程两跑 byte_identical（验收 D 的 CLI 面）。"""
        base = [sys.executable, "-m", "rfauto.cli.main", "diagram", "schematic"]
        params = json.dumps({"sweep": dict(SWEEP), "n_ports": 3, "z0": 50.0})
        outs = []
        for k in (1, 2):
            out = tmp_path / f"cli_{k}.drawio"
            proc = subprocess.run(
                [*base, "--family", "wilkinson_snp", "--snp", "demo.s3p",
                 "--params", params, "--out", str(out), "--json"],
                capture_output=True, text=True, encoding="utf-8",
                timeout=120, cwd=str(tmp_path))
            assert proc.returncode == 0, proc.stderr[-500:]
            outs.append(out.read_bytes())
        assert outs[0] == outs[1]


# ─── 信封 + CLI ─────────────────────────────────────────────────────────────


class TestService:
    def test_family_form_ok_envelope(self, tmp_path: Path):
        out = tmp_path / "schem.drawio"
        result = generate_schematic_diagram(
            out, family="wilkinson_snp", snp_path="demo.s3p",
            params={"sweep": dict(SWEEP), "n_ports": 3, "z0": 50.0})
        assert result["ok"] is True
        assert result["source"] == "family"
        assert result["family"] == "wilkinson_snp"
        assert result["n_components"] == 4 and result["n_ports"] == 3
        assert Path(result["out_path"]).exists()

    def test_family_form_full_params_needs_no_real_snp_file(
            self, tmp_path: Path):
        """sweep+n_ports 完整给出时渲染不读 Touchstone——图面只消费路径文本。"""
        out = tmp_path / "schem.drawio"
        result = generate_schematic_diagram(
            out, family="branchline_cascade", snp_path="not_a_real_file.s4p",
            params={"sweep": dict(SWEEP), "n_ports": 4})
        assert result["ok"] is True, result.get("errors")

    def test_netlist_path_form_ok(self, tmp_path: Path, wilkinson_text: str):
        net = tmp_path / "w.net"
        net.write_text(wilkinson_text, encoding="ascii")
        out = tmp_path / "schem.drawio"
        result = generate_schematic_diagram(out, netlist_path=str(net))
        assert result["ok"] is True
        assert result["source"] == "netlist"
        assert result["family"] is None

    def test_netlist_text_form_ok(self, tmp_path: Path, wilkinson_text: str):
        out = tmp_path / "schem.drawio"
        result = generate_schematic_diagram(out, netlist_text=wilkinson_text)
        assert result["ok"] is True

    def test_missing_netlist_file_error_envelope(self, tmp_path: Path):
        result = generate_schematic_diagram(
            tmp_path / "o.drawio", netlist_path=str(tmp_path / "nope.net"))
        assert result["ok"] is False
        assert "网表文件不存在" in result["errors"][0]

    def test_mutual_exclusion_error(self, tmp_path: Path, wilkinson_text: str):
        result = generate_schematic_diagram(
            tmp_path / "o.drawio", netlist_text=wilkinson_text,
            family="wilkinson_snp", snp_path="x.s3p")
        assert result["ok"] is False
        assert "互斥" in result["errors"][0]

    def test_no_input_error(self, tmp_path: Path):
        result = generate_schematic_diagram(tmp_path / "o.drawio")
        assert result["ok"] is False
        assert "恰给一" in result["errors"][0]

    def test_unknown_family_error(self, tmp_path: Path):
        result = generate_schematic_diagram(
            tmp_path / "o.drawio", family="nope", snp_path="x.s3p")
        assert result["ok"] is False
        assert "未知模板族" in result["errors"][0]

    def test_family_without_snp_error(self, tmp_path: Path):
        result = generate_schematic_diagram(
            tmp_path / "o.drawio", family="wilkinson_snp")
        assert result["ok"] is False
        assert "snp_path" in result["errors"][0]

    def test_missing_out_dir_error(self, tmp_path: Path, wilkinson_text: str):
        result = generate_schematic_diagram(
            tmp_path / "no_such_dir" / "o.drawio",
            netlist_text=wilkinson_text)
        assert result["ok"] is False
        assert "输出目录不存在" in result["errors"][0]

    def test_bad_netlist_propagates_error_envelope(self, tmp_path: Path):
        result = generate_schematic_diagram(
            tmp_path / "o.drawio", netlist_text="GARBAGE")
        assert result["ok"] is False
        assert "无法识别" in result["errors"][0]


class TestCli:
    def _invoke(self, *args: str) -> tuple[int, object, str]:
        result = CliRunner().invoke(root_app, list(args))
        out = result.output or ""
        start = out.find("{")
        payload = json.loads(out[start:]) if start >= 0 else None
        return result.exit_code, payload, out

    def test_leaf_registered(self):
        from typer.main import get_command

        cmd = get_command(root_app)
        assert "schematic" in cmd.commands["diagram"].commands

    def test_json_success(self, tmp_path: Path, branchline_text: str):
        net = tmp_path / "net.net"
        net.write_text(branchline_text, encoding="ascii")
        out = tmp_path / "schem.drawio"
        rc, payload, out_text = self._invoke(
            "diagram", "schematic", "--net", str(net),
            "--out", str(out), "--json")
        assert rc == 0, out_text
        assert payload["ok"] is True
        assert payload["n_components"] == 7
        assert out.exists()

    def test_json_failure_envelope(self, tmp_path: Path):
        rc, payload, out_text = self._invoke(
            "diagram", "schematic", "--net", str(tmp_path / "nope.net"),
            "--out", str(tmp_path / "o.drawio"), "--json")
        assert rc == 1  # service 失败=exit 1（与 usage exit 2 区分；_emit 契约）
        assert payload["ok"] is False
        assert "网表文件不存在" in payload["errors"][0]
        assert "{" in out_text  # --json 下失败路径也必须输出 JSON 信封

    def test_usage_error_net_family_exclusive(self, tmp_path: Path):
        rc, _payload, out_text = self._invoke(
            "diagram", "schematic", "--out", str(tmp_path / "o.drawio"))
        assert rc == 2  # usage 类 exit 2（恰给一门）
        assert "恰给一" in out_text

    def test_rich_path_success(self, tmp_path: Path, wilkinson_text: str):
        net = tmp_path / "net.net"
        net.write_text(wilkinson_text, encoding="ascii")
        out = tmp_path / "schem.drawio"
        result = CliRunner().invoke(
            root_app,
            ["diagram", "schematic", "--net", str(net),
             "--out", str(out)])
        assert result.exit_code == 0, result.output
        assert "引脚级原理图" in result.output
        assert out.exists()
