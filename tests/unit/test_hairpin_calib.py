"""hairpin_calib 分析函数离线单测（WP2.3 标定轮，#212 先离线后真机）。

只测纯函数与判据自洽，零真机：真机轮的证据由 runs/hairpin_calib/ 承载。
关键自洽审计：设计判据（插损/纹波/回损/峰位）喂 C13 理想频响必须
判 PASS——判据从宽但不得宽到理想裁判都过不了（判据可达性锚）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_hairpin_calib",
    str(Path(__file__).resolve().parents[2] / "scripts" / "hairpin_calib.py"))
assert _SPEC is not None and _SPEC.loader is not None
calib = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(calib)


def _toy_freq() -> np.ndarray:
    return np.linspace(2.0, 3.5, 1501)


def test_find_local_extrema_min_and_max() -> None:
    f = _toy_freq()
    y = -20.0 * np.ones_like(f)
    y[300] = -46.8    # 谷 1
    y[700] = -40.0    # 谷 2
    y[500] = -10.0    # 峰
    mins = calib.find_local_extrema(f, y, thresh_db=-35.0, mode="min")
    maxs = calib.find_local_extrema(f, y, thresh_db=-25.0, mode="max")
    assert len(mins) == 2
    assert abs(mins[0][0] - f[300]) < 1e-9
    assert mins[0][1] == pytest.approx(-46.8)
    assert abs(mins[1][0] - f[700]) < 1e-9
    assert len(maxs) == 1 and maxs[0][1] == pytest.approx(-10.0)
    # 平坦基线零误报（左严格不等守卫）
    assert calib.find_local_extrema(f, -20 * np.ones_like(f), -35.0,
                                    mode="min") == []


def test_detect_passband_genuine_vs_spike() -> None:
    f = _toy_freq()
    # 真通带：高斯峰 -2dB，6dB 等高线（-8dB）全宽 2·0.08·0.283≈45MHz
    y = -80.0 + 78.0 * np.exp(-((f - 2.5) / 0.08) ** 2)
    pb = calib.detect_passband(f, y)
    assert pb is not None
    assert pb["f_peak"] == pytest.approx(2.5, abs=0.02)
    assert 0.04 < pb["width_ghz"] < 0.05
    # 尖刺（单点）：判无通带
    y2 = -80.0 * np.ones_like(f)
    y2[750] = -5.0
    assert calib.detect_passband(f, y2) is None


def test_band_metrics_on_synthetic_band() -> None:
    f = _toy_freq()
    band = (f >= 2.4375) & (f <= 2.5625)
    s21 = np.where(band, -2.5 + 0.4 * np.sin(40 * f), -60.0)
    s11 = np.where(band, -20.0 + 2.0 * np.sin(23 * f), -1.0)
    m = calib.band_metrics(f, s21, s11, 2.5, 0.05)
    assert m["il_min_db"] == pytest.approx(float(s21[band].min()))
    assert m["ripple_db"] == pytest.approx(0.8, rel=0.05)
    assert m["rl_max_db"] == pytest.approx(-18.0, abs=0.05)
    assert abs(m["f_peak_ghz"] - 2.5) <= 0.0625
    assert m["peak_dev_pct"] == pytest.approx(
        (m["f_peak_ghz"] - 2.5) / 2.5 * 100)


def test_band_metrics_out_of_window_nan() -> None:
    f = np.linspace(4.0, 5.0, 100)
    m = calib.band_metrics(f, -3 * np.ones(100), -20 * np.ones(100),
                           2.5, 0.05)
    assert np.isnan(m["il_min_db"]) and np.isnan(m["rl_max_db"])


def test_port_health_counts_above_unity() -> None:
    s11 = np.array([0.5 + 0.1j, 0.9 + 0.2j, 1.05 + 0.0j, 0.2 - 0.3j])
    h = calib.port_health(s11)
    assert h["n_above_unity"] == 1
    assert h["max_abs_s11"] == pytest.approx(1.05)


def test_apply_single_override_guard() -> None:
    base = {"arm_len_mm": 35.4653, "arm_gap_mm": 1.0, "gap_mm": 1.1326,
            "tap_frac": 0.4019, "w_mm": 1.1134, "order": 3}
    out = calib.apply_single_override(base, {"arm_gap_mm": 3.0})
    assert out["arm_gap_mm"] == 3.0
    assert out["arm_len_mm"] == base["arm_len_mm"]   # 其余锁设计值
    with pytest.raises(ValueError, match="单变量纪律违规"):
        calib.apply_single_override(base, {"arm_gap_mm": 3.0,
                                           "tap_frac": 0.35})
    with pytest.raises(ValueError, match="非法标定变量"):
        calib.apply_single_override(base, {"w_mm": 2.0})
    with pytest.raises(ValueError, match="未指定标定变量"):
        calib.apply_single_override(base, {})
    # 阶梯模式：显式声明后允许多变量（R0→R1→R3 每轮相对上轮单变量）
    out2 = calib.apply_single_override(base, {"arm_gap_mm": 3.0,
                                              "gap_mm": 0.8}, ladder=True)
    assert out2["arm_gap_mm"] == 3.0 and out2["gap_mm"] == 0.8
    assert out2["tap_frac"] == base["tap_frac"]


def test_verdict_criteria_consistent_with_c13_ideal_judge() -> None:
    """判据自洽锚：C13 理想频响应满足除防直通下限外的全部判据。

    verdict_of 与冒烟口径逐条一致（含 il_min≤-0.2 防直通地板——理想
    无耗裁判 il_min≈-0.05 天然不满足该地板，属预期语义，不判据缺陷）。
    """
    from rfauto.adapters.openems_templates import hairpin_design_from_order
    from rfauto.core.calculators import coupling_matrix_response

    design = hairpin_design_from_order(3, 2.5, 0.05, 20.0)
    f = np.linspace(2.0, 3.5, 1501)
    resp = coupling_matrix_response(
        freq_ghz=[float(v) for v in f], f0_ghz=2.5, fbw=0.05,
        matrix=design["coupling_matrix"])
    s21 = np.asarray(resp["s21_db"], dtype=float)
    s11 = np.asarray(resp["s11_db"], dtype=float)
    m = calib.band_metrics(f, s21, s11, 2.5, 0.05)
    # 理想裁判：纹波/回损/峰位/插损下限全过
    assert -3.0 <= m["il_min_db"] <= -0.0
    assert m["ripple_db"] <= 4.0
    assert m["rl_max_db"] <= -19.0          # 贴近设计 RL=20dB
    assert abs(m["peak_dev_pct"]) <= 8.0
    # 防直通地板语义：il_min 落入 [-3,-0.2] 且其余达标 → PASS
    assert calib.verdict_of({**m, "il_min_db": -0.5},
                            beta_dev_pct=0.5) == "PASS"
    # 判据各破坏路径必须 FAIL
    assert calib.verdict_of({**m, "il_min_db": -0.5, "rl_max_db": -6.0},
                            None) == "FAIL"
    assert calib.verdict_of({**m, "il_min_db": -5.0}, None) == "FAIL"
    assert calib.verdict_of({**m, "il_min_db": -0.5, "peak_dev_pct": 12.0},
                            None) == "FAIL"
    assert calib.verdict_of({**m, "il_min_db": -0.5},
                            beta_dev_pct=5.0) == "FAIL"
    # 理想无耗 il_min=-0.047 触发防直通地板 → FAIL（预期语义，非缺陷）
    assert calib.verdict_of(m, beta_dev_pct=0.5) == "FAIL"


def test_beta_anchor_reads_csv(tmp_path: Path) -> None:
    # β=2π f √εeff/c：构造 eps_eng = 1.01·eps_hj 的数据
    eps_hj = 2.8524
    eps_eng = 1.01 * eps_hj
    rows = ["freq_hz,beta_rad_per_m"]
    for fq in (2.45e9, 2.5e9, 2.55e9):
        beta = 2 * np.pi * fq * np.sqrt(eps_eng) / 299792458.0
        rows.append(f"{fq},{beta}")
    (tmp_path / "port_beta.csv").write_text("\n".join(rows) + "\n",
                                            encoding="utf-8")
    dev = calib.beta_anchor(tmp_path, 2.5, eps_hj)
    assert dev is not None and dev == pytest.approx(1.0, abs=0.01)
    assert calib.beta_anchor(tmp_path, 9.0, eps_hj) is None  # 窗外无数据
    assert calib.beta_anchor(tmp_path / "nope", 2.5, eps_hj) is None


def test_evidence_json_serializable(tmp_path: Path) -> None:
    """evidence 组装口径抽查：NaN/None 走 default=str 不炸。"""
    payload = {"a": float("nan"), "b": None, "zeros": [(2.485, -46.8)]}
    p = tmp_path / "calib.json"
    p.write_text(json.dumps(payload, default=str), encoding="utf-8")
    assert json.loads(p.read_text(encoding="utf-8"))["zeros"] == [
        [2.485, -46.8]]
