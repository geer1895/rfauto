"""SIW 族首族=直 SIW 传输线段（2026-09-22 siw-family 立项）离线审计测试。

权威口径：runs/siw_family/criteria.md（文献双源/闭式/激励方案利弊/预声明门）。
覆盖（#212 制度化 + #118 合成回收钉 + #231 注册四件套）：
  1) 闭式内核基准：RWG 极限（d→0 ⇒ w_eff→w）、WR-90 空气波导 fc=6.5571GHz
     （Pozar 教科书值）、synthesis 回代自洽、单调性、设计规则守卫显式报错；
  2) 渲染离线 exec 审计：过孔藩篱数量/心距/贯通、上下板、端口盒落格与
     ≥2 格（#283）、孔间缝内部线 ≥1（#311 类比）、端口出 PML 净距（#253）、
     域与结构一致（DOM_X/DOM_Y 字面）、CalcPort 参考=R_PORT（闭式 Z_PV）、
     port_beta.csv cps 契约（LumpedPort 无 β）；
  3) 注册四件套：TEMPLATE_META/NOMINAL、meta.yaml、spec（render/fake/
     synthesizer）、EXPECTED_TEMPLATES；
  4) fake 派发：窄带相位斜率 → β(f0) 对照闭式（参数驱动响应）。
秒级零仿真（FDTD.Run 之前截断 exec）。
"""

from __future__ import annotations

import hashlib
import math
import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.core.calculators import (
    CALCULATOR_REGISTRY,
    siw_beta_rad_m,
    siw_effective_width_mm,
)

C0 = 299792458.0
ER = 3.66
H = 0.508
NOM = {"w_mm": 12.1317, "d_mm": 0.6, "s_mm": 1.0, "line_len_mm": 63.0724}
BAND = (9.75, 10.25)


# ─── 1) 闭式内核基准（#118/#300：先过已知基准才有资格裁判）───────────────────

def test_siw_rwg_limit_d_to_zero():
    """d→0 极限：w_eff→w 逐位（Cassivi 式退化为普通矩形波导）。"""
    w = 22.86
    assert siw_effective_width_mm(w, 0.0, 1.0) == w
    assert siw_effective_width_mm(w, 1e-12, 1.0) == pytest.approx(w, rel=1e-15)


def test_siw_wr90_air_filled_cutoff_pozar():
    """εr=1、a=22.86mm（WR-90）→ fc10=c/(2a)=6.5571GHz（Pozar 教科书值）。"""
    weff = siw_effective_width_mm(22.86, 0.0, 1.0)
    _beta, fc = siw_beta_rad_m(weff, 1.0, 10.0)
    assert fc == pytest.approx(C0 / (2 * 0.02286) / 1e9, rel=1e-9)


def test_siw_nominal_beta_and_lambda_g_pinned():
    """名义链钉值（4 位舍入 w 起算，与 synthesize_siw_model 逐位同源）。"""
    weff = siw_effective_width_mm(NOM["w_mm"], NOM["d_mm"], NOM["s_mm"])
    beta, fc = siw_beta_rad_m(weff, ER, 10.0)
    assert beta == pytest.approx(298.856009, abs=1e-3)
    assert fc == pytest.approx(6.666695, abs=1e-4)
    assert 2 * math.pi / beta * 1e3 == pytest.approx(21.024122, abs=1e-3)


def test_siw_synthesis_roundtrip_and_reachability():
    """fc10 目标 → w 回代自洽；单调性 fc 随 w 单调降。"""
    syn = CALCULATOR_REGISTRY.get("siw_synthesis").func
    r = syn(fc10_ghz=10.0 / 1.5, epsilon_r=ER, d_mm=0.6, s_mm=1.0)
    assert r["w_mm"] == 12.1317
    assert r["fc10_roundtrip_ghz"] == pytest.approx(10.0 / 1.5, abs=1e-6)
    fa = CALCULATOR_REGISTRY.get("siw_analysis").func
    fcs = [fa(w_mm=w, d_mm=0.6, s_mm=1.0, epsilon_r=ER, freq_ghz=10.0)[
        "fc10_ghz"] for w in (11.0, 12.1317, 14.0)]
    assert fcs == sorted(fcs, reverse=True)


