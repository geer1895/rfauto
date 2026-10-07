"""AP-1 极化指标包（round17 §三 AP-1，P1/S；2026-10-03）。

轴比/倾角/旋向/圆极化判别 + Ludwig-3 co/cross + XPD + 极化失配 PLF，
全部**纯函数零 IO**、numpy/math 依赖、返回 JSON 可序列化值（inf 场景
显式文档化）。零求解器依赖。

出处与口径：
- 极化椭圆参数：Balanis《Antenna Theory: Analysis and Design》4th ed
  §4.4（极化椭圆：轴比 AR、倾角 τ、旋向）。两正交复分量 E1=Eθ、
  E2=Eφ、相位差 δ=phase(Eφ)−phase(Eθ)：

      AR = √[(S+√D)/(S−√D)]，S=E1²+E2²，
      D = E1⁴+E2⁴+2·E1²·E2²·cos(2δ)
      τ = ½·atan2(2·E1·E2·cos δ, E1²−E2²)

  线极化（δ=0 或 π）时分母→0，AR→∞：本实现按 AR_LINEAR_DB_CAP
  封顶（100 dB，量纲上等价"发散"），docstring 与返回值显式标注。
- 旋向（易错点，显式钉）：IEEE Std 145-1983——沿**传播方向**看顺时针
  =右旋（RH）。对 (θ̂,φ̂,r̂) 右手系（θ̂×φ̂=r̂）端口分量，RHCP ⟺
  δ=−90°（Eφ 滞后 Eθ），与 Balanis +z 行波 RHCP 相量 (x̂−jŷ) 同构
  （−j=滞后 90°）；等价判据 Im(Eθ*·Eφ)=E1·E2·sin δ<0 → RH。
  光学镜像观察（对着来波看）习惯相反，不在本口径。
- Ludwig-3 co/cross：A.C. Ludwig, "The Definition of Cross Polarization"，
  IEEE TAP 21(1):116-119, 1973 第三定义（x 线极化参考）：

      E_co(θ,φ)    = Eθ·cos φ + Eφ·sin φ
      E_cross(θ,φ) = −Eθ·sin φ + Eφ·cos φ

  主平面性质（测试锚）：φ=0 面上 co=Eθ、cross=Eφ；φ=90° 面上
  co=Eφ、cross=−Eθ。Huygens 源（x 电偶极+y 磁偶极，Eθ∝(1+cosθ)cosφ/2、
  Eφ∝(1+cosθ)sinφ/2）在该定义下 cross≡0、co=(1+cosθ)/2 与 φ 无关
  （Balanis §4.7 Huygens 源经典性质）——该性质同时反证符号约定取正号。
- XPD：交叉极化鉴别度 XPD=20·log10(|co|/|cross|)（=10·log10 功率比）。
  纯 θ 极化场在 φ=0 面上 cross=0 → XPD 发散：按 math.inf 返回（调用方
  自行封顶；round17 验收锚"线极化 XPD→∞"）。
- PLF（极化失配因子）：Balanis §4.4.3 PLF=|ê_r·ê_t|²（ê 为单位极化
  复矢量，同横截面基）。经典锚：线-线对齐 1、正交 0、圆-圆同旋向 1/
  反旋向 0、圆-线 1/2（−3.01 dB）。

第三方法互证（#118/#300：禁自我推导自证）：AR 闭式另配时域椭圆数值法
（E(t)=Re[E1·e^{jωt}]θ̂+Re[E2·e^{jωt+δ}]φ̂ 单周期采样取 |E| max/min），
两路径在测试中互检——闭式与数值法独立实现，偏差门预声明
tests/unit/test_polarization.py。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: 线极化时 AR→∞ 的 dB 封顶（100 dB=1e5 线性，量纲上"发散"且 JSON 安全）。
AR_LINEAR_DB_CAP = 100.0

#: 旋向码：+1=右旋（RH）、−1=左旋（LH）、0=线极化（无旋向）。
SENSE_RH = 1
SENSE_LH = -1
SENSE_LINEAR = 0

#: 幅度地板：两分量皆零时 AR/XPD 无定义，按该地板避免 log10(0)。
_AMPLITUDE_FLOOR = 1e-300

#: 时域椭圆第三方法的单周期采样点数（数值积分精度 ~1e-10）。
_TIME_SAMPLES = 4096


def _num(value: Any, name: str) -> float:
    """有限数校验（bool 显式拒收——df7+⑯；0.0 合法性由各函数域守卫定）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _cplx(value: Any, name: str) -> complex:
    """复数收敛（接受 complex/数值/长度 2 序列）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为复数（不接受 bool）")
    try:
        out = complex(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为可转复数的标量，收到 {value!r}") from exc
    if not (math.isfinite(out.real) and math.isfinite(out.imag)):
        raise ValueError(f"{name} 必须为有限复数")
    return out


def axial_ratio(
    e1_abs: float, e2_abs: float, delta_rad: float
) -> float:
    """轴比 AR（线性倍数）——Balanis 4th §4.4 闭式。

    AR = √[(S+√D)/(S−√D)]，S=E1²+E2²，D=E1⁴+E2⁴+2·E1²·E2²·cos(2δ)。
    纯圆极化（E1=E2 且 δ=±90°）→ 1；线极化（δ∈{0,π} 或某分量为 0）
    → 封顶 10^(AR_LINEAR_DB_CAP/20)（docstring：真值发散）。
    等幅 δ=45° 特例解析锚：AR=√(2+√2)−路=1+√2=2.41421（=cot 22.5°，
    测试用 cot(δ/2) 恒等式独立互证）。
    """
    m1 = _num(e1_abs, "e1_abs")
    m2 = _num(e2_abs, "e2_abs")
    if m1 < 0.0 or m2 < 0.0:
        raise ValueError(f"幅度必须 ≥0，得 {m1}, {m2}")
    d = _num(delta_rad, "delta_rad")
    if m1 + m2 <= 0.0:
        raise ValueError("两分量幅度全零：极化无定义")
    s = m1 * m1 + m2 * m2
    disc = math.sqrt(
        m1**4 + m2**4 + 2.0 * m1 * m1 * m2 * m2 * math.cos(2.0 * d)
    )
    denom = s - disc
    if denom <= s * 1e-15:
        # 线极化极限（分母→0）：按封顶返回，真值发散
        return 10.0 ** (AR_LINEAR_DB_CAP / 20.0)
    return math.sqrt((s + disc) / denom)


def axial_ratio_db(e1_abs: float, e2_abs: float, delta_rad: float) -> float:
    """轴比 [dB] = 20·log10(AR)。圆极化锚 0 dB（round17 AP-1 验收锚）。"""
    return 20.0 * math.log10(axial_ratio(e1_abs, e2_abs, delta_rad))


def axial_ratio_time_domain(
    e1_abs: float, e2_abs: float, delta_rad: float,
    n_samples: int = _TIME_SAMPLES,
) -> float:
    """轴比第三方法：时域极化椭圆数值法（与闭式独立实现）。

    E(t)=E1·cos(ωt)·θ̂+E2·cos(ωt+δ)·φ̂，单周期均匀采样取 |E| 的
    max/min（椭圆长/短轴）。与闭式共享零解析推导（#118 禁自证）。
    线极化 min→0：按 AR_LINEAR_DB_CAP 封顶同 axial_ratio。
    """
    m1 = _num(e1_abs, "e1_abs")
    m2 = _num(e2_abs, "e2_abs")
    d = _num(delta_rad, "delta_rad")
    if m1 < 0.0 or m2 < 0.0:
        raise ValueError(f"幅度必须 ≥0，得 {m1}, {m2}")
    if m1 + m2 <= 0.0:
        raise ValueError("两分量幅度全零：极化无定义")
    t = np.linspace(0.0, 2.0 * math.pi, int(n_samples), endpoint=False)
    ex = m1 * np.cos(t)
    ey = m2 * np.cos(t + d)
    mag = np.sqrt(ex * ex + ey * ey)
    mn = float(mag.min())
    mx = float(mag.max())
    if mn <= mx * 1e-12:
        return 10.0 ** (AR_LINEAR_DB_CAP / 20.0)
    return mx / mn


def tilt_angle_deg(e1_abs: float, e2_abs: float, delta_rad: float) -> float:
    """极化椭圆倾角 τ [deg]——τ=½·atan2(2·E1·E2·cos δ, E1²−E2²)。

    Balanis 4th §4.4。锚：E2=0 → τ=0（沿 θ̂）；等幅 δ=±90° →
    atan2(0,0)=0（轴方向约定）。
    """
    m1 = _num(e1_abs, "e1_abs")
    m2 = _num(e2_abs, "e2_abs")
    d = _num(delta_rad, "delta_rad")
    return 0.5 * math.degrees(
        math.atan2(2.0 * m1 * m2 * math.cos(d), m1 * m1 - m2 * m2)
    )


def sense_code(e_theta: Any, e_phi: Any, tol: float = 1e-12) -> int:
    """旋向码（SENSE_RH/LH/LINEAR）——IEEE Std 145-1983 口径。

    判据 Im(Eθ*·Eφ)<0 → RH（δ=−90° 主锚，Balanis (x̂−jŷ) 同构）；
    |sin δ|≤tol（含单分量为零）→ 线极化 0。
    """
    a = _cplx(e_theta, "e_theta")
    b = _cplx(e_phi, "e_phi")
    if abs(a) <= tol or abs(b) <= tol:
        return SENSE_LINEAR
    imag_cross = (a.conjugate() * b).imag
    if abs(imag_cross) <= tol * abs(a) * abs(b):
        return SENSE_LINEAR
    return SENSE_RH if imag_cross < 0.0 else SENSE_LH


def polarization_state(e_theta: Any, e_phi: Any) -> dict[str, Any]:
    """单方向完整极化态（farfield3d_cplx 单角点消费口径）。

    返回 dict：e_theta_abs / e_phi_abs / delta_deg（phase(Eφ)−phase(Eθ)）/
    ar_linear / ar_db / tilt_deg / sense_code / sense（"RH"/"LH"/"linear"）。
    """
    a = _cplx(e_theta, "e_theta")
    b = _cplx(e_phi, "e_phi")
    if abs(a) + abs(b) <= 0.0:
        raise ValueError("两分量全零：极化无定义")
    m1, m2 = abs(a), abs(b)
    delta = math.atan2(b.imag, b.real) - math.atan2(a.imag, a.real)
    ar = axial_ratio(m1, m2, delta)
    code = sense_code(a, b)
    return {
        "e_theta_abs": m1,
        "e_phi_abs": m2,
        "delta_deg": math.degrees(delta),
        "ar_linear": ar,
        "ar_db": 20.0 * math.log10(ar),
        "tilt_deg": tilt_angle_deg(m1, m2, delta),
        "sense_code": code,
        "sense": {SENSE_RH: "RH", SENSE_LH: "LH", SENSE_LINEAR: "linear"}[code],
    }


def classify_cp(
    ar_db: float, circular_max_db: float = 3.0, linear_min_db: float = 20.0
) -> str:
    """圆极化判别（round17 AP-1"圆极化判别"）：AR dB 三段分类。

    ar_db ≤ circular_max_db → "circular"（工程惯例 ≤3 dB 视作圆极化）；
    ar_db ≥ linear_min_db → "linear"；其余 "elliptical"。门值显式入参，
    缺省 3/20 dB 为惯例口径（非标准强约束，docstring 如实）。
    """
    x = _num(ar_db, "ar_db")
    if x < 0.0:
        raise ValueError(f"ar_db 必须 ≥0（AR≥1），得 {x}")
    if circular_max_db <= 0.0 or linear_min_db <= circular_max_db:
        raise ValueError("须 0 < circular_max_db < linear_min_db")
    if x <= circular_max_db:
        return "circular"
    if x >= linear_min_db:
        return "linear"
    return "elliptical"


def ludwig3_components(e_theta: Any, e_phi: Any, phi_deg: Any) -> tuple[Any, Any]:
    """Ludwig-3 第三定义 co/cross（x 线极化参考；Ludwig 1973）。

    E_co = Eθ·cosφ + Eφ·sinφ；E_cross = −Eθ·sinφ + Eφ·cosφ。
    标量复数或同形 numpy 网格皆可（向量化）。主平面归约：
    φ=0 → (co,cross)=(Eθ,Eφ)；φ=90° → (Eφ,−Eθ)。
    """
    et = np.asarray(e_theta)
    ep = np.asarray(e_phi)
    if et.shape != ep.shape:
        raise ValueError(f"e_theta/e_phi 形状不符：{et.shape} vs {ep.shape}")
    ph = np.asarray(phi_deg, dtype=float) * math.pi / 180.0
    co = et * np.cos(ph) + ep * np.sin(ph)
    cross = -et * np.sin(ph) + ep * np.cos(ph)
    return co, cross


def xpd_db(co: Any, cross: Any, divergence_cap_db: float = 300.0) -> Any:
    """交叉极化鉴别度 XPD [dB] = 20·log10(|co|/|cross|)。

    cross=0（纯线极化锚）按真值发散口径返回 divergence_cap_db
    （缺省 300 dB；round17 验收锚"线极化 XPD→∞"的有限封顶实现，
    cap 值显式入参便于消费方改为 inf）。标量或 numpy 网格。
    """
    c = np.asarray(co)
    x = np.asarray(cross)
    if c.shape != x.shape:
        raise ValueError(f"co/cross 形状不符：{c.shape} vs {x.shape}")
    # cap 允许 inf（=真值发散直通），仅拒 nan/负值/bool——不用 _num
    if isinstance(divergence_cap_db, bool):
        raise ValueError("divergence_cap_db 不接受 bool")
    cap = float(divergence_cap_db)
    if math.isnan(cap) or cap < 0.0:
        raise ValueError(f"divergence_cap_db 须 ≥0（可取 inf=不封顶），得 {cap}")
    denom = np.maximum(np.abs(x), 10.0 ** (-cap / 20.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 20.0 * np.log10(np.maximum(np.abs(c), _AMPLITUDE_FLOOR) / denom)
    # cap=inf 时 denom=0 → 逐定义发散为 inf（#284：警告就地消化不外漏）
    return float(out) if out.ndim == 0 else out


def polarization_loss_factor(
    e1_rx: Any, e2_rx: Any, delta_rx: Any,
    e1_tx: Any, e2_tx: Any, delta_tx: Any,
) -> float:
    """PLF（极化失配因子）=|ê_rx·ê_tx|²——Balanis §4.4.3。

    ê=(E1·θ̂+E2·e^{jδ}·φ̂)/|·|（同横截面基、收发极化态各给
    (E1,E2,δ)）。经典锚：对齐线 1 / 正交线 0 / 同向圆 1 / 反向圆 0 /
    圆×线 0.5（−3.0103 dB）。
    """
    m1r = _num(e1_rx, "e1_rx")
    m2r = _num(e2_rx, "e2_rx")
    m1t = _num(e1_tx, "e1_tx")
    m2t = _num(e2_tx, "e2_tx")
    dr = _num(delta_rx, "delta_rx")
    dt = _num(delta_tx, "delta_tx")
    for name, (a, b) in (("rx", (m1r, m2r)), ("tx", (m1t, m2t))):
        if a < 0.0 or b < 0.0 or a + b <= 0.0:
            raise ValueError(f"{name} 极化态幅度非法（须 ≥0 且不全零）")
    # ê_r·ê_t = m1r·m1t + m2r·m2t·e^{j(δr−δt)}（无共轭——圆-圆反旋向锚
    # 须得 0，共轭或错相会算成 1，测试钉）
    dot = m1r * m1t + m2r * m2t * np.exp(1j * (dr - dt))
    plf = abs(dot) ** 2 / ((m1r**2 + m2r**2) * (m1t**2 + m2t**2))
    return float(min(plf, 1.0))


def polarization_grids(e_theta: Any, e_phi: Any) -> dict[str, Any]:
    """网格批量极化态（farfield3d_cplx (n_theta,n_phi) 复网格消费口径）。

    返回 dict：ar_db / tilt_deg / sense_code 三个同形网格
    （sense_code：+1 RH / −1 LH / 0 linear；NaN/无效幅度入 →
    ar_db/tilt_deg 出 NaN，sense_code 不保证——消费方以 ar_db NaN
    为无效标记）。
    """
    et = np.asarray(e_theta)
    ep = np.asarray(e_phi)
    if et.shape != ep.shape:
        raise ValueError(f"网格形状不符：{et.shape} vs {ep.shape}")
    m1 = np.abs(et)
    m2 = np.abs(ep)
    delta = np.angle(ep) - np.angle(et)
    s = m1 * m1 + m2 * m2
    disc = np.sqrt(
        m1**4 + m2**4 + 2.0 * m1 * m1 * m2 * m2 * np.cos(2.0 * delta)
    )
    denom = s - disc
    # 线极化判据：分母→0（disc→s），不是圆极化侧（disc→0）——
    # 判据方向写反会把 CP 全封顶（首跑实测抓出）
    denom = np.where(denom <= s * 1e-15, np.nan, denom)
    with np.errstate(invalid="ignore", divide="ignore"):
        ar = np.sqrt((s + disc) / denom)
    ar = np.where(np.isfinite(ar), ar, 10.0 ** (AR_LINEAR_DB_CAP / 20.0))
    ar_db = 20.0 * np.log10(ar)
    tilt = 0.5 * np.degrees(
        np.arctan2(2.0 * m1 * m2 * np.cos(delta), m1 * m1 - m2 * m2)
    )
    imag_cross = (np.conjugate(et) * ep).imag
    tiny = 1e-12 * np.maximum(m1 * m2, 1e-300)
    sense = np.where(m1 * m2 <= 0.0, 0,
                     np.where(np.abs(imag_cross) <= tiny, 0,
                              np.where(imag_cross < 0.0, SENSE_RH, SENSE_LH)))
    return {"ar_db": ar_db, "tilt_deg": tilt, "sense_code": sense}
