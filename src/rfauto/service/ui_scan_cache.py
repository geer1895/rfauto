"""UI 扫描面缓存原语叶（T1 解环；aurora_g W6-S1）。

从 ui_service 叶化：_UiScanCache（TTL+签名失效，RFAUTO_UI_CACHE=0
直通）被 rationale_memory 复用（strict 顶层 import 是 19 模块 SCC 的
唯一自上而下 strict 环边）。叶化后 rationale_memory 改读本叶。
测试缝：``setattr(ui_service, "_UI_SCAN_TTL_S", ...)`` 的 4 处钉点
随定义体改指本叶模块（test_ui_service_cache/test_w1s4_service_cache
同步更新，断言行为不变）。日志器名随模块（ui_scan_cache miss 记录
的 logger name 变更，消息文本不变——无测试断言 logger 名）。
"""
from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any

_LOG = logging.getLogger(__name__)


_UI_CACHE_OFF_VALUES = frozenset({"0", "false", "off", "no"})


_UI_SCAN_TTL_S = 60.0


def _ui_cache_enabled() -> bool:
    """env RFAUTO_UI_CACHE=0|false|off|no → 直通；其余（含未设）→ 启用。"""
    raw = os.environ.get("RFAUTO_UI_CACHE", "")
    return raw.strip().lower() not in _UI_CACHE_OFF_VALUES


class _UiScanCache:
    """进程内 TTL+签名失效缓存（runs/ 扫描面专用；观测 best-effort #105）。

    值约定：缓存对象只被端点组装读取；端点快照返回前 deepcopy，调用方
    的 sort/slice/append 不污染缓存。签名不可得（None）不落缓存——下次
    必重扫（宁多扫不多旧）。
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._store: dict[Any, tuple[float, Any, Any]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: Any, signature: Any, producer: Any) -> Any:
        if not _ui_cache_enabled():
            return producer()
        now = time.monotonic()
        ent = self._store.get(key)
        if (ent is not None and ent[1] == signature
                and (now - ent[0]) < _UI_SCAN_TTL_S):
            self.hits += 1
            return ent[2]
        t0 = time.perf_counter()
        value = producer()
        self.misses += 1
        with contextlib.suppress(Exception):  # 观测不阻塞主路径（#105）
            _LOG.info("ui_scan_cache miss cache=%s key=%r cost=%.1fms",
                      self.name, key, (time.perf_counter() - t0) * 1000.0)
        if signature is not None:
            self._store[key] = (now, signature, value)
        return value

    def stats(self) -> dict[str, Any]:
        return {"enabled": _ui_cache_enabled(), "hits": self.hits,
                "misses": self.misses, "entries": len(self._store)}
