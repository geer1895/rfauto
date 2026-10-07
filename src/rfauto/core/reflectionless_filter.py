"""TF-2 无反射（reflectionless / absorptive）滤波器闭式族内核：LPF 先行 + HPF 对偶变换。

法源（铁律 5：来源写 docstring；裁判=独立来源不自证，#118；学术诚信优先于
验收表全勾，#122）：

- 谱系勘误（round5 已核正登记）：本族权威谱系为 **Morgan-Boyd**，原任务
  提示 "Guypc/Chryssomallis" 系误记。可达来源：
  (a) M. A. Morgan, T. A. Boyd, "Theoretical and Experimental Study of a New
      Class of Reflectionless Filter," IEEE TMTT 59(5), 2011 —— 概念源；其
      修正原型表在 IEEE 付费墙内，本仓**不誊录**（UNVERIFIED，如实登记）；
  (b) M. A. Morgan, T. A. Boyd, "Reflectionless Filter Structures," IEEE
      TMTT 63(4), 2015 —— 本内核实现的**对称拓扑**出处。论文正文付费墙，
      拓扑与元件约束式经公开二手可核源转录：UAB 学位论文 D. Ulinic
      (2018) "Advanced Filter Response Based On Reflectionless Concept"
      (ddd.uab.cat/pub/tfg/2018/195048/TFG_danielulinic.pdf, pp.16-19)
      转录 [Mor15] 式 (4.5)/(4.6)：C1 = La1/(2Z0²)、Lb2 = Z0²·C1、
      Cn2 = 2·Lb2/Z0²、R = Z0（链内递推 Lb,k = C(k-1)、Ck = Lb,k），
      并附 ADS 电路图（第 5 阶实例，g1 = 1.7058 即 0.5 dB/N=5 Chebyshev
      表值，与 MYJ 表逐位一致，tests 钉）；
  (c) M. A. Morgan, W. M. Groves, T. A. Boyd, arXiv:1807.00021 (2018) ——
      任意梯形原型推广拓扑（负元件经变压器等效消除）；其 Table I 为
      Legendre-Papoulis 表（可达，但非 Chebyshev 族，本内核不消费）；
  (d) A. Guilabert, M. Morgan, T. Boyd, arXiv:1904.03718 (2019) —— 广义
      传输零点推广（lattice/coupled-ladder，原型表引 Saal Telefunken）。
- Chebyshev 原型 g 值：MYJ 1964 §4.05 递式（与 core/lc_filter 同源同式，
  tests 以文献 4 位表 + lc_filter.cauer_ladder_gk 交叉钉）。

架构（2026-09-27 离线原型实证，runs/_tf2_*.py 数值证据）：

- **拓扑**（对称二端口，镜像面竖直过桥元件与底部吸收元件）：桥
  （port1—port2 跨接串联元件）＋左右对称链（每半边 P 组"串 C＋并 L"后经
  串 R = Z0 到镜像节点）＋镜像节点对地并 C_end。全部电抗元件归一化值
  相等 v = 1/(2·g1)，桥 = 2v，C_end = 2v——即 [Mor15] 约束式 (4.5)/(4.6)
  的等值链解。
- **恒阻机理（对偶恒等式，主判据）**：偶模半电路（镜像面开路：桥失效、
  平面元件折半留半端）输入阻抗 z_e 与奇模半电路（镜像面虚地：桥折半并
  端口、平面元件两端短路失效）输入阻抗 z_o 满足 **z_e·z_o = Z0²（逐频
  恒等）**，实测 ≤1e-15（Z0=1，8 个十倍程网格）。由对称网络 S 参数分解
  S11 = ½(Γe+Γo)、S21 = ½(Γe−Γo) 得 S11 ≡ 0、S21 = Γe（低通）；全频
  max|S11| 实测 ≤1e-13（任务判据 ≤1e-9，余量 4 个量级）。
- **等值链唯一性（口径钉死）**：一般链（逐位自由值）在对偶恒等式约束下
  的解空间经多起点最小二乘探测（24 起点，13 个收敛解全部为等值链），本
  拓扑**只消费 g1**（基值）＋链长参数 P = n_pairs（对应奇数阶 N = 2P+1，
  ADS 第 5 阶实例即 P=2）；任意 g 表逐位进链需 2018 推广拓扑（负元件/
  变压器等效，见 (c)/(d)）——本内核**如实受限不做**，不做不实声称。
- **滚降（如实登记，#122）**：远阻带渐近斜率实测 **−20 dB/dec（与 P 无
  关**，端口单个串 C 主导）；阶数作用 = 过渡带肩部变陡（[3,30]·ωc 局部
  斜率 P=1/2/3/4 = −3.0/−9.5/−17.0/−17.3 dB/dec，实测钉）。任务书
  "-40dB/dec×N 量级"口径按实测修正登记，不凑勾。
- **HPF 对偶变换**：LP→HP 标准映射（L↔C、值取倒数，R 不变），恒阻恒等
  式严格保持（实测 ≤5e-13），高频直通、DC 阻断。

纯函数零 IO（numpy/math）；数值只在确定性内核（铁律 7）；数值 0.0 合法，
判缺失一律 is not None（#364④）；bool 显式拒收（df7+⑯）。单位钉在字段名
（H/F/Ω/Hz）。元件值输出含逐件 role/side/index 标注（元件值表交付面）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

__all__ = [
    "KIND_HPF",
    "KIND_LPF",
    "ReflectionlessElement",
    "ReflectionlessNetwork",
    "ReflectionlessSpec",
    "chebyshev_g_table",
    "duality_residual",
    "make_network",
    "make_spec",
    "network_sparams",
    "network_sparams_by_modes",
]

KIND_LPF = "lpf"
KIND_HPF = "hpf"
_KINDS = (KIND_LPF, KIND_HPF)


def _finite(value: float, name: str) -> float:
    """入参收敛为有限 float（bool 显式拒收，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（float(True)=1.0 静默污染统计）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} 必须 >0，实际 {out}")
    return out


