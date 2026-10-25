"""stackup schema + 共形介质纯规划器 + 薄层朝向守卫（K9，aurora_k 战役）。

用户反馈（D:\\IPD调研\\调研产出\\设计实战\\HFSS_八角电感\\rfauto使用体验与反馈.md）：
- **P15**：本工艺几何全是 μm（衬底 200/金属 5/SiNx 0.2/指隙 8），rfauto 示例
  是 mm/GHz——recipe 顶层支持 ``units: um``，内部换算到 mm；
- **F10**：``stackup.yaml`` schema（层名/厚度/材料/εr/tanδ/是否图形化/
  共形/空气隙），厚度全部用 μm；
- **F2**：IPD 的钝化/层间介质（SiNx/PI/BCB）是**共形**的——金属上是 h1、
  场区是 h2，手工建非常痛苦（用户因没建对被当场指出"最上层金属下面没有
  介质"，还引发悬空膜/块重叠/柱穿介质 3 个 bug）；需要
  ``conformal_dielectric(metal_objects, t, material)``：沿金属足迹生成 t 厚层
  +过孔/凸点处自动开窗+同材料 unite 一体；
- **P7**：``h << w``（0.2 μm 介质 vs 15 μm 线宽）时薄层扫掠会把截面建成
  "竖墙"（15 μm 高、0.2 μm 宽），SNV 层变一圈介质墙、SRF 从 6.3 GHz 崩到
  0.95 GHz——sweep 类模板必须强制校验 bbox 薄轴厚度 == h。

本模块是**纯几何规划层**（K9 席面）：零引擎依赖（无 pyaedt/openEMS
import），HFSS builder 侧与 openEMS 模板侧都能 import（分层契约：core 被
adapters/service 双侧导入，故守卫与换算 helper 落 core 而非
hfss_builder_utils——adapters 内互导虽合法，但 oe_templates/模板族席与
HFSS 侧共用时 core 是唯一无歧义落点）。三件交付：

1. :class:`Stackup`/``StackLayer``——叠层纯数据模型（§6.4 形态收窄）+
   ``z_ranges()`` z 叠算 + YAML 装载 + :func:`to_mm`/``normalize_units``
   单位 helper（recipe ``units`` 字段，缺省 mm=现状零变化）；
2. :func:`plan_conformal_dielectric`——共形介质分层矩形清单规划器
   （**矩形近似**：不做真实保形覆盖弯月面，边界如实声明）；
3. :func:`assert_thin_layer`——薄层朝向守卫（P7 断言，供模板/sweep 调用）。

数值一律调用方单位（IPD 工艺典型 μm）；``to_mm`` 是渲染入口的显式换算
单源（模板接线归模板族席逐步迁移，本席只落 helper+schema 字段）。

出处：本模块为**本仓设计**（aurora_k K9 席面，零文献转写公式）——
  Stackup/StackLayer 的 z 叠算（z_ranges 逐层累加）、units 换算与
  共形介质矩形分层规划（plan_conformal_dielectric）按用户反馈
  P15/F10/F2/P7 的工艺需求设计（反馈原文见节首），几何规则可由
  模块内声明逐条推导复算；无经验系数、无拟合常数。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rfauto.core.errors import ConfigError, ModelBuildError

__all__ = [
    "RECIPE_UNITS",
    "ConformalPlanError",
    "LayerZRange",
    "StackLayer",
    "Stackup",
    "StackupError",
    "assert_thin_layer",
    "normalize_units",
    "plan_conformal_dielectric",
    "to_mm",
]


class StackupError(ConfigError):
    """stackup schema/装载/校验失败（配方域非法 → 直接拒绝，不消耗 license）。"""


# ─── units：recipe 顶层字段 + 渲染入口换算单源（P15）─────────────────────────

#: recipe 顶层 ``units`` 字段合法词汇：``mm``（缺省，现状零变化）| ``um``
#: （IPD 工艺）。μ 前缀变体按别名收进 um（与 hfss_builder_utils 的
#: ``_NET_UNIT_ALIASES`` 同源口径；分层契约无 import 关系，对齐由测试钉）。
_UNIT_ALIASES: dict[str, str] = {"mm": "mm", "um": "um", "μm": "um", "µm": "um"}

#: 规范单位 → mm 换算因子。
_UNIT_TO_MM: dict[str, float] = {"mm": 1.0, "um": 1e-3}

#: recipe 装载侧的校验词汇（K9 最小面：validate_recipe 消费）。
RECIPE_UNITS: tuple[str, ...] = ("mm", "um")


def normalize_units(units: Any) -> str:
    """recipe ``units`` 字段 → 规范词汇 ``"mm" | "um"``（未知即报错）。

    接受 μ 前缀变体（``μm``/``µm``）作 um 别名；非字符串/未知词汇抛
    :class:`StackupError`（ConfigError 家族——配方域拒绝）。
    """
    if not isinstance(units, str):
        raise StackupError(
            f"units 需为字符串 {'|'.join(RECIPE_UNITS)}，实际类型 "
            f"{type(units).__name__}: {units!r}",
            details={"units": repr(units)[:100]},
        )
    canonical = _UNIT_ALIASES.get(units.strip())
    if canonical is None:
        raise StackupError(
            f"不支持的 units {units!r}（收 {'|'.join(RECIPE_UNITS)}；μ 前缀"
            "变体按 um 别名）",
            details={"units": units},
        )
    return canonical


def to_mm(value: float, units: Any) -> float:
    """几何值按 recipe ``units`` 换算为 mm（渲染入口唯一换算 helper，P15）。

    本席只落 helper——各模板（oe_templates/render_*、HFSS builder）接线归
    模板族席逐步迁移；当前模板参数单位语义不变（缺省 mm 零变化）。
    """
    if not _is_num(value):
        raise StackupError(
            f"to_mm: 数值非法（需 int/float，YAML 裸数字约定），实际 "
            f"{type(value).__name__}: {value!r}",
            details={"value": repr(value)[:100]},
        )
    v = float(value)
    if not math.isfinite(v):
        raise StackupError(
            f"to_mm: 数值必须有限，实际 {v!r}",
            details={"value": v},
        )
    return v * _UNIT_TO_MM[normalize_units(units)]


# ─── stackup schema（F10：层名/厚度/材料/εr/tanδ/共形/图形化/空气隙）─────────


@dataclass(frozen=True)
class StackLayer:
    """叠层中的一层（厚度一律 μm——P15：IPD 工艺口径）。

    字段语义（反馈 §6.4 形态收窄；YAML 键别名见 :meth:`Stackup.from_dict`）：

    - ``name``：层名（叠层内唯一；衬底名缺省 ``"substrate"``）；
    - ``thickness_um``：层厚 μm（>0）；**共形层占位口径：厚度计线从金属面
      起**——即 z 叠算里共形层与常规层一样占 ``[z, z+t]`` 槽位（t 从下方
      金属顶面量起）；共形层在场区的介质实际坐在槽底（金属底面起）——
      那是 :func:`plan_conformal_dielectric` 的职责（给 metal_thickness
      与 z_top_of_metal 即得场区 z 带）；
    - ``material``：材料名（导体如 ``Cu/Au`` 或介质如 ``SiNx``）；
    - ``er``：相对介电常数（介质层必给、>0；导体层可省 None）；
    - ``tand``：损耗角正切（≥0，可省）；
    - ``conformal``：是否共形层（金属上 h1/场区 h2 的钝化/层间介质族）；
    - ``patterned``：是否图形化层（光刻定义的金属/再布线层——共形规划器
      用它找下方金属厚度；衬底与匀布介质层为 False）；
    - ``air_gap_um``：本层下方预留的空气隙 μm（≥0；悬浮空桥族如 ABM 下
      的 3.0 μm gap——z 叠算先铺 gap 再铺层）。
    """

    name: str
    thickness_um: float
    material: str
    er: float | None = None
    tand: float | None = None
    conformal: bool = False
    patterned: bool = False
    air_gap_um: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise StackupError(f"层名需非空字符串，实际 {self.name!r}")
        if not isinstance(self.material, str) or not self.material.strip():
            raise StackupError(f"层 {self.name}: material 需非空字符串，实际 {self.material!r}")
        _num_field(self, "thickness_um", positive=True)
        _num_field(self, "air_gap_um", positive=False)
        if self.er is not None and not (_is_num(self.er) and float(self.er) > 0.0):
            raise StackupError(
                f"层 {self.name}: er 需 >0（介质层必给；导体层省略），实际 {self.er!r}")
        if self.tand is not None and not (_is_num(self.tand) and float(self.tand) >= 0.0):
            raise StackupError(
                f"层 {self.name}: tand 需 ≥0，实际 {self.tand!r}")
        if not isinstance(self.conformal, bool) or not isinstance(self.patterned, bool):
            raise StackupError(
                f"层 {self.name}: conformal/patterned 需布尔（YAML 裸 true/false），"
                f"实际 conformal={self.conformal!r} patterned={self.patterned!r}")


@dataclass(frozen=True)
class LayerZRange:
    """z 叠算记录：一层（或一段空气隙）的 z 占位区间（μm，衬底顶=0）。"""

    name: str
    z_lo: float
    z_hi: float
    material: str
    is_air_gap: bool = False
    conformal: bool = False
    patterned: bool = False

    @property
    def thickness(self) -> float:
        """z 跨度（μm）。"""
        return self.z_hi - self.z_lo

    def as_dict(self) -> dict[str, Any]:
        """dict 形态（UI/doctor 清单消费；字段省略风格与 Keepout.as_dict 一致）。"""
        d: dict[str, Any] = {
            "name": self.name,
            "z": [self.z_lo, self.z_hi],
            "material": self.material,
        }
        if self.is_air_gap:
            d["is_air_gap"] = True
        if self.conformal:
            d["conformal"] = True
        if self.patterned:
            d["patterned"] = True
        return d


def _is_num(v: Any) -> bool:
    """数值判定（bool 是 int 子类——显式排除，#175 教训：宽松强转是坑）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num_field(obj: Any, field_name: str, *, positive: bool) -> float:
    """dataclass 数值字段守卫：数值+有限+（positive 时 >0 否则 ≥0）。"""
    v = getattr(obj, field_name)
    where = f"层 {getattr(obj, 'name', type(obj).__name__)}: {field_name}"
    if not _is_num(v):
        raise StackupError(f"{where} 需数值（YAML 裸数字），实际 {v!r}")
    f = float(v)
    if not math.isfinite(f):
        raise StackupError(f"{where} 必须有限，实际 {f!r}")
    if positive and f <= 0.0:
        raise StackupError(f"{where} 需 >0，实际 {f!r}")
    if not positive and f < 0.0:
        raise StackupError(f"{where} 需 ≥0，实际 {f!r}")
    return f


