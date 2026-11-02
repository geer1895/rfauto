"""QM-8 锚漂移 SPC 三证据线（ge8b 席B8）：core/anchor_drift_spc 合同钉。

钉面：
1. **内核数学钉**（合成已知量回收，#118 纪律）——广义 ESD R₁ 恒等 Grubbs
   统计量、种植离群点精确回收；EWMA/CUSUM 阶跃检出步与方向、干净序列零
   误报；λ₁ 临界值对 NIST 公式独立重算（非同源实现）；
2. **诚实语义钉**——短序列（锚现状 1-4 点）三线一律不算（insufficient，
   不硬算）；σ 未声明时 EWMA/CUSUM skipped 且 ESD 照常可判；
3. **真库评估钉**——knowledge/anchors.yaml 全锚 n<8（2026-10-03 实测 34/34
   insufficient），runs/qm8_anchor_spc/assessment.json 落档形态一致。
"""
from __future__ import annotations

import importlib.util
import json
import math
import random
import statistics as st
from pathlib import Path

import pytest

from rfauto.core.anchor_drift_spc import (
    CUSUM_MIN_N,
    ESD_MIN_N,
    EWMA_MIN_N,
    SERIES_MIN_N,
    anchor_drift_spc_report,
    cusum_test,
    ewma_control,
    generalized_esd_test,
)

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "qm8_anchor_spc_assessment.py"

_spec = importlib.util.spec_from_file_location("qm8_anchor_spc_assessment",
                                               _SCRIPT)
qm8 = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(qm8)


