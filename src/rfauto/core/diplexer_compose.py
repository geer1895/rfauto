"""QW-9 diplexer 组合配方示例（compose 第二展示件，纯算法零 IO，不进注册表）。

结构（Pozar/Microwaves101 diplexer 口径）：输入 T 结（理想集总节点）分两臂——
LPF 臂（Butterworth 梯形）+ HPF 臂（LP→HP 对偶梯形）——合成三口复合网络，
|S21|=|S31| 交越点锁定 fc，互补滤波器把反射功率互相改道吸收（diplexer vs
简单功分器的物理本质）。

组装口径（docstring 声明，任务规格"skrf 级联或 ABCD 二选一"的裁决=ABCD 组装）：
两臂各自为两口 ABCD 级联（batched (n,2,2)，Pozar §4.4 传输矩阵约定，与
core/emi_filter.py 同式；本模块自包含基本件不 import emi_filter，skrf 只进
测试对拍面）；三口复合体用节点公式精确组装——臂输入阻抗 Zin_i=(A_i·Z0+B_i)/
(C_i·Z0+D_i)，节点阻抗 Zin=1/(Yin1+Yin2)，则端口 1 激励列：

    S11 = (Zin−Z0)/(Zin+Z0)
    S21 = 2·[Zin/(Zin+Z0)]·t1，S31 = 2·[Zin/(Zin+Z0)]·t2，t_i = 1/(A_i+B_i/Z0)

（V_in=A·V2+B·I2、I2=V2/Z0 → t_i=V2/V_node；Thevenin 源 Vs 内阻 Z0 下
V_node=Vs·Zin/(Zin+Z0)；功率波 a1=Vs/(2√Z0)、b2=V2/√Z0 → S21=2·V2/Vs。）
能量守恒 |S11|²+|S21|²+|S31|²=1 是该口径的**代数恒等式**（对任意 Zin 展开
|(Zin−Z0)|²+4Z0·Re(Yin)·|Zin|² ≡ |Zin+Z0|²，逐点机器精度成立），且全程无
中间节点消元——第一版 nodal+Kron 口径在臂内并联自谐振频点 Yii 奇异（数值
裁判实测），本口径天然免疫。

公式口径（逐式出处，#1c/#300 纪律）：
- Butterworth 最平坦原型 g 值闭式 ``g_k = 2·sin((2k−1)·π/(2N))``（g0=g_{N+1}=1）；
  表值对照 Pozar, *Microwave Engineering*, 4th ed., Table 5.1（N=3 为 [1, 2, 1]、
  N=5 为 [0.6180, 1.6180, 2.0000, 1.6180, 0.6180]，测试按教科书四位小数独立复核钉，
  见 ``BUTTERWORTH_G_TEXTBOOK``）。
- 等端接定标（g0=1，Pozar §5.3 低通原型定标）：串联 ``L_k = g_k·Z0/ωc``、
  并联 ``C_k = g_k/(Z0·ωc)``，ωc = 2π·fc。
- 低通→高通对偶（Pozar §5.2 频率变换 ω → −ωc²/ω）：串联 L↔串联
  ``C'_k = 1/(g_k·ωc·Z0)``、并联 C↔并联 ``L'_k = Z0/(g_k·ωc)``。
- 一阶常阻互补对偶（CR，lpf_order=hpf_order=1 时启用）：HPF 臂取
  ``C = L_LPF/Z0²``（交越锁定 fc，L = Z0/ωc）。恒等式（本仓推导，测试全带数值钉）：
  同一节点引出两支路 Z 与 Z0²/Z（各端接 Z0），输入导纳和恒为 Y0：

      1/(Z0+Z1) + 1/(Z0+Z0²/Z1) = (Z0+Z1)/(Z0·(Z0+Z1)) = 1/Z0  （对任意 Z1）

  → 复合 S11≡0、|S21|²+|S31|²≡1 全带严格成立，且 |S21|²=1/(1+x²)、
  |S31|²=x²/(1+x²)（x=f/fc）：能量守恒/互补/交越三锚全部闭式精确。
- CR 定标取 g_eff=1（L=Z0/ωc），**非** Butterworth N=1 表值 g1=2（表值锁定的是
  臂 standalone −3dB 于 fc；CR 臂 standalone −3dB 在 2fc——而复合交越恒在 fc，
  复合口径优先，notes 如实声明）。
- ≥2 阶对：标准 LP→HP 对偶对的交越点由 ω↔ωc²/ω 换臂对称性的不动点精确落于 fc；
  但纯梯形对不存在常阻互补解（串联首梯形臂的常阻伙伴要求 C'=0，系数平衡
  可证；见 tests 数值锚），交越过渡区回损有固有地板（3/3 实测 ~−7..−10 dB）。
  这是无耗网络的物理而非实现缺陷：无耗+互易三口网络不可能三口全匹配
  （Pozar §7.5），全带完美匹配只有一阶 CR 对。
- T 结理想化：零寄生集总节点（Pozar §7.5 T 型结头的理想化口径）；结处实际功率
  分配随两臂输入阻抗状态变化（非固定 1/√2——固定 1/√2 是_matched-input_损耗型
  或混合结的口径，对无耗集总节点不成立），交越点两臂 |S| 相等。
- 无耗理想元件（无 ESR/ESL/自谐振）；时谐约定 e^{+jωt}；S 为等 Z0 实参考伪波归一。
- 最平坦无耗梯形臂的 standalone 响应符合 Butterworth 律
  ``|S21_arm|² = 1/(1+(f/fc)^{2N}}``（Pozar §5.1 式 (5.10) 口径），测试经
  emi_filter ABCD 独立路径复核（#118：数值裁判必须独立来源）。

判据预声明（#122 先行，diplexer_verdict 四门）：
1. ``energy_conservation_ok``：全带 max||S11|²+|S21|²+|S31|²−1| ≤ 1e-8
   （无耗三口网络幺正性恒等式，逐点线性功率域）。
2. ``crossover_at_fc``：|S21|=|S31| 交点（多交点取最接近 fc 者）落在 fc·(1±tol)。
3. ``s11_band_ok``：两侧通带（挖去 fc·(1±tol) 交越过渡带）内 max|S11|² ≤
   10^(s11_max_db/10)（线性功率域比较，等价 dB 门；过渡带挖除是 T 结 diplexer
   的固有物理口径，见上）。
4. ``complementarity``：同掩码内 max||S21|²+|S31|²−1| ≤ 10^(s11_max_db/10)
   （由能量守恒，互补亏缺 ≡ |S11|²，阈值与 S11 门自洽）。
overall：四门全绿=pass；能量破坏或交越越界=fail；通带掩码为空=unknown
（#314/#316：无对如实 unknown，不凑 pass 也不冒充 fail）。

零 IO、不 import skrf（skrf 只进测试对拍面）、不进 @register_calculator
（参照 core/pdn.py、core/emi_filter.py 先例，免 #231 注册表消费者同步）。
"""

