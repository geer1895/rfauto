"""aurora_e W3-S15 analytic 锚续批回归钉（3 锚+1 接替版四族；#118 独立重算）。

锚册：knowledge/anchors.yaml aurora_e W3-S15 批（2026-10-18，75→79 锚、
有锚族 60/72→64/72）——

- ``ms_lattice.period_mm.closedform-v2``：ANCH-D v1 族名注册缺陷接替
  （v1 template_family=[ms_lattice] 非 TEMPLATE_META 族、按名解析零命中
  且与 ANCH-D 自身测试钉矛盾——本批开工时 test_anchd_analytic_anchors
  三红在树实证；v2 换真名三族 [ms_patch,ms_ring_patch,ms_array_NxN]，
  值/域/不确定度零改动，v1 retired+superseded_by 留档）；
- ``tjunc.s11_db/s21_db.closedform-v1``：等臂无损对称三端口结点恒等式
  （S=(1/3)[[-1,2,2],[2,-1,2],[2,2,-1]]——render_tl._tjunc_lines 头注
  在树锚判据；SENS-ANC/ANCH-D 弃选理由只针对 HJ 宽度/Z0 面，结点 S 面
  阻抗无关网络理论系独立新面）；
- ``mline.z0_ohm.closedform-v1``：HJ 系数原文核验清偿 X5/W4-E 两批
  citation-rot 缓登记项（系数双源=原文引述+skrf mline 源码逐位一致，
  2026-10-18）。

本文件每锚两类钉（#118 禁同源自证，X5/SENS-ANC/ANCH-D 同制度）：
1. **独立重算钉**：文献恒等式在测试内**第二实现转录**（纯算术/闭式重写，
   不 import 内核公式），与锚值对拍；内核设计链另与第二实现对拍；
2. **注册表钉**：resolve_anchor 域内命中、analytic 档形态=engine_pair.
   calibrated="closedform"（与引擎档可区分，#122）、v1→v2 演进钉。

弃选维持（本批复核，逐族理由沿判读报告归档不变）：
bend/tjunc 宽度面/wstep/dipole/pifa/helix/embedded_ms/msl_slot_transition/
slotline_lumped 共 9 族仍零锚（tjunc 本批只立结点 S 面双锚）——任务书
"8-12 模板"前提与树面两轮评审弃选账的差额如实报告（W3-S15 返回账）。
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from rfauto.infra.anchors_store import load_anchors

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: W3-S15 批新增锚 id（与 EXPECTED_ANCHORS 批注同步维护）
_W3S15_ANCHOR_IDS = (
    "ms_lattice.period_mm.closedform-v2",
    "tjunc.s11_db.closedform-v1",
    "tjunc.s21_db.closedform-v1",
    "mline.z0_ohm.closedform-v1",
)

_C_MM_GHZ = 299.792458
_ETA0 = 376.730313668  # 真空波阻抗（SI 推算值 376.730313668…）


def _live():
    return load_anchors()


def _meta(template: str) -> dict:
    p = _REPO_ROOT / "docs" / "templates" / template / "meta.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ── 1. ms_lattice v2：λ0/2 阵格（纯算术第二实现；v1 演进钉）──────────────────

def test_ms_lattice_v2_halfwave_period_identity() -> None:
    aid = "ms_lattice.period_mm.closedform-v2"
    rec = _live().get(aid)
    assert rec is not None
    # v2 族表=真名三族（v1 缺陷修复的本体）
    assert rec.template_family == ["ms_patch", "ms_ring_patch",
                                   "ms_array_NxN"]
    exact = _C_MM_GHZ / (2.0 * 10.0)          # λ0/2 纯算术（第二实现）
    assert exact == pytest.approx(14.9896229, abs=5e-7)
    assert rec.value == pytest.approx(exact, abs=5e-5)
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


def test_ms_lattice_v1_retired_evolution_pin() -> None:
    """演进钉：v1 retired + superseded_by=v2（锚修订不改历史，册头规则）。"""
    v1 = _live().get("ms_lattice.period_mm.closedform-v1")
    assert v1 is not None
    assert v1.status == "retired"
    assert v1.raw.get("provenance", {}).get("superseded_by") == (
        "ms_lattice.period_mm.closedform-v2")
    # retired 按 resolve 语义一律结构化 fallback（hit=False, reason=retired）
    res = _live().resolve_anchor("ms_lattice.period_mm.closedform-v1",
                                 {"f0_ghz": 10.0})
    assert res["hit"] is False and res["source"] == "fallback"
    assert res["reason"] == "retired"


# ── 2. tjunc：等臂无损三端口结点（网络理论纯算术第二实现）─────────────────────

def _tjunc_node_s() -> list[list[float]]:
    """理想结点 S 第二实现：等臂无损对称三端口（独立于内核转录）。

    导出式（非引用）：并联结点处三线同 Z0，任一口看入 Z0/2 →
    Γ=(Z0/2−Z0)/(Z0/2+Z0)=−1/3；结点电压 (1+Γ)V=2V/3，每出臂得同幅
    出射波 → |Sij|=2/3（i≠j）；功率账 1/9+4/9+4/9=1。
    """
    gamma = (0.5 - 1.0) / (0.5 + 1.0)      # = −1/3
    t = 1.0 + gamma                        # = 2/3（结点出射波幅度）
    return [[gamma if i == j else t for j in range(3)] for i in range(3)]


def test_tjunc_node_matrix_unitary_reciprocal() -> None:
    """导出式自洽钉：S=结点矩阵 幺正+互易+对角 −1/3（功率账恒等）。"""
    s = _tjunc_node_s()
    # 对角=−1/3、非对角=2/3
    for i in range(3):
        for j in range(3):
            expect = -1.0 / 3.0 if i == j else 2.0 / 3.0
            assert s[i][j] == pytest.approx(expect, abs=1e-15)
    # 幺正（无损）：Σ_k |S_ki|² = 1
    for i in range(3):
        p = sum(s[k][i] ** 2 for k in range(3))
        assert p == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("aid,ref_db", [
    ("tjunc.s11_db.closedform-v1", 20.0 * math.log10(1.0 / 3.0)),
    ("tjunc.s21_db.closedform-v1", 20.0 * math.log10(2.0 / 3.0)),
])
def test_tjunc_sparam_db_identities(aid: str, ref_db: float) -> None:
    rec = _live().get(aid)
    assert rec is not None
    assert rec.template_family == ["tjunc"]
    assert rec.value == pytest.approx(ref_db, abs=5e-7)
    # 内核裁判同型（fake_adapter node 矩阵 /3——只比对形态不 import 公式）
    import numpy as np

    from rfauto.adapters.fake_adapter import _tjunc_sparams

    f = np.array([10.0])
    # 结点同型：理想线长 0 时退化回结点矩阵（arm 长 0 无线级联）
    s0 = _tjunc_sparams(f, z_arm=50.0, eps_eff=1.0, through_len_mm=0.0,
                        branch_len_mm=0.0, tan_d=0.0)
    assert abs(s0[0, 0, 0]) == pytest.approx(1.0 / 3.0, abs=1e-12)
    assert abs(s0[0, 1, 0]) == pytest.approx(2.0 / 3.0, abs=1e-12)
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


# ── 3. mline：HJ 50Ω 恒等（系数原文核验第二实现）─────────────────────────────

def _hj_z0_er_eff(w_mm: float, h_mm: float, er: float,
                  ) -> tuple[float, float]:
    """Hammerstad-Jensen 1980 准静态第二实现（系数经原文引述+skrf 源码双源
    核验，2026-10-18；不 import skrf/内核公式）。"""
    u = w_mm / h_mm
    fu = 6.0 + (2.0 * math.pi - 6.0) * math.exp(-(30.666 / u) ** 0.7528)
    z0_air = (_ETA0 / 2.0 / math.pi) * math.log(
        fu / u + math.sqrt(1.0 + (2.0 / u) ** 2))
    a = (1.0 + math.log((u ** 4 + (u / 52.0) ** 2) / (u ** 4 + 0.432)) / 49.0
         + math.log(1.0 + (u / 18.1) ** 3) / 18.7)
    b = 0.564 * ((er - 0.9) / (er + 3.0)) ** 0.053
    er_eff = (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * (1.0 + 10.0 / u) ** (
        -a * b)
    return z0_air / math.sqrt(er_eff), er_eff


def test_mline_z0_roundtrip_identity() -> None:
    aid = "mline.z0_ohm.closedform-v1"
    rec = _live().get(aid)
    assert rec is not None
    assert rec.template_family == ["mline"]
    assert rec.value == 50.0
    # 内核链：nominal_width_mm(50) 单源 → forward 回代自洽（49.99999）
    from rfauto.core.synthesis import Stackup, forward_z0, nominal_width_mm

    stackup = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w = nominal_width_mm(50.0, 2.5, "rogers4350b_h0.508")
    assert w == pytest.approx(1.1134, abs=5e-5)
    z0_kernel = forward_z0(w, 2.5, stackup).z0
    assert z0_kernel == pytest.approx(50.0, abs=5e-4)
    # #118 独立第二源：HJ 准静态转录（系数核验版）带内（±0.05Ω 包络）
    z0_ref, _er_eff_ref = _hj_z0_er_eff(w, stackup.thickness_mm,
                                        stackup.epsilon_r)
    assert z0_ref == pytest.approx(50.0, abs=0.05)
    assert z0_kernel == pytest.approx(z0_ref, abs=0.05)
    res = _live().resolve_anchor(aid, {})
    assert res["hit"] and res["domain_ok"] and res["value"] == rec.value


# ── 4. 注册表形态钉（#122：analytic 档与引擎档可区分）────────────────────────

@pytest.mark.parametrize("aid", _W3S15_ANCHOR_IDS)
def test_w3s15_anchor_registry_shape(aid: str) -> None:
    rec = _live().get(aid)
    assert rec is not None, aid
    assert rec.kind == "constant"
    assert rec.raw["engine_pair"] == {"calibrated": "closedform",
                                      "referee": None}
    # 真机首判前如实 experimental（X5/SENS-ANC/ANCH-D 批同制度）
    assert rec.status == "experimental"
    assert rec.fallback == "closed_form"
    assert rec.raw["uncertainty"]["kind"] in ("identity", "rounding_band")
    assert rec.raw.get("layer") == "closure"
    parts = aid.split(".")
    assert rec.raw["quantity"]["name"] == f"{parts[0]}_{parts[1]}"
    from rfauto.adapters.oe_templates.registry import TEMPLATE_META

    assert all(fam in TEMPLATE_META for fam in rec.template_family)


def test_w3s15_batch_count_and_expected_source_sync() -> None:
    # 单源对账（#231）：整册与 EXPECTED_ANCHORS 一致由
    # test_anchors_store_service 钉；此处钉 W3-S15 批 4 席全在册+
    # 有锚族覆盖 60/72→64/72（X5 批口径：TEMPLATE_META 族集内计数；
    # v1 retire 前树面实况=60——ms_lattice 族名不解析，ANCH-D 自身
    # 断言 62 三红在树即此账）
    live = _live()
    for aid in _W3S15_ANCHOR_IDS:
        assert aid in live, aid
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert len(_W3S15_ANCHOR_IDS) == 4
    assert all(a in EXPECTED_ANCHORS for a in _W3S15_ANCHOR_IDS)
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
    assert len(covered) == 64  # W3-S15 批 60→64（+4 族：ms_ring_patch/
    # ms_array_NxN=缺陷接替实覆盖、tjunc、mline）
    for fam in ("ms_patch", "ms_ring_patch", "ms_array_NxN", "tjunc",
                "mline"):
        assert fam in covered, fam
