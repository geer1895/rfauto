"""F9 设计报告叙述生成器测试（数字白名单 + provenance，§10.6 F9）。

确定性、无网络：LLM 只作可注入接口，测试用 monkeypatch 钉住通道（#139）；
run 产物用 tmp_path 自造，不依赖工作区 runs/。
"""

from __future__ import annotations

import json

import pytest

from rfauto.service import report_narrative as rn

DET = {
    "model": "wilkinson_power_divider",
    "adapter": "fake",
    "metrics": {
        "s11_db_max_in_band": -11.332246035022575,
        "s21_db_mean_in_band": -3.8164830122541265,
    },
}
UNITS = {
    "metrics.s11_db_max_in_band": "dB",
    "metrics.s21_db_mean_in_band": "dB",
}
S11 = -11.332246035022575


def _wl():
    return rn.build_whitelist(DET, source="det", units=UNITS)


# ─── 白名单构建（含 provenance） ─────────────────────────────────────────────


class TestBuildWhitelist:
    def test_extracts_nested_numbers_with_provenance(self):
        wl = _wl()
        by_label = {e.label: e for e in wl.entries}
        assert set(by_label) == {"metrics.s11_db_max_in_band", "metrics.s21_db_mean_in_band"}
        e = by_label["metrics.s11_db_max_in_band"]
        assert e.value == pytest.approx(S11)
        assert e.unit == "dB"
        assert e.source == "det:metrics.s11_db_max_in_band"
        assert e.canonical() == f"{S11} dB"

    def test_skips_bool_none_nonfinite_and_strings(self):
        wl = rn.build_whitelist(
            {
                "flag": True,
                "none": None,
                "n": 3,
                "name": "wilkinson",
                "nan": float("nan"),
                "inf": float("inf"),
            }
        )
        assert [e.label for e in wl.entries] == ["n"]

    def test_units_attached_by_label(self):
        wl = rn.build_whitelist({"freqs": {"center": 2.4}}, units={"freqs.center": "GHz"})
        assert wl.entries[0].unit == "GHz"
        assert wl.entries[0].canonical() == "2.4 GHz"

    def test_list_index_labels_are_number_safe(self):
        wl = rn.build_whitelist(
            {"freqs": [2.4, 2.5]},
            source="det",
            units={"freqs.0": "GHz", "freqs.1": "GHz"},
        )
        assert [e.label for e in wl.entries] == ["freqs.0", "freqs.1"]
        text = rn.render_template_narrative({"freqs": [2.4, 2.5]}, wl, source="det")
        assert rn.check_narrative(text, wl).ok
        assert len(rn.extract_numbers(text)) == 2

    def test_run_meta_whitelist_has_run_provenance(self, tmp_path):
        run_dir = tmp_path / "runs" / "20260101_120000_abcd1234"
        run_dir.mkdir(parents=True)
        meta = {
            "run_id": "20260101_120000_abcd1234",
            "model": "wilkinson_power_divider",
            "metrics": {"s11_db_max_in_band": S11},
        }
        (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        wl = rn.build_whitelist_from_run(run_dir, units={"metrics.s11_db_max_in_band": "dB"})
        assert len(wl) == 1
        e = wl.entries[0]
        assert e.value == pytest.approx(S11)
        assert e.unit == "dB"
        assert e.source == "runs/20260101_120000_abcd1234/meta.json:metrics.s11_db_max_in_band"

    def test_run_meta_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            rn.build_whitelist_from_run(tmp_path / "no_such_run")


# ─── 数字抽取（边界守卫 + 单位） ─────────────────────────────────────────────


class TestExtractNumbers:
    def test_values_and_units(self):
        occ = rn.extract_numbers("回损 -11.33 dB，带宽 2.4GHz，步长 1e-3 mm。")
        assert [o.value for o in occ] == pytest.approx([-11.33, 2.4, 0.001])
        assert [o.unit for o in occ] == ["dB", "GHz", "mm"]

    def test_identifiers_not_counted(self):
        text = "S11 与 s21_db_mean_in_band、F9/D12 版本 v3.12，run 20260101_120000_abcd1234"
        assert rn.extract_numbers(text) == ()

    def test_non_string_raises(self):
        with pytest.raises(TypeError):
            rn.extract_numbers(None)


# ─── 叙述校验 / 净化（授权通过、未授权拒绝） ─────────────────────────────────


class TestCheckNarrative:
    def test_authorized_number_passes_with_provenance(self):
        res = rn.check_narrative(f"带内回损约 {S11} dB。", _wl())
        assert res.ok
        assert not res.violations
        assert len(res.provenance) == 1
        p = res.provenance[0]
        assert p.source == "det:metrics.s11_db_max_in_band"
        assert p.value == pytest.approx(S11)
        assert p.unit == "dB"

    def test_unauthorized_number_rejected_and_located(self):
        wl = _wl()
        text = f"回损 {S11} dB，插损 5.6 dB"
        res = rn.check_narrative(text, wl)
        assert res.ok is False
        assert [v.value for v in res.violations] == [5.6]
        v = res.violations[0]
        assert text[v.start : v.end] == "5.6"
        assert v.reason == "unauthorized"
        assert res.provenance[0].source == "det:metrics.s11_db_max_in_band"

    def test_unit_mismatch_rejected(self):
        wl = rn.NumberWhitelist((rn.NumberEntry(value=2.4, unit="GHz", source="core:synthesis"),))
        res = rn.check_narrative("线宽 2.4 mm", wl)
        assert res.ok is False
        assert res.violations[0].reason == "unit_mismatch"

    def test_canonicalization_and_unit_injection(self):
        wl = rn.NumberWhitelist(
            (rn.NumberEntry(value=2.4, unit="GHz", source="core:synthesis", label="f_ghz"),)
        )
        res = rn.check_narrative("中心频率 2.4 附近。", wl)
        assert res.ok
        assert res.text == "中心频率 2.4 GHz 附近。"
        p = res.provenance[0]
        assert p.source == "core:synthesis"
        assert res.text[p.start : p.end] == "2.4 GHz"

    def test_tolerance_accepts_rounded_and_refills_kernel_value(self):
        strict = rn.NumberWhitelist((rn.NumberEntry(value=2.4701, unit="GHz", source="hfss:run"),))
        assert rn.check_narrative("谐振 2.47 GHz", strict).ok is False
        tolerant = rn.NumberWhitelist(
            (rn.NumberEntry(value=2.4701, unit="GHz", source="hfss:run", rel_tol=1e-3),)
        )
        res = rn.check_narrative("谐振 2.47 GHz", tolerant)
        assert res.ok
        assert res.provenance[0].value == pytest.approx(2.4701)
        assert "2.4701 GHz" in res.text

    def test_exact_preferred_over_tolerance(self):
        wl = rn.NumberWhitelist(
            (
                rn.NumberEntry(value=2.47, unit="GHz", source="loose", rel_tol=1e-2),
                rn.NumberEntry(value=2.4701, unit="GHz", source="exact"),
            )
        )
        entry = wl.match(2.4701, "GHz")
        assert entry is not None
        assert entry.source == "exact"

    def test_empty_text_ok(self):
        assert rn.check_narrative("", rn.NumberWhitelist()).ok is True

    def test_non_string_text_raises(self):
        with pytest.raises(TypeError):
            rn.check_narrative(None, rn.NumberWhitelist())

    def test_repeated_calls_are_identical(self):
        wl = _wl()
        assert rn.check_narrative(f"{S11} dB", wl).to_dict() == rn.check_narrative(f"{S11} dB", wl).to_dict()


# ─── 模板回退（确定性、数字全来自白名单） ───────────────────────────────────


class TestTemplate:
    def test_template_deterministic_and_traceable(self):
        wl = _wl()
        t1 = rn.render_template_narrative(DET, wl, source="runs/RID/meta.json")
        t2 = rn.render_template_narrative(DET, wl, source="runs/RID/meta.json")
        assert t1 == t2
        res = rn.check_narrative(t1, wl)
        assert res.ok
        occurrences = rn.extract_numbers(t1)
        assert len(occurrences) == 2
        assert len(res.provenance) == len(occurrences)
        for p in res.provenance:
            assert p.source.startswith("det:")
            assert float(t1[p.start : p.end].split()[0]) == pytest.approx(p.value)

    def test_generate_without_llm_uses_template(self):
        g1 = rn.generate_narrative(DET, units=UNITS, source="det")
        g2 = rn.generate_narrative(DET, units=UNITS, source="det")
        assert g1.ok and g1.used_template
        assert g2.ok and g2.used_template
        assert g1.narrative == g2.narrative
        assert g1.to_dict() == g2.to_dict()

    def test_template_without_metrics_is_number_free(self):
        res = rn.generate_narrative({"model": "patch_antenna", "adapter": "openems"}, source="det")
        assert res.ok and res.used_template
        assert rn.extract_numbers(res.narrative) == ()

    def test_template_source_guard_blocks_unsafe_source(self):
        wl = _wl()
        text = rn.render_template_narrative(DET, wl, source="runs/2026/meta.json")
        assert "2026" not in text
        res = rn.check_narrative(text, wl)
        assert res.ok
        assert len(res.provenance) == 2


# ─── LLM 注入接口（monkeypatch 钉住，不触网） ────────────────────────────────


class TestLlmInjection:
    def test_default_llm_is_none_template_path(self):
        assert rn._DEFAULT_LLM is None
        assert rn.generate_narrative(DET, units=UNITS).used_template is True

    def test_monkeypatched_default_llm_used_and_pinned(self, monkeypatch):
        calls: list[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return f"结论：带内回损为 {S11} dB。"

        monkeypatch.setattr(rn, "_DEFAULT_LLM", fake_llm)
        res = rn.generate_narrative(DET, units=UNITS, source="det")
        assert len(calls) == 1
        assert res.ok and res.used_template is False
        assert f"{S11} dB" in res.narrative
        assert "metrics.s11_db_max_in_band" in calls[0]
        assert "det:metrics.s11_db_max_in_band" in calls[0]

    def test_explicit_llm_authorized_number_ok(self):
        def good(prompt: str) -> str:
            return f"带内回损 {S11} dB。"

        res = rn.generate_narrative(DET, units=UNITS, llm_fn=good, source="det")
        assert res.ok and res.used_template is False
        assert res.provenance[0].source == "det:metrics.s11_db_max_in_band"

    def test_explicit_llm_unauthorized_rejected(self):
        def bad(prompt: str) -> str:
            return "插损为 5.6 dB。"

        res = rn.generate_narrative(DET, units=UNITS, llm_fn=bad, source="det")
        assert res.ok is False
        assert res.used_template is False
        assert [v.value for v in res.violations] == [5.6]
        assert res.narrative == "插损为 5.6 dB。"

    def test_unauthorized_falls_back_to_template(self):
        def bad(prompt: str) -> str:
            return "插损为 5.6 dB。"

        res = rn.generate_narrative(
            DET, units=UNITS, llm_fn=bad, source="det", on_unauthorized="fallback"
        )
        assert res.ok and res.used_template
        assert res.fallback_reason == "unauthorized_numbers"
        assert [v.value for v in res.violations] == [5.6]
        assert rn.check_narrative(res.narrative, res.whitelist).ok

    def test_invalid_llm_output_falls_back(self):
        for output in ("", "   ", None, 123):
            res = rn.generate_narrative(
                DET, units=UNITS, llm_fn=lambda prompt, _o=output: _o, source="det"
            )
            assert res.ok and res.used_template
            assert res.fallback_reason == "invalid_llm_output"

    def test_extra_entries_extend_whitelist(self):
        extra = rn.NumberEntry(value=50.0, unit="ohm", source="core:synthesis", label="z0")
        res = rn.generate_narrative(
            DET,
            units=UNITS,
            llm_fn=lambda prompt: "端口阻抗 50 ohm。",
            extra_entries=[extra],
            source="det",
        )
        assert res.ok
        assert res.provenance[0].source == "core:synthesis"

    def test_bad_on_unauthorized_value_raises(self):
        with pytest.raises(ValueError):
            rn.generate_narrative(DET, on_unauthorized="ignore")


# ─── JSON 审计报告（服务层 JSON 进出） ───────────────────────────────────────


class TestAuditJson:
    def test_audit_narrative_json_safe(self):
        report = rn.audit_narrative(f"回损 {S11} dB，插损 5.6 dB", _wl())
        assert report["ok"] is False
        assert report["n_numbers"] == 2
        assert report["n_authorized"] == 1
        assert report["violations"][0]["text"] == "5.6"
        json.dumps(report, ensure_ascii=False)
