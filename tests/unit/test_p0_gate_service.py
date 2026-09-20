"""阶段 1.1：跨保真 gate 资产复用通道测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
        }},
    }
    path = tmp_path / "r.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


def _asset(tmp_path, costs_high):
    """openEMS 臂资产：metrics 直接内嵌 cost（s11_db_max_in_band 即 cost）。"""
    samples = [{"params": {"arm_len_mm": 18.0 + i * 0.4},
                "metrics": {"s11_db_max_in_band": c}}
               for i, c in enumerate(costs_high)]
    data = {
        "bounds": {"arm_len_mm": [18.0, 23.0]},
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "samples": samples,
    }
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestCrossGateFromAsset:
    def test_consistent_ranking_pass(self, tmp_path, recipe_path):
        """两通道排序一致（fake=高保真同序）→ PASS。"""
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        high = [-10.0 + i for i in range(10)]  # 单调
        asset = _asset(tmp_path, high)
        fake_costs = {18.0 + i * 0.4: float(-10.0 + i) for i in range(10)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        assert r["ok"], r.get("errors")
        assert r["verdict"] == "PASS"
        assert r["spearman_rho"] == pytest.approx(1.0)
        assert r["top5_recall"] == pytest.approx(1.0)

    def test_anti_correlated_ranking_fail(self, tmp_path, recipe_path):
        """两通道排序反相关 → FAIL 如实（不凑绿）。"""
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        high = [-10.0 + i for i in range(10)]
        asset = _asset(tmp_path, high)
        fake_costs = {18.0 + i * 0.4: float(10.0 - i) for i in range(10)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        assert r["ok"]
        assert r["verdict"] == "FAIL"
        assert r["spearman_rho"] == pytest.approx(-1.0)

    def test_objectives_mismatch_rejected(self, tmp_path, recipe_path):
        """资产与配方 objectives 不一致 → 拒绝（口径必须同源）。"""
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        data = {
            "bounds": {"arm_len_mm": [18.0, 23.0]},
            "objectives": [{"metric": "s21_db", "band": [2.3, 2.5],
                            "op": "mean_within", "value": [-3.6, -3.1]}],
            "samples": [{"params": {"arm_len_mm": 20.0},
                         "metrics": {"s21_db_mean_in_band": -3.3}}],
        }
        asset = tmp_path / "s.json"
        asset.write_text(json.dumps(data), encoding="utf-8")
        r = cross_gate_from_asset(recipe_path, asset)
        assert not r["ok"]
        assert "不一致" in r["errors"][0]

    def test_insufficient_samples_rejected(self, tmp_path, recipe_path):
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        asset = _asset(tmp_path, [-10.0, -11.0])
        r = cross_gate_from_asset(recipe_path, asset,
                                  fake_cost_fn=lambda r_, p: -10.0)
        assert not r["ok"]

    def test_missing_files_rejected(self, tmp_path, recipe_path):
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        assert not cross_gate_from_asset(recipe_path, tmp_path / "no.json")["ok"]
        assert not cross_gate_from_asset(tmp_path / "no.yaml",
                                         tmp_path / "s.json")["ok"]

    def test_recall_invalid_below_8_samples(self, tmp_path, recipe_path):
        """n<8：top5/top8 recall 恒 1（无效统计量）→ 置 None 并在
        verdict_reason 注明"样本 <8 recall 无效"；ρ 门保持。"""
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        high = [-10.0 + i for i in range(6)]   # 6 个有效点（≥5 但 <8）
        asset = _asset(tmp_path, high)
        fake_costs = {18.0 + i * 0.4: float(-10.0 + i) for i in range(6)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        assert r["ok"], r.get("errors")
        assert r["top5_recall"] is None        # 不再输出恒 1 的伪 recall
        assert r["verdict_reason"] is not None
        assert "recall 无效" in r["verdict_reason"]
        assert "< 8" in r["verdict_reason"]
        # ρ 门保持：排序一致（ρ=1）→ PASS；反相关（ρ=−1）→ FAIL
        assert r["spearman_rho"] == pytest.approx(1.0)
        assert r["verdict"] == "PASS"

        # 反相关同规模：ρ 门单独判 FAIL（recall 缺席不改变判定方向）
        high2 = [-10.0 + i for i in range(6)]
        asset2 = _asset(tmp_path, high2)
        fake_costs2 = {18.0 + i * 0.4: float(10.0 - i) for i in range(6)}
        r2 = cross_gate_from_asset(
            recipe_path, asset2,
            fake_cost_fn=lambda recipe, pt: fake_costs2[pt["arm_len_mm"]])
        assert r2["ok"]
        assert r2["top5_recall"] is None
        assert r2["verdict"] == "FAIL"
        json.dumps(r)   # verdict_reason/None 均可 JSON 序列化


class TestCrossGateFsv:
    """§10.20 ⑥：跨保真门并行暴露 D12 曲线级 FSV 等级（加性，不改 verdict）。"""

    def test_fsv_matches_core_and_keeps_legacy_verdict(self, tmp_path,
                                                       recipe_path):
        from rfauto.core.fsv import fsv as core_fsv
        from rfauto.core.objectives import Objective, SpecEvaluator
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        n = 24
        high_vals = [float(i) for i in range(n)]
        asset = _asset(tmp_path, high_vals)
        fake_costs = {18.0 + i * 0.4: float(i) + (0.5 if i % 3 else -0.5)
                      for i in range(n)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        assert r["ok"], r.get("errors")
        # 既有排序门口径逐字保留（回归）
        assert r["n_evaluated"] == n
        assert r["verdict"] == ("PASS" if r["spearman_rho"] >= 0.8
                                and r["top5_recall"] >= 0.8 else "FAIL")
        # 新增曲线级 FSV 段与直接调 core/fsv 一致
        fsv = r["fsv"]
        assert fsv["ok"] is True, fsv
        assert fsv["n_points"] == n
        assert fsv["x_axis"].startswith("配对点序号")
        objs = [Objective(metric="s11_db", band=[2.3, 2.5], op="max_below",
                          value=-15)]
        low = [fake_costs[18.0 + i * 0.4] for i in range(n)]
        high = [SpecEvaluator.evaluate_objectives(
            {"s11_db_max_in_band": v}, objs) for v in high_vals]
        x = [float(i) for i in range(n)]
        raw = core_fsv(x, low, x, high)
        assert fsv["adm_grade"] == raw["adm_grade"]
        assert fsv["fdm_grade"] == raw["fdm_grade"]
        assert fsv["gdm_grade"] == raw["gdm_grade"]
        assert fsv["gdm_mean"] == pytest.approx(raw["gdm_mean"])
        json.dumps(r)  # result 必须 JSON 可序列化（含 fsv 段）

    def test_fsv_best_effort_below_min_points(self, tmp_path, recipe_path):
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        high = [-10.0 + i for i in range(10)]
        asset = _asset(tmp_path, high)
        fake_costs = {18.0 + i * 0.4: float(-10.0 + i) for i in range(10)}
        r = cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]])
        assert r["ok"] and r["verdict"] == "PASS"
        assert r["fsv"]["ok"] is False
        assert "MIN_POINTS" in r["fsv"]["error"]
        assert r["fsv"]["n_points"] == 10

class TestFsvGradeGateWiring:
    """§10.20 ⑥ 收口：FSV 等级门并入 verdict（PASS/FAIL/降级三路语义）。

    等级数据经 cross_gate 全路径实测钉住（tmp 探针，确定性；注意资产臂
    metrics 经 SpecEvaluator 变换为 cost=v+15）：low=2i+31 vs metrics=i →
    GDM=1.020（P 级）且 ρ=1/recall=1——排序门满分而曲线级剖面畸变，正是
    等级门要拦的形态；low=(i+15)+0.3sin(8πi/24) → Ex 级。
    """

    @staticmethod
    def _run(tmp_path, recipe_path, n, low_of, high_of, **kw):
        from rfauto.service.p0_gate_service import cross_gate_from_asset

        high = [high_of(i) for i in range(n)]
        asset = _asset(tmp_path, high)
        fake_costs = {18.0 + i * 0.4: low_of(i) for i in range(n)}
        return cross_gate_from_asset(
            recipe_path, asset,
            fake_cost_fn=lambda recipe, pt: fake_costs[pt["arm_len_mm"]], **kw)

    def test_poor_grade_downgrades_pass_to_fail(self, tmp_path, recipe_path):
        """ρ=1/recall=1 但 GDM=P（>门限 F）→ 等级门否决，verdict FAIL。"""
        n = 24
        r = self._run(tmp_path, recipe_path, n,
                      low_of=lambda i: 2.0 * i + 31.0,
                      high_of=lambda i: float(i))
        assert r["ok"], r.get("errors")
        assert r["spearman_rho"] == pytest.approx(1.0)      # 排序门满分
        assert r["top5_recall"] == pytest.approx(1.0)
        assert r["fsv"]["ok"] is True
        assert r["fsv"]["gdm_grade"] == "P"                 # 实测内核等级
        assert r["fsv"]["gdm_mean"] == pytest.approx(1.020, abs=0.01)
        assert r["fsv_gate"]["pass"] is False
        assert r["fsv_gate"]["degraded"] is False
        assert r["fsv_gate"]["grade"] == "P"
        assert r["fsv_gate"]["threshold"] == "F"
        # 单点口径本应 PASS，等级门否决 → FAIL
        assert r["verdict"] == "FAIL"
        assert "FSV 等级门否决" in r["verdict_reason"]
        json.dumps(r)

    def test_excellent_grade_keeps_pass(self, tmp_path, recipe_path):
        """ρ=1/recall=1 且 GDM=Ex（≤门限）→ 等级门通过，verdict PASS。"""
        import math

        n = 24
        r = self._run(
            tmp_path, recipe_path, n,
            low_of=lambda i: (i + 15.0) + 0.3 * math.sin(8.0 * math.pi * i / n),
            high_of=lambda i: float(i))
        assert r["ok"], r.get("errors")
        assert r["spearman_rho"] == pytest.approx(1.0)
        assert r["top5_recall"] == pytest.approx(1.0)
        assert r["fsv"]["gdm_grade"] == "Ex"
        assert r["fsv_gate"]["pass"] is True
        assert r["verdict"] == "PASS"

    def test_degraded_when_below_min_points(self, tmp_path, recipe_path):
        """n=10 < MIN_POINTS=16：FSV 不可用 → 门降级（pass=None），
        verdict 回既有单点口径（ρ/recall 过线仍 PASS，不因 FSV 缺席 FAIL）。"""
        n = 10
        r = self._run(tmp_path, recipe_path, n,
                      low_of=lambda i: float(i), high_of=lambda i: float(i))
        assert r["ok"], r.get("errors")
        assert r["fsv"]["ok"] is False
        assert r["fsv_gate"]["degraded"] is True
        assert r["fsv_gate"]["pass"] is None
        assert r["fsv_gate"]["grade"] is None
        assert r["verdict"] == "PASS"
        assert "FSV 等级门降级" in r["verdict_reason"]
        json.dumps(r)

    def test_looser_threshold_rescues_poor_grade(self, tmp_path, recipe_path):
        """自定义门限松绑（threshold=VP）：同一 P 级数据 → 门通过，PASS。"""
        n = 24
        r = self._run(tmp_path, recipe_path, n,
                      low_of=lambda i: 2.0 * i + 31.0,
                      high_of=lambda i: float(i),
                      fsv_grade_threshold="VP")
        assert r["ok"], r.get("errors")
        assert r["fsv"]["gdm_grade"] == "P"
        assert r["fsv_gate"]["pass"] is True
        assert r["fsv_gate"]["threshold"] == "VP"
        assert r["verdict"] == "PASS"

    def test_tighter_threshold_rejects_fair_grade(self, tmp_path, recipe_path):
        """自定义门限收紧（threshold=VG）：G 级数据 → 门否决，FAIL。"""
        import math

        n = 24
        # 实测探针：5.0 正弦叠同斜率剖面 → GDM=0.2905（G 级）且 ρ≥0.8
        r = self._run(
            tmp_path, recipe_path, n,
            low_of=lambda i: (i + 15.0) + 5.0 * math.sin(12.0 * math.pi * i / n),
            high_of=lambda i: float(i),
            fsv_grade_threshold="VG")
        assert r["ok"], r.get("errors")
        assert r["fsv"]["gdm_grade"] == "G"
        assert r["spearman_rho"] >= 0.8 and r["top5_recall"] >= 0.8
        assert r["fsv_gate"]["pass"] is False
        assert r["verdict"] == "FAIL"

    def test_emit_gate_artifact_records_gate(self, tmp_path, recipe_path):
        """emit_gate_artifact 落盘面：report.md/meta.metrics 携带等级门结论。

        emit_gate_artifact 走缺省 fake 镜像通道（wilkinson 解析模型），
        本测试验证降级/记录链路：等级门结论必须写进 report 与 meta
        （等级值不钉——取决于 fake 模型对注入剖面的形状）。
        """
        from rfauto.service.p0_gate_service import emit_gate_artifact

        n = 24
        high = [float(i) for i in range(n)]
        asset = _asset(tmp_path, high)
        r = emit_gate_artifact(recipe_path, asset)
        assert r["ok"], r.get("errors")
        run_dir = Path(r["run_dir"])
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        assert "FSV 等级门" in report
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert "fsv_gate" in meta["metrics"]
        assert set(meta["metrics"]["fsv_gate"]) >= {"grade", "pass", "degraded"}

    def test_fsv_gate_line_rendering(self):
        from rfauto.service.p0_gate_service import _fsv_gate_line

        assert "未计算" in _fsv_gate_line(None)
        assert "降级" in _fsv_gate_line({"degraded": True, "reason": "点数不足"})
        assert "PASS" in _fsv_gate_line(
            {"degraded": False, "pass": True, "grade": "VG", "threshold": "F"})
        line = _fsv_gate_line(
            {"degraded": False, "pass": False, "grade": "P", "threshold": "F"})
        assert "FAIL" in line and "P" in line


