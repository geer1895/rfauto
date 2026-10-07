"""CMA 特征模计算器（ge6 Wave1 离线档；内核 core/characteristic_modes.py）。

Z=R+jX 广义阻抗矩阵的 R-加权特征模分解（Harrington–Mautz 1971 /
Cabedo-Fabrés 2007 口径）：X·I_n = λ_n·R·I_n，MS_n = 1/(1+λ_n²)，
R-正交归一特征电流，特征阻抗 Z_cn = 1+jλ_n。矩阵由调用方提供
（未来 MoM 导出 / HFSS CMA 报告导出 / 散射法重建算子均可接）——
本族零 IO、不自带矩量法（诚实边界见内核 docstring 散射法扩展面）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "cma_modes",
    "CMA 特征模分解（ge6 Wave1 离线档）：广义阻抗矩阵 Z=R+jX 的 R-加权"
    "广义特征值问题 X·I_n=λ_n·R·I_n（Harrington–Mautz 1971；综述 "
    "Cabedo-Fabrés 2007）。返回 λ 谱（升序实数）/模 significance "
    "MS_n=1/(1+λ²)（功率口径，幅值口径 1/√(1+λ²) 同步给出）/R-正交归一"
    "特征电流（I_mᵀ·R·I_n=δ_mn）/特征阻抗 Z_cn=1+jλ_n（R 归一口径，对 "
    "Z→αZ 缩放不变）/逐模相对残差。矩阵由调用方提供（MoM 导出、HFSS "
    "CMA 导出或散射法重建算子；npz 读出后以嵌套列表传入，计算器零 IO）；"
    "R 非正定/奇异显式报错不产 NaN。散射 dyadic CMA（Capek 2023）重建层"
    "另行立项，见 core/characteristic_modes docstring 扩展面登记",
    (("z", "list N×N Z 矩阵：嵌套 [re,im] 对（JSON 语义）或全实数方阵；"
          "npz/MoM 导出由调用方读入后转嵌套列表（零 IO）"),),
    required=("z",),
)
def cma_modes(z: Any) -> dict:
    """特征模分解（核 characteristic_modes 的 registry 薄壳）。

    入参 z 语义见 parse_z_matrix（嵌套 [re,im] 对 / 全实数方阵 /
    ndarray，形状/有限性/对称性/正定性守卫在内核）；返回
    CMAResult.to_dict() 的 JSON 快照。
    """
    from rfauto.core.characteristic_modes import characteristic_modes

    return characteristic_modes(z).to_dict()
