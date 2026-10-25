"""wave_port_cpw 规划器+落地层测试（K7，aurora_k 战役，P12/F6 前半）。

用户实测病灶原值复现钉面（反馈 §6.1 P12，2026-10-23，八角电感工程 um 制）：

- **13:05 旧端口**：aperture z 窗口 ZStart=0/Height=190（金属层 200.2–205.2
  完全没圈住）照样能建/能解/能导出 → 解出 L≈0.135 nH 等效短路；积分线
  z=102.6 在 200 μm 衬底内部——规划器必须**建模阶段直接报错**（用户验收
  口径原文："用 13:05 那组参数调用生成器，必须在建模阶段直接报错，而不是
  解出 0.135 nH"），错误文案必须带数值证据与假结果人话。
- **19:29 v5**：空气盒 6 面全辐射（含端口面，旧代码 `and False` 永不跳过）
  → radiation_on_port_plane=True 入参形态必须被第 5 条拦下；端口面在域内
  （y=-660 vs 域 y0=-720）→ 第 1 条拦下。
- **旧版整块衬底宽 ±300**（aperture 端落空气/衬底边沿）→ 第 3 条拦下。
- **衬底不延伸到端口面**（真实模型 SUB_IND y0=-420 vs 端口 y=-660 差 240）
  → 第 3 方入口（plan_from_nets 桥）第 6 条拦下。

全部确定性：零真机零网络（落地层 modeler/hfss 用 mock 同形态：create_
rectangle/get_object_faces + wave_port 记录调用）；六不变量逐条违反各有
独立钉。
"""

from __future__ import annotations

from typing import Any

import pytest

from rfauto.adapters.hfss_builder_utils import NetRegistry, wave_port_cpw
from rfauto.adapters.wave_port_planner import (
    WavePortPlanError,
    plan_from_nets,
    plan_wave_port_cpw,
)
from rfauto.core.errors import ModelBuildError

# ── 病灶场景几何（八角电感端口原值，um 制）───────────────────────────────────
#
# 衬底 GaAs 200μm + SiNx 0.2μm（z 0→200.2）；金属 FM 层 z 200.2–205.2
# （Cu 200.2–204.7 + Au 204.7–205.2，两段叠层并包=metal_z_range）；CPW 隙
# 30μm；端口面 y=-660（修正版求解域 y 下界收到端口面，AIRBOX y0=PORT_Y）。

DOMAIN = [-630.0, -660.0, -40.0, 630.0, 640.0, 620.0]
#: v5/v5 前形态：域 y0=-720（端口面在域内 60μm——第 1 条病灶）
DOMAIN_INTERNAL = [-630.0, -720.0, -40.0, 630.0, 640.0, 620.0]
#: 衬底已铺到端口面（修正理想态；真实 SUB_IND y0=-420 见 plan_from_nets 病灶钉）
SUBSTRATE = [-330.0, -660.0, 0.0, 330.0, 340.0, 200.2]
SIGNAL = [6.47, -660.0, 200.2, 136.47, -415.0, 205.2]
#: 左右地（内沿 = 信号边沿 ± gap=30；宽地→5×gap 探入不触钳制）
GROUNDS = [
    [-330.0, -660.0, 200.2, -23.53, -390.0, 205.2],
    [166.47, -660.0, 200.2, 330.0, -390.0, 205.2],
]
#: 右地窄（外沿 300 < 内沿+5×gap=316.47）→ 探入被地外沿钳制
GROUNDS_NARROW = [
    [-330.0, -660.0, 200.2, -23.53, -390.0, 205.2],
    [166.47, -660.0, 200.2, 300.0, -390.0, 205.2],
]
GAP = 30.0
METAL_Z = (200.2, 205.0 + 0.2)


def _plan(**kwargs: Any) -> dict[str, Any]:
    """好几何缺省参数的规划便捷入口（kwargs 覆盖病灶入口）。"""
    base: dict[str, Any] = dict(
        plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um"
    )
    base.update(kwargs)
    return plan_wave_port_cpw(DOMAIN, SUBSTRATE, SIGNAL, GROUNDS, GAP, **base)


