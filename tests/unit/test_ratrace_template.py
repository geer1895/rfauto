"""WP2.3 rat-race 环形电桥单测：渲染/解析（理想 180° 混合环裁判）/综合/spec。

口径（#208 理论核验轮定版）：环周长 1.5λg@70.7Ω（√2·Z0），arcs λ/4×3 +
3λ/4；规范角位 Σ=0°/out1=60°/Δ=120°/out2=300°（out1/out2 分居 Σ 两侧
λ/4，大弧扫 Δ→out2 之间；pt5 实测定版）。环带逐网格行栅格化（#198 零台阶）。
裁判=理想 180° 混合环 S 矩阵（f0 闭式，Y 矩阵推导）：Σ 均分 -3dB 同相、
Δ 隔离、out1↔out2 互隔离、Δ 激励反相输出。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC))

W_RING = 0.6035
R_PHYS = 17.344      # 物理环半径（synthesis 1.5λg，nominal 不变）
AUDIT_BASE_MM = 0.4  # 离线几何审计网格档（pt8/pt9 定标档；k(0.4)=1.1654）


def _r_eng(base_mm: float = AUDIT_BASE_MM) -> float:
    """openEMS 渲染半径 = 物理半径 / k(BASE)（阶梯环慢波伪象补偿随网格档标度，
    ratrace_ring_mesh_k；默认 0.4mm 审计档）。"""
    from rfauto.adapters.openems_templates import ratrace_ring_mesh_k

    return R_PHYS / ratrace_ring_mesh_k(base_mm)


def test_template_tables_have_ratrace():
    from rfauto.adapters.openems_templates import (
        _TEMPLATE_PORT_AXES,
        _TEMPLATE_RADIATOR,
        TEMPLATE_META,
        TEMPLATE_NOMINAL,
    )

    assert "ratrace" in TEMPLATE_META and "ratrace" in TEMPLATE_NOMINAL
    assert TEMPLATE_META["ratrace"]["n_ports"] == 4
    assert TEMPLATE_NOMINAL["ratrace"]["w_ring_mm"] == pytest.approx(0.6035,
                                                                     abs=0.001)
    assert _TEMPLATE_PORT_AXES["ratrace"] == ("x", "y")
    assert _TEMPLATE_RADIATOR["ratrace"] is False


def test_render_ratrace_structure():
    from rfauto.adapters.openems_templates import render_script

    text = render_script("ratrace", {"w_ring_mm": W_RING,
                                     "w_feed_mm": 1.1134}, (2.25, 2.75))
    compile(text, "gen", "exec")  # 语法门（#201 制度化）
    for n in (1, 2, 3, 4):
        assert f"MSLPort(CSX, port_nr={n}" in text
    assert 'prop_dir="x"' in text and 'prop_dir="y"' in text
    # 环带栅格化循环（逐 y 网格行）
    assert 'mesh.GetLines("y")' in text
    assert "_R_IN" in text and "_R_OUT" in text
    # #208：进程隔离激励轮转——渲染按 excite_port 参数化激励端口，
    # 单激励脚本（全库已验证安全模式）；适配器层装配 .s4p 主产物
    assert "SetEnabled" not in text or all(
        "#" in line[:line.index("SetEnabled")]
        for line in text.splitlines() if "SetEnabled" in line)
    assert "re_S41" in text and "_SREF" in text
    assert "excite=1 if" in text and "excite=0" in text


def test_render_ratrace_excite_port_param():
    """excite_port 参数化：第 k 份脚本仅 port k excite=1（进程隔离轮转）。"""
    from rfauto.adapters.openems_templates import render_script

    for ep in (1, 2, 3, 4):
        text = render_script("ratrace", {"w_ring_mm": W_RING,
                                         "w_feed_mm": 1.1134},
                             (2.25, 2.75), excite_port=ep)
        compile(text, "gen", "exec")
        for n in (1, 2, 3, 4):
            expected = f"excite=1 if {ep} == {n} else 0"
            assert expected in text, f"ep={ep} 缺 {expected}"
        # 单激励列 CSV：S41 列在案（9 列）
        assert "re_S41" in text


def test_near_points_exact_edges():
    from rfauto.adapters.openems_templates import _near_points

    nx, _ny = _near_points("ratrace", {"w_ring_mm": W_RING,
                                       "w_feed_mm": 1.1134},
                           base_mm=AUDIT_BASE_MM)
    # Σ/out2 水平馈带缘 y=±0.5567；out1/Δ 竖直引出段
    # x=±(0.5·R_eng + 4/√3)±0.5567 mm（#208 规范角位；R_eng=物理 R/k(BASE)）
    x_top_mm = 0.5 * _r_eng() + 4.0 / 3.0 ** 0.5
    for edge_mm in (-(x_top_mm + 0.5567), -(x_top_mm - 0.5567),
                    x_top_mm - 0.5567, x_top_mm + 0.5567):
        assert min(abs(v - edge_mm * 1e-3) for v in nx) < 1e-6
    for edge_mm in (-0.5567, 0.5567):
        assert min(abs(v - edge_mm * 1e-3) for v in _ny) < 1e-6


def test_fake_ratrace_ideal_hybrid():
    """fake：理想 180° 混合环——Σ 均分 -3dB 同相、Δ/out 间隔离、匹配。"""
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="ratrace", n_ports=4,
                     freq_ghz=(2.0, 3.0, 101), f0_ghz=2.5)
    ad.connect({})
    ad.solve("main_setup")
    net = ad.get_sparams()
    assert net.s.shape[1] == 4
    s21_db = 20 * np.log10(np.abs(net.s[:, 1, 0]) + 1e-12)
    s41_db = 20 * np.log10(np.abs(net.s[:, 3, 0]) + 1e-12)
    assert s21_db.mean() == pytest.approx(-3.01, abs=0.05)
    assert s41_db.mean() == pytest.approx(-3.01, abs=0.05)
    # 隔离对：Δ（port3）与 out1↔out2（port2↔port4）
    s31_db = 20 * np.log10(np.abs(net.s[:, 2, 0]) + 1e-12)
    s24_db = 20 * np.log10(np.abs(net.s[:, 3, 1]) + 1e-12)
    assert s31_db.mean() < -100
    assert s24_db.mean() < -100
    s11_db = 20 * np.log10(np.abs(net.s[:, 0, 0]) + 1e-12)
    assert s11_db.mean() < -100  # 匹配


def test_fake_ratrace_delta_antiphase():
    """Δ 激励 → out1/out2 反相（180° 混合环定义性质，#208 推导）。"""
    from rfauto.adapters.fake_adapter import _ratrace_sparams

    s = _ratrace_sparams(np.array([2.5]))
    phase_out1 = np.angle(s[0, 1, 2])
    phase_out2 = np.angle(s[0, 3, 2])
    assert abs(phase_out1 - phase_out2) == pytest.approx(np.pi, abs=1e-9)
    # Σ 激励 → 输出同相
    assert abs(np.angle(s[0, 1, 0]) - np.angle(s[0, 3, 0])) < 1e-9


