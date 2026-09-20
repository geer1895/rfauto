"""阶段 4.1：适配器 SDK（脚手架 + 参数语义断言）测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


class TestScaffoldAdapter:
    def test_generates_skeleton(self, tmp_path):
        from rfauto.service.adapter_kit import scaffold_adapter

        r = scaffold_adapter("cst_studio", output_dir=tmp_path)
        assert r["ok"]
        assert r["class_name"] == "CstStudioAdapter"
        text = Path(r["path"]).read_text(encoding="utf-8")
        assert "class CstStudioAdapter(EMSolverAdapter)" in text
        assert "param_semantics" in text

    def test_no_overwrite_and_bad_name(self, tmp_path):
        from rfauto.service.adapter_kit import scaffold_adapter

        r1 = scaffold_adapter("my_solver", output_dir=tmp_path)
        assert r1["ok"]
        r2 = scaffold_adapter("my_solver", output_dir=tmp_path)
        assert not r2["ok"]
        r3 = scaffold_adapter("9bad", output_dir=tmp_path)
        assert not r3["ok"]


class TestCheckParamSemantics:
    def _recipe(self, tmp_path):
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"arm_len_mm": {"value": 20.5}},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "optimization": {"params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
                "shunt_w_mm": {"low": 0.90, "high": 1.30},
            }},
        }
        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return str(path)

    def test_nominal_recipe_passes(self, tmp_path):
        from rfauto.service.adapter_kit import check_param_semantics

        r = check_param_semantics(self._recipe(tmp_path))
        assert r["ok"], r["issues"]
        assert r["n_opt_params"] == 3

    def test_missing_semantics_flagged(self, tmp_path, monkeypatch):
        """模板语义声明缺参数 → 断言必须拦截（#154 教训）。"""
        from rfauto.adapters import openems_templates
        from rfauto.service.adapter_kit import check_param_semantics

        meta = {k: dict(v) for k, v in openems_templates.TEMPLATE_META.items()}
        meta["wilkinson"]["param_semantics"] = ""
        monkeypatch.setattr(openems_templates, "TEMPLATE_META", meta)
        r = check_param_semantics(self._recipe(tmp_path))
        assert not r["ok"]
        assert any(i["check"] == "template_semantics" for i in r["issues"])

    def test_missing_recipe_rejected(self, tmp_path):
        from rfauto.service.adapter_kit import check_param_semantics

        assert not check_param_semantics(tmp_path / "nope.yaml")["ok"]

class TestScaffoldContract:
    """B-28：骨架 = 与已知适配器（openEMS/COMSOL/Palace）同一 EMSolverAdapter 契约。"""

    @staticmethod
    def _scaffold_and_import(monkeypatch, tmp_path, name):
        import importlib.util

        from rfauto.adapters import em_solver_base
        from rfauto.service.adapter_kit import scaffold_adapter

        fresh = em_solver_base.EMSolverRegistry()
        monkeypatch.setattr(em_solver_base, "get_global_registry", lambda: fresh)
        result = scaffold_adapter(name, output_dir=tmp_path)
        assert result["ok"], result.get("errors")
        spec = importlib.util.spec_from_file_location(f"_gen_{name}", result["path"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return result, module, fresh

    def test_scaffold_satisfies_contract_and_registers(self, tmp_path, monkeypatch):
        from rfauto.adapters.em_solver_base import EMSolverAdapter, EMSolverConfig
        from rfauto.service.adapter_kit import check_adapter_contract

        result, module, fresh = self._scaffold_and_import(
            monkeypatch, tmp_path, "cst_mws")
        cls = getattr(module, result["class_name"])
        assert issubclass(cls, EMSolverAdapter)
        contract = check_adapter_contract(cls)
        assert contract["ok"], contract
        assert contract["missing"] == []
        assert contract["abstract"] == []
        adapter = cls(EMSolverConfig(solver_type="cst_mws"))
        assert adapter.is_available() is False
        # 注册入口存在，且模块导入即注册（同 openems/comsol/palace 模式）
        assert callable(getattr(module, result["register_fn"]))
        assert fresh.is_registered("cst_mws")
        assert "param_semantics" in Path(result["path"]).read_text(encoding="utf-8")

    def test_known_adapters_share_the_same_contract(self):
        from rfauto.service.adapter_kit import KNOWN_ADAPTERS, check_known_adapters

        # 防空测：已知适配器目录必须非空且覆盖 COMSOL/openEMS
        assert {"openems", "comsol"} <= set(KNOWN_ADAPTERS)
        report = check_known_adapters()
        for name in ("openems", "comsol", "palace"):
            entry = report["adapters"][name]
            assert entry["contract"] == "emsolver"
            assert entry["ok"], (name, entry)
        # ADS 是原生 Python API 子进程通道，显式标注不套用 EMSolver 契约
        assert report["adapters"]["ads"]["contract"] == "ads_python_api"

    def test_broken_adapter_fails_contract_check(self):
        from rfauto.adapters.em_solver_base import EMSolverAdapter
        from rfauto.service.adapter_kit import check_adapter_contract

        class BrokenAdapter(EMSolverAdapter):
            def connect(self) -> bool:
                return True

        report = check_adapter_contract(BrokenAdapter)
        assert not report["ok"]
        assert "solve" in report["missing"]
        assert "solve" in report["abstract"]


class TestSemanticConflict:
    """B-28：同名参数跨通道语义相反（#154 实例）必须被检出。"""

    def _recipe(self, tmp_path):
        recipe = {
            "model": "wilkinson_power_divider",
            "optimization": {"params": {
                "arm_len_mm": {"low": 18.0, "high": 23.0},
                "series_w_mm": {"low": 0.25, "high": 0.45},
                "shunt_w_mm": {"low": 0.90, "high": 1.30},
            }},
        }
        path = tmp_path / "r.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return str(path)

    def test_conflicting_same_name_roles_flagged(self, tmp_path, monkeypatch):
        from rfauto.models import registry as registry_mod
        from rfauto.service.adapter_kit import check_param_semantics

        class _SwappedPlugin:
            hfss_var_map: ClassVar[dict[str, str]] = {
                "arm_len_mm": "arm_len",
                "series_w_mm": "series_w",
                "shunt_w_mm": "shunt_w",
            }
            # #154 实例：series/shunt 语义跨通道相反
            physics_roles: ClassVar[dict[str, str]] = {
                "series_w_mm": "shunt_line_width_mm",
                "shunt_w_mm": "impedance_line_width_mm",
            }

        monkeypatch.setattr(registry_mod, "get", lambda name: _SwappedPlugin)
        report = check_param_semantics(self._recipe(tmp_path))
        assert not report["ok"]
        checks = {issue["check"] for issue in report["issues"]}
        assert "semantic_conflict" in checks
        assert "channel_conflict" in checks

    def test_consistent_roles_pass(self, tmp_path):
        from rfauto.service.adapter_kit import check_param_semantics

        report = check_param_semantics(self._recipe(tmp_path))
        assert report["ok"], report["issues"]
        assert report["semantic_channels"] == ["openems_template"]
        assert report["n_semantic_roles"] >= 3

