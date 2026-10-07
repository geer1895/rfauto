"""slotline_analysis/slotline_synthesis/msl_slot_transition_design/marchand_balun_design/marchand_two_section_synthesis（W2⑨ 槽线族）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 35. 槽线与过渡薄壳（W2⑨ slotline / transitions） ─────────────────────────
# 五工具零逻辑转发 service/slotline_service（规则 4）；数值只出确定性内核
# （铁律 7：core/slotline Janaswamy–Schaubert 闭式、core/slotline_transitions
# Roberts/Knorr 过渡 + Marchand 两节耦合段电路级综合）；越有效域拒绝进
# {ok: False, error} 信封不外推；realizable=False 是合法结果非错误（#122）。

@mcp.tool
def slotline_analysis(w_mm: float, h_mm: float, epsilon_r: float,
                      freq_ghz: float) -> dict[str, Any]:
    """槽线（slotline）闭式分析：Janaswamy–Schaubert 1986 分段拟合 (w, h, εr, f) →
    λ'/λ0、εeff、β、Z0（功率-电压定义）、槽波长 λ'。

    无副作用，可安全调用。有效域 0.006≤d/λ0≤0.06、窄槽段 0.0015≤W/λ0≤0.075、
    εr∈[2.22,9.8] 两段；越域 ok=False 显式拒绝不外推（宽槽段/高 εr 段未实现）。

    Args:
        w_mm: 槽宽 mm（金属面上的缝）
        h_mm: 基板厚 mm（单面金属、基板下为空气）
        epsilon_r: 基板相对介电常数（2.22–3.8 / 3.8–9.8 两段拟合）
        freq_ghz: 频率 GHz（W/λ0、d/λ0 进入拟合式，必需）

    Returns:
        dict: {ok, result: {z0_ohm, eps_eff, lambda_ratio, beta_rad_m, lambda_g_mm,
               segment, w_over_lambda0, d_over_lambda0}} 或 {ok: False, error}
    """
    from rfauto.service.slotline_service import slotline_analysis as _analysis
    return _analysis(w_mm, h_mm, epsilon_r, freq_ghz)


@mcp.tool
def slotline_synthesis(z0_ohm: float, h_mm: float, epsilon_r: float,
                       freq_ghz: float) -> dict[str, Any]:
    """槽线（slotline）综合：目标 Z0 → 槽宽 w（窄槽段括号 brentq 反解 + 闭式回代自洽）。

    无副作用，可安全调用。目标超窄槽段可达范围 = 合法结果 realizable=False
    （ok=True + reason 含可达范围，与 marchand 两节语义统一）；基板/频率越域
    等参数非法仍 ok=False 显式拒绝（error 含域信息）。

    Args:
        z0_ohm: 目标特性阻抗 Ω（功率-电压定义）
        h_mm: 基板厚 mm
        epsilon_r: 基板相对介电常数
        freq_ghz: 频率 GHz

    Returns:
        dict: {ok, realizable, result: {w_mm, z0_actual_ohm, eps_eff,
               lambda_ratio, beta_rad_m, lambda_g_mm, segment}}；
               不可达 = {ok: True, realizable: False, reason}；非法 = {ok: False, error}
    """
    from rfauto.service.slotline_service import slotline_synthesis as _synthesis
    return _synthesis(z0_ohm, h_mm, epsilon_r, freq_ghz)


@mcp.tool
def msl_slot_transition_design(f0_ghz: float, h_mm: float, er: float,
                               w_slot_mm: float, tan_d: float = 0.0037,
                               z_msl_target: float = 50.0) -> dict[str, Any]:
    """Roberts/Knorr MSL↔槽线过渡设计参数：微带 skrf HJ 综合 + 槽线闭式精算。

    无副作用，可安全调用。开路支节 l_stub=λg_m/4+Δl_open（Hammerstad 开路端修正）、
    槽线短路臂 l_short=λg'/4；越槽线有效域 ok=False 不外推。gates 为预声明过渡门
    （带内 max|S11|≤−10dB、f0 超额损耗 ≤1dB），供真机判读同源。

    Args:
        f0_ghz: 设计中心频率 GHz
        h_mm: 基板厚 mm
        er: 基板相对介电常数
        w_slot_mm: 槽宽 mm
        tan_d: 基板损耗角正切（默认 0.0037，RO4350B）
        z_msl_target: 微带馈线目标阻抗 Ω（默认 50）

    Returns:
        dict: {ok, design: {f0_ghz, w_slot_mm, h_mm, er, z_slot_ohm, eps_eff_slot,
               lambda_slot_mm, l_short_mm, w_msl_mm, z_msl_ohm, eps_eff_msl,
               l_stub_mm, dl_open_mm}, gates} 或 {ok: False, error}
    """
    from rfauto.service.slotline_service import msl_slot_transition_design as _design
    return _design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_target)


@mcp.tool
def marchand_balun_design(f0_ghz: float, h_mm: float, er: float,
                          w_slot_mm: float, tan_d: float = 0.0037,
                          z_msl_target: float = 50.0) -> dict[str, Any]:
    """Marchand 巴伦对照设计（slotline 域）：f0/叠层 → 过渡参数+槽距（最小族）。

    无副作用，可安全调用。两跨越点共享开路支节与两段 λg'/4 短路臂；a1/a2
    为槽内/外缘到中线距离。注意：该单支节串接族已被两引擎互证不满足巴伦
    四门，保留作对照几何**不用于产品化设计**；真
    Marchand 走 marchand_two_section_synthesis。越有效域 → {ok: False,
    error} 信封不外推；gates 为预声明巴伦门。只读无时序约束。

    Args:
        f0_ghz: 设计中心频率 GHz
        h_mm: 基板厚 mm
        er: 基板相对介电常数
        w_slot_mm: 槽宽 mm
        tan_d: 基板损耗角正切（默认 0.0037）
        z_msl_target: 微带馈线目标阻抗 Ω（默认 50）

    Returns:
        dict: {ok, design: {…过渡参数…, d_center_mm, a1_mm, a2_mm}, gates}
              或 {ok: False, error}
    """
    from rfauto.service.slotline_service import marchand_balun_design as _design
    return _design(f0_ghz, h_mm, er, w_slot_mm, tan_d, z_msl_target)


@mcp.tool
def marchand_two_section_synthesis(
    f0_ghz: float = 2.5,
    z_unbal_ohm: float = 50.0,
    z_bal_diff_ohm: float = 280.0,
    er: float = 3.66,
    h_mm: float = 1.524,
    tan_d: float = 0.0037,
    s_min_mm: float = 0.1,
    w_max_mm: float = 6.0,
    z_c_ohm: float | None = None,
    band_ghz: list[float] | None = None,
) -> dict[str, Any]:
    """两节对称 Marchand 巴伦电路级综合：f0 匹配闭式 → (Z0e,Z0o) → KJ 几何反解 (w,s)
    → 节长 λ/4 → 电路级 3 端口 S 自检门（确定性内核，无耗 TEM 理想耦合线）。

    无副作用，可安全调用（数十次 brentq，秒级）。匹配不变量 L_req=√(Z_s·Z_t/2)；
    z_c_ohm 缺省沿等 L 族自动扫描取首个满足 s≥s_min、w≤w_max 的可达点。
    **realizable=False 是合法结果**（边耦合微带不可达 → 钳位最近点 + 门如实），
    不进 error；参数非法/越域 ok=False。缺省名义点 50Ω→280Ω 差分 @RO4350B 60mil。

    Args:
        f0_ghz: 设计中心频率 GHz（默认 2.5）
        z_unbal_ohm: 不平衡端阻抗 Ω（默认 50）
        z_bal_diff_ohm: 平衡端差分阻抗 Ω（单端参考 Z_L/2；默认 280）
        er: 基板相对介电常数（默认 3.66）
        h_mm: 基板厚 mm（默认 1.524）
        tan_d: 基板损耗角正切（默认 0.0037）
        s_min_mm: 可制造最小耦合缝 mm（默认 0.1）
        w_max_mm: 耦合段线宽上限 mm（默认 6.0）
        z_c_ohm: 耦合段 Z_c=√(Z0e·Z0o) Ω（缺省 None 自动扫描）
        band_ghz: 自检带 [f_lo, f_hi] GHz（缺省 f0±10%）

    Returns:
        dict: {ok, design: {realizable, coupling, coupling_db, z0e_ohm, z0o_ohm,
               z0e_realized_ohm, z0o_realized_ohm, w_mm, s_mm, l_sect_mm, w_feed_mm,
               w_bal_line_mm, slot_balanced, model_metrics: {…, gates, all_gates_pass},
               notes, …}, nominal_params, gates} 或 {ok: False, error}
    """
    from rfauto.service.slotline_service import (
        marchand_two_section_synthesis as _synthesis,
    )
    return _synthesis(f0_ghz, z_unbal_ohm, z_bal_diff_ohm, er, h_mm, tan_d,
                      s_min_mm, w_max_mm, z_c_ohm, band_ghz)
