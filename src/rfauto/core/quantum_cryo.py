"""MA 量子探索档（登记级）：超导微波面电阻（BCS 两流体/MB 支路）+ RCSJ 结。

规格：研究扩充 round17 §六 MA-11（量子探索档，
P3，只闭式与数据）——"BCS/Mattis-Bardeen Gao 2008 工程近似；Nb/NbTiN/Al
参数表；RCSJ 纯 ODE 闭式（IV/ωp/Stewart-McCumber）；Tq=hν/2k+色散位移
χ/Purcell（登记级）；JPA 增益带宽（登记级）"。任务书 ge8b Wave A 席4
（量子=BCS Rs+RCSJ 登记级可实现为知识+闭式函数）。纯闭式叶子，零 IO、
不进 calculators。

模块面
------
- ``superconductor_params``：Nb/NbTiN/Al 参数表（Tc、Δ0、λ_L0、ρ_n）——
  文献带（band 形式，single_source 标记，#122 不冒充仲裁值）。
- ``bcs_gap_ev``：Δ0 = 1.764·k_B·Tc（弱耦合 BCS 比值，数值常数锚）
  与 Δ(t→Tc) GL 极限 1.74·Δ0·√(1−t)（登记近似）。
- ``two_fluid_sigma1``：σ₁(T) = σ_n·t⁴（Gittleman-Rosenblum 工程口径）。
- ``superconductor_rs``：局部极限表面电阻
  Rs = Re[√(jωμ0/(σ₁+jσ₂))]，σ₂ = 1/(μ0 ω λ_L²(T))——(σ₁/σ₂)·ωμ0λ/2
  的一阶恒等（小 σ₁/σ₂ 展开锚，测试互证）。
- ``gao_engineering_note``：Gao 2008 工程近似的归一化常数登记面——
  指数支路 Rs ∝ (f²/T)·e^{−Δ0/k_BT} 的结构性声明；**归一化常数不产**
  （未双源核对，#122 UNVERIFIED 如实）。
- ``rcsj_plasma_frequency`` / ``rcsj_stewart_mccumber``：ωp = 1/√(L_J C)、
  L_J = Φ0/(2π I_c)、β_c = ωp·R²·C（= 2π I_c R² C/Φ0）——SI 精确恒等。
- ``rcsj_iv``：无噪声 RCSJ 直流 IV（过阻尼 β_c→0 精确支
  V = R·√(I²−I_c²)；欠阻尼 β_c>0 数值 RK4 支路，回滞自洽判据）。
- ``quantum_register_note``：Tq=hν/2k、χ、Purcell、JPA 增益带宽——
  登记级声明（不做数值面，规格登记级语义）。

物理口径（全 SI；e^{+jωt}）
----------------------------
* Josephson 常数：Φ0 = h/(2e)（SI 精确，scipy.constants 裁判）。
* 两流体 σ₁ = σ_n t⁴：t=T/Tc∈[0,1)（t≥1 抛 ValueError——正常态支路
  不在本模块语义内，如实拒绝）。
* 设计约束：标准库+math/numpy（RK4 用纯 python 循环，小网格）；非法
  输入显式 ValueError；dict 输出有限数。

出处
----
1. round 文档：round17 §六 MA-11（本文首段）。
2. Gao 2008（Stanford 学位论文，工程近似口径名）；Gittleman-Rosenblum
   IEEE Proc. 1966（t⁴ 口径名）；Tinkham "Introduction to Superconductivity"
   2nd（RCSJ/两流体口径名）。页码 UNVERIFIED 如实（#122）。
"""
from __future__ import annotations

import cmath
import math
from typing import Any

__all__ = [
    "BCS_GAP_RATIO",
    "GL_THERMAL_RATIO",
    "PHI0_WEBER",
    "QUANTUM_SOURCE",
    "SUPERCONDUCTOR_TABLE",
    "bcs_gap_ev",
    "gao_engineering_note",
    "quantum_register_note",
    "rcsj_iv",
    "rcsj_plasma_frequency",
    "rcsj_stewart_mccumber",
    "superconductor_params",
    "superconductor_rs",
    "two_fluid_sigma1",
]

# SI 精确常数：h/(2e)，h=6.62607015e-34 J·s（2019 SI 定义）、e=1.602176634e-19 C
PHI0_WEBER = 6.62607015e-34 / (2.0 * 1.602176634e-19)
#: 弱耦合 BCS 能隙比 Δ0 = 1.764 k_B Tc（数值常数锚）
BCS_GAP_RATIO = 1.764
#: GL 近 Tc 能隙比 Δ(T→Tc) = 1.74 Δ0 √(1−t)（登记近似）
GL_THERMAL_RATIO = 1.74
KB_EV_PER_K = 8.617333262e-5  # eV/K（CODATA，测试侧 scipy.constants 裁判）
QUANTUM_SOURCE = (
    "Gao 2008（工程近似口径名）；Gittleman-Rosenblum 1966（t4 口径名）；"
    "Tinkham 2nd（RCSJ/两流体口径名）；页码 UNVERIFIED（#122 如实）"
)

