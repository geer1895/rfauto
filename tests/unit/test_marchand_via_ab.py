"""C12 过孔 PEC 薄片单变量对照（Marchand −18% 归因）：旋钮/几何/归因单测。

裁判分层（#118 不自证）：
- 旋钮缺省逐字节不变（缺省 vs 显式 rod 全文相同；rod vs sheet 全文 diff 恰=
  VIA_MODE 行+过孔原语段，#312 同款）；
- 几何=exec 渲染文本（FDTD.Run 截断，#212 零仿真）读原语实测：rod 柱体
  0.25mm 方柱落格（#283 三线齐备+区间 ≥2）、sheet 零 x 厚墙全臂宽，两模式
  网格逐值相等（单变量）；网格/布局数值对照烟测证据 audit_mesh.json 硬钉；
- 归因=合成回收：电路级理论谷（core 耦合线 Z 矩阵+jωL 负载约束）在 L=0 钉
  f0、L=0.7nH 复现 HFSS −18%（2.046GHz），反演 roundtrip+方向守卫+归因表
  三分支（CONFIRMED/FALSIFIED/INCONCLUSIVE）；
- 主判估计量=理想 3dB 分馈合成用例回收（Zin/功率法驻波免疫口径）。
"""

from __future__ import annotations

import difflib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import marchand_via_ab as ab
from rfauto.adapters.openems_templates import (
    MARCHAND2_VIA_MODES,
    marchand2_via_geometry,
    render_marchand2_script,
)
from rfauto.core.slotline_transitions import (
    marchand_two_section_nominal,
    marchand_two_section_sparams,
)

_FREQ = (2.0, 4.2)


def _norm(line: str) -> str:
    return " ".join(line.split())


# ─── ① 旋钮：缺省逐字节不变 + diff 恰过孔段（#312 同款） ─────────────────────

def test_render_default_matches_explicit_rod_byte_identical():
    """缺省（不传 via_mode）与显式 via_mode='rod' 渲染全文逐字节相同。"""
    assert render_marchand2_script(_FREQ) == \
        render_marchand2_script(_FREQ, via_mode="rod")


def test_invalid_via_mode_and_side_raise():
    with pytest.raises(ValueError, match="via_mode"):
        render_marchand2_script(_FREQ, via_mode="cyl")
    with pytest.raises(ValueError, match="via_side_mm"):
        render_marchand2_script(_FREQ, via_side_mm=0.0)
    with pytest.raises(ValueError, match="via_mode"):
        marchand2_via_geometry("3d")
    assert MARCHAND2_VIA_MODES == ("rod", "sheet")


