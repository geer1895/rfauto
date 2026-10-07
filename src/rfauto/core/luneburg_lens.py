"""LM-4 Luneburg 透镜分壳离散 + 3D 打印材料表内核。

法源（铁律：来源写 docstring；裁判=独立路径，不自证，#118）：

- 连续剖面 εr(r) = 2 − (r/R)²（0 ≤ r ≤ R）：R. Luneburg（1944）数学理论，
  标准口径（Peeler & Coleman 1958 引言转述一致）。平行入射束在透镜
  对侧表面 r=R 处汇聚——解析焦点在对侧表面点 (R,0)（Luneburg 解经典
  性质：面焦点/点源馈电互易）。
- 分壳离散（step-index 近似）：G. D. M. Peeler, H. P. Coleman,
  "Microwave Stepped-Index Luneberg Lenses", IRE Trans. Antennas
  Propag., vol.6, no.2, pp.202-207, Apr.1958（书目信息经两个独立引用源
  核对；DOI 后缀未在 IEEE Xplore 二次核对，不引具体数字）。逐壳常 εr，
  文献典型 8-10 壳。
- 打印分辨率律：最小特征 = 0.7·λg（λg = λ0/√εr_eff）、最低可实现
  εr_eff ≈ 1.2 —— Chisum 组 gyroid 3D 打印 Luneburg 透镜口径
  （研究扩充 round4 [25]/[30] 二手核对；
  原始 IEEE 论文本机未逐位核对 → 两常数登记 UNVERIFIED-secondary，
  消费方如需硬门请先回原文钉值）。
- 混合模型选型（钉死一种）：线性算术（Taylor）式
  εr_eff = f·εr_base + (1−f)·εr_air。登记适用性争议：文献亦用
  Lichtenecker 对数幂律 log εr_eff = f·log εr_base + (1−f)·log εr_air
  （多用于粉末/多孔混合介质）；两者 f(εr_eff) 同为 [0,1] 单调、端点
  一致，中段差异 ~几个 %εr 量级——本内核钉线性式（闭式反演无歧义，
  聚合物-空气 infill 实测数据族普遍以线性/准线性口径发表）；换幂律属
  函数级单点替换，不得静默混用两种口径。
- 材料 schema：(material, process, infill) 三元组（PRINT_MATERIALS）。
  ABS/PLA 为"双源 εr 带"（band = 文献常引范围；er_band_status 如实标
  UNVERIFIED_band：带内逐源数字核对未做——round4 [30] 源集 Picha 2022
  全文/ABS 波导实测/Felicio 各向异性，核对是后续动作）；Clear V4 单源
  待证（UNVERIFIED_single_source）。#118：无可达单源精确数不虚构精确
  值——以"带 + UNVERIFIED 状态字段"如实登记，数值只进 schema 不进判据。

接口：纯函数零 IO；返回 JSON 可序列化 float/str/bool/list/dict；数值
0.0 合法、判缺失一律 ``is not None``（#364④）；bool 显式拒收（df7+⑯）。
射线追踪（主判据）双路径：路径 A = 分壳逐界面 Snell + 壳内直线行进；
路径 B = 连续剖面射线方程 d(n·u)/ds = ∇n 的 RK4 数值积分——两路径独
立实现同一物理量（焦点误差），互为裁判（#118）。

单位约定：几何量（radius/壳厚/最小特征）与长度单位由调用方自洽——
guided_wavelength 返回米（f0_hz 与光速 c_m_s 口径），print_feasibility
直接比较壳厚与最小特征，因此 **radius 传米** 才有物理意义；无量纲用法
（radius=1）时只做几何/收敛判定，不做打印可行性判定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ─── 常量（来源见模块 docstring）──────────────────────────────────────────────

C_M_S = 299792458.0  # 真空光速 m/s（SI 精确值）

#: 最小特征/导波波长比（Chisum gyroid 口径，UNVERIFIED-secondary）
MIN_FEATURE_OVER_LAMBDA_G = 0.7
#: 最低可实现 εr_eff 下界（Chisum 口径，UNVERIFIED-secondary）
MIN_PRINTABLE_ER_EFF = 1.2

PARTITION_EQUAL_VOLUME = "equal_volume"
PARTITION_EQUAL_THICKNESS = "equal_thickness"
_PARTITIONS = (PARTITION_EQUAL_VOLUME, PARTITION_EQUAL_THICKNESS)

REP_MIDPOINT = "midpoint"
REP_VOLUME_MEAN = "volume_mean"
_REPRESENTATIVES = (REP_MIDPOINT, REP_VOLUME_MEAN)

#: 混合模型登记名（本内核唯一口径，见 docstring 选型争议登记）
MIX_LINEAR = "linear_arithmetic"

# 3D 打印材料表：(material, process, infill) 三元组 + εr 带 + 来源。
# 状态字段诚实口径：UNVERIFIED_band = 带值是文献常引范围、逐源数字核对
# 未做；UNVERIFIED_single_source = 单源待证。键值只进 schema 与示例，
# 不做物理判据（#118）。
PRINT_MATERIALS: dict[str, dict] = {
    "pla": {
        "material": "PLA",
        "process": "FDM",
        "infill": {"pattern": "gyroid_or_rectilinear", "f_modulates": "er via mix_er_eff"},
        "er_band": (2.2, 3.0),
        "er_band_status": "UNVERIFIED_band",
        "sources": [
            "round4 [30]：Picha 2022（3D 打印材料 εr 实测，全文可达未逐位核对）",
            "round4 [30]：Moscato 组 PLA infill 依赖实测（二手常引口径）",
        ],
    },
    "abs": {
        "material": "ABS",
        "process": "FDM",
        "infill": {"pattern": "gyroid_or_rectilinear", "f_modulates": "er via mix_er_eff"},
        "er_band": (2.4, 2.9),
        "er_band_status": "UNVERIFIED_band",
        "sources": [
            "round4 [30]：ABS 波导实测（X 波段口径，二手）",
            "round4 [30]：Felicio（打印各向异性实测，二手）",
        ],
    },
    "clear_v4": {
        "material": "Formlabs Clear V4",
        "process": "SLA",
        "infill": {"pattern": "solid_or_gyroid", "f_modulates": "er via mix_er_eff"},
        "er_band": (2.5, 2.8),
        "er_band_status": "UNVERIFIED_single_source",
        "sources": [
            "round4 [30]：Clear V4 单源待证（原文未核对）",
        ],
    },
}


# ─── 入参收敛守卫（同 aging.py 口径）─────────────────────────────────────────


def _finite(value: float, name: str) -> float:
    """把入参收敛为有限 float，非法即显式报错（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    """把入参收敛为有限正 float，非法即显式报错。"""
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0")
    return out


