"""T-O4 ADS 前仿链回路钉（aurora_o，2026-11-01）。

七验收钉（任务书口径）+ spec §6 钉映射（语境钉死
runs/aurora_o/design_specs/T-O4_ADS_UX_SPEC.md）：
1. 图生成 byte-identical + mxGraph 官方九条（id 唯一/基 cell 0,1/每 vertex
   geometry/转义/不压缩）——T-O1 家法（spec 钉 1）；
2. 读回-渲染等价（spec 钉 2）：J2 改 XML 属性 theta 45→55 → 网表含 "E=55"
   逐字断言；不改值时网表与 render_ads_template 直调文本逐字节相同
   （本席零格式化逻辑的证明钉）；
3. 三态优先级（spec 钉 3）：--params > 图值 > 族缺省；effective 逐键带
   来源（input-json/diagram/default）回显；
4. 白名单自证（spec 钉 4，#231 家法参数版）：PARAM_KEYS ==
   inspect.signature(渲染器) 关键字参数集（含 sweep 展开）==
   core.circuit_diagram 布局表键集；家族不匹配/白名单外/图缺 p_ 键负例；
5. 反标注幂等 + 原 cell 零改动 + byte-identical（sim_ref=路径非时间戳）
   （spec 钉 5）；
6. provenance 图版（spec 钉 6）：annot_sim 每数值卡必带 source+sim_ref+
   unit；gate_ok=false 红色样式；NaN 卡 n/a 不出数字；ADS 段失败降级
   error 头卡不虚构指标；
7. 指标单源（spec 钉 7）：图上指标值 == payload_to_network 网络重调
   compute_system_metrics 返回值（.6g 文本化同函数 fmt_value）；
8. 信封与写面（spec 钉 8）：三叶 ok/error 同构；原图只读（hash 前后不变）；
   网表 ASCII 无 BOM（spec 钉 10）；
9. 确定性（任务书钉 7）：同图同 runner 两跑轨迹逐位（J5 同 out_dir 重跑
   逐字节）；
10. CLI 三叶（T-O1 家法）：--json 信封同构 + usage 错误 exit 2 + service
    失败 exit 1（#139 纪律：CLI run 单测 monkeypatch 钉住 hpeesofsim
    通道，禁真打 ADS）。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import skrf
from typer.testing import CliRunner

from rfauto.adapters import ads_netlist
from rfauto.cli.main import app as root_app
from rfauto.core.circuit_diagram import (
    ANNOT_LAYER_ID,
    build_annotated_diagram_xml,
    build_circuit_diagram_xml,
    family_param_keys,
    parse_effective_params,
    read_circuit_params,
)
from rfauto.linkage import ads_circuit as ads_circuit_kernel
from rfauto.linkage import ads_template_family as atf
from rfauto.linkage import field_circuit_anchor as fca
from rfauto.service import ads_template_service as ads_svc
from rfauto.service.circuit_sim_service import (
    METRIC_NAMES,
    PARAM_KEYS,
    annotate_circuit_diagram,
    circuit_sim_run,
    generate_circuit_diagram,
)
from rfauto.service.report_render import fmt_value

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))


def _payload_from_network(net: skrf.Network) -> dict:
    """skrf.Network → ads_netlist.parse_dataset 同形 payload（离线管线替身，
    test_ads_template_family 家法同构）。"""
    n = net.nports
    s = {}
    for i in range(n):
        for j in range(n):
            s[f"{i + 1}_{j + 1}"] = [[float(v.real), float(v.imag)] for v in net.s[:, i, j]]
    return {
        "ok": True, "key": "SP1.SP", "frequency_hz": [float(f) for f in net.f], "s": s,
        "port_names": [f"P{k + 1}" for k in range(n)], "port_z": [[50.0, 0.0]] * n,
    }


@pytest.fixture()
def wilk_s3p(tmp_path: Path) -> Path:
    return atf.build_wilkinson_touchstone(tmp_path / "wilk.s3p", n_points=41)


@pytest.fixture()
def bl_s4p(tmp_path: Path) -> Path:
    return fca.build_branchline_touchstone(tmp_path / "bl.s4p", n_points=41)


def _fake_runner(net: skrf.Network):
    def run(_netlist: Path) -> dict:
        return _payload_from_network(net)
    return run


def _branchline_payload(bl_s4p: Path, **cascade_params) -> dict:
    """branchline 家法替身 payload（test_ads_template_family 同构）：网表拓扑=
    TLIN→SnP(4口)→TLIN，假 payload 必须是**合成级联 2 端口嵌入 4 口**形态
    （裸 4 口 branchline S 矩阵不是网表响应——对拍必炸，#122 不凑绿）。
    cascade_params 覆盖锚缺省（与图值/JSON 三态同参，保证参考一致）。"""
    net4 = skrf.Network(str(bl_s4p))
    d = {**atf.BRANCHLINE_CASCADE_DEFAULTS, **cascade_params}
    ref = fca.compose_reference_cascade(
        net4, f0_hz=float(d["f0_hz"]), theta_in_deg=float(d["theta_in_deg"]),
        theta_out_deg=float(d["theta_out_deg"]), z_line=float(d["z_line"]))
    s4 = np.zeros((ref.f.size, 4, 4), dtype=complex)
    s4[:, :2, :2] = ref.s
    big = skrf.Network(frequency=ref.frequency, s=s4, z0=50)
    return _payload_from_network(big)


def _branchline_runner(bl_s4p: Path, **cascade_params):
    payload = _branchline_payload(bl_s4p, **cascade_params)

    def run(_netlist: Path) -> dict:
        return payload
    return run


def _branchline_values() -> dict[str, str]:
    vals = {k: "" for k in family_param_keys("branchline_cascade")}
    vals.update({"sweep.unit": "GHz", "z0": "50", "f0_hz": "2.4e+09",
                 "z_line": "50", "theta_in_deg": "90", "theta_out_deg": "45"})
    return vals


def _edit_diagram_param(diagram: Path, attr: str, new_text: str) -> Path:
    """J2 模拟：draw.io Edit Data 改 p_* 属性 → 另存新图（原图不动）。"""
    tree = ET.parse(diagram)
    hit = False
    for uo in tree.getroot().iter("UserObject"):
        if uo.get(attr) is not None:
            uo.set(attr, new_text)
            hit = True
    assert hit, f"图中无属性 {attr}（出图面缺键？）"
    out = diagram.with_name(diagram.stem + f"_edit_{attr}.drawio")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


def _drop_diagram_param(diagram: Path, attr: str) -> Path:
    """J2 误删模拟：移除 p_* 属性（图缺 p_ 键负例素材）。"""
    tree = ET.parse(diagram)
    hit = False
    for uo in tree.getroot().iter("UserObject"):
        if uo.get(attr) is not None:
            del uo.attrib[attr]
            hit = True
    assert hit, f"图中无属性 {attr}"
    out = diagram.with_name(diagram.stem + f"_drop_{attr}.drawio")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


def _cell_id_set(xml_text: str) -> set[str]:
    root = ET.fromstring(xml_text)
    return {el.get("id") for el in root.iter() if el.get("id")}


def _attrs_by_id(xml_text: str) -> dict[str, dict[str, str]]:
    root = ET.fromstring(xml_text)
    return {el.get("id"): dict(el.attrib)
            for el in root.iter() if el.get("id") is not None}


# --------------------------------------------------------------------------- #
# 钉 4（前置单源）：白名单自证 + 两表面一致性
# --------------------------------------------------------------------------- #

class TestParamKeysSelfCert:
    """PARAM_KEYS == 渲染器签名关键参集（含 sweep 展开）== core 布局表键集。"""

    @staticmethod
    def _signature_kw(renderer) -> set[str]:
        """渲染器关键字参数集（snp_path=数据路径入参，非可调参数——排除）。"""
        sig = inspect.signature(renderer)
        return {name for name, p in sig.parameters.items()
                if name != "snp_path" and p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD)}

    def test_wilkinson_param_keys_match_renderer_signature(self):
        kw = self._signature_kw(atf.render_wilkinson_snp)
        expanded = {("sweep" if k.startswith("sweep.") else k)
                    for k in PARAM_KEYS["wilkinson_snp"]}
        assert expanded == kw, f"白名单展开 {sorted(expanded)} != 渲染器签名 {sorted(kw)}"

    def test_branchline_param_keys_match_renderer_signature(self):
        kw = self._signature_kw(atf.render_branchline_cascade)
        expanded = {("sweep" if k.startswith("sweep.") else k)
                    for k in PARAM_KEYS["branchline_cascade"]}
        assert expanded <= kw, f"白名单展开 {sorted(expanded)} ⊄ 渲染器签名 {sorted(kw)}"
        # 有意例外（spec §2.3 白名单不含 n_ports）：branchline 渲染器的
        # n_ports 是拓扑核对参数（固定 4 口），上图无意义——签名演化钉=
        # 签名新增可调参数而白名单忘更，即在此红（n_ports 例外收口在下方
        # 集合差，渲染器加新参数必落差集即红）。
        assert kw - expanded == {"n_ports"}, (
            f"渲染器签名出现白名单外新参数 {sorted(kw - expanded)}——"
            "PARAM_KEYS 白名单忘同步（spec 钉 4 自证）")

    def test_param_keys_match_core_layout_tables(self):
        """#231 家法：service 白名单 == core 布局表键集（双表面忘同步即红）。"""
        for family in PARAM_KEYS:
            assert set(family_param_keys(family)) == set(PARAM_KEYS[family]), family

    def test_param_keys_cover_exactly_mvp_families(self):
        assert set(PARAM_KEYS) == set(atf.FAMILIES), "MVP 钉死两族（用户令）"

    def test_metric_names_covered_by_unit_table(self):
        from rfauto.service.circuit_sim_service import _METRIC_UNITS

        for family, names in METRIC_NAMES.items():
            for name in names:
                assert name in _METRIC_UNITS, f"{family} 指标 {name} 缺单位表项"


