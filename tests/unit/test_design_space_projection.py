"""DS-1 设计空间投影测试（ge8c 席C6）。

独立基准（#118/#300）：
- 解析锚一：二维高斯双簇沿 x 轴分离 → PC1 解释方差 >95%，两簇质心在
  PC1 轴上分离量 ≈ 簇间距（z-score 归一后可手算量级）；
- 解析锚二：严格共线数据 → PC2 解释方差 ≈ 0（<1e-10）；
- 旋转不变性：同数据旋转 90° 解释方差比不变（PCA 各向同性的解析性质）；
- 符号约定：SVD 符号二义性被确定性钉住（同输入坐标逐位一致）；
- 标注：verdict 传播 + 不可行成因标记（unreachable/marginal）+ undefined
  如实入账；零方差维如实降权；
- 负例：空点集/键集不齐/非数值参数显式报错。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rfauto.core.design_space_projection import (
    PROJECTION_SCHEMA,
    project_design_space,
    render_projection_markdown,
)


def _rows(a, b, verdict="reachable"):
    return [{"params": {"x": float(xi), "y": float(yi)},
             "verdict": verdict} for xi, yi in zip(a, b, strict=True)]


class TestAnalyticAnchors:
    def test_two_separated_clusters_pc1_dominant(self) -> None:
        rng = np.random.default_rng(3)
        c1 = rng.normal(0.0, 0.05, (40, 2)) + np.array([0.0, 0.0])
        c2 = rng.normal(0.0, 0.05, (40, 2)) + np.array([6.0, 0.0])
        # 两簇各打各的 verdict 标签（簇内散布与簇间分离分开裁判）
        rows = ([{"params": {"x": float(xi), "y": float(yi)},
                  "verdict": "reachable"} for xi, yi in c1] +
                [{"params": {"x": float(xi), "y": float(yi)},
                  "verdict": "unreachable"} for xi, yi in c2])
        r = project_design_space(rows)
        assert r["ok"] is True
        assert r["schema"] == PROJECTION_SCHEMA
        evr = r["explained_variance_ratio"]
        assert evr[0] > 0.95  # 簇间距沿 x → PC1 主导
        xs_r = [c["x"] for c in r["coords"] if c["verdict"] == "reachable"]
        xs_u = [c["x"] for c in r["coords"] if c["verdict"] == "unreachable"]
        # 两簇质心在 PC1 上的分离 ≈ 簇间距 6（原始量纲去均值 PCA）
        sep = abs(sum(xs_r) / len(xs_r) - sum(xs_u) / len(xs_u))
        assert sep == pytest.approx(6.0, abs=0.1)
        # 各簇散布远小于簇间分离（σ=0.05 量级）
        s_r = r["label_summary"]["reachable"]["spread"]
        s_u = r["label_summary"]["unreachable"]["spread"]
        assert max(s_r, s_u) < 0.5
        assert sep > 12 * max(s_r, s_u)

    def test_collinear_data_pc2_zero(self) -> None:
        t = np.linspace(0.0, 1.0, 25)
        rows = _rows(3.0 * t + 1.0, -2.0 * t + 4.0)  # 严格共线
        r = project_design_space(rows)
        assert r["explained_variance_ratio"][1] < 1e-10

    def test_rotation_invariance(self) -> None:
        rng = np.random.default_rng(7)
        data = rng.normal(0.0, 1.0, (50, 2)) @ np.array(
            [[2.0, 0.0], [0.0, 0.3]])
        rows_a = _rows(data[:, 0], data[:, 1])
        rot = np.array([[0.0, -1.0], [1.0, 0.0]])  # 90° 旋转
        data_r = data @ rot.T
        rows_b = _rows(data_r[:, 0], data_r[:, 1])
        ra = project_design_space(rows_a)
        rb = project_design_space(rows_b)
        assert ra["explained_variance_ratio"][0] == pytest.approx(
            rb["explained_variance_ratio"][0], abs=1e-9)
        assert ra["explained_variance_ratio"][1] == pytest.approx(
            rb["explained_variance_ratio"][1], abs=1e-9)

    def test_sign_convention_deterministic(self) -> None:
        rows = _rows([1.0, 2.0, 3.0, 4.0], [9.0, 5.0, 3.0, 1.0])
        a = project_design_space(rows)
        b = project_design_space(rows)
        assert json.dumps(a["coords"], sort_keys=True) == \
            json.dumps(b["coords"], sort_keys=True)
        # 符号约定：PC1 载荷绝对值最大分量为正
        loads = [v[0] for v in a["loadings"].values()]
        mx = max(loads, key=abs)
        assert mx > 0


class TestFeasibilityLabels:
    def test_verdict_propagation_and_tags(self) -> None:
        rows = ([{"params": {"x": 0.0 + i * 0.1, "y": 0.0},
                  "verdict": "unreachable"} for i in range(5)] +
                [{"params": {"x": 10.0 + i * 0.1, "y": 5.0},
                  "verdict": "reachable"} for i in range(5)] +
                [{"params": {"x": 5.0, "y": 2.5},
                  "verdict": "undefined"},
                 {"params": {"x": 5.1, "y": 2.4},
                  "verdict": "marginal"}])
        r = project_design_space(rows)
        s = r["label_summary"]
        assert s["unreachable"]["n"] == 5
        assert s["reachable"]["n"] == 5
        assert s["undefined"]["n"] == 1
        assert s["marginal"]["n"] == 1
        assert s["unreachable"]["is_infeasibility_tag"] is True
        assert s["marginal"]["is_infeasibility_tag"] is True
        assert s["undefined"]["is_infeasibility_tag"] is False
        assert s["undefined"]["share"] == pytest.approx(1 / 12)
        # 份额归一
        assert sum(v["share"] for v in s.values()) == pytest.approx(1.0)

    def test_default_verdict_undefined(self) -> None:
        r = project_design_space([{"params": {"x": 0.0, "y": 1.0}},
                                  {"params": {"x": 1.0, "y": 0.0}}])
        assert r["coords"][0]["verdict"] == "undefined"

    def test_zero_variance_dim_honest(self) -> None:
        rows = _rows([1.0, 2.0, 3.0], [5.0, 5.0, 5.0])  # y 恒定
        r = project_design_space(rows)
        assert r["n_zero_variance_dims"] == 1
        assert "零方差" in r["note"]
        assert r["ok"] is True


class TestNegatives:
    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="不可为空"):
            project_design_space([])

    def test_empty_params(self) -> None:
        with pytest.raises(ValueError, match="params 不可为空"):
            project_design_space([{"params": {}}])

    def test_mismatched_keys(self) -> None:
        with pytest.raises(ValueError, match="键集不一致"):
            project_design_space([{"params": {"x": 1.0, "y": 2.0}},
                                  {"params": {"x": 1.0}}])

    def test_nonfinite_param(self) -> None:
        with pytest.raises(ValueError, match="非有限"):
            project_design_space([{"params": {"x": float("nan"), "y": 1.0}},
                                  {"params": {"x": 1.0, "y": 2.0}}])

    def test_non_numeric_param(self) -> None:
        with pytest.raises(ValueError):
            project_design_space([{"params": {"x": "wide", "y": 1.0}},
                                  {"params": {"x": 1.0, "y": 2.0}}])


class TestMarkdown:
    def test_render(self) -> None:
        rows = ([{"params": {"x": float(i), "y": float(i) * 2},
                  "verdict": "marginal"} for i in range(4)] +
                [{"params": {"x": 10.0 + i, "y": 2.0},
                  "verdict": "reachable"} for i in range(4)])
        r = project_design_space(rows)
        md = render_projection_markdown(r)
        assert "解释方差比" in md
        assert "marginal" in md and "reachable" in md
        assert "不可行成因" in md

    def test_render_failure(self) -> None:
        md = render_projection_markdown({"ok": False, "errors": ["x"]})
        assert "失败" in md
