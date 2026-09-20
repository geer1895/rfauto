"""命名规范 + Wilkinson HFSS 建模单元测试。

验证项：
- validate_object_name 正确拦截自动命名（军规 2b）
- Wilkinson 插件变量写入正确
- Wilkinson HFSS build 使用正确 API 参数名 + 命名常量
- 材料名与 materials.yaml 对齐
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from rfauto.adapters.hfss_builder_utils import (
    ISOLATION_RESISTOR,
    MATERIAL_AIR,
    MATERIAL_CONDUCTOR,
    MATERIAL_PEC,
    MATERIAL_SUBSTRATE,
    PORT_INPUT,
    PORT_OUTPUT_1,
    PORT_OUTPUT_2,
    RESISTOR_LUMPED,
    TRACE_ARM_1,
    TRACE_ARM_2,
    TRACE_INPUT,
    TRACE_JUNCTION,
    TRACE_OUTPUT_1,
    TRACE_OUTPUT_2,
    validate_object_name,
)
from rfauto.core.errors import ModelBuildError
from rfauto.models.wilkinson_power_divider.plugin import WilkinsonPDPlugin
from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams


class TestValidateObjectName:
    """命名规范验证（军规 2b）。"""

    @pytest.mark.parametrize("good_name", [
        "Substrate", "GroundPlane", "PatchMain", "TraceInput",
        "TraceArm1", "PortInput", "AirBox", "IsolationResistor",
    ])
    def test_valid_names_pass(self, good_name):
        """语义化名称不应抛异常。"""
        validate_object_name(good_name)

    @pytest.mark.parametrize("bad_name", [
        "Box1", "Box2", "Cylinder1", "Rectangle1", "Circle1",
        "Polyline1", "Face1", "FaceID 123", "Object1", "Port1",
        "Vacuum1", "PEC1", "unnamed_thing",
    ])
    def test_auto_generated_names_rejected(self, bad_name):
        """自动生成名称应抛 ModelBuildError。"""
        with pytest.raises(ModelBuildError, match="命名规范"):
            validate_object_name(bad_name)

    def test_empty_name_rejected(self):
        """空名称应抛异常。"""
        with pytest.raises(ModelBuildError):
            validate_object_name("")

    def test_whitespace_name_rejected(self):
        """纯空白名称应抛异常。"""
        with pytest.raises(ModelBuildError):
            validate_object_name("   ")


class TestNamingConstants:
    """命名常量表完整性检查。"""

    def test_material_names_match_materials_yaml(self):
        """材料常量与 configs/materials.yaml 对齐。"""
        assert MATERIAL_SUBSTRATE == "Rogers RO4350 (tm)"
        assert MATERIAL_AIR == "vacuum"
        assert MATERIAL_CONDUCTOR == "copper"
        assert MATERIAL_PEC == "pec"

    def test_trace_constants_defined(self):
        """Wilkinson 微带线常量已定义。"""
        assert TRACE_INPUT == "TraceInput"
        assert TRACE_ARM_1 == "TraceArm1"
        assert TRACE_ARM_2 == "TraceArm2"
        assert TRACE_OUTPUT_1 == "TraceOutput1"
        assert TRACE_OUTPUT_2 == "TraceOutput2"
        assert TRACE_JUNCTION == "TraceJunction"

    def test_port_constants_defined(self):
        """端口常量已定义。"""
        assert PORT_INPUT == "PortInput"
        assert PORT_OUTPUT_1 == "PortOutput1"
        assert PORT_OUTPUT_2 == "PortOutput2"

    def test_resistor_constants_defined(self):
        """隔离电阻常量已定义。"""
        assert ISOLATION_RESISTOR == "IsolationResistor"
        assert RESISTOR_LUMPED == "ResistorLumped"


class TestWilkinsonBuildVariables:
    """验证 Wilkinson 插件写入的设计变量。"""

    def test_build_writes_all_variables(self):
        """build() 应写入所有必需的设计变量。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        mock_ad = MagicMock()
        mock_ad.session.hfss = None  # FakeAdapter 路径

        plugin.build(mock_ad, params)

        # 验证 set_variables 被调用
        mock_ad.set_variables.assert_called_once()
        var_dict = mock_ad.set_variables.call_args[0][0]

        # 用户可调参数
        assert "arm_len" in var_dict
        assert "series_w" in var_dict
        assert "shunt_w" in var_dict
        assert "f0" in var_dict
        assert "z0" in var_dict

        # 固定结构参数
        assert "sub_h" in var_dict
        assert "sub_w" in var_dict
        # sub_l 已移除：基板 Y 长度由 (arm_len+out_len+in_len) 派生（未使用的 50mm 设计变量会在每次导出的 Variables 块中造成误导）
        assert "sub_l" not in var_dict
        assert "copper_t" in var_dict
        assert "gap" in var_dict
        assert "in_len" in var_dict
        assert "out_len" in var_dict
        assert "air_margin" in var_dict
        # 结构细节变量（魔法数字收编进变量通道）
        assert "junction_len" in var_dict
        assert "resistor_offset" in var_dict
        assert "port_clear" in var_dict

    def test_build_variable_values_correct_units(self):
        """变量值应带正确单位。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams(
            arm_len_mm=22.0, series_w_mm=0.35, shunt_w_mm=1.2,
            f0_ghz=2.45, z0_ohm=50.0,
        )
        mock_ad = MagicMock()
        mock_ad.session.hfss = None

        plugin.build(mock_ad, params)
        var_dict = mock_ad.set_variables.call_args[0][0]

        assert var_dict["arm_len"] == "22.0mm"
        assert var_dict["series_w"] == "0.35mm"
        assert var_dict["shunt_w"] == "1.2mm"
        assert var_dict["f0"] == "2.45GHz"
        assert var_dict["z0"] == "50.0ohm"
        assert var_dict["sub_h"] == "0.508mm"


class TestWilkinsonHfssBuildMock:
    """用 Mock 验证 HFSS build 的 API 调用正确性。

    验证 pyaedt 1.4.0 API 参数名 + 命名常量 + 几何表达式。
    """

    def _build_mock_hfss(self):
        """创建 Mock HFSS 对象，记录所有 API 调用。"""
        hfss = MagicMock()
        modeler = MagicMock()
        hfss.modeler = modeler

        # 记录创建的对象
        created_boxes: list[dict] = []
        created_rects: list[dict] = []

        def mock_create_box(origin, sizes, name=None, material=None, **kw):
            created_boxes.append({"origin": origin, "sizes": sizes, "name": name, "material": material})
            obj = MagicMock()
            obj.name = name
            obj.material = material
            return obj

        def mock_create_rectangle(orientation, origin, sizes, name=None, material=None, **kw):
            created_rects.append({"orientation": orientation, "origin": origin, "sizes": sizes, "name": name, "material": material})
            obj = MagicMock()
            obj.name = name
            obj.material = material
            return obj

        def mock_get_object_faces(name):
            return [100, 200, 300, 400, 500, 600]

        def mock_get_face_center(face_id):
            return {
                100: [0, 10, 0.543],   # Y max face (input port)
                200: [0, 0, 0.543],
                300: [1, -25, 0.543],  # Y min face (output1 port)
                400: [-1, -25, 0.543],
                500: [1, -30, 0.543],
                600: [-1, -30, 0.543],
            }[face_id]

        modeler.create_box.side_effect = mock_create_box
        modeler.create_rectangle.side_effect = mock_create_rectangle
        modeler.get_object_faces.side_effect = mock_get_object_faces
        modeler.get_face_center.side_effect = mock_get_face_center

        # 存储调用记录用于断言
        hfss._created_boxes = created_boxes
        hfss._created_rects = created_rects
        return hfss

    def test_build_uses_correct_api_parameter_names(self):
        """create_box 用 origin/sizes，create_rectangle 用 orientation/origin/sizes。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        # 检查 create_box 调用使用了 origin= 和 sizes=
        assert len(hfss._created_boxes) > 0
        for box in hfss._created_boxes:
            assert "origin" in box
            assert "sizes" in box
            assert box["name"] is not None

    def test_build_uses_naming_constants(self):
        """所有几何对象使用命名常量，不出现默认名。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        all_names = [b["name"] for b in hfss._created_boxes]
        all_names += [r["name"] for r in hfss._created_rects]

        # 至少创建 8 个对象：基板 + 接地面 + 6 traces + 空气域
        assert len(all_names) >= 8

        # 所有名称都应通过命名规范校验
        for name in all_names:
            validate_object_name(name)

    def test_build_uses_variable_expressions_not_hardcoded(self):
        """几何尺寸引用变量表达式，不是硬编码数值。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        # 检查所有 create_box/create_rectangle 的尺寸表达式
        all_sizes = []
        for b in hfss._created_boxes:
            all_sizes.extend(b["sizes"])
        for r in hfss._created_rects:
            all_sizes.extend(r["sizes"])

        # 关键变量应出现在尺寸表达式中
        all_sizes_str = " ".join(all_sizes)

        # arm_len 应被引用
        assert "arm_len" in all_sizes_str
        # series_w 应被引用
        assert "series_w" in all_sizes_str
        # shunt_w 应被引用
        assert "shunt_w" in all_sizes_str
        # sub_h 应被引用
        assert "sub_h" in all_sizes_str

    def test_build_creates_isolation_resistor(self):
        """隔离电阻通过 assign_lumped_rlc_to_sheet 创建。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        # 验证 assign_lumped_rlc_to_sheet 被调用
        hfss.assign_lumped_rlc_to_sheet.assert_called_once()
        call_kwargs = hfss.assign_lumped_rlc_to_sheet.call_args

        # 验证参数
        assert call_kwargs.kwargs.get("resistance") == 100.0
        assert call_kwargs.kwargs.get("rlc_type") == "Parallel"
        assert call_kwargs.kwargs.get("name") == RESISTOR_LUMPED

    def test_build_assigns_radiation_to_top_face_only(self):
        """辐射边界赋在空气域顶面，不是整个空气域。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        # assign_radiation_boundary_to_faces 被调用（不是 to_objects）
        hfss.assign_radiation_boundary_to_faces.assert_called_once()
        assert not hfss.assign_radiation_boundary_to_objects.called

    def test_build_wave_ports_use_50ohm(self):
        """波端口阻抗 50Ω。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        # 3 个波端口
        assert hfss.wave_port.call_count == 3

        for call in hfss.wave_port.call_args_list:
            assert call.kwargs.get("impedance") == 50.0
            assert call.kwargs.get("renormalize") is True

    def test_build_port_names_use_constants(self):
        """端口名称使用命名常量。"""
        plugin = WilkinsonPDPlugin()
        params = WilkinsonPDParams()
        hfss = self._build_mock_hfss()

        plugin._build_hfss(hfss, params)

        port_names = [
            call.kwargs.get("name")
            for call in hfss.wave_port.call_args_list
        ]
        assert PORT_INPUT in port_names
        assert PORT_OUTPUT_1 in port_names
        assert PORT_OUTPUT_2 in port_names
