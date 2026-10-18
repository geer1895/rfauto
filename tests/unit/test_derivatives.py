"""XD-3 core/derivatives 单测：三档偏导 + 链式组装 + 三方互证门（全离线）。

已知真值回收（#118 双源）：闭式解析雅可比即真值源，FD/CS 为被测源；
门槛语义专测：坏解析必被抓、CS 误用（|x| 非解析点）必被抓——数值内
核入库门槛模板的行为证据。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.derivatives import (
    DerivativeComponent,
    FunctionComponent,
    chain_jacobian,
    check_partials,
    cs_jacobian,
    fd_jacobian,
)

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

X0 = np.array([0.3, 0.8])


def _f(v: np.ndarray) -> np.ndarray:
    return np.array([np.sin(v[0]) * np.exp(v[1]), v[0] ** 2 + v[1] ** 2])


def _jf(v: np.ndarray) -> np.ndarray:
    return np.array([[np.cos(v[0]) * np.exp(v[1]),
                      np.sin(v[0]) * np.exp(v[1])],
                     [2.0 * v[0], 2.0 * v[1]]])


def _g(v: np.ndarray) -> np.ndarray:
    return np.array([v[0] ** 2, np.exp(v[1])])


def _jg(v: np.ndarray) -> np.ndarray:
    return np.array([[2.0 * v[0], 0.0], [0.0, np.exp(v[1])]])


def _h(v: np.ndarray) -> np.ndarray:
    return np.array([np.log(v[0] + 1.0) + v[1]])


def _jh(v: np.ndarray) -> np.ndarray:
    return np.array([[1.0 / (v[0] + 1.0), 1.0]])


class TestJacobians:
    def test_fd_accuracy_vs_analytic(self):
        j_fd = fd_jacobian(_f, X0)
        assert float(np.max(np.abs(j_fd - _jf(X0)))) < 1e-7

    def test_cs_machine_precision_vs_analytic(self):
        """复步长达机器精度（Martins 2003：O(h²) 无减法消去）。"""
        j_cs = cs_jacobian(_f, X0)
        assert float(np.max(np.abs(j_cs - _jf(X0)))) < 1e-10


class TestChainRule:
    def test_analytic_chain_matches_closed_form(self):
        cg = FunctionComponent(_g, jac_fn=_jg, n_in=2, n_out=2,
                               mode="analytic")
        ch = FunctionComponent(_h, jac_fn=_jh, n_in=2, n_out=1,
                               mode="analytic")
        total, used = chain_jacobian([cg, ch], X0)
        closed = _jh(_g(X0)) @ _jg(X0)
        assert float(np.max(np.abs(total - closed))) < 1e-12
        assert used == ["analytic", "analytic"]

    def test_mixed_mode_chain_within_fd_tolerance(self):
        """cs→fd 混档链与闭式一致到 FD 精度（组装与档位解耦）。"""
        cg = FunctionComponent(_g, jac_fn=_jg, n_in=2, n_out=2, mode="cs")
        ch = FunctionComponent(_h, jac_fn=_jh, n_in=2, n_out=1, mode="fd")
        total, used = chain_jacobian([cg, ch], X0)
        closed = _jh(_g(X0)) @ _jg(X0)
        assert float(np.max(np.abs(total - closed))) < 1e-6
        assert used == ["cs", "fd"]

    def test_broken_chain_dims_rejected(self):
        """1→2 维断裂（上游 1 维输出 vs 下游 2 维输入）显式拒绝。"""
        cg = FunctionComponent(_g, jac_fn=_jg, n_in=2, n_out=2)
        ch = FunctionComponent(_h, jac_fn=_jh, n_in=2, n_out=1)
        with pytest.raises(ValueError, match="链维度断裂"):
            chain_jacobian([ch, cg], X0)  # ch 输出 1 维，cg 需要 2 维输入


class TestCheckPartialsGate:
    def test_healthy_component_passes(self):
        """健康组件：analytic vs cs 达机器精度、vs fd 达 FD 精度 → ok。"""
        comp = FunctionComponent(_f, jac_fn=_jf, n_in=2, n_out=2,
                                 mode="analytic")
        rep = check_partials(comp, X0)
        assert rep["ok"] and rep["analytic_available"]
        assert rep["rel_err"]["analytic_vs_cs"] < 1e-10
        assert rep["rel_err"]["analytic_vs_fd"] < 1e-6

    def test_broken_analytic_caught(self):
        """坏解析（漏一项）必被抓——入库门槛的负例证据。"""
        def jf_bad(v: np.ndarray) -> np.ndarray:
            j = _jf(v).copy()
            j[0, 1] = 0.0  # 坏：∂f₁/∂x₂ 抹零
            return j

        comp = FunctionComponent(_f, jac_fn=jf_bad, n_in=2, n_out=2,
                                 mode="analytic")
        rep = check_partials(comp, X0)
        assert not rep["ok"] and rep["failures"]

    def test_cs_precondition_trap_caught(self):
        """|x| 非解析点 CS 失效（返回 0 而非次导数）——门槛拦下 CS 误用
        （coupling_gradient.py 复中间链陷阱的通用形态）。"""
        def f_abs(v: np.ndarray) -> np.ndarray:
            return np.array([np.abs(v[0])])

        def j_sign(v: np.ndarray) -> np.ndarray:
            return np.array([[np.sign(v[0])]])

        comp = FunctionComponent(f_abs, jac_fn=j_sign, n_in=1, n_out=1,
                                 mode="analytic")
        rep = check_partials(comp, np.array([0.5]))
        assert not rep["ok"]
        assert rep["rel_err"]["analytic_vs_cs"] > 1.0

    def test_no_analytic_cross_check(self):
        """无解析档（声明 cs）：fd vs cs 跨证放行。"""
        comp = FunctionComponent(_f, n_in=2, n_out=2, mode="cs")
        rep = check_partials(comp, X0)
        assert rep["ok"]
        assert not rep["analytic_available"]
        assert rep["rel_err"]["fd_vs_cs"] < 1e-6

    def test_analytic_declared_but_missing_downgrades(self):
        """声明 analytic 未实现 → 降档 fd 且实际档如实透出。"""

        class _NoAnalytic(DerivativeComponent):
            partials_mode = "analytic"
            n_in = 2
            n_out = 2

            def compute(self, x: np.ndarray) -> np.ndarray:
                return _f(x)

        comp = _NoAnalytic()
        jac, used = comp.jacobian(X0)
        assert used == "fd" and jac.shape == (2, 2)