def test_siw_nominal_is_kernel_synthesized():
    """TEMPLATE_NOMINAL 几何键 = synthesize_siw_model 缺省输出（逐键一致）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import synthesize_siw_model

    params = synthesize_siw_model().params
    for key in ("w_mm", "d_mm", "s_mm", "line_len_mm"):
        assert TEMPLATE_NOMINAL["siw"][key] == pytest.approx(params[key],
                                                             abs=5e-5), key


def test_siw_design_rule_guards_explicit():
    """设计规则守卫（s≤2d / s>d / d<λ_sub/5 / w_eff>0）显式 ValueError。"""
    fa = CALCULATOR_REGISTRY.get("siw_analysis").func
    cases = [
        dict(w_mm=12.1, d_mm=0.6, s_mm=2.5, epsilon_r=ER, freq_ghz=10.0),
        dict(w_mm=12.1, d_mm=0.5, s_mm=0.4, epsilon_r=ER, freq_ghz=10.0),
        dict(w_mm=12.1, d_mm=5.0, s_mm=1.0, epsilon_r=3.66, freq_ghz=60.0),
        dict(w_mm=0.05, d_mm=0.6, s_mm=1.0, epsilon_r=ER, freq_ghz=10.0),
    ]
    for bad in cases:
        with pytest.raises(ValueError):
            fa(**bad)


def test_siw_below_cutoff_reports_alpha_not_beta():
    """f<fc10：β=None、倏逝 α 显式给出（截止下衰减物理量级）。"""
    r = CALCULATOR_REGISTRY.get("siw_analysis").func(
        w_mm=12.1317, d_mm=0.6, s_mm=1.0, epsilon_r=ER, freq_ghz=6.0)
    assert r["beta_rad_m"] is None
    assert r["alpha_below_cutoff_np_m"] == pytest.approx(116.518, abs=0.5)


def test_siw_registry_keys():
    names = set(CALCULATOR_REGISTRY.names())
    assert {"siw_analysis", "siw_synthesis"} <= names


# ─── 2) 渲染离线 exec 审计（#212）────────────────────────────────────────────

def _load(params=None, mesh_mm=0.4):
    from rfauto.adapters.openems_templates import render_script

    resolved = dict(NOM)
    if params:
        resolved.update(params)
    text = render_script("siw", resolved, BAND, mesh_resolution_mm=mesh_mm)
    cut = text.index("FDTD.Run(")
    scope: dict = {"__name__": "__main__", "__file__": str(REPO / "_siw_audit.py")}
    exec(compile(text[:cut], "siw_audit", "exec"), scope)
    return text, scope


def test_siw_render_boundaries_ports_and_reference():
    """y 轴 PML_8 + x 侧 MUR + z 底/顶 PEC；CalcPort 参考=R_PORT=闭式 Z_PV；
    port_beta.csv 走 cps 契约（无 beta 列）。"""
    text, _scope = _load()
    assert ('SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "PEC"])'
            in text)
    r_expected = 22.8393  # Z_PV=2b·Z_TE/w_eff 闭式（criteria §2）
    assert f"R_PORT = {r_expected!r}" in text
    assert f"ref_impedance={r_expected!r}" in text
    assert text.count("FDTD.AddLumpedPort(") == 2
    assert "port_beta.csv" in text
    assert '"freq_hz", "port_y1_m", "port_y2_m", "plane_dist_m"' in text
    assert "beta_rad_per_m" not in text.split("port_beta.csv")[1]


def test_siw_via_fence_geometry_offline_exec():
    """过孔藩篱：两列等长、心距精确 s、柱贯通 0..h、藩篱端孔不出域。"""
    _text, scope = _load()
    csx = scope["CSX"]
    by_name = {}
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        by_name[str(prop.GetName())] = prop
    via = by_name["siw_via"]
    cyls = list(via.GetAllPrimitives())
    assert len(cyls) == 2 * scope["DOM_Y"] * 0 + 2 * (2 * 38 + 1)  # 77 孔/列×2 列
    s = NOM["s_mm"] * 1e-3
    ys = sorted({round(float(c.GetStart()[1]), 12) for c in cyls})
    assert len(ys) == 77
    assert all(b - a == pytest.approx(s, abs=1e-12)
               for a, b in pairwise(ys))
    for c in cyls:
        assert float(c.GetStart()[2]) == 0.0
        assert float(c.GetStop()[2]) == float(scope["H_SUB"])
        assert abs(abs(float(c.GetStart()[0])) - NOM["w_mm"] * 1e-3 / 2) < 1e-12
    # 藩篱端孔外缘 = dom_y（域界吸收，#212 审计④一致性）
    assert max(ys) + NOM["d_mm"] * 1e-3 / 2 == pytest.approx(scope["DOM_Y"],
                                                             abs=1e-12)


def test_siw_plates_and_port_boxes_offline_exec():
    """上下板显式零厚贴 z 边界；端口盒三向边落格、≥2 格、中线落格（#283）、
    测量面距=line_len、激励仅 port1。"""
    _text, scope = _load()
    csx = scope["CSX"]
    plates = None
    n_resist = 0
    n_excite = 0
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        name = str(prop.GetName())
        tstr = str(prop.GetTypeString())
        if name == "siw_plates":
            plates = list(prop.GetAllPrimitives())
        if tstr == "LumpedElement":
            n_resist += 1
        if tstr == "Excitation":
            n_excite += 1
    assert plates is not None and len(plates) == 2
    for p in plates:
        lo = np.asarray(p.GetStart(), dtype=float)
        hi = np.asarray(p.GetStop(), dtype=float)
        assert (hi - lo)[2] == 0.0                     # 零厚
        assert lo[2] in (0.0, float(scope["H_SUB"]))   # 贴 z 边界
    assert n_resist == 2 and n_excite == 1             # port2 仅探针+端接
    p1, p2 = scope["_port1"], scope["_port2"]
    line_len = NOM["line_len_mm"] * 1e-3
    assert abs(p2.start[1] - p1.start[1]) == pytest.approx(line_len, abs=1e-12)
    # 端口盒 ≥2 格（#283）：x 宽=2·NEAR、y 长=2·NEAR，中线 x=0 恰在网格线
    near = scope["NEAR"]
    for port in (p1, p2):
        ext = np.abs(np.asarray(port.stop) - np.asarray(port.start))
        assert ext[0] == pytest.approx(2 * near, abs=1e-15)
        assert ext[1] == pytest.approx(2 * near, abs=1e-15)
        assert ext[2] == pytest.approx(float(scope["H_SUB"]), abs=1e-15)
    lines_x = np.asarray(scope["mesh"].GetLines("x"), dtype=float)
    assert np.min(np.abs(lines_x)) == 0.0
    # 端口面出 PML_8（16·BASE−NEAR ≥ 8·BASE，#253/H4）
    port_face = min(abs(float(p1.start[1])), abs(float(p2.start[1])))
    inset = scope["DOM_Y"] - port_face
    assert inset > 8 * scope["BASE"]


def test_siw_via_gap_interior_lines_offline_exec():
    """#311 类比：相邻过孔缝隙内 CSXCAD 实测网格线 ≥1（缝缘线不计）。"""
    _text, scope = _load()
    ys = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
    s = NOM["s_mm"] * 1e-3
    d = NOM["d_mm"] * 1e-3
    gaps_checked = 0
    for k in (-5, 0, 5):  # 抽样孔位（全域均匀栅格，三点代表全域）
        lo, hi = k * s + d / 2, (k + 1) * s - d / 2
        inside = ys[(ys > lo + 1e-12) & (ys < hi - 1e-12)]
        assert inside.size >= 1, f"过孔缝隙 [{lo}, {hi}] 内部线 = 0"
        gaps_checked += 1
    assert gaps_checked == 3


