"""campaign_notify：战役 digest webhook 推送通道（aurora_j W2-S6）。

背景：campaign_digest_service 产 JSON+txt 双产物落 runs/campaign_digest/
（aurora_e W3-S4，当时本仓无 webhook 通道、推送面留 followUp）——本模块
补齐推送面：把 digest 聚合结果推到飞书自定义机器人或通用 webhook
（POST JSON）。

语义与边界：
- **配置化缺省关**（campaign_queue_daemon env_hedge_* 同款先例）：配置
  env 单源读——``RFAUTO_NOTIFY_WEBHOOK_URL``（通用通道，POST
  ``{"text": 摘要}``）、``RFAUTO_NOTIFY_FEISHU_WEBHOOK``（飞书自定义
  机器人，POST ``{"msg_type":"text","content":{"text":摘要}}``），两键
  均未设 → skipped（零网络零行为变化）；``RFAUTO_NOTIFY_TIMEOUT_S``
  缺省 10s（非法/≤0 回缺省）；``notify_digest(..., config=...)`` 显式
  配置优先于 env（部分覆盖，测试注入面）；
- **零敏感铁律（AGENTS 规则 8）**：payload 文本由
  :func:`build_digest_payload` 从 digest 信封白名单字段重建（时间戳/
  战役数/终态计数/逐战役 name+model+verdict 词表+阶段进度）——root/
  plan 路径、失败原因自由文本等盘上原文**永不透传**；本地 txt 正文
  （notify_digest 的 ``text`` 参数）不进 payload，仅在长度上做提示语；
- **best-effort（#105）**：POST 超时/非 2xx/任何异常 → ok=False 信封
  返回，绝不抛出——通知失败不得影响 digest 主产物；
- POST 走 stdlib urllib.request（零新依赖）；网络面单点
  :func:`_http_post_json`（#139 惯例：测试 monkeypatch 它或注入
  opener 形参）。

数字出处：全部取自 campaign_digest 已产出的聚合字段，本模块零物理数字、
零状态机重算（AGENTS #7）。
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.request
from collections.abc import Callable
from typing import Any

from rfauto.service.campaign_digest_service import (
    TERMINAL_VERDICTS,
    VERDICT_MARK,
    VERDICT_ZH,
)
from rfauto.service.envelope import ok_envelope, skipped_envelope

# 有意不声明 __all__（同 campaign_digest_service.py 口径）：check_public_api
# 金快照不收私有模块——并发席位共用该金快照文件，本席零共享金样 churn
#（#228 门作用域限本项文件）。

#: 通用 webhook 通道 env 键（POST {"text": 摘要}）。
NOTIFY_WEBHOOK_URL_ENV = "RFAUTO_NOTIFY_WEBHOOK_URL"

#: 飞书自定义机器人通道 env 键（POST {"msg_type":"text","content":{...}}）。
NOTIFY_FEISHU_WEBHOOK_ENV = "RFAUTO_NOTIFY_FEISHU_WEBHOOK"

#: 推送超时 env 键与缺省秒数（未设/空/非法/≤0 回缺省）。
NOTIFY_TIMEOUT_S_ENV = "RFAUTO_NOTIFY_TIMEOUT_S"
NOTIFY_TIMEOUT_S_DEFAULT = 10.0

#: 逐战役行内联上限（聚合防刷屏，超出只报计数——digest 模块同款纪律）。
_INLINE_MAX = 20


def _int_or(v: Any, default: int = 0) -> int:
    """白名单数字段宽容取整（非数/None 回缺省——payload 构造零抛出）。"""
    with contextlib.suppress(TypeError, ValueError):
        return int(v)
    return default


def notify_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """通知配置单源：显式 ``config`` 优先（部分覆盖），env 兜底。

    返回键：``webhook_url`` / ``feishu_webhook``（None=未配置=该通道关）、
    ``timeout_s``（float）。env 空串视同未设（配置面零脏数据）；显式
    config 的通道字段非 None 且非字符串（bool/数字等）抛
    :class:`ValueError`（带字段名）——宁契约错误不 silently-wrong
    （``str(False)=="False"`` 当 URL 是假配置真推送）。
    """
    cfg: dict[str, Any] = {
        "webhook_url": str(os.environ.get(NOTIFY_WEBHOOK_URL_ENV) or "").strip()
        or None,
        "feishu_webhook": str(
            os.environ.get(NOTIFY_FEISHU_WEBHOOK_ENV) or "").strip() or None,
        "timeout_s": NOTIFY_TIMEOUT_S_DEFAULT,
    }
    raw_t = str(os.environ.get(NOTIFY_TIMEOUT_S_ENV) or "").strip()
    if raw_t:
        with contextlib.suppress(ValueError):
            t = float(raw_t)
            if t > 0:
                cfg["timeout_s"] = t
    if config:
        for k in ("webhook_url", "feishu_webhook"):
            v = config.get(k)
            if v is None:
                continue  # None=该通道不覆盖（未配置语义）
            if not isinstance(v, str):
                raise ValueError(
                    f"notify config {k!r} 须为字符串或 None，收到 "
                    f"{type(v).__name__}（{v!r}）——bool/数字当 URL 属"
                    "契约错误，拒绝不静默")
            if v.strip():
                cfg[k] = v.strip()
        with contextlib.suppress(TypeError, ValueError):
            t2 = float(config.get("timeout_s"))
            if t2 > 0:
                cfg["timeout_s"] = t2
    return cfg


def build_digest_payload(digest: dict[str, Any],
                         text: str | None = None) -> str:
    """白名单一句话 zh 摘要（payload 唯一文本源，零敏感单点）。

    只读 digest 信封白名单字段：``generated_at`` / ``n_campaigns`` /
    ``counts`` / ``campaigns[].{name,model,verdict,n_done,n_stages}``——
    逐战役行的状态词只出 verdict 词表映射（VERDICT_ZH/VERDICT_MARK，
    未知 verdict 显示"未知"，不回显 plan 本体自由串）；root/plan 路径、
    失败原因（reason 自由文本）、summary_text/headline 等盘上原文一律
    **不读入 payload**（AGENTS 规则 8）。``text``（本地 txt 正文）仅当
    digest 缺聚合字段时以"长度"入提示语，内容永不透传。

    形态（风格对齐 digest txt 首行）::

        [rfauto 战役摘要]（2026-10-23 10:00:00）：共 3 战役终态——
        2 完成、1 部分完成、0 已中止
        - wilkinson ✓ 完成（6/6 阶段）
    """
    if not isinstance(digest, dict) or "n_campaigns" not in digest:
        return (f"[rfauto 战役摘要] digest 字段不完整，"
                f"本地摘要 {len(str(text or ''))} 字符未透传")
    counts_raw = digest.get("counts")
    counts_raw = counts_raw if isinstance(counts_raw, dict) else {}
    counts = {v: _int_or(counts_raw.get(v)) for v in TERMINAL_VERDICTS}
    n_total = _int_or(digest.get("n_campaigns"))
    stat = "、".join(f"{counts[v]} {VERDICT_ZH[v]}" for v in TERMINAL_VERDICTS)
    head = (f"[rfauto 战役摘要]（{digest.get('generated_at')}）："
            f"共 {n_total} 战役终态——{stat}")
    n_other = n_total - sum(counts.values())
    if n_other > 0:
        head += f"（另 {n_other} 个非终态计入）"
    lines = [head]
    items = digest.get("campaigns")
    items = items if isinstance(items, list) else []
    n_inlined = 0
    for it in items[:_INLINE_MAX]:
        if not isinstance(it, dict):
            continue
        display = str(it.get("model") or "") or str(it.get("name") or "") or "?"
        verdict = str(it.get("verdict") or "")
        mark = VERDICT_MARK.get(verdict, "?")
        zh = VERDICT_ZH.get(verdict, "未知")
        n_done = it.get("n_done")
        n_stages = it.get("n_stages")
        done_s = "?" if n_done is None else str(_int_or(n_done))
        stages_s = "?" if n_stages is None else str(_int_or(n_stages))
        lines.append(f"- {display} {mark} {zh}（{done_s}/{stages_s} 阶段）")
        n_inlined += 1
    if n_inlined < len(items):
        lines.append(f"（另 {len(items) - n_inlined} 战役未逐列，"
                     "详见本地 digest 产物）")
    return "\n".join(lines)


def _http_post_json(url: str, payload: dict[str, Any],
                    timeout_s: float) -> int:
    """网络面单点（#139）：POST JSON → HTTP 状态码；测试 monkeypatch 点。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return int(getattr(resp, "status", 0) or 0)


