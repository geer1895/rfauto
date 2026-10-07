"""ME-22 阵列误差注入测试床：逐元幅相误差注入 → 方向图退化生成器 + 校准闭环对拍。

定位（月度增强方案 §三 J 流 ME-22）
========
M-2 在线校准（:mod:`rfauto.core.array_calib`，firstcal/logcal/lincal 已落地）
的**确定性测试床**：注入已知逐元幅相误差 → 生成退化方向图 / 构造观测可见度
→ 用 array_calib 回收 → 闭环对拍（recovery_err 即 M-2 消费面的回归锚）。
纯 numpy、零 IO、不进注册表（core 隔离件，同 array_calib 口径）。

误差模型与权威口径
========
- 逐元幅相误差（He 2021 激励误差校准综述口径——任务书指定，单源如实标注；
  同形于 Mailloux《Phased Array Antenna Handbook》公开章节的标准误差模型）：
  ``g_i = |g_i|·exp(j·δφ_i)``；幅度取 dB 域零均值高斯 = 线性域**对数正态**
  （中位数 1）：``|g_i| = 10^(X_i/20)，X_i ~ N(0, amp_sigma_db²)``；
  相位 ``δφ_i ~ N(0, phase_sigma_deg²)``；元失效为硬注入 ``g_k = 0``。
  综述中的位置误差 Δr_i 项 v1 **不做**（位置由调用方经 pos_lambda 显式给出，
  等价"位置精确已知"）——如实标注，留 v2。
- 退化统计闭式（独立推导，#118 口径：解析式与 Monte Carlo 实现互为独立
  裁判；量级与 Mailloux "σ²/N" 经典口径一致）。对

  ``E[|AF(θ)|²] = N·E[|g|²] + |E[g]|²·(|AF_0(θ)|² − N)``

  （逐项展开见 tests/unit/test_array_error_injection.py 模块文档）有：

  * 逐角误差功率地板（对理想峰值归一）：``(E[|g|²] − |E[g]|²)/N``，其中
    ``E[|g|²] = exp(2σ_a'²)``、``|E[g]|² = exp(σ_a'² − σ_φ²)``、
    ``σ_a' = ln(10)·amp_sigma_db/20``；小误差极限 ≈ (σ_a'² + σ_φ²)/N；
  * 平均峰值增益（归一）：``(E[|g|²] + (N−1)·|E[g]|²)/N``，纯相位小误差
    ≈ 1 − σ_φ²·(1−1/N)（与 "gain loss ≈ exp(−σ_φ²)" 经典式同族）。
- 元失效几何闭式：均匀阵失效 k 元（无幅相误差）时主峰 = N−k 严格成立
  （|AF| ≤ N−k 三角不等式 + 残余元广侧同相），峰损 = 20·log10((N−k)/N)
  ≈ −8.686·k/N dB——"1/N dB 量级"的精确来源。

方向图约定
========
- ``AF(θ) = Σ_i g_i·E_i(θ)·exp(j·2π·(x_i·sinθ + z_i·cosθ))``：φ=0 平面切面，
  x 轴线阵 u = sinθ（与 array_synthesis.direction_cosine 的 x 轴约定一致）；
  pos_lambda 形状 (n_ant,) 按 x 轴线阵解读，(n_ant, 3) 为通用位置（y 分量
  在 φ=0 切面不进入相位）。
- pos_lambda 以**波长为单位** ⇒ AF 对频率尺度不变：f_ghz 不进入 AF 数学
  （如实标注，不虚构频率依赖），仅校验合法性并转发给 element_pattern。
- element_pattern：可选 ``f(theta_deg, f_ghz) -> complex``（按角度广播），
  缺省 None = 全向；方向图积定理口径（乘性）。
- 未归一化复 AF（理想侧射峰值 = N）；归一与指标在 degradation_metrics。

守卫
========
数值入参显式拒收 bool/NaN/Inf（df7+⑯）；sigma 非负有限；dead 索引整数、
界内、无重复；theta_deg（指标面）一维严格递增。接线（service/CLI/MCP）
留后续批次，本模块只读消费 array_calib。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from rfauto.core.array_calib import lincal_gain_solve, redundant_group_degeneracy

__all__ = [
    "array_factor_with_errors",
    "calibration_roundtrip",
    "degradation_metrics",
    "ideal_array_factor",
    "inject_errors",
]

_TWO_PI = 2.0 * np.pi


# ─── 入参校验 ──────────────────────────────────────────────────────────────────


def _reject_bool(value: object, name: str) -> None:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 是 bool，拒绝（数值入参不得含 bool）")


def _as_positive_int(value: object, name: str) -> int:
    _reject_bool(value, name)
    if not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} 必须是整数，得到 {type(value).__name__}")
    iv = int(value)
    if iv < 1:
        raise ValueError(f"{name} 必须是正整数，得到 {value!r}")
    return iv


def _as_nonneg_float(value: object, name: str, *, positive: bool = False) -> float:
    _reject_bool(value, name)
    if not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"{name} 必须是实数标量，得到 {type(value).__name__}")
    fv = float(value)
    if not np.isfinite(fv):
        raise ValueError(f"{name} 必须有限，得到 {value!r}")
    if positive and fv <= 0.0:
        raise ValueError(f"{name} 必须为正，得到 {fv!r}")
    if not positive and fv < 0.0:
        raise ValueError(f"{name} 必须非负，得到 {fv!r}")
    return fv


def _validate_dead_elements(dead_elements: object, n_ant: int) -> list[int]:
    if dead_elements is None:
        return []
    if isinstance(dead_elements, (str, bytes)) or not isinstance(
        dead_elements, (list, tuple, np.ndarray)
    ):
        raise ValueError(
            f"dead_elements 必须是 list[int]/tuple[int, ...]/None，得到 {type(dead_elements).__name__}"
        )
    out: list[int] = []
    seen: set[int] = set()
    for k, item in enumerate(dead_elements):
        _reject_bool(item, f"dead_elements[{k}]")
        if not isinstance(item, (int, np.integer)):
            raise ValueError(f"dead_elements[{k}] 必须是整数，得到 {type(item).__name__}")
        iv = int(item)
        if not 0 <= iv < n_ant:
            raise ValueError(f"dead_elements[{k}]={iv} 越界（n_ant={n_ant}）")
        if iv in seen:
            raise ValueError(f"dead_elements 重复索引 {iv}，拒绝")
        seen.add(iv)
        out.append(iv)
    return out


def _validate_gains(gains: object, n_ant: int | None = None) -> np.ndarray:
    arr = np.asarray(gains)
    if arr.dtype == bool:
        raise ValueError("gains 为 bool 数组，拒绝")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"gains 必须是数值数组，得到 dtype={arr.dtype}")
    g = arr.astype(complex)
    if g.ndim != 1:
        raise ValueError(f"gains 必须一维，得到 ndim={g.ndim}")
    if not np.all(np.isfinite(g)):
        raise ValueError("gains 含 NaN/Inf，拒绝")
    if n_ant is not None and g.shape[0] != n_ant:
        raise ValueError(f"gains 长度 {g.shape[0]} 与位置数 {n_ant} 不一致")
    return g


def _positions_lambda(pos_lambda: object) -> np.ndarray:
    arr = np.asarray(pos_lambda)
    if arr.dtype == bool:
        raise ValueError("pos_lambda 为 bool 数组，拒绝")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"pos_lambda 必须是数值数组，得到 dtype={arr.dtype}")
    p = arr.astype(float)
    if p.ndim == 1:
        p3 = np.zeros((p.shape[0], 3), dtype=float)
        p3[:, 0] = p
        return p3
    if p.ndim == 2 and p.shape[1] == 3:
        if not np.all(np.isfinite(p)):
            raise ValueError("pos_lambda 含 NaN/Inf，拒绝")
        return p
    raise ValueError(f"pos_lambda 形状必须是 (n_ant,) 或 (n_ant, 3)，得到 {p.shape}")


def _validate_theta_any(theta_deg: object) -> np.ndarray:
    arr = np.asarray(theta_deg)
    if arr.dtype == bool:
        raise ValueError("theta_deg 为 bool 数组，拒绝")
    if not np.issubdtype(arr.dtype, np.number):
        raise ValueError(f"theta_deg 必须是数值数组，得到 dtype={arr.dtype}")
    t = arr.astype(float)
    if not np.all(np.isfinite(t)):
        raise ValueError("theta_deg 含 NaN/Inf，拒绝")
    return t


def _validate_theta_grid(theta_deg: object) -> np.ndarray:
    t = _validate_theta_any(theta_deg)
    if t.ndim != 1:
        raise ValueError(f"theta_deg 必须一维（切面网格），得到 ndim={t.ndim}")
    if t.shape[0] < 5:
        raise ValueError(f"theta_deg 网格至少 5 点，得到 {t.shape[0]}")
    if not np.all(np.diff(t) > 0):
        raise ValueError("theta_deg 必须严格递增（主瓣/零点扫描前提）")
    return t


# ─── 误差注入 ──────────────────────────────────────────────────────────────────


def inject_errors(
    n_ant: int,
    rng_seed: int,
    amp_sigma_db: float = 0.5,
    phase_sigma_deg: float = 5.0,
    dead_elements: list[int] | None = None,
) -> dict[str, object]:
    """逐元幅相误差注入（固定 seed 逐位确定）：返回每元复增益与实现明细。

    模型（见模块 docstring"误差模型与权威口径"）：
    ``g_i = 10^(X_i/20)·exp(j·δφ_i)``，``X_i ~ N(0, amp_sigma_db²)``（dB）、
    ``δφ_i ~ N(0, phase_sigma_deg²)``（度）；失效元硬置 0。
    ``amp_sigma_db=0 且 phase_sigma_deg=0`` 时增益逐位等于 1+0j（零误差
    退化 = 理想阵，供 AF 对拍）。幅度为对数正态（中位数 1），均值
    ``E|g| = exp(σ'²/2)`` 略正偏（σ' = ln10·σ_dB/20）——统计锚用精确矩。

    Parameters
    ----------
    n_ant : int
        元数（正整数）。
    rng_seed : int
        随机种子（非负整数；同 seed 同参数两次调用逐位相等）。
    amp_sigma_db : float
        幅度误差标准差（dB，20·log10 域），非负。
    phase_sigma_deg : float
        相位误差标准差（度），非负。
    dead_elements : list[int] | None
        失效元索引（界内整数、无重复）；None = 无失效。

    Returns
    -------
    dict with keys:
        gains : ndarray (n_ant,) complex —— 每元复增益（失效元 = 0）；
        amp_realizations_db : ndarray (n_ant,) —— 幅度误差实现（dB）；
        phase_realizations_deg : ndarray (n_ant,) —— 相位误差实现（度）；
        dead : list[int] —— 失效元索引（校验后的输入顺序）。
    """
    n = _as_positive_int(n_ant, "n_ant")
    _reject_bool(rng_seed, "rng_seed")
    if not isinstance(rng_seed, (int, np.integer)):
        raise ValueError(f"rng_seed 必须是整数，得到 {type(rng_seed).__name__}")
    if int(rng_seed) < 0:
        raise ValueError(f"rng_seed 必须非负，得到 {rng_seed!r}")
    s_a = _as_nonneg_float(amp_sigma_db, "amp_sigma_db")
    s_p = _as_nonneg_float(phase_sigma_deg, "phase_sigma_deg")
    dead = _validate_dead_elements(dead_elements, n)
    rng = np.random.default_rng(int(rng_seed))
    amp_db = rng.normal(0.0, s_a, size=n)
    phase_deg = rng.normal(0.0, s_p, size=n)
    gains = 10.0 ** (amp_db / 20.0) * np.exp(1j * np.deg2rad(phase_deg))
    for k in dead:
        gains[k] = 0.0
    return {
        "gains": gains,
        "amp_realizations_db": amp_db,
        "phase_realizations_deg": phase_deg,
        "dead": dead,
    }


# ─── 方向图（阵列因子） ────────────────────────────────────────────────────────


def array_factor_with_errors(
    theta_deg: object,
    pos_lambda: np.ndarray,
    gains: np.ndarray,
    f_ghz: float,
    element_pattern: Callable[[object, float], object] | None = None,
) -> np.ndarray:
    """含误差阵列因子（未归一化）：AF(θ) = Σ_i g_i·E_i(θ)·exp(j2π·r̂(θ)·r_i)。

    φ=0 切面：r̂ = (sinθ, 0, cosθ)，即相位 = 2π·(x_i·sinθ + z_i·cosθ)
    （pos_lambda 以波长为单位；y 分量不进入本切面）。x 轴线阵
    （pos 为 (n_ant,)）时退化为 Σ g_i·exp(j2π·x_i·sinθ)。

    f_ghz 仅合法性校验并转发给 element_pattern（pos 已是波长单位，AF 对
    频率尺度不变——不虚构频率依赖，见模块 docstring）。theta 标量/任意
    形状数组均可，返回形状与 theta 一致。

    element_pattern：f(theta_deg, f_ghz) -> complex，按角度广播乘在 AF 上
    （方向图积定理）；None = 全向。
    """
    g = _validate_gains(gains)
    pos = _positions_lambda(pos_lambda)
    if pos.shape[0] != g.shape[0]:
        raise ValueError(f"pos_lambda 元数 {pos.shape[0]} 与 gains 长度 {g.shape[0]} 不一致")
    f_val = _as_nonneg_float(f_ghz, "f_ghz", positive=True)
    t = _validate_theta_any(theta_deg)
    sin_t = np.sin(np.deg2rad(t))[..., None]
    cos_t = np.cos(np.deg2rad(t))[..., None]
    steer = _TWO_PI * (sin_t * pos[:, 0] + cos_t * pos[:, 2])
    af = np.exp(1j * steer) @ g
    if element_pattern is not None:
        if not callable(element_pattern):
            raise ValueError("element_pattern 必须是可调用对象 f(theta_deg, f_ghz) 或 None")
        af = af * np.asarray(element_pattern(theta_deg, f_val))
    return af


def ideal_array_factor(
    theta_deg: object,
    pos_lambda: np.ndarray,
    f_ghz: float,
    element_pattern: Callable[[object, float], object] | None = None,
) -> np.ndarray:
    """理想阵（gains = 全 1）的阵列因子，口径同 :func:`array_factor_with_errors`。"""
    n = _positions_lambda(pos_lambda).shape[0]
    return array_factor_with_errors(
        theta_deg, pos_lambda, np.ones(n, dtype=complex), f_ghz, element_pattern
    )


# ─── 退化指标 ──────────────────────────────────────────────────────────────────


def _first_local_min_index(p: np.ndarray, peak: int, step: int) -> int | None:
    """从峰值出发沿 step 方向找第一个局部极小（第一零点）网格索引；无则 None。"""
    i = peak + step
    while 0 < i < p.shape[0] - 1:
        if p[i] <= p[i - 1] and p[i] <= p[i + 1]:
            return i
        i += step
    return None


def degradation_metrics(af_err: np.ndarray, af_ideal: np.ndarray, theta_deg: np.ndarray) -> dict[str, object]:
    """方向图退化指标（全部对理想峰值 max|AF_ideal|² 归一）。

    口径（显式）：
    - ``p_gain_loss_db = 10·log10(max_θ P_err)``——扰动后主峰相对理想峰
      （P(θ) = |AF(θ)|²/max|AF_ideal|²；幅度误差偏大时可为正=伪增益）；
    - ``sll_delta_db = 10·log10(主瓣外均值P_err / 主瓣外均值P_ideal)``——
      平均副瓣抬升取**主瓣外平均功率**口径（含理想副瓣自身，非仅误差地板；
      主瓣 = 理想方向图第一零点之间）；
    - ``null_fill_db = 10·log10(max 理想第一零点角上的 P_err)``——第一零点
      填充电平（理想零点处无填充时为 -inf，不虚构）。

    Returns
    -------
    dict with keys:
        p_gain_loss_db, sll_delta_db, null_fill_db,
        first_null_deg : list[float] —— 检出的理想第一零点角 [左, 右]
            （某侧网格内无零点时缺该侧）；
        sidelobe_mean_power_err / sidelobe_mean_power_ideal : float。
    """
    af_e = _validate_gains(af_err)
    af0 = _validate_gains(af_ideal)
    if af_e.shape != af0.shape:
        raise ValueError(f"af_err 形状 {af_e.shape} 与 af_ideal 形状 {af0.shape} 不一致")
    theta = _validate_theta_grid(theta_deg)
    if theta.shape[0] != af0.shape[0]:
        raise ValueError(f"theta 网格点数 {theta.shape[0]} 与 AF 点数 {af0.shape[0]} 不一致")
    p0_peak = float(np.max(np.abs(af0)) ** 2)
    if p0_peak <= 0.0:
        raise ValueError("af_ideal 峰值功率为 0，归一化无定义，拒绝")
    p_e = np.abs(af_e) ** 2 / p0_peak
    p_0 = np.abs(af0) ** 2 / p0_peak

    peak_e = int(np.argmax(p_e))
    gain_loss_db = 10.0 * float(np.log10(p_e[peak_e])) if p_e[peak_e] > 0.0 else float("-inf")
    k0 = int(np.argmax(p_0))
    i_left = _first_local_min_index(p_0, k0, -1)
    i_right = _first_local_min_index(p_0, k0, +1)
    if i_left is None and i_right is None:
        raise ValueError(
            "理想方向图上未找到第一零点（网格过粗或主瓣占据全网格）——"
            "副瓣/零点指标无定义，拒绝"
        )
    lo = 0 if i_left is None else i_left + 1
    hi = theta.shape[0] if i_right is None else i_right
    mask = np.ones(theta.shape[0], dtype=bool)
    mask[lo:hi] = False  # 主瓣内部（两第一零点之间）剔除
    sll_ideal = float(p_0[mask].mean())
    sll_err = float(p_e[mask].mean())
    if sll_ideal <= 0.0:
        raise ValueError("主瓣外理想平均功率为 0，副瓣抬升无定义，拒绝")
    sll_delta_db = 10.0 * float(np.log10(sll_err / sll_ideal)) if sll_err > 0.0 else float("-inf")
    null_powers = [float(p_e[i]) for i in (i_left, i_right) if i is not None]
    fill = max(null_powers)
    null_fill_db = 10.0 * float(np.log10(fill)) if fill > 0.0 else float("-inf")
    return {
        "p_gain_loss_db": gain_loss_db,
        "sll_delta_db": sll_delta_db,
        "null_fill_db": null_fill_db,
        "first_null_deg": [float(theta[i]) for i in (i_left, i_right) if i is not None],
        "sidelobe_mean_power_err": sll_err,
        "sidelobe_mean_power_ideal": sll_ideal,
    }


# ─── 校准闭环（对拍 M-2.1） ────────────────────────────────────────────────────


def _validate_user_pairs(baseline_pairs: Sequence[Sequence[int]], n_ant: int) -> list[tuple[int, int]]:
    if isinstance(baseline_pairs, (str, bytes)):
        raise ValueError("baseline_pairs 不能是字符串")
    out: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for k, pair in enumerate(baseline_pairs):
        if len(pair) != 2:
            raise ValueError(f"baseline_pairs[{k}] 长度必须是 2，得到 {len(pair)}")
        i, j = pair
        for name, v in (("i", i), ("j", j)):
            _reject_bool(v, f"baseline_pairs[{k}].{name}")
            if not isinstance(v, (int, np.integer)):
                raise ValueError(f"baseline_pairs[{k}].{name} 必须是整数，得到 {type(v).__name__}")
        if i == j:
            raise ValueError(f"baseline_pairs[{k}] 自配对 ({i}, {j})，拒绝")
        if not (0 <= int(i) < n_ant and 0 <= int(j) < n_ant):
            raise ValueError(f"baseline_pairs[{k}] = ({i}, {j}) 越界（n_ant={n_ant}）")
        tp = (int(i), int(j))
        if tp in seen:
            raise ValueError(f"baseline_pairs 重复基线 {tp}，拒绝")
        seen.add(tp)
        out.append(tp)
    if not out:
        raise ValueError("baseline_pairs 为空，至少需要 1 条基线")
    return out


def calibration_roundtrip(
    n_ant: int,
    error_kwargs: dict[str, object],
    f_ghz: float,
    baseline_pairs: Sequence[Sequence[int]] | None = None,
) -> dict[str, object]:
    """注入已知误差 → 构造观测可见度 → array_calib.lincal 回收 → 对拍误差。

    闭环口径（M-2.1 消费面回归锚）：
    - 观测 ``V_ij = g_i·conj(g_j)·V^true_ij``；v1 真值 = 宽带点源@广侧射
      （``V^true_ij = 1``，全连接纯增益积口径——pos 以波长为单位时广侧射
      平面波相位恒 0，物理自洽）；
    - dead 元经**零可见度基线**检测（真值非零口径下判据 = 该元无任何一条
      非零基线 ⇔ g_k=0；单条零基线只说明两端之一失效，端点并集会误标），
      存活子阵（重索引后）交 :func:`array_calib.lincal_gain_solve` 回收
      （内部 logcal 启动），dead 元回收值置 0——M-2.1 对含零行数据
      如实拒收，dead 检测/剔除属测试床职责；
    - 幅值唯一性要求存活子阵基线图**非二部**（含奇圈；缺省全连接自动
      满足），经 :func:`array_calib.redundant_group_degeneracy` 校验，
      二部/不连通如实拒绝（棋盘幅值简并未锚定时回收不唯一）；
    - 全局相位简并由 array_calib 锚定参考元解决；回收值按参考元复数
      对齐注入值后再比误差（对齐只动真零空间方向）。

    Parameters
    ----------
    n_ant : int
        元数（≥3，非二部图前提）。
    error_kwargs : dict
        :func:`inject_errors` 关键字（**必须显式含 rng_seed**——确定性测试床）。
    f_ghz : float
        工作频率（GHz，正数；v1 真值频率平坦，仅作记录/接口口径）。
    baseline_pairs : Sequence[(i, j)] | None
        缺省全连接；显式给入时须连通且含奇圈。

    Returns
    -------
    dict with keys:
        injected / recovered : ndarray (n_ant,) complex；
        recovery_err : float —— 存活元 max|g_rec−g_inj|/|g_inj|
            （无噪闭环应达机器精度量级，M-2.1 判据 ≤1e-6）；
        amp_err_max / phase_err_max_rad : float —— 幅/相分项最大误差；
        dead_injected / dead_detected : list[int] —— 注入与零行检出的失效元
            （缺省全连接下两者应一致）；
        converged / n_iter / residual_rms : lincal 收敛信息；
        f_ghz : float。
    """
    n = _as_positive_int(n_ant, "n_ant")
    if n < 3:
        raise ValueError(f"n_ant ≥ 3 才能构成非二部基线图（幅值唯一可回收），得到 {n}")
    if not isinstance(error_kwargs, dict):
        raise ValueError(f"error_kwargs 必须是 dict（inject_errors 关键字），得到 {type(error_kwargs).__name__}")
    if "rng_seed" not in error_kwargs:
        raise ValueError("error_kwargs 必须显式含 rng_seed（确定性测试床，不做隐式随机）")
    f_val = _as_nonneg_float(f_ghz, "f_ghz", positive=True)
    inj = inject_errors(n, **error_kwargs)
    g_inj = np.asarray(inj["gains"], dtype=complex)
    dead_inj: list[int] = list(inj["dead"])  # type: ignore[arg-type]
    if n - len(dead_inj) < 3:
        raise ValueError(f"存活元 {n - len(dead_inj)} < 3，无法构成非二部图，拒绝")
    if baseline_pairs is None:
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    else:
        pairs = _validate_user_pairs(baseline_pairs, n)

    ib = np.asarray([p[0] for p in pairs], dtype=int)
    jb = np.asarray([p[1] for p in pairs], dtype=int)
    v_obs = (g_inj[ib] * np.conj(g_inj[jb]))[:, None]  # (M, 1)，真值全 1
    zero_rows = np.all(v_obs == 0, axis=1)
    # dead 检出：一条零基线 V(k,j)=0 只说明"两端之一 g=0"，零行端点并集会把
    # 全部关联元误标——正确判据 = "该元没有任何一条非零基线"（真值非零口径下
    # 与 g=0 充要；未被任何基线覆盖的元同样无可标定信息，归入检出并如实语义）。
    has_nonzero = np.zeros(n, dtype=bool)
    nonzero = ~zero_rows
    has_nonzero[ib[nonzero]] = True
    has_nonzero[jb[nonzero]] = True
    dead_detected = [int(i) for i in range(n) if not has_nonzero[i]]

    live = [i for i in range(n) if i not in set(dead_inj)]
    remap = {old: new for new, old in enumerate(live)}
    live_rows = [k for k, (i, j) in enumerate(pairs) if i in remap and j in remap]
    live_pairs = [(remap[pairs[k][0]], remap[pairs[k][1]]) for k in live_rows]
    deg = redundant_group_degeneracy(live_pairs, len(live))
    if int(deg["amp_rank_deficiency"]) > 0:  # type: ignore[arg-type]
        raise ValueError(
            "存活子阵幅值简并未锚定（孤立元/二部图棋盘模，rank_deficiency="
            f"{deg['amp_rank_deficiency']}）——基线集须连通且含奇圈（如全连接），回收才唯一"
        )

    res = lincal_gain_solve(v_obs[live_rows], live_pairs, np.ones_like(v_obs[live_rows]), ref_ant=0)
    g_rec_sub = np.asarray(res["gains"], dtype=complex)[:, 0]
    rot = g_inj[live[0]] / g_rec_sub[0]  # 全局相位对齐（只动零空间方向）
    recovered = np.zeros(n, dtype=complex)
    recovered[live] = g_rec_sub * rot

    live_idx = np.asarray(live, dtype=int)
    g_true_live = g_inj[live_idx]
    g_hat_live = recovered[live_idx]
    rel = np.abs(g_hat_live - g_true_live) / np.abs(g_true_live)
    amp_err = np.abs(np.abs(g_hat_live) - np.abs(g_true_live)) / np.abs(g_true_live)
    ph_err = np.abs(np.angle(g_hat_live * np.conj(g_true_live)))
    return {
        "injected": g_inj,
        "recovered": recovered,
        "recovery_err": float(np.max(rel)),
        "amp_err_max": float(np.max(amp_err)),
        "phase_err_max_rad": float(np.max(ph_err)),
        "dead_injected": dead_inj,
        "dead_detected": dead_detected,
        "converged": bool(res["converged"]),
        "n_iter": int(res["n_iter"]),
        "residual_rms": float(res["residual_rms"]),
        "f_ghz": f_val,
    }
