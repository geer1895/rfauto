"""F-E 件 3：Y 因子噪声测量内核（T_e / NF / ENR + GUM 不确定度闭式）。

口径与公式来源（铁律 5：来源写 docstring；裁判=独立来源，不自证，#118）：

- Keysight（Agilent）AN 57-2《Fundamentals of RF and Microwave Noise
  Figure Measurements》（5952-0255E）：Y 因子法全部口径——
  Y = P_hot/P_cold（线性功率比）；T_e = (T_hot − Y·T_cold)/(Y − 1)；
  T_cold = T0 时 F = ENR_lin/(Y − 1)（第二路径，AN 57-2 原文式）；
  NF 不确定度主导项 ∂NF/∂ENR、∂NF/∂Y。原文 PDF 已于调研批核对
  （研究扩充 round3 F-E 表件 3："5952-0255.pdf
  已核"）。
- IEEE 噪声温度基准 T0 = 290 K；NF_dB = 10·log10(1 + T_e/T0)。与
  core/budget.py 的 Friis 正向级联同口径（budget=设计正向合成，本模块
  =测量反演+不确定度；F_linear ↔ NF_dB 换算式相同，T0 一致）。
- ENR 定义 ENR_lin = (T_hot − T_cold)/T0（T_cold=源物理温度，常取
  290/295 K，参数显式）；ENR_dB = 10·log10(ENR_lin)。
- 源端损耗修正按 Friis 逐级口径：损耗 L（线性，>=1，物理温度 T0）串入
  DUT 之前，系统等效输入温度（参考损耗上游平面）
  T_e,sys = L·T_e,DUT + (L−1)·T0；反演（从含损耗表观值去嵌 DUT 本征值）
  T_e,DUT = (T_e,apparent − (L−1)·T0)/L。独立对照路径：F_sys = L·F_DUT
  （损耗在 T0 的 Friis 代数，单测钉）。
- Y 的测量不确定度（两次独立功率测量，线性域方差传播 RSS）：
  σ_Y²/Y² = σ_Ph²/Ph² + σ_Pc²/Pc²。
- GUM 传播律（JCGM 100:2008）：u_c² = Σ(∂f/∂xᵢ)²·uᵢ²。温度参数化偏导
  闭式（一般 T_cold）：
      ∂F/∂Y = (T_cold − T_hot)/(T0·(Y−1)²)
      ∂F/∂T_hot = 1/(T0·(Y−1))
      ∂F/∂T_cold = −Y/(T0·(Y−1))
  ENR 参数化（T_cold=T0 契约，AN 57-2 主导项）：∂F/∂ENR = 1/(Y−1)、
  ∂F/∂Y = −ENR_lin/(Y−1)²；dB 域分解恒等式
  NF_dB = ENR_dB − 10·log10(Y−1)（T_cold=T0，故 ∂NF/∂ENR_dB = 1 精确）。
- 蒙特卡洛对照（JCGM 101 思想）：固定 seed 抽样 ±u 输入，输出分布 std
  对照闭式 u_c——预声明阈值 rel <= 0.10（一阶泰勒域；有效样本占比
  <99% 即判 u 相对奇点距离过大，如实拒绝不硬算）。

边界语义（预声明，#122）：Y < 1 物理不可达（T_hot > T_cold 且 T_e >= 0
时 Y 恒 >1）→ ValueError；Y = 1 发散 → 返回 ±inf 合法（分子符号定号；
分子分母同零 0/0 不定 → ValueError）；T_e < 0 = 测量与 ENR 不自洽
（Y 相对 ENR 过大），照实返回不拦（只算不判，调用方决定，同
aging.arrhenius_af 域内约定）。

接口：纯函数零 IO；返回 JSON 可序列化 float/dict/dataclass（to_dict）；
单位显式钉在参数名（K/dB/linear）；判缺失一律 is not None（#364④），
数值 0.0 合法；bool 显式拒收（df7+⑯）。本件 core-only，不进 calculators
注册表（F-E 表件 3 约定，service 接线另批——既有
service/nf_measurement_service.py 是远场服务，与本模块无关，勿混）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# IEEE 噪声温度基准（K）：AN 57-2 / IEEE 口径；与 budget.py 的 NF 换算同口径
T0_K = 290.0

# 10/ln10 ≈ 4.342945：无量纲比值 ↔ dB 的斜率换算常数（dB = (10/ln10)·ln(x)）
_DB_PER_LOGE = 10.0 / math.log(10.0)


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
    """把入参收敛为有限非负 float，非法即显式报错（0.0 合法，#364④）。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


