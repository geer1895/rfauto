"""F-J.4 RF 工艺角五角 worst-case 集单测（round5 §三件 4 判据）。

判据锚（#122 先行，两条路径互证 #118）：
- 计数守恒：2^n 角全枚举恰好 2^n 条、corner_id 无重、每参数恰半数
  lo/半数 hi（n=1/2/3/5 全查）；
- 角方向物理自洽：RESPONSE_CLASS_TABLE 语义方向标注逐项钉（εr_hi→f_lo
  即 frequency 类取 εr=lo 使 f 极大等）+ ARCHETYPE_CORNERS 高频角=规格例
  εr_hi+tanδ_hi+thin_cu 口径；
- spread 极值定位恒等式：单调（线性）响应下 argmax/argmin 角与
  predict_extreme_corner 的 slope 符号预测**逐位一致**（corner_id、方向
  表、参数值三元全等；参数值来自同一 p.lo/p.hi 浮点，无算术路径差）；
  零斜率并列钉枚举序首个（方向 "lo"）；
- 双路径裁判：callable 路径与斜率表路径在线性响应上逐值一致
  （独立写法计算，approx rel=1e-12）。

边界（任务书判据）：空参数集 → ValueError；lo>hi → ValueError；
nominal 出带/bool/非有限 → ValueError。
"""

from __future__ import annotations

import json

import pytest

from rfauto.core.rf_process_corners import (
    ARCHETYPE_CORNERS,
    FIVE_CORNER_PARAM_NAMES,
    RESPONSE_CLASS_TABLE,
    THIEVING_TABLE,
    Corner,
    ProcessParam,
    build_five_corners,
    corner_injection_set,
    corner_spread,
    corner_spread_from_slopes,
    enumerate_corners,
    expected_extreme_directions,
    make_param,
    predict_extreme_corner,
    t_cu_param,
    t_cu_thieving_band_um,
)

#: 典型五角名义值（εr=materials.yaml ro4350b 口径、tanδ 同条目量级）
NOMINALS = {
    "etch_bias_um": 10.0,
    "t_cu_um": 35.0,
    "epsilon_r": 3.66,
    "tan_delta": 0.0037,
    "alignment_um": 37.5,
}

#: 单位测试参数集（dyadic 值：lo=0/nominal=0.5/hi=1，浮点全精确）
UNIT_PARAMS = [
    make_param(name, 0.5, 0.0, 1.0, unit="-", source="unit") for name in FIVE_CORNER_PARAM_NAMES
]


# ─── 1. 计数守恒 ───────────────────────────────────────────────────────────────


def test_five_corners_count_conservation():
    params = build_five_corners(NOMINALS)
    assert [p.name for p in params] == list(FIVE_CORNER_PARAM_NAMES)  # 位序契约
    corners = enumerate_corners(params)
    assert len(corners) == 2**5 == 32
    ids = [c.corner_id for c in corners]
    assert len(set(ids)) == 32  # id 无重
    assert ids[0] == "c00000" and ids[-1] == "c11111"
    for p in params:
        los = sum(1 for c in corners if c.directions[p.name] == "lo")
        his = sum(1 for c in corners if c.directions[p.name] == "hi")
        assert (los, his) == (16, 16)  # 每参数恰半数 lo/半数 hi


@pytest.mark.parametrize("n,expect", [(1, 2), (2, 4), (3, 8), (4, 16)])
def test_corner_count_generalization(n, expect):
    params = [make_param(f"p{j}", 0.5, 0.0, 1.0) for j in range(n)]
    corners = enumerate_corners(params)
    assert len(corners) == expect
    assert len({c.corner_id for c in corners}) == expect
    for p in params:
        assert sum(1 for c in corners if c.directions[p.name] == "lo") == expect // 2


def test_corner_values_match_directions_bitwise():
    params = build_five_corners(NOMINALS)
    by_name = {p.name: p for p in params}
    for c in enumerate_corners(params):
        for name, d in c.directions.items():
            p = by_name[name]
            if d == "lo":
                assert c.params[name] == p.lo  # 逐位（值即 p.lo 本身）
            else:
                assert c.params[name] == p.hi
            assert c.params[name] != (p.lo if d == "hi" else p.hi) or p.lo == p.hi


# ─── 2. 输入守卫与边界 ─────────────────────────────────────────────────────────


def _const_zero(p):
    return 0.0


def test_empty_param_set_valueerror():
    with pytest.raises(ValueError, match="不能为空"):
        enumerate_corners([])
    with pytest.raises(ValueError, match="不能为空"):
        corner_injection_set([])
    with pytest.raises(ValueError, match="不能为空"):
        corner_spread_from_slopes([], {})
    with pytest.raises(ValueError, match="不能为空"):
        predict_extreme_corner([], {})
    with pytest.raises(ValueError, match="不能为空"):
        corner_spread([], _const_zero)


