"""§10.20 ③ S 参数时域门控（skrf time-domain gating）——FDTD 端口反射/多径
的可选清洗步。

问题定位
--------
openEMS/HFSS 频域 S 参数上的"纹波"（快速起伏）常来自**延迟反射/多径**：主响应
与延迟 τ 的寄生回波在频域叠加，形成周期 ≈ 1/τ 的干涉条纹。时域门控把冲激响应
乘一个时间窗（门），只保留主响应到达的那段时间，再变回频域——这是 VNA 测量里
"time-domain gating"的标准清理手段（skrf.time.time_gate，本仓 skrf 2.1.0）。

本模块职责
----------
- TimeGate：门参数值对象。支持 (start, stop) 或 (center, span) 两种口径，
  单位 s/ms/us/ns/ps，内部统一折算为**秒**；
- gate_network：把门施于频域网络。skrf 的 time_gate **只接受 1 端口**
  （实测 nports>1 抛 ValueError），本模块对 N 端口**逐 S 参数独立门控**
  （skrf 官方 docstring 明确要求如此）；
- compare_gate / band_valley / band_ripple_db / shoulder_ripple_db /
  impulse_out_of_gate_energy_ratio：before/after 的确定性对比指标
  （谷位 GHz、带内纹波 dB、肩部纹波 dB、门外能量比），供"门是否伤到主响应"判据。

skrf 2.1.0 接口口径（先 inspect 核对，实测钉住，不凭想象；见 test_time_gating）
----------------------------------------------------------------------------
- 签名（inspect.signature(skrf.time.time_gate) 实测）:

      (ntwk, start=None, stop=None, center=None, span=None, mode='bandpass',
       window=('kaiser', 6), method='fft', fft_window='cosine',
       conv_mode='wrap', t_unit='') -> Network

- ntwk.nports > 1 → ValueError('Time-gating only works on one-ports. ...')；
- 只给 center/span 且 center 为 None 时，skrf 会把 center 当成**峰值所在时刻**
  （ntwk.s_time_mag.argmax() 后取 ntwk.frequency.t_ns，纳秒值再乘 t_mult），
  语义容易踩坑；本模块**总是**先解析成显式 start/stop 再调用，绕开该分支；
- t_unit=""（默认）在传了门参数时会发 DeprecationWarning；本模块总是显式传
  t_unit="s"；
- fft_window 默认 'cosine'：对**不含 DC 的带通数据**（如 2–3 GHz 的 S11），
  频域加窗再除回去会把带边放大——实测纹波抬到 40+ dB 级（见 test 实测）。本模块
  默认 fft_window=None，把该旋钮留给调用方。
- 门窗由 scipy.signal.get_window(window, width, fftbins=False) 生成：'boxcar'
  通带平顶（对分离良好的回波最保真），('kaiser', 6) 类窗**中心高、两端衰减**，
  宽门也会削主响应峰（合成实测 kaiser 160ns 仍把谷深 -20.0 削到 -19.36 dB）。

约定与边界
----------
- 只做确定性数值（纯 numpy + skrf），无随机、无网络、无全局状态；
- 维度/频率网格不符 → 显式 ValueError/TypeError，绝不静默广播；
- 指标只描述**时域门控对频域曲线做了什么**，不主张"回波一定是寄生的"：门宽与
  器件主响应时宽不匹配时，谷位/谷深会被门自身的频域平滑改变（本模块给出
  impulse_out_of_gate_energy_ratio 让调用方看清门到底丢了多少冲激能量）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import skrf

__all__ = [
    "TIME_UNIT_SCALE",
    "TimeGate",
    "band_ripple_db",
    "band_valley",
    "compare_gate",
    "gate_network",
    "has_interior_valley",
    "impulse_out_of_gate_energy_ratio",
    "shoulder_ripple_db",
]

#: 单位 → 秒的换算（skrf.time.time_lookup_dict 的同口径，见 test 接口契约）
TIME_UNIT_SCALE: dict[str, float] = {
    "s": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "µs": 1e-6,
    "ns": 1e-9,
    "ps": 1e-12,
}

_MODES = ("bandpass", "bandstop")
_METHODS = ("fft", "rfft", "convolution")

#: |S| 下限：避免 log10(0) 产生 -inf/warning（门控可把某些点压到 0）
_S_MAG_FLOOR = 1e-30


# ---------------------------------------------------------------------------
# 入参守卫（#140：注解不等于调用方真的传了）
# ---------------------------------------------------------------------------

def _as_network(net: Any, label: str = "network") -> skrf.Network:
    if not isinstance(net, skrf.Network):
        raise TypeError(f"{label} 必须是 skrf.Network，实际 {type(net).__name__}")
    return net


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise TypeError(f"{label} 必须是实数，实际 {type(value).__name__}: {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{label} 必须是有限实数，实际 {out!r}")
    return out


def _to_seconds(value: Any, unit: str, label: str) -> float:
    if unit not in TIME_UNIT_SCALE:
        raise ValueError(f"未知时间单位 {unit!r}；可选 {sorted(TIME_UNIT_SCALE)}")
    return _finite_number(value, label) * TIME_UNIT_SCALE[unit]


def _as_s_param_pair(s_param: Any, nports: int, label: str = "s_param") -> tuple[int, int]:
    if isinstance(s_param, (str, bytes)) or not isinstance(s_param, Sequence):
        raise TypeError(f"{label} 必须是 (i, j) 二元组，实际 {type(s_param).__name__}")
    if len(s_param) != 2:
        raise ValueError(f"{label} 必须是 (i, j) 二元组，实际长度 {len(s_param)}")
    i, j = s_param
    for name, idx in (("i", i), ("j", j)):
        if isinstance(idx, bool) or not isinstance(idx, (int, np.integer)):
            raise TypeError(f"{label}[{name}] 必须是整数，实际 {type(idx).__name__}")
        if not 0 <= int(idx) < nports:
            raise ValueError(
                f"{label}[{name}]={idx} 越界（网络 {nports} 端口，合法 0..{nports - 1}）"
            )
    return int(i), int(j)


def _require_frequency_grid(net: skrf.Network, label: str = "network") -> None:
    if net.frequency.npoints < 2:
        raise ValueError(f"{label} 频率点数 {net.frequency.npoints} < 2，无法做时域变换")
    if not np.all(np.isfinite(net.f)):
        raise ValueError(f"{label} 频率网格含非有限值")


def _require_same_grid(a: skrf.Network, b: skrf.Network, la: str, lb: str) -> None:
    """频率网格与端口数逐点一致——不一致直接报错，不广播（同 core/deembed 口径）。"""
    if a.nports != b.nports:
        raise ValueError(f"{la} 与 {lb} 端口数不一致：{a.nports} vs {b.nports}")
    if a.f.shape != b.f.shape or not np.allclose(a.f, b.f):
        raise ValueError(f"{la} 与 {lb} 频率网格不一致：{len(a.f)} 点 vs {len(b.f)} 点")


def _band_mask(freq_hz: np.ndarray, band: Any, label: str = "band") -> np.ndarray:
    """band=None → 全带；否则 (lo, hi) 闭区间掩码。空交集显式报错（#121）。"""
    if band is None:
        mask = np.ones(len(freq_hz), dtype=bool)
    else:
        if isinstance(band, (str, bytes)) or not isinstance(band, Sequence) or len(band) != 2:
            raise ValueError(f"{label} 必须是 (lo_hz, hi_hz) 二元组或 None")
        lo = _finite_number(band[0], f"{label}[0]")
        hi = _finite_number(band[1], f"{label}[1]")
        if not hi > lo:
            raise ValueError(f"{label} 需满足 hi > lo，实际 ({lo}, {hi})")
        mask = (freq_hz >= lo) & (freq_hz <= hi)
    if int(mask.sum()) < 3:
        raise ValueError(f"{label} 选中的频点仅 {int(mask.sum())} 个（<3），无法给出谷位/纹波")
    return mask


