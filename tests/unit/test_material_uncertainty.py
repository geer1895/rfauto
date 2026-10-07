"""MA-8 材料不确定度闭环内核单测（round17 §六 MA-8）。

裁判口径（#118/#122 先行）：解析锚全部由测试侧独立常量与独立代数路径
离线推导——准静态微带 Z0=Z_air/√εeff 分解恒等（εr→1⁺ 回收 Z_air）、
闭式敏感度 ↔ 中心差分互证（模型内构造性恒等，rel≤1e-8）、幂律模型
S=p 锚（f=er^p → 数值敏感度回收 p，平方律前提的代数验证）、冻结 ΔL
档闭式↔数值互证、全 HJ 档与冻结档的分裂量级（ΔL 修正项，区间钉）。
MC 交叉门（线性一阶 vs 均匀 Monte Carlo，rel≤2%）与确定性（同种子逐
位一致）。78GHz 案例钉 C10d 既档判读面（runs/ge6_anchor/verdict.json
R1–R4 数字锚：er_design 全闭式 3.1664、R3 门宽 1%）与
core/anchors.EXPECTED_ANCHORS 注册集一致性（跨面消费者钉）。
IEEE-754 1-ulp 重排——逐位断言只放在运算次序相同的构造性恒等上
（平方法反推、T=T_ref 回收），一般情形 rel 门（文件头如实登记）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import material_uncertainty as mu
from rfauto.core.symbolic_fit import patch_resonance_hj_ghz

# ─── 测试侧独立参考实现（教材公式独立输入，非被测实现产物）──────────────────
C_MM_GHZ = 299.792458


def _ref_eps_eff(w: float, h: float, er: float) -> float:
    f = (1.0 + 12.0 * h / w) ** -0.5
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 * f


def _ref_z0_air(w: float, h: float) -> float:
    r = w / h
    if r >= 1.0:
        return 120.0 * math.pi / (r + 1.393 + 0.667 * math.log(r + 1.444))
    return 60.0 * math.log(8.0 * h / w + w / (4.0 * h))


def _ref_z0(w: float, h: float, er: float) -> float:
    return _ref_z0_air(w, h) / math.sqrt(_ref_eps_eff(w, h, er))


def _ref_patch_f0(len_mm: float, w: float, er: float, h: float) -> float:
    ee = _ref_eps_eff(w, h, er)
    dl = 0.824 * h * (ee + 0.3) * (w / h + 0.264) / ((ee - 0.258) * (w / h + 0.8))
    return C_MM_GHZ / (2.0 * (len_mm + 2.0 * dl) * math.sqrt(ee))


def _ref_dl(len_mm: float, w: float, er: float, h: float) -> float:
    ee = _ref_eps_eff(w, h, er)
    return 0.824 * h * (ee + 0.3) * (w / h + 0.264) / ((ee - 0.258) * (w / h + 0.8))


# C10d 语境几何（runs/ge6_anchor/criteria.md §1 旧名义 G_old）
L_C10D, W_C10D, H_C10D, ER_C10D = 0.9271, 1.3589, 0.127, 3.0
W_FEED = 0.3259  # 50Ω 馈线宽（同链）
F0_78, F_DIP_762 = 78.0, 76.20


# ─── 准静态微带闭式（vs 测试侧独立参考）─────────────────────────────────────


def test_quasi_static_z0_matches_independent_reference():
    for w, h, er in ((W_FEED, H_C10D, 3.0), (W_C10D, H_C10D, 3.0),
                     (0.05, H_C10D, 3.0)):  # 第三点走窄线分支 W/h<1
        q = mu.quasi_static_microstrip(w, h, er)
        assert q["z0_ohm"] == pytest.approx(_ref_z0(w, h, er), rel=1e-12)
        # 分解恒等（构造性）：Z0=Z_air/√εeff
        assert q["z0_ohm"] == pytest.approx(
            q["z0_air_ohm"] / math.sqrt(q["eps_eff"]), rel=1e-12)


def test_eps_eff_linear_in_er_constructive_identity():
    """εeff 对 εr 线性（构造性）⇒ 大区间差商 = (1+F)/2。

    用 d=1 而非小步长：εeff≈2.42 的 ulp≈4.4e-16，小步长差商的相消误差
    ~ulp/d 在 d=1e-6 时达 1e-10 相对——那是浮点相消不是模型误差（#118
    家族：观察工具本身失真）。
    """
    q = mu.quasi_static_microstrip(W_FEED, H_C10D, ER_C10D)
    slope = (
        mu.eps_eff_quasi_static(W_FEED, H_C10D, ER_C10D + 1.0)
        - mu.eps_eff_quasi_static(W_FEED, H_C10D, ER_C10D - 1.0)) / 2.0
    assert slope == pytest.approx((1.0 + q["fill_factor"]) / 2.0, rel=1e-12)


def test_z0_air_recovered_at_er_one_plus():
    """εr→1⁺ ⇒ εeff→1 ⇒ Z0→Z_air（分解恒等的物理端点锚）。"""
    z_air = mu.z0_air_quasi_static(W_FEED, H_C10D)
    assert z_air == pytest.approx(_ref_z0_air(W_FEED, H_C10D), rel=1e-12)
    q = mu.quasi_static_microstrip(W_FEED, H_C10D, 1.0 + 1e-9)
    assert abs(q["z0_ohm"] - z_air) / z_air <= 1e-8


def test_quasi_static_feed_z0_near_50ohm_sanity():
    """C10d 馈线宽在准静态口径下接近 50Ω（口径差 ~1% 如实——非判据，
    宽松 5% 守卫防链漂移；绝对值以仓内 skrf HJ 综合链为准）。"""
    q = mu.quasi_static_microstrip(W_FEED, H_C10D, ER_C10D)
    assert abs(q["z0_ohm"] - 50.0) / 50.0 <= 0.05


# ─── 敏感度：闭式 ↔ 数值互证 ────────────────────────────────────────────────


def test_z0_sensitivity_closed_form_vs_numeric():
    for w in (W_FEED, W_C10D, 0.05):
        closed = mu.z0_sensitivity_closed_form(w, H_C10D, ER_C10D)
        num = mu.dk_log_sensitivity_numeric(
            lambda er, w=w: mu.quasi_static_microstrip(w, H_C10D, er)["z0_ohm"],
            ER_C10D)
        assert closed["s_z0"] == pytest.approx(num, rel=1e-8)
        # 恒等链：S_Z = −0.5·S_εeff
        assert closed["s_z0"] == pytest.approx(-0.5 * closed["s_eps_eff"],
                                               rel=1e-12)
        # 符号与量级：Dk↑ ⇒ Z0↓，|S| ∈ (0.2, 0.8)（微带常识域）
        assert -0.8 < closed["s_z0"] < -0.2


def test_log_sensitivity_recovers_power_law_exponent():
    """幂律 f(er)=er^p ⇒ S=p（平方律前提的代数锚）。"""
    for p in (-0.5, 1.0, -1.0):
        s = mu.dk_log_sensitivity_numeric(lambda er, p=p: er ** p, 3.0)
        assert s == pytest.approx(p, rel=1e-6)


def test_frozen_dl_f_res_closed_vs_numeric():
    """冻结 ΔL 档：f=c/(2(L+2ΔL₀)√εeff) 敏感度 = −0.5·S_εeff（闭式互证）。"""
    dl0 = _ref_dl(L_C10D, W_C10D, ER_C10D, H_C10D)
    num = mu.dk_log_sensitivity_numeric(
        lambda er: mu.f_res_frozen_dl(L_C10D, W_C10D, er, H_C10D, dl0), ER_C10D)
    closed = mu.z0_sensitivity_closed_form(W_C10D, H_C10D, ER_C10D)
    assert num == pytest.approx(closed["s_z0"], rel=1e-8)


def test_full_hj_sensitivity_split_documented():
    """全 HJ 档（ΔL(εeff) 非线性）与冻结档分裂 ~9%——区间钉，双档如实。"""
    model = lambda er: patch_resonance_hj_ghz(L_C10D, W_C10D, er, H_C10D)  # noqa: E731
    s_full = mu.dk_log_sensitivity_numeric(model, ER_C10D)
    dl0 = _ref_dl(L_C10D, W_C10D, ER_C10D, H_C10D)
    s_frozen = mu.dk_log_sensitivity_numeric(
        lambda er: mu.f_res_frozen_dl(L_C10D, W_C10D, er, H_C10D, dl0), ER_C10D)
    split = abs(s_full - s_frozen) / abs(s_frozen)
    assert 0.01 <= split <= 0.25, "ΔL 修正项分裂量级漂移（口径变化须重钉）"
    assert -0.6 < s_full < -0.3


def test_patch_f0_judge_matches_independent_reference():
    """仓内裁判 patch_resonance_hj_ghz ↔ 测试侧独立实现（链漂移哨兵）。"""
    f_ref = _ref_patch_f0(L_C10D, W_C10D, ER_C10D, H_C10D)
    assert patch_resonance_hj_ghz(L_C10D, W_C10D, ER_C10D, H_C10D) \
        == pytest.approx(f_ref, rel=1e-12)
    # 旧名义在其自身设计 Dk 下应精确还原 78（C10d R4 哨兵语义）
    assert abs(f_ref - F0_78) / F0_78 <= 1e-3


# ─── 容差传播：线性一阶 vs Monte Carlo ──────────────────────────────────────


def _patch_model(er: float) -> float:
    return patch_resonance_hj_ghz(L_C10D, W_C10D, er, H_C10D)


@pytest.mark.parametrize("model,er,tol,label", [
    (_patch_model, ER_C10D, 0.04, "patch full-HJ"),
    (lambda er: mu.quasi_static_microstrip(W_FEED, H_C10D, er)["z0_ohm"],
     ER_C10D, 0.04, "quasi-static z0"),
])
def test_propagate_linear_vs_mc_agreement(model, er, tol, label):
    out = mu.propagate_dk_tolerance(er, tol, model, n_mc=8000, seed=20261002)
    assert out["agreement_half_width_rel"] <= 0.02, label
    assert out["agreement_std_rel"] <= 0.02, label
    # MC 端点包络 vs 线性半宽互相夹（一阶精度内的物理一致性）
    assert out["mc_half_width"] == pytest.approx(
        out["linear_half_width"], rel=0.02)
    # 均匀分布 std=tol/(er·√3) 换算的线性 std 与 MC std 一致
    assert out["mc_std"] == pytest.approx(out["linear_std"], rel=0.02)


def test_propagate_deterministic_same_seed():
    a = mu.propagate_dk_tolerance(ER_C10D, 0.05, _patch_model, n_mc=2000,
                                  seed=12345)
    b = mu.propagate_dk_tolerance(ER_C10D, 0.05, _patch_model, n_mc=2000,
                                  seed=12345)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_propagate_sensitivity_sign_and_direction():
    out = mu.propagate_dk_tolerance(ER_C10D, 0.04, _patch_model, n_mc=2000)
    assert out["s_numeric"] < 0.0  # Dk↑ ⇒ f_res↓
    # 递减映射的分位方向：低 Dk 侧样本落 f 高端 → p05 < 名义 < p95
    assert out["mc_p05"] < out["nominal"] < out["mc_p95"]


def test_propagate_guards():
    with pytest.raises(ValueError, match="tol"):
        mu.propagate_dk_tolerance(3.0, -0.01, _patch_model)
    with pytest.raises(ValueError, match="n_mc"):
        mu.propagate_dk_tolerance(3.0, 0.04, _patch_model, n_mc=1)
    with pytest.raises(ValueError, match="bool"):
        mu.propagate_dk_tolerance(True, 0.04, _patch_model)
    with pytest.raises(ValueError, match="正"):
        mu.propagate_dk_tolerance(3.0, 0.04, lambda er: -1.0)


# ─── Design Dk 反推（平方法 + 全闭式交叉）───────────────────────────────────


def test_square_law_backout_bitwise_and_direction():
    """er·(f_t/f_o)² 运算次序相同 → 逐位；方向：f_obs<f_t ⇒ er_design>er。"""
    er_sq = mu.back_out_design_dk(3.0, F0_78, F_DIP_762)
    assert er_sq == 3.0 * (F0_78 / F_DIP_762) ** 2
    assert er_sq == pytest.approx(3.1434062868125734)  # C10d verdict 原始值
    assert mu.back_out_design_dk(3.0, 76.2, 78.0) < 3.0


def test_full_cf_backout_self_consistent_and_gated():
    er_sq = mu.back_out_design_dk(3.0, F0_78, F_DIP_762)
    er_cf = mu.back_out_design_dk_full_cf(L_C10D, W_C10D, H_C10D, 3.0,
                                          F_DIP_762)
    # 自洽：全闭式反解代回裁判面精确回收 f_dip
    f_back = patch_resonance_hj_ghz(L_C10D, W_C10D, er_cf, H_C10D)
    assert abs(f_back - F_DIP_762) / F_DIP_762 <= 1e-9
    # R1 门（criteria §2，门宽 1%）：平方律↔全闭式自洽
    assert abs(er_cf - er_sq) / er_sq <= 0.01
    assert er_cf > er_sq  # ΔL 非线性方向（verdict 3.1664 > 3.1434）
    # 无解守卫：f_obs 出模型值域显式报错（er∈[1.5,6] 模型值域上限
    # ≈133 GHz @er→1⁺；100 仍在域内，须取 150）
    with pytest.raises(ValueError, match="无解"):
        mu.back_out_design_dk_full_cf(L_C10D, W_C10D, H_C10D, 3.0, 150.0)


# ─── 78GHz Design Dk 锚案例（C10d 语境）─────────────────────────────────────


@pytest.fixture(scope="module")
def case() -> dict:
    return mu.case_78ghz_design_dk()


def test_case_r4_self_check_and_gap(case):
    assert case["r4_self_check_ok"] is True
    assert case["gap_pct"] == (F_DIP_762 - F0_78) / F0_78 * 100.0
    assert case["gap_pct"] == pytest.approx(-2.3077, abs=1e-4)
    assert case["gap_ghz"] == pytest.approx(1.80)


def test_case_anchor_numbers_match_registered_verdict(case):
    assert case["er_design_square_law"] == pytest.approx(3.1434062868125734)
    assert abs(case["er_design_full_cf"] - 3.1664305676183653) / 3.1664305676183653 \
        <= 1e-6
    assert case["square_vs_full_rel"] <= 0.01  # R1 门宽
    assert case["anchor_explains_gap"] is True  # R3 主门（≤1%）
    # ge8b 消费切 v2（K-4 双引擎 AGREE，constant active；v1 pointer 封档）
    assert case["anchor_er_design"] == 3.1025
    assert case["anchor_id"] == "mmwave.design_dk.ro3003-oe-hfss-v2"


def test_case_design_domain_does_not_cover_78(case):
    assert case["design_domain_covers_78"] is False  # datasheet design 域 8–40 GHz


def test_case_tolerance_bands_quantified(case):
    bands = case["tolerance_bands"]
    assert [b["dk_tol"] for b in bands] == pytest.approx([0.04, 0.05])
    for b in bands:
        assert b["band_explains_gap"] is False, "容差带解释不了 −2.31% 缺口"
        assert b["gap_to_band_ratio"] > 2.5, "缺口须显著大于容差带（锚必要性量级）"
        assert b["agreement_half_width_rel"] <= 0.02
    # 半宽随 tol 线性缩放（一阶构造性）：0.05 档 ≈ 0.04 档 × 1.25
    ratio = bands[1]["mc_half_width_ghz"] / bands[0]["mc_half_width_ghz"]
    assert ratio == pytest.approx(0.05 / 0.04, rel=0.05)


def test_case_web_tool_corroboration_and_method_domain_spread(case):
    # 官网工具 Design 3.1629 与锚反推 3.1434 互差 ≤1%（方法域互证）
    assert case["web_tool_vs_anchor_rel"] <= 0.01
    # 方法域差（Design vs process）~+5.4% ≫ 容差带 ±1.33%
    assert case["web_tool_vs_process_rel_pct"] == pytest.approx(
        (3.1629 - 3.00) / 3.00 * 100.0)
    assert case["web_tool_vs_process_rel_pct"] > 3.0


def test_case_cross_module_anchor_registration(case):
    """锚 id 必须在 core/anchors 注册集（跨面消费者一致性钉）。"""
    from rfauto.core.anchors import EXPECTED_ANCHORS

    assert case["anchor_id"] in EXPECTED_ANCHORS


def test_case_json_serializable_and_verdict(case):
    json.dumps(case)
    assert "容差" in case["verdict"]
    assert case["provenance"]
    assert case["s_f_full_hj"] < 0.0 and case["s_f_frozen_dl"] < 0.0
    assert 0.01 <= case["sensitivity_split_rel"] <= 0.25


# ─── J1-3 锚值单源改道（ge8e 审查批 F8）：活注册表优先 + fallback 钉 ────────


def _provider_with_ro3003_anchor(value: float):
    """合成活注册表（constant 锚，值可任意——验证消费面跟随）。"""
    from rfauto.core.anchors import AnchorSet

    raw = {
        "anchor_id": "mmwave.design_dk.ro3003-oe-hfss-v2",
        "kind": "constant",
        "status": "active",
        "template_family": ["mmwave_series_array"],
        "engine_pair": {"calibrated": "hfss", "referee": "openems"},
        "quantity": {"name": "mmwave_design_dk_ro3003",
                     "unit": "dimensionless"},
        "value": value,
        "uncertainty": {"value": 0.01, "kind": "engine_pair_spread"},
        "domain": {"f_ghz": [78.0, 78.0]},
        "provenance": {"commit": "f759753",
                       "registered_at": "2026-10-02T18:10:00+08:00"},
    }
    return AnchorSet([raw])


def test_anchor_er_design_follows_live_registry(monkeypatch):
    """读锚路径生效：monkeypatch 锚存储值 → 模块消费面跟随（J1-3 主钉）。"""
    from rfauto.core import anchors as core_anchors

    monkeypatch.setattr(core_anchors, "_LIVE_SET_PROVIDER",
                        lambda: _provider_with_ro3003_anchor(3.5))
    res = mu.resolve_anchor_er_design(F0_78)
    assert res["source"] == "anchor"
    assert res["value"] == 3.5
    assert res["reason"] is None
    assert res["anchor_id"] == "mmwave.design_dk.ro3003-oe-hfss-v2"


def test_case_78ghz_consumes_live_anchor_value(monkeypatch):
    """案例消费面（case_78ghz_design_dk）同样走活注册表值 + source 随行。"""
    from rfauto.core import anchors as core_anchors

    monkeypatch.setattr(core_anchors, "_LIVE_SET_PROVIDER",
                        lambda: _provider_with_ro3003_anchor(3.5))
    out = mu.case_78ghz_design_dk(n_mc=200)
    assert out["anchor_er_design"] == 3.5
    assert out["anchor_source"] == "anchor"


def test_anchor_er_design_fallback_with_warning_when_registry_missing(
        monkeypatch, caplog):
    """锚缺席（provider 未注册）→ fallback 常量 + 模块级 warning（#105）。"""
    from rfauto.core import anchors as core_anchors

    monkeypatch.setattr(core_anchors, "_LIVE_SET_PROVIDER", lambda: None)
    with caplog.at_level("WARNING",
                         logger="rfauto.core.material_uncertainty"):
        res = mu.resolve_anchor_er_design(F0_78)
    assert res["source"] == "fallback"
    assert res["value"] == mu.C10D_CASE["anchor_er_design"] == 3.1025
    assert res["reason"] == "registry_unavailable"
    assert any("不可解析" in rec.getMessage() and "ro3003" in rec.getMessage()
               for rec in caplog.records), "fallback 必须留 warning 痕"


