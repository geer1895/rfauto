"""物理角色接口（v0，代理校准设计 §1 的第一块地基）。

问题：公式/代理层如果直接认参数名（arm_len_mm / patch_len_mm ...），
换个模型名字不同就会静默算错——参数名是模型作者随口起的，物理角色才稳定。

约定：每个模型插件用"角色候选表"声明哪个参数承担哪个物理角色；
公式与代理层只消费角色。hfss_var_map（参数名→HFSS 设计变量名）是同一
思路在执行层的先例，本模块是它在公式层的对应物。

v0 范围：解析 + 单元测试。v1 校准服务将把角色表升格为模型插件的
显式声明（声明式元数据），本模块的 resolve 语义保持不变。
"""

from __future__ import annotations

from typing import Any

# 物理角色 → 参数名候选（按优先级；后缀 _mm 可省略由解析器兜底）
ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    # λ/4（wilkinson/branchline）或 λ/2（patch）谐振段长度
    "resonator_length_mm": ("arm_len_mm", "arm_len", "patch_len_mm", "patch_len"),
    # 阻抗变换段线宽（wilkinson: 目标 Z0*√2；branchline: 目标 Z0/√2）
    "impedance_line_width_mm": ("series_w_mm", "series_w"),
    # 50Ω 臂/分支线宽
    "shunt_line_width_mm": ("shunt_w_mm", "shunt_w"),
    # 贴片馈电点离中心/边缘的偏移
    "feed_offset_mm": ("feed_offset_mm", "feed_offset"),
    # 贴片宽度（边缘阻抗 R_edge ∝ 1/W）
    "patch_width_mm": ("patch_w_mm", "patch_w"),
    # 均匀传输线宽（mline 锚模板；Z0 由综合精算决定）
    "line_width_mm": ("w_mm", "line_w_mm"),
    # 均匀传输线长（两端口间，非谐振长度）
    "line_length_mm": ("line_len_mm", "line_len"),
    # 共面结构缝宽（CPW：中心带与地之间）
    "gap_width_mm": ("gap_mm", "gap"),
}


def parse_length(value: Any) -> float | None:
    """解析长度值：数字直接返回；字符串剥离 mm/m 单位后取浮点。

    返回 None 表示不可解析（缺失/非数值），由调用方决定回退。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("mm"):
        text = text[:-2]
    elif text.endswith("m"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def resolve_role(
    role: str,
    variables: dict[str, Any],
    default: float | None = None,
    candidates: tuple[str, ...] | None = None,
) -> float | None:
    """按角色从变量字典取值（带单位剥离与候选名兜底）。

    Args:
        role: 物理角色名（ROLE_CANDIDATES 的键）。
        variables: 设计变量（值可为 str/float）。
        default: 全部候选缺失/不可解析时的回退值。
        candidates: 覆盖默认候选表（自定义模型可传入自己的候选名）。

    Returns:
        解析出的数值；解析失败返回 default（default=None 时也是 None）。
    """
    names = candidates if candidates is not None else ROLE_CANDIDATES.get(role, ())
    for name in names:
        if name in variables:
            parsed = parse_length(variables[name])
            if parsed is not None:
                return parsed
        # 参数名常以 _mm 结尾，变量可能省略单位后缀（arm_len）
        alt = name[:-3] if name.endswith("_mm") else f"{name}_mm"
        if alt in variables:
            parsed = parse_length(variables[alt])
            if parsed is not None:
                return parsed
    return default
