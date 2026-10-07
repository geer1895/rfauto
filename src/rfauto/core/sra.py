"""EM-7 近场源重构 SRA 内核（C-1，P1）：[Jx,Jy,Mx,My]ᵀ 等效源 Tikhonov 反演。

职责（铁律 7：数值只在确定性内核；本模块 = numpy/scipy 纯函数叶子，零 IO、
不进 calculators 注册表；与 aperture_holography 的代码级差异四条，规格 §C-1）：
- 未知量 = [Jx, Jy, M̃x, M̃y]ᵀ（M̃ = M/η₀ 归一，4N 维，N = 源面采样点数）
  非"场"——场量反演见 core/aperture_holography.py（FFT 对角）；
- 算子 = 稠密积分核矩阵 Z（切向并矢 Green + 旋度核，逐采样点对闭式装配）
  非 FFT 对角 → LSQ + Tikhonov 正则；
- 输出 |J|/|M| 热图（A/m 与 V/m 表面密度）+ argmax 定位（质心细化）；
- 渐逝支路不置零（自然衰减进核，无谱域截断正则化——正则化只走 Tikhonov）。

物理口径（e^{+jωt} 时谐约定、前向波 exp(−jk·r)，与本仓 aperture_holography/
nf_transform 一致；全 SI，k = 2πf/c，η₀ = μ₀c）——逐式推导（自推导，出处节
双源交叉）：

- 电 流元（点矩 J·dV，A·m）：E = −jωμ(I + ∇∇/k²)(gJ)、H = ∇g×J；
- 磁 流元（点矩 M·dV，V·m）：H = −jωε(I + ∇∇/k²)(gM)、E = −∇g×M
  （电/磁对偶：E→H、H→−E、ε↔μ；本模块用磁流元 M 而非磁偶极矩 m，
  m = M/(jωμ) 口径换算不进内核）；
- 标量 Green g(R) = e^{−jkR}/(4πR)；∂i g = −(jk + 1/R)g·R̂i；
  ∂i∂j g = g[−k²R̂iR̂j + (jk/R + 1/R²)(3R̂iR̂j − δij)]（闭式，源面-观测面
  间距 d>0 保证核元素非奇异）；
- 切向 2×2 块：A_ij = δij·g + (∂i∂j g)/k²（并矢）；C1 = ∂z g·[[0,−1],[1,0]]
  （旋度切向核，(∇g×J)_x = −∂z g·Jy、(∇g×J)_y = +∂z g·Jx）；
- 观测方程（数据 = [Ex; Ey; η₀Hx; η₀Hy]，未知 = [Jx; Jy; M̃x; M̃y]）::

      Z = [[ −jωμ·A  ,  −η₀·C1  ],
           [  η₀·C1  ,  −jη₀k·A ]]

  其中 ωμ = η₀k 且 η₀²ωε = η₀k（η₀ = μ₀c 恒等式），数据两侧 E/η₀H 同量纲
  （V/m），未知两侧 J/M̃ 同量纲（A/m）→ L=I 最小范数在 J/M̃ 间分配有单位
  意义。

离散守卫（规格 §C-1 四条）：
1. 采样 du,dv ≤ λ/2：复用 core/aperture_holography.nyquist_guard 判据，
   四个间距（源/观测 × u/v）逐轴独立适用，违反一律 ValueError 拒收
   （锚"du>λ/2 拒收"）；d_m 进 note 仅作语境。
2. 源面 ≥1.3×观测窗：两个轴各自 (n−1)·d ≥ ratio·(m−1)·d_obs；
   违反不拒收 → domain_ok=False 如实报告（截断伪象可见不虚构）。
3. |k⊥| 带宽：观测数据角谱（FFT）中落在源网格谱支撑（|kx|≤π/du_src 且
   |ky|≤π/dv_src）之外的功率占比 > 1e-3 → domain_ok=False（源网格不可
   表示的内容存在，混叠/失配如实声明）。
4. cond(Z) > 1e8 警示：cond_warning=True（不拒收；经济型 SVD 奇异值
   σmax/σmin；m<n 时存在零空间，cond 值只描述行空间条件数，note 如实）。

Tikhonov 与 λ 双法（规格 §C-1）：min ‖Zx−b‖² + λ‖Lx‖²，L = I（单位阵）或
一阶差分（源面 u/v 双向差分，逐通道）；λ 选择 = L 曲线曲率角（Hansen）+
GCV（Golub-Heath-Wahba）双法，两法 λ 之比 >10× → method="undetermined"
（λ 仍报几何均值供检视，ok=False）。L=I 走 SVD 谱分解快路径（一次 SVD 后
任意 λ 解 O(k)）；L=一阶差分走逐 λ Cholesky（O(N³)×λ 网格，P1 限小网格，
规格风险条款"O(N²)"的工程上限如实登记）。

输出 schema（规格 §C-1 {j_map,m_map,argmax_xy_m,λ,method,cond_z,
residual_db,domain_ok} 的本仓 ASCII 键映射）：
- ``j_map``：|J| 热图 (n_src_u, n_src_v) 实数，A/m；
- ``m_map``：|M| 热图 (n_src_u, n_src_v) 实数，V/m；
- ``argmax_xy_m``：组合功率图（|J|²+|M̃|²）峰位的质心细化坐标 [x, y]（m；
  ±1 邻窗 |map|² 加权质心，亚栅格定位估计器，测试侧另有逐图 argmax）；
- ``reg_lambda``：生效正则参数（规格 schema 记号 λ）；
- ``method``：``"lcurve+gcv"``（双法一致）/ ``"lcurve"`` / ``"gcv"``
  （单法有效）/ ``"undetermined"``（双法差 >10×）；
- ``cond_z``：Z 的经济型 SVD 条件数（σmax/σmin，可能 inf）；
- ``residual_db``：20·log10(‖Zx−b‖/‖b‖)（Frobenius；精确 0 残差 → −inf，
  如实不折叠）；
- ``domain_ok``：守卫 2+3 的合取（守卫 1 违反已在入口 ValueError 拒收）；
- 另附 ``ok``（域守卫 ∧ 无 cond 警示 ∧ λ 已定 ∧ 残差 ≤ residual_gate_db）、
  ``cond_warning`` / ``extent_ok`` / ``bandwidth_ok`` / ``reg_lambda_lcurve``
  / ``reg_lambda_gcv`` / ``note``。``ok`` 只消费可观测量（铁律 7：位置误差
  真值判据在测试侧锚，不在内核）。

边界（如实登记）：
- 源面/观测面网格都以公共原点为中心（调用方负责数据配准到该网格）；
- P1 内存 = O(N_obs·N_src·~80B) 逐点对稠密装配：64×64 源 × 64×64 观测
  ≈ 4 GB（规格风险条款"O(N²)→首版 N≤64×64"的具体形态），批量/分块留 P2；
- 本模块不产任何真实器件的物理数字（判据主口径 = 合成注入回收，真值在
  测试侧独立重建，#118 家族纪律）。

出处（等级如实标注）：
- 规格指定 J. L. A. Quijano & G. Vecchi, "Field and Source Equivalence in
  Source Reconstruction on 3D Surfaces", PIER 103, 67–100, 2010
  （DOI 10.2528/PIER10030309）——电/磁等效流组合反演的公式族出处；卷页与
  DOI 经检索确认（2026-10-02），**公式级页码 UNVERIFIED**（原文未逐式核对，
  本模块算子为其平面/切向特例的自推导闭式）；
- L 曲线角判据：P. C. Hansen, "Analysis of discrete ill-posed problems by
  means of the L-curve", SIAM Review 34(4), 561–580, 1992（曲率角离散三
  点式为自实现，论文页码 UNVERIFIED）；
- GCV：G. H. Golub, M. Heath, G. Wahba, "Generalized cross-validation as a
  method for choosing a good ridge parameter", Technometrics 21(2), 215–223,
  1979（有效自由度 trace 项为标准谱式，页码 UNVERIFIED）；
- 角谱/渐逝口径（对齐依据）：J. W. Goodman, "Introduction to Fourier
  Optics" 3rd ed. §3.8（Goodman 用 e^{−jωt}/exp(+jkz·z)，与本仓 e^{+jωt}/
  exp(−jkz·z) 互为共轭，逐式换算一致）；
- 偶极子闭式场（测试侧真值用，非本模块）：J. D. Jackson, "Classical
  Electrodynamics" 3rd ed. §9.2（e^{−iωt} 口径经共轭换算到 e^{+jωt}）。
"""