@dataclass(frozen=True)
class Stackup:
    """叠层纯数据模型（衬底 + 层列表；z 原点=衬底顶，向上为正，μm 制）。

    z 叠算语义（:meth:`z_ranges`，F10）：

    - 衬底占 ``[-h_sub, 0]``，层从 0 起逐层上叠；
    - ``air_gap_um > 0`` 的层先铺一段空气隙记录（``<name>__airgap``，
      ``is_air_gap=True``）再铺层——z 账目连续无跳变；
    - **共形层占位口径**：与常规层同占 ``[z, z+t]`` 槽位（厚度计线从金属
      面起=下方图形化金属层的顶面）；共形层场区介质坐在金属底面起的低
      z 带（由 :func:`plan_conformal_dielectric` 按 metal_thickness 换算，
      本 schema 只声明占位）。

    装载：:meth:`from_dict`/:meth:`from_yaml` 收窄到反馈 §6.4 形态::

        substrate: {material: GaAs, thickness: 200, er: 12.85, tanD: 0.006}
        layers:
          - {name: SiNx1, thickness: 0.2, material: SiNx, er: 7.5}
          - {name: FM,    thickness: 5.0, material: Cu/Au, patterned: true}
          - {name: SNV,   thickness: 0.2, material: SiNx, er: 7.5, conformal: true}
          - {name: ABM,   thickness: 5.0, material: Cu/Au, air_gap: 3.0, patterned: true}

    键别名：``thickness``/``thickness_um``、``tanD``/``tand``/``tan_d``、
    ``air_gap``/``air_gap_um``；未知键拒绝（拼写错误当场暴露，不静默吞）。
    """

    substrate: StackLayer
    layers: tuple[StackLayer, ...] = ()

    def __post_init__(self) -> None:
        if self.substrate.name in {ly.name for ly in self.layers}:
            raise StackupError(
                f"层名 {self.substrate.name!r} 与衬底重名（叠层内名称唯一）")
        names = [ly.name for ly in self.layers]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise StackupError(f"层名重复: {sorted(dup)}（叠层内名称唯一）")

    # ── 装载 ─────────────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, data: Any) -> Stackup:
        """从映射装载（接受 stack 子映射本身，或含 ``stack:`` 键的 recipe 片段）。"""
        if not isinstance(data, dict):
            raise StackupError(
                f"stackup 需映射（substrate/layers），实际 {type(data).__name__}")
        if isinstance(data.get("stack"), dict) and len(data) > 0 and "substrate" not in data:
            data = data["stack"]  # recipe 片段形态 {"stack": {...}}（§6.4）
        if "substrate" not in data:
            raise StackupError("stackup 缺 'substrate' 键（§6.4 形态：substrate+layers）")
        sub = _layer_from_dict(data["substrate"], where="substrate")
        if sub.air_gap_um != 0.0:
            raise StackupError("substrate 不接受 air_gap（空气隙是层间语义）")
        raw_layers = data.get("layers", [])
        if not isinstance(raw_layers, list):
            raise StackupError(
                f"layers 需列表，实际 {type(raw_layers).__name__}")
        layers = tuple(
            _layer_from_dict(d, where=f"layers[{i}]") for i, d in enumerate(raw_layers))
        return cls(substrate=sub, layers=layers)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Stackup:
        """装载 stackup YAML 文件（``yaml.safe_load``；§6.4 形态收窄）。"""
        import yaml  # lazy: 装载面按需（core 不在 import 期背 yaml 依赖）

        p = Path(path)
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except OSError as exc:
            raise StackupError(f"stackup 文件不可读: {p}（{exc}）") from exc
        except yaml.YAMLError as exc:
            raise StackupError(f"stackup YAML 解析失败: {p}（{exc}）") from exc
        return cls.from_dict(data)

    # ── z 叠算与查询 ─────────────────────────────────────────────────────
    def z_ranges(self) -> tuple[LayerZRange, ...]:
        """从衬底起逐层叠 z 区间（衬底 ``[-h, 0]``，层从 0 上叠；μm）。

        顺序=衬底、layers 声明序；空气隙以独立记录插入（is_air_gap=True）。
        z 账目连续：每条记录 z_lo == 前条 z_hi（浮点精确相等——加法链同源）。
        """
        out: list[LayerZRange] = [
            LayerZRange(self.substrate.name, -float(self.substrate.thickness_um), 0.0,
                        self.substrate.material)]
        z = 0.0
        for ly in self.layers:
            if float(ly.air_gap_um) > 0.0:
                out.append(LayerZRange(f"{ly.name}__airgap", z,
                                       z + float(ly.air_gap_um), material="air",
                                       is_air_gap=True))
                z += float(ly.air_gap_um)
            out.append(LayerZRange(ly.name, z, z + float(ly.thickness_um), ly.material,
                                   conformal=ly.conformal, patterned=ly.patterned))
            z += float(ly.thickness_um)
        return tuple(out)

    def total_thickness_um(self) -> float:
        """衬底顶（z=0）到叠层顶的总厚 μm（含空气隙；不含衬底本厚）。"""
        return sum(float(ly.thickness_um) + float(ly.air_gap_um) for ly in self.layers)

    def layer_by_name(self, name: str) -> StackLayer:
        """按名取层（衬底也可查；未知名 → StackupError）。"""
        if name == self.substrate.name:
            return self.substrate
        for ly in self.layers:
            if ly.name == name:
                return ly
        raise StackupError(f"叠层无名为 {name!r} 的层（现有: "
                           f"{[self.substrate.name, *(ly.name for ly in self.layers)]}）")

    def nearest_metal_below(self, name: str) -> StackLayer | None:
        """named 层下方最近的图形化层（``patterned=True``；无则 None）。

        共形规划器的桥：conformal 层的场区 z 带 = 下方金属层底面起——由
        该金属的 thickness_um 给出 metal_thickness。衬底上方无金属时返回
        None（共形层坐在衬底顶，调用方按 metal_thickness=0 处理）。
        """
        self.layer_by_name(name)  # 未知名统一 StackupError（衬底合法→None）
        if name == self.substrate.name:
            return None
        idx = [ly.name for ly in self.layers].index(name)
        for ly in reversed(self.layers[:idx]):
            if ly.patterned:
                return ly
        return None


