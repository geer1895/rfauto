"""aurora_o 开放池席 o_ads 回归钉（2026-11-01）：ADS 链遗留修复+MCP 补齐四件。

四件钉（任务书口径；变异证据 runs/aurora_o/o_ads/mutation_evidence.txt）：

- 件1 rich escape：ads-circuit diagram/run 两叶人读分支的来源标签
  ``[default]``/``[diagram]``/``[input-json]`` 此前被 rich 当样式标签整段
  吞掉（实测三形态 print 全渲染为空）——stackup 叶 escape 家法回显；
  diagram 组 help 只述 link→四叶全述（D-06 字符纪律本地同守）；
- 件2 来源名统一：J1 出图 override 原记 "params-json"、run 三态记
  "input-json"——spec §3.1 钉死词表 input-json/diagram/default，J1 并入
  单源（消费端零分叉）；
- 件3 设计报告 §④：T-O4 已落——占位文案改 annot_sim 反标注图实际接入
  （``*_circuit.drawio`` 只读扫描+attachments 追加+相对链接引用；未命中
  如实生成入口指引）；md 正文零 run 绝对路径（头部 run 目录行+§⑥
  ``reports render`` 命令两处改 ``runs/<run_id>`` 相对形态，外发安全）；
- 件4 MCP 两工具：ads_circuit_diagram/ads_circuit_run（T-O4_ADS_UX_SPEC
  §5.1 v1 列项）——注册/转发/e2e（fake runner=ads_netlist 求解缝双钉，
  test_circuit_sim_service::patched_ads_channel 家法）三面。

全局计数（164 主钉）/双检（#270）由 test_mcp_server/test_mcp_em_family/
test_cli_registration_order/test_mcp_tool_consistency 邻接覆盖，本件不重
复硬数。
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import skrf
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.core.circuit_diagram import (
    ANNOT_LAYER_ID,
    build_circuit_diagram_xml,
    family_param_keys,
    write_circuit_xml,
)
from rfauto.linkage import ads_template_family as atf
from rfauto.linkage import field_circuit_anchor as fca
from rfauto.service.circuit_sim_service import (
    annotate_circuit_diagram,
    circuit_sim_run,
    generate_circuit_diagram,
)
from rfauto.service.design_replay_report import (
    build_design_report_model,
    generate_design_report,
    render_design_report_md,
)

src_dir = Path(__file__).resolve().parents[2] / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_TUT = _REPO_ROOT  # 教程词形审计基准根（TestB1TutorialWordform 消费）


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """cwd 隔离单源委托（tests/conftest.py::isolated，#144 家法）。"""
    yield


def _payload_from_network(net: skrf.Network) -> dict:
    """skrf.Network → ads_netlist.parse_dataset 同形 payload（离线管线替身，
    test_circuit_sim_service 家法同构）。"""
    n = net.nports
    s = {}
    for i in range(n):
        for j in range(n):
            s[f"{i + 1}_{j + 1}"] = [[float(v.real), float(v.imag)]
                                     for v in net.s[:, i, j]]
    return {
        "ok": True, "key": "SP1.SP",
        "frequency_hz": [float(f) for f in net.f], "s": s,
        "port_names": [f"P{k + 1}" for k in range(n)],
        "port_z": [[50.0, 0.0]] * n,
    }


@pytest.fixture()
def wilk_s3p(tmp_path: Path) -> Path:
    return atf.build_wilkinson_touchstone(tmp_path / "wilk.s3p", n_points=41)


@pytest.fixture()
def bl_s4p(tmp_path: Path) -> Path:
    return fca.build_branchline_touchstone(tmp_path / "bl.s4p", n_points=41)


@pytest.fixture()
def patched_ads_channel(monkeypatch):
    """ads_netlist 求解缝双钉（fake runner e2e 通道；test_circuit_sim_service
    同名家法）：run_hpeesofsim→回执 0、parse_dataset→脚本化 payload。"""
    from rfauto.adapters import ads_netlist

    box: dict = {"calls": {"sim": 0, "parse": 0}, "payload": None}

    def _fake_sim(netlist, ads_dir=None, **_kw):
        box["calls"]["sim"] += 1
        return subprocess.CompletedProcess(args=[], returncode=0,
                                           stdout="ok", stderr="")

    def _fake_parse(dataset, ads_dir=None, **_kw):
        box["calls"]["parse"] += 1
        assert box["payload"] is not None, "先置 payload 再走求解链"
        return box["payload"]

    monkeypatch.setattr(ads_netlist, "run_hpeesofsim", _fake_sim)
    monkeypatch.setattr(ads_netlist, "parse_dataset", _fake_parse)
    return box