def _nonneg(value: float, name: str) -> float:
    """把入参收敛为有限非负 float，非法即显式报错。"""
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} 必须 >=0")
    return out


def _count(value: int, name: str) -> int:
    """壳数收敛：正整数（bool 显式拒收，float 8.0 也拒——隐式截断是坑）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须为 int（不接受 bool/float 隐式截断）")
    if value < 1:
        raise ValueError(f"{name} 必须 >=1")
    return int(value)


# ─── 1. 连续 Luneburg 剖面 ───────────────────────────────────────────────────


def luneburg_epsilon(r: float, radius: float = 1.0) -> float:
    """连续 Luneburg 剖面 εr(r) = 2 − (r/R)²，0 ≤ r ≤ R。

    恒等式：εr(0) = 2、εr(R) = 1（逐位）；εr 沿 r 单调减。r 超出 [0, R]
    显式报错（静默外推会把 ≥1 的 εr 假象带进下游）。
    """
    R = _positive(radius, "radius")
    rr = _nonneg(r, "r")
    if rr > R:
        raise ValueError(f"r={rr} 超出剖面定义域 [0, R={R}]")
    return 2.0 - (rr / R) ** 2


def luneburg_index(r: float, radius: float = 1.0) -> float:
    """折射率 n(r) = √εr(r)。"""
    return math.sqrt(luneburg_epsilon(r, radius))


# ─── 2. 分壳离散（Peeler 1958 step-index）────────────────────────────────────


def shell_boundaries(
    radius: float, n_shells: int, partition: str = PARTITION_EQUAL_VOLUME
) -> list[float]:
    """壳边界半径表 r_0=0 … r_N=R（N+1 项，单调增）。

    partition 两种口径（参数显式，不得静默混用）：
    - equal_volume：等体积壳，r_i = R·(i/N)^(1/3)（球体积
      V_i = (4π/3)(r_i³−r_{i−1}³) = 球体积/N 恒等）。
    - equal_thickness：等厚度壳，r_i = R·(i/N)（算术级数，壳厚 R/N）。
    """
    R = _positive(radius, "radius")
    n = _count(n_shells, "n_shells")
    if partition not in _PARTITIONS:
        raise ValueError(f"partition 必须为 {_PARTITIONS} 之一，收到 {partition!r}")
    if partition == PARTITION_EQUAL_VOLUME:
        return [R * (i / n) ** (1.0 / 3.0) for i in range(n + 1)]
    return [R * (i / n) for i in range(n + 1)]


@dataclass(frozen=True)
class ShellStack:
    """分壳离散结果：壳边界表 + 每壳代表 εr 表（JSON 可序列化经 to_dict）。"""

    radius: float
    n_shells: int
    partition: str
    representative: str
    boundaries: tuple  # tuple[float, ...]，长度 N+1
    eps_shells: tuple  # tuple[float, ...]，长度 N；shell i ∈ [boundaries[i], boundaries[i+1]]
    radii_mid: tuple  # tuple[float, ...]，每壳代表半径（midpoint 口径）

    def to_dict(self) -> dict:
        """JSON 可序列化字典（float/str/int/list，无 tuple/ndarray）。"""
        return {
            "radius": self.radius,
            "n_shells": self.n_shells,
            "partition": self.partition,
            "representative": self.representative,
            "boundaries": [float(r) for r in self.boundaries],
            "eps_shells": [float(e) for e in self.eps_shells],
            "radii_mid": [float(r) for r in self.radii_mid],
            "shell_thicknesses": list(self.shell_thicknesses()),
            "shell_volumes": list(self.shell_volumes()),
        }

    def shell_thicknesses(self) -> tuple:
        """每壳厚度 (r_{i+1} − r_i)。"""
        return tuple(
            self.boundaries[i + 1] - self.boundaries[i] for i in range(self.n_shells)
        )

    def shell_volumes(self) -> tuple:
        """每壳球体积 (4π/3)(r_{i+1}³ − r_i³)。"""
        return tuple(
            (4.0 / 3.0) * math.pi * (self.boundaries[i + 1] ** 3 - self.boundaries[i] ** 3)
            for i in range(self.n_shells)
        )


def _volume_mean_epsilon(r_lo: float, r_hi: float, radius: float) -> float:
    """壳内体积平均 εr 闭式：2 − (3/5)·(r_hi⁵−r_lo⁵)/(R²·(r_hi³−r_lo³))。

    推导：∫(2−(r/R)²)r²dr / ∫r²dr 的解析积分（球体积权）——单测以数值
    积分独立复推（双路径 #118）。
    """
    num = r_hi**5 - r_lo**5
    den = r_hi**3 - r_lo**3
    return 2.0 - 0.6 * num / (radius * radius * den)


def discretize_shells(
    radius: float = 1.0,
    n_shells: int = 8,
    partition: str = PARTITION_EQUAL_VOLUME,
    representative: str = REP_MIDPOINT,
) -> ShellStack:
    """Luneburg 剖面 → N 壳 step-index 离散（Peeler 1958 口径）。

    representative 两种口径（参数显式）：
    - midpoint：壳中点半径 εr((r_lo+r_hi)/2)（缺省，Peeler 惯例近似）。
    - volume_mean：壳内体积平均 εr（闭式见 _volume_mean_epsilon）。

    返回 ShellStack（frozen dataclass）；壳序 i=0 为最内壳（含球心），
    i=N−1 为最外壳（εr→1）。
    """
    R = _positive(radius, "radius")
    n = _count(n_shells, "n_shells")
    if partition not in _PARTITIONS:
        raise ValueError(f"partition 必须为 {_PARTITIONS} 之一，收到 {partition!r}")
    if representative not in _REPRESENTATIVES:
        raise ValueError(f"representative 必须为 {_REPRESENTATIVES} 之一，收到 {representative!r}")
    bounds = shell_boundaries(R, n, partition)
    eps: list[float] = []
    mids: list[float] = []
    for i in range(n):
        r_lo, r_hi = bounds[i], bounds[i + 1]
        if representative == REP_MIDPOINT:
            r_mid = 0.5 * (r_lo + r_hi)
            eps.append(luneburg_epsilon(r_mid, R))
            mids.append(r_mid)
        else:
            eps.append(_volume_mean_epsilon(r_lo, r_hi, R))
            mids.append((r_lo + r_hi) / 2.0)
    return ShellStack(
        radius=R,
        n_shells=n,
        partition=partition,
        representative=representative,
        boundaries=tuple(bounds),
        eps_shells=tuple(eps),
        radii_mid=tuple(mids),
    )


# ─── 3. 混合模型与打印分辨率律 ───────────────────────────────────────────────


def mix_er_eff(er_base: float, fill_fraction: float, er_air: float = 1.0) -> float:
    """线性算术混合 εr_eff = f·εr_base + (1−f)·εr_air（选型登记见 docstring）。

    f：基材体积分数（[0,1]，0=纯空气 εr_air、1=纯基材，端点恒等式逐位）。
    """
    eb = _positive(er_base, "er_base")
    ea = _positive(er_air, "er_air")
    f = _finite(fill_fraction, "fill_fraction")
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"fill_fraction={f} 超出 [0,1]")
    return f * eb + (1.0 - f) * ea


def invert_fill_fraction(er_eff: float, er_base: float, er_air: float = 1.0) -> float:
    """混合模型反演 f = (εr_eff − εr_air)/(εr_base − εr_air)。

    εr_eff 落在 [εr_air, εr_base] 外（或 εr_base ≤ εr_air 退化）→
    ValueError——f∉[0,1] 是设计不可达，不是钳位对象（钳位会把不可行
    设计静默洗白）。
    """
    eb = _positive(er_base, "er_base")
    ea = _positive(er_air, "er_air")
    if eb <= ea:
        raise ValueError(f"er_base={eb} 必须 > er_air={ea}（否则反演退化/无材料对比度）")
    e = _finite(er_eff, "er_eff")
    f = (e - ea) / (eb - ea)
    if not 0.0 <= f <= 1.0:
        raise ValueError(f"er_eff={e} 反演 f={f} 超出 [0,1]（εr_eff 须在 [er_air, er_base] 内）")
    return f


def er_eff_feasible(er_eff: float, floor: float = MIN_PRINTABLE_ER_EFF) -> bool:
    """εr_eff 是否达到最低可实现下界（Chisum ≈1.2，UNVERIFIED-secondary）。"""
    e = _positive(er_eff, "er_eff")
    fl = _positive(floor, "floor")
    return e >= fl


def guided_wavelength(f0_hz: float, er_eff: float, c_m_s: float = C_M_S) -> float:
    """导波波长 λg = λ0/√εr_eff = c/(f·√εr_eff)（米）。"""
    f0 = _positive(f0_hz, "f0_hz")
    c = _positive(c_m_s, "c_m_s")
    e = _positive(er_eff, "er_eff")
    return c / (f0 * math.sqrt(e))


def min_feature_length(
    f0_hz: float, er_eff: float, factor: float = MIN_FEATURE_OVER_LAMBDA_G, c_m_s: float = C_M_S
) -> float:
    """打印最小特征 = 0.7·λg（factor 钉 Chisum 口径，UNVERIFIED-secondary）。"""
    fac = _positive(factor, "factor")
    return fac * guided_wavelength(f0_hz, er_eff, c_m_s)


def print_feasibility(
    stack: ShellStack, f0_hz: float, er_base: float, er_air: float = 1.0
) -> dict:
    """逐壳打印可行性判定（Chisum 分辨率律 + εr_eff 下界旗标）。

    每壳：目标 εr_shell → infill 分数 f（混合模型反演；f 越界记
    infeasible 不抛——本函数是设计可行性报告）；εr_shell <
    MIN_PRINTABLE_ER_EFF 记 εr 下界旗标（注意：Luneburg 最外壳 εr→1
    **必然**低于 1.2 地板——工程惯例是把外域钳位到 ε_min 再分壳，本内核
    只出旗标不静默钳位）；壳厚 < 0.7·λg(εr_shell) 记分辨率不可达。
    radius 须与 λg 同单位（米）。

    返回聚合：``all_thickness_ok``（分辨率律，N 可行性的绑定判据）、
    ``all_er_floor_ok``、``all_feasible``（严格=全部旗标绿）、
    ``min_margin_ratio``（最薄壳厚/最小特征比）。单调性论证与钳位注记
    见 max_feasible_shells。
    """
    if not isinstance(stack, ShellStack):
        raise ValueError("stack 必须为 ShellStack")
    eb = _positive(er_base, "er_base")
    ea = _positive(er_air, "er_air")
    if eb <= ea:
        raise ValueError(f"er_base={eb} 必须 > er_air={ea}")
    f0 = _positive(f0_hz, "f0_hz")
    thicknesses = stack.shell_thicknesses()
    rows: list[dict] = []
    all_ok = True
    all_thick_ok = True
    all_floor_ok = True
    min_margin = math.inf
    for i in range(stack.n_shells):
        e_shell = stack.eps_shells[i]
        thickness = thicknesses[i]
        f_ok = e_shell >= ea
        f = (e_shell - ea) / (eb - ea) if f_ok else math.nan
        fill_in_range = f_ok and 0.0 <= f <= 1.0
        er_floor_ok = er_eff_feasible(e_shell)
        lam_g = guided_wavelength(f0, e_shell)
        feat = min_feature_length(f0, e_shell)
        thick_ok = thickness >= feat
        shell_ok = fill_in_range and er_floor_ok and thick_ok
        all_ok = all_ok and shell_ok
        all_thick_ok = all_thick_ok and thick_ok
        all_floor_ok = all_floor_ok and er_floor_ok
        if feat > 0.0:
            min_margin = min(min_margin, thickness / feat)
        rows.append(
            {
                "index": i,
                "r_lo": stack.boundaries[i],
                "r_hi": stack.boundaries[i + 1],
                "thickness": thickness,
                "er_shell": e_shell,
                "fill_fraction": f,
                "fill_fraction_in_range": fill_in_range,
                "er_floor_ok": er_floor_ok,
                "lambda_g": lam_g,
                "min_feature": feat,
                "thickness_ok": thick_ok,
                "feasible": shell_ok,
            }
        )
    return {
        "n_shells": stack.n_shells,
        "f0_hz": f0,
        "er_base": eb,
        "er_air": ea,
        "mix_model": MIX_LINEAR,
        "min_feature_over_lambda_g": MIN_FEATURE_OVER_LAMBDA_G,
        "min_printable_er_eff": MIN_PRINTABLE_ER_EFF,
        "shells": rows,
        "all_thickness_ok": all_thick_ok,
        "all_er_floor_ok": all_floor_ok,
        "all_feasible": all_ok,
        "min_margin_ratio": min_margin,
    }


def max_feasible_shells(
    radius: float,
    f0_hz: float,
    er_base: float,
    partition: str = PARTITION_EQUAL_VOLUME,
    representative: str = REP_MIDPOINT,
    er_air: float = 1.0,
    hard_cap: int = 4096,
) -> dict:
    """打印分辨率律（壳厚 ≥ 0.7·λg）允许的最大壳数 N_max。

    绑定判据=分辨率律（任务口径：壳厚 ≥ 最小特征）；εr_eff 地板只进
    per-shell 旗标（Luneburg 外壳 εr→1 必然触地板，不绑 N 可行性——
    见 print_feasibility 的钳位注记）。

    单调性：两口径的最薄壳（=最外壳，equal_volume 因 (i/N)^(1/3) 凹性
    壳厚随 i 递减）随 N 增大单调变薄；最外壳 εr 随 N 增大单调趋 1
    （→ λg 增大 → min_feature 增大）→ 厚度/最小特征比单调减，首个
    不可行 N 之后全不可行，遇到即停。
    返回 {"max_n", "thickness_report"(N_max 的 print_feasibility，N_max=0
    时 None), "strict_all_feasible_at_max_n", "hard_cap_hit"}。
    """
    R = _positive(radius, "radius")
    cap = _count(hard_cap, "hard_cap")
    best: dict | None = None
    best_n = 0
    strict_at_best = False
    for n in range(1, cap + 1):
        stack = discretize_shells(R, n, partition, representative)
        report = print_feasibility(stack, f0_hz, er_base, er_air)
        if report["all_thickness_ok"]:
            best = report
            best_n = n
            strict_at_best = bool(report["all_feasible"])
        else:
            return {
                "max_n": best_n,
                "thickness_report": best,
                "strict_all_feasible_at_max_n": strict_at_best,
                "hard_cap_hit": False,
            }
    return {
        "max_n": best_n,
        "thickness_report": best,
        "strict_all_feasible_at_max_n": strict_at_best,
        "hard_cap_hit": True,
    }


# ─── 4. 射线追踪（主判据）——路径 A：分壳 Snell ───────────────────────────────

_TOL = 1e-12  # 以 radius 为单位的几何容差（边界重命中/中心穿越）
_MAX_BOUNCES = 4096  # 防死循环守卫（物理上含反射也必然有限次出射）


def _refract(
    dx: float, dy: float, nx: float, ny: float, n1: float, n2: float
) -> tuple[float, float, bool]:
    """Snell 折射。(nx,ny)=球面外法向单位矢；自动定向使 ñ·d ≤ 0。

    返回 (dx', dy', tir)。n1/n2：入射侧/透射侧折射率。全反射时返回
    镜面反射方向并置 tir=True（物理反射，由调用方继续行进）。
    """
    if (dx * nx + dy * ny) > 0.0:
        nx, ny = -nx, -ny
    cos_i = -(dx * nx + dy * ny)
    eta = n1 / n2
    sin2_t = eta * eta * (1.0 - cos_i * cos_i)
    if sin2_t > 1.0:
        # 全反射：d' = d − 2(d·ñ)ñ = d + 2·cos_i·ñ
        return dx + 2.0 * cos_i * nx, dy + 2.0 * cos_i * ny, True
    cos_t = math.sqrt(1.0 - sin2_t)
    k = eta * cos_i - cos_t
    return eta * dx + k * nx, eta * dy + k * ny, False


def _hit_sphere(
    px: float, py: float, dx: float, dy: float, r_target: float
) -> float | None:
    """从 p 沿单位方向 d 到半径 r_target 球面的前方交点参数 t（无正解→None）。

    取大于容差的最小根：p 在目标球内（过近心点/穿心后推进）时近根为
    负、远根才是前方出射交点。
    """
    b = px * dx + py * dy
    c = px * px + py * py - r_target * r_target
    disc = b * b - c
    if disc < 0.0:
        return None
    sq = math.sqrt(disc)
    t1 = -b - sq
    if t1 > _TOL:
        return t1
    t2 = -b + sq
    if t2 > _TOL:
        return t2
    return None


def trace_ray_shells(stack: ShellStack, b_over_r: float) -> dict:
    """路径 A：分壳常 εr + 逐界面 Snell 的 2D 子午面射线追踪。

    平行束沿 +x 入射，撞击参数 b = b_over_r·R（入射点
    (−√(R²−b²), b)）。理想连续剖面焦点 = 对侧表面点 (R,0)：连续透镜
    内射线恰在 (R,0) 出射，故焦点误差取**出射点位置偏差**
    |P_exit − (R,0)|/R（面焦点口径；出射方向散布即点源馈电互易角）。

    返回 {"b_over_r", "exit_point": [x, y], "exit_dir": [dx, dy],
    "focal_error_over_r", "total_internal_reflection", "n_refractions"}。
    b_over_r ∉ (−1, 1) → ValueError（|b|=R 为掠射不进透镜；b 与 −b 为
    镜像等价射线，焦点误差逐位相同——物理恒等式，单测钉）。
    """
    if not isinstance(stack, ShellStack):
        raise ValueError("stack 必须为 ShellStack")
    bo = _finite(b_over_r, "b_over_r")
    if not -1.0 < bo < 1.0:
        raise ValueError(f"b_over_r={bo} 必须在 (-1, 1)（|b|=R 为掠射不进透镜）")
    R = stack.radius
    b = bo * R
    x = -math.sqrt(R * R - b * b)
    y = b
    dx, dy = 1.0, 0.0
    n_refrac = 0
    tir = False
    # 入射：空气 → 最外壳（外法向 û=(x,y)/R，_refract 自定向；Snell 传
    # 折射率 n=√εr，不是 εr 本身）
    dx, dy, tir0 = _refract(
        dx, dy, x / R, y / R, 1.0, math.sqrt(stack.eps_shells[-1])
    )
    tir = tir or tir0
    n_refrac += 1
    i = stack.n_shells - 1  # 当前壳（0=最内）
    for _ in range(_MAX_BOUNCES):
        r = math.hypot(x, y)
        ux, uy = x / r, y / r
        rdot = dx * ux + dy * uy
        if rdot > 0.0:  # 向外 → 下一界面 = 本壳外边界
            if i == stack.n_shells - 1:
                # 出射：最外壳 → 空气
                t = _hit_sphere(x, y, dx, dy, R)
                if t is None:
                    raise RuntimeError("射线向外但与 R 球无交点（数值异常）")
                x += t * dx
                y += t * dy
                dx, dy, tir0 = _refract(
                    dx, dy, x / R, y / R, math.sqrt(stack.eps_shells[i]), 1.0
                )
                tir = tir or tir0
                n_refrac += 1
                if tir0:
                    # 全反射：留在最外壳折返向内（不跨界面）
                    continue
                norm = math.hypot(dx, dy)
                dx, dy = dx / norm, dy / norm
                fx, fy = R, 0.0
                err = math.hypot(x - fx, y - fy)
                return {
                    "b_over_r": bo,
                    "exit_point": [x, y],
                    "exit_dir": [dx, dy],
                    "focal_error_over_r": err / R,
                    "total_internal_reflection": tir,
                    "n_refractions": n_refrac,
                }
            rb = stack.boundaries[i + 1]
            t = _hit_sphere(x, y, dx, dy, rb)
            if t is None:
                raise RuntimeError(f"壳 {i} 外边界 {rb} 无交点（数值异常）")
            x += t * dx
            y += t * dy
            dx, dy, tir0 = _refract(
                dx,
                dy,
                x / rb,
                y / rb,
                math.sqrt(stack.eps_shells[i]),
                math.sqrt(stack.eps_shells[i + 1]),
            )
            tir = tir or tir0
            n_refrac += 1
            if not tir0:
                i += 1
            # TIR：镜面反射留在本壳（壳序不推进）
        else:  # 向内 → 下一事件 = 本壳内边界（或壳内近心点转折）
            rb = stack.boundaries[i]
            t = _hit_sphere(x, y, dx, dy, rb)
            if t is None:
                # 近心点在本壳内（不触及内界面）：直线推过近心点+发丝，
                # 同壳转向外（壳内 εr 均匀，物理上无事件）。
                t = -(x * dx + y * dy)
                x += t * dx + _TOL * R * dx
                y += t * dy + _TOL * R * dy
                continue
            x += t * dx
            y += t * dy
            if rb <= 0.0:
                # 轴向穿心：壳 0 均匀 εr、r=0 法向无定义 → 方向不变直通
                x += _TOL * R * dx
                y += _TOL * R * dy
                continue
            dx, dy, tir0 = _refract(
                dx,
                dy,
                x / rb,
                y / rb,
                math.sqrt(stack.eps_shells[i]),
                math.sqrt(stack.eps_shells[i - 1]),
            )
            tir = tir or tir0
            n_refrac += 1
            if not tir0:
                i -= 1
            # TIR：镜面反射留在本壳（壳序不回退）
    raise RuntimeError(f"射线 {_MAX_BOUNCES} 次界面事件内未出射（数值异常）")


def bundle_focal_error(
    radius: float = 1.0,
    n_shells: int = 8,
    b_over_r_list: list[float] | None = None,
    partition: str = PARTITION_EQUAL_VOLUME,
    representative: str = REP_MIDPOINT,
) -> dict:
    """平行束汇聚误差聚合（路径 A）。

    b_over_r_list：撞击参数表（缺省 [0, 0.1, …, 0.6]，避开掠射 TIR 带）。
    逐射线焦点误差=出射点位置偏差 |P_exit − (R,0)|/R（面焦点口径）。
    单射线误差对"近心点≈壳边界"的重合敏感（近掠面折射，随 N/b 振荡的
    尖峰，实测见测试）——束级判断用 dense 网格的 ``rms_error_over_r``
    （把尖峰在束内平均掉），``max_error_over_r`` 保留作最坏值如实上报。

    返回 {"n_shells", "max_error_over_r", "rms_error_over_r",
    "median_error_over_r", "n_tir", "per_ray"}。
    """
    R = _positive(radius, "radius")
    n = _count(n_shells, "n_shells")
    rays = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6] if b_over_r_list is None else list(b_over_r_list)
    stack = discretize_shells(R, n, partition, representative)
    per_ray = [trace_ray_shells(stack, bo) for bo in rays]
    errs = sorted(rr["focal_error_over_r"] for rr in per_ray)
    n_tir = sum(1 for rr in per_ray if rr["total_internal_reflection"])
    max_err = errs[-1]
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    mid = len(errs) // 2
    median = errs[mid] if len(errs) % 2 == 1 else 0.5 * (errs[mid - 1] + errs[mid])
    return {
        "n_shells": n,
        "max_error_over_r": max_err,
        "rms_error_over_r": rms,
        "median_error_over_r": median,
        "n_tir": n_tir,
        "per_ray": per_ray,
    }


# ─── 5. 射线追踪——路径 B：连续剖面 RK4 ───────────────────────────────────────


def _ray_deriv(x: float, y: float, ux: float, uy: float, radius: float) -> tuple:
    """射线方程右端：d/ds(x,y,u) = (u, (∇n − (u·∇n)u)/n)。

    n(r)=√(2−(r/R)²)（连续剖面，域外 n=1 直线行进）；
    dn/dr = −r/(n·R²)。
    """
    R = radius
    r2 = x * x + y * y
    if r2 >= R * R:
        return ux, uy, 0.0, 0.0
    r = math.sqrt(r2)
    eps = 2.0 - r2 / (R * R)
    n = math.sqrt(eps)
    dndr = -r / (n * R * R)
    gx = 0.0 if r == 0.0 else dndr * x / r
    gy = 0.0 if r == 0.0 else dndr * y / r
    un = ux * gx + uy * gy
    return ux, uy, (gx - un * ux) / n, (gy - un * uy) / n


def trace_ray_continuous(
    b_over_r: float, radius: float = 1.0, ds_over_r: float = 1.0e-3, max_steps: int = 200000
) -> dict:
    """路径 B：连续剖面射线方程 RK4 积分（独立裁判，#118）。

    与路径 A 无共享离散（无壳、无界面 Snell——梯度连续弯折）；ds 取
    radius 的分数。出射点由出射步内对 |p|=R 的二次精确插值给出。
    返回字段同 trace_ray_shells（另有 ds_over_r/n_steps）。
    """
    bo = _finite(b_over_r, "b_over_r")
    if not -1.0 < bo < 1.0:
        raise ValueError(f"b_over_r={bo} 必须在 (-1, 1)（|b|=R 为掠射不进透镜）")
    R = _positive(radius, "radius")
    ds = _positive(ds_over_r, "ds_over_r") * R
    steps_cap = _count(max_steps, "max_steps")
    b = bo * R
    x = -math.sqrt(R * R - b * b)
    y = b
    ux, uy = 1.0, 0.0
    was_inside = False
    for step in range(steps_cap):
        # RK4（弧长参数化）
        k1 = _ray_deriv(x, y, ux, uy, R)
        k2 = _ray_deriv(
            x + 0.5 * ds * k1[0], y + 0.5 * ds * k1[1], ux + 0.5 * ds * k1[2], uy + 0.5 * ds * k1[3], R
        )
        k3 = _ray_deriv(
            x + 0.5 * ds * k2[0], y + 0.5 * ds * k2[1], ux + 0.5 * ds * k2[2], uy + 0.5 * ds * k2[3], R
        )
        k4 = _ray_deriv(
            x + ds * k3[0], y + ds * k3[1], ux + ds * k3[2], uy + ds * k3[3], R
        )
        px, py = x, y
        x += ds * (k1[0] + 2.0 * k2[0] + 2.0 * k3[0] + k4[0]) / 6.0
        y += ds * (k1[1] + 2.0 * k2[1] + 2.0 * k3[1] + k4[1]) / 6.0
        ux += ds * (k1[2] + 2.0 * k2[2] + 2.0 * k3[2] + k4[2]) / 6.0
        uy += ds * (k1[3] + 2.0 * k2[3] + 2.0 * k3[3] + k4[3]) / 6.0
        norm = math.hypot(ux, uy)
        ux, uy = ux / norm, uy / norm
        r = math.hypot(x, y)
        if r < R:
            was_inside = True
        elif was_inside:
            # 出射步：在 [prev, cur] 线段上对 |p|=R 二次解交（精确到截断误差）
            vx, vy = x - px, y - py
            bq = px * vx + py * vy
            cq = px * px + py * py - R * R
            aq = vx * vx + vy * vy
            disc = bq * bq - aq * cq
            tq = (-bq + math.sqrt(disc)) / aq  # 出射根（入射根 <0）
            tq = min(max(tq, 0.0), 1.0)
            xe, ye = px + tq * vx, py + tq * vy
            dxo, dyo = vx, vy
            err = math.hypot(xe - R, ye)
            return {
                "b_over_r": bo,
                "exit_point": [xe, ye],
                "exit_dir": [dxo / math.hypot(dxo, dyo), dyo / math.hypot(dxo, dyo)],
                "focal_error_over_r": err / R,
                "total_internal_reflection": False,
                "n_refractions": 0,
                "ds_over_r": ds / R,
                "n_steps": step + 1,
            }
    raise RuntimeError(f"连续射线 {steps_cap} 步内未出射（数值异常）")


def focal_error_convergence(
    radius: float = 1.0,
    n_shells_list: list[int] | None = None,
    b_over_r_list: list[float] | None = None,
    partition: str = PARTITION_EQUAL_VOLUME,
    representative: str = REP_MIDPOINT,
    ds_over_r: float = 1.0e-3,
) -> list[dict]:
    """离散壳数 N ↑ → 汇聚误差收敛表（含连续路径参照，#118 双路径）。

    收敛判断推荐 equal_thickness（等厚度壳厚均匀，束级 RMS 随 N 单调
    降，实测见测试）；equal_volume 内壳厚（含球心的胖壳）使单射线近心
    掠面尖峰权重更大，束级 RMS 在个别 N 上非单调（如实登记，不满足
    逐 N 单调断言的口径）。

    返回 [{"n_shells", "max_error_over_r", "rms_error_over_r", "n_tir"},
    ...] + 末项 {"n_shells": "continuous", "max_error_over_r",
    "rms_error_over_r", "ds_over_r"}。
    """
    R = _positive(radius, "radius")
    ns = [4, 8, 16, 32] if n_shells_list is None else list(n_shells_list)
    rows: list[dict] = []
    for n in ns:
        rep = bundle_focal_error(R, int(n), b_over_r_list, partition, representative)
        rows.append(
            {
                "n_shells": int(n),
                "max_error_over_r": rep["max_error_over_r"],
                "rms_error_over_r": rep["rms_error_over_r"],
                "n_tir": rep["n_tir"],
            }
        )
    rays = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6] if b_over_r_list is None else list(b_over_r_list)
    cont = [trace_ray_continuous(bo, R, ds_over_r) for bo in rays]
    cont_errs = [c["focal_error_over_r"] for c in cont]
    rows.append(
        {
            "n_shells": "continuous",
            "max_error_over_r": max(cont_errs),
            "rms_error_over_r": math.sqrt(
                sum(e * e for e in cont_errs) / len(cont_errs)
            ),
            "ds_over_r": ds_over_r,
        }
    )
    return rows