# 层字段 YAML 键别名（§6.4 原文键 → 规范字段名）
_LAYER_KEY_ALIASES: dict[str, str] = {
    "thickness": "thickness_um",
    "thickness_um": "thickness_um",
    "tanD": "tand",
    "tand": "tand",
    "tan_d": "tand",
    "air_gap": "air_gap_um",
    "air_gap_um": "air_gap_um",
}
_LAYER_FIELDS: frozenset[str] = frozenset({
    "name", "material", "er", "conformal", "patterned", *_LAYER_KEY_ALIASES})


def _layer_from_dict(d: Any, *, where: str) -> StackLayer:
    """映射 → StackLayer（键别名收窄+未知键拒绝+严格类型）。"""
    if not isinstance(d, dict):
        raise StackupError(f"{where}: 需映射，实际 {type(d).__name__}")
    canon: dict[str, Any] = {}
    for k, v in d.items():
        ck = _LAYER_KEY_ALIASES.get(str(k), str(k))
        if ck not in _LAYER_FIELDS:
            raise StackupError(
                f"{where}: 未知键 {k!r}（收 {sorted(_LAYER_FIELDS)}；"
                f"别名 {sorted(_LAYER_KEY_ALIASES)}）")
        if ck in canon:
            raise StackupError(f"{where}: 键 {k!r} 与别名重复给同一字段 {ck!r}")
        canon[ck] = v
    if "name" not in canon and where != "substrate":
        raise StackupError(f"{where}: 缺 'name' 键")
    if "material" not in canon:
        raise StackupError(f"{where}: 缺 'material' 键")
    if "thickness_um" not in canon:
        raise StackupError(f"{where}: 缺 'thickness' 键")
    name = str(canon.get("name", "substrate"))
    kwargs: dict[str, Any] = {
        "name": name,
        "material": canon["material"],
        "thickness_um": canon["thickness_um"],
    }
    for f in ("er", "tand", "conformal", "patterned", "air_gap_um"):
        if f in canon:
            kwargs[f] = canon[f]
    try:
        return StackLayer(**kwargs)
    except StackupError as exc:
        raise StackupError(f"{where}: {exc}") from exc


