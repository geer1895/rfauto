"""mask→滤波器规格综合闭环的计算器注册面（ge6 Wave1 Ph5 池旗舰件）。

实现本体在 core/mask_filter_synthesis.py（MaskSpec/内置遮罩模板/最小阶
acosh 闭式/cm_core 复用闭环/裕量报告）；本模块只做 JSON 进出的薄注册
（service 层 JSON 进出惯例）：mask 参数为 MaskSpec.to_dict() 形态的 dict
（内置模板经 mask_template_names()/get_mask_template(name).to_dict() 取）。

#231 五钉消费者（新 CALC 键落地即同步）：
tests/unit/test_calculators.py EXPECTED + test_physics_invariants
_calculator_inputs + test_model_docs（注册表自动覆盖）+ test_check_numbers
（README/ 计数链）+ 本文件注册单点。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator

_MASK_PARAM = ("mask", "dict - 遮罩规格（MaskSpec.to_dict() 形态；内置模板见 "
              "fcc_15_247_dts_2g4 / ieee_80211_dsss_2g4 / nr_aclr_20mhz_envelope）")


@register_calculator(
    "mask_min_order",
    "发射遮罩→切比雪夫滤波器最小阶（经典 acosh 闭式，多段逐段取最大）："
    "N=ceil(acosh(√((10^(A/10)−1)·K))/acosh(Ωs))，K=10^(RL/10)−1；Ωs 为段"
    "约束点（内缘裁剪到通带边缘+guard_offset_ghz 调制滚降信用区）经几何"
    "映射 Ω=(f/f0−f0/f)/fbw 的归一化频（fbw=u(2+u)/(1+u) 精确反解，使 "
    "Ω(±通道半宽)=±1）。返回阶数/回损分配/带内纹波/逐段 Ω 与需求明细；"
    "贴边段要求超过纹波电平如实报错（全极点在 Ω=1 只能提供纹波衰减）",
    (_MASK_PARAM,
     ("required_margin_db", "float dB 各段所需设计裕量（默认 0，进闭式）"),
     ("topology", "str - 拓扑（当前仅 chebyshev 全极点，显式拒绝其他）")),
    required=("mask",),
)
def mask_min_order(mask: dict, required_margin_db: float = 0.0,
                   topology: str = "chebyshev") -> dict[str, Any]:
    """遮罩→最小阶闭式（薄注册，实现见 core/mask_filter_synthesis）。"""
    from rfauto.core.mask_filter_synthesis import MaskSpec, min_order_for_mask

    spec = MaskSpec.from_dict(mask)
    return min_order_for_mask(spec, topology=topology,
                              required_margin_db=required_margin_db)


@register_calculator(
    "mask_margin_report",
    "给定阶数滤波器 vs 发射遮罩的裕量报告：阶数→cm_core Cameron N+2 耦合"
    "矩阵→矩阵频响（−20lg|S21|，几何映射采样）→逐遮罩段裕量 dB+最紧段+"
    "PASS/FAIL；含耦合矩阵与响应采样。贴滤波器责任起点（通带边缘+guard）"
    "的段如实标注并按负裕量判 FAIL（Ω=1 处衰减=纹波电平）",
    (_MASK_PARAM,
     ("order", "int - 滤波器阶数（≥1）"),
     ("required_margin_db", "float dB 各段所需设计裕量（默认 0）")),
    required=("mask", "order"),
)
def mask_margin_report_calc(mask: dict, order: int,
                            required_margin_db: float = 0.0
                            ) -> dict[str, Any]:
    """阶数×遮罩→裕量报告（薄注册，实现见 core/mask_filter_synthesis）。"""
    from rfauto.core.mask_filter_synthesis import MaskSpec, mask_margin_report

    spec = MaskSpec.from_dict(mask)
    return mask_margin_report(spec, order, required_margin_db)


@register_calculator(
    "mask_filter_synthesize",
    "mask→滤波器规格综合闭环：遮罩→闭式最小阶→cm_core (N+2) 耦合矩阵→"
    "矩阵频响逐段回验裕量→不足自动 +1 重试（max_order_extra 上限），报告"
    "各阶裕量轨迹与最紧段。min_order_override 可钉起步阶（轨迹演示/调用方"
    "钉阶）；全程零仿真纯确定性（铁律 7）",
    (_MASK_PARAM,
     ("required_margin_db", "float dB 各段所需设计裕量（默认 0，进闭式）"),
     ("max_order_extra", "int - 起步阶之上最多重试阶数（默认 3）"),
     ("min_order_override", "int - 显式起步阶（缺省=闭式最小阶）"),
     ("topology", "str - 拓扑（当前仅 chebyshev 全极点）")),
    required=("mask",),
)
def mask_filter_synthesize(mask: dict, required_margin_db: float = 0.0,
                           max_order_extra: int = 3,
                           min_order_override: int | None = None,
                           topology: str = "chebyshev") -> dict[str, Any]:
    """遮罩→综合闭环（薄注册，实现见 core/mask_filter_synthesis）。"""
    from rfauto.core.mask_filter_synthesis import MaskSpec, synthesize_from_mask

    spec = MaskSpec.from_dict(mask)
    return synthesize_from_mask(
        spec, topology=topology, required_margin_db=required_margin_db,
        max_order_extra=max_order_extra, min_order_override=min_order_override)


__all__ = [
    "mask_filter_synthesize", "mask_margin_report_calc", "mask_min_order",
]
