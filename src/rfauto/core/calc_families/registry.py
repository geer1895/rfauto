"""注册表单源（CalculatorSpec/CalculatorRegistry/CALCULATOR_REGISTRY/register_calculator + C_MM_GHZ）（AU-1 自 core/calculators.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

C_MM_GHZ = 299.792458  # mm·GHz（光速，f[GHz]×λ[mm]=此值）


# ─── 注册表（接口先行：注册可见、未注册调用显式报错）─────────────────────────
# 实验态开关（W1⑨，2026-09-16 用户口径）：自动归纳（符号回归等）的经验
# 公式一律 experimental=True 入库——names()/describe() **默认不列**（任何
# 只拿 names() 的消费方天然不会拾取），显式 include_experimental=True 才
# 可见；运行放行由 service 层开关决定（core 零配置依赖，只带元数据）。

@dataclass(frozen=True)
class CalculatorSpec:
    """一个计算器的自描述条目（供 CLI/UI 动态生成表单）。"""

    name: str
    description: str
    func: Callable[..., dict[str, Any]]
    params: tuple[tuple[str, str], ...]  # (参数名, "类型 单位 说明")
    required: tuple[str, ...]
    experimental: bool = False  # 实验态：默认不列/默认拒跑，显式开关才用
    # 互易豁免位（QM-1 §D-7，2026-10-02）：产出 S/ABCD 的键默认 True，受
    # test_physics_invariants 互易全键扫描裁判；非互易器件（铁氧体隔离器/
    # 环形器类）注册时显式 reciprocal=False 进豁免清单——豁免清单由该测试
    # 封闭断言钉死，新增豁免键必须同步清单。纯元数据位，不参与计算语义。
    reciprocal: bool = True


class CalculatorRegistry:
    """基类+注册表模式（参照 EMSolverRegistry）：重名注册报错，
    未注册调用 KeyError 并列出可用名。"""

    def __init__(self) -> None:
        self._specs: dict[str, CalculatorSpec] = {}

    def register(self, spec: CalculatorSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"计算器重名注册: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> CalculatorSpec:
        if name not in self._specs:
            raise KeyError(
                f"未注册的计算器: {name}"
                f"（可用: {self.names(include_experimental=True)}）")
        return self._specs[name]

    def names(self, include_experimental: bool = False) -> list[str]:
        """已注册键（字典序）；实验键默认排除，include_experimental=True 才列。"""
        return sorted(
            key for key, spec in self._specs.items()
            if include_experimental or not spec.experimental)

    def is_experimental(self, name: str) -> bool:
        """键是否实验态；未注册名显式 KeyError（与 get 同语义）。"""
        return self.get(name).experimental

    def describe(self, include_experimental: bool = False) -> list[dict[str, Any]]:
        """自描述清单（含 experimental 标签）；实验键默认排除。"""
        return [
            {
                "name": self._specs[key].name,
                "description": self._specs[key].description,
                "experimental": bool(self._specs[key].experimental),
                "params": [
                    {"name": pname, "desc": pdesc,
                     "required": pname in self._specs[key].required}
                    for pname, pdesc in self._specs[key].params
                ],
            }
            for key in self.names(include_experimental=include_experimental)
        ]


CALCULATOR_REGISTRY = CalculatorRegistry()


def register_calculator(
    name: str,
    description: str,
    params: tuple[tuple[str, str], ...],
    required: tuple[str, ...] = (),
    experimental: bool = False,
    reciprocal: bool = True,
) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    """把纯函数登记进 CALCULATOR_REGISTRY 的装饰器。

    experimental=True 的键：names()/describe() 默认不列、service 运行默认
    拒绝（见 calculator_service.run_calculator 的 allow_experimental 与
    configs/settings.yaml 的 calculators.allow_experimental）。

    reciprocal=False：非互易器件豁免位（QM-1 §D-7，铁氧体键显式 False）——
    纯元数据标注，只被 test_physics_invariants 的互易全键扫描/豁免清单
    封闭断言消费；不改变任何计算语义。
    """

    def deco(
        func: Callable[..., dict[str, Any]],
    ) -> Callable[..., dict[str, Any]]:
        CALCULATOR_REGISTRY.register(CalculatorSpec(
            name=name, description=description, func=func,
            params=params, required=required, experimental=experimental,
            reciprocal=reciprocal))
        return func

    return deco