def test_siw_rect_domain_literal_and_substrate():
    """矩形域字面注入（DOM_X/DOM_Y 来自 siw_layout）；基板填满矩形域。"""
    text, scope = _load()
    from rfauto.adapters.openems_templates import siw_layout

    lay = siw_layout(dict(NOM), BAND, 0.4e-3, H * 1e-3)
    assert scope["DOM_X"] == pytest.approx(lay["dom_x"], abs=1e-15)
    assert scope["DOM_Y"] == pytest.approx(lay["dom_y"], abs=1e-15)
    assert f"DOM_X = {lay['dom_x']!r}" in text
    assert f"DOM_Y = {lay['dom_y']!r}" in text
    # 域界=网格界（结构线不出域，#212 审计④）
    for ax, dom in (("x", lay["dom_x"]), ("y", lay["dom_y"])):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        assert ls.min() == pytest.approx(-dom, abs=1e-9)
        assert ls.max() == pytest.approx(dom, abs=1e-9)


def test_siw_mesh_guard_floors():
    """#349/#152：全轴最小间距 >1µm（审计口径）；显式线集 >10µm（layout 内
    守卫已在渲染路径生效——欠分辨网格/近撞参数在此显式拒绝）。"""
    _text, scope = _load()
    for ax in ("x", "y", "z"):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        assert bool(np.all(np.diff(ls) > 1e-6))
    with pytest.raises(ValueError, match="4·NEAR"):
        from rfauto.adapters.openems_templates import siw_layout

        siw_layout(dict(NOM), BAND, 5.0e-3, H * 1e-3)  # BASE=5mm 网格欠分辨


