"""双载波无源互调（PIM）产物枚举与落带判定（纯函数，零 IO）。

口径与来源（2026-09-27 核对）：
- 产物频率 f = |m·f1 ± n·f2|、阶数 = |m| + |n|：双载波互调产物的标准枚举
  口径（RF Cafe "Passive Intermodulation" references/electrical/pim.htm——
  core/high_power.py 已引同一页，本仓先例同源；任务书 monthly_plan J 系
  "2f1−f2/3f1−2f2 类"即 (m,n)=(2,1)/(3,2) 差侧产物）。
- 阶数域：2 ≤ m+n ≤ p_max，且 m ≥ 1、n ≥ 1——单载波谐波项 (m,0)/(0,n) 不
  是两载波互调产物，不入表（显式口径，非遗漏；载波自身 (1,0)/(0,1) 同理）。
- 幅度：**只接收实测/规格 dBc 输入**（IEC 62037 无源互调测量口径，典型双音
  测试每载波 +43 dBm）——本模块不产出任何幅度预测数字（铁律 7：数值只在
  确定性内核/实测；PIM 电平与材质/镀层/接触压力/机械工艺强相关，无通用
  闭式，预测即臆造）。未给实测值的产物 dbc=None（判缺失 is not None）。
- 落带判定：矩形近似 |f_pim − rx_center| ≤ rx_bw/2（单带；rx_bw=0 → 逐点
  判定）。rx_center_hz 缺省不判（in_rx_band=None——未判非判外）。

待证/缺位（#122 如实标注）：
- PIM 产物幅度预测/级联式：有意不实现（见上，无通用权威闭式）；
- 低阶实测幅度外推高阶（阶数→幅度幂律）：无逐对权威源核对，不实现。

接口：dataclass + to_dict（JSON 可序列化）；纯 math 零 numpy/scipy/skrf
（与 core/cascade.py 同铁律）；枚举确定性排序（order, f, m, n, side）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# p_max 防呆上限（防误传 1e9 之类挂死枚举；61 阶已远超任何 PIM 关心域）
MAX_PIM_ORDER = 64

# 危险等级梯（与 core/cascade.py spur_search 同构：≤3 high、≤5 medium、其余
# low；本件自包含复制——cascade._hazard_for_order 为模块私有，不跨件引私有）
_HAZARD_HIGH_MAX_ORDER = 3
_HAZARD_MEDIUM_MAX_ORDER = 5

_AMPLITUDE_CONVENTION = (
    "幅度只接收实测/规格 dBc 输入（IEC 62037 无源互调测量口径，典型双音每载波 "
    "+43 dBm）——本模块不产幅度预测数字（铁律 7）；未给实测值 dbc=None")


def _hazard_for_order(order: int) -> str:
    if order <= _HAZARD_HIGH_MAX_ORDER:
        return "high"
    if order <= _HAZARD_MEDIUM_MAX_ORDER:
        return "medium"
    return "low"


@dataclass
class PimProduct:
    """单个 PIM 产物（频率几何 + 可选实测幅度，无预测数字）。"""

    m: int
    n: int
    side: str  # "+"=m·f1+n·f2；"-"=|m·f1−n·f2|
    order: int  # m+n
    f_hz: float
    offset_from_rx_center_hz: float | None
    in_rx_band: bool | None
    hazard: str
    dbc: float | None  # 实测/规格 dBc（未给=None）
    amplitude_source: str | None  # "measured_spec"（给了实测时）

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化平面字典（纯透传）。"""
        return {
            "m": self.m,
            "n": self.n,
            "side": self.side,
            "order": self.order,
            "f_hz": self.f_hz,
            "offset_from_rx_center_hz": self.offset_from_rx_center_hz,
            "in_rx_band": self.in_rx_band,
            "hazard": self.hazard,
            "dbc": self.dbc,
            "amplitude_source": self.amplitude_source,
        }


