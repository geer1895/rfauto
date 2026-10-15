"""数据工厂 EDB 道收集器测试（dataset_edb_lane）。

覆盖面（对应 runs/edblane85/w1_smoke 真机产物形态的合成等价物）：
- TestEdbLaneDiscover：judgment 标志目录发现（只读、路径/族名/批次名）；
- TestEdbLaneCollect：branchline+功分器两族收集 → 行 schema 逐键断言
  （DATASET_SCHEMA 对齐）、E1 指纹三键（model=spec.template /
  study_name=批次目录名 / params=spec.params）、metrics=judgment
  readings+判定元数据、provenance 指针、GT 标注（adapter=hfss）、
  query_dataset 集成（含 #369 total_rows 总数语义）；
- TestEdbLaneIdempotent：重复收集幂等（全量重扫重写行数不增）+ 同指纹
  不重入（同批次同参数重复目录折叠 n_dup 计数）；
- TestEdbLaneCrossBatch：跨批次同设计不折叠（#322：战役=批次，折叠只在
  同批次名内）；
- TestEdbLaneBadDirs：坏目录如实 skip 计数（缺 spec/缺 Touchstone/
  Touchstone 损坏/params 含 NaN 四形态，好目录行不受牵连）。

chdir 隔离零污染（#144）；依赖 duckdb/pyarrow（dataset extra）与 skrf
（openems extra），缺失时整文件 skip；Touchstone 合成走共享 helper
（tests.unit._dataset_service_helpers._write_touchstone，无源无互易
假阳性，健康门可读不误拦）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="EDB 道收集需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="EDB 道收集需要 dataset extra（pyarrow）")
pytest.importorskip("skrf", reason="EDB 道收集需要 skrf 复读 Touchstone")

from rfauto.service.dataset_edb_lane import (
    EDB_LANE_ADAPTER,
    EDB_LANE_SOURCE,
    collect_edb_lane_dataset,
    discover_edb_lane_candidates,
    resolve_dataset_runs_root,
)
from rfauto.service.dataset_service import query_dataset
from tests.unit._dataset_service_helpers import _write_touchstone

# ---------------------------------------------------------------------------
# 合成产物工厂（真机 runs/edblane85/w1_smoke/<family>/ 形态的迷你等价物）
# ---------------------------------------------------------------------------

_BRANCHLINE_PARAMS: dict[str, Any] = {
    "f0_ghz": 2.4,
    "z0_ohm": 50.0,
    "series_w_mm": 1.8702732602391428,
    "shunt_w_mm": 1.1133408215162708,
    "series_len_mm": 18.0890969702821,
    "shunt_len_mm": 18.488507896952576,
    # 描述性字符串键：与真机 spec.params 同形态（_scalar_items 收标量）
    "synthesis_source": "core.synthesis inverse_width/forward_media",
}
_POWER_DIVIDER_PARAMS: dict[str, Any] = {
    "f0_ghz": 2.4,
    "z0_ohm": 50.0,
    "arm_len_mm": 17.6,
    "iso_r_ohm": 50.0,
    "gap_mm": 0.2,
}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _judgment(n_ports: int, *, touchstone: str | None,
              readings: dict[str, float] | None = None,
              all_pass: bool = True) -> dict[str, Any]:
    """迷你 judgment（真机键面子集：readings/gates/判定元数据/指针）。"""
    return {
        "ok": all_pass,
        "all_pass": all_pass,
        "touchstone": touchstone,
        "n_ports": n_ports,
        "n_freqs": 5,
        "f_range_ghz": [2.0, 3.0],
        "f0_on_grid": True,
        "grid_step_ghz": 0.25,
        "readings": readings if readings is not None else {
            "sigma_max@f0": 0.8,
            "s11_db@f0": -25.0,
            "s21_db@f0": -3.1,
        },
        "gates": [
            {"item": "s11_db@f0", "op": "<=", "bound": -15.0, "pass": True},
            {"item": "s21_db@f0", "op": "in", "bound": [-3.5, -2.5],
             "pass": False},
        ],
    }


def _edb_product(
    root: Path,
    batch: str,
    family: str,
    *,
    template: str,
    params: dict[str, Any],
    n_ports: int,
    with_spec: bool = True,
    with_touchstone: bool = True,
    touchstone_bytes: bytes | None = None,
    judgment_touchstone_ptr: str | None = None,
    readings: dict[str, float] | None = None,
) -> Path:
    """合成一个 EDB 道产物目录：<root>/<batch>/<family>/（spec+judgment+
    state+Touchstone+批次级 run_summary.json，真机形态子集）。"""
    d = root / batch / family
    d.mkdir(parents=True, exist_ok=True)
    _write_json(d / f"{family}_spec.json", {
        "template": template,
        "schema_version": 1,
        "params": params,
    })
    ts_name = f"{family}.s{n_ports}p"
    if with_touchstone:
        if touchstone_bytes is not None:
            (d / ts_name).write_bytes(touchstone_bytes)
        else:
            _write_touchstone(d / ts_name, n_ports)
    ptr = judgment_touchstone_ptr
    if ptr is None and with_touchstone:
        ptr = str((d / ts_name).resolve())
    _write_json(d / f"{family}_judgment.json",
                _judgment(n_ports, touchstone=ptr, readings=readings))
    _write_json(d / "state.json", {
        "build": {"design": f"{family}_d1", "route": "pyaedt native",
                  "ok": True},
    })
    _write_json(root / batch / "run_summary.json", {
        "route": "pyaedt native build -> solve_project_batch",
        "families": {family: {"judge": {"rc": 0}}},
    })
    return d


@pytest.fixture
def edb_env(tmp_path, monkeypatch):
    """两族产物（branchline s4p + power_divider s3p，同批次 batch1）+
    chdir 隔离（#144）；返回 (runs_root, datasets_out)。"""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    _edb_product(root, "batch1", "branchline",
                 template="edb_branchline",
                 params=_BRANCHLINE_PARAMS, n_ports=4)
    _edb_product(root, "batch1", "power_divider",
                 template="edb_power_divider",
                 params=_POWER_DIVIDER_PARAMS, n_ports=3)
    return root, tmp_path / "datasets"


