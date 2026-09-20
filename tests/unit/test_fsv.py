"""D12 FSV 内核定向单元测试（确定性、无网络、无真机依赖）。

覆盖（验收列出的验证点）：
1. 恒等 -> GDM == 0 且等级 Excellent；
2. 纯常数偏移 -> FDM 恒 0、GDM == ADM（ADM 主导）；
2b. 2006 原始式 ADM（include_offset=False）对常数偏移不敏感（可复现 [1] 式 (1)）；
3. 仅高频细节扰动 -> FDM 主导、ADM ~ 0；
4. GDM == sqrt(ADM^2 + FDM^2) 逐点成立、且 mean(GDM) >= max(mean ADM, mean|FDM|)；
5. 扰动幅度扫描 -> GDM 均值单调不降、等级单调不升；
6. 分级边界两侧 -> 等级跳变正确（下界闭区间）；
7. 不等长曲线插值确定性 + 公共轴 = 重叠区间 + 较低点密度；
8. 频率轴乱序/降序 -> 与升序结果逐位相同；
9. 无重叠区间 / 点数过少 -> 明确报错；
10. 置信度直方图 + Grade/Spread（对照 [1] II.2 节例子）；
11. 入参不被就地修改、接受 list；
12. 交换两曲线 -> ADM/GDM 不变、FDM 反号（FDM 符号不代表优劣）。

公式来源见 src/rfauto/core/fsv.py 模块 docstring（[1] ACES Journal 2006 印刷页、
[2] ARMMS 渲染页、[3] Duffy IBIS 2021）。**未复现公开文献的数值测例**（未找到
带原始数据的公开 FSV 测例），故本文件只断言可解析/可定性验证的性质，不编造
参考数值。
"""

from __future__ import annotations

import itertools
import json

import numpy as np
import pytest

from rfauto.core.fsv import (
    GRADE_BOUNDS,
    GRADE_CODES,
    MIN_POINTS,
    confidence_histogram,
    fsv,
    grade_and_spread,
    grade_index_of,
    grade_of,
    to_jsonable,
)

# --------------------------------------------------------------------------- #
# 夹具 / 合成曲线
# --------------------------------------------------------------------------- #

def _base_curve(n: int = 201) -> tuple[np.ndarray, np.ndarray]:
    """平滑 S21 型谐振曲线（2.0-3.0GHz，2.5GHz 处深谷）。"""
    f = np.linspace(2.0, 3.0, n)
    y = -0.5 - 25.0 / (1.0 + ((f - 2.5) / 0.05) ** 2)
    return f, y


def _hf_ripple(n: int = 201, k: int = 61) -> np.ndarray:
    """归一化高频纹波（落在 Hi 段），幅值 1。"""
    return np.sin(2.0 * np.pi * k * np.arange(n) / n)


# --------------------------------------------------------------------------- #
# 1. 恒等
# --------------------------------------------------------------------------- #

def test_identity_is_zero_and_excellent() -> None:
    f, y = _base_curve()
    r = fsv(f, y, f, y)
    assert np.all(r["adm"] == 0.0)
    assert np.all(r["fdm"] == 0.0)
    assert np.all(r["gdm"] == 0.0)
    assert r["gdm_mean"] == 0.0
    assert r["gdm_grade"] == "Ex"
    assert r["adm_grade"] == "Ex"
    assert r["fdm_grade"] == "Ex"
    assert r["gdm_grade_level"] == 1
    assert r["gdm_spread"] == 1


# --------------------------------------------------------------------------- #
# 2. 常数偏移
# --------------------------------------------------------------------------- #

def test_constant_offset_is_adm_dominated() -> None:
    """常数偏移只改 DC 频点 -> Lo/Hi 不变 -> FDM 恒 0，GDM == ADM。"""
    f, y = _base_curve()
    r = fsv(f, y, f, y + 3.0)
    assert np.max(np.abs(r["fdm"])) < 1e-12
    assert np.allclose(r["gdm"], r["adm"], rtol=0.0, atol=1e-12)
    assert r["adm_mean"] > 0.0
    assert r["gdm_mean"] == pytest.approx(r["adm_mean"], abs=1e-12)


