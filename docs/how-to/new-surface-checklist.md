# 新增面消费钉清单（合流前自证）

> 给 rfauto 加任何一个新面（CLI 叶/MCP 工具/计算器键/模板/引擎），都有一组
> "只跑本项定向测试绿灯、合流全量门必红"的消费者钉（#231/#df6② 制度化）。
> 本文是对照速查；四条标准路径的完整教程见
> `docs/tutorials/extending-rfauto.md`。

## 通用自证三步

1. 改完先跑本项定向测试（自建 `tests/unit/test_<面>_*.py`）；
2. 对照下表逐钉补齐——**漏钉的形态一律是"定向绿、合流红"**；
3. 返回前跑 `scripts/merge_preflight.py`（~2 分钟：计数全链+金快照+
   docs_site 再生差异+信封契约+help 卫生），漂移红当场自愈。

## CLI 新叶

| 钉 | 位置 |
|---|---|
| 1 | `--json` 旗标必带（test_w2_c_json_coverage 棘轮门，只收不放） |
| 2 | test_check_numbers 的 `count_cli()` 锚（数字以实测为准，勿手抄旧值） |
| 3 | test_cli 注册面（同名遮蔽 zero-shadow 钉；新增子应用先 grep 顶层同名） |
| 4 | test_cli_registration_order 注册序金快照（变动后 `--write-gold` 重生成+评审） |
| 5 | docs_site 机读页再生（`scripts/build_docs_pages.py`，cli.md 树同步） |

help 文案禁 `[` 与 `%`（argparse _expand_help 对 `%` 直接抛错，#305）。

## MCP 新工具

| 钉 | 位置 |
|---|---|
| 1 | test_mcp_server 计数与名单集 |
| 2 | test_mcp_tool_consistency 常量（含逐工具可调用性双检） |
| 3 | mcp.md 机读页再生（build_docs_pages 同批） |
| 4 | MCP/服务一致性（dis LOAD_GLOBAL 静态双检抓 NameError 死壳，#270） |
| 5 | docstring 五段结构（Returns 键集对拍，W6-C 口径） |

## 计算器新键

| 钉 | 位置 |
|---|---|
| 1 | tests/unit/test_calculators.py 的 EXPECTED 键集 |
| 2 | tests/unit/test_physics_invariants.py 每键输入表（双向一致性） |
| 3 | tests/unit/test_model_docs.py 文档面 |
| 4 | test_experimental_calculators（experimental 键；计数用 len 单源） |
| 5 | kernel_cards 与 docs_site 双再生（build_kernel_cards + build_docs_pages） |

50Ω 宽/名义值禁手抄字面量（test_width_single_source 守卫）——走
`core/synthesis.nominal_width_mm` 单源或 None 哨兵惰性求值。

## 新模板

| 钉 | 位置 |
|---|---|
| 1 | tests/unit/test_template_meta_consistency.py（TEMPLATE_NOMINAL ↔ meta.yaml 逐键） |
| 2 | tests/unit/test_template_geometry_audit.py（EXPECTED_TEMPLATES，len 单源） |
| 3 | 三处模板计数字面（一律改 len(TEMPLATE_META) 单源，勿写 ==N） |
| 4 | docs/templates/<名>/meta.yaml（nominal_params 全部综合精算，#1c/#252） |
| 5 | 离线几何审计测试（#212：渲染→exec→CSXCAD 实测判据） |

速查：`rfauto dev new-template <名>` 生成骨架包+清单落盘（SO §7 P5）。

## 新引擎（适配器）

| 钉 | 位置 |
|---|---|
| 1 | EMSolverAdapter 六方法契约（check_adapter_contract） |
| 2 | check_known_adapters 全仓体检（含非 EMSolver 通道的如实分标） |
| 3 | 注册入口 import 时执行（发现层面可达） |
| 4 | 通道注册表（optimization/adapter_channels，战役面工厂） |
| 5 | 真机纪律（见 docs/how-to/add-new-solver-engine.md） |

## 金快照三类（涉及时必重生成）

public_api（新模块 `__all__` 纯增量后 `--generate`+评审）、注册序
（test_cli_registration_order `--write-gold`）、capability_cards/gallery。
