# Optimetrics 参数扫描/优化/DOE

## 参数扫描 (Parametric)

### 基本用法
```python
# 添加参数扫描
param = hfss.parametrics.add(
    variable="arm_len",      # 变量名
    start_point=18,          # 起始值
    end_point=22,            # 终止值
    step=5,                  # 步长或数量
    variation_type="LinearCount",  # 线性计数
)

# 运行
param.analyze()
```

### 添加变化
```python
# 添加更多变量
param.add_variation(
    sweep_variable="series_w",
    start_point=0.2,
    end_point=0.5,
    step=0.1,
    units="mm",
    variation_type="LinearStep",
)
```

### 变化类型
- `"LinearCount"` — 线性计数（LINC）
- `"LinearStep"` — 线性步长（LIN）
- `"DecadeCount"` — 十倍计数（DEC）
- `"OctaveCount"` — 倍频程计数（OCT）
- `"ExponentialCount"` — 指数计数（ESTP）
- `"SingleValue"` — 单值

### 同步变量
```python
# 同步两个变量的变化
param.sync_variables(["arm_len", "series_w"], sync_n=1)
```

### 导出结果
```python
# 导出到 CSV
param.export_to_csv("parametric_results.csv")
```

### 从文件导入
```python
# 从 CSV/TXT 导入参数扫描
hfss.parametrics.add_from_file("variations.csv", name="my_parametric")
```

---

## 优化 (Optimization)

### 基本用法
```python
# 添加优化
opt = hfss.optimizations.add(
    calculation="dB(S(1,1))",
    ranges={"Freq": ("2.3GHz", "2.5GHz")},
    variables=["arm_len", "series_w", "shunt_w"],
    optimization_type="Optimization",
    name="my_optimization",
)

# 添加目标
opt.add_goal(
    calculation="dB(S(1,1))",
    ranges={"Freq": ("2.3GHz", "2.5GHz")},
    condition="<=",
    goal_value=-15,
    goal_weight=1,
)

# 添加变量范围
opt.add_variation(
    variable_name="arm_len",
    min_value=18,
    max_value=22,
    starting_point=20.5,
    min_step=0.1,
    max_step=1.0,
)

# 运行
opt.analyze()
```

### 优化类型
- `"Optimization"` — 标准优化
- `"DesignExplorer"` — 设计探索
- `"DXDOE"` — DOE 设计
- `"Sensitivity"` — 灵敏度分析
- `"Statistical"` — 统计分析
- `"optiSLang"` — optiSLang 集成

---

## 灵敏度分析 (Sensitivity)

```python
sens = hfss.parametrics.add(
    variable="arm_len",
    start_point=18,
    end_point=22,
    step=100,
    variation_type="LinearCount",
    name="my_sensitivity",
)
sens.analyze()
```

---

## 统计分析 (Statistical)

```python
stat = hfss.parametrics.add(
    variable="arm_len",
    start_point=19,
    end_point=21,
    step=1000,
    variation_type="LinearCount",
    name="my_statistical",
)
stat.analyze()
```

---

## 管理 Optimetrics

```python
# 列出所有参数扫描
for setup in hfss.parametrics.setups:
    print(f"{setup.name}: {setup.soltype}")

# 列出所有优化
for setup in hfss.optimizations.setups:
    print(f"{setup.name}: {setup.soltype}")

# 删除
hfss.parametrics.delete("my_parametric")
hfss.optimizations.delete("my_optimization")

# 获取设计 setups
hfss.parametrics.design_setups
hfss.optimizations.design_setups
```

---

## 内部属性

### SetupProps
```python
# 访问 setup 属性
setup.props["Sim. Setups"]  # 关联的 setup 列表
setup.props["Sweeps"]       # 扫描定义
setup.props["Goals"]        # 优化目标
setup.props["Variables"]    # 变量定义
```

### Goal 结构
```python
# Goal 字典结构
{
    "ReportType": "Standard",
    "Solution": "Setup1 : LastAdaptive",
    "SimValueContext": {"Domain": "Sweep"},
    "Calculation": "dB(S(1,1))",
    "Name": "dB(S(1,1))",
    "Ranges": {"Range": {"Var": "Freq", "Type": "rd", "Start": "2.3GHz", "Stop": "2.5GHz"}},
    "Condition": "<=",
    "GoalValue": {"GoalValueType": "Independent", "Format": "Real/Imag", "bG": ["v:=", "[-15;]"]},
    "Weight": "[1;]",
}
```