from __future__ import annotations

import math

import numpy as np
import scipy.linalg as sla

from rfauto.core.aperture_holography import C0, nyquist_guard

__all__ = [
    "BANDWIDTH_FLOOR",
    "COM_HALF_WINDOW",
    "COND_WARN_DEFAULT",
    "EXTENT_RATIO_DEFAULT",
    "LAMBDA_RATIO_MAX_DEFAULT",
    "RESIDUAL_GATE_DB_DEFAULT",
    "solve_sra",
    "sra_operator",
    "sra_solve",
]


#: 源面/观测窗最小外扩比（规格 §C-1 守卫 2：源面 ≥1.3×观测窗）
EXTENT_RATIO_DEFAULT = 1.3

#: cond(Z) 病态警示阈（规格 §C-1 守卫 4）
COND_WARN_DEFAULT = 1e8

#: |k⊥| 带宽守卫：观测角谱落入源网格支撑外的功率占比上限（相对地板）
BANDWIDTH_FLOOR = 1e-3

#: 残差门（dB，Frobenius 相对）：ok 判据之一（规格锚"残差 ≤−20dB"）
RESIDUAL_GATE_DB_DEFAULT = -20.0

#: λ 双法一致门：|λ_L/λ_G| 比 >10× → undetermined（规格 §C-1）
LAMBDA_RATIO_MAX_DEFAULT = 10.0

#: 峰位质心细化半窗宽（±1 邻窗，亚栅格定位估计器）
COM_HALF_WINDOW = 1

_N_LAMBDA_IDENTITY = 64  # L=I 快路径 λ 网格点数（谱分解后逐 λ O(k)）
_N_LAMBDA_DIFF = 24  # L=差分慢路径 λ 网格点数（逐 λ Cholesky，控时）

_TWO_PI = 2.0 * np.pi
#: 旋度切向核基（C1 = ∂z g·R90：[x,Jy]=−∂z g、[y,Jx]=+∂z g）
_R90 = np.array([[0.0, -1.0], [1.0, 0.0]])


# ─── 入参守卫（对齐 aperture_holography / poke_predistortion 口径） ─────────

def _scalar_float(x: object, name: str, *, minimum: float, allow_zero: bool) -> float:
    """校验标量数值参数：bool/非数值/非标量/非有限/越下界一律拒收。"""
    if isinstance(x, (bool, np.bool_)):
        raise ValueError(f"{name} 是 bool，拒绝（float(True)=1.0 静默污染，显式拒收）")
    arr = np.asarray(x)
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值，得到 dtype={arr.dtype}")
    if arr.size != 1:
        raise ValueError(f"{name} 必须是标量，得到 size={arr.size}")
    value = float(arr.reshape(()))
    if not np.isfinite(value):
        raise ValueError(f"{name} 必须有限，得到 {value}")
    if allow_zero:
        if value < minimum:
            raise ValueError(f"{name} 必须 ≥ {minimum}，得到 {value}")
    elif value <= minimum:
        raise ValueError(f"{name} 必须 > {minimum}，得到 {value}")
    return value


def _positive_int(x: object, name: str) -> int:
    """校验正整数参数：bool/非整数/非正一律拒收。"""
    if isinstance(x, (bool, np.bool_)):
        raise ValueError(f"{name} 是 bool，拒绝")
    if not isinstance(x, (int, np.integer)):
        raise ValueError(f"{name} 必须是整数，得到 {type(x).__name__}")
    value = int(x)
    if value < 1:
        raise ValueError(f"{name} 必须 ≥ 1，得到 {value}")
    return value


