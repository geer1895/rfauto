"""Phase 6 W6-F cpw 锚回归钉（用户裁决⑥执行件：条件裁 A=CPWG/50Ω、核验优先）。

裁决材料：runs/w4_phase4/w4e/cpw_ambiguity_evidence.md（W4-E 两候选并列档，
49→59 批时如实缓立）；本批核验 2026-10-05 通过 → 锚 cpw.z0_ohm.closedform-v1
=50.0（CPWG 口径）落 knowledge/anchors.yaml。ANCHORS 单源计数 59→60 由主代理
合流同步（EXPECTED_ANCHORS @ core/anchors.py，席位禁碰——本文件不做计数断言）。

本文件两类钉（#118 禁同源自证，同 test_w4_w4e_anchors.py 范式）：
1. **独立重算钉**：CPWG 共形映射闭式在测试内**第二实现转录**（AGM 椭圆积分
   比，不 import 内核），与锚值对拍；内核另与第二实现对拍（抓转录/回归错）；
   A/B 口径对照钉=同几何 skrf CPW（B）67.44 vs CPWG（A）50.0 差 35% 属参照
   系差，h→∞ 极限两口径收敛（同物理、仅差底地——判别量=εeff）。
2. **渲染几何核验钉**（#212 离线审计：字符串存在性不过瘾，直接渲染管线
   产物断言）：cpw 渲染=中心带+两侧地贯穿全域（render_tl.py:61-62）+底边界
   PEC（render_core.py:1899-1906 MUR 白名单不含 cpw）；fgcpw 对照=MUR 底
   （有限地悬浮）——consumers_note 声明的语义边界机械化。
"""

from __future__ import annotations

import math

import pytest

from rfauto.infra.anchors_store import load_anchors

#: 本批登记的锚 id（单条；计数断言归 test_anchors_store_service+主代理单源）
_CPW_ANCHOR_ID = "cpw.z0_ohm.closedform-v1"

#: cpw 模板名义几何（registry.py TEMPLATE_NOMINAL，#198 CPWG 口径反解）
_NOMINAL = {"w_mm": 0.849, "gap_mm": 0.2, "h_mm": 0.508, "epsilon_r": 3.66}

_ETA0 = 376.730313668  # η0=√(μ0/ε0)（自由空间波阻抗，文献常数）

#: 内核全精度回代值（本会话实算；锚值=2 位舍入惯例带内）
_Z0_FULL = 49.99998158503503
_EPS_FULL = 2.5672930681609403


def _live():
    return load_anchors()


# ── 独立数值件（AGM 椭圆积分比，第二实现；与内核无 import 关系）────────────

def _kk_ratio_agm(k: float) -> float:
    """r=K(k)/K'(k)：k'=√(1−k²) 直取 + AGM 恒等式（K=π/(2·agm(1,k′))）。"""
    kp = math.sqrt(max(1.0 - k * k, 0.0))
    a, b = 1.0, kp
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    agm_kp = 0.5 * (a + b)
    a, b = 1.0, k
    while a - b > 1e-15 * a:
        a, b = 0.5 * (a + b), math.sqrt(a * b)
    return (0.5 * (a + b)) / agm_kp


def _cpwg_ri_ref(w_mm: float, gap_mm: float, h_mm: float,
                 epsilon_r: float) -> tuple[float, float]:
    """CPWG (εeff, Z0) 第二实现（内核 _cpwg_ri docstring 口径逐项转录）。

    C_air=2ε0(r1+r4)、C_tot=2ε0(r1+εr·r4)；εeff=C_tot/C_air；
    Z0=1/(c√(C·C_air))=η0/(2√((r1+εr·r4)(r1+r4)))（η0=1/(ε0·c) 恒等改写）。
    """
    a = w_mm / 2.0
    b = w_mm / 2.0 + gap_mm
    k1 = a / b
    k4 = (math.tanh(math.pi * a / (2.0 * h_mm))
          / math.tanh(math.pi * b / (2.0 * h_mm)))
    r1 = _kk_ratio_agm(k1)
    r4 = _kk_ratio_agm(k4)
    eps_eff = (r1 + epsilon_r * r4) / (r1 + r4)
    z0 = _ETA0 / (2.0 * math.sqrt((r1 + epsilon_r * r4) * (r1 + r4)))
    return eps_eff, z0


