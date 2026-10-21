"""Z-11 池登记项新鲜度巡检器单测（scripts/pool_patrol.py + service 引擎）。

覆盖：双判据（commit-tag×代码面）四态裁决、纯 docs commit 排除、撞号二次
消歧（qualified 别名/关键词选举/最早轮胜出/零候选 ambiguous）、五栏分级
（closed/open/partial/stale/ambiguous/merged_alias）、信封契约、CLI 注册面
与 --json 双形态；金标校准对 runs/pool_reaudit/reaudit_ledger_20261007.json
默认集 rate=1.0（真仓集成，账本/池文档缺席时诚实 skip——公开仓无此帧）。

测试零 git 依赖：commit/代码面经端口注入（CommitRec/files 替身，#144 无
chdir）；真仓校准是唯一触 git 的用例，缺席即 skip。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.service.pool_patrol_service import (
    CommitRec,
    calibrate,
    extract_keywords,
    parse_pool_doc,
    pool_patrol,
)

# ── 造数帮手 ────────────────────────────────────────────────────────────────

POOL_DOC_MIN = """# 池

## 第一轮：首登记轮（2026-09-24）

- **XA 系**：XA-1 alpha 语义流（FirstKind 闭式）/XA-2 beta 网格件/XA-3 gamma 端口件。
- **XB 系（XB-1..3）**：delta 家族语义流（RangeKind 闭式）。
- **Z-42 登记项新鲜度巡检**（本批制度化件）。

## 第二轮：域深挖轮（2026-10-04）

