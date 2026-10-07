"""Metasurface service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

W7 台账①态接线批 X3（2026-10-04）：承载零消费内核 core/coding_metasurface
（MM-2 深审 PASS：量化损失 sinc²/文献数字锚）的查询面——

- ``coding_pattern_summary``：编码矩阵 → 远场方向图摘要（峰位 (u,v)/
  峰值/量化损失理论档/轴范围；Cui 2014 权面 2D DFT 口径，方向图本体
  不回传——摘要面向 agent/预算消费，全网格走 core 面）；
- ``quant_loss_compute``：b-bit 相位量化峰值损失双报（理论
  ``metasurface_lut.quantization_loss_db`` 单源 + 梯度码实测
  ``coding_metasurface.quantization_loss_measured_db``，大小阵收敛锚
  ≤0.05 dB 由内核测试钉，本面不自证）。

信封纪律（同 emc_service）：入参校验错误收集进 ``errors: list[str]``，
内核 ValueError 同样转 ``ok=False``，绝不抛异常；数值只在确定性内核
（规则 7），本模块零物理公式。
"""

from __future__ import annotations

from functools import partial
from typing import Any

# F-13 批 2（W6-E）：_num 单源委托（partial 绑定 accept_str=False 保
# metasurface 严格 isinstance 语义；#116 旧副本删净）。
from rfauto.service._helpers import parse_num
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本
METASURFACE_SERVICE_SCHEMA_VERSION = "1.0"

#: 内核法源（provenance 透出）
_CODING_PROVENANCE = {
    "kernel": "rfauto.core.coding_metasurface",
    "sources": (
        "Cui et al., Light Sci. Appl. 3, e218 (2014)（编码面权面 2D DFT 口径）"
        "；量化损失=metasurface_lut.quantization_loss_db 单源（sinc²(1/2^b)）"
    ),
}


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(errors)


# _num 单源委托（F-13 批 2，W6-E）：functools.partial 绑定 accept_str=False
# 保严格 isinstance 语义（数字字符串拒收，SPECS §3.2 批 2 策略参）。
# 文案统一（已声明）：数字字符串/None 报错随单源（「缺失」/「必须是实数」），
# bool 报错随单源 bool 分支；ok=False 收敛语义逐位不变。
_num = partial(parse_num, accept_str=False)


def _validate_code_matrix_arg(
    code_matrix: Any, bits: Any, errors: list[str]
) -> tuple[list[list[int]] | None, int | None]:
    """编码矩阵/位数入参结构校验（值域校验在内核 validate_code_matrix）。"""
    if isinstance(bits, bool) or not isinstance(bits, int):
        errors.append(f"bits 必须是整数，实际 {bits!r}")
        bits_val = None
    else:
        bits_val = int(bits)
    if not isinstance(code_matrix, list) or not code_matrix or not all(
        isinstance(row, list) and row for row in code_matrix
    ):
        errors.append(
            f"code_matrix 必须是非空的二维数值列表，实际 {type(code_matrix).__name__}")
        return None, bits_val
    return code_matrix, bits_val


