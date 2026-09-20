"""diagnosis 孤岛接线测试——run_once 出指标后自动诊断 → metrics.json + report.md。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _recipe(tmp_path, arm_len_mm=20.5, name="recipe.yaml"):
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {"arm_len_mm": {"value": arm_len_mm, "unit": "mm"}},
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 201},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "min_above", "value": -4.0},
        ],
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


def _run(tmp_path, **kw):
    from rfauto.service.api import run_once

    result = run_once(_recipe(tmp_path, **kw), adapter_name="fake")
    assert result["ok"], result.get("errors")
    run_dir = Path(result["run_dir"])
    metrics_data = json.loads(
        (run_dir / "results" / "metrics.json").read_text(encoding="utf-8")
    )
    report_md = (run_dir / "report.md").read_text(encoding="utf-8")
    return run_dir, metrics_data, report_md


class TestDiagnosisWiring:
    def test_metrics_json_contains_diagnosis_section(self, tmp_path):
        _, metrics_data, _ = _run(tmp_path)
        assert "diagnosis" in metrics_data
        diag = metrics_data["diagnosis"]
        assert diag is not None
        assert diag["ok"] is True
        assert "diagnoses" in diag and "suggestions" in diag

    def test_report_md_contains_diagnosis_section(self, tmp_path):
        _, _, report_md = _run(tmp_path)
        assert "## Diagnosis" in report_md

    def test_r002_triggers_on_high_s11(self):
        """R002 触发路径（引擎直测；fake 解析模型 |S11|<=0.3 无法经 run_once 达阈值）。"""
        from rfauto.infra.diagnosis import diagnose_results

        diag = diagnose_results(
            {"s11_db_max_in_band": -5.0},
            model_name="wilkinson_power_divider",
            objectives=[{"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15}],
        )
        rule_ids = [d["rule_id"] for d in diag["diagnoses"]]
        assert "R002" in rule_ids
        assert diag["suggestions"]

    def test_r002_missing_metric_skipped(self):
        """C5 修复回归：指标缺失时跳过而非误报。"""
        from rfauto.infra.diagnosis import diagnose_results

        diag = diagnose_results(
            {},  # 无任何指标
            model_name="wilkinson_power_divider",
        )
        assert diag["diagnoses"] == []

    def test_diagnosis_failure_non_blocking(self, tmp_path, monkeypatch):
        """诊断引擎崩溃不得影响 run_once 主流程。"""
        from rfauto.infra import diagnosis as diag_mod

        def boom(*a, **kw):
            raise RuntimeError("rules 解析失败")

        monkeypatch.setattr(diag_mod, "diagnose_results", boom)
        from rfauto.service.api import run_once

        result = run_once(_recipe(tmp_path), adapter_name="fake")
        assert result["ok"], "诊断失败必须非阻断"

    def test_html_report_includes_diagnosis(self, tmp_path):
        from rfauto.infra.report import generate_report

        path = generate_report(
            tmp_path,
            {"s11_db_max_in_band": -5.0},
            format="html",
            diagnosis={
                "diagnoses": [{
                    "rule_id": "R002", "severity": "warning",
                    "metric": "s11_db_max_in_band", "value": -5.0, "hint": "检查馈线",
                }],
                "suggestions": ["检查馈线尺寸"],
            },
        )
        content = path.read_text(encoding="utf-8")
        assert "Diagnosis" in content and "R002" in content


class TestG12CrossEngineDivergence:
    """G12：跨引擎分歧诊断（§10.7 / §10.22 #19）——配置逐项 diff + 教训核对表。

    人为注入 3 类已知分歧（网格档 / 波端口官参 / 同名参数语义），断言诊断
    清单 top-2 命中真实原因；全部确定性输入，不依赖 LLM。
    """

    @staticmethod
    def _config():
        return {
            "mesh": {"mesh_mm": 0.45, "scheme": "guided"},
            "port": {
                "wave_port_height_mm": 3.5,
                "wave_port_width_mm": 5.0,
                "reference_plane_mm": 0.0,
            },
            "material": {"substrate_er": 3.66, "loss_tangent": 0.0037},
            "boundary": {"type": "radiation", "air_margin_mm": 10.0},
        }

    @staticmethod
    def _diverged_results():
        return {"f0_ghz": 2.40, "s11_db_min": -22.0}, {"f0_ghz": 2.52, "s11_db_min": -14.0}

    def test_mesh_level_divergence_top2_hit(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        a = self._config()
        b = self._config()
        b["mesh"] = {"mesh_mm": 0.6, "scheme": "auto"}
        ra, rb = self._diverged_results()
        report = diagnose_divergence(a, b, result_a=ra, result_b=rb)
        assert "mesh_level_mismatch" in report["top_causes"][:2]
        mesh_paths = {e["path"] for e in report["config_diff"]["dimensions"]["mesh"]}
        assert {"mesh.mesh_mm", "mesh.scheme"} <= mesh_paths
        assert report["config_diff"]["dimensions"]["port"] == []

    def test_port_size_official_deviation_top2_hit(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        a = self._config()
        b = self._config()
        b["port"] = {
            "wave_port_height_mm": 7.0,
            "wave_port_width_mm": 5.0,
            "reference_plane_mm": 0.0,
        }
        official = {"port": {"wave_port_height_mm": 3.5, "wave_port_width_mm": 5.0}}
        report = diagnose_divergence(
            a, b, official=official,
            result_a={"f0_ghz": 2.40, "s11_db_min": -22.0},
            result_b={"f0_ghz": 2.41, "s11_db_min": -13.0},
        )
        assert "port_size_official_deviation" in report["top_causes"][:2]
        top = next(d for d in report["diagnoses"] if d["id"] == "port_size_official_deviation")
        assert top["lesson_ref"].startswith("#191")
        assert report["checklist"][1]["hit"] is True

    def test_same_name_semantics_inverted_top2_hit(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        a = self._config()
        a["param_semantics"] = {"series_w_mm": "impedance_line_width"}
        b = self._config()
        b["param_semantics"] = {"series_w_mm": "shunt_line_width"}
        ra, rb = self._diverged_results()
        report = diagnose_divergence(a, b, result_a=ra, result_b=rb)
        assert report["top_causes"][0] == "param_semantics_inverted"
        assert "param_semantics_inverted" in report["top_causes"][:2]
        assert report["checklist"][0]["hit"] is True

    def test_numeric_reciprocal_flagged_as_semantics(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        a = self._config()
        a["mesh"]["cells_per_wavelength"] = 2.0
        b = self._config()
        b["mesh"]["cells_per_wavelength"] = 0.5
        report = diagnose_divergence(
            a, b, result_a={"f0_ghz": 2.4}, result_b={"f0_ghz": 2.4})
        assert "param_semantics_inverted" in report["top_causes"][:2]

    def test_clean_pair_not_diverged(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        report = diagnose_divergence(
            self._config(), self._config(),
            result_a={"f0_ghz": 2.4, "s11_db_min": -20.0},
            result_b={"f0_ghz": 2.4, "s11_db_min": -20.0},
        )
        assert report["diverged"] is False
        assert report["diagnoses"] == []
        assert report["top_causes"] == []

    def test_unit_normalization_avoids_false_diff(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        a = self._config()
        a["mesh"] = {"mesh_mm": "0.5mm"}
        b = self._config()
        b["mesh"] = {"mesh_mm": "500um"}
        report = diagnose_divergence(a, b, result_a={}, result_b={})
        assert report["config_diff"]["dimensions"]["mesh"] == []
        assert report["diverged"] is False

    def test_checklist_covers_three_lessons_and_never_calls_llm(self):
        from rfauto.infra.diagnosis import diagnose_divergence

        a = self._config()
        b = self._config()
        b["mesh"] = {"mesh_mm": 0.6}
        report = diagnose_divergence(
            a, b, result_a={"f0_ghz": 2.4}, result_b={"f0_ghz": 2.4})
        lessons = [entry["lesson"] for entry in report["checklist"]]
        assert any("#154" in item for item in lessons)
        assert any("#191" in item for item in lessons)
        assert any("先对照官方" in item for item in lessons)
        assert all(isinstance(entry["hit"], bool) for entry in report["checklist"])
        assert report["llm_role"] == "explain-only"

    def test_engine_method_delegates(self):
        from rfauto.infra.diagnosis import DiagnosisEngine

        engine = DiagnosisEngine()
        a = self._config()
        b = self._config()
        b["material"] = {"substrate_er": 4.4}
        report = engine.diagnose_divergence(
            a, b, result_a={"f0_ghz": 2.4}, result_b={"f0_ghz": 2.4})
        assert "material_mismatch" in report["top_causes"][:2]
