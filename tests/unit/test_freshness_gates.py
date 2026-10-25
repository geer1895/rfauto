"""aurora_l A3 freshness gate 消费口接线测试（R2 侦察 Top1/Top2/Top3）。

K4 落的 freshness gate（``runs_verify_service.verify_run``）此前只装在
``report_render.render_run_report``（新报告面）；本批接到三个未设防
消费口并逐一钉三态语义（fresh 放行 / stale 拒绝或标红 / legacy 带
note）+ verify 面故障不阻塞（#105）：

1. ``generate_report_for_run``（老 ``rfauto report`` 命令——用户病灶
   第二入口）：stale → 错误信封拒出图（stage="freshness_gate"）；
   legacy/fresh → 放行带 freshness 状态。
2. ``summarize_sweep``（em sweep 汇总）：逐 case ``freshness`` 列——
   stale 标红不整批拒绝（DOE 最大化产出；``n_stale_rows`` 计数 +
   summary notes），legacy 带 note，未执行行 None 不冒充状态。
3. ``compare_runs_nway`` / ``compare_runs_batch``：逐 run freshness
   列——stale 标红不硬拒（notes 点名脏侧，对比结论可读出"哪边是脏
   数据"），md 渲染面经注记行自动透出。

合成 run 手法照 test_runs_verify_service.py（sidecar+manifest stamp）；
全离线零网络（#139）、chdir 隔离零 runs/ 湖写入（#144）。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service.runs_verify_service import (
    MANIFEST_FILENAME,
    write_manifest,
    write_touchstone_sidecar,
)

# 旧工程顶替内容（与 stamp 时的字节不同 → stale_replaced）
_REPLACED_S1P = "# GHz S RI R 50\n1.0 0.9 0.0\n"


def _stamp(run: Path) -> None:
    """收官指纹：sidecar + manifest（run_once 收尾链路同序）。"""
    snp = sorted(run.rglob("*.s*p"))
    assert snp, "合成 run 应含 Touchstone"
    write_touchstone_sidecar(snp[0], run_id=run.name)
    write_manifest(run)


def _boom_verify(monkeypatch) -> None:
    """verify 面故障注入（#105 钉：观测面故障不阻塞消费主路径）。"""

    def _boom(run_dir):
        raise RuntimeError("verify 通道故障")

    monkeypatch.setattr(
        "rfauto.service.runs_verify_service.verify_run", _boom)


# ── 件1：generate_report_for_run（老 rfauto report 命令） ────────────────────


def _recipe(tmp_path: Path) -> str:
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


@pytest.fixture()
def report_env(tmp_path, monkeypatch):
    """chdir 隔离 + fake 通道真跑一个 run（收官链自带 manifest→fresh）。"""
    monkeypatch.chdir(tmp_path)
    from rfauto.service.api import run_once

    result = run_once(_recipe(tmp_path), adapter_name="fake")
    assert result["ok"], result.get("errors")
    run_dir = Path(result["run_dir"])
    assert (run_dir / MANIFEST_FILENAME).is_file()
    return run_dir


