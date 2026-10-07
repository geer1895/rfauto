"""匹配与衰减族（λ/4 变换、π/T/桥T 衰减器、驻波换算、贴片谐振长度）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.synthesis import patch_fringing_delta_l

from .registry import C_MM_GHZ, register_calculator
from .rf_line import _lambda_g_mm

# ─── λ/4 变换 / 衰减器 / 驻波 ────────────────────────────────────────────────

@register_calculator(
    "quarter_wave_transformer",
    "λ/4 阻抗变换器：段特性阻抗 z0=sqrt(Zs·Zl)；给 εeff/频率时附物理长度",
    (("z_source_ohm", "float Ω 源侧阻抗"),
     ("z_load_ohm", "float Ω 负载阻抗"),
     ("freq_ghz", "float GHz 频率（可选，配合 eps_eff 算长度）"),
     ("eps_eff", "float - 有效介电常数（可选）")),
    required=("z_source_ohm", "z_load_ohm"),
)
def quarter_wave_transformer(z_source_ohm: float, z_load_ohm: float,
                             freq_ghz: float | None = None,
                             eps_eff: float | None = None) -> dict:
    z0 = math.sqrt(z_source_ohm * z_load_ohm)
    out: dict[str, Any] = {"z0_section_ohm": round(z0, 3)}
    if freq_ghz and eps_eff:
        lam_g = _lambda_g_mm(freq_ghz, eps_eff)
        out["lambda_g_mm"] = round(lam_g, 3)
        out["length_mm"] = round(lam_g / 4.0, 3)
    return out


@register_calculator(
    "attenuator_pi",
    "π 型电阻衰减器：衰减量+Z0 → 端电阻（ABCD 校验有单测）",
    (("attenuation_db", "float dB 衰减量（>0）"),
     ("z0_ohm", "float Ω 系统阻抗")),
    required=("attenuation_db", "z0_ohm"),
)
def attenuator_pi(attenuation_db: float, z0_ohm: float) -> dict:
    if attenuation_db <= 0:
        raise ValueError("衰减量必须 >0 dB")
    # N=电压比=10^(A/20)，推导自匹配+分压两条件
    # （3dB 锚，经典值：中串 17.612Ω/端并 292.48Ω）
    n = 10.0 ** (attenuation_db / 20.0)
    r_series = z0_ohm * (n * n - 1.0) / (2.0 * n)
    r_shunt = z0_ohm * (n + 1.0) / (n - 1.0)
    return {"r_series_mid_ohm": round(r_series, 3),
            "r_shunt_end_ohm": round(r_shunt, 3),
            "note": "π 型：中点串 r_series_mid，两端各对地 r_shunt_end"}


@register_calculator(
    "attenuator_t",
    "T 型电阻衰减器：衰减量+Z0 → 端电阻（ABCD 校验有单测）",
    (("attenuation_db", "float dB 衰减量（>0）"),
     ("z0_ohm", "float Ω 系统阻抗")),
    required=("attenuation_db", "z0_ohm"),
)
def attenuator_t(attenuation_db: float, z0_ohm: float) -> dict:
    if attenuation_db <= 0:
        raise ValueError("衰减量必须 >0 dB")
    # N=电压比=10^(A/20)（经典 3dB 锚：串臂 8.550Ω/中并 141.93Ω）
    n = 10.0 ** (attenuation_db / 20.0)
    r_series = z0_ohm * (n - 1.0) / (n + 1.0)
    r_shunt = 2.0 * z0_ohm * n / (n * n - 1.0)
    return {"r_series_arm_ohm": round(r_series, 3),
            "r_shunt_mid_ohm": round(r_shunt, 3),
            "note": "T 型：上下臂各串 r_series_arm，中点对地 r_shunt_mid"}


@register_calculator(
    "attenuator_bridged_t",
    "桥 T 型电阻衰减器：衰减量+Z0 → 桥/并电阻（串臂固定 Z0；节点导纳级联校验有单测）",
    (("attenuation_db", "float dB 衰减量（>0）"),
     ("z0_ohm", "float Ω 系统阻抗")),
    required=("attenuation_db", "z0_ohm"),
)
def attenuator_bridged_t(attenuation_db: float, z0_ohm: float) -> dict:
    """桥 T 型（bridged-T）：两串臂各固定 R=Z0，桥电阻跨接输入-输出，中点并电阻对地。

    N=电压比=10^(A/20)。闭式（F8 首族变体，2026-09-16 三节点导纳 Kron 消元
    数值裁判先于采信，#118）：r_bridge=Z0·(N−1)，r_shunt=Z0/(N−1)，串臂=Z0；
    1/3/6/10/20 dB 全部 |S11|≤5e-11、|S21|=1/N（1e-6）。经典 3dB/50Ω 锚：
    桥 20.627Ω / 并 121.201Ω。极限自洽：A→0 桥→0（直通）、并→∞（开路）；
    A→∞ 桥→∞、并→0（中点接地，全反射吸收）。
    """
    if attenuation_db <= 0:
        raise ValueError("衰减量必须 >0 dB")
    n = 10.0 ** (attenuation_db / 20.0)
    r_bridge = z0_ohm * (n - 1.0)
    r_shunt = z0_ohm / (n - 1.0)
    return {"r_series_arm_ohm": round(float(z0_ohm), 3),
            "r_bridge_ohm": round(r_bridge, 3),
            "r_shunt_mid_ohm": round(r_shunt, 3),
            "note": "桥 T 型：上下臂各串固定 Z0，输入-输出跨接 r_bridge，"
                    "中点对地 r_shunt_mid"}


@register_calculator(
    "vswr_convert",
    "驻波换算：VSWR↔|Γ|↔回损↔失配损耗（三入任一，全出）",
    (("vswr", "float - 电压驻波比（>1；与回损/Γ 二选一）"),
     ("return_loss_db", "float dB 回损（正数）"),
     ("gamma_mag", "float - 反射系数模（0-1）")),
    required=(),
)
def vswr_convert(vswr: float | None = None,
                 return_loss_db: float | None = None,
                 gamma_mag: float | None = None) -> dict:
    if vswr is not None:
        if vswr <= 1.0:
            raise ValueError("VSWR 必须 >1")
        gamma = (vswr - 1.0) / (vswr + 1.0)
    elif return_loss_db is not None:
        if return_loss_db <= 0:
            raise ValueError("回损必须 >0 dB")
        gamma = 10.0 ** (-return_loss_db / 20.0)
    elif gamma_mag is not None:
        if not 0.0 <= gamma_mag < 1.0:
            raise ValueError("|Γ| 必须在 [0,1)")
        gamma = gamma_mag
    else:
        raise ValueError("需提供 vswr / return_loss_db / gamma_mag 之一")
    g = float(gamma)
    if g <= 0.0:
        return {"gamma_mag": 0.0, "vswr": 1.0, "return_loss_db": None,
                "mismatch_loss_db": 0.0, "note": "回损无穷大记 null"}
    rl = -20.0 * math.log10(g)
    vswr_out = (1.0 + g) / (1.0 - g)
    mismatch_db = -10.0 * math.log10(1.0 - g * g)
    return {"gamma_mag": round(g, 6), "vswr": round(vswr_out, 4),
            "return_loss_db": round(rl, 4),
            "mismatch_loss_db": round(mismatch_db, 4)}


# ─── 贴片谐振（Balanis 口径，与 synthesize_patch 同公式）─────────────────────

@register_calculator(
    "patch_length",
    "矩形贴片谐振长度（Balanis 闭式含边缘修正）：f0+er+h → W/εeff/L",
    (("f0_ghz", "float GHz 谐振频率"),
     ("epsilon_r", "float - 基板相对介电常数"),
     ("h_mm", "float mm 基板厚度")),
    required=("f0_ghz", "epsilon_r", "h_mm"),
)
def patch_length(f0_ghz: float, epsilon_r: float, h_mm: float) -> dict:
    """矩形贴片谐振长度（Balanis W/εeff 闭式 + Hammerstad 边缘修正）。

    **总扣口径=4ΔL**（三副本一致，历史仲裁 INCONCLUSIVE 在档
    runs/xa1_arbitration/；语义终裁挂 L5 v2 批，见
    runs/xa1_arbitration/l5_sweep/criteria.md §一）：本函数 L =
    c/(2f0√εeff) − 2·dL，其中 dL=两边缘合计（2×0.412 每边缘，Hammerstad
    单源 patch_fringing_delta_l；数值上=旧 0.824h(…) 常数）⇒ 总扣 4ΔL。
    所引 Balanis/本仓 docs/rf_template_references.md §13 字面为 −2ΔL，与
    实现 4ΔL 的矛盾即 0.824 终裁本体——出处标签如实登记，数值零改动
    （R1-2 审查批注记 2026-10-04，runs/review_ge8e/r1_calculators/REPORT.md）。
    """
    w_mm = C_MM_GHZ / (2.0 * f0_ghz) * math.sqrt(2.0 / (epsilon_r + 1.0))
    eps_eff = ((epsilon_r + 1.0) / 2.0
               + (epsilon_r - 1.0) / 2.0 * (1.0 + 12.0 * h_mm / w_mm) ** -0.5)
    # d_l = 两边缘合计（2×0.412 每边缘，Hammerstad 单源 patch_fringing_delta_l；
    # 数值上=旧 0.824h(…) 常数），L 再 ×2 ⇒ 总扣 4ΔL——XA-1/PV-016 仲裁
    # INCONCLUSIVE 维持现行口径（2026-10-02，runs/xa1_arbitration）。
    d_l = 2.0 * patch_fringing_delta_l(w_mm * 1e-3, h_mm * 1e-3, eps_eff) * 1e3
    l_mm = C_MM_GHZ / (2.0 * f0_ghz * math.sqrt(eps_eff)) - 2.0 * d_l
    return {"patch_w_mm": round(w_mm, 4), "eps_eff": round(eps_eff, 4),
            "delta_l_mm": round(d_l, 4), "patch_l_mm": round(l_mm, 4),
            "lambda_g_mm": round(_lambda_g_mm(f0_ghz, eps_eff), 3)}
