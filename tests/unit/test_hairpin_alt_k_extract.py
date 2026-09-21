"""hairpin_alt 逐点 k 提取（双口径）+ 锚选点规则离线单测（零真机/零网络，#212）。

裁判（#118 独立来源，门自设依据逐条注明）：
  ① k_Z 公式闭式回代 + SNL 噪声放大实证：对 KJ 闭式 Z0e/Z0o 注入 ±0.5Ω 扰动，
    弱耦点（gap=2.2mm，ΔZ0≈1.93Ω）k 漂移复现 #361⑥ 结论（"±0.5Ω 阻抗噪声→
    ±30% 量级不确定度"；同源实证=runs/hairpin_hfss_anchor chain_check 2.2 的
    k_z_dev_pct=31.3%）。门依据：单边实测 26.5%→门 [20,35]；最坏对（两阻抗反
    号）实测 51.8%→门 [45,60]（放大量级上限）；强耦端 gap=0.5mm（ΔZ0≈12.0Ω）
    实测单边 4.7%→门 ≤8 作对照（SNL 放大随 ΔZ0 收窄单调增长的秩序性另钉）。
  ② 合成双峰已知量回收：峰位构造值已知的双 Lorentz → k_split 回代（门 5%：
    格点量化界 grid_quantization_k≈1.7% × Lorentz 峰位近似余量，#118 合成回收
    钉）；对称 2 极模型已知 k → 直接 k_split 低估（pull 签名）+ pull 修正回收
    ≤2%（pull 曲线 40 点线性内插+峰位量化，k∈[0.05,0.12] 扫描实测 max|err|
    =1.03%）。
  ③ 锚选点规则确定性：同一输入重复调用逐位一致；去重/顺延/并列取小 gap
    分支各用合成行钉住。
  ④ 真机归档回归钉（runs/hairpin_kgap_refix 6 曲线端到端；gitignore 资产，
    缺失自动 skip，不构成网络/真机依赖）。
"""
from __future__ import annotations

import copy
import importlib.util
import json
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_hairpin_alt_k_extract",
    str(Path(__file__).resolve().parents[2] / "scripts" / "hairpin_alt_k_extract.py"))
assert _SPEC is not None and _SPEC.loader is not None
kx = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kx)

F0_HZ = 2.5e9
GRID = np.linspace(2.0e9, 3.2e9, 401)            # 引擎同款 401 点
QE, QU = 34.69064166747507, 236.34736862539347   # tau043 归档同源
ARCHIVE_ROOT = Path(__file__).resolve().parents[2] / "runs" / "hairpin_kgap_refix"


def _two_lorentz(freq_hz: np.ndarray, f1_hz: float, f2_hz: float,
                 q_l: float, s1: float, s2: float) -> np.ndarray:
    d1 = (np.asarray(freq_hz, dtype=float) - f1_hz) / f1_hz
    d2 = (np.asarray(freq_hz, dtype=float) - f2_hz) / f2_hz
    return s1 / np.sqrt(1.0 + (2.0 * q_l * d1) ** 2) \
        + s2 / np.sqrt(1.0 + (2.0 * q_l * d2) ** 2)


# ── ① k_Z 公式与 SNL 噪声放大（#361⑥ 实证）───────────────────────────


def test_k_z_formula_closed_form():
    """k_Z=(Z0e−Z0o)/(Z0e+Z0o) 闭式回代（独立手算对照）+ 病态入参拒绝。"""
    assert kx.k_z_from_impedances(55.67943, 43.65423) == pytest.approx(
        (55.67943 - 43.65423) / (55.67943 + 43.65423), rel=1e-12)
    assert kx.k_z_from_impedances(55.67943, 43.65423) == pytest.approx(
        0.121059, rel=1e-5)   # gap=0.5mm KJ 量级（归档 k_KJ 同源）
    with pytest.raises(ValueError):
        kx.k_z_from_impedances(40.0, 50.0)      # 偶模阻抗必须较高（#307）
    with pytest.raises(ValueError):
        kx.k_z_from_impedances(-1.0, 50.0)