class TestReportForRunGate:
    def test_fresh_run_passes_with_status(self, report_env):
        from rfauto.service.api import generate_report_for_run

        result = generate_report_for_run(report_env.name)
        assert result["ok"], result.get("errors")
        assert result["freshness"]["status"] == "fresh"
        assert Path(result["report"]).is_file()

    def test_stale_run_rejected_with_stage(self, report_env):
        """用户病灶形态：旧 sNp 顶替后老 report 命令必须拒绝出图。"""
        from rfauto.service.api import generate_report_for_run

        snp = sorted((report_env / "results").glob("params.s*p"))[0]
        snp.write_text(_REPLACED_S1P, encoding="utf-8")
        # run 链收官时自带的旧报告先清走（区分"gate 拒绝未再生成"）
        (report_env / "report.md").unlink(missing_ok=True)
        result = generate_report_for_run(report_env.name)
        assert result["ok"] is False
        assert result["stage"] == "freshness_gate"
        assert result["status"] == "stale"
        assert any("stale_replaced" in str(issue.get("kind"))
                   for issue in result["issues"])
        # 拒出图：报告产物不落盘
        assert not (report_env / "report.md").exists()

    def test_legacy_run_passes_with_note(self, tmp_path, monkeypatch):
        """增量兼容红线：无 manifest 老 run 的老命令行为不变，仅带 note。"""
        monkeypatch.chdir(tmp_path)
        run = tmp_path / "runs" / "legacy_run"
        (run / "results").mkdir(parents=True)
        (run / "results" / "metrics.json").write_text(
            json.dumps({"metrics": {"cost": 0.5}}), encoding="utf-8")
        (run / "results" / "params.s1p").write_text(
            "# GHz S RI R 50\n1.0 0.1 0.0\n", encoding="utf-8")
        from rfauto.service.api import generate_report_for_run

        result = generate_report_for_run("legacy_run")
        assert result["ok"], result.get("errors")
        assert result["freshness"]["status"] == "legacy"
        assert "legacy" in result["freshness"]["note"]

    def test_verify_face_failure_non_blocking(self, report_env, monkeypatch):
        from rfauto.service.api import generate_report_for_run

        _boom_verify(monkeypatch)
        result = generate_report_for_run(report_env.name)
        assert result["ok"], result.get("errors")
        assert "不可用" in result["freshness"]["note"]

    def test_cli_report_stale_exit_one(self, report_env):
        """CLI 老命令透传信封：stale → 人类分支红字 errors + 退出码 1。"""
        snp = sorted((report_env / "results").glob("params.s*p"))[0]
        snp.write_text(_REPLACED_S1P, encoding="utf-8")
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        result = CliRunner().invoke(app, ["report", report_env.name])
        assert result.exit_code == 1
        assert "stale_replaced" in result.output


# ── 件2：summarize_sweep（em sweep 汇总面） ──────────────────────────────────

_BASE_RECIPE = {
    "model": "oct_ind",
    "params": {"W_um": 15, "S_um": 15, "turns": 4},
    "objectives": [{"metric": "L_nh", "op": "target", "value": 4.2,
                    "band": [2.0, 3.0]}],
}


def _make_sweep_touchstone(run_dir: Path) -> None:
    """合成 2 端口 Touchstone（skrf 可读；提取面非本测钉）。"""
    import numpy as np
    import skrf

    freq = skrf.Frequency.from_f([1e9, 2e9, 3e9], unit="hz")
    s = np.zeros((3, 2, 2), dtype=complex)
    s[:, 0, 0] = s[:, 1, 1] = 0.1
    out = run_dir / "results" / "params.s2p"
    out.parent.mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50).write_touchstone(str(out))


def _stamped_executor_factory(*, stamp: bool):
    """mock 执行核：造 run 目录（meta+metrics+Touchstone），可选收官 stamp。"""

    def _execute(recipe_path: Path, adapter_name: str) -> dict:
        case_id = Path(recipe_path).parent.name
        run_dir = Path(recipe_path).parent / "run"
        (run_dir / "results").mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(json.dumps({
            "run_id": case_id, "status": "done", "adapter": adapter_name}),
            encoding="utf-8")
        (run_dir / "results" / "metrics.json").write_text(json.dumps({
            "metrics": {"L_nh": 4.2}, "cost": 0.1}), encoding="utf-8")
        _make_sweep_touchstone(run_dir)
        if stamp:
            _stamp(run_dir)
        return {"ok": True, "run_id": case_id, "run_dir": str(run_dir)}

    return _execute


