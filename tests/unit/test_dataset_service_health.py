"""E1 数据集注册表 v2 测试（健康门域）。

本文件承载：TestHealthGate（G11 unhealthy run 禁入注册表）与
TestHealthGatePartialMatrixReciprocity（部分 S 矩阵不构成互易证据的
掩码口径回归，含区块注释与局部 helper）。

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
)


class TestHealthGate:
    """G11 门禁接线：unhealthy/suspect run 禁入注册表（§10.17）。"""

    def test_unhealthy_run_excluded(self, runs_env):
        # run_a 塞进无源性违例 S 参数（|S|>1）→ 体检 FAIL → 被拦
        import numpy as np
        import skrf

        from rfauto.service.dataset_service import materialize_dataset

        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        s = np.full((5, 2, 2), 1.1) + 0.3j   # max|S| ≈ 1.14 > 1.01 无源性违例
        run_dir = runs_env / "runs" / "run_a" / "results"
        run_dir.mkdir(parents=True, exist_ok=True)
        skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(
            str(run_dir / "params.s2p"))
        res = materialize_dataset(["run_a", "run_b"], name="gate_ds")
        assert res["ok"]
        assert "run_a" in res["unhealthy_runs"]
        assert res["health_verdicts"]["run_a"] == "unhealthy"
        # run_b（仅 trials，cost 正常）不受牵连
        assert res["health_verdicts"].get("run_b") in ("healthy", "unknown")
        manifest = yaml.safe_load(
            Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_unhealthy_skipped"] == 1

    def test_gate_off_includes_everything(self, runs_env):
        import numpy as np
        import skrf

        from rfauto.service.dataset_service import materialize_dataset

        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        s = np.full((5, 2, 2), 0.9) + 0.2j
        s2p = runs_env / "runs" / "run_a" / "results" / "params.s2p"
        s2p.parent.mkdir(parents=True, exist_ok=True)
        skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(str(s2p))
        res = materialize_dataset(["run_a", "run_b"], name="nogate_ds",
                                  health_gate=False)
        assert res["ok"]
        assert res["unhealthy_runs"] == []
        manifest = yaml.safe_load(
            Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["health_gate"] is False

    def test_healthy_run_passes(self, runs_env):
        from rfauto.service.dataset_service import materialize_dataset

        res = materialize_dataset(["run_b"], name="healthy_ds")
        assert res["ok"]
        assert res["health_verdicts"].get("run_b") == "healthy"
        assert res["unhealthy_runs"] == []


# ---------------------------------------------------------------------------
# G11 部分 S 矩阵互易假阳性回归（审查修复队列增量①，2026-09-17 数据入库批
# 6 个 openEMS wilkinson/branchline 校准真机 run 被拦：单激励 sparams.csv 只测
# S11/S21/S31/S23 四个元素，S12/S13 置零，旧口径按全矩阵比 |S12−S21|=|S21|≈0.7
# ≥0.01 判互易违背）。修法：解析器给已测掩码，互易性只校两向都独立已测的
# 端口对，一对都没有 → UNKNOWN 不拦；Touchstone 全矩阵不带掩码，真互易破坏
# 仍按 0.01 拦（阈值语义不改）。
# ---------------------------------------------------------------------------

def _write_partial_sparams_csv(run_dir: Path, header: str, rows: list[str],
                               rel: str = "fdtd") -> Path:
    """按 openEMS sparams.csv schema 写部分矩阵产物（模板在 fdtd/ 子目录落盘）。"""
    target = run_dir / rel
    target.mkdir(parents=True, exist_ok=True)
    path = target / "sparams.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def _calib_run_with_samples(root: Path, run_id: str, model: str) -> Path:
    """校准形态 run（meta + calibration/samples.json 两个真跑点）——门放行后
    必须真的成行入库，而不是只在 unhealthy_runs 之外却因无产物被 skipped。"""
    run_dir = root / run_id
    _write_json(run_dir / "meta.json", _meta(
        run_id, model=model, adapter="calibration:openems",
        algorithm="calibration", study_name=f"calib_{run_id}", seed=None))
    _write_json(run_dir / "calibration" / "samples.json", {
        "bounds": {"series_w_mm": [0.5, 2.5]}, "objectives": [],
        "samples": [
            {"params": {"series_w_mm": 1.0}, "metrics": {"s21_db": -3.1}},
            {"params": {"series_w_mm": 1.5}, "metrics": {"s21_db": -3.0}},
        ]})
    return run_dir


# 9 列 = freq + 已测 4 元素（S11/S21/S31/S23）re/im：此前被拦的真机形态
_NINE_COL_HEADER = "freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23"
# 5 列 = freq + 已测 2 元素（S11/S21）re/im：patch 单馈校准形态
_FIVE_COL_HEADER = "freq_hz,re_S11,im_S11,re_S21,im_S21"


def _wilkinson_like_rows(n: int = 5) -> list[str]:
    """wilkinson 量级：|S11|≈0.05、|S21|=|S31|≈0.7（−3dB）、|S23|≈0.03（隔离）。"""
    return [
        f"{2.0e9 + k * 0.25e9:.1f},0.05,0.0,0.7,0.1,0.7,-0.1,0.03,0.0"
        for k in range(n)
    ]


class TestHealthGatePartialMatrixReciprocity:
    """G11 门禁：部分 S 矩阵不构成互易证据（UNKNOWN 放行），全矩阵真破坏仍拦。"""

    def test_nine_col_single_excitation_csv_is_previously_blocked_shape(self, runs_env):
        """自证样本形态：同一部分矩阵不带掩码（旧口径）确实判 FAIL，
        |S12−S21| = |0 − S21| ≈ 0.71 ≥ 0.01——这正是 6 个真机 run 被拦的机制。"""
        import numpy as np

        from rfauto.core.solve_health import solve_health_check
        from rfauto.service.health_service import _parse_sparams_csv_masked

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_wilk", "wilkinson_power_divider")
        path = _write_partial_sparams_csv(run_dir, _NINE_COL_HEADER, _wilkinson_like_rows())
        parsed = _parse_sparams_csv_masked(path)
        assert parsed is not None
        freq_hz, s, mask = parsed
        assert s.shape == (5, 3, 3)
        # 已测掩码只标 csv 列直接来源的 4 个元素；S32:=S23 的互易补齐不算独立测量
        expected_mask = np.zeros((3, 3), dtype=bool)
        expected_mask[0, 0] = expected_mask[1, 0] = expected_mask[2, 0] = expected_mask[1, 2] = True
        assert np.array_equal(mask, expected_mask)
        # 旧口径（无掩码 = 全矩阵已测）：置零 S12 对已测 S21 → 假阳性 FAIL
        old = solve_health_check(freq_hz=freq_hz, s_matrix=s)
        old_rec = next(f for f in old["factors"] if f["factor"] == "reciprocity")
        assert old_rec["status"] == "FAIL"
        assert abs(old_rec["evidence"]["max_asym"] - abs(0.7 + 0.1j)) < 1e-9
        assert old["verdict"] == "unhealthy"
        # 新口径（带掩码）：0/3 对独立已测 → UNKNOWN，不拦
        new = solve_health_check(freq_hz=freq_hz, s_matrix=s, s_measured_mask=mask)
        new_rec = next(f for f in new["factors"] if f["factor"] == "reciprocity")
        assert new_rec["status"] == "UNKNOWN"
        assert new_rec["evidence"]["partial_matrix"] is True
        assert new_rec["evidence"]["n_measured_pairs"] == 0
        assert new_rec["evidence"]["n_pairs_total"] == 3
        assert new["verdict"] == "healthy"

    def test_nine_col_single_excitation_run_passes_gate_and_lands_rows(self, runs_env):
        """端到端：此前被拦形态的校准 run 经 materialize 门 → 放行且真的成行。"""
        from rfauto.service.dataset_service import materialize_dataset
        from rfauto.service.health_service import health_check_run

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_wilk", "wilkinson_power_divider")
        _write_partial_sparams_csv(run_dir, _NINE_COL_HEADER, _wilkinson_like_rows())

        hc = health_check_run("run_wilk")
        statuses = {f["factor"]: f["status"] for f in hc["factors"]}
        assert statuses["reciprocity"] == "UNKNOWN"
        assert statuses["excitation"] == "PASS"
        assert statuses["passivity"] == "PASS"
        assert hc["verdict"] == "healthy"

        res = materialize_dataset(["run_wilk", "run_b"], name="partial_ok")
        assert res["ok"], res.get("errors")
        assert "run_wilk" not in res["unhealthy_runs"]
        assert "run_wilk" not in res["skipped_runs"]
        assert res["health_verdicts"]["run_wilk"] == "healthy"
        manifest = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_unhealthy_skipped"] == 0
        assert {s["run_id"] for s in manifest["source_runs"]} >= {"run_wilk"}
        # run_wilk 两个校准样本 + run_b 两个 trial = 4 点，无重复
        assert res["n_points"] == 4 and res["n_rows"] == 4

    def test_five_col_single_feed_csv_reciprocity_unknown_not_blocked(self, runs_env):
        """2 端口单激励（patch 单馈形态，5 列）：S12/S22 全是补齐值，0/1 对独立已测
        → UNKNOWN 如实（不凑 PASS），门放行。"""
        from rfauto.service.dataset_service import materialize_dataset
        from rfauto.service.health_service import health_check_run

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_patch", "patch_antenna")
        rows = [f"{1.8e9 + k * 0.1e9:.1f},0.3,0.2,0.05,0.01" for k in range(5)]
        _write_partial_sparams_csv(run_dir, _FIVE_COL_HEADER, rows)

        hc = health_check_run("run_patch")
        rec = next(f for f in hc["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "UNKNOWN"
        assert rec["evidence"]["n_measured_pairs"] == 0
        assert rec["evidence"]["n_pairs_total"] == 1
        assert hc["verdict"] == "healthy"

        res = materialize_dataset(["run_patch"], name="patch_ok")
        assert res["ok"], res.get("errors")
        assert res["unhealthy_runs"] == []
        assert res["health_verdicts"]["run_patch"] == "healthy"
        assert res["n_rows"] == 2

    def test_full_matrix_reciprocity_violation_still_blocked(self, runs_env):
        """阈值语义不改：Touchstone 全矩阵（HFSS/ADS 导出形态）S12≠S21 差 0.1 ≥ 0.01
        → 互易性 FAIL → unhealthy → 仍拦在注册表之外，即便它带校准样本。"""
        import numpy as np
        import skrf

        from rfauto.service.dataset_service import materialize_dataset
        from rfauto.service.health_service import health_check_run

        run_dir = _calib_run_with_samples(runs_env / "runs", "run_asym", "wilkinson_power_divider")
        freq = skrf.Frequency(2.0, 3.0, 5, unit="GHz")
        s = np.zeros((5, 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = 0.05
        s[:, 1, 0] = 0.7
        s[:, 0, 1] = 0.6  # |S12−S21| = 0.1 ≥ 0.01：真互易破坏
        (run_dir / "results").mkdir(parents=True, exist_ok=True)
        skrf.Network(frequency=freq, s=s, z0=50.0).write_touchstone(
            str(run_dir / "results" / "params.s2p"))

        hc = health_check_run("run_asym")
        rec = next(f for f in hc["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "FAIL"
        assert abs(rec["evidence"]["max_asym"] - 0.1) < 1e-6
        assert "partial_matrix" not in rec["evidence"]  # 全矩阵路径不带掩码
        assert hc["verdict"] == "unhealthy"

        res = materialize_dataset(["run_asym", "run_b"], name="asym_blocked")
        assert res["ok"], res.get("errors")
        assert res["unhealthy_runs"] == ["run_asym"]
        assert res["health_verdicts"]["run_asym"] == "unhealthy"
        manifest = yaml.safe_load(Path(res["manifest"]).read_text(encoding="utf-8"))
        assert manifest["n_unhealthy_skipped"] == 1
        assert {s["run_id"] for s in manifest["source_runs"]} == {"run_b"}

    def test_partial_matrix_measured_pair_violation_still_fails(self, runs_env):
        """掩码只放行未测对；两向都独立已测且违背的对仍 FAIL（阈值 0.01 原样）。
        合成掩码把 (1,2)/(2,1) 都标已测并注入 0.4 非对称——不能因矩阵
        "部分"就放过真破坏。"""
        import numpy as np

        from rfauto.core.solve_health import solve_health_check

        n = 5
        s = np.zeros((n, 3, 3), dtype=complex)
        s[:, 0, 0] = 0.05
        s[:, 1, 0] = s[:, 2, 0] = 0.7
        s[:, 1, 2] = 0.5
        s[:, 2, 1] = 0.9  # |S32−S23| = 0.4
        mask = np.zeros((3, 3), dtype=bool)
        mask[0, 0] = mask[1, 0] = mask[2, 0] = mask[1, 2] = mask[2, 1] = True
        report = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, n), s_matrix=s, s_measured_mask=mask)
        rec = next(f for f in report["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "FAIL"
        assert abs(rec["evidence"]["max_asym"] - 0.4) < 1e-9
        assert rec["evidence"]["n_measured_pairs"] == 1  # 只有 (1,2) 对参与
        assert rec["evidence"]["unmeasured_pairs"] == [[0, 1], [0, 2]]
        assert report["verdict"] == "unhealthy"
        # 同掩码、把 (1,2) 对修成互易 → PASS 且证据标明 1/3 对已校
        s[:, 2, 1] = 0.5
        ok = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, n), s_matrix=s, s_measured_mask=mask)
        rec_ok = next(f for f in ok["factors"] if f["factor"] == "reciprocity")
        assert rec_ok["status"] == "PASS"
        assert rec_ok["evidence"]["n_measured_pairs"] == 1
        assert rec_ok["evidence"]["n_pairs_total"] == 3

    def test_malformed_mask_falls_back_to_full_matrix_rule(self, runs_env):
        """形状不符的掩码宁可回退全矩阵口径（最多多报 FAIL 让人来看），
        不得静默按"全未测"放过真破坏。"""
        import numpy as np

        from rfauto.core.solve_health import solve_health_check

        s = np.zeros((4, 2, 2), dtype=complex)
        s[:, 1, 0] = 0.7
        s[:, 0, 1] = 0.6  # 真破坏 0.1
        bad_mask = np.zeros((3, 3), dtype=bool)  # 2 端口给了 3×3
        report = solve_health_check(
            freq_hz=np.linspace(2e9, 3e9, 4), s_matrix=s, s_measured_mask=bad_mask)
        rec = next(f for f in report["factors"] if f["factor"] == "reciprocity")
        assert rec["status"] == "FAIL"
        assert "partial_matrix" not in rec["evidence"]

    def test_legacy_parse_sparams_csv_keeps_two_tuple_contract(self, runs_env):
        """calibration 侧（fsv 曲线复算等）按 2 元组解包 _parse_sparams_csv，契约不变。"""
        from rfauto.service.health_service import _parse_sparams_csv

        run_dir = runs_env / "runs" / "legacy"
        path = _write_partial_sparams_csv(run_dir, _NINE_COL_HEADER, _wilkinson_like_rows())
        parsed = _parse_sparams_csv(path)
        assert parsed is not None
        assert len(parsed) == 2
        freq_hz, s = parsed
        assert freq_hz.shape == (5,) and s.shape == (5, 3, 3)
