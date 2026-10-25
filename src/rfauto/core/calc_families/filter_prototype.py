"""最平坦（Butterworth）低通原型 CALC 键（aurora_l G1，2026-10-23）。

一键：butterworth_prototype（归一 ωc=1 最平坦全极点低通原型 g 值阶梯+
阶数估计+截止预畸变——插损法滤波器综合的两大经典原型之一；#222
triple-grep 证据：``butterworth|maximally.?flat|最平坦`` calc_families
注册键面零命中——chebyshev_prototype=广义切比雪夫耦合矩阵级（Cameron
口径）、multisection_coupler_binomial=二项式耦合器（耦合器域）、
multiplexer_channel_prototype=多工器逐通道链（Chebyshev 单源复用），
最平坦原型独立键面空白）。

物理口径（#1c/#300 出处纪律；docstring 写死）
--------------------------------------------------------
- 最平坦（maximally flat / Butterworth）低通原型 |Γ(ω)|²=1/(1+ω^{2n})
  （Pozar《Microwave Engineering》§8.2 插损法：最平坦原型定义式；带缘
  ω=1 处恰 −3.01 dB，通带内单调、带外按 20n dB/dec 滚降）。
- 原型 g 值闭式（Pozar Table 8.3 最平坦列的生成式，教科书通行形态）：
      g_k = 2·sin[(2k−1)π/(2n)]，k=1..n；g0=g_{n+1}=1（等端接）
  元件语义：奇位 g=串联电感、偶位 g=并联电容（归一 ωc=1、1 Ω 端接；
  对偶起于并 C 的实现同样合法——本键按串 L 首位惯例输出，测试侧以梯形
  ABCD 回代响应 |Γ|²=1/(1+ω^{2n}) 双路径互证）。
- 阶数估计闭式（带缘回损 RL 与阻带衰减 RS@ωs 双规格）：
      n = ceil{ lg[(10^{RS/10}−1)/(10^{RL/10}−1)] / (2·lg ωs) }
  （最平坦衰减 A(ω)=10lg(1+ω^{2n}) 联立 RL、RS 两规格的解析解；切比
  雪夫原型同形公式把分子换成纹波口径）。RL<3.01 dB 时截止需预畸变：
      ωc = (10^{RL/10}−1)^{−1/(2n)}
  （原型 3.01 dB 点从 ω=1 移到 ω=ωc，使带缘 ω=1 恰满足 RL；输出
  cutoff_omega_c 字段，ω=1 处响应由梯形 ABCD 路径验证 ≥ 规格带内）。

数值锚（#118 独立路线，tests/unit/test_g1_calc_coverage_keys.py）：
教科书表值 g=[1,2,1]（n=3）、[1.4142,1.4142]（n=2）、[0.7654,1.8478,
1.8478,0.7654]（n=4）、[0.618,1.618,2,1.618,0.618]（n=5）；ω=1 处
|S21|=−3.0103 dB（n=3/5/7 梯形回代）；阶数-响应自洽：RL=0.5/RS=30@ωs=2
→ n=7、ωc=1.1621、ωs 处 −33.01 dB ≥ RS（梯形 ABCD 与 10lg(1+ω^{2n})
多项式双路径同值）。

守卫：order ∈ [1,31]（int；bool 拒收）或显式 None 走 (rl_db, rs_db,
omega_s) 估计路径；rl_db>0、rs_db>rl_db、omega_s>1；越界显式拒绝。

接口：纯函数零 IO；math 为主；无 ``__all__``（公开 API 快照口径）。

出处：
- butterworth_prototype：最平坦低通原型 g 值与阶数估计（Pozar
  Microwave Engineering §8.2 插损法滤波器综合——最平坦原型定义式、
  Table 8.3 生成式与阶数闭式，章节级转引；式号按 #df6-⑬ 不落页码）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——float(True)=1.0 静默污染，df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，实际 {value!r}")
    return out


def _int(value: Any, name: str) -> int:
    """整数守卫（bool 显式拒收；接受 int 或整值 float）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为整数（不接受 bool）")
    if isinstance(value, int):
        return value
    fv = float(value)
    if not math.isfinite(fv) or fv != int(fv):
        raise ValueError(f"{name} 必须为整数，实际 {value!r}")
    return int(fv)