def test_anchor_er_design_out_of_domain_falls_back(monkeypatch):
    """域外（f_ghz 不在锚 domain 盒 [78,78]）→ 结构化 fallback 不抛。"""
    from rfauto.core import anchors as core_anchors

    monkeypatch.setattr(core_anchors, "_LIVE_SET_PROVIDER",
                        lambda: _provider_with_ro3003_anchor(3.5))
    res = mu.resolve_anchor_er_design(77.0)
    assert res["source"] == "fallback"
    assert res["reason"] == "out_of_domain"
    assert res["value"] == 3.1025


def test_anchor_er_design_provider_crash_falls_back(monkeypatch, caplog):
    """provider 抛错 → 回退不炸（#105：锚系统任何故障不阻塞业务主路径）。

    live_anchor_set() 对 provider 异常自身兜底返回 None，故 reason 落
    registry_unavailable；本模块的 except 是第二道 belt（import 失败等）。
    """
    from rfauto.core import anchors as core_anchors

    def boom():
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(core_anchors, "_LIVE_SET_PROVIDER", boom)
    with caplog.at_level("WARNING",
                         logger="rfauto.core.material_uncertainty"):
        res = mu.resolve_anchor_er_design(F0_78)
    assert res["source"] == "fallback" and res["value"] == 3.1025
    assert res["reason"] == "registry_unavailable"
    assert any("不可解析" in rec.getMessage() for rec in caplog.records)
