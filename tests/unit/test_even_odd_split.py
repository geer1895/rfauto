"""DP-14 Y1 奇偶模分解单测：core/even_odd_split 内核 + service/even_odd_service。

判据书 runs/df6_dp14y1/criteria.md（判据预声明）；口径权威
docs/rf_template_references.md §13.1/§13.2。裁判=独立来源（#206 纪律）：

- 闭式回收（判据 a）：coupled_microstrip_even_odd_ohm（KJ 闭式，只读复用）造
  (Z0e,Z0o) → 测试内自建半模型 2 端口装配（不 import openems_templates 装配
  内核）→ 叠加 vs Pozar §7.6 闭式逐位（同步）+ √(Z_sc·Z_oc) 回读门 ≤1%
  （非同步）；
- 13.2 单节映射复现（判据 b）：合成布局走内核几何裁剪（跨面支臂→λ/8 半桩）
  → 偶/奇叠加复现 Pozar S21=−j/√2、S31=−1/√2；
- 几何守卫（判据 c）：镜像断言逐位（split→镜像重装配==恒等）、非对称显式
  SymmetryError、孤儿端口、跨面端口裁半。

零 CSXCAD/openEMS 依赖（纯离线；conftest skip 清单无需登记）。
"""

from __future__ import annotations

import cmath
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

C0 = 2.99792458e8
F0 = 2.5e9

# 判据书 §1 预声明锚（coupled_microstrip_even_odd_ohm @cline 标称点实测）
Z0E_ANCHOR = 69.37088231385582
Z0O_ANCHOR = 36.03866991398955
ERE_E_ANCHOR = 2.9921589396848027
ERE_O_ANCHOR = 2.466280526755509


# ─── 测试内独立装配（裁判；不 import 被测装配内核）───────────────────────────

def _tl_abcd(z0: float, theta: float):
    """均匀线 ABCD（教科书恒等式，测试内独立构造）。"""
    c, s = cmath.cos(theta), cmath.sin(theta)
    return (c, 1j * z0 * s), (1j * s / z0, c)


def _shunt_abcd(y: complex):
    return (1.0, 0.0), (y, 1.0)


def _cascade(m1, m2):
    (a1, b1), (c1, d1) = m1
    (a2, b2), (c2, d2) = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2), (c1 * a2 + d1 * c2,
                                                    c1 * b2 + d1 * d2)


def _abcd_gamma_t(m, z_ref: float = 50.0):
    (a, b), (c, d) = m
    den = a + b / z_ref + c * z_ref + d
    return (a + b / z_ref - c * z_ref - d) / den, 2.0 / den


def _tl_s(z0: float, theta: float, z_ref: float = 50.0):
    """均匀线 2 端口 S（参考 z_ref；独立闭式）。"""
    g = (z0 - z_ref) / (z0 + z_ref)
    e = cmath.exp(-2j * theta)
    s11 = g * (1.0 - e) / (1.0 - g * g * e)
    s12 = (1.0 - g * g) * cmath.exp(-1j * theta) / (1.0 - g * g * e)
    return s11, s12


def _zin_abcd(m, z_load: float | None, z_ref: float = 50.0):
    """2 端口 ABCD 在负载 z_load（None=开路）下的输入阻抗。"""
    (a, b), (c, d) = m
    if z_load is None:
        return a / c
    return (a * z_load + b) / (c * z_load + d)


def _service_cline():
    from rfauto.service import even_odd_service as svc

    return svc.even_odd_split("cline_coupler")


def _cline_length_m(report) -> float:
    """耦合段物理长（半模型 line_a 盒 y 跨度，米）。"""
    for b in report["half_models"]["even"]["boxes"]:
        if b["name"] == "line_a":
            return float(b["y1"]) - float(b["y0"])
    raise AssertionError("半模型缺 line_a 盒")


# ─── 判据 a：闭式回收（KJ → 半模型 → 回读 Z0e/Z0o）───────────────────────────

