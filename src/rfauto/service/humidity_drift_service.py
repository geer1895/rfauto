"""F-H.2 P2：湿度吸湿漂移 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/humidity_drift.py 内核（本服务零物理公式，全部数字出自确定性
内核，规则 7）。两入口：

- :func:`moisture_uptake_estimate`：暴露时长/扩散系数/板厚 → Fick 级数 +
  短时 √t 律双路径（对拍相对差+守卫域标记）；可选吸湿 εr(M) 节（混合
  三式之一）；
- :func:`msl_floor_life_query`：MSL 等级 → 车间寿命（JEDEC J-STD-033）
  + 可选 exposure_h 判耗尽。

诚实边界（预声明）：FR-4/RO4350B 等层压板的 D 与 M∞ 无单源典型值
（core 模块 MOISTURE_PARAM_STATUS awaiting_data 政策）——本服务不内嵌
材料常数， diffusivity/thickness/er_water 等全部由调用方按数据表给值；
er_water 频变强烈无缺省。所有异常（含 payload 非对象、内核 ValueError）
收敛为 ok=False errors 信封，不向调用方抛出。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from rfauto.core import humidity_drift as hum
from rfauto.service._helpers import (
    err_envelope,
)
from rfauto.service._helpers import (
    optional_num as _optional_num,
)
from rfauto.service._helpers import (
    parse_num as _num,
)
from rfauto.service._helpers import (
    require_payload_dict as _require_payload_dict,
)
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
HUMIDITY_DRIFT_SCHEMA_VERSION = "1.0"

#: 混合规则合法集（透出给调用方）
MIX_RULES = ("looyenga", "maxwell_garnett", "bruggeman")

# S2-8 单源化（review_ge8e 2026-10-04）：_num/_require_payload_dict/
# _optional_num 本地近逐字节拷贝已删净（#116），单源在 service._helpers；
# _err 为本服务版本戳变体（单源 err_envelope 的 partial 绑定，零本地逻辑）。
_err = partial(err_envelope, schema_version=HUMIDITY_DRIFT_SCHEMA_VERSION)


def moisture_uptake_estimate(payload: Any) -> dict[str, Any]:
    """湿度吸湿端到端估计（Fick 双路径 uptake + 可选 εr(M) 节）。

    Args（payload 键）:
        t_s 或 t_h: 暴露时长（二选一，>=0）；
        diffusivity_m2_s: 扩散系数 D（必填，>0，按牌号数据表——服务不内嵌
            材料常数）；
        thickness_m 或 thickness_mm: 平板全厚（二选一，>0）；
        m_inf_frac: 饱和吸湿量（可选，>=0，缺省 1.0=无纲分数口径）；
        t_over_tau_max: 短时守卫域（可选，缺省 0.05 预声明口径）；
        epsilon 节（可选，给了即须全组）：{moisture_frac, er_dry, rho_dry,
        er_water, rule?, rho_water?}。

    Returns:
        dict: {ok, schema_version, uptake:{...}, epsilon?:{...}, provenance,
        disclaimer}；非法入参/内核异常 → {ok:false, errors} 信封。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])

    t_s = _num(p.get("t_s"), "t_s", errors, nonneg=True) if p.get("t_s") is not None else None
    if t_s is None and p.get("t_h") is not None:
        t_h = _num(p.get("t_h"), "t_h", errors, nonneg=True)
        t_s = None if t_h is None else t_h * 3600.0
    if t_s is None and "t_h" not in p:
        errors.append("t_s 或 t_h 必须给其一")

    d = _num(p.get("diffusivity_m2_s"), "diffusivity_m2_s", errors, positive=True)
    th_m = (
        _num(p.get("thickness_m"), "thickness_m", errors, positive=True)
        if p.get("thickness_m") is not None
        else None
    )
    if th_m is None and p.get("thickness_mm") is not None:
        th_mm = _num(p.get("thickness_mm"), "thickness_mm", errors, positive=True)
        th_m = None if th_mm is None else th_mm * 1e-3
    if th_m is None and "thickness_mm" not in p:
        errors.append("thickness_m 或 thickness_mm 必须给其一")

    m_inf = _optional_num(p.get("m_inf_frac"), "m_inf_frac", errors, nonneg=True)
    t_over_tau_max = _optional_num(p.get("t_over_tau_max"), "t_over_tau_max", errors)

    eps = p.get("epsilon")
    eps_out: dict[str, Any] | None = None
    if eps is not None:
        if not isinstance(eps, dict):
            errors.append("epsilon 必须是 JSON 对象")
        else:
            mf = _num(eps.get("moisture_frac"), "epsilon.moisture_frac", errors, nonneg=True)
            erd = _num(eps.get("er_dry"), "epsilon.er_dry", errors, positive=True)
            rd = _num(eps.get("rho_dry"), "epsilon.rho_dry", errors, positive=True)
            erw = _num(eps.get("er_water"), "epsilon.er_water", errors, positive=True)
            rule = eps.get("rule", "looyenga")
            if rule not in MIX_RULES:
                errors.append(f"epsilon.rule 必须 ∈ {list(MIX_RULES)}，实际 {rule!r}")
            rw = _optional_num(
                eps.get("rho_water"), "epsilon.rho_water", errors, positive=True
            )
            if None not in (mf, erd, rd, erw) and rule in MIX_RULES:
                try:
                    res = hum.epsilon_moisture_shift(
                        mf,
                        erd,
                        rd,
                        erw,
                        rho_water=1000.0 if rw is None else rw,
                        rule=rule,
                    )
                    eps_out = res.to_dict()
                except ValueError as exc:
                    errors.append(f"epsilon 计算失败: {exc}")

    if errors:
        return _err(errors)
    assert t_s is not None and d is not None and th_m is not None  # errors 已拦
    try:
        uptake = hum.moisture_uptake(
            t_s,
            d,
            th_m,
            1.0 if m_inf is None else m_inf,
            t_over_tau_max=hum.SHORT_TIME_DOMAIN_DEFAULT if t_over_tau_max is None else t_over_tau_max,
        )
    except ValueError as exc:
        return _err([f"内核计算失败: {exc}"])
    out: dict[str, Any] = ok_envelope(
        schema_version=HUMIDITY_DRIFT_SCHEMA_VERSION,
        uptake=uptake.to_dict(),
        provenance={
            "fick": "Crank, The Mathematics of Diffusion, 2nd ed. (1975) §4.3",
            "mixing": "Looyenga Physica 31:401 (1965)；Maxwell-Garnett 1904；Bruggeman 1935",
            "msl": "JEDEC J-STD-033 车间寿命表（verbatim）",
        },
        disclaimer="D/M∞/er_water 由调用方按数据表给值（服务不内嵌材料常数，"
            "awaiting_data 政策见 core.humidity_drift.MOISTURE_PARAM_STATUS）；"
            "√t 律仅短时域渐近，守卫域外以级数路径为准",
    )
    if eps_out is not None:
        out["epsilon"] = eps_out
    return out


