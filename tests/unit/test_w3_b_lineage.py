"""W3-B（XD-1 跨 run lineage 索引，sa_specs2 §十）离线钉。

判据对照（任务书预声明门值）：
1. 写点零破坏：derived_from=None 时 meta.json 逐字节不变（既有 write_meta
   调用形态回归钉：签名 keyword-only+None 缺省+字节比对）。
2. 端到端三跳：合成三 run 链（calib→dataset→report）→ lineage 向上三跳
   闭合（含 git_sha 端点）；向下=影响面清单正确。
3. 旧档案兼容：无 derived_from 的历史 meta 照读照索引（零边零报错）；
   rebuild 后 lineage 表行数=全湖 derived_from 键计数（对拍钉）+幂等。
4. 环完整性：孤儿边（parent 不在湖）unknown_parent 计数进 verify 报告，
   边保留不删不崩（#316 多报不放过）；环边建表拒入+直写环递归终止。
5. 性能：合成湖 build+三跳查询计时 sanity（<60s/<1s；真湖 2873+ 目录
   实测落 runs/w3_phase3/w3b/lineage_perf.json，不入门）。
6. best-effort 钉：写边失败（归一化垃圾/duckdb 通道故障/meta 写失败）
   → 主流程成功完成+warnings/errors 留痕（#105）。

chdir 隔离零污染（#144）；duckdb/pyarrow 缺失诚实 skip；外部通道故障用
monkeypatch 钉住（#139），零网络依赖。
"""

from __future__ import annotations

import datetime as _dt
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="湖索引需要 dataset extra（duckdb）")

from rfauto.infra import run_store
from rfauto.infra.run_store import (
    LINEAGE_EDGE_KINDS,
    RUN_LINEAGE_TABLE,
    normalize_derived_from,
    record_lineage_edges,
    write_meta,
)
from rfauto.service import lake_service
from rfauto.service.lake_service import (
    build_runs_index,
    query_lineage,
    query_runs_index,
    render_lineage_md,
    verify_lineage,
)

# ---------------------------------------------------------------------------
# 共享基建：确定性 meta 写入（钉 provenance/时间）+ 合成 run/湖构造
# ---------------------------------------------------------------------------

class _FrozenDatetime(_dt.datetime):
    """write_meta 时间戳冻结（字节比对确定性）。"""

    @classmethod
    def now(cls, tz=None):
        return _dt.datetime(2026, 10, 5, 12, 0, 0, tzinfo=tz)


@pytest.fixture
def fast_meta(monkeypatch):
    """钉 _git_sha/collect_provenance/datetime——meta 字节确定+测试提速
    （真 provenance 含 pip freeze 子进程，逐次 ~1s）。"""
    monkeypatch.setattr(run_store, "_git_sha", lambda: "cafe123")
    monkeypatch.setattr(
        run_store, "collect_provenance",
        lambda **kw: {"python_version": "3.12.0", "os": "test-os",
                      "pip_freeze_sha": "fixed0123456789ef",
                      "solver_versions": {},
                      "optuna_seed": kw.get("optuna_seed"),
                      "numeric_env": {"available": False}})
    monkeypatch.setattr(run_store, "datetime", _FrozenDatetime)


def _mk_run(root: Path, name: str, *, model: str = "wilkinson",
            derived: list | None = None, kind: str = "derived",
            git: str = "cafe123") -> Path:
    """合成 run 点（fast_meta 生效前提下确定字节）。"""
    run_dir = root / name
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {"run_id": name, "model": model, "status": "done",
            "adapter": "fake", "study_name": name}
    if git is not None:
        meta["git_sha"] = git
    write_meta(run_dir, meta, run_id=name,
               derived_from=derived, edge_kind=kind)
    return run_dir


