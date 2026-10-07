"""F-H.4 低温材料面内核：Cu Rs(T) 正常/反常趋肤 + 超导 London 面 + 低温介电表 + Q(T)/f0(T)。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- **Cu 电阻率（Matthiessen 两项 + RRR 参数化）**：ρ(T) = ρ_res + ρ_ph(T)，
  ρ_res = ρ_ref/RRR（杂质/缺陷散射剩余项，深低温平台），ρ_ph(T) =
  (ρ_ref − ρ_ref/RRR)·(T/T_ref)（声子项线性近似，T_ref = 293 K）。锚点
  恒等式：T=0 → ρ_ref/RRR（逐位）；T=T_ref → ρ_ref（锚点）；RRR 定义
  恒等式 ρ(T_ref)/ρ(0) = RRR（本模型构造性精确成立）。ρ_ref = 1.68e-8
  Ω·m（退火铜 20°C 手册典型值）。**UNVERIFIED 简化**：线性声子项在
  深低温（≲ Θ_D/3 ≈ 114 K，Θ_D=343 K）高估声子贡献（Bloch-Grüneisen
  T⁵ 滚降未建模）——4 K 实测 ρ(4K)/ρ(293K) 更接近 1/RRR（剩余项主导），
  线性模型给出带内上界 [1/RRR, (1+(RRR−1)·4/293)/RRR]（单测钉推导带）；
  需要 4 K 精度时应改用 NIST 低温材料拟合表（followUp 登记）。
- **正常趋肤表面电阻**：Rs = √(π·f·μ₀·ρ)（Pozar《Microwave Engineering》
  良导体口径；同式异构 √(ω·μ₀·ρ/2)，ω=2πf——单测双路径）。μ₀ =
  1.25663706212e-6 N/A²（CODATA 2018 推荐值；2019 SI 后 μ₀ 非精确定义，
  旧值 4πe-7 相对差 ~5.4e-10）。
- **反常趋肤（ASE）分界**：正常趋肤成立条件 δ ≫ l（趋肤深度 ≫ 电子平均
  自由程）。δ = √(ρ/(π·f·μ₀))；Drude 自由电子气 l = v_F·m_e/(n·e²·ρ)
  （ρ = m/(n e² τ) 反解 τ，l = v_F·τ）。分界频率由 δ(f_c)=l 定义恒等式：
  f_c = ρ/(π·μ₀·l²)（单测钉 δ(f_c)==l）。Cu 常数：n = 8.47e28 m⁻³
  （密度 8.96 g/cm³、摩尔质量 63.546 g/mol 一价自由电子），v_F =
  1.57e6 m/s。regime 判类：δ > l → "normal"，否则 "anomalous"。Chambers
  反常区表面阻抗幅值（Rs ∝ ω^(2/3) 精确系数）**未实现**（UNVERIFIED，
  见下清单）——本模块只做分界判类，规格书"RRR≲15 无 ASE"（arXiv
  2211.00135 口径）以 f_c 位置呈现，不内嵌门槛数值。
- **超导 London 面（两流体 Gorter-Cassimir）**：λ_L(T) = λ_L(0)/√(1−t⁴)，
  t = T/T_c（C.J. Gorter & H.B.G. Casimir, Physica 1:306 (1934)；Tinkham
  《Introduction to Superconductivity》口径）。发散守卫：t ≥ T_c/T_c 即
  t≥1 显式报错（λ→∞）；t=0 → λ_L(0) 逐位。**薄膜动能电感**（薄膜极限
  t_film ≪ λ）：L_s,□ = μ₀·λ²/t_film（H/□；精确式 μ₀λ·coth(t_film/λ) 的
  薄膜展开首项，Tinkham/Zmuidzinas Annu. Rev. Condens. Matter Phys.
  3:169 (2012) 口径）。表面电抗 X_s = ω·L_s。
- **Q(T)/f0(T) 最小可用面**：无载 Q 倒数按损耗通道相加 1/Q = tanδ_eff +
  R_s/G（谐振器通用口径：介质损耗 tanδ、导体损耗经几何因子 G[Ω] 折算
  Q_c = G/R_s——SRF 惯例/Pozar 口径；仅给 tanδ → 1/tanδ）。f0(T) 经动
  能电感分数 κ_k：L_total(T) = L_g + L_k0·r(T)，r = (λ(T)/λ(0))²，
  f = f₀/√((1−κ_k) + κ_k·r(T))（LC 振子 f∝1/√L 的构造性恒等；
  κ_k = L_k0/(L_g+L_k0) 为 T=0 动能电感分数）。κ_k=0 → f₀ 逐位不变
  （无动能电感通道）。Nb 典型常数表（T_c、λ_L(0)）登记 provenance，
  点值落带内单测钉（单源如实标注）。
- **低温介电表**：蓝宝石/氧化铝/PTFE 的 εr 与 tanδ 典型带（300 K 与 4 K
  @10 GHz 口径），band 形式登记（单值不冒充仲裁值），来源 Krupka 低温
  介电测量汇编+OSTI 汇编（round4 方案书 [16]），**部分单源如实标注**
  （single_source=true，未经本仓真机仲裁）。

诚实边界（预声明，UNVERIFIED 清单）：
1. 线性声子项深低温高估（Bloch-Grüneisen 未建模，见上）；
2. Chambers 反常趋肤 Rs 幅值（ω^(2/3) 系数）未实现——只有分界判类；
3. Nb Rs(T) 闭式（Mattis-Bardeen BCS 准粒子项）未实现——超导面只有
   London 电抗 X_s，R_s 由调用方外供（实测或 MB 理论另行计算）后进 Q；
4. 两流体 λ(T)=λ0/√(1−t⁴) 在 t→1 域与强耦合/非局域修正偏离（ crude
   近似）；脏超导/合金（NbTi、NbN）λ0 与温度律不同（本表只收 Nb 典型）；
5. 介电表 band 为文献典型域（单源），未做逐牌号数据表核对；tanδ 频段
   外推未标注（10 GHz 口径）；
6. Q(T) 面忽略辐射损耗/准粒子 BCS Rs(T) 通道/耦合损耗（Q_loaded 未建模）；
   f0(T) 电路模型忽略场再分布与二级位移项。

接口：全部函数返回 JSON 可序列化 float/dict/str/bool/None；单位钉在参数
名（K/Ω·m/Hz/m/H·□⁻¹）。数值 0.0 合法（判缺失一律 is not None，#364④）；
bool 显式拒收（df7+⑯）；非有限拒收。纯函数零 IO；不进 calculators 注册
表（F-C P1 域内约定，消费者是 service/cryo_materials_service.py）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ─── 物理常数（出处见 docstring）─────────────────────────────────────────────

#: 真空磁导率（N/A²，CODATA 2018 推荐值；2019 SI 后非精确定义）
MU0_SI = 1.25663706212e-6
#: 铜电阻率参考值（Ω·m，退火铜 20°C 手册典型值）
CU_RHO_REF_OHM_M = 1.68e-8
#: 铜参考温度（K，20°C）
CU_T_REF_K = 293.0
#: 铜德拜温度（K；仅用于适用域注记，不进公式）
CU_THETA_D_K = 343.0
#: 铜自由电子密度（m⁻³，一价自由电子气口径）
CU_N_FREE_E_M3 = 8.47e28
#: 铜费米速度（m/s）
CU_V_F_M_PER_S = 1.57e6
#: 电子质量（kg，CODATA 2018）
ELECTRON_MASS_KG = 9.1093837015e-31
#: 元电荷（C，SI 精确定义）
ELEMENTARY_CHARGE_C = 1.602176634e-19

#: Nb 超导典型常数（单源典型，未经本仓仲裁——spec 低温常数面"只补材料层"）
NB_TYPICAL: dict[str, Any] = {
    "tc_k": 9.3,
    "tc_band_k": [9.2, 9.3],
    "lambda_l0_nm": 39.0,
    "lambda_l0_band_nm": [35.0, 44.0],
    "status": "typical",
    "single_source": True,
    "provenance": "Nb T_c 与 λ_L(0) 文献典型值（Tinkham 教科书口径+SRF/MkID "
    "文献域 35-44 nm）——单源典型带，未经本仓真机仲裁",
}

#: 低温介电典型带表（εr 无量纲、tanδ 无量纲；10 GHz 口径；部分单源如实）
CRYO_DIELECTRICS: dict[str, dict[str, Any]] = {
    "sapphire_al2o3": {
        "er_band": [9.3, 11.6],  # 各向异性（⊥/∥ 两轴带）
        "tan_delta_band_300k_10ghz": [1e-5, 1e-4],
        "tan_delta_band_4k_10ghz": [1e-9, 1e-7],
        "status": "typical_band",
        "single_source": True,
        "provenance": "Krupka 低温介电测量+OSTI 汇编（round4 方案书 [16]）"
        "——单源典型带，未经本仓仲裁",
    },
    "alumina_99p6": {
        "er_band": [9.5, 10.0],
        "tan_delta_band_300k_10ghz": [3e-5, 3e-4],
        "tan_delta_band_4k_10ghz": [1e-7, 1e-5],
        "status": "typical_band",
        "single_source": True,
        "provenance": "多晶氧化铝低温 tanδ 文献带（Krupka/OSTI 汇编路线，"
        "含量与工艺敏感）——单源典型带",
    },
    "ptfe": {
        "er_band": [2.0, 2.1],
        "tan_delta_band_300k_10ghz": [1.5e-4, 4e-4],
        "tan_delta_band_4k_10ghz": [1e-6, 1e-4],
        "status": "typical_band",
        "single_source": True,
        "provenance": "PTFE 低温损耗文献带（Krupka/OSTI 汇编路线）——单源"
        "典型带，4 K 档数据稀疏带取宽，如实标注",
    },
}


# ─── 输入守卫（同 core/aging.py 范式）────────────────────────────────────────


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: float, name: str) -> float:
    """把入参收敛为有限非负 float，非法即显式报错。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


