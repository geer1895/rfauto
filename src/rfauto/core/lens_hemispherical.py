"""LM-3 extended hemispherical 介质透镜综合内核（硅基双槽天线透镜族）。

法源（铁律 5：来源写 docstring；裁判=独立来源/独立路径，不自证，#118）：

- 一手原文：D. F. Filipovic, S. S. Gearhart, G. M. Rebeiz, "Double-Slot
  Antennas on Extended Hemispherical and Elliptical Silicon Dielectric
  Lenses", IEEE Trans. Microwave Theory Techn., vol. 41, no. 10,
  pp. 1738-1749 (Oct. 1993)。IEEE 付费墙外的可达全文 = 同文 ISSTT'93
  扩展版预印本（NRAO）：
  https://www.nrao.edu/meetings/isstt/papers/1993/1993157183.pdf
  （2026-09-28 实测可达，27 页，全文文本抽取逐段核对）。TMTT 排版版
  Deep Blue 副本 2026-09-28 实测因美国 DOJ bulk sensitive data 规定对
  部分地区 geo-blocked（命中页如实登记，不转引不可核内容）。
- 二手核对方（同组同口径）：D. F. Filipovic, G. V. Eleftheriades,
  G. M. Rebeiz, "Off-Axis Imaging Properties of Substrate Lens Antennas",
  Fifth Int. Symp. Space Terahertz Technology, pp. 778-787 (1994)，
  https://web.eecs.umich.edu/~jeast/filipovic_1994_12_2.pdf
  （2026-09-28 实测可达；扫描件逐页目检，p.779-780 关键句直接钉锚点）。

原文锚点逐项回收（本模块常量 = 下方引文逐字数字，非转述口径）：

- L/R=0.29（hyperhemispherical / aplanatic 位置）：'94 p.779 "the
  hyperhemispherical lens is aplanatic, implying the absence of spherical
  abberations, and satisfies the sine condition"；同页 "the
  hyperhemispherical length (R/n)" → 闭式 **L/R = 1/n**（硅 n=√11.7=
  3.4205 → 0.2924；原文印刷 2000μm/6.85mm=0.2920 同证）。'94 Fig.2(a)
  图例 "L/R=.29 (Hyperhemisphere)"。
- L/R=0.32-0.35（single-unit 高高斯耦合带）：'93 摘要 "there exists a
  wide range of extension lengths (ext. length/radius ...0.32 to 0.35)
  which result in high Gaussian-coupling efficiencies (50-60%)"（无帽；
  配 λm/4 帽后 80-90%）。'94 p.782 实验透镜 R=6.858mm、L=2.20mm
  （L/R=0.3208）落本带；'94 Fig.2(a) 图例中位 "L/R=.34"。
- L/R=0.38-0.39（peak directivity / synthesized ellipse 位置）：'93 摘要
  "an extension length/radius=0.38 to 0.39 (depending on frequency) will
  result in peak directivity"；§II 综合式：椭圆偏心率取 e=1/n（原文引
  其文献 [8]："the eccentricity of the ellipse such that the geometric
  focus becomes the optical focus"），单位球叠加条件 L = b+c−1（"The
  distance from the circular tip of an extended hemisphere to the end of
  its extension is equal to 1+L ... yields L = b+c−1"），对硅拟合
  "a=1.03 and b=1.07691 ... L = 2670μm for a 13.7mm diameter lens"
  → 2670/6850 = 0.3898；由印刷拟合值复算 L/R = b+√(b²−a²)−1 = 0.3913
  （印刷舍入带内一致，见 :func:`synth_ellipse_lr`）。'94 Fig.2(a) 图例
  "L/R=.39 (Synth. Ellipse)"。
- 匹配帽：'93 反射损耗节 "a λm/4 matching cap layer with dielectric
  constant equal to √εr" → 帽介质 εr_cap = √εr_lens（硅 → 3.42，
  "synthesized quartz" 口径），n_cap = √εr_cap = εr_lens^(1/4) =
  √(n_lens·n_air)（几何平均折射率，λ/4 变换器零反射条件，本模块闭式
  :func:`cap_index_optimal`）；帽厚 t = λm/4，λm = λ0/n_cap 为**帽内**
  波长 → t = λ0/(4·n_cap)（:func:`cap_thickness`；注意 λm 不是 λ0/n_lens
  ——同材料读法只在 n_cap=n_lens 时成立，此处按原文 √εr 帽口径钉死）。
- 硅折射率口径钉死：原文全篇 εr=11.7（'94 p.780 "silicon (εr=11.7)"）
  → n=√11.7=3.420526（本模块缺省 :data:`N_SILICON`）；后续文献常见
  n=3.416（εr≈11.67）作为替代口径登记于 :data:`N_SILICON_ALT`，不进
  缺省。1/n 两口径分别 0.29235/0.29274，均落原文锚 0.29 印刷精度内。

几何约定（2D 剖面，旋转对称取 x-y 平面，同原文 '94 Fig.1）：

- 半球球心 O=(0,0)，半径 R（内核全部按 R=1 归一，物理米制只进
  :func:`design_lens` 的米制换算）；延伸段长 L=lr·R，馈源（planar
  antenna）在延伸平面圆心 (0,−L)，透镜轴 +y；出射面=球面 x²+y²=R²。
- 射线步进：均匀媒质内直线 → 球面单次折射（矢量 Snell，n_lens→n_air
  默认 1）；全内反射（TIR）判据 n·sinθᵢ>1 逐射线打标不静默
  （:func:`refract_direction` 返回 None）。临界角（密→疏内表面）
  θc=asin(1/n)（:func:`critical_angle_deg`）。

验证面（主判据，双路径 #118）：

- 解析路径 A：aplanatic 恒等式——L/R=1/n 时球面折射无球差且满足正弦
  条件（原文 p.779 引文），出射束反向延长线**逐射线**精确交于轴上虚
  焦点 y=−n·R（经典球的一对 aplanatic 点成像定理，非近轴近似）。
  :func:`aplanatic_stigmatism_dev` 实测最大偏差 ~1e-14（单测钉 <1e-9）。
- 数值路径 B（准直扫描）：:func:`collimation_scan` 对 L/R 网格逐点
  trace 射线扇（±θmax 内均匀取角），以出射角 RMS 残差为极小目标。
  实测行为（2026-09-28 scratch 预演+缺省网格复测，如实登记）：极小值
  位置随口径单调滑移——±0.5° 半锥角时 0.4150（近轴闭式 1/(n−1)=
  0.41313，即出射面顶点密切椭圆 e=1/n、馈在远焦点的几何光学准直位置，
  两条独立推导：近轴折射公式 s'→∞ 与 e/(1−e) 代换，单测互证；细网格
  scratch 极值 0.4130）；±10° 时 0.4100；±30° 时 0.3950（细网格
  0.3935）；±40° 时 0.3800——落原文 0.38-0.39 锚 ±5% 位置带
  [0.36575, 0.40425] 内（极值位置随网格步长在带内微移，如实登记）。**"三锚点处残差极小"的如实口径**：极小值只在
  collimating 锚（0.38-0.39）附近成立；aplanatic 锚（0.29）的出射束
  发散（虚焦点 n·R，设计语义=成像放大 n 倍+零像差，非准直），其裁判
  是上面的恒等式 A 而非准直残差；intermediate 锚（0.32-0.35）残差单调
  过渡，无极值声明（登记面）。
- TIR 域：aplanatic 位置 sinθᵢ=(1/n)·sinθ_feed 恒 <1/n → 全域无 TIR
  （±89° 实测 tir_count=0）；L/R 增大后临界馈角 θfeed,c =
  asin(1/(lr·n))（0.39 时 48.6°），超出即逐射线 TIR 打标。

登记面（只登记不判收，#122 如实）：

- 增益/口径面：:func:`aperture_registration` 只给物理口径面积与
  η_ap·(π·D/λ0)² 解析口径（η_ap 由调用方供给；原文口径：无帽 50-60%
  高斯耦合效率（0.32-0.35 带）、λm/4 帽后 80-90%、0.38-0.39 峰值
  directivity 但阵列封装耦合效率低 15-20%——数字逐字来自引文，供
  参考非本模块裁判）；精确方向图/高斯耦合度积分=全波（P3）后续，
  本内核不做。
- 三锚点表 ：func:`anchor_table`：名义值/带宽/语义/来源引文逐项登记。

接口：纯算法零 IO；math 标量/纯 list 进出，JSON 可序列化（complex 只
在 :func:`quarter_wave_input_impedance` 返回值出现，docstring 显式声明
由调用方转 JSON）；dataclass+to_dict；数值 0.0 合法（判缺失一律
is not None，#364④）；bool 显式拒收（df7+⑯）。边界：R≤0 / n≤1 /
lr<0 / lr≥1（馈源不在透镜内）→ ValueError；λ0≤0、效率∉[0,1] 同收。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ─── 法源常量（原文印刷值逐字）───────────────────────────────────────────────

#: 高阻硅介电常数（'94 p.780 verbatim "silicon (εr=11.7)"）
ER_SILICON = 11.7
#: 硅折射率 = √εr（原文口径的平方根换算，模块缺省）
N_SILICON = math.sqrt(ER_SILICON)
#: 替代口径：部分后续文献沿用 n=3.416（εr≈11.67）；登记非缺省
N_SILICON_ALT = 3.416

#: 原文锚点（印刷值逐字）：aplanatic/hyperhemispherical 位置
LR_APLANATIC_PAPER = 0.29
#: single-unit 高高斯耦合带（'93 摘要 verbatim "0.32 to 0.35"）
LR_SINGLE_UNIT_BAND = (0.32, 0.35)
#: peak directivity / synthesized ellipse 带（'93 摘要 verbatim "0.38 to 0.39"）
LR_PEAK_DIRECTIVITY_BAND = (0.38, 0.39)

#: '94 Fig.2(a) 中位锚（intermediate 实验点）
LR_INTERMEDIATE_PAPER = 0.34

#: §II 硅拟合椭圆半轴（原文 verbatim "a=1.03 and b=1.07691"，单位球口径）
SYNTH_FIT_A_SILICON = 1.03
SYNTH_FIT_B_SILICON = 1.07691
#: 原文印刷综合透镜几何：L=2670μm、直径 13.7mm（→R=6.85mm）
SYNTH_L_UM_SILICON = 2670.0
SYNTH_DIAM_MM_SILICON = 13.7

#: 馈源工况枚举（feed_regime）
FEED_APLANATIC = "aplanatic"
FEED_SINGLE_UNIT = "single_unit"
FEED_PEAK_DIRECTIVITY = "peak_directivity"

#: 射线/扫描的容差与网格缺省
_AXIS_SINGULAR_TOL = 1e-15

_SOURCE_NOTE = (
    "Filipovic/Gearhart/Rebeiz IEEE TMTT 41(10):1738-1749 (1993); "
    "reachable full text = ISSTT'93 extended preprint (NRAO) "
    "https://www.nrao.edu/meetings/isstt/papers/1993/1993157183.pdf; "
    "companion: Filipovic/Eleftheriades/Rebeiz ISSTT'94 pp.778-787 "
    "https://web.eecs.umich.edu/~jeast/filipovic_1994_12_2.pdf"
)


# ─── 入参收敛守卫（同 aging.py 家族约定）─────────────────────────────────────


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


def _index(value: float, name: str) -> float:
    """透镜折射率收敛：有限、>1（n≤1 无折射语义，任务书边界）。"""
    out = _positive(value, name)
    if out <= 1.0:
        raise ValueError(f"{name} 必须 >1（介质透镜无折射语义）")
    return out


def _lr(value: float, name: str) -> float:
    """延伸比收敛：0 ≤ lr < 1（lr≥1 馈源不在透镜介质内，无物理意义）。"""
    out = _nonneg(value, name)
    if out >= 1.0:
        raise ValueError(f"{name} 必须 <1（馈源须在透镜介质内部）")
    return out


# ─── Snell 单界面（矢量形式，2D）─────────────────────────────────────────────


def refract_direction(
    dx: float, dy: float, nx: float, ny: float, n1: float, n2: float
) -> tuple[float, float] | None:
    """矢量 Snell 折射：入射方向 (dx,dy)、界面法向 (nx,ny)（指向入射侧，
    即 nx·dx+ny·dy<0），n1→n2。返回单位折射方向二元组；全内反射返回
    None（逐射线打标语义，不抛异常）。n1·sinθ1=n2·sinθ2 数值恒等式由
    单测按出射/入射角回收钉住。"""
    d1 = math.hypot(dx, dy)
    nrm = math.hypot(nx, ny)
    if d1 == 0.0 or nrm == 0.0:
        raise ValueError("方向/法向向量不得为零向量")
    ux, uy = dx / d1, dy / d1
    vx, vy = nx / nrm, ny / nrm
    cos_i = -(ux * vx + uy * vy)  # >0（法向指向入射侧）
    if cos_i <= 0.0:
        raise ValueError("法向须指向入射侧（n·d < 0）")
    eta = n1 / n2
    sin2_t = eta * eta * (1.0 - cos_i * cos_i)
    if sin2_t > 1.0:
        return None  # 全内反射（n1·sinθi > n2）
    cos_t = math.sqrt(1.0 - sin2_t)
    k = eta * cos_i - cos_t
    tx, ty = eta * ux + k * vx, eta * uy + k * vy
    tn = math.hypot(tx, ty)
    return (tx / tn, ty / tn)


def critical_angle_deg(n_lens: float) -> float:
    """密→疏内表面全内反射临界角（度）：asin(1/n)。"""
    n = _index(n_lens, "n_lens")
    return math.degrees(math.asin(1.0 / n))


# ─── 闭式：aplanatic / 近轴准直 / 综合椭圆 ───────────────────────────────────


def aplanatic_lr(n: float) -> float:
    """aplanatic（hyperhemispherical）延伸比 L/R = 1/n（原文 p.779 闭式
    "the hyperhemispherical length (R/n)"）。此位置球面折射零球差且满足
    正弦条件；出射束反向延长精确交于轴上虚焦点 −n·R（stigmatism）。"""
    return 1.0 / _index(n, "n")


def paraxial_collimation_lr(n: float) -> float:
    """近轴（几何光学）准直延伸比 L/R = 1/(n−1)。

    路径 A：单球面折射近轴公式 n/s + 1/s' = (n−1)/R（s=R+L，顶点在
    球面极点、曲率中心在入射侧）令 s'→∞；
    路径 B：密切椭圆代换——e=1/n 的 aplanatic 椭圆（馈在远焦点出射
    平行光，:func:`aplanatic_lr` 同源条件）顶点曲率半径 R=b²/a、馈距
    L=a·e(1+e) → L/R = e/(1−e)。两路径逐位同式（单测互证，#118）。
    注意：这是近轴值（硅 0.4131），高于原文有限口径峰值 directivity 锚
    0.38-0.39——差异=有限口径球差平衡（如实登记，非矛盾）。"""
    n_ = _index(n, "n")
    e = 1.0 / n_
    if e >= 1.0:  # pragma: no cover - n>1 已保证
        raise ValueError("偏心率须 <1")
    inv_by_refraction = 1.0 / (n_ - 1.0)
    inv_by_ellipse = e / (1.0 - e)
    if abs(inv_by_refraction - inv_by_ellipse) > 1e-12 * inv_by_refraction:
        # 两条推导路径必须一致（代数恒等，防实现漂移）
        raise AssertionError("近轴准直两条闭式路径不一致")
    return inv_by_refraction


def synth_ellipse_lr(a: float, b: float) -> float:
    """原文 §II 综合式复算：单位球叠加条件 L = b+c−1（c=√(b²−a²)）。

    a/b 为拟合椭圆半轴（单位球口径，b 为沿轴半长轴，b>a>0）；返回
    L/R。e=√(1−(a/b)²) 由代换在返回值内隐含，不单独校验 e=1/n（拟合
    舍入带内成立，原文印刷 a=1.03/b=1.07691 → e=0.29187 vs 1/n=0.29235）。
    """
    a_ = _positive(a, "a")
    b_ = _positive(b, "b")
    if b_ <= a_:
        raise ValueError("b 必须 > a（沿轴半长轴口径）")
    c = math.sqrt(b_ * b_ - a_ * a_)
    lr = b_ + c - 1.0
    if lr < 0.0:
        raise ValueError(f"拟合半轴给出的延伸比为负（a={a}, b={b}）")
    return lr


# ─── 射线追踪（2D 剖面，主判据验证面）────────────────────────────────────────


def _hit_point(lr: float, theta_rad: float) -> tuple[float, float]:
    """馈源 (0,−lr) 沿角 theta（自 +y 轴）的射线与单位球 x²+y²=1 的交点。

    解 |F+t·d|²=1：t²+2t(F·d)+lr²−1=0，取正根（馈源在球内 → 判别式
    恒正）。"""
    dx, dy = math.sin(theta_rad), math.cos(theta_rad)
    fx, fy = 0.0, -lr
    b = fx * dx + fy * dy
    disc = b * b - (lr * lr - 1.0)
    t = -b + math.sqrt(disc)
    return (fx + t * dx, fy + t * dy)


def trace_ray(lr: float, n: float, theta_deg: float) -> dict:
    """单射线追踪（单位球口径）：馈源自 (0,−lr) 以角 theta（自 +y 轴，
    度）入射 → 媒质内直线 → 球面单次折射（n→空气 n_air=1）。

    返回 JSON 可序列化 dict：
    {"theta_feed_deg", "hit_x", "hit_y"（球面命中点）,
     "theta_out_deg"（出射角，自 +y 轴，度；TIR 时 None）,
     "tir"（bool）,
     "axis_cross"（出射束反向延长线与轴交点 y；TIR/近轴奇异时 None）}。

    axis_cross 的用途：aplanatic 位置（lr=1/n）对**任意**馈角恒等于
    −n（stigmatism 恒等式，见 :func:`aplanatic_stigmatism_dev`）。
    """
    lr_ = _lr(lr, "lr")
    n_ = _index(n, "n")
    theta = math.radians(_finite(theta_deg, "theta_deg"))
    px, py = _hit_point(lr_, theta)
    dx, dy = math.sin(theta), math.cos(theta)
    # 界面法向指向入射侧（球内）= −P/|P|
    ref = refract_direction(dx, dy, -px, -py, n_, 1.0)
    if ref is None:
        return {
            "theta_feed_deg": theta_deg,
            "hit_x": px,
            "hit_y": py,
            "theta_out_deg": None,
            "tir": True,
            "axis_cross": None,
        }
    tx, ty = ref
    theta_out = math.degrees(math.atan2(tx, ty))
    # 近轴射线反向延长线即轴本身，交点退化（None=如实缺失）
    axis_cross = None if abs(tx) <= _AXIS_SINGULAR_TOL else py - ty * (px / tx)
    return {
        "theta_feed_deg": theta_deg,
        "hit_x": px,
        "hit_y": py,
        "theta_out_deg": theta_out,
        "tir": False,
        "axis_cross": axis_cross,
    }


def trace_fan(lr: float, n: float, theta_max_deg: float, num_rays: int) -> dict:
    """射线扇追踪与准直残差统计（±theta_max 内均匀 num_rays 条）。

    返回 dict：
    {"theta_feed_deg": list, "theta_out_deg": list（TIR 位 None）,
     "tir_count", "emergent_count",
     "residual_rms_deg"（出射角有符号 RMS——对称扇均值≈0，rms 即发散度）,
     "residual_max_deg"（最大 |出射角|）,
     "axis_cross": list}。

    残差只对非 TIR 射线统计；全部 TIR 时 residual 为 None（如实缺失，
    is not None 判缺失）。
    """
    lr_ = _lr(lr, "lr")
    n_ = _index(n, "n")
    half = _nonneg(theta_max_deg, "theta_max_deg")
    if half >= 90.0:
        raise ValueError("theta_max_deg 必须 <90（射线须朝出射半球）")
    if not isinstance(num_rays, int) or isinstance(num_rays, bool):
        raise ValueError("num_rays 必须为 int")
    if num_rays < 2:
        raise ValueError("num_rays 必须 >=2")
    theta_feed: list[float] = []
    theta_out: list[float | None] = []
    axis_cross: list[float | None] = []
    tir = 0
    for i in range(num_rays):
        th = -half + (2.0 * half) * i / (num_rays - 1)
        ray = trace_ray(lr_, n_, th)
        theta_feed.append(ray["theta_feed_deg"])
        theta_out.append(ray["theta_out_deg"])
        axis_cross.append(ray["axis_cross"])
        if ray["tir"]:
            tir += 1
    vals = [v for v in theta_out if v is not None]
    if vals:
        rms = math.sqrt(sum(v * v for v in vals) / len(vals))
        vmax = max(abs(v) for v in vals)
    else:
        rms = None
        vmax = None
    return {
        "theta_feed_deg": theta_feed,
        "theta_out_deg": theta_out,
        "tir_count": tir,
        "emergent_count": len(vals),
        "residual_rms_deg": rms,
        "residual_max_deg": vmax,
        "axis_cross": axis_cross,
    }


def aplanatic_stigmatism_dev(
    n: float, num_rays: int = 41, theta_max_deg: float = 40.0
) -> float:
    """aplanatic stigmatism 恒等式裁判（路径 A）：

    L/R=1/n 时全部出射射线反向延长交于虚焦点 y=−n·R（单位球）。
    返回 max |axis_cross + n|（应 ~1e-14 量级；单测钉 <1e-9）。
    近轴奇异射线（axis_cross=None）自动跳过；射线数不足报错。"""
    n_ = _index(n, "n")
    half = _nonneg(theta_max_deg, "theta_max_deg")
    if half <= 0.0:
        raise ValueError("theta_max_deg 必须 >0")
    lr = aplanatic_lr(n_)
    fan = trace_fan(lr, n_, half, num_rays)
    devs = [
        abs(c + n_) for c in fan["axis_cross"] if c is not None
    ]
    if not devs:
        raise ValueError("无有效 axis_cross（射线网格全落近轴奇异）")
    return max(devs)


def collimation_scan(
    n: float,
    theta_max_deg: float = 30.0,
    lr_lo: float = 0.20,
    lr_hi: float = 0.48,
    num_lr: int = 57,
    num_rays: int = 81,
) -> dict:
    """准直残差 vs L/R 网格扫描（路径 B 主判据）：逐点 trace_fan 取
    residual_rms_deg 极小。

    返回 dict：
    {"n", "theta_max_deg", "paraxial_lr"（闭式 1/(n−1) 对照锚）,
     "best_lr", "best_residual_rms_deg",
     "best_residual_max_deg", "tir_count"（best 点）,
     "table": [{"lr", "residual_rms_deg", "residual_max_deg",
                "tir_count"}, ...]}。

    预演实测（2026-09-28，n=√11.7，缺省网格步长 ~0.0049；细网格
    0.0005 步 scratch 值括注）：±0.5° → best 0.4150（scratch 0.4130，
    近轴闭式 0.41313）；±10° → 0.4100；±20° → 0.4040（scratch）；±30° →
    0.3950（scratch 0.3935）；±40° → 0.3800——单调滑移，±30° 落原文
    peak-directivity 锚 0.385±5% 带 [0.36575, 0.40425]。纯网格采样
    （确定性，无优化器随机性）。"""
    n_ = _index(n, "n")
    half = _nonneg(theta_max_deg, "theta_max_deg")
    if half >= 90.0:
        raise ValueError("theta_max_deg 必须 <90")
    lo = _nonneg(lr_lo, "lr_lo")
    hi = _lr(lr_hi, "lr_hi")
    if hi <= lo:
        raise ValueError("lr_hi 必须 > lr_lo")
    if not isinstance(num_lr, int) or isinstance(num_lr, bool) or num_lr < 2:
        raise ValueError("num_lr 必须为 >=2 的 int")
    if not isinstance(num_rays, int) or isinstance(num_rays, bool) or num_rays < 2:
        raise ValueError("num_rays 必须为 >=2 的 int")
    table: list[dict] = []
    best: dict | None = None
    for i in range(num_lr):
        lr = lo + (hi - lo) * i / (num_lr - 1)
        fan = trace_fan(lr, n_, half, num_rays)
        row = {
            "lr": lr,
            "residual_rms_deg": fan["residual_rms_deg"],
            "residual_max_deg": fan["residual_max_deg"],
            "tir_count": fan["tir_count"],
        }
        table.append(row)
        rms = fan["residual_rms_deg"]
        if rms is not None and (best is None or rms < best["residual_rms_deg"]):
            best = row
    if best is None:
        raise ValueError("扫描域内全部 TIR（无有效出射）")
    return {
        "n": n_,
        "theta_max_deg": half,
        "paraxial_lr": paraxial_collimation_lr(n_),
        "best_lr": best["lr"],
        "best_residual_rms_deg": best["residual_rms_deg"],
        "best_residual_max_deg": best["residual_max_deg"],
        "tir_count": best["tir_count"],
        "table": table,
    }


# ─── 锚点表（登记面，来源逐项钉死）───────────────────────────────────────────


def anchor_table(n: float | None = None) -> list[dict]:
    """L/R 三锚点表（原文印刷值+闭式，语义/来源逐项登记）。

    n 缺省用 :data:`N_SILICON`（判缺失 is not None）。返回 JSON 可序列化
    list[dict]，字段：name / lr_nominal / lr_band / lr_closed_form /
    regime / source。闭式只对 aplanatic（1/n）与综合椭圆复算
    （b+c−1）存在；intermediate 带无闭式（原文数值带，如实登记）。"""
    n_ = N_SILICON if n is None else _index(n, "n")
    lr_synth = synth_ellipse_lr(SYNTH_FIT_A_SILICON, SYNTH_FIT_B_SILICON)
    return [
        {
            "name": "hyperhemispherical_aplanatic",
            "lr_nominal": LR_APLANATIC_PAPER,
            "lr_band": None,
            "lr_closed_form": aplanatic_lr(n_),
            "regime": (
                "零球差+正弦条件（零彗差）；成像放大 n 倍（虚焦点 n·R，束发散）；"
                "高斯耦合 ~100%；全域无 TIR"
            ),
            "source": (
                "Filipovic'93 §II/p.779(ISSTT'94) 'hyperhemispherical length (R/n)'；"
                "'94 Fig.2(a) L/R=.29 (Hyperhemisphere)；印刷 2000μm/6.85mm=0.2920"
            ),
        },
        {
            "name": "intermediate_single_unit",
            "lr_nominal": LR_INTERMEDIATE_PAPER,
            "lr_band": list(LR_SINGLE_UNIT_BAND),
            "lr_closed_form": None,
            "regime": (
                "单单元高斯耦合效率带（无帽 50-60%、λm/4 帽后 80-90%）；"
                "准直残差单调过渡，无极值声明"
            ),
            "source": (
                "Filipovic'93 摘要 'ext. length/radius ...0.32 to 0.35'；"
                "'94 p.782 实验透镜 L/R=2.20/6.858=0.3208；'94 Fig.2(a) L/R=.34"
            ),
        },
        {
            "name": "peak_directivity_synth_ellipse",
            "lr_nominal": 0.385,
            "lr_band": list(LR_PEAK_DIRECTIVITY_BAND),
            "lr_closed_form": lr_synth,
            "regime": (
                "峰值 directivity（衍射极限）/综合椭圆位置（近似准直，有限口径"
                "残差极小随口径滑移，见 collimation_scan）；阵列高密度封装"
                "耦合效率低 15-20%"
            ),
            "source": (
                "Filipovic'93 摘要 '0.38 to 0.39 ... peak directivity'；§II 综合"
                "式 L=b+c−1（e=1/n），硅拟合 a=1.03/b=1.07691 → 复算 "
                f"{lr_synth:.4f}，印刷 L=2670μm/Φ13.7mm → 0.3898；"
                "'94 Fig.2(a) L/R=.39 (Synth. Ellipse)"
            ),
        },
    ]


# ─── 匹配帽（λm/4 变换器）与口径登记面 ───────────────────────────────────────


def quarter_wave_input_impedance(z_t: complex, z_l: complex) -> complex:
    """λ/4 传输线变换恒等式：Z_in = Z_T²/Z_L（复 Z_L 任意，逐位）。

    由 λ/4 处 ABCD 矩阵 [0, jZ_T; j/Z_T, 0] 与 Z_in=(A·Z_L+B)/(C·Z_L+D)
    代出；独立路径（无损线方程 tanh(jπ/2) 极限）同式（单测互证，#118）。
    返回 complex（调用方负责 JSON 转换——本函数不产 dict）。"""
    zt = complex(z_t)
    zl = complex(z_l)
    if zt == 0 or zl == 0:
        raise ValueError("Z_T 与 Z_L 均不得为 0")
    return zt * zt / zl


def cap_index_optimal(n_lens: float, n_out: float = 1.0) -> float:
    """λ/4 帽最优折射率 = √(n_lens·n_out)（空气侧缺省 1）。

    原文口径 "dielectric constant equal to √εr"：εr_cap = √(εr_lens·εr_out)
    → n_cap = εr_lens^(1/4)（硅 1.8495，"synthesized quartz" 3.42 介电
    常数口径）。零反射条件由 :func:`cap_reflection` 两路径数值钉。"""
    nl = _index(n_lens, "n_lens")
    no = _positive(n_out, "n_out")
    return math.sqrt(nl * no)


def cap_thickness(lambda0_m: float, n_cap: float) -> float:
    """λ/4 帽厚度 t = λ0/(4·n_cap)（λm=λ0/n_cap 为帽内波长，t=λm/4）。

    恒等式：4·n_cap·t/λ0 == 1.0（逐位，单测钉）。"""
    lam = _positive(lambda0_m, "lambda0_m")
    nc = _positive(n_cap, "n_cap")
    return lam / (4.0 * nc)


def cap_reflection(
    n_lens: float,
    n_cap: float,
    n_out: float = 1.0,
    lambda0_m: float | None = None,
) -> dict:
    """λ/4 帽反射系数（正入射振幅）双路径（#118）：

    - 路径 A（变换器）：Z_i=1/n_i（媒质特征阻抗，比例无关），
      Z_in=Z_cap²/Z_lens，Γ=(Z_in−Z_out)/(Z_in+Z_out)；
    - 路径 B（多层 Fresnel 精确式）：δ=2π·n_cap·d/λ0（d=λ0/(4·n_cap) 时
      δ=π/2），Γ=(r01+r12·e^{2jδ})/(1+r01·r12·e^{2jδ})，r_ij=(Z_j−Z_i)/(Z_j+Z_i)。

    lambda0_m 缺省 None → 归一 λ0=1（λ/4 厚度下 Γ 与 λ0 无关，如实
    登记）。返回 JSON 可序列化 dict（complex 一律转 |Γ|/相位）：
    {"gamma_abs"（双路径公共值）, "gamma_deg", "path_abs_diff",
     "gamma_bare_abs"（无帽界面反射）, "optimal_cap_index",
     "thickness_m", "zero_at_optimal"（|Γ|<1e-12）}。"""
    nl = _index(n_lens, "n_lens")
    nc = _positive(n_cap, "n_cap")
    no = _positive(n_out, "n_out")
    lam = 1.0 if lambda0_m is None else _positive(lambda0_m, "lambda0_m")

    z_lens, z_cap, z_out = 1.0 / nl, 1.0 / nc, 1.0 / no
    # 路径 A：λ/4 变换器
    z_in = quarter_wave_input_impedance(z_cap, z_lens)
    gamma_a = (z_in - z_out) / (z_in + z_out)
    # 路径 B：多层 Fresnel（e^{2jδ} = -1 at δ=π/2，逐式构造不做手代）
    delta = 2.0 * math.pi * nc * cap_thickness(lam, nc) / lam
    phase = complex(math.cos(2.0 * delta), math.sin(2.0 * delta))
    r01 = (z_cap - z_out) / (z_cap + z_out)
    r12 = (z_lens - z_cap) / (z_lens + z_cap)
    gamma_b = (r01 + r12 * phase) / (1.0 + r01 * r12 * phase)
    diff = abs(gamma_a - gamma_b)
    gamma_bare = (z_lens - z_out) / (z_lens + z_out)
    return {
        "gamma_abs": abs(gamma_a),
        "gamma_deg": math.degrees(math.atan2(gamma_a.imag, gamma_a.real)),
        "path_abs_diff": diff,
        "gamma_bare_abs": abs(gamma_bare),
        "optimal_cap_index": cap_index_optimal(nl, no),
        "thickness_m": cap_thickness(lam, nc),
        "zero_at_optimal": abs(gamma_a) < 1e-12,
    }


def aperture_registration(
    radius_m: float,
    lambda0_m: float | None = None,
    aperture_efficiency: float | None = None,
) -> dict:
    """增益/口径登记面（只登记不判收）：物理口径 A=πR²；可选解析增益
    G=η_ap·(π·D/λ0)²（D=2R；η_ap 由调用方供给——原文口径数字见模块头
    登记节，本模块不裁判效率取值）。精确方向图/高斯耦合积分=全波
    （P3）后续，不在本内核。lambda0_m 或 aperture_efficiency 缺失
    （None）→ 对应字段 None（判缺失 is not None）。"""
    r = _positive(radius_m, "radius_m")
    out: dict = {
        "diameter_m": 2.0 * r,
        "aperture_area_m2": math.pi * r * r,
        "gain": None,
    }
    if lambda0_m is not None and aperture_efficiency is not None:
        lam = _positive(lambda0_m, "lambda0_m")
        eta = _finite(aperture_efficiency, "aperture_efficiency")
        if not 0.0 <= eta <= 1.0:
            raise ValueError("aperture_efficiency 须在 [0,1]")
        out["gain"] = eta * (math.pi * 2.0 * r / lam) ** 2
    return out


# ─── 设计面（dataclass + to_dict）────────────────────────────────────────────


@dataclass
class LensDesign:
    """extended hemispherical 透镜设计（米制）；to_dict 输出 JSON 可序列化。"""

    radius_m: float
    n: float
    lr: float
    feed_regime: str
    extension_m: float
    aplanatic_lr: float
    paraxial_collimation_lr: float
    critical_angle_deg: float
    cap: dict | None = None
    aperture: dict | None = None
    lambda0_m: float | None = None
    source: str = _SOURCE_NOTE

    def to_dict(self) -> dict:
        """JSON 可序列化 dict（含锚点语义速览）。"""
        return {
            "radius_m": self.radius_m,
            "n": self.n,
            "lr": self.lr,
            "feed_regime": self.feed_regime,
            "extension_m": self.extension_m,
            "aplanatic_lr": self.aplanatic_lr,
            "paraxial_collimation_lr": self.paraxial_collimation_lr,
            "critical_angle_deg": self.critical_angle_deg,
            "cap": self.cap,
            "aperture": self.aperture,
            "lambda0_m": self.lambda0_m,
            "source": self.source,
        }


def design_lens(
    radius_m: float,
    n: float = N_SILICON,
    lr: float | None = None,
    feed_regime: str = FEED_SINGLE_UNIT,
    lambda0_m: float | None = None,
    with_cap: bool = False,
    cap_n: float | None = None,
    aperture_efficiency: float | None = None,
) -> LensDesign:
    """综合一个 extended hemispherical 透镜设计（米制出口）。

    lr 显式给定时优先生效；lr 缺省（None，判缺失 is not None）按
    feed_regime 取锚：aplanatic → 1/n（闭式）；single_unit → 0.32-0.35
    带中位 0.335；peak_directivity → 0.38-0.39 带中位 0.385。with_cap
    必须配 lambda0_m（帽厚是频率量纲，缺 → ValueError fail-fast）；
    cap_n 缺省用 :func:`cap_index_optimal`。aperture 登记面在 lambda0_m
    存在时输出面积+可选增益（aperture_efficiency 给定时）。"""
    r = _positive(radius_m, "radius_m")
    n_ = _index(n, "n")
    lam = None if lambda0_m is None else _positive(lambda0_m, "lambda0_m")
    if with_cap and lam is None:
        raise ValueError("with_cap 需要配 lambda0_m（λ/4 帽厚为频率量纲）")
    if lr is not None:
        lr_ = _lr(lr, "lr")
    elif feed_regime == FEED_APLANATIC:
        lr_ = aplanatic_lr(n_)
    elif feed_regime == FEED_SINGLE_UNIT:
        lr_ = 0.5 * (LR_SINGLE_UNIT_BAND[0] + LR_SINGLE_UNIT_BAND[1])
    elif feed_regime == FEED_PEAK_DIRECTIVITY:
        lr_ = 0.5 * (LR_PEAK_DIRECTIVITY_BAND[0] + LR_PEAK_DIRECTIVITY_BAND[1])
    else:
        raise ValueError(f"未知 feed_regime：{feed_regime}")
    cap: dict | None = None
    if with_cap and lam is not None:
        nc = cap_index_optimal(n_) if cap_n is None else _positive(cap_n, "cap_n")
        t = cap_thickness(lam, nc)
        cap = {
            "n_cap": nc,
            "thickness_m": t,
            "r_inner_m": r,
            "r_outer_m": r + t,
            "index_is_optimal": nc == cap_index_optimal(n_),
        }
    aperture = (
        None
        if lam is None
        else aperture_registration(r, lam, aperture_efficiency)
    )
    return LensDesign(
        radius_m=r,
        n=n_,
        lr=lr_,
        feed_regime=feed_regime,
        extension_m=lr_ * r,
        aplanatic_lr=aplanatic_lr(n_),
        paraxial_collimation_lr=paraxial_collimation_lr(n_),
        critical_angle_deg=critical_angle_deg(n_),
        cap=cap,
        aperture=aperture,
        lambda0_m=lam,
        source=_SOURCE_NOTE,
    )