@pytest.fixture
def chain_lake(tmp_path, monkeypatch, fast_meta):
    """合成三 run 链（判据 2 形态）：calib01 → ds01(dataset) → rep01(report)。

    chdir 隔离（#144）；返回 (tmp_path, db_path, build_result)。"""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    _mk_run(runs, "calib01", model="wilkinson", git="git_calib")
    _mk_run(runs, "ds01", model="dataset", derived=["calib01"],
            kind="dataset", git="git_ds")
    _mk_run(runs, "rep01", model="sim_ci",
            derived=[{"run_id": "ds01", "edge_kind": "report"}],
            git="git_rep")
    db = tmp_path / "lake.duckdb"
    result = build_runs_index(runs, db_path=db)
    assert result["ok"], result.get("errors")
    return tmp_path, db, result


def _edge_rows(db: Path) -> list[tuple]:
    import duckdb

    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(
            f"SELECT child_run_id, parent_run_id, edge_kind "
            f"FROM {RUN_LINEAGE_TABLE} ORDER BY 1, 2, 3").fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 判据 1：写点零破坏（derived_from=None → meta 逐字节不变）
# ---------------------------------------------------------------------------

class TestWritePointZeroBreak:
    def test_signature_keyword_only_default_none(self):
        """既有调用签名兼容：derived_from/edge_kind 均 keyword-only 且
        derived_from 缺省 None（None=零改动现状，规格 §10.2.1 原文）。"""
        sig = inspect.signature(write_meta)
        for name in ("derived_from", "edge_kind"):
            param = sig.parameters[name]
            assert param.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert sig.parameters["derived_from"].default is None
        assert sig.parameters["edge_kind"].default == "derived"

    def test_none_kwarg_byte_identical_and_absent(self, tmp_path, fast_meta):
        """derived_from=None 与不传该参数：meta.json 逐字节一致，且均无
        derived_from 键（回归钉：全部既有调用零改动）。"""
        body = {"run_id": "r1", "model": "wilkinson", "status": "done"}
        p1 = write_meta(tmp_path / "a", body, run_id="r1")
        p2 = write_meta(tmp_path / "b", body, run_id="r1", derived_from=None)
        raw1 = p1.read_bytes()
        raw2 = p2.read_bytes()
        assert raw1 == raw2
        assert b"derived_from" not in raw1

    def test_legacy_call_shapes_absent_key(self, tmp_path, fast_meta):
        """代表性既有调用形态（meta_dict 直传/run_id+seed/provenance 覆盖）
        全部零 derived_from 键。"""
        shapes = [
            ({"run_id": "x", "model": "m", "status": "done"}, {}),
            ({}, {"run_id": "y", "seed": 42}),
            ({"python_version": "custom"}, {"run_id": "z"}),
        ]
        for i, (meta_dict, kwargs) in enumerate(shapes):
            path = write_meta(tmp_path / f"s{i}", meta_dict, **kwargs)
            meta = json.loads(path.read_text(encoding="utf-8"))
            assert "derived_from" not in meta

    def test_meta_dict_derived_from_passthrough_unchanged(self, tmp_path,
                                                          fast_meta):
        """meta_dict 自带 derived_from（历史/外来 meta 回写形态）：不经
        归一化直透（既有 record.update 语义不变）。"""
        body = {"run_id": "r", "derived_from": ["legacy"]}
        path = write_meta(tmp_path / "d", body)
        assert json.loads(path.read_text(encoding="utf-8"))["derived_from"] \
            == ["legacy"]


# ---------------------------------------------------------------------------
# 归一化单元（写边 best-effort 的内核面）
# ---------------------------------------------------------------------------