# --------------------------------------------------------------------------- #
# 钉 1：图生成 byte-identical + mxGraph 官方九条
# --------------------------------------------------------------------------- #

class TestDiagramGeneration:
    def test_deterministic_bytes(self, bl_s4p):
        vals = _branchline_values()
        x1 = build_circuit_diagram_xml("branchline_cascade", vals, n_ports=4, snp_name=bl_s4p.name)
        x2 = build_circuit_diagram_xml("branchline_cascade", vals, n_ports=4, snp_name=bl_s4p.name)
        assert x1 == x2
        assert x1.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_mxgraph_nine_rules(self, bl_s4p):
        """id 唯一 / 基 cell 0,1 / 每 UserObject 有 mxGeometry / 转义正确 /
        未压缩（无 base64 段）/ label 换行 &#10; 实体。"""
        xml_text = build_circuit_diagram_xml(
            "branchline_cascade", _branchline_values(), n_ports=4, snp_name="a b&c.s4p")
        root = ET.fromstring(xml_text)
        assert root.tag == "mxfile"
        model = root.find("diagram").find("mxGraphModel")
        base_cells = model.find("root").findall("mxCell")
        assert {"0", "1"} <= {c.get("id") for c in base_cells}
        ids = [el.get("id") for el in root.iter() if el.get("id")]
        assert len(ids) == len(set(ids)), "id 必须唯一"
        for uo in root.iter("UserObject"):
            assert uo.get("placeholders") == "1"
            assert uo.find("mxCell").find("mxGeometry") is not None
        assert "a b&amp;c.s4p" in xml_text, "文件名特殊字符转义在档"
        assert "base64" not in xml_text, "未压缩原生 mxfile（压缩页显式不支持）"
        assert "&#10;" in xml_text

    def test_port_cards_match_read_n_ports(self, wilk_s3p, tmp_path):
        """spec 钉 12 结构化替身：端口卡数==实读 N（#248 钉图版）。"""
        meta = ads_netlist.snp_meta_for_netlist(wilk_s3p)
        out = tmp_path / "w.drawio"
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, out)
        assert env["ok"] and env["n_ports"] == meta["n_ports"] == 3
        info = read_circuit_params(out.read_text(encoding="utf-8"))
        assert info["n_userobjects"] == 2 + meta["n_ports"]  # setup + snp + N 端口卡
        assert info["family"] == "wilkinson_snp"

    def test_service_generation_envelope_and_values_view(self, bl_s4p, tmp_path):
        out = tmp_path / "gen" / "ckt.drawio"
        out.parent.mkdir(parents=True, exist_ok=True)
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, out)
        assert env["ok"]
        assert env["values"]["theta_in_deg"] == {"value": 90.0, "source": "default"}
        assert env["values"]["sweep.fstart"] == {"value": None, "source": "default"}
        out2 = tmp_path / "gen2" / "c.drawio"
        out2.parent.mkdir(parents=True, exist_ok=True)
        override = generate_circuit_diagram(
            "branchline_cascade", bl_s4p, out2, params={"theta_in_deg": 55})
        assert override["ok"]
        assert override["values"]["theta_in_deg"] == {"value": 55.0, "source": "input-json"}
        info = read_circuit_params(out2.read_text(encoding="utf-8"))
        assert parse_effective_params(info["raw"])["theta_in_deg"] == 55.0

    def test_generation_negatives(self, wilk_s3p, tmp_path):
        r = generate_circuit_diagram("x", wilk_s3p, tmp_path / "a.drawio")
        assert r["ok"] is False and any("未知模板族" in e for e in r["errors"])
        r = generate_circuit_diagram("branchline_cascade", wilk_s3p, tmp_path / "b.drawio")
        assert r["ok"] is False and any("4 端口" in e for e in r["errors"])
        r = generate_circuit_diagram("wilkinson_snp", tmp_path / "no.s3p", tmp_path / "c.drawio")
        assert r["ok"] is False and any("不存在" in e for e in r["errors"])
        r = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "nodir" / "d.drawio")
        assert r["ok"] is False and any("目录不存在" in e for e in r["errors"])
        r = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "e.drawio",
                                     params={"z0": True})
        assert r["ok"] is False and any("bool" in e for e in r["errors"])


