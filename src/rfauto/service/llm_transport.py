"""LLM 传输层叶（T1 终章解环；架构批 W1-S1）。

从 agent_runtime 叶化：``openai_chat_completion`` 是纯外呼传输面
（OpenAI 兼容 /chat/completions，configs/chat_settings.yaml 的
base_url/model/api_key 配置），被 systemone_service / robust_rewrite /
runtime_ab / r3_services.chat 多处函数内引用。叶化后 systemone_service
的 ``_default_chat_transport`` 改读本叶，静态图上不再出现
systemone→agent_runtime 边（agent_runtime→agent_safety→systemone→
agent_runtime 三角环的最后一条回边断；第一条 agent_runtime→agent_safety
TYPE_CHECKING 边由 agent_waterfall_types 叶断——R1 架构深审 v3 §2.2 S1，
内部证据目录）。

消费面与测试缝保真声明：
- agent_runtime 顶层同名再导出（``openai_chat_completion as
  openai_chat_completion``）：robust_rewrite / runtime_ab /
  r3_services.chat 的 ``from rfauto.service.agent_runtime import
  openai_chat_completion`` 消费路径零改动（lazy import 在调用时读
  agent_runtime 模块属性，再导出保属性在位）；
- 测试缝：test_w2s10_agent_trace.py 的
  ``monkeypatch.setattr(agent_runtime, "openai_chat_completion", ...)``
  钉的是 agent_runtime 模块属性——BuiltinOpenAIRuntime.__init__ 的
  ``transport or openai_chat_completion`` 在实例化时读 agent_runtime
  全局，patch 先于实例化即生效，缝不变（再导出后属性仍解析到本叶
  同一函数对象）；
- 函数体逐字节搬迁（含函数内 lazy import：urllib.request 与
  chat_settings_io.get_chat_settings_raw 的 import 位置不动），不
  change 任何行为。
"""
from __future__ import annotations

import json
from typing import Any


def openai_chat_completion(
        messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    """默认传输层：OpenAI 兼容 /chat/completions（configs/chat_settings.yaml）。"""
    import urllib.request

    from rfauto.service.chat_settings_io import get_chat_settings_raw
    cfg = get_chat_settings_raw()
    base = (cfg.get("base_url") or "").rstrip("/")
    url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    body = json.dumps({"model": cfg.get("model", ""), "messages": messages,
                       "tools": tools, "temperature": 0.3}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + (cfg.get("api_key") or "")})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))