from __future__ import annotations

import math
import operator
from collections.abc import Mapping, Sequence

import numpy as np

__all__ = [
    "BUTTERWORTH_G",
    "BUTTERWORTH_G_TEXTBOOK",
    "ENERGY_ATOL_VERDICT",
    "butterworth_g_values",
    "diplexer_lpf_hpf",
    "diplexer_verdict",
]

# ── 入参守卫（emi_filter 同款惯例，自包含不 import）──────────────────────────


def _freq_array(f: object, name: str = "f") -> np.ndarray:
    """频率入参收敛为一维正 float 数组（#140：注解写了不代表调用方传的是）。"""
    if isinstance(f, bool):
        raise ValueError(f"{name} 必须是数值序列，收到 bool")
    try:
        arr = np.atleast_1d(np.asarray(f, dtype=float))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值序列，收到 {f!r}") from exc
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维频率序列，实际 shape {arr.shape}")
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    if np.any(arr <= 0.0) or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 必须全为正有限数")
    return arr


def _pos_finite(value: object, name: str) -> float:
    """正有限实数守卫（显式拒收 bool，df7+⑯：float(True)=1.0 静默污染）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是实数，收到 {value!r}")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return out


def _order_int(value: object, name: str) -> int:
    """阶数守卫：1..5 整数（operator.index 拒 float/bool/str）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是 1..5 整数，收到 bool")
    try:
        n = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} 必须是 1..5 整数，收到 {value!r}") from exc
    if not 1 <= n <= _MAX_ORDER:
        raise ValueError(f"{name} 必须在 1..{_MAX_ORDER}，实际 {n}")
    return n


