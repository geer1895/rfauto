"""DOA Cramér-Rao 下界族（aurora_d W3-CORE6 席 R7_core_tier2 "doa 余量
=CRB（零命中）"补口，2026-10-14；W3-CORE8 席多源续作+本席 W3-CORE9
随机（stochastic）CRB 收口原位扩展同日）。

三键：doa_crb_ula（均匀线阵单源 DOA 估计的确定性 Cramér-Rao 下界——
阵元数/快拍数/SNR/间隔/来波角 → CRB 方差/标准差弧度与度）/
doa_crb_ula_multisource（M 源确定性 CRB 通用式——FIM 矩阵构造+求逆，
对角元→各源 CRB；单源退化=doa_crb_ula 逐位一致）/ doa_crb_stochastic
（随机（高斯）信号模型 CRB——Stoica-Nehorai 1989 两模型对照的随机半
边，celebrated 闭式+精确 Slepian-Bangs 全参数 Schur 双面并列）。

边界防撞（R7 §② G20 行 "doa 余量=CRB" 三重搜索证据沿用）
------------------------------------------------
doa.py（aurora36 W5-A）=MUSIC/ESPRIT/MVDR **估计器**面（伪谱/角回收/
波束权重）；本族只做其**性能下界**面（CRB——估计器精度的理论裁判，
P_MUSIC 峰位、ESPRIT 角误差对 CRB 的贴近度评价消费面）。mimo.py=
虚拟阵/容量、array_synth.py=幅度综合、butler_matrix.py=馈电网格——
均不并入。多源确定性 CRB 与随机 CRB 分别由 CORE8/本席收口（此前
"如实登记不硬造"的随机 CRB 缺口闭合）。

物理口径（docstring 写死，#1c/#300/#118 出处纪律）
----------------------------------------------
ULA 窄带远场（侧射角 θ=0 指阵列法向，与 doa.py 同约定），导向矢量
a(θ)_m = exp(j·2π(d/λ)sinθ·m)（m=0..N−1）。

1. **单源确定性 CRB**（Stoica & Nehorai 1989 模式；Van Trees, Optimum
Array Processing ch.8 单源式）：

    Var(θ̂) ≥ CRB(θ) = σ²/(2·Σ_t|s_t|²) · 1/(d'ᴴ·P_a^⊥·d')

    d' = da/dθ = j·(2π d/λ)cosθ·diag(m)·a，  P_a^⊥ = I − a·aᴴ/N

投影二次型对 ULA 有闭式（Σm=N(N−1)/2、Σm²=N(N−1)(2N−1)/6 代入）：

    d'ᴴ·P_a^⊥·d' = (2π d/λ)²·cos²θ·N(N²−1)/12

即本键实现式（SNR=P/σ² 线性，θ 弧度口径 → CRB 单位 rad²）::

    CRB(θ) = 12 / ( 2·T·SNR·N·(N²−1)·(2π·d/λ)²·cos²θ )

标度律（物理锚）：CRB ∝ 1/T（快拍数）、∝ 1/SNR、∝ 1/cos²θ（端fire
发散=物理，本键 |θ|<90° 开区间显式拒绝恰值）、∝ 1/N³（渐近，
精确因子 N(N²−1)/12）。d/λ>1/2 有栅瓣风险（与 doa.py 同口径：
(0,1] 物理合法、>1/2 如实 note 不拒绝）。

2. **多源确定性 CRB（通用式，FIM 矩阵求逆）**：模型
x_t = A(θ)s_t + n_t（A=[a(θ₁)..a(θ_M)] N×M、s_t 确定性未知、
n_t~CN(0,σ²I)），θ 块 Fisher 信息矩阵经 s（与 σ²）冗余参数 Schur
消元后的闭式（Stoica & Nehorai 1989 确定性 CRB 通用形态；Viberg &
Ottersten 1991 同式）::

    FIM(θ) = 2T·Re[ (Dᴴ P_A^⊥ D) ⊙ P̄ᵀ ]，  CRB(θ) = FIM⁻¹ 对角元

    D = [∂a/∂θ₁ .. ∂a/∂θ_M]，  P_A^⊥ = I − A(AᴴA)⁻¹Aᴴ（正交投影，
    秩 N−M ≥ 1 → N>M 硬前提），  P̄ = (1/T)Σ_t s_t s_tᴴ（确定性样本
    协方差；对角元=各源阵元级 SNR=p_i/σ²，σ² 在 SNR 归一下消去）

输入面：P̄ = √snr·R·√snr，R = 等相关阵（对角 1、非对角 corr_coef ρ，
正定域 ρ∈[0,1)）。**源间耦合两面**（实测锚定）：① ρ=0（不相关）时
⊙P̄ᵀ 将 FIM 非对角**恒零化**→各源解耦、CRB_i=1/(2T·p_i·Re[G_ii])；
② 但 Re[G_ii] 用**全 A 子空间投影**（含他源导向矢量），故 CRB_i 仍
≥ 单源闭式值（未知波形干扰的子空间代价，罚因子>1，M=1 才退化相等
——与单源键逐位一致的回归钉即此边界）；③ ρ→1（全相关/相干）FIM
奇异，正定守卫显式拒绝。

3. **随机（stochastic）CRB（W3-CORE9 收口）**：模型同上但
s_t~CN(0,Q) i.i.d. 高斯（边缘化后 x_t~CN(0,R)，R=AQAᴴ+σ²I）。
**celebrated 闭式**（Stoica & Nehorai 1989 两模型对照的随机半边；
Ottersten-Stoica-Söderström 1993 同形态）::

    CRB_sc(θ) = (σ²/2T)·{ Re[ (Dᴴ P_A^⊥ D) ⊙ (Q Aᴴ R⁻¹ A Q)ᵀ ] }⁻¹

σ² 经 SNR 归一消去（q_i=p_i/σ²、σ²=1 口径，θ-CRB 对 σ² 尺度不变）。
**精确性边界（实测锚定，#122 如实）**：闭式=精确高斯 FIM 下界的充要
前提是 **Q 与 σ² 作未知冗余参数全 Schur 消元**（实测 ρ=0/0.3/0.5/0.8、
等/不等 SNR 全域 rel≤7.5e-15）；Q 或 σ² 已知（不消元）时两者系统性
偏离（实测 up to 71%@ρ=0.8 不等 SNR——冗余参数消元不可省）。本键把
闭式与精确 Slepian-Bangs 面并列输出（crb_var_rad2=celebrated 闭式主
口径 + sb_exact_crb_var_rad2=精确 Slepian-Bangs（σ²、Q 全 Schur 消
元）+ closed_vs_exact_max_rel 偏差），两面全域恰等即内建 #118 第二
路线（互证面）。
**单源退化与 deterministic 键关系（Stoica-Nehorai 对照主题）**：
M=1 时 CRB_sc=(1+pN)/(2T·p²·N·G)=CRB_det·(1+1/(pN))——随机模型恒
不低于确定性模型（未知信号统计的代价），高 SNR 渐近相等（比值
1+1/(pN)→1）；且 ULA（m=0 相位约定）下 FIM_θ,σ²=FIM_θ,Q=0 精确
（Re[aᴴR⁻¹d]=0，α=aᴴd 纯虚）——单源随机 CRB 对 σ²/Q 是否已知不敏
感（实测逐位）。G=(2πd/λ)²cos²θ·N(N²−1)/12 与确定性键同源。

出处（#118 双路径：闭式 + 数值第二路线互证）
----------------------------------------------
来源：Stoica & Nehorai, "MUSIC, maximum likelihood, and Cramér-Rao
bound", IEEE Trans. ASSP 37(5):720-741, 1989（确定性/随机性 CRB 二分
与通用 FIM 形态，章节级转引，式号不落键面）；Van Trees, *Optimum
Array Processing*, Wiley 2002, ch.8（单源 CRB 口径，章节级转引）；
Viberg & Ottersten, "Sensor array processing based on subspace
fitting", IEEE Trans. SP 39(5):1110-1121, 1991（多源确定性 CRB 同式
形态，章节级转引）；Ottersten, Stoica & Söderström, "On statistical
properties of subspace fitting estimators"（随机 CRB 形态，章节级转
引）；投影二次型 ULA 闭式（Σm/Σm² 代入）与多源 FIM Schur 消元推导
=本仓代数推导（实现前独立复算（内部验证档）：单源随机闭式=Slepian-Bangs 数值 FIM（σ² 已知/未知两口径）逐位
+比值恒等式 1+1/(pN)；celebrated 闭式对角 Q 全参数 Schur rel≤2.0e-15、
非对角 Q 偏差实测 ~2%（如实并列）；Schiffman/开关网络两键同轨迹），
锚树 tests/unit/test_aurora_d_core9.py 第二路线（naive N×N Slepian-
Bangs 全参数 FIM 独立重算+Schur 消元+退化回归钉）。

守卫（三键同口径+随机键沿用多源域）：n_elements 整数 ≥2（N=1 →
N²−1=0 CRB 发散显式拒绝）；snapshots 整数 ≥1；snr_db 有限实数（线性
化 10^(snr_db/10)）；spacing_lambda∈(0,1]；angle_deg∈(−90°,90°) 开区
间（端fire 恰值 cosθ=0 → CRB 发散显式拒绝）。多源/随机新增：
n_sources=len(angles_deg)∈[1,16]；n_elements>N_sources（P⊥ 秩 N−M≥1
硬前提，N≤M 显式拒绝）；各角开区间+两两异角（重合/近重合 <1e-9° 显
式拒绝——A 奇异）；snr_db 标量广播或逐源列表（长度=M，全有限）；
corr_coef∈[0,1)（=1 全相关 FIM 奇异显式拒绝）；FIM 正定守卫
（celebrated 与 Slepian-Bangs 两面各自特征值≤0 或条件数>1e14 → 显
式拒绝指回异角/降 ρ）；越界一律显式拒绝。输出 std=sqrt(CRB)，度换
算 ×180/π；JSON 面 NaN/Inf 禁入（守卫后域内恒有限）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .registry import register_calculator
from .thermal import _finite

_SOURCES = {
    "crb": (
        "单源确定性 CRB：Stoica & Nehorai, \"MUSIC, maximum likelihood, "
        "and Cramér-Rao bound\", IEEE Trans. ASSP 37(5):720-741, 1989"
        "（确定性/随机 CRB 二分，章节级转引，式号不落键面）；Van Trees, "
        "Optimum Array Processing, Wiley 2002, ch.8（单源 ULA 口径，章节"
        "级转引）；投影二次型 ULA 闭式 N(N²−1)/12=本仓 Σm/Σm² 代数推导"
        "（数值投影器第二路线互证）"),
    "crb_multi": (
        "多源确定性 CRB 通用式：Stoica & Nehorai, \"MUSIC, maximum "
        "likelihood, and Cramér-Rao bound\", IEEE Trans. ASSP 37(5):"
        "720-741, 1989（确定性 CRB 通用 FIM 形态，章节级转引，式号不落"
        "键面）；Viberg & Ottersten, \"Sensor array processing based on "
        "subspace fitting\", IEEE Trans. SP 39(5):1110-1121, 1991（同式"
        "形态，章节级转引）；FIM=2T·Re[(DᴴP⊥D)⊙P̄ᵀ] Schur 消元=本仓代数"
        "推导（全参数 FIM 数值消元第二路线 rel≤1.0e-15，M=1 退化=单源"
        "闭式逐位）"),
    "crb_stoch": (
        "随机（高斯）信号 CRB：Stoica & Nehorai, \"MUSIC, maximum "
        "likelihood, and Cramér-Rao bound\", IEEE Trans. ASSP 37(5):"
        "720-741, 1989（确定性/随机 CRB 两模型对照——celebrated 闭式 "
        "CRB=(σ²/2T){Re[(DᴴP⊥D)⊙(QAᴴR⁻¹AQ)ᵀ]}⁻¹，章节级转引，式号不落"
        "键面）；Ottersten, Stoica & Söderström（随机 CRB 同形态，章节"
        "级转引）；Slepian-Bangs 复高斯 FIM=Tr[R⁻¹R'_i R⁻¹R'_j]（实参数"
        "Hermitian 口径）；精确性前提（Q、σ² 全 Schur 消元，全域 rel≤"
        "7.5e-15 实测）与单源比值恒等式 1+1/(pN)=本仓代数推导（Slepian-"
        "Bangs 全参数 Schur 数值第二路线，独立验证档）"),
}

#: 多源键 n_sources 上限（FIM 面与 JSON 体积守卫）
_N_SOURCES_MAX = 16

#: FIM 条件数上限（近奇异显式拒绝：异角/降 ρ 指回）
_FIM_COND_MAX = 1e14


def _crb_ula_closed(n: int, n_snap: int, snr_lin: float, k: float,
                    theta_rad: float) -> float:
    """单源 ULA CRB 闭式（单源/多源两键共享单源；算子序=CORE6 原文，
    既有输出逐位不变）。"""
    return 12.0 / (2.0 * n_snap * snr_lin * n * (n * n - 1)
                   * (k * k) * math.cos(theta_rad) ** 2)


@register_calculator(
    "doa_crb_ula",
    "DOA 单源 CRB 下界：ULA 确定性 Cramér-Rao 下界 CRB(θ)=12/(2·T·SNR·"
    "N(N²−1)·(2π·d/λ)²·cos²θ)——阵元数/快拍数/SNR/间隔/来波角 → 方差 rad²、"
    "标准差 rad/deg、Fisher 信息；闭式∝1/T·1/SNR·1/cos²θ·1/N³(渐近)；"
    "端fire θ=±90° 与 N=1 显式拒绝（发散）；MUSIC/ESPRIT 估计精度裁判面"
    "（估计器本体走 doa_* 键不并入）",
    (("n_elements", "int 阵元数 N（整数 ≥2）"),
     ("snapshots", "int 快拍数 T（整数 ≥1）"),
     ("snr_db", "float dB 单源阵元级 SNR（有限实数）"),
     ("spacing_lambda", "float 阵元间隔 d/λ（∈(0,1]；>1/2 栅瓣风险如实 "
      "note）"),
     ("angle_deg", "float° 来波角（侧射=0°；开区间 (−90,90)）")),
    required=("n_elements", "snapshots", "snr_db", "spacing_lambda",
              "angle_deg"),
)
def doa_crb_ula(
    n_elements: int,
    snapshots: int,
    snr_db: float,
    spacing_lambda: float,
    angle_deg: float,
) -> dict[str, Any]:
    """单源 ULA 确定性 CRB：闭式标量面（方差/标准差/Fisher 信息）。"""
    if isinstance(n_elements, bool):
        raise ValueError(
            f"doa_crb_ula: n_elements 须为整数，得到 bool {n_elements!r}")
    n_f = _finite(n_elements, "n_elements")
    if n_f != int(n_f):
        raise ValueError(
            f"doa_crb_ula: n_elements 须为整数，得到 {n_elements!r}")
    n = int(n_f)
    if n < 2:
        raise ValueError(
            f"doa_crb_ula: n_elements 必须 ≥2（N=1 → N²−1=0 CRB 发散），"
            f"得到 {n_elements!r}")
    if isinstance(snapshots, bool):
        raise ValueError(
            f"doa_crb_ula: snapshots 须为整数，得到 bool {snapshots!r}")
    t_f = _finite(snapshots, "snapshots")
    if t_f != int(t_f):
        raise ValueError(
            f"doa_crb_ula: snapshots 须为整数，得到 {snapshots!r}")
    n_snap = int(t_f)
    if n_snap < 1:
        raise ValueError(
            f"doa_crb_ula: snapshots 必须 ≥1，得到 {snapshots!r}")
    snr_db_v = _finite(snr_db, "snr_db")
    d_lam = _finite(spacing_lambda, "spacing_lambda")
    if not 0.0 < d_lam <= 1.0:
        raise ValueError(
            f"doa_crb_ula: spacing_lambda=d/λ 必须 ∈ (0,1]（窄带口径 "
            f"d≤λ 物理合法；>1/2 栅瓣风险 note 不拒绝），得到 "
            f"{spacing_lambda!r}")
    theta_deg = _finite(angle_deg, "angle_deg")
    if not -90.0 < theta_deg < 90.0:
        raise ValueError(
            f"doa_crb_ula: angle_deg 必须 ∈ (−90, 90) 开区间（端fire 恰值 "
            f"cosθ=0 → CRB 发散显式拒绝），得到 {angle_deg!r}")

    snr_lin = 10.0 ** (snr_db_v / 10.0)
    theta_rad = math.radians(theta_deg)
    k = 2.0 * math.pi * d_lam
    aperture_factor = n * (n * n - 1) / 12.0
    crb_rad2 = _crb_ula_closed(n, n_snap, snr_lin, k, theta_rad)
    crb_std_rad = math.sqrt(crb_rad2)

    return {
        "crb_var_rad2": crb_rad2,
        "crb_std_rad": crb_std_rad,
        "crb_std_deg": math.degrees(crb_std_rad),
        "fisher_information_per_rad2": 1.0 / crb_rad2,
        "aperture_factor": aperture_factor,
        "k_rad_per_sine": k,
        "cos_theta": math.cos(theta_rad),
        "snr_linear": snr_lin,
        "note": (
            "确定性（条件）模型单源 CRB：Var(θ̂)≥σ²/(2T)·1/(d'ᴴP_a^⊥d')，"
            "ULA 投影二次型闭式 N(N²−1)/12；标度律 ∝1/T·1/SNR·1/cos²θ·"
            "1/N³（渐近因子 N(N²−1)/12 精确）；d/λ>1/2 栅瓣风险（本键 "
            "(0,1] 收、物理合法口径与 doa_* 估计器族一致）；多源 CRB "
            "（FIM 矩阵求逆+源间耦合）=doa_crb_ula_multisource（本键为"
            "其 M=1 逐位退化锚）；估计器本体=doa_music_spectrum/"
            "doa_esprit（估计误差对 CRB 贴近度即本键消费面）"),
        "source": _SOURCES["crb"],
    }


def _snr_list(snr_db: Any, n_src: int) -> list[float]:
    """snr_db 标量广播或逐源列表收敛（bool 拒收，#364④ is not None 口径）。"""
    if isinstance(snr_db, (list, tuple)):
        if len(snr_db) != n_src:
            raise ValueError(
                f"doa_crb_ula_multisource: snr_db 列表长度须=n_sources="
                f"{n_src}，得到 {len(snr_db)}")
        out = [_finite(v, "snr_db") for v in snr_db]
    else:
        v = _finite(snr_db, "snr_db")
        out = [v] * n_src
    return [10.0 ** (s / 10.0) for s in out]