def test_cline_service_split_structure():
    """cline 半模型结构：轴 x、保端口 {1,2}、弃 {3,4}、PMC/PEC、守卫全绿。"""
    report = _service_cline()
    assert report["ok"] is True
    assert report["axis"] == "x" and report["plane"].startswith("x=0")
    sym = report["symmetry_check"]
    assert sym["ok"] is True and sym["n_boxes"] > 0 and sym["n_ports"] == 4
    for mode, bc in (("even", "PMC"), ("odd", "PEC")):
        half = report["half_models"][mode]
        assert half["bc"] == bc
        assert [p["nr"] for p in half["ports"]] == [1, 2]
        assert half["dropped_port_nrs"] == [3, 4]
        assert not half["plane_boundary"]["faces"]      # 无跨面盒
        assert all(not b.get("clipped") for b in half["boxes"])
        g = report["guards"][mode]
        assert g["ok"] is True
        assert g["mirror_reassembly"]["boxes_equal"] is True
        assert g["mirror_reassembly"]["ports_equal"] is True
        assert g["n_components_full"] == 2 and g["n_components_half"] == 1
        assert g["orphan_ports_half"] == []
    rw = {r["nr"]: r for r in report["port_rewrite_table"]}
    assert rw[1]["disposition"] == "kept" and rw[1]["mirror_of"] == 3
    assert rw[2]["disposition"] == "kept" and rw[2]["mirror_of"] == 4
    assert rw[3]["disposition"] == "dropped" and rw[3]["mirror_of"] == 1
    assert rw[4]["disposition"] == "dropped" and rw[4]["mirror_of"] == 2
    # 端口语义改写：保侧端口附模阻抗注记（耦合结构 Z0e/Z0o 直接读）
    pe = report["half_models"]["even"]["ports"][0]
    po = report["half_models"]["odd"]["ports"][0]
    assert pe["mode_impedance_ohm"] == pytest.approx(Z0E_ANCHOR, rel=1e-12)
    assert po["mode_impedance_ohm"] == pytest.approx(Z0O_ANCHOR, rel=1e-12)


def test_cline_superposition_matches_pozar_synchronous():
    """判据 a1（同步 TEM）：偶/奇叠加 vs Pozar §7.6 闭式，θ=60/75/90/110°。"""
    report = _service_cline()
    ze = report["mode_table"]["even"]["z_mode_ohm"]
    zo = report["mode_table"]["odd"]["z_mode_ohm"]
    c_coupling = (ze - zo) / (ze + zo)
    for th_deg in (60.0, 75.0, 90.0, 110.0):
        th = math.radians(th_deg)
        se11, se12 = _tl_s(ze, th)
        so11, so12 = _tl_s(zo, th)
        s11 = (se11 + so11) / 2
        s21 = (se12 + so12) / 2
        s31 = (se11 - so11) / 2
        s41 = (se12 - so12) / 2
        den = math.sqrt(1 - c_coupling ** 2) * cmath.cos(th) + 1j * cmath.sin(th)
        assert s31 == pytest.approx(
            1j * c_coupling * cmath.sin(th) / den, abs=1e-9), th_deg
        assert s21 == pytest.approx(
            math.sqrt(1 - c_coupling ** 2) / den, abs=1e-9), th_deg
        # S11=S41 门=1e-4：匹配条件残差（标称 w/s 4 位舍入 → Z0e·Z0o 相对偏
        # 1.37e-5，criteria §1 预声明锚；实测 ~5.6e-6 ≈ −105dB）
        assert abs(s11) < 1e-4 and abs(s41) < 1e-4, th_deg
    # θ=90° 教科书值：S31=C（实）、S21=−j√(1−C²)（匹配残差 1e-9 口径，同上）
    th = math.pi / 2
    se11, se12 = _tl_s(ze, th)
    so11, so12 = _tl_s(zo, th)
    assert (se11 - so11) / 2 == pytest.approx(c_coupling, abs=1e-9)
    assert (se12 + so12) / 2 == pytest.approx(
        -1j * math.sqrt(1 - c_coupling ** 2), abs=1e-9)


