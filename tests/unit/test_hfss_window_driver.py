"""hfss_window_arbitration 8 席编排驱动离线单测（wf:hfss-window-driver）。

五个面（零真机零网络零 pyaedt）：
- SEATS spec 完整性（8 席 × criteria 7 节对齐，门值/窗/预算逐席钉死值）；
- 判读纯函数（四态判定/总态封顶/ΔS 阶梯采信/G11 掩码/指标提取合成回收）；
- 几何审计纯函数（#310④ 重叠垫/#336 断链/#191 集总桥）；
- run_seat 编排（dry-run 端到端合成链 + fail-closed 故障注入 mock 面）；
- 并行发射（wf:hfss-window-parallel：波次/端口分配纯函数、per-port grpcsrv
  拉起/指纹清理 mock 面、波次编排 mock 面、缺省 1=串行行为零变化钉）。

真机 OE 参考产物在 runs/（gitignored，工作区证据）：在档则做真产物解析对账，
缺档诚实 skip（不冒充）。
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from tests.unit._hfss_window_driver_fakes import (
    FREQ,
    _arr_rects_single_source,
    _coupled_censored_sparams_csv,
    _FakeHfss,
    _FakeProc,
    _gate,
    _load,
    _mmf,
    _patch_registry_transport,
    _patch_remote_pipeline,
    _patch_remote_session,
    _setup_h,
    _stepped_s21,
    _synth_wilkinson_like,
    mod,
)

REPO = Path(__file__).resolve().parents[2]


_ALL_SEATS = ("stepped_impedance", "coupled_line", "wilkinson", "marchand_balun",
              "gysel", "branchline", "patch_array_1x4", "patch_array_2x2")


# ═══════════════ SEATS spec 完整性（8 席 × 7 节）══════════════

def test_launch_order_matches_readme():
    """README 发射序：stepped → coupled → wilkinson → marchand → gysel →
    branchline → patch_1x4 → patch_2x2（先短预算后长预算）。"""
    assert mod.LAUNCH_ORDER == _ALL_SEATS
    orders = [mod.SEATS[name]["order"] for name in mod.LAUNCH_ORDER]
    assert orders == [1, 2, 3, 4, 5, 6, 7, 8]


@pytest.mark.parametrize("seat_name", _ALL_SEATS)
def test_seat_spec_has_all_criteria_sections(seat_name):
    """每席 7 节 schema 对齐：§1 模板与名义（template/f0/n_ports/oe）/
    §2 建模方案（builder）/ §3 收敛阶梯（window/n_points/ladder/scalars）/
    §4 仲裁门（gates）/ §5 健康门（g11）/ §6 预算（budget_min）/ §7 锚注册
    （anchor）。"""
    seat = mod.SEATS[seat_name]
    for key in ("template", "f0_ghz", "n_ports", "window_ghz", "n_points",
                "ladder", "budget_min", "builder", "extractors", "gates",
                "g11", "oe", "anchor", "ladder_scalars", "order"):
        assert key in seat, f"{seat_name} 缺 {key}（criteria 7 节不对齐）"
    assert len(seat["ladder"]) == 3
    assert seat["n_points"] == 401
    assert seat["gates"], "§4 门表不得为空"
    assert all(g["metric"] in {e["metric"] for e in seat["extractors"]}
               for g in seat["gates"]), "门引用的指标必须可提取"
    assert seat["g11"]["passive_le"] == 1.05
    assert "anchor" in seat and len(seat["anchor"]) > 20


def test_seat_frozen_values_vs_criteria():
    """criteria §3/§4/§6 冻结值逐席钉（发射后不改；改动=返工）。"""
    s = mod.SEATS
    ladder = ((0.02, 12), (0.01, 20), (0.005, 30))
    for name in _ALL_SEATS:
        assert s[name]["ladder"] == ladder, name
    budgets = {"stepped_impedance": 30, "coupled_line": 30, "wilkinson": 45,
               "marchand_balun": 60, "gysel": 60, "branchline": 60,
               "patch_array_1x4": 90, "patch_array_2x2": 90}
    windows = {"stepped_impedance": (1.5, 3.5), "coupled_line": (1.8, 3.0),
               "wilkinson": (2.0, 3.0), "marchand_balun": (1.8, 3.6),
               "gysel": (2.0, 3.0), "branchline": (1.8, 2.8),
               "patch_array_1x4": (4.64, 6.96), "patch_array_2x2": (4.64, 6.96)}
    n_ports = {"stepped_impedance": 2, "coupled_line": 3, "wilkinson": 3,
               "marchand_balun": 3, "gysel": 3, "branchline": 4,
               "patch_array_1x4": 1, "patch_array_2x2": 1}
    for name in _ALL_SEATS:
        assert s[name]["budget_min"] == budgets[name], name
        assert tuple(s[name]["window_ghz"]) == windows[name], name
        assert s[name]["n_ports"] == n_ports[name], name


def test_gate_values_frozen():
    """§4 门值逐行钉（各席 criteria 表）。"""
    g = {name: {row["metric"]: row["gate"] for row in mod.SEATS[name]["gates"]}
         for name in _ALL_SEATS}
    assert g["wilkinson"] == {"f_match_ghz": 3.0, "split_db": 0.3,
                              "s21_at_match_db": 0.5, "s23_band_max_db": 5.0,
                              "s11_min_db": 5.0}
    assert g["branchline"] == {"f_match_ghz": 3.0, "split_db": 0.3,
                               "amp_mid_db": 0.5, "s41_band_max_db": 5.0,
                               "s11_min_db": 5.0}
    assert g["marchand_balun"] == {"f_null_ghz": 10.0, "s21_band_min_db": 1.0,
                                   "s31_band_min_db": 1.0,
                                   "imbalance_band_max_db": 0.5,
                                   "phase_diff_at_f_null_deg": 10.0}
    assert g["stepped_impedance"] == {"s21_at_f0_db": 0.5, "f_dip_ghz": 3.0,
                                      "bw_3db_ghz": 20.0}
    assert g["coupled_line"] == {"coupling_at_f0_db": 0.5, "f_peak_ghz": 3.0,
                                 "through_at_f0_db": 0.5}
    assert g["gysel"]["s21_at_f0_db"] == 0.5 and g["gysel"]["split_at_f0_db"] == 0.3
    assert g["gysel"]["s32_band_max_db"] == 5.0 and g["gysel"]["s11_at_f0_db"] == 5.0
    for name in ("patch_array_1x4", "patch_array_2x2"):
        assert g[name] == {"f_min_ghz": 5.0, "s11_min_db": 3.0,
                           "s11_at_5p8_db": 2.0}


def test_x_ref_windows_frozen():
    """裁判窗 x_ref 逐席钉（wilkinson f_match 2.5±5% / branchline 2.4±5% /
    patch [5.0,6.6] / 深谷 le 单边窗 / S32@f0 ≤−20）。"""
    x = {name: {row["metric"]: row.get("x_ref")
                for row in mod.SEATS[name]["gates"]} for name in _ALL_SEATS}
    assert x["wilkinson"]["f_match_ghz"] == (2.375, 2.625)
    assert x["wilkinson"]["s21_at_match_db"] == (-3.5, -2.5)
    assert x["wilkinson"]["s23_band_max_db"] == ("le", -15.0)
    assert x["branchline"]["f_match_ghz"] == (2.28, 2.52)
    assert x["branchline"]["amp_mid_db"] == (-3.5, -2.5)
    assert x["patch_array_1x4"]["f_min_ghz"] == (5.0, 6.6)
    assert x["patch_array_2x2"]["f_min_ghz"] == (5.0, 6.6)
    assert x["patch_array_1x4"]["s11_min_db"] == ("le", -8.0)
    assert x["gysel"]["s21_at_f0_db"] == (-3.5, -2.5)
    assert x["gysel"]["s32_at_f0_db"] == ("le", -20.0)


def test_builder_completion_faces():
    """8 席全量建模（builders2 补批 2026-09-28）：builder_status 无 skeleton、
    _LAYOUTS 全注册；skeleton 防线保留（test_run_seat_skeleton_rearm_fail_closed）。"""
    for name in _ALL_SEATS:
        assert mod.SEATS[name].get("builder_status") != "skeleton", name
        assert name in mod._LAYOUTS, name


def test_key_vs_info_gates():
    """marchand phase_diff 是信息项（key=False 不翻总态）；patch S11@5.8 是
    带形状信息项门；其余席门全部关键。"""
    marchand = {r["metric"]: r["key"] for r in mod.SEATS["marchand_balun"]["gates"]}
    assert marchand["phase_diff_at_f_null_deg"] is False
    assert all(v for k, v in marchand.items() if k != "phase_diff_at_f_null_deg")
    for name in ("patch_array_1x4", "patch_array_2x2"):
        keys = {r["metric"]: r["key"] for r in mod.SEATS[name]["gates"]}
        assert keys["s11_at_5p8_db"] is False
        assert keys["f_min_ghz"] and keys["s11_min_db"]
    for name in ("stepped_impedance", "coupled_line", "wilkinson", "branchline"):
        keys = {r["metric"]: r["key"] for r in mod.SEATS[name]["gates"]}
        assert all(keys.values()), name
    gysel_keys = {r["metric"]: r["key"] for r in mod.SEATS["gysel"]["gates"]}
    assert all(gysel_keys[k] for k in ("s21_at_f0_db", "split_at_f0_db",
                                       "s32_band_max_db", "s11_at_f0_db"))
    assert gysel_keys["s32_at_f0_db"] is False   # x_ref 记录行（S32@f0 ≤−20）


# ═══════════════ 判读纯函数（#350 四态 / 总态 / #335 阶梯 / G11）══════════════


def test_judge_metric_four_states():
    """#350 四态判定表（门过+窗内=JUDGE；HFSS 窗内 OE 越窗=HFSS；门炸=
    DISAGREE；门过双越窗=OPENEMS；缺值=UNKNOWN）。"""
    win = (95.0, 105.0)
    assert mod.judge_metric(100.0, 101.0, _gate(x_ref=win))["state"] == "AGREE_JUDGE"
    # HFSS 在窗内（105=上沿）而 OE 越窗（108>105），互差 2.78% ≤ 3% 门
    assert mod.judge_metric(105.0, 108.0, _gate(gate=3.0, x_ref=win))["state"] \
        == "AGREE_HFSS"
    assert mod.judge_metric(110.0, 100.0, _gate(gate=3.0, x_ref=win))["state"] \
        == "DISAGREE"
    assert mod.judge_metric(110.0, 111.0, _gate(gate=3.0, x_ref=win))["state"] \
        == "AGREE_OPENEMS"
    assert mod.judge_metric(None, 100.0, _gate())["state"] == "UNKNOWN"
    assert mod.judge_metric(float("nan"), 100.0, _gate())["state"] == "UNKNOWN"
    # rel_pct：3% 门边界（≤ 过 / > 炸）
    assert mod.judge_metric(102.9, 100.0, _gate())["state"] == "AGREE_JUDGE"
    assert mod.judge_metric(103.1, 100.0, _gate())["state"] == "DISAGREE"


def test_judge_metric_le_window_and_no_window():
    le = ("le", -15.0)
    r = mod.judge_metric(-20.0, -19.4, _gate(gate=5.0, kind="db_diff", x_ref=le))
    assert r["state"] == "AGREE_JUDGE"
    # HFSS 在窗内（≤−15）而 OE 越窗（>−15），互差 ≤ 门 → AGREE_HFSS
    r = mod.judge_metric(-15.5, -14.0, _gate(gate=5.0, kind="db_diff", x_ref=le))
    assert r["state"] == "AGREE_HFSS"
    # 无窗（None）：门过即 AGREE_JUDGE（窗口列缺省不虚构）
    assert mod.judge_metric(1.0, 1.5, _gate(gate=0.5, kind="db_diff"))["state"] \
        == "AGREE_JUDGE"
    # closed_form 未解析串=无窗（判读侧如实标注）
    r = mod.judge_metric(2.9, 2.955,
                         _gate(x_ref="closed_form:coupled_quarter_wave"))
    assert r["state"] == "AGREE_JUDGE"
    assert r["x_ref"] == "closed_form:coupled_quarter_wave"


def test_total_verdict_cap_and_undecidable():
    ok = {"state": "AGREE_JUDGE", "key": True, "metric": "a"}
    worst = {"state": "AGREE_HFSS", "key": True, "metric": "b"}
    bad = {"state": "DISAGREE", "key": True, "metric": "c"}
    info = {"state": "DISAGREE", "key": False, "metric": "d"}
    unk = {"state": "UNKNOWN", "key": True, "metric": "e"}
    assert mod.total_verdict([ok]) == "AGREE_JUDGE"
    assert mod.total_verdict([ok, worst]) == "AGREE_HFSS"       # 取最差 AGREE
    assert mod.total_verdict([ok, bad]) == "DISAGREE"
    assert mod.total_verdict([bad, info]) == "DISAGREE"          # 信息项不翻但已有关键
    assert mod.total_verdict([info]) == "UNDECIDABLE"            # 全非关键
    assert mod.total_verdict([unk]) == "UNDECIDABLE"             # 全 UNKNOWN
    # cap（闭式半集）：AGREE 封顶 AGREE_HFSS；DISAGREE 不被 cap 洗白
    assert mod.total_verdict([ok], cap="AGREE_HFSS") == "AGREE_HFSS"
    assert mod.total_verdict([worst], cap="AGREE_HFSS") == "AGREE_HFSS"
    assert mod.total_verdict([bad], cap="AGREE_HFSS") == "DISAGREE"


def test_ladder_pick_topped_and_saturation():
    """#335：触顶档不判读（回退前档）；饱和=末两档 |Δ标量|<门宽/3。"""
    gates = (_gate(metric="f_match_ghz", gate=3.0),)
    scalars = ("f_match_ghz",)
    rungs = [
        {"level": 1, "topped": False, "passes": 12, "final_delta_s": 0.02,
         "metrics": {"f_match_ghz": 2.30}},
        {"level": 2, "topped": False, "passes": 20, "final_delta_s": 0.01,
         "metrics": {"f_match_ghz": 2.20}},
        {"level": 3, "topped": True, "passes": 30, "final_delta_s": 0.006,
         "metrics": {"f_match_ghz": 2.10}},
    ]
    rep = mod.ladder_pick(rungs, gates, scalars)
    assert rep["chosen_level"] == 2            # 末档触顶 → 采信档 2
    assert rep["usable_levels"] == [1, 2]
    # |2.20−2.30|=0.10 < 门宽/3=1.0 → 饱和
    assert rep["saturated"]["f_match_ghz"] is True
    all_topped = [{"level": k, "topped": True, "passes": 30,
                   "final_delta_s": 0.05, "metrics": {}} for k in (1, 2, 3)]
    rep2 = mod.ladder_pick(all_topped, gates, scalars)
    assert rep2["chosen_level"] is None
    assert "不可判读" in rep2["reason"]
    tight = [
        {"level": 1, "topped": False, "metrics": {"f_match_ghz": 2.50}},
        {"level": 2, "topped": False, "metrics": {"f_match_ghz": 2.00}},
    ]
    rep3 = mod.ladder_pick(tight, gates, scalars)
    # |2.00−2.50|=0.5 < 1.0 → 饱和；改 1.5 才不饱和
    assert rep3["saturated"]["f_match_ghz"] is True
    wide = [
        {"level": 1, "topped": False, "metrics": {"f_match_ghz": 2.50}},
        {"level": 2, "topped": False, "metrics": {"f_match_ghz": 1.00}},
    ]
    rep4 = mod.ladder_pick(wide, gates, scalars)
    assert rep4["saturated"]["f_match_ghz"] is False   # |1.5| ≥ 1.0


def test_g11_health_full_and_masked():
    freq = np.linspace(2.0e9, 3.0e9, 101)
    s = np.zeros((101, 3, 3), dtype=complex)
    s[:, 1, 0] = 0.7
    s[:, 0, 1] = 0.7                      # 对称（互易全矩阵口径）
    s[:, 2, 0] = 0.7
    s[:, 0, 2] = 0.7
    g11 = {"passive_le": 1.05, "recip_le": 1e-3}
    out = mod.g11_health(freq, s, None, g11)
    assert out["passive"] and out["finite"]
    assert out["reciprocity"] == "PASS"
    s[:, 1, 2] = 0.5                              # 破坏互易（S32 无 S23 对应）
    assert mod.g11_health(freq, s, None, g11)["reciprocity"] == "FAIL"
    s[:, 1, 2] = 0.0
    s[:, 0, 0] = 1.10                             # 无源性炸（5% 余量口径）
    assert mod.g11_health(freq, s, None, g11)["passive"] is False
    # 单端口：互易不设门（criteria §5 如实）
    out1 = mod.g11_health(freq, np.ones((101, 1, 1), dtype=complex) * 0.1, None,
                          {"passive_le": 1.05, "recip_le": None})
    assert "NOT_APPLICABLE" in out1["reciprocity"]
    # 单激励部分矩阵：无双向独立已测对 → UNKNOWN（#314 不凑判）
    mask = np.zeros((3, 3), dtype=bool)
    mask[0, 0] = mask[1, 0] = mask[2, 0] = True   # 只有激励 1 列
    out_m = mod.g11_health(freq, s, mask, g11)
    assert "UNKNOWN" in out_m["reciprocity"]
    # NaN → finite False
    s_nan = s.copy()
    s_nan[0, 0, 0] = np.nan
    assert mod.g11_health(freq, s_nan, None, g11)["finite"] is False


# ═══════════════ 指标提取（合成回收 #118）══════════════


def test_extract_metrics_recovers_known_values():
    seat = mod.SEATS["wilkinson"]
    m = mod.extract_metrics(FREQ, _synth_wilkinson_like(), seat, None)
    assert abs(m["f_match_ghz"] - 2.2075) < 0.01
    assert abs(m["s11_min_db"] - (-32.12)) < 0.05
    assert abs(m["s21_at_match_db"] - (-3.30)) < 0.01
    assert abs(m["split_db"] - 0.04) < 0.01
    assert abs(m["s23_band_max_db"] - (-19.4)) < 0.01


def test_extract_metrics_mask_semantics():
    """#314：所需元素带内未测 → None（UNKNOWN），不凑判。"""
    seat = mod.SEATS["wilkinson"]
    mask = np.zeros((3, 3), dtype=bool)
    mask[0, 0] = mask[1, 0] = mask[2, 0] = True
    m_ok = mod.extract_metrics(FREQ, _synth_wilkinson_like(), seat, mask)
    assert m_ok["f_match_ghz"] is not None
    assert m_ok["s23_band_max_db"] is None       # S23 未测（单激励）
    mask[1, 2] = True
    m_full = mod.extract_metrics(FREQ, _synth_wilkinson_like(), seat, mask)
    assert m_full["s23_band_max_db"] is not None


