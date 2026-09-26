"""DP-7 P1/P3：fab 服务层 JSON 进出 + KiCad 导出前接线 + C4 端到端良率。

判据预声明：runs/df6_dp7fab/criteria.md C3/C4。
- C3：check_template_dfm / check_design_dfm JSON 契约；KiCad
  generate_pcb 导出前 best-effort DFM（#105 不阻塞导出）。
- C4：mline 名义 ±20% 线宽扰动在既有 GP 代理（surrogate_registry
  smt_kriging）上良率出数，与测试内 numpy 直写独立 MC（1e4 点）
  对照 |Δyield| ≤ 2%（**不改 uq_service**；P2 注入延后留接口）。
"""

from __future__ import annotations

import pytest

from rfauto.core.fab_check import load_profile
from rfauto.service.fab_service import (
    check_design_dfm,
    check_design_dfm_best_effort,
    check_template_dfm,
    fab_profile_yield,
    load_fab_profile,
)

# ── C3 服务面 JSON 契约 ──────────────────────────────────────

def test_load_fab_profile_json_contract() -> None:
    out = load_fab_profile("jlcpcb")
    assert out["ok"] is True
    assert out["name"] == "jlcpcb"
    assert out["copper_rules"]["1"]["min_trace_mm"] == pytest.approx(0.10)
    assert "rogers4350b" in out["supported_materials"]
    missing = load_fab_profile("nonexistent-fab")
    assert missing["ok"] is False and missing["errors"]


def test_check_template_dfm_mline_nominal_passes() -> None:
    out = check_template_dfm("mline")
    assert out["ok"] is True, out["violations"]
    assert out["template"] == "mline"
    assert out["facts"]["traces"] == ["w_mm"]
    assert out["params_source"] == "TEMPLATE_NOMINAL+user_overrides"


def test_check_template_dfm_thin_override_triggers() -> None:
    out = check_template_dfm("mline", {"w_mm": 0.08})
    assert out["ok"] is False
    assert any(v["code"] == "TRACE_BELOW_MIN" for v in out["violations"])


def test_check_template_dfm_cpw_gap_checked() -> None:
    out = check_template_dfm("cpw")
    assert out["facts"]["gaps"] == ["gap_mm"]
    assert out["ok"] is True
    narrow = check_template_dfm("cpw", {"gap_mm": 0.05})
    assert any(v["code"] == "GAP_BELOW_MIN" for v in narrow["violations"])


def test_check_template_dfm_scan_excludes_slot_params() -> None:
    """slot 模板走保守扫描：slot_w_mm（地缝）不按线宽分类（#154）。"""
    out = check_template_dfm("slot")
    assert "scan_note" in out["facts"]
    assert "slot_w_mm" not in out["facts"]["traces"]
    assert "slot_l_mm" not in out["facts"]["traces"]


def test_check_template_dfm_unknown_template_and_profile() -> None:
    out = check_template_dfm("no_such_template")
    assert out["ok"] is False and "未知模板" in out["errors"][0]
    out = check_template_dfm("mline", profile="nonexistent-fab")
    assert out["ok"] is False and out["errors"]


def test_check_template_dfm_huaqiu_rogers_flagged() -> None:
    """华秋剖面标准档仅 FR-4：rogers 出 MATERIAL_UNSUPPORTED 清单。"""
    out = check_template_dfm("mline", profile="huaqiu")
    assert out["ok"] is False
    assert any(v["code"] == "MATERIAL_UNSUPPORTED"
               for v in out["violations"])


def test_check_design_dfm_and_best_effort() -> None:
    good = {"traces": [{"width": 1.113}],
            "vias": [{"drill": 0.15, "pad": 0.25}],
            "material": "rogers4350b_h0.508"}
    out = check_design_dfm(good)
    assert out["ran"] is True and out["ok"] is True
    thin = check_design_dfm({"traces": [{"width": 0.08}]})
    assert thin["ok"] is False
    assert any(v["code"] == "TRACE_BELOW_MIN" for v in thin["violations"])
    # best-effort：剖面缺失留痕不抛（#105）
    out = check_design_dfm_best_effort(good, profile="nonexistent-fab")
    assert out["ran"] is False and out["ok"] is None


def test_kicad_export_dfm_hook_does_not_block(tmp_path) -> None:
    """导出前 DFM 接线：细线设计的导出结果带 TRACE_BELOW_MIN 且
    不阻塞导出主路径（无 KiCad Python → 提前失败但 dfm 已留痕）。"""
    from rfauto.adapters.kicad_pcell import PCBDesign, Trace, generate_pcb

    thin = PCBDesign(traces=[Trace(start=[0, 0], end=[10, 0], width=0.08)])
    result = generate_pcb(tmp_path / "thin.kicad_pcb", thin,
                          kicad_python="Z:/no/python.exe")
    assert result.success is False  # KiCad 缺失照常失败——DFM 不替主路径背书
    assert result.dfm is not None and result.dfm["ran"] is True
    assert any(v["code"] == "TRACE_BELOW_MIN"
               for v in result.dfm["violations"])

    fine = PCBDesign(traces=[Trace(start=[0, 0], end=[10, 0], width=1.113)])
    result = generate_pcb(tmp_path / "fine.kicad_pcb", fine,
                          kicad_python="Z:/no/python.exe")
    assert result.dfm is not None and result.dfm["ok"] is True


