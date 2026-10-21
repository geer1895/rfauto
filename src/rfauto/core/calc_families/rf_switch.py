"""射频开关件面（架构批 W2-S6 席域，R2_core_tier3 §③ D8 立项）。

三键：pin_switch_s2p（PIN 串/并联元件二态 S 参数+cutoff 品质因数）/
rf_switch_spdt_quarter_wave（λ/4 并联二极管 SPDT 频响=开关带宽语义）/
rf_switch_matrix_path（开关链二态预算：插损/隔离 dB 可加性+失配纹波界）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- **PIN 元件两态模型**（教科书 PIN 开关：导通态=串联电阻 R_on、截止态
  =并联电容 C_off，封装寄生不计的一阶口径）：
  - 串联拓扑：导通（R_on）=直通态 S21=2Z0/(2Z0+R_on)、S11=R_on/(2Z0+
    R_on)；截止（C_off）=隔离态 S21=2Z0/(2Z0+1/jωC_off)——低频渐近
    |S21|→2Z0ωC_off（隔离 ≈20log10(1/(2Z0ωC_off))）。
  - 并联拓扑：导通（R_on 对地）=隔离态 S21=2/(2+Z0/R_on)；截止（C_off
    对地）=直通态 S21=2/(2+jωC_off·Z0)——小 C 渐近插损 ≈(ωC·Z0/2)²
    （dB 域二阶小量）。
  - **cutoff 品质因数**：f_c=1/(2π·R_on·C_off)（串联口径开关截止频率，
    教科书 FOM；f_c↑ 侧重 R_on 小、f_c↑ 侧同 C_off 隔离更好——R_on·C_off
    乘积单值标度，测试按乘积标度恒等钉）。
- **λ/4 并联二极管 SPDT**（经典四分之一波长开关线）：公共结点 J，各臂
  =并联 PIN 管 + λ/4 Z0 线至掷端口。选中臂（二极管截止 C_off）：管处
  高阻、λ/4 线输入阻抗≈Z0=匹配；非选中臂（二极管导通 R_on）：管近短路
  、λ/4 变换 Z_in=Z0²/Z_L≈Z0²/R_on 高阻挂结点→隔离。ABCD 级联闭式：

      Z_in(线)=Z0(Z_L+jZ0·tanθ)/(Z0+jZ_L·tanθ)，θ=2πf·√εeff·L/c

  偏离 f0 时 tanθ 失谐→隔离/匹配退化（**开关带宽语义**：λ/4 线窄带
  性，测试钉"偏 f0/2 隔离退化"单调向）。并联管在掷端口端与端口 Z0 并联
  计入（Z_L=R_on‖Z0 / C_off‖Z0 精确）。
- **开关链二态预算**：N 级串联开关路径，直通态插损 dB 严格可加
  （ΣIL_dB——dB 域级联定义恒等式）；路径隔离=各离选支路隔离 dB 可加。
  失配纹波界（教科书级联口径）：相邻端口对 γ_i、γ_{i+1} 交互最坏
  20log10(1+γ_iγ_{i+1}) 逐对叠加。**吸收式 vs 反射式**：反射式开关
  离选臂把功率反射回源（二阶再反射项本键不计，如实注记）；吸收式
  （离选臂内置 Z0 端接）无再反射——纹波界对吸收式为严格界，对反射式
  为一阶近似（flag 如实透传）。

边界防撞（#222 triple-grep，2026-10-18 实测）
--------------------------------------------------------
- switch_pa_efficiency=开关**模 PA 效率**（D/E 类调制域）、phase_shifter
  switched_line/switched_network=**移相网络**（态间相位差面）、
  pa_arch pin_diode_limiter=**限幅器**（功率非线性两态）、
  step_attenuator_design=步进衰减（电阻网络）——本族只做 **SPnT 开关
  器件级**（插损/隔离/带宽三态口径）。
- rf 矩阵列换面（N×M 交叉点拓扑）不在本层——本键按路径元件列表面
  消费（可加性口径与拓扑无关）。

出处
----
- 教科书 PIN 开关两态模型与 f_c=1/(2πR_on·C_off) FOM：R. W. 潘/M.
  White 分类口径（Pozar Ch.12 开关器件节；二级转引）。
- λ/4 并联二极管 SPDT=经典 quarter-wave switched line（Pozar Ch.12 /
  微波控制器件文献二级转引）。
- 级联失配纹波界 20log10(1+γ_iγ_j) 教科书口径（微波测量/级联匹配
  文献二级转引）。

守卫：r_on_ohm>0、c_off_f>0、z0_ohm>0、频率>0；topology∈{series,shunt}；
elements 表逐项 il_db/iso_db ≥0 且有限；γ∈[0,1)；越界一律显式
ValueError。

出处（Pozar《Microwave Engineering》Ch.12 控制器件节）：
- pin_switch_s2p：PIN 串/并联元件二态 S 参数+cutoff 品质因数
  f_c=1/(2πR_onC_off)（Pozar Ch.12；R. White 分类口径二级转引）。
- rf_switch_spdt_quarter_wave：λ/4 并联二极管 SPDT=经典 quarter-wave
  switched line（Pozar Ch.12/微波控制器件文献二级转引；结点分析/ABCD
  闭式=均匀线标准式落地，f0 极限恒等测试钉）。
- rf_switch_matrix_path：开关链二态预算插损/隔离可加性+失配纹波界
  （微波测量文献二级转引；恒等式面测试侧独立互证）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator
from .thermal import _finite

__all__ = [
    "pin_switch_s2p",
    "rf_switch_matrix_path",
    "rf_switch_spdt_quarter_wave",
]

_TOPOLOGIES = ("series", "shunt")


def _cmag(z: complex) -> float:
    return math.hypot(z.real, z.imag)


# ─── 键 1：pin_switch_s2p（PIN 元件二态 S 参数 + cutoff FOM）────────────────

@register_calculator(
    "pin_switch_s2p",
    "PIN 开关元件二态 S 参数：导通态（串联电阻 R_on）/截止态（并联电容 "
    "C_off）一阶模型（封装寄生不计，如实注记）。串联拓扑：导通=直通 "
    "S21=2Z0/(2Z0+R_on)、截止=隔离 S21=2Z0/(2Z0+1/jωC_off)（低频渐近 "
    "≈2Z0ωC_off）；并联拓扑：导通=隔离 S21=2/(2+Z0/R_on)、截止=直通 "
    "S21=2/(2+jωC_off·Z0)。cutoff 品质因数 f_c=1/(2π·R_on·C_off)（R_on·"
    "C_off 乘积单值标度锚）。锚：R_on→0/C_off→0 理想极限（插损 0/隔离"
    "∞）、公式测试侧独立重算、乘积标度恒等",
    (("topology", "str 'series'|'shunt'（封闭集合）"),
     ("r_on_ohm", "float Ω 导通态电阻（>0）"),
     ("c_off_f", "float F 截止态电容（>0；fF 量级典型 0.05–0.5pF 以器件"
      "手册为准）"),
     ("freq_ghz", "array GHz 频率轴（>0）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）")),
    required=("topology", "r_on_ohm", "c_off_f", "freq_ghz"),
)
def pin_switch_s2p(topology: str, r_on_ohm: float, c_off_f: float,
                   freq_ghz: list, z0_ohm: float = 50.0) -> dict[str, Any]:
    topo = str(topology).strip().lower()
    if topo not in _TOPOLOGIES:
        raise ValueError(
            f"pin_switch_s2p: topology 须 {'|'.join(_TOPOLOGIES)}，得到 "
            f"{topology!r}")
    r_on = _finite(r_on_ohm, "r_on_ohm")
    c_off = _finite(c_off_f, "c_off_f")
    z0 = _finite(z0_ohm, "z0_ohm")
    if r_on <= 0.0:
        raise ValueError(f"pin_switch_s2p: r_on_ohm 必须 >0，得到 {r_on!r}")
    if c_off <= 0.0:
        raise ValueError(f"pin_switch_s2p: c_off_f 必须 >0，得到 {c_off!r}")
    if z0 <= 0.0:
        raise ValueError(f"pin_switch_s2p: z0_ohm 必须 >0，得到 {z0!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("pin_switch_s2p: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("pin_switch_s2p: 频率须 >0")

    fc_fom = 1.0 / (2.0 * math.pi * r_on * c_off)
    # 导通态（纯阻性，频率无关）：串联 S21=2Z0/(2Z0+R_on)；并联（导纳
    # 1/R_on 对地）S21=2/(2+Z0/R_on)
    if topo == "series":
        s21_on = 2.0 * z0 / (2.0 * z0 + r_on)
        s11_on = r_on / (2.0 * z0 + r_on)
    else:
        s21_on = 2.0 / (2.0 + z0 / r_on)
        s11_on = (z0 / r_on) / (2.0 + z0 / r_on)
    il_on_db = -20.0 * math.log10(max(s21_on, 1e-300))
    rl_on_db = -20.0 * math.log10(max(s11_on, 1e-300))
    # 截止态（容性，逐频）：串联 Z=1/jωC；并联 Y=jωC
    iso_db: list[float] = []
    rl_off_db: list[float] = []
    s21_off_mag: list[float] = []
    for f in freqs:
        w = 2.0 * math.pi * f * 1e9
        if topo == "series":
            z_off = complex(0.0, -1.0 / (w * c_off))
            s21 = 2.0 * z0 / (2.0 * z0 + z_off)
            s11 = z_off / (2.0 * z0 + z_off)
        else:
            y = complex(0.0, w * c_off)
            s21 = 2.0 / (2.0 + y * z0)
            s11 = (-y * z0) / (2.0 + y * z0)
        s21_off_mag.append(_cmag(s21))
        iso_db.append(-20.0 * math.log10(max(_cmag(s21), 1e-300)))
        rl_off_db.append(-20.0 * math.log10(max(_cmag(s11), 1e-300)))
    return {
        "topology": topo,
        "r_on_ohm": r_on,
        "c_off_f": c_off,
        "z0_ohm": z0,
        "fc_fom_hz": round(fc_fom, 12),
        "state_on": "through" if topo == "series" else "isolation",
        "state_off": "isolation" if topo == "series" else "through",
        # 角色化输出（拓扑决定态→角色映射）：插损面/隔离面各归其位
        "il_through_db": (round(il_on_db, 15) if topo == "series" else
                          [round(v, 15) for v in iso_db]),
        "isolation_db": (round(il_on_db, 15) if topo == "shunt" else
                         [round(v, 15) for v in iso_db]),
        "return_loss_on_db": round(rl_on_db, 15),
        "freq_ghz": freqs,
        "s21_on_mag": round(s21_on, 18),
        "s21_off_mag": [round(v, 18) for v in s21_off_mag],
        "rl_off_db": [round(v, 15) for v in rl_off_db],
        "note": (
            "一阶模型只含 R_on/C_off 本征值——封装引线电感/体电阻/焊盘"
            "寄生不计（毫米波段实测劣化以厂家 S 参数为准，如实注记）；"
            "串联拓扑导通=直通、并联拓扑导通=隔离（拓扑语义，state_on/"
            "state_off 写死，il_through_db/isolation_db 按角色归位：串联"
            "为标量+逐频列表、并联为逐频列表+标量）；f_c 为教科书 FOM"
            "（R_on·C_off 乘积单值标度），逐频精确式不做渐近替代"),
        "source": (
            "PIN 两态教科书模型（导通 R_on/截止 C_off）与 "
            "f_c=1/(2πR_onC_off) 品质因数=Pozar Microwave Engineering "
            "Ch.12 开关器件节口径（二级转引）"),
    }


# ─── 键 2：rf_switch_spdt_quarter_wave（λ/4 并联二极管 SPDT 频响）───────────

def _arm_abcd(z0: float, y_diode: complex, theta: float) -> tuple[float, complex,
                                                                   complex, complex]:
    """单臂 ABCD（从公共结点到掷端口）：λ/4 线 × 掷端并联二极管。

    [line: cosθ, jZ0sinθ; jsinθ/Z0, cosθ] × [shunt Y_d: 1,0; Y_d,1]
    隔离机制=导通二极管直接短路掷口（A+jZ0sinθ·Y_d→∞ → 传输系数→0），
    λ/4 同时把该近短路变换为结点处高阻（不加载公共结点）——双重效应。
    """
    s = math.sin(theta)
    c = math.cos(theta)
    a = c + 1j * z0 * s * y_diode
    b = 1j * z0 * s
    cc = 1j * s / z0 + c * y_diode
    d = c
    return a, b, cc, d


def _spdt_row(z0: float, r_on: float, c_off: float, theta: float,
              omega: float) -> tuple[complex, complex, complex]:
    """λ/4 SPDT 结点分析（激励公共口 a1=1）→ (b1, b2, b3)。

    结点 KCL（导纳归一 Z0）：V_J/a1√Z0 口径 → v_j=2/(1+z0/Z_A+z0/Z_B)
    （公共口 Z0 源阻抗臂归一为 1）；掷口电压传输 t_i=1/(A_i+B_i/Z0)；
    b1=v_j−1、b2/b3=v_j·t_on/t_off（掷口 Z0 端接 a=0）。
    """
    y_on = 1j * omega * c_off              # 选中臂：截止电容导纳
    y_off = 1.0 / r_on                     # 非选中臂：导通电阻
    a_on, b_on, c_on, d_on = _arm_abcd(z0, y_on, theta)
    a_off, b_off, c_off_a, d_off = _arm_abcd(z0, y_off, theta)
    z_in_on = (a_on * z0 + b_on) / (c_on * z0 + d_on)
    z_in_off = (a_off * z0 + b_off) / (c_off_a * z0 + d_off)
    v_j = 2.0 / (1.0 + z0 / z_in_on + z0 / z_in_off)
    t_on = 1.0 / (a_on + b_on / z0)
    t_off = 1.0 / (a_off + b_off / z0)
    return v_j - 1.0, v_j * t_on, v_j * t_off


@register_calculator(
    "rf_switch_spdt_quarter_wave",
    "λ/4 SPDT 开关频响：经典 quarter-wave switched line（公共结"
    "点两臂各=并联 PIN+λ/4 Z0 线）。选中臂（截止 C_off）匹配直通；非选中"
    "臂（导通 R_on）经 λ/4 变换 Z_in=Z0²/Z_L≈Z0²/R_on 高阻挂结点→隔离。"
    "ABCD 级联闭式（Z_in=Z0(Z_L+jZ0tanθ)/(Z0+jZ_Ltanθ)），偏离 f0 失谐→"
    "隔离/匹配退化=**开关带宽语义**（λ/4 线窄带性）。掷端二极管与端口 "
    "Z0 并联精确计入（R_on‖Z0 / C_off‖Z0）。锚：f0 处 R_on→0/C_off→0 "
    "理想极限（IL→0/隔离→∞）、f0 隔离测试侧独立重算、偏 f0 单调退化",
    (("f0_ghz", "float GHz 中心频率（λ/4 设计频率，>0）"),
     ("r_on_ohm", "float Ω 导通态电阻（>0）"),
     ("c_off_f", "float F 截止态电容（>0）"),
     ("freq_ghz", "array GHz 频率轴（>0，f0 附近扫描看带宽语义）"),
     ("z0_ohm", "float Ω 系统阻抗（>0，缺省 50）"),
     ("er_eff", "float 臂线有效介电常数（≥1，缺省 1=空气线理想档；微带"
      "实测按 forward_z0/εeff 给）")),
    required=("f0_ghz", "r_on_ohm", "c_off_f", "freq_ghz"),
)
def rf_switch_spdt_quarter_wave(f0_ghz: float, r_on_ohm: float,
                                c_off_f: float, freq_ghz: list,
                                z0_ohm: float = 50.0,
                                er_eff: float = 1.0) -> dict[str, Any]:
    f0 = _finite(f0_ghz, "f0_ghz")
    if f0 <= 0.0:
        raise ValueError(
            f"rf_switch_spdt_quarter_wave: f0_ghz 必须 >0，得到 {f0!r}")
    r_on = _finite(r_on_ohm, "r_on_ohm")
    c_off = _finite(c_off_f, "c_off_f")
    z0 = _finite(z0_ohm, "z0_ohm")
    er = _finite(er_eff, "er_eff")
    if r_on <= 0.0 or c_off <= 0.0 or z0 <= 0.0:
        raise ValueError(
            "rf_switch_spdt_quarter_wave: r_on_ohm/c_off_f/z0_ohm 必须 >0")
    if er < 1.0:
        raise ValueError(
            f"rf_switch_spdt_quarter_wave: er_eff 须 ≥1，得到 {er!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("rf_switch_spdt_quarter_wave: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("rf_switch_spdt_quarter_wave: 频率须 >0")
    # λ/4 物理长（按 er_eff 同步 TEM 口径）
    c0_mm_ghz = 299.792458
    arm_len_mm = c0_mm_ghz / (4.0 * f0 * math.sqrt(er))
    s11_db: list[float] = []
    il_db: list[float] = []
    iso_db: list[float] = []
    f0_row = 0
    f0_dev = float("inf")
    for idx, f in enumerate(freqs):
        theta = math.pi * f * math.sqrt(er) / (2.0 * f0)  # f=f0 → π/2
        omega = 2.0 * math.pi * f * 1e9
        b1, b2, b3 = _spdt_row(z0, r_on, c_off, theta, omega)
        s11_db.append(-20.0 * math.log10(max(_cmag(b1), 1e-300)))
        il_db.append(-20.0 * math.log10(max(_cmag(b2), 1e-300)))
        iso_db.append(-20.0 * math.log10(max(_cmag(b3), 1e-300)))
        dev = abs(f - f0)
        if dev < f0_dev:
            f0_dev = dev
            f0_row = idx
    return {
        "f0_ghz": f0,
        "r_on_ohm": r_on,
        "c_off_f": c_off,
        "z0_ohm": z0,
        "er_eff": er,
        "arm_len_mm": round(arm_len_mm, 15),
        "freq_ghz": freqs,
        "s11_db": [round(v, 15) for v in s11_db],
        "il_db": [round(v, 15) for v in il_db],
        "iso_db": [round(v, 15) for v in iso_db],
        "iso_at_f0_db": iso_db[f0_row],
        "il_at_f0_db": il_db[f0_row],
        "note": (
            "三口结点分析口径：b3=非选中掷口泄漏（隔离主口径）；隔离机制="
            "导通二极管短路掷口（传输系数→0）+λ/4 把近短路变换为结点高阻"
            "（不加载公共结点）双重效应；λ/4 线为窄带机构——偏离 f0 失谐"
            "隔离/回损退化（开关带宽语义），宽带有塞 SPDT 走行波/集总拓扑"
            "不在本层；切换时间常数为器件档（PIN 载流子寿命 µs 级、GaAs "
            "FET ns 级量级，以手册为准，empirical 如实不产数字）"),
        "source": (
            "λ/4 并联二极管 SPDT=quarter-wave switched line 经典拓扑"
            "（Pozar Microwave Engineering Ch.12 控制器件节，二级转引）；"
            "结点分析/ABCD 闭式为本席按均匀线标准式落地（f0 极限 "
            "iso→20log10(Z0/R_on) 渐近可解析复核，测试侧独立重算）"),
    }


# ─── 键 3：rf_switch_matrix_path（开关链二态预算）───────────────────────────

@register_calculator(
    "rf_switch_matrix_path",
    "开关链二态预算：N 级串联开关路径——直通态插损 dB 严格可加 "
    "ΣIL_dB（dB 域级联定义恒等式）、路径隔离=离选支路隔离 dB 可加 "
    "ΣISO_dB；失配纹波界（教科书级联口径）相邻端口对 20log10(1+γ_i·"
    "γ_{i+1}) 逐对叠加（吸收式开关=严格界、反射式=一阶近似如实注记）；"
    "SPnT 扇出不加功分损耗（开关非功分器，10log10N 不适用恒等注记）。"
    "锚：N=1 退化恒等、可加性逐位、纹波界独立重算",
    (("elements", "list[dict] 路径开关级列表（逐项 il_db/iso_db ≥0、"
      "gamma 可选 ∈[0,1)；空表=直通零损恒等档）"),
     ("absorptive", "bool 吸收式开关（离选臂内置端接；缺省 False=反射式"
      "——纹波界语义差异随 note 如实透传）")),
    required=("elements",),
)
def rf_switch_matrix_path(elements: list,
                          absorptive: bool = False) -> dict[str, Any]:
    if not isinstance(elements, list):
        raise ValueError(
            f"rf_switch_matrix_path: elements 须为 list，得到 {type(elements)!r}")
    total_il = 0.0
    total_iso = 0.0
    gammas: list[float] = []
    for idx, el in enumerate(elements):
        if not isinstance(el, dict):
            raise ValueError(
                f"rf_switch_matrix_path: elements[{idx}] 须为 dict，得到 "
                f"{type(el)!r}")
        il = _finite(el.get("il_db", 0.0), f"elements[{idx}].il_db")
        iso = _finite(el.get("iso_db", 0.0), f"elements[{idx}].iso_db")
        if il < 0.0 or iso < 0.0:
            raise ValueError(
                f"rf_switch_matrix_path: elements[{idx}] il_db/iso_db 必须 "
                f"≥0，得到 ({il!r}, {iso!r})")
        total_il += il
        total_iso += iso
        g = el.get("gamma")
        if g is None:
            # 缺省由 IL/RL 反推：γ≈10^(−IL_dB/20)（回损缺省口径，如实注记）
            g = 10.0 ** (-il / 20.0)
        g = _finite(g, f"elements[{idx}].gamma")
        if not 0.0 <= g < 1.0:
            raise ValueError(
                f"rf_switch_matrix_path: elements[{idx}].gamma 须 ∈[0,1)，"
                f"得到 {g!r}")
        gammas.append(g)
    # 失配纹波界：相邻端口对 20log10(1+γ_iγ_{i+1})
    ripple = 0.0
    for i in range(len(gammas) - 1):
        ripple += 20.0 * math.log10(1.0 + gammas[i] * gammas[i + 1])
    n = len(elements)
    return {
        "n_elements": n,
        "absorptive": bool(absorptive),
        "total_il_db": round(total_il, 15),
        "total_iso_db": round(total_iso, 15),
        "mismatch_ripple_bound_db": round(ripple, 15),
        "worst_case_il_db": round(total_il + ripple, 15),
        "gammas": [round(g, 18) for g in gammas],
        "note": (
            "dB 可加性为级联定义恒等式（N=1 退化恒等、倍程双倍恒等）；"
            "gamma 缺省按 IL 反推（γ=10^(−IL/20) 回损口径，显式 gamma "
            "优先）；纹波界=相邻对 20log10(1+γγ) 教科书口径——吸收式"
            "（离选臂内置端接无再反射）为严格界、反射式为一阶近似"
            "（二阶再反射未计，如实注记）；SPnT 扇出无 10log10N 功分项"
            "（开关选通非功分器）；交叉点矩阵隔离=行+列两支路隔离相加"
            "（本键 elements 按路径消费，拓扑无关）"),
        "source": (
            "dB 级联可加性与相邻对失配纹波界 20log10(1+γ_iγ_j)=教科书"
            "级联匹配口径（微波测量文献二级转引）；恒等式面测试侧独立"
            "重算"),
    }
