"""farfield_runs/farfield_view/kicad_extract/kicad_optimize_cpw（WP4.1 nf2ff + B6 KiCad）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 25. 远场（WP4.1 nf2ff，0bu③ 薄壳） ──────────────────────────────────────

@mcp.tool
def farfield_runs(limit: int = 50) -> dict[str, Any]:
    """远场 run 清单（farfield 域）：扫描 → 含 nf2ff/SAR 产物 run 候选表。

    无副作用，可安全调用；只列候选不读远场数据（视图走 farfield_view）。
    纯清单面恒 ok=True（无 ok=False 分支），零命中如实回空清单。
    只读无时序约束。

    Args:
        limit: 返回条数上限

    Returns:
        dict: {ok, runs: [{run_id, ...}]}
    """
    from rfauto.service.nf2ff_service import farfield_runs as _runs
    return _runs(limit=limit)


@mcp.tool
def farfield_view(run_id: str) -> dict[str, Any]:
    """远场视图（farfield 域）：run id → φ 切面 θ-dB 序列+Dmax/效率/SAR。

    无副作用，可安全调用；数值全部出自 core/farfield 确定性解析，不用于
    无 nf2ff 产物的 run（缺产物 → ok=False errors 如实）。只读无时序约束。

    Args:
        run_id: 含 nf2ff 产物的 run ID

    Returns:
        dict: {ok, run_id, cuts, metrics, sar, ...} 或 {ok: False, errors}
    """
    from rfauto.service.nf2ff_service import farfield_view as _view
    return _view(run_id)


# ─── 26. KiCad PCB→EM（B6 stage-2，0cb① 薄壳） ───────────────────────────────

@mcp.tool
def kicad_extract(pcb_path: str, kicad_python: str | None = None) -> dict[str, Any]:
    """PCB 事实提取（kicad 域）：.kicad_pcb → 叠层/走线/过孔/板框/zone 表。

    无写副作用（只读板文件；KiCad 自带 Python 3.11 子进程，ABI 隔离）；
    不用于修改板文件。解释器缺失/板文件非法 → ok=False 如实。时序：子进程
    调用完成后即释放，无常驻句柄。

    Args:
        pcb_path: .kicad_pcb 路径
        kicad_python: KiCad Python 可执行文件（显式参 > env
            RFAUTO_KICAD_PYTHON > adapters/kicad_extract 的 KICAD_PYTHON
            缺省常量；路径不存在时报 ok=False）

    Returns:
        dict: {ok, board, traces, vias, outline, zones, footprints}
    """
    from rfauto.service.kicad_em_service import extract_pcb_facts
    return extract_pcb_facts(pcb_path, kicad_python=kicad_python)


@mcp.tool
def kicad_optimize_cpw(
    pcb_path: str,
    target_z0_ohm: float | None = None,
    freq_ghz: float | None = None,
    z0_tol_ohm: float | None = None,
) -> dict[str, Any]:
    """CPWG 寻优环（kicad 域）：PCB 提取 → 闭式代理调宽（|z0−target|≤tol）。

    无写副作用（FAIL 附修正 w* 不直接改板）；数值只出自 core 闭式内核
    （_cpwg_ri + synthesize_cpw_model），不用于全波验证替代。板提取失败
    → ok=False 如实。只读无时序约束。

    Args:
        pcb_path: .kicad_pcb 路径
        target_z0_ohm: 目标阻抗 Ω（缺省 50）
        freq_ghz: 工作频率 GHz（缺省 2.5）
        z0_tol_ohm: 判据容差 Ω（缺省 2）

    Returns:
        dict: {ok, design, analysis, optimization, verdict, recipe_draft}
    """
    from rfauto.service.kicad_em_service import optimize_cpw_from_pcb
    return optimize_cpw_from_pcb(pcb_path, target_z0_ohm=target_z0_ohm,
                                 freq_ghz=freq_ghz, z0_tol_ohm=z0_tol_ohm)
