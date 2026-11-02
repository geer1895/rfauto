"""DP-17 O2 单测——公开 API 快照（check_public_api + tests/gold 金样例）。

判据（runs/df6_dp17/criteria.md §O2）：
- 生成器幂等：同一棵树连跑两次逐字节同 JSON；
- 真仓金样例 --check 通过（翻公开名=显式评审动作，测试即门）；
- 翻转公开名快照测试红：tmp 迷你树改 __all__（增/删/改名）→ --check
  非 0 退出（不污染真仓快照）；
- 无 __all__ 文件记私有（快照不含），门面口径取顶层公开 def/class。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "check_public_api.py"
_GOLD = _REPO / "tests" / "gold" / "public_api.json"
_PYTHON = Path(sys.executable)


def _run(*args: str, root: Path | None = None,
         facades: str | None = None) -> subprocess.CompletedProcess:
    cmd = [str(_PYTHON), str(_SCRIPT)]
    if root is not None:
        cmd += ["--root", str(root)]
    if facades is not None:
        cmd += ["--facades", facades]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8")


def _mini_tree(tmp_path: Path, all_names: list[str] | None) -> Path:
    """迷你包树：一个带/不带 __all__ 的模块 + 一个门面模块。"""
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "mod_a.py").write_text(
        "def pub_one():\n    return 1\n"
        + (f"__all__ = {all_names!r}\n" if all_names is not None else ""),
        encoding="utf-8")
    (root / "facade.py").write_text(
        "def top_public():\n    return 2\n\n"
        "def _hidden():\n    return 3\n\n"
        "class TopClass:\n    pass\n",
        encoding="utf-8")
    return root


class TestGeneratorIdempotency:
    def test_real_tree_generate_twice_identical(self, tmp_path):
        out1, out2 = tmp_path / "s1.json", tmp_path / "s2.json"
        r1 = _run("--generate", str(out1))
        assert r1.returncode == 0, r1.stderr
        r2 = _run("--generate", str(out2))
        assert r2.returncode == 0, r2.stderr
        assert out1.read_bytes() == out2.read_bytes()  # 逐字节幂等

    def test_real_tree_check_gold_passes(self):
        r = _run("--check", str(_GOLD))
        assert r.returncode == 0, \
            f"真仓公开面漂移（翻公开名须显式评审+重钉）：{r.stdout}"

    def test_gold_snapshot_deterministic_shape(self):
        data = json.loads(_GOLD.read_text(encoding="utf-8"))
        assert data["schema"] == "rfauto-public-api-snapshot-v1"
        assert data["files"], "真仓应有已登记 __all__ 的模块"
        assert set(data["core_facades"]) == {
            "adapters/em_solver_base", "models/registry",
            "service/db_service", "service/health_service",
            "service/league_service", "service/explain_run",
            "core/solve_health"}


class TestFlipDetection:
    def test_flip_public_name_turns_check_red(self, tmp_path):
        root = _mini_tree(tmp_path, all_names=["pub_one"])
        gold = tmp_path / "gold.json"
        assert _run("--generate", str(gold), root=root).returncode == 0
        assert _run("--check", str(gold), root=root).returncode == 0

        # 翻转公开名（改名=移除+新增）
        (root / "mod_a.py").write_text(
            "def pub_renamed():\n    return 1\n"
            "__all__ = ['pub_renamed']\n", encoding="utf-8")
        r = _run("--check", str(gold), root=root)
        assert r.returncode == 1
        assert "pub_one" in r.stdout and "pub_renamed" in r.stdout

    def test_add_and_remove_all_module_detected(self, tmp_path):
        root = _mini_tree(tmp_path, all_names=["pub_one"])
        gold = tmp_path / "gold.json"
        assert _run("--generate", str(gold), root=root).returncode == 0

        # 新增 __all__ 模块
        (root / "mod_b.py").write_text("__all__ = ['x']\n", encoding="utf-8")
        r = _run("--check", str(gold), root=root)
        assert r.returncode == 1 and "mod_b.py" in r.stdout

        # 移除既有 __all__
        (root / "mod_b.py").unlink()
        (root / "mod_a.py").write_text(
            "def pub_one():\n    return 1\n", encoding="utf-8")
        r = _run("--check", str(gold), root=root)
        assert r.returncode == 1 and "移除 __all__" in r.stdout

    def test_facade_top_level_change_detected(self, tmp_path):
        root = _mini_tree(tmp_path, all_names=None)
        gold = tmp_path / "gold.json"
        assert _run("--generate", str(gold), root=root,
                    facades="facade").returncode == 0
        data = json.loads(gold.read_text(encoding="utf-8"))
        assert data["core_facades"]["facade"] == ["TopClass", "top_public"]
        assert _run("--check", str(gold), root=root,
                    facades="facade").returncode == 0

        # 门面加一个公开函数 → 检测
        (root / "facade.py").write_text(
            "def top_public():\n    return 2\n\n"
            "def another():\n    return 4\n", encoding="utf-8")
        r = _run("--check", str(gold), root=root, facades="facade")
        assert r.returncode == 1 and "another" in r.stdout

    def test_no_all_recorded_private(self, tmp_path):
        root = _mini_tree(tmp_path, all_names=None)
        gold = tmp_path / "gold.json"
        assert _run("--generate", str(gold), root=root,
                    facades="facade").returncode == 0
        data = json.loads(gold.read_text(encoding="utf-8"))
        assert "mod_a.py" not in data["files"]  # 无 __all__ 记私有
        # 门面口径仍取顶层公开名（下划线私有不在）
        assert data["core_facades"]["facade"] == ["TopClass", "top_public"]
