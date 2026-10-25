"""verdict 摘要面测试（aurora_g W8-S4，2026-10-19）。

钉三件事：
1. 提取层确定性：平铺族（status+g 门键+复合 dict-ok 门+rc 门）与嵌套族
   （arms.checks）的门/指标/总判定提取；
2. Markdown 渲染同输入逐字节同输出（确定性渲染面，零时间戳）+管道符
   转义；
3. 错误路径信封（缺失/坏 JSON/穿越段）+ CLI 双路径冒烟（--json 成功+
   失败同构，#139 不触网、全离线 tmp 夹具）。

chdir tmp 隔离（#144）；runs 根解析走 infra/runs_paths cwd 优先三态，
tmp/runs 存在即生效。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.main import app as root_app
from rfauto.service.verdict_summary_service import (
    verdict_summary,
    verdict_summary_md,
)

# 平铺族（aurora_c_oe/aurora_d 战役档形态）：status + g 门键 + 复合门 + rc
_FLAT_VERDICT = {
    "template": "mline",
    "started": "2026-10-19 08:00:00",
    "status": "PASS",
    "g1_render": True,
    "mesh_mm": 0.4,
    "exec_rc": 0,
    "solve_success": True,
    "g3_finite": True,
    "g3_passive_le_1p05": False,
    "g5_health": {"verdict": "unhealthy", "ok": False},
    "nrts_converged": {"ok": True, "reason": "EndCriteria 提前停机",
                       "min_energy_db": -60.25, "iterations_done": 31439},
    "fetch": {"files": 35, "bytes": 1589570},
    "grpc_port": 50051,
}

# 嵌套族（designs_verify arms.checks 形态）
_NESTED_VERDICT = {
    "task": "designs 真机核实",
    "verdict": "DONE",
    "arms": {
        "arm1": {
            "arm": "arm1",
            "rc": 0,
            "checks": {"c1_flag_accepted": True, "c2_limited_designs": False},
        },
    },
}


@pytest.fixture
def verdict_env(tmp_path, monkeypatch):
    """tmp/runs 下落两份 verdict 档案 + chdir 隔离（runs 根=cwd 优先）。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs" / "camp_a"
    (root / "run_flat").mkdir(parents=True)
    (root / "run_flat" / "verdict.json").write_text(
        json.dumps(_FLAT_VERDICT, ensure_ascii=False), encoding="utf-8")
    (root / "run_nested").mkdir(parents=True)
    (root / "run_nested" / "verdict.json").write_text(
        json.dumps(_NESTED_VERDICT, ensure_ascii=False), encoding="utf-8")
    return tmp_path


