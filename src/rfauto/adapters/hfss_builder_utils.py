"""HFSS 构建工具——命名常量 + 辅助函数 + B7 量纲安全构建器。

军规 2b：禁止默认命名（Box1, FaceID）；所有几何对象必须使用语义化名称。
命名常量集中管理，便于全局搜索和重命名。

B7（方案，#218 家族收口）：几何/参数值一律经 Quantity 显式单位
构造——三类量纲：长度（nm/mm/m）、角度（deg/rad）、无量纲（比值/系数，
单位标识 "1"）；出口按目标工具序列化——HFSS 表达式串（长度预计算浮点+
显式 mm 后缀 / 角度 deg / 无量纲裸数）、openEMS（unit 缩放浮点 / 角度 rad
/ 无量纲比值）、COMSOL（"[mm]"/"[deg]" 串 / 无量纲裸数）、KiCad（长度 nm
整数 / 角度 1/10 度整数 / 无量纲 1e-6 定点整数）；字符串算术表达式
（纯数字串/字面算术/设计变量）在构建期被拒绝。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

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
TRACE_INPUT = "TraceInput"      # 输入 50Ω 线
TRACE_ARM_1 = "TraceArm1"      # 70.7Ω λ/4 臂 1
TRACE_ARM_2 = "TraceArm2"      # 70.7Ω λ/4 臂 2
TRACE_OUTPUT_1 = "TraceOutput1"   # 输出 50Ω 线 1
TRACE_OUTPUT_2 = "TraceOutput2"   # 输出 50Ω 线 2
TRACE_JUNCTION = "TraceJunction"  # T-junction 连接区

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
ISOLATION_RESISTOR = "IsolationResistor"  # 隔离电阻 sheet
RESISTOR_LUMPED = "ResistorLumped"     # lumped RLC 边界名

# 分支线耦合器
BRANCH_LINE_SERIES = "BranchLineSeries"
BRANCH_LINE_SHUNT = "BranchLineShunt"
COUPLER_ARM = "CouplerArm"

# 过孔 / 接地过孔
VIA_GROUND = "ViaGround"
VIA_STITCHING = "ViaStitching"

# 介质 / 材料（与 configs/materials.yaml 对齐）
MATERIAL_SUBSTRATE = "Rogers RO4350 (tm)"  # Rogers 4350B, 0.508mm
MATERIAL_CONDUCTOR = "copper"        # 默认导体材料
MATERIAL_PEC = "pec"             # PEC（理想导体，用于接地/薄层）
MATERIAL_AIR = "vacuum"            # 默认空气盒材料

# 求解器设置
SETUP_DEFAULT = "Setup1"
SWEEP_DEFAULT = "Sweep1"
ADAPTIVE_FREQ = "2.4GHz"

# ─── 自动命名模式检测 ────────────────────────────────────────────────────────

# HFSS / AEDT 默认自动生成的对象名称模式
_AUTO_GENERATED_PATTERNS: list[re.Pattern[str]] = [
  re.compile(r"^Box\d+$", re.IGNORECASE),     # Box1, Box2, ...
  re.compile(r"^Cylinder\d+$", re.IGNORECASE),   # Cylinder1, ...
  re.compile(r"^Rectangle\d+$", re.IGNORECASE),  # Rectangle1, ...
  re.compile(r"^Circle\d+$", re.IGNORECASE),    # Circle1, ...
  re.compile(r"^Polyline\d+$", re.IGNORECASE),   # Polyline1, ...
  re.compile(r"^Wire\d+$", re.IGNORECASE),     # Wire1, ...
  re.compile(r"^Face\d+$", re.IGNORECASE),     # Face1, ...
  re.compile(r"^FaceID\s*\d+$", re.IGNORECASE),  # FaceID 123, ...
  re.compile(r"^Object\d+$", re.IGNORECASE),    # Object1, ...
  re.compile(r"^Port\d+$", re.IGNORECASE),     # Port1, Port2, ...
  re.compile(r"^Vacuum\d+$", re.IGNORECASE),    # Vacuum1, ...
  re.compile(r"^PEC\d+$", re.IGNORECASE),     # PEC1, ...
  re.compile(r"^PerfectE_\d+$", re.IGNORECASE),  # PerfectE_1, ...
  re.compile(r"^Setup:\d+$", re.IGNORECASE),    # Setup:1, ...
  re.compile(r"^unnamed", re.IGNORECASE),      # unnamed*, ...
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
        f" - Substrate, GroundPlane, PatchMain\n"
        f" - FeedProbe, PortInput, AirBox\n"
        f" - 参见 hfss_builder_utils.py 中的命名常量",
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
  ...   center=(0, 0, 0),
  ...   size=(30, 24, 1.6),
  ...   params={"sub_length": 30, "sub_width": 24, "sub_height": 1.6},
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

  return tuple(center_exprs), tuple(size_exprs) # type: ignore[return-value]


# ─── B7 量纲安全构建器（#218 教训内核化，方案 B7）─────────────────────

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

  #218 三类字符串语义（归因存档 §二），
  本类一律拒绝、只接受显式单位数值：

  - 纯数字串（"1.113"）：HFSS 按**模型单位**补全，量纲随模型 units 漂移；
  - 字面算术表达式（"-2.5*1.113"）：HFSS 表达式引擎对无量纲算术按
   **SI 米**求值——#218 原案曾致端口 sheet 悬空域外 2.78m；
  - 含设计变量表达式（"2*W"）：量纲随变量定义，变量化建模应走
   set_variables 变量通道（变量带 mm 量纲），不进几何构建器。

  四工具序列化出口（四套单位约定 × 三类量纲）：
  - to_hfss()    → 长度 "2.7825mm" / 角度 "45deg" / 无量纲裸数 "0.5"
  - to_openems(unit) → 长度 unit 缩放浮点 / 角度 rad 浮点 / 无量纲比值
  - to_comsol()   → 长度 "2.7825[mm]" / 角度 "45[deg]" / 无量纲裸数
  - to_kicad()    → 长度 nm 整数 / 角度 1/10 度整数 / 无量纲 1e-6 定点整数

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
      return NotImplemented # 长度×长度等无物理定义
    return Quantity(self.value * float(scalar), self.dimension)

  def __rmul__(self, scalar: float | int | Quantity) -> Quantity:
    return self.__mul__(scalar)

  def __truediv__(self, other: Quantity | float | int) -> Quantity | float:
    if isinstance(other, Quantity):
      if other.value == 0:
        raise ZeroDivisionError("Quantity 除零")
      if other.dimension == self.dimension:
        return self.value / other.value # 同量纲 → 无量纲 float 比值
      if other.dimension == DIMENSIONLESS:
        return Quantity(self.value / other.value, self.dimension)
      raise ModelBuildError(
        f"量纲不匹配：{self.dimension!r} 不可除以 {other.dimension!r}",
        details={"left": self.dimension, "right": other.dimension},
      )
    return Quantity(self.value / float(other), self.dimension)
