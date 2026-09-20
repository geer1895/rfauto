"""B-30：模型/计算器/模板文档自动生成测试（覆盖/确定性/坏输入）。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def _read_tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*.md"))
    }


class TestCalculatorDocs:
    def test_all_calculators_covered(self, tmp_path):
        from rfauto.core.calculators import CALCULATOR_REGISTRY
        from rfauto.service.model_docs import CALCULATOR_DOC_PREFIX, generate_all_model_docs

        # 覆盖含实验态键（文档可见可审计，标签见 test_experimental_doc_has_label）
        names = CALCULATOR_REGISTRY.names(include_experimental=True)
        assert names, "计算器注册表不能为空（防空测）"
        results = generate_all_model_docs(tmp_path / "docs")
        for name in names:
            key = f"{CALCULATOR_DOC_PREFIX}{name}"
            assert key in results, f"缺计算器文档: {key}"
            assert (tmp_path / "docs" / f"{key}.md").exists()
        # 覆盖数 == 注册键数（含实验键，缺一即失败）
        covered = [k for k in results if k.startswith(CALCULATOR_DOC_PREFIX)]
        assert len(covered) == len(names)
        # 默认名单（排除实验键）是覆盖集的真子集
        assert set(CALCULATOR_REGISTRY.names()) < set(names)

    def test_experimental_doc_has_label(self):
        """实验键文档带实验标签；非实验键不带。"""
        from rfauto.service.model_docs import generate_calculator_docs

        exp_doc = generate_calculator_docs("patch_f0_symbolic_e13")
        assert "实验性: 是" in exp_doc
        assert "allow_experimental" in exp_doc
        plain_doc = generate_calculator_docs("microstrip_synthesis")
        assert "实验性: 否" in plain_doc

    def test_doc_contains_key_fields(self):
        from rfauto.core.calculators import CALCULATOR_REGISTRY
        from rfauto.service.model_docs import generate_calculator_docs

        spec = CALCULATOR_REGISTRY.get("microstrip_synthesis")
        doc = generate_calculator_docs("microstrip_synthesis")
        assert "microstrip_synthesis" in doc
        assert spec.description in doc
        for param_name, _ in spec.params:
            assert param_name in doc
        assert "元数据" in doc

    def test_unknown_calculator_rejected(self):
        from rfauto.service.model_docs import generate_calculator_docs

        with pytest.raises(KeyError):
            generate_calculator_docs("no_such_calculator")


class TestTemplateDocs:
    def test_all_templates_covered(self, tmp_path):
        from rfauto.adapters.openems_templates import TEMPLATE_META
        from rfauto.service.model_docs import TEMPLATE_DOC_PREFIX, generate_all_model_docs

        assert TEMPLATE_META, "模板元数据不能为空（防空测）"
        results = generate_all_model_docs(tmp_path / "docs")
        for name in TEMPLATE_META:
            key = f"{TEMPLATE_DOC_PREFIX}{name}"
            assert key in results
            assert (tmp_path / "docs" / f"{key}.md").exists()
        covered = [k for k in results if k.startswith(TEMPLATE_DOC_PREFIX)]
        assert len(covered) == len(TEMPLATE_META)

    def test_doc_contains_key_fields(self):
        from rfauto.adapters.openems_templates import TEMPLATE_META
        from rfauto.service.model_docs import generate_template_docs

        meta = TEMPLATE_META["wilkinson"]
        doc = generate_template_docs("wilkinson")
        assert "# 模板 wilkinson" in doc
        assert str(meta["f0_ghz"]) in doc
        assert str(meta["n_ports"]) in doc
        for param_name in meta["params"]:
            assert param_name in doc
        assert "70.7" in doc  # 语义列抽取自 param_semantics（只搬运声明）

    def test_unknown_template_rejected(self):
        from rfauto.service.model_docs import generate_template_docs

        with pytest.raises(KeyError):
            generate_template_docs("no_such_template")

    def test_bad_meta_explicit_error(self, tmp_path, monkeypatch):
        from rfauto.adapters import openems_templates
        from rfauto.service.model_docs import generate_all_model_docs, generate_template_docs

        meta = {k: dict(v) for k, v in openems_templates.TEMPLATE_META.items()}
        broken = dict(meta["wilkinson"])
        broken.pop("f0_ghz")
        meta["wilkinson"] = broken
        monkeypatch.setattr(openems_templates, "TEMPLATE_META", meta)
        with pytest.raises(ValueError):
            generate_template_docs("wilkinson")
        with pytest.raises(ValueError):
            generate_all_model_docs(tmp_path / "docs")


class TestDeterminismAndCoverage:
    def test_two_runs_byte_identical(self, tmp_path):
        from rfauto.service.model_docs import generate_all_model_docs

        first = generate_all_model_docs(tmp_path / "a")
        second = generate_all_model_docs(tmp_path / "b")
        assert set(first) == set(second)
        for key in first:
            assert first[key] == second[key], key
        assert _read_tree(tmp_path / "a") == _read_tree(tmp_path / "b")

    def test_coverage_counts_match_registries(self, tmp_path):
        from rfauto.adapters.openems_templates import TEMPLATE_META
        from rfauto.core.calculators import CALCULATOR_REGISTRY
        from rfauto.models.registry import list_models
        from rfauto.service.model_docs import (
            CALCULATOR_DOC_PREFIX,
            TEMPLATE_DOC_PREFIX,
            generate_all_model_docs,
        )

        results = generate_all_model_docs(tmp_path / "docs")
        models = list_models()
        assert set(models) <= set(results)
        # 计算器覆盖含实验态键；覆盖数 == 注册键数/模板数（缺一即失败）
        calc_names = CALCULATOR_REGISTRY.names(include_experimental=True)
        expected = len(models) + len(calc_names) + len(TEMPLATE_META)
        assert len(results) == expected
        calc_keys = [k for k in results if k.startswith(CALCULATOR_DOC_PREFIX)]
        tmpl_keys = [k for k in results if k.startswith(TEMPLATE_DOC_PREFIX)]
        assert len(calc_keys) == len(calc_names)
        assert len(tmpl_keys) == len(TEMPLATE_META)

    def test_output_stays_under_tmp_path(self, tmp_path):
        from rfauto.service.model_docs import generate_all_model_docs

        out = tmp_path / "out"
        results = generate_all_model_docs(out)
        files = sorted(p.relative_to(out) for p in out.rglob("*.md"))
        assert len(files) == len(results)  # 全部产物都落在给定目录
        # 默认 docs/models 未被创建（autouse chdir 把 CWD 钉在 tmp_path）
        assert not (tmp_path / "docs").exists()
