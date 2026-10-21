"""compare_runs_batch 多 run 收官对账面测试（架构批 W8-S4，2026-10-19）。

钉四件事：对账行并排（verdict status 优先回落 meta.status、wall_s 耗时、
has_verdict）、偏差 top-K 排行（相对极差降序/截断计数）、缺产物容错
（missing 行不传染、errors 记账）、入参校验与 CLI --json 双路径冒烟。

chdir tmp 隔离（#144）；全离线零网络（#139）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.main import app as root_app
from rfauto.service.batch_ops_service import (
    compare_runs_batch,
    compare_runs_batch_md,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def batch_env(tmp_path, monkeypatch):
    """tmp/runs：两个 meta 族 run（有指标+wall_s）+ 一个纯 verdict 族
    战役档目录（无 meta）。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    _write_json(root / "run_a" / "meta.json", {
        "run_id": "run_a", "model": "mline", "adapter": "fake",
        "status": "done", "wall_s": 12.5,
        "metrics": {"s11_db_max_in_band": -10.0, "s21_db_mean_in_band": -3.0,
                    "cost": 0.5}})
    _write_json(root / "run_b" / "meta.json", {
        "run_id": "run_b", "model": "mline", "adapter": "fake",
        "status": "done", "wall_s": 20.0,
        "metrics": {"s11_db_max_in_band": -14.0, "s21_db_mean_in_band": -3.5,
                    "cost": 0.2}})
    _write_json(root / "camp" / "run_v" / "verdict.json", {
        "template": "mline", "status": "FAIL",
        "solve_success": False, "exec_rc": 1})
    return tmp_path


class TestCompareRunsBatch:
    def test_rows_and_deviation_ranking(self, batch_env):
        """并排行：判定双列（verdict 优先）/耗时/cost/指标数；偏差 top-K
        按相对极差降序（s11 4/14 > s21 0.5/3.5），rel_spread 口径钉。"""
        r = compare_runs_batch(["run_a", "run_b", "camp/run_v"])
        assert r["ok"], r.get("errors")
        rows = {row["run_id"]: row for row in r["runs"]}
        assert rows["run_a"]["status"] == "done"
        assert rows["run_a"]["duration_s"] == 12.5
        assert rows["run_a"]["n_metrics"] == 3
        assert rows["camp/run_v"]["status"] == "FAIL"
        assert rows["camp/run_v"]["verdict_status"] == "FAIL"
        assert rows["camp/run_v"]["meta_status"] is None
        assert rows["camp/run_v"]["has_verdict"] is True
        assert rows["camp/run_v"]["model"] == "mline"
        # 偏差排行：纯 verdict 档案无指标不参与；相对极差降序
        # （cost 0.3/0.5=0.6 > s11 4/14≈0.286 > s21 0.5/3.5≈0.143）
        devs = r["deviations"]
        assert [d["metric"] for d in devs[:3]] == [
            "cost", "s11_db_max_in_band", "s21_db_mean_in_band"]
        s11 = devs[1]
        assert s11["spread"] == pytest.approx(4.0)
        assert s11["rel_spread"] == pytest.approx(4.0 / 14.0)
        assert set(s11["values"]) == {"run_a", "run_b"}
        assert devs[0]["rel_spread"] == pytest.approx(0.6)

    def test_top_k_cap_and_zero_column(self, batch_env):
        """top_k 收窄 + 截断如实计数；全零指标列 rel_spread=None 不臆测。"""
        _write_json(batch_env / "runs" / "run_c" / "meta.json", {
            "run_id": "run_c", "model": "mline", "adapter": "fake",
            "status": "done",
            "metrics": {"s11_db_max_in_band": -11.0, "zero_metric": 0.0}})
        # run_a 补同键全零列（偏差排行需 ≥2 run 有该键）
        meta_a = json.loads(
            (batch_env / "runs" / "run_a" / "meta.json").read_text(
                encoding="utf-8"))
        meta_a["metrics"]["zero_metric"] = 0.0
        _write_json(batch_env / "runs" / "run_a" / "meta.json", meta_a)
        r = compare_runs_batch(["run_a", "run_b", "run_c"], top_k=1)
        assert r["ok"], r.get("errors")
        assert len(r["deviations"]) == 1
        assert r["deviations_truncated"] is True and r["top_k"] == 1
        all_r = compare_runs_batch(["run_a", "run_c"])
        zero = {d["metric"]: d for d in all_r["deviations"]}["zero_metric"]
        assert zero["spread"] == 0.0 and zero["rel_spread"] is None

    def test_missing_run_tolerance(self, batch_env):
        """缺产物容错：不存在 run → missing 行 + errors 记账，ok 保持
        True 不传染（对账面）；非法形态与不存在分开记账。"""
        r = compare_runs_batch(["run_a", "ghost_run"])
        assert r["ok"] is True
        rows = {row["run_id"]: row for row in r["runs"]}
        assert rows["ghost_run"]["status"] == "missing"
        assert any("run 不存在: ghost_run" in e for e in r["errors"])
        r2 = compare_runs_batch(["../escape"])
        assert r2["ok"] is True
        assert any("非法 run_id" in e for e in r2["errors"])

    def test_input_validation(self, batch_env):
        """空清单/重复/非整数 top_k/top_k<1 → error 信封（构造器同形）。"""
        assert compare_runs_batch([])["ok"] is False
        assert compare_runs_batch(["run_a", "run_a"])["ok"] is False
        e = compare_runs_batch(["run_a", "run_b"], top_k="x")
        assert e["ok"] is False and "top_k" in e["errors"][0]
        e2 = compare_runs_batch(["run_a", "run_b"], top_k=0)
        assert e2["ok"] is False


