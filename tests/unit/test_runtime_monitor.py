"""service/runtime_monitor_service.py（R8 运行时验证 monitor）测试。

坑账钉位：
- #268：进度只认 port_ut 末行时间轴（构造 mtime 不动、内容增长的场景）；
- #262：激励尾值未衰减=截断嫌疑（yellow，不判非物理）；衰减完=无嫌疑；
- #323：衰减率实测 vs 闭式 e^(−αt) 理论值回收（独立基准）；
- #105：单文件损坏/缺失只降级本项，不传染（其余检查仍出结果）。

全离线：tmp_path 手写 port_ut/et 文本，零网络零引擎依赖。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.service.runtime_monitor_service import monitor_cycle, monitor_run_dir


def _write_series(path: Path, t: np.ndarray, v: np.ndarray) -> None:
    lines = ["% t/s\tvalue"]
    lines += [f"{ti}\t{vi}" for ti, vi in zip(t, v, strict=True)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _excitation(n: int = 200, dt: float = 1e-12, tau: float = 2e-11) -> np.ndarray:
    """高斯脉冲激励，末值已衰减到峰值 1e-8 量级（完整记录口径）。"""
    t = np.arange(n) * dt
    v = np.exp(-((t - 5 * tau) ** 2) / (2 * tau ** 2))
    return t, v


def _decay_tail(
    t_start: float, n: int = 400, dt: float = 1e-12, alpha: float = 1e8,
) -> tuple[np.ndarray, np.ndarray]:
    """v=A·e^(−αt) 衰减尾段：理论衰减率 = 20·log10(e)·α dB/s（闭式）。"""
    t = t_start + np.arange(n) * dt
    v = 1e-3 * np.exp(-alpha * (t - t_start))
    return t, v


class TestProgressPortUt:
    def test_t_last_from_port_ut(self, tmp_path: Path):
        t, v = _excitation()
        _write_series(tmp_path / "port_ut_1A", t, v)
        out = monitor_run_dir(tmp_path)
        assert out["ok"] is True
        assert out["verdict"] == "green"
        assert out["checks"]["progress_t_end_s"] == pytest.approx(t[-1])

    def test_stall_suspect_via_previous_snapshot(self, tmp_path: Path):
        """时间轴不前进（即使文件 mtime 变化）= 停滞嫌疑（#268 钉）。"""
        t, v = _excitation()
        _write_series(tmp_path / "port_ut_1A", t, v)
        first = monitor_run_dir(tmp_path)
        # 模拟"缓冲未刷"：内容不变再次体检（mtime 已变，判据与 mtime 无关）
        (tmp_path / "port_ut_1A").write_text(
            (tmp_path / "port_ut_1A").read_text(encoding="utf-8"),
            encoding="utf-8")
        second = monitor_run_dir(tmp_path, previous=first)
        assert second["verdict"] == "yellow"
        assert any("#268" in r for r in second["reasons"])

    def test_advancing_time_axis_is_green(self, tmp_path: Path):
        t, v = _excitation()
        _write_series(tmp_path / "port_ut_1A", t, v)
        first = monitor_run_dir(tmp_path)
        t2 = t + t[-1]
        _write_series(tmp_path / "port_ut_1A",
                      np.concatenate([t, t2]),
                      np.concatenate([v, v]))
        second = monitor_run_dir(tmp_path, previous=first)
        assert second["verdict"] == "green"

    def test_mtime_never_used(self, tmp_path: Path):
        """判据不读 mtime：os.utime 改时间戳不改变 verdict。"""
        t, v = _excitation()
        _write_series(tmp_path / "port_ut_1A", t, v)
        first = monitor_run_dir(tmp_path)
        import os
        os.utime(tmp_path / "port_ut_1A", (0, 0))
        again = monitor_run_dir(tmp_path, previous=first)
        assert again["checks"]["progress_t_end_s"] == \
            first["checks"]["progress_t_end_s"]


class TestTruncationEt:
    def test_undecayed_excitation_flags_suspect(self, tmp_path: Path):
        """激励末值仍在峰值量级 → 截断嫌疑 yellow（#262 钉）。"""
        n = 200
        dt = 1e-12
        t = np.arange(n) * dt
        v = np.exp(-((t - 5e-11) ** 2) / (2 * (2e-11) ** 2))
        v[-1] = 0.5  # 截断：脉冲中段戛然而止
        _write_series(tmp_path / "et", t, v)
        t_pt, v_pt = _decay_tail(t[-1] + dt)
        _write_series(tmp_path / "port_ut_1A", t_pt, v_pt)
        out = monitor_run_dir(tmp_path)
        assert out["verdict"] == "yellow"
        assert any("#262" in r for r in out["reasons"])
        assert out["checks"]["et_tail_peak_ratio"] > 0.1

    def test_decayed_excitation_no_suspect(self, tmp_path: Path):
        t, v = _excitation()
        _write_series(tmp_path / "et", t, v)
        _write_series(tmp_path / "port_ut_1A", *_decay_tail(t[-1] + 1e-12))
        out = monitor_run_dir(tmp_path)
        assert out["verdict"] == "green"
        assert not any("#262" in r for r in out["reasons"])

    def test_nrts_ceiling_is_red(self, tmp_path: Path):
        t, v = _excitation(n=200)
        _write_series(tmp_path / "et", t, v)
        _write_series(tmp_path / "port_ut_1A", *_decay_tail(t[-1] + 1e-12))
        out = monitor_run_dir(tmp_path, nr_ts=200)
        assert out["verdict"] == "red"
        assert any("NrTS" in r for r in out["reasons"])

    def test_nrts_not_reached_green(self, tmp_path: Path):
        t, v = _excitation(n=200)
        _write_series(tmp_path / "et", t, v)
        _write_series(tmp_path / "port_ut_1A", *_decay_tail(t[-1] + 1e-12))
        out = monitor_run_dir(tmp_path, nr_ts=10000)
        assert out["verdict"] == "green"