- **XA-2 改版语义流（SecondKind 全新域）**：跨轮撞号对照件。
- **WB-5 并档对照（=XA-1 同件并档）**。
- **Z-9 自称闭合件（勘误：基础面已在树）**。
"""


def _commit(sha: str, subject: str, files: tuple[str, ...], body: str = "") -> CommitRec:
    return CommitRec(sha=sha, date="2026-10-08T00:00:00+08:00", subject=subject,
                     body=body, files=files)


def _run(items_text: str, commits, files, **cfg) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "pool.md"
        doc.write_text(items_text, encoding="utf-8")
        config = {"pool_doc": str(doc), "commits": commits, "files": files, **cfg}
        return pool_patrol(config)


def _verdict_of(result: dict, token: str) -> dict:
    for it in result["items"]:
        if it["token"] == token:
            return it
    raise AssertionError(f"token {token} 不在巡检结果: {[i['token'] for i in result['items']]}")


# ── 关键词提取 ───────────────────────────────────────────────────────────────

class TestExtractKeywords:
    def test_separator_ascii_is_strong(self):
        strong, _ = extract_keywords("metrics.json 标准+golden 基线钉定（ORFS update_ok 审计语义）")
        # 全大写 len4（ORFS/HFSS 级）不入 strong（泛用缩写停用面设计口径）；
        # 含分隔符 token 与混写长词才是强关键词
        assert "metrics.json" in strong and "update_ok" in strong

    def test_cjk_long_run_is_strong_verbatim(self):
        strong, _ = extract_keywords("非均匀热梯度失谐链（域首登）")
        assert "非均匀热梯度失谐链" in strong

    def test_cjk_2gram_weak_only_from_long_runs(self):
        strong, weak = extract_keywords("去嵌方法选择裁判（全离线零真机）")
        assert "去嵌" in weak and "裁判" in weak
        assert "去嵌方法选择裁判" in strong

    def test_generic_words_filtered(self):
        strong, weak = extract_keywords("阻抗 模板 data model system closure")
        assert "阻抗" not in weak and "模板" not in weak
        assert "data" not in weak and "closure" not in weak and not strong

    def test_id_like_token_excluded(self):
        strong, weak = extract_keywords("承接 XN-9 的活")
        assert all("XN-9" not in k for k in (*strong, *weak))


# ── 池文档解析 ───────────────────────────────────────────────────────────────

class TestParsePoolDoc:
    def test_rounds_and_collision(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        xa2 = [it for it in items if it.token == "XA-2"]
        assert {it.round_no for it in xa2} == {1, 2}
        for it in xa2:
            assert it.is_collision
            assert it.occurrence_rounds == (1, 2)

    def test_range_header_fallback_keywords(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        xb1 = next(it for it in items if it.token == "XB-1")
        # 区间头（XB-1..3）局部段近空 → 回退 bullet 家族关键词
        assert any("delta" in kw or "RangeKind" in kw
                   for kw in (*xb1.keywords_strong, *xb1.keywords_weak))

    def test_merged_alias_detection(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        wb5 = next(it for it in items if it.token == "WB-5")
        assert wb5.merged_target == "XA-1"

    def test_self_claim_detection(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        z9 = next(it for it in items if it.token == "Z-9")
        assert z9.self_claimed_closed

    def test_cn_round_numbers(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        assert sorted({it.round_no for it in items}) == [1, 2]


# ── 双判据四态 + 纯 docs 排除 ────────────────────────────────────────────────

class TestDualCriteria:
    def test_closed_needs_both(self):
        res = _run(
            POOL_DOC_MIN,
            [_commit("a" * 40, " 实现笔 Z-42 巡检器落地", ("src/x.py",))],
            {"src/x.py": "# Z-42 巡检器实现\n"},
        )
        assert _verdict_of(res, "Z-42")["status"] == "closed"

    def test_tag_only_is_partial_code_pending(self):
        res = _run(
            POOL_DOC_MIN,
            [_commit("b" * 40, " Z-42 巡检器落地", ("src/y.py",))],
            {"src/other.py": "pass\n"},
        )
        v = _verdict_of(res, "Z-42")
        assert v["status"] == "partial"
        assert v["reason"] == "tag_only_code_pending"

    def test_code_only_is_partial_tag_missing(self):
        res = _run(
            POOL_DOC_MIN,
            [],  # 无任何 commit
            {"src/other.py": "# Z-42 巡检器实现\n"},
        )
        v = _verdict_of(res, "Z-42")
        assert v["status"] == "partial"
        assert v["reason"] == "code_only_tag_missing"

    def test_open_zero_evidence(self):
        res = _run(POOL_DOC_MIN, [], {"src/other.py": "pass\n"})
        assert _verdict_of(res, "Z-42")["status"] == "open"

    def test_docs_only_commit_rejected_and_watched(self):
        res = _run(
            POOL_DOC_MIN,
            [_commit("c" * 40, "纯调研批提及 Z-42 巡检", ("docs/note.md", ""))],
            {"src/other.py": "pass\n"},
        )
        v = _verdict_of(res, "Z-42")
        assert v["status"] == "open"  # 纯 docs 笔不构成实现笔证据
        fp = res["false_positive_watch"]
        assert any(w["id"].endswith("Z-42") and w["kind"] == "docs_only_commits" for w in fp)

    def test_self_claimed_stale(self):
        res = _run(POOL_DOC_MIN, [], {"src/other.py": "pass\n"})
        assert _verdict_of(res, "Z-9")["status"] == "stale"

    def test_merged_alias(self):
        res = _run(POOL_DOC_MIN, [], {"src/other.py": "pass\n"})
        assert _verdict_of(res, "WB-5")["status"] == "merged_alias"

    def test_self_path_excluded_from_code_face(self):
        # 工具自身文件（金标清单里含 ID 字面）不制造假证据
        res = _run(
            POOL_DOC_MIN,
            [],
            {"src/rfauto/service/pool_patrol_service.py": '"Z-42",\n'},
        )
        assert _verdict_of(res, "Z-42")["status"] == "open"


# ── 撞号二次消歧 ─────────────────────────────────────────────────────────────

COLLISION_DOC = """# 池

## 第十五轮：首登记轮

- **MP 系（MP-1..7）**：瞬态热 RC（Foster 闭式）/电晕局放/多物理其余件。

## 第二十二轮：域深挖轮

