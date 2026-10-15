"""aurora_d ANCH-D analytic 锚第四批回归钉（5 锚六族；#118 独立重算）。

锚册：knowledge/anchors.yaml aurora_d ANCH-D 席扩批（2026-10-14，
56→62 有锚族）——剩余 16 未覆盖模板逐个评估后可立 6 族：
coax_waveguide_transition（TE10 λg/4 背短路恒等）/sma_launcher（同轴 TEM
对数律反解 r_o）/patch_eep_1x4+patch_eep_2x2（共享单元 Balanis W+λ/2 腔 L，
多族单锚=c3.l_via_h 先例）/ms_ring_patch+ms_array_NxN（λ0/2 阵格，与
ms_patch 同常量同规则，多族单锚）。verdict 语义=闭式推导档，真机首判窗随
各卡 semantics（HFSS 仲裁/战役判读属模板面另账）。

本文件每锚两类钉（#118 禁同源自证，test_sensanc_analytic_anchors/
test_x5_analytic_anchors 同制度）：
1. **独立重算钉**：文献恒等式/经典公式在测试内**第二实现转录**（TE10
   色散/同轴对数律/Hammerstad εeff·ΔL/λ0/2 算术逐项重写，不 import 内核
   公式），与锚值对拍；内核设计链另与第二实现对拍（抓转录/回归错）；
2. **注册表钉**：resolve_anchor 域内命中、analytic 档形态=engine_pair.
   calibrated="closedform"（与引擎档可区分，#122）。

弃选 10 族（bend/tjunc/wstep/mline=唯一闭式面是 HJ 宽度本身；dipole/
pifa/helix/embedded_ms/msl_slot_transition/slotline_lumped=引擎/文献面
缺失或公式族重复）逐族理由见 runs/aurora_d_anchd/REPORT.md（SENS-ANC
报告第三节同口径复核）。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from rfauto.infra.anchors_store import load_anchors

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: ANCH-D 批 5 锚 id（与 EXPECTED_ANCHORS 批注同步维护）
_ANCHD_ANCHOR_IDS = (
    "coax_waveguide_transition.backshort_mm.closedform-v1",
    "sma_launcher.r_o_mm.closedform-v1",
    "patch_eep.elem_w_mm.closedform-v1",
    "patch_eep.elem_len_mm.closedform-v1",
    "ms_lattice.period_mm.closedform-v1",
)

_C_MM_GHZ = 299.792458


def _live():
    return load_anchors()


def _meta(template: str) -> dict:
    p = _REPO_ROOT / "docs" / "templates" / template / "meta.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ── 1. coax_waveguide_transition：TE10 λg/4 背短路（Pozar Ch.3 色散转录）─────

def _te10_backshort_ref_mm(a_mm: float, f0_ghz: float) -> float:
    """TE10 色散第二实现：fc10=c/(2a)、λg=λ0/√(1−(fc/f0)²)、backshort=λg/4。"""
    fc10 = _C_MM_GHZ / (2.0 * a_mm)
    lam0 = _C_MM_GHZ / f0_ghz
    lam_g = lam0 / math.sqrt(1.0 - (fc10 / f0_ghz) ** 2)
    return lam_g / 4.0


def test_coax_wg_backshort_te10_identity() -> None:
    aid = "coax_waveguide_transition.backshort_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("coax_waveguide_transition")["nominal_params"]
    ref = _te10_backshort_ref_mm(nom["a_mm"], 10.0)
    assert ref == pytest.approx(9.926779802778025, abs=5e-12)
    # 名义=设计规则全精度直存（无舍入），锚值逐位恒等
    assert nom["backshort_mm"] == pytest.approx(ref, abs=5e-12)
    assert rec.value == pytest.approx(ref, abs=5e-12)
    # 内核设计规则同值（路线一：coax_wg_design_params 单源）
    from rfauto.adapters.oe_templates.render_coax_wg import (
        coax_wg_design_params,
    )

    assert coax_wg_design_params()["backshort_mm"] == pytest.approx(
        ref, abs=5e-12)
    res = _live().resolve_anchor(aid, {"f0_ghz": 10.0})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


# ── 2. sma_launcher：同轴 TEM 对数律反解 r_o（via 先例同式异模板）────────────

def _coax_ro_ref_mm(ri_mm: float, z0_ohm: float, er: float) -> float:
    """同轴对数律反解第二实现：r_o = r_i·exp(Z0·√εr/60)（TEM 闭式）。"""
    return ri_mm * math.exp(z0_ohm * math.sqrt(er) / 60.0)


def test_sma_launcher_r_o_coax_log_law() -> None:
    aid = "sma_launcher.r_o_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    nom = _meta("sma_launcher")["nominal_params"]
    ref = _coax_ro_ref_mm(nom["r_i_mm"], 50.0, nom["er_fill"])
    assert ref == pytest.approx(2.124389461288955, abs=5e-7)
    assert nom["r_o_mm"] == pytest.approx(ref, abs=5e-5)
    assert rec.value == pytest.approx(ref, abs=5e-5)
    # 第二路线（正算）：舍入几何回代 Z0=(60/√εr)·ln(b/a)=50.000205
    z_implied = (60.0 / math.sqrt(nom["er_fill"]) * math.log(
        nom["r_o_mm"] / nom["r_i_mm"]))
    assert z_implied == pytest.approx(50.000205, abs=5e-6)
    # 内核综合链同值（synthesize_sma_launcher_model 单源）
    from rfauto.core.synthesis import synthesize_sma_launcher_model

    out = synthesize_sma_launcher_model(
        50.0, r_i_mm=float(nom["r_i_mm"]), er_fill=float(nom["er_fill"]))
    assert out.params["r_o_mm"] == pytest.approx(ref, abs=5e-5)
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["value"] == rec.value


# ── 3/4. patch_eep 双模板：Balanis 宽度式 + λ/2 腔长（Hammerstad 链转录）─────

def _hammerstad_eps_eff(w_mm: float, er: float, h_mm: float) -> float:
    """Hammerstad 薄板 εeff 闭式第二实现（薄微带经典式，非 import）。"""
    return ((er + 1.0) / 2.0
            + (er - 1.0) / 2.0 / math.sqrt(1.0 + 12.0 * h_mm / w_mm))


def _delta_l_edge_mm(w_mm: float, h_mm: float, eps_eff: float) -> float:
    """Hammerstad 1975 每边缘 ΔL 第二实现（0.412 原式，Pozar eq.4.23 同口径）。"""
    u = w_mm / h_mm
    return (0.412 * h_mm * (eps_eff + 0.3) * (u + 0.264)
            / ((eps_eff - 0.258) * (u + 0.8)))


def _patch_w_ref_mm(f0_ghz: float, er: float) -> float:
    """Balanis Ch.14 宽度式第二实现：W = c/(2f0)·√(2/(εr+1))。"""
    return _C_MM_GHZ / (2.0 * f0_ghz) * math.sqrt(2.0 / (er + 1.0))


def _patch_l_ref_mm(f0_ghz: float, w_mm: float, er: float,
                    h_mm: float) -> float:
    """λ/2 腔长第二实现：L = λ0/(2√εeff) − 4ΔL（每边缘 ΔL×4 总扣=仓内现行
    口径，XA-1 仲裁在档）。"""
    ee = _hammerstad_eps_eff(w_mm, er, h_mm)
    lam_g = _C_MM_GHZ / (f0_ghz * math.sqrt(ee))
    return lam_g / 2.0 - 4.0 * _delta_l_edge_mm(w_mm, h_mm, ee)


@pytest.mark.parametrize("tpl", ["patch_eep_1x4", "patch_eep_2x2"])
def test_patch_eep_elem_w_balanis_identity(tpl: str) -> None:
    aid = "patch_eep.elem_w_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    assert rec.template_family == ["patch_eep_1x4", "patch_eep_2x2"]
    nom = _meta(tpl)["nominal_params"]
    ref = _patch_w_ref_mm(5.8, 3.66)
    assert ref == pytest.approx(16.931083563726638, abs=5e-7)
    assert nom["elem_w_mm"] == pytest.approx(ref, abs=5e-5)
    assert rec.value == pytest.approx(ref, abs=5e-5)
    # 内核单源同值（closedform.array_elem_w_mm）
    from rfauto.adapters.oe_templates.closedform import array_elem_w_mm

    assert array_elem_w_mm(5.8, 3.66) == pytest.approx(ref, rel=1e-12)
    res = _live().resolve_anchor(aid, {"f0_ghz": 5.8})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


@pytest.mark.parametrize("tpl", ["patch_eep_1x4", "patch_eep_2x2"])
def test_patch_eep_elem_len_cavity_chain(tpl: str) -> None:
    aid = "patch_eep.elem_len_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    assert rec.template_family == ["patch_eep_1x4", "patch_eep_2x2"]
    nom = _meta(tpl)["nominal_params"]
    w_ref = _patch_w_ref_mm(5.8, 3.66)
    l_ref = _patch_l_ref_mm(5.8, w_ref, 3.66, 0.508)
    assert l_ref == pytest.approx(12.905820302738958, abs=5e-7)
    assert nom["elem_len_mm"] == pytest.approx(l_ref, abs=5e-5)
    assert rec.value == pytest.approx(l_ref, abs=5e-5)
    # 内核单源同值（closedform.array_elem_len_mm）
    from rfauto.adapters.oe_templates.closedform import array_elem_len_mm

    assert array_elem_len_mm(5.8, w_ref, 3.66, 0.508) == pytest.approx(
        l_ref, rel=1e-12)
    # fake 设计精确逆回代（EEP 单元谐振=patch_resonance_hj_ghz 精确逆，
    # 4 位舍入带内 f0 复原）
    from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

    assert patch_resonance_hj_ghz(
        float(nom["elem_len_mm"]), float(nom["elem_w_mm"]), 3.66, 0.508
    ) == pytest.approx(5.8, rel=5e-5)
    res = _live().resolve_anchor(aid, {"f0_ghz": 5.8})
    assert res["hit"] and res["domain_ok"]


# ── 5. ms_lattice：λ0/2 阵格（ms_patch/ms_ring_patch/ms_array_NxN 三族）──────

def test_ms_lattice_halfwave_period_identity() -> None:
    aid = "ms_lattice.period_mm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    assert rec.template_family == ["ms_patch", "ms_ring_patch",
                                   "ms_array_NxN"]
    exact = _C_MM_GHZ / (2.0 * 10.0)
    assert exact == pytest.approx(14.9896229, abs=5e-7)
    for tpl in ("ms_patch", "ms_ring_patch", "ms_array_NxN"):
        nom = _meta(tpl)["nominal_params"]
        assert nom["period_mm"] == pytest.approx(exact, abs=5e-5)
        assert nom["period_mm"] == rec.value
    # 内核注册面同值（TEMPLATE_NOMINAL 经 _MS_PATCH_NOM_PERIOD 单源）
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    for tpl in ("ms_patch", "ms_ring_patch", "ms_array_NxN"):
        assert TEMPLATE_NOMINAL[tpl]["period_mm"] == rec.value
    res = _live().resolve_anchor(aid, {"f0_ghz": 10.0})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


# ── 注册表形态钉（#122：analytic 档与引擎档可区分）───────────────────────────

@pytest.mark.parametrize("aid", _ANCHD_ANCHOR_IDS)
def test_anchd_anchor_registry_shape(aid: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    assert rec.kind == "constant"
    assert rec.raw["engine_pair"] == {"calibrated": "closedform",
                                      "referee": None}
    # 真机首判前如实 experimental（X5/SENS-ANC 批同制度）
    assert rec.status == "experimental"
    assert rec.fallback == "closed_form"
    assert rec.raw["uncertainty"]["kind"] in ("identity", "rounding_band")
    assert rec.raw.get("layer") == "closure"
    # anchor_id 前两段构词 quantity.name（多族锚首段=规则名，c3.l_via_h 先例）
    parts = aid.split(".")
    assert rec.raw["quantity"]["name"] == f"{parts[0]}_{parts[1]}"
    assert all(fam in {"coax_waveguide_transition", "sma_launcher",
                       "patch_eep_1x4", "patch_eep_2x2", "ms_patch",
                       "ms_ring_patch", "ms_array_NxN"}
               for fam in rec.template_family)


def test_anchd_batch_count_and_expected_source_sync() -> None:
    # 单源对账（#231）：整册与 EXPECTED_ANCHORS 一致由
    # test_anchors_store_service 钉；此处钉 ANCH-D 批 5 席全在册+
    # 有锚族覆盖 56/72→62/72（X5 批口径：TEMPLATE_META 族集内计数）
    live = _live()
    for aid in _ANCHD_ANCHOR_IDS:
        assert aid in live, aid
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert len(_ANCHD_ANCHOR_IDS) == 5
    assert all(a in EXPECTED_ANCHORS for a in _ANCHD_ANCHOR_IDS)
    from rfauto.adapters.openems_templates import TEMPLATE_META

    reg = yaml.safe_load(
        (_REPO_ROOT / "knowledge" / "anchors.yaml").read_text(
            encoding="utf-8"))
    covered = {
        fam
        for entry in reg["anchors"]
        for fam in (entry.get("template_family") or [])
        if fam in TEMPLATE_META
    }
    assert len(covered) == 62  # ANCH-D 批 56→62（+6 族）
    for fam in ("coax_waveguide_transition", "sma_launcher",
                "patch_eep_1x4", "patch_eep_2x2", "ms_ring_patch",
                "ms_array_NxN"):
        assert fam in covered, fam