# ---------------------------------------------------------------------------
# 发现面
# ---------------------------------------------------------------------------

class TestEdbLaneDiscover:
    def test_two_families_discovered_with_markers(self, edb_env):
        root, _out = edb_env
        r = discover_edb_lane_candidates(root)
        assert r["ok"] is True
        assert r["n_candidates"] == 2
        labels = {c["label"] for c in r["candidates"]}
        assert labels == {"batch1/branchline", "batch1/power_divider"}
        by_label = {c["label"]: c for c in r["candidates"]}
        bl = by_label["batch1/branchline"]
        assert bl["model"] == "edb_branchline"
        assert bl["batch_name"] == "batch1"
        assert bl["spec_path"] == "batch1/branchline/branchline_spec.json"
        assert (bl["judgment_path"]
                == "batch1/branchline/branchline_judgment.json")
        assert bl["touchstone_path"] == "batch1/branchline/branchline.s4p"
        assert bl["state_design"] == "branchline_d1"

    def test_discover_is_read_only(self, edb_env):
        root, _out = edb_env
        before = sorted(p.relative_to(root).as_posix().lower()
                        for p in root.rglob("*"))
        r = discover_edb_lane_candidates(root)
        assert r["ok"] is True
        after = sorted(p.relative_to(root).as_posix().lower()
                       for p in root.rglob("*"))
        assert before == after

    def test_missing_runs_root_error(self, tmp_path):
        r = discover_edb_lane_candidates(tmp_path / "nope")
        assert r["ok"] is False
        assert r["errors"]


# ---------------------------------------------------------------------------
# 收集入库：行 schema / E1 指纹 / metrics / provenance / GT / query 集成
# ---------------------------------------------------------------------------

