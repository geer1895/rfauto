"""逆向设计研究线：JAX 可微 1D FDTD + 伴随（反向模式）拓扑优化（CPU 小规模）。

定位
====================================================================
研究分支，不接入主求解链、不阻塞主线。本模块给三件事：

1. **可微 FDTD**：归一化单位（c = eps0 = mu0 = 1）的 1D Yee 时间步进，
   jax.lax.scan + jax.numpy 实现；目标 = 探针处透射功率
   T(omega0) = |A|^2 / |A_ref|^2（A 为探针场在 omega0 的离散傅里叶分量，
   A_ref 为同域真空参考运行）；jax.grad 反向模式即伴随/直接反向。
2. **密度参数化 + 投影**：设计域密度 rho in [0,1] -> 归一化移动平均滤波 ->
   tanh 投影（Wang et al. 2011, doi:10.1007/s00158-011-0666-3）->
   eps_r = eps_min + (eps_max - eps_min) * proj；beta 连续化退火做二值化拓扑优化。
3. **经典测例**：均匀介质板透射对照 Airy 闭式解；1D 反射器（透射极小）逆设计。

判定口径（不得自证）
--------------------
- **独立来源**：单层板 Airy 闭式解 T = 1/(1 + F sin^2(delta))、
  F = ((eps_r - 1)/(2n))^2，以及任意分层介质的转移矩阵（TMM）解析解；两者都
  不经过 FDTD 时间步进。网格色散用离散色散关系修正的"数值波数"给对照版本
  （残差如实标注，不硬凑）。
- **梯度对拍**：同一目标函数（同 beta / 同滤波 / 同投影）的中心有限差分。
- 分层约束：core 是稳定叶子，本模块只依赖标准库 + numpy；jax 一律在函数内
  惰性 import，未安装 jax 时模块仍可导入（真机求解抛 RuntimeError）。
"""

from __future__ import annotations

import functools
import itertools
import math
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np

C0 = 1.0  # 归一化光速
DX = 1.0  # 网格步长（归一化单位）
GRAD_REL_TOL = 1e-3  # 梯度对拍容差（jax.grad vs 中心有限差分）

_X64_CACHE: dict[str, bool] = {}


# ── 配置 ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FDTD1DConfig:
    """1D 可微 FDTD 域配置（全是普通标量，frozen 可哈希 -> 可做 lru_cache 键）。"""

    n_cells: int = 360
    n_steps: int = 1500
    courant: float = 1.0  # 1D 真空"magic step"：均匀 eps=1 区无色散
    source_index: int = 40
    probe_index: int = 320
    design_lo: int = 140
    design_hi: int = 220
    cells_per_wavelength: float = 40.0  # omega0 = 2*pi*c/(lambda0)，lambda0 用网格数表示
    pulse_t0: float = 110.0
    pulse_tau: float = 18.0
    eps_min: float = 1.0
    eps_max: float = 6.0
    filter_radius: int = 1

    @property
    def omega(self) -> float:
        """目标角频率（c=1, dx=1）：lambda0 = cells_per_wavelength 个网格。"""
        return 2.0 * math.pi * C0 / (self.cells_per_wavelength * DX)

    @property
    def design_length(self) -> int:
        return self.design_hi - self.design_lo

    @property
    def dt(self) -> float:
        return self.courant * DX / C0


@dataclass(frozen=True)
class OptimizeConfig:
    """密度法拓扑优化配置（归一化梯度 + 回溯线搜索 + beta 退火）。"""

    iterations: int = 80
    step: float = 0.08  # 归一化步长（每步 L_inf 位移上限）
    beta_start: float = 1.0
    beta_end: float = 32.0
    sense: str = "min"  # "min" = 透射极小（反射器）；"max" = 透射极大
    seed: int = 0
    init_noise: float = 0.15
    max_backtracks: int = 8


# ── 纯函数：密度参数化 / 投影（numpy 参考实现，离线可测） ─────────────────────


