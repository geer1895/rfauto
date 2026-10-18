"""XD-3 微分包统一件：declare_partials 三档 + 链式总导数 + 三方互证门。

池 P3 圈定件（aurora_e W5-S22；crossdomain R20 XD-3）。OpenMDAO
"组件声明偏导 + 框架组装 + 互证"三段式的最小确定性实现（零新依赖，
纯 numpy/scipy-free——FD 与复步长都手写闭式）：

1. **三档偏导声明**（declare_partials 语义）：组件按输出×输入声明偏导
   的供给档——``analytic``（组件自带解析雅可比，最可信）／``fd``（中心
   差分，通用兜底）／``cs``（复步长）；组件缺省档 ``partials_mode``。
2. **链式总导数组装**：组件顺序链（合成→仿真→后处理的抽象）总雅可比
   = J_N···J_1（链式法则，维度互检）。
3. **check_partials 三方互证**：解析 vs FD vs CS 逐对相对误差——本仓
   数值内核入库门槛模板（#118 双源语义：任何"给梯度的内核"必须经
   独立路径对拍才能入库/采信）。

法源：
- 复步长：Martins-Sturdza-Alonso, "The Complex-Step Derivative
  Approximation", AIAA Journal 41(9), 2003——**适用前提 = 实点处中间值
  全实且复解析**；复中间链（复 LU 等）必然失效，本仓实证见
  core/coupling_gradient.py 头注（np.abs 等非解析算子同理失效——专测
  钉住，门槛据此能抓出"CS 误用"）；
- FD：中心差分 O(h²) 截断 vs 舍入的经典权衡（Sauer, Numerical
  Analysis §5.6 口径），缺省 h=1e-6 适配 O(1) 尺度目标。

分层：core 层纯函数/纯组件（零 IO 零日志依赖）；首个消费面按方案口径
为 tolerance_allocation/inverse design（长线），本件只立内核与门槛。
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from typing import Any

import numpy as np

__all__ = [
    "PARTIAL_MODES",
    "DerivativeComponent",
    "FunctionComponent",
    "chain_jacobian",
    "check_partials",
    "cs_jacobian",
    "fd_jacobian",
]

#: 偏导供给档（键面固定；新档须同时补 jacobian 分派与互证语义）
PARTIAL_MODES = ("analytic", "fd", "cs")

#: 逐对相对误差的分母下限（防 |ref|≈0 时除爆；绝对差兜底语义）
_REL_FLOOR = 1e-12


def fd_jacobian(
    f: Callable[[np.ndarray], np.ndarray],
    x: np.ndarray,
    *,
    eps: float = 1e-6,
) -> np.ndarray:
    """中心差分雅可比（n_in→n_out；f 返回任意维实向量）。"""
    x0 = np.asarray(x, dtype=float)
    f0_shape = np.atleast_1d(np.asarray(f(x0), dtype=float)).size
    jac = np.zeros((f0_shape, x0.size))
    for i in range(x0.size):
        dx = np.zeros_like(x0)
        dx[i] = max(eps, abs(x0[i]) * eps)
        fp = np.atleast_1d(np.asarray(f(x0 + dx), dtype=float))
        fm = np.atleast_1d(np.asarray(f(x0 - dx), dtype=float))
        jac[:, i] = (fp - fm) / (2.0 * dx[i])
    return jac


def cs_jacobian(
    f: Callable[[np.ndarray], np.ndarray],
    x: np.ndarray,
    *,
    h: float = 1e-20,
) -> np.ndarray:
    """复步长雅可比（Im f(x+i·h·e_k)/h；Martins 2003 式 (5)）。

    前提（调用方保证，门槛 check_partials 负责抓误用）：f 在实点 x 处
    全实中间值且复解析——np.abs/复矩阵分解等算子下结果非导数（静默错
    值，非异常）。
    """
    x0 = np.asarray(x, dtype=float)
    x0c = x0.astype(complex)
    f0 = np.atleast_1d(np.asarray(f(x0c), dtype=complex))
    jac = np.zeros((f0.size, x0.size))
    for i in range(x0.size):
        xc = x0c.copy()
        xc[i] += 1j * h
        fc = np.atleast_1d(np.asarray(f(xc), dtype=complex))
        jac[:, i] = fc.imag / h
    return jac


class DerivativeComponent:
    """偏导组件基类（OpenMDAO declare_partials 语义的最小确定性版）。

    子类实现 ``compute``（正向映射）与（如走 analytic 档）
    ``analytic_jacobian``；partials_mode 声明缺省供给档。
    """

    #: 偏导供给档（子类按可信度声明；fd 为通用兜底缺省）
    partials_mode: str = "fd"
    n_in: int = 0
    n_out: int = 0

    def compute(self, x: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def analytic_jacobian(self, x: np.ndarray) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError(
            "组件未实现 analytic_jacobian（partials_mode 不应声明 analytic）")

    def jacobian(
        self, x: np.ndarray, mode: str | None = None,
    ) -> tuple[np.ndarray, str]:
        """按档取雅可比；返回 (J, 实际使用档)——实际档可与声明档不同
        （analytic 未实现时自动降 fd，报告面如实透出降档事实）。

        cs 档走 ``fn`` 原函数（本类暴露 fn 属性时，如 FunctionComponent）
        ——compute 的 float 收敛会截断复中间量（ComplexWarning 丢弃虚部
        ⇒ CS 退化为全零雅可比，实测门槛被"对的理由"误触发）；自定义
        子类（无 fn 属性）声明 cs 档时须保证 compute 复解析且不截断
        虚部（Martins 2003 前提，check_partials 负责终验）。
        """
        m = mode or self.partials_mode
        if m not in PARTIAL_MODES:
            raise ValueError(f"未知偏导档: {m}，可用: {PARTIAL_MODES}")
        if m == "analytic":
            try:
                return (np.atleast_2d(
                    np.asarray(self.analytic_jacobian(x), dtype=float)),
                    "analytic")
            except NotImplementedError:
                m = "fd"  # 声明 analytic 但未实现：降档并如实透出
        if m == "cs":
            return (cs_jacobian(getattr(self, "fn", self.compute), x), "cs")
        return (fd_jacobian(self.compute, x), "fd")


class FunctionComponent(DerivativeComponent):
    """函数组件：compute=fn，analytic 档可选注入 jac_fn。"""

    def __init__(
        self,
        fn: Callable[[np.ndarray], np.ndarray],
        *,
        n_in: int,
        n_out: int,
        jac_fn: Callable[[np.ndarray], np.ndarray] | None = None,
        mode: str = "fd",
        name: str = "component",
    ) -> None:
        if mode not in PARTIAL_MODES:
            raise ValueError(f"未知偏导档: {mode}，可用: {PARTIAL_MODES}")
        self.fn = fn
        self.n_in = int(n_in)
        self.n_out = int(n_out)
        self.jac_fn = jac_fn
        self.partials_mode = mode
        self.name = str(name)

    def compute(self, x: np.ndarray) -> np.ndarray:
        return np.atleast_1d(np.asarray(self.fn(x), dtype=float))

    def analytic_jacobian(self, x: np.ndarray) -> np.ndarray:
        if self.jac_fn is None:
            raise NotImplementedError
        return np.atleast_2d(np.asarray(self.jac_fn(x), dtype=float))


def chain_jacobian(
    components: list[DerivativeComponent],
    x: np.ndarray,
    *,
    mode: str | None = "declared",
) -> tuple[np.ndarray, list[str]]:
    """链式总雅可比 J_total = J_N···J_1（x 为链首输入）。

    mode="declared"：逐组件用各自声明档；也可统一强制 "fd"/"cs"/
    "analytic"。返回 (J_total, 实际档逐组件列表)（降档事实透出）。
    """
    if not components:
        raise ValueError("链为空")
    # 声明维预检（求值前拦断：下游组件不会吃到错维输入再炸 IndexError；
    # 0 = 未声明，跳过交运行时形状检查兜底）
    for a, b in pairwise(components):
        if a.n_out and b.n_in and a.n_out != b.n_in:
            raise ValueError(
                f"链维度断裂: {b.__class__.__name__} 声明输入 {b.n_in}"
                f" ≠ 上游 {a.__class__.__name__} 输出 {a.n_out}")
    cur = np.asarray(x, dtype=float)
    total: np.ndarray | None = None
    used: list[str] = []
    for comp in components:
        m = (comp.partials_mode if mode == "declared" else mode)
        jac, actual = comp.jacobian(cur, m)
        used.append(actual)
        if total is None:
            total = jac
        else:
            if total.shape[0] != jac.shape[1]:
                raise ValueError(
                    f"链维度断裂: {comp.__class__.__name__} 输入 {jac.shape[1]}"
                    f" ≠ 上游输出 {total.shape[0]}")
            total = jac @ total
        cur = np.atleast_1d(np.asarray(comp.compute(cur), dtype=float))
    assert total is not None
    return total, used


def check_partials(
    component: DerivativeComponent,
    x: np.ndarray,
    *,
    fd_tol: float = 1e-5,
    cs_tol: float = 1e-7,
    fd_eps: float = 1e-6,
    cs_h: float = 1e-20,
) -> dict[str, Any]:
    """三方互证门（数值内核入库门槛模板）。

    返回契约：{ok, analytic_available, declared_mode, used_mode,
    rel_err: {analytic_vs_fd, analytic_vs_cs, fd_vs_cs},
    tol: {fd, cs}, failures: [...]}。

    - analytic 可用：analytic vs fd ≤ fd_tol 且 analytic vs cs ≤ cs_tol
      方为 ok（cs 是高精度锚，fd 是独立路径双源）；cs 不可用（非解析
      算子）时由 rel_err=cs 侧 NaN 与 failures 如实记录，不算假绿；
    - analytic 不可用（声明 fd/cs 档）：fd vs cs ≤ fd_tol 跨证为 ok。
    """
    x0 = np.asarray(x, dtype=float)
    rep: dict[str, Any] = {"ok": False, "analytic_available": False,
                           "declared_mode": component.partials_mode,
                           "rel_err": {}, "tol": {"fd": float(fd_tol),
                                                  "cs": float(cs_tol)},
                           "failures": []}

    def _rel(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.maximum(np.abs(b), _REL_FLOOR)
        return float(np.max(np.abs(a - b) / denom))

    try:
        j_analytic = np.atleast_2d(
            np.asarray(component.analytic_jacobian(x0), dtype=float))
        rep["analytic_available"] = True
    except NotImplementedError:
        j_analytic = None
    j_fd = fd_jacobian(component.compute, x0, eps=fd_eps)
    rep["rel_err"]["fd"] = "computed"
    try:
        j_cs, _cs_used = component.jacobian(x0, "cs")
        cs_ok = True
    except Exception as exc:  # 复数不支持等——如实记失败，不冒充通过
        cs_ok = False
        rep["failures"].append(f"cs 求值异常: {exc}")
    if j_analytic is not None:
        e_fd = _rel(j_analytic, j_fd)
        rep["rel_err"]["analytic_vs_fd"] = e_fd
        if e_fd > fd_tol:
            rep["failures"].append(
                f"analytic vs fd 相对误差 {e_fd:.3e} > {fd_tol:.1e}")
        if cs_ok:
            e_cs = _rel(j_analytic, j_cs)
            rep["rel_err"]["analytic_vs_cs"] = e_cs
            if e_cs > cs_tol:
                rep["failures"].append(
                    f"analytic vs cs 相对误差 {e_cs:.3e} > {cs_tol:.1e}"
                    "（analytic 错或 cs 前提不成立——两读，门槛只拦不放）")
        else:
            rep["rel_err"]["analytic_vs_cs"] = None
        rep["ok"] = not rep["failures"]
    else:
        if cs_ok:
            e_cross = _rel(j_fd, j_cs)
            rep["rel_err"]["fd_vs_cs"] = e_cross
            if e_cross > fd_tol:
                rep["failures"].append(
                    f"fd vs cs 跨证相对误差 {e_cross:.3e} > {fd_tol:.1e}")
        else:
            rep["rel_err"]["fd_vs_cs"] = None
        rep["ok"] = not rep["failures"]
    return rep