def _write_min_run(run: Path) -> None:
    """最小优化族 run（trials+meta+recipe 快照；无 chain 数据→§④ 链路级
    missing，ADS 行独立可断）。"""
    (run / "trials").mkdir(parents=True)
    for i in range(3):
        (run / "trials" / f"trial_{i}.json").write_text(json.dumps({
            "trial_number": i, "params": {"x_mm": float(i)},
            "metrics": {}, "cost": float(3 - i)}), encoding="utf-8")
    (run / "meta.json").write_text(
        json.dumps({"run_id": run.name, "status": "finished"}),
        encoding="utf-8")
    (run / "recipe.snapshot.yaml").write_text(
        "params: {}\n"
        "optimization:\n  params:\n    x_mm: {low: 0.0, high: 3.0}\n"
        "objectives: []\n", encoding="utf-8")


def _write_sim_circuit(run: Path, family: str = "wilkinson_snp") -> Path:
    """湖面放一份 ads-circuit 出图产物（内核装配真产物，非手写字面）。"""
    vals = {k: "" for k in family_param_keys(family)}
    vals.update({"sweep.unit": "GHz", "z0": "50",
                 "n_ports": "3" if family == "wilkinson_snp" else "4"})
    n_ports = 3 if family == "wilkinson_snp" else 4
    xml_text = build_circuit_diagram_xml(family, vals, n_ports=n_ports,
                                         snp_name="ref.sNp")
    out = run / f"{family}_circuit.drawio"
    write_circuit_xml(xml_text, out)
    return out


# ── 件1：rich escape 来源标签 + diagram 组 help 四叶全述 ────────────────────


class TestRichEscapeSourceTags:
    def test_diagram_leaf_source_tags_literal(self, bl_s4p, tmp_path):
        """J1 人读分支：override 键记 [input-json]、其余 [default]——两形态
        都必须字面在输出（此前被 rich 当样式标签吞成空）。"""
        runner = CliRunner()
        r = runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "branchline_cascade",
            "--snp", str(bl_s4p), "--out", str(tmp_path / "ckt.drawio"),
            "--params", json.dumps({"theta_in_deg": 55})])
        assert r.exit_code == 0, r.output[:400]
        assert "[input-json]" in r.output, (
            "来源标签被 rich 吞掉（escape 缺失即此红）")
        assert "[default]" in r.output

    def test_run_leaf_source_tags_literal(self, wilk_s3p, tmp_path,
                                          patched_ads_channel):
        """run 人读分支：三态来源标签逐键字面回显
        （[input-json]/[diagram]/[default] 三形态齐）。"""
        patched_ads_channel["payload"] = _payload_from_network(
            skrf.Network(str(wilk_s3p)))
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p,
                                       tmp_path / "ckt.drawio")
        assert env["ok"]
        runner = CliRunner()
        r = runner.invoke(root_app, [
            "ads-circuit", "run", "--diagram", str(tmp_path / "ckt.drawio"),
            "--snp", str(wilk_s3p), "--out-dir", str(tmp_path / "run"),
            "--params", json.dumps({"z0": 48.0})])
        assert r.exit_code == 0, r.output[:400]
        assert "[input-json]" in r.output
        assert "[diagram]" in r.output, "图值来源标签被 rich 吞掉"
        assert "[default]" in r.output
        # 反标注图行在位（人读主出口）
        assert "反标注图" in r.output

    def test_diagram_group_help_describes_all_four_leaves(self):
        """diagram 组 help 只述 link→四叶全述（件1 后半；D-06 字符纪律
        本地同守：组 help 零裸 [ 零 %，--help 渲染零异常）。"""
        from typer.main import get_command

        from rfauto.cli.domains.diagram import diagram_app

        root = get_command(diagram_app)
        help_text = str(root.help or "")
        for leaf in ("link", "testsetup", "annotate", "stackup"):
            assert leaf in help_text, f"组 help 缺叶 {leaf}（只述 link 旧文案）"
        assert "[" not in help_text, "D-06：组 help 零裸 ["
        assert help_text.replace("%%", "").count("%") == 0, "D-06：零裸 %"
        r = CliRunner().invoke(root_app, ["diagram", "--help"])
        assert r.exit_code == 0, r.output[:400]


