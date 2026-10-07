"""stratified_doe：物理分层采样 DOE（OP-DOE2，round19 P2 前半，接口原型级）。

round19 原文规格：param spec 扩
``{kind: continuous|integer|categorical|conditional(active_if)}``；
**分层=分类层×连续子 LHS**（无条件 categorical 参数的值叉积=层，层内
连续维走 scipy qmc 子 LHS/Sobol）；**条件分支按激活层配额**（条件参数
仅在 active_if 指向的父 categorical 值命中的层激活，激活点数=该层配额，
非激活点显式 None 留痕）。scipy.stats.qmc 消费面（LHS/Sobol，仓内
sample_design.lhs_points 已有 qmc 先例；本面扩分层语义、不改已合流文件）。

验收（round19 原文）：4 维含 2 条件支覆盖 ≥95% 格点——
:func:`doe_grid_coverage` 把连续维离散成 bins、条件参数按激活/非激活
状态计入格点，给覆盖率报告。

接口原型级：纯确定性（seed 固定逐位重放）、零真机、零 LLM 通道（#139）；
零新采样数学（分层=叉积配额 + qmc 引擎调用，#118 基准=qmc 引擎自身
分层均匀性 + 配额算术恒等 + 确定性重放）。
"""

from __future__ import annotations

import math
from itertools import product
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

_SOURCE = "rfauto.service.stratified_doe_service"
_KINDS = ("continuous", "integer", "categorical", "conditional")
_SAMPLERS = ("lhs", "sobol")


