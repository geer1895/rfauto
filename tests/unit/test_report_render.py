"""DP-13 U1 双输出报告链测试（typst PDF + plotly 自包含 HTML 同源双出）。

全部确定性：零网络、零真机、零 runs/ 写入（真实 run 只读 fixture；
合成 run 落 tmp_path）。判定式与实现同源：
:func:`rfauto.service.report_render.bare_number_fields` /
:func:`external_resource_refs` / :func:`fmt_value` / :func:`typ_escape`
（判据预声明 runs/df6_dp13u1/criteria.md §一/§二）。
"""

from __future__ import annotations

import html as html_mod
import json
from pathlib import Path

import pytest

from rfauto.core.vv_mapping import (
    VV_NOT_JUDGED,
    VV_NOT_VALIDATED,
    VV_VALIDATED,
)
from rfauto.service.report_render import (
    REPORT_SCHEMA,
    bare_number_fields,
    build_report_model,
    external_resource_refs,
    fmt_value,
    render_html,
    render_pdf,
    render_run_report,
    render_typ,
    resolve_evidence,
    typ_escape,
)

_WIN_FONTS = r"C:\Windows\Fonts"
_REAL_RUN = Path(__file__).resolve().parents[2] / "runs" / "ratrace_03mm_sample"

_SECTION_TITLES = ("标识引用", "方法配置", "数据与判据", "结论与异常")
_HTML_SECTION_IDS = (
    "sec-identification", "sec-method", "sec-criteria", "sec-conclusion")


# ── 合成 fixture 构造（全部写 tmp_path，只造确定性数据） ─────────────────────


