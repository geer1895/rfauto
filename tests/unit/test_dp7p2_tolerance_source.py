"""DP-7 P2：公差来源单源注入（判据预声明 runs/df6_dp7p2/criteria.md）。

- C1 单源：``derive_tolerances_from_fab_profile`` /
  ``resolve_tolerance_source`` / ``load_material_epsilon_r_tolerance``
  （fab 剖面 + materials.yaml 一处定义，uq/yield 链经它取 σ）；
- C2 uq 输入规范化：``surrogate_yield``/``surrogate_yield_at``/
  ``fab_profile_yield`` 的 ``tolerance_source`` 引用 → 自动展开
  {param: σ}；缺省（不传 tolerance_source）行为零变化；
- 判据 a：同一剖面单源派生 vs 手工 σ 直传——同种子 MC 良率逐位一致；
- 判据 b：mline 名义 ±20% 出数（P1 回归保持）+ design_for_yield 端到端；
- 判据 c：tolerance_provenance 逐参数 source 可追溯（εr 含
  materials.yaml 指针；未声明材料如实 not_declared）。
"""

from __future__ import annotations

import json

import pytest

# ── 判据 c/C1：materials.yaml εr 容差声明（单源）──────────────────

def test_material_tolerance_declaration_and_undeclared() -> None:
    from rfauto.service.fab_service import load_material_epsilon_r_tolerance

    res = load_material_epsilon_r_tolerance("rogers4350b_h0.508")
    assert res["ok"] is True and res["declared"] is True
    assert res["epsilon_r"] == pytest.approx(3.66)
    assert res["tol"] == pytest.approx(0.05)
    assert res["source"] == ("configs/materials.yaml:rogers4350b_h0.508:"
                             "epsilon_r_tol_abs")
    # 2026-09-25 datasheet 复核（件②）：官方 process Dk 3.48±0.05，
    # 3.66=Design Dk 无官方容差 → 容差半宽取 process spec ±0.05（verified-web）
    assert "verified-web" in res["source_note"]
    assert "3.48" in res["source_note"]
    # RO4003C：官方 process Dk 3.38±0.05 与登记一致（2026-09-25 verified-web）
    ro4003c = load_material_epsilon_r_tolerance("rogers4003c_h0.508")
    assert ro4003c["ok"] is True and ro4003c["declared"] is True
    assert ro4003c["epsilon_r"] == pytest.approx(3.38)
    assert ro4003c["tol"] == pytest.approx(0.05)
    assert ro4003c["source"] == ("configs/materials.yaml:rogers4003c_h0.508:"
                                 "epsilon_r_tol_abs")
    assert "verified-web" in ro4003c["source_note"]
    # fr4 未声明容差：不是错误，如实 not_declared（不虚构）
    fr4 = load_material_epsilon_r_tolerance("fr4_h1.6")
    assert fr4["ok"] is True and fr4["declared"] is False
    assert fr4["source"] == "not_declared"
    bad = load_material_epsilon_r_tolerance("no_such_material")
    assert bad["ok"] is False and bad["errors"]


# ── 手工 σ（判据 a 的对照面：独立按预声明公式计算，不调实现）────────

K_SIGMA = 3.0
TRACE_PCT = 20.0        # jlcpcb trace.tolerance_pct
ER_TOL_ABS = 0.05       # rogers4350b_h0.508 epsilon_r_tol_abs（2026-09-25 datasheet 复核：
                        # 官方 process Dk 3.48±0.05，原登记 3.66±0.08 无出处已修正）


def _hand_sigmas(with_er: bool = True) -> dict[str, float]:
    sig = {"series_w_mm": 0.35 * (TRACE_PCT / 100.0) / K_SIGMA}
    if with_er:
        sig["er"] = ER_TOL_ABS / K_SIGMA
    return sig