def test_make_param_validation():
    with pytest.raises(ValueError, match=r"lo.*hi"):
        make_param("x", 1.0, 2.0, 1.0)  # lo>hi（任务书判据）
    with pytest.raises(ValueError, match="nominal"):
        make_param("x", 0.0, 1.0, 2.0)  # nominal < lo
    with pytest.raises(ValueError, match="nominal"):
        make_param("x", 3.0, 1.0, 2.0)  # nominal > hi
    with pytest.raises(ValueError, match="bool"):
        make_param("x", True, 0.0, 2.0)  # df7+⑯
    with pytest.raises(ValueError, match="bool"):
        make_param("x", 1.0, False, 2.0)
    with pytest.raises(ValueError, match="有限"):
        make_param("x", float("nan"), 0.0, 2.0)
    with pytest.raises(ValueError, match="有限"):
        make_param("x", 1.0, float("inf"), 2.0)
    with pytest.raises(ValueError, match="name"):
        make_param("", 1.0, 0.0, 2.0)
    # 边界合法：nominal 恰在带端、退化带（lo==hi）
    assert make_param("x", 0.0, 0.0, 2.0).lo == 0.0
    assert make_param("x", 2.0, 0.0, 2.0).hi == 2.0
    deg = make_param("x", 1.0, 1.0, 1.0)
    assert (deg.lo, deg.hi) == (1.0, 1.0)


def test_build_five_corners_key_validation():
    with pytest.raises(ValueError, match="缺"):
        build_five_corners({k: v for k, v in NOMINALS.items() if k != "tan_delta"})
    with pytest.raises(ValueError, match="多"):
        build_five_corners({**NOMINALS, "rogue": 1.0})
    with pytest.raises(ValueError, match="不在五角命名表"):
        build_five_corners(NOMINALS, bands={"rogue": (0.0, 1.0)})
    with pytest.raises(ValueError, match="lo > hi"):
        build_five_corners(NOMINALS, bands={"etch_bias_um": (5.0, 1.0)})
    # tan_delta 相对带基须 >0
    bad = {**NOMINALS, "tan_delta": 0.0}
    with pytest.raises(ValueError, match="tan_delta"):
        build_five_corners(bad)


def test_build_five_corners_default_bands():
    params = build_five_corners(NOMINALS)
    by = {p.name: p for p in params}
    assert (by["etch_bias_um"].lo, by["etch_bias_um"].hi) == (0.0, 20.0)
    assert (by["alignment_um"].lo, by["alignment_um"].hi) == (0.0, 75.0)
    assert (by["epsilon_r"].lo, by["epsilon_r"].hi) == (3.66 - 0.05, 3.66 + 0.05)  # ±0.05 绝对
    assert (by["tan_delta"].lo, by["tan_delta"].hi) == (0.0037 * 0.8, 0.0037 * 1.2)  # ±20% 相对
    assert by["t_cu_um"].nominal == 0.5 * (42.0 + 49.0)  # thieving 带中点
    # bands 显式覆盖：t_cu 直接给成品带，nominal 即三元组 nominal 本身
    over = build_five_corners(NOMINALS, bands={"t_cu_um": (30.0, 40.0)})
    tc = over[1]
    assert tc.name == "t_cu_um" and tc.nominal == 35.0
    assert (tc.lo, tc.hi) == (30.0, 40.0)
    # εr 带覆盖路径：nominal 落带内合法、出带报错
    er_over = build_five_corners(NOMINALS, bands={"epsilon_r": (3.0, 4.0)})
    assert (er_over[2].lo, er_over[2].hi) == (3.0, 4.0)
    with pytest.raises(ValueError, match="nominal"):
        build_five_corners(NOMINALS, bands={"epsilon_r": (3.7, 4.0)})


# ─── 3. spread 极值定位恒等式（判据核心） ─────────────────────────────────────


MIXED_SLOPES = {
    "etch_bias_um": 2.0,
    "t_cu_um": -1.0,
    "epsilon_r": -3.0,
    "tan_delta": 0.5,
    "alignment_um": -0.1,
}


