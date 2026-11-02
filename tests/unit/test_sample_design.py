"""Taguchi 正交表规范性质钉（D1-2 修复回归，审查批 2026-10-04）。

背景（runs/review_ge8e/d1_opt_linkage/REPORT.md D1-1/D1-2）：旧 L16(2^15)/
L27(3^13) 硬编码表实测 35/105、32/78 列对非正交（两列组合 (a,b) 计数
不等）——"两两因子水平均衡"承诺失守。修复=素数幂有限域线性型构造
程序化生成（sample_design._linear_oa），本文件钉规范性质（行数/列数/
值域/任意两列组合逐格等频/单列水平均衡）+ taguchi_points API 行为。
"""

from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.optimization.sample_design import (
    _TAGUCHI_ARRAYS,
    _linear_oa,
    _verify_linear_oa,
    taguchi_points,
)

#: (q, m) → (行数 q^m, 列数 (q^m−1)/(q−1))——五张表全部出自同一构造。
_EXPECTED_SHAPES = {
    ("2", 3): (2, 2),
    ("2", 7): (2, 3),
    ("2", 15): (2, 4),
    ("3", 4): (3, 2),
    ("3", 13): (3, 3),
}


class TestLinearOaProperties:
    @pytest.mark.parametrize("key", sorted(_EXPECTED_SHAPES))
    def test_table_shape_and_full_orthogonality(self, key):
        """行数=q^m、列数=(q^m−1)/(q−1)、任意两列组合逐格等频（零违规）。"""
        q, m = _EXPECTED_SHAPES[key]
        array = _TAGUCHI_ARRAYS[key]
        n_rows, n_cols = len(array), len(array[0])
        assert n_rows == q ** m
        assert n_cols == (q ** m - 1) // (q - 1)
        assert all(len(r) == n_cols for r in array)
        assert _verify_linear_oa(array, q) == []

    @pytest.mark.parametrize("key", sorted(_EXPECTED_SHAPES))
    def test_per_column_level_balance(self, key):
        """单列水平均衡：每列各水平出现次数相等（q^m/q）。"""
        q, m = _EXPECTED_SHAPES[key]
        array = _TAGUCHI_ARRAYS[key]
        per_col = q ** (m - 1)
        for c in range(len(array[0])):
            col = [array[r][c] for r in range(len(array))]
            assert sorted(set(col)) == list(range(q))
            assert all(col.count(v) == per_col for v in range(q)), (
                f"{key} 列 {c} 水平不均衡")

    def test_construction_matches_registry_tables(self):
        """注册表=构造器产物（单一事实来源，无手抄副本回流失效面）。"""
        for (lvl, cap), rows in _TAGUCHI_ARRAYS.items():
            m = _EXPECTED_SHAPES[(lvl, cap)][1]
            assert rows == _linear_oa(int(lvl), m)


class TestTaguchiPointsApi:
    def test_two_level_15_factors_full_capacity(self):
        """15 因子 2 水平 → L16 全容量 16 点、零截断（D1-2 修复后仍正交）。"""
        bounds = {f"x{i}": (0.0, 1.0) for i in range(15)}
        out = taguchi_points(bounds, n_levels=2)
        assert len(out["points"]) == 16
        assert out["design"]["truncated"] == []
        # 任意两因子组合 2×2 逐格等频（各 4 次）
        names = sorted(bounds)
        for a, b in combinations(names, 2):
            counts: dict[tuple[float, float], int] = {}
            for pt in out["points"]:
                key = (round(pt[a], 9), round(pt[b], 9))
                counts[key] = counts.get(key, 0) + 1
            assert set(counts.values()) == {4}, (a, b, counts)

    def test_three_level_13_factors_l27(self):
        """13 因子 3 水平 → L27 全容量 27 点（坏表 32/78 列对已撤）。"""
        bounds = {f"p{i}": (0.0, 2.0) for i in range(13)}
        out = taguchi_points(bounds, n_levels=3)
        assert len(out["points"]) == 27
        assert out["design"]["truncated"] == []
        names = sorted(bounds)
        for a, b in combinations(names, 2):
            counts: dict[tuple[float, float], int] = {}
            for pt in out["points"]:
                key = (round(pt[a], 9), round(pt[b], 9))
                counts[key] = counts.get(key, 0) + 1
            assert set(counts.values()) == {3}, (a, b)

    def test_level_values_mapping_and_truncation(self):
        """3 水平取 [low, mid, high]；超容量因子固定中位并登记 truncated。"""
        out = taguchi_points({"a": (0.0, 2.0), "b": (10.0, 20.0),
                              "c": (-1.0, 1.0)}, n_levels=3)
        assert len(out["points"]) == 9
        assert set(round(p["a"], 9) for p in out["points"]) == {0.0, 1.0, 2.0}
        # 17 个 3 水平因子 → 最大表 L27(13 列)，溢出 4 因子固定中位
        # （截断按 sorted(bounds) 字典序取前 13：y0,y1,y10..y16,y2..）
        bounds = {f"y{i}": (0.0, 2.0) for i in range(17)}
        out17 = taguchi_points(bounds, n_levels=3)
        kept = sorted(bounds)[:13]
        truncated = sorted(set(bounds) - set(kept))
        assert out17["design"]["truncated"] == truncated
        assert all(p[t] == 1.0 for p in out17["points"] for t in truncated)

    def test_bad_n_levels_rejected(self):
        with pytest.raises(ValueError, match="n_levels"):
            taguchi_points({"a": (0, 1)}, n_levels=4)