def project_density(x: float, beta: float, eta: float = 0.5) -> float:
    """tanh 密度投影（Wang et al. 2011 标准式）；x 先夹到 [0, 1]。"""
    x = min(max(float(x), 0.0), 1.0)
    numerator = math.tanh(beta * eta) + math.tanh(beta * (x - eta))
    denominator = math.tanh(beta * eta) + math.tanh(beta * (1.0 - eta))
    if denominator == 0.0:
        return float(x)
    return float(numerator / denominator)


def smooth_profile(values: Any, radius: int) -> list[float]:
    """归一化移动平均滤波（edge padding）；radius <= 0 时恒等。"""
    vals = [float(v) for v in values]
    if radius <= 0 or not vals:
        return vals
    width = 2 * radius + 1
    last = len(vals) - 1
    out: list[float] = []
    for i in range(len(vals)):
        total = 0.0
        for offset in range(-radius, radius + 1):
            j = min(max(i + offset, 0), last)
            total += vals[j]
        out.append(total / width)
    return out


def reference_eps_profile(density: Any, beta: float, cfg: FDTD1DConfig) -> list[float]:
    """纯 Python 参考实现：设计域密度 -> 全网格 eps_r 剖面（与 jax 路径对拍用）。"""
    smoothed = smooth_profile(density, cfg.filter_radius)
    eps = [cfg.eps_min] * cfg.n_cells
    for k, value in enumerate(smoothed):
        if k >= cfg.design_length:
            break
        projected = project_density(value, beta)
        eps[cfg.design_lo + k] = cfg.eps_min + (cfg.eps_max - cfg.eps_min) * projected
    return eps


def binary_score(density: Any, beta: float, cfg: FDTD1DConfig | None = None) -> float:
    """二值化程度：mean(4*p*(1-p)) 的投影后密度，0 = 完全二值，1 = 全 0.5。"""
    cfg = cfg or FDTD1DConfig()
    smoothed = smooth_profile(density, cfg.filter_radius)
    projected = [project_density(v, beta) for v in smoothed[: cfg.design_length]]
    if not projected:
        return 1.0
    return float(np.mean([4.0 * p * (1.0 - p) for p in projected]))


# ── 解析/闭式裁判（独立于 FDTD 时间步进） ─────────────────────────────────────


def numerical_wavenumber(
    omega: float,
    eps_r: float,
    courant: float = 1.0,
    dx: float = DX,
    c: float = C0,
) -> float:
    """离散色散关系解出的数值波数 k(omega, eps_r)。

    sin(omega*dt/2) = (c*dt/(dx*sqrt(eps_r))) * sin(k*dx/2)，dt = courant*dx/c。
    无传播解（arg 越界）返回 nan。
    """
    dt = courant * dx / c
    arg = math.sin(omega * dt / 2.0) * math.sqrt(eps_r) / courant
    if not -1.0 <= arg <= 1.0:
        return float("nan")
    return 2.0 * math.asin(arg) / dx


def airy_transmission(
    eps_r: float,
    thickness: float,
    omega: float,
    *,
    courant: float = 1.0,
    dx: float = DX,
    numerical: bool = False,
) -> float:
    """单层介质板法向入射功率透射率（Airy 闭式解）。

    T = 1 / (1 + F sin^2(delta))，F = ((eps_r-1)/(2n))^2，n = sqrt(eps_r)。
    numerical=True 时 phase 用离散色散关系的数值波数（网格伪象对照版本）。
    """
    n = math.sqrt(eps_r)
    k = numerical_wavenumber(omega, eps_r, courant, dx) if numerical else omega * n / C0
    delta = k * thickness
    if math.isnan(delta):
        return float("nan")
    finesse = ((eps_r - 1.0) / (2.0 * n)) ** 2
    return 1.0 / (1.0 + finesse * math.sin(delta) ** 2)


