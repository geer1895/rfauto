"""aurora_p 席 B2 新 MCP 工具钉子测试：ads_circuit_annotate + design_report。

计数 164→166（2026-11-01）：
- ads_circuit_annotate：CLI ads-circuit annotate 叶同源离线反标注
  （零逻辑转发 circuit_sim_service.annotate_circuit_diagram——annotate
  叶 v2 扩展位落位，原 v1「不上 MCP 最小面」钉随本席翻转，
  test_aurora_o_ads_polish 同笔）；
- design_report：CLI design-report 叶同源设计回放报告
  （零逻辑转发 design_replay_report.generate_design_report）。

覆盖面（任务书 §3 验收 C/D）：
- 注册面：两工具在册+schema 非空+描述载荷纪律 <350 字符（o_ads 家法：
  run 描述 494→347 收紧先例）+required 参数钉；
- 转发直通（零业务逻辑红线）：kwargs 逐字透传 + service 异常 →
  error 信封（信封构造器出口，#105）；
- e2e 最小链：annotate 用 tmp 骨架图+fake circuit_result JSON（含
  circuit 节）；design_report 用 tmp A 族假 run 档——isolated fixture
  chdir 隔离零 runs/ 湖写（#144 家法）；
- 负例：缺文件/缺 circuit 节/run 不存在 → ok=False 信封；
- 域映射：mcp_interop_matrix 两新工具落域（total/closed 面
  test_w5_d_fe2 邻接覆盖，此处逐名钉）。

全部离线确定性（#139 零网络）。
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
src_dir = _REPO / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.core.circuit_diagram import ANNOT_LAYER_ID

_MIN_DRAWIO = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<mxfile><diagram id="d" name="n">'
    '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '</root></mxGraphModel></diagram></mxfile>\n')

# fake circuit_result（annotate 唯一消费形态：含 circuit 节=指标离线源；
# ADS 段 ok + 指标 1 枚 + 对拍 skipped → sim_h+sim_m0+sim_c 三卡）
_FAKE_CIRCUIT_RESULT = {
    "family": "wilkinson_snp",
    "circuit": {
        "family": "wilkinson_snp",
        "sim_ref": "fake/work/wilkinson_snp_circuit.drawio",
        "metric_source": "sparams",
        "metric_names": ["system_gain_db"],
        "metrics": {"system_gain_db": -3.2},
    },
    "ads": {"status": "ok", "n_points": 41, "port_names": ["P1", "P2", "P3"]},
    "sweep": {"fstart": 1.5, "fstop": 3.5, "unit": "GHz", "npoints": 41},
    "compare": {"status": "skipped"},
}


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """cwd 隔离单源委托（tests/conftest.py::isolated，#144 家法）。"""
    yield


def _tool(name: str):
    import asyncio

    from rfauto.mcp_server import mcp as server

    return {t.name: t for t in asyncio.run(server.list_tools())}[name]


# ══ 注册面 ════════════════════════════════════════════════════════════════


class TestRegistration:
    def test_both_registered_with_schema_and_description(self):
        for name in ("ads_circuit_annotate", "design_report"):
            tool = _tool(name)
            assert tool.description.strip(), f"{name} 描述空"
            schema = (tool.parameters or {}).get("properties") or {}
            assert schema, f"{name} schema 空"

    def test_description_payload_discipline_under_350(self):
        """描述载荷纪律（o_ads 家法：过长描述触发载荷收紧先例）。"""
        for name in ("ads_circuit_annotate", "design_report"):
            desc = _tool(name).description
            assert len(desc) < 350, f"{name} 描述 {len(desc)} 字符 ≥350"

    def test_required_params_pin(self):
        assert set(_tool("ads_circuit_annotate").parameters["required"]) == {
            "diagram", "result", "out"}
        assert set(_tool("design_report").parameters["required"]) == {"run_id"}


# ══ 转发直通（零业务逻辑红线：kwargs 逐字透传+异常→error 信封） ══════════


