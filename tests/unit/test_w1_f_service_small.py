"""W1-F 席 F-14 + H-10 回归钉。

F-14（S2-8 拓②收口）：v3_services/ui_service 的 ``_load_run_trials`` 三份
拷贝并入 ``_helpers.load_run_trials`` 单源——v3 侧 trial_number 排序语义
留在消费面（稳定排序+输入序一致 → 逐位无损）；ui 侧本就文件名序，直通。
钉三面同目录逐位一致 + 单源身份。

H-10（R6 §4.2）：run_once 通道 meta 无 study_name → 湖 runs 索引 study 列
null。修 = meta 写 ``study_name=run_id``（dataset_service 导入面同款口径）。
钉 = fake 全链路 run_once 后 meta.json 携带 study_name 且等于 run_id。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml


def _write_trial(tdir: Path, name: str, trial_number: int, cost: float) -> None:
    (tdir / name).write_text(
        json.dumps({"trial_number": trial_number, "cost": cost}),
        encoding="utf-8")


def _make_run(run_dir: Path) -> None:
    """文件名序 ≠ trial_number 序 + 坏文件 + 非 trial 前缀文件的 run 目录。"""
    tdir = run_dir / "trials"
    tdir.mkdir(parents=True)
    _write_trial(tdir, "trial_00.json", 2, 0.5)   # 文件名第 1 个，号 2
    _write_trial(tdir, "trial_01.json", 0, 9.9)   # 文件名第 2 个，号 0
    _write_trial(tdir, "trial_02.json", 1, 1.2)
    (tdir / "trial_03.json").write_text("{broken", encoding="utf-8")  # 坏文件跳过
    (tdir / "notes.txt").write_text("not a trial", encoding="utf-8")  # 前缀外跳过


class TestF14TrialLoaderUnification:
    def test_three_loaders_same_dir_contract(self, tmp_path):
        """三面合同：ui≡单源（文件名序）；v3≡单源结果按 trial_number 稳定排序。"""
        from rfauto.service import ui_service, v3_services
        from rfauto.service._helpers import load_run_trials

        run_dir = tmp_path / "run_a"
        _make_run(run_dir)
        single = load_run_trials(run_dir)
        assert ui_service._load_run_trials(run_dir) == single  # ui 本就文件名序
        assert v3_services._load_run_trials(run_dir) == sorted(
            single, key=lambda t: t.get("trial_number", 0))  # 排序语义留消费面
        # 单源身份：v3/ui 均为 _helpers 同一函数的委托（身份可比对）
        assert v3_services.load_run_trials is load_run_trials
        assert ui_service.load_run_trials is load_run_trials

    def test_v3_sorts_by_trial_number_stable_and_skips_bad(self, tmp_path):
        from rfauto.service import v3_services

        run_dir = tmp_path / "run_b"
        _make_run(run_dir)
        trials = v3_services._load_run_trials(run_dir)
        assert [t["trial_number"] for t in trials] == [0, 1, 2]
        assert [t["cost"] for t in trials] == [9.9, 1.2, 0.5]

    def test_ui_preserves_filename_order_no_resort(self, tmp_path):
        from rfauto.service import ui_service

        run_dir = tmp_path / "run_c"
        _make_run(run_dir)
        trials = ui_service._load_run_trials(run_dir)
        assert [t["trial_number"] for t in trials] == [2, 0, 1]  # 文件名序

    def test_missing_dir_returns_empty_all_three(self, tmp_path):
        from rfauto.service import ui_service, v3_services
        from rfauto.service._helpers import load_run_trials

        ghost = tmp_path / "ghost"
        assert load_run_trials(ghost) == []
        assert v3_services._load_run_trials(ghost) == []
        assert ui_service._load_run_trials(ghost) == []


class TestH10RunOnceMetaStudyName:
    def test_run_once_meta_carries_study_name_equal_run_id(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """fake 全链路：run_once 落盘 meta.json 带 study_name=run_id（H-10）。"""
        from rfauto.service.api import run_once

        monkeypatch.chdir(tmp_path)
        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(wilkinson_recipe), encoding="utf-8")
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        meta = json.loads(
            (Path(result["run_dir"]) / "meta.json").read_text(encoding="utf-8"))
        assert meta.get("study_name") == result["run_id"]

    def test_lake_index_row_study_column_no_longer_null(
            self, tmp_path, monkeypatch, wilkinson_recipe):
        """消费面闭环：湖索引行 study 列 = run_id（原为 null 的病灶映射）。"""
        from rfauto.service.api import run_once
        from rfauto.service.lake_service import _index_row

        monkeypatch.chdir(tmp_path)
        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(yaml.safe_dump(wilkinson_recipe), encoding="utf-8")
        result = run_once(recipe_path)
        assert result["ok"], result.get("errors")
        row = _index_row(Path(result["run_dir"]), campaign=None, depth=2,
                         rel=result["run_id"])
        assert row["study"] == result["run_id"]
        assert row["status"] == "done"