# --------------------------------------------------------------------------- #
# 钉 2：读回-渲染等价（J2 改值端到端）
# --------------------------------------------------------------------------- #

class TestReadbackRenderEquivalence:
    def test_edited_value_reaches_netlist_verbatim(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        edited = _edit_diagram_param(tmp_path / "ckt.drawio", "p_theta_in_deg", "55")
        result = circuit_sim_run(edited, snp_path=bl_s4p, out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p, theta_in_deg=55.0))
        assert result["ok"], result
        netlist_text = Path(result["netlist_path"]).read_text(encoding="ascii")
        assert "E=55 " in netlist_text, "J2 改值 45→55 必须逐字进网表（TLIN E=θ）"
        assert "E=90 " not in netlist_text
        assert result["effective"]["theta_in_deg"] == {"value": 55.0, "source": "diagram"}

    def test_unedited_diagram_renders_byte_identical_to_direct_call(self, bl_s4p, tmp_path):
        """不改值时：图→合参→渲染 的网表 == render_ads_template 直调（零
        格式化逻辑证明钉，spec 钉 2 后半）。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p))
        assert result["ok"]
        via_diagram = Path(result["netlist_path"]).read_bytes()
        direct = ads_svc.render_ads_template({
            "family": "branchline_cascade", "snp_path": str(bl_s4p),
            "output_path": str(tmp_path / "direct.txt"),
            "params": {"sweep": {"unit": "GHz"},
                       "z0": 50.0, "f0_hz": 2.4e9, "z_line": 50.0,
                       "theta_in_deg": 90.0, "theta_out_deg": 45.0},
        })
        assert via_diagram == Path(direct["netlist_path"]).read_bytes()

    def test_readback_form_rules(self, bl_s4p, tmp_path):
        """p_ 前缀扫键 / sweep 二级点分组装 / 单位与来源三件组在档。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        info = read_circuit_params((tmp_path / "ckt.drawio").read_text(encoding="utf-8"))
        assert set(info["raw"]) == set(PARAM_KEYS["branchline_cascade"])
        assert info["cells"]["theta_in_deg"] == "uobj_tlin1"
        assert info["cells"]["f0_hz"] == "uobj_setup"
        assert info["units"]["z_line"] == "Ohm" and info["units"]["f0_hz"] == "Hz"
        assert all(v == "input" for v in info["srcs"].values())
        assert "%p_theta_in_deg%" in (tmp_path / "ckt.drawio").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 钉 3：三态优先级