def _complex_array(z: object, name: str) -> np.ndarray:
    """复数入参收敛为有限一维 complex 数组（拒 bool/字符串/NaN，#16 家族）。"""
    if isinstance(z, bool):
        raise ValueError(f"{name} 必须是数值数组，收到 bool")
    try:
        arr = np.atleast_1d(np.asarray(z, dtype=complex))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值数组，收到 {z!r}") from exc
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须是一维数组，实际 shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} 必须全为有限数")
    return arr


# ── 原型 g 表 ────────────────────────────────────────────────────────────────

_MAX_ORDER = 5


def butterworth_g_values(order: int) -> tuple[float, ...]:
    """Butterworth 最平坦原型 g 值闭式（g_k=2·sin((2k−1)π/(2N))，g0=g_{N+1}=1）。

    出处：闭式为 Butterworth 原型标准结果（Matthaei-Young-Jones §4.06 同式）；
    表值对照 Pozar Table 5.1（四位小数锚见 ``BUTTERWORTH_G_TEXTBOOK``，
    测试独立复核）。

    Args:
        order: 阶数 N（1..5；bool 显式拒收，df7+⑯）。

    Returns:
        (g1, ..., gN) 元组。

    Raises:
        ValueError: order 非 1..5 整数。
    """
    n = _order_int(order, "order")
    return tuple(2.0 * math.sin((2.0 * k - 1.0) * math.pi / (2.0 * n))
                 for k in range(1, n + 1))


#: Butterworth 原型 g 表（闭式生成，键=阶数；出处注记见 butterworth_g_values）。
BUTTERWORTH_G: dict[int, tuple[float, ...]] = {
    n: butterworth_g_values(n) for n in range(1, _MAX_ORDER + 1)
}

#: 教科书四位小数表值（Pozar Table 5.1 摘录；测试按 |闭式−表值|≤5e-4 独立复核钉）。
BUTTERWORTH_G_TEXTBOOK: dict[int, tuple[float, ...]] = {
    1: (2.0,),
    2: (1.4142, 1.4142),
    3: (1.0, 2.0, 1.0),
    4: (0.7654, 1.8478, 1.8478, 0.7654),
    5: (0.6180, 1.6180, 2.0000, 1.6180, 0.6180),
}

#: verdict 能量守恒门绝对容差（线性功率域；实测无耗网络 ~1e-15 量级，门放 1e-8）。
ENERGY_ATOL_VERDICT = 1e-8


# ── 臂梯形元件 ───────────────────────────────────────────────────────────────


def _lpf_elements(order: int, g: tuple[float, ...], wc: float, z0: float
                  ) -> list[tuple[str, float]]:
    """LPF 臂（串联首梯形）：奇位串联 L=g·Z0/ωc，偶位并联 C=g/(Z0·ωc)（Pozar §5.3）。"""
    out: list[tuple[str, float]] = []
    for k, gk in enumerate(g, start=1):
        if k % 2 == 1:
            out.append(("series_L", gk * z0 / wc))
        else:
            out.append(("shunt_C", gk / (wc * z0)))
    return out


def _hpf_elements(order: int, g: tuple[float, ...], wc: float, z0: float
                  ) -> list[tuple[str, float]]:
    """HPF 臂（串联首梯形，标准 LP→HP 对偶）：串联 C'=1/(g·ωc·Z0)，并联 L'=Z0/(g·ωc)。"""
    out: list[tuple[str, float]] = []
    for k, gk in enumerate(g, start=1):
        if k % 2 == 1:
            out.append(("series_C", 1.0 / (gk * wc * z0)))
        else:
            out.append(("shunt_L", z0 / (gk * wc)))
    return out


