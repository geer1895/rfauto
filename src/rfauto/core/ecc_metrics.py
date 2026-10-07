"""ECC 双路径确定性内核（ME-21，J 流 MIMO OTA 验收件）。

纯 numpy、零 IO、不进注册表（core 隔离件）。与并行轨在写的
core/ota_metrics.py（QW-8）互相独立：球面积分辅助各自实现、互不
import（在飞冲突隔离，后续统一收敛）——两处 sinθ 加权球面梯形积分
形态趋同是物理口径一致（TR 37.977/Balanis 同源）而非复制。

两条物理口径（同一设计的双路径可对照 = 本件核心价值）：

- 方向图积分路径（3GPP TR 37.977 annex 方向图相关口径；Balanis
  《Antenna Theory》§2.5 球面积分）：复方向图内积
      ρ_e(i,j) = ∫∫ E_i(Ω)·E_j*(Ω) dΩ / (√∫∫|E_i|²dΩ · √∫∫|E_j|²dΩ)
      dΩ = sinθ·dθ·dφ。
  输入 E_i 为"第 i 元激励、其余端接"的分量方向图（自由空间远场，
  绝对相位参考统一到阵列原点）——本模块不做阵列叠加重建。积分域 =
  入参网格覆盖域（全球或部分球域参数化，如实只积覆盖域）。
  TR 37.977 annex 完整形态含 XPR（交叉极化比）项与 θ/φ 双极化分量
  （ρ = |∫∫[XPR·G1θ·G2θ* + G1φ·G2φ*]dΩ|/…）——本件以单复场分量
  E(Ω) 承载（单极化/合成场口径）；双极化 + XPR 扩展由调用方合成
  复场或后续扩展，如实标注。

- S 参数路径（Blanch/Romeu/Corbella 2003 双端口式 + 列 Gram 多端口
  推广）。无损互易天线系统、每口单传播模、其余口共轭匹配端接：
      ECC_jk = |Σ_i S_ij*·S_ik|² / ((1−Σ_i|S_ij|²)·(1−Σ_i|S_ik|²))
  推导：无损系统功率守恒给远场内积恒等式
  ⟨E_j,E_k⟩ ∝ δ_jk − Σ_i S_ij*·S_ik = (I − SᴴS)_jk，且 ‖E_j‖² ∝
  (I − SᴴS)_jj = 1 − 第 j 列功率和 = 元 j 辐射效率（入射功率 = 反射
  + 耦合被端接吸收 + 辐射）。分子恰为列 Gram (SᴴS)_jk，与 Blanch
  2003（Electronics Letters 39(9)）印刷双端口式逐字一致：
      ECC = |S11*·S12 + S21*·S22|² /
            ((1−|S11|²−|S21|²)·(1−|S22|²−|S12|²))
  （互易 S12=S21 时与任务书行式 Σ_i S_1i*·S_2i 相同）。

- DG（分集增益）近似（任务书钉定简化式）：DG = 10·log10(1−ECC)
  = 10·log10(1−|ρ_e|²)。注：该式是"相关性损耗"口径的简化式
  （ECC→1 时 →−∞），非绝对分集增益；严格有效分集增益（EDG）需
  outage/SNR 分布假设，不在本件范围。

ECC 口径注记（重要）：文献/3GPP 语境 ECC ≡ |ρ_e|² ∈ [0,1]——0 =
理想去相关（好）、1 = 完全相关（差）；"1−|ρ_e|²"是分集增益线性
因子。本件解析锚族（共线远距→0、同图同点→1、理想无耦→0、全反
极限→1、自相关对角恒等=1）全部按该文献口径钉定，DG 式与之自洽
（DG = 10·log10(1−ECC)）。

单位与数值纪律：
- 角度一律度入参、内部弧度、线性域运算；
- 球面权重 = sinθ·θ 梯形 × φ 权重；φ 轴闭合环自动检测（跨度 ≈2π
  或缺口 ≤ 最大采样间距 → 周期梯形；数值重复端点末点权重归零，
  不双计），其余开放域走标准梯形；
- ECC 裁剪到 [0,1]（浮点对角噪声）；DG 以 1e-300 兜底（ECC=1 时
  DG = −3000 dB 哨兵值，物理判读走 loss_budget/degenerate）；
- NaN/Inf/bool 拒收（df7+⑯：float(True)=1.0 静默污染统计）；
- 非互易 S（|S_ij| 与 |S_ji| 相对偏差 > 5%）只警告不阻断——Blanch
  式假设互易，偏差事实由调用方裁决；
- 零辐射效率端口（1−Σ|S|² ≈ 0）公式 0/0 退化：按完全相关界截为
  1 并警告，degenerate 标志 + loss_budget 如实暴露退化事实。
"""

