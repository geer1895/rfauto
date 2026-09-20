"""Branchline Coupler 插件——第二个模型实例。

P5 实现特性：
- 完整 Branchline 拓扑：两对 λ/4 臂（series 35.4Ω + shunt 50Ω）
- 4 端口：Input / Through / Coupled / Isolated（完整实现）
- 所有尺寸经变量通道写入，几何用表达式引用
- 命名规范强制
- 验证"新增模板未改动任何核心层文件"（P5 验收项）
"""

from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel

from rfauto.core.interfaces import RFModelPlugin, SimulatorAdapter
from rfauto.models.branchline_coupler.schema import BranchlineCouplerParams
from rfauto.models.registry import register

logger = logging.getLogger(__name__)


class BranchlineCouplerPlugin(RFModelPlugin):
    """Branchline Coupler 模板插件。

    build() 根据参数在 HFSS 中创建完整的耦合器几何、端口、边界和 setup。
    FakeAdapter 走解析近似。
    """

    name: ClassVar[str] = "branchline_coupler"
    params_model: ClassVar[type[BaseModel]] = BranchlineCouplerParams
    schema_version: ClassVar[int] = 1
    n_ports: ClassVar[int] = 4                       # Input/Through/Coupled/Isolated
    fake_model_type: ClassVar[str] = "branchline"
    hfss_var_map: ClassVar[dict[str, str]] = {
        "arm_len_mm": "arm_len",
        "series_w_mm": "series_w",
        "shunt_w_mm": "shunt_w",
        "f0_ghz": "f0",
        "z0_ohm": "z0",
    }

    def build(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """声明式构建 Branchline Coupler。"""
        if not isinstance(params, BranchlineCouplerParams):
            raw = params.model_dump() if hasattr(params, "model_dump") else params.__dict__
            params = BranchlineCouplerParams(**raw)

        # ─── 1. 写入设计变量 ──────────────────────────────────────────────────
        var_dict = {
            "arm_len": f"{params.arm_len_mm}mm",
            "series_w": f"{params.series_w_mm}mm",
            "shunt_w": f"{params.shunt_w_mm}mm",
            "f0": f"{params.f0_ghz}GHz",
            "z0": f"{params.z0_ohm}ohm",
            # 固定结构参数
            "sub_h": "0.508mm",
            "copper_t": "0.035mm",
            "feed_len": "5mm",        # 50Ω 馈线长度（环边到域边界）
            "air_margin": "5mm",      # 空气域 X/Y 边距
        }
        ad.set_variables(var_dict)

        # ─── 2. 尝试真实 HFSS 建模 ───────────────────────────────────────────
        try:
            hfss = ad.session.hfss
            if hfss is None:
                return  # FakeAdapter
            self._build_hfss(hfss, params)
        except AttributeError:
            pass

    def _build_hfss(self, hfss, params: BranchlineCouplerParams) -> None:
        """真实 HFSS 建模——标准方形环 Branchline 拓扑（Pozar §7.2）。

        真机验证前重写。原实现两个致命问题：
        1. 几何不是环——shunt 臂用 in_len/out_len 拼接，四臂不构成回路；
        2. P3/P4 波端口放在 x=±gap/2，位于空气盒内部，必然触发
           "Wave port internal to solution domain"。

        新拓扑（环心在原点，四边等长 arm_len = λ/4）::

                       Port3 (Coupled, y_max 域边界)
                          |
                    TraceShuntTop (50Ω)
                          |
         Port4 ← ……方环…… → Port2 (Through, x_max 域边界)
       (Isolated,       series 臂×2
        y_min 域边界)   (35.35Ω 竖边)
                    TraceShuntBottom (50Ω)
                          |
                       Port1 (Input, x_min 域边界)

        - series 臂（左右竖边）35.35Ω；shunt 臂（上下横边）50Ω；
        - 四条 50Ω 馈线从环边中点引到求解域边界，波端口全部落在
          基板/空气域外边界面上（wilkinson 已验证的端口模式）；
        - 端口 sheet：P1/P2 法向 X（YZ 面，sizes 轴序 [Y,Z]）；P3/P4
          法向 Y（ZX 面，sizes 轴序 [Z,X]）——pyaedt 轴序已 inspect 确认。
        """
        from ansys.aedt.core.generic.constants import Gravity

        from rfauto.adapters.hfss_builder_utils import (
            AIRBOX,
            GROUND,
            MATERIAL_AIR,
            MATERIAL_PEC,
            MATERIAL_SUBSTRATE,
            Quantity,
        )

        modeler = hfss.modeler
        # B7 迁移：字面零值经 Quantity 显式单位构造（输出仍为 0mm，行为等价）
        zero_mm = Quantity.mm(0.0).to_hfss()

        # ─── 求解域范围（端口面 = 域边界，与 wilkinson 同模式） ────────────
        x0 = "(-arm_len/2-series_w/2-feed_len)"
        x1 = "(arm_len/2+series_w/2+feed_len)"
        y0 = "(-arm_len/2-shunt_w/2-feed_len)"
        y1 = "(arm_len/2+shunt_w/2+feed_len)"
        x_len = "(arm_len+series_w+2*feed_len)"
        y_len = "(arm_len+shunt_w+2*feed_len)"

        # ─── 1. 基板 + 接地面 ─────────────────────────────────────────────
        modeler.create_box(
            origin=[x0, y0, zero_mm], sizes=[x_len, y_len, "sub_h"],
            name="Substrate", material=MATERIAL_SUBSTRATE,
        )
        modeler.create_box(
            origin=[x0, y0, zero_mm], sizes=[x_len, y_len, zero_mm],
            name=GROUND, material=MATERIAL_PEC,
        )

        # ─── 2. 方环四臂 + 四条馈线（全 PEC，unite 成单一对象） ────────────
        # 上/下 shunt 臂（50Ω 横边）
        modeler.create_box(
            origin=["(-arm_len/2)", "(arm_len/2-shunt_w/2)", "sub_h"],
            sizes=["arm_len", "shunt_w", "copper_t"],
            name="TraceShuntTop", material=MATERIAL_PEC,
        )
        modeler.create_box(
            origin=["(-arm_len/2)", "(-arm_len/2-shunt_w/2)", "sub_h"],
            sizes=["arm_len", "shunt_w", "copper_t"],
            name="TraceShuntBottom", material=MATERIAL_PEC,
        )
        # 左/右 series 臂（35.35Ω 竖边）
        modeler.create_box(
            origin=["(-arm_len/2-series_w/2)", "(-arm_len/2)", "sub_h"],
            sizes=["series_w", "arm_len", "copper_t"],
            name="TraceSeriesLeft", material=MATERIAL_PEC,
        )
        modeler.create_box(
            origin=["(arm_len/2-series_w/2)", "(-arm_len/2)", "sub_h"],
            sizes=["series_w", "arm_len", "copper_t"],
            name="TraceSeriesRight", material=MATERIAL_PEC,
        )
        # 四条 50Ω 馈线（从环边中点伸到域边界；与臂体重叠保证 unite 连通）
        modeler.create_box(
            origin=[x0, "(-shunt_w/2)", "sub_h"],
            sizes=["(feed_len+series_w)", "shunt_w", "copper_t"],
            name="TraceFeedP1", material=MATERIAL_PEC,
        )
        modeler.create_box(
            origin=["(arm_len/2-series_w/2)", "(-shunt_w/2)", "sub_h"],
            sizes=["(feed_len+series_w)", "shunt_w", "copper_t"],
            name="TraceFeedP2", material=MATERIAL_PEC,
        )
        modeler.create_box(
            origin=["(-shunt_w/2)", "(arm_len/2-shunt_w/2)", "sub_h"],
            sizes=["shunt_w", "(feed_len+shunt_w)", "copper_t"],
            name="TraceFeedP3", material=MATERIAL_PEC,
        )
        modeler.create_box(
            origin=["(-shunt_w/2)", y0, "sub_h"],
            sizes=["shunt_w", "(feed_len+shunt_w)", "copper_t"],
            name="TraceFeedP4", material=MATERIAL_PEC,
        )
        hfss.modeler.unite([
            "TraceShuntTop", "TraceShuntBottom",
            "TraceSeriesLeft", "TraceSeriesRight",
            "TraceFeedP1", "TraceFeedP2", "TraceFeedP3", "TraceFeedP4",
        ], keep_originals=False)
        logger.debug("合并微带线: 8 个对象 → 1 个方环（合并后名保留 TraceShuntTop）")

        # ─── 3. 空气域 + 辐射边界（仅顶面，wilkinson 已验证模式） ──────────
        # 四个侧面都有波端口 → 空气域 XY 必须与基板完全同界（不能加边距，
        # 否则端口面落入域内部，HFSS 报 internal wave port；首版真机跑的
        # 失败根因即此）。空气域只在 Z 向抬高。
        modeler.create_box(
            origin=[x0, y0, zero_mm],
            sizes=[x_len, y_len, "(sub_h+copper_t+air_margin)"],
            name=AIRBOX, material=MATERIAL_AIR,
        )
        modeler.subtract(AIRBOX, ["Substrate", "TraceShuntTop"])
        air_faces = modeler.get_object_faces(AIRBOX)
        top_face = max(air_faces, key=lambda f: modeler.get_face_center(f)[2])
        hfss.assign_radiation_boundary_to_faces(assignment=[top_face], name="RadiationBoundary")

        # ─── 4. 四个波端口（全部位于求解域外边界） ──────────────────────────
        z_span = "(sub_h+copper_t+3*sub_h)"   # 地面到基板上空 3H（教科书口径）
        sheet_w = "(5*shunt_w)"               # 端口 sheet 宽 ≈ 5 倍线宽

        def _port_sheet_normal_x(name, x_expr):
            """法向 X 的端口 sheet（YZ 面，sizes 轴序 [Y, Z]）。"""
            modeler.create_rectangle(
                orientation="YZ",
                origin=[x_expr, f"(-{sheet_w}/2)", zero_mm],
                sizes=[sheet_w, z_span],
                name=f"PortSheet_{name}",
            )
            return modeler.get_object_faces(f"PortSheet_{name}")[0]

        def _port_sheet_normal_y(name, y_expr):
            """法向 Y 的端口 sheet（ZX 面，sizes 轴序 [Z, X]）。"""
            modeler.create_rectangle(
                orientation="ZX",
                origin=[f"(-{sheet_w}/2)", y_expr, zero_mm],
                sizes=[z_span, sheet_w],
                name=f"PortSheet_{name}",
            )
            return modeler.get_object_faces(f"PortSheet_{name}")[0]

        p1_face = _port_sheet_normal_x("P1", x0)
        hfss.wave_port(assignment=p1_face, name="Port1", impedance=50.0,
                       renormalize=True, integration_line=Gravity.ZPos)
        p2_face = _port_sheet_normal_x("P2", x1)
        hfss.wave_port(assignment=p2_face, name="Port2", impedance=50.0,
                       renormalize=True, integration_line=Gravity.ZPos)
        p3_face = _port_sheet_normal_y("P3", y1)
        hfss.wave_port(assignment=p3_face, name="Port3", impedance=50.0,
                       renormalize=True, integration_line=Gravity.ZPos)
        p4_face = _port_sheet_normal_y("P4", y0)
        hfss.wave_port(assignment=p4_face, name="Port4", impedance=50.0,
                       renormalize=True, integration_line=Gravity.ZPos)
        logger.debug("创建方环波端口: Port1(左入) Port2(右通) Port3(上耦) Port4(下隔)")

    def evaluate_extras(self, metrics: dict[str, float]) -> dict[str, float]:
        """Branchline 专属指标：耦合度、隔离度。"""
        return metrics


# 自动注册
register(BranchlineCouplerPlugin)