def validate_param_spec(spec: Any) -> dict[str, Any]:
    """param spec 校验（schema + 交叉引用；错误逐条如实，不静默收窄）。"""
    if not isinstance(spec, list) or not spec:
        return error_envelope(["spec 须为非空列表"])
    errors: list[str] = []
    names: set[str] = set()
    for i, p in enumerate(spec):
        if not isinstance(p, dict):
            errors.append(f"spec[{i}] 非 dict")
            continue
        name = p.get("name")
        kind = p.get("kind")
        if not name or not isinstance(name, str):
            errors.append(f"spec[{i}].name 必填（非空字符串）")
            continue
        if name in names:
            errors.append(f"spec[{i}] 参数名重复: {name}")
        names.add(name)
        if kind not in _KINDS:
            errors.append(f"spec[{i}] ({name}) 未知 kind {kind!r}"
                          f"（可选 {list(_KINDS)}）")
            continue
        if kind in ("continuous", "integer"):
            try:
                lo, hi = float(p["low"]), float(p["high"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"spec[{i}] ({name}) low/high 必填数值")
                continue
            if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
                errors.append(f"spec[{i}] ({name}) 要求 high>low 且有限，"
                              f"得 [{lo}, {hi}]")
            elif kind == "integer" and (float(p["low"]).is_integer() is False
                                        or float(p["high"]).is_integer()
                                        is False):
                errors.append(f"spec[{i}] ({name}) integer 端点必须整数")
        elif kind == "categorical":
            vals = p.get("values")
            if not isinstance(vals, list) or not vals:
                errors.append(f"spec[{i}] ({name}) values 必须非空列表")
            elif len(set(map(str, vals))) != len(vals):
                errors.append(f"spec[{i}] ({name}) values 含重复项")
        else:  # conditional
            parent_map = p.get("active_if")
            if not isinstance(parent_map, dict) or not parent_map:
                errors.append(f"spec[{i}] ({name}) active_if 必填"
                              "（{parent: value|[values]}）")
                continue
            if len(parent_map) != 1:
                errors.append(f"spec[{i}] ({name}) 原型级仅支持单父 "
                              "active_if")
            for parent, pv in parent_map.items():
                if parent not in names:
                    errors.append(f"spec[{i}] ({name}) active_if 父参数 "
                                  f"{parent!r} 须在其之前声明且为 "
                                  "categorical")
                    continue
                parent_spec = next(q for q in spec[:i]
                                   if isinstance(q, dict)
                                   and q.get("name") == parent)
                if parent_spec.get("kind") != "categorical":
                    errors.append(f"spec[{i}] ({name}) 父参数 {parent!r} "
                                  "须为 categorical")
                pv_list = pv if isinstance(pv, list) else [pv]
                known = set(map(str, parent_spec.get("values") or []))
                unknown = sorted(set(map(str, pv_list)) - known)
                if unknown:
                    errors.append(f"spec[{i}] ({name}) active_if 引用父值 "
                                  f"{unknown} 不在 {parent} 的 values 内")
            has_disc = isinstance(p.get("values"), list) and p.get("values")
            has_cont = p.get("low") is not None and p.get("high") is not None
            if not has_disc and not has_cont:
                errors.append(f"spec[{i}] ({name}) 条件参数须给 values"
                              "（离散）或 low/high（连续）")
    # ge8e W2 快偿（R5-06）：裸 ok 信封 → 构造器（键集/键序/语义零变化）
    if errors:
        return error_envelope(errors)
    return ok_envelope(errors=errors)


def _parent_of(p: dict[str, Any]) -> str:
    return next(iter(p["active_if"]))


def _active_values(p: dict[str, Any]) -> list[str]:
    pv = p["active_if"][_parent_of(p)]
    return [str(v) for v in (pv if isinstance(pv, list) else [pv])]


def _layer_names(spec: list[dict[str, Any]]) -> list[dict[str, str]]:
    cats = [p for p in spec if p["kind"] == "categorical"]
    if not cats:
        return [{}]
    return [dict(zip([c["name"] for c in cats], combo, strict=True))
            for combo in product(*[[str(v) for v in c["values"]]
                                   for c in cats])]


def stratified_doe(param_spec: list[dict[str, Any]], n_points: int,
                   seed: int = 0, sampler: str = "lhs") -> dict[str, Any]:
    """分层采样主入口：分类层×连续子 LHS；条件分支按激活层配额。

    Args:
        param_spec: validate_param_spec 通过的规格表；
        n_points: 总点数（正整数；层间配额 // 均分+余数前置层）；
        seed: qmc 种子（逐层 seed+i，确定性重放）；
        sampler: "lhs"|"sobol"（scipy.stats.qmc；Sobol 层内任意点数
            由 scipy 平衡处理）。

    Returns:
        {ok, points[{name: value...}], design{...}}；校验失败
        ok=False+errors（不抛、不静默收窄）。
    """
    chk = validate_param_spec(param_spec)
    if not chk["ok"]:
        return {"ok": False, "source": _SOURCE, "errors": chk["errors"]}
    if not isinstance(n_points, int) or isinstance(n_points, bool) \
            or n_points <= 0:
        return {"ok": False, "source": _SOURCE,
                "errors": [f"n_points 须为正整数，得到 {n_points!r}"]}
    if sampler not in _SAMPLERS:
        return {"ok": False, "source": _SOURCE,
                "errors": [f"未知 sampler {sampler!r}"
                           f"（可选 {list(_SAMPLERS)}）"]}
    from scipy.stats import qmc

    spec = [dict(p) for p in param_spec]
    conds = [p for p in spec if p["kind"] == "conditional"]
    for p in conds:
        p["_parent"] = _parent_of(p)
    layers = _layer_names(spec)
    base_quota = n_points // len(layers)
    rem = n_points - base_quota * len(layers)
    quotas = [base_quota + (1 if i < rem else 0)
              for i in range(len(layers))]

    cont_names = [p["name"] for p in spec
                  if p["kind"] in ("continuous", "integer")]
    cond_cont = [p for p in conds if p.get("values") is None]
    cond_disc = [p for p in conds if p.get("values") is not None]
    # 离散条件维也走 qmc 抽取维（独立坐标）——禁用按点序轮转：Sobol 首
    # 坐标=点序的 radical inverse，与点序奇偶结构性相关，轮转会造出
    # 结构性空格（实测 0.556 覆盖率伪象），qmc 坐标才保持层内分层。
    n_dim_draw = len(cont_names) + len(cond_cont) + len(cond_disc)

    points: list[dict[str, Any]] = []
    inactive_assignments = 0
    for li, (layer, quota) in enumerate(zip(layers, quotas, strict=True)):
        if quota == 0:
            continue
        unit = (qmc.LatinHypercube(d=n_dim_draw, seed=seed + li).random(
            n=quota) if sampler == "lhs" else
            qmc.Sobol(d=n_dim_draw, scramble=True, seed=seed + li).random(
                n=quota)) if n_dim_draw > 0 else [[0.0]] * quota
        vals: list[dict[str, Any]] = [dict(layer) for _ in range(quota)]
        col = 0
        for p in spec:
            name = p["name"]
            kind = p["kind"]
            if kind in ("continuous", "integer"):
                lo, hi = float(p["low"]), float(p["high"])
                for ri, row in enumerate(vals):
                    v = lo + float(unit[ri][col]) * (hi - lo)
                    row[name] = math.floor(v) if kind == "integer" \
                        else float(v)
                col += 1
            elif kind == "conditional":
                if str(layer[p["_parent"]]) not in _active_values(p):
                    for row in vals:
                        row[name] = None
                    inactive_assignments += quota
                elif p.get("values") is not None:
                    # 离散条件：独立 qmc 坐标 → 值索引（层内分层，确定性）
                    cvals = [str(v) for v in p["values"]]
                    ccol = len(cont_names) + len(cond_cont) \
                        + cond_disc.index(p)
                    for ri, row in enumerate(vals):
                        idx = min(int(float(unit[ri][ccol]) * len(cvals)),
                                  len(cvals) - 1)
                        row[name] = cvals[idx]
                else:  # 连续条件维：独立 qmc 坐标（层内分层）
                    lo, hi = float(p["low"]), float(p["high"])
                    ccol = len(cont_names) + cond_cont.index(p)
                    for ri, row in enumerate(vals):
                        row[name] = float(
                            lo + float(unit[ri][ccol]) * (hi - lo))
        points.extend(vals)
    return ok_envelope(
        source=_SOURCE,
        points=points,
        design={"sampler": sampler, "seed": seed,
                       "n_points": len(points),
                       "n_layers": len(layers), "quotas": quotas,
                       "layers": [{**layer, "_quota": q}
                                  for layer, q in zip(layers, quotas,
                                                      strict=True)],
                       "inactive_assignments": inactive_assignments,
                       "inactive_note": "非激活赋值计数（逐条件参数×逐点；"
                                        "非激活点显式 None 留痕）",
                       "spec": [{k: v for k, v in p.items()
                                 if not k.startswith("_")}
                                for p in spec]},
    )


def doe_grid_coverage(points: list[dict[str, Any]],
                      param_spec: list[dict[str, Any]],
                      bins: int = 4) -> dict[str, Any]:
    """格点覆盖率（round19 验收口径）：连续维离散 bins、条件按激活态计格。

    格 = 无条件 categorical 值叉积 × 连续维 bins 格 × 条件参数空间
    （激活=逐值/逐 bin；非激活="inactive" 单格）。适用格只在条件激活
    语义成立的父值层展开。覆盖率 = 命中格 / 适用格。
    """
    chk = validate_param_spec(param_spec)
    if not chk["ok"]:
        return {"ok": False, "source": _SOURCE, "errors": chk["errors"]}
    if not isinstance(bins, int) or isinstance(bins, bool) or bins < 1:
        return {"ok": False, "source": _SOURCE,
                "errors": [f"bins 须为正整数，得到 {bins!r}"]}
    if not points or not all(isinstance(p, dict) for p in points):
        return {"ok": False, "source": _SOURCE,
                "errors": ["points 须为非空 dict 列表"]}
    spec = [dict(p) for p in param_spec]
    conds = [p for p in spec if p["kind"] == "conditional"]
    for p in conds:
        p["_parent"] = _parent_of(p)
    cats = [p for p in spec if p["kind"] == "categorical"]
    conts = [p for p in spec if p["kind"] in ("continuous", "integer")]

    def _bin_of(p: dict[str, Any], value: float) -> int:
        lo, hi = float(p["low"]), float(p["high"])
        return min(bins - 1, max(0, int((value - lo) / (hi - lo) * bins)))

    def _cond_space(layer: dict[str, str]) -> list[tuple]:
        spaces: list[list[Any]] = []
        for p in conds:
            if str(layer.get(p["_parent"])) in _active_values(p):
                if p.get("values") is not None:
                    spaces.append([str(v) for v in p["values"]])
                else:
                    spaces.append(list(range(bins)))
            else:
                spaces.append(["inactive"])
        return list(product(*spaces)) if spaces else [()]

    cat_names = [c["name"] for c in cats]
    layers = _layer_names(spec)
    applicable = 0
    for layer in layers:
        applicable += (bins ** len(conts)) * len(_cond_space(layer))

    n_bad = 0
    cells: set[tuple] = set()
    for pt in points:
        bad = False
        cat_key = tuple(str(pt.get(n)) for n in cat_names)
        cond_key: list[Any] = []
        for p in conds:
            parent_active = str(pt.get(p["_parent"])) in _active_values(p)
            if not parent_active:
                if pt.get(p["name"]) is not None:
                    bad = True
                else:
                    cond_key.append("inactive")
            elif p.get("values") is not None:
                cond_key.append(str(pt.get(p["name"])))
            else:
                if pt.get(p["name"]) is None:
                    bad = True
                else:
                    cond_key.append(_bin_of(p, float(pt[p["name"]])))
        cont_key = tuple()
        if not bad:
            try:
                cont_key = tuple(_bin_of(c, float(pt[c["name"]]))
                                 for c in conts)
            except (TypeError, ValueError, KeyError):
                bad = True
        if bad:
            n_bad += 1
            continue
        cells.add(cat_key + cont_key + tuple(cond_key))
    return ok_envelope(
        source=_SOURCE,
        bins=bins,
        n_points=len(points),
        n_bad_points=n_bad,
        n_cells_hit=len(cells),
        n_cells_applicable=applicable,
        coverage=len(cells) / applicable if applicable else None,
        acceptance="round19：4 维含 2 条件支覆盖 ≥95%（bins 离散档）",
    )