def _as_complex_2d(x: object, name: str) -> np.ndarray:
    """校验并转换为二维复数场；bool/非数值/非二维/NaN/Inf 拒收（实数转复数）。"""
    arr = np.asarray(x)
    if arr.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，拒绝（数值入参不得含 bool）")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值数组，得到 dtype={arr.dtype}")
    arr = arr.astype(complex)
    if arr.ndim != 2:
        raise ValueError(f"{name} 必须是二维 (n_u, n_v) 采样场，得到 ndim={arr.ndim}")
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise ValueError(f"{name} 至少为 1x1，得到 shape={arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf，拒绝")
    return arr


def _as_real_vector(x: object, name: str) -> np.ndarray:
    """校验并转换为一维实数向量；bool/复数/NaN/Inf 拒收。"""
    arr = np.asarray(x)
    if arr.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，拒绝")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值数组，得到 dtype={arr.dtype}")
    if np.issubdtype(arr.dtype, np.complexfloating):
        raise ValueError(f"{name} 必须为实数序列（复数拒收，禁止静默丢虚部）")
    arr = arr.astype(float).reshape(-1)
    if arr.size < 1:
        raise ValueError(f"{name} 不能为空")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf，拒绝")
    return arr


def _validate_operator(operator: object) -> str:
    if operator not in ("identity", "diff"):
        raise ValueError(f"operator 必须是 'identity' 或 'diff'，得到 {operator!r}")
    return operator  # type: ignore[return-value]


def _centered_grid(n: int, d: float) -> np.ndarray:
    """以 0 为中心的均匀网格坐标 (n 点，间距 d)。"""
    return (np.arange(n, dtype=float) - (n - 1) / 2.0) * d


# ─── 算子装配：稠密核矩阵 Z ──────────────────────────────────────────────────

def sra_operator(
    du_src_m: float,
    dv_src_m: float,
    n_src_u: int,
    n_src_v: int,
    du_obs_m: float,
    dv_obs_m: float,
    n_obs_u: int,
    n_obs_v: int,
    d_m: float,
    f_hz: float,
    *,
    extent_ratio: float = EXTENT_RATIO_DEFAULT,
) -> dict[str, object]:
    """装配 SRA 稠密观测算子 Z（[Ex;Ey;η₀Hx;η₀Hy] = Z·[Jx;Jy;M̃x;M̃y]）。

    网格约定：源面 z=0 与观测面 z=d_m 都以公共原点为中心，均匀采样；
    行序 = [Ex(逐点 C 序); Ey(...); η₀Hx(...); η₀Hy(...)]，
    列序 = [Jx(逐点); Jy(...); M̃x(...); M̃y(...)]（M̃ = M/η₀）。

    守卫（规格 §C-1）：采样间距四轴逐轴 nyquist_guard，任一违反 ValueError
    拒收；源面外扩比检查如实报告不拒收（结果进 ``extent_ok``）。

    返回 dict：``z_matrix``（4N_obs × 4N_src 复数）、``src_x_m``/``src_y_m``/
    ``obs_x_m``/``obs_y_m``（1D 网格坐标）、``k_rad``、``eta0``、
    ``extent_ok``、``extent_ratio_actual``、``note``。
    """
    dus = _scalar_float(du_src_m, "du_src_m", minimum=0.0, allow_zero=False)
    dvs = _scalar_float(dv_src_m, "dv_src_m", minimum=0.0, allow_zero=False)
    duo = _scalar_float(du_obs_m, "du_obs_m", minimum=0.0, allow_zero=False)
    dvo = _scalar_float(dv_obs_m, "dv_obs_m", minimum=0.0, allow_zero=False)
    nsu = _positive_int(n_src_u, "n_src_u")
    nsv = _positive_int(n_src_v, "n_src_v")
    nou = _positive_int(n_obs_u, "n_obs_u")
    nov = _positive_int(n_obs_v, "n_obs_v")
    d = _scalar_float(d_m, "d_m", minimum=0.0, allow_zero=False)
    f = _scalar_float(f_hz, "f_hz", minimum=0.0, allow_zero=False)
    ratio_min = _scalar_float(extent_ratio, "extent_ratio", minimum=1.0, allow_zero=False)

    lam = C0 / f
    # 守卫 1：四轴采样 ≤ λ/2（nyquist_guard 逐轴独立适用，违反拒收）
    for spacing, axis in ((dus, "du_src"), (dvs, "dv_src"), (duo, "du_obs"), (dvo, "dv_obs")):
        guard = nyquist_guard(spacing, d, f)
        if not guard["ok"]:
            raise ValueError(
                f"{axis}={spacing:.6g} m > λ/2={lam / 2.0:.6g} m（f={f:.6g} Hz），"
                f"采样判据违反，拒收（{guard['note']}）"
            )

    k = _TWO_PI * f / C0
    omega = _TWO_PI * f
    mu0 = 4.0e-7 * math.pi
    eta0 = mu0 * C0  # η₀ = μ₀c（= sqrt(μ₀/ε₀)，ε₀ = 1/(μ₀c²) 恒等式）

    src_x = _centered_grid(nsu, dus)
    src_y = _centered_grid(nsv, dvs)
    obs_x = _centered_grid(nou, duo)
    obs_y = _centered_grid(nov, dvo)

    # 源面外扩比检查（守卫 2，如实报告不拒收）
    ext_u = ((nsu - 1) * dus) / max((nou - 1) * duo, 1e-300)
    ext_v = ((nsv - 1) * dvs) / max((nov - 1) * dvo, 1e-300)
    extent_ok = bool(ext_u >= ratio_min and ext_v >= ratio_min)

    # 逐点对闭式核（观测点×源点展平；C 序与 b 装配一致）
    sxg, syg = np.meshgrid(src_x, src_y, indexing="ij")
    oxg, oyg = np.meshgrid(obs_x, obs_y, indexing="ij")
    sx = sxg.reshape(-1)
    sy = syg.reshape(-1)
    ox = oxg.reshape(-1)
    oy = oyg.reshape(-1)

    dx = ox[:, None] - sx[None, :]
    dy = oy[:, None] - sy[None, :]
    rr = np.sqrt(dx * dx + dy * dy + d * d)
    g = np.exp(-1j * k * rr) / (4.0 * math.pi * rr)
    rx = dx / rr
    ry = dy / rr
    # 并矢二阶导块（切向 2×2）：T_ij = g[−k²R̂iR̂j + (jk/R + 1/R²)(3R̂iR̂j − δij)]
    w1 = 1j * k / rr + 1.0 / (rr * rr)
    txx = g * (-k * k * rx * rx + w1 * (3.0 * rx * rx - 1.0))
    tyy = g * (-k * k * ry * ry + w1 * (3.0 * ry * ry - 1.0))
    txy = g * (-k * k * rx * ry + w1 * (3.0 * rx * ry))
    # A = δ·g + T/k²（切向并矢），C1 = ∂z g·R90
    az = g + txx / (k * k)
    ayy = g + tyy / (k * k)
    axy = txy / (k * k)
    dzg = -(1j * k + 1.0 / rr) * g * (d / rr)
    a2 = np.empty((rr.size, 2, 2), dtype=complex)
    a2[:, 0, 0] = az.reshape(-1)
    a2[:, 0, 1] = axy.reshape(-1)
    a2[:, 1, 0] = axy.reshape(-1)
    a2[:, 1, 1] = ayy.reshape(-1)
    c1 = dzg.reshape(-1)[:, None, None] * _R90[None, :, :]

    nop, nsp = ox.size, sx.size
    z = np.zeros((4 * nop, 4 * nsp), dtype=complex)
    # 4D 视图装配：z4[c, i, e, j] = Z[c·Nop+i（数据分量 c @ 观测点 i）,
    # e·Nsp+j（未知分量 e @ 源点 j）]；逐点对 2×2 块按 (i, j) 摊入
    z4 = z.reshape(4, nop, 4, nsp)
    val_a = a2.reshape(nop, nsp, 2, 2).transpose(2, 0, 3, 1)  # [c,i,e,j] = A2[p,c,e]
    val_c = c1.reshape(nop, nsp, 2, 2).transpose(2, 0, 3, 1)  # [c,i,e,j] = C1[p,c,e]
    z4[0:2, :, 0:2, :] = (-1j * omega * mu0) * val_a  # E ← J（并矢块）
    z4[0:2, :, 2:4, :] = (-eta0) * val_c  # E ← M̃（−η₀·旋度核）
    z4[2:4, :, 0:2, :] = (eta0) * val_c  # η₀H ← J（+η₀·旋度核）
    z4[2:4, :, 2:4, :] = (-1j * eta0 * k) * val_a  # η₀H ← M̃（−jη₀k·并矢块：η₀²ωε=η₀k）

    note = (
        f"算子装配：源 {nsu}×{nsv}（du={dus:.6g}, dv={dvs:.6g} m）@ z=0，观测 "
        f"{nou}×{nov}（du={duo:.6g}, dv={dvo:.6g} m）@ z={d:.6g} m，f={f:.6g} Hz；"
        f"外扩比 u={ext_u:.3f}/v={ext_v:.3f}（要求 ≥{ratio_min:g}）；"
        f"Z 形状 {z.shape[0]}×{z.shape[1]}（M̃=M/η₀ 归一，η₀={eta0:.6g} Ω）"
    )
    return {
        "z_matrix": z,
        "src_x_m": src_x,
        "src_y_m": src_y,
        "obs_x_m": obs_x,
        "obs_y_m": obs_y,
        "k_rad": float(k),
        "eta0": float(eta0),
        "extent_ok": extent_ok,
        "extent_ratio_actual": (float(min(ext_u, ext_v))),
        "note": note,
    }