def tmm_transmission(
    layers: Any,
    omega: float,
    *,
    eps_ambient: float = 1.0,
    courant: float = 1.0,
    dx: float = DX,
    numerical: bool = False,
) -> float:
    """任意分层介质法向入射功率透射率（转移矩阵 TMM 解析解）。

    layers：(eps_r, thickness) 序列；两侧半无限层为 eps_ambient。
    特征矩阵单元 M_j = [[cos d, i sin d / eta], [i eta sin d, cos d]]，eta = sqrt(eps_r)；
    T = 4 eta0 eta_s / |eta0 B + C|^2，[B; C] = M [1; eta_s]。
    """
    eta0 = math.sqrt(eps_ambient)
    m00, m01, m10, m11 = complex(1.0), complex(0.0), complex(0.0), complex(1.0)
    for eps_r, thickness in layers:
        eta = math.sqrt(eps_r)
        k = numerical_wavenumber(omega, eps_r, courant, dx) if numerical else omega * eta / C0
        if math.isnan(k):
            return float("nan")
        delta = k * thickness
        cos_d, sin_d = math.cos(delta), math.sin(delta)
        a00, a01 = complex(cos_d), complex(0.0, sin_d / eta)
        a10, a11 = complex(0.0, eta * sin_d), complex(cos_d)
        m00, m01, m10, m11 = (
            m00 * a00 + m01 * a10,
            m00 * a01 + m01 * a11,
            m10 * a00 + m11 * a10,
            m10 * a01 + m11 * a11,
        )
    b = m00 + m01 * eta0
    c_term = m10 + m11 * eta0
    denominator = abs(eta0 * b + c_term) ** 2
    if denominator <= 0.0:
        return float("nan")
    return float(4.0 * eta0 * eta0 / denominator)


def profile_to_layers(eps_profile: Any, dx: float = DX) -> list[tuple[float, float]]:
    """把逐网格 eps 剖面压成 (eps_r, thickness) 层序列（TMM 用）。"""
    layers: list[tuple[float, float]] = []
    for value in eps_profile:
        eps_r = float(value)
        if layers and layers[-1][0] == eps_r:
            eps_prev, thickness = layers[-1]
            layers[-1] = (eps_prev, thickness + dx)
        else:
            layers.append((eps_r, dx))
    return layers


# ── jax 内核（惰性 import） ───────────────────────────────────────────────────


def _enable_x64() -> bool:
    """尽力开启 jax x64（float64）；不可用则退回默认 dtype（best-effort，不阻断）。"""
    if "x64" in _X64_CACHE:
        return _X64_CACHE["x64"]
    enabled = False
    try:
        import jax

        jax.config.update("jax_enable_x64", True)
        enabled = bool(getattr(jax.config, "x64_enabled", False))
    except Exception:  # jax 缺失或配置已冻结：退回默认 dtype
        enabled = False
    _X64_CACHE["x64"] = enabled
    return enabled


@dataclass(frozen=True)
class _Simulators:
    """一次编译好的 jax 内核集合（按 cfg 缓存）。"""

    value_and_grad: Any
    diagnostics: Any
    eps_profile: Any
    reference_power: float
    x64: bool
    dtype: Any