# ── 三口复合网络内核（臂 ABCD + 节点公式）────────────────────────────────────


def _arm_abcd(f: np.ndarray, elements: Sequence[tuple[str, float]]) -> np.ndarray:
    """单臂梯形 → batched ABCD (n,2,2)（串联首；Pozar §4.4 约定）。

    串联阻抗 Z：[[1,Z],[0,1]]；并联导纳 Y：[[1,0],[Y,1]]；级联=矩阵积。
    """
    omega = 2.0 * np.pi * f
    abcd = np.broadcast_to(np.eye(2, dtype=complex), (f.size, 2, 2)).copy()
    for kind, val in elements:
        if kind == "series_L":
            step = np.empty_like(abcd)
            step[..., 0, 0] = 1.0
            step[..., 0, 1] = 1j * omega * val
            step[..., 1, 0] = 0.0
            step[..., 1, 1] = 1.0
        elif kind == "series_C":
            step = np.empty_like(abcd)
            step[..., 0, 0] = 1.0
            step[..., 0, 1] = 1.0 / (1j * omega * val)
            step[..., 1, 0] = 0.0
            step[..., 1, 1] = 1.0
        elif kind == "shunt_C":
            step = np.empty_like(abcd)
            step[..., 0, 0] = 1.0
            step[..., 0, 1] = 0.0
            step[..., 1, 0] = 1j * omega * val
            step[..., 1, 1] = 1.0
        elif kind == "shunt_L":
            step = np.empty_like(abcd)
            step[..., 0, 0] = 1.0
            step[..., 0, 1] = 0.0
            step[..., 1, 0] = 1.0 / (1j * omega * val)
            step[..., 1, 1] = 1.0
        else:
            raise ValueError(f"未知元件类型 {kind!r}")
        abcd = abcd @ step
    return abcd


