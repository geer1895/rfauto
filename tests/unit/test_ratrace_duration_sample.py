"""C14a ratrace 干净补样采样驱动单测（零真机、零网络、零引擎）。

覆盖（登记判据面）：
① schema 行构造与 loader 兼容：build_sample_row/write_duration_sample 产出
   v1 同构档 -> pipeline.duration_calibration.load_duration_sample_json 消费，
   DurationSample 字段映射（wall_s/base_mm/nr_ts_cap_declared/stop_reason/
   adapter/template/grid_tier）逐键核对；触顶行 -> stop_reason=nrts_cap；
② 档位选择逻辑：choose_mesh_tiers 互补 + 预算淘汰（0.2mm 证据墙钟超
   3600s 预算被淘汰 -> 补 0.3/0.4）；已完成档不再重复补；
③ mock 求解链：run_sample 注入假 _run_openems（合成 9 列 sparams/stdout 尾巴
   /et 时间轴）-> 端到端判读+样本行落盘（不碰真机）；
④ 渲染自检：preflight_render_checks 对真实渲染文本通过；注入 EndCriteria
   kwarg / 第二激励口 -> 拒绝；
⑤ refit 侧 id 回贴：_load_duration_samples_with_ids 对合成档（含可跳过行）
   回贴 raw id，键冲突如实抛错；
⑥ 并发隔离纪律（2026-09-22）：他轨 OE 探测模式覆盖各轨宿主进程；自身进程树
   排除（不自匹配）；wait-until-idle 轮询等待 + 超上限 fail-closed；solve 后
   复查见他轨 OE -> isolated=false 如实降级。
真机调用层全部注入（solve_fn/foreign_probe），不碰 openEMS/HFSS/真实 runs/。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rfauto.pipeline.duration_calibration import load_duration_sample_json
from rfauto.pipeline.quota_guard import STOP_REASON_ENERGY, STOP_REASON_NRTS_CAP


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ratrace_duration_sample", SCRIPTS / "ratrace_duration_sample.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_script()


# ─── ① schema 行构造与 loader 兼容 ──────────────────────────────────────────


def _energy_verdict(solve_s: float = 1781.6) -> dict[str, Any]:
    return {
        "item": "c14a_ratrace_clean_sample",
        "judged_at": "2026-09-21 00:00:00",
        "mesh_mm": 0.3,
        "k_applied": 1.120439,
        "excite_port": 1,
        "solve_s": solve_s,
        "center": {"f_center_balance_ghz": 2.5},
        "readout_gates": {"all_pass": True},
        "readout_pass": True,
        "g11": {"ok": True, "verdict": "healthy", "factors": {}},
        "nr_ts_measured": 69784,
        "nr_ts_cap_declared": 100000,
        "hit_nr_ts_cap": False,
        "stop_reason": STOP_REASON_ENERGY,
        "n_cells": 9809293,
        "fdtd_core_s": 1768.23,
        "dt_s": 1.6e-13,
        "t_end_s": 1.14591e-08,
        "et_steps": 72203,
        "sparams_rows": 401,
    }


def test_sample_row_round_trips_through_loader(tmp_path: Path) -> None:
    verdict = _energy_verdict()
    row = mod.build_sample_row(
        sample_id="R11", mesh_mm=0.3, solve_s=1781.6, verdict=verdict,
        source_rel="ratrace_clean_sample_20260921/r11_0p3mm/result.json",
        note="C14a 干净补样")
    path = mod.write_duration_sample(tmp_path, [row])
    loaded = load_duration_sample_json(path)
    assert loaded["skipped"] == []
    assert len(loaded["samples"]) == 1
    sample = loaded["samples"][0]
    assert sample.mesh_mm == pytest.approx(0.3)
    assert sample.solve_s == pytest.approx(1781.6)
    assert sample.nrts_limit == 100000
    assert sample.stop_reason == STOP_REASON_ENERGY
    assert sample.solver == "openems"
    assert sample.template == "ratrace"
    assert sample.grid_tier == "0p3mm"
    assert sample.n_excitations == 1
    assert sample.domain_volume_mm3 == pytest.approx(mod.DOMAIN_VOLUME_MM3)
    assert sample.source.endswith("result.json")
    # 原始行保留 quality/机制字段（v1 field_notes 同构）
    assert row["quality"] == "isolated_single_excitation"
    assert row["hit_nr_ts_cap"] is False
    assert row["nr_ts_measured"] == 69784


def test_sample_row_nrts_cap_maps_to_cap_stop_reason(tmp_path: Path) -> None:
    verdict = _energy_verdict()
    verdict.update({"nr_ts_measured": 100000, "hit_nr_ts_cap": True,
                    "stop_reason": STOP_REASON_NRTS_CAP})
    row = mod.build_sample_row(
        sample_id="R99", mesh_mm=0.2, solve_s=13936.7, verdict=verdict,
        source_rel="x/result.json", note="触顶行")
    path = mod.write_duration_sample(tmp_path, [row])
    sample = load_duration_sample_json(path)["samples"][0]
    assert sample.stop_reason == STOP_REASON_NRTS_CAP
    assert sample.nrts_limit == 100000


# ─── ② 档位选择逻辑 ─────────────────────────────────────────────────────────


def test_choose_mesh_tiers_excludes_over_budget_and_balances() -> None:
    picks = mod.choose_mesh_tiers(
        list(mod.EXISTING_CLEAN_TIERS), n_new=2, per_point_timeout_s=3600.0)
    # 0.2mm 证据墙钟 7681.6/13936.7s > 0.8*3600 -> 淘汰；补 0.3/0.4 成 2/2/2
    assert picks == [0.3, 0.4]


def test_choose_mesh_tiers_respects_explicit_evidence_and_n_new() -> None:
    picks = mod.choose_mesh_tiers(
        [("R1", 0.2)], n_new=1, per_point_timeout_s=3600.0,
        tier_wall_evidence_s={0.4: (99999.0,)})
    assert picks == [0.3]


def test_choose_mesh_tiers_skips_already_filled_tiers_on_resume() -> None:
    done = [*list(mod.EXISTING_CLEAN_TIERS), ("R11", 0.3)]
    picks = mod.choose_mesh_tiers(done, n_new=2, per_point_timeout_s=3600.0)
    assert 0.3 not in picks
    assert picks == [0.4]


def test_label_for_known_and_unknown_tiers() -> None:
    assert mod.label_for(0.3) == "r11_0p3mm"
    assert mod.label_for(0.4) == "r12_0p4mm"
    with pytest.raises(ValueError):
        mod.label_for(0.5)


# ─── ③ mock 求解链（端到端，零真机） ────────────────────────────────────────


def _write_synth_solve_products(work: Path, *, nr_ts: int = 69784,
                                cells: int = 9809293, core_s: float = 1768.23,
                                n_freq: int = 41) -> None:
    """合成 9 列 sparams + stdout 尾巴 + fdtd/et（判读输入齐备）。"""
    freq = np.linspace(2.25e9, 2.75e9, n_freq)
    s11 = 0.05 * np.ones(n_freq, dtype=complex)
    bal = 2.5e9
    weight = np.exp(-((freq - bal) ** 2) / (2 * (30e6) ** 2))
    s21 = (-0.7 + 0.02 * weight) * np.ones(n_freq)
    s41 = (-0.7 + 0.02 * weight) * np.ones(n_freq)  # 全带平衡 -> argmin 首点
    s31 = 0.01 * np.ones(n_freq, dtype=complex)
    data = np.column_stack([
        freq, s11.real, s11.imag, s21.real, s21.imag,
        s31.real, s31.imag, s41.real, s41.imag,
    ])
    header = "freq (Hz),re(S11),im(S11),re(S21),im(S21),re(S31),im(S31),re(S41),im(S41)"
    np.savetxt(work / "sparams.csv", data, delimiter=",", header=header,
               comments="", fmt="%.10e")
    (work / "stdout_tail.txt").write_text(
        f"some log\nTime for {nr_ts} iterations with {cells} cells : "
        f"{core_s} sec\n", encoding="utf-8")
    fdtd = work / "fdtd"
    fdtd.mkdir(parents=True, exist_ok=True)
    dt = 1.6e-13
    t = np.arange(nr_ts + 1) * dt
    et = np.column_stack([t, 1e-3 * np.exp(-t / 1e-8)])
    np.savetxt(fdtd / "et", et, fmt="%.10e")


def test_run_sample_mock_end_to_end(tmp_path: Path) -> None:
    def fake_solve(work: Path, text: str, timeout_s: int):
        assert timeout_s == 1234
        _write_synth_solve_products(work)
        return 1781.6, work / "sparams.csv", ""

    row = mod.run_sample(0.3, tmp_path, timeout_s=1234, solve_fn=fake_solve,
                         foreign_probe=lambda work: [], idle_poll_s=0.001)
    assert row is not None
    assert row["id"] == "R11"
    assert row["base_mm"] == pytest.approx(0.3)
    assert row["wall_s"] == pytest.approx(1781.6)
    assert row["stop_reason"] == STOP_REASON_ENERGY
    assert row["nr_ts_measured"] == 69784
    assert row["quality"] == "isolated_single_excitation"
    # 判读产物在档
    verdict = json.loads((tmp_path / "r11_0p3mm" / "verdict.json").read_text(
        encoding="utf-8"))
    assert verdict["preflight"]["ok"] is True
    assert verdict["g11"]["verdict"]
    assert verdict["sparams_rows"] == 41
    # duration_sample.json 落盘且 loader 可消费
    loaded = load_duration_sample_json(tmp_path / "duration_sample.json")
    assert loaded["skipped"] == []
    assert [s.source for s in loaded["samples"]]


def test_run_sample_records_failed_solve(tmp_path: Path) -> None:
    def failing_solve(work: Path, text: str, timeout_s: int):
        return 12.0, None, "boom"

    row = mod.run_sample(0.3, tmp_path, timeout_s=60, solve_fn=failing_solve,
                         foreign_probe=lambda work: [], idle_poll_s=0.001)
    assert row is None
    result = json.loads((tmp_path / "r11_0p3mm" / "result.json").read_text(
        encoding="utf-8"))
    assert result["stage"] == "failed"
    # 失败样本不入 duration_sample.json（不污染干净档）
    assert mod.read_duration_samples(tmp_path) == []


# ─── ④ 渲染自检 ─────────────────────────────────────────────────────────────


def test_preflight_accepts_real_render_and_rejects_mutations() -> None:
    import ratrace_k_finalize as rkf

    text, _k_applied, base_mm = rkf._render(0.4, 1, None)
    checks = mod.preflight_render_checks(text, base_mm)
    assert checks["ok"] is True, checks["problems"]
    assert checks["nr_ts_declared"] == 100000
    assert checks["excited_ports"] == [1]
    assert checks["has_end_criteria_kwarg"] is False

    bad = text.replace("openEMS(NrTS=100000)",
                       "openEMS(NrTS=100000, EndCriteria=1e-5)", 1)
    assert bad != text
    checks_bad = mod.preflight_render_checks(bad, base_mm)
    assert checks_bad["ok"] is False

    bad2 = text.replace("excite=1 if 1 == 2 else 0",
                        "excite=1 if 1 == 1 else 0", 1)
    assert bad2 != text
    checks_two = mod.preflight_render_checks(bad2, base_mm)
    assert checks_two["ok"] is False
    assert checks_two["excited_ports"] == [1, 1]


# ─── ⑥ 并发隔离纪律（2026-09-22 扩展：探测/等待/自树排除/降级） ───────────────


def test_foreign_pattern_matches_all_oe_host_tracks() -> None:
    pat = mod.OE_FOREIGN_PATTERN
    # 本轨/既有轨 OE 宿主
    assert pat.search(r"python.exe runs\x\_rfauto_runner.py runs\x\simulation.py")
    assert pat.search("python scripts/c3_fullcurve_runner.py run interdigital")
    assert pat.search("python scripts/smoke_c3_filter_family.py --template "
                      "interdigital")
    assert pat.search("python scripts/ratrace_duration_sample.py sample")
    # 无关 python 进程不误伤
    assert not pat.search("python -m pytest tests/unit -q")
    assert not pat.search("python -m ruff check src")


def test_foreign_oe_from_lister_excludes_own_ancestry() -> None:
    rows = [
        (50, 0, "python.exe scripts/ratrace_duration_sample.py sample"),
        (100, 50, "python.exe runs/x/_rfauto_runner.py runs/x/simulation.py"),
        (200, 0, "python.exe scripts/c3_fullcurve_runner.py run interdigital"),
        (300, 0, "python.exe -m pytest -q"),
    ]
    own = mod.own_ancestry_pids(rows, 100)
    assert own == {100, 50, 0}
    foreign = mod.foreign_oe_from_lister(rows, own)
    assert len(foreign) == 1
    assert foreign[0].startswith("200\t")
    assert "c3_fullcurve_runner" in foreign[0]


def test_wait_oe_idle_polls_until_idle() -> None:
    states = iter([
        [(200, 0, "python scripts/smoke_c3_filter_family.py --t interdigital")],
        [(200, 0, "python scripts/smoke_c3_filter_family.py --t interdigital")],
        [],
    ])

    def lister(work: Path):
        return next(states)

    calls: list[str] = []

    def log(msg: str) -> None:
        calls.append(msg)

    out = mod.wait_oe_idle(Path("."), poll_s=0.001, lister=lister, log=log)
    assert out == []
    assert len(calls) == 2  # 忙两次各记一条等待日志


def test_wait_oe_idle_raises_when_busy_beyond_max_wait() -> None:
    def lister(work: Path):
        return [(200, 0, "python scripts/c3_fullcurve_runner.py run")]

    with pytest.raises(RuntimeError, match="隔离优先"):
        mod.wait_oe_idle(Path("."), poll_s=0.001, max_wait_s=0.0,
                         lister=lister, log=lambda msg: None)


def test_run_sample_waits_for_idle_then_solves_isolated(tmp_path: Path) -> None:
    probe_states = iter([
        [(200, 0, "busy c3")],  # solve 前：忙 -> 等待
        [],  # solve 前：空闲 -> 发射
        [],  # solve 后：仍空闲
    ])
    events: list[str] = []

    def probe(work: Path):
        return next(probe_states)

    def fake_solve(work: Path, text: str, timeout_s: int):
        events.append("solve")
        _write_synth_solve_products(work)
        return 756.8, work / "sparams.csv", ""

    row = mod.run_sample(0.4, tmp_path, timeout_s=60, solve_fn=fake_solve,
                         foreign_probe=probe, idle_poll_s=0.001)
    assert events == ["solve"]  # 空闲确认后才发射一次
    assert row is not None
    assert row["isolated"] is True
    assert row["quality"] == "isolated_single_excitation"
    verdict = json.loads((tmp_path / "r12_0p4mm" / "verdict.json").read_text(
        encoding="utf-8"))
    assert verdict["isolation"]["isolated"] is True
    assert verdict["isolation"]["wait_rounds"] == 1  # 忙 1 轮后等待至空闲


def test_run_sample_degrades_when_foreign_after_solve(tmp_path: Path) -> None:
    probe_states = iter([
        [],  # solve 前：空闲
        [(210, 0, "python scripts/c3_fullcurve_runner.py run")],  # solve 后现foreign
    ])

    def fake_solve(work: Path, text: str, timeout_s: int):
        _write_synth_solve_products(work)
        return 756.8, work / "sparams.csv", ""

    row = mod.run_sample(0.4, tmp_path, timeout_s=60, solve_fn=fake_solve,
                         foreign_probe=lambda work: next(probe_states),
                         idle_poll_s=0.001)
    assert row is not None
    assert row["isolated"] is False
    assert row["quality"] == "single_excitation_concurrent_risk"
    assert "isolated=false" in row["note"]


# ─── ⑤ refit 侧 id 回贴 ─────────────────────────────────────────────────────


def test_load_duration_samples_with_ids_round_trip(tmp_path: Path) -> None:
    rows = [
        {"id": "RA", "template": "ratrace", "base_mm": 0.3, "wall_s": 1781.6,
         "nr_ts_cap_declared": 100000, "hit_nr_ts_cap": False,
         "n_excitations": 1, "domain_volume_mm3": 79315.2,
         "grid_tier": "0p3mm", "adapter": "openems"},
        {"id": "BAD", "template": "ratrace", "wall_s": None},  # loader 跳过
        {"id": "RB", "template": "ratrace", "base_mm": 0.4, "wall_s": 756.8,
         "nr_ts_cap_declared": 100000, "hit_nr_ts_cap": False,
         "n_excitations": 1, "domain_volume_mm3": 79315.2,
         "grid_tier": "0p4mm", "adapter": "openems"},
    ]
    path = tmp_path / "duration_sample.json"
    path.write_text(json.dumps(
        {"schema": mod.SCHEMA, "samples": rows}, ensure_ascii=False),
        encoding="utf-8")
    with_ids = mod._load_duration_samples_with_ids(path)
    assert sorted(with_ids) == ["RA", "RB"]
    assert with_ids["RA"]["mesh_mm"] == pytest.approx(0.3)
    assert with_ids["RA"]["stop_reason"] == STOP_REASON_ENERGY
    assert with_ids["RB"]["solve_s"] == pytest.approx(756.8)


def test_load_duration_samples_with_ids_rejects_key_conflict(
        tmp_path: Path) -> None:
    rows = [
        {"id": "RA", "template": "ratrace", "base_mm": 0.3, "wall_s": 100.0,
         "n_excitations": 1, "domain_volume_mm3": 1.0},
        {"id": "RA2", "template": "ratrace", "base_mm": 0.3, "wall_s": 100.0,
         "n_excitations": 1, "domain_volume_mm3": 1.0},
    ]
    path = tmp_path / "duration_sample.json"
    path.write_text(json.dumps({"schema": mod.SCHEMA, "samples": rows}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="键冲突"):
        mod._load_duration_samples_with_ids(path)