def g_maxflat(order: int) -> list[float]:
    """最平坦低通原型 g 值（含 g0 与 g_{n+1}，等端接均=1）。"""
    body = [2.0 * math.sin((2.0 * k - 1.0) * math.pi / (2.0 * order))
            for k in range(1, order + 1)]
    return [1.0, *body, 1.0]


def _ladder_abcd(g_body: list[float], w_norm: float) -> tuple[complex, ...]:
    """低通原型梯形 ABCD（串 L 首位；奇位=串 L z=jwg、偶位=并 C y=jwg）。"""
    a_m, b_m, c_m, d_m = 1.0 + 0j, 0j, 0j, 1.0 + 0j
    for k, g_v in enumerate(g_body, start=1):
        if k % 2 == 1:  # 串联电感：M=[1 z;0 1]
            z_el = 1j * w_norm * g_v
            a_n, b_n, c_n, d_n = a_m, a_m * z_el + b_m, c_m, c_m * z_el + d_m
        else:  # 并联电容：M=[1 0;y 1]
            y_el = 1j * w_norm * g_v
            a_n, b_n, c_n, d_n = a_m + b_m * y_el, b_m, c_m + d_m * y_el, d_m
        a_m, b_m, c_m, d_m = a_n, b_n, c_n, d_n
    return a_m, b_m, c_m, d_m


def _s21_db(abcd: tuple[complex, ...]) -> float:
    """1 Ω 对称端接 S21 dB（S21=2/(A+B+C+D)）。"""
    a_m, b_m, c_m, d_m = abcd
    return 20.0 * math.log10(abs(2.0 / (a_m + b_m + c_m + d_m)))


