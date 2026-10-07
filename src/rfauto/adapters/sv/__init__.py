"""SV 扩展面子包：Palace Floquet / FDTDX 周期扩面（SV-3 / SV-4，round14 §六）。

**为什么是子包**（与 :mod:`rfauto.adapters.gpl` 同款治理逻辑）：

1. adapters/ 顶层的注册面清单由
   tests/unit/test_adapters_registry_completeness.py 三张清单全量钉
   （新增顶层模块必须先做注册面决策并同步清单，防静默漂移）。本包
   成员是**求解器前沿的配置/规格扩展面**（非 EMSolverAdapter 契约、
   零注册副作用、零 GPL 交互），归属决策（并入三张清单的哪一张/
   提升为内置通道）属公开面评审动作，留账本批显式处理——本
   docstring 即决策记录与占位声明。
2. 成员（显式 import 消费，**不**进 adapters/__init__ 自动导入链，
   内置注册路径逐字节不变）：
   - :mod:`.palace_floquet` —— SV-3：Palace v0.18.1 官方 schema 实录的
     Floquet/周期结构配置段生成器（不修改既有 palace_solver.py，
     经其 ``boundaries`` 透传通道并入）；
   - :mod:`.fdtd_periodic` —— SV-4：FDTDX 周期边界规格层 + 安装版
     源码支持性实录探针（不修改既有 fdtd_diff.py）。
"""

from __future__ import annotations
