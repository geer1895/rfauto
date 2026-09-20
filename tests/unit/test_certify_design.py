"""§10.20 补强⑭ certify_design 证据包（G11+D12+D10）单元测试。

确定性、无网络、无真机；全部数值来自既有确定性内核（solve_health / fsv /
KOHCalibrator / certify_design）。验证八因素表结构、三源一致性、缺源
UNKNOWN 语义、JSON 往返与非法输入报错。
"""

from __future__ import annotations

import json

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """隔离 cwd，避免任何相对 runs/ 读写污染真实归档（#144）。"""
    monkeypatch.chdir(tmp_path)
    yield


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #

def _linear_samples(tmp_path, name="linear_samples.json"):
    """线性指标样本集：s11 = -15 + 2*(arm_len-20)（可判 PASS/FAIL 边界）。"""
    bounds = {"arm_len_mm": [18.0, 23.0], "series_w_mm": [0.25, 0.45]}
    samples = []
    for i in range(10):
        a = 18.0 + i * 5.0 / 9
        s = 0.25 + (i % 3) * 0.08
        samples.append({
            "params": {"arm_len_mm": round(a, 6), "series_w_mm": round(s, 6)},
            "metrics": {"s11_db_max_in_band": round(-15 + 2 * (a - 20), 6)}})
    data = {
        "bounds": bounds,
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "samples": samples,
    }
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def _write_run(tmp_path, run_id="run_ev"):
    """最小真实 run 归档：openEMS schema sparams.csv + meta.json。"""
    run = tmp_path / "runs" / run_id
    run.mkdir(parents=True)
    lines = ["freq_hz,re_s11,im_s11,re_s21,im_s21"]
    for i in range(10):
        lines.append(f"{2.0e9 + i * 1e7},0.1,0.0,0.5,0.0")
    (run / "sparams.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({
        "run_id": run_id, "model": "patch_antenna", "adapter": "calibration:openems",
        "status": "done", "schema_version": "1.0", "git_sha": "abc1234"}),
        encoding="utf-8")
    return run


def _fsv_curve(n=201):
    """带谐振谷的 S11 dB 曲线（与 tests/unit/test_calibration.py 同源构造）。"""
    f = np.linspace(2.0, 3.0, n)
    y = -0.5 - 25.0 / (1.0 + ((f - 2.5) / 0.05) ** 2)
    return f, y


def _ripple(n=201, k=61):
    return np.sin(2.0 * np.pi * k * np.arange(n) / n)


def _factor(pkg, name):
    return next(f for f in pkg["factors"] if f["factor"] == name)


def _full_inputs(tmp_path):
    """齐全输入：样本集 + 真实 run 归档 + healthy G11 + 同曲线 FSV + 有效 KOH。"""
    from rfauto.service.health_service import health_check_run
    from rfauto.service.koh_service import KOHCalibrator

    path, _ = _linear_samples(tmp_path)
    run = _write_run(tmp_path, "run_full")
    health = health_check_run("run_full", runs_dir=tmp_path / "runs")
    f, y = _fsv_curve()
    cal = KOHCalibrator(bounds={"arm_len_mm": [18.0, 23.0]})
    cal.fit([{"params": {"arm_len_mm": 18.0}, "eta": -17.0, "y": -16.5},
             {"params": {"arm_len_mm": 23.0}, "eta": -9.0, "y": -8.5}])
    koh = dict(cal.predict({"arm_len_mm": 19.0}, eta=-17.0))
    koh["provenance"] = {"source": "unit-test KOHCalibrator"}
    return {
        "samples_path": path,
        "params_center": {"arm_len_mm": 19.0, "series_w_mm": 0.35},
        "run_id": "run_full",
        "run_dir": run,
        "health": health,
        "fsv_pairs": [{"label": "identity", "metric": "s11_db",
                       "freq_a": f, "val_a": y, "freq_b": f, "val_b": y,
                       "provenance": {"source": "unit-test curves"}}],
        "koh_interval": koh,
    }


# --------------------------------------------------------------------------- #
# 结构 / provenance
# --------------------------------------------------------------------------- #

