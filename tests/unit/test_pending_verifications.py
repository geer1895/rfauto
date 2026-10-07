"""docs/pending_verifications.yaml 结构卫生钉（review_ge8e R7-7 修复批 F1）。

钉两件事：
1. 禁重复键：旧账 15/21 项存在重复 ``blocks:`` 键（清洗时追加新键而非改旧
   键，YAML 后键胜出暂无实害但属结构性失真）——用拒绝重复键的 loader 装载，
   任何键重复当场红；
2. verified 项必无未清 blocks：登记簿使用说明第 2 条"verified 后同步解除
   blocks"（旧账 PV-001/PV-006/PV-016 三项 verified 而 blocks 未清）。

纯结构面断言，零内容/状态断言（状态演进属台账语义，不在单测钉死）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_PV_PATH = _REPO / "docs" / "pending_verifications.yaml"


class _NoDuplicateKeyLoader(yaml.SafeLoader):
    """pyyaml 缺省对重复键静默后键胜出——本 loader 遇重复键即抛
    yaml.constructor.ConstructorError（构造期拒绝，R7-7② 回归钉）。"""


def _no_dup_constructor(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            dup = key in mapping
        except TypeError:  # pragma: no cover - 不可哈希键本就不合法
            raise yaml.constructor.ConstructorError(
                None, None, "unhashable key in mapping",
                key_node.start_mark) from None
        if dup:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r} in mapping "
                f"（pending_verifications 禁重复键，R7-7）", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_NoDuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    lambda loader, node: _no_dup_constructor(loader, node))


@pytest.fixture(scope="module")
def doc() -> dict:
    return yaml.load(_PV_PATH.read_text(encoding="utf-8"),
                     Loader=_NoDuplicateKeyLoader)


def test_loads_without_duplicate_keys(doc: dict) -> None:
    # 装载本身即断言一：任何层级的重复键（含每个 item 映射内的 blocks）
    # 都会在构造期抛 ConstructorError 使本 fixture 红。
    assert isinstance(doc, dict)
    assert doc.get("schema") == "pending_verifications/v1"
    items = doc.get("items")
    assert isinstance(items, list) and items, "items 缺失或为空"


def test_item_ids_unique(doc: dict) -> None:
    ids = [it["id"] for it in doc["items"] if isinstance(it, dict)]
    assert len(ids) == len(set(ids)), "PV id 重号"


def test_verified_items_have_no_blocks(doc: dict) -> None:
    # R7-7①：verified = 阻断解除，blocks 必须为空/缺省（使用说明第 2 条）。
    offenders = [
        (it["id"], it["blocks"])
        for it in doc["items"]
        if isinstance(it, dict) and it.get("status") == "verified"
        and it.get("blocks")
    ]
    assert not offenders, (
        f"verified 项 blocks 未清（使用说明第 2 条违约）: {offenders}——"
        "修复：清空对应 blocks 并回填解除注记")
