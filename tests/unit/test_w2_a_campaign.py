"""VI-2：campaign run 战役执行器测试（Phase2 W2-A，全合成零真机零网络）。

规格判据（sp_specs6 §VI-2 / criteria W2-A 预声明）：
①断点续跑演练：六阶段 plan（fake 通道全离线）中段 kill solve executor
  （tune 节点执行器内 os._exit 硬死，#157 形态）→ 重调同参 → done 节点
  executor 调用计数=1（ledger+journal 复核零重执行）→ 终态全 done+报告
  产物在盘；
②互斥生效：同 run_dir 并发第二实例被拒（ok=False+errors 含 lock 字样，
  CLI rc≠0）；
③dry-run 零执行断言（探针钉 run_dag/subprocess 均不被触达）；
④entry 纸面命令串禁 shell 出（结构 AST 钉+未知 kind 拒绝行为钉）；
⑤权威账本 dag.state.json→stage 视图映射+UI 队列 running 行+注册可达
  （CLI 叶/MCP 工具，计数链自证）。

#277 三态开关陷阱不适用：campaign run 无"缺省读配置"语义旗标
（--dry-run/--detach/--resume 均 bool=False 纯开关，无配置缺省值可遮蔽）。
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml
from typer.testing import CliRunner

from rfauto.cli.domains.bands_uq import campaign_app
from rfauto.pipeline.dag_runner import (
    DAG_RUN_LOCK_NAME,
    DAG_STATE_FILE,
    acquire_lock,
    release_lock,
)
from rfauto.service.campaign_executor import (
    CAMPAIGN_EXECUTORS,
    CAMPAIGN_KINDS,
    STAGE_RESULT_FILE,
    campaign_kind_of,
    run_campaign,
)
from rfauto.service.campaign_manager import plan_campaign, save_plan
from rfauto.service.envelope import ok_envelope

runner = CliRunner()
_REPO = Path(__file__).resolve().parents[2]

_STAGE_CHAIN = (
    ("calibrate", [], 9), ("prefilter", ["calibrate"], 30),
    ("tune", ["prefilter"], 30), ("tolerance", ["tune"], 1000),
    ("report", ["tolerance"], None), ("final_verify", ["tolerance"], 5),
)


def _make_plan_dir(tmp_path: Path, name: str = "camp1") -> Path:
    """最小六阶段战役计划落盘（fake 通道全离线；recipe 为占位 YAML）。"""
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        "model: mline\nobjectives:\n  - metric: s11_db\n"
        "    op: max_below\n    value: -10.0\nlimits:\n  max_trials: 30\n",
        encoding="utf-8")
    stages = [
        {"stage": s, "kind": ("tune" if s == "final_verify" else s),
         "adapter": "fake", "depends_on": deps, "status": "pending",
         "budget": b, "license_gated": False,
         "entry": f"rfauto {'tune' if s == 'final_verify' else s} "
                  f"{recipe.name}",
         "note": ""}
        for s, deps, b in _STAGE_CHAIN
    ]
    stages[-1]["shadow_points"] = {"n_points": 3, "top_k": 1,
                                   "min_norm_dist": 0.3,
                                   "status": "pending", "capped": False}
    plan = ok_envelope(recipe=str(recipe), model="mline", stages=stages,
                       campaign_schema="rfauto-campaign-plan-v1.1")
    camp_dir = tmp_path / "runs" / name
    camp_dir.mkdir(parents=True, exist_ok=True)
    save_plan(plan, camp_dir)
    return camp_dir


def _append_ledger(ledger: Path, name: str) -> None:
    try:
        lst = json.loads(ledger.read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError):
        lst = []
    lst.append(name)
    ledger.write_text(json.dumps(lst), encoding="utf-8")


def _counting_executors(ledger: Path):
    """计数执行器六件：ledger 追加+stage_result 落盘+report 写战役报告。"""

    def _make(kind: str):
        def _exec(node, ctx):
            _append_ledger(ledger, str(node.get("node_id")))
            work = Path(ctx.get("work_dir") or ".")
            work.mkdir(parents=True, exist_ok=True)
            (work / STAGE_RESULT_FILE).write_text(
                json.dumps({"ok": True, "stage": node.get("node_id"),
                            "campaign_kind": kind}, ensure_ascii=False),
                encoding="utf-8")
            if kind == "report":
                extra = node.get("stage_extra") or {}
                camp_dir = Path(str(extra.get("campaign_dir") or "."))
                report = "# campaign report\n\nall stages synthesized.\n"
                (work / "campaign_report.md").write_text(report,
                                                         encoding="utf-8")
                camp_dir.mkdir(parents=True, exist_ok=True)
                (camp_dir / "campaign_report.md").write_text(
                    report, encoding="utf-8")
            return {"ok": True, "outputs": [STAGE_RESULT_FILE],
                    "wall_s": 0.0, "message": f"{kind} synthesized ok"}
        return _exec

    return {kind: _make(kind) for kind in CAMPAIGN_KINDS}


_KILL_CHILD_TEMPLATE = """\
import json, os, sys
from pathlib import Path
sys.path.insert(0, {src!r})
from rfauto.service.campaign_executor import run_campaign, STAGE_RESULT_FILE

