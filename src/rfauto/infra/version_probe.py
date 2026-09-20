"""EDA 版本探测（AEDT/ADS 共用基础设施）。

职责：
- 枚举本机 AEDT 安装（ANSYSEM_ROOTxxx 环境变量 + 注册表），解析版本号
- 解析 ADS 安装版本（目录名 ADS<yyyy>）
- 从 knowledge/compat_matrix.yaml 读取版本支持等级（verified / best_effort / unsupported）

背景：原先 aedt_version 由"路径含 v231"字符串启发式推导，
脆弱且只认两个硬编码版本（经验 10：EDA 默认值不可信）。本模块把探测
收敛到 infra 层，service/optimization 只调用 resolve 函数。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

# 仓库根目录下的兼容矩阵（源码布局；wheel 安装不支持，与 diagnosis.rules.yaml 一致）
_COMPAT_MATRIX_PATH = Path(__file__).parent.parent.parent.parent / "knowledge" / "compat_matrix.yaml"

_ANSYSEM_ENV_RE = re.compile(r"^ANSYSEM_ROOT(\d+)$")
_AEDT_DIR_RE = re.compile(r"^[vV]?(\d{3,4})$")
# ADS 安装目录名：4 位年份（ADS2027）或 2 位短年（ADS27），
# 短年统一归一到 20xx。
_ADS_DIR_RE = re.compile(r"ADS(\d{4}|\d{2})$", re.IGNORECASE)

_DEFAULT_AEDT_VERSION = "2024.1"  # pyaedt 未指定版本时的默认值


def build_to_aedt_version(build_num: int) -> str:
    """ANSYS 内部版本号 → 年.发布 版本串。

    规则：231 → 2023 R1 → "2023.1"；251 → 2025 R1；262 → 2026 R2。
    """
    year = 2000 + build_num // 10
    release = build_num % 10
    return f"{year}.{release}"


def detect_aedt_versions() -> list[dict[str, Any]]:
    """枚举本机 AEDT 安装。

    来源（按可信度）：
    1. ANSYSEM_ROOT<build> 环境变量（AEDT 安装时写入，指向 <版本目录>\\Win64）
    2. Windows 注册表 HKLM\\SOFTWARE\\ANSYS, Inc.（best-effort，非 Windows/无权限时跳过）

    Returns:
        [{"version_id": "v231", "path": Path, "aedt_version": "2023.1",
          "source": "env"}...] 按版本新→旧排序，重复路径去重。
    """
    installs: dict[str, dict[str, Any]] = {}

    for name, value in os.environ.items():
        m = _ANSYSEM_ENV_RE.match(name)
        if not m:
            continue
        build = int(m.group(1))
        root = Path(value)
        # ANSYSEM_ROOT231 = <版本目录>\Win64 → 版本目录取上一层
        # ANSYSEM_ROOT261 = <版本目录>\AnsysEM → 版本目录取上一层
        version_dir = root.parent if root.name.lower() in ("win64", "ansysem") else root
        version_id = f"v{build}"
        installs[str(version_dir)] = {
            "version_id": version_id,
            "path": version_dir,
            "aedt_version": build_to_aedt_version(build),
            "source": f"env:{name}",
        }

    # 注册表兜底（环境变量缺失时仍可能发现安装）
    if not installs:
        installs.update(_detect_from_registry())

    result = sorted(installs.values(), key=lambda e: e["aedt_version"], reverse=True)
    # 只保留真实存在的路径
    return [e for e in result if e["path"].exists()]


def _detect_from_registry() -> dict[str, dict[str, Any]]:
    """Windows 注册表探测（best-effort，任何失败静默返回空）。"""
    result: dict[str, dict[str, Any]] = {}
    try:  # pragma: no cover - 需要 Windows 真机
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ANSYS, Inc.") as key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    i += 1
                except OSError:
                    break
                m = re.match(r"^[vV]?(\d{3,4})(?:\.(\d))?$", subkey_name)
                if not m:
                    continue
                build = int(m.group(1))
                try:
                    with winreg.OpenKey(key, subkey_name) as sk:
                        install_dir, _ = winreg.QueryValueEx(sk, "InstallDir")
                except OSError:
                    continue
                p = Path(str(install_dir))
                version_dir = p.parent if p.name.lower() == "win64" else p
                result[str(version_dir)] = {
                    "version_id": f"v{build}",
                    "path": version_dir,
                    "aedt_version": build_to_aedt_version(build),
                    "source": "registry",
                }
    except Exception:
        return result
    return result


def resolve_aedt_install(explicit_path: str | Path | None = None) -> dict[str, Any] | None:
    """解析实际使用的 AEDT 安装（显式路径优先，否则自动探测最高版本）。

    优先级：
    1. explicit_path（RFAUTO_AEDT_PATH）：存在即用；版本号优先从目录名
       （vNNN）解析，解析不出时按路径前缀匹配已探测安装，再不行回退默认值
    2. 自动探测取最高版本（无环境变量也能发现本机 AEDT）

    Returns:
        {"path": Path, "aedt_version": str, "source": str} 或 None（未找到）
    """
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            m = _AEDT_DIR_RE.match(p.name)
            if m:
                return {
                    "path": p,
                    "aedt_version": build_to_aedt_version(int(m.group(1))),
                    "source": "explicit",
                }
            # 目录名不含 vNNN：尝试用探测结果做路径前缀匹配
            for inst in detect_aedt_versions():
                try:
                    if p.resolve() == inst["path"].resolve() or p.resolve() in inst["path"].resolve().parents:
                        return dict(inst, source="explicit+probe")
                except OSError:
                    continue
            return {"path": p, "aedt_version": _DEFAULT_AEDT_VERSION, "source": "explicit-default"}
        return None

    detected = detect_aedt_versions()
    if detected:
        best = detected[0]
        return {"path": best["path"], "aedt_version": best["aedt_version"], "source": "auto-probe"}
    return None


def detect_ads_version(ads_dir: str | Path | None = None) -> str | None:
    """从 ADS 安装目录名解析版本（...\\ADS2027 或 ...\\ADS27 → "2027"）。解析不出返回 None。"""
    if ads_dir is None:
        from rfauto.infra.config import load_settings

        ads_dir = load_settings().hpeesof_dir or None
        if ads_dir is None:
            return None
    m = _ADS_DIR_RE.search(str(Path(ads_dir).name))
    if not m:
        return None
    digits = m.group(1)
    return digits if len(digits) == 4 else f"20{digits}"


# ---------------------------------------------------------------------------
# 兼容矩阵
# ---------------------------------------------------------------------------

def load_compat_matrix() -> dict[str, Any]:
    """读取 knowledge/compat_matrix.yaml；缺失/损坏时返回空矩阵（不抛异常）。"""
    if not _COMPAT_MATRIX_PATH.exists():
        return {}
    try:
        with open(_COMPAT_MATRIX_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_LEVELS = ("verified", "best_effort", "unsupported")


def compat_level(tool: str, version: str) -> str:
    """查版本支持等级：tool ∈ {"aedt", "ads"}。

    匹配优先级：精确版本 → default_level → "unsupported"（矩阵缺失时按
    best_effort 处理，即"能用但不背书"——保守但不阻塞）。
    """
    matrix = load_compat_matrix()
    tool_cfg = matrix.get(tool, {})
    versions = tool_cfg.get("versions", {}) if isinstance(tool_cfg, dict) else {}
    entry = versions.get(version)
    if entry is not None:
        if isinstance(entry, dict):
            return str(entry.get("level", tool_cfg.get("default_level", "best_effort")))
        return str(entry)
    return str(tool_cfg.get("default_level", "best_effort"))
