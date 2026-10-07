"""F-H.2 湿度吸湿漂移内核：Fick 扩散 + 混合介质 εr(M) + MSL floor-life + 涂覆阻隔。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立路径，不自证，#118）：

- **Fick 一维扩散平板级数解**：J. Crank《The Mathematics of Diffusion》
  (Oxford, 2nd ed. 1975) §4.3 平板双面暴露解——初始均匀（干态）、表面
  瞬时达到平衡浓度的平板（全厚 h，双面吸湿）：
      M(t)/M∞ = 1 − (8/π²)·Σ_{n=0}^∞ (1/(2n+1)²)·exp(−(2n+1)²·π²·D·t/h²)
  n=0 项时间常数即特征时间 **τ = h²/(π²·D)**（u = π²·D·t/h² = t/τ，t=τ
  时 n=0 指数恰为 −1）。**短时 √t 律**（半无限早时近似，同书 §4.3.4）：
      M(t)/M∞ ≈ (4/√π)·√(D·t/h²)   （t ≪ τ）
  长短时切换守卫（预声明）：t/τ ≤ 0.05 域内级数与 √t 律相对差实测
  ~1.6e-15（√t 律误差在深短时域按 theta 对偶对 s 指数级小，本文件单测
  对拍钉 ≤1e-12）；放宽到 0.5τ ~0.11%、t≈τ 处 ~2.4% 越预声明门 ≤2%——
  守卫缺省 0.05τ 为保守域（级数全域有效，√t 律只在短时域是渐近）。
- **Looyenga 混合式**：H. Looyenga, Physica 31:401 (1965)——ε^(1/3) 按
  体积分数线性加权：ε_eff^(1/3) = (1−v)·ε_m^(1/3) + v·ε_i^(1/3)（v=夹杂
  体积分数）。另附两条对照混合式（"复/实介质混合三式"对照面，主口径钉
  Looyenga）：Maxwell-Garnett（球夹杂稀疏极限，J.C.M. Garnett, Phil.
  Trans. R. Soc. Lond. A 203:385 (1904)，式取基质 ε_m 相）与 Bruggeman
  对称有效介质（D.A.G. Bruggeman, Ann. Phys. 416:636 (1935)）。MG 与
  Bruggeman 稀释极限一阶同式（极化率项 3ε_m(ε_i−ε_m)/(ε_i+2ε_m)）；
  Looyenga 与它们按 O(v·对比度²) 线性分叉（ε^(1/3) 加权不保持稀释极化率
  首项，对比度大时分叉先行）——单测分级对拍钉。
- **吸湿率 → 水体积分数**：M = 吸水质量/干材质量（无量纲分数，行业
  "wt%" 口径），v = M·ρ_dry/ρ_water（干材单位质量的体积换算）。ρ_water
  缺省 1000 kg/m³（4°C 水密度精确值量级，工程缺省）；ρ_dry 由调用方给。
- **MSL floor-life**：JEDEC J-STD-033（Moisture/Reflow Sensitive SBA 的
  操作/包装/运输/使用标准）车间寿命表（out-of-bag，MSL2+ 按 ≤30°C/60%
  RH）：MSL1 无限 / MSL2 1 年 / MSL2a 4 周 / MSL3 168 h / MSL4 72 h /
  MSL5 48 h / MSL5a 24 h / MSL6 用前必烘（TOL）。表值为标准 verbatim；
  "1 年=8760 h、4 周=672 h" 为本模块小时换算（365/7 天自然数换算）。
- **涂覆阻隔（parylene WVTR 口径）**：涂层的防潮效果以透湿率之比参数
  化——阻隔因子 k = WVTR_bare/WVTR_coated（涂层更优 → k>1），涂层下
  有效扩散时间常数 τ_coated = k·τ_bare（透湿通量同比缩减的一阶口径）。
  WVTR 本身强依赖材料牌号/厚度/温湿度条件（parylene N/C/F 各差一个量
  级），**本模块不内嵌 WVTR 数值常量**（#118：无可达单源精确数不虚构）
  ——调用方从自家涂层数据表取值传入。

诚实边界（预声明，UNVERIFIED 清单）：
1. FR-4 等 RGB/层压板的 D（扩散系数）与 M∞（饱和吸湿率）随牌号/树脂
   含量/玻璃布样式变化数倍，公开单源典型值不足 → ``MOISTURE_PARAM_STATUS``
   按 knowledge/aging_laws.yaml 同源 provenance 政策登记 awaiting_data
   （数值字段一律缺失，不产数字）；规格书原文"FR4 85/85 Dk +5-15% 量级"
   亦标单源待实测钉（见单测示意性区间断言）。
2. 水的 εr 频变强烈（静态 ~78 → 微波频段下降），无跨频段单一权威常数
   → er_water 由调用方按工作频率给值，无缺省。
3. 级数解边界条件=双面瞬时平衡+初始均匀：单面密封/环氧-玻璃复合的
   两相扩散（Case-II 等）不在模型内；湿度滞后（吸湿/脱湿路径差异）与
   D 的浓度依赖未建模。
4. Looyenga 假设统计均匀混合、两相介电常数对比度不极端；吸湿水在聚合
   物内呈分子级分散时近似成立，微滴聚集态偏离假设（未修正项 UNKNOWN）。
5. M(t)/M∞ 级数数值域：t/τ ≳ 1e-11 量级（n_max 兜底，低于该域显式
   报错并引导走 √t 律）；t=0 恒等直返 0（物理恒等，同 glass_weave
   退化分支范式）。
6. WVTR→阻隔因子的换算是一阶通量比口径，未解涂层/基体双层扩散。

接口：全部函数返回 JSON 可序列化 float/dict/str/bool/None；单位钉在参数
名（s/m²·s⁻¹/kg·m⁻³/h）。数值 0.0 合法（判缺失一律 is not None，#364④）；
bool 显式拒收（df7+⑯）；非有限拒收。纯函数零 IO；不进 calculators 注册表
（F-C P1 域内约定，消费者是 service/humidity_drift_service.py）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: MSL 车间寿命表（小时）：JEDEC J-STD-033 车间寿命 verbatim（None=无限）；
#: 1 年=8760 h、4 周=672 h 为自然数小时换算（见模块 docstring）
MSL_FLOOR_LIFE_H: dict[str, float | None] = {
    "1": None,
    "2": 8760.0,
    "2a": 672.0,
    "3": 168.0,
    "4": 72.0,
    "5": 48.0,
    "5a": 24.0,
    "6": 0.0,
}

#: 常量来源登记（provenance 政策对齐 knowledge/aging_laws.yaml：
#: awaiting_data 条目不得携带数值字段，单测钉）
MOISTURE_PARAM_STATUS: dict[str, dict[str, str]] = {
    "msl_floor_life": {
        "status": "typical",
        "single_source": "false",
        "provenance": "JEDEC J-STD-033 车间寿命表（标准 verbatim，多源一致）",
    },
    "laminate_fr4": {
        "status": "awaiting_data",
        "reason": "FR-4 扩散系数 D 与饱和吸湿率 M∞ 随牌号/树脂含量/玻璃布样式"
        "变化数倍，无可达单源典型值——逐牌号按数据表回填",
    },
    "laminate_ro4350b": {
        "status": "awaiting_data",
        "reason": "PTFE-陶瓷碳氢体系吸湿率远低于环氧 FR-4（厂商手册只给吸湿率"
        "上限百分比），扩散系数 D 无公开单源典型值——待回填",
    },
}

#: 长短时切换守卫缺省阈值（预声明：0.05τ 内级数 vs √t 律相对差实测
#: ~1.6e-15，门 ≤2% 覆盖到 ~0.9τ——缺省取保守域，见模块 docstring）
SHORT_TIME_DOMAIN_DEFAULT = 0.05

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


# ─── Fick 扩散：特征时间 / 级数解 / 短时律 ───────────────────────────────────


def fick_tau_s(h_m: float, d_m2_per_s: float) -> float:
    """Fick 平板特征时间 τ = h²/(π²·D)（秒）。

    h_m：平板全厚（m，>0，双面吸湿口径）；d_m2_per_s：扩散系数（m²/s，>0）。
    τ 即级数 n=0 项的指数时间常数：exp(−π²·D·t/h²) = exp(−t/τ)。
    """
    h = _positive(h_m, "h_m")
    d = _positive(d_m2_per_s, "d_m2_per_s")
    return h * h / (math.pi * math.pi * d)


def fick_slab_uptake(
    t_s: float,
    d_m2_per_s: float,
    h_m: float,
    m_inf_frac: float = 1.0,
    *,
    n_max: int = 250_000,
    term_floor: float = 1e-19,
) -> float:
    """Fick 平板级数解 M(t) = M∞·[1 − (8/π²)·Σ (e^(−(2n+1)²·u)/(2n+1)²)]。

    t_s：暴露时长（s，>=0）；d_m2_per_s/h_m 同 fick_tau_s；
    m_inf_frac：饱和吸湿量 M∞（与 M 同单位，缺省 1.0=返回无纲分数）。

    恒等式：t=0 → 0.0（逐位，物理恒等直返）；t ≳ 75τ → M∞（逐位：n=0
    指数 exp(−π²·75) 已下溢为 0，级数和为 0）。数值域下限：u = t/τ·π²
    过小时（t/τ ≲ 1e-11 量级）正项级数在 n_max 内不收敛 → 显式报错并
    引导走 fick_short_time_uptake（短时域两律相对差 ~√(u/π²)·O(u) 量级，
    见模块 docstring 守卫口径）。
    """
    t = _nonneg(t_s, "t_s")
    d = _positive(d_m2_per_s, "d_m2_per_s")
    h = _positive(h_m, "h_m")
    m_inf = _nonneg(m_inf_frac, "m_inf_frac")
    if t == 0.0:
        return 0.0
    u = math.pi * math.pi * d * t / (h * h)  # = t/τ
    total = 0.0
    for n in range(n_max):
        k = 2.0 * n + 1.0
        term = math.exp(-k * k * u) / (k * k)
        if term < term_floor:
            break
        total += term
    else:
        raise ValueError(
            f"Fick 级数在 n_max={n_max} 内未收敛（t/τ≈{t / fick_tau_s(h, d):.3e} 过短），"
            "该域应改走短时 √t 律 fick_short_time_uptake"
        )
    return m_inf * (1.0 - 8.0 / (math.pi * math.pi) * total)


def fick_short_time_uptake(
    t_s: float, d_m2_per_s: float, h_m: float, m_inf_frac: float = 1.0
) -> float:
    """短时 √t 律 M(t) = M∞·(4/√π)·√(D·t/h²)（半无限早时渐近，t≪τ 有效）。

    只做渐近式本身，不钳位：t 超出短时域后返回值可 >M∞（非物理），是否
    在域内由 short_time_regime_ok 守卫/调用方先判（域内判据预声明见模块
    docstring）。t=0 → 0.0 逐位。
    """
    t = _nonneg(t_s, "t_s")
    d = _positive(d_m2_per_s, "d_m2_per_s")
    h = _positive(h_m, "h_m")
    m_inf = _nonneg(m_inf_frac, "m_inf_frac")
    return m_inf * 4.0 / math.sqrt(math.pi) * math.sqrt(d * t / (h * h))


def short_time_regime_ok(
    t_s: float, d_m2_per_s: float, h_m: float, *, t_over_tau_max: float = SHORT_TIME_DOMAIN_DEFAULT
) -> bool:
    """长短时切换守卫：t/τ ≤ t_over_tau_max（缺省 0.05，预声明域）。

    域内级数 vs √t 律相对差 ≤2%（预声明门；实测 0.05τ 处 ~1.6e-15，见模块
    docstring）。
    """
    t = _nonneg(t_s, "t_s")
    tau = fick_tau_s(h_m, d_m2_per_s)
    return t / tau <= _finite(t_over_tau_max, "t_over_tau_max")


@dataclass(frozen=True)
class FickUptakeResult:
    """吸湿轨迹单点结果（to_dict() 输出 JSON 可序列化）。"""

    t_s: float
    tau_s: float
    t_over_tau: float
    m_over_m_inf: float  # 级数路径（全域有效）
    short_time_value: float  # √t 律路径（短时域渐近）
    rel_diff: float  # 两路径相对差（以级数值为基准）
    short_time_valid: bool  # t/τ ≤ 预声明域

    def to_dict(self) -> dict[str, Any]:
        return {
            "t_s": self.t_s,
            "tau_s": self.tau_s,
            "t_over_tau": self.t_over_tau,
            "m_over_m_inf": self.m_over_m_inf,
            "short_time_value": self.short_time_value,
            "rel_diff": self.rel_diff,
            "short_time_valid": self.short_time_valid,
        }


def moisture_uptake(
    t_s: float,
    d_m2_per_s: float,
    h_m: float,
    m_inf_frac: float = 1.0,
    *,
    t_over_tau_max: float = SHORT_TIME_DOMAIN_DEFAULT,
) -> FickUptakeResult:
    """吸湿单点双路径评估：级数（主口径）+ √t 律（对拍路径，#118 独立裁判）。

    级数在极短时（t/τ ≲ 1e-11）数值域外会抛 ValueError（见
    fick_slab_uptake）——该域调用方应只消费 √t 律路径。
    """
    tau = fick_tau_s(h_m, d_m2_per_s)
    m_series = fick_slab_uptake(t_s, d_m2_per_s, h_m, m_inf_frac)
    m_short = fick_short_time_uptake(t_s, d_m2_per_s, h_m, m_inf_frac)
    rel = abs(m_short - m_series) / m_series if m_series != 0.0 else 0.0
    return FickUptakeResult(
        t_s=float(t_s),
        tau_s=tau,
        t_over_tau=float(t_s) / tau,
        m_over_m_inf=m_series,
        short_time_value=m_short,
        rel_diff=rel,
        short_time_valid=short_time_regime_ok(
            t_s, d_m2_per_s, h_m, t_over_tau_max=t_over_tau_max
        ),
    )


# ─── 混合介质三式 + 吸湿 εr(M) ───────────────────────────────────────────────


def looyenga_mix(er_matrix: float, er_inclusion: float, v_inclusion: float) -> float:
    """Looyenga ε^(1/3) 加权混合：ε^(1/3) = (1−v)·ε_m^(1/3) + v·ε_i^(1/3)。

    v_inclusion：夹杂（吸湿水）体积分数 ∈ [0,1]。端点恒等式逐位直返：
    v=0 → ε_m、v=1 → ε_i（退化物理恒等分支，同 glass_weave 范式——立方
    往返浮点不保逐位，端点分支使恒等式严格成立）。
    """
    em = _positive(er_matrix, "er_matrix")
    ei = _positive(er_inclusion, "er_inclusion")
    v = _finite(v_inclusion, "v_inclusion")
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"v_inclusion 必须 ∈ [0,1]，实际 {v}")
    if v == 0.0:
        return em
    if v == 1.0:
        return ei
    return (
        (1.0 - v) * em ** (1.0 / 3.0) + v * ei ** (1.0 / 3.0)
    ) ** 3


def maxwell_garnett_mix(er_matrix: float, er_inclusion: float, v_inclusion: float) -> float:
    """Maxwell-Garnett（球夹杂、基质 ε_m 相）：
    ε_eff = ε_m·[ε_i+2ε_m+2v(ε_i−ε_m)]/[ε_i+2ε_m−v(ε_i−ε_m)]。

    对照口径（主口径钉 Looyenga，见模块 docstring）；端点逐位直返。
    """
    em = _positive(er_matrix, "er_matrix")
    ei = _positive(er_inclusion, "er_inclusion")
    v = _finite(v_inclusion, "v_inclusion")
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"v_inclusion 必须 ∈ [0,1]，实际 {v}")
    if v == 0.0:
        return em
    if v == 1.0:
        return ei
    num = (ei + 2.0 * em) + 2.0 * v * (ei - em)
    den = (ei + 2.0 * em) - v * (ei - em)
    return em * num / den


def bruggeman_mix(er_phase_a: float, er_phase_b: float, v_phase_a: float) -> float:
    """Bruggeman 对称有效介质：v(a−x)/(a+2x) + (1−v)(b−x)/(b+2x) = 0。

    闭式正根（消元得 2x²−x·c−ab=0，c = 3v(a−b)+2b−a，判别式 c²+8ab>0）：
    x = [c + √(c²+8ab)]/4。两相对称（v ↔ 1−v 换相对称恒等式，单测钉
    rel=1e-12——闭式两种展开 1-ulp 级差）。端点逐位直返。
    """
    a = _positive(er_phase_a, "er_phase_a")
    b = _positive(er_phase_b, "er_phase_b")
    v = _finite(v_phase_a, "v_phase_a")
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"v_phase_a 必须 ∈ [0,1]，实际 {v}")
    if v == 0.0:
        return b
    if v == 1.0:
        return a
    c = 3.0 * v * (a - b) + 2.0 * b - a
    return (c + math.sqrt(c * c + 8.0 * a * b)) / 4.0


_MIX_RULES = {
    # 统一 (matrix, inclusion, v_inclusion) 语义——bruggeman 签名是
    # (phase_a, phase_b, v_phase_a)，此处换序使 v 恒指夹杂（水）相分数
    "looyenga": looyenga_mix,
    "maxwell_garnett": maxwell_garnett_mix,
    "bruggeman": lambda em, ei, v: bruggeman_mix(ei, em, v),
}


def water_volume_fraction(moisture_frac: float, rho_dry: float, rho_water: float = 1000.0) -> float:
    """吸湿质量分数 M → 水体积分数 v = M·ρ_dry/ρ_water。

    moisture_frac：吸水质量/干材质量（无量纲，>=0）；rho_dry：干材密度
    （kg/m³，>0）；rho_water：水密度（kg/m³，>0，缺省 1000）。v>1 非物理
    （水量超过基体体积）显式报错。
    """
    m = _nonneg(moisture_frac, "moisture_frac")
    rd = _positive(rho_dry, "rho_dry")
    rw = _positive(rho_water, "rho_water")
    v = m * rd / rw
    if v > 1.0:
        raise ValueError(f"水体积分数 {v} >1 非物理（moisture_frac×ρ_dry/ρ_water）")
    return v


@dataclass(frozen=True)
class MoistureEpsilonResult:
    """吸湿 εr 漂移结果（to_dict() 输出 JSON 可序列化）。"""

    moisture_frac: float
    water_volume_fraction: float
    er_dry: float
    er: float
    drift_frac: float
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "moisture_frac": self.moisture_frac,
            "water_volume_fraction": self.water_volume_fraction,
            "er_dry": self.er_dry,
            "er": self.er,
            "drift_frac": self.drift_frac,
            "rule": self.rule,
        }


def epsilon_moisture_shift(
    moisture_frac: float,
    er_dry: float,
    rho_dry: float,
    er_water: float,
    rho_water: float = 1000.0,
    rule: str = "looyenga",
) -> MoistureEpsilonResult:
    """端到端吸湿 εr(M)：M → 体积分数 → 混合三式之一 → εr(M) 与漂移分数。

    moisture_frac ≥0；er_dry/er_water/rho_dry/rho_water >0（er_water 无
    缺省——频变强烈，调用方按工作频率给值，见模块 docstring UNVERIFIED②）；
    rule ∈ {looyenga, maxwell_garnett, bruggeman}（主口径 looyenga）。
    M=0 → er_dry 逐位（水体积分数 0 → 混合端点恒等分支）。
    """
    if rule not in _MIX_RULES:
        raise ValueError(f"未知混合规则 {rule!r}，可选 {sorted(_MIX_RULES)}")
    m = _nonneg(moisture_frac, "moisture_frac")
    erd = _positive(er_dry, "er_dry")
    erw = _positive(er_water, "er_water")
    v = water_volume_fraction(m, rho_dry, rho_water)
    er = _MIX_RULES[rule](erd, erw, v)
    return MoistureEpsilonResult(
        moisture_frac=m,
        water_volume_fraction=v,
        er_dry=erd,
        er=er,
        drift_frac=er / erd - 1.0,
        rule=rule,
    )


# ─── 涂覆阻隔（parylene WVTR 口径）───────────────────────────────────────────


def coating_barrier_factor(wvtr_coated: float, wvtr_bare: float) -> float:
    """涂层阻隔因子 k = WVTR_bare/WVTR_coated（涂层更优 → k>1）。

    wvtr_*：透湿率（g·m⁻²·day⁻¹ 等任意一致单位，>0）。等 WVTR → 1.0
    逐位（IEEE-754 非零有限 x/x≡1）。WVTR 数值由调用方从涂层数据表取值
    （本模块不内嵌，见模块 docstring）。
    """
    wc = _positive(wvtr_coated, "wvtr_coated")
    wb = _positive(wvtr_bare, "wvtr_bare")
    return wb / wc


def coated_tau_s(tau_bare_s: float, barrier_factor: float) -> float:
    """涂层下有效特征时间 τ_coated = τ_bare·k（一阶通量比口径，k>=1 物理
    期待；k<1 = "涂层加速吸湿"非物理但不拦——由调用方核对数据表方向）。"""
    tau = _positive(tau_bare_s, "tau_bare_s")
    k = _positive(barrier_factor, "barrier_factor")
    return tau * k


# ─── MSL floor-life（JEDEC J-STD-033）────────────────────────────────────────


def msl_floor_life_hours(msl: str) -> float | None:
    """MSL 等级 → 车间寿命小时（J-STD-033 表 verbatim；None=无限，MSL1）。

    msl ∈ {"1","2","2a","3","4","5","5a","6"}；未知等级显式报错。
    """
    if not isinstance(msl, str) or msl not in MSL_FLOOR_LIFE_H:
        raise ValueError(f"未知 MSL 等级 {msl!r}，可选 {sorted(MSL_FLOOR_LIFE_H)}")
    return MSL_FLOOR_LIFE_H[msl]


def msl_floor_life_expired(msl: str, exposure_h: float) -> bool:
    """车间寿命是否耗尽：exposure_h 超过该 MSL 车间寿命（恰等=未超）。

    MSL1 → 恒 False；MSL6（用前必烘）→ exposure_h>0 即 True（0.0 合法
    =未开封未暴露，#364④ 数值 0.0 语义）。
    """
    exp_h = _nonneg(exposure_h, "exposure_h")
    floor = msl_floor_life_hours(msl)
    if floor is None:
        return False
    return exp_h > floor
