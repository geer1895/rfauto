"""adapters 包：导入即完成全部内置求解器的注册表注册。

注册表模式（分层架构铁律）：新增"可替换组件" = 基类 + 注册表。
新 adapter 模块在此导入一次即可（模块级 register 调用生效），
service/UI 层通过 `import rfauto.adapters` 拿到完整注册表。
"""
from rfauto.adapters import comsol_adapter, elmer_adapter, meep_adapter, ngsolve_adapter, openems_solver, palace_solver

__all__ = ["comsol_adapter", "elmer_adapter", "meep_adapter", "ngsolve_adapter",
           "openems_solver", "palace_solver"]
