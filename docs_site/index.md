# rfauto 文档站

> **rfauto** —— HFSS ↔ ADS 自动化仿真调优框架：把射频工程师的日常仿真
> 操作（建模 → 求解 → 判读 → 校准 → 优化 → 交付）收进一条可复现、可审计、
> 多保真仲裁的自动化链路。

## 它解决什么问题

- **多求解器支持**：HFSS（对齐基准）、ADS（有源链真机）、openEMS（快速
  FDTD），经 `EMSolverAdapter`/`EMSolverRegistry` 可插拔扩展。
- **数值只在确定性内核**：频率/损耗/几何数值只由确定性求解器、综合引擎或
  评判器产出；LLM/agent 只编排与解释，永不产生物理数字。
- **优化外环**：TPE/CMA-ES/NSGA-II（Optuna 系）+ warm-start + UQ/Sobol/
  GP 代理，全部走 service 层确定性判读。
- **MCP 协议**：AI 代理可经 MCP 工具面控制仿真全流程（见
  [MCP 工具参考](reference/mcp.md)）。
- **可复现与可审计**：run 指纹、provenance 账本、健康度体检门、锚体系
  （标定锚/仲裁锚）全链留痕。

## 快速开始

```bash
pip install -e .          # 安装（可选 extras：[dev] [hfss] [mcp] [ui] [docs]）
rfauto doctor             # 环境探测
rfauto syn mline 50.0 --freq 2.4 --stackup rogers4350b_h0.508   # 微带线综合
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake          # fake 通道首跑
```

完整上手路径见[用户指南：30 分钟跑通第一条链路](tutorials/getting-started.md)。

<!-- AUTO-NUMBERS:START -->
## 代码面数字（构建时实测）

以下数字由 `scripts/build_docs_pages.py` 构建时实测回填（与 `scripts/check_numbers.py` 同源，零手写——#97）:

| 维度 | 数量 |
|---|---|
| 全量门测试 | 21900 |
| CLI 叶子命令 | 254 |
| MCP 工具 | 149 |
| 确定性计算器（含实验键） | 100（101） |
| 器件模板 | 71 |
| 标定锚注册表 | 60 |

（tests 计数来源：README badge floor（环境无关））
<!-- AUTO-NUMBERS:END -->

## 站点导航

| 分区 | 内容 |
|---|---|
| [用户指南](tutorials/getting-started.md) | 安装、CLI 快速上手、首条链路 |
| [锚导览](tutorials/anchor-guide.md) | 物理标定锚：是什么、为什么可信、怎么查、怎么消费 |
| [真机仿真](tutorials/real-simulation.md) | 第一个 openEMS 求解点：离线审计 → 真跑 → 判读 |
| [RECAST 走查](tutorials/recast-walkthrough.md) | 归档判读的判据重放（可复算性对照） |
| [扩展 rfauto](tutorials/extending-rfauto.md) | 适配器/计算器/通道/模板四条标准路径 |
| [参考](reference/cli.md) | CLI 命令 / MCP 工具 / 计算器注册表机读清单 |
| [模板库](catalog/index.md) | 器件模板聚合（参数、名义值、抽取判据） |
| [架构与方法论](architecture/methodology.md) | 分层架构、锚体系、判据先行 |

## 许可与定位

MIT License。本站由 mkdocs-material 构建；所有统计数字构建时从代码面
实测回填（与 `scripts/check_numbers.py` 同源），不沿用上一份文档。
