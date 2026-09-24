"""数据工厂低保真修正复判单测（合成语料，零 HFSS 零真机）。

被测对象：scripts/factory_mfk_lowfi_fix.py 的纯逻辑面——
- DiscrepancyGP1D：KOH 简化式离散差异 GP（独立 numpy 实现 #118）——
  训练点精确插值语义、光滑函数回收、超参 log 边界、零残差头退化、
  重拟合确定性；
- fit_discrepancies：残差构造（HFSS−OE 逐头）+ 嵌套 DoE 前提守卫；
- correct_low_rows：修正面构造（s11 线性口径回 dB 地板/clip、s21/εeff
  直接加、run_id 前缀）；
- synthetic_nonaffine_rows：正弦离散差异语料真值结构（#118）；
- run_pin：非仿射差异全链回收 ≤1e-3（criteria §5）；
- run_fix 端到端（合成语料，回归钉 skipped 语义）；
- _canonical/_stat_close：确定性比对与回归钉容差语义。

诚实口径：FAIL 如实出账不凑绿（#122）；门值零改动（criteria §4）。
"""

from __future__ import annotations

import json
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

smt = pytest.importorskip("smt", reason="SMT 为可选依赖（extra: smt）")

import factory_mfk_lowfi_fix as fx


def _load_m2():
    return fx.load_scripts()[0]


@pytest.fixture(scope="module")
def m2():
    return _load_m2()


# ---------------------------------------------------------------- δGP


class TestDiscrepancyGP1D:
    W_TRAIN = np.array([0.5, 0.745, 0.9178, 1.113, 1.182, 2.0])

    def test_exact_interpolation_at_train_points(self):
        y = np.array([0.03, -0.04, 0.02, -0.05, -0.06, 0.01])
        gp = fx.DiscrepancyGP1D(self.W_TRAIN, y).fit()
        for x, yi in zip(self.W_TRAIN, y, strict=True):
            assert gp.predict(float(x)) == pytest.approx(float(yi),
                                                         abs=1e-8)

    def test_smooth_recovery_within_bounds(self):
        # 半波正弦差异（光滑、带宽与 6 锚匹配）：held 点回收 ≤1e-3
        def truth(w: float) -> float:
            return 0.04 * np.sin(np.pi * (w - 0.5) / 1.5)

        y = np.array([truth(float(w)) for w in self.W_TRAIN])
        gp = fx.DiscrepancyGP1D(self.W_TRAIN, y).fit()
        assert fx.L_BOUNDS[0] <= gp.l <= fx.L_BOUNDS[1], "超参 l 出 log 边界"
        for w in (0.9946, 1.5119, 0.6, 1.8):
            assert gp.predict(w) == pytest.approx(truth(w), abs=1e-3)

    def test_zero_residual_head_degenerates_to_zero(self):
        gp = fx.DiscrepancyGP1D(self.W_TRAIN, np.zeros(6)).fit()
        for w in (0.6, 0.9946, 1.5119):
            assert gp.predict(w) == 0.0

    def test_refit_deterministic(self):
        y = np.array([0.03, -0.04, 0.02, -0.05, -0.06, 0.01])
        g1 = fx.DiscrepancyGP1D(self.W_TRAIN, y).fit()
        g2 = fx.DiscrepancyGP1D(self.W_TRAIN, y).fit()
        assert g1.l == g2.l and g1.sf == g2.sf
        assert g1.predict(1.5119) == g2.predict(1.5119)


# ---------------------------------------------------------------- 残差/修正


class TestFitDiscrepancies:
    def test_residual_construction_matches_hand_computed(self, m2):
        freqs = m2.band_freqs(0.05)
        w_grid = np.array([0.5, 0.745, 0.9178, 1.113, 1.182, 2.0, 1.5119,
                           0.9946])
        low, train, held = fx.synthetic_nonaffine_rows(
            freqs, w_grid, [0.5, 0.745], [0.9946], m2)
        # 用非仿射语料的 train/held 充当"高保真"，残差可手算
        hi = train + held
        pack = fx.fit_discrepancies(low, hi, freqs, lambda _m: None)
        assert pack["d11"].shape == (len(hi), len(freqs))
        assert pack["de"].shape == (len(hi),)
        for i, t in enumerate(hi):
            r = fx._exact_low_row(low, float(t["w"]))
            d11 = (10.0 ** (np.asarray(t["s11_db"]) / 20.0)
                   - 10.0 ** (np.asarray(r["s11_db"]) / 20.0))
            assert pack["d11"][i] == pytest.approx(d11, abs=1e-12)
            assert pack["de"][i] == pytest.approx(
                float(t["eps_eff"]) - float(r["eps_eff"]), abs=1e-12)

    def test_nested_doe_violation_raises(self, m2):
        freqs = m2.band_freqs(0.05)
        low, train, _held = fx.synthetic_nonaffine_rows(
            freqs, np.array([0.5, 2.0]), [0.5, 2.0], [0.9946], m2)
        off = dict(train[0])
        off["w"] = 0.75  # 不在低保真网格上
        with pytest.raises(ValueError, match="嵌套 DoE"):
            fx.fit_discrepancies(low, [off], freqs, lambda _m: None)


