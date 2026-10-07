"""PR-10 文档站锚树测试（mkdocs-material 站点；#89 / #97 / #247）。

钉四件事：
1. mkdocs.yml 是合法 YAML 且 docs_dir/site_dir 契约成立；
2. nav 引用的文件全部真实存在（#89：文档串引用的配置必须真实存在）；
3. 生成器同源：重生成产物页内总数与 scripts/check_numbers.py 实测逐位
   互证——全 live 对 live，**零硬编码数字**（#247：他轨并发推进计数时
   全量字面钉必互相打红，故任何 EXPECTED=N 字面量都不得出现在本文件）；
4. 已提交 docs_site 保鲜：与本次重生成逐字节一致——合流后代码计数或
   既有文档源变动时此红 = "站点未再生成"的明确信号（修复动作见断言
   消息），不是环境故障。
构建 smoke：mkdocs 可用时真跑 mkdocs build（零 error + 关键页 HTML 产出）。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_MKDOCS_YML = _REPO / "mkdocs.yml"
_DOCS_SITE = _REPO / "docs_site"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    # py3.12 dataclasses 解析 string 注解需查 sys.modules[cls.__module__]——
    # 不先注册则收集期 AttributeError（build_docs_pages 含 @dataclass CliNode）
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


check_numbers = _load_module(
    "_pr10_test_check_numbers", _REPO / "scripts" / "check_numbers.py")
build_docs_pages = _load_module(
    "_pr10_test_build_docs_pages", _REPO / "scripts" / "build_docs_pages.py")

# 生成/同步产物相对 docs_site 的全清单（保鲜比对面）
GENERATED_PAGES: tuple[str, ...] = (
    "reference/cli.md",
    "reference/mcp.md",
    "reference/calculators.md",
    "reference/capabilities.md",
    "catalog/index.md",
    "tutorials/getting-started.md",
    "explanation/layered-architecture.md",
)
# 静态资产（mkdocs 原样拷贝、不进 nav——nav 收录的是 gallery.md 壳页）
STATIC_ASSETS: tuple[str, ...] = ("gallery/index.html",)
GENERATED_FILES: tuple[str, ...] = GENERATED_PAGES + STATIC_ASSETS


# ─── 1/2. mkdocs.yml 合法性 + nav 引用文件全存在 ──────────────────────────

def test_mkdocs_yml_valid_yaml_and_contracts() -> None:
    data = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data.get("site_name") == "rfauto"
    assert data.get("docs_dir") == "docs_site"
    assert (_REPO / str(data["docs_dir"])).is_dir()
    assert data.get("theme", {}).get("name") == "material"
    nav = data.get("nav")
    assert isinstance(nav, list) and nav, "nav 必须非空列表"


def _iter_nav_paths(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _iter_nav_paths(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nav_paths(item)


def test_nav_referenced_files_all_exist() -> None:
    data = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    paths = list(_iter_nav_paths(data.get("nav")))
    assert len(paths) >= 8, f"nav 条目数异常偏少: {len(paths)}"
    missing = [p for p in paths if not (_DOCS_SITE / p).exists()]
    assert not missing, f"nav 引用了不存在的文件（#89）: {missing}"
    # 生成页必须在 nav 内（站点不收录孤儿页；静态资产不要求入 nav）
    nav_set = set(paths)
    orphans = [f for f in GENERATED_PAGES if f not in nav_set]
    assert not orphans, f"生成页未入 nav: {orphans}"


# ─── 3. 生成器同源（全 live 互证，零硬编码数字）───────────────────────────

def test_generator_pages_embed_live_counts(tmp_path: Path) -> None:
    manifest = build_docs_pages.build_all(tmp_path)
    assert manifest["cli"] == check_numbers.count_cli()
    assert manifest["mcp"] == check_numbers.count_mcp()
    assert manifest["calculators"] == check_numbers.count_calculators()
    assert manifest["templates"] == check_numbers.count_template_meta()
    assert manifest["anchors"] == check_numbers.count_anchors()
    assert manifest["tests"] == check_numbers.count_tests()[0]

    cli_md = (tmp_path / "reference" / "cli.md").read_text(encoding="utf-8")
    assert f"共 **{manifest['cli']}** 条" in cli_md
    mcp_md = (tmp_path / "reference" / "mcp.md").read_text(encoding="utf-8")
    assert f"共 **{manifest['mcp']}** 个" in mcp_md
    calc_md = (tmp_path / "reference" / "calculators.md").read_text(
        encoding="utf-8")
    assert f"实注册 **{manifest['calculators']}** 个" in calc_md
    tmpl_md = (tmp_path / "catalog" / "index.md").read_text(encoding="utf-8")
    assert f"共 **{manifest['templates']}** 个" in tmpl_md
    # 首页数字条内容与实测一致（strip 纯函数对纯读回，零硬编码数字）
    strip_fresh = build_docs_pages.numbers_strip(
        build_docs_pages.load_check_numbers())
    assert str(check_numbers.count_mcp()) in strip_fresh
    assert str(check_numbers.count_template_meta()) in strip_fresh


# ─── 4. 已提交 docs_site 保鲜（逐字节；红=需重跑生成器）──────────────────

def test_committed_docs_site_matches_regeneration(tmp_path: Path) -> None:
    build_docs_pages.build_all(tmp_path)
    remedy = (
        "docs_site/ 落后于代码面或源文档——修复：在仓根重跑 "
        "`python scripts/build_docs_pages.py`，产物随本轮代码改动同笔提交"
        "（#97 文档与代码同 commit；#247 他轨推进计数后同样适用）")
    for rel in GENERATED_FILES:
        committed = _DOCS_SITE / rel
        assert committed.exists(), f"缺少已提交产物 docs_site/{rel}；{remedy}"
        fresh = (tmp_path / rel).read_bytes()
        assert committed.read_bytes() == fresh, f"docs_site/{rel} 内容漂移；{remedy}"
    # 首页数字条单独锚（index.md 手写部分不参与逐字节比对）
    committed_strip = build_docs_pages.read_index_strip(_DOCS_SITE)
    fresh_strip = build_docs_pages.numbers_strip(
        build_docs_pages.load_check_numbers())
    assert committed_strip.strip() == fresh_strip.strip(), (
        f"首页数字条漂移；{remedy}")


# ─── 5. 构建 smoke（mkdocs 可用时）────────────────────────────────────────

def test_mkdocs_build_smoke(tmp_path: Path) -> None:
    pytest.importorskip("mkdocs")
    site_out = tmp_path / "site"
    proc = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--site-dir", str(site_out)],
        cwd=_REPO, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, (
        f"mkdocs build 失败\nstdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}")
    assert (site_out / "index.html").exists()
    assert (site_out / "reference" / "cli" / "index.html").exists()
    assert (site_out / "catalog" / "index.html").exists()
    assert (site_out / "gallery" / "index.html").exists()
