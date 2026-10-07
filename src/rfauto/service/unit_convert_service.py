"""quantity↔pint 换算通道服务面（ge8c 席C7 quantity pint 消费链件）。

定位（任务书口径）：units extras（pyproject ``units = ["pint>=0.24"]``）已
声明、core/quantity 的 :func:`to_pint` / :func:`from_pint` 惰性桥已在——
本模块落地**至少一条真实消费链**：闭式计算器出口（core/synthesis
Hammerstad-Jensen 微带正向，仓内线宽精算单源）→ typed
:class:`~rfauto.core.quantity.Quantity` → pint 换算通道 → 服务层 JSON
信封（规则 4）。

职责边界（零语义新增）：

- **数值只由确定性内核产出**（铁律 7）：Z0/εeff 全部来自
  ``core/synthesis.forward_z0`` 现算，本模块零物理数字；pint 只做
  **单位换算**（量纲一致的线性缩放），不产生新物理量；
- 量纲严守卫仍以 core/quantity 单源（parse_quantity + check_dimension），
  pint 侧只收 SI 出口（:data:`PINT_SI_UNITS`）——桥只是换能器；
- pint 未安装=能力不适用（非失败）：:func:`convert_quantity` 如实落
  ``skipped`` 信封（reason 带安装面），内核单位表/量纲守卫不受影响
  （core/quantity 零 pint 依赖自洽维持）；
- pint 换算目标单位不受 UNIT_TABLE 限制（pint 注册表远大于仓内表，
  thou→mm 类工程换算正是本通道价值），但**回读**仍走
  UNIT_TABLE fail-closed（``in_unit_table`` 键如实透出）。

判据预声明（#118 双独立基准）：

1. 精确换算锚：1 thou = 25.4 µm（国际码制定义，精确；pint 目标单位名
   ``thou``——``mil`` 在 pint 是另一无量纲角单位，不可用）——
   ``1 mm → thou`` 幅值 = 1000/25.4（浮点逐位）；
2. 恒等式锚：λg·f·√εeff = c0（导波波长定义式，εeff 取同一
   forward_z0 出口）——合成回收相对误差 ≤1e-12；
3. 错量纲拒收：frequency → length 换算 pint DimensionalityError →
   error 信封（不静默近似）。

接口纪律：dict/JSON 进出；零网络零 LLM 零随机；pint 缺席降级如实。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.quantity import (
    UNIT_TABLE,
    check_dimension,
    parse_quantity,
)
from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

#: 换算通道契约版本。
UNIT_CONVERT_SCHEMA = "rfauto-unit-convert-v1"

#: 真空光速（mm·GHz 实用制，repo synthesis 同值；λg 恒等式锚用 SI 制）。
_C0_MM_GHZ = 299.792458


def convert_quantity(value_unit: dict[str, Any], target_unit: str) -> dict[str, Any]:
    """quantity 二元组 → pint 换算到 target_unit（服务层 JSON 信封）。

    - value_unit：``{"value": <有限实数>, "unit": <UNIT_TABLE 单位>}``
      （core/quantity.parse_quantity fail-closed 守卫）；
    - target_unit：pint 单位串（注册表全集，如 ``thou``/``MHz``/``kohm``）；
    - 量纲不匹配 → pint DimensionalityError → ``ok=False, errors=[...]``；
    - pint 未安装 → ``ok=True, skipped=True, reason=安装面``（能力不适用
      如实声明，skipped≠failed）。

    Returns:
        ok 信封字段：``schema / from / to{magnitude,unit} /
        in_unit_table``（pint 渲染单位串是否在仓内 UNIT_TABLE——回读面
        from_pint 只收表内单位，表外如实 False 不做静默近似）。
    """
    if not isinstance(target_unit, str) or not target_unit.strip():
        return error_envelope("target_unit 必须为非空字符串",
                              schema=UNIT_CONVERT_SCHEMA)
    try:
        q = parse_quantity(value_unit)
    except ValueError as exc:
        return error_envelope(str(exc), schema=UNIT_CONVERT_SCHEMA)
    import importlib.util

    if importlib.util.find_spec("pint") is None:  # 可用性探针（零副作用）
        return skipped_envelope(
                   "pint 未安装——换算通道需要可选依赖：pip install rfauto[units]",
                   **{
                   "schema": UNIT_CONVERT_SCHEMA,
                   **{"from": _quantity_view(q)},
                   },
               )
    from rfauto.core.quantity import to_pint  # 惰性桥（内核零 pint 依赖）

    pq = to_pint(q)
    try:
        converted = pq.to(target_unit)
    except Exception as exc:  # pint.DimensionalityError/UndefinedUnitError
        return error_envelope(
                   f"pint 换算失败（{type(exc).__name__}）：{exc}",
                   **{
                   "schema": UNIT_CONVERT_SCHEMA,
                   **{"from": _quantity_view(q),
                                           "target_unit": target_unit},
                   },
               )
    magnitude = float(converted.magnitude)
    unit_str = f"{converted.units:~}"
    return ok_envelope(
               **{
               "schema": UNIT_CONVERT_SCHEMA,
               **{"from": _quantity_view(q),
           "to": {"magnitude": magnitude, "unit": unit_str},
           "in_unit_table": unit_str in UNIT_TABLE},
               },
           )


def mline_exit_quantities(w_mm: float, f0_ghz: float, er: float,
                          h_mm: float) -> dict[str, Any]:
    """闭式计算器出口 → typed 量化视图 + pint 换算通道（真实消费链）。

    计算器 = ``core/synthesis.forward_z0``（HJ 微带正向，仓内线宽精算
    单源）——Z0[Ω] 与 εeff 出口原样透传；导波波长 λg[m] 由同一 εeff
    按定义式 λg = c0/(f·√εeff) 现算。出口量经 :func:`convert_quantity`
    通道给出 ohm→kohm / m→thou（1 thou=25.4 µm）的 pint 换算视图
    （pint 缺席时视图=skipped 节，主出口数值不受影响）。

    Returns:
        ok 信封：``schema / z0_ohm / eps_eff / lambda_g_m``（各含
        value/unit/si_value/dimension）+ ``views{z0_kohm, lambda_g_thou}``
        （pint 换算视图或 skipped 节）。
    """
    import math

    from rfauto.core.synthesis import Stackup, forward_z0

    media = forward_z0(float(w_mm), float(f0_ghz),
                       Stackup("unit-convert", float(er), float(h_mm)))
    z0_ohm, eps_eff = float(media[0]), float(media[1])
    lambda_g_m = _C0_MM_GHZ / (float(f0_ghz) * math.sqrt(eps_eff)) * 1e-3
    z0_q = parse_quantity({"value": z0_ohm, "unit": "ohm"})
    lg_q = parse_quantity({"value": lambda_g_m, "unit": "m"})
    return ok_envelope(
        schema=UNIT_CONVERT_SCHEMA,
        calculator="core/synthesis.forward_z0（HJ 微带正向，仓内精算单源）",
        z0_ohm=_quantity_view(z0_q),
        eps_eff=eps_eff,
        lambda_g_m=_quantity_view(lg_q),
        views={
            "z0_kohm": convert_quantity(
                {"value": z0_ohm, "unit": "ohm"}, "kohm"),
            "lambda_g_thou": convert_quantity(
                {"value": lambda_g_m, "unit": "m"}, "thou"),
        },
    )


def convert_quantity_checked(value_unit: dict[str, Any], target_unit: str,
                             dimension: str) -> dict[str, Any]:
    """带仓内量纲预检的换算（守卫语义演示面：错量纲在仓内先拒）。

    与 :func:`convert_quantity` 差异：换算前先以
    ``core.quantity.check_dimension`` 对声明量纲校验（quantity 参数
    声明口径）——错量纲报 QuantityDimensionError 文案（含
    expected/got），不再落到 pint 侧异常。
    """
    try:
        q = parse_quantity(value_unit)
        check_dimension(q, dimension)
    except ValueError as exc:
        return error_envelope(str(exc), schema=UNIT_CONVERT_SCHEMA)
    return convert_quantity(value_unit, target_unit)


def _quantity_view(q: Any) -> dict[str, Any]:
    """Quantity → JSON 视图（原值/原单位/SI 值/量纲名保真）。"""
    return {"value": q.value, "unit": q.unit, "si_value": q.si_value,
            "dimension": q.dimension_name}
