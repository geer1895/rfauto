"""XC 差异报告锚树（设计版本语义 diff，layout_diff_service 的声明面对偶件）。

判据：diff 分类六态（numeric/added/removed/type_change/value_change/
嵌套递归）逐类手构回收；数值相对变化率恒等式；structural 判据
（added/removed/type_change 任一→structural）；identical 零变更；
文件入口 YAML/JSON 双支持 + 缺文件/非映射 error 信封。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service import design_diff_service as ds


class TestDiffKinds:
    def test_identical(self):
        out = ds.design_version_diff({"a": 1, "b": {"x": [1, 2]}},
                                     {"a": 1, "b": {"x": [1, 2]}})
        assert out["verdict"] == "identical"
        assert out["changes"] == []

    def test_numeric_change_with_rel(self):
        out = ds.design_version_diff({"w_mm": 40.0}, {"w_mm": 41.0})
        assert out["verdict"] == "changed"
        (c,) = out["changes"]
        assert c == {"path": "w_mm", "kind": "numeric", "a": 40.0, "b": 41.0,
                     "rel_change": 0.025}

    def test_added_removed_type_change_are_structural(self):
        out = ds.design_version_diff({"keep": 1, "old": 2, "t": 3},
                                     {"keep": 1, "new": 9, "t": "s"})
        assert out["verdict"] == "structural"
        kinds = {c["path"]: c["kind"] for c in out["changes"]}
        assert kinds == {"old": "removed", "new": "added", "t": "type_change"}

    def test_nested_and_list_length(self):
        a = {"sub": {"x": 1.0}, "arr": [1, 2]}
        b = {"sub": {"x": 2.0}, "arr": [1, 2, 3]}
        out = ds.design_version_diff(a, b)
        kinds = {c["path"]: c["kind"] for c in out["changes"]}
        assert kinds["sub.x"] == "numeric"
        assert kinds["arr"] == "value_change"
        assert any("列表长度" in str(c.get("note")) for c in out["changes"])

    def test_bool_is_not_numeric(self):
        out = ds.design_version_diff({"flag": True}, {"flag": 1})
        assert out["changes"][0]["kind"] == "type_change"

    def test_bad_input_error_envelope(self):
        out = ds.design_version_diff({"a": 1}, None)
        assert out["ok"] is False
        assert out["errors"]


class TestMarkdown:
    def test_render_lists_paths_and_rel(self):
        out = ds.design_version_diff({"w_mm": 40.0, "old": 1},
                                     {"w_mm": 44.0})
        text = ds.render_design_diff_markdown(out)
        assert "`w_mm`" in text and "+10%" in text
        assert "`old`" in text and "structural" in text

    def test_render_error_envelope(self):
        text = ds.render_design_diff_markdown({"ok": False, "errors": ["坏"]})
        assert "不可比" in text and "坏" in text


class TestFiles:
    def test_yaml_meta_pair(self, tmp_path):
        pa = tmp_path / "a.yaml"
        pb = tmp_path / "b.yaml"
        pa.write_text("template: patch\nnominal_params:\n  patch_w_mm: 50.0\n",
                      encoding="utf-8")
        pb.write_text("template: patch\nnominal_params:\n  patch_w_mm: 40.92\n",
                      encoding="utf-8")
        out = ds.design_version_diff_from_files(pa, pb)
        assert out["ok"] is True
        assert out["verdict"] == "changed"
        c = out["changes"][0]
        assert c["path"] == "nominal_params.patch_w_mm"
        assert c["b"] == pytest.approx(40.92)
        assert out["labels"] == [str(pa), str(pb)]

    def test_json_pair_and_missing_file(self, tmp_path):
        pa = tmp_path / "a.json"
        pa.write_text(json.dumps({"x": 1}), encoding="utf-8")
        pb = tmp_path / "b.json"
        pb.write_text(json.dumps({"x": 2}), encoding="utf-8")
        assert ds.design_version_diff_from_files(pa, pb)["verdict"] == "changed"
        out = ds.design_version_diff_from_files(pa, tmp_path / "nope.yaml")
        assert out["ok"] is False and "不存在" in out["errors"][0]

    def test_non_mapping_is_error(self, tmp_path):
        p = tmp_path / "list.yaml"
        p.write_text("- 1\n- 2\n", encoding="utf-8")
        out = ds.design_version_diff_from_files(p, p)
        assert out["ok"] is False
