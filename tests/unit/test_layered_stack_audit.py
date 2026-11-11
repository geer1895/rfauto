"""layered_stack 族 openEMS 离线几何审计（T-Q26d 批 1，#212 制度化形态）。

审计手法（#212 教训制度化，test_template_geometry_audit 同款）：render →
exec 几何段（"# ── 求解 ──" 截断于 FDTD.Run 之前）→ CSXCAD 实测原语/
网格/端口。秒级、零仿真、零网络、零真机；全部判据量在 CSXCAD 实测对象
上（字符串/compile 门抓不住画法错误——#212 家族教训）。

判据一览：
① 腔挖除拓扑（分层围合）：腔足印内无介质原语（膜除外）、腔壁片落腔面；
② 金属连通性：strip+馈段单连通分量跨 ±DOM_X，与腔壁分量 DC 隔离；
③ 网格：特征线落格（#283）+ 全轴最小间距 >1µm（#152）+ #349 地板；
④ StripLinePort 端口：对称探针跨带面-腔壁、激励盒 #253 内缩、激励轮转；
⑤ 匹配馈：膜片足迹修至腔宽延续至 PML（siw v1 匹配端接口径）；
⑥ 渲染守卫 fail-loud（#266 特征分辨）+ 字节确定性（参数驱动几何）。

边界口径（如实登记）：FDTD 边界条件为 Cython 无属性面（SetBoundaryCond
无 getter），BC 断言落脚本文本钉（其余全 CSXCAD 实测）；HFSS 侧结构
断言在 test_layered_stack.py（plan 中间形态，批 1 零真机）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.layered_stack_spec import (
    ConductorSpec,
    LayeredStackSpec,
    layered_stack_layout,
)
from rfauto.adapters.oe_templates.render_layered_stack import (
    OE_FEED_SHIFT_NEAR,
    render_layered_stack,
)
from tests.unit import _geometry_audit_helpers as gh

#: 审计收敛档（repo 缺省档；#266 守卫 NEAR=0.1 ≤ strip/3=0.173 过守卫）
AUDIT_MESH_MM = 0.4

_CACHE: dict[tuple, tuple[dict[str, Any], list]] = {}


def load_geometry(mesh_mm: float | None = None,
                  excite_port: int = 1,
                  **overrides: Any) -> tuple[dict[str, Any], list]:
    """渲染 → exec 几何段 → (脚本全局字典, 原语列表)；同参会话内缓存。"""
    mesh = AUDIT_MESH_MM if mesh_mm is None else float(mesh_mm)
    key = (mesh, excite_port, tuple(sorted(
        (k, str(v)) for k, v in overrides.items())))
    cached = _CACHE.get(key)
    if cached is None:
        spec = LayeredStackSpec(**overrides) if overrides else LayeredStackSpec()
        text = render_layered_stack(spec, mesh_resolution_mm=mesh,
                                    excite_port=excite_port)
        marker = text.find("# ── 求解 ──")
        assert marker > 0, "脚本缺求解标记（审计截断点契约）"
        scope: dict[str, Any] = {"__name__": "__main__",
                                 "__file__": str(REPO / "_audit_sim.py")}
        exec(compile(text[:marker], "layered_stack_audit", "exec"), scope)
        cached = (scope, gh.extract_primitives(scope["CSX"]))
        _CACHE[key] = cached
    return cached


def _props_of(prims: list, prop: str) -> list:
    return [p for p in prims if p.prop == prop]


def _metal_prims(prims: list) -> list:
    return [p for p in prims if p.kind == "Metal"]


# ─── 1) exec 几何段 + CSXCAD 实测拓扑 ────────────────────────────────────────


class TestExecGeometry:
    def test_render_exec_geometry_segment(self):
        """渲染→exec（截断于 FDTD.Run）：材料卡/金属属性/双端口探针/
        单端口激励全建成（属性面实测，非字符串）。"""
        _scope, prims = load_geometry()
        kinds = {p.kind for p in prims}
        assert "Metal" in kinds and "Material" in kinds
        names = {p.prop for p in prims}
        assert "layered_stack_metal" in names
        assert "silicon" in names
        # 双端口 u/i 探针（StripLinePort 6 U + 2 I × 2 端口）+ 激励 2 盒
        u_probes = {n for n in names if n.startswith("port_ut_")}
        i_probes = {n for n in names if n.startswith("port_it_")}
        assert len(u_probes) == 12 and len(i_probes) == 4
        assert sum(1 for n in names if n.startswith("port_excite_")) == 2

    def test_boundary_text_pin_pml8_mur(self):
        """FDTD 边界=传播轴两端 PML_8 + 横向四 MUR（Cython 无 BC 属性面
        ——文本钉，其余判据全 CSXCAD 实测）。"""
        spec = LayeredStackSpec()
        text = render_layered_stack(spec, mesh_resolution_mm=AUDIT_MESH_MM)
        line = [ln for ln in text.splitlines()
                if "SetBoundaryCond" in ln and "PML_8" in ln]
        assert len(line) == 1
        assert ('["PML_8", "PML_8", "MUR", "MUR", "MUR", "MUR"]'
                in line[0])

    def test_byte_determinism(self):
        """同 spec 两次渲染逐字节一致（dict 序不泄漏；#212 参数驱动几何
        反向钉的前提）。"""
        a = render_layered_stack(LayeredStackSpec(),
                                 mesh_resolution_mm=AUDIT_MESH_MM)
        b = render_layered_stack(LayeredStackSpec(),
                                 mesh_resolution_mm=AUDIT_MESH_MM)
        assert a == b

    def test_params_drive_geometry(self):
        """参数驱动几何（反桩钉）：strip 宽扰动改变 CSXCAD 实测金属
        原语几何（0.52 → 0.60）。"""
        _, prims_a = load_geometry()
        _, prims_b = load_geometry(conductor=ConductorSpec(width_mm=0.6))

        def strip_body(prims: list, w_mm: float) -> list:
            return [p for p in _metal_prims(prims)
                    if abs(p.lo[0] + 2.55e-3) < 1e-12
                    and abs(p.hi[0] - 2.55e-3) < 1e-12
                    and abs(p.lo[2]) < 1e-12
                    and abs(p.hi[1] - p.lo[1] - w_mm * 1e-3) < 1e-12]

        sa = strip_body(prims_a, 0.52)
        sb = strip_body(prims_b, 0.60)
        assert sa and sb, "strip 体段原语识别失败"
        assert not strip_body(prims_a, 0.60), "参数未驱动几何（桩形态）"


# ─── 2) 腔挖除拓扑 + 网格守卫（#152/#283/#349）───────────────────────────────


class TestCavityAndMesh:
    def test_cavity_carve_topology(self):
        """CSXCAD 实测：腔足印内（|y|<0.45、−0.25<z<0.25、结构体全长）
        无介质原语，膜原语除外（导体层完整横跨）。"""
        scope, prims = load_geometry()
        l_half = float(scope["L_HALF"])
        cy0, cy1, cz0, cz1 = -0.45e-3, 0.45e-3, -0.25e-3, 0.25e-3
        for p in _props_of(prims, "silicon"):
            # 与腔体内部体积（各轴收缩 1µm 避面贴）相交的非膜原语=挖除失败
            lo = np.maximum(p.lo, [-l_half + 1e-6, cy0 + 1e-6, cz0 + 1e-6])
            hi = np.minimum(p.hi, [l_half - 1e-6, cy1 - 1e-6, cz1 - 1e-6])
            if not np.all(hi > lo):
                continue   # 不入腔内部
            is_membrane = (abs(p.lo[1] + 0.6e-3) < 1e-12
                           and abs(p.hi[1] - 0.6e-3) < 1e-12
                           and abs(p.lo[2] + 0.05e-3) < 1e-12
                           and abs(p.hi[2]) < 1e-12)
            assert is_membrane, f"腔内部残留介质原语: {p.prop} {p.lo} {p.hi}"

    def test_wall_sheets_on_cavity_faces_and_grid(self):
        """腔壁零厚片：顶/底壁 z=±0.25、侧壁 y=±0.45，全部落在网格线上
        （零厚面不入网格=原语丢失，#174 家族）。"""
        scope, prims = load_geometry()
        mesh = scope["mesh"]
        for ax, v in (("z", -0.25e-3), ("z", 0.25e-3),
                      ("y", -0.45e-3), ("y", 0.45e-3)):
            lines = np.sort(np.asarray(mesh.GetLines(ax), dtype=float))
            j = int(np.searchsorted(lines, v))
            on = (j < lines.size and abs(float(lines[j]) - v) <= 1e-9) or (
                j > 0 and abs(float(lines[j - 1]) - v) <= 1e-9)
            assert on, f"壁面 {ax}={v} 未落格"
        metal = _metal_prims(prims)
        assert any(abs(p.lo[2] - 0.25e-3) < 1e-12 and abs(p.hi[2] - 0.25e-3) < 1e-12
                   for p in metal), "顶壁片缺失"
        assert any(abs(p.lo[2] + 0.25e-3) < 1e-12 and abs(p.hi[2] + 0.25e-3) < 1e-12
                   for p in metal), "底壁片缺失"

    def test_bond_layer_sheets_at_layer_interfaces(self):
        """键合金属层（gold）零厚 sheet：layer1 落膜底（−0.05）、layer3 落
        带面（0）——层界面中已入网格的那一面（次胞面剔除规则）。键合
        sheet 并入 layered_stack_metal 单属性（设计口径），按几何签名
        识别：y∈[±0.45,±0.6] 侧段、零厚 z、x 跨结构全长。"""
        _scope, prims = load_geometry()
        bond = [p for p in _metal_prims(prims)
                if abs(p.lo[0] + 2.55e-3) < 1e-12
                and abs(p.hi[0] - 2.55e-3) < 1e-12
                and abs(p.lo[2] - p.hi[2]) < 1e-15
                and (abs(p.lo[1] + 0.6e-3) < 1e-12
                     or abs(p.hi[1] - 0.6e-3) < 1e-12)]
        assert len(bond) == 4, f"键合层 sheet 数 {len(bond)}（预期 4=两层侧段）"
        z_at = sorted({round(float(p.lo[2]), 12) for p in bond}
                      | {round(float(p.hi[2]), 12) for p in bond})
        assert z_at == [round(-0.05e-3, 12), 0.0]

    def test_mesh_feature_lines_and_no_near_coincident(self):
        """网格：布局特征线全部落格（#283）；全轴最小间距 >1µm（#152
        CFL 塌缩哨兵，GetLines 先排序——0.7.0 绑定插入序返回 #331 家族）。"""
        scope, _ = load_geometry()
        mesh = scope["mesh"]
        lay = layered_stack_layout(LayeredStackSpec())
        for ax in ("x", "y", "z"):
            lines = np.sort(np.asarray(mesh.GetLines(ax), dtype=float))
            gaps = np.diff(lines)
            assert gaps.size and bool(np.all(gaps > 1e-6)), \
                f"{ax} 轴含 ≤1µm 近重合线（#152）"
            feat = [float(v) * 1e-3 for v in lay["feature_lines_mm"][ax]]
            for v in feat:
                j = int(np.searchsorted(lines, v))
                on = (j < lines.size and abs(float(lines[j]) - v) <= 1e-9) or (
                    j > 0 and abs(float(lines[j - 1]) - v) <= 1e-9)
                assert on, f"特征线 {ax}={v} 未落格（#283）"

    def test_explicit_feature_floor_guard_in_layout(self):
        """#349 渲染期守卫：膜厚压到 5µm（次胞级）→ 特征线近撞 →
        ValueError fail-loud（不静默渲染 CFL 塌缩网格）。"""
        thin = LayeredStackSpec(
            layers=[("silicon", 0.25), ("gold", 0.003), ("silicon", 0.005),
                    ("gold", 0.003), ("silicon", 0.25)])
        with pytest.raises(ValueError, match="地板"):
            render_layered_stack(thin, mesh_resolution_mm=AUDIT_MESH_MM)