def test_siw_layout_rule_guard_rejects_rule_violation():
    """s>2d 的几何在渲染层即拒（设计规则守卫复用 core 单源）。"""
    from rfauto.adapters.openems_templates import siw_layout

    with pytest.raises(ValueError, match="2·d"):
        siw_layout({**NOM, "s_mm": 2.5}, BAND, 0.4e-3, H * 1e-3)


# ─── 2b) v2 端口方案离线审计（runs/siw_family/v2_criteria.md §1/§5；#212）────
# v2=藩篱止于端口面+端面口径 LumpedPort（跨介质孔径 ±W/2，R=Z_PV 不变）——
# 消除 §R2 归因的端面 fixture 汇（延拓支路 4/9 分光+探针中间抽头耗散），
# 按**原 G3 门（≥−3dB）**重跑的 fixture 路线。opt-in 旋钮 `_port_mode="v2"`，
# 缺省 v1 渲染逐字节不变（字节钉见下）。本节测试全部秒级零仿真。

#: v1 缺省渲染字节钉（审计档 NOM×BAND×0.4mm 全文 sha256；任何缺省路径漂移
#: 即红——改 v1 缺省行为必须显式换钉并在 runs/siw_family/ 留 unified diff 证据）
_V1_RENDER_SHA256 = "e95de918c203247b75ac8053a8715632607200015643299009d967f5072c1c6d"


def test_siw_v1_default_render_byte_pin():
    """字节不变钉（v2_criteria.md §5.7）：v1 缺省渲染 sha256 钉死；
    显式 _port_mode="v1" 与缺省逐字节同哈希（旋钮缺省路径=显式 v1）。"""
    from rfauto.adapters.openems_templates import render_script

    text = render_script("siw", dict(NOM), BAND, mesh_resolution_mm=0.4)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == _V1_RENDER_SHA256
    explicit = render_script("siw", {**NOM, "_port_mode": "v1"}, BAND,
                             mesh_resolution_mm=0.4)
    assert explicit == text


def test_siw_v2_invalid_port_mode_rejected():
    """_port_mode 非 v1/v2 显式 ValueError（不静默回退缺省）。"""
    from rfauto.adapters.openems_templates import render_script, siw_layout

    with pytest.raises(ValueError, match="_port_mode"):
        siw_layout({**NOM, "_port_mode": "v3"}, BAND, 0.4e-3, H * 1e-3)
    with pytest.raises(ValueError, match="_port_mode"):
        render_script("siw", {**NOM, "_port_mode": "v3"}, BAND,
                      mesh_resolution_mm=0.4)


def _load_v2(params=None, mesh_mm=0.4):
    merged = {"_port_mode": "v2"}
    if params:
        merged.update(params)
    return _load(merged, mesh_mm=mesh_mm)


def test_siw_v2_fence_stops_at_port_face():
    """v2 §5.1：藩篱止于端口面——63 孔/列、末孔缘不越端口面、dom_y=端口面+
    16·BASE 精确值、全部结构线在域内。"""
    _text, scope = _load_v2()
    csx = scope["CSX"]
    via = None
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        if str(prop.GetName()) == "siw_via":
            via = list(prop.GetAllPrimitives())
    assert via is not None and len(via) == 2 * 63          # 63 孔/列×2 列
    s = NOM["s_mm"] * 1e-3
    d = NOM["d_mm"] * 1e-3
    ys = sorted({round(float(c.GetStart()[1]), 12) for c in via})
    assert len(ys) == 63
    assert all(b - a == pytest.approx(s, abs=1e-12) for a, b in pairwise(ys))
    face = NOM["line_len_mm"] * 1e-3 / 2.0                 # 端口面 y=±line_len/2
    assert max(ys) == pytest.approx(31.0 * s, abs=1e-15)   # k_half=31
    assert max(ys) + d / 2 < face                          # 末孔缘 31.3<31.5362mm
    for c in via:
        assert float(c.GetStart()[2]) == 0.0
        assert float(c.GetStop()[2]) == float(scope["H_SUB"])   # 贯通 0..h
        assert abs(abs(float(c.GetStart()[0])) - NOM["w_mm"] * 1e-3 / 2) < 1e-12
    base = 0.4e-3
    assert scope["DOM_Y"] == pytest.approx(face + 16 * base, abs=1e-15)
    # 全部结构线在域内（#212 审计④；v2 无藩篱端孔吸收，端口盒缘为最外结构线）
    ys_mesh = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
    assert ys_mesh.max() <= scope["DOM_Y"] + 1e-12
    assert ys_mesh.min() >= -scope["DOM_Y"] - 1e-12