class _StubGP:
    def __init__(self, v: float) -> None:
        self.v = v

    def predict(self, _w: float) -> float:
        return self.v


class TestCorrectLowRows:
    def test_correction_applied_exact_stub(self, m2):
        freqs = m2.band_freqs(0.05)
        low, _train, _held = fx.synthetic_nonaffine_rows(
            freqs, np.array([0.5, 1.0, 2.0]), [0.5], [0.9946], m2)
        n_f = len(freqs)
        pack = {"gp11": [_StubGP(0.01)] * n_f,
                "gp21": [_StubGP(0.1)] * n_f,
                "gpe": _StubGP(0.02)}
        corr = fx.correct_low_rows(low, pack, freqs)
        assert len(corr) == len(low)
        for r0, r1 in zip(low, corr, strict=True):
            assert r1["w"] == r0["w"]
            assert str(r1["run_id"]).startswith("lowfix::")
            g0 = 10.0 ** (np.asarray(r0["s11_db"]) / 20.0)
            expect = 20.0 * np.log10(np.clip(g0 + 0.01, 1e-6, 1.0))
            assert r1["s11_db"] == pytest.approx(expect, abs=1e-12)
            assert r1["s21_db"] == pytest.approx(
                np.asarray(r0["s21_db"]) + 0.1, abs=1e-12)
            assert r1["eps_eff"] == pytest.approx(r0["eps_eff"] + 0.02,
                                                  abs=1e-12)

    def test_floor_and_clip_respected(self, m2):
        # OE+δ 为负 → clip 到 0 后地板 1e-6（−120dB）；超 1 → clip 到 1（0dB）
        freqs = m2.band_freqs(0.05)
        low, _train, _held = fx.synthetic_nonaffine_rows(
            freqs, np.array([0.5, 2.0]), [0.5], [0.9946], m2)
        n_f = len(freqs)
        pack = {"gp11": [_StubGP(-1.0)] * n_f,
                "gp21": [_StubGP(0.0)] * n_f,
                "gpe": _StubGP(0.0)}
        corr = fx.correct_low_rows(low, pack, freqs)
        floor_db = 20.0 * np.log10(fx.S11_FLOOR_LIN)
        for r in corr:
            assert np.all(r["s11_db"] >= floor_db - 1e-9)
            assert np.all(r["s11_db"] <= 0.0 + 1e-9)


# ---------------------------------------------------------------- 合成语料


class TestSyntheticNonaffineRows:
    def test_sine_discrepancy_truth_structure(self, m2):
        freqs = m2.band_freqs(0.05)
        low, train, held = fx.synthetic_nonaffine_rows(
            freqs, np.array([0.5, 1.0, 1.5119, 2.0]), [1.0], [1.5119], m2)
        by_w = {round(r["w"], 9): r for r in low}
        for t in train + held:
            w = float(t["w"])
            lo = by_w[round(w, 9)]
            eps_l = 2.5 + 0.5 * w
            expect = 1.05 * eps_l + 0.05 + 0.08 * np.sin(
                np.pi * (w - 0.5) / 1.5)
            assert t["eps_eff"] == pytest.approx(expect, abs=1e-12)
            # 低保真行本身 = 解析无耗线族（s11/s21 由 line_s_complex 回算）
            s11, s21 = m2.line_s_complex(60.0 + 15.0 * w, eps_l, freqs)
            assert lo["s11_db"] == pytest.approx(
                20 * np.log10(np.abs(s11) + 1e-30), abs=1e-9)
            assert lo["s21_db"] == pytest.approx(
                20 * np.log10(np.abs(s21) + 1e-30), abs=1e-9)


