"""c3 全收敛档两阶段 runner 单测（零真机、零网络、零引擎）。

覆盖（criteria_a.md 判据面）：
① 衰减率→NrTS 合成回收：已知 α 注入合成环振 → 内核 extract_ring_modes 回收
   α → compute_stage2_plan 回收步数（相对注入真值 ≤5%）；
② NrTS 公式锚 budget_replan §二算例（163654 步/−13dB/0.28dB/ns → ~1.37e6 步、
   wall_pred ~11.75h、预算帽 ~17.6h）；帽停点/激励步数下限；帽内收敛分支；
③ 引擎能量尾段斜率解析（线性注入回收）；combline blocked 判据；
④ 前哨门（置信三面 + S21∞@f0 ≥−3dB 语义切换，S11∞ 降级记录量）；
⑤ plan.json 预声明不可变（stage1/stage2 声明块一次写入、不等价拒绝、
   build_plan 已在档跳过/名义不一致 fail-closed）；断点续跑幂等（完成标记
   在档跳过发射）；stage1/stage2 端到端离线编排（合成引擎 mock，含 stage2
   G1-G4 判读 PASS/预算超帽 PARTIAL/G0 未收敛 FAIL_NOT_CONVERGED）。
真机调用层全部 mock（launch_fn/guard 注入），不碰 openEMS/HFSS。
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = _load_script("c3_fullcurve_runner")

from rfauto.adapters import openems_templates as ot
from rfauto.adapters.openems_templates import (
    TEMPLATE_NOMINAL,
    c3_circuit_sparams,
)

T = "interdigital"
H_MM = 0.508

# ─── 合成环振（已知 α 注入；口径同 test_c3_q_extract）──────────────────────────
DT_ROW = 45.35e-12
T_EXC = 1.14593e-8                     # refix 引擎实测激励时长
# (f_hz, alpha_per_s, r1, r2, phase)：f=2.50 主模保证 S21∞@f0 带内量级（前哨门）
MODES_MATCH = [
    (2.50e9, 4.00e7, 0.30, 0.25, 0.7),
    (2.40e9, 3.77e7, 0.20, 0.15, 2.1),
    (2.62e9, 4.50e7, 0.10, 0.08, 4.0),
]
ALPHA_MIN_S = min(m[1] for m in MODES_MATCH)          # 3.77e7 → 0.0377/ns
MODES_MISMATCH = [                                     # f0=2.5 无模（S21∞@f0 ≪ −3dB）
    (2.38e9, 3.77e7, 0.30, 0.25, 0.7),
    (2.58e9, 4.20e7, 0.22, 0.18, 2.1),
    (2.70e9, 4.50e7, 0.10, 0.08, 4.0),
]


def _synth_ports(t_end_s: float, modes: list[tuple]) -> tuple[np.ndarray, dict]:
    t = np.arange(0.0, t_end_s, DT_ROW)
    a = np.exp(-((t - T_EXC / 2) / (T_EXC / 5)) ** 2) * np.cos(2 * np.pi * 2.46e9 * t)

    def ring(amps: list[float]) -> np.ndarray:
        out = np.zeros_like(t)
        for (f_hz, al, _r1, _r2, ph), amp in zip(modes, amps, strict=True):
            tp = t - T_EXC
            m = tp >= 0
            out[m] += amp * np.exp(-al * tp[m]) * np.cos(2 * np.pi * f_hz * tp[m] + ph)
        return out

    b1 = ring([m[2] for m in modes])
    b2 = ring([m[3] for m in modes])
    probes = {1: (a + b1, (a - b1) / 50.0), 2: (b2, -b2 / 50.0)}
    return t, probes


def _write_probes(work: Path, t: np.ndarray, probes: dict) -> None:
    fdtd = work / "fdtd"
    fdtd.mkdir(parents=True, exist_ok=True)
    u1, i1 = probes[1]
    u2, i2 = probes[2]
    for name, v in (("port_ut_1A", u1), ("port_ut_1B", u1), ("port_ut_1C", u1),
                    ("port_it_1A", i1), ("port_it_1B", i1),
                    ("port_ut_2A", u2), ("port_ut_2B", u2), ("port_ut_2C", u2),
                    ("port_it_2A", i2), ("port_it_2B", i2)):
        arr = np.column_stack([t, v])
        np.savetxt(fdtd / name, arr, header="t/s voltage", comments="%")


def _engine_log(dt_s: float, exc_steps: int, done_steps: int, wall_s: float,
                e0_db: float = -4.0, slope_db_per_ns: float = 0.4,
                t_exc_s: float = T_EXC, terminated: bool = True) -> str:
    """合成引擎日志：头部 + 激励后能量线性衰减进度行 + 终止行。

    terminated=False = 帽停形态（引擎被 --timeout 杀死，无 "Time for N
    iterations" 终止行 → parse_engine_log 无 iterations_done/engine_wall_s，
    步数锚只能取末进度行 last_progress_step）。
    """
    lines = [
        "FDTD simulation size: 499x1083x23 --> 1.24e+07 FDTD cells ",
        f"FDTD timestep is: {dt_s:.5e} s; Nyquist rate: 1310 timesteps @2.75e+09 Hz",
        f"Excitation signal length is: {exc_steps} timesteps ({t_exc_s:.5e}s)",
        "Max. number of timesteps: 1000000 ( --> 12.1 * Excitation signal length)",
    ]
    t_exc_ns = t_exc_s * 1e9
    for step in range(90000, done_steps + 1, 1000):
        t_ns = step * dt_s * 1e9
        e_db = e0_db - slope_db_per_ns * (t_ns - t_exc_ns)
        lines.append(f"Timestep: {step} || Progress: 16.4% | "
                     f"Energy: ~1.0e-03 ({e_db:.2f}dB)")
    if terminated:
        lines.append(f"Time for {done_steps} iterations with 1.24e+07 cells : "
                     f"{wall_s:.1f} sec")
    return "\n".join(lines) + "\n"


def _make_plan(root: Path, templates: tuple[str, ...] = ("combline", "interdigital",
                                                        "sir_bpf")) -> None:
    root.mkdir(parents=True, exist_ok=True)
    plan = {"batch": "smoke_c3_fullcurve", "criteria": runner.CRITERIA_A,
            "templates": {t: {} for t in templates}}
    runner._plan_write(plan, root)


def _declare_stage1(root: Path, template: str = T, **overrides) -> dict:
    payload = {
        "alpha_min_per_ns": ALPHA_MIN_S * 1e-9,        # 0.0377/ns
        "rate_kernel_db_per_ns": runner.energy_rate_from_alpha(ALPHA_MIN_S * 1e-9),
        "rate_engine_db_per_ns": 0.4,
        "e_cap_db": -8.08, "iterations_done": 163654, "dt_s": 1.38713e-13,
        "excitation_steps": 82611, "solve_s": 5040.0,
        "sentinel_ok": True, "verdict": "SENTINEL_PASS",
    }
    payload.update(overrides)
    return runner.declare_block(template, "stage1", payload, root)


def _write_stage2_success(work: Path, solve_s: float = 42000.0) -> None:
    work.mkdir(parents=True, exist_ok=True)
    f = np.linspace(2.25e9, 2.75e9, 401)
    nominal = dict(TEMPLATE_NOMINAL[T])
    s = c3_circuit_sparams(T, f / 1e9, nominal, synchronous_tem=False,
                           h_mm=H_MM, l_via_h=None)
    head = "freq_hz,re_S11,im_S11,re_S21,im_S21"
    arr = np.column_stack([f, s[:, 0, 0].real, s[:, 0, 0].imag,
                           s[:, 1, 0].real, s[:, 1, 0].imag])
    np.savetxt(work / "sparams.csv", arr, delimiter=",", header=head,
               comments="", fmt="%.10e")
    result = {"template": T, "nrts": 1649093, "mesh_mm": 0.301,
              "solve_s": solve_s, "rc": 0,
              "engine": {"nrts": 1649093, "iterations_done": 900000,
                         "hit_nrts_limit": False, "excitation_covered": True,
                         "min_energy_db": -60.42, "dt_s": 1.38713e-13,
                         "excitation_steps": 82611,
                         "excitation_s": T_EXC, "engine_wall_s": solve_s}}
    (work / "_smoke_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


# ─── ② NrTS 公式（锚 budget_replan 算例）与下限/收敛分支 ───────────────────────

class TestComputeStage2Plan:
    def test_budget_replan_example_recovery(self):
        """163654 步/−13dB/0.28dB/ns → 全程 ~1.37e6 步、wall_pred ~11.75h、
        帽 ~17.6h（budget_replan §二算例的公式级回收；数值本身禁用于新设计）。"""
        p = runner.compute_stage2_plan(
            dt_s=1.38713e-13, iterations_done=163654, excitation_steps=82611,
            e_cap_db=-13.0, alpha_min_per_ns=0.03031472112374481,
            rate_engine_db_per_ns=0.28, stage1_wall_s=5040.0)
        assert p["converged_in_stage1"] is False
        assert p["rate_used_db_per_ns"] == pytest.approx(0.28)   # 慢者
        t_exp = 163654 * 1.38713e-13 + 47.0 / 0.28 * 1e-9
        assert p["t_full_s"] == pytest.approx(t_exp, abs=1e-15)
        assert p["nrts_pred"] == math.ceil(t_exp / 1.38713e-13)
        assert 1.30e6 <= p["nrts_pred"] <= 1.45e6               # ~1.35e6 文档值
        assert p["nrts"] == max(math.ceil(1.5 * p["nrts_pred"]), 163654)
        assert p["floor_steps"] == 163654
        assert 11.0 <= p["wall_pred_s"] / 3600 <= 12.5           # ~11.6h 文档值
        assert 16.0 <= p["budget_wall_s"] / 3600 <= 19.0         # ~18h 硬帽

    def test_slower_rate_gives_larger_nrts(self):
        common = dict(dt_s=1.38713e-13, iterations_done=163654,
                      excitation_steps=82611, e_cap_db=-13.0,
                      stage1_wall_s=5040.0)
        fast = runner.compute_stage2_plan(alpha_min_per_ns=0.5,
                                          rate_engine_db_per_ns=None, **common)
        slow = runner.compute_stage2_plan(alpha_min_per_ns=0.5,
                                          rate_engine_db_per_ns=0.28, **common)
        assert slow["rate_used_db_per_ns"] == 0.28
        assert slow["nrts"] > fast["nrts"]                       # 慢者=保守长预测

    def test_floor_binds_for_short_cap_and_excitation(self):
        p = runner.compute_stage2_plan(
            dt_s=1.38713e-13, iterations_done=5000, excitation_steps=82611,
            e_cap_db=-4.0, alpha_min_per_ns=1.0, rate_engine_db_per_ns=None,
            stage1_wall_s=10.0)
        assert p["floor_steps"] == 82611                         # 激励步数下限
        assert p["t_full_s"] >= 82611 * 1.38713e-13              # ≥ 激励结束时刻
        assert p["nrts"] >= 82611

    def test_converged_in_stage1_branch(self):
        p = runner.compute_stage2_plan(
            dt_s=1.38713e-13, iterations_done=163654, excitation_steps=82611,
            e_cap_db=-60.5, alpha_min_per_ns=0.0377,
            rate_engine_db_per_ns=0.28, stage1_wall_s=5040.0)
        assert p["converged_in_stage1"] is True
        assert p["nrts"] is None and p["budget_wall_s"] is None

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError):
            runner.compute_stage2_plan(dt_s=0.0, iterations_done=1,
                                       excitation_steps=1, e_cap_db=-13.0,
                                       alpha_min_per_ns=0.1,
                                       rate_engine_db_per_ns=None,
                                       stage1_wall_s=1.0)
        with pytest.raises(ValueError):
            runner.compute_stage2_plan(dt_s=1e-13, iterations_done=0,
                                       excitation_steps=1, e_cap_db=-13.0,
                                       alpha_min_per_ns=0.1,
                                       rate_engine_db_per_ns=None,
                                       stage1_wall_s=1.0)
        with pytest.raises(ValueError):
            runner.energy_rate_from_alpha(-1.0)


class TestSyntheticAlphaToNrtsRecovery:
    def test_known_decay_injection_recovers_step_count(self):
        """已知 α 注入合成环振 → 内核回收 α → NrTS 回收（相对注入真值 ≤5%）。"""
        t, probes = _synth_ports(T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)
        modes = _modes_of(t, probes)
        assert modes, "合成环振须可提取模式"
        alpha_rec_ns = min(float(m["alpha_per_s"]) * 1e-9 for m in modes)
        assert alpha_rec_ns == pytest.approx(ALPHA_MIN_S * 1e-9, rel=0.04)

        def nrts_of(alpha_ns: float) -> int:
            return runner.compute_stage2_plan(
                dt_s=1.38713e-13, iterations_done=163654,
                excitation_steps=82611, e_cap_db=-13.0,
                alpha_min_per_ns=alpha_ns, rate_engine_db_per_ns=0.28,
                stage1_wall_s=5040.0)["nrts"]

        assert nrts_of(alpha_rec_ns) == pytest.approx(
            nrts_of(ALPHA_MIN_S * 1e-9), rel=0.05)


def _modes_of(t: np.ndarray, probes: dict) -> list[dict]:
    from c3_resonance_q_extract import extract_ring_modes
    return extract_ring_modes(t, probes[1][0], 2.25e9, 2.75e9, T_EXC)


# ─── ③ 引擎能量尾段斜率 / blocked 判据 ─────────────────────────────────────────

class TestEngineTailRate:
    def test_linear_injection_recovery(self):
        log = _engine_log(1.38713e-13, 82611, 163654, 5040.0,
                          e0_db=-4.0, slope_db_per_ns=0.4)
        rate = runner.engine_energy_tail_rate(log, 1.38713e-13, T_EXC)
        assert rate == pytest.approx(0.4, abs=5e-3)

    def test_insufficient_points_or_span_returns_none(self):
        log = _engine_log(1.38713e-13, 82611, 163654, 5040.0,
                          e0_db=-4.0, slope_db_per_ns=0.05)   # 跨度 <3dB
        assert runner.engine_energy_tail_rate(log, 1.38713e-13, T_EXC) is None
        short = _engine_log(1.38713e-13, 82611, 91000, 5040.0,   # 仅 2 个激励后点
                            e0_db=-4.0, slope_db_per_ns=0.4)
        assert runner.engine_energy_tail_rate(short, 1.38713e-13, T_EXC) is None
        assert runner.engine_energy_tail_rate("no progress lines", 1e-13, 0.0) is None
        assert runner.engine_energy_tail_rate("x", -1.0, 0.0) is None


class TestBlockedRule:
    def test_combline_blocked_after_4h_hot_energy(self):
        chk = runner.blocked_check("combline", 4.0 * 3600 + 1, -5.0)
        assert chk["applicable"] is True and chk["blocked"] is True
        chk2 = runner.blocked_check("combline", 4.0 * 3600 + 1, -10.0)
        assert chk2["blocked"] is False                      # −10dB 不越 −10 门
        chk3 = runner.blocked_check("combline", 4.0 * 3600 + 1, -12.0)
        assert chk3["blocked"] is False

    def test_before_checkpoint_or_unreadable_or_other_template(self):
        assert runner.blocked_check("combline", 3600.0, -5.0)["blocked"] is False
        assert runner.blocked_check("combline", 5 * 3600.0, None)["blocked"] is False
        other = runner.blocked_check("interdigital", 5 * 3600.0, -5.0)
        assert other["applicable"] is False and other["blocked"] is False


# ─── ④ 前哨门（S11∞ 语义切换：S11∞ 降级记录量，判据=S21∞@f0）──────────────────

class TestSentinelGate:
    def test_pass_confident_and_inband(self):
        g = runner.sentinel_gate({"ok": True, "reasons": []}, -2.5)
        assert g["ok"] is True and g["conf_ok"] and g["s21_ok"]
        assert g["thresholds"]["s21_inf_f0_min_db"] == -3.0

    def test_fail_out_of_band_even_if_confident(self):
        """旧失配指纹（S21∞@f0 ≪−3dB，如 qextrap 档 −14.23dB）→ 前哨 FAIL。"""
        g = runner.sentinel_gate({"ok": True, "reasons": []}, -14.23)
        assert g["ok"] is False and g["s21_ok"] is False
        assert any("S21∞@f0" in r for r in g["reasons"])

    def test_fail_unconfident_or_missing(self):
        g = runner.sentinel_gate({"ok": False, "reasons": ["span 12dB < 20dB"]}, -2.0)
        assert g["ok"] is False and len(g["reasons"]) == 1
        g2 = runner.sentinel_gate({"ok": True, "reasons": []}, None)
        assert g2["ok"] is False
        g3 = runner.sentinel_gate(None, -2.0)
        assert g3["ok"] is False and g3["conf_ok"] is False


# ─── ⑤ plan 预声明不可变 / 命令构造 / 名义一致性 ───────────────────────────────

class TestPlanImmutability:
    def test_declare_once_then_conflict_refused(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        p1 = runner.declare_block(T, "stage2", {"nrts": 100, "budget_wall_s": 9.0},
                                  root)
        assert "declared_utc" in p1
        same = runner.declare_block(T, "stage2",
                                    {"budget_wall_s": 9.0, "nrts": 100}, root)
        assert same["nrts"] == 100                            # 等价幂等
        plan = runner._plan_load(root)
        with pytest.raises(ValueError):
            runner.declare_block(T, "stage2", {"nrts": 999, "budget_wall_s": 9.0},
                                 root)
        assert runner._plan_load(root)["templates"][T]["stage2"]["nrts"] == 100
        assert plan["templates"][T]["stage2"]["nrts"] == 100   # 预声明后不可变

    def test_declare_stage1_measured_block_conflict_refused(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        runner.declare_block(T, "stage1", {"alpha_min_per_ns": 0.0377}, root)
        with pytest.raises(ValueError):
            runner.declare_block(T, "stage1", {"alpha_min_per_ns": 0.9}, root)

    def test_build_plan_skips_existing(self, tmp_path, monkeypatch):
        root = tmp_path / "runs"
        _make_plan(root, ("combline", "interdigital", "sir_bpf"))
        plan, wrote = runner.build_plan(root)
        assert wrote is False
        assert "templates" in plan

    def test_build_plan_force_with_mocked_base(self, tmp_path, monkeypatch):
        root = tmp_path / "runs"
        _make_plan(root, ("combline", "interdigital", "sir_bpf"))

        def fake_base(template: str, nominals_path=None) -> dict:
            return {"template": template, "nominal_matches_redesign": True,
                    "mesh_mm": 0.301, "mesh_max_mm": 0.3017,
                    "grid": {"n_x": 2, "n_y": 2, "n_z": 2, "n_cells": 8,
                             "min_gap_um_all": 10.0},
                    "dt_cfl_estimate_s": 1.4e-13, "dt_est_vs_ref_ratio": 0.98,
                    "n_excitation_steps_est": 81000, "nrts_floor_estimate": 81000,
                    "stage1": None, "stage2": None}

        monkeypatch.setattr(runner, "plan_base_for", fake_base)
        plan, wrote = runner.build_plan(root, force=True)
        assert wrote is True
        assert plan["templates"][T]["nominal_matches_redesign"] is True

    def test_build_plan_failclosed_on_nominal_mismatch(self, tmp_path, monkeypatch):
        root = tmp_path / "runs"

        def fake_base(template: str, nominals_path=None) -> dict:
            return {"template": template, "nominal_matches_redesign": False}

        monkeypatch.setattr(runner, "plan_base_for", fake_base)
        with pytest.raises(ValueError, match="禁混用设计口径"):
            runner.build_plan(root, force=True)

    def test_registered_nominal_matches_redesign_doc(self):
        """真面一致性钉（当轮口径）：TEMPLATE_NOMINAL 与设计链
        l_via_h=None（auto=校准值 0.125nH）再生名义 4 位舍入一致（经 doc 参数
        注入，脱 runs/ 存档依赖）；--plan fail-closed 机制面用篡改 doc 钉
        （改任一在册几何键 → 不一致）。"""
        designers = {"interdigital": ot.interdigital_design_from_order,
                     "combline": ot.combline_design_from_order,
                     "sir_bpf": ot.sir_bpf_design_from_order}
        keys = {"interdigital": ("order", "w_mm", "res_len_mm", "gaps_mm",
                                 "feed_len_mm"),
                "combline": ("order", "w_mm", "res_len_mm", "gaps_mm",
                             "feed_len_mm", "c_load_pf"),
                "sir_bpf": ("order", "w_feed_mm", "w_low_mm", "w_high_mm",
                            "l_low_mm", "l_high_mm", "gaps_mm", "feed_len_mm")}
        for t in ("combline", "interdigital", "sir_bpf"):
            design = designers[t](3, 2.5, 0.05, 20.0, l_via_h=None)
            new_nominal = {k: design[k] for k in keys[t]}
            doc = {"templates": {t: {"new_nominal": new_nominal}}}
            assert runner._nominal_matches_redesign(
                t, dict(TEMPLATE_NOMINAL[t]), doc) is True
            bad_key = "l_high_mm" if t == "sir_bpf" else "res_len_mm"
            assert runner._nominal_matches_redesign(
                t, dict(TEMPLATE_NOMINAL[t], **{bad_key: 1.0}), doc) is False


class TestStageCmd:
    def test_stage1_cmd_shape(self):
        cmd = runner.stage_cmd(T, "stage1", runner.STAGE1_TIMEOUT_S)
        text = " ".join(cmd)
        assert "--q-extrap" in cmd and "--nrts" not in cmd
        assert "--end-criteria" not in cmd                   # 引擎缺省 −60dB 不动
        assert f"{T}/stage1" in text
        assert "5040.0" in text
        assert str(runner.ROOT) in text

    def test_stage2_cmd_carries_nrts(self, tmp_path):
        cmd = runner.stage_cmd(T, "stage2", 48000.0, nrts=1649093, root=tmp_path)
        assert cmd[cmd.index("--nrts") + 1] == "1649093"
        assert "--end-criteria" not in cmd
        assert str(tmp_path) in " ".join(cmd)

    def test_stage_cmd_param_errors(self):
        with pytest.raises(ValueError):
            runner.stage_cmd(T, "stage2", 100.0, nrts=None)
        with pytest.raises(ValueError):
            runner.stage_cmd(T, "stage1", 100.0, nrts=1000)


# ─── stage1/stage2 端到端离线编排（合成引擎 mock）──────────────────────────────

class TestStage1EndToEnd:
    def test_launch_summarize_declare_and_resume(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        t, probes = _synth_ports(T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)
        calls: list[list[str]] = []

        def fake_launch(cmd, timeout_s, cwd):
            calls.append(cmd)
            (work / "engine.log").write_text(
                _engine_log(1.38713e-13, 82611, 163654, 5040.0), encoding="utf-8")
            _write_probes(work, t, probes)
            return {"rc": 0, "killed": None}

        summary = runner.run_stage1(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert len(calls) == 1
        assert summary["verdict"] == "SENTINEL_PASS"
        assert summary["sentinel"]["ok"] is True
        assert summary["alpha_min_per_ns"] == pytest.approx(ALPHA_MIN_S * 1e-9,
                                                            rel=0.04)
        assert summary["rate_engine_db_per_ns"] == pytest.approx(0.4, abs=5e-3)
        assert summary["rate_kernel_db_per_ns"] == pytest.approx(
            runner.ENERGY_RATE_PER_ALPHA_NS * ALPHA_MIN_S * 1e-9, rel=0.04)
        eng = summary["engine"]
        assert eng["iterations_done"] == 163654 and eng["dt_s"] == pytest.approx(
            1.38713e-13)
        plan = runner._plan_load(root)
        s1 = plan["templates"][T]["stage1"]
        assert s1 is not None and s1["sentinel_ok"] is True
        # 断点续跑：完成标记在档 → 不再发射
        again = runner.run_stage1(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert len(calls) == 1
        assert again["verdict"] == "SENTINEL_PASS"

    def test_sentinel_fail_on_mismatched_design(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        t, probes = _synth_ports(T_EXC + 4.0 / ALPHA_MIN_S, MODES_MISMATCH)

        def fake_launch(cmd, timeout_s, cwd):
            (work / "engine.log").write_text(
                _engine_log(1.38713e-13, 82611, 163654, 5040.0), encoding="utf-8")
            _write_probes(work, t, probes)
            return {"rc": 0, "killed": None}

        summary = runner.run_stage1(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert summary["verdict"] == "SENTINEL_FAIL"
        assert summary["sentinel"]["s21_ok"] is False
        plan = runner._plan_load(root)
        assert plan["templates"][T]["stage1"]["sentinel_ok"] is False
        # 前哨 FAIL → stage2 拒绝放行
        out = runner.run_stage2(T, root, launch_fn=lambda **kw: (_ for _ in ()).throw(
            AssertionError("前哨 FAIL 不许发射 stage2")), guard=lambda: [])
        assert out["verdict"] == "REFUSED"

    def test_261_guard_refuses_before_launch(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        out = runner.run_stage1(T, root, guard=lambda: ["123\tsimulation.py"])
        assert out["verdict"] == "REFUSED"


class TestStage2EndToEnd:
    def _prepare(self, root: Path) -> None:
        _make_plan(root)
        _declare_stage1(root)

    def test_declare_launch_judge_pass_and_resume(self, tmp_path):
        if not runner.CPASS_PATH.exists():
            pytest.skip("runs/smoke_c3_redesign/cpass_verdict.json 归档不在"
                        "（pred_stored_cpass_pct 交叉钉依赖真机存档）")
        root = tmp_path / "runs"
        self._prepare(root)
        calls: list[dict] = []

        def fake_launch(cmd, work=None, template=None, timeout_s=None,
                        budget_s=None, cwd=None):
            calls.append({"cmd": cmd, "budget_s": budget_s})
            _write_stage2_success(work)
            return {"rc": 0, "killed": None}

        out = runner.run_stage2(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert len(calls) == 1
        plan = runner._plan_load(root)
        s2 = plan["templates"][T]["stage2"]
        nrts = s2["nrts"]
        assert nrts is not None and nrts >= s2["floor_steps"] >= 163654
        assert nrts == max(math.ceil(1.5 * s2["nrts_pred"]), s2["floor_steps"])
        assert calls[0]["cmd"][calls[0]["cmd"].index("--nrts") + 1] == str(nrts)
        assert "--end-criteria" not in calls[0]["cmd"]
        assert calls[0]["budget_s"] == pytest.approx(s2["budget_wall_s"])
        # G1-G4：EM=当轮电路裁判 → dev 0；verdict PASS
        assert out["verdict"] == "PASS"
        assert out["G1_peak_shift"]["status"] == "PASS"
        assert out["G1_peak_shift"]["abs_dev_pt"] == pytest.approx(0.0, abs=1e-9)
        assert out["G1_peak_shift"]["pred_stored_cpass_pct"] == pytest.approx(0.0,
                                                                             abs=1e-9)
        assert out["G2_il_rl"]["status"] == "PASS"
        assert out["G0_converged"]["ok"] is True
        assert out["budget"]["over_budget"] is False
        # 断点续跑：已判读 → 不再发射
        again = runner.run_stage2(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert len(calls) == 1
        assert again["verdict"] == "PASS"

    def test_nrts_declaration_immutable_across_rerun(self, tmp_path):
        root = tmp_path / "runs"
        self._prepare(root)
        n_calls = 0

        def fake_launch(cmd, work=None, template=None, timeout_s=None,
                        budget_s=None, cwd=None):
            nonlocal n_calls
            n_calls += 1
            _write_stage2_success(work)
            return {"rc": 0, "killed": None}

        first = runner.run_stage2(T, root, launch_fn=fake_launch, guard=lambda: [])
        nrts1 = runner._plan_load(root)["templates"][T]["stage2"]["nrts"]
        # 输入面被换成另一套 stage1 测量：已声明的 stage2 NrTS 不得被改数
        with pytest.raises(ValueError):
            runner.declare_block(T, "stage1", {"alpha_min_per_ns": 9.9}, root)
        assert n_calls == 1
        assert first["verdict"] == "PASS"
        assert runner._plan_load(root)["templates"][T]["stage2"]["nrts"] == nrts1

    def test_over_budget_caps_pass_to_partial(self, tmp_path):
        root = tmp_path / "runs"
        self._prepare(root)

        def fake_launch(cmd, work=None, template=None, timeout_s=None,
                        budget_s=None, cwd=None):
            _write_stage2_success(work, solve_s=60000.0)     # > 预算帽 ~50.8k s
            return {"rc": 0, "killed": None}

        out = runner.run_stage2(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert out["verdict"] == "PARTIAL"
        assert out["budget"]["over_budget"] is True
        assert out["G1_peak_shift"]["status"] == "PASS"      # 门照算，只压整体

    def test_g0_ceiling_is_fail_not_converged(self, tmp_path):
        root = tmp_path / "runs"
        self._prepare(root)

        def fake_launch(cmd, work=None, template=None, timeout_s=None,
                        budget_s=None, cwd=None):
            _write_stage2_success(work)
            result = json.loads((work / "_smoke_result.json").read_text(
                encoding="utf-8"))
            result["engine"].update({"hit_nrts_limit": True,
                                     "iterations_done": result["nrts"],
                                     "min_energy_db": -46.0})
            (work / "_smoke_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            return {"rc": 0, "killed": None}

        out = runner.run_stage2(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert out["verdict"] == "FAIL_NOT_CONVERGED"        # 旧规：触顶不采信
        assert out["G1_peak_shift"]["status"] == "PASS"      # 其余门照算只记录

    def test_blocked_kill_writes_snapshot_and_verdict(self, tmp_path):
        root = tmp_path / "runs"
        self._prepare(root)
        work = runner.stage_dir(T, "stage2", root)

        def fake_launch(cmd, work=None, template=None, timeout_s=None,
                        budget_s=None, cwd=None):
            (work / "_stage2_result.json").write_text(json.dumps({
                "template": T, "verdict": "FAIL_NOT_CONVERGED",
                "killed": "blocked", "blocked_reason": "4h 后能量 −5dB > −10dB",
                "snapshot": {"port_ut_t_end_s": 1.2e-7,
                             "last_energy_db": -5.0}}), encoding="utf-8")
            return {"rc": None, "killed": "blocked",
                    "blocked_reason": "4h 后能量 −5dB > −10dB"}

        out = runner.run_stage2(T, root, launch_fn=fake_launch, guard=lambda: [])
        assert out["verdict"] == "FAIL_NOT_CONVERGED"
        assert out["killed"] == "blocked"
        judged = json.loads((work / "_judge_a.json").read_text(encoding="utf-8"))
        assert judged["verdict"] == "FAIL_NOT_CONVERGED"


# ─── 2① stage1 帽值落痕 / 2② band_center_3db 脚本内实现（杂项批）──────────

class TestStage1CapTrace:
    def test_default_cap_recorded_explicitly(self, tmp_path):
        """缺省 5040 也显式落 summary（--stage1-cap-s 生效值不落痕修复）。"""
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        t, probes = _synth_ports(T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)

        def fake_launch(cmd, timeout_s, cwd):
            assert "5040.0" in " ".join(cmd)
            (work / "engine.log").write_text(
                _engine_log(1.38713e-13, 82611, 163654, 5040.0), encoding="utf-8")
            _write_probes(work, t, probes)
            return {"rc": 0, "killed": None}

        summary = runner.run_stage1(T, root, launch_fn=fake_launch,
                                    guard=lambda: [])
        assert summary["stage1_cap_s"] == pytest.approx(runner.STAGE1_TIMEOUT_S)
        disk = json.loads((work / "_stage1_summary.json").read_text(
            encoding="utf-8"))
        assert disk["stage1_cap_s"] == pytest.approx(runner.STAGE1_TIMEOUT_S)

    def test_custom_cap_recorded_in_summary_and_verdict(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        t, probes = _synth_ports(T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)

        def fake_launch(cmd, timeout_s, cwd):
            assert "6000.0" in " ".join(cmd)          # 发射命令吃到生效帽
            (work / "engine.log").write_text(
                _engine_log(1.38713e-13, 82611, 163654, 5040.0), encoding="utf-8")
            _write_probes(work, t, probes)
            return {"rc": 1, "killed": None, "elapsed_s": 6001.0,
                    "stdout_tail": "", "stderr_tail": ""}   # 帽停形态

        summary = runner.run_stage1(T, root, launch_fn=fake_launch,
                                    guard=lambda: [], cap_s=6000.0)
        assert summary["stage1_cap_s"] == pytest.approx(6000.0)
        vdoc = summary["stage1_verdict"]
        assert vdoc["stage1_cap_s"] == pytest.approx(6000.0)
        disk = json.loads((work / "stage1_verdict.json").read_text(
            encoding="utf-8"))
        assert disk["stage1_cap_s"] == pytest.approx(6000.0)

    def test_offline_replay_preserves_prior_cap(self, tmp_path):
        """离线重放（--judge-stage1 形态）：summary 在档 cap 优先保留原 run 落痕。"""
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        work.mkdir(parents=True, exist_ok=True)
        t, probes = _synth_ports(T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)
        (work / "engine.log").write_text(
            _engine_log(1.38713e-13, 82611, 163654, 5040.0), encoding="utf-8")
        _write_probes(work, t, probes)
        (work / "_stage1_summary.json").write_text(
            json.dumps({"stage1_cap_s": 7200.0}), encoding="utf-8")
        summary = runner.summarize_stage1(T, root)
        assert summary["stage1_cap_s"] == pytest.approx(7200.0)
        # 全无凭据（无在档）→ 缺省帽值注记
        (work / "_stage1_summary.json").unlink()
        summary2 = runner.summarize_stage1(T, root)
        assert summary2["stage1_cap_s"] == pytest.approx(runner.STAGE1_TIMEOUT_S)

    def test_quick_exit_verdict_records_cap_when_given(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        vdoc = runner.stage1_partial_verdict(
            T, root, outcome={"rc": 1, "killed": None, "elapsed_s": 10.0},
            cap_s=6000.0)
        assert vdoc["fail_kind"] == "crash"
        assert vdoc["stage1_cap_s"] == pytest.approx(6000.0)


class TestBandCenter3db:
    def test_flat_band_known_values(self):
        f = np.linspace(2.25, 2.75, 501)
        s_db = np.full_like(f, -40.0)
        m = np.abs(f - 2.5) <= 0.05                  # 平顶 −3dB 带 0.1GHz
        s_db[m] = -1.0
        bc = runner.band_center_3db(f, s_db)
        assert bc["f_center_3db_ghz"] == pytest.approx(2.5, abs=1e-12)
        assert bc["f_lo_ghz"] == pytest.approx(2.45, abs=1e-9)
        assert bc["f_hi_ghz"] == pytest.approx(2.55, abs=1e-9)
        assert bc["touches_sweep_edge"] is False
        assert bc["n_points_in_band"] == int(m.sum())
        assert bc["peak_db"] == pytest.approx(-1.0)

    def test_peak_at_sweep_edge_flagged(self):
        f = np.linspace(2.25, 2.75, 101)
        s_db = np.where(f >= 2.7, -1.0, -40.0)
        bc = runner.band_center_3db(f, s_db)
        assert bc["touches_sweep_edge"] is True

    def test_no_runs_tree_import_dependency(self):
        """2②：判读链脱 runs/ 证据树 import（脚本源静态钉；同输入数字逐位
        不变由上方已知值钉 + G1 dev=0 端到端钉背书）。"""
        src = (SCRIPTS / "c3_fullcurve_runner.py").read_text(encoding="utf-8")
        assert "from judge_refix import" not in src
        assert "import judge_refix" not in src
        seg = src[src.index("for _p in"): src.index("import numpy")]
        assert "runs" not in seg            # sys.path 注入块不再含 runs/ 路径


# ─── stage1 帽停容忍（criteria_a §一：帽=防挂死非预算门；2026-09-22 增补）────────

class TestStage1CapstopTolerance:
    """帽停/秒退分类 + 部分产物判读（stage1_verdict.json）。

    帽停形态 = smoke 内部 --timeout 杀引擎后 TimeoutExpired 未捕获崩溃退出
    （smoke 源禁改 → runner 侧容忍；rc=1、elapsed≈帽值 5040s）；部分产物判读
    走 refix extract_partial 先例（fdtd/ 剔 kill 残行 → fdtd_partial/ → 离线
    内核 ringdown + 置信三门 + S21∞@f0，门数值不动）。秒退 <4000s = crash 如实
    FAIL。真机调用层 mock（launch_fn），零引擎。
    """

    CAPSTEPS = 163000                 # 末进度行（合成日志进度行步距 1000）

    def _write_capstop_products(self, work: Path, t_end_s: float,
                                modes: list[tuple], ragged: bool = False) -> None:
        work.mkdir(parents=True, exist_ok=True)
        (work / "engine.log").write_text(
            _engine_log(1.38713e-13, 82611, self.CAPSTEPS, 5040.0,
                        terminated=False), encoding="utf-8")
        t, probes = _synth_ports(t_end_s, modes)
        _write_probes(work, t, probes)
        if ragged:
            # kill 截断残行（末行列数不足）：np.loadtxt 打不进 → 触发 fdtd_partial 剔残行
            # （须落在内核真正读取的 B 行文件上：MSLPort uf_tot=U 文件序[1]）
            p = work / "fdtd" / "port_ut_1B"
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(f"{t[-1] + 45.35e-12:.9e}\n")

    def test_classify_outcome_kinds(self):
        f = runner.classify_stage1_outcome
        assert f({"rc": 0, "killed": None, "elapsed_s": 10.0})["kind"] == "ok"
        assert f({"rc": 1, "killed": None, "elapsed_s": 5041.0})["kind"] == "capstop"
        assert f({"rc": 1, "killed": None, "elapsed_s": 4000.0})["kind"] == "capstop"
        assert f({"rc": 1, "killed": None, "elapsed_s": 3999.0})["kind"] == "quick_exit"
        assert f({"rc": 1})["kind"] == "quick_exit"       # 无 elapsed 不给帽停待遇
        assert f({"rc": None, "killed": "runner_deadline",
                  "elapsed_s": 5940.0})["kind"] == "capstop"
        assert f({"rc": None, "killed": "runner_deadline"})["kind"] == "capstop"

    def test_capstop_partial_products_pass_with_stage2_plan(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        self._write_capstop_products(work, T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)

        def fake_launch(cmd, timeout_s, cwd):
            return {"rc": 1, "killed": None, "elapsed_s": 5041.0,
                    "stdout_tail": "", "stderr_tail": "TimeoutExpired"}

        summary = runner.run_stage1(T, root, launch_fn=fake_launch, guard=lambda: [])
        vdoc = summary["stage1_verdict"]
        assert vdoc["verdict"] == "PASS" and vdoc["basis"] == "capstop"
        assert vdoc["rates"]["engine_db_per_ns"] == pytest.approx(0.4, abs=5e-3)
        assert vdoc["rates"]["rate_used_db_per_ns"] == pytest.approx(0.4, abs=5e-3)
        p2 = vdoc["stage2_plan"]
        assert p2["converged_in_stage1"] is False
        assert p2["iterations_done"] == self.CAPSTEPS
        assert p2["nrts"] == max(math.ceil(1.5 * p2["nrts_pred"]), p2["floor_steps"])
        assert p2["nrts"] >= p2["nrts_pred"] >= self.CAPSTEPS
        assert p2["budget_wall_s"] == pytest.approx(
            1.5 * p2["wall_per_step_s"] * p2["nrts_pred"], rel=1e-6)
        assert vdoc["data"]["cap_steps"] == self.CAPSTEPS
        disk = json.loads((work / "stage1_verdict.json").read_text(encoding="utf-8"))
        assert disk["verdict"] == "PASS"
        s1 = runner._plan_load(root)["templates"][T]["stage1"]
        assert s1["sentinel_ok"] is True
        assert s1["iterations_done"] == self.CAPSTEPS
        assert "capstop" in s1["steps_source"]
        # 断点续跑：完成标记在档不再发射；既有 verdict 保留
        calls: list[list[str]] = []

        def fake_launch2(cmd, timeout_s, cwd):
            calls.append(cmd)
            return {"rc": 0, "killed": None, "elapsed_s": 0.0}

        again = runner.run_stage1(T, root, launch_fn=fake_launch2, guard=lambda: [])
        assert calls == []
        assert again["verdict"] == "SENTINEL_PASS"

    def test_capstop_gates_fail_honest(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        self._write_capstop_products(work, T_EXC + 1.0 / ALPHA_MIN_S, MODES_MISMATCH)
        vdoc = runner.stage1_partial_verdict(
            T, root, outcome={"rc": 1, "killed": None, "elapsed_s": 5040.0})
        assert vdoc["verdict"] == "FAIL"
        assert vdoc["basis"] == "capstop" and vdoc["fail_kind"] == "gates"
        assert vdoc["reasons"]                            # 门失因如实列出
        assert vdoc["stage2_plan"] is None
        assert vdoc["rerun_hint"] is not None             # span 缺口加窗估计（只记录）

    def test_span_rerun_hint_degenerate_alpha_not_astronomical(self):
        # sir_bpf 形态：最弱模 α≈0（零衰减伪模）→ 加窗估计如实报不可达，不出天文数字
        summary = {"confidence": {"ok": False,
                                  "checks": {"span_db_min_obs": 0.0,
                                             "span_db_min": 20.0}},
                   "q_extrap_modes": [{"f0_ghz": 2.735, "alpha_per_ns": 5e-14,
                                       "span_db": 4.8e-12}],
                   "engine": {"dt_s": 1.27032e-13}}
        hint = runner._span_rerun_hint(summary)
        assert hint is not None and "不可达" in hint["note"]
        assert "extra_steps_est" not in hint

    def test_capstop_insufficient_data_no_ringdown(self, tmp_path):
        # combline 形态：激励未完成即帽停（探针窗 < 激励时长）→ 环振段不存在
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        self._write_capstop_products(work, T_EXC * 0.4, MODES_MATCH)
        vdoc = runner.stage1_partial_verdict(
            T, root, outcome={"rc": 1, "killed": None, "elapsed_s": 5040.0})
        assert vdoc["verdict"] == "FAIL" and vdoc["fail_kind"] == "insufficient_data"
        assert any("激励未完成" in r for r in vdoc["reasons"])
        assert vdoc["stage2_plan"] is None

    def test_capstop_ragged_probe_row_sanitized(self, tmp_path):
        # refix extract_partial 先例：fdtd/ 残行打不进内核 → fdtd_partial/ 剔残行重放
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        self._write_capstop_products(work, T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH,
                                     ragged=True)
        vdoc = runner.stage1_partial_verdict(
            T, root, outcome={"rc": 1, "killed": None, "elapsed_s": 5040.0})
        assert (work / "fdtd_partial" / "port_ut_1B").exists()
        assert vdoc["verdict"] == "PASS"

    def test_quick_exit_is_crash_fail(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        out = runner.run_stage1(
            T, root,
            launch_fn=lambda cmd, timeout_s, cwd: {
                "rc": 1, "killed": None, "elapsed_s": 137.0,
                "stdout_tail": "", "stderr_tail": "boom"},
            guard=lambda: [])
        vdoc = out["stage1_verdict"]
        assert vdoc["verdict"] == "FAIL" and vdoc["fail_kind"] == "crash"
        assert any("秒退" in r for r in vdoc["reasons"])
        disk = json.loads((runner.stage_dir(T, "stage1", root)
                           / "stage1_verdict.json").read_text(encoding="utf-8"))
        assert disk["verdict"] == "FAIL" and disk["basis"] == "crash"

    def test_judge_stage1_cli_offline_replay(self, tmp_path, capsys):
        # --judge-stage1：盘上产物纯离线重放（不发射引擎）；PASS→0 / FAIL→1
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir(T, "stage1", root)
        self._write_capstop_products(work, T_EXC + 4.0 / ALPHA_MIN_S, MODES_MATCH)
        assert runner.main(["--template", T, "--judge-stage1",
                            "--root", str(root)]) == 0
        assert "STAGE1J_INTERDIGITAL_PASS" in capsys.readouterr().out
        # 换失配模（门 FAIL）→ 重放如实 1
        self._write_capstop_products(work, T_EXC + 1.0 / ALPHA_MIN_S, MODES_MISMATCH)
        (work / "stage1_verdict.json").unlink()
        assert runner.main(["--template", T, "--judge-stage1",
                            "--root", str(root)]) == 1
        assert "STAGE1J_INTERDIGITAL_FAIL" in capsys.readouterr().out
