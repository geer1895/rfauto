"""df7 锚消费接线第二批——改道钉测试（纯改道，零行为变化）。

逐项交付判据（runs/gate_df7anchorwire.log 定向门口径）：
1. c3.l_via_h：openems_templates 两处 l_via_h=None 消费点（_c3_via_resolved_h
   与 c3_circuit_sparams）改经锚注册表惰性解析（首次 resolve 模块级缓存；
   任何失败回退字面 C3_L_VIA_CAL_H）——锚值逐位 == 0.125e-9，消费点真走
   锚路径由"换锚值跟随"哨兵证明；
2. cps.gamma_er / siw.w_eff：calculators 公式锚改道——真实注册表下消费者
   输出与原闭式逐位相等（123 点 / 36 组合，同 test_anchors_core a3/a4 口径
   但走消费者函数面），改道路由由"换锚 expr 跟随"证明，provider 未注册/
   失败回退闭式（零行为变化）；
3. patch f_dip·L 双锚：wp39_followup_run._resolve_patch_constant 按引擎对
   选锚解析（openems-v1=76.8 / hfss-v1=99.8），失败回退字面（字面行本身
   被 test_anchors_store_service a2 正则钉住，锚值与字面逐位同）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "scripts"), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rfauto.adapters import openems_templates as ot
from rfauto.core import calculators as calc
from rfauto.core.anchors import AnchorSet

# ── 公共数据（同 test_anchors_core a3/a4 口径）─────────────────────────────

_GAMMA_ER_POINTS = [1.5, 2.2, 3.0, 3.66, 4.4, 6.15, 10.2, 12.9]  # 8 定标点
_GAMMA_ER_SWEEP = [1.5 + i * (12.9 - 1.5) / 114 for i in range(115)]
_SIW_COMBOS = [(w, d, s)
               for w in (10.0, 22.86, 63.0724)
               for d in (0.0, 0.5, 1.0, 1.525)
               for s in (1.0, 2.0, 3.05)]


def _closed_gamma(er: float) -> float:
    """原闭式（改道前 cps_effective_thickness_factor 的 op 序逐位照抄）。"""
    return 1.0 + calc.CPS_H_EFF_GAMMA_C * er ** (-calc.CPS_H_EFF_GAMMA_P)


def _closed_siw(w: float, d: float, s: float) -> float:
    """原闭式（改道前 siw_effective_width_mm 的 op 序逐位照抄）。"""
    return float(w) - (float(d) ** 2) / (0.95 * float(s))


def _anchor_set_with(*raw_anchors: dict) -> AnchorSet:
    return AnchorSet(list(raw_anchors))


# ── 交付1：c3.l_via_h 两处改道 ─────────────────────────────────────────────

def test_c3_l_via_anchor_resolves_bit_exact(monkeypatch: pytest.MonkeyPatch):
    """改道后惰性解析真实注册表：值逐位 == C3_L_VIA_CAL_H == 0.125e-9。"""
    from rfauto.infra import anchors_store  # 导入即注册 provider（接线激活）

    assert anchors_store.load_anchors() is not None
    monkeypatch.setattr(ot, "_c3_l_via_anchor_ready", False)
    monkeypatch.setattr(ot, "_c3_l_via_anchor_h_cache", ot.C3_L_VIA_CAL_H)
    assert ot._c3_l_via_anchor_h() == ot.C3_L_VIA_CAL_H
    assert ot.C3_L_VIA_CAL_H == 0.125e-9


def test_c3_l_via_consumer_routes_through_anchor(
        monkeypatch: pytest.MonkeyPatch):
    """改道证明：注册表锚值改 0.2e-9 时消费点跟随（真走锚，非字面直连）。"""
    modified = _anchor_set_with({
        "anchor_id": "c3.l_via_h.openems-hfss-v1", "kind": "constant",
        "status": "active", "value": 0.2e-9})
    monkeypatch.setattr("rfauto.infra.anchors_store.load_anchors",
                        lambda *a, **k: modified)
    monkeypatch.setattr(ot, "_c3_l_via_anchor_ready", False)
    monkeypatch.setattr(ot, "_c3_l_via_anchor_h_cache", ot.C3_L_VIA_CAL_H)
    assert ot._c3_l_via_anchor_h() == 0.2e-9
    # 消费点①：_c3_via_resolved_h 的 l_via_h=None 分支走锚解析值
    assert ot._c3_via_resolved_h(None, 0.508) == 0.2e-9


def test_c3_l_via_anchor_fallback_on_store_failure(
        monkeypatch: pytest.MonkeyPatch):
    """best-effort（#105）：装载层任何异常回退字面 0.125e-9，不抛不阻塞。"""

    def _boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("rfauto.infra.anchors_store.load_anchors", _boom)
    monkeypatch.setattr(ot, "_c3_l_via_anchor_ready", False)
    monkeypatch.setattr(ot, "_c3_l_via_anchor_h_cache", 999.0)
    assert ot._c3_l_via_anchor_h() == ot.C3_L_VIA_CAL_H == 0.125e-9


