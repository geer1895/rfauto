"""相关性报告。

仿真 vs 测量相关性分析：
- 计算 S 参数偏差（幅度/相位）
- 生成相关性报告（JSON + Markdown）
- 双基线语义分离：sim=hard fail / measured=soft warn
- 补强：correlate 接宏模型保真裁判——S11/S21 dB 幅度曲线并行走
  core.fsv（IEEE 1597.1）曲线级 ADM/FDM/GDM 六级评级，best-effort 加性
  字段（#105），不改变既有 dB 阈值门语义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.measurement.import_data import MeasurementData


@dataclass
class CorrelationMetrics:
    """相关性指标。"""
    s11_max_deviation_db: float
    s21_max_deviation_db: float
    s11_mean_deviation_db: float
    s21_mean_deviation_db: float
    freq_range_ghz: tuple[float, float]
    n_freq_points: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "s11_max_deviation_db": round(self.s11_max_deviation_db, 2),
            "s21_max_deviation_db": round(self.s21_max_deviation_db, 2),
            "s11_mean_deviation_db": round(self.s11_mean_deviation_db, 2),
            "s21_mean_deviation_db": round(self.s21_mean_deviation_db, 2),
            "freq_range_ghz": list(self.freq_range_ghz),
            "n_freq_points": self.n_freq_points,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_file": self.sim_file,
            "measured_file": self.measured_file,
            "metrics": self.metrics.to_dict(),
            "is_correlated": self.is_correlated,
            "threshold_db": self.threshold_db,
            "warnings": self.warnings,
            "fsv": self.fsv,
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
    返回六级评级。best-effort：端口不足 / 公共轴点数 < MIN_POINTS 等一律
    记 {"ok": False, "error": ...}，不抛异常（#105）。

    Returns:
        {trace: {"ok", "adm_grade", "fdm_grade", "gdm_grade", "adm_mean",
        "fdm_mean_abs", "gdm_mean", "gdm_grade_level", "gdm_spread",
        "n_points"} | {"ok": False, "error"}}
    """
    from rfauto.core.fsv import fsv, to_jsonable

    out: dict[str, Any] = {}
    for trace in traces:
        try:
            row, col = (0, 0) if trace == "s11" else (1, 0)
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
) -> CorrelationResult:
    """计算仿真 vs 测量相关性。

    Args:
        sim: 仿真数据
        measured: 测量数据
        threshold_db: 偏差阈值 (dB)，超过则标记为不相关
        with_fsv: True（默认）= 并行输出 D12 FSV 曲线级评级（加性字段，
                  不影响 is_correlated 判定）

    Returns:
        CorrelationResult
    """
    # 提取 S 参数
    s_sim = sim.network.s
    s_meas = measured.network.s

    # 确保频率点数一致（取交集）
    n_freq = min(s_sim.shape[0], s_meas.shape[0])
    s_sim = s_sim[:n_freq]
    s_meas = s_meas[:n_freq]

    # 计算 S11 和 S21 的幅度偏差 (dB)
    s11_sim_db = 20 * np.log10(np.abs(s_sim[:, 0, 0]) + 1e-10)
    s11_meas_db = 20 * np.log10(np.abs(s_meas[:, 0, 0]) + 1e-10)
    s21_sim_db = 20 * np.log10(np.abs(s_sim[:, 1, 0]) + 1e-10)
    s21_meas_db = 20 * np.log10(np.abs(s_meas[:, 1, 0]) + 1e-10)

    s11_dev = np.abs(s11_sim_db - s11_meas_db)
    s21_dev = np.abs(s21_sim_db - s21_meas_db)

    freq_range = (
        float(sim.network.f[0]) / 1e9,
        float(sim.network.f[-1]) / 1e9,
    )

    metrics = CorrelationMetrics(
        s11_max_deviation_db=float(np.max(s11_dev)),
        s21_max_deviation_db=float(np.max(s21_dev)),
        s11_mean_deviation_db=float(np.mean(s11_dev)),
        s21_mean_deviation_db=float(np.mean(s21_dev)),
        freq_range_ghz=freq_range,
        n_freq_points=n_freq,
    )

    # 判断是否相关
    warnings = []
    is_correlated = True

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

    if result.warnings:
        report += "## Warnings\n\n"
        for w in result.warnings:
            report += f"- {w}\n"
        report += "\n"

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")

    return report
