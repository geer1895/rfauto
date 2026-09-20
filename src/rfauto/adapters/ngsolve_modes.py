"""NGSolve 二维横截面模式求解器（W3⑧a 路线 A：槽线模式场 → openEMS WaveguidePort）。

数学列式（推导入档，#1b 先验模型）
----------------------------------
设传播沿 X、横截面坐标 (u,v)=(y,z)，场形 E=[e_t(u,v)+x̂·e_z(u,v)]·e^{−jβX}、
H 同构，时谐约定 e^{+jωt}（工程口径）。从三维矢量波方程弱式
∫μ⁻¹(∇×E)·(∇×F) − ω²∫ε E·F = 0 直接代入行波依赖展开（不对 HCurl 场做
非法的分部积分），得二次束 Q(β)=β²M+βC+K：

  K = ∫μ⁻¹(curl_t E_t)(curl_t F_t) + ∫μ⁻¹ ∇e_z·∇φ − ω²∫ε(E_t·F_t + e_z φ)
  C = j ∫μ⁻¹ (E_t·∇φ − ∇e_z·F_t)          （反对称：β 线性项）
  M = −∫μ⁻¹ E_t·F_t                          （仅 E_t 块）

空间 E_t ∈ HCurl(order)（PEC：切向 Dirichlet）、e_z ∈ H1(order+1)（PEC：
Dirichlet）。伴随量由 Maxwell 方程解析给出（e_t 取实规一后 H_t 自动实）：

  H_u = (j/(ωμ)) ∂e_z/∂v − (β/(ωμ)) E_v
  H_v = (β/(ωμ)) E_u − (j/(ωμ)) ∂e_z/∂u
  h_z = (j/(ωμ)) curl_t E_t

二次束线性化 A y = β B y（y=[x; βx]）：
  A = [[0, I], [−K, −C]]，B = [[I, 0], [0, −M]]
scipy.sparse.linalg.eigs 移位反演（σ=β_guess）取目标模式；±β 成对出现，
选 Re>0 且 |Im/Re| 最小者。

硬自检（#118 裁判纪律：数值算法的裁判是解析闭式，不是自证）
----------------------------------------------------------
- 矩形波导 TE10：εr 均匀填充 PEC 盒必须复现 β=√(k²−(π/a)²)。实测
  order=1/2, maxh=2mm：−0.125% / −0.0001%（WR-90@10GHz，单测钉住 ≤0.5%）。
- 平行板 TEM：E=v̂ 均匀、e_z=0 精确解，β=k√εr（复现 A9 锚，实测 ~1e-7）。
- 其余本征值应为凋落模（纯虚 β），无伪实模。

槽线截面：金属零厚线 z=h（|y|>w/2 PEC Dirichlet、缝内自然连续）、基板
z∈[0,h]（IfPos 逐点 εr）、上下空气域、外框 PEC（屏蔽槽线口径——框足够大时
β 对框位置不敏感，屏蔽敏感性由 smoke 量化）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

C0 = 299792458.0
MU0 = 4.0e-7 * math.pi


def ngsolve_installed() -> bool:
    """ngsolve/netgen 可导入性（与 ngsolve_adapter 同口径，不触发 import）。"""
    import importlib.util

    return (importlib.util.find_spec("ngsolve") is not None
            and importlib.util.find_spec("netgen") is not None)


# ── 截面描述 ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SlotlineSection:
    """开放槽线横截面（mm 入参；内部转米）。

    几何：金属零厚线在 z=h；槽居中（|y| ≤ w/2）；基板 z∈[0,h]（εr）；
    z<0 空气（厚 z_bot）、z>h 空气（厚 z_top）；外框 PEC（半宽 y_half）。
    """

    w_mm: float
    h_mm: float
    er: float
    y_half_mm: float = 60.0
    z_bot_mm: float = 30.0
    z_top_mm: float = 30.0

    def __post_init__(self) -> None:
        for name in ("w_mm", "h_mm", "er", "y_half_mm", "z_bot_mm", "z_top_mm"):
            v = float(getattr(self, name))
            if not math.isfinite(v) or v <= 0.0:
                raise ValueError(f"SlotlineSection.{name} 必须为正有限，得到 {v!r}")
        if self.w_mm >= 2.0 * self.y_half_mm:
            raise ValueError("SlotlineSection: 槽宽必须小于域半宽的两倍")


@dataclass
class TransverseMode:
    """单个横截面模式的采样场与派生量（网格行主序 data[i,j] @ (y[i], z[j])）。"""

    freq_ghz: float
    beta_rad_m: float
    z0_ohm: float                 # 功率-电压特性阻抗 Z0=V0²/(2P)
    v_slot: complex               # 跨槽电压 V0 = ∫ E_y dy @ z=h（单位模幅）
    p_flow: float                 # 纵向功率流 P（单位模幅）
    y_grid_m: np.ndarray = field(default_factory=lambda: np.empty(0))
    z_grid_m: np.ndarray = field(default_factory=lambda: np.empty(0))
    e_t: np.ndarray = field(default_factory=lambda: np.empty((0, 0, 2), complex))
    h_t: np.ndarray = field(default_factory=lambda: np.empty((0, 0, 2), complex))
    e_z: np.ndarray = field(default_factory=lambda: np.empty((0, 0), complex))
    imag_residual: float = 0.0    # 规一后 E_t 虚部残差（规一质量指标）
    imag_over_real_eig: float = 0.0
    n_eigs_found: int = 0
    n_tris: int = 0
    n_dof: int = 0


# ── 网格构建 ─────────────────────────────────────────────────────────────────

def build_slotline_mesh(sec: SlotlineSection, maxh_mm: float = 3.0,
                        slot_near_mm: float | None = None,
                        dense_halfwidth_mm: float | None = None):
    """槽线截面 2D 分级网格（netgen.geom2d）。

    - 金属线 z=h 分五段：远 PEC | 近 PEC | 缝（自然）| 近 PEC | 远 PEC；
      近段（|y| ≤ dense_halfwidth，默认 4w）与缝段局部 maxh = slot_near
      （默认 w/8）；z=0 基板/空气界面同样近段加密。
    - 全域 maxh_mm 控制远场稀疏区（默认 3mm）。
    返回 ngsolve Mesh（2D，坐标 (u,v)=(y,z) 米）。
    """
    if not ngsolve_installed():
        raise RuntimeError("ngsolve 未安装（.venv/Scripts/python.exe -m pip install ngsolve）")
    from netgen.geom2d import SplineGeometry

    w = sec.w_mm * 1e-3
    h = sec.h_mm * 1e-3
    yh = sec.y_half_mm * 1e-3
    zb = sec.z_bot_mm * 1e-3
    zt = sec.z_top_mm * 1e-3
    near = (slot_near_mm if slot_near_mm is not None else sec.w_mm / 8.0) * 1e-3
    dense = (dense_halfwidth_mm if dense_halfwidth_mm is not None
             else 4.0 * sec.w_mm) * 1e-3
    maxh = maxh_mm * 1e-3
    if near > w / 4:
        raise ValueError(
            f"slot_near_mm={slot_near_mm} 过粗：槽缘网格必须 ≲ w/4="
            f"{sec.w_mm / 4:.4g}mm（缝场分辨率，#212 家族纪律）")
    if not (w / 2 < dense < yh):
        raise ValueError("dense_halfwidth 须在 (w/2, y_half) 内")

    geo = SplineGeometry()

    def pt(x, y, mh=None):
        return geo.AppendPoint(x, y) if mh is None else geo.AppendPoint(x, y, maxh=mh)

    p = {
        "bl": pt(-yh, -zb), "br": pt(yh, -zb), "rl": pt(yh, 0.0), "rh": pt(yh, h),
        "rt": pt(yh, h + zt), "tl": pt(-yh, h + zt), "lh": pt(-yh, h), "ll": pt(-yh, 0.0),
        # 金属面 z=h：近段端点与缝缘（缝缘点 maxh=near）
        "hdl": pt(-dense, h, near * 4), "ml": pt(-w / 2, h, near), "mr": pt(w / 2, h, near),
        "hdr": pt(dense, h, near * 4),
        # 基板/空气界面 z=0 近段端点
        "zdl": pt(-dense, 0.0, near * 4), "zdr": pt(dense, 0.0, near * 4),
    }
    # 外边界（CCW 遍历，左侧=内域：下空气=3、基板=1、上空气=2；右侧=0 外部）
    for a, b, dom in (("bl", "br", 3), ("br", "rl", 3), ("rl", "rh", 1), ("rh", "rt", 2),
                      ("rt", "tl", 2), ("tl", "lh", 2), ("lh", "ll", 1), ("ll", "bl", 3)):
        geo.Append(["line", p[a], p[b]], bc="outer", leftdomain=dom, rightdomain=0)
    # z=0 界面（+x 遍历：左=上方基板 1、右=下方空气 3；无 BC）
    geo.Append(["line", p["ll"], p["zdl"]], leftdomain=1, rightdomain=3)
    geo.Append(["line", p["zdl"], p["zdr"]], leftdomain=1, rightdomain=3, maxh=near * 2)
    geo.Append(["line", p["zdr"], p["rl"]], leftdomain=1, rightdomain=3)
    # z=h 金属面（+x 遍历：左=上方空气 2、右=下方基板 1）
    geo.Append(["line", p["lh"], p["hdl"]], bc="pec", leftdomain=2, rightdomain=1)
    geo.Append(["line", p["hdl"], p["ml"]], bc="pec", leftdomain=2, rightdomain=1,
               maxh=near * 2)
    geo.Append(["line", p["ml"], p["mr"]], bc="slotface", leftdomain=2, rightdomain=1,
               maxh=near)
    geo.Append(["line", p["mr"], p["hdr"]], bc="pec", leftdomain=2, rightdomain=1,
               maxh=near * 2)
    geo.Append(["line", p["hdr"], p["rh"]], bc="pec", leftdomain=2, rightdomain=1)
    return mesh_of(geo, maxh)


def mesh_of(geo, maxh: float):
    from ngsolve import Mesh

    return Mesh(geo.GenerateMesh(maxh=maxh))


def build_rect_waveguide_mesh(a_mm: float, b_mm: float, maxh_mm: float):
    """全 PEC 矩形截面（TE10 硬门；坐标 (u,v) 即波导 (a,b) 平面）。"""
    if not ngsolve_installed():
        raise RuntimeError("ngsolve 未安装")
    from netgen.geom2d import SplineGeometry

    a, b = a_mm * 1e-3, b_mm * 1e-3
    geo = SplineGeometry()
    pts = [geo.AppendPoint(*pt) for pt in [(0, 0), (a, 0), (a, b), (0, b)]]
    for i in range(4):
        geo.Append(["line", pts[i], pts[(i + 1) % 4]], bc="pec",
                   leftdomain=1, rightdomain=0)
    return mesh_of(geo, maxh_mm * 1e-3)


# ── 二次束装配与求解 ──────────────────────────────────────────────────────────

def _make_eps_cf(sec: SlotlineSection | None, eps_r: float):
    """逐点 ε CF：槽线截面用 IfPos 分层（v=h 基板上、v∈(0,h) 基板、v<0 空气）。"""
    from ngsolve import CF, IfPos
    from ngsolve import y as ng_y

    if sec is None:
        return CF(float(eps_r))
    h = sec.h_mm * 1e-3
    er = float(sec.er)
    return IfPos(ng_y - h, CF(1.0), IfPos(ng_y, CF(er), CF(1.0)))


def _assemble_pencil(mesh, eps_cf, k0: float, order: int, dirichlet: str,
                     sec: SlotlineSection | None):
    """装配 K/C/M 并按自由度约束切片为 scipy CSR；返回 (fes, K, C, M)。"""
    import scipy.sparse as sp
    from ngsolve import H1, BilinearForm, HCurl, curl, dx, grad

    fes_e = HCurl(mesh, order=order, complex=True, dirichlet=dirichlet)
    fes_z = H1(mesh, order=order + 1, complex=True, dirichlet=dirichlet)
    fes = fes_e * fes_z
    (et, ez), (ft, phi) = fes.TnT()

    k_mat = BilinearForm(fes)
    k_mat += (curl(et) * curl(ft) + grad(ez) * grad(phi)
              - k0 * k0 * eps_cf * (et * ft + ez * phi)) * dx
    c_mat = BilinearForm(fes)
    c_mat += 1j * (et * grad(phi) - grad(ez) * ft) * dx
    m_mat = BilinearForm(fes)
    m_mat += -(et * ft) * dx
    for bf in (k_mat, c_mat, m_mat):
        bf.Assemble()

    n = fes.ndof
    free = np.array([bool(fes.FreeDofs()[i]) for i in range(n)])
    idx = np.where(free)[0]

    def to_csr(bf):
        rows, cols, vals = bf.mat.COO()
        a = sp.csr_matrix((np.asarray(vals), (np.asarray(rows), np.asarray(cols))),
                          shape=(n, n))
        return a[idx][:, idx].tocsc()

    return fes, idx, to_csr(k_mat), to_csr(c_mat), to_csr(m_mat)


def _solve_pencil_beta(k_mat, c_mat, m_mat, beta_guess: float,
                       n_eigs: int = 6) -> tuple[np.ndarray, np.ndarray]:
    """线性化二次束移位反演本征求解；返回 (eigenvalues, eigenvectors)。"""
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    nf = k_mat.shape[0]
    eye = sp.identity(nf, format="csc", dtype=complex)
    zero = sp.csc_matrix((nf, nf), dtype=complex)
    a_lin = sp.bmat([[zero, eye], [-k_mat, -c_mat]], format="csc")
    b_lin = sp.bmat([[eye, zero], [zero, -m_mat]], format="csc")
    if beta_guess <= 0 or not math.isfinite(beta_guess):
        raise ValueError(f"beta_guess 必须为正有限，得到 {beta_guess!r}")
    vals, vecs = spla.eigs(a_lin, k=n_eigs, M=b_lin, sigma=beta_guess, which="LM")
    return vals, vecs


def _pick_physical_mode(vals: np.ndarray, vecs: np.ndarray,
                        beta_guess: float, max_skew: float = 0.05
                        ) -> tuple[complex, np.ndarray]:
    """选物理传播模式：Re>0、|Im/Re| ≤ max_skew（近实 β；凋落/复模拒绝）、
    离 β_guess 不远（>4 倍视为离群）；多候选取 |Im/Re| 最小者。无候选 RuntimeError。"""
    order = np.argsort(np.abs(vals - beta_guess))
    best = None
    for i in order:
        v = complex(vals[i])
        if v.real <= 0:
            continue
        if abs(v.real - beta_guess) > 4.0 * beta_guess:
            continue
        skew = abs(v.imag) / max(v.real, 1e-300)
        if skew > max_skew:
            continue
        if best is None or skew < best[0]:
            best = (skew, v, vecs[:, i])
    if best is None:
        raise RuntimeError(
            f"二次束未找到 β≈{beta_guess:.4g} 附近的物理模式（本征值：{np.round(vals, 3)}）")
    # 线性化向量 y=[x; βx]：取前半 x（原二次束自由度）
    full = best[2]
    return best[1], full[: full.shape[0] // 2]


def _lift_to_gridfunction(vec: np.ndarray, idx: np.ndarray, fes) -> tuple:
    """自由度向量 → 复合空间 GridFunction 及其 (E_t, e_z) 分量。"""
    from ngsolve import GridFunction

    gf = GridFunction(fes)
    gf.vec[:] = 0.0
    gf.vec.FV().NumPy()[idx] = vec
    return gf, gf.components[0], gf.components[1]


def _sample_fields(mesh, gfe, gfz, beta: float, omega: float,
                   y_grid: np.ndarray, z_grid: np.ndarray):
    """结构化网格采样 E_t/E_z 与解析 H_t（未规一的本征向量场）；返回 (e_t, e_z, h_t)。

    H 由列式推导的解析式给出（H_u=(j/ωμ)∂v e_z − (β/ωμ)E_v 等），时谐 e^{+jωt}；
    幅值/相位规一在 solve_slotline_mode 内按"跨槽电压 V0=1V 实正"统一施加。
    """
    # e_z 梯度（H1 GridFunction 的一阶导，逐点评估）；curl_t E_t 只进 h_z，
    # 模式文件仅需横向分量，不采样
    from ngsolve import grad as ng_grad

    gfz_grad = ng_grad(gfz)  # 2 分量 CF（H1 GridFunction 梯度）

    ny, nz = len(y_grid), len(z_grid)
    e_t = np.empty((ny, nz, 2), dtype=complex)
    e_z = np.empty((ny, nz), dtype=complex)
    h_t = np.empty((ny, nz, 2), dtype=complex)
    for i, yv in enumerate(y_grid):
        for j, zv in enumerate(z_grid):
            mpt = mesh(float(yv), float(zv))
            e2 = gfe(mpt)
            eu, evv = complex(e2[0]), complex(e2[1])   # (u,v)=(y,z) 分量
            ezv = complex(gfz(mpt))
            gz = gfz_grad(mesh(float(yv), float(zv)))
            du_ez, dv_ez = complex(gz[0]), complex(gz[1])
            e_t[i, j] = (eu, evv)
            e_z[i, j] = ezv
            # Maxwell 解析伴随（模块 docstring）：H_u=(j/ωμ)∂v e_z − (β/ωμ)E_v，
            # H_v=(β/ωμ)E_u − (j/ωμ)∂u e_z
            h_t[i, j] = ((1j * dv_ez - beta * evv) / (omega * MU0),
                         (beta * eu - 1j * du_ez) / (omega * MU0))
    return e_t, e_z, h_t


def _fem_power_voltage(mesh, gfe, gfz, beta: float, omega: float) -> tuple[complex, float]:
    """FEM 精确积分：跨槽电压 V0=∫_{slotface} E_y dl、功率流 P=½Re∫(E×H*)·x̂ dA。

    采样网格梯形积分在缝缘 1/√r 奇性下不收敛（实测 Z0 随网格 85→123Ω 跳变），
    改用 NGSolve Integrate 在 FEM 解上直接积分（H 用解析伴随 CF）。
    """
    from ngsolve import BND, Conj, Integrate
    from ngsolve import grad as ng_grad

    gz = ng_grad(gfz)
    h_u = (1j * gz[1] - beta * gfe[1]) / (omega * MU0)
    h_v = (beta * gfe[0] - 1j * gz[0]) / (omega * MU0)
    p = 0.5 * complex(Integrate(gfe[0] * Conj(h_v) - gfe[1] * Conj(h_u), mesh)).real
    v0 = complex(Integrate(gfe[0], mesh, BND, definedon=mesh.Boundaries("slotface")))
    return v0, float(p)


def graded_axis(lo: float, hi: float, dense_lo: float, dense_hi: float,
                step_dense: float, n_coarse_side: int) -> np.ndarray:
    """一维分级采样轴：[dense_lo, dense_hi] 步长 step_dense，两侧各 n_coarse_side
    个均匀点渐疏至 lo/hi；端点精确覆盖（模式文件网格，CSModeData 允许非均匀）。"""
    if not (lo < dense_lo < dense_hi < hi):
        raise ValueError("graded_axis 需 lo < dense_lo < dense_hi < hi")
    if step_dense <= 0 or n_coarse_side < 1:
        raise ValueError("graded_axis 需 step_dense>0、n_coarse_side≥1")
    fine = np.arange(dense_lo, dense_hi + 0.5 * step_dense, step_dense)
    left = np.linspace(lo, dense_lo, n_coarse_side + 1)[:-1]
    right = np.linspace(dense_hi, hi, n_coarse_side + 1)[1:]
    ax = np.unique(np.concatenate([left, fine, right]))
    ax[0], ax[-1] = lo, hi
    return ax


def solve_slotline_mode(sec: SlotlineSection, freq_ghz: float,
                        beta_guess_rad_m: float | None = None,
                        order: int = 1, maxh_mm: float = 3.0,
                        slot_near_mm: float | None = None,
                        dense_halfwidth_mm: float | None = None,
                        n_eigs: int = 6,
                        sample_step_mm: float | None = None,
                        n_coarse_side: int = 24,
                        ) -> TransverseMode:
    """槽线截面单频模式求解：β、Z0、模式场网格（喂 openEMS 模式文件）。

    - beta_guess 缺省取闭式 slotline_beta（core.slotline，惰性导入）；
    - FEM 网格：build_slotline_mesh（远区 maxh_mm、缝缘 slot_near=w/8）；
    - 采样网格（米，分级）：y 在 ±dense_halfwidth（默认 4w）内步长
      sample_step（默认 w/10）、两侧各 n_coarse_side 点至 ±y_half；z 在
      [−dense, h+dense] 内同步长、上下各 n_coarse_side 点至域边。
    """
    if beta_guess_rad_m is None:
        from rfauto.core.slotline import slotline_beta

        beta_guess_rad_m = slotline_beta(sec.w_mm, sec.h_mm, sec.er, freq_ghz)
    k0 = 2.0 * math.pi * float(freq_ghz) * 1e9 / C0
    mesh = build_slotline_mesh(sec, maxh_mm=maxh_mm, slot_near_mm=slot_near_mm,
                               dense_halfwidth_mm=dense_halfwidth_mm)
    eps_cf = _make_eps_cf(sec, sec.er)
    fes, idx, k_m, c_m, m_m = _assemble_pencil(mesh, eps_cf, k0, order, "pec", sec)
    vals, vecs = _solve_pencil_beta(k_m, c_m, m_m, beta_guess_rad_m, n_eigs=n_eigs)
    beta_c, vec = _pick_physical_mode(vals, vecs, beta_guess_rad_m)
    beta = float(beta_c.real)
    _gf, gfe, gfz = _lift_to_gridfunction(vec, idx, fes)

    yh = sec.y_half_mm * 1e-3
    zb, zt = sec.z_bot_mm * 1e-3, sec.z_top_mm * 1e-3
    h = sec.h_mm * 1e-3
    dense = (dense_halfwidth_mm if dense_halfwidth_mm is not None
             else 4.0 * sec.w_mm) * 1e-3
    step = (sample_step_mm if sample_step_mm is not None else sec.w_mm / 10.0) * 1e-3
    y_grid = graded_axis(-yh, yh, -dense, dense, step, n_coarse_side)
    z_dense_lo = max(-dense, -zb * 0.5)
    z_dense_hi = min(h + dense, h + zt * 0.5)
    z_grid = graded_axis(-zb, h + zt, z_dense_lo, z_dense_hi, step, n_coarse_side)
    # 确保 z=0、z=h 两个界面恰在采样轴上（缝电压/界面场取行精确）
    z_grid = np.unique(np.concatenate([z_grid, [0.0, h]]))

    omega = 2.0 * math.pi * float(freq_ghz) * 1e9
    e_t, e_z, h_t = _sample_fields(mesh, gfe, gfz, beta, omega, y_grid, z_grid)
    v0_raw, p_raw = _fem_power_voltage(mesh, gfe, gfz, beta, omega)
    if not (p_raw > 0) or abs(v0_raw) < 1e-300:
        raise RuntimeError(
            f"模式功率流/槽电压异常 P={p_raw!r} V0={v0_raw!r}（伴随场/传播方向异常）")
    # 规一：跨槽电压 V0 = 1 V（实正）——模式文件幅值可复现、P=1/(2Z0)
    scale = 1.0 / v0_raw
    e_t *= scale
    e_z *= scale
    h_t *= scale
    v0 = 1.0 + 0.0j
    p_flow = p_raw / abs(v0_raw) ** 2
    z0 = 1.0 / (2.0 * p_flow)
    imag_res = float(np.abs(e_t.imag).max() / max(np.abs(e_t).max(), 1e-300))
    return TransverseMode(freq_ghz=float(freq_ghz), beta_rad_m=beta, z0_ohm=z0,
                          v_slot=v0, p_flow=p_flow, y_grid_m=y_grid,
                          z_grid_m=z_grid, e_t=e_t, h_t=h_t, e_z=e_z,
                          imag_residual=imag_res,
                          imag_over_real_eig=float(abs(beta_c.imag) / beta),
                          n_eigs_found=len(vals), n_tris=int(mesh.ne),
                          n_dof=int(fes.ndof))


def solve_rect_waveguide_te10_beta(a_mm: float, b_mm: float, eps_r: float,
                                   freq_ghz: float, order: int = 1,
                                   maxh_mm: float = 2.0) -> float:
    """TE10 硬门：PEC 矩形波导 β_NGSolve（对照 β=√(k²−(π/a)²)，调用方设门）。"""
    k0 = 2.0 * math.pi * float(freq_ghz) * 1e9 / C0
    fc = C0 / (2.0 * float(a_mm) * 1e-3 * math.sqrt(float(eps_r)))
    if float(freq_ghz) * 1e9 <= fc:
        raise ValueError(f"f={freq_ghz}GHz ≤ TE10 截止 {fc / 1e9:.4f}GHz，显式拒绝")
    beta_ref = math.sqrt(k0 * k0 - (math.pi / (float(a_mm) * 1e-3)) ** 2)
    mesh = build_rect_waveguide_mesh(a_mm, b_mm, maxh_mm)
    _fes, _idx, k_m, c_m, m_m = _assemble_pencil(mesh, _make_eps_cf(None, eps_r),
                                                 k0, order, "pec", None)
    vals, vecs = _solve_pencil_beta(k_m, c_m, m_m, beta_ref * 0.9)
    beta_c, _vec = _pick_physical_mode(vals, vecs, beta_ref)
    return float(beta_c.real)


def solve_parallel_plate_beta(w_mm: float, h_mm: float, eps_r: float,
                              freq_ghz: float, order: int = 1,
                              maxh_mm: float = 0.3) -> float:
    """平行板 TEM 锚：PEC 上下板 + 侧壁自然（PMC），β=k√εr（复现 A9 锚几何）。"""
    from netgen.geom2d import SplineGeometry

    w, h = w_mm * 1e-3, h_mm * 1e-3
    k0 = 2.0 * math.pi * float(freq_ghz) * 1e9 / C0
    geo = SplineGeometry()
    pts = [geo.AppendPoint(*pt) for pt in [(0, 0), (w, 0), (w, h), (0, h)]]
    for i, bc in enumerate(("pec", "pmc", "pec", "pmc")):
        geo.Append(["line", pts[i], pts[(i + 1) % 4]], bc=bc,
                   leftdomain=1, rightdomain=0)
    mesh = mesh_of(geo, maxh_mm * 1e-3)
    _fes, _idx, k_m, c_m, m_m = _assemble_pencil(mesh, _make_eps_cf(None, eps_r),
                                                 k0, order, "pec", None)
    vals, vecs = _solve_pencil_beta(k_m, c_m, m_m, k0 * math.sqrt(eps_r))
    beta_c, _vec = _pick_physical_mode(vals, vecs, k0 * math.sqrt(eps_r))
    return float(beta_c.real)
