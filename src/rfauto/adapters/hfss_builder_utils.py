"""HFSS 构建工具——命名常量 + 辅助函数 + B7 量纲安全构建器。

军规 2b：禁止默认命名（Box1, FaceID）；所有几何对象必须使用语义化名称。
命名常量集中管理，便于全局搜索和重命名。

B7（方案 §10.19，#218 家族收口）：几何/参数值一律经 Quantity 显式单位
构造——三类量纲：长度（nm/mm/m）、角度（deg/rad）、无量纲（比值/系数，
单位标识 "1"）；出口按目标工具序列化——HFSS 表达式串（长度预计算浮点+
显式 mm 后缀 / 角度 deg / 无量纲裸数）、openEMS（unit 缩放浮点 / 角度 rad
/ 无量纲比值）、COMSOL（"[mm]"/"[deg]" 串 / 无量纲裸数）、KiCad（长度 nm
整数 / 角度 1/10 度整数 / 无量纲 1e-6 定点整数）；字符串算术表达式
（纯数字串/字面算术/设计变量）在构建期被拒绝。

K6（aurora_k 战役，P13/F11）：net-aware 几何登记薄——建模期给每个金属体
标注 net（signal/ground/other），即建即查异 net 交叠/keepout 侵入/连通分量
三件质量门，并可一条链转出 em doctor 清单 dict（service 层 K5
``run_em_doctor`` 的清单 schema，见模块尾部 net 登记薄一节）。

K7（aurora_k 战役，P12/F6 前半）：CPW 波端口生成器的落地层
``wave_port_cpw(modeler, plan, *, name)``——几何与六不变量断言在纯规划层
``wave_port_planner.plan_wave_port_cpw``（零 pyaedt 依赖），本层只建 aperture
sheet + 赋波端口 + 显式积分线（见模块尾部 wave_port_cpw 一节）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from rfauto.core.errors import ModelBuildError

# ─── 命名常量表 ──────────────────────────────────────────────────────────────

# 基板
SUBSTRATE = "Substrate"

# 接地层
GROUND = "GroundPlane"
GROUND_APERTURE = "GroundAperture"

# 贴片（主辐射体）
PATCH_MAIN = "PatchMain"
PATCH_MAIN_FEED = "PatchMainFeed"

# 馈电结构
FEED_PROBE = "FeedProbe"
FEED_LINE = "FeedLine"
FEED_SLOT = "FeedSlot"

# 微带线（Wilkinson 功分器）
TRACE_INPUT = "TraceInput"           # 输入 50Ω 线
TRACE_ARM_1 = "TraceArm1"            # 70.7Ω λ/4 臂 1
TRACE_ARM_2 = "TraceArm2"            # 70.7Ω λ/4 臂 2
TRACE_OUTPUT_1 = "TraceOutput1"     # 输出 50Ω 线 1
TRACE_OUTPUT_2 = "TraceOutput2"     # 输出 50Ω 线 2
TRACE_JUNCTION = "TraceJunction"    # T-junction 连接区

# 端口
PORT_INPUT = "PortInput"
PORT_OUTPUT_1 = "PortOutput1"
PORT_OUTPUT_2 = "PortOutput2"
PORT_REFERENCE = "PortReference"

# 空气盒 / 辐射边界
AIRBOX = "AirBox"
RADIATION_BOUNDARY = "RadiationBoundary"

# 网格区域
MESH_REGION_FEED = "MeshRegionFeed"
MESH_REGION_PATCH = "MeshRegionPatch"
MESH_REGION_GLOBAL = "MeshRegionGlobal"

# 隔离电阻（Wilkinson）
ISOLATION_RESISTOR = "IsolationResistor"    # 隔离电阻 sheet
RESISTOR_LUMPED = "ResistorLumped"          # lumped RLC 边界名

# 分支线耦合器
BRANCH_LINE_SERIES = "BranchLineSeries"
BRANCH_LINE_SHUNT = "BranchLineShunt"
COUPLER_ARM = "CouplerArm"

# 过孔 / 接地过孔
VIA_GROUND = "ViaGround"
VIA_STITCHING = "ViaStitching"

# 介质 / 材料（与 configs/materials.yaml 对齐）
MATERIAL_SUBSTRATE = "Rogers RO4350 (tm)"   # Rogers 4350B, 0.508mm
MATERIAL_CONDUCTOR = "copper"                # 默认导体材料
MATERIAL_PEC = "pec"                          # PEC（理想导体，用于接地/薄层）
MATERIAL_AIR = "vacuum"                       # 默认空气盒材料

# 求解器设置
SETUP_DEFAULT = "Setup1"
SWEEP_DEFAULT = "Sweep1"
ADAPTIVE_FREQ = "2.4GHz"

# ─── 自动命名模式检测 ────────────────────────────────────────────────────────

# HFSS / AEDT 默认自动生成的对象名称模式
_AUTO_GENERATED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^Box\d+$", re.IGNORECASE),          # Box1, Box2, ...
    re.compile(r"^Cylinder\d+$", re.IGNORECASE),     # Cylinder1, ...
    re.compile(r"^Rectangle\d+$", re.IGNORECASE),    # Rectangle1, ...
    re.compile(r"^Circle\d+$", re.IGNORECASE),       # Circle1, ...
    re.compile(r"^Polyline\d+$", re.IGNORECASE),     # Polyline1, ...
    re.compile(r"^Wire\d+$", re.IGNORECASE),         # Wire1, ...
    re.compile(r"^Face\d+$", re.IGNORECASE),         # Face1, ...
    re.compile(r"^FaceID\s*\d+$", re.IGNORECASE),    # FaceID 123, ...
    re.compile(r"^Object\d+$", re.IGNORECASE),       # Object1, ...
    re.compile(r"^Port\d+$", re.IGNORECASE),         # Port1, Port2, ...
    re.compile(r"^Vacuum\d+$", re.IGNORECASE),       # Vacuum1, ...
    re.compile(r"^PEC\d+$", re.IGNORECASE),          # PEC1, ...
    re.compile(r"^PerfectE_\d+$", re.IGNORECASE),    # PerfectE_1, ...
    re.compile(r"^Setup:\d+$", re.IGNORECASE),       # Setup:1, ...
    re.compile(r"^unnamed", re.IGNORECASE),            # unnamed*, ...
]


def validate_object_name(name: str) -> None:
    """验证对象名称是否符合命名规范。

    军规 2b：禁止使用自动生成的默认名称。

    Parameters
    ----------
    name : str
        要验证的对象名称。

    Raises
    ------
    ModelBuildError
        名称看起来像自动生成的默认名称。
    """
    if not name or not name.strip():
        raise ModelBuildError(
            "对象名称不能为空",
            details={"name": name},
        )

    name = name.strip()

    for pattern in _AUTO_GENERATED_PATTERNS:
        if pattern.match(name):
            raise ModelBuildError(
                f"检测到自动生成的对象名称 '{name}'——违反命名规范（军规 2b）。\n"
                f"请使用语义化名称，例如：\n"
                f"  - Substrate, GroundPlane, PatchMain\n"
                f"  - FeedProbe, PortInput, AirBox\n"
                f"  - 参见 hfss_builder_utils.py 中的命名常量",
                details={
                    "name": name,
                    "rule": "no_auto_generated_names",
                    "reference": "hfss_builder_utils.py",
                },
            )


def parametric_coordinate(
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    params: dict[str, float],
) -> tuple[
    tuple[str, str, str],
    tuple[str, str, str],
]:
    """创建参数化坐标表达式。

    用于将几何位置和尺寸与设计变量关联。
    返回 (center_expr, size_expr)，每个都是 (x, y, z) 字符串元组。

    Parameters
    ----------
    center : tuple[float, float, float]
        中心点坐标 (x, y, z)，单位 mm。
    size : tuple[float, float, float]
        尺寸 (dx, dy, dz)，单位 mm。
    params : dict[str, float]
        设计变量当前值，用于生成表达式。

    Returns
    -------
    tuple[tuple[str, str, str], tuple[str, str, str]]
        (center_expressions, size_expressions)，每个元素是 HFSS 表达式字符串。

    Examples
    --------
    >>> center, size = parametric_coordinate(
    ...     center=(0, 0, 0),
    ...     size=(30, 24, 1.6),
    ...     params={"sub_length": 30, "sub_width": 24, "sub_height": 1.6},
    ... )
    >>> center
    ('0mm', '0mm', '0mm')
    >>> size
    ('sub_length', 'sub_width', 'sub_height')
    """
    center_exprs: list[str] = []
    size_exprs: list[str] = []

    for c in center:
        # 尝试匹配参数值，匹配则用变量名，否则用常量
        matched = False
        for var_name, var_value in params.items():
            if abs(c - var_value) < 1e-6:
                center_exprs.append(var_name)
                matched = True
                break
        if not matched:
            center_exprs.append(f"{c}mm")

    for s in size:
        matched = False
        for var_name, var_value in params.items():
            if abs(s - var_value) < 1e-6:
                size_exprs.append(var_name)
                matched = True
                break
        if not matched:
            size_exprs.append(f"{s}mm")

    return tuple(center_exprs), tuple(size_exprs)  # type: ignore[return-value]


# ─── B7 量纲安全构建器（#218 教训内核化，方案 §10.19 B7）─────────────────────

# 量纲（三类）：长度 / 角度 / 无量纲（比值·系数）
LENGTH = "length"
ANGLE = "angle"
DIMENSIONLESS = "dimensionless"
_DIMENSIONS = (LENGTH, ANGLE, DIMENSIONLESS)

# 各类量纲的单位 → 规范存储换算因子（规范存储：长度 mm / 角度 rad / 无量纲纯比值）
_LENGTH_UNITS_TO_MM: dict[str, float] = {"nm": 1e-6, "mm": 1.0, "m": 1000.0}
_ANGLE_UNITS_TO_RAD: dict[str, float] = {"rad": 1.0, "deg": math.pi / 180.0}
# 无量纲单位标识（HFSS 裸数 / COMSOL "[1]" / 显式 ratio）
_DIMENSIONLESS_UNITS: frozenset[str] = frozenset({"1", "", "ratio", "none"})

# KiCad 整数内部量标度（长度 nm；角度 1/10 度 = EDA_ANGLE::AsTenthsOfADegree；
# 无量纲无原生单位——rfauto 以 1e-6 定点整数承载系数，仅作整数传输约定）
_KICAD_NM_PER_MM = 1e6
_KICAD_TENTHS_PER_DEG = 10.0
_KICAD_DIMENSIONLESS_SCALE = 1e6

# 纯数字串（含科学计数）：HFSS 按模型单位补全（#218 语义一）
_PURE_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
# 无标识符的算术字符集：字面算术表达式，HFSS 按 SI 米求值（#218 语义二）
_NUMERIC_ARITH_RE = re.compile(r"[\d+\-*/().eE\s]+")
# "数值 [单位]" 串（HFSS 后缀式 / COMSOL 方括号式 / 无量纲裸数）
_QUANTITY_TEXT_RE = re.compile(
    r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*"
    r"(\[[^\]]+\]|[A-Za-z]+)?\s*"
)


@dataclass(frozen=True)
class Quantity:
    """带显式单位的几何/参数值（B7 量纲安全构建器内核）。

    三类量纲（dimension）：length（规范存储 mm）、angle（规范存储 rad）、
    dimensionless（比值/系数，规范存储纯比值）。

    #218 三类字符串语义（内部证据档 §二），
    本类一律拒绝、只接受显式单位数值：

    - 纯数字串（"1.113"）：HFSS 按**模型单位**补全，量纲随模型 units 漂移；
    - 字面算术表达式（"-2.5*1.113"）：HFSS 表达式引擎对无量纲算术按
      **SI 米**求值——#218 原案曾致端口 sheet 悬空域外 2.78m；
    - 含设计变量表达式（"2*W"）：量纲随变量定义，变量化建模应走
      set_variables 变量通道（变量带 mm 量纲），不进几何构建器。

    四工具序列化出口（四套单位约定 × 三类量纲）：
    - to_hfss()        → 长度 "2.7825mm" / 角度 "45deg" / 无量纲裸数 "0.5"
    - to_openems(unit) → 长度 unit 缩放浮点 / 角度 rad 浮点 / 无量纲比值
    - to_comsol()      → 长度 "2.7825[mm]" / 角度 "45[deg]" / 无量纲裸数
    - to_kicad()       → 长度 nm 整数 / 角度 1/10 度整数 / 无量纲 1e-6 定点整数

    算术只接受同量纲 Quantity±Quantity、Quantity×标量、Quantity/标量，
    结果仍为 Quantity（量纲不丢）；同量纲 Quantity/Quantity 返回无量纲
    float 比值；系数（无量纲 Quantity）× 带量纲 Quantity 返回带量纲 Quantity。
    """

    value: float
    dimension: str = LENGTH

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ModelBuildError(
                f"几何值必须有限：{self.value!r}",
                details={"value": self.value},
            )
        if self.dimension not in _DIMENSIONS:
            raise ModelBuildError(
                f"未知量纲 {self.dimension!r}（收 {'/'.join(_DIMENSIONS)}）",
                details={"dimension": self.dimension},
            )

    # ── 规范量便捷读取（跨量纲误读即报错）────────────────────────────────
    @property
    def value_mm(self) -> float:
        """长度纲的 mm 规范值。"""
        if self.dimension != LENGTH:
            raise ModelBuildError(
                f"value_mm 只对长度纲有定义（当前 {self.dimension!r}）",
                details={"dimension": self.dimension},
            )
        return self.value

    @property
    def degrees(self) -> float:
        """角度纲的度值。"""
        if self.dimension != ANGLE:
            raise ModelBuildError(
                f"degrees 只对角度纲有定义（当前 {self.dimension!r}）",
                details={"dimension": self.dimension},
            )
        return math.degrees(self.value)

    @property
    def radians(self) -> float:
        """角度纲的弧度值。"""
        if self.dimension != ANGLE:
            raise ModelBuildError(
                f"radians 只对角度纲有定义（当前 {self.dimension!r}）",
                details={"dimension": self.dimension},
            )
        return self.value

    @property
    def ratio_value(self) -> float:
        """无量纲纲的纯比值。"""
        if self.dimension != DIMENSIONLESS:
            raise ModelBuildError(
                f"ratio_value 只对无量纲纲有定义（当前 {self.dimension!r}）",
                details={"dimension": self.dimension},
            )
        return self.value

    @property
    def is_length(self) -> bool:
        return self.dimension == LENGTH

    @property
    def is_angle(self) -> bool:
        return self.dimension == ANGLE

    @property
    def is_dimensionless(self) -> bool:
        return self.dimension == DIMENSIONLESS

    # ── 字符串分类（#218 三类，测试钉死）──────────────────────────────────
    @staticmethod
    def classify_string(s: str) -> str:
        """字符串输入分类：pure_number / literal_arithmetic / design_variable。"""
        t = s.strip()
        if _PURE_NUMBER_RE.fullmatch(t):
            return "pure_number"
        if _NUMERIC_ARITH_RE.fullmatch(t):
            return "literal_arithmetic"
        return "design_variable"

    # ── 构造（唯一入口，显式单位）─────────────────────────────────────────
    @classmethod
    def of(cls, value: float | int | str, unit: str) -> Quantity:
        if isinstance(value, str):
            cat = cls.classify_string(value)
            if cat == "pure_number":
                raise ModelBuildError(
                    f"几何值不接受纯数字字符串 {value!r}：HFSS 对纯数字串按"
                    "模型单位补全（#218 语义一），量纲随模型 units 设置漂移"
                    "——请改用 Quantity.mm()/nm()/m() 显式单位输入",
                    details={"value": value, "category": cat},
                )
            if cat == "literal_arithmetic":
                raise ModelBuildError(
                    f"几何值不接受字面算术表达式 {value!r}：HFSS 表达式引擎对"
                    "无量纲算术按 SI 米求值（#218 语义二，'-2.5*1.113' 曾致"
                    "端口 sheet 悬空域外 2.78m）——请预计算为浮点后经 "
                    "Quantity.mm() 等显式单位输入",
                    details={"value": value, "category": cat},
                )
            raise ModelBuildError(
                f"几何值不接受设计变量/表达式串 {value!r}：变量表达式量纲随"
                "变量定义（#218 语义三），本构建器只接受显式单位数值——变量"
                "化建模请走 set_variables 变量通道（变量带 mm 量纲）",
                details={"value": value, "category": cat},
            )
        if unit in _LENGTH_UNITS_TO_MM:
            return cls(float(value) * _LENGTH_UNITS_TO_MM[unit], LENGTH)
        if unit in _ANGLE_UNITS_TO_RAD:
            return cls(float(value) * _ANGLE_UNITS_TO_RAD[unit], ANGLE)
        if unit in _DIMENSIONLESS_UNITS:
            return cls(float(value), DIMENSIONLESS)
        raise ModelBuildError(
            f"不支持的长度单位 {unit!r}（长度收 "
            f"{'/'.join(_LENGTH_UNITS_TO_MM)}；角度收 "
            f"{'/'.join(_ANGLE_UNITS_TO_RAD)}；无量纲收 '1'）",
            details={"unit": unit},
        )

    @classmethod
    def mm(cls, value: float | int) -> Quantity:
        return cls.of(value, "mm")

    @classmethod
    def nm(cls, value: float | int) -> Quantity:
        return cls.of(value, "nm")

    @classmethod
    def m(cls, value: float | int) -> Quantity:
        return cls.of(value, "m")

    @classmethod
    def deg(cls, value: float | int) -> Quantity:
        return cls.of(value, "deg")

    @classmethod
    def rad(cls, value: float | int) -> Quantity:
        return cls.of(value, "rad")

    @classmethod
    def ratio(cls, value: float | int) -> Quantity:
        """无量纲比值（单位标识 "1"）。"""
        return cls.of(value, "1")

    @classmethod
    def coefficient(cls, value: float | int) -> Quantity:
        """无量纲系数（语义同 ratio，纯比值）。"""
        return cls.of(value, "1")

    # ── 四工具序列化出口 ──────────────────────────────────────────────────
    @staticmethod
    def _fmt(v: float) -> str:
        return format(v, ".10g")

    def to_hfss(self) -> str:
        """HFSS 表达式串：长度预计算 mm 后缀 / 角度 deg / 无量纲裸数字。"""
        if self.dimension == LENGTH:
            return f"{self._fmt(self.value)}mm"
        if self.dimension == ANGLE:
            return f"{self._fmt(math.degrees(self.value))}deg"
        return self._fmt(self.value)

    def to_openems(self, unit: str | None = None) -> float:
        """openEMS CSX 几何值：长度按 unit 缩放 / 角度 rad / 无量纲比值。"""
        if self.dimension == LENGTH:
            u = unit or "mm"
            if u not in _LENGTH_UNITS_TO_MM:
                raise ModelBuildError(
                    f"不支持的长度单位 {u!r}（收 {'/'.join(_LENGTH_UNITS_TO_MM)}）",
                    details={"unit": u},
                )
            return self.value / _LENGTH_UNITS_TO_MM[u]
        if self.dimension == ANGLE:
            u = unit or "rad"
            if u not in _ANGLE_UNITS_TO_RAD:
                raise ModelBuildError(
                    f"不支持的角度单位 {u!r}（收 {'/'.join(_ANGLE_UNITS_TO_RAD)}）",
                    details={"unit": u},
                )
            return self.value / _ANGLE_UNITS_TO_RAD[u]
        u = unit or "1"
        if u not in _DIMENSIONLESS_UNITS:
            raise ModelBuildError(
                f"不支持的无量纲单位 {u!r}（收 '1'）",
                details={"unit": u},
            )
        return self.value

    def to_comsol(self) -> str:
        """COMSOL 几何串：长度 "x[mm]" / 角度 "x[deg]" / 无量纲裸数字。"""
        if self.dimension == LENGTH:
            return f"{self._fmt(self.value)}[mm]"
        if self.dimension == ANGLE:
            return f"{self._fmt(math.degrees(self.value))}[deg]"
        return self._fmt(self.value)

    def to_kicad(self) -> int:
        """KiCad 整数内部量：长度 nm / 角度 1/10 度 / 无量纲 1e-6 定点。

        - 长度：KiCad 内部长度单位 = nm（1 mm = 1e6 nm）；
        - 角度：EDA_ANGLE::AsTenthsOfADegree() = round(deg × 10)；
        - 无量纲：KiCad 无原生无量纲单位，rfauto 约定以 1e-6 定点整数承载
          比值（仅整数传输，不是 KiCad 的原生量纲）。
        """
        if self.dimension == LENGTH:
            return round(self.value * _KICAD_NM_PER_MM)
        if self.dimension == ANGLE:
            return round(math.degrees(self.value) * _KICAD_TENTHS_PER_DEG)
        return round(self.value * _KICAD_DIMENSIONLESS_SCALE)

    # ── 串/整数反解（序列化往返）──────────────────────────────────────────
    @classmethod
    def parse(cls, text: str) -> Quantity:
        """解析本构建器出口串（HFSS 后缀式 / COMSOL 方括号式 / 无量纲裸数）。

        长度串必须带单位（裸数字按无量纲比值解析，避免 #218 语义一的模型
        单位漂移）；字面算术/设计变量串不匹配即报错。
        """
        m = _QUANTITY_TEXT_RE.fullmatch(text or "")
        if m is None:
            raise ModelBuildError(
                f"无法解析为带单位量 {text!r}（期望 '<数值><单位>'、"
                "'<数值>[单位]' 或无量纲裸数）",
                details={"text": text},
            )
        raw_unit = (m.group(2) or "").strip()
        if raw_unit.startswith("[") and raw_unit.endswith("]"):
            raw_unit = raw_unit[1:-1]
        return cls.of(float(m.group(1)), raw_unit or "1")

    @classmethod
    def from_kicad(cls, raw: int, dimension: str) -> Quantity:
        """KiCad 整数内部量反解（to_kicad 的逆）。"""
        if dimension == LENGTH:
            return cls.of(raw, "nm")
        if dimension == ANGLE:
            return cls.of(raw / _KICAD_TENTHS_PER_DEG, "deg")
        if dimension == DIMENSIONLESS:
            return cls.of(raw / _KICAD_DIMENSIONLESS_SCALE, "1")
        raise ModelBuildError(
            f"未知量纲 {dimension!r}（收 {'/'.join(_DIMENSIONS)}）",
            details={"dimension": dimension},
        )

    # ── 量纲安全算术（结果仍为 Quantity，量纲不丢）────────────────────────
    def _require_same_dimension(self, other: Quantity) -> None:
        if other.dimension != self.dimension:
            raise ModelBuildError(
                f"量纲不匹配：{self.dimension!r} 与 {other.dimension!r} 不可加减",
                details={"left": self.dimension, "right": other.dimension},
            )

    def __add__(self, other: Quantity) -> Quantity:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._require_same_dimension(other)
        return Quantity(self.value + other.value, self.dimension)

    def __sub__(self, other: Quantity) -> Quantity:
        if not isinstance(other, Quantity):
            return NotImplemented
        self._require_same_dimension(other)
        return Quantity(self.value - other.value, self.dimension)

    def __neg__(self) -> Quantity:
        return Quantity(-self.value, self.dimension)

    def __mul__(self, scalar: float | int | Quantity) -> Quantity:
        if isinstance(scalar, Quantity):
            # 系数（无量纲）× 带量纲量 → 带量纲量；无量纲×无量纲 → 无量纲
            if self.dimension == DIMENSIONLESS:
                return Quantity(self.value * scalar.value, scalar.dimension)
            if scalar.dimension == DIMENSIONLESS:
                return Quantity(self.value * scalar.value, self.dimension)
            return NotImplemented  # 长度×长度等无物理定义
        return Quantity(self.value * float(scalar), self.dimension)

    def __rmul__(self, scalar: float | int | Quantity) -> Quantity:
        return self.__mul__(scalar)

    def __truediv__(self, other: Quantity | float | int) -> Quantity | float:
        if isinstance(other, Quantity):
            if other.value == 0:
                raise ZeroDivisionError("Quantity 除零")
            if other.dimension == self.dimension:
                return self.value / other.value  # 同量纲 → 无量纲 float 比值
            if other.dimension == DIMENSIONLESS:
                return Quantity(self.value / other.value, self.dimension)
            raise ModelBuildError(
                f"量纲不匹配：{self.dimension!r} 不可除以 {other.dimension!r}",
                details={"left": self.dimension, "right": other.dimension},
            )
        return Quantity(self.value / float(other), self.dimension)


# ─── net-aware 几何登记薄（K6，aurora_k 战役，P13/F11）───────────────────────
#
# 用户实测病灶（反馈 P13/F11 原话）：IDC 倒装波端口第一版 S21≈−99.6 dB（两
# 个端口都短路），根因不是端口，而是 Ø80 植球正好压在 CPW 信号引线上，球顶
# 把信号经球短到盖板；修正=按"植球外接框 ∩ 信号引线矩形"剔除候选。同类：
# pad2 与最外偶指共面接触，railA/railB 短路，S21≈0 dB、串联电阻为负。HFSS
# 的 ValidateDesign 只查语法/拓扑/材料，不查 net 级短路——本节给建模侧 net
# 语义：每个金属体建模时即登记 net，即建即查（不等求解），并把用户手工的
# keepout 剔除做成 API（filter_keepout_candidates）。
#
# 与 service 层 K5 em_doctor_service 的关系：K5 是清单驱动的离线体检器（清
# 单文件 → 报告）；本节是建模期登记薄（活体建模对象 → 即建即查 + 转出清
# 单 dict）。分层契约（.importlinter layers）禁止 adapters import service，
# 故 to_doctor_manifest 只产纯 dict（schema 字段名对齐 em_doctor_service
# docstring：units/objects[name,bbox,net,kind,material?,thickness_z?]/
# keepouts[name,rect,z_range?,clearance?,applies_to?]/device_topology/
# connectivity），对齐正确性由测试端到端钉（test_hfss_net_aware.py）。

#: net 词汇（与 em_doctor_service 同词汇：signal/ground/other）。
NET_SIGNAL = "signal"
NET_GROUND = "ground"
NET_OTHER = "other"
NETS: tuple[str, ...] = (NET_SIGNAL, NET_GROUND, NET_OTHER)

#: 串联器件（IDC/MIM 家族）信号网连通分量期望（P13：railA/railB 不相连）。
SERIES_SIGNAL_COMPONENTS = 2
#: 并联器件信号网连通分量期望（信号网一整条）。
SHUNT_SIGNAL_COMPONENTS = 1

#: 接触容差缺省（按 units 定标，只吸收浮点落格噪声）。数值与 em_doctor_
#: service 的清单容差同源（分层契约禁 import，测试端到端钉对齐）。
_NET_UNIT_ALIASES: dict[str, str] = {"um": "um", "μm": "um", "mm": "mm", "m": "m"}
_NET_CONTACT_TOL: dict[str, float] = {"um": 0.5, "mm": 5e-4, "m": 5e-7}


def _bbox_norm(
    value: object, where: str
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """6 数 bbox → (lo, hi)（逐轴 min/max 强制；非法即 ModelBuildError）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ModelBuildError(
            f"{where}: bbox 需 6 数 [x0,y0,z0,x1,y1,z1]，实际 {value!r}",
            details={"where": where, "value": repr(value)[:200]},
        )
    try:
        nums = [float(v) for v in value]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ModelBuildError(
            f"{where}: bbox 含非数值: {value!r}",
            details={"where": where},
        ) from exc
    lo = tuple(min(nums[i], nums[i + 3]) for i in range(3))
    hi = tuple(max(nums[i], nums[i + 3]) for i in range(3))
    return lo, hi  # type: ignore[return-value]