def test_cline_modal_impedance_recovery_gate():
    """判据 a2（回读门 ≤1% 预声明）：半模型 Z_sc·Z_oc 开短路回读 Z0e/Z0o。"""
    report = _service_cline()
    length = _cline_length_m(report)
    for mode, anchor in (("even", Z0E_ANCHOR), ("odd", Z0O_ANCHOR)):
        mt = report["mode_table"][mode]
        z_mode = mt["z_mode_ohm"]
        theta = 2.0 * math.pi * F0 * math.sqrt(mt["eps_eff"]) * length / C0
        m = _tl_abcd(z_mode, theta)
        z_sc = _zin_abcd(m, 0.0)
        z_oc = _zin_abcd(m, None)
        recovered = math.sqrt((z_sc * z_oc).real)
        # √(Z_sc·Z_oc)=Z_m 与 θ 无关（恒等式）；门 ≤1%（实测 0）
        assert recovered == pytest.approx(z_mode, rel=1e-12)
        assert abs(recovered - anchor) / anchor <= 1e-2, mode
    # 偶/奇分配正确性：回读值与锚逐一对应（错位即 ~2× 偏差必炸）
    ze = report["mode_table"]["even"]["z_mode_ohm"]
    zo = report["mode_table"]["odd"]["z_mode_ohm"]
    assert abs(ze - Z0E_ANCHOR) < abs(ze - Z0O_ANCHOR)
    assert abs(zo - Z0O_ANCHOR) < abs(zo - Z0E_ANCHOR)


def test_cline_nonsynchronous_anchor_sidecheck():
    """判据 a3（非同步旁证锚）：@f0 叠加 S 与 §13.1 锁定值一致（真 KJ 相速）。"""
    report = _service_cline()
    length = _cline_length_m(report)
    th_e = 2.0 * math.pi * F0 * math.sqrt(ERE_E_ANCHOR) * length / C0
    th_o = 2.0 * math.pi * F0 * math.sqrt(ERE_O_ANCHOR) * length / C0
    se11, se12 = _tl_s(Z0E_ANCHOR, th_e)
    so11, so12 = _tl_s(Z0O_ANCHOR, th_o)
    db = lambda x: 20.0 * math.log10(abs(x))  # noqa: E731
    assert db((se11 + so11) / 2) == pytest.approx(-32.9, abs=1.5)
    assert db((se12 + so12) / 2) == pytest.approx(-0.478, abs=0.05)
    assert db((se11 - so11) / 2) == pytest.approx(-10.045, abs=0.05)
    assert db((se12 - so12) / 2) == pytest.approx(-23.3, abs=1.0)
    phase_gap = math.degrees(cmath.phase((se11 - so11) / 2)
                             - cmath.phase((se12 + so12) / 2))
    assert phase_gap == pytest.approx(90.0, abs=0.5)


# ─── 判据 b：13.2 单节映射复现（走内核几何裁剪）──────────────────────────────

def _single_section_branchline_layout():
    """单节分支线合成布局（米；臂/支臂中心线电长=λ/4@TEM，小线宽 w）。"""
    la = lb = 0.01                      # λ/4（TEM 裁判口径，数值任意）
    w = 2e-4

    def arm(y_c: float) -> dict:
        return {"name": f"arm_{'top' if y_c > 0 else 'bottom'}", "kind": "metal",
                "x0": -la / 2 - w / 2, "y0": y_c - w / 2, "z0": 0.0,
                "x1": la / 2 + w / 2, "y1": y_c + w / 2, "z1": 0.0}

    def branch(x_c: float) -> dict:
        return {"name": f"branch_{'left' if x_c < 0 else 'right'}", "kind": "metal",
                "x0": x_c - w / 2, "y0": -lb / 2 - w / 2, "z0": 0.0,
                "x1": x_c + w / 2, "y1": lb / 2 + w / 2, "z1": 0.0}

    boxes = [arm(lb / 2), arm(-lb / 2), branch(-la / 2), branch(la / 2)]
    ports = [
        {"nr": 1, "label": "输入（左上）", "prop_dir": "x",
         "start": [-la / 2, lb / 2, 0.0], "stop": [-la / 2 - 5e-4, lb / 2, 0.0]},
        {"nr": 2, "label": "直通（右上）", "prop_dir": "x",
         "start": [la / 2, lb / 2, 0.0], "stop": [la / 2 + 5e-4, lb / 2, 0.0]},
        {"nr": 3, "label": "耦合（右下）", "prop_dir": "x",
         "start": [la / 2, -lb / 2, 0.0], "stop": [la / 2 + 5e-4, -lb / 2, 0.0]},
        {"nr": 4, "label": "隔离（左下）", "prop_dir": "x",
         "start": [-la / 2, -lb / 2, 0.0], "stop": [-la / 2 - 5e-4, -lb / 2, 0.0]},
    ]
    return {"axis": "y", "boxes": boxes, "ports": ports}


