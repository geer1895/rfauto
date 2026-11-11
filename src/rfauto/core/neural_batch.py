"""神经代理批量评估内核（aurora_r R-28 / C2 前半：批量前向+逐候选打分取最优）。

任务来源
--------
Alpha-RF（arXiv:2603.00104；runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md
B1/C2 行）第一层的批量消费面："10000 候选 7.3 秒" = **批量前向 + 逐候选
打分取最优**——本模块只落这一半（评估内核），不训 RL 策略、不做搜索器
（C2 后半挂账）。模型形态 = core.neural_surrogate（R-05）的 fit 信封
（唯一消费形态）；候选生成（LHS）与目标规格命中度打分在
service.neural_batch_service（同席编排面）——本模块 ``score_fn`` 一律由
调用方注入，内核不做任何目标语义（铁律 7：物理判读数字只出自确定性
函数，本模块只搬运前向输出）。

批量口径
--------
- torch 可用：``_build_torch_mlp``→state 回载→``eval()``+``no_grad``→
  **单次矩阵 forward**（N 候选一批，非逐个循环）——引擎名
  ``torch_batch``。
- torch 缺失：``mlp_forward_numpy``（R-05 纯 numpy 裁判）整矩阵前向
  降级——引擎名 ``numpy_degraded``，性能**如实标注非 torch/GPU 档**。
- **逐位一致的诚实边界（#122，实证 torch 2.14.0+cpu/Windows MKL）**：
  ①单候选（batch=1）前向与 R-05 :func:`predict_mlp` 逐个前向**逐位
  一致**（同 M=1 内核路径——单测钉死）；②同调用双跑**逐位一致**；
  ③批量（M=N）vs 逐个（M=1）前向因 BLAS dgemm/dgemv 按批量维重结合
  （reassociation），**逐位不成立**（实测 max abs ~2e-15）——只承诺
  ≤1e-12 相对一致（#118 跨实现对拍同容差口径），torch 与 numpy 两
  引擎同此边界（numpy dgemm 批量 vs 逐行实测亦非逐位）。
- 前向批量收益只在矩阵乘层面；逐候选响应重组与 ``score_fn`` 调用在
  Python 侧逐个进行（N 大时为已知成本面，诚实计入调用方耗时观测）。

打分与排序契约
--------------
``score_fn: pred_response → float``（调用方注入的纯函数）；
``pred_response = {"curves": {通道: {"re": [...], "im": [...]}},
"freqs_hz": [...], "channels": [...]}``（与 predict_mlp 载荷同形；
复数 = re + 1j·im 由消费方合成，本内核不做 dB/相位等物理换算）。
排序 = 分数降序、同分按候选原始下标稳定（确定性 tie-break，
select_by_sigma 同口径）。评分异常/返回非有限/返回 bool 的候选显式
排除并计数（不静默、不炸批，#122）；参数非有限的候选整点丢弃计数
（build_sparam_dataset 同口径）；结构违例（缺名/非数值化/形态非法）
error 信封点名下标 fail-closed。

信封为同形约定 dict（core 层不经 service.envelope 构造器，R-05 同款）。
无 CLI/MCP 叶（挂账处方：消费接线出现时挂 ``rfauto neural-opt`` 薄壳，
service/neural_batch_service 已就绪，CLI 只透传参数勿复制实现）。
公开面申报制（本模块**不带 __all__**：public_api 金快照本席禁改，
合流席如需钉入快照走 check_public_api.py --generate 评审动作）——
公开名仅 :func:`batch_evaluate` 一个；对 neural_surrogate 私有件
（_load_torch/_build_torch_mlp/_load_state_into_linears）的同包复用
为显式 import，私有名不入金快照、零快照影响。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from rfauto.core.neural_surrogate import (
    TORCH_INSTALL_HINT,
    NormalizationSpec,
    _build_torch_mlp,
    _load_state_into_linears,
    _load_torch,
    apply_normalization,
    mlp_forward_numpy,
    mlp_spec_from_dict,
    undo_normalization,
)

#: fit 信封必需键（batch_evaluate 校验面；predict_mlp required 超集——
#: 曲线重组还需 channels/freqs_hz/channel_offsets/n_grid）。
_REQUIRED_FIT_KEYS = (
    "state", "norm_x", "norm_y", "param_names", "spec",
    "channels", "freqs_hz", "channel_offsets", "n_grid",
)

#: 诊断明细（dropped/score_failures）在信封内携带的条目上限——超限只保
#: 计数与截断标记（N=10 万量级时防信封被诊断条目淹没；计数恒全量如实）。
_CARRY_CAP = 50

_TORCH_NOTE = (
    "torch 批量前向：单次矩阵 forward（N 候选一批，eval+no_grad）；"
    "单候选路径与 predict_mlp 逐个前向逐位一致、批量 vs 逐个 ≤1e-12 "
    "相对一致（BLAS 按批量维重结合——单测钉，诚实边界）"
)
_NUMPY_NOTE = (
    "numpy 降级引擎（mlp_forward_numpy 整矩阵前向）——非 torch/GPU 档，"
    "性能如实降级；批量 vs 逐行 ≤1e-12 相对一致（BLAS 阻塞重结合，"
    "无逐位保证）"
)


def _error(action: str, errors: Sequence[str]) -> dict[str, Any]:
    """数据/规格条件面错误信封（core 面同形 dict，R-05 口径）。"""
    return {"ok": False, "errors": [str(e) for e in errors], "action": action}


def _unavailable() -> dict[str, Any]:
    """torch/模型不可用的结构化信封（R-05 _unavailable_envelope 同口径）。"""
    return {
        "ok": False,
        "errors": [
            "neural_batch.batch_evaluate: fit 信封不可用（torch 未安装时 "
            "fit_neural_surrogate 产 unavailable 信封，权重面不存在——"
            "numpy 降级也无 state 可前向）"],
        "unavailable": True,
        "install_hint": TORCH_INSTALL_HINT,
        "action": "batch_evaluate",
    }


def _response_row(
    y: np.ndarray, pos: int, channels: Sequence[str],
    offsets: Mapping[str, Any], n_grid: int, freqs: list[float],
) -> dict[str, Any]:
    """单候选物理量纲响应重组（predict_mlp 载荷同形；freqs 列表共享）。"""
    curves = {
        c: {
            "re": y[pos, int(offsets[c]["re_offset"]):
                    int(offsets[c]["re_offset"]) + n_grid].tolist(),
            "im": y[pos, int(offsets[c]["im_offset"]):
                    int(offsets[c]["im_offset"]) + n_grid].tolist(),
        }
        for c in channels
    }
    return {"curves": curves, "freqs_hz": freqs, "channels": list(channels)}


def batch_evaluate(
    fit_env: Mapping[str, Any],
    candidate_params: Sequence[Mapping[str, float]],
    score_fn: Callable[[Mapping[str, Any]], float],
    *,
    top_k: int | None = None,
) -> dict[str, Any]:
    """神经代理批量评估：N 候选一次前向 + 逐候选注入打分 + 排序取 top-k。

    Args:
        fit_env: ``fit_neural_surrogate`` 的 ok 信封（state/norm/spec/
            param_names/channels/freqs_hz/channel_offsets/n_grid 全上下文
            自足）；unavailable 信封传入→unavailable 信封如实透传。
        candidate_params: 候选参数字典序列（每项含全部 param_names）。
        score_fn: 打分纯函数 ``pred_response → float``（契约见模块头；
            异常/非有限/bool 返回的候选排除并计数，不炸批）。
        top_k: 返回排名前 k（≥1）；None=全部返回。排序=分数降序、同分
            按候选原始下标稳定。

    Returns:
        ok 信封::

            {"ok": True, "kind": "neural_batch_evaluate",
             "engine": "torch_batch" | "numpy_degraded",
             "engine_note", "n_candidates", "n_evaluated",
             "n_dropped", "dropped", "dropped_truncated",
             "n_score_invalid", "n_score_failed",
             "score_failures", "score_failures_truncated",
             "top_k",  # 实际返回条数（None 入参=全部）
             "ranked": [{"rank", "index", "params", "pred_response",
                         "score"}, ...]}

        结构违例（fit 信封缺键/字段违例/候选缺名/非数值化）→ error 信封
        点名；候选参数非有限整点丢弃计数；全部候选被丢弃→error 信封。
    """
    if not callable(score_fn):
        return _error("batch_evaluate", [
            "score_fn 必须为可调用对象（pred_response → float）"])
    if top_k is not None:
        try:
            k_req = int(top_k)
        except (TypeError, ValueError):
            return _error("batch_evaluate", [f"top_k 非法: {top_k!r}"])
        if k_req < 1:
            return _error("batch_evaluate", [
                f"top_k 必须 >=1（或 None=全部返回），收到 {top_k!r}"])

    # ① fit 信封校验（unavailable 如实透传；结构违例 fail-closed 点名）
    if not isinstance(fit_env, Mapping):
        return _error("batch_evaluate", [
            f"fit_env 须为 Mapping（得 {type(fit_env).__name__}）"])
    if fit_env.get("ok") is not True:
        if fit_env.get("unavailable") is True:
            return _unavailable()
        return _error("batch_evaluate", [
            "fit_env 需为 fit_neural_surrogate 的 ok 信封",
            *(f"fit_env errors: {e}" for e in (fit_env.get("errors") or []))])
    missing_keys = [k for k in _REQUIRED_FIT_KEYS if k not in fit_env]
    if missing_keys:
        return _error("batch_evaluate", [
            f"fit_env 缺键: {missing_keys}（需 {_REQUIRED_FIT_KEYS}）"])
    try:
        spec = mlp_spec_from_dict(fit_env["spec"])
        norm_x = NormalizationSpec.from_dict(fit_env["norm_x"])
        norm_y = NormalizationSpec.from_dict(fit_env["norm_y"])
    except (KeyError, TypeError, ValueError) as exc:
        return _error("batch_evaluate", [f"fit_env 字段违例: {exc}"])
    param_names = [str(p) for p in fit_env["param_names"]]
    channels = [str(c) for c in fit_env["channels"]]
    offsets = fit_env["channel_offsets"]
    try:
        n_grid = int(fit_env["n_grid"])
        freqs = [float(f) for f in fit_env["freqs_hz"]]
    except (TypeError, ValueError) as exc:
        return _error("batch_evaluate", [f"fit_env 频栅违例: {exc}"])
    if not channels or not param_names:
        return _error("batch_evaluate", ["fit_env channels/param_names 为空"])
    if len(freqs) != n_grid:
        return _error("batch_evaluate", [
            f"freqs_hz 长度 {len(freqs)} 与 n_grid {n_grid} 不一致"])
    if spec.n_inputs != len(param_names):
        return _error("batch_evaluate", [
            f"spec.n_inputs={spec.n_inputs} 与 param_names 数 "
            f"{len(param_names)} 不一致"])
    for c in channels:
        off = offsets.get(c) if isinstance(offsets, Mapping) else None
        if not (isinstance(off, Mapping) and "re_offset" in off
                and "im_offset" in off):
            return _error("batch_evaluate", [
                f"channel_offsets 缺通道 {c!r} 的 re_offset/im_offset"])
        if (int(off["re_offset"]) + n_grid > spec.n_outputs
                or int(off["im_offset"]) + n_grid > spec.n_outputs):
            return _error("batch_evaluate", [
                f"通道 {c!r} 列偏移越界（n_outputs={spec.n_outputs}）"])

    # ② 候选矩阵（结构违例点名 fail-closed；非有限整点丢弃计数）
    if isinstance(candidate_params, (str, bytes)) or not isinstance(
            candidate_params, Sequence):
        return _error("batch_evaluate", [
            f"candidate_params 须为参数字典序列（得 "
            f"{type(candidate_params).__name__}）"])
    n_cand = len(candidate_params)
    if n_cand < 1:
        return _error("batch_evaluate", ["candidate_params 为空"])
    rows: list[list[float]] = []
    kept_index: list[int] = []
    dropped: list[dict[str, Any]] = []
    for idx, cand in enumerate(candidate_params):
        if not isinstance(cand, Mapping):
            return _error("batch_evaluate", [
                f"候选 {idx} 形态违例：须为参数字典"
                f"（得 {type(cand).__name__}）"])
        missing_p = [p for p in param_names if p not in cand]
        if missing_p:
            return _error("batch_evaluate", [
                f"候选 {idx} 缺参数名 {missing_p}（需要 {param_names}）"])
        row: list[float] = []
        reason: str | None = None
        for p in param_names:
            v = cand[p]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return _error("batch_evaluate", [
                    f"候选 {idx} 参数 {p!r} 非数值化失败: {v!r}"])
            fv = float(v)
            if not math.isfinite(fv):
                reason = f"参数 {p!r} 非有限（{v!r}）"
                break
            row.append(fv)
        if reason is not None:
            dropped.append({"index": idx, "reason": reason})
            continue
        rows.append(row)
        kept_index.append(idx)
    if not rows:
        return _error("batch_evaluate", [
            "全部候选参数非有限被丢弃，无可评估点",
            *(d["reason"] for d in dropped)])

    # ③ 批量前向（torch 单次矩阵 forward；缺失→numpy 整矩阵降级）
    xn = apply_normalization(norm_x, np.asarray(rows, dtype=np.float64))
    torch = _load_torch()
    if torch is not None:
        try:
            model, linears = _build_torch_mlp(torch, spec)
            _load_state_into_linears(torch, linears, fit_env["state"])
            model.eval()
            with torch.no_grad():
                yn = model(torch.tensor(xn, dtype=torch.float64)).numpy()
            engine, engine_note = "torch_batch", _TORCH_NOTE
        except (ValueError, KeyError, TypeError) as exc:
            return _error("batch_evaluate", [f"torch 前向失败: {exc}"])
    else:
        try:
            yn = mlp_forward_numpy(fit_env["state"], spec, xn)
            engine, engine_note = "numpy_degraded", _NUMPY_NOTE
        except ValueError as exc:
            return _error("batch_evaluate", [f"numpy 前向失败: {exc}"])
    y = undo_normalization(norm_y, np.asarray(yn, dtype=np.float64))

    # ④ 逐候选打分（异常/非有限/bool 显式排除计数，#122 不静默）
    scored: list[tuple[float, int, int]] = []  # (score, 保留序位, 原下标)
    n_invalid = 0
    n_failed = 0
    failures: list[dict[str, Any]] = []
    for pos, i_orig in enumerate(kept_index):
        resp = _response_row(y, pos, channels, offsets, n_grid, freqs)
        try:
            s = score_fn(resp)
        except Exception as exc:  # 打分失败记因排除，不炸批（环编排同口径）
            n_failed += 1
            if len(failures) < _CARRY_CAP:
                failures.append({"index": i_orig,
                                 "error": f"{type(exc).__name__}: {exc}"})
            continue
        if isinstance(s, bool) or not isinstance(s, (int, float)) \
                or not math.isfinite(float(s)):
            n_invalid += 1
            continue
        scored.append((float(s), pos, i_orig))

    # ⑤ 排序（分数降序、同分按原下标稳定）+ top-k 响应重组（只重组返回面）
    scored.sort(key=lambda t: (-t[0], t[2]))
    k_eff = len(scored) if top_k is None else min(int(top_k), len(scored))
    ranked: list[dict[str, Any]] = []
    for rank, (s, pos, i_orig) in enumerate(scored[:k_eff]):
        ranked.append({
            "rank": rank,
            "index": i_orig,
            "params": dict(candidate_params[i_orig]),
            "pred_response": _response_row(
                y, pos, channels, offsets, n_grid, freqs),
            "score": s,
        })

    return {
        "ok": True,
        "kind": "neural_batch_evaluate",
        "engine": engine,
        "engine_note": engine_note,
        "n_candidates": n_cand,
        "n_evaluated": len(scored),
        "n_dropped": len(dropped),
        "dropped": dropped[:_CARRY_CAP],
        "dropped_truncated": len(dropped) > _CARRY_CAP,
        "n_score_invalid": n_invalid,
        "n_score_failed": n_failed,
        "score_failures": failures,
        "score_failures_truncated": n_failed > _CARRY_CAP,
        "top_k": k_eff,
        "ranked": ranked,
    }
