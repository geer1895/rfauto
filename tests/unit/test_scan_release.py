"""scan_release 自检（发布工具在 release/，公开仓缺省缺席→诚实 skip）。

内部发布席工具（release/scan_release.py 不随公开仓分发）；本文件保留
EP-2 覆盖宇宙占位（coverage universe 枚举含本模块），公开环境整文件
skip 不红（存在性判定见下）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SCAN_RELEASE = Path(__file__).resolve().parents[3] / "release" / "scan_release.py"

pytestmark = pytest.mark.skipif(
    not _SCAN_RELEASE.is_file(),
    reason="release/scan_release.py 为发布席内部工具，公开仓不随仓分发",
)

if _SCAN_RELEASE.is_file():  # 内部环境才加载真模块
    import importlib.util

    _spec = importlib.util.spec_from_file_location("scan_release", _SCAN_RELEASE)
    _mod = importlib.util.module_from_spec(_spec)
    import sys

    sys.modules["scan_release"] = _mod
    _spec.loader.exec_module(_mod)


def test_scanner_module_loads_when_present():
    if not _SCAN_RELEASE.is_file():
        pytest.skip("公开仓无 scan_release.py")
    import sys

    mod = sys.modules.get("scan_release")
    assert mod is not None and hasattr(mod, "scan_tree")