# ---------------------------------------------------------------------------
# 门参数值对象
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimeGate:
    """时域门参数（不可变）。两种等价口径，二选一：

    - start_s + stop_s：门的起止时刻（秒）；
    - center_s + span_s：门的中心/宽度（秒）。

    构造优先走 from_times / from_center_span（带单位），直接构造时所有时间量
    一律以**秒**为单位。
    """

    start_s: float | None = None
    stop_s: float | None = None
    center_s: float | None = None
    span_s: float | None = None
    window: Any = field(default=("kaiser", 6.0))
    mode: str = "bandpass"
    method: str = "fft"
    fft_window: Any = None

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ValueError(f"mode 必须是 {_MODES} 之一，实际 {self.mode!r}")
        if self.method not in _METHODS:
            raise ValueError(f"method 必须是 {_METHODS} 之一，实际 {self.method!r}")
        given_times = self.start_s is not None or self.stop_s is not None
        given_span = self.center_s is not None or self.span_s is not None
        if given_times and given_span:
            raise ValueError(
                "TimeGate 只能给 (start_s, stop_s) 或 (center_s, span_s)，不能同时给"
            )
        if not (given_times or given_span):
            raise ValueError(
                "TimeGate 需要完整的 (start_s, stop_s) 或 (center_s, span_s)"
                "（本模块不支持 skrf 的自动门，避免峰值时刻的隐式依赖）"
            )
        if given_times:
            if self.start_s is None or self.stop_s is None:
                raise ValueError("(start_s, stop_s) 必须同时给出，缺一不可")
            start = _finite_number(self.start_s, "start_s")
            stop = _finite_number(self.stop_s, "stop_s")
            if stop <= start:
                raise ValueError(f"stop_s ({stop}) 必须严格大于 start_s ({start})")
        else:
            if self.center_s is None or self.span_s is None:
                raise ValueError("(center_s, span_s) 必须同时给出，缺一不可")
            _finite_number(self.center_s, "center_s")
            span = _finite_number(self.span_s, "span_s")
            if span <= 0.0:
                raise ValueError(f"span_s ({span}) 必须为正")

    # -- 构造 -----------------------------------------------------------------

    @classmethod
    def from_times(cls, start: float, stop: float, unit: str = "ns", **kwargs: Any) -> TimeGate:
        """按给定单位构造 (start, stop) 门。"""
        return cls(
            start_s=_to_seconds(start, unit, "start"),
            stop_s=_to_seconds(stop, unit, "stop"),
            **kwargs,
        )

    @classmethod
    def from_center_span(
        cls, center: float, span: float, unit: str = "ns", **kwargs: Any
    ) -> TimeGate:
        """按给定单位构造 (center, span) 门。"""
        return cls(
            center_s=_to_seconds(center, unit, "center"),
            span_s=_to_seconds(span, unit, "span"),
            **kwargs,
        )

    @classmethod
    def full_record(
        cls,
        net: skrf.Network,
        *,
        window: Any = "boxcar",
        mode: str = "bandpass",
        method: str = "fft",
        fft_window: Any = None,
    ) -> TimeGate:
        """覆盖整个 FFT 时间记录的门（默认 boxcar）——数学上等于恒等变换。

        作为"全门"边界用：门宽 = 记录长度，闸门在时间轴上全 1。
        """
        net = _as_network(net)
        _require_frequency_grid(net)
        n = int(net.frequency.npoints)
        dt = 1.0 / (n * float(net.frequency.step))
        half = dt * n  # 刻意大于半记录长，find_nearest_index 会夹到首尾
        return cls(
            start_s=-half,
            stop_s=half,
            window=window,
            mode=mode,
            method=method,
            fft_window=fft_window,
        )

    # -- 派生 -----------------------------------------------------------------

    @property
    def resolved_s(self) -> tuple[float, float]:
        """解析为显式 (start_s, stop_s)（秒）——永远带 start < stop。"""
        if self.start_s is not None:
            return float(self.start_s), float(self.stop_s)
        half = float(self.span_s) / 2.0
        center = float(self.center_s)
        return center - half, center + half

    def to_dict(self) -> dict[str, Any]:
        start, stop = self.resolved_s
        return {
            "start_s": start,
            "stop_s": stop,
            "window": self.window if not isinstance(self.window, tuple) else list(self.window),
            "mode": self.mode,
            "method": self.method,
            "fft_window": (
                self.fft_window if not isinstance(self.fft_window, tuple) else list(self.fft_window)
            ),
        }