def test_branchline_single_section_mapping_via_kernel():
    """判据 b1：单节 (Z_a,Z_b)=(Z0/√2,Z0) 走内核裁剪复现 Pozar S21/S31。"""
    from rfauto.core import even_odd_split as eos

    lay = eos.normalize_layout(_single_section_branchline_layout())
    assert eos.symmetry_report(lay)["ok"] is True
    gamma_t = {}
    for mode in ("even", "odd"):
        half = eos.split_half_model(lay, mode)
        # 跨面支臂盒 → λ/8 半桩（电长比=跨距比，几何出 θ）
        stubs = [b for b in half["boxes"] if b.get("clipped")]
        assert len(stubs) == 2, mode
        ratio = stubs[0]["span_half"] / stubs[0]["span_full"]
        assert ratio == pytest.approx(0.5, abs=1e-12)
        theta_half = (math.pi / 2) * ratio
        # 装配：桩(Y_b,θ/2)·线(Z_a,θ)·桩（保下半：两支臂半桩夹主线臂）
        # 主线臂中心线长=两支臂半桩盒中点间距（几何出 θ，剔除线宽悬挂量）
        cx = sorted((float(b["x0"]) + float(b["x1"])) / 2.0 for b in stubs)
        centerline = cx[1] - cx[0]
        theta_a = (math.pi / 2) * (centerline / 0.01)   # 中心线 λ/4 口径
        y_b = 1.0                                      # Z_b=Z0（归一）
        z_a = 1.0 / math.sqrt(2.0)
        m = _cascade(_shunt_abcd(eos.stub_input_admittance(
            1.0 / y_b, theta_half, mode)),
            _cascade(_tl_abcd(z_a, theta_a),
                     _shunt_abcd(eos.stub_input_admittance(
                         1.0 / y_b, theta_half, mode))))
        gamma_t[mode] = _abcd_gamma_t(m, z_ref=1.0)
    ge, te = gamma_t["even"]
    go, to = gamma_t["odd"]
    s21 = (te + to) / 2
    s31 = (te - to) / 2
    assert s21 == pytest.approx(-1j / math.sqrt(2), abs=1e-9)
    assert s31 == pytest.approx(-1 / math.sqrt(2), abs=1e-9)
    assert abs((ge + go) / 2) < 1e-9 and abs((ge - go) / 2) < 1e-9


def test_branchline_2sect_nominal_ideal_at_f0():
    """判据 b2：两节标称 (50,120.71,70.71) 半电路 @f0 理想（S21=−1/√2、
    S31=+j/√2）；判据 b3：服务跨面注记与盒几何/HJ εeff 自洽。"""
    from rfauto.adapters.openems_templates import branchline_2sect_impedances
    from rfauto.service import even_odd_service as svc

    report = svc.even_odd_split("branchline_2sect")
    assert report["ok"] is True
    assert report["axis"] == "y"
    for mode in ("even", "odd"):
        half = report["half_models"][mode]
        assert [p["nr"] for p in half["ports"]] == [3, 4]
        assert half["dropped_port_nrs"] == [1, 2]
        clipped = [b for b in half["boxes"] if b.get("clipped")]
        assert len(clipped) == 3
        for b in clipped:
            assert b["span_half"] == pytest.approx(0.0092152, rel=1e-12)
            assert b["span_half"] * 2 == pytest.approx(b["span_full"], rel=1e-12)
        g = report["guards"][mode]
        assert g["ok"] and g["mirror_reassembly"]["boxes_equal"]
    za, zb1, zb2 = branchline_2sect_impedances(50.0, 1.0)
    th_half = math.pi / 4                      # λ/8 半桩（λ/4 支臂裁半）
    gamma_t = {}
    for mode in ("even", "odd"):
        def stub_abcd(zb: float, _mode: str = mode):
            return _shunt_abcd(svc.eos.stub_input_admittance(zb, th_half,
                                                             _mode))
        m = _cascade(stub_abcd(zb1),
                     _cascade(_tl_abcd(za, math.pi / 2),
                              _cascade(stub_abcd(zb2),
                                       _cascade(_tl_abcd(za, math.pi / 2),
                                                stub_abcd(zb1)))))
        gamma_t[mode] = _abcd_gamma_t(m, z_ref=50.0)
    ge, te = gamma_t["even"]
    go, to = gamma_t["odd"]
    s11, s21 = (ge + go) / 2, (te + to) / 2
    s31, s41 = (te - to) / 2, (ge - go) / 2
    assert s21 == pytest.approx(-1 / math.sqrt(2), abs=1e-9)
    assert s31 == pytest.approx(1j / math.sqrt(2), abs=1e-9)
    assert abs(s11) < 1e-9 and abs(s41) < 1e-9
    # 幺正（完整 4 端口装配后 S†S=I）+ 互易
    s4 = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        s4[i][i] = s11
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2)):
        s4[i][j] = s21
    for i, j in ((0, 2), (2, 0), (1, 3), (3, 1)):
        s4[i][j] = s31
    for i, j in ((0, 3), (3, 0), (1, 2), (2, 1)):
        s4[i][j] = s41
    for i in range(4):
        for j in range(4):
            dot = sum(s4[k][i].conjugate() * s4[k][j] for k in range(4))
            assert dot == pytest.approx(1.0 if i == j else 0.0, abs=1e-9)
    # 判据 b3：跨面注记自洽（θ 复算 ≤1e-12；λ/8 口径 ±1.5% 几何固有偏差）
    for a in report["mode_table"]["stub_annotations"]:
        theta_re = (2.0 * math.pi * 2.5e9 * math.sqrt(a["eps_eff_hj"])
                    * a["span_half_m"] / C0)
        assert a["theta_half_rad_at_f0"] == pytest.approx(theta_re, rel=1e-12)
        # 偏离 λ/8（π/4）≤2%：矩形拓扑单支臂跨度的固有二阶偏差（13.2 如实
        # 口径，实测 mid +1.56%/outer −1.19%）
        assert a["theta_half_rad_at_f0"] == pytest.approx(
            math.pi / 4, rel=0.02)
        assert a["y_in_even_s_at_f0"]["re"] == 0.0
        assert a["y_in_odd_s_at_f0"]["re"] == 0.0
        # 恒等式：Y_even·Y_odd = −Y0²（θh=π/4 时两者才互为相反数）
        prod = (a["y_in_even_s_at_f0"]["im"]
                * a["y_in_odd_s_at_f0"]["im"])
        assert prod == pytest.approx(-(1.0 / a["z0_hj_ohm"]) ** 2, rel=1e-9)