# ── 件2：来源名统一（spec §3.1 词表单源）────────────────────────────────────


class TestSourceNameUnified:
    def test_j1_override_source_is_input_json(self, bl_s4p, tmp_path):
        env = generate_circuit_diagram(
            "branchline_cascade", bl_s4p, tmp_path / "a.drawio",
            params={"theta_in_deg": 55.0})
        assert env["ok"]
        assert env["values"]["theta_in_deg"] == {
            "value": 55.0, "source": "input-json"}
        assert env["values"]["z0"]["source"] == "default"

    def test_j1_and_run_share_source_vocabulary(self, wilk_s3p, tmp_path,
                                                patched_ads_channel):
        """J1 出图与 run 三态同词表（input-json/diagram/default）——
        params-json 并入后全链零第二词形。"""
        patched_ads_channel["payload"] = _payload_from_network(
            skrf.Network(str(wilk_s3p)))
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p,
                                       tmp_path / "ckt.drawio",
                                       params={"z0": 48.0})
        assert env["ok"]
        vocab_j1 = {v["source"] for v in env["values"].values()}
        assert vocab_j1 <= {"input-json", "diagram", "default"}

        payload = patched_ads_channel["payload"]
        run_env = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                  out_dir=tmp_path / "run",
                                  runner=lambda _p: payload)
        assert run_env["ok"], run_env
        vocab_run = {v["source"] for v in run_env["effective"].values()}
        assert vocab_run <= {"input-json", "diagram", "default"}
        dump = json.dumps({"j1": env["values"], "run": run_env["effective"]})
        assert "params-json" not in dump, (
            "params-json 旧词形残留（件2 单源破约即红）")


# ── 件3：设计报告 §④ annot_sim 接入 + md 零绝对路径 ─────────────────────────


class TestReportAdsSimIntegration:
    def test_annot_sim_circuit_detected_and_linked(self, tmp_path):
        run = tmp_path / "run_ads"
        _write_min_run(run)
        circuit = _write_sim_circuit(run)

        model = build_design_report_model(run, with_diagrams=True)
        ads_sim = model["diagrams"]["ads_sim"]
        assert ads_sim["status"] == "ok"
        assert ads_sim["n_circuits"] == 1
        assert ads_sim["names"] == [circuit.name]
        assert ads_sim["source"], "ads_sim 数值节点必带 source（provenance）"
        # attachments：链路图缺席时 ADS 反标注图是唯一附件（T-O9 相对面同构）
        atts = model["diagrams"]["attachments"]
        assert [a["name"] for a in atts] == [circuit.name]
        assert atts[0]["rel_path"] == circuit.name
        assert str(circuit) == atts[0]["path"]  # 模型面保留原文
        # 渲染面：annot_sim 引用行+相对链接（零 T-O4 占位文案残留）
        md = render_design_report_md(model)
        assert "annot_sim 指标层" in md, (
            "_ads_sim_line ok 分支未渲染（ads_sim 接入失效即此红）")
        assert "1 张" in md
        assert f"[{circuit.name}]({circuit.name})" in md
        assert "T-O4 落地后接入" not in md

    def test_missing_circuit_gets_honest_entry_pointer(self, tmp_path):
        run = tmp_path / "run_plain"
        _write_min_run(run)
        model = build_design_report_model(run, with_diagrams=True)
        assert model["diagrams"]["ads_sim"]["status"] == "missing"
        assert model["diagrams"]["attachments"] == []
        md = render_design_report_md(model)
        assert "ads-circuit run" in md and "ads-circuit diagram" in md, (
            "未命中必须给生成入口指引（如实降级不占位）")
        assert "T-O4 落地后接入" not in md

    def test_md_body_zero_absolute_run_path_two_places(self, tmp_path):
        """外发安全两处钉：头部 run 目录行与 §⑥ reports render 命令零绝对
        路径（相对形态 runs/<run_id>；模型面 run_ref.run_dir 保留原文）。"""
        run = tmp_path / "run_leak"
        _write_min_run(run)
        env = generate_design_report(str(run))
        assert env["ok"], env
        md = Path(env["report"]).read_text(encoding="utf-8")
        assert str(run) not in md, "头部 run 目录行泄漏绝对路径"
        assert f"runs/{run.name}" in md, "相对形态 runs/<run_id> 未渲染"
        assert f"rfauto reports render runs/{run.name}" in md, (
            "§⑥ reports render 命令仍带绝对 run_dir")
        assert "reports render " not in md.replace(
            f"rfauto reports render runs/{run.name}", ""), (
            "§⑥ 出现第二形态 reports render 命令")
        # 模型面原文保留（数据完整性与 md 外发面分离）
        model = build_design_report_model(run, with_diagrams=True)
        assert model["run_ref"]["run_dir"] == str(run)

    def test_skipped_diagrams_disables_ads_scan_too(self, tmp_path):
        run = tmp_path / "run_skip"
        _write_min_run(run)
        (run / "x_circuit.drawio").write_text("<mxfile/>", encoding="utf-8")
        model = build_design_report_model(run, with_diagrams=False)
        assert model["diagrams"]["status"] == "skipped"
        assert model["diagrams"]["ads_sim"]["status"] == "skipped"
        assert model["diagrams"]["attachments"] == []


