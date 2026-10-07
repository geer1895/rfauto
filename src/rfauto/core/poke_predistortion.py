"""M-2.2 阵列测量闭环·互耦预失真核：poke 交互矩阵 SVD 谱面 + Tikhonov 伪逆权重。

谱系与口径（机制借镜 + 纯 numpy 自实现；零依赖引入，#118 来源写 docstring）
========
- 自适应光学（AO）交互矩阵法：标定时对执行器 k 施加单位 poke、测量全部
  传感器响应，得交互矩阵 ``H[i, k]``；控制/预失真权重 = 伪逆
  ``w = H⁺ e_target``；SVD 谱 = 病态方向诊断（可矫正子空间 = σ > floor·σ_max
  的计数）。谱系出处为 AO 整定实践（如 Hardy《Adaptive Optics for
  Astronomical Telescopes》交互矩阵标定章；Roddier《Adaptive Optics in
  Astronomy》同族）——**论文原文未逐篇另核页码，如实标注**；公式本身
  （SVD/Tikhonov）以数值线性代数标准定义为准，由本模块单测用独立代数
  路径（np.linalg.solve 直解、SVD 恒等式、λ 单调性解析式）互证，不自证。
- 本仓契约对齐：``service/array_service.collect_eep_manifest`` 的互耦档
  编排（激励元 k 单激励 run → 全元响应列）**天然就是 poke 协议**——
  第 k 次单激励的全元复响应 = ``H[:, k]``（EEP farfield3d_cplx.csv 或
  全 S 矩阵轮列 sparams.csv，掩码载体优先 #314），即
  ``S[i, k]`` = 元 i 对元 k 激励的响应。本模块只消费**已装配好的 H 数组**，
  零 IO、不读 run 目录（装配面在 array_service，分层铁律 3）。

物理模型（不虚构）
========
- ``H``：shape ``(n_resp, n_exc)`` 复数——列 k = 激励元 k 单独激励时全部
  响应元的复响应；方阵（n_exc == n_resp）是互耦档案的常态，非方阵允许
  （激励/响应异维，伪逆口径）。
- 预失真：目标有效激励 ``e_target``（长度 n_resp）→ 端口激励权重
  ``w = H⁺ e_target``，使矫正后有效响应 ``H @ w ≈ e_target``；
  Tikhonov 正则 ``H⁺_λ = (H^H H + λI)⁻¹ H^H``（λ > 0 抑病态放大；
  λ = 0 走 SVD 最小范数伪 ``np.linalg.pinv`` 分支，秩亏时是最小范数解
  而非精确反解，pinv 缺省 rcond 如实沿用）。SVD 域逐分量
  ``w_i(λ) = σ_i (u_i^H e) / (σ_i² + λ)``——|w_i| 随 λ 单调不增、残差
  |r_i| = λ|u_i^H e|/(σ_i²+λ) 随 λ 单调不减（单测以解析单调性数组断言）。
- 波束验证面（判据②）：矫正前（端口直接馈 e_target，实际元激励
  ``H @ e_target``）vs 矩阵矫正后（馈 w，实际元激励 ``H @ w``）的阵列
  因子对比；复权重 AF 复用 :func:`rfauto.core.array_synthesis.array_factor`
  （复权重零和守卫的公共旋转 e^{-jπ/4} 拆 Re/Im 旁路 + Σw≈0 直算兜底，
  van_atta 批登记同款，见 :func:`_af_complex` docstring）。

边界（如实登记，预声明先写后跑）
========
- 本模块是**矩阵代数核**：不产任何真实器件的物理数字（互耦 H 由测量/
  仿真装配面供给）；判据主口径 = 合成注入回收（已知 H_true → 回收 w 与
  直解逐位一致）。
- λ=0 + 满秩方阵时回收才是精确反解；秩亏/病态（Hilbert 族）时谱面如实
  报病态（cond、可矫正维数），预失真走正则分支并报告残差，不虚构"矫正
  成功"。
- 数值 0.0 合法（判缺失一律 ``is not None``，#364④）；bool/NaN/Inf/零
  矩阵/零目标/λ<0 一律 ValueError（df7+⑯ bool 拒收）。
- 纯 numpy、零 IO、不进 calculators 注册表；JSON 序列化经
  :meth:`PokeSpectrum.to_dict`（非有限值折 None），ndarray 字段本身由
  调用方负责。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from rfauto.core.array_synthesis import array_factor, peak_sidelobe_level_db

__all__ = [
    "PokeSpectrum",
    "beam_predistortion_report",
    "interaction_spectrum",
    "predistortion_weights",
    "tikhonov_sweep",
]

#: 复权重拆分的公共旋转 e^{-jπ/4}（van_atta 同款）：旋转后 ΣRe = ΣIm =
#: |Σw|/√2，双部件同时离开 array_factor 零和守卫；全局相位乘回复原。
_SPLIT_ROTATION = np.exp(-1j * math.pi / 4.0)
#: 零和判定阈（与 array_synthesis._validate_weights 拒收阈同量级）
_ZERO_SUM_TOL = 1e-12
#: 波束报告缺省方向余弦网格点数
_DEFAULT_U_POINTS = 4001


def _as_complex_matrix(x: object, name: str) -> np.ndarray:
    """校验并转换为二维复数矩阵；bool/非数值/非二维/NaN/Inf 拒收。"""
    arr = np.asarray(x)
    if arr.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，拒绝（数值入参不得含 bool）")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值数组，得到 dtype={arr.dtype}")
    arr = arr.astype(complex)
    if arr.ndim != 2:
        raise ValueError(f"{name} 形状必须是二维 (n_resp, n_exc)，得到 ndim={arr.ndim}")
    if arr.shape[0] < 1 or arr.shape[1] < 1:
        raise ValueError(f"{name} 至少为 1x1，得到 shape={arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf，拒绝")
    return arr


def _as_complex_vector(x: object, name: str) -> np.ndarray:
    """校验并转换为一维复数向量；bool/非数值/非一维/NaN/Inf 拒收。"""
    arr = np.asarray(x)
    if arr.dtype == bool:
        raise ValueError(f"{name} 为 bool 数组，拒绝（数值入参不得含 bool）")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"{name} 必须是数值数组，得到 dtype={arr.dtype}")
    arr = arr.astype(complex)
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维向量，得到 ndim={arr.ndim}")
    if arr.shape[0] < 1:
        raise ValueError(f"{name} 不能为空向量")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 含 NaN/Inf，拒绝")
    return arr


def _finite(value: object, name: str) -> float:
    """入参收敛为有限 float；bool 显式拒收（float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受 bool")
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，得到 {type(value).__name__}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，得到 {value!r}")
    return out