# ─── 3) 金属连通性（strip 网络与腔壁网络 DC 隔离）───────────────────────────


class TestMetalConnectivity:
    def test_strip_network_spans_domain_and_isolated_from_walls(self):
        """strip+馈段=单连通分量（体段+双端口馈盒在 ±L/2 搭接）跨
        [−DOM_X, +DOM_X]；腔壁=另一分量（strip 悬置不触壁=器件定义
        性质；键合层 sheet=第三类孤岛）。"""
        scope, prims = load_geometry()
        conductors, labels = gh.conductor_labels(prims)
        n_comp = len(set(labels))
        assert n_comp >= 2, "strip 网络与腔壁网络须分离（悬置定义）"
        dom_x = float(scope["DOM_X"])
        strip_pt = np.array([0.0, 0.0, 0.0])   # 带面中心
        strip_comp = gh.containing_labels(strip_pt, conductors, labels)
        assert strip_comp, "带面中心悬空（strip 断链）"
        feed_pt = np.array([-dom_x + 1e-6, 0.0, 0.0])   # 馈段近域界
        feed_comp = gh.containing_labels(feed_pt, conductors, labels)
        assert feed_comp & strip_comp, "馈段未与 strip 导通（端口断链）"
        strip_prims = [p for p, lb in zip(conductors, labels, strict=True)
                       if lb in strip_comp]
        lo_strip = min(float(p.lo[0]) for p in strip_prims)
        hi_strip = max(float(p.hi[0]) for p in strip_prims)
        assert lo_strip <= -dom_x + 1e-9 and hi_strip >= dom_x - 1e-9, \
            "strip 网络未贯通全域（匹配馈断链）"
        # 腔壁分量（顶壁面中心点）与 strip 分量不交
        wall_pt = np.array([0.0, 0.0, 0.25e-3])   # 顶壁中心
        wall_comp = gh.containing_labels(wall_pt, conductors, labels)
        assert wall_comp and not (wall_comp & strip_comp), \
            "strip 与腔壁导通（短路——悬置线定义破坏）"