#: Nb/NbTiN/Al 参数表（band 形式：中心值+文献带；single_source 标记）
SUPERCONDUCTOR_TABLE: dict[str, dict[str, Any]] = {
    "Nb": {
        "tc_k": 9.25,
        "tc_band_k": (9.2, 9.3),
        "delta0_meV": 1.50,       # ≈1.764·kB·9.25K
        "lambda_l0_nm": 39.0,
        "lambda_band_nm": (32.0, 40.0),
        "rho_n_uohm_cm": 5.0,     # 随 RRR 强变化（band 上界宽，band 标记）
        "source": (
            "SRF/量子电路文献带（Tinkham/ Mattis 经典带；single_source "
            "band 形式，#122 不冒充仲裁值）"
        ),
    },
    "NbTiN": {
        "tc_k": 14.5,
        "tc_band_k": (13.5, 15.5),
        "delta0_meV": 2.20,
        "lambda_l0_nm": 360.0,
        "lambda_band_nm": (240.0, 400.0),
        "rho_n_uohm_cm": 60.0,
        "source": (
            "超导量子电路文献带（宽 band：氮分压/工艺强依赖；"
            "single_source band 形式）"
        ),
    },
    "Al": {
        "tc_k": 1.20,
        "tc_band_k": (1.14, 1.20),
        "delta0_meV": 0.182,
        "lambda_l0_nm": 16.0,
        "lambda_band_nm": (15.0, 50.0),
        "rho_n_uohm_cm": 2.74,
        "source": (
            "Al 薄膜隧畔结文献带（λ 厚度依赖宽 band；single_source "
            "band 形式）"
        ),
    },
}


def superconductor_params(material: str) -> dict[str, Any]:
    """材料参数行（只读副本；material ∈ {Nb, NbTiN, Al}）。"""
    if material not in SUPERCONDUCTOR_TABLE:
        raise ValueError(f"material 须 ∈ {sorted(SUPERCONDUCTOR_TABLE)}，"
                         f"实际 {material!r}")
    return dict(SUPERCONDUCTOR_TABLE[material])


def bcs_gap_ev(tc_k: Any, t_k: Any) -> float:
    """BCS 能隙（eV），Mühlschlegel 近似：Δ(T) = Δ0·tanh(1.74√(Tc/T−1))。

    t=0 → Δ0 = 1.764·kB·Tc（逐位）；t→Tc → GL 极限 1.74Δ0√(1−t)
    （tanh x ≈ x）；t≥Tc 显式 ValueError（正常态不产数）。
    """
    tc = _positive(tc_k, "tc_k")
    t = _temp_ratio(t_k, tc)
    delta0 = BCS_GAP_RATIO * KB_EV_PER_K * tc
    if t == 0.0:
        return delta0
    return delta0 * math.tanh(GL_THERMAL_RATIO * math.sqrt(1.0 / t - 1.0))


def _positive(x: Any, name: str) -> float:
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {x!r}")
    return v


def _temp_ratio(t_k: Any, tc_k: Any) -> float:
    t = float(t_k)
    if not math.isfinite(t) or t < 0.0:
        raise ValueError(f"t_k 必须为非负有限数，实际 {t_k!r}")
    ratio = t / tc_k
    if ratio >= 1.0:
        raise ValueError(f"T>=Tc（正常态支路不在本模块语义内），t/Tc={ratio}")
    return ratio


def two_fluid_sigma1(sigma_n: Any, t_k: Any, tc_k: Any) -> float:
    """两流体 σ₁(T) = σ_n·t⁴（S/m；Gittleman-Rosenblum 工程口径）。"""
    sn = _positive(sigma_n, "sigma_n")
    tc = _positive(tc_k, "tc_k")
    t = _temp_ratio(t_k, tc)
    return sn * t**4


