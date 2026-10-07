"""F-I P3 离线面定向门：layout_sim_service 组装层 + 发射面（零求解）。

判据映射（研究扩充 round5 §二 F-I P3 + 任务书交付骨架）：

- **组装往返（P2 字节钉组件进来不变）**：render_substrate_block /
  render_substrate_mesh_block 产物**逐字节包含**在组装脚本里（#329 纪律：
  既有渲染组件原样拼入，本服务不转写）；同输入 sha256 稳定（判据①的组装面）；
- **端口 schema 对齐 compose pin 契约**：信封 pin_dicts 键集 = COMPOSE_PIN_KEYS；
- **负例（ok=False 信封不抛）**：缺材料数值 / 缺端口 / 穯口表 / 端口层不是
  导体层 / msl 端口 v1 拒绝 / 无参考地 / 多材料组+孔洞 / 几何全不匹配；
- **发射面 schema**：产物清单（simulation.py sha256 与脚本一致 / runner shim
  条件产物 / sparams.csv 预期产物）+ 预算注记（占位口径 + 终网格实算提示）；
- **#212 离线几何审计**（秒级零仿真，CSXCAD exec——CSXCAD 缺席时 skip，
  不碰 FDTD.Run）：渲染头 exec → 金属原语计数/基板材料实存，字符串组装
  抓不住的画法错误在此兜底。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from rfauto.adapters.layout_ports import COMPOSE_PIN_KEYS
from rfauto.adapters.layout_stack import RFRouteLayer, RFStackup
from rfauto.adapters.layout_substrate import (
    MaterialProps,
    render_substrate_block,
    render_substrate_mesh_block,
)
from rfauto.service.layout_sim_service import (
    LAYOUT_SIM_SERVICE_SCHEMA_VERSION,
    layout_sim_prepare,
)

_H_SUB = 5.08e-4  # 0.508mm（米）


def _stackup_payload(*, ground_z: float | None = _H_SUB) -> dict:
    """双导层叠层：介质 + F.Cu 信号层 + GND 地层（ground_z=None = 无地负例）。

    ground_z=_H_SUB → 共面地（CPW 口径，面内端口）；ground_z=0.0 → 底地
    （微带口径，F.Cu 在顶、垂直端口）。
    """
    layers = [
        {"name": "dielectric 1", "zmin_m": 0.0, "thickness_m": _H_SUB,
         "material": "fr4", "kind": "dielectric"},
    ]
    if ground_z == 0.0:
        layers.append({"name": "GND", "zmin_m": 0.0, "thickness_m": 0.0,
                       "material": "copper", "kind": "ground"})
        layers.append({"name": "F.Cu", "zmin_m": _H_SUB, "thickness_m": 0.0,
                       "material": "copper", "kind": "signal"})
    else:
        layers.append({"name": "F.Cu", "zmin_m": _H_SUB, "thickness_m": 0.0,
                       "material": "copper", "kind": "signal"})
        if ground_z is not None:
            layers.append({"name": "GND", "zmin_m": _H_SUB, "thickness_m": 0.0,
                           "material": "copper", "kind": "ground"})
    return {"name": "test_stackup", "layers": layers}


def _layout_payload(*, layer: str = "F.Cu", extra_layer: str | None = None) -> dict:
    items = [
        {"kind": "path", "points": [[0.0, 0.0], [10.0, 0.0]],
         "width_mm": 0.5, "layer": layer},
    ]
    layers = [{"name": layer, "gds_layer": 1, "gds_datatype": 0}]
    if extra_layer is not None:
        items.append({"kind": "polygon",
                      "points": [[-2.0, -2.0], [12.0, -2.0], [12.0, 2.0], [-2.0, 2.0]],
                      "layer": extra_layer})
        layers.append({"name": extra_layer, "gds_layer": 2, "gds_datatype": 0})
    return {"name": "demo", "layers": layers, "items": items, "annotations": {}}


def _payload() -> dict:
    """基础载荷：叠层/材料/几何/sim 齐备、**无端口**（端口由调用方按用例给出）。"""
    return {
        "stackup": _stackup_payload(),
        "material_props": {"dielectric 1": {"epsilon_r": 4.4, "loss_tangent": 0.02}},
        "layout": _layout_payload(extra_layer="GND"),
        "ports": {"marker_layer": "PORT", "port_layer": "F.Cu"},
        "sim": {"f0_ghz": 2.5, "fc_ghz": 1.0},
    }


def _payload_with_marker() -> dict:
    """标准载荷完整版：版图含 PORT 标记线（marker 端口通道可解析出 1 端口）。"""
    payload = _payload()
    payload["layout"]["items"].append(
        {"kind": "path", "points": [[0.0, 0.0], [1.0, 0.0]],
         "width_mm": 0.5, "layer": "PORT"})
    payload["layout"]["layers"].append(
        {"name": "PORT", "gds_layer": 3, "gds_datatype": 0})
    return payload


def _yaml_ports() -> list[dict]:
    """YAML 显式端口表：1 端口（与 marker 通道同几何）。"""
    return [{"port_id": "P1", "position_mm": [0.0, 0.0], "direction": [1, 0],
             "width_mm": 0.5, "layer": "F.Cu"}]


def _prim_with_hole() -> dict:
    """P1 渲染原语直通形态：带一个孔洞的 F.Cu 多边形（米制）。"""
    return {
        "kind": "polygon",
        "coords": [(-1e-3, -1e-3), (11e-3, -1e-3), (11e-3, 1e-3), (-1e-3, 1e-3)],
        "holes": [[(4e-3, -2e-4), (6e-3, -2e-4), (6e-3, 2e-4), (4e-3, 2e-4)]],
        "layer": "F.Cu", "layer_kind": "signal",
        "material": "copper", "zmin_m": _H_SUB, "thickness_m": 0.0,
        "mesh_hint_mm": None,
    }


# ---------------------------------------------------------------------------
# 组装往返与确定性（判据①组装面）
# ---------------------------------------------------------------------------


class TestAssemblyRoundTrip:
    def test_ok_envelope_happy_path(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        assert env["ok"] is True
        script = env["render_script"]
        assert "FDTD.Run(SIM_PATH" in script  # 产物是完整可发射脚本
        assert "CSX = ContinuousStructure()" in script
        assert 'w.writerow(["freq_hz", "re_S11", "im_S11"])' in script
        assert env["zero_solve"] is True and env["engine"] == "openEMS"
        assert env["schema_version"] == LAYOUT_SIM_SERVICE_SCHEMA_VERSION

    def test_p2_substrate_block_byte_contained(self) -> None:
        """P2 字节钉组件进来不变：基板块与 z 网格块逐字节原样拼入（#329）。

        坐标符号用本服务的域口径（基板延伸到侧边界 = DOM_X/DOM_Y 官方惯例），
        与服务内部调用同参 → 产物必须逐字节等于 P2 直出文本。
        """
        payload = _payload_with_marker()
        stackup = RFStackup(
            name="test_stackup",
            layers=tuple(
                RFRouteLayer(name=lay["name"], zmin_m=lay["zmin_m"],
                             thickness_m=lay["thickness_m"],
                             material=lay["material"], kind=lay["kind"])
                for lay in payload["stackup"]["layers"]))
        props = {"dielectric 1": MaterialProps(4.4, 0.02)}
        env = layout_sim_prepare(payload)
        assert env["ok"] is True
        assert render_substrate_block(
            stackup, props,
            x_lo="-DOM_X", x_hi="DOM_X", y_lo="-DOM_Y", y_hi="DOM_Y",
        ) in env["render_script"]
        assert render_substrate_mesh_block(stackup, props) in env["render_script"]

    def test_same_input_same_sha256(self) -> None:
        env1 = layout_sim_prepare(_payload_with_marker())
        env2 = layout_sim_prepare(_payload_with_marker())
        assert env1["ok"] and env2["ok"]
        h1 = hashlib.sha256(env1["render_script"].encode("utf-8")).hexdigest()
        h2 = hashlib.sha256(env2["render_script"].encode("utf-8")).hexdigest()
        assert h1 == h2
        assert env1["provenance"]["script_sha256"] == h1

    def test_geometry_and_ports_emitted(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        script = env["render_script"]
        assert "metal_F_Cu.AddPolygon(" in script
        assert "metal_GND.AddPolygon(" in script
        assert "FDTD.AddLumpedPort(1, R_PORT," in script
        assert '"y", 1.0,' in script  # 方向 +x → 端口元沿 y 正交轴展开，port1 激励
        assert "elevation=0.000508" in script
        assert env["geometry"]["n_primitives"] == 2
        assert env["geometry"]["n_metal_layers"] == 2

    def test_base_auto_lambda_sub_over_50_and_explicit_override(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        assert env["provenance"]["mesh"]["base_basis"] == "auto_lambda_sub_over_50"
        # λ_sub = c/(f_max·√εr)/50 = 3e8/(3.5e9·√4.4)/50 ≈ 0.8167mm
        assert env["provenance"]["mesh"]["base_mm"] == pytest.approx(0.8167, rel=1e-3)
        payload = _payload_with_marker()
        payload["sim"]["mesh_base_mm"] = 0.5
        env2 = layout_sim_prepare(payload)
        assert env2["provenance"]["mesh"]["base_basis"] == "explicit"
        assert env2["provenance"]["mesh"]["base_mm"] == pytest.approx(0.5)
        assert 'BASE = 0.0005' in env2["render_script"]


# ---------------------------------------------------------------------------
# 端口契约与负例
# ---------------------------------------------------------------------------


class TestPortContract:
    def test_pin_dicts_match_compose_contract(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        assert env["ok"] is True
        assert env["ports"]["n_ports"] == 1
        assert set(env["ports"]["pin_dicts"][0]) == set(COMPOSE_PIN_KEYS)
        assert env["ports"]["pin_dicts"][0]["pin_id"] == "P1"
        assert env["ports"]["pin_dicts"][0]["cross_section"] == {"layer": "F.Cu"}

    def test_yaml_table_source_and_vertical_mode(self) -> None:
        """底地层（微带口径）→ 垂直端口模式；yaml 显式表来源。"""
        payload = _payload()
        payload["stackup"] = _stackup_payload(ground_z=0.0)
        payload["layout"] = _layout_payload()
        payload["ports"] = _yaml_ports()
        env = layout_sim_prepare(payload)
        assert env["ok"] is True
        assert env["ports"]["source"] == "yaml"
        assert '"z", 1.0,' in env["render_script"]  # 垂直模式 axis=z
        assert env["ports"]["pin_dicts"][0]["position"] == [0.0, 0.0]

    def test_marker_layer_noise_filtered_from_warnings(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        warnings = env["provenance"]["warnings"]
        assert all("PORT" not in w for w in warnings)  # 标记层 unmatched=预期
        assert not any("GND" in w and "未匹配" in w for w in warnings)


class TestNegativeEnvelope:
    """ok=False 信封不抛（负例族）。"""

    def test_missing_material_props(self) -> None:
        payload = _payload_with_marker()
        del payload["material_props"]
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("material_props" in e for e in env["errors"])

    def test_wrong_material_props_raises_envelope(self) -> None:
        """介质层缺数值定义 → P2 resolve_material_props 显错经信封转 ok=False。"""
        payload = _payload_with_marker()
        payload["material_props"] = {"typo_layer": {"epsilon_r": 4.4, "loss_tangent": 0.0}}
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("缺材料数值定义" in e for e in env["errors"])

    def test_missing_ports_key(self) -> None:
        payload = _payload_with_marker()
        del payload["ports"]
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("ports" in e for e in env["errors"])

    def test_empty_port_table_without_heuristic(self) -> None:
        payload = _payload_with_marker()
        payload["ports"] = {"port_table": []}
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("0 端口" in e for e in env["errors"])

    def test_port_layer_not_conductor(self) -> None:
        payload = _payload_with_marker()
        payload["ports"] = {"marker_layer": "PORT", "port_layer": "dielectric 1"}
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("导体层" in e for e in env["errors"])

    def test_msl_port_rejected_v1(self) -> None:
        payload = _payload_with_marker()
        payload["ports"] = [{"port_id": "P1", "position_mm": [0.0, 0.0],
                             "direction": [1, 0], "width_mm": 0.5,
                             "layer": "F.Cu", "port_type": "msl"}]
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("msl" in e and "#347" in e for e in env["errors"])

    def test_no_ground_reference_negative(self) -> None:
        payload = _payload_with_marker()
        payload["stackup"] = _stackup_payload(ground_z=None)
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("参考地" in e for e in env["errors"])

    def test_multigroup_with_holes_negative(self) -> None:
        """多介质材料组 + 带孔图元（primitives 直通）→ 显错不猜（v1 边界 2）。"""
        payload = _payload_with_marker()
        payload["stackup"]["layers"].append(
            {"name": "pp", "zmin_m": 2 * _H_SUB, "thickness_m": _H_SUB,
             "material": "prepreg", "kind": "dielectric"})
        payload["material_props"]["pp"] = {"epsilon_r": 4.9, "loss_tangent": 0.02}
        payload["primitives"] = [_prim_with_hole()]
        del payload["layout"]
        payload["ports"] = _yaml_ports()
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("孔洞" in e for e in env["errors"])

    def test_all_geometry_unmatched_negative(self) -> None:
        payload = _payload_with_marker()
        payload["layout"] = _layout_payload(layer="NOPE")
        payload["ports"] = {"port_table": _yaml_ports()}
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("无匹配几何" in e for e in env["errors"])

    def test_non_dict_payload_and_missing_sim(self) -> None:
        env = layout_sim_prepare([1, 2, 3])  # type: ignore[arg-type]
        assert env["ok"] is False
        env2 = layout_sim_prepare({"stackup": _stackup_payload(),
                                   "layout": _layout_payload(),
                                   "ports": _yaml_ports()})
        assert env2["ok"] is False
        assert any("sim" in e for e in env2["errors"])

    def test_layout_and_primitives_mutually_exclusive(self) -> None:
        payload = _payload_with_marker()
        payload["primitives"] = [_prim_with_hole()]
        env = layout_sim_prepare(payload)
        assert env["ok"] is False
        assert any("二选一" in e for e in env["errors"])


# ---------------------------------------------------------------------------
# 发射面：产物清单 / 预算注记 / provenance
# ---------------------------------------------------------------------------


class TestLaunchFace:
    def test_artifact_manifest_schema(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        assert env["ok"] is True
        by_name = {a["name"]: a for a in env["artifacts"]}
        sim_py = by_name["simulation.py"]
        assert sim_py["kind"] == "render_script"
        assert sim_py["sha256"] == hashlib.sha256(
            env["render_script"].encode("utf-8")).hexdigest()
        assert sim_py["bytes"] == len(env["render_script"].encode("utf-8"))
        runner = by_name["_rfauto_runner.py"]
        assert runner["kind"] == "runner_shim" and runner["conditional"] is True
        csv_art = by_name["sparams.csv"]
        assert csv_art["kind"] == "expected_output"
        assert csv_art["columns"] == ["freq_hz", "re_S11", "im_S11"]

    def test_budget_placeholder_fields(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        budget = env["budget"]
        assert budget["estimation"] == "placeholder_lower_bound"
        assert budget["nrts_effective"] == 100000  # 官方缺省
        assert budget["nrts_basis"] == "official_default"
        assert budget["dt_cfl_upper_bound_s"] > 0.0
        assert budget["nrts_lower_bound"] > 0
        assert "终网格" in budget["note"]
        # 脚本 NrTS 用官方缺省值发射（占位预算不回写脚本）
        assert "openEMS(NrTS=100000)" in env["render_script"]
        payload = _payload_with_marker()
        payload["sim"]["nrts"] = 150000
        env2 = layout_sim_prepare(payload)
        assert env2["budget"]["nrts_effective"] == 150000
        assert env2["budget"]["nrts_basis"] == "explicit"

    def test_provenance_completeness(self) -> None:
        env = layout_sim_prepare(_payload_with_marker())
        prov = env["provenance"]
        assert prov["schema_version"] == LAYOUT_SIM_SERVICE_SCHEMA_VERSION
        assert prov["zero_solve"] is True
        assert prov["component_versions"]["primitive_schema"] == 1
        assert prov["component_versions"]["plan_substrate"] == 1
        assert prov["script_sha256"] == prov["script_sha256"]  # 键存在
        assert prov["ports"]["pin_contract_keys"] == list(COMPOSE_PIN_KEYS)
        assert len(prov["boundaries"]) >= 3  # v1 边界预声明
        assert any("#347" in b for b in prov["boundaries"])

    def test_hole_cut_emitted_with_higher_priority(self) -> None:
        """带孔图元（primitives 直通，B2 LayoutPolygon 无孔字段）→ 切除发射。"""
        payload = _payload()
        del payload["layout"]
        payload["primitives"] = [_prim_with_hole()]
        payload["ports"] = _yaml_ports()
        env = layout_sim_prepare(payload)
        assert env["ok"] is True
        assert env["geometry"]["source"] == "primitives_direct"
        assert env["geometry"]["n_hole_cuts"] == 1
        assert "priority=11" in env["render_script"]  # 切除 > 外环 priority=10
        assert "sub.AddPolygon(" in env["render_script"]  # 基板材料同面切除


# ---------------------------------------------------------------------------
# #212 离线几何审计（CSXCAD exec，秒级零仿真；FDTD.Run 不执行）
# ---------------------------------------------------------------------------


def _exec_head(script: str, tmp_path: Path) -> dict:
    pytest.importorskip("CSXCAD")
    head = script[:script.index("FDTD.Run(")]
    g: dict = {"__name__": "__main__", "__file__": str(tmp_path / "simulation.py")}
    exec(compile(head, "simulation.py", "exec"), g)
    return g


class TestExecGeometryAudit:
    def test_csx_properties_offline_exec(self, tmp_path: Path) -> None:
        """#212 制度化：字符串组装抓不住画法错误——exec 几何段实测 CSX。"""
        env = layout_sim_prepare(_payload_with_marker())
        assert env["ok"] is True
        g = _exec_head(env["render_script"], tmp_path)
        csx = g["CSX"]
        types: dict[str, int] = {}
        metal_prims = 0
        for i in range(csx.GetQtyProperties()):
            prop = csx.GetProperty(i)
            t = str(prop.GetTypeString())
            types[t] = types.get(t, 0) + 1
            if t == "Metal":
                metal_prims += len(prop.GetAllPrimitives())
        assert types.get("Metal") == 2  # F.Cu + GND 两个金属属性
        assert metal_prims == env["geometry"]["n_primitives"]
        assert types.get("Material", 0) >= 1  # 基板材料实存
        mesh = csx.GetGrid()
        for ax in ("x", "y", "z"):
            assert mesh.GetQtyLines(ax) > 0  # 三轴网格非空

    def test_exec_port_plane_on_grid(self, tmp_path: Path) -> None:
        """端口位置必须落格（#154 前节）：x/y 网格含端口坐标线。"""
        env = layout_sim_prepare(_payload_with_marker())
        assert env["ok"] is True
        g = _exec_head(env["render_script"], tmp_path)
        mesh = g["CSX"].GetGrid()
        xs = {mesh.GetLine("x", i) for i in range(mesh.GetQtyLines("x"))}
        ys = {mesh.GetLine("y", i) for i in range(mesh.GetQtyLines("y"))}
        assert 0.0 in xs and 0.0 in ys  # 端口位置 (0,0) 精确入网
