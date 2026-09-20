# 变量管理 + HPC 选项 + 批处理求解

## 变量管理

### 设置变量
```python
# 设计变量（局部）
hfss["w"] = "1.1mm"
hfss["l"] = "20mm"
hfss["h"] = "0.508mm"

# 项目变量（全局，以 $ 开头）
hfss["$project_var"] = "50"
hfss["$ambient_temp"] = "22cel"
```

### 访问变量
```python
# 获取变量对象
var = hfss.variable_manager["w"]
var.numeric_value  # 数值 (float)
var.units          # 单位 (str)
var.expression     # 表达式 (str)

# 变量列表
hfss.variable_manager.independent_variables  # 独立变量
hfss.variable_manager.dependent_variables    # 依赖变量
hfss.variable_manager.variable_names         # 所有变量名
hfss.variable_manager.independent_variable_names  # 独立变量名
```

### 变量属性
```python
var = hfss.variable_manager["w"]

# 优化相关
var.optimization_min_value = "0.5mm"
var.optimization_max_value = "2.0mm"
var.optimization_enabled = True

# 调谐相关
var.tuning_min_value = "0.5mm"
var.tuning_max_value = "2.0mm"
var.tuning_enabled = True

# 灵敏度相关
var.sensitivity_min_value = "0.5mm"
var.sensitivity_max_value = "2.0mm"
var.sensitivity_enabled = True

# 统计相关
var.statistical_min_value = "0.5mm"
var.statistical_max_value = "2.0mm"
var.statistical_enabled = True
var.statistical_sigma = 3
```

### 激活变量
```python
# 激活变量用于优化
hfss.activate_variable_optimization("w")
hfss.activate_variable_tuning("w")
hfss.activate_variable_sensitivity("w")
hfss.activate_variable_statistical("w")
```

### 解析表达式
```python
# 解析带单位的表达式
value, unit = decompose_variable_value("1.1mm")  # (1.1, "mm")
value, unit = decompose_variable_value("2.4GHz")  # (2.4, "GHz")

# 检查是否为数字
is_number("1.1mm")  # False
is_number("1.1")    # True

# 单位转换
from ansys.aedt.core.generic.constants import unit_converter
value = unit_converter(
    values=1.0,
    unit_system="Length",
    input_units="mm",
    output_units="meter",
)
```

---

## HPC 选项

### 自定义 HPC
```python
hfss.set_custom_hpc_options(
    cores=4,           # 核心数
    tasks=2,           # 任务数
    gpus=1,            # GPU 数
    num_variations_to_distribute=4,  # 分布式变体数
    allowed_distribution_types=["Nominal"],  # 允许的分布类型
    use_auto_settings=True,  # 使用自动设置
)
```

### 从文件设置 HPC
```python
hfss.set_hpc_from_file(
    acf_file="custom_hpc.acf",
    configuration_name="my_config",
)
```

### 监控仿真状态
```python
# 检查是否有仿真在运行（需要 AEDT 2023R2+）
hfss.are_there_simulations_running

# 获取监控数据
hfss.get_monitor_data()

# 停止仿真
hfss.stop_simulations(clean_stop=True)
```

---

## 批处理求解

### 基本批处理
```python
hfss.solve_in_batch(
    cores=4,
    tasks=1,
    machine="localhost",
    blocking=True,  # 阻塞等待完成
)
```

### 提交到集群
```python
job_id = hfss.submit_job(
    cluster_name="my_cluster",
    aedt_full_exe_path="/path/to/ansysedt.exe",
    nodes=1,
    cores=32,
    wait_for_license=True,
)
```

---

## 变体管理

### 获取变体
```python
# 获取可用变体
variations = hfss.available_variations.variations(
    hfss.existing_analysis_sweeps[0],
    output_as_dict=True,
)

# 标称变体
nominal = hfss.available_variations.nominal_variation()
nominal_values = hfss.available_variations.nominal_values

# 所有变体
all_vars = hfss.available_variations.all
```

### 应用变体
```python
# 应用已解决的变体
hfss.apply_solved_variation({"arm_len": "20.5mm", "series_w": "0.33mm"})
```

### 变体字符串
```python
# 转换为 AEDT 格式
var_str = hfss.available_variations.variation_string({"w": "1.1mm", "l": "20mm"})
# 结果: "w='1.1mm' l='20mm'"
```

---

## 输出变量

### 创建输出变量
```python
hfss.create_output_variable(
    variable="s11_db",
    expression="dB(S(1,1))",
    solution="Setup1 : LastAdaptive",
)
```

### 获取输出变量
```python
value = hfss.get_output_variable("s11_db")
```

### 列出输出变量
```python
hfss.output_variables  # list[str]
```

---

## 属性修改

### 修改对象属性
```python
hfss.change_property(
    aedt_object=hfss.oeditor,
    tab_name="BaseElementTab",
    property_object="Box1",
    property_name="Xpos",
    property_value="0mm",
)
```

### 批量修改属性
```python
hfss.change_properties(
    aedt_object=hfss.oeditor,
    tab_name="BaseElementTab",
    property_object="Box1",
    property_names=["Xpos", "Ypos", "Zpos"],
    property_values=["0mm", "1mm", "2mm"],
)
```