# ─── 薄层朝向守卫（P7：h << w 时扫掠截面会建反成"竖墙"）─────────────────────


def assert_thin_layer(
    measured_span: float,
    declared_h: float,
    *,
    axis: str = "z",
    rel_tol: float = 0.01,
) -> dict[str, Any]:
    """P7 断言：建出的薄层 bbox 沿薄轴跨度必须 == 声明厚度（不符即报错）。

    用户实测病灶（反馈 §一 P7 + §6.1 P15）：``create_polyline(
    xsection_type="Rectangle", xsection_width=15, xsection_height=0.2)`` 在
    h << w 时截面建成"竖墙"（15 μm 高、0.2 μm 宽），SNV 层变一圈介质墙、
    SRF 从 6.3 GHz 崩到 0.95 GHz——本守卫把用户手工加的断言
    （build_models.py::sweep）进层：模板/sweep 建完薄层几何后**必须**调本
    函数校验，不符 fail-fast（不带病求解）。

    Parameters
    ----------
    measured_span : float
        实建对象 bbox 沿薄轴的跨度（调用方单位；典型从 bounding_box 取）。
    declared_h : float
        声明的薄层厚度（>0；如 SiNx 0.2 μm）。
    axis : str
        薄轴名（x|y|z，缺省 z——层厚的法向；进错误证据）。
    rel_tol : float
        相对容差（缺省 1%——0.2 μm 层容 ±2 nm 落格噪声）。

    Returns
    -------
    dict
        证据 ``{"ok", "axis", "measured", "declared", "abs_err", "rel_err",
        "rel_tol"}``（守卫通过时返回；违反即抛 ModelBuildError 不返回）。

    Raises
    ------
    ModelBuildError
        跨度不符（典型=截面 w/h 建反的"竖墙"：measured≈线宽、declared≈层厚）
        或入参非法（非有限/declared_h≤0/axis 词汇外）。
    """
    if axis not in ("x", "y", "z"):
        raise ModelBuildError(
            f"assert_thin_layer: axis 需 x|y|z，实际 {axis!r}",
            details={"axis": str(axis)})
    if not _is_num(measured_span) or not _is_num(declared_h):
        raise ModelBuildError(
            "assert_thin_layer: measured_span/declared_h 需数值，实际 "
            f"measured={measured_span!r} declared={declared_h!r}",
            details={"measured": repr(measured_span), "declared": repr(declared_h)})
    m, h = float(measured_span), float(declared_h)
    if not (math.isfinite(m) and math.isfinite(h)):
        raise ModelBuildError(
            f"assert_thin_layer: 数值必须有限，实际 measured={m!r} declared={h!r}",
            details={"measured": m, "declared": h})
    if h <= 0.0:
        raise ModelBuildError(
            f"assert_thin_layer: declared_h 需 >0（薄层厚度本身），实际 {h!r}",
            details={"declared": h})
    if rel_tol < 0.0:
        raise ModelBuildError(
            f"assert_thin_layer: rel_tol 需 ≥0，实际 {rel_tol!r}",
            details={"rel_tol": rel_tol})
    abs_err = abs(m - h)
    rel_err = abs_err / h
    if abs_err > rel_tol * h:
        ratio = m / h if h else float("inf")
        raise ModelBuildError(
            f"薄层朝向守卫失败（P7）：bbox 沿 {axis} 轴实测跨度 {m:g} ≠ 声明厚度"
            f" {h:g}（|Δ|={abs_err:g} > 容差 {rel_tol * h:g}，rel={rel_err:.3g}）——"
            "典型根因=薄层扫掠截面 w/h 建反成'竖墙'（0.2 μm SiNx vs 15 μm 线宽"
            f"实测 15 高/0.2 宽，SRF 从 6.3 GHz 崩到 0.95 GHz；实测/声明比"
            f" {ratio:.4g}），请换扫掠截面朝向或修截面宽高序后再校验",
            details={
                "axis": axis, "measured": m, "declared": h,
                "abs_err": abs_err, "rel_err": rel_err, "rel_tol": rel_tol,
                "measured_over_declared": ratio,
            })
    return {
        "ok": True, "axis": axis, "measured": m, "declared": h,
        "abs_err": abs_err, "rel_err": rel_err, "rel_tol": rel_tol,
    }


