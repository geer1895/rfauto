"""openEMS 优化通道产物化——分支挂点/registry 键/参数传递钉。

产物化面（先战役层补丁验证、后转 src 正式路径）：
- models.registry 注册 mline 最小插件（rfauto.models.mline.plugin）；
- optimizer._create_adapter 增 "openems" 分支（与 fake/hfss 同构）；
- 真评估链 = OpenEMSOptAdapter → OpenEMSSolver（render_script 整脚本重渲染）。

**零真机**：openEMS 求解一律 _StubSolver 注入（monkeypatch
rfauto.adapters.openems_solver.OpenEMSSolver），断言分支选择/配置传递/
registry 键；e11 战役路径（run_optimization adapter_name="openems"）同口径
stub 验证——scripts/e11_warm_start_campaign.py --adapter openems 自本产物化
起无需战役层补丁（e11_openems_harness.py）即可走通。
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

# 确保 src 在 path 中（仓内测试同 test_optimization.py 口径）
src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization.optimizer import _create_adapter, run_optimization


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    """chdir 沙箱 + 临时 optuna storage（#144：优化循环类单测禁污染真实 runs/）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )
    yield


@pytest.fixture
def mline_recipe() -> dict[str, Any]:
    """wp39 mline 问题域（e11 战役配方口径，DSL 暂无 εeff 指标时判据形）。"""
    return {
        "model": "mline",
        "params": {
            "w_mm": {"value": 1.113, "unit": "mm"},
            "line_len_mm": {"value": 40.0, "unit": "mm"},
        },
        "setup": {"freq_range_ghz": [2.0, 3.0], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.4, 2.6], "op": "max_below", "value": -24},
        ],
        "optimization": {"params": {"w_mm": {"low": 0.5, "high": 2.0}}},
    }


def _write_recipe(tmp_path: Path, recipe: dict[str, Any], name: str = "mline_v1.yaml") -> str:
    import yaml

    path = tmp_path / name
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class _StubResult:
    """EMSolverResult 替身（字段面=adapters.em_solver_base.EMSolverResult 子集）。"""

    def __init__(self, success: bool = True, message: str = "stub") -> None:
        self.success = success
        self.message = message
        self.freq_ghz = np.linspace(2.0, 3.0, 41)
        s = np.zeros((41, 2, 2), dtype=complex)
        self.s_params = s


class _StubSolver:
    """OpenEMSSolver 替身：记录 config/geometry，绝不触真机。"""

    instances: ClassVar[list[_StubSolver]] = []
    connect_ok: bool = True
    build_ok: bool = True
    result: _StubResult | None = None
    raise_in_solve: Exception | None = None

    def __init__(self, config: Any) -> None:
        self.config = config
        self.geometry: dict[str, Any] | None = None
        _StubSolver.instances.append(self)

    def connect(self) -> bool:
        return _StubSolver.connect_ok

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        self.geometry = dict(geometry)
        return _StubSolver.build_ok

    def solve(self) -> _StubResult:
        if _StubSolver.raise_in_solve is not None:
            raise _StubSolver.raise_in_solve
        assert _StubSolver.result is not None, "测试未装配 _StubSolver.result"
        return _StubSolver.result


@pytest.fixture
def stub_solver(monkeypatch):
    """注入 _StubSolver 并逐测重置类状态。"""
    import rfauto.adapters.openems_solver as oe_mod

    _StubSolver.instances = []
    _StubSolver.connect_ok = True
    _StubSolver.build_ok = True
    _StubSolver.result = _StubResult()
    _StubSolver.raise_in_solve = None
    monkeypatch.setattr(oe_mod, "OpenEMSSolver", _StubSolver)
    return _StubSolver


# ─── mline 模型插件（models.registry 注册表键） ──────────────────────────────


