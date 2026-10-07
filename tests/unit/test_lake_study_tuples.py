"""DA-1（round4 中件包三）study 元组抽取+湖索引首建面测试。

判据（任务书预声明）：
- extract_study_tuple：完整 meta 全字段回收逐位；缺字段→None 如实
  （不臆测）；#320 优先级（params>calib_params>design_params 的
  template/study 字段面，嵌套优先于顶层兜底）；budget=trials 实测
  条数（含 0）否则 meta 预算字段（int 收敛拒 bool）。
- build_runs_index 小规模合成树（tmp 目录，不碰真 runs）→
  query_runs_index 回读一致 → study_tuples_from_index 聚合正确
  （同 study 两 run 合并：templates 并集+最新 template 口径）。
- 幂等：同树建两次行数一致/不重复（drop-create 重建）。
- build_index_cli_entry 统计信封（runs_scanned/rows/duration_s）。
- 真索引冒烟：skipif runs/.lake_index.duckdb 不存在（防他机红）——
  存在时只读断言行数>0（禁写真 runs/，#328 证据面只读）。

chdir 隔离零污染（#144）；duckdb 缺失诚实 skip（dataset extra）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="湖索引需要 dataset extra（duckdb）")

from rfauto.service.lake_service import (
    build_index_cli_entry,
    build_runs_index,
    default_lake_index_db_path,
    extract_study_tuple,
    query_runs_index,
    study_tuples_from_index,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(model: str, adapter: str, study: str | None, ts: str,
          **extra: object) -> dict:
    body: dict = {"run_id": "x", "model": model, "adapter": adapter,
                  "status": "done", "timestamp": ts, "seed": 42}
    if study is not None:
        body["study_name"] = study
    body.update(extra)
    return body


@pytest.fixture
def study_env(tmp_path, monkeypatch):
    """合成 runs/ 湖：同 study 双 run（异模板）+独立 study+无 study 行
    +无 meta 目录。chdir 隔离（#144），索引库落 tmp。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    _write_json(root / "camp_a" / "pt1" / "meta.json",
                _meta("mline", "fake", "s_a", "2026-09-01T10:00:00+00:00"))
    _write_json(root / "camp_a" / "pt2" / "meta.json",
                _meta("cpw", "openems", "s_a", "2026-09-05T10:00:00+00:00"))
    _write_json(root / "solo" / "meta.json",
                _meta("patch_antenna", "hfss", "s_b",
                      "2026-09-10T08:00:00+00:00"))
    # 无 study_name 的 run（聚合面如实跳过）
    _write_json(root / "nostudy" / "meta.json",
                _meta("ghost", "fake", None, "2026-09-11T00:00:00+00:00"))
    # 纯工具目录（无 meta）
    (root / "datasets").mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# extract_study_tuple：字段口径
# ---------------------------------------------------------------------------