plan_path, run_dir, ledger, solve_lock, kill_at = sys.argv[1:6]

def _append(ledger, name):
    try:
        lst = json.loads(Path(ledger).read_text(encoding="utf-8") or "[]")
    except Exception:
        lst = []
    lst.append(name)
    Path(ledger).write_text(json.dumps(lst), encoding="utf-8")

def _make(kind):
    def _exec(node, ctx):
        _append(ledger, str(node.get("node_id")))
        work = Path(ctx.get("work_dir") or ".")
        work.mkdir(parents=True, exist_ok=True)
        (work / STAGE_RESULT_FILE).write_text(
            json.dumps({{"ok": True, "stage": node.get("node_id")}}),
            encoding="utf-8")
        if str(node.get("node_id")) == kill_at:
            sys.stdout.flush()
            os._exit(87)   # #157 树死模拟：进程内硬死（无清理无期刊终写）
        return {{"ok": True, "outputs": [STAGE_RESULT_FILE], "wall_s": 0.0,
                "message": kind + " ok"}}
    return _exec

table = {{k: _make(k) for k in {kinds!r}}}
result = run_campaign(plan_path, run_dir=run_dir, executors=table,
                      solve_lock_path=solve_lock, cache_dir={cache!r})
print("UNREACHABLE", json.dumps(result, ensure_ascii=False, default=str))
"""


# ─── 判据①：断点续跑演练（中段 kill solve executor → 重调同参零重执行）─────────

def test_kill_solve_then_resume_zero_reexecution(tmp_path) -> None:
    camp_dir = _make_plan_dir(tmp_path)
    ledger = tmp_path / "executor_calls.json"
    solve_lock = tmp_path / "solve.lock"
    cache_dir = tmp_path / "cache"
    child = tmp_path / "campaign_child.py"
    child.write_text(
        _KILL_CHILD_TEMPLATE.format(src=str(_REPO / "src"),
                                    kinds=list(CAMPAIGN_KINDS),
                                    cache=str(cache_dir)),
        encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    env.pop("RFAUTO_CACHE", None)

    # 第一跑：tune（solve 类节点）执行器中段硬死整进程
    proc = subprocess.run(
        [sys.executable, str(child), str(camp_dir), str(camp_dir),
         str(ledger), str(solve_lock), "tune"],
        capture_output=True, text=True, timeout=300, env=env)
    assert proc.returncode == 87, (
        f"子进程未按预期硬死 rc={proc.returncode} "
        f"stdout={proc.stdout[-300:]} stderr={proc.stderr[-300:]}")

    # 死树现场：calibrate/prefilter 已 done、tune 停 running、运行锁残留
    state = json.loads((camp_dir / DAG_STATE_FILE).read_text(
        encoding="utf-8"))
    assert state["nodes"]["calibrate"]["status"] == "done"
    assert state["nodes"]["prefilter"]["status"] == "done"
    assert state["nodes"]["tune"]["status"] == "running"
    assert (camp_dir / DAG_RUN_LOCK_NAME).is_file()
    calls_after_kill = Counter(json.loads(
        ledger.read_text(encoding="utf-8")))
    assert calls_after_kill == {"calibrate": 1, "prefilter": 1, "tune": 1}

    # 重调同参（resume：断点续跑由期刊 _resume_decision 承担；陈锁按 pid
    # 死亡自动接管）
    result = run_campaign(str(camp_dir), executors=_counting_executors(ledger),
                          solve_lock_path=str(solve_lock),
                          cache_dir=str(cache_dir), resume=True)
    assert result["ok"] is True, result.get("errors")
    assert result["verdict"] == "COMPLETE"
    assert result["n_hit"] == 2, f"done 节点未零重算跳过: {result}"
    assert result["n_recompute"] == 4
    assert set(result["statuses"].values()) == {"done"}

    # executor 调用计数：done 节点=1（零重执行）；被 kill 的 tune=2
    calls = Counter(json.loads(ledger.read_text(encoding="utf-8")))
    assert calls["calibrate"] == 1 and calls["prefilter"] == 1
    assert calls["tune"] == 2
    assert calls["tolerance"] == 1 and calls["report"] == 1
    assert calls["final_verify"] == 1

    # 终态全 done + 报告产物在盘 + 计划视图回写
    assert (camp_dir / "campaign_report.md").is_file()
    assert not (camp_dir / DAG_RUN_LOCK_NAME).exists()
    plan_now = json.loads(
        (camp_dir / "campaign.plan.json").read_text(encoding="utf-8"))
    assert plan_now["verdict"] == "COMPLETE"
    assert all(s["status"] == "done" for s in plan_now["stages"])


# ─── 判据②：互斥生效（同 run_dir 并发第二实例被拒）───────────────────────────

def test_second_instance_rejected_by_run_lock(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    camp_dir = _make_plan_dir(tmp_path, "camp2")
    ledger = tmp_path / "calls2.json"
    holder = acquire_lock("holder", camp_dir / DAG_RUN_LOCK_NAME,
                          max_wait_s=0.0)
    try:
        res = run_campaign(str(camp_dir),
                           executors=_counting_executors(ledger),
                           solve_lock_path=str(tmp_path / "solve2.lock"),
                           cache_dir=str(tmp_path / "cache2"))
        assert res["ok"] is False
        assert any("lock" in str(e) for e in res["errors"]), res
        # CLI 面：rc≠0 + --json 信封 errors 含 lock 字样
        got = runner.invoke(campaign_app, ["run", str(camp_dir), "--json"])
        assert got.exit_code != 0
        envelope = json.loads(got.output)
        assert envelope["ok"] is False
        assert any("lock" in str(e) for e in envelope["errors"])
    finally:
        release_lock(holder, camp_dir / DAG_RUN_LOCK_NAME)


# ─── 判据③：dry-run 零执行（探针钉：run_dag/subprocess 不被触达）──────────────

def test_dry_run_zero_execution(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    camp_dir = _make_plan_dir(tmp_path, "camp3")

    import rfauto.pipeline.dag_runner as dr

    def _boom_run_dag(*a, **k):
        raise AssertionError("dry-run 触达了 run_dag（零执行违约）")

    def _boom_subprocess(*a, **k):
        raise AssertionError("dry-run 触达了子进程（零执行违约）")

    monkeypatch.setattr(dr, "run_dag", _boom_run_dag)
    monkeypatch.setattr(subprocess, "run", _boom_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _boom_subprocess)

    res = run_campaign(str(camp_dir), dry_run=True)
    assert res["ok"] is True and res["dry_run"] is True
    assert res["order"][0] == "calibrate"
    assert len(res["order"]) == 6
    by_stage = {s["stage"]: s for s in res["stages"]}
    assert by_stage["calibrate"]["budget"] == 9
    assert by_stage["tolerance"]["budget"] == 1000
    assert by_stage["tune"]["depends_on"] == ["prefilter"]
    assert res["mutex_preview"]["run_instance_lock"].endswith(DAG_RUN_LOCK_NAME)
    assert "solve_machine_lock" in res["mutex_preview"]
    # 零执行：期刊/运行锁/视图均未落
    assert not (camp_dir / DAG_STATE_FILE).exists()
    assert not (camp_dir / DAG_RUN_LOCK_NAME).exists()

    # CLI dry-run 面同样零执行且 rc=0
    got = runner.invoke(campaign_app,
                        ["run", str(camp_dir), "--dry-run", "--json"])
    assert got.exit_code == 0, got.output
    envelope = json.loads(got.output)
    assert envelope["dry_run"] is True and envelope["ok"] is True


# ─── 判据④：entry 纸面命令串禁 shell 出（结构钉+行为钉）──────────────────────

def test_no_shell_out_of_entry() -> None:
    import rfauto.service.campaign_executor as ce

    src = Path(ce.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "subprocess", (
                    "执行器面禁 subprocess（entry 纸面串禁 shell 出）")
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "subprocess", (
                "执行器面禁 subprocess（entry 纸面串禁 shell 出）")
    # 行为钉：未知 kind 的节点被 dispatch 拒绝，绝不 shell 出 entry
    dispatch = ce._dag_executors(dict(CAMPAIGN_EXECUTORS))["solve"]
    node = {"node_id": "custom_stage", "kind": "solve",
            "cmd": "rfauto custom_kind recipe.yaml",
            "stage_extra": {"campaign_recipe": "x.yaml"}}
    raw = dispatch(node, {"work_dir": ".", "budget": {}, "upstream": {}})
    assert raw["ok"] is False
    assert "禁 shell" in raw["message"] or "shell" in raw["message"]


def test_campaign_kind_of_resolution() -> None:
    assert campaign_kind_of({"node_id": "calibrate", "cmd": ""}) == "calibrate"
    assert campaign_kind_of({"node_id": "final_verify",
                             "cmd": "rfauto tune r.yaml"}) == "final_verify"
    assert campaign_kind_of({"node_id": "my_stage",
                             "cmd": "rfauto tune r.yaml"}) == "tune"
    assert campaign_kind_of({"node_id": "my_stage",
                             "cmd": "rfauto mystery r.yaml"}) is None


# ─── 权威账本→stage 视图映射（防双账本；apply_event 语义零改动）───────────────

def test_stage_view_mapping() -> None:
    from rfauto.service.campaign_executor import _NODE_TO_STAGE_VIEW, _stage_view_from_nodes

    assert _NODE_TO_STAGE_VIEW["partial"] == "done"
    assert _NODE_TO_STAGE_VIEW["inconclusive"] == "pending"
    assert _NODE_TO_STAGE_VIEW["failed"] == "failed"
    assert _NODE_TO_STAGE_VIEW["aborted"] == "aborted"
    plan = {"stages": [{"stage": "calibrate", "status": "pending"},
                       {"stage": "tune", "status": "pending",
                        "note": "中保真精算"}]}
    view = _stage_view_from_nodes(plan, {
        "calibrate": {"status": "partial"},
        "tune": {"status": "inconclusive"}})
    assert view[0]["status"] == "done" and view[0]["node_status"] == "partial"
    assert view[1]["status"] == "pending" and view[1]["node_status"] == \
        "inconclusive"
    assert "超预算 PARTIAL 入库" in plan["stages"][0]["note"]
    assert "续跑重判定" in plan["stages"][1]["note"]
    # 视图直接回写 stage status（campaign.plan.json 的投影面）
    assert plan["stages"][0]["status"] == "done"


# ─── UI 队列 running 行（运行中战役在 /api/campaign_queue 显示 running）───────

def test_ui_campaign_queue_running_row(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    camp_dir = _make_plan_dir(tmp_path, "camp_ui")
    plan = json.loads(
        (camp_dir / "campaign.plan.json").read_text(encoding="utf-8"))
    plan["verdict"] = "RUNNING"
    plan["stages"][0]["status"] = "done"
    plan["stages"][1]["status"] = "running"
    save_plan(plan, camp_dir)

    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    client = TestClient(create_ui_app())
    r = client.get("/api/campaign_queue").json()
    assert r["ok"] is True and r["n_campaigns"] == 1
    row = r["campaigns"][0]
    assert row["verdict"] == "RUNNING"
    by_stage = {s["stage"]: s["status"] for s in row["stages"]}
    assert by_stage["calibrate"] == "done"
    assert by_stage["prefilter"] == "running"


# ─── 注册可达（计数链自证：CLI 叶+MCP 工具）──────────────────────────────────

def test_cli_and_mcp_registration_reachable() -> None:
    from typer.main import get_command

    from rfauto.cli.main import app as main_app

    click_app = get_command(main_app)
    campaign_leaves = set(
        getattr(click_app.commands["campaign"], "commands", {}) or {})
    assert "run" in campaign_leaves, f"campaign 叶缺 run: {campaign_leaves}"

    from rfauto.mcp_server import mcp as mcp_server

    tools = {t.name for t in asyncio.run(mcp_server.list_tools())}
    assert "run_campaign" in tools, "MCP 缺 run_campaign 工具"


# ─── CLI --json 双路径（成功信封+失败信封同构）────────────────────────────────

def test_cli_json_dual_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # 失败路径：计划不存在 → rc≠0 且仍是 JSON 信封
    got = runner.invoke(campaign_app,
                        ["run", str(tmp_path / "__no_plan__"), "--json"])
    assert got.exit_code != 0
    envelope = json.loads(got.output)
    assert envelope["ok"] is False and envelope["errors"]
    # detach：v1 如实 skipped（零副作用，ok=True+skipped 键）
    camp_dir = _make_plan_dir(tmp_path, "camp_det")
    got2 = runner.invoke(campaign_app,
                         ["run", str(camp_dir), "--detach", "--json"])
    assert got2.exit_code == 0, got2.output
    envelope2 = json.loads(got2.output)
    assert envelope2.get("skipped") is True
    assert not (camp_dir / DAG_STATE_FILE).exists()


# ─── ge9 审查批修复席 B 钉（P1-1/P1-2/P2-2/P2-1；runs/review_ge9/slice_R2）────

def _tolerance_stage(stages: list[dict]) -> dict:
    """stages → tolerance 阶段条目（RUF015：next 取代单元素切片）。"""
    return next(s for s in stages if s.get("stage") == "tolerance")


def _ge9b_fake_recipe(tmp_path: Path, name: str = "ge9b_recipe.yaml") -> Path:
    """wilkinson 最小配方（fake 采样器/优化器秒级；含搜索空间与标量目标）。"""
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"f0_ghz": {"value": 2.4},
                   "arm_len_mm": {"value": 20.5},
                   "series_w_mm": {"value": 0.33},
                   "shunt_w_mm": {"value": 1.1}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
            "shunt_w_mm": {"low": 0.90, "high": 1.30},
        }},
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def _isolate_optuna_storage(tmp_path: Path, monkeypatch) -> Path:
    """tmp_path 隔离 optuna.db（test_w1d_watch_detach 既有注入口径同款）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{(db_dir / 'optuna.db').as_posix()}"
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path", lambda: storage)
    return storage


