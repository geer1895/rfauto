"""metasurface_coding_pattern/metasurface_quant_loss_db（编码超表面域薄壳）。

W7 台账①态接线批 X3（2026-10-04）：零逻辑转发 metasurface_service——
零消费内核 core/coding_metasurface（MM-2，Cui 2014 权面 2D DFT 口径）
的查询面。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool()
def metasurface_coding_pattern(
    code_matrix: list[list[int]],
    bits: int,
    period_um: float,
    f0_ghz: float,
    pad: int = 4,
    normalize: bool = True,
) -> dict[str, Any]:
    """编码超表面方向图（metasurface 域）：码矩阵 → 远场摘要（2D DFT 权面）。

    Cui 2014 权面 e^{jφ} 零填充 2D DFT 口径；只读无副作用，不用于单元级
    电磁仿真（纯谱域摘要面）。非法入参 → ok=False + errors 如实。
    只读无时序约束。

    Args:
        code_matrix: (M, N) 整数码矩阵，码值 ∈ [0, 2^bits)
        bits: 量化位数 b（相位栅格 2π/2^b）
        period_um: 方形单元周期 d（µm，>0）
        f0_ghz: 设计频率 GHz（>0）
        pad: 零填充倍数（≥1，缺省 4；u/v 轴采样数 = pad·M / pad·N）
        normalize: True 时峰值归一（peak_abs=1）

    Returns:
        {ok, schema_version, result: {n_m, n_n, bits, spacing_lambda,
        u_peak, v_peak, peak_abs, peak_db, quant_loss_theory_db,
        u/v_axis 端点}, provenance}；非法入参 → ok=False + errors。
    """
    from rfauto.service.metasurface_service import coding_pattern_summary
    return coding_pattern_summary(
        code_matrix, bits, period_um * 1e-6, f0_ghz,
        pad=pad, normalize=normalize)


@mcp.tool()
def metasurface_quant_loss_db(
    n_elements: int,
    bits: int,
    u_beam: float,
    v_beam: float,
    period_um: float,
    f0_ghz: float,
    pad: int = 8,
) -> dict[str, Any]:
    """量化损失双报（metasurface 域）：bits/阵规模 → 理论 sinc²+实测峰比（dB）。

    理论 −10·log10(sinc²(1/2^b))：1/2/3-bit = 3.92/0.91/0.22 dB；实测为
    连续相位 vs 量化权面 |AF| 峰比（大阵 n≳64 + 非栅格驻点指向收敛理论）。
    只读无副作用，不用于单元量化电路建模。非法入参 → ok=False + errors
    如实。只读无时序约束。

    Args:
        n_elements: 方阵单元数 n（(n,n) 口径）
        bits: 量化位数 b（≥1）
        u_beam: 扫描波束指向 u（方向余弦 [-1, 1]）
        v_beam: 扫描波束指向 v（方向余弦 [-1, 1]）
        period_um: 单元周期 µm（>0）
        f0_ghz: 设计频率 GHz（>0）
        pad: 零填充倍数（≥1，缺省 8）

    Returns:
        {ok, schema_version, result: {bits, n_elements, loss_theory_db,
        loss_measured_db, delta_db}, provenance}；非法入参 → ok=False + errors。
    """
    from rfauto.service.metasurface_service import quant_loss_compute
    return quant_loss_compute(
        n_elements, bits, u_beam, v_beam, period_um * 1e-6, f0_ghz, pad=pad)