def _ov1d(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """1D 区间交叠长度（不相交为 0）。"""
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def _gap1d(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> float:
    """1D 区间间隙（相交为 0）。"""
    return max(0.0, b_lo - a_hi, a_lo - b_hi)


def _vol_overlap(
    a: tuple[tuple[float, ...], tuple[float, ...]],
    b: tuple[tuple[float, ...], tuple[float, ...]],
) -> float:
    """3D bbox 交叠体积（不相交为 0）。"""
    vol = 1.0
    for i in range(3):
        ov = _ov1d(a[0][i], a[1][i], b[0][i], b[1][i])
        if ov <= 0.0:
            return 0.0
        vol *= ov
    return vol


def _touch(
    a: tuple[tuple[float, ...], tuple[float, ...]],
    b: tuple[tuple[float, ...], tuple[float, ...]],
    *,
    tol: float,
    axes: tuple[int, ...] = (0, 1, 2),
) -> bool:
    """bbox 接触判定：给定轴集上每轴间隙 ≤ tol（任一轴超 tol 即不接触）。

    axes=(0, 1)=xy 投影接触（连通分量近似）；(0, 1, 2)=3D 接触（贴面）。
    """
    return all(_gap1d(a[0][i], a[1][i], b[0][i], b[1][i]) <= tol for i in axes)


def _components_of(names: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """并查集连通分量（成员列表按输入序，确定性输出）。"""
    parent: dict[str, str] = {n: n for n in names}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # 路径压缩
            parent[x], x = root, parent[x]
        return root

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return sorted(groups.values(), key=lambda g: names.index(g[0]))


@dataclass(frozen=True)
class Keepout:
    """禁入矩形（xy 平面，可选 z 层面/净距阈值/作用对象清单）。

    形态与 em_doctor_service 清单 keepouts 条目同 schema（as_dict 直接可
    入清单）；rect 语义=对象 xy 投影不得与之相交，clearance 语义=侵入之外
    的净距告警阈值（同单位）。
    """

    name: str
    rect: tuple[float, float, float, float]
    clearance: float | None = None
    applies_to: tuple[str, ...] | None = None
    z_range: tuple[float, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        """doctor 清单形态（None 字段省略，消费方按缺省处理）。"""
        d: dict[str, Any] = {
            "name": self.name,
            "rect": [self.rect[0], self.rect[1], self.rect[2], self.rect[3]],
        }
        if self.z_range is not None:
            d["z_range"] = [self.z_range[0], self.z_range[1]]
        if self.clearance is not None:
            d["clearance"] = self.clearance
        if self.applies_to:
            d["applies_to"] = list(self.applies_to)
        return d


@dataclass(frozen=True)
class NetObject:
    """登记薄里的一个建模对象（bbox 为 (lo, hi) 三元组对，units 制）。"""

    name: str
    net: str
    box: tuple[tuple[float, float, float], tuple[float, float, float]]
    kind: str = "metal"
    material: str | None = None
    thickness_z: float | None = None


class NetRegistry:
    """net 登记薄：建模期 net 标注 + 即建即查的几何质量门。

    用法（pyaedt 自定义脚本侧，与命名常量/validate_object_name 同款显式
    调用风格；模块级便捷函数 net_begin/net_add/... 走默认登记薄）::

        from rfauto.adapters.hfss_builder_utils import (
            check_net_overlaps, net_add, net_begin, net_keepout,
            to_doctor_manifest)

        net_begin("ground"); net_add(lid_name); net_add(gnd_name)
        net_begin("signal"); net_add(feed_l_name); net_add(coil_name)
        net_keepout("feed_l_slot", (-70, -720, 30, -60),
                    applies_to=("bump_17",), clearance=30)
        report = check_net_overlaps()      # 即建即查（不等求解）
        manifest = to_doctor_manifest(device_topology="series")
        # 用户脚本侧（service 层）：
        #   from rfauto.service.em_doctor_service import run_em_doctor
        #   run_em_doctor(manifest)

    三件检查（check_net_overlaps/check_keepouts/check_connectivity）全部
    **显式调用、不自动跑**（opt-in）：现有 utils 无自动检查钩子惯例
    （validate_object_name 同为显式调用），且建模中途的暂态（unite 前/后续
    subtract 的正常中间形态）会被自动门误伤——质量门是建模尾部的显式契约
    动作（check_all 一条链跑三件）。

    几何判据与 service 层 em_doctor_service 同语义（bbox 近似的局限一致：
    连通用 xy 投影接触图=高估连通方向；交叠用 3D bbox 体积=L 形假阳性方向；
    零体积贴面只告警不判红）。
    """

    def __init__(self, modeler: Any = None, *, units: str = "mm") -> None:
        """Args: modeler=任意支持 ``obj = modeler[name]`` 且
        ``obj.bounding_box`` 为模型单位 6 数的对象（pyaedt ``app.modeler``；
        测试用 mock 同形态）；units=um|mm|m（bbox 数值单位，默认 mm）。"""
        u = _NET_UNIT_ALIASES.get(str(units).strip())
        if u is None:
            raise ModelBuildError(
                f"net 登记薄 units 需 um|mm|m，实际 {units!r}",
                details={"units": str(units)},
            )
        self._units = u
        self._modeler = modeler
        self._objects: dict[str, NetObject] = {}
        self._keepouts: list[Keepout] = []
        self._active_net: str | None = None

    # ── 属性 ─────────────────────────────────────────────────────────────
    @property
    def units(self) -> str:
        return self._units

    @property
    def objects(self) -> list[NetObject]:
        return list(self._objects.values())

    @property
    def keepouts(self) -> list[Keepout]:
        return list(self._keepouts)

    # ── 登记 ─────────────────────────────────────────────────────────────
    def net_begin(self, net: str) -> None:
        """声明当前 net（后续 net_add 缺省归属到该 net）。

        net ∈ signal|ground|other（与 em doctor 同词汇——金属体必属一 net）。
        """
        n = str(net).strip().lower()
        if n not in NETS:
            raise ModelBuildError(
                f"net 需 {'|'.join(NETS)}，实际 {net!r}",
                details={"net": str(net)},
            )
        self._active_net = n

    def net_add(
        self,
        obj_name: str,
        *,
        net: str | None = None,
        bbox: Any = None,
        kind: str = "metal",
        material: str | None = None,
        thickness_z: float | None = None,
    ) -> NetObject:
        """登记一个建模对象到 net（返回登记记录）。

        net 缺省取 net_begin 声明的活动 net（两者皆空即报错）；bbox 缺省从
        modeler 取 ``modeler[obj_name].bounding_box``（模型单位 6 数，登记
        时按构造 units 记账）；kind: metal|dielectric（异 net 交叠检查只对
        metal——介质层务必标 dielectric）；obj_name 过命名规范（军规 2b）；
        同名重复登记报错（登记薄是台账不是快照）。
        """
        validate_object_name(obj_name)
        n = net if net is not None else self._active_net
        if n is None:
            raise ModelBuildError(
                f"net_add({obj_name}): 无活动 net（先 net_begin 或显式 net=）",
                details={"obj": obj_name},
            )
        n = str(n).strip().lower()
        if n not in NETS:
            raise ModelBuildError(
                f"net_add({obj_name}): net 需 {'|'.join(NETS)}，实际 {n!r}",
                details={"obj": obj_name, "net": n},
            )
        k = str(kind).strip().lower()
        if k not in ("metal", "dielectric"):
            raise ModelBuildError(
                f"net_add({obj_name}): kind 需 metal|dielectric，实际 {kind!r}",
                details={"obj": obj_name, "kind": str(kind)},
            )
        if obj_name in self._objects:
            raise ModelBuildError(
                f"net_add({obj_name}): 同名对象已登记（登记薄不接受重复）",
                details={"obj": obj_name, "net": self._objects[obj_name].net},
            )
        box = (_bbox_norm(bbox, f"net_add({obj_name}) bbox") if bbox is not None
               else self._fetch_bbox(obj_name))
        rec = NetObject(
            name=obj_name, net=n, box=box, kind=k,
            material=material, thickness_z=thickness_z)
        self._objects[obj_name] = rec
        return rec

    def _fetch_bbox(
        self, obj_name: str
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """从 modeler 取 bounding_box（pyaedt 返回模型单位 6 数）。"""
        if self._modeler is None:
            raise ModelBuildError(
                f"net_add({obj_name}): 未给 bbox 且登记薄未挂 modeler——"
                "二选一：net_add(..., bbox=[6 数]) 或 NetRegistry(app.modeler)",
                details={"obj": obj_name},
            )
        try:
            raw = self._modeler[obj_name].bounding_box
        except Exception as exc:  # pyaedt 异常族宽（KeyError/gRPC……）
            raise ModelBuildError(
                f"net_add({obj_name}): modeler 取 bounding_box 失败: {exc}",
                details={"obj": obj_name},
            ) from exc
        return _bbox_norm(raw, f"net_add({obj_name}) bounding_box")

    def net_keepout(
        self,
        name: str,
        rect: Any,
        *,
        clearance: float | None = None,
        applies_to: Any = None,
        z_range: Any = None,
    ) -> Keepout:
        """登记禁入矩形（keepout）：后续对象侵入即 check_keepouts 报红。

        rect=[x0,y0,x1,y1]（xy 矩形，登记薄 units 制）；clearance=净距告警
        阈值（同单位）；applies_to=只检查这些对象名（缺省全部已登记对象）；
        z_range=[z0,z1]=只在 z 层面内生效（缺省不限层）。
        """
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ModelBuildError(
                f"net_keepout({name}): rect 需 4 数 [x0,y0,x1,y1]，实际 {rect!r}",
                details={"keepout": str(name)},
            )
        try:
            rx0, ry0, rx1, ry1 = (float(v) for v in rect)
        except (TypeError, ValueError) as exc:
            raise ModelBuildError(
                f"net_keepout({name}): rect 含非数值，实际 {rect!r}",
                details={"keepout": str(name)},
            ) from exc
        zr: tuple[float, float] | None = None
        if z_range is not None:
            if not isinstance(z_range, (list, tuple)) or len(z_range) != 2:
                raise ModelBuildError(
                    f"net_keepout({name}): z_range 需 2 数 [z0,z1]，实际 {z_range!r}",
                    details={"keepout": str(name)},
                )
            zr = (min(float(z_range[0]), float(z_range[1])),
                  max(float(z_range[0]), float(z_range[1])))
        applies: tuple[str, ...] | None = None
        if applies_to is not None:
            names = tuple(str(a) for a in applies_to)
            applies = names or None  # 空清单视同不限对象（与 doctor 缺省一致）
        try:
            cl = float(clearance) if clearance is not None else None
        except (TypeError, ValueError) as exc:
            raise ModelBuildError(
                f"net_keepout({name}): clearance 非数值，实际 {clearance!r}",
                details={"keepout": str(name)},
            ) from exc
        ko = Keepout(
            name=str(name),
            rect=(min(rx0, rx1), min(ry0, ry1), max(rx0, rx1), max(ry0, ry1)),
            clearance=cl, applies_to=applies, z_range=zr)
        self._keepouts.append(ko)
        return ko

    def nets_report(self) -> dict[str, Any]:
        """登记薄快照：net→对象清单+bbox 并集、逐对象记录、keepout 清单。"""
        nets: dict[str, Any] = {}
        for net in NETS:
            objs = [o for o in self._objects.values() if o.net == net]
            if not objs:
                continue
            lo = tuple(min(o.box[0][i] for o in objs) for i in range(3))
            hi = tuple(max(o.box[1][i] for o in objs) for i in range(3))
            nets[net] = {
                "n": len(objs),
                "objects": [o.name for o in objs],
                "bbox_union": [*lo, *hi],
            }
        return {
            "units": self._units,
            "n_objects": len(self._objects),
            "n_keepouts": len(self._keepouts),
            "nets": nets,
            "objects": [
                {
                    "name": o.name, "net": o.net, "kind": o.kind,
                    "bbox": [*o.box[0], *o.box[1]],
                    **({"material": o.material} if o.material else {}),
                    **({"thickness_z": o.thickness_z}
                       if o.thickness_z is not None else {}),
                }
                for o in self._objects.values()
            ],
            "keepouts": [ko.as_dict() for ko in self._keepouts],
        }

    # ── 检查三件（即建即查，显式调用）────────────────────────────────────
    def _contact_tol(self, tol: float | None) -> float:
        if tol is not None:
            return float(tol)
        return _NET_CONTACT_TOL[self._units]

    def check_net_overlaps(self, tol: float | None = None) -> dict[str, Any]:
        """异 net 金属 3D bbox 交叠检查（doctor 表#8 同语义）。

        交叠体积 > tol³ → violation（人话：植球短信号 S21≈−99.6 dB / pad
        与偶指共面接触 S21≈0 dB 家族）；零体积贴面 → warning（bbox 近似下
        可能是真短路）。同 net 交叠不查（unite 前形态，体互穿属活体检查）。
        """
        t = self._contact_tol(tol)
        vol_tol = t ** 3
        metals = [o for o in self._objects.values() if o.kind == "metal"]
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for i in range(len(metals)):
            for j in range(i + 1, len(metals)):
                a, b = metals[i], metals[j]
                if a.net == b.net:
                    continue
                vol = _vol_overlap(a.box, b.box)
                pair = {
                    "objects": [a.name, b.name], "nets": [a.net, b.net]}
                if vol > vol_tol:
                    violations.append({
                        **pair, "overlap_volume": vol,
                        "detail": (f"{a.name}({a.net}) × {b.name}({b.net}) "
                                   f"3D bbox 交叠体积 {vol:g}——异 net 金属"
                                   "必须零交叠（植球把信号短到地：S21≈−99.6 dB；"
                                   "pad 与偶指共面接触：S21≈0 dB 家族）")})
                elif _touch(a.box, b.box, tol=t):
                    warnings.append({
                        **pair, "overlap_volume": 0.0,
                        "detail": (f"{a.name}({a.net}) × {b.name}({b.net}) "
                                   "bbox 贴面（净距≈0）——bbox 近似下可能是真"
                                   "短路（异 net 金属面接触即短路）")})
        n_cross = sum(
            1 for i in range(len(metals)) for j in range(i + 1, len(metals))
            if metals[i].net != metals[j].net)
        return {
            "check": "net_overlap", "ok": not violations, "tol": t,
            "n_cross_net_pairs": n_cross,
            "violations": violations, "warnings": warnings,
        }

    def check_keepouts(self, tol: float | None = None) -> dict[str, Any]:
        """keepout 侵入/净距检查（doctor 表#12 同语义）。

        对象 xy 投影与禁入矩形两轴交叠均 > tol → violation（人话：Ø80 植球
        压在 CPW 信号引线上，球顶把信号经球短到盖板）；未侵入但净距 ≤
        clearance → warning；applies_to 引用未登记对象名 → warning（清单
        与登记薄对不上是配置错误，多报不放过）。
        """
        t = self._contact_tol(tol)
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if self._keepouts:
            for ko in self._keepouts:
                rx0, ry0, rx1, ry1 = ko.rect
                if ko.applies_to is not None:
                    scope = [self._objects[r] for r in ko.applies_to
                             if r in self._objects]
                    for ref in ko.applies_to:
                        if ref not in self._objects:
                            warnings.append({
                                "keepout": ko.name, "ref": ref,
                                "detail": (f"keepout {ko.name} 的 applies_to "
                                           f"引用未登记对象 {ref}")})
                else:
                    scope = list(self._objects.values())
                for o in scope:
                    if ko.z_range is not None and _ov1d(
                            o.box[0][2], o.box[1][2],
                            ko.z_range[0], ko.z_range[1]) <= t:
                        continue  # 对象不在 keepout 的 z 层面
                    ov_x = _ov1d(o.box[0][0], o.box[1][0], rx0, rx1)
                    ov_y = _ov1d(o.box[0][1], o.box[1][1], ry0, ry1)
                    if ov_x > t and ov_y > t:
                        violations.append({
                            "object": o.name, "net": o.net, "keepout": ko.name,
                            "overlap": [ov_x, ov_y],
                            "detail": (f"对象 {o.name}（net={o.net}）侵入 "
                                       f"keepout {ko.name}（矩形 x[{rx0:g},"
                                       f"{rx1:g}] y[{ry0:g},{ry1:g}]）——"
                                       "植球/凸点压信号引线家族（球顶把信号经"
                                       "球短到盖板：S21≈−99.6 dB）")})
                        continue
                    if ko.clearance is not None:
                        dx = _gap1d(o.box[0][0], o.box[1][0], rx0, rx1)
                        dy = _gap1d(o.box[0][1], o.box[1][1], ry0, ry1)
                        dist = (dx * dx + dy * dy) ** 0.5
                        if 0.0 < dist <= ko.clearance + t:
                            warnings.append({
                                "object": o.name, "keepout": ko.name,
                                "distance": dist,
                                "detail": (f"对象 {o.name} 距 keepout "
                                           f"{ko.name} 净距 {dist:g} ≤ 声明"
                                           f"清距 {ko.clearance:g}")})
        return {
            "check": "keepout_clearance", "ok": not violations, "tol": t,
            "n_keepouts": len(self._keepouts),
            "violations": violations, "warnings": warnings,
        }

    def _net_components(self, net: str, tol: float) -> list[list[str]]:
        """同名 net 的 xy 投影接触图连通分量（bbox 近似=高估连通方向）。"""
        objs = [o for o in self._objects.values() if o.net == net]
        names = [o.name for o in objs]
        edges: list[tuple[str, str]] = []
        for i in range(len(objs)):
            for j in range(i + 1, len(objs)):
                if _touch(objs[i].box, objs[j].box, tol=tol, axes=(0, 1)):
                    edges.append((names[i], names[j]))
        return _components_of(names, edges)

    def check_connectivity(
        self,
        expected: dict[str, int] | None = None,
        *,
        topology: str = "series",
    ) -> dict[str, Any]:
        """同名 net 连通分量数 vs 期望（doctor 表#7 同语义）。

        expected 缺省按 topology 派生：series→信号 2 分量（IDC/MIM 家族
        railA/railB 不相连，SERIES_SIGNAL_COMPONENTS）/ shunt→信号 1 分量
        （SHUNT_SIGNAL_COMPONENTS）；地网期望缺省 1（可被 expected 覆盖）。
        信号网分量数不符 → violation（railA/railB 意外短接：S21≈0 dB、串联
        电阻为负；或信号路径断裂）；地网分裂 → warning（经植球/过孔连通的
        盖板形态是正常分裂，bbox 近似下如实提示不硬判）。
        """
        if topology not in ("series", "shunt"):
            raise ModelBuildError(
                f"topology 需 series|shunt，实际 {topology!r}",
                details={"topology": str(topology)},
            )
        t = self._contact_tol(None)
        exp = dict(expected) if expected else {}
        exp.setdefault("signal", SERIES_SIGNAL_COMPONENTS
                       if topology == "series" else SHUNT_SIGNAL_COMPONENTS)
        exp.setdefault(NET_GROUND, 1)
        by_net: dict[str, Any] = {}
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for net in (NET_SIGNAL, NET_GROUND):
            objs = [o for o in self._objects.values() if o.net == net]
            if not objs:
                continue  # 该 net 无对象：无观测不判（不冒充 PASS 也不凑 FAIL）
            comps = self._net_components(net, t)
            by_net[net] = {
                "components": len(comps), "expected": exp.get(net),
                "members": comps}
            if exp.get(net) is None or len(comps) == exp[net]:
                continue
            entry = {
                "net": net, "components": len(comps), "expected": exp[net],
                "members": comps,
                "detail": (f"{net} 网 {len(comps)} 分量（期望 {exp[net]}）："
                           + " / ".join("+".join(g) for g in comps))}
            if net == NET_SIGNAL:
                entry["detail"] += (
                    "——P13 家族：分量数不符=railA/railB 意外短接（S21≈0 dB、"
                    "串联电阻为负）或信号路径断裂")
                violations.append(entry)
            else:
                entry["detail"] += ("——地网分裂（盖板/地环不连通风险；经植球/"
                                    "过孔连通属正常形态，bbox 近似下如实提示）")
                warnings.append(entry)
        return {
            "check": "net_connectivity", "ok": not violations,
            "topology": topology, "expected": exp, "by_net": by_net,
            "violations": violations, "warnings": warnings,
        }

    def check_all(
        self,
        expected: dict[str, int] | None = None,
        *,
        topology: str = "series",
        tol: float | None = None,
    ) -> dict[str, Any]:
        """建模尾部一条链跑三件检查（显式调用的便捷聚合门）。"""
        checks = [
            self.check_net_overlaps(tol),
            self.check_keepouts(tol),
            self.check_connectivity(expected, topology=topology),
        ]
        return {
            "check": "net_gate", "ok": all(c["ok"] for c in checks),
            "checks": checks}

    # ── 转换桥（K5 em doctor 清单 schema）────────────────────────────────
    def to_doctor_manifest(
        self,
        device_topology: str | None = None,
        connectivity: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """登记薄 → em_doctor_service 清单 dict（字段名对齐其 docstring）。

        产出可直接喂 service 层 ``run_em_doctor(manifest)``（用户脚本侧
        import；adapters 分层契约禁本模块 import service，故只产 dict）。
        device_topology/connectivity 二选一传入（都不传则 doctor 的连通
        分量检查按观测 SKIP，其余检查照常）；bbox/keepout 原样按登记薄
        units 记账。
        """
        report = self.nets_report()
        manifest: dict[str, Any] = {
            "units": self._units,
            "objects": report["objects"],
            "keepouts": report["keepouts"],
        }
        if device_topology is not None:
            manifest["device_topology"] = str(device_topology)
        if connectivity is not None:
            manifest["connectivity"] = dict(connectivity)
        return manifest

    # ── 落点前过滤（植球/凸点候选的 keepout 剔除——用户手工修复的 API 化）──
    def filter_candidates(
        self, candidates: Any, *, tol: float = 0.0
    ) -> dict[str, Any]:
        """对已登记 keepout 过滤候选（见模块级 filter_keepout_candidates）。"""
        return filter_keepout_candidates(candidates, self._keepouts, tol=tol)


def filter_keepout_candidates(
    candidates: Any,
    keepouts: Any,
    *,
    tol: float = 0.0,
) -> dict[str, Any]:
    """落点前 keepout 过滤：剔除与任一 keepout 相交的候选（skipped 如实列出）。

    用户手工修复的 API 化（反馈 P13 原话："修正=按'植球外接框 ∩ 信号引线
    矩形'剔除候选"）——候选（植球/凸点/过孔的 xy 外接矩形）与任一 keepout
    矩形两轴交叠均 > tol 即剔除；返回 kept/skipped 双清单，skipped 逐条带
    命中的 keepout 与交叠量（人话）。

    Parameters
    ----------
    candidates : 序列，元素为 ``(name, (x0, y0, x1, y1))`` 或裸 4 数矩形。
    keepouts : 序列，元素为 :class:`Keepout` 或裸 4 数矩形。
    tol : 交叠阈值（同单位；两轴交叠均 > tol 才算侵入）。

    Returns
    -------
    ``{"kept": [{name, rect}], "skipped": [{candidate, keepout, overlap,
    detail}], "n_kept", "n_skipped}``
    """
    def _rect4(value: Any, where: str) -> tuple[float, float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ModelBuildError(
                f"{where}: 需 4 数矩形 [x0,y0,x1,y1]，实际 {value!r}",
                details={"where": where},
            )
        try:
            xs, ys, xe, ye = (float(v) for v in value)
        except (TypeError, ValueError) as exc:
            raise ModelBuildError(
                f"{where}: 矩形含非数值，实际 {value!r}",
                details={"where": where},
            ) from exc
        return (min(xs, xe), min(ys, ye), max(xs, xe), max(ys, ye))

    ko_pairs: list[tuple[str, tuple[float, float, float, float]]] = []
    for i, ko in enumerate(keepouts or []):
        if isinstance(ko, Keepout):
            ko_pairs.append((ko.name, ko.rect))
        else:
            ko_pairs.append((f"keepout[{i}]", _rect4(ko, f"keepouts[{i}]")))
    cand_pairs: list[tuple[str, tuple[float, float, float, float]]] = []
    for i, c in enumerate(candidates or []):
        if (isinstance(c, (list, tuple)) and len(c) == 2
                and isinstance(c[0], str)):
            cand_pairs.append((c[0], _rect4(c[1], f"candidates[{i}]")))
        else:
            cand_pairs.append((f"candidate[{i}]", _rect4(c, f"candidates[{i}]")))
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for name, (cx0, cy0, cx1, cy1) in cand_pairs:
        hit: dict[str, Any] | None = None
        for ko_name, (kx0, ky0, kx1, ky1) in ko_pairs:
            ov_x = _ov1d(cx0, cx1, kx0, kx1)
            ov_y = _ov1d(cy0, cy1, ky0, ky1)
            if ov_x > tol and ov_y > tol:
                hit = {
                    "candidate": name, "keepout": ko_name,
                    "overlap": [ov_x, ov_y],
                    "detail": (f"候选 {name}（x[{cx0:g},{cx1:g}] "
                               f"y[{cy0:g},{cy1:g}]）与 keepout {ko_name} "
                               f"两轴交叠 {ov_x:g}×{ov_y:g}——按'植球外接框 ∩ "
                               "信号引线矩形'剔除")}
                break
        if hit is None:
            kept.append({"name": name, "rect": [cx0, cy0, cx1, cy1]})
        else:
            skipped.append(hit)
    return {
        "kept": kept, "skipped": skipped,
        "n_kept": len(kept), "n_skipped": len(skipped)}


# ─── 模块级默认登记薄（pyaedt 单模型脚本的自然用法；测试用 reset 隔离）──────

_DEFAULT_NET_REGISTRY = NetRegistry()


def get_net_registry() -> NetRegistry:
    """取模块级默认登记薄（同一模型脚本内所有便捷函数共享）。"""
    return _DEFAULT_NET_REGISTRY


def reset_net_registry(modeler: Any = None, *, units: str = "mm") -> NetRegistry:
    """重置默认登记薄（新模型开工/测试隔离；可同时换挂 modeler/units）。"""
    global _DEFAULT_NET_REGISTRY
    _DEFAULT_NET_REGISTRY = NetRegistry(modeler, units=units)
    return _DEFAULT_NET_REGISTRY


def net_begin(net: str) -> None:
    """默认登记薄：声明当前 net（signal|ground|other）。"""
    _DEFAULT_NET_REGISTRY.net_begin(net)


def net_add(
    obj_name: str,
    *,
    net: str | None = None,
    bbox: Any = None,
    kind: str = "metal",
    material: str | None = None,
    thickness_z: float | None = None,
) -> NetObject:
    """默认登记薄：登记一个建模对象（语义见 NetRegistry.net_add）。"""
    return _DEFAULT_NET_REGISTRY.net_add(
        obj_name, net=net, bbox=bbox, kind=kind, material=material,
        thickness_z=thickness_z)


def net_keepout(
    name: str,
    rect: Any,
    *,
    clearance: float | None = None,
    applies_to: Any = None,
    z_range: Any = None,
) -> Keepout:
    """默认登记薄：登记禁入矩形（语义见 NetRegistry.net_keepout）。"""
    return _DEFAULT_NET_REGISTRY.net_keepout(
        name, rect, clearance=clearance, applies_to=applies_to,
        z_range=z_range)


def nets_report() -> dict[str, Any]:
    """默认登记薄：登记薄快照（net→对象+bbox 并集/逐对象/keepout）。"""
    return _DEFAULT_NET_REGISTRY.nets_report()


def check_net_overlaps(tol: float | None = None) -> dict[str, Any]:
    """默认登记薄：异 net 金属 3D bbox 交叠检查（表#8 语义）。"""
    return _DEFAULT_NET_REGISTRY.check_net_overlaps(tol)


def check_keepouts(tol: float | None = None) -> dict[str, Any]:
    """默认登记薄：keepout 侵入/净距检查（表#12 语义）。"""
    return _DEFAULT_NET_REGISTRY.check_keepouts(tol)


def check_connectivity(
    expected: dict[str, int] | None = None,
    *,
    topology: str = "series",
) -> dict[str, Any]:
    """默认登记薄：同名 net 连通分量 vs 期望（表#7 语义）。"""
    return _DEFAULT_NET_REGISTRY.check_connectivity(expected, topology=topology)


def net_check_all(
    expected: dict[str, int] | None = None,
    *,
    topology: str = "series",
    tol: float | None = None,
) -> dict[str, Any]:
    """默认登记薄：建模尾部一条链跑三件检查。"""
    return _DEFAULT_NET_REGISTRY.check_all(
        expected, topology=topology, tol=tol)


def to_doctor_manifest(
    device_topology: str | None = None,
    connectivity: dict[str, int] | None = None,
) -> dict[str, Any]:
    """默认登记薄 → em doctor 清单 dict（K5 run_em_doctor 的输入 schema）。"""
    return _DEFAULT_NET_REGISTRY.to_doctor_manifest(
        device_topology, connectivity)


# ─── wave_port_cpw 落地层（K7，aurora_k 战役，反馈 P12/F6 前半）───────────────
#
# 与规划器分层：几何与六不变量断言全在 wave_port_planner.plan_wave_port_cpw
# （纯数值、零 pyaedt 依赖、可测核心）；本函数是薄落地层——按 plan 建 aperture
# sheet + 赋波端口 + 显式积分线，不重复几何计算、不代改调用方的边界分配。


def wave_port_cpw(
    modeler: Any,
    plan: dict[str, Any],
    *,
    name: str,
    hfss: Any = None,
) -> dict[str, Any]:
    """按 plan（wave_port_planner 产物）落地一个 HFSS CPW 波端口。

    用户反馈 P12/F6（2026-10-23）：手画 CPW 波端口五类错（aperture 不含金属→
    0.135 nH 假结果/端口面叠辐射/aperture 整块衬底宽/积分线 z 在衬底内/衬底
    不延伸到端口面）的治法=带不变量的生成器。规划器已把六条不变量逐条断言
    （违反即 WavePortPlanError，建模阶段报错）；本函数只做四件事：

    ① 校验 plan 形态（kind 标签+六不变量全绿——拒收 hand-crafted/未验证
       plan，防止绕过规划器直造端口）与端口语义名（军规 2b）；
    ② ``create_rectangle`` 建 aperture sheet（#310 尺寸序：法向 y →
       sizes=[ΔZ, ΔX]、法向 x → [ΔY, ΔZ]，与仓内 hfss_c4_arbitration/
       hfss_marchand_anchor 已验证形态一致；坐标全部拼**显式单位串**
       "<数><um|mm|m>"——B7 精神，um 不在 Quantity 单位表内故此处自拼）；
    ③ ``get_object_faces`` 取端口面；
    ④ ``hfss.wave_port`` 赋波端口+显式积分线 ``[[起点],[终点]]``（pyaedt
       接口形态与仓内仲裁脚本同款：assignment=face id、单模两点列表）。

    边界语义（P12 第 5 条）由 ``plan["boundary_config"]`` 携带：端口面不得叠
    Radiation（调用方辐射面赋值须排除 ``port_face`` 指示的面），面内 aperture
    以外默认 PEC 作端口壁——本函数**不代改**辐射边界（落地层薄，不动调用方
    的边界分配；叠辐射状态在规划期由 ``radiation_on_port_plane=True`` 入参
    断言拦截）。

    Parameters
    ----------
    modeler : pyaedt ``app.modeler``
        需支持 ``create_rectangle`` / ``get_object_faces``（测试用 mock 同形态）。
    plan : dict
        :func:`rfauto.adapters.wave_port_planner.plan_wave_port_cpw` 的产物
        （或 ``plan_from_nets`` 桥产物），``kind="wave_port_cpw_plan"``。
    name : str
        端口语义名（军规 2b；sheet 自动命名 ``f"{name}Sheet"``）。
    hfss : pyaedt ``Hfss`` app, optional
        波端口赋值对象；缺省尝试 ``modeler._app``（pyaedt Primitives 均持
        有），取不到则报错要求显式传入。

    Returns
    -------
    dict
        ``{"port", "sheet", "face", "integration_line", "boundary_config",
        "units", "modes", "impedance", "deembed"}``——F6 端口报告字段（模式
        数/Z0/积分线/参考面=deembed）。

    Raises
    ------
    ModelBuildError
        plan 形态非法/含未通过的不变量、名称违反军规 2b、建 sheet 或赋端口
        失败（pyaedt 异常族收口，带上下文）。
    """
    if not isinstance(plan, dict) or plan.get("kind") != "wave_port_cpw_plan":
        raise ModelBuildError(
            "wave_port_cpw: plan 需为 wave_port_planner.plan_wave_port_cpw 的"
            f"产物（kind='wave_port_cpw_plan'），实际 {type(plan).__name__}"
            f"/kind={plan.get('kind') if isinstance(plan, dict) else None!r}"
            "——六不变量断言在规划器，禁止 hand-crafted plan 绕过",
            details={"kind": plan.get("kind") if isinstance(plan, dict) else None},
        )
    invariants = plan.get("invariants")
    if not isinstance(invariants, dict) or not all(
        isinstance(v, dict) and v.get("ok") is True for v in invariants.values()
    ):
        raise ModelBuildError(
            "wave_port_cpw: plan 含未通过的不变量（invariants 非全绿）——"
            "先在规划器解决违规再落地（违规明细见规划器 WavePortPlanError）",
            details={"invariants": invariants},
        )
    validate_object_name(name)
    sheet_cfg = plan.get("sheet")
    il_cfg = plan.get("integration_line")
    bc = plan.get("boundary_config")
    if not isinstance(sheet_cfg, dict) or not isinstance(il_cfg, dict) \
            or not isinstance(bc, dict):
        raise ModelBuildError(
            "wave_port_cpw: plan 缺 sheet/integration_line/boundary_config 节",
            details={"plan_keys": sorted(plan.keys())},
        )
    u = _NET_UNIT_ALIASES.get(str(plan.get("units") or "").strip())
    if u is None:
        raise ModelBuildError(
            f"wave_port_cpw: plan.units 需 um|mm|m，实际 {plan.get('units')!r}",
            details={"units": str(plan.get("units"))},
        )

    app = hfss if hfss is not None else getattr(modeler, "_app", None)
    if app is None or not hasattr(app, "wave_port"):
        raise ModelBuildError(
            "wave_port_cpw: 波端口赋值需要 pyaedt Hfss app——显式传 hfss=app"
            "（modeler 上取不到 _app/wave_port）",
            details={"name": name},
        )

    def _q(v: Any) -> str:
        """长度值 → 显式单位串（防模型单位漂移；格式同 Quantity._fmt .10g）。"""
        return f"{float(v):.10g}{u}"

    sheet_name = f"{name}Sheet"
    origin = [_q(v) for v in sheet_cfg["origin"]]
    sizes = [_q(v) for v in sheet_cfg["sizes"]]
    try:
        sheet = modeler.create_rectangle(
            orientation=str(sheet_cfg["orientation"]),
            origin=origin, sizes=sizes, name=sheet_name)
    except Exception as exc:
        raise ModelBuildError(
            f"wave_port_cpw({name}): 建 aperture sheet 失败: {exc}",
            details={"name": name, "sheet": sheet_name,
                     "origin": origin, "sizes": sizes},
        ) from exc
    if not sheet:
        raise ModelBuildError(
            f"wave_port_cpw({name}): create_rectangle 返回空（pyaedt 建面失败）",
            details={"name": name, "sheet": sheet_name},
        )
    try:
        faces = modeler.get_object_faces(sheet_name)
    except Exception as exc:
        raise ModelBuildError(
            f"wave_port_cpw({name}): get_object_faces({sheet_name}) 失败: {exc}",
            details={"name": name, "sheet": sheet_name},
        ) from exc
    if not faces:
        raise ModelBuildError(
            f"wave_port_cpw({name}): sheet {sheet_name} 无面（建面形态异常）",
            details={"name": name, "sheet": sheet_name},
        )
    il_start = [_q(v) for v in il_cfg["start"]]
    il_end = [_q(v) for v in il_cfg["end"]]
    modes = int(bc.get("modes", 1))
    impedance = float(bc.get("impedance", 50.0))
    renormalize = bool(bc.get("renormalize", True))
    deembed = float(bc.get("deembed", 0.0))
    try:
        app.wave_port(
            assignment=faces[0], name=name, modes=modes,
            impedance=impedance, renormalize=renormalize, deembed=deembed,
            integration_line=[il_start, il_end])
    except Exception as exc:
        raise ModelBuildError(
            f"wave_port_cpw({name}): pyaedt wave_port 赋值失败: {exc}"
            "（接口形态=assignment=face/integration_line=[[起点],[终点]]，"
            "仓内 hfss_c4_arbitration 先例）",
            details={"name": name, "sheet": sheet_name, "face": faces[0],
                     "integration_line": [il_start, il_end]},
        ) from exc
    return {
        "port": name,
        "sheet": sheet_name,
        "face": faces[0],
        "integration_line": [il_start, il_end],
        "boundary_config": bc,
        "units": u,
        "modes": modes,
        "impedance": impedance,
        "deembed": deembed,
    }


# ─── flip-chip 植球/开窗盖板落地层（K13，aurora_k 战役，反馈 F3/F4）───────────
#
# 与规划器分层（K7 wave_port_cpw 同法）：几何与规则断言全在
# core/flip_chip.py（纯数值零引擎依赖）；本节是薄落地层——按 plan 建
# Sphere+切盒布尔截断（植球鼓形，参考工程 Project1.aedt 的 Sphere 被平面截
# 断做法；圆柱近似低估回路电感）与盖板 Box+窗口 subtract，不重复几何计算。
#
# 布尔/unite 顺序契约（#310 混材料家族 + 反馈 P8 口径，写明）：
# - 植球：Sphere 与切盒 ``intersect``（结果继承首对象名，#285 惯例——球名放
#   首位）；切盒 xy 外扩 1.05×半径（plan.profile.cut_box），避免切盒侧面与
#   球赤道**相切**的退化布尔；
# - 开窗盖板：窗口 ``subtract`` 应在盖板与同材料地金属 ``unite`` **之前**完
#   成（先开窗后合并）；**异材料严禁 unite**（反馈 P8：Cu+Au unite 静默吞
#   材料）——本函数不代任何 unite，调用方按此顺序自行合并。
#
# net 登记：建成的每个球/盖板经模块级默认登记薄（net_begin/net_add 同款）
# 挂 net（balls→ground net 或独立 bump net 由 ``net`` 入参给，词汇
# signal|ground|other）——即建即查面（check_net_overlaps/check_keepouts）
# 由调用方在建模尾部显式跑（K6 opt-in 契约不变）；自持 NetRegistry 实例的
# 用户自行 net_add（本层只走默认登记薄便捷函数）。


def _fc_unit_str(v: Any, u: str) -> str:
    """长度值 → 显式单位串（B7 精神防模型单位漂移；格式同 Quantity._fmt）。"""
    return f"{float(v):.10g}{u}"


def solder_balls(
    modeler: Any,
    plan: dict[str, Any],
    *,
    material: str,
    name_prefix: str,
    net: str = "ground",
) -> dict[str, Any]:
    """按 plan（core/flip_chip.plan_solder_balls 产物）落地植球阵列（鼓形）。

    每球两步（反馈 F3：被上下金属面截断的球，非圆柱）：

    ① ``create_sphere``（origin=[cx,cy,center_z]、radius=R，显式单位串）；
    ② ``create_box`` 切盒（xy 半宽 1.05R、z 跨 [lower_z, upper_z]，plan 已
       预算）+ ``intersect([球名, 切盒名])`` → 鼓形（结果继承首对象名=球名，
       #285 惯例）。

    每球建成即挂 net（模块级默认登记薄 net_add，kind=metal，bbox=外接方
    ±R × z 间隙带，thickness_z=间隙）——balls→ground net（缺省）或独立
    bump net（``net`` 入参）。

    Parameters
    ----------
    modeler : pyaedt ``app.modeler``
        需支持 ``create_sphere`` / ``create_box`` / ``intersect``（测试用 mock
        同形态）。
    plan : dict
        :func:`rfauto.core.flip_chip.plan_solder_balls` 产物
        （``kind="solder_ball_plan"``；拒收 hand-crafted plan）。
    material : 球材料名（如 "SAC305"）。
    name_prefix : 球对象名前缀（语义名，军规 2b；对象名 =
        f"{name_prefix}{i:02d}"——组合名过 validate_object_name，前缀拼出
        自动名形态（如 "Box"）会被拒）。
    net : 球归属 net（signal|ground|other，缺省 ground）。

    Returns
    -------
    dict
        ``{"balls": [对象名], "n_created", "net", "material", "units"}``。

    Raises
    ------
    ModelBuildError
        plan 形态非法/球清单为空、name_prefix 非法、建体或布尔失败
        （pyaedt 异常族收口带上下文）。
    """
    if not isinstance(plan, dict) or plan.get("kind") != "solder_ball_plan":
        raise ModelBuildError(
            "solder_balls: plan 需为 core.flip_chip.plan_solder_balls 的产物"
            f"（kind='solder_ball_plan'），实际 {type(plan).__name__}"
            f"/kind={plan.get('kind') if isinstance(plan, dict) else None!r}"
            "——布点规则断言在规划器，禁止 hand-crafted plan 绕过",
            details={"kind": plan.get("kind") if isinstance(plan, dict) else None},
        )
    balls = list(plan.get("balls") or ())
    if not balls:
        raise ModelBuildError(
            "solder_balls: plan 无已收球（balls 空）——无可落地对象",
            details={"n_skipped": plan.get("n_skipped")},
        )
    cut_cfg = (plan.get("profile") or {}).get("cut_box") or {}
    if "xy_half" not in cut_cfg or "z_range" not in cut_cfg:
        raise ModelBuildError(
            "solder_balls: plan 缺 profile.cut_box（鼓形切盒参数）——"
            "plan 须为 plan_solder_balls 完整产物",
            details={"profile_keys": sorted((plan.get("profile") or {}).keys())},
        )
    cut_half = float(cut_cfg["xy_half"])
    if not str(name_prefix).strip():
        raise ModelBuildError(
            "solder_balls: name_prefix 不能为空（军规 2b 语义名）",
            details={"name_prefix": name_prefix},
        )
    u = _NET_UNIT_ALIASES.get(str(plan.get("units") or "").strip())
    if u is None:
        raise ModelBuildError(
            f"solder_balls: plan.units 需 um|mm|m，实际 {plan.get('units')!r}",
            details={"units": str(plan.get("units"))},
        )
    names: list[str] = []
    for i, b in enumerate(balls):
        bname = f"{name_prefix}{i + 1:02d}"
        validate_object_name(bname)
        cx, cy = (float(v) for v in b["center"])
        r = float(b["ball_d"]) / 2.0
        cz = float(b["center_z"])
        lz = float(b["lower_z"])
        uz = float(b["upper_z"])
        cut_name = f"{bname}CutBox"
        try:
            modeler.create_sphere(
                origin=[_fc_unit_str(cx, u), _fc_unit_str(cy, u),
                        _fc_unit_str(cz, u)],
                radius=_fc_unit_str(r, u),
                name=bname, material=material)
            modeler.create_box(
                origin=[_fc_unit_str(cx - cut_half, u),
                        _fc_unit_str(cy - cut_half, u),
                        _fc_unit_str(lz, u)],
                sizes=[_fc_unit_str(2.0 * cut_half, u),
                       _fc_unit_str(2.0 * cut_half, u),
                       _fc_unit_str(uz - lz, u)],
                name=cut_name, material=material)
            modeler.intersect([bname, cut_name], keep_originals=False)
        except Exception as exc:
            raise ModelBuildError(
                f"solder_balls({bname}): 建球/布尔截断失败: {exc}"
                "（形态=Sphere+切盒 intersect，参考工程 Project1.aedt）",
                details={"ball": bname, "center": [cx, cy], "radius": r,
                         "cut_box_z": [lz, uz]},
            ) from exc
        net_add(
            bname, net=net,
            bbox=[cx - r, cy - r, lz, cx + r, cy + r, uz],
            kind="metal", material=material,
            thickness_z=uz - lz)
        names.append(bname)
    return {
        "balls": names,
        "n_created": len(names),
        "net": net,
        "material": material,
        "units": u,
    }


def lid_with_windows(
    modeler: Any,
    plan: dict[str, Any],
    *,
    material: str,
    name: str = "Lid",
    net: str = "ground",
) -> dict[str, Any]:
    """按 plan（core/flip_chip.plan_lid_windows 产物）落地开窗盖板。

    盖板 Box + 逐窗口 cut Box + **一次** ``subtract(blank=盖板, tools=全部
    窗口盒)``（窗口=全厚度通孔；多窗交叠由 subtract 天然并集吸收）。

    unite 顺序契约（写明，#310/P8 家族）：窗口 subtract 应在盖板与同材料地
    金属 unite **之前**完成（先开窗后合并）；异材料严禁 unite（反馈 P8：
    Cu+Au unite 静默吞材料）——本函数不代任何 unite。

    建成即挂 net（模块级默认登记薄 net_add，kind=metal，bbox=plan.lid_bbox）。

    Parameters
    ----------
    modeler : pyaedt ``app.modeler``
        需支持 ``create_box`` / ``subtract``（测试用 mock 同形态）。
    plan : dict
        :func:`rfauto.core.flip_chip.plan_lid_windows` 产物
        （``kind="lid_window_plan"``；拒收 hand-crafted plan）。
    material : 盖板材料名。
    name : 盖板对象名（语义名，军规 2b；窗口切盒临时名 = f"{name}Win{i}Cut"）。
    net : 盖板归属 net（缺省 ground）。

    Returns
    -------
    dict
        ``{"lid": 盖板名, "windows": [窗口名], "cut_boxes": [切盒名],
        "n_windows", "net", "material", "units"}``。

    Raises
    ------
    ModelBuildError
        plan 形态非法/无窗口、盖板名非法、建体或 subtract 失败。
    """
    if not isinstance(plan, dict) or plan.get("kind") != "lid_window_plan":
        raise ModelBuildError(
            "lid_with_windows: plan 需为 core.flip_chip.plan_lid_windows 的"
            f"产物（kind='lid_window_plan'），实际 {type(plan).__name__}"
            f"/kind={plan.get('kind') if isinstance(plan, dict) else None!r}"
            "——开窗自检断言在规划器，禁止 hand-crafted plan 绕过",
            details={"kind": plan.get("kind") if isinstance(plan, dict) else None},
        )
    windows = list(plan.get("windows") or ())
    if not windows:
        raise ModelBuildError(
            "lid_with_windows: plan 无窗口（windows 空）——不开窗直接建盒，"
            "不走本函数",
            details={"n_windows": 0},
        )
    validate_object_name(name)
    u = _NET_UNIT_ALIASES.get(str(plan.get("units") or "").strip())
    if u is None:
        raise ModelBuildError(
            f"lid_with_windows: plan.units 需 um|mm|m，实际 {plan.get('units')!r}",
            details={"units": str(plan.get("units"))},
        )
    lx0, ly0, lz0, lx1, ly1, lz1 = (float(v) for v in plan["lid_bbox"])
    try:
        modeler.create_box(
            origin=[_fc_unit_str(lx0, u), _fc_unit_str(ly0, u),
                    _fc_unit_str(lz0, u)],
            sizes=[_fc_unit_str(lx1 - lx0, u), _fc_unit_str(ly1 - ly0, u),
                   _fc_unit_str(lz1 - lz0, u)],
            name=name, material=material)
    except Exception as exc:
        raise ModelBuildError(
            f"lid_with_windows({name}): 建盖板失败: {exc}",
            details={"name": name, "lid_bbox": plan["lid_bbox"]},
        ) from exc
    cut_names: list[str] = []
    for i, w in enumerate(windows):
        wx0, wy0, wz0, wx1, wy1, wz1 = (float(v) for v in w["cut_box"])
        cut_name = f"{name}Win{i + 1}Cut"
        try:
            modeler.create_box(
                origin=[_fc_unit_str(wx0, u), _fc_unit_str(wy0, u),
                        _fc_unit_str(wz0, u)],
                sizes=[_fc_unit_str(wx1 - wx0, u), _fc_unit_str(wy1 - wy0, u),
                       _fc_unit_str(wz1 - wz0, u)],
                name=cut_name, material=material)
        except Exception as exc:
            raise ModelBuildError(
                f"lid_with_windows({name}): 建窗口切盒 {cut_name} 失败: {exc}",
                details={"window": w.get("name"), "cut_box": w["cut_box"]},
            ) from exc
        cut_names.append(cut_name)
    try:
        modeler.subtract([name], cut_names, keep_originals=False)
    except Exception as exc:
        raise ModelBuildError(
            f"lid_with_windows({name}): 窗口 subtract 失败: {exc}"
            "（unite 顺序契约：先开窗后与同材料地金属 unite；异材料严禁 "
            "unite——反馈 P8 混材料吞材料）",
            details={"name": name, "cut_boxes": cut_names},
        ) from exc
    net_add(name, net=net, bbox=plan["lid_bbox"], kind="metal",
            material=material, thickness_z=lz1 - lz0)
    return {
        "lid": name,
        "windows": [str(w.get("name")) for w in windows],
        "cut_boxes": cut_names,
        "n_windows": len(cut_names),
        "net": net,
        "material": material,
        "units": u,
    }
