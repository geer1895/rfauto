"""悬置带线 G3 残余归因 FD 静流第三方裁判内核（Q-X20 / aurora_q，2026-11-07）。

背景（Q-X13 遗留仲裁点）：qx9_anchor G3 门 openEMS 干净口 εeff=1.5459 对闭式
1.6034 偏 −3.59%；w2f 角点实测闭式在本邻域对 FD 真值系统性高 +0.4~+1.3%，
残余 ~2.4% 归因开放（最可疑=z 向空气隙 2 格 112.5µm 离散，未证）。本模块
= 纯数值静流第三方裁判（零仿真零真机，铁律 7）：

1. **收敛阶梯**：G3 精确点 (w=0.52, b=0.50, h=0.05, εr=11.9)（u=w/b=1.04、
   s=h/b=0.1——闭式 SSL_Q 族拟合域 u∈[0.1,1] 边界外，正是需要 FD 第三方
   仲裁的原因）六级网格（首格 b/40·2^(-k)，k=0..5；深档由 shake-down 实测
   选定——C_air 一阶收敛（p≈1，零厚边缘奇异），4 档时 finest-vs-外推残差
   1.7e-3 未达 0.1% 门，6 档 3.8e-4 达标）+ 三点 Richardson 外推（Çelik
   2008 单源 core/gci.assess_triple，经 quasistatic_fd.richardson_three_
   point）。**预声明收敛锚（冻结于判读前）**：finest-vs-外推残差与相邻两
   外推互差均 <0.1%（εeff 与 C_air 双量），观察阶 p∈[0.5,4]，末三档单向
   收敛——任一不满足如实 INCOMPLETE（#122 不凑绿）。
2. **run 网格离散化假说检验**：把 qx9_anchor ssl_open 真跑横截面网格
   （z=精确 9 线 [0,112.5,225,237.5,250,262.5,275,387.5,500]µm、x 近场
   ~NEAR=17.39µm）作为 FD 网格重解同一静流问题——εeff 相对收敛锚的偏移
   = 该网格静流离散误差的 leading-order 仿真。z/x 轴分别隔离（E2/E3）+
   全 run 网格（E1），z 空气隙假说按预声明份额分类（classify_z_airgap_
   hypothesis：z 偏移解释引擎残余 ≥60% CONFIRMED / 25~60% PARTIAL /
   其余 REFUTED——假说证伪不排除 FDTD 动态/探针链贡献，报告面如实声明）。
3. **裁判先过已知基准（#300/#118）**：空气带状线 Z0 vs Cohn 闭式
   _stripline_z0、h→b 全填充 εeff=εr 恒等、h→0 εeff=1 恒等、与已验证裁判
   core/quasistatic_fd.suspended_stripline_quasistatic（不同网格族：
   均匀档 vs 本模块边缘加密档）交叉对拍。

求解核复用已过锚的 core/quasistatic_fd.energy_quasistatic（变分有限体积+
能量法——w2f 重定标同一裁判核，保证本席 εeff 与 w2f 角点 +0.4~+1.3% 口径
可比；#118 的"独立来源"指 FD 对被裁判的闭式独立，复用已过锚求解核与
统一口径优先）。本模块贡献=阶梯协议/预声明门/run 网格仿真/归因分类。

几何与约定（与 _suspended_stripline_ri / quasistatic_fd 完全同构）：
两接地板 z=0、z=b φ=0；零厚度带 z=b/2、|x|≤w/2 φ=1；厚 h 基板以带为中面
对称填充 z∈[b/2−h/2, b/2+h/2] εr、两侧空气隙各 (b−h)/2；x=0 对称轴
Neumann（半宽域）。C = 4·W_half（V=1，ε0 单位）；εeff = C(εr)/C(air)；
Z0 = 1/(c·√(C_air·C))。几何单位 mm；εeff 无量纲；Z0 单位 Ω。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from rfauto.core.calc_families.rf_line import _stripline_z0
from rfauto.core.quasistatic_fd import (
    DEFAULT_EDGE_RATIO,
    DEFAULT_GRADING_RATIO,
    concat_lines,
    energy_quasistatic,
    graded_lines,
    richardson_three_point,
    uniform_lines,
)

_EPS0 = 8.8541878128e-12
_C0 = 299792458.0

# ── G3 精确点与 run 网格画像（qx9_anchor ssl_open 真跑证据，语境钉死）───────

#: G3 精确点（spec.md 冻结锚 / verdict.json anchor 块）。
G3_W_MM = 0.52
G3_B_MM = 0.50
G3_H_MM = 0.05
G3_EPS_R = 11.9

#: ssl_open 真跑 z 网格线（simulation.py L66-69 + audit n_lines.z=9，m→mm）。
#: 带平面 250µm 上半：空气隙 2 格 112.5µm + 基板上半层 2 格 12.5µm；下半镜像。
RUN_Z_LINES_MM: tuple[float, ...] = (
    0.0, 0.1125, 0.225, 0.2375, 0.25, 0.2625, 0.275, 0.3875, 0.5,
)

#: ssl_open 真跑近场分辨率 NEAR=BASE/10（simulation.py L27；audit min_gap.x
#: 17.33µm=均匀段 round(0.26/NEAR) 格宽实测互证）。
RUN_X_NEAR_MM = 0.017393131069573456
#: 带半宽（simulation.py _near_x=±0.26mm——NEAR 精细区边界=带缘精确入网）。
RUN_STRIP_HALF_MM = 0.26

# ── 预声明门（冻结于判读前；违反即 INCOMPLETE，不事后放宽）────────────────

#: 三点 Richardson 收敛锚：finest-vs-外推 与 相邻两外推互差 上限（0.1%）。
LADDER_RESIDUAL_MAX = 1e-3
#: 观察阶 p 合法窗（0.5~4；边缘加密族能量误差 ~1→2 阶窗）。
LADDER_ORDER_MIN = 0.5
LADDER_ORDER_MAX = 4.0
#: 收敛阶梯档数（含最粗档；三点外推消费末三档，前档供互差锚）。
#: 六档=shake-down 实测冻结（2026-11-07）：C_air 一阶收敛（p≈1），4 档
#: finest 残差 1.66e-3 超 0.1% 门、6 档 3.8e-4 达标；eps 外推值 5/6 档互差
#: 1.2e-6（渐近稳定）。冻结先于判读（#122：工具 shake-down 与判读分离）。
LADDER_LEVELS = 6
#: 最粗档首格（b/40，quasistatic_fd SSL 族缺省口径）；逐档 ÷2。
LADDER_D0_COARSE_FACTOR = 40.0

# ── z 空气隙假说分类阈值（预声明份额；z 偏移/引擎残余，同号负向）────────────

#: z 偏移解释 ≥60% → CONFIRMED；25%~60% → PARTIAL；其余 → REFUTED。
Z_HYPOTHESIS_CONFIRMED_SHARE = 0.60
Z_HYPOTHESIS_PARTIAL_SHARE = 0.25


@dataclass(frozen=True)
class LadderResult:
    """四级收敛阶梯 + 三点外推的判读结果。

    status=CONVERGED 当且仅当全部预声明门通过（residual_fine/residual_agree
    <0.1%、p 窗内、末三档单向收敛，εeff 与 C_air 双量）；否则 INCOMPLETE。
    """

    status: str                     # "CONVERGED" | "INCOMPLETE"
    eps_eff: float                  # 外推 εeff（INCOMPLETE 时=finest 档值）
    z0_ohm: float                   # 外推 Z0 = 1/(c·√(C_air·C))
    c_air_f_per_m: float            # 外推 C_air
    c_diel_f_per_m: float           # 外推 C(εr)
    d0_levels_mm: list[float]
    eps_levels: list[float]
    c_air_levels_eps0: list[float]
    p_eps: float                    # εeff 观察阶（三点外推返回）
    p_cair: float
    residual_eps_fine: float        # |eps_fine−eps_ext|/eps_ext
    residual_eps_agree: float       # |ext(末三档)−ext(前三档)|/ext(末三档)
    residual_cair_fine: float
    residual_cair_agree: float
    gates: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "eps_eff": self.eps_eff,
            "z0_ohm": self.z0_ohm,
            "c_air_f_per_m": self.c_air_f_per_m,
            "c_diel_f_per_m": self.c_diel_f_per_m,
            "d0_levels_mm": list(self.d0_levels_mm),
            "eps_levels": list(self.eps_levels),
            "c_air_levels_eps0": list(self.c_air_levels_eps0),
            "p_eps": self.p_eps,
            "p_cair": self.p_cair,
            "residual_eps_fine": self.residual_eps_fine,
            "residual_eps_agree": self.residual_eps_agree,
            "residual_cair_fine": self.residual_cair_fine,
            "residual_cair_agree": self.residual_cair_agree,
            "gates": dict(self.gates),
        }


# ── 网格构造（本席自建族：x 向带缘双加密 + z 向分段均匀，锚点精确落线）───────

def judge_x_lines(d0_mm: float, w_mm: float, b_mm: float,
                  xmax_factor: float = 8.0) -> np.ndarray:
    """x 轴（半宽域 [0, xmax]）：带缘 w/2 两侧几何加密（密端在带缘）。

    对称轴侧 ×DEFAULT_EDGE_RATIO 渐变到 0，远区侧 ×DEFAULT_GRADING_RATIO
    渐变到 xmax_factor·b（quasistatic_fd SSL 族 edge_refine 同构——远场指数
    衰减 e^(-π·xmax/b)，8b 处 ~1e-11 截断可忽略）。
    """
    a = w_mm / 2.0
    return concat_lines(
        graded_lines(a, 0.0, d0_mm, DEFAULT_EDGE_RATIO)[::-1],
        graded_lines(a, xmax_factor * b_mm, d0_mm, DEFAULT_GRADING_RATIO))


def judge_z_lines(d0_mm: float, b_mm: float, h_mm: float) -> np.ndarray:
    """z 轴（全高 [0, b]）：基板两界面/带平面四段均匀（界面精确落线）。"""
    z1 = b_mm / 2.0 - h_mm / 2.0
    z2 = b_mm / 2.0 + h_mm / 2.0
    return concat_lines(
        uniform_lines(0.0, z1, d0_mm),
        uniform_lines(z1, b_mm / 2.0, d0_mm),
        uniform_lines(b_mm / 2.0, z2, d0_mm),
        uniform_lines(z2, b_mm, d0_mm))


def run_x_lines(xmax_mm: float = 4.0) -> np.ndarray:
    """ssl_open 真跑 x 轴仿真：近场 [0, w/2] 均匀 ~NEAR + 远区几何渐变。

    均匀段格宽 = round(0.26/NEAR) 段宽（audit min_gap.x=17.33µm 逐位互证）；
    远区从带缘起 ×DEFAULT_GRADING_RATIO 渐变（SmoothMesh BASE 渐变的同族
    近似——近场分辨率是静流误差主导面，远区增长率非敏感项）。
    """
    return concat_lines(
        uniform_lines(0.0, RUN_STRIP_HALF_MM, RUN_X_NEAR_MM),
        graded_lines(RUN_STRIP_HALF_MM, xmax_mm, RUN_X_NEAR_MM,
                     DEFAULT_GRADING_RATIO))


def run_z_lines() -> np.ndarray:
    """ssl_open 真跑 z 轴精确 9 线（RUN_Z_LINES_MM，audit n_lines.z=9）。"""
    return np.asarray(RUN_Z_LINES_MM, dtype=float)


# ── 电容提取（复用已过锚求解核；组装面为本席独立实现）────────────────────────

def ssl_capacitance_eps0(x_lines: np.ndarray, z_lines: np.ndarray,
                         w_mm: float, b_mm: float, h_mm: float,
                         eps_r: float) -> float:
    """给定横截面网格线解半宽域静流问题，返回 C/ε0（V=1；C=4·W_half）。

    网格线必须精确落在带缘 x=w/2 与介质面 z1/b/2/z2（1e-12 容差，违者
    RuntimeError fail-loud——锚点落线是界面加权与边缘奇异可控性的前提）。
    """
    xs = np.asarray(x_lines, dtype=float)
    zs = np.asarray(z_lines, dtype=float)
    z1 = b_mm / 2.0 - h_mm / 2.0
    z2 = b_mm / 2.0 + h_mm / 2.0
    nx, nz = xs.size, zs.size
    eps = np.ones((nx - 1, nz - 1))
    zc = 0.5 * (zs[:-1] + zs[1:])
    eps[:, (zc > z1) & (zc < z2)] = eps_r
    jm = int(np.argmin(np.abs(zs - b_mm / 2.0)))
    iw = int(np.argmin(np.abs(xs - w_mm / 2.0)))
    if (abs(zs[jm] - b_mm / 2.0) > 1e-12 or abs(zs.min()) > 1e-12
            or abs(zs.max() - b_mm) > 1e-12
            or abs(xs[iw] - w_mm / 2.0) > 1e-12):
        raise RuntimeError(
            "SSL FD 裁判网格线未精确落在带缘/带平面/接地面（构造错误）")
    if h_mm > 0.0:
        j1 = int(np.argmin(np.abs(zs - z1)))
        j2 = int(np.argmin(np.abs(zs - z2)))
        if abs(zs[j1] - z1) > 1e-12 or abs(zs[j2] - z2) > 1e-12:
            raise RuntimeError("SSL FD 裁判网格线未精确落在基板界面（构造错误）")
    diri: dict[int, float] = {}
    for i in range(nx):                      # 两接地板 φ=0
        diri[i * nz] = 0.0
        diri[i * nz + nz - 1] = 0.0
    for i in range(iw + 1):                  # 零厚带 φ=1（带平面一行）
        diri[i * nz + jm] = 1.0
    return 4.0 * energy_quasistatic(xs, zs, eps, diri)


def _ssl_eps_eff_and_cair(x_lines: np.ndarray, z_lines: np.ndarray,
                          w_mm: float, b_mm: float, h_mm: float,
                          eps_r: float) -> tuple[float, float]:
    """同网格双解（εr 与 air）→ (εeff, C_air/ε0)。"""
    c_d = ssl_capacitance_eps0(x_lines, z_lines, w_mm, b_mm, h_mm, eps_r)
    c_a = ssl_capacitance_eps0(x_lines, z_lines, w_mm, b_mm, h_mm, 1.0)
    return c_d / c_a, c_a


# ── 收敛阶梯（预声明门）──────────────────────────────────────────────────────

def _triple_extrapolate(values: list[float]) -> tuple[float, float, float,
                                                       float]:
    """末三档三点外推 → (外推值, 观察阶, finest 残差, 前三档外推互差残差)。

    要求 len(values) ≥ 4（相邻两组三点外推需四档）。观察阶/外推单源
    quasistatic_fd.richardson_three_point（Çelik 2008；不收敛时诚实回退
    一阶、p=1.0——回退后残差门照常把关，不因回退放行）。
    """
    if len(values) < 4:
        raise ValueError(f"三点外推+互差锚需 ≥4 档，实得 {len(values)}")
    ext4, p4 = richardson_three_point(values[-3], values[-2], values[-1])
    ext3, _ = richardson_three_point(values[-4], values[-3], values[-2])
    resid_fine = abs(values[-1] - ext4) / abs(ext4)
    resid_agree = abs(ext4 - ext3) / abs(ext4)
    return ext4, p4, resid_fine, resid_agree


def _monotone_last3(values: list[float]) -> bool:
    """末三档差分同号（单向收敛；零差按不单调处理——诚实）。"""
    d1 = values[-2] - values[-3]
    d2 = values[-1] - values[-2]
    return d1 * d2 > 0.0


def judge_ladder(w_mm: float = G3_W_MM, b_mm: float = G3_B_MM,
                 h_mm: float = G3_H_MM, eps_r: float = G3_EPS_R,
                 xmax_factor: float = 8.0,
                 levels: int = LADDER_LEVELS) -> LadderResult:
    """四级收敛阶梯 + 三点 Richardson 外推 + 预声明收敛门。

    门（冻结）：①εeff 与 C_air 的 finest-vs-外推残差 <0.1%；②相邻两外推
    互差 <0.1%；③观察阶 p∈[0.5,4]（双量）；④末三档单向收敛（双量）。
    全过=CONVERGED；任一不过=INCOMPLETE（εeff/Z0 回落 finest 档值并如实
    降级，不凑）。
    """
    d0_coarse = b_mm / LADDER_D0_COARSE_FACTOR
    d0_levels = [d0_coarse / (2.0 ** k) for k in range(levels)]
    eps_v: list[float] = []
    cair_v: list[float] = []
    for d0 in d0_levels:
        eps_i, cair_i = _ssl_eps_eff_and_cair(
            judge_x_lines(d0, w_mm, b_mm, xmax_factor),
            judge_z_lines(d0, b_mm, h_mm), w_mm, b_mm, h_mm, eps_r)
        eps_v.append(eps_i)
        cair_v.append(cair_i)

    ext_eps, p_eps, r_eps_f, r_eps_a = _triple_extrapolate(eps_v)
    ext_cair, p_cair, r_cair_f, r_cair_a = _triple_extrapolate(cair_v)

    gates = {
        "residual_eps_fine": r_eps_f < LADDER_RESIDUAL_MAX,
        "residual_eps_agree": r_eps_a < LADDER_RESIDUAL_MAX,
        "residual_cair_fine": r_cair_f < LADDER_RESIDUAL_MAX,
        "residual_cair_agree": r_cair_a < LADDER_RESIDUAL_MAX,
        "order_eps_in_window": LADDER_ORDER_MIN <= p_eps <= LADDER_ORDER_MAX,
        "order_cair_in_window": (LADDER_ORDER_MIN <= p_cair
                                 <= LADDER_ORDER_MAX),
        "monotone_eps_last3": _monotone_last3(eps_v),
        "monotone_cair_last3": _monotone_last3(cair_v),
    }
    converged = all(gates.values())
    eps_eff = ext_eps if converged else eps_v[-1]
    c_air = ext_cair if converged else cair_v[-1]
    c_air_f = c_air * _EPS0                   # ε0 单位 → F/m
    c_diel_f = eps_eff * c_air_f
    z0 = 1.0 / (_C0 * np.sqrt(c_air_f * c_diel_f))
    return LadderResult(
        status="CONVERGED" if converged else "INCOMPLETE",
        eps_eff=float(eps_eff), z0_ohm=float(z0),
        c_air_f_per_m=float(c_air_f), c_diel_f_per_m=float(c_diel_f),
        d0_levels_mm=d0_levels, eps_levels=eps_v, c_air_levels_eps0=cair_v,
        p_eps=float(p_eps), p_cair=float(p_cair),
        residual_eps_fine=float(r_eps_f), residual_eps_agree=float(r_eps_a),
        residual_cair_fine=float(r_cair_f),
        residual_cair_agree=float(r_cair_a), gates=gates)


# ── run 网格离散化假说检验 ───────────────────────────────────────────────────

@dataclass(frozen=True)
class EmulationResult:
    """一组 run 网格轴组合的静流 εeff 仿真与相对收敛锚的偏移。"""

    tag: str            # "E1" 全 run 网格 / "E2" run z + 加密 x / "E3" run x + 加密 z
    x_mode: str         # "run" | "refined"
    z_mode: str         # "run" | "refined"
    eps_eff: float      # 仿真 εeff（refined 轴已做两档一阶外推消轴误差）
    shift_rel: float    # (eps_em − eps_conv)/eps_conv
    n_nodes: int

    def as_dict(self) -> dict:
        return {"tag": self.tag, "x_mode": self.x_mode, "z_mode": self.z_mode,
                "eps_eff": self.eps_eff, "shift_rel": self.shift_rel,
                "n_nodes": self.n_nodes}


def run_mesh_emulation_eps_eff(
        eps_conv: float, w_mm: float = G3_W_MM, b_mm: float = G3_B_MM,
        h_mm: float = G3_H_MM, eps_r: float = G3_EPS_R,
        x_mode: str = "run", z_mode: str = "run",
        d0_refined_mm: float | None = None,
        xmax_factor: float = 8.0) -> EmulationResult:
    """给定轴组合重解静流问题 → εeff 及相对收敛锚的偏移。

    x_mode/z_mode="run" 用 ssl_open 真跑轴；"refined" 用本席加密族并做
    两档一阶 Richardson 外推消该轴残余离散误差（隔离单一轴向的干净读数）。
    """
    if x_mode not in ("run", "refined") or z_mode not in ("run", "refined"):
        raise ValueError("x_mode/z_mode 仅限 'run' | 'refined'")
    d0_ref = d0_refined_mm if d0_refined_mm is not None \
        else b_mm / (LADDER_D0_COARSE_FACTOR * 2.0 ** (LADDER_LEVELS - 1))
    n_nodes = 0

    def z_lines(mode: str, d0: float) -> np.ndarray:
        return run_z_lines() if mode == "run" else judge_z_lines(d0, b_mm, h_mm)

    def x_lines(mode: str, d0: float) -> np.ndarray:
        return (run_x_lines(xmax_factor * b_mm) if mode == "run"
                else judge_x_lines(d0, w_mm, b_mm, xmax_factor))

    if x_mode == "run" and z_mode == "run":
        eps, _ = _ssl_eps_eff_and_cair(
            run_x_lines(xmax_factor * b_mm), run_z_lines(),
            w_mm, b_mm, h_mm, eps_r)
        n_nodes = run_x_lines(xmax_factor * b_mm).size * run_z_lines().size
    elif x_mode == "refined":
        vals = []
        for d0 in (d0_ref, d0_ref / 2.0):
            e_i, _ = _ssl_eps_eff_and_cair(
                x_lines("refined", d0), z_lines(z_mode, d0_ref),
                w_mm, b_mm, h_mm, eps_r)
            vals.append(e_i)
        n_nodes = (x_lines("refined", d0_ref / 2.0).size
                   * z_lines(z_mode, d0_ref).size)
        eps = 2.0 * vals[-1] - vals[0]          # 一阶外推消 x 轴残余误差
    else:
        vals = []
        for d0 in (d0_ref, d0_ref / 2.0):
            e_i, _ = _ssl_eps_eff_and_cair(
                x_lines("run", d0), z_lines("refined", d0),
                w_mm, b_mm, h_mm, eps_r)
            vals.append(e_i)
        n_nodes = (x_lines("run", d0_ref).size
                   * z_lines("refined", d0_ref / 2.0).size)
        eps = 2.0 * vals[-1] - vals[0]          # 一阶外推消 z 轴残余误差
    tag = {"run_run": "E1", "refined_run": "E2", "run_refined": "E3"}[
        f"{x_mode}_{z_mode}"]
    return EmulationResult(tag=tag, x_mode=x_mode, z_mode=z_mode,
                           eps_eff=float(eps),
                           shift_rel=float((eps - eps_conv) / eps_conv),
                           n_nodes=int(n_nodes))


def classify_z_airgap_hypothesis(residual_oe_rel: float,
                                 z_shift_rel: float,
                                 e1_shift_rel: float | None = None
                                 ) -> dict:
    """z 空气隙假说分类（预声明份额，纯函数——单测钉边界）。

    residual_oe_rel=(openEMS−FD)/FD（引擎残余，预期负）；z_shift_rel=
    (E2−FD)/FD（run z 轴静流偏移）。z 偏移同号（负）且解释 ≥60% →
    CONFIRMED；25%~60% → PARTIAL；其余（含反号/零残余）→ REFUTED。
    e1_shift_rel（全 run 网格静流偏移）随行返回占比，不进分类主判。
    """
    out: dict = {"residual_oe_rel": residual_oe_rel,
                 "z_shift_rel": z_shift_rel,
                 "e1_shift_rel": e1_shift_rel}
    if e1_shift_rel is not None and residual_oe_rel != 0.0:
        out["e1_share"] = e1_shift_rel / residual_oe_rel
    if residual_oe_rel >= 0.0:
        out["verdict"] = "NO_RESIDUAL"
        return out
    if z_shift_rel >= 0.0:
        out["verdict"] = "REFUTED"
        out["share"] = 0.0
        return out
    share = z_shift_rel / residual_oe_rel
    out["share"] = share
    if share >= Z_HYPOTHESIS_CONFIRMED_SHARE:
        out["verdict"] = "CONFIRMED"
    elif share >= Z_HYPOTHESIS_PARTIAL_SHARE:
        out["verdict"] = "PARTIAL"
    else:
        out["verdict"] = "REFUTED"
    return out


# ── 裁判先过已知基准（#300）──────────────────────────────────────────────────

def cohn_air_anchor(w_mm: float = G3_W_MM, b_mm: float = G3_B_MM,
                    d0_mm: float | None = None,
                    xmax_factor: float = 8.0) -> dict:
    """空气带状线 Z0 锚：FD（εr=1 全空气）vs Cohn 闭式 _stripline_z0。

    裁判资格锚（#300：先过已知基准才有资格裁判）——空气 εeff=1 恒等下
    Z0_air = 1/(c·C_air)。四级阶梯（主判读同族、末两档一阶外推），冻结
    合格线：外推 rel ≤0.5%（已验证裁判先例 −0.5%@d0=b/160 同量级）且
    末两档互差 <0.5%（收敛性在位）。
    """
    d0 = d0_mm if d0_mm is not None else b_mm / LADDER_D0_COARSE_FACTOR
    z0s = []
    for k in range(4):
        d = d0 / (2.0 ** k)
        # εr=1：ε 布局无关（全空气），h 取 G3 名义值仅作占位
        c_a = ssl_capacitance_eps0(judge_x_lines(d, w_mm, b_mm, xmax_factor),
                                   judge_z_lines(d, b_mm, G3_H_MM), w_mm,
                                   b_mm, G3_H_MM, 1.0)
        z0s.append(1.0 / (_C0 * c_a * _EPS0))
    cohn = _stripline_z0(w_mm, b_mm, 1.0)
    z0_ext = 2.0 * z0s[-1] - z0s[-2]
    return {"fd_z0_ohm": float(z0_ext), "cohn_z0_ohm": float(cohn),
            "rel": float(z0_ext / cohn - 1.0),
            "level_rel": [float(z / cohn - 1.0) for z in z0s],
            "converged": abs(z0s[-1] - z0s[-2]) / z0s[-1] < 5e-3}


def exact_limit_anchors(w_mm: float = G3_W_MM, b_mm: float = G3_B_MM,
                        h_mm: float = G3_H_MM,
                        eps_r: float = G3_EPS_R) -> dict:
    """精确极限/构造恒等锚（FD 组装面无偏性，任意档逐位）：

    ① h→b 全填充 εeff=εr（同网格 εr 解/air 解纯缩放恒等）；
    ② εr=1 恒等 εeff=1（双解同矩阵）；
    ③ 薄基板物理单调：εeff(h=b/100) < εeff(h=b/10) 且 εeff(h=b/100)−1 < 1%
    （h→0 极限 εeff→1 的 FD 可达版——真 h=0 会让网格出现零宽段，几何退化
    不可入网格，故取薄层物理窗替代恒等，如实声明非精确锚）。
    """
    d0 = b_mm / LADDER_D0_COARSE_FACTOR / 4.0
    eps_full, _ = _ssl_eps_eff_and_cair(
        judge_x_lines(d0, w_mm, b_mm), judge_z_lines(d0, b_mm, b_mm),
        w_mm, b_mm, b_mm, eps_r)
    eps_air, _ = _ssl_eps_eff_and_cair(
        judge_x_lines(d0, w_mm, b_mm), judge_z_lines(d0, b_mm, h_mm),
        w_mm, b_mm, h_mm, 1.0)
    eps_thin, _ = _ssl_eps_eff_and_cair(
        judge_x_lines(d0, w_mm, b_mm), judge_z_lines(d0, b_mm, b_mm / 100.0),
        w_mm, b_mm, b_mm / 100.0, eps_r)
    eps_thick, _ = _ssl_eps_eff_and_cair(
        judge_x_lines(d0, w_mm, b_mm), judge_z_lines(d0, b_mm, b_mm / 10.0),
        w_mm, b_mm, b_mm / 10.0, eps_r)
    return {"full_fill_eps_eff": float(eps_full),
            "full_fill_err": float(eps_full - eps_r),
            "air_identity_eps_eff": float(eps_air),
            "air_identity_err": float(eps_air - 1.0),
            "thin_eps_eff": float(eps_thin),
            "thin_minus_air": float(eps_thin - 1.0),
            "thin_lt_thicker": bool(eps_thin < eps_thick)}


def referee_cross_check(w_mm: float = G3_W_MM, b_mm: float = G3_B_MM,
                        h_mm: float = G3_H_MM, eps_r: float = G3_EPS_R,
                        eps_self: float | None = None) -> dict:
    """与已验证裁判 core/quasistatic_fd.suspended_stripline_quasistatic
    （均匀档+三点外推+边缘加密 opt-in）交叉对拍——不同网格族同物理，
    一致性钉住网格族特异性伪象。"""
    from rfauto.core.quasistatic_fd import suspended_stripline_quasistatic

    res = suspended_stripline_quasistatic(
        w_mm, b_mm, h_mm, eps_r, three_point=True, edge_refine=True)
    rel = (float(res.eps_eff) / eps_self - 1.0) if eps_self else None
    return {"referee_eps_eff": float(res.eps_eff),
            "referee_z0_ohm": float(res.z0_ohm),
            "referee_observed_order": res.observed_order,
            "rel_vs_self": rel}