@pytest.fixture()
def sweep_env(tmp_path, monkeypatch):
    """chdir 隔离 + 2 case 小矩阵 sweep 计划。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "base.yaml").write_text(
        yaml.safe_dump(_BASE_RECIPE), encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(
        "base_recipe: base.yaml\nadapter: fake\n"
        "matrix:\n  device: [a, b]\n", encoding="utf-8")
    from rfauto.service import em_sweep_service as sweep

    plan = sweep.plan_sweep(tmp_path / "cases.yaml")
    assert plan["ok"], plan.get("errors")
    return sweep, plan


def _case_run_dir(plan: dict, case_id: str) -> Path:
    case = next(c for c in plan["cases"] if c["case_id"] == case_id)
    return Path(case["case_dir"]) / "run"


class TestSummarizeFreshness:
    def test_stale_row_marked_not_rejected(self, sweep_env):
        """stale 行标红列并入 summary（不整批拒绝，DOE 最大化产出）。"""
        sweep, plan = sweep_env
        result = sweep.run_sweep(
            plan, execute_fn=_stamped_executor_factory(stamp=True))
        assert result["ok"]
        # 用户病灶：一个 case 的 Touchstone 被旧内容顶替
        snp = sorted((_case_run_dir(plan, "b") / "results").glob("*.s*p"))[0]
        snp.write_text(_REPLACED_S1P, encoding="utf-8")
        summary = sweep.summarize_sweep(plan)
        assert summary["ok"], summary.get("errors")  # 不整批拒绝
        rows = {r["case_id"]: r for r in summary["rows"]}
        assert rows["a"]["freshness"] == "fresh"
        assert rows["b"]["freshness"] == "stale"
        assert "stale_replaced" in rows["b"]["freshness_note"]
        assert summary["n_stale_rows"] == 1
        assert "stale 1/2" in summary["note"]
        # csv/json 落盘显式标红列（run_dir 恒收尾——既有列序钉不破）
        with open(summary["summary_csv"], encoding="utf-8", newline="") as f:
            table = list(csv.reader(f))
        header = table[0]
        assert "freshness" in header and "freshness_note" in header
        assert header[-1] == "run_dir"
        b_row = next(r for r in table[1:]
                     if r[header.index("case_id")] == "b")
        assert b_row[header.index("freshness")] == "stale"
        payload = json.loads(
            Path(summary["summary_json"]).read_text(encoding="utf-8"))
        assert payload["n_stale_rows"] == 1
        assert any("stale 1" in n and "freshness" in n
                   for n in payload["notes"])

    def test_legacy_rows_pass_with_note(self, sweep_env):
        """无 manifest 老 case → legacy 放行带 note（DOE 老 run 不废）。"""
        sweep, plan = sweep_env
        result = sweep.run_sweep(
            plan, execute_fn=_stamped_executor_factory(stamp=False))
        assert result["ok"]
        summary = sweep.summarize_sweep(plan)
        assert summary["ok"], summary.get("errors")
        assert all(r["freshness"] == "legacy" for r in summary["rows"])
        assert all("legacy" in r["freshness_note"] for r in summary["rows"])
        assert summary["n_stale_rows"] == 0

    def test_verify_face_failure_marks_unknown(self, sweep_env, monkeypatch):
        """verify 面故障不阻塞汇总（#105）：该行 unknown，整批照常落盘。"""
        sweep, plan = sweep_env
        result = sweep.run_sweep(
            plan, execute_fn=_stamped_executor_factory(stamp=True))
        assert result["ok"]
        _boom_verify(monkeypatch)
        summary = sweep.summarize_sweep(plan)
        assert summary["ok"], summary.get("errors")
        assert all(r["freshness"] == "unknown" for r in summary["rows"])
        assert all("不可用" in r["freshness_note"] for r in summary["rows"])
        assert summary["n_stale_rows"] == 0

    def test_unexecuted_rows_freshness_none(self, sweep_env):
        """未执行 case（无 run 目录）→ freshness=None 不冒充状态。"""
        sweep, plan = sweep_env
        summary = sweep.summarize_sweep(plan)
        assert summary["ok"]
        assert all(r["freshness"] is None for r in summary["rows"])
        assert summary["n_stale_rows"] == 0


# ── 件3：compare_runs_nway / compare_runs_batch（对比面对账面） ──────────────


def _fab_verified_run(root: Path, rid: str, *, cost: float, s11: float,
                      stamp: bool = True) -> Path:
    """fabricated run：meta + results/metrics.json + Touchstone（可选 stamp）。"""
    run = root / rid
    (run / "results").mkdir(parents=True, exist_ok=True)
    (run / "meta.json").write_text(json.dumps({
        "run_id": rid, "model": "mline", "adapter": "fake",
        "status": "done"}), encoding="utf-8")
    (run / "results" / "metrics.json").write_text(json.dumps({
        "run_id": rid, "metrics": {"s11_db": s11}, "cost": cost}),
        encoding="utf-8")
    (run / "results" / "params.s1p").write_text(
        "# GHz S RI R 50\n1.0 0.1 0.0\n", encoding="utf-8")
    if stamp:
        _stamp(run)
    return run


