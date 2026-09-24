"""C10 GT 补族战役单测（branchline/wilkinson，合成数据钉死，零真机零长跑）。

被测对象：scripts/c10_gt_campaign.py 的纯逻辑
（build_plan / compute_point_metrics / param_fingerprint /
 family_gt_param_tuples / recipe_bounds）与真机面的注入接线
（run_collect fake 冒烟 → 标准 run 产物 → dataset ⑤ 分支成行契约 #251④；
 run_ingest 双集合并 → readiness）。真跑面不在单测范围——OE 真机批量由
主代理排程（本批铁律：禁自行真跑）。

数值口径（#118 合成注入→回收）：合成 (n,3,3) 部分矩阵验证
compute_point_metrics 激励列口径精确回收；单激励未测列置零验证隔离类
指标不产出（不凑数，#314 同族纪律）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

from c10_gt_campaign import (
    FAMILIES,
    build_plan,
    compute_point_metrics,
    done_run_ids,
    existing_eval_index_max,
    family_gt_param_tuples,
    mesh_meta_value,
    param_fingerprint,
    recipe_bounds,
    recipe_spec,
    run_collect,
    run_ingest,
    source_registry_run_ids,
    write_run_products,
)

BOUNDS = {"arm_len_mm": (17.0, 21.0), "series_w_mm": (1.5, 2.5),
          "shunt_w_mm": (0.8, 1.5)}


def _coupler_network(n_f: int = 41, s11: float = 0.1, s21: float = 0.707,
                     s31: float = 0.707, n_ports: int = 3):
    """合成 (n,3,3) 单激励部分矩阵：S11/S21/S31 激励列实值，未测元素置零
    （openems_solver._parse_output 单激励通道同构）。"""
    import skrf

    f_ghz = np.linspace(2.3, 2.5, n_f)
    s = np.zeros((n_f, n_ports, n_ports), dtype=complex)
    s[:, 0, 0] = s11
    s[:, 1, 0] = s21
    if n_ports >= 3:
        s[:, 2, 0] = s31
    return skrf.Network(
        frequency=skrf.Frequency(float(f_ghz[0]), float(f_ghz[-1]), n_f, unit="ghz"),
        s=s, z0=50.0)


class _FakeOEAdapter:
    """OpenEMSOptAdapter 注入替身（fake 冒烟/幂等/失败路径，零真机）。"""

    #: 真实 adapter 的 mesh 观测面对齐（c10 缺省构造不传 → 0.0=auto 哨兵）
    mesh_resolution_mm = 0.0

    def __init__(self, fail_indices: set[int] | None = None, n_ports: int = 3):
        self.fail_indices = fail_indices or set()
        self.n_ports = n_ports
        self.solved: list[dict[str, float]] = []
        self.eval_root = Path("evals")  # 观测面（write 产物 eval_dir 记录用）
        self.last_eval_dir = Path("evals")  # 掩码载体来源（与真实 adapter 对齐）

    def set_variables(self, params: dict[str, float]) -> None:
        self._pending = dict(params)

    def solve(self, timeout_s: float | None = None):
        from rfauto.core.interfaces import SolveReport

        self.solved.append(dict(self._pending))
        if len(self.solved) - 1 in self.fail_indices:
            return SolveReport(success=False, message="fake 注入失败")
        self._net = _coupler_network(n_ports=self.n_ports)
        # engine 原生 sparams.csv（write_run_products 产品契约，c10 探针实证批）
        self.last_eval_dir.mkdir(parents=True, exist_ok=True)
        (self.last_eval_dir / "sparams.csv").write_text(
            "freq_hz,re_S11,im_S11,re_S21,im_S21\n"
            + "".join(f"{2e9 + k * 0.25e9:.1f},0.1,0.0,0.9,0.0\n"
                      for k in range(5)),
            encoding="utf-8")
        return SolveReport(success=True, message="fake ok")

    def get_sparams(self):
        return self._net


class TestPlan:
    def test_deterministic_and_bounds(self):
        p1 = build_plan(BOUNDS, 8, seed=20260922)
        p2 = build_plan(BOUNDS, 8, seed=20260922)
        assert p1 == p2
        assert len(p1) == 8
        for pt in p1:
            for name, (low, high) in BOUNDS.items():
                assert low <= pt["params"][name] <= high

    def test_dedup_against_taken_refills(self):
        plan0 = build_plan(BOUNDS, 8, seed=20260922)
        drop = {param_fingerprint(pt["params"]) for pt in plan0[:3]}
        plan = build_plan(BOUNDS, 8, seed=20260922, taken=drop)
        got = {param_fingerprint(pt["params"]) for pt in plan}
        assert not (drop & got), "查重集内的点必须被剔除"
        assert len(plan) == 8

    def test_plan_points_unique(self):
        plan = build_plan(BOUNDS, 12, seed=20260922)
        fps = [param_fingerprint(pt["params"]) for pt in plan]
        assert len(fps) == len(set(fps))

    def test_rejects_bad_n(self):
        with pytest.raises(ValueError, match="n_points"):
            build_plan(BOUNDS, 0, seed=1)

    def test_param_fingerprint_rounds(self):
        assert (param_fingerprint({"a": 1.0000001})
                == param_fingerprint({"a": 1.0000002}))
        assert (param_fingerprint({"b": 2.0, "a": 1.0})
                == param_fingerprint({"a": 1.0, "b": 2.0}))


class TestRecipeSpec:
    def test_branchline_bounds_and_band_from_recipe(self):
        spec = recipe_spec("branchline")
        assert spec["bounds"] == {"arm_len_mm": (17.0, 21.0),
                                  "series_w_mm": (1.5, 2.5),
                                  "shunt_w_mm": (0.8, 1.5)}
        assert spec["freq_range_ghz"] == (2.3, 2.5)
        assert spec["band_ghz"] == (2.3, 2.5)

    def test_wilkinson_freq_range_from_recipe(self):
        spec = recipe_spec("wilkinson")
        assert spec["freq_range_ghz"] == (1.5, 3.5)
        assert spec["band_ghz"] == (2.3, 2.5)

    def test_recipe_bounds_missing_low_errors(self):
        with pytest.raises(ValueError, match="low/high"):
            recipe_bounds({"optimization": {"params": {"w": {"low": 1.0}}}})


class TestComputePointMetrics:
    def test_excitation_columns_recovered(self):
        net = _coupler_network(s11=0.1, s21=1.0 / np.sqrt(2.0), s31=0.5)
        metrics, notes = compute_point_metrics(net, (2.3, 2.5))
        assert metrics["s11_db_max_in_band"] == pytest.approx(-20.0, abs=1e-6)
        assert metrics["s11_db_min_in_band"] == pytest.approx(-20.0, abs=1e-6)
        assert metrics["s21_db_mean_in_band"] == pytest.approx(-3.0103, abs=1e-4)
        assert metrics["s31_db_mean_in_band"] == pytest.approx(-6.0206, abs=1e-3)
        assert notes == []

    def test_two_port_network_skips_s31(self):
        net = _coupler_network(n_ports=2)
        metrics, notes = compute_point_metrics(net, (2.3, 2.5))
        assert "s31_db_mean_in_band" not in metrics
        assert len(notes) == 1 and "s31_skipped" in notes[0]

    def test_band_filter_narrows_stats(self):
        # 频点 2.3..2.5 取带 [2.3,2.4]：S11 斜坡构造，带内 max 不同于全带
        import skrf

        n_f = 21
        s = np.zeros((n_f, 3, 3), dtype=complex)
        s[:, 0, 0] = np.linspace(0.01, 0.9, n_f)  # 全带 max 在高频端
        net = skrf.Network(frequency=skrf.Frequency(2.3, 2.5, n_f, unit="ghz"),
                           s=s, z0=50.0)
        full, _ = compute_point_metrics(net, (2.3, 2.5))
        half, _ = compute_point_metrics(net, (2.3, 2.4))
        assert full["s11_db_max_in_band"] > half["s11_db_max_in_band"]


class TestFamilyGTParamTuples:
    def _write_parquet(self, path, rows):
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({
            "run_id": [r["run_id"] for r in rows],
            "model": [r["model"] for r in rows],
            "adapter": [r["adapter"] for r in rows],
            "params_json": [r["params_json"] for r in rows],
        })
        pq.write_table(table, path)

    def test_gt_rows_kept_fake_and_other_model_excluded(self, tmp_path):
        pq_path = tmp_path / "points.parquet"
        self._write_parquet(pq_path, [
            {"run_id": "r1", "model": "branchline_coupler", "adapter": "hfss",
             "params_json": json.dumps({"arm_len_mm": 20.0, "series_w_mm": 1.87,
                                        "shunt_w_mm": 1.11})},
            {"run_id": "r2", "model": "branchline_coupler", "adapter": "fake",
             "params_json": json.dumps({"arm_len_mm": 19.0})},
            {"run_id": "r3", "model": "patch_antenna", "adapter": "hfss",
             "params_json": json.dumps({"arm_len_mm": 18.0})},
            {"run_id": "r4", "model": "branchline_coupler",
             "adapter": "calibration:openems",
             "params_json": json.dumps({"arm_len_mm": 20.0, "series_w_mm": 1.87,
                                        "shunt_w_mm": 1.12})},
        ])
        out = family_gt_param_tuples(pq_path, "branchline_coupler")
        assert len(out) == 2  # r2 fake、r3 异族排除；两条 GT 元组各自保留
        assert (("arm_len_mm", 20.0), ("series_w_mm", 1.87), ("shunt_w_mm", 1.11)) in out
        assert (("arm_len_mm", 20.0), ("series_w_mm", 1.87), ("shunt_w_mm", 1.12)) in out

    def test_bounds_names_filter(self, tmp_path):
        pq_path = tmp_path / "points.parquet"
        self._write_parquet(pq_path, [
            {"run_id": "r1", "model": "wilkinson_power_divider", "adapter": "hfss",
             "params_json": json.dumps({"arm_len_mm": 20.0, "f0_ghz": 2.4})},
        ])
        out = family_gt_param_tuples(pq_path, "wilkinson_power_divider",
                                     bounds_names={"arm_len_mm"})
        assert out == {(("arm_len_mm", 20.0),)}

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            family_gt_param_tuples(tmp_path / "nope.parquet", "x")


class TestMeshMetaValue:
    """meta.mesh_resolution_mm 落痕口径钉（#117 邻形：0.0 哨兵禁当数值落盘）。"""

    def test_sentinel_forms(self):
        assert mesh_meta_value(None) == "unknown"
        assert mesh_meta_value(0.0) == "auto"          # 自动档哨兵→字符串注记
        assert mesh_meta_value(0.0) != 0.0
        assert mesh_meta_value(0.5) == 0.5             # 实测值原样
        assert mesh_meta_value("auto") == "auto"       # 字符串透传

    def test_meta_carries_annotation_not_zero(self, tmp_path):
        """write_run_products 落盘形态：替身 0.0（auto 档）→ meta 值 "auto"。"""
        family = "branchline"
        params = {"arm_len_mm": 20.0, "series_w_mm": 1.87, "shunt_w_mm": 1.11}
        eval_dir = tmp_path / "evals" / "eval_0001"
        eval_dir.mkdir(parents=True)
        (eval_dir / "sparams.csv").write_text(
            "freq_hz,re_S11,im_S11,re_S21,im_S21\n"
            + "".join(f"{2e9 + k * 0.25e9:.1f},0.1,0.0,0.9,0.0\n"
                      for k in range(5)),
            encoding="utf-8")
        run_dir = tmp_path / "runs" / "20260922_000000_c10a03"
        (run_dir / "results").mkdir(parents=True)
        write_run_products(run_dir, family, params, _coupler_network(),
                           wall_s=1.0, eval_dir=str(eval_dir),
                           metrics={}, notes=[],
                           freq_range_ghz=(2.3, 2.5), band_ghz=(2.3, 2.5),
                           bounds=BOUNDS, study=FAMILIES[family]["study"],
                           mesh_resolution_mm=0.0)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["mesh_resolution_mm"] == "auto"

        run_dir2 = tmp_path / "runs" / "20260922_000000_c10a04"
        (run_dir2 / "results").mkdir(parents=True)
        write_run_products(run_dir2, family, params, _coupler_network(),
                           wall_s=1.0, eval_dir=str(eval_dir),
                           metrics={}, notes=[],
                           freq_range_ghz=(2.3, 2.5), band_ghz=(2.3, 2.5),
                           bounds=BOUNDS, study=FAMILIES[family]["study"])
        meta2 = json.loads((run_dir2 / "meta.json").read_text(encoding="utf-8"))
        assert meta2["mesh_resolution_mm"] == "unknown"   # 无观测面如实 unknown


