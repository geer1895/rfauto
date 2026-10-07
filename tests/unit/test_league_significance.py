"""S-1 单测——联赛组级显著性（Dunnett vs 参考 + BH/Holm 多重校正）。

判据（研究扩充 round3 §3.1 S-1）：
- 合成已知差注入 → 检出率/假阳率回收：参考 N(0,0.1) n=8，偏移引擎
  +5σ（=0.5）n=8，同分布引擎 n=8，重复 20 次（种子 20260926 固定）——
  偏移引擎 reject 率 ≥80%（功效界）、同分布引擎假阳 ≤20%（松界防
  flaky：同分布引擎理论假阳 ~5%，20 次二项 P(≥5)≈1.6%）；松界口径
  见 test docstring（功效/样本量）；
- Dunnett 独立来源对照（#118 裁判不自证）：单比较时 Dunnett ≡ 合并
  方差 t 检验（同池化方差/自由度下数学等价）；scipy dunnett 走 QMC
  数值积分，中等 p 区实测相对差 ≤1.5e-3（5 种子），断言 rtol=5e-3；
  远尾（p<1e-6）QMC 噪声相对放大，不作对照区；
- BH vs Holm：已知 p 向量手算值逐位（scipy BH=反向 cummin、
  Holm=正向 cummax）+ 点序 holm≥bh≥raw；
- 退化（参考缺样本/样本 1 个/全同值）→ p=None 如实不虚构；
  p=0.0 是合法值（#364④：判缺失 is None，禁 `or`）；
- rebuild_league 集成：tmp runs 面（所有 API 显式 runs_dir/db_path
  参数隔离，零 chdir、不污染真实 runs/，#144 意图同既有
  test_league_service.py 构造法）造 3 引擎×同组多 run → league_report
  组级行含 p_raw/p_adj/sig_reject 三新键且既有键零删（快照集合对比）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.service.league_service import (
    _holm,
    league_report,
    rebuild_league,
    significance_vs_reference,
)

_SEED = 20260926
_N_REPS = 20
_N_PER_GROUP = 8


def _write_meta(run_dir: Path, meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")


class TestPowerAndAnchors:
    def test_power_and_false_positive_recovery(self):
        """合成已知差回收：+5σ 偏移引擎检出 ≥80%，同分布引擎假阳 ≤20%。

        功效/样本量口径：组内 n=8、噪声 σ=0.1、偏移 5σ=0.5 → 单检验
        非中心 t≈10（功效≈1）；0.8/0.2 为松界（同分布引擎理论假阳
        ~5%/次，20 次二项 P(≥5)≈1.6%，防 flaky）；种子固定 → 可复现。
        """
        rng = np.random.default_rng(_SEED)
        n_shift = n_null = 0
        for _ in range(_N_REPS):
            samples = {
                "hfss": list(rng.normal(0.0, 0.1, _N_PER_GROUP)),
                "shifted": [v + 0.5
                            for v in rng.normal(0.0, 0.1, _N_PER_GROUP)],
                "null": list(rng.normal(0.0, 0.1, _N_PER_GROUP)),
            }
            res = significance_vs_reference(samples)
            assert res["shifted"]["note"] is None
            assert res["null"]["note"] is None
            n_shift += bool(res["shifted"]["reject"])
            n_null += bool(res["null"]["reject"])
        assert n_shift >= 16, f"+5σ 偏移引擎检出率 {n_shift}/20 < 80%"
        assert n_null <= 4, f"同分布引擎假阳 {n_null}/20 > 20%"

    def test_dunnett_matches_pooled_ttest_single_comparison(self):
        """独立来源锚（#118）：单比较 Dunnett ≡ 合并方差 t 检验。

        同池化方差/自由度下两法数学等价；scipy dunnett 为 QMC 数值
        积分，中等 p 区断言 rtol=5e-3（实测 5 种子 max 1.5e-3）。
        """
        rng = np.random.default_rng(7)
        ref = list(rng.normal(0.0, 1.0, 10))
        eng = list(rng.normal(0.8, 1.0, 10))
        res = significance_vs_reference({"hfss": ref, "eng": eng})
        p_dunnett = res["eng"]["p_raw"]
        assert p_dunnett is not None
        p_ttest = float(stats.ttest_ind(eng, ref, equal_var=True).pvalue)
        assert p_dunnett == pytest.approx(p_ttest, rel=5e-3)

    def test_reject_uses_bh_adjusted_not_raw(self):
        """reject 判据=p_adj（BH 校正后）而非 p_raw：alpha 取两值之间翻转。"""
        rng = np.random.default_rng(11)
        samples = {
            "hfss": list(rng.normal(0.0, 1.0, 10)),
            "mid": list(rng.normal(0.7, 1.0, 10)),
            "far": list(rng.normal(3.0, 1.0, 10)),
        }
        base = significance_vs_reference(samples)
        eng = next(e for e in ("mid", "far")
                   if base[e]["p_raw"] is not None
                   and base[e]["p_adj"] is not None
                   and base[e]["p_raw"] < base[e]["p_adj"] < 1.0)
        alpha = (base[eng]["p_raw"] + base[eng]["p_adj"]) / 2.0
        res = significance_vs_reference(samples, alpha=alpha)
        assert res[eng]["reject_raw"] is True
        assert res[eng]["reject"] is False

    def test_significance_padj_matches_scipy_bh(self):
        """p_adj 与直接调 scipy false_discovery_control 逐位一致。"""
        rng = np.random.default_rng(13)
        samples = {"hfss": list(rng.normal(0, 1, 8)),
                   "a": list(rng.normal(1.0, 1, 8)),
                   "b": list(rng.normal(0.2, 1, 8)),
                   "c": list(rng.normal(0.5, 1, 8))}
        res = significance_vs_reference(samples)
        order = ["a", "b", "c"]
        raw = [res[e]["p_raw"] for e in order]
        assert all(p is not None for p in raw)
        expected = [float(v) for v in
                    stats.false_discovery_control(raw, method="bh")]
        for e, want in zip(order, expected, strict=True):
            assert res[e]["p_adj"] == pytest.approx(want, rel=1e-12)


class TestHolmAndBHVectors:
    def test_holm_known_vector(self):
        """Holm step-down 手算逐位：sorted [0.01,0.03,0.04]×乘子[3,2,1]
        → 正向 cummax [0.03,0.06,0.06]（回填原序）。"""
        assert _holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
        assert _holm([0.03]) == [0.03]
        assert _holm([]) == []

    def test_bh_known_vector_and_pointwise_order(self):
        """scipy BH（反向 cummin）手算逐位 + 点序 holm≥bh≥raw。"""
        ps = [0.01, 0.04, 0.03]
        bh = [float(v) for v in
              stats.false_discovery_control(ps, method="bh")]
        assert bh == [0.03, 0.04, 0.04]
        holm = _holm(ps)
        for h, b, p in zip(holm, bh, ps, strict=True):
            assert h >= b >= p


class TestDegenerateCases:
    def test_reference_missing(self):
        res = significance_vs_reference({"a": [1.0, 2.0, 3.0]})
        assert res["a"]["p_raw"] is None
        assert res["a"]["p_adj"] is None
        assert res["a"]["reject"] is False
        assert res["a"]["note"] == "insufficient_samples"

    def test_reference_empty(self):
        res = significance_vs_reference({"hfss": [], "a": [1.0, 2.0]})
        assert res["a"]["p_raw"] is None
        assert res["a"]["note"] == "insufficient_samples"

    def test_engine_single_sample(self):
        res = significance_vs_reference({"hfss": [1.0, 2.0], "a": [3.0]})
        assert res["a"]["p_raw"] is None
        assert res["a"]["reject"] is False

    def test_all_identical_zero_variance(self):
        res = significance_vs_reference({"hfss": [1.0, 1.0, 1.0],
                                         "a": [1.0, 1.0, 1.0]})
        assert res["a"]["p_raw"] is None
        assert res["a"]["reject"] is False
        assert res["a"]["note"] == "zero_variance"

    def test_zero_pvalue_is_legal_not_missing(self):
        """#364④：p=0.0 是合法值不是缺失——组内零方差+均值差 → t=inf
        → p 恰为 0.0；判缺失若用 `or` 会把 0.0 顶成缺失。"""
        res = significance_vs_reference({"hfss": [1.0, 1.0, 1.0, 1.0],
                                         "a": [2.0, 2.0, 2.0, 2.0]})
        assert res["a"]["p_raw"] == 0.0
        assert res["a"]["p_raw"] is not None
        assert res["a"]["reject"] is True

    def test_reference_engine_entry(self):
        res = significance_vs_reference({"hfss": [1.0, 2.0], "a": [3.0, 4.0]})
        assert res["hfss"] == {"p_raw": None, "p_adj": None, "reject": False,
                               "reject_raw": False, "note": "is_reference"}

    def test_nonfinite_filtered(self):
        res = significance_vs_reference({
            "hfss": [0.0, 0.1, -0.1, 0.05],
            "a": [float("nan"), 1.0, 2.0, 3.0]})
        assert res["a"]["note"] is None
        assert res["a"]["p_raw"] is not None

    def test_deterministic_across_calls(self):
        """固定 rng=0 → 同输入两次调用结果逐位一致（md 双出前提）。"""
        samples = {"hfss": [0.1, -0.2, 0.05, 0.3],
                   "a": [0.5, 0.3, 0.6, 0.4]}
        assert significance_vs_reference(samples) == \
            significance_vs_reference(samples)


_LEGACY_POINT_KEYS = {"engine", "n_rows", "median_abs_delta",
                      "median_wall_s", "on_front"}


class TestLeagueReportIntegration:
    @pytest.fixture
    def sig_runs_tree(self, tmp_path) -> Path:
        """3 引擎×同组多 run：hfss/openems 同分布、fake +6dB 偏移；
        另一 run 只带 verdict 工件（gate_verdict 组无数值样本语义）。"""
        base = tmp_path / "runs"
        specs = {
            "hfss": [-20.0, -19.9, -20.1, -20.05],
            "openems": [-20.1, -19.8, -20.2, -19.95],
            "fake": [-14.0, -14.2, -13.9, -14.15],
        }
        i = 0
        for eng, values in specs.items():
            for v in values:
                _write_meta(base / "camp" / f"r{i}", {
                    "run_id": f"r{i}", "adapter": eng, "model": "mline",
                    "status": "done", "wall_s": 100.0 + i,
                    "metrics": {"s11_db_max_in_band": v}})
                i += 1
        d = base / "camp" / "r_gv"
        _write_meta(d, {"run_id": "r_gv", "adapter": "comsol",
                        "model": "mline", "status": "done", "metrics": {}})
        (d / "verdict.json").write_text(json.dumps({"verdict": "PASS"}),
                                        encoding="utf-8")
        return base

    def _build_report(self, sig_runs_tree, tmp_path):
        db = tmp_path / "league.duckdb"
        assert rebuild_league(sig_runs_tree, db)["ok"] is True
        return league_report(db)

    def test_report_rows_have_significance_columns(
            self, sig_runs_tree, tmp_path):
        rep = self._build_report(sig_runs_tree, tmp_path)
        assert rep["ok"] is True
        group = next(g for g in rep["groups"]
                     if g["quantity"] == "s11_db_max_in_band")
        by = {p["engine"]: p for p in group["engines"]}
        # 既有键零删（快照集合对比）+ 三新键齐备
        for eng, p in by.items():
            assert set(p) >= _LEGACY_POINT_KEYS, f"{eng} 既有键缺失"
            assert {"p_raw", "p_adj", "sig_reject"} <= set(p)
        # 参考引擎如实不判
        assert by["hfss"]["p_raw"] is None
        assert by["hfss"]["p_adj"] is None
        assert by["hfss"]["sig_reject"] is False
        # +6dB 偏移引擎：p_raw=0.0（合法值非缺失，#364④）→ reject
        assert by["fake"]["p_raw"] == 0.0
        assert by["fake"]["sig_reject"] is True
        # 同分布引擎：p_raw=1.0 → 不判显著
        assert by["openems"]["p_raw"] == pytest.approx(1.0)
        assert by["openems"]["sig_reject"] is False
        # n_rows 既有语义不变
        assert all(by[e]["n_rows"] == 4 for e in ("hfss", "openems", "fake"))

    def test_report_md_has_significance_columns(
            self, sig_runs_tree, tmp_path):
        rep = self._build_report(sig_runs_tree, tmp_path)
        rep2 = league_report(tmp_path / "league.duckdb")
        assert rep["md"] == rep2["md"]  # 固定 rng → md 双出逐字节一致
        md = rep["md"]
        assert ("| engine | n_rows | median_abs_delta | median_wall_s | "
                "p_raw | p_adj | sig_reject | on_front |") in md
        hfss_row = next(ln for ln in md.splitlines()
                        if ln.startswith("| hfss |"))
        assert " - |" in hfss_row  # 参考引擎 p 列如实 "-"

    def test_report_gate_verdict_group_honest_null(
            self, sig_runs_tree, tmp_path):
        rep = self._build_report(sig_runs_tree, tmp_path)
        gv = next(g for g in rep["groups"]
                  if g["quantity"] == "gate_verdict")
        point = next(pt for pt in gv["engines"] if pt["engine"] == "comsol")
        assert point["p_raw"] is None
        assert point["p_adj"] is None
        assert point["sig_reject"] is False