# ─── 4) 匹配馈延续（siw v1 匹配端接口径）────────────────────────────────────


class TestMatchedFeed:
    def test_membrane_feed_boxes_flush_with_walls(self):
        """膜片三段：体段全宽 [−L/2, L/2] + 两馈段（足印修至腔宽 ±0.45）
        延续至 ±DOM_X——馈区截面=腔截面精确 match。"""
        scope, prims = load_geometry()
        dom_x = float(scope["DOM_X"])
        l_half = float(scope["L_HALF"])
        sil = _props_of(prims, "silicon")
        body = [p for p in sil if abs(p.lo[1] + 0.6e-3) < 1e-12
                and abs(p.hi[1] - 0.6e-3) < 1e-12
                and abs(p.lo[2] + 0.05e-3) < 1e-12]
        feed = [p for p in sil if abs(p.lo[1] + 0.45e-3) < 1e-12
                and abs(p.lo[2] + 0.05e-3) < 1e-12]
        assert body and abs(body[0].lo[0] + l_half) < 1e-12 \
            and abs(body[0].hi[0] - l_half) < 1e-12, "膜体段未覆盖结构全长"
        assert len(feed) == 2, f"馈段膜片数 {len(feed)}（预期 2）"
        ends = sorted(abs(float(p.hi[0])) for p in feed)
        assert abs(ends[0] - l_half) < 1e-12 and abs(ends[1] - dom_x) < 1e-12, \
            "馈段膜片未延续至域界（匹配馈断链）"
        for p in feed:
            assert abs(p.hi[1] - 0.45e-3) < 1e-12, "馈段膜足印未修至腔宽"