# --------------------------------------------------------------------------- #

class TestThreeStatePriority:
    def test_json_beats_diagram_beats_default(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        # 图值 90（缺省出图），JSON 显式 60 → JSON 胜
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run",
                                 params_override={"theta_in_deg": 60},
                                 runner=_branchline_runner(bl_s4p, theta_in_deg=60.0))
        assert result["ok"]
        assert result["effective"]["theta_in_deg"] == {"value": 60.0, "source": "input-json"}
        netlist_text = Path(result["netlist_path"]).read_text(encoding="ascii")
        assert "E=60 " in netlist_text

    def test_diagram_beats_default_when_json_lacks_key(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        edited = _edit_diagram_param(tmp_path / "ckt.drawio", "p_z_line", "65")
        result = circuit_sim_run(edited, snp_path=bl_s4p, out_dir=tmp_path / "run",
                                 params_override={"f0_hz": 2.6e9},
                                 runner=_branchline_runner(bl_s4p, z_line=65.0, f0_hz=2.6e9))
        assert result["ok"]
        assert result["effective"]["z_line"] == {"value": 65.0, "source": "diagram"}
        assert result["effective"]["f0_hz"] == {"value": 2.6e9, "source": "input-json"}
        # theta_out_deg 图卡承载 45（数值恰=缺省，但来源如实记 diagram——
        # 审计语义：该值确由图面卡携带，"default 胜"的可达态=sweep 缺项，
        # 见 test_sweep_missing_everywhere_falls_back_to_touchstone）
        assert result["effective"]["theta_out_deg"] == {"value": 45.0, "source": "diagram"}
        netlist_text = Path(result["netlist_path"]).read_text(encoding="ascii")
        assert "Z=65 Ohm E=" in netlist_text
        assert "F=2.6 GHz" in netlist_text, "f0 经 sweep 单位制渲染（渲染器单源格式）"

    def test_sweep_missing_everywhere_falls_back_to_touchstone(self, bl_s4p, tmp_path):
        """两者都缺 → 缺省胜（spec 钉 3 第三态；sweep 缺项=随 SnP 频带）。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p))
        assert result["ok"]
        for key in ("sweep.fstart", "sweep.fstop", "sweep.npoints"):
            assert result["effective"][key] == {"value": None, "source": "default"}
        assert result["sweep"]["source"] == "touchstone", "缺项随 SnP 频带"
        assert any("随 SnP 频带" in w for w in result["warnings"])

    def test_explicit_sweep_beats_touchstone_band(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run",
                                 params_override={"sweep": {"fstart": 1.0, "fstop": 4.0, "npoints": 21}},
                                 runner=_branchline_runner(bl_s4p))
        assert result["ok"]
        assert result["sweep"]["source"] == "explicit"
        assert result["effective"]["sweep.fstart"] == {"value": 1.0, "source": "input-json"}


# --------------------------------------------------------------------------- #
# 钉 4 负例：未知族 / 白名单外 / 图缺 p_ 键 / 家族不匹配
# --------------------------------------------------------------------------- #

class TestReadNegatives:
    def test_unknown_family_from_diagram(self, wilk_s3p, tmp_path):
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        tree = ET.parse(tmp_path / "ckt.drawio")
        for uo in tree.getroot().iter("UserObject"):
            if uo.get("family"):
                uo.set("family", "mystery_family")
        bad = tmp_path / "bad.drawio"
        tree.write(bad, encoding="utf-8", xml_declaration=True)
        result = circuit_sim_run(bad, snp_path=wilk_s3p, out_dir=tmp_path / "run",
                                 runner=_fake_runner(skrf.Network(str(wilk_s3p))))
        assert result["ok"] is False
        assert any("未知模板族" in e for e in result["errors"])

    def test_family_mismatch_explicit_arg(self, wilk_s3p, tmp_path):
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                 out_dir=tmp_path / "run", family="branchline_cascade",
                                 runner=_fake_runner(skrf.Network(str(wilk_s3p))))
        assert result["ok"] is False
        assert any("不一致" in e for e in result["errors"])

    def test_whitelist_external_key_warned_and_ignored(self, wilk_s3p, tmp_path):
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        tree = ET.parse(tmp_path / "ckt.drawio")
        for uo in tree.getroot().iter("UserObject"):
            if uo.get("p_z0") is not None:
                uo.set("p_my_note", "自用注记")
        noted = tmp_path / "noted.drawio"
        tree.write(noted, encoding="utf-8", xml_declaration=True)
        result = circuit_sim_run(noted, snp_path=wilk_s3p, out_dir=tmp_path / "run",
                                 runner=_fake_runner(skrf.Network(str(wilk_s3p))))
        assert result["ok"], "白名单外键 warnings 忽略不报错（spec §2.3）"
        assert any("my_note" in w for w in result["warnings"])

    def test_missing_p_key_fails_loud(self, bl_s4p, tmp_path):
        """图缺 p_ 键显式报错（J2 误删防线；不静默兜缺省）。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        dropped = _drop_diagram_param(tmp_path / "ckt.drawio", "p_z_line")
        result = circuit_sim_run(dropped, snp_path=bl_s4p, out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p))
        assert result["ok"] is False
        assert any("图缺必带参数键 'z_line'" in e and "uobj_tlin1" in e
                   for e in result["errors"])

    def test_empty_non_sweep_value_fails_loud(self, bl_s4p, tmp_path):
        """非 sweep 键空串=error（spec §2.4：空串=缺项仅限 sweep）。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        emptied = _edit_diagram_param(tmp_path / "ckt.drawio", "p_theta_out_deg", "")
        result = circuit_sim_run(emptied, snp_path=bl_s4p, out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p))
        assert result["ok"] is False
        assert any("值为空" in e for e in result["errors"])

    def test_conflicting_duplicate_keys_fail(self, wilk_s3p, tmp_path):
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        tree = ET.parse(tmp_path / "ckt.drawio")
        # 在第二张卡（SnP 卡）上添 p_z0 异值 → 同键双卡取值冲突显式报错
        for uo in tree.getroot().iter("UserObject"):
            if uo.get("kind") == "SNP":
                uo.set("p_z0", "60")
        bad = tmp_path / "conflict.drawio"
        tree.write(bad, encoding="utf-8", xml_declaration=True)
        with pytest.raises(ValueError, match="取值冲突"):
            read_circuit_params(bad.read_text(encoding="utf-8"))

    def test_diagram_without_family_attr_fails(self, wilk_s3p, tmp_path):
        """无 family 属性的裸骨架图 → 显式报错（非 rfauto 出图不猜族）。"""
        xml_text = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<mxfile><diagram id="d" name="n">'
            '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            '</root></mxGraphModel></diagram></mxfile>\n')
        bare = tmp_path / "bare.drawio"
        bare.write_text(xml_text, encoding="utf-8")
        result = circuit_sim_run(bare, snp_path=wilk_s3p, out_dir=tmp_path / "run",
                                 runner=_fake_runner(skrf.Network(str(wilk_s3p))))
        assert result["ok"] is False
        assert any("family" in e for e in result["errors"])

    def test_compressed_page_read_fails_explicit(self, tmp_path):
        """draw.io 压缩页（diagram 内 base64，无 mxGraphModel）显式报错。"""
        xml_text = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<mxfile><diagram id="d" name="n">c3ByaW50Q29tcHJlc3NlZA==</diagram></mxfile>\n')
        bad = tmp_path / "compressed.drawio"
        bad.write_text(xml_text, encoding="utf-8")
        with pytest.raises(ValueError, match="压缩页"):
            read_circuit_params(bad.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 钉 5+6：反标注幂等 / 原 cell 零改动 / provenance 图版 / 失败降级
# --------------------------------------------------------------------------- #

class TestBackAnnotation:
    def _run_once(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        return circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                               out_dir=tmp_path / "run",
                               runner=_branchline_runner(bl_s4p))

    def test_idempotent_and_original_cells_untouched(self, bl_s4p, tmp_path):
        result = self._run_once(bl_s4p, tmp_path)
        assert result["ok"]
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        original = (tmp_path / "ckt.drawio").read_text(encoding="utf-8")
        ids_before = _cell_id_set(original)
        ids_after = _cell_id_set(annotated)
        assert ids_before <= ids_after
        added = ids_after - ids_before
        assert added == {ANNOT_LAYER_ID, "sim_h", "sim_m0", "sim_m1", "sim_c"}
        before = _attrs_by_id(original)
        after = _attrs_by_id(annotated)
        for cell_id, attrs in before.items():
            assert after[cell_id] == attrs, f"原 cell {cell_id} 被改动（零改动纪律）"
        # 幂等：对反标注图再跑 annotate（同 result）→ 逐字节同文件
        out2 = tmp_path / "re" / "again.drawio"
        out2.parent.mkdir(parents=True, exist_ok=True)
        env2 = annotate_circuit_diagram(
            Path(result["annotated_diagram_path"]),
            tmp_path / "run" / "branchline_cascade_circuit_result.json", out2)
        assert env2["ok"]
        assert out2.read_bytes() == Path(result["annotated_diagram_path"]).read_bytes()

    def test_annotate_bytes_identical_and_provenance_attrs(self, bl_s4p, tmp_path):
        """byte-identical 钉（sim_ref=路径非时间戳）+ 每卡 source/sim_ref/unit。"""
        result = self._run_once(bl_s4p, tmp_path)
        assert result["ok"]
        result_json = tmp_path / "run" / "branchline_cascade_circuit_result.json"
        out_a = tmp_path / "a.drawio"
        out_b = tmp_path / "b.drawio"
        assert annotate_circuit_diagram(tmp_path / "ckt.drawio", result_json, out_a)["ok"]
        assert annotate_circuit_diagram(tmp_path / "ckt.drawio", result_json, out_b)["ok"]
        assert out_a.read_bytes() == out_b.read_bytes()
        root = ET.fromstring(out_a.read_text(encoding="utf-8"))
        cards = {el.get("id"): el for el in root.iter("UserObject")
                 if (el.get("id") or "").startswith("sim_")}
        assert {"sim_h", "sim_c"} <= set(cards)
        sim_ref_value = cards["sim_h"].get("sim_ref")
        assert sim_ref_value and "T" not in Path(sim_ref_value).name, "sim_ref=路径非时间戳"
        for card_id, card in cards.items():
            assert card.get("source"), f"{card_id} 缺 source"
            assert card.get("sim_ref"), f"{card_id} 缺 sim_ref"
            assert card.get("unit") is not None, f"{card_id} 缺 unit"
        metric_cards = [c for cid, c in cards.items() if cid.startswith("sim_m")]
        assert len(metric_cards) == len(METRIC_NAMES["branchline_cascade"])
        for card in metric_cards:
            assert card.get("value") == fmt_value(float(card.get("value"))), ".6g 同函数"

    def test_metric_values_single_source(self, bl_s4p, tmp_path):
        """钉 7：图上指标值 == 服务同款替身 payload 重调 compute_system_metrics
        （同 payload 同函数同值；spec 钉 7 的"payload_to_network 网络"对应
        branchline=composite_network_from_payload 形态）。"""
        result = self._run_once(bl_s4p, tmp_path)
        assert result["ok"]
        payload = _branchline_payload(bl_s4p)
        net = fca.composite_network_from_payload(payload)
        recomputed = ads_circuit_kernel.compute_system_metrics(
            net, list(METRIC_NAMES["branchline_cascade"]))
        assert result["metrics"] == recomputed
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        for name, value in recomputed.items():
            assert f"{name} = {fmt_value(value)}" in annotated

    def test_gate_fail_renders_red_card(self, wilk_s3p, tmp_path):
        net = skrf.Network(str(wilk_s3p))
        payload = _payload_from_network(net)
        payload["s"]["1_1"][0][0] += 0.1  # 对拍必炸

        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                 out_dir=tmp_path / "run", runner=lambda _p: payload)
        assert result["ok"] is False  # gate 炸=ok False（不凑绿）
        # aurora_p H1 P2-2（B1 F-6 清偿）分派钉：仿真本身成功时文案=对拍门
        # 未过（不共用"ADS 段失败"误导文案——两态工程语义不同）。
        assert "对拍门未过" in result["errors"][0]
        assert "ADS 段失败" not in result["errors"][0]
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "gate_ok=false" in annotated
        assert "fillColor=#f8cecc" in annotated, "gate_ok=false 卡红色样式（钉 6）"

    def test_ads_failure_degrades_to_error_head_card(self, wilk_s3p, tmp_path):
        def boom(_p):
            raise RuntimeError("Linear features are not licensed (0 tokens)")

        # aurora_p H1 P2-2 分派钉（对偶面）：ADS 真失败才报"ADS 段失败"。

        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                 out_dir=tmp_path / "run", runner=boom)
        assert result["ok"] is False
        assert result["ads"]["status"] == "error"
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "status=error" in annotated
        assert "not licensed" in annotated, "错误尾巴引注在卡（#105 溯源）"
        assert "sim_m0" not in annotated, "ADS 段失败不出指标卡（不虚构指标）"
        # 失败 result 也能离线 annotate（降级 error 头卡）
        out = tmp_path / "degraded.drawio"
        env2 = annotate_circuit_diagram(
            tmp_path / "ckt.drawio",
            tmp_path / "run" / "wilkinson_snp_circuit_result.json", out)
        assert env2["ok"] and out.exists()

    def test_nan_metric_card_is_na_without_number(self, bl_s4p, tmp_path):
        """NaN 不上图：非有限指标卡 status=n/a 且无 value 属性（钉 6）。"""
        net4 = skrf.Network(str(bl_s4p))
        payload = _payload_from_network(net4)
        # 注入非有限响应 → system_gain_db=NaN（指标路径单测，不涉真机）
        payload["s"]["2_1"] = [[float("nan"), 0.0]] * len(payload["frequency_hz"])
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run", runner=lambda _p: payload)
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        root = ET.fromstring(annotated)
        na_cards = [el for el in root.iter("UserObject") if el.get("status") == "n/a"]
        assert na_cards, "NaN 指标卡必须存在（n/a 形态）"
        for card in na_cards:
            assert "value" not in card.attrib, "NaN 卡不得带 value 属性（NaN 不上图）"
        assert any("n/a" in (card.get("label") or "") for card in na_cards)


# --------------------------------------------------------------------------- #
# 钉 8+9+10：信封与写面 / 原图只读 / 确定性 / ASCII
# --------------------------------------------------------------------------- #

class TestEnvelopeAndWriteFace:
    def test_original_diagram_readonly_hash(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        before = hashlib.sha256((tmp_path / "ckt.drawio").read_bytes()).hexdigest()
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p))
        assert result["ok"]
        after = hashlib.sha256((tmp_path / "ckt.drawio").read_bytes()).hexdigest()
        assert before == after, "--diagram 只读（原稿是模板）"

    def test_same_run_twice_byte_identical_j5_loop(self, bl_s4p, tmp_path):
        """确定性钉：同图同 runner 两跑（同 out_dir 重跑=J5 迭代形态）逐字节。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        runner = _branchline_runner(bl_s4p)
        r1 = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                             out_dir=tmp_path / "run", runner=runner)
        netlist_1 = Path(r1["netlist_path"]).read_bytes()
        diagram_1 = Path(r1["annotated_diagram_path"]).read_bytes()
        result_1 = (tmp_path / "run" / "branchline_cascade_circuit_result.json").read_bytes()
        r2 = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                             out_dir=tmp_path / "run", runner=runner)
        assert Path(r2["netlist_path"]).read_bytes() == netlist_1
        assert Path(r2["annotated_diagram_path"]).read_bytes() == diagram_1
        assert (tmp_path / "run" / "branchline_cascade_circuit_result.json").read_bytes() == result_1
        assert r1["metrics"] == r2["metrics"]

    def test_netlist_ascii_no_bom(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=bl_s4p,
                                 out_dir=tmp_path / "run",
                                 runner=_branchline_runner(bl_s4p))
        raw = Path(result["netlist_path"]).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), "无 BOM（钉 10）"
        raw.decode("ascii")  # 纯 ASCII（解码失败即红）

    def test_missing_inputs_fail_envelope(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        r = circuit_sim_run(tmp_path / "no.drawio", snp_path=bl_s4p, out_dir=tmp_path / "run")
        assert r["ok"] is False and any("电路图不存在" in e for e in r["errors"])
        r = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=tmp_path / "no.s4p",
                            out_dir=tmp_path / "run")
        assert r["ok"] is False and any("不存在" in e for e in r["errors"])

    def test_wilkinson_chain_end_to_end_metrics(self, wilk_s3p, tmp_path):
        """wilkinson 全链：SnP 直通 payload → 指标（等分 wilkinson 幅值
        −3.01 dB 量级，闭式对照 #118 量级合理性）。"""
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                 out_dir=tmp_path / "run",
                                 runner=_fake_runner(skrf.Network(str(wilk_s3p))))
        assert result["ok"], result
        assert result["compare"]["gate_ok"] is True
        recomputed = ads_circuit_kernel.compute_system_metrics(
            atf.payload_to_network(_payload_from_network(skrf.Network(str(wilk_s3p)))),
            list(METRIC_NAMES["wilkinson_snp"]))
        assert result["metrics"] == recomputed, "指标单源（钉 7）"
        # 带内均值量级合理（|S21| 带内滚落，均值略深于 f0 点值 −3.01 dB）
        assert -4.0 < result["metrics"]["system_gain_db"] < -3.0
        assert result["metrics"]["amplitude_balance_db"] == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# CLI 三叶（T-O1 家法；#139：hpeesofsim 通道 monkeypatch 钉住，禁真打 ADS）