# ─── 判据 c：几何守卫 ─────────────────────────────────────────────────────────

def _synthetic_symmetric_layout() -> dict:
    """合成对称布局：下/上盒+自镜像跨面盒+面上退化盒+镜像端口+跨面端口对。"""
    boxes = [
        {"name": "lo_box", "kind": "metal", "x0": -1.0, "y0": -2.0, "z0": 0.0,
         "x1": 1.0, "y1": -1.0, "z1": 0.0},
        {"name": "up_box", "kind": "metal", "x0": -1.0, "y0": 1.0, "z0": 0.0,
         "x1": 1.0, "y1": 2.0, "z1": 0.0},
        {"name": "cross_box", "kind": "metal", "x0": -0.5, "y0": -3.0, "z0": 0.0,
         "x1": 0.5, "y1": 3.0, "z1": 0.0},
        {"name": "plane_strip", "kind": "metal", "x0": -0.2, "y0": 0.0, "z0": 0.0,
         "x1": 0.2, "y1": 0.0, "z1": 0.0},
    ]
    ports = [
        {"nr": 1, "label": "p_lo", "prop_dir": "y",
         "start": [0.5, -1.5, 0.0], "stop": [0.5, -0.5, 0.0]},
        {"nr": 2, "label": "p_up", "prop_dir": "y",
         "start": [0.5, 1.5, 0.0], "stop": [0.5, 0.5, 0.0]},
        {"nr": 3, "label": "cross_a", "prop_dir": "y",
         "start": [-0.1, -2.0, 0.0], "stop": [0.3, 2.0, 0.0]},
        {"nr": 4, "label": "cross_b", "prop_dir": "y",
         "start": [-0.1, 2.0, 0.0], "stop": [0.3, -2.0, 0.0]},
    ]
    return {"axis": "y", "boxes": boxes, "ports": ports}


