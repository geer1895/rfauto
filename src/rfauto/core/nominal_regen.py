"""nominal_regen：名义值闭式再生内核（XC-N，round15 横切"巡检门"的确定性核对面）。

审计断言（round15 原文）："nominal 可由 core 链 round 再现"。本模块把
断言落成确定性的**再生产内**（core，零 I/O）：每模板一条再生链——从
meta 声明的设计输入（f0/er/h 等）出发，调用 core 综合闭式，重算名义
参数值；与注册名义值逐键比对（容差=链内 rounding 位数）。

**口径裁决（#122 预声明）**：
- 比较是"链再生 vs 注册名义"的一致性巡检，**不裁决谁对谁错**——
  注册名义与再生值不一致时如实报 MISMATCH（双值随行），修复方向
  （更新名义 vs 修链）由人工/锚仲裁决定（#1c：先验模型正确性）；
- 无再生链的模板=NOT_COVERED（如实不猜，巡检门逐模板豁免名单由此
  自然生成而非人工白名单）；
- 首件 patch（round15 点名"先清 patch/coil_nfc"——coil_nfc 链待
  nfc_coil 综合面接线后补入注册表）。

消费点：service/nominal_regen_service.py 巡检编排 + docs/templates
巡检注记。**只读** adapters.openems_templates 的 TEMPLATE_NOMINAL
（adapters 本批禁改）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _regen_patch(nominal: dict[str, Any]) -> dict[str, float]:
    """patch 再生链：synthesize_patch(f0, er, h) → 三参数（round 2 同链）。"""
    from rfauto.core.synthesis import synthesize_patch

    f0 = float(nominal.get("f0_ghz", 2.4))
    er = float(nominal.get("er", 3.66))
    h = float(nominal.get("h_mm", 0.508))
    res = synthesize_patch(f0_ghz=f0, er=er, h_mm=h)
    return {"patch_len_mm": float(res.params["patch_len_mm"]),
            "patch_w_mm": float(res.params["patch_w_mm"]),
            "feed_offset_mm": float(res.params["feed_offset_mm"])}


#: 再生链注册表：模板 → {"chain": 可调用, "inputs": 链输入键（meta 顶层
#: nominal 表内的设计输入键，其余键=被再生对象）, "round": 链内舍入位数}
NOMINAL_REGEN_CHAINS: dict[str, dict[str, Any]] = {
    "patch": {"chain": _regen_patch,
              "inputs": ("f0_ghz", "er", "h_mm"),
              "round": 2},
}


def regenerate_nominal(template: str,
                       nominal: dict[str, Any],
                       *, chains: dict[str, dict[str, Any]] | None = None,
                       ) -> dict[str, Any]:
    """单模板名义再生：返回 {covered, regenerated, missing_inputs, error}。

    covered=链覆盖的参数键；regenerated=链再生值（round 同链位数）；
    missing_inputs=链声明的设计输入键在 nominal 表缺失者（缺任一输入
    即不跑链，如实 NOT_RUN）。
    """
    table = chains if chains is not None else NOMINAL_REGEN_CHAINS
    entry = table.get(str(template))
    if entry is None:
        return {"template": str(template), "covered": [], "regenerated": {},
                "missing_inputs": [], "error": None, "verdict": "NOT_COVERED"}
    chain: Callable[[dict[str, Any]], dict[str, float]] = entry["chain"]
    inputs = tuple(entry.get("inputs", ()))
    missing = [k for k in inputs if nominal.get(k) is None]
    if missing:
        return {"template": str(template), "covered": [], "regenerated": {},
                "missing_inputs": missing, "error": None, "verdict": "NOT_RUN"}
    try:
        regenerated = chain(nominal)
    except (KeyError, TypeError, ValueError) as exc:
        return {"template": str(template), "covered": [], "regenerated": {},
                "missing_inputs": [], "error": f"{type(exc).__name__}: {exc}",
                "verdict": "ERROR"}
    digits = int(entry.get("round", 2))
    regenerated = {k: round(float(v), digits) for k, v in regenerated.items()}
    return {"template": str(template), "covered": sorted(regenerated),
            "regenerated": regenerated, "missing_inputs": [],
            "error": None, "verdict": "OK"}


def compare_nominal(template: str, nominal: dict[str, Any],
                    regenerated: dict[str, float],
                    ) -> dict[str, Any]:
    """再生值 vs 注册名义逐键比对（#117 纪律：键缺失显式判，不 or 兜底）。

    verdict 三值：MATCH（覆盖键全部一致）/ MISMATCH（任一覆盖键不一致，
    双值随行）/ NOT_COVERED（无覆盖键）。
    """
    covered = sorted(regenerated)
    if not covered:
        return {"template": str(template), "verdict": "NOT_COVERED",
                "keys": [], "mismatches": []}
    mismatches = []
    for key in covered:
        reg = float(regenerated[key])
        reg_val = nominal.get(key)
        if reg_val is None:
            mismatches.append({"key": key, "regenerated": reg,
                               "registered": None,
                               "note": "再生链覆盖键在注册名义表缺值"})
            continue
        try:
            regn = float(reg_val)
        except (TypeError, ValueError):
            mismatches.append({"key": key, "regenerated": reg,
                               "registered": reg_val, "note": "注册名义非数值"})
            continue
        if regn != reg:  # 链内同 round 位数 → 应逐位一致；不一致即漂移
            mismatches.append({"key": key, "regenerated": reg,
                               "registered": regn})
    verdict = "MISMATCH" if mismatches else "MATCH"
    return {"template": str(template), "verdict": verdict,
            "keys": covered, "mismatches": mismatches}