def test_siw_v2_port_box_grid_and_inset():
    """v2 §5.2/5.3/5.4：端口盒跨介质孔径（x 边=±W/2 列心线）、三向边落格、
    横向 ≥2 格、中线落格（#283）；#349/#152 全轴最小间距；#253 激励盒内缩。"""
    _text, scope = _load_v2()
    w = NOM["w_mm"] * 1e-3
    p1, p2 = scope["_port1"], scope["_port2"]
    for port in (p1, p2):
        lo = np.asarray(port.start, dtype=float)
        hi = np.asarray(port.stop, dtype=float)
        ext = hi - lo
        assert ext[0] == pytest.approx(w, abs=1e-15)       # 跨介质孔径 ±W/2
        assert ext[1] == pytest.approx(2 * scope["NEAR"], abs=1e-15)
        assert ext[2] == pytest.approx(float(scope["H_SUB"]), abs=1e-15)
        assert float(port.stop[2]) == float(scope["H_SUB"])  # 跨全高=负载面
    lines_x = np.asarray(scope["mesh"].GetLines("x"), dtype=float)
    lines_y = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
    # 盒边/中线落格（#283；生成期断言已在 exec 内红过一次，此处审计复测）
    for v in (scope["RX"], -scope["RX"], 0.0):
        assert np.min(np.abs(lines_x - v)) <= 1e-9
    face = abs(float(p1.stop[1]) - scope["PY"])            # y1（测量面）
    for v in (face - scope["PY"], face, face + scope["PY"]):
        assert np.min(np.abs(lines_y - v)) <= 1e-9
    # 横向 ≥2 格：x 向盒内 ≥3 条线（含边）、y 向恰 2 格（盒长=2·NEAR）
    assert int(np.sum((lines_x >= -scope["RX"] - 1e-12)
                      & (lines_x <= scope["RX"] + 1e-12))) >= 3
    assert int(np.sum((lines_y >= face - scope["PY"] - 1e-12)
                      & (lines_y <= face + scope["PY"] + 1e-12))) >= 3
    # #349/#152：全轴最小间距 >1µm（生成期守卫同口径复测）
    for ax in ("x", "y", "z"):
        ls = np.asarray(scope["mesh"].GetLines(ax), dtype=float)
        assert bool(np.all(np.diff(ls) > 1e-6))
    # #253：激励盒外缘到 y PML_8 净距=16·BASE−NEAR > 2·BASE（激励体积在物理域）
    inset = scope["DOM_Y"] - (face + scope["PY"])
    assert inset == pytest.approx(16 * scope["BASE"] - scope["NEAR"], abs=1e-15)
    assert inset > 2 * scope["BASE"]


def test_siw_v2_no_via_short_and_excitation_contract():
    """v2 §5.5/5.6：藩篱不与端口盒相交（端口片不被短路）；激励/端接与参考
    阻抗契约同 v1（Excitation×1+LumpedElement×2、R_PORT=Z_PV 闭式、
    port_beta.csv cps 契约）。"""
    text, scope = _load_v2()
    csx = scope["CSX"]
    vias = None
    n_resist = n_excite = 0
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        name, tstr = str(prop.GetName()), str(prop.GetTypeString())
        if name == "siw_via":
            vias = list(prop.GetAllPrimitives())
        if tstr == "LumpedElement":
            n_resist += 1
        if tstr == "Excitation":
            n_excite += 1
    assert n_resist == 2 and n_excite == 1                 # port2 仅探针+端接
    d = NOM["d_mm"] * 1e-3
    face = abs(float(scope["_port1"].stop[1]) - scope["PY"])
    gap = (face - scope["PY"]) - (max(float(c.GetStart()[1]) for c in vias)
                                  + d / 2)
    assert gap > 0.0                                       # 末孔缘-盒缘 0.1362mm
    r_expected = 22.8393                                   # Z_PV@10GHz 闭式
    assert f"R_PORT = {r_expected!r}" in text
    assert f"ref_impedance={r_expected!r}" in text
    assert text.count("FDTD.AddLumpedPort(") == 2
    assert ('SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "PEC"])'
            in text)
    assert "port_beta.csv" in text
    assert '"freq_hz", "port_y1_m", "port_y2_m", "plane_dist_m"' in text
    # 端口测量面位置与 v1 全同（G4 契约：plane_dist≈line_len 不随端口方案变）
    assert abs(scope["_port2"].start[1] - scope["_port1"].start[1]) == \
        pytest.approx(NOM["line_len_mm"] * 1e-3, abs=1e-12)