def test_mirror_reassembly_bitwise_and_crossing_port():
    """判据 c1/c4：重装配逐位恒等、跨面端口裁半+镜像逐位取负、bbox/分量。"""
    from rfauto.core import even_odd_split as eos

    lay = eos.normalize_layout(_synthetic_symmetric_layout())
    assert eos.symmetry_report(lay)["ok"] is True
    for mode in ("even", "odd"):
        half = eos.split_half_model(lay, mode)
        g = eos.split_guards(lay, half)
        assert g["ok"] is True, (mode, g)
        assert g["mirror_reassembly"]["boxes_equal"] is True
        assert g["mirror_reassembly"]["ports_equal"] is True
        assert g["n_components_full"] == 1 and g["n_components_half"] == 1
        assert g["bbox_half_axis_max"] == 0.0
    half = eos.split_half_model(lay, "even")
    names = [b["name"] for b in half["boxes"]]
    assert names == ["lo_box", "cross_box", "plane_strip"] or set(names) == {
        "lo_box", "cross_box", "plane_strip"}
    cross = next(b for b in half["boxes"] if b["name"] == "cross_box")
    assert cross["clipped"] is True and float(cross["y1"]) == 0.0
    assert cross["span_half"] == pytest.approx(3.0, abs=0.0)
    strip = next(b for b in half["boxes"] if b["name"] == "plane_strip")
    assert strip.get("on_plane") is True
    # 跨面端口对：下半段+面上交点逐位互为取负（镜像对插值一次缓存路径）
    p3 = next(p for p in half["ports"] if p["nr"] == 3)
    p4 = next(p for p in half["ports"] if p["nr"] == 4)
    assert p3["half_width"] is True and p4["half_width"] is True
    assert p3["stop"][0] == -p4["stop"][0]
    assert p3["stop"][1] == 0.0 and p4["stop"][1] == 0.0
    assert p3["start"] == [pytest.approx(-0.1), pytest.approx(-2.0),
                           pytest.approx(0.0)]
    # 端口语义改写表：跨面端口 disposition=clipped
    rw = {r["nr"]: r for r in eos.port_rewrite_table(lay)}
    assert rw[3]["disposition"] == "clipped" and rw[3]["half_width"] is True
    assert rw[1]["disposition"] == "kept" and rw[2]["disposition"] == "dropped"


def test_asymmetric_layout_rejected():
    """判据 c2：任一盒/端口镜像配对破坏 → SymmetryError 显式报错。"""
    from rfauto.core import even_odd_split as eos

    base = _synthetic_symmetric_layout()
    bad_box = eos.normalize_layout(base)
    bad_box["boxes"][0]["y1"] = -1.0 + 1e-4          # 扰动下盒（镜像不随动）
    with pytest.raises(eos.SymmetryError) as exc:
        eos.split_half_model(bad_box, "even")
    assert "lo_box" in str(exc.value)
    bad_port = eos.normalize_layout(base)
    bad_port["ports"][0]["start"][1] = -1.5 + 1e-4   # 扰动端口 1
    with pytest.raises(eos.SymmetryError) as exc:
        eos.split_half_model(bad_port, "odd")
    assert "p_lo" in str(exc.value)
    # symmetry_report 不抛（诊断口径；破坏配对的两侧都列名）
    rep = eos.symmetry_report(bad_box)
    assert rep["ok"] is False and "lo_box" in rep["unmatched_box_names"]


def test_connectivity_orphan_guard():
    """判据 c3：孤儿端口显式列入守卫（split_guards ok=false）。"""
    from rfauto.core import even_odd_split as eos

    lay = eos.normalize_layout(_synthetic_symmetric_layout())
    lay["ports"].append({"nr": 9, "label": "floating", "prop_dir": "y",
                         "start": [50.0, -1.5, 0.0], "stop": [50.0, -0.5, 0.0]})
    # 孤儿端口破坏对称（其镜像缺席）→ 先显式报对称错（守卫优先级最高）
    with pytest.raises(eos.SymmetryError):
        eos.split_half_model(lay, "even")
    # 成对孤儿（对称但都不触金属）→ 守卫 ok=false 且列出编号
    lay["ports"].append({"nr": 10, "label": "floating_m", "prop_dir": "y",
                         "start": [50.0, 1.5, 0.0], "stop": [50.0, 0.5, 0.0]})
    assert eos.symmetry_report(lay)["ok"] is True
    half = eos.split_half_model(lay, "even")
    g = eos.split_guards(lay, half)
    assert g["orphan_ports_half"] == [9]
    assert g["ok"] is False
    assert eos.orphan_ports(lay["boxes"], lay["ports"]) == [9, 10]


