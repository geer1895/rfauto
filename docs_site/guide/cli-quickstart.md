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

## 5. 下一步

- 30 分钟完整教程：[getting-started](../tutorials/getting-started.md)
- 优化/扫描语义与判据门：仓内 `docs/how-to/` 系列
- 分层架构与"为什么这样设计"：[架构与方法论](../architecture/methodology.md)
