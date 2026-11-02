"""devtest 投机执行 watcher 档单测（T-O11 扩容，aurora_p F1-deep）。

七组验收对应（任务书口径）：
①缺省零变化：T-O11 指纹 fields 缺 content_digest 键=原口径逐位同；watch
 旗标缺省 False、既有旗标契约（option strings/dest/缺省值）冻结钉；
②debounce 合并：窗口内两次变更（复采样指纹演进）→ 恰一次预跑发射，
 窗口终态指纹为准；
③Fast Path 三态：src 未变（缓存命中）→ nothing_to_do 零子进程；census
 忙/不可验证 → wait 零子进程；真机面（real_edt）→ 发射口 declined 如实
 零子进程；同指纹在飞 → absorbed 零 census 探针；
④指纹过期：content_digest 变化 → 旧缓存 stale 如实（status 不冒充），
 watch 评估对新指纹发射新预跑；
⑤单实例：心跳 child/owner 存活 → wait（不落 declined 假记录）零子进程；
⑥优雅停：should_stop 置位 → 循环退出零悬挂（分片 sleep 可打断；窗中停
 不发射）；rounds 上限与 sink 关闭/越界钉；
⑦轮询循环确定性：tmp 树+注入时钟/sleep，逐 tick 决策序列+观测 jsonl 逐
 行形状钉，零真轮询零真 sleep 零湖写。

全部 census/spawn/时钟/sleep/存活面注入（T-O11 fake 家法）；缓存根一律
tmp_path/"runs/devtest_speculative"（白名单尾段校验通过），零真实 runs/
湖写——唯一运行期写点（观测 jsonl）在 sink_enabled=False 的零写组之外
全部落 tmp 缓存根（经 guard 守卫）。
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import pytest

import devtest_speculative as driver
import rfauto.service.devtest_speculative_service as dss
import rfauto.service.speculative_watch_service as sws
from rfauto.service.speculative_watch_service import (
    MIN_INTERVAL_S,
    WatchConfig,
    changed_fingerprint,
    content_digest_of,
    evaluate_tick,
    wait_decision,
    watch_loop,
)

_HEAD = "a" * 40
_DIGEST = "d" * 64
_CHANGED = ["src/rfauto/service/devtest_speculative_service.py"]
_TESTS = ["tests/unit/test_devtest_speculative.py"]


@pytest.fixture()
def cache_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs" / "devtest_speculative"
    root.mkdir(parents=True)
    return root


class _Env:
    """注入环境：spawn/census/alive/sleep/clock 全记录。"""

    def __init__(self) -> None:
        self.spawned: list[list[str]] = []
        self.census_calls = 0
        self.sleeps: list[float] = []
        self.now = 1000.0
        self.census: list[dict] | None = []  # 缺省空闲
        self.alive_pids: set[int] = set()

    def spawn(self, cmd, log_path):
        self.spawned.append(list(cmd))
        return 424242

    def census_fn(self):
        self.census_calls += 1
        return self.census

    def alive(self, pid) -> bool:
        try:
            return int(pid) in self.alive_pids
        except (TypeError, ValueError):
            return False

    def sleep(self, s: float) -> None:
        self.sleeps.append(round(float(s), 6))
        self.now += float(s)

    def clock(self) -> float:
        return self.now


def _cfg(cache_root: Path, **kw) -> WatchConfig:
    return WatchConfig(cache_root=cache_root, **kw)


def _finish(cache_root: Path, fp: str, *, digest: str | None = None) -> None:
    """把一轮 running 记录置 done+summary（T-O11 公开面，测试家法）。"""
    dss.finish_run(
        cache_root, fp,
        {"schema": dss.SPECULATIVE_SUMMARY_SCHEMA, "fingerprint": fp, "state": "done",
         "passed": 22, "failed": 0, "failed_ids": [], "log_path": "x", "ts": 1060.0,
         "reason": None},
        "done",
    )
    if digest is not None:
        rec = json.loads((cache_root / "fingerprint.json").read_text(encoding="utf-8"))
        rec["fields"]["content_digest"] = digest
        (cache_root / "fingerprint.json").write_text(
            json.dumps(rec, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8"
        )


def _watch_spawn_cmd_marker(cmd: list[str]) -> bool:
    return "--child" in cmd


# ── ① 缺省零变化 ─────────────────────────────────────────────────────────────


class TestDefaultZeroChange:
    def test_fingerprint_fields_without_digest_is_legacy_set(self):
        fp, fields = dss.compute_fingerprint(
            ["src/b.py", "src/a.py"], head=_HEAD, map_digest=_DIGEST, tests=["tests/t1.py"]
        )
        assert set(fields) == {
            "version", "changed_src", "changed_src_sha256", "head", "map_digest",
            "tests", "tests_sha256",
        }, "缺省（无 content_digest）fields 键集必须= T-O11 原口径"
        assert "content_digest" not in fields
        fp_same, _ = dss.compute_fingerprint(
            ["src/a.py", "src/b.py"], head=_HEAD, map_digest=_DIGEST,
            tests=["tests/t1.py"], content_digest=None,
        )
        assert fp == fp_same, "content_digest=None 与缺省逐位同（显式 None=关）"

    def test_fingerprint_with_digest_differs_and_is_pinned(self):
        fp_base, _ = dss.compute_fingerprint(
            _CHANGED, head=_HEAD, map_digest=_DIGEST, tests=_TESTS
        )
        fp_d1, fields_d1 = dss.compute_fingerprint(
            _CHANGED, head=_HEAD, map_digest=_DIGEST, tests=_TESTS, content_digest="cafe" * 8
        )
        fp_d2, _ = dss.compute_fingerprint(
            _CHANGED, head=_HEAD, map_digest=_DIGEST, tests=_TESTS, content_digest="beef" * 8
        )
        assert fp_d1 != fp_base, "给内容摘要必须换指纹（watch 档内容感知口径）"
        assert fp_d1 != fp_d2, "内容变化必须换指纹"
        assert fields_d1["content_digest"] == "cafe" * 8

    def test_watch_flag_defaults_and_legacy_contract_frozen(self):
        ap = driver._build_parser()
        ns, extra = ap.parse_known_args([])
        assert ns.watch is False and ns.no_sink is False
        assert ns.rounds == sws.DEFAULT_ROUNDS == 0
        assert ns.interval == sws.DEFAULT_INTERVAL_S
        assert ns.debounce == sws.DEFAULT_DEBOUNCE_S
        assert extra == []
        # 既有旗标契约冻结（T-O11 原口径；翻面即红）
        legacy = {
            "--status": (False, "status"),
            "--child": (False, "child"),
            "--staged": (False, "staged"),
            "--base": (None, "base"),
            "--scope": ("direct", "scope"),
            "--json": (False, "json"),
        }
        by_flag = {opt: a for a in ap._actions for opt in a.option_strings if opt in legacy}
        for flag, (default, dest) in legacy.items():
            a = by_flag[flag]
            assert a.dest == dest and a.default == default, f"{flag} 契约漂移"
        assert by_flag["--scope"].choices == ("direct", "closed")

    def test_watch_mutex_with_status_child_is_usage_error(self, capsys):
        with pytest.raises(SystemExit) as ei:
            driver.main(["--watch", "--status"])
        assert ei.value.code == 2
        with pytest.raises(SystemExit) as ei2:
            driver.main(["--watch", "--child"])
        assert ei2.value.code == 2
        with pytest.raises(SystemExit) as ei3:
            driver.main(["--watch", "--rounds", "-1"])
        assert ei3.value.code == 2

    def test_watch_flag_does_not_disturb_trigger_parse(self):
        ap = driver._build_parser()
        ns, extra = ap.parse_known_args(["--staged", "--scope", "closed"])
        assert ns.watch is False and ns.staged is True and ns.scope == "closed"
        assert extra == []


# ── ② debounce 合并（两变一跑） ──────────────────────────────────────────────


class TestDebounceMerge:
    def test_two_changes_in_window_merge_to_one_launch(self, cache_root: Path):
        env = _Env()
        surfaces = [
            ["src/rfauto/service/devtest_speculative_service.py"],                    # 初始采样
            ["src/rfauto/service/devtest_speculative_service.py",
             "src/rfauto/service/watchdog_service.py"],                                # 窗内第一次演进
            ["src/rfauto/service/devtest_speculative_service.py",
             "src/rfauto/service/watchdog_service.py"],                                # 窗满收敛（终态）
        ]
        calls = {"n": 0}

        def collect():
            out = surfaces[min(calls["n"], len(surfaces) - 1)]
            calls["n"] += 1
            return out, _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=1.0, debounce_s=2.0, rounds=1),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "watch_e2e.jsonl",
            )
        )
        assert calls["n"] == 3, "初始采样+窗满复采样（演进一次+收敛一次）=恰 3 次采样"
        assert len(rows) == 1
        assert rows[0]["decision"] == "fire" and rows[0]["state"] == "launched"
        assert len(env.spawned) == 1, "窗口内两次变更必须合并为一次发射（验收 C）"
        assert _watch_spawn_cmd_marker(env.spawned[0])
        # 发射的是窗口终态指纹（含两文件），不是初始单文件指纹
        fp_final, _, _ = changed_fingerprint(
            surfaces[2], tests=_TESTS, head=_HEAD, map_digest=_DIGEST, content_digest=None
        )
        assert rows[0]["fingerprint"] == fp_final
        assert sum(env.sleeps) >= 2.0 + 1.0, "窗（2s）+ tick 间隔（1s）分片齐备"
        assert all(0 <= s <= 0.2 + 1e-9 for s in env.sleeps), "sleep 全为 ≤0.2s 分片（可打断）"

    def test_stable_window_fires_with_two_samples(self, cache_root: Path):
        env = _Env()
        calls = {"n": 0}
        surface = ["src/rfauto/service/devtest_speculative_service.py"]

        def collect():
            calls["n"] += 1
            return surface, _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=1.0, debounce_s=1.0, rounds=1),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert calls["n"] == 2 and len(env.spawned) == 1
        assert rows[0]["decision"] == "fire"


# ── ③ Fast Path 三态 ─────────────────────────────────────────────────────────


class TestFastPath:
    def _launch_done(self, cache_root: Path, env: _Env) -> str:
        """先发射并收尾一轮（同 T-O11 _launch 家法），返回指纹。"""
        trig = dss.speculative_run(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            census_fn=lambda: [], pid_alive_fn=lambda pid: False, spawn_fn=env.spawn,
            owner_pid=777, now=1000.0,
        )
        assert trig["state"] == "launched"
        fp = trig["fingerprint"]
        _finish(cache_root, fp)
        return fp

    def test_r1_unchanged_cache_hit_no_process(self, cache_root: Path):
        env = _Env()
        fp = self._launch_done(cache_root, env)
        env.spawned.clear()
        decision = evaluate_tick(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
            cache_root=cache_root, config=_cfg(cache_root),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=1010.0,
        )
        assert decision["decision"] == "nothing_to_do"
        assert decision["state"] == "cached" and decision["fast_path"] == "cache_hit"
        assert decision["summary"]["fingerprint"] == fp
        assert env.spawned == [] and env.census_calls == 0, "R1 直判零子进程零 census"

    def test_r3_census_busy_waits_with_no_process(self, cache_root: Path):
        env = _Env()
        env.census = [{"pid": 9, "name": "python.exe", "kind": "pytest_or_runner",
                       "cmdline": "pytest -q"}]
        decision = evaluate_tick(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
            cache_root=cache_root, config=_cfg(cache_root),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=1010.0,
        )
        assert decision["decision"] == "wait"
        assert decision["fast_path"] == "mutex_busy_or_unverified"
        assert env.spawned == [], "忙态零子进程（验收 D）"

    def test_r3_census_unverified_fail_closed_waits(self, cache_root: Path):
        env = _Env()
        env.census = None
        decision = evaluate_tick(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
            cache_root=cache_root, config=_cfg(cache_root),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=1010.0,
        )
        assert decision["decision"] == "wait" and decision["fast_path"] == "mutex_busy_or_unverified"
        assert env.spawned == []

    def test_real_machine_only_declined_honest(self, cache_root: Path):
        env = _Env()
        decision = evaluate_tick(
            _CHANGED, tests=["tests/real_edt/test_hfss_real.py"], head=_HEAD,
            map_digest=_DIGEST, cache_root=cache_root, config=_cfg(cache_root),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=1010.0,
        )
        assert decision["decision"] == "wait" and decision["state"] == "declined"
        assert decision["guard"] == "real_machine_only"
        assert env.spawned == [], "真机面拒绝零子进程（投机预跑永不真机）"

    def test_absorbed_same_fingerprint_in_flight_no_census(self, cache_root: Path):
        env = _Env()
        trig = dss.speculative_run(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            census_fn=lambda: [], pid_alive_fn=lambda pid: False, spawn_fn=env.spawn,
            owner_pid=777, now=1000.0,
        )
        fp = trig["fingerprint"]
        env.alive_pids.add(424242)
        env.census = None  # 若被消费即 wait——吸收路径必须前置短路
        decision = evaluate_tick(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
            cache_root=cache_root, config=_cfg(cache_root),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=1002.0,
        )
        assert decision["decision"] == "absorbed" and decision["state"] == "absorbed"
        assert env.census_calls == 0, "同指纹在飞吸收零 census 探针"
        assert len(env.spawned) == 1, "在飞轮不二发（Batch 合并）"
        env.alive_pids.discard(424242)
        _ = fp

    def test_wait_decision_rule_table_pure(self):
        fp = "0" * 64
        r = wait_decision(fp, in_flight_fp=fp, in_flight_alive=True,
                          heartbeat_busy=True, census_ok=False)
        assert r["state"] == "absorbed", "吸收优先于一切等待规则"
        r2 = wait_decision(fp, in_flight_fp="1" * 64, in_flight_alive=True,
                           heartbeat_busy=True, census_ok=True)
        assert r2["state"] == "wait" and r2["fast_path"] == "single_instance"
        r3 = wait_decision(fp, in_flight_fp=None, in_flight_alive=False,
                           heartbeat_busy=False, census_ok=False)
        assert r3["state"] == "wait" and r3["fast_path"] == "mutex_busy_or_unverified"
        r4 = wait_decision(fp, in_flight_fp=None, in_flight_alive=False,
                           heartbeat_busy=False, census_ok=True, debounce_remaining=1.5)
        assert r4["state"] == "wait" and r4["fast_path"] == "debounce_window"
        r5 = wait_decision(fp, in_flight_fp=None, in_flight_alive=False,
                           heartbeat_busy=False, census_ok=True)
        assert r5["state"] == "fire"


# ── ④ 指纹过期（content_digest 口径） ────────────────────────────────────────


class TestDigestStaleness:
    def test_status_stale_when_digest_changes(self, cache_root: Path):
        env = _Env()
        trig = dss.speculative_run(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            census_fn=lambda: [], pid_alive_fn=lambda pid: False, spawn_fn=env.spawn,
            owner_pid=777, now=1000.0, content_digest="c1" * 32,
        )
        _finish(cache_root, trig["fingerprint"], digest="c1" * 32)
        st = dss.speculative_status(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            content_digest="c2" * 32,
        )
        assert st["state"] == "stale", "内容变化 → 旧缓存如实 stale，不冒充有效"
        assert "summary" not in st
        st_hit = dss.speculative_status(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            content_digest="c1" * 32,
        )
        assert st_hit["state"] == "hit"

    def test_watch_refires_on_digest_change(self, cache_root: Path):
        env = _Env()
        trig = dss.speculative_run(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            census_fn=lambda: [], pid_alive_fn=lambda pid: False, spawn_fn=env.spawn,
            owner_pid=777, now=1000.0, content_digest="c1" * 32,
        )
        _finish(cache_root, trig["fingerprint"], digest="c1" * 32)
        env.spawned.clear()
        decision = evaluate_tick(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST,
            cache_root=cache_root, config=_cfg(cache_root, min_trigger_interval_s=0.0),
            content_digest="c2" * 32,
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=2000.0,
        )
        assert decision["decision"] == "fire", "内容感知口径下二次编辑必须重发（新指纹）"
        assert len(env.spawned) == 1
        rec = json.loads((cache_root / "fingerprint.json").read_text(encoding="utf-8"))
        assert rec["fingerprint"] != trig["fingerprint"]
        assert rec["fields"]["content_digest"] == "c2" * 32

    def test_content_digest_of_tmp_tree(self, tmp_path: Path):
        f = tmp_path / "src" / "a.py"
        f.parent.mkdir(parents=True)
        f.write_text("x = 1\n", encoding="utf-8")
        d1 = content_digest_of(["src/a.py"], root=tmp_path)
        assert d1 is not None and len(d1) == 64
        f.write_text("x = 2\n", encoding="utf-8")
        d2 = content_digest_of(["src/a.py"], root=tmp_path)
        assert d2 != d1, "文件内容变 → 摘要变"
        assert content_digest_of([], root=tmp_path) is None
        d_missing = content_digest_of(["src/gone.py"], root=tmp_path)
        assert d_missing is not None, "缺失文件以 '-' 占位（不静默等于空）"

    def test_changed_fingerprint_deterministic(self, tmp_path: Path):
        a = changed_fingerprint(
            ["src/b.py", "src/a.py"], tests=["tests/t2.py", "tests/t1.py"],
            head=_HEAD, map_digest=_DIGEST, content_digest="cc",
        )
        b = changed_fingerprint(
            ["src/a.py", "src/b.py"], tests=["tests/t1.py", "tests/t2.py"],
            head=_HEAD, map_digest=_DIGEST, content_digest="cc",
        )
        assert a[0] == b[0] and sorted(a[1]) == sorted(b[1]), "顺序不敏感确定性"
        assert a[2] == [] and b[2] == [], "无真机面剔除时 dropped 为空"


# ── ⑤ 单实例 ─────────────────────────────────────────────────────────────────


class TestSingleInstance:
    def test_heartbeat_busy_child_alive_waits(self, cache_root: Path):
        env = _Env()
        trig = dss.speculative_run(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            census_fn=lambda: [], pid_alive_fn=lambda pid: False, spawn_fn=env.spawn,
            owner_pid=777, now=1000.0,
        )
        assert trig["state"] == "launched"
        env.alive_pids.add(424242)  # child 仍活（单实例占用）
        env.census = None  # census 不可验证也不得发射（单实例前置）
        env.spawned.clear()  # 清掉 setup 发射记录，只看本轮
        decision = evaluate_tick(
            ["src/rfauto/service/watchdog_service.py"], tests=_TESTS, head=_HEAD,
            map_digest=_DIGEST, cache_root=cache_root, config=_cfg(cache_root),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=1005.0,
        )
        assert decision["decision"] == "wait"
        assert decision["fast_path"] == "single_instance"
        assert env.spawned == [], "单实例占用零新发射"

    def test_dead_pid_heartbeat_does_not_block(self, cache_root: Path):
        env = _Env()
        trig = dss.speculative_run(
            _CHANGED, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root,
            census_fn=lambda: [], pid_alive_fn=lambda pid: False, spawn_fn=env.spawn,
            owner_pid=777, now=1000.0,
        )
        assert trig["state"] == "launched"
        decision = evaluate_tick(
            ["src/rfauto/service/watchdog_service.py"], tests=_TESTS, head=_HEAD,
            map_digest=_DIGEST, cache_root=cache_root,
            config=_cfg(cache_root, min_trigger_interval_s=0.0),
            census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
            owner_pid=777, now=5000.0,
        )
        assert decision["decision"] == "fire", "死 pid 心跳=无主遗痕，不阻塞新触发"


# ── ⑥ 优雅停 ─────────────────────────────────────────────────────────────────


class TestGracefulStop:
    def test_stop_between_ticks_ends_clean(self, cache_root: Path):
        env = _Env()
        stop_box = {"n": 0}

        def should_stop() -> bool:
            stop_box["n"] += 1
            return stop_box["n"] > 2  # 首 tick 后置位

        def collect():
            return [], _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=5.0, rounds=0),
                should_stop=should_stop, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert len(rows) == 1 and rows[0]["decision"] == "nothing_to_do"
        assert env.spawned == []
        assert stop_box["n"] <= 4, "分片 sleep 内识别停止（无整段 interval 空等）"
        assert all(s <= 0.2 + 1e-9 for s in env.sleeps)

    def test_stop_mid_debounce_window_no_spawn(self, cache_root: Path):
        env = _Env()
        surface = ["src/rfauto/service/devtest_speculative_service.py"]
        stop = threading.Event()
        slices = {"n": 0}

        def sleep_track(s: float) -> None:
            env.sleep(s)
            slices["n"] += 1
            if slices["n"] >= 2:
                stop.set()  # 窗 sleep 分 2 片后置位 → 窗中优雅退出

        def collect():
            return surface, _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=1.0, debounce_s=3.0, rounds=0),
                should_stop=stop.is_set, sleep_fn=sleep_track, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert rows == [] and env.spawned == [], "窗中停止：零发射零行"
        assert slices["n"] < 15, "停止在分片内识别（未睡满整窗 3s/0.2s=15 片）"

    def test_rounds_cap_and_zero_infinite_contract(self, cache_root: Path):
        env = _Env()
        counter = {"n": 0}

        def collect():
            counter["n"] += 1
            return [], _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=0.5, rounds=3),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert len(rows) == 3 and counter["n"] == 3, "rounds=3 恰三轮退出"

    def test_sink_disabled_zero_write(self, cache_root: Path):
        env = _Env()

        def collect():
            return [], _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, rounds=1, sink_enabled=False),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777,
            )
        )
        assert rows[0]["sink_write_ok"] is False
        assert list(cache_root.rglob("*")) == [], "sink 关闭=缓存根零文件写"

    def test_sink_outside_root_rejected_eagerly(self, tmp_path: Path, cache_root: Path):
        with pytest.raises(dss.SpeculativeGuardError):
            watch_loop(
                lambda: ([], _HEAD, _DIGEST, _TESTS), cache_root=cache_root,
                config=_cfg(cache_root, rounds=1), sink_path=tmp_path / "evil.jsonl",
                census_fn=lambda: [], alive_fn=lambda pid: False,
                spawn_fn=lambda cmd, log: 1, owner_pid=777,
            )


# ── ⑦ 轮询循环确定性（tmp 树+注入时钟） ──────────────────────────────────────


class TestLoopDeterminism:
    def test_tick_sequence_and_sink_rows_shape(self, cache_root: Path):
        env = _Env()
        surfaces = [
            [],                                                        # tick1：无变更
            ["src/rfauto/service/devtest_speculative_service.py"],     # tick2：变更→fire
            ["src/rfauto/service/devtest_speculative_service.py"],     # tick3：在飞→absorbed
            ["src/rfauto/service/devtest_speculative_service.py"],     # tick4：在飞→absorbed
        ]
        calls = {"n": 0}

        def collect():
            out = surfaces[min(calls["n"], len(surfaces) - 1)]
            calls["n"] += 1
            return out, _HEAD, _DIGEST, _TESTS

        def spawn_track(cmd, log_path):
            pid = env.spawn(cmd, log_path)
            env.alive_pids.add(pid)  # 发射后 child 在飞（存活面模拟）
            return pid

        sink = cache_root / "watch_det.jsonl"
        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=1.0, debounce_s=0.0, rounds=4),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=spawn_track,
                owner_pid=777, sink_path=sink,
            )
        )
        assert [r["decision"] for r in rows] == [
            "nothing_to_do", "fire", "absorbed", "absorbed",
        ], "决策序列确定性：无变更/发射/在飞吸收×2"
        assert len(env.spawned) == 1
        assert env.census_calls == 2, (
            "tick1 无变更零 census；tick2 fire=预检+speculative_run 权威复核各一次；"
            "tick3/4 吸收零 census"
        )
        lines = sink.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 4
        parsed = [json.loads(ln) for ln in lines]
        assert all(p["schema"] == sws.WATCH_STATE_SCHEMA for p in parsed)
        assert [p["tick"] for p in parsed] == [1, 2, 3, 4]
        assert [p["decision"] for p in parsed] == ["nothing_to_do", "fire", "absorbed", "absorbed"]
        assert all(r["sink_write_ok"] is True for r in rows)
        fp1 = parsed[1]["fingerprint"]
        assert fp1 == parsed[2]["fingerprint"] == parsed[3]["fingerprint"], "吸收行同指纹"

    def test_collect_failure_yields_error_and_stops(self, cache_root: Path):
        env = _Env()

        def collect():
            raise SystemExit("git 失败（人话已打印）")

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, rounds=3),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert len(rows) == 1
        assert rows[0]["decision"] == "error" and rows[0]["state"] == "collect_failed"
        assert "git 失败" in rows[0]["reason"]
        assert env.spawned == []

    def test_min_interval_floor_enforced_by_loop(self, cache_root: Path):
        env = _Env()

        def collect():
            return [], _HEAD, _DIGEST, _TESTS

        list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=0.01, rounds=2),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert MIN_INTERVAL_S == 1.0
        assert all(s <= 0.2 + 1e-9 for s in env.sleeps), "interval 下限经分片 sleep 承载"

    def test_watch_e2e_launch_finish_then_cache_hit_query(
        self, cache_root: Path
    ):
        """验收 E（hermetic 端到端）：变更→合并→发射→child 收尾→查询秒回。"""
        env = _Env()
        surface = ["src/rfauto/service/devtest_speculative_service.py"]
        calls = {"n": 0}

        def collect():
            calls["n"] += 1
            if calls["n"] == 1:
                return surface, _HEAD, _DIGEST, _TESTS
            # 窗满复采样：同面收敛（模拟窗口稳定）
            return surface, _HEAD, _DIGEST, _TESTS

        rows = list(
            watch_loop(
                collect, cache_root=cache_root,
                config=_cfg(cache_root, interval_s=1.0, debounce_s=1.0, rounds=1),
                should_stop=lambda: False, sleep_fn=env.sleep, clock=env.clock,
                census_fn=env.census_fn, alive_fn=env.alive, spawn_fn=env.spawn,
                owner_pid=777, sink_path=cache_root / "w.jsonl",
            )
        )
        assert rows[0]["decision"] == "fire" and len(env.spawned) == 1
        fp = rows[0]["fingerprint"]
        cmd = env.spawned[0]
        assert "--child" in cmd and "--cache-root" in cmd
        # fake runner 收尾（真实 child 语义：finish_run 落 summary）
        _finish(cache_root, fp)
        import time as _t

        t0 = _t.perf_counter()
        st = dss.speculative_status(
            surface, tests=_TESTS, head=_HEAD, map_digest=_DIGEST, cache_root=cache_root
        )
        elapsed = _t.perf_counter() - t0
        assert st["state"] == "hit" and st["summary"]["fingerprint"] == fp
        assert elapsed < 1.0, "缓存命中查询秒回（验收 E）"
