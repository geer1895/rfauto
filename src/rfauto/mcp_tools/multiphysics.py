"""electrothermal_chain/parasitic_extract_rlc/topology_propose（WP4.4 电热/寄生/WP4.6 拓扑）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 27. 电-热 / 寄生（WP4.4a/4.4b，0br④/0bv③ 薄壳） ─────────────────────────

@mcp.tool
def electrothermal_chain(payload: dict[str, Any]) -> dict[str, Any]:
    """电-热-漂移链（multiphysics 域）：Wilkinson 损耗 → 温升 → S 失谐。

    WP4.4a。无副作用，纯确定性闭式（core/electrothermal）；闭式链面
    不替代电热协同仿真；payload 形状见 service/electrothermal_service
    模块文档（case/thermal/material/resonator/band）。未知/缺字段 →
    {ok: False, error} 显式报错。只读无时序约束。

    Args:
        payload: 电-热链输入（未知字段/缺字段显式报错）

    Returns:
        dict: {ok, chain: {power, thermal, material, drift, band}} 或 {ok: False, error}
    """
    from rfauto.service.electrothermal_service import run_wilkinson_electrothermal
    return run_wilkinson_electrothermal(payload)


@mcp.tool
def parasitic_extract_rlc(payload: dict[str, Any]) -> dict[str, Any]:
    """寄生 RLC 提取链（multiphysics 域）：pcell 几何 → DRC 门 → 闭式锚。

    WP4.4b（可选 Q3D 注入对比）。无副作用，纯确定性（core/parasitic +
    adapters/kicad_drc 几何规则）；闭式锚面不替代场提取器精算；payload
    形状见 service/parasitic_service 模块文档（pcb/substrate/...）。
    未知/缺字段/DRC 不过 → {ok: False, error|stage} 显式报错。
    只读无时序约束。

    Args:
        payload: 寄生提取链输入（未知字段/缺字段显式报错）

    Returns:
        dict: {ok, chain: {geometry, drc, anchor, q3d}} 或 {ok: False, error|stage}
    """
    from rfauto.service.parasitic_service import extract_interconnect_rlc
    return extract_interconnect_rlc(payload)


# ─── 28. 生成式综合 E10（WP4.6，0by③ 薄壳） ──────────────────────────────────

@mcp.tool
def topology_propose(
    spec: dict[str, Any],
    proposer: str = "rule_based",
    campaign: bool = False,
    n_trials: int = 80,
    seed: int = 20260914,
    sandbox_name: str | None = None,
    promote: bool = False,
) -> dict[str, Any]:
    """滤波器拓扑提议（multiphysics 域）：FilterSpec → typed 提议+初值。

    （可选小战役精算。）typed 提议面禁数值字段（数字全部出自综合链/
    裁判，铁律 7）；无真机副作用（电路裁判/几何审计离线秒级）；
    sandbox_name 给定时写沙箱草稿（runs/recipe_sandbox，不 promote）；
    promote=True（需 sandbox_name）时草稿继续走 L1 白名单/L2 模板离线
    试运行/L3 token 准入链迁 promoted/。不用于直接改工作区配方（走沙箱
    三层 Gate）。spec 非法/未知提议器 → {ok: False, error} 如实。

    Args:
        spec: FilterSpec 字段 {f0_ghz, fbw, rl_db, stop_rejection_db?, order_hint?, family_hint?}
        proposer: 提议器注册名（rule_based；llm 需注入不可经此入口）
        campaign: 是否跑小战役精算（仅 campaign_capable 家族）
        n_trials: 战役 TPE 试验数
        seed: 战役随机种子
        sandbox_name: 沙箱草稿名（缺省不落盘）
        promote: 草稿继续走三层 Gate 准入链（需 sandbox_name）

    Returns:
        dict: {ok, proposer, proposal, initial, campaign, sandbox, promote} 或 {ok: False, error}
    """
    from rfauto.service.topology_service import propose_topology
    return propose_topology(spec, proposer=proposer, campaign=campaign,
                            n_trials=n_trials, seed=seed, sandbox_name=sandbox_name,
                            promote=promote)