def _order(value: int, name: str) -> int:
    """阶数/对数收敛：int 且 >=1（bool 拒收）。"""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} 必须为 int，实际 {type(value).__name__}")
    out = int(value)
    if out < 1:
        raise ValueError(f"{name} 必须 >=1，实际 {out}")
    return out


# ─── 1. Chebyshev 原型 g 值表（MYJ 递式，含偶阶不等终接）─────────────────────


def chebyshev_g_table(order: int, ripple_db: float) -> tuple[list[float], float]:
    """Chebyshev 低通原型 g 值（g0=1 归一化，ωc=1）。

    返回 (g1..gN, g_load)。递式（MYJ 1964 §4.05，与 core/lc_filter 同源）：
    β = ln coth(δdB/17.372)、γ = sinh(β/2N)、g1 = 2A1/γ、
    gk = 4A(k-1)Ak/(B(k-1)·g(k-1))；奇阶 g_load = 1；**偶阶
    g_load = coth²(β/4) ≠ 1**（不等终接——常规等端接 Cauer I 不可实现的
    口径）。表值回收判据（tests）：文献 4 位表 rel ≤2.5e-4（0.1/0.5 dB
    N=3/5/7）；奇阶与 lc_filter.cauer_ladder_gk 交叉一致 ≤1e-9。
    """
    n = _order(order, "order")
    ripple = _positive(ripple_db, "ripple_db")
    x = ripple / (40.0 / math.log(10.0))  # 17.372 = 40/ln10（文献 17.37 舍入）
    beta = math.log(1.0 / math.tanh(x))
    gamma = math.sinh(beta / (2.0 * n))

    def _a(k: int) -> float:
        return math.sin((2 * k - 1) * math.pi / (2.0 * n))

    def _b(k: int) -> float:
        return gamma**2 + math.sin(k * math.pi / n) ** 2

    g = [2.0 * _a(1) / gamma]
    for k in range(2, n + 1):
        g.append(4.0 * _a(k - 1) * _a(k) / (_b(k - 1) * g[k - 2]))
    g_load = 1.0 if n % 2 == 1 else (1.0 / math.tanh(beta / 4.0)) ** 2
    return g, float(g_load)


# ─── 2. 网络综合（g1 → 元件值表）─────────────────────────────────────────────


@dataclass(frozen=True)
class ReflectionlessSpec:
    """无反射滤波器规格。

    n_pairs：每半边"串 C＋并 L"对数 P（>=1；对应奇数阶 N=2P+1 的 g1 取值）。
    ripple_db：Chebyshev 通带纹波（>0），经 g1 决定基值 v = 1/(2·g1)。
    z0_ohm：端口/吸收电阻（>0）。
    fc_hz：去归一化截止频率标尺（>0）；None = 归一化（ωc = 1 rad/s，
    判缺失 is not None，#364④）。
    kind："lpf"（缺省）或 "hpf"（LP→HP 对偶变换）。
    """

    n_pairs: int
    ripple_db: float
    z0_ohm: float = 1.0
    fc_hz: float | None = None
    kind: str = KIND_LPF

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_pairs": int(self.n_pairs),
            "ripple_db": self.ripple_db,
            "z0_ohm": self.z0_ohm,
            "fc_hz": self.fc_hz,
            "kind": self.kind,
        }