def test_two_campaigns_same_model_study_not_shared(tmp_path, monkeypatch) -> None:
    """ge9 审查 P1-1：同模型两战役 study 名含战役实例指纹（不相等）且
    best 互不污染——真 optuna 链（tmp 隔离库）逐战役恰好只含本役 trial，
    tune stage_result 的 best_params 出自本役 study 的 trial 集。"""
    import optuna

    from rfauto.optimization.optimizer import get_storage_path
    from rfauto.service.campaign_executor import _campaign_study_name

    storage = _isolate_optuna_storage(tmp_path, monkeypatch)
    recipe = _ge9b_fake_recipe(tmp_path)
    names: list[str] = []
    for cname in ("camp_iso_a", "camp_iso_b"):
        plan = plan_campaign(str(recipe), mid_adapter="fake",
                             high_adapter="none", tune_budget=2,
                             tolerances={"arm_len_mm": 0.3})
        assert plan["ok"], plan.get("errors")
        camp = tmp_path / "runs" / cname
        save_plan(plan, camp)
        res = run_campaign(
            str(camp), solve_lock_path=str(tmp_path / "solve.lock"),
            cache_dir=str(tmp_path / "cache"))
        assert res["ok"] is True, res.get("errors")
        expected = _campaign_study_name(
            {"campaign_model": plan["model"], "campaign_dir": str(camp),
             "campaign_stage": "tune"}, {"node_id": "tune"})
        study = optuna.load_study(study_name=expected,
                                  storage=get_storage_path())
        # 只含本战役 trial（旧名共享库形态下两役共 4 trial 挤同一 study）
        assert len(study.trials) == 2
        sr = json.loads(
            (camp / "tune" / STAGE_RESULT_FILE).read_text(encoding="utf-8"))
        # 落盘 study 名与预期指纹一致（串台面在产物里可审计）
        assert sr["study_name"] == expected
        assert sr["best_params"] in list(t.params for t in study.trials), (
            f"best_params 不在本役 study trial 集（串台嫌疑）: {sr}")
        names.append(expected)
    assert names[0] != names[1], names
    # 全库恰两个 campaign-* study（无共享名残留）
    summaries = optuna.study.get_all_study_summaries(storage=storage)
    assert sorted(s.study_name for s in summaries) == sorted(names)