# ─── 铜面：ρ(T) → Rs / δ / l / ASE 分界 ──────────────────────────────────────


def copper_resistivity(t_k: float, rrr: float) -> float:
    """铜电阻率 ρ(T) = ρ_ref/RRR + (ρ_ref − ρ_ref/RRR)·(T/T_ref)（Ω·m）。

    t_k：温度（K，>=0，线性声子项适用域 T ≲ T_ref，深低温高估见模块
    docstring UNVERIFIED①）；rrr：剩余电阻比 RRR = ρ(T_ref)/ρ(0)
    （>=1；RRR=1 → 恒 ρ_ref）。锚点恒等式：t_k=0 → ρ_ref/RRR（逐位）。
    """
    t = _nonneg(t_k, "t_k")
    r = _finite(rrr, "rrr")
    if r < 1.0:
        raise ValueError(f"rrr 必须 >=1，实际 {r}")
    rho_res = CU_RHO_REF_OHM_M / r
    return rho_res + (CU_RHO_REF_OHM_M - rho_res) * (t / CU_T_REF_K)


def normal_skin_rs_ohm(rho_ohm_m: float, f_hz: float) -> float:
    """正常趋肤表面电阻 Rs = √(π·f·μ₀·ρ)（Ω/□）。f=0 → 0.0 逐位（直流）。"""
    rho = _nonneg(rho_ohm_m, "rho_ohm_m")
    f = _nonneg(f_hz, "f_hz")
    return math.sqrt(math.pi * f * MU0_SI * rho)