def _int_arg(value: float, name: str, minimum: int) -> int:
    """整数参数收敛：bool 拒收、非整值拒绝、下限校验。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool")
    out = float(value)
    if not math.isfinite(out) or out != int(out):
        raise ValueError(f"{name} 必须为整数")
    iv = int(out)
    if iv < minimum:
        raise ValueError(f"{name} 必须 >={minimum}")
    return iv


def _loss(value: float, name: str) -> float:
    """损耗收敛：线性 L >= 1（<1 是增益，不在本口径）。"""
    out = _positive(value, name)
    if out < 1.0:
        raise ValueError(f"{name} 必须 >=1（损耗；<1 为增益不在本口径）")
    return out


# ─── 定义式：ENR 与 Y ────────────────────────────────────────────────────────


def enr_linear(t_hot_k: float, t_cold_k: float, t0_k: float = T0_K) -> float:
    """噪声源超噪比（线性）ENR = (T_hot − T_cold)/T0。

    t_hot_k/t_cold_k：噪声源热/冷态等效输出噪声温度（K，均 >0，且
    t_hot > t_cold——ENR 为正的定义域）；t0_k：IEEE 基准（K，缺省 290）。
    AN 57-2 定义口径，T_cold 为源物理温度（常取 290/295 K，显式传参）。
    """
    th = _positive(t_hot_k, "t_hot_k")
    tc = _positive(t_cold_k, "t_cold_k")
    t0 = _positive(t0_k, "t0_k")
    if th <= tc:
        raise ValueError(f"t_hot_k ({th}) 必须大于 t_cold_k ({tc})（ENR 为正的定义域）")
    return (th - tc) / t0


def enr_db(t_hot_k: float, t_cold_k: float, t0_k: float = T0_K) -> float:
    """噪声源超噪比 ENR_dB = 10·log10((T_hot − T_cold)/T0)（AN 57-2 定义）。"""
    return 10.0 * math.log10(enr_linear(t_hot_k, t_cold_k, t0_k))


def y_factor(p_hot: float, p_cold: float) -> float:
    """Y 因子 Y = P_hot/P_cold（线性功率比，同单位即可，无量纲）。

    本层只做定义式（比值 >0 即合法）；Y 的物理可达域校验在 te_from_y
    （Y<1 → ValueError，预声明）。
    """
    ph = _positive(p_hot, "p_hot")
    pc = _positive(p_cold, "p_cold")
    return ph / pc


# ─── 反演主路径：Y → T_e → F/NF ──────────────────────────────────────────────


def te_from_y(y: float, t_hot_k: float, t_cold_k: float) -> float:
    """路径 A（一般 T_cold）：T_e = (T_hot − Y·T_cold)/(Y − 1)（K）。

    AN 57-2 Y 因子法：Y = (T_hot+T_e)/(T_cold+T_e) 反解。
    边界（预声明）：y < 1 → ValueError（物理不可达）；y == 1 → 按
    分子（T_hot − T_cold）符号返回 ±inf（发散极限合法），分子分母同零
    → ValueError（0/0 不定）；T_e < 0 照实返回（测量与 ENR 不自洽的
    标志，只算不判）。
    """
    y_ = _positive(y, "y")
    th = _positive(t_hot_k, "t_hot_k")
    tc = _positive(t_cold_k, "t_cold_k")
    if y_ < 1.0:
        raise ValueError(f"y={y_} < 1 物理不可达（T_hot>T_cold 且 T_e>=0 时 Y 恒 >1）")
    num = th - y_ * tc
    if y_ == 1.0:
        if num > 0.0:
            return math.inf
        if num < 0.0:
            return -math.inf
        raise ValueError("y=1 且 T_hot=T_cold：(Y−1) 与分子同零，0/0 不定")
    return num / (y_ - 1.0)


def f_from_enr_y(enr_lin: float, y: float) -> float:
    """路径 B（AN 57-2 原文式，T_cold = T0 契约）：F = ENR_lin/(Y − 1)。

    仅当冷态温度等于 IEEE 基准 T0=290 K 时与路径 A 精确一致（单测钉
    rel 1e-12）；T_cold ≠ T0 时用 te_from_y 一般式。enr_lin：ENR 线性值
    （>0）；边界同 te_from_y（y<1 → ValueError，y=1 → +inf）。
    """
    e = _positive(enr_lin, "enr_lin")
    y_ = _positive(y, "y")
    if y_ < 1.0:
        raise ValueError(f"y={y_} < 1 物理不可达（T_hot>T_cold 且 T_e>=0 时 Y 恒 >1）")
    if y_ == 1.0:
        return math.inf
    return e / (y_ - 1.0)


def nf_from_te(t_e_k: float, t0_k: float = T0_K) -> float:
    """等效输入噪声温度 → 噪声系数 NF_dB = 10·log10(1 + T_e/T0)（IEEE）。

    t_e_k：等效输入噪声温度（K，> −T0）；t_e_k = 0 → NF = 0 dB（逐位）。
    t0_k 缺省 290 K，与 core/budget.py 的 F↔NF 换算同口径。
    """
    te = _finite(t_e_k, "t_e_k")
    t0 = _positive(t0_k, "t0_k")
    if te <= -t0:
        raise ValueError(f"t_e_k ({te}) 必须 > −t0_k（F = 1+T_e/T0 > 0 的定义域）")
    return 10.0 * math.log10(1.0 + te / t0)


def te_from_nf(nf_db: float, t0_k: float = T0_K) -> float:
    """噪声系数 → 等效输入噪声温度 T_e = T0·(10^(NF/10) − 1)（K）。

    nf_from_te 的代数逆（往返恒等式单测钉）。NF 以 dB 计（任意实数，
    负 dB 对应负 T_e 的不自洽标志，照实返回）。
    """
    nf = _finite(nf_db, "nf_db")
    t0 = _positive(t0_k, "t0_k")
    return t0 * (10.0 ** (nf / 10.0) - 1.0)


def y_from_te(t_e_k: float, t_hot_k: float, t_cold_k: float) -> float:
    """合成正向（测量仿真）：Y = (T_hot + T_e)/(T_cold + T_e)。

    te_from_y 的代数逆，用于合成回收判据（注入已知 DUT T_e 产 Y，再
    反演回收）。要求 T_hot+T_e > 0 且 T_cold+T_e > 0（噪声功率为正）。
    """
    te = _finite(t_e_k, "t_e_k")
    th = _positive(t_hot_k, "t_hot_k")
    tc = _positive(t_cold_k, "t_cold_k")
    if th + te <= 0.0 or tc + te <= 0.0:
        raise ValueError("T_hot+T_e 与 T_cold+T_e 必须为正（噪声功率为正）")
    return (th + te) / (tc + te)


# ─── 源端损耗修正（Friis 逐级口径）───────────────────────────────────────────


def apply_input_loss(t_e_k: float, loss_lin: float, t0_k: float = T0_K) -> float:
    """Friis 正向：DUT 前串损耗 L 后，系统等效输入温度（参考损耗上游）。

    T_e,sys = L·T_e,DUT + (L−1)·T0（损耗物理温度取 T0）。t_e_k：DUT 自身
    等效输入温度（参考 DUT 输入端口，K）；loss_lin：线性损耗（>=1）。
    独立对照路径：F_sys = L·F_DUT（损耗在 T0 的 Friis 代数，单测钉）。
    """
    te = _finite(t_e_k, "t_e_k")
    loss = _loss(loss_lin, "loss_lin")
    t0 = _positive(t0_k, "t0_k")
    return loss * te + (loss - 1.0) * t0


def remove_input_loss(t_e_referred_k: float, loss_lin: float, t0_k: float = T0_K) -> float:
    """Friis 反演（apply_input_loss 的代数逆）：从含损耗表观值去嵌 DUT 本征值。

    T_e,DUT = (T_e,apparent − (L−1)·T0)/L。t_e_referred_k：Y 因子实测的
    表观等效输入温度（参考损耗上游平面，K）；loss_lin：DUT 之前已知
    线性损耗（>=1）。往返恒等式单测钉 rel 1e-12。
    """
    te = _finite(t_e_referred_k, "t_e_referred_k")
    loss = _loss(loss_lin, "loss_lin")
    t0 = _positive(t0_k, "t0_k")
    return (te - (loss - 1.0) * t0) / loss


# ─── 不确定度：Y 的测量不确定度 + GUM 传播 + MC 对照 ─────────────────────────


def y_uncertainty(p_hot: float, p_cold: float, u_p_hot: float, u_p_cold: float) -> float:
    """Y 的测量不确定度（两次独立功率测量，线性域方差传播 RSS）。

    σ_Y/Y = sqrt((σ_Ph/Ph)² + (σ_Pc/Pc)²)。p_hot/p_cold：线性功率（同
    单位，>0）；u_p_hot/u_p_cold：对应功率测量标准不确定度（同单位，
    >=0，0.0 合法）。返回 σ_Y（无量纲，1σ）。
    """
    ph = _positive(p_hot, "p_hot")
    pc = _positive(p_cold, "p_cold")
    uh = _nonneg(u_p_hot, "u_p_hot")
    uc = _nonneg(u_p_cold, "u_p_cold")
    y = ph / pc
    return y * math.sqrt((uh / ph) ** 2 + (uc / pc) ** 2)


def nf_uncertainty_gum(
    y: float,
    t_hot_k: float,
    t_cold_k: float,
    u_y: float,
    u_t_hot_k: float,
    u_t_cold_k: float,
    t0_k: float = T0_K,
) -> dict[str, float]:
    """NF 不确定度 GUM 传播（温度参数化，一般 T_cold，JCGM 100:2008）。

    F(y, Th, Tc) = 1 + (Th − y·Tc)/(T0·(y−1))，偏导闭式：
        ∂F/∂y = (Tc − Th)/(T0·(y−1)²)，∂F/∂Th = 1/(T0·(y−1))，
        ∂F/∂Tc = −y/(T0·(y−1))；
    u_c² = Σ(∂F/∂xᵢ)²·uᵢ²，dB 域 u_NF = (10/(ln10·F))·u_F。

    y 必须 >1（Y=1 奇点处不确定度无定义）；u_* 均 >=0（0.0 合法）；
    ENR 不确定度按 δENR = δT_hot/T0 折入 u_t_hot_k（固定 T_cold）。
    返回 dict（F、u_F、u_NF_dB 与 F/dB 两域偏导，全部 JSON 可序列化）。
    """
    y_ = _positive(y, "y")
    if y_ <= 1.0:
        raise ValueError(f"y 必须 >1（Y=1 奇点处不确定度无定义，收到 {y_}）")
    th = _positive(t_hot_k, "t_hot_k")
    tc = _positive(t_cold_k, "t_cold_k")
    uy = _nonneg(u_y, "u_y")
    uth = _nonneg(u_t_hot_k, "u_t_hot_k")
    utc = _nonneg(u_t_cold_k, "u_t_cold_k")
    t0 = _positive(t0_k, "t0_k")

    den = y_ - 1.0
    f = 1.0 + (th - y_ * tc) / (t0 * den)
    if not f > 0.0:
        raise ValueError(f"F = {f} <= 0（测量与 ENR 不自洽超出 NF 定义域，dB 换算无定义）")
    s_y = (tc - th) / (t0 * den * den)
    s_th = 1.0 / (t0 * den)
    s_tc = -y_ / (t0 * den)
    u_f = math.sqrt((s_y * uy) ** 2 + (s_th * uth) ** 2 + (s_tc * utc) ** 2)
    scale = _DB_PER_LOGE / f
    return {
        "f_linear": f,
        "u_f_linear": u_f,
        "u_nf_db": scale * u_f,
        "sensitivity_df_dy": s_y,
        "sensitivity_df_dt_hot": s_th,
        "sensitivity_df_dt_cold": s_tc,
        "sensitivity_dnf_dy_db": scale * s_y,
        "sensitivity_dnf_dt_hot_db": scale * s_th,
        "sensitivity_dnf_dt_cold_db": scale * s_tc,
    }


def nf_uncertainty_gum_enr(
    enr_lin: float, y: float, u_enr_lin: float, u_y: float
) -> dict[str, float]:
    """NF 不确定度 GUM 传播（ENR 参数化，AN 57-2 主导项，T_cold=T0 契约）。

    F = ENR_lin/(y−1)：∂F/∂ENR = 1/(y−1)，∂F/∂y = −ENR_lin/(y−1)²。
    T_cold ≠ T0 时此参数化是近似，一般情形用 nf_uncertainty_gum
    （温度参数化，两参数化在 T_cold=T0 且 u 折算一致时逐位相等，单测钉）。
    enr_lin/u_enr_lin：ENR 线性值与其标准不确定度（>0 / >=0）；
    dB 域换算 ENR_lin = 10^(ENR_dB/10) 时 u_enr_lin = ENR_lin·ln10/10·u_ENR_dB。
    """
    e = _positive(enr_lin, "enr_lin")
    y_ = _positive(y, "y")
    if y_ <= 1.0:
        raise ValueError(f"y 必须 >1（Y=1 奇点处不确定度无定义，收到 {y_}）")
    ue = _nonneg(u_enr_lin, "u_enr_lin")
    uy = _nonneg(u_y, "u_y")

    den = y_ - 1.0
    f = e / den
    s_y = -e / (den * den)
    s_e = 1.0 / den
    u_f = math.sqrt((s_e * ue) ** 2 + (s_y * uy) ** 2)
    scale = _DB_PER_LOGE / f
    return {
        "f_linear": f,
        "u_f_linear": u_f,
        "u_nf_db": scale * u_f,
        "sensitivity_df_denr": s_e,
        "sensitivity_df_dy": s_y,
        "sensitivity_dnf_denr_db": scale * s_e,
        "sensitivity_dnf_dy_db": scale * s_y,
    }


def mc_nf_std(
    y: float,
    t_hot_k: float,
    t_cold_k: float,
    u_y: float,
    u_t_hot_k: float,
    u_t_cold_k: float,
    t0_k: float = T0_K,
    n_samples: int = 10000,
    seed: int = 20260927,
) -> dict[str, float]:
    """蒙特卡洛对照裁判：抽样 ±u 输入，返回 NF 输出分布 std（dB，1σ）。

    JCGM 101 思想：固定 seed（numpy default_rng）独立正态抽样
    (y, T_hot, T_cold)，逐样本走 te_from_y → NF 链（向量化），std(ddof=1)
    对照 GUM 闭式 u_nf_db——预声明阈值 rel <= 0.10（一阶泰勒域）。
    有效样本（y>1 且 F>0）占比 <99% → ValueError（u 相对奇点距离过大，
    一阶域不成立，如实拒绝不硬算）。n_samples >=2；seed >=0 整数。
    """
    y_ = _positive(y, "y")
    if y_ <= 1.0:
        raise ValueError(f"y 必须 >1（Y=1 奇点处不确定度无定义，收到 {y_}）")
    th = _positive(t_hot_k, "t_hot_k")
    tc = _positive(t_cold_k, "t_cold_k")
    uy = _nonneg(u_y, "u_y")
    uth = _nonneg(u_t_hot_k, "u_t_hot_k")
    utc = _nonneg(u_t_cold_k, "u_t_cold_k")
    t0 = _positive(t0_k, "t0_k")
    n = _int_arg(n_samples, "n_samples", 2)
    sd = _int_arg(seed, "seed", 0)

    rng = np.random.default_rng(sd)
    y_s = rng.normal(y_, uy, n)
    th_s = rng.normal(th, uth, n)
    tc_s = rng.normal(tc, utc, n)

    mask = y_s > 1.0
    te = np.full(n, np.nan)
    te[mask] = (th_s[mask] - y_s[mask] * tc_s[mask]) / (y_s[mask] - 1.0)
    f_s = 1.0 + te / t0
    ok = mask & np.isfinite(f_s) & (f_s > 0.0)
    nf_s = np.full(n, np.nan)
    nf_s[ok] = 10.0 * np.log10(f_s[ok])

    n_valid = int(ok.sum())
    if n_valid < 0.99 * n:
        raise ValueError(
            f"有效样本占比 {n_valid / n:.3f} < 0.99：输入 u 相对 Y=1 奇点/F=0 过大，"
            "一阶泰勒域不成立（GUM 与 MC 皆无意义）"
        )
    return {
        "std_nf_db": float(np.std(nf_s[ok], ddof=1)),
        "n_valid": float(n_valid),
        "n_samples": float(n),
    }


# ─── 端到端单次测量评估 ──────────────────────────────────────────────────────


@dataclass
class YFactorResult:
    """Y 因子单次测量端到端评估结果（全部字段 JSON 可序列化）。

    f_enr_path：路径 B（F = ENR/(Y−1)）仅在 t_cold_k == t0_k 时适用，
    否则 None（#364④ 判缺失 is not None 口径）。input_loss_lin 给定时
    t_e_corrected_k / nf_corrected_db 为 Friis 正向折算
    （apply_input_loss：L·T_e + (L−1)·T0，任务口径）。
    """

    y_linear: float
    t_hot_k: float
    t_cold_k: float
    t0_k: float
    enr_linear: float
    enr_db: float
    t_e_k: float
    f_linear: float
    nf_db: float
    f_enr_path: float | None = None
    input_loss_lin: float | None = None
    t_e_corrected_k: float | None = None
    nf_corrected_db: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        """JSON 可序列化扁平字典（全精度 float，不做显示舍入）。"""
        return {
            "y_linear": self.y_linear,
            "t_hot_k": self.t_hot_k,
            "t_cold_k": self.t_cold_k,
            "t0_k": self.t0_k,
            "enr_linear": self.enr_linear,
            "enr_db": self.enr_db,
            "t_e_k": self.t_e_k,
            "f_linear": self.f_linear,
            "nf_db": self.nf_db,
            "f_enr_path": self.f_enr_path,
            "input_loss_lin": self.input_loss_lin,
            "t_e_corrected_k": self.t_e_corrected_k,
            "nf_corrected_db": self.nf_corrected_db,
        }


def measure_yfactor(
    p_hot: float,
    p_cold: float,
    t_hot_k: float,
    t_cold_k: float,
    t0_k: float = T0_K,
    input_loss_lin: float | None = None,
) -> YFactorResult:
    """单次 Y 因子测量端到端评估（Y → T_e → F/NF → ENR → 可选损耗折算）。

    p_hot/p_cold：热/冷态输出噪声功率（线性，同单位）；t_hot_k/t_cold_k：
    噪声源热/冷态温度（K）；input_loss_lin：可选，DUT 前已知线性损耗
    （>=1），给定时按任务口径把测得 DUT T_e 正向折算到损耗上游参考面
    （t_e_corrected_k = L·T_e + (L−1)·T0；反向去嵌用 remove_input_loss）。

    发散测量（y==1）在端到端层拒绝（T_e 无界，极限语义请直接消费
    te_from_y / f_from_enr_y 的 inf 返回）；T_cold == T0 时附路径 B
    f_enr_path（双路径对照，#118）。
    """
    y = y_factor(p_hot, p_cold)
    th = _positive(t_hot_k, "t_hot_k")
    tc = _positive(t_cold_k, "t_cold_k")
    t0 = _positive(t0_k, "t0_k")

    te = te_from_y(y, th, tc)
    if not math.isfinite(te):
        raise ValueError(f"T_e = {te} 非有限（y={y} 发散测量），端到端评估要求有限 T_e")
    f = 1.0 + te / t0
    nf = nf_from_te(te, t0)
    e_lin = enr_linear(th, tc, t0)

    f_enr_path: float | None = None
    if tc == t0:
        f_enr_path = f_from_enr_y(e_lin, y)

    loss: float | None = None
    te_corr: float | None = None
    nf_corr: float | None = None
    if input_loss_lin is not None:
        loss = _loss(input_loss_lin, "input_loss_lin")
        te_corr = apply_input_loss(te, loss, t0)
        nf_corr = nf_from_te(te_corr, t0)

    return YFactorResult(
        y_linear=y,
        t_hot_k=th,
        t_cold_k=tc,
        t0_k=t0,
        enr_linear=e_lin,
        enr_db=10.0 * math.log10(e_lin),
        t_e_k=te,
        f_linear=f,
        nf_db=nf,
        f_enr_path=f_enr_path,
        input_loss_lin=loss,
        t_e_corrected_k=te_corr,
        nf_corrected_db=nf_corr,
    )
