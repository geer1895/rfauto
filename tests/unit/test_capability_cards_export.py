"""QW-5 模板能力卡导出器单测（scripts/capability_cards_export.py）。

口径（全确定性、离线、零真机；数据源可注入）：
- 生成冒烟：全模板 N 页 MD（==len(TEMPLATE_META)，#97 不钉字面）+
  index.html，抽样板关键节在场；
- 判据面：锚覆盖真实 anchors.yaml；健康门 G11 文案 + 模板作用域门
  （#274：patch 族报效率窗、非 patch 族如实"不判"）；
- 坑账链：playbook 通配规则命中（fdtd_truncation_artifact 全模板适用）+
  专属 scope 过滤；playbook 缺文件/坏结构 → 空列表如实；
- meta.yaml 主源 + TEMPLATE_META 回退（pick 语义）；
- B3-2 引擎精度卡节：真实仲裁锚（wilkinson constant）+ 四 kind 分支渲染
  （替身注入：constant/pointer/formula/curve、engine_pair=None）+ 空覆盖
  如实；
- B3-2 敏感性排序节：统一消费源 resolve_sensitivity 三态（review_ge8e F1
  处置② W8 桥接收口）——computed>teaching>None 优先级、登记表幅值分主源
  （provenance=computed+数据指针）、meta.yaml teaching 名次兜底（出处标注
  teaching）+ 双缺如实回退（挂接契约路径在卡面）+ 注入条目按 R9
  commitment_order 排序渲染 + 登记表装载缺/坏如实空 + 坏分数拒收 + 坏
  computed 如实降级 + teaching 坏块（名次不连续/缺 basis/bool order）拒收；
  W6 面不回归钉（teaching 卡/62 张回退卡敏感性节逐字节不变）+ computed
  上卡面 provenance 行钉；
- 确定性：两次生成逐字节一致；escape 注入；
- --template 过滤 + 未知名 exit。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import capability_cards_export as cce


def test_smoke_all_cards_and_index(tmp_path):
    from rfauto.adapters.openems_templates import TEMPLATE_META

    out = cce.write_cards(tmp_path / "cards")
    pages = sorted(p for p in out.glob("*.md"))
    assert len(pages) == len(TEMPLATE_META)
    assert (out / "index.html").is_file()
    idx = (out / "index.html").read_text(encoding="utf-8")
    for name in ("wilkinson", "ring_resonator", "pyramid_horn"):
        assert name in idx
    wil = (out / "wilkinson.md").read_text(encoding="utf-8")
    for section in ("## 适用场景", "## 名义参数", "## 敏感性排序（R9 先承诺）",
                    "## 判据", "## 引擎精度卡（跨引擎仲裁锚）", "## 已知边界"):
        assert section in wil, section


def test_card_sections_sampled_content():
    card = cce.collect_card("wilkinson")
    assert card["f0_ghz"] == pytest.approx(2.5)
    assert card["nominal_params"]["arm_len_mm"] == pytest.approx(18.1)
    assert card["meta_yaml_rel"] == "docs/templates/wilkinson/meta.yaml"
    md = cce.render_card_md(card)
    assert "arm_len_mm | 18.1" in md.replace("| ", "").replace(" | ", " | ") \
        or "| arm_len_mm | 18.1 |" in md
    # 坑账链：playbook 通配规则必命中 fdtd_truncation_artifact
    rule_ids = {m["rule_id"] for m in card["failure_modes"]}
    assert "fdtd_truncation_artifact" in rule_ids
    assert "#262" in {p for m in card["failure_modes"]
                       for p in m["pit_refs"]} or \
        any("#262" in m["pit_refs"] for m in card["failure_modes"])


def test_playbook_matching_scope_filter():
    rules = [
        {"id": "wild", "root_cause_family": "r1",
         "applicable_templates": ["*"], "pit_refs": ["#1"], "notes": ""},
        {"id": "specific", "root_cause_family": "r2",
         "applicable_templates": ["patch"], "pit_refs": [], "notes": "n"},
    ]
    assert [m["rule_id"] for m in cce.match_playbook_rules("patch", rules)] \
        == ["wild", "specific"]  # 按 playbook 文件序（输入序），不重排
    assert [m["rule_id"] for m in cce.match_playbook_rules("mline", rules)] \
        == ["wild"]


def test_playbook_missing_or_broken_file_honest(tmp_path):
    assert cce.load_playbook_rules(tmp_path / "nope.yaml") == []
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules: {not: a list}\n", encoding="utf-8")
    assert cce.load_playbook_rules(bad) == []


def test_real_playbook_loads_and_wildcard_rules_covered():
    rules = cce.load_playbook_rules()
    assert rules, "knowledge/diagnostics/playbook.yaml 应可读"
    wild = cce.match_playbook_rules("any_template_not_listed", rules)
    assert wild, "通配规则（applicable_templates=[*]）应覆盖任意模板"


def test_gate_notes_template_scope():
    patch_notes = cce._template_gate_notes("patch")
    assert any("效率窗门" in n for n in patch_notes)
    other = cce._template_gate_notes("wilkinson")
    assert any("如实不判" in n for n in other)


def test_meta_yaml_primary_template_meta_fallback():
    # meta.yaml 缺 mesh_note 的模板（如 patch）回退 TEMPLATE_META
    from rfauto.adapters.openems_templates import TEMPLATE_META
    card = cce.collect_card("patch")
    assert card["mesh_note"] == TEMPLATE_META["patch"]["mesh_note"]
    # 注入式：meta_yaml 主源优先
    card2 = cce.collect_card(
        "patch", meta_yaml={"f0_ghz": 9.9}, template_meta={"f0_ghz": 1.0})
    assert card2["f0_ghz"] == pytest.approx(9.9)
    # 双缺如实 None
    card3 = cce.collect_card("patch", meta_yaml={}, template_meta={})
    assert card3["topology"] is None


def test_deterministic_two_runs_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    cce.write_cards(a, template_filter="wilkinson")
    cce.write_cards(b, template_filter="wilkinson")
    assert (a / "wilkinson.md").read_bytes() == \
        (b / "wilkinson.md").read_bytes()
    assert (a / "index.html").read_bytes() == \
        (b / "index.html").read_bytes()


def test_escape_injected_fields(tmp_path):
    card = cce.collect_card(
        "tpl_<x>",
        meta_yaml={"f0_ghz": 1.0, "n_ports": 1, "params": ["<b>w</b>"],
                   "topology": "<script>alert(1)</script>",
                   "nominal_params": {"<k>": 0.5}},
        template_meta={}, anchor_records=[], playbook_rules=[])
    md = cce.render_card_md(card)
    # Markdown 面不做 HTML 转义（注入内容原样来自输入，非执行面）
    assert "tpl_<x>" in md
    # 索引 HTML 面：全插值必须 escape（模板名注入必须被转义）。
    # PR-5 X1 起页面含一个合法内联 <script>（渐进增强筛选），故注入钉
    # 收紧到"注入内容不被原样执行面"：裸 <script>alert(1) 不得出现，
    # data-search 属性内为转义形态。
    idx = cce.render_index_html([card])
    assert "<script>alert(1)" not in idx
    assert "tpl_&lt;x&gt;" in idx
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in idx
    assert idx.count("<script") == 1


def test_index_interactive_toolbar_and_data_attrs(tmp_path):
    """PR-5 X1 交互化钉：行 data-* 数据源 + 隐藏工具栏 + 族/锚覆盖 chips。"""
    from rfauto.service.gallery_service import template_family

    out = cce.write_cards(tmp_path / "cards", template_filter="wilkinson")
    idx = (out / "index.html").read_text(encoding="utf-8")
    # 零 JS 现态守卫：工具栏 hidden 起步（禁 JS 时不可见、全部行可见）
    assert '<div id="gf-toolbar" hidden>' in idx
    # 行 data-* 全套（族键与单一事实源一致；锚覆盖徽标状态）
    assert (f'<tr data-tpl="wilkinson" '
            f'data-family="{template_family("wilkinson")}" '
            f'data-anchors="5" data-coverage="covered"') in idx
    # 搜索文本含卡名与族标签（别名语义=卡内拓扑文本，不臆造独立别名字段）
    assert '功分/耦合/移相/巴伦' in idx
    # 族 chips + 锚覆盖徽标过滤 chips（计数由导出器单源渲染）
    assert 'data-fam="all" aria-pressed="true">全部 1<' in idx
    assert 'data-anc="covered"' in idx and 'data-anc="none"' in idx
    # a11y：label/status live region/focus-visible（沿 PR-1 钉）
    assert '<label for="gf-q">搜索：</label>' in idx
    assert 'id="gf-status" role="status"' in idx
    assert "focus-visible" in idx
    # 零外链 + 内联脚本恰一个（与 QW-4 画廊页共用实现）
    assert "http://" not in idx and "https://" not in idx
    assert idx.count("<script") == 1


def test_template_filter_and_unknown_exit(tmp_path):
    out = cce.write_cards(tmp_path / "one", template_filter="patch")
    assert sorted(p.name for p in out.glob("*.md")) == ["patch.md"]
    with pytest.raises(SystemExit, match="not_in_registry"):
        cce.write_cards(tmp_path / "x", template_filter="not_in_registry")


def test_index_counts_match_cards(tmp_path):
    out = cce.write_cards(tmp_path / "cards", template_filter="wilkinson")
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert "共 1 张能力卡" in idx
    assert "有锚覆盖 1 张" in idx  # 通配锚必覆盖
    assert "有引擎精度卡锚 1 张" in idx  # B3-2：精度卡列（卡级计数）
    assert "<th>精度锚</th>" in idx


# ── B3-2 引擎精度卡节（跨引擎仲裁锚）─────────────────────────────────────

def _fake_anchor(**kw):
    """轻量锚记录替身（pick_precision_anchor 全 getattr 容错）。"""
    from types import SimpleNamespace
    base: dict = dict(
        anchor_id="t.x.openems-hfss-v1", kind="constant", status="active",
        template_family=["t"],
        engine_pair={"calibrated": "openems", "referee": "hfss"},
        quantity={"name": "q", "unit": "percent"}, value=1.25,
        expr=None, variables=None, points=None, axis=None,
        uncertainty=None, provenance={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_precision_section_real_wilkinson_constant():
    card = cce.collect_card("wilkinson")
    pa = {a["anchor_id"]: a for a in card["precision_anchors"]}
    a = pa["wilkinson.f_match.openems-hfss-v1"]
    assert a["kind"] == "constant" and a["status"] == "active"
    assert a["engine_pair"] == {"calibrated": "openems", "referee": "hfss"}
    assert a["value"] == pytest.approx(1.132503)
    assert a["verdict_state"] == "AGREE_OPENEMS"
    assert a["arbitration_runs"] == ["runs/hfss_window_b2a/wilkinson"]
    md = cce.render_card_md(card)
    assert "## 引擎精度卡（跨引擎仲裁锚）" in md
    assert "`wilkinson.f_match.openems-hfss-v1`" in md
    assert "引擎对 openems（hfss 仲裁）" in md
    assert "verdict AGREE_OPENEMS" in md
    assert "证据：runs/hfss_window_b2a/wilkinson" in md


def test_precision_kind_variants_render():
    recs = [
        _fake_anchor(anchor_id="a.constant.v1",
                     uncertainty={"value": 0.3, "kind": "relative"}),
        _fake_anchor(anchor_id="b.pointer.v1", kind="pointer", value=None,
                     quantity={"name": "q2", "metric": "f_ghz",
                               "value_unit": "GHz",
                               "values": {"openems": 3.2, "hfss": 2.99}}),
        _fake_anchor(anchor_id="c.formula.v1", kind="formula", value=None,
                     engine_pair=None, expr="1 + 0.9*er**-0.6",
                     variables=["er"], quantity={"name": "q3"}),
        _fake_anchor(anchor_id="d.curve.v1", kind="curve", value=None,
                     points=[{"x": 1, "y": 2}, {"x": 3, "y": 4}],
                     axis={"param": "g_mm"}, quantity={"name": "q4"}),
    ]
    card = cce.collect_card("t", meta_yaml={}, template_meta={},
                            anchor_records=recs, playbook_rules=[],
                            sensitivity_entry={})
    kinds = {a["anchor_id"]: a["kind"] for a in card["precision_anchors"]}
    assert kinds == {"a.constant.v1": "constant", "b.pointer.v1": "pointer",
                     "c.formula.v1": "formula", "d.curve.v1": "curve"}
    md = cce.render_card_md(card)
    assert "引擎对 openems（hfss 仲裁）" in md
    assert "q = 1.25 percent；±0.3（relative）" in md
    # pointer 双值并列（键序确定性），禁平均 #122 注记在卡面
    assert "双值 hfss=2.99 / openems=3.2 GHz（不取平均，#122）" in md
    assert "expr = 1 + 0.9*er**-0.6（变量：er）" in md
    assert "闭式/文献锚（无引擎对）" in md
    assert "曲线 2 点（横轴 g_mm）" in md


def test_precision_empty_honest():
    card = cce.collect_card("t", meta_yaml={}, template_meta={},
                            anchor_records=[], playbook_rules=[],
                            sensitivity_entry={})
    md = cce.render_card_md(card)
    assert "暂无覆盖锚，如实标注" in md
    assert "knowledge/anchors.yaml" in md  # 数据源注记在场


# ── B3-2 敏感性排序节（R9 先承诺）────────────────────────────────────────

def test_sensitivity_teaching_fallback_applies(monkeypatch):
    """F1 处置②：登记表缺条目时回退 meta.yaml teaching（出处=teaching）。"""
    monkeypatch.setattr(cce, "load_sensitivity_rankings",
                        lambda path=None: {})
    card = cce.collect_card("wilkinson")
    sens = card["sensitivity"]
    assert sens is not None
    assert sens["source"] == "teaching"
    assert [(r["rank"], r["param"]) for r in sens["ranking"]] == \
        [(1, "arm_len_mm"), (2, "er"), (3, "series_w_mm"),
         (4, "shunt_w_mm")]
    md = cce.render_card_md(card)
    assert "出处=teaching" in md
    assert "| 名次 | 参数 | 依据 |" in md
    assert "| 1 | arm_len_mm |" in md
    assert "幅值分数待" in md  # 幅值面如实待数据管线，不冒充


def test_sensitivity_registry_source_wins_over_teaching():
    """登记表幅值条目在场时优先于 teaching 兜底（三态①：computed>teaching）。"""
    entry = {"method": "sobol",
             "ranking": [{"param": "z_mm", "score": 1.0}]}
    card = cce.collect_card("wilkinson", sensitivity_entry=entry)
    sens = card["sensitivity"]
    assert sens is not None
    # W8 桥接：计算数据面标注 provenance=computed + 数据指针（不冒充 teaching）
    assert sens["source"] == "computed"
    assert sens["provenance"]["registry"] == cce.SENSITIVITY_REGISTRY_REL
    assert [r["param"] for r in sens["ranking"]] == ["z_mm"]


def test_sensitivity_absent_honest(monkeypatch):
    monkeypatch.setattr(cce, "load_sensitivity_rankings",
                        lambda path=None: {})
    # 双缺（登记表无 + meta.yaml 无 teaching 块）→ 如实 None
    card = cce.collect_card("t", meta_yaml={}, template_meta={})
    assert card["sensitivity"] is None
    md = cce.render_card_md(card)
    assert "暂无已落档敏感度排序" in md
    assert "knowledge/sensitivity_rankings.yaml" in md
    assert cce.SENSITIVITY_DESIGN_NOTE_REL in md


def test_sensitivity_present_ranked_r9_order():
    entry = {"method": "sobol", "n_samples": 512, "seed": 42,
             "source_run": "runs/example",
             "ranking": [{"param": "b_mm", "score": 0.81},
                         {"param": "a_mm", "score": 0.81},
                         {"param": "c_mm", "score": 0.1}]}
    card = cce.collect_card("wilkinson", sensitivity_entry=entry)
    ranked = card["sensitivity"]["ranking"]
    # R9 commitment_order 家法：高敏感先钉死，平局按参数名升序
    assert [(r["rank"], r["param"], r["score"]) for r in ranked] == \
        [(1, "a_mm", 0.81), (2, "b_mm", 0.81), (3, "c_mm", 0.1)]
    md = cce.render_card_md(card)
    assert "| 1 | a_mm | 0.81 |" in md
    assert "方法 sobol ｜ n=512 ｜ seed=42 ｜ 证据：runs/example" in md
    assert "commitment_order" in md


def test_load_sensitivity_rankings_missing_and_broken(tmp_path):
    assert cce.load_sensitivity_rankings(tmp_path / "nope.yaml") == {}
    bad = tmp_path / "bad.yaml"
    bad.write_text("templates: {not: a list}\n", encoding="utf-8")
    assert cce.load_sensitivity_rankings(bad) == {}
    good = tmp_path / "good.yaml"
    good.write_text(
        "schema: sensitivity_rankings/v1\n"
        "templates:\n"
        "  wilkinson:\n"
        "    method: sobol\n"
        "    ranking:\n"
        "      - {param: arm_len_mm, score: 0.81}\n",
        encoding="utf-8")
    data = cce.load_sensitivity_rankings(good)
    assert set(data) == {"wilkinson"}
    assert data["wilkinson"]["method"] == "sobol"


def test_normalize_sensitivity_entry_rejects_bad_scores():
    assert cce.normalize_sensitivity_entry(None) is None
    assert cce.normalize_sensitivity_entry({}) is None
    assert cce.normalize_sensitivity_entry({"ranking": []}) is None
    out = cce.normalize_sensitivity_entry({"ranking": [
        {"param": "ok", "score": 0.5},
        {"param": "bool_score", "score": True},
        {"param": "str_score", "score": "0.9"},
        {"param": "neg", "score": -0.1},
        {"param": "inf", "score": float("inf")},
        {"param": "", "score": 0.5},
        {"param": "no_score"},
        "not_a_dict",
    ]})
    assert out is not None
    assert [r["param"] for r in out["ranking"]] == ["ok"]
    assert "method" not in out  # 缺省键不透传 None 值


def test_normalize_teaching_sensitivity_rejects_bad_blocks():
    """teaching 兜底源校验（teaching_service 同口径；导出面 best-effort None）。"""
    assert cce.normalize_teaching_sensitivity(None) is None
    assert cce.normalize_teaching_sensitivity({}) is None
    assert cce.normalize_teaching_sensitivity({"teaching": {}}) is None
    t = {"teaching": {"sensitivity_ranking": []}}
    assert cce.normalize_teaching_sensitivity(t) is None
    # 名次不连续（1..N 全序破坏）
    t = {"teaching": {"sensitivity_ranking": [
        {"param": "a", "order": 1, "basis": "b1"},
        {"param": "b", "order": 3, "basis": "b2"}]}}
    assert cce.normalize_teaching_sensitivity(t) is None
    # bool order（df7+⑯ 口径显式拒收）/缺 basis/非 dict 条目
    t = {"teaching": {"sensitivity_ranking": [
        {"param": "a", "order": True, "basis": "b1"}]}}
    assert cce.normalize_teaching_sensitivity(t) is None
    t = {"teaching": {"sensitivity_ranking": [
        {"param": "a", "order": 1}]}}
    assert cce.normalize_teaching_sensitivity(t) is None
    t = {"teaching": {"sensitivity_ranking": ["not_a_dict"]}}
    assert cce.normalize_teaching_sensitivity(t) is None
    # 正常：按 order 全序出 ranking，source=teaching 标注
    t = {"teaching": {"sensitivity_ranking": [
        {"param": "b", "order": 2, "basis": "x"},
        {"param": "a", "order": 1, "basis": "y"}]}}
    out = cce.normalize_teaching_sensitivity(t)
    assert out == {"source": "teaching", "ranking": [
        {"rank": 1, "param": "a", "basis": "y"},
        {"rank": 2, "param": "b", "basis": "x"}]}


# ── W8 桥接：统一消费源三态 + W6 面不回归（review_ge8e F1 处置②收口）──────

def test_resolve_sensitivity_three_state_priority():
    """统一消费源三态优先级钉：computed > teaching > None（W8 桥接）。"""
    meta = {"teaching": {"sensitivity_ranking": [
        {"param": "a", "order": 1, "basis": "x"}]}}
    # ① computed 在场 → 胜出（不冒充 teaching；provenance=数据指针）
    entry = {"method": "sobol", "source_run": "runs/example",
             "ranking": [{"param": "a", "score": 0.7}]}
    out = cce.resolve_sensitivity(entry, meta)
    assert out["source"] == "computed"
    assert out["provenance"] == {"registry": cce.SENSITIVITY_REGISTRY_REL,
                                 "source_run": "runs/example"}
    # ①' computed 无 source_run → 指针只含登记表路径
    out_nr = cce.resolve_sensitivity(
        {"method": "sobol", "ranking": [{"param": "a", "score": 0.7}]}, meta)
    assert out_nr["provenance"] == {"registry": cce.SENSITIVITY_REGISTRY_REL}
    # ② 登记表无条目 → teaching 兜底
    out2 = cce.resolve_sensitivity(None, meta)
    assert out2 == {"source": "teaching", "ranking": [
        {"rank": 1, "param": "a", "basis": "x"}]}
    # ③ 双缺 → 如实 None
    assert cce.resolve_sensitivity(None, {}) is None


def test_sensitivity_bad_computed_degrades_to_teaching():
    """坏数据拒收钉（#105）：登记表条目坏 → 如实降级 teaching/None，不阻塞。"""
    bad_entry = {"method": "sobol",
                 "ranking": [{"param": "x", "score": "not_a_number"},
                             {"param": "y", "score": True},
                             {"param": "z", "score": -1.0}]}
    meta = {"teaching": {"sensitivity_ranking": [
        {"param": "a", "order": 1, "basis": "x"}]}}
    # 坏 computed → teaching 兜底（降级，不硬凑不炸）
    out = cce.resolve_sensitivity(bad_entry, meta)
    assert out is not None and out["source"] == "teaching"
    # 坏 computed + 无 teaching → 如实 None
    assert cce.resolve_sensitivity(bad_entry, {}) is None
    # 坏 teaching（名次破坏全序）+ 无 computed → 如实 None
    bad_meta = {"teaching": {"sensitivity_ranking": [
        {"param": "a", "order": 2, "basis": "x"}]}}
    assert cce.resolve_sensitivity(None, bad_meta) is None