def test_kj_impedances_self_consistent_with_core():
    """k_Z 闭式与 core hairpin_k_from_gap_mm 同源自证（1e-9；内核内断言双保险）。"""
    for gap in (0.5, 0.8, 1.1328, 1.6, 2.2):
        kj = kx.kj_impedances(gap)
        assert kj["k_z_kj"] == pytest.approx(
            kx.hairpin_k_from_gap_mm(gap, 1.1117, 2.5), rel=1e-9)
        assert kj["delta_z0_ohm"] > 0.0
    # ΔZ0 随 gap 单调收窄（SNL 放大的物理来源）
    deltas = [kx.kj_impedances(g)["delta_z0_ohm"] for g in (0.5, 0.8, 1.1328, 1.6, 2.2)]
    assert all(b < a for a, b in pairwise(deltas))


def test_k_z_noise_amplification_reproduces_361():
    """#361⑥ 实证：±0.5Ω 阻抗噪声 → 弱耦点 k 漂移 ±30% 量级（门依据见模块 docstring①）。"""
    weak = kx.k_z_noise_drift_pct(*_imp(2.2))     # ΔZ0≈1.93Ω（最弱耦端）
    assert weak["single_sided_max_pct"] == pytest.approx(26.5, abs=5.0)
    assert 20.0 <= weak["single_sided_max_pct"] <= 35.0
    assert 45.0 <= weak["worst_pair_pct"] <= 60.0   # 两阻抗反号=放大量级上限
    strong = kx.k_z_noise_drift_pct(*_imp(0.5))   # ΔZ0≈12.0Ω（强耦端对照）
    assert strong["single_sided_max_pct"] <= 8.0
    assert strong["worst_pair_pct"] <= 12.0
    # 秩序性：SNL 放大随 gap（ΔZ0 收窄）单调增长
    singles = [kx.k_z_noise_drift_pct(*_imp(g))["single_sided_max_pct"]
               for g in (0.5, 0.8, 1.1328, 1.6, 2.2)]
    assert all(b > a for a, b in pairwise(singles))
    # 确定性：同入参逐位复现
    again = kx.k_z_noise_drift_pct(*_imp(2.2))
    assert again == weak


def _imp(gap_mm: float) -> tuple[float, float]:
    kj = kx.kj_impedances(gap_mm)
    return kj["z0e_ohm"], kj["z0o_ohm"]


# ── ② 合成双峰已知量回收（#118 钉）───────────────────────────────────


def test_synthetic_doublet_recovery():
    """峰位构造已知的双峰 → k_split 回代 ≤5%（量化界 ~1.7% × 峰位近似余量）。"""
    f1, f2 = 2.411e9, 2.585e9
    mag = _two_lorentz(GRID, f1, f2, q_l=40.0, s1=0.907, s2=0.762)
    res = kx.aks.alt_ksplit_point(GRID, mag.astype(complex), QE, QU, 0.08)
    assert res["k_split"] is not None
    k_true = 2.0 * (f2 - f1) / (f2 + f1)
    assert res["k_split"] == pytest.approx(k_true, rel=0.05)
    assert res["mode_pair"]["quality"] == "resolved"


def test_symmetric_model_pull_correction_recovery():
    """对称模型已知 k → 直接 k_split 系统性低估（pull 签名）；pull 修正回收 ≤2%。

    门依据：pull 曲线 40 点线性内插+峰位格点量化，k∈[0.05,0.12] 扫描实测
    max|err|=1.03%（2% 门留一倍余量；#118 合成已知量回收钉）。
    """
    for k_true in (0.05, 0.08, 0.12):
        s21_db, _ = kx.aks.hqx().coupled_model_s_db(GRID, F0_HZ, k_true, QE, 2, QU)
        pair = kx.aks.find_mode_pair(GRID, s21_db)
        assert pair["f2_ghz"] is not None, f"k={k_true} 应可分裂"
        k_direct, _ = kx.aks.k_split_from_pair(pair["f1_ghz"] * 1e9, pair["f2_ghz"] * 1e9)
        assert k_direct < k_true                        # pull 低估签名（方向）
        pull = kx.aks.model_pull_curve(F0_HZ, QE, QU, GRID)
        k_corr = kx.aks.invert_pull_curve(pull, k_direct)
        assert k_corr == pytest.approx(k_true, rel=0.02)


