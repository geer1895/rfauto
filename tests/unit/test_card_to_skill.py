"""T-Q10（aurora_q Q-W6-1）：card → SKILL.md 标准能力包产线测试。

钉五件事（R9 §8 规格，runs/aurora_q/r9/SKILL_ECO.md）：
1. frontmatter 合规三钉（name 正则=目录名 ≤64 / description ≤1024 零
   流程词 / 正文行数预算 <500）——agentskills.io 口径；
2. 产线确定性：同入参两次生成逐字节同；落盘幂等；
3. #144 缺省目录纪律回归钉：write_experience_skill 缺省拒写（不再向
   真实 skills/ 湖静默落包）、write_skill 缺省锚定配方目录、
   recipe_to_skill 信封 output_path 与 write_skill 实际路径一致、
   write_card_skill 的 output_dir 必填（born clean）；
4. 包结构钉：references/ 两卡逐字节副本 + pitfalls 抽出 + 渐进披露
   （正文不含坑账链明细）+ verify_output.py 结构核验器三态（过/数值
   拒/非有限拒）；
5. 出货对拍：skills/ 七包清点（六产线/刷新包 + 1 手写 curated 包
   veriloga-authoring）+ 三个产线包（mline/pifa/cpw）逐字节
   再生对拍 + 三个刷新包（recipe 型）正文逐字回放 + 全部 76 张能力卡
   可产线直转且 frontmatter 合规。

零网络、零 runs/ 写入、零新数值（测试内断言数字全部来自卡与内核
实跑记录，见 MLINE_EXAMPLE 出处注释）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service.skill_autopilot import validate_agentskills_md
from rfauto.service.skill_service import (
    _SKILL_FLOW_WORD_RE,
    SKILL_BODY_MAX_LINES,
    SKILL_DESCRIPTION_MAX,
    SKILL_NAME_MAX,
    SKILL_NAME_RE,
    card_to_skill,
    card_to_skill_batch,
    recipe_to_skill,
    write_card_skill,
    write_experience_skill,
    write_skill,
)

_REPO = Path(__file__).resolve().parents[2]
_SKILLS = _REPO / "skills"
_CAPS = _REPO / "docs" / "capability_cards"
_KERS = _REPO / "docs_site" / "kernel_cards"

#: 出货产线包的 curated 入参（与生成该包的生产运行逐字一致——再生门
#: 以本文件为 spec 单源）。MLINE_EXAMPLE = 2026-11-05 实跑
#: `rfauto syn mline 50 --freq 2.4 --stackup rogers4350b_h0.508 --json`
#: 的完整信封（确定性内核输出，非手拍数值）。
MLINE_EXAMPLE = {
    "z0_target": 50.0,
    "freq_ghz": 2.4,
    "stackup": "rogers4350b_h0.508",
    "width_mm": 1.1133,
    "z0_actual": 50.0,
    "epsilon_eff": 2.853,
    "status": "ok",
    "delta_z0": 0.0,
    "er_eff_source": "ep_reff",
    "skrf_version": "2.1.0",
}

MLINE_DESCRIPTION = (
    'Use when the user needs a microstrip line (mline) width or impedance for a'
    ' given substrate — e.g. "50 ohm line width on Rogers 4350B 0.508 mm", "what'
    ' Z0 is a 1.1 mm trace at 2.4 GHz", "epsilon_eff of this microstrip", or a'
    ' quarter-wave arm length; also when a Wilkinson/branchline/patch feed needs'
    ' its 50 / 70.7 / 35.35 ohm widths, or when a user pastes an openEMS/HFSS'
    ' mline run and asks why |S11| is non-zero or how to read the S21 phase slope'
    ' into epsilon_eff. Triggers: mline, microstrip, line width, impedance, Z0,'
    ' epsilon_eff, stackup ｜ 中文触发: 微带线 线宽 阻抗 等效介电常数 λ/4 臂长'
    ' 层叠. Do NOT use for CPW/CPS/stripline/SIW (sibling rfauto cards), ADS'
    ' LineCalc GUI help, or PCB current-capacity questions. Numbers come only'
    ' from the rfauto kernel and the card files under references/.')

MLINE_WORKFLOW = [
    "rfauto syn mline <Z0_ohm> --freq <GHz> --stackup <materials.yaml key> --json",
    "rfauto syn wilkinson --f0 <GHz> --z0 <ohm> --stackup <key> --json   # family synthesis (per-arm epsilon_eff)",
]

#: 判读表事实逐字出自 mline 内核卡（docs_site/kernel_cards/mline.md：
#: 三态机 / 0.5Ω 回代自洽带 / εeff 来源显式下泄 / XC-W 单源）。
MLINE_GUIDE = [
    ("status",
     "three-state machine: ok / er_eff_fallback / needs_calibration",
     "only ok is a design value; er_eff_fallback means epsilon_eff fell back to bulk er (lambda-based lengths are not trustworthy); needs_calibration means back-substitution missed the 0.5 ohm self-consistency band"),
    ("delta_z0",
     "back-substituted Z0 minus target",
     "must be < 0.5 ohm for status ok"),
    ("er_eff_source",
     "provenance of epsilon_eff (ep_reff = skrf effective permittivity)",
     "surface it verbatim; never invent an epsilon_eff"),
    ("width_mm",
     "the authoritative synthesized width for this stackup",
     "do not copy widths from other docs or templates (single-source rule, test_width_single_source)"),
]

#: 产线包 → curated 入参（空 dict = 纯机生）。
SHIPPED_CARD_PACKAGES = {
    "rfauto-mline-synthesis": {
        "card_id": "mline",
        "kwargs": {
            "skill_name": "rfauto-mline-synthesis",
            "description": MLINE_DESCRIPTION,
            "workflow_commands": MLINE_WORKFLOW,
            "reading_guide_rows": MLINE_GUIDE,
            "example_json": MLINE_EXAMPLE,
            "stackup_keys": ["rogers4350b_h0.508", "fr4_h1.6"],
        },
    },
    "rfauto-pifa": {"card_id": "pifa", "kwargs": {}},
    "rfauto-cpw": {"card_id": "cpw", "kwargs": {}},
}

#: 刷新包 → （源配方，capability 卡 ID，kernel 卡 ID）。
REFRESHED_PACKAGES = {
    "rfauto-wilkinson-power-divider": (
        "wilkinson_pd_v1.yaml", "wilkinson", "wilkinson",
        "Use when the user wants to design, run or tune a Wilkinson power "
        "divider with rfauto — two-way equal split, lambda/4 arm synthesis "
        "and isolation resistor, recipe-driven run/tune/autotune/calibrate "
        "workflows. Triggers: wilkinson, power divider, splitter, isolation "
        "resistor, arm length ｜ 中文触发: 威尔金森 功分器 等分 隔离电阻 臂长. "
        "Do NOT use for N-way or unequal-split variants (other rfauto cards) "
        "or for branchline/ratrace/gysel couplers. Numbers come only from "
        "the rfauto kernel and the card files under references/."),
    "rfauto-branchline-coupler": (
        "branchline_coupler_v1.yaml", "branchline", "branchline",
        "Use when the user wants to design, run or tune a branchline coupler "
        "(90-degree hybrid) with rfauto — quarter-wave arm impedance "
        "synthesis, recipe-driven run/tune/autotune/calibrate workflows. "
        "Triggers: branchline, branch-line, hybrid, 90 degree coupler, "
        "quadrature ｜ 中文触发: 分支线电桥 90度电桥 正交电桥. Do NOT use for "
        "ratrace (180-degree) or Lange/gysel couplers (other rfauto cards). "
        "Numbers come only from the rfauto kernel and the card files under "
        "references/."),
    "rfauto-patch-antenna": (
        "patch_antenna_v1.yaml", "patch", "patch",
        "Use when the user wants to design, run or tune a rectangular "
        "microstrip patch antenna with rfauto — cavity-model resonance, "
        "patch width/length synthesis and feed inset, recipe-driven "
        "run/tune/autotune/calibrate workflows. Triggers: patch antenna, "
        "microstrip antenna, patch width, inset feed, resonance frequency ｜ "
        "中文触发: 贴片天线 微带天线 谐振频率 馈电. Do NOT use for PIFA/IFA or "
        "patch arrays (other rfauto cards) or for generic PCB antenna "
        "questions. Numbers come only from the rfauto kernel and the card "
        "files under references/."),
}

#: 手写 curated 包（非 card/recipe 产线机生；AX-5 veriloga-authoring，
#: aurora_r R-04——读写两半的"写半"，与只读内核 core/veriloga_parser.py
#: 配对。内容正确性由 tests/unit/test_veriloga_authoring_skill.py 的
#: 围栏契约钉，本文件只钉它在 skills/ 湖的在场与 agentskills 合规）。
CURATED_PACKAGES = frozenset({"veriloga-authoring"})

EXPECTED_PACKAGE_DIRS = frozenset(
    set(SHIPPED_CARD_PACKAGES) | set(REFRESHED_PACKAGES) | CURATED_PACKAGES)


def _frontmatter(raw: str) -> dict:
    assert raw.startswith("---\n")
    close = raw.find("\n---\n", 4)
    assert close > 0
    return yaml.safe_load(raw[4:close]) or {}


def _card_spec(card_id: str):
    for name, spec in SHIPPED_CARD_PACKAGES.items():
        if spec["card_id"] == card_id:
            return name, spec["kwargs"]
    raise KeyError(card_id)


# ---------------------------------------------------------------------------
# 1. 产线契约与 frontmatter 合规
# ---------------------------------------------------------------------------

class TestCardToSkillContract:
    def test_mline_package_contract(self):
        _name, kwargs = _card_spec("mline")
        r = card_to_skill("mline", **kwargs)
        assert r["ok"], r["errors"]
        assert r["skill_name"] == _name == "rfauto-mline-synthesis"
        assert r["card_kind"] == "capability+kernel"
        assert list(r["files"]) == [
            "SKILL.md", "LICENSE.txt",
            "references/capability_card.md", "references/kernel_card.md",
            "references/pitfalls.md", "scripts/verify_output.py",
            "assets/stackups.yaml",
        ]  # 目录结构（R9 §8.3 按需子集）+ 键序（落盘顺序确定性）

    def test_frontmatter_name_compliance(self):
        _name, kwargs = _card_spec("mline")
        content = card_to_skill("mline", **kwargs)["content"]
        front = _frontmatter(content)
        assert front["name"] == "rfauto-mline-synthesis"
        assert SKILL_NAME_RE.match(front["name"])
        assert len(front["name"]) <= SKILL_NAME_MAX
        # 私有键全进 metadata，顶层无客户端方言键
        assert front["metadata"]["rfauto_card"] == "mline"
        assert "version" not in front
        assert front["metadata"]["card_kind"] == "capability+kernel"

    def test_description_compliance_curated_and_machine(self):
        _, kwargs = _card_spec("mline")
        curated = _frontmatter(
            card_to_skill("mline", **kwargs)["content"])["description"]
        assert curated == MLINE_DESCRIPTION
        assert len(curated) <= SKILL_DESCRIPTION_MAX
        assert not _SKILL_FLOW_WORD_RE.search(curated)
        # 机生路径：三张代表卡（含中文卡文并入与触发词）
        for card_id in ("mline", "pifa", "cpw"):
            desc = _frontmatter(
                card_to_skill(card_id)["content"])["description"]
            assert desc.strip()
            assert len(desc) <= SKILL_DESCRIPTION_MAX
            assert not _SKILL_FLOW_WORD_RE.search(desc)
            assert card_id in desc

    def test_body_line_budget_mline_under_250_all_under_500(self):
        _, kwargs = _card_spec("mline")
        n_mline = card_to_skill("mline", **kwargs)["n_lines"]
        assert n_mline <= 250  # R9 §8.3 渐进披露目标（本卡族正文中位参照）
        assert n_mline < SKILL_BODY_MAX_LINES

    def test_references_byte_identical_to_source_cards(self):
        _, kwargs = _card_spec("mline")
        files = card_to_skill("mline", **kwargs)["files"]
        assert (files["references/capability_card.md"]
                == (_CAPS / "mline.md").read_text(encoding="utf-8"))
        assert (files["references/kernel_card.md"]
                == (_KERS / "mline.md").read_text(encoding="utf-8"))
        assert (files["LICENSE.txt"]
                == (_REPO / "LICENSE").read_text(encoding="utf-8"))

    def test_pitfalls_extracted_and_body_stays_in_budget_layer(self):
        _, kwargs = _card_spec("mline")
        files = card_to_skill("mline", **kwargs)["files"]
        pitfalls = files["references/pitfalls.md"]
        # 坑账链条目在 pitfalls 明细层（卡面 playbook 条目逐字抽出）
        assert "fdtd_truncation_artifact" in pitfalls
        assert "grid_near_coincident_lines" in pitfalls
        # 渐进披露：正文快读层不含坑账链明细条目（只在需要时开 pitfalls）
        body = files["SKILL.md"]
        assert "fdtd_truncation_artifact" not in body
        assert "references/pitfalls.md" in body  # 加载时机表指路

    def test_example_json_recorded_and_absent_when_not_given(self):
        _, kwargs = _card_spec("mline")
        body = card_to_skill("mline", **kwargs)["content"]
        assert "## Recorded kernel output" in body
        assert "1.1133" in body and "ep_reff" in body
        pifa_body = card_to_skill("pifa")["content"]
        assert "## Recorded kernel output" not in pifa_body

    def test_stackups_subset_only_requested_keys(self):
        _, kwargs = _card_spec("mline")
        subset = yaml.safe_load(
            card_to_skill("mline", **kwargs)["files"]["assets/stackups.yaml"])
        keys = set(subset["materials"])
        assert keys == {"rogers4350b_h0.508", "fr4_h1.6"}
        full = yaml.safe_load(
            (_REPO / "configs" / "materials.yaml").read_text(encoding="utf-8"))
        assert subset["materials"]["rogers4350b_h0.508"] == \
            full["materials"]["rogers4350b_h0.508"]

    def test_unknown_stackup_key_rejected_not_guessed(self):
        r = card_to_skill("mline", stackup_keys=["no_such_stackup"])
        assert not r["ok"]
        assert any("no_such_stackup" in e for e in r["errors"])

    def test_missing_card_rejected(self):
        assert not card_to_skill("no_such_card_xyz")["ok"]

    def test_description_flow_word_rejected(self):
        r = card_to_skill("mline", description="先综合再反解然后回代验证")
        assert not r["ok"]
        assert any("流程词" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# 2. 确定性与幂等
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_generation_idempotent(self):
        _, kwargs = _card_spec("mline")
        r1 = card_to_skill("mline", **kwargs)
        r2 = card_to_skill("mline", **kwargs)
        assert r1["content"] == r2["content"]
        assert r1["files"] == r2["files"]

    def test_write_card_skill_roundtrip_and_idempotent(self, tmp_path):
        _, kwargs = _card_spec("mline")
        r1 = write_card_skill("mline", tmp_path, **kwargs)
        assert r1["ok"] and r1["written"]
        pkg = Path(r1["skill_dir"])
        assert Path(r1["output_path"]) == pkg / "SKILL.md"
        for rel, text in r1["files"].items():
            assert (pkg / rel).read_text(encoding="utf-8") == text
        r2 = write_card_skill("mline", tmp_path, **kwargs)
        for rel, text in r2["files"].items():
            assert (pkg / rel).read_text(encoding="utf-8") == text

    def test_write_card_skill_requires_output_dir_born_clean_144(self):
        _, kwargs = _card_spec("mline")
        r = write_card_skill("mline", None, **kwargs)
        assert not r["ok"]
        assert any("#144" in e for e in r["errors"])

    def test_batch_line_ok_and_fail_collected(self, tmp_path):
        r = card_to_skill_batch(["cpw", "pifa"], tmp_path)
        assert r["ok"] and r["n_ok"] == 2 and r["n_fail"] == 0
        assert (tmp_path / "rfauto-cpw" / "SKILL.md").exists()
        assert (tmp_path / "rfauto-pifa" / "SKILL.md").exists()
        bad = card_to_skill_batch(["cpw", "no_such_card_xyz"], tmp_path)
        assert not bad["ok"]
        assert bad["n_ok"] == 1 and bad["n_fail"] == 1
        failed = [x for x in bad["results"] if not x["ok"]]
        assert failed and failed[0]["card_id"] == "no_such_card_xyz"

    def test_verify_script_accepts_value_and_rejects_bad_and_nonfinite(
            self, tmp_path):
        _, kwargs = _card_spec("mline")
        r = write_card_skill("mline", tmp_path, **kwargs)
        script = Path(r["skill_dir"]) / "scripts" / "verify_output.py"
        good = tmp_path / "good.json"
        good.write_text(json.dumps(dict(MLINE_EXAMPLE)), encoding="utf-8")
        ok = subprocess.run(
            [sys.executable, str(script), "--json", str(good),
             "--expect", "width_mm=1.1133"],
            capture_output=True, text=True)
        assert ok.returncode == 0, ok.stdout + ok.stderr
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"width_mm": 9.9}), encoding="utf-8")
        reject = subprocess.run(
            [sys.executable, str(script), "--json", str(bad),
             "--expect", "width_mm=1.1133"],
            capture_output=True, text=True)
        assert reject.returncode == 1
        assert "FAIL" in reject.stdout
        nan = tmp_path / "nan.json"
        nan.write_text('{"a": NaN}', encoding="utf-8")
        nonfinite = subprocess.run(
            [sys.executable, str(script), "--json", str(nan)],
            capture_output=True, text=True)
        assert nonfinite.returncode == 1
        assert "non-finite" in nonfinite.stdout


# ---------------------------------------------------------------------------
# 3. #144 缺省目录纪律（回归钉）
# ---------------------------------------------------------------------------

class TestDefaultDirDiscipline144:
    @pytest.fixture
    def recipe_path(self, tmp_path):
        recipe = {
            "model": "probe_model",
            "params": {"x_mm": {"value": 1.0}},
            "setup": {"freq_range_ghz": [2.3, 2.5], "points": 3},
            "objectives": [],
            "optimization": {"params": {}},
        }
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
        return path

    def test_recipe_to_skill_output_path_matches_write_skill(self,
                                                             recipe_path):
        env = recipe_to_skill(recipe_path)
        assert env["ok"]
        written = write_skill(recipe_path)  # 缺省 = 配方同目录
        assert env["output_path"] == written["output_path"]
        assert Path(written["output_path"]).exists()

    def test_write_skill_default_anchored_to_recipe_dir(self, recipe_path,
                                                        monkeypatch):
        # 缺省目录锚定配方目录而非 cwd（#144 家族：cwd 相对解析禁用于
        # write_skill 形态）——在 cwd=仓根 时落点仍在配方所在 tmp 目录。
        monkeypatch.chdir(_REPO)
        written = write_skill(recipe_path)
        out = Path(written["output_path"])
        assert out.exists()
        assert out.parent.parent == recipe_path.parent
        assert _SKILLS not in out.parents

    def test_write_experience_skill_default_rejected(self, monkeypatch):
        monkeypatch.chdir(_REPO)
        r = write_experience_skill()
        assert not r["ok"]
        assert any("#144" in e for e in r["errors"])
        # 真实 skills/ 湖零污染
        assert not (_SKILLS / "rfauto-experience-checklists").exists()

    def test_write_experience_skill_explicit_dir_still_writes(self, tmp_path):
        r = write_experience_skill(output_dir=tmp_path)
        assert r["ok"] and r["written"]
        assert Path(r["output_path"]).exists()


# ---------------------------------------------------------------------------
# 4. 出货面：skills/ 七包清点 + 逐字节再生对拍 + 刷新回放
# ---------------------------------------------------------------------------

class TestShippedPackages:
    def test_skills_inventory_exact(self):
        dirs = {p.name for p in _SKILLS.iterdir() if p.is_dir()}
        assert dirs == EXPECTED_PACKAGE_DIRS

    def test_shipped_card_packages_match_regen_byte_identical(self):
        for name, spec in SHIPPED_CARD_PACKAGES.items():
            pkg = _SKILLS / name
            fresh = card_to_skill(spec["card_id"], **spec["kwargs"])
            assert fresh["ok"], (name, fresh["errors"])
            assert (pkg / "SKILL.md").read_text(encoding="utf-8") == \
                fresh["content"], name
            for rel, text in fresh["files"].items():
                assert (pkg / rel).read_text(encoding="utf-8") == text, (
                    name, rel)

    def test_shipped_packages_frontmatter_compliant(self):
        for name in sorted(EXPECTED_PACKAGE_DIRS):
            raw = (_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            front = _frontmatter(raw)
            assert front["name"] == name, name
            assert SKILL_NAME_RE.match(front["name"])
            assert len(front["name"]) <= SKILL_NAME_MAX
            assert len(str(front["description"])) <= SKILL_DESCRIPTION_MAX
            assert not _SKILL_FLOW_WORD_RE.search(str(front["description"]))
            assert "version" not in front  # 顶层无客户端方言键
            assert (_SKILLS / name / "LICENSE.txt").exists()

    def test_shipped_packages_pass_agentskills_validator(self):
        for name in sorted(EXPECTED_PACKAGE_DIRS):
            r = validate_agentskills_md(_SKILLS / name / "SKILL.md")
            assert r["ok"], (name, r["errors"])

    def test_body_budget_all_shipped_packages(self):
        for name in sorted(EXPECTED_PACKAGE_DIRS):
            raw = (_SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
            assert len(raw.splitlines()) < SKILL_BODY_MAX_LINES, name

    def test_refreshed_packages_replay_recipe_body(self):
        """刷新包正文 = recipe_to_skill(源配方) 再生体逐字内嵌（对拍钉）。"""
        for name, (recipe, _cap, _ker, _desc) in REFRESHED_PACKAGES.items():
            gen = recipe_to_skill(_REPO / "recipes" / recipe)
            assert gen["ok"], gen.get("errors")
            close = gen["content"].find("\n---\n", 4)
            body_only = gen["content"][close + 5:].strip()
            shipped = (_SKILLS / name / "SKILL.md").read_text(
                encoding="utf-8")
            assert body_only in shipped, name
            # 渐进披露结构段就位（刷新时追加的两节）
            assert "## When to open the reference files" in shipped, name
            assert "## Verify before you finish" in shipped, name

    def test_refreshed_packages_description_pinned(self):
        """刷新包 curated description 字面钉（溯源单源=本文件）。"""
        for name, (_recipe, _cap, _ker, desc) in REFRESHED_PACKAGES.items():
            front = _frontmatter(
                (_SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
            assert front["description"] == desc, name

    def test_refreshed_packages_references_byte_identical(self):
        for name, (_recipe, cap, ker, _desc) in REFRESHED_PACKAGES.items():
            refs = _SKILLS / name / "references"
            assert (refs / "capability_card.md").read_text(
                encoding="utf-8") == (_CAPS / f"{cap}.md").read_text(
                encoding="utf-8"), name
            assert (refs / "kernel_card.md").read_text(
                encoding="utf-8") == (_KERS / f"{ker}.md").read_text(
                encoding="utf-8"), name
            assert (refs / "pitfalls.md").exists(), name
            assert (_SKILLS / name / "scripts" / "verify_output.py").exists()

    def test_all_capability_cards_renderable_and_compliant(self):
        """76 张模板能力卡全量可产线直转（批量产线能力钉，tmp 域零落盘；
        75→76 aurora_q Q-X6 layered_stack，2026-11-07）。"""
        card_ids = sorted(p.stem for p in _CAPS.glob("*.md"))
        assert len(card_ids) == 76  # 器件模板数与 check_numbers 口径一致
        names: set[str] = set()
        for card_id in card_ids:
            r = card_to_skill(card_id)
            assert r["ok"], (card_id, r["errors"])
            front = _frontmatter(r["content"])
            assert SKILL_NAME_RE.match(front["name"]), card_id
            assert front["name"] == r["skill_name"]
            assert len(r["content"].splitlines()) < SKILL_BODY_MAX_LINES
            assert (r["files"]["references/capability_card.md"]
                    == (_CAPS / f"{card_id}.md").read_text(encoding="utf-8"))
            names.add(r["skill_name"])
        assert len(names) == len(card_ids)  # slug 化后仍两两不同

    def test_shipped_packages_metadata_provenance(self):
        for name, spec in SHIPPED_CARD_PACKAGES.items():
            front = _frontmatter(
                (_SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
            meta = front["metadata"]
            assert meta["author"] == "rfauto"
            assert meta["rfauto_card"] == spec["card_id"]
            assert meta["generator"] == \
                "rfauto.service.skill_service.card_to_skill"
            assert "docs/capability_cards/" in meta["source_cards"]
        for name in REFRESHED_PACKAGES:
            front = _frontmatter(
                (_SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
            meta = front["metadata"]
            assert meta["rfauto_model"] in {
                "wilkinson_power_divider", "branchline_coupler",
                "patch_antenna"}
            assert "recipes/" in meta["source_recipe"]
