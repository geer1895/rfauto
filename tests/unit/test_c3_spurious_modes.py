"""c3 零衰减伪模判别模块单测（判据 runs/c3_sirbpf_spurious/criteria.md）。

覆盖：
① 材料 Q 帽分类（物理/伪模二分；q_loaded 缺失防御；被困模假设的材料帽界定）；
② α→0 分支合成回收钉（#118 纪律，判据 §四）：物理+零衰减双模注入 →
   refine_modes_vp 紧收敛 VP 回收物理模 α/ω 相对误差 ≤1%，零衰减模 Q>帽判伪
   且不污染物理模回收；双物理模对照（无一判伪）同 ≤1%；确定性双跑逐位等；
③ 跨窗稳定性（C3）：干净物理模 spread 小/不判退化；退化判定纯函数两分支；
④ 幅值占比（C4）：已知幅值合成 → 线性解精确回收比例；
⑤ 盒模估算（C5）：120mm 域 (2,0)@ε=1 → 2.4982GHz 数学钉；
⑥ split_physical_refit：无伪模 → None（缺省路径零改动铁律）；有伪模 → 物理
   模基重外推 refit_ok=True；物理模空 → refit_ok=False（不触探针读入）；
⑦ runner 集成：summarize_stage1 伪模形态 → summary["spurious"] 在场、
   alpha_min 为物理模口径（非零 α）；全物理形态 → 无新增键（逐字节不变）；
   stage1_partial_verdict 留痕 doc["spurious"]；builder 判别报告 + 预算公式
   + span<3dB α 不可辨不进预算。
真机调用层零参与（fdtd 探针/engine.log 全合成落盘，零引擎零网络）。
合成模幅值全部 ≥0.30（> 矩形窗第一旁瓣 −13.3dBc=0.216）——防旁瓣被当第三模
拾取的非确定性。
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


spur = _load_script("c3_spurious_modes")
runner = _load_script("c3_fullcurve_runner")
import c3_resonance_q_extract as c3q

T_EXC = 1.14592e-8
DT_ROW = 45.35e-12               # sir_bpf 探针行距实测
F_LO, F_HI = 2.25e9, 2.75e9
Q_CAP = spur.Q_MAT_CAP           # 1351.4
A_ZERO_S = 1.0e-6                # 零衰减模 α（≈1e-15/ns，Q~8e14）

# 合成模表 (f_hz, alpha_per_s, amp, phase)。
# 谱可分辨设计：环振窗 T 下泄漏 ~sinc(k/T)，模间隔须 ≳2.2/T 且幅值 ≥0.30
# （> 第一旁瓣 −13.3dBc=0.216）——否则拾取落在泄漏峰上（恰为 A1 机制再现，
# 不适合做回收钉）。
# 接线族合成（D 组合实测，确定性）：SPUR 拾取恰 2 模——2.6999(Q=1.15e4 伪)
# + 2.4914(α=0.3057)；物理单模精化 α=0.2904（数据含未建模零衰减分量的确定性
# 偏置 −3.2%，真数据 sir_bpf 同位形实测偏置仅 −0.1%）；PHYS 拾取 2.5000
# (α=0.30184)+2.6987(α=0.25005)，分类零改动
MODES_SPUR = [(2.50e9, 0.30e9, 1.0, 2.1),       # 物理主模 0.30/ns
              (2.70e9, A_ZERO_S, 0.40, 0.7)]    # 零衰减伪模
MODES_PHYS = [(2.50e9, 0.30e9, 1.0, 2.1),
              (2.70e9, 0.25e9, 0.40, 0.7)]
RING_WIRE_S = 26.0e-9               # 接线族环振窗（200MHz 间隔 = 5/T）
RING_PIN_S = 26.0e-9                # 回收钉环振窗


def _synth_modes(t_end_s: float, modes: list[tuple]) -> tuple[np.ndarray, np.ndarray]:
    """环振合成：t'≥T_EXC 起振（之前置零——探针窗形态）。"""
    t = np.arange(0.0, float(t_end_s), DT_ROW)
    tp = np.maximum(t - T_EXC, 0.0)
    u = np.zeros_like(t)
    for f_hz, al, amp, ph in modes:
        u = u + amp * np.exp(-al * tp) * np.cos(2 * np.pi * f_hz * tp + ph)
    u[t < T_EXC] = 0.0
    return t, u


