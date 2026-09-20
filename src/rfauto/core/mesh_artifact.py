"""网格伪象自动诊断与收敛控制器内核。

把历史"网格病"教训内核化为确定性诊断链（numpy + 标准库，无第三方依赖）：
- #198/#219 rat-race 阶梯环：0.4mm 阶梯环慢波/容性栅格化伪象——六门在带内低端
  几乎全过、随 f 单调劣化；等效 εeff=3.28 超微带闭式上限（εr=3.66，HJ 直线
  2.7246）；全 4×4 矩阵对理想 (θ,θ,3θ,θ) 环线性幅值最小二乘得环电长缩放
  k=1.0975）。反推 k = f_target / f_center_raw；
  亦等价于 k = sqrt(εeff_等效 / εeff_闭式)。
- #205 via：底层倒置馈 MSLPort 的 β2/β1 = 1.0491±0.0011 带内恒定——乘性
  探针尺度常数（端口提取链归一化偏移），非网格伪象。
- #152：SmoothMesh/AddEdges2Grid 留下 nm 级近重合网格线 → CFL 时间步塌缩
  6 个量级（7.7e-19 s），症状是 CalcPort IndexError 而非网格报错。

与 core/solve_health.py 分工：solve_health 判"病"（本次 solve 是否可采信），
本模块判"网格病"并开药（局部加密 / 更换 BASE / 标定常数落 provenance）。
本模块不 import solve_health，两者独立；集成（service/CLI 薄壳、健康报告
内嵌网格伪象附件）留待后续增量（见 honestNotes）。

设计约束：
- 纯函数内核：输入为已加载的物理量（频率轴 + S 矩阵 / 网格细化序列 /
  各端口 εeff / timestep 记录 / 网格线间距），输出 JSON 友好报告。
- 每个检查独立 try/except：单项异常 → 该项 UNKNOWN，不传染（#105）。
- 产物缺失 → UNKNOWN，不误报。
- 判据只判"网格病"：单一"随 f 单调劣化"证据不足以定性（可能是设计错），
  必须叠加网格特异证据（细化中心上移 / 等效 εeff 超物理界）才落
  MESH_ARTIFACT，否则 INCONCLUSIVE（先验模型再校准）。
- 裸数据路径（PARTIAL）：k 反推不再要求完整
  provenance 链——直接输入多网格档响应数据（tiers，每档 mesh_mm + 频率轴
  + S 数据，全矩阵或驱动行均可）即可判伪象（各档中心裸定位 → 中心随细化
  上移）+ 给 k 估计（F0/最粗档裸定位中心，带沿截断时如实打界旗标）；带
  provenance 的定版中心 / 等效 εeff 退为增强路（精度互证），显式 kwargs >
  provenance 键 > 裸数据定位。裸数据只含门劣化+中心漂移两项证据，即便全过
  也落 INCONCLUSIVE（不升 HEALTHY——timestep/探针/εeff 未验证不背书）。

报告结构（JSON 友好）:
    status  ∈ {HEALTHY, MESH_ARTIFACT, PROBE_SCALE, TIMESTEP_COLLAPSE, INCONCLUSIVE}
    factors 为条目列表（factor / status / detail / lesson_ref / evidence）
    actions 为建议动作列表；recovered_scale 为反推电长缩放 k（可空）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# 状态与检定常量
# ---------------------------------------------------------------------------

HEALTHY = "HEALTHY"
MESH_ARTIFACT = "MESH_ARTIFACT"
PROBE_SCALE = "PROBE_SCALE"
TIMESTEP_COLLAPSE = "TIMESTEP_COLLAPSE"
INCONCLUSIVE = "INCONCLUSIVE"

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

# 教训编号——写进每条 factor，保证报告可回溯到踩坑原文
LESSON_GATE_DEGRADE = "#219（六门随 f 单调劣化+带内低端全过）"
LESSON_CENTER_SHIFT = "#219②（网格细化中心单调上移=伪象自证）"
LESSON_EPS_BOUND = "#198/#219（等效 εeff 超物理界）"
LESSON_PROBE_SCALE = "#205（MSLPort 倒置叠层探针尺度常数 1.0491）"
LESSON_TIMESTEP = "#152（nm 级近重合网格线 → CFL 时间步塌缩）"

# 教训常数（与踩坑原文数值一致）
# 1.0491 探针窗（#205）：β2/β1=1.0491±0.0011 带内恒定——
# 探针尺度常数是 β 的乘性因子 s；等效 εeff 比值 = s²（故 εeff 口径须先开方）
PROBE_SCALE_CENTER = 1.0491
PROBE_SCALE_HALF_WIDTH = 0.01
# 等效 εeff 超闭式容差：>5% 判"远超闭式"（阶梯环案例实测 +20.4%）
EPS_OVER_CLOSED_TOL = 0.05
# 网格细化中心上移显著门槛：细化档中心相对粗档上移 >2% 判伪象自证
CENTER_SHIFT_TOL = 0.02
# 多门门槛（ratrace 口径）：balance ≤1dB、match ≤-10dB、isolation ≤-15dB
BALANCE_PASS_DB = 1.0
MATCH_PASS_DB = -10.0
ISO_PASS_DB = -15.0
# 单调劣化：badness 递增步占比 ≥0.8 且首末比 >1.5
MONOTONE_STEP_FRAC = 0.8
MONOTONE_RATIO = 1.5
# timestep 塌缩（#152，与健康体检同口径）：min/max <1e-3 = 塌缩 6 个量级
TIMESTEP_COLLAPSE_RATIO = 1e-3
# 近重合网格线：AddEdges2Grid 留下的 nm~µm 级间距 <1µm（最小间距守卫口径）
NEAR_COINCIDENT_GAP_M = 1e-6
# 反推 k 双路一致性容差（中心比 vs εeff 比）
SCALE_AGREEMENT_TOL = 0.02

# ratrace 端口语义（#208 定版）：1=Σ、2=out1、3=Δ、4=out2
DEFAULT_HYBRID_PORTS = {"drive": 1, "out_a": 2, "out_b": 4, "iso": 3}

_DB_FLOOR = 1e-30


# ---------------------------------------------------------------------------
# 构造助手
# ---------------------------------------------------------------------------

def _factor(
    factor: str,
    status: str,
    detail: str,
    lesson_ref: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一形态的单条诊断 factor（JSON 友好）。"""
    item: dict[str, Any] = {
        "factor": factor,
        "status": status,
        "detail": detail,
        "lesson_ref": lesson_ref,
    }
    if evidence:
        item["evidence"] = evidence
    return item