def test_real_executor_full_chain_complete_with_tolerances(
        tmp_path, monkeypatch) -> None:
    """ge9 审查 P1-2：tolerances 生产写面打通——真执行器链（缺省
    CAMPAIGN_EXECUTORS，fake 通道全离线）calibrate→prefilter→tune→
    tolerance→report 全 COMPLETE；tolerance 节点真产出良率
    （surrogate_yield_at 消费上游校准样本+tune 名义点）。"""
    _isolate_optuna_storage(tmp_path, monkeypatch)
    recipe = _ge9b_fake_recipe(tmp_path)
    plan = plan_campaign(str(recipe), mid_adapter="fake",
                         high_adapter="none", tune_budget=3,
                         tolerances={"arm_len_mm": 0.3, "series_w_mm": 0.02,
                                     "shunt_w_mm": 0.05})
    assert plan["ok"], plan.get("errors")
    tol_stage = _tolerance_stage(plan["stages"])
    assert tol_stage["tolerances"] == {"arm_len_mm": 0.3, "series_w_mm": 0.02,
                                       "shunt_w_mm": 0.05}
    camp = tmp_path / "runs" / "camp_full"
    save_plan(plan, camp)
    res = run_campaign(str(camp), solve_lock_path=str(tmp_path / "solve.lock"),
                       cache_dir=str(tmp_path / "cache"))
    assert res["ok"] is True, res.get("errors")
    assert res["verdict"] == "COMPLETE"
    assert res["n_dead"] == 0
    assert {s["status"] for s in res["stage_view"]} == {"done"}
    # tolerance 节点真产出（不是注入执行器的合成账）
    tol_sr = json.loads(
        (camp / "tolerance" / STAGE_RESULT_FILE).read_text(encoding="utf-8"))
    assert tol_sr["ok"] is True
    assert isinstance(tol_sr.get("yield_rate"), (int, float))
    assert tol_sr["tolerances"] == {"arm_len_mm": 0.3, "series_w_mm": 0.02,
                                    "shunt_w_mm": 0.05}