def skin_depth_m(rho_ohm_m: float, f_hz: float) -> float:
    """趋肤深度 δ = √(ρ/(π·f·μ₀))（m）。f=0 → 非有限（除零）显式报错。"""
    rho = _nonneg(rho_ohm_m, "rho_ohm_m")
    f = _positive(f_hz, "f_hz")
    return math.sqrt(rho / (math.pi * f * MU0_SI))


def carrier_mean_free_path_m(rho_ohm_m: float) -> float:
    """Drude 电子平均自由程 l = v_F·m_e/(n·e²·ρ)（m，Cu 常数口径）。"""
    rho = _positive(rho_ohm_m, "rho_ohm_m")
    return CU_V_F_M_PER_S * ELECTRON_MASS_KG / (
        CU_N_FREE_E_M3 * ELEMENTARY_CHARGE_C**2 * rho
    )


def ase_crossover_freq_hz(rho_ohm_m: float) -> float:
    """反常趋肤分界频率 f_c = ρ/(π·μ₀·l²)（Hz；由 δ(f_c)=l 定义恒等式反解）。

    f ≪ f_c → 正常趋肤；f ≫ f_c → 反常趋肤。低于 f_c/10 量级才可靠按
    正常趋肤取 Rs（渐近过渡区无窄边）。
    """
    rho = _positive(rho_ohm_m, "rho_ohm_m")
    l_m = carrier_mean_free_path_m(rho)
    return rho / (math.pi * MU0_SI * l_m * l_m)


def skin_regime(rho_ohm_m: float, f_hz: float) -> str:
    """趋肤区判类：δ > l → "normal"，否则 "anomalous"（分界即 δ=l）。"""
    delta = skin_depth_m(rho_ohm_m, f_hz)
    l_m = carrier_mean_free_path_m(rho_ohm_m)
    return "normal" if delta > l_m else "anomalous"