class TestCompareRunsBatchCli:
    def test_json_dual_path_smoke(self, batch_env):
        """CLI --json 双路径冒烟：成功信封（runs/deviations 齐备）与失败
        信封同构；缺参走 typer usage（exit 2）。"""
        runner = CliRunner()
        ok = runner.invoke(
            root_app, ["runs", "compare-batch", "run_a", "run_b", "--json"])
        assert ok.exit_code == 0, ok.output
        payload = json.loads(ok.output)
        assert payload["ok"] is True and payload["n_runs"] == 2
        assert payload["deviations"][0]["metric"] == "cost"
        # 含不存在 run：ok=True 但 errors 非空 → 人类分支退出码 1
        partial = runner.invoke(
            root_app, ["runs", "compare-batch", "run_a", "ghost", "--json"])
        payload_p = json.loads(partial.output)
        assert payload_p["ok"] is True and payload_p["errors"]
        empty = runner.invoke(root_app, ["runs", "compare-batch", "--json"])
        assert empty.exit_code == 2


class TestCompareRunsBatchMd:
    """compare_runs_batch_md Markdown 渲染面（W12-S4，verdict_summary_md
    同管道范式：提取层单源+确定性渲染层）。"""

    def test_md_deterministic_and_content(self, batch_env):
        """同输入两跑逐字节一致（零时间戳零 LLM）；表头/行/偏差节/截断
        引注 needle 齐备。"""
        md1 = compare_runs_batch_md(["run_a", "run_b", "camp/run_v"])
        md2 = compare_runs_batch_md(["run_a", "run_b", "camp/run_v"])
        assert md1 == md2  # 幂等：同输入逐字节同输出
        assert md1.startswith("# run 批量对账 — 3 个")
        assert "| run_id | 判定 | model | 耗时 s | cost | 指标数 | verdict |" in md1
        # 对账行：verdict 判定 FAIL 优先于缺失 meta；耗时/cost 显示格式
        assert "`run_a` | done | mline | 12.5 | 0.5000 | 3 | - |" in md1
        assert "`camp/run_v` | FAIL | mline | - | - | 0 | yes |" in md1
        # 偏差节：相对极差降序（cost 0.6 居首）+ 格式
        assert "## 跨 run 指标偏差 top（相对极差降序）" in md1
        assert "| `cost` | 0.3 | 0.6000 |" in md1
        # 两 run 有数值指标 → 无"指标不足"注记
        assert "仅 2 个 run 有数值指标" not in md1

    def test_md_single_run_note(self, batch_env):
        """单 run 有指标 → 偏差表空+注记行如实（<2 不参与排行）。"""
        md = compare_runs_batch_md(["run_a"])
        assert "注记: 仅 1 个 run 有数值指标" in md
        assert "## 跨 run 指标偏差 top" not in md

    def test_md_truncation_and_error_path(self, batch_env):
        """截断引注如实计数；空清单渲染层不抛（说明行起头）；缺失 run
        错误行入 Markdown。"""
        md = compare_runs_batch_md(["run_a", "run_b"], top_k=1)
        assert "偏差表截断" in md and "只列前 1 项" in md
        bad = compare_runs_batch_md([])
        assert bad.startswith("批量对账不可用")
        ghost = compare_runs_batch_md(["run_a", "ghost"])
        assert "- 错误: run 不存在: ghost" in ghost
        assert "`ghost` | missing" in ghost

    def test_cli_format_md_and_json_markdown_key(self, batch_env):
        """CLI --format md 人类分支（表头 needle+缺失 run 退出码 1）；
        --format md --json 信封带 markdown 键（verdict --format md --json
        同范式）；非法 --format 走 usage 错误（exit 2）。"""
        runner = CliRunner()
        ok = runner.invoke(root_app, [
            "runs", "compare-batch", "run_a", "run_b", "--format", "md"])
        assert ok.exit_code == 0, ok.output
        assert "# run 批量对账 — 2 个" in ok.output
        assert "| `cost` | 0.3 | 0.6000 |" in ok.output
        # 含缺失 run：md 人类分支打印后 errors → 退出码 1
        partial = runner.invoke(root_app, [
            "runs", "compare-batch", "run_a", "ghost", "--format", "md"])
        assert partial.exit_code == 1
        assert "run 不存在: ghost" in partial.output
        # md+json：信封带 markdown 键，结构化对账并存
        both = runner.invoke(root_app, [
            "runs", "compare-batch", "run_a", "run_b",
            "--format", "md", "--json"])
        assert both.exit_code == 0, both.output
        payload = json.loads(both.output)
        assert payload["ok"] is True
        assert payload["markdown"].startswith("# run 批量对账 — 2 个")
        assert payload["deviations"][0]["metric"] == "cost"
        # 非法 --format：usage 错误路径
        invalid = runner.invoke(root_app, [
            "runs", "compare-batch", "run_a", "run_b", "--format", "csv"])
        assert invalid.exit_code == 2
        # 缺省 table 形态不回归：不带 --format 时富表路径仍走（无 markdown 键）
        table = runner.invoke(root_app, [
            "runs", "compare-batch", "run_a", "run_b", "--json"])
        payload_t = json.loads(table.output)
        assert payload_t["ok"] is True and "markdown" not in payload_t
