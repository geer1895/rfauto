"""E9c 相关性报告（扩展方案 §E9c）。

仿真 vs 测量相关性分析：
- 计算 S 参数偏差（幅度/相位）
- 生成相关性报告（JSON + Markdown）
- 双基线语义分离：sim=hard fail / measured=soft warn
- **补强17（§10.22）**：correlate 接 D12——S11/S21 dB 幅度曲线并行走
  core.fsv（IEEE 1597.1）曲线级 ADM/FDM/GDM 六级评级，best-effort 加性
  字段（#105），不改变既有 dB 阈值门语义
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.measurement.en_report import DEFAULT_K, align_frequency_axes
from rfauto.measurement.import_data import MeasurementData

#: FSV 迹线白名单（S-1 C-06① 2026-10-04）：trace 名（小写）→ S 参数
#: (row, col) 下标。白名单外的 trace 名显式报错——旧实现任意非 's11'
#: 名被静默按 s21 评估。
_FSV_SUPPORTED_TRACES: dict[str, tuple[int, int]] = {
    "s11": (0, 0),
    "s21": (1, 0),
}


# ---------------------------------------------------------------------------
# T1-C-10（2026-10-05）：相关系数双侧区间（GUM 口径，与 en_report 同构）
# ---------------------------------------------------------------------------

def pearson_interval(r: float, n: int, *, k: float = DEFAULT_K) -> dict[str, Any]:
    """Pearson 相关系数双侧区间：``r ± k·u_r``，``u_r = (1-r²)/√(N-1)``。

    区间构造与 en_report.gum_combined_uncertainty 同一口径（估计量 ±
    k·标准不确定度，k 缺省共用 en_report.DEFAULT_K=2.0 单源）；u_r 取
    双变量正态大样近似的标准误差 se(r)=(1-ρ²)/√(N-1)。**预声明**（判据
    书 runs/w1_phase1/criteria.md §W1-E）：非高斯/小样本下真实覆盖率会
    偏离名义，判据只锁"区间宽随 N 收缩单调"，不锁覆盖率数字。

    Returns:
        {ok, r, n, k, u_r, interval: [lo, hi], width}；n<3 / r 非有限 /
        非法 k 如实 ok=False 不硬凑（#122）。区间夹持到 [-1, 1]。
    """
    n = int(n)
    r = float(r)
    k = float(k)
    if n < 3:
        return {"ok": False, "r": r, "n": n,
                "note": f"n={n} 过小（双侧区间需 n ≥ 3）"}
    if not math.isfinite(r):
        return {"ok": False, "r": None, "n": n,
                "note": "r 非有限（常数曲线等退化输入）"}
    if not math.isfinite(k) or k <= 0:
        return {"ok": False, "r": r, "n": n, "k": k,
                "note": f"展开因子 k={k} 非法（需正有限）"}
    r_c = min(1.0, max(-1.0, r))  # 浮点边缘（|r| 略超 1）夹持
    u_r = (1.0 - r_c * r_c) / math.sqrt(n - 1)
    lo = max(-1.0, r_c - k * u_r)
    hi = min(1.0, r_c + k * u_r)
    return {"ok": True, "r": r_c, "n": n, "k": k,
            "u_r": u_r, "interval": [lo, hi], "width": hi - lo}


def correlation_with_interval(
    x: Any, y: Any, *, k: float = DEFAULT_K,
) -> dict[str, Any]:
    """配对样本 → Pearson r + 双侧区间（T1-C-10 确定性内核）。

    退化输入（样本数不等 / n<3 / 含非有限值 / 零方差常数曲线）一律
    ok=False 带如实 note，不抛异常不硬凑（#105/#122）。
    """
    xs = np.asarray(x, dtype=float).ravel()
    ys = np.asarray(y, dtype=float).ravel()
    if xs.size != ys.size:
        return {"ok": False, "n_x": int(xs.size), "n_y": int(ys.size),
                "note": "配对样本数不等"}
    if xs.size < 3:
        return {"ok": False, "n": int(xs.size),
                "note": f"n={int(xs.size)} 过小（需 ≥ 3）"}
    if not (np.all(np.isfinite(xs)) and np.all(np.isfinite(ys))):
        return {"ok": False, "n": int(xs.size), "note": "样本含非有限值"}
    if float(xs.std()) == 0.0 or float(ys.std()) == 0.0:
        return {"ok": False, "n": int(xs.size),
                "note": "零方差常数曲线，相关系数无定义"}
    r = float(np.corrcoef(xs, ys)[0, 1])
    return pearson_interval(r, int(xs.size), k=k)


@dataclass
class CorrelationMetrics:
    """相关性指标。"""
    s11_max_deviation_db: float
    s21_max_deviation_db: float
    s11_mean_deviation_db: float
    s21_mean_deviation_db: float
    freq_range_ghz: tuple[float, float]
    n_freq_points: int
    #: 频轴真交集口径（E1-1）：配对后未参与比较的仿真频点数（0=完全同栅）
    n_unpaired_points: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "s11_max_deviation_db": round(self.s11_max_deviation_db, 2),
            "s21_max_deviation_db": round(self.s21_max_deviation_db, 2),
            "s11_mean_deviation_db": round(self.s11_mean_deviation_db, 2),
            "s21_mean_deviation_db": round(self.s21_mean_deviation_db, 2),
            "freq_range_ghz": list(self.freq_range_ghz),
            "n_freq_points": self.n_freq_points,
            "n_unpaired_points": self.n_unpaired_points,
        }


@dataclass
class CorrelationResult:
    """相关性分析结果。"""
    sim_file: str
    measured_file: str
    metrics: CorrelationMetrics
    is_correlated: bool
    threshold_db: float
    warnings: list[str]
    # 补强17：D12 FSV 曲线级评估（compute_fsv_assessment 输出；None=未启用）
    fsv: dict[str, Any] | None = field(default=None)
    # T1-C-10：皮尔逊相关系数 + GUM 双侧区间（键 s11/s21；None=未启用）。
    # 加性字段：to_dict 多一键，既有消费者零破坏。
    correlation: dict[str, Any] | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_file": self.sim_file,
            "measured_file": self.measured_file,
            "metrics": self.metrics.to_dict(),
            "is_correlated": self.is_correlated,
            "threshold_db": self.threshold_db,
            "warnings": self.warnings,
            "fsv": self.fsv,
            "correlation": self.correlation,
        }


def compute_fsv_assessment(
    sim: MeasurementData,
    measured: MeasurementData,
    *,
    traces: tuple[str, ...] = ("s11", "s21"),
    n_points: int | None = None,
) -> dict[str, Any]:
    """D12 FSV 曲线级评估（补强17：correlate 接 D12，IEEE 1597.1 口径）。

    对 S11/S21 dB 幅度曲线调 `core.fsv.fsv`（全仓唯一 FSV 计算路径，与
    service.calibration_service.fsv_curve_levels 同源不二实现），按迹线
    返回六级评级。best-effort：端口不足 / 公共轴点数 < MIN_POINTS /
    **trace 名不在白名单**（S-1 C-06①）等一律记
    {"ok": False, "error": ...}，不抛异常（#105）。

    Returns:
        {trace: {"ok", "adm_grade", "fdm_grade", "gdm_grade", "adm_mean",
        "fdm_mean_abs", "gdm_mean", "gdm_grade_level", "gdm_spread",
        "n_points"} | {"ok": False, "error"}}
    """
    from rfauto.core.fsv import fsv, to_jsonable

    out: dict[str, Any] = {}
    for trace in traces:
        try:
            # S-1 C-06① 2026-10-04：trace 名白名单——旧实现"非 s11 一律
            # 按 s21"（`(0,0) if trace=='s11' else (1,0)`），笔误名（如
            # "s12"/"S11"/"vswr"）被静默评估成 S21 曲线且结果挂在笔误键
            # 下无迹可查。白名单外显式报错（best-effort 契约：落本 trace
            # 的 error 条目，不炸循环、不影响其余 trace）。
            if str(trace).lower() not in _FSV_SUPPORTED_TRACES:
                raise ValueError(
                    f"不支持的 trace 名 {trace!r}（白名单 "
                    f"{sorted(_FSV_SUPPORTED_TRACES)}；旧实现会把任意非 "
                    "'s11' 名静默按 s21 评估）")
            row, col = _FSV_SUPPORTED_TRACES[str(trace).lower()]
            if max(row, col) >= sim.network.nports or max(row, col) >= measured.network.nports:
                raise ValueError(f"网络端口数不足，无法评估 {trace}")
            v_sim = 20 * np.log10(np.abs(sim.network.s[:, row, col]) + 1e-10)
            v_meas = 20 * np.log10(np.abs(measured.network.s[:, row, col]) + 1e-10)
            raw = to_jsonable(fsv(
                sim.network.f, v_sim, measured.network.f, v_meas, n_points=n_points))
            out[trace] = {
                "ok": True,
                "adm_grade": raw["adm_grade"],
                "fdm_grade": raw["fdm_grade"],
                "gdm_grade": raw["gdm_grade"],
                "adm_mean": raw["adm_mean"],
                "fdm_mean_abs": raw["fdm_mean_abs"],
                "gdm_mean": raw["gdm_mean"],
                "gdm_grade_level": raw["gdm_grade_level"],
                "gdm_spread": raw["gdm_spread"],
                "n_points": raw["n_points"],
            }
        except Exception as exc:
            out[trace] = {"ok": False, "error": str(exc)}
    return out


def compute_correlation(
    sim: MeasurementData,
    measured: MeasurementData,
    threshold_db: float = 3.0,
    *,
    with_fsv: bool = True,
    with_correlation: bool = True,
) -> CorrelationResult:
    """计算仿真 vs 测量相关性。

    threshold_db 缺省 3.0 的出处（S-1 C-06② 2026-10-04 注记）：
    **E9c 工程缺省值**（commit 775101d6，2026-08-31，扩展方案
    §E9c 首版引入），非文献推导阈值——规格深案
    §"1. 目标与定位"原文即如实标注"从拍脑袋阈值（现 threshold_db=3.0）
    升级为计量学口径"（En 判据项，方向已立、口径待定）；调用方需要
    严格门径请显式传参，勿把 3.0 当有出处的物理常数引用。

    频轴对齐走**真交集口径**（E1-1 修复 2026-10-04，runs/review_ge8e/
    e1_pipeline/REPORT.md；#287/#294 同族先例=en_report.align_frequency_axes）：
    argmin 最近邻 + 相对 1e-9 ulp 容差逐点配对（禁 searchsorted，#294 实证
    ulp 级频移越位一格）——旧实现"同点数前缀截断"在异频段/异栅输入下把
    不同频率的曲线逐点硬比（偏差恒 0 静默假通过，exp2 实证）。配对数=0
    抛 ValueError 拒绝假交集；部分配对如实记 n_unpaired_points+warning，
    指标只在公共频点子集上计算，freq_range_ghz 报配对（交集）区间。

    Args:
        sim: 仿真数据
        measured: 测量数据
        threshold_db: 偏差阈值 (dB)，超过则标记为不相关
        with_fsv: True（默认）= 并行输出 D12 FSV 曲线级评级（加性字段，
                  不影响 is_correlated 判定）
        with_correlation: True（默认）= 并行输出 T1-C-10 皮尔逊相关系数 +
                  GUM 双侧区间（s11/s21 dB 曲线各一；加性字段）

    Returns:
        CorrelationResult

    Raises:
        ValueError: 两侧频轴无公共点（最近邻配对容差内零配对）。
    """
    # 频轴真交集配对（argmin 最近邻 + ulp 容差，禁 searchsorted）
    f_sim = np.asarray(sim.network.f, dtype=float)
    f_meas = np.asarray(measured.network.f, dtype=float)
    idx_sim, idx_meas, n_unpaired = align_frequency_axes(f_sim, f_meas)
    if idx_sim.size == 0:
        raise ValueError(
            f"仿真与测量频轴无公共点（sim {f_sim[0]:.6g}–{f_sim[-1]:.6g} Hz "
            f"共 {f_sim.size} 点 vs measured {f_meas[0]:.6g}–{f_meas[-1]:.6g} Hz "
            f"共 {f_meas.size} 点，最近邻配对容差 1e-9 相对）——相关性比较无定义，"
            "拒绝假交集（E1-1，runs/review_ge8e/e1_pipeline/REPORT.md）")

    # 提取 S 参数（按配对索引取交集子集）
    s_sim = sim.network.s[idx_sim]
    s_meas = measured.network.s[idx_meas]

    # 计算 S11 和 S21 的幅度偏差 (dB)
    s11_sim_db = 20 * np.log10(np.abs(s_sim[:, 0, 0]) + 1e-10)
    s11_meas_db = 20 * np.log10(np.abs(s_meas[:, 0, 0]) + 1e-10)
    s21_sim_db = 20 * np.log10(np.abs(s_sim[:, 1, 0]) + 1e-10)
    s21_meas_db = 20 * np.log10(np.abs(s_meas[:, 1, 0]) + 1e-10)

    s11_dev = np.abs(s11_sim_db - s11_meas_db)
    s21_dev = np.abs(s21_sim_db - s21_meas_db)

    freq_range = (
        float(f_sim[idx_sim[0]]) / 1e9,
        float(f_sim[idx_sim[-1]]) / 1e9,
    )

    metrics = CorrelationMetrics(
        s11_max_deviation_db=float(np.max(s11_dev)),
        s21_max_deviation_db=float(np.max(s21_dev)),
        s11_mean_deviation_db=float(np.mean(s11_dev)),
        s21_mean_deviation_db=float(np.mean(s21_dev)),
        freq_range_ghz=freq_range,
        n_freq_points=int(idx_sim.size),
        n_unpaired_points=int(n_unpaired),
    )

    # 判断是否相关
    warnings = []
    is_correlated = True

    if metrics.n_unpaired_points > 0:
        warnings.append(
            f"频轴非完全同栅：{metrics.n_unpaired_points} 个仿真频点未配对，"
            f"指标只在 {metrics.n_freq_points} 个公共频点上计算（E1-1 真交集口径）")

    if metrics.s11_max_deviation_db > threshold_db:
        warnings.append(f"S11 最大偏差 {metrics.s11_max_deviation_db:.1f} dB 超过阈值 {threshold_db} dB")
        is_correlated = False

    if metrics.s21_max_deviation_db > threshold_db:
        warnings.append(f"S21 最大偏差 {metrics.s21_max_deviation_db:.1f} dB 超过阈值 {threshold_db} dB")
        is_correlated = False

    return CorrelationResult(
        sim_file=sim.source_file,
        measured_file=measured.source_file,
        metrics=metrics,
        is_correlated=is_correlated,
        threshold_db=threshold_db,
        warnings=warnings,
        fsv=compute_fsv_assessment(sim, measured) if with_fsv else None,
        # T1-C-10：S11/S21 dB 曲线的皮尔逊相关 + 双侧区间（加性字段；
        # 退化曲线 ok=False 如实内嵌，不影响既有偏差门语义）
        correlation={
            "s11": correlation_with_interval(s11_sim_db, s11_meas_db),
            "s21": correlation_with_interval(s21_sim_db, s21_meas_db),
        } if with_correlation else None,
    )


def generate_correlation_report(
    result: CorrelationResult,
    output_path: str | Path | None = None,
) -> str:
    """生成相关性报告（Markdown 格式）。

    Args:
        result: 相关性分析结果
        output_path: 输出文件路径（可选）

    Returns:
        Markdown 报告内容
    """
    status = "✅ 相关" if result.is_correlated else "❌ 不相关"

    report = f"""# 仿真 vs 测量相关性报告

