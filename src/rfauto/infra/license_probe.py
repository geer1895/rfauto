"""License-aware 队列。

探测 license server 可用性；不可用时调用方应挂起（等待重试）而非失败——
真机 HFSS 求解 40 分钟成本，一次探测失败不应烧掉整个多保真管线。
观测性/外部探测代码遵循 best-effort 原则（#105）：任何异常都不抛出主路径。
"""

from __future__ import annotations

import logging
import os
import socket
import time

logger = logging.getLogger(__name__)

# 常见 license 环境变量（按序探测）
LICENSE_ENV_VARS = (
    "ANSYSLMD_LICENSE_FILE",  # AEDT
    "RFAUTO_LICENSE_SERVER",  # 显式覆盖（host:port 或 port@host）
)

DEFAULT_PROBE_TIMEOUT_S = 3.0
DEFAULT_POLL_S = 30.0


def _parse_server(spec: str) -> tuple[str, int] | None:
    """解析 'host:port' / '1055@host' 形态；解析失败返回 None。"""
    spec = spec.strip()
    if "@" in spec:
        port_s, _, host = spec.partition("@")
        try:
            return host.strip(), int(port_s.strip())
        except ValueError:
            return None
    if ":" in spec:
        host, _, port_s = spec.rpartition(":")
        try:
            return host.strip(), int(port_s)
        except ValueError:
            return None
    return None


def probe_license(server: str | None = None, *, timeout_s: float = DEFAULT_PROBE_TIMEOUT_S) -> dict:
    """探测 license server 可达性（TCP 层）。

    server 为空时依次尝试环境变量中的配置；全部缺失时返回 unknown（不算失败，
    本机节点锁 license 场景没有 server 可探测，由调用方决定放行）。
    """
    candidates: list[str] = []
    if server:
        candidates.append(server)
    else:
        for var in LICENSE_ENV_VARS:
            val = os.environ.get(var, "").strip()
            if val:
                candidates.append(val)

    if not candidates:
        return {"available": True, "server": None, "detail": "no license server configured; assuming local/loopback license"}

    for spec in candidates:
        parsed = _parse_server(spec)
        if parsed is None:
            return {"available": True, "server": spec,
                    "detail": "non-TCP license spec (port@host 解析失败)，无法探测，放行"}
        host, port = parsed
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                logger.info("license server %s:%s reachable", host, port)
                return {"available": True, "server": spec, "detail": f"tcp {host}:{port} reachable"}
        except OSError as e:
            logger.warning("license server %s unreachable: %s", spec, e)
            return {"available": False, "server": spec, "detail": str(e)}
    return {"available": False, "server": None, "detail": "no candidate probed"}


def wait_for_license(
    *,
    server: str | None = None,
    max_wait_s: float = 600.0,
    poll_s: float = DEFAULT_POLL_S,
    timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
) -> dict:
    """等待 license 可用；挂起重试而非立即失败（license-aware 队列）。

    Returns: {"available": bool, "waited_s": float, "probes": int, ...probe fields}
    """
    t0 = time.time()
    probes = 0
    last = probe_license(server, timeout_s=timeout_s)
    while not last["available"] and (time.time() - t0) < max_wait_s:
        probes += 1
        logger.info("license 不可用，%.0fs 后重试（已等 %.0fs/%.0fs）",
                    poll_s, time.time() - t0, max_wait_s)
        time.sleep(poll_s)
        last = probe_license(server, timeout_s=timeout_s)
    return {**last, "waited_s": round(time.time() - t0, 1), "probes": probes + 1}
