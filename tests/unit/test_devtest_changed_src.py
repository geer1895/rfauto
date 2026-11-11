"""devtest --changed-src 旗标钉（Q-X17，aurora_q Q-X8 遗留修复）。

背景：Q-X8 实测 `devtest --changed-src` 时该旗标名未在 argparse 注册，被
parse_known_args 漏进 pytest extra 原样转发，pytest 当未知选项报 usage 错
（exit 4）——本档钉住补注册后的契约：

①旗标注册：--changed-src 被 argparse 消费，不漏进 pytest extra（exit 4
 根因回归钉）；
②排除面：src+tests 混合变更下选择面只含 src 映射产物，tests 面变更被
 排除且逐文件如实报告；
③dry-run 组合兼容：--changed-src --dry-run → exit 0、零 pytest 发射；
④exit 码纪律：无 src 变更 → 0（无事可做）；两旗标都缺 → 用法错 exit 2
 （既有口径原样）；
⑤A/B 无旗标零变化：--changed 单旗标路径不注入排除面报告（改造前输出形态
 保持），未知旗标落 extra 的既有透传语义不被本席收紧。

全部协作面（_git/_ensure_map/_get_selection/_run_pytest）monkeypatch 注入：
零真 git、零 24MB 映射解析、零 pytest 子进程、零 runs/ 湖写（脚本模块经
importlib 按路径加载，src 层零依赖）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "devtest.py"

#: 混合变更面（src 一件 + tests 两件 + 非py 一件）：src 过滤与 tests 过滤各取所需。
_DIFF_FILES = [
    "src/rfauto/service/em_bench_service.py",
    "tests/unit/test_anim_cli.py",
    "tests/unit/test_format_overview_b3.py",
    "docs/tutorials/rf-animation.md",
    "",  # git diff -z 尾部 NUL 形态
]
_SELECTED_TESTS = ["tests/unit/test_em_bench.py", "tests/unit/test_em_bench_proposals.py"]


@pytest.fixture()
def devtest():
    """按路径加载 scripts/devtest.py（每测试独立实例，零 sys.modules 污染）。"""
    spec = importlib.util.spec_from_file_location("devtest_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch):
    """协作面全注入：记录 pytest 测试面与透传 extra，映射面返回固定选择。

    返回安装函数（装到传入的 devtest 模块实例上），记录 dict 供断言。"""
    calls: dict[str, object] = {"pytest_tests": None, "extra": None}

    def _install(mod) -> dict[str, object]:
        monkeypatch.setattr(mod, "_git", lambda args: "\0".join(_DIFF_FILES))
        monkeypatch.setattr(mod, "_ensure_map", lambda map_path, scope: "")
        monkeypatch.setattr(
            mod, "_get_selection",
            lambda map_path, scope, changed: (
                _SELECTED_TESTS, [], {"src/rfauto/service/em_bench_service.py": 2}),
        )

        def fake_run_pytest(tests, workers, extra, cache_dir, isolate_cache):
            calls["pytest_tests"] = list(tests)
            calls["extra"] = list(extra)
            return 0

        monkeypatch.setattr(mod, "_run_pytest", fake_run_pytest)
        return calls

    return _install


# ── ① 旗标注册（exit 4 根因回归钉） ──────────────────────────────────────────


def test_changed_src_flag_recognized_and_not_leaked_to_extra(devtest, harness, capsys):
    """--changed-src 走完整真跑路径：argparse 消费旗标，extra 不含它（Q-X8
    的 exit 4 形态=旗标漏进 extra 被原样转发给 pytest）。"""
    calls = harness(devtest)
    rc = devtest.main(["--changed-src"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "src-only" in out, "src-only 口径报告必须出现"
    assert calls["extra"] == [], "透传 extra 必须为空（旗标不得漏进 pytest）"
    assert calls["pytest_tests"] == _SELECTED_TESTS


def test_changed_src_with_only_tests_face_changes_exit_0(devtest, harness, capsys):
    """git diff 只有 tests/docs 面（src 零变更）→ exit 0 无事可做——旗标被
    argparse 正常消费的旁证（未注册形态会落 extra → 缺 --changed 报 exit 2）。"""
    harness(devtest)
    monkey_diff = ["tests/unit/test_anim_cli.py", "docs/x.md", ""]
    devtest._git = lambda args: "\0".join(monkey_diff)  # 档内一次性实例，直接注入
    rc = devtest.main(["--changed-src"])
    assert rc == 0
    assert "无事可做" in capsys.readouterr().out


# ── ② 排除面：tests 变更被排除且如实报告 ─────────────────────────────────────


def test_changed_src_excludes_tests_face_changes(devtest, harness, capsys):
    """src+tests 混合变更：选择面只含 src 映射产物；tests 面逐件列排除。"""
    harness(devtest)
    rc = devtest.main(["--changed-src", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "排除 tests 面自身变更 2 个" in out
    assert "[excluded] tests/unit/test_anim_cli.py" in out
    assert "[excluded] tests/unit/test_format_overview_b3.py" in out
    excluded_lines = [ln for ln in out.splitlines() if ln.startswith("  [excluded]")]
    assert all(ln.startswith("  [excluded] tests/") for ln in excluded_lines)
    assert "rf-animation.md" not in [ln.split(maxsplit=2)[-1] for ln in excluded_lines]
    assert "映射无受影响测试" not in out  # src 选择照常（未被排除面劫持）


def test_changed_tests_helper_filters_tests_py_only(devtest, monkeypatch):
    """_changed_tests 与 _changed_src 同 diff 视图、仅前缀过滤不同（同后缀）。"""
    monkeypatch.setattr(devtest, "_git", lambda args: "\0".join(_DIFF_FILES))
    got = devtest._changed_tests(staged=False, base=None)
    assert got == [
        "tests/unit/test_anim_cli.py",
        "tests/unit/test_format_overview_b3.py",
    ]
    src = devtest._changed_src(staged=False, base=None)
    assert src == ["src/rfauto/service/em_bench_service.py"]


# ── ③ dry-run 组合兼容 ───────────────────────────────────────────────────────


def test_changed_src_dry_run_zero_pytest_spawn(devtest, harness, capsys):
    """--changed-src --dry-run → exit 0、零 pytest 发射（dry-run 纪律）。"""
    calls = harness(devtest)
    rc = devtest.main(["--changed-src", "--dry-run"])
    assert rc == 0
    assert calls["pytest_tests"] is None, "dry-run 不得发射 pytest"
    out = capsys.readouterr().out
    assert "dry-run 到此为止" in out
    # 排除面报告在 dry-run 之下照常打印（选择面先于 dry-run 退出点）
    assert "src-only 口径" in out


# ── ④ exit 码纪律 ────────────────────────────────────────────────────────────


def test_missing_both_flags_usage_error_exit_2(devtest, capsys):
    """两旗标都缺 → 用法错 exit 2（既有口径；错误信息覆盖两旗标名）。"""
    with pytest.raises(SystemExit) as ei:
        devtest.main([])
    assert ei.value.code == 2
    assert "--changed-src" in capsys.readouterr().err


def test_no_src_change_exit_0_discipline(devtest, harness, capsys):
    """--changed-src 且 src 零变更 → exit 0（0=无事可做纪律照既有）。"""
    harness(devtest)
    devtest._git = lambda args: "\0".join(["", ""])  # 档内一次性实例，直接注入
    rc = devtest.main(["--changed-src"])
    assert rc == 0
    assert "无事可做" in capsys.readouterr().out


# ── ⑤ A/B：无旗标（--changed 单旗标）行为零变化 ─────────────────────────────


def test_changed_flag_alone_output_has_no_exclusion_report(devtest, harness, capsys):
    """A/B 钉：--changed 单旗标输出不含 src-only 排除面报告（改造前形态）。"""
    harness(devtest)
    rc = devtest.main(["--changed", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "src-only 口径" not in out
    assert "[excluded]" not in out
    assert "dry-run 到此为止" in out
    assert "变更 src 文件 1 个" in out


def test_unknown_flag_still_falls_to_extra_unchanged(devtest, harness):
    """既有透传语义不被本旗标改动波及：真未知名仍走 parse_known_args 落
    extra 原样转发（本席只补注册 --changed-src，不收紧透传通道——A/B 零变化）。"""
    calls = harness(devtest)
    rc = devtest.main(["--changed", "--not-a-real-flag"])
    assert rc == 0
    assert calls["extra"] == ["--not-a-real-flag"]


def test_usage_epilog_lists_exit_codes(devtest, capsys):
    """usage/exit 码纪律照既有：--help 尾注含 0/2 档口径原样。"""
    with pytest.raises(SystemExit) as ei:
        devtest.main(["--help"])
    assert ei.value.code == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "0=无事可做/全绿" in text and "2=用法错" in text
