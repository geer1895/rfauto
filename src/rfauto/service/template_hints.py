"""配方 model 名 → 3D 模板名映射叶（T1 解环；aurora_g W6-S1）。

从 ui_service 叶化：_template_hint 是纯字符串映射（ui/校准/适配器
三方共用口径），calibration_service 与 adapter_kit 改读本叶，
静态图上不再出现 实现→ui_service 边（calibration→ui→uq→calibration
环臂断）。ui_service 同名再导出保模块面零变化。
"""
from __future__ import annotations

from typing import Any


def _template_hint(recipe_data: dict[str, Any]) -> str | None:
    """配方 model 名 → 3D 模板名。"""
    model = str(recipe_data.get("model", ""))
    if "wilkinson" in model:
        return "wilkinson"
    if "branchline" in model:
        return "branchline"
    if "patch" in model:
        return "patch"
    if "mline" in model:
        return "mline"
    if "cpw" in model:
        return "cpw"
    return None
