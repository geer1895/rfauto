"""F-C.1 器件老化漂移内核（PoF 时间轴）：三律 + Miner + 任务剖面积分。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- Arrhenius 加速因子 AF = exp[(Ea/k)(1/T_use − 1/T_stress)]：NASA SMA
  PoF 方法文（Physics-of-Failure 可靠性评估）+ JEDEC JESD47G 工作例
  （Ea=0.7 eV、125°C 应力 vs 55°C 使用，行业标准缺省）。k =
  8.617333262e-5 eV/K（CODATA 2018 精确定义 k_B=1.380649e-23 J/K 与
  e=1.602176634e-19 C 之商（CODATA 公布 10 位舍入值，相对精确商差 ~1.7e-11），两者均为 SI 精确值）。AF>1 应力温度高于
  使用温度（加速）；AF<1 反之；Ea=0 或两温相等 → AF=1。
- Black 方程 MTTF = A·J⁻ⁿ·exp(Ea/kT)：J.R. Black, IEEE Trans. Electron
  Devices (1969) 电迁移经验律；Ohring《Reliability and Failure of
  Electronic Materials and Devices》教科书口径。时间单位由常数 A 吸收
  （A 标定为 h·(J 单位)ⁿ 则 MTTF 返回小时）；J 密度单位（A/cm² 或
  A/m²）同样由 A 的标定吸收，模块不做单位换算。
- Coffin-Manson 律 N_f = C·ΔT⁻q：L.F. Coffin (1954) / S.S. Manson
  (1965) 热循环疲劳律；IPC-9701 焊点热循环疲劳实践口径。C 单位 =
  循环数·K^q；ΔT 取往复全摆幅（K）。Engelmaier 修正与 Weibull 统计
  见本文件后段（F-H r4-插① 增量）。
- Miner（Palmgren-Miner）线性累积损伤 D = Σ nᵢ/N_fᵢ：M.A. Miner
  (1945)；D≥1 判失效。Python `reliability` 库 PoF.palmgren_miner_
  linear_damage 同式（对照裁判，LGPLv3，不进 pyproject 依赖，单测
  importorskip 如实 skip）。
- εr 老化律 er(t) = er0·(1 + k_log·log10(t/t0))：Class-2 铁电陶瓷
  （BaTiO₃ 基）log-时间老化口径，Knowles/Syfer 电容器应用笔记与器件
  手册族（X7R 典型 −1%/decade-hour；老化在超过居里点回火后重置）。
  t0 = 1 h 参考量（per-decade-hour 惯例）；k_log 即
  aging_frac_per_decade（分数/decade，负值=εr 随时间下降），来源由
  knowledge/aging_laws.yaml 带出处供给。

任务剖面积分（profile_integrate）：mission_profile 分段恒定应力，
各通道私有损伤并行累积——热激活通道（εr 老化）用 Arrhenius AF 把
应力段折算到使用温度的等效时间；电迁移（Black）与热循环（Coffin-
Manson）各自按段内应力独立累积 Miner 损伤；v1 多机理独立叠加、耦合
项标 UNKNOWN（F-C §4 风险②），本模块不产出认证级寿命结论——漂移
上界工具，非寿命预测器。

接口：全部函数返回 JSON 可序列化 float/dict（float/str/bool/None），
单位显式钉在参数名（K/°C、s/h）。例外：Weibull 统计节 ndarray 进出
（向量化），JSON 序列化由调用方负责。数值 0.0 合法（判缺失一律 is not
None，#364④）。纯算法零 IO；不进 calculators 注册表（F-C P1 域内
约定，消费者是 P2 的 service 层）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# Boltzmann 常数（eV/K）：CODATA 2018 两个 SI 精确定义值之商
K_B_EV_PER_K = 8.617333262e-5
# 1 eV 对应的开尔文温度（K/eV），独立常数便于双路径核对
INV_K_K_PER_EV = 1.0 / K_B_EV_PER_K

# 等效时间 → 小时换算（profile_integrate 内部口径，er 老化律 per-decade-hour）
_S_PER_H = 3600.0
# t_total_s 一致性守卫的相对容差
_TOTAL_TOL = 1e-9

# aging_laws.yaml 状态枚举（与 knowledge/aging_laws.yaml 头注一致）
LAW_STATUS_TYPICAL = "typical"
LAW_STATUS_AWAITING_DATA = "awaiting_data"


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


# ─── 三律闭式 ────────────────────────────────────────────────────────────────


def arrhenius_af(ea_ev: float, t_use_k: float, t_stress_k: float) -> float:
    """Arrhenius 加速因子 AF = exp[(Ea/k)(1/T_use − 1/T_stress)]。

    ea_ev：激活能（eV，>=0）；t_use_k / t_stress_k：使用/应力温度（K，>0）。
    恒等式：T_stress == T_use 或 Ea == 0 时 AF == 1.0（逐位）。
    """
    ea = _nonneg(ea_ev, "ea_ev")
    tu = _positive(t_use_k, "t_use_k")
    ts = _positive(t_stress_k, "t_stress_k")
    return math.exp((ea / K_B_EV_PER_K) * (1.0 / tu - 1.0 / ts))


def black_mttf(a: float, j_density: float, n: float, ea_ev: float, t_k: float) -> float:
    """Black 电迁移方程 MTTF = A·J⁻ⁿ·exp(Ea/kT)。

    a：前置常数（时间单位由 A 吸收，A 标定为 h·(J 单位)^n 则返回小时）；
    j_density：电流密度（单位与 A 的标定一致，如 A/cm²，>0）；
    n：电流密度指数（典型 1-2，>=0）；ea_ev：激活能（eV，>=0）；
    t_k：绝对温度（K，>0）。
    """
    a_ = _positive(a, "a")
    j = _positive(j_density, "j_density")
    n_ = _nonneg(n, "n")
    ea = _nonneg(ea_ev, "ea_ev")
    t = _positive(t_k, "t_k")
    out: float = a_ * j ** (-n_) * math.exp(ea / (K_B_EV_PER_K * t))
    return out


def coffin_manson(c: float, delta_t_k: float, q: float) -> float:
    """Coffin-Manson 热循环疲劳律 N_f = C·ΔT⁻q（失效循环数）。

    c：疲劳常数（循环数·K^q，>0）；delta_t_k：温度摆幅（K，>0，0 摆幅
    无损伤，调用方应先筛 0 再调用）；q：指数（焊点典型 ~2，>=0）。
    """
    c_ = _positive(c, "c")
    dt = _positive(delta_t_k, "delta_t_k")
    q_ = _nonneg(q, "q")
    out: float = c_ * dt ** (-q_)
    return out


# ─── 损伤累积与 εr 老化律 ────────────────────────────────────────────────────


def miner_accumulate(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Miner（Palmgren-Miner）线性累积损伤 D = Σ nᵢ/N_fᵢ。

    segments = [{"n_cycles": 实际循环数（>=0）, "n_f": 该应力水平失效
    循环数（>0）}, ...]。返回 {"damage": D, "failed": D >= 1.0}。
    线性累积满足交换律——分段次序交换 D 不变（物理恒等式，单测钉）。
    """
    total = 0.0
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise ValueError(f"segments[{idx}] 必须为 dict")
        n_cycles = _nonneg(seg["n_cycles"], f"segments[{idx}].n_cycles")
        n_f = _positive(seg["n_f"], f"segments[{idx}].n_f")
        total += n_cycles / n_f
    return {"damage": total, "failed": total >= 1.0}


