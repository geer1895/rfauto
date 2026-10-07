<!-- PR-10 文档站同步副本：源=docs/tutorials/extending-rfauto.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 扩展 rfauto：适配器、计算器、通道、模板四条标准路径

> 给 rfauto 加一个东西，全部走同一种模式：**基类 + 注册表**。本文给出
> 四条标准路径的入口、脚手架与交付清单，全部命令实测过。前置：
> docs/explanation/layered-architecture.md（分层架构——你加的东西落在
> 哪一层决定它能 import 什么）。

## 0. 两条通用约束

1. **分层不可破**：cli/mcp_server → service → linkage/optimization/
   models → adapters → pipeline → infra → core。依赖只能向左指，
   import-linter 在测试里强制——新文件放错层，全量门会红。
2. **新组件 = 基类 + 注册表**，不在调用点写 if/else 分发。下面四条
   路径都是这个模式的实例，照抄结构即可。

## 1. 加一个求解器适配器（主例）

适配器契约是 `adapters/em_solver_base.py` 的 `EMSolverAdapter` ABC：
六个抽象方法——`connect / is_available / build_geometry / solve /
get_sparams / close`。注册进 `EMSolverRegistry` 后，上层按名取用。

**不要从空文件写起**——用脚手架生成骨架：

```python
from rfauto.service.adapter_kit import scaffold_adapter

scaffold_adapter("my_solver")        # 不覆盖既有文件，落盘前先编译自检
# → {'ok': True, 'path': 'src/rfauto/adapters/my_solver_adapter.py',
#    'class_name': 'MySolverAdapter', 'register_fn': 'register_my_solver',
#    'contract_methods': [connect, is_available, build_geometry,
#                         solve, get_sparams, close]}
```

骨架自带六方法占位、`param_semantics` 语义清单位和 `register_my_
solver()` 注册入口。实现完两类检查兜底：

```python
from rfauto.service.adapter_kit import check_adapter_contract, check_known_adapters

check_adapter_contract(MySolverAdapter)   # 单类契约检查（缺方法即报）
check_known_adapters()                    # 全仓适配器体检
```

实测 `check_known_adapters()` 当前覆盖六个适配器（openems/comsol/
mmt/palace/vna/ads），EMSolver 契约面的条目形如：

```python
{'ok': True, 'class': 'OpenEMSSolver', 'missing': [],
 'methods': ['connect', 'is_available', 'build_geometry',
             'solve', 'get_sparams', 'close'], 'contract': 'emsolver'}
```

注意 ads 条目 `contract: 'ads_python_api'`——它走原生 Python API
子进程通道、非 EMSolverAdapter 契约，体检如实分开标注，不硬套六方法。

**交付清单**：注册入口在模块 import 时执行（import-linter 面可达）；
单测至少钉 connect/is_available 的 skip 条件与 build_geometry 的
入参收敛；真机冒烟参照 docs/how-to/run-openems-smoke.md 的"先离线
审计再真跑"纪律。

## 2. 加一个闭式计算器

计算器是纯函数（数值只在确定性内核——LLM/agent 永不产生物理数字），
注册用装饰器（`core/calc_families/registry.py`）：

```python
from rfauto.core.calc_families.registry import register_calculator

@register_calculator(
    "my_formula",                       # 键名（CLI/MCP 消费）
    "一句话语义描述（含口径与出处）",     # description
    params=(("freq_ghz", "频率 GHz"),   # 参数自描述（--help 面）
            ("w_mm", "线宽 mm")),
    required=("freq_ghz",),             # 必填参数
    experimental=False,                 # True=默认拒跑，需显式放行
    reciprocal=True,                    # 非互易器件显式 False
)
def my_formula(**kw: float) -> dict[str, float]:
    ...                                  # 返回 dict（键=输出量名）
```

**消费者五钉清单（新手最常漏，漏了定向测试绿、合流全量门红）**：

