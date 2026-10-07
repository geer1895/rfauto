"""S-5a 稀疏 PCE service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/sparse_pce.py 内核（Blatman-Sudret 自适应 LARS 稀疏 PCE + Sobol
直读，全部数字出自确定性内核，规则 7）。单入口：

- :func:`sparse_pce_sobol_report`：param_specs + objective_fn → 稀疏 PCE
  拟合 + 一阶/总阶 Sobol 解析 + JSON 安全报告信封；**ok=False 不抛**
  （信封契约：error 带原异常消息，缺参/边界/常数目标等如实拒绝）。

诚实边界（与内核 docstring 同源）：PCE 是全局多项式代理，强不连续/窄带
深谷收敛慢；输入必须独立；Kucherenko（相关输入）面属新依赖裁决项未实现
（core.sparse_pce.KUCHERENKO_STATUS）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rfauto.core.sparse_pce import KUCHERENKO_STATUS, fit_sparse_pce

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
SPARSE_PCE_SERVICE_SCHEMA_VERSION = "1.0"


def sparse_pce_sobol_report(
    param_specs: Mapping[str, Mapping[str, float]],
    objective_fn: Callable[[Mapping[str, float]], float],
    **kwargs: Any,
) -> dict[str, Any]:
    """稀疏 PCE Sobol 报告（JSON 信封，ok=False 不抛）。

    kwargs 透传 core.sparse_pce.fit_sparse_pce（degree_max/degree_start/q/
    n_samples/sampler/cut_factor/q2_target/seed）。返回 to_dict 报告 +
    模型对象（model 键，进程内消费；JSON 序列化请用 report 键）。
    """
    envelope: dict[str, Any] = {
        "method": "sparse_pce_blatman_sudret",
        "schema_version": SPARSE_PCE_SERVICE_SCHEMA_VERSION,
        "kucherenko_status": KUCHERENKO_STATUS,
    }
    try:
        model = fit_sparse_pce(param_specs, objective_fn, **kwargs)
    except Exception as exc:  # 服务信封契约：如实拒绝不抛（ok=False 不抛）
        return {**envelope, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    report = model.to_dict()
    return {
        **envelope,
        **report,
        "report": report,
        "model": model,
    }
