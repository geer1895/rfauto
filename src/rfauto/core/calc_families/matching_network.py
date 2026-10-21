"""L 节匹配网络键（架构批 W1-K1 内核第五梯队批 1，R2_core_tier5 §③ 1）。

提升核：消费 core/matching.py::synthesize_l_match（C14 锚现代入口——
response 显式声明滤波响应型、LCElement kind/role/value 显式、元件按负载端
→源端排布、f0 共轭匹配闭式构造解精确成立）。遗留入口
synthesize_l_section 的 0bf 工况标签歧义（topology 标签与响应型语义相反）
**不透传键面**——本键只消费现代入口，输出按 LCElement 语义直读，无标签
翻译层。

公式（Pozar《Microwave Engineering》§5.1 两元件集总 L 节；教科书恒等）：
- Q = √(R_big/R_small − 1)（R_big=max(R_s,R_L)、R_small=min，无自由度）；
- 升阻（R_L > R_s）：串联元件电抗 |X_s| = Q·R_small（串在源侧小电阻臂），
  并联元件电抗 |X_p| = R_big/Q（跨负载侧/大电阻侧）；
- 降阻（R_L < R_s）：对偶结构（并联支路跨源侧大电阻臂），同一 Q 闭式
  （synthesize_l_match 内部分支，元件 role/side 由本键显式标注）；
- 响应型两档显式：low_pass = 串 L 并 C / high_pass = 串 C 并 L
  （Pozar Fig. 5.2 拓扑对；两档在 f0 同为精确共轭匹配，带宽行为不同）；
- R_s = R_L 时 Q = 0 退化恒等（无需匹配，bypass 输出、元件空表）。
- f0 处 Z_in = R_s 共轭匹配精确成立（闭式构造解；测试以独立 ABCD 矩阵
  级联回代，与实现内递归路径不同源——#118 双路径）。

适用域：两元件集总 L 节（R_s/R_L 同为正实阻抗的纯电阻口径）；三元件
t_match（集总 π/T 有 q 自由度）、quarter_wave_transformer（λ/4 分布）、
stub_tuner（支节）各有专键，不并入。

锚（#118 独立算术，tests/unit/test_w1k1_core_domains.py）：名义 50→100Ω
@1GHz 低通档 Q=1、|X_s|=50Ω→L=7.9577nH、|X_p|=100Ω→C=1.5915pF 手算逐位
对照；f0 ABCD 回代 Z_in=R_s；高/低通两响应型元件电抗模恒等（对偶）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import register_calculator


def _pos(value: Any, name: str) -> float:
    """正有限数守卫（bool 显式拒收——bool 污染面 df7+⑯）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数值（不接受 bool）")
    out = float(value)
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(f"{name} 必须为正有限数，实际 {value!r}")
    return out


@register_calculator(
    "l_section_match",
    "L节匹配网络闭式：两元件集总 L 节（Pozar §5.1）——Q=√(R大/R小−1)、"
    "|X串|=Q·R小（小电阻臂）、|X并|=R大/Q（跨大电阻侧）；响应型 low_pass="
    "串L并C / high_pass=串C并L 两档显式；f0 共轭匹配闭式构造解精确成立"
    "（输出附 Z_in(f0) 回代残差）；R_s=R_L 退化 bypass 恒等",
    (("z_source_ohm", "float Ω 源侧阻抗（>0）"),
     ("z_load_ohm", "float Ω 负载阻抗（>0）"),
     ("f0_ghz", "float GHz 设计频率（>0）"),
     ("response", "str 滤波响应型 'low_pass'（串L并C）或 'high_pass'（串C并L），"
      "缺省 low_pass")),
    required=("z_source_ohm", "z_load_ohm", "f0_ghz"),
)
def l_section_match(z_source_ohm: float, z_load_ohm: float, f0_ghz: float,
                    response: str = "low_pass") -> dict[str, Any]:
    from rfauto.core.matching import synthesize_l_match

    result = synthesize_l_match(
        _pos(z_source_ohm, "z_source_ohm"),
        _pos(z_load_ohm, "z_load_ohm"),
        _pos(f0_ghz, "f0_ghz"),
        response=str(response).strip().lower(),
    )

    matched = bool(result.elements)
    # 并联支路恒跨大电阻侧（Q 定义侧）；小电阻臂走串联元件。
    # 等号分支（R_s=R_L）elements 为空，side 恒 None。
    series_side: str | None = None
    shunt_side: str | None = None
    if matched:
        shunt_side = "load" if z_load_ohm > z_source_ohm else "source"
        series_side = "source" if shunt_side == "load" else "load"
    elements = []
    for element in result.elements:  # 负载端 → 源端
        elements.append({
            "kind": element.kind,
            "role": element.role,
            "side": series_side if element.role == "series" else shunt_side,
            "value": element.value,
            "value_nh": None if element.kind != "L" else element.value_nh,
            "value_pf": None if element.kind != "C" else element.value_pf,
            "display": element.display,
        })

    zin = result.input_impedance()
    gamma_mag = abs((zin - complex(result.z_source))
                    / (zin + complex(result.z_source)))
    finite_gamma = math.isfinite(gamma_mag)
    bandwidth = result.bandwidth_frac

    return {
        "z_source_ohm": result.z_source,
        "z_load_ohm": result.z_load,
        "f0_ghz": result.f0_ghz,
        "response": result.response,
        "q": round(result.q, 12),
        "bandwidth_frac": (None if not math.isfinite(bandwidth)
                           else round(bandwidth, 12)),
        "topology_arrangement": (
            "bypass（R_s=R_L，Q=0，无需匹配）" if not matched else
            "L 型两元件（元件表按负载端→源端；并联支路跨大电阻侧）"),
        "shunt_side": shunt_side,
        "elements": elements,
        "zin_f0_re_ohm": round(zin.real, 12),
        "zin_f0_im_ohm": round(zin.imag, 12),
        "match_residual_gamma_mag_f0": (
            round(gamma_mag, 15) if finite_gamma else None),
        "return_loss_db_f0": (
            None if (not finite_gamma or gamma_mag <= 0.0)
            else round(-20.0 * math.log10(gamma_mag), 6)),
        "note": (
            "f0 处 Z_in=R_s 为闭式构造解精确成立（回代残差为浮点尾差级）；"
            "L 型 Q 由 Rs/RL 唯一确定无自由度（带宽/平坦度需求请用 "
            "t_match 的 π/T 键）；response 只切响应型不改 f0 匹配性"),
        "source": (
            "Pozar Microwave Engineering §5.1；单源 core/matching."
            "synthesize_l_match（C14 锚现代入口，0bf 遗留标签入口不透传）"),
    }
