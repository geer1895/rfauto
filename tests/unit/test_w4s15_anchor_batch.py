"""aurora_j W4-S15 锚覆盖转正批回归钉（8 锚八族；72 模板无锚差集清偿）。

锚册：knowledge/anchors.yaml aurora_j W4-S15 批（2026-10-23，79→87 锚、
有锚族 64/72→72/72=TEMPLATE_META 全覆盖）——前两轮评审弃选 9 族
（runs/aurora_d_sensanc/REPORT.md 第三节 + runs/aurora_d_anchd/REPORT.md）
本批逐族改道兑现，逐锚两类钉（#118 禁同源自证，X5/SENS-ANC/ANCH-D/W3-S15
同制度）：

1. **独立重算钉**：文献恒等式/纯算术在测试内**第二实现转录**（wstep 阶跃
   Γ 代数+Z_in 递推频率无关恒等、槽线族 λg=λ0·λ_ratio 与 β=k0√εeff 恒等、
   embedded_ms FD 裁判名义点回代），与锚值对拍；归档真机证据（wstep/bend
   WP2.2 冒烟、dipole/pifa w2srv_r2、helix HFSS 仲裁、槽线族路线 B/过渡
   真机）自归档产物**复提取逐位钉**（证据缺失 skip 如实，marchand 先例）；
2. **注册表钉**：resolve 域内命中、形态分档（closedform/fdref/lit/pointer
   与 layer 对应，#122）、消费面零接线（consumers=[]）。

弃选改道账（逐族）：wstep/bend=阶跃 Γ 代数/文献门界面（非 HJ 宽度面）；
dipole/pifa=归档真机证据新于弃选时点；helix=HFSS 仲裁 AGREE 双值 pointer
（同源风险声明禁产 constant，ring.design_dk 判例）；embedded_ms=FD 裁判
档（fdref 层）+双退化极限恒等链；msl_slot_transition/slotline_lumped=
槽线段 β/λg 色散面（非 Z0 重复）。
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from rfauto.infra.anchors_store import load_anchors

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: W4-S15 批 8 锚 id（与 EXPECTED_ANCHORS 批注同步维护）
_W4S15_ANCHOR_IDS = (
    "wstep.s11_step_db.closedform-v1",
    "bend.s11_max_db.lit-v1",
    "dipole.f_res.openems-v1",
    "pifa.f_res.openems-v1",
    "helix.f_x.openems-hfss-v1",
    "embedded_ms.eps_eff.fdref-v1",
    "msl_slot_transition.beta_slot.closedform-v1",
    "slotline_lumped.line_len_mm.closedform-v1",
)

_C_MM_GHZ = 299.792458


def _live():
    return load_anchors()


def _rec(aid: str):
    rec = _live().get(aid)
    assert rec is not None, aid
    return rec


def _skip_unless(rel: str) -> Path:
    p = _REPO_ROOT / rel
    if not p.exists():
        pytest.skip(f"既有真机历史产物缺失（gitignored 证据区）: {rel}")
    return p


def _s11_series(csv_path: Path) -> list[tuple[float, float]]:
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh))[1:]
    return [(float(r[0]) / 1e9, abs(complex(float(r[1]), float(r[2]))))
            for r in rows]


# ── 1. wstep：阶跃 Γ 精确代数（第二实现=Z_in 递推频率无关恒等）──────────────

def test_wstep_gamma_pure_algebra() -> None:
    rec = _rec("wstep.s11_step_db.closedform-v1")
    # 纯算术第二实现：|Γ|=|Z2−Z1|/(Z2+Z1)=15/85（Pozar 反射系数恒等式）
    exact_db = 20.0 * math.log10(15.0 / 85.0)
    assert exact_db == pytest.approx(-15.066553, abs=5e-7)
    assert rec.value == pytest.approx(exact_db, abs=5e-7)
    res = _live().resolve_anchor("wstep.s11_step_db.closedform-v1",
                                 {"f0_ghz": 2.5})
    assert res["hit"] and res["domain_ok"] and res["status"] == "active"
    assert res["value"] == rec.value


def test_wstep_zin_recursion_frequency_independent() -> None:
    """第二实现（导出式非引用）：对端匹配（负载=Z2）时阶跃面 Γ 经 Z1 线段
    回推端口只改相位——|S11|(θ)=|Z2−Z1|/(Z2+Z1) 对任意电长度 θ 成立。"""
    z1, z2 = 50.0, 35.0
    for theta in (0.0, 0.3, 1.0, math.pi / 4, 2.0):
        t = math.tan(theta)
        z_in = z1 * (z2 + 1j * z1 * t) / (z1 + 1j * z2 * t)
        gamma = (z_in - z1) / (z_in + z1)
        # 幅值恒定（相位随 θ 旋转——幅值即锚值，θ 无关恒等本体）
        assert abs(gamma) == pytest.approx(15.0 / 85.0, abs=1e-12), theta
    # 合成链名义回代：HJ inverse_width(35Ω)=w2 名义（X5 mline 同款自洽）
    from rfauto.core.synthesis import Stackup, forward_z0, nominal_width_mm

    w2 = nominal_width_mm(35.0, 2.5, "rogers4350b_h0.508")
    assert w2 == pytest.approx(1.897, abs=5e-4)
    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    assert forward_z0(w2, 2.5, stackup).z0 == pytest.approx(35.0, abs=5e-2)


def test_wstep_smoke_pt2_first_judgment_gap_in_gate() -> None:
    """真机首判回填钉：WP2.2 pt2 归档冒烟 |S11|@f0 对理想地板 gap ≤ +3dB。"""
    path = _skip_unless("runs/wstep_smoke/pt2/sparams.csv")
    series = _s11_series(path)
    f0_val = min(series, key=lambda t: abs(t[0] - 2.5))[1]
    gap_db = 20.0 * math.log10(f0_val) - (-15.066553)
    assert gap_db == pytest.approx(-0.8082, abs=0.01)  # 复提取逐位
    assert gap_db <= 3.0  # 预声明门（5c92d5c7 pt2 冻结口径）


# ── 2. bend：门型锚（−15dB 文献界）+ pt1 归档冒烟 ───────────────────────────

def test_bend_gate_anchor_shape_and_smoke() -> None:
    rec = _rec("bend.s11_max_db.lit-v1")
    assert rec.value == -15.0  # 门值即界
    assert rec.kind == "constant" and rec.layer == "closure"
    assert rec.engine_pair is None  # lit 源（siw.w_eff.lit-v1 同形）
    assert rec.uncertainty["value"] == 0.0
    assert "门值即界" in str(rec.uncertainty.get("note", ""))
    # 判据冻结原文在档（02d79a3d 原文口径）
    assert "未切角" in str(rec.raw["quantity"]["semantics"])
    path = _skip_unless("runs/bend_smoke/pt1/sparams.csv")
    series = _s11_series(path)
    band = [20.0 * math.log10(m) for f, m in series if 2.25 <= f <= 2.75]
    band_max = max(band)
    assert band_max == pytest.approx(-26.172, abs=0.01)  # 复提取逐位
    assert band_max <= -15.0  # 门内 11.2dB 余量（真机首判 PASS）


# ── 3./4. dipole/pifa：aurora_e w2srv_r2 归档真机 pointer ──────────────────

@pytest.mark.parametrize("tpl,aid,f_dip", [
    ("dipole", "dipole.f_res.openems-v1", 2.3232),
    ("pifa", "pifa.f_res.openems-v1", 2.268),
])
def test_dipole_pifa_pointer_vs_archive(tpl: str, aid: str,
                                        f_dip: float) -> None:
    rec = _rec(aid)
    assert rec.kind == "pointer" and rec.status == "experimental"
    assert rec.layer == "component"
    assert rec.value is None and rec.consumers == []  # 消费面不接
    vals = rec.raw["quantity"]["values"]
    assert vals == {"openems": f_dip}  # 单引擎封档（mmwave v1 制度）
    verdict = json.loads(
        _skip_unless(f"runs/aurora_e/w2srv_r2/{tpl}/verdict.json")
        .read_text(encoding="utf-8"))
    assert verdict["status"] == "PASS" and verdict["g3_finite"]
    # 归档 sparams 复提取：格点谷位逐位 == 锚双值（#314 掩码仅 S11 已测）
    series = _s11_series(
        _skip_unless(f"runs/aurora_e/w2srv_r2/{tpl}/sparams.csv"))
    f_min, m_min = min(series, key=lambda t: t[1])
    assert f_min == pytest.approx(f_dip, abs=1e-9)
    assert 20.0 * math.log10(m_min) == pytest.approx(
        -26.008 if tpl == "dipole" else -7.396, abs=0.01)
    res = _live().resolve_anchor(aid)
    assert res["hit"] and res["source"] == "anchor"
    assert res["value"] is None  # pointer 不就地求值


# ── 5. helix：HFSS 仲裁 AGREE 双值 pointer（同源风险声明）───────────────────

def test_helix_pointer_vs_arbitration() -> None:
    aid = "helix.f_x.openems-hfss-v1"
    rec = _rec(aid)
    assert rec.kind == "pointer" and rec.status == "experimental"
    assert rec.consumers == []
    vals = rec.raw["quantity"]["values"]
    assert vals["openems"] == 3.3146 and vals["hfss"] == 3.2675
    # 互差重算 == uncertainty（1.44% ≤5% 门 AGREE）
    dev = abs(vals["openems"] - vals["hfss"]) / vals["hfss"] * 100.0
    assert dev == pytest.approx(1.44, abs=0.005)
    assert rec.uncertainty["value"] == pytest.approx(
        abs(vals["openems"] - vals["hfss"]), abs=1e-9)
    # 仲裁工作点钉死（旧名义 pitch；新名义 9.2587 系同源 k 定版不入域）
    assert rec.domain == {"helix_pitch_mm": [3.6142, 3.6142]}
    # 同源风险声明随锚落档（#122 禁产 constant 的物理根据）
    sem = str(rec.raw["quantity"]["semantics"])
    assert "同源风险" in sem and "K_HELIX" in sem
    assert "forbidden" in str(rec.provenance.get("domain_note", "") or "") or \
        "forbidden" in sem
    arb = json.loads(_skip_unless("runs/helix_arbitration/hfss_arbitration.json")
                     .read_text(encoding="utf-8"))
    assert arb["verdict"] == "AGREE"
    assert arb["f_x_openems"]["f_ghz"] == vals["openems"]  # 逐位
    assert arb["f_x_hfss"]["f_ghz"] == vals["hfss"]


# ── 6. embedded_ms：FD 裁判名义 εeff（名义单点回代带内）──────────────────────

def test_embedded_ms_eps_eff_fd_referee_band() -> None:
    aid = "embedded_ms.eps_eff.fdref-v1"
    rec = _rec(aid)
    assert rec.value == 3.24008
    assert rec.kind == "constant" and rec.layer == "closure"
    assert rec.raw["engine_pair"] == {"calibrated": "quasistatic_fd",
                                      "referee": None}
    # 物理括号恒等：1 ≤ εeff ≤ εr（族内锚④同式）
    assert 1.0 < rec.value < 3.66
    # 名义单点 FD 回代（默认网格 Richardson；精度 ~0.5% 内，与设计链同源）
    from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL
    from rfauto.core.embedded_line import embedded_ms_quasistatic

    nom = TEMPLATE_NOMINAL["embedded_ms"]
    r = embedded_ms_quasistatic(nom["w_mm"], nom["h_mm"], nom["h2_mm"],
                                nom["er"])
    assert r.eps_eff == pytest.approx(rec.value, rel=5e-3)
    # 双退化极限恒等链在树（provenance 引用 test_ta_wave_c_templates 四锚）
    assert "h2" in str(rec.raw["quantity"]["semantics"])
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


# ── 7./8. 槽线族：λg/β 恒等（第二实现=色散关系纯算术转录）───────────────────

def test_slotline_family_identity_chain() -> None:
    """λg=λ0·λ_ratio、β=k0√εeff 恒等（J-S 闭式色散关系第二实现）：
    slotline_lumped.line_len=λg 设计恒等 + msl_slot_transition β 同点同式。"""
    from rfauto.core.slotline import slotline_closed_form

    r = slotline_closed_form(1.0, 1.524, 3.66, 2.5)
    lam0_mm = _C_MM_GHZ / 2.5
    lam_g = lam0_mm * r.lambda_ratio                     # 恒等式①
    assert lam_g == pytest.approx(93.46239793834523, abs=5e-7)
    beta = 2.0 * math.pi * 2.5 / _C_MM_GHZ * 1e3 * math.sqrt(r.eps_eff)
    assert beta == pytest.approx(r.beta_rad_m, rel=1e-12)  # 恒等式②
    assert beta == pytest.approx(67.22687889224117, abs=5e-7)
    # line_len 锚：TEMPLATE_NOMINAL 4 位舍入逐位（回代比值 1.0000000221）
    from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL

    rec_len = _rec("slotline_lumped.line_len_mm.closedform-v1")
    assert TEMPLATE_NOMINAL["slotline_lumped"]["line_len_mm"] == rec_len.value
    assert rec_len.value == pytest.approx(round(lam_g, 4), abs=1e-9)
    assert rec_len.value / lam_g == pytest.approx(1.0, abs=5e-8)
    # β 锚：CALC slotline_analysis 单源口径 4 位舍入逐位
    rec_beta = _rec("msl_slot_transition.beta_slot.closedform-v1")
    from rfauto.core.calc_families.slotline_siw import slotline_analysis

    assert slotline_analysis(1.0, 1.524, 3.66, 2.5)["beta_rad_m"] == \
        rec_beta.value
    # 同点 Z0 面已由 slotline.z0_ohm 在册（重复物理不另立锚的边界注记）
    z0_rec = _rec("slotline.z0_ohm.closedform-v1")
    assert z0_rec.value == pytest.approx(110.9206, abs=5e-4)
    for rec in (rec_len, rec_beta):
        res = _live().resolve_anchor(rec.anchor_id, {"f0_ghz": 2.5})
        assert res["hit"] and res["domain_ok"]
        assert res["value"] == rec.value


def test_slotline_family_real_machine_beta_in_gate() -> None:
    """真机判读钉：路线 B r_closed β 双行波 +1.746% / 过渡 trans +3.012%
    均 ≤5% 预声明信息门（slotline_transitions/openems_result.json）。"""
    pb = json.loads(_skip_unless("runs/slotline_port_b/result.json")
                    .read_text(encoding="utf-8"))
    rc = pb["variants"]["r_closed"]
    assert rc["beta_vs_cf_pct"] == pytest.approx(1.7464, abs=0.01)
    assert pb["design"]["closed_form"]["beta_rad_m"] == \
        pytest.approx(67.22687889224117, abs=1e-9)  # 闭式单源同点逐位
    tr = json.loads(
        _skip_unless("runs/slotline_transitions/openems_result.json")
        .read_text(encoding="utf-8"))["runs"]["trans"]
    assert tr["beta_vs_closed_pct"] == pytest.approx(3.0123, abs=0.01)
    assert tr["gates"]["band_max_s11_le_minus10db"] is True


# ── 注册表形态钉（#122：各档与 layer 对应，analytic 档可区分）────────────────

@pytest.mark.parametrize("aid", _W4S15_ANCHOR_IDS)
def test_w4s15_anchor_registry_shape(aid: str) -> None:
    rec = _rec(aid)
    parts = aid.split(".")
    fam = parts[0]
    from rfauto.adapters.oe_templates.registry import TEMPLATE_META

    assert fam in TEMPLATE_META, fam
    assert rec.template_family == [fam]
    assert rec.status in ("active", "experimental")
    assert rec.consumers == []  # 本批零接线如实（声明面见 provenance）
    if aid.endswith("closedform-v1"):
        assert rec.kind == "constant" and rec.layer == "closure"
        assert rec.raw["engine_pair"] == {"calibrated": "closedform",
                                          "referee": None}
        assert rec.raw["quantity"]["name"] == f"{fam}_{parts[1]}"
        assert rec.raw["uncertainty"]["kind"] in ("identity", "rounding_band")
        assert rec.fallback == "closed_form"
    elif "fdref" in aid:
        assert rec.kind == "constant" and rec.layer == "closure"
        assert rec.raw["engine_pair"]["calibrated"] == "quasistatic_fd"
    elif aid == "bend.s11_max_db.lit-v1":
        assert rec.kind == "constant" and rec.layer == "closure"
        assert rec.engine_pair is None  # lit 域盒锚形态（kj_even_domain 同）
    else:  # pointer 三席（dipole/pifa/helix）
        assert rec.kind == "pointer" and rec.layer == "component"
        assert rec.raw["engine_pair"] == {"calibrated": "openems",
                                          "referee": "hfss"}
        assert rec.raw["quantity"].get("values")
        assert rec.value is None


def test_w4s15_batch_count_and_expected_source_sync() -> None:
    # 单源对账（#231）：整册与 EXPECTED_ANCHORS 一致由
    # test_anchors_store_service 钉；此处钉 W4-S15 批 8 席全在册+
    # 有锚族 72/72 全覆盖（X5 批口径：TEMPLATE_META 族集内计数）
    live = _live()
    for aid in _W4S15_ANCHOR_IDS:
        assert aid in live, aid
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert len(_W4S15_ANCHOR_IDS) == 8
    assert all(a in EXPECTED_ANCHORS for a in _W4S15_ANCHOR_IDS)
    import yaml

    from rfauto.adapters.oe_templates.registry import TEMPLATE_META

    reg = yaml.safe_load(
        (_REPO_ROOT / "knowledge" / "anchors.yaml").read_text(
            encoding="utf-8"))
    covered = {
        fam
        for entry in reg["anchors"]
        for fam in (entry.get("template_family") or [])
        if fam in TEMPLATE_META
    }
    assert len(covered) == 72  # W4-S15 批 64→72：TEMPLATE_META 全覆盖
    for fam in _W4S15_ANCHOR_IDS:
        assert fam.split(".")[0] in covered
