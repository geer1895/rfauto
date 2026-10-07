"""E1 数据集注册表 v2 测试（单次 run域）。

本文件承载：⑤ 单次 run 产物分支（api.run_once 通道）——
_write_run_once_run 局部 helper、TestRunOncePoints（无 ①—④ 产物的
单次 run 物化为恰一个点）、TestRunOnceTouchstoneProvenance
（曲线级 touchstone_path/n_ports provenance）。

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


def _write_run_once_run(
    root: Path,
    run_id: str,
    *,
    status: str = "done",
    with_metrics: bool = True,
    with_snapshot: bool = True,
    with_trials: bool = False,
    touchstone_ports: int | None = None,
) -> None:
    """合成一个 run_once 风格 run：meta + results/metrics.json +
    recipe.snapshot.yaml（含 3 个设计变量与标量元参数），可选再挂 trials；
    ``touchstone_ports=N`` 时再落 results/params.sNp（曲线级关联用例）。"""
    run_dir = root / "runs" / run_id
    _write_json(run_dir / "meta.json", _meta(
        run_id, model="patch_antenna", adapter="hfss", algorithm="",
        study_name="", seed=None, status=status))
    if with_snapshot:
        (run_dir / "recipe.snapshot.yaml").write_text(yaml.safe_dump({
            "model": "patch_antenna", "recipe_version": 1, "schema_version": 1,
            "params": {
                "f0_ghz": {"value": 2.4, "unit": "GHz"},
                "z0_ohm": {"value": 50, "unit": "ohm"},
                "substrate": "rogers4350b_h0.508",
                "patch_len_mm": {"value": 41.5744},
                "patch_w_mm": {"value": 51.3874},
                "feed_offset_mm": {"value": 15.2078},
            },
            "optimization": {"params": {
                "patch_len_mm": {"low": 35.0, "high": 45.0},
                "feed_offset_mm": {"low": 3.0, "high": 20.0},
                "patch_w_mm": {"low": 40.0, "high": 60.0},
            }},
        }, sort_keys=False), encoding="utf-8")
    if with_metrics:
        _write_json(run_dir / "results" / "metrics.json", {
            "run_id": run_id, "schema_version": 1,
            "params": {
                "f0_ghz": 2.4, "z0_ohm": 50,
                "substrate": "rogers4350b_h0.508",
                "patch_len_mm": 41.5744, "patch_w_mm": 51.3874,
                "feed_offset_mm": 15.2078,
            },
            "metrics": {"s11_db_max_in_band": -2.3681,
                        "s11_db_min_in_band": -3.1109},
            "cost": 7.6319,
            "checks": {"passivity_ok": True},
        })
    if with_trials:
        _write_json(run_dir / "trials" / "trial_0.json", {
            "trial_number": 0, "params": {"patch_len_mm": 40.0},
            "metrics": {"s11_db_max_in_band": -9.0}, "cost": 0.1})
    if touchstone_ports is not None:
        _write_touchstone(
            run_dir / "results" / f"params.s{touchstone_ports}p",
            touchstone_ports)


class TestRunOncePoints:
    """⑤ 分支：无 ①—④ 产物的单次 run（status=done + results/metrics.json）
    物化为恰一个点（WP3.4 HFSS GT 战役 36 run 成行的通道）。"""

    def test_run_once_dir_yields_single_gt_point(self, tmp_path, monkeypatch):
        """恰 1 点：adapter/model/params（仅设计变量键）/metrics 正确，
        cost NULL、provenance 带 run_id、健康门不拦、GT 标注计数 +1。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_once")

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_once"], name="ro_ds")  # 默认健康门
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1 and res["n_dup"] == 0
        assert res["skipped_runs"] == [] and res["unhealthy_runs"] == []

        q = query_dataset("ro_ds")
        assert q["ok"] and q["n_rows"] == 1
        row = q["rows"][0]
        assert row["run_id"] == "ro_once"
        assert row["model"] == "patch_antenna" and row["adapter"] == "hfss"
        assert row["source"] == "run_once" and row["algorithm"] == "run_once"
        assert row["study_name"] == "" and row["seed"] is None
        assert row["cost"] is None  # 可空列契约：单次 run 无统一 cost 语义
        # params 只含 optimization.params 设计变量键（f0_ghz/z0_ohm/substrate
        # 元参数不进 params_json，与注册表既有 GT 行参数列同口径）
        assert row["params_json"] == (
            '{"feed_offset_mm":15.2078,"patch_len_mm":41.5744,'
            '"patch_w_mm":51.3874}')
        assert json.loads(row["metrics_json"]) == {
            "s11_db_max_in_band": -2.3681, "s11_db_min_in_band": -3.1109}
        prov = json.loads(row["provenance_json"])
        assert prov["run_id"] == "ro_once"      # ⑤ 分支 provenance 补带 run_id
        assert prov["git_sha"] == "abc1234"     # 既有 provenance 字段保留
        # 无 Touchstone 产物：曲线级两键不出现（provenance 逐字节不变）
        assert "touchstone_path" not in prov and "n_ports" not in prov

        import yaml as _yaml

        manifest = _yaml.safe_load(
            Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["ground_truth"]["n_gt_rows"] == 1
        assert manifest["ground_truth"]["per_model"] == {"patch_antenna": 1}

    def test_run_once_missing_metrics_skipped_not_blocking(self, tmp_path, monkeypatch):
        """缺 results/metrics.json：跳过并记 collect_errors 透出（#105
        best-effort 不阻塞），同批健康 run 照常成行。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_good")
        _write_run_once_run(tmp_path, "ro_nometrics", with_metrics=False)

        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["ro_good", "ro_nometrics"], name="ro_ds2",
                                  health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1
        assert res["skipped_runs"] == ["ro_nometrics"]
        assert any("results/metrics.json" in w
                   for w in res.get("warnings", []))

    def test_run_once_with_trials_not_double_counted(self, tmp_path, monkeypatch):
        """既有 trials 产物时走 ① 不触发 ⑤：同 run 有 metrics.json 也不双计。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_both", with_trials=True)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_both"], name="ro_ds3", health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1
        q = query_dataset("ro_ds3")
        row = q["rows"][0]
        assert row["source"] == "trials" and row["algorithm"] == "tune"
        assert row["params_json"] == '{"patch_len_mm":40.0}'
        assert row["cost"] == pytest.approx(0.1)

    def test_run_once_status_not_done_silently_skipped(self, tmp_path, monkeypatch):
        """status != done（在跑/失败）：即使 metrics.json 在也不收点，
        且不产生警告（非 done run 静默跳过维持旧口径）。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_nr", status="running")

        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["ro_nr"], name="ro_ds4", health_gate=False)
        assert not res["ok"]  # 零点：如实 ok=False（既有 no_points 契约）
        assert res["skipped_runs"] == ["ro_nr"]
        # 非 done run 静默跳过：collect_errors 里不出现该 run 的指责
        assert all("ro_nr" not in e for e in res["errors"])

    def test_run_once_missing_snapshot_errors_but_no_crash(self, tmp_path, monkeypatch):
        """recipe.snapshot.yaml 缺失：解析失败记 error 不抛（#105），
        该 run 零点，不阻塞同批其他 run。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_good")
        _write_run_once_run(tmp_path, "ro_nosnap", with_snapshot=False)

        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["ro_good", "ro_nosnap"], name="ro_ds5",
                                  health_gate=False)
        assert res["ok"], res.get("errors")
        assert res["n_points"] == 1 and res["n_rows"] == 1
        assert res["skipped_runs"] == ["ro_nosnap"]
        assert any("recipe.snapshot.yaml" in w
                   for w in res.get("warnings", []))


