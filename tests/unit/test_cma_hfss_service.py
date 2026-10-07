"""cma_hfss_service 定向门（ge8c 席C7 CMA HFSS 原生档接口+mock 面）。

判据预声明：
1. H-M 恒等式锚：MS=1/(1+λ²)（Harrington–Mautz 1971 提法，与内核
   core/characteristic_modes.py 同式单源）——mock 行自洽、注入坏行
   （MS 手改）逐模 FAIL；
2. skipped≠failed 锚：runner=None → skipped 信封（能力未接线如实）；
3. mock 数字零物理断言（铁律 7）——只走接口链。
"""

from __future__ import annotations

import math

import pytest

from rfauto.service.cma_hfss_service import (
    CMA_HFSS_SCHEMA,
    MS_IDENTITY_RTOL,
    hfss_cma_summary,
    mock_hfss_cma_rows,
    parse_hfss_cma_rows,
    plan_hfss_cma,
    run_hfss_cma,
)


class TestPlanFace:
    def test_plan_ok_envelope(self):
        r = plan_hfss_cma(f_start_ghz=1.0, f_end_ghz=3.0, n_modes=6)
        assert r["ok"] is True and "skipped" not in r
        assert r["engine"] == "hfss_native_cma"
        assert r["setup"]["n_modes"] == 6
        assert r["schema"] == CMA_HFSS_SCHEMA

    @pytest.mark.parametrize("bad", [
        {"f_start_ghz": 3.0, "f_end_ghz": 1.0, "n_modes": 6},   # 倒置
        {"f_start_ghz": 0.0, "f_end_ghz": 1.0, "n_modes": 6},   # 非正
        {"f_start_ghz": 1.0, "f_end_ghz": 3.0, "n_modes": 0},   # 模数<1
        {"f_start_ghz": 1.0, "f_end_ghz": 3.0, "n_modes": True},  # bool 拒
        {"f_start_ghz": 1.0, "f_end_ghz": 3.0, "n_modes": 6,
         "max_delta_s": 1.5},                                    # ΔS 越界
    ])
    def test_plan_invalid_rejected(self, bad):
        r = plan_hfss_cma(**bad)
        assert r["ok"] is False and r["errors"]


class TestMockRowsAndParseGate:
    def test_mock_rows_hm_identity(self):
        rows = mock_hfss_cma_rows([0.0, 0.2, 1.0, -0.5])
        for row in rows:
            ms_id = 1.0 / (1.0 + row["eigenvalue"] ** 2)
            rel = abs(row["modal_significance"] - ms_id) / ms_id
            assert rel <= MS_IDENTITY_RTOL

    def test_parse_pass_envelope(self):
        r = parse_hfss_cma_rows(mock_hfss_cma_rows([0.0, 0.2, 1.0]))
        assert r["ok"] is True and r["n_modes"] == 3 and r["errors"] == []
        assert all(m["ms_gate"] == "PASS" for m in r["modes"])

    def test_inconsistent_ms_row_fails_per_mode(self):
        """MS 手改坏行：逐模 FAIL 登记，好行照常（#122/#316 多报方向）。"""
        rows = mock_hfss_cma_rows([0.0, 1.0])
        rows[0]["modal_significance"] = 0.5  # 真值 1.0——10^0 级不一致
        r = parse_hfss_cma_rows(rows)
        assert r["ok"] is False
        assert r["n_ms_fail"] == 1
        assert any("H-M 恒等式不一致" in e for e in r["errors"])
        assert r["modes"][1]["ms_gate"] == "PASS"  # 好行不受连坐

    def test_nonfinite_and_range_rejected(self):
        rows = [
            {"mode_index": 0, "eigenvalue": float("nan"),
             "modal_significance": 1.0},
            {"mode_index": 1, "eigenvalue": 0.1,
             "modal_significance": 1.5},  # 出 (0,1]
            "not-a-mapping",
        ]
        r = parse_hfss_cma_rows(rows)
        assert r["ok"] is False and len(r["errors"]) == 3

    def test_zc_passthrough_marked_different_basis(self):
        r = parse_hfss_cma_rows(mock_hfss_cma_rows([0.5]))
        zc = r["modes"][0]["zc"]
        assert zc["re"] == 1.0 and zc["im"] == 0.5
        assert "不同基" in zc["basis"]


class TestSummary:
    def test_ranking_ms_desc_and_near_resonant(self):
        parsed = parse_hfss_cma_rows(mock_hfss_cma_rows([1.0, 0.0, 0.2]))
        s = hfss_cma_summary(parsed)
        ranking = s["ranking_ms_desc"]
        assert [x["modal_significance"] for x in ranking] == \
            sorted((x["modal_significance"] for x in ranking), reverse=True)
        assert ranking[0]["mode_index"] == 1  # λ=0 → MS=1 最大
        assert s["near_resonant_mode_indices"] == [1, 2]  # |λ|≤0.2
        assert s["n_ms_fail"] == 0

    def test_fail_modes_excluded_from_ranking(self):
        rows = mock_hfss_cma_rows([0.0, 1.0])
        rows[0]["modal_significance"] = 0.1
        parsed = parse_hfss_cma_rows(rows)
        s = hfss_cma_summary(parsed)
        assert s["n_pass"] == 1
        assert [x["mode_index"] for x in s["ranking_ms_desc"]] == [1]


class TestRunFace:
    def test_runner_none_skipped_honest(self):
        plan = plan_hfss_cma(f_start_ghz=1.0, f_end_ghz=2.0, n_modes=4)
        r = run_hfss_cma(plan)
        assert r["ok"] is True and r["skipped"] is True
        assert "K-9" in r["reason"]

    def test_injected_mock_runner_full_chain(self):
        plan = plan_hfss_cma(f_start_ghz=1.0, f_end_ghz=2.0, n_modes=4)
        rows = mock_hfss_cma_rows([0.05, 0.3, 1.2])

        def fake_runner(p):
            assert p["engine"] == "hfss_native_cma"  # 契约：收计划
            return {"ok": True, "source": "mock_hfss_native", "rows": rows}

        r = run_hfss_cma(plan, runner=fake_runner)
        assert r["ok"] is True and "skipped" not in r
        assert r["source"] == "mock_hfss_native"
        assert r["parsed"]["n_modes"] == 3
        assert r["summary"]["near_resonant_mode_indices"] == [0]

    def test_runner_exception_translated(self):
        plan = plan_hfss_cma(f_start_ghz=1.0, f_end_ghz=2.0, n_modes=4)

        def boom(p):
            raise RuntimeError("ansysedt 不在场")

        r = run_hfss_cma(plan, runner=boom)
        assert r["ok"] is False
        assert "ansysedt 不在场" in r["errors"][0]

    def test_bad_plan_rejected_before_runner(self):
        def spy(p):  # pragma: no cover - 不应被调
            raise AssertionError("runner 不应被调")

        r = run_hfss_cma({"engine": "wrong"}, runner=spy)
        assert r["ok"] is False

    def test_identity_anchor_math(self):
        """恒等式独立复核（#118：判定式与被测链分离）：MS(λ=1)=0.5。"""
        assert math.isclose(1.0 / (1.0 + 1.0 ** 2), 0.5)