def _sens_section(md: str) -> str:
    """渲染面敏感性节（标题起、判据标题止；W6 面不回归钉切片口径）。"""
    return md[md.index("## 敏感性排序"):md.index("## 判据")]


_W6_TEACHING_SECTION = (
    "## 敏感性排序（R9 先承诺）\n"
    "\n"
    "- 出处=teaching（`docs/templates/<模板名>/meta.yaml` "
    "teaching.sensitivity_ranking；EP-5 口径：order 名次 + basis "
    "依据，来自可复核闭式恒等式而非幅值——幅值分数待 "
    "`knowledge/sensitivity_rankings.yaml` 数据管线落档后重跑"
    "导出器上卡）\n"
    "\n"
    "| 名次 | 参数 | 依据 |\n"
    "|---|---|---|\n"
    "| 1 | arm_len_mm | λ/4 恒等式 |∂lnf0/∂lnL|=1（精确）；"
    "名义臂长=synthesize_wilkinson 综合链 |\n"
    "| 2 | er | f0 ∝ 1/sqrt(εeff)，|∂lnf0/∂lnεeff|=1/2 恒等式"
    "（er 经 εeff(w) 打折） |\n"
    "| 3 | series_w_mm | 臂宽经 εeff(w) 二阶进入臂长，并直接定臂阻抗口径"
    "（R006 线宽失配坑族） |\n"
    "| 4 | shunt_w_mm | 50Ω 馈线宽：只影响馈线匹配，λ/4 恒等式不含此项"
    "（弱敏感） |\n"
    "- 排序=teaching 名次全序（1..N 连续；人工 commit 写入，"
    "引用锚文本由 test_teaching_service 对 grounding 文件核验）\n"
    "\n"
)

