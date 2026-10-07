# {{ cookiecutter.project_slug }}

rfauto metric/benchmark 插件（AgentBench 任务集 + 确定性指标计算 + 参考提供器）。

与 solver_adapter / template_family 两模板不同：本插件**不挂 entry-point
发现口**——rfauto 当前对基准面没有 `importlib.metadata` 发现组（诚实口径，
不造假接线）；消费=显式路径/显式导入，见下。

## 包内容

- `bench_sets/{{ cookiecutter.bench_name }}_public.yaml`：AgentBench 兼容任务集
  （schema v1；`service/agent_bench.load_bench_set(path=...)` 直读，字段校验
  family/artifacts/numeric 三关）；
- `{{ cookiecutter.module_name }}/metrics.py`：确定性指标计算函数（从 S 参数
  产物提取 `expected.numeric` 里的 metric 值——**数值只在确定性内核产出**
  ，LLM/agent 永不产生物理数字）；
- `{{ cookiecutter.module_name }}/provider.py`：离线参考提供器
  （`run_agentbench_regression(trajectory_provider=...)` 注入点；回放任务期望，
  仅作门自洽正控，不构成对真实 agent 质量的判据）。

## 快速开始

```bash
pip install cookiecutter          # 渲染（一次性）
cookiecutter /path/to/rfauto/tools/plugin_templates/metric_benchmark
cd {{ cookiecutter.project_slug }}
pip install -e . --no-deps
```

## 消费接线（显式，无发现口）

```python
from pathlib import Path
from rfauto.service.agent_bench import (
    evaluate_agentbench, load_bench_set, run_agentbench_regression,
)
from {{ cookiecutter.module_name }}.provider import reference_provider
from {{ cookiecutter.module_name }} import metrics

set_path = Path(__file__).parent / "bench_sets" / "{{ cookiecutter.bench_name }}_public.yaml"

# ① 任务集加载（结构自检）
bench = load_bench_set(set_path)
assert bench["ok"], bench["errors"]

# ② 回归门自检（provider 回放期望 → 两轴应满分）
report = run_agentbench_regression(trajectory_provider=reference_provider,
                                   public_path=set_path)
assert report["ok"], report["reasons"]

# ③ 评测真实记录（埋点记录 records 由 agent 通道产出后注入打分）
result = evaluate_agentbench(records, public_path=set_path)
print(result["combined"])
```

## 数值纪律（铁律 7 / #122）

- `expected.numeric` 的 ground truth **逐条引用权威出处**（`source` 字段）：
  闭式解 / HFSS 仲裁收敛证据 / Ansys 官方例验收基准（口径集中维护在
  `docs/rf_template_references.md`）；打分器只做比较、不产生任何数字；
- 指标提取（metrics.py）=确定性内核：同输入同输出，无网络无 LLM；
- 判据预声明先写后跑（#122）：新任务进集前先写 `source` 与 `tol_pct`，
  事后改判据=翻案（禁止）。

## 公开/私有双集防污染（Gridy 经验）

- 公开集随库可复现；私有集不入库——路径走
  `RFAUTO_AGENTBENCH_PRIVATE_SET` 环境变量或 `--private-set`；
- 公开/私有任务 id 交集非空即 FAIL（`load_bench_sets` 双集校验）——
  本插件任务 id 一律带 `{{ cookiecutter.bench_name }}` 前缀防撞。

## 边界与坑（#97/#222 口径）

- 任务集是**数据**不是代码：结构变更会随 `AGENTBENCH_SCHEMA_VERSION`
  演进，跨版本任务集消费前先跑 `load_bench_set` 看校验结果；
- 本模板渲染产物不进 rfauto 主仓 sdist（第三方包独立装）；
- 真实 agent 通道（LLM）只做编排与解释，评测记录里的数值仍须由
  metrics.py 类确定性内核产出后注入。