# ─── 4b) 馈段四壁延续（Q-X14 Fix1/2，qx12 调查 RC1 修复 CSXCAD 实测钉）───────


class TestFeedWallContinuation:
    """Q-X14 Fix1（四壁馈段延续）+ Fix2（探针面金属覆盖守卫）CSXCAD 实测。

    RC1（qx12 INVESTIGATION §0）：修复前探针面（x=±(DOM_X−mp)）处
    z=±height 地平面金属命中=0——探针拾取无回流开域场，β/Z_ref 排垃圾。
    修复判据全部在 CSXCAD 实测原语上（#212：字符串/compile 门抓不住画法
    错误）；数据面/守卫 fail-loud 钉在 test_layered_stack.py。
    """

    def test_feed_wall_boxes_csxcad_single_source(self):
        """每面布局壁在两个馈段 x 区间恰有 1 个 CSXCAD 金属原语，(y,z)
        与壁盒字面逐位一致（单源直通），x 恰为 [±L_HALF,±DOM_X]。"""
        scope, prims = load_geometry()
        dom_x = float(scope["DOM_X"])
        l_half = float(scope["L_HALF"])
        lay = layered_stack_layout(LayeredStackSpec())
        metal = _metal_prims(prims)
        for wall in lay["metal_sheets"]:
            _bx0, _bx1, y0, y1, z0, z1 = (float(v) * 1e-3
                                          for v in wall["box"])
            for x0, x1 in ((l_half, dom_x), (-dom_x, -l_half)):
                hits = [p for p in metal
                        if abs(p.lo[0] - min(x0, x1)) < 1e-12
                        and abs(p.hi[0] - max(x0, x1)) < 1e-12
                        and abs(p.lo[1] - min(y0, y1)) < 1e-12
                        and abs(p.hi[1] - max(y0, y1)) < 1e-12
                        and abs(p.lo[2] - min(z0, z1)) < 1e-12
                        and abs(p.hi[2] - max(z0, z1)) < 1e-12]
                assert len(hits) == 1, \
                    f"{wall['name']} 馈段 x∈[{x0}, {x1}] 命中 {len(hits)}（预期 1）"

    def test_probe_planes_metal_covered_csxcad(self):
        """探针面金属覆盖（RC1 静态判据实测）：双端口探针面
        x=±(DOM_X−measplane_shift) 处 z=STRIP_Z±PORT_HEIGHT 地平面金属
        命中 ≥1 且覆盖 y∈[STRIP_Y0,STRIP_Y1]——修复前四组合全 0。"""
        scope, prims = load_geometry()
        dom_x = float(scope["DOM_X"])
        sz = float(scope["STRIP_Z"])
        h = float(scope["PORT_HEIGHT"])
        sy0, sy1 = float(scope["STRIP_Y0"]), float(scope["STRIP_Y1"])
        boxes = []
        for p in _metal_prims(prims):
            boxes.append((p.lo, p.hi))

        def hits(xp: float, zt: float) -> int:
            return sum(1 for lo, hi in boxes
                       if lo[0] - 1e-12 <= xp <= hi[0] + 1e-12
                       and lo[2] - 1e-12 <= zt <= hi[2] + 1e-12
                       and lo[1] <= sy1 and hi[1] >= sy0)

        for ptag, mp in (("p1", float(scope["_port1"].measplane_shift)),
                         ("p2", float(scope["_port2"].measplane_shift))):
            for sgn, stag in ((-1.0, "n"), (1.0, "p")):
                for ztag, zt in (("zp", sz + h), ("zn", sz - h)):
                    n = hits(sgn * (dom_x - mp), zt)
                    assert n > 0, f"{ptag}_{stag}_{ztag} 地平面命中=0（RC1）"

    def test_wall_component_spans_full_domain_still_isolated(self):
        """连通性：腔壁分量（含馈段延续）x 贯通 [−DOM_X,+DOM_X]；与
        strip 分量仍 DC 隔离（馈区壁贴近 strip 但零接触——悬置定义）。"""
        scope, prims = load_geometry()
        dom_x = float(scope["DOM_X"])
        conductors, labels = gh.conductor_labels(prims)
        strip_comp = gh.containing_labels(np.array([0.0, 0.0, 0.0]),
                                          conductors, labels)
        assert strip_comp, "strip 断链"
        # 体区壁面中心 + 馈区壁面点同属壁分量（馈段延续并网）
        wall_body = gh.containing_labels(np.array([0.0, 0.0, 0.25e-3]),
                                         conductors, labels)
        wall_feed = gh.containing_labels(
            np.array([dom_x - 1e-6, 0.0, 0.25e-3]), conductors, labels)
        assert wall_body and wall_feed == wall_body, \
            "馈段壁延续未并入腔壁分量（延续断链）"
        assert not (wall_body & strip_comp), \
            "馈段壁延续与 strip 导通（短路——悬置定义破坏）"
        wall_prims = [p for p, lb in zip(conductors, labels, strict=True)
                      if lb in wall_body]
        lo_wall = min(float(p.lo[0]) for p in wall_prims)
        hi_wall = max(float(p.hi[0]) for p in wall_prims)
        assert lo_wall <= -dom_x + 1e-9 and hi_wall >= dom_x - 1e-9, \
            "腔壁分量未贯通全域（匹配馈四壁延续缺失）"