class TestEdbLaneCollect:
    def test_two_families_rows_schema_and_fingerprint(self, edb_env):
        root, out = edb_env
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out, health_gate=False)
        assert r["ok"] is True, r.get("errors")
        assert r["importer"] == "edb_lane"
        assert r["n_candidates"] == 2
        assert r["n_skipped"] == 0
        assert r["n_points"] == 2
        assert r["n_rows"] == 2
        assert r["n_dup"] == 0
        assert r["per_model_rows"] == {"edb_branchline": 1,
                                       "edb_power_divider": 1}
        # GT 标注：adapter 恒 "hfss"（本道构造性事实）→ 两行入 GT
        assert r["ground_truth"]["n_gt_rows"] == 2
        assert r["ground_truth"]["per_model"] == {
            "edb_branchline": 1, "edb_power_divider": 1}

    def test_row_fields_via_query(self, edb_env):
        root, out = edb_env
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out, health_gate=False)
        assert r["ok"] is True
        q = query_dataset("edb_ds", out_dir=out, limit=10,
                          order_by="model", order="asc")
        assert q["ok"] is True
        assert q["total_rows"] == 2  # #369 总数语义：过滤后 LIMIT 前行数
        assert q["n_rows"] == 2
        rows = {row["model"]: row for row in q["rows"]}
        assert set(rows) == {"edb_branchline", "edb_power_divider"}
        row = rows["edb_branchline"]
        # E1 指纹三键：model=spec.template / study_name=批次目录名 /
        # params=spec.params 规范化 JSON
        assert row["study_name"] == "batch1"
        assert row["adapter"] == EDB_LANE_ADAPTER == "hfss"
        assert row["algorithm"] == EDB_LANE_SOURCE == "edb_lane_import"
        assert row["source"] == EDB_LANE_SOURCE
        assert row["seed"] is None
        assert row["cost"] is None
        assert row["point_index"] == 0
        params = json.loads(row["params_json"])
        assert params["f0_ghz"] == pytest.approx(2.4)
        assert params["series_w_mm"] == pytest.approx(
            _BRANCHLINE_PARAMS["series_w_mm"])
        assert params["synthesis_source"].startswith("core.synthesis")
        # metrics = judgment readings 主体 + 判定元数据 + gates 计数
        metrics = json.loads(row["metrics_json"])
        assert metrics["s11_db@f0"] == pytest.approx(-25.0)
        assert metrics["all_pass"] is True
        assert metrics["n_ports"] == 4
        assert metrics["n_gates_total"] == 2
        assert metrics["n_gates_pass"] == 1
        # provenance：指针齐备、n_ports 为 int（计数语义）
        prov = json.loads(row["provenance_json"])
        assert prov["importer"] == "edb_lane"
        assert prov["source_dir"] == "batch1/branchline"
        assert prov["batch_dir"] == "batch1"
        assert prov["spec_path"] == "batch1/branchline/branchline_spec.json"
        assert (prov["judgment_path"]
                == "batch1/branchline/branchline_judgment.json")
        assert prov["touchstone_path"] == "batch1/branchline/branchline.s4p"
        assert isinstance(prov["n_ports"], int) and prov["n_ports"] == 4
        assert prov["n_freqs"] == 5
        assert prov["f_min_ghz"] == pytest.approx(2.0)
        assert prov["f_max_ghz"] == pytest.approx(3.0)
        assert prov["state_design"] == "branchline_d1"

    def test_query_model_filter_and_limit_semantics(self, edb_env):
        root, out = edb_env
        assert collect_edb_lane_dataset(
            name="edb_ds", runs_root=root, out_dir=out,
            health_gate=False)["ok"] is True
        q = query_dataset("edb_ds", model="edb_power_divider", out_dir=out,
                          limit=10)
        assert q["ok"] is True
        assert q["n_rows"] == 1 and q["total_rows"] == 1
        assert q["rows"][0]["model"] == "edb_power_divider"
        assert json.loads(q["rows"][0]["params_json"])["gap_mm"] == 0.2
        # #369：n_rows=limit 截断非全量计数——limit=1 时 n_rows=1 而
        # total_rows=2（新代码消费全量计数走 total_rows 单列一键）
        q1 = query_dataset("edb_ds", out_dir=out, limit=1)
        assert q1["n_rows"] == 1
        assert q1["total_rows"] == 2

    def test_run_ids_and_models_filter(self, edb_env):
        root, out = edb_env
        r = collect_edb_lane_dataset(
            run_ids=["batch1/power_divider"], name="edb_pd", runs_root=root,
            out_dir=out, health_gate=False)
        assert r["ok"] is True
        assert r["n_rows"] == 1
        assert r["source_runs"][0]["source_dir"] == "batch1/power_divider"
        r2 = collect_edb_lane_dataset(models=["edb_branchline"],
                                      name="edb_bl", runs_root=root,
                                      out_dir=out, health_gate=False)
        assert r2["ok"] is True
        assert r2["per_model_rows"] == {"edb_branchline": 1}
        r3 = collect_edb_lane_dataset(models=["edb_ratrace"], name="edb_x",
                                      runs_root=root, out_dir=out,
                                      health_gate=False)
        assert r3["ok"] is False
        assert "edb_ratrace" in r3["errors"][0]
        r4 = collect_edb_lane_dataset(run_ids=["batch1/ghost"],
                                      name="edb_g", runs_root=root,
                                      out_dir=out, health_gate=False)
        assert r4["ok"] is False
        assert "batch1/ghost" in r4["missing_runs"]


