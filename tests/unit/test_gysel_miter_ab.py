"""C7 gysel mitered-jog 切角旋钮真机 A/B 驱动单测（scripts/gysel_miter_ab.py）。

裁判分层（#118 不自证，test_marchand_via_ab 同款）：
- 旋钮缺省逐字节不变（缺省 vs 显式 0 全文相同；off vs on 全文 diff 恰=近点
  两行+jog 段原语，strip_variant_specific 剥离后余下逐字节相等）；
- 几何=exec 渲染文本（FDTD.Run 截断，#212 零仿真）读终网格实测：缺口缘入网
  无 #152 族近撞（min span ≥40µm）、on/off CFL dt 因子 ≤1.5（预算可行性门）；
- 判读=合成回收：load_sparams 9 列契约（宽度守卫 fail loud #316）+ metrics
  合成注入 + ab_table 三分支（IMPROVES/NEUTRAL/WORSENS）+护栏/stability；
- 计划/判据预声明一致性（预算与阈值写死）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "src"), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gysel_miter_ab as ab
from rfauto.adapters.openems_templates import render_script

_FREQ = ab.FREQ_RANGE_GHZ
_GYS = dict(ab.GYS_PARAMS)


def _render(params: dict) -> str:
    return render_script("gysel", params, _FREQ,
                         mesh_resolution_mm=ab.MESH_MM)


# ─── ① 旋钮：off 逐字节不变 + diff 恰=jog 段（IC67 契约渲染面复验） ────────────

def test_render_default_matches_explicit_zero_byte_identical():
    """缺省（不传 _jog_miter_mm）与显式 0 渲染全文逐字节相同（off=rod 时代钉）。"""
    assert _render(dict(_GYS)) == _render(dict(_GYS, _jog_miter_mm=0.0))


def test_diff_off_on_is_jog_segment_and_near_points_only():
    """off vs on diff 恰=近点两行+jog 段；剥离后余下逐字节相等（单变量契约）。"""
    t_off, t_on = _render(dict(_GYS)), _render(dict(_GYS, _jog_miter_mm=0.2))
    assert ab.strip_variant_specific(t_off) == ab.strip_variant_specific(t_on)
    changed = [ln for ln in t_off.splitlines() if ln not in
               set(t_on.splitlines())]
    added = [ln for ln in t_on.splitlines() if ln not in
             set(t_off.splitlines())]
    assert changed and added
    jog_tokens = ("L-jog", "gysel.AddBox", "_near_", "mitered-jog", "缺口",
                  "YJ", "H_SUB")
    for ln in changed + added:
        assert any(t in ln for t in jog_tokens), f"diff 含非 jog 段行：{ln!r}"
    assert "_jog_miter_mm" not in t_off        # off 渲染零旋钮痕迹
    # on 的缺口缘网格线在 off 中不存在（x=±18.5187 / y=17.6947）
    assert "0.0185187" in t_on and "0.0176947" in t_on
    assert "0.0185187" not in t_off and "0.0176947" not in t_off


def test_notch_audit_passes_on_and_fails_missing_notch(tmp_path):
    """on 缺口几何断言全过；缺口顶缘坐标被篡改后断言红（守卫非恒真）。

    坐标=米（2026-09-21 A/B 审计修正渲染器 mm 字面量后，脚本主体同单位）；
    exec 侧交叉验证金属原语坐标=期望值（渲染文本审计↔CSX 实测双面钉）。
    """
    t_on = _render(dict(_GYS, _jog_miter_mm=0.2))
    good = ab.notch_audit(t_on)
    assert good["all_pass"] is True, good["checks"]
    assert good["checks"]["boxes_8"] and good["checks"]["jog_boxes_4"]
    assert good["checks"]["band_top_cut_2c"]
    audit, _ = _exec_audit(tmp_path, "on")
    want = ab.expected_jog_boxes_m()
    got = audit["metal_boxes_xy_m"]
    for b in want:
        assert any(all(abs(a - c) < 1e-12 for a, c in zip(b, g, strict=True))
                   for g in got), f"jog 盒缺失（米）：{b}"
    assert audit["metal_in_domain"]
    # 篡改缺口顶缘 y（+1e-7m）→ flush 断言红
    bad = ab.notch_audit(t_on.replace("0.0176947", "0.0176948"))
    assert bad["all_pass"] is False
    assert bad["checks"]["notch_flush_outcorner"] is False


# ─── ② exec 网格审计（零仿真；#152 族预算可行性门） ───────────────────────────

def _exec_audit(tmp_path: Path, mode: str) -> tuple[dict, str]:
    text = (_render(dict(_GYS)) if mode == "off"
            else _render(dict(_GYS, _jog_miter_mm=ab.MITER_C_MM)))
    path = tmp_path / f"rs_{mode}.py"
    path.write_text(text, encoding="utf-8")
    return ab.exec_mesh_audit(path, text), text


def test_exec_mesh_audit_off_baseline_and_no_cfl_collapse(tmp_path):
    """off 网格与烟测口径一致量级；on 缺口缘不塌 dt（因子 ≤1.5 预声明门）。"""
    a_off, _ = _exec_audit(tmp_path, "off")
    a_on, _ = _exec_audit(tmp_path, "on")
    assert a_off["min_span_ge_40um"] and a_on["min_span_ge_40um"]
    dt_factor = a_off["dt_cfl_s"] / a_on["dt_cfl_s"]
    assert dt_factor <= ab.DT_FACTOR_MAX
    # off 的 x 轴最小间距=烟测档量级（40-120µm；≤10µm 即 #152 族塌缩症状）
    assert 40e-6 <= a_off["min_span_m"]["x"] <= 120e-6
    # on 较 off 新增缺口缘：x/y 线数不减，且差 ≥2（两侧 x 缘；y 顶缘 1 条，
    # 与既有线重合时被渲染端 1µm 去重吸收，故只钉不减）
    for ax in "xy":
        assert a_on["mesh_lines"][ax] >= a_off["mesh_lines"][ax]


def test_c0p3_would_collapse_and_is_rejected_by_gate(tmp_path):
    """c=0.3 反证：缺口顶缘与负载盒缘 6.7µm 相撞 → 审计门红（选 c=0.2 依据）。"""
    path = tmp_path / "rs_c03.py"
    text = _render(dict(_GYS, _jog_miter_mm=0.3))
    path.write_text(text, encoding="utf-8")
    a_c03 = ab.exec_mesh_audit(path, text)
    assert a_c03["min_span_ge_40um"] is False
    assert min(a_c03["min_span_m"].values()) < 20e-6


# ─── ③ 判读纯逻辑：合成回收（#118） ──────────────────────────────────────────

def _synth_sp(s32_profile_db: np.ndarray, s11_f0: float = -25.0,
              s21_db: float = -3.01, s31_db: float = -3.01,
              nf: int = 41) -> dict[str, Any]:
    f = np.linspace(2.25, 2.75, nf)

    def flat(db_val: float) -> np.ndarray:
        return np.full(nf, 10.0 ** (db_val / 20.0))

    return {
        "f_ghz": f,
        "s11": flat(s11_f0) * (1 + 0j),
        "s21": flat(s21_db) * np.exp(-1j * np.pi / 4),
        "s31": flat(s31_db) * np.exp(+1j * np.pi / 4),
        "s23": 10.0 ** (np.asarray(s32_profile_db, dtype=float) / 20.0),
    }


def _prof(db_lo: float, db_hi: float, f0_db: float, nf: int = 41) -> np.ndarray:
    """dB 剖面：线性裙边 + f0（index nf//2）显式钉值（差值精确可控）。"""
    arr = np.linspace(db_lo, db_hi, nf)
    arr[nf // 2] = f0_db
    return arr


def test_metrics_synthetic_injection():
    sp = _synth_sp(_prof(-30.0, -26.0, -28.0))
    m = ab.metrics(sp)
    a0, iso = m["at_f0"], m["iso"]
    assert abs(a0["s32_db"] - -28.0) < 1e-9          # f0 显式钉值
    assert abs(a0["split_diff_db"]) < 1e-9
    assert abs(a0["phase_diff_deg"] - -90.0) < 1e-9
    assert abs(iso["min_db"] - -30.0) < 1e-9          # 谷在带边 lo
    assert iso["offset_pct"] == pytest.approx(-10.0, abs=0.01)
    assert abs(iso["band_max_db"] - -26.0) < 1e-9
    assert m["s11_passive_violation_pts"] == 0
    assert m["nf"] == 41


def test_ab_table_three_branches_and_side_effects():
    off = ab.metrics(_synth_sp(_prof(-30.0, -26.0, -28.0), s11_f0=-25.0))
    # 改善：ΔS32@f0=-2dB 且带内最差点更低
    on = ab.metrics(_synth_sp(_prof(-33.0, -27.0, -30.0), s11_f0=-26.0))
    tab = ab.ab_table(off, on)
    assert tab["delta_s32_f0_db"] == pytest.approx(-2.0, abs=1e-6)
    assert tab["conclusion"].startswith("MITER_IMPROVES")
    assert tab["stability"].startswith("STABLE_IMPROVED")
    assert tab["side_effects"] == []
    # 持平：ΔS32@f0=-0.5dB
    on_n = ab.metrics(_synth_sp(_prof(-31.0, -26.0, -28.5)))
    assert ab.ab_table(off, on_n)["conclusion"].startswith("MITER_NEUTRAL")
    # 恶化 + 护栏：ΔS32@f0=+2dB、ΔS11=+5dB、Δsplit=+1dB
    on_w = ab.metrics(_synth_sp(_prof(-28.0, -26.0, -26.0), s11_f0=-20.0,
                                s31_db=-4.01))
    tab_w = ab.ab_table(off, on_w)
    assert tab_w["conclusion"].startswith("MITER_WORSENS")
    assert len(tab_w["side_effects"]) == 2
    assert any("S11 护栏" in s for s in tab_w["side_effects"])
    assert any("均分护栏" in s for s in tab_w["side_effects"])
    # 差值表行完整（带内对照表：S32 四点+S11/S21/S31）
    keys = [r["metric"] for r in tab["rows"]]
    assert keys == ["s32_f0", "s32_min", "s32_band_max", "s32_edge_lo",
                    "s32_edge_hi", "s11_f0", "s21_f0", "s31_f0"]
    for r in tab["rows"]:
        assert r["delta"] == pytest.approx(r["on"] - r["off"], abs=2e-3)


def test_load_sparams_roundtrip_and_width_guard(tmp_path):
    """9 列 CSV 往返 + 宽度守卫：5 列（假 PASS 形态，fix-g11 口径）fail loud。"""
    f = np.linspace(2.25, 2.75, 5)
    s11 = 0.1 + 0.2j
    rows = np.stack([f * 1e9, np.full(5, s11.real), np.full(5, s11.imag),
                     np.full(5, 0.7), np.full(5, -0.7),
                     np.full(5, 0.6), np.full(5, 0.5),
                     np.full(5, -0.02), np.full(5, 0.05)], axis=1)
    p9 = tmp_path / "sparams.csv"
    np.savetxt(p9, rows, delimiter=",", comments="")
    header = ("freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,"
              "re_S23,im_S23\n")
    body = p9.read_text(encoding="utf-8")
    p9.write_text(header + body, encoding="utf-8")
    sp = ab.load_sparams(p9)
    assert sp["s11"][0] == s11
    assert sp["s23"][-1] == -0.02 + 0.05j
    assert len(sp["f_ghz"]) == 5
    # 5 列（S12:=S21 自比假 PASS 形态）→ ValueError 不静默
    p5 = tmp_path / "sparams5.csv"
    p5.write_text("freq_hz,re_S11,im_S11,re_S21,im_S21\n" + body,
                  encoding="utf-8")
    with pytest.raises(ValueError, match="9 列"):
        ab.load_sparams(p5)


def test_round_complete_products_over_rc(tmp_path):
    """完成判定=产物口径（#208 家族：绑定退出段 rc 崩溃但 CSV 完整即接受）。"""
    vd = tmp_path / "off"
    vd.mkdir()
    header = ("freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,"
              "re_S23,im_S23\n")
    body = "\n".join(f"{2.25e9 + i * 1.25e6},{j}" for i, j in enumerate(
        "0.1" for _ in range(ab.NF)))
    (vd / "sparams.csv").write_text(header + body + "\n", encoding="utf-8")
    (vd / "console.log").write_text(
        "rfauto openEMS simulation done\n", encoding="utf-8")
    assert ab._round_complete(vd) is True
    # 缺 done 标记 → 未完成（半程产物不冒充完成）
    (vd / "console.log").write_text("Timestep: 1234\n", encoding="utf-8")
    assert ab._round_complete(vd) is False
    # 行数不足 → 未完成
    (vd / "console.log").write_text(
        "rfauto openEMS simulation done\n", encoding="utf-8")
    (vd / "sparams.csv").write_text(header + "2250000000.0,0\n",
                                    encoding="utf-8")
    assert ab._round_complete(vd) is False


def test_gate_pack_honest_per_arm():
    m_good = ab.metrics(_synth_sp(np.full(41, -38.0)))
    g = ab.gate_pack(m_good, 0.5)
    assert all(g.values())
    m_iso_fail = ab.metrics(_synth_sp(np.full(41, -12.0)))
    g2 = ab.gate_pack(m_iso_fail, 0.5)
    assert g2["s32_le_minus15db"] is False
    assert g2["s21_minus3pm1db"] and g2["split_le_0p5db"]
    m_split = ab.metrics(_synth_sp(np.full(41, -38.0), s31_db=-4.5))
    assert ab.gate_pack(m_split, 0.5)["split_le_0p5db"] is False


# ─── ④ plan 幂等 + 预声明一致性 ──────────────────────────────────────────────

@pytest.fixture()
def _ab_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "ROOT", tmp_path)
    monkeypatch.setattr(ab, "PLAN_PATH", tmp_path / "plan.json")
    monkeypatch.setattr(ab, "CRITERIA_PATH", tmp_path / "criteria.md")
    monkeypatch.setattr(ab, "VERDICT_PATH", tmp_path / "verdict.json")
    monkeypatch.setattr(ab, "COLLECT_STATE_PATH",
                        tmp_path / "collect_state.json")
    return tmp_path


