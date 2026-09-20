"""Wilkinson 真机 HFSS 建模测试。

验证项：
- 真实 HFSS API 调用成功（不抛异常）
- 几何对象正确创建（命名规范）
- 端口和边界正确赋值
- 项目可保存

运行命令：
    pytest tests/integration/test_wilkinson_real.py -m real_edt -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_edt


def _get_aedt_version() -> str:
    """根据 AEDT 路径推断版本号。"""
    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if "v231" in aedt_path:
        return "2023.1"
    return "2025.1"


def _skip_if_no_aedt():
    """无 AEDT 路径时跳过测试。"""
    aedt_path = os.environ.get("RFAUTO_AEDT_PATH", "")
    if not aedt_path or not Path(aedt_path).exists():
        pytest.skip(f"RFAUTO_AEDT_PATH not set or not exists: {aedt_path}")


@pytest.fixture
def real_hfss_adapter():
    """提供真实的 HfssAdapter 实例（连接 → yield → 关闭）。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.adapters.hfss_session import HfssSession

    # 重置单例
    HfssSession.reset()

    adapter = HfssAdapter()
    version = _get_aedt_version()
    adapter.connect({
        "desktop_version": version,
        "non_graphical": True,
        "new_desktop_session": True,
    })
    yield adapter
    adapter.close(save=False)


class TestWilkinsonRealBuild:
    """Wilkinson 功分器真机建模测试。"""

    def test_wilkinson_build_creates_all_objects(self, real_hfss_adapter, tmp_path):
        """完整建模：基板 + 接地面 + 6 微带线 + 隔离电阻 + 空气域 + 3 端口。"""
        _skip_if_no_aedt()

        from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin
        from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams

        # 1. 打开项目
        project_path = str(tmp_path / "wilkinson_real.aedt")
        real_hfss_adapter.open_or_create_project(project_path, "WilkinsonReal")

        # 2. 构建模型
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        plugin.build(real_hfss_adapter, params)

        # 3. 验证几何对象
        # 6 条微带线 unite 为单一 TraceInput；3 个波端口各带显式端口 sheet
        hfss = real_hfss_adapter.session.hfss
        modeler = hfss.modeler
        object_names = modeler.object_names

        expected_names = [
            "Substrate", "GroundPlane",
            "TraceInput",  # 6 条 trace 合并后的单一 PEC 对象
            "AirBox", "IsolationResistor",
            "PortSheetInput", "PortSheetOutput1", "PortSheetOutput2",
        ]

        for name in expected_names:
            assert name in object_names, f"Expected object '{name}' not found. Found: {object_names}"

        # 4. 验证变量写入（independent_variables 返回 dict，keys 为变量名）
        var_dict = hfss.variable_manager.independent_variables
        var_names = list(var_dict.keys())
        assert "arm_len" in var_names, f"arm_len not found in variables: {var_names}"
        assert "series_w" in var_names
        assert "shunt_w" in var_names
        assert "sub_h" in var_names

        # 5. 验证端口创建（hfss.ports 返回 list[str]）
        port_names = list(hfss.ports)
        assert "PortInput" in port_names, f"PortInput not found. Ports: {port_names}"
        assert "PortOutput1" in port_names
        assert "PortOutput2" in port_names

        # 6. 验证边界条件（hfss.boundaries 返回 list[BoundaryObject]）
        boundary_names = [b.name for b in hfss.boundaries]
        assert any("Resistor" in b for b in boundary_names), f"Resistor boundary not found. Boundaries: {boundary_names}"
        assert any("Radiation" in b for b in boundary_names), f"Radiation boundary not found. Boundaries: {boundary_names}"

        print(f"Object names ({len(object_names)}): {object_names}")
        print(f"Variables ({len(var_names)}): {var_names}")
        print(f"Ports ({len(port_names)}): {port_names}")
        print(f"Boundaries ({len(boundary_names)}): {boundary_names}")

    def test_wilkinson_build_three_parameter_sets(self, real_hfss_adapter, tmp_path):
        """3 组参数自动建模验证（验收标准之一）。"""
        _skip_if_no_aedt()

        from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin
        from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams

        plugin = WilkinsonPDPlugin()

        param_sets = [
            {"arm_len_mm": 20.5, "series_w_mm": 0.33, "shunt_w_mm": 1.10, "f0_ghz": 2.4, "z0_ohm": 50},
            {"arm_len_mm": 22.0, "series_w_mm": 0.30, "shunt_w_mm": 1.15, "f0_ghz": 2.45, "z0_ohm": 50},
            {"arm_len_mm": 19.0, "series_w_mm": 0.38, "shunt_w_mm": 1.05, "f0_ghz": 2.35, "z0_ohm": 50},
        ]

        for i, ps in enumerate(param_sets):
            tag = f"Set{i+1}"
            project_path = str(tmp_path / f"wilkinson_{tag}.aedt")
            real_hfss_adapter.open_or_create_project(project_path, f"Wilkinson{tag}")

            params = WilkinsonPDParams(**ps)
            plugin.build(real_hfss_adapter, params)

            # 获取当前 design 的 hfss 实例（open_or_create_project 会更新 session.hfss）
            hfss = real_hfss_adapter.session.hfss

            # 验证变量值正确写入（independent_variables 返回 dict[name] = Variable）
            var_dict = hfss.variable_manager.independent_variables
            arm_len_val = var_dict.get("arm_len")
            f0_val = var_dict.get("f0")
            assert arm_len_val is not None, f"{tag}: arm_len not found"
            assert f0_val is not None, f"{tag}: f0 not found"
            # expression 返回原始字符串如 "20.5mm"，提取数值部分比较
            import re
            arm_len_expr = str(arm_len_val.expression) if hasattr(arm_len_val, 'expression') else str(arm_len_val)
            f0_expr = str(f0_val.expression) if hasattr(f0_val, 'expression') else str(f0_val)
            arm_len_num = float(re.sub(r'[^0-9.\-]', '', arm_len_expr))
            f0_num = float(re.sub(r'[^0-9.\-]', '', f0_expr))
            assert abs(arm_len_num - ps['arm_len_mm']) < 0.1, \
                f"{tag}: arm_len not {ps['arm_len_mm']}, got {arm_len_num}"
            assert abs(f0_num - ps['f0_ghz']) < 0.01, \
                f"{tag}: f0 not {ps['f0_ghz']}, got {f0_num}"

            print(f"Parameter set {tag} passed: arm_len={ps['arm_len_mm']}, f0={ps['f0_ghz']}GHz")

    def test_wilkinson_save_project(self, real_hfss_adapter, tmp_path):
        """验证建模后可保存项目文件。"""
        _skip_if_no_aedt()

        from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin
        from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams

        project_path = str(tmp_path / "wilkinson_save.aedt")
        real_hfss_adapter.open_or_create_project(project_path, "WilkinsonSave")

        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        plugin.build(real_hfss_adapter, params)

        # 保存
        real_hfss_adapter.close(save=True)

        # 验证文件存在
        assert Path(project_path).exists(), f"Project file not created: {project_path}"
        file_size = Path(project_path).stat().st_size
        assert file_size > 1000, f"Project file too small ({file_size} bytes)"
        print(f"Project saved: {project_path} ({file_size} bytes)")
