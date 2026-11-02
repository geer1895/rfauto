"""代理产物 ONNX 导出服务面（T-N20，aurora_n W3；JSON 进出，规则 4）。

消费面（最小形态）：``rfauto surrogate export-onnx KIND SAMPLES OUT``
CLI 薄壳与本 service 单源；playground/远程消费按返回的 io 契约
（input name/shape + meta 的 param_names/freq_ghz/coord_keys/field_key）
直接喂 onnxruntime。

模型来源=**现场重拟合**（surrogate_playground 同款口径）：torch 系代理
的拟合网络是注册工厂方法内定义的局部类（``_FNONet``/``_SirenNet``），
pickle 序列化不可达（实测 AttributeError: can't get local object）——
训练产物不落 pickle；本服务按 kind+config+samples 现场重拟合后导出。
确定性由 config 固定 seed 保证（三键 fit 全链固定种子，同输入同产物），
导出落盘字节经 protobuf deterministic 规范化（内核验收③）。

samples 形态与校准样本集同构：``[{"params": {...}, "metrics": {...}}]``
JSON（fno/deep_ensemble 消费曲线键 metrics[curve_key]，siren 消费
metrics[field_key]；样本数下限见各键内核守卫）。

依赖面：torch + onnx + onnxscript 缺席 → ok=False 信封带安装指引
（导出面缺席，不静默）；onnxruntime 缺席 → 导出成功但对拍跳过注记
（verify 面 best-effort，#105）。

数值纪律（铁律 7）：本模块零数值产出——拟合/导出/对拍全在确定性内核
（surrogate_registry 工厂 + optimization/surrogate/onnx_export）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["surrogate_export_onnx"]


def surrogate_export_onnx(payload: dict[str, Any]) -> dict[str, Any]:
    """kind+config+samples 现场重拟合 → ONNX 导出（服务层单源）。

    payload 键：
        kind（必填）: 代理注册键（支持面见内核 SUPPORTED_KINDS；
            format="auto"/"numpy" 时扩 numpy 系覆盖面，见
            onnx_numpy_export.coverage_table）；
        config（可选）: 代理 config dict（bounds/freq_grid/coord_keys 等
            语义与 surrogate_registry.create 同一契约；缺省={}，fno/
            deep_ensemble 的 bounds 必填键缺失在拟合面显式报错）；
        samples（与 samples_path 二选一）: 样本列表（同构校准样本集）；
        samples_path（与 samples 二选一）: 样本 JSON 文件路径；
        out_path（必填）: ONNX 输出路径；
        opset（可选）: ONNX opset（缺省 18，内核 DEFAULT_OPSET）；
        verify（可选）: 导出-回代对拍开关（缺省 True；bool|#277 缺省
            语义由调用方 CLI 三态开关裁决后传入，本函数只收显式 bool）；
        format（可选）: 导出分派（aurora_p D5）——``"torch"``（缺省，既有
            行为零变化：只收 torch 系三键，其余键报错列支持面）|
            ``"auto"``（按键种类分派：torch 键→既有路径，numpy 可转换键
            →onnx_numpy_export builder，不可转换/未分类键显式报错列覆盖
            面）|``"numpy"``（只收 numpy 可转换键）。

    Returns:
        ok=True：内核导出返回全键透传（kind/path/sha256/opset/input/
        output/verified/max_abs_diff/param_names/metric_names/...）+
        fit 摘要（n_samples）。
        ok=False：``errors`` 列表（参数缺失/samples 不可读/不支持 kind/
        训练失败/依赖缺席/对拍超容差）。
    """
    payload = dict(payload or {})
    kind = str(payload.get("kind") or "")
    cfg = payload.get("config")
    if cfg is None:
        cfg = {}                       # siren 面可零 config（全缺省键）
    if not isinstance(cfg, dict):
        return error_envelope("config 须为 dict（代理 config 契约同 create）")
    out_path = str(payload.get("out_path") or "")
    if not kind or not out_path:
        return error_envelope("kind 与 out_path 均必填")
    fmt = str(payload.get("format") or "torch")
    if fmt not in ("torch", "auto", "numpy"):
        return error_envelope(
            f"format 须为 'torch'|'auto'|'numpy'，实得 {fmt!r}")

    samples = payload.get("samples")
    samples_path = str(payload.get("samples_path") or "")
    if samples is None:
        if not samples_path:
            return error_envelope("samples 与 samples_path 二选一必填")
        s_path = Path(samples_path)
        if not s_path.is_file():
            return error_envelope(f"样本 JSON 不存在: {samples_path}")
        try:
            samples = json.loads(s_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return error_envelope(f"样本 JSON 不可读: {exc}")
    if not isinstance(samples, list):
        return error_envelope("samples 须为列表（[{params, metrics}, ...]）")

    from rfauto.optimization.surrogate import surrogate_registry
    from rfauto.optimization.surrogate.onnx_export import (
        SUPPORTED_KINDS,
        export_onnx,
    )

    # 分派前置分类（D5）：legacy torch 档文案/行为逐字节不变（既有钉）；
    # auto/numpy 档走覆盖表分类（诚实边界：pending/unsupported/未分类
    # 在拟合前拦截——不白跑训练）。
    if fmt == "torch":
        if kind not in SUPPORTED_KINDS:
            return error_envelope(
                f"ONNX 导出不支持代理 kind={kind!r}——支持面（torch 系三键）: "
                f"{', '.join(SUPPORTED_KINDS)}；其余键请走本仓 python 推理"
                "路径")
    else:
        from rfauto.optimization.surrogate.onnx_numpy_export import (
            NUMPY_EXPORTABLE_KINDS,
            classify_kind,
        )

        try:
            cls = classify_kind(kind)
        except ValueError as exc:
            return error_envelope(str(exc))
        if fmt == "numpy" and cls != "numpy":
            return error_envelope(
                f"format='numpy' 只收 numpy 可转换键 "
                f"({', '.join(NUMPY_EXPORTABLE_KINDS)})，kind={kind!r} "
                f"分类={cls}——torch 键改用 format='auto'/'torch'，其余见 "
                "coverage_table")
        if fmt == "auto" and cls == "pending":
            from rfauto.optimization.surrogate.onnx_numpy_export import (
                NUMPY_PENDING_KINDS,
            )

            return error_envelope(
                f"kind={kind!r} 可转换但未实施: "
                f"{NUMPY_PENDING_KINDS[kind]}——python 推理路径")
    try:
        model = surrogate_registry.create(kind, config=dict(cfg))
        fit_info = model.fit(samples)
    except Exception as exc:
        return error_envelope(f"代理拟合失败（kind={kind}）: {exc}")

    kwargs: dict[str, Any] = {}
    opset = payload.get("opset")
    if opset is not None:
        kwargs["opset_version"] = int(opset)
    verify = payload.get("verify")
    if verify is not None:
        kwargs["verify"] = bool(verify)
    try:
        if fmt == "torch":
            res = export_onnx(model, out_path, **kwargs)
        else:
            from rfauto.optimization.surrogate.onnx_numpy_export import (
                export_onnx_auto,
            )

            res = export_onnx_auto(model, out_path, **kwargs)
    except (ValueError, RuntimeError) as exc:
        return error_envelope(str(exc))
    res["n_samples"] = int(fit_info.get("n_samples", len(samples)))
    return ok_envelope(**res)