def test_plan_campaign_without_tolerances_keeps_honest_fail(
        tmp_path, monkeypatch) -> None:
    """缺省（不传 tolerances）不写字段——executor "v1 不猜"如实失败口径
    保留（修复只补生产写面，不硬造缺省剖面）。"""
    recipe = _ge9b_fake_recipe(tmp_path)
    plan = plan_campaign(str(recipe), mid_adapter="fake",
                         high_adapter="none")
    tol_stage = _tolerance_stage(plan["stages"])
    assert "tolerances" not in tol_stage


def test_cli_campaign_plan_tolerances_flag(tmp_path, monkeypatch) -> None:
    """CLI --tolerances（k=v 可多次，_kv_floats 单源解析）→ 计划字段；
    缺省不传不写字段。"""
    monkeypatch.chdir(tmp_path)
    recipe = _ge9b_fake_recipe(tmp_path)
    got = runner.invoke(campaign_app, [
        "plan", str(recipe), "--high-adapter", "none", "--mid-adapter",
        "fake", "--tolerances", "arm_len_mm=0.05", "--tolerances",
        "series_w_mm=0.02", "--json"])
    assert got.exit_code == 0, got.output
    env = json.loads(got.output)
    tol_stage = _tolerance_stage(env["stages"])
    assert tol_stage["tolerances"] == {"arm_len_mm": 0.05,
                                       "series_w_mm": 0.02}
    got2 = runner.invoke(campaign_app, [
        "plan", str(recipe), "--high-adapter", "none", "--mid-adapter",
        "fake", "--json"])
    assert got2.exit_code == 0, got2.output
    env2 = json.loads(got2.output)
    tol2 = _tolerance_stage(env2["stages"])
    assert "tolerances" not in tol2


