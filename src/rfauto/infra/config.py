"""rfauto settings loader — 3-tier priority (env > YAML > defaults)."""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_SETTINGS: dict[str, Any] = {
    "aedt_path": "",
    "hpeesof_dir": "",
    "grpc_port": 50051,
    "default_unit": "mm",
    "max_concurrent_solves": 4,
    "timeout_default_s": 3600,
    "workspace_dir": ".",
    "cache_mode": "readwrite",
    # 嵌套节（实验计算器开关）：YAML 侧为
    # calculators.allow_experimental；env 侧 RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL
    "calculators": {"allow_experimental": False},
    # 嵌套节：注册表数据库路径。YAML 侧 db.path；
    # env 侧 RFAUTO_REGISTRY_DB 由 infra/db.default_registry_db_path 直接读
    # （优先级高于本节，同三层口径：env > YAML > 默认 runs/registry.sqlite）。
    "db": {"path": ""},
}

_ENV_PREFIX = "RFAUTO_"
_ENV_MAP = {
    "aedt_path": "RFAUTO_AEDT_PATH",
    "hpeesof_dir": "RFAUTO_HPEESOF_DIR",
    "grpc_port": "RFAUTO_GRPC_PORT",
    "default_unit": "RFAUTO_DEFAULT_UNIT",
    "max_concurrent_solves": "RFAUTO_MAX_CONCURRENT",
    "timeout_default_s": "RFAUTO_TIMEOUT_S",
    "workspace_dir": "RFAUTO_WORKSPACE_DIR",
    "cache_mode": "RFAUTO_CACHE",
    # 嵌套节用点路径作键；取值时展开进 merged 的对应子 dict
    "calculators.allow_experimental": "RFAUTO_CALCULATORS_ALLOW_EXPERIMENTAL",
}

_TRUTHY_ENV = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV = frozenset({"0", "false", "no", "off"})


def _parse_bool_env(raw: str) -> bool | None:
    """环境变量布尔解析（1/true/yes/on、0/false/no/off，大小写不敏感）；
    无法识别返回 None（保持默认——坏值不阻断启动，安全侧默认关闭）。"""
    value = raw.strip().lower()
    if value in _TRUTHY_ENV:
        return True
    if value in _FALSY_ENV:
        return False
    return None

_DEFAULT_YAML = Path("configs/settings.yaml")


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------
class CalculatorsSettings(BaseModel):
    """计算器行为设置（实验态开关）。"""

    allow_experimental: bool = Field(
        False,
        description="Allow running experimental (induced) calculators",
    )


class DbSettings(BaseModel):
    """注册表数据库设置（db 默认路径与 settings 合流）。"""

    path: str = Field(
        "",
        description=(
            "Registry SQLite path; empty = runs/registry.sqlite. "
            "Env RFAUTO_REGISTRY_DB takes precedence (read by "
            "infra.db.default_registry_db_path)."
        ),
    )


class Settings(BaseModel):
    """Application settings with 3-tier priority resolution."""

    aedt_path: str = Field("", description="Path to AEDT installation")
    hpeesof_dir: str = Field("", description="Path to ADS (HPEESOF_DIR)")
    grpc_port: int = Field(50051, description="gRPC server port")
    default_unit: str = Field("mm", description="Default geometry unit")
    max_concurrent_solves: int = Field(4, description="Max parallel solves")
    timeout_default_s: int = Field(3600, description="Default solve timeout (s)")
    workspace_dir: str = Field(".", description="Workspace root directory")
    cache_mode: str = Field("readwrite", description="Cache mode: readwrite | readonly | off")
    calculators: CalculatorsSettings = Field(
        default_factory=CalculatorsSettings,
        description="Calculator behaviour (experimental switch)",
    )
    db: DbSettings = Field(
        default_factory=DbSettings,
        description="Registry database settings (db.path)",
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_settings(yaml_path: str | Path = _DEFAULT_YAML) -> Settings:
    """Load settings with 3-tier priority.

    Priority (highest → lowest):
    1. Environment variables (``RFAUTO_*``)
    2. YAML config file (``configs/settings.yaml``)，同目录
       ``settings.local.yaml``（gitignore 的本机路径覆盖）存在时后加载覆盖
    3. Code defaults
    """
    # Tier 3: code defaults
    merged = dict(_DEFAULT_SETTINGS)

    # Tier 2: YAML file（本机覆盖文件 local 在其后加载即优先生效）
    for yaml_p in (Path(yaml_path), Path(yaml_path).with_name("settings.local.yaml")):
        if yaml_p.exists():
            yaml_cfg = OmegaConf.load(str(yaml_p))
            yaml_dict = OmegaConf.to_container(yaml_cfg, resolve=True)
            merged.update({k: v for k, v in yaml_dict.items() if k in _DEFAULT_SETTINGS})

    # Tier 1: environment variables override everything
    for field_name, env_var in _ENV_MAP.items():
        env_val = os.environ.get(env_var)
        if env_val is None:
            continue
        if "." in field_name:
            # 嵌套节（如 calculators.allow_experimental）：按节展开合并；
            # 坏布尔值保持默认（安全侧关闭），不阻断启动。
            section, leaf = field_name.split(".", 1)
            base = _DEFAULT_SETTINGS.get(section)
            if not isinstance(base, dict):
                continue
            parsed = _parse_bool_env(env_val)
            if parsed is not None:
                node = dict(merged.get(section) or base)
                node[leaf] = parsed
                merged[section] = node
            continue
        # Coerce ints
        if isinstance(_DEFAULT_SETTINGS.get(field_name), int) and not isinstance(
            _DEFAULT_SETTINGS.get(field_name), bool
        ):
            with contextlib.suppress(ValueError):
                env_val = int(env_val)  # type: ignore[assignment]
        merged[field_name] = env_val

    return Settings(**merged)


# ---------------------------------------------------------------------------
# Doctor check
# ---------------------------------------------------------------------------

def doctor_check(settings: Settings | None = None) -> dict[str, Any]:
    """Verify AEDT / ADS paths and return a status dict."""
    if settings is None:
        settings = load_settings()

    result: dict[str, Any] = {"aedt": {}, "ads": {}, "ok": True}

    # AEDT
    aedt = Path(settings.aedt_path) if settings.aedt_path else None
    if aedt and aedt.exists():
        result["aedt"]["path"] = str(aedt)
        result["aedt"]["exists"] = True
        # 目录名 vNNN → 版本串（解析不出则缺省，doctor 侧会再探测）
        m = re.match(r"^[vV]?(\d{3,4})$", aedt.name)
        if m:
            year = 2000 + int(m.group(1)) // 10
            result["aedt"]["version"] = f"{year}.{int(m.group(1)) % 10}"
    elif aedt:
        result["aedt"]["path"] = str(aedt)
        result["aedt"]["exists"] = False
        result["ok"] = False
    else:
        result["aedt"]["path"] = None
        result["aedt"]["exists"] = False
        result["aedt"]["note"] = "not configured"

    # ADS
    ads = Path(settings.hpeesof_dir) if settings.hpeesof_dir else None
    if ads and ads.exists():
        result["ads"]["path"] = str(ads)
        result["ads"]["exists"] = True
    elif ads:
        result["ads"]["path"] = str(ads)
        result["ads"]["exists"] = False
        result["ok"] = False
    else:
        result["ads"]["path"] = None
        result["ads"]["exists"] = False
        result["ads"]["note"] = "not configured"

    return result
