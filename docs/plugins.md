# rfauto 插件开发指南

> 本文面向第三方/扩展开发者：如何把自定义求解器适配器、模板族或
> metric/benchmark 基准件接入 rfauto。
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
- **cookiecutter 不在本 venv（#222 实测）**——仓内置换渲染器：
  `python -m tools.plugin_templates.render <模板名> [--out DIR] [--set k=v]`
  （`tools/plugin_templates/render.py`；`--list` 列可用模板）。

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
4. 第 6 消费者（I-14，X1 §6）：`service/gallery_service.TEMPLATE_FAMILIES`
   模板族分类单一事实源——新模板注册时须补族映射；缺省静默落 `other`
   （`family_of` 回退），能力卡/画廊导出（capability_cards_export /
   gallery_export）随之漏族，注册 checklist 同日核对。

## 模板族插件（template_family 模板）

```bash
cd tools/plugin_templates/template_family
cookiecutter .   # 或 python -m tools.plugin_templates.render template_family
pip install -e ./<你的包> --no-deps
```

渲染类插件的自主修改一律走沙箱草稿→三层 Gate 晋级。

## metric/benchmark 插件（metric_benchmark 模板）

```bash
cd tools/plugin_templates/metric_benchmark
cookiecutter .   # 或 python -m tools.plugin_templates.render metric_benchmark
pip install -e ./<你的包> --no-deps
```

AgentBench 任务集（`bench_sets/*.yaml`，`service/agent_bench.load_bench_set`
直读）+ 确定性指标计算（`metrics.py`，铁律 7）+ 离线参考提供器
（`provider.py`，`run_agentbench_regression(trajectory_provider=...)` 注入点）。
**本件不挂 entry-point 发现口**——基准面当前没有 importlib.metadata 发现组
（诚实口径，README 明示）；消费=显式路径/显式导入。ground truth 数值逐条
引用权威出处（`source` 字段，闭式解/HFSS 仲裁/官方例口径集中维护在
`docs/rf_template_references.md`），打分器只比较、不产数字。

## 稳定性契约

公开面与弃用政策见 [stability_policy.md](stability_policy.md)；
接口冻结先例 ADR-0002/0010。

## 已知边界（#270 同族警示）

发现口当前仅测试与模板 README 消费——运行时自动接线点（service 层求解
选型入口调用 `ensure_adapter_plugins_loaded()`）为登记中的 followUp；
在此之上手动 `from rfauto.adapters.em_solver_base import
ensure_adapter_plugins_loaded; ensure_adapter_plugins_loaded()` 即生效。
