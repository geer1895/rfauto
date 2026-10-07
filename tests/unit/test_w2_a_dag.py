"""VI-4/SN-1：rfauto dag run / dag status CLI 接线测试（Phase2 W2-A）。

规格判据（sp_specs6 §VI-4 预声明）：
①断点续跑演练：两节点链（render 产文件、solve 消费），solve 中段整树 kill
  （#157 模拟：孙进程 os.kill 父 runner）→ 重跑同参 → node1 零重执行
  （journal _resume_decision 命中 done/键引用 + 执行计数器不复增）且终态
  done、node2 产物在盘；
②互斥生效：同 run_dir 并发第二实例被拒（rc≠0+信封 errors 含 lock 字样）；
③dag status 对演练 run 三态各一例（done/failed/inconclusive）；
④--json 双路径信封（成功+失败）；
⑤零数值面（AST 探针：浮点字面量白名单+禁 numpy/scipy/数值内核 import+
  物理量词面零命中，铁律 7）。

全合成零真机零网络（#139 精神）：执行器=vi 内建 subprocess，cmd 全部指向
tmp 内一次性 helper 脚本；#261 互斥锁与 CAS 缓存目录均落 tmp。
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from rfauto.cli.domains.dag import dag_app, dag_run, dag_status
from rfauto.pipeline.dag_runner import (
    DAG_RUN_LOCK_NAME,
    DAG_STATE_FILE,
    acquire_lock,
    release_lock,
)

runner = CliRunner()
_REPO = Path(__file__).resolve().parents[2]

#: 零数值面白名单：本模块允许的浮点字面量（仅 lock-wait 占即拒缺省）。
_ALLOWED_FLOATS = {0.0}
_BANNED_IMPORT_TOKENS = ("numpy", "scipy", "pandas", "calc_families")


# ─── helper 脚本模板（cmd 面全部经 shlex 分词的声明性命令串）─────────────────

_RENDER_HELPER = """\
import sys
from pathlib import Path
out, counter = sys.argv[1], sys.argv[2]
Path(out).write_text("rendered:v1\\n", encoding="utf-8")
with open(counter, "a", encoding="utf-8") as f:
    f.write("render\\n")
"""

_SOLVE_HELPER = """\
import sys, time
from pathlib import Path
marker, out = sys.argv[1], sys.argv[2]
if Path(marker).exists():
    # 续跑轮：第二次尝试完成产物（判废重试/续跑语义的确定性替身）
    Path(out).write_text("solved:v1\\n", encoding="utf-8")
    sys.exit(0)
Path(marker).write_text("solving\\n", encoding="utf-8")
time.sleep(600)   # 首轮长睡：被外部树杀打断（#157 中段 kill 形态）
"""

_SOFT_HELPER = """\
import sys
sys.exit(0)
"""

_FAIL_HELPER = """\
import sys
sys.stderr.write("boom: intentional failure\\n")
sys.exit(3)
"""


def _pyexe() -> str:
    return sys.executable.replace("\\", "/")


def _two_node_plan(tmp_path: Path, counter: Path, run_dir: Path) -> dict:
    """两节点链计划（规格判据①形态：render 产文件 → solve 消费）。

    产物目标=节点工作目录（run_dir/<node_id>/，基座 digest 面的相对产物根）。
    """
    render_helper = tmp_path / "render_helper.py"
    render_helper.write_text(_RENDER_HELPER, encoding="utf-8")
    solve_helper = tmp_path / "solve_helper.py"
    solve_helper.write_text(_SOLVE_HELPER, encoding="utf-8")
    return {
        "nodes": [
            {"node_id": "n1_render", "kind": "render", "depends_on": [],
             "inputs": {"files": [], "params": {}},
             "outputs": ["rendered.txt"],
             "cmd": f'"{_pyexe()}" "{render_helper.as_posix()}" '
                    f'"{(run_dir / "n1_render" / "rendered.txt").as_posix()}" '
                    f'"{counter.as_posix()}"',
             "budget": {}},
            {"node_id": "n2_solve", "kind": "solve",
             "depends_on": ["n1_render"],
             "inputs": {"files": [], "params": {}},
             "outputs": ["solved.txt"],
             "cmd": f'"{_pyexe()}" "{solve_helper.as_posix()}" '
                    f'"{(tmp_path / "solve_started.txt").as_posix()}" '
                    f'"{(run_dir / "n2_solve" / "solved.txt").as_posix()}"',
             "budget": {}},
        ],
    }


def _child_runner_script(tmp_path: Path) -> Path:
    """子进程 runner（独立进程跑 dag_run——kill 才有意义；#157 同型）。"""
    script = tmp_path / "runner_child.py"
    script.write_text(
        "import json, sys\n"
        "from rfauto.cli.domains.dag import dag_run\n"
        "plan, run_dir, cache_dir, solve_lock = sys.argv[1:5]\n"
        "result = dag_run(plan, run_dir, cache_dir=cache_dir,\n"
        "                 solve_lock=solve_lock)\n"
        "print(json.dumps(result, ensure_ascii=False, default=str))\n",
        encoding="utf-8")
    return script


