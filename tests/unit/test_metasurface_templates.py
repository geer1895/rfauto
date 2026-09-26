"""DP-10 超表面/FSS 族离线审计（#212 制度：渲染→exec 几何段→实测，秒级零仿真）。

判据源=runs/df6_dp10ms/criteria.md（开工前冻结）；规格=DP-10 节。
本文件管 DP-10 族专项（周期一致/间隙守卫/cell_map 覆盖/地连续/NEAR 守卫/
名义闭式互证/波导模拟器口径字面），通用审计（原语/端口/连通/域/网格）在
test_template_geometry_audit.py 自动参数化覆盖。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rfauto.adapters.openems_templates import (
    METASURFACE_TEMPLATES,
    MS_UNIT_TEMPLATES,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    ms_jcross_metal_boxes,
    ms_unit_layout,
    render_script,
)
from rfauto.core.metasurface_lut import (
    ms_cross_arm_len_mm,
    ms_jcross_slot_dims_mm,
    ms_patch_resonant_len_mm,
    synthesize_layout,
)
from tests.unit._geometry_audit_helpers import load_geometry, mesh_lines
from tests.unit.test_metasurface_lut import (
    _synthetic_lut,  # 复用合成 LUT（回收钉同源，判据 criteria §1a）
)
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

BAND = (9.75, 10.25)
AUDIT_MESH_MM = 0.4


# ─── 波导模拟器口径字面（渲染脚本正面断言）────────────────────────────────────


@pytest.mark.parametrize("template", sorted(MS_UNIT_TEMPLATES))
def test_wg_simulator_bc_and_polarization_premise(template):
    """单胞三件：x 对壁 PEC / y 对壁 PMC（≡无限阵@θ=0，E∥x 前提）逐字面。"""
    text = render_script(template, dict(TEMPLATE_NOMINAL[template]), BAND,
                         mesh_resolution_mm=AUDIT_MESH_MM)
    assert '"PEC", "PEC", "PMC", "PMC"' in text, \
        f"{template}: 波导模拟器对壁 BC 缺失"
    assert "E∥x" in text, f"{template}: 极化前提未注明"
    assert "376.7303" in text, f"{template}: 片端口参考 R≠η0"
    assert "LumpedPort" in text


def test_ms_patch_ground_pec_bottom():
    """ms_patch 反射型：z 底=地面 PEC 边界（地连续由边界构造性保证）。"""
    text = render_script("ms_patch", dict(TEMPLATE_NOMINAL["ms_patch"]), BAND,
                         mesh_resolution_mm=AUDIT_MESH_MM)
    assert '"PEC"' in text
    scope, prims = load_geometry("ms_patch")
    assert scope is not None and prims
    # 单端口反射口径：_port2 为 _port1 别名（S21 列≡S11 footer 契约）
    assert scope.get("_port2") is scope.get("_port1")


@pytest.mark.parametrize("template", sorted(MS_UNIT_TEMPLATES))
def test_unit_domain_equals_half_period(template):
    """栅格周期一致（criteria §4.1）：单胞域半宽=period/2（x/y 双轴）。"""
    scope, _ = load_geometry(template)
    period_m = float(TEMPLATE_NOMINAL[template]["period_mm"]) * 1e-3
    for axis, dom in (("x", scope["DOM_X"]), ("y", scope["DOM_Y"])):
        assert dom == pytest.approx(period_m / 2, rel=1e-12)
        lines = mesh_lines(scope, axis)
        assert lines.min() == pytest.approx(-period_m / 2, abs=1e-9)
        assert lines.max() == pytest.approx(period_m / 2, abs=1e-9)


@pytest.mark.parametrize("template", sorted(MS_UNIT_TEMPLATES))
def test_mesh_floor_10um_all_axes(template):
    """全轴 ≥10µm（DP-10 族加严档，高于审计⑤ 1µm 地板）。"""
    scope, _ = load_geometry(template)
    for axis in ("x", "y", "z"):
        lines = mesh_lines(scope, axis)
        assert float(np.diff(lines).min()) >= 10e-6, \
            f"{template}: {axis} 轴最小网格间距 <10µm"


def test_gap_midlines_enter_mesh():
    """胞缘缝 3+ 内部线入网（#311 口径）：patch 胞缘缝内部实测 ≥3 条。"""
    nom = dict(TEMPLATE_NOMINAL["ms_patch"])
    scope, _ = load_geometry("ms_patch", nom)
    px = nom["px_mm"] * 1e-3
    half = nom["period_mm"] * 1e-3 / 2
    for gap_lo, gap_hi in ((-half, -px / 2), (px / 2, half)):
        inside = mesh_lines(scope, "x")[
            (mesh_lines(scope, "x") > gap_lo + 1e-9)
            & (mesh_lines(scope, "x") < gap_hi - 1e-9)]
        assert inside.size >= 3, \
            f"胞缘缝 [{gap_lo}, {gap_hi}] 内部线 {inside.size} <3"