def _unknown(factor: str, detail: str, lesson_ref: str,
             evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """产物缺失/不可判定时的 UNKNOWN 条目（不误报，#152 惯例）。"""
    return _factor(factor, UNKNOWN, detail, lesson_ref, evidence=evidence)


def _db(x: Any) -> np.ndarray:
    """线性幅值 → dB（地板 1e-30 防 log10(0)）。"""
    return 20.0 * np.log10(np.abs(np.asarray(x, dtype=complex)) + _DB_FLOOR)


def _as_float(value: Any) -> float | None:
    """尽力转 float，失败/非有限返回 None。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


# ---------------------------------------------------------------------------
# S 参数：混合环六门随频率劣化检测（#219 诊断链前两级）
# ---------------------------------------------------------------------------

def hybrid_gate_series(
    freq_hz: Any,
    s_matrix: Any,
    ports: dict[str, int] | None = None,
) -> dict[str, Any]:
    """按 ratrace 口径算逐频点六门指标（纯函数，供 factor 与复算脚本共用）。

    端口语义（1-indexed，默认 #208 定版）：drive=Σ(1)、out_a=out1(2)、
    out_b=out2(4)、iso=Δ(3)。数据不足返回 {"ok": False, "reason": ...}。
    """
    if freq_hz is None or s_matrix is None:
        return {"ok": False, "reason": "缺频率轴或 S 矩阵"}
    f = np.asarray(freq_hz, dtype=float).reshape(-1)
    s = np.asarray(s_matrix, dtype=complex)
    if s.ndim != 3 or s.shape[1] != s.shape[2] or f.size != s.shape[0]:
        return {"ok": False, "reason": f"S 矩阵形状不匹配: {s.shape} vs freq {f.size}"}
    p = dict(DEFAULT_HYBRID_PORTS)
    if ports:
        p.update({k: int(v) for k, v in ports.items()})
    n = s.shape[1]
    if max(p.values()) > n or min(p.values()) < 1:
        return {"ok": False, "reason": f"端口号超范围（n_ports={n}）: {p}"}
    d, oa, ob, iso = p["drive"] - 1, p["out_a"] - 1, p["out_b"] - 1, p["iso"] - 1
    finite = np.isfinite(f) & np.all(np.isfinite(s), axis=(1, 2))
    if finite.sum() < 4:
        return {"ok": False, "reason": "有效频点 <4"}
    f, s = f[finite], s[finite]
    order = np.argsort(f)
    f, s = f[order], s[order]
    sda, sdb = s[:, oa, d], s[:, ob, d]
    balance_db = np.abs(_db(sda) - _db(sdb))
    match_db = np.max(_db(np.diagonal(s, axis1=1, axis2=2)), axis=1)
    iso_db = np.maximum(_db(s[:, iso, d]), _db(s[:, ob, oa]))
    # badness：三门线性"越坏越大"合成量（单调劣化判据用）
    badness = (np.abs(np.abs(sda) - np.abs(sdb))
               + np.max(np.abs(np.diagonal(s, axis1=1, axis2=2)), axis=1)
               + np.maximum(np.abs(s[:, iso, d]), np.abs(s[:, ob, oa])))
    return {
        "ok": True,
        "freq_hz": f,
        "balance_db": balance_db,
        "match_db": match_db,
        "isolation_db": iso_db,
        "badness": badness,
        "ports": p,
    }


def locate_hybrid_center_ghz(freq_hz: Any, s_matrix: Any,
                             ports: dict[str, int] | None = None) -> float | None:
    """定位混合环中心（badness 最小频点，GHz）；数据不足返回 None。

    注意：0.4mm 原始 ratrace 的 best 落在带内低端边界（真中心在带外更低），
    本定位量只作交叉参考；反推 k 优先用带 provenance 的中心记录。
    """
    g = hybrid_gate_series(freq_hz, s_matrix, ports)
    if not g.get("ok"):
        return None
    f = g["freq_hz"]
    idx = int(np.argmin(g["badness"]))
    return float(f[idx] / 1e9)


def locate_tier_center_ghz(freq_hz: Any, s_matrix: Any,
                           ports: dict[str, int] | None = None) -> dict[str, Any]:
    """单档响应数据裸定位混合环中心（跨档同口径）。

    数据形态二选一：
    - 全矩阵 (n_freq, n, n)：额外给 badness_min（#219 口径）；
    - 驱动行 (n_freq, m)：列按端口序 [S_{1d},...,S_{md}]（如归档 sparams.csv
      的 S11,S21,S31,S41），与全矩阵取激励列等价——跨档同口径可比。

    指标：balance_min（|S_outa,d| 与 |S_outb,d| 幅差最小）、s11_min（|S_dd|
    最小）、badness_min（仅全矩阵）。中心 = 各指标 argmin 频点的均值（与
    网格收敛研究 f_center_avg=balance/s11 均值口径一致）；argmin 落在首/末
    频点 → 该指标 band_edge_limited=True；全带沿截断时中心打
    band_edge_limited 旗（真中心可能带外，k=F0/f 仅作界值）。

    返回 {"ok": True, "f_center_ghz", "band_edge_limited", "metrics",
    "data_shape", "n_freq"}；数据不足返回 {"ok": False, "reason": ...}。
    """
    if freq_hz is None or s_matrix is None:
        return {"ok": False, "reason": "缺频率轴或响应数据"}
    f = np.asarray(freq_hz, dtype=float).reshape(-1)
    s = np.asarray(s_matrix, dtype=complex)
    full = s.ndim == 3 and s.shape[1] == s.shape[2] and f.size == s.shape[0]
    partial = s.ndim == 2 and f.size == s.shape[0]
    if not full and not partial:
        return {"ok": False, "reason": f"响应数据形状不支持（需 (F,N,N) 或 (F,M)）: {s.shape}"}
    p = dict(DEFAULT_HYBRID_PORTS)
    if ports:
        p.update({k: int(v) for k, v in ports.items()})
    n_cols = s.shape[2] if full else s.shape[1]
    if max(p.values()) > n_cols or min(p.values()) < 1:
        return {"ok": False, "reason": f"端口号超范围（n_cols={n_cols}）: {p}"}
    finite = np.isfinite(f) & np.all(np.isfinite(s), axis=(1, 2) if full else 1)
    if finite.sum() < 4:
        return {"ok": False, "reason": "有效频点 <4"}
    f = f[finite]
    s = s[finite] if full else s[finite, :]
    order = np.argsort(f)
    f, s = f[order], s[order]
    d, oa, ob = p["drive"] - 1, p["out_a"] - 1, p["out_b"] - 1
    drive_row = s[:, :, d] if full else s  # 列=响应端口序，行=频点
    metrics: dict[str, Any] = {}

    def _metric(name: str, series: np.ndarray, axis_f: np.ndarray) -> None:
        idx = int(np.argmin(series))
        metrics[name] = {"f_ghz": float(axis_f[idx] / 1e9),
                         "edge_limited": bool(idx in (0, axis_f.size - 1))}

    _metric("balance_min", np.abs(np.abs(drive_row[:, oa]) - np.abs(drive_row[:, ob])), f)
    _metric("s11_min", np.abs(drive_row[:, d]), f)
    if full:
        g = hybrid_gate_series(f, s, p)
        if g.get("ok"):
            _metric("badness_min", np.asarray(g["badness"]), np.asarray(g["freq_hz"]))
    interior = [m["f_ghz"] for m in metrics.values() if not m["edge_limited"]]
    edge = not interior
    center = float(np.mean(interior) if interior
                   else np.mean([m["f_ghz"] for m in metrics.values()]))
    return {
        "ok": True,
        "f_center_ghz": center,
        "band_edge_limited": edge,
        "metrics": metrics,
        "data_shape": "full_matrix" if full else "drive_row",
        "n_freq": int(f.size),
    }


def _analyze_gate_degradation(freq_hz: Any, s_matrix: Any,
                              ports: dict[str, int] | None) -> dict[str, Any]:
    """#219：带内低端六门全过 + 随 f 单调劣化 → FAIL（网格伪象特征信号）。"""
    g = hybrid_gate_series(freq_hz, s_matrix, ports)
    if not g.get("ok"):
        return _unknown("gate_degradation", f"S 参数不足，无法判定多门劣化（{g.get('reason', '')}）",
                        LESSON_GATE_DEGRADE)
    f, badness = g["freq_hz"], g["badness"]
    n = f.size
    k_edge = max(1, round(float(n) * 0.1))
    lo_pass = bool(
        np.all(g["balance_db"][:k_edge] <= BALANCE_PASS_DB)
        and np.all(g["match_db"][:k_edge] <= MATCH_PASS_DB)
        and np.all(g["isolation_db"][:k_edge] <= ISO_PASS_DB)
    )
    hi_fail = bool(
        np.any(g["balance_db"][-k_edge:] > BALANCE_PASS_DB)
        or np.any(g["match_db"][-k_edge:] > MATCH_PASS_DB)
        or np.any(g["isolation_db"][-k_edge:] > ISO_PASS_DB)
    )
    steps = np.diff(badness)
    frac_up = float(np.mean(steps > 0)) if steps.size else 0.0
    ratio = float(badness[-1] / badness[0]) if badness[0] > 0 else float("inf")
    monotone = frac_up >= MONOTONE_STEP_FRAC and ratio > MONOTONE_RATIO
    ev = {
        "low_band_all_gates_pass": lo_pass,
        "high_band_any_gate_fail": hi_fail,
        "badness_first": float(badness[0]),
        "badness_last": float(badness[-1]),
        "increasing_step_fraction": frac_up,
        "last_over_first": ratio,
        "balance_db_at_low": float(g["balance_db"][0]),
        "match_db_at_low": float(g["match_db"][0]),
        "isolation_db_at_low": float(g["isolation_db"][0]),
    }
    if lo_pass and hi_fail and monotone:
        return _factor(
            "gate_degradation", FAIL,
            f"带内低端六门全过、随 f 单调劣化（badness {badness[0]:.3f}→{badness[-1]:.3f}，"
            f"递增步占比 {frac_up:.2f}）——网格伪象特征信号，但需网格特异证据定性（#219①）",
            LESSON_GATE_DEGRADE, evidence=ev,
        )
    if lo_pass and hi_fail:
        return _factor(
            "gate_degradation", WARN,
            "带内低端六门全过且高端有门不过，但劣化非单调——不足以判伪象",
            LESSON_GATE_DEGRADE, evidence=ev,
        )
    if not lo_pass:
        return _factor(
            "gate_degradation", PASS,
            "带内低端六门未全过——非低端全过+单调劣化形态",
            LESSON_GATE_DEGRADE, evidence=ev,
        )
    return _factor(
        "gate_degradation", PASS,
        "六门未现单调劣化形态",
        LESSON_GATE_DEGRADE, evidence=ev,
    )


# ---------------------------------------------------------------------------
# 网格细化中心漂移（伪象自证，#219②）
# ---------------------------------------------------------------------------

def _normalize_mesh_study(mesh_study: Any) -> list[tuple[float, float]]:
    """网格研究归一化为 [(mesh_mm, f_center_ghz)]（按 mesh_mm 降序=粗→细）。"""
    out: list[tuple[float, float]] = []
    if not mesh_study:
        return out
    for row in mesh_study:
        if isinstance(row, dict):
            mm = _as_float(row.get("mesh_mm"))
            fc = _as_float(row.get("f_center_ghz", row.get("f_center")))
        else:
            try:
                mm, fc = _as_float(row[0]), _as_float(row[1])
            except (TypeError, IndexError):
                mm = fc = None
        if mm is not None and fc is not None and mm > 0:
            out.append((mm, fc))
    out.sort(key=lambda t: -t[0])
    return out


def _normalize_tiers(tiers: Any) -> list[dict[str, Any]]:
    """多档裸响应数据归一化为 [{"mesh_mm", "freq_hz", "s_matrix"}]（剔无效行）。"""
    rows: list[dict[str, Any]] = []
    if not tiers:
        return rows
    for t in tiers:
        if not isinstance(t, dict):
            continue
        mm = _as_float(t.get("mesh_mm"))
        if mm is None or mm <= 0:
            continue
        rows.append({"mesh_mm": mm, "freq_hz": t.get("freq_hz"),
                     "s_matrix": t.get("s_matrix")})
    return rows


def _analyze_center_shift(mesh_study: Any) -> dict[str, Any]:
    """#219②：网格细化后中心频率单调上移 → FAIL（伪象自证）。"""
    rows = _normalize_mesh_study(mesh_study)
    if len(rows) < 2:
        return _unknown(
            "mesh_center_shift",
            f"网格细化记录 {len(rows)} 档 <2，无法判定中心是否随细化上移",
            LESSON_CENTER_SHIFT,
            evidence={"n_levels": len(rows)},
        )
    mesh = [r[0] for r in rows]
    centers = [r[1] for r in rows]
    deltas = np.diff(centers)
    monotone_up = bool(np.all(deltas > 0))
    shift = float(centers[-1] / centers[0] - 1.0)
    ev = {
        "mesh_mm_desc": mesh,
        "f_center_ghz": centers,
        "shift_frac_fine_over_coarse": shift,
        "monotone_up": monotone_up,
    }
    if monotone_up and shift > CENTER_SHIFT_TOL:
        return _factor(
            "mesh_center_shift", FAIL,
            f"网格细化（{mesh[0]:g}mm→{mesh[-1]:g}mm）中心单调上移 "
            f"{centers[0]:.4f}→{centers[-1]:.4f}GHz（+{shift * 100:.1f}%）——伪象自证："
            "物理器件中心不随网格变",
            LESSON_CENTER_SHIFT, evidence=ev,
        )
    if monotone_up:
        return _factor(
            "mesh_center_shift", WARN,
            f"中心随细化单调上移但幅度仅 {shift * 100:.2f}% ≤{CENTER_SHIFT_TOL * 100:.0f}%，"
            "不足以定性伪象",
            LESSON_CENTER_SHIFT, evidence=ev,
        )
    return _factor(
        "mesh_center_shift", PASS,
        f"中心未随网格细化单调上移（{centers[0]:.4f}→{centers[-1]:.4f}GHz）",
        LESSON_CENTER_SHIFT, evidence=ev,
    )


# ---------------------------------------------------------------------------
# 等效 εeff 超物理界（#198/#219）
# ---------------------------------------------------------------------------

def recovered_scale_from_eps(equiv_eps_eff: Any, eps_eff_closed_form: Any) -> float | None:
    """k = sqrt(εeff_等效 / εeff_闭式)（电长缩放 ↔ 介电常数缩放）。"""
    eq = _as_float(equiv_eps_eff)
    cl = _as_float(eps_eff_closed_form)
    if eq is None or cl is None or cl <= 0:
        return None
    return float(np.sqrt(eq / cl))


def _analyze_equiv_eps(equiv_eps_eff: Any, eps_eff_closed_form: Any,
                       eps_r: Any) -> dict[str, Any]:
    """#198/#219：等效 εeff 超基板 εr 或远超闭式 → FAIL（物理界判据）。"""
    eq = _as_float(equiv_eps_eff)
    cl = _as_float(eps_eff_closed_form)
    er = _as_float(eps_r)
    if eq is None:
        return _unknown(
            "equiv_eps_eff",
            "无等效 εeff（全矩阵电长拟合）记录，无法与物理界对照",
            LESSON_EPS_BOUND,
        )
    over_closed = None if (cl is None or cl <= 0) else eq / cl - 1.0
    k_eps = recovered_scale_from_eps(eq, cl)
    ev: dict[str, Any] = {
        "equiv_eps_eff": eq,
        "eps_eff_closed_form": cl,
        "eps_r": er,
        "over_closed_form_frac": over_closed,
        "recovered_scale_from_eps": k_eps,
    }
    if er is not None and eq > er:
        return _factor(
            "equiv_eps_eff", FAIL,
            f"等效 εeff={eq:.4f} > 基板 εr={er:.4f}——超物理上限，必为栅格化伪象",
            LESSON_EPS_BOUND, evidence=ev,
        )
    if over_closed is not None and over_closed > EPS_OVER_CLOSED_TOL:
        return _factor(
            "equiv_eps_eff", FAIL,
            f"等效 εeff={eq:.4f} 远超闭式 {cl:.4f}（+{over_closed * 100:.1f}% >"
            f" {EPS_OVER_CLOSED_TOL * 100:.0f}%）——慢波/容性栅格化伪象"
            f"（反推电长缩放 k={k_eps:.4f}）",
            LESSON_EPS_BOUND, evidence=ev,
        )
    return _factor(
        "equiv_eps_eff", PASS,
        f"等效 εeff={eq:.4f} 未超物理界"
        + (f"（闭式 {cl:.4f}，+{over_closed * 100:.1f}%）" if over_closed is not None else ""),
        LESSON_EPS_BOUND, evidence=ev,
    )


# ---------------------------------------------------------------------------
# 探针尺度常数（#205 1.0491）
# ---------------------------------------------------------------------------

def _normalize_eps_by_port(eps_eff_by_port: Any) -> dict[str, float]:
    """各端口 εeff 归一化为 {port: value}（剔除非正/非有限）。"""
    out: dict[str, float] = {}
    if isinstance(eps_eff_by_port, dict):
        items = list(eps_eff_by_port.items())
    else:
        arr = np.asarray(eps_eff_by_port, dtype=float).reshape(-1)
        items = [(f"port{i + 1}", v) for i, v in enumerate(arr)]
    for key, val in items:
        v = _as_float(val)
        if v is not None and v > 0:
            out[str(key)] = v
    return out


def _probe_scale_candidates(beta: dict[str, float], eps: dict[str, float]) -> list[dict[str, Any]]:
    """把各端口 β / εeff 统一折算为探针尺度因子 s（εeff 比值 = s²）。"""
    pairs: list[dict[str, Any]] = []
    for source, table, root in (("beta", beta, False), ("eps_eff", eps, True)):
        keys = sorted(table)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = table[keys[i]], table[keys[j]]
                raw = max(a, b) / min(a, b)
                s = float(np.sqrt(raw)) if root else float(raw)
                pairs.append({"source": source, "port_a": keys[i], "port_b": keys[j],
                              "raw_ratio": raw, "scale": s})
    return pairs


def _analyze_probe_scale(beta_by_port: Any, eps_eff_by_port: Any) -> dict[str, Any]:
    """#205：探针尺度因子 s=β2/β1（或 sqrt(εeff 比)）落 1.0491±0.01 → FAIL。

    MSLPort 差分 β 提取在倒置叠层+残余驻波下的敏感性放大呈**乘性**常数偏移
    （#205：β2/β1=1.0491±0.0011 带内恒定），是端口提取链的病，不是网格病。
    """
    beta = _normalize_eps_by_port(beta_by_port)
    eps = _normalize_eps_by_port(eps_eff_by_port)
    if len(beta) < 2 and len(eps) < 2:
        return _unknown(
            "probe_scale_offset",
            f"有效端口记录不足（β={len(beta)}、εeff={len(eps)}），无法做两两比值",
            LESSON_PROBE_SCALE,
            evidence={"beta_by_port": beta, "eps_eff": eps},
        )
    pairs = _probe_scale_candidates(beta, eps)
    lo = PROBE_SCALE_CENTER - PROBE_SCALE_HALF_WIDTH
    hi = PROBE_SCALE_CENTER + PROBE_SCALE_HALF_WIDTH
    suspicious = [p for p in pairs if lo <= p["scale"] <= hi]
    ev: dict[str, Any] = {"beta_by_port": beta, "eps_eff": eps, "suspicious_pairs": suspicious}
    if not suspicious:
        return _factor(
            "probe_scale_offset", PASS,
            f"各端口两两探针尺度因子 s 均不在 {PROBE_SCALE_CENTER:.4f}±{PROBE_SCALE_HALF_WIDTH} 窗内",
            LESSON_PROBE_SCALE, evidence=ev,
        )
    detail = "；".join(
        f"{p['source']} {p['port_a']}/{p['port_b']} s={p['scale']:.4f}" for p in suspicious)
    return _factor(
        "probe_scale_offset", FAIL,
        f"探针尺度因子落入 {PROBE_SCALE_CENTER:.4f}±{PROBE_SCALE_HALF_WIDTH} 窗：{detail}——"
        "MSLPort 倒置叠层探针尺度常数（β 乘性归一化偏移），非网格伪象，勿以加密求解",
        LESSON_PROBE_SCALE, evidence=ev,
    )


# ---------------------------------------------------------------------------
# 时间步塌缩（#152）
# ---------------------------------------------------------------------------

def _analyze_timestep(timestep_values: Any, mesh_line_gaps_m: Any) -> dict[str, Any]:
    """#152：timestep min/max <1e-3 或网格线间距 <1µm → FAIL（CFL 塌缩）。"""
    ts = None
    if timestep_values is not None:
        arr = np.asarray(timestep_values, dtype=float).reshape(-1)
        arr = arr[np.isfinite(arr) & (arr > 0)]
        ts = arr
    gaps = None
    if mesh_line_gaps_m is not None:
        garr = np.asarray(mesh_line_gaps_m, dtype=float).reshape(-1)
        garr = garr[np.isfinite(garr) & (garr > 0)]
        gaps = garr
    if ts is None and gaps is None:
        return _unknown(
            "timestep_collapse",
            "无 timestep 记录与网格线间距，无法判定 CFL 塌缩（#152 惯例不误报）",
            LESSON_TIMESTEP,
        )
    ev: dict[str, Any] = {}
    reasons: list[str] = []
    if ts is not None and ts.size >= 2:
        ratio = float(np.min(ts) / np.max(ts))
        ev["n_timestep_records"] = int(ts.size)
        ev["timestep_min_s"] = float(np.min(ts))
        ev["timestep_max_s"] = float(np.max(ts))
        ev["timestep_min_max_ratio"] = ratio
        if ratio < TIMESTEP_COLLAPSE_RATIO:
            reasons.append(f"timestep min/max 比 {ratio:.3e} < {TIMESTEP_COLLAPSE_RATIO:.0e}"
                           f"（塌缩 {np.log10(1.0 / ratio):.1f} 个量级）")
    if gaps is not None and gaps.size:
        min_gap = float(np.min(gaps))
        ev["n_mesh_gaps"] = int(gaps.size)
        ev["min_mesh_gap_m"] = min_gap
        if min_gap < NEAR_COINCIDENT_GAP_M:
            reasons.append(f"网格线最小间距 {min_gap:.3e}m < {NEAR_COINCIDENT_GAP_M:.0e}m"
                           "（AddEdges2Grid 近重合线，最小间距守卫未生效）")
    if reasons:
        return _factor(
            "timestep_collapse", FAIL,
            "CFL 时间步塌缩：" + "；".join(reasons)
            + "——症状常为 CalcPort IndexError 而非网格报错（#152）",
            LESSON_TIMESTEP, evidence=ev,
        )
    n_ok = (ts.size if ts is not None else 0) + (gaps.size if gaps is not None else 0)
    if n_ok == 0:
        return _unknown(
            "timestep_collapse",
            "timestep/网格线间距记录为空，无法判定",
            LESSON_TIMESTEP, evidence=ev,
        )
    return _factor(
        "timestep_collapse", PASS,
        "timestep 量级与网格线间距正常（无 CFL 塌缩指纹）",
        LESSON_TIMESTEP, evidence=ev,
    )


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

_ACTIONS = {
    MESH_ARTIFACT: [
        "局部加密网格（BASE/2）复核中心是否继续上移（伪象自证）",
        "更换 BASE/网格策略（环带带缘对齐或柱坐标，避免阶梯化）",
        "把引擎常数 k 与生效范围（mesh/BASE）写进 provenance，换档必须重定标",
        "以 HFSS（物理 R 无补偿）为对齐基准仲裁归属",
    ],
    PROBE_SCALE: [
        "端口去嵌入/标定 MSLPort 探针尺度常数（skrf de-embedding）",
        "核对端口叠层 start/stop 约定与参考面（#150/#205），勿以加密网格求解",
        "把探针常数（如 1.0491）落 provenance，与网格伪象常数分开记账",
    ],
    TIMESTEP_COLLAPSE: [
        "网格构建末尾做最小间距守卫（SetLines 回写去重，间距 ≥1µm，#152）",
        "排查 AddEdges2Grid/SmoothMesh 留下的 nm~µm 级近重合线",
        "重跑前确认 timestep 量级恢复（塌缩 6 个量级=激励被截成 1 样本）",
    ],
    INCONCLUSIVE: [
        "补充网格细化研究（≥2 档）或等效 εeff 闭式对照以定性",
        "补 timestep 记录 / 各端口 εeff 提取 / 带 provenance 的中心频率",
    ],
    HEALTHY: [],
}


def _compute_recovered_scale(
    target_freq_ghz: Any,
    center_ghz: Any,
    equiv_eps_eff: Any,
    eps_eff_closed_form: Any,
    route_notes: dict[str, str] | None = None,
) -> tuple[float | None, dict[str, float], str | None]:
    """反推电长缩放 k：中心比与 εeff 比双路，返回 (均值, 各路, 告警)。

    route_notes：各路的如实注记（如裸数据定位中心带沿截断的界旗），
    追加进告警文本（单路无分歧告警时独立成告警）。
    """
    routes: dict[str, float] = {}
    tgt = _as_float(target_freq_ghz)
    ctr = _as_float(center_ghz)
    if tgt is not None and ctr is not None and ctr > 0:
        routes["center_ratio"] = float(tgt / ctr)
    k_eps = recovered_scale_from_eps(equiv_eps_eff, eps_eff_closed_form)
    if k_eps is not None:
        routes["eps_eff_ratio"] = k_eps
    if not routes:
        return None, {}, None
    values = list(routes.values())
    mean = float(np.mean(values))
    warn = None
    if len(values) >= 2 and (max(values) - min(values)) > SCALE_AGREEMENT_TOL * mean:
        warn = (f"反推 k 双路不一致（{routes}，差 {max(values) - min(values):.4f} >"
                f" {SCALE_AGREEMENT_TOL:.2f}）——单一证据存疑")
    for route, note in sorted((route_notes or {}).items()):
        if note and route in routes:
            warn = f"{warn}；{note}" if warn else note
    return mean, routes, warn


def diagnose_mesh_artifact(
    *,
    freq_hz: Any | None = None,
    s_matrix: Any | None = None,
    target_freq_ghz: Any | None = None,
    center_ghz: Any | None = None,
    equiv_eps_eff: Any | None = None,
    eps_eff_closed_form: Any | None = None,
    eps_r: Any | None = None,
    beta_by_port: Any | None = None,
    eps_eff_by_port: Any | None = None,
    mesh_study: Any | None = None,
    timestep_values: Any | None = None,
    mesh_line_gaps_m: Any | None = None,
    tiers: Any | None = None,
    hybrid_ports: dict[str, int] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """网格伪象诊断统一入口（纯函数，输入均为已加载物理量）。

    参数（显式 kwargs > provenance 同名键 > 多档裸数据定位）：
        freq_hz / s_matrix: 频率轴(Hz) 与 (n_freq, n_ports, n_ports) 复矩阵。
        target_freq_ghz: 设计目标中心频率（GHz）。
        center_ghz: 实测/记录中心频率（GHz，优先带 provenance 的定版记录）。
        equiv_eps_eff: 全矩阵电长拟合的等效 εeff（#198/#219）。
        eps_eff_closed_form: 同几何闭式 εeff（如 HJ 直线值）。
        eps_r: 基板相对介电常数（物理上限）。
        beta_by_port: 各端口 β 提取值 {port: v} 或序列（#205 探针窗首选口径）。
        eps_eff_by_port: 各端口 εeff 提取值 {port: v} 或序列（#205，折算 s=sqrt(比)）。
        mesh_study: [{"mesh_mm": m, "f_center_ghz": f}, ...] 网格细化序列。
        timestep_values: 同 run 的 FDTD timestep 记录序列(s)（#152）。
        mesh_line_gaps_m: 相邻网格线间距序列(m)（#152 近重合线判据）。
        tiers: 多网格档裸响应数据 [{"mesh_mm": m, "freq_hz": f, "s_matrix": S},
              ...]）——不要求完整 provenance 链：
              每档裸定位中心（locate_tier_center_ghz，全矩阵或驱动行均可），
              缺 mesh_study 时由各档中心合成；缺 freq_hz/s_matrix 时取带全
              矩阵的最粗档供六门判据；缺 center_ghz 时以最粗档裸定位中心
              补反推 k 的中心比路（带沿截断时打界旗进告警）。显式 kwargs 与
              provenance 键优先于该兜底（provenance 为增强路）。
        hybrid_ports: 端口语义覆盖（默认 ratrace #208 定版）。
        provenance: 兜底 dict（可携带上述任一键 + 数据来源说明）。

    返回：见模块 docstring。每项检查独立 try/except，单项异常 → UNKNOWN（#105）。
    tiers 非空时报告附加 "tier_centers"（逐档定位明细，JSON 友好）。
    """
    provenance = provenance or {}
    if freq_hz is None:
        freq_hz = provenance.get("freq_hz")
    if s_matrix is None:
        s_matrix = provenance.get("s_matrix")
    if target_freq_ghz is None:
        target_freq_ghz = provenance.get("target_freq_ghz", provenance.get("target_f_ghz"))
    if center_ghz is None:
        center_ghz = provenance.get("center_ghz")
    if equiv_eps_eff is None:
        equiv_eps_eff = provenance.get("equiv_eps_eff")
    if eps_eff_closed_form is None:
        eps_eff_closed_form = provenance.get("eps_eff_closed_form")
    if eps_r is None:
        eps_r = provenance.get("eps_r")
    if beta_by_port is None:
        beta_by_port = provenance.get("beta_by_port")
    if eps_eff_by_port is None:
        eps_eff_by_port = provenance.get("eps_eff_by_port")
    if mesh_study is None:
        mesh_study = provenance.get("mesh_study")
    if timestep_values is None:
        timestep_values = provenance.get("timestep_values", provenance.get("timesteps"))
    if mesh_line_gaps_m is None:
        mesh_line_gaps_m = provenance.get("mesh_line_gaps_m")
    if hybrid_ports is None:
        hybrid_ports = provenance.get("hybrid_ports")

    # 多档裸响应数据兜底：显式 kwargs > provenance 键 > 裸定位。
    # 每档独立定位（单项炸 → 该档 ok=False，不传染，#105）。
    tier_centers: list[dict[str, Any]] = []
    center_route_note: str | None = None
    normalized_tiers = _normalize_tiers(tiers)
    if normalized_tiers:
        tier_located: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for t in normalized_tiers:
            loc = locate_tier_center_ghz(t["freq_hz"], t["s_matrix"], hybrid_ports)
            entry: dict[str, Any] = {"mesh_mm": t["mesh_mm"], "ok": bool(loc.get("ok"))}
            if loc.get("ok"):
                entry.update({
                    "f_center_ghz": loc["f_center_ghz"],
                    "band_edge_limited": loc["band_edge_limited"],
                    "metrics": loc["metrics"],
                    "data_shape": loc["data_shape"],
                    "n_freq": loc["n_freq"],
                })
            else:
                entry["reason"] = str(loc.get("reason", ""))
            tier_centers.append(entry)
            tier_located.append((t, loc))
        valid = [(t, loc) for t, loc in tier_located if loc.get("ok")]
        if valid:
            if mesh_study is None:
                mesh_study = [{"mesh_mm": t["mesh_mm"],
                               "f_center_ghz": loc["f_center_ghz"]}
                              for t, loc in valid]
            if freq_hz is None and s_matrix is None:
                full = [(t, loc) for t, loc in valid
                        if loc["data_shape"] == "full_matrix"]
                pick = max(full or valid, key=lambda tl: tl[0]["mesh_mm"])
                freq_hz, s_matrix = pick[0]["freq_hz"], pick[0]["s_matrix"]
            if center_ghz is None:
                coarse = max(valid, key=lambda tl: tl[0]["mesh_mm"])
                center_ghz = coarse[1]["f_center_ghz"]
                if coarse[1]["band_edge_limited"]:
                    center_route_note = (
                        f"裸数据定位中心 {center_ghz:.4f}GHz 落在带沿"
                        "（真中心可能带外），反推 k=F0/f 为带沿界估计，"
                        "须以更宽带窗或 provenance 定版复核")

    runners = {
        "mesh_center_shift": lambda: _analyze_center_shift(mesh_study),
        "equiv_eps_eff": lambda: _analyze_equiv_eps(equiv_eps_eff, eps_eff_closed_form, eps_r),
        "gate_degradation": lambda: _analyze_gate_degradation(freq_hz, s_matrix, hybrid_ports),
        "probe_scale_offset": lambda: _analyze_probe_scale(beta_by_port, eps_eff_by_port),
        "timestep_collapse": lambda: _analyze_timestep(timestep_values, mesh_line_gaps_m),
    }
    order = ("gate_degradation", "mesh_center_shift", "equiv_eps_eff",
             "probe_scale_offset", "timestep_collapse")
    factors: list[dict[str, Any]] = []
    for name in order:
        try:
            factors.append(runners[name]())
        except Exception as exc:  # 单项炸 → UNKNOWN，不传染（#105）
            factors.append(_factor(name, UNKNOWN, f"检查项异常: {exc!r}", "mesh_artifact 内核"))
    fmap = {f["factor"]: f for f in factors}

    def _is(name: str, status: str) -> bool:
        return fmap.get(name, {}).get("status") == status

    timestep_fail = _is("timestep_collapse", FAIL)
    probe_fail = _is("probe_scale_offset", FAIL)
    mesh_specific_fail = _is("mesh_center_shift", FAIL) or _is("equiv_eps_eff", FAIL)
    degrade_fail = _is("gate_degradation", FAIL)
    any_unknown = any(f["status"] == UNKNOWN for f in factors)
    all_pass = all(f["status"] == PASS for f in factors)

    if timestep_fail:
        status = TIMESTEP_COLLAPSE
    elif probe_fail and not mesh_specific_fail:
        status = PROBE_SCALE
    elif mesh_specific_fail:
        status = MESH_ARTIFACT
    elif degrade_fail:
        status = INCONCLUSIVE
    elif all_pass:
        status = HEALTHY
    else:
        status = INCONCLUSIVE

    # 反推电长缩放 k 只对网格伪象有处方意义（探针尺度/时间步塌缩另有常数）
    if status == MESH_ARTIFACT:
        scale, routes, scale_warn = _compute_recovered_scale(
            target_freq_ghz, center_ghz, equiv_eps_eff, eps_eff_closed_form,
            route_notes={"center_ratio": center_route_note} if center_route_note else None)
    else:
        scale, routes, scale_warn = None, {}, None
    located = locate_hybrid_center_ghz(freq_hz, s_matrix, hybrid_ports)

    if status == MESH_ARTIFACT:
        detail = "判网格伪象（MESH_ARTIFACT）"
        if scale is not None:
            detail += f"，反推电长缩放 k={scale:.4f}"
        if scale_warn:
            detail += f"；注意：{scale_warn}"
    elif status == PROBE_SCALE:
        detail = "判探针尺度常数（PROBE_SCALE）：端口提取乘性偏移，非网格病"
    elif status == TIMESTEP_COLLAPSE:
        detail = "判时间步塌缩（TIMESTEP_COLLAPSE）：近重合网格线致 CFL 塌缩"
    elif status == HEALTHY:
        detail = "未见网格伪象（HEALTHY）：证据项全过"
    else:
        detail = ("不可判定（INCONCLUSIVE）：证据不足或仅有非网格特异的频率劣化信号"
                  if not any_unknown else "不可判定（INCONCLUSIVE）：关键证据缺失")

    report: dict[str, Any] = {
        "status": status,
        "factors": factors,
        "actions": list(_ACTIONS[status]),
        "recovered_scale": scale,
        "recovered_scale_routes": routes,
        "located_center_ghz": located,
        "detail": detail,
    }
    if tier_centers:
        report["tier_centers"] = tier_centers
    if provenance:
        report["provenance"] = provenance
    return report
