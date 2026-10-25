"""EP-5 教学三件单测（teaching_service：物理推导节 + 教科书反向索引 + 题库）。

裁判独立性（#118）：
- 出处接地测试：每张卡的 derivation source 必须①指回仓内 grounding 文件
  （docs/rf_template_references.md / knowledge/rules.yaml / knowledge/
  anchors.yaml / core 内核），且②教科书作者名在该 grounding 文件本体
  在场（引用链可复核——不接受 LLM 自编出处，铁律 7 精神）；
- 题库：期望值由内核现算（内置答案=零），patch 宽度/耦合系数/horn 增益
  与测试侧独立手算/仓内恒等式对拍；
- 卡数 ≥8（任务书首批门槛），模板名必须在 EXPECTED_TEMPLATES 冻结集。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service import teaching_service as ts
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

_REFERENCES = (REPO / "docs" / "rf_template_references.md").read_text(encoding="utf-8")
_RULES = (REPO / "knowledge" / "rules.yaml").read_text(encoding="utf-8")
_ANCHORS = (REPO / "knowledge" / "anchors.yaml").read_text(encoding="utf-8")

#: grounding 文件（仓内已核口径所在）
_GROUNDING_FILES = {
    "docs/rf_template_references.md": _REFERENCES,
    "knowledge/rules.yaml": _RULES,
    "knowledge/anchors.yaml": _ANCHORS,
}
_AUTHOR_TOKENS = (
    "Pozar", "Balanis", "Orfanidis", "Hammerstad", "Lancaster",
    "Makimoto", "Qucs", "Gupta", "Dishal",
)


def _grounding_body(source: str) -> str | None:
    """source 串指回的 grounding 文件本体（无指针→None）。"""
    for name, body in _GROUNDING_FILES.items():
        if name in source:
            return body
    return None


class TestTeachingCards:
    def test_first_batch_at_least_8_templates(self):
        filled = ts.list_teaching_templates()
        assert len(filled) >= 8
        assert set(filled) <= set(EXPECTED_TEMPLATES)

    def test_card_schema_and_sources_nonempty(self):
        for tmpl in ts.list_teaching_templates():
            t = ts.load_teaching(tmpl)
            assert t["schema"] == "rfauto-teaching/v1"
            assert t["physics"]["summary"]
            for d in t["physics"]["derivations"]:
                assert d["claim"] and d["formula"] and d["source"]
            # 名次 1..N 连续（load_teaching 已校验，双检）
            orders = sorted(int(r["order"]) for r in t["sensitivity_ranking"])
            assert orders == list(range(1, len(orders) + 1))

    def test_every_source_is_grounded(self):
        # 出处接地①：derivation source 必须含 ≥1 个可解析的仓内指针
        # （grounding 文档 / core 模块 / 模板卡 meta），且②凡声称教科书
        # 作者名，该名必须在仓内 grounding 本体在场（可复核引用链）
        import re

        for tmpl in ts.list_teaching_templates():
            t = ts.load_teaching(tmpl)
            for d in t["physics"]["derivations"]:
                src = d["source"]
                pointers = 0
                for doc, body in _GROUNDING_FILES.items():
                    if doc in src:
                        pointers += 1
                        assert body  # 文件本体已读入
                for token in re.findall(r"(core/[A-Za-z0-9_.]+)", src):
                    rel = token if token.endswith(".py") else token.split(".")[0] + ".py"
                    assert (REPO / "src" / "rfauto" / rel).is_file(), (tmpl, token)
                    pointers += 1
                for meta_path in re.findall(r"(docs/templates/[a-z0-9_]+/meta\.yaml)", src):
                    assert (REPO / meta_path).is_file(), (tmpl, meta_path)
                    pointers += 1
                assert pointers >= 1, (tmpl, src)
                # 教科书作者名接地（作者名声称必须在 grounding 本体在场）
                for tok in _AUTHOR_TOKENS:
                    if tok in src:
                        assert any(tok in body for body in _GROUNDING_FILES.values()), (tmpl, tok)
        # 敏感度 basis 必须非空（名次依据可溯源）
        for tmpl in ts.list_teaching_templates():
            t = ts.load_teaching(tmpl)
            for r in t["sensitivity_ranking"]:
                assert r["basis"], (tmpl, r["param"])

    def test_no_fabricated_page_numbers(self):
        # 未逐位核对的页码一律不写（章节/式号级引用）；"p. 123"/"pp.117" 形态即红
        import re

        for tmpl in ts.list_teaching_templates():
            blob = yaml.safe_dump(ts.load_teaching(tmpl), allow_unicode=True)
            assert not re.search(r"\bpp?\.\s*\d", blob), tmpl

    def test_render_markdown(self):
        md = ts.render_teaching_markdown("wilkinson")
        assert "## 物理与推导（wilkinson）" in md
        assert "敏感性排序" in md
        assert "例 7.2" in md

    def test_missing_block_and_bad_template(self, tmp_path, monkeypatch):
        # 缺块见证不再指向真实模板（teaching 卡已扩到全注册族）——用 tmp
        # 模板目录构造缺块/不存在两错误路径（monkeypatch TEMPLATES_DIR）
        nblock = tmp_path / "nblock"
        nblock.mkdir()
        (nblock / "meta.yaml").write_text(
            "template: nblock\nparams: []\n", encoding="utf-8")
        monkeypatch.setattr(ts, "TEMPLATES_DIR", tmp_path)
        with pytest.raises(ValueError, match="无 teaching 块"):
            ts.load_teaching("nblock")
        with pytest.raises(ValueError, match="模板卡不存在"):
            ts.load_teaching("no_such_template")


class TestTextbookIndex:
    def test_rows_and_grounding(self):
        out = ts.textbook_index()
        assert out["n_rows"] == len(ts.TEXTBOOK_INDEX)
        for row in ts.TEXTBOOK_INDEX:
            # 模板存在（冻结集）
            for t in row["templates"]:
                assert t in EXPECTED_TEMPLATES, t
            # 模块路径存在（仓内文件）
            for m in row["modules"]:
                assert (REPO / m).is_file(), m
            # 教科书姓氏在 references/rules 本体在场（章节串=已核口径同源）
            surname_seg = row["textbook"].split(",")[0]
            tokens = [tok for tok in _AUTHOR_TOKENS if tok in surname_seg]
            assert tokens, row["textbook"]
            assert any(tok in _REFERENCES or tok in _RULES for tok in tokens), row["textbook"]

    def test_filter_by_textbook(self):
        pozar = ts.textbook_index("Pozar")
        assert pozar["n_rows"] >= 1
        assert all("Pozar" in r["textbook"] for r in pozar["rows"])
        assert ts.textbook_index("不存在的书")["n_rows"] == 0


class TestQuizBank:
    def test_bank_shape_and_zero_builtin_answers(self):
        assert len(ts.QUIZ_BANK) >= 8
        ids = [q["id"] for q in ts.QUIZ_BANK]
        assert len(set(ids)) == len(ids)
        for q in ts.QUIZ_BANK:
            assert q["statement"] and q["source"] and q["solve"] is not None
            assert 0 < q["tolerance_rel"] <= 0.1
            assert q["statement"].format(**q["params"])  # 题面渲染不炸

    def test_render_quiz_substitution_and_source(self):
        q = ts.render_quiz("Q-WILK-ZT", {"z0_ohm": 100.0})
        assert "100.0" in q["statement"]
        assert q["source"]
        with pytest.raises(ValueError, match="未知题目"):
            ts.render_quiz("Q-NOPE")

    def test_check_answer_kernel_expected_and_judge(self):
        r = ts.check_answer("Q-WILK-ZT", 70.71067811865476)
        assert abs(r["expected"] - math.sqrt(2) * 50.0) <= 1e-12
        assert r["correct"] is True
        r_bad = ts.check_answer("Q-WILK-ZT", 60.0)
        assert r_bad["correct"] is False
        assert r_bad["rel_err"] > r_bad["tolerance_rel"]
        # 参数覆盖改变期望值（题面参数化、答案现算）
        r2 = ts.check_answer("Q-WILK-ZT", math.sqrt(2) * 100.0, params={"z0_ohm": 100.0})
        assert r2["correct"] is True
        with pytest.raises(ValueError):
            ts.check_answer("Q-WILK-ZT", -1.0)
        with pytest.raises(ValueError):
            ts.check_answer("Q-WILK-ZT", True)  # type: ignore[arg-type]

    def test_patch_w_independent_hand_check(self):
        # 独立手算：W = 299.792458/(2·2.4)·√(2/4.66) = 40.9167mm（Balanis 式）
        expect = 299.792458 / (2 * 2.4) * math.sqrt(2 / (3.66 + 1))
        r = ts.check_answer("Q-PATCH-W", expect)
        assert r["correct"] is True
        assert abs(r["expected"] - expect) <= 1e-12

    def test_coupling_k_identity(self):
        f1, f2 = 2.475, 2.525
        expect = (f2**2 - f1**2) / (f2**2 + f1**2)
        r = ts.check_answer("Q-HAIRPIN-K", expect)
        assert r["correct"] is True
        # 窄带近似 k≈2Δf/(f1+f2) 只作旁证（数值接近但不等——内核用精确式）
        approx = 2 * (f2 - f1) / (f1 + f2)
        assert abs(expect - approx) < 1e-3

    def test_dipole_rin_literature_constant(self):
        r = ts.check_answer("Q-DIPOLE-RIN", 73.0)
        assert r["correct"] is True
        assert abs(r["expected"] - 73.0) <= 1e-12
        # 非半波口径如实拒绝（不外推文献常数）
        with pytest.raises(ValueError, match="半波"):
            ts.check_answer("Q-DIPOLE-RIN", 73.0, params={"len_frac": 0.375})

    def test_horn_gain_repo_identity(self):
        # 仓内恒等式：名义综合设计点增益=15dB（test_pyramid_horn_template 同源）
        r = ts.check_answer("Q-HORN-GAIN", 15.0)
        assert r["correct"] is True
        assert abs(r["expected"] - 15.0) <= 0.01

    def test_mline_z0_50ohm_anchor(self):
        # 名义 50Ω 线宽 1.113mm@2.5GHz rogers4350b → Z0≈50Ω（R005/XC-W 定案口径）
        r = ts.check_answer("Q-MLINE-Z0", 50.0)
        assert r["correct"] is True
        assert abs(r["expected"] - 50.0) <= 1.0

    def test_wilkinson_arm_matches_template_nominal(self):
        # 综合链答案与模板卡名义臂长一致（wilkinson meta arm_len_mm=18.1@2.5GHz）
        r = ts.check_answer("Q-WILK-ARM", 18.1)
        assert r["correct"] is True

    def test_ratrace_ring_close_to_nominal(self):
        # ratrace meta r_ring_mm=17.344（周长=2πR≈108.97mm@2.5GHz）
        r = ts.check_answer("Q-RATRACE-RING", 2 * math.pi * 17.344)
        assert r["correct"] is True

    # ── R1 #19：三新模板族入题库（octagonal_spiral/mim_cap/interdigital_cap）──

    def test_new_family_cards_present_and_count_sync(self):
        ids = {q["id"] for q in ts.QUIZ_BANK}
        assert {"Q-OCTA-L", "Q-MIM-C", "Q-IDC-C"} <= ids
        # 卡数计数同步：旧族 9 + 新族 3 = 12
        assert len(ts.QUIZ_BANK) == 12

    def test_quiz_sources_grounded(self):
        # 出处接地（quiz 面）：凡声称的仓内指针必须真实存在——core/ 斜杠
        # 形式→模块文件 is_file（K19 修法：斜杠形式可被正则捕获且文件
        # 真实存在；点分 core.calc_families 形态不进正则，禁用）；三新族卡
        # 必须各含 ≥1 仓内指针（铁律 7：不接受 LLM 自编出处）
        import re

        new_ids = {"Q-OCTA-L", "Q-MIM-C", "Q-IDC-C"}
        for q in ts.QUIZ_BANK:
            src = q["source"]
            pointers = 0
            for doc in _GROUNDING_FILES:
                if doc in src:
                    pointers += 1
            for token in re.findall(r"(core/[A-Za-z0-9_.]+)", src):
                rel = token if token.endswith(".py") else token.split(".")[0] + ".py"
                assert (REPO / "src" / "rfauto" / rel).is_file(), (q["id"], token)
                pointers += 1
            for meta_path in re.findall(r"(docs/templates/[a-z0-9_]+/meta\.yaml)", src):
                assert (REPO / meta_path).is_file(), (q["id"], meta_path)
                pointers += 1
            if q["id"] in new_ids:
                assert pointers >= 1, (q["id"], src)

    def test_octagon_l_matches_template_nominal(self):
        # octagonal_spiral meta 名义档 L=4.1147nH（n=5、d_in=80、W=10、S=5μm
        # →d_out=220μm）；内核现算与 meta nominal_derivation 同链
        r = ts.check_answer("Q-OCTA-L", 4.1147)
        assert r["correct"] is True
        # 参数覆盖改变期望值（题面参数化、答案现算）
        r2 = ts.check_answer("Q-OCTA-L", 4.1147, params={"n_turns": 6})
        assert r2["expected"] > r["expected"]  # n² 主项单调

    def test_mim_cap_matches_template_nominal(self):
        # mim_cap meta 名义档 C=132.8128fF（20×20μm、d=0.2μm、εr=7.5；
        # 独立手算：ε0·7.5·400μm²/0.2μm——ε0 取 8.854187817e-12（ipc_cap
        # 常数口径）；内核 _EPS0=1/(μ0c²) 与之差 <1e-10 相对，绝对门放宽）
        expect = 8.854187817e-12 * 7.5 * (20e-6 * 20e-6) / 0.2e-6 * 1e15
        r = ts.check_answer("Q-MIM-C", expect)
        assert r["correct"] is True
        assert abs(r["expected"] - expect) <= 1e-6  # ε0 常数尾数口径差
        # meta nominal_derivation 名义档（4 位小数引用口径）
        assert abs(r["expected"] - 132.8128) < 1e-3

    def test_idc_cap_matches_template_nominal(self):
        # interdigital_cap meta 名义档 C=174.09fF（N=24、l_c=220−15=205μm、
        # s=5μm、t=3μm、εeff=(1+12.9)/2=6.95；用户实测 173.5fF 同量级参考）
        expect = 23 * 8.8541878128e-12 * 6.95 * 3e-6 * 205e-6 / 5e-6 * 1e15
        r = ts.check_answer("Q-IDC-C", expect)
        assert r["correct"] is True
        assert abs(r["expected"] - 174.09) < 0.01
        # 尖部外伸不产生相邻缝：e_tip 增大 → l_c 减小 → C 减小（负通道）
        r2 = ts.check_answer("Q-IDC-C", expect, params={"e_tip_um": 25.0})
        assert r2["expected"] < r["expected"]
