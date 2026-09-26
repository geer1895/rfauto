"""adapters 包：导入即完成全部内置求解器的注册表注册。

注册表模式（分层架构铁律）：新增"可替换组件" = 基类 + 注册表。
新 adapter 模块在此导入一次即可（模块级 register 调用生效），
service/UI 层通过 `import rfauto.adapters` 拿到完整注册表。
"""
from rfauto.adapters import (
    comsol_adapter,
    elmer_adapter,
    meep_adapter,
    mmt_adapter,
    ngsolve_adapter,
    openems_solver,
    palace_solver,
    qucsator_adapter,
    vna_adapter,
)
from rfauto.adapters.qucsator_adapter import register_qucsator as _register_qucsator
from rfauto.adapters.vna_adapter import register_vna as _register_vna

_register_vna()  # DP-11：VNA 测量通道（EMSolverType.VNA）导入即注册

_register_qucsator()  # DP-14 N7：qucsatorRF 电路级通道（EMSolverType.QUCSATOR）导入即注册

# DP-1：RWG/SIW 解析模基 MMT（GSM）通道（EMSolverType.MMT；模块级注册）
mmt_adapter.register_mmt()

__all__ = [
    "comsol_adapter",
    "elmer_adapter",
    "meep_adapter",
    "mmt_adapter",
    "ngsolve_adapter",
    "openems_solver",
    "palace_solver",
    "qucsator_adapter",
    "vna_adapter",
]
