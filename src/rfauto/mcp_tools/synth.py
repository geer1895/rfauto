"""synthesize/synthesize_bpf/budget_analysis/cascade_budget/spur_search/if_plan_sweep（综合与系统级预算）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope

# ─── 服务器启动入口 ────────────────────────────────────────────────────────



# ─── 8. synthesize (E6a) ──────────────────────────────────────────────────────

@mcp.tool
def synthesize(
    z0_target: float,
    freq_ghz: float = 2.4,
    stackup: str = "rogers4350b_h0.508",
) -> dict[str, Any]:
    """微带线综合（synth 域）：目标阻抗+叠层 → 线宽（HJ 闭式反解）。

    skrf MLine (Hammerstad-Jensen) + brentq 反解；只读计算面无副作用，
    不用于全波验证（数值为闭式设计值）。非法阻抗/未知叠层 → ok=False
    errors 如实。只读无时序约束。

    Args:
        z0_target: 目标特性阻抗 (Ω)
        freq_ghz: 频率 (GHz)
        stackup: 层叠名称 (materials.yaml 键)

    Returns:
        dict: {ok, data: {width_mm, z0_actual, epsilon_eff, status,
        er_eff_source, skrf_version}}（XA-4：εeff 来源显式化 + skrf 版本入 meta）
    """
    from rfauto.core.synthesis import synthesize_mline
    try:
        result = synthesize_mline(z0_target, freq_ghz, stackup)
        return ok_envelope(data=result.to_dict())
    except Exception as e:
        return error_envelope([str(e)])


# ─── 8b. synthesize_bpf (C13 耦合矩阵综合) ────────────────────────────────────

@mcp.tool
def synthesize_bpf(
    order: int,
    f0_ghz: float,
    fbw: float,
    rl_db: float,
    transmission_zeros_ghz: list[float] | None = None,
    topology: str = "folded",
) -> dict[str, Any]:
    """BPF 耦合矩阵综合（synth 域）：N/f0/fbw/rl → Cameron N+2 矩阵。

    C13 广义切比雪夫 → folded/arrow 拓扑。确定性内核
    （core/synthesis.synthesize_bpf_model）：Y 留数法闭式横向矩阵 +
    复正交合同旋转拓扑约简，频响与原型多项式逐点一致；只读计算面
    无副作用，不用于物理尺寸综合。非法阶数/零点在通带 → ok=False
    errors 如实。只读无时序约束。

    Args:
        order: 阶数 N（≥1）
        f0_ghz: 中心频率 (GHz)
        fbw: 相对带宽 (0,1]
        rl_db: 带内回波损耗 (dB，>0)
        transmission_zeros_ghz: 传输零点频率列表 (GHz，须在阻带；±对口径)
        topology: folded | arrow

    Returns:
        dict: synthesize_bpf_model 的 JSON（ok/coupling_matrix/nominal/
        cross_family/response_max_err/pattern_residual/notes 或 errors）
    """
    from rfauto.core.synthesis import synthesize_bpf_model
    try:
        return synthesize_bpf_model(
            order=order, f0_ghz=f0_ghz, fbw=fbw, rl_db=rl_db,
            transmission_zeros_ghz=list(transmission_zeros_ghz or []),
            topology=topology)
    except Exception as e:
        return error_envelope([str(e)])


# ─── 9. budget_analysis (E8c) ─────────────────────────────────────────────────

@mcp.tool
def budget_analysis(
    chain: list[str],
    catalog: str = "parts/catalog.yaml",
) -> dict[str, Any]:
    """链路预算分析（link 域）：级联器件链 → Friis 级联增益/噪声系数表。

    不用于单器件参数提取；目录/器件名不存在 → ok=False errors 信封。
    只读无时序约束。

    Args:
        chain: 级联器件名列表（顺序=信号流向）
        catalog: 器件目录 YAML 路径

    Returns:
        dict: {ok, data: {cascade_gain_db, cascade_nf_db, stages}}；
        目录缺失或器件名未登记 → ok=False
    """
    from rfauto.core.block_spec import DeviceCatalog
    from rfauto.core.budget import LinkBudget
    try:
        dev_catalog = DeviceCatalog.from_yaml(catalog)
        budget = LinkBudget()
        for name in chain:
            spec = dev_catalog.get(name)
            budget.add_stage(
                name=name,
                gain_db=spec.gain_db or -(spec.conversion_loss_db or 0),
                nf_db=spec.nf_db or spec.conversion_loss_db or 0,
                p1db_dbm=spec.p1db_dbm,
                oip3_dbm=spec.oip3_dbm,
            )
        result = budget.compute()
        return ok_envelope(data=result.to_dict())
    except Exception as e:
        return error_envelope([str(e)])


# ─── 9b. cascade 预算/杂散/IF 规划 (DP-5) ─────────────────────────────────────

@mcp.tool
def cascade_budget(
    stages: list[dict],
    snr_min_db: float = 10.0,
    rx_power_dbm: float | None = None,
    bw_hz: float | None = None,
) -> dict[str, Any]:
    """级联预算（synth 域）：级表 → 增益/Friis NF/IIP3/P1dB/SFDR/灵敏度。

    DP-5。只读计算面无副作用；闭式级联口径（Friis/级联 IIP3），不用于
    非线性大信号仿真。级表非法 → ok=False error 信封如实。只读无时序
    约束。

    Args:
        stages: 级表（顺序=信号流向）。schema: {type: amp|mixer|filter|atten|cable,
                gain_db, nf_db?, iip3_dbm?, p1db_dbm?, bw_hz?, network_path?/il_db?}；
                filter/atten 插损来源=network_path（skrf 实取 S21，需配 il_freq_hz）
                或常数 il_db，显式二选一；无源级 NF 缺省=插损（T0）
        snr_min_db: 解调最小 SNR (dB)
        rx_power_dbm: 接收功率 (dBm)，给定时输出链路裕量
        bw_hz: 系统噪声带宽 (Hz)，缺省取末级 bw_hz

    Returns:
        dict: {ok, result: {gain_total_db, nf_total_db, iip3_total_dbm, sfdr_db, ...}}；
        级表非法 → ok=False error
    """
    from rfauto.service.cascade_service import cascade_budget_report
    try:
        report = cascade_budget_report(stages, snr_min_db=snr_min_db,
                                       rx_power_dbm=rx_power_dbm, bw_hz=bw_hz)
        return report
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def spur_search(
    f_rf_hz: float,
    f_lo_hz: float,
    if_center_hz: float | None = None,
    if_bw_hz: float = 0.0,
    rf_bw_hz: float = 0.0,
    max_order: int = 7,
) -> dict[str, Any]:
    """混频杂散搜索（synth 域）：f_RF/f_LO → |m·f_RF±n·f_LO| 落带判定表。

    DP-5。只读计算面无副作用；纯代数枚举+落带判定+危险等级，不用于
    杂散幅度预测。非法频率（非正） → ok=False error 信封如实。只读无
    时序约束。

    Args:
        f_rf_hz: RF 中心频率 (Hz)
        f_lo_hz: 本振频率 (Hz)
        if_center_hz: 目标 IF 中心 (Hz)，缺省 |f_RF−f_LO|
        if_bw_hz: 目标带宽 (Hz)
        rf_bw_hz: RF 信号带宽 (Hz)（谐波带宽线性缩放）
        max_order: 最大阶数 m+n（缺省 7）

    Returns:
        dict: {ok, result: {n_products, n_spurs_in_band, spurs: [...]}}；
        非法入参 → ok=False error
    """
    from rfauto.service.cascade_service import spur_search_report
    try:
        return spur_search_report(f_rf_hz, f_lo_hz, if_center_hz=if_center_hz,
                                  if_bw_hz=if_bw_hz, rf_bw_hz=rf_bw_hz,
                                  max_order=max_order)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def if_plan_sweep(
    f_rf_hz: float,
    if_lo_hz: float,
    if_hi_hz: float,
    side: str = "low",
    n_points: int = 201,
    if_bw_hz: float = 0.0,
    max_order: int = 7,
) -> dict[str, Any]:
    """IF 频率规划扫掠（synth 域）：候选 IF 逐点杂散判定 → spurious-free 窗。

    DP-5。只读计算面无副作用；逐点枚举口径同 spur_search，不用于杂散
    幅度预测。非法区间（low 侧 ≥ f_RF 等） → ok=False error 信封如实。
    只读无时序约束。

    Args:
        f_rf_hz: RF 中心频率 (Hz)
        if_lo_hz: IF 扫掠下限 (Hz)
        if_hi_hz: IF 扫掠上限 (Hz)（low 侧须 < f_rf_hz）
        side: 注入侧 "low"（f_LO=f_RF−IF）或 "high"（f_LO=f_RF+IF）
        n_points: 网格点数
        if_bw_hz: 目标带宽 (Hz)
        max_order: 最大阶数 m+n（缺省 7）

    Returns:
        dict: {ok, result: {points: [...], windows: [{start_hz, end_hz, n_points}]}}
    """
    from rfauto.service.cascade_service import if_plan_report
    try:
        return if_plan_report(f_rf_hz, if_lo_hz=if_lo_hz, if_hi_hz=if_hi_hz,
                              side=side, n_points=n_points, if_bw_hz=if_bw_hz,
                              max_order=max_order)
    except Exception as e:
        return {"ok": False, "error": str(e)}