@pytest.mark.parametrize("template", ot.C3_TEMPLATES)
def test_c3_sparams_none_routes_through_anchor(
        template: str, monkeypatch: pytest.MonkeyPatch):
    """消费点②：c3_circuit_sparams(l_via_h=None) 取锚解析值（哨兵逐位等价）。"""
    sentinel = 0.2e-9
    monkeypatch.setattr(ot, "_c3_l_via_anchor_h", lambda: sentinel)
    freqs = np.linspace(2.0, 3.0, 401)
    nom = dict(ot.TEMPLATE_NOMINAL[template])
    s_auto = ot.c3_circuit_sparams(template, freqs, nom, l_via_h=None)
    s_expl = ot.c3_circuit_sparams(template, freqs, nom, l_via_h=sentinel)
    assert np.array_equal(s_auto, s_expl)  # None 分支取的就是锚解析值（逐位）
    # 哨兵 ≠ 字面 0.125e-9：若消费点仍直连字面常量（未改道），此断言必假
    assert not np.array_equal(
        s_auto,
        ot.c3_circuit_sparams(template, freqs, nom,
                              l_via_h=ot.C3_L_VIA_CAL_H))


# ── 交付2：cps.gamma_er 公式锚改道 ─────────────────────────────────────────

def test_cps_gamma_er_consumer_routes_through_anchor(
        monkeypatch: pytest.MonkeyPatch):
    """改道证明：锚 expr 换 "2.0" 时消费者跟随（真走锚，非闭式直连）。"""
    import rfauto.core.anchors as anchors_mod

    modified = _anchor_set_with({
        "anchor_id": "cps.gamma_er.fdref-v1", "kind": "formula",
        "status": "active", "expr": "2.0", "variables": ["er"]})
    monkeypatch.setattr(anchors_mod, "_LIVE_SET_PROVIDER", lambda: modified)
    assert calc.cps_effective_thickness_factor(3.66) == 2.0


def test_cps_gamma_er_consumer_fallback_closed_form(
        monkeypatch: pytest.MonkeyPatch):
    """provider 未注册 → 回退闭式逐位同；er<1 旧校验保留。"""
    import rfauto.core.anchors as anchors_mod

    monkeypatch.setattr(anchors_mod, "_LIVE_SET_PROVIDER", None)
    for er in (1.0, 1.2, 3.66, 20.0):  # 域内/域外都走回退
        assert calc.cps_effective_thickness_factor(er) == _closed_gamma(er)
    with pytest.raises(ValueError, match="εr"):
        calc.cps_effective_thickness_factor(0.5)


def test_cps_gamma_er_consumer_bit_exact_real_registry():
    """真实注册表（锚路径激活）：消费者与原闭式 123 点逐位相等。"""
    from rfauto.infra import anchors_store

    assert anchors_store.load_anchors() is not None
    for er in _GAMMA_ER_POINTS + _GAMMA_ER_SWEEP:
        assert calc.cps_effective_thickness_factor(er) == _closed_gamma(er), \
            f"er={er}"