def test_stub_identities_open_short():
    """判据 c5：偶=开路桩/奇=短路桩 vs 独立 ABCD 终接推导 ≤1e-12；θ=π/4 锚。"""
    from rfauto.core import even_odd_split as eos

    for z0 in (36.03866991398955, 50.0, 120.71):
        for th in (0.3, math.pi / 4, 1.2):
            y_even = eos.stub_input_admittance(z0, th, "even")
            y_odd = eos.stub_input_admittance(z0, th, "odd")
            m = _tl_abcd(z0, th)
            y_open_ref = _zin_abcd(m, None) ** -1.0        # 开路桩 Y=C/A
            y_short_ref = _zin_abcd(m, 0.0) ** -1.0        # 短路桩 Y=D/B
            assert y_even == pytest.approx(y_open_ref, abs=1e-12)
            assert y_odd == pytest.approx(y_short_ref, abs=1e-12)
    y0 = 1.0 / 70.71
    assert eos.stub_input_admittance(70.71, math.pi / 4, "even") == \
        pytest.approx(1j * y0, abs=1e-12)
    assert eos.stub_input_admittance(70.71, math.pi / 4, "odd") == \
        pytest.approx(-1j * y0, abs=1e-12)
    with pytest.raises(ValueError):
        eos.stub_input_admittance(50.0, 0.3, "weird")
    with pytest.raises(ValueError):
        eos.stub_input_admittance(-1.0, 0.3, "even")


# ─── 服务面契约（JSON 进出/注册表/#154 语义声明）────────────────────────────

def test_service_json_contract_and_determinism():
    """服务输出 JSON 可序列化、两次调用逐位一致、未知模板显式报错。"""
    import json

    from rfauto.service import even_odd_service as svc

    for t in svc.EVEN_ODD_TEMPLATES:
        assert t in ("cline_coupler", "branchline_2sect")
        r1 = svc.even_odd_split(t)
        r2 = svc.even_odd_split(t)
        assert r1 == r2                                   # 确定性（逐位）
        json.dumps(r1)                                    # JSON 进出
        meta = svc.template_even_odd_meta(t)
        assert meta["axis"] in ("x", "y")
        assert meta["half_model_semantics"]
        assert set(meta["port_roles"]) == {"1", "2", "3", "4"}
        assert meta["reassembly"]["formulas"]["S11"] == "(Γe+Γo)/2"
    with pytest.raises(ValueError):
        svc.even_odd_split("wilkinson")                   # 未接入模板显式报错
    # 两模板语义显式分派（#154）：导体间平面 vs 切割导体
    m_cline = svc.template_even_odd_meta("cline_coupler")
    m_bl = svc.template_even_odd_meta("branchline_2sect")
    assert "模阻抗" in m_cline["half_model_semantics"]
    assert "λ/8 半桩" in m_bl["half_model_semantics"]


def test_service_strict_vs_report_and_cline_branchline_modes():
    """严格口径 raise / 报告口径 ok=false；mode_table 三键与 KJ 来源注记。"""
    from rfauto.service import even_odd_service as svc

    r = _service_cline()
    mt = r["mode_table"]
    assert mt["even"]["bc"] == "PMC" and mt["odd"]["bc"] == "PEC"
    assert mt["even"]["z_mode_ohm"] == pytest.approx(Z0E_ANCHOR, rel=1e-12)
    assert mt["odd"]["z_mode_ohm"] == pytest.approx(Z0O_ANCHOR, rel=1e-12)
    assert mt["even"]["eps_eff"] == pytest.approx(ERE_E_ANCHOR, rel=1e-12)
    assert "Kirschning-Jansen" in mt["source"]
    # 注入非对称布局（monkeypatch 注册表几何映射）→ 严格/报告两口径
    import rfauto.service.even_odd_service as mod

    broken = {"axis": "y", "boxes": [
        {"name": "only", "kind": "metal", "x0": -1.0, "y0": -2.0, "z0": 0.0,
         "x1": 1.0, "y1": -1.0, "z1": 0.0}], "ports": []}
    saved = dict(mod._REGISTRY["cline_coupler"])
    mod._REGISTRY["cline_coupler"]["layout"] = lambda params: broken
    try:
        rep = svc.even_odd_split_report("cline_coupler")
        assert rep["ok"] is False and "不满足镜像对称" in rep["error"]
        with pytest.raises(svc.SymmetryError):
            svc.even_odd_split("cline_coupler")
    finally:
        mod._REGISTRY["cline_coupler"].update(saved)
