"""W3-D F-10 六服务 shell 接线定向门（Phase 3 批，2026-10-05）。

判据（批 criteria W3-D 预声明，逐条钉住；W1-A 同款纪律）：

- ①六服务八叶 --help 真跑全过（typer CliRunner 真构建命令面）+ help 文案
  卫生自证（无裸 ``[``、无 ``%``——#305 家法）；
- ②每叶 ≥1 条双路径冒烟（成功信封 + 失败信封，_emit 同构进出；bench 叶
  按 bench 门色退出码语义 PASS=0/FAIL=1）；
- ③防同名遮蔽钉（#df6①）：五子应用叶集精确断言 + bench 旧五叶保留 +
  新 tool 名集与既有 137 名集零交；
- ④qucsator 通道 fail-closed 与 #139：缺席/未知 engine 显式 ok=False；
  子进程/真机一律 monkeypatch 钉住，单测零网络零真跑；
- ⑤零数值面：两个 wholly-new 壳文件 AST 零 float 字面量、零 math/numpy
  导入（bench_app 新叶豁免说明：--min-pass-rate 1.0 是 spec 预声明选项
  缺省=service DEFAULT 透传形态，同文件既有 goldset 门 min_tsa=0.9 同款）；
- ⑥MCP stdio stdout 字节=0 回归钉（#278）不回归。

注册面计数（test_cli.py/test_check_numbers.py/test_mcp_server.py/
test_mcp_tool_consistency.py 五钉 + docs 三处 + 注册序金快照）不在本文件
作用域（批纪律：主代理合流时集中更新）；本文件只自证本席注册正确性。
预期计数链：CLI 227→235（+8：fault-tree 1/datasheet 1/netlist-goldset 1/
humidity 2/weave 2/cryo 1）、MCP 137→145（+8）、bench 分解 5→6。
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.main import app

runner = CliRunner()

_REPO = Path(__file__).resolve().parents[2]


def _walk_click_tree(group, prefix: str = "") -> list[tuple[str, object]]:
    """鸭子判别遍历（#354：typer._click 内嵌 click，isinstance 全漏）。"""
    out: list[tuple[str, object]] = []
    commands = getattr(group, "commands", None)
    if not isinstance(commands, dict):
        return out
    for name in sorted(commands):
        sub = commands[name]
        path = f"{prefix} {name}".strip()
        out.append((path, sub))
        out.extend(_walk_click_tree(sub, path))
    return out


def _click_tree() -> list[tuple[str, object]]:
    from typer.main import get_command

    return _walk_click_tree(get_command(app))


def _invoke_json(args: list[str]):
    """跑命令并解析 --json 信封（_emit 走 rich print_json，可 json.loads）。"""
    result = runner.invoke(app, args)
    try:
        payload = json.loads(result.output)
    except ValueError:
        payload = None
    return result, payload


