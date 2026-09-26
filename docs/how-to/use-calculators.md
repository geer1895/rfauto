# 如何用 calc 计算器查闭式

**场景**：设计前要一条闭式公式的数值（衰减器电阻、Wilkinson 臂长、级联
预算……），或想用第二条独立代码路径交叉核对综合结果。

## 1. 看有什么计算器

```bash
rfauto calc list
```

每个键带参数自描述（名称/类型/单位/必填性），UI 表单与 MCP 工具表都从
同一清单生成。标 `[实验]` 的键（符号回归归纳公式等）默认列出但拒跑。

## 2. 跑一个计算器

参数用 `-p k=v`（可重复），单位口径 mm/GHz/Ω/dB：

```bash
rfauto calc run attenuator_pi -p attenuation_db=3.0 -p z0_ohm=50
```

实测输出：

```
attenuator_pi
  r_series_mid_ohm: 17.615
  r_shunt_end_ohm: 292.402
  note: π 型：中点串 r_series_mid，两端各对地 r_shunt_end
```

## 3. 脚本/agent 消费：service 层 JSON 进出

CLI/MCP/UI 都是薄壳，权威入口是 service 函数（JSON 进出，未知名/缺参/
参数不匹配一律 `ok=False + error`，不抛异常）：

```python
from rfauto.service.calculator_service import list_calculators, run_calculator

catalog = list_calculators()               # {"ok": True, "calculators": [...]}
out = run_calculator("microstrip_synthesis",
                     {"z0_ohm": 50, "freq_ghz": 2.4,
                      "epsilon_r": 3.66, "h_mm": 0.508})
assert out["ok"], out["error"]
print(out["result"]["width_mm"])           # 1.1117
```

数值只在确定性内核：service 层零物理公式，全部闭式来自
`src/rfauto/core/calculators.py` 的注册表（`CALCULATOR_REGISTRY`）。
agent/LLM 永远不产生数字，只发 typed tool call（分层铁律，见
docs/explanation/layered-architecture.md）。

## 4. 实验键的放行

```bash
rfauto calc run <实验键> --allow-experimental ...          # 命令行显式放行
```

或配置 `calculators.allow_experimental: true`（configs 三层优先级；
env `RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL`）。显式拒绝优先于配置放行
（`--no-experimental`）。

## 排错

- **未知名/缺参**：输出 `ok=False` + 中文 error，先 `rfauto calc list`
  核对参数名——参数自描述就是权威签名。
- **结果与综合差一位小数**：先核对单位口径（Hz vs GHz、mm vs m）与
  层叠参数（εr/h）是否同源；两条独立路径互差应 <1%，超出先查输入。