def test_constant_offset_invisible_in_2006_adm() -> None:
    """include_offset=False -> [1] 式 (1) 原始 ADM：常偏移落在 DC 频点，不可见。"""
    f, y = _base_curve()
    r = fsv(f, y, f, y + 3.0, include_offset=False)
    # 常偏移只改 DC 频点；Lo 段在浮点意义下不变（残差为 FFT 舍入噪声 ~1e-17）
    assert np.max(np.abs(r["adm"])) < 1e-12
    assert np.max(np.abs(r["gdm"])) < 1e-12
    assert r["gdm_grade"] == "Ex"


# --------------------------------------------------------------------------- #
# 3. 高频细节扰动
# --------------------------------------------------------------------------- #

def test_high_frequency_detail_is_fdm_dominated() -> None:
    f, y = _base_curve()
    r = fsv(f, y, f, y + 0.8 * _hf_ripple())
    assert r["adm_mean"] < 1e-9
    assert r["fdm_mean_abs"] > 0.05
    assert r["fdm_mean_abs"] > 100.0 * max(r["adm_mean"], 1e-12)
    assert r["gdm_mean"] == pytest.approx(r["fdm_mean_abs"], rel=1e-6)


# --------------------------------------------------------------------------- #
# 4. 恒等式与不等式
# --------------------------------------------------------------------------- #

def test_gdm_equals_hypot_of_adm_fdm() -> None:
    f, y = _base_curve()
    r = fsv(f, y, f, y + 0.4 * _hf_ripple() + 0.3)
    assert np.allclose(r["gdm"], np.hypot(r["adm"], r["fdm"]), rtol=1e-12, atol=1e-12)


def test_mean_gdm_dominates_component_means() -> None:
    """mean(sqrt(a^2+f^2)) >= max(mean a, mean|f|)（[1] Table IV 各行也满足）。"""
    f, y = _base_curve()
    for amp in (0.1, 0.4, 1.0):
        r = fsv(f, y, f, y + amp * _hf_ripple())
        assert r["gdm_mean"] >= r["adm_mean"] - 1e-12
        assert r["gdm_mean"] >= r["fdm_mean_abs"] - 1e-12


# --------------------------------------------------------------------------- #
# 5. 幅度扫描单调性
# --------------------------------------------------------------------------- #

def test_amplitude_sweep_gdm_monotone_and_grade_nonincreasing() -> None:
    f, y = _base_curve()
    amps = (0.0, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
    means: list[float] = []
    levels: list[int] = []
    for amp in amps:
        r = fsv(f, y, f, y + amp * _hf_ripple())
        means.append(float(r["gdm_mean"]))
        levels.append(grade_index_of(float(r["gdm_mean"])))
    diffs = np.diff(np.asarray(means))
    assert np.all(diffs >= -1e-12), f"GDM 均值非单调: {means}"
    assert all(b >= a for a, b in itertools.pairwise(levels)), f"等级非单调不升: {levels}"
    assert levels[0] == 0 and levels[-1] > levels[0], f"扫描未跨等级: {levels}"


# --------------------------------------------------------------------------- #
# 6. 分级边界
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "Ex"),
        (0.0999999, "Ex"),
        (0.1, "VG"),
        (0.1999999, "VG"),
        (0.2, "G"),
        (0.3999999, "G"),
        (0.4, "F"),
        (0.7999999, "F"),
        (0.8, "P"),
        (1.5999999, "P"),
        (1.6, "VP"),
        (1e6, "VP"),
    ],
)
def test_grade_boundaries_lower_inclusive(value: float, expected: str) -> None:
    assert grade_of(value) == expected


