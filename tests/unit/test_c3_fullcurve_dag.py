"""DP-9 P3：c3_fullcurve_runner stage 真跑段 DAG 包装单测（tmp run_dir 零真机）。

判据（规格 §5，全合成零真机零网络；已落接口 core.compose.dag_schema/
infra.dag_cache/pipeline.dag_runner 只消费不改）：
① 缺省路径零变化：同参数缺省路径 vs DAG 路径（mock 发射）plan.json stage1
   声明块关键段一致（declared_utc 除外，_payload_equal 口径）+ 缺省路径零
   dag 产物面（无 dag.state.json/dag.artifact.json）；
② 节点键构成：cmd / budget(nrts) / registration_commit_ts 任一变化 → decl 与
   solve 键都变（P2 solve 键成分不含 cmd/注册 ts 的缺口经 decl 键 + decl 产物
   dag_decl.json 字节 + 上游键传导补齐，接口零改动）；
③ fake executor（monkeypatch 低层发射器）跑通 run_dag 两节点链 + 期刊落盘
   （dag.state.json 两节点 done、stage 目录 dag.artifact.json、decl 落痕）；
④ 断点续跑：第一次跑完 stage1 后"重启"（全新 run_stage_via_dag 调用）→
   n_hit=2 / n_recompute=0、低层发射器零再调（test_dag_runner kill 用例口径）；
⑤ SolveMachineMutex：陈锁假占锁 → 接管放行；注入 acquire=False → solve 节点
   判废（failed/ABORTED、发射器零调用），解锁后重跑 failed 分支重试复活；
⑥ #145 接线：runner_deadline = Abort 真打断 → 判废重试（escalated ×1.5 实测
   到发射 deadline）；竞态完成（wall>截止仍交付）→ RaceCompleted 接受真结果。
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load_script("c3_fullcurve_runner")

T = "interdigital"
_REG_TS = "1700000000"
_EV = "openems-fake-ev"

_MIN_ENGINE_LOG = (
    "FDTD simulation size: 499x1083x23 --> 1.24e+07 FDTD cells\n"
    "FDTD timestep is: 1.38713e-13 s; Nyquist rate: 1310 timesteps @2.75e+09 Hz\n"
    "Excitation signal length is: 82611 timesteps (1.14592e-08s)\n"
)


@pytest.fixture(autouse=True)
def _clean_cache_env(monkeypatch):
    """隔离 RFAUTO_CACHE（防环境泄漏改变索引模式语义；#139 钉通道精神）。"""
    monkeypatch.delenv("RFAUTO_CACHE", raising=False)


def _make_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    runner._plan_write({"batch": "smoke_c3_fullcurve",
                        "templates": {t: {} for t in ("combline", "interdigital",
                                                      "sir_bpf")}}, root)


def _fake_launch1(work: Path, *, rc: int = 0, killed: str | None = None,
                  elapsed_s: float = 1.0, sleep_s: float = 0.0):
    """stage1 低层发射器替身：写最小产物 + 记录 (cmd, deadline)。"""
    calls: list[dict] = []

    def launch(cmd, timeout_s, cwd):
        calls.append({"cmd": list(cmd), "timeout_s": float(timeout_s)})
        if sleep_s:
            time.sleep(sleep_s)
        (work / "simulation.py").write_text("# rendered stage1\n",
                                            encoding="utf-8")
        (work / "engine.log").write_text(_MIN_ENGINE_LOG, encoding="utf-8")
        return {"rc": rc, "killed": killed, "elapsed_s": elapsed_s,
                "stdout_tail": "", "stderr_tail": ""}

    return launch, calls


def _fake_launch2(work: Path, *, rc: int = 0, killed: str | None = None):
    """stage2 低层发射器替身（run_stage2 的 kwargs 签名）。"""
    calls: list[dict] = []

    def launch(cmd, work=None, template=None, timeout_s=None, budget_s=None,
               cwd=None):
        calls.append({"cmd": list(cmd), "timeout_s": timeout_s,
                      "budget_s": budget_s})
        (work / "simulation.py").write_text("# rendered stage2\n",
                                            encoding="utf-8")
        (work / "engine.log").write_text(_MIN_ENGINE_LOG, encoding="utf-8")
        return {"rc": rc, "killed": killed}

    return launch, calls