def make_spec(
    n_pairs: int,
    ripple_db: float,
    z0_ohm: float = 1.0,
    fc_hz: float | None = None,
    kind: str = KIND_LPF,
) -> ReflectionlessSpec:
    """构造并校验规格（判据 #122 先行：非法入参显式 ValueError）。"""
    if kind not in _KINDS:
        raise ValueError(f"kind 必须是 {list(_KINDS)} 之一，实际 {kind!r}")
    p = _order(n_pairs, "n_pairs")
    ripple = _positive(ripple_db, "ripple_db")
    z0 = _positive(z0_ohm, "z0_ohm")
    fc: float | None = None if fc_hz is None else _positive(fc_hz, "fc_hz")
    return ReflectionlessSpec(n_pairs=p, ripple_db=ripple, z0_ohm=z0, fc_hz=fc, kind=kind)


@dataclass(frozen=True)
class ReflectionlessElement:
    """单个元件（元件值表交付面）。

    role：bridge_series_L / bridge_series_C / chain_series_C / chain_shunt_L /
    chain_series_L / chain_shunt_C / chain_series_R / plane_shunt_C /
    plane_shunt_L。side：left / right / common。value 单位由 role 定
    （H/F/Ω）。index：链内对序号（1-based）；非链元件 None（判缺失
    is not None）。
    """

    role: str
    side: str
    value: float
    index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "side": self.side,
            "value": self.value,
            "index": self.index,
        }


@dataclass
class ReflectionlessNetwork:
    """综合结果：规格＋原型表＋去归一化元件值（结构化＋逐件展平）。

    omega_c_rad_s：归一化角频率（fc_hz=None 时为 1.0）。
    v_norm = 1/(2·g1)；链内全部对归一化值 = v_norm；桥 = 2·v_norm；
    平面元件 = 2·v_norm（[Mor15] 约束式 Cn2 = 2·Lb2）。
    chain_pairs：扁平序列 [(kind, value) × 2P]，自端口向镜像面为
    [串, 并] × P；HPF 时串 L/并 C。
    """

    spec: ReflectionlessSpec
    g_table: list[float]
    g_load: float
    v_norm: float
    omega_c_rad_s: float
    bridge_l_h: float | None  # LPF：桥串 L（H）；HPF 为 None
    bridge_c_f: float | None  # HPF：桥串 C（F）；LPF 为 None
    chain_pairs: list[tuple[str, float]]
    r_absorber_ohm: float
    plane_c_f: float | None  # LPF：镜像节点对地 C（F）；HPF 为 None
    plane_l_h: float | None  # HPF：镜像节点对地 L（H）；LPF 为 None
    elements: list[ReflectionlessElement] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": self.spec.to_dict(),
            "g_table": [float(g) for g in self.g_table],
            "g_load": float(self.g_load),
            "v_norm": float(self.v_norm),
            "omega_c_rad_s": float(self.omega_c_rad_s),
            "bridge_l_h": self.bridge_l_h,
            "bridge_c_f": self.bridge_c_f,
            "chain_pairs": [[k, float(v)] for k, v in self.chain_pairs],
            "r_absorber_ohm": float(self.r_absorber_ohm),
            "plane_c_f": self.plane_c_f,
            "plane_l_h": self.plane_l_h,
            "elements": [el.to_dict() for el in self.elements],
            "sources": dict(self.sources),
        }