# ---------------------------------------------------------------- 全链


class TestRunPin:
    def test_nonaffine_recovery_within_1e3(self, m2):
        _m2, rj = fx.load_scripts()
        pin = fx.run_pin(rj, m2, lambda _m: None)
        assert pin["pass"] is True
        assert pin["checks"] == {"gamma_lin": True, "eps_eff_rel": True,
                                 "s21_db": True}
        assert pin["arms"]["smt_mfk"]["gamma_lin"]["max"] <= 1e-3
        assert pin["arms"]["smt_mfk"]["eps_eff_rel"]["max"] <= 1e-3
        assert pin["arms"]["smt_mfk"]["s21_db"]["max"] <= 1e-3
        assert pin["value_add_pass_vs_raw_low"] is True


class TestRunFixEndToEnd:
    def test_synthetic_corpus_full_chain(self, m2, tmp_path):
        """合成语料端到端：修正链应过三门+双增值门（回归钉 skipped）。"""
        freqs = m2.band_freqs(0.05)
        w_train = [0.5, 0.745, 0.9178, 1.113, 1.182, 2.0]
        w_held = [0.9946, 1.5119]
        w_grid = np.unique(np.round(np.concatenate([
            np.linspace(0.5, 2.0, 40), np.array(w_train), np.array(w_held)]),
            12))
        low, train, held = fx.synthetic_nonaffine_rows(
            freqs, w_grid, w_train, w_held, m2)
        verdict = fx.run_fix(low, train + held, freqs,
                             prefix_verdict_path=None,
                             out_dir=tmp_path, log=lambda _m: None)
        assert verdict["schema"] == "factory_mfk_lowfi_fix_verdict/1"
        assert verdict["regression_pin"]["ok"] is None, \
            "归档缺失时回归钉如实 skipped（不冒充 PASS/FAIL）"
        assert verdict["deterministic"] is True
        assert verdict["synthetic_recovery"]["pass"] is True
        j = verdict["judgment"]
        assert set(j["arms"]) == {"mfk_lowfi_fix", "baseline_oe_direct",
                                  "mfk_prefix", "koh_lowfi_direct"}
        assert j["gates_pass"] == {"gamma_lin": True, "eps_eff_rel": True,
                                   "s21_db": True}
        assert j["value_add_pass_vs_oe"] is True
        assert j["second_control_vs_prefix"] is True
        assert verdict["overall"] == "PASS"
        assert (tmp_path / "mfk_verdict_lowfi_fix.json").exists()
        assert (tmp_path / "discrepancy_gp_hyper.json").exists()
        assert (tmp_path / "heldout_compare_fix.png").exists()
        reloaded = json.loads(
            (tmp_path / "mfk_verdict_lowfi_fix.json").read_text(
                encoding="utf-8"))
        assert reloaded["overall"] == "PASS"

    def test_pending_when_anchors_missing(self, m2, tmp_path):
        freqs = m2.band_freqs(0.05)
        low, train, _held = fx.synthetic_nonaffine_rows(
            freqs, np.array([0.5, 2.0]), [0.5, 2.0], [0.9946], m2)
        verdict = fx.run_fix(low, train, freqs, prefix_verdict_path=None,
                             out_dir=tmp_path, log=lambda _m: None)
        assert verdict["overall"] == "PENDING_HIGH_FI"


# ---------------------------------------------------------------- 工具


class TestCanonicalAndStatClose:
    def test_canonical_strips_time_varying_keys(self):
        a = {"generated_at": "2026-01-01T00:00:00+00:00", "wall_s": 1.0,
             "v": [1, 2, {"k": "x"}]}
        b = {"generated_at": "2026-09-22T12:00:00+00:00", "wall_s": 99.0,
             "v": [1, 2, {"k": "x"}]}
        assert fx._canonical(a) == fx._canonical(b)

    def test_stat_close_tolerance_semantics(self):
        good = {"gamma_lin": {"max": 0.1, "mean": 0.05},
                "eps_eff_rel": {"max": 0.01, "mean": 0.005},
                "s21_db": {"max": 0.1, "mean": 0.05}}
        assert fx._stat_close(good, good, 1e-9) == []
        drift = json.loads(json.dumps(good))
        drift["gamma_lin"]["max"] = 0.1 + 1e-6
        bad = fx._stat_close(good, drift, 1e-9)
        assert bad == ["gamma_lin.max: 0.1 vs 0.100001"]