def _seeded_base(n: int = 24, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    return [100.0 + rng.gauss(0, 1) for _ in range(n)]


# ─── ① 内核数学钉 ───────────────────────────────────────────────────────────


def test_esd_first_statistic_identity_with_grubbs() -> None:
    """R₁ 恒等 Grubbs 统计量 max|x−x̄|/s（同一数据两种独立算法）。"""
    x = _seeded_base()
    x[3], x[17] = 108.0, 109.0
    g = generalized_esd_test(x, max_outliers=1)
    mu, s = st.mean(x), st.stdev(x)
    assert g["eligible"] is True
    assert g["statistics"][0] == pytest.approx(
        max(abs(v - mu) for v in x) / s, rel=1e-9)


def test_esd_lambda1_independent_formula_recompute() -> None:
    """λ₁ 对 NIST 公式独立重算（scipy t 分位直调，非被测实现内部路径）。"""
    from scipy.stats import t as t_dist

    n, alpha = 24, 0.05
    p1 = 1.0 - alpha / (2.0 * (n - 1 + 1))
    t1 = float(t_dist.ppf(p1, n - 2))
    lam_expected = (n - 1) * t1 / math.sqrt((n - 2 + t1 * t1) * (n - 2))
    x = _seeded_base()
    lam = generalized_esd_test(x, max_outliers=1)["critical_values"][0]
    assert lam == pytest.approx(lam_expected, rel=1e-12)


def test_esd_planted_outliers_recovered() -> None:
    """种植离群点（+8/+9σ 于 N(100,1) 底噪）被精确回收（合成回收裁判）。"""
    x = _seeded_base()
    x[3], x[17] = 108.0, 109.0
    r = generalized_esd_test(x)
    assert r["n_outliers"] == 2
    assert sorted(r["outlier_indices"]) == [3, 17]
    clean = generalized_esd_test(_seeded_base())
    assert clean["n_outliers"] == 0 and clean["outlier_indices"] == []


def test_esd_short_series_not_computed() -> None:
    """n<10（ESD 有效域）→ eligible=False 不硬算（锚现状 1-4 点场景）。"""
    for n in (0, 1, 4, ESD_MIN_N - 1):
        r = generalized_esd_test([100.0 + 0.1 * i for i in range(n)])
        assert r["eligible"] is False
        assert "不硬算" in r["reason"]


def test_ewma_cusum_detect_shift_with_declared_sigma() -> None:
    """EWMA/CUSUM（显式 σ+target）：阶跃 +3.5σ 在阶跃后数步内以正确方向
    检出；干净序列零误报。"""
    base = _seeded_base()
    target = sum(base) / len(base)
    shifted = list(base)
    shift_at = 12
    shifted[shift_at:] = [v + 3.5 for v in shifted[shift_at:]]
    ew = ewma_control(shifted, sigma=1.0, target=target)
    cs = cusum_test(shifted, sigma=1.0, target=target)
    assert ew["signal"] is True
    assert shift_at + 1 <= ew["breach_at"] <= shift_at + 6
    assert cs["signal"] is True and cs["breach_side"] == "high"
    assert shift_at + 1 <= cs["breach_at"] <= shift_at + 6
    assert ewma_control(base, sigma=1.0, target=target)["signal"] is False
    assert cusum_test(base, sigma=1.0, target=target)["signal"] is False


def test_ewma_cusum_require_declared_sigma() -> None:
    """σ 未显式声明 → 两线 skipped（不从同序列内估 σ 虚构精度）；ESD 照常。"""
    x = _seeded_base()
    ew = ewma_control(x, sigma=None)
    cs = cusum_test(x, sigma=None)
    assert ew["eligible"] is False and "σ 未显式声明" in ew["reason"]
    assert cs["eligible"] is False and "σ 未显式声明" in cs["reason"]
    assert generalized_esd_test(x)["eligible"] is True  # 自标准化线不受影响


def test_report_combination_and_honest_short_series() -> None:
    """组合规则钉：≥2 线命中=drifted / 1=warning / 0=stable；
    n<SERIES_MIN_N=insufficient 且 esd/ewma/cusum 全 None（不硬算）。"""
    base = _seeded_base()
    target = sum(base) / len(base)
    # 0 线命中 → stable
    assert anchor_drift_spc_report(base, sigma=1.0, target=target
                                   )["verdict"] == "stable"
    # 单线（ESD 种植单点）→ warning（不升级 drifted）
    one = list(base)
    one[9] += 6.0
    rep_one = anchor_drift_spc_report(one, sigma=5.0, target=target)
    assert rep_one["verdict"] == "warning"
    assert rep_one["fired_lines"] == ["esd"]
    # n 不足 → insufficient，三线载体 None + reasons 留痕
    rep_short = anchor_drift_spc_report([0.1, 0.12, 0.11], sigma=None)
    assert rep_short["verdict"] == "insufficient"
    assert rep_short["esd"] is None and rep_short["ewma"] is None
    assert rep_short["cusum"] is None
    assert any("不硬算" in r for r in rep_short["reasons"])
    assert len(rep_short["reasons"]) >= 3  # 各线可用性逐条留痕


def test_minimums_constants_doc() -> None:
    """有效域常量与模块 docstring 口径一致（NIST 实践口径冻结）。"""
    assert SERIES_MIN_N == 8 and EWMA_MIN_N == 8 and CUSUM_MIN_N == 8
    assert ESD_MIN_N == 10


# ─── ② 真库评估钉（knowledge/anchors.yaml + 落档形态） ─────────────────────


def _load_real_anchors() -> list[dict]:
    import yaml

    raw = yaml.safe_load(
        (REPO / "knowledge" / "anchors.yaml").read_text(encoding="utf-8"))
    return list(raw.get("anchors") or [])


def test_real_anchor_library_series_lengths_insufficient() -> None:
    """真库盘点（#122 如实）：每锚可用时序 0-1 点（快照库未积累+注册表
    单点），全锚 insufficient——锚注册表单点现状的量化落档。"""
    anchors = _load_real_anchors()
    assert len(anchors) >= 30  # 2026-10-03 实测 34
    n_with_residual = 0
    for rec in anchors:
        cand = qm8.candidate_series(
            rec, qm8.load_snapshot_series(
                REPO / "runs" / "anchor_drift" / "snapshots.json"
            ).get(str(rec["anchor_id"]), []))
        assert cand["n_total"] <= 1  # 单点现状（v1/v2 演进史无数值序列）
        assert cand["n_total"] < SERIES_MIN_N
        n_with_residual += cand["n_registry_last_verified"]
    assert 0 < n_with_residual < len(anchors)  # 部分锚连 residual 也未落


@pytest.mark.skipif(
    not (REPO / "runs" / "qm8_anchor_spc" / "assessment.json").is_file(),
    reason="评估档未落档（先跑 scripts/qm8_anchor_spc_assessment.py）")
def test_assessment_archive_schema() -> None:
    """落档形态钉：全锚 insufficient、启用条件清单在档、零数值判定。"""
    data = json.loads(
        (REPO / "runs" / "qm8_anchor_spc" / "assessment.json").read_text(
            encoding="utf-8"))
    assert data["schema"] == "rfauto-qm8-anchor-spc-assessment-v1"
    assert data["n_anchors"] == data["n_insufficient"]
    assert data["n_with_spc_verdict"] == 0
    assert data["per_anchor"], "per_anchor 盘点非空"
    for entry in data["per_anchor"]:
        assert entry["spc_verdict"] == "insufficient"
        assert entry["available_series"]["n_total"] < SERIES_MIN_N
        assert "enables_when" in entry