from __future__ import annotations

import warnings

import numpy as np

__all__ = [
    "ecc_crosscheck",
    "ecc_from_patterns",
    "ecc_from_sparams",
]

#: φ 轴闭合环缺口判定余量（相对最大采样间距的放大系数）
_PHI_WRAP_REL_TOL = 1.0 + 1e-6
#: 非互易幅度相对偏差警告阈值（Blanch 式假设互易）
_RECIPROCITY_TOL = 0.05
#: 辐射效率零判定（公式退化域）
_LOSS_BUDGET_TINY = 1e-12
#: DG 兜底（ECC=1 → 10·log10(1e-300) = −3000 dB 哨兵）
_DG_FLOOR = 1e-300


def _as_complex_array(value: object, name: str) -> np.ndarray:
    """复数组收敛 + bool/NaN/Inf 拒收（df7+⑯）。"""
    arr = np.asarray(value)
    if arr.dtype == np.bool_:
        raise ValueError(f"{name} 为 bool 数组：布尔会静默当 0/1 污染统计，拒收")
    try:
        arr = arr.astype(np.complex128)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 无法转复数数组: {exc}") from exc
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含 NaN/Inf，拒收")
    return arr


def _as_angle_vector(value: object, name: str, hi_max: float | None) -> np.ndarray:
    """角度轴收敛：一维、有限、严格升序；hi_max 非 None 时约束上界。"""
    arr = np.asarray(value, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维角度轴（度），得到 ndim={arr.ndim}")
    if arr.size < 2:
        raise ValueError(f"{name} 至少 2 个采样点，得到 {arr.size}")
    if not bool(np.all(np.isfinite(arr))):
        raise ValueError(f"{name} 含 NaN/Inf，拒收")
    if not bool(np.all(np.diff(arr) > 0.0)):
        raise ValueError(f"{name} 必须严格升序")
    if hi_max is not None and (arr[0] < -1e-9 or arr[-1] > hi_max + 1e-9):
        raise ValueError(f"{name} 超出 [0, {hi_max}] 度范围")
    return arr


def _trapezoid_weights(x: np.ndarray) -> np.ndarray:
    """开放区间标准梯形权重（Σw = x[-1] − x[0]）。"""
    d = np.diff(x)
    w = np.zeros_like(x)
    w[:-1] += d / 2.0
    w[1:] += d / 2.0
    return w


def _phi_weights_rad(ph: np.ndarray) -> np.ndarray:
    """φ 轴权重（弧度）：闭合环自动检测走周期梯形，否则开放梯形。

    - 缺口 wrap = 2π − span ≤ 1e-9：端点跨（或重复于）整环。
      数值重复端点（末点 ≈ 首点）末点权重归零；端点跨整环（如
      [0, 2π]）按周期邻距分配——对周期方向图两者逐点等价。
    - 缺口 ≤ 最大采样间距：endpoint=False 满环采样，按周期梯形补
      wrap 段（Σw = 2π）。
    - 其余：部分方位域，开放梯形（Σw = span，如实只积覆盖域）。
    """
    n = int(ph.size)
    two_pi = 2.0 * np.pi
    span = float(ph[-1] - ph[0])
    wrap = two_pi - span
    if wrap <= 1e-9 and abs(float(ph[-1] - ph[0])) <= 1e-9:
        # 重复端点闭合环（如 linspace(0, 360, N) 含端点）
        d = np.diff(ph)
        w = np.zeros(n, dtype=float)
        w[1:-1] = (d[:-1] + d[1:]) / 2.0
        w[0] = (d[-1] + d[0]) / 2.0
        # w[-1] 保持 0：重复端点不双计
        return w
    d_max = float(np.max(np.diff(ph)))
    if wrap > 1e-9 and wrap > d_max * _PHI_WRAP_REL_TOL:
        return _trapezoid_weights(ph)
    # 闭合环（endpoint=False 满环 / 端点恰跨 2π）：周期梯形
    d_cyc = np.append(np.diff(ph), wrap)
    return 0.5 * (np.roll(d_cyc, 1) + d_cyc)


def _sphere_weights(theta_deg: np.ndarray, phi_deg: np.ndarray) -> np.ndarray:
    """球面积分权重（弧度域）：sinθ·θ 梯形 ⊗ φ 权重，形状 (n_th, n_ph)。"""
    th = np.deg2rad(theta_deg)
    ph = np.deg2rad(phi_deg)
    w_th = _trapezoid_weights(th) * np.sin(th)
    w_ph = _phi_weights_rad(ph)
    return np.outer(w_th, w_ph)


def _dg_from_ecc(ecc: np.ndarray) -> np.ndarray:
    """DG = 10·log10(1−ECC)，1e-300 兜底（ECC=1 → −3000 dB 哨兵）。"""
    return 10.0 * np.log10(np.maximum(1.0 - ecc, _DG_FLOOR))


def ecc_from_patterns(
    e_fields: np.ndarray, theta_deg: np.ndarray, phi_deg: np.ndarray
) -> dict:
    """方向图积分路径 ECC（TR 37.977 annex 球面复内积口径）。

    e_fields: (n_ports, n_theta, n_phi) 复场——第 i 元激励、其余端接
    的分量方向图，绝对相位参考统一到阵列原点；theta_deg/phi_deg 为
    度制严格升序轴（θ ∈ [0,180]，φ 闭合环自动检测）。积分域 = 网格
    覆盖域（全球或部分球域参数化）。

    返回 dict：
    - ecc_matrix: (n, n) ECC ≡ |ρ_e|²（文献口径，0=理想去相关），
      对角恒等 1；
    - dg_matrix: (n, n) DG = 10·log10(1−ECC)（简化式，见模块注记）；
    - integral_norms: (n,) 每端口 √∫∫|E_i|²dΩ 归一诊断量；
    - corr_matrix: (n, n) 复相关系数 ρ_e（诊断/锚核对用）。
    """
    e = _as_complex_array(e_fields, "e_fields")
    if e.ndim != 3:
        raise ValueError(f"e_fields 须为 (n_ports, n_theta, n_phi) 三维，得到 ndim={e.ndim}")
    n = int(e.shape[0])
    if n < 2:
        raise ValueError(f"ECC 需要 ≥2 个端口，得到 n_ports={n}")
    th = _as_angle_vector(theta_deg, "theta_deg", hi_max=180.0)
    ph = _as_angle_vector(phi_deg, "phi_deg", hi_max=None)
    if e.shape[1] != th.size or e.shape[2] != ph.size:
        raise ValueError(
            f"e_fields 形状 {e.shape} 与角度轴 (n_theta={th.size}, n_phi={ph.size}) 不符"
        )
    w = _sphere_weights(th, ph)
    ef = e.reshape(n, -1)
    wf = w.reshape(-1)
    norm2 = np.abs(ef) ** 2 @ wf
    if bool(np.any(norm2 <= 0.0)):
        raise ValueError("存在零方向图端口（球面积分模长为 0），无法归一相关系数")
    norms = np.sqrt(norm2)
    corr = (ef * wf) @ ef.conj().T / np.outer(norms, norms)
    corr = (corr + corr.conj().T) / 2.0  # 数学上必 Hermitian，仅消浮点噪声
    ecc = np.clip(np.abs(corr) ** 2, 0.0, 1.0)
    return {
        "ecc_matrix": ecc,
        "dg_matrix": _dg_from_ecc(ecc),
        "integral_norms": norms,
        "corr_matrix": corr,
    }


def _warn_non_reciprocal(s: np.ndarray) -> None:
    """|S_ij| 与 |S_ji| 相对偏差超阈警告（Blanch 式假设互易）。"""
    amp = np.abs(s)
    off = ~np.eye(amp.shape[0], dtype=bool)
    denom = np.maximum(np.maximum(amp, amp.T), 1e-300)
    rel = np.abs(amp - amp.T) / denom
    if bool(np.any(rel[off] > _RECIPROCITY_TOL)):
        warnings.warn(
            "S 幅度非互易（|S_ij| 与 |S_ji| 相对偏差 >5%）：Blanch 式假设无损互易，"
            "结果为警告注记下的近似，请核对器件口径",
            UserWarning,
            stacklevel=3,
        )


def ecc_from_sparams(s: np.ndarray) -> dict:
    """S 参数路径 ECC（Blanch 2003 双端口式 + 列 Gram 多端口推广）。

    s: (n_ports, n_ports) 复 S 矩阵（单频点）。假设域：无损互易天线
    系统、每口单传播模、其余口共轭匹配端接（公式推导见模块 docstring）。

    返回 dict：
    - ecc_matrix: (n, n) ECC ≡ |ρ_e|²，对角恒等 1（自相关定义恒等）；
    - dg_matrix: (n, n) DG = 10·log10(1−ECC)；
    - loss_budget: (n,) 各元辐射效率 1−Σ_i|S_ij|²（列口径；互易时 =
      行口径。总辐射效率损失 = 1 − loss_budget，即 Σ 反射+耦合损耗）；
    - corr_matrix: (n, n) 复相关系数 ρ_e；
    - degenerate: bool——任一元辐射效率 ≈ 0 时 True（公式 0/0 退化，
      ECC 按完全相关界截为 1 并告警）；
    - n=2 时另给标量便捷键 ecc/dg = 矩阵 [0,1] 元。
    """
    sarr = _as_complex_array(s, "s")
    if sarr.ndim != 2 or sarr.shape[0] != sarr.shape[1]:
        raise ValueError(f"s 须为 (n_ports, n_ports) 方阵，得到形状 {sarr.shape}")
    n = int(sarr.shape[0])
    if n < 2:
        raise ValueError(f"ECC 需要 ≥2 个端口，得到 n_ports={n}")
    _warn_non_reciprocal(sarr)
    gram = sarr.conj().T @ sarr  # 列 Gram：(SᴴS)_jk = Σ_i S_ij*·S_ik
    col_power = np.real(np.diag(gram))
    loss_budget = 1.0 - col_power
    if bool(np.any(loss_budget < -_LOSS_BUDGET_TINY)):
        raise ValueError(
            "S 列功率和 >1（有源/非无损口径）：超出 Blanch 式假设域，拒绝硬算"
        )
    degenerate = bool(np.any(loss_budget <= _LOSS_BUDGET_TINY))
    if degenerate:
        warnings.warn(
            "存在零辐射效率端口（1−Σ|S|²≈0）：ECC 公式 0/0 退化，"
            "按完全相关界截为 1；物理判读以 loss_budget/degenerate 为准",
            UserWarning,
            stacklevel=2,
        )
    safe_lb = np.maximum(loss_budget, _LOSS_BUDGET_TINY)
    corr = (np.eye(n) - gram) / np.sqrt(np.outer(safe_lb, safe_lb))
    np.fill_diagonal(corr, 1.0)  # 自相关恒等 1（退化元亦然）
    corr = (corr + corr.conj().T) / 2.0
    ecc = np.clip(np.abs(corr) ** 2, 0.0, 1.0)
    out: dict = {
        "ecc_matrix": ecc,
        "dg_matrix": _dg_from_ecc(ecc),
        "loss_budget": loss_budget,
        "corr_matrix": corr,
        "degenerate": degenerate,
    }
    if n == 2:
        out["ecc"] = float(ecc[0, 1])
        out["dg"] = float(_dg_from_ecc(ecc[0, 1]))
    return out


def _unit_interval_scalar(value: object, name: str) -> float:
    """[0,1] 标量收敛：bool/非数值/非有限/越界拒收。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 为 bool：拒收（布尔会静默当 0/1）")
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} 须为数值标量，得到 {type(value).__name__}")
    v = float(value)
    if not np.isfinite(v):
        raise ValueError(f"{name} 非有限值，拒收")
    if v < 0.0 or v > 1.0:
        raise ValueError(f"{name}={v} 超出 [0,1]")
    return v


def ecc_crosscheck(ecc_pattern: float, ecc_sparams: float, tol: float = 0.05) -> dict:
    """双路径互证裁决：方向图积分 ECC vs S 参数式 ECC。

    两物理口径对同一设计的可对照性 = 本件核心价值。verdict 语义：
    |差值| ≤ tol → AGREE（双路径互证通过）；否则 DISAGREE（两口径
    假设域分歧或数据可疑——强耦合/有损/多模下 S 式与方向图式如实
    分歧，须人工归因，不得凑绿）。

    tol 缺省 0.05（ECC ∈ [0,1] 的绝对差 5%）：弱耦合典型双路径残差
    量级 ~1e-3，松界留足两式假设差余量。
    """
    a = _unit_interval_scalar(ecc_pattern, "ecc_pattern")
    b = _unit_interval_scalar(ecc_sparams, "ecc_sparams")
    if isinstance(tol, (bool, np.bool_)) or not isinstance(
        tol, (int, float, np.integer, np.floating)
    ):
        raise ValueError(f"tol 须为正数值标量，得到 {type(tol).__name__}")
    tol_f = float(tol)
    if not np.isfinite(tol_f) or tol_f <= 0.0:
        raise ValueError(f"tol 须为正有限值，得到 {tol_f}")
    abs_diff = abs(a - b)
    return {
        "verdict": "AGREE" if abs_diff <= tol_f else "DISAGREE",
        "abs_diff": abs_diff,
        "tol": tol_f,
        "ecc_pattern": a,
        "ecc_sparams": b,
    }
