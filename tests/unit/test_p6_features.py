"""P6 功能测试（知识库 + 反标 + 代理模型 + 公差 + 变异）。"""

from __future__ import annotations

import numpy as np


class TestDiagnosisEngine:
    """知识库诊断引擎测试。"""

    def test_load_rules(self):
        from rfauto.infra.diagnosis import DiagnosisEngine
        engine = DiagnosisEngine()
        assert len(engine.rules) > 0

    def test_diagnose_bad_s11(self):
        from rfauto.infra.diagnosis import diagnose_results
        metrics = {"s11_db_max_in_band": -5.0}  # 很差的 S11
        result = diagnose_results(metrics, model_name="wilkinson_power_divider")
        assert result["ok"] is True
        assert len(result["diagnoses"]) > 0
        assert result["diagnoses"][0]["rule_id"] == "R002"

    def test_diagnose_good_s11(self):
        from rfauto.infra.diagnosis import diagnose_results
        metrics = {"s11_db_max_in_band": -20.0}  # 好的 S11
        result = diagnose_results(metrics, model_name="wilkinson_power_divider")
        assert result["ok"] is True
        assert len(result["diagnoses"]) == 0


class TestBackAnnotator:
    """反标回路测试。"""

    def test_back_annotate(self):
        from rfauto.linkage.back_annotation import back_annotate
        ads_metrics = {"capacitor_pf": 2.0}
        result = back_annotate(ads_metrics)
        assert "shunt_w" in result
        assert result["shunt_w"] > 0

    def test_custom_mapping(self):
        from rfauto.linkage.back_annotation import BackAnnotator
        mapping = {"test_val": {"hfss_variable": "arm_len", "transform": "linear", "reference": {"test": 1.0, "len": 20.0}}}
        annotator = BackAnnotator(mapping=mapping)
        result = annotator.ads_to_hfss_params({"test_val": 2.0})
        assert result["arm_len"] == 40.0


class TestSurrogateModel:
    """代理模型测试。"""

    def test_rbf_fit_predict(self):
        from rfauto.optimization.surrogate import ResponseSurfaceModel
        X = np.array([[0, 0], [1, 0], [0, 1], [1, 1]])
        y = np.array([0, 1, 1, 2])
        model = ResponseSurfaceModel(backend="rbf")
        model.fit(X, y)
        mean, _std = model.predict(np.array([[0.5, 0.5]]))
        assert len(mean) == 1

    def test_prescreener(self):
        from rfauto.optimization.surrogate import SurrogatePrescreener
        prescreener = SurrogatePrescreener(n_initial=10, n_prescreen=50)
        def obj(x): return float(np.sum(x**2))
        bounds = (np.array([-1, -1]), np.array([1, 1]))
        result = prescreener.prescreen(obj, bounds, n_features=2)
        assert result["ok"] is True
        assert result["n_evaluations"] == 10


class TestToleranceAnalyzer:
    """公差分析测试。"""

    def test_tolerance_analysis(self):
        from rfauto.optimization.tolerance import ToleranceAnalyzer
        analyzer = ToleranceAnalyzer(n_samples=100)
        nominal = {"x": 1.0, "y": 2.0}
        tolerances = {"x": 0.1, "y": 0.2}
        def obj(params): return {"value": params["x"] + params["y"]}
        specs = {"value": {"max": 4.0}}
        result = analyzer.analyze(nominal, tolerances, obj, specs)
        assert result["ok"] is True
        assert 0 <= result["yield_rate"] <= 1


class TestTopologyMutator:
    """拓扑变异测试。"""

    def test_mutate_add_stub(self):
        from rfauto.optimization.mutation import TopologyMutator
        mutator = TopologyMutator(seed=42)
        recipe = {"model": "test", "ops": [], "params": {"x": {"value": 1.0}}}
        mutated = mutator.mutate(recipe, n_mutations=1, mutation_types=["add_stub"])
        assert len(mutated) == 1
        assert len(mutated[0]["ops"]) == 1
        assert mutated[0]["ops"][0]["op"] == "add_stub"

    def test_mutation_reviewer(self):
        from rfauto.optimization.mutation import MutationReviewer
        reviewer = MutationReviewer()
        recipe = {"model": "test"}
        reviewer.submit(recipe, "add_stub")
        assert len(reviewer.get_pending()) == 1
        approved = reviewer.approve(0)
        assert approved is not None
        assert len(reviewer.approved) == 1
