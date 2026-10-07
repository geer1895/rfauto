"""varactor_oe_judge (d) 判据-实现保真单测（slice9 P2-1 收口，2026-09-29）。

裁判口径：归因四选一的预声明判据（模块 docstring + predeclared_criteria 文本
单源 _predeclared_criteria_text()）必须与 attribute() 实现门同口径——(d) 实现
门=预声明四判据**合取**（慢振铃形态 + 跨档偏压追踪 + S11 谷在音上 + 能量 2f
晃动互证）；偏压追踪成立而旁证缺席 → 标签 corroboration_missing、置信
≤medium、不授 (d)。合成 tier dict（零真机产物依赖，纯离线）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_varactor_oe_judge",
    str(Path(__file__).resolve().parents[2] / "scripts" / "varactor_oe_judge.py"))
assert _SPEC is not None and _SPEC.loader is not None
vj = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vj)


def _tier_dict(*, shape: str = "slow_ring", slosh: bool = True,
               valley: float | None = 2.5, tone: float = 2.5,
               box_mode: bool = False, bias_tracking: bool = True,
               spread: float = 0.09, decay: bool = False) -> tuple[dict, dict]:
    """合成单档 tier + cross dict（attribute() 的最小输入面）。"""
    r = {
        "oe_result": {"engine": {"hit_nrts_limit": True, "nrts": 100000,
                                 "iterations_done": 100000, "dt_s": 5.06e-11},
                      "kernel": {"f0_ghz": 2.5}},
        "energy_log": {"found": True, "shape_class": shape,
                       "ring_subclass": "plateau" if shape == "slow_ring" else None,
                       "peaks_slope_db_per_ns": 0.05, "peaks_change_db": 0.3,
                       "peaks_fit_r2": 0.9,
                       "raw_slope_db_per_ns": -0.6 if decay else 0.1,
                       "raw_fit_r2": 0.95 if decay else 0.1,
                       "post_window": {"env_min_db": -20.0, "env_max_db": -18.0},
                       "slosh_freq_hz": 2 * tone * 1e9,
                       "slosh_mode_if_single_hz": tone * 1e9,
                       "slosh_half_matches_tone": slosh,
                       "q_eff_energy": 712.0},
        "sparams": {"violation_frac": 0.05, "n_viol_gt1": 2,
                    "violation_runs_ghz": [(2.4, 2.5)],
                    "oe_result_valley_ghz": valley},
        "gamma": {"scan_direction": "improves",
                  "truncation_scan": [{"max_abs_gamma": 1.1, "n_viol_gt1": 2},
                                      {"max_abs_gamma": 1.0, "n_viol_gt1": 0}]},
        "dc_drift": {"drift_over_osc_ratio": 0.01},
        "stderr": {"endcriteria_60db_reached_cap": True,
                   "timesteps_lt_3x_excitation": False,
                   "unused_primitive_count": 2, "excitation_inside_mur": False},
        "probes": {"port_ut_1B": {"tone": {"f_secondary_hz": None}}},
    }
    cross = {"tone_f_ghz": {"v0.5": tone}, "spread_frac": spread,
             "monotonic_with_c_order": bias_tracking,
             "box_mode": box_mode, "bias_tracking": bias_tracking}
    return r, cross


def test_d_gate_full_conjunction_grants_d_high():
    """四判据齐 -> (d) 标签 + d_evidence 全 True + 置信 high（宣称=实现）。"""
    r, cross = _tier_dict()
    a = vj.attribute("v0.5", r, cross)
    assert a["primary"] == "d"
    assert "d" in a["labels"]
    assert a["d_evidence"] == {"slow_ring": True, "bias_tracking": True,
                               "valley_on_tone": True, "slosh_interlock": True}
    assert a["confidence"] == "high"


@pytest.mark.parametrize("missing", ["slosh_interlock", "valley_on_tone",
                                     "slow_ring"])
def test_d_gate_missing_corroboration_denies_d(missing: str):
    """旁证缺席（本批实证：v3.6342 晃动不符 / v10 谷偏 1.86%）-> 不授 (d)、
    corroboration_missing 标签、主归因降 undetermined、置信 ≤medium。"""
    slosh = missing != "slosh_interlock"
    valley = 2.5 if missing != "valley_on_tone" else 2.6     # 偏 4% > 1.5% 阈
    shape = "slow_ring" if missing != "slow_ring" else "unclassified"
    r, cross = _tier_dict(slosh=slosh, valley=valley, shape=shape)
    a = vj.attribute("v0.5", r, cross)
    assert a["d_evidence"][missing] is False
    assert "d" not in a["labels"]
    assert "corroboration_missing" in a["labels"]
    assert a["primary"] == "undetermined"
    assert a["confidence"] in ("medium", "low")


def test_d_gate_box_mode_still_b_and_monotonic_decay_still_a():
    """(b)/(a) 路径不受 (d) 收口影响：盒模 -> b；单调衰减形态 -> a。"""
    r, cross = _tier_dict(box_mode=True, bias_tracking=False, spread=0.005)
    assert vj.attribute("v0.5", r, cross)["primary"] == "b"
    r, cross = _tier_dict(shape="monotonic_decay", decay=True)
    assert vj.attribute("v0.5", r, cross)["primary"] == "a"


def test_predeclared_text_matches_implementation_gate():
    """预声明文本单源（docstring + _predeclared_criteria_text）与实现门同口径：
    (d) 合取表述 + corroboration_missing 降级路径 + Γ 扫描端点口径（P3-1）。"""
    assert "合取" in vj.__doc__
    assert "corroboration_missing" in vj.__doc__
    assert "端点判据" in vj.__doc__            # P3-1：Γ scan 非严格单调检验
    crit = vj._predeclared_criteria_text()
    assert "四判据合取" in crit["d_bias_resonance"]
    assert "corroboration_missing" in crit["d_bias_resonance"]
    assert f">={vj.BIAS_TRACK_SPREAD_MIN * 100:.0f}%" in crit["d_bias_resonance"]
    assert "末<首×0.98" in crit["a_truncation"]
    assert "端点回落" in crit["a_truncation"]


# ---------------------------------------------------------------------------
# ge5 触帽腿降级修复批（2026-10-01）：analyze_tier port_ut 回退路径 + 判读行
# 幂等刷新。合成数据零真机依赖；tone 频率 2.71GHz 恰在细栅周期图格点上
# （0.3GHz + 1205×2MHz），单音合成下 f_dominant_hz 逐位钉。
# ---------------------------------------------------------------------------
_VSMOKE_SPEC = importlib.util.spec_from_file_location(
    "_varactor_smoke",
    str(Path(__file__).resolve().parents[2] / "scripts" / "varactor_smoke.py"))
assert _VSMOKE_SPEC is not None and _VSMOKE_SPEC.loader is not None
vsm = importlib.util.module_from_spec(_VSMOKE_SPEC)
_VSMOKE_SPEC.loader.exec_module(vsm)

_TONE_HZ = 2.71e9
_DT_PORT = 4.1568e-11          # port dump 采样距（真实触帽腿同量级）
_DT_ENG = 1.91e-11             # et 引擎步采样距
_T_EXCITE_END = 5.73e-9
_SPAN = 40e-9


def _ring_signal(t: np.ndarray, amp_ring: float = 1.2e-3) -> np.ndarray:
    """激励段 2.5GHz 强瞬态 + 末端起 2.71GHz 单音振铃（晚窗纯单音）。"""
    return np.where(t <= _T_EXCITE_END,
                    5e-3 * np.sin(2 * np.pi * 2.5e9 * t),
                    amp_ring * np.sin(2 * np.pi * _TONE_HZ * t))


def _t_axis() -> np.ndarray:
    return np.arange(0.0, _SPAN, _DT_PORT)


def _write_port_dump(path: Path, t: np.ndarray, v: np.ndarray) -> None:
    rows = ["% synthetic port dump (test)", "% start-coordinates: (0,0,0)",
            "% stop-coordinates: (0,0,0)", "% t/s\tvoltage"]
    rows += [f"{float(ti)!r}\t{float(vi)!r}"
             for ti, vi in zip(t, v, strict=True)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _make_fallback_dir(base: Path, v_fn=None) -> Path:
    """触帽降级腿合成 run 目录：sparams.csv 缺 + stdout 0B（触帽伪象签名）。"""
    d = base / "fdtd"
    d.mkdir(parents=True)
    t = _t_axis()
    v = (v_fn or _ring_signal)(t)
    _write_port_dump(d / "port_ut_1B", t, v)
    _write_port_dump(d / "port_ut_1A", t, v)
    te = np.arange(0.0, _T_EXCITE_END + _DT_ENG / 2, _DT_ENG)
    np.savetxt(d / "et", np.column_stack([te, np.sin(3.0 * te)]))
    (base / "_last_stdout.log").write_text("", encoding="utf-8")   # 0B 触帽伪象
    (base / "_last_stderr.log").write_text("TimeoutExpired after 7200.0s",
                                           encoding="utf-8")
    (base / "oe_result.json").write_text(json.dumps(
        {"leg": base.name, "engine": {}, "solve_success": False,
         "budget": {"wall_actual_s": 7200.0}, "preflight": {"ok": True},
         "tone_error": "FileNotFoundError: sparams.csv not found."}),
        encoding="utf-8")
    return base


def _make_normal_dir(base: Path) -> Path:
    """正常路径合成 run 目录：sparams/stdout/全探针在档（零行为钉输入面）。"""
    d = base / "fdtd"
    d.mkdir(parents=True)
    t = _t_axis()
    v = _ring_signal(t)
    for nm in ("port_ut_1A", "port_ut_1B", "port_ut_1C",
               "port_it_1A", "port_it_1B"):
        _write_port_dump(d / nm, t, v)
    te = np.arange(0.0, _T_EXCITE_END + _DT_ENG / 2, _DT_ENG)
    np.savetxt(d / "et", np.column_stack([te, np.sin(3.0 * te)]))
    freq = np.linspace(2.0, 3.0, 101) * 1e9
    s11 = np.full(101, 0.3 + 0.1j)
    s11[50] = 0.2 + 0.0j                      # 2.5GHz 处深谷
    s21 = np.full(101, 0.1 - 0.05j)
    rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
    rows += [f"{float(f)!r},{float(z11.real)!r},{float(z11.imag)!r},"
             f"{float(z21.real)!r},{float(z21.imag)!r}"
             for f, z11, z21 in zip(freq, s11, s21, strict=True)]
    (base / "sparams.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    eng = [f"Timestep: {i * 1000} ||Speed: 1.0 Mcells/s||"
           " Energy: ~1.0 (- 13.0dB)" for i in range(51)]  # 0..50000 步→9.7ns 窗
    (base / "_last_stdout.log").write_text("\n".join(eng) + "\n",
                                           encoding="utf-8")
    (base / "_last_stderr.log").write_text("", encoding="utf-8")
    (base / "oe_result.json").write_text(json.dumps(
        {"leg": base.name, "solve_success": True,
         "engine": {"dt_s": 1.94e-13, "nrts": 100000,
                    "iterations_done": 50000, "hit_nrts_limit": False},
         "budget": {"wall_actual_s": 100.0}, "preflight": {"ok": True}}),
        encoding="utf-8")
    return base


def test_analyze_tier_fallback_recovers_tone_from_port_ut(tmp_path):
    """降级路径：sparams 缺/stdout 0B 时从 port_ut 自回收音（逐位钉）+ 标记。"""
    d = _make_fallback_dir(tmp_path / "a1_pml")
    r = vj.analyze_tier(d)
    assert r["tone_source"] == "port_ut_fallback"
    assert r["missing_artifacts"] == ["sparams.csv"]
    tone = r["probes"]["port_ut_1B"]["tone"]
    assert tone["f_dominant_hz"] == _TONE_HZ          # 细栅格点逐位
    fb = r["fallback_tone"]
    assert fb["ok"] is True and fb["tone_trusted"] is True
    assert fb["dt_s"] == pytest.approx(_DT_PORT, rel=1e-9)  # 采样距自文件回收
    assert fb["t_span_ns"] == pytest.approx(float(_t_axis()[-1]) * 1e9,
                                            rel=1e-12)
    st = fb["window_stability"]
    assert st["ok"] is True and st["n_windows"] == 3
    assert st["f_ghz"] == [2.71, 2.71, 2.71]          # 三窗稳定（单音合成）
    assert st["spread_frac"] == 0.0
    assert fb["late_level_db_vs_post_peak"] > -vj.END_DB_TARGET
    assert r["energy_log"]["found"] is False          # stdout 0B 如实缺档
    assert r["sparams"]["available"] is False
    assert r["gamma"]["available"] is False
    assert r["t_excite_end_ns"] == pytest.approx(5.73, rel=1e-9)


def test_analyze_tier_fallback_no_file_not_found_and_stdout_absent(tmp_path):
    """sparams.csv 缺不再抛 FileNotFoundError；stdout 整文件缺也走降级并
    如实入缺件清单（触帽腿判读不被提取器中断——伪 vanished 根因修复钉）。"""
    d = _make_fallback_dir(tmp_path / "a2_airtop")
    (d / "_last_stdout.log").unlink()                 # stdout 整文件缺
    r = vj.analyze_tier(d)                            # 不抛即过
    assert set(r["missing_artifacts"]) == {"_last_stdout.log", "sparams.csv"}
    assert r["tone_source"] == "port_ut_fallback"
    assert r["probes"]["port_ut_1B"]["tone"]["f_dominant_hz"] == _TONE_HZ


def test_analyze_tier_fallback_below_floor_tone_is_none(tmp_path):
    """判读诚实：晚窗电平低于 -60dB（EndCriteria 同源下限）时周期图峰不采信，
    主音按缺失处理（禁把噪声峰凑成 unmoved）。"""
    rng = np.random.default_rng(42)

    def vfn(t):
        return np.where(t <= 6.0e-9,
                        np.sin(2 * np.pi * _TONE_HZ * t),
                        1e-9 * rng.standard_normal(t.size))

    d = _make_fallback_dir(tmp_path / "dead_leg", v_fn=vfn)
    r = vj.analyze_tier(d)
    tone = r["probes"]["port_ut_1B"]["tone"]
    assert tone["f_dominant_hz"] is None
    assert "f_dominant_hz_missing_reason" in tone
    fb = r["fallback_tone"]
    assert fb["late_level_db_vs_post_peak"] <= -vj.END_DB_TARGET
    assert fb["tone_trusted"] is False


def test_analyze_tier_normal_path_zero_behavior(tmp_path):
    """正常路径（sparams 在）零行为钉：频域数值=测试内独立复算 + tone 同值 +
    新增键只增不改（tone_source=standard / missing 空 / fallback_tone None）。"""
    d = _make_normal_dir(tmp_path / "a3_board")
    r = vj.analyze_tier(d)
    assert r["tone_source"] == "standard"
    assert r["missing_artifacts"] == []
    assert r["fallback_tone"] is None
    sp = r["sparams"]
    assert "available" not in sp                      # 正常路径不带降级标记
    assert sp["s11_min"] == pytest.approx(0.2, abs=1e-12)
    assert sp["s11_min_ghz"] == 2.5
    assert sp["n_viol_gt1"] == 0
    assert sp["violation_frac"] == pytest.approx(0.0)
    assert sp["n_freq"] == 101
    assert sp["band_ghz"] == [2.0, 3.0]
    tone = r["probes"]["port_ut_1B"]["tone"]
    assert tone["f_dominant_hz"] == _TONE_HZ
    en = r["energy_log"]
    assert en["found"] is True
    assert en["shape_class"] == "slow_ring"           # 常数平台能量序列
    assert en["slosh_half_matches_tone"] in (True, False)
    gm = r["gamma"]
    assert gm["scan_direction"] in ("improves", "worsens", "flat")
    assert len(gm["truncation_scan"]) == 5
    # 旧契约键面完整（新增键只增不改——零行为）
    assert set(r) >= {"run_dir", "oe_result", "t_excite_end_ns", "probes",
                      "dc_drift", "energy_log", "sparams", "gamma", "stderr"}


def test_locate_judge_refresh_fallback_and_idempotent(tmp_path):
    """locate-judge 幂等刷新（零求解）：触帽腿伪 vanished→unmoved（fallback
    注记）+ 正常腿复验零行为 + 产物缺腿保留原读数 + 旧 verdict 留痕 .bak +
    classify 判别树语义不变（全 unmoved→器件局域囚禁模分支）。"""
    base = tmp_path / "trapped_mode_locate"
    base.mkdir()
    _make_fallback_dir(base / "a1_pml")
    _make_fallback_dir(base / "a2_airtop")
    d3 = _make_normal_dir(base / "a3_board")
    (d3 / "oe_result.json").write_text(json.dumps(
        {"leg": "a3_board", "solve_success": True,
         "engine": {"dt_s": 1.94e-13, "nrts": 100000,
                    "iterations_done": 50000, "hit_nrts_limit": False},
         "budget": {"wall_actual_s": 4196.3}, "preflight": {"ok": True},
         "tone_f_ghz": 2.71, "shape_class": None}), encoding="utf-8")
    base_l0 = base / "l0_dump"                        # 产物缺失腿：只有判读行
    base_l0.mkdir()
    (base_l0 / "oe_result.json").write_text(json.dumps(
        {"leg": "l0_dump", "budget": {"wall_actual_s": 3417.3},
         "preflight": {"ok": True}, "tone_f_ghz": 2.71}), encoding="utf-8")

    rc = vsm.cmd_locate_judge(tmp_path)
    assert rc == 0
    vd = json.loads((base / "locate_verdict.json").read_text(encoding="utf-8"))
    lg = vd["legs"]
    # 触帽腿：伪 vanished → 实测 unmoved（fallback 证据路径注记）
    for k in ("a1_pml", "a2_airtop"):
        assert lg[k]["class"] == "unmoved"
        assert lg[k]["tone_f_ghz"] == pytest.approx(2.71)
        assert lg[k]["tone_source"] == "port_ut_fallback"
        tr = lg[k]["tone_refresh"]
        assert tr["prior_tone_f_ghz"] is None
        assert tr["missing_artifacts"] == ["sparams.csv"]
    # 正常腿：同核确定性复验，读数不变
    assert lg["a3_board"]["class"] == "unmoved"
    assert lg["a3_board"]["tone_refresh"]["prior_tone_f_ghz"] == pytest.approx(2.71)
    assert lg["a3_board"]["tone_source"] == "standard"
    # 产物缺失腿：复提提不出音 → 保留原读数不冒充主音缺失
    assert lg["l0_dump"]["class"] == "unmoved"
    assert lg["l0_dump"]["tone_refresh"]["kept_prior_tone"] is True
    # classify 判别树语义不变：全 unmoved → 器件局域囚禁模分支（预声明矩阵行）
    assert "器件局域囚禁模" in vd["conclusion"]
    md = (base / "locate_verdict.md").read_text(encoding="utf-8")
    assert "tone_source=port_ut_fallback" in md
    assert "降级证据" in md

    # 幂等：二跑分类/结论不变；旧版留痕 .bak（首见即钉——三跑后 .bak 仍=一跑
    # 输出，原始判读证据不随复跑滚动丢失）
    md1 = md.replace(vd["finished"], "")
    rc2 = vsm.cmd_locate_judge(tmp_path)
    assert rc2 == 0
    assert (base / "locate_verdict.md.bak").is_file()
    assert (base / "locate_verdict.json.bak").is_file()
    bak_md_1 = (base / "locate_verdict.md.bak").read_text(encoding="utf-8")
    vd2 = json.loads((base / "locate_verdict.json").read_text(encoding="utf-8"))
    assert {k: v2["class"] for k, v2 in vd2["legs"].items()} == \
        {k: v["class"] for k, v in vd["legs"].items()}
    assert vd2["conclusion"] == vd["conclusion"]
    md2 = (base / "locate_verdict.md").read_text(encoding="utf-8")
    assert md2.replace(vd2["finished"], "") == md1
    vsm.cmd_locate_judge(tmp_path)
    assert (base / "locate_verdict.md.bak").read_text(encoding="utf-8") == bak_md_1
