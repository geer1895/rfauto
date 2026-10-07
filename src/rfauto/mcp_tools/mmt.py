"""mmt_solve/compose_netlist（DP-1 MMT 段表求解 + 网表组合）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 32. DP-1 MMT 秒级段表求解（mmt_service 薄壳） ────────────────────────────

@mcp.tool
def mmt_solve(
    sections: list[dict[str, Any]],
    freqs_ghz: list[float] | None = None,
    eps_r: float = 1.0,
    tan_d: float = 0.0,
    sigma_s_m: float | None = None,
    mode_policy: dict[str, Any] | None = None,
    z0_ref: float = 50.0,
    freq_start_ghz: float | None = None,
    freq_stop_ghz: float | None = None,
    n_freq: int = 41,
    work_dir: str | None = None,
) -> dict[str, Any]:
    """MMT 段表求解（mmt 域）：RWG/SIW 段表 → GSM 级联 S 参数（秒级）。

    DP-1。零外部进程/license；不替代全波仿真（膜片/阶梯绝对 S 值
    UNDECIDABLE 待 HFSS 仲裁）。段表三型（mm 口径）：uniform（a_mm/b_mm/
    length_mm）、hstep（a_left_mm/b_left_mm/a_right_mm/b_right_mm，缺省
    几何居中）、iris（a_mm/b_mm/aperture_mm/thickness_mm，零厚度=零长段
    三件级联）。SIW 膜片/阶梯的 w_eff 须由调用方经 siw_effective_width_mm
    折算后传入。

    undetermined 频点（近截止/过传）S=null 不外推（随信封
    absolute_s_note）；非法段表 → ok=False 信封如实。只读计算面
    （产物只落 work_dir），无时序约束。

    Args:
        sections: 段表列表（mm 口径三型，见上）
        freqs_ghz: 显式频点网格 GHz（≥2 点严格递增；与 start/stop 二选一）
        eps_r: 顶层缺省相对介电常数（段内可覆盖）
        tan_d: 顶层缺省损耗正切
        sigma_s_m: 顶层缺省导体电导率 S/m（None=PEC 壁）
        mode_policy: 模式数策略（n_modes_ref/n_modes_max/n_doublings_max 等）
        z0_ref: 端口参考阻抗 Ω（缺省 50）
        freq_start_ghz: 均匀网格起点（freqs_ghz 缺省时用）
        freq_stop_ghz: 均匀网格终点
        n_freq: 均匀网格点数（缺省 41）
        work_dir: 产物目录（缺省临时目录；写 sparams.csv/mmt.s2p/mmt_meta.json）

    Returns:
        dict: {ok, freqs_ghz, s11/s21/s12/s22, z_pv_ports, beta_te10_ports,
        converged, warnings, undetermined_freqs_ghz, artifacts, ...}
    """
    from rfauto.service.mmt_service import solve_mmt

    payload: dict[str, Any] = {
        "sections": sections,
        "eps_r": eps_r,
        "tan_d": tan_d,
        "z0_ref": z0_ref,
        "n_freq": n_freq,
    }
    if freqs_ghz is not None:
        payload["freqs_ghz"] = freqs_ghz
    if sigma_s_m is not None:
        payload["sigma_s_m"] = sigma_s_m
    if mode_policy is not None:
        payload["mode_policy"] = mode_policy
    if freq_start_ghz is not None:
        payload["freq_start_ghz"] = freq_start_ghz
    if freq_stop_ghz is not None:
        payload["freq_stop_ghz"] = freq_stop_ghz
    return solve_mmt(payload, work_dir=work_dir)


@mcp.tool
def compose_netlist(netlist: dict, out_dir: str | None = None) -> dict[str, Any]:
    """模板几何组合（mmt 域）：rfauto-netlist-v1 三段式 → simulation.py。

    DP-8 布局合并路线；netlist schema 由 compose_service 模块头单源定义。
    非法 netlist/写盘失败 → ok=False error 信封如实。时序：产物走既有
    渲染管线消费。

    Args:
        netlist: rfauto-netlist-v1 三段式 netlist（schema 详见
            service/compose_service.py 模块头；instances/connections/
            exposed_ports 三段式）
        out_dir: 产物目录（None=runs/compose_<ts>）

    Returns:
        dict: {ok, out_dir, simulation_py, compose_meta, netlist_yaml, ...}
    """
    from rfauto.service.compose_service import compose_from_netlist, compose_write
    try:
        if out_dir:
            return compose_write(netlist, out_dir)
        return compose_from_netlist(netlist)
    except Exception as e:
        return {"ok": False, "error": str(e)}