# ── 件4：MCP 两工具（注册/转发/e2e fake runner）─────────────────────────────


def _tool(name: str):
    import asyncio

    from rfauto.mcp_server import mcp as server

    return {t.name: t for t in asyncio.run(server.list_tools())}[name]


class TestMcpAdsToolsRegistration:
    @pytest.mark.parametrize("name", ["ads_circuit_diagram",
                                      "ads_circuit_run"])
    def test_registered_with_schema_and_description(self, name):
        tool = _tool(name)
        assert tool.description.strip()
        schema = (tool.parameters or {}).get("properties") or {}
        assert schema, f"{name} schema 空"

    def test_required_params_pin(self):
        assert set(_tool("ads_circuit_diagram").parameters["required"]) == {
            "family", "snp", "out"}
        assert set(_tool("ads_circuit_run").parameters["required"]) == {
            "diagram", "snp", "out_dir"}

    def test_annotate_leaf_present_v2_extension(self):
        """annotate 叶 v2 扩展位落位（aurora_p 席 B2，2026-11-01）。

        v1 曾钉 annotate 不上 MCP 最小面；本钉随 aurora_p B2 翻转——
        离线反标注（annotate）与 diagram/run 同为 ads-circuit 域 MCP 面。
        aurora_p B1 补 curves 形参（B4 遗留④：签名加参透传 service，
        非新工具；required 面不变）。
        """
        import asyncio

        from rfauto.mcp_server import mcp as server

        tools = {t.name: t for t in asyncio.run(server.list_tools())}
        tool = tools.get("ads_circuit_annotate")
        assert tool is not None, (
            "annotate 叶应在册（aurora_p 席 B2 v2 扩展位落位）")
        assert tool.description.strip()
        schema = (tool.parameters or {}).get("properties") or {}
        assert set(schema) == {"diagram", "result", "out", "curves"}, (
            "schema 键面漂移（B1 遗留④ curves 形参应入 schema）")
        assert set(tool.parameters["required"]) == {"diagram", "result", "out"}
        assert schema["curves"].get("description"), (
            "curves 参数 schema description 空（描述单源门 dim3）")