class TestNormalizeDerivedFrom:
    def test_str_dict_mixed_dedupe_and_junk(self):
        entries, warnings = normalize_derived_from(
            ["a", "a", {"run_id": "b", "edge_kind": "dataset"},
             {"run_id": "", "edge_kind": "x"}, 42, None, {"note": "no id"}],
            edge_kind="report")
        assert entries == [
            {"run_id": "a", "edge_kind": "report"},
            {"run_id": "b", "edge_kind": "dataset"},
        ]
        assert len(warnings) >= 3  # 空串重复已去重/空 run_id/非串非 dict

    def test_scalar_input_and_empty_kind(self):
        entries, _w = normalize_derived_from("solo")
        assert entries == [{"run_id": "solo", "edge_kind": "derived"}]
        entries2, _w2 = normalize_derived_from(["k"], edge_kind="  ")
        assert entries2[0]["edge_kind"] == "derived"

    def test_meta_form_plain_vs_dict(self):
        """缺省边种+无 note=裸 run_id 串（规格"run_id 列表"字面）；有边种/
        note=dict 形态。"""
        form = run_store._lineage_meta_form([
            {"run_id": "a", "edge_kind": "derived"},
            {"run_id": "b", "edge_kind": "dataset"},
            {"run_id": "c", "edge_kind": "calib", "note": "seed"},
        ])
        assert form == ["a",
                        {"run_id": "b", "edge_kind": "dataset"},
                        {"run_id": "c", "edge_kind": "calib",
                         "note": "seed"}]

    def test_write_meta_json_shapes_roundtrip(self, tmp_path, fast_meta):
        """meta.json 落盘形态：缺省边种=裸 run_id 串、显式边种=dict；读侧
        _lineage_edges_from_meta 对称还原（child=目录名）。"""
        write_meta(tmp_path / "r1", {"run_id": "r1"},
                   derived_from=["a"])
        write_meta(tmp_path / "r2", {"run_id": "r2"},
                   derived_from=["a", {"run_id": "b",
                                       "edge_kind": "warmstart"}],
                   edge_kind="calib")
        meta1 = json.loads((tmp_path / "r1" / "meta.json")
                           .read_text(encoding="utf-8"))
        assert meta1["derived_from"] == ["a"]
        meta2 = json.loads((tmp_path / "r2" / "meta.json")
                           .read_text(encoding="utf-8"))
        assert meta2["derived_from"] == [
            {"run_id": "a", "edge_kind": "calib"},
            {"run_id": "b", "edge_kind": "warmstart"}]
        edges = lake_service._lineage_edges_from_meta(meta2, "r2")
        assert ("r2", "a", "calib") in edges and ("r2", "b", "warmstart") in edges

    def test_edge_kind_vocab_documented(self):
        """预声明词汇表锚（dataset|calib|report|warmstart+derived 缺省）——
        开放词汇不做枚举强校验，常量只作文档锚。"""
        assert set(LINEAGE_EDGE_KINDS) == {
            "dataset", "calib", "report", "warmstart", "derived"}


# ---------------------------------------------------------------------------
# 判据 2：端到端三跳（向上闭合含 git_sha 端点 / 向下影响面）
# ---------------------------------------------------------------------------