# ── C4 端到端：GP 代理良率 vs 独立手工 MC（|Δyield| ≤ 2%）────

W_NOMINAL = 1.113  # mline 50Ω 名义线宽（TEMPLATE_NOMINAL）
SPEC_VALUE = -17.5  # s11_db ≤ −17.5：理论良率 = P(|w/1.113−1| ≤ 0.15) = 0.75
N_DRAWS = 10_000


@pytest.fixture(scope="module")
def mline_gp():
    """合成数据集 → 既有 GP 代理（smt_kriging，surrogate_registry）。"""
    import numpy as np

    from rfauto.optimization.surrogate import surrogate_registry

    def f(w: float) -> float:
        return -40.0 + 150.0 * abs(w / W_NOMINAL - 1.0)

    # 101 均匀点：|w/1.113−1| 的 kink 处 kriging 平滑使稀疏采样（41 点）
    # 良率对真值偏差 +9.3pt（0.845 vs 0.752）——101 点实测偏差 −0.0004
    # （2026-09-24 会话内三档采样对照实验，见 runs/df6_dp7fab/criteria.md
    # 判据实绩节）。门断言用同 GP 双实现对照（保真度偏差相消），密度
    # 档只影响"良率估计对真函数"的质量，不改变实现等价性判定。
    ws = np.linspace(0.4, 2.0, 101)
    samples = [{"params": {"w_mm": float(w)},
                "metrics": {"s11_db": float(f(w))}} for w in ws]
    model = surrogate_registry.create(
        "smt_kriging",
        config={"bounds": {"w_mm": (0.4, 2.0)}, "metrics": ["s11_db"],
                "theta0": 0.05})
    model.fit(samples)
    return model


def _independent_mc_yield(model, n: int, seed: int,
                          tol_pct: float = 20.0) -> float:
    """numpy 直写独立对照实现（与被测实现不同代码路径）。

    同一分布语义：w = 名义 × U(1±tol)；判据：pred ≤ spec（max_below）。
    """
    import numpy as np

    rng = np.random.default_rng(seed)
    factors = 1.0 + rng.uniform(-tol_pct / 100.0, tol_pct / 100.0, n)
    preds = [
        float(model.predict({"w_mm": float(W_NOMINAL * fac)})["s11_db"])
        for fac in factors
    ]
    return float(np.mean(np.asarray(preds) <= SPEC_VALUE))


def test_c4_yield_same_seed_matches_reference(mline_gp) -> None:
    """同种子：被测实现与独立实现应逐位同分布（实现等价性）。"""
    out = fab_profile_yield(
        mline_gp, {"w_mm": W_NOMINAL}, perturb_param="w_mm",
        spec={"metric": "s11_db", "op": "max_below", "value": SPEC_VALUE},
        profile="jlcpcb", n=N_DRAWS, seed=42)
    assert out["ok"] is True
    assert out["tolerance_source"] == "fab_profile:jlcpcb:trace.tolerance_pct"
    assert out["distribution"] == "uniform_multiplicative"
    assert out["tolerance"]["pct"] == pytest.approx(20.0)
    ref = _independent_mc_yield(mline_gp, N_DRAWS, seed=42)
    # 同种子同序抽样：至多阈值点 1-ulp 翻转差（≪2% 门）
    assert abs(out["yield_rate"] - ref) <= 0.002
    # 良率非退化出数（理论 0.75 附近）
    assert 0.5 < out["yield_rate"] < 0.95


def test_c4_yield_different_seed_within_2pct(mline_gp) -> None:
    """异种子：独立 MC 噪声 std_diff≈0.006，2% 门 ≈3σ（判据门）。"""
    got = fab_profile_yield(
        mline_gp, {"w_mm": W_NOMINAL}, perturb_param="w_mm",
        spec={"metric": "s11_db", "op": "max_below", "value": SPEC_VALUE},
        profile="jlcpcb", n=N_DRAWS, seed=49)
    ref = _independent_mc_yield(mline_gp, N_DRAWS, seed=42)
    assert abs(got["yield_rate"] - ref) <= 0.02


def test_c4_yield_explicit_tol_override_marks_provenance(mline_gp) -> None:
    out = fab_profile_yield(
        mline_gp, {"w_mm": W_NOMINAL}, perturb_param="w_mm",
        spec={"metric": "s11_db", "op": "max_below", "value": SPEC_VALUE},
        profile="jlcpcb", n=200, seed=1, tol_pct=5.0)
    assert out["tolerance_source"] == "explicit_override"
    assert out["tolerance"]["pct"] == pytest.approx(5.0)


def test_c4_yield_input_validation(mline_gp) -> None:
    bad = fab_profile_yield(
        mline_gp, {"w_mm": W_NOMINAL}, perturb_param="nope",
        spec={"metric": "s11_db", "op": "max_below", "value": -20}, n=10)
    assert bad["ok"] is False and bad["errors"]
    bad = fab_profile_yield(
        mline_gp, {"w_mm": W_NOMINAL}, perturb_param="w_mm",
        spec={"metric": "s11_db", "op": "bogus", "value": -20}, n=10)
    assert bad["ok"] is False and bad["errors"]
    # 剖面 2oz 档线宽下限独立可查（load_profile 走通）
    assert load_profile("jlcpcb").copper_rules[2.0].min_trace_mm == \
        pytest.approx(0.16)
