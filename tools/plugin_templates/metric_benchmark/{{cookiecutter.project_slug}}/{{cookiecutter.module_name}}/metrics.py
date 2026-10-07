"""确定性指标计算（metric 面；铁律 7：数值只在确定性内核产出）。

本模块的函数从 S 参数产物提取 `expected.numeric` 用的 metric 值——
同输入同输出，零网络零 LLM 零随机。ground truth 判据（value/tol_pct/
source）在任务集里预声明（#122 先写后跑），本模块只负责"产生被比较的
数"，不产生"判据的数"。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

#: 真空光速 m/s（SI 定义值；与 rfauto 内核各模块 C0 同值）
C0 = 299792458.0

__all__ = ["C0", "resonance_freq_ghz", "s21_at_ghz_db"]


def _freq_hz(freq_hz: Sequence[float]) -> np.ndarray:
    _reject_bool("freq_hz", freq_hz)
    arr = np.asarray(freq_hz, dtype=float)
    if arr.ndim != 1 or arr.size < 2 or not np.all(np.isfinite(arr)) \
            or np.any(arr <= 0):
        raise ValueError("freq_hz 须为正有限一维序列（≥2 点）")
    return arr


def _db_series(name: str, series: Sequence[float], n: int) -> np.ndarray:
    """dB 序列入参：先查 bool/长度再转数组（asarray 会把 bool 静默转 1.0）。"""
    _reject_bool(name, series)
    arr = np.asarray(series, dtype=float)
    if arr.ndim != 1 or arr.size != n:
        raise ValueError(f"{name} 须与 freq_hz 等长一维序列")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含非有限值（NaN/Inf）——先修数据再判读")
    return arr


def _reject_bool(name: str, value: object) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值，得到 bool（df7+ 坑16 惯例）")
    if isinstance(value, (list, tuple)) and any(
            isinstance(v, bool) for v in value):
        raise ValueError(f"{name} 序列含 bool 元素——静默转 1.0 污染统计"
                         "（df7+ 坑16 惯例），显式拒收")


def resonance_freq_ghz(freq_hz: Sequence[float],
                       s11_db: Sequence[float]) -> float:
    """谐振频率（|S11| 谷位，GHz）：argmin 口径（窄带单谷响应面）。

    边界（如实）：多谷/平顶响应取首谷——适合单谐振器模板的判读；多模
    器件请改用模式追踪口径后再入任务集，勿套本函数。
    """
    arr_f = _freq_hz(freq_hz)
    arr = _db_series("s11_db", s11_db, arr_f.size)
    return float(arr_f[int(np.argmin(arr))]) / 1e9


def s21_at_ghz_db(freq_hz: Sequence[float], s21_db: Sequence[float],
                  f_query_ghz: float) -> float:
    """指定频点的 |S21|（dB）：最近邻插值（栅距内线性）。"""
    _reject_bool("f_query_ghz", f_query_ghz)
    arr_f = _freq_hz(freq_hz)
    arr = _db_series("s21_db", s21_db, arr_f.size)
    return float(np.interp(f_query_ghz * 1e9, arr_f, arr))
