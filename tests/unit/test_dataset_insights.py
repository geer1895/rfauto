"""WP2.4 数据集注册表余量测试：覆盖度统计 + ground truth 标注（6.3 解锁
进度）+ HF 格式/公开双集（dataset_insights）。

构造临时 runs/（假 run，chdir 隔离零污染 #144）；duckdb/pyarrow（dataset
extra）缺失时整文件 skip。全离线秒级，禁止真机求解进测试。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据集余量测试需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据集余量测试需要 dataset extra（pyarrow）")

import yaml


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _meta(run_id: str, *, model: str, adapter: str = "fake",
          algorithm: str = "tune", study_name: str = "s1",
          seed: int | None = 42) -> dict:
    return {
        "run_id": run_id, "model": model, "adapter": adapter,
        "algorithm": algorithm, "study_name": study_name, "seed": seed,
        "aedt_version": "fake", "ads_version": "", "git_sha": "abc1234",
        "timestamp": "2026-09-13T00:00:00+00:00", "status": "done",
    }


@pytest.fixture
def runs_env(tmp_path, monkeypatch):
    """与 test_dataset_service 同款假 run 群：run_a/run_b（fake，trials）、
    run_c（calibration:openems，校准样本=GT）、run_empty（无产物）。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    _write_json(root / "run_a" / "meta.json", _meta("run_a", model="mline"))
    _write_json(root / "run_a" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -10.0}, "cost": 0.05})
    _write_json(root / "run_a" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 2.0},
        "metrics": {"s11_db_max_in_band": -20.0}, "cost": 0.5})
    _write_json(root / "run_b" / "meta.json", _meta("run_b", model="mline"))
    _write_json(root / "run_b" / "trials" / "trial_0.json", {
        "trial_number": 0, "params": {"w_mm": 1.0},
        "metrics": {"s11_db_max_in_band": -11.0}, "cost": 0.06})
    _write_json(root / "run_b" / "trials" / "trial_1.json", {
        "trial_number": 1, "params": {"w_mm": 3.0},
        "metrics": {"s11_db_max_in_band": -15.0}, "cost": 0.2})
    _write_json(root / "run_c" / "meta.json", _meta(
        "run_c", model="patch_antenna", adapter="calibration:openems",
        algorithm="calibration", study_name="calib_c", seed=None))
    _write_json(root / "run_c" / "calibration" / "samples.json", {
        "bounds": {"h_mm": [0.5, 2.5]}, "objectives": [],
        "samples": [
            {"params": {"h_mm": 1.2}, "metrics": {"gain_db": 5.0}},
            {"params": {"h_mm": 2.0}, "metrics": {"gain_db": 6.0}},
        ]})
    _write_json(root / "run_empty" / "meta.json", _meta("run_empty", model="mline"))
    return tmp_path


def _materialize(name: str = "demo", run_ids=None):
    from rfauto.service.dataset_service import materialize_dataset

    return materialize_dataset(run_ids, name=name)