def make_network(spec: ReflectionlessSpec) -> ReflectionlessNetwork:
    """规格 → 无反射网络元件值表。

    判据（#122 先行）：spec 非 ReflectionlessSpec / kind 未注册 /
    n_pairs<1 / ripple<=0 / z0<=0 / fc<=0（非 None 时）→ ValueError。
    元件值按 [Mor15] 约束式生成（等值链族，口径见模块 docstring）；
    去归一化 L·Z0/ωc、C/(Z0·ωc)，R = Z0。
    """
    if not isinstance(spec, ReflectionlessSpec):
        raise ValueError("spec 必须是 ReflectionlessSpec")
    order = 2 * int(spec.n_pairs) + 1  # 奇数阶口径（ADS 第 5 阶实例 ↔ P=2）
    g_table, g_load = chebyshev_g_table(order, spec.ripple_db)
    g1 = float(g_table[0])
    v_norm = 1.0 / (2.0 * g1)
    omega_c = 1.0 if spec.fc_hz is None else 2.0 * math.pi * float(spec.fc_hz)
    z0 = float(spec.z0_ohm)
    scale_l = z0 / omega_c
    scale_c = 1.0 / (z0 * omega_c)
    n_pairs = int(spec.n_pairs)

    elements: list[ReflectionlessElement] = []
    if spec.kind == KIND_LPF:
        bridge_l = 2.0 * v_norm * scale_l
        chain: list[tuple[str, float]] = []
        for _ in range(n_pairs):
            chain.append(("C", v_norm * scale_c))
            chain.append(("L", v_norm * scale_l))
        plane_c = 2.0 * v_norm * scale_c
        net = ReflectionlessNetwork(
            spec=spec,
            g_table=[float(g) for g in g_table],
            g_load=float(g_load),
            v_norm=float(v_norm),
            omega_c_rad_s=float(omega_c),
            bridge_l_h=float(bridge_l),
            bridge_c_f=None,
            chain_pairs=chain,
            r_absorber_ohm=z0,
            plane_c_f=float(plane_c),
            plane_l_h=None,
        )
        elements.append(ReflectionlessElement("bridge_series_L", "common", float(bridge_l)))
        for side in ("left", "right"):
            for i in range(n_pairs):
                elements.append(
                    ReflectionlessElement("chain_series_C", side, v_norm * scale_c, i + 1)
                )
                elements.append(
                    ReflectionlessElement("chain_shunt_L", side, v_norm * scale_l, i + 1)
                )
            elements.append(ReflectionlessElement("chain_series_R", side, z0, n_pairs + 1))
        elements.append(ReflectionlessElement("plane_shunt_C", "common", float(plane_c)))
    else:
        bridge_c = (1.0 / (2.0 * v_norm)) * scale_c
        chain = []
        for _ in range(n_pairs):
            chain.append(("L", (1.0 / v_norm) * scale_l))
            chain.append(("C", (1.0 / v_norm) * scale_c))
        plane_l = (1.0 / (2.0 * v_norm)) * scale_l
        net = ReflectionlessNetwork(
            spec=spec,
            g_table=[float(g) for g in g_table],
            g_load=float(g_load),
            v_norm=float(v_norm),
            omega_c_rad_s=float(omega_c),
            bridge_l_h=None,
            bridge_c_f=float(bridge_c),
            chain_pairs=chain,
            r_absorber_ohm=z0,
            plane_c_f=None,
            plane_l_h=float(plane_l),
        )
        elements.append(ReflectionlessElement("bridge_series_C", "common", float(bridge_c)))
        for side in ("left", "right"):
            for i in range(n_pairs):
                elements.append(
                    ReflectionlessElement(
                        "chain_series_L", side, (1.0 / v_norm) * scale_l, i + 1
                    )
                )
                elements.append(
                    ReflectionlessElement(
                        "chain_shunt_C", side, (1.0 / v_norm) * scale_c, i + 1
                    )
                )
            elements.append(ReflectionlessElement("chain_series_R", side, z0, n_pairs + 1))
        elements.append(ReflectionlessElement("plane_shunt_L", "common", float(plane_l)))
    net.elements = elements
    net.sources = {
        "topology": (
            "Morgan & Boyd 2015 (IEEE TMTT 63(4)) symmetric reflectionless "
            "topology; constraints (4.5)/(4.6) transcribed from UAB thesis "
            "(D. Ulinic 2018, ddd.uab.cat, pp.16-19) with ADS schematic"
        ),
        "concept": (
            "Morgan & Boyd 2011 (IEEE TMTT 59(5)); its prototype tables are "
            "paywalled - NOT transcribed (UNVERIFIED)"
        ),
        "lineage_correction": (
            "task hint 'Guypc/Chryssomallis' is a mis-citation; authoritative "
            "lineage is Morgan-Boyd 2011/2015 (round5 correction on record)"
        ),
        "extensions": (
            "arXiv:1807.00021 (2018, arbitrary-prototype topology); "
            "arXiv:1904.03718 (2019, generalized transmission zeros)"
        ),
        "prototype": "Chebyshev g-values via MYJ 1964 par 4.05 recurrence "
        "(same source as core/lc_filter)",
        "scoping": (
            "equal-chain canonical family only (g1 enters; duality solution "
            "manifold probed 2026-09-27: 24 least-squares starts, all "
            "convergent solutions equal-valued); arbitrary g-tables need the "
            "2018 generalized topology - honestly out of scope"
        ),
    }
    return net


