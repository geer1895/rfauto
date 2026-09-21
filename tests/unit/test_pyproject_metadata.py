"""pyproject.toml 发布元数据钉（C20/0dd⑥：PEP 639 license 迁移）。

PEP 639 口径：
- ``[project].license`` 必须是 SPDX 表达式字符串（禁旧式 ``{ text = ... }`` 表）；
- ``license-files`` 列表声明许可文件；
- 废弃的 ``License ::`` classifier 禁止与 SPDX 并存（构建后端会报错/告警）。
SPDX 值必须跟随 LICENSE 文件文本（本仓 LICENSE=GPL-3.0 文本，SPDX 表达式
以其是否含 "or later" 措辞为准）。
"""

from __future__ import annotations

from pathlib import Path

import tomllib

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"
_LICENSE = _ROOT / "LICENSE"


def _load_project() -> dict:
    with open(_PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]


def test_license_is_spdx_string_not_table():
    """license 必须是 PEP 639 SPDX 字符串（旧式 { text = ... } 表即红）。"""
    license_field = _load_project()["license"]
    assert isinstance(license_field, str), (
        f"license 须为 SPDX 字符串，实际 {license_field!r}（旧式 table 未迁移）")
    assert license_field.startswith("GPL-3.0")


def test_license_files_declares_license():
    assert _load_project()["license-files"] == ["LICENSE"]
    assert _LICENSE.is_file()


def test_spdx_matches_license_text():
    """SPDX 值跟随 LICENSE 文件文本（迁移口径：文本与表达式一致）。"""
    head = _LICENSE.read_text(encoding="utf-8", errors="replace")[:200]
    spdx = _load_project()["license"]
    if spdx == "MIT":
        assert "MIT License" in head
    elif spdx.startswith("GPL-3.0"):
        assert "GNU GENERAL PUBLIC LICENSE" in head
        assert ("or later" in head) == (spdx == "GPL-3.0-or-later")


def test_no_deprecated_license_classifier():
    """PEP 639：license classifier 与 SPDX 表达式禁并存。"""
    bad = [c for c in _load_project().get("classifiers", [])
           if c.startswith("License ::")]
    assert bad == []