def _port1_column(
    f: np.ndarray,
    arms: Mapping[str, Sequence[tuple[str, float]]],
    z0: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """T 节点复合体端口 1 激励列 (S11, S21, S31)（公式见模块 docstring 组装口径）。

    能量守恒 |S11|²+|S21|²+|S31|²=1 为代数恒等式（对任意臂成立，逐点机器精度）。
    """
    a_lpf = _arm_abcd(f, arms["lpf"])
    a_hpf = _arm_abcd(f, arms["hpf"])

    def _zin(a: np.ndarray) -> np.ndarray:
        return (a[..., 0, 0] * z0 + a[..., 0, 1]) / (a[..., 1, 0] * z0 + a[..., 1, 1])

    def _t(a: np.ndarray) -> np.ndarray:
        return 1.0 / (a[..., 0, 0] + a[..., 0, 1] / z0)

    zin = 1.0 / (1.0 / _zin(a_lpf) + 1.0 / _zin(a_hpf))
    node_div = zin / (zin + z0)
    s11 = (zin - z0) / (zin + z0)
    s21 = 2.0 * node_div * _t(a_lpf)
    s31 = 2.0 * node_div * _t(a_hpf)
    return s11, s21, s31


def _find_crossover(
    f: np.ndarray,
    s21: np.ndarray,
    s31: np.ndarray,
    fc_hz: float,
) -> float | None:
    """|S21|=|S31| 交点（Hz）；多交点取最接近 fc 者；无交点返回 None。

    频轴内部按升序排序后找相邻符号翻转区间线性插值（d=|S21|−|S31|，
    d 恰为 0 的频点直接取该频点）。
    """
    order = np.argsort(f)
    fs = f[order]
    d = np.abs(s21[order]) - np.abs(s31[order])
    crossings: list[float] = []
    for i in range(fs.size - 1):
        a, b = d[i], d[i + 1]
        if a == 0.0:
            crossings.append(float(fs[i]))
            continue
        if (a < 0.0) != (b < 0.0) or b == 0.0:
            denom = abs(a) + abs(b)
            t = 0.0 if denom == 0.0 else abs(a) / denom
            crossings.append(float(fs[i] + t * (fs[i + 1] - fs[i])))
    if d.size and d[-1] == 0.0:
        crossings.append(float(fs[-1]))
    if not crossings:
        return None
    return min(crossings, key=lambda x: abs(x - fc_hz))


# ── 公开 API ─────────────────────────────────────────────────────────────────


def diplexer_lpf_hpf(
    f_axis_hz: float | Sequence[float] | np.ndarray,
    fc_hz: float,
    lpf_order: int = 3,
    hpf_order: int = 3,
    z0: float = 50.0,
) -> dict[str, object]:
    """低通-高通对偶型 diplexer 全网络 S 参数（T 结 + LPF 臂 + HPF 臂，全离线）。

    结构与口径见模块 docstring。一阶对（lpf_order=hpf_order=1）为常阻互补
    对偶（CR）：S11≡0、|S21|²+|S31|²≡1、交越精确 fc；≥2 阶对为标准 LP→HP
    对偶：交越仍精确 fc（换臂对称性不动点），交越过渡区回损有固有地板。

    Args:
        f_axis_hz: 频率轴 Hz（一维正有限序列；乱序允许，交点搜索内部排序）。
        fc_hz: 交越（截止）频率 Hz（正有限）。
        lpf_order: LPF 臂 Butterworth 阶数（1..5）。
        hpf_order: HPF 臂阶数（1..5）。
        z0: 系统参考阻抗 Ω（正有限）。

    Returns:
        dict：
        - ``f_axis_hz``：(n,) float 频率轴；
        - ``s11`` / ``s21_lpf_arm`` / ``s31_hpf_arm``：(n,) complex 线性 S 参数
          （端口 1 激励；s21=LPF 臂出端口 2，s31=HPF 臂出端口 3）；
        - ``crossover_ghz``：|S21|=|S31| 交点 GHz（实测插值；无交点 None）；
        - ``g_values``：{"lpf": (…), "hpf": (…), "rule": "cr_crossover_locked" |
          "lp_hp_duality"}；
        - ``notes``：理想化口径与出处注记（str 列表）；
        - ``fc_hz`` / ``z0`` / ``element_values``：定标回显与逐元件值（离线审计面）。

    Raises:
        ValueError: 入参非法（频率非正/非有限、阶数越界或 bool、z0 非正等）。
    """
    f = _freq_array(f_axis_hz, "f_axis_hz")
    fc = _pos_finite(fc_hz, "fc_hz")
    n_lpf = _order_int(lpf_order, "lpf_order")
    n_hpf = _order_int(hpf_order, "hpf_order")
    r0 = _pos_finite(z0, "z0")
    wc = 2.0 * math.pi * fc

    cr_pair = n_lpf == 1 and n_hpf == 1
    if cr_pair:
        # 常阻互补对偶（CR）：L=Z0/ωc（g_eff=1），C=L/Z0²=1/(ωc·Z0)，交越锁定 fc。
        lpf_elems: list[tuple[str, float]] = [("series_L", r0 / wc)]
        hpf_elems: list[tuple[str, float]] = [("series_C", 1.0 / (wc * r0))]
        g_lpf: tuple[float, ...] = (1.0,)
        g_hpf: tuple[float, ...] = (1.0,)
        rule = "cr_crossover_locked"
    else:
        g_lpf = BUTTERWORTH_G[n_lpf]
        g_hpf = BUTTERWORTH_G[n_hpf]
        lpf_elems = _lpf_elements(n_lpf, g_lpf, wc, r0)
        hpf_elems = _hpf_elements(n_hpf, g_hpf, wc, r0)
        rule = "lp_hp_duality"

    s11, s21, s31 = _port1_column(f, {"lpf": lpf_elems, "hpf": hpf_elems}, r0)
    f_x = _find_crossover(f, s21, s31, fc)

    notes = [
        "T 结=理想集总节点（零寄生；Pozar §7.5 三口结头理想化口径）；"
        "结处功率分配随两臂输入阻抗状态变化，非固定 1/√2，交越点两臂 |S| 相等",
        "集总理想元件（无 ESR/ESL/自谐振）；时谐约定 e^{+jωt}；"
        "S 为等 Z0 实参考伪波归一",
        "组装=节点导纳精确解+Kron 消内部节点，S=(I−Z0·Y)(I+Z0·Y)^{-1}"
        "（两口 ABCD 级联不足以表达三口复合体）；skrf 只进测试对拍面",
    ]
    if cr_pair:
        notes += [
            "一阶常阻互补对偶（CR）：HPF 臂 C=L_LPF/Z0²（交越锁定 fc）；恒等式 "
            "Yin_LPF+Yin_HPF≡Y0 → S11≡0、|S21|²+|S31|²≡1 全带严格成立"
            "（闭式本仓推导+测试全带数值钉）",
            "CR 定标取 g_eff=1（L=Z0/ωc），非 Butterworth N=1 表值 g1=2；"
            "复合响应 |S21|²=1/(1+x²)、|S31|²=x²/(1+x²)（x=f/fc）",
        ]
    else:
        notes += [
            "臂=标准 LP→HP 对偶（Pozar §5.2；串联 C=1/(g·ωc·Z0)、并联 L=Z0/(g·ωc)）；"
            "同阶对交越点由 ω↔ωc²/ω 换臂对称性不动点精确落于 fc",
            "纯梯形对不存在常阻互补解：交越过渡区回损有固有地板"
            "（无耗+互易三口不可全匹配，Pozar §7.5）；全带完美匹配仅一阶 CR 对"
            "（lpf_order=hpf_order=1）",
            "交越锁定 fc 要求两臂同阶同原型（换臂对称性）；异阶对交越偏移如实实测"
            "（例 2/4 对偏 −15.6%），v1 不做异阶重定标",
        ]
    notes.append(
        "Butterworth 原型 g=2·sin((2k−1)π/2N)，表值对照 Pozar Table 5.1"
        "（N=3 [1,2,1]、N=5 [0.6180,1.6180,2.0000,1.6180,0.6180]）"
    )

    return {
        "f_axis_hz": f,
        "s11": s11,
        "s21_lpf_arm": s21,
        "s31_hpf_arm": s31,
        "crossover_ghz": None if f_x is None else f_x / 1e9,
        "g_values": {"lpf": g_lpf, "hpf": g_hpf, "rule": rule},
        "notes": notes,
        "fc_hz": fc,
        "z0": r0,
        "element_values": {"lpf": lpf_elems, "hpf": hpf_elems},
    }


def diplexer_verdict(
    s_data: Mapping[str, object],
    fc_hz: float,
    s11_max_db: float = -15.0,
    crossover_tol_frac: float = 0.1,
) -> dict[str, object]:
    """diplexer 预声明判据（#122 先行；四门口径见模块 docstring 判据节）。

    交越点从 S 数组重算（不信任 s_data 携带的 crossover_ghz——病态输入也要
    如实判）；s11/complementarity 掩码=两侧通带（挖去 fc·(1±tol) 交越过渡带，
    固有物理口径见模块 docstring）。

    Args:
        s_data: ``diplexer_lpf_hpf`` 返回 dict（至少含 f_axis_hz/s11/
            s21_lpf_arm/s31_hpf_arm）。
        fc_hz: 名义交越频率 Hz（判据基准；故意给错即 crossover 门 FAIL）。
        s11_max_db: 通带 |S11| 门 dB（须为负；线性功率域阈值=10^(门/10)）。
        crossover_tol_frac: 交越容差相对分数（0<tol<1；兼作过渡带半宽）。

    Returns:
        dict：overall（"pass"|"fail"|"unknown"）+ 四门布尔
        （energy_conservation_ok / crossover_at_fc / s11_band_ok /
        complementarity，掩码空时后两门为 None）+ 实测明细（交点/最劣值/
        掩码点数/scope_note）。

    Raises:
        ValueError: s_data 缺键或形状不一致、fc 非正、门非负、tol 越界等。
    """
    if not isinstance(s_data, Mapping):
        raise ValueError(f"s_data 必须是 Mapping（diplexer_lpf_hpf 返回值），收到 {type(s_data)!r}")
    for key in ("f_axis_hz", "s11", "s21_lpf_arm", "s31_hpf_arm"):
        if key not in s_data:
            raise ValueError(f"s_data 缺键 {key!r}")
    f = _freq_array(s_data["f_axis_hz"], "s_data.f_axis_hz")
    s11 = _complex_array(s_data["s11"], "s_data.s11")
    s21 = _complex_array(s_data["s21_lpf_arm"], "s_data.s21_lpf_arm")
    s31 = _complex_array(s_data["s31_hpf_arm"], "s_data.s31_hpf_arm")
    n = f.size
    if not (s11.size == s21.size == s31.size == n):
        raise ValueError(
            f"s_data 频率/S 数组长度不一致：f={n}, s11={s11.size}, "
            f"s21={s21.size}, s31={s31.size}"
        )
    fc = _pos_finite(fc_hz, "fc_hz")
    if isinstance(s11_max_db, bool) or not isinstance(s11_max_db, (int, float)):
        raise ValueError(f"s11_max_db 必须是负实数，收到 {s11_max_db!r}")
    gate_db = float(s11_max_db)
    if not math.isfinite(gate_db) or gate_db >= 0.0:
        raise ValueError(f"s11_max_db 必须为负有限数，实际 {s11_max_db!r}")
    if isinstance(crossover_tol_frac, bool) or not isinstance(
        crossover_tol_frac, (int, float)
    ):
        raise ValueError(f"crossover_tol_frac 必须是实数，收到 {crossover_tol_frac!r}")
    tol = float(crossover_tol_frac)
    if not math.isfinite(tol) or not 0.0 < tol < 1.0:
        raise ValueError(f"crossover_tol_frac 必须在 (0,1)，实际 {crossover_tol_frac!r}")

    gate_lin = 10.0 ** (gate_db / 10.0)

    # 门 1：能量守恒（全带逐点，无耗三口幺正性）。
    p11, p21, p31 = np.abs(s11) ** 2, np.abs(s21) ** 2, np.abs(s31) ** 2
    energy_dev = float(np.max(np.abs(p11 + p21 + p31 - 1.0)))
    energy_ok = energy_dev <= ENERGY_ATOL_VERDICT

    # 门 2：交越（从数组重算，不信任 s_data 携带值）。
    f_x = _find_crossover(f, s21, s31, fc)
    crossover_ok = f_x is not None and abs(f_x - fc) <= tol * fc
    offset = None if f_x is None else (f_x - fc) / fc

    # 门 3/4：通带掩码（挖去交越过渡带）。
    mask = (f <= fc * (1.0 - tol)) | (f >= fc * (1.0 + tol))
    n_mask = int(np.count_nonzero(mask))
    if n_mask == 0:
        s11_ok: bool | None = None
        comp_ok: bool | None = None
        worst_db: float | None = None
        worst_deficit: float | None = None
    else:
        s11_ok = bool(np.max(p11[mask]) <= gate_lin)
        p11_max = float(np.max(p11[mask]))
        worst_db = float("-inf") if p11_max == 0.0 else float(10.0 * np.log10(p11_max))
        worst_deficit = float(np.max(np.abs(1.0 - (p21 + p31)[mask])))
        comp_ok = bool(worst_deficit <= gate_lin)

    if not energy_ok or not crossover_ok:
        overall = "fail"
    elif n_mask == 0:
        overall = "unknown"
    elif s11_ok and comp_ok:
        overall = "pass"
    else:
        overall = "fail"

    return {
        "overall": overall,
        "energy_conservation_ok": energy_ok,
        "crossover_at_fc": crossover_ok,
        "s11_band_ok": s11_ok,
        "complementarity": comp_ok,
        "energy_max_dev": energy_dev,
        "crossover_ghz": None if f_x is None else f_x / 1e9,
        "crossover_offset_frac": offset,
        "s11_worst_db": worst_db,
        "s11_gate_db": gate_db,
        "complementarity_worst_deficit": worst_deficit,
        "complementarity_rtol": gate_lin,
        "n_band_points": n_mask,
        "scope_note": (
            "s11_band_ok/complementarity 掩码=两侧通带（挖去 fc·(1±tol) 交越过渡带）；"
            "交越点从 S 数组重算；能量守恒全带逐点"
        ),
    }