def er_aging_drift(
    er0: float, aging_frac_per_decade: float, t_equivalent_h: float, t_ref_h: float = 1.0
) -> dict[str, float]:
    """Class-2 陶瓷 εr log-时间老化律 er(t) = er0·(1 + k_log·log10(t/t0))。

    er0：参考时刻 εr（>0）；aging_frac_per_decade：每 decade 的 εr 相对
    老化分数（负值=衰减；来自 knowledge/aging_laws.yaml）；t_equivalent_h：
    等效老化时间（小时，>0）；t_ref_h：参考时间 t0（小时，>0，缺省 1 h
    = Knowles per-decade-hour 惯例）。返回 {"er", "drift_frac", "decades"}。
    t == t0 时 er == er0（逐位）。t < t0 为外推区（er 高于 er0），调用方
    自行决定是否钳位到重置时刻。
    """
    er0_ = _positive(er0, "er0")
    k_log = _finite(aging_frac_per_decade, "aging_frac_per_decade")
    t = _positive(t_equivalent_h, "t_equivalent_h")
    t0 = _positive(t_ref_h, "t_ref_h")
    decades = math.log10(t / t0)
    er = er0_ * (1.0 + k_log * decades)
    return {
        "er": er,
        "drift_frac": er / er0_ - 1.0,
        "decades": decades,
    }


