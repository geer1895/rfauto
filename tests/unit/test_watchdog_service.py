"""watchdog service 三证判活钉子测试（T-O12，aurora_o）。

验收对应（任务书口径）：
①三证判定真值表：alive/stalled/dead/unknown 全覆盖（合成进程 stub+注入 CPU
  采样两态；真采样面单钉本进程 busy-loop 两采样 delta>0）；
②unknown 不凑判钉：census 不可验证/采样失败/glob 未配置/glob 零命中一律
  unknown（#122 家法），且信封恒 ok=True（#105 观测面不阻塞）；
③确定性：同采样两次判定逐位一致（信封 dict 全等）；
④负例：pid 不存在→dead；无产物 glob→证据 None 非 False。

零真机、零真 PS（census_fn 全注入）；产物面一律 tmp_path（#144：测试不落
真实 runs/）。watch_loop 钉"默认关"：生成器函数、不迭代零文件写、sink 白
名单单根 runs/watchdog 越界 ValueError。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

import rfauto.service.watchdog_service as wd
from rfauto.service.watchdog_service import (
    campaign_liveness_summary,
    census_command,
    judge_artifact_only,
    judge_liveness,
    sample_cpu_seconds,
    seat_liveness_view,
    validate_watch_root,
    watch_loop,
)


def _view(target, *, cpu_samples=None, alive=True, globs=(),
          now=1000.0, census=None, **kwargs):
    """seat_liveness_view 全注入快捷构造：cpu_samples=两次采样脚本序列；
    产物面走真实 glob（测试文件落 tmp_path，mtime 真实可控）。"""
    samples = list(cpu_samples) if cpu_samples is not None else [None, None]

    def fake_sample(pid):
        return samples.pop(0) if samples else None

    return seat_liveness_view(
        target,
        artifact_globs=globs,
        cpu_sample_fn=fake_sample,
        sleep_fn=lambda _s: None,
        pid_alive_fn=lambda pid: alive,
        census_fn=census if census is not None else (lambda name, fp: []),
        now=now,
        **kwargs,
    )


# ── 判定表纯函数单源 ─────────────────────────────────────────────────────────


def test_judge_liveness_truth_table():
    assert judge_liveness(False, None, None) == ("dead", judge_liveness(False, None, None)[1])
    assert judge_liveness(False, True, True)[0] == "dead"
    assert judge_liveness(None, True, True)[0] == "unknown"
    assert judge_liveness(True, True, None)[0] == "alive"
    assert judge_liveness(True, None, True)[0] == "alive"
    assert judge_liveness(True, True, False)[0] == "alive"
    assert judge_liveness(True, False, False)[0] == "stalled"
    assert judge_liveness(True, False, None)[0] == "stalled"
    assert judge_liveness(True, None, False)[0] == "stalled"
    assert judge_liveness(True, None, None)[0] == "unknown"


def test_judge_artifact_only_semantics():
    assert judge_artifact_only(True)[0] == "alive"
    assert judge_artifact_only(False)[0] == "stalled"
    assert judge_artifact_only(None)[0] == "unknown"
    assert "进程证缺席" in (judge_artifact_only(True)[1] or "")


# ── ① 三证真值表（视图层，合成 stub） ────────────────────────────────────────


def test_view_alive_by_cpu_growth():
    env = _view(100, cpu_samples=[1.0, 5.0], alive=True)
    assert env["ok"] is True and env["state"] == "alive"
    assert env["evidence"] == {"process_alive": True, "cpu_growing": True, "artifact_fresh": None}
    assert env["cpu"]["delta_s"] == pytest.approx(4.0)


def test_view_alive_by_fresh_artifact_real_file(tmp_path: Path):
    # #268 语义：进程 CPU 低但产物在写 → alive（mtime 活证覆盖）
    art = tmp_path / "art.log"
    art.write_text("progress", encoding="utf-8")
    os.utime(art, (900.0, 900.0))  # now=1000，age=100s ≤ 900s 窗
    env = _view(100, cpu_samples=[2.0, 2.0], alive=True, globs=[str(art.parent / "*.log")],
                now=1000.0)
    assert env["state"] == "alive"
    assert env["evidence"]["artifact_fresh"] is True
    assert env["artifacts"]["age_s"] == pytest.approx(100.0, abs=0.01)


def test_view_stalled_zero_cpu_and_stale_artifact(tmp_path: Path):
    art = tmp_path / "art.log"
    art.write_text("stalled", encoding="utf-8")
    os.utime(art, (5.0, 5.0))  # now=1000，age=995 > 900 窗 → 停滞
    env = _view(100, cpu_samples=[3.0, 3.0], alive=True, globs=[str(art.parent / "*.log")],
                now=1000.0)
    assert env["state"] == "stalled"
    assert env["evidence"]["cpu_growing"] is False
    assert env["evidence"]["artifact_fresh"] is False
    assert env["cpu"]["delta_s"] == 0.0, "stalled 附两证数字（#157 早期形态）"


def test_view_stalled_zero_cpu_no_globs():
    env = _view(100, cpu_samples=[7.0, 7.0], alive=True)
    assert env["state"] == "stalled"
    assert env["evidence"]["artifact_fresh"] is None  # 未配置=缺席，不是 False


def test_view_stalled_cpu_unverifiable_but_artifact_stale(tmp_path: Path):
    art = tmp_path / "art.log"
    art.write_text("x", encoding="utf-8")
    os.utime(art, (50.0, 50.0))  # age=950 > 900s 窗 → 停滞（边界外）
    env = _view(100, cpu_samples=[None, None], alive=True, globs=[str(art)],
                now=1000.0, stall_window_s=900.0)
    assert env["state"] == "stalled"
    assert env["evidence"]["cpu_growing"] is None
    assert env["evidence"]["artifact_fresh"] is False


def test_view_dead_process():
    env = _view(999, alive=False, cpu_samples=[1.0, 2.0], globs=["x/*.log"])
    assert env["state"] == "dead"
    assert env["evidence"]["process_alive"] is False
    assert env["evidence"]["cpu_growing"] is None, "死进程不采样（快速短路）"


def test_view_census_target_match_and_dead():
    lines = ["4321|python.exe -m pytest tests/unit -q"]

    def census(name, fp):
        return lines if "pytest" in fp else []

    env = _view("pytest", census=census, cpu_samples=[1.0, 9.0])
    assert env["state"] == "alive" and env["target"]["kind"] == "census"
    assert env["cpu"]["first_s"] == 1.0, "census 命中行 pid 作 CPU 采样对象"
    env_dead = _view("pytest", census=lambda name, fp: [], cpu_samples=[])
    assert env_dead["state"] == "dead", "census 零命中=进程不在 → dead"


def test_view_census_dict_target_with_process_name():
    spec = {"process_name": "python.exe", "fingerprint": "pytest"}

    def census(name, fp):
        assert name == "python.exe" and fp == "pytest"
        return ["55|python.exe -m pytest"]

    env = _view(spec, census=census, cpu_samples=[1.0, 1.0])
    assert env["state"] == "stalled"  # 命中在但零增长


# ── ② unknown 不凑判钉 ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs",
    [
        {"census": lambda name, fp: None, "cpu_samples": []},           # census 不可验证
        {"cpu_samples": [None, None]},                                  # CPU 采样失败+无 glob
        {"cpu_samples": [None, None], "globs": ["x-no-such-dir-xyz/*.log"]},  # glob 零命中
        {"cpu_samples": [1.0, None]},                                   # 二次采样失败
    ],
)
def test_view_unknown_never_forced(kwargs):
    env = _view(100, alive=True, **kwargs)
    assert env["ok"] is True, "unknown 是观测成功且如实（#105），不是失败"
    assert env["state"] == "unknown"
    assert "不凑判" in (env["reason"] or "")


def test_view_bool_target_is_error_envelope():
    env = _view(True)
    assert env["ok"] is False, "bool 不是 pid——isinstance(int) 陷阱显式拒绝"


# ── ③ 确定性：同采样两次判定逐位 ─────────────────────────────────────────────


def test_view_deterministic_same_samples_bit_identical(tmp_path: Path):
    art = tmp_path / "a.log"
    art.write_text("x", encoding="utf-8")
    os.utime(art, (950.0, 950.0))
    kwargs = dict(
        cpu_samples=[1.5, 1.5], alive=True, globs=[str(art.parent / "*.log")], now=1000.0,
    )
    v1 = _view(100, **kwargs)
    v2 = _view(100, **kwargs)
    assert v1 == v2, "同采样两次判定逐位一致（验收③）"


# ── ④ 负例 ───────────────────────────────────────────────────────────────────


def test_no_globs_is_absent_evidence_not_stale():
    env = _view(100, cpu_samples=[1.0, 2.0], alive=True, globs=())
    assert env["evidence"]["artifact_fresh"] is None
    assert env["artifacts"]["reason"], "未配置 glob 必须留原因"


def test_glob_zero_match_is_unknown_not_false():
    env = _view(100, cpu_samples=[None, None], alive=True, globs=["x-no-such-dir-xyz/*.log"])
    assert env["evidence"]["artifact_fresh"] is None
    assert env["artifacts"]["matches"] == 0


# ── 真实 CPU 采样两态（纯 stdlib 面） ────────────────────────────────────────


def test_sample_cpu_seconds_self_grows_and_invalid_is_none():
    a = sample_cpu_seconds(os.getpid())
    assert a is not None and a >= 0.0
    _ = sum(range(2_000_000))  # busy loop：保证本进程 CPU 时间推进
    b = sample_cpu_seconds(os.getpid())
    assert b > a, "真采样两态：同进程两次采样 CPU 必增长"
    assert sample_cpu_seconds(0) is None
    assert sample_cpu_seconds(2**30) is None, "不存在 pid → None（证据缺失语义）"


# ── 批量视图 campaign_liveness_summary ───────────────────────────────────────


def _make_dir(tmp_path: Path, name: str, mtime: float | None) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    if mtime is not None:
        f = d / "run.log"
        f.write_text("x", encoding="utf-8")
        os.utime(f, (mtime, mtime))
    return d


def test_campaign_summary_rows_and_counts(tmp_path: Path):
    fresh = _make_dir(tmp_path, "fresh", 995.0)
    stalled = _make_dir(tmp_path, "stalled", 5.0)
    empty = _make_dir(tmp_path, "empty", None)  # 目录在但零产物
    missing = tmp_path / "missing"
    now = 1000.0
    env = campaign_liveness_summary(
        [str(fresh), str(stalled), str(empty), str(missing)],
        artifact_globs=("*.log",), now=now, stall_window_s=900.0,
    )
    assert env["ok"] is True and env["n_dirs"] == 4
    rows = {Path(r["run_dir"]).name: r for r in env["rows"]}
    assert rows["fresh"]["state"] == "alive"
    assert rows["stalled"]["state"] == "stalled"
    assert rows["empty"]["state"] == "unknown", "零产物=无证据不凑判"
    assert rows["missing"]["state"] == "unknown", "目录缺失=unknown 不凑 dead"
    assert env["counts"] == {"alive": 1, "stalled": 1, "dead": 0, "unknown": 2}
    assert rows["fresh"]["evidence"]["process_alive"] is None, "未提供 pid=进程证缺席"
    assert rows["fresh"]["pid"] is None


def test_campaign_summary_with_pid_full_three_evidence(tmp_path: Path):
    d = _make_dir(tmp_path, "fresh", 995.0)
    seq = iter([1.0, 8.0])
    env = campaign_liveness_summary(
        [str(d)], artifact_globs=("*.log",), now=1000.0,
        pids={str(d): 4242},
        cpu_sample_fn=lambda pid: next(seq, None),
        sleep_fn=lambda _s: None,
        pid_alive_fn=lambda pid: True,
    )
    row = env["rows"][0]
    assert row["pid"] == 4242
    assert row["state"] == "alive", "提供 pid 的行走全三证（CPU 增长正证）"
    assert row["evidence"] == {
        "process_alive": True, "cpu_growing": True, "artifact_fresh": True
    }


def test_campaign_summary_deterministic(tmp_path: Path):
    d1 = _make_dir(tmp_path, "a", 995.0)
    d2 = _make_dir(tmp_path, "b", 5.0)
    kwargs = dict(artifact_globs=("*.log",), now=1000.0, stall_window_s=900.0)
    s1 = campaign_liveness_summary([str(d1), str(d2)], **kwargs)
    s2 = campaign_liveness_summary([str(d1), str(d2)], **kwargs)
    assert s1 == s2


# ── watch_loop：默认关 + 白名单 sink ─────────────────────────────────────────


def test_watch_loop_is_iterator_default_off():
    import inspect

    assert inspect.isgenerator(
        wd._watch_iter(1, Path("x"), 0, 0.0, time.time, lambda _s: None, {})
    ), "watch_loop 迭代体必须是生成器（惰性轮次，急切校验在 watch_loop 本体）"
    src = inspect.getsource(wd)
    assert "threading" not in src and "Thread(" not in src, "模块零线程面（#105：可调用函数非线程）"


def test_watch_loop_no_iteration_no_file_write(tmp_path: Path):
    sink = tmp_path / "runs" / "watchdog" / "seat1" / "live.jsonl"
    gen = watch_loop(100, sink=sink, whitelist_root=tmp_path / "runs" / "watchdog",
                     pid_alive_fn=lambda pid: False, census_fn=lambda n, f: [])
    assert not sink.exists(), "生成器不迭代=零文件写（默认关语义）"
    list(gen)  # 消费一轮
    assert sink.exists() and len(sink.read_text(encoding="utf-8").splitlines()) == 1
    line = json.loads(sink.read_text(encoding="utf-8").splitlines()[0])
    assert line["view"]["ok"] is True and line["view"]["watch_round"] == 1


def test_watch_loop_two_rounds_jsonl_growth(tmp_path: Path):
    sink = tmp_path / "runs" / "watchdog" / "seat1" / "live.jsonl"
    views = list(
        watch_loop(None, sink=sink, rounds=2, interval_s=0.0,
                   whitelist_root=tmp_path / "runs" / "watchdog",
                   artifact_globs=(), glob_fn=lambda p: [], sleep_fn=lambda _s: None)
    )
    assert len(views) == 2 and views[0]["watch_round"] == 1 and views[1]["watch_round"] == 2
    assert all(v["sink_write_ok"] is True for v in views)
    assert len(sink.read_text(encoding="utf-8").splitlines()) == 2


def test_watch_loop_sink_outside_whitelist_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        watch_loop(1, sink=tmp_path / "elsewhere" / "live.jsonl",
                   whitelist_root=tmp_path / "runs" / "watchdog")
    with pytest.raises(ValueError):
        watch_loop(1, sink=tmp_path / "runs" / "other.jsonl",
                   whitelist_root=tmp_path / "runs" / "watchdog")


def test_validate_watch_root_semantics(tmp_path: Path):
    assert validate_watch_root(tmp_path / "runs" / "watchdog") == tmp_path / "runs" / "watchdog"
    with pytest.raises(ValueError):
        validate_watch_root(tmp_path / "runs")


# ── census 命令构造（#261 单源复用钉） ───────────────────────────────────────


def test_census_command_delegates_and_variants():
    from rfauto.service.remote_service.mutex import remote_mutex_command

    with_name = census_command("python.exe", "pytest")
    assert with_name == remote_mutex_command("python.exe", "pytest"), "有进程名=单源直复用"
    without = census_command(None, "pytest")
    assert "Win32_Process" in without and "pytest" in without
    assert "$_.CommandLine -match 'pytest'" in without