# ── ③ 锚选点规则确定性 ───────────────────────────────────────────────


def _mk_row(gap: float, pt: str, *, anchored=False, in_map=True, k_split=None):
    return {"gap_mm": gap, "pt_id": pt,
            "anchor": ({"k_split_eigen_hfss": 0.01} if anchored else None),
            "in_gap_map": in_map, "primary_value": k_split}


def test_anchor_selection_deterministic():
    """选点规则确定性（重复调用逐位一致）+ 各分支（未锚中部/k 最大/去重顺延/并列）。"""
    rows = [_mk_row(0.5, "a", anchored=True, k_split=0.0696),
            _mk_row(0.8, "b", anchored=True, k_split=0.0348),
            _mk_row(1.1328, "c", anchored=True),
            _mk_row(1.6, "d"),
            _mk_row(2.2, "e", anchored=True)]
    picks = kx.select_anchor_candidates(rows)
    assert picks == kx.select_anchor_candidates(copy.deepcopy(rows))
    assert [(p["slot"], p["gap_mm"]) for p in picks] == [
        ("n1_middle", 1.6), ("n2_kmax_resolved", 0.5)]
    assert picks[1]["role"].startswith("复仲裁")     # 0.5 已锚 → 复仲裁角色
    # 并列取小 gap：已锚 {2.0}，未锚 {1.0, 3.0} 等距 → 取小 gap 1.0
    rows_tie = [_mk_row(2.0, "t1", anchored=True), _mk_row(1.0, "t2"), _mk_row(3.0, "t3")]
    picks_tie = kx.select_anchor_candidates(rows_tie)
    assert picks_tie[0]["gap_mm"] == 1.0
    # n1/n2 重合去重：唯一未锚点恰是 k 最大点 → n2 顺延 k 序次优（u2）
    rows_dedup = [_mk_row(0.5, "u1", k_split=0.09),
                  _mk_row(1.0, "u2", anchored=True, k_split=0.05)]
    picks_dedup = kx.select_anchor_candidates(rows_dedup)
    assert [p["slot"] for p in picks_dedup] == ["n1_middle", "n2_kmax_resolved"]
    assert [p["pt_id"] for p in picks_dedup] == ["u1", "u2"]
    assert picks_dedup[1]["role"].startswith("复仲裁")   # u2 已锚 → 复仲裁角色
    # 无候选（全锚/无解析点）→ 如实少选
    assert [p["slot"] for p in kx.select_anchor_candidates(
        [_mk_row(0.5, "x", anchored=True)])] == []


# ── ④ 真机归档回归钉 ─────────────────────────────────────────────────


@pytest.mark.skipif(not (ARCHIVE_ROOT / "kgapalt_g0500" / "sparams.csv").exists(),
                    reason="真机归档 runs/hairpin_kgap_refix 不在检出版本内（gitignore 资产）")