# ─── conformal_dielectric 纯规划器（F2：金属上 h1/场区 h2 的分层矩形清单）────


class ConformalPlanError(ValueError):
    """conformal 介质规划失败：输入几何非法或自检违规（fail-fast 不带病建模）。

    继承 ValueError（K7 WavePortPlanError 同款契约：纯规划层错误带人话
    证据+可编程 details，供建模脚本捕获）。
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


#: 矩形=4 数 [x0, y0, x1, y1]（调用方单位；IPD 工艺典型 μm）。
Rect = tuple[float, float, float, float]


def _norm_rect(value: Any, where: str) -> Rect:
    """4 数 → 规范矩形（min/max 归一；两轴跨度必须严格 >0）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ConformalPlanError(
            f"{where}: 需 4 数矩形 [x0,y0,x1,y1]，实际 {value!r}",
            details={"where": where, "value": repr(value)[:200]})
    nums: list[float] = []
    for v in value:
        if not _is_num(v) or not math.isfinite(float(v)):
            raise ConformalPlanError(
                f"{where}: 矩形含非有限数值 {v!r}",
                details={"where": where, "value": repr(value)[:200]})
        nums.append(float(v))
    x0, y0 = min(nums[0], nums[2]), min(nums[1], nums[3])
    x1, y1 = max(nums[0], nums[2]), max(nums[1], nums[3])
    if x1 <= x0 or y1 <= y0:
        raise ConformalPlanError(
            f"{where}: 矩形退化（两轴跨度需 >0），实际 [{x0:g},{y0:g},{x1:g},{y1:g}]",
            details={"where": where, "rect": [x0, y0, x1, y1]})
    return (x0, y0, x1, y1)