# ─── 3. 频响面：偶/奇半电路（ABCD 级联连分数口径）＋ MNA 全网表 ─────────────


def _element_z(kind: str, value: float, s: complex) -> complex:
    """元件阻抗：L → sL；C → 1/(sC)。"""
    if kind == "L":
        return s * value
    return 1.0 / (s * value)


def _parallel(z1: complex, z2: complex) -> complex:
    return (z1 * z2) / (z1 + z2)


def _chain_series_list(net: ReflectionlessNetwork) -> list[tuple[str, float]]:
    """链内序列：扁平 [(串, 值), (并, 值)] × P（自端口向镜像面）。"""
    return list(net.chain_pairs)


def _half_z(net: ReflectionlessNetwork, s: complex, even: bool) -> complex:
    """半电路输入阻抗（Ω，含桥/平面元件的模态折算）。

    偶模：桥失效（不进半电路）；链折叠端接 R＋平面元件**阻抗加倍**
    （并联元件折算规则：偶模导纳折半 ⇒ 阻抗 ×2，与元件类型无关）。
    奇模：平面元件短路失效；链折叠端接 R；桥**阻抗折半**（串联跨越
    元件折算规则：奇模中点虚地 ⇒ 每半 Z/2，与元件类型无关）由调用方
    并接。LPF 数值核对：桥 L/2、平面 C/2（1/(s·C/2) = 2/(sC)）＝
    [Mor15] 约束式；HPF 同一规则（桥 C 阻抗折半、平面 L 阻抗加倍）。
    链序列自端口向镜像面为 [串, 并] × P：折叠自镜像端起，并元件取
    阻抗并联、串元件累加。
    """
    seq = _chain_series_list(net)
    z_plane = (
        _element_z("C", net.plane_c_f, s)
        if net.plane_c_f is not None
        else _element_z("L", net.plane_l_h, s)
    )
    z_end = net.r_absorber_ohm + 2.0 * z_plane if even else net.r_absorber_ohm + 0j
    z = z_end
    for idx in range(len(seq) - 1, -1, -1):
        kind_i, val_i = seq[idx]
        z_i = _element_z(kind_i, val_i, s)
        z = z_i + z if idx % 2 == 0 else _parallel(z_i, z)  # 偶位串 / 奇位并
    return z


def _bridge_half_z(net: ReflectionlessNetwork, s: complex) -> complex:
    """桥元件奇模折半阻抗（阻抗折半，与元件类型无关）。"""
    if net.bridge_l_h is not None:
        return _element_z("L", net.bridge_l_h, s) / 2.0
    return _element_z("C", net.bridge_c_f, s) / 2.0


def _check_omega(omega: np.ndarray) -> np.ndarray:
    w = np.atleast_1d(np.asarray(omega, dtype=float))
    if not bool(np.all(np.isfinite(w)) and np.all(w > 0.0)):
        raise ValueError("omega 必须为有限正数（ω=0 处元件阻抗奇异）")
    return w