def test_diff_rod_sheet_is_via_segment_only():
    """rod vs sheet 渲染全文 diff 恰=过孔段（VIA_MODE 行+过孔原语，#312 同款）。"""
    rod = render_marchand2_script(_FREQ).splitlines()
    sheet = render_marchand2_script(_FREQ, via_mode="sheet").splitlines()
    changed = [ln for ln in difflib.unified_diff(rod, sheet, lineterm="", n=0)
               if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    assert changed, "两变体渲染文本无差异（旋钮失效？）"
    tokens = ("VIA", "via", "薄片", "过孔", "短路", "Y_S1", "Y_S2", "rod", "sheet")
    for ln in changed:
        assert any(t in ln for t in tokens), f"diff 含非过孔段行：{ln!r}"
    # 过孔原语段各恰 4 行（两短路位 × 两行）
    rod_via = [ln for ln in changed if ln.startswith("-")]
    sheet_via = [ln for ln in changed if ln.startswith("+")]
    assert len(rod_via) == 5 and len(sheet_via) == 5   # VIA_MODE 行 + 4 几何行


# ─── ② rod 缺省=烟测口径（golden 语句 + 数值硬钉） ────────────────────────────

#: golden 语句（runs/smoke_marchand_2sect/render_run.py @ 落档版，2026-09-21 钉；
#: 空白归一比对——模块级流缩进少 4 空格，语句内容逐词同文；csx→CSX 系模块级
#: 变量名重命名，该行不在此列、由 exec 数值断言兜底）
_SMOKE_GOLDEN = (
    "via1_c = VIA1_C",
    "x_lines = [-XDOM, DOM_X, X_E, X_E + L_PORT,",
    "XA, XA + VIA / 2, XA + VIA, # 过孔 1（x 边+中线）",
    "XC - VIA, XC - VIA / 2, XC] # 过孔 2",
    "mesh.AddLine(ax, np.asarray(sorted(set(pts)), dtype=float))",
    "mesh.SmoothMeshLines(ax, NEAR)",
    "mesh.SmoothMeshLines(ax, BASE)",
    'msl.AddBox((-DOM_X, Y_M_LO, H), (XC, Y_M_HI, H), priority=10) # 主线',
    'msl.AddBox((XA, Y_S1_LO, H), (XB, Y_S1_HI, H), priority=10) # 副 1',
    'msl.AddBox((XB, Y_S2_LO, H), (XC, Y_S2_HI, H), priority=10) # 副 2',
    "msl.AddBox((XA, via1_c - VIA / 2, 0.0), (XA + VIA, via1_c + VIA / 2, H),",
    "msl.AddBox((XC - VIA, -via1_c - VIA / 2, 0.0), (XC, -via1_c + VIA / 2, H), priority=10) # 过孔 2",
    'p1 = MSLPort(CSX, port_nr=1, metal_prop=msl,',
    "FeedShift=10 * NEAR, MeasPlaneShift=MEAS_SHIFT, priority=10)",
    'p2 = LumpedPort(CSX, 2, 140.0,',
    'p3 = LumpedPort(CSX, 3, 140.0,',
    '"z", excite=0, priority=5)',
    "FDTD.SetBoundaryCond([\"PML_8\", \"PML_8\", \"PML_8\", \"PML_8\", \"MUR\", \"MUR\"])",
)


def test_rod_golden_statements_from_smoke_present():
    text = render_marchand2_script(_FREQ)
    norm = _norm(text)
    for g in _SMOKE_GOLDEN:
        assert _norm(g) in norm, f"烟测 golden 语句缺失：{g!r}"


# ─── ③ exec 几何审计（零仿真；#212 原语实测 + #283 落格） ─────────────────────

def _exec_variant(tmp_path: Path, mode: str, monkeypatch) -> dict:
    monkeypatch.delenv("RFAUTO_SKIP_RUN", raising=False)
    text = render_marchand2_script(_FREQ, via_mode=mode)
    vd = tmp_path / mode
    vd.mkdir()
    path = vd / "render_script.py"
    path.write_text(text, encoding="utf-8")
    cut = text.index("FDTD.Run(")
    scope: dict = {"__name__": "__main__", "__file__": str(path)}
    exec(compile(text[:cut], str(path), "exec"), scope)
    assert (vd / "audit_mesh.json").exists()
    audit = json.loads((vd / "audit_mesh.json").read_text(encoding="utf-8"))
    return {"scope": scope, "audit": audit, "text": text}


def _metal_boxes(scope: dict) -> list[tuple[np.ndarray, np.ndarray]]:
    csx = scope["CSX"]
    out = []
    for i in range(csx.GetQtyProperties()):
        prop = csx.GetProperty(i)
        if str(prop.GetTypeString()) != "Metal":
            continue
        for prim in prop.GetAllPrimitives():
            if hasattr(prim, "GetStart"):
                s = np.asarray(prim.GetStart(), dtype=float)
                e = np.asarray(prim.GetStop(), dtype=float)
                out.append((np.minimum(s, e), np.maximum(s, e)))
    return out


def test_exec_rod_geometry_and_grid_matches_smoke(tmp_path, monkeypatch):
    """rod：柱实体尺寸/位置逐值断言 + 落格 + 网格/布局=烟测证据硬钉。"""
    got = _exec_variant(tmp_path, "rod", monkeypatch)
    audit, scope = got["audit"], got["scope"]
    assert audit["all_pass"] is True
    assert audit["via"]["mode"] == "rod"
    # 网格/布局与烟测证据 audit_mesh.json 硬钉（2026-09-21 实测读回）
    assert audit["mesh_lines"] == {"x": 313, "y": 87, "z": 77}
    for ax, um in (("x", 104.47), ("y", 50.8), ("z", 250.0)):
        assert abs(audit["min_span_m"][ax] * 1e6 - um) < 0.01
    lay = audit["layout_m"]
    assert abs(lay["BASE"] - 299792458.0 / 3.0e9 / math.sqrt(3.66) / 50.0) < 1e-12
    assert abs(lay["XDOM"] - 0.026626) < 1e-6
    assert abs(lay["DOM_X"] - 0.042934) < 1e-6
    assert abs(lay["X_E"] - (-0.012)) < 1e-9
    # 原语实测：两根 0.25mm 方柱贯通 z∈[0,H]，中心 y=±(w+s)
    nom = marchand_two_section_nominal().nominal_params()
    w, s = nom["w_mm"] * 1e-3, nom["s_mm"] * 1e-3
    l_sect = nom["l_sect_mm"] * 1e-3
    h = 1.524e-3                      # = MARCHAND2_NOMINAL_INPUTS["h_mm"]
    via, c = 0.25e-3, w + s
    rods = [b for b in _metal_boxes(scope)
            if abs((b[1][0] - b[0][0]) - via) < 1e-12
            and abs((b[1][1] - b[0][1]) - via) < 1e-12]
    assert len(rods) == 2
    lo = min(rods, key=lambda b: b[0][1])
    hi = max(rods, key=lambda b: b[0][1])
    assert np.allclose(lo[0], [2 * l_sect - via, -c - via / 2, 0.0])
    assert np.allclose(lo[1], [2 * l_sect, -c + via / 2, h])
    assert np.allclose(hi[0], [0.0, c - via / 2, 0.0])
    assert np.allclose(hi[1], [via, c + via / 2, h])
    # 落格：过孔 6 线齐备 + 足印内网格区间 ≥2（#283 严格 > 口径）
    mesh = scope["mesh"]
    for ax, vals in (("x", (0.0, via / 2, via)),
                     ("y", (c - via / 2, c, c + via / 2))):
        ls = np.asarray(mesh.GetLines(ax), dtype=float)
        for v in vals:
            assert np.any(np.abs(ls - v) <= 1e-6), f"{ax} 轴缺过孔线 {v}"
            inner = int(np.sum((ls > min(vals) + 1e-6) & (ls < max(vals) - 1e-6)))
        assert inner + 1 >= 2
    # summary/audit 记录生效值（#283）
    assert "via_mode" in got["text"] and "via_side_mm" in got["text"]
    assert "nrts_declared" in got["text"] and "base_mm" in got["text"]


def test_exec_sheet_walls_and_mesh_identity(tmp_path, monkeypatch):
    """sheet：零 x 厚墙全臂宽/贴 z 两端 + 与 rod 网格逐值相等（单变量）。"""
    rod = _exec_variant(tmp_path, "rod", monkeypatch)
    sheet = _exec_variant(tmp_path, "sheet", monkeypatch)
    assert sheet["audit"]["all_pass"] is True
    assert sheet["audit"]["via"]["mode"] == "sheet"
    walls = [b for b in _metal_boxes(sheet["scope"])
             if abs(b[1][0] - b[0][0]) < 1e-12
             and abs(b[0][2]) < 1e-12 and abs(b[1][2] - 1.524e-3) < 1e-12
             and (b[1][1] - b[0][1]) > 0.0]
    assert len(walls) == 2, "薄片短路墙应为两面零 x 厚盒"
    nom = marchand_two_section_nominal().nominal_params()
    w, s = nom["w_mm"] * 1e-3, nom["s_mm"] * 1e-3
    l_sect = nom["l_sect_mm"] * 1e-3
    by_y = sorted(walls, key=lambda b: b[0][1])
    assert np.allclose(by_y[0][0], [2 * l_sect, -3 * w / 2 - s, 0.0])
    assert np.allclose(by_y[0][1], [2 * l_sect, -w / 2 - s, 1.524e-3])
    assert np.allclose(by_y[1][0], [0.0, w / 2 + s, 0.0])
    assert np.allclose(by_y[1][1], [0.0, 3 * w / 2 + s, 1.524e-3])
    # 与主线间隙 = s（薄片不短路耦合缝）
    assert abs((by_y[1][0][1] - w / 2) - s) < 1e-12
    assert abs((-w / 2 - by_y[0][1][1]) - s) < 1e-12
    # 单变量：两模式网格线逐值相等（rod 专属线在 sheet 保留为纯加密）
    for ax in "xyz":
        assert np.array_equal(np.asarray(rod["scope"]["mesh"].GetLines(ax)),
                              np.asarray(sheet["scope"]["mesh"].GetLines(ax))), ax
    assert rod["audit"]["mesh_lines"] == sheet["audit"]["mesh_lines"]


def test_via_guard_bites_on_displaced_rod(tmp_path, monkeypatch):
    """守卫非恒真：柱位置被篡改的渲染文本 exec 后 all_pass=False（不起跑）。"""
    monkeypatch.delenv("RFAUTO_SKIP_RUN", raising=False)
    text = render_marchand2_script(_FREQ, via_mode="rod")
    bad = text.replace("msl.AddBox((XA, via1_c - VIA / 2, 0.0), (XA + VIA, via1_c + VIA / 2, H),",
                       "msl.AddBox((XA, via1_c + VIA, 0.0), (XA + VIA, via1_c + 2 * VIA, H),")
    assert bad != text, "篡改锚未命中"
    path = tmp_path / "bad_render.py"
    path.write_text(bad, encoding="utf-8")
    scope: dict = {"__name__": "__main__", "__file__": str(path)}
    with pytest.raises(SystemExit) as ei:      # 审计 FAIL → 渲染脚本 rc=2 不起跑
        exec(compile(bad[:bad.index("FDTD.Run(")], str(path), "exec"), scope)
    assert ei.value.code == 2
    audit = scope["audit"]
    assert audit["all_pass"] is False
    guard = audit["via_guard"]
    assert guard["rod1_pos"] is False or guard["rod1_in_sub1"] is False


# ─── ④ 归因纯逻辑：理论谷钉 + 合成回收（#118） ────────────────────────────────

def test_theory_null_ideal_short_at_f0():
    assert abs(ab.theory_null_ghz(0.0) - 2.5) < 1e-6


def test_theory_null_l07nh_reproduces_hfss_minus18pct():
    """电路级 L=0.7nH → 谷 2.046GHz：HFSS 巴伦锚 −18% 的定量复现（预判钉）。"""
    f_null = ab.theory_null_ghz(ab.THEORY_L_VIA_NH * 1e-9)
    assert abs(f_null - 2.046) < 0.005
    dev_pct = (f_null - 2.5) / 2.5 * 100.0
    assert abs(dev_pct - (-18.2)) < 0.3


def test_via_circuit_s11_l0_matches_core_sparams():
    """l_via=0 与 core marchand_two_section_sparams 逐位同解（同构自检）。"""
    f = np.array([2.0, 2.25, 2.5, 2.75, 3.0])
    s_via = ab.via_circuit_s11(f, 0.0)
    s_core = marchand_two_section_sparams(f, 2.5, _d().z0e_ohm, _d().z0o_ohm,
                                          _d().z_unbal_ohm, _d().z_bal_se_ohm)
    assert np.max(np.abs(s_via - s_core)) < 1e-9


def test_via_l_inversion_roundtrip_and_direction_guard():
    """反演回收：电路级谷位对 → L 估计（耦合加载使孤立短截线式偏 +~19% 模型偏）。

    估计式 θ_via=90°(1−f_rod/f_sheet) 忽略耦合线加载对谷位的牵引——对电路级
    真值 0.7nH 回收 0.832nH（+18.9%），钉该模型偏量级（≤25%、同向），judge 的
    l_via_eff_nh 按估计口径列账（主判=Δ 谷位，非 L 反演）。
    """
    f_rod = ab.theory_null_ghz(0.7e-9)
    f_sheet = ab.theory_null_ghz(0.0)
    l_eff = ab.via_l_from_nulls(f_rod, f_sheet)
    assert abs(l_eff - 0.7e-9) / 0.7e-9 < 0.25   # 模型偏 ≤25%（实测 +18.9%）
    assert l_eff > 0.7e-9                        # 偏置方向钉（加载使谷位上移）
    with pytest.raises(ValueError, match="f_rod < f_sheet"):
        ab.via_l_from_nulls(3.0, 2.5)


def _d():
    return marchand_two_section_nominal()


def test_attribution_table_three_branches():
    # CONFIRMED：Δ=22%（≈理论 22.0% 同向贴量）
    f_rod, f_sheet = 3.05, 3.05 * 1.22
    tab = ab.attribution_table(f_rod, f_sheet)
    assert tab["conclusion"].startswith("VIA_CONFIRMED")
    assert abs(tab["delta_via_rel"] - 0.22) < 1e-6
    assert 0.3e-9 < ab.via_l_from_nulls(f_rod, f_sheet) < 1.5e-9
    # FALSIFIED：Δ<5%
    tab2 = ab.attribution_table(3.0, 3.0 * 1.001)
    assert tab2["conclusion"].startswith("VIA_FALSIFIED")
    # INCONCLUSIVE：谷位触扫频边
    tab3 = ab.attribution_table(2.0, 4.19, censored={"rod": True})
    assert tab3["conclusion"].startswith("INCONCLUSIVE")
    assert "delta_via_rel" not in tab3
    # 理论列：HFSS 2.04 vs 电路级 0.7nH 谷 2.046（+0.3% 内）
    th = tab["theory"]
    assert abs(th["null_ghz"][1] - 2.046) < 0.005
    assert abs(th["hfss_vs_theory_dev_pct"]) < 1.0


def test_gp_l_via_formula_value():
    assert abs(ab._gp_l_via_nh(0.25) - 1.278) < 0.01


def test_g0_tier_thresholds():
    a = {"t": {"tail10_rel_db": -45.0, "tail_slope_db_per_ns": -2.0}}
    b = {"t": {"tail10_rel_db": -35.0, "tail_slope_db_per_ns": -1.5}}
    c = {"t": {"tail10_rel_db": -20.0, "tail_slope_db_per_ns": -0.3}}
    assert ab.g0_tier(a) == "A"
    assert ab.g0_tier(b) == "B"
    assert ab.g0_tier(c) == "C"


# ─── ⑤ 主判估计量：合成用例回收（理想 3dB 分馈 + 门负探针） ───────────────────

def _synth_summary_rows(s21_abs: float, s31_abs: float, ph3_deg: float = 180.0,
                        nf: int = 41):
    """合成驻波免疫估计量输入：Zin=50（Γ=0）、|S21|/|S31| 给定、出波相位差可调。

    β 行取 HJ 参考值（与被测函数同式独立重算）→ beta_sane True 回收。
    """
    from rfauto.core.synthesis import Stackup, forward_z0

    stack = Stackup(name="marchand2", epsilon_r=3.66, thickness_mm=1.524,
                    loss_tangent=0.0037)
    _, eps_hj = forward_z0(float(marchand_two_section_nominal().w_mm), 2.5, stack)
    beta_hj = 2.0 * math.pi * 2.5e9 * math.sqrt(eps_hj) / 299792458.0
    f = np.linspace(2.0e9, 4.0e9, nf)
    z1 = np.full(nf, 50.0 + 0j)
    u1i, u1r = np.ones(nf) + 0j, np.zeros(nf) + 0j
    i1 = (u1i - u1r) / z1
    p_avail = 0.5 * np.real((u1i + u1r) * np.conj(i1))   # 0.01
    i2 = np.sqrt(2.0 * (s21_abs ** 2) * p_avail / 140.0) + 0j
    i3 = np.sqrt(2.0 * (s31_abs ** 2) * p_avail / 140.0) + 0j
    u2r = 0.7 * np.ones(nf) + 0j
    u3r = 0.6 * np.exp(1j * math.radians(ph3_deg)) * np.ones(nf)
    summ = {
        "nf": nf,
        "uf1_inc": {"re": list(u1i.real), "im": list(u1i.imag)},
        "uf1_ref": {"re": list(u1r.real), "im": list(u1r.imag)},
        "uf2_ref": {"re": list(u2r.real), "im": list(u2r.imag)},
        "uf2_inc": {"re": list((u2r + 140.0 * i2).real),
                    "im": list((u2r + 140.0 * i2).imag)},
        "uf3_ref": {"re": list(u3r.real), "im": list(u3r.imag)},
        "uf3_inc": {"re": list((u3r + 140.0 * i3).real),
                    "im": list((u3r + 140.0 * i3).imag)},
        "z1_ref": {"re": list(z1.real), "im": list(z1.imag)},
    }
    rows = [{"freq_hz": repr(float(fi)), "beta_rad_m": repr(beta_hj)} for fi in f]
    return summ, rows


def test_metrics_from_summary_synthetic_3db_recovery():
    summ, rows = _synth_summary_rows(0.7071, 0.7071)
    out = ab.metrics_from_summary(summ, rows)
    m, gates = out["metrics"], out["gates"]
    assert abs(m["band_min_s21_db"] + 3.0103) < 0.01
    assert abs(m["band_min_s31_db"] + 3.0103) < 0.01
    assert m["band_max_abs_imbalance_db"] < 1e-6
    assert m["band_max_phase_error_deg"] < 1e-6
    assert m["band_max_s11_db"] < -200.0          # Γ=0（恒等式回收）
    assert out["s11_passive_violation_pts"] == 0
    assert all(gates.values()) and out["all_gates_pass"]
    assert out["lb_xcheck"]["beta_sane"] is True
    assert out["mask"]["S23"] is False            # #314 未测不判


def test_metrics_from_summary_negative_probe_and_nf_guard():
    summ, rows = _synth_summary_rows(0.7071, 0.4472)   # 不平衡 4dB → 门 FAIL
    out = ab.metrics_from_summary(summ, rows)
    assert out["gates"]["amp_imbalance_le_1db"] is False
    assert out["all_gates_pass"] is False
    with pytest.raises(ValueError, match="nf"):
        ab.metrics_from_summary(dict(summ, nf=999), rows)


# ─── ⑥ 计划/判据预声明一致性（预算与可证伪阈值写死） ──────────────────────────

def test_plan_declared_constants_and_prediction():
    assert ab.VIA_CONFIRMED_MIN_REL == 0.05
    assert ab.BUDGET_WALL_S == 3600.0 and ab.PARTIAL_FACTOR == 1.5
    assert ab.SOLVE_TIMEOUT_S == 5400.0
    assert ab.VARIANTS == ("rod", "sheet")
    assert ab.FREQ_RANGE_GHZ == (2.0, 4.2)
    criteria = ab.CRITERIA_TEXT
    assert "PARTIAL" in criteria and "2.25h" in criteria
    assert "VIA_FALSIFIED" in criteria and "5%" in criteria
    assert "engine_z0_correction" in criteria      # 正交性声明
    crit = ab.CRITERIA_TEXT.format(ts="x")
    assert "RFAUTO_NRTS=300000" in crit


def test_runner_module_importable_and_plan_paths():
    spec = importlib.util.find_spec("marchand_via_ab")
    assert spec is not None
    assert ab.ROOT.name == "marchand_via_ab"
    assert ab.LOCK_PATH.name == ".oe_collect.lock"
    assert re.search(r"#261", ab.oe_foreign_running.__doc__ or "")