@dataclass(frozen=True)
class CryoSurfaceResult:
    """铜低温表面面单点结果（to_dict() 输出 JSON 可序列化）。"""

    t_k: float
    rrr: float
    rho_ohm_m: float
    rs_ohm_per_sq: float
    skin_depth_m: float
    mean_free_path_m: float
    f_crossover_hz: float
    regime: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "t_k": self.t_k,
            "rrr": self.rrr,
            "rho_ohm_m": self.rho_ohm_m,
            "rs_ohm_per_sq": self.rs_ohm_per_sq,
            "skin_depth_m": self.skin_depth_m,
            "mean_free_path_m": self.mean_free_path_m,
            "f_crossover_hz": self.f_crossover_hz,
            "regime": self.regime,
        }


def copper_surface_face(t_k: float, rrr: float, f_hz: float) -> CryoSurfaceResult:
    """铜面端到端：ρ(T,RRR) → Rs/δ/l/f_c/regime 单点全量（低温滤波器 Rs 面）。"""
    t = _nonneg(t_k, "t_k")
    rho = copper_resistivity(t, rrr)
    return CryoSurfaceResult(
        t_k=t,
        rrr=_finite(rrr, "rrr"),
        rho_ohm_m=rho,
        rs_ohm_per_sq=normal_skin_rs_ohm(rho, f_hz),
        skin_depth_m=skin_depth_m(rho, f_hz),
        mean_free_path_m=carrier_mean_free_path_m(rho),
        f_crossover_hz=ase_crossover_freq_hz(rho),
        regime=skin_regime(rho, f_hz),
    )


# ─── 超导面：London λ(T) / 动能电感 / f0(T) ──────────────────────────────────


def london_penetration_depth_m(lambda_l0_m: float, t_k: float, tc_k: float) -> float:
    """两流体 London 穿透深度 λ(T) = λ(0)/√(1−t⁴)，t = T/T_c（m）。

    发散守卫：T ≥ T_c → ValueError（λ→∞，两流体律定义域外）；
    T=0 → λ_L(0) 逐位（√1=1 精确）；t∈(0,1) 单调增。
    """
    l0 = _positive(lambda_l0_m, "lambda_l0_m")
    t = _nonneg(t_k, "t_k")
    tc = _positive(tc_k, "tc_k")
    frac = t / tc
    if frac >= 1.0:
        raise ValueError(f"t=T/T_c={frac} >=1：两流体律 λ→∞ 发散，定义域外")
    return l0 / math.sqrt(1.0 - frac**4)


def sheet_kinetic_inductance_h_per_sq(lambda_m: float, film_thickness_m: float) -> float:
    """薄膜动能电感（H/□）L_s = μ₀·λ²/t_film（薄膜极限 t_film ≪ λ）。

    精确式 μ₀·λ·coth(t_film/λ) 的薄膜展开首项（见模块 docstring）；适用
    域由调用方核对（本函数不拦 t_film ≳ λ 的粗膜调用）。
    """
    lam = _positive(lambda_m, "lambda_m")
    tf = _positive(film_thickness_m, "film_thickness_m")
    return MU0_SI * lam * lam / tf


def sheet_surface_reactance_ohm_per_sq(
    f_hz: float, lambda_m: float, film_thickness_m: float
) -> float:
    """超导薄膜表面电抗 X_s = ω·L_s = 2πf·μ₀·λ²/t_film（Ω/□）。f=0 → 0.0。"""
    f = _nonneg(f_hz, "f_hz")
    return 2.0 * math.pi * f * sheet_kinetic_inductance_h_per_sq(lambda_m, film_thickness_m)


def superconductor_f0_hz(
    f0_at_zero_k_hz: float, kappa_kinetic: float, lambda_l0_m: float, t_k: float, tc_k: float
) -> float:
    """超导谐振器 f0(T)：f = f₀/√((1−κ_k) + κ_k·r(T))，r = (λ(T)/λ(0))²。

    f0_at_zero_k_hz：T=0 谐振频率（Hz，>0）；kappa_kinetic：T=0 动能电感
    分数 κ_k ∈ [0,1]。恒等式：κ_k=0 → f₀ 逐位（无动能电感通道）；T=0 →
    r=1 → f₀（rel 1e-15）；T→T_c 随 London 守卫报错。
    """
    f0 = _positive(f0_at_zero_k_hz, "f0_at_zero_k_hz")
    k = _finite(kappa_kinetic, "kappa_kinetic")
    if not 0.0 <= k <= 1.0:
        raise ValueError(f"kappa_kinetic 必须 ∈ [0,1]，实际 {k}")
    if k == 0.0:
        return f0
    r = (
        london_penetration_depth_m(lambda_l0_m, t_k, tc_k) / lambda_l0_m
    ) ** 2
    return f0 / math.sqrt((1.0 - k) + k * r)