def _build_simulators(cfg: FDTD1DConfig) -> _Simulators:
    if not (0 < cfg.source_index < cfg.design_lo <= cfg.design_hi <= cfg.probe_index < cfg.n_cells):
        raise ValueError("索引不合法：要求 0 < source < design_lo <= design_hi <= probe < n_cells")
    import jax
    import jax.numpy as jnp

    x64 = _enable_x64()
    dtype = jnp.float64 if x64 else jnp.float32
    complex_dtype = jnp.complex128 if x64 else jnp.complex64

    dt = cfg.dt
    t = jnp.arange(cfg.n_steps, dtype=dtype)
    pulse = jnp.exp(-(((t - cfg.pulse_t0) / cfg.pulse_tau) ** 2))
    phase = jnp.exp(-1j * cfg.omega * dt * t).astype(complex_dtype)
    mur = (cfg.courant - 1.0) / (cfg.courant + 1.0)
    last = cfg.n_cells - 1

    def eps_profile(density: Any, beta: Any) -> Any:
        x = jnp.clip(jnp.asarray(density, dtype=dtype), 0.0, 1.0)
        if cfg.filter_radius > 0:
            width = 2 * cfg.filter_radius + 1
            kernel = jnp.ones(width, dtype=dtype) / width
            padded = jnp.pad(x, (cfg.filter_radius, cfg.filter_radius), mode="edge")
            x = jnp.convolve(padded, kernel, mode="valid")
        eta = 0.5
        projected = (jnp.tanh(beta * eta) + jnp.tanh(beta * (x - eta))) / (
            jnp.tanh(beta * eta) + jnp.tanh(beta * (1.0 - eta))
        )
        return cfg.eps_min + (cfg.eps_max - cfg.eps_min) * projected

    def run(density: Any, beta: Any) -> tuple[Any, Any]:
        eps_design = eps_profile(density, beta)
        eps = jnp.full((cfg.n_cells,), cfg.eps_min, dtype=dtype)
        eps = eps.at[cfg.design_lo : cfg.design_hi].set(eps_design)

        def step(carry: Any, xs: Any) -> tuple[Any, None]:
            ez, hy, acc = carry
            p, ph = xs
            new = ez.at[1:last].add(cfg.courant * (hy[1:] - hy[:-1]) / eps[1:last])
            new = new.at[0].set(ez[1] + mur * (new[1] - ez[0]))
            new = new.at[last].set(ez[last - 1] + mur * (new[last - 1] - ez[last]))
            new = new.at[cfg.source_index].add(p)
            hy = hy + cfg.courant * (new[1:] - new[:-1])
            acc = acc + new[cfg.probe_index] * ph
            return (new, hy, acc), None

        carry0 = (
            jnp.zeros(cfg.n_cells, dtype=dtype),
            jnp.zeros(cfg.n_cells - 1, dtype=dtype),
            jnp.zeros((), dtype=complex_dtype),
        )
        (ez, _hy, acc), _ = jax.lax.scan(step, carry0, (pulse, phase))
        return acc, jnp.max(jnp.abs(ez))

    jitted_run = jax.jit(run)
    zero_density = jnp.zeros(cfg.design_length, dtype=dtype)
    reference_acc, _ = jitted_run(zero_density, 1.0)
    ref = np.asarray(reference_acc)
    reference_power = float(np.real(ref * np.conj(ref)))

    def transmission(density: Any, beta: Any) -> Any:
        acc, _ = run(density, beta)
        power = jnp.real(acc * jnp.conj(acc))
        return power / reference_power

    return _Simulators(
        value_and_grad=jax.jit(jax.value_and_grad(transmission)),
        diagnostics=jitted_run,
        eps_profile=jax.jit(eps_profile),
        reference_power=reference_power,
        x64=x64,
        dtype=np.float64 if x64 else np.float32,
    )


@functools.lru_cache(maxsize=16)
def _compiled(cfg: FDTD1DConfig) -> _Simulators:
    return _build_simulators(cfg)


def _as_density(density: Any, cfg: FDTD1DConfig, sim: _Simulators) -> np.ndarray:
    arr = np.asarray(density, dtype=sim.dtype).reshape(-1)
    if arr.size != cfg.design_length:
        raise ValueError(f"density 长度 {arr.size} != design_length {cfg.design_length}")
    return arr


def jax_eps_profile(
    density: Any,
    beta: float = 1.0,
    cfg: FDTD1DConfig | None = None,
) -> np.ndarray:
    """jax 路径的设计域 eps 剖面（滤波 + 投影后；与 reference_eps_profile 对拍用）。"""
    cfg = cfg or FDTD1DConfig()
    sim = _compiled(cfg)
    return np.asarray(sim.eps_profile(_as_density(density, cfg, sim), float(beta)), dtype=float)