def test_fake_ratrace_matches_skrf_ring_assembly():
    """闭式裁判对照独立来源（#205 互检纪律）：skrf 理想弧段 Y 装配。

    独立构造：四弧（λ/4,λ/4,3λ/4,λ/4）用 skrf 媒体对象的 ABCD→Y，
    节点导纳装配 → S=(I−Z0Y)(I+Z0Y)⁻¹，在 f0 处应逐元素等于闭式。
    """
    import skrf

    from rfauto.adapters.fake_adapter import _ratrace_sparams

    f0 = 2.5
    freq = skrf.Frequency(f0, f0, 1, unit="GHz")
    zr = 50.0 * 2.0 ** 0.5
    c0 = 299792458.0
    beta = 2.0 * np.pi * f0 * 1e9 / c0
    media = skrf.media.DefinedGammaZ0(frequency=freq, gamma=1j * beta,
                                      z0=zr)
    # skrf line() 默认单位=deg：λ/4=90°、3λ/4=270°（理想无畸变弧）
    arcs = [(0, 1, media.line(90, unit="deg")),
            (1, 2, media.line(90, unit="deg")),
            (2, 3, media.line(270, unit="deg")),
            (3, 0, media.line(90, unit="deg"))]
    y = np.zeros((4, 4), dtype=complex)
    for i, j, net in arcs:
        yij = net.y[0]
        y[i, i] += yij[0, 0]
        y[j, j] += yij[1, 1]
        y[i, j] += yij[0, 1]
        y[j, i] += yij[1, 0]
    z0 = 50.0
    s_asm = (np.eye(4) - z0 * y) @ np.linalg.inv(np.eye(4) + z0 * y)
    s_ref = _ratrace_sparams(np.array([f0]))[0]
    np.testing.assert_allclose(s_asm, s_ref, atol=1e-9)