def _read_manifest(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


class TestGroundTruthPolicy:
    """真机引擎白名单判别：全仓实测 adapter 值逐个钉死（#222 口径）。"""

    def test_real_adapters(self):
        from rfauto.service.dataset_service import is_ground_truth_adapter

        # runs/ 实测存在的 adapter 值（2026-09-13 盘点）：
        # fake×1175 / calibration:openems×11 / hfss×9 / mf:fake+hfss×2 /
        # p0_gate:asset_reuse×1 / ""×1
        assert is_ground_truth_adapter("hfss") is True
        assert is_ground_truth_adapter("HFSS") is True          # 大小写不敏感
        assert is_ground_truth_adapter("calibration:openems") is True
        assert is_ground_truth_adapter("COMSOL:6.3") is True
        assert is_ground_truth_adapter("measured:vna") is True

    def test_non_ground_truth_adapters(self):
        from rfauto.service.dataset_service import is_ground_truth_adapter

        assert is_ground_truth_adapter("fake") is False
        assert is_ground_truth_adapter("mf:fake+hfss") is False  # 混合保真不标
        assert is_ground_truth_adapter("") is False
        assert is_ground_truth_adapter(None) is False
        assert is_ground_truth_adapter("p0_gate:asset_reuse") is False


class TestMaterializeAnnotation:
    """物化即标注：manifest 随物化带 visibility + ground_truth 基础块。"""

    def test_manifest_records_visibility_and_gt(self, runs_env):
        from rfauto.service.dataset_service import MANIFEST_NAME

        r = _materialize("demo")
        assert r["ok"], r.get("errors")
        assert r["visibility"] == "private"
        assert r["ground_truth"]["n_gt_rows"] == 2
        assert r["ground_truth"]["per_model"] == {"patch_antenna": 2}
        manifest = _read_manifest(
            runs_env / "runs" / "datasets" / "demo" / MANIFEST_NAME)
        assert manifest["visibility"] == "private"
        assert manifest["ground_truth"]["n_gt_rows"] == 2
        assert "fake" in manifest["ground_truth"]["policy"]

    def test_all_fake_dataset_zero_gt(self, runs_env):
        r = _materialize("only_fake", ["run_a", "run_b"])
        assert r["ok"]
        assert r["ground_truth"]["n_gt_rows"] == 0
        assert r["ground_truth"]["per_model"] == {}


class TestCoverage:
    """点数/参数空间覆盖度统计。"""

    def test_point_counts_and_param_coverage(self, runs_env):
        from rfauto.service.dataset_insights import dataset_coverage

        _materialize("demo")
        r = dataset_coverage("demo")
        assert r["ok"], r.get("errors")
        # 点数分布
        assert r["n_rows"] == 5 and r["n_points"] == 6
        assert r["by_model"] == {"mline": 3, "patch_antenna": 2}
        assert r["by_source"] == {"calibration_samples": 2, "trials": 3}
        assert r["by_adapter"] == {"calibration:openems": 2, "fake": 3}
        # 参数空间：w_mm ∈ {1,2,3} 等宽 10 箱占 0/5/9 → 3 箱；h_mm 占 2 箱
        assert r["coverage"]["n_dims"] == 2
        assert r["per_key"]["w_mm"]["distinct"] == 3
        assert r["per_key"]["w_mm"]["min"] == 1.0
        assert r["per_key"]["w_mm"]["max"] == 3.0
        assert r["per_key"]["w_mm"]["occupancy"] == pytest.approx(0.3)
        assert r["per_key"]["h_mm"]["occupancy"] == pytest.approx(0.2)
        cov = r["coverage"]
        assert cov["mean_occupancy"] == pytest.approx(0.25)
        assert cov["min_occupancy"] == pytest.approx(0.2)
        assert cov["weakest_key"] == "h_mm"
        assert cov["n_constant_dims"] == 0

    def test_constant_dim_not_reported_as_full_coverage(self, runs_env):
        """常数维（min==max）只记占 1 格并单列计数——不虚报 100% 覆盖。"""
        from rfauto.service.dataset_insights import dataset_coverage

        root = runs_env / "runs"
        _write_json(root / "run_const" / "meta.json",
                    _meta("run_const", model="mline"))
        for i in range(3):
            _write_json(root / "run_const" / "trials" / f"trial_{i}.json", {
                "trial_number": i, "params": {"w_mm": 2.0, "h_mm": float(i)},
                "metrics": {}, "cost": 0.1 * i})
        r = _materialize("const_ds", ["run_const"])
        assert r["ok"]
        c = dataset_coverage("const_ds")
        assert c["ok"]
        assert c["coverage"]["n_constant_dims"] == 1
        assert c["per_key"]["w_mm"]["distinct"] == 1
        assert c["per_key"]["w_mm"]["occupancy"] == pytest.approx(0.1)
        assert c["per_key"]["h_mm"]["distinct"] == 3
        assert c["coverage"]["weakest_key"] == "w_mm"

    def test_bins_and_missing_dataset_validation(self, runs_env):
        from rfauto.service.dataset_insights import dataset_coverage

        r = dataset_coverage("demo", bins=1)
        assert not r["ok"] and "bins" in r["errors"][0]
        r2 = dataset_coverage("nope")
        assert not r2["ok"] and "数据集不存在" in r2["errors"][0]


class TestGroundTruthAnnotation:
    """GT 标注回写 manifest + 6.3 解锁进度（门槛默认 100 点/族）。"""

    def test_annotate_and_progress_below_threshold(self, runs_env):
        from rfauto.service.dataset_insights import annotate_ground_truth

        _materialize("demo")
        r = annotate_ground_truth("demo")
        assert r["ok"], r.get("errors")
        assert r["n_gt_rows"] == 2 and r["n_rows"] == 5
        assert r["threshold"] == 100
        assert r["unlocked"] is False
        assert r["per_model"] == {"patch_antenna": {"n_gt": 2, "unlocked": False}}
        assert r["best_model"] == "patch_antenna"
        assert r["progress_ratio"] == pytest.approx(0.02)
        assert r["deficit"] == 98
        manifest = _read_manifest(r["manifest"])
        gt = manifest["ground_truth"]
        assert gt["threshold"] == 100 and gt["unlocked"] is False
        assert gt["annotated_at"]  # 回写时间戳留档

    def test_annotate_threshold_override(self, runs_env):
        from rfauto.service.dataset_insights import annotate_ground_truth

        _materialize("demo")
        r = annotate_ground_truth("demo", threshold=2)
        assert r["ok"]
        assert r["unlocked"] is True
        assert r["progress_ratio"] == pytest.approx(1.0)
        assert r["deficit"] == 0

    def test_unlocked_at_100_points_real_engine(self, runs_env):
        """单族 105 个 HFSS 真机点 → 族级解锁翻转（门槛口径实证）。"""
        from rfauto.service.dataset_insights import annotate_ground_truth

        root = runs_env / "runs"
        _write_json(root / "run_hfss" / "meta.json", _meta(
            "run_hfss", model="patch_antenna", adapter="hfss"))
        for i in range(105):
            _write_json(root / "run_hfss" / "trials" / f"trial_{i}.json", {
                "trial_number": i, "params": {"h_mm": 1.0 + i * 0.01},
                "metrics": {}, "cost": 0.1 + i * 0.001})  # cost 有区分度（G11 #195）
        r = _materialize("gt100", ["run_hfss"])
        assert r["ok"] and r["n_rows"] == 105
        ann = annotate_ground_truth("gt100")
        assert ann["ok"]
        assert ann["n_gt_rows"] == 105
        assert ann["unlocked"] is True
        assert ann["per_model"]["patch_antenna"]["unlocked"] is True
        assert ann["deficit"] == 0

    def test_bad_threshold_rejected(self, runs_env):
        from rfauto.service.dataset_insights import annotate_ground_truth

        _materialize("demo")
        r = annotate_ground_truth("demo", threshold=0)
        assert not r["ok"] and "threshold" in r["errors"][0]


class TestReadiness:
    """6.3 解锁进度视图：无标注/门槛不一致时自动重算回写（幂等）。"""

    def test_auto_annotate_on_fresh_dataset(self, runs_env):
        from rfauto.service.dataset_insights import neural_operator_readiness

        _materialize("demo")  # 物化块无 threshold → readiness 自动补标
        r = neural_operator_readiness("demo")
        assert r["ok"], r.get("errors")
        assert r["threshold"] == 100
        assert r["unlocked"] is False and r["n_gt_rows"] == 2
        manifest = _read_manifest(r["manifest"])
        assert manifest["ground_truth"]["threshold"] == 100
        assert manifest["ground_truth"]["annotated_at"]

    def test_read_threshold_match_no_rewrite_needed(self, runs_env):
        from rfauto.service.dataset_insights import (
            annotate_ground_truth,
            neural_operator_readiness,
        )

        _materialize("demo")
        ann = annotate_ground_truth("demo", threshold=50)
        before = _read_manifest(ann["manifest"])["ground_truth"]["annotated_at"]
        r = neural_operator_readiness("demo", threshold=50)
        assert r["ok"]
        assert r["threshold"] == 50 and r["unlocked"] is False
        after = _read_manifest(ann["manifest"])["ground_truth"]["annotated_at"]
        assert before == after  # 门槛一致：直读标注，不重写

    def test_missing_dataset(self, runs_env):
        from rfauto.service.dataset_insights import neural_operator_readiness

        r = neural_operator_readiness("nope")
        assert not r["ok"] and "数据集不存在" in r["errors"][0]


class TestVisibilityAndListing:
    """公开/私有双集：visibility 切换 + 注册表余量总览。"""

    def test_set_visibility_and_list_filter(self, runs_env):
        from rfauto.service.dataset_insights import (
            list_datasets,
            set_dataset_visibility,
        )

        _materialize("ds_a")
        _materialize("ds_b")
        r = set_dataset_visibility("ds_a", "public")
        assert r["ok"] and r["visibility"] == "public"
        assert _read_manifest(r["manifest"])["visibility"] == "public"

        all_ds = list_datasets()
        assert all_ds["ok"] and all_ds["n_datasets"] == 2
        by_name = {d["name"]: d for d in all_ds["datasets"]}
        assert by_name["ds_a"]["visibility"] == "public"
        assert by_name["ds_b"]["visibility"] == "private"
        # 关键数字进总览：GT 标注随物化可见（WP2.4「解锁进度可见」）
        assert by_name["ds_a"]["n_gt_rows"] == 2
        assert by_name["ds_a"]["gt_unlocked"] is False
        assert by_name["ds_a"]["has_hf"] is False

        pub = list_datasets(visibility="public")
        assert pub["n_datasets"] == 1
        assert pub["datasets"][0]["name"] == "ds_a"
        priv = list_datasets(visibility="private")
        assert priv["n_datasets"] == 1
        assert priv["datasets"][0]["name"] == "ds_b"

    def test_invalid_visibility_rejected(self, runs_env):
        from rfauto.service.dataset_insights import (
            list_datasets,
            set_dataset_visibility,
        )

        _materialize("ds_a")
        r = set_dataset_visibility("ds_a", "internal")
        assert not r["ok"] and "public/private" in r["errors"][0]
        r2 = set_dataset_visibility("nope", "public")
        assert not r2["ok"]
        r3 = list_datasets(visibility="internal")
        assert not r3["ok"]

    def test_empty_registry(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from rfauto.service.dataset_insights import list_datasets

        r = list_datasets()
        assert r["ok"] and r["datasets"] == [] and r["n_datasets"] == 0


class TestHfExport:
    """HF 格式导出：数据卡 + data 分片 + private 放行门。"""

    def test_private_export_refused_by_default(self, runs_env):
        from rfauto.service.dataset_insights import export_hf_dataset

        _materialize("demo")
        r = export_hf_dataset("demo")
        assert not r["ok"]
        assert "set_dataset_visibility" in r["errors"][0]
        assert not (runs_env / "runs" / "datasets" / "demo" / "hf").exists()

    def test_export_layout_card_and_byte_identical_copy(self, runs_env):
        from rfauto.service.dataset_insights import (
            export_hf_dataset,
            set_dataset_visibility,
        )

        _materialize("demo")
        set_dataset_visibility("demo", "public")
        r = export_hf_dataset("demo", license="CC-BY-4.0")
        assert r["ok"], r.get("errors")
        assert r["visibility"] == "public" and r["license"] == "CC-BY-4.0"
        hf_parquet = Path(r["parquet"])
        assert hf_parquet.name == "train-00000-of-00001.parquet"
        assert hf_parquet.parent == Path(r["hf_dir"]) / "data"
        # 逐字节副本：schema/行面与 points.parquet 完全一致
        src = runs_env / "runs" / "datasets" / "demo" / "points.parquet"
        assert hf_parquet.read_bytes() == src.read_bytes()
        # 数据卡 frontmatter：标准键 + rfauto 嵌套统计
        card = Path(r["card"]).read_text(encoding="utf-8")
        parts = card.split("---")
        front = yaml.safe_load(parts[1])
        assert front["name"] == "demo"
        assert front["visibility"] == "public"
        assert front["license"] == "CC-BY-4.0"
        assert front["configs"][0]["data_files"][0]["path"] == \
            "data/train-00000-of-00001.parquet"
        meta = front["rfauto"]
        assert meta["n_rows"] == 5 and meta["n_points"] == 6
        assert meta["ground_truth"]["n_gt_rows"] == 2
        assert "columns" in meta and "source_runs" in meta

    def test_allow_private_explicit_bypass(self, runs_env):
        from rfauto.service.dataset_insights import export_hf_dataset

        _materialize("demo")
        r = export_hf_dataset("demo", allow_private=True)
        assert r["ok"], r.get("errors")
        assert r["visibility"] == "private"
        assert Path(r["parquet"]).exists()

    def test_missing_dataset_rejected(self, runs_env):
        from rfauto.service.dataset_insights import export_hf_dataset

        r = export_hf_dataset("nope", allow_private=True)
        assert not r["ok"] and "数据集不存在" in r["errors"][0]


# ---------------------------------------------------------------------------
# E1 收口②：公开集注册路径 + 公开/私有双集防污染（对齐 WP3.7 load_bench_sets）
# ---------------------------------------------------------------------------

def _public_set_path(root: Path) -> Path:
    from rfauto.service.dataset_insights import PUBLIC_SET_NAME

    return root / "runs" / "datasets" / PUBLIC_SET_NAME


class TestPublicSetIsolation:
    def test_not_configured_is_clean_not_error(self, runs_env):
        """E2 未接入前公开集缺文件=合法空集（not_configured），私有集由
        manifest 派生（物化默认 private）。"""
        from rfauto.service.dataset_insights import load_dataset_sets

        _materialize("demo")
        r = load_dataset_sets()
        assert r["ok"] and r["errors"] == []
        assert r["public"]["status"] == "not_configured"
        assert r["public"]["ids"] == [] and r["private"]["ids"] == ["demo"]
        assert r["overlap_ids"] == []

    def test_register_external_public_id_clean(self, runs_env):
        """未本地物化的外部公开集先登记（source 记来源）：注册表落盘、
        双集无交集、幂等重注册覆盖条目不重复。"""
        from rfauto.service.dataset_insights import (
            load_dataset_sets,
            register_public_dataset,
        )

        _materialize("demo")
        r = register_public_dataset("open_rf_bench", source="https://example.org/x")
        assert r["ok"], r.get("errors")
        assert r["promoted"] is False and r["n_entries"] == 1
        assert r["overlap_ids"] == []
        reg = yaml.safe_load(_public_set_path(runs_env).read_text(encoding="utf-8"))
        assert reg["schema_version"] == "1.0"
        assert reg["entries"][0]["name"] == "open_rf_bench"
        assert reg["entries"][0]["source"] == "https://example.org/x"
        # 幂等
        r2 = register_public_dataset("open_rf_bench", license="cc-by-4.0")
        assert r2["ok"] and r2["n_entries"] == 1
        sets = load_dataset_sets()
        assert sets["ok"] and sets["public"]["status"] == "loaded"
        assert sets["public"]["ids"] == ["open_rf_bench"]
        assert sets["private"]["ids"] == ["demo"]

    def test_register_private_id_refused_by_default(self, runs_env):
        """防污染前置：id 已是本地私有数据集 → 默认拒绝，注册表不落盘，
        manifest visibility 不变（私有战役资产不被静默洗白）。"""
        from rfauto.service.dataset_insights import register_public_dataset

        m = _materialize("demo")
        r = register_public_dataset("demo")
        assert not r["ok"]
        assert "双集污染防护" in r["errors"][0] and "promote" in r["errors"][0]
        assert not _public_set_path(runs_env).exists()
        assert _read_manifest(m["manifest"])["visibility"] == "private"

    def test_register_promote_flips_visibility_and_leaves_private_set(self, runs_env):
        from rfauto.service.dataset_insights import (
            load_dataset_sets,
            register_public_dataset,
        )

        m = _materialize("demo")
        r = register_public_dataset("demo", promote=True, license="cc-by-4.0")
        assert r["ok"], r.get("errors")
        assert r["promoted"] is True and r["overlap_ids"] == []
        assert _read_manifest(m["manifest"])["visibility"] == "public"
        sets = load_dataset_sets()
        assert sets["ok"]
        assert sets["public"]["ids"] == ["demo"] and sets["private"]["ids"] == []

    def test_overlap_non_empty_is_fail(self, runs_env):
        """两集 id 交集非空即 FAIL（对齐 load_bench_sets 口径）：手改注册表
        把私有数据集 id 塞进公开集 → ok=False + overlap_ids + 污染文案。"""
        from rfauto.service.dataset_insights import load_dataset_sets

        _materialize("demo")
        _materialize("campaign_b", run_ids=["run_a"])
        path = _public_set_path(runs_env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({
            "schema_version": "1.0",
            "entries": [{"name": "campaign_b"}, {"name": "open_rf_bench"}],
        }), encoding="utf-8")
        r = load_dataset_sets()
        assert not r["ok"]
        assert r["overlap_ids"] == ["campaign_b"]
        assert any("双集污染" in e and "campaign_b" in e for e in r["errors"])
        assert r["public"]["status"] == "loaded"
        assert r["private"]["ids"] == ["campaign_b", "demo"]

    def test_register_after_hand_edited_overlap_surfaces_fail(self, runs_env):
        """纵深防御：注册表已被手改污染时，注册另一个干净 id 也如实 ok=False
        并回传 overlap_ids（不把污染状态藏在成功回执里）。"""
        from rfauto.service.dataset_insights import register_public_dataset

        _materialize("demo")
        path = _public_set_path(runs_env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"entries": [{"name": "demo"}]}),
                        encoding="utf-8")
        r = register_public_dataset("open_rf_bench")
        assert not r["ok"] and r["overlap_ids"] == ["demo"]
        assert r["n_entries"] == 2

    def test_invalid_registry_is_hard_error(self, runs_env):
        """注册表存在但结构非法（非对象条目/非法 id/重复 id）→ invalid 硬错误
        （防静默降级），注册路径也拒绝在其上写入。"""
        from rfauto.service.dataset_insights import (
            load_dataset_sets,
            register_public_dataset,
        )

        _materialize("demo")
        path = _public_set_path(runs_env)
        path.parent.mkdir(parents=True, exist_ok=True)
        for payload in (
            {"entries": ["demo"]},
            {"entries": [{"name": "bad name"}]},
            {"entries": [{"name": "x1"}, {"name": "x1"}]},
            ["not", "a", "mapping"],
        ):
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            r = load_dataset_sets()
            assert not r["ok"], payload
            assert r["public"]["status"] == "invalid", payload
            reg = register_public_dataset("open_rf_bench")
            assert not reg["ok"], payload
        assert "open_rf_bench" not in path.read_text(encoding="utf-8")

    def test_bad_dataset_name_rejected(self, runs_env):
        from rfauto.service.dataset_insights import register_public_dataset

        r = register_public_dataset("../escape")
        assert not r["ok"] and "非法数据集名" in r["errors"][0]

    def test_registry_file_not_listed_as_dataset(self, runs_env):
        """public_set.yaml 是注册表根目录下的文件，list_datasets 只迭代目录，
        不会被误认成数据集。"""
        from rfauto.service.dataset_insights import list_datasets, register_public_dataset

        _materialize("demo")
        assert register_public_dataset("open_rf_bench")["ok"]
        r = list_datasets()
        assert r["ok"] and [d["name"] for d in r["datasets"]] == ["demo"]
        assert r["datasets"][0]["format"] == "parquet"