_W6_FALLBACK_SECTION = (
    "## 敏感性排序（R9 先承诺）\n"
    "\n"
    "-（暂无已落档敏感度排序——挂接契约：`knowledge/sensitivity_rankings.yaml`，"
    "设计见 `runs/qw5_b32_capability_cards/design_note.md`；数据落档后重跑"
    "导出器自动上卡，不硬凑）\n"
    "\n"
)


def test_w6_sensitivity_face_non_regression():
    """W6 面不回归钉：teaching 卡（wilkinson 真数据）与 62 张回退卡敏感性节
    逐字节不变（W8 桥接只动 computed 分支；teaching/None 分支零改动）。"""
    md = cce.render_card_md(cce.collect_card("wilkinson"))
    assert _sens_section(md) == _W6_TEACHING_SECTION
    md62 = cce.render_card_md(cce.collect_card("ring_resonator"))
    assert _sens_section(md62) == _W6_FALLBACK_SECTION


def test_sensitivity_computed_face_renders_provenance():
    """computed 上卡面（W8 桥接新增分支）：出处=computed + 数据指针行在扬；
    W6 既有 method/证据/分数表行零改动（升级卡升级面=新增出处行）。"""
    entry = {"method": "sobol", "n_samples": 512, "seed": 42,
             "source_run": "runs/example",
             "ranking": [{"param": "a_mm", "score": 0.8}]}
    card = cce.collect_card("wilkinson", sensitivity_entry=entry)
    md = cce.render_card_md(card)
    assert ("- 出处=computed（幅值分数登记表 "
            "`knowledge/sensitivity_rankings.yaml`；证据 runs/example；"
            "坏条目拒收如实降级 #105）") in md
    assert "方法 sobol ｜ n=512 ｜ seed=42 ｜ 证据：runs/example" in md
    assert "| 1 | a_mm | 0.8 |" in md
