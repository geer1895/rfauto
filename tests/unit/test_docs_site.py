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

aurora_m W1-4 再生器去重：3/4 两测的 build_all 产物改由 session 级共享
夹具 docs_site_fresh（tests/unit/_docs_regen_shared.py，pytest tmp 域内
单次构建+原子改名缓存）供给——断言面零变化（manifest 仍为 build_all
真实返回值），同一批跑里三消费文件（本文件+test_check_docs_drift+
test_kernel_cards）docs_site 只构建一次（A 侧实测 11 次）。
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

from tests.unit._docs_regen_shared import RegenBuild

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
# 机读 JSON 产物（build_docs_pages.build_rest_schema_page；漂移钉另见
# tests/unit/test_rest_e2e_smoke_script.py 的 live 枚举一致性口径）
SCHEMA_ASSETS: tuple[str, ...] = ("rest_schema.json",)
GENERATED_FILES: tuple[str, ...] = GENERATED_PAGES + STATIC_ASSETS + SCHEMA_ASSETS


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

def test_generator_pages_embed_live_counts(docs_site_fresh: RegenBuild) -> None:
    manifest = docs_site_fresh.manifest
    built = docs_site_fresh.directory
    assert manifest["cli"] == check_numbers.count_cli()
    assert manifest["mcp"] == check_numbers.count_mcp()
    assert manifest["calculators"] == check_numbers.count_calculators()
    assert manifest["templates"] == check_numbers.count_template_meta()
    assert manifest["anchors"] == check_numbers.count_anchors()
    assert manifest["tests"] == check_numbers.count_tests()[0]

    cli_md = (built / "reference" / "cli.md").read_text(encoding="utf-8")
    assert f"共 **{manifest['cli']}** 条" in cli_md
    mcp_md = (built / "reference" / "mcp.md").read_text(encoding="utf-8")
    assert f"共 **{manifest['mcp']}** 个" in mcp_md
    calc_md = (built / "reference" / "calculators.md").read_text(
        encoding="utf-8")
    assert f"实注册 **{manifest['calculators']}** 个" in calc_md
    tmpl_md = (built / "catalog" / "index.md").read_text(encoding="utf-8")
    assert f"共 **{manifest['templates']}** 个" in tmpl_md
    # 首页数字条内容与实测一致（strip 纯函数对纯读回，零硬编码数字）
    strip_fresh = build_docs_pages.numbers_strip(
        build_docs_pages.load_check_numbers())
    assert str(check_numbers.count_mcp()) in strip_fresh
    assert str(check_numbers.count_template_meta()) in strip_fresh


# ─── 4. 已提交 docs_site 保鲜（逐字节；红=需重跑生成器）──────────────────

def test_committed_docs_site_matches_regeneration(
        docs_site_fresh: RegenBuild) -> None:
    remedy = (
        "docs_site/ 落后于代码面或源文档——修复：在仓根重跑 "
        "`python scripts/build_docs_pages.py`，产物随本轮代码改动同笔提交"
        "（#97 文档与代码同 commit；#247 他轨推进计数后同样适用）")
    for rel in GENERATED_FILES:
        committed = _DOCS_SITE / rel
        assert committed.exists(), f"缺少已提交产物 docs_site/{rel}；{remedy}"
        fresh = (docs_site_fresh.directory / rel).read_bytes()
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


# ─── 6. 门 prebuild 消费口（aurora_m W1-3：跨段构建收敛）───────────────────

def test_regen_prebuilt_env_port_direct(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """_maybe_prebuilt 三态钉（白盒）：env 未设 → None（缺省行为不变红线）；
    env 在场+产物齐 → 直接消费；产物/manifest 缺 → 如实红（不静默回退自建
    ——静默回退会把"每门 ≤1 次"契约悄悄变 3 次）。"""
    from tests.unit import _docs_regen_shared as shared

    monkeypatch.delenv(shared.REGEN_FROM_ENV, raising=False)
    assert shared._maybe_prebuilt("docs_site") is None

    fake = tmp_path / "gate_regen"
    (fake / "docs_site").mkdir(parents=True)
    (fake / "docs_site.manifest.json").write_text('{"cli": 3}',
                                                  encoding="utf-8")
    monkeypatch.setenv(shared.REGEN_FROM_ENV, str(fake))
    pre = shared._maybe_prebuilt("docs_site")
    assert pre is not None
    assert pre.directory == fake / "docs_site"
    assert pre.manifest == {"cli": 3}

    monkeypatch.setenv(shared.REGEN_FROM_ENV, str(tmp_path / "absent"))
    with pytest.raises(RuntimeError, match="prebuild 契约"):
        shared._maybe_prebuilt("docs_site")


def test_docs_site_fixture_consumes_gate_prebuild(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """夹具实体接线钉：env 指向手工 prebuild 目录时获取单源直接返回它
    （零真实构建——假产物缺真实内容即证）。直呼夹具薄壳下的普通函数
    _docs_site_product（pytest 8 禁直呼夹具；且不经 session 缓存，判定
    与同会话他测顺序无关）。"""
    from tests.unit import _docs_regen_shared as shared

    fake = tmp_path / "gate_regen"
    (fake / "docs_site").mkdir(parents=True)
    (fake / "docs_site" / "marker.txt").write_text("prebuilt",
                                                   encoding="utf-8")
    (fake / "docs_site.manifest.json").write_text('{"fake": true}',
                                                  encoding="utf-8")
    monkeypatch.setenv(shared.REGEN_FROM_ENV, str(fake))
    built = shared._docs_site_product(tmp_path / "unused-basetemp")
    assert built.directory == fake / "docs_site"
    assert (built.directory / "marker.txt").read_text("utf-8") == "prebuilt"
    assert built.manifest == {"fake": True}
