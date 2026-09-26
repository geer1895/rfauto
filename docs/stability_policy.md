# rfauto 稳定性政策

> 本文声明 rfauto 的公开 API 面、快照机制与弃用窗口。参考 SPEC 0
> （科学 Python 生态弃用惯例）/ PEP 702 / pint 等项目惯例；
> 内部接口冻结先例见 ADR-0002/0010。

## 公开面定义

- **公开 API** = 模块 `__all__` 显式导出的名字 + 下列核心门面的模块级函数：
  - `rfauto.adapters.em_solver_base`（适配器基类/注册表/发现口）
  - `rfauto.models.registry`（模型注册表）
  - `rfauto.service.db_service` / `health_service` / `league_service` /
    `explain_run` / `solve_health`
- 快照机制：`scripts/check_public_api.py --generate` 生成
  `tests/gold/public_api.json`（AST 扫 `__all__`，无时间戳幂等）；
  `--check` 模式进测试门——**翻转/移除公开名必须显式评审并重生成快照**
  （快照 diff 即评审记录）。首版快照：41 个 `__all__` 文件 + 7 核心门面。
- 未列入 `__all__` 的名字一律视为**私有**，无兼容承诺（零行为变化前提下
  可随时改名/移除）。

## 弃用窗口

- **pre-1.0（当前）**：如实免承诺——弃用消息给出"不会早于 <版本/日期>"
  移除意向，但不构成硬承诺。
- **1.0 起**：弃用窗口 = "2 个 minor 版本或 6 个月，取晚者"（SPEC 0 对齐）。
- 弃用机制：`rfauto.infra.compat.deprecated(release, removal, alternative)`
  （PEP 702 `typing_extensions.deprecated` 透传，统一三要素消息：
  弃用于哪版 / 计划移除不早于何时 / 替代物是什么）。

## 内部（非公开）面

`src/rfauto` 下未列入公开面的模块（pipeline/infra 骨架、cli、ui、
mcp_server 工具面语义等）为内部实现细节：跨版本可变；CLI/MCP 工具的
JSON 输出契约以 `annotate_contract` 标注的 schema 为准并随变更记录留档。