def _grow(r: Rect, g: float) -> Rect:
    """矩形四向外扩 g（lateral_growth 侧壁包覆近似）。"""
    return (r[0] - g, r[1] - g, r[2] + g, r[3] + g)


def _area(r: Rect) -> float:
    return (r[2] - r[0]) * (r[3] - r[1])


def _overlap_xy(a: Rect, b: Rect) -> float:
    """两轴同时正交叠的面积（贴边=0）。"""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    if dx > 0.0 and dy > 0.0:
        return dx * dy
    return 0.0


def _rect_subtract(a: Rect, b: Rect) -> list[Rect]:
    """a ⊖ b → 矩形清单（最多 4 条；贴边不产零宽条——严格不等号）。"""
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix0 >= ix1 or iy0 >= iy1:
        return [a]  # 无交
    out: list[Rect] = []
    if a[0] < ix0:
        out.append((a[0], a[1], ix0, a[3]))
    if ix1 < a[2]:
        out.append((ix1, a[1], a[2], a[3]))
    if a[1] < iy0:
        out.append((ix0, a[1], ix1, iy0))
    if iy1 < a[3]:
        out.append((ix0, iy1, ix1, a[3]))
    return out


def _subtract_many(base: Sequence[Rect], cuts: Sequence[Rect]) -> list[Rect]:
    """矩形集 ⊖ 切割矩形集（逐块迭代裁剪；结果互不重叠）。"""
    rects = list(base)
    for cut in cuts:
        nxt: list[Rect] = []
        for r in rects:
            nxt.extend(_rect_subtract(r, cut))
        rects = nxt
    return rects


