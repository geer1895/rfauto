"""全链路集成测试——FakeAdapter 驱动，无 license 秒级跑通。"""

import json
from pathlib import Path

from rfauto.core.contracts import AdsExchangeContract
from rfauto.core.objectives import Objective, SpecEvaluator


class TestFullRunFake:
    """FakeAdapter 全链路：connect → build → solve → export → metrics。"""

    def test_wilkinson_full_run(self, fake_adapter_3port, wilkinson_recipe, tmp_path):
        """完整 Wilkinson 功分器仿真（FakeAdapter 3 端口, 与契约一致）。"""
        recipe = wilkinson_recipe
        fake_adapter = fake_adapter_3port  # 3 端口, 与默认契约 port_order 一致

        # 1. 连接
        fake_adapter.connect({})

        # 2. 构建
        from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin
        from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams(**{
            k: (v["value"] if isinstance(v, dict) else v)
            for k, v in recipe["params"].items()
            if k in WilkinsonPDParams.model_fields
        })
        plugin.build(fake_adapter, params)

        # 3. 设置变量
        var_dict = {}
        for k, v in recipe["params"].items():
            if isinstance(v, dict) and "value" in v:
                var_dict[k] = f"{v['value']}{v.get('unit', 'mm')}"
            elif isinstance(v, (int, float)):
                var_dict[k] = str(v)
        fake_adapter.set_variables(var_dict)

        # 4. 求解
        report = fake_adapter.solve("main_setup")
        assert report.success, f"求解失败: {report.message}"

        # 5. 导出 Touchstone
        sparams_path = tmp_path / "test.s3p"
        contract = AdsExchangeContract()
        exported = fake_adapter.export_touchstone(sparams_path, contract)
        assert exported.exists()

        # 6. 计算指标
        network = fake_adapter.get_sparams()
        objectives = [Objective(**o) for o in recipe.get("objectives", [])]
        metrics = SpecEvaluator.compute_metrics(network, objectives)
        cost = SpecEvaluator.evaluate_objectives(metrics, objectives)

        assert "s11_db_max_in_band" in metrics
        assert cost >= 0.0

        # 7. 校验
        assert SpecEvaluator.check_passivity(network)
        assert SpecEvaluator.check_reciprocity(network)

        fake_adapter.close()

    def test_metrics_json_output(self, fake_adapter, tmp_path):
        """验证 metrics.json 输出格式。"""
        fake_adapter.connect({})
        fake_adapter.solve("test")
        network = fake_adapter.get_sparams()

        objectives = [
            Objective(metric="s11_db", band=[2.3, 2.5], op="max_below", value=-10),
        ]
        metrics = SpecEvaluator.compute_metrics(network, objectives)

        metrics_data = {
            "run_id": "test_00000000_00000000",
            "metrics": metrics,
            "cost": SpecEvaluator.evaluate_objectives(metrics, objectives),
        }
        metrics_path = tmp_path / "metrics.json"
        metrics_path.write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")

        loaded = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert loaded["run_id"] == "test_00000000_00000000"
        assert "metrics" in loaded

    def test_run_once_generates_figs_and_report(self, tmp_path, monkeypatch, wilkinson_recipe):
        """P0 验收防再犯：run_once 全链路必须产出 S 参数图 + report.md。

        回归背景：审计发现 run 目录只有 s2p/metrics.json、没有 figs（与
        "出 S 参数图"的预期记录不符）。根因是 run_once 未调用 generate_report。
        """
        from rfauto.service.api import run_once

        monkeypatch.chdir(tmp_path)
        import yaml

        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(wilkinson_recipe), encoding="utf-8")

        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")

        run_dir = Path(result["run_dir"])
        figs = list((run_dir / "results" / "figs").glob("*.png"))
        assert len(figs) >= 2, f"应生成 S11/S21 两张图，实际: {figs}"
        assert (run_dir / "report.md").exists()
        assert Path(result["report"]).exists()

    def test_replay_run_reproduces_and_checks_versions(self, tmp_path, monkeypatch, wilkinson_recipe):
        """P1 验收项：rfauto replay 可复现任一次 run（含版本核对）。"""
        from rfauto.service.api import replay_run, run_once

        monkeypatch.chdir(tmp_path)
        import yaml

        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(wilkinson_recipe), encoding="utf-8")

        first = run_once(recipe_path)
        assert first["ok"], first.get("errors")

        # 正常 replay
        result = replay_run(first["run_id"])
        assert result["ok"], result.get("errors") or result.get("result", {}).get("errors")
        assert result["source_run_id"] == first["run_id"]
        assert result["replay_run_id"] not in (None, first["run_id"])

        # 复现 run 应产出 metrics
        replay_dir = Path("runs") / result["replay_run_id"]
        assert (replay_dir / "results" / "metrics.json").exists()

        # 不存在的 run 显式报错
        bad = replay_run("no_such_run_0000")
        assert not bad["ok"]
        assert any("未找到 run" in e for e in bad["errors"])