def _wait_node_status(run_dir: Path, node_id: str, status: str,
                      timeout_s: float = 60.0) -> dict:
    """轮询状态期刊直到节点进入指定态（kill 时机同步）。"""
    import time as _t
    deadline = _t.monotonic() + timeout_s
    while _t.monotonic() < deadline:
        try:
            state = json.loads(
                (run_dir / DAG_STATE_FILE).read_text(encoding="utf-8"))
            got = (state.get("nodes", {}).get(node_id) or {}).get("status", "")
            if got == status:
                return state
        except (OSError, ValueError):
            pass
        _t.sleep(0.1)
    raise AssertionError(
        f"节点 {node_id} 未在 {timeout_s}s 内进入 {status}（期刊: "
        f"{(run_dir / DAG_STATE_FILE).read_text(encoding='utf-8')[:400]}）")


def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO / "src") + os.pathsep + env.get(
        "PYTHONPATH", "")
    env.pop("RFAUTO_CACHE", None)
    return env


# ─── 判据①：断点续跑演练（node2 中段 kill → 重跑 node1 零重执行）─────────────

def test_resume_after_mid_solve_tree_kill(tmp_path) -> None:
    run_dir = tmp_path / "run1"
    cache_dir = tmp_path / "cache"
    solve_lock = tmp_path / "solve.lock"
    counter = tmp_path / "render_calls.txt"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(_two_node_plan(tmp_path, counter, run_dir),
                   ensure_ascii=False),
        encoding="utf-8")

    # 第一跑：独立子进程，n2 solve 中段被外部整树硬杀（#157 树死形态；
    # 本环境沙箱禁杀祖先进程——杀的面=pytest 自己的子树，等效且可达）
    child = _child_runner_script(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, str(child), str(plan_path), str(run_dir),
         str(cache_dir), str(solve_lock)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env=_child_env())
    try:
        _wait_node_status(run_dir, "n2_solve", "running")
        # kill 时机=helper 真启动（marker 落盘）：只等"节点 running"会与
        # helper 进程 spawn 竞速——负载下 kill 落在 marker 写前，续跑轮走
        # 首轮分支长睡 600s（W3 合流门两轮实证 wall 翻倍的元凶）。
        import time as _time
        _marker = tmp_path / "solve_started.txt"
        _deadline = _time.monotonic() + 30.0
        while not _marker.exists():
            assert _time.monotonic() < _deadline, "helper 未在 30s 内写 marker"
            _time.sleep(0.05)
        kill = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, text=True, timeout=30)
        assert kill.returncode == 0, (
            f"树杀失败 rc={kill.returncode} out={kill.stdout} err={kill.stderr}")
        rc = proc.wait(timeout=60)
    finally:
        if proc.poll() is None:  # 兜底清树（不留孤儿 python）
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, text=True, timeout=30)
            proc.wait(timeout=30)
    assert rc != 0, f"子进程未按预期硬死 rc={rc}"

    # 死树现场：n1 已 done、n2 停在 running、运行锁残留（持有者已死）
    state = json.loads((run_dir / DAG_STATE_FILE).read_text(encoding="utf-8"))
    assert state["nodes"]["n1_render"]["status"] == "done"
    assert state["nodes"]["n2_solve"]["status"] == "running"
    assert (run_dir / DAG_RUN_LOCK_NAME).is_file()
    assert (run_dir / "n1_render" / "rendered.txt").is_file()
    assert counter.read_text(encoding="utf-8").count("render") == 1

    # 重跑同参（断点续跑由 _resume_decision 承担；陈锁按 pid 死亡自动接管）
    result = dag_run(str(plan_path), str(run_dir), cache_dir=str(cache_dir),
                     solve_lock=str(solve_lock))
    assert result["ok"] is True, result.get("errors")
    assert result["verdict"] == "COMPLETE"
    assert result["n_hit"] == 1, f"已完成节点未零重算跳过: {result}"
    assert result["n_recompute"] == 1
    assert result["statuses"]["n1_render"] == "done"
    assert result["statuses"]["n2_solve"] == "done"
    # node1 产物在盘且零重执行（计数器不复增）
    assert (run_dir / "n1_render" / "rendered.txt").is_file()
    assert (run_dir / "n2_solve" / "solved.txt").is_file()
    assert counter.read_text(encoding="utf-8").count("render") == 1
    # journal 复核：_resume_decision 命中 done（skip 理由带"键同+digest 过"）
    log_text = (run_dir / "dag.log").read_text(encoding="utf-8")
    assert "[hit] n1_render" in log_text
    assert "断点续跑零重算" in log_text
    # 终局运行锁释放（陈锁接管后正常收尾）
    assert not (run_dir / DAG_RUN_LOCK_NAME).exists()