class TestExtractStudyTuple:
    def test_full_tuple_roundtrip(self):
        """完整 meta 全字段回收逐位（trials 给出时 budget=实测条数）。"""
        objective = {"metric": "s11_db", "op": "max_below", "value": -15}
        meta = {
            "study_name": "tune_wilkinson_pd_v1_957c4adb",
            "model": "wilkinson_power_divider",
            "adapter": "fake", "status": "done",
            "objective": objective,
        }
        trials = [{"cost": 3.9}, {"cost": 2.1}, {"cost": 1.5}]
        got = extract_study_tuple(meta, trials)
        assert got == {
            "study": "tune_wilkinson_pd_v1_957c4adb",
            "template": "wilkinson_power_divider",
            "target": objective,   # 原样透传（同一对象语义）
            "budget": 3,
        }
        assert got["target"] is objective

    def test_missing_fields_all_none(self):
        """缺字段→None 如实（空 meta/非 dict meta 不臆测）。"""
        assert extract_study_tuple({}) == {
            "study": None, "template": None, "target": None,
            "budget": None}
        # 非 dict 输入收敛（#140 惯例）：全 None 不抛
        assert extract_study_tuple(None)["study"] is None
        # 真实 meta 形态（2026-09-26 实测）：无 objective/预算字段 →
        # target/budget None 如实，study/template 正常回收
        real_like = {
            "study_name": "tune_x_957c4adb",
            "model": "wilkinson_power_divider",
            "adapter": "fake", "status": "done",
            "metrics": {"s11_db_max_in_band": -11.3},
        }
        got = extract_study_tuple(real_like)
        assert got["study"] == "tune_x_957c4adb"
        assert got["template"] == "wilkinson_power_divider"
        assert got["target"] is None and got["budget"] is None

    def test_template_priority_chain_320(self):
        """#320 优先级：params>calib_params>design_params 嵌套面 →
        顶层 template → 顶层 model 兜底。"""
        # 三处并存：params 胜
        m3 = {"model": "m_top",
              "params": {"template": "t_params"},
              "calib_params": {"template": "t_calib"},
              "design_params": {"template": "t_design"}}
        assert extract_study_tuple(m3)["template"] == "t_params"
        # 缺 params：calib_params 胜
        m2 = {"model": "m_top",
              "calib_params": {"template": "t_calib"},
              "design_params": {"template": "t_design"}}
        assert extract_study_tuple(m2)["template"] == "t_calib"
        # 仅 design_params
        m1 = {"model": "m_top",
              "design_params": {"template": "t_design"}}
        assert extract_study_tuple(m1)["template"] == "t_design"
        # 嵌套全缺：顶层 template 优先于 model
        m0 = {"template": "t_top", "model": "m_fallback"}
        assert extract_study_tuple(m0)["template"] == "t_top"
        # 全缺：model 兜底（真实主源）
        assert extract_study_tuple({"model": "m_fallback"})["template"] \
            == "m_fallback"

    def test_study_priority_chain(self):
        """study 同口径：study_name 顶层主源 → 嵌套面 → study 顶层。"""
        assert extract_study_tuple({"study_name": "s_main"})["study"] \
            == "s_main"
        assert extract_study_tuple(
            {"params": {"study_name": "s_nested"}})["study"] == "s_nested"
        assert extract_study_tuple(
            {"study": "s_top"})["study"] == "s_top"
        assert extract_study_tuple({"study_name": None, "study": None})[
            "study"] is None

    def test_budget_from_trials_measured(self):
        """budget=trials 实测条数（非空/空列表皆实测口径，#144 反面）。"""
        assert extract_study_tuple({}, trials=[{"n": i} for i in range(10)])[
            "budget"] == 10
        # 空 trials 列表=真实测量（0 条），不是缺省
        assert extract_study_tuple({}, trials=[])[
            "budget"] == 0
        # trials 非 list（坏输入）：按未给出处理，落 meta 预算面
        assert extract_study_tuple({"n_trials": 7},
                                   trials="bad")["budget"] == 7

    def test_budget_from_meta_fields_bool_reject(self):
        """无 trials：meta 预算字段 n_trials/budget/max_trials 依次回退；
        int 收敛拒 bool（#df7+⑯）；嵌套面兜底。"""
        assert extract_study_tuple({"n_trials": 30})["budget"] == 30
        assert extract_study_tuple({"budget": 12})["budget"] == 12
        assert extract_study_tuple({"max_trials": 5})["budget"] == 5
        # 整值 float 收敛
        assert extract_study_tuple({"n_trials": 12.0})["budget"] == 12
        # bool 拒收：True 不是 1，回退下一候选
        assert extract_study_tuple({"n_trials": True, "budget": 9})[
            "budget"] == 9
        assert extract_study_tuple({"n_trials": True})["budget"] is None
        # 非整数值如实 None
        assert extract_study_tuple({"n_trials": "many"})["budget"] is None
        assert extract_study_tuple({"n_trials": 1.5})["budget"] is None
        # 顶层全缺：嵌套面兜底
        assert extract_study_tuple(
            {"params": {"max_trials": 8}})["budget"] == 8


# ---------------------------------------------------------------------------
# 索引面：build → query 回读 → study_tuples 聚合 → 幂等
# ---------------------------------------------------------------------------