# ─── λ 选择三件：L 曲线曲率角 / GCV / 双法合流 ───────────────────────────────

def _l_curve_corner(lambdas: np.ndarray, x_norms: np.ndarray, res_norms: np.ndarray) -> float | None:
    """L 曲线曲率角：log-log 平面离散三点（Menger）曲率最大点。

    Hansen 1992 的 L 曲线角判据离散实现：点序 (log‖x_λ‖, log‖r_λ‖)，
    κ_i = 2·|叉积| / (|p−a||q−b||p−a|)（三点外接圆曲率的 Menger 式），
    取 |κ| 最大者为中心点。非有限/非正范数点剔除；有效点 <3 返回 None。
    """
    lx = np.log10(np.asarray(x_norms, dtype=float))
    lr = np.log10(np.asarray(res_norms, dtype=float))
    valid = np.isfinite(lx) & np.isfinite(lr) & (lx > -300.0) & (lr > -300.0)
    idx = np.nonzero(valid)[0]
    if idx.size < 3:
        return None
    pts = np.stack([lx[idx], lr[idx]], axis=1)
    kappa = np.empty(idx.size, dtype=float)
    kappa[:] = 0.0
    for t in range(1, idx.size - 1):
        a, b, c = pts[t - 1], pts[t], pts[t + 1]
        d1 = float(np.linalg.norm(b - a))
        d2 = float(np.linalg.norm(c - b))
        d3 = float(np.linalg.norm(c - a))
        if d1 <= 0.0 or d2 <= 0.0 or d3 <= 0.0:
            continue
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        kappa[t] = 2.0 * abs(cross) / (d1 * d2 * d3)
    t_best = int(np.argmax(kappa))
    if kappa[t_best] <= 0.0:
        return None
    return float(lambdas[idx[t_best]])