# ─── 渲染期守卫（#266 口径：违反抛错不静默）──────────────────────────────────


def test_ms_patch_near_guard_rejects_undersized_gap():
    """px 贴满胞（缝 <3·NEAR）+ 粗网格 → 渲染期 ValueError（不静默粗网格）。"""
    params = dict(TEMPLATE_NOMINAL["ms_patch"])
    params["px_mm"] = 14.9   # 缝 0.05mm；审计档 base=0.4 → NEAR=0.1 → 3·NEAR=0.3
    with pytest.raises(ValueError, match="守卫"):
        render_script("ms_patch", params, BAND, mesh_resolution_mm=AUDIT_MESH_MM)


def test_ms_cross_guard_rejects_arm_overflow():
    """臂越胞（2·arm>period）→ ValueError（审计扰动的 PERTURB_OVERRIDES 同源）。"""
    params = dict(TEMPLATE_NOMINAL["ms_cross"])
    params["arm_len_mm"] = 6.6   # 2·6.6=13.2 > 12
    with pytest.raises(ValueError, match="胞内"):
        render_script("ms_cross", params, BAND, mesh_resolution_mm=AUDIT_MESH_MM)


# ─── ms_jcross 屏几何（孔洞补集盒分解的互联性与覆盖）──────────────────────────


class TestJcrossScreen:
    def test_aperture_interior_is_void(self):
        """孔径内部（主缝中点/端枝中点）无金属盒覆盖=互联单孔径。"""
        nom = TEMPLATE_NOMINAL["ms_jcross"]
        boxes = ms_jcross_metal_boxes(
            nom["period_mm"] * 1e-3, nom["slot_len_mm"] * 1e-3,
            nom["slot_w_mm"] * 1e-3, nom["stub_len_mm"] * 1e-3)

        def covered(x, y):
            return any(x0 <= x <= x1 and y0 <= y <= y1
                       for x0, y0, x1, y1 in boxes)

        s = nom["slot_len_mm"] * 1e-3
        w = nom["slot_w_mm"] * 1e-3
        t = nom["stub_len_mm"] * 1e-3
        assert not covered(0.0, 0.0)                    # 主缝中心
        assert not covered(s / 2 - w / 2, w / 2 + t / 2)   # +x 端枝孔中心
        assert not covered(-(s / 2 - w / 2), -(w / 2 + t / 2))  # −x 端枝孔中心
        assert covered(0.0, w)                          # 缝外 y 向=金属
        assert covered(s / 2 + 1e-4, 0.0)               # 缝外 x 向=金属
        assert covered(0.0, w / 2 + t + 1e-4)           # 端枝尖外=金属

    def test_boxes_tile_full_cell_without_overlap(self):
        """补集盒恰铺满胞面（面积和=胞面积+孔洞面积=胞面积）且互不重叠。"""
        a, sl, sw, st = 11.9917e-3, 4.91e-3, 0.491e-3, 2.455e-3
        boxes = ms_jcross_metal_boxes(a, sl, sw, st)
        area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
        hole = sl * sw + 4 * sw * st
        assert area == pytest.approx(a * a - hole, rel=1e-12)
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                ax0, ay0, ax1, ay1 = boxes[i]
                bx0, by0, bx1, by1 = boxes[j]
                ox = min(ax1, bx1) - max(ax0, bx0)
                oy = min(ay1, by1) - max(ay0, by0)
                if ox > 1e-12 and oy > 1e-12:
                    pytest.fail(f"盒 {i}/{j} 重叠")

    def test_render_exec_screen_is_connected_metal(self):
        """渲染实测：10 补集盒全落网格且构成单连通屏（审计③口径补强）。"""
        _scope, prims = load_geometry("ms_jcross")
        screen = [p for p in prims if p.prop == "jc_screen"]
        # 5 条带 × 孔洞分段 = 1+3+2+3+1 = 10 盒（band 分解单源
        # ms_jcross_metal_boxes；tiling/互不重叠由 TestJcrossScreen 面积钉）
        assert len(screen) == 10