# ---------------------------------------------------------------------------
# E1 收口①×余量接口：hdf5 物化数据集上的覆盖度/GT 标注/HF 导出
# ---------------------------------------------------------------------------

class TestHdf5Insights:
    def test_coverage_and_annotate_parity_with_parquet(self, runs_env):
        pytest.importorskip("h5py", reason="HDF5 物化需要 h5py（openems extra）")
        from rfauto.service.dataset_insights import (
            annotate_ground_truth,
            dataset_coverage,
        )
        from rfauto.service.dataset_service import materialize_dataset

        assert _materialize("pq")["ok"]
        h5 = materialize_dataset(None, name="h5", fmt="hdf5")
        assert h5["ok"], h5.get("errors")
        cp, ch = dataset_coverage("pq"), dataset_coverage("h5")
        assert cp["ok"] and ch["ok"], (cp.get("errors"), ch.get("errors"))
        assert ch["per_key"] == cp["per_key"]
        assert ch["coverage"] == cp["coverage"]
        assert ch["by_adapter"] == cp["by_adapter"]
        ap, ah = annotate_ground_truth("pq"), annotate_ground_truth("h5")
        assert ah["n_gt_rows"] == ap["n_gt_rows"] == 2
        assert ah["per_model"] == ap["per_model"]

    def test_export_hf_from_hdf5_writes_parquet_shard(self, runs_env):
        """hdf5 物化的数据集导出 HF 布局：分片仍是 parquet（经 Arrow 转写），
        datasets 生态可直读；行数与 manifest 一致。"""
        pytest.importorskip("h5py")
        import pyarrow.parquet as pq

        from rfauto.service.dataset_insights import export_hf_dataset
        from rfauto.service.dataset_service import materialize_dataset

        h5 = materialize_dataset(None, name="h5", fmt="hdf5")
        assert h5["ok"], h5.get("errors")
        r = export_hf_dataset("h5", allow_private=True)
        assert r["ok"], r.get("errors")
        table = pq.read_table(r["parquet"])
        assert table.num_rows == h5["n_rows"] == 5
        assert table.column_names[:2] == ["run_id", "model"]
