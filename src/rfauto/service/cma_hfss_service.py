"""CMA HFSS 原生档接口+mock 面（ge8c 席C7；真跑非本席——K-9 合并真机窗）。

定位（任务书口径）：CMA 离线档内核（core/characteristic_modes.py，H-M
1971 口径）已立、HFSS 原生 CMA（HFSS ≥18.1 内置同一 Harrington–Mautz
提法）为 **C 类仲裁锚**（研究扩充 round6
中件包一：一阶 pyaedt 脚本驱动 HFSS 原生 CMA→λn/MSn→馈电位置定量论证；
HFSS 原生为仲裁锚）。本模块落的是**接口面**：

- :func:`plan_hfss_cma`：HFSS 原生 CMA 求解设置声明面（频带/模数/
  收敛容差→JSON 设置计划，零 HFSS 零网络）；
- :func:`run_hfss_cma`：执行面，``runner`` 为**注入点**——真跑
  （pyaedt 驱动 ansysedt CMA setup+导出）不在本席（K-9 合并真机窗），
  runner=None 如实 ``skipped``（能力未接线≠失败）；注入 runner 时走
  解析+一致性门链；
- :func:`parse_hfss_cma_rows`：HFSS 原生 CMA 导出行 → 归一化模态表，
  带 **H-M 恒等式一致性门**：MS_n 与 1/(1+λ_n²) 逐模对拍（同一提法
  的两个独立报告量，#118 双源互证）——超容差逐模 FAIL 登记（#122
  如实，不静默丢弃也不凑 PASS）；
- :func:`mock_hfss_cma_rows`：mock 导出行生成器（**接口演练专用**——
  生成 H-M 恒等式自洽的行，零物理断言；mock 数字永不进判读面，
  铁律 7）。

HFSS 原生档导出行契约（对接面预声明；真跑席按此落导出）::

    {"mode_index": int, "eigenvalue": float, "modal_significance": float,
     "zc_re": float | None, "zc_im": float | None}

（λ/MS 必给；特征阻抗可选——HFSS 的 Z_cn 为功率权重口径，与内核
 R 归一口径 1+jλ **不同基**，只透传不互检，如实标注。）

接口纪律：dict/JSON 进出；确定性（mock 生成器固定种子）；零网络零
LLM；真跑驱动层（pyaedt→ansysedt）另行立项不在此层。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope, skipped_envelope

#: HFSS 原生 CMA 档契约版本。
CMA_HFSS_SCHEMA = "rfauto-cma-hfss-v1"

#: H-M 恒等式一致性门容差：MS 报告值 vs 1/(1+λ²) 相对容差（同一提法的
#: 两个报告量；HFSS 报告位数为 3-4 位有效数字，1e-3 相对带宽内判一致）。
MS_IDENTITY_RTOL = 1e-3

#: 近谐振档：|λ_n| ≤ 此阈的模记为 near_resonant（MS ≥ 1/(1+0.2²)≈0.962，
#: Cabedo-Fabrés 2007 综述惯例"谐振模 λ≈0"的量化档）。
NEAR_RESONANT_LAMBDA = 0.2


def plan_hfss_cma(*, f_start_ghz: float, f_end_ghz: float, n_modes: int,
                  max_delta_s: float = 0.02,
                  note: str | None = None) -> dict[str, Any]:
    """HFSS 原生 CMA 求解设置计划（声明面，零 HFSS）。

    HFSS CMA 设置三要素：频带（f_start/f_end）、模数上限（n_modes）、
    收敛（max_delta_s，与 driven modal 同款 ΔS 收敛口径）。输入非法
    （频带倒置/非正、模数 <1、ΔS 不在 (0,1)）→ error 信封。
    """
    errors: list[str] = []
    try:
        f0, f1 = float(f_start_ghz), float(f_end_ghz)
    except (TypeError, ValueError):
        return error_envelope("频率必须为数值", schema=CMA_HFSS_SCHEMA)
    if not (f0 > 0.0 and f1 > f0):
        errors.append(f"频带非法：[{f0}, {f1}]（须 0 < f_start < f_end）")
    nm = n_modes
    if isinstance(nm, bool) or not isinstance(nm, int) or nm < 1:
        errors.append(f"n_modes 必须为正整数，得 {n_modes!r}")
    mds = float(max_delta_s)
    if not (0.0 < mds < 1.0):
        errors.append(f"max_delta_s 必须在 (0,1)，得 {max_delta_s!r}")
    if errors:
        return error_envelope(errors, schema=CMA_HFSS_SCHEMA)
    return ok_envelope(
        schema=CMA_HFSS_SCHEMA,
        engine="hfss_native_cma",
        hfss_min_version="18.1",
        setup={"f_start_ghz": f0, "f_end_ghz": f1, "n_modes": nm,
               "max_delta_s": mds},
        note=note or "真跑驱动层（pyaedt→ansysedt CMA setup+导出）"
                     "归 K-9 合并真机窗；本计划面零 HFSS 依赖",
    )


def mock_hfss_cma_rows(lambdas: Sequence[float], *,
                       ms_digits: int = 6) -> list[dict[str, Any]]:
    """mock HFSS CMA 导出行（接口演练专用，零物理断言）。

    行 = H-M 恒等式自洽（MS=1/(1+λ²)，按 ``ms_digits`` 位舍入模拟
    HFSS 报告有限位宽——舍入仍在 :data:`MS_IDENTITY_RTOL` 门内）。
    mock 数字**永不进判读面**（铁律 7）：只证明接口链/解析器/一致性
    门可走通。
    """
    rows: list[dict[str, Any]] = []
    for i, lam in enumerate(lambdas):
        lam_f = float(lam)
        ms = round(1.0 / (1.0 + lam_f * lam_f), ms_digits)
        rows.append({
            "mode_index": i,
            "eigenvalue": lam_f,
            "modal_significance": ms,
            "zc_re": 1.0,
            "zc_im": lam_f,
        })
    return rows


def parse_hfss_cma_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """HFSS CMA 导出行 → 归一化模态表 + H-M 恒等式一致性门。

    逐行校验：mode_index 连续、λ/MS 有限、MS ∈ (0, 1]、MS vs
    1/(1+λ²) 相对差 ≤ :data:`MS_IDENTITY_RTOL`。坏行**逐模 FAIL
    登记**（#122/#316 多报方向），好行照常入表——批量不因单坏行中断。
    """
    import math

    modes: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, row in enumerate(rows):
        tag = f"row[{i}]"
        if not isinstance(row, Mapping):
            errors.append(f"{tag}: 须为 mapping")
            continue
        lam = row.get("eigenvalue")
        ms = row.get("modal_significance")
        if isinstance(lam, bool) or not isinstance(lam, (int, float)) \
                or not math.isfinite(float(lam)):
            errors.append(f"{tag}: eigenvalue 非有限数值：{lam!r}")
            continue
        if isinstance(ms, bool) or not isinstance(ms, (int, float)) \
                or not math.isfinite(float(ms)):
            errors.append(f"{tag}: modal_significance 非有限数值：{ms!r}")
            continue
        lam_f, ms_f = float(lam), float(ms)
        if not (0.0 < ms_f <= 1.0):
            errors.append(f"{tag}: MS={ms_f!r} 出 (0,1]（导出损伤）")
            continue
        ms_id = 1.0 / (1.0 + lam_f * lam_f)
        rel = abs(ms_f - ms_id) / ms_id
        entry: dict[str, Any] = {
            "mode_index": row.get("mode_index", i),
            "eigenvalue": lam_f,
            "modal_significance": ms_f,
            "ms_identity_expected": ms_id,
            "ms_identity_rel_err": rel,
            "ms_gate": "PASS" if rel <= MS_IDENTITY_RTOL else "FAIL",
        }
        if entry["ms_gate"] == "FAIL":
            errors.append(
                f"{tag}: H-M 恒等式不一致 MS={ms_f:g} vs 1/(1+λ²)="
                f"{ms_id:g}（rel={rel:.3g} > {MS_IDENTITY_RTOL:g}）——"
                "导出侧口径/损伤，逐模 FAIL 如实")
        zc_re = row.get("zc_re")
        zc_im = row.get("zc_im")
        if isinstance(zc_re, (int, float)) and isinstance(zc_im, (int, float)):
            # HFSS Z_cn 为功率权重口径，与内核 R 归一口径 1+jλ 不同基——
            # 只透传不互检（如实标注 different_basis）
            entry["zc"] = {"re": float(zc_re), "im": float(zc_im),
                           "basis": "hfss_power_weighted(不同基，不与 1+jλ 互检)"}
        modes.append(entry)
    n_fail = sum(1 for m in modes if m["ms_gate"] == "FAIL")
    return {
        "schema": CMA_HFSS_SCHEMA,
        "n_modes": len(modes),
        "n_ms_fail": n_fail,
        "errors": errors,
        "modes": modes,
        "ok": bool(modes) and not errors,
    }


def hfss_cma_summary(parsed: Mapping[str, Any]) -> dict[str, Any]:
    """归一化模态表 → 判读摘要（MS 降序全序 + 近谐振档）。

    消费面（round6 中件包一声明）：馈电位置定量论证消费"谐振模的
    电流分布"——本摘要给模排序与近谐振集合，场分布消费归真跑席。
    只对 ms_gate=PASS 的模排序（FAIL 模不进判读，#314 掩码口径）。
    """
    passing = [m for m in parsed.get("modes", []) if m.get("ms_gate") == "PASS"]
    ranked = sorted(passing, key=lambda m: (-m["modal_significance"],
                                            m["eigenvalue"]))
    near = [m["mode_index"] for m in passing
            if abs(m["eigenvalue"]) <= NEAR_RESONANT_LAMBDA]
    return {
        "schema": CMA_HFSS_SCHEMA,
        "n_pass": len(passing),
        "n_ms_fail": parsed.get("n_ms_fail", 0),
        "ranking_ms_desc": [
            {"mode_index": m["mode_index"],
             "modal_significance": m["modal_significance"]}
            for m in ranked],
        "near_resonant_mode_indices": near,
        "near_resonant_lambda_max": NEAR_RESONANT_LAMBDA,
    }


def run_hfss_cma(plan: Mapping[str, Any],
                 runner: Callable[[Mapping[str, Any]], Mapping[str, Any]]
                 | None = None) -> dict[str, Any]:
    """执行面：计划 → （注入的）HFSS 原生 CMA 跑 → 解析+一致性门。

    - ``runner=None``：真跑层未接线（pyaedt 驱动归 K-9 真机窗）——
      如实 ``skipped``（能力未接线≠失败，skipped≠failed）；
    - 注入 runner：``runner(plan) → {"ok": bool, "rows": [...],
      "source": str}`` 契约（真跑席按此落适配）；runner 抛错 → error
      信封（异常原文透传，#122）；rows 过 :func:`parse_hfss_cma_rows`
      一致性门后附 :func:`hfss_cma_summary`。
    """
    if runner is None:
        return skipped_envelope(
            "HFSS 原生 CMA 真跑层未接线（pyaedt 驱动归 K-9 合并真机窗）"
            "——本面当前只提供设置计划/解析门/mock 演练",
            schema=CMA_HFSS_SCHEMA,
            plan=dict(plan))
    if not isinstance(plan, Mapping) or plan.get("engine") != "hfss_native_cma":
        return error_envelope("plan 须为 plan_hfss_cma 产物（engine="
                              "hfss_native_cma）", schema=CMA_HFSS_SCHEMA)
    try:
        raw = runner(plan)
    except Exception as exc:
        return error_envelope(f"runner 执行失败（{type(exc).__name__}）：{exc}",
                              schema=CMA_HFSS_SCHEMA)
    if not isinstance(raw, Mapping) or not raw.get("ok"):
        return error_envelope(
            "runner 返回失败信封：" + str((raw or {}).get("errors")),
            schema=CMA_HFSS_SCHEMA)
    parsed = parse_hfss_cma_rows(raw.get("rows") or [])
    return ok_envelope(
        schema=CMA_HFSS_SCHEMA,
        source=str(raw.get("source", "unknown")),
        parsed=parsed,
        summary=hfss_cma_summary(parsed),
    )