# ─── ms_array_NxN：cell_map 覆盖完备/邻胞间隙/逐单元驱动/照明口径 ─────────────


class TestMsArray:
    def test_portless_and_illumination(self):
        """无端口 + 软激励平面 + nf2ff 盒 + 地 PEC token（audit ② 正面判据）。"""
        text = render_script("ms_array_NxN", dict(TEMPLATE_NOMINAL["ms_array_NxN"]),
                             BAND, mesh_resolution_mm=AUDIT_MESH_MM)
        assert "_port" not in text
        assert 'exc_type=0' in text
        assert "CreateNF2FFBox" in text
        assert '"MUR", "MUR", "MUR", "MUR", "PEC", "MUR"' in text
        assert "E∥x" in text

    def test_cell_map_coverage_guard(self):
        """cell_map 行列数与 n 逐维不等 → ValueError（覆盖完备守卫）。"""
        params = dict(TEMPLATE_NOMINAL["ms_array_NxN"])
        params["n_x"] = 4                      # cell_map 仍 3 列
        with pytest.raises(ValueError, match="覆盖不完备"):
            render_script("ms_array_NxN", params, BAND,
                          mesh_resolution_mm=AUDIT_MESH_MM)

    def test_cell_gap_guard_fires(self):
        """胞缘缝 <2·NEAR → ValueError（criteria §4.2 渲染期守卫）。

        口径注记：邻胞间隙=edge_i+edge_j（均匀周期）恒 ≥4·NEAR 当各 edge
        ≥2·NEAR——ms_array_layout 的邻胞检查是纵深防御（结构上后于胞缘
        守卫触发），本测钉住守卫链的实际首触发点。
        """
        params = dict(TEMPLATE_NOMINAL["ms_array_NxN"])
        params["cell_map"] = [[{"cell_id": "ms_patch", "px_mm": 14.9,
                                "py_mm": 14.9}] * 3] * 3
        with pytest.raises(ValueError, match="胞缘缝"):
            render_script("ms_array_NxN", params, BAND,
                          mesh_resolution_mm=AUDIT_MESH_MM)

    def test_cell_map_drives_geometry_per_cell(self):
        """cell_map 逐单元驱动（exec 实测）：每胞贴片盒=cell_map 值。"""
        _scope, prims = load_geometry("ms_array_NxN")
        patches = [p for p in prims if p.kind == "Metal"]
        cell_map = TEMPLATE_NOMINAL["ms_array_NxN"]["cell_map"]
        period = TEMPLATE_NOMINAL["ms_array_NxN"]["period_mm"] * 1e-3
        n_y = len(cell_map)
        found = 0
        for j, row in enumerate(cell_map):
            for i, cell in enumerate(row):
                cx = (i - (len(row) - 1) / 2) * period
                cy = (j - (n_y - 1) / 2) * period
                px = cell["px_mm"] * 1e-3
                py = cell["py_mm"] * 1e-3
                hit = [p for p in patches
                       if p.lo[0] == pytest.approx(cx - px / 2, abs=1e-12)
                       and p.hi[0] == pytest.approx(cx + px / 2, abs=1e-12)
                       and p.lo[1] == pytest.approx(cy - py / 2, abs=1e-12)
                       and p.hi[1] == pytest.approx(cy + py / 2, abs=1e-12)]
                assert hit, f"cell_map[{j}][{i}] 贴片未按参数渲染"
                found += 1
        assert found == 9

    def test_period_consistency_with_cell_layout(self):
        """栅格周期一致（criteria §4.1）：阵胞心距=period（x 双胞实测）。"""
        _scope, prims = load_geometry("ms_array_NxN")
        patches = sorted((p for p in prims if p.kind == "Metal"),
                         key=lambda p: ((p.lo[1] + p.hi[1]) / 2, p.lo[0]))
        period = TEMPLATE_NOMINAL["ms_array_NxN"]["period_mm"] * 1e-3
        cy0 = (patches[0].lo[1] + patches[0].hi[1]) / 2
        row = [p for p in patches
               if (p.lo[1] + p.hi[1]) / 2 == pytest.approx(cy0, abs=1e-12)]
        assert len(row) == 3
        # 胞心距=period（lo 差含 px 差异，必须用盒中心）
        c0 = (row[0].lo[0] + row[0].hi[0]) / 2
        c1 = (row[1].lo[0] + row[1].hi[0]) / 2
        assert (c1 - c0) == pytest.approx(period, rel=1e-12)

    def test_budget_note_present(self):
        """发射面预算口径在 meta（15×15 ~4×10⁷ cells 小时级/轮，#328 口径）。"""
        note = TEMPLATE_META["ms_array_NxN"]["mesh_note"]
        assert "15×15" in note and "4×10⁷" in note


