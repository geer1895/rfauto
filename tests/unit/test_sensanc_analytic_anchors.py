"""架构批 SENS-ANC analytic 锚第三批回归钉（10 锚十族；#118 独立重算）。

锚册：knowledge/anchors.yaml 架构批 SENS-ANC 复核扩批（2026-10-14，
46→56 有锚族）——loop/slot/ifa/lange/cline_coupler/branchline_2sect/via/
ms_mushroom/ms_jcross/ms_patch 十族闭式恒等锚（verdict 语义=闭式推导档，
真机首判窗随各卡 semantics）。

本文件每锚两类钉（#118 禁同源自证，test_x5_analytic_anchors 同制度）：
1. **独立重算钉**：文献恒等式/经典公式在测试内**第二实现转录**（L/C/εeff
   公式逐项重写，不 import 内核公式/系数表），与锚值对拍；内核值另与第二
   实现对拍（抓转录/回归错）；
2. **注册表钉**：resolve_anchor 域内命中、analytic 档形态=engine_pair.
   calibrated="closedform"（与引擎档可区分，#122）。

候选裁决策（dipole/pifa/helix/mline/ms_ring_patch/wstep/tjunc/bend/
slotline_lumped 不立锚的理由）见 内部证据目录 第三节。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from rfauto.infra.anchors_store import load_anchors

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: SENS-ANC 批 10 锚 id（与 EXPECTED_ANCHORS 批注同步维护）
_SENSANC_ANCHOR_IDS = (
    "loop.loop_side_mm.closedform-v1",
    "slot.slot_l_mm.closedform-v1",
    "ifa.ifa_arm_mm.closedform-v1",
    "lange.finger_len_mm.closedform-v1",
    "cline_coupler.coupled_len_mm.closedform-v1",
    "branchline_2sect.sect_len_mm.closedform-v1",
    "via.z_antipad_ohm.closedform-v1",
    "ms_mushroom.f_amc_ghz.closedform-v1",
    "ms_jcross.f0_ghz.closedform-v1",
    "ms_patch.f0_ghz.closedform-v1",
)

_C0 = 299792458.0
_C_MM_GHZ = 299.792458
_MU0 = 4.0e-7 * math.pi
_EPS0 = 8.854187817e-12  # metasurface_lut.EPS0_F_M 同值转录（非 import）


def _live():
    return load_anchors()


def _meta(template: str) -> dict:
    p = _REPO_ROOT / "docs" / "templates" / template / "meta.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ── 1. loop：全波环 C=4a≈λ0 纯算术恒等 ──────────────────────────────────────

def test_loop_lambda_quarter_identity() -> None:
    aid = "loop.loop_side_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    exact = _C_MM_GHZ / (4.0 * 2.4)
    assert exact == pytest.approx(31.228381, abs=5e-7)
    assert rec.value == pytest.approx(exact, abs=5e-5)
    assert _meta("loop")["nominal_params"]["loop_side_mm"] == rec.value
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.4})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


# ── 2. slot：Booker 对偶 + 半空间均值 εeff=(1+εr)/2 纯算术恒等 ───────────────

def test_slot_booker_halfspace_identity() -> None:
    aid = "slot.slot_l_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    eps_half = 0.5 * (1.0 + 3.66)
    exact = _C_MM_GHZ / (2.0 * 2.4 * math.sqrt(eps_half))
    assert exact == pytest.approx(40.916785, abs=5e-7)
    assert rec.value == pytest.approx(exact, abs=5e-5)
    assert _meta("slot")["nominal_params"]["slot_l_mm"] == rec.value
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.4})
    assert res["hit"] and res["domain_ok"]


# ── 3. ifa：λ/4 恒等 + εeff 链双路线（ratrace.r_ring_mm 先例）───────────────

def test_ifa_lambda_quarter_chain() -> None:
    aid = "ifa.ifa_arm_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("ifa")["nominal_params"]
    assert nom["ifa_arm_mm"] == rec.value
    # 路线一（算术）：锚值 × εeff → 回代 f0=2.4（εeff 走内核 bare-HJ 正算）
    from rfauto.core.synthesis import Stackup, forward_z0

    _, eps_eff = forward_z0(nom["ifa_w_mm"], 2.4,
                            Stackup(name="ifa", epsilon_r=3.66,
                                    thickness_mm=0.508))
    f0_implied = _C_MM_GHZ / (4.0 * rec.value * math.sqrt(eps_eff))
    assert f0_implied == pytest.approx(2.4, rel=5e-5)
    # 路线二（内核）：设计精确逆新鲜回代（fake 与 openems_templates 同单源）
    from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

    assert antenna2_resonance_ghz("ifa", dict(nom), eps_eval_ghz=2.4,
                                  er=3.66, h_mm=0.508) == pytest.approx(
        2.4, rel=1e-4)
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.4})
    assert res["hit"] and res["domain_ok"]


# ── 4/5. lange / cline_coupler：λ/4 @KJ 偶/奇模平均填充（implied-εeff 双路线）─

@pytest.mark.parametrize("aid,tpl", [
    ("lange.finger_len_mm.closedform-v1", "lange"),
    ("cline_coupler.coupled_len_mm.closedform-v1", "cline_coupler"),
])
def test_coupled_len_lambda_quarter_kj_chain(aid: str, tpl: str) -> None:
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta(tpl)["nominal_params"]
    assert nom[
        "finger_len_mm" if tpl == "lange" else "coupled_len_mm"] == rec.value
    # 路线一（算术）：锚值反解 implied εeff_avg，与 KJ 正算对拍（rel 5e-4，
    # w 4 位舍入传播带；ratrace.r_ring_mm 同形）
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    _ze, _zo, ee, eo = coupled_microstrip_even_odd_ohm(
        nom["w_mm"], nom["gap_mm"], 2.5, 3.66, 0.508)
    lam_quarter = 4.0 * rec.value  # 名义 λ/4 几何长
    eps_implied = (_C_MM_GHZ / (2.5 * lam_quarter)) ** 2
    assert eps_implied == pytest.approx(0.5 * (ee + eo), rel=5e-4)
    # 路线二（内核）：KJ 平均 εeff 正算回代 f0=2.5
    f0 = _C_MM_GHZ / (lam_quarter * math.sqrt(0.5 * (ee + eo)))
    assert f0 == pytest.approx(2.5, rel=5e-5)
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.5})
    assert res["hit"] and res["domain_ok"]


# ── 6. branchline_2sect：主线节 λ/4 @bare-HJ εeff(w_main)=2.85785 ────────────

def test_branchline_2sect_sect_len_chain() -> None:
    aid = "branchline_2sect.sect_len_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("branchline_2sect")["nominal_params"]
    assert nom["sect_len_mm"] == rec.value
    # 文献恒等式（Pozar branch-line 主线节 θ=90°）：L=λ0/(4√εeff)；
    # εeff=2.85785（bare-HJ @w_main，meta param_semantics 2.8579 同值钉）
    from rfauto.core.synthesis import Stackup, forward_z0

    _, eps_eff = forward_z0(nom["w_main_mm"], 2.5,
                            Stackup(name="branchline_2sect",
                                    epsilon_r=3.66, thickness_mm=0.508))
    assert eps_eff == pytest.approx(2.8580, abs=5e-4)
    exact = _C_MM_GHZ / (4.0 * 2.5 * math.sqrt(eps_eff))
    assert exact == pytest.approx(17.733771, abs=5e-7)
    assert rec.value == pytest.approx(exact, abs=5e-5)
    res = _live().resolve_anchor(aid, {"f0_ghz": 2.5})
    assert res["hit"] and res["domain_ok"]


# ── 7. via：反焊盘同轴对数律 (60/√εr)·ln(b/a) 纯算术 ─────────────────────────

def test_via_antipad_coax_log_law() -> None:
    aid = "via.z_antipad_ohm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("via")["nominal_params"]
    exact = 60.0 / math.sqrt(3.66) * math.log(
        nom["antipad_mm"] / nom["r_via_mm"])
    assert exact == pytest.approx(52.500090, abs=5e-7)
    assert rec.value == pytest.approx(exact, abs=1e-3)
    # domain null 恒域内（stripline.z0_ohm 先例）
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["value"] == rec.value


# ── 8. ms_mushroom：Sievenpiper LC 链逐项转录（coil_nfc Mohan 先例同制度）────

def _amc_f0_ref_ghz(period_mm: float, gap_mm: float, er: float,
                    h_mm: float) -> float:
    """f=1/(2π√(LC)) 第二实现：L=μ0·h（Sievenpiper 1999）、
    C=(2D/π)ε0·εeff·ln(csc(πg/2D))（Luukkonen/Costa eq.4）、
    εeff=(1+εr)/2（eq.3）。常数自测试内转录，不 import 内核。"""
    d, g, h = period_mm * 1e-3, gap_mm * 1e-3, h_mm * 1e-3
    l_via = _MU0 * h
    eps_eff = 0.5 * (1.0 + er)
    c_gap = (2.0 * d / math.pi) * _EPS0 * eps_eff * math.log(
        1.0 / math.sin(math.pi * g / (2.0 * d)))
    return 1.0 / (2.0 * math.pi * math.sqrt(l_via * c_gap)) / 1e9


def test_ms_mushroom_amc_lc_transcription() -> None:
    aid = "ms_mushroom.f_amc_ghz.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("ms_mushroom")["nominal_params"]
    ref = _amc_f0_ref_ghz(nom["period_mm"], nom["gap_mm"], nom["er"],
                          nom["h_mm"])
    assert ref == pytest.approx(9.9999284, abs=1e-6)
    assert rec.value == pytest.approx(ref, abs=1e-3)
    # 内核链同值
    from rfauto.core.amc_mushroom import (
        amc_gap_capacitance_f,
        amc_resonance_hz,
        amc_via_inductance_h,
    )

    l_k = amc_via_inductance_h(nom["h_mm"] * 1e-3)
    c_k = amc_gap_capacitance_f(nom["period_mm"] * 1e-3,
                                nom["gap_mm"] * 1e-3,
                                0.5 * (1.0 + nom["er"]))
    assert amc_resonance_hz(l_k, c_k) / 1e9 == pytest.approx(ref, rel=1e-9)
    res = _live().resolve_anchor(aid, {"f0_ghz": 10.0})
    assert res["hit"] and res["domain_ok"]


# ── 9. ms_jcross：λg/4 主缝 + 半空间均值纯算术 ───────────────────────────────

def test_ms_jcross_slot_quarter_wave_identity() -> None:
    aid = "ms_jcross.f0_ghz.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("ms_jcross")["nominal_params"]
    eps_half = 0.5 * (1.0 + nom["er"])
    exact = _C_MM_GHZ / (4.0 * nom["slot_len_mm"] * math.sqrt(eps_half))
    assert exact == pytest.approx(10.000029, abs=5e-7)
    assert rec.value == pytest.approx(exact, abs=1e-3)
    res = _live().resolve_anchor(aid, {"f0_ghz": 10.0})
    assert res["hit"] and res["domain_ok"]


# ── 10. ms_patch：Balanis 腔模型 λ/2 + Hammerstad εeff 不动点转录 ────────────

def _hammerstad_eps_eff(w_mm: float, er: float, h_mm: float) -> float:
    """Hammerstad 薄板 εeff 闭式第二实现（薄微带经典式，非 import）。"""
    return ((er + 1.0) / 2.0
            + (er - 1.0) / 2.0 / math.sqrt(1.0 + 12.0 * h_mm / w_mm))


def _ms_patch_px_ref_mm(f0_ghz: float, er: float, h_mm: float) -> float:
    """方贴片谐振边长不动点第二实现：px=λ0/(2√εeff(px)) 自洽迭代。"""
    lam0_mm = _C_MM_GHZ / f0_ghz
    w = lam0_mm / (2.0 * math.sqrt((er + 1.0) / 2.0))
    for _ in range(16):
        w = lam0_mm / (2.0 * math.sqrt(_hammerstad_eps_eff(w, er, h_mm)))
    return w


def test_ms_patch_cavity_fixed_point_transcription() -> None:
    aid = "ms_patch.f0_ghz.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("ms_patch")["nominal_params"]
    px_ref = _ms_patch_px_ref_mm(10.0, nom["er"], nom["h_mm"])
    assert px_ref == pytest.approx(8.5405675, abs=1e-6)
    # 名义边长=不动点 4 位舍入；回代恒等式 f0=10.0
    assert nom["px_mm"] == pytest.approx(px_ref, abs=5e-5)
    f0 = _C_MM_GHZ / (2.0 * nom["px_mm"]
                      * math.sqrt(_hammerstad_eps_eff(nom["px_mm"], nom["er"],
                                                      nom["h_mm"])))
    assert f0 == pytest.approx(10.0, abs=1e-3)
    assert rec.value == pytest.approx(10.0, abs=1e-6)
    # 内核不动点同值
    from rfauto.core.metasurface_lut import ms_patch_resonant_len_mm

    assert ms_patch_resonant_len_mm(10.0, nom["er"], nom["h_mm"]) == \
        pytest.approx(px_ref, rel=1e-9)
    res = _live().resolve_anchor(aid, {"f0_ghz": 10.0})
    assert res["hit"] and res["domain_ok"]


# ── 注册表形态钉（#122：analytic 档与引擎档可区分）───────────────────────────

@pytest.mark.parametrize("aid", _SENSANC_ANCHOR_IDS)
def test_sensanc_anchor_registry_shape(aid: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    assert rec.kind == "constant"
    assert rec.raw["engine_pair"] == {"calibrated": "closedform",
                                      "referee": None}
    # 真机首判前如实 experimental（X5 批同制度）
    assert rec.status == "experimental"
    assert rec.fallback == "closed_form"
    assert rec.raw["uncertainty"]["kind"] in ("identity", "rounding_band")
    assert rec.raw.get("layer") == "closure"
    # anchor_id 首段 = template_family 单族
    assert rec.template_family == [aid.split(".")[0]]
    # quantity.name 缺省构词
    fam, qty = aid.split(".")[0], aid.split(".")[1]
    assert rec.raw["quantity"]["name"] == f"{fam}_{qty}"


def test_sensanc_batch_count_and_expected_source_sync() -> None:
    # 单源对账（#231）：整册与 EXPECTED_ANCHORS 一致由
    # test_anchors_store_service 钉；此处钉 SENS-ANC 批 10 席全在册
    live = _live()
    for aid in _SENSANC_ANCHOR_IDS:
        assert aid in live, aid
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert len(_SENSANC_ANCHOR_IDS) == 10
    assert all(a in EXPECTED_ANCHORS for a in _SENSANC_ANCHOR_IDS)