def test_synthesize_ratrace_model_roundtrip():
    from rfauto.core.synthesis import Stackup, inverse_width, synthesize_ratrace_model

    result = synthesize_ratrace_model(z0_ohm=50.0, freq_ghz=2.5)
    assert result.model == "ratrace"
    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_ref, _, _ = inverse_width(70.7, 2.5, st)
    assert result.params["w_ring_mm"] == pytest.approx(w_ref, abs=0.01)
    # 环半径 = 1.5λg/(2π)：λg = λ0/√εeff(70.7Ω 线)
    # εeff 独立锚：70.7Ω 线 HJ 值（E4/inverse_width 同源，见 notes）
    er_eff = 2.7246
    lam_g = 299.792458 / 2.5 / np.sqrt(er_eff)
    assert result.params["r_ring_mm"] == pytest.approx(
        1.5 * lam_g / (2 * np.pi), abs=0.05)


def test_ratrace_spec_wiring():
    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs

    bootstrap_template_specs()
    spec = TEMPLATE_SPECS.get("ratrace")
    assert spec.render_script is not None
    assert spec.fake_model is not None
    assert spec.synthesizer is not None
    draft = TEMPLATE_SPECS.draft_recipe("ratrace", z0_ohm=50.0)
    assert draft["model"] == "ratrace"


def test_meta_yaml_sync():
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META

    p = REPO / "docs" / "templates" / "ratrace" / "meta.yaml"
    assert p.exists()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    assert data["template"] == "ratrace"
    assert data["n_ports"] == TEMPLATE_META["ratrace"]["n_ports"]


def _ratrace_metal_boxes(tmp_path, mesh_mm: float = 0.4):
    """渲染→exec 几何段→CSXCAD 金属原语 (x0,x1,y0,y1) mm 列表（#212 审计基元）。"""
    import numpy as np

    from rfauto.adapters.openems_templates import render_script

    text = render_script("ratrace", {"w_ring_mm": W_RING,
                                     "w_feed_mm": 1.1134},
                         (2.25, 2.75), mesh_resolution_mm=mesh_mm,
                         excite_port=1)
    head = text[:text.index("FDTD.Run(")]
    g = {"__name__": "__main__",
         "__file__": str(tmp_path / "simulation.py")}
    exec(compile(head, "sim", "exec"), g)
    csx = g["CSX"]
    boxes = []
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        if str(prop.GetTypeString()) != "Metal":
            continue
        for prim in prop.GetAllPrimitives():
            s = np.array(prim.GetStart(), dtype=float)
            e = np.array(prim.GetStop(), dtype=float)
            x0, x1 = sorted((s[0] * 1e3, e[0] * 1e3))
            y0, y1 = sorted((s[1] * 1e3, e[1] * 1e3))
            boxes.append((x0, x1, y0, y1))
    return boxes


def _overlap_area(a, b) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0])) * \
        max(0.0, min(a[3], b[3]) - max(a[2], b[2]))


def _stub_rows(boxes, sign_y: int, sign_x: int = 1):
    """径向 stub 行盒判据：盒宽 = W_F/sin60°（构造精确值 1.2856mm，±2e-3）
    且盒中心落在解析中心线 x_c(y)=±(0.5R+(|y|−0.866R)/tan60) ±0.05mm 上
    （结点行环弦盒中心偶合中心线但宽 1.21≠1.286；竖直段盒高 ≈41mm）。"""
    import math

    r, tan60 = _r_eng(), math.tan(math.radians(60.0))
    w_stub = 1.1134 / math.sin(math.radians(60.0))
    out = []
    for b in boxes:
        yc = sign_y * 0.5 * (b[2] + b[3])
        if not (0.866 * r - 0.3 <= yc <= 0.866 * r + 4.3):
            continue
        if not (abs((b[1] - b[0]) - w_stub) <= 2e-3 and (b[3] - b[2]) <= 0.6):
            continue
        yc_clip = min(max(yc, 0.866 * r), 0.866 * r + 4.0)
        xc = sign_x * (0.5 * r + (yc_clip - 0.866 * r) / tan60)
        if abs(0.5 * (b[0] + b[1]) - xc) <= 0.05:
            out.append(b)
    return out


