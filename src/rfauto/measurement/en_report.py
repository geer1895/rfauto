"""DP-11 P2：En 相关性报告确定性内核（规格书 DP-11 §3）。

计量学口径的"仿真 vs 实测"判据，替代拍脑袋 dB 阈值（correlate.py 的
threshold_db=3.0 保留并行，不改既有门语义——#122 门不因新工具改）：

- **En 定义**：逐频点逐 S 参数 ``En = (x_lab − x_ref) / √(U_lab² + U_ref²)``；
  ``|En| ≤ 1`` 判满意。x 取 dB 幅度（``20·log10|S|``）。
- **深谐振谷双分支**（#370/#371）：lab 与 ref **同时**低于 −40 dB 的频段，
  dB 域差值噪声放大到物理无意义 → 自动切**线性域**（|S| 幅度直判，U 按
  一阶传播 ``U_lin = |S|·(ln10/20)·U_db`` 换算），该频点 dB 域结果如实标
  ``not_evaluable``。
- **U_meas**：GUM 预算表（configs/uncertainty_budgets.yaml 默认模板：
  残余直接度/连接器重复性 0.005 dB/温漂 0.02 dB/°C×ΔT/IF 噪声/calkit 分量；
  ``u_c = √Σ(c_i·u_i)²``、U = k·u_c，k=2）。
- **U_sim**：锚 uncertainty 或该族 HFSS 仲裁残差；均缺 → 兜底值并
  ``source="fallback"`` 如实标注（不冒充计量学口径）。
- **U 下限** 1e-3 dB 防除零（低于即抬到下限）。
- **频轴对齐**（#287/#294）：argmin 最近邻 + 相对 1e-9 ulp 容差；
  **禁 searchsorted**（ulp 级频移会越位一格，#294 实证）。

全部确定性：纯 numpy，无随机、无网络、无全局状态（数值只在确定性内核，
铁律 7）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import skrf

#: 深谷阈值（dB）：lab 与 ref 同时低于 → 线性域
DEFAULT_DEEP_VALLEY_DB = -40.0
#: U 下限（dB）：防除零（规格书 §3）
MIN_U_DB = 1e-3
#: U 下限（线性域，除零兜底；−120 dB 量级）
MIN_U_LIN = 1e-6
#: 展开因子 k（GUM 常规）
DEFAULT_K = 2.0
#: 频轴最近邻配对容差（相对）：同栅+ulp 级扰动 ≪1e-9；异栅半步 ≥1e-4 量级
FREQ_MATCH_RTOL = 1e-9
#: 默认预算表路径（锚仓根推导，#295 家族：相对 cwd 的配置路径在从
#: runs/ 子目录执行时静默落空）
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BUDGET_PATH = _REPO_ROOT / "configs" / "uncertainty_budgets.yaml"
#: U_sim 兜底（dB）——锚/HFSS 残差均缺时的保守值（source=fallback 如实）
DEFAULT_FALLBACK_U_SIM_DB = 0.5


# ---------------------------------------------------------------------------
# GUM 预算表
# ---------------------------------------------------------------------------

def gum_combined_uncertainty(
    components: list[dict[str, Any]],
    *,
    k: float = DEFAULT_K,
    delta_t_c: float = 0.0,
) -> dict[str, Any]:
    """GUM 合成标准不确定度：``u_c = √Σ(c_i·u_i)²``、U = k·u_c。

    Args:
        components: ``[{name, u, unit?, c?, per_c?}]``——``u`` 为标准
            不确定度（dB）；``c`` 灵敏度系数（缺省 1.0）；``per_c=true`` 或
            ``unit`` 含 "/°C" 的分量按温漂处理：有效 u = u×ΔT。
        k: 展开因子（缺省 2）。
        delta_t_c: 与校准温度的温差（°C，温漂分量消费）。

    Returns:
        {u_c, U, k, contributions: [{name, contribution}], delta_t_c}
        —— contributions 逐分量 c_i·u_i（含温漂换算后的有效值）。
    """
    total = 0.0
    contributions: list[dict[str, Any]] = []
    for comp in components:
        u = float(comp["u"])
        c = float(comp.get("c", 1.0))
        unit = str(comp.get("unit", "dB"))
        per_c = bool(comp.get("per_c", False)) or "/°C" in unit or "/C" in unit
        eff_u = u * float(delta_t_c) if per_c else u
        contrib = c * eff_u
        total += contrib * contrib
        contributions.append({
            "name": str(comp.get("name", "")),
            "effective_u": eff_u,
            "c": c,
            "contribution": contrib,
            "per_c": per_c,
        })
    # math.sqrt(逐项平方和)：闭式对照测试用同一算式逐位对齐
    u_c = math.sqrt(total)
    return {
        "u_c": u_c,
        "U": k * u_c,
        "k": float(k),
        "contributions": contributions,
        "delta_t_c": float(delta_t_c),
    }


def load_budget(path: str | Path | None = None) -> dict[str, Any]:
    """加载 GUM 预算表 YAML（configs/uncertainty_budgets.yaml 缺省模板）。

    Returns:
        {name, k, delta_t_c, components, description}；文件缺失/损坏抛异常
        （预算表是判据输入，静默缺省=伪造计量学口径，不合法）。
    """
    import yaml

    p = Path(path or DEFAULT_BUDGET_PATH)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    budget = data.get("budgets", {}).get("default_vna")
    if budget is None:
        raise KeyError(f"预算表 {p} 缺 default_vna 条目")
    return {
        "name": "default_vna",
        "description": str(budget.get("description", "")),
        "k": float(budget.get("k", DEFAULT_K)),
        "delta_t_c": float(budget.get("delta_t_c", 0.0)),
        "components": list(budget.get("components") or []),
    }


# ---------------------------------------------------------------------------
# U_sim 解析
# ---------------------------------------------------------------------------

def resolve_u_sim(
    *,
    anchor_uncertainty_db: float | None = None,
    hfss_residual_db: float | None = None,
    fallback_db: float = DEFAULT_FALLBACK_U_SIM_DB,
) -> tuple[float, str]:
    """U_sim 解析优先级：锚 uncertainty → HFSS 仲裁残差 → 兜底。

    Returns:
        (U_sim_db, source)；source ∈ {"anchor", "hfss_arbitration", "fallback"}
        ——fallback 如实标注（诚实边界 4，criteria.md §4）。
    """
    if anchor_uncertainty_db is not None:
        return float(anchor_uncertainty_db), "anchor"
    if hfss_residual_db is not None:
        return float(hfss_residual_db), "hfss_arbitration"
    return float(fallback_db), "fallback"


# ---------------------------------------------------------------------------
# 频轴对齐（#287/#294：argmin 最近邻 + ulp 容差，禁 searchsorted）
# ---------------------------------------------------------------------------

def align_frequency_axes(
    f_lab: np.ndarray,
    f_ref: np.ndarray,
    *,
    rtol: float = FREQ_MATCH_RTOL,
) -> tuple[np.ndarray, np.ndarray, int]:
    """argmin 最近邻配对 → (lab 索引, ref 索引, 未配对 lab 点数)。

    判据：配对距离 ``|Δf| ≤ rtol·max(|f_lab|, |f_ref|)``——同栅+ulp 级
    扰动（#287：~1e-7 Hz @2 GHz，相对 1e-16）通过；异栅半步（MHz 量级）
    拒配（诚实 not_evaluable，不错位硬凑）。
    """
    f_lab = np.asarray(f_lab, dtype=float)
    f_ref = np.asarray(f_ref, dtype=float)
    if f_lab.size == 0 or f_ref.size == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int), int(f_lab.size)
    # 外积 argmin（小网格直接向量化；禁 searchsorted——不要求单调且免越位）
    diff = np.abs(f_lab[:, None] - f_ref[None, :])
    j = np.argmin(diff, axis=1)
    d = diff[np.arange(f_lab.size), j]
    tol = rtol * np.maximum(np.abs(f_lab), np.abs(f_ref[j]))
    keep = d <= tol
    idx_lab = np.nonzero(keep)[0]
    idx_ref = j[keep]
    n_unmatched = int(f_lab.size - idx_lab.size)
    return idx_lab, idx_ref, n_unmatched


# ---------------------------------------------------------------------------
# En 内核
# ---------------------------------------------------------------------------

def _clamp_u(u_db: np.ndarray) -> np.ndarray:
    """U 下限（dB）：低于 1e-3 dB 抬到下限（防除零，规格书 §3）。"""
    return np.maximum(np.asarray(u_db, dtype=float), MIN_U_DB)


def en_core(
    x_lab_db: np.ndarray,
    x_ref_db: np.ndarray,
    s_lab_lin: np.ndarray,
    s_ref_lin: np.ndarray,
    u_lab_db: np.ndarray,
    u_ref_db: np.ndarray,
    deep_valley_db: float = DEFAULT_DEEP_VALLEY_DB,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """En 纯内核（dB 域主分支 + 深谷线性域分支）→ (en, domain, evaluable)。

    逐频：``En = (x_lab − x_ref)/√(U_lab²+U_ref²)``（U 先过 1e-3 dB 下限）；
    lab 与 ref 同时 ``|S| < 10^(deep/20)`` 的频点切线性域
    （``(s_lab−s_ref)/√(U_lin_lab²+U_lin_ref²)``，U_lin=|S|·ln10/20·U_db），
    dB 域结果标 not_evaluable（#370/#371 深谷双分支）。

    本函数是 G5 合成回收逐位钉的入面：x_ref/U 取 2 的幂构造时，
    ``x_lab = x_ref ± c·√(U_lab²+U_ref²)``（同算式构造）→ En ≡ ∓c 逐位。
    """
    x_lab_db = np.asarray(x_lab_db, dtype=float)
    x_ref_db = np.asarray(x_ref_db, dtype=float)
    s_lab_lin = np.asarray(s_lab_lin, dtype=float)
    s_ref_lin = np.asarray(s_ref_lin, dtype=float)
    ul = _clamp_u(np.broadcast_to(np.asarray(u_lab_db, dtype=float),
                                  x_lab_db.shape).astype(float))
    ur = _clamp_u(np.broadcast_to(np.asarray(u_ref_db, dtype=float),
                                  x_ref_db.shape).astype(float))
    denom = np.sqrt(ul * ul + ur * ur)

    en = np.empty(x_lab_db.size, dtype=float)
    domain = np.empty(x_lab_db.size, dtype=object)
    evaluable = np.ones(x_lab_db.size, dtype=bool)

    thr_lin = 10.0 ** (float(deep_valley_db) / 20.0)
    deep = (np.maximum(s_lab_lin, s_ref_lin) < thr_lin)
    # dB 域（默认分支）
    en[~deep] = (x_lab_db[~deep] - x_ref_db[~deep]) / denom[~deep]
    domain[~deep] = "db"
    # 线性域（深谷分支；U 线性换算 = |S|·ln10/20·U_db，一阶传播）
    if np.any(deep):
        k = math.log(10.0) / 20.0
        ulin_l = np.maximum(s_lab_lin[deep] * k * ul[deep], MIN_U_LIN)
        ulin_r = np.maximum(s_ref_lin[deep] * k * ur[deep], MIN_U_LIN)
        en[deep] = (s_lab_lin[deep] - s_ref_lin[deep]) / np.sqrt(
            ulin_l * ulin_l + ulin_r * ulin_r)
        domain[deep] = "linear"
    evaluable[:] = ~deep   # 深谷频点 dB 域如实 not_evaluable（值在线性域）
    return en, domain, evaluable


def compute_en_trace(
    f_lab: np.ndarray,
    s_lab: np.ndarray,
    f_ref: np.ndarray,
    s_ref: np.ndarray,
    u_lab_db: float | np.ndarray,
    u_ref_db: float | np.ndarray,
    trace: str = "S11",
    *,
    deep_valley_db: float = DEFAULT_DEEP_VALLEY_DB,
    freq_rtol: float = FREQ_MATCH_RTOL,
    u_sim_source: str = "anchor",
    u_meas_source: str = "gum_budget",
) -> EnTraceResult:
    """逐频 En（网络复数 S 输入面；深谷双分支；#287/#294 频轴对齐）。

    Args:
        f_lab/s_lab: 实测侧频率 (Hz) 与复数 S 参数。
        f_ref/s_ref: 参考侧（仿真）同构。
        u_lab_db/u_ref_db: 两侧标准不确定度（dB，标量或逐频）。
    """
    f_lab = np.asarray(f_lab, dtype=float)
    f_ref = np.asarray(f_ref, dtype=float)
    s_lab = np.asarray(s_lab, dtype=complex)
    s_ref = np.asarray(s_ref, dtype=complex)
    idx_lab, idx_ref, n_unmatched = align_frequency_axes(f_lab, f_ref,
                                                         rtol=freq_rtol)
    provenance = {"u_sim_source": u_sim_source, "u_meas_source": u_meas_source}
    if idx_lab.size == 0:
        return EnTraceResult(
            trace=trace, freq_ghz=np.empty(0), en=np.empty(0),
            domain=np.empty(0, dtype=object), evaluable=np.empty(0, dtype=bool),
            x_lab_db=np.empty(0), x_ref_db=np.empty(0),
            u_lab_db=np.empty(0), u_ref_db=np.empty(0),
            deep_valley_db=float(deep_valley_db),
            n_unmatched_freqs=n_unmatched, provenance=provenance)

    sl = np.abs(s_lab[idx_lab])
    sr = np.abs(s_ref[idx_ref])
    x_lab = 20.0 * np.log10(np.maximum(sl, 1e-300))
    x_ref = 20.0 * np.log10(np.maximum(sr, 1e-300))
    en, domain, evaluable = en_core(
        x_lab, x_ref, sl, sr, u_lab_db, u_ref_db,
        deep_valley_db=deep_valley_db)
    ul = _clamp_u(np.broadcast_to(np.asarray(u_lab_db, dtype=float),
                                  x_lab.shape).astype(float))
    ur = _clamp_u(np.broadcast_to(np.asarray(u_ref_db, dtype=float),
                                  x_ref.shape).astype(float))

    freq_ghz = f_lab[idx_lab] / 1e9
    segments = _out_of_spec_segments(freq_ghz, en, evaluable)
    return EnTraceResult(
        trace=trace, freq_ghz=freq_ghz, en=en, domain=domain,
        evaluable=evaluable, x_lab_db=x_lab, x_ref_db=x_ref,
        u_lab_db=ul, u_ref_db=ur,
        deep_valley_db=float(deep_valley_db),
        n_unmatched_freqs=n_unmatched, segments=segments,
        provenance=provenance,
    )


@dataclass
class EnTraceResult:
    """单条 S 参数迹线的 En 判定结果。"""

    trace: str
    freq_ghz: np.ndarray
    en: np.ndarray                    # 配对频点的 En（未评估点 NaN）
    domain: np.ndarray                # "db" | "linear"（object 数组）
    evaluable: np.ndarray             # bool
    x_lab_db: np.ndarray
    x_ref_db: np.ndarray
    u_lab_db: np.ndarray
    u_ref_db: np.ndarray
    deep_valley_db: float
    n_unmatched_freqs: int            # 频轴未配对数（诚实计数）
    segments: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """门：全部配对频点可评估且 |En| ≤ 1。"""
        if self.en.size == 0:
            return False
        return bool(np.all(self.evaluable) and np.all(np.abs(self.en) <= 1.0))

    @property
    def max_abs_en(self) -> float:
        valid = self.en[np.isfinite(self.en)]
        return float(np.max(np.abs(valid))) if valid.size else float("inf")

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace": self.trace,
            "ok": self.ok,
            "max_abs_en": None if math.isinf(self.max_abs_en) else self.max_abs_en,
            "n_points": int(self.en.size),
            "n_evaluable": int(np.count_nonzero(self.evaluable)),
            "n_not_evaluable": int(np.count_nonzero(~self.evaluable)),
            "n_unmatched_freqs": int(self.n_unmatched_freqs),
            "n_linear_domain": int(np.count_nonzero(self.domain == "linear")),
            "deep_valley_db": self.deep_valley_db,
            "out_of_spec_segments": self.segments,
            "freq_ghz": [round(float(f), 9) for f in self.freq_ghz],
            "en": [float(v) if math.isfinite(v) else None for v in self.en],
            "domain": [str(d) for d in self.domain],
            "u_lab_db": [float(v) for v in self.u_lab_db],
            "u_ref_db": [float(v) for v in self.u_ref_db],
            "provenance": self.provenance,
        }


def _out_of_spec_segments(
    freq_ghz: np.ndarray,
    en: np.ndarray,
    evaluable: np.ndarray,
) -> list[dict[str, Any]]:
    """超差频段定位：连续 ``|En| > 1`` 频点合并成段（预声明口径）。"""
    bad = evaluable & np.isfinite(en) & (np.abs(en) > 1.0)
    segments: list[dict[str, Any]] = []
    i = 0
    n = bad.size
    while i < n:
        if not bad[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and bad[j + 1]:
            j += 1
        seg_en = en[i:j + 1]
        segments.append({
            "start_ghz": round(float(freq_ghz[i]), 9),
            "end_ghz": round(float(freq_ghz[j]), 9),
            "n_points": int(j - i + 1),
            "max_abs_en": float(np.max(np.abs(seg_en))),
        })
        i = j + 1
    return segments


def compute_en_report(
    lab: Any,
    ref: Any,
    u_lab_db: float | np.ndarray,
    u_ref_db: float | np.ndarray,
    *,
    traces: tuple[str, ...] = ("S11", "S21"),
    deep_valley_db: float = DEFAULT_DEEP_VALLEY_DB,
    freq_rtol: float = FREQ_MATCH_RTOL,
    u_sim_source: str = "anchor",
    u_meas_source: str = "gum_budget",
    measurement_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """完整 En 报告（JSON 友好 + Markdown），skrf.Network 输入。

    lab/ref 为 skrf.Network；traces 形如 ``"S11"``/``"S21"``（1 基端口对）。
    返回 dict：{ok, traces: {…}, summary, measurement_meta}；``ok`` = 全部
    迹线门过（逐迹线明细自带）。``render_markdown`` 出人读报告。
    """
    if not isinstance(lab, skrf.Network) or not isinstance(ref, skrf.Network):
        raise TypeError("lab/ref 须为 skrf.Network")

    trace_results: dict[str, EnTraceResult] = {}
    trace_dicts: dict[str, Any] = {}
    for t in traces:
        m = _parse_trace_name(t)
        row, col = m
        if max(row, col) >= lab.nports or max(row, col) >= ref.nports:
            raise ValueError(f"迹线 {t} 超出网络端口数（lab={lab.nports}, "
                             f"ref={ref.nports}）")
        r = compute_en_trace(
            lab.f, lab.s[:, row, col], ref.f, ref.s[:, row, col],
            u_lab_db, u_ref_db, trace=t,
            deep_valley_db=deep_valley_db, freq_rtol=freq_rtol,
            u_sim_source=u_sim_source, u_meas_source=u_meas_source)
        trace_results[t] = r
        trace_dicts[t] = r.to_dict()

    report = {
        "ok": bool(trace_dicts) and all(d["ok"] for d in trace_dicts.values()),
        "traces": trace_dicts,
        "summary": {
            "n_traces": len(trace_dicts),
            "traces_passed": sum(1 for d in trace_dicts.values() if d["ok"]),
            "deep_valley_db": float(deep_valley_db),
            "u_sim_source": u_sim_source,
            "u_meas_source": u_meas_source,
        },
        "measurement_meta": dict(measurement_meta or {}),
    }
    report["markdown"] = render_markdown(report)
    return report


def _parse_trace_name(name: str) -> tuple[int, int]:
    import re

    m = re.fullmatch(r"S(\d+)(\d+)", str(name).strip().upper())
    if not m:
        raise ValueError(f"迹线名须为 S<i>j 形态: {name!r}")
    return int(m.group(1)) - 1, int(m.group(2)) - 1


def render_markdown(report: dict[str, Any]) -> str:
    """En 报告 Markdown 渲染（概要 + 逐迹线 + 超差频段 + provenance）。"""
    lines: list[str] = ["# En 相关性报告（DP-11）", "",
                        "## 概要", ""]
    ok = report.get("ok")
    lines.append(f"- **判定**: {'✅ 满意（|En|≤1 全过）' if ok else '❌ 存在超差/不可评估'}")
    summary = report.get("summary", {})
    lines.append(f"- **迹线**: {summary.get('traces_passed', 0)}/"
                 f"{summary.get('n_traces', 0)} 过门")
    lines.append(f"- **深谷阈值**: {summary.get('deep_valley_db', -40)} dB"
                 "（同时低于 → 线性域）")
    lines.append(f"- **U 来源**: sim={summary.get('u_sim_source')}, "
                 f"meas={summary.get('u_meas_source')}")
    lines.append("")

    for t, d in report.get("traces", {}).items():
        lines.append(f"## {t.upper()}")
        lines.append("")
        lines.append(f"- 判定: {'PASS' if d['ok'] else 'FAIL'}"
                     f"（max|En|={d['max_abs_en'] if d['max_abs_en'] is not None else 'N/A'}）")
        lines.append(f"- 评估点: {d['n_evaluable']}/{d['n_points']}"
                     f"（线性域 {d['n_linear_domain']}，频轴未配对 {d['n_unmatched_freqs']}）")
        if d["out_of_spec_segments"]:
            lines.append("- 超差频段:")
            lines.append("")
            lines.append("| 起止 (GHz) | 点数 | max|En| |")
            lines.append("|---|---|---|")
            for s in d["out_of_spec_segments"]:
                lines.append(f"| {s['start_ghz']}–{s['end_ghz']} "
                             f"| {s['n_points']} | {s['max_abs_en']:.3f} |")
        else:
            lines.append("- 超差频段: 无")
        lines.append("")

    meta = report.get("measurement_meta") or {}
    if meta:
        lines.append("## 测量 meta")
        lines.append("")
        for k, v in meta.items():
            lines.append(f"- {k}: {v}")
        lines.append("")
    return "\n".join(lines)