# ── 1. 独立重算钉：锚值 50.0 = CPWG 闭式回代（第二实现逐位） ────────────────

def test_cpw_anchor_second_implementation() -> None:
    rec = _live().get(_CPW_ANCHOR_ID)
    assert rec is not None, _CPW_ANCHOR_ID
    eps_ref, z0_ref = _cpwg_ri_ref(**_NOMINAL)
    # 第二实现自检（全精度逐位钉——抓转录错）
    assert z0_ref == pytest.approx(_Z0_FULL, rel=1e-9)
    assert eps_ref == pytest.approx(_EPS_FULL, rel=1e-9)
    # 锚值=round 惯例 50.0，舍入带 0.005 覆盖回代值（suspended_stripline 同形）
    assert rec.value == 50.0
    assert abs(rec.value - z0_ref) <= 0.005
    # 内核对拍（抓内核回归错）
    from rfauto.core.calc_families.rf_line import _cpwg_ri

    eps_k, z0_k = _cpwg_ri(_NOMINAL["w_mm"], _NOMINAL["gap_mm"],
                           _NOMINAL["h_mm"], _NOMINAL["epsilon_r"])
    assert z0_k == pytest.approx(z0_ref, rel=1e-9)
    assert eps_k == pytest.approx(eps_ref, rel=1e-9)
    # 注册表面（domain=null 恒域内命中）
    res = _live().resolve_anchor(_CPW_ANCHOR_ID, {})
    assert res["hit"] and res["value"] == rec.value


def test_cpw_synthesis_chain_nominal_roundtrip() -> None:
    """综合链同源钉：synthesize_cpw_model 缺省反解回代=registry 名义逐位。"""
    from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL
    from rfauto.core.synthesis import synthesize_cpw_model

    r = synthesize_cpw_model()
    assert r.params["w_mm"] == TEMPLATE_NOMINAL["cpw"]["w_mm"] == 0.849
    assert r.params["gap_mm"] == TEMPLATE_NOMINAL["cpw"]["gap_mm"] == 0.2
    eps_k, z0_k = _cpwg_ri_ref(r.params["w_mm"], r.params["gap_mm"],
                               _NOMINAL["h_mm"], _NOMINAL["epsilon_r"])
    assert z0_k == pytest.approx(50.0, abs=0.005)
    assert eps_k == pytest.approx(2.5673, abs=5e-4)


# ── 2. A/B 口径对照钉：B=67.44 是参照系差非物理错；h→∞ 两口径收敛 ───────────

def test_cpw_convention_b_comparison_note_pins() -> None:
    """B 口径数值钉（防 semantics 注记静默腐烂）：skrf CPW 无底地=67.44。"""
    from rfauto.core.calc_families.rf_line import cpw_analysis

    r = cpw_analysis(w_mm=_NOMINAL["w_mm"], gap_mm=_NOMINAL["gap_mm"],
                     freq_ghz=2.5, epsilon_r=_NOMINAL["epsilon_r"],
                     h_mm=_NOMINAL["h_mm"])
    assert r["z0_ohm"] == 67.44
    assert r["eps_eff"] == 2.0895
    # 差 35% 属参照系差：A/B 比 = 67.44/50.0 ≈ 1.349
    assert pytest.approx(1.3488, abs=5e-4) == 67.44 / 50.0