# ── 好参数：方案各字段值钉 ──────────────────────────────────────────────────


class TestPlanGoodGeometry:
    def test_plan_fields_pinned(self) -> None:
        """好几何全字段钉：sheet/aperture/积分线/边界配置/不变量全绿。"""
        p = _plan()
        assert p["kind"] == "wave_port_cpw_plan"
        assert p["units"] == "um"
        # 不变量 1：端口面=域 y 下界（lo 面）
        assert p["plane"] == {
            "axis": "y", "at": -660.0, "domain_face": "lo", "orientation": "ZX"}
        # sheet：#310 尺寸序（法向 y → sizes=[ΔZ, ΔX]）
        assert p["sheet"]["orientation"] == "ZX"
        assert p["sheet"]["origin"] == pytest.approx([-173.53, -660.0, 0.0])
        assert p["sheet"]["sizes"] == pytest.approx([295.2, 490.0])
        # aperture：z=衬底底 0 → 金属顶 205.2+3×30=295.2；
        # 横向=地内沿向外探 5×gap=150（左右地均够宽，不触钳制）
        assert p["aperture"]["z"] == pytest.approx([0.0, 295.2])
        assert p["aperture"]["lateral"] == pytest.approx([-173.53, 316.47])
        assert p["aperture"]["bbox"] == pytest.approx(
            [-173.53, -660.0, 0.0, 316.47, -660.0, 295.2])
        # 积分线：左地内沿 → 信号左沿，z=金属层中心 202.7
        assert p["integration_line"]["start"] == pytest.approx([-23.53, -660.0, 202.7])
        assert p["integration_line"]["end"] == pytest.approx([6.47, -660.0, 202.7])
        assert p["integration_line"]["z"] == pytest.approx(202.7)
        assert p["integration_line"]["z_basis"] == "metal_center"
        assert p["integration_line"]["from"] == "ground_inner_edge"
        assert p["integration_line"]["to"] == "signal_edge"
        # 边界配置：端口面排除辐射 + aperture 外 PEC 壁 + 单模 50Ω
        bc = p["boundary_config"]
        assert bc["radiation_on_port_plane"] is False
        assert bc["port_face"] == {"axis": "y", "at": -660.0, "domain_face": "lo"}
        assert bc["outside_aperture_wall"] == "pec"
        assert bc["pec_cap"] is False
        assert bc["modes"] == 1
        assert bc["impedance"] == 50.0
        assert bc["renormalize"] is True
        assert bc["deembed"] == 0.0
        # 六不变量全绿且证据带数值
        assert set(p["invariants"]) == {str(i) for i in range(1, 7)}
        assert all(v["ok"] for v in p["invariants"].values())
        assert "295.2" in p["invariants"]["2"]["evidence"]
        assert "未取整宽" in p["invariants"]["3"]["evidence"]
        assert "202.7" in p["invariants"]["4"]["evidence"]
        assert p["notes"] == []

    def test_plan_lateral_pen_clamped_by_narrow_ground(self) -> None:
        """右地窄（外沿 300）：探入被地外沿钳制 pen=133.53，端点仍落金属上。"""
        p = plan_wave_port_cpw(
            DOMAIN, SUBSTRATE, SIGNAL, GROUNDS_NARROW, GAP,
            plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")
        assert p["aperture"]["lateral"] == pytest.approx([-173.53, 300.0])
        assert any("钳制" in n for n in p["notes"])
        assert p["invariants"]["3"]["ok"] is True

    def test_plan_x_axis_port_idc_style(self) -> None:
        """x 法向端口（IDC 双端口形态）：orientation=YZ、sizes=[ΔY, ΔZ]。"""
        domain = [-660.0, -630.0, -40.0, 640.0, 630.0, 620.0]
        substrate = [-660.0, -460.0, 0.0, 440.0, 460.0, 200.2]
        signal = [-320.0, -215.0, 200.2, -660.0, -160.0, 205.2]
        grounds = [
            [-660.0, -460.0, 200.2, -390.0, -245.0, 205.2],   # y 低侧地
            [-660.0, -130.0, 200.2, -390.0, 460.0, 205.2],    # y 高侧地
        ]
        p = plan_wave_port_cpw(
            domain, substrate, signal, grounds, GAP,
            plane_axis="x", plane_at=-660.0, metal_z_range=METAL_Z, units="um")
        assert p["plane"]["orientation"] == "YZ"
        assert p["plane"]["domain_face"] == "lo"
        # 横向轴=y：内沿 -245/-130，外探 5×30=150 → [-395, 20]
        assert p["aperture"]["lateral"] == pytest.approx([-395.0, 20.0])
        assert p["sheet"]["origin"] == pytest.approx([-660.0, -395.0, 0.0])
        assert p["sheet"]["sizes"] == pytest.approx([415.0, 295.2])  # [ΔY, ΔZ]
        assert p["integration_line"]["start"] == pytest.approx([-660.0, -245.0, 202.7])
        assert p["integration_line"]["end"] == pytest.approx([-660.0, -215.0, 202.7])
        assert all(v["ok"] for v in p["invariants"].values())


# ── 六不变量逐条违反的报错钉 ─────────────────────────────────────────────────


class TestInvariantViolations:
    def test_inv1_internal_sheet(self) -> None:
        """第 1 条：端口面在域内（v5 形态 y0=-720，距下界 60μm）。"""
        with pytest.raises(WavePortPlanError, match="违反第 1 条") as ei:
            plan_wave_port_cpw(
                DOMAIN_INTERNAL, SUBSTRATE, SIGNAL, GROUNDS, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")
        msg = str(ei.value)
        assert "-720" in msg and "60" in msg
        assert "PEC 背衬" in msg

    def test_inv2_aperture_z_1305(self) -> None:
        """第 2 条=13:05 病灶复现：z 窗口 0–190 未覆盖金属 200.2–205.2。

        用户验收口径：用 13:05 那组参数调用生成器，必须在建模阶段直接报错，
        而不是解出 0.135 nH——错误文案必须带数值证据与 0.135 nH 人话。
        """
        with pytest.raises(WavePortPlanError, match="违反第 2 条") as ei:
            _plan(aperture_z_range=(0.0, 190.0))
        msg = str(ei.value)
        assert "190" in msg and "200.2" in msg and "205.2" in msg
        assert "295.2" in msg          # 要求的上界（金属顶+3×gap）
        assert "0.135" in msg          # 假结果人话（13:05 病灶）

    def test_inv2_auto_exceeds_domain(self) -> None:
        """第 2 条副判据：求解域 z 装不下所需孔径（域顶 250 < 295.2）。"""
        domain = [-630.0, -660.0, -40.0, 630.0, 640.0, 250.0]
        with pytest.raises(WavePortPlanError, match="超出求解域"):
            plan_wave_port_cpw(
                domain, SUBSTRATE, SIGNAL, GROUNDS, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")

    def test_inv3_lateral_full_substrate_width(self) -> None:
        """第 3 条：旧版整块衬底宽 ±300（上端 371.47 落在地外空气）。"""
        with pytest.raises(WavePortPlanError, match="违反第 3 条") as ei:
            _plan(aperture_lateral_range=(-228.53, 371.47))
        msg = str(ei.value)
        assert "371.47" in msg and "地金属" in msg

    def test_inv3_lateral_equals_substrate_width(self) -> None:
        """第 3 条后半：孔径宽=整块衬底宽（±330 满宽圈衬底/腔模）。"""
        with pytest.raises(WavePortPlanError, match="整块衬底宽度") as ei:
            _plan(aperture_lateral_range=(-330.0, 330.0))
        assert "660" in str(ei.value)   # 衬底宽证据

    def test_inv3_no_ground_on_side(self) -> None:
        """第 3 条：信号一侧无地金属（G-S-G 截面不成立）。"""
        with pytest.raises(WavePortPlanError, match="右侧没有地金属"):
            _plan_gnd_single()

    def test_inv3_ground_overlaps_signal(self) -> None:
        """第 3 条前置：地与信号横向交叠=信号短地（P13 家族）。"""
        grounds = [[-330.0, -660.0, 200.2, 80.0, -390.0, 205.2], GROUNDS[1]]
        with pytest.raises(WavePortPlanError, match="交叠") as ei:
            plan_wave_port_cpw(
                DOMAIN, SUBSTRATE, SIGNAL, grounds, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")
        assert "短路" in str(ei.value)

    def test_inv4_integration_line_z_in_substrate(self) -> None:
        """第 4 条=13:05 第二病灶：积分线 z=102.6 在衬底内部（应 202.7）。"""
        with pytest.raises(WavePortPlanError, match="违反第 4 条") as ei:
            _plan(integration_line_z=102.6)
        msg = str(ei.value)
        assert "102.6" in msg and "202.7" in msg and "衬底" in msg

    def test_inv5_radiation_on_port_plane(self) -> None:
        """第 5 条=19:29 v5 病灶：端口面被叠 Radiation（六面全辐射）。"""
        with pytest.raises(WavePortPlanError, match="违反第 5 条") as ei:
            _plan(radiation_on_port_plane=True)
        assert "Radiation" in str(ei.value) and "PEC" in str(ei.value)

    def test_inv6_substrate_short_of_plane(self) -> None:
        """第 6 条：衬底未铺到端口面（空气悬空 CPW）。"""
        substrate = [-330.0, -600.0, 0.0, 330.0, 340.0, 200.2]
        with pytest.raises(WavePortPlanError, match="违反第 6 条") as ei:
            plan_wave_port_cpw(
                DOMAIN, substrate, SIGNAL, GROUNDS, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")
        assert "空气悬空" in str(ei.value) or "悬在空气" in str(ei.value)

    def test_inv6_signal_short_of_plane(self) -> None:
        """第 6 条（导体面）：信号导体未延伸到端口面=开路 stub 家族。"""
        signal = [6.47, -600.0, 200.2, 136.47, -415.0, 205.2]
        with pytest.raises(WavePortPlanError, match="信号导体"):
            plan_wave_port_cpw(
                DOMAIN, SUBSTRATE, signal, GROUNDS, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")


def _plan_gnd_single() -> dict[str, Any]:
    """只给左侧地的规划（右侧缺地→第 3 条）。"""
    return plan_wave_port_cpw(
        DOMAIN, SUBSTRATE, SIGNAL, [GROUNDS[0]], GAP,
        plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")


# ── 13:05 全状态聚合 + 异常契约 ─────────────────────────────────────────────


class Test1305Acceptance:
    def test_1305_full_state_lists_all_violations(self) -> None:
        """13:05 旧端口全参数（z 窗口+整宽+积分线 z+叠辐射）一次报齐 2/3/4/5 条。

        验收口径：建模阶段直接报错（而不是解出 0.135 nH）——一条报错聚合
        全部违反项，details.violations 可编程消费。
        """
        with pytest.raises(WavePortPlanError) as ei:
            _plan(
                aperture_z_range=(0.0, 190.0),
                aperture_lateral_range=(-228.53, 371.47),
                integration_line_z=102.6,
                radiation_on_port_plane=True,
            )
        numbers = [v["invariant"] for v in ei.value.details["violations"]]
        assert numbers == [2, 3, 4, 5]
        msg = str(ei.value)
        assert "0.135" in msg
        for n in (2, 3, 4, 5):
            assert f"违反第 {n} 条" in msg

    def test_v5_internal_plane_auto_mode(self) -> None:
        """v5/v5 前域形态（域 y0=-720）纯自动模式也必炸（第 1 条）。"""
        with pytest.raises(WavePortPlanError, match="违反第 1 条"):
            plan_wave_port_cpw(
                DOMAIN_INTERNAL, SUBSTRATE, SIGNAL, GROUNDS, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")

    def test_error_is_valueerror_with_details(self) -> None:
        """异常契约：WavePortPlanError 是 ValueError（任务契约），带 details。"""
        with pytest.raises(ValueError) as ei:
            _plan(aperture_z_range=(0.0, 190.0))
        assert isinstance(ei.value, WavePortPlanError)
        assert isinstance(ei.value.details["violations"], list)


class TestInputValidation:
    def test_bad_axis_rejected(self) -> None:
        with pytest.raises(WavePortPlanError, match="plane_axis"):
            _plan(plane_axis="z")

    def test_bad_gap_rejected(self) -> None:
        with pytest.raises(WavePortPlanError, match="gap"):
            plan_wave_port_cpw(
                DOMAIN, SUBSTRATE, SIGNAL, GROUNDS, 0.0,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")

    def test_bad_bbox_rejected(self) -> None:
        with pytest.raises(WavePortPlanError, match="bbox"):
            plan_wave_port_cpw(
                [1, 2, 3], SUBSTRATE, SIGNAL, GROUNDS, GAP,
                plane_axis="y", plane_at=-660.0, metal_z_range=METAL_Z, units="um")

    def test_bad_units_rejected(self) -> None:
        with pytest.raises(WavePortPlanError, match="units"):
            _plan(units="mil")


# ── plan_from_nets 桥（K6 NetRegistry 互通）──────────────────────────────────


def _registry_with_feed(*, substrate_to_plane: bool = True) -> NetRegistry:
    """登记薄建房：衬底/AirBox(dielectric)+信号(Cu/Au 两段)+左右地(Cu/Au)。"""
    reg = NetRegistry(units="um")
    reg.net_begin("other")
    sub_y0 = -660.0 if substrate_to_plane else -420.0   # 真实 SUB_IND y0=-420
    reg.net_add("GaAs_sub", bbox=[-330.0, sub_y0, 0.0, 330.0, 340.0, 200.2],
                kind="dielectric")
    reg.net_add("AirBox", bbox=DOMAIN, kind="dielectric")
    reg.net_begin("signal")
    reg.net_add("feed_sig_Cu", bbox=[6.47, -660.0, 200.2, 136.47, -415.0, 204.7])
    reg.net_add("feed_sig_Au", bbox=[6.47, -660.0, 204.7, 136.47, -415.0, 205.2])
    reg.net_begin("ground")
    for suffix in ("Cu", "Au"):
        reg.net_add(f"feed_gndL_{suffix}",
                    bbox=[-330.0, -660.0, 200.2, -23.53, -390.0, 205.2])
        reg.net_add(f"feed_gndR_{suffix}",
                    bbox=[166.47, -660.0, 200.2, 330.0, -390.0, 205.2])
    return reg


class TestPlanFromNets:
    def test_bridge_matches_direct_plan(self) -> None:
        """桥产物与直调规划器逐字段一致（多层金属自动并包出 metal_z）。"""
        report = _registry_with_feed().nets_report()
        p = plan_from_nets(
            report, "P1", domain_names=("AirBox",), gap=GAP,
            plane_axis="y", plane_at=-660.0)
        ref = _plan()
        assert p["port_name"] == "P1"
        assert p["units"] == "um"
        assert p["sheet"] == ref["sheet"]
        assert p["aperture"] == ref["aperture"]
        assert p["integration_line"] == ref["integration_line"]
        # metal_z_range 缺省=信号并包 z（Cu 200.2–204.7 + Au →200.2–205.2）
        assert p["invariants"]["2"]["ok"] is True
        assert "205.2" in p["invariants"]["2"]["evidence"]
        assert set(p["extraction"]["signal"]) == {"feed_sig_Cu", "feed_sig_Au"}
        assert p["extraction"]["domain"] == ["AirBox"]
        assert p["extraction"]["substrate"] == ["GaAs_sub"]   # AirBox 已排除

    def test_bridge_substrate_short_of_plane_fires_inv6(self) -> None:
        """真实模型形态（SUB_IND y0=-420，端口 y=-660 差 240）→ 第 6 条拦下。"""
        report = _registry_with_feed(substrate_to_plane=False).nets_report()
        with pytest.raises(WavePortPlanError, match="违反第 6 条") as ei:
            plan_from_nets(
                report, "P1", domain_names=("AirBox",), gap=GAP,
                plane_axis="y", plane_at=-660.0)
        assert "-420" in str(ei.value) and "240" in str(ei.value)

    def test_bridge_requires_domain(self) -> None:
        report = _registry_with_feed().nets_report()
        with pytest.raises(WavePortPlanError, match="domain"):
            plan_from_nets(
                report, "P1", gap=GAP, plane_axis="y", plane_at=-660.0)

    def test_bridge_explicit_signal_names_and_domain_bbox(self) -> None:
        """signal_names 显式点名 + domain_bbox 显式 6 数（两条备用通道）。"""
        report = _registry_with_feed().nets_report()
        p = plan_from_nets(
            report, "P2", domain_bbox=DOMAIN, gap=GAP,
            plane_axis="y", plane_at=-660.0,
            signal_names=("feed_sig_Cu", "feed_sig_Au"))
        assert p["extraction"]["domain"] == "explicit_bbox"
        assert p["aperture"]["z"] == pytest.approx([0.0, 295.2])

    def test_bridge_unknown_name_rejected(self) -> None:
        report = _registry_with_feed().nets_report()
        with pytest.raises(WavePortPlanError, match="未登记"):
            plan_from_nets(
                report, "P1", domain_names=("AirBox",), gap=GAP,
                plane_axis="y", plane_at=-660.0, signal_names=("feed_nope",))

    def test_bridge_override_passthrough_1305(self) -> None:
        """13:05 覆盖入口经桥透传同样拦下（第 2 条）。"""
        report = _registry_with_feed().nets_report()
        with pytest.raises(WavePortPlanError, match="违反第 2 条"):
            plan_from_nets(
                report, "P1", domain_names=("AirBox",), gap=GAP,
                plane_axis="y", plane_at=-660.0,
                aperture_z_range=(0.0, 190.0))


# ── 落地层（hfss_builder_utils.wave_port_cpw）mock 冒烟 ──────────────────────


class _MockSheet:
    def __init__(self, name: str) -> None:
        self.name = name


class _MockModeler:
    """pyaedt ``app.modeler`` 最小形态（记录调用，测试零真机）。"""

    def __init__(self, *, with_app: bool = True) -> None:
        self.rect_calls: list[dict[str, Any]] = []
        self.faces: dict[str, list[int]] = {}
        self._app = _MockHfss() if with_app else None

    def create_rectangle(self, *, orientation, origin, sizes, name):
        self.rect_calls.append(
            {"orientation": orientation, "origin": list(origin),
             "sizes": list(sizes), "name": name})
        self.faces[name] = [101]
        return _MockSheet(name)

    def get_object_faces(self, name: str) -> list[int]:
        return list(self.faces.get(name, []))


class _MockHfss:
    """pyaedt ``Hfss`` app 最小形态（记录 wave_port 调用）。"""

    def __init__(self) -> None:
        self.port_calls: list[dict[str, Any]] = []

    def wave_port(self, **kwargs: Any) -> str:
        self.port_calls.append(kwargs)
        return f"BoundaryObject({kwargs['name']})"


class TestLandingLayer:
    def test_landing_creates_sheet_and_port(self) -> None:
        """落地：sheet 尺寸序/显式单位串 + wave_port 面赋值 + 两点积分线。"""
        modeler, hfss = _MockModeler(), _MockHfss()
        plan = _plan()
        out = wave_port_cpw(modeler, plan, name="PortInput", hfss=hfss)
        assert len(modeler.rect_calls) == 1
        call = modeler.rect_calls[0]
        assert call["name"] == "PortInputSheet"
        assert call["orientation"] == "ZX"
        # 显式单位串（防模型单位漂移；.10g 格式）
        assert call["origin"] == ["-173.53um", "-660um", "0um"]
        assert call["sizes"] == ["295.2um", "490um"]
        assert len(hfss.port_calls) == 1
        wp = hfss.port_calls[0]
        assert wp["assignment"] == 101
        assert wp["name"] == "PortInput"
        assert wp["modes"] == 1
        assert wp["impedance"] == 50.0
        assert wp["renormalize"] is True
        assert wp["deembed"] == 0.0
        assert wp["integration_line"] == [
            ["-23.53um", "-660um", "202.7um"], ["6.47um", "-660um", "202.7um"]]
        # 返回=端口报告字段（F6）
        assert out["port"] == "PortInput"
        assert out["sheet"] == "PortInputSheet"
        assert out["face"] == 101
        assert out["units"] == "um"
        assert out["boundary_config"]["outside_aperture_wall"] == "pec"

    def test_landing_uses_modeler_app_backref(self) -> None:
        """hfss 缺省走 modeler._app（pyaedt Primitives 均持有）。"""
        modeler = _MockModeler(with_app=True)
        assert modeler._app is not None
        out = wave_port_cpw(modeler, _plan(), name="PortInput")
        assert len(modeler._app.port_calls) == 1
        assert out["port"] == "PortInput"

    def test_landing_requires_hfss_app(self) -> None:
        """取不到 app：显式报错（不静默只建 sheet）。"""
        modeler = _MockModeler(with_app=False)
        with pytest.raises(ModelBuildError, match="hfss"):
            wave_port_cpw(modeler, _plan(), name="PortInput")

    def test_landing_rejects_non_plan(self) -> None:
        modeler = _MockModeler()
        with pytest.raises(ModelBuildError, match="plan"):
            wave_port_cpw(modeler, {"kind": "other"}, name="PortInput")
        with pytest.raises(ModelBuildError, match="plan"):
            wave_port_cpw(modeler, "not-a-plan", name="PortInput")  # type: ignore[arg-type]

    def test_landing_rejects_failed_invariants(self) -> None:
        """invariants 非全绿的 plan 拒落地（防绕过规划器带病建端口）。"""
        modeler = _MockModeler()
        plan = _plan()
        broken = dict(plan)
        broken["invariants"] = {"2": {"ok": False, "evidence": "手工篡改"}}
        with pytest.raises(ModelBuildError, match="不变量"):
            wave_port_cpw(modeler, broken, name="PortInput")

    def test_landing_rejects_auto_name(self) -> None:
        """军规 2b：Port1 这类自动名拒收。"""
        modeler = _MockModeler()
        with pytest.raises(ModelBuildError):
            wave_port_cpw(modeler, _plan(), name="Port1")

    def test_landing_wraps_pyaedt_failure(self) -> None:
        """wave_port 赋值失败 → ModelBuildError 带上下文（不裸抛 pyaedt 异常）。"""
        modeler = _MockModeler()

        class _Boom:
            def wave_port(self, **kwargs: Any) -> None:
                raise RuntimeError("grpc channel broken")

        with pytest.raises(ModelBuildError, match="wave_port 赋值失败"):
            wave_port_cpw(modeler, _plan(), name="PortInput", hfss=_Boom())

    def test_landing_mm_units_strings(self) -> None:
        """mm 制 plan → 单位串 um→mm（数值由规划器保证同单位）。"""
        domain = [-0.63, -0.66, -0.04, 0.63, 0.64, 0.62]
        substrate = [-0.33, -0.66, 0.0, 0.33, 0.34, 0.2002]
        signal = [0.00647, -0.66, 0.2002, 0.13647, -0.415, 0.2052]
        grounds = [
            [-0.33, -0.66, 0.2002, -0.02353, -0.39, 0.2052],
            [0.16647, -0.66, 0.2002, 0.33, -0.39, 0.2052],
        ]
        plan = plan_wave_port_cpw(
            domain, substrate, signal, grounds, 0.03,
            plane_axis="y", plane_at=-0.66,
            metal_z_range=(0.2002, 0.2052), units="mm")
        modeler, hfss = _MockModeler(), _MockHfss()
        wave_port_cpw(modeler, plan, name="PortInput", hfss=hfss)
        assert modeler.rect_calls[0]["origin"] == [
            "-0.17353mm", "-0.66mm", "0mm"]
        assert modeler.rect_calls[0]["sizes"] == ["0.2952mm", "0.49mm"]

    def test_landing_end_to_end_with_bridge(self) -> None:
        """端到端：NetRegistry 建房 → plan_from_nets → 落地（零真机全链）。"""
        report = _registry_with_feed().nets_report()
        plan = plan_from_nets(
            report, "P1", domain_names=("AirBox",), gap=GAP,
            plane_axis="y", plane_at=-660.0)
        modeler, hfss = _MockModeler(), _MockHfss()
        out = wave_port_cpw(modeler, plan, name="P1", hfss=hfss)
        assert out["sheet"] == "P1Sheet"
        assert hfss.port_calls[0]["assignment"] == 101