class TestExistingEvalIndexMax:
    """A-02 resume 防覆盖：factory 以既有 eval_NNNN 最大序号接续编号。"""

    def test_scans_existing_dirs(self, tmp_path):
        root = tmp_path / "evals"
        (root / "eval_0001").mkdir(parents=True)
        (root / "eval_0003").mkdir()
        (root / "eval_0002").mkdir()
        (root / "eval_0007").write_text("not a dir", encoding="utf-8")  # 文件不计
        (root / "points_index.json").write_text("{}", encoding="utf-8")
        assert existing_eval_index_max(root) == 3

    def test_missing_or_empty_root_is_zero(self, tmp_path):
        assert existing_eval_index_max(tmp_path / "nope") == 0
        root = tmp_path / "empty"
        root.mkdir()
        assert existing_eval_index_max(root) == 0


class TestWriteRunProducts:
    def test_products_satisfy_run_once_collect_contract(self, tmp_path):
        """⑤ 分支成行契约钉（#251④）：单点产物 → _collect_run_points 恰 1 行，
        params 键集 = optimization.params，provenance 带 touchstone/n_ports。"""
        from rfauto.service.dataset_service import _collect_run_points

        family = "branchline"
        params = {"arm_len_mm": 20.0, "series_w_mm": 1.87, "shunt_w_mm": 1.11}
        net = _coupler_network()
        # eval_dir 语义=最近一次 solve 的评估目录，engine sparams.csv 必须在
        eval_dir = tmp_path / "evals" / "eval_0001"
        eval_dir.mkdir(parents=True)
        (eval_dir / "sparams.csv").write_text(
            "freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23\n"
            + "".join(f"{2e9 + k * 0.25e9:.1f},0.1,0.0,0.9,0.0,0.7,0.0,0.7,0.0\n"
                      for k in range(5)),
            encoding="utf-8")
        run_dir = tmp_path / "runs" / "20260922_000000_c10a01"
        (run_dir / "results").mkdir(parents=True)
        metrics = {"s11_db_max_in_band": -20.0, "s11_db_min_in_band": -20.0,
                   "s21_db_mean_in_band": -3.01, "s31_db_mean_in_band": -3.01}
        write_run_products(run_dir, family, params, net, wall_s=36.0,
                           eval_dir=str(eval_dir), metrics=metrics, notes=[],
                           freq_range_ghz=(2.3, 2.5), band_ghz=(2.3, 2.5),
                           bounds=BOUNDS, study=FAMILIES[family]["study"])
        assert (run_dir / "recipe.snapshot.yaml").exists()
        # 单激励通道 (n,3,3) → .s3p（#248 扩展名契约）
        assert (run_dir / "results" / "params.s3p").exists()
        # engine 原生掩码载体随 run 归档（G11 健康门互易 UNKNOWN 路径）
        assert (run_dir / "results" / "sparams.csv").exists()
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["status"] == "done"
        assert meta["model"] == "branchline_coupler"
        assert meta["adapter"] == "openems"

        points, errors, n_nf = _collect_run_points(run_dir)
        assert n_nf == 0
        assert len(points) == 1, errors
        pt = points[0]
        assert pt["params"] == params
        assert pt["source"] == "run_once"
        assert pt["provenance_extra"]["n_ports"] == 3
        assert pt["provenance_extra"]["run_id"] == run_dir.name
        assert pt["provenance_extra"]["touchstone_path"].endswith("params.s3p")

    def test_missing_eval_csv_raises(self, tmp_path):
        """engine sparams.csv 缺失 → 抛错（掩码载体是产品契约，禁止 Touchstone
        单飞——c10 探针实证：无掩码全对查互易必假阳性拦批）。"""
        family = "branchline"
        params = {"arm_len_mm": 20.0, "series_w_mm": 1.87, "shunt_w_mm": 1.11}
        run_dir = tmp_path / "runs" / "20260922_000000_c10a02"
        (run_dir / "results").mkdir(parents=True)
        empty_eval = tmp_path / "evals" / "eval_0002"
        empty_eval.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match=r"sparams\.csv"):
            write_run_products(run_dir, family, params, _coupler_network(),
                               wall_s=1.0, eval_dir=str(empty_eval),
                               metrics={}, notes=[],
                               freq_range_ghz=(2.3, 2.5), band_ghz=(2.3, 2.5),
                               bounds=BOUNDS,
                               study=FAMILIES[family]["study"])


