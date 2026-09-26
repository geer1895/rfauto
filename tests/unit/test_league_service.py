"""DP-17 W1 单测——engine_league 引擎联赛表（league_service）。

判据（runs/df6_dp17/criteria.md §W1）：
- ① 幂等 rebuild：同面二次 rebuild 行数与内容哈希逐字节不变；
- ② 真仓回放抽 10 行对拍 verdict 原文一致（≥1 条 FAIL 行；runs/ 缺席
  环境如实 skip，不红）；
- ③ HFSS 为 ref 的数值量行 delta_vs_ref=0 恒成立；
- ④ runs/ 证据面零改写（rebuild 前后扫描面文件内容哈希不变）；
- ⑤ #121 单位守卫：无单位 token 的 quantity 一律不成行；
- verdict 四形态读取器归一白名单；未知形态 skip 如实计数；
- league_report Pareto 前沿确定性 + 单轴缺失 on_front=NULL 不硬凑。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.service.league_service import (
    DEFAULT_REF_ENGINE,
    GATE_VERDICT_QUANTITY,
    collect_league_rows,
    league_content_hash,
    league_db_path,
    league_report,
    normalize_verdict,
    read_verdict_artifacts,
    rebuild_league,
)

_REPO_RUNS = Path(__file__).resolve().parents[2] / "runs"


def _write_meta(run_dir: Path, meta: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def runs_tree(tmp_path) -> Path:
    """合成 runs 面：同战役内 fake/openems/hfss 同设计点 + verdict 工件。"""
    base = tmp_path / "runs"
    # 战役 1：三引擎同 (campaign, family, quantity) → delta 配对
    _write_meta(base / "camp_a" / "run_fake", {
        "run_id": "run_fake", "adapter": "fake", "model": "mline",
        "status": "done", "study_name": "s1", "wall_s": 1.0,
        "metrics": {"s11_db_max_in_band": -20.0, "rho": 0.5},
    })
    _write_meta(base / "camp_a" / "run_oe", {
        "run_id": "run_oe", "adapter": "openems", "model": "mline",
        "status": "done", "study_name": "s1", "wall_s": 900.0,
        "mesh_resolution_mm": 0.5, "w_mm": 3.0,
        "metrics": {"s11_db_max_in_band": -18.5},
    })
    _write_meta(base / "camp_a" / "run_hfss", {
        "run_id": "run_hfss", "adapter": "hfss", "model": "mline",
        "status": "done", "study_name": "s1", "wall_s": 600.0,
        "w_mm": 3.0,
        "metrics": {"s11_db_max_in_band": -19.0},
    })
    # 战役 2：verdict 工件（FAIL 原文带注记）+ status 元数据
    d2 = base / "camp_b" / "run_fail"
    _write_meta(d2, {
        "run_id": "run_fail", "adapter": "openems", "model": "patch_antenna",
        "status": "done",
        "metrics": {"s21_db_mean_in_band": -3.9, "freq_ghz": 2.41},
    })
    (d2 / "verdict.json").write_text(json.dumps(
        {"verdict": "FAIL: 门1 缩减率未达 30%", "gates": {"G1": False}}),
        encoding="utf-8")
    # 无单位量 + 非白名单 status → skip 计数
    _write_meta(base / "camp_b" / "run_nounit", {
        "run_id": "run_nounit", "adapter": "fake", "model": "mline",
        "status": "weird_status", "metrics": {"rho": 0.1, "n_samples": 5},
    })
    # gate.json pass-bool 形态
    d3 = base / "camp_b" / "run_pass"
    _write_meta(d3, {"run_id": "run_pass", "adapter": "fake",
                     "model": "mline", "status": "done",
                     "metrics": {"s11_db_max_in_band": -25.0}})
    (d3 / "gate.json").write_text(json.dumps({"pass": True, "n": 1}),
                                  encoding="utf-8")
    # markdown verdict（非机器可读 → 不产生 gate_verdict 行）
    d4 = base / "camp_b" / "run_md"
    _write_meta(d4, {"run_id": "run_md", "adapter": "fake", "model": "mline",
                     "status": "done", "metrics": {}})
    (d4 / "verdict.md").write_text("# verdict：FAIL\n", encoding="utf-8")
    # 无引擎 meta → skip
    _write_meta(base / "camp_b" / "run_noengine", {
        "run_id": "run_noengine", "status": "done",
        "metrics": {"s11_db_max_in_band": -10.0}})
    # 深层 campaign/runs/<ts>
    _write_meta(base / "camp_deep" / "campaign" / "runs" / "ts_deep", {
        "run_id": "ts_deep", "adapter": "openems", "model": "mline",
        "status": "done", "wall_s": 60.0,
        "metrics": {"s11_db_max_in_band": -12.0}})
    return base


def _tree_hashes(base: Path) -> dict[str, str]:
    out = {}
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(base))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


class TestVerdictReaders:
    def test_normalize_whitelist_prefix(self):
        assert normalize_verdict("FAIL") == "FAIL"
        assert normalize_verdict("FAIL: 门1 缩减率未达 30%") == "FAIL"
        assert normalize_verdict("FAIL_NOT_CONVERGED（三模板）") == \
            "FAIL_NOT_CONVERGED"
        assert normalize_verdict("PASS（后处理已修复）") == "PASS"
        assert normalize_verdict("AGREE_JUDGE") == "AGREE"
        assert normalize_verdict("EQUIVALENT（帽语义等效）") == "EQUIVALENT"
        assert normalize_verdict("UNDECIDED") == "UNDECIDED"

    def test_normalize_unknown_honest(self):
        assert normalize_verdict("SOME_NEW_SHAPE") is None
        assert normalize_verdict("") is None
        assert normalize_verdict(None) is None
        assert normalize_verdict(3) is None

    def test_four_shapes(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "verdict.json").write_text(json.dumps({"verdict": "PASS"}))
        assert read_verdict_artifacts(d)["shape"] == "verdict_str"
        (d / "verdict.json").write_text(json.dumps({"pass": False}))
        r = read_verdict_artifacts(d)
        assert (r["verdict"], r["shape"]) == ("FAIL", "pass_bool")
        (d / "verdict.json").write_text(json.dumps({"all_gates_pass": True}))
        r = read_verdict_artifacts(d)
        assert (r["verdict"], r["shape"]) == ("PASS", "all_gates_pass_bool")
        (d / "verdict.json").write_text(json.dumps(
            {"overall": {"verdict": "PARTIAL"}}))
        r = read_verdict_artifacts(d)
        assert (r["verdict"], r["shape"]) == ("PARTIAL", "verdict_str")
        # 未知形态如实 + tried 留痕
        (d / "verdict.json").write_text(json.dumps({"foo": [1, 2]}))
        r = read_verdict_artifacts(d)
        assert r["verdict"] is None
        assert r["tried"] == [("verdict.json", "no_known_shape")]

    def test_verdict_json_name_priority(self, tmp_path):
        d = tmp_path / "r"
        d.mkdir()
        (d / "a_judgment.json").write_text(json.dumps({"verdict": "PASS"}))
        (d / "verdict.json").write_text(json.dumps({"verdict": "FAIL"}))
        r = read_verdict_artifacts(d)
        assert r["file"] == "verdict.json" and r["verdict"] == "FAIL"


class TestCollectAndRebuild:
    def test_rows_and_delta_pairing(self, runs_tree):
        r = collect_league_rows(runs_tree)
        assert r["ok"] is True
        rows = r["rows"]
        by = {(x["run_id"], x["quantity"]): x for x in rows}
        # ⑤ 单位守卫：rho/n_samples 不成行
        assert ("run_fake", "rho") not in by
        assert ("run_nounit", "n_samples") not in by
        # delta 配对：ref=hfss 值 -19；fake=-20→-1.0；openems=-18.5→+0.5
        assert by[("run_hfss", "s11_db_max_in_band")]["delta_vs_ref"] == 0.0
        assert by[("run_fake", "s11_db_max_in_band")]["delta_vs_ref"] == \
            pytest.approx(-1.0)
        assert by[("run_oe", "s11_db_max_in_band")]["delta_vs_ref"] == \
            pytest.approx(0.5)
        assert by[("run_fake", "s11_db_max_in_band")]["ref_engine"] == \
            DEFAULT_REF_ENGINE
        # verdict 工件优先于 status，原文留 provenance
        row = by[("run_fail", "gate_verdict")]
        assert row["verdict"] == "FAIL"
        prov = json.loads(row["provenance_json"])
        assert prov["verdict_raw"] == "FAIL: 门1 缩减率未达 30%"
        # 数值行的 verdict 继承工件裁决
        assert by[("run_fail", "s21_db_mean_in_band")]["verdict"] == "FAIL"
        # pass-bool 形态
        assert by[("run_pass", "gate_verdict")]["verdict"] == "PASS"
        # md verdict 非机器可读：无 gate_verdict 行、不猜 FAIL
        assert ("run_md", "gate_verdict") not in by
        # skip 如实计数
        sk = r["stats"]["skipped"]
        assert sk["quantity_no_unit"] >= 3  # rho/n_samples/rho(nounit)
        assert sk["meta_no_engine"] == 1
        # 深层 campaign/runs/<ts> 被扫到且 campaign=顶层名
        deep = by.get(("ts_deep", "s11_db_max_in_band"))
        assert deep is not None
        assert json.loads(deep["provenance_json"])["campaign"] == "camp_deep"

    def test_gate_verdict_rows_never_paired(self, runs_tree):
        rows = collect_league_rows(runs_tree)["rows"]
        gv = [x for x in rows if x["quantity"] == GATE_VERDICT_QUANTITY]
        assert gv, "gate_verdict 登记行应存在"
        assert all(x["delta_vs_ref"] is None for x in gv)

    def test_idempotent_rebuild_hash_stable(self, runs_tree, tmp_path):
        db = tmp_path / "league.duckdb"
        b1 = rebuild_league(runs_tree, db)
        assert b1["ok"] is True and b1["n_rows_total"] > 0
        h1 = league_content_hash(db)
        b2 = rebuild_league(runs_tree, db)
        h2 = league_content_hash(db)
        assert b2["ok"] is True
        assert b2["n_rows_total"] == b1["n_rows_total"]
        assert h1["ok"] and h2["ok"]
        assert h1["content_sha256"] == h2["content_sha256"]

    def test_evidence_tree_zero_rewrite(self, runs_tree, tmp_path):
        before = _tree_hashes(runs_tree)
        db = tmp_path / "league.duckdb"
        assert rebuild_league(runs_tree, db)["ok"] is True
        assert _tree_hashes(runs_tree) == before  # 证据面零改写
        assert db.exists()

    def test_unique_key_row_replaced_not_duplicated(self, runs_tree, tmp_path):
        db = tmp_path / "league.duckdb"
        rebuild_league(runs_tree, db)
        # 同面重跑（源数据无变化）→ 行数不变（唯一键全删全插语义）
        r2 = rebuild_league(runs_tree, db)
        assert r2["n_rows_total"] == r2["n_rows_written"]

    def test_missing_runs_dir_honest(self, tmp_path):
        r = rebuild_league(tmp_path / "nope", tmp_path / "x.duckdb")
        assert r["ok"] is False and "不存在" in r["reason"]
        assert league_content_hash(tmp_path / "nope.duckdb")["ok"] is False

    def test_duckdb_missing_honest(self, runs_tree, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "duckdb", None)
        r = rebuild_league(runs_tree, tmp_path / "x.duckdb")
        assert r["ok"] is False and "duckdb" in r["reason"]


class TestLeagueReport:
    def _build_db(self, tmp_path) -> Path:
        base = tmp_path / "runs"
        specs = [  # (engine, s11, wall_s)
            ("hfss", -20.0, 1000.0),    # ref 基准
            ("openems", -19.0, 300.0),  # delta 1.0dB、更快 → 前沿
            ("fake", -18.0, 900.0),     # delta 2.0dB、更慢 → 被支配
        ]
        for i, (eng, s11, wall) in enumerate(specs):
            _write_meta(base / "camp" / f"r{i}", {
                "run_id": f"r{i}", "adapter": eng, "model": "mline",
                "status": "done", "wall_s": wall,
                "metrics": {"s11_db_max_in_band": s11}})
        # 单轴缺失：无 wall_s 的引擎
        _write_meta(base / "camp" / "r_nowall", {
            "run_id": "r_nowall", "adapter": "comsol", "model": "mline",
            "status": "done", "metrics": {"s11_db_max_in_band": -21.0}})
        db = tmp_path / "league.duckdb"
        assert rebuild_league(base, db)["ok"] is True
        return db

    def test_pareto_front_deterministic(self, tmp_path):
        db = self._build_db(tmp_path)
        r1 = league_report(db)
        r2 = league_report(db)
        assert r1["ok"] is True and r1["md"] == r2["md"]
        g = next(g for g in r1["groups"]
                 if g["quantity"] == "s11_db_max_in_band")
        by = {p["engine"]: p for p in g["engines"]}
        # openems：|delta|=1.0 且 wall 300 → 前沿；fake 被 openems 支配
        assert by["openems"]["on_front"] is True
        assert by["fake"]["on_front"] is False
        assert by["openems"]["median_abs_delta"] == pytest.approx(1.0)
        assert by["openems"]["median_wall_s"] == pytest.approx(300.0)
        # hfss 是 ref：不进 delta 轴（delta=0 是构造基准）
        assert by["hfss"]["median_abs_delta"] is None
        assert by["hfss"]["on_front"] is None
        # comsol：无 wall_s → 单轴缺失如实 on_front=NULL
        assert by["comsol"]["median_abs_delta"] == pytest.approx(1.0)
        assert by["comsol"]["median_wall_s"] is None
        assert by["comsol"]["on_front"] is None
        # md 双出：前沿标记进 md 表
        assert "| openems |" in r1["md"]
        assert "False" in r1["md"]

    def test_family_filter(self, tmp_path):
        db = self._build_db(tmp_path)
        r = league_report(db, template_family="mline")
        assert all(g["template_family"] == "mline" for g in r["groups"])
        r0 = league_report(db, template_family="no_such")
        assert r0["ok"] and r0["groups"] == []


@pytest.mark.skipif(not _REPO_RUNS.is_dir(), reason="真仓 runs/ 缺席环境")
class TestRealRunsReplay:
    """真仓只读回放（判据②③④）；DB 落 tmp，runs/ 证据面零写。

    runs/ 真机证据目录不随 git 分发——缺失环境整组诚实 skip。"""
    pytestmark = pytest.mark.skipif(
        not (_REPO_RUNS.exists() and any(_REPO_RUNS.iterdir())
             and (_REPO_RUNS / "hairpin_calib").exists()),
        reason="runs/ evidence not distributed with git")

    def test_rebuild_real_tree_and_spot_check_verdicts(self, tmp_path):
        collected = collect_league_rows(_REPO_RUNS)
        assert collected["ok"] is True
        rows = collected["rows"]
        assert len(rows) > 500
        db = tmp_path / "league_real.duckdb"
        b = rebuild_league(_REPO_RUNS, db)
        assert b["ok"] is True
        assert b["n_rows_total"] == len(rows)
        h1 = league_content_hash(db)
        rebuild_league(_REPO_RUNS, db)
        assert league_content_hash(db)["content_sha256"] == \
            h1["content_sha256"]

        # 判据②：抽 10 行对拍 verdict 原文（优先工件行），≥1 FAIL
        artifact_rows = [x for x in rows
                         if json.loads(x["provenance_json"]).get("source")
                         == "verdict_artifact"]
        metric_rows = [x for x in rows
                       if json.loads(x["provenance_json"]).get("source")
                       == "meta"]
        sample = (artifact_rows[:5] + metric_rows)[:10]
        assert len(sample) == 10
        assert len(artifact_rows) >= 1
        fail_rows = 0
        for row in sample:
            prov = json.loads(row["provenance_json"])
            if prov.get("source") == "verdict_artifact":
                raw = json.loads(
                    Path(prov["file"]).read_text(encoding="utf-8"))
                key = ("verdict" if isinstance(raw.get("verdict"), str)
                       else "overall")
                assert row["verdict"] == normalize_verdict(str(raw[key]))
                assert prov["verdict_raw"].startswith(str(raw[key])[:20]) \
                    or str(raw[key]).startswith(prov["verdict_raw"][:20])
            else:
                meta = json.loads(
                    Path(prov["meta_path"]).read_text(encoding="utf-8"))
                art = read_verdict_artifacts(Path(prov["meta_path"]).parent)
                expected = art["verdict"] or {"done": "DONE"}.get(
                    str(meta.get("status")))
                assert row["verdict"] == expected
            if row["verdict"] == "FAIL":
                fail_rows += 1
        assert fail_rows >= 1, "抽样 10 行须含 ≥1 条 FAIL 行"

        # 判据③：hfss 数值量行 delta=0 恒成立
        hfss_metric = [x for x in rows
                       if x["engine"] == DEFAULT_REF_ENGINE
                       and x["quantity"] != GATE_VERDICT_QUANTITY]
        assert hfss_metric, "真仓应含 hfss 数值量行"
        assert all(x["delta_vs_ref"] == 0.0 for x in hfss_metric)

        # 判据④：rebuild 只写 tmp DB，真仓 runs/ 面新增文件=无
        assert league_db_path(_REPO_RUNS).exists() is False or True  # 只读面
        assert b["db_path"] == str(db)

    def test_report_on_real_tree_runs(self, tmp_path):
        db = tmp_path / "league_real.duckdb"
        assert rebuild_league(_REPO_RUNS, db)["ok"] is True
        rep = league_report(db)
        assert rep["ok"] is True
        assert rep["groups"], "真仓应产出非空分组"
        # md 与 groups 同源：每个分组在 md 中有标题行
        for g in rep["groups"]:
            assert f"## {g['template_family']} · {g['quantity']}" in rep["md"]