def network_sparams_by_modes(
    net: ReflectionlessNetwork, omega: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """偶/奇半电路路径（ABCD 级联连分数口径）：S11、S21（复数组）。

    S11 = ½(Γe+Γo)、S21 = ½(Γe−Γo)，Γ = (z−Z0)/(z+Z0)。对偶恒等式
    z_e·z_o = Z0² 成立时 S11 ≡ 0、S21 = Γe（低通/高通按 kind）。
    与 network_sparams 互为独立实现路径（#118 双路径，tests 钉一致）。
    """
    w = _check_omega(omega)
    z0 = float(net.spec.z0_ohm)
    s11 = np.empty(w.shape, dtype=complex)
    s21 = np.empty(w.shape, dtype=complex)
    for i, wi in enumerate(w):
        s = 1j * float(wi)
        z_e = _half_z(net, s, even=True)
        z_chain_o = _half_z(net, s, even=False)
        z_o = _parallel(_bridge_half_z(net, s), z_chain_o)
        g_e = (z_e - z0) / (z_e + z0)
        g_o = (z_o - z0) / (z_o + z0)
        s11[i] = 0.5 * (g_e + g_o)
        s21[i] = 0.5 * (g_e - g_o)
    return s11, s21


def duality_residual(net: ReflectionlessNetwork, omega: np.ndarray) -> np.ndarray:
    """对偶恒等式残差 |z_e·z_o/Z0² − 1|（逐频；任务判据 4 的量化输出）。

    实测 ≤1e-15（等值链族全频段）；恒等式失效即恒阻特性失效。
    """
    w = _check_omega(omega)
    z0 = float(net.spec.z0_ohm)
    out = np.empty(w.shape, dtype=float)
    for i, wi in enumerate(w):
        s = 1j * float(wi)
        z_e = _half_z(net, s, even=True)
        z_chain_o = _half_z(net, s, even=False)
        z_o = _parallel(_bridge_half_z(net, s), z_chain_o)
        out[i] = abs(z_e * z_o / (z0 * z0) - 1.0)
    return out


def network_sparams(
    net: ReflectionlessNetwork, omega: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """全网表 MNA 路径（主引擎）：S11、S21（复数组，端接 Z0）。

    节点导纳装配（节点：port1/port2/各链内节点/镜像节点/地）→ 删地行列
    求逆得 Z 参数 → S = (Z−Z0 I)(Z+Z0 I)⁻¹ 标量式。与
    network_sparams_by_modes 互为独立实现路径（#118 双路径，tests 钉
    一致 ≤1e-9）。
    """
    w = _check_omega(omega)
    p = int(net.spec.n_pairs)
    z0 = float(net.spec.z0_ohm)
    nodes = ["p1", "p2"]
    nodes += [f"x{i}" for i in range(1, p + 1)]  # 左链内节点
    nodes += ["w"]  # 镜像节点
    nodes += [f"y{i}" for i in range(p, 0, -1)]  # 右链内节点（镜像对称序）
    nodes += ["g"]
    idx = {n_i: i for i, n_i in enumerate(nodes)}
    n_all = len(nodes)
    seq = _chain_series_list(net)
    s11 = np.empty(w.shape, dtype=complex)
    s21 = np.empty(w.shape, dtype=complex)

    def _branch(y_mat: np.ndarray, na: str, nb: str, z_br: complex, idx: dict[str, int]) -> None:
        y = 1.0 / z_br
        i_ = idx[na]
        j_ = idx[nb]
        y_mat[i_, i_] += y
        y_mat[j_, j_] += y
        y_mat[i_, j_] -= y
        y_mat[j_, i_] -= y

    for k, wk in enumerate(w):
        s = 1j * float(wk)
        y_mat = np.zeros((n_all, n_all), dtype=complex)
        if net.bridge_l_h is not None:
            _branch(y_mat, "p1", "p2", _element_z("L", net.bridge_l_h, s), idx)
        else:
            _branch(y_mat, "p1", "p2", _element_z("C", net.bridge_c_f, s), idx)
        prev_l, prev_r = "p1", "p2"
        for i in range(p):
            k_ser, v_ser = seq[2 * i]
            k_sh, v_sh = seq[2 * i + 1]
            node_l, node_r = f"x{i + 1}", f"y{p - i}"
            z_ser = _element_z(k_ser, v_ser, s)
            z_sh = _element_z(k_sh, v_sh, s)
            _branch(y_mat, prev_l, node_l, z_ser, idx)
            _branch(y_mat, prev_r, node_r, z_ser, idx)
            _branch(y_mat, node_l, "g", z_sh, idx)
            _branch(y_mat, node_r, "g", z_sh, idx)
            prev_l, prev_r = node_l, node_r
        _branch(y_mat, prev_l, "w", net.r_absorber_ohm + 0j, idx)
        _branch(y_mat, prev_r, "w", net.r_absorber_ohm + 0j, idx)
        if net.plane_c_f is not None:
            _branch(y_mat, "w", "g", _element_z("C", net.plane_c_f, s), idx)
        else:
            _branch(y_mat, "w", "g", _element_z("L", net.plane_l_h, s), idx)
        keep = [idx[n_i] for n_i in nodes if n_i != "g"]
        z_full = np.linalg.inv(y_mat[np.ix_(keep, keep)])
        i1, i2 = keep.index(idx["p1"]), keep.index(idx["p2"])
        z11 = z_full[i1, i1]
        z12 = z_full[i1, i2]
        z22 = z_full[i2, i2]
        den = (z11 + z0) * (z22 + z0) - z12 * z12
        s11[k] = ((z11 - z0) * (z22 + z0) - z12 * z12) / den
        s21[k] = 2.0 * z0 * z12 / den
    return s11, s21
