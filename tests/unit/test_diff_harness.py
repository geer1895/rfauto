"""QM-11 差分测试 harness 定向单元测试（确定性、无网络、无真机依赖）。

三块验证面（任务书）：
1. **正例全过**：四族物理等价变换关系（无耗缩放/频率轴翻转/单位制切换/
   golden 恒等）在真实纯内核（calc_families 注册键）上全过——被测轴与
   QM-1 四族（互易/线性叠加/无源性/频移等价）刻意不重叠；
2. **负例注入全检出（自证可失败）**：每族关系注入违例内核/扭曲输出，
   check_metamorphic 必须判 ok=False；FSV 门对扭曲曲线判 DISAGREE；
   标量矩阵对篡改值判 DISAGREE——harness 不是恒真断言器；
3. **被测面回归**：golden 值全部取独立来源（切比雪夫多项式解析零点、
   ε 闭式、光速常数 C_MM_GHZ），禁同源自证（#118）。

harness 机制面：verdict 契约（等长/顺序/NaN 判败）、engine pair 矩阵
自动发现（全组合/星型/去重/exclude）、pointer 锚候选（仅 DISAGREE、
id 正则与 core/anchors.py 单源一致）、确定性重跑逐位相同。
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from rfauto.core.calc_families.registry import CALCULATOR_REGISTRY
from rfauto.core.diff_harness import (
    ANCHOR_ID_RE,
    FsvGateSpec,
    RelationVerdict,
    check_metamorphic,
    discover_engine_pairs,
    even_symmetry_relation,
    fsv_pair_gate,
    golden_identity_relation,
    linear_scale_relation,
    pair_matrix_curves,
    pair_matrix_scalar,
    pointer_anchor_candidates,
    slugify,
    wave_unit_product_relation,
)
from rfauto.core.fsv import fsv as _fsv_kernel

# --------------------------------------------------------------------------- #
# 被测内核收口（calc_families 注册键直调，不绕过注册表）
# --------------------------------------------------------------------------- #

_QWT = CALCULATOR_REGISTRY.get("quarter_wave_transformer").func
_REFL = CALCULATOR_REGISTRY.get("chebyshev_refl_fn").func
_PROTO = CALCULATOR_REGISTRY.get("chebyshev_prototype").func
_LAMG = CALCULATOR_REGISTRY.get("microstrip_lambda_g").func

_OMEGA_GRID = [round(-1.2 + 0.06 * i, 6) for i in range(41)]

_SCALE_INPUTS = [(50.0, 25.0, 2.4, 1.9), (30.0, 55.0, 3.1, 2.2), (75.0, 75.0, 5.8, 3.0)]


def _smooth_curve(n: int = 201, shift: float = 0.0, amp: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """平滑 S21 型谐振曲线（FSV 门正/负例共用底形）。"""
    f = np.linspace(2.0, 3.0, n)
    y = amp * (-0.5 - 25.0 / (1.0 + ((f - 2.5 - shift) / 0.05) ** 2))
    return f, y


# --------------------------------------------------------------------------- #
# §1 正例：四族关系在真实内核上全过
# --------------------------------------------------------------------------- #

def _run(kernel, inputs, transform, relation, *, tol, name):
    return check_metamorphic(kernel, inputs, transform, relation, tol=tol, name=name)


def test_scale_invariance_quarter_wave_transformer() -> None:
    """无耗缩放（common-mode 阻抗 ×k）：z0 正齐次 + 电学长度不变。"""
    kernel = lambda t: _QWT(  # noqa: E731 - harness 收口多参内核为单入参
        z_source_ohm=t[0], z_load_ohm=t[1], freq_ghz=t[2], eps_eff=t[3])
    verdicts = _run(
        kernel,
        _SCALE_INPUTS,
        lambda t: (2.0 * t[0], 2.0 * t[1], t[2], t[3]),
        linear_scale_relation(lambda o: o["z0_section_ohm"], scale_factor=2.0),
        tol=1.0,
        name="lossless_scale_z0",
    )
    assert len(verdicts) == len(_SCALE_INPUTS)
    assert all(v.ok for v in verdicts)
    # 电学长度（lambda_g_mm/length_mm）在缩放下逐位不变（同一内核口径）
    for t in _SCALE_INPUTS:
        a = _QWT(z_source_ohm=t[0], z_load_ohm=t[1], freq_ghz=t[2], eps_eff=t[3])
        b = _QWT(z_source_ohm=2 * t[0], z_load_ohm=2 * t[1], freq_ghz=t[2], eps_eff=t[3])
        assert a["length_mm"] == b["length_mm"]
        assert a["lambda_g_mm"] == b["lambda_g_mm"]


@pytest.mark.parametrize("series_key", ["s11_mag", "s21_mag"])
@pytest.mark.parametrize("order,rl_db", [(3, 0.1), (4, 20.0), (5, 0.5)])
def test_freq_flip_symmetry_chebyshev_refl_fn(series_key: str, order: int, rl_db: float) -> None:
    """频率轴翻转对称：实系数原型 |S(−Ω)| == |S(Ω)|（奇阶 s11 带符号翻转
    被偶幅度对称吸收——chebyshev_refl_fn 的 s11_mag 是带符号反射函数）。"""
    verdicts = _run(
        lambda om: _REFL(n=order, rz_db=rl_db, omega=list(om)),
        [_OMEGA_GRID],
        lambda om: [-x for x in om],
        even_symmetry_relation(lambda o: o["omega"], lambda o: o[series_key], tol=1e-9),
        tol=1.0,
        name="freq_flip_even",
    )
    assert verdicts[0].ok
    assert verdicts[0].metric == 0.0  # T_n 递推在 ±Ω 逐位对称 → 偶幅度零违例


def test_unit_product_microstrip_lambda_g() -> None:
    """单位制切换：λ0[mm]·f[GHz] == C_MM_GHZ（mm·GHz 光速单位系不变量）。"""
    cases = [
        dict(width_mm=1.1134, freq_ghz=2.4, epsilon_r=4.4, h_mm=1.0),
        dict(width_mm=0.5554, freq_ghz=10.0, epsilon_r=2.2, h_mm=0.508),
        dict(width_mm=2.0, freq_ghz=0.9, epsilon_r=10.2, h_mm=1.27),
    ]
    verdicts = _run(
        lambda kw: _LAMG(**kw),
        cases,
        lambda kw: dict(kw),
        wave_unit_product_relation(
            lambda kw: kw["freq_ghz"], lambda o: o["lambda_0_mm"], tol=1e-2),
        tol=1.0,
        name="unit_mm_ghz_product",
    )
    assert len(verdicts) == len(cases)
    assert all(v.ok for v in verdicts)


def test_golden_identity_chebyshev_prototype() -> None:
    """golden 恒等：ε 闭式与 T_3 解析零点（独立来源）逐位钉死。"""
    eps_true = 1.0 / math.sqrt(10.0 ** (0.1 / 10.0) - 1.0)
    rz_true = sorted(math.cos(math.pi * (2 * k + 1) / 6.0) for k in range(3))
    verdicts_eps = _run(
        lambda tz: _PROTO(order=3, rl_db=0.1, transmission_zeros=list(tz)),
        [()],
        lambda tz: tz,
        golden_identity_relation(lambda o: o["epsilon"], eps_true, tol=1e-8),
        tol=1.0,
        name="golden_eps",
    )
    assert verdicts_eps[0].ok
    out = _PROTO(order=3, rl_db=0.1)
    rz_kernel = sorted(float(v) for v in out["reflection_zeros"])
    assert max(abs(a - b) for a, b in zip(rz_kernel, rz_true, strict=True)) <= 1e-8


def test_golden_identity_light_speed_constant() -> None:
    """golden 恒等第二面：C_MM_GHZ 单源常量进 harness 缺省积。"""
    verdicts = _run(
        lambda kw: _LAMG(**kw),
        [dict(width_mm=1.1134, freq_ghz=2.4, epsilon_r=4.4, h_mm=1.0)],
        lambda kw: dict(kw),
        wave_unit_product_relation(
            lambda kw: kw["freq_ghz"], lambda o: o["lambda_0_mm"], tol=1e-2),
        tol=1.0,
        name="golden_c_mm_ghz",
    )
    assert verdicts[0].ok


# --------------------------------------------------------------------------- #
# §2 负例注入全检出（自证可失败）
# --------------------------------------------------------------------------- #

def test_negative_scale_violation_is_detected() -> None:
    """注入：变换不满足 common-mode（只缩放一端 2.02×）→ 正齐次必须判败。

    （输出级公共损坏对比值型正齐次关系不可见——这正是元变关系"对共同
    偏差免疫"的判据面；可检出的是**非等价变换**。）
    """
    verdicts = _run(
        lambda t: _QWT(z_source_ohm=t[0], z_load_ohm=t[1], freq_ghz=t[2], eps_eff=t[3]),
        _SCALE_INPUTS[:1],
        lambda t: (2.02 * t[0], 2.0 * t[1], t[2], t[3]),
        linear_scale_relation(lambda o: o["z0_section_ohm"], scale_factor=2.0),
        tol=1.0,
        name="lossless_scale_z0",
    )
    assert not verdicts[0].ok
    assert verdicts[0].metric > 1.0


def test_negative_scale_common_output_corruption_is_invisible() -> None:
    """比值型关系的判据面：输出级公共乘性损坏被正齐次关系免疫（比例不变）。"""

    def corrupted(t):
        good = _QWT(z_source_ohm=t[0], z_load_ohm=t[1], freq_ghz=t[2], eps_eff=t[3])
        bad = dict(good)
        bad["z0_section_ohm"] = round(good["z0_section_ohm"] * 1.5, 3)
        return bad

    verdicts = _run(
        corrupted,
        _SCALE_INPUTS[:1],
        lambda t: (2.0 * t[0], 2.0 * t[1], t[2], t[3]),
        linear_scale_relation(lambda o: o["z0_section_ohm"], scale_factor=2.0),
        tol=1.0,
        name="lossless_scale_z0",
    )
    assert verdicts[0].ok  # 两分支同乘 1.5 → 比值不变 → 关系仍满足（设计使然）


def test_negative_flip_violation_is_detected() -> None:
    """注入：偶幅度序列叠加**输入相关**的奇扰动 → 翻转对称必须判败。

    （扰动必须依赖输入：与输入无关的输出级公共损坏对两分支同形，不构成
    关系违例——见 scale 正例的同源判据面。）
    """
    def broken(om):
        out = _REFL(n=3, rz_db=0.1, omega=list(om))
        even_part = [0.05 * float(w) * float(w) for w in om]  # 偶扰动破奇序列的偶幅度对称
        return {
            "omega": list(out["omega"]),
            "s11_mag": [a + b for a, b in zip(out["s11_mag"], even_part, strict=True)],
        }

    verdicts = _run(
        broken,
        [_OMEGA_GRID],
        lambda om: [-x for x in om],
        even_symmetry_relation(lambda o: o["omega"], lambda o: o["s11_mag"], tol=1e-9),
        tol=1.0,
        name="freq_flip_even",
    )
    assert not verdicts[0].ok


def test_negative_flip_axis_mismatch_raises() -> None:
    """harness 配置错误（内核轴口径漂移）→ ValueError 原样上抛，不静默判。"""

    def axis_offset(om):
        # 内核轴 = 输入 + 1.5：非对称网格下翻转后轴值集 {1.5−w} ≠ {1.5+w}
        return _REFL(n=3, rz_db=0.1, omega=[x + 1.5 for x in om])

    nonsym = [0.0, 0.05, 0.15, 0.4, 1.0, 1.7]  # 非对称网格（对称网格翻转闭包会掩盖）
    with pytest.raises(ValueError, match="翻转轴值集不闭合"):
        _run(
            axis_offset,
            [nonsym],
            lambda om: [-x for x in om],
            even_symmetry_relation(lambda o: o["omega"], lambda o: o["s11_mag"], tol=1e-9),
            tol=1.0,
            name="freq_flip_even",
        )


def test_negative_unit_product_violation_is_detected() -> None:
    """注入：内核 λ0 放大 2%（绝对比较型关系不抵消公共损坏）→ 必须判败。"""
    def corrupted(kw):
        good = _LAMG(**kw)
        bad = dict(good)
        bad["lambda_0_mm"] = round(good["lambda_0_mm"] * 1.02, 3)
        return bad

    verdicts = _run(
        corrupted,
        [dict(width_mm=1.1134, freq_ghz=2.4, epsilon_r=4.4, h_mm=1.0)],
        lambda kw: dict(kw),
        wave_unit_product_relation(
            lambda kw: kw["freq_ghz"], lambda o: o["lambda_0_mm"], tol=1e-2),
        tol=1.0,
        name="unit_mm_ghz_product",
    )
    assert not verdicts[0].ok


def test_negative_golden_violation_and_nan_detected() -> None:
    """注入：ε 偏移 + NaN 输出 → golden 恒等必须判败（NaN 走 isfinite 判败）。"""
    def shifted(_tz):
        out = dict(_PROTO(order=3, rl_db=0.1))
        out["epsilon"] = out["epsilon"] * 1.001
        return out

    eps_true = 1.0 / math.sqrt(10.0 ** (0.1 / 10.0) - 1.0)
    v1 = _run(
        shifted, [()], lambda tz: tz,
        golden_identity_relation(lambda o: o["epsilon"], eps_true, tol=1e-8),
        tol=1.0, name="golden_eps")
    assert not v1[0].ok

    v2 = _run(
        lambda _tz: {"epsilon": float("nan")}, [()], lambda tz: tz,
        golden_identity_relation(lambda o: o["epsilon"], eps_true, tol=1e-8),
        tol=1.0, name="golden_eps")
    assert not v2[0].ok
    assert not math.isfinite(v2[0].metric)


def test_negative_tol_must_be_nonnegative() -> None:
    with pytest.raises(ValueError, match="tol"):
        check_metamorphic(
            lambda x: x, [1], lambda x: x,
            lambda p, a, b: 0.0, tol=-1.0)


def test_negative_relation_exception_is_config_error_not_violation() -> None:
    """relation 抛 ValueError = harness 配置错误（原样上抛），不吃掉掩盖。"""

    def bad_relation(point, out_a, out_b):
        raise ValueError("missing key")

    with pytest.raises(ValueError, match="missing key"):
        check_metamorphic(lambda x: x, [1], lambda x: x, bad_relation, tol=1.0)


# --------------------------------------------------------------------------- #
# §3 FSV 门判（正/负/退化三态）
# --------------------------------------------------------------------------- #

def test_fsv_gate_identity_is_agree() -> None:
    f, y = _smooth_curve()
    row = fsv_pair_gate(f, y, f, y, FsvGateSpec())
    assert row["decision"] == "AGREE"
    assert row["reason"] is None
    assert row["grade_level"] == 1
    assert row["gdm_mean"] == pytest.approx(0.0, abs=1e-12)


def test_fsv_gate_distortion_is_disagree_with_reason() -> None:
    f, y = _smooth_curve()
    f2, y2 = _smooth_curve(shift=0.15)  # 谐振整体搬移 = 特征差异
    row = fsv_pair_gate(f, y, f2, y2, FsvGateSpec())
    assert row["decision"] == "DISAGREE"
    assert row["reason"] is not None
    assert "grade_level" in row["reason"] or "spread" in row["reason"]


def test_fsv_gate_max_gdm_mean_subgate() -> None:
    f, y = _smooth_curve()
    _, yn = _smooth_curve()
    rng = np.random.default_rng(20261002)
    y_noise = yn + 0.01 * rng.standard_normal(yn.size)
    spec = FsvGateSpec(max_grade_level=3, max_spread=3, max_gdm_mean=0.0)
    row = fsv_pair_gate(f, y, f, y_noise, spec)
    assert row["decision"] == "DISAGREE"
    assert "gdm_mean" in row["reason"]
    # 同一噪声在只开等级门的宽档下 AGREE（子门独立生效的证据）
    row_wide = fsv_pair_gate(f, y, f, y_noise, FsvGateSpec(max_grade_level=3, max_spread=3))
    assert row_wide["decision"] == "AGREE"


def test_fsv_gate_degenerate_is_indeterminate() -> None:
    f, y = _smooth_curve(n=8)
    row = fsv_pair_gate(f, y, f, y, FsvGateSpec())
    assert row["decision"] == "INDETERMINATE"
    assert row["reason"] is not None
    assert row["reason"].startswith("fsv_rejected:")
    # 判定行数值字段保持 None（不伪造）
    assert row["grade_level"] is None


def test_fsv_gate_spec_validation() -> None:
    with pytest.raises(ValueError, match="max_grade_level"):
        FsvGateSpec(max_grade_level=0)
    with pytest.raises(ValueError, match="max_grade_level"):
        FsvGateSpec(max_grade_level=7)
    with pytest.raises(ValueError, match="max_spread"):
        FsvGateSpec(max_spread=9)
    with pytest.raises(ValueError, match="max_gdm_mean"):
        FsvGateSpec(max_gdm_mean=-0.1)


def test_fsv_gate_matches_kernel_verdict_fields() -> None:
    """门行数值字段与 core/fsv 直接结果一致（单一事实源，不二次实现）。"""
    f, y = _smooth_curve()
    f2, y2 = _smooth_curve(shift=0.15)
    row = fsv_pair_gate(f, y, f2, y2, FsvGateSpec())
    ref = _fsv_kernel(f, y, f2, y2)
    assert row["gdm_mean"] == pytest.approx(float(ref["gdm_mean"]))
    assert row["adm_mean"] == pytest.approx(float(ref["adm_mean"]))
    assert row["fdm_mean_abs"] == pytest.approx(float(ref["fdm_mean_abs"]))
    assert row["grade_level"] == int(ref["gdm_grade_level"])


# --------------------------------------------------------------------------- #
# §4 engine pair 矩阵自动发现 + pointer 锚候选
# --------------------------------------------------------------------------- #

def test_discover_engine_pairs_full_combinations() -> None:
    pairs = discover_engine_pairs(["openems", "hfss", "comsol", "openems", "hfss "])
    assert pairs == [("comsol", "hfss"), ("comsol", "openems"), ("hfss", "openems")]


def test_discover_engine_pairs_star_reference() -> None:
    pairs = discover_engine_pairs(["openems", "hfss", "fake"], reference="hfss")
    assert pairs == [("hfss", "fake"), ("hfss", "openems")]
    with pytest.raises(ValueError, match="reference"):
        discover_engine_pairs(["openems"], reference="hfss")


def test_discover_engine_pairs_exclude_and_degenerate() -> None:
    assert discover_engine_pairs(["a", "b", "c"], exclude=["b"]) == [("a", "c")]
    assert discover_engine_pairs(["a"]) == []
    assert discover_engine_pairs([]) == []


def test_pair_matrix_curves_all_agree_and_negative_engine() -> None:
    curves = {name: _smooth_curve() for name in ("engine_a", "engine_b", "engine_c")}
    rows = pair_matrix_curves(curves, gate=FsvGateSpec())
    assert len(rows) == 3
    assert [(r["engine_a"], r["engine_b"]) for r in rows] == [
        ("engine_a", "engine_b"), ("engine_a", "engine_c"), ("engine_b", "engine_c")]
    assert all(r["decision"] == "AGREE" for r in rows)

    # 注入坏引擎：只有含它的 pair 判 DISAGREE（矩阵定位能力）
    curves_bad = dict(curves)
    curves_bad["engine_c"] = _smooth_curve(shift=0.2)
    rows_bad = pair_matrix_curves(curves_bad, gate=FsvGateSpec())
    by_pair = {(r["engine_a"], r["engine_b"]): r["decision"] for r in rows_bad}
    assert by_pair[("engine_a", "engine_b")] == "AGREE"
    assert by_pair[("engine_a", "engine_c")] == "DISAGREE"
    assert by_pair[("engine_b", "engine_c")] == "DISAGREE"


def test_pair_matrix_curves_deterministic_rerun() -> None:
    curves = {name: _smooth_curve() for name in ("hfss", "openems", "meep")}
    r1 = pair_matrix_curves(curves, gate=FsvGateSpec())
    r2 = pair_matrix_curves(curves, gate=FsvGateSpec())
    assert r1 == r2


def test_pair_matrix_curves_star_reference() -> None:
    curves = {name: _smooth_curve() for name in ("hfss", "openems", "meep")}
    rows = pair_matrix_curves(curves, gate=FsvGateSpec(), reference="hfss")
    assert [(r["engine_a"], r["engine_b"]) for r in rows] == [
        ("hfss", "meep"), ("hfss", "openems")]


def test_pair_matrix_scalar_gates_and_double_zero() -> None:
    rows = pair_matrix_scalar({"openems": 4.976, "hfss": 5.6898, "fake": 5.0}, rel_tol=0.05)
    by_pair = {(r["engine_a"], r["engine_b"]): r for r in rows}
    assert by_pair[("fake", "hfss")]["decision"] == "DISAGREE"
    assert by_pair[("fake", "openems")]["decision"] == "AGREE"
    assert by_pair[("hfss", "openems")]["decision"] == "DISAGREE"
    assert by_pair[("hfss", "openems")]["reason"] is not None
    # 双零 = 无相对差，AGREE（0/0 特判不产 NaN）
    rows_zero = pair_matrix_scalar({"x": 0.0, "y": 0.0}, rel_tol=0.05)
    assert rows_zero[0]["decision"] == "AGREE"
    assert rows_zero[0]["rel_delta"] == 0.0


def test_pointer_anchor_candidates_only_from_disagree() -> None:
    rows = pair_matrix_scalar({"openems": 4.976, "hfss": 5.6898, "fake": 5.0}, rel_tol=0.05)
    cands = pointer_anchor_candidates(
        rows, template_family="patch_array", quantity="f_res", unit="GHz", version=1)
    ids = {c["anchor_id"] for c in cands}
    assert ids == {"patch_array.f_res.fake-hfss-v1", "patch_array.f_res.hfss-openems-v1"}
    for cand in cands:
        assert cand["kind"] == "pointer"
        assert cand["status"] == "experimental"
        assert cand["template_family"] == ["patch_array"]
        assert cand["quantity"]["unit"] == "GHz"
        assert set(cand["quantity"]["values"]) == {cand["engine_pair"]["engines"][0],
                                                   cand["engine_pair"]["engines"][1]}
        assert ANCHOR_ID_RE.match(cand["anchor_id"])
        assert cand["provenance"]["source"] == "diff_harness.pair_matrix"
        assert cand["provenance"]["decision"] == "DISAGREE"


def test_pointer_anchor_candidates_agree_only_is_empty() -> None:
    rows = pair_matrix_scalar({"a": 5.0, "b": 5.01}, rel_tol=0.05)
    assert pointer_anchor_candidates(rows, template_family="mline", quantity="f_res") == []


def test_pointer_anchor_candidates_slugifies_and_merges() -> None:
    rows = pair_matrix_scalar({"Engine A": 1.0, "Engine B": 2.0}, rel_tol=0.05)
    cands = pointer_anchor_candidates(
        rows, template_family="Slot Line", quantity="Z0-kOhm", unit="kOhm", version=3,
        provenance={"campaign": "qm11-smoke"},
        extra_quantity={"note": "双值分歧指针"},
    )
    assert len(cands) == 1
    cand = cands[0]
    assert cand["anchor_id"] == "slot_line.z0_kohm.engine_a-engine_b-v3"
    assert cand["quantity"]["values"] == {"Engine A": 1.0, "Engine B": 2.0}
    assert cand["quantity"]["note"] == "双值分歧指针"
    assert cand["provenance"]["campaign"] == "qm11-smoke"


def test_anchor_id_regex_matches_core_anchors_single_source() -> None:
    """harness 的 id 正则必须与 core/anchors.py 单源逐字节一致（拷贝漂移守卫）。"""
    from rfauto.core.anchors import _ANCHOR_ID_RE

    assert ANCHOR_ID_RE.pattern == _ANCHOR_ID_RE.pattern


def test_slugify_empty_is_unnamed() -> None:
    assert slugify("###") == "unnamed"
    assert slugify("OpenEMS (2025 R1)") == "openems_2025_r1"


# --------------------------------------------------------------------------- #
# §5 verdict 契约与不可变性
# --------------------------------------------------------------------------- #

def test_relation_verdict_to_dict_shape() -> None:
    v = RelationVerdict(relation="r", ok=True, metric=0.0, tol=1.0, detail="d")
    assert v.to_dict() == {"relation": "r", "ok": True, "metric": 0.0, "tol": 1.0,
                           "detail": "d"}


def test_check_metamorphic_preserves_input_order_and_detail() -> None:
    inputs = [3, 1, 2]
    verdicts = check_metamorphic(
        lambda x: 6, inputs, lambda x: x,
        golden_identity_relation(lambda o: o, 6, tol=1e-9),
        tol=1.0, name="g", detail_of=lambda p: f"pt={p}")
    assert [v.detail for v in verdicts] == ["pt=3", "pt=1", "pt=2"]
    assert all(v.ok for v in verdicts)
    assert all(v.relation == "g" for v in verdicts)


def test_harness_does_not_mutate_caller_inputs() -> None:
    grid = list(_OMEGA_GRID)
    snapshot = copy.deepcopy(grid)
    _run(
        lambda om: _REFL(n=3, rz_db=0.1, omega=list(om)),
        [grid],
        lambda om: [-x for x in om],
        even_symmetry_relation(lambda o: o["omega"], lambda o: o["s11_mag"], tol=1e-9),
        tol=1.0, name="flip")
    assert grid == snapshot