# ─── Q(T) 面：损耗通道相加 ───────────────────────────────────────────────────


def resonator_unloaded_q(
    tan_delta_eff: float, rs_ohm_per_sq: float | None = None, geometry_factor_ohm: float | None = None
) -> float:
    """无载 Q = 1/(tanδ_eff + R_s/G)（介质+导体损耗通道相加口径）。

    tan_delta_eff：有效介质损耗正切（>=0，覆盖介质/磁滞/辐照等集总口径）；
    rs_ohm_per_sq 与 geometry_factor_ohm：导体通道（R_s[Ω/□] 与 G[Ω]，
    Q_c = G/R_s——二者须同时给出或同时缺省）；rs 缺省（None）→ 纯介质
    Q = 1/tanδ_eff。两通道全零 → ValueError（无耗散 Q 无定义，调用方
    自行决定 ∞ 语义）。
    """
    td = _nonneg(tan_delta_eff, "tan_delta_eff")
    if rs_ohm_per_sq is None and geometry_factor_ohm is None:
        if td == 0.0:
            raise ValueError("无耗散通道（tanδ=0 且无导体 Rs）→ Q 无定义")
        return 1.0 / td
    if rs_ohm_per_sq is None or geometry_factor_ohm is None:
        raise ValueError("导体通道须同时给 rs_ohm_per_sq 与 geometry_factor_ohm")
    rs = _nonneg(rs_ohm_per_sq, "rs_ohm_per_sq")
    g = _positive(geometry_factor_ohm, "geometry_factor_ohm")
    total = td + rs / g
    if total == 0.0:
        raise ValueError("无耗散通道（tanδ=0 且 Rs=0）→ Q 无定义")
    return 1.0 / total


@dataclass(frozen=True)
class ResonatorQResult:
    """Q 损耗分解结果（to_dict() 输出 JSON 可序列化；None=该通道未计）。"""

    q_unloaded: float
    q_dielectric: float | None
    q_conductor: float | None
    tan_delta_eff: float
    rs_ohm_per_sq: float | None
    geometry_factor_ohm: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "q_unloaded": self.q_unloaded,
            "q_dielectric": self.q_dielectric,
            "q_conductor": self.q_conductor,
            "tan_delta_eff": self.tan_delta_eff,
            "rs_ohm_per_sq": self.rs_ohm_per_sq,
            "geometry_factor_ohm": self.geometry_factor_ohm,
        }


def resonator_q_breakdown(
    tan_delta_eff: float, rs_ohm_per_sq: float | None = None, geometry_factor_ohm: float | None = None
) -> ResonatorQResult:
    """Q 损耗通道分解：1/Q = 1/Q_d + 1/Q_c（Q_d=1/tanδ、Q_c=G/R_s）。

    判据恒等式：Q_unloaded = 1/(1/Q_d + 1/Q_c)（双路径单测钉）。通道
    未计 → None（JSON 语义，#364④：缺失用 None 非 0）。
    """
    td = _nonneg(tan_delta_eff, "tan_delta_eff")
    q_d: float | None = None if td == 0.0 else 1.0 / td
    q_c: float | None = None
    if rs_ohm_per_sq is not None and geometry_factor_ohm is not None:
        rs = _nonneg(rs_ohm_per_sq, "rs_ohm_per_sq")
        g = _positive(geometry_factor_ohm, "geometry_factor_ohm")
        if rs > 0.0:
            q_c = g / rs
    inv = 0.0
    if q_d is not None:
        inv += 1.0 / q_d
    if q_c is not None:
        inv += 1.0 / q_c
    if inv == 0.0:
        raise ValueError("无耗散通道 → Q 无定义")
    return ResonatorQResult(
        q_unloaded=1.0 / inv,
        q_dielectric=q_d,
        q_conductor=q_c,
        tan_delta_eff=td,
        rs_ohm_per_sq=None if rs_ohm_per_sq is None else _nonneg(rs_ohm_per_sq, "rs_ohm_per_sq"),
        geometry_factor_ohm=(
            None if geometry_factor_ohm is None else _positive(geometry_factor_ohm, "geometry_factor_ohm")
        ),
    )