def notify_digest(
    digest: dict[str, Any],
    text: str,
    *,
    config: dict[str, Any] | None = None,
    opener: Callable[[str, dict[str, Any], float], int] | None = None,
) -> dict[str, Any]:
    """digest → 已配置 webhook 通道推送（best-effort，绝不抛出，#105）。

    参数：
    - digest：campaign_digest 返回信封（白名单字段进 payload，见
      :func:`build_digest_payload`）；
    - text：本地 txt 摘要正文——**不透传**（可能含 root 绝对路径/失败
      原因自由文本），仅当 digest 缺聚合字段时以长度入提示语；
    - config：显式配置（``webhook_url``/``feishu_webhook``/``timeout_s``，
      部分覆盖 env；测试注入面）；
    - opener：网络注入缝（缺省走 :func:`_http_post_json`；签名
      ``(url, payload_dict, timeout_s) -> HTTP 状态码``，测试假网络面）。

    返回：
    - 两通道均未配置 → skipped 信封（缺省关零行为，零网络）；
    - 配置了 → 逐通道 POST，结果入 ``results``（``{"ok", "status"}`` 或
      ``{"ok": False, "error"}``），整体 ``ok``=全部通道成功。
    """
    payload_text = build_digest_payload(digest, text)
    cfg = notify_config(config)
    targets: list[tuple[str, str, dict[str, Any]]] = []
    if cfg["webhook_url"]:
        targets.append(
            ("webhook", str(cfg["webhook_url"]), {"text": payload_text}))
    if cfg["feishu_webhook"]:
        targets.append((
            "feishu", str(cfg["feishu_webhook"]),
            {"msg_type": "text", "content": {"text": payload_text}}))
    if not targets:
        return skipped_envelope(
            "not_configured：RFAUTO_NOTIFY_WEBHOOK_URL/"
            "RFAUTO_NOTIFY_FEISHU_WEBHOOK 均未设（缺省关零行为）")
    timeout_s = float(cfg["timeout_s"])
    post = opener if opener is not None else _http_post_json
    results: dict[str, Any] = {}
    for name, url, payload in targets:
        try:
            status = int(post(url, payload, timeout_s))
            results[name] = ({"ok": True, "status": status}
                             if 200 <= status < 300
                             else {"ok": False, "error": f"HTTP {status}"})
        except Exception as exc:  # #105：观测面绝不抛——通知失败不拆主路径
            results[name] = {"ok": False,
                             "error": str(exc) or type(exc).__name__}
    return ok_envelope(
        ok=all(r["ok"] for r in results.values()),
        channels=[name for name, _, _ in targets],
        results=results,
    )