class TestMcpAdsToolsForwarding:
    def test_diagram_forwards_kwargs_verbatim(self, monkeypatch, tmp_path):
        box: dict = {}

        def _fake_gen(family, snp, out, *, params=None, title=None):
            box.update({"family": family, "snp": snp, "out": out,
                        "params": params, "title": title})
            return {"ok": True, "out_path": out}

        import rfauto.service.circuit_sim_service as svc

        monkeypatch.setattr(svc, "generate_circuit_diagram", _fake_gen)
        out = _tool("ads_circuit_diagram").fn(
            family="wilkinson_snp", snp="w.s3p",
            out=str(tmp_path / "o.drawio"), params={"z0": 48.0}, title="t")
        assert out["ok"] is True
        assert box == {"family": "wilkinson_snp", "snp": "w.s3p",
                       "out": str(tmp_path / "o.drawio"),
                       "params": {"z0": 48.0}, "title": "t"}

    def test_run_forwards_kwargs_verbatim(self, monkeypatch, tmp_path):
        box: dict = {}

        def _fake_run(diagram, *, snp_path, out_dir, params_override=None,
                      family=None, ads_dir=None, compare=True, gate=None):
            box.update({"diagram": diagram, "snp_path": snp_path,
                        "out_dir": out_dir,
                        "params_override": params_override,
                        "family": family, "ads_dir": ads_dir,
                        "compare": compare, "gate": gate})
            return {"ok": True}

        import rfauto.service.circuit_sim_service as svc

        monkeypatch.setattr(svc, "circuit_sim_run", _fake_run)
        out = _tool("ads_circuit_run").fn(
            diagram="c.drawio", snp="w.s3p", out_dir=str(tmp_path / "run"),
            params={"z0": 48.0}, family="wilkinson_snp", ads_dir="E:/ADS",
            compare=False, gate=1e-4)
        assert out["ok"] is True
        assert box == {"diagram": "c.drawio", "snp_path": "w.s3p",
                       "out_dir": str(tmp_path / "run"),
                       "params_override": {"z0": 48.0},
                       "family": "wilkinson_snp", "ads_dir": "E:/ADS",
                       "compare": False, "gate": 1e-4}

    def test_service_exception_becomes_error_envelope(self, monkeypatch):
        import rfauto.service.circuit_sim_service as svc

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(svc, "generate_circuit_diagram", _boom)
        out = _tool("ads_circuit_diagram").fn(family="x", snp="y", out="z")
        assert out["ok"] is False
        assert any("RuntimeError: boom" in str(e) for e in out["errors"])


class TestMcpAdsToolsEndToEnd:
    """e2e：MCP diagram 工具 → MCP run 工具（fake runner=ads_netlist 求解缝
    双钉）→ 真渲染器/真指标内核/真对拍/真反标注全链。"""

    def test_diagram_then_run_full_chain(self, wilk_s3p, tmp_path,
                                         patched_ads_channel):
        patched_ads_channel["payload"] = _payload_from_network(
            skrf.Network(str(wilk_s3p)))
        t_diagram = _tool("ads_circuit_diagram")
        env = t_diagram.fn(family="wilkinson_snp", snp=str(wilk_s3p),
                           out=str(tmp_path / "ckt.drawio"),
                           params={"z0": 48.0})
        assert env["ok"] is True, env
        assert env["values"]["z0"] == {"value": 48.0, "source": "input-json"}
        ET.parse(tmp_path / "ckt.drawio")  # 产物=合法 XML

        t_run = _tool("ads_circuit_run")
        run_env = t_run.fn(diagram=str(tmp_path / "ckt.drawio"),
                           snp=str(wilk_s3p),
                           out_dir=str(tmp_path / "run"),
                           params={"z0": 48.0})
        assert run_env["ok"] is True, run_env
        assert -4.0 < run_env["metrics"]["system_gain_db"] < -3.0
        assert run_env["compare"]["gate_ok"] is True
        assert run_env["effective"]["z0"]["source"] == "input-json"
        # fake runner 走了真求解缝（sim×1 + 指标层复解析×2——既有入口零改动
        # 红线的编排取数成本，test_circuit_sim_service 家法同账）
        assert patched_ads_channel["calls"] == {"sim": 1, "parse": 2}
        # 产物面：circuit_result + annot_sim 反标注图在 out_dir
        result_file = tmp_path / "run" / "wilkinson_snp_circuit_result.json"
        annot_file = tmp_path / "run" / "wilkinson_snp_circuit.drawio"
        assert result_file.is_file() and annot_file.is_file()
        result_doc = json.loads(result_file.read_text(encoding="utf-8"))
        assert (result_doc["circuit"]["metrics"]["system_gain_db"]
                == run_env["metrics"]["system_gain_db"])
        annot_xml = annot_file.read_text(encoding="utf-8")
        assert any(el.get("id") == ANNOT_LAYER_ID
                   for el in ET.fromstring(annot_xml).iter("mxCell"))
        # 离线 annotate 叶消费同一 result（回路闭环，CLI 叶同源语义）
        ann_env = annotate_circuit_diagram(
            tmp_path / "ckt.drawio", result_file, tmp_path / "reann.drawio")
        assert ann_env["ok"] is True and ann_env["n_cards"] >= 4

    def test_diagram_unknown_family_negative_envelope(self, wilk_s3p,
                                                      tmp_path):
        out = _tool("ads_circuit_diagram").fn(
            family="hb_pa_template", snp=str(wilk_s3p),
            out=str(tmp_path / "x.drawio"))
        assert out["ok"] is False
        assert any("未知模板族" in str(e) for e in out["errors"])
        assert not (tmp_path / "x.drawio").exists()

    def test_run_missing_diagram_negative_envelope(self, wilk_s3p, tmp_path):
        out = _tool("ads_circuit_run").fn(
            diagram=str(tmp_path / "nope.drawio"), snp=str(wilk_s3p),
            out_dir=str(tmp_path / "run"))
        assert out["ok"] is False and out["errors"]


