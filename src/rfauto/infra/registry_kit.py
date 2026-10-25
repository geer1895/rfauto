"""RegistryKit 兼容入口（本体已下沉 core/registry_kit.py，aurora_h W2-S3）。

下沉原因：R1_arch_audit_v3 §5 扩面三件中 Calculator（core/calc_families/
registry.py）与 Budget（core/error_budget.py）两注册表住 core 层——分层
契约（.importlinter layers，"core is a stable dependency-free leaf"）禁止
core 反向 import infra；Kit 为零第三方依赖的纯 stdlib 泛型容器，下沉
core=分层合法的最低层。本文件保留 re-export（同一类对象非拷贝），既有
``from rfauto.infra.registry_kit import RegistryKit`` 的 13 处消费面导入
路径逐字节不变。**新代码一律从 core 侧导入**；本入口仅承载历史兼容，
不新增能力（扩 Kit 能力改 core/registry_kit.py）。

仍不声明 ``__all__``：public_api 金快照口径下无 ``__all__`` 记私有
（加 __all__ 会给金快照新增 files 条目=显式评审动作，非本席权限）。
"""

from rfauto.core.registry_kit import RegistryKit as RegistryKit