class TestForwarding:
    def test_annotate_forwards_positional_verbatim(self, monkeypatch, tmp_path):
        box: dict = {}

        def _fake_ann(diagram, result, out, *, with_curves=False):
            box.update({"diagram": diagram, "result": result, "out": out,
                        "with_curves": with_curves})
            return {"ok": True, "out_path": out, "n_cards": 3}

        import rfauto.service.circuit_sim_service as svc

        monkeypatch.setattr(svc, "annotate_circuit_diagram", _fake_ann)
        out = _tool("ads_circuit_annotate").fn(
            diagram="c.drawio", result="r.json", out=str(tmp_path / "a.drawio"))
        assert out["ok"] is True
        assert box == {"diagram": "c.drawio", "result": "r.json",
                       "out": str(tmp_path / "a.drawio"), "with_curves": False}

    def test_annotate_curves_kwarg_forwarded(self, monkeypatch, tmp_path):
        """curves=True 透传 service with_curves（B4 遗留④补齐：MCP 形参
        缺位——签名加参非新工具，MCP 计数不变）。"""
        box: dict = {}

        def _fake_ann(diagram, result, out, *, with_curves=False):
            box["with_curves"] = with_curves
            return {"ok": True, "out_path": out, "n_cards": 3,
                    "curves_card": with_curves}

        import rfauto.service.circuit_sim_service as svc

        monkeypatch.setattr(svc, "annotate_circuit_diagram", _fake_ann)
        out = _tool("ads_circuit_annotate").fn(
            diagram="c.drawio", result="r.json",
            out=str(tmp_path / "a.drawio"), curves=True)
        assert out["ok"] is True
        assert box["with_curves"] is True

    def test_annotate_exception_becomes_error_envelope(self, monkeypatch):
        import rfauto.service.circuit_sim_service as svc

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(svc, "annotate_circuit_diagram", _boom)
        out = _tool("ads_circuit_annotate").fn(
            diagram="c.drawio", result="r.json", out="a.drawio")
        assert out["ok"] is False and out["errors"]
        assert any("RuntimeError: boom" in str(e) for e in out["errors"])

    def test_design_report_forwards_kwargs_verbatim(self, monkeypatch):
        box: dict = {}

        def _fake_gen(run_id, *, output=None, with_diagrams=True):
            box.update({"run_id": run_id, "output": output,
                        "with_diagrams": with_diagrams})
            return {"ok": True, "run_id": run_id, "report": output}

        import rfauto.service.design_replay_report as svc

        monkeypatch.setattr(svc, "generate_design_report", _fake_gen)
        out = _tool("design_report").fn(run_id="r1", out="rep.md",
                                        with_diagrams=False)
        assert out["ok"] is True
        assert box == {"run_id": "r1", "output": "rep.md",
                       "with_diagrams": False}

    def test_design_report_defaults_forwarded(self, monkeypatch):
        """缺省形态：out=None/with_diagrams=True 与 CLI 叶缺省同语义。"""
        box: dict = {}

        def _fake_gen(run_id, *, output=None, with_diagrams=True):
            box.update({"run_id": run_id, "output": output,
                        "with_diagrams": with_diagrams})
            return {"ok": True}

        import rfauto.service.design_replay_report as svc

        monkeypatch.setattr(svc, "generate_design_report", _fake_gen)
        out = _tool("design_report").fn(run_id="r1")
        assert out["ok"] is True
        assert box == {"run_id": "r1", "output": None, "with_diagrams": True}

    def test_design_report_exception_becomes_error_envelope(self, monkeypatch):
        import rfauto.service.design_replay_report as svc

        def _boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(svc, "generate_design_report", _boom)
        out = _tool("design_report").fn(run_id="r1")
        assert out["ok"] is False and out["errors"]
        assert any("RuntimeError: boom" in str(e) for e in out["errors"])


# ══ e2e 最小链（annotate：tmp 图+fake circuit_result） ═══════════════════


class TestAnnotateEndToEnd:
    def test_annotate_full_chain(self, tmp_path):
        """骨架图+fake circuit_result → annot_sim 层上图；二次反标注逐字节
       相同（幂等，service byte-identical 钉同源）。"""
        diagram = tmp_path / "ckt.drawio"
        diagram.write_text(_MIN_DRAWIO, encoding="utf-8")
        result = tmp_path / "wilkinson_snp_circuit_result.json"
        result.write_text(json.dumps(_FAKE_CIRCUIT_RESULT, indent=1),
                          encoding="utf-8")
        out = tmp_path / "annotated" / "a.drawio"
        out.parent.mkdir()

        env = _tool("ads_circuit_annotate").fn(
            diagram=str(diagram), result=str(result), out=str(out))
        assert env["ok"] is True, env
        assert env["n_cards"] == 3  # 头卡+1 指标+对拍 skipped
        assert env["annot_layer"] == ANNOT_LAYER_ID
        doc = ET.parse(out)  # 产物=合法 XML
        assert any(el.get("id") == ANNOT_LAYER_ID
                   for el in doc.getroot().iter("mxCell"))
        # 幂等：同图同 result 二次反标注逐字节相同
        out2 = tmp_path / "annotated" / "a2.drawio"
        env2 = _tool("ads_circuit_annotate").fn(
            diagram=str(diagram), result=str(result), out=str(out2))
        assert env2["ok"] is True
        assert out.read_bytes() == out2.read_bytes()

    def test_annotate_annot_layer_idempotent_replace(self, tmp_path):
        """已反标注图再反标注 → annot_sim 层替换不堆积（单层）。"""
        diagram = tmp_path / "ckt.drawio"
        diagram.write_text(_MIN_DRAWIO, encoding="utf-8")
        result = tmp_path / "r.json"
        result.write_text(json.dumps(_FAKE_CIRCUIT_RESULT, indent=1),
                          encoding="utf-8")
        env1 = _tool("ads_circuit_annotate").fn(
            diagram=str(diagram), result=str(result),
            out=str(tmp_path / "a1.drawio"))
        assert env1["ok"] is True
        env2 = _tool("ads_circuit_annotate").fn(
            diagram=str(tmp_path / "a1.drawio"), result=str(result),
            out=str(tmp_path / "a2.drawio"))
        assert env2["ok"] is True
        xml2 = (tmp_path / "a2.drawio").read_text(encoding="utf-8")
        assert xml2.count(f'id="{ANNOT_LAYER_ID}"') == 1

    def test_annotate_missing_diagram_negative_envelope(self, tmp_path):
        result = tmp_path / "r.json"
        result.write_text(json.dumps(_FAKE_CIRCUIT_RESULT, indent=1),
                          encoding="utf-8")
        out = _tool("ads_circuit_annotate").fn(
            diagram=str(tmp_path / "nope.drawio"), result=str(result),
            out=str(tmp_path / "a.drawio"))
        assert out["ok"] is False and out["errors"]
        assert not (tmp_path / "a.drawio").exists()

    def test_annotate_missing_result_negative_envelope(self, tmp_path):
        diagram = tmp_path / "ckt.drawio"
        diagram.write_text(_MIN_DRAWIO, encoding="utf-8")
        out = _tool("ads_circuit_annotate").fn(
            diagram=str(diagram), result=str(tmp_path / "nope.json"),
            out=str(tmp_path / "a.drawio"))
        assert out["ok"] is False and out["errors"]

    def test_annotate_result_without_circuit_node_negative(self, tmp_path):
        """裸 <family>_result.json（无 circuit 节）不消费——显式报错信封。"""
        diagram = tmp_path / "ckt.drawio"
        diagram.write_text(_MIN_DRAWIO, encoding="utf-8")
        result = tmp_path / "wilkinson_snp_result.json"
        result.write_text(json.dumps({"family": "wilkinson_snp", "ok": True},
                                     indent=1), encoding="utf-8")
        out = _tool("ads_circuit_annotate").fn(
            diagram=str(diagram), result=str(result),
            out=str(tmp_path / "a.drawio"))
        assert out["ok"] is False
        assert any("circuit" in str(e) for e in out["errors"])