@dataclass
class PimProductSet:
    """双载波 PIM 产物全集（枚举 + 落带 + 实测幅度归并）。"""

    f1_hz: float
    f2_hz: float
    p_max: int
    rx_center_hz: float | None
    rx_bw_hz: float
    products: list[PimProduct]
    amplitude_convention: str = _AMPLITUDE_CONVENTION

    @property
    def n_products(self) -> int:
        return len(self.products)

    @property
    def n_in_band(self) -> int | None:
        """落带产物数（rx_center 未给=未判 → None，非 0——#364④ 判缺失语义）。"""
        if self.rx_center_hz is None:
            return None
        return sum(1 for p in self.products if p.in_rx_band)

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化（products 逐个 to_dict，计数随行）。"""
        return {
            "f1_hz": self.f1_hz,
            "f2_hz": self.f2_hz,
            "p_max": self.p_max,
            "rx_center_hz": self.rx_center_hz,
            "rx_bw_hz": self.rx_bw_hz,
            "n_products": self.n_products,
            "n_in_band": self.n_in_band,
            "amplitude_convention": self.amplitude_convention,
            "products": [p.to_dict() for p in self.products],
        }


def _finite_positive(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正的有限实数，收到 {value!r}")
    return out


def enumerate_pim_products(
    f1_hz: float,
    f2_hz: float,
    *,
    p_max: int = 7,
    rx_center_hz: float | None = None,
    rx_bw_hz: float = 0.0,
    amplitudes: list[dict[str, Any]] | None = None,
) -> PimProductSet:
    """双载波 PIM 产物枚举：f = |m·f1 ± n·f2|，2 ≤ m+n ≤ p_max 且 m,n ≥ 1。

    幅度只经 amplitudes 注入实测/规格值（[{"m","n","side","dbc"}]，键必须
    命中枚举产物、不得重复——未知/重复/非法键显式报错，不静默丢弃，#316
    "多报不放过"方向）；其余产物 dbc=None。

    Examples
    --------
    >>> from rfauto.core.pim_products import enumerate_pim_products
    >>> ps = enumerate_pim_products(2.4e9, 2.41e9, p_max=3)
    >>> p = next(x for x in ps.products if (x.m, x.n, x.side) == (2, 1, "-"))
    >>> int(p.f_hz), p.order, p.hazard
    (2390000000, 3, 'high')
    >>> ps.n_products  # 手算组合数：(1,1),(1,2),(2,1) 各 ± 两侧
    6
    """
    f1 = _finite_positive(f1_hz, "f1_hz")
    f2 = _finite_positive(f2_hz, "f2_hz")
    if f1 == f2:
        raise ValueError(
            f"f1_hz == f2_hz == {f1!r}（退化单载波，双载波互调模型不适用）——"
            "单载波谐波面请用谐波枚举，两载波须互异")
    if isinstance(p_max, bool) or not isinstance(p_max, int):
        raise ValueError(f"p_max 必须是整数，收到 {p_max!r}")
    if p_max < 2:
        raise ValueError(f"p_max 必须 ≥2（PIM 从 2 阶起），收到 {p_max!r}")
    if p_max > MAX_PIM_ORDER:
        raise ValueError(
            f"p_max 必须 ≤ {MAX_PIM_ORDER}（防呆上限），收到 {p_max!r}")
    rx_bw = _finite_bounded_nonneg(rx_bw_hz, "rx_bw_hz")
    if rx_center_hz is None and rx_bw_hz != 0:
        raise ValueError("给了 rx_bw_hz 但未给 rx_center_hz——带宽无参照即无落带"
                         "判定；请同时给 rx_center_hz 或都不给")
    rx_center = (None if rx_center_hz is None
                 else _finite_bounded_nonneg(rx_center_hz, "rx_center_hz"))

    products: list[PimProduct] = []
    for m in range(1, p_max):
        for n in range(1, p_max + 1 - m):
            order = m + n
            for side, f_pim in (
                ("+", m * f1 + n * f2),
                ("-", abs(m * f1 - n * f2)),
            ):
                if f_pim <= 0.0:  # DC 产物（|m·f1−n·f2| ≡ 0）不入表
                    continue
                if rx_center is None:
                    offset = None
                    in_band = None
                else:
                    offset = f_pim - rx_center
                    in_band = abs(offset) <= 0.5 * rx_bw
                products.append(PimProduct(
                    m=m, n=n, side=side, order=order, f_hz=f_pim,
                    offset_from_rx_center_hz=offset, in_rx_band=in_band,
                    hazard=_hazard_for_order(order),
                    dbc=None, amplitude_source=None))
    products.sort(key=lambda p: (p.order, p.f_hz, p.m, p.n, p.side))

    if amplitudes is not None:
        if not isinstance(amplitudes, list):
            raise ValueError(
                f"amplitudes 必须是 list[dict]，收到 {type(amplitudes)!r}")
        lookup = {(p.m, p.n, p.side): p for p in products}
        seen: set[tuple[int, int, str]] = set()
        for k, spec in enumerate(amplitudes):
            if not isinstance(spec, dict):
                raise ValueError(
                    f"amplitudes[{k}] 必须是 dict，收到 {type(spec)!r}")
            m_v, n_v, side_v = spec.get("m"), spec.get("n"), spec.get("side")
            if isinstance(m_v, bool) or not isinstance(m_v, int):
                raise ValueError(f"amplitudes[{k}].m 必须是整数，收到 {m_v!r}")
            if isinstance(n_v, bool) or not isinstance(n_v, int):
                raise ValueError(f"amplitudes[{k}].n 必须是整数，收到 {n_v!r}")
            if side_v not in ("+", "-"):
                raise ValueError(
                    f"amplitudes[{k}].side 必须是 '+' 或 '-'，收到 {side_v!r}")
            dbc = spec.get("dbc")
            if isinstance(dbc, bool) or not isinstance(dbc, (int, float)) \
                    or not math.isfinite(float(dbc)):
                raise ValueError(
                    f"amplitudes[{k}].dbc 必须为有限实数（实测/规格 dBc），"
                    f"收到 {dbc!r}")
            key = (m_v, n_v, side_v)
            if key not in lookup:
                raise ValueError(
                    f"amplitudes[{k}] 的 (m,n,side)={key} 不在枚举域内"
                    f"（p_max={p_max} 且 m,n≥1）——未知产物的幅度无法归属，"
                    "请扩 p_max 或修正键")
            if key in seen:
                raise ValueError(
                    f"amplitudes[{k}] 重复指定 (m,n,side)={key} 的幅度——"
                    "同一产物只允许一个实测值")
            seen.add(key)
            product = lookup[key]
            product.dbc = float(dbc)
            product.amplitude_source = "measured_spec"
    return PimProductSet(f1_hz=f1, f2_hz=f2, p_max=p_max,
                         rx_center_hz=rx_center, rx_bw_hz=rx_bw,
                         products=products)


def _finite_bounded_nonneg(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"{name} 必须为非负的有限实数，收到 {value!r}")
    return out