# ---------------------------------------------------------------------------
# 门控
# ---------------------------------------------------------------------------

def _one_port(net: skrf.Network, i: int, j: int) -> skrf.Network:
    """取 (i, j) 元素做成 1 端口网络（skrf 的 time_gate 只吃 1 端口）。"""
    z0 = np.asarray(net.z0)
    z0_i = z0[:, i, i] if z0.ndim == 3 else z0[:, i]
    return skrf.Network(
        frequency=net.frequency,
        s=net.s[:, i, j].reshape(-1, 1, 1),
        z0=np.asarray(z0_i, dtype=complex).reshape(-1),
    )


def _resolve_pairs(net: skrf.Network, s_params: Any) -> list[tuple[int, int]]:
    if s_params is None:
        return [(i, j) for i in range(net.nports) for j in range(net.nports)]
    if isinstance(s_params, (str, bytes)) or not isinstance(s_params, Iterable):
        raise TypeError("s_params 必须是 (i, j) 二元组的可迭代对象或 None")
    pairs: list[tuple[int, int]] = []
    for item in s_params:
        pair = _as_s_param_pair(item, net.nports)
        if pair not in pairs:
            pairs.append(pair)
    if not pairs:
        raise ValueError("s_params 不能为空（如需恒等请直接传 gate=None）")
    return pairs


