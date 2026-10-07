"""emc_cispr_band_params/emc_cispr_detect/emc_ground_spacing_check/emc_cm_radiated_budget（EMC 域薄壳）。

W7 台账①态接线批 X3（2026-10-04）：零逻辑转发 emc_service——零消费内核
core/cispr_detector（CISPR 16-1-1 三检波器）与 core/common_mode（接地
拓扑 λ/20 判据 + 浮地-机壳 CM 辐射预算）的查询面。
"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool()
def emc_cispr_band_params(band: str) -> dict[str, Any]:
    """CISPR 检波器参数表（emc 域）：Band A/B/C/D → 16-1-1 Table 1 四参数。

    只读常表查询无副作用；verbatim 口径不插值，不用于实测读数（走
    emc_cispr_detect）。非法 band → ok=False + errors 如实。只读无时序
    约束。

    Args:
        band: 频段键（"A"/"B"/"C"/"D"）

    Returns:
        {ok, schema_version, result: {band, f_min_hz, f_max_hz, bw6_hz,
        tau_charge_s, tau_discharge_s, tau_meter_s, overload_*_db, source,
        definition}, provenance}；非法 band → ok=False + errors。
    """
    from rfauto.service.emc_service import cispr_band_params
    return cispr_band_params(band)


@mcp.tool()
def emc_cispr_detect(
    samples: list[float],
    fs_mhz: float,
    band: str,
    f_center_mhz: float | None = None,
    unit_dbuv_ref: float | None = None,
) -> dict[str, Any]:
    """CISPR 三检波器读数（emc 域）：时域波形 → Peak/QP/Avg dBµV。

    CISPR 16-1-1。链路：6 dB 带宽等效滤波 → 解析包络 → 一阶非对称 RC
    充放 → 二阶临界阻尼表头；读数口径与验证锚见内核 docstring（QP=表头
    稳态最大摆幅）；只读计算面无副作用，不用于辐射发射合规判定替代。
    非法入参（全零波形/采样率欠采） → ok=False + errors 如实。
    只读无时序约束。

    Args:
        samples: 实值时域波形（伏特，一维有限值，全零拒收）
        fs_mhz: 采样率 MHz（守卫 fs ≥ 4×B6 且 f_center±B6/2 ≤ fs/2）
        band: "A"/"B"/"C"/"D"
        f_center_mhz: 接收机调谐频率 MHz（None 时取 |FFT| 峰）
        unit_dbuv_ref: 线性→dBµV 偏移（None=输入为伏特，+120）

    Returns:
        {ok, schema_version, result: {peak_dbuv, qp_dbuv, avg_dbuv,
        qp_settling_ok, band, f_center_hz, bw6_hz, ...}, provenance}；
        非法入参 → ok=False + errors。
    """
    from rfauto.service.emc_service import cispr_detect_compute
    return cispr_detect_compute(
        samples,
        fs_mhz * 1e6,
        band,
        f_center_hz=None if f_center_mhz is None else f_center_mhz * 1e6,
        unit_dbuv_ref=unit_dbuv_ref,
    )


@mcp.tool()
def emc_ground_spacing_check(spacing_mm: float, f_mhz: float) -> dict[str, Any]:
    """接地间距判据（emc 域）：间距/频率 → λ/20 等电位判据（Ott/Paul）。

    s < λ/20 → equipotential（等电位）；s ≥ λ/20 → electrically_long
    （地结构电长化，按 CM 辐射预算路径评估）。只读计算面无副作用；
    闭式判据面不替代辐射实测。非法入参（非正间距/频率） → ok=False
    errors 如实。只读无时序约束。

    Args:
        spacing_mm: 接地点/绑接间距 mm（>0）
        f_mhz: 关注频率 MHz（>0）

    Returns:
        {ok, schema_version, result: {spacing_over_lambda20, lambda20_m,
        wavelength_m, critical_f_mhz, verdict, notes}, provenance}。
    """
    from rfauto.service.emc_service import ground_spacing_check
    return ground_spacing_check(spacing_mm * 1e-3, f_mhz)


@mcp.tool()
def emc_cm_radiated_budget(
    f_mhz: float,
    length_m: float,
    distance_m: float,
    v_cm_v: float,
    c_pf: float | None = None,
    coupling_area_cm2: float | None = None,
    coupling_distance_mm: float | None = None,
    l_path_nh: float = 0.0,
    r_path_ohm: float = 0.0,
    er: float = 1.0,
    with_ground_image: bool = True,
) -> dict[str, Any]:
    """CM 辐射预算（emc 域）：浮地-机壳耦合电容 → I_CM → Ott 辐射场。

    电容来源二选一：c_pf 直给，或 coupling_area_cm2 + coupling_distance_mm
    （+er）平行板闭式估计；同给 → ok=False（单一事实来源）。I_CM 喂
    emc_radiated Ott 短偶极链（镜像/偶极上限/限值面全复用）；只读计算面
    无副作用，闭式预算面不替代合规实测。非法入参 → ok=False + errors
    如实。只读无时序约束。

    Args:
        f_mhz: 频率 MHz（≥0；0 → I=0 浮地隔直恒等）
        length_m: CM 电缆长度 m（>0）
        distance_m: 测量距离 m（>0）
        v_cm_v: 浮地-机壳 CM 电压源 V（≥0）
        c_pf: 耦合电容 pF（与 area/distance 二选一）
        coupling_area_cm2: 平行板正对面积 cm²（与 c_pf 二选一）
        coupling_distance_mm: 平行板间距 mm（area 给时必给）
        l_path_nh: CM 回路路径电感 nH（≥0）
        r_path_ohm: CM 回路电阻 Ω（≥0；谐振点须非零）
        er: 平行板相对介电常数（≥1，缺省空气 1.0）
        with_ground_image: 理想地平面镜像 ×2

    Returns:
        {ok, schema_version, result: {floating_ground: {c_f, i_cm_ua,
        dual_path_diff_db, resonance_f_mhz, ...}, radiated: {...}},
        provenance}；非法入参 → ok=False + errors。
    """
    from rfauto.service.emc_service import cm_radiated_budget_compute
    return cm_radiated_budget_compute(
        f_mhz, length_m, distance_m, v_cm_v,
        c_f=None if c_pf is None else c_pf * 1e-12,
        coupling_area_m2=None if coupling_area_cm2 is None
        else coupling_area_cm2 * 1e-4,
        coupling_distance_m=None if coupling_distance_mm is None
        else coupling_distance_mm * 1e-3,
        l_path_h=l_path_nh * 1e-9,
        r_path_ohm=r_path_ohm,
        er=er,
        with_ground_image=with_ground_image,
    )
