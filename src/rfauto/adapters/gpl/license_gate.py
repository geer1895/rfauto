"""fail-closed GPL 许可门（adapters/gpl 子包共享；SV-1/SV-2 强制前置）。

许可边界（任务书 SV-1 原文："license/许可边界写死 fail-closed"）：

- scuff-em 为 GPL-2/3、PyPO 为 GPL-3 的 copyleft 工程。rfauto 主机程序
  与它们的合规交互面 = **子进程调用**（mere aggregation 边界）+ 用户
  对 GPL 工具使用的**显式知情 opt-in**。两道边界中任何一道不满足，
  通道一律拒绝执行——fail-closed：缺省拒绝、解析不了的值也拒绝、
  只认显式真值令牌。
- 门只管"是否允许走该通道"；可用性探测（exe 是否在盘、包是否可
  import）不执行被测工具、不构成 GPL 交互，不受门约束（is_available
  语义照旧）。

开通方式（写死为环境变量，缺省拒绝）：
- 全局：``RFAUTO_ALLOW_GPL_TOOLS=1|true|yes|on``（大小写不敏感）；
- 单工具：``RFAUTO_ALLOW_SCUFF`` / ``RFAUTO_ALLOW_PYPO``（同令牌集）。
- 其余任何值（0/false/空串/拼写错）= 拒绝——不猜意图。
"""

from __future__ import annotations

import os
from collections.abc import Mapping

_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})

#: 全局 opt-in 环境变量
ALLOW_ENV = "RFAUTO_ALLOW_GPL_TOOLS"


class LicenseRefusedError(RuntimeError):
    """GPL 通道被 fail-closed 许可门拒绝（附 remedy 文案）。"""


def _env_get(environ: Mapping[str, str] | None, key: str) -> str | None:
    src = os.environ if environ is None else environ
    val = src.get(key)
    return val if val is None else str(val)


def _explicit_true(raw: str | None) -> bool:
    """只认显式真值令牌；None/其余一律 False（fail-closed，不猜意图）。"""
    if raw is None:
        return False
    return raw.strip().lower() in _TRUE_TOKENS


def gpl_gate_decision(
    tool: str, environ: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    """GPL 工具通道是否放行（fail-closed 纯函数判定）。

    Args:
        tool: 工具键（"scuff" | "pypo"；单工具 env 键取大写形式）。
        environ: 环境映射（None=真实 os.environ；测试注入用）。

    Returns:
        (allowed, reason)：reason 为放行/拒绝的一句话依据（拒绝时含
        remedy：显式 opt-in 的环境变量名与令牌集）。
    """
    key = str(tool).strip().lower()
    if key not in ("scuff", "pypo"):
        return False, (
            f"未知 GPL 工具键 {tool!r}（fail-closed：只认 scuff | pypo）")
    # 单工具 env 显式设置（任何值）时优先裁定；未设置才落全局开关
    per_tool = _env_get(environ, f"RFAUTO_ALLOW_{key.upper()}")
    if per_tool is not None:
        if _explicit_true(per_tool):
            return True, f"显式 opt-in：RFAUTO_ALLOW_{key.upper()}={per_tool}"
        return False, (
            f"GPL 工具 {key!r} 通道被许可门拒绝（RFAUTO_ALLOW_"
            f"{key.upper()}={per_tool!r} 非真值令牌——只认 1/true/yes/on，"
            "不猜意图）")
    glob = _env_get(environ, ALLOW_ENV)
    if _explicit_true(glob):
        return True, f"显式 opt-in：{ALLOW_ENV}={glob}"
    return False, (
        f"GPL 工具 {key!r} 通道被许可门拒绝（fail-closed 缺省拒绝）："
        f"scuff-em 为 GPL-2/3、PyPO 为 GPL-3 copyleft 工程，rfauto 仅以"
        f"子进程边界交互；如知情接受，请显式设置 "
        f"RFAUTO_ALLOW_{key.upper()}=1 或 {ALLOW_ENV}=1"
        f"（只认 1/true/yes/on，其余值含拼写错一律仍拒绝）")


def require_gpl_channel(
    tool: str, environ: Mapping[str, str] | None = None,
) -> str:
    """门通过则返回放行依据；拒绝则抛 :class:`LicenseRefusedError`。"""
    allowed, reason = gpl_gate_decision(tool, environ)
    if not allowed:
        raise LicenseRefusedError(reason)
    return reason
