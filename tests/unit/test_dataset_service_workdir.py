"""E1 数据集注册表 v2 测试（工作目录导入域）。

本文件承载：工作目录形态真机产物导入器区块（discover/import 的
局部 helper 与 workdir_env fixture）、TestWorkdirDiscover、
TestWorkdirImport、TestWorkdirShells（CLI 薄壳冒烟）、
TestRegistrySync（R2-D-03 物化/导入回写注册表）。

本文件自 tests/unit/test_dataset_service.py 按被测域拆分而得
（W9 席，ge8e 后续批 P3，G1-4 登记伴生件）：纯搬运重构，类名/测试名/断言
逐字节保持，零语义变化。跨域共享基建抽至 tests/unit/_dataset_service_helpers.py
（同 _geometry_audit_helpers 包内导入惯例）；runs_env fixture 经
tests/unit/conftest.py re-export 供 pytest 解析（模块级导入会与测试参数
同名遮蔽触发 F401/F811，conftest 发现是 pytest 的正规机制）。

原模块头注释（拆分前原文，对本文件同样成立）：
构造临时 runs/（假 run：meta.json + trials/*.json + calibration/samples.json），
chdir 隔离零污染（#144）。依赖 duckdb/pyarrow（dataset extra），缺失时整文件
skip（fresh env 下的优雅降级）；缺依赖的显式报错分支用 monkeypatch sys.modules
钉住（#139 教训：不真打外部通道）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

pytest.importorskip("duckdb", reason="数据集注册表 v2 需要 dataset extra（duckdb）")
pytest.importorskip("pyarrow", reason="数据集注册表 v2 需要 dataset extra（pyarrow）")

import yaml

from tests.unit._dataset_service_helpers import (
    _meta,
    _write_json,
    _write_touchstone,
)

# ---------------------------------------------------------------------------
# 工作目录形态真机产物导入器（审查修复队列增量③；审计 #17 "造了零件没装上车"）
# 样本按真机 runs/ 文件构成裁剪：hairpin_calib/kgap2_g0500（calib.json 双参数
# 段）、helix_arbitration（根级多 s1p + 仲裁 JSON s1p 键引用）、
# hfss_marchand_anchor（根级 s4p/s3p + .aedt）、mline_smoke/pt1、
# slotline_port_a/pt1（参数在根级 results JSON design 段）。chdir 隔离（#144）。
# ---------------------------------------------------------------------------

_CSV_HEADER_2P = "freq_hz,re_S11,im_S11,re_S21,im_S21"
_CSV_HEADER_3P = ("freq_hz,re_S11,im_S11,re_S21,im_S21,"
                  "re_S31,im_S31,re_S23,im_S23")


def _write_sparams_csv(path: Path, header: str = _CSV_HEADER_2P,
                       n: int = 5) -> None:
    """合成 openEMS 单激励 sparams.csv：|S11|=0.3、|S21|=0.5（3 端口再补
    S31/S23=0.4）无源，健康门可读不误拦；列数由 header 决定。"""
    n_cols = len(header.split(",")) - 1
    rows = []
    for i in range(n):
        f = 2.0e9 + i * 0.25e9
        vals = [0.3, 0.0, 0.5, 0.0, 0.4, 0.0, 0.4, 0.0][:n_cols]
        rows.append(",".join([f"{f:.1f}", *(f"{v:.6f}" for v in vals)]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _openems_point(point_dir: Path, header: str = _CSV_HEADER_2P) -> None:
    """openEMS 点目录最小构成（真机 pt1/ 形态）：sparams.csv + simulation.py +
    _rfauto_runner.py + fdtd/（空）。"""
    _write_sparams_csv(point_dir / "sparams.csv", header)
    (point_dir / "simulation.py").write_text("# rendered\n", encoding="utf-8")
    (point_dir / "_rfauto_runner.py").write_text("# runner\n", encoding="utf-8")
    (point_dir / "fdtd").mkdir(exist_ok=True)


def _write_hairpin_calib_point(root: Path, workdir: str, pt: str, gap_mm: float,
                               arm_len_mm: float = 36.7799) -> None:
    p = root / workdir / pt
    _openems_point(p)
    _write_json(p / "calib.json", {
        "pt": pt, "f0_ghz": 2.5, "fbw": 0.05, "mesh_mm": 0.4,
        "window_ghz": [2.0, 3.2],
        "design_params": {"order": 2, "w_mm": 1.1117, "arm_len_mm": 35.4676,
                          "arm_gap_mm": 3.0, "gap_mm": 0.7539,
                          "tap_frac": 0.388478},
        "calib_params": {"order": 2, "w_mm": 1.1117, "arm_len_mm": arm_len_mm,
                         "arm_gap_mm": 3.0, "gap_mm": gap_mm, "tap_frac": 0.43},
        "changed": {"gap_mm": [0.7539, gap_mm]},
    })


def _workdir_fixtures(root: Path) -> None:
    """五族工作目录形态最小样本 + 两个反例（有 meta 的标准 run / 无族无曲线目录）。"""
    # hairpin：kgap2_g0500/{calib.json（design_params 校准前 + calib_params 实跑）,
    # sparams.csv}
    _write_hairpin_calib_point(root, "hairpin_calib", "kgap2_g0500", 0.5)
    # helix：根级多曲线，仲裁 JSON 以 s1p 键（绝对路径）显式引用主曲线，
    # geom.nominal 是设计参数；attempt2 无引用 → 跳过
    h = root / "helix_arbitration"
    _write_touchstone(h / "hfss_helix.s1p", 1)
    _write_touchstone(h / "hfss_helix_attempt2_coarse.s1p", 1)
    (h / "hfss_project").mkdir()
    _write_json(h / "hfss_arbitration.json", {
        "stage": "hfss", "ok": True, "solve_s": 123.4, "verdict": "AGREE",
        "geom": {"source": "_ant2_layout('helix')",
                 "nominal": {"helix_d_mm": 3.0, "helix_turns": 2,
                             "helix_pitch_mm": 3.6142, "helix_w_mm": 0.6,
                             "feed_gap_mm": 2.0}},
        "s1p": str(h / "hfss_helix.s1p"),
    })
    # marchand：根级 s4p/s3p + .aedt；同名 stem JSON 带 geometry；b 无归属 → 跳过
    m = root / "hfss_marchand_anchor"
    _write_touchstone(m / "hfss_marchand_anchor_a.s4p", 4)
    _write_touchstone(m / "hfss_marchand_anchor_b.s3p", 3)
    (m / "hfss_marchand_anchor_a.aedt").write_text("", encoding="utf-8")
    _write_json(m / "hfss_marchand_anchor_a.json", {
        "anchor": "a", "verdict": "AGREE",
        "geometry": {"w_mm": 0.62, "s_mm": 0.15, "len_mm": 18.4, "er": 3.66},
    })
    # mline：pt1/ 单曲线目录 + 点级 JSON params
    q = root / "mline_smoke" / "pt1"
    _openems_point(q)
    (q / "port_beta.csv").write_text("freq_hz,beta\n2.0e9,60.0\n",
                                     encoding="utf-8")
    _write_json(q / "mline_point.json",
                {"params": {"w_mm": 1.113, "L_mm": 40.0}, "mesh_mm": 0.4})
    # slotline：pt1/ 摘要无参数段，参数在根级 results JSON 的 design 段（上溯）
    s = root / "slotline_port_a" / "pt1"
    _openems_point(s)
    _write_json(s / "slotline_summary.json",
                {"ok": True, "excite_port": 1, "f0_hz": 2.5e9,
                 "z_mode_ohm": 107.38})
    _write_json(root / "slotline_port_a" / "slotline_port_a_results.json", {
        "route": "A",
        "design": {"f0_ghz": 2.5, "band_ghz": [2.25, 2.75], "w_mm": 1.0,
                   "h_mm": 1.524, "er": 3.66, "line_len_mm_1lambda": 93.4624,
                   "section": {"y_half_mm": 60.0}},
    })
    # 反例①：有 meta.json 的标准 run（走 materialize，不是候选）
    _write_json(root / "20260901_000000_deadbeef" / "meta.json",
                _meta("20260901_000000_deadbeef", model="mline"))
    # 反例②：无族标签且无曲线的目录（runs/datasets 类）——不列
    (root / "datasets").mkdir()
    (root / "datasets" / "readme.txt").write_text("x", encoding="utf-8")


@pytest.fixture
def workdir_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "runs"
    root.mkdir()
    _workdir_fixtures(root)
    return root


class TestWorkdirDiscover:
    """discover_workdir_candidates：五族入口逐一可发现，反例不列。"""

    def test_five_families_each_discoverable(self, workdir_env):
        from rfauto.service.dataset_service import (
            WORKDIR_FAMILIES,
            discover_workdir_candidates,
        )

        disc = discover_workdir_candidates()
        assert disc["ok"], disc.get("errors")
        assert disc["families"] == list(WORKDIR_FAMILIES)
        assert disc["per_family"] == {
            "hairpin": 1, "helix": 1, "marchand": 1, "mline": 1, "slotline": 1}
        assert disc["n_candidates"] == 5
        assert disc["n_with_meta"] == 1   # 标准 run 不是候选
        by_id = {c["run_id"]: c for c in disc["candidates"]}
        assert set(by_id) == {"hairpin_calib", "helix_arbitration",
                              "hfss_marchand_anchor", "mline_smoke",
                              "slotline_port_a"}
        assert "datasets" not in by_id and "20260901_000000_deadbeef" not in by_id
        # 逐族：族标签/曲线数/引擎/端口数
        assert by_id["hairpin_calib"]["family"] == "hairpin"
        assert by_id["hairpin_calib"]["n_curves"] == 1
        assert by_id["hairpin_calib"]["adapters"] == ["openems"]
        c = by_id["hairpin_calib"]["curves"][0]
        assert c["path"] == "kgap2_g0500/sparams.csv"
        assert c["kind"] == "sparams_csv" and c["n_ports"] == 2
        assert c["source_dir"] == "hairpin_calib/kgap2_g0500"
        assert c["mtime"]  # ISO 时间戳非空
        assert by_id["helix_arbitration"]["family"] == "helix"
        assert by_id["helix_arbitration"]["n_curves"] == 2
        assert by_id["helix_arbitration"]["adapters"] == ["hfss"]
        assert by_id["hfss_marchand_anchor"]["family"] == "marchand"
        kinds = {c["path"]: (c["kind"], c["n_ports"])
                 for c in by_id["hfss_marchand_anchor"]["curves"]}
        assert kinds == {"hfss_marchand_anchor_a.s4p": ("touchstone", 4),
                         "hfss_marchand_anchor_b.s3p": ("touchstone", 3)}
        assert by_id["mline_smoke"]["family"] == "mline"
        assert by_id["slotline_port_a"]["family"] == "slotline"
        assert by_id["slotline_port_a"]["curves"][0]["adapter"] == "openems"

    def test_models_filter_and_invalid_family(self, workdir_env):
        from rfauto.service.dataset_service import discover_workdir_candidates

        disc = discover_workdir_candidates(models=["slotline", "HELIX"])
        assert disc["ok"] and disc["n_candidates"] == 2
        assert {c["run_id"] for c in disc["candidates"]} == {
            "slotline_port_a", "helix_arbitration"}
        bad = discover_workdir_candidates(models=["patch"])
        assert not bad["ok"] and "未知器件族" in bad["errors"][0]
        nodir = discover_workdir_candidates("nope_root")
        assert not nodir["ok"] and "不存在" in nodir["errors"][0]

    def test_unclassified_curve_dir_listed_only_without_filter(self, workdir_env):
        """无族标签但有曲线的目录：models=None 列出（family=""），过滤时不列；
        导入默认五族不收它。"""
        from rfauto.service.dataset_service import (
            WORKDIR_FAMILIES,
            discover_workdir_candidates,
        )

        _openems_point(workdir_env / "misc_probe" / "pt1")
        disc = discover_workdir_candidates()
        by_id = {c["run_id"]: c for c in disc["candidates"]}
        assert by_id["misc_probe"]["family"] == ""
        assert disc["per_family"]["other"] == 1
        disc5 = discover_workdir_candidates(models=list(WORKDIR_FAMILIES))
        assert "misc_probe" not in {c["run_id"] for c in disc5["candidates"]}

    def test_curve_walk_bounded_and_skips_engine_dirs(self, tmp_path):
        """曲线扫描：fdtd/ 内 sparams.csv 收（p0_cross_fidelity 形态）、
        .aedtresults/__pycache__/hfss_project 不下钻、深度 >3 不收、
        端口数 0 不认、大小写不敏感。"""
        from rfauto.service.dataset_service import _scan_workdir_curves

        w = tmp_path / "w"
        _write_sparams_csv(w / "ems_0" / "fdtd" / "sparams.csv")
        (w / "proj.aedtresults").mkdir(parents=True)
        (w / "proj.aedtresults" / "x.s2p").write_text("! x", encoding="utf-8")
        (w / "hfss_project").mkdir()
        (w / "hfss_project" / "y.s2p").write_text("! x", encoding="utf-8")
        (w / "a" / "b" / "c" / "d").mkdir(parents=True)
        (w / "a" / "b" / "c" / "d" / "deep.s2p").write_text("! x", encoding="utf-8")
        (w / "a" / "b" / "c" / "ok.S3P").write_text("! x", encoding="utf-8")
        (w / "zero.s0p").write_text("! x", encoding="utf-8")
        got = [(c["rel"], c["kind"], c["n_ports"]) for c in _scan_workdir_curves(w)]
        assert got == [("a/b/c/ok.S3P", "touchstone", 3),
                       ("ems_0/fdtd/sparams.csv", "sparams_csv", 2)]

    def test_sparams_csv_ports_helper(self, tmp_path):
        from rfauto.service.dataset_service import _sparams_csv_ports

        _write_sparams_csv(tmp_path / "two.csv", _CSV_HEADER_2P)
        _write_sparams_csv(tmp_path / "three.csv", _CSV_HEADER_3P)
        (tmp_path / "junk.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        assert _sparams_csv_ports(tmp_path / "two.csv") == 2
        assert _sparams_csv_ports(tmp_path / "three.csv") == 3
        assert _sparams_csv_ports(tmp_path / "junk.csv") is None
        assert _sparams_csv_ports(tmp_path / "missing.csv") is None


class TestWorkdirImport:
    """import_workdir_runs：导入后注册表行数增加 + provenance 可查
    （来源目录/时间戳/touchstone 路径/n_ports）。"""

    def test_import_all_five_families_rows_and_provenance(self, workdir_env):
        from rfauto.service.dataset_service import (
            WORKDIR_SOURCE,
            import_workdir_runs,
            query_dataset,
        )

        res = import_workdir_runs(name="wd_all")   # 默认健康门
        assert res["ok"], res.get("errors")
        assert res["importer"] == "workdir"
        assert res["n_candidates"] == 5 and res["n_curves"] == 7
        # helix attempt2（无引用）+ marchand b（无 JSON）无可归属参数 → 跳过如实
        assert res["n_points_skipped"] == 2
        assert res["n_points"] == 5 and res["n_rows"] == 5 and res["n_dup"] == 0
        assert res["unhealthy_points"] == []   # 合成无源曲线不被 G11 误拦
        assert res["skipped_runs"] == [] and res["missing_runs"] == []
        assert res["per_family_rows"] == {
            "hairpin": 1, "helix": 1, "marchand": 1, "mline": 1, "slotline": 1}
        # 全部 openems/hfss 真机引擎 → GT 标注 5/5
        assert res["ground_truth"]["n_gt_rows"] == 5
        assert res["ground_truth"]["per_model"] == res["per_family_rows"]
        skipped_labels = " ".join(res["warnings"])
        assert "helix_arbitration/hfss_helix_attempt2_coarse.s1p" in skipped_labels
        assert "hfss_marchand_anchor/hfss_marchand_anchor_b.s3p" in skipped_labels
        # 单曲线目录健康门 verdict 落 manifest，多曲线根目录 unknown 不拦
        assert res["health_verdicts"]["hairpin_calib/kgap2_g0500"] != "unhealthy"
        assert res["health_verdicts"]["helix_arbitration"] == "unknown"

        q = query_dataset("wd_all", limit=50)
        assert q["ok"] and q["n_rows"] == 5
        rows = {r["run_id"]: r for r in q["rows"]}
        for r in rows.values():
            assert r["source"] == WORKDIR_SOURCE and r["algorithm"] == WORKDIR_SOURCE
            assert r["study_name"] == r["run_id"]   # 战役即 study
            assert r["seed"] is None and r["cost"] is None
            prov = json.loads(r["provenance_json"])
            assert prov["importer"] == "workdir" and prov["run_id"] == r["run_id"]
            assert prov["run_timestamp"].endswith("+00:00")   # 曲线 mtime UTC ISO
            assert prov["materialized_at"] and isinstance(prov["materialized_at"], str)
            assert prov["source_dir"].startswith(r["run_id"])
            assert isinstance(prov["n_ports"], int)
            # 相对路径可直接拼回：runs/<run_id>/<curve_path> 命中真实文件
            assert (workdir_env / r["run_id"] / prov["curve_path"]).is_file()
            assert (workdir_env / r["run_id"] / prov["params_source"]).is_file()

        # hairpin：calib_params（实跑几何）优先于 design_params（校准前设计）
        hp = rows["hairpin_calib"]
        assert hp["model"] == "hairpin" and hp["adapter"] == "openems"
        assert json.loads(hp["params_json"])["gap_mm"] == 0.5
        assert json.loads(hp["params_json"])["arm_len_mm"] == 36.7799
        assert json.loads(hp["metrics_json"]) == {
            "pt": "kgap2_g0500", "f0_ghz": 2.5, "fbw": 0.05, "mesh_mm": 0.4}
        hp_prov = json.loads(hp["provenance_json"])
        assert hp_prov["source_dir"] == "hairpin_calib/kgap2_g0500"
        assert hp_prov["curve_path"] == "kgap2_g0500/sparams.csv"
        assert hp_prov["curve_kind"] == "sparams_csv" and hp_prov["n_ports"] == 2
        assert hp_prov["params_source"] == "kgap2_g0500/calib.json"
        assert hp_prov["params_key"] == "calib_params"
        assert "touchstone_path" not in hp_prov   # csv 曲线无 Touchstone 键

        # helix：多曲线根目录靠仲裁 JSON s1p 键显式引用归属，geom.nominal 参数
        hx = rows["helix_arbitration"]
        assert hx["model"] == "helix" and hx["adapter"] == "hfss"
        assert json.loads(hx["params_json"]) == {
            "feed_gap_mm": 2.0, "helix_d_mm": 3.0, "helix_pitch_mm": 3.6142,
            "helix_turns": 2, "helix_w_mm": 0.6}
        hx_prov = json.loads(hx["provenance_json"])
        assert hx_prov["touchstone_path"] == "hfss_helix.s1p"
        assert hx_prov["curve_kind"] == "touchstone" and hx_prov["n_ports"] == 1
        assert hx_prov["source_dir"] == "helix_arbitration"
        assert hx_prov["params_key"] == "geom.nominal"
        assert json.loads(hx["metrics_json"])["verdict"] == "AGREE"

        # marchand：同名 stem JSON 归属 + .aedt → hfss，s4p → n_ports 4
        mc = rows["hfss_marchand_anchor"]
        assert mc["model"] == "marchand" and mc["adapter"] == "hfss"
        mc_prov = json.loads(mc["provenance_json"])
        assert mc_prov["touchstone_path"] == "hfss_marchand_anchor_a.s4p"
        assert mc_prov["n_ports"] == 4 and mc_prov["params_key"] == "geometry"
        assert json.loads(mc["params_json"])["len_mm"] == 18.4

        # mline：点级 JSON params 键
        ml = rows["mline_smoke"]
        assert ml["model"] == "mline" and ml["adapter"] == "openems"
        assert json.loads(ml["params_json"]) == {"L_mm": 40.0, "w_mm": 1.113}
        assert json.loads(ml["provenance_json"])["params_key"] == "params"

        # slotline：pt1 无参数段 → 上溯到根级 results JSON design 段（只收标量）
        sl = rows["slotline_port_a"]
        assert sl["model"] == "slotline"
        assert json.loads(sl["params_json"]) == {
            "er": 3.66, "f0_ghz": 2.5, "h_mm": 1.524,
            "line_len_mm_1lambda": 93.4624, "w_mm": 1.0}
        sl_prov = json.loads(sl["provenance_json"])
        assert sl_prov["params_source"] == "slotline_port_a_results.json"
        assert sl_prov["params_key"] == "design"
        assert sl_prov["source_dir"] == "slotline_port_a/pt1"

        # manifest：导入器键 + 既有注册表键（list_datasets 可见 = 入口可发现）
        manifest = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["importer"] == "workdir" and manifest["n_rows"] == 5
        assert manifest["families"] == ["slotline", "hairpin", "marchand",
                                        "mline", "helix"]
        assert manifest["health_gate"] is True
        assert manifest["ground_truth"]["n_gt_rows"] == 5
        from rfauto.service.dataset_insights import list_datasets

        listed = list_datasets(out_dir="runs/datasets")
        assert listed["ok"]
        assert "wd_all" in {d["name"] for d in listed["datasets"]}

    def test_progressive_reimport_grows_rows(self, workdir_env):
        """渐进收集：新战役落盘后重跑同名，注册表行数增加（旧行仍在）。"""
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        r1 = import_workdir_runs(name="wd_grow", models=["hairpin"],
                                 health_gate=False)
        assert r1["ok"] and r1["n_rows"] == 1
        _write_hairpin_calib_point(workdir_env, "hairpin_calib", "kgap2_g0800", 0.8)
        _write_hairpin_calib_point(workdir_env, "hairpin_calib2", "pt1", 1.1328)
        r2 = import_workdir_runs(name="wd_grow", models=["hairpin"],
                                 health_gate=False)
        assert r2["ok"] and r2["n_rows"] == 3 and r2["n_candidates"] == 2
        q = query_dataset("wd_grow", limit=50, columns=["run_id", "params_json"])
        gaps = sorted(json.loads(r["params_json"])["gap_mm"] for r in q["rows"])
        assert gaps == [0.5, 0.8, 1.1328]
        manifest = yaml.safe_load(Path(r2["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_rows"] == 3
        assert [s["run_id"] for s in manifest["source_runs"]] == [
            "hairpin_calib", "hairpin_calib2"]

    def test_dedup_within_workdir_only(self, workdir_env):
        """指纹 (model, study_name=工作目录, seed, params)：同战役内同设计点折叠
        计 n_dup，跨战役同设计各留一行。"""
        from rfauto.service.dataset_service import import_workdir_runs

        _write_hairpin_calib_point(workdir_env, "hairpin_calib", "kgap2_dup", 0.5)
        _write_hairpin_calib_point(workdir_env, "hairpin_other", "pt1", 0.5)
        res = import_workdir_runs(name="wd_dedup", models=["hairpin"],
                                  health_gate=False)
        assert res["ok"]
        assert res["n_points"] == 3 and res["n_rows"] == 2 and res["n_dup"] == 1

    def test_run_ids_filter_missing_and_all_missing(self, workdir_env):
        from rfauto.service.dataset_service import import_workdir_runs

        res = import_workdir_runs(["mline_smoke", "nope", "20260901_000000_deadbeef"],
                                  name="wd_ids", health_gate=False)
        assert res["ok"] and res["n_rows"] == 1
        assert res["missing_runs"] == ["20260901_000000_deadbeef", "nope"]
        bad = import_workdir_runs(["nope"], name="wd_none", health_gate=False)
        assert not bad["ok"] and bad["missing_runs"] == ["nope"]
        none_fam = import_workdir_runs(name="wd_fam", models=["patch"])
        assert not none_fam["ok"] and "未知器件族" in none_fam["errors"][0]
        assert not import_workdir_runs(name="bad name")["ok"]
        assert not import_workdir_runs(name="wd_fmt", fmt="csv")["ok"]

    def test_health_gate_blocks_unhealthy_point(self, workdir_env, monkeypatch):
        """G11 目录级门：verdict=unhealthy 的单曲线目录禁入（同 materialize
        口径），health_gate=False 放行；体检器异常如实降级不拦。"""
        import rfauto.service.health_service as hs
        from rfauto.service.dataset_service import import_workdir_runs

        seen: list[tuple[str, str]] = []

        def fake_hc(run_id, *, runs_dir=None):
            seen.append((run_id, Path(runs_dir).name))
            if run_id == "kgap2_g0500":
                return {"ok": False, "verdict": "unhealthy", "factors": []}
            if run_id == "pt1" and Path(runs_dir).name == "mline_smoke":
                raise RuntimeError("体检器故障")
            return {"ok": True, "verdict": "healthy", "factors": []}

        monkeypatch.setattr(hs, "health_check_run", fake_hc)
        res = import_workdir_runs(name="wd_gate")
        assert res["ok"]
        assert res["unhealthy_points"] == ["hairpin_calib/kgap2_g0500/sparams.csv"]
        assert res["health_verdicts"]["hairpin_calib/kgap2_g0500"] == "unhealthy"
        assert res["health_verdicts"]["mline_smoke/pt1"] == "unknown"
        assert any("health_gate" in w and "体检器故障" in w
                   for w in res["warnings"])
        assert res["n_rows"] == 4 and "hairpin" not in res["per_family_rows"]
        # 体检按单曲线目录调用（run_id=目录名, runs_dir=父目录）；多曲线根目录不调
        assert ("kgap2_g0500", "hairpin_calib") in seen
        assert all(rid not in ("helix_arbitration", "hfss_marchand_anchor")
                   for rid, _ in seen)
        off = import_workdir_runs(name="wd_nogate", health_gate=False)
        assert off["ok"] and off["n_rows"] == 5 and off["health_verdicts"] == {}

    def test_ambiguous_multi_curve_dir_skipped_not_guessed(self, tmp_path, monkeypatch):
        """多曲线目录无引用/同名 JSON → 不猜归属（#122）；祖先级引用按"相对该级
        目录的路径"精确匹配，pt1 的引用不会漏给 pt2。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        w = root / "mline_multi"
        _write_sparams_csv(w / "pt1" / "sparams.csv")
        _write_sparams_csv(w / "pt2" / "sparams.csv")
        _write_touchstone(w / "var_a.s2p", 2)
        _write_touchstone(w / "var_b.s2p", 2)
        _write_json(w / "summary.json", {
            "params": {"w_mm": 1.0},
            "curves": ["pt1/sparams.csv"],   # 只引用 pt1
        })
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        res = import_workdir_runs(name="wd_amb", health_gate=False)
        assert res["ok"], res.get("errors")
        # pt1：祖先 summary.json 以 "pt1/sparams.csv" 显式引用 → 成行；
        # pt2：单曲线目录上溯认无引用 JSON（同 summary.json params）→ 与 pt1 同参
        #   指纹折叠 n_dup=1（引用匹配按相对该级目录的路径，pt1 的引用不漏给 pt2，
        #   pt2 成行走的是单曲线规则而非误匹配）；
        # 根级 var_a/var_b：多曲线目录无引用/同名 JSON → 不猜，跳过 2
        assert res["n_points_skipped"] == 2 and res["n_points"] == 2
        assert res["n_rows"] == 1 and res["n_dup"] == 1
        row = query_dataset("wd_amb")["rows"][0]
        assert json.loads(row["provenance_json"])["curve_path"] == "pt1/sparams.csv"
        assert any("var_a.s2p" in w for w in res["warnings"])
        assert any("var_b.s2p" in w for w in res["warnings"])

    def test_nonfinite_params_skipped_metrics_key_dropped(self, tmp_path, monkeypatch):
        """params 非有限 → 整点跳过计数；metrics 非有限 → 只剔键、点保留。"""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        p_bad = root / "hairpin_nan" / "pt_bad"
        _openems_point(p_bad)
        (p_bad / "pt.json").write_text(
            '{"params": {"w_mm": NaN, "gap_mm": 0.5}, "f0_ghz": 2.5}',
            encoding="utf-8")
        p_ok = root / "hairpin_nan" / "pt_ok"
        _openems_point(p_ok)
        (p_ok / "pt.json").write_text(
            '{"params": {"w_mm": 1.0, "gap_mm": 0.5}, "solve_s": Infinity, "f0_ghz": 2.5}',
            encoding="utf-8")
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        res = import_workdir_runs(name="wd_nan", health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_nonfinite_skipped"] == 1 and res["n_rows"] == 1
        assert any("pt_bad" in w and "非有限" in w for w in res["warnings"])
        assert any("pt_ok" in w and "solve_s" in w for w in res["warnings"])
        row = query_dataset("wd_nan")["rows"][0]
        assert json.loads(row["metrics_json"]) == {"f0_ghz": 2.5}
        assert "NaN" not in row["params_json"] and "Infinity" not in row["metrics_json"]

    def test_hdf5_format_roundtrip(self, workdir_env):
        pytest.importorskip("h5py", reason="hdf5 格式需要 h5py")
        from rfauto.service.dataset_service import import_workdir_runs, query_dataset

        res = import_workdir_runs(name="wd_h5", models=["mline"], fmt="hdf5",
                                  health_gate=False)
        assert res["ok"] and res["format"] == "hdf5" and res["hdf5"].endswith("points.h5")
        q = query_dataset("wd_h5")
        assert q["ok"] and q["n_rows"] == 1 and q["format"] == "hdf5"
        assert json.loads(q["rows"][0]["provenance_json"])["n_ports"] == 2

    def test_empty_root_and_no_rows_envelopes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        from rfauto.service.dataset_service import import_workdir_runs

        res = import_workdir_runs(name="wd_empty")
        assert not res["ok"] and "工作目录形态产物" in res["errors"][0]
        # 有候选但零可归属点：ok=False + 计数字段齐全
        _write_sparams_csv(tmp_path / "runs" / "mline_bare" / "pt1" / "sparams.csv")
        res2 = import_workdir_runs(name="wd_zero", health_gate=False)
        assert not res2["ok"] and res2["n_candidates"] == 1
        assert res2["n_points_skipped"] == 1 and res2["skipped_runs"] == ["mline_bare"]


class TestWorkdirShells:
    """CLI 薄壳冒烟：datasets discover-workdir / import-workdir 直连 service。"""

    def test_cli_discover_and_import(self, workdir_env):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        runner = CliRunner()
        r1 = runner.invoke(app, ["datasets", "discover-workdir", "--models", "hairpin,helix"])
        assert r1.exit_code == 0, r1.output
        assert '"n_candidates": 2' in r1.output
        r2 = runner.invoke(app, ["datasets", "import-workdir", "--name", "cli_wd",
                                 "--no-health-gate"])
        assert r2.exit_code == 0, r2.output
        assert "工作目录产物已导入: cli_wd" in r2.output
        assert "无可归属参数跳过: 2" in r2.output
        r3 = runner.invoke(app, ["datasets", "query", "cli_wd",
                                 "--where", "model = 'helix'",
                                 "--columns", "run_id,model"])
        assert r3.exit_code == 0, r3.output
        assert "helix_arbitration" in r3.output
        bad = runner.invoke(app, ["datasets", "import-workdir", "--name", "x",
                                  "--models", "patch"])
        assert bad.exit_code == 1 and "导入失败" in bad.output
        bad2 = runner.invoke(app, ["datasets", "discover-workdir", "--runs-root", "nope"])
        assert bad2.exit_code == 1 and "发现失败" in bad2.output


class TestRegistrySync:
    """R2-D-03 ⑤：数据集物化回写注册表（默认关零行为变化，best-effort #105）。

    autouse chdir + 清双 env（#144，同 test_registry_db 模板）；开关解析链
    =显式实参 > settings db.dataset_registry_sync > False。
    """

    @pytest.fixture(autouse=True)
    def _isolated_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
        monkeypatch.delenv("RFAUTO_JOB_REGISTRY_DB", raising=False)
        yield

    @staticmethod
    def _seed_one_run(tmp_path: Path) -> None:
        _write_json(tmp_path / "runs" / "r1" / "meta.json",
                    _meta("r1", model="mline"))
        _write_json(tmp_path / "runs" / "r1" / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"w_mm": 1.0},
            "metrics": {"s11_db_max_in_band": -10.0}, "cost": 0.05})

    # -- materialize_dataset ------------------------------------------------

    def test_materialize_default_off_no_db_file(self, tmp_path):
        self._seed_one_run(tmp_path)
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="sync_off")
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert not (tmp_path / "runs" / "registry.sqlite").exists()

    def test_materialize_explicit_on_row_queryable(self, tmp_path):
        self._seed_one_run(tmp_path)
        from rfauto.service import db_service
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="sync_on", registry_sync=True)
        assert r["ok"] is True and r["registry_sync"] is True
        out = db_service.db_query(
            "SELECT name, n_rows, visibility, format FROM datasets ORDER BY name")
        assert out["ok"] is True
        assert out["rows"] == [["sync_on", 1, "private", "parquet"]]

    def test_materialize_settings_yaml_enables_without_explicit(self, tmp_path):
        self._seed_one_run(tmp_path)
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        from rfauto.service.dataset_service import materialize_dataset

        r = materialize_dataset(None, name="sync_yaml")
        assert r["ok"] is True and r["registry_sync"] is True

    def test_materialize_upsert_failure_does_not_block(self, tmp_path, monkeypatch):
        self._seed_one_run(tmp_path)
        from rfauto.infra import db as db_mod
        from rfauto.service.dataset_service import materialize_dataset

        def _boom(self, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(db_mod.RegistryDB, "upsert_dataset", _boom)
        r = materialize_dataset(None, name="sync_fail", registry_sync=True)
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert any("注册表回写失败" in w for w in r.get("warnings", []))
        # 物化产物不受影响
        assert (tmp_path / "runs" / "datasets" / "sync_fail"
                / "points.parquet").exists()

    def test_visibility_flip_syncs_registry_and_manifest(self, tmp_path):
        self._seed_one_run(tmp_path)
        # visibility 回写无显式实参入口，开关走 settings 键
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        from rfauto.infra.db import RegistryDB
        from rfauto.service.dataset_insights import set_dataset_visibility
        from rfauto.service.dataset_service import materialize_dataset

        assert materialize_dataset(None, name="sync_vis", registry_sync=True)["ok"]
        r = set_dataset_visibility("sync_vis", "public")
        assert r["ok"] is True and r["registry_sync"] is True
        db = RegistryDB()
        try:
            assert db.get_dataset("sync_vis")["visibility"] == "public"
        finally:
            db.close()
        manifest = yaml.safe_load(
            (tmp_path / "runs" / "datasets" / "sync_vis" / "dataset_manifest.yaml")
            .read_text(encoding="utf-8"))
        assert manifest["visibility"] == "public"

    def test_visibility_default_off_no_db_file(self, tmp_path):
        self._seed_one_run(tmp_path)
        from rfauto.service.dataset_insights import set_dataset_visibility
        from rfauto.service.dataset_service import materialize_dataset

        assert materialize_dataset(None, name="vis_off")["ok"]
        r = set_dataset_visibility("vis_off", "public")
        assert r["ok"] is True and r["registry_sync"] is False
        assert not (tmp_path / "runs" / "registry.sqlite").exists()

    # -- import_workdir_runs（同型四例） ------------------------------------

    def test_import_default_off_no_db_file(self, workdir_env, tmp_path):
        from rfauto.service.dataset_service import import_workdir_runs

        r = import_workdir_runs(name="wd_off", health_gate=False)
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert not (tmp_path / "runs" / "registry.sqlite").exists()

    def test_import_explicit_on_row_queryable(self, workdir_env):
        from rfauto.service import db_service
        from rfauto.service.dataset_service import import_workdir_runs

        r = import_workdir_runs(name="wd_on", health_gate=False, registry_sync=True)
        assert r["ok"] is True and r["registry_sync"] is True
        out = db_service.db_query("SELECT name, visibility FROM datasets")
        assert out["ok"] is True
        assert out["rows"] == [["wd_on", "private"]]

    def test_import_settings_yaml_enables_without_explicit(self, workdir_env, tmp_path):
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        from rfauto.service.dataset_service import import_workdir_runs

        r = import_workdir_runs(name="wd_yaml", health_gate=False)
        assert r["ok"] is True and r["registry_sync"] is True

    def test_import_upsert_failure_does_not_block(self, workdir_env, monkeypatch):
        from rfauto.infra import db as db_mod
        from rfauto.service.dataset_service import import_workdir_runs

        def _boom(self, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(db_mod.RegistryDB, "upsert_dataset", _boom)
        r = import_workdir_runs(name="wd_fail", health_gate=False, registry_sync=True)
        assert r["ok"] is True
        assert r["registry_sync"] is False
        assert any("注册表回写失败" in w for w in r.get("warnings", []))

    # -- CLI 三态（#277：bool|None 选项，缺省不得被当显式 False 压掉配置） --

    def test_cli_registry_sync_three_states(self, tmp_path):
        self._seed_one_run(tmp_path)
        from typer.testing import CliRunner

        from rfauto.cli.main import app
        from rfauto.service import db_service

        runner = CliRunner()
        # 显式 --registry-sync：默认关配置下也入库
        r1 = runner.invoke(app, ["datasets", "materialize",
                                 "--name", "cli_sync_on", "--registry-sync"])
        assert r1.exit_code == 0, r1.output
        out = db_service.db_query("SELECT name, visibility FROM datasets")
        assert out["rows"] == [["cli_sync_on", "private"]]

        # 配置开 + 显式 --no-registry-sync：压过配置不入库
        (tmp_path / "configs").mkdir()
        (tmp_path / "configs" / "settings.yaml").write_text(
            "db:\n  dataset_registry_sync: true\n", encoding="utf-8")
        r2 = runner.invoke(app, ["datasets", "materialize",
                                 "--name", "cli_sync_off", "--no-registry-sync"])
        assert r2.exit_code == 0, r2.output
        out2 = db_service.db_query("SELECT name FROM datasets ORDER BY name")
        assert [row[0] for row in out2["rows"]] == ["cli_sync_on"]

        # 缺省（无 flag）读配置 true → 入库（三态关键档）
        r3 = runner.invoke(app, ["datasets", "materialize",
                                 "--name", "cli_sync_yaml"])
        assert r3.exit_code == 0, r3.output
        out3 = db_service.db_query("SELECT name FROM datasets ORDER BY name")
        assert [row[0] for row in out3["rows"]] == ["cli_sync_on", "cli_sync_yaml"]