def transmission(density: Any, beta: float = 1.0, cfg: FDTD1DConfig | None = None) -> float:
    """设计域密度 -> 探针处目标频率功率透射率 T（jax 前向，返回 Python float）。"""
    cfg = cfg or FDTD1DConfig()
    sim = _compiled(cfg)
    acc, _peak = sim.diagnostics(_as_density(density, cfg, sim), float(beta))
    value = np.asarray(acc)
    power = float(np.real(value * np.conj(value)))
    return power / sim.reference_power


def simulate(density: Any, beta: float = 1.0, cfg: FDTD1DConfig | None = None) -> dict:
    """完整诊断：T、探针谱幅、max|Ez|、有限性、x64。"""
    cfg = cfg or FDTD1DConfig()
    sim = _compiled(cfg)
    acc, peak = sim.diagnostics(_as_density(density, cfg, sim), float(beta))
    value = np.asarray(acc)
    power = float(np.real(value * np.conj(value)))
    peak_f = float(np.asarray(peak))
    trans = power / sim.reference_power
    return {
        "transmission": trans,
        "amplitude": value,
        "max_abs_ez": peak_f,
        "finite": bool(np.isfinite(trans) and np.isfinite(peak_f)),
        "x64": sim.x64,
    }


def transmission_and_gradient(
    density: Any,
    beta: float = 1.0,
    cfg: FDTD1DConfig | None = None,
) -> tuple[float, np.ndarray]:
    """T 及其对密度 rho 的梯度（jax.grad 反向模式 = 伴随/直接反向）。"""
    cfg = cfg or FDTD1DConfig()
    sim = _compiled(cfg)
    value, grad = sim.value_and_grad(_as_density(density, cfg, sim), float(beta))
    return float(value), np.asarray(grad)


def adjoint_gradient(
    density: Any,
    beta: float = 1.0,
    cfg: FDTD1DConfig | None = None,
) -> np.ndarray:
    """目标 T 对材料密度 rho 的伴随梯度（jax.grad 反向模式）。

    密度法拓扑优化的下降方向来源：dT/drho 由反向模式穿过完整 FDTD 时间步进算出，
    等价于对时间步进的离散伴随（adjoint）求解。
    """
    return transmission_and_gradient(density, beta, cfg)[1]


# ── 梯度对拍 / 均匀板验证 / 逆设计 ───────────────────────────────────────────


def relative_error(approx: Any, reference: Any) -> float | None:
    """|approx - reference| / |reference|；参考近零/非有限返回 None。"""
    try:
        a = float(approx)
        r = float(reference)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(a) and math.isfinite(r)) or abs(r) < 1e-300:
        return None
    return abs(a - r) / abs(r)


def gradient_check(
    cfg: FDTD1DConfig | None = None,
    *,
    beta: float = 1.0,
    seed: int = 0,
    components: int = 4,
    step: float | None = None,
) -> dict:
    """jax.grad（反向模式）vs 中心有限差分（同一目标函数）。"""
    cfg = cfg or FDTD1DConfig()
    sim = _compiled(cfg)
    length = cfg.design_length
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.3, 0.7, length)
    analytic = adjoint_gradient(base, beta, cfg)
    indices = sorted({int(i) for i in np.linspace(1, length - 2, num=min(components, length - 2))})
    h = step if step is not None else (1e-4 if sim.x64 else 1e-3)
    fd = np.zeros(len(indices))
    for k, idx in enumerate(indices):
        plus = base.copy()
        plus[idx] += h
        minus = base.copy()
        minus[idx] -= h
        fd[k] = (transmission(plus, beta, cfg) - transmission(minus, beta, cfg)) / (2.0 * h)
    rel = [relative_error(analytic[i], fd[k]) for k, i in enumerate(indices)]
    rel_valid = [r for r in rel if r is not None]
    return {
        "indices": indices,
        "analytic": [float(analytic[i]) for i in indices],
        "finite_difference": [float(v) for v in fd],
        "relative_errors": rel,
        "max_relative_error": max(rel_valid) if rel_valid else None,
        "step": h,
        "x64": sim.x64,
    }


