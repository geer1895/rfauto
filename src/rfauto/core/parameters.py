"""参数系统（§7.1）—— ParameterSystem 管理设计变量的生命周期。

职责：
- 参数值的 pydantic 校验模型
- 参数命名空间（含 sim 归属标签，为 ADR-0003 联合优化预留）
- 从 Recipe 提取参数、写入 adapter 的统一通道
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SimNamespace(str, Enum):
    """变量归属的仿真器命名空间（ADR-0003 联合优化预留）。"""
    HFSS = "hfss"
    ADS = "ads"
    COMMON = "common"


class ParamValue(BaseModel):
    """单个参数的值描述。"""
    name: str = Field(..., description="参数名（HFSS 变量名风格）")
    value: float | int | str = Field(..., description="参数值")
    unit: str = Field(default="mm", description="单位")
    namespace: SimNamespace = Field(default=SimNamespace.HFSS, description="归属仿真器")
    bounds: tuple[float, float] | None = Field(default=None, description="优化搜索范围 (min, max)")
    description: str = Field(default="", description="参数描述")

    def to_hfss_expr(self) -> str:
        """转换为 HFSS 表达式字符串，如 '20.5mm'。"""
        if isinstance(self.value, str):
            return self.value
        return f"{self.value}{self.unit}"

    def to_setup_dict(self) -> dict[str, Any]:
        """转换为适配器 set_variables 所需的 {name: expr} 字典。"""
        return {self.name: self.to_hfss_expr()}


class ParameterSystem:
    """参数管理器——从 Recipe 提取参数、统一写入适配器。

    使用方式：
        ps = ParameterSystem(recipe.params)
        ps.write_to_adapter(adapter)   # 统一写入
        ps.update({"arm_len_mm": 21.0})  # 优化器更新
        ps.write_to_adapter(adapter)   # 增量写入
    """

    def __init__(self, params: dict[str, ParamValue]) -> None:
        self._params: dict[str, ParamValue] = dict(params)
        self._dirty: set[str] = set(params.keys())  # 初始全部待写入

    @property
    def params(self) -> dict[str, ParamValue]:
        return dict(self._params)

    @property
    def dirty(self) -> set[str]:
        """返回自上次 write_to_adapter 以来被修改的参数名。"""
        return set(self._dirty)

    def update(self, updates: dict[str, float | int | str]) -> None:
        """用优化器的建议更新参数值（只改 value，不改 unit/bounds）。"""
        for name, val in updates.items():
            if name not in self._params:
                raise KeyError(f"未知参数: {name}")
            self._params[name] = self._params[name].model_copy(update={"value": val})
            self._dirty.add(name)

    def get_hfss_vars(
        self, only_dirty: bool = False, name_map: dict[str, str] | None = None
    ) -> dict[str, str]:
        """获取 HFSS 变量名→表达式字典。

        name_map：配方参数名 → 设计变量名（如 arm_len_mm → arm_len）。
        缺省恒等映射。真实调谐回路（2026-08-30 branchline 8-trial）发现：
        插件 build 写入的设计变量名不带单位后缀，而配方参数名带——不做
        映射时优化器写入的是无人引用的新变量，几何纹丝不动，cost 恒定。
        """
        mapping = name_map or {}
        targets = self._dirty if only_dirty else set(self._params.keys())
        return {
            mapping.get(self._params[name].name, self._params[name].name): self._params[
                name
            ].to_hfss_expr()
            for name in targets
            if name in self._params and self._params[name].namespace in (SimNamespace.HFSS, SimNamespace.COMMON)
        }

    def write_to_adapter(
        self,
        adapter: Any,
        only_dirty: bool = True,
        name_map: dict[str, str] | None = None,
    ) -> None:
        """将参数写入适配器的 set_variables（name_map 同 get_hfss_vars）。"""
        vars_dict = self.get_hfss_vars(only_dirty=only_dirty, name_map=name_map)
        if vars_dict:
            adapter.set_variables(vars_dict)
            self._dirty.clear()

    def to_canonical_json(self) -> str:
        """生成用于缓存键的规范化 JSON。"""
        import json
        data = {k: {"value": v.value, "unit": v.unit} for k, v in sorted(self._params.items())}
        return json.dumps(data, sort_keys=True, separators=(",", ":"))