def _write_workspace(work: Path, t: np.ndarray, u1: np.ndarray,
                     cap_steps: int, exc_steps: int = 90207,
                     dt_s: float = 1.27032e-13) -> None:
    """fdtd 探针 + engine.log 合成落盘（load_msl_probes 全文件面）。"""
    fdtd = work / "fdtd"
    fdtd.mkdir(parents=True, exist_ok=True)
    u2 = 0.3 * u1
    i1 = u1 / 50.0
    i2 = -u2 / 50.0
    for name, v in (("port_ut_1A", u1), ("port_ut_1B", u1), ("port_ut_1C", u1),
                    ("port_it_1A", i1), ("port_it_1B", i1),
                    ("port_ut_2A", u2), ("port_ut_2B", u2), ("port_ut_2C", u2),
                    ("port_it_2A", i2), ("port_it_2B", i2)):
        np.savetxt(fdtd / name, np.column_stack([t, v]),
                   header="t/s voltage", comments="%")
    t_exc_ns = T_EXC * 1e9
    lines = [
        "FDTD simulation size: 505x997x22 --> 1.11e+07 FDTD cells ",
        f"FDTD timestep is: {dt_s:.5e} s; Nyquist rate: 1431 timesteps @2.75e+09 Hz",
        f"Excitation signal length is: {exc_steps} timesteps ({T_EXC:.5e}s)",
        "Max. number of timesteps: 1000000 ( --> 11.1 * Excitation signal length)",
    ]
    step = max(1000, (cap_steps - exc_steps) // 40)
    for s in range(exc_steps, cap_steps + 1, step):
        e_db = -2.0 - 1.0 * (s * dt_s * 1e9 - t_exc_ns)     # 1dB/ns 线性尾段
        lines.append(f"Timestep: {s} || Progress: 16.4% | "
                     f"Energy: ~1.0e-03 ({e_db:.2f}dB)")
    (work / "engine.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_plan(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    plan = {"batch": "smoke_c3_fullcurve", "criteria": runner.CRITERIA_A,
            "templates": {t: {} for t in ("combline", "interdigital", "sir_bpf")}}
    runner._plan_write(plan, root)


def _report_of(modes_kernel: list[dict]) -> list[dict]:
    return [{"f0_ghz": m["f0_hz"] / 1e9, "alpha_per_ns": m["alpha_per_s"] * 1e-9,
             "q_loaded": m["q_loaded"], "span_db": m["span_db"],
             "n_fit": int(m["n_fit"])} for m in modes_kernel]


def _pick(t: np.ndarray, u: np.ndarray, n_modes: int = 3) -> list[dict]:
    return c3q.extract_ring_modes(t, u, F_LO, F_HI, T_EXC, n_modes=n_modes)


# ── ① 材料 Q 帽分类 ─────────────────────────────────────────────────────────────

class TestClassifyModes:
    def test_all_physical_unchanged(self):
        modes = [{"f0_ghz": 2.5, "alpha_per_ns": 0.15, "q_loaded": 52.4,
                  "span_db": 14.7, "n_fit": 244}]
        cls = spur.classify_modes(modes)
        assert cls["changed"] is False
        assert len(cls["physical"]) == 1 and cls["spurious"] == []

    def test_zero_decay_modes_are_spurious(self):
        modes = [{"f0_ghz": 2.5464, "alpha_per_ns": 0.1541, "q_loaded": 51.9,
                  "span_db": 14.75, "n_fit": 244},
                 {"f0_ghz": 2.6543, "alpha_per_ns": 5.5e-5, "q_loaded": 1.5e5,
                  "span_db": 0.005, "n_fit": 244},
                 {"f0_ghz": 2.7351, "alpha_per_ns": 5.1e-14,
                  "q_loaded": 1.7e14, "span_db": 4.8e-12, "n_fit": 244}]
        cls = spur.classify_modes(modes)
        assert cls["changed"] is True
        assert [m["f0_ghz"] for m in cls["physical"]] == [2.5464]
        assert [m["f0_ghz"] for m in cls["spurious"]] == [2.6543, 2.7351]
        assert cls["q_mat_cap"] == pytest.approx(Q_CAP)

    def test_trapped_mode_hypothesis_bounded_by_material_cap(self):
        # #344 语境：被困模不解除介质损耗——Q 恰在帽下 = 物理（保留），帽上 = 伪
        at_cap = {"f0_ghz": 2.5, "alpha_per_ns": math.pi * 2.5 / (Q_CAP * 0.99),
                  "q_loaded": Q_CAP * 0.99, "span_db": 25.0, "n_fit": 244}
        over_cap = dict(at_cap, q_loaded=Q_CAP * 1.01,
                        alpha_per_ns=math.pi * 2.5 / (Q_CAP * 1.01))
        assert spur.classify_modes([at_cap])["changed"] is False
        assert spur.classify_modes([over_cap])["changed"] is True

    def test_missing_q_defensive_spurious(self):
        modes = [{"f0_ghz": 2.6, "alpha_per_ns": 0.0, "q_loaded": None,
                  "span_db": 0.0, "n_fit": 10}]
        cls = spur.classify_modes(modes)
        assert cls["changed"] is True and len(cls["spurious"]) == 1

    def test_kernel_roundtrip(self):
        k = spur.kernel_modes_from_report(
            [{"f0_ghz": 2.5, "alpha_per_ns": 0.15, "q_loaded": 52.4,
              "span_db": 14.7, "n_fit": 244}])
        assert k[0]["f0_hz"] == pytest.approx(2.5e9)
        assert k[0]["alpha_per_s"] == pytest.approx(0.15e9)
        assert k[0]["n_fit"] == 244


# ── ② α→0 分支合成回收钉（判据 §四：≤1%，先合成后真数据）───────────────────────

class TestRefineRecoveryPin:
    def test_physical_plus_zero_decay_recovery_le_1pct(self):
        """物理(2.50GHz, 0.15/ns) + 零衰减(2.70GHz, α≈0)注入 → 物理模 α/ω
        回收 ≤1%；零衰减模 Q>帽判伪；物理模回收不被污染。"""
        t, u = _synth_modes(T_EXC + RING_PIN_S,
                            [(2.50e9, 0.15e9, 1.0, 0.0),
                             (2.70e9, A_ZERO_S, 0.30, 0.7)])
        modes = spur.refine_modes_vp(t, u, T_EXC,
                                     spur.kernel_modes_from_report(
                                         _report_of(_pick(t, u, n_modes=2))))
        assert len(modes) == 2
        phys = next(m for m in modes if abs(m["f0_hz"] / 1e9 - 2.50) < 0.05)
        zero = next(m for m in modes if abs(m["f0_hz"] / 1e9 - 2.70) < 0.05)
        assert abs(phys["alpha_per_s"] - 0.15e9) / 0.15e9 <= 0.01
        assert abs(phys["f0_hz"] - 2.50e9) / 2.50e9 <= 0.01
        assert zero["q_loaded"] > Q_CAP        # α→0 分支：材料帽以上判伪
        cls = spur.classify_modes(_report_of(modes))
        assert cls["changed"] is True
        phys_rep = [m["f0_ghz"] for m in cls["physical"]]
        assert len(phys_rep) == 1
        assert phys_rep[0] == pytest.approx(2.50, rel=1e-2)

    def test_dual_physical_no_false_spurious(self):
        """双物理模对照（无一伪）：两模 α/ω 均 ≤1% 回收且分类零改动。"""
        t, u = _synth_modes(T_EXC + RING_PIN_S,
                            [(2.50e9, 0.15e9, 1.0, 0.0),
                             (2.65e9, 0.05e9, 0.30, 2.1)])
        modes0 = _pick(t, u, n_modes=2)
        assert spur.classify_modes(_report_of(modes0))["changed"] is False
        modes = spur.refine_modes_vp(t, u, T_EXC,
                                     spur.kernel_modes_from_report(
                                         _report_of(modes0)))
        for m, (f_true, a_true) in zip(modes, [(2.50e9, 0.15e9), (2.65e9, 0.05e9)],
                                       strict=True):
            assert abs(m["alpha_per_s"] - a_true) / a_true <= 0.01
            assert abs(m["f0_hz"] - f_true) / f_true <= 0.01
        assert spur.classify_modes(_report_of(modes))["changed"] is False

    def test_refine_is_deterministic(self):
        t, u = _synth_modes(T_EXC + RING_PIN_S,
                            [(2.50e9, 0.15e9, 1.0, 0.0),
                             (2.70e9, A_ZERO_S, 0.30, 0.7)])
        km = spur.kernel_modes_from_report(_report_of(_pick(t, u, n_modes=2)))
        r1 = spur.refine_modes_vp(t, u, T_EXC, km)
        r2 = spur.refine_modes_vp(t, u, T_EXC, km)
        assert [(m["alpha_per_s"], m["f0_hz"]) for m in r1] == [
            (m["alpha_per_s"], m["f0_hz"]) for m in r2]


# ── ③ 跨窗稳定性（C3）───────────────────────────────────────────────────────────

class TestCrossWindowStability:
    def test_clean_physical_mode_stable_not_degenerate(self):
        t, u = _synth_modes(T_EXC + RING_WIRE_S, MODES_SPUR)
        base = _report_of(_pick(t, u, n_modes=3))
        stab = spur.cross_window_stability(t, u, F_LO, F_HI, T_EXC, base,
                                           delays_ns=(1.0, 2.0, 3.0),
                                           fracs=(0.7, 1.0))
        assert stab["n_variants"] == 6
        phys = next(p for p in stab["per_mode"]
                    if p["q_loaded_base"] <= spur.Q_MAT_CAP)   # 物理基模
        assert phys["n_absent"] == 0                       # 物理模每窗均在
        assert phys["alpha_spread_ratio"] < spur.ALPHA_DEGEN_SPREAD_MAX
        assert phys["degenerate_fit"] is False

    def test_degenerate_decision_pure_function_both_branches(self):
        assert spur.is_degenerate_fit(15.0, 6.4) is True      # α 散布 >10×
        assert spur.is_degenerate_fit(1.2, 31.0) is True      # f0 漂移 >30MHz
        assert spur.is_degenerate_fit(1.2, 6.4) is False      # 干净物理模
        assert spur.is_degenerate_fit(None, None) is False    # 全缺席不算退化
        assert spur.is_degenerate_fit(spur.ALPHA_DEGEN_SPREAD_MAX, None) is False


# ── ④ 幅值占比（C4）─────────────────────────────────────────────────────────────

class TestModeAmplitudes:
    def test_known_amplitudes_recovered(self):
        t, u = _synth_modes(T_EXC + RING_PIN_S,
                            [(2.50e9, 0.15e9, 1.0, 0.0),
                             (2.70e9, A_ZERO_S, 0.30, 0.7)])
        amp = spur.mode_amplitudes(t, u, T_EXC, _pick(t, u, n_modes=2))
        rels = {round(a["f0_ghz"], 2): a["rel_to_max"] for a in amp["modes"]}
        assert rels[2.5] == pytest.approx(1.0, rel=1e-3)
        assert rels[2.7] == pytest.approx(0.30, rel=5e-2)
        assert amp["resid_rms"] < 5e-2 * amp["signal_rms"]


# ── ⑤ 盒模估算（C5，数学钉）────────────────────────────────────────────────────

class TestBoxModeCandidates:
    def test_20_mode_on_120mm_domain(self):
        # c/2·(2/0.12)/1e9 = 2.4982GHz @ε=1
        cands = spur.box_mode_candidates(2.4982, lx_m=0.120, ly_m=0.120)
        hit = [c for c in cands if c["i"] == 2 and c["j"] == 0 and c["eps_eff"] == 1.0]
        assert hit and hit[0]["f_ghz"] == pytest.approx(2.4982, abs=5e-4)

    def test_below_fundamental_empty(self):
        # 0.5GHz：最低盒模 (0,1)@ε=3.66=0.653GHz，2% 容差内无候选
        assert spur.box_mode_candidates(0.5, lx_m=0.120, ly_m=0.120) == []


# ── ⑥ split_physical_refit（判读链薄接线面）────────────────────────────────────

class TestSplitPhysicalRefit:
    def test_no_spurious_returns_none(self):
        modes = [{"f0_ghz": 2.5, "alpha_per_ns": 0.15, "q_loaded": 52.4,
                  "span_db": 14.7, "n_fit": 244}]
        assert spur.split_physical_refit("/nonexistent", np.linspace(F_LO, F_HI, 8),
                                         T_EXC, 2.5e9, modes) is None

    def test_spurious_triggers_physical_refit(self, tmp_path):
        t, u = _synth_modes(T_EXC + RING_PIN_S, MODES_SPUR)
        _write_workspace(tmp_path, t, u,
                         cap_steps=int((T_EXC + RING_PIN_S) / 1.27032e-13))
        modes0 = _pick(t, u, n_modes=2)
        split = spur.split_physical_refit(
            str(tmp_path / "fdtd"), np.linspace(F_LO, F_HI, 401), T_EXC, 2.5e9,
            _report_of(modes0))
        assert split is not None and split["changed"] is True
        assert split["refit_ok"] is True
        assert split["report_physical"] is not None
        assert "keys" in split["report_physical"]
        assert len(split["modes_physical_kernel"]) == 1   # 零衰减模不在物理基
        # 精化 Q 确定性值 26.88（真值 26.18，未建模零衰减分量的 +2.7% 偏置）
        assert (split["modes_physical_kernel"][0]["q_loaded"]
                == pytest.approx(math.pi * 2.5 / 0.30, rel=0.05))

    def test_empty_physical_refit_not_ok_no_probe_read(self):
        # 物理模空：refit 如实不可行且不触探针读入（/nonexistent 不炸）
        modes = [{"f0_ghz": 2.7, "alpha_per_ns": 5e-14, "q_loaded": 1.7e14,
                  "span_db": 0.0, "n_fit": 244}]
        split = spur.split_physical_refit("/nonexistent",
                                          np.linspace(F_LO, F_HI, 8),
                                          T_EXC, 2.5e9, modes)
        assert split is not None and split["refit_ok"] is False
        assert split["report_physical"] is None


# ── ⑦ runner 集成（summarize/stage1_partial_verdict/builder）───────────────────

class TestRunnerSpuriousWiring:
    def test_summarize_records_spurious_and_physical_alpha(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir("interdigital", "stage1", root)
        t, u1 = _synth_modes(T_EXC + RING_WIRE_S, MODES_SPUR)
        _write_workspace(work, t, u1,
                         cap_steps=int((T_EXC + RING_WIRE_S) / 1.27032e-13))
        summary = runner.summarize_stage1("interdigital", root)
        assert "spurious" in summary                     # 伪模在场才新增键
        assert summary["spurious"]["changed"] is True
        spur_f = [m["f0_ghz"] for m in summary["spurious"]["spurious"]]
        assert any(abs(f - 2.70) < 0.01 for f in spur_f)
        # α_min 为物理模口径（非零衰减伪模）：精化单物理模确定性值 0.2904
        assert summary["alpha_min_per_ns"] > 1e-3
        assert summary["alpha_min_per_ns"] == pytest.approx(0.2904, rel=0.02)
        phys_f = [m["f0_ghz"] for m in summary["spurious"]["physical"]]
        assert any(abs(f - 2.4914) < 0.02 for f in phys_f)

    def test_summarize_default_path_no_new_keys(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir("interdigital", "stage1", root)
        t, u1 = _synth_modes(T_EXC + RING_WIRE_S, MODES_PHYS)
        _write_workspace(work, t, u1,
                         cap_steps=int((T_EXC + RING_WIRE_S) / 1.27032e-13))
        summary = runner.summarize_stage1("interdigital", root)
        assert "spurious" not in summary                 # 缺省路径零新增键
        assert summary["alpha_min_per_ns"] == pytest.approx(0.25, rel=0.05)

    def test_stage1_partial_verdict_records_spurious(self, tmp_path):
        root = tmp_path / "runs"
        _make_plan(root)
        work = runner.stage_dir("interdigital", "stage1", root)
        t, u1 = _synth_modes(T_EXC + RING_WIRE_S, MODES_SPUR)
        _write_workspace(work, t, u1,
                         cap_steps=int((T_EXC + RING_WIRE_S) / 1.27032e-13))
        doc = runner.stage1_partial_verdict(
            "interdigital", root,
            outcome={"rc": 1, "killed": None, "elapsed_s": 5040.0})
        assert "spurious" in doc
        assert doc["spurious"]["changed"] is True
        assert doc["rates"]["kernel_db_per_ns"] == pytest.approx(
            runner.ENERGY_RATE_PER_ALPHA_NS * 0.2904, rel=0.02)  # 物理口径
        disk = json.loads((work / "stage1_verdict.json").read_text(encoding="utf-8"))
        assert "spurious" in disk

    def test_builder_full_report_on_synthetic(self, tmp_path):
        work = tmp_path / "stage1"
        t, u1 = _synth_modes(T_EXC + RING_WIRE_S, MODES_SPUR)
        cap_steps = int((T_EXC + RING_WIRE_S) / 1.27032e-13)
        _write_workspace(work, t, u1, cap_steps=cap_steps)
        out = tmp_path / "spurious_verdict.json"
        doc = spur.build_spurious_verdict(str(work), str(out))
        assert out.exists()
        assert len(doc["classification"]["spurious"]) == 1
        assert any(abs(m["f0_ghz"] - 2.70) < 0.01
                   for m in doc["classification"]["spurious"])
        assert doc["modes_physical_refined"], "物理模须精化在场"
        phys = next(m for m in doc["modes_physical_refined"]
                    if abs(m["f0_ghz"] - 2.4914) < 0.02)
        assert phys["alpha_per_ns"] == pytest.approx(0.2904, rel=0.02)
        assert doc["attribution"], "伪模归因标注在场"
        attr = next(iter(doc["attribution"].values()))
        assert attr["class"].startswith("A")
        # 预算：rate=min(kernel(物理 α_min≈0.3), engine 1dB/ns)=1dB/ns（合成尾段）
        b = doc["stage2_budget_if_released"]
        assert b is not None
        assert b["rate_used_db_per_ns"] == pytest.approx(1.0, rel=1e-3)
        # （合成日志能量行 2 位小数量化 → polyfit 斜率 1.00016）
        assert b["nrts"] >= b["nrts_pred"] >= cap_steps
        assert doc["stage2_release"] is not None
        assert doc["stage2_release"]["released"] == doc["sentinel_replay_physical"]["ok"]

    def test_budget_alpha_min_floor(self):
        # α 可辨下界（span≥3dB 才作预算输入）：慢模 span 不足 → 预算输入如实缺失
        identifiable = [{"alpha_per_s": 0.15e9, "span_db": 30.0},
                        {"alpha_per_s": 0.05e9, "span_db": 2.0}]
        assert spur.budget_alpha_min(identifiable) == pytest.approx(0.15)
        assert spur.budget_alpha_min([{"alpha_per_s": 0.15e9, "span_db": 2.9}])             is None
        assert spur.budget_alpha_min([]) is None
