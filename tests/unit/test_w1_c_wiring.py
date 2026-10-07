"""W1-C 孤儿接线批定向门：单元 10/11/12/14/15/15c 共 8 叶（VI-1 表行）。

判据（批 criteria W1-C 预声明，逐条钉住）：

- ①各叶 --help 真跑全过（typer CliRunner 真构建命令面）；help 文案
  卫生自证（无裸 ``[``、无 ``%``，#305 家法——typer 面全角替代）；
- ②每叶 ≥1 条 ``--json`` 双路径（成功信封+失败信封）冒烟；无法离线
  构造真机面的叶（vna measure 真采集）用 monkeypatch 钉 service 转发；
- ③vna measure 无 --address = dry-run 计划态信封（ok=true+dry_run 标记，
  零连接零 subprocess——service 函数注入炸弹证明采集链未进入）；
- ④zenodo 全程零网络（socket 注入炸弹钉，#139/PR-11）；
- ⑤全部 _emit 信封进出（成功/失败信封同构，ok/errors 键恒在）；
- ⑥零数值面：本席三个新增 CLI 文件 AST 零 float 字面量（全部转发，
  铁律 7；calc_vna/diagnose 为既有文件追加叶，其既有缺省浮点不计）。

注册面计数（test_cli.py/test_check_numbers.py 五钉）不在本文件作用域
（批纪律：主代理合流时集中更新）；本文件只自证本席注册正确性。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.domains import few_shot as few_shot_domain
from rfauto.cli.domains import teaching as teaching_domain
from rfauto.cli.domains import zenodo as zenodo_domain
from rfauto.cli.main import app

runner = CliRunner()

REPO = Path(__file__).resolve().parents[2]

#: 八叶名单（本席交付面；单元 10/11/12/14×2/15/15c×2）。
NEW_LEAVES = (
    ("vna", "measure"),
    ("vna", "calibrate"),
    ("diagnose", "detective"),
    ("teaching", "show"),
    ("teaching", "index"),
    ("few-shot", "build"),
    ("zenodo", "export"),
    ("zenodo", "validate"),
)

#: 本席三个新增 CLI 文件（判据⑥零数值面作用域）。
NEW_CLI_FILES = (teaching_domain, few_shot_domain, zenodo_domain)

#: 子应用 → 叶全云集（防遮蔽钉：子应用内出现名单外命令=被顶替/漂移）。
SUBAPP_LEAVES = {
    "teaching": {"show", "index"},
    "few-shot": {"build"},
    "zenodo": {"export", "validate"},
    "vna": {"en-report", "replay", "measure", "calibrate"},
    "diagnose": {"q", "cm", "cat", "detective", "deviation"},
    # deviation=W6 批新增诊断叶（配方偏差判读入口）——合流集中更新
}


def _click_root():
    """typer app → click 树根（Typer 无 .commands，须经 get_command 落成）。"""
    from typer.main import get_command

    return get_command(app)


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


def _invoke_json(args: list[str]):
    """跑命令并解析 --json 信封（_emit 走 rich print_json，可 json.loads）。"""
    result = runner.invoke(app, args)
    try:
        payload = json.loads(result.output)
    except ValueError:
        payload = None
    return result, payload


# ══ 判据①：注册面 + --help 真跑 + help 文案卫生 ═══════════════════════════


class TestRegistration:
    def test_new_leaves_registered(self):
        nodes = dict(_walk_click_tree(_click_root()))
        for sub, leaf in NEW_LEAVES:
            assert f"{sub} {leaf}" in nodes, f"{sub} {leaf} 未注册进 CLI 树"

    @pytest.mark.parametrize("sub", sorted(SUBAPP_LEAVES))
    def test_no_shadow_subapp_leaves(self, sub):
        """#df6① 防遮蔽钉：子应用节点命令集=名单全集（被顶替即缺叶打红）。"""
        nodes = dict(_walk_click_tree(_click_root()))
        assert sub in nodes, f"{sub} 子应用未注册"
        got = set(getattr(nodes[sub], "commands", {}) or {})
        assert got == SUBAPP_LEAVES[sub], f"{sub} 叶集漂移: {got}"

    @pytest.mark.parametrize(("sub", "leaf"), NEW_LEAVES)
    def test_help_runs(self, sub, leaf):
        result = runner.invoke(app, [sub, leaf, "--help"])
        assert result.exit_code == 0, result.output

    def test_help_text_hygiene_self_check(self):
        """本席 8 叶+3 新子应用节点 help/short_help 无裸 [ 与 %（#305 家法）。"""
        guard_paths = {f"{s} {leaf}" for s, leaf in NEW_LEAVES} | set(SUBAPP_LEAVES)
        for path, cmd in _walk_click_tree(_click_root()):
            if path not in guard_paths:
                continue
            for text in (getattr(cmd, "help", None) or "",
                         getattr(cmd, "short_help", None) or ""):
                assert "[" not in text, (path, text)
                assert "%" not in text, (path, text)