def _write_samples(tmp_path, *, with_er: bool = True) -> str:
    """合成校准样本集（名义点=cost 最小=samples[0]，poly_ridge 可拟合）。"""
    import numpy as np

    rng = np.random.default_rng(7)
    bounds: dict[str, list[float]] = {"arm_len_mm": [18.0, 23.0],
                                      "series_w_mm": [0.25, 0.45]}
    if with_er:
        bounds["er"] = [3.5, 3.8]
    samples = []
    for _ in range(30):
        p = {k: float(rng.uniform(*v)) for k, v in bounds.items()}
        s11 = (-20.0 + 5.0 * (p["arm_len_mm"] - 20.0) ** 2
               + 10.0 * (p["series_w_mm"] - 0.35) ** 2)
        if with_er:
            s11 += 40.0 * (p["er"] - 3.66) ** 2
        samples.append({"params": p,
                        "metrics": {"s11_db_max_in_band": float(s11)}})
    nominal = {"arm_len_mm": 20.0, "series_w_mm": 0.35}
    if with_er:
        nominal["er"] = 3.66
    samples[0]["params"] = nominal
    samples[0]["metrics"] = {"s11_db_max_in_band": -20.0}
    data = {
        "bounds": bounds,
        "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                        "op": "max_below", "value": -15}],
        "samples": samples,
    }
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class _QuadModel:
    """合成二次面 stub（w_mm 锚 1.0；无批路径 → _mc_yield 逐点回退）。

    曲率取 400：±20% 线宽扰动的 3σ 边界会踩 spec（良率非退化 ∈(0,1)）。
    """

    def predict(self, params: dict) -> dict:
        w = float(params.get("w_mm", 1.0))
        s11 = -20.0 + 400.0 * (w - 1.0) ** 2
        return {"s11_db_max_in_band": float(s11)}


# ── C1：单源派生公式与手工公式逐位一致 ───────────────────────────

def test_derive_tolerances_matches_hand_formula() -> None:
    from rfauto.service.fab_service import derive_tolerances_from_fab_profile

    res = derive_tolerances_from_fab_profile(
        {"series_w_mm": 0.35, "er": 3.66, "arm_len_mm": 20.0},
        profile="jlcpcb", material="rogers4350b_h0.508")
    assert res["ok"] is True
    # 判据 a 的派生级前置：派生 σ 与手工公式逐位相等（dict ==）
    assert res["sigmas"] == _hand_sigmas()
    prov = res["provenance"]
    assert prov["series_w_mm"]["source"] == \
        "fab_profile:jlcpcb:trace.tolerance_pct"
    assert prov["series_w_mm"]["class"] == "trace"
    assert prov["er"]["source"].startswith(
        "configs/materials.yaml:rogers4350b_h0.508:")
    assert prov["er"]["class"] == "epsilon_r"
    # 非公差参数不扰动（arm_len_mm → other）
    assert res["classes"]["other"] == ["arm_len_mm"]
    assert "arm_len_mm" not in res["sigmas"]
    assert res["epsilon_r_declaration"]["declared"] is True


def test_derive_thickness_from_profile_fields() -> None:
    from rfauto.service.fab_service import derive_tolerances_from_fab_profile

    res = derive_tolerances_from_fab_profile(
        {"h_mm": 1.6, "sub_h_mm": 0.8, "w_mm": 1.0}, profile="jlcpcb")
    assert res["ok"] is True
    # ≥1.0mm → 板厚公差 ±10%（pct）；<1.0mm → ±0.1mm（剖面字段直取）
    assert res["sigmas"]["h_mm"] == 1.6 * (10.0 / 100.0) / K_SIGMA
    assert res["sigmas"]["sub_h_mm"] == 0.1 / K_SIGMA
    assert res["provenance"]["h_mm"]["source"].endswith(
        "board_thickness.tolerance_pct_ge_1mm")
    assert res["provenance"]["sub_h_mm"]["source"].endswith(
        "board_thickness.tolerance_abs_mm_lt_1mm")