# ─── 任务剖面积分 ────────────────────────────────────────────────────────────

_LAWS_REQUIRED = ("t_use_c", "ea_ev", "er0", "aging_frac_per_decade")
_LAWS_BLACK = ("a_black", "n_black", "ea_ev_black")
_LAWS_CM = ("c_cm", "q_cm", "cycle_period_s")


def profile_integrate(
    mission_profile: list[dict[str, Any]], laws: dict[str, Any], t_total_s: float | None = None
) -> dict[str, Any]:
    """任务剖面逐步积分：分段恒定应力 → 三通道并行损伤累积 + εr 漂移轨迹。

    mission_profile = [{"t_s": 段时长（秒，>0）, "t_c": 段温度（°C）,
    "j_density": 电流密度（可选）, "delta_t_c": 热循环摆幅（K，可选，
    取 |ΔT|）}, ...]。可选通道字段键**缺失**=该段不计该通道（None 语义）；
    数值 0.0 合法（有字段但无应力 → 该通道该段零损伤，#364④）。

    laws 必填：{t_use_c（使用温度 °C）, ea_ev（热激活 Ea eV）, er0,
    aging_frac_per_decade}；通道可选：{a_black, n_black, ea_ev_black,
    black_time_unit_s（MTTF 输出单位对应秒数，缺省 3600=小时）} 与
    {c_cm, q_cm, cycle_period_s（单循环时长秒）}——剖面出现对应应力字段
    而 laws 缺该通道参数即显式报错（fail-fast，不静默跳通道）。

    t_total_s：可选总时长一致性校验（与 Σt_s 相对偏差超 1e-9 即报错）。

    返回（JSON 可序列化）：
    {"t_total_s", "t_equivalent_s"（Arrhenius 折算到使用温度的等效时间）,
     "t_equivalent_h", "damage": {"electromigration": float|None,
     "thermal_cycling": float|None}, "failed"（任一非 None 损伤 >=1）,
     "drift": {"er0", "aging_frac_per_decade", "t_ref_h", "er_eol",
     "drift_frac"}, "trajectory": [{"t0_s", "t1_s", "t_eq_cum_s", "er_t",
     "damage_em_cum", "damage_cm_cum"}, ...]}。

    多机理独立叠加（v1，耦合项 UNKNOWN）；AF 折算只作用于热激活通道
    （εr 老化），Black/Coffin-Manson 按段内真实应力各自累积。
    """
    for key in _LAWS_REQUIRED:
        if laws.get(key) is None:
            raise ValueError(f"laws 缺必填参数 {key}")
    t_use_c = _finite(laws["t_use_c"], "laws.t_use_c")
    ea_ev = _nonneg(laws["ea_ev"], "laws.ea_ev")
    er0 = _positive(laws["er0"], "laws.er0")
    frac = _finite(laws["aging_frac_per_decade"], "laws.aging_frac_per_decade")
    t_use_k = t_use_c + 273.15

    if not mission_profile:
        raise ValueError("mission_profile 不能为空")
    total_s = 0.0
    for idx, seg in enumerate(mission_profile):
        if not isinstance(seg, dict):
            raise ValueError(f"mission_profile[{idx}] 必须为 dict")
        if seg.get("t_s") is None:
            raise ValueError(f"mission_profile[{idx}] 缺 t_s")
        total_s += _positive(seg["t_s"], f"mission_profile[{idx}].t_s")
        if seg.get("t_c") is None:
            raise ValueError(f"mission_profile[{idx}] 缺 t_c")
        _finite(seg["t_c"], f"mission_profile[{idx}].t_c")
    if t_total_s is not None and abs(total_s - float(t_total_s)) > _TOTAL_TOL * max(
        1.0, abs(float(t_total_s))
    ):
        raise ValueError(
            f"t_total_s={t_total_s} 与剖面时长和 Σt_s={total_s} 不一致（相对容差 {_TOTAL_TOL}）"
        )

    need_black = any(seg.get("j_density") is not None for seg in mission_profile)
    need_cm = any(seg.get("delta_t_c") is not None for seg in mission_profile)
    if need_black:
        for key in _LAWS_BLACK:
            if laws.get(key) is None:
                raise ValueError(f"剖面含 j_density 但 laws 缺电迁移参数 {key}")
        btu = laws.get("black_time_unit_s")
        btu = _S_PER_H if btu is None else btu  # 键在值 None 同缺省（审查轨 A P2-3：None 须 ValueError 非 TypeError）
        black_time_unit_s = _positive(btu, "laws.black_time_unit_s")
    if need_cm:
        for key in _LAWS_CM:
            if laws.get(key) is None:
                raise ValueError(f"剖面含 delta_t_c 但 laws 缺热循环参数 {key}")

    t_eq_cum_s = 0.0
    em_cum: float | None = None
    cm_cum: float | None = None
    trajectory: list[dict[str, Any]] = []
    for idx, seg in enumerate(mission_profile):
        t0_s = 0.0 if not trajectory else trajectory[-1]["t1_s"]
        t_seg_s = _positive(seg["t_s"], f"mission_profile[{idx}].t_s")
        t_k = _finite(seg["t_c"], f"mission_profile[{idx}].t_c") + 273.15
        af = arrhenius_af(ea_ev, t_use_k, t_k)
        t_eq_cum_s += t_seg_s * af

        j_density = seg.get("j_density")
        if j_density is not None:
            j_val = _nonneg(j_density, f"mission_profile[{idx}].j_density")
            d_em = 0.0 if j_val == 0.0 else t_seg_s / (
                black_mttf(laws["a_black"], j_val, laws["n_black"], laws["ea_ev_black"], t_k)
                * black_time_unit_s
            )
            em_cum = d_em if em_cum is None else em_cum + d_em

        delta_t_c = seg.get("delta_t_c")
        if delta_t_c is not None:
            dt_val = abs(_finite(delta_t_c, f"mission_profile[{idx}].delta_t_c"))
            d_cm = (
                0.0
                if dt_val == 0.0
                else (t_seg_s / _positive(laws["cycle_period_s"], "laws.cycle_period_s"))
                / coffin_manson(laws["c_cm"], dt_val, laws["q_cm"])
            )
            cm_cum = d_cm if cm_cum is None else cm_cum + d_cm

        er_t = er_aging_drift(er0, frac, t_eq_cum_s / _S_PER_H)["er"]
        trajectory.append(
            {
                "t0_s": t0_s,
                "t1_s": t0_s + t_seg_s,
                "t_eq_cum_s": t_eq_cum_s,
                "er_t": er_t,
                "damage_em_cum": em_cum,
                "damage_cm_cum": cm_cum,
            }
        )

    er_eol = er_aging_drift(er0, frac, t_eq_cum_s / _S_PER_H)
    failed = (em_cum is not None and em_cum >= 1.0) or (cm_cum is not None and cm_cum >= 1.0)
    return {
        "t_total_s": total_s,
        "t_equivalent_s": t_eq_cum_s,
        "t_equivalent_h": t_eq_cum_s / _S_PER_H,
        "damage": {"electromigration": em_cum, "thermal_cycling": cm_cum},
        "failed": failed,
        "drift": {
            "er0": er0,
            "aging_frac_per_decade": frac,
            "t_ref_h": 1.0,
            "er_eol": er_eol["er"],
            "drift_frac": er_eol["drift_frac"],
        },
        "trajectory": trajectory,
    }