def test_extract_metrics_bw3db_and_none():
    seat = mod.SEATS["stepped_impedance"]
    s = np.zeros((len(FREQ), 2, 2), dtype=complex)
    s[:, 1, 0] = 10.0 ** (-0.4 / 20.0)           # 全程 ≥ −3dB → bw=None（如实）
    m = mod.extract_metrics(FREQ, s, seat, None)
    assert m["bw_3db_ghz"] is None
    fg = FREQ / 1e9
    inside = np.abs(fg - 2.4) <= 0.2             # 0.4GHz 连续段 ≥ −3dB
    s2 = s.copy()
    s2[~inside, 1, 0] = 10.0 ** (-6.0 / 20.0)
    m2 = mod.extract_metrics(FREQ, s2, seat, None)
    assert m2["bw_3db_ghz"] is not None and abs(m2["bw_3db_ghz"] - 0.4) < 0.05


# ═══════════════ 几何审计纯函数（#310④/#336/#191）══════════════

def test_apply_pads_creates_area_overlap():
    a = (0.0, 0.0, 1.0, 1.0)
    b = (0.0, 1.0, 1.0, 2.0)
    assert mod.rect_overlap_area(a, b) == 0.0            # 仅共边
    padded = mod.apply_pads({"a": a, "b": b},
                            [{"a": "a", "b": "b", "axis": "y"}])
    assert mod.rect_overlap_area(padded["a"], padded["b"]) > 0.0
    assert padded["a"][3] == pytest.approx(1.0 + mod.PAD_MM)
    # 反向（a 在 b 上方）也向 b 延伸
    padded2 = mod.apply_pads({"a": b, "b": a},
                             [{"a": "a", "b": "b", "axis": "y"}])
    assert mod.rect_overlap_area(padded2["a"], padded2["b"]) > 0.0
    assert padded2["a"][1] == pytest.approx(1.0 - mod.PAD_MM)


def test_audit_connectivity_orphan_detection():
    rects = {"feed": (0.0, 0.0, 1.0, 1.0),
             "body_a": (0.0, 1.0, 1.0, 2.1),
             "body_b": (0.0, 2.0, 1.0, 3.0)}
    conn = mod.audit_connectivity(rects)
    assert conn["orphans"] == ["feed"]                    # 仅共边=断链（#310④）
    assert conn["main"] == ["body_a", "body_b"]
    padded = mod.apply_pads(rects, [{"a": "feed", "b": "body_a", "axis": "y"}])
    conn2 = mod.audit_connectivity(padded)
    assert conn2["orphans"] == [] and conn2["n_components"] == 1


def test_audit_geometry_ports_and_floating():
    rects = {"feed": (0.0, 0.0, 1.0, 1.0), "body": (0.0, 1.0, 1.0, 3.0)}
    padded = mod.apply_pads(rects, [{"a": "feed", "b": "body", "axis": "y"}])
    ok = mod.audit_geometry(padded, {"P1": (0.5, 0.0)})
    assert ok["ok"] and ok["ports_missing_metal"] == []
    assert ok["floating_components"] == []
    bad = mod.audit_geometry(padded, {"P1": (5.0, 5.0)})
    assert not bad["ok"] and bad["ports_missing_metal"] == ["P1"]
    # 悬空金属岛（无任何端口触点的分量）→ 断链 fail
    islands = {"feed": (0.0, 0.0, 1.0, 1.0),
               "body": (0.0, 1.0, 1.0, 3.0),
               "island": (5.0, 5.0, 6.0, 6.0)}
    padded2 = mod.apply_pads(islands, [{"a": "feed", "b": "body", "axis": "y"}])
    out = mod.audit_geometry(padded2, {"P1": (0.5, 0.0)})
    assert not out["ok"] and len(out["floating_components"]) == 1


def test_audit_lumped_bridge_191():
    """#191：电阻片必须触两臂且与 PEC 零面积交叠。"""
    arm_l = (0.0, 1.0, 1.0, 2.0)
    arm_r = (3.0, 1.0, 4.0, 2.0)
    good = (1.0, 1.2, 3.0, 1.8)                 # 两端各触内缘
    out = mod.audit_lumped_bridge(good, "x", {"arm_left": arm_l, "arm_right": arm_r})
    assert out["ok"] and out["touched"] == {"lo": True, "hi": True}
    overlap = (0.5, 1.2, 3.0, 1.8)              # 与臂面积交叠（#191 击败面）
    out2 = mod.audit_lumped_bridge(overlap, "x",
                                   {"arm_left": arm_l, "arm_right": arm_r})
    assert not out2["ok"] and out2["pec_overlap"] == ["arm_left"]
    floating = (1.2, 1.2, 2.8, 1.8)             # 悬空（不触臂）
    out3 = mod.audit_lumped_bridge(floating, "x",
                                   {"arm_left": arm_l, "arm_right": arm_r})
    assert not out3["ok"] and out3["touched"] == {"lo": False, "hi": False}


def test_seat_layouts_audit_pass():
    """8 席几何面（builders2 补批全量）：垫后端口/负载触点全部落金属、无
    悬空岛、集总桥审计全过（coupled_line/marchand 允许多岛拓扑——每岛有
    端口即连通，#336 语义）。"""
    for name in _ALL_SEATS:
        ctx = mod.seat_context(name)
        lay = mod.seat_layout(name, ctx)
        assert lay["audit"]["ok"], (name, lay["audit"])
        assert lay["audit"]["floating_components"] == []
        for lump in lay.get("lumped", []):
            if lump.get("audit") is not None:
                assert lump["audit"]["ok"], (name, lump["name"], lump["audit"])


def test_wilkinson_layout_matches_geometry_spec_single_source():
    """wilkinson 布局对 TEMPLATE_NOMINAL 单源现算（零手抄；T 分叉/臂/馈线
    关键坐标与 geometry_spec 同源口径）。"""
    ctx = mod.seat_context("wilkinson")
    p = ctx["nominal_params"]
    lay = mod.seat_layout("wilkinson", ctx)
    xa = 4.0 + float(p["series_w_mm"]) / 2
    assert lay["padded_rects"]["t_junction"][0] == pytest.approx(-xa - float(
        p["series_w_mm"]) / 2)
    assert lay["padded_rects"]["arm_left"][3] == pytest.approx(-30.0 + float(
        p["arm_len_mm"]))
    # feed_in 垫后伸入 t_junction（+PAD）
    assert lay["padded_rects"]["feed_in"][3] == pytest.approx(
        -30.0 + mod.PAD_MM)


def test_marchand_layout_mirror_semantics():
    """#310④：节 2 副线关于主线中心 y=w/2 镜像（gap 恒 =s，写错即伪失衡）。"""
    ctx = mod.seat_context("marchand_balun")
    s_mm = ctx["s_mm"]
    lay = mod.seat_layout("marchand_balun", ctx)
    r = lay["padded_rects"]
    gap1 = r["SecLine1"][1] - r["MainLine"][3]
    gap2 = r["MainLine"][1] - r["SecLine2"][3]
    assert gap1 == pytest.approx(s_mm, abs=1e-9)
    assert gap2 == pytest.approx(s_mm, abs=1e-9)
    assert ctx["l_sect_mm"] == pytest.approx(18.467, abs=1e-3)
    assert ctx["r_bal_se_ohm"] == 140.0


# ═══════════════ 后 4 席 builder（wf:hfss-window-builders2 补批）══════════════

def test_edge_touch_pads_semantics():
    """邻接自动垫三态：面积交叠跳过 / 共边生成 pad / 纯点接触不生成。"""
    rects = {
        "a": (0.0, 0.0, 1.0, 1.0),
        "b": (0.0, 1.0, 1.0, 2.0),      # 与 a 仅共边（y=1）
        "c": (0.0, 0.5, 1.0, 1.5),      # 与 a 面积交叠（跳过）
        "d": (1.0, 2.0, 2.0, 3.0),      # 与 b 纯点接触（(1,2)，双投影 0）
        "e": (3.0, 0.0, 4.0, 1.0),      # 与 a 分离（间隙 2mm）
    }
    pads = mod.edge_touch_pads(rects)
    assert pads == [{"a": "a", "b": "b", "axis": "y"}]
    padded = mod.apply_pads({k: rects[k] for k in ("a", "b")}, pads)
    assert mod.rect_overlap_area(padded["a"], padded["b"]) > 0.0


def test_gysel_layout_single_source_and_loads():
    """gysel：_gysel_layout 单源现算（零手抄）+ 3 端口同 y=−60 边 + Δ1/Δ2
    50Ω 竖直集总（x=±iso_len、触点落桥带，criteria §2）。"""
    from rfauto.adapters.openems_templates import _gysel_layout

    ctx = mod.seat_context("gysel")
    g = _gysel_layout(dict(ctx["nominal_params"]))
    lay = mod.seat_layout("gysel", ctx)
    r = lay["padded_rects"]
    xa, xb, yj, wf = g["xa"], g["xb"], g["yj"], g["wf"]
    # 环坐标单源：臂跨度 ±XA / 竖直段止于 YJ / 桥带 ±(XB+W_F/2)
    assert r["arm_bottom"][:3:2] == pytest.approx((-xa, xa))
    assert r["iso_left_v"][3] == pytest.approx(yj)
    assert r["bridge_top"][:3:2] == pytest.approx(
        (-(xb + wf / 2), xb + wf / 2))
    # 3 端口同板边（OE MSLPort 同位）：P1 x=0、P2/P3 x=∓XA，截面 ≥4w×3h
    assert [(p["name"], p["edge_y"], p["center_x"]) for p in lay["ports"]] == [
        ("P1", -mod.BOARD_MM, 0.0), ("P2", -mod.BOARD_MM, -xa),
        ("P3", -mod.BOARD_MM, xa)]
    assert lay["ports"][0]["w"] == pytest.approx(4.0 * wf)
    assert lay["ports"][0]["h"] >= 3.0
    # 2×50Ω 竖直负载：薄片 y=YJ、x=±(XB±W_F/2)（OE LumpedElement 同位）
    loads = {ln["name"]: ln for ln in lay["lumped"]}
    assert set(loads) == {"Rload1", "Rload2"}
    for nm, sgn in (("Rload1", -1.0), ("Rload2", 1.0)):
        ld = loads[nm]
        assert ld["kind"] == "rlc" and ld["plane"] == "xz"
        assert ld["r_ohm"] == 50.0
        assert ld["sheet"] == pytest.approx(
            (sgn * xb - wf / 2, yj, sgn * xb + wf / 2, yj))
        assert ld["audit"]["ok"] and ld["audit"]["mode"] == "xz_shunt"
    # 仅馈线↔隔离竖直段 y=0 缝需垫（环片间自然面积交叠，DRIVER_NOTES §四）
    assert len(lay["pads"]) == 2
    assert {tuple(sorted((p["a"], p["b"]))) for p in lay["pads"]} == {
        ("feed_out_left", "iso_left_v"), ("feed_out_right", "iso_right_v")}
    assert lay["air_top"] == mod.AIR_TOP_MM and lay["board"] == mod.BOARD_MM
    assert any("辐射边界" in n for n in lay["notes"])   # criteria 偏差如实注记


def test_branchline_layout_ring_and_ports():
    """branchline：8 片正方环 geometry_spec 同式 + 4 端口四板边（P1 入/P2 直通/
    P3 耦合/P4 隔离，OE 端口序）+ 仅共边缝自动垫。"""
    ctx = mod.seat_context("branchline")
    p = ctx["nominal_params"]
    arm, sw, shw = (float(p[k]) for k in
                    ("arm_len_mm", "series_w_mm", "shunt_w_mm"))
    half = arm / 2.0
    lay = mod.seat_layout("branchline", ctx)
    r = lay["padded_rects"]
    assert len(r) == 8
    assert r["arm_top"] == pytest.approx(
        (-half - shw / 2, half - sw / 2, half + shw / 2, half + sw / 2))
    assert r["arm_left"][2] == pytest.approx(-half + shw / 2)
    # 4 端口四板边（无相邻端口重叠约束）：P1/P3 y 边、P2/P4 x 边
    assert [(q["name"], q.get("edge_y"), q.get("edge"), q.get("center_x"),
             q.get("center_y")) for q in lay["ports"]] == [
        ("P1", -mod.BOARD_MM, None, -half, None),
        ("P2", None, ("x", mod.BOARD_MM), None, -half),
        ("P3", mod.BOARD_MM, None, half, None),
        ("P4", None, ("x", -mod.BOARD_MM), None, half)]
    assert lay["ports"][0]["w"] == pytest.approx(4.0 * shw)
    # 仅 feed_p1↔arm_left / feed_p3↔arm_right 共边需垫（环角自然面积交叠）
    assert {tuple(sorted((q["a"], q["b"]))) for q in lay["pads"]} == {
        ("arm_left", "feed_p1"), ("arm_right", "feed_p3")}
    assert lay["lumped"] == [] and lay["air_top"] == mod.AIR_TOP_MM
    assert any("辐射边界" in n for n in lay["notes"])


def test_patch_array_layouts_consume_single_source():
    """patch 阵两席：rects 逐盒 == _arr_layout 单源（零手抄，criteria §2）；
    底探针竖直 LumpedPort（触点落主干）；无波端口（单端口集总馈）；空气顶
    =λ0/4；共边缝全垫连。"""
    lam4 = 0.25 * mod.C0 / (5.8e9) * 1e3
    for template, n_rect in (("patch_array_1x4", 31), ("patch_array_2x2", 31)):
        _ctx, lay, src = _arr_rects_single_source(template)
        assert lay["padded_rects"].keys() == src.keys()
        assert len(src) == n_rect
        for name, rect in src.items():            # 垫只外延不挪缘（外缘不动）
            got = lay["padded_rects"][name]
            assert got[0] <= rect[0] and got[1] <= rect[1], (template, name)
            assert got[2] >= rect[2] and got[3] >= rect[3], (template, name)
        assert lay["ports"] == []                 # 集总馈无波端口
        assert len(lay["lumped"]) == 1
        probe = lay["lumped"][0]
        assert probe["name"] == "P1" and probe["kind"] == "port"
        assert probe["r_ohm"] == 50.0
        assert mod._point_on_rect(probe["contact_point"],
                                  lay["padded_rects"]["trunk"])
        assert lay["air_top"] == pytest.approx(lam4, abs=1e-3)
        assert lay["board"] == mod.BOARD_MM
        assert lay["audit"]["ok"] and lay["pads"], template


def test_patch_array_2x2_mirror_semantics():
    """2×2 顶排折弯链镜像语义审计（criteria §2，#310④）：底排缺口 −y 自下
    入 / 顶排 +y 自上入，逐盒核对 stub 方向与缺口侧；违者 fail-fast。
    另按 review-slice4 P2-1 在测试侧独立复算关键坐标（不经审计器自身）。"""
    ctx, lay, src = _arr_rects_single_source("patch_array_2x2")
    mirror = lay["mirror_audit"]
    assert mirror is not None and mirror["ok"]
    assert set(mirror["per_column"]) == {"l", "r"}
    for col_checks in mirror["per_column"].values():
        assert all(col_checks.values())
    # 独立复算（review-slice4 P2-1）：底排 stub 底缘==贴片底缘（−y 自下入）、
    # 顶排 stub 顶缘==贴片顶缘（+y 自上入）、stub 入深=elem_feed_mm——
    # 直接对 _arr_layout 单源坐标断言，审计判据自身写错时此处仍能分辨。
    d_in = float(ctx["nominal_params"]["elem_feed_mm"])
    for col in ("l", "r"):
        assert src[f"e_b_{col}_stub"][1] == src[f"e_b_{col}_l"][1], col
        assert src[f"e_t_{col}_stub"][3] == src[f"e_t_{col}_l"][3], col
        assert (src[f"e_b_{col}_stub"][3] - src[f"e_b_{col}_stub"][1]
                == pytest.approx(d_in)), col
        assert (src[f"e_t_{col}_stub"][3] - src[f"e_t_{col}_stub"][1]
                == pytest.approx(d_in)), col
    # 1×4 无折弯链，无镜像审计
    _c1, lay1, _s1 = _arr_rects_single_source("patch_array_1x4")
    assert lay1["mirror_audit"] is None


def test_build_seat_geometry_fake_executable_face():
    """8 席 builder 可执行面 mock 审计（零真机零网络；断链审计 fail-fast/
    逐片与并集 bbox 自审/#310 unite 保首名在真调 build_seat_geometry 中逐席
    过账——到达断言即全过）。"""
    pytest.importorskip("ansys.aedt.core")
    from ansys.aedt.core.generic.constants import Gravity

    for name in _ALL_SEATS:
        seat = mod.SEATS[name]
        ctx = mod.seat_context(name)
        h = _FakeHfss()
        build = mod.build_seat_geometry(h, name, ctx)
        m = h.modeler
        # 端口面：波端口+集总口计数 == n_ports（patch 阵=0 波端口+1 探针）
        n_lport = len(m.lumped_ports)
        assert len(m.wave_ports) + n_lport == seat["n_ports"], name
        # PerfectE：金属并集+地板两薄片（#356①）；unite 保首名（#310）
        assert [a for a, _n in m.pec_assignments] == [
            [build["unite_kept"], "GGnd"]], name
        assert build["unite_kept"] == m.unite_calls[0][0]
        assert build["audit"]["ports_ok"] is True
        # 辐射开放面（ASSIGN_RADIATION 先例；面心过滤+空选守卫已过）
        assert build["n_radiation_faces"] >= 1, name
        assert len(m.radiation_assignments) == 1
        if seat["template"].startswith("patch_array"):
            # 辐射族：顶+四侧 5 面辐射边界（底=PEC 地不入辐射面，criteria §2）
            assert build["n_radiation_faces"] == 5, name
            assert m.wave_ports == []
            lp = m.lumped_ports[0]
            assert lp["name"] == "P1" and lp["impedance"] == 50.0
            assert lp["integration_line"] == Gravity.ZPos
            assert build["vias"] == []
    # gysel：2×50Ω 竖直集总（ZPos 电流，XZ 薄片 sizes=[h,w] 轴向映射）
    ctx = mod.seat_context("gysel")
    h = _FakeHfss()
    build = mod.build_seat_geometry(h, "gysel", ctx)
    assert [k["resistance"] for k in h.modeler.lumped_rlc] == [50.0, 50.0]
    assert all(k["start_direction"] == Gravity.ZPos
               for k in h.modeler.lumped_rlc)
    assert all(k["rlc_type"] == "Parallel" for k in h.modeler.lumped_rlc)
    assert len(h.modeler.wave_ports) == 3
    # wilkinson 先例不回归：100Ω 隔离电阻仍 XPos（XY 片）
    h2 = _FakeHfss()
    mod.build_seat_geometry(h2, "wilkinson", mod.seat_context("wilkinson"))
    riso = h2.modeler.lumped_rlc[0]
    assert riso["resistance"] == 100.0
    assert riso["start_direction"] == Gravity.XPos