def test_real_archive_per_point_rows():
    """6 曲线端到端逐点提取回归钉：k_split 逐位复现/合并判定/截断不采信/锚定表。"""
    result = kx.analyze(ARCHIVE_ROOT)
    rows = {r["pt_id"]: r for r in result["points"]}
    assert len(rows) == 6
    vd = result["verdict"]
    assert vd["primary_caliber"] == "k_split"
    assert vd["n_map_points"] == 5 and vd["n_untrusted_truncation"] == 1
    assert vd["n_split_resolved"] == 1 and vd["n_split_shallow"] == 1
    assert vd["n_merged"] == 3
    # g0500：确定性逐位复现（本口径历史复算值，test_hairpin_alt_ksplit 同源）
    assert rows["kgapalt_g0500"]["k_split"]["value"] == \
        pytest.approx(0.06965572457966374, rel=1e-9)
    assert rows["kgapalt_g0500"]["anchor"]["dev_split_vs_eigen_pct"] == \
        pytest.approx(-8.7, abs=0.1)
    # g2200：合并 + k_Z SNL 支配 + HFSS line2t 双 basis
    r22 = rows["kgapalt_g2200"]
    assert r22["k_split"]["merged"] is True and r22["primary_value"] is None
    assert r22["k_z"]["snl"]["snl_dominant"] is True
    assert r22["k_z"]["k_hfss_line2t"] == pytest.approx(0.025363855621157023, rel=1e-9)
    # 截断变体：max|S11|=1.0204 >1 → untrusted（primary 不出值），正式 350k 曲线不受牵连
    rt = rows["kgapalt_g11328_trunc100k"]
    assert rt["truncated"] is True and rt["max_abs_s11"] == pytest.approx(1.0204, abs=1e-3)
    assert rt["primary_value"] is None
    assert rows["kgapalt_g11328"]["truncated"] is False
    # 锚定 c_true 表（4 点，与两批 HFSS 锚归档逐位同源）
    assert sorted(vd["anchored_gaps"]) == [0.5, 0.8, 1.1328, 2.2]
    assert vd["c_true_anchored"]["0.5"] == pytest.approx(0.6299, abs=1e-3)
    assert vd["c_true_anchored"]["2.2"] == pytest.approx(0.5468, abs=1e-3)
    assert vd["kz_snl_dominant_gaps"] == [1.6, 2.2]


@pytest.mark.skipif(not (ARCHIVE_ROOT / "kgapalt_g0500" / "sparams.csv").exists(),
                    reason="真机归档 runs/hairpin_kgap_refix 不在检出版本内（gitignore 资产）")
def test_anchor_plan_deterministic_and_contract():
    """锚任务书：选点 (1.6, 0.5)、κ 线内插预期、重复产出逐位一致（JSON 级）。"""
    result = kx.analyze(ARCHIVE_ROOT)
    plan = kx.build_anchor_plan(result, ARCHIVE_ROOT)
    plan2 = kx.build_anchor_plan(kx.analyze(ARCHIVE_ROOT), ARCHIVE_ROOT)
    assert json.dumps(plan, sort_keys=True) == json.dumps(plan2, sort_keys=True)
    cands = plan["candidates"]
    assert [(c["slot"], c["gap_mm"]) for c in cands] == [
        ("n1_middle", 1.6), ("n2_kmax_resolved", 0.5)]
    n1 = cands[0]
    assert n1["geometry"]["gap_mm"] == 1.6 and n1["geometry"]["w_mm"] == 1.1117
    assert n1["geometry"]["tap_frac"] == 0.43
    # κ 线内插预期：c_true(1.6)∈(c_true(1.1328), c_true(2.2))，k_pred=c_pred·k_KJ
    assert n1["expected"]["c_true_interp"] == pytest.approx(0.5719, abs=1e-3)
    assert n1["expected"]["k_pred"] == pytest.approx(
        n1["expected"]["c_true_interp"]
        * kx.hairpin_k_from_gap_mm(1.6, 1.1117, 2.5), rel=1e-9)
    assert n1["expected"]["k_pred_interval_pct"] == 15.0
    assert n1["expected"]["openems_plausible_interval"][0] == \
        pytest.approx(0.019551346247946595, rel=1e-9)
    n2 = cands[1]
    assert n2["expected"]["k_eigen_previous"] == pytest.approx(0.07625418440361244, rel=1e-9)
    assert n2["expected"]["reproduce_gate_pct"] == 5.0
