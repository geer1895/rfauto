"""dataset_coverage/dataset_annotate_ground_truth/dataset_set_visibility/dataset_export_hf（数据工厂运维面）（AU-1 自 mcp_server.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

from typing import Any

from rfauto.mcp_tools._core import mcp as mcp

# ─── 29. 数据集余量（WP2.4①：coverage/annotate/visibility/export） ───────────

@mcp.tool
def dataset_coverage(
    name: str,
    bins: int = 10,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """数据集覆盖度报告（datasets_ops 域）：数据集名 → 逐维占用/最弱维。

    无副作用，可安全调用；喂 LHS 增广决策，不用于行级导出（走
    dataset_export_hf）。常数维不虚报 100%。数据集不存在 → ok=False
    如实。只读无时序约束。

    Args:
        name: 数据集名
        bins: 等宽分箱数（>=2）
        out_dir: 数据集根目录

    Returns:
        dict: {ok, n_rows, by_model, coverage: {...}, weakest_key, ...}；
        数据集缺失 → ok=False
    """
    from rfauto.service.dataset_insights import dataset_coverage as _cov
    return _cov(name, out_dir=out_dir, bins=bins)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def dataset_annotate_ground_truth(
    name: str,
    threshold: int = 100,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """ground truth 标注（datasets_ops 域）：白名单源清点 → manifest 回写。

    副作用：回写数据集 manifest 的 ground_truth 块（幂等重算）；标注只认
    白名单源（hfss/openems/comsol/meas），不猜测未登记来源。数据集缺失
    → ok=False 如实。时序：materialize 之后调用；幂等可重放。

    Args:
        name: 数据集名
        threshold: 神经算子族级解锁门槛（点数）
        out_dir: 数据集根目录

    Returns:
        dict: {ok, ground_truth: {...}, unlocked, ...}；数据集缺失 → ok=False
    """
    from rfauto.service.dataset_insights import annotate_ground_truth
    return annotate_ground_truth(name, threshold=threshold, out_dir=out_dir)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def dataset_set_visibility(
    name: str,
    visibility: str,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """数据集可见性切换（datasets_ops 域）：public/private → manifest 回写。

    副作用：回写数据集 manifest 的 visibility 字段（public 是 HF 导出放行
    前提）；非法 visibility 值/数据集缺失 → ok=False errors 如实。
    时序：幂等可重放；导出前先置 public。

    Args:
        name: 数据集名
        visibility: public | private
        out_dir: 数据集根目录

    Returns:
        dict: {ok, name, visibility} 或 {ok: False, errors}
    """
    from rfauto.service.dataset_insights import set_dataset_visibility
    return set_dataset_visibility(name, visibility, out_dir=out_dir)


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": True,
    }
)
def dataset_export_hf(
    name: str,
    license: str = "",
    allow_private: bool = False,
    out_dir: str = "runs/datasets",
) -> dict[str, Any]:
    """HF 数据集导出（datasets_ops 域）：数据集 → parquet 分片+数据卡目录。

    副作用：写 <dataset_dir>/hf/（本地目录布局，零上传零外发）；private
    数据集默认拒绝（防战役数据误发布，allow_private 须显式）。数据集
    缺失 → ok=False errors 如实。时序：先 set_visibility(public) 或显式
    allow_private。

    Args:
        name: 数据集名
        license: 数据卡 license 字段
        allow_private: 显式允许导出 private 数据集
        out_dir: 数据集根目录

    Returns:
        dict: {ok, hf_dir, files, ...} 或 {ok: False, errors}
    """
    from rfauto.service.dataset_insights import export_hf_dataset
    return export_hf_dataset(name, out_dir=out_dir, license=license,
                             allow_private=allow_private)