# ---------------------------------------------------------------------------
# ⑤ 分支曲线级关联：provenance 带 touchstone_path / n_ports（数据工厂第一步，
# 曲线级神经算子 A/B 铺路——消费侧不再写死 results/params.s1p）
# ---------------------------------------------------------------------------

class TestRunOnceTouchstoneProvenance:
    """results/params.sNp 在时 ⑤ 点 provenance 多带 touchstone_path（相对
    run 目录 posix 路径）与 n_ports（int）；不在时两键缺席。①—④ 分支不动。"""

    def test_s1p_present_provenance_has_path_and_ports(self, tmp_path, monkeypatch):
        """带 params.s1p 的 run_once（WP3.4 HFSS patch 口径）：默认健康门
        放行（合成网络无源），provenance 带 touchstone_path='results/params.s1p'
        与 n_ports=1（JSON 里是整数不是字符串）。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_s1p", touchstone_ports=1)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_s1p"], name="ts_ds1")  # 默认健康门
        assert res["ok"], res.get("errors")
        assert res["n_rows"] == 1 and res["unhealthy_runs"] == []
        row = query_dataset("ts_ds1")["rows"][0]
        prov = json.loads(row["provenance_json"])
        assert prov["run_id"] == "ro_s1p"
        assert prov["touchstone_path"] == "results/params.s1p"
        assert prov["n_ports"] == 1 and isinstance(prov["n_ports"], int)
        # 相对路径可直接拼回 run 目录命中真实文件（消费侧契约）
        assert (tmp_path / "runs" / "ro_s1p" / prov["touchstone_path"]).is_file()
        # 曲线级键不进 params/metrics 列（只在 provenance）
        assert "touchstone_path" not in row["params_json"]
        assert "touchstone_path" not in row["metrics_json"]

    def test_no_touchstone_keys_absent(self, tmp_path, monkeypatch):
        """不带 sNp 的 run_once：provenance 只有 run_id 等既有键，两个曲线级
        键缺席（与 WP3.4 收尾口径逐字节一致）；同批带 s1p 的 run 不受牵连。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_plain")
        _write_run_once_run(tmp_path, "ro_curve", touchstone_ports=1)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        res = materialize_dataset(["ro_plain", "ro_curve"], name="ts_ds2",
                                  health_gate=False)
        assert res["ok"], res.get("errors")
        # 两 run 参数点相同（同合成快照）→ 指纹去重只留首个（ro_curve 排序
        # 在前）；用 run_ids 分别物化避免去重干扰逐 run 断言
        by_run: dict[str, dict] = {}
        for rid in ("ro_plain", "ro_curve"):
            r = materialize_dataset([rid], name=f"ts_{rid}", health_gate=False)
            assert r["ok"], r.get("errors")
            by_run[rid] = json.loads(
                query_dataset(f"ts_{rid}")["rows"][0]["provenance_json"])
        assert "touchstone_path" not in by_run["ro_plain"]
        assert "n_ports" not in by_run["ro_plain"]
        assert by_run["ro_plain"]["run_id"] == "ro_plain"
        assert by_run["ro_curve"]["touchstone_path"] == "results/params.s1p"
        assert by_run["ro_curve"]["n_ports"] == 1

    def test_multiport_s2p_s3p_ports_parsed(self, tmp_path, monkeypatch):
        """多端口：params.s2p → n_ports=2、params.s3p → n_ports=3（wilkinson
        3 端口/branchline 4 端口同路径），路径后缀随端口数变。"""
        monkeypatch.chdir(tmp_path)
        _write_run_once_run(tmp_path, "ro_2p", touchstone_ports=2)
        _write_run_once_run(tmp_path, "ro_3p", touchstone_ports=3)
        _write_run_once_run(tmp_path, "ro_4p", touchstone_ports=4)

        from rfauto.service.dataset_service import materialize_dataset, query_dataset

        for rid, n in (("ro_2p", 2), ("ro_3p", 3), ("ro_4p", 4)):
            r = materialize_dataset([rid], name=f"mp_{rid}", health_gate=False)
            assert r["ok"], r.get("errors")
            prov = json.loads(
                query_dataset(f"mp_{rid}")["rows"][0]["provenance_json"])
            assert prov["touchstone_path"] == f"results/params.s{n}p", rid
            assert prov["n_ports"] == n and isinstance(prov["n_ports"], int)

    def test_run_touchstone_helper_edge_cases(self, tmp_path):
        """helper 直测：大小写不敏感（.S4P）、非 params.* 前缀/带后缀名不认、
        缺 results 目录 → None、多候选按文件名排序取首个（确定性）。"""
        from rfauto.service.dataset_service import _run_touchstone

        # 缺 results 目录
        assert _run_touchstone(tmp_path / "nope") is None
        run = tmp_path / "r"
        (run / "results").mkdir(parents=True)
        # 只有不认的名字：other.s2p / params.s2p.bak / params.sp / 目录同名
        (run / "results" / "other.s2p").write_text("! x", encoding="utf-8")
        (run / "results" / "params.s2p.bak").write_text("! x", encoding="utf-8")
        (run / "results" / "params.sp").write_text("! x", encoding="utf-8")
        (run / "results" / "params.s0p").write_text("! x", encoding="utf-8")
        assert _run_touchstone(run) is None
        # 大小写不敏感：params.S4P → n_ports=4，路径保留原文件名
        (run / "results" / "params.S4P").write_text("! x", encoding="utf-8")
        got = _run_touchstone(run)
        assert got is not None and got[1] == 4
        assert got[0].lower() == "results/params.s4p"
        # 多候选按小写名排序：s0p（端口数 0 不认，跳过）< s1p < s4p → 取 s1p
        # （若按原始名排序 'S'(0x53) 会排在 's'(0x73) 前而错取 S4P）
        (run / "results" / "params.s1p").write_text("! x", encoding="utf-8")
        assert _run_touchstone(run) == ("results/params.s1p", 1)
