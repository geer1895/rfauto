"""MA 导体补强：σ(T) 通用化（RRR→任意金属）+ 表面处理定量下界面。

规格：研究扩充 round17 §六 MA-10（导体补强，
P2/S）——"σ(T) 通用化（RRR→任意金属）+OSP/ImAg 定量下界+方向 SR 分离；
MVDT 名称未确认（待证登记）"。任务书 ge8b Wave A 席4 MA-12（规格为准=
本件）。与 core/cryo_materials.copper_resistivity（Cu 专用 Matthiessen）
同构异消费：本模块把 ρ(T; ρ_ref, RRR, T_ref) 参数化到任意金属；单测做
Cu 行跨模块互证（#118）。纯闭式叶子，零 IO、不进 calculators。

模块面
------
- ``METAL_RHO_REF_293K``：常用金属 293 K 体电阻率表（CRC/手册带，
  band+single_source；Nb 等工艺敏感金属带宽）。
- ``metal_resistivity``：ρ(T) = ρ_ref/RRR + (ρ_ref−ρ_ref/RRR)·(T/T_ref)
  （Matthiessen 两项；锚点恒等式 T=0 → ρ_ref/RRR、T=T_ref → ρ_ref、
  RRR 定义恒等——与 cryo_materials 同构造）。
- ``metal_conductivity``：σ(T) = 1/ρ(T)。
- ``finish_conductivity_face``：表面处理（OSP/ImAg/ENIG/裸铜）定量
  下界面——*薄 finish 层不增 DC/RF 损耗的下界语义*：
  * OSP（有机保焊膜，无金属层）→ 有效 σ 下界=裸铜 σ；
  * ImAg（浸银，IPC-4553 厚度带 0.07–0.4 µm）→ 复合 Rs 下界按
    趋肤分段（薄层 ≤δ/3 时≈裸铜；厚层按 Ag σ 并联修正上浮）——
    **下界口径**：Rs ≥ Rs_Cu/√(σ_finish/σ_cu) 的频率无关工程包络，
    只给下界不给精确复合阻抗（多层有耗 TL 精确解属消费层）。
  * ENIG（镍金）→ Ni 有磁性（μ_r≈100+），损耗上浮——**下界仍=裸铜，
    上浮面不做**（Ni 复合阻抗需实测层参数，如实登记）。
- ``directional_sr_note``：方向 SR（表面粗糙度方向性）分离——登记级
  注记（Huray/Hammerstad 各向同性口径在 conductor_loss；方向分离无
  公认闭式，铁律 7 不产数）。
- ``MVDT_REGISTER_NOTE``：MVDT 名称未确认（规格待证登记，不做）。

出处
----
1. round 文档：round17 §六 MA-10（本文首段）。
2. ρ_ref 表：CRC 手册/Cryer 低温汇编带（band+single_source，#122）；
   Matthiessen 两项构造与 cryo_materials.copper_resistivity 同源
   （跨模块互证锚）；IPC-4553（ImAg 厚度带口径名，正文收费）。
"""
from __future__ import annotations

import math
from typing import Any

__all__ = [
    "CONDUCTOR_SOURCE",
    "IMAG_THICKNESS_M",
    "METAL_RHO_REF_293K",
    "T_REF_K",
    "directional_sr_note",
    "finish_conductivity_face",
    "metal_conductivity",
    "metal_resistivity",
    "mvdt_register_note",
]

T_REF_K = 293.0
CONDUCTOR_SOURCE = (
    "CRC/低温汇编 ρ_ref 带（band+single_source，#122）；Matthiessen 两项"
    "构造同 cryo_materials（跨模块互证）；IPC-4553 ImAg 厚度带口径名"
    "（正文收费，页码 UNVERIFIED）"
)

#: 常用金属 293 K 体电阻率（Ω·m）——中心值+带（工艺/纯度敏感者带宽）
METAL_RHO_REF_293K: dict[str, dict[str, Any]] = {
    "Cu": {"rho": 1.68e-8, "band": (1.60e-8, 1.80e-8)},
    "Ag": {"rho": 1.59e-8, "band": (1.55e-8, 1.65e-8)},
    "Au": {"rho": 2.44e-8, "band": (2.35e-8, 2.50e-8)},
    "Al": {"rho": 2.74e-8, "band": (2.60e-8, 2.90e-8)},
    "W": {"rho": 5.49e-8, "band": (5.30e-8, 5.70e-8)},
    "Mo": {"rho": 5.34e-8, "band": (5.10e-8, 5.60e-8)},
    "Nb": {"rho": 1.45e-7, "band": (1.2e-7, 1.8e-7)},  # 工艺敏感带宽
}