def _is_band_box(b, tol: float = 0.4) -> bool:
    """环带盒：四角半径均落在 [R_IN−tol, R_OUT+tol]（环弦盒/结点行盒）。"""
    import math

    r_in, r_out = _r_eng() - W_RING / 2, _r_eng() + W_RING / 2
    return all(r_in - tol <= math.hypot(x, y) <= r_out + tol
               for x in (b[0], b[1]) for y in (b[2], b[3]))


def test_render_ratrace_geometry_bandwidth_offline(tmp_path):
    """离线几何审计（#212 P0-1 回归 + pt8 行栅格化定版）：渲染脚本几何段
    exec 后用 CSXCAD 实测径向馈线——字符串存在性测试抓不住画法错误
    （pt5/pt6"中心线弦"三径向端口全死；pt7 x 列画法留 1.8mm 向内尖刺+
    大焊盘把 hybrid 中心压到 2.2GHz）。秒级、零仿真。

    定版画法：60° 陡线沿 y 行栅格化，每行盒宽 = W_F/sin60° ≈ 1.286mm
    （垂直投影带宽恰为 W_F），在环中心线处裁剪（无环孔内尖刺）。
    """
    import numpy as np

    boxes = _ratrace_metal_boxes(tmp_path)
    r_in = _r_eng() - W_RING / 2
    stub = _stub_rows(boxes, +1)          # out1 径向 stub 行盒
    # 旧"中心线弦"/x 列画法均不可能产出这种行盒——存在性即回归判据
    assert len(stub) >= 5, f"径向行盒不足: {len(stub)} 个"
    widths = [b[1] - b[0] for b in stub]
    med = float(np.median(widths))
    assert 1.15 <= med <= 1.45, f"径向行盒宽 {med:.3f}mm 非 W_F/sin60"
    # 无尖刺：stub 盒四角最小半径不得深入环内缘（pt7 旧画法 15.32mm）
    r_min = min(min(np.hypot(x, y) for x in (b[0], b[1]) for y in (b[2], b[3]))
                for b in stub)
    assert r_min >= r_in - 0.2, f"径向 stub 伸入环孔: r_min={r_min:.2f}mm"


def test_render_ratrace_stub_connectivity_and_mirror(tmp_path):
    """径向 stub 与环带/竖直引出段正面积重叠（FDTD 网格意义导通，#174
    零缝教训）；out1/out2 stub 逐盒关于 y=0 严格镜像（弯折对称加载）。
    """
    boxes = _ratrace_metal_boxes(tmp_path)
    out1, out2 = _stub_rows(boxes, +1), _stub_rows(boxes, -1)
    delta = _stub_rows(boxes, +1, sign_x=-1)
    assert len(out1) >= 5 and len(out2) == len(out1) == len(delta)
    # 镜像：每个 out1 行盒在 out2 中有 (x 同, y→−y) 对应盒
    for b in out1:
        mirror = (b[0], b[1], -b[3], -b[2])
        assert any(all(abs(m - n) < 1e-6 for m, n in zip(mirror, c, strict=True))
                   for c in out2), f"out1 盒 {b} 无 out2 镜像"
    # 连通：最低行盒与环带盒（贴环带、非同一盒）正面积重叠；最高行盒与
    # 竖直引出段盒正面积重叠（竖直段盒 ×2：模板 AddBox + MSLPort 自画）
    vertical = [b for b in boxes if b[3] > 50.0 and b[0] > 9.0 and b[1] < 13.0]
    assert len(vertical) >= 1, "out1 竖直引出段盒缺失"
    lowest = min(out1, key=lambda b: b[2])
    highest = max(out1, key=lambda b: b[3])
    assert any(b != lowest and _is_band_box(b) and _overlap_area(lowest, b) > 1e-4
               for b in boxes), f"stub 最低行 {lowest} 未与环带正面积重叠"
    assert _overlap_area(highest, vertical[0]) > 1e-4, \
        f"stub 最高行 {highest} 未与竖直段 {vertical[0]} 正面积重叠"


