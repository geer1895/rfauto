"""QW-4 模板画廊静态页导出器单测（scripts/gallery_export.py）。

口径（全部确定性、离线、零真机）：
- 生成冒烟：全量渲染含抽样板名 + 汇总行总数==len(TEMPLATE_META)；
- 确定性：同输入两次生成逐字节一致（无 --stamp）；
- escape：注入含 "<>" 的假字段路径 → 输出已转义（防注入面）；
- --template 过滤单卡 + 未知名 exit；--out 自定义路径生效；
- 锚覆盖口径：真实 anchors.yaml 经 load_anchors 装载，通配 "*" 与
  专属 template_family 两种匹配实测；
- 文档链接：docs/models/<t>.md 存在（tmp fixture）才生成相对链接。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import gallery_export as ge

# ─── 生成冒烟 ───────────────────────────────────────────────────────────────

def test_smoke_contains_sampled_templates_and_total(tmp_path):
    from rfauto.adapters.openems_templates import TEMPLATE_META
    out = tmp_path / "gallery.html"
    ge.write_gallery(out)
    text = out.read_text(encoding="utf-8")
    # 抽 3 个实测键名（含 2026-09 新成员 ring_resonator/pyramid_horn）
    for name in ("wilkinson", "ring_resonator", "pyramid_horn"):
        assert name in text, f"缺模板卡 {name}"
    # 汇总行总数 == 注册表实测长度（非硬编码 55）
    assert f"模板总数 <b>{len(TEMPLATE_META)}</b>" in text
    # 单文件自包含：零外链；内联脚本恰一个（PR-5 X1 渐进增强筛选，
    # 原"零 JS"钉随交互化 v1 更新——仍禁外链/CDN，离线可开不变）
    assert "http://" not in text and "https://" not in text
    assert "<script src=" not in text
    assert text.count("<script") == 1


def test_progressive_enhancement_toolbar_and_data_attrs(tmp_path):
    """PR-5 X1 交互化钉：data-* 数据源 + 隐藏工具栏 + 族/锚覆盖 chips。"""
    out = tmp_path / "gallery.html"
    ge.write_gallery(out)
    text = out.read_text(encoding="utf-8")
    # 零 JS 现态守卫：工具栏 hidden 起步（禁 JS 时不可见、全部卡片可见）
    assert '<div id="gf-toolbar" hidden>' in text
    # 每卡 data-* 全套（族/锚覆盖/搜索文本）
    assert 'data-tpl="wilkinson"' in text
    assert ('id="tpl-wilkinson" data-tpl="wilkinson" '
            'data-family="coupler"') in text
    assert 'data-coverage="covered"' in text
    # 族 chips（计数由导出器单源渲染，键序字母序）
    assert 'data-fam="all" aria-pressed="true"' in text
    assert 'data-fam="antenna" aria-pressed="false"' in text
    assert "天线与阵列" in text and "滤波器与双工器" in text
    # 锚覆盖徽标过滤 chips（有锚/无锚 + 计数）
    assert 'data-anc="covered"' in text and 'data-anc="none"' in text
    assert ">有锚 " in text and ">无锚 " in text
    # a11y：搜索框 label、结果 status live region、焦点可见样式
    assert '<label for="gf-q">搜索：</label>' in text
    assert 'id="gf-status" role="status"' in text
    assert "focus-visible" in text


def test_family_chip_counts_sum_to_cards(tmp_path):
    from rfauto.service.gallery_service import TEMPLATE_FAMILIES

    out = tmp_path / "gallery.html"
    ge.write_gallery(out)
    text = out.read_text(encoding="utf-8")
    # 全量渲染下 "全部 N" == 注册表实测（chips 计数与卡数同源）
    assert f'全部 {len(TEMPLATE_FAMILIES)}<' in text
    # 抽样族卡 data-family 与单一事实源一致
    from rfauto.service.gallery_service import template_family
    for name in ("patch", "hairpin", "siw"):
        assert f'data-tpl="{name}" data-family="{template_family(name)}"' \
            in text


def test_deterministic_two_runs_byte_identical(tmp_path):
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    ge.write_gallery(a)
    ge.write_gallery(b)
    assert a.read_bytes() == b.read_bytes()


# ─── escape（假字段路径注入）─────────────────────────────────────────────────

_FAKE_TEMPLATES = {
    "tpl_x": {
        "f0_ghz": 1.0, "n_ports": 2, "extraction": "S11", "max_time_ns": 1.0,
        "params": ["<b>w_mm</b>"],
        "topology": "<script>alert(1)</script>",
        "param_semantics": "<i>sem</i>",
        "mesh_note": "note",
    },
}
_FAKE_NOMINAL = {"tpl_x": {"<k>": 0.5, "lst": ["<a>", 1]}}


def test_escape_injected_angle_brackets(tmp_path):
    cards = ge.collect_cards(templates=_FAKE_TEMPLATES, nominal=_FAKE_NOMINAL,
                             anchor_records=[], repo_root=tmp_path)
    text = ge.render_html(cards, total_in_registry=1,
                          out_dir=tmp_path, n_anchors=0)
    # PR-5 X1 起页面含一个合法内联 <script>（渐进增强筛选），注入钉收紧到
    # "注入内容不进执行面"：裸 <script>alert(1) 不得出现，卡面为转义形态。
    assert "<script>alert(1)" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;b&gt;w_mm&lt;/b&gt;" in text  # 参数键名 chips 亦转义
    assert "&lt;i&gt;sem&lt;/i&gt;" in text
    assert "&lt;a&gt;" in text  # nominal 列表值（JSON 渲染）亦转义
    assert "锚覆盖 0（无覆盖）" in text  # 空锚集如实标注
    assert text.count("<script") == 1  # 注入不会制造第二个脚本块


# ─── --template 过滤与未知名 ─────────────────────────────────────────────────

def test_template_filter_single_card(tmp_path):
    out = tmp_path / "one.html"
    ge.write_gallery(out, template_filter="wilkinson")
    text = out.read_text(encoding="utf-8")
    assert "wilkinson" in text
    assert "pyramid_horn" not in text
    assert "本页显示 1" in text


def test_template_filter_unknown_name_exits(tmp_path):
    with pytest.raises(SystemExit, match="not_in_registry"):
        ge.write_gallery(tmp_path / "x.html", template_filter="not_in_registry")


def test_out_custom_path_effective(tmp_path):
    out = tmp_path / "sub" / "dir" / "g.html"
    got = ge.write_gallery(out)
    assert got == out.absolute()
    assert out.is_file() and out.stat().st_size > 0


# ─── 锚覆盖口径（真实 anchors.yaml，通配+专属双实测）────────────────────────

def test_anchor_coverage_wildcard_and_specific():
    from rfauto.infra.anchors_store import load_anchors
    records = load_anchors().records
    assert len(records) > 0
    patch_ids = ge.match_anchor_ids("patch", records)
    # 通配锚 cps.gamma_er.fdref-v1 覆盖全部模板 + patch 专属两锚
    assert "cps.gamma_er.fdref-v1" in patch_ids
    assert "patch.f_dip_l.openems-v1" in patch_ids
    assert "patch.f_dip_l.hfss-v1" in patch_ids
    wilkinson_ids = ge.match_anchor_ids("wilkinson", records)
    # 通配 + wilkinson 专属锚（anchor-register 批 ANCHORS 6→12 后覆盖面扩展；
    # T5 批 kj_even_domain 通配域盒锚 +1；T14 批 mmt 双锚（inductive_post_b/
    # resonant_window_fres）亦 wildcard 通配族覆盖 → 17 锚态）
    assert wilkinson_ids == [
        "coupled_microstrip.kj_even_domain.lit-v1",
        "cps.gamma_er.fdref-v1",
        "mmt.inductive_post_b.hfss-v1",
        "mmt.resonant_window_fres.hfss-v1",
        "wilkinson.f_match.openems-hfss-v1",
    ]
    cards = ge.collect_cards(templates={"wilkinson":
                                        {"f0_ghz": 2.5, "params": []}},
                             anchor_records=records)
    assert cards[0]["anchor_specific_ids"] == ["wilkinson.f_match.openems-hfss-v1"]


# ─── 文档链接（docs/models/<t>.md 存在才链，tmp fixture）────────────────────

def test_doclink_generated_only_when_doc_exists(tmp_path):
    templates = {"tpl_doc": {"f0_ghz": 1.0, "params": []},
                 "tpl_nolink": {"f0_ghz": 1.0, "params": []}}
    doc = tmp_path / "docs" / "models" / "tpl_doc.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# tpl_doc\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cards = ge.collect_cards(templates=templates, nominal={},
                             anchor_records=[], repo_root=tmp_path)
    text = ge.render_html(cards, total_in_registry=2,
                          out_dir=out_dir, n_anchors=0)
    assert 'href="../docs/models/tpl_doc.md"' in text  # 相对 out_dir 的链接
    assert "docs/models/tpl_doc.md" in text
    assert "tpl_nolink" in text  # 无文档模板照常出卡
    assert "tpl_nolink.md" not in text  # 但不生成链接


# ─── meta.yaml 交叉校验钉（画廊数据源 == docs/templates/<t>/meta.yaml）──────

def test_gallery_sources_match_template_meta_yaml():
    """QW-4 增量钉：TEMPLATE_META/TEMPLATE_NOMINAL 与 docs 树 meta.yaml
    全量逐键一致（数据源单一事实；新增模板漏 meta.yaml 当场红）。"""
    import yaml

    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

    repo = Path(__file__).resolve().parents[2]
    assert len(TEMPLATE_META) == len(TEMPLATE_NOMINAL)
    for name in sorted(TEMPLATE_META):
        meta_path = repo / "docs" / "templates" / name / "meta.yaml"
        assert meta_path.is_file(), f"模板 {name} 缺 docs/templates/<t>/meta.yaml"
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        assert isinstance(meta, dict), f"{name} meta.yaml 非映射"        # 名义参数逐键一致（键序无关；meta.yaml 未声明按缺失 None 对照）
        assert meta.get("nominal_params") == TEMPLATE_NOMINAL.get(name), \
            f"{name} nominal_params 与 TEMPLATE_NOMINAL 漂移"
        # 画廊卡渲染的关键字段与 meta.yaml 同源
        card_meta = TEMPLATE_META[name]
        assert card_meta.get("f0_ghz") == meta.get("f0_ghz"), \
            f"{name} f0_ghz 与 meta.yaml 漂移"
        assert card_meta.get("n_ports") == meta.get("n_ports"), \
            f"{name} n_ports 与 meta.yaml 漂移"


def test_gallery_renders_meta_yaml_nominal_values(tmp_path):
    """抽样板：HTML 卡内名义参数表值 == meta.yaml 原文值（端到端一致）。"""

    from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

    name = "wilkinson"
    repo = Path(__file__).resolve().parents[2]
    meta_path = repo / "docs" / "templates" / name / "meta.yaml"
    assert meta_path.is_file(), "wilkinson 缺 meta.yaml（画廊数据源前置）"
    out = tmp_path / "g.html"
    ge.write_gallery(out, template_filter=name)
    text = out.read_text(encoding="utf-8")
    for key, value in (TEMPLATE_NOMINAL[name] or {}).items():
        rendered = ge._fmt(value)
        assert f"<th>{key}</th>" in text, f"{name} 卡缺名义参数键 {key}"
        assert f"<td>{rendered}</td>" in text, \
            f"{name} 卡名义参数 {key} 渲染值与 meta.yaml 不一致"
    assert len(TEMPLATE_META) >= 1  # 注册表非空守卫（消费面）


# ─── 已提交画廊保鲜钉（R7-1 陈旧回归：build_docs_pages 只原样拷贝该资产，
#     mtime 刷新掩盖内容陈旧——2026-09-29 渲染的 57 模板/6 锚旧页被拷进
#     docs_site 直到 review_ge8e 才发现。重渲染 == 已提交字节，漂移=红。）──

def test_committed_gallery_matches_regeneration(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    committed = repo / "docs" / "gallery" / "index.html"
    assert committed.is_file(), "docs/gallery/index.html 缺失"
    fresh = ge.write_gallery(tmp_path / "gallery_fresh.html")
    assert committed.read_bytes() == fresh.read_bytes(), (
        "docs/gallery/index.html 落后于 TEMPLATE_META/锚注册表现状（R7-1 "
        "陈旧回归）——修复：仓根重跑 `python scripts/gallery_export.py "
        "--out docs/gallery/index.html` 再 `python scripts/"
        "build_docs_pages.py`，产物随本轮代码改动同笔提交（#97）")


def test_committed_gallery_contains_all_template_keys_and_anchors():
    # 结构双钉：源画廊页必须含 TEMPLATE_META 全部键名卡节 + 锚数与
    # anchors.yaml 实况一致（防"页在数字旧"的二次陈旧，review_ge8e R7-1）。
    from rfauto.adapters.openems_templates import TEMPLATE_META
    from rfauto.infra.anchors_store import load_anchors

    repo = Path(__file__).resolve().parents[2]
    text = (repo / "docs" / "gallery" / "index.html").read_text(
        encoding="utf-8")
    n_anchors = len(load_anchors().records)
    for name in TEMPLATE_META:
        assert f'id="tpl-{name}"' in text, \
            f"画廊源页缺模板卡 {name}（陈旧，重跑 gallery_export.py）"
    assert f"锚注册表共 {n_anchors} 条" in text, (
        f"画廊源页锚数与 anchors.yaml 实况 {n_anchors} 漂移（陈旧，"
        "重跑 gallery_export.py）")
    assert f"模板总数 <b>{len(TEMPLATE_META)}</b>" in text
