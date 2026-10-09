"""EDB 快车道 CLI/MCP 出口定向门（2026-10-08）。

判据（任务书预声明）：
- ①service 编排纯度：发射段走 edb_templates 确定性发射器（离线纯函数，
  零 pyedb/AEDT）；建库/批解段 monkeypatch 钉通道（#139——EdbAdapter 与
  hfss_batch.solve_project_batch/export_touchstone_after_solve 全 fake，
  真机依赖零触碰）；信封三态契约（ok/errors/warnings）；
- ②CLI 三叶（build/solve/status）：全叶 --json 双路径（成功信封+失败
  信封同构、退出码语义）、help 卫生（无裸 % 与方括号，#305/rich markup）；
- ③MCP 三工具（edb_emit_spec/edb_build_solve/edb_status）：零逻辑转发钉
  （payload 透传+结果恒等）+程序性错误 error 信封不炸会话。

注册面计数（test_cli/test_check_numbers/test_mcp_server/
test_mcp_tool_consistency/注册序金快照/docs 数字）不在本文件作用域
（批纪律：五钉清单集中更新）；本文件只自证本席接线正确性。
预期计数链：CLI 261→264（+3）；MCP 149→152（+3）。

W3 遗留升格批追记（2026-10-08）：TestEmitSpecExt/TestStatus 扩钉——
分派表接入 coupled_line/ratrace 两新族（emit→build 假链全通）、lange
预留键结构化拒绝信封（指向 docs/templates/edb_lange/meta.yaml 升格
前置条件）、edb_status 五族清单 templates 节。

MCP resources 批追记（2026-10-08）：TestMcpResources 四件——
``rfauto://edb/status``（edb_status 透传+summary 薄聚合+失败信封不注
入）与 ``rfauto://edb/datasets``（list_datasets 前缀过滤 edb_lane_*+
失败信封透传）+read_resource 端到端 JSON 文本形态。resources 注册面
计数（5→7）的集中钉在 test_mcp_server/test_mcp_tool_consistency/
test_check_numbers（五钉清单批纪律），本文件只自证资源体接线。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.mcp_tools.edb import edb_build_solve as mcp_edb_build_solve
from rfauto.mcp_tools.edb import edb_emit_spec as mcp_edb_emit_spec
from rfauto.mcp_tools.edb import edb_status as mcp_edb_status
from rfauto.service import edb_lane_service as lane

runner = CliRunner()

_PARAMS = {"f0_ghz": 2.4}


# ── 假件（#139 通道钉：真机依赖零触碰）───────────────────────────────────────


class _FakeEdbAdapter:
    """EdbAdapter 替身：build 只回假路径不落盘；solve_batch 不可达
    （solve 链走 monkeypatch hfss_batch.solve_project_batch 的真实归一路）。"""

    instances: ClassVar[list[_FakeEdbAdapter]] = []

    def __init__(self, workdir):
        self.workdir = Path(workdir)
        _FakeEdbAdapter.instances.append(self)

    def build(self, spec):
        self.spec = spec
        stem = str(spec.get("name") or "edb_layout")
        aedb = self.workdir / f"{stem}.aedb"
        aedb.mkdir(parents=True, exist_ok=True)  # 真适配器会落盘，solve 链依赖存在性
        from rfauto.adapters.edb_adapter import EdbBuildResult

        return EdbBuildResult(
            aedb_path=aedb,
            config_json_path=self.workdir / f"{stem}_config.json",
            warnings=["fake-warning-占用顺移"],
        )

    def solve_batch(self, aedb_path, timeout_s=3600.0):
        """与真实现同构：转调 hfss_batch.solve_project_batch（fake 面）。"""
        from rfauto.adapters import hfss_batch
        from rfauto.adapters.edb_adapter import BatchSolveResult

        raw = hfss_batch.solve_project_batch(aedb_path, timeout_s=timeout_s)
        return BatchSolveResult(
            success=bool(raw["ok"]), rc=raw.get("rc"),
            log_path=Path(raw["logfile"]) if raw.get("logfile") else None,
            artifacts=[Path(a) for a in raw.get("artifacts") or []],
            elapsed_s=float(raw.get("elapsed_s") or 0.0),
        )


def _fake_solve_dict(ok: bool = True, project: str = "fake.aedb") -> dict:
    """hfss_batch.solve_project_batch 结构化 dict 契约（他席口径 fake）。"""
    return {
        "ok": ok,
        "rc": 0 if ok else 1,
        "timed_out": False,
        "command": ["ansysedt-fake", "-BatchSolve"],
        "ansysedt_exe": "fake-ansysedt.exe",
        "project": project,
        "project_kind": "aedb",
        "logfile": "fake_batch.log",
        "logfile_tail": "" if ok else "ERROR: fake",
        "artifacts": [],
        "elapsed_s": 1.5,
        "errors": [] if ok else ["fake solve failure"],
    }


def _fake_export_dict(ok: bool = True) -> dict:
    return {
        "ok": ok,
        "rc": 0 if ok else 1,
        "timed_out": False,
        "mode": "batchextract",
        "out_file": "fake_export.s2p" if ok else None,
        "n_ports": 4 if ok else None,
        "logfile": "fake_extract.log",
        "errors": [] if ok else ["fake export failure"],
    }


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    _FakeEdbAdapter.instances.clear()
    yield
    _FakeEdbAdapter.instances.clear()


# ── ①service：发射（确定性内核离线段）────────────────────────────────────────


class TestEmitSpec:
    def test_branchline_ok_envelope(self):
        r = lane.edb_emit_spec("edb_branchline", _PARAMS)
        assert r["ok"] is True
        assert r["template"] == "edb_branchline"
        spec = r["spec"]
        assert spec["template"] == "edb_branchline"
        assert len(spec["traces"]) == 8  # 四臂+四馈（branchline 拓扑）
        assert len(spec["ports"]) == 4
        assert {s["name"] for s in r["config_json"]["stackup"]["materials"]}

    def test_power_divider_ok_envelope(self):
        r = lane.edb_emit_spec("edb_power_divider", _PARAMS)
        assert r["ok"] is True
        assert len(r["spec"]["ports"]) == 3
        assert len(r["spec"]["resistors"]) == 1  # 隔离电阻 RISO（两输出臂间）

    def test_unknown_template_error_envelope(self):
        r = lane.edb_emit_spec("edb_nope", _PARAMS)
        assert r["ok"] is False
        assert r["errors"] and "edb_nope" in r["errors"][0]

    def test_bad_params_error_envelope(self):
        r = lane.edb_emit_spec("edb_branchline", {"f0_ghz": 2.4, "z0_ohm": 40})
        assert r["ok"] is False
        assert r["errors"] and "50" in r["errors"][0]

    def test_missing_f0_error_envelope(self):
        r = lane.edb_emit_spec("edb_branchline", {})
        assert r["ok"] is False
        assert r["errors"]

    def test_out_dir_writes_spec_json(self, tmp_path):
        r = lane.edb_emit_spec("edb_branchline", _PARAMS, out_dir=tmp_path)
        assert r["ok"] is True
        path = Path(r["spec_path"])
        assert path.is_file() and path.name.endswith("_spec.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["template"] == "edb_branchline"


# ── ①service：W3 遗留升格——分派表四族 + lange 结构化拒绝（2026-10-08）────────


class TestEmitSpecExt:
    """分派表接入 coupled_line/ratrace 两族 + lange 明确"不支持"信封。

    - 两新族 emit→build 假链全通（发射段确定性内核离线纯函数 + 建库段
      fake 适配器，#139 真机依赖零触碰）；
    - lange=结构化不支持信封（ok=False / 明确原因 / 升格前置条件指向
      docs/templates/edb_lange/meta.yaml）；
    - 未知模板名报错信封列出全部合法键并提示 lange 声明不支持。
    """

    def test_coupled_line_emit_build_fake_chain(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        r = lane.edb_emit_spec("edb_coupled_line", _PARAMS)
        assert r["ok"] is True and r["template"] == "edb_coupled_line"
        spec = r["spec"]
        assert spec["template"] == "edb_coupled_line"
        assert len(spec["traces"]) == 6  # 两耦合线 + 四馈线
        assert len(spec["ports"]) == 4
        b = lane.edb_build("edb_coupled_line", _PARAMS, workdir=tmp_path)
        assert b["ok"] is True
        assert b["aedb_path"].endswith("edb_coupled_line.aedb")  # 缺省名=template
        (adapter,) = _FakeEdbAdapter.instances
        assert adapter.spec["template"] == "edb_coupled_line"
        assert len(adapter.spec["traces"]) == 6

    def test_ratrace_emit_build_fake_chain(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        r = lane.edb_emit_spec("edb_ratrace", _PARAMS)
        assert r["ok"] is True and r["template"] == "edb_ratrace"
        spec = r["spec"]
        assert spec["template"] == "edb_ratrace"
        assert len(spec["traces"]) == 12  # 八环段 + 四馈线
        assert len(spec["ports"]) == 4
        b = lane.edb_build("edb_ratrace", _PARAMS, workdir=tmp_path,
                           name="rr24")
        assert b["ok"] is True
        assert b["aedb_path"].endswith("rr24.aedb")
        assert _FakeEdbAdapter.instances[0].spec["name"] == "rr24"

    def test_new_family_dry_run_zero_write(self, tmp_path):
        # dry_run 计划态对两新族同语义：零写盘零 pyedb
        for template, n_traces in (("edb_coupled_line", 6),
                                   ("edb_ratrace", 12)):
            r = lane.edb_build(template, _PARAMS, workdir=tmp_path / template,
                               dry_run=True)
            assert r["ok"] is True and r["dry_run"] is True
            assert len(r["spec"]["traces"]) == n_traces
            assert set(r["config"]) >= {"stackup", "modeler", "ports"}
        assert not (tmp_path / "edb_coupled_line").exists()
        assert not (tmp_path / "edb_ratrace").exists()

    def test_lange_structured_unsupported_envelope(self):
        r = lane.edb_emit_spec("edb_lange", _PARAMS)
        assert r["ok"] is False
        assert r["template"] == "edb_lange"
        assert r["supported"] is False
        assert "不支持" in r["reason"] and "crossover" in r["reason"]
        assert r["upgrade_doc"] == "docs/templates/edb_lange/meta.yaml"
        assert r["errors"] and "meta.yaml" in r["errors"][0]
        assert "升格前置条件" in r["errors"][0]
        assert "spec" not in r and "config_json" not in r

    def test_lange_rejected_before_adapter_zero_side_effect(self, tmp_path):
        b = lane.edb_build("edb_lange", _PARAMS, workdir=tmp_path)
        assert b["ok"] is False and b["supported"] is False
        assert list(tmp_path.iterdir()) == []  # 拒绝在发射段：零写盘零适配器
        combo = lane.edb_build_solve("edb_lange", _PARAMS, workdir=tmp_path,
                                     solve=True)
        assert combo["ok"] is False and combo["supported"] is False
        assert "build" not in combo and "solve" not in combo  # 短路不进建库段

    def test_unknown_template_lists_supported_and_lange_hint(self):
        r = lane.edb_emit_spec("edb_nope", _PARAMS)
        assert r["ok"] is False and r["errors"]
        msg = r["errors"][0]
        assert "edb_nope" in msg
        for key in ("edb_branchline", "edb_power_divider",
                    "edb_coupled_line", "edb_ratrace"):
            assert key in msg
        assert "edb_lange" in msg and "不支持" in msg


# ── ①service：建库（fake 适配器）─────────────────────────────────────────────


class TestBuild:
    def test_dry_run_zero_write(self, tmp_path):
        workdir = tmp_path / "lane"
        r = lane.edb_build("edb_branchline", _PARAMS, workdir=workdir,
                           dry_run=True)
        assert r["ok"] is True
        assert r["dry_run"] is True
        assert set(r["config"]) >= {"stackup"}
        assert not workdir.exists()  # 零写盘
        assert "aedb_path" not in r

    def test_build_with_fake_adapter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        r = lane.edb_build("edb_branchline", _PARAMS, workdir=tmp_path)
        assert r["ok"] is True
        assert r["aedb_path"].endswith("edb_branchline.aedb")  # 缺省名=template
        assert r["warnings"] == ["fake-warning-占用顺移"]
        (adapter,) = _FakeEdbAdapter.instances
        assert adapter.spec["name"] == "edb_branchline"
        assert len(adapter.spec["traces"]) == 8

    def test_build_explicit_name_passthrough(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        r = lane.edb_build("edb_power_divider", _PARAMS, workdir=tmp_path,
                           name="pd24")
        assert r["ok"] is True
        assert r["aedb_path"].endswith("pd24.aedb")
        assert _FakeEdbAdapter.instances[0].spec["name"] == "pd24"

    def test_adapter_runtime_error_envelope(self, tmp_path, monkeypatch):
        class _Boom:
            def __init__(self, workdir):
                pass

            def build(self, spec):
                raise RuntimeError("pyedb 未安装（fake）")

        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter", _Boom)
        r = lane.edb_build("edb_branchline", _PARAMS, workdir=tmp_path)
        assert r["ok"] is False
        assert r["errors"] and "pyedb 未安装" in r["errors"][0]


# ── ①service：批解+导出（fake hfss_batch 通道，走真实归一路）─────────────────


class TestSolve:
    def _make_project(self, tmp_path: Path) -> Path:
        proj = tmp_path / "demo.aedb"
        proj.mkdir()
        return proj

    def test_missing_project_error_envelope(self, tmp_path):
        r = lane.edb_solve(tmp_path / "nope.aedb")
        assert r["ok"] is False
        assert r["errors"] and "不存在" in r["errors"][0]

    def test_solve_success_with_export(self, tmp_path, monkeypatch):
        proj = self._make_project(tmp_path)
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(
                                project=str(p)))
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: _fake_export_dict(ok=True))
        r = lane.edb_solve(proj)
        assert r["ok"] is True
        assert r["solve"]["ok"] is True and r["solve"]["rc"] == 0
        assert r["export"]["ok"] is True
        assert r["export"]["n_ports"] == 4
        assert r["warnings"] == []

    def test_solve_no_export_skips_leg(self, tmp_path, monkeypatch):
        proj = self._make_project(tmp_path)
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(project=str(p)))
        called: list = []
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: called.append(p) or _fake_export_dict())
        r = lane.edb_solve(proj, export=False)
        assert r["ok"] is True
        assert r["export"] is None  # --no-export：导出段零调用
        assert called == []

    def test_export_failure_is_warning_not_failure(self, tmp_path,
                                                   monkeypatch):
        # #105 best-effort 语义钉：导出失败只并告警，不推翻求解 ok
        proj = self._make_project(tmp_path)
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(project=str(p)))
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: _fake_export_dict(ok=False))
        r = lane.edb_solve(proj)
        assert r["ok"] is True
        assert r["export"]["ok"] is False
        assert r["warnings"] and "导出失败" in r["warnings"][0]

    def test_solve_failure_error_envelope(self, tmp_path, monkeypatch):
        proj = self._make_project(tmp_path)
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(
                                ok=False, project=str(p)))
        r = lane.edb_solve(proj)
        assert r["ok"] is False
        assert r["solve"]["ok"] is False
        assert r["errors"]


class TestBuildSolveCombo:
    def test_build_only_passthrough(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        r = lane.edb_build_solve("edb_branchline", _PARAMS, workdir=tmp_path)
        assert r["ok"] is True
        assert "solve" not in r  # solve=False：批解段零触碰
        assert r["aedb_path"].endswith(".aedb")

    def test_build_then_solve(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(project=str(p)))
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: _fake_export_dict())
        r = lane.edb_build_solve("edb_branchline", _PARAMS, workdir=tmp_path,
                                 solve=True)
        assert r["ok"] is True
        assert r["build"]["ok"] is True
        assert r["solve"]["solve"]["ok"] is True  # solve 节=edb_solve 信封

    def test_build_failure_short_circuits(self, tmp_path):
        r = lane.edb_build_solve("edb_nope", _PARAMS, workdir=tmp_path,
                                 solve=True)
        assert r["ok"] is False
        assert "build" not in r and "solve" not in r

    def test_solve_failure_merged_error_envelope(self, tmp_path, monkeypatch):
        # W4 审查 P3 信封批：solve 段失败走 error_envelope 构造器——
        # 键集与旧 ok_envelope(ok=ok) 覆盖+手挂 errors 形态等价
        # {ok, errors, template, build, solve}，errors=solve 段错误回传。
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(
                                ok=False, project=str(p)))
        r = lane.edb_build_solve("edb_branchline", _PARAMS, workdir=tmp_path,
                                 solve=True)
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]
        assert all(isinstance(e, str) for e in r["errors"])
        assert set(r) == {"ok", "errors", "template", "build", "solve"}
        assert r["template"] == "edb_branchline"
        assert r["build"]["ok"] is True
        assert r["solve"]["solve"]["ok"] is False


# ── ①service：status（只读扫描）──────────────────────────────────────────────


class TestStatus:
    def test_missing_root_honest_empty(self, tmp_path):
        r = lane.edb_status(tmp_path / "absent")
        assert r["ok"] is True
        assert r["n_projects"] == 0 and r["items"] == []

    def test_populated_inventory(self, tmp_path):
        stem = "edb_branchline"
        (tmp_path / f"{stem}.aedb").mkdir()
        for suffix in ("_config.json", "_spec.json", "_export.s2p"):
            (tmp_path / f"{stem}{suffix}").write_text("x", encoding="utf-8")
        (tmp_path / f"ansysedt_batch_{stem}.log").write_text(
            "x", encoding="utf-8")
        (tmp_path / f"ansysedt_batch_extract_{stem}.log").write_text(
            "x", encoding="utf-8")
        (tmp_path / "unrelated.txt").write_text("x", encoding="utf-8")
        r = lane.edb_status(tmp_path)
        assert r["ok"] is True and r["n_projects"] == 1
        (row,) = r["items"]
        assert row["stem"] == stem
        assert row["aedb"] and row["config_json"] and row["solve_log"]
        assert row["extract_log"] and row["touchstone"] and row["spec_json"]
        assert row["solved"] is True

    def test_partial_inventory_none_for_missing(self, tmp_path):
        (tmp_path / "solo.aedb").mkdir()
        r = lane.edb_status(tmp_path)
        assert r["n_projects"] == 1
        (row,) = r["items"]
        assert row["aedb"] and row["solved"] is False
        assert row["config_json"] is None and row["touchstone"] is None

    def test_template_catalog_five_families(self, tmp_path):
        """五族清单随信封走（空表也带）：四支持族 + lange 结构化不支持。"""
        r = lane.edb_status(tmp_path / "absent")
        assert r["ok"] is True
        cat = r["templates"]
        assert len(cat) == 5
        # 确定序：四支持族键序在前，lange 声明不支持殿后
        assert [row["template"] for row in cat] == [
            "edb_branchline", "edb_coupled_line", "edb_power_divider",
            "edb_ratrace", "edb_lange"]
        by = {row["template"]: row for row in cat}
        for key in ("edb_branchline", "edb_power_divider",
                    "edb_coupled_line", "edb_ratrace"):
            assert by[key]["supported"] is True
            assert "reason" not in by[key]
        lange = by["edb_lange"]
        assert lange["supported"] is False
        assert "不支持" in lange["reason"]
        assert lange["upgrade_doc"] == "docs/templates/edb_lange/meta.yaml"
        # 拒绝信封与 status 清单的 lange 文案同源（单源纪律）
        rej = lane.edb_emit_spec("edb_lange", _PARAMS)
        assert rej["reason"] == lange["reason"]

    def test_template_catalog_present_in_populated_root(self, tmp_path):
        (tmp_path / "demo.aedb").mkdir()
        r = lane.edb_status(tmp_path)
        assert r["n_projects"] == 1
        assert len(r["templates"]) == 5


# ── ②CLI 三叶 ────────────────────────────────────────────────────────────────


class TestCliHelpHygiene:
    """全叶 --json 旗标在位 + 自写 help 文本无裸 % 与方括号。

    渲染面只断 %（#305：裸 % 炸 --help format 扩展）；方括号断言钉在
    typer 命令 help 字符串本面——click/rich 自己的 usage 脚手架
    （``[OPTIONS]``/``[default: ...]``）含方括号属正常产物，不算我方
    help 文本违规（rich markup 吞字面只发生在自写文本里）。
    """

    @pytest.mark.parametrize("leaf", ["build", "solve", "status"])
    def test_help_clean_and_json_flag(self, leaf):
        from rfauto.cli.domains.edb import edb_app

        r = runner.invoke(root_app, ["edb", leaf, "--help"])
        assert r.exit_code == 0, r.output
        assert "%" not in r.output
        assert "--json" in r.output
        # 自写 help 文本面（app 描述+该叶 docstring）零裸 % 零方括号
        info = edb_app.info.help or ""
        assert "%" not in info and "[" not in info
        (cmd_info,) = [c for c in edb_app.registered_commands
                       if c.name == leaf]
        help_text = cmd_info.help or ""
        assert "%" not in help_text and "[" not in help_text


class TestCliBuild:
    def test_dry_run_json_envelope(self):
        r = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_branchline", "-p", "f0_ghz=2.4",
            "--dry-run", "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True and data["dry_run"] is True
        assert len(data["spec"]["traces"]) == 8

    def test_failure_envelope_exit_1(self):
        r = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_branchline", "-p", "f0_ghz=2.4",
            "-p", "z0_ohm=40", "--json"])
        assert r.exit_code == 1
        data = json.loads(r.output)
        assert data["ok"] is False and data["errors"]

    def test_build_real_path_fake_adapter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rfauto.adapters.edb_adapter.EdbAdapter",
                            _FakeEdbAdapter)
        r = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_power_divider", "-p", "f0_ghz=2.4",
            "--workdir", str(tmp_path), "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True
        assert data["aedb_path"].endswith("edb_power_divider.aedb")
        assert data["warnings"] == ["fake-warning-占用顺移"]

    def test_dry_run_human_path(self):
        r = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_branchline", "-p", "f0_ghz=2.4",
            "--dry-run"])
        assert r.exit_code == 0, r.output
        assert "dry-run" in r.output

    def test_lange_json_envelope_structured(self):
        """CLI 面 lange 拒绝：退出码 1 + 结构化信封字段透传（--json 同构）。"""
        r = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_lange", "-p", "f0_ghz=2.4", "--json"])
        assert r.exit_code == 1, r.output
        data = json.loads(r.output)
        assert data["ok"] is False
        assert data["template"] == "edb_lange"
        assert data["supported"] is False
        assert data["upgrade_doc"] == "docs/templates/edb_lange/meta.yaml"

    def test_coupled_line_cli_dry_run_json(self):
        """CLI 面两新族可达：dry-run JSON 信封全通（分派表接线端到端）。"""
        r = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_coupled_line", "-p", "f0_ghz=2.4",
            "--dry-run", "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True and data["dry_run"] is True
        assert data["template"] == "edb_coupled_line"
        assert len(data["spec"]["traces"]) == 6
        r2 = runner.invoke(root_app, [
            "edb", "build", "-t", "edb_ratrace", "-p", "f0_ghz=2.4",
            "--dry-run", "--json"])
        assert r2.exit_code == 0, r2.output
        data2 = json.loads(r2.output)
        assert data2["ok"] is True
        assert len(data2["spec"]["traces"]) == 12


class TestCliSolve:
    def test_missing_project_exit_1(self, tmp_path):
        r = runner.invoke(root_app, [
            "edb", "solve", str(tmp_path / "nope.aedb"), "--json"])
        assert r.exit_code == 1
        data = json.loads(r.output)
        assert data["ok"] is False

    def test_solve_success_json(self, tmp_path, monkeypatch):
        proj = tmp_path / "demo.aedb"
        proj.mkdir()
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(project=str(p)))
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: _fake_export_dict())
        r = runner.invoke(root_app, ["edb", "solve", str(proj), "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True
        assert data["export"]["n_ports"] == 4

    def test_no_export_flag_reaches_service(self, tmp_path, monkeypatch):
        proj = tmp_path / "demo.aedb"
        proj.mkdir()
        monkeypatch.setattr("rfauto.adapters.hfss_batch.solve_project_batch",
                            lambda p, **kw: _fake_solve_dict(project=str(p)))
        called: list = []
        monkeypatch.setattr(
            "rfauto.adapters.hfss_batch.export_touchstone_after_solve",
            lambda p, **kw: called.append(p) or _fake_export_dict())
        r = runner.invoke(root_app, [
            "edb", "solve", str(proj), "--no-export", "--json"])
        assert r.exit_code == 0, r.output
        assert called == []


class TestCliStatus:
    def test_empty_root_json(self, tmp_path):
        r = runner.invoke(root_app, [
            "edb", "status", "--root", str(tmp_path), "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["ok"] is True and data["n_projects"] == 0

    def test_populated_json_and_human(self, tmp_path):
        (tmp_path / "demo.aedb").mkdir()
        (tmp_path / "demo_config.json").write_text("{}", encoding="utf-8")
        r = runner.invoke(root_app, [
            "edb", "status", "--root", str(tmp_path), "--json"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["n_projects"] == 1
        r2 = runner.invoke(root_app, [
            "edb", "status", "--root", str(tmp_path)])
        assert r2.exit_code == 0, r2.output
        assert "demo" in r2.output


# ── ③MCP 三工具（转发钉+信封钉）──────────────────────────────────────────────


class TestMcpTools:
    def test_emit_spec_forwards_to_service(self, monkeypatch):
        sentinel = {"ok": True, "template": "edb_branchline", "spec": {},
                    "config_json": {}}
        seen: list = []

        def _fake(template, params, out_dir=None):
            seen.append((template, params, out_dir))
            return sentinel

        monkeypatch.setattr(lane, "edb_emit_spec", _fake)
        assert mcp_edb_emit_spec({"template": "edb_branchline",
                                  "params": {"f0_ghz": 2.4}}) is sentinel
        assert seen == [("edb_branchline", {"f0_ghz": 2.4}, None)]

    def test_build_solve_forwards_flags(self, monkeypatch):
        sentinel = {"ok": True, "aedb_path": "x.aedb"}
        seen: list = []

        def _fake(template, params, **kwargs):
            seen.append((template, params, kwargs))
            return sentinel

        monkeypatch.setattr(lane, "edb_build_solve", _fake)
        out = mcp_edb_build_solve({
            "template": "edb_power_divider", "params": {"f0_ghz": 2.4},
            "workdir": "w", "name": "pd", "dry_run": True, "solve": True,
            "timeout_s": 60.0, "export": False})
        assert out is sentinel
        assert seen == [("edb_power_divider", {"f0_ghz": 2.4},
                         {"workdir": "w", "name": "pd", "dry_run": True,
                          "solve": True, "timeout_s": 60.0,
                          "export": False})]

    def test_status_forwards_root(self, monkeypatch):
        sentinel = {"ok": True, "root": "r", "n_projects": 0, "items": []}
        seen: list = []
        monkeypatch.setattr(lane, "edb_status",
                            lambda root: seen.append(root) or sentinel)
        assert mcp_edb_status({"root": "r"}) is sentinel
        assert seen == ["r"]

    def test_programming_error_returns_error_envelope(self):
        out = mcp_edb_emit_spec({"template": "edb_nope"})
        assert out["ok"] is False and out["errors"]

    def test_live_emit_via_tool(self):
        """端到端：工具面直调发射（确定性内核，零 fake 零真机）。"""
        out = mcp_edb_emit_spec({"template": "edb_branchline",
                                 "params": {"f0_ghz": 2.4}})
        assert out["ok"] is True
        assert len(out["spec"]["ports"]) == 4


# ── ④MCP resources 两件（只读快车道状态面，2026-10-08）───────────────────────


class TestMcpResources:
    """``rfauto://edb/status`` 与 ``rfauto://edb/datasets`` 资源体钉。

    注册面计数（resources 5→7）的集中钉在 test_mcp_server/
    test_mcp_tool_consistency/test_check_numbers（五钉清单批纪律）；
    本类自证资源体接线：service 层既有函数同源薄包装（规则 4）、
    summary 聚合只注成功信封、失败信封原样透传（不臆造）、端到端
    read_resource JSON 文本形态。
    """

    @staticmethod
    def _read_text(mcp, uri: str) -> str:
        import anyio

        content = anyio.run(lambda: mcp.read_resource(uri))
        if isinstance(content, list):
            return content[0].text
        return content.contents[0].content  # fastmcp 3.x ResourceResult

    def test_registered_uris(self):
        import asyncio

        from rfauto.mcp_server import mcp

        uris = {str(r.uri) for r in asyncio.run(mcp.list_resources())}
        assert {"rfauto://edb/status",
                "rfauto://edb/datasets"} <= uris

    def test_status_resource_enriches_summary(self, monkeypatch):
        from rfauto.mcp_tools.edb import edb_status_resource

        sentinel_items = [
            {"stem": "a", "solved": True, "touchstone": "a_export.s2p",
             "config_json": None, "spec_json": None},
            {"stem": "b", "solved": False, "touchstone": None,
             "config_json": "b_config.json", "spec_json": "b_spec.json"},
        ]
        seen: list = []
        monkeypatch.setattr(
            lane, "edb_status",
            lambda root="runs/edb_lane": seen.append(root) or {
                "ok": True, "root": root, "n_projects": 2,
                "items": sentinel_items, "templates": []})
        out = edb_status_resource()
        assert seen == ["runs/edb_lane"]  # 缺省产物根透传
        assert out["items"] == sentinel_items  # 信封主体同源透传
        assert out["summary"] == {"n_solved": 1, "n_touchstone": 1,
                                  "n_config_json": 1, "n_spec_json": 1}

    def test_status_resource_error_envelope_no_summary(self, monkeypatch):
        # 失败信封原样透传：summary 只注成功面，不臆造统计
        from rfauto.mcp_tools.edb import edb_status_resource

        boom = {"ok": False, "errors": ["产物根目录不可读"]}
        monkeypatch.setattr(lane, "edb_status",
                            lambda root="runs/edb_lane": boom)
        assert edb_status_resource() is boom
        assert "summary" not in boom

    def test_datasets_resource_prefix_filter(self, monkeypatch):
        from rfauto.mcp_tools.edb import edb_datasets_resource
        from rfauto.service import dataset_insights

        fake = {"ok": True, "out_dir": "runs/datasets", "n_datasets": 3,
                "datasets": [
                    {"name": "edb_lane_a", "n_points": 3},
                    {"name": "datafactory_b", "n_points": 9},
                    {"name": "edb_lane_c", "n_points": 1},
                ]}
        seen: list = []
        monkeypatch.setattr(dataset_insights, "list_datasets",
                            lambda **kw: seen.append(kw) or fake)
        out = edb_datasets_resource()
        assert seen == [{}]  # 缺省参数调用（缺省注册表根 runs/datasets）
        assert [d["name"] for d in out["datasets"]] == [
            "edb_lane_a", "edb_lane_c"]  # 他族数据集不混入
        assert out["n_datasets"] == 2
        assert out["out_dir"] == "runs/datasets"

    def test_datasets_resource_error_envelope_passthrough(self, monkeypatch):
        from rfauto.mcp_tools.edb import edb_datasets_resource
        from rfauto.service import dataset_insights

        boom = {"ok": False, "errors": ["boom"]}
        monkeypatch.setattr(dataset_insights, "list_datasets",
                            lambda **kw: boom)
        assert edb_datasets_resource() is boom

    def test_read_resource_end_to_end_json(self, tmp_path, monkeypatch):
        """端到端：chdir 隔离 tmp 根，read_resource 真读 JSON 文本形态。"""
        from rfauto.mcp_server import mcp

        monkeypatch.chdir(tmp_path)
        lane_root = tmp_path / "runs" / "edb_lane"
        lane_root.mkdir(parents=True)
        (lane_root / "demo.aedb").mkdir()
        (lane_root / "demo_config.json").write_text("{}", encoding="utf-8")
        ds_dir = tmp_path / "runs" / "datasets" / "edb_lane_demo_20261009"
        ds_dir.mkdir(parents=True)
        (ds_dir / "dataset_manifest.yaml").write_text(
            "schema_version: '2.0'\nname: edb_lane_demo_20261009\n"
            "n_points: 2\nvisibility: private\n", encoding="utf-8")

        st = json.loads(self._read_text(mcp, "rfauto://edb/status"))
        assert st["ok"] is True and st["n_projects"] == 1
        assert st["summary"]["n_config_json"] == 1
        assert len(st["templates"]) == 5  # 五族清单随资源走
        dsr = json.loads(self._read_text(mcp, "rfauto://edb/datasets"))
        assert dsr["ok"] is True and dsr["n_datasets"] == 1
        assert dsr["datasets"][0]["name"] == "edb_lane_demo_20261009"
        assert dsr["datasets"][0]["visibility"] == "private"
