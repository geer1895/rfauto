# rfauto 插件开发指南

> 本文面向第三方/扩展开发者：如何把自定义求解器适配器或模板族接入 rfauto。
> 内部架构与资产治理（ADR-0002/0010 接口冻结先例）见仓内文档。

## 内置能力实测口径（#97：数字与代码实测一致）

- **内置模型注册表**（`models.registry`）：`list_models()` 实测 **4 个**。
- **内置适配器**（`KNOWN_ADAPTERS`）：**4 个**（EMSolver 契约 3 + ADS 原生 1）；
  EMSolver 契约下已挂：openems / palace / comsol / elmer / meep / ngsolve 等
  适配器经进程内注册表 `EMSolverRegistry`（`adapters/em_solver_base.py`）登记。
- **插件发现口**：`adapters.em_solver_base.ensure_adapter_plugins_loaded()`——
  双检锁扫描 `importlib.metadata` 的 `rfauto.adapters` entry-point 组
  （跨 distribution 聚合），第三方包自带 entry-point 即可被发现；
  **内置注册路径逐字节不变**（发现口只增不替换）。

## 求解器适配器插件（solver_adapter 模板）

```bash
# 从模板生成（cookiecutter 或 tools/plugin_templates 内置占位符渲染器）
cd tools/plugin_templates/solver_adapter
cookiecutter .   # 或 .venv/Scripts/python.exe -m tools.plugin_templates.render
pip install -e ./<你的包> --no-deps
```

**#362 硬警告**：`[project.entry-points.*]` 变更后必须
`pip install -e . --no-deps` 重装——importlib.metadata 读安装期 dist-info
快照，不重装则新插件对发现层不存在。

适配器契约（EMSolverAdapter 子类）要点：

1. `solver_type` 唯一命名；`CAPABILITIES` 如实声明（#122 不凑绿）。
2. **param_semantics 逐参数声明**（#154 教训：同名参数跨适配器语义可能相反）。
3. 模板族注册的交付门含 #304 五消费者
   （test_template_meta_consistency / test_template_geometry_audit /
   test_calculators / test_physics_invariants / test_model_docs）。

## 模板族插件（template_family 模板）

```bash
cd tools/plugin_templates/template_family
cookiecutter .
pip install -e ./<你的包> --no-deps
```

渲染类插件的自主修改一律走沙箱草稿→三层 Gate 晋级（仓内铁律 6/7：
LLM 永不产物理数字；数值只在确定性内核）。

## 稳定性契约

公开面与弃用政策见 [stability_policy.md](stability_policy.md)；
接口冻结先例 ADR-0002/0010。

## 已知边界（#270 同族警示）

发现口当前仅测试与模板 README 消费——运行时自动接线点（service 层求解
选型入口调用 `ensure_adapter_plugins_loaded()`）为登记中的 followUp；
在此之上手动 `from rfauto.adapters.em_solver_base import
ensure_adapter_plugins_loaded; ensure_adapter_plugins_loaded()` 即生效。