def gate_network(
    net: skrf.Network,
    gate: TimeGate | None = None,
    *,
    s_params: Any = None,
) -> skrf.Network:
    """对频域网络做时域门控，返回**新的** skrf.Network。

    Parameters
    ----------
    net : skrf.Network
        频域网络（N 端口）。
    gate : TimeGate or None
        None 表示"无门" → 返回 net.copy()（恒等）。
    s_params : iterable of (i, j), optional
        要门控的 S 元素；默认**全部** (i, j)（符合 skrf 对 N 端口"逐 S 参数
        独立门控"的官方要求）。

    Returns
    -------
    skrf.Network
        频率轴/z0/name 与原网络一致，仅所选 S 元素被替换。
    """
    net = _as_network(net)
    _require_frequency_grid(net)
    if gate is None:
        return net.copy()
    if not isinstance(gate, TimeGate):
        raise TypeError(f"gate 必须是 TimeGate 或 None，实际 {type(gate).__name__}")
    start_s, stop_s = gate.resolved_s
    pairs = _resolve_pairs(net, s_params)
    out = net.copy()
    for i, j in pairs:
        gated = skrf.time.time_gate(
            _one_port(net, i, j),
            start=start_s,
            stop=stop_s,
            window=gate.window,
            mode=gate.mode,
            method=gate.method,
            fft_window=gate.fft_window,
            t_unit="s",
        )
        out.s[:, i, j] = gated.s[:, 0, 0]
    return out


# ---------------------------------------------------------------------------
# 对比指标
# ---------------------------------------------------------------------------

def _port_db(net: skrf.Network, s_param: Any) -> np.ndarray:
    i, j = _as_s_param_pair(s_param, net.nports)
    mag = np.maximum(np.abs(net.s[:, i, j]), _S_MAG_FLOOR)
    return 20.0 * np.log10(mag)


def band_valley(net: skrf.Network, s_param: Any = (0, 0), band: Any = None) -> tuple[float, float]:
    """带内 |S| 谷位：返回 (谷频 Hz, 谷值 dB)。

    谷位取带内 20*log10|S_ij| 的最小值所在频点——与 core 判据统计量口径一致
    （#195：谷深语义走显式指标，不用带内 max/mean 冒充）。
    """
    net = _as_network(net)
    _require_frequency_grid(net)
    db = _port_db(net, s_param)
    mask = _band_mask(net.f, band)
    k = int(np.flatnonzero(mask)[int(np.argmin(db[mask]))])
    return float(net.f[k]), float(db[k])


def band_ripple_db(net: skrf.Network, s_param: Any = (0, 0), band: Any = None) -> float:
    """带内纹波（dB）= 带内 20*log10|S_ij| 的峰峰值。"""
    net = _as_network(net)
    _require_frequency_grid(net)
    db = _port_db(net, s_param)
    v = db[_band_mask(net.f, band)]
    return float(v.max() - v.min())


def shoulder_ripple_db(
    net: skrf.Network,
    s_param: Any = (0, 0),
    band: Any = None,
    *,
    notch_exclusion: float = 0.10,
) -> float:
    """肩部纹波（dB）= 带内**挖掉谷位邻域**后的峰峰值。

    notch_exclusion 是挖掉的半宽占分析带宽的比例（0 ≤ x < 0.5）。谷位附近的深谷
    会把整带峰峰值撑大，肩部纹波更能反映"条纹型"纹波。
    """
    excl = _finite_number(notch_exclusion, "notch_exclusion")
    if not 0.0 <= excl < 0.5:
        raise ValueError(f"notch_exclusion 需落在 [0, 0.5)，实际 {excl}")
    net = _as_network(net)
    _require_frequency_grid(net)
    db = _port_db(net, s_param)
    mask = _band_mask(net.f, band)
    fv = net.f[mask]
    dbv = db[mask]
    k = int(np.argmin(dbv))
    band_w = float(fv[-1] - fv[0])
    keep = np.abs(fv - fv[k]) > excl * band_w
    if int(keep.sum()) < 3:
        raise ValueError(f"notch_exclusion={excl} 把肩部挖到只剩 {int(keep.sum())} 点（<3）")
    return float(dbv[keep].max() - dbv[keep].min())


