"""rfauto —— HFSS ↔ ADS 自动化仿真调优框架。

版本单一来源：优先读安装元数据（pyproject.toml），未安装（源码直接
PYTHONPATH 运行）时回退硬编码。业务代码一律 `from rfauto import __version__`，
禁止散落硬编码版本串（审查发现 meta.json 里三处 "0.1.0" 各自为政）。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_FALLBACK_VERSION = "0.10.0"

try:
    __version__ = version("rfauto")
except PackageNotFoundError:  # 源码运行、未 pip install
    __version__ = _FALLBACK_VERSION