class TestVerdictSummary:
    def test_flat_family_gates_status_metrics(self, verdict_env):
        """平铺族：总判定/布尔门/复合门/rc 门/指标提取逐键钉。"""
        r = verdict_summary("camp_a/run_flat")
        assert r["ok"], r.get("errors")
        assert r["status"] == "PASS" and r["status_key"] == "status"
        assert r["run_id"] == "run_flat"
        assert r["meta"]["template"] == "mline"
        gates = {g["path"]: g for g in r["gates"]}
        # 布尔门：True/False 原值透传
        assert gates["g1_render"]["ok"] is True
        assert gates["g3_passive_le_1p05"]["ok"] is False
        # dry_run 类非门形态布尔不入清单（本档案无该键，防回归钉）
        assert "mesh_mm" not in gates
        # 复合门：dict 含 ok 键（g5_health/nrts_converged），evidence 取
        # verdict/reason 首个字符串
        assert gates["g5_health"]["kind"] == "dict_ok"
        assert gates["g5_health"]["ok"] is False
        assert gates["g5_health"]["evidence"] == "unhealthy"
        assert gates["nrts_converged"]["evidence"] == "EndCriteria 提前停机"
        # rc 门：exec_rc=0 → PASS
        assert gates["exec_rc"]["kind"] == "rc"
        assert gates["exec_rc"]["ok"] is True
        assert r["n_gates_pass"] == 5 and r["n_gates_fail"] == 2
        # 指标：数值叶子透传（复合门内嵌数值也在），噪声键/grpc_port 剔除
        metrics = {m["path"]: m["value"] for m in r["key_metrics"]}
        assert metrics["mesh_mm"] == 0.4
        assert metrics["nrts_converged.min_energy_db"] == -60.25
        assert metrics["fetch.files"] == 35
        assert "grpc_port" not in metrics
        assert "exec_rc" not in metrics
        assert not r["truncated"]

    def test_nested_family_checks_collected(self, verdict_env):
        """嵌套族：verdict 键作总判定；arms.checks 逐叶布尔成门（深度 ≤3）。"""
        r = verdict_summary("camp_a/run_nested")
        assert r["ok"], r.get("errors")
        assert r["status"] == "DONE" and r["status_key"] == "verdict"
        gates = {g["path"]: g for g in r["gates"]}
        assert gates["arms.arm1.checks.c1_flag_accepted"]["ok"] is True
        assert gates["arms.arm1.checks.c2_limited_designs"]["ok"] is False
        assert gates["arms.arm1.rc"]["ok"] is True

    def test_md_deterministic_and_escaping(self, verdict_env):
        """Markdown：同输入逐字节同输出（确定性渲染）；表行齐备；
        管道符按 Markdown 表格语义转义。"""
        md1 = verdict_summary_md("camp_a/run_flat")
        md2 = verdict_summary_md("camp_a/run_flat")
        assert md1 == md2
        assert md1.startswith("# verdict 摘要 — PASS")
        assert "## 门检查" in md1 and "## 关键指标" in md1
        assert "| `g5_health` | FAIL | unhealthy |" in md1
        assert "| `exec_rc` | PASS | rc=0 |" in md1
        # 管道符转义：status 含 | 时不破表
        (verdict_env / "runs" / "camp_a" / "run_pipe").mkdir(parents=True)
        (verdict_env / "runs" / "camp_a" / "run_pipe" / "verdict.json").write_text(
            json.dumps({"status": "PASS|NOTE", "g1_render": True},
                       ensure_ascii=False), encoding="utf-8")
        md3 = verdict_summary_md("camp_a/run_pipe")
        assert "PASS\\|NOTE" in md3

    def test_error_paths_envelope(self, verdict_env):
        """缺失/坏 JSON/穿越段 → ok=False 信封 errors 恒 list[str]；
        md 渲染层不抛（返回"摘要不可用"说明串）。"""
        r = verdict_summary("camp_a/no_such_run")
        assert r["ok"] is False and isinstance(r["errors"], list)
        assert all(isinstance(e, str) for e in r["errors"])
        bad = verdict_env / "runs" / "camp_a" / "run_bad"
        bad.mkdir(parents=True)
        (bad / "verdict.json").write_text("{not json", encoding="utf-8")
        r2 = verdict_summary("camp_a/run_bad")
        assert r2["ok"] is False and r2["errors"]
        # 穿越段拒绝（runs 根防逃逸）
        r3 = verdict_summary("../outside")
        assert r3["ok"] is False
        md = verdict_summary_md("camp_a/no_such_run")
        assert md.startswith("verdict 摘要不可用")


class TestVerdictSummaryCli:
    def test_json_dual_path_smoke(self, verdict_env):
        """CLI --json 双路径冒烟：成功信封与失败信封同构（--json 下失败
        路径不许非 JSON，#24 口径）；md 形态信封带 markdown 键。"""
        runner = CliRunner()
        ok = runner.invoke(
            root_app, ["verdict-summary", "camp_a/run_flat", "--json"])
        assert ok.exit_code == 0, ok.output
        payload = json.loads(ok.output)
        assert payload["ok"] is True and payload["status"] == "PASS"
        ok_md = runner.invoke(
            root_app,
            ["verdict-summary", "camp_a/run_flat", "--format", "md", "--json"])
        assert ok_md.exit_code == 0, ok_md.output
        payload_md = json.loads(ok_md.output)
        assert payload_md["ok"] is True
        assert payload_md["markdown"].startswith("# verdict 摘要 — PASS")
        fail = runner.invoke(
            root_app, ["verdict-summary", "camp_a/no_such_run", "--json"])
        assert fail.exit_code == 1
        payload_fail = json.loads(fail.output)
        assert payload_fail["ok"] is False
        assert isinstance(payload_fail["errors"], list) and payload_fail["errors"]

    def test_md_plain_output_and_bad_format(self, verdict_env):
        """缺省 md 直出（markup=False 纯文本）；--format 非法 → usage
        类退出码 2 且 --json 下走 JSON 信封；--format json 单独使用
        （不带 --json）也必须结构化直出（W16-S4 终验：此前静默零输出）。"""
        runner = CliRunner()
        plain = runner.invoke(root_app, ["verdict-summary", "camp_a/run_flat"])
        assert plain.exit_code == 0, plain.output
        assert plain.output.startswith("# verdict 摘要 — PASS")
        fmt_json = runner.invoke(
            root_app, ["verdict-summary", "camp_a/run_flat",
                       "--format", "json"])
        assert fmt_json.exit_code == 0, fmt_json.output
        payload_fj = json.loads(fmt_json.output)
        assert payload_fj["ok"] is True and payload_fj["status"] == "PASS"
        bad = runner.invoke(
            root_app, ["verdict-summary", "camp_a/run_flat",
                       "--format", "yaml", "--json"])
        assert bad.exit_code == 2
        assert json.loads(bad.output)["ok"] is False
