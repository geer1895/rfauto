"""AU-6 optimizer 通道注册表钉——收拢后行为零变化 + 惰性导入面。

钉面（对应 runs/au3_audit/au6_design.md）：
- 注册表内容：内置三通道 fake/hfss/openems 注册在位；
- 未知通道：``(None, "")`` fallthrough 逐位（原 optimizer._create_adapter
  尾部落点）；
- 通道解析零行为：factory 直调 vs optimizer._create_adapter 分发对同一
  输入逐键相等（类型/版本/模板/健康检查）；
- 惰性导入面：import optimizer + adapter_channels（注册发生）后
  sys.modules 无 rfauto.adapters.*；选中 fake 通道后 fake_adapter 在位；
- 注册语义：register_channel 幂等覆盖（后注册者胜）；
- 公共预处理语义：分支前 setup_cfg 提取保留（recipe_data 非 dict 时
  AttributeError，与改前一致）；
- monkeypatch 兼容：optimizer._create_adapter 仍是模块级函数（消费面
  test_review_fixes monkeypatch 入口不变）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.optimization import adapter_channels
from rfauto.optimization.adapter_channels import (
    channel_names,
    create_via_channel,
    register_channel,
)
from rfauto.optimization.optimizer import _create_adapter


@pytest.fixture
def mline_recipe() -> dict[str, Any]:
    """与 test_openems_optimizer_channel 同款最小配方（fake/openems 通道）。"""
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


class _StubSolver:
    """零真机替身（openEMS 通道求解子进程不做真跑）。"""

    def solve(self, *a: Any, **k: Any):  # pragma: no cover - 不应被调
        raise AssertionError("stub solver must not run in registry pins")


@pytest.fixture
def stub_openems(monkeypatch):
    """openEMS 求解子进程替身（与 test_openems_optimizer_channel 同口径）。"""
    import rfauto.adapters.openems_solver as solver_mod

    monkeypatch.setattr(solver_mod, "OpenEMSSolver", _StubSolver)


class TestRegistryContent:
    def test_builtin_three_channels_registered(self):
        assert channel_names() == ("fake", "hfss", "openems")

    def test_dispatcher_still_module_level_function(self):
        # monkeypatch 兼容：test_review_fixes 等消费面按模块属性替换
        import rfauto.optimization.optimizer as opt_mod

        assert callable(opt_mod._create_adapter)


class TestUnknownChannelFallback:
    @pytest.mark.parametrize("name", ["nope", "", "FAKE", None])
    def test_unknown_channel_returns_none_tuple(self, name):
        assert create_via_channel(
            name, setup_cfg={}, freq_range=[1.5, 3.5], freq_points=201,
            adapter_kwargs=None, recipe_data={}) == (None, "")

    @pytest.mark.parametrize("name", ["nope", "", "FAKE"])
    def test_dispatcher_fallthrough_bitwise(self, name, mline_recipe):
        # 原 optimizer._create_adapter 尾部落点：未知名 → (None, "")
        assert _create_adapter(name, None, mline_recipe) == (None, "")


class TestZeroBehaviorPins:
    def test_fake_channel_dispatcher_vs_factory_identical(self, mline_recipe):
        from rfauto.adapters.fake_adapter import FakeAdapter

        via_dispatcher = _create_adapter("fake", None, mline_recipe)
        via_factory = create_via_channel(
            "fake", setup_cfg=mline_recipe.get("setup", {}),
            freq_range=[2.0, 3.0], freq_points=41,
            adapter_kwargs=None, recipe_data=mline_recipe)
        try:
            assert via_dispatcher[1] == via_factory[1] == "fake"
            assert type(via_dispatcher[0]) is type(via_factory[0])
            assert isinstance(via_dispatcher[0], FakeAdapter)
            # C4 插件元数据推导：n_ports/model_type（收拢前后同 derivation）
            assert via_dispatcher[0].n_ports == 2
            assert via_dispatcher[0].model_type == "mline"
            assert via_dispatcher[0].freq_ghz == (2.0, 3.0, 41)
        finally:
            via_dispatcher[0].close()
            via_factory[0].close()

    def test_fake_channel_explicit_kwargs_override(self, mline_recipe):
        adapter, version = _create_adapter(
            "fake", {"n_ports": 3, "model_type": "wilkinson"}, mline_recipe)
        try:
            assert version == "fake"
            assert adapter.n_ports == 3
            assert adapter.model_type == "wilkinson"
        finally:
            adapter.close()

    def test_openems_channel_tuple_unchanged(self, mline_recipe, stub_openems):
        adapter, version = _create_adapter("openems", None, mline_recipe)
        try:
            assert version == "openems"
            assert adapter.template == "mline"
        finally:
            adapter.close()

    def test_openems_unknown_model_none_tuple(self, mline_recipe):
        bad = dict(mline_recipe, model="no_such_model_family")
        assert _create_adapter("openems", None, bad) == (None, "")

    def test_setup_extraction_before_dispatch_preserved(self):
        # 改前：setup_cfg 提取在分支选择之前 → recipe_data 非 dict 时
        # AttributeError（含 hfss 通道）。收拢后同语义（公共预处理保留）。
        with pytest.raises(AttributeError):
            _create_adapter("hfss", None, None)  # type: ignore[arg-type]


class TestLazyImportSurface:
    def test_no_adapter_modules_on_import(self):
        """import optimizer + 注册发生（adapter_channels）后无 adapters.*。"""
        code = (
            "import sys\n"
            "import rfauto.optimization.optimizer\n"
            "import rfauto.optimization.adapter_channels as ac\n"
            "names = ac.channel_names()\n"
            "assert names == ('fake', 'hfss', 'openems'), names\n"
            "bad = [m for m in sys.modules if m.startswith('rfauto.adapters')]\n"
            "assert not bad, bad\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, cwd=str(src_dir.parent))
        assert proc.returncode == 0, proc.stderr

    def test_fake_channel_imports_on_selection(self):
        """选中 fake 通道后 fake_adapter 模块在 sys.modules（惰性而非禁止）。"""
        code = (
            "import sys\n"
            "from rfauto.optimization.adapter_channels import create_via_channel\n"
            "adapter, version = create_via_channel(\n"
            "    'fake', setup_cfg={}, freq_range=[1.5, 3.5], freq_points=21,\n"
            "    adapter_kwargs={'n_ports': 3, 'model_type': 'wilkinson'},\n"
            "    recipe_data={})\n"
            "assert version == 'fake'\n"
            "assert 'rfauto.adapters.fake_adapter' in sys.modules\n"
            "adapter.close()\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, cwd=str(src_dir.parent))
        assert proc.returncode == 0, proc.stderr


class TestRegistrationSemantics:
    def test_register_channel_overrides_and_restores(self, mline_recipe):
        original = adapter_channels._CHANNEL_FACTORIES["fake"]
        seen: dict[str, Any] = {}

        def stub_factory(**kwargs: Any) -> tuple[Any | None, str]:
            seen.update(kwargs)
            return "stub-adapter", "stub-version"

        try:
            register_channel("fake", stub_factory)
            # 后注册者胜（幂等覆盖，同 EMSolverRegistry.register 语义）
            got = _create_adapter("fake", {"k": 1}, mline_recipe)
            assert got == ("stub-adapter", "stub-version")
            # 公共预处理结果随分发透传给工厂
            assert seen["freq_range"] == [2.0, 3.0]
            assert seen["freq_points"] == 41
            assert seen["adapter_kwargs"] == {"k": 1}
            assert seen["recipe_data"] is mline_recipe
        finally:
            register_channel("fake", original)
        # 还原后既有通道行为恢复（同进程内后续测试不受污染）
        adapter, version = _create_adapter("fake", None, mline_recipe)
        try:
            assert version == "fake"
        finally:
            adapter.close()
