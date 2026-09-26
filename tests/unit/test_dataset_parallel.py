"""F2（df7）物化并行化判据测试：serial vs n_workers 并行**逐位一致**。

规格 F2 步骤 4(a) 预声明判据：构造多 run 临时战役目录 → serial 与
n_workers=4 的物化结果 == 断言，含行序。战役覆盖全部收集通道：

- ① trials ×2（同 study/seed 共享同参点 → 去重路径）
- ② calibration/samples.json（cost NULL 路径）
- ③ surrogate_loop best / ④ autotune best
- ⑤ run_once（recipe.snapshot.yaml + results/metrics.json →
  provenance_extra 补 run_id 路径）
- 非有限值整点拦截（NaN/Infinity 字面量，计数路径）
- 无产物空 run（skipped_runs 路径）+ G11 unhealthy run（禁入路径，
  skrf 造无源性违例 Touchstone）
- 干扰目录（无 meta.json，不入 target_ids）

对比口径：结果信封除易变键（name/created_at/产物路径）外全字段相等；
Parquet 行**全列含行序**逐位相等（provenance_json 中的 materialized_at
是物化时刻戳、两次物化必然不同——解析后剔除该键再逐行比对，并另钉
"同次物化内所有行 materialized_at 一致"证明 created_at 由父进程冻结
注入、worker 未自产时间戳）。

chdir 隔离零污染（#144）；依赖 duckdb/pyarrow（dataset extra），缺失时
整文件诚实 skip。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据集物化需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据集物化需要 dataset extra（pyarrow）")

import pyarrow.parquet as pq


def _echo(item):
    """池预热探针（模块级可 pickle；见 TestParallelBitwiseIdentity 回归钉）。"""
    return item


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(run_id: str, **kw) -> dict:
    base = {
        "run_id": run_id, "model": "mline", "adapter": "fake",
        "algorithm": "tune", "study_name": "s1", "seed": 42,
        "aedt_version": "fake", "ads_version": "", "git_sha": "abc1234",
        "timestamp": "2026-09-09T00:00:00+00:00", "status": "done",
    }
    base.update(kw)
    return base


N_RUNS = 9  # 含 r_bad；r_empty 计 skipped，not_a_run 无 meta 不入


def _build_campaign(root: Path) -> None:
    """在 root（=tmp/runs）下构造多通道战役目录。"""
    # ① trials ×2：r_tri_a 3 点；r_tri_b 2 点（trial_0 与 r_tri_a 的
    # trial_0 同指纹 → 去重 1 条）
    _write_json(root / "r_tri_a" / "meta.json", _meta("r_tri_a"))
    for i, (w, c) in enumerate([(1.0, 0.05), (2.0, 0.5), (3.25, 0.325)]):
        _write_json(root / "r_tri_a" / "trials" / f"trial_{i}.json", {
            "trial_number": i, "params": {"w_mm": w, "l_mm": w * 2 + 0.1},
            "metrics": {"s11_db_max_in_band": -10.0 - i}, "cost": c})
    _write_json(root / "r_tri_b" / "meta.json", _meta("r_tri_b"))
    for i, (w, c) in enumerate([(1.0, 0.06), (4.5, 0.75)]):
        _write_json(root / "r_tri_b" / "trials" / f"trial_{i}.json", {
            "trial_number": i, "params": {"w_mm": w, "l_mm": w * 2 + 0.1},
            "metrics": {"s11_db_max_in_band": -11.0 - i}, "cost": c})
    # ② 校准样本（真跑点、无逐点 cost）
    _write_json(root / "r_calib" / "meta.json", _meta(
        "r_calib", model="patch_antenna", adapter="calibration:openems",
        algorithm="calibration", study_name="calib", seed=None))
    _write_json(root / "r_calib" / "calibration" / "samples.json", {
        "samples": [
            {"params": {"h_mm": 1.2}, "metrics": {"gain_db": 5.0}},
            {"params": {"h_mm": 2.0}, "metrics": {"gain_db": 6.0}},
        ]})
    # ③ surrogate_loop best
    _write_json(root / "r_loop" / "meta.json", _meta("r_loop", model="cpw"))
    _write_json(root / "r_loop" / "surrogate_loop.json", {
        "algorithm": "surrogate_loop",
        "best": {"params": {"gap_um": 12.5}, "metrics": {"z0": 48.2},
                 "cost": 0.11}})
    # ④ autotune best
    _write_json(root / "r_auto" / "meta.json", _meta("r_auto", model="cpw"))
    _write_json(root / "r_auto" / "autotune.json", {
        "best": {"params": {"gap_um": 15.0}, "metrics": {"z0": 50.1},
                 "cost": 0.02}})
    # ⑤ run_once（provenance_extra 补 run_id 路径）
    _write_json(root / "r_once" / "meta.json",
                _meta("r_once", algorithm="run_once"))
    _write_json(root / "r_once" / "results" / "metrics.json",
                {"metrics": {"gain_db": 2.5}})
    # JSON 是合法 YAML：snapshot 经 _write_json 落盘
    _write_json(root / "r_once" / "recipe.snapshot.yaml", {
        "params": {"w_mm": {"value": 0.7}, "eps_r": {"value": 4.4}},
        "optimization": {"params": {"w_mm": {}, "eps_r": {}}}})
    # 非有限值拦截（json.dumps 缺省 allow_nan=True → NaN/Infinity 字面量）
    _write_json(root / "r_nf" / "meta.json", _meta("r_nf"))
    _write_json(root / "r_nf" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"gain_db": float("inf")}, "cost": 0.1})
    _write_json(root / "r_nf" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 2.0},
        "metrics": {}, "cost": 0.2})
    # 空 run（无产物 → skipped_runs）
    _write_json(root / "r_empty" / "meta.json", _meta("r_empty"))
    # 干扰目录（无 meta.json → 不入 target_ids）
    (root / "not_a_run").mkdir(exist_ok=True)
    _write_json(root / "not_a_run" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 9.9}, "metrics": {},
        "cost": 9.9})


@pytest.fixture
def runs_env(tmp_path, monkeypatch):
    """9 run 多通道战役 + unhealthy run，chdir 隔离（#144）。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    _build_campaign(root)
    # G11 unhealthy：无源性违例 S 参数（|S|>1）→ 体检 FAIL → 禁入注册表
    import numpy as np
    import skrf

    freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
    s = np.full((5, 2, 2), 1.1) + 0.3j
    (root / "r_bad" / "results").mkdir(parents=True, exist_ok=True)
    skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(
        str(root / "r_bad" / "results" / "params.s2p"))
    _write_json(root / "r_bad" / "meta.json", _meta("r_bad"))
    return tmp_path


