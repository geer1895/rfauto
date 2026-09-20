"""WP1.2 mline 引擎基准 2026-09-13 复扫证据 golden 钉子（离线零真机）。

背景：复扫真跑产物只落 runs/benchmark/（runs/ 不入库），可提交证据面为空。
按 tests/golden/ 惯例（参照 wilkinson_fake_baseline.json）把复扫结果快照入库：
tests/golden/mline_benchmark_rescan_20260913.json。本文件离线回放三件事：
① 快照结构自检（防证据文件本身被误改坏）；
② 快照逐档数据过判据内核 core/anchor_verdict.mline_benchmark_verdict
   四门（收敛/主锚金标准/副锚 HJ/健康）→ PASS——升级/换机后重跑 harness
   出现判据漂移时，本钉子与 live JSON 一起给出历史一致性参照；
③ 对 #189 预扫备份的逐档复现一致性：最细档 2.8813 五位小数逐位一致、
   其余三档差 ≤3e-5。

证据源真跑命令（本测试不执行任何求解）：
  .venv/Scripts/python.exe scripts/engine_benchmark_mline.py
  → runs/benchmark/mline_mesh_convergence.json
  日志尾：ENGINE_BENCHMARK_MLINE_PASS（runs/benchmark/rescan_20260913.log）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.core.anchor_verdict import mline_benchmark_verdict

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "golden" / "mline_benchmark_rescan_20260913.json"


def _load() -> dict:
    assert GOLDEN.exists(), "复扫证据 golden 缺失：tests/golden/mline_benchmark_rescan_20260913.json"
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


class TestRescanSnapshotShape:
    """证据文件结构自检：防止快照被误改坏后回放测试空转。"""

    def test_provenance_and_result_present(self):
        data = _load()
        assert data["kind"] == "engine_benchmark_mline_rescan"
        for key in ("harness", "live_result", "pre_rescan_backup"):
            assert data["provenance"][key], f"provenance.{key} 缺失"
        assert isinstance(data["result"], dict)
        assert isinstance(data["pre_rescan_189"]["eps_eff_by_mesh"], list)

    def test_four_tiers_all_ok(self):
        result = _load()["result"]
        assert result["anchor"] == "mline"
        assert result["w_mm"] == 1.113
        assert result["judge_freq_ghz"] == 2.5
        assert [e["mesh_mm"] for e in result["entries"]] == [0.0, 0.6, 0.4, 0.25]
        assert all(e["ok"] for e in result["entries"]), "存在失败档：快照不完整"
        assert result["verdict"] == "PASS"

    def test_criteria_match_kernel_gates(self):
        # 快照 criteria 与内核默认门一致（判据改动=显式重标定，须同步快照）
        result = _load()["result"]
        assert result["criteria"] == {
            "convergence_pct_lt": 1.0,
            "delta_vs_gold_pct_abs_le": 2.0,
            "delta_vs_hj_pct_abs_le": 3.0,
            "s11_max_db_lt": -10,
        }
        assert result["eps_gold_standard"] == 2.886


class TestRescanReplayThroughKernel:
    """快照数据过 mline_benchmark_verdict 四门 → PASS（判据内核回放）。"""

    def test_recorded_data_passes_dual_anchor_kernel(self):
        result = _load()["result"]
        ok = [e for e in result["entries"] if e["ok"]]
        # 收敛性按 harness 同式重算（最细两档相对移动），须与快照记录一致
        conv = round(
            abs(ok[-1]["eps_eff"] - ok[-2]["eps_eff"]) / ok[-1]["eps_eff"] * 100,
            4,
        )
        assert conv == result["convergence_finest2_pct"]
        s11_worst = max(e["s11_max_db"] for e in ok)
        r = mline_benchmark_verdict(
            ok[-1]["eps_eff"], conv, s11_worst,
            result["eps_gold_standard"], result["eps_hj_closed_form"],
        )
        assert r["verdict"] == "PASS"
        assert r["reason"] == ""
        assert r["delta_gold_pct"] == pytest.approx(
            result["delta_vs_gold_pct"], abs=0.01)
        assert r["delta_hj_pct"] == pytest.approx(
            result["delta_vs_hj_pct"], abs=0.01)
        assert all((r["convergence_ok"], r["main_ok"], r["sub_ok"],
                    r["health_ok"]))

    def test_finest_tier_values_pinned(self):
        # 最细档（0.25mm）是复现锚本体：逐位钉死，防快照数值被静默改动
        result = _load()["result"]
        finest = next(e for e in result["entries"] if e["mesh_mm"] == 0.25)
        assert finest["eps_eff"] == 2.8813
        assert finest["delta_vs_gold_pct"] == -0.163
        assert finest["delta_vs_hj_pct"] == 1.005
        assert finest["s11_max_db"] == -32.23


class TestRescanAgainst189Backup:
    """对 #189 预扫备份的逐档复现一致性（升级/换机复现锚）。"""

    @staticmethod
    def _189_by_mesh() -> dict[float, float]:
        return {
            float(m): eps
            for m, eps in _load()["pre_rescan_189"]["eps_eff_by_mesh"]
        }

    def test_finest_tier_bit_identical_to_189(self):
        pre = self._189_by_mesh()
        result = _load()["result"]
        finest = next(e for e in result["entries"] if e["mesh_mm"] == 0.25)
        assert finest["eps_eff"] == pre[0.25] == 2.8813

    def test_per_tier_reproduction_within_3e_minus5(self):
        pre = self._189_by_mesh()
        for entry in _load()["result"]["entries"]:
            diff = abs(entry["eps_eff"] - pre[entry["mesh_mm"]])
            assert diff <= 3e-5, (
                f"mesh={entry['mesh_mm']} 对 #189 复现漂移 {diff:.2e} 超 3e-5："
                "openEMS 升级/换机后引擎基准漂移，须复核 harness 与模板面"
            )