def test_wave_port_sheet_bbox_all_seats():
    """波端口薄片 bbox 逐席独立断言（review-slice4 P0-1/P1-1 防线）：edge_y
    席=XZ 横截面薄片（x∈[xc−w/2,xc+w/2]@y=edge、法向 y 跨=0）；edge_x 席=
    YZ 竖片（y∈[yc−w/2,yc+w/2]@x=edge、法向 x 跨=0）；z 跨=[0, 声明端口高]
    （波端口截面高于基板入空气的微带惯例，非基板高 h_mm）。期望值由端口
    定义在测试侧独立推导（不信被测代码内的 _audit_obj 自身）；fake 轴向
    映射=pyaedt 实码口径（XZ sizes=(z,x)、YZ sizes=(y,z)）——薄片平面/
    尺寸/位置错误当场红（变异验证：edge_y 回滚 YZ+[w,h] 即红）。"""
    pytest.importorskip("ansys.aedt.core")
    checked = 0
    for name in _ALL_SEATS:
        ctx = mod.seat_context(name)
        lay = mod.seat_layout(name, ctx)
        h = _FakeHfss()
        mod.build_seat_geometry(h, name, ctx)
        for pt in lay["ports"]:
            sheet = f"{pt['name']}sheet"
            assert sheet in h.modeler.rect_bboxes, (name, sheet)
            if "edge_y" in pt:
                xc, edge = float(pt["center_x"]), float(pt["edge_y"])
                want = [xc - pt["w"] / 2, edge, 0.0,
                        xc + pt["w"] / 2, edge, float(pt["h"])]
            else:
                x_edge, cy = float(pt["edge"][1]), float(pt["center_y"])
                want = [x_edge, cy - pt["w"] / 2, 0.0,
                        x_edge, cy + pt["w"] / 2, float(pt["h"])]
            got = h.modeler.rect_bboxes[sheet]
            assert got == pytest.approx(want, abs=1e-6), (name, sheet, got)
            # 积分线两端点必须落在薄片 bbox 内（零厚轴=面坐标）——edge_x
            # 分支原 [y_c,x_edge,…] 坐标序换位（积分线离片）由本断言钉住
            by_name = {w["name"]: w for w in h.modeler.wave_ports}
            wp = by_name.get(pt["name"])
            assert wp is not None, (name, pt["name"])
            for p_xyz in wp["integration_line"]:
                px = [_mmf(c) for c in p_xyz]
                for axis in range(3):
                    lo, hi = sorted((got[axis], got[axis + 3]))
                    assert lo - 1e-9 <= px[axis] <= hi + 1e-9, \
                        (name, pt["name"], axis, px)
            # 积分线方向钉（review-slice5 P3-1）：start=地面(z=0)→end=导带
            # 上缘（z=h_mm 基板顶；df6⑪/Gravity.ZPos/same_geometry/ratrace
            # 全部真机先例同向；原导带→地已统一翻转——方向变异在此当场红）
            iz = [_mmf(p[2]) for p in wp["integration_line"]]
            assert iz[0] == pytest.approx(0.0, abs=1e-9), (name, pt["name"], iz)
            assert iz[1] == pytest.approx(float(ctx["h_mm"]), abs=1e-6), \
                (name, pt["name"], iz)
            checked += 1
    assert checked == 16   # 13 edge_y + 3 edge_x（patch 两席无波端口）


# ═══════════════ OE 参考解析（真产物在档对账 / 缺档诚实 skip / 回退封顶）══════════════

def _oe_csv_exists(rel: str) -> bool:
    return (REPO / rel).exists()


def test_oe_refs_wilkinson_from_real_artifact():
    """真产物在档（oe_nominal_README 2026-09-28 补齐）→ 同口径提取对账
    （产物 verdict.json 标量：f_dip 2.2075 / s23_max −19.4 / s21@f0 −3.34）。"""
    rel = "runs/hfss_window_b2a/wilkinson/oe_nominal/sparams.csv"
    if not _oe_csv_exists(rel):
        pytest.skip(f"真机 OE 产物不在档（gitignored 工作区证据）：{rel}")
    refs = mod.resolve_oe_refs("wilkinson")
    assert refs["cap"] is None
    vals = refs["values"]
    assert vals.get("f_match_ghz") == pytest.approx(2.2075, abs=0.01)
    assert vals.get("s23_band_max_db") == pytest.approx(-19.4, abs=0.1)
    assert vals.get("s21_at_match_db") == pytest.approx(-3.28, abs=0.1)


def test_oe_refs_coupled_line_wideband():
    rel = "runs/hfss_window_b2a/coupled_line/oe_nominal_wideband/sparams.csv"
    if not _oe_csv_exists(rel):
        pytest.skip(f"真机 OE 产物不在档：{rel}")
    vals = mod.resolve_oe_refs("coupled_line")["values"]
    assert vals.get("coupling_at_f0_db") == pytest.approx(-12.01, abs=0.05)
    # review-fix8 P1-2（#298 口径）：f_peak=峰 −3dB 带心（带 [2.388,3.0] 上沿
    # 触窗 censored），旧 argmax 峰位 2.955 撤销
    assert vals.get("f_peak_ghz") == pytest.approx(2.694, abs=0.01)
    assert vals.get("through_at_f0_db") == pytest.approx(-0.45, abs=0.05)


def test_oe_refs_branchline_touchstone():
    rel = "runs/branchline_real_anchor/branchline.s4p"
    if not _oe_csv_exists(rel):
        pytest.skip(f"真机 OE 产物不在档：{rel}")
    vals = mod.resolve_oe_refs("branchline")["values"]
    assert vals.get("f_match_ghz") == pytest.approx(2.136, abs=0.01)
    assert abs(vals.get("split_db")) == pytest.approx(0.054, abs=0.02)  # 符号随端口序
    assert vals.get("s11_min_db") == pytest.approx(-48.78, abs=0.5)


def test_oe_refs_gysel_verdict_fields():
    rel = "runs/gysel_miter_ab/verdict.json"
    if not _oe_csv_exists(rel):
        pytest.skip(f"真机 OE 产物不在档：{rel}")
    vals = mod.resolve_oe_refs("gysel")["values"]
    assert vals.get("s21_at_f0_db") == pytest.approx(-3.2213, abs=1e-3)
    assert vals.get("s32_band_max_db") == pytest.approx(-22.48, abs=0.05)
    assert vals.get("s11_at_f0_db") == pytest.approx(-24.99, abs=0.05)


def test_oe_refs_marchand_constants():
    vals = mod.resolve_oe_refs("marchand_balun")["values"]
    assert vals["f_null_ghz"] == pytest.approx(3.272)
    assert vals["s21_band_min_db"] == pytest.approx(-6.44)
    assert vals["imbalance_band_max_db"] == pytest.approx(1.085)


def test_oe_refs_closed_form_fallback_caps_agree_hfss(tmp_path, monkeypatch):
    """产物缺失 → 闭式回退 + cap=AGREE_HFSS（criteria §1b）；offline 用 tmp
    伪造空仓根（REPO 重定向，不触真 runs）。"""
    monkeypatch.setattr(mod, "REPO", tmp_path)
    refs = mod.resolve_oe_refs("wilkinson")
    assert refs["cap"] == "AGREE_HFSS"
    assert refs["source"] == "closed_form:wilkinson_hj"
    f_hj = refs["values"]["f_match_ghz"]
    assert 2.0 < f_hj < 3.0                      # HJ λ/4@εeff 量级合理
    refs_c = mod.resolve_oe_refs("coupled_line")
    assert refs_c["cap"] == "AGREE_HFSS"
    assert refs_c["closed_form"]["kj"]["z0e_ohm"] > refs_c["closed_form"]["kj"]["z0o_ohm"]
    refs_b = mod.resolve_oe_refs("branchline")
    assert refs_b["cap"] is None                 # 常量回退不封顶（预声明值）
    assert refs_b["values"]["f_match_ghz"] == pytest.approx(2.136)


def test_oe_branchline_fallback_note_present():
    fb = mod.SEATS["branchline"]["oe"]["fallback_note"]
    assert "@f_match" in fb                       # 带内包络代比注记（#122 如实）


# ═══════════════ run_seat 编排（dry 端到端 + fail-closed mock 面）══════════════

def test_run_seat_dry_end_to_end(tmp_path):
    """dry-run 端到端（零 pyaedt）：OE 解析→合成链→阶梯→G11→判读→落盘。

    UNDECIDABLE 也在合法集内：干净 checkout 无 runs/ 产物（gitignored）时
    OE 回退闭式仍缺值 → 指标 UNKNOWN → 总态 UNDECIDABLE（#122 如实）。"""
    v = mod.run_seat("wilkinson", machine="local", out_dir=tmp_path,
                     dry_run=True)
    assert v["verdict"] in (*mod._OK_VERDICTS, "UNDECIDABLE")
    assert v["status"] == "DONE"
    assert v["ladder"]["chosen_level"] == 3
    assert v["g11"]["passive"] is True
    assert len(v["per_metric"]) == 5
    # 合成数据醒目标记（review-slice4 P3）：HFSS 列=synthetic_s 合成值，
    # verdict 须带 data_provenance="synthetic"（消费者不作验收依据）
    assert v["dry_run"] is True
    assert v["data_provenance"] == "synthetic"
    assert "合成" in v["synthetic_note"] and "不作" in v["synthetic_note"]
    for f in ("verdict.json", "verdict.md", "progress.log"):
        assert (tmp_path / f).exists(), f
    saved = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    assert saved["verdict"] == v["verdict"]
    assert saved["data_provenance"] == "synthetic"
    md = (tmp_path / "verdict.md").read_text(encoding="utf-8")
    assert v["verdict"] in md and "| 指标 |" in md
    assert "SYNTHETIC DATA" in md        # md 首屏横幅（消费者第一眼可见）


@pytest.mark.parametrize("seat_name", _ALL_SEATS)
def test_run_seat_dry_all_seats_produce_verdicts(tmp_path, seat_name):
    """8 席 dry 链全通（判读/OE/阶梯面对全席就绪的证明；产物缺档时
    UNDECIDABLE 合法，见 test_run_seat_dry_end_to_end 注）。"""
    v = mod.run_seat(seat_name, machine="local",
                     out_dir=tmp_path / seat_name, dry_run=True)
    assert v["verdict"] in (*mod._OK_VERDICTS, "UNDECIDABLE"), \
        (seat_name, v.get("error"))
    assert v["status"] == "DONE"
    assert v["wall_s"] < 1.5 * v["budget_min"] * 60


def test_run_seat_fail_closed_connect_error(tmp_path, monkeypatch):
    """fail-closed：连接异常 → verdict FAIL + 证据落盘，异常不逃逸。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)

    def _boom(seat, project_path):
        raise ConnectionError("gRPC 拒绝（mock）")

    monkeypatch.setattr(mod, "open_local_hfss", _boom)
    v = mod.run_seat("stepped_impedance", machine="local", out_dir=tmp_path,
                     dry_run=False)
    assert v["verdict"] == "FAIL"
    assert "ConnectionError" in v["error"]
    assert (tmp_path / "verdict.json").exists()
    # 真机/mock 路径不得冒充合成标记（review-slice4 P3 反向钉）
    assert v.get("data_provenance") is None


def test_run_seat_license_error_maps_to_skip(tmp_path, monkeypatch):
    """许可类异常（FlexNet/-8,544）→ SKIP 如实（不冒充 FAIL 也不凑绿）。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)

    def _lic(seat, project_path):
        raise RuntimeError("FlexNet license checkout failed (-8,544)")

    monkeypatch.setattr(mod, "open_local_hfss", _lic)
    v = mod.run_seat("stepped_impedance", machine="local", out_dir=tmp_path,
                     dry_run=False)
    assert v["verdict"] == "SKIP"
    assert "许可" in v["status"]


def test_run_seat_ansysedt_residue_blocks(tmp_path, monkeypatch):
    """#265：本机 ansysedt 残留 >0 → 起跑前阻塞（SKIP，不代杀）。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 2)
    launched = []

    def _no_launch(seat, project_path):
        launched.append(project_path)
        raise AssertionError("残留>0 不得起跑")

    monkeypatch.setattr(mod, "open_local_hfss", _no_launch)
    v = mod.run_seat("stepped_impedance", machine="local", out_dir=tmp_path,
                     dry_run=False)
    assert v["verdict"] == "SKIP"
    assert v["ansysedt_before"] == 2
    assert launched == []


def test_run_seat_skeleton_rearm_fail_closed(tmp_path, monkeypatch):
    """skeleton 防线（builders2 补批后 8/8 full，防线保留）：显式改回
    skeleton 的席真机路径 = SKIP(实现待续)（NotImplementedError fail-closed，
    绝不凑跑）。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)
    monkeypatch.setitem(mod.SEATS["gysel"], "builder_status", "skeleton")

    class _Dummy:                                  # 不触 pyaedt
        def release_desktop(self, **kw):
            pass

    monkeypatch.setattr(mod, "open_local_hfss", lambda seat, p: _Dummy())
    v = mod.run_seat("gysel", machine="local", out_dir=tmp_path, dry_run=False)
    assert v["verdict"] == "SKIP"
    assert "实现待续" in v["status"]


def test_run_seat_remote_export_fetch_fail_is_fail(tmp_path, monkeypatch):
    """远程：导出后回取失败 → FAIL（verdict 无从判读，不虚构数据）。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)
    monkeypatch.setattr(mod, "remote_license_preflight",
                        lambda m, deep=False: {"verdict": "PASS",
                                               "reason": None})
    monkeypatch.setattr(mod, "open_remote_hfss",
                        lambda seat, machine, *, grpc_port=None: (
                            None, object(),
                            {"remote": {"project_root": "X"},
                             "server_project": "X\\p.aedt"}))
    monkeypatch.setattr(mod, "build_seat",
                        lambda h, name, ctx: {"notes": [], "ports": []})
    monkeypatch.setattr(mod, "make_setup_and_sweep", lambda h, seat, level: "Setup")
    monkeypatch.setattr(mod, "solve_with_watchdog",
                        lambda h, setup: {"solve_s": 1.0})
    monkeypatch.setattr(mod, "export_network_data", lambda h, p: None)
    monkeypatch.setattr(mod, "fetch_remote_file",
                        lambda machine, rp, lp: False)
    v = mod.run_seat("stepped_impedance", machine="sim_host",
                     out_dir=tmp_path, dry_run=False)
    assert v["verdict"] == "FAIL"
    assert "回取失败" in v["error"]


def test_run_seat_budget_overtime_marks_partial(tmp_path, monkeypatch):
    """预算守卫：wall > 1.5×budget → status PARTIAL 如实（门不放宽）。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)
    calls = {"n": 0}

    class FakeTime:
        @staticmethod
        def monotonic() -> float:
            calls["n"] += 1
            return 1000.0 + 100000.0 * calls["n"]   # 步进 1e5s ≫ 1.5×预算

        @staticmethod
        def strftime(_fmt: str) -> str:
            return "fake"

    fake_time = type("M", (), {"monotonic": staticmethod(FakeTime.monotonic),
                               "strftime": staticmethod(FakeTime.strftime)})
    monkeypatch.setattr(mod, "time", fake_time)

    def _boom(seat, project_path):
        raise ConnectionError("gRPC 拒绝")

    monkeypatch.setattr(mod, "open_local_hfss", _boom)
    v = mod.run_seat("wilkinson", machine="local", out_dir=tmp_path,
                     dry_run=False)
    assert v["verdict"] == "FAIL"
    assert "超预算" in v["status"]
    assert v["wall_s"] > 1.5 * v["budget_min"] * 60


# ═══════════════ CLI（--help/--list/--dry-run dry-call 钉，#df4②）══════════════