# ─── Engelmaier 蠕变-疲劳修正与 Weibull 统计（F-H 件 1，r4 插①）─────────────
#
# 口径来源（原文可达、已逐位核对——非转述口径）：
# - W. Engelmaier《Solder Joints in Electronics: Design for Reliability》
#   （analysistech.com/wp-content/uploads/2016/04/SolderJointDesignFor
#   Reliability.pdf）Eq.3/Eq.4/Eq.5/Eq.9；
# - Wikipedia "Solder fatigue" Engelmaier 节（引 Engelmaier 1983, IEEE
#   Trans. CHMT-6(3):232-237）同式互证；Hillman（electronics.org 文库）
#   ln(1+f)、f=360/t_D 频率折算互证。
# Pb-free（SAC305）修正不内嵌数值（#118：无可达单源精确数不虚构）——
# 合金差异经 eps_f_prime 等参数显式传参完成（Blattau/Hillman "An
# Engelmaier Model for Leadless Ceramic Chip Devices with Pb-free
# Solder" 修正路线，Coyle 2015/Mi 2014 综述线索）。

# Engelmaier 疲劳延性指数 c 的常数（原文 Eq.4 逐位）
ENGELMAIER_C0 = -0.442  # 温度无关项
ENGELMAIER_C_TEMP = -6.0e-4  # 平均循环焊点温度系数（1/°C）
ENGELMAIER_C_DWELL = 1.74e-2  # 驻留项系数（乘 ln(1+360/t_D)）
ENGELMAIER_DWELL_NORM = 360.0  # 驻留归一常数（min；≈每日循环数 f 的经验折算）
# 疲劳延性系数 ε_f′ 缺省：共晶/60-40 SnPb（原文 verbatim "0.325"；常被
# 误引的 0.65 是复合量 2ε_f′——本模块参数取 ε_f′ 本义，分母显式写 2ε_f′）
ENGELMAIER_EPS_F_SNPB = 0.325