class TestEndToEndThreeHops:
    def test_up_three_hops_closes_with_git_sha(self, chain_lake):
        _tmp, db, build = chain_lake
        assert build["n_lineage_edges"] == 2
        q = query_lineage(db, "rep01", direction="up", hops=3)
        assert q["ok"], q.get("errors")
        nodes = {n["run_id"]: n for n in q["nodes"]}
        assert set(nodes) == {"ds01", "calib01"}
        assert nodes["ds01"]["depth"] == 1
        assert nodes["ds01"]["edge_kind"] == "report"
        assert nodes["calib01"]["depth"] == 2
        assert nodes["calib01"]["edge_kind"] == "dataset"
        # 渲染 commit 端点闭环（§10.2.4）：上游 run 的 git_sha 可查
        assert nodes["calib01"]["git_sha"] == "git_calib"
        assert nodes["calib01"]["in_lake"] is True
        assert q["root"]["run_id"] == "rep01"
        assert q["root"]["git_sha"] == "git_rep"

    def test_down_impact_surface(self, chain_lake):
        _tmp, db, _b = chain_lake
        q = query_lineage(db, "calib01", direction="down", hops=3)
        assert q["ok"], q.get("errors")
        nodes = {n["run_id"]: n for n in q["nodes"]}
        assert set(nodes) == {"ds01", "rep01"}
        assert nodes["rep01"]["edge_kind"] == "report"
        assert q["children_count"] == 1  # calib01 的直接下游=ds01

    def test_hops_truncation(self, chain_lake):
        _tmp, db, _b = chain_lake
        q1 = query_lineage(db, "rep01", direction="up", hops=1)
        assert {n["run_id"] for n in q1["nodes"]} == {"ds01"}
        q3 = query_lineage(db, "rep01", direction="up", hops=3)
        assert {n["run_id"] for n in q3["nodes"]} == {"ds01", "calib01"}

    def test_md_tree_render(self, chain_lake):
        _tmp, db, _b = chain_lake
        q = query_lineage(db, "rep01", direction="up", hops=3)
        tree = render_lineage_md(q)
        assert "rep01" in tree and "(起点)" in tree
        assert "edge_kind=report" in tree and "edge_kind=dataset" in tree
        assert "git_sha=git_calib" in tree
        assert "children_count=" in tree

    def test_md_truncated_note(self, chain_lake):
        _tmp, db, _b = chain_lake
        q = query_lineage(db, "rep01", direction="up", hops=3, max_nodes=1)
        assert q["truncated"] is True
        assert "expand" in render_lineage_md(q)

    def test_query_validation_errors(self, chain_lake, tmp_path):
        _tmp, db, _b = chain_lake
        assert query_lineage(db, "")["ok"] is False
        assert query_lineage(db, "rep01", direction="sideways")["ok"] is False
        assert query_lineage(db, "rep01", hops="x")["ok"] is False
        assert query_lineage(db, "rep01", hops=99)["hops"] == 10  # 钳制
        assert query_lineage(db, "nope")["ok"] is False  # 起点不在湖零边
        assert query_lineage(tmp_path / "missing.duckdb", "x")["ok"] is False

    def test_zero_edges_start_in_lake_is_ok(self, chain_lake):
        """起点在湖但零边：ok=True 如实零节点（旧档案形态）。"""
        _tmp, db, _b = chain_lake
        q = query_lineage(db, "calib01", direction="up", hops=3)
        assert q["ok"] and q["nodes"] == [] and q["n_edges_walked"] == 0


# ---------------------------------------------------------------------------
# 判据 3：旧档案兼容 + 对拍钉（rebuild 行数=derived_from 键计数）+ 幂等
# ---------------------------------------------------------------------------

class TestLegacyCompatAndReplay:
    def test_legacy_lake_zero_edges_no_errors(self, tmp_path, monkeypatch,
                                              fast_meta):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _mk_run(runs, "old1")
        _mk_run(runs / "camp", "old2", model="patch")
        db = tmp_path / "lake.duckdb"
        r = build_runs_index(runs, db_path=db)
        assert r["ok"] and r["errors"] == []
        assert r["n_lineage_edges"] == 0
        assert r["n_lineage_unknown_parent"] == 0
        assert r["n_lineage_cycle_edges"] == 0
        v = verify_lineage(db)
        assert v["ok"] and v["consistent"] is True and v["n_edges"] == 0

    def test_rebuild_count_matches_derived_from_count(self, tmp_path,
                                                      monkeypatch, fast_meta):
        """对拍钉：lineage 表行数 = 全湖 derived_from 键（归一后）计数；
        drop-create 重建幂等（两次 rebuild 行数不变）。"""
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _mk_run(runs, "seed1")
        _mk_run(runs, "d1", derived=["seed1", "ghost1"], kind="dataset")
        _mk_run(runs, "d2", derived=[{"run_id": "seed1",
                                      "edge_kind": "warmstart"}])
        _mk_run(runs, "r1", derived=["d1", "d2"], kind="report")
        db = tmp_path / "lake.duckdb"
        r1 = build_runs_index(runs, db_path=db)
        # d1:2 + d2:1 + r1:2 = 5（ghost1 也在数内——边保留）
        assert r1["n_lineage_edges"] == 5
        assert len(_edge_rows(db)) == 5
        r2 = build_runs_index(runs, db_path=db)
        assert r2["n_lineage_edges"] == r1["n_lineage_edges"]

    def test_same_basename_two_campaigns_edges_both(self, tmp_path,
                                                    monkeypatch, fast_meta):
        """同名 run 点跨战役同父边=同三元组：PK 级去重（图级不可区分，
        去重如实——对拍口径=去重后边数；炸整表是本钉的回归面）。"""
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _mk_run(runs / "camp_a", "same_name", derived=["root1"],
                kind="dataset")
        _mk_run(runs / "camp_b", "same_name", derived=["root1"],
                kind="dataset")
        _mk_run(runs, "root1")
        db = tmp_path / "lake.duckdb"
        r = build_runs_index(runs, db_path=db)
        assert r["ok"], r.get("errors")
        assert r["n_lineage_edges"] == 1  # 去重后
        assert _edge_rows(db) == [("same_name", "root1", "dataset")]