def test_render_ratrace_ring_mesh_constant_applied(tmp_path):
    """k(BASE) 生效（ratrace-k 定版轮）：渲染环半径 = 物理 17.344 / k(BASE)，物理
    R 与 nominal/synthesis 不变。用 CSXCAD 原语实测 0.4mm 档 y≈0 行环带外缘
    x = R_eng+W/2（而非物理 17.344+W/2）；k 范围守卫 [1.05,1.20] 防误改
    （0.4mm 锚 1.1654 超旧上限 1.15，pt8 归档锚 1.0975 仅存证不再消费）。
    """
    from rfauto.adapters.openems_templates import (
        _RATRACE_RING_MESH_K,
        TEMPLATE_NOMINAL,
        ratrace_ring_mesh_k,
        render_script,
    )

    k04 = ratrace_ring_mesh_k(AUDIT_BASE_MM)
    assert 1.05 <= k04 <= 1.20
    assert pytest.approx(1.0975) == _RATRACE_RING_MESH_K   # pt8 归档锚仅存证
    assert TEMPLATE_NOMINAL["ratrace"]["r_ring_mm"] == pytest.approx(R_PHYS, abs=1e-3)
    text = render_script("ratrace", {"w_ring_mm": W_RING, "w_feed_mm": 1.1134},
                         (2.25, 2.75), mesh_resolution_mm=AUDIT_BASE_MM)
    assert f"/ {k04!r}" in text
    assert "/ 1.0975" not in text            # 归档常数不得再进渲染脚本
    boxes = _ratrace_metal_boxes(tmp_path)
    # y≈0 行的右侧环带盒：x1 = 外半径（该行 |y|<0.05，弦≈外半径）
    ring_right = [b for b in boxes if b[2] <= 0.0 <= b[3] and b[0] > 10.0
                  and b[1] < 25.0 and (b[1] - b[0]) < 1.0]
    assert ring_right, "y=0 行右侧环带盒缺失"
    x_out = max(b[1] for b in ring_right)
    assert x_out == pytest.approx(_r_eng() + W_RING / 2, abs=0.02), \
        f"环外缘 x={x_out:.3f} ≠ R_eng+W/2={_r_eng() + W_RING / 2:.3f}"
    assert abs(x_out - (R_PHYS + W_RING / 2)) > 1.0, "引擎常数未生效（仍为物理半径）"


# ── k(BASE) 网格档自适应（ratrace-k 定版：两锚幂律内插 + 域外 clamp）──

def test_ratrace_ring_mesh_k_anchors_and_alpha():
    """两锚精确复现（openems_convergence.json k_needed_0p2mm/0p4mm）；(k−1)
    幂律指数 α=ln((k04−1)/(k02−1))/ln2≈0.915 由锚闭式导出（两点比值 1.886）。"""
    import math

    from rfauto.adapters.openems_templates import (
        _RATRACE_K_ANCHOR_HI,
        _RATRACE_K_ANCHOR_LO,
        ratrace_ring_mesh_k,
    )

    assert ratrace_ring_mesh_k(0.2) == pytest.approx(_RATRACE_K_ANCHOR_LO, abs=1e-12)
    assert ratrace_ring_mesh_k(0.4) == pytest.approx(_RATRACE_K_ANCHOR_HI, abs=1e-12)
    assert pytest.approx(1.0877, abs=1e-9) == _RATRACE_K_ANCHOR_LO
    assert pytest.approx(1.1654, abs=1e-9) == _RATRACE_K_ANCHOR_HI
    ratio = (_RATRACE_K_ANCHOR_HI - 1.0) / (_RATRACE_K_ANCHOR_LO - 1.0)
    assert ratio == pytest.approx(1.886, abs=2e-3)
    alpha = math.log(ratio) / math.log(2.0)
    assert alpha == pytest.approx(0.915, abs=2e-3)
    # 中点 0.3mm：(k−1) 几何中值（对数空间线性）
    k_mid = ratrace_ring_mesh_k(0.3)
    assert (k_mid - 1.0) == pytest.approx(
        math.sqrt((_RATRACE_K_ANCHOR_LO - 1.0) * (_RATRACE_K_ANCHOR_HI - 1.0)), abs=1e-12)


def test_ratrace_ring_mesh_k_monotonic_and_clamp():
    """BASE 单调不减；定标域 [0.2,0.4]mm 外夹到最近锚并打 clamp 旗（默认自动档
    BASE=λ_sub/50≈1.14mm 落 clamp 分支，禁止外推到 ~1.43）。"""
    from rfauto.adapters.openems_templates import (
        ratrace_ring_mesh_k,
        ratrace_ring_mesh_k_clamped,
    )

    grid = [0.2 + 0.01 * i for i in range(21)]
    ks = [ratrace_ring_mesh_k(b) for b in grid]
    assert all(b <= a for a, b in zip(ks[1:], ks[:-1], strict=True))
    assert ks[-1] > ks[0]
    for b in (0.05, 0.1, 0.19):
        assert ratrace_ring_mesh_k(b) == ratrace_ring_mesh_k(0.2)
        assert ratrace_ring_mesh_k_clamped(b) is True
    for b in (0.41, 1.1405, 2.0):
        assert ratrace_ring_mesh_k(b) == ratrace_ring_mesh_k(0.4)
        assert ratrace_ring_mesh_k_clamped(b) is True
        assert ratrace_ring_mesh_k(b) < 1.2     # 未外推
    for b in (0.2, 0.3, 0.4):
        assert ratrace_ring_mesh_k_clamped(b) is False