def plan_conformal_dielectric(
    metal_footprints: Sequence[Sequence[float]],
    *,
    thickness: float,
    metal_thickness: float,
    z_top_of_metal: float,
    windows: Sequence[Sequence[float]] = (),
    lateral_growth: float = 0.0,
) -> dict[str, Any]:
    """共形介质层的**分层矩形清单**规划器（F2；纯数值零引擎依赖）。

    输入金属足迹矩形清单（调用方单位，典型 μm），输出可直接建体的分段
    矩形（每段一个 z 带 + 一个 xy 矩形；**段间保证零重叠**——调用方同
    材料 unite 一体不会报 intersect，正是用户 3 个 bug 之一的治法）：

    - **金属正上方段**（``over_metal``）：每足迹一块，z ∈
      ``[z_top_of_metal, z_top_of_metal + thickness]``，xy=足迹外扩
      ``lateral_growth``（侧壁包覆的保守近似）；
    - **场区段**（``field``）：足迹间空隙的桥接块，z ∈ ``[z_top_of_metal
      - metal_thickness, ... + thickness]``（共形层在场区坐在**金属底面**
      起——金属上 h1/场区 h2 的 F2 原语义）；xy=足迹外包络 ⊖ 外扩足迹
      （简化版：空隙矩形并在同 z 带）；
    - **开窗扣除**（``windows``）：过孔/凸点处自动开窗——每个窗口矩形从
      **全部段**（over_metal 与 field）扣差集（通孔贯穿整个介质带）。

    **矩形近似共形边界（如实声明）**：不做真实保形覆盖弯月面（sidewall
    爬坡/拐角减薄不在模型内）——侧壁区以 ``lateral_growth`` 矩形外扩近
    似，**该值由用户按工艺给**（典型 = 层厚的 30–100%）；外扩导致足迹
    相交时 fail-fast（要么减小 growth 要么先合并金属）。

    自检（三件，违反即 :class:`ConformalPlanError`，返回的 plan 恒已认证）：
    ① 段间零重叠（3D bbox 两两无正交叠）；② 总厚度核算（每段 z 跨度 ==
    thickness）；③ 面积核算（全段 xy 面积和 == 外包络 ⊖ 窗口 的面积）。

    Parameters
    ----------
    metal_footprints : 序列，元素 4 数矩形 [x0,y0,x1,y1]（金属层 xy 足迹）。
    thickness : 介质层厚 t（>0）。
    metal_thickness : 下方金属层厚（≥0；field z 带的基准=金属底面。
        0=金属为零厚 sheet，field 带与 over 带同基）。
    z_top_of_metal : 金属顶面 z。
    windows : 开窗矩形清单（过孔/凸点外接框；贯穿整个介质带）。
    lateral_growth : 侧壁包覆近似外扩量（≥0，工艺参数，用户按工艺给）。

    Returns
    -------
    dict
        ``{"kind": "conformal_dielectric_plan", "thickness",
        "metal_thickness", "z_top_of_metal", "lateral_growth",
        "z_bands": {"over_metal": [z0,z1], "field": [z0,z1]}, "envelope",
        "segments": [{name, kind, rect, z}], "n_over_metal", "n_field",
        "windows", "self_check", "approximation", "warnings"}``——段名
        ``over_metal_NN``/``field_NN`` 建议调用方加层名前缀
        （如 ``f"SNV_{seg['name']}"``，军规 2b 语义化命名）。

    Raises
    ------
    ConformalPlanError
        输入非法（退化矩形/thickness≤0/足迹空清单/外扩后足迹相交）或
        自检违规（段重叠/厚度/面积核算不过——构造性恒过，防御性保留）。
    """
    # ── 入参守卫 ────────────────────────────────────────────────────────
    for label, v, lo in (("thickness", thickness, "gt0"),
                         ("metal_thickness", metal_thickness, "ge0"),
                         ("z_top_of_metal", z_top_of_metal, "finite"),
                         ("lateral_growth", lateral_growth, "ge0")):
        if not _is_num(v) or not math.isfinite(float(v)):
            raise ConformalPlanError(
                f"{label} 需有限数值，实际 {v!r}", details={"field": label})
        f = float(v)
        if (lo == "gt0" and f <= 0.0) or (lo == "ge0" and f < 0.0):
            raise ConformalPlanError(
                f"{label} 需 {'>0' if lo == 'gt0' else '≥0'}，实际 {f!r}",
                details={"field": label, "value": f})
    t = float(thickness)
    mt = float(metal_thickness)
    zt = float(z_top_of_metal)
    g = float(lateral_growth)

    foots = [ _norm_rect(r, f"metal_footprints[{i}]")
              for i, r in enumerate(metal_footprints or []) ]
    if not foots:
        raise ConformalPlanError(
            "metal_footprints 至少一个金属足迹（空足迹=无共形层可言）",
            details={"n_footprints": 0})
    wins = [ _norm_rect(w, f"windows[{i}]")
             for i, w in enumerate(windows or []) ]

    grown = [_grow(r, g) for r in foots]
    # 足迹相交守卫（原始相交=输入错；外扩致交=growth 超间隙——都 fail-fast）
    for i in range(len(grown)):
        for j in range(i + 1, len(grown)):
            if _overlap_xy(grown[i], grown[j]) > 0.0:
                cause = ("原始足迹已相交" if _overlap_xy(foots[i], foots[j]) > 0.0
                         else f"lateral_growth={g:g} 外扩后相交（间隙不足 2×growth）")
                raise ConformalPlanError(
                    f"金属足迹[{i}]×[{j}] {cause}——共形段会重叠：减小 "
                    f"lateral_growth 或先合并金属足迹",
                    details={"i": i, "j": j, "lateral_growth": g,
                             "rect_i": list(grown[i]), "rect_j": list(grown[j])})

    env: Rect = (min(r[0] for r in grown), min(r[1] for r in grown),
                 max(r[2] for r in grown), max(r[3] for r in grown))
    z_over = (zt, zt + t)
    z_field = (zt - mt, zt - mt + t)

    # ── 分段（先 over_metal/field 两带，再统一开窗）──────────────────────
    segs: list[dict[str, Any]] = [
        {"kind": "over_metal", "rect": r, "z": z_over} for r in grown]
    for r in _subtract_many([env], grown):
        segs.append({"kind": "field", "rect": r, "z": z_field})

    n_full_window = 0
    if wins:
        kept: list[dict[str, Any]] = []
        for s in segs:
            pieces = _subtract_many([s["rect"]], wins)
            if not pieces and s["kind"] == "over_metal":
                n_full_window += 1  # 窗口整吞一段（过孔整压足迹——合法形态）
            for r in pieces:
                kept.append({"kind": s["kind"], "rect": r, "z": s["z"]})
        segs = kept

    # ── 命名（over_metal_NN / field_NN，按带内构造序）────────────────────
    counters = {"over_metal": 0, "field": 0}
    for s in segs:
        s["name"] = f"{s['kind']}_{counters[s['kind']]:02d}"
        counters[s["kind"]] += 1
        s["rect"] = list(s["rect"])
        s["z"] = list(s["z"])

    # ── 自检三件（构造性恒过；防御性保留——规划器改动时的安全网）────────
    span = max(env[2] - env[0], env[3] - env[1])
    eps = 1e-9 * max(1.0, span)  # 长度容差（落格噪声级）
    violations: list[str] = []
    for s in segs:
        z0, z1 = s["z"]
        if abs((z1 - z0) - t) > 1e-9 * max(1.0, abs(t), abs(z0), abs(z1)):
            violations.append(f"段 {s['name']} z 跨度 {z1 - z0:g} ≠ thickness {t:g}")
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            a, b = segs[i], segs[j]
            dz = min(a["z"][1], b["z"][1]) - max(a["z"][0], b["z"][0])
            if dz > eps and _overlap_xy(a["rect"], b["rect"]) > eps * eps:
                violations.append(
                    f"段 {a['name']}×{b['name']} 3D 重叠（z 交 {dz:g}）")
    expected = _subtract_many([env], wins)
    area_expected = sum(_area(r) for r in expected)
    area_got = sum(_area(s["rect"]) for s in segs)
    if abs(area_got - area_expected) > 1e-6 * max(1.0, area_expected):
        violations.append(
            f"面积核算不符：段面积和 {area_got:g} ≠ 外包络⊖窗口 {area_expected:g}")
    if violations:
        raise ConformalPlanError(
            f"conformal 介质规划自检违规（{len(violations)} 条）："
            + "；".join(violations),
            details={"violations": violations})

    warnings: list[str] = []
    if g > 0.0:
        warnings.append(
            f"lateral_growth={g:g} 为矩形外扩近似（侧壁弯月面不在模型内，"
            "F2 边界如实声明）——值由用户按工艺给，过大会触发足迹相交守卫")
    if n_full_window:
        warnings.append(
            f"{n_full_window} 个金属正上方段被窗口整吞（过孔/凸点整压足迹，"
            "开窗语义合法；unite 时只剩场区段）")
    if mt == 0.0:
        warnings.append(
            "metal_thickness=0（零厚金属 sheet）：场区段与金属正上方段同 z 基")

    return {
        "kind": "conformal_dielectric_plan",
        "thickness": t,
        "metal_thickness": mt,
        "z_top_of_metal": zt,
        "lateral_growth": g,
        "z_bands": {"over_metal": list(z_over), "field": list(z_field)},
        "envelope": list(env),
        "segments": segs,
        "n_over_metal": counters["over_metal"],
        "n_field": counters["field"],
        "windows": [list(w) for w in wins],
        "self_check": {
            "ok": True,
            "checks": {"zero_overlap": True, "thickness": True, "area": True},
            "area_segments": area_got,
            "area_expected": area_expected,
            "n_segments": len(segs),
        },
        "approximation": {
            "model": "rectangular_conformal",
            "notes": [
                "矩形近似共形：不做真实保形覆盖弯月面（侧壁爬坡/拐角减薄不在模型内）",
                f"侧壁区以 lateral_growth={g:g} 矩形外扩近似，由用户按工艺给",
                "段间零重叠保证：同材料 unite 一体不报 intersect（F2 悬空膜/"
                "块重叠/柱穿介质三 bug 的建反面）",
            ],
        },
        "warnings": warnings,
    }