- **MP 系（多物理 II 3）**：MP-1 非均匀热梯度失谐链/MP-2 电流拥挤。
"""


class TestCollisionDisambiguation:
    def test_qualified_alias_attributes(self):
        # 账面 qualified 名（SB22-MP-1 形态口径）直接归属 22 轮
        res = _run(
            COLLISION_DOC,
            [_commit("d" * 40, " SB22-MP-1 失谐链落地", ("src/w.py",))],
            {"src/w.py": "# 非均匀热梯度失谐链\n"},
        )
        v22 = next(it for it in res["items"] if it["token"] == "MP-1" and it["round"] == 22)
        assert v22["status"] == "closed"

    def test_election_resolves_to_family_round(self):
        # ge8-mp1 笔形态：裸 MP-1 + 十五轮家族语义 → 归 15，22 侧零证据=开放
        res = _run(
            COLLISION_DOC,
            [_commit("e" * 40, " MP-1瞬态热RC(Foster闭式)", ("src/t.py",))],
            {"src/other.py": "pass\n"},
        )
        v15 = next(it for it in res["items"] if it["token"] == "MP-1" and it["round"] == 15)
        v22 = next(it for it in res["items"] if it["token"] == "MP-1" and it["round"] == 22)
        assert v15["status"] == "partial"  # 有 tag 无代码=待代码取证
        assert v22["status"] == "open"     # 已消解到他轮，本侧干净

    def test_zero_candidate_is_ambiguous(self):
        # 裸 token 命中但零轮关键词可认领 → 撞号未消解不强判
        res = _run(
            COLLISION_DOC,
            [_commit("f" * 40, " MP-1 第三命名空间件", ("src/z.py",))],
            {"src/other.py": "pass\n"},
        )
        for rnd in (15, 22):
            v = next(it for it in res["items"] if it["token"] == "MP-1" and it["round"] == rnd)
            assert v["status"] == "ambiguous"

    def test_multi_candidate_earliest_wins(self):
        # ≥2 轮关键词同票 → 最早登记轮胜出（后轮=引用/勘误补记）
        res = _run(
            COLLISION_DOC,
            [_commit("g" * 40, " MP-1 瞬态热与非均匀热梯度同批", ("src/x.py",))],
            {"src/other.py": "pass\n"},
        )
        v15 = next(it for it in res["items"] if it["token"] == "MP-1" and it["round"] == 15)
        v22 = next(it for it in res["items"] if it["token"] == "MP-1" and it["round"] == 22)
        assert v15["status"] == "partial"   # 拿到 tag（最早轮胜出）
        assert v22["status"] == "open"      # 引用轮不与登记件竞争


# ── 信封契约与 ids 过滤 ──────────────────────────────────────────────────────

class TestEnvelope:
    def test_missing_doc_error_envelope(self, tmp_path):
        res = pool_patrol({"pool_doc": str(tmp_path / "nope.md")})
        assert res["ok"] is False
        assert res["errors"]

    def test_ids_filter_error_on_unknown(self, tmp_path):
        doc = tmp_path / "pool.md"
        doc.write_text(POOL_DOC_MIN, encoding="utf-8")
        res = pool_patrol({"pool_doc": str(doc), "ids": ["NOPE-9"],
                           "commits": [], "files": {}})
        assert res["ok"] is False

    def test_ok_envelope_shape(self):
        res = _run(POOL_DOC_MIN, [], {"src/other.py": "pass\n"})
        assert res["ok"] is True
        for key in ("counts", "items", "false_positive_watch", "false_negative_watch"):
            assert key in res
        assert res["counts"]["open"] >= 1

    def test_qualified_id_in_ids_filter(self):
        res = _run(COLLISION_DOC, [], {"src/o.py": "pass\n"},
                   ids=["MP-1"])
        assert res["ok"] is True
        assert {it["round"] for it in res["items"]} == {15, 22}

    def test_ids_lens_is_context_stable(self):
        # 透镜不是改判器：qualified 名只报 22 轮，但裁决必须与全池一致
        # （15 轮在场时 ge8 形态 commit 被选举吸走；单看 22 轮会误判 partial）
        commits = [_commit("e" * 40, " MP-1瞬态热RC(Foster闭式)",
                           ("src/t.py",))]
        full = _run(COLLISION_DOC, commits, {"src/o.py": "pass\n"})
        lens = _run(COLLISION_DOC, commits, {"src/o.py": "pass\n"},
                    ids=["SB22-MP-1"])
        v_full = next(it for it in full["items"]
                      if it["token"] == "MP-1" and it["round"] == 22)
        assert lens["total_items"] == 1
        v_lens = lens["items"][0]
        assert v_lens["status"] == v_full["status"] == "open"


# ── 金标校准（纯函数面） ─────────────────────────────────────────────────────

class TestCalibrate:
    def test_rate_one_on_agreeing_verdicts(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        verdicts = {(it.round_no, it.token): {"status": "closed", "reason": "r"}
                    for it in items}
        cal = calibrate(verdicts, items, gold_closed=("Z-42",), gold_open=())
        assert cal["rate"] == 1.0 and cal["mismatches"] == []

    def test_mismatch_listed(self):
        items = parse_pool_doc(POOL_DOC_MIN)
        verdicts = {(it.round_no, it.token): {"status": "open", "reason": "r"}
                    for it in items}
        cal = calibrate(verdicts, items, gold_closed=("Z-42",), gold_open=())
        assert cal["mismatches"] and cal["mismatches"][0]["id"] == "Z-42"


# ── CLI 注册面与 --json 双形态 ───────────────────────────────────────────────

class TestCliPoolPatrol:
    def test_registered(self):
        from rfauto.cli.main import app

        names = [i.name for i in app.registered_commands]
        assert "pool-patrol" in names

    def test_json_error_envelope_exit_2(self, tmp_path):
        from rfauto.cli.main import app

        runner = CliRunner()
        result = runner.invoke(
            app, ["pool-patrol", "--pool-doc", str(tmp_path / "nope.md"), "--json"])
        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["ok"] is False

    def test_json_success_envelope_monotone(self, tmp_path, monkeypatch):
        from rfauto.cli import main as cli_main
        from rfauto.service import pool_patrol_service as svc_mod

        doc = tmp_path / "pool.md"
        doc.write_text(POOL_DOC_MIN, encoding="utf-8")

        def fake_pool_patrol(config):
            return {"ok": True, "counts": {"closed": 0, "open": 3}, "items": [],
                    "false_positive_watch": [], "false_negative_watch": []}

        monkeypatch.setattr(svc_mod, "pool_patrol", fake_pool_patrol)
        runner = CliRunner()
        result = runner.invoke(
            cli_main.app,
            ["pool-patrol", "--pool-doc", str(doc), "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True

    def test_human_output_smoke(self, tmp_path):
        from rfauto.cli.main import app

        doc = tmp_path / "pool.md"
        doc.write_text(POOL_DOC_MIN, encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(app, ["pool-patrol", "--pool-doc", str(doc)])
        assert result.exit_code == 0


# ── 独立脚本面 ───────────────────────────────────────────────────────────────

class TestScriptEntry:
    def test_main_json_exit_2_on_missing_doc(self, tmp_path, capsys):
        scripts_dir = Path(__file__).parent.parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        try:
            import pool_patrol as script

            rc = script.main([str(tmp_path / "nope.md"), "--json"])
            assert rc == 2
            payload = json.loads(capsys.readouterr().out)
            assert payload["ok"] is False
        finally:
            sys.path.remove(str(scripts_dir))

    def test_human_report_smoke(self):
        scripts_dir = Path(__file__).parent.parent.parent / "scripts"
        sys.path.insert(0, str(scripts_dir))
        try:
            import pool_patrol as script

            text = script._human({
                "pool_doc": "x.md", "total_items": 2,
                "counts": {"closed": 1, "open": 1, "partial": 0, "stale": 0,
                           "ambiguous": 0, "merged_alias": 0},
                "items": [{"id": "R1/Z-42", "status": "open", "reason": "双判据零命中",
                           "round": 1, "line_no": 4}],
            })
            assert "闭合 1" in text and "R1/Z-42" in text
        finally:
            sys.path.remove(str(scripts_dir))


# ── 真仓金标校准（集成；帧缺席诚实 skip） ────────────────────────────────────

REPO = Path(__file__).parent.parent.parent
POOL_DOC_REAL = REPO / "docs" / "plan_expansion_pool_20260924.md"


class TestGoldCalibrationRealRepo:
    @pytest.mark.slow  # 终门 DURATIONS >60s 慢件（206s，真仓金标校准）
    def test_default_gold_rate_is_one(self):
        if not POOL_DOC_REAL.exists():
            pytest.skip("池登记文档不在帧内（公开仓无此文件）——真仓校准 skip")
        res = pool_patrol({"pool_doc": str(POOL_DOC_REAL), "gold": True})
        assert res["ok"] is True
        cal = res["calibration"]
        assert cal["rated"] >= 15, f"金标样本不足: {cal['rated']}"
        assert cal["rate"] == 1.0, (
            f"金标不一致={cal['mismatches']}（修工具不修金标）")
        assert res["calibration_gate"] == "PASS"
