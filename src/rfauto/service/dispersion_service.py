"""色散材料适应性报告信封（D1 装车：审查 C 分片"内核在、adapters 零调用"）。

core/dispersion.py（Debye / Djordjevic-Sarkar 因果宽带模型，506 行）此前
生产零消费。本模块提供**最小安全口径**装车：dispersion_fitness_report——
用 D-S 模型（configs/materials.yaml 已有 RO4350B dispersion 条目）算给定
材料在频带内 εr/tanδ 的变化幅度，判定"常数 εr 近似是否成立"（默认 ≤2% 门），
不成立时给修正建议（openEMS AddDjordjevicSarkarMaterial 参数，确定性内核
导出）。

**只读报告**：不改任何模板/适配器的渲染行为——"模板接色散渲染"属语义
变更（需锚重跑）。数值全部出自 core/dispersion 确定性求值
（铁律 7）；零网络、零求解器。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

#: 常数 εr 近似门：带内 ε' 相对漂移 ≤ 2% 视为常数近似成立
DEFAULT_MAX_EPS_R_DRIFT = 0.02
#: 频带内采样点数（对数均布，含两端）
DEFAULT_N_SAMPLES = 7


def _load_materials_yaml(config_path: str | Path | None) -> dict[str, Any]:
    """读 materials.yaml 的 materials 段（只读；失败返回空表）。"""
    import yaml

    if config_path is None:
        from rfauto.core.dispersion import _materials_path

        path = _materials_path(None)
    else:
        path = Path(config_path)
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError:
        return {}
    materials = data.get("materials", {})
    return materials if isinstance(materials, dict) else {}


def _dispersion_material_names(materials: dict[str, Any]) -> list[str]:
    """有 dispersion 条目的材料名（排序，供提示/审计）。"""
    return sorted(
        name for name, block in materials.items()
        if isinstance(block, dict) and block.get("dispersion")
    )


def _band_samples_hz(band_ghz: Any, n_samples: int) -> list[float]:
    """频带 [lo, hi] GHz → 采样频率 Hz 列表（对数均布含两端；lo==hi 退化为单点）。

    入参非法抛 ValueError（由调用方转信封错误）。
    """
    if not isinstance(band_ghz, (list, tuple)) or len(band_ghz) != 2:
        raise ValueError(f"band_ghz 应为 [f_low_ghz, f_high_ghz]，收到 {band_ghz!r}")
    try:
        lo, hi = float(band_ghz[0]), float(band_ghz[1])
    except (TypeError, ValueError):
        raise ValueError(f"频带端点必须为数字（GHz），收到 {band_ghz!r}") from None
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo <= 0.0 or hi <= 0.0:
        raise ValueError(f"频带端点必须为正的有限值（GHz），收到 {band_ghz!r}")
    if lo > hi:
        raise ValueError(f"要求 f_low <= f_high，收到 {band_ghz!r}")
    if lo == hi:
        return [lo * 1e9]
    n = max(2, int(n_samples))
    step = (math.log10(hi) - math.log10(lo)) / (n - 1)
    return [10.0 ** (math.log10(lo) + i * step) * 1e9 for i in range(n)]


def dispersion_fitness_report(
    material: str,
    band_ghz: list[float] | tuple[float, float] | None = None,
    *,
    config_path: str | Path | None = None,
    max_eps_r_drift: float = DEFAULT_MAX_EPS_R_DRIFT,
    n_samples: int = DEFAULT_N_SAMPLES,
) -> dict[str, Any]:
    """材料在给定频带内的色散适应性报告（D1 装车，只读）。

    参数：
        material: materials.yaml 材料键（须含 dispersion 条目；已配
            rogers4350b_h0.508_dispersion——RO4350B datasheet 单点
            Dk=3.66/Df=0.0037 @10GHz）
        band_ghz: [f_low, f_high]（GHz）；缺省用该材料 D-S 拟合频带端点
        config_path: materials.yaml 路径（缺省 configs/materials.yaml）
        max_eps_r_drift: 常数 εr 近似门（相对漂移，默认 0.02=2%）
        n_samples: 带内采样点数（对数均布，≥2）

    返回（JSON 信封）：
        ok / material / band_ghz / f_meas_ghz / eps_r_at_meas /
        tan_delta_at_meas / samples[] / eps_r_drift_pct / tan_delta_drift_pct /
        gate{passed, verdict, max_eps_r_drift_pct, message} /
        correction（过门时给 openEMS AddDjordjevicSarkarMaterial 参数与
        多极 Debye 导出摘要）/ available_dispersion_materials /
        config_note / follow_up_note；材料未知或无 dispersion 条目 →
        ok=False + errors + 可用材料提示。
    """
    materials = _load_materials_yaml(config_path)
    available = _dispersion_material_names(materials)
    if material not in materials:
        return {
            "ok": False,
            "errors": [f"未知材料: {material}，可用: {sorted(materials) or '（materials.yaml 不可读）'}"],
            "available_dispersion_materials": available,
        }
    block = materials[material]
    if not isinstance(block, dict) or not block.get("dispersion"):
        return {
            "ok": False,
            "errors": [
                f"材料 {material} 没有 dispersion 条目（常数 εr={block.get('epsilon_r')}、"
                f"tanδ={block.get('loss_tangent')}），无法评估带内漂移；"
                f"色散评估请用: {available or '无（先在 materials.yaml 增补 dispersion 条目）'}",
            ],
            "available_dispersion_materials": available,
        }

    from rfauto.core.dispersion import load_dispersion_material

    try:
        model = load_dispersion_material(material, config_path)
    except (KeyError, ValueError, OSError, TypeError) as exc:
        return {
            "ok": False,
            "errors": [f"色散模型构造失败（材料 {material}）: {exc}"],
            "available_dispersion_materials": available,
        }

    effective_band = (
        band_ghz if band_ghz is not None else (model.f1_hz / 1e9, model.f2_hz / 1e9)
    )
    try:
        freqs_hz = _band_samples_hz(effective_band, n_samples)
    except ValueError as exc:
        return {
            "ok": False,
            "errors": [str(exc)],
            "available_dispersion_materials": available,
        }

    f_meas_hz = model.f_meas_hz if model.f_meas_hz is not None else math.sqrt(model.f1_hz * model.f2_hz)
    eps_r_meas = float(model.epsilon_r(f_meas_hz))
    tan_d_meas = float(model.loss_tangent(f_meas_hz))

    samples: list[dict[str, float]] = []
    eps_r_drift = 0.0
    tan_d_drift = 0.0
    for f_hz in freqs_hz:
        eps_r = float(model.epsilon_r(f_hz))
        tan_d = float(model.loss_tangent(f_hz))
        eps_r_drift = max(eps_r_drift, abs(eps_r - eps_r_meas) / eps_r_meas)
        tan_d_drift = max(tan_d_drift, abs(tan_d - tan_d_meas) / tan_d_meas) if tan_d_meas > 0 else 0.0
        samples.append({
            "f_ghz": f_hz / 1e9,
            "eps_r": eps_r,
            "tan_delta": tan_d,
        })

    gate_passed = eps_r_drift <= float(max_eps_r_drift)
    verdict = "constant_eps_r_ok" if gate_passed else "dispersion_recommended"
    gate_pct = float(max_eps_r_drift) * 100.0
    report: dict[str, Any] = {
        "ok": True,
        "material": material,
        "band_ghz": [freqs_hz[0] / 1e9, freqs_hz[-1] / 1e9],
        "f_meas_ghz": f_meas_hz / 1e9,
        "eps_r_at_meas": eps_r_meas,
        "tan_delta_at_meas": tan_d_meas,
        "samples": samples,
        "eps_r_drift_pct": eps_r_drift * 100.0,
        "tan_delta_drift_pct": tan_d_drift * 100.0,
        "gate": {
            "passed": gate_passed,
            "verdict": verdict,
            "max_eps_r_drift_pct": gate_pct,
            "message": (
                f"带内 ε' 相对漂移 {eps_r_drift * 100:.3f}% ≤ 门 {gate_pct:.1f}%："
                "常数 εr 近似成立"
                if gate_passed else
                f"带内 ε' 相对漂移 {eps_r_drift * 100:.3f}% > 门 {gate_pct:.1f}%："
                "常数 εr 近似不成立，建议改用色散材料渲染（见 correction）"
            ),
        },
        "available_dispersion_materials": available,
        "config_note": (
            "configs/materials.yaml 已有 RO4350B 色散条目 "
            "rogers4350b_h0.508_dispersion（Dk=3.66/Df=0.0037 @10GHz，"
            "openEMS 官方频带口径 f1=1MHz/f2=200GHz）"
        ),
        "follow_up_note": (
            "本报告只读：不修改模板/适配器渲染行为；模板接 D-S 色散渲染"
            "（AddDjordjevicSarkarMaterial / 多极 Debye）属语义变更，需重跑锚"
        ),
    }
    if not gate_passed:
        report["correction"] = {
            "advice": (
                "用 Djordjevic-Sarkar 因果宽带材料替换常数 εr 渲染：openEMS 走 "
                "AddDjordjevicSarkarMaterial（单点拟合，官方口径）；"
                "HFSS 走多极 Debye 材料属性（EpsilonDelta_i/EpsilonRelaxTime_i）"
            ),
            "openems_sarkar_kwargs": model.to_openems_sarkar_kwargs(),
            "openems_debye_export": model.to_openems(),
        }
    return report
