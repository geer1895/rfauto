"""{{ cookiecutter.module_name }}：rfauto {{ cookiecutter.bench_name }} metric/benchmark 插件包。

显式导入消费（基准面当前无 entry-point 发现组——诚实口径，见 README）：
- ``.metrics``：确定性指标计算（铁律 7：数值只在确定性内核产出）；
- ``.provider``：离线参考提供器（run_agentbench_regression 注入点）。
"""

from {{ cookiecutter.module_name }} import metrics, provider

__all__ = ["metrics", "provider"]