def test_render_ratrace_k_follows_mesh_and_near_points_agree(tmp_path):
    """渲染层自适应：0.2/0.4/自动档各取各 k，脚本 R_RING 文本与 _near_points 引出段
    近场线同 k（几何/网格一致）；自动档脚本含"未定标档 clamp"注释行。"""
    import re

    from rfauto.adapters.openems_templates import (
        _near_points,
        ratrace_ring_mesh_k,
        render_script,
    )

    params = {"w_ring_mm": W_RING, "w_feed_mm": 1.1134}
    for mesh_mm, want_clamp in ((0.2, False), (0.4, False), (0.0, True)):
        text = render_script("ratrace", params, (2.25, 2.75),
                             mesh_resolution_mm=mesh_mm, excite_port=1)
        compile(text, "gen", "exec")
        base_mm = float(re.search(r"BASE = ([0-9.eE+-]+)", text).group(1)) * 1e3
        k = ratrace_ring_mesh_k(base_mm)
        assert f"R_RING = {R_PHYS!r} * 1e-3 / {k!r}" in text
        assert ("未定标档 clamp" in text) is want_clamp
        if want_clamp:
            assert base_mm > 0.4                 # 自动档 λ_sub/50≈1.14mm
        nx, _ny = _near_points("ratrace", params, base_mm=base_mm)
        x_top_mm = 0.5 * R_PHYS / k + 4.0 / 3.0 ** 0.5
        assert min(abs(v - (x_top_mm + 0.5567) * 1e-3) for v in nx) < 1e-9
    # 0.2 与 0.4 档渲染半径不同（k 随档变）
    assert ratrace_ring_mesh_k(0.2) < ratrace_ring_mesh_k(0.4)


def test_cylindrical_script_stays_k1():
    """柱坐标渲染（#219/#232 根治首选）不消费 k(BASE)：脚本无任何 k 补偿字样。"""
    from rfauto.adapters.openems_templates import render_ratrace_cylindrical

    text = render_ratrace_cylindrical(
        {"w_ring_mm": W_RING, "w_feed_mm": 1.1134}, (2.25, 2.75),
        mesh_resolution_mm=0.4, excite_port=1)
    assert "ratrace_ring_mesh_k" not in text
    assert "_RATRACE_RING_MESH_K" not in text
    assert "1.0975" not in text and "1.1654" not in text and "1.0877" not in text
    assert "0.017344" in text                 # 物理半径 k=1


# ── 环带行判据定版审计（2026-09-12 HFSS 仲裁批，坑 #212 零仿真模式）──

def _ratrace_head_and_mesh(tmp_path, mesh_mm: float):
    """渲染→exec 几何段→（金属盒 mm 列表, y 网格线 mm 数组, 脚本文本）。"""
    from rfauto.adapters.openems_templates import render_script

    text = render_script("ratrace", {"w_ring_mm": W_RING,
                                     "w_feed_mm": 1.1134},
                         (2.25, 2.75), mesh_resolution_mm=mesh_mm,
                         excite_port=1)
    head = text[:text.index("FDTD.Run(")]
    g = {"__name__": "__main__",
         "__file__": str(tmp_path / "simulation.py")}
    exec(compile(head, "sim", "exec"), g)
    csx = g["CSX"]
    boxes = []
    for pi in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(pi)
        if str(prop.GetTypeString()) != "Metal":
            continue
        for prim in prop.GetAllPrimitives():
            s = np.array(prim.GetStart(), dtype=float)
            e = np.array(prim.GetStop(), dtype=float)
            x0, x1 = sorted((s[0] * 1e3, e[0] * 1e3))
            y0, y1 = sorted((s[1] * 1e3, e[1] * 1e3))
            boxes.append((x0, x1, y0, y1))
    ylines = np.sort(np.asarray(g["mesh"].GetLines("y"), dtype=float)) * 1e3
    return text, boxes, ylines


