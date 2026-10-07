"""ge8e X5 解析档锚批回归钉（13 锚九族；#118 独立重算=第二实现/文献值回代）。

锚册：knowledge/anchors.yaml ge8e X5 批（2026-10-04，36→48 席）——
atten_pi/atten_t/ratrace/stripline/slotline/siw/monopole/coil_nfc/
pyramid_horn 九族闭式恒等锚（verdict 语义=闭式推导档，真机首判窗随各卡）。

本文件每锚两类钉（#118 禁同源自证）：
1. **独立重算钉**：文献公式在测试内**第二实现转录**（不 import 内核公式/
   系数表），与锚值对拍；内核值另与第二实现对拍（抓转录/回归错）；
2. **注册表钉**：resolve_anchor 域内命中、值/单位/域盒一致；analytic 档
   形态=engine_pair.calibrated="closedform"（与引擎档可区分，#122）。

候选裁决策（宁少勿滥，followUp 留账 runs/review_ge8e/x5_analytic_anchors/
REPORT.md）：cpw 因 skrf-CPW（无底地，名义 67.44Ω）与 _cpwg_ri（底接地
CPWG，名义 50.0Ω）模型二义不立锚；mline 因 HJ 系数无仓内已核原文转录面
（#df6-⑬ citation-rot 防御）不立锚。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from rfauto.infra.anchors_store import load_anchors

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: X5 批 13 锚 id（与 EXPECTED_ANCHORS 批注同步维护）
_X5_ANCHOR_IDS = (
    "atten_pi.r_series_mid_ohm.closedform-v1",
    "atten_pi.r_shunt_end_ohm.closedform-v1",
    "atten_t.r_series_arm_ohm.closedform-v1",
    "atten_t.r_shunt_mid_ohm.closedform-v1",
    "ratrace.ring_z_ohm.closedform-v1",
    "ratrace.r_ring_mm.closedform-v1",
    "stripline.z0_ohm.closedform-v1",
    "stripline.eps_eff.closedform-v1",
    "slotline.z0_ohm.closedform-v1",
    "siw.fc_te10_ghz.closedform-v1",
    "monopole.mon_len_mm.closedform-v1",
    "coil_nfc.l_uh.closedform-v1",
    "pyramid_horn.gain_db.closedform-v1",
)

_C0 = 299792458.0


def _live():
    return load_anchors()


def _meta(template: str) -> dict:
    p = _REPO_ROOT / "docs" / "templates" / template / "meta.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ── 1. atten_pi / atten_t：匹配+分压两条件闭式（第二实现）───────────────────

def _atten_pi(a_db: float, z0: float) -> tuple[float, float]:
    n = 10.0 ** (a_db / 20.0)
    return (z0 * (n * n - 1.0) / (2.0 * n),   # 中点串臂
            z0 * (n + 1.0) / (n - 1.0))       # 两端对地并臂


def _atten_t(a_db: float, z0: float) -> tuple[float, float]:
    n = 10.0 ** (a_db / 20.0)
    return (z0 * (n - 1.0) / (n + 1.0),       # 串臂（上下各一）
            2.0 * z0 * n / (n * n - 1.0))     # 中点对地并臂


@pytest.mark.parametrize("aid,recalc,lit", [
    ("atten_pi.r_series_mid_ohm.closedform-v1", _atten_pi(10.0, 50.0)[0],
     71.15),
    ("atten_pi.r_shunt_end_ohm.closedform-v1", _atten_pi(10.0, 50.0)[1],
     96.25),
    ("atten_t.r_series_arm_ohm.closedform-v1", _atten_t(10.0, 50.0)[0],
     25.98),
    ("atten_t.r_shunt_mid_ohm.closedform-v1", _atten_t(10.0, 50.0)[1],
     35.14),
])
def test_atten_anchor_independent_recalc_and_literature(
        aid: str, recalc: float, lit: float) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    # 锚值 = 内核 3 位舍入，与第二实现全精度差 ≤ 舍入带
    assert abs(rec.value - recalc) <= 5.0e-4, (aid, rec.value)
    # 经典文献表值（Pozar/Mini-Circuits 10dB/50Ω 2 位小数）同带互证（双源）
    assert abs(rec.value - lit) <= 6e-3, (aid, lit)
    # 域内命中（operating point 域盒）
    res = _live().resolve_anchor(aid, {"atten_db": 10.0, "z0_ohm": 50.0})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value
    # 域外（ atten_db≠10）结构化 fallback（degenerate 域盒语义；resolve
    # 对已知锚保持 hit=True 但 source=fallback+reason=out_of_domain）
    res_off = _live().resolve_anchor(aid, {"atten_db": 3.0, "z0_ohm": 50.0})
    assert res_off["source"] == "fallback"
    assert res_off["domain_ok"] is False
    assert res_off["reason"] == "out_of_domain"
    assert res_off["value"] is None


def test_atten_kernel_matches_second_implementation() -> None:
    from rfauto.core.calc_families.rf_match import attenuator_pi, attenuator_t

    pi = attenuator_pi(10.0, 50.0)
    t = attenuator_t(10.0, 50.0)
    assert pi["r_series_mid_ohm"] == pytest.approx(
        _atten_pi(10.0, 50.0)[0], abs=5e-4)
    assert pi["r_shunt_end_ohm"] == pytest.approx(
        _atten_pi(10.0, 50.0)[1], abs=5e-4)
    assert t["r_series_arm_ohm"] == pytest.approx(
        _atten_t(10.0, 50.0)[0], abs=5e-4)
    assert t["r_shunt_mid_ohm"] == pytest.approx(
        _atten_t(10.0, 50.0)[1], abs=5e-4)


# ── 2. ratrace：环阻抗 √2·Z0 + 周长 1.5λg（Pozar §7.5 双链）────────────────

def test_ratrace_ring_z_identity() -> None:
    aid = "ratrace.ring_z_ohm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    # 独立重算：√2·50 纯算术（恒等锚零带宽）
    assert rec.value == pytest.approx(math.sqrt(2.0) * 50.0, abs=5e-5)
    res = _live().resolve_anchor(aid, {"z0_ohm": 50.0})
    assert res["hit"] and res["domain_ok"]
    # 域外（Z0≠50 系统点）结构化 fallback
    off = _live().resolve_anchor(aid, {"z0_ohm": 75.0})
    assert off["source"] == "fallback" and off["reason"] == "out_of_domain"


def test_ratrace_r_ring_identity_chain() -> None:
    aid = "ratrace.r_ring_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    meta = _meta("ratrace")
    assert meta["nominal_params"]["r_ring_mm"] == rec.value
    assert meta["nominal_params"]["w_ring_mm"] == pytest.approx(0.604)
    # 独立重算（Pozar §7.5 链算术）：R → 周长 1.5λg → εeff 反解
    lam0_mm = _C0 / (2.5e9) * 1e3
    lam_g_mm = 2.0 * math.pi * rec.value / 1.5
    eps_eff_implied = (lam0_mm / lam_g_mm) ** 2
    # HJ 正算（内核）与反解一致（双链闭合；w_ring 4 位舍入传播 ≤5e-4）
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup.from_materials_yaml("rogers4350b_h0.508")
    _, eps_eff_hj = forward_z0(
        float(meta["nominal_params"]["w_ring_mm"]), 2.5, st)
    assert eps_eff_implied == pytest.approx(eps_eff_hj, rel=5e-4)
    # 内核新鲜综合复现名义
    from rfauto.core.synthesis import synthesize_ratrace_model

    out = synthesize_ratrace_model()
    assert out.params["r_ring_mm"] == pytest.approx(rec.value, abs=1e-3)
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.5})
    assert res["hit"] and res["domain_ok"]


# ── 3. stripline：Cohn 椭圆积分闭式（AGM 第二实现）+ TEM εeff=εr ────────────

def _agm(a: float, b: float) -> float:
    for _ in range(80):
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return a


def _stripline_z0_ref(w_mm: float, b_mm: float, er: float) -> float:
    """Cohn 零厚对称带状线第二实现：Z0=30π/(√εr·r)，r=K(k)/K′(k)、
    k=tanh(πw/2b)；K(k)=π/(2·agm(1,k′))（AGM 恒等式）。"""
    x = math.pi * w_mm / (2.0 * b_mm)
    k = math.tanh(x)
    kp = 1.0 / math.cosh(x)  # sech 直取（无 1−k² 相消）
    r = _agm(1.0, k) / _agm(1.0, kp)
    return 30.0 * math.pi / (r * math.sqrt(er))


def test_stripline_z0_agm_transcription() -> None:
    aid = "stripline.z0_ohm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    ref = _stripline_z0_ref(0.5554, 1.016, 3.66)
    assert rec.value == pytest.approx(ref, abs=1e-4)
    from rfauto.core.calc_families.rf_line import _stripline_z0

    assert _stripline_z0(0.5554, 1.016, 3.66) == pytest.approx(ref, rel=1e-9)
    # 渲染几何口径：中面带 b=2·h（render_tl _stripline_lines）
    assert abs(1.016 - 2 * 0.508) < 1e-12
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["value"] == rec.value  # domain null 恒域内


def test_stripline_eps_eff_tem_identity() -> None:
    aid = "stripline.eps_eff.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    # 均匀填充 TEM 恒等：εeff = εr（模板基板名义）
    assert rec.value == pytest.approx(3.66)
    assert _meta("stripline").get("substrate", {}).get("er", 3.66) == 3.66


# ── 4. slotline：Janaswamy-Schaubert 1986 式 (9) 逐项转录 ───────────────────

def _slotline_z0_eq9(w_mm: float, d_mm: float, er: float,
                     f_ghz: float) -> float:
    """式 (9)（2.22≤εr≤3.8 窄槽段）第二实现（模块 docstring 逐字转抄）。"""
    lam0 = _C0 / (f_ghz * 1e9)
    w_d = w_mm / d_mm
    d_l = d_mm * 1e-3 / lam0
    w_l = w_mm * 1e-3 / lam0
    ln_er = math.log(er)
    return (60.0
            + 3.69 * math.sin((er - 2.22) * math.pi / 2.36)
            + 133.5 * math.log(10.0 * er) * math.sqrt(w_l)
            + 2.81 * (1.0 - 0.011 * er * (4.48 + ln_er)) * w_d
            * math.log(100.0 * d_l)
            + 131.1 * (1.028 - ln_er) * math.sqrt(d_l)
            + 12.48 * (1.0 + 0.18 * ln_er) * w_d
            / math.sqrt(er - 2.06 + 0.85 * w_d * w_d))


def test_slotline_z0_eq9_transcription() -> None:
    aid = "slotline.z0_ohm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    ref = _slotline_z0_eq9(1.0, 1.524, 3.66, 2.5)
    assert rec.value == pytest.approx(ref, abs=1e-4)
    from rfauto.core.slotline import slotline_z0

    assert slotline_z0(1.0, 1.524, 3.66, 2.5) == pytest.approx(ref, rel=1e-9)
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.5})
    assert res["hit"] and res["domain_ok"]


# ── 5. siw：Cassivi w_eff × TE10 截止双文献链 ───────────────────────────────

def test_siw_fc_te10_dual_chain() -> None:
    aid = "siw.fc_te10_ghz.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    meta = _meta("siw")
    nom = meta["nominal_params"]
    # 独立重算（全算术双链）：w_eff = w − d²/(0.95·s)；fc = c/(2·w_eff·√εr)
    w_eff = nom["w_mm"] - nom["d_mm"] ** 2 / (0.95 * nom["s_mm"])
    fc = _C0 / (2.0 * w_eff * 1e-3 * math.sqrt(nom["er"])) / 1e9
    assert fc == pytest.approx(6.66669473, abs=1e-7)  # =f0/1.5 设计点
    assert rec.value == pytest.approx(fc, abs=1e-4)
    # 内核链同值
    from rfauto.core.calc_families.slotline_siw import (
        siw_beta_rad_m,
        siw_effective_width_mm,
    )

    weff_k = siw_effective_width_mm(nom["w_mm"], nom["d_mm"], nom["s_mm"])
    assert weff_k == pytest.approx(w_eff, abs=5e-5)
    _, fc_k = siw_beta_rad_m(weff_k, nom["er"], 10.0)
    assert fc_k == pytest.approx(fc, rel=1e-9)
    res = _live().resolve_anchor(aid, {"f0_ghz": 10.0})
    assert res["hit"] and res["domain_ok"]


# ── 6. monopole：λ0/4 像理论设计恒等 ────────────────────────────────────────

def test_monopole_lambda_quarter_identity() -> None:
    aid = "monopole.mon_len_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    assert rec.value == pytest.approx(_C0 / (4.0 * 2.4e9) * 1e3, abs=1e-4)
    assert _meta("monopole")["nominal_params"]["mon_len_mm"] == rec.value
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.4})
    assert res["hit"] and res["domain_ok"]


# ── 7. coil_nfc：Mohan JSSC 1999 current-sheet 逐项转录 ─────────────────────

def _mohan_current_sheet_square(n: float, d_out_m: float, w_m: float,
                                s_m: float) -> float:
    """Mohan current-sheet（Table II square：c1..c4=1.27/2.07/0.18/0.13）
    第二实现（常数自测试内转录，不 import 内核系数表）。"""
    mu0 = 4.0e-7 * math.pi
    d_in = d_out_m - 2.0 * n * w_m - 2.0 * (n - 1.0) * s_m
    d_avg = 0.5 * (d_out_m + d_in)
    rho = (d_out_m - d_in) / (d_out_m + d_in)
    c1, c2, c3, c4 = 1.27, 2.07, 0.18, 0.13
    return (c1 * mu0 * n * n * d_avg / 2.0
            * (math.log(c2 / rho) + c3 * rho + c4 * rho * rho))


def test_coil_nfc_current_sheet_transcription() -> None:
    aid = "coil_nfc.l_uh.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("coil_nfc")["nominal_params"]
    ref_uh = _mohan_current_sheet_square(
        float(nom["n_turns"]), nom["d_out_mm"] * 1e-3, nom["w_mm"] * 1e-3,
        nom["s_mm"] * 1e-3) * 1e6
    assert ref_uh == pytest.approx(2.931054, abs=1e-5)
    assert rec.value == pytest.approx(ref_uh, abs=1e-4)
    # 内核同值
    from rfauto.core.nfc_coil import CoilGeometry, evaluate_coil

    geom = CoilGeometry(shape="square", n_turns=float(nom["n_turns"]),
                        d_out_m=nom["d_out_mm"] * 1e-3,
                        w_m=nom["w_mm"] * 1e-3, s_m=nom["s_mm"] * 1e-3)
    assert evaluate_coil(geom).l_h["current_sheet"] * 1e6 == \
        pytest.approx(ref_uh, rel=1e-9)


# ── 8. pyramid_horn：最优 σ 设计方程 + 文献常数钉 ───────────────────────────

def test_pyramid_horn_gain_design_point() -> None:
    aid = "pyramid_horn.gain_db.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("pyramid_horn")["nominal_params"]
    from rfauto.core.horn_synthesis import horn_gain_direct

    out = horn_gain_direct(
        a_mm=nom["a_mm"], b_mm=nom["b_mm"], a1_mm=nom["a1_mm"],
        b1_mm=nom["b1_mm"], l_mm=nom["l_flare_mm"], f_ghz=10.0)
    # 设计点恒等：最优 σ 设计方程解 = 15dB（roundtrip 内核钉）
    assert out["gain_db"] == pytest.approx(rec.value, abs=1e-6)
    assert rec.value == 15.0
    # #118 文献常数钉（Balanis 最优厚度档）：σh=√1.5、σe=1、δh=3λ/8、δe=λ/4
    lam_mm = _C0 / 10e9 * 1e3
    assert out["sigma_h"] == pytest.approx(math.sqrt(1.5), rel=1e-9)
    assert out["sigma_e"] == pytest.approx(1.0, rel=1e-9)
    assert out["delta_h_over_lambda"] == pytest.approx(0.375, rel=1e-9)
    assert out["delta_e_over_lambda"] == pytest.approx(0.25, rel=1e-9)
    assert out["lambda_mm"] == pytest.approx(lam_mm, rel=1e-9)
    # 第二路径互证（Balanis 最优喇叭近似口径效率 0.51）：带内一致 ≤0.05dB
    a_m, b_m = nom["a1_mm"] * 1e-3, nom["b1_mm"] * 1e-3
    approx_db = 10.0 * math.log10(
        4.0 * math.pi * 0.51 * a_m * b_m / (lam_mm * 1e-3) ** 2)
    assert abs(approx_db - rec.value) <= 0.05
    res = _live().resolve_anchor(aid, {"f_ghz": 10.0})
    assert res["hit"] and res["domain_ok"]


# ── 9. 注册表形态钉（#122：analytic 档与引擎档可区分）───────────────────────

@pytest.mark.parametrize("aid", _X5_ANCHOR_IDS)
def test_x5_anchor_registry_shape(aid: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    # analytic 档形态（XA-10 helper 规范形；引擎档 calibrated∈{openems,
    # hfss, mmt, quasistatic_fd} 可区分）
    assert rec.kind == "constant"
    assert rec.raw["engine_pair"] == {"calibrated": "closedform",
                                      "referee": None}
    # 真机首判前如实 experimental；G-13 首判回填后按判据演进
    # （W7-A：PASS→active 原地翻转，awaiting_data「data 回填后翻 active」
    # 头部先例同族；FAIL/INCONCLUSIVE 留 experimental）。
    assert rec.status in ("experimental", "active")
    assert rec.fallback == "closed_form"
    assert rec.raw["uncertainty"]["kind"] in ("identity", "rounding_band")
    # anchor_id 首段 = template_family 单族
    assert rec.template_family == [aid.split(".")[0]]
    # quantity.name 缺省构词
    fam, qty = aid.split(".")[0], aid.split(".")[1]
    assert rec.raw["quantity"]["name"] == f"{fam}_{qty}"


def test_x5_batch_count_and_expected_source_sync() -> None:
    # 单源对账（#231）：整册与 EXPECTED_ANCHORS 一致由
    # test_anchors_store_service 钉；此处钉 X5 批 13 席全在册
    live = _live()
    for aid in _X5_ANCHOR_IDS:
        assert aid in live, aid
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert len(_X5_ANCHOR_IDS) == 13
    assert all(a in EXPECTED_ANCHORS for a in _X5_ANCHOR_IDS)
