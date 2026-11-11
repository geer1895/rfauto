"""aedt-migrate CLI 三叶测试（aurora_r AM-S4，纯离线零 AEDT）。

覆盖（CliRunner 直连 aedt_migrate_app——不触共享 app 侧写面；接线由
五钉锚文件与注册序金快照钉）：
- run：--json 信封成败双路（成功=批量信封 counts/results；无 --input=
  usage 错 exit 2 JSON 信封 #ge1㉙；输入不存在=error 信封 exit 1）+
  参数透传（inputs/work_root 逐字到 service.migrate_batch，monkeypatch
  服务边界）+ 执行器缺位诚实 error 行（不伪造 verdict，#122）；
- status/report：真报告（service migrate_batch+fake executors 产线
  MIGRATED_DIRECT_PASS / FAILED_OPEN 两 verdict）--json 成路 + 人读分
  支 exit 0 + report --json 报告原文逐键透传；坏文件三态（不存在/
  非 JSON/缺 verdict 键）exit 2；
- help 卫生冒烟：组+三叶 --help exit 0（#305 家法：parser 真构建，
  字符卫生全树门由 test_cli_help_text_hygiene 常驻）；
- 信封契约：--json 下失败路径恒 JSON（errors 恒 list），零红字裸文本。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.domains.aedt_migrate import aedt_migrate_app
from rfauto.service import aedt_migrate_service
from rfauto.service.aedt_migrate_service import CHECK_KEYS

runner = CliRunner()


# ---------------------------------------------------------------------------
# fixture：假 .aedt 工程（纯文件，收集面只看后缀+存在性）
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_project(tmp_path: Path) -> Path:
    p = tmp_path / "legacy_pd.aedt"
    p.write_text("dummy aedt project placeholder", encoding="utf-8")
    return p


class _FakeExecutors:
    """三必需执行器 fake（service 单测同款契约；outcome 可脚本化）。"""

    def __init__(self, open_outcome: str = "success"):
        self.open_outcome = open_outcome

    def direct_open(self, project_path, context):
        return {"outcome": self.open_outcome, "messages": [f"open:{self.open_outcome}"]}

    def health(self, project_path, context):
        return {
            "ok": True,
            "geometry_error": False,
            "checks": {k: True for k in CHECK_KEYS},
            "messages": ["health:ok"],
        }

    def compare(self, project_path, context):
        return {
            "has_baseline": True,
            "baseline_kind": "sparams",
            "deltas": {"s21_db": 0.001},
            "messages": ["compare:ok"],
        }

    def mapping(self):
        return {
            "direct_open": self.direct_open,
            "health": self.health,
            "compare": self.compare,
        }


def _make_report(tmp_path: Path, open_outcome: str = "success") -> dict:
    """经 service 产线跑一份真迁移报告，返回批量信封（results[0] 含
    report_path；status/report 两叶消费同一文件）。"""
    project = tmp_path / f"proj_{open_outcome}.aedt"
    project.write_text("x", encoding="utf-8")
    work = tmp_path / f"work_{open_outcome}"
    envelope = aedt_migrate_service.migrate_batch(
        [str(project)],
        executors=_FakeExecutors(open_outcome).mapping(),
        work_root=work,
    )
    assert envelope["ok"] is True, envelope
    return envelope


# ---------------------------------------------------------------------------
# run 叶
# ---------------------------------------------------------------------------


def test_cli_run_json_passthrough_and_envelope(tmp_path, monkeypatch):
    """参数透传钉：inputs 列表+work_root 逐字到 migrate_batch（服务边界
    monkeypatch——CLI 薄壳零逻辑的正面证明）。"""
    seen: dict = {}

    def fake_batch(inputs, config=None, executors=None, work_root=None,
                   yaml_path=None):
        seen["inputs"] = list(inputs)
        seen["work_root"] = work_root
        return {"ok": True, "work_root": str(work_root), "total": 0,
                "results": [], "counts": {}}

    monkeypatch.setattr(aedt_migrate_service, "migrate_batch", fake_batch)
    proj = tmp_path / "a.aedt"
    proj.write_text("x", encoding="utf-8")
    work = tmp_path / "w"
    res = runner.invoke(
        aedt_migrate_app,
        ["run", "--input", str(proj), "--input", str(tmp_path),
         "--work-root", str(work), "--json"])
    assert res.exit_code == 0, res.output
    assert seen["inputs"] == [str(proj), str(tmp_path)]
    assert seen["work_root"] == str(work)
    envelope = json.loads(res.output)
    assert envelope["ok"] is True


def test_cli_run_executor_missing_honest_error_row(tmp_path, fake_project):
    """CLI 直跑（无真机执行器）→ 批量信封 ok=True 但逐工程 error 行
    （响亮 ValueError 入行，不伪造 verdict——S1 service 契约原文）。"""
    work = tmp_path / "w"
    res = runner.invoke(
        aedt_migrate_app,
        ["run", "--input", str(fake_project), "--work-root", str(work),
         "--json"])
    assert res.exit_code == 0, res.output
    envelope = json.loads(res.output)
    assert envelope["ok"] is True
    assert envelope["counts"].get("error") == 1
    row = envelope["results"][0]
    assert row["ok"] is False
    assert "executor" in ";".join(row["errors"])
    assert "verdict" not in row


def test_cli_run_missing_input_usage_error():
    """无 --input → usage 错 exit 2；--json 下 JSON 信封禁红字裸文本。"""
    res = runner.invoke(aedt_migrate_app, ["run", "--json"])
    assert res.exit_code == 2
    envelope = json.loads(res.output)
    assert envelope["ok"] is False
    assert isinstance(envelope["errors"], list) and envelope["errors"]


def test_cli_run_bad_input_error_envelope(tmp_path):
    """输入不存在 → collect 守卫 error 信封 exit 1（--json 恒 JSON）。"""
    res = runner.invoke(
        aedt_migrate_app,
        ["run", "--input", str(tmp_path / "nope.aedt"), "--json"])
    assert res.exit_code == 1
    envelope = json.loads(res.output)
    assert envelope["ok"] is False
    assert isinstance(envelope["errors"], list) and envelope["errors"]


def test_cli_run_human_branch(tmp_path, fake_project):
    """人读分支 exit 0（批量信封行渲染；无异常即过）。"""
    work = tmp_path / "w"
    res = runner.invoke(
        aedt_migrate_app,
        ["run", "--input", str(fake_project), "--work-root", str(work)])
    assert res.exit_code == 0, res.output
    assert "批量完成" in res.output


# ---------------------------------------------------------------------------
# status / report 叶（真报告产线）
# ---------------------------------------------------------------------------


@pytest.fixture()
def pass_report(tmp_path):
    return _make_report(tmp_path, "success")


@pytest.fixture()
def fail_report(tmp_path):
    return _make_report(tmp_path, "error")


def test_cli_status_json_envelope(tmp_path, pass_report):
    report_path = pass_report["results"][0]["report_path"]
    res = runner.invoke(
        aedt_migrate_app, ["status", "--report", report_path, "--json"])
    assert res.exit_code == 0, res.output
    env = json.loads(res.output)
    assert env["ok"] is True
    assert env["verdict"] == "MIGRATED_DIRECT_PASS"
    assert env["stage_reached"] == "S0→S1→S2→S3"
    assert env["project"] == "proj_success"
    assert env["n_messages"] >= 1
    assert env["checks"]["materials"] is True


def test_cli_status_human_branch(pass_report):
    report_path = pass_report["results"][0]["report_path"]
    res = runner.invoke(aedt_migrate_app, ["status", "--report", report_path])
    assert res.exit_code == 0, res.output
    assert "MIGRATED_DIRECT_PASS" in res.output


def test_cli_status_human_branch_failed_verdict(fail_report):
    """FAILED_OPEN 报告人读分支如实渲染失败终态（零凑绿零重试）。"""
    report_path = fail_report["results"][0]["report_path"]
    res = runner.invoke(aedt_migrate_app, ["status", "--report", report_path])
    assert res.exit_code == 0, res.output
    assert "FAILED_OPEN" in res.output


def test_cli_report_json_passthrough_fidelity(pass_report):
    """report --json = 报告原文逐键透传（CLI 不裁面不加工——审计消费面）。"""
    report_path = pass_report["results"][0]["report_path"]
    on_disk = json.loads(Path(report_path).read_text(encoding="utf-8"))
    res = runner.invoke(
        aedt_migrate_app, ["report", "--report", report_path, "--json"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output) == on_disk


def test_cli_report_human_branch_sections(pass_report):
    report_path = pass_report["results"][0]["report_path"]
    res = runner.invoke(aedt_migrate_app, ["report", "--report", report_path])
    assert res.exit_code == 0, res.output
    assert "迁移报告" in res.output
    assert "MIGRATED_DIRECT_PASS" in res.output


# ---------------------------------------------------------------------------
# 坏文件三态（exit 2 usage 家法，#ge1㉙ --json 恒 JSON 信封）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "label"),
    [(None, "missing"), ("{not json", "bad_json"), ('{"schema": "x"}', "no_verdict")],
)
def test_cli_status_bad_report_three_states(tmp_path, content, label):
    if content is None:
        report = tmp_path / "no_such_report.json"
    else:
        report = tmp_path / "broken.json"
        report.write_text(content, encoding="utf-8")
    res = runner.invoke(
        aedt_migrate_app, ["status", "--report", str(report), "--json"])
    assert res.exit_code == 2, (label, res.output)
    envelope = json.loads(res.output)
    assert envelope["ok"] is False
    assert isinstance(envelope["errors"], list) and envelope["errors"]


def test_cli_report_bad_report_json_envelope(tmp_path):
    report = tmp_path / "no_such_report.json"
    res = runner.invoke(
        aedt_migrate_app, ["report", "--report", str(report), "--json"])
    assert res.exit_code == 2
    assert json.loads(res.output)["ok"] is False


# ---------------------------------------------------------------------------
# help 卫生冒烟（#305 家法：parser 真构建跑 --help）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv", [["--help"], ["run", "--help"], ["status", "--help"],
             ["report", "--help"]])
def test_cli_help_smoke(argv):
    res = runner.invoke(aedt_migrate_app, argv)
    assert res.exit_code == 0, res.output


def test_cli_leaves_carry_json_flag():
    """三叶全带 --json（合流期"新面必红清单"①，本地镜像钉）。"""
    from typer.main import get_command

    cmd = get_command(aedt_migrate_app)
    for leaf in ("run", "status", "report"):
        flags = {o for p in cmd.commands[leaf].params for o in getattr(p, "opts", ())}
        assert "--json" in flags, leaf
