"""cm_diagnose_q/cm_extract_refine/cm_cat_critique/correlate_measurement（耦合矩阵诊断与测量相关）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp
from rfauto.service.envelope import error_envelope, ok_envelope

# ─── 9c. CM 诊断三件套 (DP-2) ─────────────────────────────────────────────────

@mcp.tool
def cm_diagnose_q(
    network_path: str | None = None,
    freq_ghz: list[float] | None = None,
    s11: list | None = None,
    f0_hint_ghz: float | None = None,
    q_e: list[float] | None = None,
) -> dict[str, Any]:
    """单腔 Q 诊断（cm 域）：S11 → VF 极点 × Kajfez 圆拟合互证+skrf 仲裁。

    DP-2。只读输入零副作用；互证 |ΔQu|/Qu≤10% → AGREE，超阈 UNDECIDABLE
    如实（不凑 AGREE），三方极差 ≤15% 并报。数据缺失/非法 → ok=False
    error 信封。只读无时序约束。

    Args:
        network_path: Touchstone 路径（.s1p/.s2p；与 freq_ghz+s11 二选一）
        freq_ghz: 频率轴 GHz（直接给数据时必填）
        s11: 复 S11 [re,im] 对列表
        f0_hint_ghz: 谐振频率提示 GHz
        q_e: 外部 Q 列表（给定时输出 Q_unloaded）

    Returns:
        dict: {ok, result: {vf, circle, verdict, cross_diff_pct, third_opinion}}
    """
    from rfauto.service.diagnosis_service import diagnose_q
    try:
        return diagnose_q({"touchstone_path": network_path,
                           "freq_ghz": freq_ghz, "s11": s11,
                           "f0_hint_ghz": f0_hint_ghz, "q_e": q_e})
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def cm_extract_refine(
    network_path: str | None = None,
    freq_ghz: list[float] | None = None,
    s11: list | None = None,
    s21: list | None = None,
    order: int | None = None,
    f0_ghz: float | None = None,
    fbw: float | None = None,
    topology: str = "folded",
    target_matrix: list | None = None,
) -> dict[str, Any]:
    """耦合矩阵提取（cm 域）：S 参数 → VF 定阶+LM 拓扑精化（+目标偏差表）。

    DP-2。只读输入零副作用；不用于 Q 诊断（走 cm_diagnose_q）。目标
    逐元素偏差门 5%（给 target_matrix 才出）。数据缺失/非法 → ok=False
    error 信封如实。只读无时序约束。

    Args:
        network_path: 2 端口 Touchstone 路径（与 freq_ghz+s11+s21 二选一）
        freq_ghz: 频率轴 GHz
        s11: 复 S11 [re,im] 对列表
        s21: 复 S21 [re,im] 对列表
        order: 阶数（缺省=VF 自动判）
        f0_ghz: 中心频率提示 GHz
        fbw: 相对带宽提示
        topology: "folded"（缺省）| "arrow"
        target_matrix: 目标 (N+2)×(N+2) 矩阵（[re,im] 对嵌套列表；给定时输出偏差表）

    Returns:
        dict: {ok, result: {extract, refine, target_check?}}
    """
    from rfauto.service.diagnosis_service import diagnose_cm
    try:
        return diagnose_cm({"touchstone_path": network_path,
                            "freq_ghz": freq_ghz, "s11": s11, "s21": s21,
                            "order": order, "f0_ghz": f0_ghz, "fbw": fbw,
                            "topology": topology,
                            "target_matrix": target_matrix})
    except Exception as e:
        return {"ok": False, "error": str(e)}


@mcp.tool
def cm_cat_critique(
    freq_ghz: list[float],
    s21: list | None = None,
    s11: list | None = None,
    f0_ghz: float = 0.0,
    fbw: float = 0.0,
    target_matrix: list | None = None,
    current_params: dict | None = None,
    bounds: dict | None = None,
    tol: float = 0.1,
) -> dict[str, Any]:
    """Dishal 调谐 critique（cm 域）：τ(f) 峰数指纹+Qe/k 偏差 → typed fixes。

    DP-2。只读输入零副作用；C 系数钉死（S21 透射泄漏 C=2、S11 反射全通
    C=4，合成回收裁决）；k 拆分精确式 k=(f₂²−f₁²)/(f₂²+f₁²)。判据不凑绿，
    超容差如实 issues。非法输入 → ok=False error 信封。只读无时序约束。

    Args:
        freq_ghz: 频率轴 GHz
        s21: 复 S21 [re,im] 对列表（透射口径，与 s11 恰给其一）
        s11: 复 S11 [re,im] 对列表（反射口径）
        f0_ghz: 目标中心频率 GHz
        fbw: 相对带宽
        target_matrix: 目标 (N+2)×(N+2) 矩阵
        current_params: 当前可调参数 {name: value}
        bounds: 参数界 {name: [lo, hi]}
        tol: 相对容差（缺省 0.1）

    Returns:
        dict: {ok, result: {n_peaks, qe_measured?, k_measured?, issues, fixes, verdict}}
    """
    from rfauto.service.diagnosis_service import diagnose_cat
    try:
        return diagnose_cat({"freq_ghz": freq_ghz, "s21": s21, "s11": s11,
                             "f0_ghz": f0_ghz, "fbw": fbw,
                             "target_matrix": target_matrix,
                             "current_params": current_params,
                             "bounds": bounds, "tol": tol})
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── 10. correlate_measurement (E9c) ──────────────────────────────────────────

@mcp.tool
def correlate_measurement(
    sim_file: str,
    measured_file: str,
    threshold_db: float = 3.0,
) -> dict[str, Any]:
    """仿真 vs 测量相关性分析（measurement 域）：两份 .s2p → 相关性判定。

    不用于仿真间对拍；文件缺失/解析失败 → ok=False errors 信封不抛出。
    只读无时序约束。

    Args:
        sim_file: 仿真结果文件 (.s2p)
        measured_file: 测量数据文件 (.s2p)
        threshold_db: 偏差阈值 (dB)

    Returns:
        dict: {ok, data: {is_correlated, metrics, warnings}}；文件缺失
        或解析失败 → ok=False
    """
    from rfauto.measurement.correlate import compute_correlation
    from rfauto.measurement.import_data import import_touchstone
    try:
        sim = import_touchstone(sim_file)
        measured = import_touchstone(measured_file)
        result = compute_correlation(sim, measured, threshold_db)
        return ok_envelope(data=result.to_dict())
    except Exception as e:
        return error_envelope([str(e)])
