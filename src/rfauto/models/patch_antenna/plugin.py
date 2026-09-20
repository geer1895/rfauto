"""Patch Antenna 插件——第三个模型实例。

P5 实现特性：
- 矩形贴片天线拓扑：贴片 + 同轴馈电 + 接地面
- 1 端口：Coax Feed
- 暴露接口缺口：远场提取/辐射边界（P5 验收项）
- 验证"第三实例暴露接口缺口"→ 接口冻结 ADR-0006
"""

from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel

from rfauto.core.interfaces import RFModelPlugin, SimulatorAdapter
from rfauto.models.patch_antenna.schema import PatchAntennaParams
from rfauto.models.registry import register

logger = logging.getLogger(__name__)


class PatchAntennaPlugin(RFModelPlugin):
    """矩形贴片天线模板插件。

    build() 根据参数在 HFSS 中创建完整的贴片天线几何、端口、边界和 setup。
    FakeAdapter 走解析近似。
    """

    name: ClassVar[str] = "patch_antenna"
    params_model: ClassVar[type[BaseModel]] = PatchAntennaParams
    schema_version: ClassVar[int] = 1
    # 物理上 1 端口（coax feed）；fake 解析近似无贴片模型，借 2 端口 wilkinson
    # 形状产出 s11/s21 曲线供调优回路干跑，真机走 HFSS 全链
    n_ports: ClassVar[int] = 2
    fake_model_type: ClassVar[str] = "patch"
    hfss_var_map: ClassVar[dict[str, str]] = {
        "patch_len_mm": "patch_len",
        "patch_w_mm": "patch_w",
        "feed_offset_mm": "feed_offset",
        "f0_ghz": "f0",
        "z0_ohm": "z0",
    }

    def build(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """声明式构建贴片天线。"""
        if not isinstance(params, PatchAntennaParams):
            raw = params.model_dump() if hasattr(params, "model_dump") else params.__dict__
            params = PatchAntennaParams(**raw)

        # ─── 1. 写入设计变量 ──────────────────────────────────────────────────
        var_dict = {
            "patch_len": f"{params.patch_len_mm}mm",
            "patch_w": f"{params.patch_w_mm}mm",
            "feed_offset": f"{params.feed_offset_mm}mm",
            "f0": f"{params.f0_ghz}GHz",
            "z0": f"{params.z0_ohm}ohm",
            # 固定结构参数
            "sub_h": "0.508mm",
            "sub_w": "80mm",       # 基板宽度（大于贴片）
            "sub_l": "80mm",       # 基板长度
            "copper_t": "0.035mm",
            "air_margin": "10mm",
            "air_height": "30mm",  # 空气域高度（λ/4 @ 2.4GHz ≈ 31mm）
            "coax_r": "1.5mm",        # 同轴内导体（针）半径
            "coax_wall_r": "3.5mm",   # 同轴外导体壁半径（空气线 50Ω：ln(b/a)≈0.85）
            "coax_ext": "5mm",        # 同轴伸出地板以下的长度（空气域须覆盖）
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

    def _build_hfss(self, hfss, params: PatchAntennaParams) -> None:
        """真实 HFSS 建模——矩形贴片天线。

        结构：
        - 接地面（PEC，z=0）
        - 基板（Rogers 4350B，z=0 到 z=sub_h）
        - 贴片（PEC，z=sub_h）
        - 同轴馈电（圆柱，从 z=-5mm 到 z=sub_h）
        - 空气域（z=0 到 z=air_height）+ 辐射边界（所有面）

        ★接口缺口暴露：当前 SimulatorAdapter 没有远场提取方法，
        需要新增 get_far_field() 或类似接口。这是 P5 接口冻结的输入。
        """
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

        # ─── 1. 接地面 ────────────────────────────────────────────────────────
        modeler.create_box(
            origin=["(-sub_w/2)", "(-sub_l/2)", zero_mm],
            sizes=["sub_w", "sub_l", zero_mm],
            name=GROUND,
            material=MATERIAL_PEC,
        )

        # ─── 2. 基板 ──────────────────────────────────────────────────────────
        modeler.create_box(
            origin=["(-sub_w/2)", "(-sub_l/2)", zero_mm],
            sizes=["sub_w", "sub_l", "sub_h"],
            name="Substrate",
            material=MATERIAL_SUBSTRATE,
        )

        # ─── 3. 贴片 ──────────────────────────────────────────────────────────
        modeler.create_box(
            origin=["(-patch_w/2)", "(-patch_len/2)", "sub_h"],
            sizes=["patch_w", "patch_len", "copper_t"],
            name="PatchMain",
            material=MATERIAL_PEC,
        )

        # ─── 4. 同轴探针馈电（pyaedt stackup_3d 官方模式） ────────────────────
        # 真机多轮验证后的结论：
        # - 导体与介质的"部分相交"（贯穿边界）会被 HFSS 校验拒绝，导体须
        #   完全含于介质或互相分离；
        # - 外导体用 PEC sheet 圆柱壁（不是实体管），介质柱用 vacuum；
        # - 端口放在介质柱底面（与空气域底面共面）+ create_pec_cap。
        # 结构（50Ω 空气线：ln(3.5/1.5)≈0.85）：
        #   FeedWire:   PEC 针下段 z=-coax_ext..0（完全含于 FeedOuter 真空柱）
        #   FeedPinUp:  PEC 针上段 z=0..sub_h（穿基板孔，顶面贴贴片底面）
        #   FeedOuter:  vacuum 柱 r=coax_wall_r z=-coax_ext..0（同轴介质）
        #   外导体:     FeedOuter 侧面 PEC sheet（贴地板）
        modeler.create_cylinder(
            orientation="Z",
            origin=["feed_offset", zero_mm, "(-coax_ext)"],
            radius="coax_r",
            height="coax_ext",
            name="FeedWire",
            material=MATERIAL_PEC,
        )
        modeler.create_cylinder(
            orientation="Z",
            origin=["feed_offset", zero_mm, zero_mm],
            radius="coax_r",
            height="sub_h",
            name="FeedPinUp",
            material=MATERIAL_PEC,
        )
        modeler.create_cylinder(
            orientation="Z",
            origin=["feed_offset", zero_mm, "(-coax_ext)"],
            radius="coax_wall_r",
            height="coax_ext",
            name="FeedOuter",
            material="vacuum",
        )
        # 地板/基板开孔（官方做法：地板用真空柱挖孔）
        modeler.subtract(GROUND, ["FeedOuter"], keep_originals=True)
        modeler.subtract("Substrate", ["FeedPinUp"], keep_originals=True)

        # 外导体 = 真空柱侧面 PEC sheet。侧面 = 顶点 z 有跨度的面
        # （圆盘顶/底面的顶点各自同 z）。全程只用顶点坐标——is_planar/
        # center 会对曲面写入 "[error] Script macro error" 消息，该消息
        # 会污染求解前置校验导致 Analyze 被拒（真机实测）。
        def _face_axis_sets(face):
            pts = [v.position for v in face.vertices if v.position]
            xs = {round(p[0], 6) for p in pts}
            ys = {round(p[1], 6) for p in pts}
            zs = {round(p[2], 6) for p in pts}
            return xs, ys, zs

        feed_outer_obj = modeler["FeedOuter"]
        outer_wall_id = None
        port_face_obj = None
        wall_vertex_spread = -1.0
        port_bottom_z = None
        for face in feed_outer_obj.faces:
            xs, ys, zs = _face_axis_sets(face)
            if len(zs) > 1:  # 侧面（z 有跨度）
                spread = max(zs) - min(zs)
                if spread > wall_vertex_spread:
                    wall_vertex_spread = spread
                    outer_wall_id = face.id
            else:  # 圆盘面
                z = next(iter(zs))
                if port_bottom_z is None or z < port_bottom_z:
                    port_bottom_z = z
                    port_face_obj = face  # wave_port(create_pec_cap) 需 FacePrimitive 对象
        assert outer_wall_id is not None and port_face_obj is not None
        hfss.assign_perfecte_to_sheets(outer_wall_id, "FeedOuterPEC")
        logger.debug("同轴馈电: FeedWire + FeedPinUp + 真空柱(PEC壁) + 地板/基板开孔")

        # ─── 5. 空气域 + 辐射边界 ─────────────────────────────────────────────
        # 空气域下沿 z=-coax_ext 与同轴端口面共面（端口必须在域边界上）。
        modeler.create_box(
            origin=["(-sub_w/2-air_margin)", "(-sub_l/2-air_margin)", "(-coax_ext)"],
            sizes=["(sub_w+2*air_margin)", "(sub_l+2*air_margin)", "(air_height+coax_ext)"],
            name=AIRBOX,
            material=MATERIAL_AIR,
        )
        modeler.subtract(
            AIRBOX,
            ["Substrate", "PatchMain", "FeedOuter", "FeedWire", "FeedPinUp"],
        )

        # 辐射边界（纯顶点法，仅限空气盒外表面）：
        # 外表面 = 所有顶点落在包围盒某一极值平面上的面（四侧壁 + 顶面）；
        # - 底面（z=Z0，端口面）排除；
        # - subtract 产生的内部腔面（圆柱壁、z=0 环面等）不在极值平面上，
        #   天然排除——真机实测把内部面赋辐射边界会报
        #   "An internal radiation boundary has been detected which HFSS does
        #    not support"（hf3d 端口精化阶段直接失败）。
        airbox = modeler[AIRBOX]
        all_pts = [v.position for f in airbox.faces for v in f.vertices if v.position]
        x0e, x1e = min(p[0] for p in all_pts), max(p[0] for p in all_pts)
        y0e, y1e = min(p[1] for p in all_pts), max(p[1] for p in all_pts)
        z1e = max(p[2] for p in all_pts)
        radiating_faces = []
        for face in airbox.faces:
            xs, ys, zs = _face_axis_sets(face)
            if len(xs) == 1 and (xs == {x0e} or xs == {x1e}):
                radiating_faces.append(face.id)  # x 方向侧壁
            elif len(ys) == 1 and (ys == {y0e} or ys == {y1e}):
                radiating_faces.append(face.id)  # y 方向侧壁
            elif len(zs) == 1 and zs == {z1e}:
                radiating_faces.append(face.id)  # 顶面
        hfss.assign_radiation_boundary_to_faces(
            assignment=radiating_faces,
            name="RadiationBoundary",
        )
        logger.debug("创建辐射边界: %d 个外表面（顶点法：底面/内部腔面排除）", len(radiating_faces))

        # ─── 6. 波端口（真空柱底面 + PEC 背腔，官方做法） ─────────────────────
        hfss.wave_port(
            port_face_obj,
            reference="FeedOuter",
            create_pec_cap=True,
            name="PortInput",
            impedance=50.0,
            renormalize=True,
        )
        logger.debug("创建贴片天线: PatchMain + 同轴探针馈电 + PortInput")

    def evaluate_extras(self, metrics: dict[str, float]) -> dict[str, float]:
        """Patch Antenna 专属指标：增益、方向图。

        接口状态（C4 复核）：SimulatorAdapter.get_far_field() 已存在（P5 冻结后
        增补），FakeAdapter 有解析近似实现；缺口在 HfssAdapter 侧的真机实现
        （capabilities().supports_field_export 为真时才可调用），待真机联调时补。
        """
        return metrics


# 自动注册
register(PatchAntennaPlugin)
