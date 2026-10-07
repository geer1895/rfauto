"""XN-4 跨战役敏感性先验（round19 P2，ge8c 席C6）——结构信息积累→先验库→预算加权。

定位（round19 口径"每战役 Sobol/Morris 结构信息积累→模板级'全局敏感性
先验'库→新战役采样预算按历史重要性加权（warm_start 参数面复用的姊妹件
=结构信息复用）"）：

- **记录**（register 面）：每战役一条 ``SensitivityRecord``——直接消费
  ``optimization.sensitivity`` 的输出形状（sobol：``{param: {S1, ST}}``；
  morris：``{param: {mu_star, sigma}}``），本模块不重算敏感度（内核在
  optimization 层，分层契约：本模块在 core，只做**结构信息聚合**）；
- **先验**（prior 面）：模板级聚合——每战役重要性向量先归一（Sobol S1
  天然无量纲；Morris mu_star 按战役内 Σmu_star 归一，吸收量纲/尺度），
  逐参数取**中位数**（跨战役鲁棒，单战役离群不绑架先验），并报覆盖数
  （该参数出现在几场战役）；确定性全序，无随机；
- **预算加权**（allocate 面）：``n_i ∝ max(w_i, min_weight)`` 后按最大余数
  法整数分配（确定性：余数同分按参数名字典序）；低敏感参数保底防饿死
  （结构先验是采样效率先验，不是"砍参数"裁决）。

诚实边界（#122）：先验只影响**采样预算分配**，不产生任何物理数字；记录
里 method/n_samples/seed 原样留痕（可复现性钉）；战役数 <2 时如实标
``n_campaigns`` 并照常出先验（单战役先验=该战役自身结构，注明未跨验）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "PRIOR_SCHEMA",
    "SensitivityRecord",
    "allocate_budget",
    "build_template_prior",
    "render_prior_markdown",
]

#: 先验库 schema 标识（JSON 消费面稳定钉）。
PRIOR_SCHEMA = "rfauto-sensitivity-prior-v1"

#: 记录方法词表（与 optimization.sensitivity 两种输出形态一一对应）。
_METHODS = ("sobol", "morris")


class SensitivityRecord(BaseModel):
    """一场战役的敏感度结构记录（不存物理响应值，只存无量纲结构）。"""

    model_config = ConfigDict(frozen=True)

    template: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    method: str = Field(pattern="^(sobol|morris)$")
    #: Sobol: {param: {S1, ST}}；Morris: {param: {mu_star, sigma}}
    sensitivity: dict[str, dict[str, float]]
    n_samples: int = Field(ge=1)
    seed: int = 0
    note: str = ""

    @field_validator("sensitivity")
    @classmethod
    def _validate_sensitivity(
        cls, v: dict[str, dict[str, float]], info: Any
    ) -> dict[str, dict[str, float]]:
        if not v:
            raise ValueError("sensitivity 不可为空（空战役无结构信息可积累）")
        method = (info.data or {}).get("method")
        expected = {"S1", "ST"} if method == "sobol" else \
            {"mu_star", "sigma"} if method == "morris" else None
        for param, metrics in v.items():
            if not param or not isinstance(metrics, dict):
                raise ValueError(f"sensitivity[{param!r}] 形态非法")
            if expected is not None:
                missing = expected - set(metrics)
                if missing:
                    raise ValueError(
                        f"method={method} 缺指标键 {sorted(missing)}"
                        f"（param={param}）")
            for k, num in metrics.items():
                if isinstance(num, bool) or not isinstance(num, (int, float)) \
                        or not math.isfinite(float(num)):
                    raise ValueError(
                        f"sensitivity[{param}][{k}] 必须有限数")
        return v


def _normalized_importance(rec: SensitivityRecord) -> dict[str, float]:
    """单战役重要性向量归一（Σ=1；负值裁 0——归一化误差下 S1 可能 -1e-16）。"""
    raw = {}
    for param, metrics in rec.sensitivity.items():
        val = metrics.get("S1") if rec.method == "sobol" \
            else metrics.get("mu_star")
        raw[param] = max(float(val), 0.0)
    total = sum(raw.values())
    if total <= 0.0:
        # 全零结构（退化战役）：均匀不硬凑——如实全 0，先验面记 degenerate
        return {p: 0.0 for p in raw}
    return {p: v / total for p, v in raw.items()}


def build_template_prior(records: Sequence[SensitivityRecord],
                         template: str) -> dict[str, Any]:
    """模板级先验：逐参数跨战役中位重要性 + 覆盖 + 退化标记（确定性）。"""
    if not records:
        raise ValueError("records 不可为空")
    sel = sorted(
        (r for r in records if r.template == template),
        key=lambda r: (r.campaign_id, r.method))
    if not sel:
        raise ValueError(f"template 无记录: {template!r}")
    per_campaign: list[tuple[str, str, dict[str, float]]] = []
    degenerate = 0
    for r in sel:
        imp = _normalized_importance(r)
        if all(v == 0.0 for v in imp.values()):
            degenerate += 1
        per_campaign.append((r.campaign_id, r.method, imp))

    all_params = sorted({p for _, _, imp in per_campaign for p in imp})
    med: dict[str, float] = {}
    coverage: dict[str, int] = {}
    for p in all_params:
        vals = sorted(imp[p] for _, _, imp in per_campaign if p in imp)
        coverage[p] = len(vals)
        n = len(vals)
        med[p] = (vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0)

    total = sum(med.values())
    normalized = ({p: (v / total if total > 0 else 0.0)
                   for p, v in med.items()} if total > 0 else dict(med))
    ranking = sorted(all_params, key=lambda p: (-normalized[p], p))
    return {
        "ok": True,
        "schema": PRIOR_SCHEMA,
        "template": template,
        "n_campaigns": len(sel),
        "n_degenerate": degenerate,
        "methods": sorted({m for _, m, _ in per_campaign}),
        "campaign_ids": sorted({cid for cid, _, _ in per_campaign}),
        "importance_median": normalized,
        "importance_raw_median": med,
        "coverage": coverage,
        "ranking": ranking,
        "note": ("跨战役中位重要性（结构先验）；n_campaigns<2 时未跨验，"
                 "预算加权前建议补一场独立战役" if len(sel) < 2 else
                 "跨战役中位重要性（结构先验）"),
    }


def allocate_budget(prior: Mapping[str, Any], total_n: int, *,
                    min_weight: float = 0.02) -> dict[str, Any]:
    """先验 → 新战役采样预算分配（最大余数法，确定性）。

    - ``min_weight``：单参数保底权重份额（防低敏感参数饿死；0<min<1/参数数）；
    - 总量 <参数数或 min_weight×参数数 >1 时 ValueError（不可行分配显式报）。
    """
    total_n = int(total_n)
    if total_n < 1:
        raise ValueError("total_n 必须 ≥1")
    if not 0.0 < min_weight < 1.0:
        raise ValueError("min_weight 必须在 (0,1)")
    imp = {str(k): float(v) for k, v in
           (prior.get("importance_median") or {}).items()}
    if not imp:
        raise ValueError("prior 缺 importance_median（先经 build_template_prior）")
    n_params = len(imp)
    if total_n < n_params:
        raise ValueError(
            f"total_n={total_n} < 参数数 {n_params}（每参数至少 1 点不可行）")
    if min_weight * n_params > 1.0:
        raise ValueError(
            f"min_weight={min_weight}×{n_params} 参数 >1（保底不可行）")
    floor = min_weight
    raw = {p: max(w, floor) for p, w in imp.items()}
    raw_total = sum(raw.values())
    weights = {p: v / raw_total for p, v in raw.items()}

    quota = {p: weights[p] * total_n for p in weights}
    alloc = {p: math.floor(q) for p, q in quota.items()}
    remainder = total_n - sum(alloc.values())
    # 余数按小数部分降序、再参数名字典序分配（确定性全序）
    order = sorted(weights, key=lambda p: (-(quota[p] - alloc[p]), p))
    for p in order[:remainder]:
        alloc[p] += 1
    return {
        "ok": True,
        "schema": PRIOR_SCHEMA,
        "template": prior.get("template"),
        "total_n": total_n,
        "min_weight": min_weight,
        "allocation": alloc,
        "weights": weights,
        "note": "先验只影响采样预算分配，不产生物理数字（铁律 7）",
    }


def render_prior_markdown(prior: Mapping[str, Any]) -> str:
    """先验 → Markdown（只渲染聚合量；非 ok 输入如实记失败）。"""
    if not prior.get("ok"):
        return f"# 敏感性先验\n\n- 生成失败：{prior.get('errors')}\n"
    lines = [
        f"# 敏感性先验（template={prior.get('template')}）", "",
        f"- 战役数：{prior.get('n_campaigns')}（退化 "
        f"{prior.get('n_degenerate')}）；方法：{prior.get('methods')}", "",
        "| 参数 | 中位重要性（归一） | 覆盖战役数 |",
        "| --- | --- | --- |",
    ]
    cov = prior.get("coverage") or {}
    for p in prior.get("ranking") or []:
        w = (prior.get("importance_median") or {}).get(p, 0.0)
        lines.append(f"| {p} | {w:.4f} | {cov.get(p, 0)} |")
    lines += ["", f"> {prior.get('note', '')}", ""]
    return "\n".join(lines)
