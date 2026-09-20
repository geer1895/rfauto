"""Wilkinson 功分器插件——第一个模型实例。

P1 实现特性：
- 完整 Wilkinson 拓扑：T-junction + 2× λ/4 臂(70.7Ω) + 隔离电阻(100Ω)
- 所有尺寸经变量通道写入，几何用表达式引用
- 命名规范强制：使用 hfss_builder_utils 常量表
- 微带线端口：空气域 + 辐射边界（Spike A 验证）
- 端口阻抗 50Ω，wave_port 用 face_id 自动积分线
"""

from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel

from rfauto.core.interfaces import RFModelPlugin, SimulatorAdapter
from rfauto.models.registry import register
from rfauto.models.wilkinson_power_divider.schema import WilkinsonPDParams

logger = logging.getLogger(__name__)


class WilkinsonPDPlugin(RFModelPlugin):
    """Wilkinson 功分器模板插件。

    build() 根据参数在 HFSS 中创建完整的功分器几何、端口、边界和 setup。
    FakeAdapter 走解析近似（hfss=None 时跳过 HFSS 建模）。
    """

    name: ClassVar[str] = "wilkinson_power_divider"
    params_model: ClassVar[type[BaseModel]] = WilkinsonPDParams
    schema_version: ClassVar[int] = 1
    n_ports: ClassVar[int] = 3                       # input + output_1 + output_2
    fake_model_type: ClassVar[str] = "wilkinson"
    hfss_var_map: ClassVar[dict[str, str]] = {
        "arm_len_mm": "arm_len",
        "series_w_mm": "series_w",
        "shunt_w_mm": "shunt_w",
        "f0_ghz": "f0",
        "z0_ohm": "z0",
    }

    def build(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """声明式构建 Wilkinson 功分器。

        硬性约束：
        - 尺寸只经 hfss['VarName']=value 写成变量再以表达式引用
        - 对象命名用常量表（Substrate, TraceArm1, PortInput ...）
        - 端口/边界绑定只允许命名对象
        """
        if not isinstance(params, WilkinsonPDParams):
            raw = params.model_dump() if hasattr(params, "model_dump") else params.__dict__
            params = WilkinsonPDParams(**raw)

        # ─── 1. 写入设计变量（尺寸经变量通道）──────────────────────
        var_dict = {
            # 用户可调参数
            "arm_len": f"{params.arm_len_mm}mm",
            "series_w": f"{params.series_w_mm}mm",       # 70.7Ω 臂宽
            "shunt_w": f"{params.shunt_w_mm}mm",         # 50Ω 线宽
            "f0": f"{params.f0_ghz}GHz",
            "z0": f"{params.z0_ohm}ohm",
            # 固定结构参数
            "sub_h": "0.508mm",       # Rogers 4350B 厚度
            "sub_w": "30mm",          # 基板宽度 (X)
            "copper_t": "0.035mm",   # 铜厚
            "gap": "2.0mm",           # 两臂间距
            "in_len": "10mm",         # 输入线长度
            "out_len": "5mm",         # 输出线长度
            "air_margin": "5mm",      # 空气域边距 (X/Z)
            # 结构细节（避免魔法数字散落几何表达式）
            "junction_len": "2mm",    # T-junction 连接区长度
            "resistor_offset": "1mm", # 隔离电阻距臂端的缩进
            "port_clear": "0.2mm",    # 输出端口 sheet 与相邻端口的间隙
        }
        ad.set_variables(var_dict)

        # ─── 2. 尝试真实 HFSS 建模 ───────────────────────────────────────────
        try:
            hfss = ad.session.hfss
            if hfss is None:
                return  # FakeAdapter 无 hfss 属性，走解析近似

            self._build_hfss(hfss, params)
        except AttributeError:
            # FakeAdapter 或适配器不支持真实建模，静默跳过
            pass

    # ─── HFSS 几何建模 ─────────────────────────────────────────────────────────

    def _build_hfss(self, hfss, params: WilkinsonPDParams) -> None:
        """真实 HFSS 建模——完整 Wilkinson 功分器拓扑。

        坐标系（Y 正向 = 输入方向）::

            Y upward = input direction
              PortInput (y_max)
                 |
              50Ω input line (shunt_w)
                 |
              T-Junction (y=0)
              /         \\
          70.7Ω arm1   70.7Ω arm2
          series_w      series_w
          arm_len       arm_len
              \\         /
               +-R100--+   isolation resistor
               |       |
              50Ω     50Ω
              Out1   Out2 (y_min)

        所有尺寸引用设计变量，避免硬编码。
        """
        from ansys.aedt.core.generic.constants import Gravity, Plane

        from rfauto.adapters.hfss_builder_utils import (
            AIRBOX,
            GROUND,
            ISOLATION_RESISTOR,
            MATERIAL_AIR,
            MATERIAL_PEC,
            MATERIAL_SUBSTRATE,
            PORT_INPUT,
            PORT_OUTPUT_1,
            PORT_OUTPUT_2,
            RESISTOR_LUMPED,
            SUBSTRATE,
            TRACE_ARM_1,
            TRACE_ARM_2,
            TRACE_INPUT,
            TRACE_JUNCTION,
            TRACE_OUTPUT_1,
            TRACE_OUTPUT_2,
            Quantity,
        )

        modeler = hfss.modeler
        # B7 迁移：字面零值经 Quantity 显式单位构造（输出仍为 0mm，行为等价）
        zero_mm = Quantity.mm(0.0).to_hfss()

        # ─── 几何参数表达式（全部引用变量）──────────────────────────────────
        # Y 方向：基板/接地面/空气域都终止于端口平面（波端口必须位于求解域边界），
        # 输入端口 y=in_len，输出端口 y=-arm_len-out_len
        sub_x0 = "(-sub_w/2)"
        sub_y0 = "(-arm_len-out_len)"
        sub_l = "(arm_len+out_len+in_len)"
        sub_z0 = zero_mm

        # ─── 1. 基板 ──────────────────────────────────────────────────────────
        modeler.create_box(
            origin=[sub_x0, sub_y0, sub_z0],
            sizes=["sub_w", sub_l, "sub_h"],
            name=SUBSTRATE,
            material=MATERIAL_SUBSTRATE,
        )
        logger.debug("创建基板: %s", SUBSTRATE)

        # ─── 2. 接地面（基板底面 PEC，零厚度 box，官方推荐模式）────────────────
        # 参考 pyaedt_reference/examples_hfss.py：用 create_box 带 0mm 厚度
        modeler.create_box(
            origin=[sub_x0, sub_y0, sub_z0],
            sizes=["sub_w", sub_l, zero_mm],
            name=GROUND,
            material=MATERIAL_PEC,
        )
        logger.debug("创建接地面: %s", GROUND)

        # ─── 3. 微带线（3D box，厚度=copper_t）────────────────────────────────
        # 输入 50Ω 线：从 junction(y=0) 向 Y 正向延伸 in_len
        modeler.create_box(
            origin=["(-shunt_w/2)", zero_mm, "sub_h"],
            sizes=["shunt_w", "in_len", "copper_t"],
            name=TRACE_INPUT,
            material=MATERIAL_PEC,
        )

        # 70.7Ω 臂 1（右侧）：从 junction 向 Y 负向延伸 arm_len
        modeler.create_box(
            origin=["(gap/2-series_w/2)", "(-arm_len)", "sub_h"],
            sizes=["series_w", "arm_len", "copper_t"],
            name=TRACE_ARM_1,
            material=MATERIAL_PEC,
        )

        # 70.7Ω 臂 2（左侧）
        modeler.create_box(
            origin=["(-gap/2-series_w/2)", "(-arm_len)", "sub_h"],
            sizes=["series_w", "arm_len", "copper_t"],
            name=TRACE_ARM_2,
            material=MATERIAL_PEC,
        )

        # 输出 50Ω 线 1（右侧）：从臂端向 Y 负向延伸 out_len
        modeler.create_box(
            origin=["(gap/2-shunt_w/2)", "(-arm_len-out_len)", "sub_h"],
            sizes=["shunt_w", "out_len", "copper_t"],
            name=TRACE_OUTPUT_1,
            material=MATERIAL_PEC,
        )

        # 输出 50Ω 线 2（左侧）
        modeler.create_box(
            origin=["(-gap/2-shunt_w/2)", "(-arm_len-out_len)", "sub_h"],
            sizes=["shunt_w", "out_len", "copper_t"],
            name=TRACE_OUTPUT_2,
            material=MATERIAL_PEC,
        )

        # T-junction 连接区：连接输入线底端与两臂顶端
        junction_w = "(gap+series_w)"
        junction_x0 = "(-gap/2-series_w/2)"
        modeler.create_box(
            origin=[junction_x0, "(-junction_len)", "sub_h"],
            sizes=[junction_w, "junction_len", "copper_t"],
            name=TRACE_JUNCTION,
            material=MATERIAL_PEC,
        )
        # 合并所有 PEC trace 为单一对象，消除重叠导致的 Design Validation 失败
        hfss.modeler.unite([
            TRACE_INPUT, TRACE_ARM_1, TRACE_ARM_2,
            TRACE_OUTPUT_1, TRACE_OUTPUT_2, TRACE_JUNCTION,
        ], keep_originals=False)
        logger.debug("合并微带线: 6 个 trace → 1 个对象")

        # ─── 4. 隔离电阻（lumped RLC, 100Ω）──────────────────────────────────
        # 垂直 sheet（XZ 面）连接两臂内侧壁：距臂端缩进 resistor_offset，
        # x 从左臂内缘到右臂内缘，z 覆盖铜厚。边缘与两臂内壁面重合 → 电气连接。
        modeler.create_rectangle(
            orientation=Plane.ZX,
            origin=["(-gap/2+series_w/2)", "(-arm_len+resistor_offset)", "sub_h"],
            sizes=["copper_t", "(gap-series_w)"],
            name=ISOLATION_RESISTOR,
        )

        # 赋 lumped RLC 边界：R=100Ω, 无 L 无 C
        hfss.assign_lumped_rlc_to_sheet(
            assignment=ISOLATION_RESISTOR,
            start_direction=Gravity.XPos,
            name=RESISTOR_LUMPED,
            rlc_type="Parallel",
            resistance=100.0,
        )
        logger.debug("创建隔离电阻: %s (R=100Ω)", ISOLATION_RESISTOR)

        # ─── 5. 空气域 + 辐射边界（微带线端口必须，Spike A 验证）───────────────
        # 空气域从 z=0 起覆盖整个结构；Y 方向终止于端口平面（波端口必须在求解域
        # 外边界上，否则报 "Waveport internal to solution domain"），X/Z 方向留边距
        air_x0 = "(-sub_w/2-air_margin)"
        air_y0 = "(-arm_len-out_len)"
        air_z0 = zero_mm  # 从 z=0 开始（与接地面同层）
        air_w = "(sub_w+2*air_margin)"
        air_l = sub_l
        air_h = "(sub_h+copper_t+air_margin)"

        modeler.create_box(
            origin=[air_x0, air_y0, air_z0],
            sizes=[air_w, air_l, air_h],
            name=AIRBOX,
            material=MATERIAL_AIR,
        )
        # 消除空气域与基板/微带线的体积重叠（HFSS 不容忍同体积不同材料）
        modeler.subtract(AIRBOX, [SUBSTRATE, TRACE_INPUT])
        logger.debug("创建空气域: %s (已扣除基板与微带线)", AIRBOX)

        # 辐射边界只赋在空气域顶面（Z 最大面），不是整个空气域
        air_faces = modeler.get_object_faces(AIRBOX)
        top_face = max(air_faces, key=lambda f: modeler.get_face_center(f)[2])
        hfss.assign_radiation_boundary_to_faces(
            assignment=[top_face],
            name="RadiationBoundary",
        )
        logger.debug("创建空气域 + 辐射边界: %s", AIRBOX)

        # ─── 6. 波端口（50Ω，显式端口 sheet，教科书式微带波端口）──────────────
        # 每个端口：XZ 面垂直矩形（法向 = Y），从接地面 z=0 延伸到基板上空
        # 3*sub_h，宽度数倍线宽；sheet 穿过基板（标准做法）。
        # 积分线沿 Z 正向（从地到信号线）。
        # 注意：合并后所有 trace 变为单一对象（名为 TRACE_INPUT）。
        def _make_port_sheet(name, y_expr, center_x_expr, width_expr):
            """创建 XZ 面端口 sheet（法向 Y），返回 face id。"""
            modeler.create_rectangle(
                orientation=Plane.ZX,
                origin=[f"({center_x_expr}-{width_expr}/2)", y_expr, zero_mm],
                sizes=["(sub_h+copper_t+3*sub_h)", width_expr],
                name=name,
            )
            faces = modeler.get_object_faces(name)
            return faces[0]

        # 输入端口：y = in_len（输入线末端），宽度 5 倍线宽
        input_face = _make_port_sheet(
            "PortSheetInput", "in_len", zero_mm, "(5*shunt_w)",
        )
        hfss.wave_port(
            assignment=input_face,
            name=PORT_INPUT,
            impedance=50.0,
            renormalize=True,
            integration_line=Gravity.ZPos,
        )

        # 输出端口：y = -arm_len-out_len（输出线末端）
        # 两输出线中心 x=±gap/2，间距 gap；端口宽度必须留 port_clear 间隙以免两 sheet 重叠
        out1_face = _make_port_sheet(
            "PortSheetOutput1", "(-arm_len-out_len)", "(gap/2)", "(gap-port_clear)",
        )
        out2_face = _make_port_sheet(
            "PortSheetOutput2", "(-arm_len-out_len)", "(-gap/2)", "(gap-port_clear)",
        )
        hfss.wave_port(
            assignment=out1_face,
            name=PORT_OUTPUT_1,
            impedance=50.0,
            renormalize=True,
            integration_line=Gravity.ZPos,
        )
        hfss.wave_port(
            assignment=out2_face,
            name=PORT_OUTPUT_2,
            impedance=50.0,
            renormalize=True,
            integration_line=Gravity.ZPos,
        )
        logger.debug("创建波端口: %s, %s, %s (50Ω)",
                      PORT_INPUT, PORT_OUTPUT_1, PORT_OUTPUT_2)

    def evaluate_extras(self, metrics: dict[str, float]) -> dict[str, float]:
        """Wilkinson 专属指标：隔离度。"""
        return metrics


# 自动注册
register(WilkinsonPDPlugin)