def test_cli_help_and_list(capsys):
    with pytest.raises(SystemExit) as ei:
        mod.main(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    assert "--seat" in out and "--machine" in out and "--dry-run" in out
    rc = mod.main(["--list"])
    assert rc == 0
    out2 = capsys.readouterr().out
    for name in _ALL_SEATS:
        assert name in out2
    assert out2.index("stepped_impedance") < out2.index("patch_array_2x2")


def test_cli_requires_seat_or_all():
    with pytest.raises(SystemExit) as ei:
        mod.main([])
    assert ei.value.code == 2                     # argparse 用法错


def test_cli_dry_run_end_to_end(tmp_path, capsys):
    """--seat wilkinson --dry-run 全链（退出码 0=合法裁决态；依赖真机 OE
    产物在档，缺档时 UNDECIDABLE→rc 1 如实，诚实 skip）。"""
    if not _oe_csv_exists("runs/hfss_window_b2a/wilkinson/oe_nominal/"
                          "sparams.csv"):
        pytest.skip("真机 OE 产物不在档（gitignored 工作区证据）")
    rc = mod.main(["--seat", "wilkinson", "--dry-run",
                   "--out-dir", str(tmp_path / "dry")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert (tmp_path / "dry" / "verdict.json").exists()


def test_synthetic_s_finite_and_disagree_moves_valley():
    seat = mod.SEATS["wilkinson"]
    freq = np.linspace(2.0e9, 3.0e9, 201)
    s_ok = mod.synthetic_s("wilkinson", freq, "agree")
    assert s_ok.shape == (201, 3, 3)
    assert bool(np.all(np.isfinite(s_ok)))
    m_ok = mod.extract_metrics(freq, s_ok, seat)
    m_no = mod.extract_metrics(freq, mod.synthetic_s("wilkinson", freq,
                                                     "disagree"), seat)
    assert abs(m_ok["f_match_ghz"] - m_no["f_match_ghz"]) > 0.05


def test_spec_notes_present():
    notes_m = mod._spec_notes("marchand_balun")
    assert any("2 模" in n for n in notes_m)
    notes_g = mod._spec_notes("gysel")
    assert any("2.25–2.75" in n for n in notes_g)
    assert mod._spec_notes("wilkinson") == []


def test_implementation_notes_reach_verdict(tmp_path):
    v = mod.run_seat("marchand_balun", machine="local",
                     out_dir=tmp_path / "mb", dry_run=True)
    joined = " ".join(v.get("implementation_notes", []))
    assert "2 模端口" in joined
    assert "端接口径" in joined


def test_all_extractors_require_measured_semantics_consistent():
    """席指标提取键与门引用双向一致（#231 消费者纪律在驱动内的等价物）。"""
    for name in _ALL_SEATS:
        seat = mod.SEATS[name]
        ex_keys = {e["metric"] for e in seat["extractors"]}
        for gate in seat["gates"]:
            assert gate["metric"] in ex_keys
        scalars = seat["ladder_scalars"]
        assert set(scalars) <= ex_keys
        for e in seat["extractors"]:
            if "ref" in e:
                assert e["ref"] in ex_keys, (name, e["metric"])


def test_judge_diff_zero_gate_boundary_is_pass():
    """#364 族：差值恰=门宽 → 过（≤）；深度谷值 0.0 不被 or 陷阱顶替。"""
    r = mod.judge_metric(3.0, 3.0, _gate(gate=0.3, kind="db_diff"))
    assert r["state"] == "AGREE_JUDGE" and r["diff"] == 0.0
    r2 = mod.judge_metric(0.0, 0.0, _gate(gate=0.3, kind="db_diff"))
    assert r2["state"] == "AGREE_JUDGE"
    assert not math.isnan(r2["diff"])


# ═══════════════ review-fix3（P1-1/P1-2/P2-1/P3）回归钉 ═══════════════

def test_extract_metrics_first_pass_locators_honor_mask():
    """P2-1：第一遍定位量（s_db_min/max_*）同过 #314 掩码——定位元素未测
    → None（零填充列不参与定位），引用量（*_at_ref）随 ref 缺失级联 None。"""
    seat = mod.SEATS["wilkinson"]
    mask = np.zeros((3, 3), dtype=bool)           # 单激励零填充形态极端例
    m = mod.extract_metrics(FREQ, _synth_wilkinson_like(), seat, mask)
    assert m["f_match_ghz"] is None               # 第一遍定位量被掩码拦下
    assert m["s11_min_db"] is None
    assert m["s21_at_match_db"] is None           # ref 缺失级联
    assert m["split_db"] is None
    mask2 = np.zeros((3, 3), dtype=bool)
    mask2[0, 0] = True                            # 仅对角已测 → 定位量恢复
    m2 = mod.extract_metrics(FREQ, _synth_wilkinson_like(), seat, mask2)
    assert m2["f_match_ghz"] is not None
    assert abs(m2["f_match_ghz"] - 2.2075) < 0.01
    assert m2["s21_at_match_db"] is None          # (1,0) 仍未测


def test_convergence_record_two_states(monkeypatch):
    """P1-2：提取失败≠触顶两态分开——异常/passes==0/setup 缺失→
    extraction_failed=True 且不带 passes（零收敛证据不得伪装未触顶）；
    正常提取路径形态钉（passes/final_delta_s 在位+显式 False）。"""
    target = "rfauto.adapters.hfss_adapter.HfssAdapter._extract_convergence"
    monkeypatch.setattr(target, staticmethod(lambda setup: (12, 0.02)))
    rec = mod.convergence_record(_setup_h(object()))
    assert rec == {"passes": 12, "final_delta_s": 0.02,
                   "extraction_failed": False}
    monkeypatch.setattr(target, staticmethod(
        lambda setup: (_ for _ in ()).throw(RuntimeError("gRPC 断"))))
    assert mod.convergence_record(_setup_h(object())) == {
        "extraction_failed": True}
    monkeypatch.setattr(target, staticmethod(lambda setup: (0, 0.0)))
    assert mod.convergence_record(_setup_h(object())) == {
        "extraction_failed": True}                # passes==0 与成功互斥
    assert mod.convergence_record(_setup_h(None)) == {
        "extraction_failed": True}                # setup 缺失


def test_ladder_pick_extraction_failed_not_usable():
    """P1-2 判读链：extraction_failed 档不判读（与 topped 两态分开），采信
    最深可用档并在报告留档失败层；全档失败→不可判读+如实 UNKNOWN 注记。"""
    gates = (_gate(metric="f_match_ghz", gate=3.0),)
    scalars = ("f_match_ghz",)
    rungs = [
        {"level": 1, "topped": False, "extraction_failed": True,
         "metrics": {"f_match_ghz": 2.30}},
        {"level": 2, "topped": False, "extraction_failed": False,
         "metrics": {"f_match_ghz": 2.20}},
    ]
    rep = mod.ladder_pick(rungs, gates, scalars)
    assert rep["chosen_level"] == 2
    assert rep["extraction_failed_levels"] == [1]
    assert rep["rungs"][0]["extraction_failed"] is True
    all_failed = [{"level": k, "topped": False, "extraction_failed": True,
                   "metrics": {}} for k in (1, 2, 3)]
    rep2 = mod.ladder_pick(all_failed, gates, scalars)
    assert rep2["chosen_level"] is None
    assert "提取失败" in rep2["reason"] and "UNKNOWN" in rep2["reason"]


def test_run_seat_partial_extraction_failed_keeps_usable_rung(tmp_path,
                                                              monkeypatch):
    """P1-2 端到端：档 1/2 提取失败→如实 UNKNOWN 不判收敛门，档 3 可用照常
    采信；verdict 注记逐档点名（正常提取路径判读零变化）。"""
    conv_seq = [{"extraction_failed": True}, {"extraction_failed": True},
                {"passes": 30, "final_delta_s": 0.004,
                 "extraction_failed": False}]
    sink: list = [[], tmp_path]
    _patch_remote_pipeline(monkeypatch, conv_seq, sink)
    v = sink[0][0]
    assert v["verdict"] != "FAIL"
    ladder = v["ladder"]
    assert ladder["chosen_level"] == 3
    assert ladder["extraction_failed_levels"] == [1, 2]
    assert [r["extraction_failed"] for r in ladder["rungs"]] == \
        [True, True, False]
    assert all(r["passes"] is None for r in ladder["rungs"][:2])
    notes = " ".join(v.get("implementation_notes", []))
    assert "收敛证据提取失败" in notes and "UNKNOWN" in notes
    assert "档 1" in notes and "档 2" in notes
    assert "档 3" not in notes


def test_run_seat_all_extraction_failed_is_fail_closed(tmp_path, monkeypatch):
    """P1-2 端到端：全档提取失败→无可用档→FAIL（fail-closed，不凑判）；
    ladder reason 如实 UNKNOWN（提取失败≠触顶，两态分开留档）。"""
    sink: list = [[], tmp_path]
    _patch_remote_pipeline(monkeypatch, [{"extraction_failed": True}], sink)
    v = sink[0][0]
    assert v["verdict"] == "FAIL"
    assert "收敛证据提取失败 3 档" in v["error"]
    assert v["ladder"]["chosen_level"] is None
    assert "UNKNOWN" in v["ladder"]["reason"]


def test_open_remote_hfss_switches_active_at_construction(monkeypatch):
    """P1-1：远程分支构造期消费共享单源四开关（grpc_local/grpc_secure_mode
    False+remote_rpc_session True+PRE_GRPC_ARGS 环境变量在位），目录 bootstrap
    先于 Desktop 构造，attach 后 remote_rpc_session 置 None（remote_service
    同款），CM 退出后本机 settings/env 零残留。"""
    calls: dict = {}
    aedt_settings = _patch_remote_session(monkeypatch, calls)
    saved = (aedt_settings.grpc_local, aedt_settings.grpc_secure_mode,
             aedt_settings.remote_rpc_session,
             os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS"))
    try:
        _desktop, _h, info = mod.open_remote_hfss(
            {"template": "wilkinson"}, "sim_host")
    finally:
        pass
    d = calls["desktop"]
    assert d["grpc_local"] is False and d["grpc_secure_mode"] is False
    assert d["remote_rpc_session"] is True           # 防 new_desktop 翻转坑
    assert d["pre_grpc_args"] == "True"
    assert d["kw"]["machine"] == "10.20.30.40"
    assert d["kw"]["port"] == 50051 and d["kw"]["new_desktop"] is False
    assert calls["hfss"]["remote_rpc_session"] is None   # attach 后置 None
    assert calls["hfss"]["kw"]["project"].endswith("project.aedt")
    assert calls["order"] == ["bootstrap", "desktop", "hfss"]
    assert calls["bootstrap"] == [(
        "sim_host",
        "E:\\rfauto_remote\\hfss_window_b2a\\wilkinson\\hfss_side")]
    assert info["server_project"].endswith("project.aedt")
    assert info["project_dir"].endswith("hfss_side")
    # CM 退出零残留（构造期快照消费、退出恢复原值，不污染本地会话）
    assert (aedt_settings.grpc_local, aedt_settings.grpc_secure_mode,
            aedt_settings.remote_rpc_session,
            os.environ.get("PYAEDT_USE_PRE_GRPC_ARGS")) == saved


def test_open_remote_hfss_bootstrap_fail_closed(monkeypatch):
    """P1-1：服务器目录预建失败 → 显式 RuntimeError（无目录不发射），Desktop
    构造不得开始。"""
    calls: dict = {}
    _patch_remote_session(monkeypatch, calls, bootstrap_ok=False)
    with pytest.raises(RuntimeError, match="预建失败"):
        mod.open_remote_hfss({"template": "wilkinson"}, "sim_host")
    assert calls["order"] == ["bootstrap"]        # attach 未开始


def test_ensure_remote_project_dir_cmd_mkdir(monkeypatch):
    """P1-1：bootstrap 走注册表 SSH 面，命令=cmd /c mkdir（Windows 服务器
    cmd/PowerShell 缺省 shell 双兼容，中间目录自动建）；SSH 面故障→False。"""
    sent: list = []

    class _T:
        def __init__(self, cfg):
            pass

        def connect(self):
            pass

        def run_command(self, cmd, timeout_s=60.0):
            sent.append(cmd)
            return 0, "", ""

        def close(self):
            pass

    base = "rfauto.infra.remote_machines"
    monkeypatch.setattr(f"{base}.SshTransport", _T)
    monkeypatch.setattr(f"{base}.load_remote_machines",
                        lambda: {"sim_host": object()})
    monkeypatch.setattr(f"{base}.resolve_machine", lambda name, table: object())
    ok = mod.ensure_remote_project_dir("sim_host",
                                       "E:\\rfauto_remote\\a\\b")
    assert ok is True
    assert sent == ['cmd /c mkdir "E:\\rfauto_remote\\a\\b"']

    class _TDown(_T):
        def connect(self):
            raise OSError("ssh down")

    monkeypatch.setattr(f"{base}.SshTransport", _TDown)
    assert mod.ensure_remote_project_dir("sim_host", "E:\\x") is False


def test_is_license_error_fingerprint_variants():
    """P3：FlexNet -8,544（带逗号）与 -8544（无逗号）两形态都命中；非许可
    异常不误报。"""
    assert mod._is_license_error(RuntimeError("lmgrd checkout (-8,544)"))
    assert mod._is_license_error(RuntimeError("FlexNet Licensing error:-8544"))
    assert mod._is_license_error(RuntimeError("license server unreachable"))
    assert not mod._is_license_error(RuntimeError("Connection refused"))


def test_run_all_exit_code_semantics(tmp_path, monkeypatch):
    """P3：--all 汇总退出码与单席语义同源（原恒 0 修复）——FAIL/UNDECIDABLE
    →1；无 FAIL 有 SKIP→2；全合法裁决态→0。"""
    monkeypatch.setattr(mod, "OUT_ROOT", tmp_path)      # 防污染真实 runs/
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)

    def _seats(verdict):
        return lambda seat_name, machine="local", dry_run=False, out_dir=None: {
            "seat": seat_name, "verdict": verdict, "status": verdict,
            "wall_s": 1.0}

    for verdict, want in (("AGREE_JUDGE", 0), ("AGREE_HFSS", 0),
                          ("SKIP", 2), ("FAIL", 1), ("UNDECIDABLE", 1)):
        monkeypatch.setattr(mod, "run_seat", _seats(verdict))
        assert mod.run_all("local", dry_run=False) == want, verdict


# ═══════════════ 并行发射（wf:hfss-window-parallel）═══════════════

def test_partition_waves_shapes():
    """波次划分纯函数：每波 parallel 席按发射序切、末波允许不满；parallel<1
    fail-closed。"""
    names = list(mod.LAUNCH_ORDER)
    assert mod.partition_waves(names, 3) == [
        names[0:3], names[3:6], names[6:8]]
    assert mod.partition_waves(names, 1) == [[n] for n in names]
    assert mod.partition_waves(names, 8) == [names]
    assert mod.partition_waves(names, 10) == [names]     # N>席数：单波不越界
    assert mod.partition_waves([], 4) == []
    with pytest.raises(ValueError):
        mod.partition_waves(names, 0)
    with pytest.raises(ValueError):
        mod.partition_waves(names, -2)


def test_assign_seat_ports_wave_reuse():
    """端口分配纯函数：base+波内下标（50051+0..N-1），下一波同下标席位复用
    同端口；--port-base 可覆盖；parallel<1 fail-closed。"""
    names = list(mod.LAUNCH_ORDER)
    ports = mod.assign_seat_ports(names, 3)
    assert ports["stepped_impedance"] == 50051      # 波1 下标 0
    assert ports["coupled_line"] == 50052
    assert ports["wilkinson"] == 50053
    assert ports["marchand_balun"] == 50051         # 波2 下标 0：波次复用
    assert ports["patch_array_2x2"] == 50052
    assert mod.assign_seat_ports(names, 3, 60000)["stepped_impedance"] == 60000
    assert set(mod.assign_seat_ports(names, 1).values()) == {50051}
    with pytest.raises(ValueError):
        mod.assign_seat_ports(names, 0)


def test_assign_ports_matches_partition():
    """分配器与切波器同构不变量：任一席位端口=port_base+其波内下标。"""
    names = list(mod.LAUNCH_ORDER)
    for n in (1, 2, 3, 5, 8, 9):
        waves = mod.partition_waves(names, n)
        ports = mod.assign_seat_ports(names, n, 50051)
        for wave in waves:
            for j, name in enumerate(wave):
                assert ports[name] == 50051 + j, (n, name)


def test_seat_argv_wiring():
    """单席子进程 argv：--grpc-port 仅 remote 真机路径携带；--no-residue-check
    仅 local 并行真机路径携带；--dry-run 透传；缺省最小面。"""
    base = {"machine": "sim_host", "out_dir": Path("o"), "dry_run": False}
    argv = mod._seat_argv("wilkinson", grpc_port=50052, residue_check=True,
                          **base)
    assert "--grpc-port" in argv and argv[argv.index("--grpc-port") + 1] == "50052"
    assert "--no-residue-check" not in argv and "--dry-run" not in argv
    # local 并行真机：端口不传（本机实例端口由 pyaedt 自管），残留检查关
    argv = mod._seat_argv("wilkinson", machine="local", out_dir=Path("o"),
                          dry_run=False, grpc_port=None, residue_check=False)
    assert "--no-residue-check" in argv
    assert "--grpc-port" not in argv
    # dry-run：--dry-run 透传、无端口无残留开关
    argv = mod._seat_argv("wilkinson", machine="local", out_dir=Path("o"),
                          dry_run=True, grpc_port=None, residue_check=True)
    assert "--dry-run" in argv and "--grpc-port" not in argv
    assert "--no-residue-check" not in argv
    assert argv.count("--seat") == 1 and argv[argv.index("--out-dir") + 1] == "o"


def test_run_all_parallel_two_waves_dry_mock(tmp_path, monkeypatch):
    """并行编排 mock 面（2 波×2 席 dry-run）：波次推进/端口映射/子进程 argv/
    波内 max 预算池/summary 落盘/退出码——零真子进程。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER",
                        ("stepped_impedance", "coupled_line",
                         "wilkinson", "marchand_balun"))
    calls: list[list[str]] = []
    walls = {"stepped_impedance": 1.0, "coupled_line": 5.0,
             "wilkinson": 2.0, "marchand_balun": 7.0}

    def _fake_spawn(argv, out_dir, log_fh):
        calls.append(list(argv))
        seat = argv[argv.index("--seat") + 1]
        (Path(out_dir) / "verdict.json").write_text(json.dumps(
            {"seat": seat, "verdict": "AGREE_JUDGE", "status": "DONE",
             "wall_s": walls[seat]}), encoding="utf-8")
        return _FakeProc(0)

    monkeypatch.setattr(mod, "_spawn_seat", _fake_spawn)
    rc = mod.run_all_parallel("local", True, 2, out_root=tmp_path)
    assert rc == 0
    assert len(calls) == 4
    # 波内 2 席并行：argv 全 dry 面、无端口无残留开关（local+dry）
    for argv in calls:
        assert "--dry-run" in argv and "--grpc-port" not in argv
        assert "--no-residue-check" not in argv
        assert "--machine" in argv and "local" in argv
    s = json.loads((tmp_path / "window_summary.json").read_text(encoding="utf-8"))
    assert s["parallel"] == 2 and s["port_base"] == 50051
    assert s["seat_ports"] == {"stepped_impedance": 50051,
                               "coupled_line": 50052,
                               "wilkinson": 50051, "marchand_balun": 50052}
    assert [w["seats"] for w in s["waves"]] == [
        ["stepped_impedance", "coupled_line"], ["wilkinson", "marchand_balun"]]
    # 预算池：波墙钟=波内 max（非求和），campaign=Σ波max
    assert s["waves"][0]["wall_s_max"] == 5.0
    assert s["waves"][1]["wall_s_max"] == 7.0
    assert s["wall_s_campaign"] == 12.0
    assert [e["seat"] for e in s["seats"]] == [   # 发射序不乱（波内并行）
        "stepped_impedance", "coupled_line", "wilkinson", "marchand_balun"]
    assert all(e["verdict"] == "AGREE_JUDGE" and e["rc"] == 0
               for e in s["seats"])
    assert s["stopped_reason"] is None


def test_run_all_parallel_remote_ports_launch_cleanup(tmp_path, monkeypatch):
    """remote 真机并行：逐席端口分配（base+波内下标，波次复用）随 --grpc-port
    进 argv；波前 launch/波后 cleanup 全链携带 per-seat 端口与任务名。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER",
                        ("stepped_impedance", "coupled_line",
                         "wilkinson", "marchand_balun"))
    monkeypatch.setattr(mod, "remote_license_preflight",
                        lambda m, deep=False: {"verdict": "PASS",
                                               "reason": None})
    launches: list[tuple[str, int]] = []
    cleanups: list[tuple[str, int, str | None]] = []
    spawned: list[list[str]] = []

    def _fake_launch(machine, port, **kw):
        launches.append((machine, port))
        return {"ok": True, "port": port,
                "task_name": f"RFAuto\\hfss_window_{port}_deadbeef"}

    def _fake_cleanup(machine, port, *, task_name=None):
        cleanups.append((machine, port, task_name))
        return {"ok": True, "port": port, "killed_pids": []}

    def _fake_spawn(argv, out_dir, log_fh):
        spawned.append(list(argv))
        seat = argv[argv.index("--seat") + 1]
        (Path(out_dir) / "verdict.json").write_text(json.dumps(
            {"seat": seat, "verdict": "AGREE_JUDGE", "status": "DONE",
             "wall_s": 3.0}), encoding="utf-8")
        return _FakeProc(0)

    monkeypatch.setattr(mod, "launch_remote_grpcsrv", _fake_launch)
    monkeypatch.setattr(mod, "cleanup_remote_grpcsrv", _fake_cleanup)
    monkeypatch.setattr(mod, "_spawn_seat", _fake_spawn)
    rc = mod.run_all_parallel("sim_host", False, 2, port_base=60000,
                              out_root=tmp_path)
    assert rc == 0
    assert launches == [("sim_host", 60000), ("sim_host", 60001),
                        ("sim_host", 60000), ("sim_host", 60001)]
    # cleanup 与 launch 同席同端口同任务名（波次复用端口逐席清理不互杀）
    assert [(p, t) for _m, p, t in cleanups] == [
        (60000, "RFAuto\\hfss_window_60000_deadbeef"),
        (60001, "RFAuto\\hfss_window_60001_deadbeef"),
        (60000, "RFAuto\\hfss_window_60000_deadbeef"),
        (60001, "RFAuto\\hfss_window_60001_deadbeef")]
    ports_in_argv = [int(a[a.index("--grpc-port") + 1]) for a in spawned]
    assert ports_in_argv == [60000, 60001, 60000, 60001]
    assert all("--no-residue-check" not in a for a in spawned)  # remote 不传
    s = json.loads((tmp_path / "window_summary.json").read_text(encoding="utf-8"))
    assert s["port_base"] == 60000
    assert all(w["launch"] and w["cleanup"] for w in s["waves"])
    assert s["seats"][0]["verdict"] == "AGREE_JUDGE"


def test_run_all_parallel_launch_fail_fail_closed(tmp_path, monkeypatch):
    """grpcsrv 拉起失败席：fail-closed FAIL 落盘（verdict.json+summary）、
    子进程不发射；同波他席不受连坐；该端口仍进清理（任务可能在档）。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER",
                        ("stepped_impedance", "coupled_line",
                         "wilkinson", "marchand_balun"))
    monkeypatch.setattr(mod, "remote_license_preflight",
                        lambda m, deep=False: {"verdict": "PASS",
                                               "reason": None})
    spawned: list[str] = []

    def _fake_launch(machine, port, **kw):
        if port == 50052:
            return {"ok": False, "port": port, "reason": "schtasks create 非零"}
        return {"ok": True, "port": port,
                "task_name": f"RFAuto\\hfss_window_{port}_aa"}

    def _fake_spawn(argv, out_dir, log_fh):
        seat = argv[argv.index("--seat") + 1]
        spawned.append(seat)
        (Path(out_dir) / "verdict.json").write_text(json.dumps(
            {"seat": seat, "verdict": "AGREE_JUDGE", "status": "DONE",
             "wall_s": 1.0}), encoding="utf-8")
        return _FakeProc(0)

    cleanups: list[int] = []
    monkeypatch.setattr(mod, "launch_remote_grpcsrv", _fake_launch)
    monkeypatch.setattr(mod, "cleanup_remote_grpcsrv",
                        lambda m, p, *, task_name=None: cleanups.append(p)
                        or {"ok": True, "killed_pids": []})
    monkeypatch.setattr(mod, "_spawn_seat", _fake_spawn)
    rc = mod.run_all_parallel("sim_host", False, 2, out_root=tmp_path)
    assert rc == 1
    assert "coupled_line" not in spawned and "marchand_balun" not in spawned
    fail_entry = next(e for e in
                      json.loads((tmp_path / "window_summary.json")
                                 .read_text(encoding="utf-8"))["seats"]
                      if e["seat"] == "coupled_line")
    assert fail_entry["verdict"] == "FAIL"
    assert fail_entry["grpc_port"] == 50052
    v = json.loads((tmp_path / "coupled_line" / "hfss_side_remote" /
                    "verdict.json").read_text(encoding="utf-8"))
    assert v["verdict"] == "FAIL" and "拉起失败" in v["status"]
    assert 50051 in cleanups and 50052 in cleanups   # 失败席也清理


def test_run_all_parallel_verdict_missing_fail_closed(tmp_path, monkeypatch):
    """子进程未落 verdict（rc≠0）→ 该席 FAIL(verdict 缺失)，不静默放过。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER",
                        ("stepped_impedance", "coupled_line"))
    monkeypatch.setattr(mod, "_spawn_seat",
                        lambda argv, out_dir, fh: _FakeProc(1))
    rc = mod.run_all_parallel("local", True, 2, out_root=tmp_path)
    assert rc == 1
    s = json.loads((tmp_path / "window_summary.json").read_text(encoding="utf-8"))
    assert all(e["verdict"] == "FAIL" and "缺失" in e["status"]
               for e in s["seats"])


def test_run_all_parallel_local_residue_preflight(tmp_path, monkeypatch):
    """local 真机并行波前守卫（#265 上移）：残留>0 → 全席 SKIP 不发射、
    不代杀，rc=2。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER",
                        ("stepped_impedance", "coupled_line"))
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 3)
    spawned: list[str] = []

    def _fake_spawn(argv, out_dir, fh):
        spawned.append(argv[argv.index("--seat") + 1])
        return _FakeProc(0)

    monkeypatch.setattr(mod, "_spawn_seat", _fake_spawn)
    rc = mod.run_all_parallel("local", False, 2, out_root=tmp_path)
    assert rc == 2
    assert spawned == []
    s = json.loads((tmp_path / "window_summary.json").read_text(encoding="utf-8"))
    assert all(e["verdict"] == "SKIP" and "残留" in e["status"]
               for e in s["seats"])
    assert "#265" in s["stopped_reason"]
    assert s["waves"] == []


def test_run_all_default_serial_zero_change(tmp_path, monkeypatch):
    """缺省零变化钉：--parallel 缺省 1 时 run_all 走串行路径——summary 键集
    与逐席条目键集与改造前逐字节同面（无 parallel/waves/port_base 新键）；
    CLI 缺省参数钉 + 非法组合 parser.error。"""
    monkeypatch.setattr(mod, "OUT_ROOT", tmp_path)      # 防污染真实 runs/
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)

    def _seat(seat_name, machine="local", dry_run=False, out_dir=None):
        return {"seat": seat_name, "verdict": "AGREE_JUDGE",
                "status": "DONE", "wall_s": 1.0}

    monkeypatch.setattr(mod, "run_seat", _seat)
    assert mod.run_all("local", dry_run=True) == 0
    s = json.loads((tmp_path / "window_summary.json").read_text(encoding="utf-8"))
    assert set(s.keys()) == {"machine", "dry_run", "order", "seats", "ts"}
    assert all(set(e.keys()) == {"seat", "verdict", "status", "wall_s"}
               for e in s["seats"])
    assert len(s["seats"]) == 8

    # CLI 缺省：parallel=1 / port_base=50051 / grpc_port=None / 残留检查开
    captured: dict = {}

    def _fake_run_all(machine="local", dry_run=False, *, parallel=1,
                      port_base=mod.DEFAULT_GRPC_PORT_BASE, out_root=None):
        captured["all"] = (machine, dry_run, parallel, port_base, out_root)
        return 0

    def _fake_run_seat(seat_name, **kw):
        captured["seat"] = (seat_name, kw)
        return {"verdict": "AGREE_JUDGE"}

    monkeypatch.setattr(mod, "run_all", _fake_run_all)
    monkeypatch.setattr(mod, "run_seat", _fake_run_seat)
    assert mod.main(["--all"]) == 0
    assert captured["all"] == ("local", False, 1, 50051, None)
    assert mod.main(["--all", "--machine", "sim_host", "--dry-run",
                     "--out-dir", str(tmp_path)]) == 0
    assert captured["all"] == ("sim_host", True, 1, 50051, Path(tmp_path))
    assert mod.main(["--seat", "wilkinson"]) == 0
    seat_name, kw = captured["seat"]
    assert seat_name == "wilkinson"
    assert kw["grpc_port"] is None and kw["residue_check"] is True

    # 非法组合 fail-closed（argparse error → SystemExit）
    for bad in (["--all", "--parallel", "0"],
                ["--seat", "wilkinson", "--parallel", "2"],
                ["--all", "--grpc-port", "50055"],
                ["--all", "--parallel", "abc"]):
        with pytest.raises(SystemExit):
            mod.main(bad)


def test_run_seat_grpc_port_forwarded_and_recorded(tmp_path, monkeypatch):
    """run_seat 远程分支 grpc_port 接线：转发 open_remote_hfss 且随 verdict
    落档（仅非 None 时新增键）；缺省 None 时零新键（零变化面）。"""
    captured: dict = {}
    monkeypatch.setattr(mod, "remote_license_preflight",
                        lambda m, deep=False: {"verdict": "PASS",
                                               "reason": None})

    def _open(seat, machine, *, grpc_port=None):
        captured["grpc_port"] = grpc_port
        raise mod.LicenseBlockedError("probe skip（接线钉）")

    monkeypatch.setattr(mod, "open_remote_hfss", _open)
    v = mod.run_seat("wilkinson", machine="sim_host", out_dir=tmp_path,
                     grpc_port=50053)
    assert v["verdict"] == "SKIP"
    assert captured["grpc_port"] == 50053
    assert v["grpc_port"] == 50053
    captured.clear()
    v = mod.run_seat("wilkinson", machine="sim_host", out_dir=tmp_path)
    assert captured["grpc_port"] is None
    assert "grpc_port" not in v          # 缺省零变化：无端口覆盖零新键


def test_run_seat_residue_check_gate(tmp_path, monkeypatch):
    """residue_check=False 时 #265 残留检查（前+后）都不发生（并行子进程面）；
    缺省 True 保持现行为（前查发生）。"""
    calls = {"n": 0}

    def _count():
        calls["n"] += 1
        return 0

    def _boom(seat, project_path):
        raise RuntimeError("connect fail（fail-closed 钉）")

    monkeypatch.setattr(mod, "check_ansysedt_residue", _count)
    monkeypatch.setattr(mod, "open_local_hfss", _boom)
    v = mod.run_seat("wilkinson", machine="local", out_dir=tmp_path,
                     residue_check=False)
    assert v["verdict"] == "FAIL"
    assert calls["n"] == 0               # 前后查都跳过
    calls["n"] = 0
    v = mod.run_seat("wilkinson", machine="local", out_dir=tmp_path)
    assert v["verdict"] == "FAIL"
    assert calls["n"] >= 1               # 缺省：波前查在位（#265）


def test_open_remote_hfss_grpc_port_override(monkeypatch):
    """grpc_port 覆盖直达 Desktop/Hfss 构造端口与 info.remote.port；项目路径
    不含端口（per-seat 目录隔离与端口正交）；None=注册表端口（零变化）。"""
    pytest.importorskip("ansys.aedt.core")
    import ansys.aedt.core as aedt

    import rfauto.service.remote_service as rs

    calls: dict = {}

    class _FakeDesktop:
        def __init__(self, **kw):
            calls["desktop"] = kw

        def release_desktop(self, **kw):
            pass

    class _FakeHfss:
        def __init__(self, **kw):
            calls["hfss"] = kw

        def release_desktop(self, **kw):
            pass

    monkeypatch.setattr(rs, "remote_probe", lambda m: {
        "machines": [{"ports": {"ansys_license": {"open": True}}}]})
    monkeypatch.setattr(rs, "hfss_remote_session_config", lambda m: {
        "ok": True,
        "remote": {"remote_machine": m, "machine": "10.20.30.40",
                   "port": 50051, "project_root": "E:\\rfauto_remote",
                   "version": "2025.1"}})
    monkeypatch.setattr(aedt, "Desktop", _FakeDesktop)
    monkeypatch.setattr(aedt, "Hfss", _FakeHfss)
    monkeypatch.setattr(mod, "ensure_remote_project_dir",
                        lambda machine, project_dir: True)

    _d, _h, info = mod.open_remote_hfss({"template": "wilkinson"},
                                        "sim_host", grpc_port=50053)
    assert calls["desktop"]["port"] == 50053
    assert calls["hfss"]["port"] == 50053
    assert info["remote"]["port"] == 50053
    assert info["server_project"].endswith(
        "hfss_window_b2a\\wilkinson\\hfss_side\\project.aedt")
    calls.clear()
    _d, _h, info = mod.open_remote_hfss({"template": "wilkinson"},
                                        "sim_host")
    assert calls["desktop"]["port"] == 50051    # 缺省=注册表单值
    assert info["remote"]["port"] == 50051


def test_launch_remote_grpcsrv_per_port_vbs_and_task(monkeypatch):
    """per-port 拉起：vbs=launch_grpcsrv_<port>.vbs（并发不覆盖共享名）、内容
    含 -ng + <host>:<port>:InsecureMode；schtasks 唯一任务名含端口、/tr 走
    wscript.exe 静默宿主；端口开轮询通过 → ok 信封带 task_name。"""
    sent: list[str] = []
    uploads = _patch_registry_transport(monkeypatch, sent)
    base = "rfauto.infra.remote_machines"
    probe_state = {"n": 0}

    def _probe(host, port, timeout_s=3.0):
        probe_state["n"] += 1
        return (probe_state["n"] > 1, 1.0)   # 首查（预检）未占用，轮询即开

    monkeypatch.setattr(f"{base}.probe_port", _probe)
    env = mod.launch_remote_grpcsrv("sim_host", 50052, grpc_wait_s=5.0)
    assert env["ok"] is True and env["port"] == 50052
    assert env["task_name"].startswith("RFAuto\\hfss_window_50052_")
    (vbs_remote, vbs_bytes), = uploads
    assert vbs_remote.endswith("launch_grpcsrv_50052.vbs")
    text = vbs_bytes.decode("ascii")
    assert '"E:\\ANSYSINC\\ansysedt.exe"' in text
    assert "-ng -grpcsrv 10.20.30.40:50052:InsecureMode" in text
    create = next(c for c in sent if "schtasks /create" in c)
    run = next(c for c in sent if "schtasks /run" in c)
    assert "wscript.exe" in create
    assert "launch_grpcsrv_50052.vbs" in create
    assert env["task_name"] in create and env["task_name"] in run
    assert any("New-Item" in c for c in sent)          # 工作根预建


def test_launch_remote_grpcsrv_silent_vbs_semantics(monkeypatch):
    """静默语义钉（wf:silent-launch-p8 用户痛点=服务器桌面 cmd 黑框积累）：
    vbs 走 WScript.Shell.Run windowstyle 0（完全无窗）+异步 False；发射链
    （上传内容+schtasks 命令）零 .bat/零 cmd 宿主形态。"""
    sent: list[str] = []
    uploads = _patch_registry_transport(monkeypatch, sent)
    base = "rfauto.infra.remote_machines"
    probe_state = {"n": 0}

    def _probe(host, port, timeout_s=3.0):
        probe_state["n"] += 1
        return (probe_state["n"] > 1, 1.0)   # 首查（预检）未占用，轮询即开

    monkeypatch.setattr(f"{base}.probe_port", _probe)
    env = mod.launch_remote_grpcsrv("sim_host", 50051, grpc_wait_s=5.0)
    assert env["ok"] is True
    (_vbs_remote, vbs_bytes), = uploads
    text = vbs_bytes.decode("ascii")
    # windowstyle 0=完全无窗、False=异步不等待（单行 Run 调用收尾）
    assert text.startswith('CreateObject("WScript.Shell").Run "')
    assert text.rstrip("\r\n").endswith(', 0, False')
    # 旧 bat 形态零残留：无 cmd/start/bat 宿主痕迹
    for banned in ("cmd.exe", ".bat", "start ", "@echo off"):
        assert banned not in text
    create = next(c for c in sent if "schtasks /create" in c)
    assert "wscript.exe" in create                     # GUI 宿主无控制台
    assert ".bat" not in create and "cmd.exe" not in create
    assert not any("cmd.exe" in c for c in sent)       # 发射链全命令零 cmd 宿主


def test_launch_remote_grpcsrv_port_busy_fail_closed(monkeypatch):
    """端口已被占（疑残留实例）：fail-closed 不代杀（#265），不触发 schtasks
    任何写面。"""
    sent: list[str] = []
    _patch_registry_transport(monkeypatch, sent)
    monkeypatch.setattr("rfauto.infra.remote_machines.probe_port",
                        lambda host, port, timeout_s=3.0: (True, 1.0))
    env = mod.launch_remote_grpcsrv("sim_host", 50051)
    assert env["ok"] is False
    assert "已有监听" in env["reason"] and "不代杀" in env["reason"]
    assert not any("schtasks" in c for c in sent)


def test_launch_remote_grpcsrv_missing_exe_and_ssh_down(monkeypatch):
    """未登记 ansysedt_exe / SSH 面故障：失败信封（不抛），best-effort #105。"""
    import types

    sent: list[str] = []
    cfg = types.SimpleNamespace(
        name="sim_host", host="h", hfss_ansysedt_exe="",
        hfss_project_root="E:/rfauto_remote")
    uploads = _patch_registry_transport(monkeypatch, sent, cfg=cfg)
    monkeypatch.setattr("rfauto.infra.remote_machines.probe_port",
                        lambda host, port, timeout_s=3.0: (False, 1.0))
    env = mod.launch_remote_grpcsrv("sim_host", 50051)
    assert env["ok"] is False and "ansysedt_exe" in env["reason"]
    assert uploads == [] and not any("schtasks" in c for c in sent)

    class _TDown:
        def __init__(self, c):
            pass

        def connect(self):
            raise OSError("ssh down")

        def close(self):
            pass

    base = "rfauto.infra.remote_machines"
    monkeypatch.setattr(f"{base}.SshTransport", _TDown)
    env = mod.launch_remote_grpcsrv("sim_host", 50051)
    assert env["ok"] is False and "OSError" in env["reason"]


def test_cleanup_remote_grpcsrv_fingerprint_no_mutual_kill(monkeypatch):
    """清理端口指纹钉：多实例（50051/50052）+他人 GUI 实例并存时，逐席清理
    只杀本席 ":<port>:" 指纹实例与只删本席任务——多实例天然不互杀。"""
    query_out = "\n".join([
        "111|E:\\x\\ansysedt.exe -grpcsrv 10.20.30.40:50051:InsecureMode",
        "222|E:\\x\\ansysedt.exe -grpcsrv 10.20.30.40:50052:InsecureMode",
        "333|E:\\x\\ansysedt.exe",                      # 他人 GUI 无 grpcsrv
        "444|E:\\x\\ansysedt.exe -grpcsrv host:60000:InsecureMode",
    ])
    sent: list[str] = []
    _patch_registry_transport(monkeypatch, sent, query_output=query_out)
    task = "RFAuto\\hfss_window_50051_ab12cd34"
    env = mod.cleanup_remote_grpcsrv("sim_host", 50051, task_name=task)
    assert env["ok"] is True and env["killed_pids"] == ["111"]
    kill = next(c for c in sent if c.startswith("taskkill"))
    assert "/PID 111" in kill
    assert "/PID 222" not in kill and "/PID 333" not in kill
    assert "/PID 444" not in kill
    delete = next(c for c in sent if "schtasks /delete" in c)
    assert task in delete
    # 反向：50052 席只杀 222（波次复用端口逐席清理语义）
    sent.clear()
    env = mod.cleanup_remote_grpcsrv("sim_host", 50052)
    assert env["killed_pids"] == ["222"]
    kill = next(c for c in sent if c.startswith("taskkill"))
    assert "/PID 222" in kill and "/PID 111" not in kill
    assert not any("schtasks /delete" in c for c in sent)  # 无任务名不删


def test_cleanup_remote_grpcsrv_no_match_and_failure(monkeypatch):
    """无匹配=0 杀如实上报（ok 信封）；SSH 面故障=失败信封不抛（#105）。"""
    sent: list[str] = []
    _patch_registry_transport(monkeypatch, sent, query_output="")
    env = mod.cleanup_remote_grpcsrv("sim_host", 50051)
    assert env["ok"] is True and env["killed_pids"] == []
    assert not any(c.startswith("taskkill") for c in sent)

    class _TDown:
        def __init__(self, c):
            pass

        def connect(self):
            raise OSError("ssh down")

        def close(self):
            pass

    base = "rfauto.infra.remote_machines"
    monkeypatch.setattr(f"{base}.SshTransport", _TDown)
    env = mod.cleanup_remote_grpcsrv("sim_host", 50051)
    assert env["ok"] is False and "OSError" in env["reason"]


# ═══════════════ SOLVE_TIMEOUT_S env 口（wf:patch2x2-timeout-env）══════════════

def test_solve_timeout_default_3600_when_env_unset(monkeypatch):
    """缺省钉：env 未设=3600（判据冻结不放宽；import 链与消费点缺省逐字节不变）。"""
    monkeypatch.delenv("RFAUTO_HFSS_SOLVE_TIMEOUT_S", raising=False)
    assert mod._solve_timeout_from_env() == 3600.0
    fresh = _load()
    assert fresh.SOLVE_TIMEOUT_S == 3600.0
    assert fresh.solve_with_watchdog.__defaults__[-1] == 3600.0


def test_solve_timeout_env_override_7200(monkeypatch):
    """生效钉：env 设 7200=7200（rung3 结构性超 3600s 的恢复通道 a，env 显式才变）。"""
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_TIMEOUT_S", "7200")
    assert mod._solve_timeout_from_env() == 7200.0
    fresh = _load()
    assert fresh.SOLVE_TIMEOUT_S == 7200.0
    assert fresh.solve_with_watchdog.__defaults__[-1] == 7200.0


@pytest.mark.parametrize("bad", ["abc", "", "   ", "0", "-1", "nan", "inf"])
def test_solve_timeout_env_invalid_falls_back_to_3600(monkeypatch, bad):
    """回退钉：env 非法（非数字/空/非有限正数）=3600 回退不炸。"""
    monkeypatch.setenv("RFAUTO_HFSS_SOLVE_TIMEOUT_S", bad)
    assert mod._solve_timeout_from_env() == 3600.0


# ═══════════════ review-fix8（review-slice11 P1-1/P1-2/P2-1/P2-2/P2-3）回归钉 ═══════════════

_WINDOW = (1.5, 3.5)


def test_bw3db_main_lobe_selected_over_wider_edge_truncated_lobe():
    """P1-1 双 −3dB 段合成钉：主瓣口径选**含峰段**；更宽的窗沿截断上瓣
    （stepped HFSS rung3 实测 0.705 形态）不得因「最宽」被选中；主瓣触窗沿
    → truncated=True → bw=None（如实 UNKNOWN 不 DISAGREE，criteria §8 注记）。"""
    fg = np.linspace(1.5, 3.5, 401)
    s = np.zeros((401, 2, 2), dtype=complex)
    # 主瓣 [1.5,2.18]（含峰、触下窗沿）+ 上瓣 [2.795,3.5]（更宽、触上窗沿）
    s[:, 1, 0] = _stepped_s21(fg, [(1.5, 2.18, -0.2), (2.795, 3.5, -1.0)])
    det = mod._bw3db_detail(fg, mod._db(s[:, 1, 0]), _WINDOW)
    assert det["truncated"] is True and det["width"] is None
    assert det["reason"] == "edge_truncated"
    assert det["main_lobe"]["width"] == pytest.approx(0.68, abs=1e-9)
    assert [(sg["f_lo"], sg["f_hi"]) for sg in det["segments"]] == \
        [(1.5, 2.18), (2.795, 3.5)]
    m = mod.extract_metrics(fg * 1e9, s, mod.SEATS["stepped_impedance"], None)
    assert m["bw_3db_ghz"] is None          # 旧口径此处置 0.705（错瓣拾取）


def test_bw3db_main_lobe_non_truncated_returns_width():
    """P1-1：主瓣不触窗沿 → 返回主瓣宽（即使存在更宽的截断旁瓣——旁瓣=窗
    沿伪象不参选）；无穿越/全程 ≥−3dB → None 原语义不变。"""
    fg = np.linspace(1.5, 3.5, 401)
    s21 = _stepped_s21(fg, [(2.0, 2.4, -0.3), (2.8, 3.5, -1.0)])
    det = mod._bw3db_detail(fg, mod._db(s21), _WINDOW)
    assert det["truncated"] is False and det["reason"] == "main_lobe"
    assert det["width"] == pytest.approx(0.4, abs=1e-9)
    assert mod._bw3db(fg, mod._db(_stepped_s21(fg, [])), _WINDOW) is None
    assert mod._bw3db(fg, mod._db(_stepped_s21(fg, [(1.5, 3.5, -1.0)])),
                      _WINDOW) is None       # 全程 ≥−3dB（all_above）


def test_f_peak_3db_center_plateau_stable_vs_argmax_drift():
    """P1-2 平台化峰合成钉：argmax 随平台微扰在两沿间漂移（旧口径 0.612GHz
    级漂移→20% 级假分歧），−3dB 带心稳定不变；带触窗沿 censored=True 且
    带心以窗端点夹持；带内不触沿 → censored=False。"""
    seat = mod.SEATS["coupled_line"]
    fg = np.linspace(1.8, 3.0, 401)
    base = 10.0 ** (-9.16 / 20.0)
    plateau = (fg >= 2.388) & (fg <= 3.0)      # 触上窗沿（censored 形态）
    tilt = 0.01 * (fg - 2.694)
    centers, argmaxes = [], []
    for sign in (+1.0, -1.0):
        s = np.zeros((401, 3, 3), dtype=complex)
        s31 = np.full(401, 10.0 ** (-20.0 / 20.0))
        s31[plateau] = base * 10.0 ** (sign * tilt[plateau] / 20.0)
        s[:, 2, 0] = s31
        notes: list[str] = []
        m = mod.extract_metrics(fg * 1e9, s, seat, None, notes=notes)
        centers.append(m["f_peak_ghz"])
        argmaxes.append(float(fg[int(np.argmax(s31))]))
        assert notes and "censored" in notes[0]
    assert abs(argmaxes[0] - argmaxes[1]) > 0.6      # 旧 argmax 口径漂移量
    assert centers[0] == pytest.approx(centers[1])   # 带心稳定（#298）
    assert centers[0] == pytest.approx(0.5 * (2.388 + 3.0), abs=1e-9)
    # 不触沿形态：带心=数据段带心、无 censored 注记
    s = np.zeros((401, 3, 3), dtype=complex)
    s31 = np.full(401, 10.0 ** (-20.0 / 20.0))
    s31[(fg >= 2.2) & (fg <= 2.6)] = base
    s[:, 2, 0] = s31
    notes2: list[str] = []
    m2 = mod.extract_metrics(fg * 1e9, s, seat, None, notes=notes2)
    assert m2["f_peak_ghz"] == pytest.approx(2.4, abs=1e-9)
    assert notes2 == []


def test_coupled_f_peak_extractor_declares_band_center_kind():
    """P1-2 spec 钉：coupled f_peak 提取器 kind=s_db_max_f_center3db（#298
    带心口径），判据门值/窗不动（criteria §8 注记在案）。"""
    ex = next(e for e in mod.SEATS["coupled_line"]["extractors"]
              if e["metric"] == "f_peak_ghz")
    assert ex["kind"] == "s_db_max_f_center3db"
    assert tuple(mod.SEATS["coupled_line"]["window_ghz"]) == (1.8, 3.0)


def test_read_touchstone_rejects_im_zero_synthetic(tmp_path):
    """P2-1 防御钉：Im≡0（dry-run 合成链特征，synthetic_s 全实数）在
    reject_synthetic=True 拒读（防 hfss_side_dryrun 漏移 stub 被当真机 rung
    消费——patch_2x2 rung3.s1p 逐字节实证），False/缺省放行（dry 链回读）；
    含数值虚部数据两态都过。"""
    import skrf

    freq = np.linspace(1.0e9, 2.0e9, 11)
    s_real = np.zeros((11, 1, 1), dtype=complex)
    s_real[:, 0, 0] = 0.5
    p = tmp_path / "rung3.s1p"
    skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="Hz"),
                 s=s_real).write_touchstone(str(p))
    assert mod.touchstone_is_synthetic(p) is True
    with pytest.raises(ValueError, match="Im≡0"):
        mod.read_touchstone(p, reject_synthetic=True)
    _f2, s2 = mod.read_touchstone(p)             # 缺省放行（dry-run 链回读）
    assert s2.shape == (11, 1, 1) and float(np.max(np.abs(s2.imag))) == 0.0
    s_cplx = s_real + 1e-3j
    p3 = tmp_path / "rung_real.s1p"
    skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="Hz"),
                 s=s_cplx).write_touchstone(str(p3))
    assert mod.touchstone_is_synthetic(p3) is False
    _f4, s4 = mod.read_touchstone(p3, reject_synthetic=True)
    assert float(np.max(np.abs(s4.imag))) == pytest.approx(1e-3)


