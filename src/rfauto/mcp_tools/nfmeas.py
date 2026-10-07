"""nfmeas_ffs_info/nfmeas_cut_view/nfc_coil_evaluate/nfc_coil_synthesize/nfc_coil_q/sar_analytic_plane_wave（nf 测量/NFC/SAR 族）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool()
def nfmeas_ffs_info(path: str) -> dict[str, Any]:
    """审计 HFSS .ffs 远场文件头（nfmeas 域）：路径 → 频率/三功率/轴序。

    无副作用只读；不读全量复矩阵（大文件安全）。文件缺失/格式非法
    → ok=False error 信封。只读无时序约束。

    Args:
        path: HFSS .ffs 远场文件路径

    Returns:
        dict: {ok, path, reader_version, n_freq, frequencies_hz,
        power_first_block, n_phi, n_theta, phi_deg_span, theta_deg_span,
        row_order, units_note}；文件不存在/解析失败 → ok=False error
    """
    from rfauto.service.nf_measurement_service import ffs_info
    return ffs_info(path)

@mcp.tool()
def nfmeas_cut_view(path: str, freq_index: int = 0, phi_deg: float | None = None,
                    theta_deg: float | None = None) -> dict[str, Any]:
    """.ffs 切面视图（nfmeas 域）：单频块 → 固定 φ 取 θ 扫描（或反之）。

    无副作用只读；幅度+归一 dB 切面，不用于远场指标判读（走
    farfield_view）。文件缺失/切角不在采样轴/phi 与 theta 缺一 →
    ok=False error 信封如实。只读无时序约束。

    Args:
        path: HFSS .ffs 远场文件路径
        freq_index: 单频块索引（缺省 0）
        phi_deg: 固定 φ 角（度，须在采样轴上；与 theta_deg 二选一）
        theta_deg: 固定 θ 角（度，须在采样轴上；与 phi_deg 二选一）

    Returns:
        dict: {ok, reader_version, freq_hz, cut, theta_deg|phi_deg（切向轴）,
        e_theta_amp, e_phi_amp, pattern_db, units_note}；切面不可取 →
        ok=False error
    """
    from rfauto.service.nf_measurement_service import ffs_cut_view
    return ffs_cut_view(path, freq_index=freq_index, phi_deg=phi_deg,
                        theta_deg=theta_deg)

@mcp.tool()
def nfc_coil_evaluate(shape: str, n_turns: float, d_out_mm: float,
                      w_um: float, s_um: float) -> dict[str, Any]:
    """NFC 平面螺旋电感评估（nfc 域）：几何 → Mohan 1999 电感闭式（H）。

    几何不可行显式报错不凑值；不用于版图寄生提取。单位 mm/µm 入参、
    H 回传（见 Args）。只读无时序约束。

    Args:
        shape: 线圈形状（"square" | "hexagonal" | "octagonal" | "circle"）
        n_turns: 圈数（正数）
        d_out_mm: 外径 (mm)
        w_um: 线宽 (µm)
        s_um: 线间距 (µm)

    Returns:
        dict: {ok, shape, n_turns, d_out_m, d_in_m, s_m, w_m, fill_ratio,
        l_h}；几何不可行 → ok=False error
    """
    from rfauto.service.nfc_coil_service import coil_evaluate
    return coil_evaluate(shape, n_turns, d_out_mm * 1e-3, w_um * 1e-6, s_um * 1e-6)

@mcp.tool()
def nfc_coil_synthesize(target_l_nh: float, shape: str, n_turns: float,
                        w_um: float, s_um: float,
                        expression: str = "current_sheet") -> dict[str, Any]:
    """NFC 线圈综合（nfc 域）：目标电感 → 外径二分反解（回代自洽 ≤1e-10）。

    几何不可行/表达式不适用显式报错；不用于 Q 评估（走 nfc_coil_q）。
    单位 nH 入参、H 内部解算。只读无时序约束。

    Args:
        target_l_nh: 目标电感 (nH)
        shape: 线圈形状（同 nfc_coil_evaluate 词表）
        n_turns: 圈数（正数）
        w_um: 线宽 (µm)
        s_um: 线间距 (µm)
        expression: Mohan 表达式档（缺省 "current_sheet"）

    Returns:
        dict: {ok, shape, n_turns, target_l_h, expression, d_out_m, d_in_m,
        s_m, w_m, l_back_h, rel_error}；不可行 → ok=False error
    """
    from rfauto.service.nfc_coil_service import coil_synthesize
    return coil_synthesize(target_l_nh * 1e-9, shape, n_turns, w_um * 1e-6,
                           s_um * 1e-6, expression=expression)

@mcp.tool()
def nfc_coil_q(f_mhz: float, l1_nh: float, r1_ohm: float, m_nh: float = 0.0,
               l2_nh: float = 0.0, r2_ohm: float = 0.0) -> dict[str, Any]:
    """NFC 线圈 Q 评估（nfc 域）：频率+线圈参数 → 有载/无载 Q（T 模型精确式）。

    R₁≤0 → Q 如实 None 不凑值；不用于电感综合（走 nfc_coil_synthesize）。
    参数非法 → ok=False。单位 MHz/nH/Ω 入参。只读无时序约束。

    Args:
        f_mhz: 工作频率 (MHz)
        l1_nh: 初级电感 (nH)
        r1_ohm: 初级串联电阻 (Ω)
        m_nh: 互感 (nH；0=单线圈无载档)
        l2_nh: 次级电感 (nH；m_nh>0 时必填)
        r2_ohm: 次级串联电阻 (Ω；m_nh>0 时必填)

    Returns:
        dict: {ok, f_hz, model, q_loaded, q_unloaded, z_in_ohm,
        z_reflected_ohm}；R₁≤0 → q 如实 None
    """
    from rfauto.service.nfc_coil_service import coil_q
    return coil_q(f_mhz * 1e6, l1_nh * 1e-9, r1_ohm, m_nh * 1e-9,
                  l2_nh * 1e-9, r2_ohm)

@mcp.tool()
def sar_analytic_plane_wave(freq_mhz: float, e0_v_per_m: float,
                            sigma_s_per_m: float, epsilon_r: float,
                            rho_kg_m3: float,
                            depth_mm: list[float]) -> dict[str, Any]:
    """平面波 SAR 闭式对照（sar 域）：组织参数+深度 → 随深衰减谱（判据锚）。

    闭式对照面非人体模型；不用于合规判定，只作引擎/合成链判据锚。
    参数非法 → 异常如实上报。单位 MHz/V/m/S/m/kg·m⁻³/mm 入参。只读无时序约束。

    Args:
        freq_mhz: 频率 (MHz)
        e0_v_per_m: 平面波场强 (V/m)
        sigma_s_per_m: 组织电导率 (S/m)
        epsilon_r: 相对介电常数（无量纲）
        rho_kg_m3: 组织密度 (kg/m³)
        depth_mm: 深度采样点列表 (mm)

    Returns:
        dict: {ok, alpha_np_per_m, tan_delta, sar_w_per_kg, depth_m,
        cube_side_m, note}；参数非法 → 异常信封如实
    """
    from rfauto.service.sar_service import sar_analytic_plane_wave
    return sar_analytic_plane_wave(freq_mhz * 1e6, e0_v_per_m, sigma_s_per_m,
                                   epsilon_r, rho_kg_m3,
                                   [d * 1e-3 for d in depth_mm])
