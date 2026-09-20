"""E2a 参数映射契约单元测试。

验收标准：
① 禁止同名即映射
② dry-run 输出最终写入值
③ 单测覆盖"调参确实影响几何/网表"
④ supports_recipe_version 向后兼容
"""

from __future__ import annotations

import pytest

from rfauto.core.param_mapping import ParameterMappingRegistry, ParamMapping


class TestParamMapping:
    """单个映射测试。"""

    def test_basic_mapping(self):
        m = ParamMapping(source="arm_len_mm", target="arm_len", unit="mm")
        assert m.apply(20.5) == 20.5

    def test_transform_mapping(self):
        m = ParamMapping(
            source="freq_ghz", target="freq_hz",
            unit="Hz", transform=lambda x: x * 1e9,
        )
        assert m.apply(2.4) == 2.4e9

    def test_same_name_raises(self):
        """① 禁止同名即映射。"""
        with pytest.raises(ValueError, match="禁止同名映射"):
            ParamMapping(source="arm_len", target="arm_len")


class TestParameterMappingRegistry:
    """注册表测试。"""

    def test_register_and_resolve(self):
        r = ParameterMappingRegistry()
        r.register(ParamMapping(source="arm_len_mm", target="arm_len"))
        result = r.resolve({"arm_len_mm": 20.5})
        assert result == {"arm_len": 20.5}

    def test_duplicate_source_raises(self):
        r = ParameterMappingRegistry()
        r.register(ParamMapping(source="arm_len_mm", target="arm_len"))
        with pytest.raises(KeyError, match="已注册"):
            r.register(ParamMapping(source="arm_len_mm", target="arm_len2"))

    def test_unknown_source_raises(self):
        r = ParameterMappingRegistry()
        with pytest.raises(KeyError, match="未注册"):
            r.resolve({"unknown": 1.0})

    def test_dry_run(self):
        """② dry-run 输出最终写入值。"""
        r = ParameterMappingRegistry()
        r.register(ParamMapping(
            source="arm_len_mm", target="arm_len", unit="mm",
            description="λ/4 臂长",
        ))
        dry = r.dry_run({"arm_len_mm": 20.5})
        assert "arm_len" in dry
        assert dry["arm_len"]["source_value"] == 20.5
        assert dry["arm_len"]["target_value"] == 20.5
        assert dry["arm_len"]["unit"] == "mm"

    def test_validate_pass(self):
        r = ParameterMappingRegistry()
        r.register(ParamMapping(
            source="arm_len_mm", target="arm_len", tolerance=0.1,
        ))
        issues = r.validate({"arm_len_mm": 20.5}, {"arm_len": 20.5})
        assert issues == []

    def test_validate_fail(self):
        r = ParameterMappingRegistry()
        r.register(ParamMapping(
            source="arm_len_mm", target="arm_len", tolerance=0.01,
        ))
        issues = r.validate({"arm_len_mm": 20.5}, {"arm_len": 20.6})
        assert len(issues) == 1
        assert "Δ" in issues[0]

    def test_sources_and_targets(self):
        r = ParameterMappingRegistry()
        r.register(ParamMapping(source="a", target="x"))
        r.register(ParamMapping(source="b", target="y"))
        assert r.sources == ["a", "b"]
        assert r.targets == ["x", "y"]
        assert r.has("a") is True
        assert r.has("c") is False

    def test_from_hfss_var_map(self):
        """向后兼容：从 hfss_var_map 创建。"""
        r = ParameterMappingRegistry.from_hfss_var_map(
            {"arm_len_mm": "arm_len", "series_w_mm": "series_w"},
            units={"arm_len_mm": "mm", "series_w_mm": "mm"},
        )
        assert r.has("arm_len_mm")
        result = r.resolve({"arm_len_mm": 20.5})
        assert result == {"arm_len": 20.5}

    def test_from_hfss_var_map_same_name_raises(self):
        """hfss_var_map 中同名映射应抛异常。"""
        with pytest.raises(ValueError, match="禁止同名映射"):
            ParameterMappingRegistry.from_hfss_var_map({"arm_len": "arm_len"})


class TestSupportsRecipeVersion:
    """④ supports_recipe_version 测试。"""

    def test_v1_always_supported(self):
        from rfauto.models.branchline_coupler.plugin import BranchlineCouplerPlugin
        assert BranchlineCouplerPlugin.supports_recipe_version(1) is True

    def test_v2_supported_if_schema_v2(self):
        """schema_version=1 的插件不支持 v2。"""
        from rfauto.models.branchline_coupler.plugin import BranchlineCouplerPlugin
        assert BranchlineCouplerPlugin.supports_recipe_version(2) is False