def test_parse_verdict_lines_refuses_dryrun_prefix(tmp_path):
    """P2-3 判读链防御钉：``[dryrun]`` 前缀 verdict 行（fix8 起写入即带；
    存量干跑假行同形拒收——gysel 假 DISAGREE 与真态相反实证）一律不产出；
    真跑行按文件序解析；缺文件零异常空表。"""
    log = tmp_path / "progress.log"
    log.write_text(
        "[05:31:48] [dryrun] verdict=DISAGREE status=DONE wall=0.5s\n"
        "[11:30:27] verdict=AGREE_JUDGE status=DONE wall=991.2s\n"
        "[05:42:32] [dryrun] verdict=DISAGREE status=DONE wall=0.5s\n",
        encoding="utf-8")
    assert mod.parse_verdict_lines(log) == [
        {"time": "11:30:27", "verdict": "AGREE_JUDGE", "status": "DONE",
         "wall_s": 991.2}]
    assert mod.parse_verdict_lines(tmp_path / "missing.log") == []


def test_run_seat_dry_progress_lines_carry_dryrun_prefix(tmp_path):
    """P2-3 端到端钉：dry-run 链落 progress.log 的 verdict 行带 [dryrun]
    前缀（写入口防御），parse_verdict_lines 对其零产出——干跑写错目录
    （hfss_side_dryrun 漏移形态）也不可再被 grep 消费者误取。"""
    v = mod.run_seat("wilkinson", machine="local", out_dir=tmp_path,
                     dry_run=True)
    assert v["status"] == "DONE"
    log = (tmp_path / "progress.log").read_text(encoding="utf-8")
    vlines = [ln for ln in log.splitlines() if "verdict=" in ln]
    assert vlines and all("[dryrun]" in ln for ln in vlines)
    assert mod.parse_verdict_lines(tmp_path / "progress.log") == []