def _run_stage1_dag(root: Path, monkeypatch, *, cap_s: float = 5040.0,
                    reg: str = _REG_TS, cache_dir=None):
    work = runner.stage_dir(T, "stage1", root)
    fake, calls = _fake_launch1(work)
    monkeypatch.setattr(runner, "_launch_stage1_real", fake)
    cmd = runner.stage_cmd(T, "stage1", cap_s, root=root)
    out = runner.run_stage_via_dag(
        T, "stage1", cmd, root=root, cap_s=cap_s, cache_dir=cache_dir,
        solve_lock_path=root.parent / "solve.lock",
        registration_commit_ts=reg, engine_version=_EV)
    return out, cmd, calls


def _run_stage2_dag(root: Path, monkeypatch, *, nrts: int,
                    cache_dir=None, budget_s: float = 1000.0):
    work = runner.stage_dir(T, "stage2", root)
    fake, calls = _fake_launch2(work)
    monkeypatch.setattr(runner, "_launch_stage2_real", fake)
    cmd = runner.stage_cmd(T, "stage2", 48000.0, nrts=nrts, root=root)
    out = runner.run_stage_via_dag(
        T, "stage2", cmd, root=root, budget_s=budget_s, cache_dir=cache_dir,
        solve_lock_path=root.parent / "solve.lock",
        registration_commit_ts=_REG_TS, engine_version=_EV)
    return out, cmd, calls


def _journal_keys(root: Path) -> dict:
    state = json.loads((root / T / "dag.state.json").read_text(encoding="utf-8"))
    return {nid: e.get("key", "") for nid, e in state["nodes"].items()}


# ─── 节点拓扑与计划结构 ─────────────────────────────────────────────────────────

def test_build_stage_dag_plan_structure_and_parse():
    cmd = runner.stage_cmd(T, "stage2", 48000.0, nrts=12345)
    plan = runner.build_stage_dag_plan(
        T, "stage2", cmd,
        budget={"timeout_s": 100.0, "nrts": 12345, "mesh_tier": "0.301",
                "mesh": 0.301},
        registration_commit_ts=_REG_TS)
    from rfauto.core.compose.dag_schema import parse_dag
    parsed = parse_dag(plan)
    assert parsed["ok"] is True
    assert parsed["order"] == ["stage2_decl", "stage2"]
    decl, solve = parsed["nodes"]
    assert decl["kind"] == "render" and solve["kind"] == "solve"
    assert solve["depends_on"] == ["stage2_decl"]
    assert decl["cmd"] == " ".join(cmd) and solve["cmd"] == " ".join(cmd)
    assert solve["retries"] == 1 and decl["retries"] == 0
    assert solve["inputs"]["files"] == ["simulation.py"]
    assert solve["budget"]["nrts"] == 12345
    assert solve["budget"]["timeout_s"] == pytest.approx(100.0)
    # 注册 ts 走 decl params（P2 normalize_node 只保 inputs.files/params——缺口
    # 注记见 runner 模块注释），渲染源/smoke 脚本 sha 为脏工作树守卫
    assert decl["inputs"]["params"]["registration_commit_ts"] == _REG_TS
    assert decl["inputs"]["params"]["smoke_script_sha256"]
    assert decl["inputs"]["params"]["render_source_sha256"]


def test_openems_registration_ts_nonempty_in_repo():
    """handoff §四：registration_commit_ts 对 openems_templates.py 实测非空。"""
    if not (REPO / ".git").exists():
        pytest.skip("非 git 工作区")
    ts = runner.openems_registration_ts()
    assert ts != "" and ts.isdigit()
    assert ts == runner.openems_registration_ts()      # 同工作树确定性


def test_stage_mesh_tier_deterministic():
    assert runner.stage_mesh_tier(T) == runner.stage_mesh_tier(T)
    assert isinstance(runner.stage_mesh_tier(T), str)


