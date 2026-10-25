"""终端接负载均匀传输线的输入阻抗/反射系数精确解 CALC 键（aurora_l G1，
2026-10-23）。

一键：line_input_impedance（终端负载 Z_L 经电长度 θ=βl 的无耗线变换后的
输入阻抗 Zin、输入/负载反射系数、驻波比、回损、失配损耗——微波网络最
基本的单线变换闭式；#222 triple-grep 证据：``tan.*βl|电长度输入|terminated``
calc_families 注册面零命中，vswr_convert=纯标量 Γ/VSWR/回损换算无电长度
自由度、stub_tuner=调配拓扑解、microstrip_* 族=几何正反解，均不撞）。

物理口径（#1c/#300 出处纪律；docstring 写死）
--------------------------------------------------------
- 负载反射系数 Γ_L=(Z_L−Z0)/(Z_L+Z0)（Pozar《Microwave Engineering》
  §2.3 传输线一般理论，式级口径）。
- 输入阻抗精确式（sin/cos 形，θ=90° 无 tan 奇点）：
      Zin = Z0·(Z_L·cosθ + j·Z0·sinθ)/(Z0·cosθ + j·Z_L·sinθ)
  （Pozar §2.4 端接线的输入阻抗；tan 形 Zin=Z0(Z_L+jZ0tanθ)/(Z0+jZ_Ltanθ)
  在 θ=90° 数值奇异，本键取同值 sin/cos 形——极限恒等测试钉）。
- 输入反射系数 Γ_in=Γ_L·e^{−j2θ}（无耗线仅相位旋转，模不变）——与
  (Zin−Z0)/(Zin+Z0) 双路径恒等（独立代数路径互证，rel≤1e-12 测试钉）。
- 驻波比 VSWR=(1+|Γ|)/(1−|Γ|)、回损 RL=−20lg|Γ|、失配损耗
  −10lg(1−|Γ|²)（§2.3 同族标量面）。
- 经典极限锚（测试钉）：θ=90° → Zin=Z0²/Z_L；θ=180° → Zin=Z_L；
  Z_L=0 → Zin=jZ0tanθ；|Γ|=1 纯电抗负载 → VSWR/回损无定义，vswr/
  return_loss_db 记 null（JSON 契约禁 Inf，vswr_convert 同口径）。

守卫：z0_ohm>0；rl_ohm≥0（有源负 |Γ|>1 驻波面无定义，显式拒绝）；
xl_ohm 有限任意；theta_deg 有限任意实数（无耗线半波长周期，内部按
θ mod 180° 归一——cos/sin 精确式对任意 θ 良态，归一只为输出可读）；
bool 入参显式拒收（df7+⑯）。

接口：纯函数零 IO；math 为主；复数按服务 [re,im] 约定出双字段；无
``__all__``（公开 API 快照口径）。

出处：
- line_input_impedance：端接线输入阻抗/反射系数精确式（Pozar
  Microwave Engineering §2.3–§2.4 传输线理论与端接线分析——章节级
  转引通行形态；sin/cos 奇异消除形为等价代数变形）。
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


@register_calculator(
    "line_input_impedance",
    "端接线输入阻抗精确解：Z_L 经电长度 θ=βl 无耗线"
    "变换 Zin=Z0(Z_L cosθ+jZ0 sinθ)/(Z0 cosθ+jZ_L sinθ)（sin/cos 形无 "
    "tan 奇点）+Γ_L=(Z_L−Z0)/(Z_L+Z0)、Γ_in=Γ_L e^{−j2θ}（模不变双路径"
    "恒等互证）+VSWR/回损/失配损耗（|Γ|=1 纯电抗负载 VSWR/回损记 null）"
    "；经典极限 θ=90°→Z0²/Z_L、θ=180°→Z_L、短路→jZ0tanθ。纯标量驻波换"
    "算=vswr_convert、调配解=stub_tuner_single、微带几何=microstrip_"
    "analysis 不撞",
    (("rl_ohm", "float Ω 负载电阻实部（≥0；有源负阻 |Γ|>1 显式拒绝）"),
     ("xl_ohm", "float Ω 负载电抗（有限任意，可负）"),
     ("z0_ohm", "float Ω 线特性阻抗（>0，缺省 50）"),
     ("theta_deg", "float deg 线电长度 βl（有限任意；输出按 mod 180° 归"
      "一，半波长周期）")),
    required=("rl_ohm", "xl_ohm", "theta_deg"),
)
def line_input_impedance(rl_ohm: float, xl_ohm: float,
                         theta_deg: float,
                         z0_ohm: float = 50.0) -> dict[str, Any]:
    """端接负载均匀无耗线的输入阻抗/反射系数精确解（sin/cos 形）。"""
    tag = "line_input_impedance"
    rl = _num(rl_ohm, f"{tag}.rl_ohm")
    xl = _num(xl_ohm, f"{tag}.xl_ohm")
    theta_raw = _num(theta_deg, f"{tag}.theta_deg")
    z0 = _num(z0_ohm, f"{tag}.z0_ohm")
    if rl < 0.0:
        raise ValueError(
            f"{tag}: rl_ohm 必须 ≥0（有源负阻 |Γ|>1 驻波面无定义），得到 "
            f"{rl_ohm!r}")
    if z0 <= 0.0:
        raise ValueError(f"{tag}: z0_ohm 必须 >0，得到 {z0_ohm!r}")
    # 半波长周期归一（sin/cos 精确式本对任意 θ 良态；归一只为输出可读且
    # 使 theta_deg 落 [0,180) 标准口径）
    theta = theta_raw % 180.0

    z_l = complex(rl, xl)
    th = math.radians(theta)
    cos_t = math.cos(th)
    sin_t = math.sin(th)
    z_in = z0 * (z_l * cos_t + 1j * z0 * sin_t) / (z0 * cos_t + 1j * z_l * sin_t)

    g_l = (z_l - z0) / (z_l + z0)
    g_in_path2 = (z_in - z0) / (z_in + z0)
    g_in_path1 = g_l * complex(math.cos(-2.0 * th), math.sin(-2.0 * th))
    # 双路径恒等互证（Γ_L e^{-j2θ} vs (Zin−Z0)/(Zin+Z0)——独立代数路径）
    ident_rel = abs(g_in_path1 - g_in_path2) / max(abs(g_in_path2), 1e-300)

    g_mag = abs(g_in_path2)
    if g_mag >= 1.0 - 1e-12:
        vswr: float | None = None
        rl_db: float | None = None  # |Γ|=1 回损 0/无穷语义：纯电抗负载记 null
    else:
        vswr = (1.0 + g_mag) / (1.0 - g_mag)
        rl_db = -20.0 * math.log10(g_mag) if g_mag > 0.0 else None
    mismatch_db = (
        -10.0 * math.log10(max(1.0 - g_mag * g_mag, 1e-300))
        if g_mag < 1.0 - 1e-15 else None)

    return {
        "rl_ohm": rl,
        "xl_ohm": xl,
        "z0_ohm": z0,
        "theta_deg": round(theta, 12),
        "theta_deg_raw": round(theta_raw, 12),
        "z_load": [round(z_l.real, 15), round(z_l.imag, 15)],
        "z_in": [round(z_in.real, 12), round(z_in.imag, 12)],
        "gamma_load": [round(g_l.real, 15), round(g_l.imag, 15)],
        "gamma_in": [round(g_in_path2.real, 12), round(g_in_path2.imag, 12)],
        "gamma_in_mag": round(g_mag, 15),
        "vswr": None if vswr is None else round(vswr, 9),
        "return_loss_db": None if rl_db is None else round(rl_db, 9),
        "mismatch_loss_db": (
            None if mismatch_db is None else round(mismatch_db, 9)),
        "gamma_phase_rotation_identity_rel_dev": round(ident_rel, 18),
        "note": (
            "无耗线变换精确式（sin/cos 形，θ=90° 无 tan 奇点）；Γ_in=Γ_L·"
            "e^{−j2θ} 模不变（gamma_phase_rotation_identity_rel_dev≈机器"
            "精度，双路径恒等式构造级互证）；|Γ|=1 纯电抗负载（rl=0）"
            "VSWR/回损无定义记 null；θ 按 mod 180° 归一（theta_deg_raw 留"
            "原值，半波长周期恒等）；λ/4→Zin=Z0²/Z_L、λ/2→Zin=Z_L、短路→"
            "jZ0tanθ 为经典极限（测试钉）"),
        "source": (
            "Pozar Microwave Engineering §2.3–§2.4 传输线理论：端接线输入"
            "阻抗与反射系数精确式（章节级转引；sin/cos 形为 tan 形的等价"
            "奇异消除变形）"),
    }