def msl_floor_life_query(payload: Any) -> dict[str, Any]:
    """MSL 车间寿命查询（J-STD-033 表）+ 可选 exposure_h 耗尽判定。

    Args（payload 键）: msl（必填，"1".."6"/"2a"/"5a"）；exposure_h（可选，
        >=0，给出则判 expired）。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])
    msl = p.get("msl")
    if not isinstance(msl, str):
        errors.append(f"msl 必须是字符串，实际 {msl!r}")
        return _err(errors)
    exposure = _optional_num(p.get("exposure_h"), "exposure_h", errors, nonneg=True)
    if errors:
        return _err(errors)
    try:
        floor = hum.msl_floor_life_hours(msl)
    except ValueError as exc:
        return _err([str(exc)])
    out: dict[str, Any] = {
        "ok": True,
        "schema_version": HUMIDITY_DRIFT_SCHEMA_VERSION,
        "msl": msl,
        "floor_life_h": floor,  # None=无限（MSL1），JSON 语义
        "unlimited": floor is None,
        "provenance": "JEDEC J-STD-033 车间寿命表（标准 verbatim；1 年=8760h、4 周=672h 为小时换算）",
    }
    if exposure is not None:
        out["exposure_h"] = exposure
        out["expired"] = hum.msl_floor_life_expired(msl, exposure)
    return out
