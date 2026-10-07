"""F-H.4 P2：低温材料面 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/cryo_materials.py 内核（本服务零物理公式，全部数字出自确定性
内核，规则 7）。单入口：

- :func:`cryo_surface_estimate`：温度/RRR/频率 → 铜面全量（ρ/Rs/δ/l/
  f_c/regime）；可选超导节（λ_L0+T_c+膜厚 → λ(T)/L_s/X_s，f0(T) 可选）；
  可选 Q 节（tanδ_eff[+Rs+G] → Q 分解）。

诚实边界（预声明）：线性声子项深低温高估（Bloch-Grüneisen 未建模）；
Chambers 反常区 Rs 幅值未实现（只有分界判类）；Nb Rs(T)（Mattis-
Bardeen）未实现——超导 Q 的 R_s 由调用方外供；介电表为单源典型带
（core.CRYO_DIELECTRICS，如实标注）。所有异常（含 payload 非对象、
内核 ValueError）收敛为 ok=False errors 信封，不向调用方抛出。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from rfauto.core import cryo_materials as cryo
from rfauto.service._helpers import (
    err_envelope,
)
from rfauto.service._helpers import (
    optional_num as _optional_num,
)
from rfauto.service._helpers import (
    parse_num as _num,
)
from rfauto.service._helpers import (
    require_payload_dict as _require_payload_dict,
)

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
CRYO_MATERIALS_SCHEMA_VERSION = "1.0"

# S2-8 单源化（review_ge8e 2026-10-04）：_num/_require_payload_dict/
# _optional_num 本地近逐字节拷贝已删净（#116），单源在 service._helpers；
# _err 为本服务版本戳变体（单源 err_envelope 的 partial 绑定，零本地逻辑）。
_err = partial(err_envelope, schema_version=CRYO_MATERIALS_SCHEMA_VERSION)


def cryo_surface_estimate(payload: Any) -> dict[str, Any]:
    """低温材料面端到端估计（铜面必出；超导节/Q 节可选）。

    Args（payload 键）:
        t_k: 温度（必填，K，>=0）；
        rrr: 铜剩余电阻比（必填，>=1）；
        f_hz: 频率（必填，Hz，>0）；
        superconductor 节（可选）：{lambda_l0_m, tc_k, film_thickness_m,
        f0_at_zero_k_hz?, kappa_kinetic?}——前三者给齐即出 λ(T)/L_s/X_s；
        f0_at_zero_k_hz 与 kappa_kinetic 同时给出再出 f0(T)；
        q_section 节（可选）：{tan_delta_eff, rs_ohm_per_sq?,
        geometry_factor_ohm?}——Rs 与 G 成对给/不给。

    Returns:
        dict: {ok, schema_version, copper:{...}, superconductor?:{...},
        q?:{...}, constants:{nb, cryo_dielectrics}, provenance, disclaimer}；
        非法入参/内核异常 → {ok:false, errors} 信封。
    """
    errors: list[str] = []
    try:
        p = _require_payload_dict(payload)
    except ValueError as exc:
        return _err([str(exc)])

    t_k = _num(p.get("t_k"), "t_k", errors, nonneg=True)
    rrr = _num(p.get("rrr"), "rrr", errors)
    f_hz = _num(p.get("f_hz"), "f_hz", errors, positive=True)
    if errors:
        return _err(errors)
    assert t_k is not None and rrr is not None and f_hz is not None  # errors 已拦

    out: dict[str, Any] = {}
    try:
        copper = cryo.copper_surface_face(t_k, rrr, f_hz)
    except ValueError as exc:
        return _err([f"铜面计算失败: {exc}"])
    out["copper"] = copper.to_dict()

    sc = p.get("superconductor")
    if sc is not None:
        if not isinstance(sc, dict):
            return _err(["superconductor 必须是 JSON 对象"])
        l0 = _num(sc.get("lambda_l0_m"), "superconductor.lambda_l0_m", errors, positive=True)
        tc = _num(sc.get("tc_k"), "superconductor.tc_k", errors, positive=True)
        tf = _num(sc.get("film_thickness_m"), "superconductor.film_thickness_m", errors, positive=True)
        f0_0 = _optional_num(sc.get("f0_at_zero_k_hz"), "superconductor.f0_at_zero_k_hz", errors, positive=True)
        kappa = _optional_num(sc.get("kappa_kinetic"), "superconductor.kappa_kinetic", errors)
        if errors:
            return _err(errors)
        assert l0 is not None and tc is not None and tf is not None
        try:
            lam_t = cryo.london_penetration_depth_m(l0, t_k, tc)
            sc_out: dict[str, Any] = {
                "lambda_t_m": lam_t,
                "lambda_ratio": lam_t / l0,
                "sheet_kinetic_inductance_h_per_sq": cryo.sheet_kinetic_inductance_h_per_sq(
                    lam_t, tf
                ),
                "sheet_surface_reactance_ohm_per_sq": cryo.sheet_surface_reactance_ohm_per_sq(
                    f_hz, lam_t, tf
                ),
            }
            if f0_0 is not None and kappa is not None:
                sc_out["f0_hz"] = cryo.superconductor_f0_hz(f0_0, kappa, l0, t_k, tc)
                sc_out["f0_at_zero_k_hz"] = f0_0
                sc_out["kappa_kinetic"] = kappa
            elif f0_0 is not None or kappa is not None:
                return _err(["f0_at_zero_k_hz 与 kappa_kinetic 须同时给出"])
            out["superconductor"] = sc_out
        except ValueError as exc:
            return _err([f"超导节计算失败: {exc}"])

    qs = p.get("q_section")
    if qs is not None:
        if not isinstance(qs, dict):
            return _err(["q_section 必须是 JSON 对象"])
        td = _num(qs.get("tan_delta_eff"), "q_section.tan_delta_eff", errors, nonneg=True)
        rs = _optional_num(qs.get("rs_ohm_per_sq"), "q_section.rs_ohm_per_sq", errors, nonneg=True)
        g = _optional_num(qs.get("geometry_factor_ohm"), "q_section.geometry_factor_ohm", errors, positive=True)
        if errors:
            return _err(errors)
        assert td is not None
        if (rs is None) != (g is None):
            return _err(["q_section 的 rs_ohm_per_sq 与 geometry_factor_ohm 须成对给出"])
        try:
            breakdown = cryo.resonator_q_breakdown(td, rs, g)
        except ValueError as exc:
            return _err([f"Q 节计算失败: {exc}"])
        out["q"] = breakdown.to_dict()

    out.update(
        ok=True,
        schema_version=CRYO_MATERIALS_SCHEMA_VERSION,
        constants={"nb_typical": dict(cryo.NB_TYPICAL), "cryo_dielectrics": dict(cryo.CRYO_DIELECTRICS)},
        provenance={
            "cu": "Matthiessen+RRR 线性声子近似；Rs=√(πfμ₀ρ)（Pozar 良导体）；"
            "ASE 分界 δ=l（Drude l=v_F·m_e/(n·e²·ρ)）",
            "superconductor": "Gorter-Cassimir 两流体 λ(T)；L_s=μ₀λ²/t_film 薄膜极限"
            "（Tinkham/Zmuidzinas 2012）；Q=1/(tanδ+Rs/G) 谐振器通用口径",
            "dielectrics": "Krupka 低温介电+OSTI 汇编（单源典型带，如实标注）",
        },
        disclaimer=(
            "线性声子项深低温高估（Bloch-Grüneisen 未建模）；Chambers 反常区 Rs 幅值与 "
            "Nb Mattis-Bardeen Rs(T) 未实现（分界判类/超导 R_s 外供）；介电表为单源典型带"
        ),
    )
    return out
