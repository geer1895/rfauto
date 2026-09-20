"""infra/visualization 单测（E5 孤岛补测试批次，Agg 后端离线出图）。"""

from __future__ import annotations

import base64

import matplotlib

matplotlib.use("Agg")  # 无显示环境

import numpy as np

from rfauto.infra.visualization import (
    generate_html_report,
    plot_optimization_convergence,
    plot_s_params,
)


def _sample_sparams(n: int = 64) -> tuple[np.ndarray, np.ndarray]:
    freq = np.linspace(1.0, 5.0, n)
    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = 0.2 * np.exp(1j * freq)
    s[:, 1, 0] = 0.7 * np.exp(-1j * freq)
    return freq, s


class TestPlotSParams:
    def test_save_to_file(self, tmp_path):
        freq, s = _sample_sparams()
        out = tmp_path / "s11.png"
        result = plot_s_params(freq, s, output_path=out)
        assert result == str(out)
        assert out.exists() and out.stat().st_size > 0

    def test_base64_fallback_without_path(self):
        freq, s = _sample_sparams(n=16)
        result = plot_s_params(freq, s, output_path=None)
        # 无输出路径时返回 base64 PNG
        base64.b64decode(result)  # 不抛错即合法
        assert len(result) > 100


class TestConvergence:
    def test_save_to_file(self, tmp_path):
        trials = [{"number": i, "cost": 3.0 - 0.05 * i + (i % 3) * 0.01}
                  for i in range(10)]
        out = tmp_path / "conv.png"
        plot_optimization_convergence(trials, output_path=out)
        assert out.exists()


class TestHtmlReport:
    def test_generates_sections(self, tmp_path):
        out = tmp_path / "report.html"
        html = generate_html_report(
            "测试报告",
            [
                {"title": "文本", "type": "text", "content": "hello"},
                {"title": "表格", "type": "table",
                 "headers": ["a", "b"], "rows": [[1, 2]]},
                {"title": "图", "type": "plot", "content": base64.b64encode(b"x").decode()},
            ],
            out,
        )
        assert out.exists()
        assert "测试报告" in html
        assert "<table>" in html
        assert "data:image/png;base64," in html