# --------------------------------------------------------------------------- #

class TestCliAdsCircuit:
    @pytest.fixture()
    def patched_ads_channel(self, monkeypatch):
        """钉住 ADS 求解/解析通道（#139：环境存在也不许单测真打 ADS）。

        返回 box：测试先 box["payload"]=... 再调 CLI run；parse 调用计数
        留证（真机链复解析路径的消费面）。
        """
        box: dict = {"payload": None, "calls": {"parse": 0, "sim": 0}}

        def _fake_sim(netlist, ads_dir=None, **_kw):
            box["calls"]["sim"] += 1
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

        def _fake_parse(dataset, ads_dir=None, **_kw):
            box["calls"]["parse"] += 1
            assert box["payload"] is not None, "CLI run 前必须先置 payload"
            return box["payload"]

        monkeypatch.setattr(ads_netlist, "run_hpeesofsim", _fake_sim)
        monkeypatch.setattr(ads_netlist, "parse_dataset", _fake_parse)
        return box

    def test_three_leaves_json_roundtrip(self, wilk_s3p, tmp_path, patched_ads_channel):
        runner = CliRunner()
        patched_ads_channel["payload"] = _payload_from_network(skrf.Network(str(wilk_s3p)))
        # J1 diagram
        r = runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "wilkinson_snp",
            "--snp", str(wilk_s3p), "--out", str(tmp_path / "ckt.drawio"), "--json"])
        assert r.exit_code == 0, r.output
        env = json.loads(r.output)
        assert env["ok"] and env["family"] == "wilkinson_snp"
        # J3+J4 run（真机通道已被钉住→假 payload 走全链，含 .ds 复解析路）
        r2 = runner.invoke(root_app, [
            "ads-circuit", "run", "--diagram", str(tmp_path / "ckt.drawio"),
            "--snp", str(wilk_s3p), "--out-dir", str(tmp_path / "run"), "--json"])
        assert r2.exit_code == 0, r2.output
        env2 = json.loads(r2.output)
        assert env2["ok"], env2
        assert -4.0 < env2["metrics"]["system_gain_db"] < -3.0
        assert env2["compare"]["gate_ok"] is True
        assert patched_ads_channel["calls"]["sim"] == 1
        # 真机链解析×2=编排取数成本（run_ads_template 内部解析 + 指标层
        # 复解析取 payload——既有入口零改动红线的代价，circuit_sim_run
        # docstring 如实声明）；两解析确定性同值（parse_dataset 纯读）
        assert patched_ads_channel["calls"]["parse"] == 2
        # 离线 annotate
        r3 = runner.invoke(root_app, [
            "ads-circuit", "annotate", "--diagram", str(tmp_path / "ckt.drawio"),
            "--result", str(tmp_path / "run" / "wilkinson_snp_circuit_result.json"),
            "--out", str(tmp_path / "out.drawio"), "--json"])
        assert r3.exit_code == 0, r3.output
        env3 = json.loads(r3.output)
        assert env3["ok"] and env3["n_cards"] >= 4

    def test_diagram_leaf_rich_path(self, wilk_s3p, tmp_path):
        runner = CliRunner()
        r = runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "branchline_cascade",
            "--snp", str(wilk_s3p.parent / "no4p.s4p"), "--out",
            str(tmp_path / "x.drawio")])
        assert r.exit_code == 1, "service 失败=exit 1（非 json 路径红字）"

    def test_run_leaf_service_failure_exit_1(self, wilk_s3p, tmp_path):
        runner = CliRunner()
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        r = runner.invoke(root_app, [
            "ads-circuit", "run", "--diagram", str(tmp_path / "ckt.drawio"),
            "--snp", str(tmp_path / "missing.s3p"), "--out-dir", str(tmp_path / "run"),
            "--json"])
        assert r.exit_code == 1, "service 失败=exit 1（usage 与 service 分离）"
        body = json.loads(r.output)
        assert body["ok"] is False and body["errors"]

    def test_usage_error_exit_2(self, wilk_s3p, tmp_path):
        runner = CliRunner()
        r = runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "wilkinson_snp",
            "--snp", str(wilk_s3p), "--out", str(tmp_path / "a.drawio"),
            "--params", "{bad json", "--json"])
        assert r.exit_code == 2, "--params 非法 JSON=usage 类 exit 2"
        r2 = runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "wilkinson_snp",
            "--snp", str(wilk_s3p), "--out", str(tmp_path / "a.drawio"),
            "--params", "@no_such_file.json", "--json"])
        assert r2.exit_code == 2, "@文件不存在=usage 类 exit 2"
        r3 = runner.invoke(root_app, [
            "ads-circuit", "annotate", "--diagram", str(tmp_path / "a.drawio"),
            "--result", str(tmp_path / "a.drawio"), "--out", str(tmp_path / "a.drawio")])
        assert r3.exit_code == 2, "annotate out==diagram 同路径=usage 类 exit 2"

    def test_annotate_rejects_bare_result(self, wilk_s3p, tmp_path):
        """裸 run_ads_template 产物（无 circuit 节）→ 显式报错指引（离线源
        契约）。"""
        runner = CliRunner()
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        bare = tmp_path / "run_bare"
        bare.mkdir()
        (bare / "wilkinson_snp_result.json").write_text(
            json.dumps({"ok": True, "family": "wilkinson_snp"}), encoding="utf-8")
        r = runner.invoke(root_app, [
            "ads-circuit", "annotate", "--diagram", str(tmp_path / "ckt.drawio"),
            "--result", str(bare / "wilkinson_snp_result.json"),
            "--out", str(tmp_path / "x.drawio"), "--json"])
        assert r.exit_code == 1
        body = json.loads(r.output)
        assert any("circuit" in e for e in body["errors"])

    def test_all_three_leaves_have_json_flag(self):
        """新 CLI 叶必带 --json（W3 棘轮门家法的本地替身自证）。"""
        from typer.main import get_command

        from rfauto.cli.domains.ads_circuit import ads_circuit_app

        root = get_command(ads_circuit_app)
        assert hasattr(root, "commands"), "ads-circuit 必须是命令组"
        assert set(root.commands) == {"diagram", "run", "annotate"}
        for name, sub in root.commands.items():
            opts = {opt for p in sub.params for opt in p.opts}
            assert "--json" in opts, f"叶 {name} 缺 --json 旗标（W3 棘轮门同款判据）"