def test_grade_index_matches_bounds_and_rejects_nonfinite() -> None:
    assert GRADE_BOUNDS == (0.1, 0.2, 0.4, 0.8, 1.6)
    assert GRADE_CODES == ("Ex", "VG", "G", "F", "P", "VP")
    for i in range(6):
        mid = 0.0 if i == 0 else float(GRADE_BOUNDS[i - 1])
        assert grade_index_of(mid) == i
    with pytest.raises(ValueError):
        grade_index_of(float("nan"))
    with pytest.raises(ValueError):
        grade_of(float("inf"))


# --------------------------------------------------------------------------- #
# 7. 不等长曲线与公共轴
# --------------------------------------------------------------------------- #

def test_unequal_length_interpolation_deterministic() -> None:
    f_long, y_long = _base_curve(401)
    f_short, y_short = _base_curve(101)
    r1 = fsv(f_long, y_long, f_short, y_short)
    r2 = fsv(f_long, y_long, f_short, y_short)
    assert np.array_equal(r1["freq"], r2["freq"])
    assert np.array_equal(r1["gdm"], r2["gdm"])
    assert r1["gdm_mean"] == r2["gdm_mean"]
    assert r1["n_points"] == 101
    assert r1["freq"][0] == pytest.approx(2.0)
    assert r1["freq"][-1] == pytest.approx(3.0)
    # 同函数不同采样格 -> 线性插值下的差异应很小（平滑曲线）
    assert r1["gdm_mean"] < 0.05


def test_partial_overlap_uses_intersection_and_explicit_n_points() -> None:
    f, y = _base_curve(201)          # 2.0-3.0
    g = np.linspace(2.4, 3.6, 121)   # 2.4-3.6
    gy = -0.5 - 25.0 / (1.0 + ((g - 2.5) / 0.05) ** 2)
    r = fsv(f, y, g, gy)
    assert r["freq"][0] == pytest.approx(2.4)
    assert r["freq"][-1] == pytest.approx(3.0)
    assert r["n_points"] == 121
    r2 = fsv(f, y, g, gy, n_points=64)
    assert r2["n_points"] == 64
    assert r2["freq"][0] == pytest.approx(2.4)


# --------------------------------------------------------------------------- #
# 8. 乱序 / 降序横轴
# --------------------------------------------------------------------------- #

def test_descending_axes_match_ascending() -> None:
    f, y = _base_curve()
    r_up = fsv(f, y, f, y + 0.5 * _hf_ripple())
    r_dn = fsv(f[::-1], y[::-1], f[::-1], (y + 0.5 * _hf_ripple())[::-1])
    assert np.array_equal(r_up["gdm"], r_dn["gdm"])
    assert r_up["gdm_mean"] == r_dn["gdm_mean"]


def test_duplicate_and_unsorted_frequencies_are_sanitised() -> None:
    f, y = _base_curve(64)
    perm = np.argsort(np.sin(np.arange(64)))
    r_plain = fsv(f, y, f, y + 0.2)
    r_shuffled = fsv(f[perm], y[perm], f[perm], (y + 0.2)[perm])
    assert np.allclose(r_plain["gdm"], r_shuffled["gdm"], rtol=0, atol=1e-12)


# --------------------------------------------------------------------------- #
# 9. 错误路径
# --------------------------------------------------------------------------- #

def test_non_overlapping_axes_raise() -> None:
    fa = np.linspace(1.0, 2.0, 64)
    fb = np.linspace(3.0, 4.0, 64)
    with pytest.raises(ValueError, match="无公共横轴区间"):
        fsv(fa, np.ones(64), fb, np.ones(64))


def test_too_few_points_raise() -> None:
    f = np.linspace(2.0, 3.0, MIN_POINTS - 1)
    with pytest.raises(ValueError):
        fsv(f, np.zeros(MIN_POINTS - 1), f, np.zeros(MIN_POINTS - 1))


