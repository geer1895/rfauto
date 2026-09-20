"""调谐闭环修复回归——hfss_var_map 必须作用于设计变量写入。

2026-08-30 branchline 真机 8-trial 发现：插件设计变量名不带单位后缀
（arm_len），优化器按配方参数名（arm_len_mm）写入的是无人引用的新变量，
8 trial cost 恒定（几何纹丝不动）。本文件锁死映射行为。
"""

from __future__ import annotations

from rfauto.adapters.fake_adapter import FakeAdapter
from rfauto.core.parameters import ParameterSystem, ParamValue
from rfauto.models.branchline_coupler.plugin import BranchlineCouplerPlugin
from rfauto.models.patch_antenna.plugin import PatchAntennaPlugin
from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin


class TestHfssVarMap:
    def test_plugins_declare_maps(self):
        assert WilkinsonPDPlugin.hfss_var_map["arm_len_mm"] == "arm_len"
        assert BranchlineCouplerPlugin.hfss_var_map["arm_len_mm"] == "arm_len"
        assert PatchAntennaPlugin.hfss_var_map["patch_len_mm"] == "patch_len"
        assert PatchAntennaPlugin.hfss_var_map["feed_offset_mm"] == "feed_offset"

    def test_write_to_adapter_applies_map(self):
        ps = ParameterSystem({
            "arm_len_mm": ParamValue(name="arm_len_mm", value=21.0, unit="mm"),
        })
        ad = FakeAdapter()
        ad.connect({})
        ps.write_to_adapter(ad, name_map={"arm_len_mm": "arm_len"})
        assert ad._variables["arm_len"] == "21.0mm"
        assert "arm_len_mm" not in ad._variables, "不得再写入无人引用的原名变量"

    def test_identity_map_default(self):
        ps = ParameterSystem({
            "w": ParamValue(name="w", value=2.0, unit="mm"),
        })
        ad = FakeAdapter()
        ad.connect({})
        ps.write_to_adapter(ad)
        assert ad._variables["w"] == "2.0mm"

    def test_optimized_update_lands_on_geometry_var(self):
        """模拟优化器 trial：update → 映射写入 → 变量在适配器侧生效。"""
        ps = ParameterSystem({
            "arm_len_mm": ParamValue(name="arm_len_mm", value=20.5, unit="mm",
                                     bounds=(18.0, 23.0)),
        })
        ad = FakeAdapter()
        ad.connect({})
        var_map = BranchlineCouplerPlugin.hfss_var_map
        ps.update({"arm_len_mm": 19.0})
        ps.write_to_adapter(ad, name_map=var_map, only_dirty=True)
        assert ad._variables["arm_len"] == "19.0mm"
