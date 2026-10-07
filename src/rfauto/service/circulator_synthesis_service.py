"""F-K.B 环形器综合 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/circulator_synthesis.py 内核（全部物理数字出自确定性闭式，规则 7）。
零物理公式：本服务只做入参收敛 → 内核调用 → JSON 信封组装；任何内核
ValueError 转 ok=False 显式错误（不抛、不部分产出）。

- :func:`circulator_disk_design`：Polder 张量 + μ_eff + 盘半径初值 +
  准理想 S 矩阵（ΔH 损耗通道可选）+ λ/4 匹配段（可选结阻抗）；
- :func:`circulator_lumped_lc`：集总 LC 低频版（f0 恒等式 + 理想环行 S）。

**诚实边界**：输出全部为设计初值（非真机裁决）；UNVERIFIED 项（Wu-
Rosenbaum 精确百分比、Bosma Eq.69 系数）随 provenance 原样透传，不做
判定（#122 判据先行）。引擎/仿真面不在此服务（openEMS 张量限制与
HFSS/COMSOL 仲裁锚登记见内核 docstring）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import circulator_synthesis as circ
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
CIRCULATOR_SERVICE_SCHEMA_VERSION = "1.0"


def _envelope_ok(data: dict) -> dict:
    return ok_envelope(schema_version=CIRCULATOR_SERVICE_SCHEMA_VERSION, data=data)


def _envelope_err(exc: Exception) -> dict:
    return {
        "ok": False,
        "schema_version": CIRCULATOR_SERVICE_SCHEMA_VERSION,
        "error": str(exc),
        "error_type": type(exc).__name__,
    }


def _positive(value: float, name: str) -> float:
    """service 侧入参收敛（不伸内核私有助手；与内核同口径拒 bool/非有限/<=0）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数")
    return out


def circulator_disk_design(
    f_hz: float,
    er: float,
    ms_a_per_m: float,
    h_i_a_per_m: float,
    delta_h_a_per_m: float | None = None,
    alpha: float | None = None,
    h_sat_a_per_m: float | None = None,
    z0_ohm: float = 50.0,
    z_junction_ohm: float | None = None,
    sense: int = 1,
) -> dict:
    """结盘半径设计面：JSON 信封（ok=False 不抛）。

    内核入参语义同 core.circulator_synthesis.disk_design；可选
    z_junction_ohm（结阻抗）给出 λ/4 变换段初值 Z_T=√(Z_j·Z0)；
    sense=±1 环行方向。返回 data 键：polder/mu_eff/disk/s_matrix/
    quarter_wave（可选）/provenance。
    """
    try:
        polder = circ.polder_permeability(
            f_hz,
            ms_a_per_m,
            h_i_a_per_m,
            delta_h_a_per_m=delta_h_a_per_m,
            alpha=alpha,
            h_sat_a_per_m=h_sat_a_per_m,
        )
        design = circ.disk_design(
            f_hz,
            er,
            ms_a_per_m,
            h_i_a_per_m,
            delta_h_a_per_m=delta_h_a_per_m,
            alpha=alpha,
            h_sat_a_per_m=h_sat_a_per_m,
        )
        loss: float | None = None
        try:
            loss = circ.magnetic_loss_fraction(polder)
        except ValueError:
            loss = None  # 截止带/深损耗带：loss 口径不适用，如实 None 不硬造
        if loss is not None and loss > 0.0:
            s_mat = circ.quasi_ideal_lossy_s_matrix(loss, sense=sense)
        else:
            s_mat = circ.ideal_junction_s_matrix(sense=sense)
        data: dict[str, Any] = {
            "polder": polder.to_dict(),
            "mu_eff": {
                "re": design.mu_eff.real,
                "im": design.mu_eff.imag,
                "cutoff": design.cutoff,
            },
            "disk": design.to_dict(),
            "s_matrix": s_mat.to_dict(),
            "provenance": dict(circ.CIRCULATOR_SYNTHESIS_PROVENANCE),
        }
        if z_junction_ohm is not None:
            zt = circ.quarter_wave_transformer_impedance(z_junction_ohm, z0_ohm)
            data["quarter_wave"] = {
                "z_junction_ohm": _positive(z_junction_ohm, "z_junction_ohm"),
                "z0_ohm": _positive(z0_ohm, "z0_ohm"),
                "z_t_ohm": zt,
            }
        return _envelope_ok(data)
    except (ValueError, TypeError) as exc:
        return _envelope_err(exc)


def circulator_lumped_lc(l_h: float, c_f: float, sense: int = 1) -> dict:
    """集总 LC 低频版：JSON 信封（ok=False 不抛）。data 键：lumped_lc。"""
    try:
        lc = circ.lumped_lc_circulator(l_h, c_f, sense=sense)
        return _envelope_ok({"lumped_lc": lc.to_dict()})
    except (ValueError, TypeError) as exc:
        return _envelope_err(exc)


def circulator_bandwidth_reference(f_low_hz: float) -> dict:
    """Wu-Rosenbaum 倍频程登记面：JSON 信封（UNVERIFIED 清单原样透传）。"""
    try:
        ref = circ.wu_rosenbaum_bandwidth_reference(f_low_hz)
        if not math.isfinite(float(ref["f_low_hz"])):  # pragma: no cover - 防御性
            raise ValueError("f_low_hz 必须为有限数")
        return _envelope_ok({"bandwidth_reference": ref})
    except (ValueError, TypeError) as exc:
        return _envelope_err(exc)