@register_calculator(
    "doa_crb_ula_multisource",
    "DOA 多源 CRB 下界：FIM 矩阵求逆通用式 FIM=2T·Re[(DᴴP⊥D)⊙P̄ᵀ]"
    "（P̄=√snr·R·√snr 等相关源协方差）→ 求逆对角元=各源 CRB 方差/标准"
    "差 rad/deg；ρ=0 源解耦（FIM 对角恒零化）、ρ→1 相干奇异显式拒绝；"
    "N>M 投影秩硬前提；M=1 与 doa_crb_ula 逐位一致；MUSIC/ESPRIT 多目"
    "标精度裁判面（随机 CRB 不在键面如实登记）",
    (("n_elements", "int 阵元数 N（整数 ≥2 且 >源数 M——P⊥ 秩 N−M≥1）"),
     ("snapshots", "int 快拍数 T（整数 ≥1）"),
     ("angles_deg", "list[float]° 各源来波角（1..16 个；开区间 (−90,90)、"
      "两两异角）"),
     ("snr_db", "float|list dB 各源阵元级 SNR（标量广播或长度=M 列表）"),
     ("spacing_lambda", "float 阵元间隔 d/λ（∈(0,1]）"),
     ("corr_coef", "float 源间等相关系数 ρ（∈[0,1) 缺省 0=不相关；→1 "
      "相干 FIM 奇异显式拒绝）")),
    required=("n_elements", "snapshots", "angles_deg", "snr_db",
              "spacing_lambda"),
)
def doa_crb_ula_multisource(
    n_elements: int,
    snapshots: int,
    angles_deg: list[float],
    snr_db: float | list[float],
    spacing_lambda: float,
    corr_coef: float = 0.0,
) -> dict[str, Any]:
    """多源 ULA 确定性 CRB：FIM=2T·Re[(DᴴP⊥D)⊙P̄ᵀ] 求逆对角元（通用式）。"""
    if isinstance(n_elements, bool):
        raise ValueError(
            f"doa_crb_ula_multisource: n_elements 须为整数，得到 bool "
            f"{n_elements!r}")
    n_f = _finite(n_elements, "n_elements")
    if n_f != int(n_f):
        raise ValueError(
            f"doa_crb_ula_multisource: n_elements 须为整数，得到 "
            f"{n_elements!r}")
    n = int(n_f)
    if n < 2:
        raise ValueError(
            f"doa_crb_ula_multisource: n_elements 必须 ≥2，得到 "
            f"{n_elements!r}")
    if isinstance(snapshots, bool):
        raise ValueError(
            f"doa_crb_ula_multisource: snapshots 须为整数，得到 bool "
            f"{snapshots!r}")
    t_f = _finite(snapshots, "snapshots")
    if t_f != int(t_f):
        raise ValueError(
            f"doa_crb_ula_multisource: snapshots 须为整数，得到 "
            f"{snapshots!r}")
    n_snap = int(t_f)
    if n_snap < 1:
        raise ValueError(
            f"doa_crb_ula_multisource: snapshots 必须 ≥1，得到 "
            f"{snapshots!r}")
    if not isinstance(angles_deg, (list, tuple)) or not angles_deg:
        raise ValueError(
            "doa_crb_ula_multisource: angles_deg 须为非空角度列表，得到 "
            f"{angles_deg!r}")
    m_src = len(angles_deg)
    if m_src > _N_SOURCES_MAX:
        raise ValueError(
            f"doa_crb_ula_multisource: 源数必须 ≤{_N_SOURCES_MAX}（FIM 面"
            f"/JSON 体积守卫），得到 {m_src}")
    if n <= m_src:
        raise ValueError(
            f"doa_crb_ula_multisource: n_elements={n} 必须 >源数 M="
            f"{m_src}（P⊥=I−A(AᴴA)⁻¹Aᴴ 秩 N−M≥1 硬前提，N≤M 时 FIM 奇异"
            "无界，显式拒绝）")
    thetas = [_finite(a, "angles_deg") for a in angles_deg]
    for i, a in enumerate(thetas):
        if not -90.0 < a < 90.0:
            raise ValueError(
                f"doa_crb_ula_multisource: angles_deg[{i}] 必须 ∈ (−90, "
                f"90) 开区间（端fire 恰值 cosθ=0 → CRB 发散），得到 {a!r}")
    for i in range(m_src):
        for j in range(i + 1, m_src):
            if abs(thetas[i] - thetas[j]) < 1e-9:
                raise ValueError(
                    f"doa_crb_ula_multisource: angles_deg[{i}]={thetas[i]!r}"
                    f" 与 [{j}]={thetas[j]!r} 重合/近重合（<1e-9°）——A 奇"
                    "异显式拒绝")
    d_lam = _finite(spacing_lambda, "spacing_lambda")
    if not 0.0 < d_lam <= 1.0:
        raise ValueError(
            f"doa_crb_ula_multisource: spacing_lambda=d/λ 必须 ∈ (0,1]，"
            f"得到 {spacing_lambda!r}")
    rho = _finite(corr_coef, "corr_coef")
    if not 0.0 <= rho < 1.0:
        raise ValueError(
            f"doa_crb_ula_multisource: corr_coef 必须 ∈ [0,1)（ρ=1 全相"
            "干/相干源 FIM 奇异显式拒绝；负相关不在键面如实注记），得到 "
            f"{corr_coef!r}")
    if m_src == 1 and rho != 0.0:
        raise ValueError(
            "doa_crb_ula_multisource: M=1 时 corr_coef 须缺省 0（单源无"
            f"源间相关可言），得到 {corr_coef!r}")
    snr_lin = _snr_list(snr_db, m_src)

    # ── FIM 通用式：FIM = 2T·Re[(DᴴP⊥D) ⊙ P̄ᵀ] ──────────────────────────
    m_idx = np.arange(n, dtype=float)
    thetas_rad = [math.radians(a) for a in thetas]
    a_mat = np.column_stack([
        np.exp(1j * (2.0 * math.pi * d_lam * math.sin(t)) * m_idx)
        for t in thetas_rad])
    d_mat = np.column_stack([
        1j * (2.0 * math.pi * d_lam * math.cos(t)) * m_idx
        * np.exp(1j * (2.0 * math.pi * d_lam * math.sin(t)) * m_idx)
        for t in thetas_rad])
    gram = a_mat.conj().T @ a_mat
    proj = np.eye(n) - a_mat @ np.linalg.solve(gram, a_mat.conj().T)
    g_mat = d_mat.conj().T @ proj @ d_mat
    s_root = np.sqrt(np.asarray(snr_lin, dtype=float))
    r_mat = ((1.0 - rho) * np.eye(m_src)
             + rho * np.ones((m_src, m_src)))
    p_bar = np.outer(s_root, s_root) * r_mat
    fim = 2.0 * n_snap * (g_mat * p_bar.T).real
    fim = 0.5 * (fim + fim.T)  # 对称化（理论对称，浮点尾差 hygiene）

    # M=1 退化：单源闭式逐位路径（与 doa_crb_ula 同 helper 同算子序）
    if m_src == 1:
        k = 2.0 * math.pi * d_lam
        crb_diag = np.array([
            _crb_ula_closed(n, n_snap, snr_lin[0], k, thetas_rad[0])])
        fim = np.array([[1.0 / crb_diag[0]]])
    else:
        eigs = np.linalg.eigvalsh(fim)
        if eigs.min() <= 0.0:
            raise ValueError(
                f"doa_crb_ula_multisource: FIM 非正定（λmin={eigs.min():.3e}"
                "≤0）——源近重合/ρ 过高致奇异，显式拒绝（异角/降 corr_coef）")
        if eigs.max() <= 0.0 or eigs.min() / eigs.max() < 1.0 / _FIM_COND_MAX:
            raise ValueError(
                "doa_crb_ula_multisource: FIM 条件数超 "
                f"{_FIM_COND_MAX:.1e}（近奇异）——角度分辨率不足或源强近相"
                "干，显式拒绝（增大角间隔/降低 corr_coef/增快拍）")
        crb_diag = np.diag(np.linalg.inv(fim))

    crb_var = [float(v) for v in crb_diag]
    crb_std = [math.sqrt(v) for v in crb_var]
    # 不相关参考（ρ=0 对角面）与耦合罚因子
    uncoupled = [1.0 / (2.0 * n_snap * snr_lin[i] * float(g_mat[i, i].real))
                 for i in range(m_src)]
    penalty = [c / u if u > 0 else None
               for c, u in zip(crb_var, uncoupled, strict=True)]
    i_worst = max(range(m_src), key=lambda i: crb_var[i])

    return {
        "n_elements": n,
        "snapshots": n_snap,
        "n_sources": m_src,
        "angles_deg": list(thetas),
        "snr_db": [10.0 * math.log10(s) for s in snr_lin],
        "snr_linear": list(snr_lin),
        "spacing_lambda": d_lam,
        "corr_coef": rho,
        "fim_matrix": [[float(v) for v in row] for row in fim],
        "crb_var_rad2": crb_var,
        "crb_std_rad": crb_std,
        "crb_std_deg": [math.degrees(v) for v in crb_std],
        "uncoupled_crb_rad2": uncoupled,
        "coupling_penalty": penalty,
        "worst_source_index": i_worst,
        "worst_crb_std_deg": math.degrees(crb_std[i_worst]),
        "k_rad_per_sine": 2.0 * math.pi * d_lam,
        "note": (
            "确定性模型多源 CRB 通用式：FIM=2T·Re[(DᴴP⊥D)⊙P̄ᵀ]、"
            "CRB=FIM⁻¹ 对角元（Stoica-Nehorai 1989/Viberg-Ottersten 1991 "
            "形态；σ² 经 SNR 归一消去）；P̄=√snr·R·√snr 等相关口径"
            "（ρ∈[0,1)）；ρ=0 时 ⊙P̄ᵀ 零化 FIM 非对角→源解耦，但 Re[G_ii]"
            " 用全 A 子空间投影（含他源导向矢量）→ 各源 CRB 仍 ≥ 单源闭"
            "式（coupling_penalty>1=未知波形干扰的子空间代价，实测 "
            "1.0054@N8 双源）；ρ→1 相干 FIM 奇异（正定/条件数双守卫显式"
            "拒绝）；M=1 与 doa_crb_ula 逐位一致（同 helper 回归钉）；"
            "随机（高斯）模型对照口径=doa_crb_stochastic（本键为确定性"
            "半边）；估计器本体=doa_music_spectrum/doa_esprit"),
        "source": _SOURCES["crb_multi"],
    }