# ══ e2e 最小链（design_report：tmp A 族假 run 档，chdir 隔离零湖写） ═════


def _make_a_run(tmp_path: Path) -> Path:
    """A 单评族最小 fixture（meta+recipe 快照+results/metrics.json——
    test_design_replay_report::_make_a_run 家法同构，零湖写）。"""
    run = tmp_path / "run_a"
    (run / "results").mkdir(parents=True)
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
    }
    (run / "recipe.snapshot.yaml").write_text(
        yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    (run / "results" / "metrics.json").write_text(json.dumps({
        "run_id": "run_a",
        "params": {"arm_len_mm": 20.5},
        "metrics": {"s11_db_max_in_band": -11.5},
        "cost": 3.5,
        "checks": {"passivity_ok": True, "reciprocity_ok": True},
    }, indent=1), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": "run_a",
        "model": "wilkinson_power_divider",
        "adapter": "fake",
        "status": "done",
        "metrics": {"s11_db_max_in_band": -11.5},
    }, indent=1), encoding="utf-8")
    return run


class TestDesignReportEndToEnd:
    def test_design_report_full_chain(self, tmp_path):
        """tmp 假 run → 六节 md 落盘；报告路径在信封 report 键。"""
        run = _make_a_run(tmp_path)
        out_md = tmp_path / "rep" / "design_report.md"
        out_md.parent.mkdir()

        env = _tool("design_report").fn(run_id=str(run), out=str(out_md))
        assert env["ok"] is True, env
        # run_id 回显走 service 解析口径（runs/ 命中→目录名；显式路径→原样）
        assert env["run_id"] in {run.name, str(run)}
        assert out_md.is_file()
        md_text = out_md.read_text(encoding="utf-8")
        assert "s11_db" in md_text  # 门表带目标键（全数字带 provenance 面）
        fresh = env.get("freshness") or {}
        assert fresh.get("status") in {"legacy", "fresh", "unknown"}

    def test_design_report_run_not_found_negative_envelope(self, tmp_path):
        env = _tool("design_report").fn(
            run_id=str(tmp_path / "no_such_run"))
        assert env["ok"] is False and env["errors"]

    def test_design_report_no_lake_pollution(self, tmp_path):
        """runs/ 湖零写入：cwd 已隔离（autouse isolated），假 run 档在 tmp，
        调用后 cwd 下不出现任何 runs/ 落物（#144 纪律自证）。"""
        run = _make_a_run(tmp_path)
        cwd = Path.cwd()
        env = _tool("design_report").fn(run_id=str(run),
                                        out=str(tmp_path / "r.md"))
        assert env["ok"] is True
        assert not (cwd / "runs").exists()


# ══ 域映射（mcp_interop_matrix；total/closed 邻接面= test_w5_d_fe2） ═════


class TestDomainMapping:
    def test_both_tools_mapped(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "mcp_interop_matrix", _REPO / "scripts" / "mcp_interop_matrix.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.our_tool_domain("ads_circuit_annotate") == "后处理"
        assert mod.our_tool_domain("design_report") == "后处理"
        assert mod.our_tool_domain("ads_circuit_annotate") in mod.DOMAINS
        assert mod.our_tool_domain("design_report") in mod.DOMAINS
