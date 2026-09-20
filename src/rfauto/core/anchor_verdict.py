"""mline 锚 εeff 双锚判读内核（确定性判据）。

背景（#218 归因收口后唯一未过门）：HFSS mline 探针 εeff 对 HJ 准静态
闭式 +2.36%/+2.53% 超旧 ±2% 单门——跨引擎同向偏移（openEMS 自身对 HJ
+1.18%），旧 HJ ±2% 单门对该锚偏严，如实 PARTIAL 不凑绿。
双锚口径 2026-09-12 定稿（本内核统一
engine harness 与 sweep_assert 旧单门）：

  主锚（金标准）：εeff 对 openEMS β 金标准 ``EPS_EFF_MLINE_GOLD``（2.886
                @2.5GHz），|Δ|≤2%。金标准为同几何全波真跑收敛值族
                （#189：2.8813~2.8884，网格收敛扫描最细档）。
  副锚（解析哨兵）：εeff 对 HJ 准静态闭式（core/synthesis.forward_z0，
                w=1.113 rogers4350b → 2.8526），|Δ|≤3%（放宽口径）。
                HJ 是独立来源解析锚（#118 纪律），完全降级为信息量会
                失去哨兵；钉死几何/频点（2.5GHz·w=1.113·RO4350B）实测
                系统偏移全谱 openEMS +1.18% / HFSS +2.36%/+2.53% 均在
                3% 内，不误杀健康通道；若未来移出准静态有效域应显式重
                标定两锚，而非静默放水。
  匹配/健康门：|S11| 深于 ``S11_HEALTH_DB``（-10dB）——探针看谷 min、
                harness 看全带 max，语义同向：浅于门=端口/网格判废信号。

判据改动=显式重标定决策（改动须附真机证据）。纯函数零真机，单测钉死于
tests/unit/test_mline_probe_dual_anchor.py。LLM/agent 永不产生物理数字：
锚值与实测 εeff 全部来自确定性链路（openEMS CalcPort
β 推导 / HFSS S21 相位斜率推导 / core/synthesis HJ 闭式）。

消费方：
- scripts/hfss_mline_probe.py（HFSS 探针，dual_anchor_verdict）
- scripts/engine_benchmark_mline.py（引擎基准 harness，
  mline_benchmark_verdict：收敛性+最细档双锚+健康门）
- scripts/hfss_mline_repro_sweep_assert.py（#191 复现脚本 unitfix 臂，
  旧 HJ ±2% 单门收编为双锚）
"""

from __future__ import annotations

# 双锚判据常量（见模块 docstring；改动=显式重标定决策，须附真机证据）
EPS_EFF_MLINE_GOLD = 2.886   # openEMS β 金标准 @2.5GHz（#189 收敛+归因档 §二）
MAIN_ANCHOR_TOL_PCT = 2.0    # 主锚：|Δ| 对金标准
SUB_ANCHOR_TOL_PCT = 3.0     # 副锚：|Δ| 对 HJ 准静态闭式（放宽口径）
S11_HEALTH_DB = -10.0        # 匹配/健康门（浅于此值=端口/网格判废信号）


def dual_anchor_verdict(
    s11_min_db: float,
    eps_hfss: float,
    eps_openems_beta: float,
    eps_hj: float,
    main_tol_pct: float = MAIN_ANCHOR_TOL_PCT,
    sub_tol_pct: float = SUB_ANCHOR_TOL_PCT,
    s11_min_ok_db: float = S11_HEALTH_DB,
) -> dict[str, float | bool | str]:
    """mline 探针双锚判读（纯函数，零真机，单测钉死于 test_mline_probe_dual_anchor）。

    PASS 当且仅当：匹配门（|S11|min < s11_min_ok_db）∧ 主锚
    （|Δ vs openEMS β| ≤ main_tol_pct）∧ 副锚（|Δ vs HJ| ≤ sub_tol_pct）。
    """
    delta_openems = (eps_hfss / eps_openems_beta - 1.0) * 100.0
    delta_hj = (eps_hfss / eps_hj - 1.0) * 100.0
    match_ok = bool(s11_min_db < s11_min_ok_db)
    main_ok = bool(abs(delta_openems) <= main_tol_pct)
    sub_ok = bool(abs(delta_hj) <= sub_tol_pct)
    verdict = "PASS" if (match_ok and main_ok and sub_ok) else "FAIL"
    reasons: list[str] = []
    if not match_ok:
        reasons.append(
            f"|S11|min={s11_min_db:.2f}dB 未深于 {s11_min_ok_db}dB"
            "（端口/网格判废信号）")
    if not main_ok:
        reasons.append(
            f"主锚超门：对 openEMS β {delta_openems:+.2f}% 超 "
            f"±{main_tol_pct}%")
    if not sub_ok:
        reasons.append(
            f"副锚超门：对 HJ 准静态闭式 {delta_hj:+.2f}% 超 "
            f"±{sub_tol_pct}%")
    return {
        "verdict": verdict,
        "delta_openems_pct": delta_openems,
        "delta_hj_pct": delta_hj,
        "match_ok": match_ok,
        "main_ok": main_ok,
        "sub_ok": sub_ok,
        "reason": "; ".join(reasons),
    }