def test_slope_spread_extreme_localization_identity():
    params = build_five_corners(NOMINALS)
    r0 = 1.25
    spread = corner_spread_from_slopes(params, MIXED_SLOPES, r_nominal=r0)
    pred_max = predict_extreme_corner(params, MIXED_SLOPES, maximize=True)
    pred_min = predict_extreme_corner(params, MIXED_SLOPES, maximize=False)
    # 逐位一致：id、方向表、参数值三元全等（值来自同一 p.lo/p.hi 浮点）
    assert spread["argmax_corner_id"] == pred_max.corner_id
    assert spread["argmax_directions"] == pred_max.directions
    assert spread["argmax_params"] == pred_max.params
    assert spread["argmin_corner_id"] == pred_min.corner_id
    assert spread["argmin_directions"] == pred_min.directions
    assert spread["argmin_params"] == pred_min.params
    # spread == max−min，且极值即该角 value（同列表元素，逐位）
    vals = {row["corner_id"]: row["value"] for row in spread["values"]}
    assert spread["spread"] == max(vals.values()) - min(vals.values())
    assert spread["argmax_params"] and vals[pred_max.corner_id] == max(vals.values())
    assert len(spread["values"]) == 32
    # 独立路径复核（#118）：测试侧独立求和重算 32 角
    by = {p.name: p for p in params}
    for c in enumerate_corners(params):
        manual = r0
        for name in FIVE_CORNER_PARAM_NAMES:
            manual += MIXED_SLOPES[name] * (c.params[name] - by[name].nominal)
        assert vals[c.corner_id] == pytest.approx(manual, rel=1e-12)


def test_callable_spread_and_slope_table_agree():
    r0 = 0.25
    nom = {p.name: p.nominal for p in UNIT_PARAMS}

    def lin_fn(p):
        acc = r0
        for name in FIVE_CORNER_PARAM_NAMES:
            acc = acc + MIXED_SLOPES[name] * (p[name] - nom[name])
        return acc

    spread_fn = corner_spread(UNIT_PARAMS, lin_fn)
    spread_s = corner_spread_from_slopes(UNIT_PARAMS, MIXED_SLOPES, r_nominal=r0)
    assert spread_fn["argmax_corner_id"] == spread_s["argmax_corner_id"]
    assert spread_fn["argmin_corner_id"] == spread_s["argmin_corner_id"]
    for row_fn, row_s in zip(spread_fn["values"], spread_s["values"], strict=True):
        assert row_fn["corner_id"] == row_s["corner_id"]
        assert row_fn["value"] == pytest.approx(row_s["value"], rel=1e-12)
    with pytest.raises(TypeError):
        corner_spread(UNIT_PARAMS, "not-callable")
    with pytest.raises(ValueError, match="缺参数"):
        corner_spread_from_slopes(UNIT_PARAMS, {"etch_bias_um": 1.0})

    def nan_fn(p):
        return float("nan")

    with pytest.raises(ValueError, match="有限"):
        corner_spread(UNIT_PARAMS, nan_fn)


def test_monotonic_response_matches_response_class_table():
    for cls in ("frequency", "loss"):
        dirs = expected_extreme_directions(cls)
        assert dirs  # 两类均有已声明方向
        slopes = {name: 0.0 for name in FIVE_CORNER_PARAM_NAMES}
        for name, d in dirs.items():
            slopes[name] = 1.0 if d == "hi" else -1.0
        spread = corner_spread_from_slopes(UNIT_PARAMS, slopes)
        # 每个已声明方向参数：极值角方向 == 方向表预测
        for name, d in dirs.items():
            assert spread["argmax_directions"][name] == d
        pred = predict_extreme_corner(UNIT_PARAMS, slopes, maximize=True)
        assert spread["argmax_params"] == pred.params  # 逐位
        assert spread["argmax_corner_id"] == pred.corner_id
    with pytest.raises(ValueError, match="response_class"):
        expected_extreme_directions("no_such_class")


def test_zero_slope_tie_break():
    zeros = {name: 0.0 for name in FIVE_CORNER_PARAM_NAMES}
    spread = corner_spread_from_slopes(UNIT_PARAMS, zeros, r_nominal=2.0)
    assert spread["spread"] == 0.0  # 全零斜率 → 平坦响应 spread=0
    assert spread["argmax_corner_id"] == "c00000"  # 并列钉枚举序首个
    assert spread["argmin_corner_id"] == "c00000"
    assert all(v["value"] == 2.0 for v in spread["values"])
    pred = predict_extreme_corner(UNIT_PARAMS, zeros, maximize=True)
    assert set(pred.directions.values()) == {"lo"}  # 零斜率并列方向钉 "lo"


# ─── 4. 方向表物理自洽与具名惯例角 ────────────────────────────────────────────