@register_calculator(
    "butterworth_prototype",
    "最平坦低通原型（Butterworth）：g_k=2sin[(2k−1)π/2n]"
    "（g0=g_{n+1}=1 等端接；奇位串 L/偶位并 C 惯例）+阶数估计闭式 "
    "n=ceil{lg[(10^{RS/10}−1)/(10^{RL/10}−1)]/(2lg ωs)}（RL<3.01dB 给截止"
    "预畸变 ωc=(10^{RL/10}−1)^{−1/(2n)}）+响应自证（ω=1 处 −3.0103dB、"
    "ωs 处梯形 ABCD 回代 vs 10lg(1+ω^{2n}) 多项式双路径）。广义切比雪夫"
    "原型=chebyshev_prototype（耦合矩阵级 Cameron 口径）不撞",
    (("order", "int 阶数（1..31；None 走 RL/RS/ωs 估计路径）"),
     ("rl_db", "float dB 带缘（ω=1）最大回损规格（>0，估计路径必填）"),
     ("rs_db", "float dB 阻带 ωs 处最小衰减规格（>rl_db，估计路径必填）"),
     ("omega_s", "float 阻带边界归一频率（>1，估计路径必填）")),
    required=(),
)
def butterworth_prototype(order: int | None = None,
                          rl_db: float | None = None,
                          rs_db: float | None = None,
                          omega_s: float | None = None) -> dict[str, Any]:
    """最平坦低通原型：g 值阶梯 + 阶数估计 + 响应自证。"""
    tag = "butterworth_prototype"
    cutoff_wc: float | None = None
    if order is None:
        if rl_db is None or rs_db is None or omega_s is None:
            raise ValueError(
                f"{tag}: order=None 时 rl_db/rs_db/omega_s 三者必填（阶数"
                "估计路径），得到 "
                f"{rl_db!r}/{rs_db!r}/{omega_s!r}")
        rl = _num(rl_db, f"{tag}.rl_db")
        rs = _num(rs_db, f"{tag}.rs_db")
        ws = _num(omega_s, f"{tag}.omega_s")
        if rl <= 0.0:
            raise ValueError(f"{tag}: rl_db 必须 >0，得到 {rl_db!r}")
        if rs <= rl:
            raise ValueError(
                f"{tag}: rs_db 必须 >rl_db（阻带规格严于带缘），得到 "
                f"rl={rl!r}, rs={rs!r}")
        if ws <= 1.0:
            raise ValueError(
                f"{tag}: omega_s 必须 >1（阻带在带缘之外），得到 {omega_s!r}")
        ratio = (10.0 ** (rs / 10.0) - 1.0) / (10.0 ** (rl / 10.0) - 1.0)
        n_est = math.log10(ratio) / (2.0 * math.log10(ws))
        n = max(1, math.ceil(n_est - 1e-12))
        # RL<3.01 dB：原型 3.01 dB 点预畸变到 ωc（带缘 ω=1 恰满足 RL）
        if rl < 3.0102999566398121:
            cutoff_wc = (10.0 ** (rl / 10.0) - 1.0) ** (-1.0 / (2.0 * n))
        order_source = "estimated"
    else:
        n = _int(order, f"{tag}.order")
        if not 1 <= n <= 31:
            raise ValueError(
                f"{tag}: order 须 ∈[1,31]（原型阶梯规模守卫），得到 {order!r}")
        order_source = "explicit"

    g_vals = g_maxflat(n)
    # 响应自证：ω=1 处 −3.0103 dB（等端接最平坦定义式）；ωs 处（给出规格
    # 时）梯形 ABCD 回代 vs 10lg(1+ω^{2n}) 多项式双路径互证
    s21_w1_db = _s21_db(_ladder_abcd(g_vals[1:-1], 1.0))
    stop_db: float | None = None
    stop_poly_db: float | None = None
    ws_val: float | None = None
    if rl_db is not None and rs_db is not None and omega_s is not None:
        ws_val = _num(omega_s, f"{tag}.omega_s")
        if ws_val <= 1.0:
            raise ValueError(
                f"{tag}: omega_s 必须 >1（阻带在带缘之外），得到 {omega_s!r}")
    if ws_val is not None or cutoff_wc is not None:
        wc = cutoff_wc if cutoff_wc is not None else 1.0
        w_eff = (ws_val if ws_val is not None else 1.0) / wc
        stop_db = _s21_db(_ladder_abcd(g_vals[1:-1], w_eff))
        stop_poly_db = -10.0 * math.log10(1.0 + w_eff ** (2.0 * n))

    return {
        "order": n,
        "order_source": order_source,
        "g_values": [round(g_v, 12) for g_v in g_vals],
        "g0": 1.0,
        "g_n_plus_1": 1.0,
        "element_rule": (
            "奇位 g=串联电感 L_k=g_k（H·ωc 归一）、偶位 g=并联电容 "
            "C_k=g_k（F·ωc 归一），ωc=1、1Ω 端接；对偶（并 C 首位）同合法"),
        "cutoff_omega_c": None if cutoff_wc is None else round(cutoff_wc, 12),
        "s21_at_band_edge_db": round(s21_w1_db, 9),
        "stopband_atten_db": None if stop_db is None else round(stop_db, 9),
        "stopband_poly_db": (
            None if stop_poly_db is None else round(stop_poly_db, 9)),
        "n_est_raw": None if order_source == "explicit" else round(n_est, 12),
        "note": (
            "最平坦原型 |Γ(ω)|²=1/(1+ω^{2n})：带缘 ω=1 恰 −3.0103dB（"
            "s21_at_band_edge_db 梯形 ABCD 回代自证）；阶数估计闭式=RL/RS/"
            "ωs 双规格解析解（RL<3.01dB 给截止预畸变 ωc，stopband_atten_db"
            " 按 ω_eff=ωs/ωc 回代）；stopband_poly_db=10lg(1+ω_eff^{2n}) "
            "多项式路径（与梯形 ABCD 独立代数路径，rel 一致性测试钉）；"
            "20n dB/dec 带外滚降为渐近档"),
        "source": (
            "Pozar Microwave Engineering §8.2 插损法：最平坦低通原型定义"
            "式、g 值生成式（Table 8.3 最平坦列）与阶数估计闭式（章节级"
            "转引；式号按 #df6-⑬ 不落页码）"),
    }
