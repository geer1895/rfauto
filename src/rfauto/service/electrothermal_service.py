"""电-热链 service 编排（HFSS→Icepak）。

JSON 进出薄编排：把 core/electrothermal 的确定性内核串成首案例链路

  Wilkinson 隔离电阻损耗 → 热路温升（闭式 R_th 或外部温度场结果）
  → 材料温漂（TCDk/CTE 一阶闭式）→ S 参数失谐 + 带内判据

只做确定性算术与参数校验：无 LLM、无网络；Icepak 真机温度由
adapters/icepak_adapter.IcepakAdapter.solve() 产出后，把
{"t_blk_c": ...} 作为 thermal.t_hot_c 注入本服务（真机面与编排面解耦）。

输入 payload 形状（未知字段/缺字段显式报错，ok=False 不抛异常）::

  {
   "case": {
    "scenario": "isolation_injection" | "combiner_imbalance"
         | "divider_through" | "waves",
    # isolation_injection: injected_power_w
    # divider_through:  input_power_w
    # combiner_imbalance: p2_w, p3_w, phase_diff_deg
    # waves:       p2_w, p3_w, phase_diff_deg（同上，语义别名）
   },
   "thermal": {
    "ambient_c": 25.0,      # 二选一：闭式热阻
    "r_th_k_per_w": 20.0,
    # 或直接注入温度（Icepak 真机/实测）：
    "t_hot_c": 61.3
   },
   "material": {"t_ref_c": 25.0, "cte_ppm_per_k": 14.0,
          "tcdk_ppm_per_k": 50.0},
   "resonator": {"f0_hz": 2.4e9},
   "band": {"low_hz": 2.3e9, "high_hz": 2.5e9}  # 可选
  }

输出::

  {"ok": true, "chain": {"power": ..., "thermal": ..., "drift": ...,
              "band": ... | null}}
非法输入/缺字段：{"ok": false, "error": "..."}（确定性、可序列化）。

WP4.4a 深化（③ 双向温漂定点）另有两枚薄函数（同为 JSON 进出，零网络）：
- ``derive_r_th_from_field``：Icepak 场解 {t_hot_c, power_w, ambient_c}
 → 有效热阻 R_th = ΔT/P（负温升/非正功率显式报错）；
- ``run_electrothermal_fixed_point``：material + config + thermal（闭式
 R_th 或场解推导二选一）→ core/thermal_iteration.solve_thermal_fixed_point
 （em/loss 评估器仅 keyword 注入供离线 fake 测试，None=core 微带解析链）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from rfauto.core.electrothermal import (
  band_guard,
  combiner_imbalance_case,
  divider_through_case,
  isolation_injection_case,
  thermal_detune,
)
from rfauto.core.thermal_iteration import (
  MaterialTemperatureModel,
  ThermalIterationConfig,
  solve_thermal_fixed_point,
)

_SCENARIOS = (
  "isolation_injection", "combiner_imbalance", "divider_through", "waves",
)


def _as_mapping(value: Any, where: str) -> Mapping[str, Any]:
  if not isinstance(value, Mapping):
    raise ValueError(f"{where} 必须是对象（dict）")
  return value


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
  unknown = sorted(set(data) - allowed)
  if unknown:
    raise ValueError(f"{where} 含未知字段: {unknown}")


def _require_key(data: Mapping[str, Any], key: str, where: str) -> Any:
  if key not in data:
    raise ValueError(f"{where} 缺少字段 {key!r}")
  return data[key]


def _finite(value: Any, name: str) -> float:
  try:
    out = float(value)
  except (TypeError, ValueError) as exc:
    raise ValueError(f"{name} 必须是实数，收到 {value!r}") from exc
  if not math.isfinite(out):
    raise ValueError(f"{name} 必须是有限数，收到 {value!r}")
  return out


def _resolve_power(case: Mapping[str, Any]) -> dict[str, Any]:
  """按 scenario 解析隔离电阻损耗工况（core 内核产出，含守恒自检）。"""
  scenario = str(_require_key(case, "scenario", "case"))
  if scenario not in _SCENARIOS:
    raise ValueError(f"scenario 必须是 {_SCENARIOS}，收到 {scenario!r}")
  if scenario == "isolation_injection":
    return isolation_injection_case(
      float(_require_key(case, "injected_power_w", "case")))
  if scenario == "divider_through":
    return divider_through_case(float(_require_key(case, "input_power_w", "case")))
  # combiner_imbalance / waves
  return combiner_imbalance_case(
    float(_require_key(case, "p2_w", "case")),
    float(_require_key(case, "p3_w", "case")),
    float(_require_key(case, "phase_diff_deg", "case")))


def _resolve_temperature(thermal: Mapping[str, Any], power_w: float) -> dict[str, Any]:
  """热路解析：显式 t_hot_c（真机/实测注入）优先，否则闭式 R_th。"""
  _reject_unknown(thermal, {"ambient_c", "r_th_k_per_w", "t_hot_c"}, "thermal")
  t_hot = thermal.get("t_hot_c")
  if t_hot is not None:
    t_hot_c = _finite(t_hot, "thermal.t_hot_c")
    return {"t_hot_c": t_hot_c, "source": "injected",
        "ambient_c": (None if thermal.get("ambient_c") is None
               else _finite(thermal.get("ambient_c"), "thermal.ambient_c")),
        "rise_k": t_hot_c - (
          _finite(thermal.get("ambient_c", 25.0), "thermal.ambient_c"))}
  ambient_c = _finite(
    _require_key(thermal, "ambient_c", "thermal"), "thermal.ambient_c")
  r_th = _finite(_require_key(thermal, "r_th_k_per_w", "thermal"),
          "thermal.r_th_k_per_w")
  if r_th < 0.0:
    raise ValueError(f"thermal.r_th_k_per_k 必须 >=0，收到 {r_th!r}")
  rise_k = r_th * power_w
  return {"t_hot_c": ambient_c + rise_k, "rise_k": rise_k,
      "r_th_k_per_w": r_th, "ambient_c": ambient_c, "source": "r_th_closed_form"}


def run_wilkinson_electrothermal(payload: Mapping[str, Any]) -> dict[str, Any]:
  """首案例链路编排：损耗 → 温度 → 温漂 → 失谐（+ 带内判据，可选）。

  Raises 不外泄：任何 ValueError 转成 {"ok": False, "error": str}。
  """
  try:
    src = _as_mapping(payload, "payload")
    _reject_unknown(src, {"case", "thermal", "material", "resonator", "band"},
            "payload")
    case = _as_mapping(_require_key(src, "case", "payload"), "case")
    thermal = _as_mapping(_require_key(src, "thermal", "payload"), "thermal")
    material = _as_mapping(_require_key(src, "material", "payload"), "material")
    resonator = _as_mapping(_require_key(src, "resonator", "payload"), "resonator")
    _reject_unknown(material, {"t_ref_c", "cte_ppm_per_k", "tcdk_ppm_per_k"},
            "material")
    _reject_unknown(resonator, {"f0_hz"}, "resonator")

    power = _resolve_power(case)
    heat = _resolve_temperature(thermal, power["resistor_w"])

    t_ref = material.get("t_ref_c")
    t_ref_c = _finite(t_ref, "material.t_ref_c") if t_ref is not None else 25.0
    delta_t = heat["t_hot_c"] - t_ref_c
    drift = thermal_detune(
      f0_hz=_finite(_require_key(resonator, "f0_hz", "resonator"), "f0_hz"),
      delta_t_c=delta_t,
      cte_ppm_per_k=_finite(
        _require_key(material, "cte_ppm_per_k", "material"), "cte_ppm_per_k"),
      tcdk_ppm_per_k=_finite(
        _require_key(material, "tcdk_ppm_per_k", "material"), "tcdk_ppm_per_k"),
    )

    band_raw = src.get("band")
    band_out: dict[str, Any] | None = None
    if band_raw is not None:
      band = _as_mapping(band_raw, "band")
      band_out = band_guard(
        drift["f0_shifted_hz"],
        _finite(_require_key(band, "low_hz", "band"), "band.low_hz"),
        _finite(_require_key(band, "high_hz", "band"), "band.high_hz"),
      )
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "chain": {
    "power": power, "thermal": heat,
    "material": {"t_ref_c": t_ref_c, "delta_t_c": delta_t},
    "drift": drift, "band": band_out,
  }}


# ---------------------------------------------------------------------------
# WP4.4a ③ 双向温漂定点编排（Icepak 场解 R_th 推导 + core 定点迭代注入）
# ---------------------------------------------------------------------------

def derive_r_th_from_field(payload: Mapping[str, Any]) -> dict[str, Any]:
  """Icepak/实测温度场 → 有效热阻 R_th = ΔT/P [K/W]（纯确定性算术）。

  payload: {"t_hot_c": 热点温度, "power_w": 耗散功率,
       "ambient_c": 环境/热沉温度（默认 25.0）, "source": 标注（可选）}

  校验：功率 >0、温升 ΔT = t_hot − ambient >=0（负温升非物理，显式报错
  不夹取）。返回 {"ok": True, "r_th_k_per_w", "rise_k", ...}；
  非法输入 {"ok": False, "error"}（确定性、可序列化）。
  """
  try:
    src = _as_mapping(payload, "payload")
    _reject_unknown(src, {"t_hot_c", "power_w", "ambient_c", "source"},
            "payload")
    t_hot_c = _finite(_require_key(src, "t_hot_c", "payload"), "t_hot_c")
    power_w = _finite(_require_key(src, "power_w", "payload"), "power_w")
    ambient_raw = src.get("ambient_c")
    ambient_c = (_finite(ambient_raw, "ambient_c")
           if ambient_raw is not None else 25.0)
    if power_w <= 0.0:
      raise ValueError(f"power_w 必须 >0，收到 {power_w!r}")
    rise_k = t_hot_c - ambient_c
    if rise_k < 0.0:
      raise ValueError(
        f"温升非物理：t_hot_c({t_hot_c}) < ambient_c({ambient_c})")
    return {"ok": True,
        "r_th_k_per_w": rise_k / power_w,
        "rise_k": rise_k,
        "t_hot_c": t_hot_c,
        "power_w": power_w,
        "ambient_c": ambient_c,
        "source": str(src["source"]) if "source" in src else "icepak_field"}
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}


def run_electrothermal_fixed_point(
  payload: Mapping[str, Any],
  *,
  em_evaluator: Any = None,
  loss_evaluator: Any = None,
) -> dict[str, Any]:
  """双向温漂定点编排（D3-3 口径）：材料(T) ↔ 损耗 ↔ 温度。

  在 core/thermal_iteration.solve_thermal_fixed_point 之上做 JSON 进出
  薄编排（core 文件不改）：

  - ``material``：MaterialTemperatureModel 字典（TCDk/CTE/tan_delta 温度
   律，core 单一实现）；
  - ``config``：ThermalIterationConfig 字典，但 **不得含
   thermal_resistance_k_per_w**（由 thermal 节给出，避免双源）；
  - ``thermal``：二选一——{"ambient_c", "r_th_k_per_w"} 闭式热阻，或
   {"t_hot_c", "power_w"(, "ambient_c")} Icepak/实测场解（经
   derive_r_th_from_field 推导）。

  em_evaluator/loss_evaluator：仅 keyword 注入的回调（不属于 JSON 契约，
  供离线收敛测试用 fake 评估器钉通道 #139）；None = core 微带解析链
  （无网络）。

  返回 {"ok": True, "thermal": {...}, "result": {...}}；非法输入
  {"ok": False, "error"}。
  """
  try:
    src = _as_mapping(payload, "payload")
    _reject_unknown(src, {"material", "config", "thermal"}, "payload")
    material = MaterialTemperatureModel.from_dict(
      _as_mapping(_require_key(src, "material", "payload"), "material"))
    config_raw = dict(_as_mapping(
      _require_key(src, "config", "payload"), "config"))
    if "thermal_resistance_k_per_w" in config_raw:
      raise ValueError(
        "config.thermal_resistance_k_per_w 由 thermal 节推导，"
        "不得在 config 中重复给出")
    thermal = _as_mapping(_require_key(src, "thermal", "payload"), "thermal")
    if "r_th_k_per_w" in thermal:
      _reject_unknown(thermal, {"ambient_c", "r_th_k_per_w"}, "thermal")
      r_th_value = _finite(thermal["r_th_k_per_w"], "thermal.r_th_k_per_w")
      if r_th_value < 0.0:
        raise ValueError(f"thermal.r_th_k_per_w 必须 >=0，收到 {r_th_value!r}")
      r_th: dict[str, Any] = {
        "ok": True, "r_th_k_per_w": r_th_value,
        "ambient_c": _finite(thermal.get("ambient_c", 25.0),
                   "thermal.ambient_c"),
        "source": "explicit"}
    else:
      _reject_unknown(thermal, {"ambient_c", "t_hot_c", "power_w", "source"},
              "thermal")
      r_th = derive_r_th_from_field(thermal)
      if not r_th.get("ok"):
        return {"ok": False, "error": f"thermal: {r_th.get('error')}"}
    ambient_c = float(r_th["ambient_c"])
    config = ThermalIterationConfig.from_dict({
      **config_raw,
      "ambient_c": config_raw.get("ambient_c", ambient_c),
      "thermal_resistance_k_per_w": r_th["r_th_k_per_w"],
    })
    result = solve_thermal_fixed_point(
      material, config,
      em_evaluator=em_evaluator, loss_evaluator=loss_evaluator)
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "thermal": r_th, "result": result.to_dict()}
