"""网格收敛性检查器（GCI/Richardson 外推，SV-6 round14 :197；纯函数叶模块）。

职责（铁律 7：数值只在确定性内核；本模块 = 纯 stdlib 叶子，无业务依赖）：
对同一标量量的 (h, f(h)) 网格序列做离散误差估计——观察收敛阶 p、Richardson
外推值、细网格 GCI 离散误差带（GCI_fine = Fs·|ε21|/(r^p − 1)，Fs=1.25 为
Celik 2008/Roache 惯例安全因子）。

方法口径（ASME J. Fluids Eng. 2008 标准过程，Çelik 三网格法）：
- 细→粗三级 φ1/φ2/φ3（φ1 最细），逐级差 ε21 = φ2 − φ1、ε32 = φ3 − φ2；
- ε21·ε32 > 0 = 单调收敛：p = ln(ε32/ε21)/ln r（恒定细化比闭式，天然支持
  非整数 p）；ε21·ε32 < 0 = 振荡收敛：p = |ln|ε32/ε21||/ln r（同式取绝对
  值，Çelik 2008 对振荡情形的处方）；
- Richardson 外推 φ_ext = (r^p·φ1 − φ2)/(r^p − 1)；恒定 r 下恒等式
  |φ1 − φ_ext| = |ε21|/(r^p − 1)，故 GCI_fine = Fs·|φ1 − φ_ext|；
- 离散误差带 = φ1 ± GCI_fine（细网格报告口径）。

仓内关系：
- core/quasistatic_fd.richardson_first_order 是本模块 p=1、r=2 的一阶特例
  （既有语义零改动，SV-6 为其形式化推广）；
- core/vv_mapping.u_num_gci 是恒定 r 的标量 u_num 保守路径（差比 ≤1 一律
  None 不虚构）——本模块恒定 r 单调支路与它逐位同式，测试对拍钉住；
- #335 ΔS 阶梯收敛核验与 #313 地板项分解是仓内网格收敛实践先例，本模块
  是其通用形式化（判据不变，产出结构化）。

迁移语义（round14 规格"网格序列-外推-报告进 solve_health"）：主入口
:func:`assess_grid_convergence` 接收任意排序的 (h, f(h)) 序列（≥3 网格，
内部排序取最细三级）；solve_health 接线为后续项，本模块只出纯内核，
不做服务层依赖。

诚实语义（#122 族）：无法给出正收敛阶（差为零/差比 ≤1/非恒定比无正根/
振荡且比非恒定）时如实返回 p/GCI = None 并给 reason，不虚构收敛带。
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

__all__ = [
    "FS_DEFAULT",
    "REASON_EXTRAP_OVERFLOW",
    "REASON_NONPOSITIVE_ORDER",
    "REASON_NO_ROOT",
    "REASON_OSC_REQUIRES_CONSTANT_R",
    "REASON_ZERO_DIFFERENCE",
    "R_TOL",
    "STATUS_DEGENERATE",
    "STATUS_MONOTONIC",
    "STATUS_OSCILLATORY",
    "GridConvergenceResult",
    "assess_grid_convergence",
    "assess_triple",
    "gci_from_order",
]

#: GCI 安全因子缺省（Çelik 2008/Roache 惯例 Fs=1.25；vv_mapping.FS_CONSERVATIVE 同值同源）
FS_DEFAULT = 1.25
#: 序列入口"近恒定细化比"判定（|r21/r32 − 1| ≤ R_TOL 按恒定闭式，r 取几何平均）
R_TOL = 1e-3

STATUS_MONOTONIC = "monotonic"      #: 逐级差同号
STATUS_OSCILLATORY = "oscillatory"  #: 逐级差变号
STATUS_DEGENERATE = "degenerate"    #: 无法分类（零差等）

REASON_ZERO_DIFFERENCE = "zero_successive_difference"
REASON_NONPOSITIVE_ORDER = "non_positive_observed_order"
REASON_NO_ROOT = "no_positive_order_root"
REASON_OSC_REQUIRES_CONSTANT_R = "oscillatory_requires_constant_refinement_ratio"
REASON_EXTRAP_OVERFLOW = "extrapolation_overflow"

# 广义 p 求解的搜索下界（远小于任何实际观察阶；再小则 u=exp(−a·p) 舍入为 1 失效）
_P_LO = 1e-9


@dataclass(frozen=True)
class GridConvergenceResult:
    """一次网格收敛评估的结构化产出（solve_health 报告面的载体）。

    status/convergent/p/r 是判读主键；f_extrapolated/richardson_error/
    gci_fine/gci_fine_rel/band 只在 convergent 时非 None（诚实语义：
    无正收敛阶不虚构误差带）。reason 给不可估原因（值域见模块级
    REASON_* 常量），convergent 且无异常时为 None。
    """

    status: str                       # STATUS_* 常量
    convergent: bool                  # p > 0 且 GCI 可估
    p: float | None                   # 观察收敛阶（含非整数；不可估为 None）
    r: float | None                   # 代表细化比（恒定支路 = r21 与 r32 的几何平均）
    r_constant: bool                  # 细化比按恒定（或近恒定）闭式处理
    f_fine: float                     # φ1（最细网格值）
    f_medium: float                   # φ2
    f_coarse: float                   # φ3
    h_fine: float | None              # 最细网格 h（triple 入口无 h 时 None）
    h_medium: float | None
    h_coarse: float | None
    f_extrapolated: float | None      # Richardson 外推值
    richardson_error: float | None    # |φ1 − φ_ext|
    gci_fine: float | None            # Fs·|φ1 − φ_ext|（恒定 r 恒等于 Fs·|ε21|/(r^p−1)）
    gci_fine_rel: float | None        # gci_fine/|φ1|（φ1 = 0 时 None）
    band: tuple[float, float] | None  # φ1 ± gci_fine
    fs: float                         # 安全因子
    reason: str | None                # 不可估原因（REASON_* 常量）

    def as_dict(self) -> dict[str, float | bool | int | str | list[float] | None]:
        """JSON 可承载形态（band 转列表；供服务层 provenance/报告直用）。"""
        return {
            "status": self.status,
            "convergent": self.convergent,
            "p": self.p,
            "r": self.r,
            "r_constant": self.r_constant,
            "f_fine": self.f_fine,
            "f_medium": self.f_medium,
            "f_coarse": self.f_coarse,
            "h_fine": self.h_fine,
            "h_medium": self.h_medium,
            "h_coarse": self.h_coarse,
            "f_extrapolated": self.f_extrapolated,
            "richardson_error": self.richardson_error,
            "gci_fine": self.gci_fine,
            "gci_fine_rel": self.gci_fine_rel,
            "band": list(self.band) if self.band is not None else None,
            "fs": self.fs,
            "reason": self.reason,
        }


def gci_from_order(f_fine: float, f_medium: float, r: float, p: float,
                   fs: float = FS_DEFAULT) -> float:
    """GCI_fine = Fs·|ε21|/(r^p − 1)（Çelik 2008 eq.12 逐字实现）。

    ε21 = φ2 − φ1（中 − 细）。r ≤ 1、fs ≤ 0 或 p ≤ 0（r^p − 1 ≤ 0 = 无正
    收敛阶）抛 ValueError——调用方应先用 :func:`assess_triple` 的诚实
    语义分类，本函数只服务"已确认 p > 0"的公式直算面。
    """
    if not (float(r) > 1.0):
        raise ValueError(f"细化比 r 必须 > 1（当前 r={r!r}）")
    if not (float(fs) > 0.0):
        raise ValueError(f"安全因子 fs 必须 > 0（当前 fs={fs!r}）")
    denom = float(r) ** float(p) - 1.0
    if not (denom > 0.0) or not math.isfinite(denom):
        raise ValueError(f"r^p − 1 必须 > 0（当前 r={r!r}, p={p!r}）→ 无正收敛阶")
    e21 = float(f_medium) - float(f_fine)
    return float(fs) * abs(e21) / denom


def assess_triple(f_fine: float, f_medium: float, f_coarse: float, r: float,
                  fs: float = FS_DEFAULT) -> GridConvergenceResult:
    """恒定细化比 r 的三网格 GCI 评估（细→粗次序，Çelik 2008 标准过程）。

    r 必须严格 > 1（h_coarse/h_fine 口径），否则 ValueError。
    单调支路 p = ln(ε32/ε21)/ln r；振荡支路（ε21·ε32 < 0）取绝对值同式；
    零差或 p ≤ 0（差比 ≤ 1 = 无正收敛观察）走诚实 None 语义并给 reason。
    """
    if not (float(r) > 1.0):
        raise ValueError(f"细化比 r 必须 > 1（当前 r={r!r}）")
    if not (float(fs) > 0.0):
        raise ValueError(f"安全因子 fs 必须 > 0（当前 fs={fs!r}）")
    f1, f2, f3 = float(f_fine), float(f_medium), float(f_coarse)
    if not all(math.isfinite(v) for v in (f1, f2, f3)):
        raise ValueError("网格值必须有限")
    e21 = f2 - f1
    e32 = f3 - f2
    if e21 == 0.0 or e32 == 0.0:
        return GridConvergenceResult(
            status=STATUS_DEGENERATE, convergent=False, p=None, r=float(r),
            r_constant=True, f_fine=f1, f_medium=f2, f_coarse=f3,
            h_fine=None, h_medium=None, h_coarse=None,
            f_extrapolated=None, richardson_error=None, gci_fine=None,
            gci_fine_rel=None, band=None, fs=float(fs),
            reason=REASON_ZERO_DIFFERENCE)
    ratio = e32 / e21
    if ratio > 0.0:
        status = STATUS_MONOTONIC
    else:
        status = STATUS_OSCILLATORY
        ratio = -ratio  # Çelik 2008：振荡情形取绝对值进式 (5)
    p = math.log(ratio) / math.log(float(r))
    return _finalize_from_p(f1, f2, f3, float(r), p, float(fs), status,
                            r_constant=True)


def assess_grid_convergence(h_seq: list[float] | tuple[float, ...],
                            f_seq: list[float] | tuple[float, ...],
                            fs: float = FS_DEFAULT,
                            r_tol: float = R_TOL) -> GridConvergenceResult:
    """(h, f(h)) 序列主入口（迁移语义；round14 SV-6"网格序列-外推-报告"）。

    序列任意排序、长度 ≥3；内部按 h 升序取最细三级（h1<h2<h3）评估。
    近恒定细化比（|r21/r32 − 1| ≤ r_tol）按恒定闭式（r 取几何平均
    sqrt(h3/h1)）；否则解广义两点模型 (φ3−φ2)/(φ2−φ1) = (h3^p−h2^p)/
    (h2^p−h1^p) 的非整数 p（单调情形下有唯一正根，二分求解）；振荡且
    比非恒定时两点模型不可表（h^p 项恒同号），如实 p=None 不虚构。
    """
    if len(h_seq) != len(f_seq):
        raise ValueError(f"h/f 序列长度不一致（{len(h_seq)} vs {len(f_seq)}）")
    if len(h_seq) < 3:
        raise ValueError(f"GCI 至少需要 3 级网格（当前 {len(h_seq)} 级）")
    if not (float(fs) > 0.0):
        raise ValueError(f"安全因子 fs 必须 > 0（当前 fs={fs!r}）")
    floats = [(float(h), float(f)) for h, f in zip(h_seq, f_seq, strict=True)]
    if not all(math.isfinite(h) and h > 0.0 for h, _ in floats):
        raise ValueError("h 必须为正且有限")
    if not all(math.isfinite(v) for _, v in floats):
        raise ValueError("网格值必须有限")
    pairs = sorted(floats)
    hs = [p_[0] for p_ in pairs]
    if any(b - a <= 0.0 for a, b in itertools.pairwise(hs)):
        raise ValueError("h 序列不得含重复值（排序后须严格递增）")
    # 最细三级（h 最小的三个）
    h1, h2, h3 = hs[0], hs[1], hs[2]
    f1, f2, f3 = pairs[0][1], pairs[1][1], pairs[2][1]
    r21 = h2 / h1
    r32 = h3 / h2
    if abs(r21 / r32 - 1.0) <= float(r_tol):
        # 近恒定比：闭式分类定稿（assess_triple 单源），再附 h 报告字段
        res = assess_triple(f1, f2, f3, math.sqrt(r21 * r32), float(fs))
        return replace(res, h_fine=h1, h_medium=h2, h_coarse=h3)
    return _assess_nonconstant_ratio(h1, h2, h3, f1, f2, f3, float(fs))


# ─── 内部：分类定稿 ──────────────────────────────────────────────────────────

def _finalize_from_p(f1: float, f2: float, f3: float, r: float,
                     p: float | None, fs: float, status: str,
                     r_constant: bool, h: tuple[float, float, float] | None = None,
                     reason: str | None = None) -> GridConvergenceResult:
    """由（或无）观察阶 p 定稿：外推、GCI、误差带；不可估走诚实 None。

    p=None 时 status/reason 必须由调用方给出（零差/无根/振荡非恒定比）。
    """
    h_fine, h_medium, h_coarse = h if h is not None else (None, None, None)
    if p is None:
        return GridConvergenceResult(
            status=status if status else STATUS_DEGENERATE, convergent=False,
            p=None, r=r, r_constant=r_constant, f_fine=f1, f_medium=f2,
            f_coarse=f3, h_fine=h_fine, h_medium=h_medium, h_coarse=h_coarse,
            f_extrapolated=None, richardson_error=None, gci_fine=None,
            gci_fine_rel=None, band=None, fs=fs, reason=reason)
    if not (p > 0.0):
        return GridConvergenceResult(
            status=status, convergent=False, p=p, r=r, r_constant=r_constant,
            f_fine=f1, f_medium=f2, f_coarse=f3, h_fine=h_fine,
            h_medium=h_medium, h_coarse=h_coarse, f_extrapolated=None,
            richardson_error=None, gci_fine=None, gci_fine_rel=None,
            band=None, fs=fs, reason=REASON_NONPOSITIVE_ORDER)
    rp = r ** p
    if r_constant:
        # Çelik 2008 eq.10（恒定 r 闭式）；与 eq.12 恒等：
        # |φ1 − φ_ext| = |ε21|/(r^p − 1)
        f_ext = (rp * f1 - f2) / (rp - 1.0)
    else:
        # 两点模型拟合：φ(h) = φe + C·h^p，C = ε21/(h2^p − h1^p)
        # （非恒定比支路必带 h，见 _assess_nonconstant_ratio）
        hf, hm = float(h_fine), float(h_medium)  # type: ignore[arg-type]
        c = (f2 - f1) / (hm ** p - hf ** p)
        f_ext = f1 - c * hf ** p
    if not math.isfinite(f_ext):
        return GridConvergenceResult(
            status=status, convergent=False, p=p, r=r, r_constant=r_constant,
            f_fine=f1, f_medium=f2, f_coarse=f3, h_fine=h_fine,
            h_medium=h_medium, h_coarse=h_coarse, f_extrapolated=None,
            richardson_error=None, gci_fine=None, gci_fine_rel=None,
            band=None, fs=fs, reason=REASON_EXTRAP_OVERFLOW)
    rich_err = abs(f1 - f_ext)
    gci = gci_from_order(f1, f2, r, p, fs) if r_constant else fs * rich_err
    band = (f1 - gci, f1 + gci)
    rel = gci / abs(f1) if f1 != 0.0 else None
    return GridConvergenceResult(
        status=status, convergent=True, p=p, r=r, r_constant=r_constant,
        f_fine=f1, f_medium=f2, f_coarse=f3, h_fine=h_fine,
        h_medium=h_medium, h_coarse=h_coarse, f_extrapolated=f_ext,
        richardson_error=rich_err, gci_fine=gci, gci_fine_rel=rel,
        band=band, fs=float(fs), reason=None)


def _assess_nonconstant_ratio(h1: float, h2: float, h3: float, f1: float,
                              f2: float, f3: float,
                              fs: float) -> GridConvergenceResult:
    """非恒定细化比支路：广义两点模型解非整数 p（单调情形唯一正根二分）。"""
    e21 = f2 - f1
    e32 = f3 - f2
    ratio_r = math.sqrt(h3 / h1)
    if e21 == 0.0 or e32 == 0.0:
        return _finalize_from_p(f1, f2, f3, ratio_r, None, fs,
                                STATUS_DEGENERATE, r_constant=False,
                                h=(h1, h2, h3), reason=REASON_ZERO_DIFFERENCE)
    target = e32 / e21
    if target < 0.0:
        # 两点模型 h^p 项恒同号，振荡情形无非整数 p 解——如实 None
        return _finalize_from_p(f1, f2, f3, ratio_r, None, fs,
                                STATUS_OSCILLATORY, r_constant=False,
                                h=(h1, h2, h3), reason=REASON_OSC_REQUIRES_CONSTANT_R)
    # log 空间安全比值：u = (h1/h2)^p、v = (h2/h3)^p ∈ (0,1]
    # ratio(p) = (1 − v)/(v·(1 − u))，p→0+ 极限 = ln(h3/h2)/ln(h2/h1)，p↑ 单调增
    a = math.log(h2 / h1)
    b = math.log(h3 / h2)
    r_min = b / a
    if not (target > r_min):
        return _finalize_from_p(f1, f2, f3, ratio_r, None, fs,
                                STATUS_MONOTONIC, r_constant=False,
                                h=(h1, h2, h3), reason=REASON_NO_ROOT)

    def _ratio_at(p_val: float) -> float:
        u = math.exp(-a * p_val)
        v = math.exp(-b * p_val)
        if v == 0.0:
            return math.inf
        return (1.0 - v) / (v * (1.0 - u))

    p_hi = 1.0
    while _ratio_at(p_hi) <= target:
        p_hi *= 2.0
        if p_hi > 1e9:
            return _finalize_from_p(f1, f2, f3, ratio_r, None, fs,
                                    STATUS_MONOTONIC, r_constant=False,
                                    h=(h1, h2, h3), reason=REASON_NO_ROOT)
    p_lo = _P_LO
    if _ratio_at(p_lo) >= target:
        return _finalize_from_p(f1, f2, f3, ratio_r, None, fs,
                                STATUS_MONOTONIC, r_constant=False,
                                h=(h1, h2, h3), reason=REASON_NO_ROOT)
    for _ in range(200):  # 二分：ratio(p) 单调，200 轮远超双精度需求
        mid = 0.5 * (p_lo + p_hi)
        if _ratio_at(mid) < target:
            p_lo = mid
        else:
            p_hi = mid
        if p_hi - p_lo <= 1e-15 * max(1.0, p_hi):
            break
    p = 0.5 * (p_lo + p_hi)
    return _finalize_from_p(f1, f2, f3, ratio_r, p, fs, STATUS_MONOTONIC,
                            r_constant=False, h=(h1, h2, h3))
