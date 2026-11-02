"""build_impact_map 候选生成回归钉（aurora_n 零覆盖治理席，2026-10-30）。

W0-2 影响面映射把 src/rfauto/service/sdk.py 误判为 zero-coverage（direct=[]），
真因两处叠加：
1. ``_collect_candidates`` 对绝对 ImportFrom 把 base 置成 node.module 再拼
   ``base.node.module.alias``——候选全翻倍成 ``rfauto.service.rfauto.service.sdk``
   垃圾点路径，``_resolve_under`` 按文件存在性过滤后颗粒无收；
2. grep 面 token "sdk"（3 字符）被短 stem 过滤弃用（map stats
   grep_tokens_skipped_short_stem）。

而 tests/unit/test_rest_api.py:21 ``from rfauto.service import rest_api, sdk``
是 30+ 处直连消费（coverage 实测 sdk.py 84%）。本文件钉住修复后的候选
语义：绝对/相对 ImportFrom 与 Import 三形态的候选均须能落到真实文件键。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from build_impact_map import _collect_candidates, _resolve_under

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_absolute_from_import_yields_real_submodule_candidate():
    """回归主钉：`from rfauto.service import rest_api, sdk` 必须产出
    rfauto.service.sdk（修复前=base 翻倍垃圾 rfauto.service.rfauto.service.sdk）。"""
    tree = ast.parse("from rfauto.service import rest_api, sdk\n")
    cands = _collect_candidates(tree, "tests.unit.test_rest_api", False)
    assert "rfauto.service" in cands
    assert "rfauto.service.rest_api" in cands
    assert "rfauto.service.sdk" in cands
    # 修复前形态：点路径翻倍，任何真实文件都解析不回
    assert not any(c.count("rfauto.service.rfauto") for c in cands)


def test_absolute_from_import_symbol_alias_is_harmless_candidate():
    """符号别名（非子模块）也生成 `module.alias` 候选——由 _resolve_under
    按文件存在性过滤，不误入键集（宁多勿漏语义）。"""
    tree = ast.parse(
        "from rfauto.service.dataset_service import DATASET_SCHEMA\n")
    cands = _collect_candidates(tree, "tests.unit.test_x", False)
    assert "rfauto.service.dataset_service" in cands
    assert "rfauto.service.dataset_service.DATASET_SCHEMA" in cands


def test_relative_from_imports_semantics_unchanged():
    """相对 import 三形态：level=1 同级、level=1 带模块、level=2 上溯。"""
    tree = ast.parse(
        "from . import sibling\n"
        "from .mod import thing\n"
        "from ..other import item\n"
    )
    cands = _collect_candidates(tree, "rfauto.sub.pkg", False)
    assert "rfauto.sub.sibling" in cands
    assert "rfauto.sub.mod" in cands
    assert "rfauto.sub.mod.thing" in cands
    assert "rfauto.other" in cands
    assert "rfauto.other.item" in cands


def test_plain_import_unchanged():
    tree = ast.parse("import rfauto.service.sdk\nimport yaml\n")
    cands = _collect_candidates(tree, "tests.unit.test_x", False)
    assert "rfauto.service.sdk" in cands
    assert "yaml" in cands


def test_sdk_candidate_resolves_to_real_file_key():
    """端到端：候选点路径经 _resolve_under 落到真实仓文件键
    src/rfauto/service/sdk.py（映射 direct 面修复的落点证据）。"""
    keys: set[str] = set()
    _resolve_under(
        _REPO_ROOT / "src" / "rfauto", "rfauto", "rfauto.service.sdk", keys)
    assert "src/rfauto/service/sdk.py" in keys
    # 沿途祖先包 __init__ 同被 import 语义执行，一并入键
    assert "src/rfauto/service/__init__.py" in keys


def test_rest_api_import_line_is_direct_edge_source():
    """用 test_rest_api.py 真实文件头复现 direct 边：sdk 在候选中。"""
    src = (_REPO_ROOT / "tests" / "unit" / "test_rest_api.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    cands = _collect_candidates(tree, "tests.unit.test_rest_api", False)
    assert "rfauto.service.sdk" in cands
    assert "rfauto.service.rest_api" in cands