def test_rejected_run_leaves_no_phantom_running(tmp_path, monkeypatch) -> None:
    """ge9 审查 P2-2：占锁拒绝路径不留幻影 running 行（verdict 回写还原，
    UI 队列不再消费到无活跑的 RUNNING）。"""
    monkeypatch.chdir(tmp_path)
    camp_dir = _make_plan_dir(tmp_path, "camp_phantom")
    ledger = tmp_path / "calls_phantom.json"
    holder = acquire_lock("holder", camp_dir / DAG_RUN_LOCK_NAME,
                          max_wait_s=0.0)
    try:
        res = run_campaign(str(camp_dir),
                           executors=_counting_executors(ledger),
                           solve_lock_path=str(tmp_path / "solve.lock"),
                           cache_dir=str(tmp_path / "cache"))
        assert res["ok"] is False
        assert any("lock" in str(e) for e in res["errors"])
        plan_after = json.loads(
            (camp_dir / "campaign.plan.json").read_text(encoding="utf-8"))
        assert plan_after.get("verdict") != "RUNNING"
    finally:
        release_lock(holder, camp_dir / DAG_RUN_LOCK_NAME)


def test_report_and_final_verify_stage_result_persistence(
        tmp_path, monkeypatch) -> None:
    """ge9 审查 P2-1：作者显式要落盘的键过白名单（report_html /
    shadow_selection / adapter_channel 不再被静默丢弃）。"""
    import rfauto.service.v3_services as v3_mod
    from rfauto.service.campaign_executor import (
        _exec_final_verify,
        _exec_report,
    )

    monkeypatch.setattr(v3_mod, "generate_enhanced_report",
                        lambda *a, **k: str(k.get("output", "")))
    tunedir = tmp_path / "tune_wd"
    tunedir.mkdir()
    (tunedir / STAGE_RESULT_FILE).write_text(json.dumps(
        {"ok": True, "run_id": "runX", "best_params": {"a": 0.5},
         "best_cost": 0.1}), encoding="utf-8")
    upstream = {"tune": {"artifact_run_dir": str(tunedir)}}

    wd_report = tmp_path / "wd_report"
    _exec_report({"node_id": "report",
                  "stage_extra": {"campaign_dir": str(tmp_path / "camp")}},
                 {"work_dir": str(wd_report), "upstream": upstream})
    sr_report = json.loads(
        (wd_report / STAGE_RESULT_FILE).read_text(encoding="utf-8"))
    assert "report_html" in sr_report
    assert sr_report["run_id"] == "runX"

    wd_fv = tmp_path / "wd_fv"
    _exec_final_verify(
        {"node_id": "final_verify",
         "stage_extra": {"campaign_recipe": "r.yaml", "adapter": "fake",
                         "shadow_points": {"n_points": 3, "top_k": 1,
                                           "min_norm_dist": 0.3}}},
        {"work_dir": str(wd_fv), "upstream": upstream})
    sr_fv = json.loads(
        (wd_fv / STAGE_RESULT_FILE).read_text(encoding="utf-8"))
    assert "shadow_selection" in sr_fv
    assert sr_fv["shadow_selection"]["n_selected"] >= 1
    assert sr_fv["adapter_channel"] == "fake->fake"