def engelmaier_c_index(t_mean_c: float, t_dwell_min: float) -> float:
    """Engelmaier 疲劳延性指数 c（平均温度/驻留时间相关）。

    c = −0.442 − 6e−4·T_SJ + 1.74e−2·ln(1 + 360/t_D)（原文 Eq.4 逐位）

    t_mean_c：平均循环焊点温度 T_SJ（°C）；t_dwell_min：半循环驻留时间
    t_D（min，>0）。360/t_D 即每日循环数 f 的经验折算（原文口径）——
    驻留越长应力松弛/蠕变越充分 → c 越负 → 同应变下 N_f 越低。

    适用域警示（原文 Caveat 3）：t_D < 1 min 量级（振动/快速温变域，
    应力松弛非主导机制）本式不适用，调用方应改走 Coffin-Manson 等律；
    本函数不拦 t_D<1（只拦非正），适用域判断留给调用方（同 arrhenius_af
    只算不判的域内约定）。
    """
    t = _finite(t_mean_c, "t_mean_c")
    td = _positive(t_dwell_min, "t_dwell_min")
    return (
        ENGELMAIER_C0
        + ENGELMAIER_C_TEMP * t
        + ENGELMAIER_C_DWELL * math.log(1.0 + ENGELMAIER_DWELL_NORM / td)
    )


def engelmaier_cycles(
    t_mean_c: float,
    t_dwell_min: float,
    delta_gamma_eff: float,
    eps_f_prime: float = ENGELMAIER_EPS_F_SNPB,
) -> float:
    """Engelmaier-Wild 中位疲劳寿命 N_50 = 0.5·(Δγ_eff/(2ε_f′))^(1/c)。

    原文 Eq.3 逐位（N_f(50%) = (1/2)·[ΔD/(2ε_f′)]^(1/c)；c 为负指数，
    故 1/c<0：应变比 <1 时 c 越负 N_50 越低）。eps_f_prime：疲劳延性
    系数 ε_f′，缺省 0.325 = 共晶/60-40 SnPb（原文 verbatim）；SAC305
    等无铅合金修正经显式传参（修正路线见本节头注，本内核不内嵌未核实
    数值）。delta_gamma_eff：循环总剪切应变范围（>0）——热失配分量
    （thermal_mismatch_shear_strain）与机械/弯曲分量按原文 §3.6 口径
    直接相加。
    """
    dg = _positive(delta_gamma_eff, "delta_gamma_eff")
    eps = _positive(eps_f_prime, "eps_f_prime")
    c = engelmaier_c_index(t_mean_c, t_dwell_min)
    out: float = 0.5 * (dg / (2.0 * eps)) ** (1.0 / c)
    return out