# ══ 判据⑥：零数值面 + service 消费点自证 ══════════════════════════════════


class TestZeroNumericFace:
    @pytest.mark.parametrize("domain", NEW_CLI_FILES, ids=lambda d: d.__name__)
    def test_no_float_literals_in_new_cli_files(self, domain):
        tree = ast.parse(Path(domain.__file__).read_text(encoding="utf-8"))
        floats = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Constant)
                  and isinstance(node.value, float)]
        assert floats == [], f"新增 CLI 文件出现 float 字面量: {floats[:5]}"

    @pytest.mark.parametrize("domain", NEW_CLI_FILES, ids=lambda d: d.__name__)
    def test_no_numeric_imports(self, domain):
        src = Path(domain.__file__).read_text(encoding="utf-8")
        assert "import math" not in src
        assert "import numpy" not in src


class TestServiceConsumption:
    @pytest.mark.parametrize(("module_name", "functions"), [
        ("rfauto.service.vna_service",
         ("run_vna_measure", "vna_calibrate_standalone")),
        ("rfauto.service.data_detective",
         ("data_detective_report", "render_detective_markdown")),
        ("rfauto.service.teaching_service",
         ("load_teaching", "render_teaching_markdown", "textbook_index")),
        ("rfauto.service.few_shot_service",
         ("select_few_shots", "build_few_shot_system")),
        ("rfauto.service.zenodo_service",
         ("export_zenodo_metadata", "validate_citation_metadata")),
    ])
    def test_service_functions_exist(self, module_name, functions):
        import importlib

        mod = importlib.import_module(module_name)
        for fn in functions:
            assert callable(getattr(mod, fn, None)), (module_name, fn)


# ══ 判据②③：单元 10 —— vna measure（dry-run 计划态 + 双路径） ════════════