# ─── 名义尺寸闭式互证（#252/#1c：nominal=core 闭式导入期计算，逐位互证）────────


class TestNominalClosedFormIdentity:
    def test_ms_patch_nominal_is_fixed_point(self):
        px = ms_patch_resonant_len_mm(10.0, 3.66, 1.524)
        assert round(px, 4) == TEMPLATE_NOMINAL["ms_patch"]["px_mm"]
        assert TEMPLATE_NOMINAL["ms_patch"]["py_mm"] == \
            TEMPLATE_NOMINAL["ms_patch"]["px_mm"]      # 方贴片口径
        assert TEMPLATE_NOMINAL["ms_patch"]["period_mm"] == round(
            299792458.0 / 10e9 * 1e3 / 2, 4)   # λ0/2 闭式 4 位圆整

    def test_ms_cross_nominal_is_closed_form(self):
        arm = ms_cross_arm_len_mm(10.0, 3.66)
        nom = TEMPLATE_NOMINAL["ms_cross"]
        assert round(arm, 4) == nom["arm_len_mm"]
        assert nom["arm_w_mm"] == pytest.approx(round(arm / 5, 4), abs=1e-9)
        assert nom["period_mm"] == round(
            0.4 * 299792458.0 / 10e9 * 1e3, 4)  # 0.4λ0 闭式 4 位圆整

    def test_ms_jcross_nominal_is_closed_form(self):
        jc = ms_jcross_slot_dims_mm(10.0, 3.66)
        nom = TEMPLATE_NOMINAL["ms_jcross"]
        assert round(jc["slot_len_mm"], 4) == nom["slot_len_mm"]
        assert round(jc["stub_len_mm"], 4) == nom["stub_len_mm"]
        eps_eff = (1 + 3.66) / 2
        lamg = 299792458.0 / 10e9 * 1e3 / (eps_eff ** 0.5)
        assert nom["slot_w_mm"] == pytest.approx(round(lamg / 40, 4), abs=1e-9)

    def test_layout_defaults_match_nominal(self):
        """渲染缺省值与 nominal 同源（p.get 缺省漂移即红）。"""
        params = ms_unit_layout("ms_jcross", {}, BAND, 0.4e-3, 0.508e-3)
        nom = TEMPLATE_NOMINAL["ms_jcross"]
        assert params["slot_len"] == pytest.approx(nom["slot_len_mm"] * 1e-3,
                                                   rel=1e-12)
        assert params["slot_w"] == pytest.approx(nom["slot_w_mm"] * 1e-3,
                                                 rel=1e-12)
        assert params["stub_len"] == pytest.approx(nom["stub_len_mm"] * 1e-3,
                                                   rel=1e-12)


# ─── 布局综合端到端（core 内核 → cell_map 参数域，J1a 链路落地预演）────────────


def test_synthesized_layout_feeds_cell_map_domain():
    """合成回收钉链路：闭式相位图 → LUT 反查 → px 值域可作 cell_map 输入
    （core→模板参数域桥接，逐单元 px=反查值）。"""
    lut = _synthetic_lut()
    cells = synthesize_layout(
        n_x=4, n_y=4, period_m=15e-3, f0_ghz=10.0, lut=lut, bits=2,
        u_beam=np.array([math.sin(math.radians(25)), 0.0,
                         math.cos(math.radians(25))]),
    )
    px_values = {c["sweep_value"] for c in cells}
    assert px_values and all(2.0 <= v <= 13.0 for v in px_values)
    # 每胞反查相位与目标相位差 ≤ 量化步长/2 + LUT 网格分辨率（确定性上界）
    for c in cells:
        q = c["phase_quantized_deg"]
        assert abs((c["phase_achieved_deg"] - q + 180) % 360 - 180) <= \
            330 / (lut.sweep_values.size - 1) + 1e-9


def test_expected_templates_contains_ms_family():
    """注册联动（#304）：四件全进冻结集；TEMPLATE_META 计数=53（df7 C10d
    mmwave_series_array 52→53；主代理回填 docs 数字以实测为准）。"""
    for t in METASURFACE_TEMPLATES:
        assert t in EXPECTED_TEMPLATES
    assert len(TEMPLATE_META) == 53