@pytest.fixture()
def compare_env(tmp_path, monkeypatch):
    """chdir 隔离 + 三态语料：fresh / legacy / stale（旧内容顶替）。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    _fab_verified_run(root, "r_fresh", cost=0.1, s11=-10.0, stamp=True)
    _fab_verified_run(root, "r_legacy", cost=0.2, s11=-20.0, stamp=False)
    stale = _fab_verified_run(root, "r_stale", cost=0.3, s11=-30.0, stamp=True)
    (stale / "results" / "params.s1p").write_text(
        _REPLACED_S1P, encoding="utf-8")
    return tmp_path


class TestCompareFreshnessColumns:
    def test_nway_rows_and_stale_note(self, compare_env):
        from rfauto.service.batch_ops_service import compare_runs_nway

        r = compare_runs_nway(["r_fresh", "r_legacy", "r_stale"])
        assert r["ok"], r.get("errors")
        rows = {row["run_id"]: row for row in r["runs"]}
        assert rows["r_fresh"]["freshness"] == "fresh"
        assert rows["r_legacy"]["freshness"] == "legacy"
        assert "legacy" in rows["r_legacy"]["freshness_note"]
        assert rows["r_stale"]["freshness"] == "stale"
        assert "stale_replaced" in rows["r_stale"]["freshness_note"]
        # stale 标红不硬拒：ok 保持 True，notes 点名脏侧
        assert any("r_stale" in n and "stale" in n for n in r["notes"])

    def test_batch_rows_missing_none_and_md_note(self, compare_env):
        from rfauto.service.batch_ops_service import (
            compare_runs_batch,
            compare_runs_batch_md,
        )

        r = compare_runs_batch(["r_fresh", "r_stale", "ghost"])
        assert r["ok"] is True
        rows = {row["run_id"]: row for row in r["runs"]}
        assert rows["r_fresh"]["freshness"] == "fresh"
        assert rows["r_stale"]["freshness"] == "stale"
        # missing 行不冒充状态（freshness=None，status 仍 missing）
        assert rows["ghost"]["status"] == "missing"
        assert rows["ghost"]["freshness"] is None
        assert any("r_stale" in n for n in r["notes"])
        # md 渲染面：表头/行结构不变（既有钉不破），脏侧经注记行透出
        md = compare_runs_batch_md(["r_fresh", "r_stale"])
        assert ("| run_id | 判定 | model | 耗时 s | cost | 指标数 | verdict |"
                in md)
        assert "freshness: r_stale" in md

    def test_batch_verify_failure_marks_unknown(self, compare_env,
                                                monkeypatch):
        from rfauto.service.batch_ops_service import compare_runs_batch

        _boom_verify(monkeypatch)
        r = compare_runs_batch(["r_fresh", "r_legacy"])
        assert r["ok"] is True
        rows = {row["run_id"]: row for row in r["runs"]}
        assert rows["r_fresh"]["freshness"] == "unknown"
        assert "不可用" in rows["r_fresh"]["freshness_note"]
        assert rows["r_legacy"]["freshness"] == "unknown"
        assert r["notes"] == []  # 无 stale 不点名（unknown 不冒充脏）

    def test_batch_report_stale_lands_in_failed(self, compare_env,
                                                tmp_path):
        """批量 report 面（R2 Top3 消费口）：stale run 经件1门落 failed，
        errors 带 verify 点名；legacy run 照常出报告。"""
        from rfauto.service.batch_ops_service import report_runs_batch

        r = report_runs_batch(["r_legacy", "r_stale"],
                              out_dir=str(tmp_path / "batch_out"))
        assert r["ok"] is True
        assert r["n_ok"] == 1 and r["n_failed"] == 1
        assert r["failed"][0]["run_id"] == "r_stale"
        assert any("stale_replaced" in e for e in r["failed"][0]["errors"])
        assert r["reports"] and Path(r["reports"][0]).exists()
