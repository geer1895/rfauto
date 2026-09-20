"""W4⑪b WP3.4：神经算子 × kriging A/B 脚本（scripts/wp34_neural_operator_ab.py）单测。

零真机、零网络：在 tmp_path 造一份与 wp34 注册表同列的合成 parquet + 合成 Touchstone
.s1p（解析谐振族），跑通装载→折划分→五模型 CV→门→JSON 全链路（quick 小 epochs）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("torch", reason="torch 为可选依赖（extra: torch）")
pytest.importorskip("smt", reason="smt 为可选依赖（extra: smt）")
pd = pytest.importorskip("pandas", reason="dataset extra（pandas）")
pytest.importorskip("pyarrow", reason="dataset extra（pyarrow）")
pytest.importorskip("skrf", reason="Touchstone 解析走 skrf")

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "wp34_neural_operator_ab.py"

F_GHZ = np.linspace(2.3, 2.5, 11)  # 与真实 GT .s1p 同网格（11 点，步长 20MHz）


@pytest.fixture(scope="module")
def ab():
    spec = importlib.util.spec_from_file_location("wp34_neural_operator_ab", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_curve_db(params: dict[str, float]) -> np.ndarray:
    """谷位随 patch_len 线性移动、谷深随 feed_offset 变的 Lorentzian（dB）。"""
    f0 = 2.3 + 0.2 * (45.0 - params["patch_len_mm"]) / 10.0
    depth = 4.0 + 20.0 * (params["feed_offset_mm"] - 3.0) / 17.0
    return -depth / (1.0 + ((F_GHZ - f0) / 0.05) ** 2)


def _write_s1p(path: Path, s11_db: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mag = 10.0 ** (s11_db / 20.0)
    lines = ["! synthetic touchstone for unit test", "# GHz S MA R 50.000000"]
    for f, m, k in zip(F_GHZ, mag, range(len(F_GHZ)), strict=True):
        lines.append(f"{f:.6f}  {m:.9f}  {-120.0 - 4.0 * k:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(run_id: str, model: str, adapter: str, algorithm: str,
         params: dict, metrics: dict, prov_run_id: str | None) -> dict:
    return {
        "run_id": run_id, "model": model, "adapter": adapter, "algorithm": algorithm,
        "study_name": "", "seed": 0, "params_json": json.dumps(params),
        "metrics_json": json.dumps(metrics), "cost": 0.0, "point_index": 0,
        "source": "unit", "provenance_json": json.dumps(
            {"run_id": prov_run_id} if prov_run_id else {}),
    }


@pytest.fixture
def synthetic_registry(tmp_path: Path):
    """12 条可用 hfss run_once 曲线行 + 3 条干扰行（tune 无目标 / openems 双参 / 他族）。"""
    rng = np.random.default_rng(0)
    runs_root = tmp_path / "runs"
    rows = []
    for i in range(12):
        params = {"patch_len_mm": float(rng.uniform(35, 45)),
                  "feed_offset_mm": float(rng.uniform(3, 20)),
                  "patch_w_mm": float(rng.uniform(40, 60))}
        db = _synthetic_curve_db(params)
        rid = f"synt_{i:02d}"
        _write_s1p(runs_root / rid / "results" / "params.s1p", db)
        rows.append(_row(rid, "patch_antenna", "hfss", "run_once", params,
                         {"s11_db_min_in_band": float(db.min()),
                          "s11_db_max_in_band": float(db.max())}, rid))
    rows.append(_row("tune_a", "patch_antenna", "hfss", "tune",
                     {"patch_len_mm": 40.0, "feed_offset_mm": 10.0, "patch_w_mm": 50.0},
                     {"s11_db_max_in_band": -1.0}, None))
    rows.append(_row("cal_a", "patch_antenna", "calibration:openems", "calibration",
                     {"patch_len_mm": 40.0, "patch_w_mm": 50.0},
                     {"s11_db_max_in_band": -1.0}, None))
    rows.append(_row("wk_a", "wilkinson_power_divider", "fake", "tune",
                     {"x": 1.0}, {"s21_db": -3.0}, None))
    dataset = tmp_path / "points.parquet"
    pd.DataFrame(rows).to_parquet(dataset, index=False)
    return dataset, runs_root


class TestLoading:
    def test_parse_touchstone_roundtrip(self, ab, tmp_path):
        db = np.linspace(-1.0, -25.0, len(F_GHZ))
        p = tmp_path / "x" / "results" / "params.s1p"
        _write_s1p(p, db)
        f, got = ab.parse_touchstone_s1p(p)
        np.testing.assert_allclose(f, F_GHZ, atol=1e-9)
        np.testing.assert_allclose(got, db, atol=1e-6)

    def test_load_gt_rows_filters_and_counts(self, ab, synthetic_registry):
        dataset, runs_root = synthetic_registry
        rows, summary = ab.load_gt_rows(dataset, runs_root)
        assert len(rows) == 12 and summary["n_used"] == 12
        assert summary["n_patch_total"] == 14  # 他族 wilkinson 行不计入 patch
        assert summary["n_rows_total"] == 15
        assert summary["dropped"]["not_hfss_run_once"] == 2
        assert summary["target"] == "s11_db_min_in_band"
        assert summary["target_stats"]["std"] > 0
        assert summary["n_param_values_outside_bounds"] == 0
        r0 = rows[0]
        assert set(r0["params"]) == set(ab.BOUNDS)
        assert len(r0["curve_f_ghz"]) == 11 and np.isfinite(r0["target"])
        assert ab.common_freq_grid(rows) == (2.3, 2.5)

    def test_missing_curve_file_is_counted_not_fatal(self, ab, synthetic_registry):
        dataset, runs_root = synthetic_registry
        (runs_root / "synt_03" / "results" / "params.s1p").unlink()
        rows, summary = ab.load_gt_rows(dataset, runs_root)
        assert len(rows) == 11 and summary["dropped"]["missing_curve"] == 1


class TestFoldsAndGate:
    @staticmethod
    def _partition(fid: np.ndarray, k: int) -> frozenset:
        return frozenset(frozenset(np.where(fid == f)[0].tolist()) for f in range(k))

    def test_fold_ids_balanced_and_repeats_change_partition(self, ab):
        fid0 = ab.fold_ids(36, 6, 0)
        assert np.array_equal(fid0, np.arange(36) % 6)  # repeat 0 = 索引取模惯例
        parts = []
        for rep in range(3):
            fid = ab.fold_ids(36, 6, rep)
            assert sorted(np.bincount(fid).tolist()) == [6] * 6  # 均衡
            assert np.array_equal(fid, ab.fold_ids(36, 6, rep))  # 同 repeat 确定性
            parts.append(self._partition(fid, 6))
        # 回归：不同 repeat 必须是不同的折集合（首版 (i+offset)%k 只轮换折号，
        # 划分相同 → 重复间 std 恰为 0）
        assert len(set(parts)) == 3
        rotated = (np.arange(36) + 1) % 6
        assert self._partition(rotated, 6) == parts[0]  # 说明"轮换≠重划分"

    @pytest.mark.parametrize("rho_fno, rho_don, expected", [
        (0.90, 0.86, True),      # 都 ≥ 0.886-0.05=0.836
        (0.90, 0.80, False),     # deeponet 不过
        (0.70, 0.90, False),     # fno 不过
        (None, 0.90, False),     # ρ 无定义 → FAIL（不编造）
    ])
    def test_evaluate_gate(self, ab, rho_fno, rho_don, expected):
        scalar = {"poly_ridge": {"spearman_rho_mean": 0.886},
                  "fno": {"spearman_rho_mean": rho_fno},
                  "deeponet": {"spearman_rho_mean": rho_don}}
        gate = ab.evaluate_gate(scalar)
        assert gate["pass"] is expected
        assert set(gate["checks"]) == {"fno", "deeponet"}
        assert gate["checks"]["fno"]["threshold"] == pytest.approx(0.836)

    def test_gate_fails_when_reference_missing(self, ab):
        gate = ab.evaluate_gate({"fno": {"spearman_rho_mean": 0.9},
                                 "deeponet": {"spearman_rho_mean": 0.9}})
        assert gate["pass"] is False


class TestEndToEnd:
    def test_run_ab_quick_writes_report(self, ab, synthetic_registry, tmp_path):
        dataset, runs_root = synthetic_registry
        out = tmp_path / "out" / "ab.json"
        payload = ab.run_ab(dataset_path=dataset, runs_root=runs_root, out_path=out,
                            folds=3, repeats=2, quick=True)
        assert out.is_file()
        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["gate"]["pass"] == payload["gate"]["pass"]
        assert isinstance(payload["gate"]["pass"], bool)
        assert payload["data"]["n_used"] == 12 and len(payload["run_ids"]) == 12
        assert set(payload["scalar_cv"]) == set(ab.ALL_KINDS)
        for kd, s in payload["scalar_cv"].items():
            assert len(s["per_repeat"]) == 2, kd
            assert s["spearman_rho_mean"] is None or -1.0 <= s["spearman_rho_mean"] <= 1.0
            assert s["rms_error_mean"] is not None and s["rms_error_mean"] >= 0
        assert set(payload["curve_cv"]) == set(ab.CURVE_KINDS)
        for kd, c in payload["curve_cv"].items():
            assert c["n_predictions"] == 24, kd  # 12 曲线 × 2 次重复
            assert c["native_step_mhz"] == pytest.approx(20.0)
            assert 0.0 <= c["valley_within_one_step_frac"] <= 1.0
            assert c["rms_db_mean"] >= 0
        assert payload["settings"]["quick"] is True
        assert payload["settings"]["freq_grid_ghz"] == [2.3, 2.5]
        assert "预声明门" in payload["conclusion"]
        assert "样本量评估" in payload["conclusion"]
        assert payload["runtime_s"]["total"] > 0

    def test_run_ab_rejects_too_few_rows(self, ab, synthetic_registry, tmp_path):
        dataset, runs_root = synthetic_registry
        df = pd.read_parquet(dataset)
        small = tmp_path / "small.parquet"
        df.head(4).to_parquet(small, index=False)
        with pytest.raises(ValueError, match="A/B 无意义"):
            ab.run_ab(dataset_path=small, runs_root=runs_root,
                      out_path=tmp_path / "o.json", folds=3, repeats=1, quick=True)