def test_length_mismatch_and_nonfinite_raise() -> None:
    f = np.linspace(2.0, 3.0, 64)
    with pytest.raises(ValueError, match="长度不一致"):
        fsv(f, np.zeros(32), f, np.zeros(64))
    bad = np.linspace(2.0, 3.0, 64)
    bad[3] = np.nan
    with pytest.raises(ValueError, match="NaN/Inf"):
        fsv(bad, np.zeros(64), f, np.zeros(64))


# --------------------------------------------------------------------------- #
# 10. 置信度 / Grade / Spread
# --------------------------------------------------------------------------- #

def test_confidence_histogram_sums_to_one() -> None:
    f, y = _base_curve()
    r = fsv(f, y, f, y + 0.6 * _hf_ripple())
    for key in ("confidence", "confidence_adm", "confidence_fdm"):
        hist = np.asarray(r[key], dtype=float)
        assert hist.shape == (6,)
        assert hist.sum() == pytest.approx(1.0)
        assert np.all(hist >= 0.0)


def test_grade_and_spread_matches_aces_examples() -> None:
    # [1] II.2 例子：Good/Fair/Poor 各 1/3 -> Spread 3、Grade 5
    h = np.zeros(6)
    h[2] = h[3] = h[4] = 1.0 / 3.0
    assert grade_and_spread(h) == (5, 3)
    # [1] II.2 例子：一半 Excellent 一半 Very Poor -> Spread 6、Grade 6
    h2 = np.zeros(6)
    h2[0] = h2[5] = 0.5
    assert grade_and_spread(h2) == (6, 6)
    # 全部 Excellent
    h3 = np.zeros(6)
    h3[0] = 1.0
    assert grade_and_spread(h3) == (1, 1)


def test_confidence_histogram_of_known_values() -> None:
    hist = confidence_histogram([0.05, 0.05, 0.05, 0.9])
    assert hist.tolist() == pytest.approx([0.75, 0.0, 0.0, 0.0, 0.25, 0.0])
    # 0.75 落在 Ex、0.25 落在 Poor -> 覆盖 85% 的最短相邻段是 [Ex..Poor] 共 5 段
    grade, spread = grade_and_spread(hist)
    assert (grade, spread) == (5, 5)


# --------------------------------------------------------------------------- #
# 11. 入参 / 序列化
# --------------------------------------------------------------------------- #

def test_inputs_not_mutated_and_lists_accepted() -> None:
    f, y = _base_curve(64)
    fl, yl = f.tolist(), y.tolist()
    f_copy, y_copy = list(fl), list(yl)
    r = fsv(fl, yl, fl, [v + 0.2 for v in yl])
    assert fl == f_copy and yl == y_copy
    assert r["n_points"] == 64
    assert isinstance(r["gdm"], np.ndarray)


def test_to_jsonable_is_json_serialisable() -> None:
    f, y = _base_curve()
    r = fsv(f, y, f, y + 0.3 * _hf_ripple())
    payload = to_jsonable(r)
    text = json.dumps(payload)
    back = json.loads(text)
    assert back["gdm_grade"] in GRADE_CODES
    assert len(back["gdm"]) == r["n_points"]
    assert back["n_points"] == r["n_points"]


# --------------------------------------------------------------------------- #
# 12. 交换对称性
# --------------------------------------------------------------------------- #

def test_swap_symmetry() -> None:
    f, y = _base_curve()
    yb = y + 0.5 * _hf_ripple() + 0.4
    ab = fsv(f, y, f, yb)
    ba = fsv(f, yb, f, y)
    assert np.allclose(ab["adm"], ba["adm"], rtol=1e-12, atol=1e-12)
    assert np.allclose(ab["gdm"], ba["gdm"], rtol=1e-12, atol=1e-12)
    assert np.allclose(ab["fdm"], -ba["fdm"], rtol=1e-12, atol=1e-12)
    assert ab["gdm_mean"] == pytest.approx(ba["gdm_mean"], rel=1e-12, abs=1e-12)
