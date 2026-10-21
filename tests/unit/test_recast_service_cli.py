"""RECAST 判据重放服务+CLI 薄壳测试（2026-10-11 架构批 W2-D）。

覆盖面（教程-代码断链清偿：docs/tutorials/recast-walkthrough.md 此前
无 CLI/MCP 壳）：
- TestRecastService：recast_status（真注册源 3 判据全合格；目录缺失
  error 信封；坏 YAML 条目如实登记）；recast_replay（threshold_gate
  合成判据 same/flip 两向；evidence_paths 绑定；archived_verdict_path
  缺省/none/错路径三态；坏证据条目登记继续；全坏 error 信封）；
- TestRecastCli：CliRunner 驱动真实入口——两叶注册面、--json 信封
  解析（status 清单/replay 报告）、flip 退出码仍 0（翻案是成功的重放
  不是命令失败）、全坏证据退出码 1、人类可读面 flip 显眼浮出。

零写盘零归档改写（#325/#326）：全部输入走 tmp 合成，真注册源只读。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.main import app
from rfauto.service.recast_service import (
    recast_replay,
    recast_status,
)

runner = CliRunner()

_REPO = Path(__file__).resolve().parents[2]
_REAL_CRITERIA = _REPO / "knowledge" / "criteria" / "v2"

_CRITERIA_YAML = """\
schema: criteria/v2
criteria_id: w2d_synthetic_gate
title: W2-D 合成阈值门（本测试专用合成判据，零物理语义）
status: active_v2
runner_binding: none
claim:
  quantity: probe_score
  template: synthetic
  f_ghz: 1.0
evidence_fields:
  - probe.score
u_val:
  u_num:
    source: none_declared
    rule: 合成判据无不确定度可估——unknown 不虚构
  u_input:
    source: none_declared
    rule: 同上
  u_D:
    source: none_declared
    rule: 同上
decision_rule:
  form: threshold_gate
  threshold: 10.0
  comparison: ">="
verdict_map:
  PASS: validated
  FAIL: not_validated
provenance:
  commit: synthetic