def tmm_fdtd_cross_check(
    density: Any,
    beta: float = 1.0,
    cfg: FDTD1DConfig | None = None,
) -> dict:
    """FDTD 透射 vs TMM 解析透射（同一分层剖面，两种独立算法）。

    注意：T 很小（强反射）时相对误差对两个近零数不可解释，此时只看两者是否
    一致地预测强反射（tmm/FDTD 都 << 1）；T 为 O(0.01..1) 时相对误差有意义。
    """
    cfg = cfg or FDTD1DConfig()
    eps_profile = reference_eps_profile(density, beta, cfg)
    layers = profile_to_layers(eps_profile)
    t_fdtd = transmission(density, beta, cfg)
    t_tmm_num = tmm_transmission(layers, cfg.omega, courant=cfg.courant, numerical=True)
    t_tmm_phys = tmm_transmission(layers, cfg.omega, courant=cfg.courant, numerical=False)
    return {
        "transmission_fdtd": float(t_fdtd),
        "tmm_numerical": float(t_tmm_num),
        "tmm_physical": float(t_tmm_phys),
        "rel_error_numerical": relative_error(t_fdtd, t_tmm_num),
        "rel_error_physical": relative_error(t_fdtd, t_tmm_phys),
    }


def homogeneous_slab_report(
    eps_r: float,
    thickness_cells: int,
    cfg: FDTD1DConfig | None = None,
) -> dict:
    """均匀板 FDTD 透射 vs Airy 闭式解（物理 + 离散色散修正两版）。"""
    base = cfg or FDTD1DConfig()
    thickness = float(thickness_cells) * DX
    slab_cfg = replace(base, design_hi=base.design_lo + int(thickness_cells), eps_max=float(eps_r))
    ones = np.ones(slab_cfg.design_length)
    t_fdtd = transmission(ones, 1.0, slab_cfg)
    t_physical = airy_transmission(eps_r, thickness, slab_cfg.omega, numerical=False)
    t_numerical = airy_transmission(
        eps_r, thickness, slab_cfg.omega, courant=slab_cfg.courant, numerical=True
    )
    return {
        "eps_r": float(eps_r),
        "thickness_cells": int(thickness_cells),
        "transmission_fdtd": float(t_fdtd),
        "airy_physical": float(t_physical),
        "airy_numerical": float(t_numerical),
        "rel_error_physical": relative_error(t_fdtd, t_physical),
        "rel_error_numerical": relative_error(t_fdtd, t_numerical),
    }


def _initial_density(cfg: FDTD1DConfig, optimize_cfg: OptimizeConfig) -> np.ndarray:
    rng = np.random.default_rng(optimize_cfg.seed)
    noise = rng.normal(0.0, optimize_cfg.init_noise, cfg.design_length)
    return np.clip(0.5 + noise, 0.0, 1.0)