def _snr_cov(snr_lin: list[float], rho: float) -> np.ndarray:
    """源协方差 Q：等相关的对角 1、非对角 ρ 乘各自 √snr（与多源键同构）。"""
    m_src = len(snr_lin)
    r_mat = (1.0 - rho) * np.eye(m_src) + rho * np.ones((m_src, m_src))
    root = np.sqrt(np.asarray(snr_lin, dtype=float))
    return np.outer(root, root) * r_mat


def _crb_stoch_closed_fim(a_mat: np.ndarray, d_mat: np.ndarray,
                          q_mat: np.ndarray, n_snap: int) -> np.ndarray:
    """celebrated 随机 CRB 的 θ-块 FIM（σ²=1 口径）：
    FIM = 2T·Re[(DᴴP⊥D) ⊙ (QAᴴR⁻¹AQ)ᵀ]。"""
    n_el = a_mat.shape[0]
    r_mat = a_mat @ q_mat @ a_mat.conj().T + np.eye(n_el)
    w_mat = q_mat @ a_mat.conj().T @ np.linalg.solve(r_mat, a_mat) @ q_mat
    gram = a_mat.conj().T @ a_mat
    proj = np.eye(n_el) - a_mat @ np.linalg.solve(gram, a_mat.conj().T)
    g_mat = d_mat.conj().T @ proj @ d_mat
    return 2.0 * n_snap * (g_mat * w_mat.T).real