class TestEnergyDecay:
    def test_decay_rate_recovery_closed_form(self, tmp_path: Path):
        """e^(−αt) 合成尾段 → 实测衰减率回收闭式 20·log10(e)·α（独立基准）。"""
        alpha = 2.0e8  # 1/s
        t, v = _excitation()
        _write_series(tmp_path / "et", t, v)
        t_pt, v_pt = _decay_tail(t[-1] + 1e-12, alpha=alpha)
        _write_series(tmp_path / "port_ut_1A", t_pt, v_pt)
        out = monitor_run_dir(tmp_path)
        decay = out["checks"]["energy_decay"]
        theory = 20.0 * np.log10(np.e) * alpha * 1e-9  # dB/ns
        assert decay["decay_db_per_ns"] == pytest.approx(theory, rel=0.05)
        assert decay["level"] == "green"

    def test_stagnant_tail_flags_yellow(self, tmp_path: Path):
        """零衰减平尾（高 Q 未收敛/未歇）→ 停滞嫌疑 yellow（#323 口径）。"""
        t, v = _excitation()
        _write_series(tmp_path / "et", t, v)
        t_pt = t[-1] + 1e-12 + np.arange(400) * 1e-12
        v_pt = np.full(400, 1e-5)  # 恒幅：衰减率 0
        _write_series(tmp_path / "port_ut_1A", t_pt, v_pt)
        out = monitor_run_dir(tmp_path)
        assert out["verdict"] == "yellow"
        assert out["checks"]["energy_decay"]["decay_db_per_ns"] == \
            pytest.approx(0.0, abs=1e-12)

    def test_growing_tail_flags_yellow(self, tmp_path: Path):
        t, v = _excitation()
        _write_series(tmp_path / "et", t, v)
        t_pt, v_pt = _decay_tail(t[-1] + 1e-12, alpha=-1e8)  # 负 α=增长
        _write_series(tmp_path / "port_ut_1A", t_pt, v_pt)
        out = monitor_run_dir(tmp_path)
        assert out["verdict"] == "yellow"
        assert out["checks"]["energy_decay"]["decay_db_per_ns"] < 0.0


class TestIsolationAndCycle:
    def test_missing_dir_error_envelope(self, tmp_path: Path):
        out = monitor_run_dir(tmp_path / "nope")
        assert out["ok"] is False

    def test_no_artifacts_unknown(self, tmp_path: Path):
        (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
        out = monitor_run_dir(tmp_path)
        assert out["verdict"] == "unknown"

    def test_corrupt_port_does_not_kill_other_checks(self, tmp_path: Path):
        """坏 port_ut 只降级本文件；et 判据照常出结果（#105 钉）。"""
        (tmp_path / "port_ut_1A").write_text("垃圾数据\n===\n1.0\n",
                                             encoding="utf-8")
        t, v = _excitation()
        v[-1] = 0.6
        _write_series(tmp_path / "et", t, v)
        out = monitor_run_dir(tmp_path)
        assert out["ok"] is True
        assert out["checks"]["ports"]["port_ut_1A"]["status"] == "unreadable"
        assert out["checks"]["et_tail_peak_ratio"] > 0.1

    def test_fdtd_subdir_resolved(self, tmp_path: Path):
        fdtd = tmp_path / "fdtd"
        fdtd.mkdir()
        _write_series(fdtd / "port_ut_1A", *_excitation())
        out = monitor_run_dir(tmp_path)
        assert out["verdict"] == "green"

    def test_monitor_cycle_aggregates(self, tmp_path: Path):
        """周期面：red/yellow/green/无产物目录四类聚合与快照透传。"""
        red = tmp_path / "20261003_red"
        red.mkdir()
        t, v = _excitation(n=200)
        _write_series(red / "et", t, v)
        green = tmp_path / "20261003_green"
        green.mkdir()
        _write_series(green / "port_ut_1A", *_excitation())
        (tmp_path / "not_a_run").mkdir()  # 无产物：不入册
        junk = tmp_path / "junk_dir"
        junk.mkdir()
        (junk / "random.txt").write_text("x", encoding="utf-8")
        cycle = monitor_cycle(tmp_path, nr_ts=200)
        assert cycle["ok"] is True
        assert cycle["n_monitored"] == 2
        assert cycle["red"] == ["20261003_red"]
        assert cycle["yellow"] == []
        assert "20261003_green" in cycle["unknown"]
        assert cycle["snapshots"]["20261003_red"]["verdict"] == "red"
        # 二轮带快照：green 时间轴不动 → 停滞嫌疑透传
        cycle2 = monitor_cycle(tmp_path, previous=cycle, nr_ts=200)
        assert "20261003_green" in cycle2["yellow"]

    def test_monitor_cycle_missing_root(self, tmp_path: Path):
        out = monitor_cycle(tmp_path / "nope")
        assert out["ok"] is False