def _expected_ring_rows(ylines_mm, r_eng: float, skip_criterion: bool = True):
    """按当前判据（|行中心|>R_OUT 跳行）独立复算环带盒集合（mm，排序）。"""
    r_out, r_in = r_eng + W_RING / 2, r_eng - W_RING / 2
    out = []
    for k in range(len(ylines_mm) - 1):
        ya, yb = float(ylines_mm[k]), float(ylines_mm[k + 1])
        yc = 0.5 * (ya + yb)
        if skip_criterion and abs(yc) > r_out:
            continue
        xo = math.sqrt(max(r_out ** 2 - yc ** 2, 0.0))
        xi = math.sqrt(max(r_in ** 2 - yc ** 2, 0.0))
        if xi > 1e-9:
            out.append((-xo, -xi, ya, yb))
            out.append((xi, xo, ya, yb))
        else:
            out.append((-xo, xo, ya, yb))
    return sorted(tuple(round(v, 6) for v in b) for b in out)


def _candidate_criterion_extra_rows(ylines_mm, r_eng: float):
    """候选判据"行∩带重叠即画"相对当前判据"|行中心|>R_OUT 跳行"会多画的行
    [(ya, yb, 带内重叠 mm)]——原始浮点直接比较、不舍入。旧实现把 round(·,4)
    与 round(round(·,6),4) 混比，0.27835000000000004 这类值双重舍入不一致
    产出 8 行假差集，让"非无操作"断言在 k(0.4) 下假绿（ratrace-k 定版轮实测）。"""
    r_out = r_eng + W_RING / 2
    out = []
    for k in range(len(ylines_mm) - 1):
        ya, yb = float(ylines_mm[k]), float(ylines_mm[k + 1])
        ov = min(yb, r_out) - max(ya, -r_out)
        if ov > 1e-12 and abs(0.5 * (ya + yb)) > r_out:
            out.append((ya, yb, ov))
    return out


def test_render_ratrace_ring_row_criterion_locked_0p4(tmp_path):
    """0.4mm 档环带原语集合 = 行中心判据复算集合（定标前提锁定）+ 候选判据差集
    按实测钉值。

    仲裁批（k=1.0975，R_OUT=16.105）离线审计：候选判据"行与环带有重叠"在
    0.4mm 档非无操作——每侧 cap 各 1 行 [16.0895, 16.4887]（|yc|=16.289 >
    R_OUT，带内重叠 15.4µm）。**ratrace-k 定版轮重审计翻转**（k(0.4)=1.1654，
    R_eng=14.8824 / R_OUT=15.1842）：0.4mm 档顶行上缘 15.2921 已越过 R_OUT，
    候选判据成**无操作**（差集空、中心圈覆盖 100%、无 cap sliver）；非无操作
    只剩默认自动档（见 test_render_ratrace_default_mesh_ring_continuity）。
    旧断言 len(new_rows)>=1 曾靠双重舍入假差集假绿（#122 不凑绿），本版改
    原始浮点比较并按实测钉值；仲裁决议"保留原判据"不变。改判据/改 k 锚
    必须同步重审计并更新本测试。
    """

    _text, boxes, ylines = _ratrace_head_and_mesh(tmp_path, AUDIT_BASE_MM)
    r_eng = _r_eng()
    got = sorted(tuple(round(v, 6) for v in b) for b in boxes
                 if _is_band_box(b))
    want = _expected_ring_rows(ylines, r_eng, skip_criterion=True)
    # CSXCAD 实测集合 ⊇ 判据复算集合（浮点路径一致性，逐盒 1e-6mm 容差）
    missing = [b for b in want if b not in got]
    assert not missing, f"判据复算的 {len(missing)} 个环带盒未在实测集合中" \
                        f"（渲染判据被改？）: {missing[:3]}"
    # 候选判据差集：k(0.4) 下 0.4mm 档为无操作（顶行上缘越过 R_OUT）
    extra = _candidate_criterion_extra_rows(ylines, r_eng)
    assert extra == [], \
        f"0.4mm 档候选判据非无操作（与定版轮重审计不符，需复核）: {extra}"
    r_out = r_eng + W_RING / 2
    y_top = max(b[3] for b in want)
    assert y_top >= r_out, f"顶行上缘 {y_top:.4f} 未越过 R_OUT={r_out:.4f}（出现 cap sliver）"
    assert r_eng == pytest.approx(14.8824, abs=2e-3)
    assert y_top == pytest.approx(15.2921, abs=5e-3)


