"""参数映射契约。

ParameterMappingRegistry：来源域 → 目标域的显式映射，解决 hfss_var_map
教训（经验30：名字"巧合兼容"是最危险的静默失效形态）。

设计决策：
- 禁止同名即映射（必须显式声明来源域/目标域/单位/变换）
- dry-run 输出最终写入值（可审计）
- 单测覆盖"调参确实影响几何/网表"

ADR-0010 只增不改：新接口不修改现有 hfss_var_map 行为，
ParameterMappingRegistry 是 hfss_var_map 的制度化替代。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParamMapping:
    """单个参数映射。"""
    source: str              # 来源域参数名（配方参数名，如 arm_len_mm）
    target: str              # 目标域参数名（设计变量名，如 arm_len）
    unit: str = "mm"         # 单位
    transform: Callable[[float], float] | None = None  # 变换函数（如 ×1000）
    tolerance: float = 0.0   # 容差（用于 dry-run 校验）
    description: str = ""

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError(
                f"禁止同名映射: {self.source} -> {self.target}。"
                "必须显式声明来源域/目标域（ADR-0010 + 经验30）。"
            )

    def apply(self, value: float) -> float:
        """应用变换。"""
        if self.transform is not None:
            return self.transform(value)
        return value


class ParameterMappingRegistry:
    """参数映射注册表。

    用法：
        registry = ParameterMappingRegistry()
        registry.register(ParamMapping(
            source="arm_len_mm",
            target="arm_len",
            unit="mm",
        ))
        # dry-run：输出最终写入值
        dry = registry.dry_run({"arm_len_mm": 20.5})
        # {"arm_len": {"source_value": 20.5, "target_value": 20.5, "unit": "mm"}}
    """

    def __init__(self) -> None:
        self._mappings: dict[str, ParamMapping] = {}

    def register(self, mapping: ParamMapping) -> None:
        """注册映射。禁止同名即映射。"""
        if mapping.source == mapping.target:
            raise ValueError(
                f"禁止同名映射: {mapping.source} -> {mapping.target}。"
                "必须显式声明来源域/目标域（ADR-0010 + 经验30）。"
            )
        if mapping.source in self._mappings:
            raise KeyError(f"来源参数已注册: {mapping.source}")
        self._mappings[mapping.source] = mapping

    def get(self, source: str) -> ParamMapping | None:
        """获取映射。"""
        return self._mappings.get(source)

    def has(self, source: str) -> bool:
        """检查是否有映射。"""
        return source in self._mappings

    @property
    def sources(self) -> list[str]:
        """所有来源参数名。"""
        return list(self._mappings.keys())

    @property
    def targets(self) -> list[str]:
        """所有目标参数名。"""
        return [m.target for m in self._mappings.values()]

    def resolve(self, source_values: dict[str, float]) -> dict[str, float]:
        """解析：来源域值 → 目标域值。

        Args:
            source_values: {source_name: value}

        Returns:
            {target_name: transformed_value}
        """
        result: dict[str, float] = {}
        for source, value in source_values.items():
            mapping = self._mappings.get(source)
            if mapping is None:
                raise KeyError(f"未注册的来源参数: {source}")
            result[mapping.target] = mapping.apply(value)
        return result

    def dry_run(self, source_values: dict[str, float]) -> dict[str, dict[str, Any]]:
        """Dry-run：输出最终写入值（可审计）。

        Returns:
            {target_name: {source_value, target_value, unit, description}}
        """
        result: dict[str, dict[str, Any]] = {}
        for source, value in source_values.items():
            mapping = self._mappings.get(source)
            if mapping is None:
                raise KeyError(f"未注册的来源参数: {source}")
            target_value = mapping.apply(value)
            result[mapping.target] = {
                "source_value": value,
                "target_value": round(target_value, 6),
                "unit": mapping.unit,
                "description": mapping.description,
            }
        return result

    def validate(
        self,
        source_values: dict[str, float],
        actual_values: dict[str, float],
    ) -> list[str]:
        """校验：实际写入值与预期值的偏差。

        Returns:
            偏差描述列表（空=全部合格）
        """
        issues: list[str] = []
        for source, value in source_values.items():
            mapping = self._mappings.get(source)
            if mapping is None:
                continue
            expected = mapping.apply(value)
            actual = actual_values.get(mapping.target)
            if actual is None:
                issues.append(f"{mapping.target}: 未写入")
                continue
            delta = abs(actual - expected)
            if mapping.tolerance > 0 and delta > mapping.tolerance:
                issues.append(
                    f"{mapping.target}: 预期 {expected:.4f}, 实际 {actual:.4f}, "
                    f"Δ={delta:.4f} > 容差 {mapping.tolerance:.4f}"
                )
        return issues

    @classmethod
    def from_hfss_var_map(
        cls,
        hfss_var_map: dict[str, str],
        units: dict[str, str] | None = None,
    ) -> ParameterMappingRegistry:
        """从现有 hfss_var_map 创建注册表（向后兼容）。

        注意：这只是过渡方法——新代码应使用 ParamMapping 显式注册。
        """
        registry = cls()
        for source, target in hfss_var_map.items():
            unit = (units or {}).get(source, "mm")
            registry.register(ParamMapping(
                source=source,
                target=target,
                unit=unit,
                description="从 hfss_var_map 自动导入（过渡）",
            ))
        return registry
