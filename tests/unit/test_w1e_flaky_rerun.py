"""W1-E Z-6 定向门——known_flaky marker 消费（pytest-rerunfailures 重跑行为）。

判据（runs/w1_phase1/criteria.md §W1-E）：
- 标记用例重跑行为：RFAUTO_FLAKY_RERUN=1 + known_flaky → 首红+重跑绿，
  整门 rc=0（ENV_FLAKY 分级：不计回归），实测重跑真发生（attempts=2）；
- **物理红永不隔离**（诚实分级铁律）：缺省门（无 env）带 marker → 单次
  执行即 FAIL；env 开但未打 marker → 同样单次 FAIL。两条路径都不得给
  物理红第二次机会；
- 手段注记：重跑状态属 pytest 会话级，必须子进程真跑——探针文件落
  tmp_path，内部 conftest 以 importlib 装载**真实** tests/conftest.py 的
  pytest_configure/pytest_collection_modifyitems 再 re-export（钩子代码
  路径与真门同一份，非复制逻辑）；探针不落 tests/ 树（并发席全量门
  零碰撞），内层会话不继承仓 pyproject 配置（rootdir=tmp，干净缺省）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_CONFTEST = _REPO_ROOT / "tests" / "conftest.py"

_PROBE_HEADER = textwrap.dedent("""
    import pytest

    _N = {"attempt": 0}
""")

_MARKED_TEST = textwrap.dedent('''

    @pytest.mark.known_flaky(reason="w1e probe：首红+重跑绿（设计内）")
    def test_w1e_flaky_probe_marked():
        _N["attempt"] += 1
        with open(_N["sink"], "a", encoding="utf-8") as fh:
            fh.write("marked\\n")
        assert _N["attempt"] > 1, "首红（探针设计内）"
''')

_UNMARKED_TEST = textwrap.dedent('''

    def test_w1e_flaky_probe_unmarked():
        _N["attempt"] += 1
        with open(_N["sink"], "a", encoding="utf-8") as fh:
            fh.write("unmarked\\n")
        assert False, "物理红（探针设计内，永不隔离）"
''')

_CONFTEST_SHIM = textwrap.dedent("""
    # Z-6 测试垫片：装载真实仓 conftest 的两个钩子并 re-export（非复制逻辑）
    import importlib.util

    _spec = importlib.util.spec_from_file_location(
        "_w1e_repo_conftest", {conftest!r})
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    pytest_configure = _mod.pytest_configure
    pytest_collection_modifyitems = _mod.pytest_collection_modifyitems
""")


def _make_probe(tmp_path: Path, kind: str) -> tuple[Path, Path]:
    """kind="marked" 只含 known_flaky 用例；"unmarked" 只含未标记用例。"""
    probe = tmp_path / "w1e_flaky_probe.py"
    sink = tmp_path / "attempts.txt"
    body = _PROBE_HEADER + (
        _MARKED_TEST if kind == "marked" else _UNMARKED_TEST)
    body = body.replace('_N["sink"]', repr(str(sink)))
    probe.write_text(body, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        _CONFTEST_SHIM.format(conftest=str(_REPO_CONFTEST)),
        encoding="utf-8")
    return probe, sink


def _run_pytest(probe: Path, *, gate_on: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("RFAUTO_FLAKY_RERUN", None)
    # 注意：不禁用插件 autoload——pytest-rerunfailures 经 entry point 注册，
    # 内层会话必须真实加载它（与真门同一插件激活形态）。
    if gate_on:
        env["RFAUTO_FLAKY_RERUN"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-q",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=120,
        cwd=str(probe.parent.parent), env=env)


def _attempts(sink: Path, label: str) -> list[str]:
    lines = sink.read_text(encoding="utf-8").splitlines()
    marked = [x for x in lines if x == "marked"]
    unmarked = [x for x in lines if x == "unmarked"]
    assert marked or unmarked, f"{label}: 探针一次都没执行到（环境坏）"
    return [f"marked={len(marked)}", f"unmarked={len(unmarked)}"]


class TestKnownFlakyRerunBehavior:
    def test_marked_first_red_rerun_green_not_a_regression(self, tmp_path):
        """ENV_FLAKY 分级主钉：首红+重跑绿 → rc=0（不计回归），attempts=2。"""
        probe, sink = _make_probe(tmp_path, "marked")
        proc = _run_pytest(probe, gate_on=True)
        assert proc.returncode == 0, (
            f"重跑绿仍判红=隔离失效:\n{proc.stdout}\n{proc.stderr}")
        assert sink.read_text(encoding="utf-8").splitlines().count(
            "marked") == 2, _attempts(sink, "gate_on+marked")

    def test_default_gate_marked_red_never_isolated(self, tmp_path):
        """缺省门（无 RFAUTO_FLAKY_RERUN）：带 marker 也单次 FAIL（物理红）。"""
        probe, sink = _make_probe(tmp_path, "marked")
        proc = _run_pytest(probe, gate_on=False)
        assert proc.returncode != 0
        assert sink.read_text(encoding="utf-8").splitlines().count(
            "marked") == 1, _attempts(sink, "gate_off+marked")

    def test_gate_on_unmarked_red_never_isolated(self, tmp_path):
        """env 开但未打 marker：物理红照样单次 FAIL（铁律第 2 条主钉）。"""
        probe, sink = _make_probe(tmp_path, "unmarked")
        proc = _run_pytest(probe, gate_on=True)
        assert proc.returncode != 0
        assert sink.read_text(encoding="utf-8").splitlines().count(
            "unmarked") == 1, _attempts(sink, "gate_on+unmarked")

    def test_marker_registered_without_strict_warning(self, tmp_path):
        """pytest_configure 仍注册 known_flaky（垫片内层会话无 unknown-mark 警告）。"""
        probe, _sink = _make_probe(tmp_path, "marked")
        proc = _run_pytest(probe, gate_on=True)
        assert "PytestUnknownMarkWarning" not in (proc.stdout + proc.stderr)

    def test_pyproject_dev_dependency_registered(self):
        """pyproject dev 组登记 pytest-rerunfailures（席位只动这一处）。"""
        text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "pytest-rerunfailures==16.7" in text

    def test_plugin_installed_in_venv(self):
        import importlib.util
        assert importlib.util.find_spec("pytest_rerunfailures") is not None, (
            "pytest-rerunfailures 未装进 .venv（pip show 核对）")
