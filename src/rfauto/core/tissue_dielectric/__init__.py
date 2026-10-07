"""NX-7 组织介电常数表（Gabriel 1996 四阶 Cole-Cole）+ 植入链路闭式面。

规格：研究扩充 round14 §四 NX-7——"Gabriel
1996 四阶 Cole-Cole（Phys. Med. Biol. 41 免费文献双源）入 materials
schema；植入天线闭式链（等效介质波长缩短+SAR 门）。IT'IS Virtual Family
许可边界维持"。数据包形态：data/gabriel1996_table1.csv（原文 Table 1
p.2291 逐格转录，出处头在 CSV 内）+ 本加载器/闭式函数。纯函数叶子，
零网络 IO、不进 calculators（同席 2/3 约定）。

模块面
------
- ``load_gabriel1996``：CSV 加载（参数 dict per tissue；出处头解析为
  PROVENANCE 常量）。
- ``cole_cole_eps``：ε*(ω) = ε∞ + Σ Δεi/(1+(jωτi)^{1−αi}) + σ/(jωε0)
  （Gabriel 式(4)口径）→ εr′/εr″/σ_eff/穿透深度 δ=1/√(πfμ0σ_eff)。
- ``implant_link_chain``：植入闭式链——有耗介质波长缩短
  λ_eff = λ0/Re√εr_eff（非磁）、等效损耗角与 SAR 门
  （SAR = σ|E_rms|²/ρ，IEEE 1528 rms 口径；门限 2 W/kg（10 g）登记
  公开值，verdict 只做门判不产组织内场分布）。
- ``SAR_GATE_W_PER_KG_10G``：2.0（ICNIRP/IEEE 1528 公开口径名，登记）。

出处（双源）
------------
1. 原文 Table 1 p.2291（免费 PDF 逐格读数，2026-10-03，见 CSV 头 [A]）。
2. round 文档 NX-7 条目（round14 §四/round17 §四，[B]）。
 tertiary：FCC Body Tissue Dielectric Parameters 公开工具库（muscle 等
 行逐格一致旁证；kidney α1 差异 0.10/0.11 已在 CSV 行内如实记）。
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

__all__ = [
    "C0_M_S",
    "EPS0_F_M",
    "GABRIEL_PROVENANCE",
    "SAR_GATE_W_PER_KG_10G",
    "cole_cole_eps",
    "implant_link_chain",
    "load_gabriel1996",
]

C0_M_S = 299792458.0
EPS0_F_M = 8.8541878128e-12
SAR_GATE_W_PER_KG_10G = 2.0  # W/kg（10g 平均，ICNIRP 公开口径名，登记）
GABRIEL_PROVENANCE = (
    "Gabriel-Lau-Gabriel 1996 Phys. Med. Biol. 41 Table 1 p.2291（原文 "
    "PDF 逐格读数 2026-10-03）+ round14 §四 NX-7（round 来源）；"
    "tertiary：FCC 公开工具库旁证（muscle 行一致；kidney α1 差异如实记）"
)

_DATA_PATH = Path(__file__).parent / "data" / "gabriel1996_table1.csv"
#: 极 1-4 的 CSV 列后缀与秒换算（ps/ns/µs/ms，Gabriel Table 1 原文单位）
_TAU_COLUMNS = (("tau1_ps", 1e-12), ("tau2_ns", 1e-9),
                ("tau3_us", 1e-6), ("tau4_ms", 1e-3))


def load_gabriel1996() -> dict[str, dict[str, Any]]:
    """加载 Gabriel 1996 Table 1 参数（逐组织 dict；拷贝面）。

    返回 {tissue: {eps_inf, poles: [(de_i, tau_i_s, a_i), ...],
    sigma_s_m, provenance_note}}——tau 已换算到秒；零幅值极剔除。
    """
    out: dict[str, dict[str, Any]] = {}
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        tissue = row["tissue"].strip()
        if not tissue:
            continue
        eps_inf = float(row["eps_inf"])
        sigma = float(row["sigma_s_m"])
        poles = []
        for k in (1, 2, 3, 4):
            de = float(row[f"de{k}"])
            col, scale = _TAU_COLUMNS[k - 1]
            tau = float(row[col]) * scale
            a = float(row[f"a{k}"])
            if de > 0.0:
                poles.append((de, tau, a))
        out[tissue] = {
            "eps_inf": eps_inf,
            "poles": poles,
            "sigma_s_m": sigma,
            "provenance_note": row.get("provenance_note", "").strip(),
        }
    if "muscle" not in out:
        raise ValueError("Gabriel 表加载异常：muscle 行缺失")
    return out


def _finite(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须为有限数，实际 {x!r}")
    return v


def cole_cole_eps(tissue: Any, f_hz: Any,
                  table: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Gabriel 四阶 Cole-Cole 单频求值（e^{+jωt} 约定：ε*(ω)=ε′−jε″）。

    ε* = ε∞ + Σ Δεi/(1+(jωτi)^{1−αi}) + σ/(jωε0)；输出
    {eps_r_real, eps_r_imag(=ε″, 正值), sigma_eff_s_m(=ωε0ε″+σ),
    tan_delta, penetration_depth_m}。σ_eff 与穿透深度按良导体近似
    δ=1/√(π f μ0 σ_eff)（有耗介质工程口径，f 足高时成立）。
    """
    t = str(tissue)
    f = _finite(f_hz, "f_hz")
    if f <= 0.0:
        raise ValueError("f_hz 必须为正")
    tab = table if table is not None else load_gabriel1996()
    if t not in tab:
        raise ValueError(f"未知组织 {t!r}；可选 {sorted(tab)}")
    row = tab[t]
    omega = 2.0 * math.pi * f
    eps_star = complex(row["eps_inf"], 0.0)
    for de, tau, a in row["poles"]:
        # (jωτ)^(1−α)：模/辐角直接算（1−α∈(0,1]，无分支奇异）
        mag = (omega * tau) ** (1.0 - a)
        ang = (1.0 - a) * math.pi / 2.0
        denom = 1.0 + complex(mag * math.cos(ang), mag * math.sin(ang))
        eps_star += de / denom
    # σ/(jωε0) = −jσ/(ωε0)
    eps_star += complex(0.0, -row["sigma_s_m"] / (omega * EPS0_F_M))
    eps_r = eps_star.real
    eps_i = -eps_star.imag  # ε″（正值语义）
    if eps_r <= 0.0:
        raise ValueError(f"{t}: εr′≤0（参数/频率组合非法）")
    sigma_eff = omega * EPS0_F_M * eps_i + row["sigma_s_m"]
    mu0 = 4.0e-7 * math.pi
    delta = 1.0 / math.sqrt(math.pi * f * mu0 * sigma_eff) if sigma_eff > 0.0 \
        else math.inf
    return {
        "eps_r_real": eps_r,
        "eps_r_imag": eps_i,
        "sigma_eff_s_m": sigma_eff,
        "tan_delta": eps_i / eps_r,
        "penetration_depth_m": delta,
    }