class TestMlineRegistry:
    def test_registered_with_expected_classvars(self):
        from rfauto.models.registry import get, list_models

        plugin_cls = get("mline")
        assert plugin_cls.name == "mline"
        assert plugin_cls.n_ports == 2
        assert plugin_cls.fake_model_type == "mline"
        assert plugin_cls.openems_template == "mline"
        assert plugin_cls.hfss_var_map == {}  # 配方参数名=设计变量名（恒等）
        assert "mline" in list_models()

    def test_params_schema(self):
        from rfauto.models.mline.schema import MlineParams
        from rfauto.models.registry import export_schema

        params = MlineParams()
        assert params.w_mm == pytest.approx(1.113)
        assert params.line_len_mm == pytest.approx(40.0)
        schema = export_schema("mline")
        assert set(schema["properties"]) == {"w_mm", "line_len_mm"}

    def test_build_is_noop_hook(self):
        from rfauto.models.mline.plugin import MlinePlugin
        from rfauto.models.mline.schema import MlineParams

        plugin = MlinePlugin()
        plugin.build(object(), MlineParams())  # 任何适配器上都不画几何
        assert plugin.evaluate_extras({"s11_db_max_in_band": -30.0}) == {
            "s11_db_max_in_band": -30.0}


# ─── fake 链等价钉（registry 驱动的 C4 推导路径） ────────────────────────────


class TestFakeChainEquivalence:
    def test_fake_branch_derives_mline_from_registry(self, mline_recipe):
        from rfauto.adapters.fake_adapter import FakeAdapter

        adapter, version = _create_adapter("fake", None, mline_recipe)
        try:
            assert version == "fake"
            assert isinstance(adapter, FakeAdapter)
            # C4：未显式指定 n_ports/model_type 时从插件元数据推导
            assert adapter.n_ports == 2
            assert adapter.model_type == "mline"
        finally:
            adapter.close()

    def test_fake_run_optimization_mline_zero_real_solve(self, tmp_path, mline_recipe):
        path = _write_recipe(tmp_path, mline_recipe)
        result = run_optimization(
            path, adapter_name="fake", max_trials=2, study_name="mline_fake_e2e")
        assert result["ok"] is True
        assert result["trials_completed"] == 2
        assert result["best_cost"] is not None
        assert "w_mm" in (result.get("best_params") or {})


# ─── openems 分支挂点（optimizer._create_adapter） ───────────────────────────


