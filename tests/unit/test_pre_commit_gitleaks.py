"""r4 P-2 秘密卫生门单测（scripts/pre_commit_gitleaks.py + install_git_hooks.py）。

确定性、无网络：不依赖 gitleaks 在装——staged 清单解析用 mock、缺失/strict
分支走纯函数、launcher 幂等与已有钩子不覆盖用 tmp dir 模拟。真实 gitleaks
在装时的端到端 smoke 用 skipif 门（tools/gitleaks/gitleaks.exe 存在才跑）。

注意：本文件自身未来也要过 gitleaks 门——测试用假 secret 一律分片拼装，
源码里不得出现完整 token 字面量。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import install_git_hooks as igh
import pre_commit_gitleaks as pcg

REPO_ROOT = Path(__file__).resolve().parents[2]
GITLEAKS_EXE = REPO_ROOT / "tools" / "gitleaks" / "gitleaks.exe"

# 分片拼装的假 Slack bot token（缺省规则 slack-bot-token 实测命中）；
# 完整字面量不落本文件，避免未来 commit 时被本门自己拦截
_FAKE_TOKEN = "-".join(
    ["xoxb", "1234" * 3, "1234567890" + "123", "abcdefghij" * 2 + "klmn"]
)


@pytest.fixture(autouse=True)
def _clean_gitleaks_env(monkeypatch):
    """清空本门的整个环境变量集合（同名前缀全清， 确定性铁律）。"""
    for name in (pcg.ENV_STRICT, pcg.ENV_BIN):
        monkeypatch.delenv(name, raising=False)


class TestListStagedFiles:
    def test_nul_separated_parse(self, monkeypatch, tmp_path):
        # #235 口径：-z 原始字节按 NUL 切，尾部空段过滤，禁止 trim+slice
        raw = b"src/a.py\x00dir with space/b.txt\x00\x00tail.py\x00"
        monkeypatch.setattr(pcg, "run_git", lambda root, *a: raw)
        assert pcg.list_staged_files(tmp_path) == [
            "src/a.py",
            "dir with space/b.txt",
            "tail.py",
        ]

    def test_empty_staged(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pcg, "run_git", lambda root, *a: b"")
        assert pcg.list_staged_files(tmp_path) == []

    def test_non_utf8_name_no_crash(self, monkeypatch, tmp_path):
        # git -z 输出原始字节；surrogateescape 解码保证不抛异常
        monkeypatch.setattr(pcg, "run_git", lambda root, *a: b"caf\xe9.txt\x00")
        files = pcg.list_staged_files(tmp_path)
        assert len(files) == 1 and files[0].endswith(".txt")

    def test_real_repo_parse_matches_git(self):
        # 与真实 git 输出互证：-z 解析 == 普通模式逐行（当前仓任何 staged 态）
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        expected = [ln for ln in out.splitlines() if ln.strip()]
        assert pcg.list_staged_files(REPO_ROOT) == expected


class TestMissingBinary:
    def test_missing_fails_open_with_skip_message(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["x.py"])
        # best-effort #105：无工具环境警告放行
        rc = pcg.run_gate(tmp_path, None, strict=False)
        assert rc == pcg.EXIT_CLEAN
        out = capsys.readouterr().out
        assert "SKIPPED: gitleaks not installed" in out

    def test_missing_strict_fails_closed(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["x.py"])
        rc = pcg.run_gate(tmp_path, None, strict=True)
        assert rc == pcg.EXIT_LEAKS
        out = capsys.readouterr().out
        assert "FAIL" in out and pcg.ENV_STRICT in out

    def test_no_staged_files_short_circuits(self, monkeypatch, tmp_path, capsys):
        # 无 staged 文件：连 gitleaks 查找都不触发（找不到也不影响放行）
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: [])
        rc = pcg.run_gate(tmp_path, None, strict=True)
        assert rc == pcg.EXIT_CLEAN
        assert "no staged files" in capsys.readouterr().out


class TestStrictEnv:
    def test_env_1_is_strict(self, monkeypatch):
        monkeypatch.setenv(pcg.ENV_STRICT, "1")
        assert pcg.strict_from_env() is True

    def test_env_other_values_not_strict(self, monkeypatch):
        for val in ("0", "", "true", "yes"):
            monkeypatch.setenv(pcg.ENV_STRICT, val)
            assert pcg.strict_from_env() is False, val

    def test_env_unset_not_strict(self):
        assert pcg.strict_from_env() is False

    def test_main_uses_env_strict_on_missing_bin(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv(pcg.ENV_STRICT, "1")
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["x.py"])
        monkeypatch.setattr(pcg.shutil, "which", lambda name: None)
        rc = pcg.main(["--repo", str(tmp_path), "--bin", str(tmp_path / "nope.exe")])
        assert rc == pcg.EXIT_LEAKS
        assert "SKIPPED" not in capsys.readouterr().out


class TestFindGitleaks:
    def test_explicit_override_wins(self, tmp_path):
        exe = tmp_path / "custom-gitleaks.exe"
        exe.write_bytes(b"")
        assert pcg.find_gitleaks(tmp_path, override=str(exe)) == exe

    def test_repo_tools_location(self, tmp_path):
        exe = tmp_path.joinpath(*pcg.GITLEAKS_REPO_REL)
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        assert pcg.find_gitleaks(tmp_path) == exe

    def test_missing_everywhere_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pcg.shutil, "which", lambda name: None)
        assert pcg.find_gitleaks(tmp_path) is None


class TestRunGateExitCodes:
    def test_clean_rc0(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["a.py"])

        def fake_run(cmd, **kwargs):
            assert cmd[1:3] == list(pcg.SCAN_SUBCOMMAND)
            assert "--redact" in cmd
            return SimpleNamespace(returncode=0, stdout="no leaks", stderr="")

        monkeypatch.setattr(pcg.subprocess, "run", fake_run)
        rc = pcg.run_gate(tmp_path, Path("gl.exe"), strict=False)
        assert rc == pcg.EXIT_CLEAN
        assert "clean" in capsys.readouterr().out

    def test_leaks_rc1_prints_redacted_findings(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["a.py", "b.py"])

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout="Finding: REDACTED\nRuleID: slack-bot-token\n",
                stderr="leaks found: 1",
            )

        monkeypatch.setattr(pcg.subprocess, "run", fake_run)
        rc = pcg.run_gate(tmp_path, Path("gl.exe"), strict=False)
        assert rc == pcg.EXIT_LEAKS
        out = capsys.readouterr().out
        assert "LEAKS DETECTED" in out
        assert "slack-bot-token" in out  # 违规元数据回显
        assert "a.py" in out  # staged 清单回显

    def test_tool_error_fails_open_non_strict(self, monkeypatch, tmp_path, capsys):
        # rc>=2 = gitleaks 自身故障：非 strict 按 #105 fail-open
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["a.py"])
        monkeypatch.setattr(
            pcg.subprocess,
            "run",
            lambda cmd, **kw: SimpleNamespace(returncode=2, stdout="", stderr="boom"),
        )
        rc = pcg.run_gate(tmp_path, Path("gl.exe"), strict=False)
        assert rc == pcg.EXIT_CLEAN
        assert "WARN" in capsys.readouterr().out

    def test_tool_error_fails_closed_strict(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pcg, "list_staged_files", lambda root: ["a.py"])
        monkeypatch.setattr(
            pcg.subprocess,
            "run",
            lambda cmd, **kw: SimpleNamespace(returncode=128, stdout="", stderr="boom"),
        )
        assert pcg.run_gate(tmp_path, Path("gl.exe"), strict=True) == pcg.EXIT_LEAKS


class TestInstallHook:
    def _repo(self, tmp_path: Path) -> Path:
        (tmp_path / ".git" / "hooks").mkdir(parents=True)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "pre_commit_gitleaks.py").write_text("# gate\n")
        python_exe = tmp_path / "venv" / "python.exe"
        python_exe.parent.mkdir()
        python_exe.write_bytes(b"")
        return tmp_path

    def test_build_launcher_deterministic(self, tmp_path):
        repo = self._repo(tmp_path)
        py = repo / "venv" / "python.exe"
        a = igh.build_launcher(py, repo)
        b = igh.build_launcher(py, repo)
        assert a == b
        assert a.startswith("#!/bin/sh")
        assert igh.MARKER in a
        assert py.resolve().as_posix() in a  # python 绝对路径（posix 斜杠）
        assert "git rev-parse --show-toplevel" in a  # 运行时 repo 根探测
        assert "scripts/pre_commit_gitleaks.py" in a

    def test_install_then_rerun_is_noop(self, tmp_path):
        repo = self._repo(tmp_path)
        py = repo / "venv" / "python.exe"
        assert igh.install_hook(repo, py) == "installed"
        first = (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
        assert igh.install_hook(repo, py) == "already"
        second = (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
        assert first == second

    def test_foreign_hook_not_overwritten(self, tmp_path):
        repo = self._repo(tmp_path)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho my own hook\n", encoding="utf-8")
        status = igh.install_hook(repo, repo / "venv" / "python.exe")
        assert status == "skipped_existing"
        assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho my own hook\n"

    def test_managed_hook_drift_converges(self, tmp_path):
        repo = self._repo(tmp_path)
        py = repo / "venv" / "python.exe"
        assert igh.install_hook(repo, py) == "installed"
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text(
            f"# {igh.MARKER}\nstale content\n", encoding="utf-8"
        )
        assert igh.install_hook(repo, py) == "updated"
        assert hook.read_text(encoding="utf-8") == igh.build_launcher(py, repo)

    def test_missing_python_raises(self, tmp_path):
        repo = self._repo(tmp_path)
        with pytest.raises(FileNotFoundError):
            igh.install_hook(repo, tmp_path / "nope" / "python.exe")


class TestCliSmoke:
    def test_help_smoke(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "pre_commit_gitleaks.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "gitleaks" in proc.stdout

    def test_install_cli_smoke_on_tmp_repo(self, tmp_path):
        # 端到端 CLI：tmp repo 安装 → 幂等重跑 → 外部钩子跳过路径（exit 0）
        repo = tmp_path / "repo"
        (repo / ".git" / "hooks").mkdir(parents=True)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "pre_commit_gitleaks.py").write_text("# gate\n")
        py = tmp_path / "py.exe"
        py.write_bytes(b"")
        base = [sys.executable, str(SCRIPTS / "install_git_hooks.py")]
        runs = [
            (["--repo", str(repo), "--python", str(py)], "installed ->"),
            (["--repo", str(repo), "--python", str(py)], "already installed"),
            # --force 对自家已装钩子内容一致 → 仍 no-op
            (["--repo", str(repo), "--python", str(py), "--force"], "already installed"),
        ]
        for args, expect in runs:
            proc = subprocess.run(
                base + args, capture_output=True, text=True, check=False
            )
            assert proc.returncode == 0, proc.stderr
            assert expect in proc.stdout
        # --force 覆盖外部钩子：终态内容收敛为 canonical launcher
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
        proc = subprocess.run(
            [*base, "--repo", str(repo), "--python", str(py), "--force"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert hook.read_text(encoding="utf-8") == igh.build_launcher(py, repo)


@pytest.mark.skipif(
    not GITLEAKS_EXE.is_file(),
    reason="gitleaks not installed (tools/gitleaks/gitleaks.exe absent)",
)
class TestEndToEndWithRealGitleaks:
    def _git(self, repo: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, check=True
        )

    def _init_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "e2e"
        repo.mkdir()
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.com")
        self._git(repo, "config", "user.name", "t")
        (repo / "clean.txt").write_text("hello world\n", encoding="utf-8")
        self._git(repo, "add", "clean.txt")
        self._git(repo, "commit", "-qm", "init")
        return repo

    def test_clean_staged_passes(self, tmp_path):
        repo = self._init_repo(tmp_path)
        (repo / "more.txt").write_text("nothing here\n", encoding="utf-8")
        self._git(repo, "add", "more.txt")
        rc = pcg.run_gate(repo, GITLEAKS_EXE, strict=False)
        assert rc == pcg.EXIT_CLEAN

    def test_staged_secret_blocked(self, tmp_path):
        repo = self._init_repo(tmp_path)
        (repo / "leak.txt").write_text(
            f'slack = "{_FAKE_TOKEN}"\n', encoding="utf-8"
        )
        self._git(repo, "add", "leak.txt")
        rc = pcg.run_gate(repo, GITLEAKS_EXE, strict=False)
        assert rc == pcg.EXIT_LEAKS

    def test_unstaged_secret_ignored(self, tmp_path):
        # 只扫 staged：泄漏留在工作区未 add 时不拦
        repo = self._init_repo(tmp_path)
        (repo / "leak.txt").write_text(
            f'slack = "{_FAKE_TOKEN}"\n', encoding="utf-8"
        )
        rc = pcg.run_gate(repo, GITLEAKS_EXE, strict=False)
        assert rc == pcg.EXIT_CLEAN

    def test_real_repo_nothing_staged_short_circuit(self):
        # 本仓无 staged 内容时门短路放行（其余轨在飞 staged 面不可预测→跳过）
        staged = pcg.list_staged_files(REPO_ROOT)
        if staged:
            pytest.skip("repo has staged content mid-flight")
        rc = pcg.run_gate(REPO_ROOT, GITLEAKS_EXE, strict=False)
        assert rc == pcg.EXIT_CLEAN


class TestStdlibOnlyContract:
    def test_no_pip_dependency(self):
        # 本门纯 stdlib（venv 零变更铁律）：两个脚本源码里禁止出现 pip 面
        source = (SCRIPTS / "pre_commit_gitleaks.py").read_text(encoding="utf-8")
        assert "pip" not in source
        installer = (SCRIPTS / "install_git_hooks.py").read_text(encoding="utf-8")
        assert "pip" not in installer