# ── aurora_p 席 B1 遗留清偿钉（四族 help/annotate escape/教程词形） ─────────


class TestB1FourFamilyWordface:
    """遗留①：ads-circuit 四族（A2 落 active_chain_sparam/loadpull_hb 后
    CLI help/MCP 描述残留“MVP 钉死两族”旧口径——四族口径全面对齐）。"""

    def test_diagram_family_help_names_all_four(self):
        r = CliRunner().invoke(root_app, ["ads-circuit", "diagram", "--help"])
        assert r.exit_code == 0, r.output[:400]
        for fam in ("wilkinson_snp", "branchline_cascade",
                    "active_chain_sparam", "loadpull_hb"):
            assert fam in r.output, f"--family help 缺族名 {fam}"
        assert "钉死两族" not in r.output, "旧口径“MVP 钉死两族”残留"
        # D-06 本地同守：help 渲染零异常（含裸 [/​% 即渲染炸的旧坑）
        assert r.output

    def test_module_docstring_four_families(self):
        import rfauto.cli.domains.ads_circuit as mod

        assert mod.__doc__ is not None
        assert "钉死两族" not in mod.__doc__, "模块 docstring 旧口径残留"
        assert "active_chain_sparam" in mod.__doc__
        assert "loadpull_hb" in mod.__doc__

    def test_mcp_ads_tool_desc_payload_discipline(self):
        """三工具描述：四族口径+载荷纪律 <350（o_ads 家法推广到全域）。"""
        for name in ("ads_circuit_diagram", "ads_circuit_run",
                     "ads_circuit_annotate"):
            desc = _tool(name).description
            assert len(desc) < 350, f"{name} 描述 {len(desc)} 字符 ≥350"
        assert "钉死两族" not in _tool("ads_circuit_diagram").description
        assert "四族" in _tool("ads_circuit_diagram").description

    def test_mcp_annotate_curves_param_schema(self, monkeypatch):
        """遗留④：MCP annotate curves 形参（签名加参非新工具；required
        面不变；schema 带描述=描述单源门 dim3）。"""
        tool = _tool("ads_circuit_annotate")
        props = (tool.parameters or {}).get("properties") or {}
        assert set(props) == {"diagram", "result", "out", "curves"}
        assert set(tool.parameters["required"]) == {"diagram", "result", "out"}
        assert props["curves"].get("description")
        # 转发直通：curves=True → service with_curves=True
        box: dict = {}

        def _fake_ann(diagram, result, out, *, with_curves=False):
            box["with_curves"] = with_curves
            return {"ok": True, "out_path": out, "n_cards": 1}

        import rfauto.service.circuit_sim_service as svc

        monkeypatch.setattr(svc, "annotate_circuit_diagram", _fake_ann)
        out = _tool("ads_circuit_annotate").fn(
            diagram="c.drawio", result="r.json", out="a.drawio",
            curves=True)
        assert out["ok"] is True
        assert box["with_curves"] is True