"""


def _criteria_dir(tmp_path: Path) -> Path:
    d = tmp_path / "criteria"
    d.mkdir()
    (d / "w2d_synthetic_gate.yaml").write_text(
        _CRITERIA_YAML, encoding="utf-8")
    return d


def _artifact(tmp_path: Path, *, score: float, verdict: str) -> Path:
    p = tmp_path / f"art_{score}_{verdict}.json"
    p.write_text(json.dumps(
        {"probe": {"score": score}, "verdict": verdict}), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 服务面
# ---------------------------------------------------------------------------

class TestRecastService:
    def test_status_real_registry_all_ok(self):
        r = recast_status(_REAL_CRITERIA)
        assert r["ok"] is True
        assert r["n_criteria"] == 3
        assert r["n_criteria_ok"] == 3
        ids = {c["criteria_id"] for c in r["criteria"]}
        assert "df6_dp10_scan_j1c_coverage" in ids

    def test_status_missing_dir_error_envelope(self, tmp_path):
        r = recast_status(tmp_path / "nope")
        assert r["ok"] is False
        assert r["errors"]

    def test_status_bad_entry_registered_not_silent(self, tmp_path):
        d = _criteria_dir(tmp_path)
        (d / "broken.yaml").write_text("schema: wrong/v0\n", encoding="utf-8")
        r = recast_status(d)
        assert r["ok"] is True  # 装载面成立；坏条目如实登记不翻车
        bad = [c for c in r["criteria"] if c["name"] == "broken.yaml"]
        assert len(bad) == 1 and bad[0]["ok"] is False
        assert bad[0]["errors"]

    def test_replay_same_direction(self, tmp_path):
        r = recast_replay(
            {"sentinel": _artifact(tmp_path, score=12.0, verdict="PASS")},
            criteria_dir=_criteria_dir(tmp_path),
            evidence_paths={"w2d_synthetic_gate": "probe.score"})
        assert r["ok"] is True, r.get("errors")
        assert r["summary"]["n_pairs"] == 1
        assert r["pairs"][0]["direction"] == "same"
        assert r["replay_ok"] is True

    def test_replay_flip_surfaces_not_swallowed(self, tmp_path):
        """重放 PASS × 归档 FAIL → flip 如实浮出（人工仲裁信号不吞）。"""
        r = recast_replay(
            {"sentinel": _artifact(tmp_path, score=12.0, verdict="FAIL")},
            criteria_dir=_criteria_dir(tmp_path),
            evidence_paths={"w2d_synthetic_gate": "probe.score"})
        assert r["ok"] is True
        assert r["pairs"][0]["direction"] == "flip"
        assert r["summary"]["n_flip"] == 1

    def test_replay_evidence_path_binding(self, tmp_path):
        r = recast_replay(
            {"sentinel": _artifact(tmp_path, score=12.0, verdict="PASS")},
            criteria_dir=_criteria_dir(tmp_path),
            evidence_paths={"w2d_synthetic_gate": "probe.score"})
        assert r["pairs"][0]["replay_verdict"] == "PASS"

    def test_replay_archived_path_none_and_wrong(self, tmp_path):
        art = _artifact(tmp_path, score=12.0, verdict="PASS")
        crit = _criteria_dir(tmp_path)
        ev = {"w2d_synthetic_gate": "probe.score"}
        # none：不比归档侧 → not_judged（重放侧已判 PASS，方向仍如实不判）
        r = recast_replay({"a": art}, criteria_dir=crit,
                          evidence_paths=ev, archived_verdict_path=None)
        assert r["pairs"][0]["replay_verdict"] == "PASS"
        assert r["pairs"][0]["direction"] == "not_judged"
        # 错路径：归档侧取不到 → not_judged（fail-closed 不虚构）
        r2 = recast_replay({"a": art}, criteria_dir=crit,
                           evidence_paths=ev,
                           archived_verdict_path="no.such.path")
        assert r2["pairs"][0]["direction"] == "not_judged"

    def test_replay_bad_artifact_continues_good_one(self, tmp_path):
        crit = _criteria_dir(tmp_path)
        good = _artifact(tmp_path, score=12.0, verdict="PASS")
        bad = tmp_path / "bad.json"
        bad.write_text("not json{", encoding="utf-8")
        r = recast_replay({"good": good, "bad": bad}, criteria_dir=crit)
        assert r["ok"] is True
        assert r["summary"]["n_pairs"] == 1
        assert len(r["artifact_errors"]) == 1
        assert "bad" in r["artifact_errors"][0]

    def test_replay_all_artifacts_bad_error_envelope(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json{", encoding="utf-8")
        r = recast_replay({"bad": bad}, criteria_dir=_criteria_dir(tmp_path))
        assert r["ok"] is False
        assert r["errors"]

    def test_replay_missing_criteria_dir_error_envelope(self, tmp_path):
        r = recast_replay(
            {"a": _artifact(tmp_path, score=1.0, verdict="PASS")},
            criteria_dir=tmp_path / "nope")
        assert r["ok"] is False


# ---------------------------------------------------------------------------
# CLI 面
# ---------------------------------------------------------------------------

class TestRecastCli:
    def test_recast_subapp_registered_with_two_readonly_leaves(self):
        from typer.main import get_command

        cmd = get_command(app)
        recast_cmd = cmd.commands["recast"]
        assert set(recast_cmd.commands) == {"status", "replay"}

    def test_status_json_envelope(self, tmp_path):
        res = runner.invoke(app, ["recast", "status", "--json",
                                  "--criteria-dir", str(_criteria_dir(tmp_path))])
        assert res.exit_code == 0, res.output
        doc = json.loads(res.output)
        assert doc["ok"] is True
        assert doc["n_criteria"] == 1
        assert doc["criteria"][0]["criteria_id"] == "w2d_synthetic_gate"

    def test_status_human_table(self, tmp_path):
        res = runner.invoke(app, ["recast", "status",
                                  "--criteria-dir", str(_criteria_dir(tmp_path))])
        assert res.exit_code == 0, res.output
        assert "w2d_synthetic_gate" in res.output

    def test_replay_json_same_and_flip(self, tmp_path):
        crit = str(_criteria_dir(tmp_path))
        art = str(_artifact(tmp_path, score=12.0, verdict="PASS"))
        res = runner.invoke(app, ["recast", "replay", "--json",
                                  "--criteria-dir", crit, "-a", art,
                                  "--evidence-path",
                                  "w2d_synthetic_gate=probe.score"])
        assert res.exit_code == 0, res.output
        doc = json.loads(res.output)
        assert doc["ok"] is True
        assert doc["pairs"][0]["direction"] == "same"
        # flip 退出码仍 0：翻案是成功的重放，不是命令失败
        art_flip = str(_artifact(tmp_path, score=12.0, verdict="FAIL"))
        res2 = runner.invoke(app, ["recast", "replay", "--json",
                                   "--criteria-dir", crit, "-a", art_flip,
                                   "--evidence-path",
                                   "w2d_synthetic_gate=probe.score"])
        assert res2.exit_code == 0, res2.output
        doc2 = json.loads(res2.output)
        assert doc2["pairs"][0]["direction"] == "flip"
        assert doc2["summary"]["n_flip"] == 1

    def test_replay_human_mode_surfaces_flip_prominently(self, tmp_path):
        crit = str(_criteria_dir(tmp_path))
        art = str(_artifact(tmp_path, score=12.0, verdict="FAIL"))
        res = runner.invoke(app, ["recast", "replay",
                                  "--criteria-dir", crit, "-a", art,
                                  "--evidence-path",
                                  "w2d_synthetic_gate=probe.score"])
        assert res.exit_code == 0, res.output
        assert "flip" in res.output

    def test_replay_all_bad_artifacts_exit_1(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json{", encoding="utf-8")
        res = runner.invoke(app, ["recast", "replay", "--json",
                                  "--criteria-dir", str(_criteria_dir(tmp_path)),
                                  "-a", str(bad)])
        assert res.exit_code == 1
        doc = json.loads(res.output)
        assert doc["ok"] is False

    def test_replay_evidence_path_flag_wiring(self, tmp_path):
        crit = str(_criteria_dir(tmp_path))
        art = str(_artifact(tmp_path, score=12.0, verdict="PASS"))
        res = runner.invoke(app, [
            "recast", "replay", "--json", "--criteria-dir", crit,
            "-a", art, "--evidence-path", "w2d_synthetic_gate=probe.score"])
        assert res.exit_code == 0, res.output
        assert json.loads(res.output)["pairs"][0]["replay_verdict"] == "PASS"
        # 非法形态退出码 2（薄壳参数校验）
        res2 = runner.invoke(app, [
            "recast", "replay", "--criteria-dir", crit, "-a", art,
            "--evidence-path", "malformed"])
        assert res2.exit_code == 2

    def test_replay_bad_evidence_path_json_envelope(self, tmp_path):
        """A5 P1-1：--json 下 --evidence-path 解析失败输出 JSON 信封
        （#ge1㉙ 错误路径禁红字裸文本；exit 2=usage 惯例保留）。"""
        res = runner.invoke(app, [
            "recast", "replay", "--json",
            "--criteria-dir", str(_criteria_dir(tmp_path)),
            "--evidence-path", "malformed"])
        assert res.exit_code == 2, res.output
        data = json.loads(res.output)
        assert data["ok"] is False
        assert ("--evidence-path" in data["errors"][0]
                and "malformed" in data["errors"][0])

    def test_replay_archived_none_flag(self, tmp_path):
        crit = str(_criteria_dir(tmp_path))
        art = str(_artifact(tmp_path, score=12.0, verdict="PASS"))
        res = runner.invoke(app, [
            "recast", "replay", "--json", "--criteria-dir", crit, "-a", art,
            "--archived-verdict-path", "none"])
        assert res.exit_code == 0, res.output
        assert json.loads(res.output)["pairs"][0]["direction"] == "not_judged"

    def test_real_registry_smoke_from_repo_root(self, monkeypatch):
        """真注册源冒烟（cwd=仓根缺省 --criteria-dir）：3 判据可见——
        教程 walkthrough 的命令形态实跑口径。"""
        monkeypatch.chdir(_REPO)
        res = runner.invoke(app, ["recast", "status", "--json"])
        assert res.exit_code == 0, res.output
        doc = json.loads(res.output)
        assert doc["ok"] is True
        assert doc["n_criteria"] == 3

    def test_yaml_roundtrip_of_synthetic_criteria(self, tmp_path):
        """合成判据 YAML 可被 core.load_criteria_dir 消费（合同自检：
        REQUIRED_TOP 全键 truthy——坏在源头时本测试先红，防测试假阳性）。"""
        from rfauto.core.recast import load_criteria_dir

        entries = load_criteria_dir(_criteria_dir(tmp_path))
        assert len(entries) == 1 and entries[0]["ok"] is True