def _gcv_minimize(
    lambdas: np.ndarray, res_sq: np.ndarray, n_rows: int, trace_terms: np.ndarray
) -> float | None:
    """GCV：G(λ) = m·‖r‖²/(m − tr(I − Z·Z_λ⁺))²，取网格最小。

    Golub-Heath-Wahba 1979 标准式；``trace_terms`` = Σᵢ sᵢ²/(sᵢ²+λ)（L=I）
    或逐 λ 的 ‖L_chol⁻¹ Z^H‖²_F（一般 L 的 exact trace）。分母 ≤0 的点取
    inf（GCV 在该 λ 无定义，不参与最小）；全 inf 返回 None。
    """
    lam = np.asarray(lambdas, dtype=float)
    rho = np.asarray(res_sq, dtype=float)
    tr = np.asarray(trace_terms, dtype=float)
    denom = float(n_rows) - tr
    with np.errstate(divide="ignore", invalid="ignore"):
        gcv = float(n_rows) * rho / np.where(denom > 0.0, denom**2, np.nan)
    if not np.any(np.isfinite(gcv)):
        return None
    i_best = int(np.nanargmin(gcv))
    return float(lam[i_best])


def _reconcile_lambda(
    lam_lcurve: float | None,
    lam_gcv: float | None,
    ratio_max: float,
) -> tuple[float | None, str, str]:
    """λ 双法合流：一致（比 ≤ratio_max）→ 几何均值 + "lcurve+gcv"；
    单法有效 → 该法；双法差 >ratio_max× → "undetermined"（仍报几何均值）；
    双法均无效 → (None, "undetermined")。"""
    both = lam_lcurve is not None and lam_gcv is not None and lam_lcurve > 0.0 and lam_gcv > 0.0
    if both:
        assert lam_lcurve is not None and lam_gcv is not None
        ratio = max(lam_lcurve, lam_gcv) / min(lam_lcurve, lam_gcv)
        lam = math.sqrt(lam_lcurve * lam_gcv)
        if ratio > ratio_max:
            return (
                lam,
                "undetermined",
                f"λ 双法分歧：L 曲线 {lam_lcurve:.6g} vs GCV {lam_gcv:.6g}"
                f"（比 {ratio:.3g} > {ratio_max:g}），正则强度不可判定，ok=False",
            )
        return (
            lam,
            "lcurve+gcv",
            f"λ 双法一致：L 曲线 {lam_lcurve:.6g} ≈ GCV {lam_gcv:.6g}"
            f"（比 {ratio:.3g} ≤ {ratio_max:g}），取几何均值 {lam:.6g}",
        )
    if lam_lcurve is not None and lam_lcurve > 0.0:
        return lam_lcurve, "lcurve", f"仅 L 曲线角有效（λ={lam_lcurve:.6g}），GCV 无有效极小"
    if lam_gcv is not None and lam_gcv > 0.0:
        return lam_gcv, "gcv", f"仅 GCV 有效（λ={lam_gcv:.6g}），L 曲线角无有效极大"
    return None, "undetermined", "λ 双法均无有效判据（网格退化或范数非正）"


# ─── 求解核：Tikhonov 谱路径（L=I）与逐 λ Cholesky 路径（L=差分） ────────────

def _lambda_grid(z: np.ndarray, n_points: int) -> np.ndarray:
    """缺省 λ 网格：[σmax²·1e-10, σmax²] 对数栅（8 个量级，覆盖角区两臂）。

    上界 σmax²：λ 超过 σmax² 后滤波因子 < 1/(2σmax)，解已被重阻尼到无信息
    （L 曲线在对数坐标的远端近直线，曲率角无物理意义）——网格不进该死区。
    """
    s_max = float(np.linalg.norm(z, 2))
    if not math.isfinite(s_max) or s_max <= 0.0:
        raise ValueError("Z 为零矩阵（σmax=0），源重构无定义，拒绝")
    return np.geomspace(s_max**2 * 1e-10, s_max**2, n_points)


def _identity_sweep(z: np.ndarray, b: np.ndarray, lambdas: np.ndarray) -> dict[str, object]:
    """L=I 快路径：一次经济型 SVD，任意 λ 的解/范数 O(k) 谱式给出。

    x_λ = V·diag(s/(s²+λ))·U^H b；‖r_λ‖² = ‖b‖² − ‖β‖² + Σ(λ/(s²+λ))²|β|²
    （β = U^H b；† 项为行空间外的投影残差，m>n 时为 0）。GCV trace 项 =
    Σ s²/(s²+λ)。
    """
    u, s, vh = np.linalg.svd(z, full_matrices=False)
    beta = u.conj().T @ b
    beta_sq = np.abs(beta) ** 2
    b_sq = float(np.vdot(b, b).real)
    lam = np.asarray(lambdas, dtype=float)[:, None]
    s2 = s[None, :] ** 2
    filt = s[None, :] / (s2 + lam)
    x_norms = np.sqrt(np.sum((filt**2) * beta_sq[None, :], axis=1))
    res_sq = b_sq - float(beta_sq.sum()) + np.sum(
        ((lam / (s2 + lam)) ** 2) * beta_sq[None, :], axis=1
    )
    res_sq = np.maximum(res_sq, 0.0)  # 浮点相消可为微负，截 0（平方量非负）
    trace_terms = np.sum(s2 / (s2 + lam), axis=1)
    return {
        "u": u,
        "s": s,
        "vh": vh,
        "beta": beta,
        "lambdas": np.asarray(lambdas, dtype=float),
        "x_norms": x_norms,
        "res_sq": res_sq,
        "trace_terms": trace_terms,
        "cond_z": float(s[0] / s[-1]) if s[-1] > 0.0 else math.inf,
    }


def _identity_solve_x(sweep: dict[str, object], lam: float) -> np.ndarray:
    s = np.asarray(sweep["s"])
    beta = np.asarray(sweep["beta"])
    filt = s / (s**2 + lam)
    return np.asarray(sweep["vh"]).conj().T @ (filt * beta)


def _diff_matrix(nsu: int, nsv: int) -> np.ndarray:
    """一阶差分正则算子 L 的稠密矩阵（见 _diff_operator 的行/列布局说明）。"""
    n = 4 * nsu * nsv
    n_rows = 4 * ((nsu - 1) * nsv + nsu * (nsv - 1))
    mat = np.zeros((n_rows, n), dtype=float)
    entries: list[tuple[int, int, float]] = []
    r = 0
    for ch in range(4):
        base = ch * nsu * nsv
        for i in range(nsu - 1):
            for j in range(nsv):
                entries.append((r, base + i * nsv + j, 1.0))
                entries.append((r, base + (i + 1) * nsv + j, -1.0))
                r += 1
        for i in range(nsu):
            for j in range(nsv - 1):
                entries.append((r, base + i * nsv + j, 1.0))
                entries.append((r, base + i * nsv + j + 1, -1.0))
                r += 1
    for rr_, cc_, vv_ in entries:
        mat[rr_, cc_] = vv_
    return mat