def has_interior_valley(
    net: skrf.Network,
    s_param: Any = (0, 0),
    band: Any = None,
    *,
    edge_margin: float = 0.05,
) -> bool:
    """谷位是否落在带内（距任一带边 > edge_margin × 带宽）。

    谷位贴在带边 = 带内没有真正的谷（归档不适合作为"谷位不漂"的验证对象）。
    """
    margin = _finite_number(edge_margin, "edge_margin")
    if not 0.0 <= margin < 0.5:
        raise ValueError(f"edge_margin 需落在 [0, 0.5)，实际 {margin}")
    net = _as_network(net)
    _require_frequency_grid(net)
    db = _port_db(net, s_param)
    mask = _band_mask(net.f, band)
    fv = net.f[mask]
    k = int(np.argmin(db[mask]))
    band_w = float(fv[-1] - fv[0])
    offset = float(fv[k] - fv[0])
    return bool(margin * band_w < offset < (1.0 - margin) * band_w)


def impulse_out_of_gate_energy_ratio(
    net: skrf.Network,
    gate: TimeGate,
    s_param: Any = (0, 0),
    *,
    window: Any = "hamming",
) -> float:
    """门外冲激能量比 = 门外 |冲激响应|² 之和 / 总能量（0..1）。

    用 skrf 的 impulse_response（默认 hamming 窗，与 gate 内部时间轴同长）估门丢掉
    多少时间域能量；作为"门是否在切真实信号"的指示量，不是判决。
    """
    net = _as_network(net)
    _require_frequency_grid(net)
    if not isinstance(gate, TimeGate):
        raise TypeError(f"gate 必须是 TimeGate，实际 {type(gate).__name__}")
    i, j = _as_s_param_pair(s_param, net.nports)
    t, y = _one_port(net, i, j).impulse_response(window=window)
    energy = np.abs(np.ravel(np.atleast_1d(y))) ** 2
    total = float(energy.sum())
    if total <= 0.0:
        raise ValueError("冲激响应总能量为 0，无法给出门外能量比")
    start_s, stop_s = gate.resolved_s
    inside = (t >= start_s) & (t <= stop_s)
    return float(energy[~inside].sum() / total)


def _shot(
    net: skrf.Network, s_param: Any, band: Any, notch_exclusion: float
) -> dict[str, float]:
    f_hz, dip_db = band_valley(net, s_param, band)
    return {
        "dip_freq_hz": f_hz,
        "dip_freq_ghz": f_hz / 1e9,
        "dip_db": dip_db,
        "band_ripple_db": band_ripple_db(net, s_param, band),
        "shoulder_ripple_db": shoulder_ripple_db(
            net, s_param, band, notch_exclusion=notch_exclusion
        ),
    }


def compare_gate(
    before: skrf.Network,
    after: skrf.Network,
    *,
    s_param: Any = (0, 0),
    band: Any = None,
    notch_exclusion: float = 0.10,
    gate: TimeGate | None = None,
) -> dict[str, Any]:
    """门控前后对比报告（JSON 友好 dict）。

    返回 before / after 两组指标 + 差值：谷位漂移 dip_shift_hz（正 = 向高频漂）、
    纹波变化 band_ripple_delta_db / shoulder_ripple_delta_db（**负 = 纹波下降**）。
    给了 gate 时附带 out_of_gate_energy_ratio。
    """
    before = _as_network(before, "before")
    after = _as_network(after, "after")
    _require_frequency_grid(before, "before")
    _require_same_grid(before, after, "before", "after")
    before_m = _shot(before, s_param, band, notch_exclusion)
    after_m = _shot(after, s_param, band, notch_exclusion)
    f_lo = float(before.f[0] if band is None else band[0])
    f_hi = float(before.f[-1] if band is None else band[1])
    report: dict[str, Any] = {
        "s_param": list(_as_s_param_pair(s_param, before.nports)),
        "band_hz": [f_lo, f_hi],
        "notch_exclusion": float(notch_exclusion),
        "before": before_m,
        "after": after_m,
        "dip_shift_hz": after_m["dip_freq_hz"] - before_m["dip_freq_hz"],
        "dip_shift_ghz": after_m["dip_freq_ghz"] - before_m["dip_freq_ghz"],
        "dip_db_delta_db": after_m["dip_db"] - before_m["dip_db"],
        "band_ripple_delta_db": after_m["band_ripple_db"] - before_m["band_ripple_db"],
        "shoulder_ripple_delta_db": (
            after_m["shoulder_ripple_db"] - before_m["shoulder_ripple_db"]
        ),
    }
    if gate is not None:
        report["out_of_gate_energy_ratio"] = impulse_out_of_gate_energy_ratio(
            before, gate, s_param
        )
    return report