def _sb_exact_crb_fim(a_mat: np.ndarray, d_mat: np.ndarray,
                      q_mat: np.ndarray, n_snap: int) -> np.ndarray:
    """精确 Slepian-Bangs θ-块 FIM（σ² 与 Q 实参数化全 Schur 消元）。

    参数方向：θ_i（M 个）+ Q 实参数化（M 对角 + 2·C(M,2) 非对角 Re/Im）
    + σ²；全部 Tr[R⁻¹X_a R⁻¹X_b] 经循环不变量约简到 M×M 对象
    （B=AᴴRiA、S=QAᴴRiD、W=QAᴴRiAQ、V=DᴴRiAQ、K=DᴴRiD）。与锚树
    naive N×N 全参数构造互为独立路线（#118）。"""
    n_el, m_src = a_mat.shape
    r_inv = np.linalg.inv(a_mat @ q_mat @ a_mat.conj().T + np.eye(n_el))
    rid = r_inv @ d_mat
    ria = r_inv @ a_mat
    b_mat = a_mat.conj().T @ ria            # AᴴRiA
    h_mat = a_mat.conj().T @ rid            # AᴴRiD
    g_mat = d_mat.conj().T @ ria            # DᴴRiA
    s_mat = q_mat @ h_mat                   # QAᴴRiD
    w_mat = q_mat @ b_mat @ q_mat           # QAᴴRiAQ
    v_mat = d_mat.conj().T @ (ria @ q_mat)  # DᴴRiAQ
    k_mat = d_mat.conj().T @ rid            # DᴴRiD

    # θ-θ（四项循环约简，实部）：SijSji + KjiWij + KijWji + VijVji
    f_tt = np.empty((m_src, m_src), dtype=float)
    for i in range(m_src):
        for j in range(m_src):
            t_total = (s_mat[i, j] * s_mat[j, i] + k_mat[j, i] * w_mat[i, j]
                       + k_mat[i, j] * w_mat[j, i]
                       + v_mat[i, j] * v_mat[j, i])
            f_tt[i, j] = n_snap * t_total.real

    # Q 实参数化基（M 对角 + 每非对角对 Re/Im 两方向）
    e_basis: list[np.ndarray] = []
    for k_i in range(m_src):
        e_m = np.zeros((m_src, m_src))
        e_m[k_i, k_i] = 1.0
        e_basis.append(e_m)
    for k_i in range(m_src):
        for l_i in range(k_i + 1, m_src):
            e_r = np.zeros((m_src, m_src))
            e_r[k_i, l_i] = 1.0
            e_r[l_i, k_i] = 1.0
            e_basis.append(e_r)
            e_i = np.zeros((m_src, m_src), dtype=complex)
            e_i[k_i, l_i] = 1.0j
            e_i[l_i, k_i] = -1.0j
            e_basis.append(e_i)
    nq = len(e_basis)

    # θ-q 交叉：F=T·Tr[AᴴRi dR_θi Ri A Ea]，C_i 约简 M×M
    # （C_i=AᴴRid_i·e_iᵀ(QAᴴRiA)+(AᴴRiAQe_i)·d_iᴴRiA；U=QB、BQ）
    u_mat = q_mat @ b_mat
    c_vec = [h_mat[:, i:i + 1] @ u_mat[i:i + 1, :]
             + (b_mat @ q_mat)[:, i:i + 1] @ g_mat[i:i + 1, :]
             for i in range(m_src)]
    f_tq = np.empty((m_src, nq), dtype=float)
    for i in range(m_src):
        for a_i, e_a in enumerate(e_basis):
            f_tq[i, a_i] = n_snap * (c_vec[i] * e_a.T).sum().real

    # q-q：F=T·Tr[B Ea B Eb]
    f_qq = np.empty((nq, nq), dtype=float)
    for a_i in range(nq):
        ba = b_mat @ e_basis[a_i]
        for b_i in range(nq):
            f_qq[a_i, b_i] = n_snap * (ba @ b_mat @ e_basis[b_i]).trace().real

    # σ² 行/列与 Schur 消元
    f_ts = n_snap * (s_mat.diagonal() + v_mat.diagonal()).real
    f_qs = np.array([n_snap * (b_mat * e_a.T).sum().real
                     for e_a in e_basis])
    f_ss = n_snap * (r_inv @ r_inv).trace().real

    dim = m_src + nq + 1
    fim = np.zeros((dim, dim))
    fim[:m_src, :m_src] = f_tt
    fim[:m_src, m_src:m_src + nq] = f_tq
    fim[m_src:m_src + nq, :m_src] = f_tq.T
    fim[m_src:m_src + nq, m_src:m_src + nq] = f_qq
    fim[:m_src, -1] = f_ts
    fim[-1, :m_src] = f_ts
    fim[m_src:m_src + nq, -1] = f_qs
    fim[-1, m_src:m_src + nq] = f_qs
    fim[-1, -1] = f_ss

    elim = list(range(m_src, dim))
    fr = fim[np.ix_(list(range(m_src)) + elim, list(range(m_src)) + elim)]
    return fr[:m_src, :m_src] - fr[:m_src, m_src:] @ np.linalg.solve(
        fr[m_src:, m_src:], fr[m_src:, :m_src])


