"""D9 频段注册表 service：JSON 进出，CLI/MCP/UI 三壳共享（规则 4）。

数值只在确定性内核（铁律 7）：本模块只做参数校验与异常到 JSON 的翻译，
一切频段边界/限值来自 core/bands.py 的标准常量表（逐条带出处）。
显式报错语义（与 calculator_service 一致）：未知 key / 非法参数一律
ok=False + error（不抛出），薄壳零逻辑直接渲染。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.bands import (
  BANDS,
  ENVIRONMENTS,
  BandKind,
  EnvKind,
  env_temperature_points,
  env_to_delta_t,
  env_to_uq_axis,
  find_bands,
  find_envs,
  get_band,
  get_env,
  search,
  search_env,
  to_spec_bounds,
)


def bands_list(
  standard: str | None = None,
  kind: str | None = None,
  region: str | None = None,
) -> dict[str, Any]:
  """频段清单（可按 standard 子串/kind/region 过滤），JSON 可直接渲染。"""
  try:
    entries = search(standard=standard, kind=kind, region=region)
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {
    "ok": True,
    "count": len(entries),
    "total": len(BANDS),
    "bands": [e.to_dict() for e in entries],
  }


def _check_key(key: Any) -> str | None:
  """key 参数校验：非空字符串。非法返回错误消息，合法返回 None。"""
  if not isinstance(key, str) or not key.strip():
    return f"key 必须为非空字符串，收到: {key!r}"
  return None


def bands_get(key: str) -> dict[str, Any]:
  """按 key 取单条频段（未知 key → ok=False，error 带可用键列表）。"""
  err = _check_key(key)
  if err:
    return {"ok": False, "error": err}
  try:
    entry = get_band(key)
  except KeyError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "band": entry.to_dict()}


def bands_find(freq_ghz: Any) -> dict[str, Any]:
  """查包含给定频率的全部条目。

  参数校验：freq 必须是正有限数（bool 是 int 子类，显式拒绝）。
  """
  if isinstance(freq_ghz, bool) or not isinstance(freq_ghz, (int, float)):
    return {"ok": False, "error": f"freq_ghz 必须为数字，收到: {freq_ghz!r}"}
  try:
    entries = find_bands(freq_ghz)
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {
    "ok": True,
    "freq_ghz": float(freq_ghz),
    "count": len(entries),
    "bands": [e.to_dict() for e in entries],
  }


def bands_spec_bounds(key: str) -> dict[str, Any]:
  """key → {"band": [f_low, f_high]}（SpecEvaluator Objective.band 结构）。

  用法：objectives 条目先 from rfauto.core.objectives import Objective，
  再 Objective(metric=..., **bands_spec_bounds("gpp_n78"), op=..., value=...)。
  """
  err = _check_key(key)
  if err:
    return {"ok": False, "error": err}
  try:
    bounds = to_spec_bounds(key)
  except KeyError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "key": key, "spec_bounds": bounds, "kind": get_band(key).kind.value}


# 供薄壳（CLI/MCP/UI）渲染参数提示：合法 kind 与 region 集合
VALID_KINDS: list[str] = [m.value for m in BandKind]
VALID_REGIONS: list[str] = sorted({e.region for e in BANDS.values()})

# ── D9 环境包络注册表 service（D9 强化）───────────────────────────────
# 与频段接口同风格：JSON 进出、未知 key/非法参数一律 ok=False + error（不抛出），
# 薄壳零逻辑直接渲染。数值仍只来自 core/bands.py 的标准常量表。


def bands_env_list(standard: str | None = None,
          kind: str | None = None) -> dict[str, Any]:
  """环境包络清单（可按 standard 子串/kind 过滤），JSON 可直接渲染。"""
  try:
    entries = search_env(standard=standard, kind=kind)
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {
    "ok": True,
    "count": len(entries),
    "total": len(ENVIRONMENTS),
    "environments": [e.to_dict() for e in entries],
  }


def bands_env_get(key: str) -> dict[str, Any]:
  """按 key 取单条环境包络（未知 key → ok=False，error 带可用键列表）。"""
  err = _check_key(key)
  if err:
    return {"ok": False, "error": err}
  try:
    entry = get_env(key)
  except KeyError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "environment": entry.to_dict()}


def bands_env_find(t_c: Any) -> dict[str, Any]:
  """查温区包含给定温度的全部环境包络（bool/非数字显式拒绝）。"""
  if isinstance(t_c, bool) or not isinstance(t_c, (int, float)):
    return {"ok": False, "error": f"t_c 必须为数字，收到: {t_c!r}"}
  try:
    entries = find_envs(t_c)
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {
    "ok": True,
    "t_c": float(t_c),
    "count": len(entries),
    "environments": [e.to_dict() for e in entries],
  }


def bands_env_delta_t(key: str, t_ref_c: Any = None) -> dict[str, Any]:
  """环境包络 → ΔT 上下限（D3 温区扫描 / D8 UQ / WP4.2 良率消费接口）。

  t_ref_c=None 用条目自身参考温度；显式传入必须为数字（bool 拒绝）。
  """
  err = _check_key(key)
  if err:
    return {"ok": False, "error": err}
  ref: float | None = None
  if t_ref_c is not None:
    if isinstance(t_ref_c, bool) or not isinstance(t_ref_c, (int, float)):
      return {"ok": False,
          "error": f"t_ref_c 必须为数字或 null，收到: {t_ref_c!r}"}
    ref = float(t_ref_c)
  try:
    bounds = env_to_delta_t(key, t_ref_c=ref)
  except (KeyError, ValueError) as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, **bounds}


def bands_env_uq_axis(key: str, t_ref_c: Any = None,
           k_sigma: Any = 3.0) -> dict[str, Any]:
  """环境包络 → UQ/良率温度轴（名义点 + σ + ΔT 上下限）。"""
  err = _check_key(key)
  if err:
    return {"ok": False, "error": err}
  ref: float | None = None
  if t_ref_c is not None:
    if isinstance(t_ref_c, bool) or not isinstance(t_ref_c, (int, float)):
      return {"ok": False,
          "error": f"t_ref_c 必须为数字或 null，收到: {t_ref_c!r}"}
    ref = float(t_ref_c)
  if isinstance(k_sigma, bool) or not isinstance(k_sigma, (int, float)):
    return {"ok": False, "error": f"k_sigma 必须为数字，收到: {k_sigma!r}"}
  try:
    axis = env_to_uq_axis(key, t_ref_c=ref, k_sigma=float(k_sigma))
  except (KeyError, ValueError) as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, **axis}


def bands_env_points(key: str, n: Any = 5) -> dict[str, Any]:
  """温区等距采样点（含两端），供 D3 温区扫描。"""
  err = _check_key(key)
  if err:
    return {"ok": False, "error": err}
  try:
    points = env_temperature_points(key, n)
  except KeyError as exc:
    return {"ok": False, "error": str(exc)}
  except ValueError as exc:
    return {"ok": False, "error": str(exc)}
  return {"ok": True, "key": key, "count": len(points), "temperatures_c": points}


# 供薄壳（CLI/MCP/UI）渲染参数提示：环境包络合法 kind 集合
VALID_ENV_KINDS: list[str] = [m.value for m in EnvKind]

