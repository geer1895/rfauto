"""render_constraint_check/import_solid_payload/certify_design/port_gate（ME-17a 认证/门族）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 35. df7+ R4 渲染前声明式几何约束（render_constraint_service 薄壳） ───────
# z3 缺装降级在 core 内完成（status="unavailable" 进 verdict 不抛出）；
# config 形状非法的 ValueError 在此收进 ok=False 信封（不炸会话）。

@mcp.tool
def render_constraint_check(config: dict[str, Any]) -> dict[str, Any]:
    """渲染前约束求解（certify 域）：声明式 config → UNSAT 冲突组+witness。

    R4（z3）。对渲染脚本的既有 if 链守卫做声明式前置检查（#266 缝格/
    #152 最小间距/#311 缝内线存在性/参数 bounds/NEAR=BASE/n 定义）；只读
    配置面零写副作用，不替代渲染期运行时守卫。数值只在确定性内核
    （规则 7）：全部数字出自 z3 求解（witness）或本 config 输入。z3 缺装
    → ok=False/status="unavailable" 如实；config 非法 → ok=False 信封。
    只读无时序约束。

    Args:
        config: 约束配置对象（键全部可选，缺项即不组装对应规则）：
            mesh_resolution_mm（float 钉值或 {low, high} 可取域）、
            near_ratio（缺省 4）、gaps_mm（缝宽列表取最小）或 min_gap_mm、
            gap_cells_min（缺省 3）、min_line_spacing_mm（缺省 1e-3）、
            mesh_lines_mm（{轴: [线位 mm]}，逐轴最小间距）、
            param_bounds（{变量: {low, high}}）、
            max_conflict_groups（缺省 8）

    Returns:
        dict: {ok, status, conflict_rule_ids, conflict_groups, rules,
        witness, near_mm, assembled, reason, solver}；z3 缺装时
        ok=False/status="unavailable"；config 非法 → ok=False/error 信封
    """
    from rfauto.service.render_constraint_service import evaluate_render_constraints
    try:
        return evaluate_render_constraints(config)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 36. ME-17a 接线批第一组（solid_import/certify_design/port_gate 三工具）──
# 零逻辑转发既有 service 面（规则 4）；数值只出确定性内核（规则 7）。
# runs_stats / tracking_export 属 CLI 消费面（`rfauto runs stats` /
# `rfauto runs export-tracking`），不进 MCP 最小面；port_gate 真机发射走
# 对象面（HfssPortDriver 注入），JSON 面只到合成回放（服务内如实 UNKNOWN
# 拒发 hfss 驱动）。

@mcp.tool
def import_solid_payload(path: str, material: str = "metal") -> dict[str, Any]:
    """STL 实体导入（certify 域）：STL 路径 → 解析+分类+CSX 载荷。

    只读文件零写副作用（B3）；STEP 等不支持格式如实拒绝不硬造（显式缺口
    登记面）。一切失败 ok=False 信封不抛出。只读无时序约束。

    Args:
        path: STL 文件路径（STEP 属显式缺口，服务如实拒绝不硬造）
        material: 分类材料标签（缺省 "metal"）

    Returns:
        dict: {ok, path, format, units, mesh{n_triangles, volume_mm3,
        bbox_mm, is_watertight, ...}, solids[{csx_args_m, csx_lines, ...}]}；
        失败 → {ok: False, error}
    """
    from rfauto.service.solid_import_service import import_solid_payload as _fn
    try:
        return _fn(path, material=material)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def certify_design(
    samples_path: str,
    params_center: dict[str, float],
    tolerance_pct: float = 0.02,
    n_grid: int = 9,
    kind: str = "poly_ridge",
) -> dict[str, Any]:
    """公差盒 → 指标区间证书（三值门面：逐目标 PASS/FAIL/UNKNOWN + 总 verdict）。

    确定性内核：代理模型拟合样本集后按 Lipschitz 有限差分
    保守界外推中心点指标区间；UNKNOWN=证据不足，如实不证明。

    Args:
        samples_path: 公差盒样本集 JSON（bounds/objectives/samples 同款
            schema；样本 ≥5 且带 objectives）
        params_center: 中心参数 {轴名: 值}（每轴必给）
        tolerance_pct: 每参数 ±公差（相对该轴 span 百分比，缺省 0.02）
        n_grid: Lipschitz 有限差分每轴网格数（缺省 9）
        kind: 代理模型类型（缺省 poly_ridge）

    Returns:
        dict: {ok, verdict: CERTIFIED|PARTIAL|FAIL, certificates[
            {metric, interval, verdict: PASS|FAIL|UNKNOWN, ...}],
            n_pass, n_fail, n_unknown, ...}；样本缺失/不足 → ok=False
    """
    from rfauto.service.certify_design import certify_design as _certify
    try:
        return _certify(samples_path, params_center,
                        tolerance_pct=tolerance_pct, n_grid=n_grid, kind=kind)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def port_gate(payload: dict[str, Any]) -> dict[str, Any]:
    """端口尺寸收敛前置门（DP-16 C4；JSON 进出合成回放面）。

    端口阶梯（微带 3/5/8×w、槽线 ±60/∓30mm 官方口径等）先于真机求解
    逐档换尺寸判敛，防 #191/#254 类端口尺寸错误浪费求解席位；真机发射
    走脚本对象注入面，JSON 面 hfss 驱动如实 UNKNOWN 拒发。

    Args:
        payload: JSON 进出 payload。driver="synthetic"（缺省）：合成序列
            回放——line_width_mm/substrate_h_mm/probe_freq_ghz 必给，
            z0_ohm_sequence/s21_db_sequence 序列必传，可选 template/
            physics_roles/family/l_ext_mm/full_sweep_final/max_rungs；
            driver="hfss"：不发射，返回 UNKNOWN。

    Returns:
        dict: {ok, gate: "port_size_convergence", verdict, rungs, ...}；
        payload 缺键/非法 → ok=False 信封不抛出
    """
    from rfauto.service.port_gate_service import port_gate_from_json
    try:
        return port_gate_from_json(payload)
    except (KeyError, TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}