def thermal_mismatch_shear_strain(
    delta_t_c: float,
    alpha_1_ppm: float,
    alpha_2_ppm: float,
    die_seal_loop_mm: float,
    joint_height_mm: float,
    d_factor: float = 1.0,
) -> float:
    """热失配总剪切应变范围 Δγ = D·Δα·ΔT·L/h（原文 Eq.5 的 leadless 简化）。

    Δα = |α1−α2|（ppm/°C，符号取绝对值——失配幅度只看差值大小）；
    ΔT = 循环温度全摆幅（°C，>=0，0 摆幅 → 0 应变合法，#364④）；
    L = die_seal_loop_mm 密封环/最远焊点 DNP 距离（mm，>=0）；h =
    joint_height_mm 焊点高度（mm，>0）；ppm 按 1e-6 折算成无量纲应变。

    d_factor：经验非理想因子（原文 Eq.5 记 F，逐位口径）：球/柱类无引
    脚互连 1.0-1.5、带圆角无引脚（castellated/chip）0.7-1.2、柔性引线
    ≈1（原文 verbatim）。缺省 1.0 = 理想刚体位移全摆幅口径。
    """
    dt = _nonneg(delta_t_c, "delta_t_c")
    a1 = _finite(alpha_1_ppm, "alpha_1_ppm")
    a2 = _finite(alpha_2_ppm, "alpha_2_ppm")
    loop = _nonneg(die_seal_loop_mm, "die_seal_loop_mm")
    h = _positive(joint_height_mm, "joint_height_mm")
    d = _positive(d_factor, "d_factor")
    return d * abs(a1 - a2) * 1e-6 * dt * loop / h


def _prob_vector(value: object, name: str) -> np.ndarray:
    """失效概率向量收敛：有限且落在 [0,1)（p=1 → N→∞ 非有限，拒绝）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    arr = np.asarray(value, dtype=float)
    if arr.size == 0:
        return arr
    if (
        not bool(np.all(np.isfinite(arr)))
        or float(np.min(arr)) < 0.0
        or float(np.max(arr)) >= 1.0
    ):
        raise ValueError(f"{name} 必须为 [0,1) 内的有限数")
    return arr


def _cycles_vector(value: object, name: str) -> np.ndarray:
    """循环数向量收敛：有限且 >=0。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    arr = np.asarray(value, dtype=float)
    if arr.size == 0:
        return arr
    if not bool(np.all(np.isfinite(arr))) or float(np.min(arr)) < 0.0:
        raise ValueError(f"{name} 必须为 >=0 的有限数")
    return arr


def weibull_life(eta: float, beta: float, p: np.ndarray) -> np.ndarray:
    """2 参数 Weibull 反演 N = η·(−ln(1−p))^(1/β)（失效概率 → 寿命）。

    eta：特征寿命（P_f=63.2% 处，>0）；beta：形状参数 β（>0）；p：失效
    概率（[0,1)，ndarray 进出）。β 经验提示（原文 §3.7 verbatim）：疲劳
    试验典型 b≈3；低加速试验硬无引脚互连 b≈4、柔性引线互连 b≈2；观测
    域 1.8-10（强加速使斜率更陡）——焊料 ATC 实践 β≈2-5 量级。p=0 →
    N=0（逐位）。
    """
    eta_ = _positive(eta, "eta")
    b = _positive(beta, "beta")
    arr = _prob_vector(p, "p")
    out: np.ndarray = eta_ * (-np.log1p(-arr)) ** (1.0 / b)
    return out


def weibull_p_of_failure(eta: float, beta: float, n: np.ndarray) -> np.ndarray:
    """2 参数 Weibull 失效概率 P_f(N) = 1 − exp(−(N/η)^β)。

    eta/beta 同 weibull_life；n：循环数（>=0，ndarray 进出）。N=0 →
    P_f=0（逐位）；N=η → P_f = 1−1/e（逐位恒等）。
    """
    eta_ = _positive(eta, "eta")
    b = _positive(beta, "beta")
    arr = _cycles_vector(n, "n")
    return -np.expm1(-((arr / eta_) ** b))