# ---------------------------------------------------------------------------
# 判据 4：环完整性（孤儿边保留+计数；环边建表拒入；直写环递归终止）
# ---------------------------------------------------------------------------

class TestCycleIntegrity:
    def test_orphan_parent_reported_kept(self, tmp_path, monkeypatch,
                                         fast_meta):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _mk_run(runs, "kid", derived=["ghost_run"], kind="dataset")
        db = tmp_path / "lake.duckdb"
        r = build_runs_index(runs, db_path=db)
        assert r["ok"] and r["n_lineage_unknown_parent"] == 1
        assert r["lineage_unknown_parents"] == ["ghost_run"]
        # 边保留不删（#316 多报不放过）
        assert ("kid", "ghost_run", "dataset") in _edge_rows(db)
        v = verify_lineage(db)
        assert v["ok"] and v["consistent"] is False
        assert v["n_unknown_parent"] == 1
        assert v["unknown_parents"] == ["ghost_run"]
        # 查询面：孤儿节点 in_lake=False 富化字段 NULL，不崩
        q = query_lineage(db, "kid", direction="up", hops=3)
        assert q["ok"]
        assert q["nodes"][0]["run_id"] == "ghost_run"
        assert q["nodes"][0]["in_lake"] is False
        assert q["nodes"][0]["git_sha"] is None

    def test_cycle_edges_rejected_at_build(self, tmp_path, monkeypatch,
                                           fast_meta):
        """A derived B + B derived A：环边拒入（风险①），环外边保留。"""
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _mk_run(runs, "ra", derived=[{"run_id": "rb",
                                      "edge_kind": "warmstart"}])
        _mk_run(runs, "rb", derived=[{"run_id": "ra",
                                      "edge_kind": "warmstart"}])
        _mk_run(runs, "rc", derived=["ra"], kind="report")
        db = tmp_path / "lake.duckdb"
        r = build_runs_index(runs, db_path=db)
        assert r["n_lineage_cycle_edges"] == 2
        assert r["n_lineage_edges"] == 1  # rc→ra 保留
        rows = _edge_rows(db)
        assert rows == [("rc", "ra", "report")]
        # 查询不炸：rc 向上两跳得 ra（rb 方向被拒）
        q = query_lineage(db, "rc", direction="up", hops=3)
        assert q["ok"]
        assert {n["run_id"] for n in q["nodes"]} == {"ra"}
        v = verify_lineage(db)
        assert v["consistent"] is True  # 拒入后无孤儿（ra 在湖）

    def test_split_cycle_edges_self_loop_unit(self):
        kept, rejected = lake_service._split_cycle_edges(
            [("a", "a", "derived"), ("b", "c", "derived")])
        assert kept == [("b", "c", "derived")]
        assert rejected == [("a", "a", "derived")]

    def test_three_node_cycle_and_tail(self):
        edges = [("x", "y", "k"), ("y", "z", "k"), ("z", "x", "k"),
                 ("t", "x", "k")]
        kept, rejected = lake_service._split_cycle_edges(edges)
        assert kept == [("t", "x", "k")]
        assert len(rejected) == 3

    def test_direct_synced_cycle_query_terminates(self, tmp_path):
        """直写桥可造环（绕过建表验环）：深度守卫保证递归 CTE 必终止。"""
        db = tmp_path / "lake.duckdb"
        assert record_lineage_edges("a", ["b"], db_path=db) is True
        assert record_lineage_edges("b", ["a"], db_path=db) is True
        q = query_lineage(db, "a", direction="up", hops=3)
        assert q["ok"]
        assert q["n_edges_walked"] <= 3  # a→b→a→b 深度钳制截断
        assert {n["run_id"] for n in q["nodes"]} == {"b", "a"}