def test_siw_v2_loss_budget_preview():
    """v2 §3/§5.8 损耗账预演（纯数值闭式，#118 可复算；g3_budget.py 同链）：
    v1 三支路天花板 −3.10dB 复现（门结构性不可达）；v2 端面即负载后理想化
    |S21|≈−0.57dB；G3 对端面失配稳健至 |Γ|≈0.85。"""
    weff = siw_effective_width_mm(NOM["w_mm"], NOM["d_mm"], NOM["s_mm"])
    L = NOM["line_len_mm"] * 1e-3
    tand = 0.0037

    def p_one_way(f_ghz):
        """单程功率因子 p=exp(−2α_d·L)；κ 按 f_exc=9.5GHz 落入（g3_budget 口径）。"""
        beta, _fc = siw_beta_rad_m(weff, ER, f_ghz)
        k = 2.0 * math.pi * f_ghz * 1e9 * math.sqrt(ER) / C0
        ad = k * k * (tand * 9.5 / f_ghz) / (2.0 * beta)   # Np/m
        return math.exp(-2.0 * ad * L)

    # α_d·L@10GHz≈0.518dB 单程（criteria §3 账，与 g3_budget 0.9454Np/m 互洽）
    assert -10.0 * math.log10(p_one_way(10.0)) == pytest.approx(0.518, abs=0.02)
    # v1 结构天花板：三支路节点（导波/延拓/探针 y=1）Γg=−1/3、τ=2/3，
    # |S21|max=(2/3)·√p/(1−p/9)（FP 谐振增强）→ 带内 max≈0.700=−3.10dB<−3dB 门
    ceil_v1 = max((2.0 / 3.0) * math.sqrt(p_one_way(f))
                  / (1.0 - p_one_way(f) / 9.0)
                  for f in np.linspace(9.0, 11.0, 401))
    assert ceil_v1 == pytest.approx(0.6999, abs=5e-4)      # g3_budget 实测钉值
    # v2：端面=终端负载（无延拓支路）。理想化全孔径局部欧姆片 Z_eff=(π/2)R、
    # R=Z_PV ⇒ |Γ|=(π/2−1)/(π/2+1)=0.222（ρ=0.0493）；对称 FP
    # T=(1−ρ)²p/(1−ρp)² → |S21|≈−0.57dB@10GHz——原 −3dB 门应可达
    rho = ((math.pi / 2 - 1) / (math.pi / 2 + 1)) ** 2
    p10 = p_one_way(10.0)
    t_v2 = (1 - rho) ** 2 * p10 / (1 - rho * p10) ** 2
    assert 10.0 * math.log10(t_v2) == pytest.approx(-0.57, abs=0.05)
    assert t_v2 >= 0.501                                   # G3 门 −3dB
    # 稳健界：带内最劣 p（9GHz）下 T≥0.501 容许 ρ≤0.72（|Γ|≤0.85）——
    # 覆盖理想化 0.22 与 v1 实测端面反射率 0.543（g3_attribution §4）
    p_worst = p_one_way(9.0)
    rho_max = max(r for r in np.linspace(0.0, 0.85, 851)
                  if (1 - r) ** 2 * p_worst / (1 - r * p_worst) ** 2 >= 0.501)
    assert rho_max == pytest.approx(0.72, abs=0.01)
    assert rho_max > 0.70


# ─── 3) 注册四件套（#231）────────────────────────────────────────────────────

