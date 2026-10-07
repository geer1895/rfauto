"""LM-3 extended hemispherical 透镜 service 接线（JSON 进出，CLI/MCP 壳共享）。

薄壳（分层铁律 3/4）：数值只在确定性内核 core/lens_hemispherical
（Filipovic'93 三锚点闭式 + 射线追踪双路径验证，#118 互证）；本模块
不产生物理数字，只做契约适配与异常到 JSON 信封的翻译。信封契约（与
rotman_lens_service 同族）：ok=False + error 字符串绝不抛出。complex
返回值（quarter_wave_input_impedance）在本层转 JSON 安全形态。
"""

from __future__ import annotations

from rfauto.core import lens_hemispherical as lh
from rfauto.service.envelope import ok_envelope

#: 数值内核期可预期的异常族（进信封，不外抛）
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError, ArithmeticError)


def lens_hemispherical_design(
    radius_m: float,
    n: float | None = None,
    lr: float | None = None,
    feed_regime: str = lh.FEED_SINGLE_UNIT,
    lambda0_m: float | None = None,
    with_cap: bool = False,
    cap_n: float | None = None,
    aperture_efficiency: float | None = None,
    scan_theta_max_deg: float = 30.0,
) -> dict:
    """设计 + 验证摘要（轻量面）。

    验证摘要含 aplanatic stigmatism 恒等式偏差（应 <1e-9，实测 ~1e-14）
    与 ±scan_theta_max_deg 准直扫描极小是否落 peak-directivity 锚 ±5%
    位置带（预声明判据，#122）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        kwargs: dict = {"radius_m": radius_m, "feed_regime": feed_regime}
        if n is not None:
            kwargs["n"] = n
        if lr is not None:
            kwargs["lr"] = lr
        if lambda0_m is not None:
            kwargs["lambda0_m"] = lambda0_m
        if with_cap:
            kwargs["with_cap"] = True
        if cap_n is not None:
            kwargs["cap_n"] = cap_n
        if aperture_efficiency is not None:
            kwargs["aperture_efficiency"] = aperture_efficiency
        design = lh.design_lens(**kwargs)
        n_eff = design.n
        stig_dev = lh.aplanatic_stigmatism_dev(n_eff)
        scan = lh.collimation_scan(n_eff, theta_max_deg=scan_theta_max_deg)
        anchor_band = (0.385 * 0.95, 0.385 * 1.05)
        return ok_envelope(
            data={
                "design": design.to_dict(),
                "validation": {
                    "aplanatic_stigmatism_dev": stig_dev,
                    "scan_theta_max_deg": scan["theta_max_deg"],
                    "scan_best_lr": scan["best_lr"],
                    "scan_best_residual_rms_deg": scan["best_residual_rms_deg"],
                    "paraxial_lr": scan["paraxial_lr"],
                    "scan_best_lr_in_anchor_band": (
                        anchor_band[0] <= scan["best_lr"] <= anchor_band[1]
                    ),
                },
            },
        )
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}


def lens_hemispherical_cap(
    n_lens: float,
    n_cap: float | None = None,
    n_out: float = 1.0,
    lambda0_m: float | None = None,
) -> dict:
    """λ/4 匹配帽反射/厚度载荷（双路径 Γ，complex 转 JSON 安全形态）。

    Returns:
        JSON 可序列化 dict；失败时 ``{"ok": False, "error": str}`` 不抛出。
    """
    try:
        kwargs: dict = {"n_lens": n_lens, "n_out": n_out}
        if n_cap is not None:
            kwargs["n_cap"] = n_cap
        if lambda0_m is not None:
            kwargs["lambda0_m"] = lambda0_m
        res = lh.cap_reflection(**kwargs)
        return ok_envelope(data=res)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