def _pd_guard(fim: np.ndarray, key: str, face: str) -> None:
    """FIM 正定/条件数双守卫（celebrated 与 Slepian-Bangs 两面各自判）。"""
    eigs = np.linalg.eigvalsh(0.5 * (fim + fim.T))
    if eigs.min() <= 0.0:
        raise ValueError(
            f"{key}: {face} FIM 非正定（λmin={eigs.min():.3e}≤0）——源近重"
            "合/ρ 过高致奇异，显式拒绝（异角/降 corr_coef）")
    if eigs.max() <= 0.0 or eigs.min() / eigs.max() < 1.0 / _FIM_COND_MAX:
        raise ValueError(
            f"{key}: {face} FIM 条件数超 {_FIM_COND_MAX:.1e}（近奇异）——"
            "角度分辨率不足或源强近相干，显式拒绝（增大角间隔/降低 "
            "corr_coef/增快拍）")


def _stoch_common_guards(
    key: str, n_elements: Any, snapshots: Any, angles_deg: Any,
    snr_db: Any, spacing_lambda: Any, corr_coef: float,
) -> tuple[int, int, list[float], list[float], float, float]:
    """随机键与多源键同口径的域守卫（返回 N/T/角列/线性 SNR/间隔/ρ）。"""
    if isinstance(n_elements, bool):
        raise ValueError(
            f"{key}: n_elements 须为整数，得到 bool {n_elements!r}")
    n_f = _finite(n_elements, "n_elements")
    if n_f != int(n_f):
        raise ValueError(
            f"{key}: n_elements 须为整数，得到 {n_elements!r}")
    n = int(n_f)
    if n < 2:
        raise ValueError(
            f"{key}: n_elements 必须 ≥2，得到 {n_elements!r}")
    if isinstance(snapshots, bool):
        raise ValueError(
            f"{key}: snapshots 须为整数，得到 bool {snapshots!r}")
    t_f = _finite(snapshots, "snapshots")
    if t_f != int(t_f):
        raise ValueError(
            f"{key}: snapshots 须为整数，得到 {snapshots!r}")
    n_snap = int(t_f)
    if n_snap < 1:
        raise ValueError(
            f"{key}: snapshots 必须 ≥1，得到 {snapshots!r}")
    if not isinstance(angles_deg, (list, tuple)) or not angles_deg:
        raise ValueError(
            f"{key}: angles_deg 须为非空角度列表，得到 {angles_deg!r}")
    m_src = len(angles_deg)
    if m_src > _N_SOURCES_MAX:
        raise ValueError(
            f"{key}: 源数必须 ≤{_N_SOURCES_MAX}（FIM 面/JSON 体积守卫），"
            f"得到 {m_src}")
    if n <= m_src:
        raise ValueError(
            f"{key}: n_elements={n} 必须 >源数 M={m_src}（P⊥=I−A(AᴴA)⁻¹"
            "Aᴴ 秩 N−M≥1 硬前提，N≤M 时 FIM 奇异无界，显式拒绝）")
    thetas = [_finite(a, "angles_deg") for a in angles_deg]
    for i, a in enumerate(thetas):
        if not -90.0 < a < 90.0:
            raise ValueError(
                f"{key}: angles_deg[{i}] 必须 ∈ (−90, 90) 开区间（端fire "
                f"恰值 cosθ=0 → CRB 发散），得到 {a!r}")
    for i in range(m_src):
        for j in range(i + 1, m_src):
            if abs(thetas[i] - thetas[j]) < 1e-9:
                raise ValueError(
                    f"{key}: angles_deg[{i}]={thetas[i]!r} 与 [{j}]="
                    f"{thetas[j]!r} 重合/近重合（<1e-9°）——A 奇异显式拒绝")
    d_lam = _finite(spacing_lambda, "spacing_lambda")
    if not 0.0 < d_lam <= 1.0:
        raise ValueError(
            f"{key}: spacing_lambda=d/λ 必须 ∈ (0,1]，得到 "
            f"{spacing_lambda!r}")
    rho = _finite(corr_coef, "corr_coef")
    if not 0.0 <= rho < 1.0:
        raise ValueError(
            f"{key}: corr_coef 必须 ∈ [0,1)（ρ=1 全相干 FIM 奇异显式拒"
            f"绝），得到 {corr_coef!r}")
    if m_src == 1 and rho != 0.0:
        raise ValueError(
            f"{key}: M=1 时 corr_coef 须缺省 0（单源无源间相关可言），得到 "
            f"{corr_coef!r}")
    return n, n_snap, thetas, _snr_list(snr_db, m_src), d_lam, rho