def test_marchand_build_records_lumped_ports():
    """P2-2 结构化记账钉：marchand P2/P3 140Ω 集总口进 build.lumped_ports
    （name/阻抗/XZ 薄片落位/contact 单源现抄 layout）——判读所依赖的端口
    口径不得只存自由文本注记（对照 gysel Rload 全账先例）。"""
    pytest.importorskip("ansys.aedt.core")
    ctx = mod.seat_context("marchand_balun")
    h = _FakeHfss()
    build = mod.build_seat_geometry(h, "marchand_balun", ctx)
    lp = build["lumped_ports"]
    assert [p["name"] for p in lp] == ["P2", "P3"]
    assert all(p["impedance_ohm"] == 140.0 for p in lp)
    assert all(p["kind"] == "port" and p["axis"] == "y"
               and len(p["sheet_x0y0x1y1_mm"]) == 4
               and len(p["contact_point_xy_mm"]) == 2 for p in lp)
    lay = mod.seat_layout("marchand_balun", ctx)
    src = {ln["name"]: ln for ln in lay["lumped"] if ln.get("kind") == "port"}
    for p in lp:                                 # 账=建模实参（单源逐位一致）
        assert p["sheet_x0y0x1y1_mm"] == [float(x)
                                          for x in src[p["name"]]["sheet"]]
        assert p["contact_point_xy_mm"] == [float(x) for x in
                                            src[p["name"]]["contact_point"]]
    assert [k["impedance"] for k in h.modeler.lumped_ports] == [140.0, 140.0]


# ═══════════════ review-fix9（review-slice13 P1-1/P2-1/P3-A）回归钉 ═══════════════

def test_extract_metrics_censored_structured_fields():
    """P1-1 结构化钉：bw 主瓣触窗沿截断 → ``bw_3db_ghz_censored=True`` 与
    ``bw_3db_ghz_detail`` 明细块**与值同层**落（P3-A：明细进 live 提取出口，
    不再只存自由文本）；f_peak 带心触窗沿 → ``f_peak_ghz_censored=True``。
    不触沿形态 censored 键**不存在**（非 False 占位），notes 出口并行留证。"""
    fg = np.linspace(1.5, 3.5, 401)
    seat_bw = mod.SEATS["stepped_impedance"]
    s = np.zeros((401, 2, 2), dtype=complex)
    s[:, 1, 0] = _stepped_s21(fg, [(1.5, 2.18, -0.2), (2.795, 3.5, -1.0)])
    notes: list[str] = []
    m = mod.extract_metrics(fg * 1e9, s, seat_bw, None, notes=notes)
    assert m["bw_3db_ghz"] is None
    assert m["bw_3db_ghz_censored"] is True
    det = m["bw_3db_ghz_detail"]
    assert det["truncated"] is True and det["reason"] == "edge_truncated"
    assert det["main_lobe"]["width"] == pytest.approx(0.68, abs=1e-9)
    assert notes and "censored" in notes[0]      # notes 并行发射（bw 分支新出口）
    # 不触沿：带宽有值、censored 键不存在、明细 reason=main_lobe
    s2 = np.zeros((401, 2, 2), dtype=complex)
    s2[:, 1, 0] = _stepped_s21(fg, [(2.0, 2.4, -0.3)])
    notes2: list[str] = []
    m2 = mod.extract_metrics(fg * 1e9, s2, seat_bw, None, notes=notes2)
    assert m2["bw_3db_ghz"] == pytest.approx(0.4, abs=1e-9)
    assert "bw_3db_ghz_censored" not in m2
    assert m2["bw_3db_ghz_detail"]["reason"] == "main_lobe"
    assert notes2 == []
    # f_peak 带心 censored（coupled 触上窗沿形态，#298 带心口径）
    seat_c = mod.SEATS["coupled_line"]
    fgc = np.linspace(1.8, 3.0, 401)
    sc = np.zeros((401, 3, 3), dtype=complex)
    s31 = np.full(401, 10.0 ** (-20.0 / 20.0))
    s31[fgc >= 2.388] = 10.0 ** (-9.16 / 20.0)
    sc[:, 2, 0] = s31
    notes3: list[str] = []
    m3 = mod.extract_metrics(fgc * 1e9, sc, seat_c, None, notes=notes3)
    assert m3["f_peak_ghz"] == pytest.approx(0.5 * (2.388 + 3.0), abs=1e-9)
    assert m3["f_peak_ghz_censored"] is True
    assert notes3 and "censored" in notes3[0]


def test_oe_resolve_paths_carry_notes_and_censored(tmp_path, monkeypatch):
    """P1-1③ OE 侧出口钉：sparams_csv 路径（resolve_oe_refs 全链，tmp REPO
    合成 csv）values 携带 ``f_peak_ghz_censored=True`` 且 notes 带 censored
    注记；touchstone 路径（_resolve_oe_touchstone 直调合成 s3p）notes 同样
    透传——两条现算路径双注记（此前 OE 侧零出口，双侧 censored 只记 HFSS）。"""
    oe_dir = (tmp_path / "runs/hfss_window_b2a/coupled_line"
              / "oe_nominal_wideband")
    oe_dir.mkdir(parents=True)
    _coupled_censored_sparams_csv(oe_dir / "sparams.csv")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    refs = mod.resolve_oe_refs("coupled_line")
    assert refs["source"].endswith("sparams.csv")
    assert refs["values"]["f_peak_ghz"] == pytest.approx(2.694, abs=1e-9)
    assert refs["values"]["f_peak_ghz_censored"] is True
    assert refs["notes"] and "censored" in refs["notes"][0]
    # touchstone 路径：合成 3 端口 s3p 直调（#248 扩展名=rank，3 端口用 .s3p）
    import skrf

    fg = np.linspace(1.8, 3.0, 41)
    s = np.zeros((41, 3, 3), dtype=complex)
    s31 = np.where(fg >= 2.388, 10.0 ** (-9.16 / 20.0), 10.0 ** (-20.0 / 20.0))
    s[:, 2, 0] = s31 + 1e-6j
    s[:, 1, 0] = 10.0 ** (-0.45 / 20.0) + 1e-6j
    s3p = tmp_path / "oe_ref.s3p"
    skrf.Network(frequency=skrf.Frequency.from_f(fg * 1e9, unit="Hz"),
                 s=s).write_touchstone(str(s3p))
    seat_t = {"template": "coupled_line", "window_ghz": (1.8, 3.0),
              "f0_ghz": 2.4, "n_ports": 3,
              "extractors": ({"metric": "f_peak_ghz",
                              "kind": "s_db_max_f_center3db", "ij": (2, 0),
                              "band": "window"},),
              "oe": {"candidates": ["oe_ref.s3p"]}}
    notes_t: list[str] = []
    vals_t, src_t, _mask = mod._resolve_oe_touchstone(seat_t, notes=notes_t)
    assert src_t.endswith("oe_ref.s3p")
    assert vals_t["f_peak_ghz_censored"] is True
    assert notes_t and "censored" in notes_t[0]


