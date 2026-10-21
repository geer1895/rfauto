"""chat_settings.yaml 原始读取叶（T1 解环；架构批 W6-S1）。

从 r3_services 叶化：get_chat_settings_raw 是纯配置读面（含 api_key
明文，契约性不对外——api 门面 _EXCLUDED 排除不变）。transport 侧
（agent_runtime/systemone/pydantic_ai_runtime）改读本叶，静态图上
不再出现实现→r3_services 边（R1 审计 19 模块 SCC 的
agent_runtime↔r3 臂；架构批 补齐 pydantic_ai_runtime 一处）。
测试缝不变：r3 内部消费面经 r3_services 模块属性再导出，既有
``setattr(r3_services, "get_chat_settings", ...)`` 钉点照常生效。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

CHAT_SETTINGS_PATH = Path("configs") / "chat_settings.yaml"


def get_chat_settings_raw() -> dict[str, Any]:
    """内部用：原始设置（含 api_key），不对外。"""
    import yaml

    if not CHAT_SETTINGS_PATH.exists():
        return {}
    return yaml.safe_load(CHAT_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