# ─── 判据②：互斥生效（同 run_dir 并发第二实例被拒）───────────────────────────

def test_second_instance_rejected_by_run_lock(tmp_path) -> None:
    run_dir = tmp_path / "run2"
    run_dir.mkdir(parents=True)
    counter = tmp_path / "c2.txt"
    plan_path = tmp_path / "plan2.json"
    plan_path.write_text(
        json.dumps(_two_node_plan(tmp_path, counter, run_dir),
                   ensure_ascii=False),
        encoding="utf-8")
    holder = acquire_lock("holder", run_dir / DAG_RUN_LOCK_NAME, max_wait_s=0.0)
    try:
        # --json 路径：rc≠0 + 信封 errors 含锁路径（lock 字样）
        res = runner.invoke(
            dag_app,
            ["run", str(plan_path), "--run-dir", str(run_dir),
             "--cache-dir", str(tmp_path / "cache2"),
             "--solve-lock", str(tmp_path / "solve2.lock"), "--json"])
        assert res.exit_code != 0, res.output
        envelope = json.loads(res.output)
        assert envelope["ok"] is False
        assert any("lock" in str(e) for e in envelope["errors"]), envelope
        assert any("运行锁被占" in str(e) for e in envelope["errors"])
        # 非 --json 路径：同样 rc≠0（人读红字）
        res2 = runner.invoke(
            dag_app,
            ["run", str(plan_path), "--run-dir", str(run_dir),
             "--solve-lock", str(tmp_path / "solve2.lock")])
        assert res2.exit_code != 0
    finally:
        release_lock(holder, run_dir / DAG_RUN_LOCK_NAME)


# ─── 判据③：dag status 三态各一例（done/failed/inconclusive）────────────────

def test_dag_status_three_states(tmp_path) -> None:
    render_helper = tmp_path / "r.py"
    render_helper.write_text(_RENDER_HELPER, encoding="utf-8")
    soft_helper = tmp_path / "soft.py"
    soft_helper.write_text(_SOFT_HELPER, encoding="utf-8")
    fail_helper = tmp_path / "fail.py"
    fail_helper.write_text(_FAIL_HELPER, encoding="utf-8")
    counter = tmp_path / "c3.txt"
    run_dir = tmp_path / "run3"
    plan = {
        "nodes": [
            {"node_id": "s1_render", "kind": "render", "depends_on": [],
             "inputs": {"files": [], "params": {}},
             "outputs": ["rendered.txt"],
             "cmd": f'"{_pyexe()}" "{render_helper.as_posix()}" '
                    f'"{(run_dir / "s1_render" / "rendered.txt").as_posix()}" '
                    f'"{counter.as_posix()}"', "budget": {}},
            # QW-7 途径②：声明产物缺失全部命中 soft 清单 → inconclusive
            {"node_id": "s2_judge", "kind": "judge",
             "depends_on": ["s1_render"],
             "inputs": {"files": [], "params": {}},
             "outputs": ["evidence/gate.csv"],
             "inconclusive_when": {"outputs_missing_any":
                                   ["evidence/gate.csv"]},
             "cmd": f'"{_pyexe()}" "{soft_helper.as_posix()}"',
             "budget": {}},
            {"node_id": "s3_post", "kind": "postprocess",
             "depends_on": ["s1_render"],
             "inputs": {"files": [], "params": {}}, "outputs": [],
             "cmd": f'"{_pyexe()}" "{fail_helper.as_posix()}"',
             "budget": {}},
        ],
    }
    plan_path = tmp_path / "plan3.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False),
                         encoding="utf-8")
    result = dag_run(str(plan_path), str(run_dir),
                     cache_dir=str(tmp_path / "cache3"),
                     solve_lock=str(tmp_path / "solve3.lock"))
    assert result["ok"] is False          # 有 failed 节点 → ABORTED
    assert result["verdict"] == "ABORTED"

    status = dag_status(str(run_dir))
    assert status["ok"] is True
    by_id = {n["node_id"]: n for n in status["nodes"]}
    assert by_id["s1_render"]["status"] == "done"
    assert by_id["s2_judge"]["status"] == "inconclusive"
    assert by_id["s3_post"]["status"] == "failed"
    assert status["verdict"] == "ABORTED"

    # CLI --json 面与 journal 一致
    res = runner.invoke(dag_app, ["status", str(run_dir), "--json"])
    assert res.exit_code == 0, res.output
    envelope = json.loads(res.output)
    got = {n["node_id"]: n["status"] for n in envelope["nodes"]}
    assert got == {"s1_render": "done", "s2_judge": "inconclusive",
                   "s3_post": "failed"}