def _nonnegative(value: object, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >= 0，得到 {out!r}")
    return out


def _af_complex(u_grid: np.ndarray, w: np.ndarray, spacing_lambda: float) -> np.ndarray:
    """复权重阵因子（array_factor 复用 + 零和守卫旁路，van_atta 批登记同款）。

    首选：权重乘公共旋转 e^{-jπ/4} 后拆 Re/Im 两次**实权重**调用（线性性：
    AF(w) = e^{+jπ/4}·[AF(Re) + j·AF(Im)]，normalize=False 保持绝对标度）——
    array_synthesis._validate_weights 以 dtype=float 收权重并对 Σw=0 拒收
    （该守卫为 normalize 语义设），复权重直接传入会被 dtype=float 静默丢
    虚部，故必须经本旁路。旋转使 ΣRe = ΣIm = |Σw|/√2；Σw ≈ 0 的
    Dirichlet 零点方向旋转救不了，走同核直算兜底
    （Σ w_n·e^{j2πd·u·n}，与 array_factor 同式，仅全局相位约定差）。
    """
    u_arr = np.asarray(u_grid, dtype=float)
    wr = w * _SPLIT_ROTATION
    if (
        abs(float(wr.real.sum())) > _ZERO_SUM_TOL
        and abs(float(wr.imag.sum())) > _ZERO_SUM_TOL
    ):
        af = array_factor(
            u_arr,
            wr.real,
            spacing_lambda=spacing_lambda,
            scan_direction_cosine=0.0,
            normalize=False,
        )
        af = af + 1j * array_factor(
            u_arr,
            wr.imag,
            spacing_lambda=spacing_lambda,
            scan_direction_cosine=0.0,
            normalize=False,
        )
        return af * np.conj(_SPLIT_ROTATION)
    idx = np.arange(w.size, dtype=float)
    kernel = np.exp(1j * 2.0 * np.pi * spacing_lambda * np.outer(idx, u_arr))
    return w @ kernel


@dataclass(frozen=True)
class PokeSpectrum:
    """poke 交互矩阵 SVD 谱面（不可变；ndarray 字段由调用方序列化）。

    singular_values / singular_values_db 为 ndarray（JSON 序列化经
    :meth:`to_dict`，非有限值折 None，判缺失 ``is not None``）。
    """

    n_resp: int
    n_exc: int
    singular_values: np.ndarray
    singular_values_db: np.ndarray
    condition_number: float
    correctable_dims: int
    sigma_floor: float

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（ndarray → list；±inf/NaN 折 None）。"""

        def _json_float_list(arr: np.ndarray) -> list[float | None]:
            return [float(v) if math.isfinite(float(v)) else None for v in arr.tolist()]

        cond_json: float | None = (
            float(self.condition_number) if math.isfinite(self.condition_number) else None
        )
        return {
            "n_resp": self.n_resp,
            "n_exc": self.n_exc,
            "singular_values": _json_float_list(self.singular_values),
            "singular_values_db": _json_float_list(self.singular_values_db),
            "condition_number": cond_json,
            "correctable_dims": self.correctable_dims,
            "sigma_floor": self.sigma_floor,
        }


def interaction_spectrum(
    H: np.ndarray, *, sigma_floor: float = 1e-3, cond_max: float | None = None
) -> PokeSpectrum:
    """poke 交互矩阵 SVD 谱面：奇异值谱（dB）、cond、可矫正子空间维数。

    H = U Σ V^H（经济型 SVD）；奇异值谱取 ``20·log10(σ_i/σ_max)``（dB，
    首元恒 0.0）；cond = σ_max/σ_min（含零奇异值 → cond = ∞）；可矫正
    子空间维数 = 严格 ``σ_i > sigma_floor·σ_max`` 的计数（比较用严格 >，
    阈值恰等不入——#283 同口径）。

    Parameters
    ----------
    H : ndarray (n_resp, n_exc) 复数
        poke 交互矩阵（列 k = 激励元 k 单激励的全元响应，collect_eep_manifest
        契约对齐见模块 docstring）；非方阵允许；零矩阵拒收（cond 无定义）。
    sigma_floor : float
        可矫正判据下限（σ_max 的相对值），须 0 < floor ≤ 1。
    cond_max : float or None
        病态守卫（opt-in）：给出且 cond 超限 → ValueError（调用方据此拒绝
        无正则化的预失真，转 Tikhonov 分支）。

    Returns
    -------
    PokeSpectrum
    """
    mat = _as_complex_matrix(H, "H")
    if np.all(mat == 0):
        raise ValueError("H 为零矩阵，SVD 谱/cond 无定义，拒绝")
    floor = _finite(sigma_floor, "sigma_floor")
    if not 0.0 < floor <= 1.0:
        raise ValueError(f"sigma_floor 须落在 (0, 1]，得到 {floor!r}")
    s_vals = np.linalg.svd(mat, compute_uv=False)  # 降序
    smax = float(s_vals[0])
    smin = float(s_vals[-1])
    cond = math.inf if smin <= 0.0 else smax / smin
    if cond_max is not None:
        guard = _finite(cond_max, "cond_max")
        if guard <= 0.0:
            raise ValueError(f"cond_max 必须 > 0，得到 {guard!r}")
        if cond > guard:
            raise ValueError(
                f"H 病态：cond={cond:.6g} 超过守卫 cond_max={guard:.6g}"
                "（如实拒绝，转 Tikhonov 正则分支）"
            )
    dims = int(np.count_nonzero(s_vals > floor * smax))
    # 零奇异值的 -inf dB 如实保留（to_dict 折 None），不截断不伪造
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(s_vals / smax)
    return PokeSpectrum(
        n_resp=int(mat.shape[0]),
        n_exc=int(mat.shape[1]),
        singular_values=s_vals,
        singular_values_db=db,
        condition_number=float(cond),
        correctable_dims=dims,
        sigma_floor=floor,
    )


def predistortion_weights(
    H: np.ndarray, e_target: np.ndarray, *, reg_lambda: float = 0.0
) -> dict:
    """Tikhonov 伪逆预失真权重：w = (H^H H + λI)⁻¹ H^H e_target。

    λ = 0 走 SVD 最小范数伪逆分支（``np.linalg.pinv(H) @ e``，秩亏时是最
    小范数解而非精确反解）；λ > 0 走显式 Tikhonov 法方程（Hermitian 正定，
    np.linalg.solve 直解）。矫正后有效响应 ``H @ w`` 对 e_target 的残差
    随结果一并返回（判据②口径）。

    Returns
    -------
    dict with keys:
        weights : ndarray (n_exc,) 复数——端口预失真权重；
        effective : ndarray (n_resp,) 复数——矫正后有效响应 H @ w；
        residual : ndarray (n_resp,) 复数——e_target − H @ w；
        residual_rms : float——rms|residual|（绝对）；
        residual_rel : float——rms|residual| / rms|e_target|；
        weights_norm : float——‖w‖₂（λ 单调性裁判量）；
        reg_lambda : float——生效正则强度。
    """
    mat = _as_complex_matrix(H, "H")
    if np.all(mat == 0):
        raise ValueError("H 为零矩阵，预失真权重无定义，拒绝")
    target = _as_complex_vector(e_target, "e_target")
    if target.shape[0] != mat.shape[0]:
        raise ValueError(
            f"e_target 长度 {target.shape[0]} 与 H 行数（响应元数）{mat.shape[0]} 不一致"
        )
    lam = _nonnegative(reg_lambda, "reg_lambda")
    if np.all(target == 0):
        raise ValueError("e_target 为零向量，预失真目标无意义（相对残差无定义），拒绝")
    if lam == 0.0:
        weights = np.linalg.pinv(mat) @ target
    else:
        gram = mat.conj().T @ mat
        weights = np.linalg.solve(gram + lam * np.eye(mat.shape[1]), mat.conj().T @ target)
    effective = mat @ weights
    residual = target - effective
    tgt_rms = float(np.sqrt(np.mean(np.abs(target) ** 2)))
    residual_rms = float(np.sqrt(np.mean(np.abs(residual) ** 2)))
    return {
        "weights": weights,
        "effective": effective,
        "residual": residual,
        "residual_rms": residual_rms,
        "residual_rel": residual_rms / tgt_rms,
        "weights_norm": float(np.linalg.norm(weights)),
        "reg_lambda": lam,
    }


def tikhonov_sweep(
    H: np.ndarray, e_target: np.ndarray, lambdas: np.ndarray
) -> dict:
    """λ 扫描：每个 λ 的 ‖w‖ 与相对残差（单调性裁判面）。

    SVD 域逐分量解析单调性：|w_i(λ)| = σ_i|u_i^H e|/(σ_i²+λ) 随 λ 单调
    不增、|r_i(λ)| = λ|u_i^H e|/(σ_i²+λ) 单调不减——本函数只做数值产出，
    单调性断言在单测（判据 #122 先行）。

    Returns
    -------
    dict with keys:
        lambdas : ndarray (K,)——生效 λ 序列（升序输入原样返回）；
        weights_norm : ndarray (K,)——每 λ 的 ‖w‖₂；
        residual_rel : ndarray (K,)——每 λ 的 rms|residual|/rms|e_target|。
    """
    arr = np.asarray(lambdas)
    if arr.dtype == bool:
        raise ValueError("lambdas 为 bool 数组，拒绝")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"lambdas 必须是数值数组，得到 dtype={arr.dtype}")
    if np.issubdtype(arr.dtype, np.complexfloating):
        raise ValueError("lambdas 必须为实数序列（复数 λ 无定义，拒绝静默丢虚部）")
    lam_arr = arr.astype(float).reshape(-1)
    if lam_arr.size < 1:
        raise ValueError("lambdas 不能为空序列")
    if not np.all(np.isfinite(lam_arr)):
        raise ValueError("lambdas 含 NaN/Inf，拒绝")
    if np.any(lam_arr < 0.0):
        raise ValueError("lambdas 含负值，拒绝")
    norms = np.empty(lam_arr.shape[0], dtype=float)
    rels = np.empty(lam_arr.shape[0], dtype=float)
    for k, lam in enumerate(lam_arr.tolist()):
        out = predistortion_weights(H, e_target, reg_lambda=lam)
        norms[k] = out["weights_norm"]
        rels[k] = out["residual_rel"]
    return {"lambdas": lam_arr, "weights_norm": norms, "residual_rel": rels}


def beam_predistortion_report(
    H: np.ndarray,
    e_target: np.ndarray,
    *,
    u_grid: np.ndarray | None = None,
    spacing_lambda: float = 0.5,
    reg_lambda: float = 0.0,
) -> dict:
    """合成波束验证面（判据②）：矫正前 vs 矩阵矫正后的方向图对比报告。

    矫正前 = 端口直接馈 e_target（实际元激励 ``H @ e_target``，互耦畸变
    未预失真）；矫正后 = 端口馈 ``w = H⁺ e``（实际元激励 ``H @ w``）。
    各方向图按自身峰值归一后与理想方向图（AF(e_target)）比 rms 误差；
    峰值方向 argmax|AF| 与峰值副瓣电平（复用
    :func:`rfauto.core.array_synthesis.peak_sidelobe_level_db`）三口径
    （理想/前/后）并列报告，改善布尔量如实给出（不虚构"必然改善"）。

    Returns
    -------
    dict with keys（全部 JSON 可序列化；-inf 副瓣折 None，判缺失 is not None）:
        before/after/ideal 的 peak_u、psl_db、pattern_error_rms，及
        peak_direction_improved / psl_improved / residual_rel。
    """
    mat = _as_complex_matrix(H, "H")
    if np.all(mat == 0):
        raise ValueError("H 为零矩阵，波束验证面无定义，拒绝")
    target = _as_complex_vector(e_target, "e_target")
    if target.shape[0] != mat.shape[0]:
        raise ValueError(
            f"e_target 长度 {target.shape[0]} 与 H 行数（响应元数）{mat.shape[0]} 不一致"
        )
    if np.all(target == 0):
        raise ValueError("e_target 为零向量，方向图无定义，拒绝")
    spacing = float(spacing_lambda)
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise ValueError(f"spacing_lambda 必须为正有限值，得到 {spacing_lambda!r}")
    if u_grid is None:
        u_arr = np.linspace(-1.0, 1.0, _DEFAULT_U_POINTS)
    else:
        u_arr = np.asarray(u_grid, dtype=float)
        if u_arr.ndim != 1 or u_arr.size < 3:
            raise ValueError("u_grid 须为一维且至少 3 点（副瓣定位前提）")
        if not np.all(np.isfinite(u_arr)):
            raise ValueError("u_grid 含 NaN/Inf，拒绝")

    pred = predistortion_weights(mat, target, reg_lambda=reg_lambda)
    weights = pred["weights"]
    af_ideal = _af_complex(u_arr, target, spacing)
    af_before = _af_complex(u_arr, mat @ target, spacing)
    # 矫正后的**实际元激励**是 H @ w（端口馈 w，经互耦映射），非端口权重本身
    af_after = _af_complex(u_arr, mat @ weights, spacing)

    def _norm(af: np.ndarray) -> np.ndarray:
        peak = float(np.max(np.abs(af)))
        if peak <= 0.0:
            raise ValueError("方向图峰值为 0，无法归一化")
        return af / peak

    ideal_n = _norm(af_ideal)
    ideal_rms = float(np.sqrt(np.mean(np.abs(ideal_n) ** 2)))

    def _psl(af: np.ndarray) -> float | None:
        val = peak_sidelobe_level_db(np.abs(af), u_arr, main_lobe_direction_cosine=0.0)
        return float(val) if math.isfinite(val) else None

    def _metrics(af: np.ndarray) -> dict:
        af_n = _norm(af)
        err = float(np.sqrt(np.mean(np.abs(af_n - ideal_n) ** 2)) / ideal_rms)
        return {
            "peak_u": float(u_arr[int(np.argmax(np.abs(af_n)))]),
            "psl_db": _psl(af_n),
            "pattern_error_rms": err,
        }

    before = _metrics(af_before)
    after = _metrics(af_after)
    ideal = {
        "peak_u": float(u_arr[int(np.argmax(np.abs(ideal_n)))]),
        "psl_db": _psl(ideal_n),
        "pattern_error_rms": 0.0,
    }
    # 副瓣改善布尔量：任一图案无副瓣（PSL 缺失 None）时如实不可比（None）
    psl_improved: bool | None = None
    if (
        after["psl_db"] is not None
        and before["psl_db"] is not None
        and ideal["psl_db"] is not None
    ):
        psl_improved = bool(
            abs(after["psl_db"] - ideal["psl_db"]) <= abs(before["psl_db"] - ideal["psl_db"])
        )
    # 峰位改善：argmax 在平顶主瓣上是 O(Δu) 网格分辨率歧义量（#298 同族——
    # 机器噪声即可使 argmax 在顶邻格间翻转），判等带 1 格容差，不虚构精确峰位
    du = float(u_arr[1] - u_arr[0]) if u_arr.size > 1 else 0.0
    return {
        "n_points": int(u_arr.size),
        "spacing_lambda": spacing,
        "reg_lambda": float(pred["reg_lambda"]),
        "residual_rel": float(pred["residual_rel"]),
        "ideal": ideal,
        "before": before,
        "after": after,
        "peak_direction_improved": bool(
            abs(after["peak_u"] - ideal["peak_u"])
            <= abs(before["peak_u"] - ideal["peak_u"]) + du
        ),
        "psl_improved": psl_improved,
    }