def test_run_seat_dry_censored_structured_both_sides(tmp_path, monkeypatch):
    """P1-1④ 端到端钉（合成 S 参数双引擎 censored 场景）：HFSS 侧（合成链
    patched synthetic_s）与 OE 侧（tmp REPO 合成 sparams.csv 同形态）双侧
    censored → per_metric f_peak 行 ``censored`` 结构化字段**双侧在位** +
    implementation_notes 双注记；censored 只加标记不改四态（判据冻结 #122，
    定量引用禁令由字段+注记承载）；verdict.json 落盘保真。"""
    oe_dir = (tmp_path / "runs/hfss_window_b2a/coupled_line"
              / "oe_nominal_wideband")
    oe_dir.mkdir(parents=True)
    _coupled_censored_sparams_csv(oe_dir / "sparams.csv")
    monkeypatch.setattr(mod, "REPO", tmp_path)

    def _synth(seat_name, freq_hz, variant="agree"):
        fg = np.asarray(freq_hz, dtype=float) / 1e9
        s = np.zeros((len(fg), 3, 3), dtype=complex)
        s31 = np.where(fg >= 2.388, 10.0 ** (-9.16 / 20.0),
                       10.0 ** (-20.0 / 20.0))
        s[:, 2, 0] = s31 + 1e-7j
        s[:, 1, 0] = 10.0 ** (-0.45 / 20.0) + 1e-7j
        return s

    monkeypatch.setattr(mod, "synthetic_s", _synth)
    out = tmp_path / "coupled"
    v = mod.run_seat("coupled_line", machine="local", out_dir=out,
                     dry_run=True)
    assert v["status"] == "DONE"
    assert v["hfss_metrics"]["f_peak_ghz_censored"] is True
    assert v["oe"]["values"]["f_peak_ghz_censored"] is True
    row = next(r for r in v["per_metric"] if r["metric"] == "f_peak_ghz")
    assert row["censored"] == {"hfss": True, "oe": True}
    assert row["state"] == "AGREE_JUDGE"     # censored 不改判读态（门冻结）
    cens_notes = [n for n in v["implementation_notes"] if "censored" in n]
    assert len(cens_notes) >= 2              # HFSS chosen rung + OE 双注记
    saved = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    row_s = next(r for r in saved["per_metric"] if r["metric"] == "f_peak_ghz")
    assert row_s["censored"] == {"hfss": True, "oe": True}


def test_run_seat_dry_bw_detail_lands_in_verdict(tmp_path, monkeypatch):
    """P3-A/P2补 端到端钉：bw 截断档 verdict 增 ``bw_detail`` 结构化块
    （truncated/reason/main_lobe/segments 逐字段，docstring「供 verdict 留证」
    兑现）+ per_metric bw 行 censored（HFSS 侧；空 REPO 强制 OE 闭式回退无
    bw 值 → oe 侧 False 如实，环境无关）。"""
    monkeypatch.setattr(mod, "REPO", tmp_path)   # 空 tmp → OE 闭式回退

    def _synth(seat_name, freq_hz, variant="agree"):
        fg = np.asarray(freq_hz, dtype=float) / 1e9
        s = np.zeros((len(fg), 2, 2), dtype=complex)
        s21 = np.full(len(fg), 10.0 ** (-6.0 / 20.0))
        s21[(fg >= 1.5) & (fg <= 2.18)] = 10.0 ** (-0.2 / 20.0)
        s[:, 1, 0] = s21 + 1e-7j
        return s

    monkeypatch.setattr(mod, "synthetic_s", _synth)
    v = mod.run_seat("stepped_impedance", machine="local",
                     out_dir=tmp_path / "st", dry_run=True)
    assert v["status"] == "DONE"
    det = v["bw_detail"]
    assert det["truncated"] is True and det["reason"] == "edge_truncated"
    assert det["main_lobe"]["width"] == pytest.approx(0.68, abs=1e-9)
    assert [(sg["f_lo"], sg["f_hi"]) for sg in det["segments"]] == [(1.5, 2.18)]
    assert v["hfss_metrics"]["bw_3db_ghz"] is None
    row = next(r for r in v["per_metric"] if r["metric"] == "bw_3db_ghz")
    assert row["censored"] == {"hfss": True, "oe": False}


def test_parse_verdict_lines_rejects_legacy_prefixless_fake_wall(tmp_path):
    """P2-1 存量假行防御钉：无 ``[dryrun]`` 前缀的 legacy 假 verdict 行
    （4 个 hfss_side_dryrun 目录 wall 2.0s 级形态）按 ``wall_s<60s`` 特征
    拒收（dry 合成链 0.5–2s vs 真机 485–6065s，60s 安全带）；真跑 wall
    （485s）放行；边界 59.9 拒/60.0 收；前缀防御叠加不变；真跑快速失败
    attempt（abort FAIL wall=2.1s）同被拒——其执行证据走 verdict.json，
    不经判读解析器（docstring 如实声明）。"""
    log = tmp_path / "progress.log"
    log.write_text(
        "[05:31:48] verdict=DISAGREE status=DONE wall=2.0s\n"       # legacy 假行
        "[11:30:27] verdict=AGREE_JUDGE status=DONE wall=485.0s\n"  # 真跑行
        "[05:31:49] verdict=AGREE_OPENEMS status=DONE wall=59.9s\n"  # 边界下
        "[05:31:50] verdict=AGREE_HFSS status=DONE wall=60.0s\n"     # 边界上
        "[13:08:05] verdict=FAIL status=FAIL(执行异常) wall=2.1s\n"  # 快速失败
        "[05:31:51] [dryrun] verdict=DISAGREE status=DONE wall=0.5s\n",
        encoding="utf-8")
    assert mod.parse_verdict_lines(log) == [
        {"time": "11:30:27", "verdict": "AGREE_JUDGE", "status": "DONE",
         "wall_s": 485.0},
        {"time": "05:31:50", "verdict": "AGREE_HFSS", "status": "DONE",
         "wall_s": 60.0}]


# ═══════════════ S2 审计 lesson 回写 + marchand 端口形态发射面（2026-09-29 T6）══════════════
# 审计：docs/audit/hfss_window_disagree_audit_20260929.md §3/§5/§8.3。
# 纪律：机制面新增，已落档 verdict/锚值零触碰（判据冻结 #122）。

def test_lesson1_band_symmetry_spec_integrity():
    """lesson-1 规格钉：8 席判据全过同带门。外部常量/字段型 OE 参考
    （marchand=constants、gysel=verdict_fields）必须显式声明 oe.band_ghz
    且与带统计量提取器显式带逐位一致；曲线型 OE（sparams_csv/touchstone）
    经同一提取器同带提取（构造性同带）豁免。"""
    for name in _ALL_SEATS:
        assert mod.band_symmetry_violations(mod.SEATS[name]) == [], name
    assert tuple(mod.SEATS["marchand_balun"]["oe"]["band_ghz"]) == (2.25, 2.75)
    assert tuple(mod.SEATS["gysel"]["oe"]["band_ghz"]) == (2.25, 2.75)


def test_lesson1_band_symmetry_negative_pins():
    """lesson-1 负例钉：外部常量型 OE 的带统计量门——①band=window 不可核验/
    ②band_ghz 未声明/③声明与提取器带不一致，三类违例逐一被护栏抓获；
    曲线型源豁免；未被门引用的带统计量提取器不参与强制（信息项自由）。"""
    ex = {"metric": "s21_band_min_db", "kind": "s_db_band_min",
          "ij": (1, 0), "band": (2.25, 2.75)}
    gate = {"metric": "s21_band_min_db", "gate": 1.0, "gate_kind": "db_diff",
            "key": True}
    s1 = {"extractors": [{**ex, "band": "window"}], "gates": [gate],
          "oe": {"source": "constants", "band_ghz": (2.25, 2.75)}}
    v1 = mod.band_symmetry_violations(s1)
    assert len(v1) == 1 and "window" in v1[0]
    s2 = {"extractors": [ex], "gates": [gate], "oe": {"source": "constants"}}
    v2 = mod.band_symmetry_violations(s2)
    assert len(v2) == 1 and "band_ghz" in v2[0]
    s3 = {"extractors": [ex], "gates": [gate],
          "oe": {"source": "constants", "band_ghz": (1.8, 3.6)}}
    v3 = mod.band_symmetry_violations(s3)
    assert len(v3) == 1 and "不一致" in v3[0]
    s4 = {"extractors": [ex], "gates": [gate], "oe": {"source": "sparams_csv"}}
    assert mod.band_symmetry_violations(s4) == []
    s5 = {"extractors": [ex], "gates": [], "oe": {"source": "constants"}}
    assert mod.band_symmetry_violations(s5) == []


def test_lesson1_band_symmetry_runseat_fail_closed(tmp_path, monkeypatch):
    """lesson-1 端到端负例：带窗不对称判据（OE band_ghz 与提取器带不一致）
    → run_seat 起跑前 fail-closed FAIL、不触会话（判据面错误=执行 FAIL，
    不发射，#122）。"""
    base = mod.SEATS["marchand_balun"]
    bad = {**base, "oe": {**base["oe"], "band_ghz": (1.8, 3.6)}}
    monkeypatch.setitem(mod.SEATS, "marchand_balun", bad)
    launched: list = []

    def _no_launch(seat, project_path):
        launched.append(project_path)
        raise AssertionError("违例判据不得起跑")

    monkeypatch.setattr(mod, "open_local_hfss", _no_launch)
    v = mod.run_seat("marchand_balun", machine="local", out_dir=tmp_path,
                     dry_run=False)
    assert v["verdict"] == "FAIL"
    assert "lesson-1" in v["error"]
    assert launched == []


def test_lesson2_weak_feature_downgrade_both_directions(tmp_path, monkeypatch):
    """lesson-2 双向钉：①病态背景（带内最优匹配 −1.28dB > −3dB，本窗
    marchand HFSS 形态）f_null 压线超门 → 降级 info——行照实记 DISAGREE+
    weak_feature.downgraded、总态不被翻（其余门 AGREE → AGREE_JUDGE）、
    注记/md 标记在位；②健康背景（真实深谷 −30dB）同幅失配 → DISAGREE
    照常强制（总态 DISAGREE）。判据门值/窗冻结不变。"""
    fg = np.linspace(1.8, 3.6, 401)
    seat_m = mod.SEATS["marchand_balun"]
    gate_fn = next(g for g in seat_m["gates"] if g["metric"] == "f_null_ghz")
    assert gate_fn["weak_feature"] is True and gate_fn["key"] is True
    assert gate_fn["gate"] == 10.0            # 门值冻结不变（lesson 只降级不改门）
    # OE 常量改自洽集（幅度三量与平坦等幅合成一致，隔离出 f_null 单门差异；
    # 归档 SEATS 面测试后自动还原）
    monkeypatch.setitem(seat_m["oe"], "constants",
                        {"f_null_ghz": 3.272, "s21_band_min_db": -6.44,
                         "s31_band_min_db": -6.44, "imbalance_band_max_db": 0.0})

    def _marchand_s(depth_db: float):
        s = np.zeros((len(fg), 3, 3), dtype=complex)
        base = 10.0 ** (-1.0 / 20.0)
        dip = 10.0 ** (depth_db / 20.0)
        s[:, 0, 0] = base - (base - dip) * np.exp(-((fg - 2.916) / 0.08) ** 2)
        bal = 10.0 ** (-6.44 / 20.0)
        s[:, 1, 0] = bal
        s[:, 2, 0] = bal                      # 等幅 → 幅度三门全 AGREE
        return s

    outs = {}
    for tag, depth in (("pathological", -1.28), ("healthy", -30.0)):
        monkeypatch.setattr(mod, "synthetic_s",
                            lambda seat_name, freq_hz, variant="agree",
                            _d=depth: _marchand_s(_d))
        outs[tag] = mod.run_seat("marchand_balun", machine="local",
                                 out_dir=tmp_path / tag, dry_run=True)

    vp = outs["pathological"]
    assert vp["status"] == "DONE"
    row = next(r for r in vp["per_metric"] if r["metric"] == "f_null_ghz")
    assert row["state"] == "DISAGREE"                      # 观测照实记录
    wf = row["weak_feature"]
    assert wf["downgraded"] is True and wf["pathological"] is True
    assert wf["background_db"] == pytest.approx(-1.28, abs=0.05)
    assert wf["floor_db"] == mod.WEAK_FEATURE_BG_FLOOR_DB == -3.0
    assert vp["verdict"] != "DISAGREE"                     # 不翻总态
    assert vp["verdict"] == "AGREE_JUDGE"                  # 其余门全 AGREE
    notes = " ".join(vp["implementation_notes"])
    assert "lesson-2" in notes and "降级 info" in notes
    md = (tmp_path / "pathological" / "verdict.md").read_text(encoding="utf-8")
    assert "→info(weak)" in md

    vh = outs["healthy"]
    assert vh["status"] == "DONE"
    row_h = next(r for r in vh["per_metric"] if r["metric"] == "f_null_ghz")
    assert row_h["state"] == "DISAGREE"
    assert row_h["weak_feature"]["downgraded"] is False    # 健康背景不降级
    assert row_h["weak_feature"]["background_db"] == pytest.approx(-30.0,
                                                                   abs=0.1)
    assert vh["verdict"] == "DISAGREE"                     # 门照常强制


def test_lesson3_valley_map_and_compare_patch2x2():
    """lesson-3 形态钉（审计 §5.2 patch_2x2 谷位图复现）：两引擎 4 谷位置
    一致 ≤0.3%、argmin 型 f_min 互差 ~14.3% 实为谷 1/谷 2 深度排序翻转
    （depth_order_agrees=False）；<3dB 纹波谷不计（prominence 门）；
    f_min_ghz_valleys 结构化出口与值同层。"""
    fg = np.linspace(4.64, 6.96, 1161)

    def _curve(valleys, ripple=None):
        base = 10.0 ** (-1.5 / 20.0)
        y = np.full(len(fg), base)
        feats = list(valleys) + ([ripple] if ripple else [])
        for f0, depth in feats:
            d = 10.0 ** (depth / 20.0)
            shape = base - (base - d) * np.exp(-((fg - f0) / 0.05) ** 2)
            y = np.minimum(y, shape)
        s = np.zeros((len(fg), 1, 1), dtype=complex)
        s[:, 0, 0] = y
        return s

    hfss_v = [(4.976, -10.1), (5.690, -27.6), (5.928, -9.3), (6.722, -5.2)]
    oe_v = [(4.976, -17.8), (5.672, -15.0), (5.916, -11.3), (6.728, -5.1)]
    seat_p = mod.SEATS["patch_array_2x2"]
    m_h = mod.extract_metrics(fg * 1e9, _curve(hfss_v, ripple=(5.2, -2.2)),
                              seat_p, None)
    m_o = mod.extract_metrics(fg * 1e9, _curve(oe_v), seat_p, None)
    assert m_h["f_min_ghz"] == pytest.approx(5.690, abs=0.01)   # HFSS 最深=谷2
    assert m_o["f_min_ghz"] == pytest.approx(4.976, abs=0.01)   # OE 最深=谷1
    fmin_diff_pct = (abs(m_h["f_min_ghz"] - m_o["f_min_ghz"])
                     / m_o["f_min_ghz"] * 100.0)
    assert fmin_diff_pct == pytest.approx(14.3, abs=0.5)        # 审计 14.345%
    vm_h = m_h["f_min_ghz_valleys"]
    vm_o = m_o["f_min_ghz_valleys"]
    assert vm_h["n_valleys"] == 4 and vm_o["n_valleys"] == 4    # 纹波谷不计
    cmp_ = mod.valley_map_compare(vm_h, vm_o)
    assert cmp_["max_pos_diff_pct"] <= 0.35                     # 谷位 ≤0.3% 级
    assert cmp_["depth_order_agrees"] is False                  # 深度排序翻转
    assert cmp_["argmin_same"] is False                         # 单值 f_min 分歧
    assert cmp_["pairs"][0]["depth_diff_db"] == pytest.approx(7.7, abs=0.3)
    assert cmp_["pairs"][1]["depth_diff_db"] == pytest.approx(-12.6, abs=0.3)


def test_marchand_port_form_dispatch_faces():
    """S2 决策 2 发射面纯函数：形态解析（缺省/显式/非法/越席）、判据分派
    （wave2mode=P1 反射侧两门+弱特征标记；SEATS 冻结面零触碰）、Σ模数、
    wave2mode 产物目录隔离。"""
    assert mod.SEATS["marchand_balun"]["port_form"] == "lumped140"
    assert mod.resolve_marchand_port_form("marchand_balun") == "lumped140"
    assert mod.resolve_marchand_port_form("marchand_balun",
                                          "wave2mode") == "wave2mode"
    with pytest.raises(ValueError):
        mod.resolve_marchand_port_form("marchand_balun", "bogus")
    with pytest.raises(ValueError):
        mod.resolve_marchand_port_form("wilkinson", "wave2mode")
    # 幂等：已解析值回呼安全（内部分派面）
    assert mod.resolve_marchand_port_form("stepped_impedance",
                                          "lumped140") == "lumped140"
    assert mod.criteria_for_run("marchand_balun") is mod.SEATS["marchand_balun"]
    w2m = mod.criteria_for_run("marchand_balun", "wave2mode")
    assert w2m is not mod.SEATS["marchand_balun"]
    assert {g["metric"] for g in w2m["gates"]} == {"f_null_ghz", "s11_min_db"}
    gf = next(g for g in w2m["gates"] if g["metric"] == "f_null_ghz")
    assert gf["key"] is True and gf["weak_feature"] is True
    assert gf["gate"] == 10.0
    gs = next(g for g in w2m["gates"] if g["metric"] == "s11_min_db")
    assert gs["key"] is False
    assert {e["metric"] for e in w2m["extractors"]} == {"f_null_ghz",
                                                        "s11_min_db"}
    assert mod.SEATS["marchand_balun"]["gates"][0]["metric"] == "f_null_ghz"
    assert len(mod.SEATS["marchand_balun"]["gates"]) == 5      # 冻结面零触碰
    assert mod.seat_mode_count("marchand_balun") == 3
    assert mod.seat_mode_count("marchand_balun", "wave2mode") == 5  # 1+2+2
    assert mod.seat_mode_count("stepped_impedance") == 2
    d0 = mod.default_out_dir("marchand_balun", "local")
    d1 = mod.default_out_dir("marchand_balun", "local", port_form="wave2mode")
    assert d0.name == "hfss_side" and d1.name == "hfss_side_wave2mode"