def test_derive_fr4_er_not_declared_honest() -> None:
    from rfauto.service.fab_service import derive_tolerances_from_fab_profile

    res = derive_tolerances_from_fab_profile(
        {"w_mm": 1.0, "er": 4.4}, profile="jlcpcb", material="fr4_h1.6")
    assert res["ok"] is True
    assert res["sigmas"]["w_mm"] == 1.0 * (TRACE_PCT / 100.0) / K_SIGMA
    # εr 未声明 → 不派生 σ，provenance 如实 not_declared（判据 c）
    assert "er" not in res["sigmas"]
    assert res["provenance"]["er"]["declared"] is False
    assert res["provenance"]["er"]["source"] == "not_declared"


# ── 判据 a：单源派生 vs 手工 σ 直传——MC 良率逐位一致 ─────────────

def test_criterion_a_surrogate_yield_bit_identical(tmp_path) -> None:
    from rfauto.service.uq_service import surrogate_yield

    samples = _write_samples(tmp_path, with_er=True)
    src = {"fab_profile": "jlcpcb", "material": "rogers4350b_h0.508"}
    r_src = surrogate_yield(samples, tolerance_source=src, n=4000, seed=42)
    r_hand = surrogate_yield(samples, _hand_sigmas(), n=4000, seed=42)
    assert r_src["ok"] is True and r_hand["ok"] is True
    assert r_src["tolerances"] == _hand_sigmas()
    # 判据 a：同种子同 σ → MC 良率逐位相等（==，非 approx）
    assert r_src["yield_rate"] == r_hand["yield_rate"]
    assert r_src["metric_stats"] == r_hand["metric_stats"]
    assert r_src["implementation"] == r_hand["implementation"]
    assert 0.0 < r_src["yield_rate"] < 1.0
    # 判据 c：provenance 仅在 tolerance_source 分支出现（缺省零变化）
    assert "tolerance_provenance" not in r_hand
    assert r_src["tolerance_provenance"]["er"]["source"].startswith(
        "configs/materials.yaml:rogers4350b_h0.508:")
    assert r_src["tolerance_provenance"]["series_w_mm"]["source"] == \
        "fab_profile:jlcpcb:trace.tolerance_pct"


def test_criterion_a_file_form_and_inline_dict_identical(tmp_path) -> None:
    import yaml

    from rfauto.service.uq_service import surrogate_yield

    samples = _write_samples(tmp_path, with_er=True)
    tf = tmp_path / "tol_src.yaml"
    tf.write_text(yaml.safe_dump({
        "fab_profile": "jlcpcb",
        "material": "rogers4350b_h0.508",
        "k_sigma": 3.0}), encoding="utf-8")
    r_file = surrogate_yield(samples, tolerance_source=str(tf),
                             n=4000, seed=42)
    r_inline = surrogate_yield(
        samples,
        tolerance_source={"fab_profile": "jlcpcb",
                          "material": "rogers4350b_h0.508"},
        n=4000, seed=42)
    assert r_file["ok"] and r_inline["ok"]
    assert r_file["yield_rate"] == r_inline["yield_rate"]


def test_criterion_a_surrogate_yield_at_bit_identical(tmp_path) -> None:
    from rfauto.service.uq_service import surrogate_yield_at

    samples = _write_samples(tmp_path, with_er=True)
    nominal = {"arm_len_mm": 20.0, "series_w_mm": 0.35, "er": 3.66}
    r_src = surrogate_yield_at(
        samples, nominal=nominal,
        tolerance_source={"fab_profile": "jlcpcb",
                          "material": "rogers4350b_h0.508"},
        n=3000, seed=42)
    r_hand = surrogate_yield_at(samples, _hand_sigmas(), nominal=nominal,
                                n=3000, seed=42)
    assert r_src["ok"] is True and r_hand["ok"] is True
    assert r_src["yield_rate"] == r_hand["yield_rate"]
    assert "tolerance_provenance" not in r_hand
    assert r_src["tolerance_provenance"]["er"]["class"] == "epsilon_r"