# ---------------------------------------------------------------------------
# 幂等与指纹折叠
# ---------------------------------------------------------------------------

class TestEdbLaneIdempotent:
    def test_recollect_is_idempotent(self, edb_env):
        root, out = edb_env
        r1 = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                      out_dir=out, health_gate=False)
        assert r1["ok"] is True and r1["n_rows"] == 2
        r2 = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                      out_dir=out, health_gate=False)
        assert r2["ok"] is True
        # 全量重扫重写：重复收集行数不增（同指纹不重入）
        assert r2["n_rows"] == 2
        assert r2["n_dup"] == 0
        assert r2["per_model_rows"] == r1["per_model_rows"]
        q = query_dataset("edb_ds", out_dir=out, limit=100)
        assert q["total_rows"] == 2

    def test_same_fingerprint_duplicate_dir_folds(self, edb_env):
        root, out = edb_env
        assert collect_edb_lane_dataset(
            name="edb_ds", runs_root=root, out_dir=out,
            health_gate=False)["ok"] is True
        # 同批次内同设计点（同 template+同 params、异 stem）→ 折叠一份
        _edb_product(root, "batch1", "branchline_v2",
                     template="edb_branchline",
                     params=dict(_BRANCHLINE_PARAMS), n_ports=4)
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out, health_gate=False)
        assert r["ok"] is True
        assert r["n_points"] == 3
        assert r["n_rows"] == 2  # 新候选同指纹被折叠
        assert r["n_dup"] == 1
        q = query_dataset("edb_ds", out_dir=out, limit=100)
        assert q["total_rows"] == 2


