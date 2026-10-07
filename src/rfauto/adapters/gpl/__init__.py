"""GPL 隔离子包：scuff-em / PyPO 适配器（SV-1 / SV-2，round14 §六）。

**为什么是子包**（结构性许可边界，两条理由）：

1. **GPL 隔离**：scuff-em（GPL-2/3）与 PyPO（GPL-3）是 copyleft 工程
   ——本仓适配器只经**子进程 CLI**（scuff-em）或**显式 opt-in 的进程
   内通道**（PyPO，接口位）交互，且全部入口被 fail-closed 许可门
   （:mod:`.license_gate`）拦在前：缺省（无显式环境变量 opt-in）一律
   拒绝执行，拒绝信息写明许可边界与开通方式。子包边界让 GPL 交互面
   在文件树上可枚举、可审计。
2. **注册面治理**：adapters/ 顶层的注册面清单由
   tests/unit/test_adapters_registry_completeness.py 三张清单全量钉
   （新增顶层模块必须先做注册面决策并同步清单）。本子包以显式 import
   注册（``import rfauto.adapters.gpl`` 即向全局 EMSolverRegistry 贡献
   自定义字符串键 ``"scuff"`` / ``"pypo"``——EMSolverConfig.solver_type
   自定义字符串通道，em_solver_base docstring 先例），**不**进
   adapters/__init__ 自动导入链（内置注册路径逐字节不变，em_solver_base
   第三方发现口同纪律）。清单归属决策（是否并入三张清单）属公开面
   评审动作，留给账本批显式处理——本 docstring 即决策记录。

成员：
- :mod:`.license_gate` —— fail-closed GPL 许可门（共享）。
- :mod:`.scuff_adapter` —— SV-1 scuff-em 表面积分方程（MoM/RWG）通道。
- :mod:`.pypo_adapter` —— SV-2 PyPO 物理光学大电尺寸通道 + 闭式互证
  裁判（口径效率/Gain 闭式）。
"""

from __future__ import annotations

from rfauto.adapters.gpl.license_gate import (
    LicenseRefusedError as LicenseRefusedError,
)
from rfauto.adapters.gpl.license_gate import (
    gpl_gate_decision as gpl_gate_decision,
)
from rfauto.adapters.gpl.license_gate import (
    require_gpl_channel as require_gpl_channel,
)
from rfauto.adapters.gpl.pypo_adapter import (  # 导入即注册两通道
    PypoAdapter as PypoAdapter,
)
from rfauto.adapters.gpl.pypo_adapter import register_pypo as register_pypo
from rfauto.adapters.gpl.scuff_adapter import (  # 导入即注册
    ScuffAdapter as ScuffAdapter,
)
from rfauto.adapters.gpl.scuff_adapter import register_scuff as register_scuff