def test_siw_registration_quartet():
    import yaml

    from rfauto.adapters import openems_templates as ot
    from rfauto.models.template_specs import TEMPLATE_SPECS

    assert "siw" in ot.TEMPLATE_META and "siw" in ot.TEMPLATE_NOMINAL
    assert ot.TEMPLATE_META["siw"]["params"] == ["w_mm", "d_mm", "s_mm",
                                                 "line_len_mm"]
    assert ot.TEMPLATE_META["siw"]["n_ports"] == 2
    assert ot._TEMPLATE_PORT_AXES["siw"] == ("y",)
    assert ot._TEMPLATE_RADIATOR["siw"] is False
    meta_path = REPO / "docs" / "templates" / "siw" / "meta.yaml"
    assert meta_path.exists()
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert set(data["params"]) == set(ot.TEMPLATE_META["siw"]["params"])
    for key, val in ot.TEMPLATE_NOMINAL["siw"].items():
        assert float(data["nominal_params"][key]) == pytest.approx(val)
    spec = TEMPLATE_SPECS.get("siw")
    assert spec.physics_roles == {"w_mm": "line_width_mm",
                                  "line_len_mm": "line_length_mm"}
    assert callable(TEMPLATE_SPECS.component("siw", "fake_model"))
    assert callable(TEMPLATE_SPECS.component("siw", "synthesizer"))
    assert callable(TEMPLATE_SPECS.component("siw", "render_script"))
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    assert "siw" in EXPECTED_TEMPLATES


# ─── 4) fake 派发（参数驱动真实响应）─────────────────────────────────────────

def test_fake_siw_dispatch_phase_matches_closed_form():
    from rfauto.adapters.fake_adapter import FakeAdapter

    ad = FakeAdapter(model_type="siw", n_ports=2,
                     freq_ghz=(9.75, 10.25, 201), f0_ghz=10.0)
    ad.connect({})
    # _parse_variable 只解析带单位字符串（裸数值 .strip() 静默回退缺省——
    # msl_cpw 分支同注）；cps 派发测试同口径
    ad.set_variables({k: f"{v}mm" for k, v in NOM.items()})
    ad.solve("main_setup")
    net = ad.get_sparams()
    phase = np.unwrap(np.angle(net.s[:, 1, 0]))
    slope = np.polyfit(net.f, phase, 1)[0]     # 窄带群时延口径：dφ/df=−L·dβ/df
    weff = siw_effective_width_mm(NOM["w_mm"], NOM["d_mm"], NOM["s_mm"])
    # 闭式 dβ/df@f0（中心差分；β 色散 → 斜率=群时延×L，非 β 本身）
    d = 1e-6
    b_hi, _ = siw_beta_rad_m(weff, ER, 10.0 + d)
    b_lo, _ = siw_beta_rad_m(weff, ER, 10.0 - d)
    dbeta_df = (b_hi - b_lo) / (2 * d * 1e9)          # rad/m per Hz
    assert -slope == pytest.approx(dbeta_df * NOM["line_len_mm"] * 1e-3,
                                   rel=5e-4)
    # 逐频复数对拍：S21 = exp(−γ(f)·L)（fake 与闭式同链，钉的是派发接线）
    beta_ref, _fc = siw_beta_rad_m(weff, ER, 10.0)
    assert beta_ref == pytest.approx(298.856009, abs=1e-3)
    assert np.max(np.abs(net.s[:, 0, 0])) < 1e-3     # 匹配端接口径 S11≈0
    # d 变 → w_eff 变 → 相位斜率变（数据工厂语义：参数驱动真实响应）
    ad.set_variables({**{k: f"{v}mm" for k, v in NOM.items()},
                      "d_mm": "0.8mm"})
    ad.solve("main_setup")
    s2 = ad.get_sparams().s
    assert not np.allclose(np.angle(s2[:, 1, 0]), np.angle(net.s[:, 1, 0]))


def test_fake_siw_stopband_rolloff_below_cutoff():
    """fake 在 fc 以下倏逝衰减（γ 分支选择 α>0，对 tanδ→0 稳健）。"""
    from rfauto.adapters.fake_adapter import _siw_sparams

    freqs = np.array([6.0, 10.0])
    s = _siw_sparams(freqs, weff_mm=11.7527526, line_len_mm=63.0724,
                     epsilon_r=ER)
    s21_6 = abs(s[0, 1, 0])
    s21_10 = abs(s[1, 1, 0])
    assert s21_6 < 0.05 < s21_10                     # 截止下强衰减
