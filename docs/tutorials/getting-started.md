# 入门：30 分钟跑通第一条链路

> 本文每条命令都在开发环境实测过（退出码 0）。你将完成：安装 → 认识
> CLI → 综合第一条微带线 → 用闭式计算器交叉核对 → 跑一次 fake 仿真 →
> 读结果与健康度体检。全程不需要 HFSS/ADS 许可证（fake 适配器离线近似）。

## 0. 前置

- Python ≥3.10，<3.13（项目按 3.12 开发）。
- git（拉源码用）。

## 1. 安装（约 5 分钟）

```bash
git clone <repo-url> rfauto && cd rfauto
python -m venv .venv
# Windows（git-bash）
source .venv/Scripts/activate
# Linux/macOS 用 source .venv/bin/activate
pip install -e .
```

`-e`（editable）装完即用，源码改了立即生效。可选 extras：`[dev]`（开发
依赖）、`[mcp]`（MCP Agent 接口，见 README「MCP Agent 接口」节）。

## 2. 认识 CLI（1 分钟）

```bash
rfauto --help
```

实测输出（节选）：命令面板按动词分组——`doctor`（环境探测）、
`run/sweep/tune/refine`（仿真与优化外环）、`syn`（微带综合）、
`calc`（闭式计算器）、`runs`（产物体检）、`models`（模型管理）等。
任何子命令加 `--help` 看参数，例如 `rfauto syn mline --help`。

## 3. 第一个综合：50Ω 微带线（2 分钟）

```bash
rfauto syn mline 35.35 --freq 2.4
```

实测输出：

```
微带线综合结果 (rogers4350b_h0.508 @ 2.4 GHz)
  目标阻抗: 35.35 Ω
  线宽:     1.8707 mm
  实际阻抗: 35.35 Ω
  εeff:     2.9804
  ΔZ0:      0.0000 Ω
  状态:     ok
```

读法：目标是 Wilkinson 功分器的 70.7/50Ω 家族里的 35.35Ω 分支——综合器
用 Hammerstad-Jensen 闭式 + brentq 反解出线宽，再把线宽**回代**正向模型
得到"实际阻抗"，ΔZ0 是自洽性残差（>0.5Ω 会标 `needs_calibration` 提醒，
不会静默通过）。层叠缺省 `rogers4350b_h0.508`，可换：

```bash
rfauto syn mline 50.0 --freq 2.4 --json
```

实测输出（JSON 面供脚本消费，退出码仍是唯一成败判据）：

```json
{
  "z0_target": 50.0,
  "freq_ghz": 2.4,
  "stackup": "rogers4350b_h0.508",
  "width_mm": 1.1133,
  "z0_actual": 50.0,
  "epsilon_eff": 2.853,
  "status": "ok",
  "delta_z0": 0.0
}
```

层叠清单在 `configs/materials.yaml`（带 source/verified_by 出处字段）。

## 4. 用闭式计算器交叉核对（2 分钟）

综合结果不是孤证——用 `calc` 计算器独立复算同一设计：

```bash
rfauto calc run microstrip_synthesis -p z0_ohm=50 -p freq_ghz=2.4 -p epsilon_r=3.66 -p h_mm=0.508
```

实测输出：

```
microstrip_synthesis
  width_mm: 1.1117
  z0_actual_ohm: 50.0
  eps_eff: 2.8579
  status: ok
  lambda_g_mm: 73.891
```

线宽 1.1117 vs 综合 1.1133 mm——两条独立代码路径互差 <0.2%。计算器全部
清单与参数自描述：`rfauto calc list`（衰减器/功分器/级联预算等；标
`[实验]` 的键默认拒跑，需 `--allow-experimental` 显式放行）。

## 5. 跑一次仿真：fake 适配器（5 分钟）

```bash
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake
```

实测输出（run_id 每次不同）：

```
✓ 仿真完成  run_id: 20260925_062950_1a6365e9
  run 目录: runs/20260925_062950_1a6365e9
  cost: 7.424965102246688
  指标:
    s11_db_max_in_band: -8.0835
    s11_db_min_in_band: -10.2581
    s21_db_mean_in_band: -4.1084
    iso_s23_db_min_in_band: 25.4717
```

`--adapter fake` 是解析近似通道（无电磁求解器，秒级），用来把"配方 →
仿真 → 指标 → cost"全链路走通。`--adapter hfss` 才是真实 AEDT 全链
（需要许可证与环境，见 `rfauto doctor`）。正式跑之前建议先校验配方：

```bash
rfauto validate recipes/wilkinson_pd_v1.yaml   # 只校验不执行
rfauto run recipes/wilkinson_pd_v1.yaml --adapter fake --dry-run  # 输出执行计划
```

## 6. 读结果：健康度体检（5 分钟）

每次 run 落一个 `runs/<run_id>/` 目录。用 G11 体检门读它：

```bash
rfauto runs health 20260925_062950_1a6365e9
```

实测输出（节选，fake run 也走同一判据链）：

```
┌──────────┬────────┬──────┬──────────────────────────────┐
│ 检查项   │ 状态   │ 依据 │ 说明                         │
├──────────┼────────┼──────┼──────────────────────────────┤
│ ...      │ PASS   │ ...  │ SpecEvaluator 口径逐项判读   │
│ gain     │ PASS   │ 插损 │ -4.462 dB ≤ 0.5 dB，无非物理 │
└──────────┴────────┴──────┴──────────────────────────────┘
  verdict: healthy  ok=True
```

判读要点：`verdict` 取 healthy / suspect / unhealthy，退出码与之一致
（healthy=0），可直接进 CI 门禁；`--json` 出原始 JSON。状态为 UNKNOWN
的检查项是"证据不足、如实不判"（比如 fake run 没有场 dump 就不评功率
守恒），不是通过也不是失败。逐项含义与历史教训编号见
`rfauto runs health --help` 与 docs/reference.md 指针。

## 7. 下一步

- 想跑真实 openEMS 冒烟：docs/how-to/run-openems-smoke.md
- 想做链路预算/混频杂散规划：docs/how-to/cascade-budget-and-spur.md
- 想读懂体检门判据：docs/how-to/read-verdict-gates.md
- 架构分层为什么这样设计：docs/explanation/layered-architecture.md
- 全部命令与模块的权威出处（单一事实源）：docs/reference.md
