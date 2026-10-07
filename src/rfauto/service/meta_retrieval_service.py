"""meta_retrieval_service —— DA-2 检索式元学习服务薄壳（JSON 进出，规则 4）。

职责边界：
- 检索内核在 core/meta_retrieval.py（确定性 k-NN，零学习零随机）；本
  模块只做信封转换与既有通道接线——数值全部由内核产出，本层零计算。
- 历史库以**显式条目列表入参**（不读 runs/ 文件；真实数据由调用方经
  dataset_service/warm_start_data 数据面查询后供给，#144 chdir 隔离
  纪律）。
- ``gate_meta_warm_start`` 把检索先验喂给既有 warm_start 相似度门
  （optimization.warm_start.warm_start_points，负迁移防线归通道所有）；
  惰性导入（#139：optimization/optuna 依赖重，且便于单测 monkeypatch
  钉住通道）。门的异常如实透传不吞（本层不重复设门也不降级）。
- 查询/参数非法：内核 ValueError → ``{"ok": False, "errors": [...]}``
  信封（CLI/MCP 薄壳可直接回 JSON），不向上抛。
"""

from __future__ import annotations

from typing import Any

from rfauto.core.meta_retrieval import METRIC_STANDARDIZED_MAHALANOBIS, SUPPORTED_METRICS, TEMPLATE_FAMILY_VOCAB
from rfauto.core.meta_retrieval import retrieve_warm_start_prior as _retrieve_kernel
from rfauto.service.envelope import error_envelope

__all__ = [
    "SUPPORTED_METRICS",
    "TEMPLATE_FAMILY_VOCAB",
    "gate_meta_warm_start",
    "retrieve_meta_warm_start",
]


def retrieve_meta_warm_start(
    query_meta: dict[str, Any],
    library: list[dict[str, Any]],
    *,
    k: int = 5,
    metric: str = METRIC_STANDARDIZED_MAHALANOBIS,
) -> dict[str, Any]:
    """检索式 warm-start 先验（JSON 信封）。

    Args:
        query_meta: 新战役问题侧元特征（schema 见 core 模块 docstring）。
        library: 历史库条目列表（调用方显式供给，本层零 IO）。
        k: 检索近邻数（缺省 5）。
        metric: 距离口径（缺省 standardized_mahalanobis）。

    Returns:
        内核结果原样（ok=True，含 warm_start_samples 通道对齐形态）；
        查询/k/metric 非法 → ``{"ok": False, "errors": [str]}``。
    """
    try:
        return _retrieve_kernel(query_meta, library, k=k, metric=metric)
    except (ValueError, TypeError) as exc:
        return error_envelope([str(exc)])


def gate_meta_warm_start(
    samples: list[dict[str, Any]],
    bounds: dict[str, dict[str, Any]],
    *,
    top_n: int = 3,
    min_similarity: float = 0.5,
) -> dict[str, Any]:
    """检索先验 → 既有 warm_start 相似度门（通道透传，薄壳零计算）。

    ``samples`` 即 ``retrieve_meta_warm_start`` 输出的
    ``warm_start_samples``（``list[{"params", "cost", ...}]``，多余溯源
    键被门忽略）；``bounds`` 为新战役参数空间
    ``{param: {"low": float, "high": float}}``（optimizer 提取口径）。
    返回值/异常语义与 ``optimization.warm_start.warm_start_points`` 完全
    一致（门拒绝 → ``ok=False/reason=insufficient_similarity``）。
    """
    from rfauto.optimization.warm_start import warm_start_points

    return warm_start_points(
        list(samples or []),
        bounds=bounds,
        top_n=top_n,
        min_similarity=min_similarity,
    )
