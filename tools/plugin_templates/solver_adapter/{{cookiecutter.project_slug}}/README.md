# {{ cookiecutter.project_slug }}

rfauto 第三方求解器适配器插件（EMSolverAdapter 契约）。

## 快速开始

```bash
pip install cookiecutter          # 渲染（一次性）
cookiecutter /path/to/rfauto/tools/plugin_templates/solver_adapter
cd {{ cookiecutter.project_slug }}   # 渲染后按提示输入 adapter_name 等
pip install -e . --no-deps        # 安装进 rfauto 所在 venv
```

安装后 `rfauto` 侧经 `[project.entry-points."rfauto.adapters"]` 自动发现
（`ensure_adapter_plugins_loaded()`），适配器以字符串类型键
`"{{ cookiecutter.adapter_name }}"` 注册进 EMSolverRegistry。

## ⚠️ #362：entry-point 变更必须重装

`importlib.metadata` 读的是**安装时 dist-info 快照**——改过
`pyproject.toml` 的 entry-point 段后不重装，新插件对发现层不存在：

```bash
pip install -e . --no-deps   # entry-point 变更后必跑
python -c "from importlib.metadata import entry_points; \
print([ep.name for ep in entry_points(group='rfauto.adapters')])"
```

连带坑：测试里 `importlib.reload(registry)` 会清空注册表且缓存模块不重
执行 `@register` 装饰器——reload 类测试必须快照 `registry.__dict__` 并
finally 还原，否则"单跑绿、全量红"。

## #154：param_semantics 逐参数声明（必填）

同名参数跨适配器语义可能相反（wilkinson series/shunt 实证——单通道各
自"看着对"，跨保真就是两个器件家族）。适配器类上的
`param_semantics: dict[模板名][参数名] = 物理角色描述` 必须逐模板逐参数
声明；接入新通道先用 `rfauto` 的 `check_param_semantics` 断言互洽。

## #304：注册后必须同步核对消费者清单

注册表不是孤立登记——新增适配器键后逐项核对：

- `configs/solvers.yaml`：solver_type/通道配置（缺省会静默走默认）；
- `rfauto validate-adapter`（doctor 面契约自检，6 抽象方法 + 注册入口）；
- `tests/unit/test_adapter_kit.py` 的 `KNOWN_ADAPTERS`（内置适配器目录，
  第三方包可不进，但契约自检工具消费同一方法表）；
- EMSolverRegistry 消费面（`solver_capabilities_for` 按注册表反查能力
  声明——未声明 CAPABILITIES 的适配器会被显式 KeyError，不静默）。

## 验证 dry-run（确定性合成通道）

```python
from rfauto.adapters.em_solver_base import (
    EMSolverConfig, get_global_registry, ensure_adapter_plugins_loaded)

ensure_adapter_plugins_loaded()
reg = get_global_registry()
assert reg.is_registered("{{ cookiecutter.adapter_name }}")
ad = reg.create("{{ cookiecutter.adapter_name }}",
                EMSolverConfig(solver_type="{{ cookiecutter.adapter_name }}"))
assert ad.connect()
assert ad.build_geometry({"w_mm": 3.0})
result = ad.solve()
freq, sparams = ad.get_sparams()
ad.close()
```

骨架 `solve()` 产出**确定性合成 S 参数**（|S11|=0.1，非物理）——用于
链路验证；接入真实求解器时替换 `solve()`/`get_sparams()` 实现即可，
注册面与方法签名保持不变。