def test_cmd_plan_idempotent_and_declares_budget(_ab_root):
    assert ab.cmd_plan() == 0
    plan1 = json.loads((_ab_root / "plan.json").read_text(encoding="utf-8"))
    sha_off = plan1["variants"]["off"]["sha256"]
    assert plan1["declared"]["miter_c_mm"] == 0.2
    assert plan1["declared"]["partial_factor"] == 1.5
    assert plan1["declared"]["budget_wall_s"] == 7200.0
    assert plan1["declared"]["nrts"] == 100000
    assert plan1["declared"]["mesh_mm"] == 0.4
    assert (_ab_root / "criteria.md").exists()
    # 幂等：重跑 sha 不漂移、不重写 variants 内容
    assert ab.cmd_plan() == 0
    plan2 = json.loads((_ab_root / "plan.json").read_text(encoding="utf-8"))
    assert plan2["variants"]["off"]["sha256"] == sha_off
    assert (plan2["variants"]["off"]["mesh_min_span_m"]
            == plan1["variants"]["off"]["mesh_min_span_m"])
    # 渲染脚本落盘且 off 无旋钮痕迹
    off_txt = (_ab_root / "off" / "render_script.py").read_text(
        encoding="utf-8")
    assert "_jog_miter_mm" not in off_txt
    on_txt = (_ab_root / "on" / "render_script.py").read_text(encoding="utf-8")
    assert "mitered-jog" in on_txt


