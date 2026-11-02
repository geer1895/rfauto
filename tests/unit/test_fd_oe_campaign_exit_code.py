"""fd_oe_campaign 退出码聚合（H1-5 修复面）+ REPO 绝对锚（H1-7/#295 族）
离线回归钉（零引擎、零网络、零真机）。

出处链：oe_chain.log 2026-10-03 K-7 全座 SKIP 被"rc=0=链完毕"吞掉
（修复前 main() 恒 return 0，oe_chain_waiter 家族以 rc 串发）→ H1 席
审查 H1-5/H1-7 → F6 修复席（2026-10-04）。退出码表见
scripts/fd_oe_campaign.py 模块 docstring；总表见
runs/review_ge8e/f6_scripts_fix/REPORT.md。

钉面：
① campaign_exit_code 状态优先级三态+边界（FAIL>Skip>非PASS>全PASS>空）；
② campaign_exit_code_from_summary 伪造座位结果文件驱动（消费面入口，
   缺/损坏/非 dict=发射面异常 rc1，不猜不凑 #122）；
③ format_seat_line 批尾日志行规定格式（seats=N pass=N skip=N fail=N rc=X）；
④ argparse 用法错=64（自定义 error，避开 rc2=座位 FAIL 双义，H1-6 同族）；
⑤ 模块从 runs/ 子目录 cwd spec 装载不炸且 sys.path 注入为仓根绝对锚。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "fd_oe_campaign.py"

_MODULE_NAME = "fd_oe_campaign_exit_code_target"


def _load(cwd: Path | None = None):
    """spec 装载脚本模块（cwd 可注入=H1-7 回归钉面：非仓根 cwd 不炸）。"""
    import os

    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    old_cwd = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        spec.loader.exec_module(mod)
    finally:
        os.chdir(old_cwd)
    return mod


mod = _load()


# ─── ① campaign_exit_code 状态优先级 ─────────────────────────────────────

def test_exit_code_all_pass_is_zero():
    assert mod.campaign_exit_code(["PASS", "PASS"]) == mod.EXIT_OK == 0


def test_exit_code_any_fail_is_two_even_with_skip():
    """FAIL 优先于 SKIP（失败比跳过更需要人介入，预声明优先级）。"""
    assert mod.campaign_exit_code(["PASS", "FAIL"]) == 2
    assert mod.campaign_exit_code(["SKIP", "FAIL", "PASS"]) == 2


def test_exit_code_any_skip_is_three_when_no_fail():
    assert mod.campaign_exit_code(["PASS", "SKIP"]) == 3
    assert mod.campaign_exit_code(["SKIP", "PARTIAL"]) == 3


def test_exit_code_partial_or_unknown_without_fail_skip_is_four():
    assert mod.campaign_exit_code(["PASS", "PARTIAL"]) == 4
    assert mod.campaign_exit_code(["PARTIAL"]) == 4
    assert mod.campaign_exit_code(["PASS", "weird"]) == 4


def test_exit_code_empty_is_launch_error():
    assert mod.campaign_exit_code([]) == mod.EXIT_LAUNCH_ERROR == 1


def test_exit_code_k7_skip_scenario_is_not_zero():
    """ oe_chain.log K-7 回归签名：全座 SKIP 不得再记成链成功（rc!=0）。"""
    assert mod.campaign_exit_code(["SKIP"]) != 0


# ─── ② campaign_exit_code_from_summary（伪造座位结果文件驱动）────────────

def _write_summary(tmp_path: Path, statuses: dict) -> Path:
    p = tmp_path / "campaign_summary.json"
    p.write_text(json.dumps(statuses, ensure_ascii=False), encoding="utf-8")
    return p


def test_summary_all_pass(tmp_path):
    p = _write_summary(tmp_path, {"a": {"status": "PASS"},
                                  "b": {"status": "PASS"}})
    assert mod.campaign_exit_code_from_summary(p) == 0


def test_summary_skip_seats(tmp_path):
    """伪造 K-7 座位结果文件：全 SKIP → rc3（修复前此形态恒 rc0）。"""
    p = _write_summary(tmp_path, {"ms_ring_patch": {"status": "SKIP"}})
    assert mod.campaign_exit_code_from_summary(p) == 3


def test_summary_fail_and_partial(tmp_path):
    p = _write_summary(tmp_path, {"a": {"status": "FAIL"}})
    assert mod.campaign_exit_code_from_summary(p) == 2
    p2 = _write_summary(tmp_path, {"a": {"status": "PARTIAL"}})
    assert mod.campaign_exit_code_from_summary(p2) == 4


def test_summary_missing_or_corrupt_or_non_dict_is_launch_error(tmp_path):
    assert mod.campaign_exit_code_from_summary(
        tmp_path / "nope.json") == 1            # 缺文件
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert mod.campaign_exit_code_from_summary(bad) == 1     # 损坏
    arr = tmp_path / "arr.json"
    arr.write_text("[1,2]", encoding="utf-8")
    assert mod.campaign_exit_code_from_summary(arr) == 1     # 非 dict
    weird = _write_summary(tmp_path, {"a": "not-a-dict"})
    assert mod.campaign_exit_code_from_summary(weird) == 4   # 值非 dict=未知态


# ─── ③ 批尾日志行格式 ─────────────────────────────────────────────────────

def test_format_seat_line_prescribed_format():
    line = mod.format_seat_line(
        {"PASS": 1, "SKIP": 1, "FAIL": 1, "PARTIAL": 1}, 2)
    assert line == "seats=4 pass=1 skip=1 fail=1 rc=2"
    assert mod.format_seat_line({}, 0) == "seats=0 pass=0 skip=0 fail=0 rc=0"


# ─── ④ argparse 用法错=64（避开 rc2 双义）────────────────────────────────

def test_usage_error_exits_64_not_2():
    """--timeout 传非数 → 自定义 error rc=64；rc2 已语义化为「任一座 FAIL」，
    用法错若仍落 2 即 H1-6 双义（链消费方会把调用笔误误读成战役失败）。"""
    with pytest.raises(SystemExit) as ei:
        mod._parse_args(["--timeout", "notanint"])
    assert ei.value.code == mod.EXIT_USAGE == 64


def test_good_args_still_parse():
    a = mod._parse_args(["--only", "ms_patch", "--timeout", "99"])
    assert a.only == "ms_patch" and a.timeout == 99.0


# ─── ⑤ H1-7/#295：REPO 绝对锚（非仓根 cwd 装载不炸）─────────────────────

def test_module_loads_from_runs_subdir_cwd_with_absolute_repo_anchor(
        tmp_path, monkeypatch):
    """从 runs/ 子目录 cwd spec 装载（#295 族回归钉）：模块正常导入，
    sys.path 注入为仓根绝对 src（cwd 相对 "src" 旧写法在此形态下
    ModuleNotFoundError）。零仓根锚回归签名=REPO 恒为仓根。"""
    fake_runs = tmp_path / "runs" / "ge_fd" / "some_seat"
    fake_runs.mkdir(parents=True)
    monkeypatch.chdir(fake_runs)
    m = _load(cwd=fake_runs)
    assert m.REPO == REPO
    assert (REPO / "src").is_dir()
    assert str(REPO / "src") in sys.path
