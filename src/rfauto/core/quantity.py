"""A2 quantity 类型 + 量纲守卫（月计划 I 流 B2；typed tool call 数值二元组）。

仓库盘点（#222 三查，2026-09-28）：
- adapters/hfss_builder_utils.Quantity（B7 量纲安全构建器，#218 家族）是
  **HFSS 构建器面**——只收 mm/nm/m 三种显式单位、输出 to_hfss() 串；它住
  adapters 层，core（分层底座）不可反向 import。A2 的缺口是 **agent typed
  tool call 的入参面**：工具入参声明为物理量时，LLM/外部调用方必须以
  ``{"value": 2.4, "unit": "GHz"}`` 数值二元组传入，且量纲与声明相符——
  裸数字/错量纲在此拒收（规则 7：typed tool call 可复现、模型无关）。
- pint **不进运行时依赖**：本模块实现为**确定性内置单位表 + SI 七基本
  量纲指数代数**（纯 stdlib，零依赖、零网络），内核自洽维持。pint 互换
  面走 :func:`to_pint` / :func:`from_pint` 可选桥（B2-2 followUp，ge5
  B 小件批落地）——惰性 import，未安装时 ImportError 诚实降级并指向
  ``pip install rfauto[units]``（pyproject ``units`` extra，pint>=0.24）；
  桥只是换能器，量纲校验仍以本模块单位表/量纲代数单源。

判据预声明（合成回收，#118）：
- 换算回收：2.4 GHz → si_value=2.4e9（逐位）；1 mm → 1e-3。
- 量纲代数回收：dim(frequency)+dim(time)==无量纲（指数相加为零）；
  si_value 复合 2.4 GHz × 1 ns = 2.4（approx）。
- 错配拒收：frequency 声明收 "mm" → QuantityDimensionError，报文含
  expected/got 量纲名。
- 非线性域显式排除：dB/dBm 是对数域记号（线性代数下混用是经典翻车），
  不入单位表——解析即报错，不做"近似无量纲"的静默降维。
- 摄氏度拒收（非原点线性量，+273.15 偏移不可与热力学量纲代数混算），
  只收 K。

守卫面（fail-closed）：:func:`validate_quantity_args` 对参数声明里
``type=="quantity"`` 的项校验入参——裸数字、缺 unit、错量纲、未知单位、
bool/NaN/Inf 值一律进错误清单；**未声明 quantity 的参数零过问**（既有
工具行为零变化）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

__all__ = [
    "DIMENSIONS",
    "PINT_SI_UNITS",
    "UNIT_TABLE",
    "Dimension",
    "Quantity",
    "QuantityDimensionError",
    "QuantityError",
    "check_dimension",
    "dimension_of",
    "from_pint",
    "parse_quantity",
    "quantity_of",
    "to_pint",
    "validate_quantity_args",
]


class QuantityError(ValueError):
    """quantity 面 base 异常（解析/校验失败，fail-closed）。"""


class QuantityDimensionError(QuantityError):
    """量纲不匹配（expected vs got 进报文）。"""


@dataclass(frozen=True)
class Dimension:
    """SI 七基本量纲指数向量（length 长度 mass 质量 time 时间 current 电流
    temperature 温度 amount 物质的量 luminous 发光强度）。

    乘法=指数相加、除法=指数相减；全零=无量纲。字段用全名不用单字母
    SI 符号：``I``（电流）撞 ruff E741 歧义名（l/I/0 视读）。
    """

    length: int = 0
    mass: int = 0
    time: int = 0
    current: int = 0
    temperature: int = 0
    amount: int = 0
    luminous: int = 0

    def __add__(self, other: Dimension) -> Dimension:
        return replace(self, **{k: getattr(self, k) + getattr(other, k)
                                for k in self.__dataclass_fields__})

    def __sub__(self, other: Dimension) -> Dimension:
        return replace(self, **{k: getattr(self, k) - getattr(other, k)
                                for k in self.__dataclass_fields__})

    @property
    def is_dimensionless(self) -> bool:
        return all(getattr(self, k) == 0 for k in self.__dataclass_fields__)


#: 量纲名 → 指数向量（守卫声明用的规范名；导出量纲按 SI 代数派生）
DIMENSIONS: dict[str, Dimension] = {
    "dimensionless": Dimension(),
    "length": Dimension(length=1),
    "area": Dimension(length=2),
    "mass": Dimension(mass=1),
    "time": Dimension(time=1),
    "frequency": Dimension(time=-1),
    "current": Dimension(current=1),
    "voltage": Dimension(length=2, mass=1, time=-3, current=-1),
    "resistance": Dimension(length=2, mass=1, time=-3, current=-2),
    "power": Dimension(length=2, mass=1, time=-3),
    "capacitance": Dimension(length=-2, mass=-1, time=4, current=2),
    "inductance": Dimension(length=2, mass=1, time=-2, current=-2),
    "temperature": Dimension(temperature=1),
    "angle": Dimension(),  # 单独标签：rad/deg 与无量纲数值混用也拒（严守卫）
}


def _d(name: str) -> tuple[float, str]:
    return 1.0, name


#: 单位表（大小写敏感，SI 惯例）：unit → (SI 缩放, 量纲规范名)。
#: 规范名直存（不用 Dimension 反查）：angle 与 dimensionless 指数向量同为
#: 全零，反查会把 rad/deg 误标成 dimensionless——量纲标签按单位条目忠实携带。
#: 预声明排除：dB/dBm/dBi（对数域非线性）；degC/°C/f（摄氏非原点量）；
#: eV/atm/psi 等工程杂制按需增补（增补时同步 test_quantity 回收钉）。
UNIT_TABLE: dict[str, tuple[float, str]] = {
    # length
    "m": _d("length"), "km": (1e3, "length"),
    "cm": (1e-2, "length"), "mm": (1e-3, "length"),
    "um": (1e-6, "length"), "µm": (1e-6, "length"),
    "nm": (1e-9, "length"),
    # area
    "m2": (1.0, "area"), "m^2": (1.0, "area"),
    "mm2": (1e-6, "area"), "mm^2": (1e-6, "area"),
    # mass
    "kg": _d("mass"), "g": (1e-3, "mass"),
    # time
    "s": _d("time"), "ms": (1e-3, "time"),
    "us": (1e-6, "time"), "µs": (1e-6, "time"),
    "ns": (1e-9, "time"), "ps": (1e-12, "time"),
    "fs": (1e-15, "time"),
    "min": (60.0, "time"), "h": (3600.0, "time"),
    # frequency
    "Hz": _d("frequency"), "kHz": (1e3, "frequency"),
    "MHz": (1e6, "frequency"), "GHz": (1e9, "frequency"),
    "THz": (1e12, "frequency"),
    # current
    "A": _d("current"), "mA": (1e-3, "current"),
    "uA": (1e-6, "current"), "µA": (1e-6, "current"),
    # voltage
    "V": _d("voltage"), "mV": (1e-3, "voltage"),
    "kV": (1e3, "voltage"),
    # resistance（Ω→ohm 别名双拼）
    "ohm": _d("resistance"), "Ohm": _d("resistance"), "Ω": _d("resistance"),
    "kohm": (1e3, "resistance"), "kOhm": (1e3, "resistance"),
    "kΩ": (1e3, "resistance"),
    "Mohm": (1e6, "resistance"), "MOhm": (1e6, "resistance"),
    "MΩ": (1e6, "resistance"),
    # power
    "W": _d("power"), "mW": (1e-3, "power"),
    "uW": (1e-6, "power"), "µW": (1e-6, "power"),
    "kW": (1e3, "power"),
    # capacitance / inductance
    "F": _d("capacitance"), "pF": (1e-12, "capacitance"),
    "nF": (1e-9, "capacitance"),
    "uF": (1e-6, "capacitance"), "µF": (1e-6, "capacitance"),
    "H": _d("inductance"), "pH": (1e-12, "inductance"),
    "nH": (1e-9, "inductance"),
    "uH": (1e-6, "inductance"), "µH": (1e-6, "inductance"),
    # temperature（只收 K；摄氏非原点量显式拒）
    "K": _d("temperature"),
    # angle（独立量纲标签）
    "rad": _d("angle"), "deg": (math.pi / 180.0, "angle"),
    # dimensionless
    "1": _d("dimensionless"), "": _d("dimensionless"),
    "scalar": _d("dimensionless"), "ratio": _d("dimensionless"),
}


@dataclass(frozen=True)
class Quantity:
    """物理量：原值+原单位（可复现原样保留）+ SI 值+量纲（守卫用）。"""

    value: float
    unit: str
    si_value: float
    dimension: Dimension
    dimension_name: str


def dimension_of(name: str) -> Dimension:
    """量纲规范名 → 指数向量（未知名报错并列可选名）。"""
    dim = DIMENSIONS.get(str(name))
    if dim is None:
        raise QuantityError(
            f"未知量纲名 {name!r}（可用: {sorted(DIMENSIONS)}）")
    return dim


def parse_quantity(arg: Any) -> Quantity:
    """typed tool call 数值二元组 → Quantity（fail-closed）。

    合法入参 = ``{"value": <有限非 bool 实数>, "unit": <单位表内 str>}``；
    其余形态（裸数字、缺键、bool、NaN/Inf、未知单位、摄氏/分贝域）一律
    QuantityError，报文含期望形态（#316 多报方向）。
    """
    if isinstance(arg, (int, float)) and not isinstance(arg, bool):
        raise QuantityError(
            f"quantity 入参收到裸数值 {arg!r}——必须是 {{'value','unit'}} 数值"
            "二元组（裸数字无单位=不可复现，typed tool call 拒收）")
    if not isinstance(arg, Mapping):
        raise QuantityError(
            f"quantity 入参必须是 {{'value','unit'}} 映射，得 {type(arg).__name__}")
    missing = [k for k in ("value", "unit") if k not in arg]
    if missing:
        raise QuantityError(f"quantity 二元组缺键 {missing}（需 value+unit）")
    extra = [k for k in arg if k not in ("value", "unit")]
    if extra:
        raise QuantityError(f"quantity 二元组多键 {sorted(extra)}（只收 value+unit）")
    value = arg["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QuantityError(
            f"quantity value 必须是实数（拒 bool/str），得 {value!r}")
    value = float(value)
    if not math.isfinite(value):
        raise QuantityError(f"quantity value 必须有限（拒 NaN/Inf），得 {arg['value']!r}")
    unit = arg["unit"]
    if not isinstance(unit, str):
        raise QuantityError(f"quantity unit 必须是字符串，得 {unit!r}")
    entry = UNIT_TABLE.get(unit)
    if entry is None:
        if unit.strip().lower() in {"db", "dbm", "dbi", "dbc"}:
            raise QuantityError(
                f"对数域单位 {unit!r} 不入线性单位表（dB/dBm 与量纲代数混算"
                "是已知翻车面）——请以无量纲比值+显式换算表达")
        if unit.strip() in {"degC", "°C", "celsius", "C"}:
            raise QuantityError(
                f"{unit.strip()!r} 是非原点线性量（+273.15 偏移），量纲代数"
                "不可混算——请以 K 表达")
        raise QuantityError(
            f"未知单位 {unit!r}（大小写敏感，SI 惯例）；可用量纲族: "
            f"{sorted(DIMENSIONS)}")
    si_scale, dim_name = entry
    return Quantity(value=value, unit=unit, si_value=value * si_scale,
                    dimension=DIMENSIONS[dim_name], dimension_name=dim_name)


def quantity_of(value: float, unit: str) -> Quantity:
    """位置参数便捷构造（等价 parse_quantity({'value': value, 'unit': unit})）。"""
    return parse_quantity({"value": value, "unit": unit})


def check_dimension(q: Quantity, expected: str) -> None:
    """量纲守卫：q 的量纲 ≠ 声明量纲 → QuantityDimensionError（expected/got 进报文）。"""
    want = dimension_of(expected)
    if q.dimension_name != str(expected) or q.dimension != want:
        raise QuantityDimensionError(
            f"量纲不匹配：声明 {expected!r}（{want}），入参 "
            f"{q.value:g} {q.unit}（{q.dimension_name}）")


def validate_quantity_args(param_specs: Mapping[str, Mapping[str, Any]],
                           args: Mapping[str, Any],
                           required: Mapping[str, Any] | None = None,
                           ) -> list[str]:
    """typed tool call 入参守卫（非抛出形态，返回错误清单；空=过）。

    只校验声明 ``type=="quantity"`` 的参数（须带 ``dimension`` 量纲名）；
    其余参数零过问（既有工具行为零变化）。required 给定时缺参也报
    （缺省不要求——可选 quantity 参数缺席合法）。fail-closed 方向：
    裸数字/缺 unit/错量纲/未知单位/bool/NaN 全部进清单，绝不静默放行。
    """
    errors: list[str] = []
    required_set = set((required or {}).get("quantity") or [])
    for name, spec in (param_specs or {}).items():
        if not isinstance(spec, Mapping) or spec.get("type") != "quantity":
            continue
        dim_name = spec.get("dimension")
        if not dim_name or dim_name not in DIMENSIONS:
            errors.append(f"{name}: quantity 参数未声明合法 dimension"
                          f"（得 {dim_name!r}，可用 {sorted(DIMENSIONS)}）")
            continue
        if name not in args or args[name] is None:
            if name in required_set:
                errors.append(f"{name}: 必填 quantity 参数缺席")
            continue
        try:
            q = parse_quantity(args[name])
            check_dimension(q, str(dim_name))
        except QuantityError as exc:
            errors.append(f"{name}: {exc}")
    return errors


# ─── pint 可选桥（B2-2 followUp；惰性 import，内核零 pint 依赖） ─────────────

#: 量纲规范名 → pint 侧 SI 单位串（to_pint 的 SI 换算出口）。
#: angle 出 rad（pint 缺省把 rad 当无量纲换算——桥面只保证 SI 值互换，
#: 量纲严守卫仍以本模块 check_dimension 单源）。
PINT_SI_UNITS: dict[str, str] = {
    "dimensionless": "",
    "length": "m",
    "area": "m**2",
    "mass": "kg",
    "time": "s",
    "frequency": "Hz",
    "current": "A",
    "voltage": "V",
    "resistance": "ohm",
    "power": "W",
    "capacitance": "F",
    "inductance": "H",
    "temperature": "K",
    "angle": "rad",
}


def _import_pint() -> Any:
    """惰性 pint import（ImportError 诚实降级，指明安装面）。"""
    try:
        import pint
    except ImportError as exc:
        raise ImportError(
            "pint 未安装——quantity↔pint 桥需要可选依赖："
            "pip install rfauto[units]（内核单位表/量纲守卫不依赖 pint）") from exc
    return pint


def to_pint(q: Quantity) -> Any:
    """Quantity → pint.Quantity（SI 值出口；pint 未装 ImportError）。

    出口取 ``si_value`` + 量纲规范名对应的 SI 单位（:data:`PINT_SI_UNITS`）
    ——原值/原单位已在本类型保真，pint 侧拿到的是无歧义 SI 形态。
    """
    pint = _import_pint()
    ureg = pint.UnitRegistry()
    si_unit = PINT_SI_UNITS[q.dimension_name]
    return ureg.Quantity(q.si_value, ureg.Unit(si_unit) if si_unit
                         else ureg.dimensionless)


def from_pint(pq: Any) -> Quantity:
    """pint.Quantity → Quantity（入口复走本模块 parse_quantity 守卫）。

    单位串取 pint 缩写形（``~``）并把 ``**`` 归一成 ``^``（本模块单位表
    的面积记法）；pint 侧单位不在 :data:`UNIT_TABLE` 时如实
    QuantityError（fail-closed，不做静默近似）。
    """
    pint = _import_pint()
    if not isinstance(pq, pint.Quantity):
        raise QuantityError(
            f"from_pint 收到 {type(pq).__name__}——需 pint.Quantity")
    magnitude = float(pq.magnitude)
    unit_str = f"{pq.units:~}".replace("**", "^")
    return parse_quantity({"value": magnitude, "unit": unit_str})
