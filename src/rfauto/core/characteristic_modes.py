"""CMA（Characteristic Mode Analysis，特征模分析）离线档内核：广义阻抗矩阵
Z = R + jX 的 R-加权特征模分解（ge6 Wave1，Ph5 池第十二轮 CMA 条目的
离线档；HFSS 原生 CMA 为 C 类仲裁登记，见
方案池 第十二轮与
研究扩充 round6 中件包一）。

数学口径（Harrington–Mautz 1971，"Computation of characteristic modes for
conducting bodies of arbitrary shape"；综述口径 Cabedo-Fabrés et al. 2007，
"Characteristic modes" 命名文献与 "On the physical meaning of
characteristic modes", IEEE Antennas Propag. Mag. 49(5)）：

- 特征对方程：X·I_n = λ_n·R·I_n——R 加权实对称广义特征值问题
  （R=Re Z 辐射实部、X=Im Z 储能虚部，均实对称），scipy.linalg.eigh 直解；
  λ_n 实数，按升序返回。
- 模 significance（功率口径，本档规格）：MS_n = 1/(1+λ_n²)∈(0,1]；
  文献更常见的幅值口径 |1/(1+jλ_n)| = 1/√(1+λ_n²) 以
  modal_significance_amplitude 同步给出（=sqrt(MS)），两口径零自由度换算。
- 特征电流：R-正交归一 I_m^T·R·I_n = δ_mn（eigh 对 SPD 右端阵的返回
  性质；返回复电流的虚部为零属该口径的常态——模电流方向由实对称
  算子决定，激励相位不在本档）。
- 特征阻抗（R 归一口径）：Z_cn = I_n^T·Z·I_n / I_n^T·R·I_n = 1 + j·λ_n；
  特征值问题对 Z→αZ 整体缩放不变（λ/MS/特征阻抗不变）；特征电流按
  eigh 的 B-归一口径 vᵀ·R·v=1 返回——α 缩放下电流幅值差 √α 因子
  （方向/形状不变，归一基准随 R 走；见 test_scale_invariance_z_alpha_z）。
- 模 Q（Cabedo-Fabrés 2007 §"Q factor" 口径，可选扫频件）：
  Q_n = (ω/2)·dλ_n/dω（R 归一后模电抗 X_nn = λ_n；串联 RLC 在谐振处
  回收 ω₀L/R 闭式，test_characteristic_modes 钉）。单频点 Z 无频率导数
  信息，模 Q 必须由扫频输入经 modal_q_sweep 计算。

诚实边界（#122 口径，docstring 声明不装）：
- 本模块不自带 MoM/EFIE——Z 矩阵由调用方提供（未来 MoM 导出、HFSS
  CMA 报告导出、散射法重建算子均可接；输入语义 JSON 嵌套 [re,im] 对）。
- 散射法扩展面：Capek 2023 TAP 散射 dyadic CMA（MIT 补充材料码四引擎
  验证）以 Lebedev 采样×平面波激励×nf2ff 从场响应重建 Z 算子后接本
  内核——重建层涉及 openEMS 通道复用（rotation 进程隔离），另行立项，
  不在本离线档。调研稿未给闭式 S→特征量换算（散射 CMA 需场采样而非
  端口 S 矩阵），故本档仅 Z 口径。
- R 非正定（非互易/损伤导出）与数值奇异显式 ValueError，不产出 NaN
  （#315/#316 多报方向）；恰半正定（min eig=0）不加地板、由 LAPACK
  非正定判定显式报错；噪声级负特征值（求积/舍入噪声）按 PSD 地板
  微抬并在结果 r_shift 字段留痕——奇异与噪声由此可分。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# PSD 地板：min_eig(R) 负得比此更深 → 显式报错；更浅 → 微抬（留痕）
_PSD_TOL_REL = 1e-10
_PSD_FLOOR_REL = 1e-12
# 近奇异噪声带（相对 max eig）：带内 min eig（任一号）→ 走 PSD 地板路径
_NEAR_SINGULAR_REL = 1e-8
# 对称性容差（相对矩阵尺度；互易结构导出对称，超容差=导出损伤）
_SYM_TOL_REL = 1e-8


@dataclass(frozen=True)
class CMAResult:
    """特征模分解结果（numpy 数组 + JSON 安全 to_dict）。

    属性：
        eigenvalues: λ_n，实数升序（shape (N,)）
        modal_significance: MS_n = 1/(1+λ_n²)（功率口径）
        modal_significance_amplitude: 1/√(1+λ_n²)（文献幅值口径 = √MS）
        currents: 特征电流矩阵（N×N 实数，列为 R-正交归一模电流）
        characteristic_impedance: Z_cn = 1 + jλ_n（R 归一口径，(N,) 复数）
        max_rel_residual: max_n |X v_n − λ_n R v_n| / ‖X + |λ_n|R‖（数值健康钉）
        r_shift: 求解前对 R 施加的 PSD 地板抬升量（0=未抬）
        n_modes: 模数 N
    """

    eigenvalues: np.ndarray
    modal_significance: np.ndarray
    modal_significance_amplitude: np.ndarray
    currents: np.ndarray
    characteristic_impedance: np.ndarray
    max_rel_residual: float
    r_shift: float
    n_modes: int

    def to_dict(self) -> dict[str, Any]:
        """JSON 安全快照（registry 计算器出口语义：嵌套列表、零 numpy 类型）。"""
        return {
            "n_modes": int(self.n_modes),
            "eigenvalues": [float(v) for v in self.eigenvalues],
            "modal_significance": [float(v) for v in self.modal_significance],
            "modal_significance_amplitude": [
                float(v) for v in self.modal_significance_amplitude],
            "currents": [[float(v) for v in row] for row in self.currents],
            "characteristic_impedance": [
                [float(v.real), float(v.imag)]
                for v in self.characteristic_impedance],
            "max_rel_residual": float(self.max_rel_residual),
            "r_shift": float(self.r_shift),
        }


def _as_real_symmetric(name: str, mat: np.ndarray, scale_ref: float,
                       sym_tol: float) -> np.ndarray:
    """方形/有限/对称校验 + 对称化（浮点导出的 ~1ulp 反对称吸收）。"""
    arr = np.asarray(mat, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"{name} 必须为方阵，收到 shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf（导出损伤），拒绝求解")
    asym = float(np.max(np.abs(arr - arr.T))) if arr.shape[0] else 0.0
    tol = sym_tol * max(scale_ref, 1.0)
    if asym > tol:
        raise ValueError(
            f"{name} 非对称（max|A−Aᵀ|={asym:.3e} > 容差 {tol:.3e}）："
            "特征模口径要求 R/X 实对称（互易结构导出应满足）；"
            "超容差按导出损伤显式拒绝，不静默对称化")
    return 0.5 * (arr + arr.T)


def parse_z_matrix(z: Any) -> np.ndarray:
    """Z 矩阵入参收敛（三形态显式判别，不做 numpy 复数折叠猜测）：

    - 复数 N×N ndarray：直接用；
    - (N,N,2) 实数对（JSON 嵌套 [re,im] 对 / npz 读出形态）：末轴折叠；
    - 全实数 N×N：虚部取零（2×2 实数方阵也按实矩阵解——本解析器不依赖
      numpy 的"末维 2 折叠为复数"语义，实矩阵与 [re,im] 对形态互斥可判）。

    npz/MoM 导出矩阵由调用方读入后按本语义传入（registry 计算器零 IO）。
    形状/有限性非法显式 ValueError。
    """
    raw = np.asarray(z)
    if np.iscomplexobj(raw):
        arr = np.asarray(raw, dtype=complex)
    elif raw.ndim == 3 and raw.shape[-1] == 2:
        arr = raw[..., 0].astype(float) + 1j * raw[..., 1].astype(float)
    elif raw.ndim == 2:
        arr = raw.astype(float) + 0j
    else:
        raise ValueError(
            f"z 必须为 N×N（复数/全实数方阵）或 (N,N,2) [re,im] 对形态，"
            f"收到 shape {raw.shape}")
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"z 必须为 N×N 方阵，收到 shape {arr.shape}")
    if arr.shape[0] < 1:
        raise ValueError("z 至少为 1×1")
    if not (np.all(np.isfinite(arr.real)) and np.all(np.isfinite(arr.imag))):
        raise ValueError("z 含 NaN/Inf（导出损伤），拒绝求解")
    return arr


def characteristic_modes(z: Any, *, sym_tol: float = _SYM_TOL_REL) -> CMAResult:
    """广义阻抗矩阵 Z = R + jX 的特征模分解（R 加权广义特征值问题）。

    入参：z 为 N×N 广义阻抗矩阵（嵌套 [re,im] 对 / 实数方阵 / 复 ndarray，
    语义见 parse_z_matrix）。sym_tol 为对称性相对容差。

    返回 CMAResult（λ 升序；口径与诚实边界见模块 docstring）。
    显式报错面：非方阵 / 含 NaN-Inf / 非对称超容差 / R 非正定（负特征值
    超 PSD 容差）/ R 零或负实部 / R 数值奇异（LinAlgError 翻译为
    ValueError）——全程不产出 NaN/Inf。
    """
    from scipy.linalg import LinAlgError, eigh

    zc = parse_z_matrix(z)
    n = zc.shape[0]
    scale = float(max(np.max(np.abs(zc.real)), np.max(np.abs(zc.imag)), 1.0))
    r_mat = _as_real_symmetric("R(=Re z)", zc.real, scale, sym_tol)
    x_mat = _as_real_symmetric("X(=Im z)", zc.imag, scale, sym_tol)

    # ── R 正定性守卫（eigh 右端阵必须 SPD；真奇异/非正定显式拒绝）────────
    # 契约（奇异与噪声可分，docstring 口径）：
    # - max eig ≤ 0（全零/负）→ 显式拒绝（无辐射/全零导出）；
    # - min eig < −tol·max（非正定）→ 显式拒绝（非互易/有源/损伤导出）；
    # - min eig == 0 恰零 → 显式拒绝（结构性半正定退化，如 rank-1 导出；
    #   LAPACK 对恰零也必失败或产垃圾，不静默）；
    # - min eig 落在 ±噪声带（|min| < 1e-8·max，求积/舍入噪声，全场 MoM
    #   导出常态）→ PSD 地板微抬（留痕 r_shift），物理模不受扰（地板比
    #   最小物理特征值低 ≥3 个量级）。
    r_eigs = np.linalg.eigvalsh(r_mat)
    r_min = float(r_eigs.min())
    r_max = float(r_eigs.max())
    if r_max <= 0.0:
        raise ValueError(
            f"R（辐射实部）无正特征值（max eig={r_max:.3e}）："
            "无辐射结构或全零导出，特征模问题退化，显式拒绝")
    if r_min < -_PSD_TOL_REL * r_max:
        raise ValueError(
            f"R 非正定（min eig={r_min:.3e} < −{_PSD_TOL_REL:g}·max eig）："
            "特征模口径要求辐射实部半正定；非互易/有源/损伤导出显式拒绝")
    if r_min == 0.0:
        raise ValueError(
            "R 含恰零特征值（结构性半正定退化，如秩亏导出）：特征模问题"
            "奇异，显式拒绝；数值噪声请由导出方清理或走 PSD 地板路径")
    r_shift = 0.0
    if r_min < _NEAR_SINGULAR_REL * r_max:
        # 噪声带：负值抬到正、正噪声抬离 1 ulp 边界（两种都留痕）
        r_shift = max(-r_min, 0.0) + _PSD_FLOOR_REL * r_max
    try:
        eigenvalues, currents = eigh(x_mat, r_mat + r_shift * np.eye(n))
    except LinAlgError as exc:  # 守卫带外仍数值奇异（近零秩边缘）
        raise ValueError(
            f"R 数值奇异（特征分解失败：{exc}）：退化输入显式拒绝，不产出 NaN"
        ) from exc

    eigenvalues = np.asarray(eigenvalues, dtype=float)
    if not np.all(np.isfinite(eigenvalues)):
        raise ValueError("特征值含非有限值（R 病态超出浮点可解域），显式拒绝")
    currents = np.asarray(currents, dtype=float)

    # 数值健康钉：逐模相对残差 max|X v_n − λ_n·R_s·v_n| / ((‖X‖₂+|λ_n|‖R_s‖₂)·
    # max(1,‖v_n‖))，R_s = R + r_shift·I 为实际求解算子（留痕口径：r_shift>0
    # 时残差按求解算子计，物理模对原 R 的偏差同阶于地板值，见模块 docstring）
    r_solved = r_mat + r_shift * np.eye(n)
    scale_r = float(np.linalg.norm(r_solved, 2))
    scale_x = float(np.linalg.norm(x_mat, 2))
    raw = np.abs(x_mat @ currents
                 - (r_solved @ currents) * eigenvalues[np.newaxis, :])
    v_norm = np.maximum(np.linalg.norm(currents, axis=0), 1.0)
    denom = np.maximum(
        (scale_x + np.abs(eigenvalues) * scale_r) * v_norm, 1e-300)
    residual = float(np.max(raw / denom[np.newaxis, :]))

    ms = 1.0 / (1.0 + eigenvalues**2)
    return CMAResult(
        eigenvalues=eigenvalues,
        modal_significance=ms,
        modal_significance_amplitude=np.sqrt(ms),
        currents=currents,
        characteristic_impedance=1.0 + 1j * eigenvalues,
        max_rel_residual=residual,
        r_shift=float(r_shift),
        n_modes=int(n),
    )


def modal_q_sweep(omegas: Any, z_list: Any) -> np.ndarray:
    """扫频模 Q（Cabedo-Fabrés 2007 口径）：Q_n(ω_i) = (ω_i/2)·dλ_n/dω。

    入参：omegas 一维角频率序列（单位任意但须自洽，单调），z_list 等长
    的 Z 矩阵序列（每项语义同 characteristic_modes 的 z）。dλ/dω 取中心
    差分（端点单侧差分）。

    返回 (len(omegas), N) 实数数组；模对齐按各频点 λ 升序（模次序跨频
    缓变时成立——密扫频+良分模；强交叉/模跟踪属扩展面，本档不做）。
    """
    om = np.asarray(omegas, dtype=float)
    if om.ndim != 1 or om.size < 3:
        raise ValueError("omegas 须为一维且 ≥3 点（中心差分需要）")
    if not np.all(np.isfinite(om)) or np.any(np.diff(om) <= 0):
        raise ValueError("omegas 须严格单调递增且有限")
    if len(z_list) != om.size:
        raise ValueError(
            f"z_list 长度 {len(z_list)} != omegas 点数 {om.size}")
    lam = np.stack([
        characteristic_modes(z).eigenvalues for z in z_list])  # (F, N)
    dq = np.empty_like(lam)
    dq[1:-1] = (lam[2:] - lam[:-2]) / (om[2:] - om[:-2])[:, np.newaxis]
    dq[0] = (lam[1] - lam[0]) / (om[1] - om[0])
    dq[-1] = (lam[-1] - lam[-2]) / (om[-1] - om[-2])
    return (om[:, np.newaxis] / 2.0) * dq