def optimize_density(
    cfg: FDTD1DConfig | None = None,
    optimize_cfg: OptimizeConfig | None = None,
) -> dict:
    """归一化梯度下降 + 回溯线搜索 + beta 退火的二值化拓扑优化。

    目标：sense="min" 最小化 T(omega0)（反射器），"max" 最大化 T。
    每步用 L_inf 归一化梯度，回溯保证目标单调不劣（因此历史可断言非增/非减）。
    """
    cfg = cfg or FDTD1DConfig()
    optimize_cfg = optimize_cfg or OptimizeConfig()
    if optimize_cfg.sense not in ("min", "max"):
        raise ValueError(f"sense 必须是 'min'/'max'，收到 {optimize_cfg.sense!r}")
    if optimize_cfg.iterations < 1:
        raise ValueError("iterations 必须 >= 1")
    sign = 1.0 if optimize_cfg.sense == "min" else -1.0

    rho = _initial_density(cfg, optimize_cfg)
    rho_initial = rho.copy()
    beta = optimize_cfg.beta_start
    value, grad = transmission_and_gradient(rho, beta, cfg)
    history = [value]
    beta_history = [beta]
    accepted_steps = 0
    ratio = (optimize_cfg.beta_end / optimize_cfg.beta_start) ** (
        1.0 / max(optimize_cfg.iterations - 1, 1)
    )

    for iteration in range(1, optimize_cfg.iterations + 1):
        beta = optimize_cfg.beta_start * ratio**iteration
        value, grad = transmission_and_gradient(rho, beta, cfg)
        norm = float(np.max(np.abs(grad)))
        direction = -sign * grad / norm if norm > 0.0 else np.zeros_like(rho)
        step = optimize_cfg.step
        new_rho, new_value = rho, value
        for _ in range(optimize_cfg.max_backtracks):
            candidate = np.clip(rho + step * direction, 0.0, 1.0)
            candidate_value = transmission(candidate, beta, cfg)
            if sign * candidate_value <= sign * value + 1e-12:
                new_rho, new_value = candidate, candidate_value
                accepted_steps += 1
                break
            step *= 0.5
        rho = new_rho
        history.append(new_value)
        beta_history.append(beta)

    final_beta = beta_history[-1]
    eps_profile = reference_eps_profile(rho, final_beta, cfg)
    tmm_num = tmm_transmission(
        profile_to_layers(eps_profile), cfg.omega, courant=cfg.courant, numerical=True
    )
    tmm_phys = tmm_transmission(
        profile_to_layers(eps_profile), cfg.omega, courant=cfg.courant, numerical=False
    )
    best = min(history) if optimize_cfg.sense == "min" else max(history)
    best_history: list[float] = []
    running = history[0]
    for v in history:
        running = min(running, v) if optimize_cfg.sense == "min" else max(running, v)
        best_history.append(running)
    strict_improvements = sum(1 for a, b in itertools.pairwise(best_history) if b != a)
    initial_at_final_beta = transmission(rho_initial, final_beta, cfg)
    return {
        "config": asdict(cfg),
        "optimize_config": asdict(optimize_cfg),
        "sense": optimize_cfg.sense,
        "objective_history": [float(v) for v in history],
        "objective_history_best": [float(v) for v in best_history],
        "beta_history": [float(b) for b in beta_history],
        "initial_objective": float(history[0]),
        "initial_objective_final_beta": float(initial_at_final_beta),
        "final_objective": float(history[-1]),
        "best_objective": float(best),
        "strict_improvements": strict_improvements,
        "accepted_steps": accepted_steps,
        "density": [float(v) for v in rho],
        "eps_profile": [float(v) for v in eps_profile],
        "binary_score": binary_score(rho, final_beta, cfg),
        "tmm_transmission_numerical": float(tmm_num),
        "tmm_transmission_physical": float(tmm_phys),
        "tmm_rel_error": relative_error(history[-1], tmm_num),
    }


LITERATURE_NOTES: tuple[str, ...] = (
    "经典闭式对照：单层板 Airy 公式 T = 1/(1 + F sin^2(delta))，F = ((eps_r-1)/(2n))^2（教科书法布里-珀罗口径）。",
    "独立数值对照：分层介质转移矩阵（TMM）——本模块用离散色散波数给网格修正版，残差如实报告。",
    "方法学路线指引（本次未真跑，不硬凑）：Meep adjoint 教程（meep.readthedocs.io Adjoint_Solver，密度法拓扑优化 + nlopt）；"
    "FDTDX（arXiv 2412.12360）与 rfx 的 JAX 原生可微 FDTD；HFSS Adjoint Solver 商业锚待后续增量。",
    "本增量范围：1D、CPU、小规模、单频目标；2D 波导弯头/宽频/最小特征尺寸约束未实现。",
)

