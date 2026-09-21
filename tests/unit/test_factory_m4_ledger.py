"""B1 M4 摊销台账单测（scripts/factory_m4_ledger.py，全部 tmp_path 隔离）。

钉住：①scan 双指纹语义（surrogate_loop 类 + 库存关联才计数；wp39 引擎
战役 excluded；解析失败 unreadable 不凑数）；②--add 手工登记按 id 幂等；
③ledger 汇总字段（K=自动+手工、常数来源、摊销状态三档）。
禁读真 runs/：全部构造在 tmp_path（#144 隔离口径）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
for _p in (REPO / "src", SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_SPEC = importlib.util.spec_from_file_location(
    "factory_m4_ledger", SCRIPTS / "factory_m4_ledger.py")
assert _SPEC is not None and _SPEC.loader is not None
ledger_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ledger_mod)


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def _stock_campaign(path: Path) -> Path:
    """M4 bench 形态：surrogate_loop 指纹 + 数据工厂库存引用（应计数）。"""
    return _write_json(path, {
        "schema_version": 1,
        "created_at": "2026-09-20T08:00:15+00:00",
        "criteria": {"baseline_s": 1457.74},
        "stock": {"path": "runs\\datasets\\datafactory_m1_mline_20260919\\points.parquet",
                  "n_rows": 120},
        "timing": {"t_loop_s": 23.35, "n_queries": 22},
        "loop": {"ok": True, "algorithm": "surrogate_loop", "n_queries": 22,
                 "n_real_used": 22},
    })


class TestScan:
    def test_counts_stock_linked_surrogate_loop(self, tmp_path: Path) -> None:
        _stock_campaign(tmp_path / "runs" / "datafactory_m4" / "m4_offline.json")
        scan = ledger_mod.scan_campaigns(tmp_path / "runs")
        assert len(scan["counted"]) == 1
        entry = scan["counted"][0]
        assert entry["path"] == "datafactory_m4/m4_offline.json"
        assert entry["algorithm"] == "surrogate_loop"
        assert entry["n_queries"] == 22
        assert "points.parquet" in (entry["stock_ref"] or "")
        assert scan["excluded"] == [] and scan["unreadable"] == []

    def test_excludes_engine_campaign_without_stock(self, tmp_path: Path) -> None:
        """wp39_mvp 系引擎真解 SBO 战役：有指纹无库存引用 -> 不计 K。"""
        _write_json(tmp_path / "runs" / "wp39_mvp" / "mline__sbo.json", {
            "schema": "wp39_mvp_campaign_v1", "problem": "mline",
            "engine": "sbo", "stage": "done", "budget": 25,
            "wall_s": 1234.5, "n_evals": 25,
        })
        scan = ledger_mod.scan_campaigns(tmp_path / "runs")
        assert scan["counted"] == []
        assert len(scan["excluded"]) == 1
        assert scan["excluded"][0]["path"] == "wp39_mvp/mline__sbo.json"
        assert "无数据工厂库存引用" in scan["excluded"][0]["reason"]

    def test_run_dir_multifidelity_campaign_excluded(self, tmp_path: Path) -> None:
        """run 目录战役（mf_sbo 双保真）：引擎解算无库存引用 -> excluded。"""
        run_dir = tmp_path / "runs" / "20260101_000000_ab12cd34"
        _write_json(run_dir / "surrogate_loop.json", {
            "algorithm": "multifidelity_surrogate_loop",
            "adapter": "mf_sbo:fake+fake", "run_id": "20260101_000000_ab12cd34",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        _write_json(run_dir / "meta.json", {
            "run_id": "20260101_000000_ab12cd34",
            "algorithm": "multifidelity_surrogate_loop", "status": "done",
        })
        scan = ledger_mod.scan_campaigns(tmp_path / "runs")
        # 同一 run 目录两个指纹文件是两份档案，逐文件去重后 2 条 excluded、0 计数
        assert scan["counted"] == []
        assert len(scan["excluded"]) == 2
        assert {e["path"] for e in scan["excluded"]} == {
            "20260101_000000_ab12cd34/surrogate_loop.json",
            "20260101_000000_ab12cd34/meta.json",
        }

    def test_unreadable_marker_file_not_counted(self, tmp_path: Path) -> None:
        """关键字命中但解析失败：不计数、如实列 unreadable（禁凑数）。"""
        bad = tmp_path / "runs" / "datafactory_m4" / "broken.json"
        bad.parent.mkdir(parents=True)
        bad.write_text('{"loop": {"algorithm": "surrogate_loop"', encoding="utf-8")
        scan = ledger_mod.scan_campaigns(tmp_path / "runs")
        assert scan["counted"] == []
        assert len(scan["unreadable"]) == 1
        assert scan["unreadable"][0]["path"] == "datafactory_m4/broken.json"

    def test_non_campaign_json_ignored(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "runs" / "some_run" / "metrics.json",
                    {"cost": 1.0, "adapter": "fake"})
        scan = ledger_mod.scan_campaigns(tmp_path / "runs")
        assert scan == {"counted": [], "excluded": [], "unreadable": []}

    def test_missing_runs_dir_is_empty(self, tmp_path: Path) -> None:
        scan = ledger_mod.scan_campaigns(tmp_path / "nope")
        assert scan == {"counted": [], "excluded": [], "unreadable": []}


class TestManualEntries:
    def test_add_and_idempotent(self, tmp_path: Path) -> None:
        first = ledger_mod.add_manual_entry(tmp_path, "m4-run2-refine",
                                            date="2026-09-20", note="谷芯加密验证腿")
        assert first == {"ok": True, "already_present": False,
                         "id": "m4-run2-refine", "n_entries": 1}
        again = ledger_mod.add_manual_entry(tmp_path, "m4-run2-refine")
        assert again["ok"] and again["already_present"] is True
        assert again["n_entries"] == 1
        entries = ledger_mod.load_manual_entries(tmp_path)
        assert [e["id"] for e in entries] == ["m4-run2-refine"]
        assert entries[0]["origin"] == "manual"

    def test_add_distinct_ids_append(self, tmp_path: Path) -> None:
        ledger_mod.add_manual_entry(tmp_path, "a")
        ledger_mod.add_manual_entry(tmp_path, "b")
        assert [e["id"] for e in ledger_mod.load_manual_entries(tmp_path)] == ["a", "b"]

    def test_add_rejects_blank_id(self, tmp_path: Path) -> None:
        result = ledger_mod.add_manual_entry(tmp_path, "   ")
        assert result["ok"] is False
        assert ledger_mod.load_manual_entries(tmp_path) == []

    def test_corrupt_lines_skipped(self, tmp_path: Path) -> None:
        d = tmp_path / ledger_mod.LEDGER_DIRNAME
        d.mkdir(parents=True)
        (d / ledger_mod.ENTRIES_FILENAME).write_text(
            '{"id": "ok1"}\nnot-json\n{"no_id": true}\n', encoding="utf-8")
        assert [e["id"] for e in ledger_mod.load_manual_entries(tmp_path)] == ["ok1"]


class TestLedger:
    def test_summary_fields_and_status_recovering(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        _stock_campaign(runs / "datafactory_m4" / "m4_offline.json")
        ledger_mod.add_manual_entry(runs, "manual-1")
        doc = ledger_mod.build_ledger(runs)
        assert doc["k_auto"] == 1 and doc["k_manual"] == 1
        assert doc["k_current"] == 2
        assert doc["k_current"] < doc["constants"]["breakeven_k"]
        assert doc["amortization_status"] == "回收中"
        assert doc["campaigns"][0]["path"] == "datafactory_m4/m4_offline.json"
        assert doc["manual_entries"][0]["id"] == "manual-1"
        # 一期实测常数在档（声明常数兜底档）
        assert doc["constants"]["breakeven_k"] == pytest.approx(3.35)
        assert doc["constants"]["target_5x_k"] == pytest.approx(16.7)
        assert "declared" in doc["constants"]["source"]

    def test_constants_prefer_verdict_measured(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        _write_json(runs / "datafactory_m4" / "m4_verdict.json", {
            "amortization": {"k_breakeven_measured": 3.347,
                             "k_for_5x_amortized": 16.74},
        })
        doc = ledger_mod.build_ledger(runs)
        assert doc["constants"]["breakeven_k"] == pytest.approx(3.347)
        assert doc["constants"]["target_5x_k"] == pytest.approx(16.74)
        assert "m4_verdict.json" in doc["constants"]["source"]

    def test_status_recovered_then_5x(self, tmp_path: Path) -> None:
        # 已回收：breakeven ≤ K < 5×（3.35 ≤ 4 < 16.7）
        for i in range(4):
            ledger_mod.add_manual_entry(tmp_path, f"m{i}")
        doc = ledger_mod.build_ledger(tmp_path)
        assert doc["k_current"] == 4
        assert doc["amortization_status"] == "已回收"
        # ≥5×达成：K ≥ 16.7（17 场）
        for i in range(4, 17):
            ledger_mod.add_manual_entry(tmp_path, f"m{i}")
        doc = ledger_mod.build_ledger(tmp_path)
        assert doc["k_current"] == 17
        assert doc["amortization_status"] == "≥5×达成"

    def test_write_ledger_file(self, tmp_path: Path) -> None:
        doc = ledger_mod.build_ledger(tmp_path)
        out = ledger_mod.write_ledger(tmp_path, doc)
        assert out == tmp_path / ledger_mod.LEDGER_DIRNAME / ledger_mod.LEDGER_FILENAME
        reread = json.loads(out.read_text(encoding="utf-8"))
        assert reread["k_current"] == 0
        assert reread["amortization_status"] == "回收中"
        assert reread["semantics"]["unit"].startswith("一场 =")

    def test_cli_scan_and_add_end_to_end(self, tmp_path: Path, capsys) -> None:
        _stock_campaign(tmp_path / "runs" / "datafactory_m4" / "m4_offline.json")
        runs = str(tmp_path / "runs")
        assert ledger_mod.main(["--add", "m4-run2-refine", "--runs-dir", runs]) == 0
        assert ledger_mod.main(["--scan", "--runs-dir", runs]) == 0
        out_text = capsys.readouterr().out
        assert "K 当前 = 2" in out_text and "回收中" in out_text
        reread = json.loads(
            (tmp_path / "runs" / ledger_mod.LEDGER_DIRNAME
             / ledger_mod.LEDGER_FILENAME).read_text(encoding="utf-8"))
        assert reread["k_auto"] == 1 and reread["k_manual"] == 1

    def test_cli_no_args_exit_2(self) -> None:
        assert ledger_mod.main([]) == 2