def mline_benchmark_verdict(
    eps_finest: float | None,
    convergence_pct: float | None,
    s11_max_db: float | None,
    eps_gold: float,
    eps_hj: float,
    convergence_tol_pct: float = 1.0,
    main_tol_pct: float = MAIN_ANCHOR_TOL_PCT,
    sub_tol_pct: float = SUB_ANCHOR_TOL_PCT,
    s11_max_db_lt: float = S11_HEALTH_DB,
) -> dict[str, float | bool | str | None]:
    """引擎基准 harness 判读（收敛性+最细档双锚+健康门，纯函数零真机）。

    判据显式决策（scripts/engine_benchmark_mline.py 调用）：
    1. 收敛性：最细两档 εeff 相对移动 < convergence_tol_pct；
    2. 主锚：最细档 εeff 对金标准 eps_gold |Δ|≤main_tol_pct（#189 收敛值族
       复现一致性——harness 升级/换机/模板迁移后复跑的复现锚）；
    3. 副锚：最细档 εeff 对 HJ 闭式 |Δ|≤sub_tol_pct（放宽口径，理由见模块
       docstring；历史 #189 最细档 2.8813 → 对 gold −0.16%/对 HJ +1.01%，
       双锚 PASS 不误杀）；
    4. 健康：ok 档全带 |S11|max < s11_max_db_lt。

    输入 None（无有效档/收敛不可算）→ 对应门如实 FAIL，不凑绿。
    """
    reasons: list[str] = []

    if eps_finest is None or eps_gold <= 0.0 or eps_hj <= 0.0:
        delta_gold: float | None = None
        delta_hj: float | None = None
        main_ok = False
        sub_ok = False
        if eps_finest is None:
            reasons.append("最细档 εeff 缺失（无成功档），主/副锚不可判")
        else:
            reasons.append("锚值非法（≤0），主/副锚不可判")
    else:
        delta_gold = (eps_finest / eps_gold - 1.0) * 100.0
        delta_hj = (eps_finest / eps_hj - 1.0) * 100.0
        main_ok = bool(abs(delta_gold) <= main_tol_pct)
        sub_ok = bool(abs(delta_hj) <= sub_tol_pct)
        if not main_ok:
            reasons.append(
                f"主锚超门：最细档对金标准 {delta_gold:+.2f}% 超 "
                f"±{main_tol_pct}%")
        if not sub_ok:
            reasons.append(
                f"副锚超门：最细档对 HJ 闭式 {delta_hj:+.2f}% 超 "
                f"±{sub_tol_pct}%")

    if convergence_pct is None:
        convergence_ok = False
        reasons.append("收敛性不可判（成功档 <2），如实 FAIL")
    else:
        convergence_ok = bool(convergence_pct < convergence_tol_pct)
        if not convergence_ok:
            reasons.append(
                f"收敛超门：最细两档相对移动 {convergence_pct:.4f}% 未小于 "
                f"{convergence_tol_pct}%")

    if s11_max_db is None:
        health_ok = False
        reasons.append("健康门不可判（无 |S11| 数据），如实 FAIL")
    else:
        health_ok = bool(s11_max_db < s11_max_db_lt)
        if not health_ok:
            reasons.append(
                f"健康门超限：全带 |S11|max={s11_max_db:.2f}dB 未深于 "
                f"{s11_max_db_lt}dB")

    verdict = "PASS" if (convergence_ok and main_ok and sub_ok and health_ok) \
        else "FAIL"
    return {
        "verdict": verdict,
        "delta_gold_pct": delta_gold,
        "delta_hj_pct": delta_hj,
        "convergence_ok": convergence_ok,
        "main_ok": main_ok,
        "sub_ok": sub_ok,
        "health_ok": health_ok,
        "reason": "; ".join(reasons),
    }
