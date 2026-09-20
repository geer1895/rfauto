"""api.py re-export 完整性测试（B-34 / #112 / #116 治理钉子）。

api.py 是 CLI/MCP 的统一服务入口：v3_services / r3_services /
dataset_service / dataset_insights / warm_start_data 的公开服务函数必须
全部 re-export，且 api 上的名字与源模块是**同一对象**——若 api 尾部再出现
同名 def 遮蔽 re-export（#116 幽灵 bug：修源模块不生效），身份断言立即失败。

排除与过滤规则：
- 契约性排除 get_chat_settings_raw（返回含 api_key 明文，自述"不对外"），
  并钉住它不进 api 公开面；
- 按 ``__module__`` 归属过滤源模块 import 进来的名字（Path/Any 等），
  只检查定义于源模块的函数/类；
- 不依赖 dataset extra：api 链上没有任何模块级 duckdb/pyarrow/h5py import
  （dataset_service/dataset_insights 依赖全部惰性），本文件无 importorskip。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import rfauto.service.api as api
import rfauto.service.dataset_insights as dataset_insights
import rfauto.service.dataset_service as dataset_service
import rfauto.service.r3_services as r3_services
import rfauto.service.v3_services as v3_services
import rfauto.service.warm_start_data as warm_start_data

# 契约性排除：不进入 api 公开面的源模块公开名
_EXCLUDED = {"get_chat_settings_raw"}

_SOURCE_MODULES = [
    v3_services, r3_services, dataset_service, dataset_insights, warm_start_data,
]


def _public_defs(module) -> dict[str, object]:
    """源模块内自定义的公开函数/类（__module__ 过滤掉 import 进来的名字）。"""
    out: dict[str, object] = {}
    for name, obj in inspect.getmembers(
            module, lambda o: inspect.isfunction(o) or inspect.isclass(o)):
        if name.startswith("_"):
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        out[name] = obj
    return out


class TestApiReexportCompleteness:
    def test_every_public_service_function_reexported_same_object(self):
        """四源模块公开服务函数全部在 api 且身份一致（缺 re-export 与
        尾部同名 def 遮蔽两种 #116 形态都会失败）。"""
        missing: list[str] = []
        shadowed: list[str] = []
        checked = 0
        for mod in _SOURCE_MODULES:
            for name, obj in _public_defs(mod).items():
                if name in _EXCLUDED:
                    continue
                checked += 1
                if not hasattr(api, name):
                    missing.append(f"{mod.__name__}.{name}")
                elif getattr(api, name) is not obj:
                    shadowed.append(f"api.{name} 不是 {mod.__name__}.{name} 本体")
        assert not missing, f"api 缺 re-export: {missing}"
        assert not shadowed, f"api 尾部同名 def 遮蔽 re-export（#116）: {shadowed}"
        # 面覆盖自检：防 introspection 静默失效空转（当前 32 个公开名：
        # 24 + dataset_insights 8）
        assert checked >= 30, f"实际只检查了 {checked} 个名字，过滤规则疑似失效"

    def test_known_entries_present(self):
        """抽样钉死关键入口（读得直观，不依赖 introspection 规则）。"""
        for name in (
            # v3_services（9）
            "compare_runs_provenance", "run_p0_experiment", "study_inject",
            "structured_sweep", "run_multifidelity_tune", "run_sensitivity",
            "agent_quality_summary", "generate_enhanced_report",
            "hfss_import_recipe",
            # r3_services（11：10 函数 + AgentChat 类）
            "list_solver_visualizations", "list_registered_solvers",
            "add_solver_to_config", "remove_solver_from_config",
            "list_pending_approvals", "approve_proposal",
            "get_chat_settings", "save_chat_settings",
            "fs_list", "list_recipes", "AgentChat",
            # dataset_service（2）
            "materialize_dataset", "query_dataset",
            # dataset_insights（8：WP2.4 六接口 + E1 收口公开集注册/双集装载）
            "dataset_coverage", "annotate_ground_truth",
            "neural_operator_readiness", "set_dataset_visibility",
            "export_hf_dataset", "list_datasets",
            "register_public_dataset", "load_dataset_sets",
            # warm_start_data（2）
            "collect_warm_start_samples",
            "run_optimization_warm_start_from_dataset",
        ):
            assert hasattr(api, name), f"api 缺 {name}"
            assert callable(getattr(api, name)), f"api.{name} 不可调用"

    def test_dataset_insights_reexports_are_identity(self):
        """dataset_insights 八接口 re-export 身份钉子（E1 收口验收项）：
        api.<name> is dataset_insights.<name>，尾部同名 def 遮蔽即红。"""
        for name in (
            "dataset_coverage", "annotate_ground_truth",
            "neural_operator_readiness", "set_dataset_visibility",
            "export_hf_dataset", "list_datasets",
            "register_public_dataset", "load_dataset_sets",
        ):
            assert getattr(api, name) is getattr(dataset_insights, name), (
                f"api.{name} 不是 dataset_insights.{name} 本体（#116）")

    def test_secret_reader_excluded_from_api_surface(self):
        """get_chat_settings_raw 返回 api_key 明文，契约'不对外'——
        不得被'补齐 re-export'误加进 api 公开面。"""
        assert not hasattr(api, "get_chat_settings_raw")

    def test_no_tail_shadowing_defs_in_source_modules(self):
        """B-34 验收 grep 口径：源模块与 api 内不得有同名顶层 def/class
        重复定义（文件内二次定义=前者死代码，正是 #116 的土壤）。"""
        import re

        for path in (
            Path(api.__file__), Path(v3_services.__file__),
            Path(r3_services.__file__), Path(dataset_service.__file__),
            Path(dataset_insights.__file__), Path(warm_start_data.__file__),
        ):
            names: list[str] = re.findall(
                r"^(?:def|class) ([A-Za-z_]\w*)",
                path.read_text(encoding="utf-8"), flags=re.MULTILINE)
            dup = sorted({n for n in names if names.count(n) > 1})
            assert not dup, f"{path.name} 存在同名重复定义: {dup}"
