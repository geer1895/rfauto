"""ads-circuit 反标注曲线嵌入钉（aurora_p B4：opt-in 缺省零变化）。

任务书验收映射（冻结判据）：
- A. 缺省行为零变化：curves 关（缺省）路径 result 无 curves 节、图无
  sim_g 卡、信封零新键（既有全部反标注钉在本文件外零改动全绿即总证）；
- B. curves 幂等三方逐字节：annotate(annotate(x, curves))==annotate(x,
  curves)==run 产物（build_annotated_diagram_xml 整层替换既有幂等机制）；
- C. PNG 确定性：同输入两次 annotate/run 逐字节（PNG 确定性由
  test_diagram_curve_image 两独立进程钉单源承担，此处链路级互证）；
- E. 曲线数据逐点==payload：circuit["curves"] 节抽 3 频点对拍 runner
  payload（JSON 往返无损——float repr 最短往返）；
- 负例：HB 形态 payload（无 S 参数）→ run/annotate 均如实 warnings 跳过
  不炸（幂等不炸语义）；CLI e2e（run/annotate 两叶 --curves 全链出图）。
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import skrf
from typer.testing import CliRunner

from rfauto.adapters import ads_netlist
from rfauto.cli.main import app as root_app
from rfauto.core.circuit_diagram import ANNOT_LAYER_ID
from rfauto.linkage import ads_template_family as atf
from rfauto.service.circuit_sim_service import (
    annotate_circuit_diagram,
    circuit_sim_run,
    generate_circuit_diagram,
)

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))


def _payload_from_network(net: skrf.Network) -> dict:
    """skrf.Network → ads_netlist.parse_dataset 同形 payload（离线替身）。"""
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


def _runner(net: skrf.Network):
    payload = _payload_from_network(net)

    def run(_netlist: Path) -> dict:
        return payload

    return run


def _ids(xml_text: str) -> set[str]:
    return {el.get("id") for el in ET.fromstring(xml_text).iter() if el.get("id")}


def _userobject_by_id(xml_text: str, cell_id: str) -> ET.Element | None:
    for el in ET.fromstring(xml_text).iter("UserObject"):
        if el.get("id") == cell_id:
            return el
    return None


def _result_json(run_dir: Path, family: str = "wilkinson_snp") -> Path:
    return run_dir / f"{family}_circuit_result.json"


# ─── 验收 A：缺省零变化 ──────────────────────────────────────────────────────


class TestDefaultPathZeroChange:
    def test_run_default_no_curves_node_no_sim_g_card(self, wilk_s3p, tmp_path):
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                 out_dir=tmp_path / "run",
                                 runner=_runner(skrf.Network(str(wilk_s3p))))
        assert result["ok"]
        assert "curves_card" not in result, "缺省信封零新键"
        stored = json.loads(_result_json(tmp_path / "run").read_text(encoding="utf-8"))
        assert "curves" not in stored["circuit"], "缺省 result 零 curves 节"
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "sim_g" not in _ids(annotated), "缺省图零曲线卡"

    def test_annotate_default_on_curves_result_still_no_card(self, wilk_s3p, tmp_path):
        """curves 节在而 with_curves 关 → 消费端同样 opt-in（零新卡零新键）。"""
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                        out_dir=tmp_path / "run", curves=True,
                        runner=_runner(skrf.Network(str(wilk_s3p))))
        out = tmp_path / "plain.drawio"
        env2 = annotate_circuit_diagram(tmp_path / "ckt.drawio",
                                        _result_json(tmp_path / "run"), out)
        assert env2["ok"]
        assert "curves_card" not in env2, "缺省 annotate 信封零新键"
        assert "sim_g" not in _ids(out.read_text(encoding="utf-8"))


# ─── 验收 B/C/E：curves 开启全链 ─────────────────────────────────────────────


class TestCurvesChain:
    @pytest.fixture()
    def curves_run(self, wilk_s3p, tmp_path):
        net = skrf.Network(str(wilk_s3p))
        env = generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        assert env["ok"]
        result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                                 out_dir=tmp_path / "run", curves=True,
                                 runner=_runner(net))
        assert result["ok"], result
        return {"net": net, "result": result, "tmp": tmp_path}

    def test_curves_node_point_by_point_vs_payload(self, curves_run):
        """验收 E：result JSON 内 curves 节抽 3 频点对拍 runner payload。"""
        result = curves_run["result"]
        assert result["curves_card"] is True
        stored = json.loads(
            _result_json(curves_run["tmp"] / "run").read_text(encoding="utf-8"))
        node = stored["circuit"]["curves"]
        assert node["keys"] == ["1_1", "2_1"]
        freq = node["frequency_hz"]
        for idx in (0, len(freq) // 2, len(freq) - 1):
            comp = complex(curves_run["net"].s[idx, 0, 0])
            expect = 20.0 * math.log10(math.hypot(comp.real, comp.imag))
            assert node["series"][0]["db"][idx] == expect
        assert node["frequency_hz"] == [float(f) for f in curves_run["net"].f]

    def test_sim_g_card_embedded_image_style(self, curves_run):
        annotated = Path(curves_run["result"]["annotated_diagram_path"]).read_text(
            encoding="utf-8")
        card = _userobject_by_id(annotated, "sim_g")
        assert card is not None, "curves 开启 → sim_g 卡在图"
        inner = card.find("mxCell")
        style = inner.get("style") or ""
        assert style.startswith("shape=image;verticalLabelPosition=bottom;")
        assert ";base64" not in style, "data URI 无分号红线（先例同款）"
        assert "image=data:image/png," in style
        assert card.get("source") == "rfauto.core.diagram_curve_image.render_curves_png"
        assert card.get("unit") == "dB" and card.get("sim_ref") and card.get("sim_result")
        assert card.get("curves") == "S11, S21" and card.get("n_points") == "41"
        geo = inner.find("mxGeometry")
        assert geo.get("width") == "480" and geo.get("height") == "300"

    def test_idempotent_three_way_bytes(self, curves_run):
        """验收 B：annotate(annotate(x))==annotate(x)==run 产物 三方逐字节。"""
        result = curves_run["result"]
        run_annotated = Path(result["annotated_diagram_path"]).read_bytes()
        out1 = curves_run["tmp"] / "a1.drawio"
        out2 = curves_run["tmp"] / "a2" / "a2.drawio"
        out2.parent.mkdir(parents=True, exist_ok=True)
        rj = _result_json(curves_run["tmp"] / "run")
        env1 = annotate_circuit_diagram(curves_run["tmp"] / "ckt.drawio", rj, out1,
                                        with_curves=True)
        env2 = annotate_circuit_diagram(out1, rj, out2, with_curves=True)
        assert env1["ok"] and env2["ok"]
        assert env1["curves_card"] is True and env2["curves_card"] is True
        assert env1["warnings"] == [] and env2["warnings"] == []
        assert out1.read_bytes() == out2.read_bytes() == run_annotated

    def test_run_twice_byte_identical_and_annotate_twice(self, wilk_s3p, tmp_path):
        """验收 C 链路级：curves=True 同图同 runner 同 out_dir 两跑（J5 形态，
        sim_ref=路径）逐字节 + 同图同 result 两次 annotate 逐字节（PNG 确
        定性在链路端的互证）。"""
        net = skrf.Network(str(wilk_s3p))
        generate_circuit_diagram("wilkinson_snp", wilk_s3p, tmp_path / "ckt.drawio")
        r1 = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                             out_dir=tmp_path / "run", curves=True, runner=_runner(net))
        p1 = Path(r1["annotated_diagram_path"]).read_bytes()
        result1 = _result_json(tmp_path / "run").read_bytes()
        r2 = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=wilk_s3p,
                             out_dir=tmp_path / "run", curves=True, runner=_runner(net))
        assert r2["ok"]
        p2 = Path(r2["annotated_diagram_path"]).read_bytes()
        assert p1 == p2
        assert _result_json(tmp_path / "run").read_bytes() == result1
        out_a, out_b = tmp_path / "b1.drawio", tmp_path / "b2.drawio"
        annotate_circuit_diagram(tmp_path / "ckt.drawio",
                                 _result_json(tmp_path / "run"),
                                 out_a, with_curves=True)
        annotate_circuit_diagram(tmp_path / "ckt.drawio",
                                 _result_json(tmp_path / "run"),
                                 out_b, with_curves=True)
        assert out_a.read_bytes() == out_b.read_bytes() == p1


# ─── 负例：payload 无 S 参数（幂等不炸语义；真家族=loadpull_hb 单点） ────────


class TestCurvesNegativeNoSparams:
    @staticmethod
    def _lp2_snp(path: Path) -> Path:
        """2 端口衰减器替身 SnP（test_circuit_diagram_active 家法同构）。"""
        import numpy as np

        freqs = np.linspace(1.8e9, 2.2e9, 41)
        s = np.zeros((freqs.size, 2, 2), dtype=complex)
        s[:, 0, 1] = 10 ** (-3.0 / 20)
        s[:, 1, 0] = 10 ** (-3.0 / 20)
        net = skrf.Network(frequency=skrf.Frequency.from_f(freqs, unit="Hz"),
                           s=s, z0=50)
        net.write_touchstone(str(path), form="ri")
        return path

    @staticmethod
    def _hb_payload(_netlist: Path) -> dict:
        """HB 单点形态 payload（无 s/frequency_hz——parse_hb_dataset 键面；
        mix=1 基波节点 N_OUT 供 hb_payload_to_point 单源取点）。"""
        return {"ok": True, "key": "HB.HB",
                "harmonics": [
                    {"mix": 0, "freq_hz": 2.4e9, "nodes": {"N_OUT": [0.0, 0.0]}},
                    {"mix": 1, "freq_hz": 2.4e9, "nodes": {"N_OUT": [3.0, 1.0]}},
                ],
                "measurements": {"Pout_dBm": 10.0, "Pout_W": 1e-2, "Gain_dB": 10.0}}

    @pytest.fixture()
    def lp_result(self, tmp_path):
        dev = self._lp2_snp(tmp_path / "dev.s2p")
        env = generate_circuit_diagram(
            "loadpull_hb", dev, tmp_path / "lp.drawio",
            params={"f0_hz": 2.4e9, "power_dbm": 0.0,
                    "z_load_re": 50.0, "z_load_im": 0.0})
        assert env["ok"], env
        result = circuit_sim_run(
            tmp_path / "lp.drawio", snp_path=dev, out_dir=tmp_path / "run",
            curves=True, compare=False, runner=self._hb_payload)
        assert result["ok"], result
        return {"result": result, "tmp": tmp_path}

    def test_run_with_curves_on_hb_payload_warns_and_skips(self, lp_result):
        result = lp_result["result"]
        assert result["curves_card"] is False
        assert any("无 S 参数" in w and "如实跳过" in w for w in result["warnings"])
        stored = json.loads(
            _result_json(lp_result["tmp"] / "run", "loadpull_hb").read_text(
                encoding="utf-8"))
        assert "curves" not in stored["circuit"]
        annotated = Path(result["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "sim_g" not in _ids(annotated)

    def test_annotate_with_curves_on_result_without_node_warns(self, lp_result):
        tmp = lp_result["tmp"]
        out1, out2 = tmp / "c1.drawio", tmp / "c2.drawio"
        rj = _result_json(tmp / "run", "loadpull_hb")
        env1 = annotate_circuit_diagram(tmp / "lp.drawio", rj, out1,
                                        with_curves=True)
        env2 = annotate_circuit_diagram(out1, rj, out2, with_curves=True)
        assert env1["ok"] and env2["ok"], "幂等不炸语义"
        assert env1["curves_card"] is False and env2["curves_card"] is False
        assert env1["warnings"] and "如实跳过" in env1["warnings"][0]
        assert out1.read_bytes() == out2.read_bytes(), "无卡路径同样幂等逐字节"


# ─── CLI e2e（--curves 旗标透传；#139：hpeesofsim 通道 monkeypatch 钉住） ────


class TestCliCurves:
    @pytest.fixture()
    def patched_ads_channel(self, monkeypatch):
        box: dict = {"payload": None}

        def _fake_sim(netlist, ads_dir=None, **_kw):
            return subprocess.CompletedProcess(args=[], returncode=0,
                                               stdout="ok", stderr="")

        def _fake_parse(dataset, ads_dir=None, **_kw):
            assert box["payload"] is not None
            return box["payload"]

        monkeypatch.setattr(ads_netlist, "run_hpeesofsim", _fake_sim)
        monkeypatch.setattr(ads_netlist, "parse_dataset", _fake_parse)
        return box

    def test_run_and_annotate_with_curves_flag(self, wilk_s3p, tmp_path,
                                               patched_ads_channel):
        patched_ads_channel["payload"] = _payload_from_network(
            skrf.Network(str(wilk_s3p)))
        runner = CliRunner()
        r = runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "wilkinson_snp",
            "--snp", str(wilk_s3p), "--out", str(tmp_path / "ckt.drawio"), "--json"])
        assert r.exit_code == 0, r.output
        # run --curves 全链出图
        r2 = runner.invoke(root_app, [
            "ads-circuit", "run", "--diagram", str(tmp_path / "ckt.drawio"),
            "--snp", str(wilk_s3p), "--out-dir", str(tmp_path / "run"),
            "--curves", "--json"])
        assert r2.exit_code == 0, r2.output
        env2 = json.loads(r2.output)
        assert env2["ok"] and env2["curves_card"] is True
        annotated = Path(env2["annotated_diagram_path"]).read_text(encoding="utf-8")
        assert "sim_g" in _ids(annotated)
        # annotate --curves 离线重放
        r3 = runner.invoke(root_app, [
            "ads-circuit", "annotate", "--diagram", str(tmp_path / "ckt.drawio"),
            "--result", str(tmp_path / "run" / "wilkinson_snp_circuit_result.json"),
            "--out", str(tmp_path / "out.drawio"), "--curves", "--json"])
        assert r3.exit_code == 0, r3.output
        env3 = json.loads(r3.output)
        assert env3["ok"] and env3["curves_card"] is True
        assert (tmp_path / "out.drawio").read_bytes() == \
            Path(env2["annotated_diagram_path"]).read_bytes()

    def test_annotate_without_flag_envelope_unchanged(self, wilk_s3p, tmp_path,
                                                      patched_ads_channel):
        patched_ads_channel["payload"] = _payload_from_network(
            skrf.Network(str(wilk_s3p)))
        runner = CliRunner()
        runner.invoke(root_app, [
            "ads-circuit", "diagram", "--family", "wilkinson_snp",
            "--snp", str(wilk_s3p), "--out", str(tmp_path / "ckt.drawio"), "--json"])
        runner.invoke(root_app, [
            "ads-circuit", "run", "--diagram", str(tmp_path / "ckt.drawio"),
            "--snp", str(wilk_s3p), "--out-dir", str(tmp_path / "run"),
            "--curves", "--json"])
        r = runner.invoke(root_app, [
            "ads-circuit", "annotate", "--diagram", str(tmp_path / "ckt.drawio"),
            "--result", str(tmp_path / "run" / "wilkinson_snp_circuit_result.json"),
            "--out", str(tmp_path / "plain.drawio"), "--json"])
        assert r.exit_code == 0, r.output
        env = json.loads(r.output)
        assert env["ok"] and "curves_card" not in env and "warnings" not in env

    def test_leaf_set_unchanged_zero_new_command(self):
        """零新叶零计数（既有三叶钉同款判据本地复述）。"""
        from typer.main import get_command

        from rfauto.cli.domains.ads_circuit import ads_circuit_app

        root = get_command(ads_circuit_app)
        assert set(root.commands) == {"diagram", "run", "annotate"}
        assert ANNOT_LAYER_ID == "annot_sim"