def n50_from_weibull(eta: float, beta: float) -> float:
    """Weibull 参数 → 中位寿命 N_50 = η·(ln2)^(1/β)（P_f(N_50)=0.5 定义恒等式）。"""
    eta_ = _positive(eta, "eta")
    b = _positive(beta, "beta")
    out: float = eta_ * math.log(2.0) ** (1.0 / b)
    return out


def weibull_from_n50(n50: float, beta: float) -> float:
    """中位寿命 → Weibull 特征寿命 η = N_50/(ln2)^(1/β)（n50_from_weibull 逆）。"""
    n = _positive(n50, "n50")
    b = _positive(beta, "beta")
    out: float = n / math.log(2.0) ** (1.0 / b)
    return out


def compound_miner(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """复合载荷多通道 Miner：各应力通道独立累积后求和 D_total。

    segments = [{"channels": [chan, ...]}, ...]。chan 支持两种形态
    （单条 chan 只允许其一；同名通道跨段自动合并累积，未命名通道按
    "seg{i}_ch{k}" 自动编址，i/k 为段/通道下标）：
      A. {"n_cycles": 实际循环数（>=0）, "n_f": 失效循环数（>0）}——
         循环应力通道，逐条复用 miner_accumulate 语义（禁重复实现分叉）；
      B. {"damage": 直接损伤量（>=0）}——调用方已折算的损伤贡献
         （如电迁移 em_damage_rate×dwell_hours：速率×时长）。

    返回 {"damage_channels": {通道名: 该通道累积损伤}, "damage":
    D_total, "failed": D_total >= 1.0}。空输入 → D=0 不失效（与
    miner_accumulate 空表口径一致）。通道间损伤独立叠加、机理耦合项
    UNKNOWN（v1 同 profile_integrate 口径）。
    """
    channel_order: list[str] = []
    channel_parts: dict[str, list[dict[str, Any]]] = {}
    channel_direct: dict[str, float] = {}
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise ValueError(f"segments[{i}] 必须为 dict")
        channels = seg.get("channels")
        if not isinstance(channels, list):
            raise ValueError(f"segments[{i}] 缺 channels 列表")
        for k, chan in enumerate(channels):
            if not isinstance(chan, dict):
                raise ValueError(f"segments[{i}].channels[{k}] 必须为 dict")
            name = chan.get("name")
            if name is None:
                name = f"seg{i}_ch{k}"
            elif not isinstance(name, str):
                raise ValueError(f"segments[{i}].channels[{k}].name 必须为 str")
            if name not in channel_order:
                channel_order.append(name)
                channel_parts[name] = []
                channel_direct[name] = 0.0
            has_cycles = chan.get("n_cycles") is not None or chan.get("n_f") is not None
            has_damage = chan.get("damage") is not None
            if has_cycles and has_damage:
                raise ValueError(
                    f"segments[{i}].channels[{k}] 不得同时给 n_cycles/n_f 与 damage"
                )
            if has_damage:
                label = f"segments[{i}].channels[{k}].damage"
                channel_direct[name] += _nonneg(chan["damage"], label)
            elif has_cycles:
                if chan.get("n_cycles") is None or chan.get("n_f") is None:
                    raise ValueError(
                        f"segments[{i}].channels[{k}] 循环形态必须同时给 n_cycles 与 n_f"
                    )
                channel_parts[name].append(
                    {
                        "n_cycles": _nonneg(
                            chan["n_cycles"], f"segments[{i}].channels[{k}].n_cycles"
                        ),
                        "n_f": _positive(chan["n_f"], f"segments[{i}].channels[{k}].n_f"),
                    }
                )
            else:
                raise ValueError(
                    f"segments[{i}].channels[{k}] 缺损伤字段（n_cycles/n_f 或 damage）"
                )

    damage_channels: dict[str, float] = {}
    total = 0.0
    for name in channel_order:
        d = miner_accumulate(channel_parts[name])["damage"] if channel_parts[name] else 0.0
        d += channel_direct[name]
        damage_channels[name] = d
        total += d
    return {"damage_channels": damage_channels, "damage": total, "failed": total >= 1.0}