# --------------------------------------------------------------------------- #
# 反标注内核（core 层直钉：幂等删除含 UserObject 包装卡——回归钉）
# --------------------------------------------------------------------------- #

class TestAnnotateKernelIdempotency:
    def test_reannotation_on_annotated_file_no_layer_stack(self, bl_s4p, tmp_path):
        """回归钉：旧层卡=UserObject 包装形态（parent 在内层 mxCell）——
        漏删内层则二次反标注整层堆积（本轮实证 bug 的回归钉）。"""
        env = generate_circuit_diagram("branchline_cascade", bl_s4p, tmp_path / "ckt.drawio")
        assert env["ok"]
        original = (tmp_path / "ckt.drawio").read_text(encoding="utf-8")
        cards = [{
            "id": "sim_h", "label": "head", "style": "s",
            "x": 1060, "y": 40, "width": 340, "height": 104,
            "attrs": {"sim_ref": "r.ds", "unit": "1", "source": "svc"},
        }]
        once = build_annotated_diagram_xml(original, cards)
        twice = build_annotated_diagram_xml(once, cards)
        assert once == twice, "二次反标注必须幂等（旧层卡整层替换）"
        layer_cells = [el for el in ET.fromstring(twice).iter("mxCell")
                       if el.get("id") == ANNOT_LAYER_ID]
        assert len(layer_cells) == 1