def test_criterion_a_fab_profile_yield_explicit_vs_profile(tmp_path) -> None:
    """fab_profile_yield 链：剖面派生 vs 显式 params 手写 tol——逐位一致。"""
    from rfauto.service.fab_service import fab_profile_yield

    nominal = {"w_mm": 1.0}
    spec = {"metric": "s11_db_max_in_band", "op": "max_below", "value": -17.5}
    r_prof = fab_profile_yield(
        _QuadModel(), nominal, spec=spec,
        tolerance_source={"fab_profile": "jlcpcb"}, n=2000, seed=7)
    r_hand = fab_profile_yield(
        _QuadModel(), nominal, spec=spec,
        tolerance_source={"params": {"w_mm": {"tol": 1.0 * (20.0 / 100.0)}}},
        n=2000, seed=7)
    assert r_prof["ok"] is True and r_hand["ok"] is True
    assert r_prof["distribution"] == "normal_additive_single_source"
    assert r_prof["tolerances"]["w_mm"] == 1.0 * (20.0 / 100.0) / K_SIGMA
    assert r_prof["yield_rate"] == r_hand["yield_rate"]
    assert r_prof["metric_stats"] == r_hand["metric_stats"]
    assert r_prof["cpk_per_spec"]["s11_db_max_in_band"]["cpk"] is not None


# ── 缺省行为零变化 + 错误路径 ────────────────────────────────────

def test_default_behavior_unchanged(tmp_path) -> None:
    """不传 tolerance_source：路径/键集零变化（无 provenance 键）。"""
    from rfauto.service.fab_service import fab_profile_yield
    from rfauto.service.uq_service import surrogate_yield

    samples = _write_samples(tmp_path, with_er=True)
    r = surrogate_yield(samples, {"series_w_mm": 0.01}, n=500, seed=1)
    assert r["ok"] is True
    assert "tolerance_provenance" not in r
    assert r["tolerances"] == {"series_w_mm": 0.01}
    # 缺少 tolerances 且无 tolerance_source → 原报错语义
    r2 = surrogate_yield(samples)
    assert r2["ok"] is False and "缺少 tolerances" in r2["errors"][0]
    # fab_profile_yield 缺省路径：均匀乘性、无 provenance/tolerances 键
    out = fab_profile_yield(
        _QuadModel(), {"w_mm": 1.0}, perturb_param="w_mm",
        spec={"metric": "s11_db_max_in_band", "op": "max_below",
              "value": -17.5},
        n=200, seed=1)
    assert out["ok"] is True
    assert out["distribution"] == "uniform_multiplicative"
    assert "tolerance_provenance" not in out and "tolerances" not in out
    # perturb_param 缺失且无 tolerance_source → 显式报错
    bad = fab_profile_yield(
        _QuadModel(), {"w_mm": 1.0},
        spec={"metric": "s11_db_max_in_band", "op": "max_below",
              "value": -17.5}, n=10)
    assert bad["ok"] is False and bad["errors"]


def test_tolerance_source_error_paths(tmp_path) -> None:
    from rfauto.service.uq_service import surrogate_yield

    samples = _write_samples(tmp_path, with_er=True)
    src = {"fab_profile": "jlcpcb", "material": "rogers4350b_h0.508"}
    # tolerances 与 tolerance_source 二选一
    r = surrogate_yield(samples, {"series_w_mm": 0.01},
                        tolerance_source=src, n=100)
    assert r["ok"] is False and "二选一" in r["errors"][0]
    # 未知剖面
    r = surrogate_yield(samples, tolerance_source={"fab_profile": "nope"},
                        n=100)
    assert r["ok"] is False and r["errors"]
    # 显式 params 含未知参数 → 不在搜索空间
    r = surrogate_yield(samples,
                        tolerance_source={"params": {"nope_mm": 0.1}},
                        n=100)
    assert r["ok"] is False and "不在搜索空间" in r["errors"][0]
    # 非法形态
    r = surrogate_yield(samples, tolerance_source=42, n=100)
    assert r["ok"] is False and r["errors"]
    # 裸剖面名引用形态
    r = surrogate_yield(samples, tolerance_source="jlcpcb", n=200, seed=3)
    assert r["ok"] is True
    assert r["tolerances"]["series_w_mm"] == \
        0.35 * (TRACE_PCT / 100.0) / K_SIGMA


