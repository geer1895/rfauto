"""2D 准静态 FD Laplace 裁判内核（#118 独立数值来源）。

职责（数值只在确定性内核；本模块 = 纯 numpy/scipy 叶子，无业务依赖）：
- 张量网格（网格线**精确**落在导体边缘/介质面，远区几何递增）上以变分有限体积
  离散 ∇·(ε∇φ)=0：每条网格边的电导 g = (两侧 cell 的 ε·半格宽之和)/边长，
  能量法 C = 2W/V²，W = ½Σ g·Δφ²——离散二次型与离散算子同源，能量法 ≡ 通量法；
  ε 按边两侧 cell 半格加权 = 切向 E 连续、能量可加（介质面必须落在网格线上）。
- 零厚度导体边缘场奇异使收敛阶 ≈1，提供一阶 Richardson 外推 2·v(d/2) − v(d)。
- 三个几何族：cps_quasistatic（共面带，无地有限厚基板）、
  suspended_stripline_quasistatic（悬置带线，基板对称居中）、
  microstrip_quasistatic（微带，验证锚）。

验证锚（tests/unit/test_quasistatic_fd.py）：
- 微带 vs Hammerstad–Jensen 静态 εeff（skrf MLine，4 几何含 εr=9.8）：+0.18~+0.32%
  （d0=h/40，HJ 自身精度 ~0.2%）；
- CPS h→∞ 半空间极限 (1+εr)/2：−0.1%（w=s=0.5、h=8mm）；
- 零厚度带状线空气 Z0 vs Cohn 精确闭式 `_stripline_z0`：−0.5%（d0=b/160，收敛向上）；
- 悬置带线 h→b 全填充：εeff→εr。
两份未入库的临时 FD（旧 3.02 / 2.36，refs §11.2 旧口径）均未过上述基准，已撤。

约定：几何单位 mm；返回 C 单位 F/m、Z 单位 Ω；εeff = C(εr)/C(air)（准 TEM，
L' = 1/(c²·C_air)），Z0 = 1/(c·√(C_air·C))。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

_EPS0 = 8.8541878128e-12
_C0 = 299792458.0

#: 远区网格几何递增比（每格 +8%：远场衰减慢于网格增长，能量截断 <0.1%）
DEFAULT_GRADING_RATIO = 1.08


@dataclass(frozen=True)
class QuasiStaticResult:
    """一次准静态裁判的结果（eps_eff 为 Richardson 外推值或单档值）。"""

    eps_eff: float
    c_air_f_per_m: float
    c_diel_f_per_m: float
    z0_air_ohm: float
    z0_ohm: float
    d0_mm: float
    richardson: bool
    eps_eff_coarse: float
    eps_eff_fine: float
    n_nodes: int

    def as_dict(self) -> dict[str, float | bool | int]:
        return {
            "eps_eff": self.eps_eff,
            "c_air_f_per_m": self.c_air_f_per_m,
            "c_diel_f_per_m": self.c_diel_f_per_m,
            "z0_air_ohm": self.z0_air_ohm,
            "z0_ohm": self.z0_ohm,
            "d0_mm": self.d0_mm,
            "richardson": self.richardson,
            "eps_eff_coarse": self.eps_eff_coarse,
            "eps_eff_fine": self.eps_eff_fine,
            "n_nodes": self.n_nodes,
        }


# ─── 网格构造 ────────────────────────────────────────────────────────────────

def graded_lines(x0: float, x1: float, d0: float,
                 ratio: float = DEFAULT_GRADING_RATIO) -> np.ndarray:
    """从 x0 向 x1 的网格线：首格 d0、逐格 ×ratio，末格截到 x1（含两端点）。

    x1 == x0 时返回单点；余距 <1.5·当前格宽时直接以 x1 收口（避免 nm 级末格，
    #152 同族守卫）。
    """
    if abs(x1 - x0) <= 1e-15:
        return np.array([x0])
    sgn = 1.0 if x1 > x0 else -1.0
    pts = [x0]
    d = float(d0)
    while (x1 - pts[-1]) * sgn > 1.5 * d:
        pts.append(pts[-1] + sgn * d)
        d *= ratio
    pts.append(x1)
    return np.array(pts)


def uniform_lines(x0: float, x1: float, d0: float) -> np.ndarray:
    """[x0, x1] 上格宽 ≈d0 的均匀网格线（含端点；至少 2 格；x1==x0 返回单点）。"""
    if abs(x1 - x0) <= 1e-15:
        return np.array([x0])
    n = max(2, round(abs(x1 - x0) / d0))
    return np.linspace(x0, x1, n + 1)


def concat_lines(*segments: np.ndarray) -> np.ndarray:
    """拼接首尾相接的线段（去掉重复接点），保证严格单调。"""
    out: list[float] = []
    for seg in segments:
        for v in np.asarray(seg, dtype=float):
            if out and abs(v - out[-1]) <= 1e-15:
                continue
            out.append(float(v))
    arr = np.array(out)
    if arr.size > 1 and not (np.all(np.diff(arr) > 0) or np.all(np.diff(arr) < 0)):
        raise ValueError("网格线拼接后非严格单调（段顺序或方向错误）")
    return arr if arr.size == 1 or arr[1] > arr[0] else arr[::-1]


# ─── 变分 FD 求解 ───────────────────────────────────────────────────────────

def energy_quasistatic(xs: np.ndarray, zs: np.ndarray, eps_cell: np.ndarray,
                       dirichlet: dict[int, float]) -> float:
    """张量网格 (xs, zs) 上解 ∇·(ε∇φ)=0，返回 W = ½Σ g·Δφ²（ε 以 ε0=1 计）。

    eps_cell[i, j] 为 cell(i, j) = [xs[i], xs[i+1]]×[zs[j], zs[j+1]] 的相对介电
    常数；dirichlet 以节点号 n = i·nz + j 索引；非 Dirichlet 外边界 = 自然
    Neumann（∂φ/∂n=0）。
    """
    xs = np.asarray(xs, dtype=float)
    zs = np.asarray(zs, dtype=float)
    nx, nz = xs.size, zs.size
    if eps_cell.shape != (nx - 1, nz - 1):
        raise ValueError(f"eps_cell 形状 {eps_cell.shape} ≠ ({nx - 1}, {nz - 1})")
    dx = np.diff(xs)
    dz = np.diff(zs)
    if np.any(dx <= 0) or np.any(dz <= 0):
        raise ValueError("网格线必须严格递增")
    n_nodes = nx * nz

    # 水平边 (i,j)-(i+1,j)：ε 权 = 下 cell(i,j−1)·dz/2 + 上 cell(i,j)·dz/2
    wz = np.zeros((nx - 1, nz))
    wz[:, 1:] += eps_cell * dz[None, :] / 2.0
    wz[:, :-1] += eps_cell * dz[None, :] / 2.0
    g_h = (wz / dx[:, None]).ravel()
    ii, jj = np.meshgrid(np.arange(nx - 1), np.arange(nz), indexing="ij")
    h1 = (ii * nz + jj).ravel()
    h2 = ((ii + 1) * nz + jj).ravel()
    # 竖直边 (i,j)-(i,j+1)：ε 权 = 左 cell(i−1,j)·dx/2 + 右 cell(i,j)·dx/2
    wx = np.zeros((nx, nz - 1))
    wx[1:, :] += eps_cell * dx[:, None] / 2.0
    wx[:-1, :] += eps_cell * dx[:, None] / 2.0
    g_v = (wx / dz[None, :]).ravel()
    ii, jj = np.meshgrid(np.arange(nx), np.arange(nz - 1), indexing="ij")
    v1 = (ii * nz + jj).ravel()
    v2 = (ii * nz + jj + 1).ravel()

    n1 = np.concatenate([h1, v1])
    n2 = np.concatenate([h2, v2])
    g = np.concatenate([g_h, g_v])
    a = sp.coo_matrix(
        (np.concatenate([g, g, -g, -g]),
         (np.concatenate([n1, n2, n1, n2]), np.concatenate([n1, n2, n2, n1]))),
        shape=(n_nodes, n_nodes)).tocsr()

    phi = np.zeros(n_nodes)
    fixed = np.zeros(n_nodes, dtype=bool)
    for n, v in dirichlet.items():
        phi[n] = v
        fixed[n] = True
    if not fixed.any():
        raise ValueError("至少需要一个 Dirichlet 节点（导体电位）")
    free = ~fixed
    a_ff = a[free][:, free].tocsc()
    rhs = -(a[free][:, fixed] @ phi[fixed])
    phi[free] = spla.spsolve(a_ff, rhs)
    dphi = phi[n1] - phi[n2]
    return float(0.5 * np.sum(g * dphi * dphi))


def richardson_first_order(v_coarse: float, v_fine: float) -> float:
    """一阶 Richardson 外推（格宽减半）：v∞ ≈ 2·v(d/2) − v(d)。"""
    return 2.0 * v_fine - v_coarse


def _finish(c_diel_eps0: float, c_air_eps0: float, d0: float,
            richardson: bool, eps_coarse: float, eps_fine: float,
            n_nodes: int) -> QuasiStaticResult:
    eps_eff = richardson_first_order(eps_coarse, eps_fine) if richardson else eps_fine
    c_air = c_air_eps0 * _EPS0
    c_diel = eps_eff * c_air
    z0_air = 1.0 / (_C0 * c_air)
    return QuasiStaticResult(
        eps_eff=float(eps_eff), c_air_f_per_m=float(c_air),
        c_diel_f_per_m=float(c_diel), z0_air_ohm=float(z0_air),
        z0_ohm=float(z0_air / np.sqrt(eps_eff)), d0_mm=float(d0),
        richardson=bool(richardson), eps_eff_coarse=float(eps_coarse),
        eps_eff_fine=float(eps_fine), n_nodes=int(n_nodes))


# ─── 几何族：CPS（共面带，无地有限厚基板）────────────────────────────────────

def cps_capacitance_eps0(w_mm: float, gap_mm: float, h_mm: float, eps_r: float,
                         d0_mm: float, xmax_mm: float | None = None,
                         zmax_mm: float | None = None,
                         ratio: float = DEFAULT_GRADING_RATIO) -> tuple[float, int]:
    """CPS 半域：x∈[0,xmax]，对称轴 x=0 为 φ=0（奇模 Dirichlet），带 x∈[a,b]、
    z=0（基板上表面）φ=1；基板 z∈[−h,0] εr、其余空气；外边界 Neumann。

    两带 ±1 V → V=2、W_total=2·W_half → C = 2·W_total/V² = W_half（ε0 单位）。
    缺省外边界 20·b：CPS 空气场偶极衰减慢，8mm 域 C_air 截断 −3%（Z0_air +3%）
    而 εeff 比值不受影响（≤0.1%）；20·b 下 Z0_air 与共形闭式差 +0.03%（实测）。
    """
    a, b = gap_mm / 2.0, gap_mm / 2.0 + w_mm
    xmax = xmax_mm if xmax_mm is not None else max(8.0, 20.0 * b)
    zmax = zmax_mm if zmax_mm is not None else max(8.0, 20.0 * b, 3.0 * h_mm)
    xs = concat_lines(uniform_lines(0.0, a, d0_mm), uniform_lines(a, b, d0_mm),
                      graded_lines(b, xmax, d0_mm, ratio))
    zs = concat_lines(graded_lines(-h_mm, -zmax, d0_mm, ratio)[::-1],
                      uniform_lines(-h_mm, 0.0, d0_mm),
                      graded_lines(0.0, zmax, d0_mm, ratio))
    nx, nz = xs.size, zs.size
    eps = np.ones((nx - 1, nz - 1))
    zc = 0.5 * (zs[:-1] + zs[1:])
    eps[:, (zc > -h_mm) & (zc < 0.0)] = eps_r
    j0 = int(np.argmin(np.abs(zs)))
    ia = int(np.argmin(np.abs(xs - a)))
    ib = int(np.argmin(np.abs(xs - b)))
    if abs(zs[j0]) > 1e-12 or abs(xs[ia] - a) > 1e-12 or abs(xs[ib] - b) > 1e-12:
        raise RuntimeError("CPS 网格线未精确落在带缘/基板面（构造错误）")
    diri = {0 * nz + j: 0.0 for j in range(nz)}
    for i in range(ia, ib + 1):
        diri[i * nz + j0] = 1.0
    return energy_quasistatic(xs, zs, eps, diri), nx * nz


def cps_quasistatic(w_mm: float, gap_mm: float, h_mm: float, eps_r: float,
                    d0_mm: float | None = None, richardson: bool = True,
                    **grid_kw: float) -> QuasiStaticResult:
    """CPS εeff/Z0 裁判。缺省 d0 = min(h/20, gap/8)；richardson=True 时再算 d0/2
    并一阶外推（εeff 与 C_air 均外推）。"""
    if w_mm <= 0 or gap_mm <= 0 or h_mm <= 0 or eps_r < 1.0:
        raise ValueError("CPS 裁判定义域：w>0、gap>0、h>0、εr≥1")
    d0 = d0_mm if d0_mm is not None else min(h_mm / 20.0, gap_mm / 8.0)
    steps = (d0, d0 / 2.0) if richardson else (d0,)
    eps_v, cair_v, n_nodes = [], [], 0
    for d in steps:
        c_d, n_nodes = cps_capacitance_eps0(w_mm, gap_mm, h_mm, eps_r, d, **grid_kw)
        c_a, _ = cps_capacitance_eps0(w_mm, gap_mm, h_mm, 1.0, d, **grid_kw)
        eps_v.append(c_d / c_a)
        cair_v.append(c_a)
    c_air = (richardson_first_order(cair_v[0], cair_v[1]) if richardson
             else cair_v[-1])
    return _finish(eps_v[-1] * c_air, c_air, d0, richardson, eps_v[0], eps_v[-1],
                   n_nodes)


# ─── 几何族：悬置带线（基板对称居中，两地=腔壁）────────────────────────────────

def suspended_stripline_capacitance_eps0(
        w_mm: float, b_mm: float, h_mm: float, eps_r: float, d0_mm: float,
        xmax_factor: float = 8.0,
        ratio: float = DEFAULT_GRADING_RATIO) -> tuple[float, int]:
    """悬置带线半域：x∈[0, xmax_factor·b]，对称轴 x=0 Neumann（偶模）；地 z=0、
    z=b φ=0；零厚度带 z=b/2、x∈[0,w/2] φ=1；基板 z∈[b/2−h/2, b/2+h/2] εr。

    V=1、W_total=2·W_half → C = 4·W_half（ε0 单位）。h=b（全填充）/h=0（空气）
    两支退化段自动跳过。
    """
    if w_mm <= 0 or b_mm <= 0 or eps_r < 1.0 or h_mm < 0 or h_mm > b_mm:
        raise ValueError("悬置带线裁判定义域：w>0、b>0、0≤h≤b、εr≥1")
    xmax = xmax_factor * b_mm
    xs = concat_lines(uniform_lines(0.0, w_mm / 2.0, d0_mm),
                      graded_lines(w_mm / 2.0, xmax, d0_mm, ratio))
    z1, z2 = b_mm / 2.0 - h_mm / 2.0, b_mm / 2.0 + h_mm / 2.0
    zs = concat_lines(uniform_lines(0.0, z1, d0_mm),
                      uniform_lines(z1, b_mm / 2.0, d0_mm),
                      uniform_lines(b_mm / 2.0, z2, d0_mm),
                      uniform_lines(z2, b_mm, d0_mm))
    nx, nz = xs.size, zs.size
    eps = np.ones((nx - 1, nz - 1))
    zc = 0.5 * (zs[:-1] + zs[1:])
    eps[:, (zc > z1) & (zc < z2)] = eps_r
    jm = int(np.argmin(np.abs(zs - b_mm / 2.0)))
    iw = int(np.argmin(np.abs(xs - w_mm / 2.0)))
    if abs(zs[jm] - b_mm / 2.0) > 1e-12 or abs(xs[iw] - w_mm / 2.0) > 1e-12:
        raise RuntimeError("悬置带线网格线未精确落在带缘/中面（构造错误）")
    diri: dict[int, float] = {}
    for i in range(nx):
        diri[i * nz] = 0.0
        diri[i * nz + nz - 1] = 0.0
    for i in range(iw + 1):
        diri[i * nz + jm] = 1.0
    return 4.0 * energy_quasistatic(xs, zs, eps, diri), nx * nz


def suspended_stripline_quasistatic(
        w_mm: float, b_mm: float, h_mm: float, eps_r: float,
        d0_mm: float | None = None, richardson: bool = True,
        **grid_kw: float) -> QuasiStaticResult:
    """悬置带线 εeff/Z0 裁判。缺省 d0 = b/40（标称 b=1.016 → 0.0254mm）。"""
    d0 = d0_mm if d0_mm is not None else b_mm / 40.0
    steps = (d0, d0 / 2.0) if richardson else (d0,)
    eps_v, cair_v, n_nodes = [], [], 0
    for d in steps:
        c_d, n_nodes = suspended_stripline_capacitance_eps0(
            w_mm, b_mm, h_mm, eps_r, d, **grid_kw)
        c_a, _ = suspended_stripline_capacitance_eps0(
            w_mm, b_mm, h_mm, 1.0, d, **grid_kw)
        eps_v.append(c_d / c_a)
        cair_v.append(c_a)
    c_air = (richardson_first_order(cair_v[0], cair_v[1]) if richardson
             else cair_v[-1])
    return _finish(eps_v[-1] * c_air, c_air, d0, richardson, eps_v[0], eps_v[-1],
                   n_nodes)


# ─── 几何族：微带（验证锚，对照 Hammerstad–Jensen）──────────────────────────────

def microstrip_capacitance_eps0(w_mm: float, h_mm: float, eps_r: float,
                                d0_mm: float, xmax_mm: float = 20.0,
                                zmax_mm: float = 20.0,
                                ratio: float = DEFAULT_GRADING_RATIO
                                ) -> tuple[float, int]:
    """微带半域：x∈[0,xmax] 对称轴 Neumann；地 z=0 φ=0；零厚度带 z=h、x∈[0,w/2]
    φ=1；基板 z∈[0,h] εr。C = 4·W_half（ε0 单位）。"""
    if w_mm <= 0 or h_mm <= 0 or eps_r < 1.0:
        raise ValueError("微带裁判定义域：w>0、h>0、εr≥1")
    xs = concat_lines(uniform_lines(0.0, w_mm / 2.0, d0_mm),
                      graded_lines(w_mm / 2.0, xmax_mm, d0_mm, ratio))
    zs = concat_lines(uniform_lines(0.0, h_mm, d0_mm),
                      graded_lines(h_mm, zmax_mm, d0_mm, ratio))
    nx, nz = xs.size, zs.size
    eps = np.ones((nx - 1, nz - 1))
    zc = 0.5 * (zs[:-1] + zs[1:])
    eps[:, zc < h_mm] = eps_r
    jh = int(np.argmin(np.abs(zs - h_mm)))
    iw = int(np.argmin(np.abs(xs - w_mm / 2.0)))
    if abs(zs[jh] - h_mm) > 1e-12 or abs(xs[iw] - w_mm / 2.0) > 1e-12:
        raise RuntimeError("微带网格线未精确落在带缘/基板面（构造错误）")
    diri = {i * nz: 0.0 for i in range(nx)}
    for i in range(iw + 1):
        diri[i * nz + jh] = 1.0
    return 4.0 * energy_quasistatic(xs, zs, eps, diri), nx * nz


def microstrip_quasistatic(w_mm: float, h_mm: float, eps_r: float,
                           d0_mm: float | None = None, richardson: bool = True,
                           **grid_kw: float) -> QuasiStaticResult:
    """微带静态 εeff/Z0 裁判（对照 HJ）。缺省 d0 = h/20。"""
    d0 = d0_mm if d0_mm is not None else h_mm / 20.0
    steps = (d0, d0 / 2.0) if richardson else (d0,)
    eps_v, cair_v, n_nodes = [], [], 0
    for d in steps:
        c_d, n_nodes = microstrip_capacitance_eps0(w_mm, h_mm, eps_r, d, **grid_kw)
        c_a, _ = microstrip_capacitance_eps0(w_mm, h_mm, 1.0, d, **grid_kw)
        eps_v.append(c_d / c_a)
        cair_v.append(c_a)
    c_air = (richardson_first_order(cair_v[0], cair_v[1]) if richardson
             else cair_v[-1])
    return _finish(eps_v[-1] * c_air, c_air, d0, richardson, eps_v[0], eps_v[-1],
                   n_nodes)
