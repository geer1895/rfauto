"""EC-3 导体表面阻抗 CALC 注册面薄包装键（aurora_j W4-S12，2026-10-23）。

一键：conductor_surface_impedance（趋肤深度 δ/表面电阻 Rs/复表面阻抗
Zs=Rs(1+j)——A1 席位键；候选定稿 内部证据档 §1.3，
EC-3 verified 缺口"surface_impedance 注册键面零"收口）。

**薄注册纪律**（polarization_reg/helix_axial_reg 同款）：物理公式单源在
``rfauto.core.conductor_loss``（D2 导体损耗口径 §1.7.1：skin_depth/
smooth_surface_resistance 纯函数在库未注册——wg_fundamental.py Rs 注记
"留调用方自算"的正式面补口）——本模块**只注册不实现**，零公式复制
（#116 死副本教训）。wrapper 是纯委托：入参收敛透传 + dict 字段映射，
数值量只做 round 展示；Zs=Rs(1+j) 为良导体复表面阻抗定义式装配
（实部=虚部=Rs，无独立公式复制）。

#222 triple-grep 证据（2026-10-23 本席开工实测）
--------------------------------------------------------
``surface_impedance`` calc_families 注册键面零命中（core/conductor_loss
的 layered_surface_impedance=分层导体 F-J.1 闭式、skrf_surface_impedance_
crosscheck=第三来源裁判，均未注册；wg_te10_attenuation/circular_* 的
Rs=√(πfμ/σ) 均为函数体内消费量非键面）；``conductor_surface_impedance``
src/tests/scripts 三面零命中。

与既有面边界
--------------------------------------------------------
- layered_surface_impedance/enig_stack（core 未注册）=分层导体镀层级联
  闭式（多材质叠层语境）；本键=单一良导体半无限基准面（δ/Rs/Zs 三量）。
- wg_te10_attenuation/microstrip_attenuation=把 Rs 消费成衰减率的面；
  superconductor_rs=超导两流体 Rs（另一物理机制域）——均不并入。
- 微带 HJ 档 microstrip_extra 已复用 skin_depth 单源（同仓消费先例）。

数值锚（#118 独立路线，tests/unit/test_w4s12_wg_conductor_keys.py）：
σ=5.8e7（铜）@1GHz 教科书值逐位锚（δ≈2.0898µm/Rs≈8.250mΩ 档）+
Rs·σ·δ=1 恒等式构造级残差 + μr 标度（μr×4 → δ×2、Rs×2 幂律精确）。

守卫：透传 core 单源校验（f/sigma/mu_r 均 >0 且有限）；bool 入参显式
拒收（df7+⑯——core _finite 不拒 bool 的本族自守，polarization_reg
_deg2rad 先例）。

接口：纯函数零 IO；全部返回 JSON 可序列化结构（复数按服务 [re,im] 约
定出 zs_complex）；无 ``__all__``（公开 API 快照口径）。

出处（见 rfauto.core.conductor_loss 模块 docstring §1：D. M. Pozar,
Microwave Engineering, 4th ed., §1.7.1 趋肤深度与表面电阻；本键为薄注
册包装，公式零复制）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.conductor_loss import (
    skin_depth,
    smooth_surface_resistance,
)

from .registry import register_calculator

_SOURCE = (
    "出处见 rfauto.core.conductor_loss 模块 docstring §1（Pozar Microwave "
    "Engineering 4th ed. §1.7.1 趋肤深度 δ=√(2/(ωμσ)) 与表面电阻 "
    "Rs=√(ωμ/(2σ))=√(πfμ/σ)；本键为薄注册包装，公式零复制）"
)


def _num(value: Any, name: str) -> float:
    """有限数守卫（bool 显式拒收——df7+⑯，core _finite 不拒 bool 的自守）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值，收到 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} 必须为有限数，收到 {value!r}")
    return out


@register_calculator(
    "conductor_surface_impedance",
    "良导体表面阻抗基准面：趋肤深度 δ=√(2/(ωμ0μrσ))、表面电阻 "
    "Rs=√(πfμ/σ)=1/(σδ)、复表面阻抗 Zs=Rs(1+j)（良导体 45° 口径，[re,im]"
    " 服务复数约定）；薄注册单源复用 core/conductor_loss；μr 幂律标度"
    "（μr×4 → δ×2、Rs×2）；分层镀层/超导/衰减率消费面不并入",
    (("f_hz", "float Hz 工作频率（>0）"),
     ("sigma_s_per_m", "float S/m 导体电导率（>0；铜 5.8e7）"),
     ("mu_r", "float 相对磁导率（>0，缺省 1；铁磁材料微波 μr 取值注意"
      "弛豫，如实注记不猜）")),
    required=("f_hz", "sigma_s_per_m"),
)
def conductor_surface_impedance(f_hz: float, sigma_s_per_m: float,
                                mu_r: float = 1.0) -> dict[str, Any]:
    """薄委托 core/conductor_loss 单源（δ/Rs 透传 + Zs=Rs(1+j) 装配）。"""
    freq = _num(f_hz, "f_hz")
    sigma = _num(sigma_s_per_m, "sigma_s_per_m")
    mur = _num(mu_r, "mu_r")
    delta_m = skin_depth(freq, sigma, mur)          # 单源：Pozar §1.7.1
    rs_ohm_per_sq = smooth_surface_resistance(freq, sigma, mur)  # 同单源
    # 良导体复表面阻抗定义式装配：Zs=Rs·(1+j)（实部=虚部=Rs）
    zs_re = rs_ohm_per_sq
    zs_im = rs_ohm_per_sq
    return {
        "f_hz": freq,
        "sigma_s_per_m": sigma,
        "mu_r": mur,
        "delta_m": round(delta_m, 15),
        "rs_ohm_per_sq": round(rs_ohm_per_sq, 15),
        "zs_complex": [round(zs_re, 15), round(zs_im, 15)],
        "zs_mag_ohm": round(math.hypot(rs_ohm_per_sq, rs_ohm_per_sq), 15),
        "skin_depth_um": round(delta_m * 1e6, 9),
        "note": (
            "薄注册包装（物理单源 rfauto.core.conductor_loss，公式零复"
            "制）：良导体半无限基准面——Zs=Rs(1+j)（实部=虚部=Rs，45° "
            "感抗口径，[re,im] 服务复数约定）；Rs·σ·δ=1 恒等式构造级自"
            "证；μr>1 时微波铁磁 μr 弛豫取值需实测（本键如实按入参幂律"
            "标度：δ∝1/√μr、Rs∝√μr）；分层镀层（layered_surface_"
            "impedance 面）、超导（superconductor_rs 两流体域）、衰减率"
            "消费（wg_te10_attenuation/microstrip_attenuation）不并入"),
        "source": _SOURCE,
    }