def coding_pattern_summary(
    code_matrix: list[list[int]],
    bits: int,
    period_m: float,
    f0_ghz: float,
    pad: int = 4,
    normalize: bool = True,
) -> dict[str, Any]:
    """编码面远场方向图摘要（零填充 2D DFT，方向图本体不回传）。

    Args:
        code_matrix: (M, N) 整数码矩阵，码值 ∈ [0, 2^bits)。
        bits: 量化位数 b（相位栅格 2π/2^b）。
        period_m: 方形单元周期 d（m，>0）。
        f0_ghz: 设计频率 GHz（>0）。
        pad: 零填充倍数（≥1；u/v 轴采样数 = pad·M / pad·N）。
        normalize: True 时方向图除以 max|AF|（峰值 1）。

    Returns:
        {"ok": True, "schema_version", "result"（n_m/n_n/bits/spacing_lambda/
        u_peak/v_peak/peak_abs/quant_loss_theory_db/u_axis/v_axis 端点）,
        "provenance"}；非法入参 → {"ok": False, "errors": [str]}。
    """
    import numpy as np

    from rfauto.core.coding_metasurface import (
        coding_scattering_pattern,
        pattern_db,
    )
    from rfauto.core.metasurface_lut import quantization_loss_db

    errors: list[str] = []
    codes, bits_val = _validate_code_matrix_arg(code_matrix, bits, errors)
    period_val = _num(period_m, "period_m", errors, positive=True)
    f0_val = _num(f0_ghz, "f0_ghz", errors, positive=True)
    if isinstance(pad, bool) or not isinstance(pad, int) or pad < 1:
        errors.append(f"pad 必须是 ≥1 整数，实际 {pad!r}")
    if errors:
        return _err(errors)
    try:
        pat = coding_scattering_pattern(
            codes, bits_val, period_val, f0_val, pad=pad, normalize=normalize)
        peak_ix = int(np.argmax(np.abs(pat.pattern)))
        iu, iv = divmod(peak_ix, pat.pattern.shape[1])
        result = {
            "n_m": int(pat.code_matrix.shape[0]),
            "n_n": int(pat.code_matrix.shape[1]),
            "bits": int(pat.bits),
            "spacing_lambda": float(pat.spacing_lambda),
            "u_peak": float(pat.u[iu]),
            "v_peak": float(pat.v[iv]),
            "peak_abs": float(np.abs(pat.pattern[iu, iv])),
            "quant_loss_theory_db": float(quantization_loss_db(int(pat.bits))),
            "u_axis_min": float(pat.u.min()),
            "u_axis_max": float(pat.u.max()),
            "v_axis_min": float(pat.v.min()),
            "v_axis_max": float(pat.v.max()),
            "normalized": bool(normalize),
        }
        # 峰位 dB 面仅供日志/人读（峰值 0 dB 归一口径；floor 同内核缺省）
        result["peak_db"] = float(pattern_db(pat)[iu, iv])
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=METASURFACE_SERVICE_SCHEMA_VERSION,
        result=result,
        provenance=dict(_CODING_PROVENANCE),
    )


def quant_loss_compute(
    n_elements: int,
    bits: int,
    u_beam: float,
    v_beam: float,
    period_m: float,
    f0_ghz: float,
    pad: int = 8,
) -> dict[str, Any]:
    """b-bit 相位量化峰值损失双报（理论单源 + 梯度码实测，dB 正值=损失）。

    理论 = −10·log10(sinc²(1/2^b))（1/2/3-bit = 3.92/0.91/0.22 dB）；
    实测 = 连续相位 vs 量化权面的 |AF| 峰比（大阵 n≳64 + 非栅格驻点指向
    收敛到理论，误差 O(1/n)——内核测试锚）。

    Returns:
        {"ok": True, "schema_version", "result"（bits/loss_theory_db/
        loss_measured_db/delta_db/n_elements）, "provenance"}；
        非法入参 → {"ok": False, "errors": [str]}。
    """
    from rfauto.core.coding_metasurface import quantization_loss_measured_db
    from rfauto.core.metasurface_lut import quantization_loss_db

    errors: list[str] = []
    if isinstance(n_elements, bool) or not isinstance(n_elements, int) or n_elements < 1:
        errors.append(f"n_elements 必须是 ≥1 整数，实际 {n_elements!r}")
    if isinstance(bits, bool) or not isinstance(bits, int) or bits < 1:
        errors.append(f"bits 必须是 ≥1 整数，实际 {bits!r}")
    u_val = _num(u_beam, "u_beam", errors)
    v_val = _num(v_beam, "v_beam", errors)
    period_val = _num(period_m, "period_m", errors, positive=True)
    f0_val = _num(f0_ghz, "f0_ghz", errors, positive=True)
    if isinstance(pad, bool) or not isinstance(pad, int) or pad < 1:
        errors.append(f"pad 必须是 ≥1 整数，实际 {pad!r}")
    if errors:
        return _err(errors)
    try:
        theory = float(quantization_loss_db(bits))
        measured = float(
            quantization_loss_measured_db(
                n_elements, bits, u_val, v_val, period_val, f0_val, pad=pad))
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=METASURFACE_SERVICE_SCHEMA_VERSION,
        result={
            "bits": int(bits),
            "n_elements": int(n_elements),
            "u_beam": float(u_val),
            "v_beam": float(v_val),
            "loss_theory_db": theory,
            "loss_measured_db": measured,
            "delta_db": measured - theory,
        },
        provenance=dict(_CODING_PROVENANCE),
    )