class TestEdbLaneCrossBatch:
    def test_same_design_across_batches_not_folded(self, tmp_path,
                                                    monkeypatch):
        # #322：战役=批次，指纹折叠只在同批次名内；跨批次同设计各留一行
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        _edb_product(root, "batch1", "branchline",
                     template="edb_branchline",
                     params=_BRANCHLINE_PARAMS, n_ports=4)
        _edb_product(root, "batch2", "branchline",
                     template="edb_branchline",
                     params=dict(_BRANCHLINE_PARAMS), n_ports=4)
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=tmp_path / "datasets",
                                     health_gate=False)
        assert r["ok"] is True
        assert r["n_points"] == 2
        assert r["n_rows"] == 2
        assert r["n_dup"] == 0
        q = query_dataset("edb_ds", model="edb_branchline",
                          out_dir=tmp_path / "datasets", limit=10,
                          order_by="study_name", order="asc")
        assert [row["study_name"] for row in q["rows"]] == [
            "batch1", "batch2"]

    def test_same_batch_name_across_campaigns_not_folded(self, tmp_path,
                                                          monkeypatch):
        """E1 指纹碰撞面修复钉（W5 审查批）：study_name=批次**相对 runs
        根路径**而非裸目录名——不同战役根下同名批次目录（各战役各自的
        ``w1_smoke`` 是常态命名）不折叠，各留一行。

        旧口径（裸批次名）实证：两战役同 design 点 → 同指纹
        (model, "w1_smoke", None, params_json) → 静默折叠 n_dup=1，
        第二战役的实测曲线丢失（仅 provenance.batch_dir 留痕）。
        """
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        for camp in ("campaign_a", "campaign_b"):
            _edb_product(root, f"{camp}/w1_smoke", "branchline",
                         template="edb_branchline",
                         params=_BRANCHLINE_PARAMS, n_ports=4)
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=tmp_path / "datasets",
                                     health_gate=False)
        assert r["ok"] is True
        assert r["n_points"] == 2
        assert r["n_rows"] == 2  # 同名批次跨战役不折叠（旧口径此处 n_dup=1）
        assert r["n_dup"] == 0
        q = query_dataset("edb_ds", model="edb_branchline",
                          out_dir=tmp_path / "datasets", limit=10,
                          order_by="study_name", order="asc")
        assert [row["study_name"] for row in q["rows"]] == [
            "campaign_a/w1_smoke", "campaign_b/w1_smoke"]
        provs = [json.loads(row["provenance_json"]) for row in q["rows"]]
        assert [p["batch_dir"] for p in provs] == [
            "campaign_a/w1_smoke", "campaign_b/w1_smoke"]

    def test_product_directly_under_runs_root_self_batch(self, tmp_path,
                                                          monkeypatch):
        """产物目录即 runs 根（judgment 直落根）时批次=自身——旧口径取
        runs 根父级目录名（越出 runs 根，批次名随宿主目录漂移）。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        root.mkdir(parents=True)
        family = "branchline"
        _write_json(root / f"{family}_spec.json", {
            "template": "edb_branchline",
            "schema_version": 1,
            "params": _BRANCHLINE_PARAMS,
        })
        _write_touchstone(root / f"{family}.s4p", 4)
        _write_json(root / f"{family}_judgment.json",
                    _judgment(4, touchstone=str((root / f"{family}.s4p")
                                                .resolve())))
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=tmp_path / "datasets",
                                     health_gate=False)
        assert r["ok"] is True
        assert r["n_rows"] == 1
        q = query_dataset("edb_ds", out_dir=tmp_path / "datasets", limit=10)
        # 批次=产物目录自身 → study_name=其相对 runs 根路径（"."）
        assert q["rows"][0]["study_name"] == "."


# ---------------------------------------------------------------------------
# 坏目录如实 skip
# ---------------------------------------------------------------------------

class TestEdbLaneBadDirs:
    def test_bad_dirs_skipped_good_rows_survive(self, edb_env):
        root, out = edb_env
        # 坏①：judgment 在、spec 缺（无参数来源）
        d = root / "batch1" / "nospec"
        d.mkdir(parents=True)
        _write_json(d / "nospec_judgment.json",
                    _judgment(2, touchstone=None))
        # 坏②：spec 在、Touchstone 缺（judgment 指针失效 + 目录内无 sNp）
        _edb_product(root, "batch1", "nots", template="edb_branchline",
                     params=_BRANCHLINE_PARAMS, n_ports=2,
                     with_touchstone=False, judgment_touchstone_ptr=None)
        # 坏③：Touchstone 损坏（skrf 解析失败）
        _edb_product(root, "batch1", "corrupt", template="edb_branchline",
                     params=_BRANCHLINE_PARAMS, n_ports=2,
                     touchstone_bytes=b"this is not a touchstone",
                     judgment_touchstone_ptr=None)
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out, health_gate=False)
        assert r["ok"] is True, r.get("errors")
        # 好目录两行不受牵连
        assert r["n_rows"] == 2
        assert r["per_model_rows"] == {"edb_branchline": 1,
                                       "edb_power_divider": 1}
        # 坏目录逐个如实计数（坏①②③各一条原因）
        assert r["n_skipped"] == 3
        warnings_text = "\n".join(r.get("warnings") or [])
        assert "batch1/nospec" in warnings_text
        assert "缺 nospec_spec.json" in warnings_text
        assert "batch1/nots" in warnings_text
        assert "无 Touchstone 产物" in warnings_text
        assert "batch1/corrupt" in warnings_text
        assert "Touchstone 解析失败" in warnings_text
        # 零行产物目录进 skipped_runs（同 workdir 口径）
        assert set(r["skipped_runs"]) >= {
            "batch1/nospec", "batch1/nots", "batch1/corrupt"}

    def test_nan_params_point_skipped_and_counted(self, edb_env):
        root, out = edb_env
        _edb_product(root, "batch1", "nanparams",
                     template="edb_branchline",
                     params={"f0_ghz": float("nan"), "w_mm": 1.0},
                     n_ports=2)
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out, health_gate=False)
        assert r["ok"] is True
        assert r["n_nonfinite_skipped"] == 1
        assert r["n_rows"] == 2  # NaN 点拦截，好点不受影响
        warnings_text = "\n".join(r.get("warnings") or [])
        assert "batch1/nanparams" in warnings_text
        assert "非有限值" in warnings_text


# ---------------------------------------------------------------------------
# 健康门通道（默认开：G11 目录级体检，仅 unhealthy 拦）
# ---------------------------------------------------------------------------

class TestEdbLaneHealthGate:
    def test_health_gate_default_on_does_not_block_passive_products(
            self, edb_env):
        root, out = edb_env
        # 合成 Touchstone 为无源互易矩阵（共享 helper 口径），健康门不误拦
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out)
        assert r["ok"] is True, r.get("errors")
        assert r["health_gate"] is True
        assert len(r["health_verdicts"]) == 2
        assert all(v != "unhealthy" for v in r["health_verdicts"].values())
        assert r["n_rows"] == 2


# ---------------------------------------------------------------------------
# manifest runs_root 脱敏（aurora36 W2-D，SUMMARY §5.4 清偿）：绝对路径/
# 盘符不落盘——runs/datasets 数据集条件发布面唯一硬敏感面
# ---------------------------------------------------------------------------

_DRIVE_RE = re.compile(r"[A-Za-z]:[\\/]")


class TestEdbLaneManifestRunsRoot:
    def test_new_manifest_is_relative_and_drive_free(self, edb_env):
        """新生成 manifest 不含盘符与绝对路径（本席立钉）；runs_root=相对
        本 manifest 所在目录的 posix 形态（缺省布局 ``../../``），且可经
        resolve_dataset_runs_root 单源解析回真实 runs 根。"""
        root, out = edb_env
        r = collect_edb_lane_dataset(name="edb_ds", runs_root=root,
                                     out_dir=out, health_gate=False)
        assert r["ok"] is True, r.get("errors")
        manifest_path = out / "edb_ds" / "dataset_manifest.yaml"
        text = manifest_path.read_text(encoding="utf-8")
        # 全文零盘符/绝对路径（盘符正则 + \w:\ 反斜杠形态双查）
        assert _DRIVE_RE.search(text) is None, text
        import yaml

        doc = yaml.safe_load(text)
        # fixture 布局：runs_root=<tmp>/runs，manifest 在 <tmp>/datasets/
        # edb_ds/ → 相对形态 = ../../runs（真机布局 runs/datasets/<name>
        # 则为 ../../，同一算法）
        assert doc["runs_root"] == "../../runs"
        assert "盘符" in doc["runs_root_note"]  # 可重建说明字段随行
        # 读取侧单源：相对形态解析回真实 runs 根（存在性探测链②）
        resolved = resolve_dataset_runs_root(doc, manifest_path)
        assert resolved == root.resolve()

    def test_resolve_legacy_absolute_manifest(self, edb_env):
        """旧绝对路径形态兼容（读取侧存在性探测链①）：在盘即认。"""
        root, out = edb_env
        assert collect_edb_lane_dataset(
            name="edb_ds", runs_root=root, out_dir=out,
            health_gate=False)["ok"] is True
        manifest_path = out / "edb_ds" / "dataset_manifest.yaml"
        import yaml

        doc = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        doc["runs_root"] = str(root.resolve())  # 模拟 2026-10 前旧 manifest
        resolved = resolve_dataset_runs_root(doc, manifest_path)
        assert resolved == root.resolve()

    def test_resolve_fallback_chain(self, tmp_path, monkeypatch):
        """存在性探测链③与全落空形态：缺省 runs 在盘即认；全不在盘返回
        首个候选（不虚构目录，调用方 is_dir 报错面接手）。"""
        monkeypatch.chdir(tmp_path)
        runs = tmp_path / "runs"
        runs.mkdir()
        manifest_path = tmp_path / "datasets" / "ds" / "dataset_manifest.yaml"
        manifest_path.parent.mkdir(parents=True)
        # ③：runs_root 键缺失 → 缺省 runs（相对 cwd）在盘即认
        assert resolve_dataset_runs_root({}, manifest_path) == runs.resolve()
        # ② 在盘优先于 ③：相对形态指向的目录存在即认
        alt = tmp_path / "datasets" / "ds" / "alt_runs"
        alt.mkdir()
        assert resolve_dataset_runs_root(
            {"runs_root": "alt_runs"}, manifest_path) == alt.resolve()
        # 全落空（缺省也不在盘）：返回首个候选（相对解析形态），不虚构
        resolved = resolve_dataset_runs_root(
            {"runs_root": "ghost"}, tmp_path / "nowhere.yaml",
            default=tmp_path / "ghost_runs")
        assert resolved == (tmp_path / "ghost")

    @pytest.mark.skipif(os.name != "nt", reason="跨盘 ValueError 为 Windows 形态")
    def test_manifest_runs_root_cross_drive_falls_empty(self):
        """跨盘（Windows 异盘符）相对化不可表达 → 落空串不回退写绝对路径
        （脱敏优先；note 字段说明重建口径）。"""
        from rfauto.service.dataset_edb_lane import _manifest_runs_root
        assert _manifest_runs_root(Path("Q:/elsewhere/runs"),
                                   Path("C:/somewhere/datasets/x")) == ""