def _diff_sweep(
    z: np.ndarray, b: np.ndarray, lambdas: np.ndarray, l_mat: np.ndarray
) -> dict[str, object]:
    """L=一阶差分慢路径：逐 λ 法方程 Cholesky（O(N³)×|λ|，P1 限小网格）。

    GCV trace 项 = ‖L_chol⁻¹ Z^H‖²_F（exact：tr(Z·B⁻¹·Z^H)，
    B = Z^H Z + λ L^H L = L_chol·L_chol^H 的 Cholesky 分解）。
    """
    gram = z.conj().T @ z
    ztb = z.conj().T @ b
    lh_l = l_mat.conj().T @ l_mat
    lam_list = np.asarray(lambdas, dtype=float)
    x_norms = np.empty(lam_list.size, dtype=float)
    res_sq = np.empty(lam_list.size, dtype=float)
    trace_terms = np.empty(lam_list.size, dtype=float)
    for t, lam in enumerate(lam_list.tolist()):
        b_mat = gram + lam * lh_l
        chol = sla.cholesky(b_mat, lower=True)
        x = sla.cho_solve((chol, True), ztb)
        resid = z @ x - b
        x_norms[t] = float(np.linalg.norm(x))
        res_sq[t] = float(np.vdot(resid, resid).real)
        w = sla.solve_triangular(chol, z.conj().T, lower=True)
        trace_terms[t] = float(np.vdot(w, w).real)  # ‖W‖²_F（复数 vdot 自共轭内积）
    cond_z = float(np.linalg.norm(z, 2))
    s_min = float(np.linalg.svd(z, compute_uv=False)[-1])
    return {
        "lambdas": lam_list,
        "x_norms": x_norms,
        "res_sq": res_sq,
        "trace_terms": trace_terms,
        "cond_z": cond_z / s_min if s_min > 0.0 else math.inf,
        "_gram": gram,
        "_ztb": ztb,
        "_lh_l": lh_l,
    }


def _diff_solve_x(sweep: dict[str, object], lam: float) -> np.ndarray:
    gram = np.asarray(sweep["_gram"])
    lh_l = np.asarray(sweep["_lh_l"])
    ztb = np.asarray(sweep["_ztb"])
    chol = sla.cholesky(gram + lam * lh_l, lower=True)
    return sla.cho_solve((chol, True), ztb)