@register_calculator(
    "doa_crb_stochastic",
    "DOA 随机（高斯）信号 CRB：s_t~CN(0,Q) 边缘化 x_t~CN(0,R) 模型——"
    "celebrated 闭式 CRB=(σ²/2T){Re[(DᴴP⊥D)⊙(QAᴴR⁻¹AQ)ᵀ]}⁻¹（Stoica-"
    "Nehorai 1989 两模型对照随机半边）主口径 + 精确 Slepian-Bangs 全参数"
    "（σ²、Q Schur 消元）内建互证面（全域恰等 rel≤7.5e-15 实测）；"
    "M=1 退化=确定性键×(1+1/(pN))（随机≥确定性、高 SNR 渐近相等）；"
    "与 doa_crb_ula_multisource（确定性）并列口径",
    (("n_elements", "int 阵元数 N（整数 ≥2 且 >源数 M——P⊥ 秩 N−M≥1）"),
     ("snapshots", "int 快拍数 T（整数 ≥1）"),
     ("angles_deg", "list[float]° 各源来波角（1..16 个；开区间 (−90,90)、"
      "两两异角）"),
     ("snr_db", "float|list dB 各源阵元级 SNR=p/σ²（标量广播或长度=M 列"
      "表）"),
     ("spacing_lambda", "float 阵元间隔 d/λ（∈(0,1]）"),
     ("corr_coef", "float 源间等相关系数 ρ（∈[0,1) 缺省 0=不相关；ρ=0 "
      "闭式恰等精确面）")),
    required=("n_elements", "snapshots", "angles_deg", "snr_db",
              "spacing_lambda"),
)
def doa_crb_stochastic(
    n_elements: int,
    snapshots: int,
    angles_deg: list[float],
    snr_db: float | list[float],
    spacing_lambda: float,
    corr_coef: float = 0.0,
) -> dict[str, Any]:
    """随机（高斯）信号 CRB：celebrated 闭式主口径 + 精确 SB 面并列。"""
    key = "doa_crb_stochastic"
    n, n_snap, thetas, snr_lin, d_lam, rho = _stoch_common_guards(
        key, n_elements, snapshots, angles_deg, snr_db, spacing_lambda,
        corr_coef)
    m_src = len(thetas)

    m_idx = np.arange(n, dtype=float)
    thetas_rad = [math.radians(a) for a in thetas]
    a_mat = np.column_stack([
        np.exp(1j * (2.0 * math.pi * d_lam * math.sin(t)) * m_idx)
        for t in thetas_rad])
    d_mat = np.column_stack([
        1j * (2.0 * math.pi * d_lam * math.cos(t)) * m_idx
        * np.exp(1j * (2.0 * math.pi * d_lam * math.sin(t)) * m_idx)
        for t in thetas_rad])
    q_mat = _snr_cov(snr_lin, rho)

    fim_closed = _crb_stoch_closed_fim(a_mat, d_mat, q_mat, n_snap)
    _pd_guard(fim_closed, key, "celebrated 闭式")
    crb_closed = np.diag(np.linalg.inv(fim_closed))

    fim_sb = _sb_exact_crb_fim(a_mat, d_mat, q_mat, n_snap)
    _pd_guard(fim_sb, key, "Slepian-Bangs 精确")
    crb_sb = np.diag(np.linalg.inv(fim_sb))

    crb_var = [float(v) for v in crb_closed]
    crb_std = [math.sqrt(v) for v in crb_var]
    sb_vals = [float(v) for v in crb_sb]
    rel_dev = max(abs(c - s) / abs(s)
                  for c, s in zip(crb_var, sb_vals, strict=True))
    i_worst = max(range(m_src), key=lambda i: crb_var[i])

    out: dict[str, Any] = {
        "n_elements": n,
        "snapshots": n_snap,
        "n_sources": m_src,
        "angles_deg": list(thetas),
        "snr_db": [10.0 * math.log10(s) for s in snr_lin],
        "snr_linear": list(snr_lin),
        "spacing_lambda": d_lam,
        "corr_coef": rho,
        "q_matrix": [[float(v.real), float(v.imag)]
                     for row in q_mat for v in row],
        "q_matrix_shape": [m_src, m_src],
        "fim_stoch": [[float(v) for v in row] for row in fim_closed],
        "crb_var_rad2": crb_var,
        "crb_std_rad": crb_std,
        "crb_std_deg": [math.degrees(v) for v in crb_std],
        "sb_exact_fim_theta": [[float(v) for v in row] for row in fim_sb],
        "sb_exact_crb_var_rad2": sb_vals,
        "closed_vs_exact_max_rel": rel_dev,
        "worst_source_index": i_worst,
        "worst_crb_std_deg": math.degrees(crb_std[i_worst]),
        "k_rad_per_sine": 2.0 * math.pi * d_lam,
        "noise_variance_note": (
            "σ²=1 SNR 归一口径（θ-CRB 对 σ² 尺度不变）；Slepian-Bangs 面"
            "已对 σ² 与 Q（实参数化）全 Schur 消元"),
    }
    if m_src == 1:
        g_val = ((2.0 * math.pi * d_lam) ** 2
                 * math.cos(thetas_rad[0]) ** 2
                 * n * (n * n - 1) / 12.0)
        p_lin = snr_lin[0]
        det_crb = 1.0 / (2.0 * n_snap * p_lin * g_val)
        out["m1_deterministic_crb_rad2"] = det_crb
        out["m1_stoch_over_det_ratio"] = crb_var[0] / det_crb
        out["m1_ratio_identity"] = 1.0 + 1.0 / (p_lin * n)
    out["note"] = (
        "随机（高斯）信号模型 CRB：x_t~CN(0,R)、R=AQAᴴ+σ²I；celebrated "
        "闭式 CRB=(σ²/2T){Re[(DᴴP⊥D)⊙(QAᴴR⁻¹AQ)ᵀ]}⁻¹（Stoica-Nehorai "
        "1989 两模型对照随机半边）为 crb_var_rad2 主口径；sb_exact_*="
        "精确 Slepian-Bangs 全参数 FIM（σ²、Q Schur 消元）——Q/σ² 全消"
        "元前提下两口径全域恰等（实测 ρ=0..0.8 等/不等 SNR rel≤7.5e-15，"
        "closed_vs_exact_max_rel 即内建互证面）；Q 或 σ² 已知不消元时系"
        "统性偏离（冗余参数消元不可省，实测 up to 71%@ρ=0.8）；M=1 退化 "
        "CRB=(1+pN)/(2T·p²·N·G)=确定性键×(1+1/(pN))——随机恒 ≥ 确定性"
        "（未知信号统计代价）、高 SNR 渐近相等，且 ULA m=0 约定下 "
        "FIM_θ,σ²=FIM_θ,Q=0（σ²/Q 是否已知不敏感，实测逐位）；确定性模"
        "型对应键=doa_crb_ula/doa_crb_ula_multisource（两模型对照即原文"
        "献主题）")
    out["source"] = _SOURCES["crb_stoch"]
    return out