# ─── 架构批 审查批修复席 F4 钉（P1-2 显式 0 tune 预算 + P3 falsy 位；
# runs/review_aurora_next/A3_service_am/REPORT.md）────────────────────────────

def test_plan_recipe_explicit_zero_max_trials_respected(tmp_path) -> None:
    """A3 P1-2（配方侧）：显式 limits.max_trials: 0 尊为 0——旧
    `limits.get("max_trials") or 30` 把显式 0 顶成 30（#364④ 同族）。"""
    recipe = _ge9b_fake_recipe(tmp_path)
    data = yaml.safe_load(recipe.read_text(encoding="utf-8"))
    data["limits"] = {"max_trials": 0}
    recipe.write_text(yaml.safe_dump(data), encoding="utf-8")
    plan = plan_campaign(str(recipe), mid_adapter="fake",
                         high_adapter="none")
    by_stage = {s["stage"]: s for s in plan["stages"]}
    assert by_stage["tune"]["budget"] == 0
    assert by_stage["prefilter"]["budget"] == 0


def test_explicit_zero_tune_budget_end_to_end(tmp_path, monkeypatch) -> None:
    """A3 P1-2（端到端）：--tune-budget 0 全链落 0——plan 端 stage budget=0
    保真 → nodes campaign_stage_budget={"stage_budget": 0} → 执行端
    is not None 判缺（旧 `or 30` 把显式 0 再顶回 30=S2-3 修复 no-op）。"""
    import rfauto.service.api as api_mod

    # 校准 stage 的 run 目录=create_run_dir(Path(".").resolve())（cwd 相对）
    # ——chdir 隔离（#144 家族终门实证：四日 24 个假 calibration:fake run
    # 污染真实 runs/ 湖，report.md 直指 pytest tmp 配方路径）
    monkeypatch.chdir(tmp_path)
    recipe = _ge9b_fake_recipe(tmp_path)
    plan = plan_campaign(str(recipe), mid_adapter="fake",
                         high_adapter="none", tune_budget=0,
                         tolerances={"arm_len_mm": 0.3})
    assert plan["ok"], plan.get("errors")
    by_stage = {s["stage"]: s for s in plan["stages"]}
    assert by_stage["tune"]["budget"] == 0
    camp = tmp_path / "runs" / "camp_zero"
    save_plan(plan, camp)

    captured: list[int] = []

    def _fake_start_tune(recipe_path, *, adapter_name, max_trials,
                         study_name):
        captured.append(int(max_trials))
        return {"ok": True, "best_params": {"arm_len_mm": 20.5},
                "best_cost": 0.5, "run_id": "",
                "trials_completed": 0, "study_name": study_name}

    monkeypatch.setattr(api_mod, "start_tune", _fake_start_tune)
    res = run_campaign(str(camp),
                       solve_lock_path=str(tmp_path / "solve.lock"),
                       cache_dir=str(tmp_path / "cache"))
    assert res["ok"] is True, res.get("errors")
    assert captured == [0], f"显式 0 预算被顶替: {captured}"