def sra_solve(
    z_matrix: np.ndarray,
    data: np.ndarray,
    *,
    n_src_u: int,
    n_src_v: int,
    operator: str = "identity",
    lambda_grid: np.ndarray | None = None,
    lambda_ratio_max: float = LAMBDA_RATIO_MAX_DEFAULT,
) -> dict[str, object]:
    """SRA 正则化求解核：给定 Z 与数据 b，返回 Tikhonov 解与 λ 双法判据。

    纯线性代数层（无量纲语义，单位解释在 solve_sra）：``operator="identity"``
    走 SVD 谱快路径；``operator="diff"`` 走逐 λ Cholesky（``n_src_u``×
    ``n_src_v`` 定义差分算子网格）。λ 网格缺省按 σmax² 对数栅（见
    ``_lambda_grid``），可显式传入覆盖。

    返回 dict：``x``（4N 复解向量，布局 [Jx;Jy;M̃x;M̃y] 逐点 C 序）、
    ``reg_lambda``、``method``、``reg_lambda_lcurve``、``reg_lambda_gcv``、
    ``residual_rel``、``cond_z``、``lambdas``/``x_norms``/``res_norms``
    （扫描面，L 曲线画图用）、``note``。
    """
    z = np.asarray(z_matrix)
    if z.ndim != 2 or z.shape[0] < 1 or z.shape[1] < 1:
        raise ValueError(f"z_matrix 必须是二维非空矩阵，得到 shape={z.shape}")
    if not np.all(np.isfinite(z)):
        raise ValueError("z_matrix 含 NaN/Inf，拒绝")
    b = np.asarray(data)
    if b.ndim != 1 or b.shape[0] != z.shape[0]:
        raise ValueError(f"data 必须是一维且长度 = Z 行数 {z.shape[0]}，得到 shape={b.shape}")
    if not np.all(np.isfinite(b)):
        raise ValueError("data 含 NaN/Inf，拒绝")
    if float(np.vdot(b, b).real) <= 0.0:
        raise ValueError("data 为零向量，源重构无定义（相对残差无意义），拒绝")
    nsu = _positive_int(n_src_u, "n_src_u")
    nsv = _positive_int(n_src_v, "n_src_v")
    if 4 * nsu * nsv != z.shape[1]:
        raise ValueError(
            f"n_src=({nsu},{nsv}) 与 Z 列数 {z.shape[1]} 不一致（应为 {4 * nsu * nsv}）"
        )
    op = _validate_operator(operator)
    ratio_max = _scalar_float(lambda_ratio_max, "lambda_ratio_max", minimum=1.0, allow_zero=True)

    n_lam = _N_LAMBDA_IDENTITY if op == "identity" else _N_LAMBDA_DIFF
    lams = (
        _as_real_vector(lambda_grid, "lambda_grid")
        if lambda_grid is not None
        else _lambda_grid(z, n_lam)
    )
    if np.any(lams < 0.0):
        raise ValueError("lambda_grid 含负值，拒绝")

    sweep = _identity_sweep(z, b, lams) if op == "identity" else _diff_sweep(
        z, b, lams, _diff_matrix(nsu, nsv)
    )
    lam_l = _l_curve_corner(np.asarray(sweep["lambdas"]), sweep["x_norms"], np.sqrt(np.asarray(sweep["res_sq"])))
    lam_g = _gcv_minimize(np.asarray(sweep["lambdas"]), sweep["res_sq"], int(z.shape[0]), sweep["trace_terms"])
    lam, method, note = _reconcile_lambda(lam_l, lam_g, ratio_max)
    if lam is None:
        lam = float(np.asarray(sweep["lambdas"])[len(sweep["lambdas"]) // 2])
        note = note + f"；无可判 λ，回退网格中位 {lam:.6g}（ok 判据为 False，不虚构可信解）"
    x = _identity_solve_x(sweep, lam) if op == "identity" else _diff_solve_x(sweep, lam)
    resid = z @ x - b
    res_rel = float(math.sqrt(float(np.vdot(resid, resid).real) / float(np.vdot(b, b).real)))
    return {
        "x": x,
        "reg_lambda": float(lam),
        "method": method,
        "reg_lambda_lcurve": lam_l,
        "reg_lambda_gcv": lam_g,
        "residual_rel": res_rel,
        "cond_z": float(sweep["cond_z"]),
        "lambdas": np.asarray(sweep["lambdas"]),
        "x_norms": np.asarray(sweep["x_norms"]),
        "res_norms": np.sqrt(np.asarray(sweep["res_sq"])),
        "note": note,
    }


# ─── 峰位质心细化（亚栅格定位估计器） ────────────────────────────────────────

def _locate_peak(power: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    """|map|² 加权质心细化峰位：离散 argmax 的 ±COM_HALF_WINDOW 邻窗质心。"""
    i0, j0 = np.unravel_index(int(np.argmax(power)), power.shape)
    i_lo, i_hi = max(i0 - COM_HALF_WINDOW, 0), min(i0 + COM_HALF_WINDOW + 1, power.shape[0])
    j_lo, j_hi = max(j0 - COM_HALF_WINDOW, 0), min(j0 + COM_HALF_WINDOW + 1, power.shape[1])
    win = power[i_lo:i_hi, j_lo:j_hi]
    w_sum = float(win.sum())
    if w_sum <= 0.0:
        return float(xs[i0]), float(ys[j0])
    wx = float((win.sum(axis=1) * xs[i_lo:i_hi]).sum())
    wy = float((win.sum(axis=0) * ys[j_lo:j_hi]).sum())
    return wx / w_sum, wy / w_sum


# ─── |k⊥| 带宽守卫（观测角谱 vs 源网格谱支撑） ───────────────────────────────

def _bandwidth_guard(
    fields: list[np.ndarray], du_obs: float, dv_obs: float, du_src: float, dv_src: float
) -> tuple[bool, float, str]:
    """观测数据角谱落入源网格谱支撑外的功率占比 > BANDWIDTH_FLOOR → 不通过。

    源网格谱支撑（矩形）：|kx| ≤ π/du_src 且 |ky| ≤ π/dv_src；超出部分是源
    网格**不可表示**的空间频率（离散化失配），如实声明 domain_ok=False。
    """
    kx = _TWO_PI * np.fft.fftfreq(fields[0].shape[0], d=du_obs)
    ky = _TWO_PI * np.fft.fftfreq(fields[0].shape[1], d=dv_obs)
    # 相对容差 1e-9：Nyquist 边缘 bin 的 |kx|=π/du 与边界比较对 ulp 敏感
    # （2π·fftfreq 与 π/du 的舍入差可把边缘 bin 甩到界外），容差只吸收该
    # 伪效应；真实超支撑内容（测试锚 du_obs < du_src）远超容差照常拦截。
    inside = (np.abs(kx) <= math.pi / du_src * (1.0 + 1e-9))[:, None] & (
        np.abs(ky) <= math.pi / dv_src * (1.0 + 1e-9)
    )[None, :]
    power = np.zeros(fields[0].shape, dtype=float)
    for fld in fields:
        power += np.abs(np.fft.fft2(fld)) ** 2
    total = float(power.sum())
    if total <= 0.0:
        return True, 0.0, "带宽守卫：数据谱功率为 0，无内容可查（通过）"
    frac_out = float(power[~inside].sum() / total)
    ok = frac_out <= BANDWIDTH_FLOOR
    note = (
        f"带宽守卫：观测角谱支撑外功率占比 {frac_out:.3g}"
        f"（源网格支撑 |kx|≤{math.pi / du_src:.4g}, |ky|≤{math.pi / dv_src:.4g} rad/m，"
        f"地板 {BANDWIDTH_FLOOR:g}）→ {'通过' if ok else '不通过'}"
    )
    return ok, frac_out, note


# ─── 主入口：观测场 → 源图 ───────────────────────────────────────────────────

def solve_sra(
    e_x: np.ndarray,
    e_y: np.ndarray,
    h_x: np.ndarray,
    h_y: np.ndarray,
    du_obs_m: float,
    dv_obs_m: float,
    d_m: float,
    f_hz: float,
    du_src_m: float,
    dv_src_m: float,
    n_src_u: int,
    n_src_v: int,
    *,
    operator: str = "identity",
    extent_ratio: float = EXTENT_RATIO_DEFAULT,
    cond_warn: float = COND_WARN_DEFAULT,
    residual_gate_db: float = RESIDUAL_GATE_DB_DEFAULT,
    lambda_grid: np.ndarray | None = None,
    lambda_ratio_max: float = LAMBDA_RATIO_MAX_DEFAULT,
) -> dict[str, object]:
    """近场切向场 → 等效源 |J|/|M| 热图 + 定位（SRA 主入口，规格 §C-1）。

    入参：观测面 z=d_m 的切向场 Ex/Ey/Hx/Hy（复二维 (n_obs_u, n_obs_v)，
    与 ``sra_operator`` 同一中心化网格配准，全 SI）；观测采样间距
    du/dv_obs_m；扫描距 d_m；频率 f_hz；源网格间距 du/dv_src_m 与点数
    n_src_u×n_src_v（z=0，中心对齐观测窗）。``operator`` = "identity"（L=I，
    SVD 快路径）或 "diff"（一阶差分，逐 λ Cholesky）。

    守卫行为：采样违反 λ/2 → ValueError 拒收（锚"du>λ/2 拒收"）；源面外扩
    不足 / 带宽超支撑 → domain_ok=False 如实继续；cond(Z)>cond_warn →
    cond_warning=True。

    返回 dict（键义见模块 docstring"输出 schema"节）：``j_map``（A/m）、
    ``m_map``（V/m）、``argmax_xy_m``（质心细化 [x,y]，m）、``reg_lambda``、
    ``method``、``cond_z``、``residual_db``、``domain_ok``、``ok``、
    ``cond_warning``、``extent_ok``、``bandwidth_ok``、
    ``argmax_j_xy_m``/``argmax_m_xy_m``（逐图质心细化，测试侧锚用）、
    ``reg_lambda_lcurve``/``reg_lambda_gcv``、``note``。
    """
    ex = _as_complex_2d(e_x, "e_x")
    ey = _as_complex_2d(e_y, "e_y")
    hx = _as_complex_2d(h_x, "h_x")
    hy = _as_complex_2d(h_y, "h_y")
    if not (ex.shape == ey.shape == hx.shape == hy.shape):
        raise ValueError(
            f"四个观测场形状必须一致，得到 e_x={ex.shape}, e_y={ey.shape}, "
            f"h_x={hx.shape}, h_y={hy.shape}"
        )
    duo = _scalar_float(du_obs_m, "du_obs_m", minimum=0.0, allow_zero=False)
    dvo = _scalar_float(dv_obs_m, "dv_obs_m", minimum=0.0, allow_zero=False)
    d = _scalar_float(d_m, "d_m", minimum=0.0, allow_zero=False)
    f = _scalar_float(f_hz, "f_hz", minimum=0.0, allow_zero=False)
    dus = _scalar_float(du_src_m, "du_src_m", minimum=0.0, allow_zero=False)
    dvs = _scalar_float(dv_src_m, "dv_src_m", minimum=0.0, allow_zero=False)
    ratio_max = _scalar_float(lambda_ratio_max, "lambda_ratio_max", minimum=1.0, allow_zero=True)

    op = sra_operator(
        dus,
        dvs,
        n_src_u,
        n_src_v,
        duo,
        dvo,
        ex.shape[0],
        ex.shape[1],
        d,
        f,
        extent_ratio=extent_ratio,
    )
    z = np.asarray(op["z_matrix"])
    eta0 = float(op["eta0"])

    # 守卫 3：观测角谱 vs 源网格谱支撑
    bw_ok, bw_frac, bw_note = _bandwidth_guard([ex, ey], duo, dvo, dus, dvs)

    # 数据装配：[Ex; Ey; η₀Hx; η₀Hy]（行序与算子一致，分量优先 C 序展平）
    b = np.concatenate([ex.reshape(-1), ey.reshape(-1), (eta0 * hx).reshape(-1), (eta0 * hy).reshape(-1)])

    sol = sra_solve(
        z,
        b,
        n_src_u=n_src_u,
        n_src_v=n_src_v,
        operator=operator,
        lambda_grid=lambda_grid,
        lambda_ratio_max=ratio_max,
    )
    x = np.asarray(sol["x"])
    nsu, nsv = int(n_src_u), int(n_src_v)
    chan = x.reshape(4, nsu, nsv)
    j_map = np.sqrt(np.abs(chan[0]) ** 2 + np.abs(chan[1]) ** 2) / (dus * dvs)
    m_map = eta0 * np.sqrt(np.abs(chan[2]) ** 2 + np.abs(chan[3]) ** 2) / (dus * dvs)
    power = j_map**2 + (m_map / eta0) ** 2
    if float(power.max()) <= 0.0:
        raise ValueError("反演源图为零（数据与算子失配），定位无定义，拒绝")

    src_x = np.asarray(op["src_x_m"])
    src_y = np.asarray(op["src_y_m"])
    loc_comb = _locate_peak(power, src_x, src_y)
    loc_j = _locate_peak(j_map**2, src_x, src_y)
    loc_m = _locate_peak(m_map**2, src_x, src_y)

    cond_z = float(sol["cond_z"])
    cond_warning = bool(cond_z > cond_warn)
    res_rel = float(sol["residual_rel"])
    residual_db = 20.0 * math.log10(res_rel) if res_rel > 0.0 else -math.inf
    domain_ok = bool(op["extent_ok"]) and bw_ok
    ok = bool(
        domain_ok
        and not cond_warning
        and sol["method"] != "undetermined"
        and residual_db <= residual_gate_db
    )

    note = (
        f"{op['note']}；{bw_note}；{sol['note']}；"
        f"cond_z={cond_z:.6g}（警示阈 {cond_warn:g}）→{'警示' if cond_warning else '正常'}；"
        f"残差 {residual_db:.2f} dB（门 {residual_gate_db:g}）；ok={ok}"
        f"（域 {domain_ok} ∧ cond {'OK' if not cond_warning else '警示'} ∧ "
        f"λ {sol['method']} ∧ 残差门）"
    )
    return {
        "j_map": j_map,
        "m_map": m_map,
        "argmax_xy_m": np.array(loc_comb, dtype=float),
        "reg_lambda": sol["reg_lambda"],
        "method": sol["method"],
        "cond_z": cond_z,
        "residual_db": residual_db,
        "domain_ok": domain_ok,
        "ok": ok,
        "cond_warning": cond_warning,
        "extent_ok": bool(op["extent_ok"]),
        "bandwidth_ok": bw_ok,
        "bandwidth_frac_out": bw_frac,
        "argmax_j_xy_m": np.array(loc_j, dtype=float),
        "argmax_m_xy_m": np.array(loc_m, dtype=float),
        "reg_lambda_lcurve": sol["reg_lambda_lcurve"],
        "reg_lambda_gcv": sol["reg_lambda_gcv"],
        "src_x_m": src_x,
        "src_y_m": src_y,
        "note": note,
    }
