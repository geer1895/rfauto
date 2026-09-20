"""ADS 通道选择器（项目 A）—— 按版本与可用性在 M/A/B/C 档间决策。

通道定义（与 compat_matrix.yaml channel 字段一致）：
- m  官方 MCP（ADS 2027 起 bin/ads-mcp.exe；需要运行中的 ADS GUI 会话）
- a  A档 ads_python_api（ADS 2027 原生 Python API，须 ≥2027）
- b  B档 网表 + hpeesofsim 子进程（生产主通道，兼容面最宽）
- c  C档 人工保底（恒可用：导出 sNp + 导入指南）

选择原则：
1. 版本决定候选集（compat_matrix.ads.versions.<ver>.channel，缺省 [b, c]）
2. 候选按优先级排序后逐一检查本地可用性，返回首个可用通道 + 全量探测
   结果（降级原因可审计）
3. 显式 prefer 可强制指定（未可用时报错而非静默降级）

rfauto 自己的 MCP server（mcp_server.py，Agent 统一入口）与本选择器
无关——官方 MCP 是通道实现选项，不是它的替代品。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from rfauto.infra.version_probe import detect_ads_version, load_compat_matrix

logger = logging.getLogger(__name__)

_CHANNELS = ("m", "a", "b", "c")


def _version_from_dir(ads_dir: Path) -> str | None:
    return detect_ads_version(ads_dir)


def _matrix_channels(version: str | None) -> list[str]:
    matrix = load_compat_matrix()
    ads_cfg = matrix.get("ads", {})
    versions = ads_cfg.get("versions", {}) if isinstance(ads_cfg, dict) else {}
    entry = versions.get(version or "", {})
    if isinstance(entry, dict) and entry.get("channel"):
        return [c for c in entry["channel"] if c in _CHANNELS]
    return ["b", "c"]


def probe_channel_availability(
    ads_dir: str | Path,
    version: str | None = None,
) -> dict[str, dict[str, Any]]:
    """逐通道探测本地可用性。返回 {channel: {available, reason}}。"""
    ads_dir = Path(ads_dir)
    bin_dir = ads_dir / "bin"
    result: dict[str, dict[str, Any]] = {}

    # M：官方 MCP server 可执行文件（2027 起随产品分发）
    mcp_exe = bin_dir / "ads-mcp.exe"
    if mcp_exe.exists():
        result["m"] = {
            "available": True,
            "reason": f"官方 MCP server 存在: {mcp_exe}",
            "note": "连接还需要运行中的 ADS GUI 会话（server 为会话感知型）",
        }
    else:
        result["m"] = {"available": False, "reason": "未找到 bin/ads-mcp.exe（需 ADS 2027+）"}

    # A：原生 Python API（2027 起提供 keysight.ads 包；实际 import 在
    # ADS 自带 python 子进程内进行，此处按版本门槛做静态判定）
    if version is not None and version >= "2027":
        result["a"] = {"available": True, "reason": f"ADS {version} ≥ 2027，Python API 可用"}
    else:
        result["a"] = {"available": False, "reason": "Python API 需 ADS 2027+"}

    # B：hpeesofsim 求解器
    sim_exe = bin_dir / "hpeesofsim.exe"
    if sim_exe.exists():
        result["b"] = {"available": True, "reason": f"hpeesofsim 存在: {sim_exe}"}
    else:
        result["b"] = {"available": False, "reason": "未找到 bin/hpeesofsim.exe"}

    # C：人工保底恒可用
    result["c"] = {"available": True, "reason": "导出 sNp + 导入指南（恒可用）"}
    return result


def select_ads_channel(
    ads_dir: str | Path | None = None,
    *,
    prefer: str | None = None,
) -> dict[str, Any]:
    """选择 ADS 通道：矩阵候选 × 本地可用性，返回决策与审计信息。

    Args:
        ads_dir: ADS 安装目录；None 时走 settings/env 解析
        prefer: 显式强制通道（"m"/"a"/"b"/"c"）；不可用时抛 ValueError

    Returns:
        {"ok": bool, "channel": str, "version": str|None, "ads_dir": str,
         "candidates": [...], "probed": {...}, "errors": [...]}
    """
    errors: list[str] = []
    resolved_dir: Path | None = None
    version: str | None = None

    if ads_dir is not None:
        resolved_dir = Path(ads_dir)
        if not resolved_dir.exists():
            errors.append(f"ADS 目录不存在: {resolved_dir}")
        else:
            version = _version_from_dir(resolved_dir)
    else:
        from rfauto.infra.config import load_settings

        cfg = str(load_settings().hpeesof_dir or "")
        if cfg and Path(cfg).exists():
            resolved_dir = Path(cfg)
            version = _version_from_dir(resolved_dir)
        else:
            errors.append("ADS 目录未配置或不存在（RFAUTO_HPEESOF_DIR）")

    if version is None:
        errors.append("无法从目录名解析 ADS 版本（如 ADS2027）")

    matrix_channels = _matrix_channels(version)
    probed = (
        probe_channel_availability(resolved_dir, version)
        if resolved_dir is not None and resolved_dir.exists()
        else {c: {"available": False, "reason": "ADS 目录不可用"} for c in _CHANNELS}
    )

    if prefer:
        if prefer not in _CHANNELS:
            return {"ok": False, "errors": [*errors, f"未知通道: {prefer}（可选 m/a/b/c）"]}
        candidates = [prefer]
    else:
        candidates = matrix_channels

    chosen: str | None = None
    degrade_reasons: list[str] = []
    for ch in candidates:
        info = probed.get(ch, {"available": False, "reason": "未探测"})
        if info.get("available"):
            chosen = ch
            break
        degrade_reasons.append(f"{ch}: {info.get('reason', '')}")

    if chosen is None:
        errors.append("候选通道全部不可用")
        for r in degrade_reasons:
            errors.append(f"  降级: {r}")
        return {
            "ok": False,
            "channel": None,
            "version": version,
            "ads_dir": str(resolved_dir) if resolved_dir else None,
            "candidates": candidates,
            "probed": probed,
            "errors": errors,
        }

    if prefer is None and chosen != candidates[0]:
        logger.info("ADS 通道降级: %s → %s", candidates[0], chosen)

    return {
        "ok": True,
        "channel": chosen,
        "version": version,
        "ads_dir": str(resolved_dir) if resolved_dir else None,
        "candidates": candidates,
        "probed": probed,
        "degrade_reasons": degrade_reasons,
        "errors": [],
    }
