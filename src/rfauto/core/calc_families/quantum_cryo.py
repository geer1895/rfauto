"""超导材料 Rs/能隙两键（架构批 W3-K 池件批，R2_core_tier5 §⑤-1/§③-14
提升核——池件 MP-7 同笔清偿）。

提升核：消费 core/quantum_cryo.py 登记级全套闭式（round17 §六 MA-11 落地
物；Gao 2008 工程近似口径名+Gittleman-Rosenblum 1966 t⁴ 口径名+Tinkham
《Introduction to Superconductivity》2nd；#122 页码 UNVERIFIED 如实已在
内核标注）——该内核 docstring 自证"纯闭式叶子，零 IO、不进 calculators"，
本文件即其 CALC 注册面。与 qubit_readout 族（架构批 W7-A）的分工边界
已在彼处写死：quantum_cryo=材料/器件面（本族），读出链数值面=彼族。

公式（单源不复制，出处与互证路径见 core/quantum_cryo.py 模块 docstring）
------------------------------------------------------------------------
- 两流体模型（Tinkham 2nd ch.10 工程口径）：σ₁(T) = σ_n·t⁴（正常流体
  份额 n_n/n = t⁴，Gittleman-Rosenblum 1966）；London 穿透深度温度律
  λ_L(T) = λ_L0/√(1−t⁴)（同一两流体假设的直接推论：λ² ∝ 1/n_s、
  n_s/n = 1−t⁴）。
- 局部极限（London 极限）超导面电阻：Rs = Re[√(jωμ0/(σ₁−jσ₂))]，
  σ₂ = 1/(μ0ωλ_L²(T))（e^{+jωt} 约定，London 感应电流）；小比值
  σ₁/σ₂ ≪ 1 展开的一阶恒等 Rs ≈ (σ₁/(2σ₂))·ωμ0λ_L（内核
  ratio_approx_ohm 字段同式，测试互证）。
- BCS 能隙：Δ0 = 1.764·k_B·Tc（弱耦合 BCS 比值数值常数）；Δ(T)
  Mühlschlegel 近似 Δ(T) = Δ0·tanh(1.74√(Tc/T−1))；近 Tc GL 极限
  Δ(T→Tc) ≈ 1.74·Δ0·√(1−t)（tanh 小宗量极限，独立第二锚）。

适用域与边界
------------
- material ∈ {Nb, NbTiN, Al}（SUPERCONDUCTOR_TABLE 文献带，single_source
  band 标记——#122 不冒充仲裁值；ρ_n 随 RRR/工艺强变化，输出按名义带）。
- 温度域 0 < T < Tc（正常态支路 T≥Tc 显式拒绝=内核同款语义；T→0 的
  σ₁→0 支路被内核 _positive 守卫拒绝，本键同域 0<t/Tc<1）。
- 局部极限适用判据：膜厚/曲率半径 ≫ λ_L、晶粒尺寸 ≫ 相干长度（BCS
  工程档）；非局域（CLEAN/反常趋肤）、residual Rs（两能级缺陷 TLS 面）
  档**不加**——R2_core_tier5 §⑤-1 预声明"residual 档 ⚠️ 不加"，Gao
  2008 归一化常数未双源核对不产数（#122）。
- boundary：qubit_readout（读出链 χ/S21/SNR 数值面）、cryo_materials
  （介质损耗面）、conductor_loss（正常导体 Rs/粗糙度面）。

锚（#118 独立算术，tests/unit/test_w3k_pool_domains.py）：①Nb@5GHz/
4.2K 的 Rs 与一阶恒等 ratio_approx 相对差 <1e-6（σ₁/σ₂~5e-5 展开余项
O(ε²)~3e-9）；②Rs ∝ f² 局部极限幂律（f 减半 → Rs×¼）；③t→0⁺ λ_L→λ_L0
逐位退化；④Δ(t=0)=1.764·k_B·Tc（k_B/e 由测试侧 scipy.constants 裁判，
独立于内核常数）；⑤t→Tc GL 极限 1.74Δ0√(1−t) 相对差 <1e-3（tanh 小宗
量）；⑥Al Δ0=0.1824 meV 与表值 0.182 meV 带≤0.5% 互洽。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——float(True)=1.0 静默污染面 df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _resolve_material(material: Any) -> dict[str, Any]:
    """材料参数行解析（未知材料显式拒绝；字符串档显式校验）。"""
    from rfauto.core.quantum_cryo import superconductor_params

    if not isinstance(material, str):
        raise ValueError(
            f"material 须为字符串档 {sorted(['Nb', 'NbTiN', 'Al'])}，"
            f"实际 {material!r}")
    return superconductor_params(material)


@register_calculator(
    "superconductor_rs",
    "超导面电阻Rs（BCS两流体）：局部极限 Rs=Re[√(jωμ0/(σ₁−jσ₂))]，"
    "σ₁=σn·t⁴（Gittleman-Rosenblum 1966）、λ_L(T)=λ_L0/√(1−t⁴)（同一"
    "两流体推论）、σ₂=1/(μ0ωλ²)，附小比值一阶恒等 (σ₁/2σ₂)·ωμ0λ 互证"
    "字段；材料档 Nb/NbTiN/Al 文献带（single_source，#122）；温度域 "
    "0<T<Tc（正常态与 T→0 支路显式拒绝）；residual Rs 档不加（R2 预"
    "声明）。单源 core/quantum_cryo（提升核注册面）",
    (("material", "str 超导材料档：Nb/NbTiN/Al（文献带参数表）"),
     ("f_hz", "float Hz 工作频率（>0）"),
     ("t_k", "float K 工作温度（0<T<Tc，正常态支路显式拒绝）")),
    required=("material", "f_hz", "t_k"),
)
def superconductor_rs(material: str, f_hz: float,
                      t_k: float) -> dict[str, Any]:
    from rfauto.core.quantum_cryo import superconductor_rs as _rs_kernel
    from rfauto.core.quantum_cryo import two_fluid_sigma1

    row = _resolve_material(material)
    freq = _num(f_hz, "f_hz")
    if freq <= 0.0:
        raise ValueError(f"superconductor_rs: f_hz 必须 >0，得 {freq}")
    temp = _num(t_k, "t_k")
    if temp <= 0.0:
        raise ValueError(
            "superconductor_rs: t_k 必须 >0（T→0 的 σ₁→0 支路在局部极限"
            f"内核定义域外，显式拒绝），得 {temp}")
    tc = _num(row["tc_k"], "tc_k")
    ratio = temp / tc
    if ratio >= 1.0:
        raise ValueError(
            f"superconductor_rs: T>=Tc（正常态支路不在语义内），"
            f"t/Tc={ratio}")

    # 正常态电导率：ρ_n[µΩ·cm] → Ω·m（1 µΩ·cm = 1e-8 Ω·m）；σn=1/ρn
    rho_n = _num(row["rho_n_uohm_cm"], "rho_n_uohm_cm") * 1.0e-8
    sigma_n = 1.0 / rho_n
    sigma1 = two_fluid_sigma1(sigma_n, temp, tc)
    # 两流体 London 穿透深度温度律 λ_L(T)=λ_L0/√(1−t⁴)
    lam0 = _num(row["lambda_l0_nm"], "lambda_l0_nm") * 1.0e-9
    lambda_t = lam0 / math.sqrt(1.0 - ratio ** 4)

    out = _rs_kernel(sigma1, lambda_t, freq)
    return {
        "material": material,
        "f_hz": freq,
        "t_k": temp,
        "tc_k": tc,
        "t_ratio": round(ratio, 15),
        "rho_n_ohm_m": rho_n,
        "sigma_n_s_per_m": round(sigma_n, 12),
        # 极低温档 σ₁ 可至 1e-17 量级——禁 12 位小数 round（会归零，
        # #117 falsy 族数值版），保持原始浮点（JSON 安全）
        "sigma1_s_per_m": sigma1,
        "lambda_l0_nm": round(lam0 * 1.0e9, 12),
        "lambda_l_t_nm": round(lambda_t * 1.0e9, 12),
        "rs_ohm": out["rs_ohm"],
        "zs_imag_ohm": out["zs_imag"],
        "sigma2_s_per_m": out["sigma2_s_per_m"],
        "sigma1_over_sigma2": sigma1 / out["sigma2_s_per_m"],
        "ratio_approx_ohm": out["ratio_approx_ohm"],
        "note": (
            "局部极限（London）BCS 工程档：σ₁=σn·t⁴、λ_L(T)=λ_L0/√(1−t⁴)"
            "（两流体）；Rs 与 (σ₁/2σ₂)·ωμ0λ 一阶恒等在 σ₁≪σ₂ 域互证"
            "（展开余项 O((σ₁/σ₂)²)）；ρ_n 随 RRR/工艺强变化（band 名义"
            "档）；residual Rs/TLS 面与 Gao 2008 归一化常数不产数（#122）"),
        "source": (
            "Gittleman-Rosenblum 1966（t⁴ 口径名）；Tinkham 2nd（两流体/"
            "London 口径名）；Gao 2008（工程近似口径名）；页码 UNVERIFIED"
            "（#122 如实）"),
    }


@register_calculator(
    "superconductor_gap",
    "超导能隙（BCS）：Δ0=1.764·k_B·Tc（弱耦合比值常数）+Mühlschlegel "
    "近似 Δ(T)=Δ0·tanh(1.74√(Tc/T−1))，附近 Tc GL 极限 1.74·Δ0·√(1−t) "
    "独立参照字段与材料表文献带参考值（Nb/NbTiN/Al，#122 band 标记）；"
    "温度域 0≤T<Tc。单源 core/quantum_cryo（提升核注册面）",
    (("material", "str 超导材料档：Nb/NbTiN/Al（文献带参数表）"),
     ("t_k", "float K 工作温度（0≤T<Tc；t=0 返回 Δ0 逐位）")),
    required=("material", "t_k"),
)
def superconductor_gap(material: str, t_k: float) -> dict[str, Any]:
    from rfauto.core.quantum_cryo import (
        BCS_GAP_RATIO,
        GL_THERMAL_RATIO,
        bcs_gap_ev,
    )

    row = _resolve_material(material)
    temp = _num(t_k, "t_k")
    if temp < 0.0:
        raise ValueError(f"superconductor_gap: t_k 须 ≥0，得 {temp}")
    tc = _num(row["tc_k"], "tc_k")
    ratio = temp / tc
    if ratio >= 1.0:
        raise ValueError(
            f"superconductor_gap: T>=Tc（正常态无能隙，不产数），"
            f"t/Tc={ratio}")

    delta0_ev = bcs_gap_ev(tc, 0.0)
    delta_t_ev = bcs_gap_ev(tc, temp)
    # 近 Tc GL 极限独立参照：1.74·Δ0·√(1−t)（tanh 小宗量极限）
    gl_ref_ev = GL_THERMAL_RATIO * delta0_ev * math.sqrt(1.0 - ratio)
    table_delta0_mev = _num(row["delta0_meV"], "delta0_meV")
    return {
        "material": material,
        "t_k": temp,
        "tc_k": tc,
        "t_ratio": round(ratio, 15),
        "bcs_gap_ratio": BCS_GAP_RATIO,
        "delta0_ev": delta0_ev,
        "delta0_meV": round(delta0_ev * 1.0e3, 12),
        "delta_t_ev": delta_t_ev,
        "delta_t_meV": round(delta_t_ev * 1.0e3, 12),
        "gl_near_tc_ev": gl_ref_ev,
        "gl_vs_tanh_rel": (round((delta_t_ev - gl_ref_ev) / delta_t_ev, 12)
                           if delta_t_ev > 0.0 else None),
        "table_delta0_meV": table_delta0_mev,
        "table_band_note": (
            "表值为文献带中心（single_source band，#122 不冒充仲裁值）；"
            "本键 Δ0 按弱耦合比值 1.764·k_B·Tc 精算，与表值差即材料的"
            "强耦合/工艺偏离（NbTiN 显著、Nb/Al 带 ≤0.5%）"),
        "source": (
            "BCS 弱耦合比值 1.764（数值常数锚）；Mühlschlegel 近似；"
            "GL 近 Tc 极限 1.74（登记近似）；材料带=Tinkham/Mattis 经典"
            "带（single_source，#122 如实）"),
    }