class TestEvidenceStructure:
    def test_factor_table_has_eight_factors_in_order(self, tmp_path):
        from rfauto.service.certify_design import NASA_FACTORS, certify_design_evidence

        path, _ = _linear_samples(tmp_path)
        run = _write_run(tmp_path, "run_struct")
        pkg = certify_design_evidence(
            design="d", samples_path=path,
            params_center={"arm_len_mm": 19.0, "series_w_mm": 0.35},
            run_id="run_struct", run_dir=run)
        assert pkg["ok"] is True
        assert [f["factor"] for f in pkg["factors"]] == list(NASA_FACTORS)
        assert len(pkg["factors"]) == 8

    def test_every_factor_has_provenance_and_detail(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        path, _ = _linear_samples(tmp_path)
        run = _write_run(tmp_path, "run_prov")
        pkg = certify_design_evidence(
            design="d", samples_path=path,
            params_center={"arm_len_mm": 19.0, "series_w_mm": 0.35},
            run_id="run_prov", run_dir=run,
            extra_inputs=[{"label": "campaign", "path": tmp_path / "nope.json"}])
        for f in pkg["factors"]:
            assert set(f) >= {"factor", "label", "status", "detail", "provenance"}
            assert isinstance(f["provenance"], dict) and f["provenance"], f
            assert isinstance(f["provenance"].get("source"), str), f
            assert isinstance(f["detail"], str) and f["detail"], f
            assert f["status"] in {"PASS", "WARN", "FAIL", "UNKNOWN"}


# --------------------------------------------------------------------------- #
# 三源一致性（G11 / D12 / D10 直接调用 vs 包内）
# --------------------------------------------------------------------------- #

class TestSourceConsistency:
    def test_health_factor_matches_direct_g11(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence
        from rfauto.service.health_service import health_check_run

        run = _write_run(tmp_path, "run_g11")
        health = health_check_run("run_g11", runs_dir=tmp_path / "runs")
        assert health["verdict"] == "healthy"  # 非恒真：健康归档才应判 healthy
        path, _ = _linear_samples(tmp_path)
        pkg = certify_design_evidence(
            design="d", samples_path=path,
            params_center={"arm_len_mm": 19.0, "series_w_mm": 0.35},
            health=health, run_id="run_g11", run_dir=run)
        f = _factor(pkg, "v_and_v")
        assert f["status"] == "PASS"
        assert f["evidence"]["health_verdict"] == health["verdict"]
        got = {x["factor"]: x["status"] for x in f["evidence"]["g11_factors"]}
        exp = {x["factor"]: x["status"] for x in health["factors"]}
        assert got == exp and len(got) == 9

    def test_fsv_factor_matches_direct_d12(self):
        from rfauto.service.calibration_service import fsv_curve_levels
        from rfauto.service.certify_design import certify_design_evidence

        f, y = _fsv_curve()
        yb = y + 0.9 * _ripple()
        expected = fsv_curve_levels(f, y, f, yb)
        pkg = certify_design_evidence(
            design="d",
            fsv_pairs=[{"label": "a_vs_b", "metric": "s11_db",
                        "freq_a": f, "val_a": y, "freq_b": f, "val_b": yb,
                        "provenance": {"source": "synthetic"}}])
        e = _factor(pkg, "vv_history")["evidence"]["fsv"][0]
        assert e["ok"] is True
        assert e["adm_grade"] == expected["adm_grade"]
        assert e["fdm_grade"] == expected["fdm_grade"]
        assert e["gdm_grade"] == expected["gdm_grade"]
        assert e["gdm_mean"] == pytest.approx(expected["gdm_mean"])

    def test_koh_interval_matches_direct_d10(self):
        from rfauto.service.certify_design import certify_design_evidence
        from rfauto.service.koh_service import KOHCalibrator

        cal = KOHCalibrator(bounds={"x": [0.0, 1.0]})
        assert cal.fit([{"params": {"x": 0.0}, "eta": 1.0, "y": 1.1},
                        {"params": {"x": 1.0}, "eta": 2.0, "y": 2.2}])["ok"]
        pred = cal.predict({"x": 0.5}, eta=1.5)
        pkg = certify_design_evidence(
            design="d",
            koh_interval={**pred, "provenance": {"source": "unit-test KOH"}})
        f = _factor(pkg, "uncertainty_characterization")
        assert f["status"] == "PASS"
        row = f["evidence"]["koh_interval"]
        assert row["mean"] == pred["mean"]
        assert row["lo95"] == pred["lo95"] and row["hi95"] == pred["hi95"]
        assert row["provenance"]["source"] == "unit-test KOH"

    def test_design_certificate_matches_direct_call(self, tmp_path):
        from rfauto.service.certify_design import certify_design, certify_design_evidence

        path, _ = _linear_samples(tmp_path)
        pc = {"arm_len_mm": 19.0, "series_w_mm": 0.35}
        direct = certify_design(path, pc, tolerance_pct=0.02, n_grid=9)
        pkg = certify_design_evidence(design="d", samples_path=path, params_center=pc)
        assert pkg["design_certificate"] == direct
        assert pkg["design_certificate"]["samples_path"] == direct["samples_path"]
        f = _factor(pkg, "results_robustness")
        assert f["status"] == "PASS"
        assert f["evidence"]["n_pass"] == direct["n_pass"]
        assert f["evidence"]["n_unknown"] == direct["n_unknown"]


# --------------------------------------------------------------------------- #
# 对错样例（非恒真）
# --------------------------------------------------------------------------- #

class TestVerdicts:
    def test_fsv_good_pair_pass_bad_pair_fail(self):
        from rfauto.service.certify_design import certify_design_evidence

        f, y = _fsv_curve()
        good = {"label": "identity", "freq_a": f, "val_a": y, "freq_b": f, "val_b": y}
        bad = {"label": "offset", "freq_a": f, "val_a": y, "freq_b": f, "val_b": y + 20.0}

        pkg_good = certify_design_evidence(design="d", fsv_pairs=[good])
        assert _factor(pkg_good, "vv_history")["status"] == "PASS"
        assert _factor(pkg_good, "vv_history")["evidence"]["worst_gdm_grade"] == "Ex"

        pkg_bad = certify_design_evidence(design="d", fsv_pairs=[bad])
        assert _factor(pkg_bad, "vv_history")["status"] == "FAIL"
        assert _factor(pkg_bad, "vv_history")["evidence"]["worst_gdm_grade"] == "VP"

        pkg_mixed = certify_design_evidence(design="d", fsv_pairs=[good, bad])
        assert _factor(pkg_mixed, "vv_history")["status"] == "FAIL"

    def test_certificate_fail_drives_fail_verdict(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        path, _ = _linear_samples(tmp_path)
        pkg = certify_design_evidence(
            design="d", samples_path=path,
            params_center={"arm_len_mm": 21.0, "series_w_mm": 0.35})
        assert _factor(pkg, "results_robustness")["status"] == "FAIL"
        assert pkg["verdict"] == "FAIL"
        assert _factor(pkg, "conclusion")["status"] == "FAIL"

    def test_all_sources_present_certifies(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(design="d", **_full_inputs(tmp_path))
        assert [f["status"] for f in pkg["factors"]] == ["PASS"] * 8, pkg
        assert pkg["verdict"] == "CERTIFIED"

    def test_conclusion_partial_when_some_unknown(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(design="d")  # 全缺源
        seven = [f["status"] for f in pkg["factors"][:7]]
        assert seven == ["UNKNOWN"] * 7
        assert pkg["verdict"] == "PARTIAL"
        assert _factor(pkg, "conclusion")["status"] == "WARN"


# --------------------------------------------------------------------------- #
# 缺源语义 / JSON / 非法输入
# --------------------------------------------------------------------------- #

class TestRobustness:
    def test_missing_sources_marked_unknown(self):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(design="d")
        assert pkg["ok"] is True
        for name in ("v_and_v", "input_pedigree", "uncertainty_characterization",
                     "results_robustness", "ms_history", "data_history", "vv_history"):
            assert _factor(pkg, name)["status"] == "UNKNOWN", name
        assert _factor(pkg, "vv_history")["evidence"]["worst_gdm_grade"] is None

    def test_json_roundtrip(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(design="d", **_full_inputs(tmp_path))
        text = json.dumps(pkg, ensure_ascii=False, sort_keys=True)
        assert json.loads(text) == pkg

    def test_invalid_samples_path_reports_error(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(
            design="d", samples_path=tmp_path / "missing.json",
            params_center={"arm_len_mm": 19.0})
        assert pkg["ok"] is False
        assert pkg["errors"] and "不存在" in pkg["errors"][0]

    def test_samples_without_center_reports_error(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        path, _ = _linear_samples(tmp_path)
        pkg = certify_design_evidence(design="d", samples_path=path)
        assert pkg["ok"] is False and pkg["errors"]

    def test_missing_axis_reports_error(self, tmp_path):
        from rfauto.service.certify_design import certify_design_evidence

        path, _ = _linear_samples(tmp_path)
        pkg = certify_design_evidence(
            design="d", samples_path=path,
            params_center={"arm_len_mm": 19.0})
        assert pkg["ok"] is False
        assert any("series_w_mm" in e for e in pkg["errors"])

    def test_invalid_fsv_pair_marks_unknown_not_crash(self):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(
            design="d",
            fsv_pairs=[{"label": "bad", "freq_a": [1.0, 2.0, 3.0],
                        "val_a": [1.0, 2.0], "freq_b": [1.0, 2.0, 3.0],
                        "val_b": [1.0, 2.0, 3.0]}])
        f = _factor(pkg, "vv_history")
        assert f["status"] == "UNKNOWN"
        assert f["evidence"]["fsv"][0]["ok"] is False
        assert f["evidence"]["fsv_errors"]

    def test_invalid_koh_interval_warns(self):
        from rfauto.service.certify_design import certify_design_evidence

        pkg = certify_design_evidence(
            design="d",
            koh_interval={"mean": 1.0, "lo95": 2.0, "hi95": 1.0})
        f = _factor(pkg, "uncertainty_characterization")
        assert f["status"] == "WARN"
        assert f["evidence"]["koh_interval"] is None