class TestB1AnnotateRichEscape:
    """遗留②：annotate 叶人读分支 rich escape（o_ads 修了 diagram/run 两
    叶，本叶 out_path 此前未 escape——路径含 "[...]" 形态段时被 rich 当
    样式标签吞段）。"""

    def test_annotate_out_path_with_bracket_segment_literal(
            self, wilk_s3p, tmp_path):
        diagram = tmp_path / "ckt.drawio"
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, diagram)
        assert env["ok"]
        result = tmp_path / "wilkinson_snp_circuit_result.json"
        result.write_text(json.dumps({
            "family": "wilkinson_snp",
            "circuit": {
                "family": "wilkinson_snp",
                "sim_ref": "ref", "metric_source": "sparams",
                "metric_names": ["system_gain_db"],
                "metrics": {"system_gain_db": -3.2},
            },
            "ads": {"status": "ok"},
            "compare": {"status": "skipped"},
        }, indent=1), encoding="utf-8")
        out = tmp_path / "annot[demo].drawio"  # 路径含 rich 标签形态段
        r = CliRunner().invoke(root_app, [
            "ads-circuit", "annotate", "--diagram", str(diagram),
            "--result", str(result), "--out", str(out)])
        assert r.exit_code == 0, r.output[:400]
        assert "[demo]" in r.output, (
            "annotate out_path 被 rich 吞段（escape 缺失即此红）")
        assert out.is_file()


class TestB1TutorialWordform:
    """遗留③+⑤：教程来源标签词形 params-json→input-json 单源同步
    （docs/tutorials 与 docs_site 镜像同笔）+zh/en 命令表逐字一致审计。"""

    TUTORIAL_PAIRS = (
        ("docs/tutorials/circuit_diagrams_and_reports.md",
         "docs/tutorials/circuit_diagrams_and_reports_en.md"),
        ("docs/tutorials/design_report.md",
         "docs/tutorials/design_report_en.md"),
    )

    @staticmethod
    def _bash_blocks(text: str) -> list[str]:
        import re

        return re.findall(r"```bash\n(.*?)```", text, re.S)

    @staticmethod
    def _commands(block: str) -> list[str]:
        """bash 块 → 命令行清单（续行接驳+注释剔除——zh/en 注释语言不同，
        命令本身必须逐字一致）。"""
        import re

        lines = []
        for line in block.splitlines():
            if line.lstrip().startswith("#"):
                continue
            lines.append(re.sub(r"\s+#.*$", "", line))
        joined = re.sub(r"\\\n\s*", " ", "\n".join(lines))
        return [seg for seg in (s.strip() for s in joined.splitlines()) if seg]

    def test_source_label_wordform_input_json_single_source(self):
        """词形残留清零：docs/tutorials 与 docs_site 镜像零 params-json；
        电路图教程（params-json 原生出处）input-json 在位（J1/run 同词
        表，o_ads 件2 单源）。"""
        circuit_zh, circuit_en = self.TUTORIAL_PAIRS[0]
        for pair in self.TUTORIAL_PAIRS:
            for rel in pair:
                text = (_REPO_TUT / rel).read_text(encoding="utf-8")
                assert "params-json" not in text, f"{rel} 旧词形残留"
        for rel in (circuit_zh, circuit_en):
            text = (_REPO_TUT / rel).read_text(encoding="utf-8")
            assert "input-json" in text, f"{rel} 缺新词形"

    def test_docs_site_mirror_synced(self):
        """docs_site 镜像同笔再生（build_docs_pages 再生面零漂移的字面
        抽钉——镜像与源同改）。"""
        for pair in self.TUTORIAL_PAIRS:
            for rel in pair:
                mirror = _REPO_TUT / "docs_site" / rel.removeprefix("docs/")
                assert mirror.is_file(), f"docs_site 镜像缺 {rel}"
                assert "params-json" not in mirror.read_text(encoding="utf-8")

    def test_zh_en_command_blocks_verbatim(self):
        """zh/en 双篇命令表逐字一致（续行接驳+注释剔除后逐块逐命令比对；
        circuit_diagrams_and_reports 11 块/design_report 2 块全同）。"""
        for zh_rel, en_rel in self.TUTORIAL_PAIRS:
            zh = (_REPO_TUT / zh_rel).read_text(encoding="utf-8")
            en = (_REPO_TUT / en_rel).read_text(encoding="utf-8")
            blocks_zh = self._bash_blocks(zh)
            blocks_en = self._bash_blocks(en)
            assert len(blocks_zh) == len(blocks_en), (
                f"{zh_rel} bash 块数 {len(blocks_zh)} ≠ en {len(blocks_en)}")
            for i, (bz, be) in enumerate(
                    zip(blocks_zh, blocks_en, strict=True)):
                assert self._commands(bz) == self._commands(be), (
                    f"{zh_rel} bash 块 {i} 命令表与 en 不一致（词形/结构"
                    "改动后必须双篇同笔）")