# ── 判据 b：design_for_yield 端到端（DFM+MC+Cpk 一条 JSON 面）────

class _MLineModel:
    """mline kink 面 stub（P1 C4 同族：s11 = −40 + 150·|w/w_nom−1|）。

    锚定名义可参数化——细线 override 用例的扰动 σ 与判据都跟随名义
    （单源：名义×20%/3），模型锚必须与名义一致才非退化。
    """

    def __init__(self, w_nom: float = 1.113) -> None:
        self.w_nom = float(w_nom)

    def predict(self, params: dict) -> dict:
        w = float(params.get("w_mm", self.w_nom))
        return {"s11_db": -40.0 + 150.0 * abs(w / self.w_nom - 1.0)}


_SPECS = [{"metric": "s11_db", "op": "max_below", "value": -17.5}]


def test_criterion_b_design_for_yield_mline() -> None:
    from rfauto.service.fab_service import design_for_yield

    r = design_for_yield("mline", _MLineModel(), _SPECS, n=4000, seed=42)
    assert r["ok"] is True
    # DFM 清单（mline 名义线宽 1.113 过 jlcpcb 1oz 档）
    assert r["dfm"]["ran"] is True and r["dfm_pass"] is True
    assert r["dfm"]["facts"]["traces"] == ["w_mm"]
    # 良率 MC 非退化出数
    y = r["yield_mc"]["yield_rate"]
    assert 0.0 < y < 1.0
    assert r["n_draws"] == 4000
    # 单源 σ：名义 × ±20% / 3σ
    assert r["tolerances"]["w_mm"] == 1.113 * (TRACE_PCT / 100.0) / K_SIGMA
    assert r["tolerance_provenance"]["w_mm"]["source"] == \
        "fab_profile:jlcpcb:trace.tolerance_pct"
    # 逐规范 Cpk 出数
    entry = r["cpk_per_spec"]["s11_db"]
    assert entry["cpk"] is not None
    assert entry["op"] == "max_below" and entry["usl"] == pytest.approx(-17.5)
    assert r["cpk_min"] is not None


def test_criterion_b_dfm_fail_does_not_block_mc() -> None:
    """细线 override：DFM FAIL 如实列违规，MC 报数不阻断（判据 b）。"""
    from rfauto.service.fab_service import design_for_yield

    r = design_for_yield("mline", _MLineModel(0.08), _SPECS,
                         params={"w_mm": 0.08}, n=500, seed=1)
    assert r["ok"] is True
    assert r["dfm_pass"] is False
    assert any(v["code"] == "TRACE_BELOW_MIN" for v in r["dfm"]["violations"])
    assert 0.0 < r["yield_mc"]["yield_rate"] < 1.0
    # 扰动 σ 跟随 override 后的名义（单源：名义×20%/3）
    assert r["tolerances"]["w_mm"] == 0.08 * (TRACE_PCT / 100.0) / K_SIGMA


def test_design_for_yield_validation() -> None:
    from rfauto.service.fab_service import design_for_yield

    r = design_for_yield("no_such_template", _MLineModel(), _SPECS)
    assert r["ok"] is False and "未知模板" in r["errors"][0]
    r = design_for_yield("mline", _MLineModel(),
                         [{"metric": "s11_db", "op": "bogus", "value": -20}])
    assert r["ok"] is False and r["errors"]
    r = design_for_yield("mline", _MLineModel(), [])
    assert r["ok"] is False and r["errors"]
