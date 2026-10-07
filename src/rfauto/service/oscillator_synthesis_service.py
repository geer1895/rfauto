"""F-L 振荡器综合 service 面（JSON 进出薄壳，规则 4；物理数字全部出自 core 内核，规则 7）。

消费 core/oscillator_synthesis.py（F-L 第 3 步内核）与 core/clock_noise.py
（F-E 件 2 积分器——rms 抖动闭环积分自检在这里做，内核零 import，#112
家族双向零耦合约定）。本服务零物理公式、零 IO（不读文件、不连网络）；
全部入口收 dict、返回 JSON 信封 {"ok", "schema_version", "result"|"error",
"provenance"}；ValueError/TypeError/KeyError → ok=False 不抛（service 层
JSON 进出契约）。判缺失一律 ``is not None``（数值 0.0 合法，#364④）。

入口：
- :func:`oscillator_frequency`：kind+元件值 → 振荡频率（colpitts/hartley/
  clapp/cross_coupled）；
- :func:`oscillator_design`：kind+目标频率+显式比值参数 → 元件值（反设计）；
- :func:`oscillator_startup_report`：负阻（串联/反射系数）与交叉耦合起振
  判据报告（可选大信号工作点/裕度扫描）；
- :func:`leeson_noise_report`：Leeson 模型 + 三段渐近段链 + clock_noise
  积分闭环（σ_φ 与 rms 抖动；段链渐近口径 vs 精确乘积式积分的相对差
  如实回告 chain_exact_rel_delta，不裁决取舍）。

诚实边界：Leeson 段链是渐近近似（内核边界②），拐角过渡带内两口径差异
可达 dB 量级（尤其积分下限深入 1/f³ 区时），调用方按消费面选口径；
F、f_c 等经验参数由调用方供给，本服务不标定；q_l 可直给或经
dro_q0/dro_beta 折算（Q_L=Q_0/(1+β)），路由如实回告 q_route。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import clock_noise
from rfauto.core import oscillator_synthesis as osc
from rfauto.service.envelope import ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
SCHEMA_VERSION = "1.0"

_PROVENANCE: dict[str, Any] = {
    "kernel": "rfauto.core.oscillator_synthesis",
    "integrator": "rfauto.core.clock_noise",
    "sources": [
        "Kurokawa 1973 negative-resistance oscillation criterion (secondary citation)",
        "Leeson 1966, Proc. IEEE 54(2):329-330 (secondary citation, form per task spec)",
        "Razavi RF Microelectronics 2nd ed. Ch.8 (secondary citation)",
    ],
}


def _envelope(build: Any) -> dict[str, Any]:
    """统一 JSON 信封：构建函数抛 ValueError/TypeError/KeyError → ok=False 不抛。"""
    try:
        result = build()
    except (ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "schema_version": SCHEMA_VERSION, "error": str(exc)}
    return ok_envelope(schema_version=SCHEMA_VERSION, result=result, provenance=dict(_PROVENANCE))


def _req(payload: dict[str, Any], key: str) -> Any:
    """必填参数读取（判缺失 is not None；0.0/False 值语义由内核守卫裁决）。"""
    value = payload.get(key)
    if value is None:
        raise ValueError(f"缺必填参数 {key}")
    return value


def _complex_pairs(value: Any, name: str) -> list[complex]:
    """JSON 复数数组收敛：[[re, im], ...] → list[complex]（bool 显式拒收）。"""
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{name} 必须为非空 [[re, im], ...] 列表")
    out: list[complex] = []
    for idx, item in enumerate(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"{name}[{idx}] 必须为 [re, im] 二元组")
        re_part, im_part = item[0], item[1]
        if isinstance(re_part, bool) or isinstance(im_part, bool):
            raise ValueError(f"{name}[{idx}] 不接受 bool")
        out.append(complex(float(re_part), float(im_part)))
    return out


# ─── 频率正问题 ──────────────────────────────────────────────────────────────


def oscillator_frequency(payload: dict[str, Any]) -> dict[str, Any]:
    """kind+元件值 → 振荡频率（Hz）。kind ∈ {colpitts, hartley, clapp, cross_coupled}。

    payload 必填（随 kind）：colpitts=(l_h, c1_f, c2_f)；hartley=(l1_h,
    l2_h, m_h, c_f)；clapp=(l_h, c1_f, c2_f, c3_f)；cross_coupled=(l_h, c_f)。
    """
    if not isinstance(payload, dict):
        return {"ok": False, "schema_version": SCHEMA_VERSION, "error": "payload 必须为 dict"}
    kind = payload.get("kind")

    def build() -> dict[str, Any]:
        if kind == "colpitts":
            f_hz = osc.colpitts_frequency(_req(payload, "l_h"), _req(payload, "c1_f"), _req(payload, "c2_f"))
        elif kind == "hartley":
            f_hz = osc.hartley_frequency(
                _req(payload, "l1_h"), _req(payload, "l2_h"), _req(payload, "m_h"), _req(payload, "c_f")
            )
        elif kind == "clapp":
            f_hz = osc.clapp_frequency(
                _req(payload, "l_h"), _req(payload, "c1_f"), _req(payload, "c2_f"), _req(payload, "c3_f")
            )
        elif kind == "cross_coupled":
            f_hz = osc.cross_coupled_frequency(_req(payload, "l_h"), _req(payload, "c_f"))
        else:
            raise ValueError(
                f"kind={kind!r} 不支持（'colpitts' | 'hartley' | 'clapp' | 'cross_coupled'）"
            )
        return {"kind": kind, "f_hz": float(f_hz)}

    return _envelope(build)


# ─── 反设计 ──────────────────────────────────────────────────────────────────


def oscillator_design(payload: dict[str, Any]) -> dict[str, Any]:
    """kind+目标频率+显式比值参数 → 元件值（反设计）。

    payload 必填（随 kind）：colpitts=(f_hz, l_h, c_ratio)；hartley=(f_hz,
    c_f, l_ratio, k_coupling)；clapp=(f_hz, l_h, c_ratio, c3_f)；
    cross_coupled=(f_hz, l_h)。
    """
    if not isinstance(payload, dict):
        return {"ok": False, "schema_version": SCHEMA_VERSION, "error": "payload 必须为 dict"}
    kind = payload.get("kind")

    def build() -> dict[str, Any]:
        f_hz = _req(payload, "f_hz")
        if kind == "colpitts":
            out = osc.colpitts_design(f_hz, _req(payload, "l_h"), _req(payload, "c_ratio"))
        elif kind == "hartley":
            out = osc.hartley_design(f_hz, _req(payload, "c_f"), _req(payload, "l_ratio"), _req(payload, "k_coupling"))
        elif kind == "clapp":
            out = osc.clapp_design(f_hz, _req(payload, "l_h"), _req(payload, "c_ratio"), _req(payload, "c3_f"))
        elif kind == "cross_coupled":
            c_f = osc.cross_coupled_design(f_hz, _req(payload, "l_h"))
            return {"kind": kind, "f_hz": float(f_hz), "c_f": float(c_f)}
        else:
            raise ValueError(
                f"kind={kind!r} 不支持（'colpitts' | 'hartley' | 'clapp' | 'cross_coupled'）"
            )
        return out.to_dict()

    return _envelope(build)


# ─── 起振判据报告 ────────────────────────────────────────────────────────────


def oscillator_startup_report(payload: dict[str, Any]) -> dict[str, Any]:
    """起振判据报告。mode ∈ {series, reflection, cross_coupled}。

    - series：r_in_ohm, r_res_ohm 必填；可选 amplitudes+r_in_curve（等长
      数组）→ 附大信号稳态工作点（Kurokawa 限幅交点）；
    - reflection：gamma_amp/gamma_res（[[re, im], ...] JSON 复数形态）与
      freq_hz 数组；
    - cross_coupled：gm_s, r_p_ohm；可选 gm_sweep 数组 → 附裕度曲线。
    """
    if not isinstance(payload, dict):
        return {"ok": False, "schema_version": SCHEMA_VERSION, "error": "payload 必须为 dict"}
    mode = payload.get("mode")

    def build() -> dict[str, Any]:
        out: dict[str, Any] = {"mode": mode}
        if mode == "series":
            out["startup"] = osc.negative_resistance_startup(
                _req(payload, "r_in_ohm"), _req(payload, "r_res_ohm")
            ).to_dict()
            if payload.get("amplitudes") is not None and payload.get("r_in_curve") is not None:
                out["operating_point"] = osc.negative_resistance_operating_point(
                    payload["amplitudes"], payload["r_in_curve"], _req(payload, "r_res_ohm")
                ).to_dict()
        elif mode == "reflection":
            out["startup"] = osc.reflection_startup(
                _complex_pairs(_req(payload, "gamma_amp"), "gamma_amp"),
                _complex_pairs(_req(payload, "gamma_res"), "gamma_res"),
                _req(payload, "freq_hz"),
            ).to_dict()
        elif mode == "cross_coupled":
            out["startup"] = osc.cross_coupled_startup(
                _req(payload, "gm_s"), _req(payload, "r_p_ohm")
            ).to_dict()
            if payload.get("gm_sweep") is not None:
                sweep = osc.cross_coupled_margin_sweep(payload["gm_sweep"], _req(payload, "r_p_ohm"))
                out["margin_sweep"] = sweep.to_dict()
        else:
            raise ValueError(f"mode={mode!r} 不支持（'series' | 'reflection' | 'cross_coupled'）")
        return out

    return _envelope(build)


# ─── Leeson 相噪报告（clock_noise 积分闭环）──────────────────────────────────


def leeson_noise_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Leeson 模型 + 段链 + clock_noise 积分闭环。

    payload 必填：f0_hz, flicker_corner_hz, noise_figure_lin, p_s_w,
    f_min_hz, f_max_hz, jitter_f1_hz, jitter_f2_hz；q_l 或 (dro_q0+dro_beta)
    二选一（dro 路由经 Q_L=Q_0/(1+β) 折算）；可选 t0_k、f_carrier_hz
    （给则回 rms 抖动）。[jitter_f1_hz, jitter_f2_hz] 必须落在
    [f_min_hz, f_max_hz] 段链覆盖内（clock_noise 不外推）。
    """
    if not isinstance(payload, dict):
        return {"ok": False, "schema_version": SCHEMA_VERSION, "error": "payload 必须为 dict"}

    def build() -> dict[str, Any]:
        q_l: float
        if payload.get("q_l") is not None:
            q_l = float(payload["q_l"])
            q_route = "direct"
        elif payload.get("dro_q0") is not None:
            q_l = osc.dro_loaded_q(_req(payload, "dro_q0"), _req(payload, "dro_beta"))
            q_route = "dro"
        else:
            raise ValueError("缺 q_l（直给）或 (dro_q0, dro_beta)（DRO 耦合折算）")
        kwargs: dict[str, Any] = {
            "f0_hz": _req(payload, "f0_hz"),
            "q_l": q_l,
            "flicker_corner_hz": _req(payload, "flicker_corner_hz"),
            "noise_figure_lin": _req(payload, "noise_figure_lin"),
            "p_s_w": _req(payload, "p_s_w"),
            "f_min_hz": _req(payload, "f_min_hz"),
            "f_max_hz": _req(payload, "f_max_hz"),
        }
        t0 = payload.get("t0_k")
        if t0 is not None:
            kwargs["t0_k"] = t0
        model = osc.leeson_model(**kwargs)
        out = model.to_dict()
        out["q_route"] = q_route

        f1 = _req(payload, "jitter_f1_hz")
        f2 = _req(payload, "jitter_f2_hz")
        sigma2_chain = clock_noise.power_law_sigma_phi2(model.segments, f1, f2)
        sigma_kwargs = {k: v for k, v in kwargs.items() if k not in ("f_min_hz", "f_max_hz")}
        sigma2_exact = osc.leeson_sigma_phi2_exact(f1, f2, **sigma_kwargs)
        chain_delta = (
            (sigma2_chain - sigma2_exact) / sigma2_exact if sigma2_exact > 0.0 else 0.0
        )
        jitter: dict[str, Any] = {
            "f1_hz": float(f1),
            "f2_hz": float(f2),
            "sigma_phi2_chain_rad2": sigma2_chain,
            "sigma_phi2_exact_rad2": sigma2_exact,
            "chain_exact_rel_delta": chain_delta,
            "note": (
                "chain=三段渐近幂律链经 clock_noise 积分（拼接面口径）；"
                "exact=精确乘积式逐项闭式积分；差为渐近模型固有误差（内核边界②）"
            ),
        }
        carrier = payload.get("f_carrier_hz")
        if carrier is not None:
            jitter["f_carrier_hz"] = float(carrier)
            jitter["sigma_phi_rad"] = math.sqrt(sigma2_chain)
            jitter["jitter_s"] = clock_noise.rms_jitter_s(math.sqrt(sigma2_chain), carrier)
        out["jitter"] = jitter
        return out

    return _envelope(build)