# ── 交付3：siw.w_eff 公式锚改道 ────────────────────────────────────────────

def test_siw_w_eff_consumer_routes_through_anchor(
        monkeypatch: pytest.MonkeyPatch):
    """改道证明：锚 expr 换 "w_mm" 时消费者跟随（真走锚，非闭式直连）。"""
    import rfauto.core.anchors as anchors_mod

    modified = _anchor_set_with({
        "anchor_id": "siw.w_eff.lit-v1", "kind": "formula",
        "status": "active", "expr": "w_mm",
        "variables": ["w_mm", "d_mm", "s_mm"]})
    monkeypatch.setattr(anchors_mod, "_LIVE_SET_PROVIDER", lambda: modified)
    assert calc.siw_effective_width_mm(10.0, 0.5, 1.0) == 10.0  # ≠ 闭式 9.7368…


def test_siw_w_eff_consumer_fallback_closed_form(
        monkeypatch: pytest.MonkeyPatch):
    """provider 未注册 → 回退闭式逐位同（含 d=0 退化点）。"""
    import rfauto.core.anchors as anchors_mod

    monkeypatch.setattr(anchors_mod, "_LIVE_SET_PROVIDER", None)
    assert calc.siw_effective_width_mm(22.86, 0.0, 2.0) == _closed_siw(
        22.86, 0.0, 2.0)


def test_siw_w_eff_consumer_bit_exact_real_registry():
    """真实注册表（锚路径激活）：消费者与原闭式 36 组合逐位相等。"""
    from rfauto.infra import anchors_store

    assert anchors_store.load_anchors() is not None
    for w, d, s in _SIW_COMBOS:
        assert calc.siw_effective_width_mm(w, d, s) == _closed_siw(w, d, s), \
            f"w={w} d={d} s={s}"


# ── 交付4：patch f_dip·L 双锚（脚本消费点改道）─────────────────────────────

def _runner():
    import wp39_followup_run as runner

    return runner


def test_patch_constants_real_registry_bit_exact():
    """真实注册表：按引擎对选锚解析值与字面回退值逐位相等。"""
    runner = _runner()
    from rfauto.infra import anchors_store

    assert anchors_store.load_anchors() is not None
    assert runner._resolve_patch_constant(
        "patch.f_dip_l.openems-v1", runner.OPENEMS_PATCH_CONSTANT_DOC) == 76.8
    assert runner._resolve_patch_constant(
        "patch.f_dip_l.hfss-v1", runner.HFSS_PATCH_CONSTANT_REF) == 99.8


def test_patch_constant_routes_through_anchor(
        monkeypatch: pytest.MonkeyPatch):
    """改道证明：锚值改 77.0 时解析跟随（openems 锚对按 engine 字段分选）。"""
    runner = _runner()
    modified = _anchor_set_with({
        "anchor_id": "patch.f_dip_l.openems-v1", "kind": "constant",
        "status": "active", "value": 77.0})
    monkeypatch.setattr("rfauto.infra.anchors_store.load_anchors",
                        lambda *a, **k: modified)
    assert runner._resolve_patch_constant(
        "patch.f_dip_l.openems-v1", 76.8) == 77.0


def test_patch_constant_fallback_on_failure(monkeypatch: pytest.MonkeyPatch):
    """best-effort（#105）：装载层任何异常回退字面参考值，不抛不阻塞。"""
    runner = _runner()

    def _boom(*a, **k):
        raise RuntimeError("store down")

    monkeypatch.setattr("rfauto.infra.anchors_store.load_anchors", _boom)
    assert runner._resolve_patch_constant(
        "patch.f_dip_l.openems-v1", 76.8) == 76.8
    assert runner._resolve_patch_constant(
        "patch.f_dip_l.hfss-v1", 99.8) == 99.8
