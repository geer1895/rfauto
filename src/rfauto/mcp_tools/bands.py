"""bands_* 十接口（D9 频段/环境包络注册表薄壳）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 20. 频段/环境包络注册表（D9 归口 WP3.3 的 MCP 薄壳） ─────────────────────

@mcp.tool
def bands_list(
    standard: str | None = None,
    kind: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """频段清单查询（bands 域）：过滤词 → 标准频段注册表条目清单。

    无副作用，可安全调用；不用于单键取值（走 bands_get）。过滤零命中
    如实回空清单；注册表不可用 → ok=False error。只读无时序约束。

    Args:
        standard: 按 standard 子串过滤（如 "3GPP"）；缺省不过滤
        kind: 按类型过滤（如 "cellular"/"ism"）；缺省不过滤
        region: 按区域过滤；缺省不过滤

    Returns:
        dict: {ok, count, total, bands: [...]}；异常 → ok=False error
    """
    from rfauto.service.bands_service import bands_list as _list
    return _list(standard=standard, kind=kind, region=region)


@mcp.tool
def bands_get(key: str) -> dict[str, Any]:
    """按 key 取单条频段详情（边界/出处/区域）。

    无副作用，可安全调用。未知 key 返回 ok=False 且 error 带可用键列表。

    Args:
        key: 频段键（如 "gpp_n78"）

    Returns:
        dict: {ok, band} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_get as _get
    return _get(key)


@mcp.tool
def bands_find(freq_ghz: float) -> dict[str, Any]:
    """频段查询（bands 域）：频率 GHz → 覆盖该频率的全部频段条目。

    无副作用，可安全调用；不用于生成 bounds（走 bands_spec_bounds）。
    频率非正有限 → ok=False 如实。只读无时序约束。

    Args:
        freq_ghz: 频率 (GHz，正有限数)

    Returns:
        dict: {ok, freq_ghz, count, bands: [...]}；非法频率 → ok=False
    """
    from rfauto.service.bands_service import bands_find as _find
    return _find(freq_ghz)


@mcp.tool
def bands_spec_bounds(key: str) -> dict[str, Any]:
    """频段 band 结构查询（bands 域）：频段键 → SpecEvaluator band 界。

    无副作用，可安全调用；喂 objectives 的 band 定义与优化 bounds，不用于
    条目清单（走 bands_list）。未知/非法键 → ok=False error 不猜键名。
    只读无时序约束。

    Args:
        key: 频段键（如 "gpp_n78"）

    Returns:
        dict: {ok, key, spec_bounds, kind} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_spec_bounds as _bounds
    return _bounds(key)


@mcp.tool
def bands_env_list(
    standard: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """环境包络清单查询（bands 域）：过滤词 → 包络注册表条目清单。

    无副作用，可安全调用；不用于单键详情（走 bands_env_get）。零命中
    如实回空清单；注册表不可用 → ok=False error。只读无时序约束。

    Args:
        standard: 按 standard 子串过滤；缺省不过滤
        kind: 按类型过滤；缺省不过滤

    Returns:
        dict: {ok, count, total, environments: [...]}；异常 → ok=False
    """
    from rfauto.service.bands_service import bands_env_list as _list
    return _list(standard=standard, kind=kind)


@mcp.tool
def bands_env_get(key: str) -> dict[str, Any]:
    """按 key 取单条环境包络详情（温区/等级/出处）。

    无副作用，可安全调用。未知 key 返回 ok=False 且 error 带可用键列表。

    Args:
        key: 环境包络键（如 "iec_industrial"）

    Returns:
        dict: {ok, environment} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_get as _get
    return _get(key)


@mcp.tool
def bands_env_find(t_c: float) -> dict[str, Any]:
    """环境包络查询（bands 域）：温度 °C → 覆盖该温区的全部环境包络。

    无副作用，可安全调用；数值只出自 core/bands.py 标准常量表，不插值
    不外推。非法温度 → ok=False。只读无时序约束。

    Args:
        t_c: 温度 (°C)

    Returns:
        dict: {ok, t_c, count, environments: [...]}；非法温度 → ok=False
    """
    from rfauto.service.bands_service import bands_env_find as _find
    return _find(t_c)


@mcp.tool
def bands_env_delta_t(key: str, t_ref_c: float | None = None) -> dict[str, Any]:
    """环境包络 ΔT 界查询（bands 域）：包络键 → ΔT 上下限（°C）。

    无副作用，可安全调用；数值只出自 core/bands.py 标准常量表，不插值
    不外推。未知包络键 → ok=False 不猜键名（先 bands_env_list 查键面）。
    只读无时序约束。

    Args:
        key: 环境包络键
        t_ref_c: 参考温度 (°C)；缺省用条目自身参考温度

    Returns:
        dict: {ok, delta_t_low, delta_t_high, ...} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_delta_t as _dt
    return _dt(key, t_ref_c)


@mcp.tool
def bands_env_uq_axis(
    key: str,
    t_ref_c: float | None = None,
    k_sigma: float = 3.0,
) -> dict[str, Any]:
    """UQ 温度轴查询（bands 域）：包络键 → 名义点+σ+ΔT 上下限（°C）。

    无副作用，可安全调用；喂 D8 UQ/良率的温度轴，不用于采样点展开
    （走 bands_env_points）。未知键/非法 k_sigma → ok=False 如实。
    只读无时序约束。

    Args:
        key: 环境包络键
        t_ref_c: 参考温度 (°C)；缺省用条目自身参考温度
        k_sigma: σ 倍数（默认 3.0）

    Returns:
        dict: {ok, t_nominal_c, sigma, t_low_c, t_high_c, ...}
        或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_uq_axis as _uq
    return _uq(key, t_ref_c, k_sigma)


@mcp.tool
def bands_env_points(key: str, n: int = 5) -> dict[str, Any]:
    """环境包络采样（bands 域）：包络键 → 温区等距采样点（含两端）。

    无副作用，可安全调用；未知包络键 → ok=False 不猜键名（先
    bands_env_list 查键面）。只读无时序约束。

    Args:
        key: 环境包络键（bands_env_list 可查）
        n: 采样点数（默认 5）

    Returns:
        dict: {ok, key, count, temperatures_c: [...]} 或 {ok: False, error}
    """
    from rfauto.service.bands_service import bands_env_points as _points
    return _points(key, n)