# 结果信封中的易变键：数据集名/物化时刻戳/产物绝对路径（两次物化必不同）
_VOLATILE_KEYS = {"name", "created_at", "dataset_dir", "points_file",
                  "manifest", "parquet", "hdf5"}


def _strip_volatile(res: dict) -> dict:
    return {k: v for k, v in res.items() if k not in _VOLATILE_KEYS}


def _rows_without_materialized_at(points_file: str) -> list[dict]:
    """Parquet 全列逐行读出（保持行序），provenance 剔除物化时刻戳。"""
    table = pq.read_table(points_file).to_pylist()
    rows = []
    for row in table:
        prov = json.loads(row.pop("provenance_json"))
        prov.pop("materialized_at")
        row["provenance"] = prov
        rows.append(row)
    return rows


def _materialized_at_values(points_file: str) -> set[str]:
    table = pq.read_table(points_file).to_pylist()
    return {
        json.loads(r["provenance_json"])["materialized_at"]
        for r in table
    }


class TestParallelBitwiseIdentity:
    def test_full_campaign_serial_vs_parallel(self, runs_env):
        """判据 F2-4(a)：全战役 serial vs n_workers=4 物化逐位一致。"""
        from rfauto.infra.par_exec import map_ordered
        from rfauto.service.dataset_service import materialize_dataset

        # 回归钉：先用"错误 cwd"预热可复用池——worker 的 cwd 冻结在
        # spawn 时刻（df7 门实测：先跑过 par_exec 池的会话里，相对
        # runs/ 在 worker 内解析到旧 cwd → 全部"缺 meta.json"假跳过）。
        # 物化入参必须绝对路径，本测试先制造该场景再断言逐位一致。
        warmup_dir = runs_env / "warmup_cwd"
        warmup_dir.mkdir(exist_ok=True)
        os.chdir(warmup_dir)
        map_ordered(_echo, [1], n_workers=4)
        os.chdir(runs_env)  # 回到战役根（fixture 的 tmp_path）

        res_s = materialize_dataset(None, name="ds_ser")
        res_p = materialize_dataset(None, name="ds_par", n_workers=4)
        assert res_s["ok"], res_s.get("errors")
        assert res_p["ok"], res_p.get("errors")
        # 信封全字段（除易变键）相等：计数/去重/bounds/健康门/warnings…
        assert _strip_volatile(res_s) == _strip_volatile(res_p)
        # 行级：全列含行序逐位一致（provenance 剔物化时刻戳后）
        assert _rows_without_materialized_at(res_s["points_file"]) == \
            _rows_without_materialized_at(res_p["points_file"])
        # created_at 由父进程冻结注入：同次物化内所有行一致（worker 未
        # 自产时间戳），且两次物化时刻戳各自一致地不同
        assert len(_materialized_at_values(res_s["points_file"])) == 1
        assert len(_materialized_at_values(res_p["points_file"])) == 1
        # 行序抽查：首行来自 run_ids 排序首位的 r_auto（④ best 点），
        # 完成序聚合（并行下 r_auto 常先完成）会破坏该序
        rows = _rows_without_materialized_at(res_s["points_file"])
        assert rows[0]["run_id"] == "r_auto"
        # 通道计数抽查：11 点（r_auto/r_loop/r_once 各 1 + r_calib 2 +
        # r_tri_a 3 + r_tri_b 2），去重 1 条，非有限值 1 点，unhealthy 1
        assert res_s["n_points"] == res_p["n_points"] == 11
        assert res_s["n_rows"] == res_p["n_rows"] == 10
        assert res_s["n_dup"] == res_p["n_dup"] == 1
        assert res_s["n_nonfinite_skipped"] == \
            res_p["n_nonfinite_skipped"] == 1
        assert res_s["unhealthy_runs"] == res_p["unhealthy_runs"] == ["r_bad"]
        assert res_s["skipped_runs"] == res_p["skipped_runs"] == ["r_empty"]

    def test_subset_serial_vs_parallel_small_pool(self, runs_env):
        """显式 run_ids 子集 + 小池（n_workers=2）同样逐位一致。"""
        from rfauto.service.dataset_service import materialize_dataset

        ids = ["r_tri_a", "r_tri_b", "r_calib", "r_once", "r_bad"]
        res_s = materialize_dataset(ids, name="sub_ser")
        res_p = materialize_dataset(ids, name="sub_par", n_workers=2)
        assert res_s["ok"] and res_p["ok"]
        assert _strip_volatile(res_s) == _strip_volatile(res_p)
        assert _rows_without_materialized_at(res_s["points_file"]) == \
            _rows_without_materialized_at(res_p["points_file"])

    def test_default_is_serial_zero_change(self, runs_env):
        """缺省（n_workers 缺省 0）与显式 n_workers=0 结果一致（零行为
        变化缺省路径，既有调用方零改动）。"""
        from rfauto.service.dataset_service import materialize_dataset

        res_default = materialize_dataset(["r_tri_a"], name="dflt")
        res_zero = materialize_dataset(["r_tri_a"], name="zero",
                                       n_workers=0)
        assert res_default["ok"] and res_zero["ok"]
        assert _strip_volatile(res_default) == _strip_volatile(res_zero)