# ─── 5) StripLinePort 端口（探针/激励 #253/轮转）────────────────────────────


class TestStripLinePorts:
    def test_voltage_probes_span_strip_to_walls(self):
        """U 探针（对称 ±height）：每端口存在 strip→顶壁（z 0..0.25）与
        strip→底壁（z −0.25..0）探针盒（height=带面-腔壁距离）。"""
        _scope, prims = load_geometry()
        probes = [p for p in prims
                  if p.prop.startswith("port_ut_") and p.prop.endswith(("1", "2"))]
        up = [p for p in probes
              if abs(float(p.lo[2])) < 1e-12
              and abs(float(p.hi[2]) - 0.25e-3) < 1e-9]
        dn = [p for p in probes
              if abs(float(p.hi[2])) < 1e-12
              and abs(float(p.lo[2]) + 0.25e-3) < 1e-9]
        assert len(up) >= 3 and len(dn) >= 3, \
            f"对称电压探针缺失（up={len(up)}, dn={len(dn)}）"

    def test_excitation_inset_ge_2base_and_rotation(self):
        """激励盒 #253 内缩（10·NEAR=2.5·BASE ≥ 2·BASE）；excite_port=1
        激励在 port1 侧（−DOM_X+10·NEAR），轮转 excite_port=2 反侧。"""
        scope, prims = load_geometry()
        dom_x = float(scope["DOM_X"])
        base = float(scope["BASE"])
        near = float(scope["NEAR"])
        exc = [p for p in prims if p.prop.startswith("port_excite_")]
        assert exc, "激励盒缺失"
        xs = [float(p.lo[0]) for p in exc]
        expected = -dom_x + OE_FEED_SHIFT_NEAR * near
        assert all(abs(x - expected) <= 1e-9 for x in xs), \
            f"激励位置 {xs} ≠ port1 侧 {expected}"
        inset = expected + dom_x
        assert inset >= 2.0 * base - 1e-15, f"#253 内缩不足 {inset}"
        # 轮转：excite_port=2 → 激励在 port2 侧
        scope2, prims2 = load_geometry(excite_port=2)
        dom_x2 = float(scope2["DOM_X"])
        near2 = float(scope2["NEAR"])
        exc2 = [p for p in prims2 if p.prop.startswith("port_excite_")]
        expected2 = dom_x2 - OE_FEED_SHIFT_NEAR * near2
        assert all(abs(float(p.lo[0]) - expected2) <= 1e-9 for p in exc2), \
            "激励未轮转至 port2 侧"

    def test_ports_measured_inside_feed(self):
        """测量面在馈段内（MeasPlaneShift=FEED/3）：U 探针 x 位置 ∈
        (−DOM_X, −L/2)（port1）——退嵌参考面口径。"""
        scope, prims = load_geometry()
        dom_x = float(scope["DOM_X"])
        l_half = float(scope["L_HALF"])
        probes = [p for p in prims if p.prop.startswith("port_ut_1")]
        assert probes
        for p in probes:
            x = float(p.lo[0])
            assert -dom_x < x < -l_half, f"port1 探针 x={x} 不在馈段内"