def test_marchand_wave2mode_layout_and_audit():
    """wave2mode 几何面：PA/PB 2 模大截面波端口（横向 ±12mm/全高、贴 ±y
    域界）、馈线延伸至域界（#174 反例规避）、140Ω 集总口移除、断链/触点
    审计全过；lumped140 缺省布局形态零变化（P1 单波端口+P2/P3 集总）。"""
    ctx_w = mod.seat_context("marchand_balun", port_form="wave2mode")
    assert ctx_w["port_form"] == "wave2mode"
    lay = mod.seat_layout("marchand_balun", ctx_w)
    assert lay["audit"]["ok"], lay["audit"]
    assert lay["audit"]["floating_components"] == []
    names = [p["name"] for p in lay["ports"]]
    assert names == ["P1", "PA", "PB"]
    pa, pb = lay["ports"][1], lay["ports"][2]
    assert pa["modes"] == 2 and pb["modes"] == 2
    assert pa["w"] == pytest.approx(2.0 * mod.MARCHAND_W2M_LATERAL_MM)
    assert pa["h"] == pytest.approx(mod.MARCHAND_AIR_TOP_MM)   # 全高（域顶）
    assert pa["edge_y"] == pytest.approx(lay["sub_half_y"])    # 贴 +y 域界
    assert pb["edge_y"] == pytest.approx(-lay["sub_half_y"])
    assert not [ln for ln in lay.get("lumped", [])
                if ln.get("kind") == "port"]                   # 集总口移除
    fa, fb = lay["rects"]["FeedA"], lay["rects"]["FeedB"]
    assert fa[3] == pytest.approx(lay["sub_half_y"])           # 馈线到域界
    assert fb[1] == pytest.approx(-lay["sub_half_y"])
    # 缺省形态零变化
    ctx0 = mod.seat_context("marchand_balun")
    assert ctx0["port_form"] == "lumped140"
    lay0 = mod.seat_layout("marchand_balun", ctx0)
    assert [p["name"] for p in lay0["ports"]] == ["P1"]
    assert [ln["name"] for ln in lay0["lumped"]] == ["P2", "P3"]
    assert all(ln["r_ohm"] == 140.0 for ln in lay0["lumped"])
    assert lay0["audit"]["ok"]


def test_marchand_wave2mode_build_fake_records_modes2():
    """wave2mode 建模面（fake 可执行面，家法同 test_build_seat_geometry_
    fake_executable_face）：P1 单模 + PA/PB modes=2、多模积分线显式
    [[S,S],[E,E]] 格式（#308，两模同用地→导带竖直路径）、零集总口、
    PA 薄片横向 ±12mm/z 0→域顶 bbox 自审过账。"""
    pytest.importorskip("ansys.aedt.core")
    ctx = mod.seat_context("marchand_balun", port_form="wave2mode")
    h = _FakeHfss()
    build = mod.build_seat_geometry(h, "marchand_balun", ctx)
    m = h.modeler
    assert [p["name"] for p in m.wave_ports] == ["P1", "PA", "PB"]
    p1, pa, pb = m.wave_ports
    assert p1["modes"] == 1 and pa["modes"] == 2 and pb["modes"] == 2
    for pt in (pa, pb):
        il = pt["integration_line"]
        assert len(il) == 2                                    # [起点列表, 终点列表]
        assert il[0] == [il[0][0], il[0][0]]                   # [[S,S],[E,E]]
        assert il[1] == [il[1][0], il[1][0]]
        assert _mmf(il[0][0][2]) == 0.0                        # 地（z=0）
        assert _mmf(il[1][0][2]) == pytest.approx(ctx["h_mm"])  # 导带上缘
    assert m.lumped_ports == [] and build["lumped_ports"] == []
    ell, wb = ctx["l_sect_mm"], ctx["w_bal_mm"]
    x_ca = ell - wb / 2.0
    sheet = m.rect_bboxes["PAsheet"]
    assert sheet[0] == pytest.approx(x_ca - mod.MARCHAND_W2M_LATERAL_MM)
    assert sheet[3] == pytest.approx(x_ca + mod.MARCHAND_W2M_LATERAL_MM)
    assert sheet[5] == pytest.approx(mod.MARCHAND_AIR_TOP_MM)  # z 0→域顶
    assert build["audit"]["ports_ok"] is True
    assert build["n_radiation_faces"] >= 1


def test_marchand_wave2mode_dry_end_to_end(tmp_path):
    """wave2mode 发射面端到端（dry 合成链，零 pyaedt 零求解）：判据分派
    P1 反射侧两门、.s5p Σ模数导出、分派注记落 implementation_notes、
    BALUN_GATES 记录项如实缺位；缺省 lumped140 形态行为零变化对照
    （.s3p/五门全套）。"""
    v = mod.run_seat("marchand_balun", machine="local", out_dir=tmp_path,
                     dry_run=True, marchand_port_form="wave2mode")
    assert v["status"] == "DONE"
    assert v["port_form"] == "wave2mode"
    assert v["verdict"] in (*mod._OK_VERDICTS, "UNDECIDABLE")
    for lvl in (1, 2, 3):
        assert (tmp_path / f"rung{lvl}.s5p").exists()          # Σ模数 5（#309）
    assert {r["metric"] for r in v["per_metric"]} == {"f_null_ghz",
                                                      "s11_min_db"}
    notes = " ".join(v["implementation_notes"])
    assert "wave2mode 判据分派" in notes and "2 模反演" in notes
    assert "balun_gates_record" not in v                       # 模域矩阵不适用
    assert v["valley_maps"]["f_null_ghz"]["hfss"]["n_valleys"] >= 1
    # 缺省形态零变化对照
    v0 = mod.run_seat("marchand_balun", machine="local",
                      out_dir=tmp_path / "lumped", dry_run=True)
    assert v0["port_form"] == "lumped140"
    assert (tmp_path / "lumped" / "rung1.s3p").exists()
    assert {r["metric"] for r in v0["per_metric"]} >= {
        "f_null_ghz", "s21_band_min_db", "s31_band_min_db",
        "imbalance_band_max_db"}
    assert "balun_gates_record" in v0


def test_marchand_port_form_cli_guards():
    """CLI 面：--marchand-port-form 越席/配 --all 一律 parser.error 拒绝
    （端口形态单变量对照只属 marchand 单席路径）。"""
    with pytest.raises(SystemExit) as ei:
        mod.main(["--seat", "wilkinson", "--machine", "local",
                  "--marchand-port-form", "wave2mode"])
    assert ei.value.code == 2
    with pytest.raises(SystemExit) as ei2:
        mod.main(["--all", "--marchand-port-form", "wave2mode"])
    assert ei2.value.code == 2


def test_seat_argv_carries_port_form():
    """并行编排器→席位子进程 argv 全链携带 --marchand-port-form（缺省零
    携带=行为零变化）。"""
    argv = mod._seat_argv("marchand_balun", machine="sim_host",
                          out_dir=Path("x"), dry_run=True, grpc_port=None,
                          residue_check=True,
                          marchand_port_form="wave2mode")
    assert "--marchand-port-form" in argv
    assert argv[argv.index("--marchand-port-form") + 1] == "wave2mode"
    argv0 = mod._seat_argv("marchand_balun", machine="local",
                           out_dir=Path("x"), dry_run=False, grpc_port=None,
                           residue_check=True)
    assert "--marchand-port-form" not in argv0


# ═══════════════ --remote 路由+license 预检+max_parallel 闸（v1 调度面）══════════════
# 全 mock 零网络（#139）：预检通道一律 monkeypatch mod.remote_license_preflight。

def test_run_seat_remote_preflight_fail_skips(tmp_path, monkeypatch):
    """远程真机：license 预检 FAIL → SKIP(许可阻塞) 如实记账；会话层不开始
    （不硬打），信封随 verdict 落档。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)
    monkeypatch.setattr(mod, "remote_license_preflight", lambda m, deep=False: {
        "verdict": "FAIL", "reason": "license 端口不可达: ansys_license(1055)"})

    def _boom(*a, **kw):
        raise AssertionError("预检未过不得进入会话层")

    monkeypatch.setattr(mod, "open_remote_hfss", _boom)
    v = mod.run_seat("stepped_impedance", machine="sim_host",
                     out_dir=tmp_path, dry_run=False)
    assert v["verdict"] == "SKIP"
    assert "预检未过" in v["error"]
    assert v["license_preflight"]["verdict"] == "FAIL"


def test_run_seat_remote_preflight_pass_records_envelope(tmp_path, monkeypatch):
    """预检 PASS → 信封留档，会话层照常 fail-closed（故障注入验证次序：
    预检先于 attach）。"""
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)
    monkeypatch.setattr(mod, "remote_license_preflight",
                        lambda m, deep=False: {"verdict": "PASS",
                                               "reason": None})

    def _connect_boom(seat, machine, *, grpc_port=None):
        raise ConnectionError("gRPC 拒绝")

    monkeypatch.setattr(mod, "open_remote_hfss", _connect_boom)
    v = mod.run_seat("stepped_impedance", machine="sim_host",
                     out_dir=tmp_path, dry_run=False)
    assert v["verdict"] == "FAIL"
    assert v["license_preflight"]["verdict"] == "PASS"


def test_run_seat_local_and_dry_never_preflight(tmp_path, monkeypatch):
    """缺省 local 零变化钉：local 真机与远程 dry-run 路径都绝不发起 license
    预检（零网络零注册表读）。"""
    def _boom(*a, **kw):
        raise AssertionError("local/dry 路径不得发起 license 预检")

    monkeypatch.setattr(mod, "remote_license_preflight", _boom)
    monkeypatch.setattr(mod, "check_ansysedt_residue", lambda: 0)

    def _open_boom(seat, project_path):
        raise ConnectionError("gRPC 拒绝")

    monkeypatch.setattr(mod, "open_local_hfss", _open_boom)
    v = mod.run_seat("wilkinson", machine="local", out_dir=tmp_path,
                     dry_run=False)
    assert v["verdict"] == "FAIL"          # local 故障照旧，无预检
    assert "license_preflight" not in v
    v2 = mod.run_seat("wilkinson", machine="sim_host", out_dir=tmp_path,
                      dry_run=True)        # dry 合成链零网络
    assert v2["verdict"] in mod._OK_VERDICTS   # dry 端到端照常（裁决态不挑）
    assert "license_preflight" not in v2


def test_run_all_parallel_remote_license_gate_blocks_wave(tmp_path, monkeypatch):
    """remote 并行：波前 license 预检 FAIL → 整波席位 SKIP 不发射（不拉
    grpcsrv 不 spawn），逐席 verdict.json 记账+波级 license_gate 留痕，rc=2。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER",
                        ("stepped_impedance", "coupled_line"))
    monkeypatch.setattr(mod, "remote_license_preflight", lambda m, deep=False: {
        "verdict": "FAIL", "reason": "端口不通"})

    def _boom(*a, **kw):
        raise AssertionError("预检未过不得拉 grpcsrv")

    monkeypatch.setattr(mod, "launch_remote_grpcsrv", _boom)
    spawned: list = []
    monkeypatch.setattr(
        mod, "_spawn_seat",
        lambda argv, out_dir, fh: spawned.append(argv) or _FakeProc(0))
    rc = mod.run_all_parallel("sim_host", False, 2, out_root=tmp_path)
    assert rc == 2
    assert spawned == []
    s = json.loads((tmp_path / "window_summary.json").read_text(
        encoding="utf-8"))
    assert all(e["verdict"] == "SKIP" and "license" in e["status"]
               for e in s["seats"])
    assert all(w["license_gate"]["verdict"] == "FAIL" for w in s["waves"])
    v = json.loads((tmp_path / "stepped_impedance" / "hfss_side_remote" /
                    "verdict.json").read_text(encoding="utf-8"))
    assert v["verdict"] == "SKIP"
    assert v["license_preflight"]["reason"] == "端口不通"


def test_run_all_parallel_local_has_no_license_gate(tmp_path, monkeypatch):
    """local 并行零变化钉：零预检调用、waves 无 license_gate 键。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER", ("stepped_impedance",))

    def _boom(*a, **kw):
        raise AssertionError("local 不得发起 license 预检")

    monkeypatch.setattr(mod, "remote_license_preflight", _boom)

    def _fake_spawn(argv, out_dir, log_fh):
        seat = argv[argv.index("--seat") + 1]
        (Path(out_dir) / "verdict.json").write_text(json.dumps(
            {"seat": seat, "verdict": "AGREE_JUDGE", "status": "DONE",
             "wall_s": 1.0}), encoding="utf-8")
        return _FakeProc(0)

    monkeypatch.setattr(mod, "_spawn_seat", _fake_spawn)
    rc = mod.run_all_parallel("local", True, 2, out_root=tmp_path)
    assert rc == 0
    s = json.loads((tmp_path / "window_summary.json").read_text(
        encoding="utf-8"))
    assert "license_gate" not in s["waves"][0]
    assert "max_parallel_cap" not in s


def test_run_all_remote_parallel_capped_by_registry(tmp_path, monkeypatch):
    """远程 --parallel 超注册表 hfss.max_parallel → 发射侧收敛到闸值并随
    run_all_parallel 记账；local 不读注册表（零变化钉）。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER", ("stepped_impedance",))
    import rfauto.infra.remote_machines as rm
    captured: dict = {}

    def _fake_par(machine, dry_run, parallel, port_base=None, out_root=None,
                  max_parallel_cap=None):
        captured["parallel"] = parallel
        captured["cap"] = max_parallel_cap
        return 0

    monkeypatch.setattr(mod, "run_all_parallel", _fake_par)
    cfg = rm.RemoteMachineConfig(name="sim_host", host="1.2.3.4",
                                 hfss_max_parallel=2)
    monkeypatch.setattr(rm, "load_remote_machines", lambda: {"sim_host": cfg})
    assert mod.run_all("sim_host", False, parallel=8, out_root=tmp_path) == 0
    assert captured["parallel"] == 2
    assert captured["cap"]["declared"] == 8
    assert captured["cap"]["effective"] == 2
    assert "hfss.max_parallel" in captured["cap"]["source"]

    # local：不读注册表（注册表加载被替换成炸警卫）+ cap 恒 None
    def _no_load():
        raise AssertionError("local 路径不得读注册表")

    monkeypatch.setattr(rm, "load_remote_machines", _no_load)
    captured.clear()
    assert mod.run_all("local", True, parallel=8, out_root=tmp_path) == 0
    assert captured["parallel"] == 8
    assert captured["cap"] is None


def test_run_all_remote_parallel_registry_unreadable_no_cap(tmp_path,
                                                            monkeypatch):
    """注册表读失败 → 闸缺席不硬设（None=不收敛），坏机器由逐席预检/会话层
    如实 FAIL——治理面不成为主路径故障点（#105）。"""
    monkeypatch.setattr(mod, "LAUNCH_ORDER", ("stepped_impedance",))
    import rfauto.infra.remote_machines as rm
    captured: dict = {}

    def _fake_par(machine, dry_run, parallel, port_base=None, out_root=None,
                  max_parallel_cap=None):
        captured["parallel"] = parallel
        return 0

    monkeypatch.setattr(mod, "run_all_parallel", _fake_par)

    def _boom():
        raise RuntimeError("registry io boom")

    monkeypatch.setattr(rm, "load_remote_machines", _boom)
    assert mod.run_all("sim_host", False, parallel=6, out_root=tmp_path) == 0
    assert captured["parallel"] == 6


def test_cli_remote_routing(monkeypatch):
    """--remote 路由分派：裸 --remote=唯一登记机器、带值=显式机器名、
    --all 路径透传 run_all。"""
    import rfauto.infra.remote_machines as rm
    cfg = rm.RemoteMachineConfig(name="sim_host", host="1.2.3.4")
    monkeypatch.setattr(rm, "load_remote_machines", lambda: {"sim_host": cfg})
    seat_calls: list = []
    all_calls: list = []

    def _fake_seat(seat, machine="local", out_dir=None, dry_run=False,
                   grpc_port=None, residue_check=True,
                   marchand_port_form=None):
        seat_calls.append((seat, machine))
        return {"verdict": "AGREE_JUDGE", "status": "DONE", "wall_s": 1.0}

    def _fake_all(machine="local", dry_run=False, **kw):
        all_calls.append(machine)
        return 0

    monkeypatch.setattr(mod, "run_seat", _fake_seat)
    monkeypatch.setattr(mod, "run_all", _fake_all)
    assert mod.main(["--seat", "wilkinson", "--remote"]) == 0
    assert seat_calls == [("wilkinson", "sim_host")]      # 裸=唯一登记机器
    seat_calls.clear()
    assert mod.main(["--seat", "wilkinson",
                     "--remote", "sim_host"]) == 0
    assert seat_calls == [("wilkinson", "sim_host")]      # 显式名
    assert mod.main(["--all", "--remote"]) == 0
    assert all_calls == ["sim_host"]


def test_cli_remote_conflicts_and_errors(monkeypatch):
    """--remote 冲突/错误面（argparse 级拒绝，SystemExit 2）：与 --machine
    互斥、--remote local 拒绝、未登记机器拒绝、空注册表拒绝。"""
    import rfauto.infra.remote_machines as rm
    for bad in (
        ["--all", "--machine", "sim_host", "--remote"],
        ["--seat", "wilkinson", "--remote", "local"],
        ["--seat", "wilkinson", "--remote", "nope"],
    ):
        with pytest.raises(SystemExit) as ei:
            mod.main(bad)
        assert ei.value.code == 2
    monkeypatch.setattr(rm, "load_remote_machines", lambda: {})
    with pytest.raises(SystemExit):
        mod.main(["--seat", "wilkinson", "--remote"])   # 空注册表


def test_cli_default_local_zero_registry_read(monkeypatch):
    """缺省（不带 --remote）零变化钉：main 不读注册表、machine 恒 local。"""
    import rfauto.infra.remote_machines as rm
    seat_calls: list = []

    def _fake_seat(seat, machine="local", out_dir=None, dry_run=False,
                   grpc_port=None, residue_check=True,
                   marchand_port_form=None):
        seat_calls.append(machine)
        return {"verdict": "AGREE_JUDGE", "status": "DONE", "wall_s": 1.0}

    def _no_load():
        raise AssertionError("缺省 local 不得读注册表")

    monkeypatch.setattr(rm, "load_remote_machines", _no_load)
    monkeypatch.setattr(mod, "run_seat", _fake_seat)
    assert mod.main(["--seat", "wilkinson", "--dry-run"]) == 0
    assert seat_calls == ["local"]