# ─── ① 缺省路径零变化 ───────────────────────────────────────────────────────────

def test_default_path_zero_change_plan_block(tmp_path, monkeypatch):
    """同参数 mock 引擎：缺省路径（launch_fn=None）与 DAG 路径的 plan.json
    stage1 声明块关键段一致（declared_utc 除外）；缺省路径零 dag 产物面。"""
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    _make_plan(root_a)
    _make_plan(root_b)
    fake_a, calls_a = _fake_launch1(runner.stage_dir(T, "stage1", root_a))
    fake_b, calls_b = _fake_launch1(runner.stage_dir(T, "stage1", root_b))
    monkeypatch.setattr(runner, "_launch_stage1_real", fake_a)
    summary_a = runner.run_stage1(T, root_a, guard=lambda: [])
    monkeypatch.setattr(runner, "_launch_stage1_real", fake_b)
    summary_b = runner.run_stage1(
        T, root_b,
        launch_fn=runner.dag_launch_stage1(
            T, root_b, cap_s=5040.0, cache_dir=tmp_path / "cache_b",
            solve_lock_path=tmp_path / "s_b.lock"),
        guard=lambda: [])
    assert len(calls_a) == 1 and len(calls_b) == 1
    # 发射命令同源（cmd=现值不变）：两路径都是未改动的 stage_cmd 构造器产物，
    # 仅 --root 因演练根不同而异（cmd 内嵌 root ⇒ 键天然 per-campaign）
    assert calls_a[0]["cmd"] == runner.stage_cmd(T, "stage1", 5040.0, root=root_a)
    assert calls_b[0]["cmd"] == runner.stage_cmd(T, "stage1", 5040.0, root=root_b)

    def _cmd_without_root(c: list) -> list:
        i = c.index("--root")
        return c[:i] + c[i + 2:]

    assert _cmd_without_root(calls_a[0]["cmd"]) == _cmd_without_root(calls_b[0]["cmd"])
    assert summary_a["verdict"] == summary_b["verdict"]
    pa = runner._plan_load(root_a)["templates"][T]["stage1"]
    pb = runner._plan_load(root_b)["templates"][T]["stage1"]
    assert runner._payload_equal(pa, pb)
    # 缺省路径零 dag 产物面；DAG 路径有（证据面只新增）
    assert not (root_a / T / "dag.state.json").exists()
    assert not (root_a / T / "stage1" / "dag.artifact.json").exists()
    assert (root_b / T / "dag.state.json").is_file()
    assert (root_b / T / "stage1" / "dag.artifact.json").is_file()


# ─── ③ fake executor 两节点链 + 期刊落盘 ───────────────────────────────────────

