"""F-L 第 1 步：场效应管噪声模型 service 面（JSON 进出，规则 4；CLI/MCP 薄壳）。

消费 core/fet_noise.py 确定性内核（全部物理数字出自内核，规则 7），本服务
零物理公式：入参 payload → 白名单收敛 → 内核四参 + 可选等噪声圆组/LNA 匹配
建议/fT/Fukui 对照 → JSON 信封返回。任何入参异常（缺键/非法值/内核
ValueError）→ ``ok=False`` + error 文案，**不抛**（服务层信封纪律）。

payload 约定（全部可选除 model/f_hz/tg_k/td_k）：
    model: {cgs_f, ri_ohm, gm_s, gds_s, rg_ohm?, rs_ohm?, cgd_f?}（SI）
    f_hz, tg_k, td_k: 频点与两等效温度（必填）
    t0_k?, z0?, trg_k?, trs_k?: 口径可选项
    nf_targets_db?: [float, ...] → 每档一张等噪声圆（圆心+半径）
    sparams?: [[s11,s12],[s21,s22]] 复数 2x2 → 附 LNA 源匹配建议+增益
    with_fukui?: bool → 附 Fukui 经验式对照（kf 按参考频点自标定，量级带
    语义，见 core.fet_noise.fukui_fmin docstring）
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.fet_noise import (
    FetSmallSignal,
    fukui_fmin,
    lna_source_match,
    noise_circle,
    pospieszalski_noise_params,
    transition_frequency_hz,
)
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
FET_NOISE_SERVICE_SCHEMA_VERSION = "1.0"

_MODEL_KEYS = ("cgs_f", "ri_ohm", "gm_s", "gds_s", "rg_ohm", "rs_ohm", "cgd_f")
_MODEL_REQUIRED = ("cgs_f", "ri_ohm", "gm_s", "gds_s")


def _build_model(obj: Any) -> FetSmallSignal:
    """白名单收敛 model 字段（缺必填键显式报错；缺可选键取缺省 0.0）。"""
    if not isinstance(obj, dict):
        raise ValueError("payload.model 必须为 dict")
    kwargs: dict[str, float] = {}
    for key in _MODEL_REQUIRED:
        if obj.get(key) is None:
            raise ValueError(f"payload.model 缺必填键 {key}")
        kwargs[key] = float(obj[key])
    for key in ("rg_ohm", "rs_ohm", "cgd_f"):
        if obj.get(key) is not None:
            kwargs[key] = float(obj[key])
    return FetSmallSignal(**kwargs).validate()


def _build_sparams(obj: Any) -> list[list[complex]]:
    """[[s11,s12],[s21,s22]]（re/im dict 或 [re,im] 对）→ 2x2 复数列表。"""
    if not isinstance(obj, list) or len(obj) != 2:
        raise ValueError("payload.sparams 必须为 2x2 复数嵌套列表")

    def _cx(v: Any) -> complex:
        if isinstance(v, dict) and "re" in v and "im" in v:
            return complex(float(v["re"]), float(v["im"]))
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return complex(float(v[0]), float(v[1]))
        raise ValueError(f"sparams 元素形态非法: {v!r}")

    return [[_cx(obj[0][0]), _cx(obj[0][1])], [_cx(obj[1][0]), _cx(obj[1][1])]]


def fet_noise_evaluate(payload: dict) -> dict:
    """Pospieszalski 四噪声参数 + 可选圆组/匹配建议（JSON 信封，不抛）。"""
    try:
        if not isinstance(payload, dict):
            raise ValueError("payload 必须为 dict")
        for key in ("model", "f_hz", "tg_k", "td_k"):
            if payload.get(key) is None:
                raise ValueError(f"payload 缺必填键 {key}")
        model = _build_model(payload["model"])
        params = pospieszalski_noise_params(
            model,
            float(payload["f_hz"]),
            float(payload["tg_k"]),
            float(payload["td_k"]),
            t0_k=float(payload.get("t0_k", 290.0)),
            z0=float(payload.get("z0", 50.0)),
            trg_k=None if payload.get("trg_k") is None else float(payload["trg_k"]),
            trs_k=None if payload.get("trs_k") is None else float(payload["trs_k"]),
        )
        data: dict[str, Any] = {
            "noise_params": params.to_dict(),
            "ft_hz": transition_frequency_hz(model),
        }
        targets = payload.get("nf_targets_db")
        if targets is not None:
            if not isinstance(targets, list):
                raise ValueError("payload.nf_targets_db 必须为 list")
            circles = []
            for nf in targets:
                c = noise_circle(params, float(nf))
                circles.append({
                    "nf_db": float(nf),
                    "center": {"re": c.center.real, "im": c.center.imag},
                    "radius": c.radius,
                })
            data["noise_circles"] = circles
        if payload.get("sparams") is not None:
            data["lna_match"] = lna_source_match(params, _build_sparams(payload["sparams"]))
        if payload.get("with_fukui"):
            f_hz = float(payload["f_hz"])
            excess = params.fmin_linear - 1.0
            if excess > 0.0:
                r_total = model.rg_ohm + model.rs_ohm + model.ri_ohm
                kf_cal = excess * model.gm_s / (f_hz * model.cgs_f * math.sqrt(r_total))
            else:
                kf_cal = 0.0
            data["fukui"] = {
                "kf_calibrated_si": kf_cal,
                "fmin_linear": fukui_fmin(model, f_hz, kf_cal, include_ri=True)
                if kf_cal > 0.0
                else params.fmin_linear,
                "note": "kf 为 SI 口径自标定值；跨频量级互证带 ±30%（见内核 docstring）",
            }
        return ok_envelope(schema_version=FET_NOISE_SERVICE_SCHEMA_VERSION, data=data)
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "schema_version": FET_NOISE_SERVICE_SCHEMA_VERSION,
                "error": str(exc)}