# ---------------------------------------------------------------------------
# 判据 5：性能 sanity（合成湖计时；真湖门值见 runs/w3_phase3/w3b/ 冒烟）
# ---------------------------------------------------------------------------

class TestPerfSanity:
    def test_build_and_query_timing_small_lake(self, tmp_path, monkeypatch,
                                               fast_meta):
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        for i in range(60):
            _mk_run(runs, f"src_{i:03d}", model="mline")
        for i in range(60):
            _mk_run(runs, f"ds_{i:03d}", model="dataset",
                    derived=[f"src_{i:03d}"], kind="dataset")
        db = tmp_path / "lake.duckdb"
        t0 = _dt.datetime.now()
        r = build_runs_index(runs, db_path=db)
        build_s = (_dt.datetime.now() - t0).total_seconds()
        assert r["ok"] and r["n_lineage_edges"] == 60
        assert build_s < 60.0  # 判据 5 门值（2873 目录 <1min 的合成 sanity）
        t1 = _dt.datetime.now()
        q = query_lineage(db, "ds_000", direction="up", hops=3)
        query_s = (_dt.datetime.now() - t1).total_seconds()
        assert q["ok"] and q["nodes"][0]["run_id"] == "src_000"
        assert query_s < 1.0  # 三跳查询 <1s 门值


# ---------------------------------------------------------------------------
# 判据 6：best-effort 钉（写边失败不阻塞主路径，errors/warnings 留痕）
# ---------------------------------------------------------------------------

class _Boom:
    """duckdb 替身：任何属性访问即抛（#139 通道钉法）。"""

    def __getattr__(self, name):
        raise RuntimeError("duckdb 通道故障（钉死）")


class TestBestEffort:
    def test_write_meta_junk_edges_never_raises(self, tmp_path, fast_meta):
        """归一化垃圾边：丢垃圾留 meta（主路径完成），有效边照写。"""
        path = write_meta(tmp_path / "r", {"run_id": "r"},
                          derived_from=[42, {"run_id": ""}, object(),
                                        "good1"])
        meta = json.loads(path.read_text(encoding="utf-8"))
        assert meta["derived_from"] == ["good1"]

    def test_record_lineage_edges_failure_returns_false(self, tmp_path,
                                                        monkeypatch):
        monkeypatch.setitem(sys.modules, "duckdb", _Boom())
        assert record_lineage_edges("c", ["p"],
                                    db_path=tmp_path / "x.duckdb") is False

    def test_record_lineage_edges_noop_cases(self, tmp_path):
        assert record_lineage_edges("", ["p"],
                                    db_path=tmp_path / "x.duckdb") is True
        assert record_lineage_edges("c", ["  ", {"run_id": ""}],
                                    db_path=tmp_path / "x.duckdb") is True
        assert not (tmp_path / "x.duckdb").exists()  # 无事不建库

    def test_record_run_edge_sync_failure_main_flow_ok(self, tmp_path,
                                                       monkeypatch):
        """record_run 可选同步边失败：run 登记照常成功（判据 6 原文：
        run 主流程成功完成+故障留痕）。"""
        monkeypatch.setitem(sys.modules, "duckdb", _Boom())
        from rfauto.infra.run_store import record_run

        ok = record_run(str(tmp_path / "registry.sqlite"),
                        {"run_id": "r1", "model": "m", "status": "done"},
                        derived_from=["p1"])
        assert ok is True
        from rfauto.infra.run_store import list_runs

        assert [r["run_id"] for r in list_runs(str(tmp_path / "registry.sqlite"))] \
            == ["r1"]

    def test_record_lineage_edges_happy_and_idempotent(self, tmp_path):
        db = tmp_path / "lake.duckdb"
        assert record_lineage_edges("c", ["p1", "p2"],
                                    edge_kind="dataset", db_path=db) is True
        assert record_lineage_edges("c", [{"run_id": "p1",
                                           "edge_kind": "dataset"}],
                                    db_path=db) is True
        rows = _edge_rows(db)
        assert rows == [("c", "p1", "dataset"), ("c", "p2", "dataset")]
        v = verify_lineage(db)
        # 索引表未建：verify 报表缺失如实（不算孤儿）
        assert v["ok"] is False and "表缺失" in v["errors"][0]

    def test_rebuild_replays_meta_and_drops_sync_only_edges(self, tmp_path,
                                                            monkeypatch,
                                                            fast_meta):
        """事实源语义：meta 落边的 rebuild 重放存活；仅直写未落 meta 的
        边被 rebuild 冲掉（record_lineage_edges docstring 契约钉）。"""
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        _mk_run(runs, "kid", derived=["pa"], kind="dataset")
        db = tmp_path / "lake.duckdb"
        build_runs_index(runs, db_path=db)
        record_lineage_edges("kid", ["ghost_only"], db_path=db)
        assert len(_edge_rows(db)) == 2
        build_runs_index(runs, db_path=db)
        rows = _edge_rows(db)
        assert rows == [("kid", "pa", "dataset")]