| 钉 | 位置 |
|---|---|
| 1 | tests/unit/test_calculators.py 的 `EXPECTED` 键集 |
| 2 | tests/unit/test_physics_invariants.py 的每键输入表 |
| 3 | tests/unit/test_model_docs.py 的文档面 |
| 4 | tests/unit/test_experimental_calculators.py（experimental 键；计数用 `len(EXPECTED)` 单源，勿写字面数） |
| 5 | docs 三处文档面的数字实测更新 |

新键落地即跑这四个测试文件，再补文档。锚注册表（`core/anchors.py`
的 `EXPECTED_ANCHORS`）用的是同款单源计数钉——消费者清单的完整
对照见 docs/tutorials/anchor-guide.md 第 5 节。

## 3. 加一个求解通道（战役面）

战役外环（tune/sweep 真跑）的通道注册表在 `optimization/
adapter_channels.py`——它与 EMSolverRegistry 分工不同：

| 注册表 | 值 | 语义 |
|---|---|---|
| `EMSolverRegistry` | 类 | 均匀六方法契约，适配器层 |
| `_CHANNEL_FACTORIES` | 工厂函数 | 吸收各通道构造签名差异（fake/openems 吃频段+点数，hfss 走安装探测），战役层 |

```python
from rfauto.optimization.adapter_channels import register_channel, channel_names

register_channel("my_channel", my_factory)   # 幂等，后注册者胜
channel_names()        # → ('fake', 'hfss', 'openems')
```

工厂签名：入参=optimizer 的公共预处理结果，返回
`(adapter | None, 版本串)`。惰性导入面（工厂体内 import）配合
sys.modules 钉死测试。

## 4. 加一个 openEMS 模板

模板单源在 `adapters/oe_templates/registry.py`：`TEMPLATE_META`
（71 模板：几何参数表/端口轴/网格口径）与 `TEMPLATE_NOMINAL`
（名义值表），经 `adapters/openems_templates.py` re-export 消费。

两条铁律（都有历史代价，别再付）：

1. **名义几何值全部综合引擎精算**（微带用 Hammerstad-Jensen 综合），
   禁止从其他模型/文档抄毫米数——手算捷径造成的名义频偏达 −10%
   量级。
2. **离线几何审计必过再真跑**：渲染脚本 exec 到建模段，判据落在
   CSXCAD 实测对象（原语非零体积/端口激励非零/连通性/网格间距），
   走法见 docs/tutorials/real-simulation.md 第 3 节。

**交付清单（模板注册的消费者五钉）**：

| 钉 | 位置 |
|---|---|
| 1 | tests/unit/test_template_meta_consistency.py（TEMPLATE_NOMINAL ↔ docs/templates/<t>/meta.yaml 逐键一致） |
| 2 | tests/unit/test_template_geometry_audit.py（EXPECTED_TEMPLATES 全量计数，单源 `len(TEMPLATE_META)`） |
| 3-5 | 三处模板计数字面改单源（勿写 `== 71`） |

外加：模板定向单测 `tests/unit/test_<模板>_template.py`（几何审计
门槛）、docs/templates/<模板>/meta.yaml 落盘。

## 5. 练习

1. `scaffold_adapter("toy")` 生成骨架，读一遍六个方法占位的 docstring
   契约，然后删掉骨架文件（它有 register 入口，留着会被发现层扫到）。
2. `check_known_adapters()` 数一数 EMSolver 契约面与 ads 通道面的
   条目差异，解释为什么体检不把它们硬塞进同一契约。
3. 对照第 2 节五钉清单，在仓里找出全部五处消费者文件（grep 键名）。

## 6. 下一步

- 分层为什么这样设计：docs/explanation/layered-architecture.md
- 适配器真跑纪律：docs/how-to/run-openems-smoke.md
- 模板离线审计实操：docs/tutorials/real-simulation.md
- 新适配器的引擎偏差如何变成锚（跨引擎换算基准的登记与消费）：
  docs/tutorials/anchor-guide.md
- 命令/模块权威出处：docs/reference.md