# ─── 判据④：--json 双路径信封（成功+失败路径同构）────────────────────────────

def test_json_dual_path_envelopes(tmp_path) -> None:
    # 失败路径：计划不存在 → ok=False 信封 + rc≠0（仍是 JSON）
    res = runner.invoke(
        dag_app, ["run", str(tmp_path / "__not_exist__.json"),
                  "--run-dir", str(tmp_path / "run4"), "--json"])
    assert res.exit_code != 0
    envelope = json.loads(res.output)
    assert envelope["ok"] is False and envelope["errors"]

    res2 = runner.invoke(
        dag_app, ["status", str(tmp_path / "__no_such_run__"), "--json"])
    assert res2.exit_code != 0
    envelope2 = json.loads(res2.output)
    assert envelope2["ok"] is False and envelope2["errors"]

    # 成功路径：无产物面单节点（纯 judge，命令零产物）→ ok=True 信封
    plan = {"nodes": [{"node_id": "j1", "kind": "judge", "depends_on": [],
                       "inputs": {"files": [], "params": {}},
                       "outputs": [],
                       "cmd": f'"{_pyexe()}" -c "print(\'noop\')"',
                       "budget": {}}]}
    plan_path = tmp_path / "plan5.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    res3 = runner.invoke(
        dag_app, ["run", str(plan_path), "--run-dir", str(tmp_path / "run5"),
                  "--solve-lock", str(tmp_path / "solve5.lock"), "--json"])
    assert res3.exit_code == 0, res3.output
    envelope3 = json.loads(res3.output)
    assert envelope3["ok"] is True
    assert envelope3["verdict"] == "COMPLETE"
    assert envelope3["statuses"] == {"j1": "done"}


# ─── 判据⑤：零数值面（铁律 7 AST 探针）──────────────────────────────────────

def test_zero_numeric_face() -> None:
    import rfauto.cli.domains.dag as dag_mod

    src = Path(dag_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    floats = [n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, float)]
    assert set(floats) <= _ALLOWED_FLOATS, (
        f"CLI 执行器面出现意外浮点字面量: {floats}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in _BANNED_IMPORT_TOKENS, alias.name
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in _BANNED_IMPORT_TOKENS, node.module
    # 物理量词面零命中（不产生任何物理数字）
    assert not re.search(r"\d+(?:\.\d+)?\s*(ghz|mm|db|ohm)\b", src, re.I)


# ─── 注册可达（计数链自证：dag 域两叶真在 CLI 树上）──────────────────────────

def test_dag_leaves_registered_in_cli_tree() -> None:
    from typer.main import get_command

    from rfauto.cli.main import app as main_app

    click_app = get_command(main_app)
    commands = getattr(click_app, "commands", {}) or {}
    assert "dag" in commands, "顶层缺 dag 域"
    leaves = set(getattr(commands["dag"], "commands", {}) or {})
    assert {"run", "status"} <= leaves, f"dag 域叶不齐: {leaves}"