class TestStudyIndexIntegration:
    def test_build_query_roundtrip(self, study_env):
        """合成树建索引 → 行数正确 → query_runs_index 回读字段一致。"""
        db = study_env / "lake.duckdb"
        r = build_runs_index(study_env / "runs", db_path=db)
        assert r["ok"], r.get("errors")
        # 6 目录全入索引：camp_a + pt1 + pt2 + solo + nostudy + datasets
        assert r["n_rows"] == 6
        assert r["n_meta_rows"] == 4
        q = query_runs_index(db_path=db)
        assert q["ok"] and q["n_rows"] == 6
        rows = {row["path"]: row for row in q["rows"]}
        pt1 = rows["camp_a/pt1"]
        assert pt1["template"] == "mline" and pt1["adapter"] == "fake"
        assert pt1["study"] == "s_a"
        assert pt1["created_ts"] == "2026-09-01T10:00:00+00:00"
        assert str(pt1["created_date"]) == "2026-09-01"
        assert rows["nostudy"]["study"] is None  # 无 study 行如实 NULL
        assert rows["datasets"]["has_meta"] is False

    def test_study_tuples_aggregation(self, study_env):
        """聚合：同 study 两 run 合并（templates 并集+最新 template），
        无 study 行跳过，结果按 study 名排序。"""
        db = study_env / "lake.duckdb"
        assert build_runs_index(study_env / "runs", db_path=db)["ok"]
        tuples = study_tuples_from_index(db)
        assert [t["study"] for t in tuples] == ["s_a", "s_b"]
        s_a = tuples[0]
        assert s_a["n_runs"] == 2
        assert s_a["templates"] == ["cpw", "mline"]      # 并集排序
        assert s_a["adapters"] == ["fake", "openems"]
        # 最新口径：pt2（2026-09-05）比 pt1（2026-09-01）新
        assert s_a["template"] == "cpw"
        assert s_a["last_created_ts"] == "2026-09-05T10:00:00+00:00"
        assert s_a["last_run_id"] == "pt2"
        s_b = tuples[1]
        assert s_b["n_runs"] == 1 and s_b["templates"] == ["patch_antenna"]
        # 无 study 行不参与（2+1=3）
        assert sum(t["n_runs"] for t in tuples) == 3

    def test_index_view_target_budget_none_schema(self, study_env):
        """索引视图 target/budget 恒 None（索引无 objective/预算列），
        键面稳定供 DA-2 消费；run 级补全走 extract_study_tuple。"""
        db = study_env / "lake.duckdb"
        assert build_runs_index(study_env / "runs", db_path=db)["ok"]
        for t in study_tuples_from_index(db):
            assert t["target"] is None and t["budget"] is None
            assert {"study", "template", "templates", "adapters",
                    "target", "budget", "n_runs", "last_run_id",
                    "last_created_ts"} <= set(t)

    def test_no_study_rows_returns_empty(self, tmp_path, monkeypatch):
        """全部行无 study 名 → 空列表如实（不报错不臆造）。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _write_json(root / "r1" / "meta.json",
                    _meta("ghost", "fake", None, "2026-09-01T00:00:00+00:00"))
        db = tmp_path / "lake.duckdb"
        assert build_runs_index(root, db_path=db)["ok"]
        assert study_tuples_from_index(db) == []

    def test_missing_db_raises(self, tmp_path):
        """库不存在 → FileNotFoundError 显式（勿与"无 study"混淆）。"""
        with pytest.raises(FileNotFoundError, match="build_runs_index"):
            study_tuples_from_index(tmp_path / "nope.duckdb")

    def test_rebuild_idempotent_no_dup(self, study_env):
        """幂等：同树建两次行数一致/内容不重复（drop-create 重建）。"""
        db = study_env / "lake.duckdb"
        r1 = build_runs_index(study_env / "runs", db_path=db)
        r2 = build_runs_index(study_env / "runs", db_path=db)
        assert r1["ok"] and r2["ok"]
        assert r1["n_rows"] == r2["n_rows"] == 6
        q = query_runs_index(db_path=db)
        assert q["n_rows"] == 6  # 无残留重复
        assert len(study_tuples_from_index(db)) == 2


# ---------------------------------------------------------------------------
# build_index_cli_entry：统计信封
# ---------------------------------------------------------------------------

class TestBuildIndexCliEntry:
    def test_stats_envelope(self, study_env):
        """薄包装统计键：runs_scanned=枚举目录数、rows=入表行数、
        duration_s>=0，db_path 落指定路径。"""
        db = study_env / "lake.duckdb"
        r = build_index_cli_entry(study_env / "runs", db_path=db)
        assert r["ok"], r.get("errors")
        assert r["runs_scanned"] == 6
        assert r["rows"] == 6
        assert r["duration_s"] >= 0
        assert r["db_path"] == str(db)
        assert r["n_meta_rows"] == 4

    def test_default_db_path_and_missing_runs(self, tmp_path, monkeypatch):
        """缺省库路径=runs/.lake_index.duckdb；runs 目录缺失如实零值
        不建库。"""
        monkeypatch.chdir(tmp_path)
        r = build_index_cli_entry(tmp_path / "nope")
        assert r["ok"] and r["rows"] == 0 and r["runs_scanned"] == 0
        assert "runs 目录不存在" in (r.get("note") or "")
        assert Path(r["db_path"]).as_posix() == "runs/.lake_index.duckdb"
        assert default_lake_index_db_path().as_posix() == \
            "runs/.lake_index.duckdb"
        assert not (tmp_path / "runs" / ".lake_index.duckdb").exists()


# ---------------------------------------------------------------------------
# 真索引冒烟（只读；skipif 防他机红）
# ---------------------------------------------------------------------------

class TestRealIndexSmoke:
    def test_real_lake_index_rows_positive(self):
        """真 runs/.lake_index.duckdb 存在时：只读断言行数>0 且 study
        聚合面可出（禁写真 runs/，#328 证据面只读）。"""
        db = _REPO_ROOT / "runs" / ".lake_index.duckdb"
        if not db.exists():
            pytest.skip("真索引未建（runs/.lake_index.duckdb 缺席）")
        q = query_runs_index(db_path=db, limit=200)
        assert q["ok"], q.get("errors")
        assert q["n_rows"] > 0
        tuples = study_tuples_from_index(db)
        assert isinstance(tuples, list)
        assert all(t["n_runs"] >= 1 for t in tuples)
