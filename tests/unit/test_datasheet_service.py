"""EP-4 datasheet 生成器单测（service/datasheet_service，PR-4 链复用面）。

裁判独立性：PR-4 复用面用真实 ``build_report_model``（tmp run 目录最小
meta.json）端到端；裸数字 provenance 用 PR-4 判定式 ``bare_number_fields``
（复用本体，不复制逻辑）；HTML 转义用注入探针。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service import datasheet_service as ds
from rfauto.service.report_render import bare_number_fields, build_report_model

_META = {
    "template": "patch",
    "topology": "矩形贴片（patch_len = 谐振 λ/2 轴）+ 边缘微带馈电",
    "f0_ghz": 2.4,
    "substrate": {"er": 3.66, "h_mm": 0.508},
    "nominal_params": {"patch_len_mm": 34.9, "patch_w_mm": 50.0, "feed_offset_mm": 10.0},
}


def _fake_report() -> dict:
    """手工最小 rfauto-report/v1 模型（每数值节点带 source，同 PR-4 纪律）。"""
    return {
        "schema": "rfauto-report/v1",
        "identification": {
            "source": "tmp/run1",
            "run_id": "run1",
            "run_dir": "tmp/run1",
            "generated_at": "2026-10-03T00:00:00+08:00",
            "git_commit": "deadbeef",
            "artifacts": [],
        },
        "method": {
            "source": "meta.json",
            "status": "ok",
            "template": "patch",
            "fields": [
                {"name": "f0_ghz", "value": 2.42, "unit": "GHz", "source": "result.json:f0_ghz"},
            ],
        },
        "criteria": {"status": "none-provided", "source": "none:missing"},
        "conclusion": {
            "source": "verdict.json:verdict",
            "verdict": "PASS",
            "vv_status": "pass",
            "vv_basis": "map_verdict",
            "gates_pass": [],
            "gates_fail": [],
            "criteria_overall": None,
            "anomalies": [],
        },
        "curves": {
            "source": "tmp/run1/sparams.csv",
            "status": "missing",
            "freq_ghz": [],
            "traces": [],
            "n_points": 0,
            "n_traces": 0,
            "note": "",
        },
    }


class TestBuildDatasheet:
    def test_meta_only_model(self):
        m = ds.build_datasheet(part_number="RF-PATCH-2G4", template="patch", meta=_META)
        assert m["schema"] == "rfauto-datasheet/v1"
        assert "非厂商 datasheet" in m["disclaimer"]
        params = {r["param"]: r for r in m["electrical"]["rows"]}
        assert params["patch_len_mm"]["source"] == "docs/templates/patch/meta.yaml"
        assert params["substrate.er"]["unit"] == ""
        assert params["f0_ghz"]["unit"] == "GHz"
        # 裸数字=0（PR-4 provenance 判定式复用本体）
        assert bare_number_fields(m) == []
        # 机械尺寸=mm 行
        assert all(r["unit"] == "mm" for r in m["mechanical"]["rows"])
        assert "patch_len_mm" in {r["param"] for r in m["mechanical"]["rows"]}

    def test_report_passthrough_rows_and_verdict(self):
        rep = _fake_report()
        m = ds.build_datasheet(part_number="P1", template="patch", meta=_META, report=rep)
        rows = {r["param"]: r for r in m["electrical"]["rows"]}
        assert rows["f0_ghz"]["value"] == 2.42
        assert rows["f0_ghz"]["source"] == "result.json:f0_ghz"
        assert rows["run_verdict"]["value"] == "PASS"
        assert any("run1" in s for s in m["sources"])

    def test_real_build_report_model_integration(self, tmp_path):
        # PR-4 全链端到端：tmp run 目录（最小 meta.json）→ build_report_model → datasheet
        run = tmp_path / "run_smoke"
        run.mkdir()
        (run / "meta.json").write_text(
            json.dumps({"template": "patch", "params": {"patch_len_mm": 34.9}}),
            encoding="utf-8",
        )
        rep = build_report_model(run)
        m = ds.build_datasheet(part_number="P2", template="patch", meta=_META, report=rep)
        assert bare_number_fields(m) == []
        # 曲线缺产物如实降级（sparams.csv 不在场）
        assert m["curves"]["status"] == "missing"

    def test_typical_application_source_required(self):
        with pytest.raises(ValueError, match="source"):
            ds.build_datasheet(
                part_number="P", template="patch",
                typical_application={"text": "2.4 GHz 星型拓扑供电支路"},
            )
        m = ds.build_datasheet(
            part_number="P", template="patch",
            typical_application={"text": "2.4 GHz 支路", "source": "docs/templates/patch/meta.yaml"},
        )
        assert m["typical_application"]["source"] == "docs/templates/patch/meta.yaml"

    def test_field_refs_and_notes_and_guards(self):
        m = ds.build_datasheet(
            part_number="P", template="patch", meta=_META,
            field_plot_refs=[{"name": "ez@f0", "path": "runs/x/ez.png"}],
            notes=["未冒烟（离线审计过）"],
        )
        assert m["field_plot_refs"][0]["name"] == "ez@f0"
        assert m["notes"] == ["未冒烟（离线审计过）"]
        with pytest.raises(ValueError, match="part_number"):
            ds.build_datasheet(part_number="", template="patch")
        with pytest.raises(ValueError, match=r"field_plot_refs\.name"):
            ds.build_datasheet(part_number="P", template="patch",
                               field_plot_refs=[{"path": "a.png"}])


class TestRenderers:
    def test_markdown_sections(self):
        m = ds.build_datasheet(
            part_number="RF-PATCH-2G4", template="patch", meta=_META,
            typical_application={"text": "2.4 GHz 支路馈电", "source": "meta"},
        )
        md = ds.render_markdown(m)
        assert md.startswith("# 规格书：RF-PATCH-2G4")
        for section in ("## 电气规格", "## S 参数曲线", "## 典型应用", "## 机械尺寸", "## 来源清单"):
            assert section in md
        assert "非厂商 datasheet" in md
        assert "| f0_ghz | 2.4 | GHz |" in md

    def test_html_escapes_injection(self):
        m = ds.build_datasheet(
            part_number="<script>alert(1)</script>", template="patch", meta=_META,
        )
        html = ds.render_html(m)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html
        assert m["disclaimer"] in html  # 免责声明原文在场（中文不被转义破坏）

    def test_html_curves_missing_note(self):
        m = ds.build_datasheet(part_number="P", template="patch")
        html = ds.render_html(m)
        assert "曲线缺失" in html
        assert "plotly" not in html.split("曲线缺失")[1].split("</p>")[0]

    def test_json_roundtrip(self):
        m = ds.build_datasheet(part_number="P", template="patch", meta=_META)
        blob = json.loads(json.dumps(m, ensure_ascii=False))
        assert ds.render_markdown(blob) == ds.render_markdown(m)