class TestVnaMeasure:
    def test_no_address_dry_run_plan_envelope(self, monkeypatch):
        """判据③：无 --address=计划态信封，采集链零进入（service 炸弹钉）。"""
        import rfauto.service.vna_service as svc

        def _bomb(*a, **k):  # pragma: no cover - 被调用即测试红
            raise AssertionError("dry-run 计划态不得进入采集链（零连接铁律）")

        monkeypatch.setattr(svc, "run_vna_measure", _bomb)
        result, payload = _invoke_json(["vna", "measure", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["dry_run"] is True
        plan = payload["plan"]
        assert plan["address"] == ""
        assert plan["model"] == "librevna"
        assert "note" in plan

    def test_dry_run_plan_reflects_parsed_params(self, monkeypatch):
        import rfauto.service.vna_service as svc

        monkeypatch.setattr(
            svc, "run_vna_measure",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("禁入")))
        result, payload = _invoke_json([
            "vna", "measure", "--model", "nanovna",
            "--freq-range-ghz", "1.0,2.0", "--n-points", "11", "--json"])
        assert result.exit_code == 0, result.output
        plan = payload["plan"]
        assert plan["model"] == "nanovna"
        assert plan["freq_range_ghz"] == [1.0, 2.0]
        assert plan["n_points"] == 11

    def test_bad_freq_range_failure_envelope(self):
        result, payload = _invoke_json([
            "vna", "measure", "--freq-range-ghz", "3.0,1.0", "--json"])
        assert result.exit_code == 2
        assert payload is None  # 参数解析面退出码 2（typer 惯例，非信封面）

    def test_success_forwards_to_service(self, tmp_path, monkeypatch):
        import rfauto.service.vna_service as svc

        calls: dict = {}

        def _fake(*, address, model, freq_range_ghz, n_points, ifbw_hz,
                  calkit_id, twoxthru_path, visa_library, ref_s2p, runs_dir):
            calls.update(address=address, model=model,
                         freq=tuple(freq_range_ghz), runs_dir=runs_dir)
            return {"ok": True, "run_id": "r1", "run_dir": str(runs_dir),
                    "artifacts": {}, "metrics": {}, "errors": []}

        monkeypatch.setattr(svc, "run_vna_measure", _fake)
        rd = tmp_path / "runs"
        result, payload = _invoke_json([
            "vna", "measure", "--address", "TCPIP0::sim::INSTR",
            "--runs-dir", str(rd), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert calls["address"] == "TCPIP0::sim::INSTR"
        assert calls["runs_dir"] == str(rd)

    def test_service_error_envelope_rc1(self, tmp_path, monkeypatch):
        import rfauto.service.vna_service as svc

        monkeypatch.setattr(
            svc, "run_vna_measure",
            lambda *a, **k: {"ok": False, "errors": ["VNA 连接失败"]})
        result, payload = _invoke_json([
            "vna", "measure", "--address", "TCPIP0::gone::INSTR",
            "--runs-dir", str(tmp_path), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"] == ["VNA 连接失败"]


# ══ 判据②：单元 11 —— vna calibrate（catalog 真链 + 双路径） ══════════════

_CALKIT_DIR = REPO / "knowledge" / "calkits"


def _solt_two_port_measurements(tmp_path: Path) -> dict[str, Path]:
    """catalog 反射件（1-port .s1p）→ 双端口同反射 .s2p（VNA 双口实测口径）。

    skrf SOLT 契约要求双端口（TwelveTerm 读 s11/s22 两口径）——包裹脚手架
    与 test_calibration.py TestMs3CatalogSoltSmoke._two_port_diag 同语义；
    through 用 catalog 自带的 2-port 实件直通。
    """
    import numpy as np
    import skrf

    out: dict[str, Path] = {}
    for std, fname in (("short", "wl_2g5_short.s1p"),
                       ("open", "wl_2g5_open.s1p"),
                       ("load", "wl_2g5_load.s1p")):
        net = skrf.Network(str(_CALKIT_DIR / fname))
        s = np.zeros((len(net.f), 2, 2), dtype=complex)
        s[:, 0, 0] = net.s[:, 0, 0]
        s[:, 1, 1] = net.s[:, 0, 0]
        wrapped = skrf.Network(frequency=net.frequency, s=s, z0=50.0,
                               name=std)
        p = tmp_path / f"{std}_2p.s2p"
        wrapped.write_touchstone(str(p))
        out[std] = p
    out["through"] = _CALKIT_DIR / "wl_2g5_thru.s2p"
    return out


class TestVnaCalibrate:
    def test_solt_success_envelope(self, tmp_path):
        out = tmp_path / "cal.s2p"
        meas = _solt_two_port_measurements(tmp_path)
        args = ["vna", "calibrate", "--calkit", "wl_2g5_solt_smoke", "--json"]
        for std in ("short", "open", "load", "through"):
            args += ["-m", f"{std}={meas[std]}"]
        args += ["--dut", str(meas["through"]), "--out", str(out)]
        result, payload = _invoke_json(args)
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["calibration"]["is_calibrated"] is True
        assert payload["calibration_order"]
        assert payload["written"] == str(out) and out.is_file()

    def test_missing_standards_failure_envelope(self):
        args = ["vna", "calibrate", "--calkit", "wl_2g5_solt_smoke", "--json",
                "-m", f"short={_CALKIT_DIR / 'wl_2g5_short.s1p'}"]
        result, payload = _invoke_json(args)
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "缺少标准件实测" in payload["errors"][0]

    def test_missing_file_failure_envelope(self):
        args = ["vna", "calibrate", "--calkit", "wl_2g5_solt_smoke", "--json",
                "-m", "short=__no_such__.s1p"]
        result, payload = _invoke_json(args)
        assert result.exit_code == 1
        assert payload["ok"] is False

    def test_no_measurements_failure_envelope(self):
        result, payload = _invoke_json(
            ["vna", "calibrate", "--calkit", "wl_2g5_solt_smoke", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "--measurements" in payload["errors"][0]


# ══ 判据②：单元 12 —— diagnose detective（--ref 直消费 + 双路径） ═════════

_FAKE_EXPLAIN: dict = {
    "ok": True,
    "run_dir": "runs/fake_run",
    "playbook": {"path": "knowledge/diagnostics/playbook.yaml",
                 "schema": "rfauto-diag-playbook-v1", "n_rules": 10},
    "meta": {"model": "mline"},
    "health_verdict": "FAIL",
    "fingerprints": {
        "sparam_passivity_violation": {"evidence": ["meta: max|S|=1.04"]},
    },
    "matched_rules": [
        {"id": "fdtd_truncation_artifact",
         "root_cause_family": "fdtd_truncation_artifact",
         "matched_fingerprints": ["sparam_passivity_violation"],
         "evidence": {},
         "forensic_commands": ["看 et 尾段：tail -n 5 <run>/fdtd/et"],
         "pit_refs": ["#262"],
         "notes": "窄 FC 窗截断长脉冲"},
    ],
    "candidates": ["fdtd_truncation_artifact"],
    "skipped_rules": [],
    "overall": "candidates",
}


class TestDiagnoseDetective:
    def test_ref_success_envelope(self, tmp_path):
        ref = tmp_path / "explain.json"
        ref.write_text(json.dumps(_FAKE_EXPLAIN, ensure_ascii=False),
                       encoding="utf-8")
        md = tmp_path / "report.md"
        result, payload = _invoke_json([
            "diagnose", "detective", "--ref", str(ref),
            "--markdown", str(md), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["markdown_path"] == str(md)
        assert md.is_file()
        assert list(payload["sections"]) == [
            "findings", "hypotheses", "evidence", "conclusion"]

    def test_no_input_failure_envelope(self):
        result, payload = _invoke_json(["diagnose", "detective", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert "--run-dir" in payload["errors"][0]

    def test_not_ok_explain_failure_envelope(self, tmp_path):
        ref = tmp_path / "bad_explain.json"
        ref.write_text(json.dumps({"ok": False, "reason": "no evidence"}),
                       encoding="utf-8")
        result, payload = _invoke_json(
            ["diagnose", "detective", "--ref", str(ref), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


# ══ 判据②：单元 14 —— teaching show / index（双路径） ═════════════════════


class TestTeachingShow:
    def test_success_envelope(self, tmp_path):
        md = tmp_path / "mline_teaching.md"
        result, payload = _invoke_json([
            "teaching", "show", "mline", "--markdown", str(md), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["template"] == "mline"
        assert payload["teaching"]["schema"] == "rfauto-teaching/v1"
        assert payload["markdown"]
        assert md.is_file()

    def test_unknown_template_failure_envelope(self):
        result, payload = _invoke_json(
            ["teaching", "show", "__no_such_template__", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]


class TestTeachingIndex:
    def test_full_table_success_envelope(self):
        result, payload = _invoke_json(["teaching", "index", "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["n_rows"] > 0
        assert payload["rows"]

    def test_filtered_zero_hit_empty_table_honest(self):
        result, payload = _invoke_json(
            ["teaching", "index", "--textbook", "__no_such_book__", "--json"])
        assert result.exit_code == 0
        assert payload["n_rows"] == 0 and payload["rows"] == []

    def test_service_error_envelope_rc1(self, monkeypatch):
        """防御面：service 面语义演进回错误信封时，薄壳原样透传 rc 1。"""
        import rfauto.service.teaching_service as svc

        monkeypatch.setattr(
            svc, "textbook_index",
            lambda *a, **k: {"ok": False, "errors": ["索引构建失败"]})
        result, payload = _invoke_json(["teaching", "index", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


# ══ 判据②：单元 15 —— few-shot build（双路径） ════════════════════════════


def _session_doc(session_id: str) -> dict:
    return {
        "schema": "rfauto-chat-session-v1",
        "session_id": session_id,
        "history": [
            {"role": "user", "content": "综合 mline 微带线并跑校准"},
            {"role": "assistant", "content": "已完成提案"},
        ],
        "tool_calls": [{"action": "syn_mline"}],
        "stats": {"turns": 1},
    }


class TestFewShotBuild:
    def test_success_envelope_with_sessions_dir(self, tmp_path):
        sess = tmp_path / "sessions"
        sess.mkdir()
        (sess / "chat_good.json").write_text(
            json.dumps(_session_doc("chat_good"), ensure_ascii=False),
            encoding="utf-8")
        out = tmp_path / "section.md"
        result, payload = _invoke_json([
            "few-shot", "build", "--task", "mline 校准",
            "--sessions-dir", str(sess), "--out", str(out), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["n_candidates"] == 1
        assert payload["exemplars"]
        assert payload["section_path"] == str(out)
        assert out.is_file()

    def test_service_error_envelope_rc1(self, monkeypatch):
        import rfauto.service.few_shot_service as svc

        monkeypatch.setattr(
            svc, "build_few_shot_system",
            lambda *a, **k: {"ok": False, "errors": ["会话档扫描失败"]})
        result, payload = _invoke_json(
            ["few-shot", "build", "--task", "任意任务", "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False


# ══ 判据②④：单元 15c —— zenodo export / validate（零网络钉+双路径） ══════

_CFF_COMPLETE = """\
cff-version: 1.2.0
message: "If you use rfauto in your research, please cite it as below."
title: "rfauto: test framework"
type: software
repository-code: "https://github.com/example/rfauto"
authors:
  - name: rfauto developers
version: 9.9.9
license: GPL-3.0-only
abstract: >-
  Test abstract for the exporter.
keywords:
  - RF
  - test
"""

_PYPROJECT_MATCHING = '[project]\nname = "rfauto"\nversion = "9.9.9"\n'
_PYPROJECT_MISMATCH = '[project]\nname = "rfauto"\nversion = "0.0.1"\n'


def _no_network(monkeypatch) -> None:
    """判据④：socket 注入炸弹——zenodo 两叶全程零网络（#139/PR-11）。"""
    import socket

    def _bomb(*a, **k):  # pragma: no cover - 被调用即测试红
        raise AssertionError("zenodo 面禁止网络调用（PR-11 零网络铁律）")

    monkeypatch.setattr(socket, "socket", _bomb)


class TestZenodoExport:
    def test_success_envelope_zero_network(self, tmp_path, monkeypatch):
        _no_network(monkeypatch)
        cff = tmp_path / "CITATION.cff"
        cff.write_text(_CFF_COMPLETE, encoding="utf-8")
        out = tmp_path / ".zenodo.json"
        result, payload = _invoke_json([
            "zenodo", "export", "--cff", str(cff), "--out", str(out),
            "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["metadata"]["title"] == "rfauto: test framework"
        assert payload["written"] is True
        assert out.is_file()

    def test_missing_cff_failure_envelope(self, tmp_path, monkeypatch):
        _no_network(monkeypatch)
        result, payload = _invoke_json([
            "zenodo", "export", "--cff", str(tmp_path / "gone.cff"), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]


class TestZenodoValidate:
    def test_success_envelope_zero_network(self, tmp_path, monkeypatch):
        _no_network(monkeypatch)
        cff = tmp_path / "CITATION.cff"
        cff.write_text(_CFF_COMPLETE, encoding="utf-8")
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(_PYPROJECT_MATCHING, encoding="utf-8")
        result, payload = _invoke_json([
            "zenodo", "validate", "--cff", str(cff),
            "--pyproject", str(pyproject), "--json"])
        assert result.exit_code == 0, result.output
        assert payload["ok"] is True
        assert payload["checked"]

    def test_version_mismatch_failure_envelope(self, tmp_path, monkeypatch):
        _no_network(monkeypatch)
        cff = tmp_path / "CITATION.cff"
        cff.write_text(_CFF_COMPLETE, encoding="utf-8")
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(_PYPROJECT_MISMATCH, encoding="utf-8")
        result, payload = _invoke_json([
            "zenodo", "validate", "--cff", str(cff),
            "--pyproject", str(pyproject), "--json"])
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"]