## 概要

- **状态**: {status}
- **仿真文件**: {result.sim_file}
- **测量文件**: {result.measured_file}
- **阈值**: {result.threshold_db} dB

## 指标

| 指标 | 值 |
|------|-----|
| S11 最大偏差 | {result.metrics.s11_max_deviation_db:.2f} dB |
| S21 最大偏差 | {result.metrics.s21_max_deviation_db:.2f} dB |
| S11 平均偏差 | {result.metrics.s11_mean_deviation_db:.2f} dB |
| S21 平均偏差 | {result.metrics.s21_mean_deviation_db:.2f} dB |
| 频率范围 | {result.metrics.freq_range_ghz[0]:.1f} - {result.metrics.freq_range_ghz[1]:.1f} GHz |
| 频率点数 | {result.metrics.n_freq_points} |

"""

    if result.fsv:
        report += "## FSV 等级（D12, IEEE 1597.1）\n\n"
        for trace, f in result.fsv.items():
            if f.get("ok"):
                report += (
                    f"- **{trace.upper()}**: GDM={f['gdm_grade']}"
                    f" (mean {float(f['gdm_mean']):.4f})，"
                    f"ADM={f['adm_grade']}，FDM={f['fdm_grade']}\n"
                )
            else:
                report += f"- **{trace.upper()}**: 不可用（{f.get('error', 'unknown')}）\n"
        report += "\n"

    if result.correlation:
        report += "## 相关系数双侧区间（T1-C-10，GUM 口径 r ± k·u_r）\n\n"
        for trace, c in result.correlation.items():
            if c.get("ok"):
                lo, hi = c["interval"]
                report += (
                    f"- **{trace.upper()}**: r={c['r']:.4f}"
                    f"，{c['k']:.0f}×双侧区间 [{lo:.4f}, {hi:.4f}]"
                    f"（n={c['n']}）\n"
                )
            else:
                report += (f"- **{trace.upper()}**: 不可用"
                           f"（{c.get('note', 'unknown')}）\n")
        report += "\n"

    if result.warnings:
        report += "## Warnings\n\n"
        for w in result.warnings:
            report += f"- {w}\n"
        report += "\n"

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")

    return report
