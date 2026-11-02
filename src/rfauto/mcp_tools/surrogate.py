"""surrogate_export_onnx/surrogate_uq —— 代理导出与 MC 良率面（aurora_n MCP 接线补齐席，2026-10-31）。

zero_wiring 登记欠账清偿：T-N20 ONNX 导出（此前仅 CLI 叶
``rfauto surrogate export-onnx``）与代理蒙特卡洛 UQ（CLI ``rfauto
surrogate uq``，samples+tolerances 形态的 uq_service.surrogate_yield——
MCP 面既有的 uq_yield_at=点值形态（surrogate_yield_at）、
robustness_report=robustness_service 配方 specs 形态，均非同形）。
零逻辑转发 service 单源（规则 4：JSON 信封进出；铁律 7：数值只由
确定性内核产出，本层零新数值）。

文件路径面：samples/out 均为本机路径（MCP 客户端与服务器同盘语义，
由调用方保证可达）；导出落盘只写调用方点名的 out_path 一个文件。
"""

from __future__ import annotations

import json
from typing import Any

from rfauto.mcp_tools._core import mcp as mcp


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def surrogate_export_onnx(
    kind: str,
    samples_path: str,
    out_path: str,
    config_json: str = "",
    opset: int = 18,
    verify: bool = True,
) -> dict[str, Any]:
    """torch 系代理现场重拟合并导出 ONNX（fno/deep_ensemble/siren 三键）。

    模型来源=现场重拟合（playground 同款口径——torch 拟合网络含局部类
    不可 pickle），确定性由 config 固定 seed 保证；导出图输入=原始单位
    参数/坐标向量，落盘字节经 protobuf deterministic 规范化（同权重
    两跑 sha256 一致）。返回 io 契约（input name/shape + meta）供
    onnxruntime 直接消费。依赖 torch+onnx+onnxscript 缺席 → ok=False
    信封带安装指引；其余代理键不支持导出（显式报错列支持面）。

    Args:
        kind: 代理注册键：fno | deep_ensemble | siren（其余键显式拒绝）
        samples_path: 样本 JSON 文件路径（[{"params": {...},
            "metrics": {...}}, ...]，同构校准样本集；fno/deep_ensemble
            消费曲线键 metrics[curve_key]，siren 消费 metrics[field_key]）
        out_path: ONNX 输出路径（.onnx；只写此一个文件）
        config_json: 代理 config JSON 文本（对象：bounds/freq_grid/
            coord_keys/seed 等，语义同 surrogate_registry.create；空串=
            缺省 {}——fno/deep_ensemble 的 bounds 必填键缺失在拟合面
            显式报错）
        opset: ONNX opset 版本（缺省 18）
        verify: 导出-回代对拍开关（缺省 True；对拍消费 onnxruntime，
            缺席时导出成功但对拍跳过注记）

    Returns:
        dict: ok=True {kind, path, sha256, opset, input, output, verified,
        max_abs_diff, param_names, n_samples, ...}；失败 {ok: False,
        errors: [...]}
    """
    from rfauto.service.envelope import error_envelope
    from rfauto.service.surrogate_export_service import surrogate_export_onnx

    cfg: dict[str, Any] = {}
    if str(config_json).strip():
        try:
            loaded = json.loads(config_json)
        except ValueError as exc:
            return error_envelope(f"config_json 不是合法 JSON: {exc}")
        if not isinstance(loaded, dict):
            return error_envelope("config_json 根节点须为 JSON 对象")
        cfg = loaded
    return surrogate_export_onnx({
        "kind": kind,
        "config": cfg,
        "samples_path": samples_path,
        "out_path": out_path,
        "opset": opset,
        "verify": bool(verify),
    })


@mcp.tool(
    annotations={
        "destructiveHint": False,
        "idempotentHint": False,
    }
)
def surrogate_uq(
    samples_path: str,
    tolerances: dict[str, float],
    n: int = 10000,
    seed: int = 42,
    kind: str = "poly_ridge",
    order: int = 2,
    ridge_lambda: float = 0.1,
) -> dict[str, Any]:
    """代理蒙特卡洛 UQ 报表（良率/指标分布/敏感性排序，确定性 seed 复现）。

    名义点=校准样本集中 cost 最小的点（确定性推导，无需手传）；代理
    MC 抽样产出良率、逐指标 mean/std/q05/q95 与敏感性排序。代理估计面
    不替代真机复验；样本集缺失/公差参数未覆盖 → ok=False 如实。只读
    无副作用（不落盘）。tolerance_source（fab 剖面派生 σ 的 DP-7 P2
    形态）不走本工具——剖面单源面属配方/CLI 通道。

    Args:
        samples_path: 校准样本集 samples.json 路径（[{params, metrics},
            ...]；代理由样本集拟合）
        tolerances: 公差 σ {参数名: σ}（与该参数同单位：几何参数 mm、
            频率参数 GHz；须覆盖样本集参数域）
        n: 蒙特卡洛抽样数（≥1；缺省 10000）
        seed: 随机种子（同 seed 同输入逐位复现）
        kind: 代理类型 poly_ridge（缺省）| nn
        order: poly_ridge 多项式阶数（缺省 2）
        ridge_lambda: poly_ridge 岭收缩系数（缺省 0.1）

    Returns:
        dict: {ok, yield_rate, metric_stats, nominal_params,
        sensitivity_ranking, surrogate_kind, n_draws, ...}；失败
        {ok: False, errors: [...]}
    """
    from rfauto.service.uq_service import surrogate_yield

    return surrogate_yield(
        samples_path, tolerances, n=n, seed=seed, kind=kind, order=order,
        ridge_lambda=ridge_lambda)