def superconductor_rs(sigma1_s_per_m: Any, lambda_l_m: Any,
                      f_hz: Any) -> dict[str, float]:
    """局部极限超导面电阻 Rs = Re[√(jωμ0/(σ₁−jσ₂))]，σ₂=1/(μ0ωλ²)。

    e^{+jωt} 约定下超导电导 σ=σ₁−jσ₂（London 感应）；σ₁→0 时
    Zs→+jωμ0λ（纯感应，Re→0——测试钉）。返回 {rs_ohm, zs_real,
    zs_imag, sigma2_s_per_m, ratio_approx_ohm}——ratio_approx_ohm =
    (σ₁/2σ₂)·ωμ0λ 的小比值一阶恒等（Gittleman-Rosenblum 支，测试互证）。
    """
    s1 = _positive(sigma1_s_per_m, "sigma1_s_per_m")
    lam = _positive(lambda_l_m, "lambda_l_m")
    f = _positive(f_hz, "f_hz")
    mu0 = 4.0e-7 * math.pi
    omega = 2.0 * math.pi * f
    sigma2 = 1.0 / (mu0 * omega * lam * lam)
    # 时谐约定 e^{+jωt}（本仓口径）：超导电导 σ = σ1 − jσ2（London 电流
    # 滞后 E 90°；σ2 = 1/(μ0 ω λ²) 取正幅值）——用 +jσ2 会把 London
    # 感应面错成实电阻（非物理），测试侧钉 σ1→0 时 Re[Zs]→0。
    zs = cmath.sqrt(1j * omega * mu0 / complex(s1, -sigma2))
    ratio_approx = (s1 / (2.0 * sigma2)) * omega * mu0 * lam
    return {
        "rs_ohm": zs.real,
        "zs_real": zs.real,
        "zs_imag": zs.imag,
        "sigma2_s_per_m": sigma2,
        "ratio_approx_ohm": ratio_approx,
    }


def gao_engineering_note() -> dict[str, str]:
    """Gao 2008 工程近似登记面（结构性声明；归一化常数不产数）。"""
    return {
        "structure": (
            "余辉支路：Rs_BCS ∝ (f²/T)·exp(−Δ0/(k_B T))（f² 幂律与 "
            "指数温度支路的结构性口径）"
        ),
        "normalization": (
            "归一化常数依赖材料/工艺（残阻/α²F）——未双源核对不产数"
            "（#122 UNVERIFIED 如实）"
        ),
        "source": "Gao 2008（口径名，页码 UNVERIFIED）",
    }


# ─── RCSJ 结 ────────────────────────────────────────────────────────────────
def rcsj_plasma_frequency(ic_a: Any, c_farad: Any) -> dict[str, float]:
    """等离子体频率 ωp = 1/√(L_J C)，L_J = Φ0/(2π I_c)（SI 精确恒等）。"""
    ic = _positive(ic_a, "ic_a")
    c = _positive(c_farad, "c_farad")
    lj = PHI0_WEBER / (2.0 * math.pi * ic)
    omega_p = 1.0 / math.sqrt(lj * c)
    return {"lj_henry": lj, "omega_p_rad_s": omega_p,
            "f_p_hz": omega_p / (2.0 * math.pi)}


def rcsj_stewart_mccumber(ic_a: Any, r_ohm: Any, c_farad: Any) -> dict[str, float]:
    """Stewart-McCumber 参数 β_c = ωp R² C = 2π I_c R² C/Φ0（SI 精确恒等）。

    β_c<1 过阻尼（无回滞）、>1 欠阻尼（回滞）。
    """
    ic = _positive(ic_a, "ic_a")
    r = _positive(r_ohm, "r_ohm")
    c = _positive(c_farad, "c_farad")
    beta_c = 2.0 * math.pi * ic * r * r * c / PHI0_WEBER
    omega_p = rcsj_plasma_frequency(ic, c)["omega_p_rad_s"]
    return {"beta_c": beta_c, "omega_p_rad_s": omega_p,
            "regime": "underdamped" if beta_c > 1.0 else "overdamped"}


