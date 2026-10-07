"""AAA 有理逼近试点（round3 附带三件之一，研究扩充 §3.1）。

任务口径原文：
    "AAA 有理逼近试点（scipy.interpolate.AAA 1.15 起实测在装——标量频响
    greedy 有理逼近与 AFS/VF 对照，出极点/留数）"

定位与边界（试点，如实）：
- scipy AAA：对**标量复响应** y(x) 的 greedy 自适应有理逼近（barycentric
  表示），支持点逐个贪心加入（每步取残差最大处，无随机初值，确定性），
  出极点/留数/支持点；
- 对照面 = 同一数据的 skrf VF 路（core/afs.py 同款调用惯例：固定阶、无随机
  初值；#286：skrf 存储极点数共轭对只存一个，且 VF 内部在 rad/s 域、极点
  可在 RMS 达标下迁移——故 VF 侧只做阶数/RMS 对照，**极点级恢复钉只在
  AAA 侧做**（x 域即调用方域，无换算歧义）；
- 本模块是"逼近器对照试点"内核，不接入 AFS 选频主循环（D13/AFS 主线改动
  须走其自身批次）；真机频响回收（mline/ring 提取）属 C 类，不在本件。

数值纪律：逼近质量与极点恢复的裁判 = 合成已知有理函数的
回收误差（tests/unit/test_aaa_pilot.py 预声明容差钉），不是自我推导；
本模块不做任何物理断言。

依赖与降级：AAA 需 scipy>=1.15（pyproject 基线 scipy>=1.11）——惰性 import，
缺 API 时 aaa_fit 抛 RuntimeError 带 reason（render_constraints z3 惰性降级
同款先例）；skrf VF 为基线依赖（>=2.0），顶层 import。

分层：core 叶子，仅 numpy + scipy（惰性）+ scikit-rf；无 IO、无随机、无墙钟。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import skrf
from skrf.vectorFitting import VectorFitting

__all__ = [
    "SCIPY_AAA_HINT",
    "AaaFit",
    "aaa_fit",
    "aaa_vs_vf_compare",
    "match_poles",
]

SCIPY_AAA_HINT = "AAA 有理逼近需 scipy>=1.15（当前环境缺 scipy.interpolate.AAA）"
"""scipy AAA 缺 API 时的降级 reason（版本面如实，不静默降级）。"""

_DB_FLOOR = 1e-12
"""rms_db 计算的幅度地板（防 log10(0)；core/afs.py 同款惯例）。"""


def _attr_or_call(obj: Any, name: str) -> Any:
    """scipy AAA 跨版本属性/方法双兼容访问器。

    scipy 1.18 实测 ``poles``/``residues``/``roots`` 是**方法**（须调用），
    早期文档口径为属性——统一"可调用则调用，否则取属性"，调用点只写一处。
    """
    value = getattr(obj, name)
    return value() if callable(value) else value


@dataclass(frozen=True)
class AaaFit:
    """AAA 拟合结果（极点/留数/支持点 + 样本 RMS 摘要）。

    residues 为 scipy AAA 其 barycentric 表示导出的留数**原样透出**——与
    解析部分分式留数之间可能差一个尺度/规范（本试点不做解析留数断言，
    #122 如实口径）；极点级断言由单测以合成回收钉承担。
    """

    poles: np.ndarray
    residues: np.ndarray
    support_points: np.ndarray
    support_values: np.ndarray
    rms_at_samples: float
    rms_db_at_samples: float
    rtol_used: float | None
    _approx: Any = field(repr=False, compare=False, default=None)

    def model(self, freqs: Any) -> np.ndarray:
        """AAA barycentric 模型在任意频点处的求值（确定性纯函数）。"""
        if self._approx is None:
            raise ValueError("AaaFit 无可求值内核（缺 _approx）")
        return np.asarray(self._approx(np.asarray(freqs, dtype=float)), dtype=complex)

    def to_report(self) -> dict[str, Any]:
        """JSON 安全摘要（复数量以 [re, im] 对出，供服务层直出）。"""
        return {
            "n_poles": int(np.size(self.poles)),
            "n_support_points": int(np.size(self.support_points)),
            "rms_at_samples": self.rms_at_samples,
            "rms_db_at_samples": self.rms_db_at_samples,
            "rtol_used": self.rtol_used,
            "poles": [[float(np.real(p)), float(np.imag(p))] for p in np.ravel(self.poles)],
            "residues": [[float(np.real(z)), float(np.imag(z))] for z in np.ravel(self.residues)],
        }


def _validate_samples(freqs: Any, values: Any) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(freqs, dtype=float)
    y = np.asarray(values, dtype=complex)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
        raise ValueError(f"需 1D 等长实频轴/复响应，得 x{x.shape} y{y.shape}")
    if x.size < 3:
        raise ValueError(f"样本点过少（{x.size} < 3），AAA 无意义")
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        # scipy AAA 会静默丢弃 NaN/Inf 点——这里显式拒绝，避免样本集被悄悄改写
        raise ValueError("freqs/values 含 NaN/Inf（显式拒绝，不做静默丢弃）")
    return x, y


def aaa_fit(
    freqs: Any,
    values: Any,
    *,
    rtol: float | None = None,
    max_terms: int = 100,
) -> AaaFit:
    """对标量复响应做 AAA 有理逼近，出极点/留数/支持点与样本 RMS。

    rtol=None 时用 scipy 缺省（eps**0.75）；greedy 支持点选择无随机成分，
    同输入逐位可复现（单测有确定性钉）。
    """
    try:
        from scipy.interpolate import AAA
    except ImportError as exc:  # scipy<1.15 无 AAA（版本面如实）
        raise RuntimeError(SCIPY_AAA_HINT) from exc
    x, y = _validate_samples(freqs, values)
    approx = AAA(x, y, rtol=rtol, max_terms=max_terms)
    poles = np.asarray(_attr_or_call(approx, "poles"), dtype=complex).ravel()
    residues = np.asarray(_attr_or_call(approx, "residues"), dtype=complex).ravel()
    support_points = np.asarray(approx.support_points, dtype=float).ravel()
    support_values = np.asarray(approx.support_values, dtype=complex).ravel()
    y_fit = np.asarray(approx(x), dtype=complex)
    rms = float(np.sqrt(np.mean(np.abs(y - y_fit) ** 2)))
    rms_db = float(20.0 * np.log10(max(rms, _DB_FLOOR)))
    return AaaFit(
        poles=poles,
        residues=residues,
        support_points=support_points,
        support_values=support_values,
        rms_at_samples=rms,
        rms_db_at_samples=rms_db,
        rtol_used=rtol,
        _approx=approx,
    )


def match_poles(true_poles: Any, fitted_poles: Any) -> dict[str, Any]:
    """极点回收度量：贪心最近邻（全局最小优先、不放回）匹配。

    返回 JSON 安全 dict：``pairs=[(true_i, fit_j, rel_err)]``、
    ``max_rel_err``（被匹配上的真实极点的最大相对误差）、
    ``n_unmatched_true``。rel_err = |q−p|/|q|。纯函数、确定性。
    """
    q = np.asarray(true_poles, dtype=complex).ravel()
    p = np.asarray(fitted_poles, dtype=complex).ravel()
    pairs: list[list[float]] = []
    used: set[int] = set()
    remaining_q = list(range(q.size))
    while remaining_q:
        best: tuple[float, int, int] | None = None
        for i in remaining_q:
            for j in range(p.size):
                if j in used:
                    continue
                rel = float(np.abs(q[i] - p[j]) / max(abs(q[i]), 1e-300))
                if best is None or rel < best[0]:
                    best = (rel, i, j)
        if best is None:  # 拟合极点耗尽，剩余真实极点无匹配
            break
        rel, i, j = best
        pairs.append([float(i), float(j), rel])
        used.add(j)
        remaining_q.remove(i)
    max_rel = max((r for _, _, r in pairs), default=float("nan"))
    return {
        "pairs": pairs,
        "max_rel_err": float(max_rel) if pairs else float("nan"),
        "n_unmatched_true": len(remaining_q),
    }


def aaa_vs_vf_compare(
    freqs: Any,
    values: Any,
    *,
    n_poles_real: int,
    n_poles_cmplx: int,
) -> dict[str, Any]:
    """同一标量频响上 AAA 与 skrf VF 的对照摘要（JSON 安全，确定性）。

    AAA 侧给极点/留数/支持点；VF 侧只给存储阶数（#286：共轭对只存一个）
    与样本 RMS（VF 极点在 rad/s 域且可在 RMS 达标下迁移，不做极点匹配）。
    VF 极点迁移 RuntimeWarning 计数入 ``n_vf_warnings``（不掩盖，afs 同款）。
    """
    x, y = _validate_samples(freqs, values)
    fit = aaa_fit(x, y)
    network = skrf.Network(frequency=x, s=y.reshape(-1, 1, 1), z0=50.0)
    vf = VectorFitting(network)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        vf.vector_fit(n_poles_real=n_poles_real, n_poles_cmplx=n_poles_cmplx)
    y_vf = np.asarray(vf.get_model_response(0, 0, x), dtype=complex).ravel()
    rms_vf = float(np.sqrt(np.mean(np.abs(y - y_vf) ** 2)))
    return {
        "aaa": fit.to_report(),
        "vf": {
            "n_poles_real": int(n_poles_real),
            "n_poles_cmplx": int(n_poles_cmplx),
            "n_poles_stored": int(np.size(vf.poles)),
            "rms_at_samples": rms_vf,
            "rms_db_at_samples": float(20.0 * np.log10(max(rms_vf, _DB_FLOOR))),
            "n_vf_warnings": len(caught),
        },
    }