def implant_link_chain(tissue: Any, f_hz: Any,
                       e_rms_v_per_m: Any,
                       tissue_density_kg_m3: Any = 1000.0,
                       table: dict[str, dict[str, Any]] | None = None
                       ) -> dict[str, Any]:
    """植入天线闭式链：介质波长缩短 + SAR 门（规格 NX-7 口径）。

    - 波长缩短：λ_eff = λ0/√εr′（非磁、弱耗工程口径——取 εr′ 实部；
      色散介质下逐频求值，如实不做宽带等效）。
    - SAR = σ_eff·E_rms²/ρ（IEEE 1528 rms 场口径；10 g 平均门限
      SAR_GATE=2 W/kg 公开值——verdict 只按点值门判，不做组织内平均
      分布（登记边界）。
    """
    cc = cole_cole_eps(tissue, f_hz, table)
    f = _finite(f_hz, "f_hz")
    e = _finite(e_rms_v_per_m, "e_rms_v_per_m")
    rho = _finite(tissue_density_kg_m3, "tissue_density_kg_m3")
    if rho <= 0.0:
        raise ValueError("tissue_density_kg_m3 必须为正")
    lam0 = C0_M_S / f
    lam_eff = lam0 / math.sqrt(cc["eps_r_real"])
    sar = cc["sigma_eff_s_m"] * e * e / rho
    return {
        "lambda0_m": lam0,
        "lambda_eff_m": lam_eff,
        "shortening_ratio": lam0 / lam_eff,
        "eps_r_real": cc["eps_r_real"],
        "sigma_eff_s_m": cc["sigma_eff_s_m"],
        "sar_w_per_kg": sar,
        "sar_gate_w_per_kg": SAR_GATE_W_PER_KG_10G,
        "sar_verdict": "pass" if sar <= SAR_GATE_W_PER_KG_10G else "fail",
        "penetration_depth_m": cc["penetration_depth_m"],
    }
