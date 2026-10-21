<!-- PR-10 文档站同步副本：源=docs/how-to/registry-kit.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何用 RegistryKit 搭一个新注册面（不手写 dict+register 样板）

**场景**：你要新增一个"名字 → 实现类/函数"的注册面（求解器、代理模型、
lint 检查、预算项、模板规格……），或者要把一个手写的 `_registry dict +
register()/get()/keys()` 类迁移到统一脚手架。全仓 35+ 注册面、同构手写
11 处（R1 架构审计实测）——RegistryKit 把这份样板收敛为一个百行级
Generic 容器，新面直接继承/组合，不再各写一遍。

## 1. 是什么、在哪导入

```python
from rfauto.core.registry_kit import RegistryKit   # 新代码一律 core 侧
```

本体在 `src/rfauto/core/registry_kit.py`（纯 stdlib、零第三方依赖的
`Generic[V]`，分层合法的最低层）。`rfauto.infra.registry_kit` 保留
re-export 兼容入口（**同一类对象非拷贝**），既有 infra 侧导入路径不变
——但新代码从 core 导入；给 Kit 加能力改 core 本体，不动 infra 入口。

何时用它 vs `@register_calculator` 那类专用装饰器：专用注册表
（CALCULATOR_REGISTRY 等）有自己的消费者契约（金快照/计数面/文档再生），
照 docs/how-to/add-new-calc-key.md 走；RegistryKit 管**没有专用装饰器
的普通注册面**——架构审计里"又一个手写 Registry 类"都该是它。

## 2. 三种注册形态（同一入口收口）

```python
reg = RegistryKit(label="子检查")

@reg.register("my_check")        # 形态①：显式名键装饰器（即刻验重）
def my_check(...): ...

@reg.register                    # 形态②：裸装饰器（键取 obj.name，
class MyImpl:                    #   缺失回退 obj.__name__）
    name = "my_impl"

reg.register("other", obj)       # 形态③：直调登记（返回 obj 原样）
```

读取/消费：

```python
reg.get("my_impl")               # 缺名 KeyError（文案带 label+可用键清单）
reg.get("nope", default=None)    # 缺名回退缺省值（区分"未传"与"传 None"）
reg.create("my_impl", x=1)       # 取出并调用（工厂/类注册面实例化）
reg.keys()                       # 缺省字典序；ordered=True 时=登记序
"my_impl" in reg, len(reg)       # 容器协议
```

维护/对账：`unregister(key)`（缺名静默 no-op，测试清理用）、
`snapshot()`（快照拷贝，金快照/消费者对账用，改动不回注本体）。

## 3. 构造参数：迁移旧面时逐项保真

```python
RegistryKit(
    label="代理类型",             # 进错误文案
    key_attr="name",             # 形态②取键属性
    allow_overwrite=False,       # False=重名 ValueError（编程错误视角）
    missing_fmt="未注册的{label}: {key}（可用: {keys}）",
    dup_fmt="{label}重复注册: {key}",
    allow_non_str_keys=False,    # True=键面放开为任意 hashable
    ordered=False,               # True=keys() 返回登记序
)
```

- **重名策略是语义差异不是口味**：`False`（ValueError）是
  LintCheck/CALCULATOR 惯例；`True`（静默覆盖）是 EMSolver/surrogate
  的历史语义。迁移旧面按旧面行为选，别"顺手改对"——那是对外可观测
  行为变更；
- **文案模板占位符**：`{label}/{key}/{keys}`（逗号连接）与
  `{keys_list}`（整列表 repr，带方括号引号）并存，覆盖两类历史文案
  形态；未引用的占位符不受影响；
- `allow_non_str_keys=True` 服务"枚举键 ∪ 自定义字符串键"混排口径
  （EMSolverRegistry 先例）；缺省 False 保持 str 键强校验。

## 4. 已迁面清单（找先例对号入座）

试点三面（行为与迁移前逐字节一致）：`service/design_lint_service.py`
（LintCheckRegistry）、`optimization/surrogate/base.py`
（SurrogateRegistry）、`adapters/em_solver_base.py`（EngineRegistry，
枚举键面=`allow_non_str_keys` 先例）。其后扩面：
`core/calc_families/registry.py`（Calculator）、`core/error_budget.py`
（Budget，`{keys_list}` 文案先例）、`models/template_spec.py`
（TemplateSpec）、`service/agent_runtime.py`/`agent_safety.py`/
`topology_service.py`/`systemone_service.py`/
`hierarchical_scheduler.py`、`adapters/fab_export/base.py`。
新增注册面前先 grep 这份清单——大概率已有同形先例可抄构造参数。

## 5. 定向测试

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_registry_kit.py -q
```

迁移类改动同时跑被迁移面的自有定向测试（行为保真断言住那边）。

## 6. 高频坑位

- **以为 Kit 会替你发现插件**：它是纯数据容器，不做 import 副作用、
  不做 entry-point 发现——注册仍由各模块 import 期显式执行；新模块
  命名空间=新 Kit 实例=空表（#362 家族）。配套铁律：entry-point 变更
  必须 `pip install -e . --no-deps` 重装，否则注册表读的是安装时
  dist-info 快照，"单跑绿全量红、缺谁取决于元数据龄"；测试里
  `importlib.reload(registry)` 必须快照 `reg.__dict__` 并 finally 还原；
- **keys() 排序口径混用**：缺省字典序（全部既有面），`ordered=True`
  是登记序（dict 插入序）——枚举键∪字符串键混排时二者不可互比排序
  （sorted 会 TypeError）。测试断言/快照对账统一走 `keys()`，别直接
  摸内部 dict；
- **别给本模块补 `__all__`**：public_api 金快照口径下无 `__all__` 记
  私有——加 `__all__` 会给金快照新增条目，那是显式评审动作，不是
  顺手清理。
