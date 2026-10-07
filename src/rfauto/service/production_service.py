"""PT-7 产线测试数据服务面（JSON 进出薄壳，规则 4：新功能先写 service）。

规格 研究扩充 round18 §四 PT-7：产线测试数据
schema + 按测项失效率 Pareto。数值全在确定性内核 core/production_data.py
（铁律 7），本模块只做 JSON/dict 归一面与文件装载（load_json_records），
零计算零物理数字（阈值/实测值只透传）。

**dataset_service 扩展说明**：规格原文"dataset_service 扩 schema"——
dataset_service.py 为既有服务文件（本席禁改），扩展接线留归属面批次；
本文件是 PT-7 的独立新增消费面，schema 键名与 dataset_service 的行式
schema 风格对齐（snake_case、schema 版本串头注），后续并入时可平移。

接口纪律：JSON 进出；bool 显式拒收交内核；文件只读 JSON；无 CLI/MCP 面
（任务书纪律 4）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rfauto.core.production_data import (
    PRODUCTION_SCHEMA_VERSION,
    failure_pareto,
    lot_yield,
    normalize_records,
    vendor_batch_summary,
)

__all__ = [
    "PRODUCTION_SCHEMA_VERSION",
    "load_json_records",
    "production_overview",
    "records_from_payload",
]


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    """dict/list 载荷 → 归一记录列表。

    接受两种形态：裸记录列表、或 ``{"records": [...]}`` 信封（信封缺
    records 键如实 ValueError，不静默空表——#316 方向）。
    """
    if isinstance(payload, dict):
        if "records" not in payload:
            raise ValueError("信封形态载荷必须含 records 键")
        payload = payload["records"]
    return normalize_records(payload)


def load_json_records(path: str | Path) -> list[dict[str, Any]]:
    """从 JSON 文件装载产线测试记录（只读；异常如实上抛不吞）。"""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        return records_from_payload(json.load(fh))


def production_overview(payload: Any) -> dict[str, Any]:
    """一次出三面（Pareto / 批次良率 / 供应商批次摘要），JSON 可序列化。"""
    rows = records_from_payload(payload)
    return {
        "schema": PRODUCTION_SCHEMA_VERSION,
        "pareto": failure_pareto(rows),
        "lot_yield": lot_yield(rows),
        "vendor_batches": vendor_batch_summary(rows),
    }