class TestOpenemsBranchSelection:
    def test_branch_returns_shim_with_plugin_template(self, mline_recipe):
        from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter

        adapter, version = _create_adapter("openems", None, mline_recipe)
        assert version == "openems"
        assert isinstance(adapter, OpenEMSOptAdapter)
        assert adapter.template == "mline"  # 插件 openems_template ClassVar 优先
        assert adapter.health_check() is True
        assert adapter.connect({}) is True
        adapter.close()

    def test_unknown_model_fails_explicitly(self, mline_recipe):
        bad = dict(mline_recipe, model="no_such_model_family")
        assert _create_adapter("openems", None, bad) == (None, "")

    def test_explicit_template_override(self, mline_recipe):
        adapter, version = _create_adapter(
            "openems", {"template": "cpw"}, mline_recipe)
        assert version == "openems"
        assert adapter.template == "cpw"  # 显式 adapter_kwargs.template 最高优先
        adapter.close()

    def test_wilkinson_falls_back_to_substring_map(self, tmp_path):
        # wilkinson 插件未声明 openems_template → 回退子串映射（与
        # service._template_hint 同口径）
        recipe = {
            "model": "wilkinson_power_divider",
            "params": {"w_mm": {"value": 1.113, "unit": "mm"}},
            "setup": {"freq_range_ghz": [1.5, 3.5], "points": 21},
            "objectives": [
                {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            ],
        }
        adapter, version = _create_adapter("openems", None, recipe)
        assert version == "openems"
        assert adapter.template == "wilkinson"
        adapter.close()

    def test_template_mapping_matches_service_hint(self):
        from rfauto.adapters.openems_optimizer_adapter import template_for_model
        from rfauto.service.ui_service import _template_hint

        for model in ("wilkinson_power_divider", "branchline_coupler",
                      "patch_antenna", "mline", "cpw_line"):
            assert template_for_model(model) == _template_hint({"model": model})
        with pytest.raises(ValueError):
            template_for_model("no_such_family")

    def test_sweep_backend_delegates(self, mline_recipe):
        from rfauto.optimization.sweep_backend import _create_adapter as sb_create

        adapter, version = sb_create("openems", None, mline_recipe)
        assert version == "openems"
        assert adapter.template == "mline"
        adapter.close()


# ─── solve 链参数传递（stub 替身，零真机） ────────────────────────────────────


class TestOpenemsSolveStub:
    def test_solve_passes_config_geometry_and_loads_network(self, mline_recipe, stub_solver):
        substrate = {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037}
        adapter, _ = _create_adapter("openems", {
            "seed": 7, "cache": False, "mesh_resolution_mm": 0.4,
            "substrate": substrate,
        }, mline_recipe)
        adapter.set_variables({"w_mm": "1.2mm", "line_len_mm": "40.0mm"})
        report = adapter.solve("main_setup")
        assert report.success is True

        assert len(stub_solver.instances) == 1
        stub = stub_solver.instances[0]
        # EMSolverConfig.solver_type 接受 str|enum（dataclass 不强转），按值断言
        assert str(getattr(stub.config.solver_type, "value", stub.config.solver_type)) == "openems"
        assert stub.config.freq_range_ghz == (2.0, 3.0)
        assert stub.config.mesh_resolution_mm == pytest.approx(0.4)
        assert stub.config.extra_params["cache"] is False
        assert stub.config.extra_params["solve_timeout_s"] == pytest.approx(900.0)
        assert stub.geometry == {
            "template": "mline",
            "params": {"w_mm": 1.2, "line_len_mm": 40.0},
            "substrate": substrate,
        }
        # 评估产物目录在 eval_root 之下
        work = Path(stub.config.working_dir)
        assert work.parent == adapter.eval_root

        network = adapter.get_sparams()
        assert network.s.shape == (41, 2, 2)
        assert len(network.f) == 41
        adapter.close()

    def test_cache_default_follows_env(self, mline_recipe, stub_solver, monkeypatch):
        monkeypatch.setenv("RFAUTO_CACHE", "off")
        adapter, _ = _create_adapter("openems", None, mline_recipe)
        adapter.set_variables({"w_mm": "1.113mm"})
        assert adapter.solve().success is True
        assert stub_solver.instances[0].config.extra_params["cache"] is False

        monkeypatch.setenv("RFAUTO_CACHE", "readwrite")
        adapter2, _ = _create_adapter("openems", None, mline_recipe)
        adapter2.set_variables({"w_mm": "1.113mm"})
        assert adapter2.solve().success is True
        assert stub_solver.instances[1].config.extra_params["cache"] is True

    def test_no_substrate_uses_template_default(self, mline_recipe, stub_solver):
        adapter, _ = _create_adapter("openems", None, mline_recipe)
        adapter.set_variables({"w_mm": "1.113mm", "line_len_mm": "40mm"})
        assert adapter.solve().success is True
        geometry = stub_solver.instances[0].geometry
        assert "substrate" not in geometry  # 模板缺省基板口径

    def test_failure_paths_report_not_raise(self, mline_recipe, stub_solver):
        adapter, _ = _create_adapter("openems", None, mline_recipe)
        adapter.set_variables({"w_mm": "1.113mm"})

        stub_solver.connect_ok = False
        report = adapter.solve()
        assert report.success is False
        assert "openEMS exe 不可用" in report.message

        stub_solver.connect_ok = True
        stub_solver.build_ok = False
        report = adapter.solve()
        assert report.success is False
        assert "渲染" in report.message

        stub_solver.build_ok = True
        stub_solver.result = _StubResult(success=False, message="fdtd 崩了")
        report = adapter.solve()
        assert report.success is False
        assert "fdtd 崩了" in report.message

        stub_solver.result = _StubResult(success=True)
        stub_solver.raise_in_solve = RuntimeError("boom")
        report = adapter.solve()
        assert report.success is False
        assert "boom" in report.message

    def test_get_sparams_before_solve_raises(self, mline_recipe):
        adapter, _ = _create_adapter("openems", None, mline_recipe)
        with pytest.raises(RuntimeError):
            adapter.get_sparams()

    def test_expr_to_float(self):
        from rfauto.adapters.openems_optimizer_adapter import expr_to_float

        assert expr_to_float("1.113mm") == pytest.approx(1.113)
        assert expr_to_float("40.0mm") == pytest.approx(40.0)
        assert expr_to_float(2.4) == pytest.approx(2.4)
        with pytest.raises(ValueError):
            expr_to_float(True)
        with pytest.raises(ValueError):
            expr_to_float("abc")


# ─── e11 战役路径端到端（stub 化真评估链） ────────────────────────────────────


class TestOptimizerEndToEndOpenems:
    def test_run_optimization_openems_channel(self, tmp_path, mline_recipe, stub_solver):
        path = _write_recipe(tmp_path, mline_recipe)
        result = run_optimization(
            path, adapter_name="openems", max_trials=2,
            study_name="oe_channel_e2e", adapter_kwargs={"seed": 7})
        assert result["ok"] is True
        assert result["trials_completed"] == 2
        assert result["best_cost"] is not None
        assert "w_mm" in (result.get("best_params") or {})
        # 逐评估参数传递：调谐参数落在搜索界内；固定参数 line_len_mm 经
        # _prepare_env 全参写入（ParameterSystem 初始全 dirty 语义）到达渲染端
        w_vals = [g.geometry["params"]["w_mm"] for g in stub_solver.instances]
        assert all(0.5 <= w <= 2.0 for w in w_vals)
        assert all(
            g.geometry["params"]["line_len_mm"] == pytest.approx(40.0)
            for g in stub_solver.instances)
        assert len(stub_solver.instances) == 2  # 无缓存白送，逐 trial 真评估

    def test_solve_failure_is_pruned_not_fatal(self, tmp_path, mline_recipe, stub_solver):
        stub_solver.result = _StubResult(success=False, message="未收敛")
        path = _write_recipe(tmp_path, mline_recipe)
        result = run_optimization(
            path, adapter_name="openems", max_trials=2,
            study_name="oe_channel_prune")
        assert result["ok"] is True
        assert result["trials_completed"] == 0


# ─── e11 战役脚本兼容（脚本零改动获益） ──────────────────────────────────────


class TestE11CampaignScriptCompat:
    def test_script_importable_and_channel_contract_intact(self):
        root = Path(__file__).parent.parent.parent
        script = root / "scripts" / "e11_warm_start_campaign.py"
        spec = importlib.util.spec_from_file_location("e11_campaign_compat", script)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # run_campaign(adapter_name=...) 原样透传 run_optimization——src 分支
        # 就位后 --adapter openems 无需战役层 _create_adapter 补丁
        assert "adapter_name" in inspect.signature(mod.run_campaign).parameters
        assert callable(mod.judge_campaign)


# ─── A-02 resume 防覆盖：eval_index_offset 接续编号 + mesh 观测面 ────────────


class TestAdapterResumeOffset:
    def test_eval_offset_continues_numbering(self, tmp_path, stub_solver):
        """既有 eval_0001..0002 归档 → offset=2 实例首个 solve 落 eval_0003，
        既有归档不被新实例 _n 回卷覆盖（c10 GT 战役 resume 实证形态）。"""
        from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter

        evals = tmp_path / "evals"
        for i in (1, 2):
            (evals / f"eval_{i:04d}").mkdir(parents=True)
            (evals / f"eval_{i:04d}" / "keep.txt").write_text("x",
                                                              encoding="utf-8")
        adapter = OpenEMSOptAdapter((2.0, 3.0), template="mline",
                                    work_root=evals, eval_index_offset=2)
        # 未 solve 时 last_eval_dir=根目录（不把既有归档误报为"最近"）
        assert adapter.last_eval_dir == evals
        adapter.set_variables({"w_mm": "1.113mm"})
        assert adapter.solve().success is True
        work = Path(stub_solver.instances[0].config.working_dir)
        assert work == evals / "eval_0003"
        assert adapter.last_eval_dir == evals / "eval_0003"
        assert (evals / "eval_0001" / "keep.txt").exists()   # 归档零改写
        assert not (evals / "eval_0003" / "keep.txt").exists()

    def test_default_offset_is_zero_and_mesh_property_roundtrip(self, tmp_path):
        from rfauto.adapters.openems_optimizer_adapter import OpenEMSOptAdapter

        adapter = OpenEMSOptAdapter((2.0, 3.0), template="mline",
                                    work_root=tmp_path / "e")
        assert adapter.last_eval_dir == tmp_path / "e"       # 缺省行为不变
        assert adapter.mesh_resolution_mm == 0.0             # 自动档哨兵
        explicit = OpenEMSOptAdapter((2.0, 3.0), template="mline",
                                     work_root=tmp_path / "e2",
                                     mesh_resolution_mm=0.4)
        assert explicit.mesh_resolution_mm == pytest.approx(0.4)
