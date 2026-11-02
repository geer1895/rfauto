"""docs/reference.md「配方 schema」节防漂移钉（aurora_n 旅程席 A，F-P2-1）。

文档节手写 + 双向钉（任务书允许形态）：节内顶层键表/ops 表/指标名表/
setup·export 键与单一事实源逐项比对——

- 顶层键表 ↔ ``service/recipe_validation.RECIPE_TOP_LEVEL_KEYS``（含必需标注）；
- ops 表 ↔ ``core/objectives.MetricOp``；
- 指标名表 ↔ ``core/objectives.OBJECTIVE_METRIC_NAMES``；
- 指标名清单本体 ↔ ``SpecEvaluator.compute_metrics`` 分支字面量（双向：
  集合里的名字必须真有分支；分支里的字面量必须已登记）；
- setup 键行 ↔ ``adapters/hfss_session.HFSS_SETUP_KNOWN_KEYS``（snake 子集）。

新增合法键/指标先落单源，再同步文档节——漏同步即本文件门红。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

_REF = Path(__file__).resolve().parents[2] / "docs" / "reference.md"

_SECTION_HEADER = "## 配方 schema"


def _section() -> str:
    text = _REF.read_text(encoding="utf-8")
    start = text.index(_SECTION_HEADER)
    rest = text[start + len(_SECTION_HEADER):]
    end = rest.index("\n## ")
    return rest[:end]


def _subsection(section: str, title: str) -> str:
    """取「### <title>」小节正文（到下一个小节头为止）。"""
    marker = f"### {title}"
    start = section.index(marker) + len(marker)
    rest = section[start:]
    end = rest.find("\n### ")
    return rest[:end if end >= 0 else None]


def _table_keys(text: str) -> list[str]:
    """表格行首列的反引号键（`| `key` | ...` 形态，按行序）。"""
    return re.findall(r"^\| `([^`]+)` \|", text, re.M)


# ─── 顶层键表 ↔ 白名单单源 ───────────────────────────────────────────────────


class TestTopLevelKeyTable:
    def test_keys_and_required_flags_match_single_source(self):
        from rfauto.service.recipe_validation import (
            RECIPE_TOP_LEVEL_KEYS,
            REQUIRED_RECIPE_KEYS,
        )

        rows = re.findall(
            r"^\| `([a-z_]+)` \| (必需|可选) \|", _subsection(_section(), "顶层键"),
            re.M)
        doc_keys = [k for k, _ in rows]
        assert doc_keys == list(RECIPE_TOP_LEVEL_KEYS), (doc_keys,
                                                        list(RECIPE_TOP_LEVEL_KEYS))
        for key, flag in rows:
            expect = "必需" if key in REQUIRED_RECIPE_KEYS else "可选"
            assert flag == expect, (key, flag, expect)

    def test_single_source_names_are_consumed_recipe_keys(self):
        """白名单每个键都该像配方键（下划线小写形态）——防手滑登记脏键。"""
        from rfauto.service.recipe_validation import RECIPE_TOP_LEVEL_KEYS

        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", k)
                   for k in RECIPE_TOP_LEVEL_KEYS)


# ─── ops 表 ↔ MetricOp ───────────────────────────────────────────────────────


class TestOpsTable:
    def test_ops_match_metric_op_enum(self):
        from rfauto.core.objectives import MetricOp

        ops = _table_keys(_subsection(_section(), "objectives 的 ops"))
        assert ops == [op.value for op in MetricOp]


# ─── 指标名表 ↔ OBJECTIVE_METRIC_NAMES ↔ compute_metrics（双向） ─────────────


class TestMetricTable:
    def test_doc_metrics_match_catalog(self):
        from rfauto.core.objectives import OBJECTIVE_METRIC_NAMES

        doc = _table_keys(_subsection(_section(), "指标名"))
        assert set(doc) == set(OBJECTIVE_METRIC_NAMES), (doc,
                                                         sorted(OBJECTIVE_METRIC_NAMES))
        assert len(doc) == len(set(doc)), "文档指标表有重复行"

    def test_catalog_bidirectional_pin_to_compute_metrics(self):
        """集合 ↔ compute_metrics 分支字面量双向钉（防单侧漂移）。"""
        from rfauto.core.objectives import (
            OBJECTIVE_METRIC_NAMES,
            SpecEvaluator,
        )

        src = inspect.getsource(SpecEvaluator.compute_metrics)
        # 正向：集合里每个名字在分支消费面有出处
        for name in OBJECTIVE_METRIC_NAMES:
            assert name in src, f"指标 {name} 不在 compute_metrics 源"
        # 反向：分支字面量（obj.metric == "X" / obj.metric in ("X", ...)）必须已登记
        branched = set(re.findall(r'obj\.metric\s*==\s*["\']([^"\']+)["\']', src))
        for tuple_block in re.findall(r'obj\.metric\s*in\s*\(([^)]*)\)', src):
            branched |= set(re.findall(r'["\']([^"\']+)["\']', tuple_block))
        unregistered = {m for m in branched if m not in OBJECTIVE_METRIC_NAMES}
        assert not unregistered, f"compute_metrics 新分支未登记指标目录: {unregistered}"


# ─── setup / export 键行 ↔ HFSS 白名单 ───────────────────────────────────────


class TestSetupExportTable:
    def test_setup_row_covers_hfss_whitelist_snake_keys(self):
        from rfauto.adapters.hfss_session import HFSS_SETUP_KNOWN_KEYS

        row = _subsection(_section(), "setup / export 键")
        snake = {k for k in HFSS_SETUP_KNOWN_KEYS
                 if re.fullmatch(r"[a-z][a-z0-9_]*", k)}
        backticked = set(re.findall(r"`([a-z_0-9]+)`", row))
        missing = snake - backticked
        assert not missing, f"setup 键行缺 HFSS 白名单键: {missing}"

    def test_setup_row_keeps_template_layer_keys(self):
        """solver/radiation_box（模板层消费）必须在行内（历史配方防误伤口径）。"""
        row = _subsection(_section(), "setup / export 键")
        assert "`solver`" in row and "`radiation_box`" in row


# ── 守真：文档节与单源模块的指针真实性（引用路径/符号存在） ────────────────────


@pytest.mark.parametrize("symbol_path", [
    ("rfauto.service.recipe_validation", "RECIPE_TOP_LEVEL_KEYS"),
    ("rfauto.core.objectives", "OBJECTIVE_METRIC_NAMES"),
    ("rfauto.core.objectives", "MetricOp"),
    ("rfauto.adapters.hfss_session", "HFSS_SETUP_KNOWN_KEYS"),
])
def test_doc_pointed_symbols_exist(symbol_path):
    """文档节自称的单源符号必须真实存在（指针不烂，SNRO 家法）。"""
    import importlib

    mod_name, attr = symbol_path
    mod = importlib.import_module(mod_name)
    assert hasattr(mod, attr), f"{mod_name}.{attr} 不存在——文档指针悬空"
