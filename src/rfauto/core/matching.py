"""匹配网络与滤波器综合。

匹配网络综合（L/π/T，L-section 闭式）
滤波器综合（commensurate-line，Richard 变换）

产出是元件值/线宽序列给 ADS 网表消费，不是几何。
E-5：网表由 ads_netlist.py 生成，综合只产参数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ─── L-section 匹配网络 ───────────────────────────────────────────────────────

@dataclass
class LSectionResult:
    """L-section 匹配网络结果。

    注意（0bf 遗留标注）：topology 字符串是历史"工况标签"（RL>Rs 记
    "high_pass"、RL<Rs 记 "low_pass"），**不是**滤波响应型——见
    synthesize_l_section 文档说明。元件语义以各 property 为准。
    """

    topology: str  # 遗留工况标签: "high_pass"(RL>Rs) | "low_pass"(RL<Rs) | "bypass"
    z1: float      # 串联支路电抗模值 (ohm)
    z2: float      # 并联支路电抗模值 (ohm)
    f0_ghz: float
    z_source: float
    z_load: float

    @property
    def l_series_nh(self) -> float:
        """串联电感 (nH)。"""
        return self.z1 / (2 * math.pi * self.f0_ghz * 1e9) * 1e9

    @property
    def c_shunt_pf(self) -> float:
        """并联电容 (pF)。"""
        return 1 / (2 * math.pi * self.f0_ghz * 1e9 * self.z2) * 1e12

    @property
    def c_series_pf(self) -> float:
        """串联支路若取电容的容值 (pF)——由 z1 反推（见类文档 0bf 排布注记）。"""
        return 1 / (2 * math.pi * self.f0_ghz * 1e9 * self.z1) * 1e12

    @property
    def l_shunt_nh(self) -> float:
        """并联支路若取电感的感值 (nH)——由 z2 反推（见类文档 0bf 排布注记）。"""
        return self.z2 / (2 * math.pi * self.f0_ghz * 1e9) * 1e9

    def to_dict(self) -> dict[str, Any]:
        return {
            "topology": self.topology,
            "z_source": self.z_source,
            "z_load": self.z_load,
            "f0_ghz": self.f0_ghz,
            "z1_series_ohm": round(self.z1, 2),
            "z2_shunt_ohm": round(self.z2, 2),
        }


def synthesize_l_section(
    z_source: float,
    z_load: float,
    f0_ghz: float,
) -> LSectionResult:
    """L-section 匹配网络综合（闭式解）。**遗留入口（0bf 标注）**。

    遗留说明——topology 标签与元件响应型语义相反（本次如实标注、不改行为）：

    - RL > Rs（返回标签 "high_pass"）：**串联电感（模值 z1）+ 并联电容
      （模值 z2，跨负载侧/大电阻侧）**——这是**低通**梯形结构，标签是
      历史工况记号（阻抗升高侧），与响应型相反。l_series_nh/c_shunt_pf
      属性与该排布一致，可按属性名直接画网络（f0 共轭匹配精确成立）；
    - RL < Rs（返回标签 "low_pass"）：**串联电容（模值 z2=RL·q，靠负载）
      + 并联电感（模值 z1=Rs/q，跨源侧/大电阻侧）**——这是**高通**梯形
      结构。注意：c_series_pf(取 z1)/l_shunt_nh(取 z2) 的属性命名对应
      RL>Rs 的"串 z1 并 z2"排布，RL<Rs 分支若按属性名直接取值画网络
      （串 z1 并 z2）**得不到**共轭匹配——正确排布须交换（串 z2 并 z1）。
      这是 0bf 标注的歧义核心：闭式值正确、属性↔位置映射在本分支相反。

    闭式解本身正确（q、z1、z2 在 f0 精确共轭匹配，值不含糊），仅标签与
    属性排布映射有歧义。新代码请用 synthesize_l_match：response
    参数显式声明响应型（low_pass=串 L 并 C / high_pass=串 C 并 L），元件
    以 LCElement(kind/role/value) 显式给出且按负载端→源端排布、逐元件
    语义无歧义。本函数保留仅为行为兼容（标签字符串与 z1/z2 逐字节不变，
    既有消费方/测试钉住）。

    Args:
        z_source: 源阻抗 (ohm)
        z_load: 负载阻抗 (ohm)
        f0_ghz: 中心频率 (GHz)

    Returns:
        LSectionResult
    """
    # Q 因子
    r_ratio = z_load / z_source
    if abs(r_ratio - 1.0) < 1e-10:
        # 阻抗相等：不需要匹配，返回零值
        return LSectionResult(
            topology="bypass", z1=1e-12, z2=1e12,
            f0_ghz=f0_ghz, z_source=z_source, z_load=z_load,
        )
    elif r_ratio > 1:
        # RL>Rs（遗留标签 "high_pass"）：串联电感(z1) + 并联电容(z2，跨负载)——
        # 实际低通梯形结构，标签为工况记号非响应型（0bf 标注）
        q = math.sqrt(r_ratio - 1)
        z1 = z_source * q
        z2 = z_load / q
        topology = "high_pass"
    else:
        # RL<Rs（遗留标签 "low_pass"）：串联电容(模值 z2，靠负载) +
        # 并联电感(模值 z1，跨源)——实际高通梯形结构；属性 c_series/l_shunt
        # 的 z 引用与本分支排布相反（见 docstring，0bf 标注不改值）
        q = math.sqrt(1 / r_ratio - 1)
        z1 = z_source / q
        z2 = z_load * q
        topology = "low_pass"

    return LSectionResult(
        topology=topology,
        z1=z1,
        z2=z2,
        f0_ghz=f0_ghz,
        z_source=z_source,
        z_load=z_load,
    )


# ─── Chebyshev 滤波器综合 ────────────────────────────────────────────────────

@dataclass
class ChebyshevFilterResult:
    """Chebyshev 滤波器综合结果。"""
    order: int
    passband_ripple_db: float
    cutoff_ghz: float
    element_values: list[float]  # g1, g2, ..., gn
    z0: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "chebyshev",
            "order": self.order,
            "passband_ripple_db": self.passband_ripple_db,
            "cutoff_ghz": self.cutoff_ghz,
            "element_values": [round(v, 4) for v in self.element_values],
            "z0": self.z0,
        }


def chebyshev_g_values(order: int, ripple_db: float) -> list[float]:
    """计算 Chebyshev 滤波器的 g 值（归一化元件值）。

    基于 Pozar §8.4 表8.4.1 的递推公式。

    Args:
        order: 滤波器阶数
        ripple_db: 通带纹波 (dB)

    Returns:
        [g0, g1, g2, ..., gn, g_load] 长度为 order+2
    """
    # 通带纹波因子
    epsilon = math.sqrt(10 ** (ripple_db / 10) - 1)

    # beta 参数
    beta = math.log(1 / math.tanh(ripple_db / 17.37))

    # gamma
    gamma = math.sinh(beta / (2 * order))

    # g0 = 1 (源阻抗归一化)
    g = [1.0]

    # g1
    g1 = 2 * math.sin(math.pi / (2 * order)) / gamma
    g.append(g1)

    # gn 递推
    for i in range(2, order + 1):
        num = 4 * math.sin((2 * i - 1) * math.pi / (2 * order)) * math.sin((2 * i - 3) * math.pi / (2 * order))
        den = g[i - 1] * (gamma ** 2 + math.sin((i - 1) * math.pi / order) ** 2)
        g.append(num / den)

    # 负载 g 值
    if order % 2 == 1:
        g.append(1.0)  # 奇数阶：负载 = 源
    else:
        g.append(1.0 + epsilon ** 2)

    return g


def synthesize_chebyshev_filter(
    order: int,
    ripple_db: float,
    cutoff_ghz: float,
    z0: float = 50.0,
) -> ChebyshevFilterResult:
    """Chebyshev 低通滤波器综合。

    Args:
        order: 滤波器阶数
        ripple_db: 通带纹波 (dB)
        cutoff_ghz: 截止频率 (GHz)
        z0: 参考阻抗 (ohm)

    Returns:
        ChebyshevFilterResult
    """
    g_values = chebyshev_g_values(order, ripple_db)

    return ChebyshevFilterResult(
        order=order,
        passband_ripple_db=ripple_db,
        cutoff_ghz=cutoff_ghz,
        element_values=g_values,
        z0=z0,
    )


# ─── Richard 变换（commensurate line 滤波器）──────────────────────────────────

@dataclass
class CommensurateLineResult:
    """Commensurate 线滤波器结果。"""
    order: int
    cutoff_ghz: float
    z0: float
    line_lengths_deg: list[float]  # 每段电长度 (度)
    impedances: list[float]        # 每段阻抗 (ohm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "commensurate_line",
            "order": self.order,
            "cutoff_ghz": self.cutoff_ghz,
            "z0": self.z0,
            "line_lengths_deg": [round(v, 2) for v in self.line_lengths_deg],
            "impedances_ohm": [round(v, 2) for v in self.impedances],
        }


def synthesize_commensurate_line(
    order: int,
    cutoff_ghz: float,
    z0: float = 50.0,
) -> CommensurateLineResult:
    """Commensurate 线滤波器综合（Richard 变换）。

    将集总元件滤波器变换为等效传输线结构。
    每段线长 = lambda/4 @ cutoff 频率。

    Args:
        order: 滤波器阶数
        cutoff_ghz: 截止频率 (GHz)
        z0: 参考阻抗 (ohm)

    Returns:
        CommensurateLineResult
    """
    # 先综合 Chebyshev 滤波器
    cheb = synthesize_chebyshev_filter(order, 0.5, cutoff_ghz, z0)

    # Richard 变换：集总元件 → 传输线
    # 串联 L → 串联短截线 (Z = L * Z0)
    # 并联 C → 并联短截线 (Z = Z0 / C)
    impedances: list[float] = []
    for i, g in enumerate(cheb.element_values[1:-1]):  # 跳过 g0 和 g_load
        z_line = g * z0 if i % 2 == 0 else z0 / g  # 奇数=串联, 偶数=并联
        impedances.append(z_line)

    # 每段电长度 = 90 度 @ cutoff
    line_lengths = [90.0] * len(impedances)

    return CommensurateLineResult(
        order=order,
        cutoff_ghz=cutoff_ghz,
        z0=z0,
        line_lengths_deg=line_lengths,
        impedances=impedances,
    )


# ─── L / π / T 匹配网络闭式解（vs skrf 对拍锚）───────────────────────
#
# 给定 Rs、RL、f0（π/T 另给有载 Q 或带宽目标）→ 集总 LC 元件值。
# 元件表按「负载端 → 源端」排列，便于自负载做阻抗递推（input_impedance）。
#
# 拓扑与闭式解（Pozar §5.1 L-section / Q 匹配；多元件 π/T 的虚拟电阻 Rv）：
#   L  : 2 元件（1 串联 + 1 并联），Q = sqrt(R_big / R_small - 1) 由阻抗比唯一确定；
#        并联支路跨接较大电阻，串联支路与较小电阻串联。
#   π  : 并联(跨 RL) - 串联 - 并联(跨 Rs)；Rv < min(Rs, RL)，
#        Q1 = sqrt(Rs/Rv - 1)、Q2 = sqrt(RL/Rv - 1)、Q = Q1 + Q2。
#   T  : 串联(串 RL) - 并联 - 串联(串 Rs)；Rv > max(Rs, RL)，
#        Q1 = sqrt(Rv/Rs - 1)、Q2 = sqrt(Rv/RL - 1)、Q = Q1 + Q2。
#   响应型：low_pass = 串联电感 + 并联电容；high_pass = 串联电容 + 并联电感
#   （同一 f0 上两型的电抗/电纳量值相同、符号相反，理想匹配深度一致）。
#
# 判据（§10.22 #24）：闭式元件值 → skrf 构造同拓扑网络 → |S11|@f0 与理论匹配
# 深度一致（to_skrf_network + tests/unit/test_matching.py 的 ±0.1 dB 对拍）。

_MATCH_LOW_PASS = "low_pass"
_MATCH_HIGH_PASS = "high_pass"
_MATCH_RESPONSES = (_MATCH_LOW_PASS, _MATCH_HIGH_PASS)


def _require_positive_finite(name: str, value: float) -> float:
    """收敛为 float 并断言为正有限数（非法输入立即抛 ValueError）。"""
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return number


def _require_response(response: str) -> str:
    if response not in _MATCH_RESPONSES:
        raise ValueError(f"response 必须是 {_MATCH_RESPONSES} 之一，实际 {response!r}")
    return response


@dataclass(frozen=True)
class LCElement:
    """单个集总元件；value 为电感 (H) 或电容 (F)。"""

    kind: str    # "L" | "C"
    role: str    # "series" | "shunt"
    value: float

    def impedance(self, omega: float) -> complex:
        """元件自身阻抗（Ω）；串联元件直接用，并联元件取 1/(1/Z + 1/Z_el)。"""
        if self.kind == "L":
            return 1j * omega * self.value
        return 1.0 / (1j * omega * self.value)

    @property
    def value_nh(self) -> float:
        return self.value * 1e9

    @property
    def value_pf(self) -> float:
        return self.value * 1e12

    @property
    def display(self) -> str:
        if self.kind == "L":
            return f"{self.role} L = {self.value_nh:.4f} nH"
        return f"{self.role} C = {self.value_pf:.4f} pF"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "role": self.role,
            "value": self.value,
            "value_nh": self.value_nh,
            "value_pf": self.value_pf,
        }


@dataclass
class MatchNetworkResult:
    """L/π/T 匹配网络闭式解结果（elements 按负载端 → 源端排列）。"""

    topology: str
    response: str
    f0_ghz: float
    z_source: float
    z_load: float
    q: float
    elements: list[LCElement]
    virtual_resistance: float | None = None

    @property
    def bandwidth_frac(self) -> float:
        """设计带宽（分数带宽，一阶约定 BW = f0/Q）。"""
        return math.inf if self.q <= 0.0 else 1.0 / self.q

    def input_impedance(self, f_ghz: float | None = None) -> complex:
        """自负载端向源端递推的输入阻抗（闭式，无 skrf 依赖）。"""
        omega = 2.0 * math.pi * (self.f0_ghz if f_ghz is None else float(f_ghz)) * 1e9
        impedance = complex(self.z_load)
        for element in self.elements:  # 负载端 → 源端
            branch = element.impedance(omega)
            impedance = (
                impedance + branch
                if element.role == "series"
                else 1.0 / (1.0 / impedance + 1.0 / branch)
            )
        return impedance

    def s11(self, f_ghz: float | None = None, z_ref: float | None = None) -> complex:
        reference = self.z_source if z_ref is None else float(z_ref)
        impedance = self.input_impedance(f_ghz)
        return (impedance - reference) / (impedance + reference)

    def s11_db(self, f_ghz: float | None = None, z_ref: float | None = None) -> float:
        magnitude = abs(self.s11(f_ghz, z_ref))
        return -math.inf if magnitude == 0.0 else 20.0 * math.log10(magnitude)

    def match_depth_db(self, f_ghz: float | None = None, z_ref: float | None = None) -> float:
        """回波损耗深度（dB，正值）；理想无损匹配在 f0 趋于 +inf。"""
        return -self.s11_db(f_ghz, z_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "match_network",
            "topology": self.topology,
            "response": self.response,
            "f0_ghz": self.f0_ghz,
            "z_source": self.z_source,
            "z_load": self.z_load,
            "q": self.q,
            "bandwidth_frac": (None if not math.isfinite(self.bandwidth_frac) else self.bandwidth_frac),
            "virtual_resistance_ohm": self.virtual_resistance,
            "elements": [element.to_dict() for element in self.elements],
        }


def _angular_frequency(f0_ghz: float) -> float:
    return 2.0 * math.pi * f0_ghz * 1e9


def _l_match_q(z_source: float, z_load: float) -> float:
    """L 匹配（亦为 π/T 的下限）有载 Q。"""
    big, small = max(z_source, z_load), min(z_source, z_load)
    return math.sqrt(big / small - 1.0)


def _series_reactance_element(x_ohm: float, response: str, omega: float) -> LCElement:
    if response == _MATCH_LOW_PASS:
        return LCElement("L", "series", x_ohm / omega)
    return LCElement("C", "series", 1.0 / (x_ohm * omega))


def _shunt_susceptance_element(b_siemens: float, response: str, omega: float) -> LCElement:
    if response == _MATCH_LOW_PASS:
        return LCElement("C", "shunt", b_siemens / omega)
    return LCElement("L", "shunt", 1.0 / (b_siemens * omega))


def _resolve_loaded_q(
    q: float | None,
    bandwidth_frac: float | None,
    z_source: float,
    z_load: float,
    topology: str,
) -> float:
    if (q is None) == (bandwidth_frac is None):
        raise ValueError("必须且只能给定 q 与 bandwidth_frac 之一")
    if bandwidth_frac is not None:
        resolved = 1.0 / _require_positive_finite("bandwidth_frac", bandwidth_frac)
    else:
        resolved = _require_positive_finite("q", q)
    q_min = _l_match_q(z_source, z_load)
    if resolved <= q_min:
        raise ValueError(f"{topology} 匹配有载 Q 必须大于 L 匹配极限 Q={q_min:.6g}，实际 q={resolved:.6g}")
    return resolved


def _solve_virtual_resistance(q_target: float, z_source: float, z_load: float, kind: str) -> float:
    """解虚拟电阻 Rv，使 Q1 + Q2 = q_target（对 t 做二分，良态且确定性）。

    t = sqrt(R_big/Rv - 1)（π）或 sqrt(Rv/R_big - 1)（T），Q(t) 单调递增。
    """
    big, small = max(z_source, z_load), min(z_source, z_load)
    ratio = big / small
    if q_target <= math.sqrt(ratio - 1.0):
        raise ValueError("q 必须大于 L 匹配极限 Q")
    if kind == "pi":
        def q_of(t: float) -> float:
            return t + math.sqrt(ratio * t * t + (ratio - 1.0))
    else:
        def q_of(t: float) -> float:
            return t + math.sqrt(ratio * (1.0 + t * t) - 1.0)
    low, high = 0.0, q_target
    for _ in range(200):
        mid = 0.5 * (low + high)
        if mid <= low or mid >= high:
            break
        if q_of(mid) < q_target:
            low = mid
        else:
            high = mid
    t = 0.5 * (low + high)
    if kind == "pi":
        return small / (1.0 + t * t)
    return big * (1.0 + t * t)


def synthesize_l_match(
    z_source: float,
    z_load: float,
    f0_ghz: float,
    response: str = _MATCH_LOW_PASS,
) -> MatchNetworkResult:
    """L 型匹配闭式解；Q 由 Rs/RL 唯一确定（无自由度）。"""
    z_source = _require_positive_finite("z_source", z_source)
    z_load = _require_positive_finite("z_load", z_load)
    f0_ghz = _require_positive_finite("f0_ghz", f0_ghz)
    response = _require_response(response)
    omega = _angular_frequency(f0_ghz)
    big, small = max(z_source, z_load), min(z_source, z_load)
    q = math.sqrt(big / small - 1.0)
    elements: list[LCElement] = []
    if q > 0.0:
        shunt = _shunt_susceptance_element(q / big, response, omega)
        series = _series_reactance_element(q * small, response, omega)
        # 并联支路跨接较大电阻；输出表按负载端 → 源端排列
        elements = [shunt, series] if z_load >= z_source else [series, shunt]
    return MatchNetworkResult("L", response, f0_ghz, z_source, z_load, q, elements)


def synthesize_pi_match(
    z_source: float,
    z_load: float,
    f0_ghz: float,
    q: float | None = None,
    bandwidth_frac: float | None = None,
    response: str = _MATCH_LOW_PASS,
) -> MatchNetworkResult:
    """π 型匹配闭式解（并联-串联-并联）；给定 q 或 bandwidth_frac 之一。"""
    z_source = _require_positive_finite("z_source", z_source)
    z_load = _require_positive_finite("z_load", z_load)
    f0_ghz = _require_positive_finite("f0_ghz", f0_ghz)
    response = _require_response(response)
    q = _resolve_loaded_q(q, bandwidth_frac, z_source, z_load, "π")
    omega = _angular_frequency(f0_ghz)
    rv = _solve_virtual_resistance(q, z_source, z_load, kind="pi")
    q_source = math.sqrt(z_source / rv - 1.0)
    q_load = math.sqrt(z_load / rv - 1.0)
    series = _series_reactance_element((q_source + q_load) * rv, response, omega)
    shunt_load = _shunt_susceptance_element(q_load / z_load, response, omega)
    shunt_source = _shunt_susceptance_element(q_source / z_source, response, omega)
    elements = [shunt_load, series, shunt_source]  # 负载端 → 源端
    return MatchNetworkResult("pi", response, f0_ghz, z_source, z_load, q, elements, virtual_resistance=rv)


def synthesize_t_match(
    z_source: float,
    z_load: float,
    f0_ghz: float,
    q: float | None = None,
    bandwidth_frac: float | None = None,
    response: str = _MATCH_LOW_PASS,
) -> MatchNetworkResult:
    """T 型匹配闭式解（串联-并联-串联）；给定 q 或 bandwidth_frac 之一。"""
    z_source = _require_positive_finite("z_source", z_source)
    z_load = _require_positive_finite("z_load", z_load)
    f0_ghz = _require_positive_finite("f0_ghz", f0_ghz)
    response = _require_response(response)
    q = _resolve_loaded_q(q, bandwidth_frac, z_source, z_load, "T")
    omega = _angular_frequency(f0_ghz)
    rv = _solve_virtual_resistance(q, z_source, z_load, kind="T")
    q_source = math.sqrt(rv / z_source - 1.0)
    q_load = math.sqrt(rv / z_load - 1.0)
    series_load = _series_reactance_element(q_load * z_load, response, omega)
    series_source = _series_reactance_element(q_source * z_source, response, omega)
    shunt = _shunt_susceptance_element((q_source + q_load) / rv, response, omega)
    elements = [series_load, shunt, series_source]  # 负载端 → 源端
    return MatchNetworkResult("T", response, f0_ghz, z_source, z_load, q, elements, virtual_resistance=rv)


def synthesize_match_network(
    topology: str,
    z_source: float,
    z_load: float,
    f0_ghz: float,
    q: float | None = None,
    bandwidth_frac: float | None = None,
    response: str = _MATCH_LOW_PASS,
) -> MatchNetworkResult:
    """统一入口：topology ∈ {'L', 'pi', 'T'}。"""
    key = str(topology).strip().lower()
    if key in ("l", "l-match", "l_match", "l-section", "l_section"):
        if q is not None or bandwidth_frac is not None:
            raise ValueError("L 匹配的 Q 由 Rs/RL 唯一确定，不能另行给定 q/bandwidth_frac")
        return synthesize_l_match(z_source, z_load, f0_ghz, response=response)
    if key == "pi":
        return synthesize_pi_match(z_source, z_load, f0_ghz, q=q, bandwidth_frac=bandwidth_frac, response=response)
    if key in ("t", "t-match", "t_match"):
        return synthesize_t_match(z_source, z_load, f0_ghz, q=q, bandwidth_frac=bandwidth_frac, response=response)
    raise ValueError(f"未知匹配拓扑 {topology!r}（应为 'L'/'pi'/'T'）")


def to_skrf_network(result: MatchNetworkResult, freqs_ghz: Any = None) -> Any:
    """把闭式解构造成 skrf 集总 LC 网络（懒加载 skrf；返回 skrf.Network）。

    外部端口 z0：源端 = result.z_source，负载端 = result.z_load。
    freqs_ghz 为 None 时只取 f0；也接受非空正频率序列 (GHz)。
    """
    import numpy as np
    import skrf
    from skrf.circuit import Circuit

    if freqs_ghz is None:
        values = np.array([result.f0_ghz], dtype=float)
    else:
        values = np.atleast_1d(np.asarray(freqs_ghz, dtype=float))
    if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("freqs_ghz 必须是一维非空的有限正频率序列 (GHz)")
    if not result.elements:
        raise ValueError("该匹配结果为 bypass（无元件），无需构造 skrf 网络")
    frequency = skrf.Frequency.from_f(values * 1e9, unit="hz")
    omega = 2.0 * math.pi * frequency.f
    port_source = Circuit.Port(frequency, "port_source", z0=result.z_source)
    port_load = Circuit.Port(frequency, "port_load", z0=result.z_load)
    nodes: list[list[tuple[Any, int]]] = []
    current: list[tuple[Any, int]] = [(port_source, 0)]
    for index, element in enumerate(reversed(result.elements)):  # 源端 → 负载端
        branch = element.impedance(omega)
        if element.role == "series":
            network = Circuit.SeriesImpedance(frequency, branch, name=f"e{index}")
        else:
            network = Circuit.ShuntAdmittance(frequency, 1.0 / branch, name=f"e{index}")
        nodes.append([*current, (network, 0)])
        current = [(network, 1)]
    nodes.append([*current, (port_load, 0)])
    return Circuit(nodes).network