def test_render_ratrace_default_mesh_ring_continuity(tmp_path):
    """默认网格（BASE=λ_sub/50=1.1405mm，k(BASE) 域外 clamp 到 k(0.4)=1.1654）
    环连续性离线断言（#212 零仿真），ratrace-k 定版轮重审计钉值。

    仲裁批（k=1.0975）实测：跳过行 [15.9281, 17.0582] 使环带 y 顶缺
    0.177mm（=0.155·BASE），覆盖 98.96%，缺口 ±73.6°/±105.5°。**定版轮
    （R_eng=14.8824 / R_OUT=15.1842）实测**：跳过行 [15.1191, 16.2411]
    （|yc|=15.6801 > R_OUT，带内重叠 0.0651mm=5.8% 行高）使顶缺 0.0651mm
    （=0.057·BASE）；严格中心圈覆盖 98.84%，缺口在 74.8–75.8°/104.2–105.2°
    及其 y 镜像（行中心弦量化楔形，弧长 0.27mm×4）；**不存在**早期误判所述
    "83–97° 开路/覆盖率 91.7%"。候选判据在默认档非无操作（每侧多画 1 行
    cap sliver）——仲裁决议维持原判据。锁定：覆盖 ≥97%、cap 区连续、
    缺口 ≤0.2·BASE 且按实测钉值。
    """
    import re

    text, boxes, ylines = _ratrace_head_and_mesh(tmp_path, 0.0)
    m = re.search(r"BASE = ([0-9.eE+-]+)", text)
    assert m, "渲染脚本缺 BASE 定义"
    base_mm = float(m.group(1)) * 1e3
    assert base_mm == pytest.approx(1.1405, abs=1e-3)      # λ_sub/50 自动档
    assert "未定标档 clamp" in text                          # k(BASE) 域外旗
    r_eng = _r_eng(base_mm)
    assert r_eng == pytest.approx(_r_eng(AUDIT_BASE_MM), abs=1e-9)   # clamp 到 0.4 锚
    r_out = r_eng + W_RING / 2
    band = [b for b in boxes if _is_band_box(b)]
    assert band, "默认档环带盒缺失"
    # 1) 中心圈严格覆盖（无 halo，0.02° 步进）≥97%（实测 98.84%）
    step = 0.02
    n = int(360 / step)
    th = np.arange(n) * step
    px = r_eng * np.cos(np.deg2rad(th))
    py = r_eng * np.sin(np.deg2rad(th))
    bx0 = np.array([b[0] for b in band])
    bx1 = np.array([b[1] for b in band])
    by0 = np.array([b[2] for b in band])
    by1 = np.array([b[3] for b in band])
    hit = ((px[:, None] >= bx0[None, :]) & (px[:, None] <= bx1[None, :])
           & (py[:, None] >= by0[None, :]) & (py[:, None] <= by1[None, :]))
    covered = hit.any(axis=1)
    cov = float(covered.mean())
    assert cov >= 0.97, f"默认档中心圈覆盖 {cov * 100:.2f}% < 97%（环开路？）"
    assert cov == pytest.approx(0.9884, abs=2e-3)
    # 2) 90° 邻域（cap 区）必须覆盖：判据跳行未造成历史误判所述 83–97° 开路
    near90 = (np.abs(th - 90) <= 7) | (np.abs(th - 270) <= 7)
    assert covered[near90].all(), \
        "cap 区（83–97°/263–277°）中心圈存在缺口——与仲裁批实测不符"
    # 3) cap 缺口定量锁定：环带 y 向顶 = 最后一行上缘，缺口 ≤0.2·BASE
    y_top = max(max(b[3], -b[2]) for b in band)
    shortfall = r_out - y_top
    assert 0.0 <= shortfall <= 0.2 * base_mm, \
        f"cap 缺口 {shortfall:.4f}mm 超 0.2·BASE={0.2 * base_mm:.4f}mm"
    assert shortfall == pytest.approx(0.0651, abs=2e-3)
    # 4) 候选判据在默认档非无操作：每侧恰 1 行被跳过、其带内重叠 = 顶缺口
    extra = _candidate_criterion_extra_rows(ylines, r_eng)
    assert len(extra) == 2, f"默认档候选判据差集应为每侧 1 行，实测 {extra}"
    for _ya, _yb, ov in extra:
        assert ov == pytest.approx(shortfall, abs=1e-6)