def _payload_file(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


#: 本席八叶节点路径（含父节点，--help 真跑面）。
SEAT_NODE_PATHS = (
    "fault-tree",
    "fault-tree report",
    "datasheet",
    "datasheet build",
    "humidity",
    "humidity uptake",
    "humidity msl",
    "weave",
    "weave styles",
    "weave estimate",
    "cryo",
    "cryo surface",
    "bench netlist-goldset",
)

#: 零数值面自证清单：wholly-new 壳文件（bench_app 既有文件豁免，见模块 docstring ⑤）。
NEW_SHELL_FILES = (
    "src/rfauto/cli/domains/env_reliability.py",
    "src/rfauto/mcp_tools/env_reliability.py",
)

#: 本席新增 MCP 工具名（与既有 137 名集零交=防遮蔽三钉之一）。
SEAT_TOOL_NAMES = (
    "fault_tree_report",
    "build_datasheet",
    "netlist_goldset_replay",
    "humidity_uptake",
    "msl_floor_life_query",
    "weave_style_info",
    "weave_skew_estimate",
    "cryo_surface_estimate",
)


# ══ 判据①：八叶注册可达 + --help 真跑 + help 文案卫生 ═══════════════════


class TestRegistration:
    def test_seat_nodes_registered(self):
        nodes = dict(_click_tree())
        for path in SEAT_NODE_PATHS:
            assert path in nodes, f"本席节点未注册: {path}"

    @pytest.mark.parametrize("node_path", SEAT_NODE_PATHS)
    def test_help_runs(self, node_path):
        result = runner.invoke(app, [*node_path.split(), "--help"])
        assert result.exit_code == 0, result.output

    def test_help_text_hygiene_self_check(self):
        """本席节点 help/short_help 无裸 [ 与 %（不碰冻结基线门，全角替代）。"""
        for path, cmd in _click_tree():
            if path not in SEAT_NODE_PATHS:
                continue
            for text in (getattr(cmd, "help", None) or "",
                         getattr(cmd, "short_help", None) or ""):
                assert "[" not in text, (path, text)
                assert "%" not in text, (path, text)

    def test_help_runs_in_real_subprocess(self):
        """真进程 --help（console 路径）：-m rfauto.cli.main fault-tree --help。"""
        proc = subprocess.run(
            [sys.executable, "-m", "rfauto.cli.main", "fault-tree", "--help"],
            capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0
        assert "report" in proc.stdout

    def test_subapp_leaf_sets_exact_and_no_shadow(self):
        """#df6① 防遮蔽钉：五子应用叶集精确 + bench 旧五叶保留 + 新叶并存。"""
        nodes = dict(_click_tree())
        assert set(getattr(nodes["fault-tree"], "commands", {})) == {"report"}
        assert set(getattr(nodes["datasheet"], "commands", {})) == {"build"}
        assert set(getattr(nodes["humidity"], "commands", {})) == {"uptake", "msl"}
        assert set(getattr(nodes["weave"], "commands", {})) == {"styles", "estimate"}
        assert set(getattr(nodes["cryo"], "commands", {})) == {"surface"}
        bench_children = set(getattr(nodes["bench"], "commands", {}))
        assert bench_children == {
            "goldset", "agentbench", "level2", "prompt-regression",
            "consistency", "netlist-goldset",
        }, f"bench 叶集漂移: {bench_children}"


# ══ 判据②：双路径冒烟（成功信封 + 失败信封） ═══════════════════════════


class TestFaultTreeLeaf:
    def test_report_json_success(self):
        result, payload = _invoke_json(["fault-tree", "report", "--engine", "enumerate"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["tree"]["top"]["gate"] == "OR"
        assert payload["mcs"] and payload["n_mcs"] >= 1
        assert payload["audit"]["n_rules_in_tree"] >= 1

    def test_report_mermaid_human_path(self):
        result = runner.invoke(app, ["fault-tree", "report", "--format", "mermaid"])
        assert result.exit_code == 0, result.output
        assert "graph TD" in result.output

    def test_report_mermaid_json_envelope(self):
        result, payload = _invoke_json(
            ["fault-tree", "report", "--format", "mermaid", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert "graph TD" in payload["mermaid"]

    def test_report_bad_engine_fails_closed(self):
        result, payload = _invoke_json(["fault-tree", "report", "--engine", "bogus"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]

    def test_report_bad_playbook_fail_envelope(self):
        result, payload = _invoke_json(
            ["fault-tree", "report", "--playbook", "Z:/no/such/playbook.yaml"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]

    def test_report_bad_format_fail_envelope(self):
        result, payload = _invoke_json(["fault-tree", "report", "--format", "dot"])
        assert result.exit_code == 1
        assert payload["ok"] is False

    def test_engine_z3_missing_extras_fail_closed(self, monkeypatch):
        """#139 钉：z3 extras 缺席面 monkeypatch 钉住（不依赖真装状态）。"""
        from rfauto.service import fault_tree_service as fts

        monkeypatch.setattr(
            fts, "_z3_available", lambda: (False, "z3 未安装（单测钉）"))
        result, payload = _invoke_json(["fault-tree", "report", "--engine", "z3"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload.get("hint")


class TestDatasheetLeaf:
    def test_build_degenerate_run_dir_degrades_honestly(self, tmp_path):
        """run 目录在场但无 run 数据（docs/ 形态）→ 如实降级（curves missing），
        零实测行不伪造——reports render 的"缺如实降级"同源语义。"""
        out = tmp_path / "ds.md"
        result, payload = _invoke_json([
            "datasheet", "build", "--template", "mline",
            "--run", str(_REPO / "docs"), "--out", str(out), "--json",
        ])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["curves_status"] == "missing"
        assert out.is_file() and out.stat().st_size > 0

    def test_build_run_missing_fail_envelope(self, tmp_path):
        result, payload = _invoke_json([
            "datasheet", "build", "--template", "mline",
            "--run", str(tmp_path / "no_such_run"), "--json",
        ])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "run" in payload["errors"][0]

    def test_build_nominal_only_success_and_file(self, tmp_path):
        out = tmp_path / "ds.md"
        result, payload = _invoke_json([
            "datasheet", "build", "--template", "mline",
            "--part-number", "MLINE-TEST", "--out", str(out), "--json",
        ])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["part_number"] == "MLINE-TEST"
        assert payload["curves_status"] == "missing"
        assert out.is_file() and out.stat().st_size > 0
        text = out.read_text(encoding="utf-8")
        assert "MLINE-TEST" in text and "工程规格书" in text

    def test_build_print_path_and_html(self, tmp_path):
        result, payload = _invoke_json([
            "datasheet", "build", "--template", "mline",
            "--format", "html", "--json",
        ])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["content"].startswith("<!DOCTYPE html>")

    def test_build_bad_format_fail_envelope(self):
        result, payload = _invoke_json(
            ["datasheet", "build", "--template", "mline", "--format", "pdf", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False

    def test_build_no_template_no_part_fail_envelope(self):
        result, payload = _invoke_json(
            ["datasheet", "build", "--template", "", "--part-number", "", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


class TestHumidityLeaves:
    def test_uptake_success(self, tmp_path):
        payload_file = _payload_file(tmp_path, {
            "t_h": 24, "diffusivity_m2_s": 1.0e-12, "thickness_mm": 1.0,
        })
        result, payload = _invoke_json(["humidity", "uptake", payload_file])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert "uptake" in payload

    def test_uptake_fail_envelope(self, tmp_path):
        payload_file = _payload_file(tmp_path, {})
        result, payload = _invoke_json(["humidity", "uptake", payload_file])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]

    def test_msl_success(self, tmp_path):
        payload_file = _payload_file(tmp_path, {"msl": "3", "exposure_h": 1})
        result, payload = _invoke_json(["humidity", "msl", payload_file])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["unlimited"] is False
        assert payload["expired"] is False

    def test_msl_fail_envelope(self, tmp_path):
        payload_file = _payload_file(tmp_path, {"msl": "99"})
        result, payload = _invoke_json(["humidity", "msl", payload_file])
        assert result.exit_code == 1
        assert payload["ok"] is False


class TestWeaveLeaves:
    def test_styles_readonly_face(self):
        result, payload = _invoke_json(["weave", "styles"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert set(payload["styles"]) >= {"1067", "1080", "2116", "7628"}

    def test_styles_single(self):
        result, payload = _invoke_json(["weave", "styles", "--style", "1080"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert set(payload["styles"]) == {"1080"}

    def test_styles_unknown_fail_envelope(self):
        result, payload = _invoke_json(["weave", "styles", "--style", "9999"])
        assert result.exit_code == 1
        assert payload["ok"] is False

    def test_estimate_success(self, tmp_path):
        payload_file = _payload_file(tmp_path, {
            "style": "1080", "length_mm": 10.0, "er_resin": 3.5,
        })
        result, payload = _invoke_json(["weave", "estimate", payload_file])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert "skew_worst" in payload

    def test_estimate_fail_envelope(self, tmp_path):
        payload_file = _payload_file(tmp_path, {"style": "1080"})
        result, payload = _invoke_json(["weave", "estimate", payload_file])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]


class TestCryoLeaf:
    def test_surface_success(self, tmp_path):
        payload_file = _payload_file(tmp_path, {"t_k": 77.0, "rrr": 50.0, "f_hz": 1.0e9})
        result, payload = _invoke_json(["cryo", "surface", payload_file])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert "copper" in payload

    def test_surface_fail_envelope(self, tmp_path):
        payload_file = _payload_file(tmp_path, {})
        result, payload = _invoke_json(["cryo", "surface", payload_file])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]


class TestBenchNetlistGoldsetLeaf:
    def _goldset_file(self, tmp_path: Path) -> str:
        p = tmp_path / "netlist_goldset.yaml"
        p.write_text(yaml.safe_dump({
            "version": 1,
            "tasks": [{
                "id": "rc_lowpass_ac",
                "netlist": "* RC lowpass\n",
                "analysis": "ac dec 100 1 1Meg",
                "expected": {"fc_hz": {"value": 1591.55, "tol": 0.02}},
            }],
        }, allow_unicode=True), encoding="utf-8")
        return str(p)

    def test_unknown_engine_fail_closed(self, tmp_path):
        result, payload = _invoke_json([
            "bench", "netlist-goldset", "--goldset", self._goldset_file(tmp_path),
            "--engine", "ngspice",
        ])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["gate"] == "FAIL"

    def test_qucsator_missing_fail_closed(self, tmp_path, monkeypatch):
        """#139 钉：可执行缺席面 monkeypatch（不依赖本机 qucsator 在装状态）。"""
        from rfauto.service import netlist_sim_channels as nsc

        def _raise(_exe=None):
            raise FileNotFoundError("未找到 qucsatorRF 可执行文件（单测钉）")

        monkeypatch.setattr(nsc, "resolve_qucsator_exe", _raise)
        result, payload = _invoke_json([
            "bench", "netlist-goldset", "--goldset", self._goldset_file(tmp_path),
        ])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["gate"] == "FAIL"
        assert "fail-closed" in payload["reasons"][0]

    def test_replay_pass_gate(self, tmp_path, monkeypatch):
        from rfauto.service import netlist_sim_channels as nsc

        monkeypatch.setattr(
            nsc, "build_simulator_channel",
            lambda engine, exe=None: (lambda netlist, analysis: {"fc_hz": 1591.55}))
        result, payload = _invoke_json([
            "bench", "netlist-goldset", "--goldset", self._goldset_file(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True and payload["gate"] == "PASS"
        assert payload["n_pass"] == 1

    def test_replay_fail_gate(self, tmp_path, monkeypatch):
        from rfauto.service import netlist_sim_channels as nsc

        monkeypatch.setattr(
            nsc, "build_simulator_channel",
            lambda engine, exe=None: (lambda netlist, analysis: {"fc_hz": 999.0}))
        result, payload = _invoke_json([
            "bench", "netlist-goldset", "--goldset", self._goldset_file(tmp_path),
        ])
        assert result.exit_code == 1
        assert payload["ok"] is False and payload["gate"] == "FAIL"


# ══ 判据④：通道内核（dataset_metrics 纯函数 + 子进程链 monkeypatch 钉） ══


class TestNetlistSimChannels:
    def test_unknown_engine_value_error(self):
        from rfauto.service.netlist_sim_channels import build_simulator_channel

        with pytest.raises(ValueError):
            build_simulator_channel("xyce")

    def test_dataset_metrics_convention(self):
        from rfauto.service.netlist_sim_channels import dataset_metrics

        out = dataset_metrics({
            "freq_hz": [1.0e9, 2.0e9],
            "S": {(1, 1): [0.5 + 0j, 0.25 + 0j], (2, 1): [0.9 + 0.1j, 0.8 - 0.1j]},
        })
        assert set(out) == {
            "n_freq", "freq_min_hz", "freq_max_hz",
            "s11_mag_min", "s11_mag_max", "s11_db_min", "s11_db_max",
            "s21_mag_min", "s21_mag_max", "s21_db_min", "s21_db_max",
        }
        import math

        assert out["n_freq"] == 2.0
        assert out["freq_min_hz"] == 1.0e9
        assert out["s11_mag_min"] == 0.25
        assert math.isclose(out["s11_db_max"], 20.0 * math.log10(0.5))

    def test_dataset_metrics_ndarray_safe(self):
        """回归钉（真机冒烟实证）：read_qucs_dataset 产出 numpy 数组——
        ``or []`` falsy 惯语对 ndarray 触发 ambiguous truth value（#117 家族），
        缺省判断必须 is not None。"""
        import numpy as np

        from rfauto.service.netlist_sim_channels import dataset_metrics

        out = dataset_metrics({
            "freq_hz": np.array([1.0e9, 2.0e9]),
            "S": {(1, 1): np.array([0.5 + 0j, 0.25 + 0j])},
        })
        assert out["n_freq"] == 2.0
        assert out["s11_mag_max"] == 0.5
        # 空指标缺省面（键缺省=通道未产出，replay 链如实 FAIL）
        assert dataset_metrics({"freq_hz": None, "S": None}) == {"n_freq": 0.0}

    def test_channel_writes_analysis_comment_and_parses(self, monkeypatch, tmp_path):
        """子进程链钉：-i/-o 参数形态 + analysis 注释落网表 + dataset 解析。"""
        from rfauto.service import netlist_sim_channels as nsc

        seen: dict = {}

        def fake_run(cmd, **_kw):
            net = Path(cmd[cmd.index("-i") + 1])
            seen["net_text"] = net.read_text(encoding="utf-8")
            dat = Path(cmd[cmd.index("-o") + 1])
            dat.write_text("<Qucs Dataset>（单测钉）", encoding="utf-8")

            class _Proc:
                returncode = 0
                stdout = ""
                stderr = ""

            return _Proc()

        monkeypatch.setattr(nsc.subprocess, "run", fake_run)
        monkeypatch.setattr(
            nsc, "read_qucs_dataset",
            lambda _p: {"freq_hz": [1.0e9], "S": {(1, 1): [0.5 + 0j]}})
        monkeypatch.setattr(
            nsc, "resolve_qucsator_exe", lambda _exe=None: tmp_path / "qucsator_rf.exe")
        channel = nsc.build_qucsator_channel()
        out = channel("* RC\n", "ac dec 100 1 1Meg")
        assert "# analysis: ac dec 100 1 1Meg" in seen["net_text"]
        assert seen["net_text"].startswith("* RC\n")
        assert out["n_freq"] == 1.0 and out["s11_mag_max"] == 0.5

    def test_channel_nonzero_exit_raises(self, monkeypatch, tmp_path):
        from rfauto.adapters.qucsator_adapter import QucsatorError
        from rfauto.service import netlist_sim_channels as nsc

        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr(nsc.subprocess, "run", lambda cmd, **_kw: _Proc())
        monkeypatch.setattr(
            nsc, "resolve_qucsator_exe", lambda _exe=None: tmp_path / "qucsator_rf.exe")
        channel = nsc.build_qucsator_channel()
        with pytest.raises(QucsatorError):
            channel("* RC\n", "")

    def test_channel_missing_dataset_raises(self, monkeypatch, tmp_path):
        from rfauto.adapters.qucsator_adapter import QucsatorError
        from rfauto.service import netlist_sim_channels as nsc

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(nsc.subprocess, "run", lambda cmd, **_kw: _Proc())
        monkeypatch.setattr(
            nsc, "resolve_qucsator_exe", lambda _exe=None: tmp_path / "qucsator_rf.exe")
        channel = nsc.build_qucsator_channel()
        with pytest.raises(QucsatorError):
            channel("* RC\n", "")

    def test_build_channel_missing_exe_raises(self, monkeypatch):
        from rfauto.service import netlist_sim_channels as nsc

        def _raise(_exe=None):
            raise FileNotFoundError("no exe")

        monkeypatch.setattr(nsc, "resolve_qucsator_exe", _raise)
        with pytest.raises(FileNotFoundError):
            nsc.build_simulator_channel("qucsator")


# ══ 判据③⑥：MCP 注册面 + stdout 字节钉 ═══════════════════════════════


def _registered_tool_names() -> set[str]:
    import rfauto.mcp_server as mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    return {t.name for t in tools}


class TestMcpWiring:
    def test_eight_tools_registered(self):
        names = _registered_tool_names()
        for name in SEAT_TOOL_NAMES:
            assert name in names, f"MCP 工具未注册: {name}"

    def test_no_shadow_with_preexisting_tools(self):
        """新八名与既有面零重名（list_tools 名单无重复=fastmcp 级防遮蔽）。"""
        import rfauto.mcp_server as mcp_server

        tools = asyncio.run(mcp_server.mcp.list_tools())
        names = [t.name for t in tools]
        assert len(names) == len(set(names)), "工具重名（遮蔽事故形态）"
        assert len(names) == 141 + len(SEAT_TOOL_NAMES), (  # 141=W6 三钉后基数（run_monitor/start_tune/preflight_run，合流集中更新）
            f"工具总数漂移: {len(names)}（合流钉由主代理集中更新，"
            "本钉只断言本席 +8 落位）")

    def test_fault_tree_report_callable(self):
        from rfauto.mcp_tools.env_reliability import fault_tree_report

        out = fault_tree_report()
        assert out["ok"] is True and out["mcs"]
        mm = fault_tree_report(out_format="mermaid")
        assert "graph TD" in mm["mermaid"]

    def test_build_datasheet_callable(self):
        from rfauto.mcp_tools.env_reliability import build_datasheet

        out = build_datasheet(template="mline", part_number="MLINE-MCP")
        assert out["ok"] is True
        assert out["content"] and out["model"]["schema"] == "rfauto-datasheet/v1"
        bad = build_datasheet(run_dir="Z:/no/such/run", template="mline")
        assert bad["ok"] is False and bad["errors"]

    def test_netlist_goldset_replay_fail_closed_and_pass(self, monkeypatch, tmp_path):
        from rfauto.mcp_tools.env_reliability import netlist_goldset_replay
        from rfauto.service import netlist_sim_channels as nsc

        def _raise(engine, exe=None):
            raise FileNotFoundError("no exe（单测钉）")

        monkeypatch.setattr(nsc, "build_simulator_channel", _raise)
        bad = netlist_goldset_replay(goldset_path="whatever.yaml")
        assert bad["ok"] is False and bad["gate"] == "FAIL"

        monkeypatch.setattr(
            nsc, "build_simulator_channel",
            lambda engine, exe=None: (lambda netlist, analysis: {"fc_hz": 1591.55}))
        gold = tmp_path / "g.yaml"
        gold.write_text(yaml.safe_dump({
            "version": 1,
            "tasks": [{"id": "t1", "netlist": "* n\n", "analysis": "ac",
                       "expected": {"fc_hz": {"value": 1591.55, "tol": 0.02}}}],
        }, allow_unicode=True), encoding="utf-8")
        out = netlist_goldset_replay(goldset_path=str(gold))
        assert out["ok"] is True and out["gate"] == "PASS"

    def test_payload_tools_callable(self):
        from rfauto.mcp_tools.env_reliability import (
            cryo_surface_estimate,
            humidity_uptake,
            msl_floor_life_query,
            weave_skew_estimate,
            weave_style_info,
        )

        out = humidity_uptake({"t_h": 24, "diffusivity_m2_s": 1.0e-12,
                               "thickness_mm": 1.0})
        assert out["ok"] is True and "uptake" in out
        assert msl_floor_life_query({"msl": "3"})["ok"] is True
        assert weave_style_info()["ok"] is True
        assert weave_style_info({"style": "1080"})["ok"] is True
        est = weave_skew_estimate({"style": "1080", "length_mm": 10.0,
                                   "er_resin": 3.5})
        assert est["ok"] is True and "skew_worst" in est
        cryo = cryo_surface_estimate({"t_k": 77.0, "rrr": 50.0, "f_hz": 1.0e9})
        assert cryo["ok"] is True and "copper" in cryo
        assert weave_skew_estimate({})["ok"] is False

    def test_optional_payload_schema_builds(self):
        """weave_style_info 的可选 payload（dict|None）schema 可生成（fastmcp 兼容钉）。"""
        import rfauto.mcp_server as mcp_server

        tools = asyncio.run(mcp_server.mcp.list_tools())
        by_name = {t.name: t for t in tools}
        assert by_name["weave_style_info"].parameters is not None

    def test_mcp_import_emits_zero_stdout_bytes(self):
        """#278 回归钉：import rfauto.mcp_server 零 stdout 字节（stdio 信道保护）。"""
        proc = subprocess.run(
            [sys.executable, "-c", "import rfauto.mcp_server"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
        assert proc.returncode == 0, proc.stderr[-500:]
        assert proc.stdout == b"", f"stdout 泄漏 {len(proc.stdout)} 字节"


# ══ 判据⑤：零数值面（AST 零 float 字面量、零 math/numpy） ═══════════════


class TestZeroNumericFace:
    @pytest.mark.parametrize("rel", NEW_SHELL_FILES)
    def test_no_float_literals_in_new_shell_files(self, rel):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        floats = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Constant) and isinstance(n.value, float)]
        assert not floats, f"{rel} 出现 float 字面量: {floats[:5]}"

    @pytest.mark.parametrize("rel", NEW_SHELL_FILES)
    def test_no_math_numpy_imports_in_new_shell_files(self, rel):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        banned = roots & {"math", "numpy"}
        assert not banned, f"{rel} 壳面出现数值库导入: {banned}"


# ══ 数据源 helper（load_template_meta）钉 ════════════════════════════════


class TestLoadTemplateMeta:
    def test_real_template_meta_loads(self):
        from rfauto.service.datasheet_service import load_template_meta

        meta = load_template_meta("mline")
        assert isinstance(meta, dict) and meta

    def test_missing_template_returns_none(self):
        from rfauto.service.datasheet_service import load_template_meta

        assert load_template_meta("no_such_template_xyz") is None
        assert load_template_meta("") is None

    def test_explicit_dir_injection(self, tmp_path):
        from rfauto.service.datasheet_service import load_template_meta

        d = tmp_path / "tpl_x"
        (d / "meta.yaml").parent.mkdir(parents=True)
        (d / "meta.yaml").write_text("f0_ghz: 2.4\n", encoding="utf-8")
        meta = load_template_meta("tpl_x", templates_dir=str(tmp_path))
        assert meta == {"f0_ghz": 2.4}