def rcsj_iv(ic_a: Any, r_ohm: Any, c_farad: Any,
            i_max_factor: Any = 2.0, n_steps: Any = 200) -> dict[str, Any]:
    """无噪声 RCSJ 直流 IV（RK4 斜坡，i 从 0.5·Ic 升到 i_max 再降回）。

    无量纲方程（τ=ωp·t）：β_c φ'' + φ' = i − sinφ。
    - β_c ≤ 0.5（过阻尼）：直接积分一阶 RSJ 精确支 φ' = i − sinφ
      （φ 对 τ' = 2π Ic R t/Φ0 归一），运行支 ⟨V⟩ = R√(I²−Ic²)
      （解析锚，overdamped_check 给数值对）。
    - β_c > 0.5（欠阻尼）：全二阶积分；降流支在 i<1 处呈亚稳运行态
      （有限时窗表观回滞；噪声面不做，如实声明）。
    返回 {i_over_a, v_up_v, v_down_v, beta_c, regime, overdamped_check}。
    """
    ic = _positive(ic_a, "ic_a")
    r = _positive(r_ohm, "r_ohm")
    c = _positive(c_farad, "c_farad")
    fac = float(i_max_factor)
    if fac <= 1.0:
        raise ValueError("i_max_factor 须 >1")
    n = int(n_steps)
    if n < 50:
        raise ValueError("n_steps 须 >=50")
    beta_c = rcsj_stewart_mccumber(ic, r, c)["beta_c"]
    i_grid = [0.5 + (fac - 0.5) * k / (n - 1) for k in range(n)]
    v_scale = (PHI0_WEBER / (2.0 * math.pi)) * (
        1.0 / math.sqrt((PHI0_WEBER / (2.0 * math.pi * ic)) * c))
    # ↑ (Φ0/2π)·ωp：无量纲 ⟨φ'⟩（τ=ωp t 归一）→ 有量纲 V 的因子
    overdamped = beta_c <= 0.5

    def sweep(i_values: list[float], phi0: float = 0.0,
              v0: float = 0.0) -> tuple[list[float], float, float]:
        v_out = []
        if overdamped:
            # 一阶 RSJ（τ' 归一）：dφ/dτ' = i − sinφ
            phi = phi0
            dt = 0.01
            for i_norm in i_values:
                tail = []
                for s in range(4000):
                    k1 = i_norm - math.sin(phi)
                    k2 = i_norm - math.sin(phi + 0.5 * dt * k1)
                    k3 = i_norm - math.sin(phi + 0.5 * dt * k2)
                    k4 = i_norm - math.sin(phi + dt * k3)
                    phi += dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
                    if s >= 2000:
                        tail.append(i_norm - math.sin(phi))
                v_out.append(sum(tail) / len(tail) * ic * r)
            return v_out, phi, 0.0
        # 全二阶（τ=ωp t 归一）：β_c φ'' + φ' = i − sinφ
        phi, v = phi0, v0
        dt = 0.01
        for i_norm in i_values:
            tail = []
            for s in range(1600):
                k1p, k1v = v, (i_norm - math.sin(phi) - v) / beta_c
                k2p, k2v = v + 0.5 * dt * k1v, (
                    i_norm - math.sin(phi + 0.5 * dt * k1p)
                    - (v + 0.5 * dt * k1v)) / beta_c
                k3p, k3v = v + 0.5 * dt * k2v, (
                    i_norm - math.sin(phi + 0.5 * dt * k2p)
                    - (v + 0.5 * dt * k2v)) / beta_c
                k4p, k4v = v + dt * k3v, (
                    i_norm - math.sin(phi + dt * k3p)
                    - (v + dt * k3v)) / beta_c
                phi += dt / 6.0 * (k1p + 2 * k2p + 2 * k3p + k4p)
                v += dt / 6.0 * (k1v + 2 * k2v + 2 * k3v + k4v)
                if s >= 1300:
                    tail.append(v)
            v_out.append(max(sum(tail) / len(tail), 0.0) * v_scale)
        return v_out, phi, v

    v_up, phi_end, v_end = sweep(i_grid)
    # 降流支从升支终态（运行态）延续——亚稳回滞的物理前提（如实口径）
    v_down_rev, _, _ = sweep(list(reversed(i_grid)), phi_end, v_end)
    v_down = list(reversed(v_down_rev))
    # 过阻尼运行支精确式互证：i=1.5 处数值 vs R√(I²−Ic²)（相对差）
    check = None
    if overdamped:
        i_mid = min(1.5, (0.5 + fac) / 2.0 + 0.5)
        i_mid = max(i_mid, 1.01)
        idx = min(range(n), key=lambda k: abs(i_grid[k] - i_mid))
        v_exact = r * math.sqrt(i_grid[idx] ** 2 - 1.0) * ic
        if v_exact > 0.0:
            check = abs(v_up[idx] - v_exact) / v_exact
    return {
        "i_over_a": i_grid,
        "v_up_v": v_up,
        "v_down_v": v_down,
        "beta_c": beta_c,
        "regime": "underdamped" if beta_c > 1.0 else "overdamped",
        "overdamped_check": check,
    }


def quantum_register_note() -> dict[str, str]:
    """Tq/χ/Purcell/JPA 登记级声明（规格登记级语义，不做数值面）。"""
    return {
        "thermal_quanta": "Tq = hν/(2 k_B)（hν≪k_BT 时 Tq≈hν/k_B 口径名）",
        "dispersive_shift": "χ = g²/(Δ) 一阶口径名（Jaynes-Cummings 色散支）",
        "purcell": "Γ_Purcell = (g/Δ)²·κ 口径名",
        "jpa": "JPA 增益带宽 ∝ √(泵浦功率) 口径名",
        "boundary": (
            "全部登记级：只口径声明不做数值判据（工艺依赖强，规格 "
            "no-go 条款）"
        ),
    }
