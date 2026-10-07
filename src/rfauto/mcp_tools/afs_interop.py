"""afs_plan/read_hfss_touchstone_comments（M-3 AFS 计划 + ME-10' HFSS 注释直读）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 40. M-3 AFS 自适应频扫计划（afs_service 薄壳） ──────────────────────────
# 零逻辑转发 service/afs_service.afs_sweep_plan（纯计划面：不求解、不调
# evaluate）；数值只出确定性内核（规则 7，core/afs + core/fsv）。频带入参
# GHz（本仓用户面惯例），service 面口径 Hz（内核 skrf 口径），换算在本壳。


@mcp.tool
def afs_plan(
    f_min_ghz: float,
    f_max_ghz: float,
    tol: float = 1e-2,
    max_points: int = 96,
    n_init: int = 7,
    max_rounds: int = 12,
) -> dict[str, Any]:
    """AFS 频扫计划（afs 域）：频带 → 初始频点表+加密协议+验收判据。

    M-3 纯计划面（不求解不调 evaluate）。向量拟合（D13 skrf VF）驱动
    选频点、中点收敛即停的扫频前计划：生产侧先拿计划做求解预算，再经
    service.afs_service.afs_sweep 注入 evaluate 回调（f_hz ->
    {'s': complex|[re,im]}，每调用计一次求解）执行；不用于直接产出
    S 数据。参数非法 → ok=False（不抛出）如实。只读无时序约束。

    Args:
        f_min_ghz: 频带下端 (GHz)
        f_max_ghz: 频带上端 (GHz)，须 > f_min_ghz
        tol: 中点收敛容差（线性复幅差，None/缺省 1e-2 落内核缺省）
        max_points: 采样点上限（终止保护，>= n_init）
        n_init: 初始均匀采样点数（>= 3）
        max_rounds: 加密轮数上限

    Returns:
        dict: {ok, plan: {band_hz, initial_frequencies_hz, order_ladder,
        protocol, acceptance_criteria, evaluate_contract}}；参数非法
        ok=False（不抛出）
    """
    from rfauto.service.afs_service import afs_sweep_plan
    try:
        return afs_sweep_plan(
            [float(f_min_ghz) * 1e9, float(f_max_ghz) * 1e9],
            tol, max_points, n_init=n_init, max_rounds=max_rounds)
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}


# ─── 41. ME-10' HFSS Touchstone 注释块直读（interop_service 薄壳） ───────────
# 零逻辑转发 service/interop_service.hfss_touchstone_comments →
# adapters/touchstone_interop.read_hfss_touchstone_comments（KJ-P2 模态基
# 直读抓手：! Gamma 传播常数 + ! Port Impedance（Zpi 口径，#254）。


@mcp.tool
def read_hfss_touchstone_comments(path: str) -> dict[str, Any]:
    """HFSS Touchstone 注释直读（afs 域）：.sNp 路径 → Gamma/Zpi 注释块。

    ME-10'。解析 HFSS ExportNetworkData 逐频点注释行：``! Gamma``（γ=α+jβ，
    Np/m、rad/m——不是反射系数）与 ``! Port Impedance``（恒为 Zpi 口径，
    不按 CharImp 写出，#254）；另含重归一旗标/端口名/Key:Value 头部元数据/
    注释行原文。行序即频率序；本工具不读 S 数据（skrf 负责），不用于
    S 参数解析。文件不存在/注释块结构矛盾 ok=False（#316 方向显式报）。
    只读无时序约束。

    Args:
        path: HFSS 导出的 .sNp 文件路径

    Returns:
        dict: {ok, data: {n_ports, n_freqs, port_zpi, gamma（复数 JSON 化
        [[re,im],...]）, renormalized, renormalize_ohm, port_names, header,
        raw}}；文件不存在/注释块结构矛盾 ok=False（#316 方向显式报）
    """
    from rfauto.service.interop_service import hfss_touchstone_comments
    try:
        return hfss_touchstone_comments(path)
    except (TypeError, ValueError, OSError) as e:
        return {"ok": False, "error": str(e)}