# ---------------------------------------------------------------------------
# 索引 schema 增列 + CLI 叶 + 接线（dataset/calib/report）
# ---------------------------------------------------------------------------

class TestIndexSchemaAndCli:
    def test_new_columns_populated_and_null_honest(self, chain_lake):
        _tmp, db, _b = chain_lake
        q = query_runs_index(db_path=db, limit=10)
        rows = {r["run_id"]: r for r in q["rows"]}
        assert rows["rep01"]["git_sha"] == "git_rep"
        assert rows["rep01"]["render_input_sha256"] is None  # 缺键如实 NULL

    def test_lineage_leaf_registered_and_help_clean(self):
        """+1 叶注册面（CLI 计数链预期 +1，五钉主代理合流更新）+ help
        字符卫生（D-06 全禁门同口径：命令 help 无裸 [ 与 %）。"""
        from typer.main import get_command

        from rfauto.cli.main import app

        cmd = get_command(app)
        lake = cmd.commands["lake"]
        assert "lineage" in lake.commands
        for text in (lake.commands["lineage"].help or "",
                     lake.commands["lineage"].short_help or ""):
            assert "[" not in text
            assert text.replace("%%", "").count("%") == 0

    def test_cli_lineage_json_roundtrip(self, chain_lake):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        _tmp, db, _b = chain_lake
        runner = CliRunner()
        up = runner.invoke(app, ["lake", "lineage", "--run", "rep01",
                                 "--db", str(db), "--format", "json"])
        assert up.exit_code == 0, up.output
        payload = json.loads(up.output)
        assert {n["run_id"] for n in payload["nodes"]} == {"ds01", "calib01"}
        down = runner.invoke(app, ["lake", "lineage", "--run", "calib01",
                                   "--down", "--format", "json",
                                   "--db", str(db)])
        assert down.exit_code == 0, down.output
        payload_down = json.loads(down.output)
        assert {n["run_id"] for n in payload_down["nodes"]} \
            == {"ds01", "rep01"}

    def test_cli_lineage_missing_db_exit_1(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        res = runner.invoke(app, ["lake", "lineage", "--run", "x",
                                  "--db", str(tmp_path / "nope.duckdb"),
                                  "--json"])
        assert res.exit_code == 1
        assert '"ok": false' in res.output


class TestWiring:
    """三调用点接线（dataset/calib/report 各一行传参；边来源=调用方上下文）。"""

    def test_dataset_meta_lineage_edges(self, runs_env):
        """dataset 接线：物化后 runs/datasets/<name>/meta.json 落
        derived_from=source_runs（edge_kind=dataset）；湖 build 后数据集
        节点向上可查到全部 source runs。"""
        pytest.importorskip("pyarrow",
                            reason="物化面需要 dataset extra（pyarrow）")
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(name="w3b_demo", health_gate=False)
        assert r["ok"], r.get("errors")
        dmeta = json.loads((runs_env / "runs" / "datasets" / "w3b_demo"
                            / "meta.json").read_text(encoding="utf-8"))
        assert dmeta["derived_from"] == [
            {"run_id": "run_a", "edge_kind": "dataset"},
            {"run_id": "run_b", "edge_kind": "dataset"},
            {"run_id": "run_c", "edge_kind": "dataset"},
        ]
        db = runs_env / "lake.duckdb"
        build = build_runs_index(runs_env / "runs", db_path=db)
        assert build["ok"] and build["n_lineage_edges"] == 3
        q = query_lineage(db, "w3b_demo", direction="up", hops=3)
        assert {n["run_id"] for n in q["nodes"]} \
            == {"run_a", "run_b", "run_c"}

    def test_dataset_meta_write_failure_non_blocking(self, runs_env,
                                                     monkeypatch):
        """判据 6 接线面：数据集 meta 写失败（目录只读模拟）→ 物化照常
        ok=True + warnings 留痕。"""
        pytest.importorskip("pyarrow",
                            reason="物化面需要 dataset extra（pyarrow）")
        from rfauto.service import dataset_service

        def _boom(*_a, **_kw):
            raise OSError("模拟 meta 目录只读")

        monkeypatch.setattr(run_store, "write_meta", _boom)
        r = dataset_service.materialize_dataset(name="w3b_fail",
                                                health_gate=False)
        assert r["ok"] is True
        assert any("血缘 meta 写入失败" in w for w in r.get("warnings") or [])

    def test_calib_derived_from_passthrough(self, tmp_path, monkeypatch,
                                            fast_meta):
        """calib 接线：derived_from 参数 → meta.json 边（edge_kind=calib）；
        None=零改动现状。"""
        from rfauto.service.calibration_service import calibrate_surrogate

        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(
            "model: mline\n"
            "setup:\n"
            "  freq_range_ghz: [1.0, 5.0]\n"
            "optimization:\n"
            "  params:\n"
            "    w_mm: {low: 0.5, high: 3.0}\n"
            "objectives:\n"
            "  - metric: s11_db_max_in_band\n"
            "    op: max_below\n"
            "    value: -10\n"
            "    band: [1.0, 5.0]\n",
            encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        r = calibrate_surrogate(recipe, sampler="fake", derived_from=["seedrun"])
        assert r["ok"], r.get("errors")
        metas = list((tmp_path / "runs").glob("*/meta.json"))
        assert metas, "校准 run meta 缺失"
        meta = json.loads(metas[0].read_text(encoding="utf-8"))
        assert meta["derived_from"] == [{"run_id": "seedrun",
                                         "edge_kind": "calib"}]
        # None=零改动现状（同秒 run_id 尾码随机——按内容判别不按序）
        r2 = calibrate_surrogate(recipe, sampler="fake")
        assert r2["ok"], r2.get("errors")
        all_metas = [json.loads(p.read_text(encoding="utf-8"))
                     for p in (tmp_path / "runs").glob("*/meta.json")]
        assert len(all_metas) == 2
        with_edge = [m for m in all_metas if "derived_from" in m]
        assert len(with_edge) == 1
        assert with_edge[0]["derived_from"] == [{"run_id": "seedrun",
                                                 "edge_kind": "calib"}]

    def test_report_baseline_run_ids_helper(self):
        """report 接线内核：_baseline_run_ids 只收显式 baseline 引用
        （entries.baseline.run_id + regressions[].baseline_run_id）。"""
        from rfauto.service.sim_ci_service import _baseline_run_ids

        entries = [
            {"recipe": "a", "baseline": {"run_id": "base1"}},
            {"recipe": "b", "baseline": "missing"},
            {"recipe": "c"},
        ]
        regressions = [{"recipe": "a", "baseline_run_id": "base2"},
                       {"recipe": "x"}]
        assert _baseline_run_ids(entries, regressions) == ["base1", "base2"]
        assert _baseline_run_ids(None, None) == []