def test_cpw_h_infinity_limit_converges_to_ungrounded_cpw() -> None:
    """h→∞ 极限：CPWG 退化为无地 CPW 无限厚基板（εeff=(1+εr)/2 精确）。"""
    from rfauto.core.calc_families.rf_line import _cpwg_ri, cpw_analysis

    h_big = 1.0e6
    eps_eff, z0 = _cpwg_ri(_NOMINAL["w_mm"], _NOMINAL["gap_mm"], h_big,
                           _NOMINAL["epsilon_r"])
    assert eps_eff == pytest.approx((1.0 + _NOMINAL["epsilon_r"]) / 2.0,
                                    rel=1e-9)
    r = cpw_analysis(w_mm=_NOMINAL["w_mm"], gap_mm=_NOMINAL["gap_mm"],
                     freq_ghz=2.5, epsilon_r=_NOMINAL["epsilon_r"],
                     h_mm=h_big)
    # 两口径同物理（仅差底地）：极限处 Z0 一致（skrf 侧 4 位舍入口径）
    assert z0 == pytest.approx(r["z0_ohm"], rel=5e-4)
    assert eps_eff == pytest.approx(r["eps_eff"], rel=5e-4)


# ── 3. 渲染几何核验钉（#212 离线审计：渲染管线产物直接断言） ────────────────

def _render_cpw_script() -> str:
    from rfauto.adapters.openems_templates import render_script

    return render_script("cpw", {"w_mm": _NOMINAL["w_mm"],
                                 "gap_mm": _NOMINAL["gap_mm"],
                                 "line_len_mm": 40.0}, (2.25, 2.75))


def test_cpw_render_side_grounds_and_bottom_pec() -> None:
    """核验本体（裁决 A 的证据面机械化）：侧地贯穿全域+底边界 PEC。"""
    script = _render_cpw_script()
    # 中心带 + 两侧地（render_tl.py:59/61-62 原文行——地延伸到 ±BOARD 域边）
    assert "cpw.AddBox((-W / 2, Y0, H_SUB), (W / 2, Y1, H_SUB)" in script
    assert ("cpw.AddBox((-BOARD, -BOARD, H_SUB), (-W / 2 - GAP, BOARD, H_SUB)"
            in script)
    assert ("cpw.AddBox((W / 2 + GAP, -BOARD, H_SUB), (BOARD, BOARD, H_SUB)"
            in script)
    # 底边界=z-min 槽位 PEC（第 5 元；六元序 [x0,x1,y0,y1,zmin,zmax]）
    bc_lines = [ln for ln in script.splitlines()
                if "FDTD.SetBoundaryCond" in ln]
    assert bc_lines, "缺 SetBoundaryCond 行"
    for ln in bc_lines:
        slots = ln.split("[")[1].split("]")[0].split(",")
        assert slots[4].strip().strip('"') == "PEC"
    # CPWPort 一等端口（gap_width 口径）
    assert "CPWPort(" in script and "gap_width=GAP" in script


def test_cpw_vs_fgcpw_semantic_boundary_mechanized() -> None:
    """fgcpw 对照（consumers_note 语义边界）：fgcpw 底=MUR（有限地悬浮）。"""
    from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL
    from rfauto.adapters.openems_templates import render_script

    s = render_script("fgcpw", dict(TEMPLATE_NOMINAL["fgcpw"]),
                      (2.25, 2.75))
    bc = next(ln for ln in s.splitlines() if "FDTD.SetBoundaryCond" in ln)
    slots = bc.split("[")[1].split("]")[0].split(",")
    assert slots[4].strip().strip('"') == "MUR"  # cpw 同槽位=PEC（上测已钉）


# ── 4. 锚注册表形态钉（analytic 档与引擎档可区分，#122） ────────────────────

def test_cpw_anchor_registry_shape() -> None:
    rec = _live().get(_CPW_ANCHOR_ID)
    assert rec.kind == "constant"
    assert rec.engine_pair.get("calibrated") == "closedform"
    assert rec.engine_pair.get("referee") is None
    assert rec.quantity["unit"] == "ohm"
    assert rec.status == "experimental"
    assert rec.fallback == "closed_form"
    assert rec.domain is None
    assert rec.consumers == []
    assert rec.uncertainty["kind"] == "rounding_band"
    assert rec.uncertainty["value"] == 0.005
    # semantics 必须携带口径 B 对照注记（防 skrf 消费者踩口径差，#154 族）
    sem = rec.quantity["semantics"]
    assert "67.44" in sem and "cpw_analysis" in sem