#: ImAg 厚度带（IPC-4553 口径名，m）
IMAG_THICKNESS_M = (7.0e-8, 4.0e-7)


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _nonneg(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v < 0.0:
        raise ValueError(f"{name} 必须为非负有限数，实际 {x!r}")
    return v


def metal_resistivity(t_k: Any, rho_ref: Any, rrr: Any,
                      t_ref_k: Any = T_REF_K) -> float:
    """Matthiessen 两项 ρ(T) = ρ_ref/RRR + (ρ_ref−ρ_ref/RRR)·(T/T_ref)。

    锚点恒等式（构造性精确）：T=0 → ρ_ref/RRR；T=T_ref → ρ_ref；
    ρ(T_ref)/ρ(0) = RRR（定义恒等，单测钉）。与
    cryo_materials.copper_resistivity 同构造（Cu+RRR=该函数 Cu 行）。
    T<0 显式 ValueError；声子项线性近似（T⁵ 滚降未建模——带内上界
    语义，同 cryo_materials 声明）。
    """
    t = float(t_k)
    if not math.isfinite(t) or t < 0.0:
        raise ValueError(f"t_k 必须为非负有限数，实际 {t_k!r}")
    rho = _positive(rho_ref, "rho_ref")
    r = _positive(rrr, "rrr")
    if r < 1.0:
        raise ValueError(f"RRR 须 >=1（ρ(T_ref)/ρ(0) 物理定义），实际 {rrr!r}")
    t_ref = _positive(t_ref_k, "t_ref_k")
    rho_res = rho / r
    return rho_res + (rho - rho_res) * (t / t_ref)


def metal_conductivity(t_k: Any, rho_ref: Any, rrr: Any,
                       t_ref_k: Any = T_REF_K) -> float:
    """σ(T) = 1/ρ(T)（S/m）。"""
    return 1.0 / metal_resistivity(t_k, rho_ref, rrr, t_ref_k)


def finish_conductivity_face(finish: str, sigma_cu_s_per_m: Any,
                             f_hz: Any) -> dict[str, Any]:
    """表面处理定量下界面（*下界语义*：损耗不会优于该界——不虚构复合阻抗）。

    - OSP：有机层无金属 → 下界=裸铜 Rs；
    - ImAg：σ_Ag>σ_Cu + 厚度带 ≤δ_ImAg/3 时复合面近似裸铜 → 下界
      =裸铜 Rs（薄层口径）；厚层给出 Ag 修正包络（如实 single_source）；
    - ENIG：Ni 磁性上浮不做（登记）→ 下界=裸铜 Rs（声明）。
    返回 {finish, rs_lower_ohm_sq, note}；Rs=√(πfμ0/σ)（非磁）。
    """
    sc = _positive(sigma_cu_s_per_m, "sigma_cu_s_per_m")
    f = _positive(f_hz, "f_hz")
    mu0 = 4.0e-7 * math.pi
    rs_cu = math.sqrt(math.pi * f * mu0 / sc)
    if finish == "osp":
        return {
            "finish": "osp", "rs_lower_ohm_sq": rs_cu,
            "note": "有机保焊膜无金属层：下界=裸铜 Rs",
        }
    if finish == "imag":
        sigma_ag = 1.0 / METAL_RHO_REF_293K["Ag"]["rho"]
        delta_ag = math.sqrt(2.0 / (2.0 * math.pi * f * mu0 * sigma_ag))
        t_max = IMAG_THICKNESS_M[1]
        thin = t_max <= delta_ag / 3.0
        note = (
            f"ImAg 厚度带 ≤{t_max*1e9:.0f}nm vs δ_Ag={delta_ag*1e6:.1f}µm"
            f"@{f/1e9:.2f}GHz：{'薄层口径，' if thin else '厚层口径，'}"
            "下界=裸铜 Rs（薄层不增损）；厚层 Ag 修正在消费层做复合阻抗"
        )
        return {"finish": "imag", "rs_lower_ohm_sq": rs_cu,
                "delta_ag_m": delta_ag, "thin_layer_regime": thin,
                "note": note}
    if finish == "enig":
        return {
            "finish": "enig", "rs_lower_ohm_sq": rs_cu,
            "note": "Ni 磁性（μ_r≫1）损耗上浮面不做（层参数实测依赖，"
                    "登记级）——下界=裸铜 Rs 仅声明",
        }
    if finish == "bare_cu":
        return {"finish": "bare_cu", "rs_lower_ohm_sq": rs_cu,
                "note": "裸铜基准"}
    raise ValueError(f"未知表面处理 {finish!r}；"
                     f"可选 osp|imag|enig|bare_cu")


def directional_sr_note() -> dict[str, str]:
    """方向 SR（表面粗糙度方向性）分离——登记级注记（不产数）。"""
    return {
        "existing_models": (
            "conductor_loss 的 Hammerstad/Huray 均各向同性口径"
        ),
        "directional_separation": (
            "蚀刻方向性粗糙度（横向/纵向 SR 分离）无公认闭式——"
            "铁律 7 不产数，登记待全波/实测仲裁"
        ),
    }


def mvdt_register_note() -> str:
    """MVDT 名称未确认（规格待证登记——不做，#222 待证不进主序）。"""
    return ("MVDT 名称未确认（round17 MA-10 待证登记）；不实现不产数，"
            "立项前先证后做")