def test_response_class_table_physical_semantics():
    # 每类键集恰为五角、值域 ⊆ {"lo","hi",None}
    for _cls, table in RESPONSE_CLASS_TABLE.items():
        assert set(table) == set(FIVE_CORNER_PARAM_NAMES)
        assert all(v in ("lo", "hi", None) for v in table.values())
    # εr_hi→f_lo 语义：frequency 类取 εr=lo 使 f 极大（规格例的等价表述）
    assert RESPONSE_CLASS_TABLE["frequency"]["epsilon_r"] == "lo"
    # tanδ 一阶不移频（frequency 类不声明）
    assert RESPONSE_CLASS_TABLE["frequency"]["tan_delta"] is None
    # loss 类：tanδ_hi 介质损耗上；薄铜导体损耗上；线窄电流密度高损耗上
    assert RESPONSE_CLASS_TABLE["loss"]["tan_delta"] == "hi"
    assert RESPONSE_CLASS_TABLE["loss"]["t_cu_um"] == "lo"
    assert RESPONSE_CLASS_TABLE["loss"]["etch_bias_um"] == "hi"
    # 具名惯例角=规格例"高频角=εr_hi+tanδ_hi+thin_cu"口径
    hf = ARCHETYPE_CORNERS["high_freq_worst"]
    assert (hf["epsilon_r"], hf["tan_delta"], hf["t_cu_um"]) == ("hi", "hi", "lo")
    lf = ARCHETYPE_CORNERS["low_freq_worst"]
    for name in FIVE_CORNER_PARAM_NAMES:
        assert lf[name] == ("lo" if hf[name] == "hi" else "hi")  # 逐参数反向


def test_archetype_corner_ids_injection_set():
    params = build_five_corners(NOMINALS)
    inj = corner_injection_set(params)
    assert set(inj["archetype_corner_ids"]) == set(ARCHETYPE_CORNERS)
    by_id = {c.corner_id: c for c in enumerate_corners(params)}
    for name, cid in inj["archetype_corner_ids"].items():
        corner = by_id[cid]
        assert corner.directions == ARCHETYPE_CORNERS[name]
        for pname, d in corner.directions.items():
            p = next(x for x in params if x.name == pname)
            assert corner.params[pname] == (p.hi if d == "hi" else p.lo)


# ─── 5. 电镀集边（thieving）入角集 ────────────────────────────────────────────


def test_thieving_band_and_t_cu_param():
    # 20–40% 口径：isolated 上偏带 (×1.20, ×1.40)，dense = 目标口径
    assert t_cu_thieving_band_um(35.0, "isolated") == (42.0, 49.0)
    assert t_cu_thieving_band_um(35.0, "dense") == (35.0, 35.0)
    with pytest.raises(ValueError, match="density"):
        t_cu_thieving_band_um(35.0, "rogue")
    with pytest.raises(ValueError, match="target_um"):
        t_cu_thieving_band_um(0.0, "isolated")
    with pytest.raises(ValueError, match="bool"):
        t_cu_thieving_band_um(True, "isolated")
    p = t_cu_param(35.0, density="isolated")
    assert isinstance(p, ProcessParam) and p.name == "t_cu_um"
    assert (p.lo, p.hi) == (42.0, 49.0)
    assert p.nominal == 0.5 * (42.0 + 49.0)  # 带中点（单侧上偏带，目标值在带外）
    assert "isolated" in p.source and "35.0" in p.source  # 目标值留痕
    assert t_cu_param(35.0, density="dense").hi == 35.0
    # max_plus_pct 最大档（+40%）为 THIEVING_TABLE 上端口径
    assert max(b["max_plus_pct"] for b in THIEVING_TABLE.values()) == 40.0


# ─── 6. MC 注入集形态（tolerance/uq 面对齐） ──────────────────────────────────


def test_injection_set_shape():
    params = build_five_corners(NOMINALS)
    inj = corner_injection_set(params)
    assert inj["n_params"] == 5 and inj["n_corners"] == 32
    assert inj["nominal_params"] == {p.name: p.nominal for p in params}
    for p in params:
        # tolerance 面 ±半宽形态（ToleranceAnalyzer.analyze 的 tolerances 语义），逐位
        assert inj["tolerances_half_width"][p.name] == 0.5 * (p.hi - p.lo)
        assert inj["bounds"][p.name] == {"lo": p.lo, "hi": p.hi}
    corners = inj["corners"]
    assert len(corners) == 32
    lo_hi = {p.name: {p.lo, p.hi} for p in params}
    for c in corners:
        for name, v in c["params"].items():
            assert v in lo_hi[name]  # 角点值恰为端点（MC 支撑集端点）
    # 逐角 params dict 直接可作点求值入参
    def sum_fn(p):
        return sum(p.values())

    assert all(isinstance(sum_fn(c["params"]), float) for c in corners)


# ─── 7. JSON 可序列化（dataclass+to_dict） ───────────────────────────────────


def test_json_roundtrip():
    params = build_five_corners(NOMINALS)
    inj = corner_injection_set(params)
    spread = corner_spread_from_slopes(params, MIXED_SLOPES)
    corner: Corner = enumerate_corners(params)[3]
    payload = {
        "param": params[0].to_dict(),
        "corner": corner.to_dict(),
        "injection": inj,
        "spread": spread,
        "pred": predict_extreme_corner(params, MIXED_SLOPES).to_dict(),
    }
    text = json.dumps(payload, ensure_ascii=False)
    assert "c00000" in text and "c11111" in text
