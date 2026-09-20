"""hairpin_alt_ksplit 纯函数离线单测（#212 先离线，零真机/零网络）。

裁判（#118 独立来源）：
  ① 分裂公式闭式回代：手算 2|f2−f1|/(f2+f1) 与平方变体逐位对照；
  ② 合成双 Lorentz 叠加曲线（峰位构造值已知）→ find_mode_pair 回代峰位/合并判定；
  ③ 对称 2 极有耗模型（hairpin_q_extract.coupled_model_s_db 复用）的 k_merge
    bisection 自洽（下界单峰/上界双峰）+ pull 曲线单调且 k_direct<k_true、
    可逆域内 round-trip 回代；
  ④ 真机归档回归钉（runs/hairpin_kgap_refix g0500 双峰/g2200 合并；归档为
    gitignore 资产，缺失自动 skip，不构成网络/真机依赖）。
网格取引擎同款（渲染脚本固定 401 点，2.0-3.2GHz → 3MHz 步）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_hairpin_alt_ksplit",
    str(Path(__file__).resolve().parents[2] / "scripts" / "hairpin_alt_ksplit.py"))
assert _SPEC is not None and _SPEC.loader is not None
aks = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(aks)

F0_HZ = 2.5e9
GRID = np.linspace(2.0e9, 3.2e9, 401)            # 引擎同款 401 点
ARCHIVE_ROOT = Path(__file__).resolve().parents[2] / "runs" / "hairpin_kgap_refix"
QE, QU = 34.69064166747507, 236.34736862539347   # tau043 归档同源（kgap_curve.json）


def _two_lorentz(freq_hz: np.ndarray, f1_hz: float, f2_hz: float,
                 q_l: float, s1: float, s2: float) -> np.ndarray:
    """两个 Lorentz 峰的幅度叠加（Δf ≫ 线宽时峰位≈f1/f2；合成裁判用）。"""
    d1 = (np.asarray(freq_hz, dtype=float) - f1_hz) / f1_hz
    d2 = (np.asarray(freq_hz, dtype=float) - f2_hz) / f2_hz
    return s1 / np.sqrt(1.0 + (2.0 * q_l * d1) ** 2) \
        + s2 / np.sqrt(1.0 + (2.0 * q_l * d2) ** 2)


def test_k_split_formula_closed_form():
    """分裂公式闭式回代：k=2|f2−f1|/(f2+f1) 与平方变体（独立手算对照）。"""
    f1, f2 = 2.411e9, 2.585e9
    k, k_sq = aks.k_split_from_pair(f1, f2)
    assert k == pytest.approx(2.0 * (f2 - f1) / (f2 + f1), rel=1e-12)
    assert k_sq == pytest.approx((f2 ** 2 - f1 ** 2) / (f2 ** 2 + f1 ** 2), rel=1e-12)
    assert k == pytest.approx(0.0696557, rel=1e-6)   # 锚点 g0500 量级（0.348/4.996）
    # 反序/同频
    k_rev, _ = aks.k_split_from_pair(f2, f1)
    assert k_rev == pytest.approx(k, rel=1e-12)
    assert aks.k_split_from_pair(f1, f1) == (0.0, 0.0)
    with pytest.raises(ValueError):
        aks.k_split_from_pair(-1.0, f2)


def test_find_mode_pair_synthetic_doublet_and_single():
    """合成双峰→峰位回代（≤半个格步）+ resolved 判级；单峰→如实 merged。"""
    f1, f2 = 2.411e9, 2.585e9
    mag = _two_lorentz(GRID, f1, f2, q_l=40.0, s1=0.907, s2=0.762)
    pair = aks.find_mode_pair(GRID, 20.0 * np.log10(mag + 1e-12))
    assert pair["n_candidates"] == 2
    step_ghz = float(GRID[1] - GRID[0]) / 1e9
    assert pair["f1_ghz"] == pytest.approx(f1 / 1e9, abs=step_ghz)
    assert pair["f2_ghz"] == pytest.approx(f2 / 1e9, abs=step_ghz)
    assert pair["quality"] == "resolved"
    k, _ = aks.k_split_from_pair(pair["f1_ghz"] * 1e9, pair["f2_ghz"] * 1e9)
    assert k == pytest.approx(2.0 * (f2 - f1) / (f2 + f1), rel=0.05)  # 格点量化容差
    # 单 Lorentz → 单峰合并（浅峰第二模不存在的形态）
    d = (GRID - F0_HZ) / F0_HZ
    mag1 = 0.5 / np.sqrt(1.0 + (2.0 * 16.0 * d) ** 2)
    single = aks.find_mode_pair(GRID, 20.0 * np.log10(mag1 + 1e-12))
    assert single["n_candidates"] == 1 and single["f2_ghz"] is None
    assert single["quality"] == "single_peak" and single["valley_depth_db"] is None


def test_model_merge_threshold_and_pull_curve():
    """k_merge bisection 自洽 + pull 曲线单调/低估方向/可逆域 round-trip。"""
    k_merge = aks.model_merge_threshold(F0_HZ, QE, QU, GRID)
    assert 0.03 < k_merge < 0.06                     # 归档 5 点实测 0.0466 量级
    s_lo, _ = aks.hqx().coupled_model_s_db(GRID, F0_HZ, k_merge - 0.005, QE, 2, QU)
    s_hi, _ = aks.hqx().coupled_model_s_db(GRID, F0_HZ, k_merge + 0.01, QE, 2, QU)
    assert aks.find_mode_pair(GRID, s_lo)["n_candidates"] < 2
    assert aks.find_mode_pair(GRID, s_hi)["n_candidates"] >= 2
    # pull 曲线：k_direct 全程 < k_true（加载拉动低估）且单调可逆；round-trip ≤2%
    pull = aks.model_pull_curve(F0_HZ, QE, QU, GRID)
    assert pull["monotone"] and pull["n_invertible"] >= 5
    kt = np.asarray(pull["k_true"])
    kd = np.asarray(pull["k_direct"])
    assert np.all(kd < kt)
    for k_true, k_direct in ((0.07, float(np.interp(0.07, kt, kd))),
                             (0.10, float(np.interp(0.10, kt, kd)))):
        assert aks.invert_pull_curve(pull, k_direct) == pytest.approx(k_true, rel=0.02)
    # 域外（低于可逆域下限/高于上限）如实 None
    assert aks.invert_pull_curve(pull, kd[0] * 0.5) is None
    assert aks.invert_pull_curve(pull, kd[-1] * 1.5) is None


def test_alt_ksplit_point_merged_interval_bounds():
    """合并点主入口：k_split=None + 参照区间 [k_ref, k_merge]（含 k_ref 透传留痕）。"""
    d = (GRID - F0_HZ) / F0_HZ
    mag = 0.5 / np.sqrt(1.0 + (2.0 * 16.0 * d) ** 2)   # 单峰形态（Q_L≈16）
    res = aks.alt_ksplit_point(GRID, mag.astype(complex), QE, QU, 0.01931154,
                               k_ref=0.01955, k_ref_method="peak_level",
                               k_ref_verdict="OK")
    assert res["merged"] is True and res["k_split"] is None
    lo, hi = res["k_plausible_interval"]
    assert lo == pytest.approx(0.01955, rel=1e-12)
    assert hi == pytest.approx(res["k_merge_symmodel"], rel=1e-12)
    assert 0.03 < hi < 0.06
    assert res["c_ref"] == pytest.approx(0.01955 / 0.01931154, rel=1e-9)


_REAL_G0500_K_SPLIT = 0.06965572457966374   # 归档 kgapalt_g0500 实测（本口径确定性复算值）


@pytest.mark.skipif(not (ARCHIVE_ROOT / "kgapalt_g0500" / "sparams.csv").exists(),
                    reason="真机归档 runs/hairpin_kgap_refix 不在检出版本内（gitignore 资产）")
def test_real_archive_regression_pins():
    """真机归档回归钉：g0500 双峰 k_split 逐位复现 + c_alt；g2200 合并判定与区间。"""
    f, s21 = aks.read_sparams_csv(ARCHIVE_ROOT / "kgapalt_g0500" / "sparams.csv")
    res = aks.alt_ksplit_point(f, s21, QE, QU, 0.12105867594345493,
                               k_ref=0.09337262219905676, k_ref_method="full_fit",
                               k_ref_verdict="WIDTH_FAIL")
    assert res["k_split"] == pytest.approx(_REAL_G0500_K_SPLIT, rel=1e-9)
    assert res["mode_pair"]["quality"] == "resolved"
    assert res["mode_pair"]["valley_depth_db"] == pytest.approx(3.16, abs=0.01)
    assert res["c_alt"] == pytest.approx(0.57539, rel=1e-4)
    assert res["k_split_pull_corrected"] == pytest.approx(0.076903, rel=1e-4)
    f2, s21_2 = aks.read_sparams_csv(ARCHIVE_ROOT / "kgapalt_g2200" / "sparams.csv")
    res2 = aks.alt_ksplit_point(f2, s21_2, QE, QU, 0.01931153860983805,
                                k_ref=0.01102195585422419, k_ref_method="peak_level",
                                k_ref_verdict="OK")
    assert res2["merged"] is True and res2["k_split"] is None
    lo, hi = res2["k_plausible_interval"]
    assert lo == pytest.approx(0.01102195585422419, rel=1e-9)
    assert 0.04 < hi < 0.05
