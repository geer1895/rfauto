"""UI 修复批项 4（2026-09-15）：3D 预览基板直立 → 轴向回归钉子。

根因定位（两层嫌疑逐一排查）：
- spec 层（adapters/openems_templates.geometry_spec，经 ui_service.model3d_for_params
  透传）**正确**：基板 ``start_mm=[-60,-60,0] stop_mm=[60,60,h]``，z=厚度轴（0.508mm），
  x/y=120×120 水平面，与 render_script 同口径——不动渲染内核。
- 前端 drawBoxes（ui/static/app.js）**错**：位置做了模型 (x,y,z)→场景 (x,z,y) 轴交换
  （模型 z→three.js y=上），但 ``BoxGeometry(...size)`` 尺寸与端口 ``dir`` 向量**没做**
  同一交换——模型 y 尺寸 120 被当成场景高度，基板成竖立大板。修法：
  ``BoxGeometry(size[0], size[2], size[1])`` + ``Vector3(dir[0], dir[2], dir[1])``。

本文件：(1) 钉 spec 契约（薄轴=z）；(2) 用 Python 镜像 drawBoxes 的新/旧映射做最小复现
——旧映射复现"高度=120"的 bug、新映射断言 120×120 水平、0.508 竖直、金属贴板顶、馈线
到板边、端口方向随几何；(3) 源码钉子防回退（app.js 必须含轴交换写法且不再含旧写法）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.service.ui_service import model3d_for_params

APP_JS = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static" / "app.js"

# 场景轴约定（与 app.js drawBoxes / drawIsoMesh 注释一致）：x→x, z→上(y), y→深度(z)
SCENE_X, SCENE_UP, SCENE_DEPTH = 0, 1, 2


def _extent(box: dict) -> list[float]:
    return [abs(box["stop_mm"][i] - box["start_mm"][i]) for i in range(3)]


def _mid(box: dict) -> list[float]:
    return [(box["start_mm"][i] + box["stop_mm"][i]) / 2 for i in range(3)]


def _scene_size_fixed(size_model: list[float]) -> list[float]:
    """修复后 BoxGeometry(size[0], size[2], size[1])：与 position 同一轴交换。"""
    return [size_model[0], size_model[2], size_model[1]]


def _scene_size_legacy(size_model: list[float]) -> list[float]:
    """修复前 BoxGeometry(...size)：尺寸未交换（bug 复现用）。"""
    return list(size_model)


def _scene_pos(mid_model: list[float]) -> list[float]:
    """drawBoxes 一直如此：position.set(mid[0], mid[2], mid[1])。"""
    return [mid_model[0], mid_model[2], mid_model[1]]


def _scene_dir_fixed(d: list[float]) -> list[float]:
    return [d[0], d[2], d[1]]


@pytest.fixture()
def branchline():
    spec = model3d_for_params("branchline", {
        "arm_len_mm": 20.5, "series_w_mm": 1.87, "shunt_w_mm": 1.11})
    assert spec["ok"]
    return spec


def _box(spec: dict, name_prefix: str) -> dict:
    return next(b for b in spec["boxes"] if b["name"].startswith(name_prefix))


class TestSpecLayerContract:
    """spec 层轴序是对的：z=厚度轴（薄轴），x/y=板面——渲染内核不动。"""

    def test_substrate_thin_axis_is_z(self, branchline):
        sub = _box(branchline, "substrate")
        ext = _extent(sub)
        h = float(branchline["substrate"]["h_mm"])
        assert ext[0] == pytest.approx(120.0) and ext[1] == pytest.approx(120.0)
        assert ext[2] == pytest.approx(h) and 0 < h < 2.0
        assert ext.index(min(ext)) == 2, "基板薄轴必须是 z（模型坐标第 3 轴）"

    def test_metal_sits_on_substrate_top_plane(self, branchline):
        h = float(branchline["substrate"]["h_mm"])
        metals = [b for b in branchline["boxes"]
                  if b["material"] == "metal" and b["name"] != "ground"]
        assert metals
        for b in metals:
            assert b["start_mm"][2] == pytest.approx(h) and b["stop_mm"][2] == pytest.approx(h), \
                f"{b['name']} 金属面应在基板顶面 z=h"
        gnd = _box(branchline, "ground")
        assert gnd["start_mm"][2] == gnd["stop_mm"][2] == 0.0

    def test_feeds_reach_board_edge_and_ports_sit_there(self, branchline):
        # 四根馈线各自伸到板边 ±60，端口就在该板边上、方向朝外
        edges = {
            "feed_p1": (1, -60.0), "feed_p2": (0, 60.0),
            "feed_p3": (1, 60.0), "feed_p4": (0, -60.0),
        }
        for pfx, (axis, edge) in edges.items():
            b = _box(branchline, pfx)
            assert edge in (b["start_mm"][axis], b["stop_mm"][axis]), f"{pfx} 未到板边"
        ports = branchline["ports"]
        assert len(ports) == 4
        for p in ports:
            assert 60.0 in (abs(p["pos_mm"][0]), abs(p["pos_mm"][1])), "端口应在板边"
            assert p["dir"][2] == 0.0, "端口方向在板面内（不朝上/下）"
            # 方向朝外：与所在板边同号
            axis = 0 if abs(p["pos_mm"][0]) == 60.0 else 1
            assert p["dir"][axis] * p["pos_mm"][axis] > 0


class TestDrawBoxesAxisMapping:
    """Python 镜像 drawBoxes：旧映射复现 bug，新映射钉正确轴向。"""

    def test_legacy_mapping_reproduces_upright_board_bug(self, branchline):
        sub = _box(branchline, "substrate")
        legacy = _scene_size_legacy(_extent(sub))
        # 最小复现：修复前场景"上"方向尺寸=120（模型 y），基板竖立
        assert legacy[SCENE_UP] == pytest.approx(120.0)
        assert legacy[SCENE_DEPTH] == pytest.approx(float(branchline["substrate"]["h_mm"]))

    def test_fixed_mapping_board_is_flat(self, branchline):
        sub = _box(branchline, "substrate")
        size = _scene_size_fixed(_extent(sub))
        h = float(branchline["substrate"]["h_mm"])
        assert size[SCENE_X] == pytest.approx(120.0)
        assert size[SCENE_DEPTH] == pytest.approx(120.0)
        assert size[SCENE_UP] == pytest.approx(h), "0.51 必须是竖直方向"
        assert size.index(min(size)) == SCENE_UP

    def test_fixed_mapping_size_and_position_use_same_axes(self, branchline):
        """尺寸与位置同一交换：任一盒子场景包围盒 = 模型包围盒经同一置换。"""
        for b in branchline["boxes"]:
            size = _scene_size_fixed(_extent(b))
            pos = _scene_pos(_mid(b))
            lo = [pos[i] - size[i] / 2 for i in range(3)]
            hi = [pos[i] + size[i] / 2 for i in range(3)]
            # 场景 x ↔ 模型 x；场景上 ↔ 模型 z；场景深 ↔ 模型 y
            assert lo[SCENE_X] == pytest.approx(min(b["start_mm"][0], b["stop_mm"][0]))
            assert hi[SCENE_X] == pytest.approx(max(b["start_mm"][0], b["stop_mm"][0]))
            assert lo[SCENE_UP] == pytest.approx(min(b["start_mm"][2], b["stop_mm"][2]))
            assert hi[SCENE_UP] == pytest.approx(max(b["start_mm"][2], b["stop_mm"][2]))
            assert lo[SCENE_DEPTH] == pytest.approx(min(b["start_mm"][1], b["stop_mm"][1]))
            assert hi[SCENE_DEPTH] == pytest.approx(max(b["start_mm"][1], b["stop_mm"][1]))

    def test_fixed_mapping_metal_lies_on_top_of_board(self, branchline):
        h = float(branchline["substrate"]["h_mm"])
        sub_top = _scene_pos(_mid(_box(branchline, "substrate")))[SCENE_UP] + h / 2
        for b in branchline["boxes"]:
            if b["material"] != "metal" or b["name"] == "ground":
                continue
            assert _scene_pos(_mid(b))[SCENE_UP] == pytest.approx(sub_top), \
                f"{b['name']} 应贴在基板顶面（场景竖直坐标 = 板顶）"
            # 金属为零厚平面盒：交换后竖直尺寸为 0（前端 clamp 到 0.05 薄片），不再是 120 高墙
            assert _scene_size_fixed(_extent(b))[SCENE_UP] == pytest.approx(0.0)

    def test_fixed_port_dirs_lie_in_board_plane(self, branchline):
        for p in branchline["ports"]:
            d = _scene_dir_fixed(p["dir"])
            assert d[SCENE_UP] == pytest.approx(0.0), f"{p['name']} 端口箭头不得朝上/下"
            assert abs(d[SCENE_X]) + abs(d[SCENE_DEPTH]) == pytest.approx(1.0)
            # 端口位置与馈线同层同板边（位置一直是交换过的）
            pos = _scene_pos(p["pos_mm"])
            assert pos[SCENE_UP] == pytest.approx(float(branchline["substrate"]["h_mm"]))

    def test_legacy_port_dir_would_point_vertically(self, branchline):
        # 修复前 Vector3(...dir) 未交换：模型 y 向端口在场景里朝上/下（bug 形态）
        p1 = next(p for p in branchline["ports"] if p["name"].startswith("Port1"))
        assert p1["dir"][1] != 0.0 and list(p1["dir"])[SCENE_UP] != 0.0


class TestAppJsSourcePin:
    """源码钉子：防回退到未交换写法（唯一能对 JS 施加的静态回归）。"""

    def test_box_geometry_swaps_axes(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "new THREE.BoxGeometry(size[0], size[2], size[1])" in src
        assert "new THREE.BoxGeometry(...size)" not in src

    def test_port_dir_swaps_axes(self):
        src = APP_JS.read_text(encoding="utf-8")
        assert "new THREE.Vector3(p.dir[0], p.dir[2], p.dir[1])" in src
        assert "new THREE.Vector3(...p.dir)" not in src

    def test_position_mapping_unchanged(self):
        # 位置映射本来就对，修复只补尺寸/方向；位置写法不得被顺手改掉
        src = APP_JS.read_text(encoding="utf-8")
        assert "mesh.position.set(mid[0] - c[0], mid[2] - c[2], mid[1] - c[1])" in src
        assert "new THREE.Vector3(p.pos_mm[0] - c[0], p.pos_mm[2] - c[2], p.pos_mm[1] - c[1])" in src
