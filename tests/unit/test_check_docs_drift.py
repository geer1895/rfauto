"""check_docs_drift 驱动 + build_docs_pages --check 漂移语义测试
（架构批 A4-D，2026-10-11）。

钉四件事：
1. build_docs_pages.py --check 退出码语义（与 build_kernel_cards --check
   同语义）：基准缺文件/内容漂移=1；生成集之外多余文件=WARN 不判红；
   基准目录缺席=1；一致=0。
2. check_docs_drift.py 定性纯函数：rc=1 且含漂移标记=DRIFT；rc=1 无标记
   （进程崩溃 traceback）=INFRA；聚合 INFRA 优先于 DRIFT（基础设施掩盖
   漂移判定先修环境）；空清单=INFRA（静默空跑=假绿，禁止）。
3. 驱动端到端：真实仓树两再生面全绿（rc=0）——同时充当已提交 docs_site/
   kernel_cards 保鲜的日检面（与 test_docs_site/test_kernel_cards 同判据
   同源，经脚本 CLI 路径）。
4. --only 子集与未知面名的 argparse 语义（未知面名=usage 错误退出码 2）。

零硬编码计数（#247 同源纪律）：全部判定走 rc/标记/相对路径，无 EXPECTED=N。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    # py3.12 dataclasses 解析 string 注解需先注册 sys.modules（同
    # test_docs_site._load_module：build_docs_pages 含 @dataclass CliNode）
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


build_docs_pages = _load_module(
    "_cdd_build_docs_pages", _REPO / "scripts" / "build_docs_pages.py")
check_docs_drift = _load_module(
    "_cdd_check_docs_drift", _REPO / "scripts" / "check_docs_drift.py")


@pytest.fixture(scope="module")
def built_ref(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """真实生成器产物基准（module 级只建一次；各测试用副本变异）。"""
    ref = tmp_path_factory.mktemp("docs_ref")
    build_docs_pages.build_all(ref)
    return ref


def _copy_ref(built_ref: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "ref"
    shutil.copytree(built_ref, dst)
    return dst


def _first_rel(ref: Path) -> Path:
    return sorted(build_docs_pages._rel_files(ref))[0]


# ─── 1. build_docs_pages --check 退出码语义 ───────────────────────────────

def test_check_green_on_fresh_reference(built_ref: Path,
                                        capsys: pytest.CaptureFixture[str],
                                        ) -> None:
    rc = build_docs_pages.main(["--check", "--out", str(built_ref)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_check_green_on_committed_docs_site(
        capsys: pytest.CaptureFixture[str]) -> None:
    rc = build_docs_pages.main(["--check"])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_check_red_on_content_drift(built_ref: Path, tmp_path: Path,
                                    capsys: pytest.CaptureFixture[str],
                                    ) -> None:
    ref = _copy_ref(built_ref, tmp_path)
    target = ref / _first_rel(ref)
    target.write_bytes(target.read_bytes() + b"\n<!-- tampered -->\n")
    rc = build_docs_pages.main(["--check", "--out", str(ref)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "漂移" in out
    rel = _first_rel(ref)
    # 输出走 list repr 形态（Windows 分隔符在 repr 里是双反斜杠）
    assert repr(str(rel)) in out or rel.as_posix() in out


def test_check_red_on_missing_reference_file(built_ref: Path,
                                             tmp_path: Path) -> None:
    ref = _copy_ref(built_ref, tmp_path)
    (ref / _first_rel(ref)).unlink()
    assert build_docs_pages.main(["--check", "--out", str(ref)]) == 1


def test_check_red_on_missing_reference_dir(tmp_path: Path) -> None:
    assert build_docs_pages.main(
        ["--check", "--out", str(tmp_path / "no_such_dir")]) == 1


def test_check_extra_reference_file_warns_not_red(
        built_ref: Path, tmp_path: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    ref = _copy_ref(built_ref, tmp_path)
    (ref / "hand_written_extra.md").write_text("legacy asset\n",
                                               encoding="utf-8")
    rc = build_docs_pages.main(["--check", "--out", str(ref)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARN" in out
    assert "hand_written_extra.md" in out


def test_check_does_not_write_reference(built_ref: Path, tmp_path: Path,
                                        ) -> None:
    """--check 消费基准目录，绝不回写（判漂移的同时不能污染产物）。"""
    before = {p: p.stat().st_mtime_ns
              for p in built_ref.rglob("*") if p.is_file()}
    assert build_docs_pages.main(["--check", "--out", str(built_ref)]) == 0
    after = {p: p.stat().st_mtime_ns
             for p in built_ref.rglob("*") if p.is_file()}
    assert before == after


# ─── 2. 定性/聚合纯函数 ───────────────────────────────────────────────────

def test_classify_rc_semantics() -> None:
    assert check_docs_drift.classify(0, "[docs_site] OK：...") == ("PASS", 0)
    # rc=1 且含漂移标记=漂移红
    assert check_docs_drift.classify(
        1, "[docs_site] 漂移：1 个文件与基准不一致") == ("DRIFT", 1)
    # rc=1 无漂移标记=进程崩溃 traceback，归基础设施
    assert check_docs_drift.classify(
        1, "Traceback (most recent call last): ...") == ("INFRA", 2)
    # rc>=2（argparse usage 错误等）与负 rc（超时/缺席哨兵）=基础设施
    assert check_docs_drift.classify(2, "usage: ...") == ("INFRA", 2)
    assert check_docs_drift.classify(-1, "超时（>600s）") == ("INFRA", 2)


def test_aggregate_infra_masks_drift() -> None:
    assert check_docs_drift.aggregate([]) == 2  # 空清单=INFRA 非假绿
    assert check_docs_drift.aggregate(
        [("PASS", 0), ("PASS", 0)]) == 0
    assert check_docs_drift.aggregate(
        [("PASS", 0), ("DRIFT", 1)]) == 1
    assert check_docs_drift.aggregate(
        [("DRIFT", 1), ("INFRA", 2)]) == 2  # INFRA 优先（掩盖判定先修环境）


# ─── 3/4. 驱动端到端（真实仓树）与 CLI 语义 ──────────────────────────────

def test_driver_end_to_end_green_on_repo() -> None:
    r = subprocess.run(
        [sys.executable, "scripts/check_docs_drift.py"],
        cwd=str(_REPO), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert "[PASS] docs_site" in r.stdout
    assert "[PASS] kernel_cards" in r.stdout
    assert "GREEN" in r.stdout


def test_driver_only_subset_runs_single_face() -> None:
    r = subprocess.run(
        [sys.executable, "scripts/check_docs_drift.py", "--only",
         "docs_site"],
        cwd=str(_REPO), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert "[PASS] docs_site" in r.stdout
    assert "kernel_cards" not in r.stdout


def test_driver_unknown_face_name_is_usage_error() -> None:
    r = subprocess.run(
        [sys.executable, "scripts/check_docs_drift.py", "--only", "bogus"],
        cwd=str(_REPO), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2  # argparse usage 错误退出码
    assert "bogus" in (r.stderr + r.stdout)