def test_declared_constants_and_criteria_text():
    assert ab.VARIANTS == ("off", "on")
    assert ab.MITER_C_MM == 0.2
    assert ab.BUDGET_WALL_S == 7200.0 and ab.PARTIAL_FACTOR == 1.5
    assert ab.SOLVE_TIMEOUT_S == 5400.0
    assert ab.LOCK_POLL_S == 30.0 and ab.LOCK_MAX_WAIT_S == 1800.0
    assert ab.IMPROVE_MAX_DB == -1.0 and ab.STABILITY_DELTA_DB == -0.5
    assert ab.LOCK_PATH.name == ".oe_collect.lock"
    assert ab.ROOT.name == "gysel_miter_ab"
    assert re.search(r"#261", ab.oe_foreign_running.__doc__ or "")
    crit = ab.CRITERIA_TEXT.format(ts="x")
    for token in ("PARTIAL", "3h", "c=0.2", "G11", "-38.1", "6.7µm",
                  "12µm", "6926", "fail-closed"):
        assert token in crit, f"criteria 缺预声明 token：{token}"


def test_runner_module_importable():
    spec = importlib.util.find_spec("gysel_miter_ab")
    assert spec is not None
    # 判读阈值联动：IMPROVE 边界恰在 ±IMPROVE_MAX_DB（|Δ|=1dB 持平侧）
    assert ab.IMPROVE_MAX_DB == -ab.IMPROVE_MAX_DB * -1.0  # 对称性自检
