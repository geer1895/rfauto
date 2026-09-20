"""WP0.1 依赖体检脚本单测：纯分类逻辑钉行为，无 venv/网络 IO。"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from check_env_deps import (
    BOOTSTRAP_ALLOWLIST,
    check_extras_coverage,
    classify,
    load_declared,
    managed_closure,
    scan_src_imports,
)


def _pyproject(deps: list, extras: dict | None = None) -> dict:
    project: dict = {"dependencies": deps}
    if extras is not None:
        project["optional-dependencies"] = extras
    return {"project": project}


def test_load_declared_merges_core_and_extras():
    declared = load_declared(_pyproject(
        ["numpy>=1.24", "scikit_rf>=2.0,<3"],
        {"dev": ["pytest>=7.4"], "ui": ["starlette>=0.35"]}))
    assert set(declared) == {"numpy", "scikit-rf", "pytest", "starlette"}
    assert len(declared["scikit-rf"]) == 1


def test_classify_missing_and_conflict():
    declared = load_declared(_pyproject(
        ["numpy>=2.0"], {"mcp": ["fastmcp>=3.0"]}))
    report = classify(declared, {"numpy": "1.24.0"}, {})
    assert report["missing"] == ["fastmcp"]
    assert any(c.startswith("numpy==1.24.0") for c in report["conflict"])
    # numpy 在声明闭包内，不算 unmanaged
    assert report["unmanaged"] == []


def test_classify_version_satisfied_no_conflict():
    declared = load_declared(_pyproject(["numpy>=1.24"]))
    report = classify(declared, {"numpy": "2.5.3"}, {})
    assert report["missing"] == []
    assert report["conflict"] == []


def test_classify_unmanaged_with_allowlist_exempt():
    declared = load_declared(_pyproject(["numpy"]))
    versions = {"numpy": "2.0.0", "leftpad": "9.9",
                "pip": "25.0", "rfauto": "0.10.0"}
    report = classify(declared, versions, {})
    assert report["unmanaged"] == ["leftpad"]
    assert "pip" in BOOTSTRAP_ALLOWLIST and "rfauto" in BOOTSTRAP_ALLOWLIST


def test_closure_marks_transitive_deps_managed():
    declared = load_declared(_pyproject(["uvicorn>=0.27"]))
    versions = {"uvicorn": "0.52.4", "click": "8.1.0", "h11": "0.14.0"}
    requires_map = {"uvicorn": ["click>=7.0", "h11>=0.8"]}
    closure = managed_closure(declared, versions, requires_map)
    assert {"uvicorn", "click", "h11"} <= closure
    report = classify(declared, versions, requires_map)
    assert report["unmanaged"] == []


def test_closure_handles_extras_markers_and_bad_require():
    declared = load_declared(_pyproject(["uvicorn"]))
    versions = {"uvicorn": "0.52.4", "watchfiles": "1.0"}
    # extras marker 串与坏串都不能让闭包崩溃（marker 过取策略）
    requires_map = {"uvicorn": ['watchfiles; extra == "watch"', "not-a-require!!"]}
    report = classify(declared, versions, requires_map)
    assert report["missing"] == [] and report["conflict"] == []
    assert "watchfiles" not in report["unmanaged"]


def test_check_extras_coverage_flags_undeclared_extra():
    used = {"starlette", "uvicorn", "numpy"}
    gaps = check_extras_coverage(used, declared_extras={"mcp", "hfss"})
    assert gaps == [
        "starlette 需要 extras [ui]，pyproject 未声明",
        "uvicorn 需要 extras [ui]，pyproject 未声明",
    ]
    assert check_extras_coverage(used, declared_extras={"ui"}) == []
    # 非可选模块（不在映射表内）永不产生缺口
    assert check_extras_coverage({"numpy", "optuna"}, declared_extras=set()) == []


def test_scan_src_imports_collects_top_level(tmp_path):
    (tmp_path / "a.py").write_text(
        "import starlette.applications\nfrom uvicorn.config import Config\n",
        encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text(
        "from . import sibling\nimport numpy as np\n", encoding="utf-8")
    tops = scan_src_imports(tmp_path)
    assert {"starlette", "uvicorn", "numpy"} <= tops
    assert "sibling" not in tops  # 相对导入不计（level>0）


def test_bad_syntax_file_skipped(tmp_path):
    (tmp_path / "broken.py").write_text("def (折断", encoding="utf-8")
    (tmp_path / "ok.py").write_text("import h5py\n", encoding="utf-8")
    assert scan_src_imports(tmp_path) == {"h5py"}