class TestRunCollectFakeSmoke:
    """首点 fake 冒烟（本批铁律的离线验证面）：零真机、零 runs/ 污染、零真锁。"""

    def _seed_plan(self, tmp_root: Path, family: str, n_points: int = 4,
                   seed: int = 20260922) -> Path:
        spec = recipe_spec(family)
        points = build_plan(spec["bounds"], n_points, seed)
        plan = {
            "family": family, "model": FAMILIES[family]["model"],
            "source_registry": "wp34_registry_20260916",
            "param_space": {k: [float(v[0]), float(v[1])]
                            for k, v in spec["bounds"].items()},
            "freq_range_ghz": list(spec["freq_range_ghz"]),
            "band_ghz": list(spec["band_ghz"]),
            "seed": seed, "n_points": n_points, "started_at": "t0",
            "points": points,
        }
        root = tmp_root / "work"
        root.mkdir(parents=True)
        (root / "plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
        return tmp_root

    def _probe_ok(self, calls: list[list[str]]):
        def _materialize(run_ids, name, **_kw):
            calls.append(list(run_ids))
            return {"ok": True, "n_rows": len(run_ids)}
        return _materialize

    def test_first_point_collects_probe_and_index(self, tmp_path, monkeypatch):
        family = "branchline"
        repo = self._seed_plan(tmp_path, family)
        monkeypatch.chdir(repo)  # cwd 守卫：repo 根 = tmp 根
        probes: list[list[str]] = []
        adapter = _FakeOEAdapter()
        rc = run_collect(repo, family, n_points=4, max_points=1,
                         adapter_factory=lambda: adapter,
                         materialize_fn=self._probe_ok(probes),
                         work_root=repo / "work", use_shared_lock=False)
        assert rc == 0
        assert len(adapter.solved) == 1
        assert probes and len(probes[0]) == 1, "首点 ingest 探针必须 1 行成行"
        index = json.loads((repo / "work" / "points_index.json")
                           .read_text(encoding="utf-8"))
        assert index["pt00"]["status"] == "done"
        rid = index["pt00"]["rid"]
        run_dir = repo / "runs" / rid
        assert (run_dir / "results" / "params.s3p").exists()
        assert (run_dir / "meta.json").exists()
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        # mesh 哨兵落痕（#117 邻形）：替身 0.0=自动档 → "auto" 字符串非数值
        assert meta["mesh_resolution_mm"] == "auto"
        # 变量真传给了适配器（params 三键全量）
        assert adapter.solved[0].keys() == {"arm_len_mm", "series_w_mm", "shunt_w_mm"}

    def test_resume_skips_done_no_resolve(self, tmp_path, monkeypatch):
        family = "wilkinson"
        repo = self._seed_plan(tmp_path, family)
        monkeypatch.chdir(repo)
        probes: list[list[str]] = []
        adapter = _FakeOEAdapter()
        common = dict(n_points=4, adapter_factory=lambda: adapter,
                      materialize_fn=self._probe_ok(probes),
                      work_root=repo / "work", use_shared_lock=False)
        assert run_collect(repo, family, max_points=1, **common) == 0
        index1 = json.loads((repo / "work" / "points_index.json")
                            .read_text(encoding="utf-8"))
        rid1 = index1["pt00"]["rid"]
        solved1 = list(adapter.solved)
        # 第二次调用：pt00 done 幂等跳过（不重解、rid 不变），继续采集 pt01
        assert run_collect(repo, family, max_points=1, **common) == 0
        index2 = json.loads((repo / "work" / "points_index.json")
                            .read_text(encoding="utf-8"))
        assert index2["pt00"]["rid"] == rid1
        assert index2["pt01"]["status"] == "done"
        assert len(adapter.solved) == len(solved1) + 1
        assert adapter.solved[-1] == index2["pt01"]["params"]

    def test_failed_point_recorded_and_continues(self, tmp_path, monkeypatch):
        family = "branchline"
        repo = self._seed_plan(tmp_path, family)
        monkeypatch.chdir(repo)
        probes: list[list[str]] = []
        adapter = _FakeOEAdapter(fail_indices={0})
        rc = run_collect(repo, family, n_points=4, max_points=2,
                         adapter_factory=lambda: adapter,
                         materialize_fn=self._probe_ok(probes),
                         work_root=repo / "work", use_shared_lock=False)
        assert rc == 0
        index = json.loads((repo / "work" / "points_index.json")
                           .read_text(encoding="utf-8"))
        assert index["pt00"]["status"] == "failed"
        # 失败点不入探针：首点探针顺延到第一个成功点（pt01）
        assert probes and len(probes[0]) == 1
        assert index["pt01"]["status"] == "done"

    def test_plan_mismatch_rejects(self, tmp_path, monkeypatch):
        family = "branchline"
        repo = self._seed_plan(tmp_path, family, n_points=4)
        monkeypatch.chdir(repo)
        rc = run_collect(repo, family, n_points=5,
                         adapter_factory=lambda: _FakeOEAdapter(),
                         materialize_fn=self._probe_ok([]),
                         work_root=repo / "work", use_shared_lock=False)
        assert rc == 2

    def test_cwd_guard_rejects(self, tmp_path):
        family = "branchline"
        repo = self._seed_plan(tmp_path, family)
        # cwd 仍是仓库根 ≠ tmp repo → 拒跑（run_dir 相对锚保护，#144 同族）
        rc = run_collect(repo, family, adapter_factory=lambda: _FakeOEAdapter(),
                         materialize_fn=self._probe_ok([]),
                         work_root=repo / "work", use_shared_lock=False)
        assert rc == 2


class TestRunIngest:
    def test_merges_source_and_campaign_runs(self, tmp_path, monkeypatch):
        family = "branchline"
        index = {
            "pt00": {"status": "done", "rid": "r_c10_b"},
            "pt01": {"status": "failed", "rid": "r_dead"},
        }
        root = tmp_path / "work"
        root.mkdir(parents=True)
        (root / "points_index.json").write_text(
            json.dumps(index), encoding="utf-8")
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text(
            "source_runs:\n  - run_id: r_old_a\n  - run_id: r_old_b\n",
            encoding="utf-8")
        seen: dict[str, Any] = {}

        def _materialize(run_ids, name, **kw):
            seen["run_ids"], seen["name"], seen["kw"] = list(run_ids), name, kw
            return {"ok": True, "name": name, "n_rows": 3}

        def _readiness(name, **_kw):
            seen["readiness_model"] = name
            return {"ok": True, "per_model": {FAMILIES[family]["model"]: 35}}

        monkeypatch.chdir(tmp_path)
        rc = run_ingest(family, manifest_path=manifest,
                        readiness_fn=_readiness, materialize_fn=_materialize,
                        work_root=root)
        assert rc == 0
        assert seen["run_ids"] == ["r_c10_b", "r_old_a", "r_old_b"]  # done ∪ source，failed 不入
        assert seen["name"] == "registry_20260922_branchline"
        assert seen["kw"].get("health_gate") is True
        assert seen["readiness_model"] == "registry_20260922_branchline"
        out = json.loads((root / "readiness.json").read_text(encoding="utf-8"))
        assert out["n_campaign_runs"] == 1
        assert out["n_source_runs"] == 2

    def test_no_done_points_returns_2(self, tmp_path):
        root = tmp_path / "work"
        root.mkdir(parents=True)
        assert run_ingest("branchline", work_root=root) == 2

    def test_source_manifest_without_source_runs_raises(self, tmp_path):
        bad = tmp_path / "m.yaml"
        bad.write_text("source_runs: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="source_runs"):
            source_registry_run_ids(bad)


class TestDoneRunIds:
    def test_sorted_done_only(self):
        index = {
            "pt01": {"status": "done", "rid": "rb"},
            "pt00": {"status": "done", "rid": "ra"},
            "pt02": {"status": "failed", "rid": "rc"},
        }
        assert done_run_ids(index) == ["ra", "rb"]


class TestDefaultAdapterFactory:
    """缺省 factory 契约钉（round5 C-F2）：GT 采集必须新鲜 solve——
    OpenEMSOptAdapter 显式 ``cache=False``。缓存命中即早退（openems_solver
    _load_cached）不执行渲染脚本 → 新 eval_dir 无 sparams.csv →
    write_run_products 抛 FileNotFoundError，成功的（缓存）点被判假失败；
    且缺省 cache 跟随 RFAUTO_CACHE 环境（缺省开），必须显式压住。"""

    def test_openems_adapter_constructed_with_cache_false(self, monkeypatch):
        import c10_gt_campaign as c10
        from rfauto.adapters import openems_optimizer_adapter as oea_mod

        captured: dict[str, Any] = {}

        def _spy(freq_range_ghz, **kwargs):
            captured["freq"] = freq_range_ghz
            captured["kwargs"] = dict(kwargs)
            return object()

        monkeypatch.setattr(oea_mod, "OpenEMSOptAdapter", _spy)
        c10._default_adapter_factory("branchline", (2.3, 2.5), 900.0,
                                     Path("evals"))
        assert captured["kwargs"]["cache"] is False
        assert (captured["kwargs"]["template"]
                == FAMILIES["branchline"]["template"])
        assert captured["freq"] == (2.3, 2.5)
        assert captured["kwargs"]["eval_index_offset"] == 0   # 全新根接续 0

    def test_openems_adapter_resume_continues_existing_max(self, tmp_path,
                                                           monkeypatch):
        """A-02：既有 eval_0001..eval_0003 归档 → 新会话 offset=3 接续，
        eval_0001 起的既有归档不被新会话 _n 回卷整目录覆盖。"""
        import c10_gt_campaign as c10
        from rfauto.adapters import openems_optimizer_adapter as oea_mod

        evals = tmp_path / "evals"
        for i in (1, 2, 3):
            (evals / f"eval_{i:04d}").mkdir(parents=True)
        captured: dict[str, Any] = {}

        def _spy(freq_range_ghz, **kwargs):
            captured["kwargs"] = dict(kwargs)
            return object()

        monkeypatch.setattr(oea_mod, "OpenEMSOptAdapter", _spy)
        c10._default_adapter_factory("wilkinson", (1.5, 3.5), 900.0, evals)
        assert captured["kwargs"]["eval_index_offset"] == 3