# ─── 6) 渲染守卫 fail-loud + 闭式锚嵌脚本 ───────────────────────────────────


class TestGuardsAndAnchor:
    def test_mesh_guard_rejects_coarse_base(self):
        """#266 特征分辨守卫：base=2mm → NEAR=0.5 > strip/3 → ValueError。"""
        with pytest.raises(ValueError, match="#266 特征分辨守卫"):
            render_layered_stack(LayeredStackSpec(), mesh_resolution_mm=2.0)

    def test_closed_form_anchor_embedded(self):
        """闭式锚（确定性内核）嵌入脚本 meta 块：εeff/Z0 与
        _suspended_stripline_ri(0.52, 0.50, 0.05, 11.9) 重算一致（§2.1
        实测锚 50Ω 点；铁律 7 数值出处单源）。"""
        from rfauto.core.calculators import _suspended_stripline_ri

        eps_eff, z0 = _suspended_stripline_ri(0.52, 0.50, 0.05, 11.9)
        text = render_layered_stack(LayeredStackSpec(),
                                    mesh_resolution_mm=AUDIT_MESH_MM)
        assert repr(round(eps_eff, 12)) in text or repr(eps_eff) in text
        assert repr(round(z0, 12)) in text or repr(z0) in text
        assert eps_eff == pytest.approx(1.59, rel=0.02)
        assert z0 == pytest.approx(50.2, rel=0.02)

    def test_excite_port_domain_rejected(self):
        """越域激励显式拒绝（双端口模板 excite_port ∈ {1,2}）。"""
        with pytest.raises(ValueError, match="excite_port"):
            render_layered_stack(LayeredStackSpec(), excite_port=3)