def test_final_verify_explicit_zero_top_k_not_floored(
        tmp_path, monkeypatch) -> None:
    """A3 P3-3：shadow_points.top_k 显式 0 不再被 `or 1` 顶成 1
    （#117 族 falsy 位 is not None 化；缺省档不传仍按缺省）。"""
    import rfauto.service.campaign_manager as cm_mod
    from rfauto.service.campaign_executor import _exec_final_verify

    real = cm_mod.select_shadow_points
    seen: dict = {}

    def _spy(points, *, n_points, top_k, min_norm_dist):
        seen["top_k"] = top_k
        seen["min_norm_dist"] = min_norm_dist
        return real(points, n_points=n_points, top_k=top_k,
                    min_norm_dist=min_norm_dist)

    monkeypatch.setattr(cm_mod, "select_shadow_points", _spy)
    tunedir = tmp_path / "tune_wd"
    tunedir.mkdir()
    (tunedir / STAGE_RESULT_FILE).write_text(json.dumps(
        {"ok": True, "run_id": "", "best_params": {"a": 0.5},
         "best_cost": 0.1}), encoding="utf-8")
    upstream = {"tune": {"artifact_run_dir": str(tunedir)}}
    _exec_final_verify(
        {"node_id": "final_verify",
         "stage_extra": {"campaign_recipe": "r.yaml", "adapter": "fake",
                         "shadow_points": {"n_points": 2, "top_k": 0,
                                           "min_norm_dist": 0.3}}},
        {"work_dir": str(tmp_path / "wd"), "upstream": upstream})
    assert seen["top_k"] == 0
    # 缺省档（不写 top_k）仍按缺省 1：None → 1
    _exec_final_verify(
        {"node_id": "final_verify",
         "stage_extra": {"campaign_recipe": "r.yaml", "adapter": "fake",
                         "shadow_points": {"n_points": 2}}},
        {"work_dir": str(tmp_path / "wd2"), "upstream": upstream})
    assert seen["top_k"] == 1


def test_seat_payload_explicit_zero_timeout_not_floored(tmp_path) -> None:
    """A3 P3-3：座位 timeout_s 显式 0 不再被 `or 2400.0` 顶成 2400
    （#117 族 falsy 位 is not None 化）；未声明仍落缺省 2400。"""
    from rfauto.service.campaign_executor import _resolve_seat_payload

    node = {"node_id": "tune", "stage_extra": {"campaign_dir": str(tmp_path)}}
    seat, err = _resolve_seat_payload(
        {"seat": {"simulation_py": "sim.py", "timeout_s": 0}}, node,
        {"run_dir": str(tmp_path)})
    assert err is None
    assert seat["timeout_s"] == 0.0
    seat_def, _ = _resolve_seat_payload(
        {"seat": {"simulation_py": "sim.py"}}, node,
        {"run_dir": str(tmp_path)})
    assert seat_def["timeout_s"] == 2400.0
