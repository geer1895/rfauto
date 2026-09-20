"""G14 close-out：稳健时长预测回退语义 + 覆盖面统计 单元测试。

钉死 :class:`RobustDurationPredictor` 的三条门语义（g14-close）：

1. 样本不足（n < 4）-> status=unknown、predicted_s=None、保守上界 =
   unknown_bound_multiple × max(观测实耗)，绝不给点估计；
2. 模型不可信（LOO max 相对误差 > 1.0）-> 同样回退 unknown + 保守上界；
3. 可信且查询在标定域内 -> calibrated，上界 = 预测 × (1 + LOO max)；
   查询越界 -> extrapolated（给数但明确低置信）。

覆盖面统计（coverage_ratio）：留一折内重拟合、用与部署一致的
上界规则在历史实耗上评测；零仿真（合成样本），不读真实 runs/。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.pipeline.duration_calibration import (
    FAMILY_MLINE,
    FAMILY_RATRACE,
    calibration_report,
    load_openems_duration_samples,
)
from rfauto.pipeline.quota_guard import (
    MIN_CALIBRATION_SAMPLES,
    UNKNOWN_BOUND_MULTIPLE,
    DurationSample,
    RobustDurationPredictor,
)

# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #

def _exact_offset_power_samples(n: int = 5) -> list[DurationSample]:
    """精确 offset+power 律 t = 20 + 5·mesh^-3.5 的合成标定样本（零噪声）。"""

    def solve_s(mesh: float) -> float:
        return 20.0 + 5.0 * mesh ** (-3.5)

    meshes = [0.6, 0.5, 0.4, 0.3, 0.25][:n]
    return [
        DurationSample(
            mesh_mm=m,
            solve_s=solve_s(m),
            domain_volume_mm3=1000.0,
            n_excitations=1,
            source=f"synthetic/m{m:g}",
        )
        for m in meshes
    ]


# --------------------------------------------------------------------------- #
# 门 1：样本不足 -> unknown + 保守上界
# --------------------------------------------------------------------------- #

def test_too_few_samples_falls_back_to_unknown() -> None:
    samples = _exact_offset_power_samples(MIN_CALIBRATION_SAMPLES - 1)
    predictor = RobustDurationPredictor.fit(samples)
    prediction = predictor.predict(mesh_mm=0.4)
    assert prediction.status == "unknown"
    assert prediction.predicted_s is None, "unknown 状态绝不给点估计"
    expected_bound = UNKNOWN_BOUND_MULTIPLE * max(s.solve_s for s in samples)
    assert prediction.upper_bound_s == pytest.approx(expected_bound)
    assert "insufficient samples" in prediction.reason
    assert prediction.loo_max_rel_error is None


def test_no_samples_unknown_bound_is_none() -> None:
    predictor = RobustDurationPredictor.fit([])
    prediction = predictor.predict(mesh_mm=0.4)
    assert prediction.status == "unknown"
    assert prediction.predicted_s is None
    assert prediction.upper_bound_s is None
    assert predictor.coverage_ratio() is None


# --------------------------------------------------------------------------- #
# 门 2：模型不可信（LOO max > 1）-> unknown + 保守上界
# --------------------------------------------------------------------------- #

def test_untrusted_loo_falls_back_to_unknown() -> None:
    """聚类 + 近零离群点：留一折对离群点必然错到远超 100% -> 不可信。"""
    samples = [
        DurationSample(mesh_mm=0.4, solve_s=1000.0, n_excitations=1, source="c1"),
        DurationSample(mesh_mm=0.4, solve_s=1000.0, n_excitations=1, source="c2"),
        DurationSample(mesh_mm=0.4, solve_s=1000.0, n_excitations=1, source="c3"),
        DurationSample(mesh_mm=0.2, solve_s=1.0, n_excitations=1, source="outlier"),
    ]
    predictor = RobustDurationPredictor.fit(samples)
    assert predictor.loo_max is not None and predictor.loo_max > 1.0
    prediction = predictor.predict(mesh_mm=0.4)
    assert prediction.status == "unknown"
    assert prediction.predicted_s is None
    expected_bound = UNKNOWN_BOUND_MULTIPLE * 1000.0
    assert prediction.upper_bound_s == pytest.approx(expected_bound)
    assert "untrusted" in prediction.reason
    assert prediction.loo_max_rel_error == pytest.approx(predictor.loo_max)


# --------------------------------------------------------------------------- #
# 门 3：可信 -> calibrated / extrapolated
# --------------------------------------------------------------------------- #

def test_calibrated_prediction_bound_covers_worst_loo() -> None:
    predictor = RobustDurationPredictor.fit(_exact_offset_power_samples())
    assert predictor.status == "calibrated"
    assert predictor.loo_max is not None and predictor.loo_max <= 1.0
    query = DurationSample(mesh_mm=0.45, domain_volume_mm3=1000.0, n_excitations=1)
    prediction = predictor.predict(query)
    assert prediction.status == "calibrated"
    assert prediction.predicted_s is not None and prediction.predicted_s > 0.0
    expected = 20.0 + 5.0 * 0.45 ** (-3.5)
    assert prediction.predicted_s == pytest.approx(expected, rel=0.05)
    assert prediction.upper_bound_s == pytest.approx(
        prediction.predicted_s * (1.0 + predictor.loo_max)
    )
    assert prediction.upper_bound_s >= prediction.predicted_s


def test_extrapolated_query_outside_calibration_range() -> None:
    predictor = RobustDurationPredictor.fit(_exact_offset_power_samples())
    prediction = predictor.predict(mesh_mm=2.0)  # 高于标定域 [0.25, 0.6]
    assert prediction.status == "extrapolated"
    assert prediction.predicted_s is not None
    assert prediction.upper_bound_s is not None
    assert "mesh_mm" in prediction.reason
    below = predictor.predict(mesh_mm=0.05)
    assert below.status == "extrapolated"


def test_predict_accepts_kwargs_and_rejects_wrong_type() -> None:
    predictor = RobustDurationPredictor.fit(_exact_offset_power_samples())
    via_kwargs = predictor.predict(mesh_mm=0.4, domain_volume_mm3=1000.0)
    via_sample = predictor.predict(
        DurationSample(mesh_mm=0.4, domain_volume_mm3=1000.0, n_excitations=1)
    )
    assert via_kwargs.predicted_s == via_sample.predicted_s
    assert via_kwargs.status == via_sample.status
    with pytest.raises(TypeError):
        predictor.predict("not-a-sample")


# --------------------------------------------------------------------------- #
# 覆盖面统计
# --------------------------------------------------------------------------- #

def test_coverage_ratio_perfect_on_exact_model() -> None:
    predictor = RobustDurationPredictor.fit(_exact_offset_power_samples())
    assert predictor.coverage_ratio() == pytest.approx(1.0)


def test_coverage_ratio_detects_uncovered_outlier() -> None:
    """含离群点的标定档：上界规则盖不住离群点 -> coverage < 1。"""
    samples = _exact_offset_power_samples()
    samples.append(
        DurationSample(
            mesh_mm=0.22,
            solve_s=float(samples[-1].solve_s) * 50.0,  # 同域特征下 50 倍实耗
            domain_volume_mm3=1000.0,
            n_excitations=1,
            source="synthetic/outlier",
        )
    )
    predictor = RobustDurationPredictor.fit(samples)
    coverage = predictor.coverage_ratio()
    assert coverage is not None
    assert 0.0 < coverage < 1.0


def test_summary_and_to_dict_json_able_and_deterministic() -> None:
    predictor = RobustDurationPredictor.fit(_exact_offset_power_samples())
    prediction = predictor.predict(mesh_mm=0.4)
    payload = prediction.to_dict()
    json.dumps(payload)  # 可序列化
    summary = predictor.summary()
    json.dumps(summary)
    again = RobustDurationPredictor.fit(_exact_offset_power_samples()).summary()
    assert json.dumps(again, sort_keys=True) == json.dumps(summary, sort_keys=True)


# --------------------------------------------------------------------------- #
# runs/ 标定档装载（合成 runs 树，零真实 runs/ 依赖）
# --------------------------------------------------------------------------- #

def _simulation_py(mesh_mm: float) -> str:
    return (
        f"BASE = {mesh_mm / 1e3:.6f}\n"
        "BOARD = 0.060\n"
        "H_SUB = 0.0008\n"
        "AIR_SIDE = 0.020\n"
        "AIR_TOP = 0.015\n"
    )


@pytest.fixture()
def synthetic_runs(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    bench = runs / "benchmark"
    for mesh in (0.6, 0.4):
        d = bench / f"mline_m{mesh:g}"
        d.mkdir(parents=True)
        (d / "simulation.py").write_text(_simulation_py(mesh), encoding="utf-8")
    (bench / "mline_mesh_convergence.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"mesh_mm": 0.6, "ok": True, "wall_s": 239},
                    {"mesh_mm": 0.4, "ok": True, "wall_s": 497},
                ]
            }
        ),
        encoding="utf-8",
    )
    arb = runs / "ratrace_arbitration" / "mesh_0p2mm" / "p1"
    arb.mkdir(parents=True)
    (arb / "simulation.py").write_text(_simulation_py(0.2), encoding="utf-8")
    (runs / "ratrace_arbitration" / "openems_convergence.json").write_text(
        json.dumps({"solve_s_0p2mm": 7681.6}), encoding="utf-8"
    )
    smoke = runs / "ratrace_smoke" / "pt8"
    smoke.mkdir(parents=True)
    (smoke / "smoke_pt8.log").write_text("solve_s=3227 ok=True errs=[]\n", encoding="utf-8")
    smoke9 = runs / "ratrace_smoke" / "pt9"
    smoke9.mkdir(parents=True)
    (smoke9 / "smoke_pt9.log").write_text("solve_s=2989 ok=True errs=[]\n", encoding="utf-8")
    return runs


def test_loader_splits_families_and_records_provenance(synthetic_runs: Path) -> None:
    loaded = load_openems_duration_samples(synthetic_runs)
    families = loaded["families"]
    assert [s.solve_s for s in families[FAMILY_MLINE]] == [239.0, 497.0]
    assert len(families[FAMILY_RATRACE]) == 3  # 精算 1 点 + 冒烟 2 点
    assert "benchmark/mline_mesh_convergence.json" in loaded["provenance"]
    assert loaded["skipped"] == []
    for samples in families.values():
        for sample in samples:
            assert sample.domain_volume_mm3 > 0.0


def test_loader_missing_sources_are_skipped_best_effort(tmp_path: Path) -> None:
    loaded = load_openems_duration_samples(tmp_path / "empty_runs")
    assert all(not samples for samples in loaded["families"].values())
    assert len(loaded["skipped"]) >= 2


def test_calibration_report_family_semantics(synthetic_runs: Path) -> None:
    """2 样本档 -> unknown（不足）；报告同时给混池对照。"""
    report = calibration_report(synthetic_runs)
    mline = report["families"][FAMILY_MLINE]
    ratrace = report["families"][FAMILY_RATRACE]
    assert mline["status"] == "unknown"
    assert mline["n_samples_below_min"] is True
    assert mline["conservative_unknown_bound_s"] == pytest.approx(
        UNKNOWN_BOUND_MULTIPLE * 497.0
    )
    assert ratrace["status"] == "unknown"
    pooled = report["pooled"]
    assert pooled["n_samples"] == 5
    assert set(report) >= {"families", "pooled", "provenance", "skipped"}


def test_calibration_report_on_exact_synthetic_family_is_calibrated(
    tmp_path: Path,
) -> None:
    """4 点精确 offset+power 档 -> calibrated 且 coverage=1（端到端语义）。"""
    runs = tmp_path / "runs"
    bench = runs / "benchmark"
    entries = []
    for mesh in (0.6, 0.5, 0.4, 0.3):
        d = bench / f"mline_m{mesh:g}"
        d.mkdir(parents=True)
        (d / "simulation.py").write_text(_simulation_py(mesh), encoding="utf-8")
        entries.append(
            {"mesh_mm": mesh, "ok": True, "wall_s": 20.0 + 5.0 * mesh ** (-3.5)}
        )
    (bench / "mline_mesh_convergence.json").write_text(
        json.dumps({"entries": entries}), encoding="utf-8"
    )
    report = calibration_report(runs)
    mline = report["families"][FAMILY_MLINE]
    assert mline["status"] == "calibrated"
    assert mline["coverage_ratio"] == pytest.approx(1.0)
    assert mline["loo_max_rel_error"] is not None
    assert mline["loo_max_rel_error"] <= 0.01
