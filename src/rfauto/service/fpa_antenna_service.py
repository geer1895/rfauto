"""LM-1 P2：Fabry-Perot 谐振腔天线 service 面（JSON 进出，规则 4；CLI/MCP 薄壳）。

零物理公式（规则 7）——全部数字出自 core/fpa_antenna.py 确定性内核
（Ji 2016 PIERL 58 / Trentini 1956 口径，法源见内核 docstring）。三入口：

- :func:`fpa_design`：一次成点（给 phi_prs_deg 或 h_m 恰其一 → 腔高/
  所需相位 + D/dB + Q/带宽）；
- :func:`fpa_resonance_heights`：(f0, phi_PRS, phi_GND) → 腔高多解列表；
- :func:`fpa_directivity_scan`：R 数组 → D 数组（单调性守恒）+ dB 面。

信封约定（同 aging_service）：非法入参 ``{"ok": False, "errors": [...]}``
不抛异常；正常路径 ``{"ok": True, ...}`` 全 JSON 可序列化。诚实边界随
返回体透传（q_model/feed_loading/literature_anchor 字段出自内核）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core import fpa_antenna

# F-13 批 2（W6-E）：载荷守卫单源化（#116 删净）。文案分歧件已声明统一：
# 原「payload 必须为 dict」→ 单源「payload 必须是 JSON 对象，实际 X」
# （ValueError 捕获进 errors 的 ok=False 语义逐位不变，文案变更见
# W6-E 报告）。
from rfauto.service._helpers import require_payload_dict as _require_payload_dict
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
FPA_SERVICE_SCHEMA_VERSION = "1.0"


def _require_fields(payload: dict[str, Any], names: tuple[str, ...]) -> None:
    missing = [k for k in names if payload.get(k) is None]
    if missing:
        raise ValueError(f"缺必填参数 {missing}")


def fpa_design(payload: Any) -> dict[str, Any]:
    """FPA 设计点一次成点（JSON 信封）。

    payload 必填 {f0_ghz, r, phi_gnd_deg}；可选 {phi_prs_deg | h_m} 恰给
    其一、{n}（phi 分支谐振阶，缺省 0）。缺参/非法值 → ok=False errors
    （错误来自内核校验，逐条入列）。
    """
    try:
        p = _require_payload_dict(payload)
        _require_fields(p, ("f0_ghz", "r", "phi_gnd_deg"))
        design = fpa_antenna.design_point(
            p["f0_ghz"],
            p["r"],
            p["phi_gnd_deg"],
            phi_prs_deg=p.get("phi_prs_deg"),
            h_m=p.get("h_m"),
            n=p.get("n", 0),
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return error_envelope([str(exc)])
    return ok_envelope(schema_version=FPA_SERVICE_SCHEMA_VERSION, design=design)


def fpa_resonance_heights(payload: Any) -> dict[str, Any]:
    """(f0, phi_PRS, phi_GND) → 腔高多解列表（JSON 信封）。

    payload 必填 {f0_ghz, phi_prs_deg, phi_gnd_deg}；可选 {n_solutions,
    h_max_m}（语义同内核）。
    """
    try:
        p = _require_payload_dict(payload)
        _require_fields(p, ("f0_ghz", "phi_prs_deg", "phi_gnd_deg"))
        sols = fpa_antenna.resonance_heights(
            p["f0_ghz"],
            p["phi_prs_deg"],
            p["phi_gnd_deg"],
            n_solutions=p.get("n_solutions", 8),
            h_max_m=p.get("h_max_m"),
        )
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return error_envelope([str(exc)])
    return ok_envelope(schema_version=FPA_SERVICE_SCHEMA_VERSION, solutions=[s.to_dict() for s in sols])


def fpa_directivity_scan(payload: Any) -> dict[str, Any]:
    """R 数组 → D 数组 + dB 数组（JSON 信封；两路数字全部出自内核）。

    d 出内核 directivity_scan 扫描面（含逐元素校验）；dB 出内核
    directivity_db 逐 R 点产出（本服务零公式，规则 7——上一版把 D 值
    误作 R 传入 directivity_db 的错法已修，DB 面按 R 原值重放内核）。
    """
    try:
        p = _require_payload_dict(payload)
        r_values = p.get("r_values")
        if r_values is None:
            raise ValueError("缺必填参数 ['r_values']")
        arr = np.asarray(r_values, dtype=float)
        d = fpa_antenna.directivity_scan(arr)
        r_list = [float(x) for x in arr.ravel()]
        d_list = [float(x) for x in np.asarray(d).ravel()]
        db_list = [fpa_antenna.directivity_db(r) for r in r_list]
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return error_envelope([str(exc)])
    return ok_envelope(schema_version=FPA_SERVICE_SCHEMA_VERSION, r=r_list, d=d_list, d_db=db_list)
