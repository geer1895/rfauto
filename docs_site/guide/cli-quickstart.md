# CLI 快速上手

> 本文只讲"高频命令怎么串成一条链路"。逐命令的完整参数表见
> [CLI 命令参考](../reference/cli.md)（机读生成，与代码实注册同源）；
> 每条命令的权威口径始终是 `rfauto <命令> --help`。

## 0. 心智模型

rfauto 的命令面围绕一条主链路组织：

```
doctor → syn/compose（设计） → run/sweep/tune（求解与外环）
       → report/explain（判读） → fab/export（交付）
```

配方（YAML）是贯穿件：设计变量、适配器选择、判据门都写在配方里，
`run`/`sweep`/`tune`/`autotune` 消费同一份配方。

## 1. 环境与模型

```bash
rfauto doctor                 # AEDT/ADS 版本、license、路径探测
rfauto models list            # 已注册模型插件
rfauto validate <recipe.yaml> # 配方静态校验（schema/引用/判据）
```

## 2. 设计与综合

```bash
rfauto syn mline 50.0 --freq 2.4 --stackup rogers4350b_h0.508
rfauto calc run attenuator_pi -p attenuation_db=6 -p z0_ohm=50
rfauto calc list              # 确定性计算器全清单（实验键需显式开关）
```

`calc` 是闭式计算器入口——物理数值只出自确定性内核，可直接当设计
依据，也能与仿真结果交叉核对。

## 3. 求解与外环

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake   # 首跑（离线近似）
rfauto sweep recipes/wilkinson_pd_v1.yaml --method auto --coarse 15
rfauto tune  recipes/wilkinson_pd_v1.yaml                # Optuna 外环
rfauto autotune recipes/wilkinson_pd_v1.yaml --n-trials 40
```

`fake` 适配器不需要 HFSS/ADS 许可证，是验证链路与配方语义的首选通道；
换 `--adapter hfss` 走真机求解（版本配对与环境探测见 `rfauto doctor`）。

## 4. 判读与交付

```bash
rfauto report <run-dir>       # 健康度体检 + 汇总
rfauto explain-run <run-dir>  # 运行解释（叙事面）
rfauto sparams-compare a.s2p b.s2p   # 曲线对拍
rfauto fab go --vars part_vars.json --rules rules/<x>.yaml  # 机加交付包
```

## 5. AEDT 版本批量迁移（aedt-migrate）

合作者遗留的老版本 `.aedt` 工程（如 2021 时代）迁移到本机统一使用的
AEDT 2025 R1，走 `aedt-migrate` 域三叶（五阶段决策树：直开→体检→
对比→桥接→抢救，每工程产出结构化迁移报告）：

```bash
rfauto aedt-migrate run --input <file|dir> [--work-root DIR] [--json]
rfauto aedt-migrate status --report <path> [--json]   # 结构化摘要
rfauto aedt-migrate report --report <path> [--json]   # 人读全文
```

`run` 递归收集 `*.aedt`，盘点（sha256+备份规划）后逐工程决策树，报告落
`<work-root>/reports/`；原 `.aedt` 全程只读，一切产物落 work-root。重跑
幂等：`MIGRATED_*`（已完成）自动跳过，`FAILED_*`/`BLOCKED_*` 允许重跑。
`verdict` 枚举（诚实终态，零凑绿）：

| verdict | 语义 |
| --- | --- |
| MIGRATED_DIRECT_PASS | 2025 R1 直开+体检+新旧对比达标 |
| MIGRATED_DIRECT_FAIL_COMPARISON | 迁移成功但新旧结果对比超差（如实红） |
| MIGRATED_VIA_BRIDGE_PASS | 经 2023 R2 桥接后全链达标 |
| NEEDS_CAD_REEXPORT | 几何需老版本导出 Parasolid/STEP 抢救重建 |
| NO_BASELINE | 原件无已存解，新旧对比无基线（如实，不伪造） |
| FAILED_OPEN / FAILED_HEALTH / FAILED_BRIDGE | 直开/体检/桥接链失败（附消息原文） |
| BLOCKED_NO_BRIDGE_HOST | 桥接机（2023 R2）未配置——前提不满足，非失败 |

MCP 侧同名两面 `aedt_migrate_run`/`aedt_migrate_report` 供 agent 消费。

## 6. 下一步

- 30 分钟完整教程：[getting-started](../tutorials/getting-started.md)
- 优化/扫描语义与判据门：仓内 `docs/how-to/` 系列
- 分层架构与"为什么这样设计"：[架构与方法论](../architecture/methodology.md)
