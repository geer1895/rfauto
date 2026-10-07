"""adapters 包：内置 EM 求解器注册面入口。

注册表模式：新增"可替换组件" = 基类 + 注册表。
注册表本体 = em_solver_base.EMSolverRegistry（键 = EMSolverType；观测面
get_global_registry()）。本包 __init__ 只导入第一类通道；引擎级 SDK
（pyaedt/MPh/meep/ngsolve/openEMS 绑定）在各模块内部惰性 import，导入
清单不引入任何引擎依赖，裸环境 ``import rfauto.adapters`` 安全。

一、导入即注册通道（``import rfauto.adapters`` 后 get_global_registry()
    必含以下 11 键；各模块尾部模块级 register_*() 自注册，与下方显式
    调用互为幂等兜底，registry.register 语义 = 同键覆盖不膨胀）：
    openems_solver→OPENEMS、meep_adapter→MEEP、elmer_adapter→ELMER、
    palace_solver→PALACE、comsol_adapter→COMSOL、ngsolve_adapter→NGSOLVE、
    vna_adapter→VNA、qucsator_adapter→QUCSATOR、xyce_adapter→XYCE、
    mmt_adapter→MMT、pssfss_adapter→PSSFSS（EC-20：ms_* 族单胞 Floquet
    快档；引擎级 SDK pypssfss/Julia 在模块内部惰性 import，导入清单
    不引入引擎依赖）。

二、显式注册通道（提供 register_* 函数、**不随包导入自动注册**，由
    消费点按需调用——当前 scripts/ 真机案例直用适配器类、tests/ 显式
    注册；未来 service 接线走同一函数）：
    icepak_adapter.register_icepak_adapter()→ICEPAK（WP4.4a 电-热）、
    q3d_adapter.register_q3d_adapter()→Q3D（WP4.4b 寄生提取）。

三、不经 EMSolverRegistry 的适配器家族（键集断言勿期待）：
    - SimulatorAdapter 家族（core/interfaces.py）：fake_adapter.FakeAdapter、
      hfss_adapter.HfssAdapter、openems_optimizer_adapter.OpenEMSOptAdapter
      —— optimization/service 消费点按 adapter_name 惰性 import 后直接
      实例化（optimization/optimizer.py 适配器创建分支），不走注册表；
    - ADS 通道：ads_python_api（A 档）/ ads_netlist（B 档主通道），独立
      协议（service/adapter_kit.KNOWN_ADAPTERS contract=ads_python_api）。

键集完整性回归：tests/unit/test_adapters_registry_completeness.py 钉
"导入键集 == 本清单""显式注册函数键集""重复注册幂等"与"全模块 import
体检（缺外部可选依赖记 expected-missing）"；新增注册通道或新增 adapter
模块时必须同步该测试的 REGISTRY_* 清单与本 docstring。
"""
from rfauto.adapters import (
    comsol_adapter,
    elmer_adapter,
    meep_adapter,
    mmt_adapter,
    ngsolve_adapter,
    openems_solver,
    palace_solver,
    pssfss_adapter,
    qucsator_adapter,
    vna_adapter,
    xyce_adapter,
)
from rfauto.adapters.qucsator_adapter import register_qucsator as _register_qucsator
from rfauto.adapters.vna_adapter import register_vna as _register_vna
from rfauto.adapters.xyce_adapter import register_xyce as _register_xyce

_register_vna()  # DP-11：VNA 测量通道（EMSolverType.VNA）导入即注册

_register_qucsator()  # DP-14 N7：qucsatorRF 电路级通道（EMSolverType.QUCSATOR）导入即注册

_register_xyce()  # F-L.2：Xyce-WSL 电路级 SPICE 通道（EMSolverType.XYCE）导入即注册

# DP-1：RWG/SIW 解析模基 MMT（GSM）通道（EMSolverType.MMT；模块级注册）
mmt_adapter.register_mmt()

# EC-20（W2-F）：PSSFSS 周期结构快档通道（EMSolverType.PSSFSS；模块级注册）
pssfss_adapter.register_pssfss()

__all__ = [
    "comsol_adapter",
    "elmer_adapter",
    "meep_adapter",
    "mmt_adapter",
    "ngsolve_adapter",
    "openems_solver",
    "palace_solver",
    "pssfss_adapter",
    "qucsator_adapter",
    "vna_adapter",
    "xyce_adapter",
]