def test_dag_path_two_node_chain_journal_and_manifest(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    out, cmd, calls = _run_stage1_dag(root, monkeypatch,
                                      cache_dir=tmp_path / "cache")
    assert out["rc"] == 0 and len(calls) == 1
    dag = out["dag"]
    assert dag["verdict"] == "COMPLETE"
    assert dag["n_hit"] == 0 and dag["n_recompute"] == 2
    assert dag["statuses"] == {"stage1_decl": "done", "stage1": "done"}
    # 期刊落盘（<root>/<template>/dag.state.json，两节点 done）
    state = json.loads((root / T / "dag.state.json").read_text(encoding="utf-8"))
    assert state["nodes"]["stage1"]["status"] == "done"
    assert state["nodes"]["stage1_decl"]["status"] == "done"
    # stage 目录 dag.artifact.json（现状目录即节点工作目录，证据面只新增）
    man = json.loads((runner.stage_dir(T, "stage1", root)
                      / "dag.artifact.json").read_text(encoding="utf-8"))
    assert man["complete"] is True
    assert [f["path"] for f in man["files"]] == ["engine.log", "simulation.py"]
    assert man["node_id"] == "stage1"
    # decl 落痕：cmd/预算/注册 ts 进 dag_decl.json，无时间戳（字节级可复现）
    doc = json.loads((root / T / "stage1_decl" / "dag_decl.json")
                     .read_text(encoding="utf-8"))
    assert doc["cmd"] == " ".join(cmd)
    assert doc["registration_commit_ts"] == _REG_TS
    assert doc["budget"]["timeout_s"] == pytest.approx(5040.0)
    assert doc["budget"]["nrts"] is None
    assert "generated_utc" not in doc and "declared_utc" not in doc
    # node_budget 观测键（solve 键预算档来源）
    assert dag["node_budget"]["timeout_s"] == pytest.approx(5040.0)
    assert dag["node_budget"]["mesh_tier"] == runner.stage_mesh_tier(T)


def test_stage2_direct_node_budget_carries_nrts_and_budget(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    out, cmd, calls = _run_stage2_dag(root, monkeypatch, nrts=4321,
                                      cache_dir=tmp_path / "cache")
    assert out["rc"] == 0 and len(calls) == 1
    assert out["dag"]["verdict"] == "COMPLETE"
    assert out["dag"]["nrts"] == 4321
    assert out["dag"]["node_budget"]["nrts"] == 4321
    assert out["dag"]["node_budget"]["timeout_s"] == pytest.approx(1000.0)
    doc = json.loads((root / T / "stage2_decl" / "dag_decl.json")
                     .read_text(encoding="utf-8"))
    assert doc["budget"]["nrts"] == 4321
    assert "--nrts" in cmd and doc["cmd"] == " ".join(cmd)


def test_decl_artifact_bytes_deterministic_across_reruns(tmp_path, monkeypatch):
    """decl 产物无时间戳 → 同 root 重跑（清树后）dag_decl.json 字节级相同
    （上游重跑产物字节级不变 ⇒ 下游零重算的判据②前提）。"""
    root = tmp_path / "runs"
    _run_stage1_dag(root, monkeypatch, cache_dir=tmp_path / "cache")
    before = (root / T / "stage1_decl" / "dag_decl.json").read_bytes()
    before_sim = (root / T / "stage1_decl" / "simulation.py").read_bytes()
    shutil.rmtree(root / T)
    _run_stage1_dag(root, monkeypatch, cache_dir=tmp_path / "cache")
    assert (root / T / "stage1_decl" / "dag_decl.json").read_bytes() == before
    assert (root / T / "stage1_decl" / "simulation.py").read_bytes() == before_sim


# ─── ② 节点键构成（cmd/budget/registration_commit_ts 改任一→键变）──────────────

def test_key_sensitivity_cmd_changes_decl_and_solve_keys(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    _run_stage1_dag(root, monkeypatch, cap_s=5040.0, cache_dir=tmp_path / "c")
    k1 = _journal_keys(root)
    _run_stage1_dag(root, monkeypatch, cap_s=6000.0, cache_dir=tmp_path / "c")
    k2 = _journal_keys(root)
    assert k1["stage1_decl"] != k2["stage1_decl"]
    assert k1["stage1"] != k2["stage1"]          # cmd 变 → solve 键变（decl 传导）


def test_key_sensitivity_nrts_budget_changes_solve_key(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    _run_stage2_dag(root, monkeypatch, nrts=1000, cache_dir=tmp_path / "c")
    k1 = _journal_keys(root)
    _run_stage2_dag(root, monkeypatch, nrts=2000, cache_dir=tmp_path / "c")
    k2 = _journal_keys(root)
    assert k1["stage2_decl"] != k2["stage2_decl"]      # cmd 内嵌 --nrts
    assert k1["stage2"] != k2["stage2"]                # budget_tier（#343/#262）


def test_key_sensitivity_registration_ts_changes_keys(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    _run_stage1_dag(root, monkeypatch, reg="1700000000", cache_dir=tmp_path / "c")
    k1 = _journal_keys(root)
    _run_stage1_dag(root, monkeypatch, reg="1700000001", cache_dir=tmp_path / "c")
    k2 = _journal_keys(root)
    assert k1["stage1_decl"] != k2["stage1_decl"]
    assert k1["stage1"] != k2["stage1"]          # 注册 ts 变 → solve 键经传导变


# ─── ④ 断点续跑（跑完 stage1 后"重启"→ 零重算）─────────────────────────────────

def test_resume_after_stage1_complete_zero_recompute(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    work = runner.stage_dir(T, "stage1", root)
    fake, calls = _fake_launch1(work)          # 同一发射器替身贯穿两次调用
    monkeypatch.setattr(runner, "_launch_stage1_real", fake)
    cmd = runner.stage_cmd(T, "stage1", 5040.0, root=root)
    kwargs = dict(root=root, cache_dir=tmp_path / "cache",
                  solve_lock_path=tmp_path / "s.lock",
                  registration_commit_ts=_REG_TS, engine_version=_EV)
    out1 = runner.run_stage_via_dag(T, "stage1", cmd, cap_s=5040.0, **kwargs)
    assert out1["dag"]["n_recompute"] == 2 and len(calls) == 1
    # “重启”= 全新 run_stage_via_dag 调用（同 run_dir/同 cache，#157 死树重启同型）
    out2 = runner.run_stage_via_dag(T, "stage1", cmd, cap_s=5040.0, **kwargs)
    assert out2["dag"]["verdict"] == "COMPLETE"
    assert out2["dag"]["n_hit"] == 2
    assert out2["dag"]["n_recompute"] == 0, "已完成节点被重算（断点续跑语义破坏）"
    assert len(calls) == 1, "低层发射器被重复调用（零重算破坏）"


# ─── ⑤ SolveMachineMutex：假占锁 / 判废重试 ───────────────────────────────────

def test_solve_mutex_stale_fake_lock_takeover(tmp_path, monkeypatch):
    """假占锁（持有者 pid 已死的陈锁）→ 陈锁接管放行（acquire_lock 式样）。"""
    dr, _ = runner._dag_deps()
    lock = tmp_path / "oe_collect.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"task": "dag_solve", "pid": 999999999}),
                    encoding="utf-8")
    monkeypatch.setattr(dr, "_pid_alive", lambda pid: False)
    root = tmp_path / "runs"
    work = runner.stage_dir(T, "stage1", root)
    fake, calls = _fake_launch1(work)
    monkeypatch.setattr(runner, "_launch_stage1_real", fake)
    cmd = runner.stage_cmd(T, "stage1", 5040.0, root=root)
    out = runner.run_stage_via_dag(
        T, "stage1", cmd, root=root, cache_dir=tmp_path / "cache",
        solve_lock_path=lock, registration_commit_ts=_REG_TS,
        engine_version=_EV)
    assert out["rc"] == 0 and len(calls) == 1     # 陈锁接管后照常发射
    assert out["dag"]["verdict"] == "COMPLETE"
    assert not lock.exists(), "派发结束后家族锁未释放"


def test_solve_mutex_blocked_fails_then_retry_after_release(tmp_path, monkeypatch):
    """注入 acquire=False（互斥不可得）→ solve 节点判废 failed/下游 ABORTED、
    发射器零调用；解锁后重跑：failed 分支重启重试复活（decl 零重算）。"""
    dr, _ = runner._dag_deps()
    original_acquire = dr.SolveMachineMutex.acquire
    monkeypatch.setattr(dr.SolveMachineMutex, "acquire",
                        lambda self, **kw: False)
    root = tmp_path / "runs"
    work = runner.stage_dir(T, "stage1", root)
    fake, calls = _fake_launch1(work)
    monkeypatch.setattr(runner, "_launch_stage1_real", fake)
    cmd = runner.stage_cmd(T, "stage1", 5040.0, root=root)
    kwargs = dict(root=root, cache_dir=tmp_path / "cache", solve_lock_path=root
                  .parent / "solve.lock", registration_commit_ts=_REG_TS,
                  engine_version=_EV)
    out1 = runner.run_stage_via_dag(T, "stage1", cmd, **kwargs)
    assert out1["killed"] == "dag_no_launch" and calls == []
    assert out1["dag"]["verdict"] == "ABORTED"
    assert out1["dag"]["statuses"]["stage1"] == "failed"
    # 解锁（恢复 acquire）→ 重跑：failed 分支重启重试，decl 命中零重算
    monkeypatch.setattr(dr.SolveMachineMutex, "acquire", original_acquire)
    out2 = runner.run_stage_via_dag(T, "stage1", cmd, **kwargs)
    assert out2["rc"] == 0 and len(calls) == 1
    assert out2["dag"]["verdict"] == "COMPLETE"
    assert out2["dag"]["n_hit"] == 1 and out2["dag"]["n_recompute"] == 1


# ─── ⑥ #145 接线：Abort 判废重试 / 竞态完成 ───────────────────────────────────

def test_abort_runner_deadline_retries_with_escalated_budget(tmp_path, monkeypatch):
    """killed=runner_deadline = Abort 真打断 → NodeAbortedError 判废重试，
    重试 deadline 按 escalated_budget ×1.5 实测到发射器（5040×1.5+900）。"""
    root = tmp_path / "runs"
    work = runner.stage_dir(T, "stage1", root)
    calls: list[float] = []

    def flaky(cmd, timeout_s, cwd):
        calls.append(float(timeout_s))
        if len(calls) == 1:
            return {"rc": None, "killed": "runner_deadline",
                    "elapsed_s": float(timeout_s),
                    "stdout_tail": "", "stderr_tail": ""}
        (work / "simulation.py").write_text("# rendered\n", encoding="utf-8")
        (work / "engine.log").write_text(_MIN_ENGINE_LOG, encoding="utf-8")
        return {"rc": 0, "killed": None, "elapsed_s": 1.0,
                "stdout_tail": "", "stderr_tail": ""}

    monkeypatch.setattr(runner, "_launch_stage1_real", flaky)
    cmd = runner.stage_cmd(T, "stage1", 5040.0, root=root)
    out = runner.run_stage_via_dag(
        T, "stage1", cmd, root=root, cap_s=5040.0, runner_timeout_s=5940.0,
        cache_dir=tmp_path / "cache", solve_lock_path=tmp_path / "s.lock",
        registration_commit_ts=_REG_TS, engine_version=_EV)
    assert calls == pytest.approx([5940.0, 5040.0 * 1.5 + 900.0])
    assert out["rc"] == 0
    assert out["dag"]["verdict"] == "COMPLETE"
    state = json.loads((root / T / "dag.state.json").read_text(encoding="utf-8"))
    notes = " ".join(state["nodes"]["stage1"]["notes"])
    assert "Abort 真打断" in notes


def test_race_completed_accepted_via_dag(tmp_path, monkeypatch):
    """rc=0 而 wall 超截止（帽值微缩试验档）→ RaceCompleted 竞态接受真结果
    （#145：不丢已算完的数据；wall 实测进 journal）。"""
    root = tmp_path / "runs"
    work = runner.stage_dir(T, "stage1", root)
    fake, calls = _fake_launch1(work, sleep_s=0.05)
    monkeypatch.setattr(runner, "_launch_stage1_real", fake)
    cmd = runner.stage_cmd(T, "stage1", 5040.0, root=root)
    out = runner.run_stage_via_dag(
        T, "stage1", cmd, root=root, cap_s=0.04, runner_timeout_s=5940.0,
        cache_dir=tmp_path / "cache", solve_lock_path=tmp_path / "s.lock",
        registration_commit_ts=_REG_TS, engine_version=_EV)
    assert out["rc"] == 0 and len(calls) == 1
    # 试验帽 0.04s×1.5 预算帽与 sleep 0.05s 同量级——verdict 至最坏 PARTIAL
    # （超预算入库不删数据）；判据面=竞态接受注记（RaceCompleted 翻译成立）
    assert out["dag"]["verdict"] in ("COMPLETE", "PARTIAL")
    state = json.loads((root / T / "dag.state.json").read_text(encoding="utf-8"))
    entry = state["nodes"]["stage1"]
    assert entry["status"] in ("done", "partial")   # 超预算帽至最坏 PARTIAL
    notes = " ".join(entry["notes"])
    assert "竞态完成接受真结果" in notes