def _make_sparams(run: Path) -> None:
    """2 端口小样：|S11|=0.1（-20dB）、|S21|≈0.7071（约 -3.01dB）。"""
    rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
    for i in range(5):
        f = 2.0 + 0.25 * i
        rows.append(f"{f * 1e9:.1f},0.06,0.08,0.5,0.5")  # |S11|=0.1 |S21|=sqrt(.5)
    (run / "sparams.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _make_meta(run: Path, template: str = "interdigital") -> None:
    (run / "meta.json").write_text(json.dumps({
        "template": template, "engine": "openems", "stage": "sample",
        "mesh_mm": 0.3, "n_ports": 2, "n_freq_points": 5,
        "freq_range_ghz": [2.0, 3.0], "reference_impedance": 50.0,
        "sub": {"er": 4.4, "h_mm": 1.6, "tan_d": 0.02},
    }, ensure_ascii=False), encoding="utf-8")


def _make_sentinel_verdict(run: Path) -> None:
    """镜像 runs/df5_c3fix/sentinel_verdict.json 的证据路径（合成小样）。"""
    (run / "sentinel_verdict.json").write_text(json.dumps({
        "schema": "df5_c3fix_sentinel_verdict/1",
        "run": {"template": "interdigital", "stage": "stage1"},
        "four_gates": {
            "dev_db": {"obs": 0.406, "max": 0.5, "ok": True},
            "holdout_rel": {"obs": 0.00502, "max": 0.05, "ok": True},
            "span_db": {"obs": 12.443, "min": 20.0, "ok": False},
            "s21_inf_f0_db": {"obs": -10.34, "min": -3.0, "ok": False},
        },
        "budget": {"declared": 12000, "actual": 15600},
        "mode_pair_verdict": {"verdict": "PASS"},
    }, ensure_ascii=False), encoding="utf-8")


def _make_full_run(tmp_path: Path) -> Path:
    run = tmp_path / "run_full"
    run.mkdir()
    _make_meta(run)
    _make_sparams(run)
    _make_sentinel_verdict(run)
    return run


def _make_degraded_run(tmp_path: Path) -> Path:
    run = tmp_path / "run_degraded"
    run.mkdir()
    _make_meta(run, template="mline")  # knowledge/criteria/v2 无 mline 判据
    return run


# ── 同源判定式与 d2 叶遍历 ──────────────────────────────────────────────────


def _leaf_strings(node, path="model", skip=frozenset({"freq_ghz", "values_db"})):
    """收集 (路径, 叶值)：str/bool/None/数值标量；跳过曲线浮点数组键。"""
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in skip:
                continue
            out += _leaf_strings(value, f"{path}.{key}", skip)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            out += _leaf_strings(item, f"{path}[{i}]", skip)
    else:
        out.append((path, node))
    return out


def _assert_leaf_in_both_products(model) -> tuple[str, str]:
    """d2：每个标量叶的 fmt_value 形态须在 .typ 源与 .html 源中在场。"""
    typ = render_typ(model)
    html = render_html(model)
    missing = []
    for path, leaf in _leaf_strings(model):
        shown = fmt_value(leaf)
        typ_hit = shown in typ or typ_escape(shown) in typ
        html_hit = shown in html or html_mod.escape(shown) in html
        if not (typ_hit and html_hit):
            missing.append((path, shown, typ_hit, html_hit))
    assert missing == [], f"叶值未同时进双产物: {missing[:8]}"
    return typ, html


# ── a 双产物四段齐备 ────────────────────────────────────────────────────────


class TestFourSections:
    def test_pdf_contains_four_sections_and_run_id(self, tmp_path):
        pytest.importorskip("typst")
        pytest.importorskip("pypdf")
        import pypdf

        model = build_report_model(_make_full_run(tmp_path), git_commit="feedface1234")
        pdf_path = tmp_path / "report.pdf"
        pdf_path.write_bytes(render_pdf(model))
        reader = pypdf.PdfReader(str(pdf_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        for title in _SECTION_TITLES:
            assert title in text, f"PDF 缺段标题: {title}"
        assert model["identification"]["run_id"] in text
        assert REPORT_SCHEMA in text

    def test_html_contains_four_sections_and_fields(self, tmp_path):
        model = build_report_model(_make_full_run(tmp_path), git_commit="feedface1234")
        html = render_html(model)
        for sec_id in _HTML_SECTION_IDS:
            assert f'id="{sec_id}"' in html
        for title in _SECTION_TITLES:
            assert title in html
        assert model["identification"]["run_id"] in html
        assert "criteria 状态" in html and "applied" in html
        # 对照表（合同级工件）逐列在场
        for col in ("指标", "阈值", "观测", "判定", "出处"):
            assert f"<th>{col}</th>" in html

    def test_real_run_fixture_both_products(self, tmp_path):
        """真实健康 run 只读 smoke：runs/ratrace_03mm_sample（存在才跑）。"""
        pytest.importorskip("typst")
        pytest.importorskip("pypdf")
        import pypdf

        if not _REAL_RUN.is_dir():
            pytest.skip("真实 fixture run 不在场（干净环境如实 skip）")
        model = build_report_model(_REAL_RUN, git_commit="real0run1fixt")
        pdf_path = tmp_path / "real.pdf"
        pdf_path.write_bytes(render_pdf(model))
        text = "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(str(pdf_path)).pages)
        for title in _SECTION_TITLES:
            assert title in text
        # 无 meta.json → template None → 判据如实 none-provided，不虚构
        assert model["criteria"]["status"] == "none-provided"
        assert model["criteria"]["rows"] == []
        assert model["curves"]["status"] == "ok"
        assert model["curves"]["n_traces"] == 4
        html = render_html(model)
        assert "none-provided" in html


# ── b PDF 中文正常渲染（CJK 豆腐块防回归） ──────────────────────────────────


@pytest.mark.skipif(not Path(_WIN_FONTS).is_dir(),
                    reason="typst font_paths 指系统字体，该目录缺失的环境如实 skip")
class TestChinesePdf:
    def test_pdf_text_contains_chinese_probes(self, tmp_path):
        pytest.importorskip("typst")
        pytest.importorskip("pypdf")
        import pypdf

        model = build_report_model(_make_full_run(tmp_path), git_commit="feedface1234")
        pdf_path = tmp_path / "cjk.pdf"
        pdf_path.write_bytes(render_pdf(model))
        text = "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(str(pdf_path)).pages)
        for probe in (*_SECTION_TITLES, "判据状态", "异常", "注记"):
            assert probe in text, f"PDF 中文探针缺失（CJK 豆腐块?）: {probe}"


# ── c HTML 零外网 ───────────────────────────────────────────────────────────


class TestHtmlOffline:
    def test_no_external_resource_refs_and_inline_plotly(self, tmp_path):
        model = build_report_model(_make_full_run(tmp_path), git_commit="feedface1234")
        html = render_html(model)
        assert external_resource_refs(html) == []
        assert "Plotly.newPlot" in html  # include_plotlyjs=True 全量内联
        assert len(html) > 1_000_000  # 内联体积 sanity（外链版只有几 KB）

    def test_detector_positive_control(self, tmp_path):
        """判定器正控：真外链资源标签必须被抓（裁判先过已知基准 #118）。"""
        model = build_report_model(_make_full_run(tmp_path), git_commit="x")
        html = render_html(model)
        bad = html.replace(
            "</body></html>",
            '<script src="https://cdn.example.com/x.js"></script>'
            "<img src='//evil.example/i.png'></body></html>")
        refs = external_resource_refs(bad)
        assert len(refs) == 2, refs
        # 非资源标签的锚点链接不是取回引用（须点击才离开页面），不误报
        anchor = html.replace("</body></html>",
                              '<a href="https://a.example">x</a></body></html>')
        assert external_resource_refs(anchor) == []


# ── d1 数字 100% provenance ─────────────────────────────────────────────────


class TestProvenance:
    def test_full_run_model_has_no_bare_numbers(self, tmp_path):
        model = build_report_model(_make_full_run(tmp_path), git_commit="x")
        assert bare_number_fields(model) == []
        # 抽查溯源键形态：判据行 source 指向 文件:json路径
        rows = {r["metric"]: r for r in model["criteria"]["rows"]}
        assert rows["dev_db"]["source"].startswith("sentinel_verdict.json:")
        assert rows["dev_db"]["source"].endswith("four_gates.dev_db.obs")

    def test_real_fixture_and_degraded_model_have_no_bare_numbers(self, tmp_path):
        if _REAL_RUN.is_dir():
            assert bare_number_fields(build_report_model(_REAL_RUN)) == []
        assert bare_number_fields(build_report_model(_make_degraded_run(tmp_path))) == []


# ── d2 同源：模型字段 100% 进双产物 ─────────────────────────────────────────


class TestSameSourceDualOutput:
    def test_all_scalar_leaves_in_both_products(self, tmp_path):
        model = build_report_model(_make_full_run(tmp_path), git_commit="feedface1234")
        typ, html = _assert_leaf_in_both_products(model)
        # 双产物互证：同一对照表行（指标+判定）两侧都在场（typ 下划线被转义）
        assert typ_escape("dev_db") in typ and "dev_db" in html
        assert "PASS" in typ and "FAIL" in typ and "PASS" in html and "FAIL" in html

    def test_renderers_do_not_read_run_dir(self, tmp_path, monkeypatch):
        """渲染器零二次采数：渲染期删除 run 目录，双产物照出（同源硬证据）。"""
        run = _make_full_run(tmp_path)
        model = build_report_model(run, git_commit="x")
        import shutil

        shutil.rmtree(run)
        typ = render_typ(model)
        html = render_html(model)
        assert "数据与判据" in typ and "数据与判据" in html
        assert len(html) > 1_000_000


# ── 判据对照表（v2 YAML 消费，只读） ────────────────────────────────────────


class TestCriteriaV2Consumption:
    def test_multi_gate_all_pass_rows_and_overall(self, tmp_path):
        """真 v2 判据（df5_c3fix_sentinel，只读）× 合成证据：逐门判定。"""
        model = build_report_model(_make_full_run(tmp_path), git_commit="x")
        crit = model["criteria"]
        assert crit["status"] == "applied"
        assert crit["criteria_id"] is not None
        assert "df5_c3fix" in crit["source"]
        rows = {r["metric"]: r for r in crit["rows"]}
        # 逐条「指标-阈值-出处-判定」
        assert rows["dev_db"]["judgment"] == "PASS"          # 0.406 ≤ 0.5
        assert rows["holdout_rel"]["judgment"] == "PASS"     # 0.00502 ≤ 0.05
        assert rows["span_db"]["judgment"] == "FAIL"         # 12.443 < 20
        assert rows["s21_inf_f0_db"]["judgment"] == "FAIL"   # -10.34 < -3.0
        assert "FAIL" in str(crit["overall"])
        assert VV_NOT_VALIDATED in str(crit["vv_status"])
        # 预算条件门：1.3 ≤ 1.5 不触发，不翻案四门 FAIL
        budget = rows["budget_ratio"]
        assert budget["judgment"] == "PASS"
        assert budget["observed"] == pytest.approx(1.3)

    def test_nearest_reference_gate_agree(self, tmp_path):
        """真 v2 判据（hfss M1，只读）× 合成证据：<setup> 通配 + 判向。"""
        run = tmp_path / "run_m1"
        run.mkdir()
        (run / "meta.json").write_text(json.dumps({"template": "interdigital"}))
        (run / "verdict.json").write_text(json.dumps({
            "curves": {"Setup1": {
                "conv": {"final_delta_s": 0.028, "max_delta_s": 0.05},
                "curve": {"s21_db_at_f0": 0.05, "passivity_max": 0.95},
            }},
        }))
        model = build_report_model(run, git_commit="x")
        crit = model["criteria"]
        assert crit["status"] == "applied"
        assert "AGREE_CIRCUIT" in str(crit["overall"])
        assert VV_VALIDATED in str(crit["vv_status"])
        rows = {r["metric"]: r for r in crit["rows"]}
        assert rows["|s21_db_at_f0-circuit|"]["judgment"] == "PASS"
        assert rows["|s21_db_at_f0-sentinel|"]["judgment"] == "FAIL"

    def test_missing_evidence_is_unknown_not_fabricated(self, tmp_path):
        """观测缺失→UNKNOWN（不虚构不凑，#105/#122）。"""
        run = tmp_path / "run_partial"
        run.mkdir()
        (run / "meta.json").write_text(json.dumps({"template": "interdigital"}))
        # 只放一半证据：dev_db 在、span_db 缺
        (run / "sentinel_verdict.json").write_text(json.dumps({
            "four_gates": {"dev_db": {"obs": 0.1}},
        }))
        model = build_report_model(run, git_commit="x")
        rows = {r["metric"]: r for r in model["criteria"]["rows"]}
        assert rows["dev_db"]["judgment"] == "PASS"
        assert rows["span_db"]["judgment"] == "UNKNOWN"
        assert rows["span_db"]["observed"] is None
        # 两份 interdigital 判据都适用：缺证据者如实 UNKNOWN，不虚构
        assert str(model["criteria"]["overall"]).startswith("UNKNOWN")
        assert VV_NOT_JUDGED in str(model["criteria"]["vv_status"])
        # 出处如实引到判据 yaml 自身（阈值/操作符出处），非空
        assert rows["span_db"]["source"]

    def test_no_matching_template_is_none_provided(self, tmp_path):
        model = build_report_model(_make_degraded_run(tmp_path), git_commit="x")
        crit = model["criteria"]
        assert crit["status"] == "none-provided"
        assert crit["rows"] == []
        assert any("none-provided" in n for n in crit["notes"])

    def test_resolve_evidence_wildcard_records_actual_path(self):
        docs = {"verdict.json": {"curves": {"Setup2": {"conv": {"final_delta_s": 0.028}}}}}
        value, source = resolve_evidence(docs, "curves.<setup>.conv.final_delta_s")
        assert value == 0.028
        assert source == "verdict.json:curves.Setup2.conv.final_delta_s"
        missing, empty_src = resolve_evidence(docs, "curves.<setup>.conv.not_there")
        assert missing is None and empty_src == ""


# ── e 缺产物降级不崩 ─────────────────────────────────────────────────────────


class TestDegradedRun:
    def test_degraded_run_builds_and_renders_both_products(self, tmp_path):
        pytest.importorskip("typst")
        run = _make_degraded_run(tmp_path)
        model = build_report_model(run, git_commit="x")
        # 如实降级标记
        assert model["method"]["status"] == "ok"  # 只有 meta.json，白名单键齐
        assert model["curves"]["status"] == "missing"
        assert model["criteria"]["status"] == "none-provided"
        assert model["conclusion"]["verdict"] == "UNKNOWN"
        assert model["conclusion"]["anomalies"], "异常清单不得为空（如实记录）"
        assert bare_number_fields(model) == []
        # 双产物照出不崩
        result = render_run_report(run, tmp_path / "out_degraded")
        assert result["ok"], result
        assert (tmp_path / "out_degraded" / "report.pdf").stat().st_size > 1000
        assert (tmp_path / "out_degraded" / "report.html").stat().st_size > 1000
        assert (tmp_path / "out_degraded" / "report.typ").is_file()
        html = (tmp_path / "out_degraded" / "report.html").read_text(encoding="utf-8")
        assert "none-provided" in html and "Plotly.newPlot" not in html  # 无曲线不画图

    def test_nonexistent_run_dir_is_clean_error(self, tmp_path):
        result = render_run_report(tmp_path / "no_such_run", tmp_path / "out")
        assert result["ok"] is False
        assert "不存在" in result["error"]


# ── f CLI 接线 ───────────────────────────────────────────────────────────────


class TestCliReportRender:
    def test_cli_render_writes_both_products(self, tmp_path):
        pytest.importorskip("typst")
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        run = _make_full_run(tmp_path)
        out = tmp_path / "cli_out"
        result = CliRunner().invoke(app, ["reports", "render", str(run),
                                          "--out-dir", str(out)])
        assert result.exit_code == 0, result.output
        assert (out / "report.pdf").stat().st_size > 1000
        assert (out / "report.html").stat().st_size > 1000

    def test_cli_render_json_and_failure(self, tmp_path):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        run = _make_full_run(tmp_path)
        result = CliRunner().invoke(app, ["reports", "render", str(run),
                                          "--out-dir", str(tmp_path / "o2"),
                                          "--json"])
        assert result.exit_code == 0
        assert '"criteria_status": "applied"' in result.output
        bad = CliRunner().invoke(app, ["reports", "render", str(tmp_path / "nope")])
        assert bad.exit_code == 1
