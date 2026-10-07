"""scripts/census_status.py 收编版（H1-4）解析面离线回归钉（零 SSH 零真机）。

出处链：runs/ge8_server_batch/census_status.py（gitignored 原版，H1-4
登记：无版本控制/in_census 死变量/宽窄双轨"同源"靠约定）→ F6 修复席
收编 scripts/census_status.py（解析逻辑抽纯函数 parse_census_probe，
行为与原版逐行同源；runs/ 原版零改写留档）。

钉面（任务书规定三态 fixture）：
① BUSY 行（含 CMD= 截断）；② CLEAR（无 BUSY 行，含表头/census 段噪声）；
③ 大小写敏感回归签名（小写 busy: 不命中=原版宽匹配口径）。
另钉：首个 BUSY 行优先、REPO 仓根锚、文件在仓内版本控制面。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "census_status.py"

_SPEC = importlib.util.spec_from_file_location("census_status_test_target",
                                               _SCRIPT)
census = importlib.util.module_from_spec(_SPEC)
sys.modules["census_status_test_target"] = census
_SPEC.loader.exec_module(census)


# ─── 探针输出三态 ─────────────────────────────────────────────────────────

def test_busy_line_with_cmd_truncated():
    """BUSY 行：输出 BUSY:<cmd> 前段，CMD= 之后（PID/CPU 噪声）截断。"""
    text = ("current solver-process census (#261 mutex precheck)\n"
            "BUSY: python -u scripts/fd_oe_campaign.py CMD=python PID=4242 CPU=12.5\n")
    assert census.parse_census_probe(text) == (
        "BUSY: python -u scripts/fd_oe_campaign.py ")


def test_clear_when_no_busy_line():
    """CLEAR：表头行/census 段/小写 busy 噪声都不是 BUSY 行。"""
    text = ("current solver-process census (#261 mutex precheck)\n"
            "census section [6] wide-match\n"
            "mutex CLEAR\n"
            "(no solver processes)\n")
    assert census.parse_census_probe(text) == "CLEAR"


def test_busy_case_sensitive_lower_busy_not_matched():
    """大小写敏感回归签名（H1-4：宽匹配只认探针大写协议行 BUSY:）。"""
    assert census.parse_census_probe("busy: something CMD=x\n") == "CLEAR"


def test_first_busy_line_wins():
    text = ("BUSY: first.exe CMD=first PID=1\n"
            "BUSY: second.exe CMD=second PID=2\n")
    assert census.parse_census_probe(text) == "BUSY: first.exe "


def test_bare_busy_prefix():
    """恰为 "BUSY:" 的退化行 → "BUSY:"（原版 split 行为同源）。"""
    assert census.parse_census_probe("BUSY:\n") == "BUSY:"


def test_empty_and_multiline_noise_is_clear():
    assert census.parse_census_probe("") == "CLEAR"
    assert census.parse_census_probe("line1\nline2\nline3\n") == "CLEAR"


# ─── 收编面：REPO 仓根锚 + 文件在版本控制面 ───────────────────────────────

def test_repo_anchor_is_repo_root():
    """收编后层级（scripts/ 直下）：parents[1]=仓根（原版在 runs/ 子目录
    用 parents[2]，收编时已按新层级重算——H1-2 同族错位预防钉）。"""
    assert census.REPO == REPO
    assert (census.REPO / "src").is_dir()
    assert str(census.REPO / "src") in sys.path


def test_script_lives_in_versioned_scripts_tree():
    """收编兑现：解析单源落在 git 版本控制面（runs/ 原版 gitignored 无版本）。
    提交边界两态皆可：已入库（ls-files 命中）或本批待提交（porcelain 命中）。"""
    rel = _SCRIPT.relative_to(REPO).as_posix()
    tracked = subprocess.run(
        ["git", "ls-files", rel], cwd=str(REPO), capture_output=True,
        text=True, check=True).stdout.strip()
    if tracked == rel:
        return
    pending = subprocess.run(
        ["git", "status", "--porcelain", "--", rel], cwd=str(REPO),
        capture_output=True, text=True, check=True).stdout
    assert rel in pending, "census_status.py 必须已收编入仓（tracked 或待提交）"
