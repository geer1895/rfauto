"""PDF 报告导出测试（FSV 验收 / 编排成本 / 叙述位 + 数值可溯）。

全部确定性：只落盘到 tmp_path，不触网、不碰真机、不引入新依赖（pypdf 为 dev extra）。
"""

from __future__ import annotations

import pypdf


def _extract(pdf_path):
    """读回 PDF：返回 (全文, PdfReader)。"""
    reader = pypdf.PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return text, reader


def _fsv_payload():
    """FSV 位：模拟 core/fsv.py 的评级结果（数值均为传入值，测试不新造）。"""
    return {
        "gdm_grade": "Very Good",
        "gdm_grade_level": 2,
        "gdm_spread": 1,
        "gdm_mean": 0.1357,
        "adm_grade": "Good",
        "fdm_mean_abs": 0.42,
        "n_points": 101,
    }


def _cost_rollup():
    """编排成本位：模拟 pipeline/quota_guard.py CostLedger.rollup() 表。"""
    totals = {
        "total_tokens": 424242.0,
        "solve_hours": 1.25,
        "seat_hours": 3.5,
        "gpu_hours": 0.0,
        "cost": 7.75,
    }
    return {
        "batch-001": {**totals, "actors": {"solver": dict(totals)}},
    }


class TestPdfExport:
    def test_export_writes_pdf_with_magic_and_pages(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(tmp_path, {"m": 1.0})
        assert path.name == "report.pdf"
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        assert len(data) > 0
        _, reader = _extract(path)
        assert len(reader.pages) >= 1

    def test_metrics_values_traceable(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(tmp_path, {"s11_min_db": -22.5, "bw_ghz": 1.25})
        text, _ = _extract(path)
        assert "s11_min_db: -22.5" in text
        assert "bw_ghz: 1.25" in text

    def test_fsv_grade_slot_written(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(tmp_path, {"m": 1.0}, fsv=_fsv_payload())
        text, _ = _extract(path)
        assert "FSV Validation" in text
        assert "gdm_grade: Very Good" in text
        assert "gdm_mean: 0.1357" in text
        assert "adm_grade: Good" in text
        assert "gdm_grade_level: 2" in text

    def test_cost_table_slot_written(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(tmp_path, {"m": 1.0}, cost_rollup=_cost_rollup())
        text, _ = _extract(path)
        assert "Orchestration Cost" in text
        assert "batch-001" in text
        assert "total_tokens" in text
        assert "424242.0" in text
        assert "1.25" in text
        assert "solver" in text

    def test_narrative_slot_written(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(
            tmp_path, {"m": 1.0}, narrative="narrative-42: all checks explained"
        )
        text, _ = _extract(path)
        assert "F9 Narrative" in text
        assert "narrative-42: all checks explained" in text

    def test_narrative_none_is_placeholder(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(tmp_path, {"m": 1.0})
        text, _ = _extract(path)
        assert "F9 Narrative" in text
        assert "(not provided)" in text

    def test_unpassed_number_absent_from_pdf(self, tmp_path):
        """渲染层不得生成新数字：未传入的数值串不应出现。"""
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(
            tmp_path, {"s11_min_db": -22.5}, fsv={"gdm_grade": "Good"}
        )
        text, _ = _extract(path)
        assert "-22.5" in text
        assert "987654321.5" not in text

    def test_multi_page_when_many_metrics(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        metrics = {f"metric_{i:03d}": i for i in range(80)}
        path = export_report_pdf(tmp_path, metrics)
        _, reader = _extract(path)
        assert len(reader.pages) >= 2

    def test_existing_figure_embedded_adds_page(self, tmp_path):
        from rfauto.infra.report import export_report_pdf, plot_s11

        figs_dir = tmp_path / "results" / "figs"
        ref = plot_s11([1e9, 2e9, 3e9], [-10.0, -20.0, -30.0], figs_dir)
        assert (tmp_path / ref).exists()
        sections = {"metrics": [("m", 1.0)], "figures": [("S11 Curve", ref)]}
        path = export_report_pdf(tmp_path, sections=sections)
        text, reader = _extract(path)
        assert len(reader.pages) >= 2
        assert ref in text

    def test_missing_figure_degrades_without_error(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        sections = {
            "metrics": [("m", 1.0)],
            "figures": [("Ghost", "results/figs/does_not_exist.png")],
        }
        path = export_report_pdf(tmp_path, sections=sections)
        text, reader = _extract(path)
        assert len(reader.pages) >= 1
        assert "results/figs/does_not_exist.png" in text

    def test_empty_sections_robust(self, tmp_path):
        from rfauto.infra.report import export_report_pdf

        path = export_report_pdf(tmp_path, sections={})
        text, reader = _extract(path)
        assert len(reader.pages) >= 1
        assert "Metrics" in text
        assert "(none)" in text

    def test_scalar_passthrough_no_reformat(self):
        """可溯性：渲染层只 str() 原值，不重格式化、不做算术。"""
        from rfauto.infra.report import _scalar_text

        assert _scalar_text(-22.5) == "-22.5"
        assert _scalar_text(0.1357) == "0.1357"
        assert _scalar_text(2) == "2"
        assert _scalar_text("Very Good") == "Very Good"

    def test_render_layer_has_no_llm_or_network_client(self):
        """F9 位只是文本占位：infra/report.py 不得引入任何 LLM/网络客户端。"""
        import inspect

        from rfauto.infra import report

        source = inspect.getsource(report)
        for marker in ("import openai", "import requests", "anthropic", "urllib.request"):
            assert marker not in source

