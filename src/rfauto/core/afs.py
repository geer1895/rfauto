"""AFS 自适应频扫（Adaptive Frequency Sampling）确定性内核。

任务口径：
    "AFS 自适应频扫：向量拟合驱动选频点，收敛即停——每频点一次
    FEM 求解、每次占席位，省席位-小时。HFSS 插值扫频同思路；skrf VF。
    验收：平行板/mline 案例频点数减半且 vs 全扫 FSV >= VG。"

设计（与口径逐条对应）
----------------------
* "向量拟合驱动选频点"：拟合器复用已落库的
  ``skrf.vectorFitting.VectorFitting``（固定阶数、无随机初值，确定性），
  不自造拟合算法；
* "收敛即停"：每一轮在当前采样点的**相邻中点**处用模型预测一次并与真响应
  比对（每个中点 = 一次"求解"，计入 solve 计费），全部中点误差 <= tol 即
  判收敛停止；误差超 tol 的中点加入采样集进入下一轮（最坏处加密）；
* "每频点一次 FEM 求解"：真响应抽象为 ``evaluate(f_hz) -> complex`` 回调，
  本模块只通过它取数并对每次调用计数（生产中即一次 FEM 单点求解）；
* "vs 全扫 FSV >= VG"：对重建的密集模型响应与全扫参考（已归档的密集数据，
  *不计入* solve 计费）做 FSV 裁判（|S| dB 口径，同 core/macromodel），
  summary 给出 GDM 等级供验收（>= VG 即等级下标 <= 1）。

算法边界（如实）
----------------
* 中点误差检验以**线性复幅差**为口径：``|S_true(f) - S_model(f)| <= tol``。
  对无源 S 参数（|S| <= 1）这等价于全带相对容差；深凹谷底部（|S| -> 0）
  处绝对容差偏松，属 HFSS 插值扫频同类近似，验收以 FSV 等级兜底。
* 真机验收（平行板/mline 频点减半）需真机批次执行；本模块单测以**合成
  有理函数当真响应**做零仿真验证：缩减比与插值误差数字进 summary。

分层：core 层叶子，仅依赖 numpy + scikit-rf + 同层 core.fsv（与
core/macromodel.py 同口径）；无 IO、无随机、无墙钟。
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

import numpy as np
import skrf
from skrf.vectorFitting import VectorFitting

from rfauto.core.fsv import GRADE_CODES, fsv, grade_index_of

__all__ = [
    "DEFAULT_ORDER_LADDER",
    "DEFAULT_RMS_THRESHOLD_DB",
    "DEFAULT_TOL",
    "AFSError",
    "afs_sample",
]

#: 缺省确定性升阶阶梯（n_poles_real, n_poles_cmplx）。谐振类 S 参数由复极点
#: 对主导：从 (0,1) 纯复极点档起步（实测单谐振系统 (0,1) 即精确拟合，
#: 实极点档起步反而引入坏实极点），逐级加档到 (4,8)。
DEFAULT_ORDER_LADDER: tuple[tuple[int, int], ...] = (
    (0, 1), (0, 2), (1, 2), (2, 4), (4, 8),
)
#: 样本点拟合 RMS（dB）达标阈值，与 macromodel 同款。
DEFAULT_RMS_THRESHOLD_DB = -40.0
#: 中点收敛容差（线性复幅差；无源 S 参数 |S|<=1 时即全带相对容差）。
DEFAULT_TOL = 1e-2
#: 复数 dB 地板（|S|=0 保护）。
_DB_FLOOR = 1e-30


class AFSError(Exception):
    """AFS 内核异常（拟合全败 / 参数非法）。"""


def _fit_best(
    freq: np.ndarray,
    s: np.ndarray,
    order_ladder: tuple[tuple[int, int], ...],
    rms_threshold_db: float,
) -> tuple[Callable[[np.ndarray], np.ndarray], dict[str, Any]]:
    """Hz 频轴上的向量拟合（确定性，先达标先停）。

    返回 ``(model, info)``：``model(frequencies_hz) -> complex array`` 是
    拟合好的模型响应求值器；``info`` 为拟合摘要。skrf VF 内部自带按平均
    频率的自归一化（实测 GHz 频段 Hz 轴拟合 ~1e-15 rms），不再额外做
    无量纲化（实测 [0,1] 归一轴反而让极点迁移退化，极点坍缩到原点）。
    阶梯从 (0,1) 起步：谐振类 S 参数由复极点对主导，先给纯复极点档，
    实极点档靠后（实测 (1,2) 起步会在单谐振系统上引入坏实极点）。
    skrf VF 的极点迁移 RuntimeWarning 捕获计数记入 attempts（不掩盖，
    阶梯按 RMS 取最优不受其影响）。
    """
    network = skrf.Network(
        frequency=np.asarray(freq, dtype=float), s=s, z0=50.0
    )
    attempts: list[dict[str, Any]] = []
    best: tuple[float, float, VectorFitting, int, int] | None = None
    for n_real, n_cmplx in order_ladder:
        vf = VectorFitting(network)
        warnings_history: list[str] = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            try:
                vf.vector_fit(n_poles_real=n_real, n_poles_cmplx=n_cmplx)
            except Exception as exc:  # skrf 内部可抛 LinAlgError/ValueError，如实记录
                attempts.append(
                    {"n_poles_real": n_real, "n_poles_cmplx": n_cmplx,
                     "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            warnings_history = [str(w.message) for w in caught]
        s_fit = np.asarray(
            vf.get_model_response(0, 0, network.f), dtype=complex
        ).ravel()
        rms = float(np.sqrt(np.mean(np.abs(s - s_fit) ** 2)))
        rms_db = float(20.0 * np.log10(max(rms, _DB_FLOOR)))
        attempts.append(
            {"n_poles_real": n_real, "n_poles_cmplx": n_cmplx,
             "rms_db": rms_db, "passed": bool(rms_db <= rms_threshold_db),
             "n_vf_warnings": len(warnings_history)}
        )
        if best is None or rms < best[0]:
            best = (rms, rms_db, vf, n_real, n_cmplx)
        if rms_db <= rms_threshold_db:
            break
    if best is None:
        raise AFSError(f"所有阶数的向量拟合均失败: {attempts}")
    rms, rms_db, vf, n_real, n_cmplx = best

    def model(frequencies_hz: np.ndarray) -> np.ndarray:
        return np.asarray(
            vf.get_model_response(0, 0, np.asarray(frequencies_hz, dtype=float)),
            dtype=complex,
        ).ravel()

    info = {
        "n_poles_real": n_real,
        "n_poles_cmplx": n_cmplx,
        "n_poles_total": int(np.size(vf.poles)),
        "rms_db_at_samples": rms_db,
        "attempts": attempts,
    }
    return model, info


def _jsonify(value: Any) -> Any:
    """numpy -> JSON 原生（不改数值）。"""
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonify(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def afs_sample(
    evaluate: Callable[[float], complex],
    f_min: float,
    f_max: float,
    *,
    n_init: int = 7,
    tol: float = DEFAULT_TOL,
    max_points: int = 96,
    max_rounds: int = 12,
    order_ladder: tuple[tuple[int, int], ...] = DEFAULT_ORDER_LADDER,
    fit_rms_threshold_db: float = DEFAULT_RMS_THRESHOLD_DB,
    n_dense: int = 401,
    full_response: Callable[[np.ndarray], np.ndarray] | None = None,
) -> dict[str, Any]:
    """自适应选点采样 + 向量拟合重建（确定性，零真机）。

    参数
    ----
    evaluate : 真响应回调 ``f_hz -> complex``；每次调用计一次求解。
    f_min, f_max : 频带（Hz，f_min < f_max）。
    n_init : 初始均匀采样点数（>= 3）。
    tol : 中点收敛容差（线性复幅差）。
    max_points / max_rounds : 终止保护（触发时 status 如实标注未收敛）。
    order_ladder / fit_rms_threshold_db : VF 定阶阶梯与样本点 RMS 阈值。
    n_dense : 重建/判分的密集频轴点数（全扫参考点数口径）。
    full_response : 可选，全扫参考 ``freqs(Hz) -> complex array``（已归档
        的密集数据插值口径；*不计入* solve 计费）。提供时 summary 附
        ``vs_full``（逐点误差 + FSV 裁判）。

    返回
    ----
    JSON 原生 dict：solve 计费（n_solves）、采样点（frequencies_hz）、收敛
    状态、拟合阶数与样本点 RMS、密集重建（freq_hz / s_model）、以及
    ``vs_full`` 中的缩减比（reduction_ratio = 1 - n_solves / n_dense）与
    FSV 等级。
    """
    f_min_f = float(f_min)
    f_max_f = float(f_max)
    if not (np.isfinite(f_min_f) and np.isfinite(f_max_f)) or not f_max_f > f_min_f:
        raise AFSError(f"频带非法: [{f_min!r}, {f_max!r}]")
    if not callable(evaluate):
        raise AFSError("evaluate 必须为可调用对象 f_hz -> complex")
    n_init = int(n_init)
    if n_init < 3:
        raise AFSError(f"n_init 必须 >= 3，得到 {n_init}")
    if int(max_points) < n_init:
        raise AFSError("max_points 不能小于 n_init")

    solves = 0

    def solve(f: float) -> complex:
        nonlocal solves
        solves += 1
        return complex(evaluate(float(f)))

    freqs = np.linspace(f_min_f, f_max_f, n_init)
    samples = {float(f): solve(f) for f in freqs}

    model: Callable[[np.ndarray], np.ndarray] | None = None
    fit_info: dict[str, Any] = {}
    converged = False
    status = "max_rounds"
    rounds = 0
    max_mid_error = float("inf")
    for _ in range(int(max_rounds)):
        rounds += 1
        grid = np.array(sorted(samples))
        s_vals = np.array([samples[float(f)] for f in grid], dtype=complex)
        model, fit_info = _fit_best(grid, s_vals, order_ladder, fit_rms_threshold_db)

        mids = (grid[:-1] + grid[1:]) / 2.0
        if mids.size == 0:
            converged = True
            status = "converged"
            break
        model_at_mids = model(mids)
        errs: list[tuple[float, float, complex]] = []
        for mid, model_val in zip(mids, model_at_mids, strict=True):
            actual = solve(float(mid))
            errs.append((float(mid), abs(actual - model_val), actual))
        max_mid_error = max(e[1] for e in errs)
        failing = [(f, a) for f, err, a in errs if err > tol]
        if not failing:
            converged = True
            status = "converged"
            break
        for f, actual in failing:
            samples[float(f)] = actual
        if len(samples) >= int(max_points):
            status = "max_points"
            break

    grid = np.array(sorted(samples))
    s_vals = np.array([samples[float(f)] for f in grid], dtype=complex)
    model_final, fit_info = _fit_best(grid, s_vals, order_ladder, fit_rms_threshold_db)

    dense_freq = np.linspace(f_min_f, f_max_f, int(n_dense))
    dense_model = model_final(dense_freq)

    summary: dict[str, Any] = {
        "status": status,
        "converged": converged,
        "tol": float(tol),
        "n_init": n_init,
        "rounds": rounds,
        "n_solves": solves,
        "n_accepted": int(grid.size),
        "frequencies_hz": [float(f) for f in grid],
        "max_midpoint_error": None if not np.isfinite(max_mid_error) else float(max_mid_error),
        "fit": fit_info,
        "dense": {
            "n_points": int(n_dense),
            "freq_hz": [float(f) for f in dense_freq],
            "s_model": [[float(v.real), float(v.imag)] for v in dense_model],
        },
    }

    if full_response is not None:
        dense_true = np.asarray(full_response(dense_freq), dtype=complex).ravel()
        if dense_true.size != dense_freq.size:
            raise AFSError("full_response 返回长度与密集频轴不一致")
        abs_err = np.abs(dense_true - dense_model)
        rms = float(np.sqrt(np.mean(abs_err**2)))
        mag_true_db = 20.0 * np.log10(np.maximum(np.abs(dense_true), _DB_FLOOR))
        mag_model_db = 20.0 * np.log10(np.maximum(np.abs(dense_model), _DB_FLOOR))
        fsv_result = fsv(dense_freq, mag_true_db, dense_freq, mag_model_db)
        gdm_grade_index = grade_index_of(float(fsv_result["gdm_mean"]))
        summary["vs_full"] = {
            "n_full": int(n_dense),
            "n_solves": solves,
            "reduction_ratio": float(1.0 - solves / float(n_dense)),
            "max_abs_err": float(np.max(abs_err)),
            "rms_abs_err": rms,
            "fsv": {
                "adm_mean": float(fsv_result["adm_mean"]),
                "fdm_mean_abs": float(fsv_result["fdm_mean_abs"]),
                "gdm_mean": float(fsv_result["gdm_mean"]),
                "adm_grade": fsv_result["adm_grade"],
                "fdm_grade": fsv_result["fdm_grade"],
                "gdm_grade": fsv_result["gdm_grade"],
                "gdm_grade_level": int(fsv_result["gdm_grade_level"]),
                "gdm_spread": int(fsv_result["gdm_spread"]),
                # 验收口径：vs 全扫 FSV >= VG（等级下标 <= 1）；
                # >= Good（下标 <= 2）一并给出供放宽口径使用。
                "at_least_vg": bool(gdm_grade_index <= 1),
                "at_least_good": bool(gdm_grade_index <= 2),
                "scale": GRADE_CODES,
            },
        }
    return _jsonify(summary)
